"""The journal event model — the minimum that keeps the verified distinctions.

    RUN_OPENED            the run exists, bound to one verified lock
    INPUT_LOCK_BOUND      journal[1] of an INPUT_LOCKED run only: the anchor of
                          the run's Input Lock (run id, EII, input.json digest).
                          Its closed record and its position are checked by
                          `journal.anchor`, which classifies the run
    SESSION_OPENED        a session acquired the run (R8)
    INTENT_RECORDED       durable pre-call intent for one attempt (R1): record,
                          attempt, schedule position, request identity, the
                          intended execution identity
    CALL_FAILED           the adapter raised: the call outcome is UNKNOWN
    CALL_RETURNED         the adapter returned: actual execution identity read
                          off the response (R37), the response digest (R4) and,
                          when the realisation was a derivation, the derivation
                          record read off what performed it (R41)
    RESPONSE_REJECTED     the adapter returned something malformed: a
                          realisation happened, no valid artifact exists
    ARTIFACT_PERSISTED    the returned content is persisted and read back (R2)
    SESSION_CLOSED        the session released the run
    RUN_SEALED            every scheduled record is in sealed custody; the run
                          is terminal and its custody head is immutable
    RUN_ABORTED           terminal; the run is never executed again

Every attempt event binds run, session, execution record and attempt. There is
no retry event: MVP has one attempt per record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.errors import EvidenceError

JOURNAL_SCHEMA = "boomvalley-lab-journal-1"

RUN_OPENED = "RUN_OPENED"
INPUT_LOCK_BOUND = "INPUT_LOCK_BOUND"
SESSION_OPENED = "SESSION_OPENED"
INTENT_RECORDED = "INTENT_RECORDED"
CALL_FAILED = "CALL_FAILED"
CALL_RETURNED = "CALL_RETURNED"
RESPONSE_REJECTED = "RESPONSE_REJECTED"
ARTIFACT_PERSISTED = "ARTIFACT_PERSISTED"
SESSION_CLOSED = "SESSION_CLOSED"
RUN_SEALED = "RUN_SEALED"
RUN_ABORTED = "RUN_ABORTED"

ATTEMPT_KEYS = ("run", "session", "record", "attempt")

#: event -> keys it must carry (besides "event" and "at").
REQUIRED: dict[str, tuple[str, ...]] = {
    RUN_OPENED: ("run", "lock_contract", "lock_design", "lock_schedule"),
    INPUT_LOCK_BOUND: ("run", "input_digest", "input_identity"),
    SESSION_OPENED: ("run", "session"),
    INTENT_RECORDED: (*ATTEMPT_KEYS, "position", "request", "intended"),
    CALL_FAILED: (*ATTEMPT_KEYS, "error"),
    CALL_RETURNED: (*ATTEMPT_KEYS, "actual_execution", "response"),
    RESPONSE_REJECTED: (*ATTEMPT_KEYS, "reason"),
    ARTIFACT_PERSISTED: (*ATTEMPT_KEYS, "artifact", "artifact_content"),
    SESSION_CLOSED: ("run", "session"),
    RUN_SEALED: ("run", "session", "custody", "seal", "entries"),
    RUN_ABORTED: ("run", "session", "reason"),
}

#: event -> keys it MAY carry beyond the required ones. A journal event is a
#: closed record, not a bag: a lifecycle event is not record-scoped, and
#: nothing downstream may conclude otherwise from a key that only appears
#: because someone wrote it there.
OPTIONAL: dict[str, tuple[str, ...]] = {
    SESSION_CLOSED: ("released_by", "release_decision", "next_session"),
    CALL_RETURNED: ("derivation",),
}

EXECUTION_KEYS = ("adapter_provenance", "model_identity")


def execution_document(value: Any, where: str) -> dict[str, str]:
    """The canonical actual/intended execution identity facts."""
    if not isinstance(value, Mapping) or tuple(sorted(value)) != EXECUTION_KEYS:
        raise EvidenceError(f"{where}: execution identity is exactly {list(EXECUTION_KEYS)}")
    for key in EXECUTION_KEYS:
        if not isinstance(value[key], str) or not value[key].strip():
            raise EvidenceError(f"{where}: {key} must be a non-empty string")
    return {key: value[key] for key in EXECUTION_KEYS}


def permitted(kind: str) -> tuple[str, ...]:
    """Every key this kind of event may carry."""
    return ("event", "at", *REQUIRED[kind], *OPTIONAL.get(kind, ()))


def check_event(event: Any, where: str) -> dict:
    """One event, against the grammar — what it must carry AND what it may not.

    Checking only for missing keys leaves the other half of the grammar
    unstated, and downstream readers then decide what an event IS from the
    keys it happens to have. A SESSION_CLOSED carrying a `record` was grouped
    with that record's attempt events and read as one of them, which ended in
    a raw KeyError for a key lifecycle events do not have — while other
    readers of the same journal carried on. Malformed persisted state must
    fail as persisted state, once, for every reader.
    """
    if not isinstance(event, Mapping) or event.get("event") not in REQUIRED:
        raise EvidenceError(f"{where}: not a journal event: {event!r}")
    kind = event["event"]
    if kind == INPUT_LOCK_BOUND:
        # A malformed anchor is not a malformed journal: it is an INVALID
        # anchor, which `journal.anchor` classifies and every reader refuses
        # with its own code (Input Contract §10.4). It is never repaired.
        return dict(event)
    missing = [key for key in (*REQUIRED[kind], "at") if key not in event]
    if missing:
        raise EvidenceError(f"{where}: {kind} lacks {missing}")
    forbidden = sorted(set(event) - set(permitted(kind)))
    if forbidden:
        raise EvidenceError(
            f"{where}: {kind} carries {forbidden}, which this event does not have"
        )
    for key in ("intended", "actual_execution"):
        if key in event:
            execution_document(event[key], where)
    return dict(event)
