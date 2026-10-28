"""The execution gate (#76 C, #81): may this experiment input start executing?

One pre-execution decision, evaluated by `bvl check` and `bvl run` after the
Input Lock values exist in memory and before any run directory is created:

    CLEARED                        every mandatory pre-execution gate holds: the run
                                   may start
    MANDATORY_REQUIREMENT_NOT_MET  execution may be technically possible, but a
                                   mandatory requirement of the research protocol /
                                   contract does not hold: it MUST NOT execute
    EXECUTION_NOT_POSSIBLE         not a policy block: a runtime / capability this
                                   installation needs to execute the profile is absent
    NOT_EVALUATED                  the gate was not evaluated, or the stage that
                                   applies it was not reached

A gate decision is a normal decision, never an error: every non-CLEARED status
carries at least one reason - a stable `rule_id` (`RULES`), a `reason_code`
(closed vocabulary, `REASONS`, registered in `core.codes`), a `message_key +
params` for the human view (`core.i18n`) and, where there is one, an
`evidence_ref`. A malformed / contract / system failure stays an `InputRefusal`
with an error code; the two are never mixed. `verification_status` (does the
evidence hold?) and `execution_status` (did execution start?) are separate
axes, reported beside the gate status and never merged with it.

Each reason code establishes exactly one status, and the decision's status is
the most severe one its reasons establish (`PRECEDENCE`): a run that cannot be
executed here is EXECUTION_NOT_POSSIBLE even if a requirement also failed, and
a known unmet requirement outranks a part that was not evaluated.

A non-CLEARED `bvl run` creates no run and executes nothing (NOT_STARTED). It
writes a gate record instead (`write_record`): the decision, the canonical
declaration (raw digest = ContractIdentity), the canonical execution profile
and the exact GNDCRW preflight bytes, each listed by raw digest - enough for
`verify_record` to recompute the ContractIdentity, the ExperimentInputIdentity
of the gated input state, the GNDCRW outcome and from it every preflight
reason. The capability reasons are facts about the installation that evaluated
the gate and are attested (`EXECUTION_CAPABILITY_ATTESTED`).

The gate policy is BVL's. An independent reader (FULLMT) checks the EPC claims,
identities and core invariants; it does not re-implement this engine.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import (
    UNSUPPORTED_SCHEMA,
    BoomvalleyError,
    EvidenceError,
    ExecutionError,
)
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes

SCHEMA = "bvl-execution-gate-1"
RECORD_SCHEMA = "bvl-execution-gate-record-1"
RECORD_FILE = "EXECUTION_GATE.json"
DECLARATION_MEMBER = "design/declaration.json"
PROFILE_MEMBER = "input/execution_profile.json"

CLEARED = "CLEARED"
MANDATORY_REQUIREMENT_NOT_MET = "MANDATORY_REQUIREMENT_NOT_MET"
EXECUTION_NOT_POSSIBLE = "EXECUTION_NOT_POSSIBLE"
NOT_EVALUATED = "NOT_EVALUATED"
STATUSES = (CLEARED, MANDATORY_REQUIREMENT_NOT_MET, EXECUTION_NOT_POSSIBLE, NOT_EVALUATED)

#: `execution_status`: did execution start? (a third axis, never the gate status)
STARTED = "STARTED"
NOT_STARTED = "NOT_STARTED"
EXECUTION_STATUSES = (STARTED, NOT_STARTED)

#: `verification_status` of a gate record (`verify_record`)
VERIFIED = "VERIFIED"
REJECTED = "REJECTED"

#: most severe first: the status a set of reasons establishes
PRECEDENCE = (EXECUTION_NOT_POSSIBLE, MANDATORY_REQUIREMENT_NOT_MET, NOT_EVALUATED)

#: reason_code -> the one status it establishes (the closed vocabulary)
REASONS: dict[str, str] = {
    # a mandatory research-protocol requirement does not hold: MUST NOT execute
    "GNDCRW_PREFLIGHT_NOT_CLEARED": MANDATORY_REQUIREMENT_NOT_MET,
    # this installation cannot execute the locked profile
    "REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE": EXECUTION_NOT_POSSIBLE,
    # the gate (or part of it) was not evaluated
    "VALIDATION_ONLY": NOT_EVALUATED,
    "EXECUTION_PROFILE_ABSENT": NOT_EVALUATED,
    "LEGACY_RUN_NOT_GATED": NOT_EVALUATED,
    "EXECUTION_GATE_NOT_RECORDED": NOT_EVALUATED,
}

#: rule_id -> the reason codes that rule states (stable, public)
RULES: dict[str, tuple[str, ...]] = {
    # the attached GNDCRW preflight's outcome is RUN (the attachment requires RUN)
    "GATE-REQ-001": ("GNDCRW_PREFLIGHT_NOT_CLEARED",),
    # the request builder the profile names is installed
    "GATE-CAP-001": ("REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE",),
    # the adapter the profile names is installed and executes one attempt per record
    "GATE-CAP-002": ("REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE",),
    # the gate was evaluated at all
    "GATE-EVAL-001": ("VALIDATION_ONLY", "EXECUTION_PROFILE_ABSENT", "LEGACY_RUN_NOT_GATED",
                      "EXECUTION_GATE_NOT_RECORDED"),
}

#: the checked GNDCRW outcomes that do not clear the gate
PREFLIGHT_NOT_CLEARED = ("BLOCK", "UNVERIFIABLE")

#: what a gate record cannot prove by recomputation
RECORD_LIMITATIONS = ("EXECUTION_CAPABILITY_ATTESTED", "NOT_SIGNED")

#: the rules `verify_record` recomputes (not decision rules: evidence rules)
RECORD_RULES = ("GATE-REC-001", "GATE-REC-002", "GATE-REC-003")

#: canonical-json-1 has no null: an absent evidence_ref / identity is an absent member,
#: in memory as on the wire and at rest
REASON_MEMBERS = {"rule_id", "reason_code", "message_key", "params"}
REASON_OPTIONAL = {"evidence_ref"}
DOCUMENT_MEMBERS = {"schema", "execution_gate_status", "reasons", "subject"}
SUBJECT_MEMBERS = {"contract_identity", "experiment_input_identity"}


def message_key(code: str) -> str:
    return f"gate.reason.{code}"


def status_message_key(status: str) -> str:
    return f"gate.status.{status}"


def reason(rule_id: str, code: str, params: Mapping[str, Any] | None = None,
           evidence_ref: Mapping[str, Any] | None = None) -> dict:
    if code not in RULES.get(rule_id, ()):
        raise ValueError(f"unregistered execution gate reason {rule_id}/{code!r}")
    entry = {"rule_id": rule_id, "reason_code": code, "message_key": message_key(code),
             "params": dict(params or {})}
    if evidence_ref:
        entry["evidence_ref"] = dict(evidence_ref)
    return entry


def _order(entry: Mapping) -> tuple[str, str]:
    return (str(entry.get("rule_id")), str(entry.get("reason_code")))


def status_of(reasons: Sequence[Mapping]) -> str:
    established = {REASONS[r["reason_code"]] for r in reasons}
    return next((status for status in PRECEDENCE if status in established), CLEARED)


def decision(reasons: Sequence[Mapping], *, contract: str | None,
             eii: str | None) -> dict:
    ordered = sorted(reasons, key=_order)
    subject = {name: value for name, value in (("contract_identity", contract),
                                               ("experiment_input_identity", eii))
               if value is not None}
    return {"schema": SCHEMA, "execution_gate_status": status_of(ordered),
            "reasons": ordered, "subject": subject}


def not_evaluated(code: str, *, contract: str | None = None, eii: str | None = None,
                  params: Mapping[str, Any] | None = None) -> dict:
    return decision([reason("GATE-EVAL-001", code, params)], contract=contract, eii=eii)


# ------------------------------------------------------------------ evaluation
def _failing(result: Mapping, status: str) -> list[str]:
    return sorted(f["finding_id"] for f in result["findings"]
                  if f["policy_class"] == "BLOCKING" and f["status"] == status)


def preflight_reasons(preflight) -> list[dict]:
    """A checked BLOCK / UNVERIFIABLE GNDCRW outcome is an unmet mandatory requirement:
    a normal decision read off a result that checked, never a parse / contract error."""
    if preflight is None or preflight.outcome not in PREFLIGHT_NOT_CLEARED:
        return []
    from boomvalley_lab.core.layout import GNDCRW_RESULT_FILE, PREFLIGHT_DIR

    result = load_bytes(preflight.result)
    status = "FAIL" if preflight.outcome == "BLOCK" else "UNVERIFIABLE"
    return [reason("GATE-REQ-001", "GNDCRW_PREFLIGHT_NOT_CLEARED",
                   {"outcome": preflight.outcome, "required_outcome": "RUN",
                    "findings": _failing(result, status)},
                   {"locator": f"{PREFLIGHT_DIR}/{GNDCRW_RESULT_FILE}#/outcome",
                    "sha256": str(sha256_bytes(preflight.result)),
                    "size": len(preflight.result)})]


def capability_reasons(profile: Mapping) -> list[dict]:
    """Can THIS installation execute the profile? (a runtime fact, not a policy)"""
    from boomvalley_lab.experiment_input import profile as profiles

    root = Path(profiles.__file__).resolve().parent.parent
    found = []
    for rule_id, capability, key, pointer in (
            ("GATE-CAP-001", "request_builder", f"builder:{profile['request_builder']['id']}",
             "/request_builder/id"),
            ("GATE-CAP-002", "adapter", f"adapter:{profile['adapter']['kind']}",
             "/adapter/kind")):
        files = profiles.CODE_REGISTRY.get(key)
        missing = sorted(f for f in files or () if not (root / f).is_file())
        if files is None or missing:
            found.append(reason(rule_id, "REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE",
                                {"capability": capability, "implementation": key,
                                 "missing": missing,
                                 "detail": "not registered" if files is None else
                                 "implementation files are not installed"},
                                {"locator": f"{PROFILE_MEMBER}#{pointer}"}))
    if not any(r["rule_id"] == "GATE-CAP-002" for r in found):
        try:
            adapter, detail = profiles.adapter_for(profile), "max_attempts != 1"
        except Exception as error:  # noqa: BLE001 - a missing runtime, reported as data
            adapter, detail = None, f"{type(error).__name__}: {error}"
        if adapter is None or getattr(adapter, "max_attempts", None) != 1:
            found.append(reason("GATE-CAP-002", "REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE",
                                {"capability": "adapter",
                                 "implementation": f"adapter:{profile['adapter']['kind']}",
                                 "missing": [], "detail": detail},
                                {"locator": f"{PROFILE_MEMBER}#/adapter"}))
    return found


def evaluate(m, preflight) -> dict:
    """The gate over what I0..I6 established (`bvl check`, `bvl run`)."""
    from boomvalley_lab.experiment_input import lockdoc as docs

    reasons = preflight_reasons(preflight)
    if m.profile is None:
        reasons.append(reason("GATE-EVAL-001", "EXECUTION_PROFILE_ABSENT",
                              evidence_ref={"locator": "envelope#/execution"}))
        eii = None
    else:
        reasons += capability_reasons(m.profile)
        eii = None if (m.attachment is not None and preflight is None) else \
            docs.eii_of(docs.eii_preimage(m, preflight))
    return decision(reasons, contract=m.contract, eii=eii)


# ------------------------------------------------------------------ document checks
def problems(document: Any) -> list[str]:
    """A gate decision document means one thing: closed members, registered rules and
    codes, the status its reasons establish."""
    if not isinstance(document, dict) or set(document) != DOCUMENT_MEMBERS \
            or document.get("schema") != SCHEMA:
        return [f"not a closed {SCHEMA} decision"]
    found = []
    status = document["execution_gate_status"]
    if status not in STATUSES:
        found.append(f"execution_gate_status {status!r} is not registered")
    reasons = document["reasons"]
    if not isinstance(reasons, list):
        return [*found, "reasons is not a list"]
    good = []
    for index, entry in enumerate(reasons):
        where = f"reasons[{index}]"
        if not isinstance(entry, dict) or \
                not REASON_MEMBERS <= set(entry) <= REASON_MEMBERS | REASON_OPTIONAL:
            found.append(f"{where} is not a closed reason")
            continue
        code, rule_id = entry["reason_code"], entry["rule_id"]
        if code not in REASONS:
            found.append(f"{where}: reason_code {code!r} is not registered")
            continue
        if code not in RULES.get(rule_id, ()):
            found.append(f"{where}: rule_id {rule_id!r} does not state {code}")
            continue
        if entry["message_key"] != message_key(code):
            found.append(f"{where}: message_key {entry['message_key']!r}")
        if not isinstance(entry["params"], dict):
            found.append(f"{where}: params is not an object")
        if not isinstance(entry.get("evidence_ref", {}), dict) or entry.get("evidence_ref") == {}:
            found.append(f"{where}: evidence_ref is not an object")
        good.append(entry)
    keys = [_order(r) for r in reasons if isinstance(r, dict)]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        found.append("reasons are not unique and in (rule_id, reason_code) order")
    if status in STATUSES and len(good) == len(reasons):
        if status != status_of(good):
            found.append(f"status {status} is not the one its reasons establish "
                         f"({status_of(good)})")
        if status != CLEARED and not good:
            found.append(f"a {status} decision without a reason_code")
    subject = document["subject"]
    if not isinstance(subject, dict) or not set(subject) <= SUBJECT_MEMBERS or not all(
            isinstance(value, str) for value in subject.values()):
        found.append("subject is not {contract_identity?, experiment_input_identity?}")
    return found


# ------------------------------------------------------------------ the no-run record
def record_files(m, preflight) -> dict[str, bytes]:
    from boomvalley_lab.experiment_input import lockdoc as docs

    files = {DECLARATION_MEMBER: canonical_bytes(m.lock["declaration"])}
    if m.profile is not None:
        files[PROFILE_MEMBER] = canonical_bytes(m.profile)
    if preflight is not None:
        files.update({docs.member(name): data
                      for name, data in docs.preflight_files(m, preflight).items()})
    return files


def write_record(into: Path, gate: dict, files: Mapping[str, bytes], *, preflight,
                 label: str | None) -> dict:
    """A non-CLEARED `bvl run`: the decision and its evidence, written once. No run."""
    into = Path(into)
    if into.exists() and any(into.iterdir()):
        raise ExecutionError(f"{into} is not empty; a gate record is written once")
    if gate["execution_gate_status"] == CLEARED:
        raise ValueError("a gate record is written only for a decision that is not CLEARED")
    members = [{"path": path, "sha256": str(sha256_bytes(data)), "size": len(data)}
               for path, data in sorted(files.items())]
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA, "gate": gate, "run_label": label,
        "execution_status": NOT_STARTED, "members": members,
        "preflight": None if preflight is None else {
            "tool": dict(preflight.tool), "exit_code": preflight.exit_code,
            "outcome": preflight.outcome},
        "limitations": list(RECORD_LIMITATIONS),
    }
    data = canonical_bytes(record)
    into.mkdir(parents=True, exist_ok=True)
    for path, content in {**files, RECORD_FILE: data}.items():
        target = into / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    return record


def is_record(directory: Path) -> bool:
    return (Path(directory) / RECORD_FILE).is_file()


def verify_record(directory: Path) -> dict:
    """Recompute a gate record. VERIFIED says the evidence holds; the gate status
    says what it decided - the two are reported side by side, never merged."""
    from boomvalley_lab.core.layout import (
        GNDCRW_MANIFEST_FILE,
        GNDCRW_RESULT_FILE,
        GNDCRW_SUBJECT_FILES,
    )
    from boomvalley_lab.experiment_input import gndcrw
    from boomvalley_lab.experiment_input import lockdoc as docs
    from boomvalley_lab.experiment_input.envelope import GNDCRW_ATTACHMENT, ROLES

    directory = Path(directory)
    try:
        data = (directory / RECORD_FILE).read_bytes()
        record = load_bytes(data)
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"{RECORD_FILE} is unreadable: {error}") from error
    if not isinstance(record, dict) or record.get("schema") != RECORD_SCHEMA:
        raise EvidenceError(f"not a {RECORD_SCHEMA} record", code=UNSUPPORTED_SCHEMA)
    rules: dict[str, list[str]] = {}
    # GATE-REC-001 members: listed bytes, nothing else under the root
    found = []
    if canonical_bytes(record) != data:
        found.append(f"{RECORD_FILE} is not canonical-json-1 at rest")
    expected = {"schema", "gate", "run_label", "execution_status", "members", "preflight",
                "limitations"}
    if set(record) != expected:
        found.append(f"record members {sorted(record)}")
    held: dict[str, bytes] = {}
    for member in record.get("members") or []:
        path = member.get("path") if isinstance(member, dict) else None
        file = directory / str(path)
        if not isinstance(path, str) or not file.is_file() or file.is_symlink():
            found.append(f"member {path!r} is missing")
            continue
        held[path] = file.read_bytes()
        if {"sha256": str(sha256_bytes(held[path])), "size": len(held[path])} != \
                {k: member.get(k) for k in ("sha256", "size")}:
            found.append(f"{path}: not the listed bytes")
    present = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    found += [f"{p} is not a member" for p in sorted(present - set(held) - {RECORD_FILE})]
    if record.get("execution_status") != NOT_STARTED:
        found.append("a gate record is of an input whose execution was NOT_STARTED")
    if record.get("limitations") != list(RECORD_LIMITATIONS):
        found.append(f"limitations {record.get('limitations')}")
    rules["GATE-REC-001"] = found
    gate = record.get("gate")
    # GATE-REC-002 the decision is closed and coherent
    rules["GATE-REC-002"] = problems(gate)
    if rules["GATE-REC-002"]:
        rules["GATE-REC-003"] = ["the decision is not readable"]
        return _record_report(directory, record, rules)
    # GATE-REC-003 the subject and the preflight reasons recompute from the member bytes
    found = []
    declaration = held.get(DECLARATION_MEMBER)
    contract = None if declaration is None else str(sha256_bytes(declaration))
    if contract is None or gate["subject"].get("contract_identity") != contract:
        found.append("subject.contract_identity is not SHA-256(design/declaration.json)")
    else:
        try:
            from boomvalley_lab.identity.lock import lock as make_lock

            relocked = make_lock(load_bytes(declaration))["identities"]["contract"]
        except (BoomvalleyError, MalformedJSON) as error:
            relocked = f"unlockable: {error}"
        if relocked != contract:
            found.append("design/declaration.json does not lock to its own digest")
    profile = held.get(PROFILE_MEMBER)
    names = {role: docs.member(GNDCRW_SUBJECT_FILES[role]) for role in ROLES}
    manifest = held.get(docs.member(GNDCRW_MANIFEST_FILE))
    result_bytes = held.get(docs.member(GNDCRW_RESULT_FILE))
    preflight = record.get("preflight")
    derived: list[dict] = []
    if (manifest is None) != (result_bytes is None) or (manifest is None) != (preflight is None):
        found.append("the preflight members and the preflight facts disagree")
    elif manifest is not None and contract is not None:
        subjects = {role: held.get(path) for role, path in names.items()}
        if any(value is None for value in subjects.values()):
            found.append("a GNDCRW subject snapshot is missing")
        else:
            try:
                result = gndcrw.check_result(
                    result_bytes, manifest=manifest,
                    subjects={r: {"sha256": str(sha256_bytes(b)), "size": len(b)}
                              for r, b in subjects.items()},
                    contract=contract, version=str(preflight["tool"].get("version")),
                    exit_code=preflight.get("exit_code"), declaration=subjects["declaration"])
                if preflight.get("outcome") != result["outcome"] or \
                        preflight.get("tool") != result["tool"]:
                    found.append("the recorded preflight facts are not the result's")
                if manifest != gndcrw.manifest_bytes(
                        {r: _Held(b) for r, b in subjects.items()}, contract):
                    found.append("the GNDCRW manifest does not re-derive from C and the "
                                 "snapshots")
                derived = preflight_reasons(_Recomputed(result["outcome"], result_bytes))
            except BoomvalleyError as error:
                found.append(f"the GNDCRW result does not check: {error}")
    stated = [r for r in gate["reasons"] if r["rule_id"] == "GATE-REQ-001"]
    if manifest is not None and not found and stated != derived:
        found.append("the GATE-REQ-001 reasons are not the ones the recorded GNDCRW result "
                     "establishes")
    if gate["execution_gate_status"] == CLEARED:
        found.append("a gate record is written only for a decision that is not CLEARED")
    eii = gate["subject"].get("experiment_input_identity")
    if profile is not None and contract is not None and not found:
        preimage: dict[str, Any] = {"identity_schema": docs.IDENTITY_SCHEMA,
                                    "contract": contract,
                                    "execution": str(sha256_document(load_bytes(profile)))}
        if manifest is not None:
            preimage["pre_execution"] = {
                "contracts": dict(GNDCRW_ATTACHMENT["contracts"]),
                "external_subject": {"digest": contract,
                                     "scheme": "boomvalley-lab-contract-identity"},
                "inputs": {r: docs.raw(held[p]) for r, p in names.items()},
                "manifest": docs.raw(manifest),
                "manifest_version": GNDCRW_ATTACHMENT["manifest_version"],
                "policy": GNDCRW_ATTACHMENT["policy"],
                "require_outcome": GNDCRW_ATTACHMENT["require_outcome"],
                "result": docs.raw(result_bytes),
                "result_version": GNDCRW_ATTACHMENT["result_version"]}
        if canonical_bytes(load_bytes(profile)) != profile:
            found.append(f"{PROFILE_MEMBER} is not canonical at rest")
        if eii != docs.eii_of(preimage):
            found.append("subject.experiment_input_identity does not recompute")
    elif profile is None and eii is not None:
        found.append("an ExperimentInputIdentity with no execution profile member")
    rules["GATE-REC-003"] = found
    return _record_report(directory, record, rules)


class _Held:
    """A snapshot as `gndcrw.manifest_bytes` reads it: raw digest and size."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def raw(self) -> dict:
        return {"sha256": str(sha256_bytes(self.data)), "size": len(self.data)}


class _Recomputed:
    """A checked result as `preflight_reasons` reads it."""

    def __init__(self, outcome: str, result: bytes) -> None:
        self.outcome, self.result = outcome, result


def _record_report(directory: Path, record: dict, rules: dict[str, list[str]]) -> dict:
    verified = not any(rules.values())
    gate = record.get("gate") if isinstance(record.get("gate"), dict) else {}
    return {"gate_record": RECORD_FILE, "directory": str(directory), "verified": verified,
            "verification_status": VERIFIED if verified else REJECTED,
            "execution_gate_status": gate.get("execution_gate_status"),
            "execution_status": record.get("execution_status"),
            "execution_gate": gate or None,
            "rules": [{"rule_id": k, "verdict": "VIOLATED" if v else "VERIFIED",
                       "reasons": list(v)} for k, v in rules.items()],
            "limitations": record.get("limitations")}
