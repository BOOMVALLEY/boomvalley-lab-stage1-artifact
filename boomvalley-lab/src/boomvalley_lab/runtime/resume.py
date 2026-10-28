"""Resuming a run: the operator surface over the resume planner.

    plan_for(run)      read-only. What the evidence says and whether a new
                       session may continue (no session is acquired).
    resume(run, …)     continue a permitted run: skip what is complete,
                       execute only records the evidence proves were never
                       called. Refuses without opening a session when an
                       operator decision is outstanding; lets the executor
                       record the terminal abort when a state is unsafe.
    recover(run, …)    the ONLY way a persisted-but-unaccepted artifact
                       enters custody: an operator names their decision, the
                       whole evidence chain is re-verified, and the entry is
                       written with origin RECOVERED (R16).
    release(run, …)    an operator releases a session that died holding the
                       run, as durable evidence (R8, R15).

Every entry that WRITES — resume, recover, release — first verifies the
evidence that is already there (`resume.preflight`). An existing prefix that
does not verify is refused with nothing opened, nothing written and nothing
called, including the terminal abort a kinder implementation would record on
its way out (OD-04). A run that merely stopped is not "invalid": the frozen
R7 policy still decides what may be done with each incomplete state.

Nothing here retries, replays, repairs or infers. Resume never produces a
second realisation of a record: there is one attempt per record and no
attempt is ever re-opened.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.custody.entries import CustodyLedger
from boomvalley_lab.custody.entries import recover as accept_recovered
from boomvalley_lab.resume import preflight
from boomvalley_lab.resume.classify import Decision
from boomvalley_lab.resume.planner import TERMINAL, ResumePlan, RunEvidence, plan
from boomvalley_lab.runtime.adapter import Adapter, RequestBuilder
from boomvalley_lab.runtime.executor import ExecutionSummary, execute
from boomvalley_lab.runtime.run import Run
from boomvalley_lab.runtime.session import acquire, active_session, release_stale


def evidence(run: Run) -> RunEvidence:
    """Everything the planner may look at — and nothing else."""
    return RunEvidence(
        run=run.run_id,
        identities=run.lock["identities"],
        records=run.records,
        journal=run.events(),
        store=run.store,
        custody=CustodyLedger(run.directory).by_record(),
        state=run.state().value,
        active_session=active_session(run),
    )


def plan_for(directory: Path | str) -> ResumePlan:
    """Plan a run on disk. The lock is re-verified before anything is read."""
    return plan(evidence(Run.open(Path(directory))))


def _verified(found: RunEvidence, *, action: str, opening: bool) -> None:
    """OD-04: the existing prefix is verified before this run is touched at all.

    `opening` is True for the paths that would open a new session. A release
    opens none — it closes the one the journal still shows holding the run —
    so it is not held to the new-writer rule it exists to resolve.
    """
    preflight.verified(action=action, run_id=found.run, identities=found.identities,
                       records=found.records, journal=found.journal, store=found.store,
                       custody=found.custody, state=found.state, opening=opening)


def _mode(directory: Path | str, input_locked: bool) -> None:
    """Which resume this is, decided from the JOURNAL before anything is written.

    The legacy path (`input_locked=False`) refuses an INPUT_LOCKED or unanchored
    directory in the §10.7 order (IR-06). The `bvl` path has already verified
    the Input Lock (ILV) and only confirms the anchor is still VALID.
    """
    from boomvalley_lab.journal.anchor import AnchorState, classify, legacy_guard
    from boomvalley_lab.journal.log import Journal

    if not input_locked:
        legacy_guard(Path(directory))
    elif classify(Journal(Path(directory)).read()).state is not AnchorState.VALID:
        raise ExecutionError(f"{directory} is not an INPUT_LOCKED run")


def resume(directory: Path | str, adapter: Adapter, build_request: RequestBuilder, *,
           clock: Callable[[], str], stop_after: int | None = None,
           input_locked: bool = False) -> ExecutionSummary:
    _mode(directory, input_locked)
    run = Run.open(Path(directory))
    found = evidence(run)
    current = plan(found)
    if current.state in TERMINAL:
        raise ExecutionError(f"run {run.run_id} cannot be resumed: {TERMINAL[current.state]}")
    if current.active_session:
        raise ExecutionError(
            f"run {run.run_id} cannot be resumed: {current.blocking[0]}"
        )
    _verified(found, action="resumed", opening=True)
    unsafe = [p for p in current.records if p.decision is Decision.ABORT]
    if not unsafe and current.operator_decisions:
        raise ExecutionError(
            f"run {run.run_id} needs an operator decision for "
            f"{len(current.operator_decisions)} record(s), first "
            f"{current.operator_decisions[0]}; no session was opened"
        )
    # unsafe states are not refused quietly: the executor opens a session,
    # records RUN_ABORTED and closes it, so the terminal decision is evidence.
    return execute(run, adapter, build_request, clock=clock, stop_after=stop_after)


def recover(directory: Path | str, record_key: str, *, operator: str, decision: str,
            clock: Callable[[], str], input_locked: bool = False) -> dict:
    """Operator-confirmed custody recovery of one PERSISTED_UNRECORDED record."""
    if not operator.strip() or not decision.strip():
        raise ExecutionError("recovery records who decided, and what they decided (R16)")
    _mode(directory, input_locked)
    run = Run.open(Path(directory))
    found = evidence(run)
    current = plan(found)
    if current.state in TERMINAL:
        raise ExecutionError(f"run {run.run_id}: {TERMINAL[current.state]}")
    if current.active_session:
        raise ExecutionError(f"run {run.run_id}: {current.blocking[0]}")
    _verified(found, action="recovered", opening=True)
    planned = {p.record: p for p in current.records}.get(record_key)
    if planned is None:
        raise ExecutionError(
            f"{record_key} is not a record of this run's locked schedule"
        )
    if planned.decision is not Decision.OPERATOR_DECISION:
        raise ExecutionError(
            f"{record_key} is {planned.state.value}, whose frozen decision is "
            f"{planned.decision.value}; only a persisted artifact that custody never "
            "accepted may be recovered"
        )
    session = acquire(run, at=clock())  # a write to the run happens in a session
    try:
        entry = accept_recovered(
            run.directory, run_id=run.run_id, identities=run.lock["identities"],
            records=run.records, record_key=record_key, session=str(session),
            journal=run.events(), store=run.store, at=clock(),
            operator_decision=f"{operator}: {decision}",
        )
    finally:
        from boomvalley_lab.runtime.session import release
        release(run, session, at=clock())
    return entry


def release(directory: Path | str, *, operator: str, decision: str,
            clock: Callable[[], str], input_locked: bool = False) -> str:
    """Release the session that died holding a run. Durable evidence (R8, R15)."""
    if not operator.strip() or not decision.strip():
        raise ExecutionError("a release records who released the run, and why")
    _mode(directory, input_locked)
    run = Run.open(Path(directory))
    held = active_session(run)
    if held is None:
        raise ExecutionError(f"run {run.run_id} is not held by any session")
    # a release is durable evidence too, so it is not written onto a prefix
    # that does not verify (OD-04)
    _verified(evidence(run), action="released", opening=False)
    release_stale(run, held, operator=operator, at=clock(), decision=decision)
    return held
