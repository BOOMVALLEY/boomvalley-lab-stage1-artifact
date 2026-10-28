"""Generic one-node handlers for the K0/B8-lite runtime.

Each handler owns exactly one semantic node.  Study-specific behavior is
provided through typed renderer/parser/World plugins; orchestration remains in
GenericEpisodeEngine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.kernel.actors import (
    MODEL_IDENTITY_MISMATCH,
    PROFILE_IDENTITY_MISMATCH,
    PROVIDER_IDENTITY_MISMATCH,
    UNDECLARED_PROFILE_OVERRIDE,
    ActorBindingV1,
    ActorError,
)
from boomvalley_lab.kernel.adapter2 import ActorAdapterV2
from boomvalley_lab.kernel.call_executor import (
    CompletedCallV2,
    DurableCallExecutorV2,
    call_identity_of,
)
from boomvalley_lab.kernel.containment import PARSER, RENDERER, active_session, invoke_pure
from boomvalley_lab.kernel.decisions import (
    BUILTIN_RULES,
    PROPOSAL_INVALID,
    REQUIRED_PROPOSAL_MISSING,
    RULE_IDENTITY_MISMATCH,
    RULE_NOT_REGISTERED,
    CandidateV1,
    DecisionError,
    DecisionOutcome,
    DecisionRuleV1,
    candidate_document,
    run_rule,
    settle,
)
from boomvalley_lab.kernel.decisions import (
    EVIDENCE_SCHEMA_V2 as DECISION_EVIDENCE_SCHEMA_V2,
)
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentRefV2,
    EvidenceDocumentStoreV2,
)
from boomvalley_lab.kernel.engine import EngineContext, HandlerResult
from boomvalley_lab.kernel.human import HUMAN_EXECUTION_UNSUPPORTED, HumanError
from boomvalley_lab.kernel.identity import (
    DecisionArtifactIdentity,
    MemoryArtifactIdentity,
    ProposalIdentity,
)
from boomvalley_lab.kernel.information import InformationSourceStoreV1
from boomvalley_lab.kernel.journal2 import (
    DECISION_FAILED,
    DECISION_RECORDED,
    MEMORY_RECORDED,
    PROPOSAL_PARSE_FAILED,
    PROPOSAL_PARSED,
    Journal2,
)
from boomvalley_lab.kernel.l1_evidence import call_binding_document
from boomvalley_lab.kernel.memory import (
    artifact_payload,
    node_policy,
    transformed,
)
from boomvalley_lab.kernel.pipeline import (
    DEFAULT_CODEC,
    ActorRendererV1,
    PipelineTraceV1,
    ProviderCodecV1,
    RequestPipelineV1,
    SourceTransformV1,
)
from boomvalley_lab.kernel.proposals import (
    EVIDENCE_SCHEMA_V1,
    EVIDENCE_SCHEMA_V2,
    PARSE_FAILED,
    PARSER_IDENTITY_MISMATCH,
    PARSER_NOT_REGISTERED,
    ParseVerdict,
    ProposalContractV1,
    ProposalError,
    ProposalParserV1,
    attempt_parse,
    judge,
)
from boomvalley_lab.kernel.protocol import ProtocolNode
from boomvalley_lab.kernel.replay import commit
from boomvalley_lab.kernel.request import RequestV2
from boomvalley_lab.kernel.seed import SeedDerivation
from boomvalley_lab.kernel.tool import execution_unsupported as tool_execution_unsupported
from boomvalley_lab.kernel.tool import select_tool_arguments, tool_intent
from boomvalley_lab.kernel.tool_actor_call import ToolExchangeV1, execute_tool_actor_call
from boomvalley_lab.kernel.tool_call import DurableToolCallExecutorV1
from boomvalley_lab.kernel.waiting import HumanDeskV1, HumanExchangeV1, execute_human_call
from boomvalley_lab.kernel.world import PureWorld
from boomvalley_lab.kernel.world_executor import (
    AppliedWorldTransitionV2,
    DurableWorldTransitionV2,
)
from boomvalley_lab.kernel.world_registry import WorldRegistryV1


class ObservationRendererV2(Protocol):
    """Historical T0 renderer (plans without actors): builds request-2 itself."""

    plugin_identity: str

    def render(
        self,
        node: ProtocolNode,
        context: EngineContext,
        *,
        seed: int,
    ) -> RequestV2: ...


class ProposalParserV2(Protocol):
    plugin_identity: str

    def parse(self, content: bytes) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ActorProfileV2:
    actor_id: str
    renderer: ObservationRendererV2
    adapter: ActorAdapterV2


@dataclass(frozen=True)
class ParsedProposalV2:
    identity: ProposalIdentity
    actor_call: CompletedCallV2
    value: Mapping[str, Any]
    evidence: EvidenceDocumentRefV2
    # P06 verdict (T1-004); historical unschematized proposals are VALID
    verdict: ParseVerdict = ParseVerdict.VALID


@dataclass(frozen=True)
class DecisionArtifactV2:
    identity: DecisionArtifactIdentity
    rule_identity: str
    # P07 (T1-005): the selected proposal of a SELECTED decision; None for an
    # AGGREGATE (see ``supporting_proposals``) or NO_ACTION decision
    selected_proposal: ProposalIdentity | None
    requested_action: Mapping[str, Any]
    evidence: EvidenceDocumentRefV2
    outcome: DecisionOutcome = DecisionOutcome.SELECTED
    supporting_proposals: tuple[ProposalIdentity, ...] = ()
    # every candidate the rule saw (P07 decisions; empty for a decision-1)
    candidate_proposals: tuple[ProposalIdentity, ...] = ()

    def source_proposal(self) -> ProposalIdentity | None:
        """The proposal whose custody-accepted call anchors the World intent.

        SELECTED: the selected proposal.  AGGREGATE: the canonical first
        supporting proposal (every supporter carries the decided action; the
        choice is content-ordered, never call-ordered).  NO_ACTION: no proposal
        carries the decision, so the canonical first candidate the rule saw
        (T3-004): a NO_ACTION input is custody-anchored like any other.
        """

        if self.selected_proposal is not None:
            return self.selected_proposal
        if self.supporting_proposals:
            return min(self.supporting_proposals, key=str)
        if self.outcome is DecisionOutcome.NO_ACTION and self.candidate_proposals:
            return min(self.candidate_proposals, key=str)
        return None


@dataclass(frozen=True)
class MemoryArtifactV2:
    identity: MemoryArtifactIdentity
    owner: str
    value: Mapping[str, Any]
    evidence: EvidenceDocumentRefV2
    # the full artifact document under a memory lifecycle (T4-003)
    document: Mapping[str, Any] | None = None


class ActorCallHandlerV2:
    """One engine-owned actor call.

    Under a plan that declares actors (P04, T1-001) the actor, its role and
    its ExecutionProfile come from the frozen plan (``context.actors``); the
    handler only resolves the profile's renderer/provider plugin identities
    to implementations and holds the call to the profile:

    - the provider adapter is the profile's provider     (BVL-ACTOR-006)
    - the request's renderer is the profile's renderer   (BVL-ACTOR-005)
    - model / options / seed are the profile's           (BVL-ACTOR-007/010)

    all before intent (zero external calls on refusal), and after the call
    the reported model is the intended one (BVL-ACTOR-007; the response is
    already durable evidence and the engine journals EPISODE_FAILED).

    request-2 of a planned call is built by the one P05 pipeline (T1-003,
    ``RequestPipelineV1``): source -> default-deny access -> registered
    transform -> the profile's renderer (content only, an
    ``ActorRendererV1``) -> the provider's codec (``codecs`` keyed by provider
    identity; default ``builtin.chat-messages-codec:1``) -> request-2
    assembled from the frozen profile.  Under a plan that declares
    information (P05, T1-002) the renderer receives only the actor's
    authorized observation; before intent the request is checked for
    withheld content (BVL-INFO-005) and source files must be denied to plugin
    windows (BVL-INFO-011).  ``traces`` holds each built call's pipeline
    trace; the call's L1 ``call_binding`` evidence (T1-008) persists it with
    the actor / role / profile identities before intent.

    ``profiles`` keyed by a bare actor string is the historical T0 path for
    plans without actors; the two never mix.

    An actor the plan contracts as a person (P17, ``context.humans``) is asked
    through its human channel and the desk instead of an adapter (T5-002,
    ``kernel.waiting``): the same request-2, call binding, call chain and
    custody, and a call that may wait for its answer.

    An actor the plan contracts as a tool (P17, ``context.tools``) is answered
    by its bound tool through the journaled tool call instead of an adapter
    (T5-007, ``kernel.tool_actor_call``): the same request-2, call binding,
    call chain and custody.  Its arguments are the contract's declared
    selection over the actor's observation, typed before anything is written
    (BVL-TOOL-005).
    """

    def __init__(
        self,
        *,
        calls: DurableCallExecutorV2,
        seeds: SeedDerivation,
        profiles: Mapping[str, ActorProfileV2] | None = None,
        renderers: Mapping[str, ActorRendererV1] | None = None,
        adapters: Mapping[str, ActorAdapterV2] | None = None,
        codecs: Mapping[str, ProviderCodecV1] | None = None,
        sources: InformationSourceStoreV1 | None = None,
        transforms: Mapping[str, SourceTransformV1] | None = None,
        channels: Mapping[str, object] | None = None,
        desk: HumanDeskV1 | None = None,
        tools: Mapping[str, object] | None = None,
        tool_calls: DurableToolCallExecutorV1 | None = None,
    ) -> None:
        if (profiles is None) == (renderers is None and adapters is None):
            raise ValueError("supply either profiles (T0 path) or renderers+adapters (P04)")
        if profiles is None and (renderers is None or adapters is None):
            raise ValueError("P04 actor calls need both renderers and adapters")
        if profiles is not None and (codecs or sources or transforms):
            raise ValueError("the historical T0 path has no P05 pipeline stages")
        self._profiles = dict(profiles or {})
        self._renderers = dict(renderers or {})
        self._adapters = dict(adapters or {})
        self._codecs = dict(codecs or {})
        self._calls = calls
        self._seeds = seeds
        self._channels = dict(channels or {})
        self._desk = desk
        self._tools = dict(tools or {})
        self._tool_calls = tool_calls
        self._pipeline = RequestPipelineV1(sources=sources, transforms=transforms)
        self.traces: list[PipelineTraceV1] = []

    @property
    def seed_tree(self) -> SeedDerivation:
        return self._seeds

    def __call__(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        if context.actors is not None:
            if self._profiles:
                raise ExecutionError("a plan with actors is never executed from loose profiles")
            return self._planned_call(node, context)
        if not self._profiles:
            raise ExecutionError("P04 actor calls run only under a plan that declares actors")
        actor_id = node.config.get("actor")
        if not isinstance(actor_id, str) or actor_id not in self._profiles:
            raise ExecutionError(f"actor_call {node.node_id!r} has no registered actor")
        if context.step_identity is None:
            raise ExecutionError("actor_call has no engine-owned StepIdentity")

        profile = self._profiles[actor_id]
        seed = self._seeds.actor_call(
            str(context.episode_identity),
            round_index=context.round_index,
            step_id=node.node_id,
            actor_id=actor_id,
        )
        request = invoke_pure(
            RENDERER,
            profile.renderer,
            lambda renderer: renderer.render(node, context, seed=seed),
            RequestV2.document,
        )
        completed = self._calls.execute(
            episode=context.episode_identity,
            step=context.step_identity,
            round_index=context.round_index,
            request=request,
            adapter=profile.adapter,
            resume=context.resumed,
        )
        return HandlerResult(completed)

    def _planned_call(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        if context.step_identity is None:
            raise ExecutionError("actor_call has no engine-owned StepIdentity")
        binding: ActorBindingV1 = context.actors.binding(node.config.get("actor"))
        profile = binding.profile
        renderer = self._renderers.get(profile.renderer)
        if renderer is None:
            raise ActorError(
                PROFILE_IDENTITY_MISMATCH,
                f"renderer {profile.renderer!r} of actor {binding.actor_id!r} is not supplied",
            )
        humans = getattr(context, "humans", None)  # the plan's P17 contracts, if any
        human = (
            None if humans is None or binding.actor_id not in humans
            else humans.contract(binding.actor_id)
        )
        tools = getattr(context, "tools", None)  # the plan's P17 tool contracts, if any
        tool = (
            None if tools is None or binding.actor_id not in tools
            else tools.contract(binding.actor_id)
        )
        adapter = self._adapters.get(profile.provider)
        if tool is not None:
            if (
                not tool.executable
                or self._tool_calls is None
                or profile.provider not in self._tools
            ):
                raise tool_execution_unsupported([binding.actor_id])
        elif human is not None:
            if self._desk is None or profile.provider not in self._channels:
                raise HumanError(
                    HUMAN_EXECUTION_UNSUPPORTED,
                    f"human actor {binding.actor_id!r} has no desk and registered channel "
                    "to be asked through",
                )
        elif adapter is None or adapter.plugin_identity != profile.provider:
            raise ActorError(
                PROVIDER_IDENTITY_MISMATCH,
                f"provider {profile.provider!r} of actor {binding.actor_id!r} is not supplied "
                "under its registered identity",
            )
        seed = profile.resolve_seed(
            self._seeds,
            actor=binding.identity,
            episode_key=str(context.episode_identity),
            round_index=context.round_index,
            step_id=node.node_id,
        )
        built = self._pipeline.build(
            node=node,
            context=context,
            binding=binding,
            renderer=renderer,
            codec=self._codecs.get(profile.provider, DEFAULT_CODEC),
            seed=seed,
        )
        request = built.request
        _hold_request_to_profile(binding, request, seed)
        self.traces.append(built.trace)
        arguments = None
        if tool is not None:
            # the declared selection over what the actor observes, typed before
            # any evidence of the call is written (BVL-TOOL-005)
            observation, _ = self._pipeline.observe(context, binding.actor_id)
            arguments = select_tool_arguments(tool, observation.read)
            tool_intent(
                tool, binding, step=context.step_identity, request=request,
                arguments=arguments,
            )
        call = call_identity_of(
            episode=context.episode_identity,
            step=context.step_identity,
            round_index=context.round_index,
            request=request.identity(),
            adapter_plugin_identity=profile.provider,
        )
        # a step makes one call (T2-006): refused before any evidence is written
        self._calls.require_step_call(
            episode=context.episode_identity, step=context.step_identity, call=call
        )
        # L1 call binding (T1-008): durable before intent, named by it
        evidence = EvidenceDocumentStoreV2(self._calls.run_directory).put(
            "call_binding",
            call_binding_document(
                call=call,
                episode=context.episode_identity.document(),
                step=context.step_identity.document(),
                round_index=context.round_index,
                node_id=node.node_id,
                request=request,
                binding=binding,
                trace=built.trace,
            ),
        )
        if tool is not None:
            completed = execute_tool_actor_call(
                self._calls,
                self._tool_calls,
                episode=context.episode_identity,
                step=context.step_identity,
                round_index=context.round_index,
                request=request,
                exchange=ToolExchangeV1(tool, binding, self._tools[profile.provider]),
                arguments=arguments,
                binding=evidence,
                resume=context.resumed,
            )
        elif human is not None:
            completed = execute_human_call(
                self._calls,
                episode=context.episode_identity,
                step=context.step_identity,
                round_index=context.round_index,
                request=request,
                exchange=HumanExchangeV1(
                    human, binding, self._channels[profile.provider], self._desk
                ),
                binding=evidence,
                resume=context.resumed,
            )
        else:
            completed = self._calls.execute(
                episode=context.episode_identity,
                step=context.step_identity,
                round_index=context.round_index,
                request=request,
                adapter=adapter,
                binding=evidence,
                resume=context.resumed,
            )
        if completed.response.model_identity != profile.model:
            raise ActorError(
                MODEL_IDENTITY_MISMATCH,
                f"actor {binding.actor_id!r} intended model {profile.model!r}, "
                f"provider reported {completed.response.model_identity!r}",
            )
        return HandlerResult(completed)


def _hold_request_to_profile(binding: ActorBindingV1, request: RequestV2, seed: int) -> None:
    """request-2 carries exactly the frozen profile (a pipeline postcondition)."""

    profile = binding.profile
    if request.renderer_identity != profile.renderer:
        raise ActorError(
            PROFILE_IDENTITY_MISMATCH,
            f"actor {binding.actor_id!r} request was rendered by {request.renderer_identity!r}, "
            f"its profile binds {profile.renderer!r}",
        )
    if request.model_identity != profile.model:
        raise ActorError(
            MODEL_IDENTITY_MISMATCH,
            f"actor {binding.actor_id!r} request names model {request.model_identity!r}, "
            f"its profile binds {profile.model!r}",
        )
    if canonical_json(dict(request.options)) != canonical_json(dict(profile.options)):
        raise ActorError(
            UNDECLARED_PROFILE_OVERRIDE,
            f"actor {binding.actor_id!r} request options differ from its frozen profile",
        )
    if request.resolved_seed != seed:
        raise ActorError(
            UNDECLARED_PROFILE_OVERRIDE,
            f"actor {binding.actor_id!r} request seed is not the profile-derived seed",
        )


class ProposalParseHandlerV2:
    """One engine-owned proposal parse (P06).

    Under a plan carrying P06 proposal contracts (T1-004) the node's parser,
    parser config, proposal schema and failure policy come from the frozen
    plan (``context.proposals``); *proposal_parsers* only resolves the
    contract's parser plugin identity to an implementation:

    - no implementation registered for the contract's parser   BVL-PROP-001
    - implementation reporting another plugin identity          BVL-PROP-002

    The parser runs contained (pure and replayed: deterministic or refused)
    on the custody-accepted response bytes.  Its ``ProposalSyntaxError`` is
    BVL-PROP-004 and output outside the schema's closed typed shape is
    BVL-PROP-005.  Under PARSE_FAILURE the invalid proposal is evidenced,
    PROPOSAL_PARSE_FAILED journaled and the episode fails with that code;
    under NO_ACTION an explicit NO_ACTION proposal is committed.  Domain
    admissibility is never judged here: it is the World's verdict (P15).

    A plan without contracts keeps the historical unschematized parse by
    ``node.config["parser"]`` and ``boomvalley-lab-proposal-1`` evidence.
    """

    def __init__(
        self,
        *,
        parsers: Mapping[str, ProposalParserV2],
        journal: Journal2,
        documents: EvidenceDocumentStoreV2,
        run_id: str,
        proposal_parsers: Mapping[str, ProposalParserV1] | None = None,
    ) -> None:
        self._parsers = dict(parsers)
        self._proposal_parsers = dict(proposal_parsers or {})
        self._journal = journal
        self._documents = documents
        self._run_id = run_id

    def __call__(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        if len(node.depends_on) != 1:
            raise ExecutionError(
                f"proposal_parse {node.node_id!r} needs exactly one actor-call dependency"
            )
        source = context.dependency(node.depends_on[0])
        if not isinstance(source, CompletedCallV2):
            raise ExecutionError(
                f"proposal_parse {node.node_id!r} dependency is not a completed actor call"
            )
        if context.proposals is not None:
            contract = context.proposals.contract(node.node_id)
            return self._contracted(node, context, source, contract)
        parser_id = node.config.get("parser")
        if not isinstance(parser_id, str) or parser_id not in self._parsers:
            raise ExecutionError(f"proposal_parse {node.node_id!r} has no registered parser")
        parser = self._parsers[parser_id]
        value = invoke_pure(
            PARSER,
            parser,
            lambda plugin: dict(plugin.parse(source.response.content)),
            dict,
        )
        return self._commit(context, source, parser.plugin_identity, value, {})

    def _contracted(
        self,
        node: ProtocolNode,
        context: EngineContext,
        source: CompletedCallV2,
        contract: ProposalContractV1,
    ) -> HandlerResult:
        parser = self._proposal_parsers.get(contract.parser)
        if parser is None:
            raise ProposalError(
                PARSER_NOT_REGISTERED,
                f"proposal_parse {node.node_id!r}: parser {contract.parser!r} is not registered",
            )
        reported = getattr(parser, "plugin_identity", None)
        if reported != contract.parser:
            raise ProposalError(
                PARSER_IDENTITY_MISMATCH,
                f"proposal_parse {node.node_id!r}: implementation is {reported!r}, "
                f"the plan binds {contract.parser!r}",
            )
        config = dict(contract.config)
        attempt = invoke_pure(
            PARSER,
            parser,
            lambda plugin: attempt_parse(plugin, source.response.content, dict(config)),
            repr,
        )
        session = active_session()
        if session is not None:
            # a refused hidden call (BVL-PROP-009) swallowed by the parser is
            # never relabelled as a syntax verdict
            session.check()
        outcome = judge(contract, attempt)
        extra = {
            "contract": contract.document(),
            "verdict": outcome.verdict.value,
            "reason": dict(outcome.reason) if outcome.reason is not None else None,
        }
        if outcome.verdict is not ParseVerdict.INVALID:
            return self._commit(context, source, contract.parser, dict(outcome.value), extra)
        identity, _ = self._evidence(context, source, contract.parser, {}, extra)
        commit(
            self._journal,
            PROPOSAL_PARSE_FAILED,
            resumed=context.resumed,
            run=self._run_id,
            episode=str(context.episode_identity),
            step=str(context.step_identity),
            round=context.round_index,
            proposal={
                "identity": identity.document(),
                "parser": contract.parser,
                "schema": contract.schema.ref,
                "verdict": outcome.verdict.value,
                "reason": extra["reason"],
            },
        )
        reason = extra["reason"] or {"code": PARSE_FAILED, "detail": "invalid"}
        raise ProposalError(
            reason["code"],
            f"proposal_parse {node.node_id!r} round {context.round_index}: {reason['detail']}",
        )

    def _evidence(
        self,
        context: EngineContext,
        source: CompletedCallV2,
        parser: str,
        value: Mapping[str, Any],
        extra: Mapping[str, Any],
    ) -> tuple[ProposalIdentity, EvidenceDocumentRefV2]:
        """Proposal-1 (no contract) or proposal-2 (contract, verdict, reason)."""

        content = {
            "episode": context.episode_identity.document(),
            "step": context.step_identity.document(),
            "round": context.round_index,
            "call": source.call_identity.document(),
            "response_artifact": source.artifact.document(),
            "parser": parser,
        }
        identity = ProposalIdentity.of_payload({**content, "proposal": dict(value), **extra})
        evidence = self._documents.put(
            "proposal",
            {
                "schema": EVIDENCE_SCHEMA_V2 if extra else EVIDENCE_SCHEMA_V1,
                "identity": identity.document(),
                **content,
                "value": dict(value),
                **extra,
            },
        )
        return identity, evidence

    def _commit(
        self,
        context: EngineContext,
        source: CompletedCallV2,
        parser: str,
        value: dict[str, Any],
        extra: Mapping[str, Any],
    ) -> HandlerResult:
        identity, evidence = self._evidence(context, source, parser, value, extra)
        verdict = ParseVerdict(extra.get("verdict", ParseVerdict.VALID.value))
        event: dict[str, Any] = {"identity": identity.document(), "parser": parser, "value": value}
        if extra:
            event["schema"] = extra["contract"]["proposal_schema"]["schema_id"]
            event["verdict"] = verdict.value
        commit(
            self._journal,
            PROPOSAL_PARSED,
            resumed=context.resumed,
            run=self._run_id,
            episode=str(context.episode_identity),
            step=str(context.step_identity),
            round=context.round_index,
            proposal=event,
        )
        return HandlerResult(ParsedProposalV2(identity, source, value, evidence, verdict))


class SingleAuthorityDecisionHandlerV2:
    plugin_identity = "builtin.single-authority-v2:1"

    def __init__(
        self,
        *,
        journal: Journal2,
        documents: EvidenceDocumentStoreV2,
        run_id: str,
    ) -> None:
        self._journal = journal
        self._documents = documents
        self._run_id = run_id

    def __call__(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        source_id = node.config.get("binding")
        if not isinstance(source_id, str) or source_id not in node.depends_on:
            raise ExecutionError(
                f"decision {node.node_id!r} binding must name one declared dependency"
            )
        selected = context.dependency(source_id)
        if not isinstance(selected, ParsedProposalV2):
            raise ExecutionError(
                f"decision {node.node_id!r} binding is not a parsed proposal"
            )
        if selected.verdict is not ParseVerdict.VALID:
            # acting on (or abstaining from) a NO_ACTION proposal is P07 (T1-005)
            raise ExecutionError(
                f"decision {node.node_id!r} binding is a {selected.verdict.value} proposal; "
                "single authority requires a VALID proposal"
            )
        requested_action = dict(selected.value)
        identity = DecisionArtifactIdentity.of_payload(
            {
                "episode": context.episode_identity.document(),
                "step": context.step_identity.document(),
                "round": context.round_index,
                "rule": self.plugin_identity,
                "selected_proposal": selected.identity.document(),
                "requested_action": requested_action,
            }
        )
        evidence = self._documents.put(
            "decision",
            {
                "schema": "boomvalley-lab-decision-1",
                "identity": identity.document(),
                "episode": context.episode_identity.document(),
                "step": context.step_identity.document(),
                "round": context.round_index,
                "rule": self.plugin_identity,
                "selected_proposal": selected.identity.document(),
                "requested_action": requested_action,
            },
        )
        decision = DecisionArtifactV2(
            identity,
            self.plugin_identity,
            selected.identity,
            requested_action,
            evidence,
        )
        commit(
            self._journal,
            DECISION_RECORDED,
            resumed=context.resumed,
            run=self._run_id,
            episode=str(context.episode_identity),
            step=str(context.step_identity),
            round=context.round_index,
            decision={
                "identity": identity.document(),
                "rule": self.plugin_identity,
                "selected_proposal": selected.identity.document(),
                "requested_action": requested_action,
            },
        )
        return HandlerResult(decision)


class DecisionRuleHandlerV1:
    """One engine-owned decision under a registered P07 rule (T1-005).

    Under a plan carrying P07 decision contracts the rule, its config, the
    authority (eligible actors and their proposal inputs) and the unresolved
    policy come from the frozen plan (``context.decisions``); *rules* only
    resolves the contract's rule plugin identity to an implementation
    (builtin single-authority / majority / plurality are always present):

    - no implementation registered for the contract's rule     BVL-DEC-001
    - implementation reporting another plugin identity          BVL-DEC-002
    - an authority input that is not a committed proposal       BVL-DEC-003
    - an INVALID proposal reaching the decision                 BVL-DEC-004

    The rule sees ``CandidateV1`` only (actor, proposal identity, verdict,
    value) and runs contained, replayed and on every candidate order
    (BVL-DEC-012 when the order matters).  The kernel settles its outcome
    (``decisions.settle``): a SELECTED / AGGREGATE action is checked against
    the candidates' P06 schema (BVL-DEC-011); an unresolved outcome follows
    the declared policy - NO_ACTION commits an explicit NO_ACTION decision,
    FAIL_EPISODE evidences the failed decision, journals DECISION_FAILED and
    fails the episode with the rule's code (003 / 006 / 007).

    A plan without decision contracts keeps the historical single-authority
    decision by ``node.config["binding"]`` and decision-1 evidence.
    """

    def __init__(
        self,
        *,
        journal: Journal2,
        documents: EvidenceDocumentStoreV2,
        run_id: str,
        rules: Mapping[str, DecisionRuleV1] | None = None,
    ) -> None:
        self._legacy = SingleAuthorityDecisionHandlerV2(
            journal=journal, documents=documents, run_id=run_id
        )
        self._rules = {**BUILTIN_RULES, **dict(rules or {})}
        self._journal = journal
        self._documents = documents
        self._run_id = run_id

    def __call__(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        if context.decisions is None:
            return self._legacy(node, context)
        contract = context.decisions.contract(node.node_id)
        rule = self._rules.get(contract.rule)
        if rule is None:
            raise DecisionError(
                RULE_NOT_REGISTERED,
                f"decision {node.node_id!r}: rule {contract.rule!r} is not registered",
            )
        reported = getattr(rule, "plugin_identity", None)
        if reported != contract.rule:
            raise DecisionError(
                RULE_IDENTITY_MISMATCH,
                f"decision {node.node_id!r}: implementation is {reported!r}, "
                f"the plan binds {contract.rule!r}",
            )
        candidates: list[CandidateV1] = []
        documents: list[dict[str, Any]] = []
        identities: dict[str, ProposalIdentity] = {}
        for actor, parse_node in sorted(contract.candidates.items()):
            proposal = context.current_round.get(parse_node)
            if not isinstance(proposal, ParsedProposalV2):
                raise DecisionError(
                    REQUIRED_PROPOSAL_MISSING,
                    f"decision {node.node_id!r}: {actor!r} has no committed proposal "
                    f"of {parse_node!r}",
                )
            if proposal.verdict is ParseVerdict.INVALID:
                raise DecisionError(
                    PROPOSAL_INVALID, f"decision {node.node_id!r}: {actor!r} proposal is INVALID"
                )
            candidate = CandidateV1(
                actor, str(proposal.identity), proposal.verdict.value, proposal.value
            )
            candidates.append(candidate)
            documents.append(
                candidate_document(candidate, parse_node, proposal.identity.document())
            )
            identities[candidate.proposal] = proposal.identity
        schema = context.proposals.contract(next(iter(contract.candidates.values()))).schema
        outcome = run_rule(rule, contract, tuple(candidates))
        settled = settle(contract, tuple(candidates), outcome, schema)
        selected = identities[settled.selected] if settled.selected is not None else None
        supporting = tuple(identities[key] for key in settled.supporting)
        content = {
            "episode": context.episode_identity.document(),
            "step": context.step_identity.document(),
            "round": context.round_index,
            "rule": contract.rule,
            "contract": contract.document(),
            "candidates": documents,
            "outcome": settled.outcome.value,
            "selected_proposal": selected.document() if selected is not None else None,
            "supporting_proposals": [identity.document() for identity in supporting],
            "requested_action": dict(settled.action),
            "tally": dict(settled.tally),
            "reason": dict(settled.reason) if settled.reason is not None else None,
        }
        identity = DecisionArtifactIdentity.of_payload(content)
        evidence = self._documents.put(
            "decision",
            {"schema": DECISION_EVIDENCE_SCHEMA_V2, "identity": identity.document(), **content},
        )
        if settled.outcome is DecisionOutcome.FAILED:
            reason = content["reason"]
            commit(
                self._journal,
                DECISION_FAILED,
                resumed=context.resumed,
                run=self._run_id,
                episode=str(context.episode_identity),
                step=str(context.step_identity),
                round=context.round_index,
                decision={"identity": identity.document(), "rule": contract.rule, "reason": reason},
            )
            raise DecisionError(
                reason["code"],
                f"decision {node.node_id!r} round {context.round_index}: {reason['detail']}",
            )
        commit(
            self._journal,
            DECISION_RECORDED,
            resumed=context.resumed,
            run=self._run_id,
            episode=str(context.episode_identity),
            step=str(context.step_identity),
            round=context.round_index,
            decision={
                "identity": identity.document(),
                "rule": contract.rule,
                "outcome": settled.outcome.value,
                "selected_proposal": content["selected_proposal"],
                "supporting_proposals": content["supporting_proposals"],
                "requested_action": content["requested_action"],
            },
        )
        return HandlerResult(
            DecisionArtifactV2(
                identity,
                contract.rule,
                selected,
                dict(settled.action),
                evidence,
                settled.outcome,
                supporting,
                tuple(identities.values()),
            )
        )


class WorldTransitionHandlerV2:
    """Apply one authoritative decision through the durable World boundary.

    Intent, apply, evidence and commit ordering, custody of the source call
    and crash recovery live in DurableWorldTransitionV2 (T0-011).
    """

    def __init__(
        self,
        *,
        worlds: Mapping[str, PureWorld],
        journal: Journal2,
        documents: EvidenceDocumentStoreV2,
        run_id: str,
        seeds: SeedDerivation,
    ) -> None:
        self._worlds = dict(worlds)
        self._seeds = seeds
        self._transitions = DurableWorldTransitionV2(
            journal.path.parent,
            run_id=run_id,
            journal=journal,
            documents=documents,
        )

    @property
    def seed_tree(self) -> SeedDerivation:
        return self._seeds

    def __call__(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        if len(node.depends_on) != 1:
            raise ExecutionError(
                f"world_transition {node.node_id!r} needs one decision dependency"
            )
        decision = context.dependency(node.depends_on[0])
        if not isinstance(decision, DecisionArtifactV2):
            raise ExecutionError(
                f"world_transition {node.node_id!r} dependency is not a DecisionArtifact"
            )
        world_id = node.config.get("world")
        if not isinstance(world_id, str) or world_id not in self._worlds:
            raise ExecutionError(f"world_transition {node.node_id!r} has no registered World")
        if context.step_identity is None:
            raise ExecutionError("world_transition has no engine-owned StepIdentity")
        no_action = decision.outcome is DecisionOutcome.NO_ACTION
        if no_action and context.world is None:
            # P07 §13.4: NO_ACTION is not a generic skip-World shortcut; its
            # domain transition semantics belong to a World contract (P15 §13.5)
            raise ExecutionError(
                f"world_transition {node.node_id!r}: a NO_ACTION decision has no World "
                "transition semantics without a World contract"
            )
        anchor = decision.source_proposal()
        sources = [
            value
            for value in context.current_round.values()
            if isinstance(value, ParsedProposalV2) and value.identity == anchor
        ]
        if len(sources) != 1:
            raise ExecutionError(
                f"world_transition {node.node_id!r} cannot trace its decision to one proposal"
            )
        world = self._worlds[world_id]
        if context.world is not None:
            # T3-001: only the registered World that still carries the plan's contract
            world = WorldRegistryV1(self._worlds).resolve(context.world)
        seed = self._seeds.world(
            str(context.episode_identity),
            round_index=context.round_index,
            transition_id=node.node_id,
        )
        applied = self._transitions.apply(
            episode=context.episode_identity,
            step=context.step_identity,
            round_index=context.round_index,
            node_id=node.node_id,
            decision=decision.identity,
            requested_action=decision.requested_action,
            source_call=sources[0].actor_call.call_identity,
            world=world,
            seed=seed,
            pre_state=context.world_state,
            contract=context.world,
            no_action=no_action,
        )
        return HandlerResult(applied, world_state=applied.transition.post_state)


class OutcomeMemoryHandlerV2:
    plugin_identity = "builtin.outcome-memory-v2:1"

    def __init__(
        self,
        *,
        journal: Journal2,
        documents: EvidenceDocumentStoreV2,
        run_id: str,
    ) -> None:
        self._journal = journal
        self._documents = documents
        self._run_id = run_id

    def __call__(self, node: ProtocolNode, context: EngineContext) -> HandlerResult:
        if len(node.depends_on) != 1:
            raise ExecutionError(
                f"memory_update {node.node_id!r} needs one World dependency"
            )
        applied = context.dependency(node.depends_on[0])
        if not isinstance(applied, AppliedWorldTransitionV2):
            raise ExecutionError(
                f"memory_update {node.node_id!r} dependency is not a World transition"
            )
        owner = node.config.get("owner")
        key = node.config.get("key")
        if not isinstance(owner, str) or not owner or not isinstance(key, str) or not key:
            raise ExecutionError(
                f"memory_update {node.node_id!r} needs non-empty owner and key"
            )
        if "scope" in node.config:
            return self._lifecycle(node, context, applied)
        value = dict(applied.transition.outcome)
        identity = MemoryArtifactIdentity.of_payload(
            {
                "owner": owner,
                "source_transition": applied.identity.document(),
                "transform": self.plugin_identity,
                "round": context.round_index,
                "value": value,
            }
        )
        evidence = self._documents.put(
            "memory",
            {
                "schema": "boomvalley-lab-memory-artifact-1",
                "identity": identity.document(),
                "owner": owner,
                "source_transition": applied.identity.document(),
                "transform": self.plugin_identity,
                "round": context.round_index,
                "value": value,
            },
        )
        memory = MemoryArtifactV2(identity, owner, value, evidence)
        commit(
            self._journal,
            MEMORY_RECORDED,
            resumed=context.resumed,
            run=self._run_id,
            episode=str(context.episode_identity),
            step=str(context.step_identity),
            round=context.round_index,
            memory={
                "identity": identity.document(),
                "owner": owner,
                "key": key,
                "value": value,
            },
        )
        return HandlerResult(memory, memory_updates={key: value})

    def _lifecycle(
        self, node: ProtocolNode, context: EngineContext, applied: AppliedWorldTransitionV2
    ) -> HandlerResult:
        """T4-003: one Memory Artifact of the node's declared lifecycle.

        Evidence and journal only: the engine's ledger, not a memory dict,
        carries it to later rounds as a granted ``memory_artifact`` source.
        """

        policy = node_policy(node)
        payload = artifact_payload(
            policy,
            episode=context.episode_identity.document(),
            step=context.step_identity.document(),
            round_index=context.round_index,
            source_transition=applied.identity.document(),
            value=transformed(policy.transform, {"outcome": dict(applied.transition.outcome)}),
            episode_key=context.episode_key,
        )
        identity = MemoryArtifactIdentity.of_payload(payload)
        document = {
            "schema": policy.artifact_schema,
            "identity": identity.document(),
            **payload,
        }
        evidence = self._documents.put("memory", document)
        commit(
            self._journal,
            MEMORY_RECORDED,
            resumed=context.resumed,
            run=self._run_id,
            episode=str(context.episode_identity),
            step=str(context.step_identity),
            round=context.round_index,
            memory={
                "identity": identity.document(),
                "owner": policy.owner,
                "key": policy.key,
                "value": payload["value"],
            },
        )
        return HandlerResult(
            MemoryArtifactV2(identity, policy.owner, payload["value"], evidence, document)
        )

