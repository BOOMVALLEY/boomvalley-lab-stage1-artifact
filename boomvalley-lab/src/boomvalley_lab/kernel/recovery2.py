"""Evidence-driven resume classification for K0 actor calls (T0-009).

Resume is never a retry policy.  This module only decides what the durable
evidence proves may happen next.  Classification is read-only and
deterministic: it reads journal-2, request-2, the response member and
custody-v2, never calls a provider and never writes evidence.

The durable call chain is

    CALL_INTENT_RECORDED -> TRANSPORT_STARTED -> CALL_RETURNED
        -> CALL_PERSISTED -> CUSTODY_ACCEPTED

and every prefix maps to exactly one state:

    (nothing)                     NOT_STARTED             -> EXECUTE
    intent                        INTENT_RECORDED         -> EXECUTE (continue
                                  the recorded intent; no provider was reached)
    intent, transport[, unknown]  CALL_OUTCOME_UNKNOWN    -> OPERATOR_DECISION
    ... returned                  RETURNED_NOT_PERSISTED  -> ABORT
    ... returned + member, or
    ... persisted                 PERSISTED_UNRECORDED    -> OPERATOR_DECISION
    ... custody accepted and the
        whole chain re-verifies   CUSTODY_ACCEPTED        -> SKIP
    anything else / tamper        INCONSISTENT            -> ABORT

There is deliberately no RETRY decision: once transport started, only an
operator may decide whether a provider side effect happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.kernel.custody2 import (
    CustodyLedgerV2,
    call_artifact_name,
    read_intent_request_v2,
    recompute_recorded_call_v2,
    verify_call_v2,
)
from boomvalley_lab.kernel.identity import CallIdentity
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_OUTCOME_UNKNOWN,
    CALL_PERSISTED,
    CALL_RETURNED,
    CUSTODY_ACCEPTED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.request_store import RequestStoreV2
from boomvalley_lab.store.artifacts import ArtifactStore


class CallStateV2(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    INTENT_RECORDED = "INTENT_RECORDED"
    CALL_OUTCOME_UNKNOWN = "CALL_OUTCOME_UNKNOWN"
    RETURNED_NOT_PERSISTED = "RETURNED_NOT_PERSISTED"
    PERSISTED_UNRECORDED = "PERSISTED_UNRECORDED"
    CUSTODY_ACCEPTED = "CUSTODY_ACCEPTED"
    INCONSISTENT = "INCONSISTENT"


class ResumeDecisionV2(StrEnum):
    EXECUTE = "EXECUTE"
    SKIP = "SKIP"
    ABORT = "ABORT"
    OPERATOR_DECISION = "OPERATOR_DECISION"


POLICY_V2: dict[CallStateV2, ResumeDecisionV2] = {
    CallStateV2.NOT_STARTED: ResumeDecisionV2.EXECUTE,
    CallStateV2.INTENT_RECORDED: ResumeDecisionV2.EXECUTE,
    CallStateV2.CALL_OUTCOME_UNKNOWN: ResumeDecisionV2.OPERATOR_DECISION,
    CallStateV2.RETURNED_NOT_PERSISTED: ResumeDecisionV2.ABORT,
    CallStateV2.PERSISTED_UNRECORDED: ResumeDecisionV2.OPERATOR_DECISION,
    CallStateV2.CUSTODY_ACCEPTED: ResumeDecisionV2.SKIP,
    CallStateV2.INCONSISTENT: ResumeDecisionV2.ABORT,
}

_CALL_SCOPE = ("run", "episode", "step", "round", "call")
_INTENT = [CALL_INTENT_RECORDED]
_TRANSPORT = [*_INTENT, TRANSPORT_STARTED]
_UNKNOWN = [*_TRANSPORT, CALL_OUTCOME_UNKNOWN]
_RETURNED = [*_TRANSPORT, CALL_RETURNED]
_PERSISTED = [*_RETURNED, CALL_PERSISTED]
_ACCEPTED = [*_PERSISTED, CUSTODY_ACCEPTED]


@dataclass(frozen=True)
class ClassifiedCallV2:
    call: str
    state: CallStateV2
    decision: ResumeDecisionV2
    reason: str = ""


def classify_call_v2(
    *,
    run_directory: Path,
    call: CallIdentity,
    journal: Journal2,
    requests: RequestStoreV2,
    artifacts: ArtifactStore,
) -> ClassifiedCallV2:
    call_key = str(call)

    def result(state: CallStateV2, reason: str = "") -> ClassifiedCallV2:
        return ClassifiedCallV2(call_key, state, POLICY_V2[state], reason)

    def inconsistent(reason: str) -> ClassifiedCallV2:
        return result(CallStateV2.INCONSISTENT, reason)

    try:
        events = journal.of_call(call_key)
        custody = CustodyLedgerV2(run_directory).of_call(call_key)
    except EvidenceError as error:
        return inconsistent(str(error))
    kinds = [event["event"] for event in events]
    member = call_artifact_name(call)
    artifact_exists = artifacts.exists(member)

    if not events:
        if custody or artifact_exists:
            return inconsistent("artifact/custody exists without a durable call intent")
        return result(CallStateV2.NOT_STARTED)

    intent = events[0]
    if intent["event"] != CALL_INTENT_RECORDED:
        return inconsistent(f"call history does not open with {CALL_INTENT_RECORDED}: {kinds}")
    for event in events[1:]:
        for field in _CALL_SCOPE:
            if event[field] != intent[field]:
                return inconsistent(
                    f"{event['event']} at sequence {event['sequence']} {field} "
                    "contradicts the call intent"
                )
    try:
        read_intent_request_v2(intent, requests)
    except (EvidenceError, OSError, ValueError) as error:
        return inconsistent(f"call intent request does not re-verify: {error}")

    if kinds == _INTENT:
        if artifact_exists or custody:
            return inconsistent("response evidence exists although transport never started")
        return result(
            CallStateV2.INTENT_RECORDED,
            "intent is durable but transport never started; no provider side effect",
        )

    if kinds in (_TRANSPORT, _UNKNOWN):
        if artifact_exists or custody:
            return inconsistent("call outcome is unknown but response evidence exists")
        return result(
            CallStateV2.CALL_OUTCOME_UNKNOWN,
            "transport started but provider outcome is not proven",
        )

    if kinds == _RETURNED:
        if custody:
            return inconsistent("custody exists before response persistence")
        if artifact_exists:
            try:
                content = artifacts.path(member).read_bytes()
            except OSError as error:
                return inconsistent(f"response member is unreadable: {error}")
            if events[-1]["response"].get("content_digest") != str(sha256_bytes(content)):
                return inconsistent("response member bytes are not the returned response")
            return result(
                CallStateV2.PERSISTED_UNRECORDED,
                "response member exists but CALL_PERSISTED is not journaled",
            )
        return result(
            CallStateV2.RETURNED_NOT_PERSISTED,
            "provider returned but the response was never durably persisted",
        )

    if kinds == _PERSISTED:
        if len(custody) > 1:
            return inconsistent("duplicate custody entries")
        try:
            expected = recompute_recorded_call_v2(
                call=call, events=events, requests=requests, artifacts=artifacts
            )
        except (EvidenceError, OSError, ValueError) as error:
            return inconsistent(str(error))
        if custody:
            if custody[0] != expected:
                return inconsistent("custody entry does not recompute from the call chain")
            return result(
                CallStateV2.PERSISTED_UNRECORDED,
                "custody ledger entry exists but CUSTODY_ACCEPTED is not journaled",
            )
        return result(
            CallStateV2.PERSISTED_UNRECORDED,
            "response is persisted but not accepted into custody",
        )

    if kinds == _ACCEPTED:
        try:
            verify_call_v2(
                run_directory=run_directory,
                call=call,
                journal=journal,
                requests=requests,
                artifacts=artifacts,
            )
        except (EvidenceError, OSError, ValueError) as error:
            return inconsistent(str(error))
        return result(CallStateV2.CUSTODY_ACCEPTED)

    return inconsistent(f"unsupported or contradictory call event history: {kinds}")
