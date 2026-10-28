"""`bvl` operations, one process each (Input Contract §10.1, §22).

    validate  I0..I5                        writes nothing; gate NOT_EVALUATED
    check     I0..I6 -> execution gate      writes nothing (the private GNDCRW
                                            staging directory is removed)
    run       I0..I5 -> schedule preflight (#153, `--expect-schedule`: EXACT_MATCH or
                                            refuse, nothing created) -> I4 -> I6
                                         -> experiment-input preflight (#175,
                                            `--expect-experiment-input`: EXACT_MATCH or
                                            refuse, nothing created) -> execution gate
                                         -> CLEARED: adapter identity (#176:
                                            OLLAMA_IDENTITY_MISMATCH -> refuse, 0 calls,
                                            nothing created) -> I7 -> Run.create -> PC-1..8 ->
                                            Run.open -> ILV -> execute
                                         -> not CLEARED: a gate record, no run (#76 C)
    status    classification + ILV (read-only) + the legacy status
    resume    ILV (read-only, before any write) -> the legacy resume machinery
              with the adapter and builder from input.json only

There is no editable state between GNDCRW and run creation: everything from I0
to the INPUT_LOCK_BOUND line is computed and written in one invocation, from
bytes read once.

#76 B: an Input Lock is written once, into a directory that holds no run. A
`run --into` an existing run is refused (`INPUT_LOCK_RELOCK_REFUSED`) before
anything is read or written: a changed input is a new ExperimentInputIdentity
and a new run, never a re-lock of the old one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.experiment_input import gate as gates
from boomvalley_lab.experiment_input import gndcrw, verify
from boomvalley_lab.experiment_input import input_gate as inputs
from boomvalley_lab.experiment_input import lockdoc as docs
from boomvalley_lab.experiment_input import profile as profiles
from boomvalley_lab.experiment_input import schedule_gate as schedules
from boomvalley_lab.experiment_input.envelope import (
    Materialized,
    check_for_run,
    check_run_combination,
    materialize,
)
from boomvalley_lab.experiment_input.errors import InputRefusal, drift

LIMITATION_WORDING = ("GNDCRW preflight: RUN (producer assertion; surface-scoped external "
                      "subject, provider-attested)")


def _summary(m: Materialized) -> dict:
    identities = m.lock["identities"]
    return {
        "experiment": m.lock["declaration"]["experiment"]["id"],
        "records": m.lock["summary"]["execution_records"],
        "contract_identity": identities["contract"],
        "design_identity": identities["design"],
        "schedule_identity": identities["schedule"],
        "run_label": m.label,
        "gndcrw_attached": m.attachment is not None,
        "gndcrw_subjects": {role: s.raw() for role, s in m.subjects.items()} or None,
    }


def validate(path: Path) -> dict:
    """I0..I5. The ContractIdentity it reports is what a surface producer stamps
    into `provenance.input_digests["boomvalley-lab-contract-identity"]` (GM-07)."""
    m = materialize(path)
    gate = gates.not_evaluated("VALIDATION_ONLY", contract=m.contract)
    return {"valid": True, **_summary(m), "execution_gate": gate,
            "execution_gate_status": gate["execution_gate_status"]}


def _preflight(m: Materialized, gndcrw_path: str | None) -> gndcrw.Preflight | None:
    if m.attachment is None:
        return None
    executable = gndcrw.probe(gndcrw_path)                                 # I4 (6)
    return gndcrw.invoke(executable, m.subjects, m.contract)               # I6


def _preflight_report(m: Materialized, preflight: gndcrw.Preflight | None) -> dict | None:
    if preflight is None:
        return None
    wording = (LIMITATION_WORDING if preflight.outcome == "RUN" else
               f"GNDCRW preflight: {preflight.outcome} (the attachment requires RUN)")
    return {"outcome": preflight.outcome, "wording": wording,
            "tool": preflight.tool, "executable": preflight.executable.document(),
            "integration_baseline": gndcrw.baseline(preflight.tool),
            "manifest": docs.raw(preflight.manifest), "result": docs.raw(preflight.result),
            "external_subject": {"scheme": "boomvalley-lab-contract-identity",
                                 "digest": m.contract},
            "limitations": list(docs.PREFLIGHT_LIMITATIONS)}


def _schedule_preflight(m: Materialized, expect_schedule, comparator) -> dict:
    """#153: the schedule gate's decision (NOT_REQUESTED without `--expect-schedule`)."""
    if expect_schedule is None:
        return schedules.not_requested()
    return schedules.evaluate(m.lock, expect_schedule, comparator=comparator)


def _reported(scheduled: dict, gated: dict | None = None) -> dict:
    """The decisions as result members; each absent when its gate was not asked for, so
    a run without `--expect-schedule` / `--expect-experiment-input` reports exactly what
    it did before #153 / #175."""
    found = ({} if scheduled["schedule_preflight_status"] == schedules.NOT_REQUESTED else
             {"schedule_preflight": scheduled})
    if gated is not None and gated["experiment_input_preflight_status"] != inputs.NOT_REQUESTED:
        found["experiment_input_preflight"] = gated
    return found


def _input_preflight(m: Materialized, preflight, expect_experiment_input) -> dict:
    """#175: the experiment-input gate's decision (NOT_REQUESTED without the option)."""
    if expect_experiment_input is None:
        return inputs.not_requested()
    return inputs.evaluate(m, preflight, expect_experiment_input)


def _identity_preflight(adapter) -> None:
    """#176 (BVVH #174 MINOR-1): an adapter that can resolve what would answer
    (`check_identity`, the Ollama adapter) is asked once before a run is created or
    resumed. Another identity than the pinned one is refused with no model call and
    nothing created (`OLLAMA_IDENTITY_MISMATCH`, exit 4); a server that cannot be
    resolved is a capability failure (exit 5). The adapter asks again before every
    chat, so drift during a run aborts it with no chat for that record."""
    probe = getattr(adapter, "check_identity", None)
    if probe is None:
        return
    from boomvalley_lab.runtime.adapters.ollama import OllamaError

    try:
        probe()
    except OllamaError as error:
        klass = ("EXECUTION_IDENTITY_REFUSAL" if error.code == "OLLAMA_IDENTITY_MISMATCH"
                 else "CAPABILITY_ERROR")
        raise InputRefusal(klass, error.code, str(error), layer="I4",
                           path="profile#/adapter", evidence={"model_calls": 0}) from None


def check(path: Path, *, gndcrw_path: str | None = None, expect_schedule=None,
          schedule_comparator=None, expect_experiment_input=None) -> dict:
    """The same pre-execution envelope as `run`, in the same order, writing nothing:
    whatever `run` refuses before its first model call, `check` refuses the same way."""
    m = materialize(path)
    scheduled = _schedule_preflight(m, expect_schedule, schedule_comparator)
    if expect_schedule is not None:
        schedules.enforce(scheduled)                  # #153: a check that fails, fails
    if m.profile is not None:
        check_run_combination(m)                      # #175 / MINOR-3: run's I4 parity
    preflight = _preflight(m, gndcrw_path)
    gated = _input_preflight(m, preflight, expect_experiment_input)
    if expect_experiment_input is not None:
        inputs.enforce(gated)                         # #175: exit 4 unless exact
    report = {"checked": True, **_summary(m), "preflight": _preflight_report(m, preflight),
              **_reported(scheduled, gated)}
    if m.profile is not None and (preflight is not None or m.attachment is None):
        # #175: the identity `run` will lock - what `--expect-experiment-input` freezes
        preimage = docs.eii_preimage(m, preflight)
        report["experiment_input_identity"] = docs.eii_of(preimage)
    report["execution_gate"] = gates.evaluate(m, preflight)
    report["execution_gate_status"] = report["execution_gate"]["execution_gate_status"]
    return report


#: #80: the registered reason (`core.codes.INPUT_LOCK_RELOCK_REASONS`) a re-lock refusal
#: states - the contract boundary: a changed input needs a new EII and a new run
RELOCK_REASON = "RELOCK_REQUIRES_NEW_EII_NEW_RUN"
#: #76 B / #80: every name a run (or its gate record) leaves in its directory. Any one of
#: them means the directory already belongs to a run lineage.
RUN_RESIDUE = ("journal.jsonl", "input.json", "run.json", "lock.json", "preflight",
               "sessions", "custody", "artifacts", "EVIDENCE.json", "PACKAGE.json",
               gates.RECORD_FILE, schedules.RECORD_FILE, inputs.RECORD_FILE)


def _held_identity(into: Path) -> dict:
    """What the directory says it already is: its run id and EII, read for the refusal
    evidence only (an unreadable file is simply not reported; it decides nothing)."""
    from boomvalley_lab.core.strict_json import load_file

    found = {}
    for name, key, member in (("run.json", "run", "held_run"),
                              ("input.json", "experiment_input_identity",
                               "held_experiment_input_identity")):
        try:
            document = load_file(into / name)
        except (OSError, BoomvalleyError, ValueError):
            continue
        if isinstance(document, dict) and isinstance(document.get(key), str):
            found[member] = document[key]
    return found


def refuse_relock(into: Path) -> None:
    """#76 B / #80: the Input Lock of a run is never re-bound (no same-run re-lock).

    Fail closed, before the experiment is read and before anything is written: a
    directory holding any run residue is refused whatever input is offered - the same
    one or a changed one. A changed locked input / declaration / profile is a new
    ExperimentInputIdentity, and a new EII is a new run lineage in a new directory.
    """
    into = Path(into)
    held = [name for name in RUN_RESIDUE if (into / name).exists()]
    if held:
        raise InputRefusal(
            "IDENTITY_ERROR", "INPUT_LOCK_RELOCK_REFUSED",
            f"{into} already holds a run or a gate record ({', '.join(held)}); its Input Lock "
            "is never re-bound. A changed input is a new ExperimentInputIdentity and a new "
            "run (a new run label, a new directory)", layer="I7", path="argv#/into",
            evidence={"held": held, **_held_identity(into), "reason": RELOCK_REASON})


def run(path: Path, into: Path, *, clock: Callable[[], str], gndcrw_path: str | None = None,
        stop_after: int | None = None, expect_schedule=None,
        schedule_comparator=None, expect_experiment_input=None) -> dict:
    from boomvalley_lab.runtime.executor import execute
    from boomvalley_lab.runtime.run import InputLockArtifacts, Run, opened_event

    refuse_relock(Path(into))                                               # #76 B
    m = materialize(path)                                                   # I0..I5
    scheduled = _schedule_preflight(m, expect_schedule, schedule_comparator)  # #153
    if expect_schedule is not None and not schedules.passed(scheduled):
        # fail closed: no run, no session, no adapter - only the evidence of that
        record = schedules.write_record(Path(into), scheduled, at=clock())
        raise schedules.refusal(scheduled, record=record)
    check_for_run(m)                                                        # I4
    preflight = _preflight(m, gndcrw_path)                                  # I4 (6), I6
    gated = _input_preflight(m, preflight, expect_experiment_input)         # #175
    if expect_experiment_input is not None and not inputs.passed(gated):
        # fail closed: no gate record, no run, no session, no adapter - only this evidence
        record = inputs.write_record(Path(into), gated, at=clock())
        raise inputs.refusal(gated, record=record)
    decided = gates.evaluate(m, preflight)                                  # #76 C
    if decided["execution_gate_status"] != gates.CLEARED:
        # a normal decision, not an error: no run is created and nothing executes
        record = gates.write_record(Path(into), decided, gates.record_files(m, preflight),
                                    preflight=preflight, label=m.label)
        return {"run": None, "directory": str(into),
                "execution_status": gates.NOT_STARTED,
                "execution_gate_status": decided["execution_gate_status"],
                "execution_gate": decided, "gate_record": gates.RECORD_FILE,
                "contract_identity": m.contract,
                "experiment_input_identity": decided["subject"].get("experiment_input_identity"),
                "preflight": _preflight_report(m, preflight),
                **_reported(scheduled, gated),
                "members": [member["path"] for member in record["members"]]}
    adapter = profiles.adapter_for(m.profile)
    _identity_preflight(adapter)                                            # #176
    binding = profiles.binding(m.profile)
    document = docs.input_lock(m, preflight, binding)                       # I7 in memory
    eii = document["experiment_input_identity"]
    input_bytes = docs.input_bytes(document)
    identities = m.lock["identities"]
    run_bytes = canonical_bytes(docs.run_projection(m.label, identities, input_bytes, eii))
    at = clock()
    anchor = docs.anchor_event(m.label, input_bytes, eii, at)
    files = docs.preflight_files(m, preflight) if preflight is not None else {}
    artifacts = InputLockArtifacts(preflight=files, input_bytes=input_bytes,
                                   run_bytes=run_bytes, anchor=anchor)
    Run.create(Path(into), m.lock, m.label, at=at, input_lock=artifacts)    # IR-02
    verify.post_create(Path(into), lock_bytes=canonical_bytes(m.lock),       # PC-1..8
                       input_bytes=input_bytes, run_bytes=run_bytes,
                       opened=opened_event(m.label, identities, at), anchor=anchor,
                       preflight=files, binding=binding, profile=m.profile)
    try:
        opened = Run.open(Path(into))
    except BoomvalleyError as error:
        raise drift("INPUT_LOCK_SUBSTITUTED", f"the created run does not open: {error}",
                    layer="I7") from None
    locked = verify.verify_input_lock(opened.directory)                     # ILV-1..15
    if locked.identity != eii:
        raise drift("EII_MISMATCH", "the verified Input Lock is not the one just written")
    if expect_schedule is not None:
        schedules.bind(scheduled, opened)                                   # #153 req 6
    if expect_experiment_input is not None:
        inputs.bind(gated, locked.identity)                                 # #175
    summary = execute(opened, adapter,                                       # the in-memory
                      profiles.builder_for(m.profile), clock=clock,          # profile (§10.6)
                      stop_after=stop_after)
    return {
        "run": opened.run_id, "directory": str(opened.directory),
        "execution_status": gates.STARTED,
        "execution_gate_status": decided["execution_gate_status"], "execution_gate": decided,
        "experiment_input_identity": eii,
        "input_digest": anchor["input_digest"],
        "contract_identity": identities["contract"],
        "preflight": _preflight_report(m, preflight),
        **_reported(scheduled, gated),
        "executed": summary.executed, "skipped": summary.skipped,
        "remaining": summary.remaining, "state": opened.state().value,
    }


def status(directory: Path) -> dict:
    from boomvalley_lab.runtime.status import status as legacy_status

    found = verify.classification(Path(directory))
    report = {"input_lock": found}
    try:
        report.update(legacy_status(Path(directory)))
    except BoomvalleyError as error:
        report["run_error"] = str(error)
    return report


def resume(directory: Path, *, clock: Callable[[], str], stop_after: int | None = None,
           plan: bool = False, release: tuple[str, str] | None = None,
           recover: tuple[str, str, str] | None = None) -> dict:
    """ILV first, read-only; only then any write (Input Contract §10.5)."""
    from boomvalley_lab.runtime import resume as legacy

    directory = Path(directory)
    locked = verify.verify_input_lock(directory)
    bound = {"experiment_input_identity": locked.identity, "input_digest": locked.digest,
             "input_lock": "INPUT_LOCK_OK"}
    if plan:
        return {"planned": True, **bound, **legacy.plan_for(directory).document()}
    if release is not None:
        operator, decision = release
        released = legacy.release(directory, operator=operator, decision=decision, clock=clock,
                                  input_locked=True)
        return {"released": released, **bound, **legacy.plan_for(directory).document()}
    if recover is not None:
        record, operator, decision = recover
        entry = legacy.recover(directory, record, operator=operator, decision=decision,
                               clock=clock, input_locked=True)
        return {"recovered": entry["record"], "origin": entry["origin"], **bound,
                **legacy.plan_for(directory).document()}
    adapter = profiles.adapter_for(locked.profile)
    _identity_preflight(adapter)                                            # #176
    summary = legacy.resume(directory, adapter,
                            profiles.builder_for(locked.profile), clock=clock,
                            stop_after=stop_after, input_locked=True)
    return {"executed": summary.executed, "skipped": summary.skipped,
            "remaining": summary.remaining, **bound, **legacy.plan_for(directory).document()}


__all__ = ["InputRefusal", "check", "resume", "run", "status", "validate"]
