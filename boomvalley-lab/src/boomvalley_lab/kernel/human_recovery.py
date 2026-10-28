"""Evidence-driven resume classification of a human actor call (P17, T5-002).

``recovery2`` classifies an actor call for a provider that answers inside one
transport: once transport started, whether the provider did anything is not
proven, and a returned response that was not persisted is gone.  Neither holds
for a call whose intent names a human request intent (``human_intent``): the
request and its answer exist once per intent on the call's channel, durable
and outside the process, so what was interrupted can be finished from there.

This module leaves ``recovery2`` - its states and its policy - as they are for
every call, and reads three of its verdicts again for a human call:

    intent, transport             CALL_OUTCOME_UNKNOWN   -> AWAITING_HUMAN
                                  (the request is with the channel: delivered
                                  once, its answer collected once)
    ... returned                  RETURNED_NOT_PERSISTED -> HUMAN_RETURNED
    ... returned + member, or     PERSISTED_UNRECORDED   -> HUMAN_RETURNED
    ... persisted, no custody     (the answer is journaled by digest and is
        entry                     still on its channel: persistence and custody
                                  are finished from there, byte-checked)

Both continue (EXECUTE): nobody is asked again and nothing is asked of a
provider.  Every other verdict is ``recovery2``'s, unchanged - a human call
whose transport raised, whose custody entry exists without its
CUSTODY_ACCEPTED, or whose evidence contradicts itself is what it is for any
call.  Classification is read-only.

A call whose intent names a tool call (``tool_call``, T5-007) is read again by
``kernel/tool_recovery.py`` in the same way: its tool's journaled call decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.kernel.custody2 import CustodyLedgerV2
from boomvalley_lab.kernel.identity import CallIdentity
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.recovery2 import (
    CallStateV2,
    ClassifiedCallV2,
    ResumeDecisionV2,
    classify_call_v2,
)
from boomvalley_lab.kernel.request_store import RequestStoreV2
from boomvalley_lab.kernel.tool_recovery import (
    ClassifiedToolActorCallV1,
    classify_tool_actor_call,
)
from boomvalley_lab.store.artifacts import ArtifactStore


class HumanCallStateV1(StrEnum):
    AWAITING_HUMAN = "AWAITING_HUMAN"
    HUMAN_RETURNED = "HUMAN_RETURNED"


@dataclass(frozen=True)
class ClassifiedHumanCallV1:
    call: str
    state: HumanCallStateV1
    decision: ResumeDecisionV2
    reason: str


def classify_actor_call(
    *,
    run_directory: Path,
    call: CallIdentity,
    journal: Journal2,
    requests: RequestStoreV2,
    artifacts: ArtifactStore,
) -> ClassifiedCallV2 | ClassifiedHumanCallV1 | ClassifiedToolActorCallV1:
    """``classify_call_v2``, read again for a call a person or a tool answers."""

    base = classify_call_v2(
        run_directory=run_directory, call=call, journal=journal, requests=requests,
        artifacts=artifacts,
    )
    call_key = str(call)
    try:
        events = journal.of_call(call_key)
        custody = CustodyLedgerV2(run_directory).of_call(call_key)
    except EvidenceError:
        return base
    if events and "tool_call" in events[0]:
        return classify_tool_actor_call(
            base, run_directory=run_directory, journal=journal, events=events,
            custody=custody,
        )
    if not events or "human_intent" not in events[0]:
        return base

    def human(state: HumanCallStateV1, reason: str) -> ClassifiedHumanCallV1:
        return ClassifiedHumanCallV1(call_key, state, ResumeDecisionV2.EXECUTE, reason)

    kinds = [event["event"] for event in events]
    if base.state is CallStateV2.CALL_OUTCOME_UNKNOWN and kinds == [
        CALL_INTENT_RECORDED, TRANSPORT_STARTED
    ]:
        return human(
            HumanCallStateV1.AWAITING_HUMAN,
            "the request is with a human channel; the answer is collected once",
        )
    if base.state is CallStateV2.RETURNED_NOT_PERSISTED or (
        base.state is CallStateV2.PERSISTED_UNRECORDED and not custody
    ):
        return human(
            HumanCallStateV1.HUMAN_RETURNED,
            "the human answer is journaled by digest and not custody-accepted; its channel "
            "still holds it",
        )
    return base
