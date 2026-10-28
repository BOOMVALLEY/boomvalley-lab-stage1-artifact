"""The schedule preflight (#153): a fail-closed hard gate before any model call.

    bvl check --experiment F.json --expect-schedule S.json     report; exit 4 unless exact
    bvl run   --experiment F.json --expect-schedule S.json ... refuse unless exact

A frozen experiment states, before any call, the exact order its records must
run in. `--expect-schedule` names that frozen order; this module compares it with
the order the locked schedule will actually execute (`lock.declaration`, the same
bytes `Run.create` writes and the executor follows) and returns one decision:

    EXACT_MATCH    the comparison completed, the comparator said `exact` explicitly,
                   the gate's own equality agrees, and the schedule identity binds
    MISMATCH       the comparison completed and the orders (or identities) differ
    ERROR          the comparison could not be made: the expected schedule cannot be
                   read or parsed, or the comparator raised / exited
    UNVERIFIABLE   there is nothing to compare (no frozen schedule on either side), or
                   the comparator's answer cannot be read as an explicit exact match

Only EXACT_MATCH lets `bvl run` go on. Anything else - including a status this
module does not know - refuses (`SCHEDULE_PREFLIGHT_REFUSAL`, exit 4) before the
run directory is created, a session is acquired or the adapter is touched: zero
model calls. The refusal leaves `SCHEDULE_PREFLIGHT.json` in `--into` (execution
NOT_STARTED, model_calls 0) as evidence that nothing started, and that file makes
the directory run residue: a corrected input runs in a new directory.

The gate is BVL's, not a shell chain's: it runs in the `bvl run` process, and a
failure of any step (I/O, parse, comparator) is a refusal, never a warning.

Binding (#153 req 6): EXACT_MATCH also requires that the lock's ScheduleIdentity
recomputes from the locked declaration, and - when the expected document states a
`schedule_identity` - that it is that identity. After `Run.create`/`Run.open`,
`bind` checks that the opened run still executes that order under that identity.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import InputRefusal

SCHEMA = "bvl-schedule-preflight-1"
EXPECTED_SCHEMA = "bvl-expected-schedule-1"
RECORD_FILE = "SCHEDULE_PREFLIGHT.json"
REFUSAL_CLASS = "SCHEDULE_PREFLIGHT_REFUSAL"

EXACT_MATCH = "EXACT_MATCH"
MISMATCH = "MISMATCH"
ERROR = "ERROR"
UNVERIFIABLE = "UNVERIFIABLE"
#: `bvl check` / `bvl run` without `--expect-schedule`: no gate was asked for
NOT_REQUESTED = "NOT_REQUESTED"
STATUSES = (EXACT_MATCH, MISMATCH, ERROR, UNVERIFIABLE, NOT_REQUESTED)

#: refusal code -> the one status it establishes (closed; registered in `core.codes`)
CODES: dict[str, str] = {
    "SCHEDULE_PREFLIGHT_ORDER_MISMATCH": MISMATCH,
    "SCHEDULE_PREFLIGHT_LENGTH_MISMATCH": MISMATCH,
    "SCHEDULE_PREFLIGHT_IDENTITY_MISMATCH": MISMATCH,
    "SCHEDULE_PREFLIGHT_PATH_ERROR": ERROR,
    "SCHEDULE_PREFLIGHT_PARSE_ERROR": ERROR,
    "SCHEDULE_PREFLIGHT_COMPARATOR_FAILED": ERROR,
    "SCHEDULE_PREFLIGHT_SCHEDULE_MISSING": UNVERIFIABLE,
    "SCHEDULE_PREFLIGHT_UNVERIFIABLE": UNVERIFIABLE,
    # after Run.open: the opened run is not the order / identity that was gated
    "SCHEDULE_PREFLIGHT_BINDING_MISMATCH": MISMATCH,
}

#: a comparator: (expected keys, actual keys) -> its answer. `compare` is BVL's; a
#: test (or a future pluggable check) may hand another in. Its answer is only read,
#: never trusted: EXACT_MATCH needs `exact is True` AND the gate's own equality.
Comparator = Callable[[Sequence[str], Sequence[str]], Mapping[str, Any]]

_MSYS_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?:/(.*))?$")


def native_path(text: str | os.PathLike, *, windows: bool | None = None) -> Path:
    """A path argument as this OS reads it (#153 req 4).

    On Windows a Git-Bash / MSYS / Cygwin drive path (`/c/dev/x`, `/cygdrive/c/x`)
    is the drive path `C:/dev/x`; left alone, Windows Python reads it as `\\c\\dev\\x`
    on the current drive - the #152 path error. `C:\\...`, `C:/...`, UNC and relative
    paths are returned unchanged. Elsewhere every path is unchanged."""
    windows = os.name == "nt" if windows is None else windows
    raw = os.fspath(text)
    if windows:
        found = _MSYS_DRIVE.match(raw.replace("\\", "/"))
        if found:
            return Path(f"{found.group(1).upper()}:/{found.group(2) or ''}")
    return Path(raw)


def compare(expected: Sequence[str], actual: Sequence[str]) -> dict:
    """BVL's comparator: exact equality of two ordered key lists, and where they differ."""
    expected, actual = list(expected), list(actual)
    pairs = enumerate(zip(expected, actual, strict=False))
    first = next((index for index, (a, b) in pairs if a != b), None)
    if first is None and len(expected) != len(actual):
        first = min(len(expected), len(actual))
    answer = {"exact": expected == actual, "expected_length": len(expected),
              "actual_length": len(actual)}
    if first is not None:
        answer["first_difference"] = {
            "position": first,
            "expected": expected[first] if first < len(expected) else "<end>",
            "actual": actual[first] if first < len(actual) else "<end>"}
    return answer


# ------------------------------------------------------------------ reading
def _locked_order(lock: Mapping) -> tuple[list[str], bool, str, str]:
    """(keys in execution order, declared?, stored identity, recomputed identity)."""
    from boomvalley_lab.declare.experiment import load
    from boomvalley_lab.identity.derive import schedule_identity

    experiment = load(lock["declaration"])
    return ([record.key for record in experiment.records], experiment.schedule.declared,
            str(lock["identities"]["schedule"]), str(schedule_identity(experiment).digest))


def _expected(data: bytes) -> tuple[list[str] | None, str | None, str | None]:
    """(keys or None, stated schedule identity or None, parse problem or None).

    A JSON list of record keys (what `scripts/bvl_balanced_schedule.py` prints), or
    {"schema": "bvl-expected-schedule-1", "schedule": [...], "schedule_identity"?}."""
    from boomvalley_lab.core.strict_json import load_bytes

    try:
        document = load_bytes(data)
    except (ValueError, UnicodeDecodeError) as error:
        return None, None, f"not strict JSON: {error}"
    identity = None
    if isinstance(document, dict):
        unknown = sorted(set(document) - {"schema", "schedule", "schedule_identity"})
        if document.get("schema") != EXPECTED_SCHEMA or unknown:
            return None, None, (f"an expected-schedule object is {{\"schema\": "
                                f"\"{EXPECTED_SCHEMA}\", \"schedule\": [...], "
                                f"\"schedule_identity\"?}} (unknown: {unknown})")
        identity = document.get("schedule_identity")
        if identity is not None and not isinstance(identity, str):
            return None, None, "schedule_identity is a sha256:<hex> string"
        if "schedule" not in document:
            return None, identity, None
        document = document["schedule"]
    if not isinstance(document, list) or not all(isinstance(k, str) for k in document):
        return None, None, "the expected schedule is a JSON list of record keys"
    return document, identity, None


# ------------------------------------------------------------------ the decision
def _decision(status: str, code: str | None, params: Mapping[str, Any], *,
              expected: Mapping, actual: Mapping, contract: str,
              comparison: Mapping | None = None) -> dict:
    document = {"schema": SCHEMA, "schedule_preflight_status": status,
                "exact": status == EXACT_MATCH,
                "message_key": f"schedule_preflight.{code or 'status.' + status}",
                "params": dict(params), "expected": dict(expected), "actual": dict(actual),
                "contract_identity": contract}
    if code is not None:
        document["reason_code"] = code
    if comparison is not None:
        document["comparison"] = dict(comparison)
    return document


def not_requested() -> dict:
    return {"schema": SCHEMA, "schedule_preflight_status": NOT_REQUESTED, "exact": False,
            "message_key": f"schedule_preflight.status.{NOT_REQUESTED}", "params": {}}


def evaluate(lock: Mapping, expected_path: str | os.PathLike, *,
             comparator: Comparator | None = None) -> dict:
    """The decision document. Never raises for a bad input: every failure is a status."""
    comparator = compare if comparator is None else comparator
    given = os.fspath(expected_path)
    path = native_path(given)
    keys, declared, stored, recomputed = _locked_order(lock)
    actual = {"schedule_identity": stored, "recomputed_schedule_identity": recomputed,
              "declared": declared, "length": len(keys),
              "order_digest": str(sha256_document(keys))}
    expected: dict[str, Any] = {"source": given, "path": str(path)}

    def decided(code: str, comparison: Mapping | None = None, **params) -> dict:
        return _decision(CODES[code], code, params, expected=expected, actual=actual,
                         contract=str(lock["identities"]["contract"]), comparison=comparison)

    try:
        data = path.read_bytes()
    except OSError as error:
        return decided("SCHEDULE_PREFLIGHT_PATH_ERROR", path=str(path),
                       error=f"{type(error).__name__}: {error.strerror or error}")
    expected.update({"sha256": str(sha256_bytes(data)), "size": len(data)})
    order, stated, problem = _expected(data)
    if problem is not None:
        return decided("SCHEDULE_PREFLIGHT_PARSE_ERROR", path=str(path), problem=problem)
    if stated is not None:
        expected["schedule_identity"] = stated
    if not order:
        return decided("SCHEDULE_PREFLIGHT_SCHEDULE_MISSING", side="expected",
                       problem="the expected schedule is absent or empty")
    expected.update({"length": len(order), "order_digest": str(sha256_document(order))})
    if not declared:
        return decided("SCHEDULE_PREFLIGHT_SCHEDULE_MISSING", side="declaration",
                       problem="the declaration freezes no `schedule` (canonical order)")
    if recomputed != stored or (stated is not None and stated != stored):
        return decided("SCHEDULE_PREFLIGHT_IDENTITY_MISMATCH", locked=stored,
                       recomputed=recomputed, stated=stated or "-")
    try:
        answer = comparator(list(order), list(keys))
    except (Exception, SystemExit) as error:  # noqa: BLE001 - a failed step is a refusal
        return decided("SCHEDULE_PREFLIGHT_COMPARATOR_FAILED",
                       error=f"{type(error).__name__}: {error}")
    if not isinstance(answer, Mapping) or not isinstance(answer.get("exact"), bool):
        return decided("SCHEDULE_PREFLIGHT_UNVERIFIABLE",
                       problem="the comparator returned no explicit boolean `exact`")
    comparison = {k: answer[k] for k in ("exact", "expected_length", "actual_length",
                                         "first_difference") if k in answer}
    if len(order) != len(keys):
        return decided("SCHEDULE_PREFLIGHT_LENGTH_MISMATCH", comparison,
                       expected=len(order), actual=len(keys))
    if order != keys:
        difference = compare(order, keys)["first_difference"]
        return decided("SCHEDULE_PREFLIGHT_ORDER_MISMATCH", comparison, **difference)
    if answer["exact"] is not True:
        return decided("SCHEDULE_PREFLIGHT_UNVERIFIABLE", comparison,
                       problem="the comparator did not report an exact match")
    return _decision(EXACT_MATCH, None, {"length": len(keys)}, expected=expected,
                     actual=actual, contract=str(lock["identities"]["contract"]),
                     comparison=comparison)


def passed(decision: Mapping) -> bool:
    """The ONE admission test: an explicit EXACT_MATCH and exact True. Nothing else."""
    return (isinstance(decision, Mapping)
            and decision.get("schedule_preflight_status") == EXACT_MATCH
            and decision.get("exact") is True)


def refusal(decision: Mapping, *, record: str | None = None) -> InputRefusal:
    code = decision.get("reason_code")
    if code not in CODES:
        code = "SCHEDULE_PREFLIGHT_UNVERIFIABLE"
    detail = (f"schedule preflight {decision.get('schedule_preflight_status')}: "
              f"{code} {dict(decision.get('params') or {})}; execution NOT_STARTED, "
              "0 model calls")
    evidence = {"schedule_preflight": dict(decision), "execution_status": "NOT_STARTED",
                "model_calls": 0}
    if record is not None:
        evidence["record"] = record
    return InputRefusal(REFUSAL_CLASS, code, detail, layer="SP",
                        path="argv#/expect-schedule", evidence=evidence)


def enforce(decision: Mapping) -> None:
    if not passed(decision):
        raise refusal(decision)


def write_record(into: Path, decision: Mapping, *, at: str) -> str | None:
    """The evidence that nothing started. Written once (exclusive); returns its name,
    or None when it could not be written - the refusal stands either way."""
    document = {"schema": f"{SCHEMA}-record", "at": at, "decision": dict(decision),
                "execution_status": "NOT_STARTED", "model_calls": 0,
                "run_created": False, "session_acquired": False}
    try:
        into.mkdir(parents=True, exist_ok=True)
        with open(into / RECORD_FILE, "xb") as handle:
            handle.write(canonical_bytes(document))
    except OSError:
        return None
    return RECORD_FILE


def bind(decision: Mapping, run) -> None:
    """After Run.open, before the executor: the opened run executes the gated order
    under the gated ScheduleIdentity, or nothing executes."""
    keys = [record.key for record in run.records]
    identity = str(run.lock["identities"]["schedule"])
    gated = decision["actual"]
    if identity != gated["schedule_identity"] or \
            str(sha256_document(keys)) != gated["order_digest"] or \
            gated["order_digest"] != decision["expected"].get("order_digest"):
        raise refusal(_decision(
            MISMATCH, "SCHEDULE_PREFLIGHT_BINDING_MISMATCH",
            {"gated": gated["schedule_identity"], "opened": identity},
            expected=decision["expected"], actual=gated,
            contract=str(decision["contract_identity"])))
