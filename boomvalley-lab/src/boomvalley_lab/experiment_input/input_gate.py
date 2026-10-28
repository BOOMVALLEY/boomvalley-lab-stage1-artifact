"""The experiment-input preflight (#175): a fail-closed hard gate before any model call.

    bvl check --experiment F.json --expect-experiment-input X      report; exit 4 unless exact
    bvl run   --experiment F.json --expect-experiment-input X ...  refuse unless exact

A frozen experiment states, before any call, the ExperimentInputIdentity (EII) it
was preregistered under. The EII binds the contract, the execution profile (treatment
text, prompt, seeds, generation options, model pin) and the GNDCRW preflight. The
schedule gate (#153) binds the order only; this gate binds everything else the run
will execute: a treatment-text swap, a seed change, a 1-byte prompt drift or an
option drift is a different EII and is refused here (BVVH #174 MAJOR-2).

`X` is either the identity itself (`experiment_input:sha256:<64 hex>`) or a file:

    a text file holding exactly that identity (surrounding whitespace ignored)
    {"schema": "bvl-expected-experiment-input-1", "experiment_input_identity": "..."}
    a frozen run's `input.json` (bvl-input-lock-2): its identity, which must recompute
                   from its own `eii_preimage`

The actual identity is computed from the materialized input (after I0..I5 and the
GNDCRW preflight, I6) exactly as `lockdoc.input_lock` will write it, and compared by
exact string equality. One decision:

    EXACT_MATCH    the identities are equal
    MISMATCH       they differ
    ERROR          the expected identity cannot be read or parsed (missing, unreadable,
                   malformed, an input lock that does not recompute)
    UNVERIFIABLE   the actual identity cannot be computed (no execution profile, or the
                   computation failed)

Only EXACT_MATCH lets `bvl run` go on. Anything else refuses
(`EXPERIMENT_INPUT_PREFLIGHT_REFUSAL`, exit 4) before the execution gate, `Run.create`,
a session or the adapter: zero model calls. `run` leaves `EXPERIMENT_INPUT_PREFLIGHT.json`
in `--into` (NOT_STARTED, model_calls 0) as evidence; `check` writes nothing. After
`Run.open`, `bind` checks that the verified Input Lock is the gated identity.

Evidence surface: the gated identity IS the EII the run's `input.json`, `run.json`,
INPUT_LOCK_BOUND and EPC package carry (FULLMT recomputes it), so a sealed run proves
which input executed; the decision itself (expected source and digest, EXACT_MATCH) is
in the `bvl run` / `bvl check` result. Binding the decision into the EPC needs a new
member role, which FULLMT's closed vocabulary does not have (BVL-REC-085).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import InputRefusal

SCHEMA = "bvl-experiment-input-preflight-1"
EXPECTED_SCHEMA = "bvl-expected-experiment-input-1"
INPUT_LOCK_SCHEMA = "bvl-input-lock-2"
RECORD_FILE = "EXPERIMENT_INPUT_PREFLIGHT.json"
REFUSAL_CLASS = "EXPERIMENT_INPUT_PREFLIGHT_REFUSAL"

EXACT_MATCH = "EXACT_MATCH"
MISMATCH = "MISMATCH"
ERROR = "ERROR"
UNVERIFIABLE = "UNVERIFIABLE"
#: `bvl check` / `bvl run` without `--expect-experiment-input`: no gate was asked for
NOT_REQUESTED = "NOT_REQUESTED"
STATUSES = (EXACT_MATCH, MISMATCH, ERROR, UNVERIFIABLE, NOT_REQUESTED)

#: refusal code -> the one status it establishes (closed; registered in `core.codes`)
CODES: dict[str, str] = {
    "EXPERIMENT_INPUT_PREFLIGHT_IDENTITY_MISMATCH": MISMATCH,
    "EXPERIMENT_INPUT_PREFLIGHT_PATH_ERROR": ERROR,
    "EXPERIMENT_INPUT_PREFLIGHT_PARSE_ERROR": ERROR,
    "EXPERIMENT_INPUT_PREFLIGHT_UNVERIFIABLE": UNVERIFIABLE,
    # after Run.open: the verified Input Lock is not the gated identity
    "EXPERIMENT_INPUT_PREFLIGHT_BINDING_MISMATCH": MISMATCH,
}

IDENTITY = re.compile(r"experiment_input:sha256:[0-9a-f]{64}")


def _identity_problem(value: object) -> str | None:
    if not isinstance(value, str) or IDENTITY.fullmatch(value) is None:
        return "an experiment input identity is experiment_input:sha256:<64 lowercase hex>"
    return None


# ------------------------------------------------------------------ reading
def _from_document(document: object) -> tuple[str | None, str | None, str | None]:
    """(identity, form, problem) of a parsed expected document."""
    from boomvalley_lab.experiment_input import lockdoc as docs

    if isinstance(document, str):
        return (None, None, problem) if (problem := _identity_problem(document)) else \
            (document, "json_string", None)
    if not isinstance(document, dict):
        return None, None, "the expected experiment input is an identity or a JSON object"
    if document.get("schema") == EXPECTED_SCHEMA:
        unknown = sorted(set(document) - {"schema", "experiment_input_identity"})
        if unknown:
            return None, None, f"unknown members in {EXPECTED_SCHEMA}: {unknown}"
        stated = document.get("experiment_input_identity")
        if (problem := _identity_problem(stated)) is not None:
            return None, None, problem
        return stated, EXPECTED_SCHEMA, None
    if document.get("schema") == INPUT_LOCK_SCHEMA:
        stated, preimage = document.get("experiment_input_identity"), document.get("eii_preimage")
        if (problem := _identity_problem(stated)) is not None:
            return None, None, problem
        if not isinstance(preimage, dict) or docs.eii_of(preimage) != stated:
            return None, None, ("the input lock's experiment_input_identity does not recompute "
                                "from its eii_preimage")
        return stated, INPUT_LOCK_SCHEMA, None
    return None, None, (f"an expected-experiment-input object is {{\"schema\": "
                        f"\"{EXPECTED_SCHEMA}\", \"experiment_input_identity\": ...}} or a "
                        f"{INPUT_LOCK_SCHEMA} input.json")


def _expected(data: bytes) -> tuple[str | None, str | None, str | None]:
    """(identity, form, problem) of the expected file's bytes."""
    from boomvalley_lab.core.strict_json import load_bytes

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return None, None, f"not UTF-8: {error}"
    if IDENTITY.fullmatch(text.strip()):
        return text.strip(), "text", None
    try:
        document = load_bytes(data)
    except (ValueError, UnicodeDecodeError) as error:
        return None, None, f"neither an identity line nor strict JSON: {error}"
    return _from_document(document)


def actual_identity(m, preflight) -> tuple[str | None, str | None]:
    """(EII, problem): the identity `lockdoc.input_lock` will write for this input."""
    from boomvalley_lab.experiment_input import lockdoc as docs

    if m.profile is None:
        return None, "the experiment input has no execution profile; it has no run identity"
    try:
        return docs.eii_of(docs.eii_preimage(m, preflight)), None
    except Exception as error:  # noqa: BLE001 - an identity that cannot be made refuses
        return None, f"{type(error).__name__}: {error}"


# ------------------------------------------------------------------ the decision
def _decision(status: str, code: str | None, params: Mapping[str, Any], *,
              expected: Mapping, actual: Mapping, contract: str) -> dict:
    document = {"schema": SCHEMA, "experiment_input_preflight_status": status,
                "exact": status == EXACT_MATCH,
                "message_key": f"experiment_input_preflight.{code or 'status.' + status}",
                "params": dict(params), "expected": dict(expected), "actual": dict(actual),
                "contract_identity": contract}
    if code is not None:
        document["reason_code"] = code
    return document


def not_requested() -> dict:
    return {"schema": SCHEMA, "experiment_input_preflight_status": NOT_REQUESTED,
            "exact": False, "message_key": f"experiment_input_preflight.status.{NOT_REQUESTED}",
            "params": {}}


def evaluate(m, preflight, expected_value: str | os.PathLike) -> dict:
    """The decision document. Never raises for a bad input: every failure is a status."""
    from boomvalley_lab.experiment_input.schedule_gate import native_path

    given = os.fspath(expected_value)
    computed, unmade = actual_identity(m, preflight)
    actual: dict[str, Any] = {"experiment_input_identity": computed}
    expected: dict[str, Any] = {"source": given}

    def decided(code: str, **params) -> dict:
        return _decision(CODES[code], code, params, expected=expected, actual=actual,
                         contract=str(m.contract))

    if given.lower().startswith("experiment_input:"):  # the identity itself, never a path
        expected["form"] = "identity"
        if (problem := _identity_problem(given)) is not None:
            return decided("EXPERIMENT_INPUT_PREFLIGHT_PARSE_ERROR", path="argv",
                           problem=problem)
        stated = given
    else:
        path = native_path(given)
        expected["path"] = str(path)
        try:
            data = path.read_bytes()
        except OSError as error:
            return decided("EXPERIMENT_INPUT_PREFLIGHT_PATH_ERROR", path=str(path),
                           error=f"{type(error).__name__}: {error.strerror or error}")
        expected.update({"sha256": str(sha256_bytes(data)), "size": len(data)})
        stated, form, problem = _expected(data)
        if problem is not None:
            return decided("EXPERIMENT_INPUT_PREFLIGHT_PARSE_ERROR", path=str(path),
                           problem=problem)
        expected["form"] = form
    expected["experiment_input_identity"] = stated
    if computed is None:
        return decided("EXPERIMENT_INPUT_PREFLIGHT_UNVERIFIABLE", problem=unmade)
    if stated != computed:
        return decided("EXPERIMENT_INPUT_PREFLIGHT_IDENTITY_MISMATCH", expected=stated,
                       actual=computed)
    return _decision(EXACT_MATCH, None, {"identity": computed}, expected=expected,
                     actual=actual, contract=str(m.contract))


def passed(decision: Mapping) -> bool:
    """The ONE admission test: an explicit EXACT_MATCH, exact True, and equal identities."""
    if not isinstance(decision, Mapping):
        return False
    stated = (decision.get("expected") or {}).get("experiment_input_identity")
    computed = (decision.get("actual") or {}).get("experiment_input_identity")
    return (decision.get("experiment_input_preflight_status") == EXACT_MATCH
            and decision.get("exact") is True
            and isinstance(stated, str) and IDENTITY.fullmatch(stated) is not None
            and stated == computed)


def refusal(decision: Mapping, *, record: str | None = None) -> InputRefusal:
    code = decision.get("reason_code")
    if code not in CODES:
        code = "EXPERIMENT_INPUT_PREFLIGHT_UNVERIFIABLE"
    detail = (f"experiment input preflight "
              f"{decision.get('experiment_input_preflight_status')}: {code} "
              f"{dict(decision.get('params') or {})}; execution NOT_STARTED, 0 model calls")
    evidence = {"experiment_input_preflight": dict(decision), "execution_status": "NOT_STARTED",
                "model_calls": 0}
    if record is not None:
        evidence["record"] = record
    return InputRefusal(REFUSAL_CLASS, code, detail, layer="EP",
                        path="argv#/expect-experiment-input", evidence=evidence)


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


def bind(decision: Mapping, locked_identity: str) -> None:
    """After Run.open and ILV, before the executor: the verified Input Lock is the
    gated identity, or nothing executes."""
    gated = decision["actual"]["experiment_input_identity"]
    if locked_identity != gated or not passed(decision):
        raise refusal(_decision(
            MISMATCH, "EXPERIMENT_INPUT_PREFLIGHT_BINDING_MISMATCH",
            {"gated": gated, "opened": locked_identity},
            expected=decision["expected"], actual=decision["actual"],
            contract=str(decision["contract_identity"])))
