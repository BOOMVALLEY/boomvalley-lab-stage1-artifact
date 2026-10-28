"""`bvl-study-1`: one K0 study declaration, compiled into frozen plans (T1-010).

A study is data only.  It declares the Protocol IR, the initial World state,
the P04 actors (roles, execution profiles, actors; a profile may be chosen
``by_factor``), optional P05 information (frozen sources and default-deny
access rules, a rule optionally ``when`` a cell's levels and through a
registered transform; T1-011; ``actor_output`` sources naming a producer
node, the only way one actor observes another's output; T2-001), the P06
proposal contracts, the P07 decision authority, an
optional pre-bound analysis (T1-009), the P09 design contract and the config of
the plugins it names (``lifecycle.plugins``: the catalog and, given a
``plugin_loader``, the installed plugins; T4-011), and optionally the
``world`` it runs against (T3-001): ``{"plugin", "state_schema": "id:version",
"action_schema": "id:version"}`` names one registered World and the state and
action schema versions the study means (T3-003), and optionally the
``no_action`` meaning and ``exogenous_events`` kinds it means (T3-004; stated,
they must be the registered World's) and the ``rng_policy`` it runs under
(T3-006: ``DETERMINISTIC`` unless stated, so a study runs a stochastic World
only by declaring ``SEEDED``; BVL-WORLD-013 otherwise); the registered World's
contract is frozen into the plan (``semantic-plan-8``) and the initial state
must be a state of that schema.  A World with regimes is declared with its
``regime_events`` and ``regime_fields`` (T4-004; stated, they must be the
registered World's).  An optional ``schedule`` (``{"episodes": [...]}``,
T4-004) is the ExperimentSchedule the run executes, opening on
``episode_key``; without one the run is that one episode.  Every episode
opens on the initial World state; memory crosses an episode only under a
``memory_update`` node's declared ``carry``, whose episodes the schedule must
order as declared (BVL-ROUND-011).  Its ``root_seed`` is the
K0 seed tree every cell's plan binds (``semantic-plan-7``, T1-012): a changed
root seed is another plan.  Compilation is the P02
step: design cell levels -> the semantic plan document the engine executes for
that cell, through ``kernel.engine.semantic_plan_v2`` and nothing else.

The protocol may declare ``constructs``: ``bounded_revision`` blocks (T2-005,
``kernel.revision``) unrolled into finite IR nodes, whose proposal contracts,
veto decision and per-stage actor_output grants join the declared ones before
the plan is compiled.  Repetition is only ever a finite integer bound.

A study may declare ``humans`` (P17, T5-001, ``kernel.human``): a list of
``{"actor", "channel", "response": {"modality", "max_chars"}, "provenance":
{"minimum_grade"}, "consent": {"basis", "document_sha256"}, "privacy":
{"classification", "response_content"}}``, one per actor a person answers.
Such an actor's profile names the channel (a registered ``human_channel``) as
its provider and the human model ``bvl:human-participant:1``; the contracts are
frozen into every cell's plan (``semantic-plan-9``).  An actor on the human
model without a contract, or a contract over a model actor, is BVL-HUMAN-003;
a channel that does not carry the contract BVL-HUMAN-002.

A study may declare ``tools`` (P17, T5-003, ``kernel.tool``): a list of
``{"actor", "tool", "effect", "side_effect", "operation", "resource",
"arguments": {field: type}, "result": {field: type}}``, one per actor a tool
answers.  ``effect`` is ``READ_ONLY`` or ``MUTATING``; ``side_effect`` (T5-004)
is ``NONE`` for a read-only tool and ``IDEMPOTENT_BY_KEY`` or ``IRREVERSIBLE``
for a mutating one: what an unknown outcome of its call permits.  Such an
actor's profile names the tool (a registered ``tool`` plugin) as its provider
and the tool model
``bvl:tool-actor:1``; the contracts are frozen into every cell's plan
(``semantic-plan-10``).  An actor on the tool model without a contract, or a
contract over a model actor, is BVL-TOOL-003; a tool that is not the contracted
one (effect, side effect, operation or types) BVL-TOOL-002.  With
``"argument_selection": {argument: {"value": constant} | {"source": granted
source, "field": field of its JSON object}}`` (T5-007) the contract declares
where every argument of a call comes from and its actor can be executed; a
selected source its actor is not granted is BVL-TOOL-001.

Every refusal is a DeclarationError ``BVL-LIFE-001`` (or the kernel's own coded
refusal) raised before anything is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.core.strict_json import load_file
from boomvalley_lab.kernel.actors import (
    ActorBindingSetV1,
    ActorRegistryV1,
    ActorV1,
    ExecutionProfileV1,
    ProfileByFactorV1,
    RoleV1,
    SeedPolicy,
)
from boomvalley_lab.kernel.bound_analysis import AnalysisContractV1
from boomvalley_lab.kernel.coverage import CoverageContractsV1, DesignContractV1
from boomvalley_lab.kernel.decisions import (
    DecisionContractSetV1,
    DecisionDeclV1,
    DecisionRegistryV1,
)
from boomvalley_lab.kernel.engine import semantic_plan_v2
from boomvalley_lab.kernel.human import HumanActorContractSetV1, HumanActorContractV1
from boomvalley_lab.kernel.identity import PlanIdentity
from boomvalley_lab.kernel.information import (
    AccessRuleV1,
    ActorOutputSourceV1,
    InformationAccessSetV1,
    InformationRegistryV1,
    InformationSourceStoreV1,
    InformationSourceV1,
    MemoryArtifactSourceV1,
    SourceKind,
    TransformSpecV1,
)
from boomvalley_lab.kernel.memory import memory_policies, require_carry_schedule
from boomvalley_lab.kernel.package_binding import EntryPointLoader
from boomvalley_lab.kernel.plugin_registry import PluginRegistryV1, PluginType
from boomvalley_lab.kernel.proposals import (
    ProposalContractDeclV1,
    ProposalContractSetV1,
    ProposalRegistryV1,
    ProposalSchemaV1,
)
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR, ProtocolNode
from boomvalley_lab.kernel.revision import BoundedRevisionV1, CompiledRevisionV1, compile_protocol
from boomvalley_lab.kernel.rounds import RoundContractV1
from boomvalley_lab.kernel.schedule import ExperimentScheduleV1
from boomvalley_lab.kernel.seed import SeedDerivation
from boomvalley_lab.kernel.tool import CONTRACT_SCHEMA as TOOL_CONTRACT_SCHEMA
from boomvalley_lab.kernel.tool import CONTRACT_SCHEMA_V3 as TOOL_CONTRACT_SCHEMA_V3
from boomvalley_lab.kernel.tool import ToolActorContractSetV1, ToolActorContractV1
from boomvalley_lab.kernel.world import (
    ACTION_SCHEMA_INVALID,
    DETERMINISTIC,
    INITIAL_STATE_INVALID,
    RNG_POLICY_INVALID,
    WORLD_IDENTITY_MISMATCH,
    WorldContractV1,
    WorldError,
    state_domain_problems,
)
from boomvalley_lab.kernel.world_registry import WorldRegistryV1
from boomvalley_lab.lifecycle import plugins

STUDY_SCHEMA = "bvl-study-1"
STUDY_INVALID = "BVL-LIFE-001"
REQUIRED = frozenset({
    "schema", "experiment_id", "episode_key", "root_seed", "protocol",
    "initial_world_state", "roles", "profiles", "actors", "proposals", "decisions",
})
OPTIONAL = frozenset(
    {"analysis", "design", "humans", "information", "plugin_config", "schedule", "tools",
     "world"}
)


def invalid(detail: str) -> DeclarationError:
    return DeclarationError(f"{STUDY_INVALID} study declaration is invalid: {detail}",
                            code=STUDY_INVALID)


def is_study(document: Any) -> bool:
    return isinstance(document, Mapping) and document.get("schema") == STUDY_SCHEMA


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise invalid(f"{what} is an object")
    return value


def _list(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise invalid(f"{what} is a non-empty list")
    return value


def _closed(item: Any, required: set[str], optional: set[str], what: str) -> Mapping[str, Any]:
    item = _mapping(item, what)
    if not required <= set(item) <= required | optional:
        raise invalid(f"{what} has keys {sorted(item)}; required {sorted(required)}, "
                      f"optional {sorted(optional)}")
    return item


def _protocol(document: Any) -> tuple[ProtocolIR, tuple[CompiledRevisionV1, ...]]:
    document = _mapping(document, "protocol")
    # exactly one repetition: a bare ``rounds`` bound (bvl-protocol-ir-1) or a
    # typed ``round`` contract (P16, T4-001: bvl-protocol-ir-2)
    if ("rounds" in document) == ("round" in document):
        raise invalid("protocol declares exactly one of rounds (a bare bound) and round "
                      "(a round contract)")
    repetition = "round" if "round" in document else "rounds"
    document = _closed(document, {repetition, "nodes"}, {"constructs"}, "protocol")
    contract = (RoundContractV1.from_declaration(document["round"])
                if repetition == "round" else None)
    nodes = []
    for index, node in enumerate(_list(document["nodes"], "protocol.nodes")):
        node = _closed(node, {"id", "kind"}, {"depends_on", "config"}, f"protocol.nodes[{index}]")
        try:
            kind = NodeKind(node["kind"])
        except ValueError as error:
            raise invalid(f"protocol node kind {node['kind']!r} is unknown") from error
        depends = node.get("depends_on", [])
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
            raise invalid(f"protocol node {node['id']!r} depends_on is a list of node ids")
        nodes.append(ProtocolNode(node["id"], kind, tuple(depends),
                                  dict(_mapping(node.get("config", {}), "node config"))))
    blocks = [] if "constructs" not in document else [
        BoundedRevisionV1.from_document(item)
        for item in _list(document["constructs"], "protocol.constructs")
    ]
    protocol, compiled = compile_protocol(nodes, blocks, document.get("rounds", 1), contract)
    # A node's dependencies are a set: the order a declaration lists them in is
    # not part of the plan (T2-009), as the order of the nodes themselves is not.
    canonical = tuple(replace(node, depends_on=tuple(sorted(node.depends_on)))
                      for node in protocol.nodes)
    return ProtocolIR(canonical, protocol.rounds, protocol.round), compiled


def _registry(document: Mapping[str, Any]) -> ActorRegistryV1:
    roles = [RoleV1(role) for role in _list(document["roles"], "roles")]
    profiles = []
    for index, item in enumerate(_list(document["profiles"], "profiles")):
        item = _closed(item, {"profile_id", "provider", "model", "renderer"},
                       {"options", "seed_policy"}, f"profiles[{index}]")
        try:
            policy = SeedPolicy(item.get("seed_policy", SeedPolicy.PER_ACTOR.value))
        except ValueError as error:
            raise invalid(f"profiles[{index}].seed_policy is not one of "
                          f"{[p.value for p in SeedPolicy]}") from error
        profiles.append(ExecutionProfileV1(
            item["profile_id"], item["provider"], item["model"],
            dict(_mapping(item.get("options", {}), "profile options")), policy, item["renderer"],
        ))
    actors = []
    for index, item in enumerate(_list(document["actors"], "actors")):
        item = _closed(item, {"actor_id", "role", "profile"}, set(), f"actors[{index}]")
        profile = item["profile"]
        if isinstance(profile, Mapping):
            chosen = _closed(profile, {"factor", "cases"}, set(), f"actors[{index}].profile")
            profile = ProfileByFactorV1(chosen["factor"],
                                        dict(_mapping(chosen["cases"], "profile cases")))
        actors.append(ActorV1(item["actor_id"], item["role"], profile))
    return ActorRegistryV1(roles=roles, profiles=profiles, actors=actors)


def _proposals(document: Any, compiled: tuple[CompiledRevisionV1, ...] = ()) -> ProposalRegistryV1:
    document = _closed(document, {"schemas", "contracts"}, set(), "proposals")
    schemas = [ProposalSchemaV1.from_document(item)
               for item in _list(document["schemas"], "proposals.schemas")]
    contracts = [decl for unit in compiled for decl in unit.proposals]
    declared = ([] if compiled and document["contracts"] == []
                else _list(document["contracts"], "proposals.contracts"))
    for index, item in enumerate(declared):
        item = _closed(item, {"node_id", "schema", "parser"}, {"config", "on_invalid"},
                       f"proposals.contracts[{index}]")
        contracts.append(ProposalContractDeclV1(
            item["node_id"], item["schema"], item["parser"],
            dict(_mapping(item.get("config", {}), "parser config")),
            item.get("on_invalid", "PARSE_FAILURE"),
        ))
    return ProposalRegistryV1(schemas, contracts)


def _decisions(document: Any, compiled: tuple[CompiledRevisionV1, ...] = ()) -> DecisionRegistryV1:
    decisions = [unit.decision for unit in compiled]
    declared = [] if compiled and document == [] else _list(document, "decisions")
    for index, item in enumerate(declared):
        item = _closed(item, {"node_id", "rule", "authority"}, {"config", "on_unresolved"},
                       f"decisions[{index}]")
        decisions.append(DecisionDeclV1(
            item["node_id"], item["rule"], list(_list(item["authority"], "authority")),
            dict(_mapping(item.get("config", {}), "rule config")),
            item.get("on_unresolved", "FAIL_EPISODE"),
        ))
    return DecisionRegistryV1(decisions)


def _information(
    document: Any, base: Path, compiled: tuple[CompiledRevisionV1, ...] = ()
) -> InformationRegistryV1:
    """P05 sources and access rules.

    A ``frozen_resource`` names a ``path`` relative to the study file; an
    ``actor_output`` (T2-001) names its ``producer`` node, whose output the
    granted actors observe in the same round (P13 visibility); a
    ``memory_artifact`` (T4-003) names its ``producer`` memory_update node,
    whose Memory Artifacts valid in a round the granted actors observe.
    """

    sources: list[InformationSourceV1 | ActorOutputSourceV1 | MemoryArtifactSourceV1] = [
        source for unit in compiled for source in unit.sources
    ]
    rules = [rule for unit in compiled for rule in unit.access]
    if document is None:  # a study without information: only the blocks' grants
        return InformationRegistryV1(sources=sources, access=rules)
    document = _closed(document, {"sources", "access"}, set(), "information")
    for index, item in enumerate(_list(document["sources"], "information.sources")):
        if (
            isinstance(item, Mapping)
            and item.get("kind") == SourceKind.ACTOR_OUTPUT.value
            and "path" not in item  # an actor output is no file: BVL-INFO-012 below
        ):
            item = _closed(item, {"source_id", "kind", "producer"}, set(),
                           f"information.sources[{index}]")
            sources.append(ActorOutputSourceV1(item["source_id"], item["producer"]))
            continue
        if (
            isinstance(item, Mapping)
            and item.get("kind") == SourceKind.MEMORY_ARTIFACT.value
            and "path" not in item  # memory is no file either
        ):
            item = _closed(item, {"source_id", "kind", "producer"}, set(),
                           f"information.sources[{index}]")
            sources.append(MemoryArtifactSourceV1(item["source_id"], item["producer"]))
            continue
        item = _closed(item, {"source_id", "kind", "path"}, set(),
                       f"information.sources[{index}]")
        if not isinstance(item["path"], str) or not item["path"]:
            raise invalid(f"information.sources[{index}].path is a non-empty string")
        sources.append(InformationSourceV1(item["source_id"], item["kind"], base / item["path"]))
    for index, item in enumerate(_list(document["access"], "information.access")):
        item = _closed(item, {"actor", "source", "effect"}, {"when", "transform"},
                       f"information.access[{index}]")
        transform = None
        if "transform" in item:
            spec = _closed(item["transform"], {"transform"}, {"config"},
                           f"information.access[{index}].transform")
            transform = TransformSpecV1(spec["transform"],
                                        dict(_mapping(spec.get("config", {}), "transform config")))
        rules.append(AccessRuleV1(item["actor"], item["source"], item["effect"],
                                  dict(_mapping(item.get("when", {}), "access when")), transform))
    return InformationRegistryV1(sources=sources, access=rules)


def _analysis(document: Any) -> AnalysisContractV1:
    document = _closed(document, {"analysis_id", "metrics"}, set(), "analysis")
    return AnalysisContractV1.of(document["analysis_id"], _list(document["metrics"], "metrics"))


def _design(document: Any) -> DesignContractV1:
    document = _closed(document, set(), {"factors", "contrasts", "exclusions"}, "design")
    return DesignContractV1(
        dict(_mapping(document.get("factors", {}), "design.factors")),
        dict(_mapping(document.get("contrasts", {}), "design.contrasts")),
        dict(_mapping(document.get("exclusions", {}), "design.exclusions")),
    )


def _world(document: Any) -> dict[str, Any]:
    document = _closed(
        document,
        {"plugin", "state_schema", "action_schema"},
        {"no_action", "exogenous_events", "rng_policy", "regime_events", "regime_fields"},
        "world",
    )
    for name in ("plugin", "state_schema", "action_schema", "no_action", "rng_policy"):
        if name in document and (not isinstance(document[name], str) or not document[name]):
            raise invalid(f"world.{name} is a non-empty string")
    events = document.get("exogenous_events", [])
    if not isinstance(events, list) or any(not isinstance(kind, str) for kind in events):
        raise invalid("world.exogenous_events is a list of event kind names")
    for name in ("regime_events", "regime_fields"):
        names = document.get(name, [])
        if not isinstance(names, list) or any(not isinstance(item, str) for item in names):
            raise invalid(f"world.{name} is a list of names")
    return dict(document)


def _humans(document: Any) -> HumanActorContractSetV1:
    """The declared human actor contracts; the kernel reads each closed section."""

    contracts = []
    for index, item in enumerate(_list(document, "humans")):
        item = _closed(item, {"actor", "channel", "response", "provenance", "consent", "privacy"},
                       set(), f"humans[{index}]")
        contracts.append(HumanActorContractV1.from_document(
            {"schema": "bvl-human-actor-contract-1", "actor_id": item["actor"],
             **{key: item[key] for key in item if key != "actor"}}
        ))
    return HumanActorContractSetV1.of(contracts)


def _tools(document: Any) -> ToolActorContractSetV1:
    """The declared tool actor contracts; the kernel reads each closed contract."""

    keys = {
        "actor", "tool", "effect", "side_effect", "operation", "resource", "arguments",
        "result",
    }
    contracts = []
    for index, item in enumerate(_list(document, "tools")):
        item = _closed(item, keys, {"argument_selection"}, f"tools[{index}]")
        # T5-007: a contract that declares where its arguments come from
        schema = (
            TOOL_CONTRACT_SCHEMA_V3 if "argument_selection" in item else TOOL_CONTRACT_SCHEMA
        )
        contracts.append(ToolActorContractV1.from_document(
            {"schema": schema, "actor_id": item["actor"],
             **{key: item[key] for key in item if key != "actor"}}
        ))
    return ToolActorContractSetV1.of(contracts)


def _schedule(document: Any, episode_key: str) -> ExperimentScheduleV1:
    if document is None:
        return ExperimentScheduleV1((episode_key,))
    document = _closed(document, {"episodes"}, set(), "schedule")
    episodes = _list(document["episodes"], "schedule.episodes")
    if any(not isinstance(key, str) or not key for key in episodes) or len(
        set(episodes)
    ) != len(episodes):
        raise invalid("schedule.episodes is a list of distinct episode keys")
    if episodes[0] != episode_key:
        raise invalid(f"the schedule opens on episode_key {episode_key!r}, "
                      f"not on {episodes[0]!r}")
    return ExperimentScheduleV1(tuple(episodes))


@dataclass(frozen=True)
class CompiledStudy:
    """One validated study: its design cells compile to frozen semantic plans."""

    document: Mapping[str, Any]
    experiment_id: str
    episode_key: str
    root_seed: int
    protocol: ProtocolIR
    initial_world_state: Mapping[str, Any]
    registry: ActorRegistryV1
    proposals: ProposalContractSetV1
    decision_registry: DecisionRegistryV1
    analysis: AnalysisContractV1 | None
    design: DesignContractV1
    plugin_config: Mapping[str, Mapping[str, Any]]
    information_registry: InformationRegistryV1 | None = None
    world_declaration: Mapping[str, Any] | None = None
    # the episodes one run executes, in order (T4-004; default: episode_key)
    schedule: ExperimentScheduleV1 | None = None
    # resolves an installed plugin entry point (T4-011); None: the catalog only
    plugin_loader: EntryPointLoader | None = None
    # the actors a person answers, and under what terms (T5-001, plan-9)
    humans: HumanActorContractSetV1 | None = None
    # the actors a tool answers, and what the tool does (T5-003, plan-10)
    tools: ToolActorContractSetV1 | None = None

    @property
    def episodes(self) -> ExperimentScheduleV1:
        return self.schedule or ExperimentScheduleV1((self.episode_key,))

    @cached_property
    def plugins(self) -> PluginRegistryV1:
        # T5-001: the human channels the study's contracts name, and no other
        channels = () if self.humans is None else sorted(
            {contract.channel for contract in self.humans.contracts.values()}
        )
        # T5-003: likewise the tools its tool actor contracts name
        tools = () if self.tools is None else sorted(
            {contract.tool for contract in self.tools.contracts.values()}
        )
        return plugins.plugin_registry(
            self.plugin_config, self.plugin_loader, channels, tools
        )

    @cached_property
    def contracts(self) -> CoverageContractsV1:
        """The P09 coverage contracts of the registered plugins (P03 descriptors)."""

        return CoverageContractsV1.from_descriptors(self.plugins.descriptors())

    @cached_property
    def worlds(self) -> WorldRegistryV1:
        return WorldRegistryV1.from_plugins(self.plugins)

    @cached_property
    def world(self) -> WorldContractV1 | None:
        """The registered World's contract the study declares (plan-8), if any."""

        declared = self.world_declaration
        if declared is None:
            return None
        contract = self.worlds.contract(declared["plugin"])
        if contract.state_schema.ref != declared["state_schema"]:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"the study declares state schema {declared['state_schema']!r}; registered "
                f"World {contract.plugin!r} reads and writes {contract.state_schema.ref}",
            )
        if contract.action_schema.ref != declared["action_schema"]:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"the study declares action schema {declared['action_schema']!r}; registered "
                f"World {contract.plugin!r} accepts {contract.action_schema.ref}",
            )
        # T3-006: randomness is explicit - a study runs a stochastic World only by
        # declaring it, and declares none of a World that has none
        if declared.get("rng_policy", DETERMINISTIC) != contract.rng.policy:
            raise WorldError(
                RNG_POLICY_INVALID,
                f"the study declares the RNG policy "
                f"{declared.get('rng_policy', DETERMINISTIC)!r} (DETERMINISTIC unless stated); "
                f"registered World {contract.plugin!r} is {contract.rng.policy}",
            )
        frozen = contract.progression
        if declared.get("no_action", frozen.no_action) != frozen.no_action:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"the study declares NO_ACTION as {declared['no_action']!r}; to registered "
                f"World {contract.plugin!r} it means {frozen.no_action}",
            )
        if "exogenous_events" in declared and sorted(declared["exogenous_events"]) != list(
            frozen.exogenous_events
        ):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"the study declares exogenous events {sorted(declared['exogenous_events'])}; "
                f"registered World {contract.plugin!r} states "
                f"{list(frozen.exogenous_events)}",
            )
        # T4-004: the regime a study states is the registered World's
        for name in ("regime_events", "regime_fields"):
            if name in declared and sorted(declared[name]) != list(getattr(frozen, name)):
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH,
                    f"the study declares {name} {sorted(declared[name])}; registered "
                    f"World {contract.plugin!r} declares {list(getattr(frozen, name))}",
                )
        return contract

    def cells(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.design.cells())

    def levels(self, cell: str | None) -> tuple[str, dict[str, str]]:
        """The one design cell a run executes: *cell*, or the only cell there is."""

        cells = dict(self.design.cells())
        if cell is None:
            if len(cells) != 1:
                raise invalid(f"the design has {len(cells)} cells; name one with --cell "
                              f"({', '.join(cells)})")
            cell = next(iter(cells))
        if cell not in cells:
            raise invalid(f"cell {cell!r} is not a design cell ({', '.join(cells)})")
        return cell, cells[cell]

    def actors(self, levels: Mapping[str, str]) -> ActorBindingSetV1:
        return self.registry.resolve(dict(levels))

    def decisions(self, levels: Mapping[str, str]) -> DecisionContractSetV1:
        return self.decision_registry.resolve(self.protocol, self.actors(levels), self.proposals)

    def information(
        self, levels: Mapping[str, str]
    ) -> tuple[InformationAccessSetV1 | None, InformationSourceStoreV1 | None]:
        """The cell's resolved default-deny access and its kernel-held source store."""

        if self.information_registry is None:
            return None, None
        return self.information_registry.resolve(self.actors(levels), dict(levels))

    def compile_cell(self, levels: Mapping[str, str]) -> dict[str, Any]:
        return self.plan(levels)[0]

    def plan(self, levels: Mapping[str, str]) -> tuple[dict[str, Any], PlanIdentity]:
        return semantic_plan_v2(
            experiment_id=self.experiment_id,
            protocol=self.protocol,
            initial_world_state=self.initial_world_state,
            actors=self.actors(levels),
            information=self.information(levels)[0],
            proposals=self.proposals,
            decisions=self.decisions(levels),
            analysis=self.analysis,
            seeds=self.seeds,
            world=self.world,
            humans=self.humans,
            tools=self.tools,
        )

    @property
    def seeds(self) -> SeedDerivation:
        """The K0 seed tree every cell's plan binds (plan-7, T1-012)."""

        return SeedDerivation(self.root_seed)

    def require_plugins(self, levels: Mapping[str, str]) -> None:
        """Every renderer, provider and World the plan names is a catalog plugin."""

        for actor_id, binding in self.actors(levels).bindings.items():
            human = self.humans is not None and actor_id in self.humans
            tool = self.tools is not None and actor_id in self.tools
            for plugin_id, plugin_type in (
                (binding.profile.provider,
                 PluginType.HUMAN_CHANNEL if human
                 else PluginType.TOOL if tool else PluginType.ADAPTER),
                (binding.profile.renderer, PluginType.RENDERER),
            ):
                self._resolve(plugin_id, plugin_type, f"actor {actor_id!r}")
            if human:
                # T5-001: the registered channel carries the contract (BVL-HUMAN-002)
                self.humans.contract(actor_id).require_channel(
                    self.plugins.resolve(binding.profile.provider, PluginType.HUMAN_CHANNEL)
                )
                continue
            if tool:
                # T5-003: the registered tool is the contracted one (BVL-TOOL-002)
                self.tools.contract(actor_id).require_tool(
                    self.plugins.resolve(binding.profile.provider, PluginType.TOOL)
                )
                continue
            # T4-010: a provider may hold the profile to its config and option
            # domains here, so a misdeclared provider never opens a run
            hold = getattr(self.plugins.resolve(binding.profile.provider, PluginType.ADAPTER),
                           "require_profile", None)
            if hold is not None:
                try:
                    hold(binding.profile)
                except DeclarationError as error:
                    raise invalid(f"actor {actor_id!r} profile {binding.profile.profile_id!r}: "
                                  f"{error}") from None
        for node in self.protocol.nodes:
            if node.kind is NodeKind.WORLD_TRANSITION:
                self._resolve(node.config.get("world"), PluginType.WORLD, f"node {node.node_id!r}")
                # SV-11: a state of the schema that is outside the domain the World
                # states for its rule (a count below zero) opens no run
                outside = state_domain_problems(
                    getattr(self.worlds.worlds()[node.config["world"]], "state_domain", ()),
                    self.initial_world_state,
                )
                if outside:
                    raise WorldError(
                        INITIAL_STATE_INVALID,
                        f"the initial state is outside the domain of World "
                        f"{node.config['world']!r}: {'; '.join(outside)}",
                    )
                # SV-13: a World that states a domain keeps it only on the actions of
                # its schema, and only the `world` contract holds an action to them
                if self.world_declaration is None and getattr(
                    self.worlds.worlds()[node.config["world"]], "state_domain", ()
                ):
                    raise WorldError(
                        ACTION_SCHEMA_INVALID,
                        f"node {node.node_id!r} applies World {node.config['world']!r}, "
                        "whose rule is defined on a stated domain; the study declares no "
                        "`world` contract to hold its actions and states to it",
                    )
                # T3-006: K0 binds no RNG; a stochastic World runs only under the
                # `world` contract that freezes its policy
                policy = getattr(self.worlds.worlds()[node.config["world"]], "rng", None)
                if self.world_declaration is None and getattr(policy, "seeded", False):
                    raise WorldError(
                        RNG_POLICY_INVALID,
                        f"node {node.node_id!r} applies World {node.config['world']!r}, "
                        "whose rng policy is SEEDED; the study declares no `world` "
                        "contract to freeze it",
                    )

    def _resolve(self, plugin_id: Any, plugin_type: PluginType, where: str) -> None:
        try:
            self.plugins.resolve(plugin_id, plugin_type)
        except DeclarationError as error:
            raise invalid(f"{where} names {plugin_type.value} {plugin_id!r}: {error}") from None


def compile_study(
    document: Any, base: Path | None = None, *, plugin_loader: EntryPointLoader | None = None
) -> CompiledStudy:
    """*base* is the directory information source paths are relative to;
    *plugin_loader* admits the installed plugins beside the catalog (T4-011)."""

    document = _closed(document, set(REQUIRED), set(OPTIONAL), "study")
    if document["schema"] != STUDY_SCHEMA:
        raise invalid(f"schema is exactly {STUDY_SCHEMA!r}")
    for name in ("experiment_id", "episode_key"):
        if not isinstance(document[name], str) or not document[name]:
            raise invalid(f"{name} is a non-empty string")
    seed = document["root_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise invalid("root_seed is a non-negative integer")
    config = _mapping(document.get("plugin_config", {}), "plugin_config")
    protocol, compiled = _protocol(document["protocol"])
    study = CompiledStudy(
        document=document,
        experiment_id=document["experiment_id"],
        episode_key=document["episode_key"],
        root_seed=seed,
        protocol=protocol,
        initial_world_state=dict(_mapping(document["initial_world_state"],
                                          "initial_world_state")),
        registry=_registry(document),
        proposals=_proposals(document["proposals"], compiled).resolve(),
        decision_registry=_decisions(document["decisions"], compiled),
        analysis=None if "analysis" not in document else _analysis(document["analysis"]),
        design=_design(document.get("design", {})),
        plugin_config={k: dict(_mapping(v, f"plugin_config {k!r}")) for k, v in config.items()},
        information_registry=(None if "information" not in document and not compiled else
                              _information(document.get("information"), Path(base or "."),
                                           compiled)),
        world_declaration=None if "world" not in document else _world(document["world"]),
        schedule=_schedule(document.get("schedule"), document["episode_key"]),
        plugin_loader=plugin_loader,
        humans=None if "humans" not in document else _humans(document["humans"]),
        tools=None if "tools" not in document else _tools(document["tools"]),
    )
    # T4-004: the schedule orders every declared carry (BVL-ROUND-011)
    require_carry_schedule(
        memory_policies(study.protocol), study.episodes.episodes, journaled=True
    )
    for _, levels in study.design.cells():  # every cell compiles, before anything runs
        study.plan(levels)
        study.require_plugins(levels)
    return study


def load_study(path: Path, *, plugin_loader: EntryPointLoader | None = None) -> CompiledStudy:
    return compile_study(
        load_file(Path(path)), Path(path).resolve().parent, plugin_loader=plugin_loader
    )


def read_subject(path: Path) -> Any:
    """The parsed input document (study or not), read once."""

    return load_file(Path(path))
