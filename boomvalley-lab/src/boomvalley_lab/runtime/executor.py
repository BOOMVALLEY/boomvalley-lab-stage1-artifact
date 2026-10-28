"""The executor: a locked schedule, in order, one attempt per record.

For each record the classifier says to EXECUTE, in the locked order:

    build payload from the record alone -> request document -> RequestIdentity
    INTENT_RECORDED (durable)            ... only then:
    adapter.call(request)                -> exception: CALL_FAILED, ABORT
    validate response                    -> malformed: RESPONSE_REJECTED, ABORT
    CALL_RETURNED (actual execution read off the response, response digest)
    store.put + read back                -> failure: ABORT (returned, not persisted)
    ARTIFACT_PERSISTED

Before the loop the resume planner decides for the whole run (one
assessment source, shared with `status` and `resume`): any ABORT state ->
the run is ABORTED; any OPERATOR_DECISION state -> refused, left OPEN for
Phase 4. PERSISTED records are skipped. Nothing is retried, reordered,
batched or parallelised.

Before ANY of that — before the session is acquired — whatever evidence the
run already carries is verified (`resume.preflight`). A prefix that does not
verify is refused with nothing opened, written or called (OD-04); a fresh run
has no prefix and pays nothing for the check.

`hook(boundary)` exists for crash injection. A `BaseException` escaping the
loop (a crash, SimulatedCrash, KeyboardInterrupt) leaves the session marker
in place — exactly what a dead process leaves — so the next session is
refused until an operator releases it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.custody.entries import CustodyLedger, accept
from boomvalley_lab.custody.seal import seal
from boomvalley_lab.identity.kinds import RequestIdentity, SessionIdentity
from boomvalley_lab.journal import events as ev
from boomvalley_lab.resume import preflight
from boomvalley_lab.resume.classify import Decision
from boomvalley_lab.resume.planner import assess
from boomvalley_lab.runtime.adapter import (
    Adapter,
    AdapterRequest,
    RequestBuilder,
    ResponseRejected,
    request_document,
    validate_response,
)
from boomvalley_lab.runtime.run import Run
from boomvalley_lab.runtime.session import acquire, release
from boomvalley_lab.store.artifacts import artifact_name

BOUNDARIES = (
    "before_intent", "after_intent", "after_return", "after_returned_event",
    "after_persist", "after_persisted_event", "after_custody",
)


class SimulatedCrash(BaseException):  # noqa: N818 - it is a crash, not an error
    """Test-only: the process dies at a boundary."""


@dataclass(frozen=True)
class ExecutionSummary:
    session: str
    executed: int
    skipped: int
    remaining: int


def attempt_id(record_key: str) -> str:
    return f"{record_key}#a1"  # one attempt per record in MVP


def execute(run: Run, adapter: Adapter, build_request: RequestBuilder, *,
            clock: Callable[[], str], hook: Callable[[str], None] | None = None,
            stop_after: int | None = None) -> ExecutionSummary:
    hook = hook or (lambda boundary: None)
    if getattr(adapter, "max_attempts", None) != 1:
        raise ExecutionError(
            "the adapter may realise a request more than once (max_attempts != 1); "
            "MVP has one attempt per record and no hidden retry"
        )
    intended = ev.execution_document(getattr(adapter, "intended", None), "adapter.intended")
    # OD-04: whatever evidence is already here is verified BEFORE a session is
    # opened, before a line is journaled and before the adapter is touched. A
    # fresh run has no prefix, so this costs it nothing; a broken one is
    # refused while refusing is still free.
    preflight.verified(
        action="executed", run_id=run.run_id, identities=run.lock["identities"],
        records=run.records, journal=run.events(), store=run.store,
        custody=CustodyLedger(run.directory).by_record(), state=run.state().value,
        opening=True,
    )
    session = acquire(run, at=clock())
    try:
        summary = _loop(run, session, adapter, intended, build_request, clock, hook, stop_after)
    except ExecutionError:
        raise
    except Exception as error:  # an unexpected failure is still a controlled stop
        _abort(run, session, f"unexpected failure: {error!r}", clock)
        raise ExecutionError(f"run {run.run_id} aborted: {error!r}") from error
    release(run, session, at=clock())
    return summary


def _abort(run: Run, session: SessionIdentity, reason: str, clock) -> None:
    run.journal.append({"event": ev.RUN_ABORTED, "run": run.run_id, "session": str(session),
                        "reason": reason, "at": clock()})
    release(run, session, at=clock())


def _loop(run, session, adapter, intended, build_request, clock, hook, stop_after):
    records = run.records
    ledger = CustodyLedger(run.directory)
    planned = assess(records, run.events(), run.store, ledger.by_record())
    decisions = {p.record: p.decision for p in planned}
    abort = [p for p in planned if p.decision is Decision.ABORT]
    if abort:
        _abort(run, session, f"{abort[0].record}: {abort[0].state} ({abort[0].reason})", clock)
        raise ExecutionError(
            f"run {run.run_id} aborted: {len(abort)} record(s) in an unsafe state, "
            f"first {abort[0].record} {abort[0].state}"
        )
    waiting = [p for p in planned if p.decision is Decision.OPERATOR_DECISION]
    if waiting:
        release(run, session, at=clock())
        raise ExecutionError(
            f"run {run.run_id} needs an operator decision for {len(waiting)} record(s), "
            f"first {waiting[0].record} {waiting[0].state}"
        )
    executed = skipped = 0
    base = {"run": run.run_id, "session": str(session)}
    for position, record in enumerate(records):
        if decisions[record.key] is Decision.SKIP:
            skipped += 1
            continue
        if stop_after is not None and executed >= stop_after:
            break
        attempt = {**base, "record": record.key, "attempt": attempt_id(record.key)}
        document = request_document(record, build_request(record))
        identity = RequestIdentity.of_document(document)
        hook("before_intent")
        run.journal.append({**attempt, "event": ev.INTENT_RECORDED, "at": clock(),
                            "position": position, "request": str(identity.digest),
                            "intended": intended})
        hook("after_intent")
        try:
            response = adapter.call(AdapterRequest(record.key, identity, document["payload"]))
        except Exception as error:
            run.journal.append({**attempt, "event": ev.CALL_FAILED, "at": clock(),
                                "error": repr(error)})
            _abort(run, session, f"{record.key}: call outcome unknown ({error!r})", clock)
            raise ExecutionError(f"run {run.run_id} aborted: the call for {record.key} "
                                 f"failed and its outcome is unknown") from error
        hook("after_return")
        try:
            response = validate_response(response)
        except ResponseRejected as error:
            run.journal.append({**attempt, "event": ev.RESPONSE_REJECTED, "at": clock(),
                                "reason": str(error)})
            _abort(run, session, f"{record.key}: malformed response ({error})", clock)
            raise ExecutionError(f"run {run.run_id} aborted: malformed response for "
                                 f"{record.key}") from error
        content = bytes(response.content)
        run.journal.append({
            **attempt, "event": ev.CALL_RETURNED, "at": clock(),
            "actual_execution": {"model_identity": response.model_identity,
                                 "adapter_provenance": response.adapter_provenance},
            "response": str(sha256_bytes(content)),
            # present only when a derivation performed this realisation (R41)
            "derivation": response.derivation,
        })
        hook("after_returned_event")
        try:
            ref = run.store.put(artifact_name(position), content)
        except Exception as error:
            _abort(run, session, f"{record.key}: returned but not persisted ({error!r})", clock)
            raise ExecutionError(f"run {run.run_id} aborted: {record.key} returned but its "
                                 "artifact was not persisted") from error
        hook("after_persist")
        run.journal.append({**attempt, "event": ev.ARTIFACT_PERSISTED, "at": clock(),
                            "artifact": ref.name, "artifact_content": str(ref.content.digest)})
        hook("after_persisted_event")
        try:
            accept(run.directory, run_id=run.run_id, identities=run.lock["identities"],
                   records=records, record_key=record.key, session=str(session),
                   journal=run.events(), store=run.store, at=clock())
        except Exception as error:
            _abort(run, session, f"{record.key}: persisted but not accepted ({error!r})", clock)
            raise ExecutionError(f"run {run.run_id} aborted: {record.key} was persisted but "
                                 "custody refused it") from error
        hook("after_custody")
        executed += 1
    remaining = len(records) - skipped - executed
    if not remaining:
        _seal(run, session, clock)
    return ExecutionSummary(str(session), executed, skipped, remaining)


def _seal(run: Run, session: SessionIdentity, clock) -> None:
    """The whole locked schedule is in custody: seal the run once (R2, R5, R15)."""
    head = seal(run.directory, run_id=run.run_id, identities=run.lock["identities"],
                records=run.records, journal=run.events(), at=clock(), session=str(session))
    run.journal.append({"event": ev.RUN_SEALED, "run": run.run_id, "session": str(session),
                        "custody": head["custody"], "seal": head["seal"],
                        "entries": head["entries"], "at": clock()})
