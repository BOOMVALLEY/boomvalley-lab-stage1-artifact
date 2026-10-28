"""One attempt at a time — the cross-record serialization of execution.

Two records can each have a perfectly legal attempt history, and the run can
have begun them in exactly the registered order, and the history can still be
one no sequential runtime could ever have written:

    Frozen schedule: A -> B

    A.INTENT_RECORDED          A's attempt starts
    B.INTENT_RECORDED          ... and B's starts before A ended
    B.CALL_RETURNED
    B.ARTIFACT_PERSISTED
    A.CALL_RETURNED            A resumes, after B finished
    A.ARTIFACT_PERSISTED

Read per record, both attempts are `[INTENT, RETURNED, PERSISTED]` — the
per-attempt grammar is satisfied. Read across records, the intents are A then
B — the frozen schedule order is satisfied. What neither of them asks is
whether the two attempts were ever in flight at the same time:

    legal per-attempt grammar
    + legal durable-intent order
    != legal sequential execution history

The executor realises one record at a time: it builds a request, records the
intent, calls, persists and accepts custody before it looks at the next
record. Nothing is reordered, batched or parallelised, and BOOMVALLEY Lab V1
supports no concurrent, parallel or batched execution at all. So an overlap
is not a run that went unusually — it is a history that did not happen.

The invariant, read off those sequential semantics:

    from the moment a record's INTENT_RECORDED is written until that attempt
    reaches a terminal outcome, no other record's attempt event may appear.

Two things this deliberately does NOT do:

    it does not re-decide what a legal attempt looks like. Which events may
    follow which, and where an attempt ends, is `journal.grammar` (#6) — the
    terminal events here are derived from that machine rather than restated,
    so the two cannot drift apart;

    it does not re-decide which records ran, or in what order they began.
    That is `journal.order` (#7). A history can satisfy either of those and
    violate this one, which is why this is a third invariant in a third
    module rather than a clause bolted onto one of them.

Sessions bound it. An attempt does not span sessions (R8: an interrupted
attempt is abandoned, never resumed), so every session begins with nothing in
flight, and an attempt left open when its session ended is the R7 policy's
business, not an overlap. That is what makes the legitimate crash paths —
crash, operator release, recovery, continuation in a new session — pass here
untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import grammar

#: the events that end an attempt, read off the per-attempt machine itself:
#: every transition whose target state is terminal (#6 owns that definition).
CLOSING = frozenset(kind for (_, kind), state in grammar.TRANSITIONS.items()
                    if state in grammar.TERMINAL)


def problems(journal: Sequence[Mapping]) -> list[str]:
    """Where two records' attempts were in flight at the same time."""
    found: list[str] = []
    holder: str | None = None          # the record whose attempt is in flight

    for position, event in enumerate(journal):
        kind = event["event"]
        if kind == ev.SESSION_OPENED:
            holder = None              # a session begins with nothing in flight
            continue
        if kind not in grammar.ATTEMPT_EVENTS or "record" not in event:
            continue
        record = event["record"]

        if holder is not None and holder != record:
            if kind == ev.INTENT_RECORDED:
                found.append(
                    f"{record} begins an attempt at position {position} while {holder}'s "
                    "attempt has not ended; the runtime realises one record at a time"
                )
            else:
                found.append(
                    f"{kind} for {record} at position {position} arrives while {holder}'s "
                    "attempt has not ended; two attempts are never in flight at once"
                )
            holder = None              # reported once; resynchronise from here

        if kind == ev.INTENT_RECORDED:
            holder = record
        elif kind in CLOSING and holder == record:
            holder = None
    return found


def in_flight(journal: Sequence[Mapping]) -> str | None:
    """The record whose attempt the journal leaves unfinished, if any.

    Only meaningful when `problems` is empty; a history that already overlapped
    has no single attempt in flight.
    """
    holder: str | None = None
    for event in journal:
        kind = event["event"]
        if kind == ev.SESSION_OPENED:
            holder = None
        elif kind == ev.INTENT_RECORDED and "record" in event:
            holder = event["record"]
        elif kind in CLOSING and holder == event.get("record"):
            holder = None
    return holder
