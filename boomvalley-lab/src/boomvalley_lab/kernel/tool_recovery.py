"""Evidence-driven resume classification of a tool actor call (P17, T5-007).

``recovery2`` classifies an actor call for a provider that answers inside one
transport: once transport started, whether the provider did anything is not
proven, and a returned response that was not persisted is gone.  A call whose
intent names a tool call (``tool_call``) is answered by a tool whose own call
is journaled on the same step (``kernel/tool_call.py``), so what the transport
did is evidence, and what may follow is the tool call's decision under the
contract's declared side effect - never a guess about a provider.

This module leaves ``recovery2`` as it is for every call and reads three of
its verdicts again for a tool actor call:

    intent, transport             CALL_OUTCOME_UNKNOWN   -> TOOL_PENDING
                                  the journaled tool call decides:
          not reached, read again,       EXECUTE
          reconcile by key, or result
          recorded
          unknown IRREVERSIBLE outcome   OPERATOR_DECISION
          contradictory tool evidence    ABORT
    ... returned                  RETURNED_NOT_PERSISTED -> TOOL_RETURNED
    ... returned + member, or     PERSISTED_UNRECORDED   -> TOOL_RETURNED
    ... persisted, no custody     (the typed result is ``tool_result``
        entry                     evidence: the response bytes are derived
                                  from it again, byte-checked, and the tool is
                                  not called)

Every other verdict is ``recovery2``'s, unchanged.  Classification is
read-only: it never calls a tool and never asks one to reconcile.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.identity import StepIdentity
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    RUN_OPENED,
    TOOL_CALL_STARTED,
    TOOL_INTENT_RECORDED,
    TOOL_OUTCOME_UNKNOWN,
    TOOL_RECONCILED,
    TOOL_RETURNED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.recovery2 import CallStateV2, ClassifiedCallV2, ResumeDecisionV2
from boomvalley_lab.kernel.tool import INTENT_TYPES, ToolActorContractSetV1, ToolActorContractV1
from boomvalley_lab.kernel.tool_call import (
    INTENT_ROLE,
    ToolResumeDecisionV1,
    classify_tool_call,
)

TOOL_EVENTS = frozenset(
    {TOOL_INTENT_RECORDED, TOOL_CALL_STARTED, TOOL_OUTCOME_UNKNOWN, TOOL_RETURNED,
     TOOL_RECONCILED}
)

_DECISIONS = {
    ToolResumeDecisionV1.EXECUTE: ResumeDecisionV2.EXECUTE,
    ToolResumeDecisionV1.RECONCILE: ResumeDecisionV2.EXECUTE,
    ToolResumeDecisionV1.SKIP: ResumeDecisionV2.EXECUTE,
    ToolResumeDecisionV1.OPERATOR_DECISION: ResumeDecisionV2.OPERATOR_DECISION,
    ToolResumeDecisionV1.ABORT: ResumeDecisionV2.ABORT,
}


class ToolActorCallStateV1(StrEnum):
    TOOL_PENDING = "TOOL_PENDING"
    TOOL_RETURNED = "TOOL_RETURNED"


@dataclass(frozen=True)
class ClassifiedToolActorCallV1:
    call: str
    state: ToolActorCallStateV1
    decision: ResumeDecisionV2
    reason: str


def run_tool_contracts(run_directory: Path, journal: Journal2) -> ToolActorContractSetV1 | None:
    """The tool actor contracts of the plan the run was opened on, from its evidence."""

    opened = journal.of_event(RUN_OPENED)
    if len(opened) != 1:
        raise ValueError(f"the journal opens {len(opened)} runs")
    held = [document for document in EvidenceDocumentStoreV2(run_directory).members("plan")
            if document.get("identity") == opened[0]["plan"]]
    if len(held) != 1:
        raise ValueError("the run holds no plan evidence for the plan it was opened on")
    tools = held[0]["plan"].get("tools")
    return None if tools is None else ToolActorContractSetV1.from_document(tools)


def _pending(
    run_directory: Path, journal: Journal2, intent_record: dict[str, Any]
) -> tuple[ResumeDecisionV2, str]:
    """What the step's journaled tool call allows next."""

    step_key = intent_record["step"]
    records = [r for r in journal.of_step(step_key) if r["event"] in TOOL_EVENTS]
    if not records:
        return ResumeDecisionV2.EXECUTE, "transport started and the tool was not reached"
    if records[0]["event"] != TOOL_INTENT_RECORDED:
        return ResumeDecisionV2.ABORT, "the step's tool records do not open with an intent"
    try:
        contracts = run_tool_contracts(run_directory, journal)
        named = intent_record["tool_call"]["contract"]
        contract: ToolActorContractV1 = next(
            item for item in (contracts.contracts.values() if contracts is not None else ())
            if item.identity().document() == named
        )
        intent = INTENT_TYPES[contract.effect].from_document(
            EvidenceDocumentStoreV2(run_directory).read(
                evidence_ref_from_document(records[0]["evidence"], INTENT_ROLE)
            )
        )
        if intent.identity().document() != intent_record["tool_call"]["intent"]:
            return ResumeDecisionV2.ABORT, "the step journals another tool intent than its call's"
        kind, _, digest = step_key.partition(":")
        if dict(intent.step) != {"kind": kind, "digest": digest}:
            return ResumeDecisionV2.ABORT, "the tool intent is another step's"
        step = StepIdentity(Digest.parse(digest))
    except StopIteration:
        return ResumeDecisionV2.ABORT, "the call's tool contract is not one of the run's plan"
    except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
        return ResumeDecisionV2.ABORT, f"the tool call evidence does not read: {error}"
    classified = classify_tool_call(
        run_directory=run_directory, journal=journal, contract=contract, step=step,
        intent=intent,
    )
    reason = f"the tool call is {classified.state.value}: {classified.decision.value}" + (
        f" ({classified.reason})" if classified.reason else ""
    )
    return _DECISIONS[classified.decision], reason


def classify_tool_actor_call(
    base: ClassifiedCallV2,
    *,
    run_directory: Path,
    journal: Journal2,
    events: list[dict[str, Any]],
    custody: list[Any],
) -> ClassifiedCallV2 | ClassifiedToolActorCallV1:
    """``recovery2``'s verdict *base*, read again for a call a tool answers."""

    call_key = base.call
    kinds = [event["event"] for event in events]
    if base.state is CallStateV2.CALL_OUTCOME_UNKNOWN and kinds == [
        CALL_INTENT_RECORDED, TRANSPORT_STARTED
    ]:
        decision, reason = _pending(run_directory, journal, events[0])
        return ClassifiedToolActorCallV1(
            call_key, ToolActorCallStateV1.TOOL_PENDING, decision, reason
        )
    if base.state is CallStateV2.RETURNED_NOT_PERSISTED or (
        base.state is CallStateV2.PERSISTED_UNRECORDED and not custody
    ):
        return ClassifiedToolActorCallV1(
            call_key, ToolActorCallStateV1.TOOL_RETURNED, ResumeDecisionV2.EXECUTE,
            "the tool's typed result is journaled evidence and not custody-accepted; the "
            "response is derived from it again",
        )
    return base
