"""Durable K0 actor-call boundary.

Ordering is structural:

    require the run's gate-2 authorization (T0-012; nothing is written or
    invoked under a refused, missing or unverifiable gate)
    -> prepare request-2
    -> persist request-2
    -> journal CALL_INTENT_RECORDED (naming the call's L1 call-binding
       evidence when the handler bound one, T1-008)
    -> journal TRANSPORT_STARTED
    -> adapter.invoke exactly once
    -> journal CALL_RETURNED
    -> persist response
    -> journal CALL_PERSISTED
    -> recompute/accept custody-entry-2
    -> journal CUSTODY_ACCEPTED

The executor does not parse proposals or choose authority.  Before any write
it classifies the call from durable evidence (recovery2): only a call that
never reached transport may proceed.  An intent recorded by an interrupted
earlier attempt is continued, not duplicated; every other state refuses, so a
provider is never invoked twice for one call.

A step makes one call: a request that re-derives to another CallIdentity than
the one the step already journals is refused before its intent
(BVL-RES-001; the actor-call handler refuses it before any write), so a restart
can never add a second call to a step.  In a
resumed episode (T2-006, ``resume=True``) a custody-accepted call is returned
from its re-verified evidence, never re-invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.identity.kinds import RequestIdentity
from boomvalley_lab.kernel.adapter2 import ActorAdapterV2, ActorResponseV2
from boomvalley_lab.kernel.authorization import require_run_authorization_v2
from boomvalley_lab.kernel.containment import ADAPTER, plugin_window
from boomvalley_lab.kernel.custody2 import (
    CustodyLedgerV2,
    accept_call_v2,
    call_artifact_name,
    verify_call_v2,
)
from boomvalley_lab.kernel.document_store import EvidenceDocumentRefV2, EvidenceDocumentStoreV2
from boomvalley_lab.kernel.identity import (
    CallIdentity,
    CustodyEntryIdentity,
    EpisodeIdentity,
    StepIdentity,
)
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_OUTCOME_UNKNOWN,
    CALL_PERSISTED,
    CALL_RETURNED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.recovery2 import CallStateV2, classify_call_v2
from boomvalley_lab.kernel.replay import (
    RESUME_EVIDENCE_MISMATCH,
    RESUME_OUTCOME_NOT_PROVEN,
    ResumeRefusedError,
)
from boomvalley_lab.kernel.request import RequestV2
from boomvalley_lab.kernel.request_store import RequestRefV2, RequestStoreV2
from boomvalley_lab.store.artifacts import ArtifactRef, ArtifactStore, content_identity


@dataclass(frozen=True)
class CompletedCallV2:
    call_identity: CallIdentity
    request: RequestRefV2
    response: ActorResponseV2
    artifact: ArtifactRef
    custody: CustodyEntryIdentity


def call_identity_v2(
    *,
    episode: EpisodeIdentity,
    step: StepIdentity,
    round_index: int,
    request: RequestRefV2,
    adapter_plugin_identity: str,
) -> CallIdentity:
    return call_identity_of(
        episode=episode,
        step=step,
        round_index=round_index,
        request=request.identity,
        adapter_plugin_identity=adapter_plugin_identity,
    )


def call_identity_of(
    *,
    episode: EpisodeIdentity,
    step: StepIdentity,
    round_index: int,
    request: RequestIdentity,
    adapter_plugin_identity: str,
) -> CallIdentity:
    """The CallIdentity of a request-2, computable before it is persisted."""

    return CallIdentity.of_payload(
        {
            "episode": episode.document(),
            "step": step.document(),
            "round": round_index,
            "request": request.document(),
            "adapter": adapter_plugin_identity,
        }
    )


class DurableCallExecutorV2:
    def __init__(self, run_directory: Path, *, run_id: str) -> None:
        if not run_id:
            raise ValueError("run_id must be non-empty")
        self.run_id = run_id
        self.run_directory = Path(run_directory)
        self.requests = RequestStoreV2(run_directory)
        self.artifacts = ArtifactStore(run_directory)
        self.journal = Journal2(run_directory)

    def execute(
        self,
        *,
        episode: EpisodeIdentity,
        step: StepIdentity,
        round_index: int,
        request: RequestV2,
        adapter: ActorAdapterV2,
        binding: EvidenceDocumentRefV2 | None = None,
        resume: bool = False,
    ) -> CompletedCallV2:
        require_run_authorization_v2(
            self.requests.root.parent, run_id=self.run_id, journal=self.journal
        )
        request_ref = self.requests.put(request)
        call = call_identity_v2(
            episode=episode,
            step=step,
            round_index=round_index,
            request=request_ref,
            adapter_plugin_identity=adapter.plugin_identity,
        )
        if binding is not None:
            # the L1 call binding is durable before intent and is this call's
            bound = EvidenceDocumentStoreV2(self.run_directory).read(binding)
            if binding.role != "call_binding" or bound.get("call") != call.document():
                raise ExecutionError(f"call binding {binding.path} is not call {call}'s")
        named = {} if binding is None else {"call_binding": binding.document()}

        if self.journal.torn_tail():
            raise ExecutionError("journal-2 has a torn tail; refusing to append call evidence")
        if CustodyLedgerV2(self.requests.root.parent).torn_tail():
            raise ExecutionError("custody-v2 has a torn tail; refusing to append call evidence")
        self.require_step_call(episode=episode, step=step, call=call)
        classified = classify_call_v2(
            run_directory=self.requests.root.parent,
            call=call,
            journal=self.journal,
            requests=self.requests,
            artifacts=self.artifacts,
        )
        if classified.state is CallStateV2.NOT_STARTED:
            self.journal.append_event(
                CALL_INTENT_RECORDED,
                run=self.run_id,
                episode=str(episode),
                step=str(step),
                round=round_index,
                call=str(call),
                request=request_ref.document(),
                **named,
            )
        elif classified.state is CallStateV2.INTENT_RECORDED:
            intent = next(iter(self.journal.of_call(str(call))))
            if intent["run"] != self.run_id:
                raise ExecutionError(f"call {call} intent belongs to another run")
            if intent.get("call_binding") != named.get("call_binding"):
                raise ExecutionError(f"call {call} intent names another call binding")
        elif resume and classified.state is CallStateV2.CUSTODY_ACCEPTED:
            return self._recorded(call, request_ref, named)
        elif resume:
            raise ResumeRefusedError(
                RESUME_OUTCOME_NOT_PROVEN,
                f"call {call} is {classified.state.value}; resume decision "
                f"{classified.decision.value}; the executor never re-invokes a provider"
                + (f" ({classified.reason})" if classified.reason else ""),
            )
        else:
            raise ExecutionError(
                f"call {call} is {classified.state.value}; resume decision "
                f"{classified.decision.value}; the executor never re-invokes a provider"
                + (f" ({classified.reason})" if classified.reason else "")
            )

        self.journal.append_event(
            TRANSPORT_STARTED,
            run=self.run_id,
            episode=str(episode),
            step=str(step),
            round=round_index,
            call=str(call),
        )
        try:
            # the one engine-authorized transport window (T0-016)
            with plugin_window(ADAPTER, adapter.plugin_identity):
                response = adapter.invoke(request)
        except Exception as error:
            self.journal.append_event(
                CALL_OUTCOME_UNKNOWN,
                run=self.run_id,
                episode=str(episode),
                step=str(step),
                round=round_index,
                call=str(call),
                reason=type(error).__name__,
            )
            raise

        response_digest = sha256_bytes(response.content)
        self.journal.append_event(
            CALL_RETURNED,
            run=self.run_id,
            episode=str(episode),
            step=str(step),
            round=round_index,
            call=str(call),
            response={
                "content_digest": str(response_digest),
                "model_identity": response.model_identity,
                "adapter_provenance": response.adapter_provenance,
            },
        )

        artifact = self.artifacts.put(
            call_artifact_name(call),
            response.content,
        )
        self.journal.append_event(
            CALL_PERSISTED,
            run=self.run_id,
            episode=str(episode),
            step=str(step),
            round=round_index,
            call=str(call),
            artifact=artifact.document(),
        )
        _, custody = accept_call_v2(
            run_directory=self.requests.root.parent,
            run_id=self.run_id,
            call=call,
            journal=self.journal,
            requests=self.requests,
            artifacts=self.artifacts,
        )
        return CompletedCallV2(call, request_ref, response, artifact, custody)

    def require_step_call(
        self, *, episode: EpisodeIdentity, step: StepIdentity, call: CallIdentity
    ) -> None:
        """A step makes one call: refuse *call* if the step journals another."""

        others = sorted(
            {
                event["call"]
                for event in self.journal.of_step(str(step))
                if "call" in event
                and event.get("step") == str(step)
                and event.get("episode") == str(episode)
                and event["call"] != str(call)
            }
        )
        if others:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"step {step} already carries {others[0]}; its request re-derives to {call}: "
                "the evidence it is built from does not reproduce the journaled call",
            )

    def _recorded(
        self, call: CallIdentity, request: RequestRefV2, named: dict
    ) -> CompletedCallV2:
        """The custody-accepted call, read back through its re-verified chain."""

        custody = verify_call_v2(
            run_directory=self.run_directory,
            call=call,
            journal=self.journal,
            requests=self.requests,
            artifacts=self.artifacts,
        )
        events = {
            event["event"]: event for event in self.journal.of_call(str(call))
        }
        intent, returned = events[CALL_INTENT_RECORDED], events[CALL_RETURNED]["response"]
        if intent["run"] != self.run_id:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH, f"call {call} belongs to another run"
            )
        if intent.get("call_binding") != named.get("call_binding"):
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH, f"call {call} intent names another call binding"
            )
        name = call_artifact_name(call)
        content = self.artifacts.path(name).read_bytes()
        artifact = ArtifactRef(name, content_identity(content))
        if artifact.document() != events[CALL_PERSISTED]["artifact"]:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH, f"call {call} response member is not the persisted one"
            )
        response = ActorResponseV2(
            content=content,
            model_identity=returned["model_identity"],
            adapter_provenance=returned["adapter_provenance"],
        )
        return CompletedCallV2(call, request, response, artifact, custody)
