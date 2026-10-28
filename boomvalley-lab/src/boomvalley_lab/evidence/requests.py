"""Request content in an evidence package (#76 D): `request_content_status`.

The request a record sent need not be published. What the package states about
it is one of three statuses, never a mixture:

    AVAILABLE    the exact request bytes are members (`requests/record-NNNNNN.json`);
                 each hashes to its intent's `request` and has the stated size
    WITHHELD     the request existed and is deliberately not published: no request
                 member, and for every intent its digest (= the intent's `request`,
                 the RequestIdentity the journal binds), its size and one closed
                 reason_code. The content is never written to the package, a log,
                 stdout or stderr
    UNAVAILABLE  the request was not retained or cannot be obtained: a closed
                 reason_code, no request member and no digest - a digest nobody holds
                 the bytes of is never made up

canonical-json-1 has no null (an absent value is an absent member), so each status
has exactly one closed shape - a member that does not belong to the status is a
contradiction, never "empty":

    AVAILABLE    {"request_content_status", "requests": [{"record", "position",
                                                          "digest", "size", "member"}]}
    WITHHELD     {"request_content_status", "reason_code",
                  "requests": [{"record", "position", "digest", "size"}]}
    UNAVAILABLE  {"request_content_status", "reason_code"}

A request entry's `digest` is its content digest (`sha256:<64 hex>`, the raw-byte
SHA-256 of the request) and `size` its content size in bytes: for WITHHELD they
are the binding of content that is not published.

A reason code establishes exactly one status (`REASONS`). UNAVAILABLE is the
state of a run whose request builder was never recorded (a legacy
NOT_INPUT_LOCKED run); an INPUT_LOCKED run can always rebuild its requests, so
for it only AVAILABLE or WITHHELD mean something.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

AVAILABLE = "AVAILABLE"
WITHHELD = "WITHHELD"
UNAVAILABLE = "UNAVAILABLE"
STATUSES = (AVAILABLE, WITHHELD, UNAVAILABLE)

#: reason_code -> the one status it establishes (the closed vocabulary)
REASONS: dict[str, str] = {
    "REQUEST_WITHHELD_CONFIDENTIAL": WITHHELD,
    "REQUEST_WITHHELD_PERSONAL_DATA": WITHHELD,
    "REQUEST_WITHHELD_LICENSE_RESTRICTED": WITHHELD,
    "REQUEST_BUILDER_NOT_RECORDED": UNAVAILABLE,
}

#: `bvl package --withhold-requests <choice>` -> reason_code
WITHHOLD_CHOICES = {"CONFIDENTIAL": "REQUEST_WITHHELD_CONFIDENTIAL",
                    "PERSONAL_DATA": "REQUEST_WITHHELD_PERSONAL_DATA",
                    "LICENSE_RESTRICTED": "REQUEST_WITHHELD_LICENSE_RESTRICTED"}

#: the package limitation each non-AVAILABLE status states
LIMITATION = {WITHHELD: "REQUEST_CONTENT_WITHHELD", UNAVAILABLE: "REQUEST_UNAVAILABLE"}

#: status -> the closed member set of its request_content document
SHAPES: dict[str, frozenset[str]] = {
    AVAILABLE: frozenset({"request_content_status", "requests"}),
    WITHHELD: frozenset({"request_content_status", "reason_code", "requests"}),
    UNAVAILABLE: frozenset({"request_content_status", "reason_code"}),
}
#: status -> the closed member set of one request entry
ENTRY_SHAPES: dict[str, frozenset[str]] = {
    AVAILABLE: frozenset({"record", "position", "digest", "size", "member"}),
    WITHHELD: frozenset({"record", "position", "digest", "size"}),
}
_HEX = set("0123456789abcdef")


def member_path(position: int) -> str:
    return f"requests/record-{position:06d}.json"


def is_digest(value: Any) -> bool:
    """`sha256:` + 64 lowercase hex: the one form a content digest has."""
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71 \
        and set(value[7:]) <= _HEX


def status_message_key(status: str) -> str:
    return f"request_content.status.{status}"


def reason_message_key(code: str) -> str:
    return f"request_content.reason.{code}"


def reading(status: str | None, reason_code: str | None, requests: int | None) -> dict:
    """What a verifier / `bvl package` reports about request content: codes for machines,
    `message_key + params` for the human text (`core.i18n`). Never the content itself."""
    out: dict[str, Any] = {"request_content_status": status}
    if status in STATUSES:
        out["message_key"] = status_message_key(status)
        out["params"] = {"requests": requests} if requests is not None else {}
    if reason_code in REASONS:
        out["reason"] = {"reason_code": reason_code,
                         "message_key": reason_message_key(reason_code), "params": {}}
    return out


def read(content: Any) -> dict:
    """`reading` of a manifest's request_content (whatever it claims; REQ-001 judges it)."""
    if not isinstance(content, dict):
        return reading(None, None, None)
    status = content.get("request_content_status")
    requests = content.get("requests")
    return reading(status if status in STATUSES else None, content.get("reason_code"),
                   len(requests) if isinstance(requests, list) else None)


def document(status: str, reason_code: str | None,
             entries: Sequence[Mapping] | None) -> dict:
    if (reason_code is None) != (status == AVAILABLE) or \
            (reason_code is not None and REASONS[reason_code] != status) or \
            (entries is None) != (status == UNAVAILABLE):
        raise ValueError(f"request content {status} with reason {reason_code!r}")
    content: dict[str, Any] = {"request_content_status": status}
    if reason_code is not None:
        content["reason_code"] = reason_code
    if entries is not None:
        content["requests"] = [dict(e) for e in entries]
    return content


def entry(record: str, position: int, digest: str, size: int, *, published: bool) -> dict:
    item = {"record": record, "position": position, "digest": digest, "size": size}
    if published:
        item["member"] = member_path(position)
    return item


def problems(content: Any, *, intents: Sequence[Mapping], held: Mapping[str, bytes],
             listed: set[str], locked: bool, limitations: Sequence[str],
             sha) -> list[str]:
    """What is wrong with a package's request content claim (fail-closed).

    `intents` are the journal's INTENT_RECORDED events (record, position, request);
    `held` maps member path -> bytes; `listed` is every path with role `request`;
    `sha(bytes) -> "sha256:<hex>"` is the caller's digest (the consumer brings its own).
    """
    if not isinstance(content, dict):
        return ["request_content is not an object"]
    status = content.get("request_content_status")
    if status not in STATUSES:
        return [f"request_content_status {status!r} is not registered"]
    if set(content) != SHAPES[status]:
        return [f"{status} request_content is not {sorted(SHAPES[status])} "
                f"(has {sorted(set(content))})"]
    code, requests = content.get("reason_code"), content.get("requests")
    found = []
    if status != AVAILABLE:
        if code not in REASONS:
            found.append(f"{status} request content without a registered reason_code ({code!r})")
        elif REASONS[code] != status:
            found.append(f"reason_code {code} is a {REASONS[code]} reason, not {status}: "
                         "WITHHELD and UNAVAILABLE are never mixed")
    for other, limitation in LIMITATION.items():
        if (limitation in limitations) != (status == other):
            state = "listed" if limitation in limitations else "missing"
            found.append(f"limitation {limitation} {state} for {status} request content")
    if status == UNAVAILABLE:
        if listed:
            found.append(f"UNAVAILABLE request content with request members {sorted(listed)}")
        if locked:
            found.append("an INPUT_LOCKED run can rebuild its requests: UNAVAILABLE is not "
                         "its state")
        return found
    if not isinstance(requests, list):
        return [*found, f"{status} request content has no request list"]
    by_position = {i["position"]: i for i in intents}
    seen = set()
    for index, item in enumerate(requests):
        where = f"requests[{index}]"
        if not isinstance(item, dict) or set(item) != ENTRY_SHAPES[status]:
            found.append(f"{where} is not a {status} entry {sorted(ENTRY_SHAPES[status])}")
            continue
        position = item["position"]
        intent = by_position.get(position) \
            if isinstance(position, int) and not isinstance(position, bool) else None
        if intent is None or item["record"] != intent["record"]:
            found.append(f"{where} names no recorded intent")
            continue
        seen.add(position)
        if not is_digest(item["digest"]) or item["digest"] != intent["request"]:
            found.append(f"{where}: digest is not the request its intent recorded")
        if not isinstance(item["size"], int) or isinstance(item["size"], bool) \
                or item["size"] < 1:
            found.append(f"{where}: size is not a positive byte count")
        if status == WITHHELD:
            continue
        if item["member"] != member_path(position):
            found.append(f"{where}: member {item['member']!r}")
            continue
        data = held.get(item["member"])
        if data is None or sha(data) != item["digest"] or len(data) != item["size"]:
            found.append(f"{item['member']} is not the listed request bytes")
    positions = [i.get("position") for i in requests if isinstance(i, dict)]
    if positions != sorted(by_position) or seen != set(by_position):
        found.append("the request list is not one entry per intent, in position order")
    expected = {member_path(p) for p in by_position} if status == AVAILABLE else set()
    if listed != expected:
        found.append(f"request members {sorted(listed ^ expected)} "
                     + ("missing or extra" if status == AVAILABLE
                        else "published although WITHHELD"))
    return found
