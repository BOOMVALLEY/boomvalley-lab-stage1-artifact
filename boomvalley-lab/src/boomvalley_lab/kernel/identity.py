"""K0 identities for generalized organizational execution.

The critical design rule is acyclicity:

    semantic plan
        -> PlanIdentity
        -> validation / gate artifacts
        -> AuthorizationIdentity
        -> runtime lineage

Build and plugin code bindings are deliberately outside PlanIdentity.  A
patch-level software change must not redefine the scientific experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from boomvalley_lab.identity.kinds import DigestIdentity


@dataclass(frozen=True)
class _KernelIdentity(DigestIdentity):
    """Base class for K0 digest identities."""

    SCHEMA: ClassVar[str] = ""

    @classmethod
    def of_payload(cls, payload: Any) -> _KernelIdentity:
        return cls.of_document({"schema": cls.SCHEMA, "payload": payload})


@dataclass(frozen=True)
class PlanIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "plan"
    IDENTIFIES: ClassVar[str] = "the normalized scientific execution semantics"
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "build",
        "plugin code",
        "gate",
        "authorization",
    )
    SCHEMA: ClassVar[str] = "bvl-plan-identity-1"


@dataclass(frozen=True)
class ProtocolDagIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "protocol_dag"
    IDENTIFIES: ClassVar[str] = (
        "the intra-episode causal order: typed protocol nodes, dependency edges, round bound"
    )
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "plan",
        "experiment_schedule",
        "step serialization",
        "journal position",
    )
    SCHEMA: ClassVar[str] = "bvl-protocol-dag-identity-1"


@dataclass(frozen=True)
class ExperimentScheduleIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "experiment_schedule"
    IDENTIFIES: ClassVar[str] = "the experimental schedule order: a run's ordered episode keys"
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("protocol_dag", "episode", "plan")
    SCHEMA: ClassVar[str] = "bvl-experiment-schedule-identity-1"


@dataclass(frozen=True)
class RoleIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "role"
    IDENTIFIES: ClassVar[str] = "one declared organizational role"
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("actor", "decision authority")
    SCHEMA: ClassVar[str] = "bvl-role-identity-1"


@dataclass(frozen=True)
class ActorIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "actor"
    IDENTIFIES: ClassVar[str] = "one declared organizational participant (actor id x role)"
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "factor level",
        "declaration position",
        "execution_profile",
        "call",
    )
    SCHEMA: ClassVar[str] = "bvl-actor-identity-1"


@dataclass(frozen=True)
class ExecutionProfileIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "execution_profile"
    IDENTIFIES: ClassVar[str] = "how an actor is executed: provider/model/options/seed/renderer"
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("actor", "role", "build")
    SCHEMA: ClassVar[str] = "bvl-execution-profile-identity-1"


@dataclass(frozen=True)
class BuildIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "build"
    IDENTIFIES: ClassVar[str] = "one installed BVL product build"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "plugin_set")
    SCHEMA: ClassVar[str] = "bvl-build-identity-1"


@dataclass(frozen=True)
class PluginSetIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "plugin_set"
    IDENTIFIES: ClassVar[str] = "the executable scientific plugin set bound to a plan"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("build", "plan")
    SCHEMA: ClassVar[str] = "bvl-plugin-set-identity-1"


@dataclass(frozen=True)
class CoverageAttestationIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "coverage_attestation"
    IDENTIFIES: ClassVar[str] = "one plan-derived execution/analysis coverage attestation"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "gate")
    SCHEMA: ClassVar[str] = "bvl-coverage-attestation-identity-1"


@dataclass(frozen=True)
class GNDCRWResultSetIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "gndcrw_result_set"
    IDENTIFIES: ClassVar[str] = "the bound set of GNDCRW preflight results"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("coverage_attestation", "gate")
    SCHEMA: ClassVar[str] = "bvl-gndcrw-result-set-identity-1"


@dataclass(frozen=True)
class GateDecisionIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "gate_decision"
    IDENTIFIES: ClassVar[str] = "one gate-2 authorization decision"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "authorization")
    SCHEMA: ClassVar[str] = "bvl-gate-decision-identity-1"


@dataclass(frozen=True)
class ExecutionBindingIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "execution_binding"
    IDENTIFIES: ClassVar[str] = "one PlanIdentity bound to one executable build/plugin set"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "authorization")
    SCHEMA: ClassVar[str] = "bvl-execution-binding-identity-1"


@dataclass(frozen=True)
class AuthorizationIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "authorization"
    IDENTIFIES: ClassVar[str] = "one validated authorization for one plan and binding"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "execution_binding")
    SCHEMA: ClassVar[str] = "bvl-authorization-identity-1"


@dataclass(frozen=True)
class EpisodeIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "episode"
    IDENTIFIES: ClassVar[str] = "one planned organizational decision unit"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("call", "step")
    SCHEMA: ClassVar[str] = "bvl-episode-identity-1"


@dataclass(frozen=True)
class StepIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "step"
    IDENTIFIES: ClassVar[str] = "one protocol step inside one episode"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("episode", "call")
    SCHEMA: ClassVar[str] = "bvl-step-identity-1"


@dataclass(frozen=True)
class CallIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "call"
    IDENTIFIES: ClassVar[str] = "one engine-owned actor/provider call"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("episode", "step")
    SCHEMA: ClassVar[str] = "bvl-call-identity-1"


@dataclass(frozen=True)
class CustodyEntryIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "custody_entry"
    IDENTIFIES: ClassVar[str] = "one accepted actor-call evidence chain"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("call", "artifact")
    SCHEMA: ClassVar[str] = "bvl-custody-entry-identity-2"


@dataclass(frozen=True)
class ProposalIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "proposal"
    IDENTIFIES: ClassVar[str] = "one typed proposal derived from one actor response"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("decision", "response")
    SCHEMA: ClassVar[str] = "bvl-proposal-identity-1"


@dataclass(frozen=True)
class DecisionArtifactIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "decision"
    IDENTIFIES: ClassVar[str] = "one authoritative decision derived from typed proposals"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("proposal", "world_transition")
    SCHEMA: ClassVar[str] = "bvl-decision-identity-1"


@dataclass(frozen=True)
class WorldStateIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "world_state"
    IDENTIFIES: ClassVar[str] = "one canonical domain World state"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("world_transition",)
    SCHEMA: ClassVar[str] = "bvl-world-state-identity-1"
    #: P15 (T3-001): a state under a declared World state schema.  identity-1
    #: (a bare state payload) keeps its meaning; the two never share a preimage.
    VERSIONED_SCHEMA: ClassVar[str] = "bvl-world-state-identity-2"

    @classmethod
    def of_versioned(cls, *, state_schema: str, state: Any) -> WorldStateIdentity:
        """The identity of *state* as one state of the schema ``id:version``."""

        return cls.of_document(
            {
                "schema": cls.VERSIONED_SCHEMA,
                "payload": {"state_schema": state_schema, "state": state},
            }
        )


@dataclass(frozen=True)
class WorldTransitionIntentIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "world_transition_intent"
    IDENTIFIES: ClassVar[str] = "one engine-authorized intent to apply a World action"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("world_transition", "world_state")
    SCHEMA: ClassVar[str] = "bvl-world-transition-intent-identity-1"


@dataclass(frozen=True)
class WorldTransitionIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "world_transition"
    IDENTIFIES: ClassVar[str] = "one evidenced World transition"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("world_state", "decision")
    SCHEMA: ClassVar[str] = "bvl-world-transition-identity-1"


@dataclass(frozen=True)
class TerminationRuleIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "termination_rule"
    IDENTIFIES: ClassVar[str] = "one registered round termination rule and its frozen config"
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "termination verdict", "round")
    SCHEMA: ClassVar[str] = "bvl-termination-rule-identity-1"


@dataclass(frozen=True)
class RoundIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "round"
    IDENTIFIES: ClassVar[str] = (
        "one round of one episode: episode, round index and the World state it opens on"
    )
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("episode", "step", "world_state")
    SCHEMA: ClassVar[str] = "bvl-round-identity-1"


@dataclass(frozen=True)
class EvidenceManifestIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "evidence_manifest"
    IDENTIFIES: ClassVar[str] = "one manifest-4 evidence package membership statement"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("plan", "dataset")
    SCHEMA: ClassVar[str] = "bvl-evidence-manifest-identity-1"


@dataclass(frozen=True)
class MemoryArtifactIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "memory_artifact"
    IDENTIFIES: ClassVar[str] = "one explicit organizational memory artifact"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("world_state",)
    SCHEMA: ClassVar[str] = "bvl-memory-artifact-identity-1"


def execution_binding_identity(
    plan: PlanIdentity,
    *,
    build_identity: BuildIdentity,
    plugin_set_identity: PluginSetIdentity,
) -> ExecutionBindingIdentity:
    """Bind semantic plan to executable software without changing PlanIdentity."""

    return ExecutionBindingIdentity.of_payload(
        {
            "plan": plan.document(),
            "build_identity": build_identity.document(),
            "plugin_set_identity": plugin_set_identity.document(),
        }
    )


def authorization_identity(
    plan: PlanIdentity,
    binding: ExecutionBindingIdentity,
    *,
    coverage_identity: CoverageAttestationIdentity,
    gndcrw_result_set_identity: GNDCRWResultSetIdentity,
    gate_identity: GateDecisionIdentity,
) -> AuthorizationIdentity:
    """The terminal pre-execution authorization identity (K0 / EII-3 shape)."""

    return AuthorizationIdentity.of_payload(
        {
            "plan": plan.document(),
            "binding": binding.document(),
            "coverage_identity": coverage_identity.document(),
            "gndcrw_result_set_identity": gndcrw_result_set_identity.document(),
            "gate_identity": gate_identity.document(),
        }
    )
