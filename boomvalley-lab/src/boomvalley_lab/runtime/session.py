"""Sessions and the run lock — owner decision R8: ONE ACTIVE SESSION PER RUN.

    acquire(run)          exclusive-create `sessions/ACTIVE` (O_EXCL). If it
                          exists, another session holds the run: REFUSED.
                          Then SESSION_OPENED is journaled with the next ordinal.
    release(run, session) SESSION_CLOSED, then the marker is removed. A later
                          session is sequential and gets the next ordinal.
    release_stale(...)    after a crash the marker survives and every new
                          session is refused (fail closed) until an operator
                          releases it, naming the session it holds; the
                          release is journaled.

Local and single-machine; no distributed locking; concurrent writers are out
of MVP. An ABORTED or SEALED run cannot be acquired: both are terminal.
"""

from __future__ import annotations

import os
from pathlib import Path

from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.core.layout import ACTIVE_MARKER, SESSIONS_DIR
from boomvalley_lab.identity.kinds import SessionIdentity
from boomvalley_lab.journal import events as ev
from boomvalley_lab.runtime.run import Run, RunState


def _marker(run: Run) -> Path:
    return run.directory / SESSIONS_DIR / ACTIVE_MARKER


def active_session(run: Run) -> str | None:
    marker = _marker(run)
    return marker.read_text(encoding="utf-8") if marker.exists() else None


def acquire(run: Run, *, at: str) -> SessionIdentity:
    state = run.state()
    if state is RunState.ABORTED:
        raise ExecutionError(f"run {run.run_id} is ABORTED; it is never executed again")
    if state is RunState.SEALED:
        raise ExecutionError(f"run {run.run_id} is SEALED; its evidence is complete and closed")
    ordinal = 1 + sum(1 for e in run.events() if e["event"] == ev.SESSION_OPENED)
    session = SessionIdentity(run.run_id, ordinal)
    marker = _marker(run)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ExecutionError(
            f"run {run.run_id} already has an active session "
            f"({marker.read_text(encoding='utf-8')}); one active session per run"
        ) from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(session))
        handle.flush()
        os.fsync(handle.fileno())
    run.journal.append({"event": ev.SESSION_OPENED, "run": run.run_id,
                        "session": str(session), "at": at})
    return session


def release(run: Run, session: SessionIdentity, *, at: str) -> None:
    if active_session(run) != str(session):
        raise ExecutionError(f"{session} does not hold run {run.run_id}")
    run.journal.append({"event": ev.SESSION_CLOSED, "run": run.run_id,
                        "session": str(session), "at": at})
    _marker(run).unlink()


def release_stale(run: Run, session: str, *, operator: str, at: str,
                  decision: str | None = None) -> None:
    """An operator frees a run whose session died holding it.

    The release is evidence: who released which session, when, and the id the
    next session will take (deterministic — the ordinal never rewinds).
    """
    if active_session(run) != session:
        raise ExecutionError(f"{session} is not the session holding run {run.run_id}")
    opened = sum(1 for e in run.events() if e["event"] == ev.SESSION_OPENED)
    event = {"event": ev.SESSION_CLOSED, "run": run.run_id, "session": session,
             "at": at, "released_by": operator,
             "next_session": str(SessionIdentity(run.run_id, opened + 1))}
    if decision is not None:
        event["release_decision"] = decision
    run.journal.append(event)
    _marker(run).unlink()
