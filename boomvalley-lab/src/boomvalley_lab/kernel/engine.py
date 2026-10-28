"""Thin generic episode engine used to validate the K0 Protocol IR.

This is intentionally an in-memory architecture spike, not yet the durable
journal-2 runtime.  The important property is that orchestration belongs here:
plugins handle one typed node at a time and cannot own the protocol loop.

A journaled engine runs only under one gate-2 ExecutionAuthorizationV2
(T0-012): the semantic plan it derives must be the authorized plan, the run's
journal must re-verify that authorization before EPISODE_OPENED, and every
EpisodeIdentity binds the AuthorizationIdentity (runtime lineage follows
authorization, never the reverse).

Every execution is contained (T0-016): one ContainmentSessionV2 is armed for
the episode, the kernel seal is verified before anything is written and after
every handler, and a handler that mutates or rebinds the engine-owned world
state, memory or round values is refused.  A refusal is journaled as
EPISODE_FAILED whose reason carries the violation code
(``ContainmentViolationV2:<CODE>``).

A plan that declares actors (P04, T1-001) carries their resolved
``ActorBindingSetV1`` under the versioned ``boomvalley-lab-semantic-plan-2``
schema; handlers read actor/role/profile bindings from the engine context,
i.e. from the frozen plan, never from their own configuration.  A plan
without actors keeps the historical ``-spike-1`` document unchanged.

A plan that also declares information sources (P05, T1-002) carries its
resolved default-deny ``InformationAccessSetV1`` under
``boomvalley-lab-semantic-plan-3``: source digests and per-actor grants, never
source contents.  The context exposes that access set; contents stay with the
kernel-held source store and reach a renderer only as one actor's authorized
observation.
Another actor's output is information too (T2-001): it reaches a renderer
only as a granted ``actor_output`` source whose producer is a same-round
ancestor of the call (``bvl-information-access-3``).

A plan that declares P06 proposal contracts (T1-004) is
``boomvalley-lab-semantic-plan-4``: the resolved ``ProposalContractSetV1``
(schema, parser plugin identity, parser config and failure policy per
proposal_parse node) enters PlanIdentity because the parser can change the
decision outcome; parsed proposals never do.  plan-4 requires actors and
carries information access when declared.

A plan that declares P07 decision contracts (T1-005) is
``boomvalley-lab-semantic-plan-5``: the resolved ``DecisionContractSetV1``
(rule plugin identity, rule config, authority and its kernel-derived proposal
inputs, unresolved policy per decision node) enters PlanIdentity because
changing the rule changes the decision even on identical proposals.  plan-5
requires P06 contracts (a rule decides over typed proposals only).

A plan that pre-binds its official analysis (T1-009) is
``boomvalley-lab-semantic-plan-6``: the ``AnalysisContractV1`` (closed,
deterministic metrics over the eligible dataset units) enters PlanIdentity, so
gate-2 decides on it before any call.  No handler reads it; it is consumed only
when the run is sealed (``kernel/bound_analysis.py``).  plan-6 requires P04
actors (the analysis population is the L1 dataset of call-bound runs) and
otherwise carries the sections of the plan it extends.

A plan that binds its K0 seed tree (T1-012) is
``boomvalley-lab-semantic-plan-7``: the ``SeedDerivation`` document (tree
version x root seed) enters PlanIdentity over any actor plan (2..6), so a
changed root seed is another plan and gate, and every actor-call seed
re-derives from the frozen plan alone.  The engine refuses a seed-deriving
handler (``seed_tree``) that holds another tree than the plan binds.

A plan that freezes its World contract (T3-001, ``kernel/world.py``) is
``boomvalley-lab-semantic-plan-8``: the registered World and the schema
version of its state enter PlanIdentity over a seeded plan (7).  The contract
is the plan's one World and the initial state is a state of its schema
(BVL-WORLD-002 / -003, before anything runs).  The engine then persists the
initial state as ``world_state`` evidence before EPISODE_OPENED, which names
it (``initial_state``), and every state identity it journals is the versioned
one; a plan without a contract keeps identity-1.

A plan that declares human actors (P17, T5-001, ``kernel/human.py``) is
``boomvalley-lab-semantic-plan-9``: the ``HumanActorContractSetV1`` (channel,
response form, least provenance, consent terms and privacy per human actor)
enters PlanIdentity over a seeded plan (7) or a World plan (8).  Exactly the
contracted actors are on a human profile; an actor that states the human model
without a contract is refused in every plan (BVL-HUMAN-003).

A plan that declares tool actors (P17, T5-003, ``kernel/tool.py``) is
``boomvalley-lab-semantic-plan-10``: the ``ToolActorContractSetV1`` (tool,
effect, operation, resource and the types of arguments and result per tool
actor) enters PlanIdentity over a seeded plan (7, 8 or 9).  Exactly the
contracted actors are on a tool profile; an actor that states the tool model
without a contract is refused in every plan (BVL-TOOL-003).  A contract that
declares where its arguments come from (T5-007, ``argument_selection``) selects
only sources its actor is granted (BVL-TOOL-001), and its actor is called by
the engine like every actor: the actor-call handler answers the step through
the journaled tool call (``kernel/tool_actor_call.py``).  A tool outcome that
is not proven (``ToolCallRefusedError``) is not an outcome of the episode:
nothing is journaled for it and the run stays interrupted.

A human actor call may wait (P17, T5-002, ``kernel/waiting.py``): the request
is with a person and no answer exists yet.  ``HumanResponsePending`` is not an
outcome of the episode - nothing is journaled for it, the episode stays open
and the run is WAITING - and the episode is continued by ``resume`` like any
interrupted one, every boundary committed once.

Execution is dependency-ready (T2-002, ``kernel/readiness.py``): a journaled
engine admits a step only when every same-round dependency carries its
durable commit event in journal-2 and the held value is the committed one
(BVL-DEP-001 / -002, journaled as EPISODE_FAILED before the step's
STEP_READY).  A downstream actor call is never intended before an upstream
actor's call is custody-accepted and its proposal committed.

Schedule order is not causal order (T2-004, ``kernel/schedule.py``): every
EPISODE_OPENED names the episode's ProtocolDagIdentity (the IR's intra-episode
causal order) and its place in the run's ExperimentScheduleV1 (the
experimental schedule order, default: the one episode).  An episode opens only
after exactly its schedule predecessors (BVL-SCHED-001); neither order enters
EpisodeIdentity or StepIdentity.

An interrupted episode is resumed, never replayed blindly (T2-006,
``kernel/replay.py``): with ``resume=True`` the engine continues the episode
the journal already opened.  It walks the same IR from round 1, and every
engine event, call, World transition and step commit is committed once - a
recorded one is matched, not appended again - so no dependency output is
fabricated or duplicated.  A ``ResumeRefusedError`` (BVL-RES-*) is not a
scientific outcome and is never journaled as EPISODE_FAILED.  Nor is a
``WorldCustodyRefusedError`` (T3-007, BVL-WORLD-011 / -012): a World transition
whose outcome is not established, or whose continuation would confirm a second
one, leaves the run interrupted and nothing written.

Repetition is the plan's, not the engine's (P16, T4-001, ``kernel/rounds.py``):
under a ``bvl-protocol-ir-2`` round contract the engine opens every round on an
identified pre-state (ROUND_OPENED: RoundIdentity = episode x round x
pre-state), and after ROUND_COMPLETED it evaluates the contract's registered
termination rule and journals the verdict (TERMINATION_EVALUATED).  The next
round exists only because that verdict is CONTINUE; no handler can terminate
such an episode (BVL-ROUND-001) and no round is opened past the safety bound
(BVL-ROUND-010).  A plan without a contract keeps the historical bare bound.

Episode isolation is the default, and what crosses an episode is declared
(P16 13.4 / 13.5, T4-004, ``kernel/memory.py``): every episode opens on the
plan's initial World state, and it holds memory of an earlier episode only
under a ``memory_update`` node's declared carry - the run's schedule orders the
carry's episodes as declared (BVL-ROUND-011, before anything is written), and
the engine rebuilds the carried artifacts from the run's own committed
evidence, never from a process's memory.  A declared regime event of the
plan's World is read from the committed transition; a node declaring
``regime_change: reset`` holds no artifact recorded before it from the next
round on.

The state chain is the engine's (P16 4, T4-005, ``kernel/state_chain.py``):
round t+1 opens on exactly the state round t closed on, and that state moves
only in a committed World transition.  A step of any other kind that returns a
World state fails the episode (BVL-ROUND-005) before a round can close on it;
the verifiers re-walk the chain from the run's evidence.

Where the rule is evaluated is the plan's too (P16 13.6, T4-002): a contract
that declares its timing is evaluated before the round opens
(``before_observation``), after its last decision and before the World
(``after_decision``), after its last World transition
(``after_world_transition``) or after ROUND_COMPLETED (``after_round_close``),
on the state the episode is in at exactly that point; the verdict names the
point and that state's identity.  A TERMINATE ends the episode there: the
round is not opened, or is cut and closed on its current state.  When round
``max_rounds`` closes without one, the engine journals the safety-bound verdict
itself.  A state rule that cannot be evaluated fails the episode
(BVL-ROUND-004).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import DeclarationError, ExecutionError
from boomvalley_lab.kernel.actors import ActorBindingSetV1
from boomvalley_lab.kernel.authorization import (
    ExecutionAuthorizationV2,
    require_run_authorization_v2,
)
from boomvalley_lab.kernel.bound_analysis import AnalysisContractV1
from boomvalley_lab.kernel.containment import (
    ContainmentSessionV2,
    ContainmentViolationV2,
    state_fingerprint,
)
from boomvalley_lab.kernel.decisions import (
    AUTHORITY_SET_INVALID,
    DecisionContractSetV1,
    DecisionError,
)
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentRefV2,
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.human import (
    HumanActorContractSetV1,
    HumanError,
    require_no_uncontracted_human,
)
from boomvalley_lab.kernel.identity import (
    AuthorizationIdentity,
    EpisodeIdentity,
    MemoryArtifactIdentity,
    PlanIdentity,
    StepIdentity,
)
from boomvalley_lab.kernel.information import (
    ACCESS_RULE_AMBIGUOUS,
    InformationAccessSetV1,
    InformationError,
)
from boomvalley_lab.kernel.journal2 import (
    EPISODE_COMPLETED,
    EPISODE_FAILED,
    EPISODE_OPENED,
    MEMORY_RECORDED,
    ROUND_COMPLETED,
    ROUND_OPENED,
    STEP_READY,
    TERMINATION_EVALUATED,
    WORLD_APPLIED,
    Journal2,
    held_run,
)
from boomvalley_lab.kernel.memory import (
    SCOPE_CROSS_EPISODE,
    EpisodeMemoryV1,
    MemoryPolicyV1,
    held,
    require_carry_schedule,
    require_memory_lifecycle,
)
from boomvalley_lab.kernel.proposals import (
    PROPOSAL_SCHEMA_UNKNOWN,
    ProposalContractSetV1,
    ProposalError,
)
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR, ProtocolNode
from boomvalley_lab.kernel.readiness import (
    DependencyNotReadyError,
    require_dependencies_ready,
)
from boomvalley_lab.kernel.replay import RESUME_EPISODE_CLOSED, ResumeRefusedError, commit
from boomvalley_lab.kernel.rounds import (
    AFTER_ROUND_CLOSE,
    BEFORE_OBSERVATION,
    CROSS_EPISODE_STATE_UNDECLARED,
    HIDDEN_ACTOR_MEMORY,
    ROUND_PLAN_INVALID,
    SAFETY_BOUND,
    STATE_CHAIN_MISMATCH,
    TERMINATE,
    RoundError,
    round_identity,
)
from boomvalley_lab.kernel.schedule import ExperimentScheduleV1, protocol_dag_identity
from boomvalley_lab.kernel.seed import SeedDerivation
from boomvalley_lab.kernel.tool import (
    ToolActorContractSetV1,
    ToolError,
    require_no_uncontracted_tool,
)
from boomvalley_lab.kernel.tool_actor_call import ToolCallRefusedError
from boomvalley_lab.kernel.waiting import HumanDeskRefusedError, HumanResponsePending
from boomvalley_lab.kernel.world import (
    WORLD_IDENTITY_MISMATCH,
    WORLD_NOT_REGISTERED,
    WorldContractV1,
    WorldError,
    state_evidence_document,
    state_identity,
)
from boomvalley_lab.kernel.world_executor import WorldCustodyRefusedError


@dataclass(frozen=True)
class HandlerResult:
    value: Any = None
    world_state: Mapping[str, Any] | None = None
    memory_updates: Mapping[str, Any] = field(default_factory=dict)
    terminate: bool = False


@dataclass(frozen=True)
class TraceEntry:
    round_index: int
    node_id: str
    kind: str
    step_identity: str
    value: Any


@dataclass
class EngineContext:
    experiment_id: str
    plan_identity: PlanIdentity
    episode_identity: EpisodeIdentity
    round_index: int
    world_state: Mapping[str, Any]
    memory: dict[str, Any]
    current_round: dict[str, Any]
    step_identity: StepIdentity | None = None
    actors: ActorBindingSetV1 | None = None
    information: InformationAccessSetV1 | None = None
    proposals: ProposalContractSetV1 | None = None
    decisions: DecisionContractSetV1 | None = None
    # engine-owned: this episode continues an interrupted one (T2-006)
    resumed: bool = False
    # the plan's frozen World contract, if it declares one (T3-001)
    world: WorldContractV1 | None = None
    # engine-owned Memory Artifact ledger of the episode (T4-003): memory_update
    # node -> its committed artifact documents; the request pipeline derives
    # granted memory_artifact sources from it, no plugin receives it
    memory_artifacts: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    # engine-owned: the episode's key in the run's schedule (T4-004: a Memory
    # Artifact names the episode that recorded it); no renderer receives it
    episode_key: str = ""
    # the plan's frozen human actor contracts, if it declares any (T5-001)
    humans: HumanActorContractSetV1 | None = None
    # the plan's frozen tool actor contracts, if it declares any (T5-007)
    tools: ToolActorContractSetV1 | None = None

    def dependency(self, node_id: str) -> Any:
        if node_id not in self.current_round:
            raise ExecutionError(f"dependency {node_id!r} is not available")
        return self.current_round[node_id]


Handler = Callable[[ProtocolNode, EngineContext], HandlerResult]


def _episode_document(name: str) -> dict[str, str]:
    """journal-2's ``episode:sha256:...`` -> the EpisodeIdentity document."""

    kind, _, digest = name.partition(":")
    return {"kind": kind, "digest": digest}

SEMANTIC_PLAN_SCHEMA_V1 = "boomvalley-lab-semantic-plan-spike-1"
SEMANTIC_PLAN_SCHEMA_V2 = "boomvalley-lab-semantic-plan-2"
SEMANTIC_PLAN_SCHEMA_V3 = "boomvalley-lab-semantic-plan-3"
SEMANTIC_PLAN_SCHEMA_V4 = "boomvalley-lab-semantic-plan-4"
SEMANTIC_PLAN_SCHEMA_V5 = "boomvalley-lab-semantic-plan-5"
SEMANTIC_PLAN_SCHEMA_V6 = "boomvalley-lab-semantic-plan-6"
SEMANTIC_PLAN_SCHEMA_V7 = "boomvalley-lab-semantic-plan-7"
SEMANTIC_PLAN_SCHEMA_V8 = "boomvalley-lab-semantic-plan-8"
SEMANTIC_PLAN_SCHEMA_V9 = "boomvalley-lab-semantic-plan-9"
SEMANTIC_PLAN_SCHEMA_V10 = "boomvalley-lab-semantic-plan-10"


def _step_snapshot(
    context: EngineContext,
    state: Mapping[str, Any],
    memory: Mapping[str, Any],
    current: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Engine-owned state a step's plugins must leave untouched (T0-016)."""

    return (
        context.world_state is state,
        context.memory is memory,
        context.current_round is current,
        context.experiment_id,
        context.plan_identity,
        context.episode_identity,
        context.round_index,
        context.step_identity,
        context.actors,
        context.information,
        context.proposals,
        context.decisions,
        context.resumed,
        context.world,
        context.episode_key,
        context.humans,
        context.tools,
        state_fingerprint(state, memory, current),
        id(context.memory_artifacts),
        tuple(
            (node_id, tuple(str(artifact.get("identity")) for artifact in artifacts))
            for node_id, artifacts in sorted(context.memory_artifacts.items())
        ),
    )


def semantic_plan_v2(
    *,
    experiment_id: str,
    protocol: ProtocolIR,
    initial_world_state: Mapping[str, Any],
    initial_memory: Mapping[str, Any] | None = None,
    actors: ActorBindingSetV1 | None = None,
    information: InformationAccessSetV1 | None = None,
    proposals: ProposalContractSetV1 | None = None,
    decisions: DecisionContractSetV1 | None = None,
    analysis: AnalysisContractV1 | None = None,
    seeds: SeedDerivation | None = None,
    world: WorldContractV1 | None = None,
    humans: HumanActorContractSetV1 | None = None,
    tools: ToolActorContractSetV1 | None = None,
) -> tuple[dict[str, Any], PlanIdentity]:
    """The normalized plan document and PlanIdentity the engine will execute.

    Exposed so gate-2 can decide on exactly the plan before execution.
    """

    if information is not None and actors is None:
        raise InformationError(
            ACCESS_RULE_AMBIGUOUS, "information access is resolved per plan actor"
        )
    if proposals is not None and actors is None:
        raise ProposalError(
            PROPOSAL_SCHEMA_UNKNOWN, "proposal contracts bind the parse nodes of an actor plan"
        )
    if decisions is not None and proposals is None:
        raise DecisionError(
            AUTHORITY_SET_INVALID, "decision contracts decide over P06 proposal contracts"
        )
    if analysis is not None and actors is None:
        raise DeclarationError(
            "BVL-ANA-001 analysis contract is invalid: an analysis is bound over the "
            "L1 dataset units of a plan with P04 actors"
        )
    if analysis is not None and proposals is not None:
        # SV-04: a metric reads a field, of its own type, that a decision can request
        analysis.require_action_fields(
            [contract.schema.fields for contract in proposals.contracts.values()]
        )
    if seeds is not None and actors is None:
        raise DeclarationError(
            "a seed tree is bound into a plan with P04 actors (the seeds of its actor calls)"
        )
    # T5-001: a person is asked only under a contract, in a seeded plan
    if humans is not None:
        if seeds is None:
            raise DeclarationError(
                "human actor contracts are bound into a plan with a seed tree (plan-7 or -8)"
            )
        humans.require_actors(actors)
    else:
        require_no_uncontracted_human(actors, None)
    # T5-003: a tool is called only under a contract, in a seeded plan
    if tools is not None:
        if seeds is None:
            raise DeclarationError(
                "tool actor contracts are bound into a plan with a seed tree (plan-7, -8 "
                "or -9)"
            )
        tools.require_actors(actors)
        # T5-007: an argument is selected only from a source its actor is granted
        tools.require_granted(None if information is None else information.granted)
    else:
        require_no_uncontracted_tool(actors, None)
    if protocol.round is not None:
        # T4-002: a state rule terminates on admitted World states only
        protocol.round.require_plan(
            initial_state=initial_world_state, world_contract=world is not None
        )
    # T4-003: memory is declared end to end (lifecycle node -> P05 source);
    # T4-004: a regime-change reset names a World that declares its regime
    require_memory_lifecycle(
        protocol,
        actors=actors,
        information=information,
        initial_memory=initial_memory,
        world=world,
    )
    if world is not None:
        require_world_contract(protocol, world, initial_world_state, seeds)
    if tools is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V10
    elif humans is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V9
    elif world is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V8
    elif seeds is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V7
    elif analysis is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V6
    elif decisions is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V5
    elif proposals is not None:
        schema = SEMANTIC_PLAN_SCHEMA_V4
    elif actors is None:
        schema = SEMANTIC_PLAN_SCHEMA_V1
    elif information is None:
        schema = SEMANTIC_PLAN_SCHEMA_V2
    else:
        schema = SEMANTIC_PLAN_SCHEMA_V3
    document: dict[str, Any] = {
        "schema": schema,
        "experiment_id": experiment_id,
        "protocol": protocol.document(),
        "initial_world_state": dict(initial_world_state),
        "initial_memory": dict(initial_memory or {}),
    }
    if actors is not None:
        require_planned_actors(protocol, actors)
        document["actors"] = actors.document()
    if information is not None:
        information.require_actors(actors)
        information.require_protocol(protocol)  # P13 visibility (T2-001)
        document["information"] = information.document()
    if proposals is not None:
        proposals.require_protocol(protocol)
        document["proposals"] = proposals.document()
    if decisions is not None:
        decisions.require_protocol(protocol, actors, proposals)
        document["decisions"] = decisions.document()
    if analysis is not None:
        document["analysis"] = analysis.document()
    if seeds is not None:
        document["seed"] = seeds.document()
    if world is not None:
        document["world"] = world.document()
    if humans is not None:
        document["humans"] = humans.document()
    if tools is not None:
        document["tools"] = tools.document()
    return document, PlanIdentity.of_payload(document)


def require_world_contract(
    protocol: ProtocolIR,
    world: WorldContractV1,
    initial_world_state: Mapping[str, Any],
    seeds: SeedDerivation | None,
) -> None:
    """A plan-8 World contract is the one World of the plan, on a valid initial state.

    Refused before anything runs: a contract over no seed tree, a contract no
    ``world_transition`` applies, a transition naming another World or
    applying anything but the one decision it depends on (BVL-WORLD-002) and an
    initial state outside the schema (BVL-WORLD-003).
    """

    if seeds is None:
        raise DeclarationError(
            "a World contract is bound into a plan with a seed tree (the seeds of its "
            "transitions)"
        )
    named = [
        node for node in protocol.nodes if node.kind is NodeKind.WORLD_TRANSITION
    ]
    if not named:
        raise WorldError(
            WORLD_NOT_REGISTERED,
            f"the plan declares World {world.plugin!r} but no world_transition applies it",
        )
    for node in named:
        if node.config.get("world") != world.plugin:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"world_transition {node.node_id!r} names World {node.config.get('world')!r}, "
                f"the plan's World contract is {world.plugin!r}",
            )
        # T3-GATE: the Decision -> World edge is the plan's, not found at run time
        kinds = [protocol.node(dependency).kind for dependency in node.depends_on]
        if kinds != [NodeKind.DECISION]:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"world_transition {node.node_id!r} depends on "
                f"{[kind.value for kind in kinds]}: under a World contract a transition "
                "applies exactly one decision node",
            )
    world.require_initial_state(initial_world_state)


def require_planned_actors(protocol: ProtocolIR, actors: ActorBindingSetV1) -> None:
    """Every actor_call names a plan actor (BVL-ACTOR-009), before anything runs."""

    for node in protocol.nodes:
        if node.kind is NodeKind.ACTOR_CALL:
            actors.binding(node.config.get("actor"))


@dataclass(frozen=True)
class EpisodeResult:
    plan_identity: PlanIdentity
    plan_document: Mapping[str, Any]
    plan_evidence: EvidenceDocumentRefV2 | None
    episode_identity: EpisodeIdentity
    rounds_executed: int
    world_state: Mapping[str, Any]
    memory: Mapping[str, Any]
    trace: tuple[TraceEntry, ...]
    authorization: AuthorizationIdentity | None = None


class GenericEpisodeEngine:
    """Execute one finite ProtocolIR with engine-owned ordering."""

    def __init__(
        self,
        handlers: Mapping[NodeKind, Handler],
        *,
        journal: Journal2 | None = None,
        documents: EvidenceDocumentStoreV2 | None = None,
        run_id: str | None = None,
        authorization: ExecutionAuthorizationV2 | None = None,
        denied_sources: Sequence[Path] = (),
    ) -> None:
        if (journal is None) != (run_id is None):
            raise ValueError("journal and run_id are supplied together")
        if journal is not None and authorization is None:
            raise ValueError("a journaled engine runs only under a gate-2 authorization")
        if authorization is not None and authorization.run_id != run_id:
            raise ValueError("the gate-2 authorization belongs to another run")
        self._authorization = authorization
        self._handlers = dict(handlers)
        self._journal = journal
        self._documents = documents
        self._run_id = run_id
        self._denied_sources = tuple(Path(source) for source in denied_sources)

    def execute(
        self,
        *,
        experiment_id: str,
        episode_key: str,
        protocol: ProtocolIR,
        initial_world_state: Mapping[str, Any],
        initial_memory: Mapping[str, Any] | None = None,
        actors: ActorBindingSetV1 | None = None,
        information: InformationAccessSetV1 | None = None,
        proposals: ProposalContractSetV1 | None = None,
        decisions: DecisionContractSetV1 | None = None,
        analysis: AnalysisContractV1 | None = None,
        seeds: SeedDerivation | None = None,
        schedule: ExperimentScheduleV1 | None = None,
        resume: bool = False,
        world: WorldContractV1 | None = None,
        humans: HumanActorContractSetV1 | None = None,
        tools: ToolActorContractSetV1 | None = None,
    ) -> EpisodeResult:
        if resume and self._journal is None:
            raise ValueError("only a journaled episode is resumed")
        denied = list(self._denied_sources)
        run = None
        if self._journal is not None:
            run = self._journal.path.parent
            denied.append(run)  # the run's own evidence
        # this process is the run's one writer for the whole episode
        with held_run(run) if run is not None else nullcontext(), ContainmentSessionV2(
            denied_sources=denied
        ) as session:
            return self._execute(
                session,
                experiment_id=experiment_id,
                episode_key=episode_key,
                protocol=protocol,
                initial_world_state=initial_world_state,
                initial_memory=initial_memory,
                actors=actors,
                information=information,
                proposals=proposals,
                decisions=decisions,
                analysis=analysis,
                seeds=seeds,
                schedule=schedule or ExperimentScheduleV1((episode_key,)),
                resume=resume,
                world=world,
                humans=humans,
                tools=tools,
            )

    def _execute(
        self,
        session: ContainmentSessionV2,
        *,
        experiment_id: str,
        episode_key: str,
        protocol: ProtocolIR,
        initial_world_state: Mapping[str, Any],
        initial_memory: Mapping[str, Any] | None,
        actors: ActorBindingSetV1 | None,
        information: InformationAccessSetV1 | None,
        proposals: ProposalContractSetV1 | None,
        decisions: DecisionContractSetV1 | None,
        analysis: AnalysisContractV1 | None,
        seeds: SeedDerivation | None,
        schedule: ExperimentScheduleV1,
        resume: bool,
        world: WorldContractV1 | None,
        humans: HumanActorContractSetV1 | None,
        tools: ToolActorContractSetV1 | None,
    ) -> EpisodeResult:
        if seeds is not None:
            for kind, handler in self._handlers.items():
                tree = getattr(handler, "seed_tree", None)
                if tree is not None and tree != seeds:
                    raise ExecutionError(
                        f"the {kind.value} handler derives seeds from another tree than the "
                        "plan binds"
                    )
        plan_document, plan = semantic_plan_v2(
            experiment_id=experiment_id,
            protocol=protocol,
            initial_world_state=initial_world_state,
            initial_memory=initial_memory,
            actors=actors,
            information=information,
            proposals=proposals,
            decisions=decisions,
            analysis=analysis,
            seeds=seeds,
            world=world,
            humans=humans,
            tools=tools,
        )
        state_schema = None if world is None else world.state_schema.ref
        authorization = self._authorize(plan)
        opened_at = schedule.opened(episode_key)  # BVL-SCHED-001 before any write
        # T4-003: under a memory lifecycle the engine holds artifacts, no memory dict
        policies = require_memory_lifecycle(
            protocol,
            actors=actors,
            information=information,
            initial_memory=initial_memory,
            world=world,
        )
        # T4-004: a declared carry is executed in its declared episode order
        require_carry_schedule(
            policies, schedule.episodes, journaled=self._journal is not None
        )
        episode = EpisodeIdentity.of_payload(
            {
                "plan": plan.document(),
                "authorization": (
                    authorization.document() if authorization is not None else None
                ),
                "episode_key": episode_key,
            }
        )
        resumed = resume and self._resumes(episode)
        if self._journal is not None and not resumed:
            schedule.require_next(
                episode_key,
                [r for r in self._journal.read() if r["event"] == EPISODE_OPENED],
            )
        plan_evidence = (
            self._documents.put(
                "plan",
                {
                    "schema": "boomvalley-lab-plan-evidence-1",
                    "identity": plan.document(),
                    "plan": plan_document,
                },
            )
            if self._documents is not None
            else None
        )
        state = dict(initial_world_state)
        memory = dict(initial_memory or {})
        ledger: Mapping[str, tuple[Mapping[str, Any], ...]] = MappingProxyType({})
        # T4-004: what earlier episodes of the run committed under a declared
        # carry, this episode's own artifacts and the rounds its regime changed in
        carried = self._carried(policies, episode, world)
        own: dict[str, list[Mapping[str, Any]]] = {node_id: [] for node_id in policies}
        regime_rounds: list[int] = []
        trace: list[TraceEntry] = []
        rounds_executed = 0

        if self._journal is not None:
            opened: dict[str, Any] = {}
            if world is not None:
                # T3-001: the versioned initial state is evidence before the
                # episode opens on it (its identity is every first pre-state's)
                opened["initial_state"] = {
                    "identity": state_identity(state, state_schema).document(),
                    "evidence": self._documents.put(
                        "world_state", state_evidence_document(state, state_schema)
                    ).document(),
                }
            # plan + episode_key let a package verifier recompute the
            # EpisodeIdentity from the run's authorization (T0-014).
            commit(
                self._journal,
                EPISODE_OPENED,
                resumed=resumed,
                run=self._run_id,
                episode=str(episode),
                episode_key=episode_key,
                plan=plan.document(),
                protocol_dag=protocol_dag_identity(protocol).document(),
                schedule=opened_at,
                **opened,
            )

        contract = protocol.round
        timing = None if contract is None else contract.timing
        anchor = protocol.termination_anchor
        last_step: tuple[str, int] | None = None

        def terminates(point: str) -> bool:
            """Evaluate the timed contract at *point* of the current round (T4-002)."""

            try:
                verdict = contract.evaluate_at(
                    round_index,
                    observed_state=state_identity(state, state_schema).document(),
                    state=state,
                    point=point,
                )
            except RoundError as error:
                if self._journal is not None and last_step is not None:
                    self._journal.append_event(
                        EPISODE_FAILED,
                        run=self._run_id,
                        episode=str(episode),
                        step=last_step[0],
                        round=last_step[1],
                        reason=f"{type(error).__name__}:{error.code}",
                    )
                raise
            if self._journal is not None:
                commit(
                    self._journal,
                    TERMINATION_EVALUATED,
                    resumed=resumed,
                    run=self._run_id,
                    episode=str(episode),
                    round=round_index,
                    point=point,
                    terminate=verdict["verdict"] == TERMINATE,
                    termination=verdict,
                )
            return verdict["verdict"] == TERMINATE

        round_index = 0
        while True:
            round_index += 1
            if timing == BEFORE_OBSERVATION and terminates(BEFORE_OBSERVATION):
                break  # the round never exists
            cut = False
            if contract is not None and self._journal is not None:
                # T4-001: the round is identified on its pre-state before any step
                pre_state = state_identity(state, state_schema).document()
                commit(
                    self._journal,
                    ROUND_OPENED,
                    resumed=resumed,
                    run=self._run_id,
                    episode=str(episode),
                    round=round_index,
                    round_identity=round_identity(episode, round_index, pre_state).document(),
                    pre_state=pre_state,
                )
            if policies:
                ledger = MappingProxyType(
                    {
                        node_id: tuple(
                            held(
                                policy,
                                (
                                    *carried.get(node_id, ()),
                                    EpisodeMemoryV1(
                                        episode_key,
                                        episode.document(),
                                        tuple(own[node_id]),
                                        tuple(regime_rounds),
                                    ),
                                ),
                                round_index,
                            )
                        )
                        for node_id, policy in policies.items()
                    }
                )
            current: dict[str, Any] = {}
            context = EngineContext(
                experiment_id=experiment_id,
                plan_identity=plan,
                episode_identity=episode,
                round_index=round_index,
                world_state=state,
                memory=memory,
                current_round=current,
                actors=actors,
                information=information,
                proposals=proposals,
                decisions=decisions,
                resumed=resumed,
                world=world,
                memory_artifacts=ledger,
                episode_key=episode_key,
                humans=humans,
                tools=tools,
            )

            for node_id in protocol.topological_order():
                node = protocol.node(node_id)
                missing = [dep for dep in node.depends_on if dep not in current]
                if missing:
                    raise ExecutionError(
                        f"step {node_id!r} is not ready; dependencies {missing}"
                    )
                handler = self._handlers.get(node.kind)
                if handler is None:
                    raise ExecutionError(f"no handler registered for {node.kind.value}")

                def step_of(planned: ProtocolNode, round_index: int = round_index) -> StepIdentity:
                    return StepIdentity.of_payload(
                        {
                            "episode": episode.document(),
                            "round": round_index,
                            "node": planned.node_id,
                            "kind": planned.kind.value,
                        }
                    )

                step = step_of(node)
                if self._journal is not None:
                    try:
                        require_dependencies_ready(
                            node=node,
                            nodes=protocol.node,
                            records=self._journal.of_episode(str(episode)),
                            episode=str(episode),
                            round_index=round_index,
                            step_of=lambda planned: str(step_of(planned)),
                            held=current,
                        )
                    except DependencyNotReadyError as error:
                        self._journal.append_event(
                            EPISODE_FAILED,
                            run=self._run_id,
                            episode=str(episode),
                            step=str(step),
                            round=round_index,
                            reason=f"{type(error).__name__}:{error.code}",
                        )
                        raise
                context.step_identity = step
                if self._journal is not None:
                    commit(
                        self._journal,
                        STEP_READY,
                        resumed=resumed,
                        run=self._run_id,
                        episode=str(episode),
                        step=str(step),
                        round=round_index,
                    )
                # engine-owned state is immutable while the step's plugins run;
                # the session re-checks it at every plugin-window exit.
                session.watch(
                    partial(_step_snapshot, context, state, memory, current),
                    f"step {node.node_id!r} round {round_index}",
                )
                try:
                    try:
                        result = handler(node, context)
                        session.check()
                    finally:
                        session.watch(None, "")
                except Exception as error:
                    # a refused resume is not a scientific outcome: not journaled; nor
                    # is a World transition the boundary may not continue (T3-007),
                    # nor a person who has not answered yet or a desk that
                    # contradicts the run (T5-002), nor a tool outcome that is
                    # not proven (T5-007)
                    if self._journal is not None and not isinstance(
                        error,
                        (ResumeRefusedError, WorldCustodyRefusedError, HumanResponsePending,
                         HumanDeskRefusedError, ToolCallRefusedError),
                    ):
                        reason = type(error).__name__
                        if isinstance(
                            error,
                            (ContainmentViolationV2, ProposalError, DecisionError, HumanError,
                             ToolError),
                        ):
                            reason = f"{reason}:{error.code}"
                        self._journal.append_event(
                            EPISODE_FAILED,
                            run=self._run_id,
                            episode=str(episode),
                            step=str(step),
                            round=round_index,
                            reason=reason,
                        )
                    raise
                if not isinstance(result, HandlerResult):
                    raise ExecutionError(
                        f"handler for {node.kind.value} did not return HandlerResult"
                    )

                if policies and result.memory_updates:
                    # memory exists only as a Memory Artifact (P16 13.3)
                    hidden = RoundError(
                        HIDDEN_ACTOR_MEMORY,
                        f"the {node.kind.value} handler of {node.node_id!r} returned memory "
                        f"{sorted(result.memory_updates)} outside the plan's memory lifecycle",
                    )
                    if self._journal is not None:
                        self._journal.append_event(
                            EPISODE_FAILED,
                            run=self._run_id,
                            episode=str(episode),
                            step=str(step),
                            round=round_index,
                            reason=f"{type(hidden).__name__}:{hidden.code}",
                        )
                    raise hidden
                if result.world_state is not None and node.kind is not NodeKind.WORLD_TRANSITION:
                    # T4-005: World(t) -> World(t+1) is a World transition's and
                    # nothing else's; any other step would break the state chain
                    broken = RoundError(
                        STATE_CHAIN_MISMATCH,
                        f"the {node.kind.value} handler of {node.node_id!r} returned a World "
                        "state: only a world_transition step moves the episode's state",
                    )
                    if self._journal is not None:
                        self._journal.append_event(
                            EPISODE_FAILED,
                            run=self._run_id,
                            episode=str(episode),
                            step=str(step),
                            round=round_index,
                            reason=f"{type(broken).__name__}:{broken.code}",
                        )
                    raise broken
                if result.world_state is not None:
                    state = dict(result.world_state)
                    context.world_state = state
                if result.memory_updates:
                    memory.update(dict(result.memory_updates))
                    context.memory = memory
                if node.node_id in policies:
                    artifact = getattr(result.value, "document", None)
                    if not isinstance(artifact, Mapping):
                        raise ExecutionError(
                            f"memory_update {node.node_id!r} produced no Memory Artifact "
                            "under the plan's memory lifecycle"
                        )
                    own[node.node_id].append(artifact)
                    ledger = MappingProxyType(
                        {**ledger, node.node_id: (*ledger.get(node.node_id, ()), artifact)}
                    )
                    context.memory_artifacts = ledger
                if policies and world is not None and node.kind is NodeKind.WORLD_TRANSITION:
                    # T4-004: a declared regime event, read from the committed transition
                    stated = getattr(getattr(result.value, "transition", None),
                                     "exogenous_events", ())
                    if round_index not in regime_rounds and world.progression.regime_changes(
                        {"exogenous_events": [dict(event) for event in stated]}
                    ):
                        regime_rounds.append(round_index)

                last_step = (str(step), round_index)
                current[node.node_id] = result.value
                trace.append(
                    TraceEntry(
                        round_index=round_index,
                        node_id=node.node_id,
                        kind=node.kind.value,
                        step_identity=str(step),
                        value=result.value,
                    )
                )
                if result.terminate and contract is not None:
                    # termination is the round contract's verdict, never a plugin's
                    refused = RoundError(
                        ROUND_PLAN_INVALID,
                        f"the {node.kind.value} handler of {node.node_id!r} terminated an "
                        "episode whose round contract owns termination",
                    )
                    if self._journal is not None:
                        self._journal.append_event(
                            EPISODE_FAILED,
                            run=self._run_id,
                            episode=str(episode),
                            step=str(step),
                            round=round_index,
                            reason=f"{type(refused).__name__}:{refused.code}",
                        )
                    raise refused
                if result.terminate:
                    rounds_executed = round_index
                    if self._journal is not None:
                        commit(
                            self._journal,
                            ROUND_COMPLETED,
                            resumed=resumed,
                            run=self._run_id,
                            episode=str(episode),
                            round=round_index,
                            post_state=state_identity(state, state_schema).document(),
                        )
                        commit(
                            self._journal,
                            EPISODE_COMPLETED,
                            resumed=resumed,
                            run=self._run_id,
                            episode=str(episode),
                            rounds=rounds_executed,
                        )
                    return EpisodeResult(
                        plan,
                        plan_document,
                        plan_evidence,
                        episode,
                        rounds_executed,
                        state,
                        dict(memory),
                        tuple(trace),
                        authorization,
                    )
                if node.node_id == anchor and terminates(timing):
                    cut = True  # the round ends at its timing point
                    break

            rounds_executed = round_index
            if self._journal is not None:
                commit(
                    self._journal,
                    ROUND_COMPLETED,
                    resumed=resumed,
                    run=self._run_id,
                    episode=str(episode),
                    round=round_index,
                    post_state=state_identity(state, state_schema).document(),
                )
            if contract is None:
                if round_index == protocol.rounds:
                    break
                continue
            if timing is not None:
                if cut or (timing == AFTER_ROUND_CLOSE and terminates(AFTER_ROUND_CLOSE)):
                    break
                if round_index == contract.max_rounds:
                    terminates(SAFETY_BOUND)  # the bound ends the episode as evidence
                    break
                continue
            # the plan's registered rule decides whether another round exists;
            # past the safety bound it refuses (BVL-ROUND-010)
            verdict = contract.evaluate(round_index)
            if self._journal is not None:
                commit(
                    self._journal,
                    TERMINATION_EVALUATED,
                    resumed=resumed,
                    run=self._run_id,
                    episode=str(episode),
                    round=round_index,
                    terminate=verdict["verdict"] == TERMINATE,
                    termination=verdict,
                )
            if verdict["verdict"] == TERMINATE:
                break

        if self._journal is not None:
            commit(
                self._journal,
                EPISODE_COMPLETED,
                resumed=resumed,
                run=self._run_id,
                episode=str(episode),
                rounds=rounds_executed,
            )
        return EpisodeResult(
            plan,
            plan_document,
            plan_evidence,
            episode,
            rounds_executed,
            state,
            dict(memory),
            tuple(trace),
            authorization,
        )

    def _carried(
        self,
        policies: Mapping[str, MemoryPolicyV1],
        episode: EpisodeIdentity,
        world: WorldContractV1 | None,
    ) -> dict[str, tuple[EpisodeMemoryV1, ...]]:
        """memory_update node -> the committed memory of the run's earlier episodes.

        Read from journal-2 and the evidence store only (T4-004): an artifact
        that is not the committed one, byte for byte under its identity, is
        undeclared cross-episode state (BVL-ROUND-011) and nothing opens.
        """

        if self._journal is None or not any(
            policy.scope == SCOPE_CROSS_EPISODE for policy in policies.values()
        ):
            return {}
        slots = {(policy.owner, policy.key): node_id for node_id, policy in policies.items()}
        stored = {
            canonical_json(document.get("identity")): document
            for document in self._documents.members("memory")
            if isinstance(document, Mapping)
        }
        earlier: list[tuple[str, str]] = []
        artifacts: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        regimes: dict[str, list[int]] = {}
        for record in self._journal.read():
            name = record.get("episode")
            if name == str(episode):
                if record["event"] == EPISODE_OPENED:
                    break  # a resumed episode: only what opened before it is earlier
                continue
            if record["event"] == EPISODE_OPENED:
                earlier.append((name, record["episode_key"]))
            elif record["event"] == MEMORY_RECORDED:
                committed = record["memory"]
                document = stored.get(canonical_json(committed.get("identity")))
                payload = {
                    key: value
                    for key, value in (document or {}).items()
                    if key not in ("schema", "identity")
                }
                node_id = slots.get((committed.get("owner"), committed.get("key")))
                if (
                    document is None
                    or node_id is None
                    or MemoryArtifactIdentity.of_payload(payload).document()
                    != document["identity"]
                    or document.get("episode") != _episode_document(name)
                ):
                    raise RoundError(
                        CROSS_EPISODE_STATE_UNDECLARED,
                        f"journal-2 #{record['sequence']} commits memory "
                        f"{committed.get('identity')} whose evidence is not the committed "
                        "Memory Artifact: nothing is carried from it",
                    )
                artifacts.setdefault((name, node_id), []).append(document)
            elif record["event"] == WORLD_APPLIED and world is not None:
                applied = self._documents.read(
                    evidence_ref_from_document(record["evidence"]["transition"], "world_transition")
                )
                if world.progression.regime_changes(applied["transition"]):
                    regimes.setdefault(name, []).append(record["round"])
        return {
            node_id: tuple(
                EpisodeMemoryV1(
                    key,
                    _episode_document(name),
                    tuple(artifacts.get((name, node_id), ())),
                    tuple(sorted(set(regimes.get(name, ())))),
                )
                for name, key in earlier
            )
            for node_id in policies
        }

    def _resumes(self, episode: EpisodeIdentity) -> bool:
        """Whether the journal already opened *episode* (and has not closed it)."""

        events = [r["event"] for r in self._journal.read() if r.get("episode") == str(episode)]
        closed = [event for event in events if event in (EPISODE_COMPLETED, EPISODE_FAILED)]
        if closed:
            raise ResumeRefusedError(
                RESUME_EPISODE_CLOSED, f"episode {episode} is closed ({closed[0]})"
            )
        return EPISODE_OPENED in events

    def _authorize(self, plan: PlanIdentity) -> AuthorizationIdentity | None:
        """Refuse before any write unless gate-2 cleared exactly this plan."""

        if self._authorization is None:
            return None
        if self._authorization.plan != plan:
            raise ExecutionError(
                f"semantic plan {plan} is not the gate-2 authorized plan "
                f"{self._authorization.plan}"
            )
        durable = require_run_authorization_v2(
            self._journal.path.parent, run_id=self._run_id, journal=self._journal
        )
        if durable.identity != self._authorization.identity:
            raise ExecutionError(
                f"run {self._run_id} is opened under {durable.identity}, "
                f"not {self._authorization.identity}"
            )
        return durable.identity
