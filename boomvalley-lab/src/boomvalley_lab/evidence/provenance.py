"""Producer provenance in an evidence package (#87, C1 C2a): two trust classes.

`provenance/producer.json` states what produced the evidence. Its items are not
equally trustworthy, and `boomvalley-epc-producer-2` says which is which:

    self_reported_provenance  what the producer, an adapter or a tool says of itself.
                              A reader can check it is well formed and that it restates
                              the sealed evidence where the evidence holds it; it can
                              never check that it is TRUE. It is never a verified claim.
    verified_provenance       what a reader recomputes from the package bytes alone
                              (a member digest, a digest the Input Lock binds). Both
                              readers recompute every entry; a mismatch is refused.

    { "schema": "boomvalley-epc-producer-2",
      "self_reported_provenance": [entry, ...],   sorted by field, unique
      "verified_provenance":      [entry, ...] }  sorted by field, unique
    entry = {"field", "trust_class", "basis", "value"}

`FIELDS` is closed: every field has exactly one trust class and one basis. A field
in the other section, a trust class other than its section's, an unknown trust
class, field or basis is a malformed document - never re-read as a neighbour. In
particular a self-reported field (for example `gndcrw_tool`, whose `code_digest` is
GNDCRW's own statement: TOOL_CODE_SELF_REPORTED) has no verification basis, so it
cannot be promoted into `verified_provenance`. The same value in both classes would
still not be the same claim: equal values, different trust.

A verified entry's claim is exactly its basis - "these are the bytes / the digest
the package binds" - not that the code behind them is what it says it is:

    input_lock_digest         member_digest_recomputed  SHA-256(input.json) = run.json
                                                        input.digest
    execution_profile_digest  input_lock_recomputed     SHA-256(canonical(the Input Lock
                                                        execution profile document))
    gndcrw_result_digest      member_digest_recomputed  {sha256, size} of the held GNDCRW
                                                        result = the preflight record's

`boomvalley-epc-producer-1` (the #85 canonical package, the manifest-1 reference)
is still read, never re-labelled: it predates the split, so every item in it is
read as self-reported and nothing in it as verified (PRV-002 / PRV-003 NO_CLAIM).

Rules (both readers; `scripts/epc_consume.py` re-derives them stdlib-only):

    PRV-001  the document: a known schema; -2: the closed shape and trust table,
             every required field present, no field its run does not have, the
             self-reported values well formed
    PRV-002  every verified entry recomputes from the package bytes
    PRV-003  the self-reported entries restate the sealed evidence where it holds
             them (model = the custody ledger's actual_execution; code binding, GNDCRW
             executable and tool = the Input Lock / preflight record / result bytes)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes

PRODUCER_SCHEMA_V1 = "boomvalley-epc-producer-1"
PRODUCER_SCHEMA = "boomvalley-epc-producer-2"
READABLE_SCHEMAS = (PRODUCER_SCHEMA_V1, PRODUCER_SCHEMA)
REQUEST_VERSION = "boomvalley-lab-request-1"

SELF_REPORTED = "self_reported"
VERIFIED = "verified"
TRUST_CLASSES = (SELF_REPORTED, VERIFIED)
#: section member -> the one trust class its entries have
SECTIONS = {"self_reported_provenance": SELF_REPORTED, "verified_provenance": VERIFIED}
DOCUMENT_MEMBERS = frozenset({"schema", *SECTIONS})
ENTRY_MEMBERS = frozenset({"field", "trust_class", "basis", "value"})

#: field -> (trust class, basis): the closed trust table
FIELDS: dict[str, tuple[str, str]] = {
    "software": (SELF_REPORTED, "producer_self_report"),
    "source": (SELF_REPORTED, "producer_self_report"),
    "runtime": (SELF_REPORTED, "producer_self_report"),
    "os": (SELF_REPORTED, "producer_self_report"),
    "request_version": (SELF_REPORTED, "producer_self_report"),
    "model": (SELF_REPORTED, "adapter_self_report"),
    "execution_code_binding": (SELF_REPORTED, "producer_self_report"),
    "gndcrw_executable": (SELF_REPORTED, "producer_self_report"),
    "gndcrw_tool": (SELF_REPORTED, "tool_self_report"),
    "input_lock_digest": (VERIFIED, "member_digest_recomputed"),
    "execution_profile_digest": (VERIFIED, "input_lock_recomputed"),
    "gndcrw_result_digest": (VERIFIED, "member_digest_recomputed"),
}
ALWAYS = ("software", "source", "runtime", "os", "request_version", "model")
INPUT_LOCKED = ("execution_code_binding", "input_lock_digest", "execution_profile_digest")
PRE_EXECUTION = ("gndcrw_executable", "gndcrw_tool", "gndcrw_result_digest")

#: reason codes (machine-readable, English; each reason is "<CODE>: <detail>")
SHAPE_INVALID = "PROVENANCE_SHAPE_INVALID"
SCHEMA_UNKNOWN = "PROVENANCE_SCHEMA_UNKNOWN"
TRUST_CLASS_UNKNOWN = "PROVENANCE_TRUST_CLASS_UNKNOWN"
TRUST_CLASS_MISMATCH = "PROVENANCE_TRUST_CLASS_MISMATCH"
PROMOTED = "SELF_REPORTED_PROMOTED"
FIELD_UNKNOWN = "PROVENANCE_FIELD_UNKNOWN"
BASIS_MISMATCH = "PROVENANCE_BASIS_MISMATCH"
FIELD_MISSING = "PROVENANCE_FIELD_MISSING"
FIELD_UNEXPECTED = "PROVENANCE_FIELD_UNEXPECTED"
VALUE_INVALID = "SELF_REPORTED_VALUE_INVALID"
VERIFIED_MISMATCH = "VERIFIED_PROVENANCE_MISMATCH"
SELF_INCONSISTENT = "SELF_REPORTED_PROVENANCE_INCONSISTENT"
V1_NOT_CLASSIFIED = "PRODUCER_1_NOT_TRUST_CLASSIFIED"

_HEX = set("0123456789abcdef")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71 \
        and set(value[7:]) <= _HEX


def _strings(value: Any, keys: Sequence[str]) -> bool:
    return isinstance(value, dict) and set(value) == set(keys) and all(
        isinstance(value[k], str) and value[k] for k in keys)


def _source_ok(value: Any) -> bool:
    if value == {"status": "unknown"}:
        return True
    return (isinstance(value, dict) and set(value) == {"status", "commit", "dirty"}
            and value["status"] == "git" and isinstance(value["commit"], str)
            and len(value["commit"]) == 40 and set(value["commit"]) <= _HEX
            and isinstance(value["dirty"], bool))


#: self-reported field -> its value shape (all a reader can check of a pure self-report)
_SHAPES: dict[str, Callable[[Any], bool]] = {
    "software": lambda v: _strings(v, ("name", "version")),
    "source": _source_ok,
    "runtime": lambda v: _strings(v, ("name", "version")),
    "os": lambda v: _strings(v, ("name", "version", "arch")),
    "request_version": lambda v: v == REQUEST_VERSION,
    "model": lambda v: isinstance(v, list),
    "execution_code_binding": lambda v: isinstance(v, dict) and bool(v),
    "gndcrw_executable": lambda v: isinstance(v, dict) and set(v) == {"sha256"}
    and _digest(v["sha256"]),
    "gndcrw_tool": lambda v: isinstance(v, dict) and set(v) == {
        "name", "version", "code_digest", "code_digest_method"} and _digest(v["code_digest"]),
}


# =====================================================================
# the evidence the package holds, read from its bytes
# =====================================================================
class Held:
    """The package bytes provenance is checked against (None: the member is absent)."""

    def __init__(self, *, entries: Sequence[Mapping], input_bytes: bytes | None,
                 run_document: Mapping | None, result_bytes: bytes | None,
                 sha: Callable[[bytes], str]):
        self.entries = entries
        self.input_bytes = input_bytes
        self.input = load_bytes(input_bytes) if input_bytes is not None else None
        self.run = run_document
        self.result_bytes = result_bytes
        self.sha = sha

    @property
    def locked(self) -> bool:
        return self.input is not None

    @property
    def record(self) -> Mapping | None:
        pre = (self.input or {}).get("pre_execution")
        return pre["preflight_record"]["gndcrw"] if pre else None

    def required(self) -> set[str]:
        fields = set(ALWAYS)
        if self.locked:
            fields |= set(INPUT_LOCKED)
        if self.record is not None:
            fields |= set(PRE_EXECUTION)
        return fields

    def verified(self) -> dict[str, Any]:
        """field -> the value a reader recomputes from the bytes (verified_provenance)."""
        values: dict[str, Any] = {}
        if self.locked:
            values["input_lock_digest"] = self.sha(self.input_bytes)
            values["execution_profile_digest"] = self.sha(canonical_bytes(
                self.input["execution_profile"]["document"]))
        if self.record is not None and self.result_bytes is not None:
            values["gndcrw_result_digest"] = {"sha256": self.sha(self.result_bytes),
                                              "size": len(self.result_bytes)}
        return values

    def bound(self) -> list[str]:
        """What the verified values must also equal where the package binds them."""
        problems = []
        if self.locked:
            if (self.run or {}).get("input", {}).get("digest") != self.sha(self.input_bytes):
                problems.append("input_lock_digest is not run.json's input.digest")
            if self.input["execution_profile"].get("digest") != self.sha(canonical_bytes(
                    self.input["execution_profile"]["document"])):
                problems.append("execution_profile_digest is not the Input Lock's profile "
                                "digest")
        if self.record is not None:
            recorded = {k: self.record["result"].get(k) for k in ("sha256", "size")}
            if self.result_bytes is None or recorded != {
                    "sha256": self.sha(self.result_bytes), "size": len(self.result_bytes)}:
                problems.append("gndcrw_result_digest is not the preflight record's result")
        return problems

    def models(self) -> list[dict]:
        pairs = sorted({(e["actual_execution"]["adapter_provenance"],
                         e["actual_execution"]["model_identity"]) for e in self.entries})
        models: list[dict] = [{"adapter_provenance": p, "reported": m} for p, m in pairs]
        if self.locked:
            local = self.input["execution_profile"]["document"]["adapter"]["kind"] == "local"
            for model in models:
                model["provider_version"] = {
                    "status": "not_applicable" if local else "not_disclosed"}
        return models

    def restated(self) -> dict[str, Any]:
        """self-reported field -> the value the sealed evidence holds for it."""
        values: dict[str, Any] = {"model": self.models()}
        if self.locked:
            values["execution_code_binding"] = self.input["execution_profile"]["binding"]
        if self.record is not None:
            values["gndcrw_executable"] = {"sha256": self.record["executable"]["sha256"]}
            values["gndcrw_tool"] = self.record["tool"]
        return values

    def result_tool(self) -> Any:
        try:
            result = load_bytes(self.result_bytes) if self.result_bytes is not None else None
        except MalformedJSON:
            return None
        return result.get("tool") if isinstance(result, dict) else None


# =====================================================================
# the writer
# =====================================================================
def entry(field: str, value: Any) -> dict:
    trust_class, basis = FIELDS[field]
    return {"field": field, "trust_class": trust_class, "basis": basis, "value": value}


def producer_document(held: Held, *, host: Mapping[str, Any]) -> dict:
    """`boomvalley-epc-producer-2`: each item in the one section its trust class allows.

    `host` holds the producer's statements about itself (software, source, runtime,
    os); everything else is taken from the evidence the package holds."""
    self_reported = {**{k: host[k] for k in ("software", "source", "runtime", "os")},
                     "request_version": REQUEST_VERSION, **held.restated()}
    verified = held.verified()
    return {"schema": PRODUCER_SCHEMA,
            "self_reported_provenance": [entry(f, self_reported[f])
                                         for f in sorted(self_reported)],
            "verified_provenance": [entry(f, verified[f]) for f in sorted(verified)]}


# =====================================================================
# the readers' checks
# =====================================================================
def shape_problems(document: Any, held: Held) -> list[str]:
    """PRV-001."""
    if not isinstance(document, dict) or document.get("schema") not in READABLE_SCHEMAS:
        schema = document.get("schema") if isinstance(document, dict) else None
        return [f"{SCHEMA_UNKNOWN}: producer provenance schema {schema!r}"]
    if document["schema"] == PRODUCER_SCHEMA_V1:
        return []
    if set(document) != DOCUMENT_MEMBERS:
        return [f"{SHAPE_INVALID}: members {sorted(document)}, not {sorted(DOCUMENT_MEMBERS)}"]
    problems: list[str] = []
    seen: dict[str, str] = {}
    for section, section_class in SECTIONS.items():
        entries = document[section]
        if not isinstance(entries, list):
            problems.append(f"{SHAPE_INVALID}: {section} is not a list")
            continue
        fields = []
        for item in entries:
            if not isinstance(item, dict) or set(item) != ENTRY_MEMBERS \
                    or not isinstance(item["field"], str):
                problems.append(f"{SHAPE_INVALID}: {section} entry {item!r} is not "
                                f"{sorted(ENTRY_MEMBERS)}")
                continue
            field, trust_class = item["field"], item["trust_class"]
            fields.append(field)
            if trust_class not in TRUST_CLASSES:
                problems.append(f"{TRUST_CLASS_UNKNOWN}: {field}: trust_class {trust_class!r}")
                continue
            if trust_class != section_class:
                problems.append(f"{TRUST_CLASS_MISMATCH}: {field} in {section} says "
                                f"{trust_class!r}")
            if field not in FIELDS:
                problems.append(f"{FIELD_UNKNOWN}: {field!r}")
                continue
            own_class, basis = FIELDS[field]
            if own_class == SELF_REPORTED and VERIFIED in (section_class, trust_class):
                problems.append(f"{PROMOTED}: {field} is self-reported ({basis}); it has no "
                                "verification basis and is never a verified claim")
            elif own_class != section_class:
                problems.append(f"{TRUST_CLASS_MISMATCH}: {field} is {own_class}, listed in "
                                f"{section}")
            if item["basis"] != basis:
                problems.append(f"{BASIS_MISMATCH}: {field} basis {item['basis']!r}, its "
                                f"basis is {basis!r}")
            if field in seen:
                problems.append(f"{SHAPE_INVALID}: {field} is listed twice")
            seen[field] = section
            if own_class == SELF_REPORTED and not _SHAPES[field](item["value"]):
                problems.append(f"{VALUE_INVALID}: {field} value {item['value']!r}")
        if fields != sorted(fields):
            problems.append(f"{SHAPE_INVALID}: {section} is not sorted by field")
    required = held.required()
    problems += [f"{FIELD_MISSING}: {f}" for f in sorted(required - set(seen))]
    problems += [f"{FIELD_UNEXPECTED}: {f} (this run has no such provenance)"
                 for f in sorted(set(seen) & set(FIELDS) - required)]
    return problems


def _values(document: Mapping, section: str) -> dict[str, Any]:
    return {e["field"]: e["value"] for e in document[section]}


def verified_problems(document: Mapping, held: Held) -> list[str]:
    """PRV-002 (only on a -2 document whose shape holds)."""
    stated, expected = _values(document, "verified_provenance"), held.verified()
    problems = [f"{VERIFIED_MISMATCH}: {field} states {stated.get(field)!r}; the package "
                f"bytes give {expected.get(field)!r}"
                for field in sorted(set(stated) | set(expected))
                if stated.get(field) != expected.get(field)]
    return problems + [f"{VERIFIED_MISMATCH}: {p}" for p in held.bound()]


def consistency_problems(document: Mapping, held: Held) -> list[str]:
    """PRV-003 (only on a -2 document whose shape holds)."""
    stated = _values(document, "self_reported_provenance")
    problems = [f"{SELF_INCONSISTENT}: {field} states {stated.get(field)!r}; the sealed "
                f"evidence holds {value!r}"
                for field, value in sorted(held.restated().items())
                if stated.get(field) != value]
    if held.record is not None and held.result_tool() != held.record["tool"]:
        problems.append(f"{SELF_INCONSISTENT}: gndcrw_tool: the preflight record's tool is "
                        "not the one in the GNDCRW result bytes")
    return problems


def reading(document: Any) -> dict | None:
    """What a consumer may rely on: the verified fields, and the self-reported ones
    kept apart. A -1 document is all self-reported (`trust_classified` false)."""
    if not isinstance(document, dict) or document.get("schema") not in READABLE_SCHEMAS:
        return None
    if document["schema"] == PRODUCER_SCHEMA_V1:
        return {"producer_schema": PRODUCER_SCHEMA_V1, "trust_classified": False,
                "verified_provenance": {},
                "self_reported_provenance": {
                    k: {"basis": "producer_self_report", "value": v}
                    for k, v in sorted(document.items()) if k != "schema"}}
    return {"producer_schema": PRODUCER_SCHEMA, "trust_classified": True,
            **{section: {e["field"]: {"basis": e["basis"], "value": e["value"]}
                         for e in document[section]} for section in SECTIONS}}


def model_entries(document: Mapping) -> list:
    """The model list a producer document states (-1 top level, -2 self-reported)."""
    if document.get("schema") == PRODUCER_SCHEMA_V1:
        return list(document.get("model") or [])
    return list(_values(document, "self_reported_provenance").get("model") or [])


__all__ = ["FIELDS", "Held", "PRODUCER_SCHEMA", "PRODUCER_SCHEMA_V1", "SECTIONS",
           "consistency_problems", "producer_document", "reading", "shape_problems",
           "verified_problems"]
