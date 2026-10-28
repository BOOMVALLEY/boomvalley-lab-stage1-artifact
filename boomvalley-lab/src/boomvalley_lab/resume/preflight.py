"""Preflight: the existing evidence is verified BEFORE the run is touched.

Resume is the one entry that meets evidence it did not write. Everything it
then does — opening a session, appending an event, accepting custody, calling
a provider — appends to a history whose validity it has not yet established.
If that history is already broken, every one of those actions makes the
broken run longer, harder to diagnose, and (for a provider-backed experiment)
more expensive; recording a helpful `RUN_ABORTED` on top of forged evidence
is itself a write onto evidence that was never this run's to extend.

    OD-04   an invalid existing prefix is REFUSED before any side effect:
            0 writes, 0 new sessions, 0 adapter calls
    R7      safe resume semantics — continuing is a decision over evidence,
            and evidence that cannot be true is not a decision to continue from

This module adds NO new notion of validity. It asks the questions the
already-authoritative validators ask, in the order they belong, and it asks
them at the one moment when refusing is still free:

    journal.session     who held the run and how the next writer was
                        authorised (R8, R15, R16, OD-02)
    journal.order       the run followed the registered schedule, in the
                        registered order (frozen schedule semantics)
    journal.serial      one attempt at a time: no two records' attempts were
                        in flight at once (sequential execution semantics)
    journal.grammar     each attempt's history could have happened, and is
                        attributed to this run and to a session that was open
                        (R1, R2, R3, R7, R18, R37)
    custody.seal        each accepted record still reconciles to the bytes:
                        the same chain a seal recomputes (R4, R13, R38, R41)
    resume.classify     the frozen R7 state of every record

and, for the paths that would open a new session, one question none of those
answer: may another writer join this history at all (`opening_problems`)?

What it deliberately does NOT refuse is an HONEST incomplete prefix. A run
whose session died after the intent, after the return, or after persistence
is not invalid — it is unfinished, and the frozen R7 policy already says what
may be done with each of those states. Preflight refuses histories that
contradict themselves, not histories that stopped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.custody.seal import Reconciliation, reconcile_entry, session_ledger
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.journal import grammar, serial
from boomvalley_lab.journal import order as schedule_order
from boomvalley_lab.journal import session as lifecycle
from boomvalley_lab.resume.classify import State, classify
from boomvalley_lab.resume.planner import TERMINAL
from boomvalley_lab.store.artifacts import ArtifactStore


def problems(*, run_id: str, identities: Mapping[str, str],
             records: Sequence[ExecutionRecord], journal: Sequence[Mapping],
             store: ArtifactStore, custody: Mapping[str, Sequence[Mapping]],
             state: str) -> list[str]:
    """Everything about this run's EXISTING evidence that forbids continuing.

    Read-only by construction: it opens nothing, appends nothing and calls
    nothing. An empty list means the prefix is one a new session may legally
    extend — not that the run is complete.
    """
    found: list[str] = []
    if state in TERMINAL:
        found.append(TERMINAL[state])
    # who was allowed to write, and how the next writer was authorised (F-003)
    found.extend(lifecycle.problems(journal, run_id))
    # the registered schedule is an order, not a set (F-002)
    found.extend(schedule_order.problems(records, journal))
    # and the run realised one record at a time (F-018)
    found.extend(serial.problems(journal))

    by_record: dict[str, list[Mapping]] = {}
    for event in journal:
        if "record" in event:
            by_record.setdefault(event["record"], []).append(event)
    context = grammar.RunContext.of(journal, run_id)
    for record in records:
        # a history that could not have happened (F-001)
        found.extend(grammar.problems(record.key, by_record.get(record.key, []), context))

    ledger = {session["session"] for session in session_ledger(journal)}
    reconciliation = Reconciliation()
    for position, record in enumerate(records):
        entries = custody.get(record.key, ())
        if len(entries) > 1:
            found.append(f"custody {record.key}: held more than once (R3)")
            continue
        if not entries:
            continue
        # the same recomputation a seal performs, on the prefix that exists
        reconcile_entry(reconciliation, record, position, entries[0],
                        by_record.get(record.key, []), run_id=run_id, identities=identities,
                        store=store, grammar=context, ledger=ledger)
    found.extend([*reconciliation.membership, *reconciliation.integrity,
                  *reconciliation.binding, *reconciliation.sessions])

    # and the frozen R7 reading of every record: INCONSISTENT is evidence that
    # contradicts itself, which is never a prefix to continue from. The other
    # states — including the unfinished ones — are the policy's business.
    try:
        classified = classify(records, journal, store, custody)
    except EvidenceError as error:
        # the journal or custody names something the lock does not: there is
        # no R7 state to read, and certainly nothing to continue
        found.append(str(error))
        return found
    for key, found_state in classified.items():
        if found_state.state is State.INCONSISTENT:
            found.append(f"{key}: INCONSISTENT — {found_state.reason}")
    return found


def holding_session(journal: Sequence[Mapping]) -> str | None:
    """The session the JOURNAL says still holds the run, if any."""
    for transition in lifecycle.transitions(journal):
        if transition.closed is None:
            return transition.session
    return None


def opening_problems(journal: Sequence[Mapping]) -> list[str]:
    """Whether a NEW session may be opened on top of this history (R8, OD-04).

    A history can be entirely valid and still be one no new writer may join.
    `journal.session.problems` answers "could this history have happened?",
    and under OD-02 the LAST session is allowed to have no close: it may still
    be running, and a sealing session's close necessarily postdates the seal.
    That exception is about READING a finished run. It is not permission to
    admit a second writer, and conflating the two is how a run acquires two
    holders.

    So the continuation asks its own question — and asks it of the journal,
    not of `sessions/ACTIVE`. The marker is a lock file: a run whose marker
    was deleted, never copied, or tidied up by something other than a release
    still has a journal that says who holds it. When the two disagree the
    journal is the evidence, because the journal is what the seal covers and
    what an auditor reads (R8, R15).

        history validity  !=  permission to open another session
    """
    held = holding_session(journal)
    if held is None:
        return []
    return [f"session {held!r} still holds the run according to the journal: it was never "
            "closed and no operator release authorised a next writer, so the run already "
            "has an active session and a second one may not open (R8)"]


def verified(*, action: str, run_id: str, identities: Mapping[str, str],
             records: Sequence[ExecutionRecord], journal: Sequence[Mapping],
             store: ArtifactStore, custody: Mapping[str, Sequence[Mapping]],
             state: str, opening: bool) -> None:
    """Refuse `action` unless the existing prefix verifies. Writes nothing (OD-04).

    `opening` says whether this action would open a NEW session. Continuation
    (execute, resume, recover) does; an operator `release` does not — a
    release exists precisely to close the session that is still holding the
    run, so the state that forbids a new writer is its precondition.
    """
    found = problems(run_id=run_id, identities=identities, records=records, journal=journal,
                     store=store, custody=custody, state=state)
    if opening:
        found.extend(opening_problems(journal))
    elif state == "SEALED":
        # closing the session that died holding a sealed run is its close,
        # which necessarily postdates the seal (CUSTODY §3); SEALED forbids a
        # new writer, not that close (RUNTIME §2 release_stale)
        found = [problem for problem in found if problem != TERMINAL["SEALED"]]
    if not found:
        return
    raise ExecutionError(
        f"run {run_id} cannot be {action}: its existing evidence does not verify, so "
        f"nothing was opened, written or called (OD-04); first of {len(found)}: {found[0]}",
        problems=tuple(found),
    )
