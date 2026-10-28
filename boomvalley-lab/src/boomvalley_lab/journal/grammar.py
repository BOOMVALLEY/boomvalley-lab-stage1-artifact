"""The legal temporal grammar of the journal — what could actually have happened.

A valid set of events is not a valid history. Downstream verification that
counts events accepts orderings no execution could produce: a persistence
recorded before the call returned, a failure recorded after a return, an
attempt continued after the run was terminated. This module states the grammar
once, derived from the frozen semantics rather than from what the writer
happens to emit, so every reader asks the same question.

Where each rule comes from:

    R1   a durable intent precedes the provider outcome — an attempt begins
         with INTENT_RECORDED and with nothing else
    R37  the outcome facts exist only after the call returned
    R2   persistence happens after the returned outcome, never before it
    R3   one attempt per scheduled record, so every event of a record carries
         the same attempt id and no event kind occurs twice
    R7   an attempt that ended is never continued: no event may follow a
         terminal outcome (failed, rejected, persisted)
    R18  every attempt event belongs to the run it is written in (RUN_BOUND)
    R8   and to the session that was open when it happened (SESSION_BOUND):
         an attempt does not span sessions, because an interrupted attempt is
         abandoned rather than resumed
    R7   a terminated run (ABORTED) or a closed one (SEALED) accepts no
         further attempt events

The state machine, and nothing outside it:

    START ──INTENT_RECORDED──▶ INTENDED ──CALL_RETURNED──▶ RETURNED
                                  │                           │
                                  ├──CALL_FAILED──▶ FAILED     └─ARTIFACT_PERSISTED─▶ PERSISTED
                                  └──RESPONSE_REJECTED──▶ REJECTED

FAILED, REJECTED and PERSISTED are terminal. Custody acceptance is a separate
log and is not part of this grammar; what this grammar decides is whether the
history custody rests on could have happened at all.

Scope: one attempt's history inside one run. The frozen schedule's cross-record
order and the session lifecycle/seal are verified elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import session as lifecycle

START = "START"
INTENDED = "INTENDED"
RETURNED = "RETURNED"
PERSISTED = "PERSISTED"
FAILED = "FAILED"
REJECTED = "REJECTED"

#: (state, event) -> next state. Every other pair is impossible.
TRANSITIONS: dict[tuple[str, str], str] = {
    (START, ev.INTENT_RECORDED): INTENDED,
    (INTENDED, ev.CALL_FAILED): FAILED,
    (INTENDED, ev.RESPONSE_REJECTED): REJECTED,
    (INTENDED, ev.CALL_RETURNED): RETURNED,
    (RETURNED, ev.ARTIFACT_PERSISTED): PERSISTED,
}

#: an attempt in one of these states is over (R7: never continued).
TERMINAL = frozenset({FAILED, REJECTED, PERSISTED})

#: the attempt events, as opposed to run/session lifecycle events.
ATTEMPT_EVENTS = frozenset({ev.INTENT_RECORDED, ev.CALL_FAILED, ev.RESPONSE_REJECTED,
                            ev.CALL_RETURNED, ev.ARTIFACT_PERSISTED})

#: a run in one of these states accepts no further attempt event.
RUN_TERMINAL_EVENTS = (ev.RUN_ABORTED, ev.RUN_SEALED)


@dataclass(frozen=True)
class RunContext:
    """What one run's journal says about when attempts were allowed to happen.

    Built once from the whole journal so every record can be checked against
    the same picture: which run this is, when each session was open, and when
    the run stopped accepting attempt events.
    """

    run: str
    sessions: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    terminal_at: int | None = None
    positions: Mapping[int, int] = field(default_factory=dict)

    @classmethod
    def of(cls, journal: Sequence[Mapping], run: str) -> RunContext:
        # the session windows come from the lifecycle machine, so a duplicate
        # close cannot quietly extend the range an attempt may be written in.
        opened = lifecycle.windows(journal)
        terminal_at: int | None = None
        positions: dict[int, int] = {}
        for index, event in enumerate(journal):
            positions[id(event)] = index
            if event["event"] in RUN_TERMINAL_EVENTS and terminal_at is None:
                terminal_at = index
        return cls(run=run, sessions=opened, terminal_at=terminal_at, positions=positions)

    def index_of(self, event: Mapping) -> int | None:
        return self.positions.get(id(event))


def attempt_events(events: Sequence[Mapping]) -> list[Mapping]:
    return [event for event in events if event["event"] in ATTEMPT_EVENTS]


def walk(events: Sequence[Mapping]) -> tuple[str, str | None]:
    """Run the state machine. Returns the state reached and the first problem.

    The machine alone decides legal predecessor, legal successor, multiplicity
    (no state accepts a kind it has already consumed) and post-terminal
    silence. It knows nothing about this product's writer.
    """
    state = START
    for event in events:
        kind = event["event"]
        if state in TERMINAL:
            return state, (f"{kind} follows a {state.lower()} attempt; an attempt that "
                           "ended is never continued")
        nxt = TRANSITIONS.get((state, kind))
        if nxt is None:
            if state is START:
                return state, (f"the attempt begins with {kind}; a durable intent must come "
                               "first (R1)")
            return state, f"{kind} cannot follow {state.lower()} in any execution"
        state = nxt
    return state, None


def problems(record_key: str, events: Sequence[Mapping],
             context: RunContext | None = None) -> list[str]:
    """Everything illegal about one record's attempt history, in evidence order."""
    found: list[str] = []
    history = attempt_events(events)
    if not history:
        return found

    state, problem = walk(history)
    if problem is not None:
        found.append(f"{record_key}: {problem}")

    attempts = {event["attempt"] for event in history if "attempt" in event}
    if len(attempts) > 1:
        found.append(f"{record_key}: the journal names {len(attempts)} attempts for one "
                     "scheduled record (R3)")
    if context is None:
        return found

    foreign = {event.get("run") for event in history} - {context.run}
    if foreign:
        found.append(f"{record_key}: attempt events are attributed to another run "
                     f"{sorted(str(r) for r in foreign)} (R18)")

    sessions = {event.get("session") for event in history}
    if len(sessions) > 1:
        found.append(f"{record_key}: one attempt spans {len(sessions)} sessions; an "
                     "interrupted attempt is abandoned, never continued (R8)")
    for session in sessions:
        window = context.sessions.get(session)
        if window is None:
            found.append(f"{record_key}: attributed to session {session!r}, which this run "
                         "never opened (R15)")
            continue
        opened_at, closed_at = window
        for event in history:
            if event.get("session") != session:
                continue
            at = context.index_of(event)
            if at is None:
                continue
            if at < opened_at:
                found.append(f"{record_key}: {event['event']} is recorded before its session "
                             "was opened (R8)")
            elif at > closed_at:
                found.append(f"{record_key}: {event['event']} is recorded after its session "
                             "was closed (R8)")
    if context.terminal_at is not None:
        for event in history:
            at = context.index_of(event)
            if at is not None and at > context.terminal_at:
                found.append(f"{record_key}: {event['event']} is recorded after the run "
                             "reached a terminal state (R7)")
    return found


def state_of(events: Sequence[Mapping]) -> str | None:
    """The attempt state a legal history reached, or None if it is illegal."""
    state, problem = walk(attempt_events(events))
    return None if problem is not None else state
