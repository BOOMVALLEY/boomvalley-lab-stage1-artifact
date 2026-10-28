"""P09-ERF: plan-derived execution-relevant coverage and validation surfaces (T1-006).

Validation must check the frozen plan the runtime consumes, never a
hand-written description of it.  One product path replaces every
study-specific surface producer:

    DesignContractV1 (factors, levels, contrasts, typed exclusions)
        -> P02 compiles one frozen semantic plan per design cell
        -> ERF inventory: the kernel walks every key of every plan document;
           plugin config is enumerated only through the plugin's registered
           coverage contract (P03): undeclared key -> BVL-COV-002, plugin
           without a contract -> BVL-COV-010
        -> plan-derived surfaces: one GNDCRW ``gndcrw-surface/v0.1`` target
           per ERF, valued from the plan itself, one ``target catalog`` over
           the union of the cells
        -> comparison set: the required isolation edges derived from the
           design (2x2 -> four adjacent edges); each edge materializes its
           GNDCRW declaration (expected changes = the factor's declared
           contrast targets, invariants = every other ERF), surfaces, catalog
           and pair context
        -> CoverageAttestationV1 -> CoverageAttestationIdentity (gate-2)

Every ERF is either a validation target or a typed exclusion of a registered
``ExclusionClass`` that its owner permits; there is no free-text ignore list.
An incomplete execution coverage refuses gate-2 (``coverage_refusals``), so
no actor call happens.  A supplied (e.g. legacy hand-written) surface is
accepted only when it is mechanically equal to the plan-derived one
(BVL-COV-006 / BVL-COV-007).  After execution ``corroboration_problems``
holds the run's request / profile / parser / decision evidence to the
attested ERF values (BVL-COV-011).

P09-ARF (analysis-relevant coverage) belongs to P11; this attestation lists no
ARF and reports ``analysis_coverage`` NOT_EVALUATED.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import Digest, sha256_bytes
from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.kernel.identity import (
    CoverageAttestationIdentity,
    PlanIdentity,
    StepIdentity,
)
from boomvalley_lab.kernel.plugin_registry import PluginDescriptorV1, PluginType
from boomvalley_lab.kernel.rounds import planned_rounds

# P09 §8 stable reason-code family
INVENTORY_BUILD_FAILED = "BVL-COV-001"
ERF_UNMAPPED = "BVL-COV-002"
ARF_UNMAPPED = "BVL-COV-003"
EXCLUSION_CLASS_UNKNOWN = "BVL-COV-004"
EXCLUSION_NOT_ALLOWED = "BVL-COV-005"
SURFACE_PLAN_MISMATCH = "BVL-COV-006"
REQUIRED_TARGET_MISSING = "BVL-COV-007"
TARGET_PARTITION_INVALID = "BVL-COV-008"
COMPARISON_SET_INCOMPLETE = "BVL-COV-009"
PLUGIN_COVERAGE_CONTRACT_MISSING = "BVL-COV-010"
POST_EXECUTION_CORROBORATION_FAILED = "BVL-COV-011"

COVERAGE_CODES = frozenset(
    {
        INVENTORY_BUILD_FAILED,
        ERF_UNMAPPED,
        ARF_UNMAPPED,
        EXCLUSION_CLASS_UNKNOWN,
        EXCLUSION_NOT_ALLOWED,
        SURFACE_PLAN_MISMATCH,
        REQUIRED_TARGET_MISSING,
        TARGET_PARTITION_INVALID,
        COMPARISON_SET_INCOMPLETE,
        PLUGIN_COVERAGE_CONTRACT_MISSING,
        POST_EXECUTION_CORROBORATION_FAILED,
    }
)

INVENTORY_METHOD = "bvl-erf-inventory-1"
ATTESTATION_SCHEMA = "bvl-coverage-attestation-1"
CONTRACT_SCHEMA = "bvl-plugin-coverage-contract-1"
DESIGN_SCHEMA = "bvl-design-contract-1"
ADJACENT_ISOLATION = "bvl-adjacent-isolation-1"
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
ARF_NOT_EVALUATED = "NOT_EVALUATED"

# The GNDCRW v0.1 subject contracts the plan-derived surfaces are written in.
SURFACE_VERSION = "gndcrw-surface/v0.1"
CATALOG_VERSION = "gndcrw-target-catalog/v0.1"
DECLARATION_VERSION = "gndcrw-declaration/v0.1"
PAIR_VERSION = "gndcrw-pair/v0.1"
PROVIDER_ID = "boomvalley-lab"
CATALOG_ID = "bvl-plan-erf"
CATALOG_PROFILE = "erf-l1"
PLAN_SUBJECT_SCHEME = "boomvalley-lab-plan-identity"
SURFACE_ENTRYPOINT = "boomvalley_lab.kernel.coverage.plan_surface"

CORE = "core"
LIMITATIONS = (
    "P09-ARF analysis-relevant coverage is owned by P11 and not evaluated here",
    "provider codec identity is selected per provider at run time: evidenced in request-2, "
    "not enumerated by the plan (BVL-REC-128)",
    "World plugin semantics are L3 ERFs: initial World state is covered as plan data only",
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9._-]+")
_DESIGN_ID = re.compile(r"[A-Za-z0-9_-]+")


class CoverageError(DeclarationError):
    """A P09 refusal carrying one stable ``BVL-COV-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in COVERAGE_CODES:
            raise ValueError(f"unknown coverage reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


class ExclusionClass(StrEnum):
    """The registered typed exclusions; nothing else may leave the surface."""

    # a human-readable label no execution path consumes
    DISPLAY_LABEL = "DISPLAY_LABEL"
    # diagnostic metadata (paths, notes) no execution path consumes
    DIAGNOSTIC_METADATA = "DIAGNOSTIC_METADATA"
    # a legacy node-config binding a frozen P06/P07 contract supersedes
    SUPERSEDED_BY_CONTRACT = "SUPERSEDED_BY_CONTRACT"
    # the plan-6 analysis contract (T1-009): analysis-relevant, consumed by no
    # execution path; it is applied only to the sealed run's dataset units
    ANALYSIS_CONTRACT = "ANALYSIS_CONTRACT"


_EXCLUSIONS = frozenset(item.value for item in ExclusionClass)


def _digest(document: Any) -> str:
    return str(sha256_bytes(canonical_bytes(document)))


def _exclusion(value: Any, where: str) -> str:
    if value not in _EXCLUSIONS:
        raise CoverageError(
            EXCLUSION_CLASS_UNKNOWN,
            f"{where}: {value!r} is not a registered exclusion class {sorted(_EXCLUSIONS)}",
        )
    return str(value)


# --------------------------------------------------------------------- plugin contracts
@dataclass(frozen=True)
class PluginCoverageContractV1:
    """What a scientific plugin's frozen config can change (P09 §5).

    ``erf`` names the config keys that can change execution; ``excludable``
    names the keys the plugin declares non-scientific, each with the one
    registered exclusion class a declaration may apply to it.  A config key
    in neither is unenumerable: the plugin is not eligible (BVL-COV-002).
    """

    plugin_id: str
    plugin_type: PluginType
    erf: Sequence[str] = ()
    excludable: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_id, str) or not self.plugin_id:
            raise CoverageError(INVENTORY_BUILD_FAILED, "plugin_id must be a non-empty string")
        if not isinstance(self.plugin_type, PluginType):
            raise CoverageError(INVENTORY_BUILD_FAILED, "plugin_type is a registered PluginType")
        erf = tuple(self.erf)
        if len(erf) != len(set(erf)) or not all(isinstance(k, str) and k for k in erf):
            raise CoverageError(INVENTORY_BUILD_FAILED, f"{self.plugin_id}: erf keys are unique")
        excludable = {
            key: _exclusion(value, f"{self.plugin_id} excludable {key!r}")
            for key, value in dict(self.excludable).items()
        }
        if set(erf) & set(excludable):
            raise CoverageError(
                INVENTORY_BUILD_FAILED,
                f"{self.plugin_id}: keys {sorted(set(erf) & set(excludable))} are both "
                "execution-relevant and excludable",
            )
        object.__setattr__(self, "erf", tuple(sorted(erf)))
        object.__setattr__(self, "excludable", MappingProxyType(dict(sorted(excludable.items()))))

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "plugin_id": self.plugin_id,
            "plugin_type": self.plugin_type.value,
            "erf": list(self.erf),
            "excludable": dict(self.excludable),
        }

    def identity(self) -> str:
        return _digest(self.document())

    @classmethod
    def from_descriptor(
        cls, descriptor: PluginDescriptorV1, excludable: Mapping[str, str] | None = None
    ) -> PluginCoverageContractV1:
        """The P03 descriptor's ERF contribution as a coverage contract."""

        return cls(descriptor.plugin_id, descriptor.plugin_type, descriptor.erf, excludable or {})

    @classmethod
    def from_document(cls, document: Any) -> PluginCoverageContractV1:
        keys = {"schema", "plugin_id", "plugin_type", "erf", "excludable"}
        if (
            not isinstance(document, Mapping)
            or set(document) != keys
            or document["schema"] != CONTRACT_SCHEMA
            or not isinstance(document["erf"], list)
            or not isinstance(document["excludable"], Mapping)
        ):
            raise CoverageError(INVENTORY_BUILD_FAILED, "not a plugin coverage contract")
        try:
            plugin_type = PluginType(document["plugin_type"])
        except ValueError as error:
            raise CoverageError(INVENTORY_BUILD_FAILED, str(error)) from error
        contract = cls(
            document["plugin_id"], plugin_type, document["erf"], document["excludable"]
        )
        if contract.document() != dict(document):
            raise CoverageError(INVENTORY_BUILD_FAILED, "coverage contract is not normalized")
        return contract


# Contracts of the kernel's own builtin plugins.
BUILTIN_COVERAGE: Mapping[str, PluginCoverageContractV1] = MappingProxyType(
    {
        contract.plugin_id: contract
        for contract in (
            PluginCoverageContractV1("builtin.single-authority:1", PluginType.DECISION_RULE),
            PluginCoverageContractV1("builtin.majority:1", PluginType.DECISION_RULE),
            PluginCoverageContractV1("builtin.plurality:1", PluginType.DECISION_RULE),
            PluginCoverageContractV1("builtin.veto:1", PluginType.DECISION_RULE),
            PluginCoverageContractV1(
                "builtin.redact-json-keys:1", PluginType.VISIBILITY_TRANSFORM, ("keys",)
            ),
        )
    }
)


class CoverageContractsV1:
    """The plugin coverage contracts an inventory may consult (builtins included)."""

    def __init__(self, contracts: Sequence[PluginCoverageContractV1] = ()) -> None:
        merged = dict(BUILTIN_COVERAGE)
        for contract in contracts:
            if not isinstance(contract, PluginCoverageContractV1):
                raise CoverageError(INVENTORY_BUILD_FAILED, "not a PluginCoverageContractV1")
            if contract.plugin_id in BUILTIN_COVERAGE and contract == BUILTIN_COVERAGE[
                contract.plugin_id
            ]:
                continue  # an attestation lists the builtin contracts it used
            if contract.plugin_id in merged:
                raise CoverageError(
                    INVENTORY_BUILD_FAILED,
                    f"coverage contract {contract.plugin_id!r} is declared twice",
                )
            merged[contract.plugin_id] = contract
        self._contracts = MappingProxyType(dict(sorted(merged.items())))

    def get(self, plugin_id: str) -> PluginCoverageContractV1 | None:
        return self._contracts.get(plugin_id)

    @classmethod
    def from_descriptors(
        cls,
        descriptors: Sequence[PluginDescriptorV1],
        excludable: Mapping[str, Mapping[str, str]] | None = None,
    ) -> CoverageContractsV1:
        """Contracts from registered P03 descriptors (``registry.descriptors()``)."""

        excludable = dict(excludable or {})
        return cls(
            [
                PluginCoverageContractV1.from_descriptor(d, excludable.get(d.plugin_id))
                for d in descriptors
            ]
        )


# --------------------------------------------------------------------- inventory
@dataclass(frozen=True)
class CoverageFindingV1:
    code: str
    cell: str
    target: str
    detail: str

    def document(self) -> dict[str, str]:
        return {"code": self.code, "cell": self.cell, "target": self.target, "detail": self.detail}


@dataclass(frozen=True)
class ErfV1:
    """One execution-relevant field: its validation target, owner and plan value."""

    target: str
    owner: str
    value: Any

    def document(self) -> dict[str, Any]:
        return {"target": self.target, "owner": self.owner, "value": self.value}


@dataclass(frozen=True)
class ExcludedV1:
    target: str
    owner: str
    exclusion_class: str

    def document(self) -> dict[str, str]:
        return {"target": self.target, "owner": self.owner, "class": self.exclusion_class}


@dataclass(frozen=True)
class ErfInventoryV1:
    """The total ERF inventory of one frozen semantic plan."""

    erf: tuple[ErfV1, ...]
    excluded: tuple[ExcludedV1, ...]
    contracts: tuple[PluginCoverageContractV1, ...]
    findings: tuple[CoverageFindingV1, ...]

    def values(self) -> dict[str, Any]:
        return {item.target: item.value for item in self.erf}


# Node config keys the kernel itself consumes, per node kind.
CORE_NODE_CONFIG: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "actor_call": frozenset({"actor"}),
        "proposal_parse": frozenset({"parser"}),
        "decision": frozenset({"binding"}),
        "world_transition": frozenset({"world"}),
        # T4-003: scope / retention / transform declare a memory lifecycle;
        # T4-004: carry / regime_change declare what crosses an episode or a regime
        "memory_update": frozenset(
            {"owner", "key", "scope", "retention", "transform", "carry", "regime_change"}
        ),
        "termination": frozenset(),
    }
)
_PLAN_KEYS = frozenset(
    {
        "schema",
        "experiment_id",
        "protocol",
        "initial_world_state",
        "initial_memory",
        "actors",
        "information",
        "proposals",
        "decisions",
        "analysis",
        "seed",
        "world",
        "humans",
        "tools",
    }
)


class _Walk:
    def __init__(
        self, cell: str, contracts: CoverageContractsV1, exclusions: Mapping[str, str]
    ) -> None:
        self.cell = cell
        self.contracts = contracts
        self.exclusions = exclusions
        self.claimed: set[str] = set()
        self.erf: dict[str, ErfV1] = {}
        self.excluded: dict[str, ExcludedV1] = {}
        self.used: dict[str, PluginCoverageContractV1] = {}
        self.findings: list[CoverageFindingV1] = []

    def find(self, code: str, target: str, detail: str) -> None:
        self.findings.append(CoverageFindingV1(code, self.cell, target, detail))

    def _claim(self, target: str) -> bool:
        if not _IDENTIFIER.fullmatch(target):
            self.find(TARGET_PARTITION_INVALID, target, "not a GNDCRW target identifier")
            return False
        if target in self.claimed:
            self.find(TARGET_PARTITION_INVALID, target, "two plan fields map to one target")
            return False
        self.claimed.add(target)
        return True

    def field(self, target: str, value: Any, owner: str = CORE, excludable: str | None = None):
        if not self._claim(target):
            return
        declared = self.exclusions.get(target)
        if declared is not None:
            if declared == excludable:
                self.excluded[target] = ExcludedV1(target, owner, declared)
                return
            self.find(
                EXCLUSION_NOT_ALLOWED,
                target,
                f"{owner} does not permit exclusion class {declared} here",
            )
        self.erf[target] = ErfV1(target, owner, value)

    def exclude(self, target: str, exclusion: ExclusionClass) -> None:
        if self._claim(target):
            self.excluded[target] = ExcludedV1(target, CORE, exclusion.value)

    def unmapped(self, target: str, detail: str) -> None:
        self.find(ERF_UNMAPPED, target, detail)

    def closed(self, prefix: str, document: Mapping[str, Any], known: frozenset[str]) -> None:
        for key in sorted(set(document) - known):
            self.unmapped(f"{prefix}.{key}", "no core or plugin coverage contract claims it")

    def leaves(self, prefix: str, value: Any) -> None:
        if isinstance(value, Mapping) and value:
            for key in sorted(value):
                self.leaves(f"{prefix}.{key}", value[key])
        else:
            self.field(prefix, value)

    def plugin(
        self, prefix: str, plugin_id: Any, plugin_type: PluginType, config: Any
    ) -> None:
        """Enumerate *config* only through *plugin_id*'s coverage contract."""

        contract = self.contracts.get(plugin_id) if isinstance(plugin_id, str) else None
        if contract is None or contract.plugin_type is not plugin_type:
            self.find(
                PLUGIN_COVERAGE_CONTRACT_MISSING,
                prefix,
                f"{plugin_type.value} {plugin_id!r} has no {plugin_type.value} coverage "
                "contract; it is not eligible for scientific execution",
            )
            return
        self.used[contract.plugin_id] = contract
        if not isinstance(config, Mapping):
            self.unmapped(prefix, f"{plugin_id} config is not an enumerable object")
            return
        owner = f"plugin:{contract.plugin_id}"
        for key in sorted(config):
            target = f"{prefix}.{key}"
            if key in contract.erf:
                self.field(target, config[key], owner)
            elif key in contract.excludable:
                self.field(target, config[key], owner, excludable=contract.excludable[key])
            else:
                self.unmapped(
                    target, f"config key {key!r} is not in {plugin_id}'s coverage contract"
                )


def _protocol(walk: _Walk, protocol: Any, plan: Mapping[str, Any]) -> None:
    if "round" in protocol:
        # P16 (T4-001): the round contract is core-owned and wholly ERF
        walk.closed("protocol", protocol, frozenset({"schema", "round", "nodes"}))
        walk.field("protocol.schema", protocol["schema"])
        contract = protocol["round"]
        walk.closed("protocol.round", contract, frozenset({"schema", "max_rounds", "termination"}))
        walk.field("protocol.round.schema", contract["schema"])
        walk.field("protocol.round.max_rounds", contract["max_rounds"])
        timed = "timing" in contract["termination"]  # bvl-round-contract-2 (T4-002)
        walk.closed("protocol.round.termination", contract["termination"],
                    frozenset({"rule", "timing", "config"} if timed else {"rule", "config"}))
        walk.field("protocol.round.termination.rule", contract["termination"]["rule"])
        if timed:
            walk.field("protocol.round.termination.timing", contract["termination"]["timing"])
        walk.leaves("protocol.round.termination.config", contract["termination"]["config"])
    else:
        walk.closed("protocol", protocol, frozenset({"schema", "rounds", "nodes"}))
        walk.field("protocol.schema", protocol["schema"])
        walk.field("protocol.rounds", protocol["rounds"])
    contracted = {
        section: {item["node_id"] for item in plan[section]["contracts"]}
        for section in ("proposals", "decisions")
        if section in plan
    }
    for node in protocol["nodes"]:
        prefix = f"protocol.node.{node['id']}"
        walk.closed(prefix, node, frozenset({"id", "kind", "depends_on", "config"}))
        walk.field(f"{prefix}.kind", node["kind"])
        walk.field(f"{prefix}.depends_on", list(node["depends_on"]))
        consumed = CORE_NODE_CONFIG.get(node["kind"], frozenset())
        for key in sorted(node["config"]):
            target = f"{prefix}.config.{key}"
            superseded = (node["kind"], key) in (
                ("proposal_parse", "parser"),
                ("decision", "binding"),
            ) and node["id"] in contracted.get(
                "proposals" if key == "parser" else "decisions", set()
            )
            if superseded:
                walk.exclude(target, ExclusionClass.SUPERSEDED_BY_CONTRACT)
            elif key in consumed:
                walk.field(target, node["config"][key])
            else:
                walk.unmapped(target, f"{node['kind']} node config key {key!r} has no consumer")


def _actors(
    walk: _Walk,
    actors: Any,
    humans: frozenset[str] = frozenset(),
    tools: frozenset[str] = frozenset(),
) -> None:
    walk.closed("actors", actors, frozenset({"schema", "actors"}))
    walk.field("actors.schema", actors["schema"])
    for actor in actors["actors"]:
        prefix = f"actor.{actor['actor_id']}"
        walk.closed(prefix, actor, frozenset({"actor_id", "role", "profile"}))
        walk.field(f"{prefix}.role", actor["role"])
        profile = actor["profile"]
        keys = frozenset({"schema", "provider", "model", "options", "seed_policy", "renderer"})
        walk.closed(f"{prefix}.profile", profile, keys)
        for key in sorted(keys - {"options"}):
            walk.field(f"{prefix}.profile.{key}", profile[key])
        # options are the provider adapter's generation config; the renderer is
        # a scientific plugin without config: both need a coverage contract
        # (a human actor's provider is its human channel: T5-001; a tool
        # actor's is its tool: T5-003)
        provider = PluginType.ADAPTER
        if actor["actor_id"] in humans:
            provider = PluginType.HUMAN_CHANNEL
        elif actor["actor_id"] in tools:
            provider = PluginType.TOOL
        walk.plugin(
            f"{prefix}.profile.options", profile["provider"], provider, profile["options"],
        )
        walk.plugin(f"{prefix}.profile.renderer", profile["renderer"], PluginType.RENDERER, {})


def _humans(walk: _Walk, humans: Any) -> None:
    """The plan-9 human actor contracts (T5-001): who answers under what terms."""

    walk.closed("humans", humans, frozenset({"schema", "actors"}))
    walk.field("humans.schema", humans["schema"])
    keys = frozenset(
        {"schema", "actor_id", "channel", "response", "provenance", "consent", "privacy"}
    )
    for contract in humans["actors"]:
        prefix = f"human.{contract['actor_id']}"
        walk.closed(prefix, contract, keys)
        for key in sorted(keys - {"actor_id"}):
            walk.leaves(f"{prefix}.{key}", contract[key])


def _tools(walk: _Walk, tools: Any) -> None:
    """The plan-10 tool actor contracts (T5-003 / T5-004): which tool, which effect, which
    side effect, which types."""

    walk.closed("tools", tools, frozenset({"schema", "actors"}))
    walk.field("tools.schema", tools["schema"])
    keys = frozenset(
        {"schema", "actor_id", "tool", "effect", "side_effect", "operation", "resource",
         "arguments", "result"}
    )
    for contract in tools["actors"]:
        prefix = f"tool.{contract['actor_id']}"
        # a contract-3 (T5-007) also declares where its arguments come from
        held = keys | ({"argument_selection"} if "argument_selection" in contract else set())
        walk.closed(prefix, contract, frozenset(held))
        for key in sorted(held - {"actor_id"}):
            walk.leaves(f"{prefix}.{key}", contract[key])


def _information(walk: _Walk, information: Any) -> None:
    keys = frozenset({"schema", "sources", "grants", "transforms"})
    walk.closed("information", information, keys)
    walk.field("information.schema", information["schema"])
    for source in information["sources"]:
        prefix = f"information.source.{source['source_id']}"
        keys = (
            # actor_output (T2-001) / memory_artifact (T4-003) name a producer
            frozenset({"source_id", "source_kind", "producer"})
            if source.get("source_kind") in ("actor_output", "memory_artifact")
            else frozenset({"source_id", "source_kind", "content_sha256", "size"})
        )
        walk.closed(prefix, source, keys)
        for key in sorted(keys - {"source_id"} & set(source)):
            walk.field(f"{prefix}.{key}", source[key])
    for grant in information["grants"]:
        prefix = f"information.grant.{grant['actor_id']}"
        walk.closed(prefix, grant, frozenset({"actor_id", "sources"}))
        walk.field(prefix, list(grant["sources"]))
    for transform in information.get("transforms", []):
        prefix = f"information.transform.{transform['actor_id']}.{transform['source_id']}"
        walk.closed(prefix, transform, frozenset({"actor_id", "source_id", "transform", "config"}))
        walk.field(f"{prefix}.transform", transform["transform"])
        walk.plugin(
            f"{prefix}.config", transform["transform"], PluginType.VISIBILITY_TRANSFORM,
            transform["config"],
        )


def _proposals(walk: _Walk, proposals: Any) -> None:
    walk.closed("proposals", proposals, frozenset({"schema", "contracts"}))
    walk.field("proposals.schema", proposals["schema"])
    keys = frozenset({"schema", "node_id", "parser", "proposal_schema", "config", "on_invalid"})
    for contract in proposals["contracts"]:
        prefix = f"proposal.{contract['node_id']}"
        walk.closed(prefix, contract, keys)
        for key in ("schema", "parser", "proposal_schema", "on_invalid"):
            walk.field(f"{prefix}.{key}", contract[key])
        walk.plugin(
            f"{prefix}.config", contract["parser"], PluginType.PROPOSAL_PARSER, contract["config"]
        )


def _decisions(walk: _Walk, decisions: Any) -> None:
    walk.closed("decisions", decisions, frozenset({"schema", "contracts"}))
    walk.field("decisions.schema", decisions["schema"])
    keys = frozenset(
        {"schema", "node_id", "rule", "authority", "candidates", "config", "on_unresolved"}
    )
    for contract in decisions["contracts"]:
        prefix = f"decision.{contract['node_id']}"
        walk.closed(prefix, contract, keys)
        for key in ("schema", "rule", "authority", "candidates", "on_unresolved"):
            walk.field(f"{prefix}.{key}", contract[key])
        walk.plugin(
            f"{prefix}.config", contract["rule"], PluginType.DECISION_RULE, contract["config"]
        )


def erf_inventory(
    plan_document: Mapping[str, Any],
    contracts: CoverageContractsV1,
    *,
    exclusions: Mapping[str, str] | None = None,
    cell: str = "cell",
) -> ErfInventoryV1:
    """Walk every key of one frozen semantic plan into its ERF inventory.

    Never raises on a coverage gap: gaps are findings.  A plan that is not a
    semantic plan document at all raises BVL-COV-001.
    """

    walk = _Walk(cell, contracts, dict(exclusions or {}))
    try:
        if not isinstance(plan_document, Mapping) or "protocol" not in plan_document:
            raise TypeError("not a semantic plan document")
        walk.closed("plan", plan_document, _PLAN_KEYS)
        walk.field("plan.schema", plan_document["schema"])
        walk.field("plan.experiment_id", plan_document["experiment_id"])
        _protocol(walk, plan_document["protocol"], plan_document)
        walk.leaves("world.initial", plan_document.get("initial_world_state", {}))
        walk.leaves("memory.initial", plan_document.get("initial_memory", {}))
        if "actors" in plan_document:
            _actors(
                walk, plan_document["actors"],
                frozenset(
                    contract["actor_id"]
                    for contract in plan_document.get("humans", {}).get("actors", ())
                ),
                frozenset(
                    contract["actor_id"]
                    for contract in plan_document.get("tools", {}).get("actors", ())
                ),
            )
        if "information" in plan_document:
            _information(walk, plan_document["information"])
        if "proposals" in plan_document:
            _proposals(walk, plan_document["proposals"])
        if "decisions" in plan_document:
            _decisions(walk, plan_document["decisions"])
        if "analysis" in plan_document:
            walk.exclude("analysis", ExclusionClass.ANALYSIS_CONTRACT)
        if "seed" in plan_document:
            # the plan-7 seed tree (T1-012) decides every derived seed: an ERF
            walk.leaves("seed", plan_document["seed"])
        if "world" in plan_document:
            # the plan-8 World contract (T3-001): which World, and the schema
            # version of every state it reads and writes
            walk.leaves("world.contract", plan_document["world"])
        if "humans" in plan_document:
            _humans(walk, plan_document["humans"])
        if "tools" in plan_document:
            _tools(walk, plan_document["tools"])
    except (KeyError, TypeError, AttributeError) as error:
        raise CoverageError(
            INVENTORY_BUILD_FAILED, f"plan does not walk: {type(error).__name__}: {error}"
        ) from error
    for target in sorted(set(walk.exclusions) - walk.claimed):
        walk.find(EXCLUSION_NOT_ALLOWED, target, "the declared exclusion names no plan field")
    return ErfInventoryV1(
        erf=tuple(walk.erf[t] for t in sorted(walk.erf)),
        excluded=tuple(walk.excluded[t] for t in sorted(walk.excluded)),
        contracts=tuple(walk.used[p] for p in sorted(walk.used)),
        findings=tuple(walk.findings),
    )


# --------------------------------------------------------------------- design / contrasts
@dataclass(frozen=True)
class ComparisonEdgeV1:
    edge_id: str
    factor: str
    base_cell: str
    candidate_cell: str

    def document(self) -> dict[str, str]:
        return {
            "edge_id": self.edge_id,
            "factor": self.factor,
            "base_cell": self.base_cell,
            "candidate_cell": self.candidate_cell,
        }


def _matches(pattern: str, target: str) -> bool:
    if pattern.endswith(".*"):
        return target.startswith(pattern[:-1])
    return target == pattern


@dataclass(frozen=True)
class DesignContractV1:
    """The typed design/contrast contract (P09 §13.2).

    ``factors`` maps each factor to its ordered closed levels; ``contrasts``
    maps every factor to the targets (exact ids, or ``prefix.*``) its levels
    are declared to change.  Researchers declare contrasts; the kernel
    derives the comparison edges.  ``exclusions`` are typed exclusions
    ``target -> ExclusionClass`` the declaration applies.
    """

    factors: Mapping[str, Sequence[str]] = field(default_factory=dict)
    contrasts: Mapping[str, Sequence[str]] = field(default_factory=dict)
    exclusions: Mapping[str, str] = field(default_factory=dict)
    comparison: str = ADJACENT_ISOLATION

    def __post_init__(self) -> None:
        factors: dict[str, tuple[str, ...]] = {}
        for factor, levels in dict(self.factors).items():
            levels = tuple(levels)
            ids = (factor, *levels)
            if not all(isinstance(i, str) and _DESIGN_ID.fullmatch(i) for i in ids):
                raise CoverageError(
                    TARGET_PARTITION_INVALID, f"factor {factor!r} / levels {levels!r} are not ids"
                )
            if len(levels) < 2 or len(set(levels)) != len(levels):
                raise CoverageError(
                    TARGET_PARTITION_INVALID, f"factor {factor!r} needs >= 2 distinct levels"
                )
            factors[factor] = levels
        contrasts = {factor: tuple(targets) for factor, targets in dict(self.contrasts).items()}
        if set(contrasts) != set(factors):
            raise CoverageError(
                COMPARISON_SET_INCOMPLETE,
                f"every factor declares its contrast: factors {sorted(factors)}, "
                f"contrasts {sorted(contrasts)}",
            )
        for factor, targets in contrasts.items():
            if not targets or not all(isinstance(t, str) and t for t in targets):
                raise CoverageError(
                    COMPARISON_SET_INCOMPLETE, f"factor {factor!r} declares no changed target"
                )
        exclusions = {
            target: _exclusion(value, f"declared exclusion {target!r}")
            for target, value in dict(self.exclusions).items()
        }
        if self.comparison != ADJACENT_ISOLATION:
            raise CoverageError(
                COMPARISON_SET_INCOMPLETE, f"comparison method {self.comparison!r} is unknown"
            )
        object.__setattr__(self, "factors", MappingProxyType(dict(sorted(factors.items()))))
        object.__setattr__(
            self,
            "contrasts",
            MappingProxyType({f: tuple(sorted(set(t))) for f, t in sorted(contrasts.items())}),
        )
        object.__setattr__(self, "exclusions", MappingProxyType(dict(sorted(exclusions.items()))))

    @staticmethod
    def cell_key(cell: Mapping[str, str]) -> str:
        return "cell" + "".join(f".{factor}-{cell[factor]}" for factor in sorted(cell))

    def cells(self) -> tuple[tuple[str, dict[str, str]], ...]:
        names = list(self.factors)
        return tuple(
            (self.cell_key(dict(zip(names, combo, strict=True))),
             dict(zip(names, combo, strict=True)))
            for combo in itertools.product(*(self.factors[n] for n in names))
        )

    def comparison_edges(self) -> tuple[ComparisonEdgeV1, ...]:
        """Adjacent isolation: consecutive levels of one factor, all else held."""

        edges = []
        for factor, levels in self.factors.items():
            others = [f for f in self.factors if f != factor]
            for context in itertools.product(*(self.factors[f] for f in others)):
                held = dict(zip(others, context, strict=True))
                for low, high in itertools.pairwise(levels):
                    base = self.cell_key({**held, factor: low})
                    candidate = self.cell_key({**held, factor: high})
                    suffix = "".join(f".{f}-{held[f]}" for f in sorted(held))
                    edges.append(
                        ComparisonEdgeV1(
                            f"edge.{factor}.{low}-{high}{suffix}", factor, base, candidate
                        )
                    )
        return tuple(sorted(edges, key=lambda edge: edge.edge_id))

    def document(self) -> dict[str, Any]:
        return {
            "schema": DESIGN_SCHEMA,
            "factors": {f: list(levels) for f, levels in self.factors.items()},
            "contrasts": {f: list(targets) for f, targets in self.contrasts.items()},
            "exclusions": dict(self.exclusions),
            "comparison": self.comparison,
        }

    @classmethod
    def from_document(cls, document: Any) -> DesignContractV1:
        keys = {"schema", "factors", "contrasts", "exclusions", "comparison"}
        if not isinstance(document, Mapping) or set(document) != keys or (
            document["schema"] != DESIGN_SCHEMA
        ):
            raise CoverageError(INVENTORY_BUILD_FAILED, "not a bvl-design-contract-1 document")
        design = cls(
            document["factors"], document["contrasts"], document["exclusions"],
            document["comparison"],
        )
        if design.document() != dict(document):
            raise CoverageError(INVENTORY_BUILD_FAILED, "design contract is not normalized")
        return design


# --------------------------------------------------------------------- GNDCRW subjects
def _value_kind(values: Sequence[Any]) -> str:
    def kind(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "NUMBER"
        if isinstance(value, str):
            return "STRING"
        return "JSON"

    kinds = {kind(value) for value in values}
    return kinds.pop() if len(kinds) == 1 else "JSON"


def target_catalog(cells: Mapping[str, Mapping[str, Any]]) -> dict:
    """The GNDCRW target catalog over the union of the cells' ERF targets.

    A target absent from a cell is observed there as JSON ``null`` (the plan
    has no such field), so its kind widens to JSON.
    """

    targets: dict[str, Any] = {}
    for target in sorted({t for values in cells.values() for t in values}):
        values = [values.get(target) for values in cells.values()]
        kind = _value_kind(values)
        targets[target] = {
            "level": "SUBSTRUCTURE" if kind == "JSON" else "SURFACE",
            "value_kind": kind,
            "availability": "SUPPORTED",
            "equality": "JSON_STRUCTURAL",
        }
    catalog = {
        "catalog_version": CATALOG_VERSION,
        "catalog_id": CATALOG_ID,
        "profile_id": CATALOG_PROFILE,
        "provider_id": PROVIDER_ID,
        "targets": targets,
        "composition_targets": {
            "entity_count": {
                "value_kind": "INTEGER",
                "availability": "SUPPORTED",
                "equality": "JSON_STRUCTURAL",
            },
            "entity_set": {
                "value_kind": "STRING_SET",
                "availability": "SUPPORTED",
                "equality": "SET_EXACT",
            },
        },
    }
    catalog["catalog_digest"] = catalog_digest(catalog)
    return catalog


def catalog_digest(catalog: Mapping[str, Any]) -> str:
    """GNDCRW CATALOG §5: SHA-256 over everything but ``catalog_digest``."""

    return _digest({key: value for key, value in catalog.items() if key != "catalog_digest"})


def catalog_ref(catalog: Mapping[str, Any]) -> dict[str, str]:
    return {
        name: catalog[name]
        for name in ("provider_id", "catalog_id", "catalog_version", "profile_id", "catalog_digest")
    }


def plan_surface(
    surface_id: str,
    role: str,
    values: Mapping[str, Any],
    catalog: Mapping[str, Any],
    plan: PlanIdentity,
    actors: Sequence[str],
) -> dict[str, Any]:
    """One GNDCRW surface valued from one cell's plan ERFs (no producer script)."""

    return {
        "surface_version": SURFACE_VERSION,
        "surface_id": surface_id,
        "role": role,
        "provider": {
            "provider_id": PROVIDER_ID,
            "provider_version": INVENTORY_METHOD,
            "adapter_id": "bvl-plan-surface",
            "adapter_version": "1",
        },
        "assembly": {
            "mode": "DIRECT",
            "assembly_entrypoint": SURFACE_ENTRYPOINT,
            "equivalence": None,
        },
        "targets": {
            target: {
                "level": descriptor["level"],
                "observability": "OBSERVED",
                "value": values.get(target),
            }
            for target, descriptor in catalog["targets"].items()
        },
        "composition": {
            "entity_kind": "actor",
            "entity_count": len(actors),
            "entity_ids": sorted(actors),
            "identity_namespace": "bvl.actor/v1",
        },
        "provenance": {"input_digests": {PLAN_SUBJECT_SCHEME: str(plan.digest)}},
        "premises": [],
    }


# --------------------------------------------------------------------- attestation
@dataclass(frozen=True)
class CellCoverageV1:
    cell: str
    levels: Mapping[str, str]
    plan: PlanIdentity
    actors: tuple[str, ...]
    inventory: ErfInventoryV1

    def values(self) -> dict[str, Any]:
        return self.inventory.values()

    def surface_digest(self) -> str:
        return _digest(self.values())

    def document(self) -> dict[str, Any]:
        return {
            "cell": self.cell,
            "levels": dict(self.levels),
            "plan": self.plan.document(),
            "actors": list(self.actors),
            "erf": [item.document() for item in self.inventory.erf],
            "excluded": [item.document() for item in self.inventory.excluded],
            "plugin_contracts": sorted(c.identity() for c in self.inventory.contracts),
            "surface_digest": self.surface_digest(),
        }


def edge_documents(
    design: DesignContractV1,
    cells: Mapping[str, tuple[Mapping[str, Any], PlanIdentity, Sequence[str]]],
    edge: ComparisonEdgeV1,
) -> dict[str, dict[str, Any]]:
    """The five GNDCRW subject documents of one edge (cell -> values, plan, actors).

    The single construction both the gate (from the in-memory attestation)
    and the package verifier (from the stored attestation, T1-007) use.
    """

    catalog = target_catalog({key: values for key, (values, _, _) in cells.items()})
    changes = sorted(
        t for t in catalog["targets"]
        if any(_matches(p, t) for p in design.contrasts[edge.factor])
    )

    def rule(prefix: str, index: int, target: str, operation: str) -> dict[str, Any]:
        return {
            "rule_id": f"{prefix}-{index:04d}",
            "target": {"kind": "TARGET", "id": target},
            "operation": operation,
            "scope": {"kind": "WHOLE_TARGET"},
            "premise_refs": [],
        }

    def surface(key: str, role: str) -> dict[str, Any]:
        values, plan, actors = cells[key]
        return plan_surface(key, role, values, catalog, plan, actors)

    declaration: dict[str, Any] = {
        "declaration_version": DECLARATION_VERSION,
        "declaration_id": edge.edge_id,
        "intent": {"intent_id": edge.edge_id, "intent_digest": ""},
        "catalog_ref": catalog_ref(catalog),
        "comparison": {"required_mode": "CONTROL"},
        "expected_changes": [
            rule("CHG", i, t, "MUST_DIFFER") for i, t in enumerate(changes, 1)
        ],
        "invariants": [
            rule("INV", i, t, "MUST_EQUAL")
            for i, t in enumerate((t for t in catalog["targets"] if t not in changes), 1)
        ],
        "declared_consequences": [],
        "premises": [],
        "context": [],
    }
    # GNDCRW DECLARATION §5 intent projection (rule ids already sort in order)
    projection = ("catalog_ref", "comparison", "expected_changes", "invariants",
                  "declared_consequences", "premises", "context")
    declaration["intent"]["intent_digest"] = _digest(
        {key: declaration[key] for key in projection}
    )
    return {
        "declaration": declaration,
        "target_catalog": catalog,
        "base_surface": surface(edge.base_cell, "BASE"),
        "candidate_surface": surface(edge.candidate_cell, "CANDIDATE"),
        "pair_context": {
            "pair_version": PAIR_VERSION,
            "comparison_mode": "CONTROL",
            "base_surface_id": edge.base_cell,
            "candidate_surface_id": edge.candidate_cell,
            "entity_comparability": {
                "status": "ESTABLISHED",
                "method": "STABLE_DOMAIN_ID",
                "authority": {"kind": "PROVIDER", "id": PROVIDER_ID},
                "mapping": None,
                "limitations": [],
            },
        },
    }


def _plan_of(document: Any) -> PlanIdentity:
    if not isinstance(document, Mapping) or document.get("kind") != PlanIdentity.KIND:
        raise ValueError("an attested cell plan is not a plan identity")
    return PlanIdentity(Digest.parse(document["digest"]))


def attested_edge_documents(document: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Every required edge's GNDCRW subjects, rebuilt from a stored attestation.

    Raises CoverageError when the document is not an attestation of its design.
    """

    if not isinstance(document, Mapping) or document.get("schema") != ATTESTATION_SCHEMA:
        raise CoverageError(INVENTORY_BUILD_FAILED, "not a bvl-coverage-attestation-1 document")
    try:
        design = DesignContractV1.from_document(document["design"])
        cells = {
            item["cell"]: (
                {e["target"]: e.get("value") for e in item["erf"]},
                _plan_of(item["plan"]),
                tuple(item["actors"]),
            )
            for item in document["cells"]
        }
    except (KeyError, TypeError, ValueError) as error:
        raise CoverageError(
            INVENTORY_BUILD_FAILED, f"attestation does not parse: {error}"
        ) from error
    if sorted(cells) != sorted(key for key, _ in design.cells()):
        raise CoverageError(TARGET_PARTITION_INVALID, "attested cells are not the design's")
    return {edge.edge_id: edge_documents(design, cells, edge) for edge in design.comparison_edges()}


def _plan_actors(plan_document: Mapping[str, Any]) -> tuple[str, ...]:
    actors = plan_document.get("actors", {}).get("actors", [])
    return tuple(sorted(actor["actor_id"] for actor in actors))


@dataclass(frozen=True)
class CoverageAttestationV1:
    """P09-ERF coverage attestation: first-class pre-execution evidence."""

    design: DesignContractV1
    cells: tuple[CellCoverageV1, ...]
    contracts: tuple[PluginCoverageContractV1, ...]
    findings: tuple[CoverageFindingV1, ...]
    supplied_surfaces: Mapping[str, str] = field(default_factory=dict)

    @property
    def execution_coverage(self) -> str:
        return COMPLETE if not self.findings else INCOMPLETE

    def cell(self, key: str) -> CellCoverageV1:
        for cell in self.cells:
            if cell.cell == key:
                return cell
        raise CoverageError(TARGET_PARTITION_INVALID, f"no design cell {key!r}")

    def cell_for_plan(self, plan: PlanIdentity) -> CellCoverageV1 | None:
        return next((cell for cell in self.cells if cell.plan == plan), None)

    def catalog(self) -> dict[str, Any]:
        return target_catalog({cell.cell: cell.values() for cell in self.cells})

    def surface(self, key: str, role: str = "BASE") -> dict[str, Any]:
        cell = self.cell(key)
        return plan_surface(key, role, cell.values(), self.catalog(), cell.plan, cell.actors)

    def edges(self) -> tuple[ComparisonEdgeV1, ...]:
        return self.design.comparison_edges()

    def expected_changes(self, factor: str) -> list[str]:
        targets = self.catalog()["targets"]
        return sorted(
            t for t in targets if any(_matches(p, t) for p in self.design.contrasts[factor])
        )

    def gndcrw_edge(self, edge_id: str) -> dict[str, dict[str, Any]]:
        """The five GNDCRW subject documents of one required comparison edge."""

        edge = next((e for e in self.edges() if e.edge_id == edge_id), None)
        if edge is None:
            raise CoverageError(COMPARISON_SET_INCOMPLETE, f"{edge_id!r} is not a required edge")
        cells = {cell.cell: (cell.values(), cell.plan, cell.actors) for cell in self.cells}
        return edge_documents(self.design, cells, edge)

    def comparison_set_document(self) -> dict[str, Any]:
        values = {cell.cell: cell.values() for cell in self.cells}
        edges = []
        for edge in self.edges():
            base, candidate = values[edge.base_cell], values[edge.candidate_cell]
            differing = sorted(
                t for t in set(base) | set(candidate) if base.get(t) != candidate.get(t)
            )
            edges.append(
                {
                    **edge.document(),
                    "expected_changes": self.expected_changes(edge.factor),
                    "differing_targets": differing,
                }
            )
        return {"method": self.design.comparison, "edges": edges}

    def document(self) -> dict[str, Any]:
        catalog = self.catalog()
        return {
            "schema": ATTESTATION_SCHEMA,
            "lifecycle": "P09-ERF",
            "inventory_method": INVENTORY_METHOD,
            "design": self.design.document(),
            "plugin_contracts": [c.document() for c in self.contracts],
            "cells": [cell.document() for cell in self.cells],
            "catalog": {
                "catalog_ref": catalog_ref(catalog),
                "targets": len(catalog["targets"]),
            },
            "comparison_set": self.comparison_set_document(),
            "supplied_surfaces": dict(self.supplied_surfaces),
            "findings": [finding.document() for finding in self.findings],
            "erf_count": sum(len(cell.inventory.erf) for cell in self.cells),
            "unmapped_erf_count": sum(f.code == ERF_UNMAPPED for f in self.findings),
            "arf": [],
            "unmapped_arf_count": 0,
            "execution_coverage": self.execution_coverage,
            "analysis_coverage": ARF_NOT_EVALUATED,
            "limitations": list(LIMITATIONS),
        }

    def identity(self) -> CoverageAttestationIdentity:
        return CoverageAttestationIdentity.of_payload(self.document())


def _supplied_findings(
    cell: str, supplied: Any, values: Mapping[str, Any], catalog: Mapping[str, Any]
) -> list[CoverageFindingV1]:
    """A supplied surface must equal the plan-derived one (P09 §3.3, FR-04)."""

    if not isinstance(supplied, Mapping) or not isinstance(supplied.get("targets"), Mapping):
        return [CoverageFindingV1(SURFACE_PLAN_MISMATCH, cell, "targets", "not a surface")]
    targets = supplied["targets"]
    findings = []
    for target in sorted(catalog["targets"]):
        if target not in targets:
            findings.append(
                CoverageFindingV1(
                    REQUIRED_TARGET_MISSING, cell, target,
                    "the runtime consumes this ERF but the supplied surface omits it",
                )
            )
            continue
        record = targets[target]
        if not isinstance(record, Mapping) or record.get("observability") != "OBSERVED" or (
            record.get("value") != values.get(target)
        ):
            findings.append(
                CoverageFindingV1(
                    SURFACE_PLAN_MISMATCH, cell, target,
                    "the supplied value is not the frozen plan value",
                )
            )
    findings.extend(
        CoverageFindingV1(SURFACE_PLAN_MISMATCH, cell, target, "not an ERF of the plan")
        for target in sorted(set(targets) - set(catalog["targets"]))
    )
    return findings


def attest_execution_coverage(
    design: DesignContractV1,
    compile_cell: Callable[[Mapping[str, str]], Mapping[str, Any]],
    contracts: CoverageContractsV1,
    *,
    supplied_surfaces: Mapping[str, Any] | None = None,
) -> CoverageAttestationV1:
    """Derive the ERF coverage attestation of every design cell's frozen plan.

    *compile_cell* is the P02 compiler: design cell levels -> the semantic
    plan document the engine will execute for that cell.  *supplied_surfaces*
    (cell -> GNDCRW surface) are only ever checked against the plan-derived
    form; the plan-derived form is the authority.
    """

    cells: list[CellCoverageV1] = []
    findings: list[CoverageFindingV1] = []
    used: dict[str, PluginCoverageContractV1] = {}
    for key, levels in design.cells():
        document = compile_cell(dict(levels))
        inventory = erf_inventory(document, contracts, exclusions=design.exclusions, cell=key)
        cells.append(
            CellCoverageV1(
                key, levels, PlanIdentity.of_payload(document), _plan_actors(document), inventory
            )
        )
        findings.extend(inventory.findings)
        used.update({c.plugin_id: c for c in inventory.contracts})
    attestation = CoverageAttestationV1(
        design, tuple(cells), tuple(used[p] for p in sorted(used)), ()
    )
    catalog = attestation.catalog()
    for factor, patterns in design.contrasts.items():
        for pattern in patterns:
            if not any(_matches(pattern, target) for target in catalog["targets"]):
                findings.append(
                    CoverageFindingV1(
                        REQUIRED_TARGET_MISSING, "design", pattern,
                        f"factor {factor!r} declares a change no plan ERF carries",
                    )
                )
    surfaces = dict(supplied_surfaces or {})
    for key in sorted(set(surfaces) - {cell.cell for cell in cells}):
        findings.append(
            CoverageFindingV1(TARGET_PARTITION_INVALID, key, "surface", "no such design cell")
        )
    digests = {}
    for cell in cells:
        if cell.cell in surfaces:
            digests[cell.cell] = _digest(surfaces[cell.cell])
            findings.extend(
                _supplied_findings(cell.cell, surfaces[cell.cell], cell.values(), catalog)
            )
    return CoverageAttestationV1(
        design, tuple(cells), attestation.contracts, tuple(findings), digests
    )


# --------------------------------------------------------------------- gate / verification
def coverage_refusals(
    attestation: CoverageAttestationV1,
    plan: PlanIdentity,
    *,
    bound_comparisons: Sequence[str] | None = None,
) -> list[str]:
    """gate-2 refusal reasons the coverage gives *plan* (``[]``: coverage clears).

    *bound_comparisons*, when given, are the edge ids validation results are
    bound for; anything short of the full required set refuses (P09 §3.4).
    """

    reasons = sorted({f"{f.code}:{f.cell}:{f.target}" for f in attestation.findings})
    if attestation.cell_for_plan(plan) is None:
        reasons.append(f"{TARGET_PARTITION_INVALID}:plan:{plan} is not an attested design cell")
    if bound_comparisons is not None:
        missing = sorted({e.edge_id for e in attestation.edges()} - set(bound_comparisons))
        reasons.extend(f"{COMPARISON_SET_INCOMPLETE}:{edge}" for edge in missing)
    return reasons


def require_execution_coverage(attestation: CoverageAttestationV1, plan: PlanIdentity) -> None:
    reasons = coverage_refusals(attestation, plan)
    if reasons:
        code = reasons[0].split(":", 1)[0]
        raise CoverageError(code, "execution coverage is incomplete: " + "; ".join(reasons))


def attested_cell_problems(
    document: Any, plan_document: Mapping[str, Any]
) -> tuple[list[str], dict[str, Any] | None]:
    """Recompute one plan's cell of a stored attestation (package verifier).

    Returns the problems and the attested cell document of the plan.
    """

    problems: list[str] = []
    if not isinstance(document, Mapping) or document.get("schema") != ATTESTATION_SCHEMA:
        return ["coverage evidence is not a bvl-coverage-attestation-1 document"], None
    try:
        design = DesignContractV1.from_document(document["design"])
        contracts = CoverageContractsV1(
            [PluginCoverageContractV1.from_document(c) for c in document["plugin_contracts"]]
        )
    except (CoverageError, KeyError, TypeError) as error:
        return [f"coverage attestation does not parse: {error}"], None
    plan = PlanIdentity.of_payload(plan_document)
    cell = next(
        (c for c in document.get("cells", []) if c.get("plan") == plan.document()), None
    )
    if cell is None:
        return ["the coverage attestation does not attest the run's plan"], None
    inventory = erf_inventory(
        plan_document, contracts, exclusions=design.exclusions, cell=cell["cell"]
    )
    if inventory.findings:
        problems.append(
            "the run's plan has coverage findings: "
            + "; ".join(f"{f.code}:{f.target}" for f in inventory.findings)
        )
    # compared at rest: canonical-json-1 omits a None-valued entry
    if canonical_bytes(cell["erf"]) != canonical_bytes(
        [item.document() for item in inventory.erf]
    ) or canonical_bytes(cell["excluded"]) != canonical_bytes(
        [item.document() for item in inventory.excluded]
    ):
        problems.append("the attested ERF surface does not recompute from the run's plan")
    if cell["surface_digest"] != _digest(inventory.values()):
        problems.append("the attested surface digest does not recompute")
    if document.get("execution_coverage") != COMPLETE or document.get("findings"):
        problems.append("the attested execution coverage is not COMPLETE")
    cells = {item["cell"]: {e["target"]: e.get("value") for e in item["erf"]}
             for item in document.get("cells", [])}
    if sorted(cells) != sorted(key for key, _ in design.cells()):
        problems.append("the attested cells are not exactly the design's cells")
    else:
        if document["catalog"]["catalog_ref"] != catalog_ref(target_catalog(cells)):
            problems.append("the attested catalog does not recompute from the attested cells")
        edges = [e["edge_id"] for e in document["comparison_set"]["edges"]]
        if edges != [e.edge_id for e in design.comparison_edges()]:
            problems.append("the attested comparison set is not the design's required set")
    return problems, cell


def _read(root: Path, relative: str) -> Any:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def corroboration_problems(
    root: Path, cell: Mapping[str, Any], plan_document: Mapping[str, Any]
) -> list[str]:
    """BVL-COV-011: does the run's evidence show exactly the attested ERF values?

    Corroborates per actor call the profile (model, options, renderer) in the
    persisted request-2 and the reported model, per proposal the parser
    contract, and per decision the rule contract (P09 §13.5).
    """

    root = Path(root)
    values = {item["target"]: item.get("value") for item in cell["erf"]}
    problems: list[str] = []

    def problem(detail: str) -> None:
        problems.append(f"{POST_EXECUTION_CORROBORATION_FAILED}: {detail}")

    nodes = {node["id"]: node for node in plan_document["protocol"]["nodes"]}
    records = [
        json.loads(line)
        for line in (root / "journal-2.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    episodes = {r["episode"]: r for r in records if r["event"] == "EPISODE_OPENED"}
    steps: dict[str, str] = {}
    for episode in episodes:
        for round_index in range(1, planned_rounds(plan_document["protocol"]) + 1):
            for node_id, node in nodes.items():
                kind, digest = episode.split(":", 1)
                step = StepIdentity.of_payload(
                    {
                        "episode": {"kind": kind, "digest": digest},
                        "round": round_index,
                        "node": node_id,
                        "kind": node["kind"],
                    }
                )
                steps[str(step)] = node_id
    returned = {r["call"]: r for r in records if r["event"] == "CALL_RETURNED"}
    for record in records:
        if record["event"] != "CALL_INTENT_RECORDED":
            continue
        node_id = steps.get(record["step"])
        actor = nodes[node_id]["config"].get("actor") if node_id in nodes else None
        if actor is None:
            problem(f"call {record['call']} is not an attested actor-call step")
            continue
        request = _read(root, f"requests-v2/{record['request']['name']}")
        prefix = f"actor.{actor}.profile"
        options = {
            target[len(f"{prefix}.options."):]: value
            for target, value in values.items()
            if target.startswith(f"{prefix}.options.")
        }
        excluded = {
            item["target"][len(f"{prefix}.options."):]
            for item in cell["excluded"]
            if item["target"].startswith(f"{prefix}.options.")
        }
        if request.get("model_identity") != values.get(f"{prefix}.model"):
            problem(f"{actor} request-2 model is not the attested profile model")
        if request.get("renderer_identity") != values.get(f"{prefix}.renderer"):
            problem(f"{actor} request-2 renderer is not the attested renderer")
        consumed = {k: v for k, v in dict(request.get("options") or {}).items()
                    if k not in excluded}
        if consumed != options:
            problem(f"{actor} request-2 options are not the attested profile options")
        response = returned.get(record["call"], {}).get("response", {})
        if response and response.get("model_identity") != values.get(f"{prefix}.model"):
            problem(f"{actor} provider reported a model other than the attested one")
    for role, section, keys in (
        ("proposal", "proposal", ("parser", "on_invalid", "proposal_schema")),
        ("decision", "decision", ("rule", "authority", "candidates", "on_unresolved")),
    ):
        for path in sorted((root / "evidence-v2" / role).glob("*.json")):
            evidence = _read(root, path.relative_to(root).as_posix())
            contract = evidence.get("contract")
            if contract is None:  # pre-contract evidence carries no plan contract
                continue
            node = contract.get("node_id")
            for key in keys:
                if contract.get(key) != values.get(f"{section}.{node}.{key}"):
                    problem(f"{role} of {node!r} ran with a {key} other than the attested one")
            config = {
                target.rsplit(".", 1)[1]: value
                for target, value in values.items()
                if target.startswith(f"{section}.{node}.config.")
            }
            excluded = {
                item["target"].rsplit(".", 1)[1]
                for item in cell["excluded"]
                if item["target"].startswith(f"{section}.{node}.config.")
            }
            consumed = {k: v for k, v in contract.get("config", {}).items() if k not in excluded}
            if consumed != config:
                problem(f"{role} of {node!r} consumed config outside the attested ERFs")
    return problems
