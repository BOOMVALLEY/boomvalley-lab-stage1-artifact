"""The one authoritative classifier of execution-record state.

Reads the journal, the artifact store and the custody ledger — never a
provider — and places every locked execution record in exactly one state:

    NOT_STARTED                  no intent: the provider was certainly not called
    CALL_OUTCOME_UNKNOWN         intent (and possibly CALL_FAILED), no return:
                                 whether the provider was called is unknowable
    CALL_RETURNED_NOT_PERSISTED  a realisation happened (returned, or returned
                                 malformed) and no valid artifact exists
    PERSISTED_UNRECORDED         the artifact is on disk and the run never
                                 accepted it as evidence: its persistence was
                                 not journaled, or it is not in custody
    PERSISTED                    persisted, journaled, read back, digest matches
                                 the returned response, AND accepted into
                                 custody (R2: complete is never "a file is
                                 there" — it is "this run accepted it")
    INCONSISTENT                 the evidence contradicts itself (duplicate
                                 intents, events out of order, artifact
                                 missing or changed, artifact without intent)

The frozen R7 decision per state (Phase 4 executes the policy; Phase 2 only
refuses to proceed past anything but EXECUTE / SKIP):

    NOT_STARTED -> EXECUTE · PERSISTED -> SKIP · CALL_OUTCOME_UNKNOWN -> ABORT
    CALL_RETURNED_NOT_PERSISTED -> ABORT · PERSISTED_UNRECORDED -> OPERATOR_DECISION
    INCONSISTENT -> ABORT
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.identity.kinds import ArtifactContentIdentity
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import grammar
from boomvalley_lab.store.artifacts import ArtifactRef, ArtifactStore, artifact_name


class State(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    CALL_OUTCOME_UNKNOWN = "CALL_OUTCOME_UNKNOWN"
    CALL_RETURNED_NOT_PERSISTED = "CALL_RETURNED_NOT_PERSISTED"
    PERSISTED_UNRECORDED = "PERSISTED_UNRECORDED"
    PERSISTED = "PERSISTED"
    INCONSISTENT = "INCONSISTENT"


class Decision(StrEnum):
    EXECUTE = "EXECUTE"
    SKIP = "SKIP"
    ABORT = "ABORT"
    OPERATOR_DECISION = "OPERATOR_DECISION"


POLICY: dict[State, Decision] = {
    State.NOT_STARTED: Decision.EXECUTE,
    State.PERSISTED: Decision.SKIP,
    State.CALL_OUTCOME_UNKNOWN: Decision.ABORT,
    State.CALL_RETURNED_NOT_PERSISTED: Decision.ABORT,
    State.PERSISTED_UNRECORDED: Decision.OPERATOR_DECISION,
    State.INCONSISTENT: Decision.ABORT,
}


@dataclass(frozen=True)
class Classified:
    record: str
    state: State
    reason: str = ""


def classify(records: Sequence[ExecutionRecord], journal: Sequence[dict],
             store: ArtifactStore,
             custody: Mapping[str, Sequence[Mapping]] | None = None
             ) -> dict[str, Classified]:
    known = {record.key for record in records}
    by_record: dict[str, list[dict]] = {}
    for event in journal:
        if "record" in event:
            if event["record"] not in known:
                raise EvidenceError(
                    f"the journal names an execution record the lock does not: {event['record']}"
                )
            by_record.setdefault(event["record"], []).append(event)
    context = (grammar.RunContext.of(journal, journal[0]["run"]) if journal else None)
    custody = dict(custody or {})
    for key in custody:
        if key not in known:
            raise EvidenceError(
                f"custody names an execution record the lock does not: {key}"
            )
    result = {}
    for position, record in enumerate(records):
        result[record.key] = _with_custody(
            _one(record.key, position, by_record.get(record.key, []), store, context),
            position, by_record.get(record.key, []), custody.get(record.key, ()),
        )
    return result


def _with_custody(base: Classified, position: int, events: Sequence[Mapping],
                  entries: Sequence[Mapping]) -> Classified:
    """Store-level state + what the run accepted = the frozen R7 state (R2)."""
    def state(value: State, reason: str = "") -> Classified:
        return Classified(base.record, value, reason)

    if len(entries) > 1:
        return state(State.INCONSISTENT, "custody holds this record more than once")
    if not entries:
        if base.state is State.PERSISTED:
            return state(State.PERSISTED_UNRECORDED,
                         "persisted, not accepted into custody evidence")
        return base
    entry = entries[0]
    if base.state not in (State.PERSISTED, State.PERSISTED_UNRECORDED):
        return state(State.INCONSISTENT,
                     f"custody accepted this record and its execution evidence is {base.state}")
    returned = [e for e in events if e["event"] == ev.CALL_RETURNED]
    response = returned[0]["response"] if len(returned) == 1 else None
    if response is None or {entry["response"], entry["artifact_content"]} != {response}:
        return state(State.INCONSISTENT, "custody does not hold the response the journal records")
    if entry["attempt"] != events[0]["attempt"] or entry["position"] != position:
        return state(State.INCONSISTENT, "custody names another attempt or schedule position")
    return state(State.PERSISTED, "" if entry["origin"] == "FRESH" else "recovered custody")


def _one(key: str, position: int, events: list[dict], store: ArtifactStore,
         context: grammar.RunContext | None = None) -> Classified:
    kinds = [e["event"] for e in events]
    on_disk = store.exists(artifact_name(position))

    def state(value: State, reason: str = "") -> Classified:
        return Classified(key, value, reason)

    if not events:
        if on_disk:
            return state(State.INCONSISTENT, "an artifact exists with no intent")
        return state(State.NOT_STARTED)
    # One grammar, shared with custody and the gate: a history that could not
    # have happened is INCONSISTENT here for the same reason it is refused
    # there (R1, R3, R7, R37, R2).
    illegal = grammar.problems(key, events, context)
    if illegal:
        return state(State.INCONSISTENT, illegal[0])
    if events[0]["position"] != position:
        return state(State.INCONSISTENT, "the intent names another schedule position")
    if kinds[-1] in (ev.INTENT_RECORDED, ev.CALL_FAILED):
        if on_disk:
            return state(State.INCONSISTENT, "an artifact exists for a call with no return")
        return state(State.CALL_OUTCOME_UNKNOWN, "intent recorded, no return")
    if kinds[-1] == ev.RESPONSE_REJECTED:
        return state(State.CALL_RETURNED_NOT_PERSISTED, "the response was malformed")
    if kinds[-1] == ev.CALL_RETURNED:
        if on_disk:
            return state(State.PERSISTED_UNRECORDED, "artifact on disk, persistence not journaled")
        return state(State.CALL_RETURNED_NOT_PERSISTED)
    persisted = events[-1]
    returned = events[1]
    if persisted["artifact_content"] != returned["response"]:
        return state(State.INCONSISTENT, "the persisted content is not the returned response")
    ref = ArtifactRef(persisted["artifact"],
                      ArtifactContentIdentity(Digest.parse(persisted["artifact_content"])))
    if persisted["artifact"] != artifact_name(position):
        return state(State.INCONSISTENT, "the persisted artifact is not this record's")
    try:
        store.read(ref)
    except (OSError, EvidenceError) as error:
        return state(State.INCONSISTENT, f"the persisted artifact does not read back: {error}")
    return state(State.PERSISTED)
