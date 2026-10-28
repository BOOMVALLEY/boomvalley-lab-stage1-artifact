"""The actor call a tool answers (P17, T5-007).

A tool actor is called by the engine like every actor: one ``actor_call`` step,
one request-2 built by the P05 pipeline from what the actor may observe, one
call binding, one call in the K0 call chain, one custody entry.  What differs
is who answers inside the transport: not an adapter, but the actor's
contracted tool, through the journaled tool call (``kernel/tool_call.py``):

    request-2, call binding           as for every planned call
    arguments                         the contract's declared selection over
                                      the actor's observation
                                      (``tool.select_tool_arguments``)
    -> CALL_INTENT_RECORDED           names the tool call (``tool_call``: the
                                      tool intent and its contract)
    -> TRANSPORT_STARTED
    -> TOOL_INTENT_RECORDED -> TOOL_CALL_STARTED -> TOOL_RETURNED
                                      the journaled tool call, on the same step
    -> CALL_RETURNED                  the response is the canonical bytes of
                                      the typed result
                                      (``tool.tool_response_content``)
    -> CALL_PERSISTED -> CUSTODY_ACCEPTED

So custody, readiness, the proposal parser, the decision rule, resume and the
package read a tool actor's call as they read a model's, and the tool's result
enters the organization only as that call's response: its meaning for the
actor's proposal is the actor's parser contract (P06).

Every boundary is committed once.  A process that stops anywhere in the chain
is continued from what is durable (``kernel/tool_recovery.py``): the tool call
decides under the contract's declared side effect whether the tool is called
(not reached, a read, a reconciled NOT_APPLIED), asked by key (reconcile) or
left alone (its result is recorded); a response that was returned and not
accepted is derived from the recorded result again, byte-checked.  A restart
whose arguments re-derive to another tool intent than the journaled one is
refused (BVL-RES-001) before anything is called.

An outcome that is not proven is not an outcome of the episode.  An unknown
outcome that only an operator may decide (BVL-TOOL-010), tool evidence that
contradicts itself (BVL-TOOL-011) or a reconciliation that did not answer
(BVL-TOOL-012) is ``ToolCallRefusedError``: the engine journals no
EPISODE_FAILED for it and the run stays interrupted, with the tool call's
journal as it is.  What an operator's decision records is not in this build.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.kernel.actors import ActorBindingV1
from boomvalley_lab.kernel.adapter2 import ActorResponseV2
from boomvalley_lab.kernel.authorization import require_run_authorization_v2
from boomvalley_lab.kernel.call_executor import (
    CompletedCallV2,
    DurableCallExecutorV2,
    call_identity_v2,
)
from boomvalley_lab.kernel.custody2 import CustodyLedgerV2, accept_call_v2, call_artifact_name
from boomvalley_lab.kernel.document_store import EvidenceDocumentRefV2, EvidenceDocumentStoreV2
from boomvalley_lab.kernel.human_recovery import classify_actor_call
from boomvalley_lab.kernel.identity import EpisodeIdentity, StepIdentity
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_PERSISTED,
    CALL_RETURNED,
    TRANSPORT_STARTED,
)
from boomvalley_lab.kernel.recovery2 import CallStateV2
from boomvalley_lab.kernel.replay import (
    RESUME_EVIDENCE_MISMATCH,
    RESUME_OUTCOME_NOT_PROVEN,
    ResumeRefusedError,
)
from boomvalley_lab.kernel.request import RequestV2
from boomvalley_lab.kernel.tool import (
    TOOL_CALL_EVIDENCE_MISMATCH,
    TOOL_MODEL,
    TOOL_OUTCOME_UNKNOWN,
    TOOL_RECONCILIATION_FAILED,
    TOOL_UNSUPPORTED,
    ToolActorContractV1,
    ToolError,
    tool_intent,
    tool_response_content,
    tool_response_provenance,
)
from boomvalley_lab.kernel.tool_call import DurableToolCallExecutorV1
from boomvalley_lab.kernel.tool_recovery import ToolActorCallStateV1
from boomvalley_lab.store.artifacts import ArtifactRef, content_identity

#: tool refusals that are no outcome of the episode: the run stays interrupted
_NOT_AN_OUTCOME = frozenset(
    {TOOL_OUTCOME_UNKNOWN, TOOL_CALL_EVIDENCE_MISMATCH, TOOL_RECONCILIATION_FAILED}
)


class ToolCallRefusedError(ExecutionError):
    """The tool's outcome is not proven, or its evidence contradicts itself.

    An integrity or operator outcome, not a scientific one: the engine
    journals nothing for it and the run stays interrupted.
    """

    def __init__(self, error: ToolError) -> None:
        super().__init__(str(error), code=error.code)


@dataclass(frozen=True)
class ToolExchangeV1:
    """What one tool actor call is answered through: contract, binding, bound tool."""

    contract: ToolActorContractV1
    binding: ActorBindingV1
    tool: object


def execute_tool_actor_call(
    calls: DurableCallExecutorV2,
    tool_calls: DurableToolCallExecutorV1,
    *,
    episode: EpisodeIdentity,
    step: StepIdentity,
    round_index: int,
    request: RequestV2,
    exchange: ToolExchangeV1,
    arguments: Mapping[str, Any],
    binding: EvidenceDocumentRefV2 | None = None,
    resume: bool = False,
) -> CompletedCallV2:
    """One tool actor call through the durable call chain.

    Every boundary is committed once: whatever an earlier process of the run
    made durable is matched, not repeated.
    """

    contract, tool = exchange.contract, exchange.tool
    journal = calls.journal
    require_run_authorization_v2(calls.run_directory, run_id=calls.run_id, journal=journal)
    # the tool is the contracted one and can be called, before anything is written
    contract.require_binding(exchange.binding)
    contract.require_tool(tool)
    if not callable(getattr(tool, "call", None)):
        raise ToolError(TOOL_UNSUPPORTED, f"tool {contract.tool!r} cannot be called")
    intent = tool_intent(
        contract, exchange.binding, step=step, request=request, arguments=arguments
    )

    request_ref = calls.requests.put(request)
    call = call_identity_v2(
        episode=episode, step=step, round_index=round_index, request=request_ref,
        adapter_plugin_identity=contract.tool,
    )
    if binding is not None:
        bound = EvidenceDocumentStoreV2(calls.run_directory).read(binding)
        if binding.role != "call_binding" or bound.get("call") != call.document():
            raise ExecutionError(f"call binding {binding.path} is not call {call}'s")
    named: dict[str, Any] = {
        "tool_call": {
            "intent": intent.identity().document(),
            "contract": contract.identity().document(),
        }
    }
    if binding is not None:
        named["call_binding"] = binding.document()

    if journal.torn_tail():
        raise ExecutionError("journal-2 has a torn tail; refusing to append call evidence")
    if CustodyLedgerV2(calls.run_directory).torn_tail():
        raise ExecutionError("custody-v2 has a torn tail; refusing to append call evidence")
    calls.require_step_call(episode=episode, step=step, call=call)
    classified = classify_actor_call(
        run_directory=calls.run_directory, call=call, journal=journal,
        requests=calls.requests, artifacts=calls.artifacts,
    )
    scope = {"run": calls.run_id, "episode": str(episode), "step": str(step),
             "round": round_index}
    state = classified.state
    if state is CallStateV2.NOT_STARTED:
        journal.append_event(
            CALL_INTENT_RECORDED, **scope, call=str(call), request=request_ref.document(), **named
        )
    else:
        recorded = journal.of_call(str(call))[0]
        if recorded["run"] != calls.run_id or any(
            recorded.get(name) != named.get(name) for name in ("tool_call", "call_binding")
        ):
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"call {call} was intended for another tool intent than "
                f"{intent.identity()} re-derives: its tool is not called for it",
            )
        if resume and state is CallStateV2.CUSTODY_ACCEPTED:
            return calls._recorded(call, request_ref, named)
        if state not in (CallStateV2.INTENT_RECORDED, ToolActorCallStateV1.TOOL_PENDING,
                         ToolActorCallStateV1.TOOL_RETURNED):
            raise ResumeRefusedError(
                RESUME_OUTCOME_NOT_PROVEN,
                f"tool actor call {call} is {state.value}; resume decision "
                f"{classified.decision.value}"
                + (f" ({classified.reason})" if classified.reason else ""),
            )
    if state in (CallStateV2.NOT_STARTED, CallStateV2.INTENT_RECORDED):
        journal.append_event(TRANSPORT_STARTED, **scope, call=str(call))

    # the journaled tool call: called once, or continued from what it proves
    try:
        completed = tool_calls.execute(
            episode=episode, step=step, round_index=round_index, contract=contract,
            binding=exchange.binding, tool=tool, intent=intent,
        )
    except ToolError as error:
        if error.code in _NOT_AN_OUTCOME:
            raise ToolCallRefusedError(error) from None
        raise

    content = tool_response_content(completed.result)
    returned = ActorResponseV2(
        content=content, model_identity=TOOL_MODEL,
        adapter_provenance=tool_response_provenance(contract),
    )
    stated = {
        "content_digest": str(sha256_bytes(content)),
        "model_identity": returned.model_identity,
        "adapter_provenance": returned.adapter_provenance,
    }
    name = call_artifact_name(call)
    chain = {event["event"]: event for event in journal.of_call(str(call))}
    if CALL_RETURNED in chain:
        # the call returned in an earlier process: the recorded result is that one
        if chain[CALL_RETURNED]["response"] != stated:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"tool actor call {call} returned another response than its recorded tool "
                "result derives",
            )
    else:
        journal.append_event(CALL_RETURNED, **scope, call=str(call), response=stated)
    if calls.artifacts.exists(name):
        # persisted by the process that stopped: the member is the result's bytes
        artifact = ArtifactRef(name, content_identity(content))
        if calls.artifacts.path(name).read_bytes() != content:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"tool actor call {call} response member is not its recorded tool result",
            )
    else:
        artifact = calls.artifacts.put(name, content)
    if CALL_PERSISTED not in chain:
        journal.append_event(
            CALL_PERSISTED, **scope, call=str(call), artifact=artifact.document()
        )
    _, custody = accept_call_v2(
        run_directory=calls.run_directory, run_id=calls.run_id, call=call, journal=journal,
        requests=calls.requests, artifacts=calls.artifacts,
    )
    return CompletedCallV2(call, request_ref, returned, artifact, custody)
