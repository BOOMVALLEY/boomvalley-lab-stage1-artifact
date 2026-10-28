"""The session lifecycle — who was allowed to write, and how the next writer
was authorised.

A session is not a label on an event. It is the evidence that answers: which
writer held this run, when it stopped holding it, who released it if anyone
did, and on what authority the next writer opened. Verification that treats
sessions as a membership list accepts histories where two writers hold the run
at once, where a session is closed before it opened, where a duplicate close
silently extends a window, or where the transition that authorised the next
writer has simply been deleted after sealing.

Where each rule comes from:

    R8    one active session per run; sessions are sequential, never
          overlapping, and a session id is opened once
    R15   the session history is part of what the seal commits
    R16   a recovery session is a session like any other — its transition is
          recorded, so recovered custody stays distinguishable
    R18   a lifecycle event belongs to the run it is written in
    OD-02 for every PRIOR session the committed evidence must carry
          SESSION_OPENED, SESSION_CLOSED, `released_by`, `release_decision`
          and `next_session` where they apply, so a later verifier can
          reconstruct why the next writer was authorised. The FINAL sealing
          session may be open-only, because its close necessarily postdates
          the seal — and that exception is for the sealing session alone.

The machine, and nothing outside it:

    (no active) ──SESSION_OPENED s──▶ (s active) ──SESSION_CLOSED s──▶ (no active)

A run that has reached RUN_ABORTED or RUN_SEALED is terminal: no session may
open after it, and no attempt may be written after it. The sealing session's
own close is the one thing that legitimately follows RUN_SEALED.

Scope: the lifecycle of sessions within one run. What happens inside an
attempt is `journal.grammar` (per-attempt), and the order of records across
attempts is `journal.order` (frozen schedule). Three invariants, three
modules, deliberately not one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from boomvalley_lab.journal import events as ev

#: the events that move the lifecycle, as opposed to attempt events.
LIFECYCLE_EVENTS = frozenset({ev.SESSION_OPENED, ev.SESSION_CLOSED,
                              ev.RUN_ABORTED, ev.RUN_SEALED})

TERMINAL_EVENTS = (ev.RUN_ABORTED, ev.RUN_SEALED)


@dataclass(frozen=True)
class Transition:
    """One session's whole lifecycle, as the journal recorded it."""

    session: str
    opened: str
    opened_at: int
    closed: str | None = None
    closed_at: int | None = None
    released_by: str | None = None
    release_decision: str | None = None
    next_session: str | None = None

    @property
    def window(self) -> tuple[int, int]:
        """The positions between which this session could write."""
        return self.opened_at, (self.closed_at if self.closed_at is not None else -1)

    def document(self, *, committed_close: bool = True) -> dict:
        """What the seal commits for this session (OD-02).

        `committed_close=False` is the sealing session's exception: its close
        cannot exist yet when the seal is computed, so it is not committed.
        """
        found: dict = {"session": self.session, "opened": self.opened}
        if committed_close:
            found["closed"] = self.closed
            found["released_by"] = self.released_by
            found["release_decision"] = self.release_decision
            found["next_session"] = self.next_session
        return found


def transitions(journal: Sequence[Mapping]) -> list[Transition]:
    """Every session's lifecycle, in the order the sessions opened."""
    found: list[Transition] = []
    index_of: dict[str, int] = {}
    for position, event in enumerate(journal):
        kind = event["event"]
        session = event.get("session")
        if kind == ev.SESSION_OPENED and session is not None:
            if session in index_of:          # illegal; `problems` says so
                continue
            index_of[session] = len(found)
            found.append(Transition(session=session, opened=event.get("at", ""),
                                    opened_at=position))
        elif kind == ev.SESSION_CLOSED and session in index_of:
            at = index_of[session]
            if found[at].closed_at is not None:   # a duplicate close changes nothing
                continue
            found[at] = Transition(
                session=session, opened=found[at].opened, opened_at=found[at].opened_at,
                closed=event.get("at"), closed_at=position,
                released_by=event.get("released_by"),
                release_decision=event.get("release_decision"),
                next_session=event.get("next_session"),
            )
    return found


def windows(journal: Sequence[Mapping]) -> dict[str, tuple[int, int]]:
    """session -> the half-open position range in which it could write.

    A session that was never closed stays open to the end of the journal. A
    duplicate close does not extend anything: the first close is the close.
    """
    end = len(journal)
    return {t.session: (t.opened_at, end if t.closed_at is None else t.closed_at)
            for t in transitions(journal)}


def sealing_session(journal: Sequence[Mapping], *, holder: str | None = None) -> str | None:
    """The session that sealed the run, according to the evidence.

    The custody head, not the RUN_SEALED event, is the seal (CUSTODY §11).
    When RUN_SEALED was journaled it names the sealer. When the process died
    between writing the head and journaling RUN_SEALED, the sealer is the one
    session the journal leaves open - but only if the run lock still names it
    (`holder`, sessions/ACTIVE): a crashed process leaves the marker, and a
    release journals SESSION_CLOSED before removing it (RUNTIME §2, R8) - or
    the last session, closed by an operator's stale release (`released_by`),
    which is how a dead sealer's close is journaled (its close postdates the
    seal, CUSTODY §3). An open session with no marker, or an ordinary close
    with no RUN_SEALED, is terminal evidence removed after the fact (F-003
    "terminal-evidence removal"): no sealer.
    """
    for event in journal:
        if event["event"] == ev.RUN_SEALED:
            return event.get("session")
    found = transitions(journal)
    if not found:
        return None
    last = found[-1]
    still_open = [t.session for t in found if t.closed_at is None]
    if still_open == [last.session] and last.session == holder:
        return holder                  # died holding the run; the marker says so
    if last.closed_at is not None and last.released_by:
        return last.session            # died holding it; an operator released it
    return None


def committed(journal: Sequence[Mapping], *, sealed_by: str | None) -> list[dict]:
    """The session provenance a seal commits (R15, OD-02).

    Every prior session contributes its full transition — opened, closed, who
    released it, on what decision, and which session it authorised next.
    The sealing session contributes its opening only, because its close
    necessarily postdates the seal.
    """
    return [t.document(committed_close=t.session != sealed_by) for t in transitions(journal)]


def problems(journal: Sequence[Mapping], run: str) -> list[str]:
    """Everything illegal about this run's session lifecycle."""
    found: list[str] = []
    active: str | None = None
    opened_before: set[str] = set()
    terminal_at: int | None = None
    terminal_kind: str | None = None

    for position, event in enumerate(journal):
        kind = event["event"]
        if kind not in LIFECYCLE_EVENTS:
            continue
        if event.get("run") != run:
            found.append(f"{kind} at position {position} is attributed to run "
                         f"{event.get('run')!r}, not to this run (R18)")
            continue
        session = event.get("session")

        if kind == ev.SESSION_OPENED:
            if terminal_at is not None:
                found.append(f"session {session!r} opens after the run reached "
                             f"{terminal_kind} (R7/R8)")
            if active is not None:
                found.append(f"session {session!r} opens while {active!r} still holds the "
                             "run; a run has one active session (R8)")
            elif session in opened_before:
                found.append(f"session {session!r} is opened again; a session id is "
                             "opened once and never reopened (R8)")
            active = session
            opened_before.add(session)

        elif kind == ev.SESSION_CLOSED:
            if session not in opened_before:
                found.append(f"session {session!r} closes without ever opening (R8)")
            elif active != session:
                found.append(f"session {session!r} closes while it is not the active "
                             f"session ({active!r}); a close is not repeatable (R8)")
            else:
                active = None

        else:   # RUN_ABORTED / RUN_SEALED
            if terminal_at is not None:
                found.append(f"{kind} follows {terminal_kind}; a run reaches a terminal "
                             "state once (R7)")
            elif active is not None and session != active:
                found.append(f"{kind} is written by {session!r} while {active!r} holds the "
                             "run (R8)")
            if terminal_at is None:
                terminal_at, terminal_kind = position, kind

    # OD-02: a session that handed the run to a next writer must show how.
    # The last session is exempt: it may still be active, and if it sealed the
    # run its close necessarily postdates the seal.
    order = transitions(journal)
    for position, transition in enumerate(order):
        last = position == len(order) - 1
        if transition.closed is None and not last:
            found.append(f"session {transition.session!r} authorised a next writer without "
                         "ever closing (OD-02)")
            continue
        if transition.released_by is not None and not transition.next_session:
            found.append(f"session {transition.session!r} was released by an operator "
                         "without recording which session it authorised (OD-02)")
    return found
