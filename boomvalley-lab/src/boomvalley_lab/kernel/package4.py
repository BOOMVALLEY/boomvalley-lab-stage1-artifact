"""Complete, verifiable manifest-4 CONFORMANCE packages (T0-014).

A K0 run directory becomes a package only after everything in it re-derives
from durable evidence and the one Protocol IR the run executed:

    gate-2 authorization (T0-012) + execution binding (T0-013)
    -> plan evidence recomputes the authorized PlanIdentity and parses back
       into exactly one ``bvl-protocol-ir-1`` ProtocolIR
    -> every EPISODE_OPENED recomputes its EpisodeIdentity from
       plan x authorization x episode_key
    -> the journaled steps are exactly the IR's steps (rounds x topological
       order; StepIdentity recomputed), every step carries exactly the commit
       event its node kind prescribes, and every dependency edge of the IR is
       the evidence lineage (call -> proposal -> decision -> World -> memory)
    -> every EPISODE_OPENED names the IR's ProtocolDagIdentity (intra-episode
       causal order) and its place in one ExperimentScheduleV1 (experimental
       schedule order): episodes open as the schedule's prefix (T2-004)
    -> call custody and World transitions reconcile
    -> a P09-ERF coverage attestation (role ``coverage``, T1-006), when the
       gate decided on one: it recomputes the run's plan cell, its catalog and
       comparison set, is COMPLETE, and the run's request / profile / parser /
       decision evidence corroborates the attested ERF values (BVL-COV-011)
    -> a GNDCRW comparison result set (role ``gndcrw_results``, T1-007), when
       the strict gate bound one: it is the gate's result set and re-binds one
       RUN result per required edge against the stored attestation
    -> L1 call bindings (role ``call_binding``, T1-008), when the run's call
       intents name them: exactly one per accepted call, each recomputing its
       CallIdentity, plan actor / role / profile identities, request-2 and
       default-deny access trace (``kernel/l1_evidence.py``)
    -> conformance attestation (role ``conformance_attestation``): the derived
       coverage, counts and limitations, written as evidence
    -> L1 dataset units (role ``dataset_units``, T1-008) of an L1 run: the
       calls / proposals / decisions / eligibility tables re-derived from the
       evidence above, byte-identical to the stored member
    -> the bound analysis (role ``analysis_output``, T1-009) of a plan-6 L1
       run: the plan's AnalysisContractV1 recomputed over the eligible units
       of the re-derived dataset only, byte-identical to the stored member
       (``kernel/bound_analysis.py``)
    -> MANIFEST-4.json lists exactly the reconciled members.

``verify_package_v4`` re-derives all of it independently of the builder: the
attestation must be byte-identical to a fresh derivation, the member list must
be exactly what reconciliation collects, and no file may sit in the package
unlisted.  Study-specific code is never consulted; the IR is the only source
of expected structure, so one verifier covers every study the IR expresses.

CONFORMANCE packages are not scientific evidence.  SCIENTIFIC packages are
refused until gate-2 inputs are derived (BVL-REC-102) and the engine resolves
handlers through the bound plugin set (BVL-REC-104).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes, canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import BoomvalleyError, DeclarationError, EvidenceError
from boomvalley_lab.core.strict_json import load_bytes
from boomvalley_lab.kernel.actors import ActorBindingSetV1
from boomvalley_lab.kernel.authorization import reconcile_authorization_v2
from boomvalley_lab.kernel.bound_analysis import (
    ANALYSIS_CHECK,
    ANALYSIS_ROLE,
    AnalysisContractV1,
    analysis_document,
)
from boomvalley_lab.kernel.comparison import stored_result_set_problems
from boomvalley_lab.kernel.coverage import attested_cell_problems, corroboration_problems
from boomvalley_lab.kernel.custody2 import read_intent_request_v2, reconcile_custody_v2
from boomvalley_lab.kernel.decisions import (
    EVIDENCE_FIELDS_V1 as DECISION_FIELDS_V1,
)
from boomvalley_lab.kernel.decisions import (
    EVIDENCE_FIELDS_V2 as DECISION_FIELDS_V2,
)
from boomvalley_lab.kernel.decisions import (
    EVIDENCE_SCHEMA_V1 as DECISION_SCHEMA_V1,
)
from boomvalley_lab.kernel.decisions import (
    EVIDENCE_SCHEMA_V2 as DECISION_SCHEMA_V2,
)
from boomvalley_lab.kernel.decisions import (
    DecisionContractSetV1,
    committed_decision_problems,
)
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentRefV2,
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.engine import (
    SEMANTIC_PLAN_SCHEMA_V1,
    SEMANTIC_PLAN_SCHEMA_V2,
    SEMANTIC_PLAN_SCHEMA_V3,
    SEMANTIC_PLAN_SCHEMA_V4,
    SEMANTIC_PLAN_SCHEMA_V5,
    SEMANTIC_PLAN_SCHEMA_V6,
    SEMANTIC_PLAN_SCHEMA_V7,
    SEMANTIC_PLAN_SCHEMA_V8,
    SEMANTIC_PLAN_SCHEMA_V9,
    SEMANTIC_PLAN_SCHEMA_V10,
    require_planned_actors,
    require_world_contract,
)
from boomvalley_lab.kernel.gate import identity_from_document
from boomvalley_lab.kernel.human import HumanActorContractSetV1, require_no_uncontracted_human
from boomvalley_lab.kernel.identity import (
    CoverageAttestationIdentity,
    DecisionArtifactIdentity,
    EpisodeIdentity,
    GNDCRWResultSetIdentity,
    MemoryArtifactIdentity,
    PlanIdentity,
    ProposalIdentity,
    StepIdentity,
)
from boomvalley_lab.kernel.information import InformationAccessSetV1
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_OUTCOME_UNKNOWN,
    CALL_RETURNED,
    CUSTODY_ACCEPTED,
    DECISION_FAILED,
    DECISION_RECORDED,
    EPISODE_COMPLETED,
    EPISODE_FAILED,
    EPISODE_OPENED,
    HUMAN_RESPONSE_RECEIVED,
    MEMORY_RECORDED,
    PRE_TRANSPORT_REFUSED,
    PROPOSAL_PARSE_FAILED,
    PROPOSAL_PARSED,
    RESPONSE_REJECTED,
    ROUND_COMPLETED,
    RUN_ABORTED,
    RUN_OPENED,
    STEP_READY,
    TOOL_INTENT_RECORDED,
    TOOL_RECONCILED,
    TOOL_RETURNED,
    WORLD_APPLIED,
    WORLD_INTENT_RECORDED,
    WORLD_OUTCOME_UNKNOWN,
    Journal2,
)
from boomvalley_lab.kernel.l1_evidence import (
    L1_CALL_CHECK,
    L1_ROLES,
    NOT_ATTESTED,
    NOT_BOUND,
    call_binding_problems,
    dataset_document,
    eligibility_row,
)
from boomvalley_lab.kernel.manifest4 import (
    ROLES,
    ManifestV4,
    collect_manifest4_members,
    read_manifest4,
    write_manifest4,
)
from boomvalley_lab.kernel.memory import (
    MEMORY_ARTIFACT_SCHEMA_V1,
    MEMORY_ARTIFACT_SCHEMA_V2,
    MEMORY_ARTIFACT_SCHEMA_V3,
    MEMORY_CHECK,
    MEMORY_FIELDS_V1,
    MEMORY_FIELDS_V2,
    MEMORY_FIELDS_V3,
    REGIME_RESET,
    SCOPE_CROSS_EPISODE,
    EpisodeMemoryV1,
    artifact_problems,
    held,
    memory_policies,
    require_carry_schedule,
    source_view,
)
from boomvalley_lab.kernel.proposals import (
    EVIDENCE_FIELDS_V1,
    EVIDENCE_FIELDS_V2,
    EVIDENCE_SCHEMA_V1,
    EVIDENCE_SCHEMA_V2,
    ProposalContractSetV1,
    committed_proposal_problems,
)
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.readiness import COMMIT_EVENT
from boomvalley_lab.kernel.request_store import RequestStoreV2
from boomvalley_lab.kernel.rounds import round_problems, state_key
from boomvalley_lab.kernel.schedule import protocol_dag_identity, schedule_problems
from boomvalley_lab.kernel.seed import SeedDerivation
from boomvalley_lab.kernel.strict_gate import STRICT_GATE_POLICY
from boomvalley_lab.kernel.tool import ToolActorContractSetV1, require_no_uncontracted_tool
from boomvalley_lab.kernel.world import WorldContractV1, state_identity

ATTESTATION_SCHEMA = "boomvalley-lab-conformance-attestation-1"
PLAN_EVIDENCE_SCHEMA = "boomvalley-lab-plan-evidence-1"
SEMANTIC_PLAN_SCHEMA = SEMANTIC_PLAN_SCHEMA_V1
_PLAN_KEYS = frozenset(
    {"schema", "experiment_id", "protocol", "initial_world_state", "initial_memory"}
)
# plan-2 (T1-001) adds the resolved P04 actor bindings; spike-1 keeps its meaning.
# Each schema names its allowed closed key sets.
SEMANTIC_PLAN_SHAPES = {
    SEMANTIC_PLAN_SCHEMA_V1: (_PLAN_KEYS,),
    SEMANTIC_PLAN_SCHEMA_V2: (_PLAN_KEYS | {"actors"},),
    # plan-3 (T1-002) adds the resolved P05 default-deny information access
    SEMANTIC_PLAN_SCHEMA_V3: (_PLAN_KEYS | {"actors", "information"},),
    # plan-4 (T1-004) adds the P06 proposal contracts, information optional
    SEMANTIC_PLAN_SCHEMA_V4: (
        _PLAN_KEYS | {"actors", "proposals"},
        _PLAN_KEYS | {"actors", "information", "proposals"},
    ),
    # plan-5 (T1-005) adds the P07 decision contracts over plan-4
    SEMANTIC_PLAN_SCHEMA_V5: (
        _PLAN_KEYS | {"actors", "proposals", "decisions"},
        _PLAN_KEYS | {"actors", "information", "proposals", "decisions"},
    ),
}
# plan-6 (T1-009) pre-binds the official analysis over any actor plan (2..5)
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_V6] = tuple(
    shape | {"analysis"}
    for schema in (SEMANTIC_PLAN_SCHEMA_V2, SEMANTIC_PLAN_SCHEMA_V3,
                   SEMANTIC_PLAN_SCHEMA_V4, SEMANTIC_PLAN_SCHEMA_V5)
    for shape in SEMANTIC_PLAN_SHAPES[schema]
)
# plan-7 (T1-012) binds the K0 seed tree over any actor plan (2..6)
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_V7] = tuple(
    shape | {"seed"}
    for schema in (SEMANTIC_PLAN_SCHEMA_V2, SEMANTIC_PLAN_SCHEMA_V3, SEMANTIC_PLAN_SCHEMA_V4,
                   SEMANTIC_PLAN_SCHEMA_V5, SEMANTIC_PLAN_SCHEMA_V6)
    for shape in SEMANTIC_PLAN_SHAPES[schema]
)
# plan-8 (T3-001) freezes the World contract over a seeded plan (7)
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_V8] = tuple(
    shape | {"world"} for shape in SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_V7]
)
# plan-9 (T5-001) freezes the P17 human actor contracts over a seeded plan (7, 8)
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_V9] = tuple(
    shape | {"humans"}
    for schema in (SEMANTIC_PLAN_SCHEMA_V7, SEMANTIC_PLAN_SCHEMA_V8)
    for shape in SEMANTIC_PLAN_SHAPES[schema]
)
# plan-10 (T5-003) freezes the P17 tool actor contracts over a seeded plan (7, 8, 9)
SEMANTIC_PLAN_SHAPES[SEMANTIC_PLAN_SCHEMA_V10] = tuple(
    shape | {"tools"}
    for schema in (SEMANTIC_PLAN_SCHEMA_V7, SEMANTIC_PLAN_SCHEMA_V8, SEMANTIC_PLAN_SCHEMA_V9)
    for shape in SEMANTIC_PLAN_SHAPES[schema]
)
PROPOSAL_FIELDS = {EVIDENCE_SCHEMA_V1: EVIDENCE_FIELDS_V1, EVIDENCE_SCHEMA_V2: EVIDENCE_FIELDS_V2}
DECISION_FIELDS = {DECISION_SCHEMA_V1: DECISION_FIELDS_V1, DECISION_SCHEMA_V2: DECISION_FIELDS_V2}
MANIFEST_NAME = "MANIFEST-4.json"

# Every CONFORMANCE package states what it is not.
CONFORMANCE_LIMITATIONS = (
    "CONFORMANCE_PACKAGE_NOT_SCIENTIFIC_EVIDENCE",
    "FULLMT_MANIFEST4_SPIKE_READER_REQUIRED",
    "GATE2_INPUTS_SUPPLIED_NOT_DERIVED",
    "PLUGIN_SET_NOT_ENGINE_RESOLVED",
)

_COMMIT_EVENTS = frozenset(COMMIT_EVENT.values())

# Evidence roles the IR's node kinds require, beyond the run-level roles.
BASE_ROLES = frozenset(
    {"plan", "execution_binding", "gate", "episode_lineage", "conformance_attestation"}
)
KIND_ROLES: dict[NodeKind, frozenset[str]] = {
    NodeKind.ACTOR_CALL: frozenset({"request", "response", "custody"}),
    NodeKind.PROPOSAL_PARSE: frozenset({"proposal"}),
    NodeKind.DECISION: frozenset({"decision"}),
    NodeKind.WORLD_TRANSITION: frozenset({"world_transition", "world_state"}),
    NodeKind.MEMORY_UPDATE: frozenset({"memory"}),
    NodeKind.TERMINATION: frozenset(),
}

# A conformance run has no refused, unknown, rejected, failed or aborted step.
_NON_CONFORMANT_EVENTS = frozenset(
    {
        PRE_TRANSPORT_REFUSED,
        CALL_OUTCOME_UNKNOWN,
        RESPONSE_REJECTED,
        PROPOSAL_PARSE_FAILED,
        DECISION_FAILED,
        WORLD_OUTCOME_UNKNOWN,
        EPISODE_FAILED,
        RUN_ABORTED,
    }
)

CHECKS = (
    "authorization_reconciled",
    "plan_recomputes_and_parses_to_protocol_ir",
    "episode_identities_recompute",
    "protocol_dag_and_schedule_order_separate",
    "step_coverage_equals_protocol_ir",
    "one_commit_event_per_step_by_node_kind",
    "ir_dependency_edges_are_evidence_lineage",
    "artifact_identities_recompute",
    "custody_reconciled",
    "world_transitions_reconciled",
)
# Added to CHECKS only for a run whose gate-2 decided on a P09-ERF attestation,
# so historical attestations re-derive byte-identically.
COVERAGE_CHECK = "erf_coverage_recomputes_and_is_corroborated"
# Added only for a plan with a P16 round contract (T4-001, bvl-protocol-ir-2).
ROUND_CHECK = "round_contract_terminates_as_planned"
# T4-005 adds ``kernel.state_chain.STATE_CHAIN_CHECK`` for a plan with a round
# contract and a World contract: its attestation states every episode's chain head.
# Added only for a run whose strict gate-2 bound a GNDCRW result set (T1-007).
GNDCRW_CHECK = "gndcrw_comparison_set_bound_and_run"


class PackageRefusedV4(EvidenceError):
    """The run directory cannot be packaged; ``problems`` says why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("manifest-4 package refused: " + "; ".join(problems))
        self.problems = tuple(problems)


def _key(document: Any) -> str:
    """``{"kind", "digest"}`` -> the ``kind:digest`` string journal-2 uses."""

    if not isinstance(document, Mapping) or set(document) != {"kind", "digest"}:
        raise EvidenceError(f"not an identity document: {document!r}")
    return f"{document['kind']}:{document['digest']}"


def required_roles_v4(protocol: ProtocolIR) -> frozenset[str]:
    """The evidence roles a complete package of *protocol* must contain."""

    roles = set(BASE_ROLES)
    for node in protocol.nodes:
        roles |= KIND_ROLES[node.kind]
    return frozenset(roles)


def _read_role(root: Path, role: str) -> list[tuple[EvidenceDocumentRefV2, Any]]:
    store = EvidenceDocumentStoreV2(root)
    documents = []
    for path in sorted((root / "evidence-v2" / role).glob("*.json")):
        ref = EvidenceDocumentRefV2(
            role,
            path.relative_to(root).as_posix(),
            f"sha256:{path.stem}",
            path.stat().st_size,
        )
        documents.append((ref, store.read(ref)))
    return documents


# The exchange evidence a journal-2 record of a human or tool actor names
# (T5-002, T5-003): event -> (record member, evidence role).
_EXCHANGE_EVIDENCE = (
    (CALL_INTENT_RECORDED, "human_intent", "human_intent"),
    (HUMAN_RESPONSE_RECEIVED, "human_response", "human_response"),
    (TOOL_INTENT_RECORDED, "evidence", "tool_intent"),
    (TOOL_RETURNED, "evidence", "tool_result"),
    (TOOL_RECONCILED, "evidence", "tool_result"),
)


# The roles whose every member ``_derive`` reads itself: each is checked against the
# plan, the authorization, the journal or the World / custody reconciliation, and a
# member of one that belongs to none of them is refused there.  A member of any other
# role is evidence only when a journal-2 record names it (SV-06).
_DERIVED_ROLES = frozenset(
    {
        "plan",
        "execution_binding",
        "gate",
        "coverage",
        "gndcrw_results",
        "proposal",
        "decision",
        "memory",
        "world_transition",
        "world_state",
        "call_binding",
        "conformance_attestation",
        "dataset_units",
        "analysis_output",
    }
)


def _exchange_evidence_problems(root: Path, records: list[dict]) -> list[str]:
    """Every human / tool exchange document the journal names is held and reads (SV-04).

    What a person or a tool was asked and what they answered is evidence the
    journal names by content address.  Its content is the call provenance's to
    recompute (``call_provenance.py``); that it is there, unchanged and
    canonical is the package's: a package does not verify over a named member
    that is missing, cut or overwritten.
    """

    store = EvidenceDocumentStoreV2(root)
    problems: list[str] = []
    seen: set[str] = set()

    def held(named: Any, role: str, sequence: int) -> Any:
        try:
            ref = evidence_ref_from_document(named, role)
            if ref.path in seen:
                return None
            seen.add(ref.path)
            return store.read(ref)
        except (BoomvalleyError, OSError) as error:
            problems.append(f"{role} evidence named by journal-2 #{sequence} does not read: "
                            f"{error}")
            return None

    for record in records:
        for event, member, role in _EXCHANGE_EVIDENCE:
            if record["event"] != event or member not in record:
                continue
            document = held(record[member], role, record["sequence"])
            if role == "human_intent" and document is not None:
                # the consent the person was asked under is named by the intent
                consent = document.get("consent") if isinstance(document, Mapping) else None
                held(consent, "human_consent", record["sequence"])
    # SV-06 (SV-03 M-02): the collector seals every file of a registered role directory
    # and every ``requests-v2`` member.  One that no record names was reached by no
    # check above: it is not this run's evidence, whatever its bytes are
    for role in sorted(ROLES - _DERIVED_ROLES):
        for path in sorted((root / "evidence-v2" / role).glob("*.json")):
            relative = path.relative_to(root).as_posix()
            if relative not in seen:
                problems.append(f"{relative} is {role} evidence no journal-2 record names")
    requested = {
        record["request"].get("name")
        for record in records
        if record["event"] == CALL_INTENT_RECORDED and isinstance(record.get("request"), Mapping)
    }
    for path in sorted((root / "requests-v2").glob("request-*.json")):
        if path.name not in requested:
            problems.append(f"requests-v2/{path.name} is the request of no journaled call intent")
    return problems


#: SV-11: the events that place a step in its round: it is ready, and it committed
_STEP_PLACING = frozenset({
    STEP_READY, CUSTODY_ACCEPTED, PROPOSAL_PARSED, DECISION_RECORDED, WORLD_APPLIED,
    MEMORY_RECORDED,
})

#: SV-11: the members a commit event restates of its artifact, by evidence role
_RESTATED = {
    "proposal": ("parser", "value", "verdict"),
    "decision": ("rule", "outcome", "selected_proposal", "supporting_proposals",
                 "requested_action"),
    "memory": ("owner", "key", "value"),
}


def _restates(stated: Any, role: str, document: Mapping[str, Any], node: Any) -> bool:
    """Whether a commit event's summary is exactly what its evidence document says.

    The journal names a proposal, a decision and a memory artifact by identity
    and restates some of their members beside it (the value, the verdict, the
    action, the owner).  The identity is of the document; the restatement is
    held to it here, member for member and by canonical bytes, so ``15`` is not
    ``15.0`` and a member the document does not state is not restated.
    """

    if not isinstance(stated, Mapping):
        return False
    expected = {name: document[name] for name in _RESTATED[role] if name in document}
    if role == "proposal" and isinstance(document.get("contract"), Mapping):
        schema = document["contract"].get("proposal_schema")
        expected["schema"] = schema.get("schema_id") if isinstance(schema, Mapping) else None
    if role == "memory":
        # memory-artifact-1 does not state its key: it is the plan node's
        expected.setdefault("key", node.config.get("key"))
    try:
        return canonical_bytes(
            {name: value for name, value in stated.items() if name != "identity"}
        ) == canonical_bytes(expected)
    except (BoomvalleyError, TypeError, ValueError):
        return False


@dataclass
class _Step:
    episode: str
    round: int
    node_id: str
    kind: NodeKind
    ready_sequence: int
    output: str | None = None


def _plan(root: Path, plan: PlanIdentity, problems: list[str]):
    plans = _read_role(root, "plan")
    if len(plans) != 1:
        problems.append(f"expected exactly one plan evidence member, found {len(plans)}")
        return None, None
    ref, document = plans[0]
    if (
        not isinstance(document, Mapping)
        or set(document) != {"schema", "identity", "plan"}
        or document["schema"] != PLAN_EVIDENCE_SCHEMA
    ):
        problems.append("plan evidence has the wrong closed shape")
        return None, None
    semantic = document["plan"]
    if PlanIdentity.of_payload(semantic) != plan or document["identity"] != plan.document():
        problems.append("plan evidence does not recompute the authorized PlanIdentity")
        return None, None
    if (
        not isinstance(semantic, Mapping)
        or semantic.get("schema") not in SEMANTIC_PLAN_SHAPES
        or set(semantic) not in SEMANTIC_PLAN_SHAPES[semantic["schema"]]
    ):
        problems.append("semantic plan has the wrong closed shape")
        return None, None
    try:
        protocol = ProtocolIR.from_document(semantic["protocol"])
    except DeclarationError as error:
        problems.append(f"plan protocol is not a Protocol IR: {error}")
        return None, None
    actors = information = None
    if "actors" in semantic:
        try:
            # every planned actor call names an actor bound in the frozen plan
            actors = ActorBindingSetV1.from_document(semantic["actors"])
            require_planned_actors(protocol, actors)
        except DeclarationError as error:
            problems.append(f"plan actors are not a P04 actor binding set: {error}")
            return None, None
        if "information" in semantic:
            try:
                # access is resolved for exactly the plan's actors
                information = InformationAccessSetV1.from_document(semantic["information"])
                information.require_actors(actors)
                information.require_protocol(protocol)  # P13 visibility (T2-001)
            except DeclarationError as error:
                problems.append(f"plan information is not a P05 access set: {error}")
                return None, None
    proposals = None
    if "proposals" in semantic:
        try:
            # exactly the IR's proposal_parse nodes carry one frozen P06 contract
            proposals = ProposalContractSetV1.from_document(semantic["proposals"])
            proposals.require_protocol(protocol)
        except DeclarationError as error:
            problems.append(f"plan proposals are not a P06 contract set: {error}")
            return None, None
    decisions = None
    if "decisions" in semantic:
        try:
            # every decision node carries one frozen P07 contract whose
            # authority re-derives from the IR, the actors and the P06 contracts
            decisions = DecisionContractSetV1.from_document(semantic["decisions"])
            decisions.require_protocol(protocol, actors, proposals)
        except DeclarationError as error:
            problems.append(f"plan decisions are not a P07 contract set: {error}")
            return None, None
    analysis = None
    if "analysis" in semantic:
        try:
            analysis = AnalysisContractV1.from_document(semantic["analysis"])
        except DeclarationError as error:
            problems.append(f"plan analysis is not an analysis contract: {error}")
            return None, None
    if "seed" in semantic:
        try:
            SeedDerivation.from_document(semantic["seed"])
        except (TypeError, ValueError) as error:
            problems.append(f"plan seed is not a K0 seed tree: {error}")
            return None, None
    if "world" in semantic:
        try:
            # the one World of the plan, on an initial state of its schema version
            require_world_contract(
                protocol,
                WorldContractV1.from_document(semantic["world"]),
                semantic["initial_world_state"],
                SeedDerivation.from_document(semantic["seed"]),
            )
        except DeclarationError as error:
            problems.append(f"plan world is not a P15 World contract: {error}")
            return None, None
    try:
        # exactly the contracted actors are on a human profile (T5-001)
        if "humans" in semantic:
            HumanActorContractSetV1.from_document(semantic["humans"]).require_actors(actors)
        else:
            require_no_uncontracted_human(actors, None)
    except DeclarationError as error:
        problems.append(f"plan humans are not a P17 human actor contract set: {error}")
        return None, None
    try:
        # exactly the contracted actors are on a tool profile (T5-003)
        if "tools" in semantic:
            ToolActorContractSetV1.from_document(semantic["tools"]).require_actors(actors)
        else:
            require_no_uncontracted_tool(actors, None)
    except DeclarationError as error:
        problems.append(f"plan tools are not a P17 tool actor contract set: {error}")
        return None, None
    return ref, (semantic, protocol, proposals, decisions, actors, information, analysis)


def derive_conformance_attestation_v4(root: Path) -> dict[str, Any]:
    """Re-derive the run's conformance attestation, or raise PackageRefusedV4.

    Malformed evidence of any shape fails closed as a refusal.
    """

    return _derive_state(root)[0]


def _derive_state(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _derive(Path(root))
    except PackageRefusedV4:
        raise
    except (BoomvalleyError, OSError, KeyError, TypeError, AttributeError, ValueError) as error:
        reason = f"evidence is malformed: {type(error).__name__}: {error}"
        raise PackageRefusedV4([reason]) from error


def _derive(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    problems: list[str] = []

    authorization_state = reconcile_authorization_v2(root)
    if authorization_state.refused:
        raise PackageRefusedV4(["a gate-2 REFUSED run has no CONFORMANCE package"])
    authorization = authorization_state.authorization
    if not authorization_state.complete or authorization is None:
        raise PackageRefusedV4(
            ["no verified gate-2 authorization", *authorization_state.problems]
        )
    journal = Journal2(root)
    if journal.torn_tail():
        raise PackageRefusedV4(["journal-2 has a torn tail"])
    records = journal.read()

    plan_ref, parsed = _plan(root, authorization.plan, problems)
    if parsed is None:
        raise PackageRefusedV4(problems)
    semantic, protocol, proposals, decisions, actors, information, analysis = parsed
    order = [protocol.node(node_id) for node_id in protocol.topological_order()]
    # the state every episode opens on (the first round's pre-state, T4-001)
    state_schema = (
        WorldContractV1.from_document(semantic["world"]).state_schema.ref
        if "world" in semantic
        else None
    )
    initial_state = state_identity(semantic["initial_world_state"], state_schema).document()
    # T4-002: a timed state rule is re-derived on the evidenced state it read;
    # every state is looked up by the identity its own content recomputes to
    evidenced_states: dict[str, Any] = {state_key(initial_state): semantic["initial_world_state"]}
    if protocol.round is not None and protocol.round.termination.observes_state:
        for _, kept in _read_role(root, "world_state"):
            if isinstance(kept, Mapping) and isinstance(kept.get("state"), Mapping):
                evidenced_states[
                    state_key(state_identity(kept["state"], state_schema).document())
                ] = kept["state"]

    for record in records:
        if record["event"] in _NON_CONFORMANT_EVENTS:
            problems.append(f"journal-2 #{record['sequence']} is {record['event']}")
        if record["event"] == RUN_OPENED and record["sequence"] != 0:
            problems.append("RUN_OPENED appears after journal-2 position 0")

    # Episodes: recomputed identities and IR step coverage.
    steps: dict[str, _Step] = {}
    episodes: list[dict[str, Any]] = []
    opened = [record for record in records if record["event"] == EPISODE_OPENED]
    if not opened:
        problems.append("the run executed no episode")
    keys = [record["episode_key"] for record in opened]
    if len(keys) != len(set(keys)):
        problems.append("an episode_key is opened twice")
    for record in opened:
        episode_str = record["episode"]
        expected = EpisodeIdentity.of_payload(
            {
                "plan": authorization.plan.document(),
                "authorization": authorization.identity.document(),
                "episode_key": record["episode_key"],
            }
        )
        if record["plan"] != authorization.plan.document() or str(expected) != episode_str:
            problems.append(
                f"episode {record['episode_key']!r} does not recompute from "
                "plan x authorization x episode_key"
            )
            continue
        mine = [
            item
            for item in records
            if item.get("episode") == episode_str and item["sequence"] > record["sequence"]
        ]
        ready = [item for item in mine if item["event"] == STEP_READY]
        completed = [item for item in mine if item["event"] == EPISODE_COMPLETED]
        if len(completed) != 1:
            problems.append(f"episode {record['episode_key']!r} is not completed exactly once")
            continue
        rounds_executed = completed[0]["rounds"]
        planned = [
            (round_index, node)
            for round_index in range(1, protocol.rounds + 1)
            for node in order
        ]
        if len(ready) > len(planned):
            problems.append(f"episode {record['episode_key']!r} has steps beyond the IR")
            continue
        for item, (round_index, node) in zip(ready, planned, strict=False):
            step = StepIdentity.of_payload(
                {
                    "episode": expected.document(),
                    "round": round_index,
                    "node": node.node_id,
                    "kind": node.kind.value,
                }
            )
            if item["step"] != str(step) or item["round"] != round_index:
                problems.append(
                    f"episode {record['episode_key']!r} journal #{item['sequence']} is not "
                    f"IR step {node.node_id!r} of round {round_index}"
                )
                break
            steps[item["step"]] = _Step(
                episode_str, round_index, node.node_id, node.kind, item["sequence"]
            )
        else:
            full = len(ready) == len(planned)
            if not ready:
                problems.append(f"episode {record['episode_key']!r} executed no step")
                continue
            last_round, last_node = planned[len(ready) - 1]
            timed = protocol.round is not None and protocol.round.timing is not None
            # a timed round contract ends the episode at its verdict (round_problems)
            if not full and not timed and last_node.kind is not NodeKind.TERMINATION:
                problems.append(
                    f"episode {record['episode_key']!r} stopped after "
                    f"{last_node.node_id!r} (round {last_round}), not at an IR termination"
                )
            if rounds_executed != last_round:
                problems.append(
                    f"episode {record['episode_key']!r} completed {rounds_executed} rounds, "
                    f"its steps cover {last_round}"
                )
            closed = [item["round"] for item in mine if item["event"] == ROUND_COMPLETED]
            if closed != list(range(1, last_round + 1)):
                problems.append(f"episode {record['episode_key']!r} rounds closed {closed}")
            # SV-11: a round closes after the steps of it and before any of the next, and
            # the episode after its last round - by position, not by count.  A step is
            # placed by its STEP_READY and its commit event; what else is journaled in a
            # step's scope (a call, a tool call) is the call provenance's to place.
            closing = [
                (item["round"], item["sequence"])
                for item in mine
                if item["event"] == ROUND_COMPLETED and type(item["round"]) is int
            ]
            misplaced = sorted(
                item["sequence"]
                for item in mine
                if item["event"] in _STEP_PLACING
                # an event of another round than its step's is the next check's to name
                and item.get("step") in steps and steps[item["step"]].round == item.get("round")
                and any((item["round"] <= closed_round) != (item["sequence"] < at)
                        for closed_round, at in closing)
            ) + [at for _, at in closing if at > completed[0]["sequence"]]
            if misplaced:
                problems.append(
                    f"episode {record['episode_key']!r} journal #{misplaced[0]} is not within "
                    "its round: a round closes after its steps and before the next round's, "
                    "the episode after its last round"
                )
            # T4-001: the rounds are the plan's round contract, verdict by verdict
            problems += round_problems(
                contract=protocol.round,
                episode=expected,
                records=mine,
                initial_state=initial_state,
                label=f"episode {record['episode_key']!r}",
                order=[(node.node_id, node.kind.value) for node in order],
                states=evidenced_states,
            )
            episodes.append(
                {
                    "episode": expected.document(),
                    "episode_key": record["episode_key"],
                    "rounds_planned": protocol.rounds,
                    "rounds_executed": rounds_executed,
                    "steps": len(ready),
                    "terminated_by_ir": not full,
                }
            )

    unknown = sorted(
        {
            item["episode"]
            for item in records
            if "episode" in item and item["episode"] not in {r["episode"] for r in opened}
        }
    )
    if unknown:
        problems.append(f"journal-2 carries events of unopened episodes {unknown}")
    # Two orders, two identities (T2-004): the causal DAG is the IR's, the
    # schedule is the order the run opened its episodes in.
    ordering, schedule = schedule_problems(opened, protocol)
    problems += ordering
    positions = {key: index for index, key in enumerate((schedule or {}).get("episodes", ()))}
    for item in episodes:
        item["schedule_position"] = positions.get(item["episode_key"])

    # One commit event per step, of the kind the IR node prescribes.
    commits: dict[str, dict] = {}
    for record in records:
        if "step" not in record or record["event"] == STEP_READY:
            continue
        step = steps.get(record["step"])
        if step is None:
            problems.append(f"journal-2 #{record['sequence']} names a step outside the IR")
            continue
        if record["round"] != step.round or record["sequence"] < step.ready_sequence:
            problems.append(f"journal-2 #{record['sequence']} is out of its step's round/order")
        if record["event"] in _COMMIT_EVENTS:
            if record["event"] != COMMIT_EVENT.get(step.kind):
                problems.append(
                    f"step {step.node_id!r} ({step.kind.value}) carries {record['event']}"
                )
            elif record["step"] in commits:
                problems.append(f"step {step.node_id!r} round {step.round} committed twice")
            else:
                commits[record["step"]] = record
    for step_key, step in steps.items():
        if step.kind in COMMIT_EVENT and step_key not in commits:
            problems.append(
                f"step {step.node_id!r} round {step.round} has no {COMMIT_EVENT[step.kind]}"
            )

    # Artifact identities recompute; journal and evidence are in bijection.
    by_role: dict[str, dict[str, Any]] = {}
    # T4-003: memory-artifact-2 exactly under a plan declaring a memory lifecycle
    policies = memory_policies(protocol)
    for role, identity_cls, field_names in (
        ("proposal", ProposalIdentity, None),
        ("decision", DecisionArtifactIdentity, None),
        ("memory", MemoryArtifactIdentity, None),
    ):
        indexed: dict[str, Any] = {}
        for ref, document in _read_role(root, role):
            if role == "proposal":
                # proposal-2 exactly under a plan with P06 contracts (T1-004)
                expected = EVIDENCE_SCHEMA_V1 if proposals is None else EVIDENCE_SCHEMA_V2
                if document.get("schema") != expected:
                    problems.append(f"{ref.path} is not {expected} evidence")
                    continue
                field_names = PROPOSAL_FIELDS[expected]
            elif role == "decision":
                # decision-2 exactly under a plan with P07 contracts (T1-005)
                expected = DECISION_SCHEMA_V1 if decisions is None else DECISION_SCHEMA_V2
                if document.get("schema") != expected:
                    problems.append(f"{ref.path} is not {expected} evidence")
                    continue
                field_names = DECISION_FIELDS[expected]
            else:
                # artifact-2, or artifact-3 of a node declaring T4-004 semantics
                # (which of the two is its node's, ``artifact_problems`` decides)
                shapes = (
                    {
                        MEMORY_ARTIFACT_SCHEMA_V2: MEMORY_FIELDS_V2,
                        MEMORY_ARTIFACT_SCHEMA_V3: MEMORY_FIELDS_V3,
                    }
                    if policies
                    else {MEMORY_ARTIFACT_SCHEMA_V1: MEMORY_FIELDS_V1}
                )
                if document.get("schema") not in shapes:
                    problems.append(f"{ref.path} is not {' / '.join(shapes)} evidence")
                    continue
                field_names = shapes[document["schema"]]
                if set(document) != {"schema", "identity", *field_names}:
                    problems.append(f"{ref.path} has the wrong closed shape")
                    continue
            # SV-07: of every role - a member the schema does not name is in no
            # identity and the journal restates none of it.  Not ``!=``: a proposal
            # and a decision omit the members they state null (canonical-json-1)
            if not set(document) <= {"schema", "identity", *field_names}:
                problems.append(f"{ref.path} has the wrong closed shape")
                continue
            payload = {name: document.get(name) for name in field_names}
            if role == "proposal":
                payload["proposal"] = payload.pop("value")
            if _key(document.get("identity")) != str(identity_cls.of_payload(payload)):
                problems.append(f"{ref.path} identity does not recompute from its content")
                continue
            indexed[_key(document["identity"])] = document
        by_role[role] = indexed

    custody = reconcile_custody_v2(root)
    if not custody.complete:
        problems.append(
            "call custody does not reconcile: "
            + "; ".join([*(f"pending {c}" for c in custody.pending), *custody.problems])
        )
    # Local import: world_executor -> document_store -> manifest4 (as manifest4 does).
    from boomvalley_lab.kernel.state_chain import (
        STATE_CHAIN_CHECK,
        attested_chain,
        run_state_chain,
    )
    from boomvalley_lab.kernel.world_executor import (
        WORLD_ACTION_CHECK,
        WORLD_ADMISSIBILITY_CHECK,
        WORLD_CUSTODY_CHECK,
        WORLD_PROGRESSION_CHECK,
        WORLD_REPLAY_CHECK,
        WORLD_RNG_CHECK,
        WORLD_STATE_CHECK,
        admissibility_counts,
        custody_counts,
        progression_counts,
        reconcile_world_v2,
        rng_counts,
        world_action_problems,
        world_admissibility_problems,
        world_custody_problems,
        world_progression_problems,
        world_replay_problems,
        world_rng_problems,
        world_state_problems,
    )

    world = reconcile_world_v2(root)
    if not world.complete:
        problems.append(
            "World transitions do not reconcile: "
            + "; ".join([*(f"{i} {s}" for i, s in world.pending), *world.problems])
        )
    else:
        # initial/pre/post states are explicit and versioned (T3-001)
        problems.extend(world_state_problems(root, records, semantic))
        # the exact action handed to the World is evidenced before apply (T3-002)
        problems.extend(world_action_problems(root, records, semantic))
        # requested/admissible/executed actions are preserved independently (T3-003)
        problems.extend(world_admissibility_problems(root, records, semantic))
        # a null action or an environment progression is never a hidden mutation (T3-004)
        problems.extend(world_progression_problems(root, records, semantic))
        # every transition is one function of its serialized inputs (T3-005)
        problems.extend(world_replay_problems(root, records, semantic))
        # the declared RNG, bound to the plan's seed tree, is the only randomness (T3-006)
        problems.extend(world_rng_problems(root, records, semantic))
        # every intent is confirmed exactly once, from custody-accepted input (T3-007)
        problems.extend(world_custody_problems(root, records, semantic))
    # World(t) -> World(t+1): one chain of states per episode (T4-005); walked
    # whatever else failed, so a broken chain is always named as one
    broken, state_chain = run_state_chain(root, records, semantic)
    problems.extend(broken)

    event_field = {
        PROPOSAL_PARSED: ("proposal", "proposal"),
        DECISION_RECORDED: ("decision", "decision"),
        MEMORY_RECORDED: ("memory", "memory"),
    }
    referenced: dict[str, set[str]] = {role: set() for role in by_role}
    for step_key, record in commits.items():
        step = steps[step_key]
        if record["event"] == CUSTODY_ACCEPTED:
            step.output = record["call"]
        elif record["event"] == WORLD_APPLIED:
            step.output = _key(record["transition"])
        else:
            role, name = event_field[record["event"]]
            identity = _key(record[name]["identity"])
            document = by_role[role].get(identity)
            if document is None:
                problems.append(f"{record['event']} {identity} has no {role} evidence")
                continue
            if role != "memory" and (
                _key(document["step"]) != step_key or _key(document["episode"]) != step.episode
            ):
                problems.append(f"{role} evidence {identity} belongs to another step")
            if document["round"] != step.round:
                problems.append(f"{role} evidence {identity} belongs to another round")
            # SV-11: what the journal restates of the artifact beside its identity is
            # the artifact's - a commit event that says another value is not its commit
            if not _restates(record[name], role, document, protocol.node(step.node_id)):
                problems.append(
                    f"journal-2 #{record['sequence']} {record['event']} does not restate "
                    f"its {role} evidence {identity}"
                )
            if role == "proposal" and proposals is not None:
                # the committed proposal is the plan contract's, schema-valid
                problems.extend(
                    f"proposal evidence {identity}: {problem}"
                    for problem in committed_proposal_problems(
                        document, proposals.contract(step.node_id)
                    )
                )
            referenced[role].add(identity)
            step.output = identity
    for role, indexed in by_role.items():
        stray = sorted(set(indexed) - referenced[role])
        if stray:
            problems.append(f"{role} evidence not committed by journal-2: {stray}")
    if len(list((root / "evidence-v2" / "world_transition").glob("*.json"))) != sum(
        1 for record in commits.values() if record["event"] == WORLD_APPLIED
    ):
        problems.append("world_transition evidence is not one per WORLD_APPLIED")
    calls = {record["call"] for record in commits.values() if record["event"] == CUSTODY_ACCEPTED}
    if set(custody.accepted) != calls:
        problems.append("custody-accepted calls are not exactly the IR's actor-call steps")
    # T4-003: (episode, memory_update node) -> its committed artifact documents
    recorded: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for step in steps.values():
        if step.node_id in policies and step.output in by_role["memory"]:
            recorded.setdefault((step.episode, step.node_id), []).append(
                by_role["memory"][step.output]
            )
    # T4-004: the rounds whose committed World transition stated a declared
    # regime event, and what each round of each episode holds of a node's
    # memory under its declared carry, reset boundaries and regime interaction
    regime_rounds: dict[str, set[int]] = {}
    if policies and "world" in semantic:
        progression = WorldContractV1.from_document(semantic["world"]).progression
        stated = {
            _key(document.get("identity")): document
            for _, document in _read_role(root, "world_transition")
        }
        for record in records:
            if record["event"] != WORLD_APPLIED:
                continue
            body = stated.get(_key(record["transition"]), {}).get("transition")
            if isinstance(body, Mapping) and progression.regime_changes(body):
                regime_rounds.setdefault(record["episode"], set()).add(record["round"])
    order = [(record["episode"], record["episode_key"]) for record in opened]
    try:
        require_carry_schedule(
            policies, (schedule or {}).get("episodes", ()), journaled=True
        )
    except DeclarationError as error:
        problems.append(f"the run's schedule does not execute a declared carry: {error}")

    def remembered(episode: str, node_id: str, round_index: int) -> list[Mapping[str, Any]]:
        names = [name for name, _ in order]
        if episode not in names or node_id not in policies:
            return []
        timeline = [
            EpisodeMemoryV1(
                key,
                _identity_document(name),
                tuple(recorded.get((name, node_id), ())),
                tuple(sorted(regime_rounds.get(name, ()))),
            )
            for name, key in order[: names.index(episode) + 1]
        ]
        return held(policies[node_id], timeline, round_index)

    episode_keys = dict(order)
    bindings = _call_bindings(
        root, records, commits, steps, protocol, actors, information, problems,
        produced=_produced_digests(steps, commits, by_role),
        lineage=_produced_lineage(steps, commits, by_role),
        remembered=remembered,
        seeds=SeedDerivation.from_document(semantic["seed"]) if "seed" in semantic else None,
    )

    # Every IR dependency edge is the evidence lineage between the two steps.
    located = {(s.episode, s.round, s.node_id): s for s in steps.values()}
    step_keys = {(s.episode, s.round, s.node_id): key for key, s in steps.items()}
    intents = {
        record["step"]: _key(record["decision"])
        for record in records
        if record["event"] == WORLD_INTENT_RECORDED
    }
    transitions = (
        {_key(document.get("identity")): document
         for _, document in _read_role(root, "world_transition")}
        if policies
        else {}
    )
    for step_key, step in steps.items():
        node = protocol.node(step.node_id)

        def upstream(node_id: str, step: _Step = step) -> str | None:
            source = located.get((step.episode, step.round, node_id))
            return source.output if source is not None else None

        # dependency-ready (T2-002): each evidencing dependency committed
        # before this step became ready
        for dependency in node.depends_on:
            source_key = step_keys.get((step.episode, step.round, dependency))
            source = steps.get(source_key) if source_key is not None else None
            commit = commits.get(source_key) if source_key is not None else None
            if source is not None and source.kind in COMMIT_EVENT and (
                commit is None or commit["sequence"] > step.ready_sequence
            ):
                problems.append(
                    f"step {node.node_id!r} round {step.round} became ready before "
                    f"dependency {dependency!r} committed {COMMIT_EVENT[source.kind]}"
                )

        if step.kind is NodeKind.PROPOSAL_PARSE and step.output in by_role["proposal"]:
            link = _key(by_role["proposal"][step.output]["call"])
            source = node.depends_on[0] if len(node.depends_on) == 1 else None
            if source is None or link != upstream(source):
                problems.append(f"proposal of {node.node_id!r} round {step.round} is not "
                                "parsed from its IR actor-call dependency")
        elif (
            step.kind is NodeKind.DECISION
            and step.output in by_role["decision"]
            and decisions is not None
        ):
            # the artifact's candidates are the IR's committed proposals and a
            # builtin rule recomputes to exactly its outcome (P07 §10)
            contract = decisions.contract(node.node_id)
            problems.extend(
                f"decision of {node.node_id!r} round {step.round}: {problem}"
                for problem in committed_decision_problems(
                    by_role["decision"][step.output],
                    contract,
                    {
                        parse: by_role["proposal"].get(upstream(parse) or "")
                        for parse in contract.candidates.values()
                    },
                    proposals.contract(next(iter(contract.candidates.values()))).schema,
                    _key,
                )
            )
        elif step.kind is NodeKind.DECISION and step.output in by_role["decision"]:
            link = _key(by_role["decision"][step.output]["selected_proposal"])
            binding = node.config.get("binding")
            if binding not in node.depends_on or link != upstream(binding):
                problems.append(f"decision of {node.node_id!r} round {step.round} does not "
                                "select its IR binding proposal")
        elif step.kind is NodeKind.WORLD_TRANSITION:
            source = node.depends_on[0] if len(node.depends_on) == 1 else None
            if source is None or intents.get(step_key) != upstream(source):
                problems.append(f"World transition of {node.node_id!r} round {step.round} "
                                "does not apply its IR decision dependency")
        elif step.kind is NodeKind.MEMORY_UPDATE and step.output in by_role["memory"]:
            link = _key(by_role["memory"][step.output]["source_transition"])
            source = node.depends_on[0] if len(node.depends_on) == 1 else None
            if source is None or link != upstream(source):
                problems.append(f"memory of {node.node_id!r} round {step.round} is not "
                                "derived from its IR World dependency")
            if node.node_id in policies:
                # the artifact is its node's declared lifecycle, derived by its
                # transform from the committed source evidence (P16 13.2)
                applied = transitions.get(link, {}).get("transition")
                problems.extend(
                    f"memory of {node.node_id!r} round {step.round} {problem}"
                    for problem in artifact_problems(
                        by_role["memory"][step.output],
                        policies[node.node_id],
                        episode=_identity_document(step.episode),
                        step=_identity_document(step_key),
                        round_index=step.round,
                        record=commits[step_key]["memory"],
                        transition=applied if isinstance(applied, Mapping) else None,
                        episode_key=episode_keys.get(step.episode),
                    )
                )

    problems.extend(_exchange_evidence_problems(root, records))

    coverage = _coverage(root, semantic, problems)
    gndcrw = _gndcrw_results(root, authorization, problems)
    if authorization.gate.policy_identity == STRICT_GATE_POLICY:
        # SV-04: the strict gate decided on both; a run it cleared holds them
        for role, found in (("coverage", coverage), ("gndcrw_results", gndcrw)):
            if found is None and not any((root / "evidence-v2" / role).glob("*.json")):
                problems.append(
                    f"the run's {STRICT_GATE_POLICY} gate-2 decision names a {role} member "
                    "the run does not hold"
                )

    if analysis is not None and bindings is None:
        problems.append("a bound analysis needs the L1 dataset units of call-bound runs")

    if problems:
        raise PackageRefusedV4(problems)

    kinds = Counter(step.kind.value for step in steps.values())
    required = set(required_roles_v4(protocol)) | (L1_ROLES if bindings is not None else set())
    if protocol.round is not None and protocol.round.timing is not None:
        # T4-002: a timed contract may end the episode before a node kind ever
        # ran; the package owes the evidence of the kinds it executed
        required = set(BASE_ROLES) | (L1_ROLES if bindings is not None else set())
        for node in protocol.nodes:
            if node.kind.value in kinds:
                required |= KIND_ROLES[node.kind]
    if analysis is not None:
        required.add(ANALYSIS_ROLE)
    attestation = {
        "schema": ATTESTATION_SCHEMA,
        "package_class": "CONFORMANCE",
        "verdict": "CONFORMANT",
        "run": authorization.run_id,
        "experiment_id": semantic["experiment_id"],
        "plan": authorization.plan.document(),
        "plan_evidence": plan_ref.document(),
        "protocol_ir": semantic["protocol"]["schema"],
        "binding": authorization.binding.document(),
        "authorization": authorization.identity.document(),
        "required_roles": sorted(required),
        "episodes": sorted(episodes, key=lambda item: item["episode_key"]),
        "protocol_dag": protocol_dag_identity(protocol).document(),
        "experiment_schedule": schedule,
        "steps_by_kind": dict(sorted(kinds.items())),
        "custody_accepted_calls": len(custody.accepted),
        "world_transitions_applied": kinds.get(NodeKind.WORLD_TRANSITION.value, 0),
        "checks": list(CHECKS),
        "limitations": sorted(CONFORMANCE_LIMITATIONS),
    }
    if protocol.round is not None:
        attestation["checks"].append(ROUND_CHECK)
        attestation["round_contract"] = {
            "max_rounds": protocol.round.max_rounds,
            "termination_rule": protocol.round.termination.rule,
            "termination": protocol.round.termination.identity.document(),
            "rounds": protocol.round.rounds,
        }
        if protocol.round.timing is not None:
            # T4-002: where the rule is evaluated is part of what was verified
            attestation["round_contract"]["timing"] = protocol.round.timing
    if protocol.round is not None and "world" in semantic:
        # T4-005: the chain every round was verified on, head by head
        attestation["checks"].append(STATE_CHAIN_CHECK)
        attestation["state_chain"] = attested_chain(state_chain)
    if policies:
        # T4-003: which memory was declared, and how much of it is evidence
        attestation["checks"].append(MEMORY_CHECK)
        attestation["memory_lifecycle"] = {
            "nodes": {
                node_id: {
                    "owner": policy.owner,
                    "key": policy.key,
                    "scope": policy.scope,
                    "retention": policy.retention,
                    "transform": policy.transform,
                    "source": policy.source,
                    # T4-004: what crosses an episode or a regime, as declared
                    **(
                        {"regime_change": policy.regime_change}
                        if policy.extended
                        else {}
                    ),
                    **(
                        {
                            "carry": {
                                "episodes": list(policy.carry_episodes),
                                "reset_before": list(policy.reset_before),
                            }
                        }
                        if policy.scope == SCOPE_CROSS_EPISODE
                        else {}
                    ),
                }
                for node_id, policy in sorted(policies.items())
            },
            "sources": {
                source_id: descriptor.producer
                for source_id, descriptor in (
                    information.memory_artifacts.items() if information is not None else ()
                )
            },
            "artifacts": len(by_role["memory"]),
        }
        if any(policy.extended for policy in policies.values()):
            attestation["memory_lifecycle"]["regime_change_rounds"] = {
                episode_keys[name]: sorted(rounds)
                for name, rounds in sorted(regime_rounds.items())
                if name in episode_keys
            }
            attestation["memory_lifecycle"]["regime_resets"] = sorted(
                node_id
                for node_id, policy in policies.items()
                if policy.regime_change == REGIME_RESET
            )
    if "world" in semantic:
        contract = WorldContractV1.from_document(semantic["world"])
        attestation["checks"].extend(
            [
                WORLD_STATE_CHECK,
                WORLD_ACTION_CHECK,
                WORLD_ADMISSIBILITY_CHECK,
                WORLD_PROGRESSION_CHECK,
                WORLD_REPLAY_CHECK,
                WORLD_RNG_CHECK,
                WORLD_CUSTODY_CHECK,
            ]
        )
        attestation["world_contract"] = {
            "plugin": contract.plugin,
            "state_schema": contract.state_schema.ref,
            "action_schema": contract.action_schema.ref,
            "no_action": contract.progression.no_action,
            "exogenous_events": list(contract.progression.exogenous_events),
            "rng_policy": contract.rng.policy,
        }
        if contract.progression.regime_events:  # T4-004: the World's declared regime
            attestation["world_contract"]["regime"] = contract.progression.document()["regime"]
        attestation["world_admissibility"] = admissibility_counts(root, records)
        attestation["world_progression"] = progression_counts(root, records)
        attestation["world_rng"] = rng_counts(root, records)
        attestation["world_custody"] = custody_counts(root, records)
    if bindings is not None:
        attestation["checks"].append(L1_CALL_CHECK)
    if analysis is not None:
        attestation["checks"].append(ANALYSIS_CHECK)
    if coverage is not None:
        attestation["checks"].append(COVERAGE_CHECK)
        attestation["execution_coverage"] = coverage
    if gndcrw is not None:
        attestation["checks"].append(GNDCRW_CHECK)
        attestation["gndcrw_results"] = gndcrw
    state = {
        "steps": steps,
        "commits": commits,
        "episode_keys": {record["episode"]: record["episode_key"] for record in opened},
        "by_role": by_role,
        "bindings": bindings,
        "returned": {r["call"]: r for r in records if r["event"] == CALL_RETURNED},
        "coverage": coverage,
        "gndcrw": gndcrw,
        "analysis": analysis,
    }
    return attestation, state


def _call_bindings(
    root: Path,
    records: list[dict],
    commits: dict[str, dict],
    steps: dict[str, _Step],
    protocol: ProtocolIR,
    actors: ActorBindingSetV1 | None,
    information: InformationAccessSetV1 | None,
    problems: list[str],
    *,
    seeds: SeedDerivation | None = None,
    produced: Mapping[tuple[str, int, str], str] | None = None,
    lineage: Mapping[tuple[str, int, str], Mapping[str, Any]] | None = None,
    remembered: Callable[[str, str, int], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, tuple[EvidenceDocumentRefV2, Any]] | None:
    """Verify the run's L1 call bindings (T1-008); None for a pre-L1 run.

    A run is L1 when its call intents name call bindings; then every
    accepted call names exactly one, and the members are exactly those.
    Under a plan-7 seed tree each bound seed re-derives from it (T1-012).
    An observed actor_output source is its producer's committed output in the
    same episode and round (*produced*, T2-001), and request-2 binds that
    producer's committed identity (*lineage*, T2-003).  An observed
    memory_artifact source is its node's committed artifacts valid in the
    call's round: of the same episode (T4-003) and, under a declared carry,
    of the earlier episodes it consumes (*remembered*, T4-004).
    """

    intents = {r["call"]: r for r in records if r["event"] == CALL_INTENT_RECORDED}
    accepted = {
        record["call"]: step_key
        for step_key, record in commits.items()
        if record["event"] == CUSTODY_ACCEPTED
    }
    named = {call: intents[call].get("call_binding") for call in accepted if call in intents}
    stored = _read_role(root, "call_binding")
    if all(value is None for value in named.values()):
        if stored:
            problems.append("call_binding evidence in a run whose call intents name none")
        return None
    if any(value is None for value in named.values()) or set(named) != set(accepted):
        problems.append("the run mixes L1-bound and unbound accepted calls")
        return None
    if actors is None:
        problems.append("L1 call bindings need a plan with P04 actors")
        return None
    store = EvidenceDocumentStoreV2(root)
    requests = RequestStoreV2(root)
    bound: dict[str, tuple[EvidenceDocumentRefV2, Any]] = {}
    for call, reference in sorted(named.items()):
        step = steps[accepted[call]]
        try:
            ref = evidence_ref_from_document(reference, "call_binding")
            document = store.read(ref)
            request = load_bytes(read_intent_request_v2(intents[call], requests))
        except (EvidenceError, OSError, ValueError) as error:
            problems.append(f"call binding of {call}: {error}")
            continue
        views = {
            source: source_view(
                source,
                descriptor.producer,
                () if remembered is None
                else remembered(step.episode, descriptor.producer, step.round),
                step.round,
                _identity_document(step.episode),
            )
            for source, descriptor in (
                information.memory_artifacts.items() if information is not None else ()
            )
        }
        found = call_binding_problems(
            document,
            call=call,
            intent_request=intents[call]["request"]["identity"],
            episode=_identity_document(step.episode),
            step=_identity_document(accepted[call]),
            round_index=step.round,
            node_id=step.node_id,
            binding=actors.binding(protocol.node(step.node_id).config.get("actor")),
            request=request,
            access=information,
            seeds=seeds,
            produced={
                **{
                    source: (produced or {}).get(
                        (step.episode, step.round, descriptor.producer)
                    )
                    for source, descriptor in (
                        information.actor_outputs.items() if information is not None else ()
                    )
                },
                **{source: sha256_bytes(view[0]).hex for source, view in views.items()},
            },
            memory={source: view[1] for source, view in views.items()},
            lineage={
                source: (lineage or {}).get((step.episode, step.round, descriptor.producer))
                for source, descriptor in (
                    information.actor_outputs.items() if information is not None else ()
                )
            },
        )
        problems.extend(f"call binding of {call}: {problem}" for problem in found)
        bound[call] = (ref, document)
    if {ref.path for ref, _ in bound.values()} != {ref.path for ref, _ in stored}:
        problems.append("call_binding members are not exactly the ones the call intents name")
    return bound


def _produced_digests(
    steps: dict[str, _Step], commits: dict[str, dict], by_role: Mapping[str, Mapping[str, Any]]
) -> dict[tuple[str, int, str], str]:
    """(episode, round, node) -> sha256 of the output an actor_output source carries.

    actor_call: the custody-accepted response artifact.  proposal_parse: the
    committed proposal value as canonical JSON (T2-001).
    """

    found: dict[tuple[str, int, str], str] = {}
    for step_key, record in commits.items():
        step = steps[step_key]
        where = (step.episode, step.round, step.node_id)
        if record["event"] == CUSTODY_ACCEPTED and isinstance(record.get("artifact"), Mapping):
            algorithm, _, digest = str(record["artifact"].get("content")).partition(":")
            if algorithm == "sha256":
                found[where] = digest
        elif record["event"] == PROPOSAL_PARSED:
            document = by_role["proposal"].get(_key(record["proposal"]["identity"]))
            if document is not None and isinstance(document.get("value"), Mapping):
                found[where] = sha256_bytes(
                    canonical_json(dict(document["value"])).encode("utf-8")
                ).hex
    return found


def _produced_lineage(
    steps: dict[str, _Step], commits: dict[str, dict], by_role: Mapping[str, Mapping[str, Any]]
) -> dict[tuple[str, int, str], dict[str, Any]]:
    """(episode, round, node) -> the committed identity an actor_output carries (T2-003).

    actor_call: the custody-accepted CallIdentity.  proposal_parse: the
    committed ProposalIdentity; each with the digest of the carried bytes.
    """

    digests = _produced_digests(steps, commits, by_role)
    found: dict[tuple[str, int, str], dict[str, Any]] = {}
    for step_key, record in commits.items():
        step = steps[step_key]
        where = (step.episode, step.round, step.node_id)
        if where not in digests:
            continue
        if record["event"] == CUSTODY_ACCEPTED:
            kind, identity = "actor_call", _identity_document(record["call"])
        else:
            kind, identity = "proposal_parse", dict(record["proposal"]["identity"])
        found[where] = {
            "producer_kind": kind, "identity": identity, "content_sha256": digests[where]
        }
    return found


def _identity_document(key: str) -> dict[str, str]:
    kind, digest = key.split(":", 1)
    return {"kind": kind, "digest": digest}


def _dataset(
    attestation: Mapping[str, Any], evidence: EvidenceDocumentRefV2, state: Mapping[str, Any]
) -> dict[str, Any]:
    """The L1 dataset units of a derived run (T1-008): four unit tables."""

    steps, keys, bindings = state["steps"], state["episode_keys"], state["bindings"]
    proposals_by_id = state["by_role"]["proposal"]

    def located(step_key: str) -> dict[str, Any]:
        step = steps[step_key]
        return {"episode_key": keys[step.episode], "round": step.round, "node": step.node_id}

    calls, proposals, decisions = [], [], []
    for step_key, record in state["commits"].items():
        if record["event"] == CUSTODY_ACCEPTED:
            ref, binding = bindings[record["call"]]
            trace = binding["access"]
            calls.append({
                "unit": binding["call"],
                **located(step_key),
                "actor_id": binding["actor"]["actor_id"],
                "actor": binding["actor"]["identity"],
                "role_id": binding["role"]["role_id"],
                "role": binding["role"]["identity"],
                "profile": binding["profile"],
                "provider": binding["provider"],
                "model": state["returned"][record["call"]]["response"]["model_identity"],
                "seed": binding["seed"],
                "request": binding["request"],
                "response": record["artifact"],
                "custody": record["custody"],
                "binding": ref.document(),
                "access": {
                    name: trace[name] for name in ("granted", "denied", "transforms", "observation")
                },
            })
        elif record["event"] == PROPOSAL_PARSED:
            document = proposals_by_id[_key(record["proposal"]["identity"])]
            proposals.append({
                "unit": document["identity"],
                **located(step_key),
                "call": document["call"],
                "actor_id": bindings[_key(document["call"])][1]["actor"]["actor_id"],
                "parser": document["parser"],
                "verdict": document.get("verdict", "VALID"),
                "value": document["value"],
                "reason": document.get("reason"),
            })
        elif record["event"] == DECISION_RECORDED:
            document = state["by_role"]["decision"][_key(record["decision"]["identity"])]
            selected = document.get("selected_proposal")
            if "candidates" in document:  # decision-2 (P07)
                candidates = [item["proposal"] for item in document["candidates"]]
                supporting = document["supporting_proposals"]
                outcome = document["outcome"]
            else:  # decision-1: the one bound proposal is selected
                candidates = supporting = [selected]
                outcome = "SELECTED"
            decisions.append({
                "unit": document["identity"],
                **located(step_key),
                "rule": document["rule"],
                "outcome": outcome,
                "selected_proposal": selected,
                "supporting_proposals": supporting,
                "candidates": candidates,
                "requested_action": document.get("requested_action"),
            })

    coverage = state["coverage"]["verdict"] if state["coverage"] else NOT_ATTESTED
    comparisons = state["gndcrw"]["outcome"] if state["gndcrw"] else NOT_BOUND
    eligibility = []
    for decision in decisions:
        parsed = [proposals_by_id.get(_key(item)) for item in decision["candidates"]]
        lineage = all(
            proposal is not None and _key(proposal["call"]) in bindings for proposal in parsed
        )
        eligibility.append(
            eligibility_row(
                decision, lineage_bound=lineage, coverage=coverage, comparisons=comparisons
            )
        )
    return dataset_document(
        run=attestation["run"],
        experiment_id=attestation["experiment_id"],
        plan=attestation["plan"],
        authorization=attestation["authorization"],
        attestation=evidence.document(),
        conditions={
            "coverage": coverage,
            "comparisons": comparisons,
            "cell": state["coverage"]["cell"] if state["coverage"] else None,
        },
        calls=calls,
        proposals=proposals,
        decisions=decisions,
        eligibility=eligibility,
    )


def derive_dataset_units_v4(root: Path) -> dict[str, Any] | None:
    """Re-derive an attested L1 run's dataset units; None for a pre-L1 run."""

    root = Path(root)
    attestation, state = _derive_state(root)
    if state["bindings"] is None:
        return None
    stored = _read_role(root, "conformance_attestation")
    if len(stored) != 1 or stored[0][1] != attestation:
        raise PackageRefusedV4(["dataset units need the run's one re-derived attestation"])
    return _dataset(attestation, stored[0][0], state)


def _gndcrw_results(root: Path, authorization: Any, problems: list[str]) -> dict | None:
    """Verify the run's GNDCRW comparison result set, if its strict gate bound one."""

    members = _read_role(root, "gndcrw_results")
    if not members:
        return None
    coverage = _read_role(root, "coverage")
    if len(members) != 1 or len(coverage) != 1:
        problems.append(
            f"a GNDCRW result set needs exactly one result set and one coverage member, "
            f"found {len(members)} / {len(coverage)}"
        )
        return None
    ref, document = members[0]
    identity = GNDCRWResultSetIdentity.of_payload(document)
    if identity != authorization.gate.gndcrw_results:
        problems.append("gndcrw_results: not the gate-2 decision's GNDCRW result set")
    found = stored_result_set_problems(coverage[0][1], document)
    problems.extend(f"gndcrw_results: {problem}" for problem in found)
    if found:
        return None
    return {
        "result_set": identity.document(),
        "evidence": ref.document(),
        "edges": len(document["required_edges"]),
        "outcome": "RUN",
    }


def _coverage(root: Path, semantic: Mapping[str, Any], problems: list[str]) -> dict | None:
    """Verify the run's P09-ERF coverage member, if its gate decided on one."""

    members = _read_role(root, "coverage")
    if not members:
        return None
    if len(members) != 1:
        problems.append(f"expected at most one coverage member, found {len(members)}")
        return None
    ref, document = members[0]
    found, cell = attested_cell_problems(document, semantic)
    problems.extend(f"coverage: {problem}" for problem in found)
    if cell is None or found:
        return None
    problems.extend(corroboration_problems(root, cell, semantic))
    return {
        "attestation": CoverageAttestationIdentity.of_payload(document).document(),
        "evidence": ref.document(),
        "cell": cell["cell"],
        "erf": len(cell["erf"]),
        "excluded": len(cell["excluded"]),
        "verdict": document["execution_coverage"],
    }


@dataclass(frozen=True)
class ConformancePackageV4:
    root: Path
    manifest: ManifestV4
    manifest_path: Path
    attestation: Mapping[str, Any]
    attestation_evidence: EvidenceDocumentRefV2


def build_conformance_package_v4(root: Path) -> ConformancePackageV4:
    """Seal one completed K0 run directory as a verified CONFORMANCE package."""

    root = Path(root)
    if (root / MANIFEST_NAME).exists():
        raise EvidenceError("manifest-4 is immutable and already exists")
    attestation, state = _derive_state(root)
    store = EvidenceDocumentStoreV2(root)
    derived: dict[str, Any] = {"conformance_attestation": attestation}
    if state["bindings"] is not None:
        dataset = _dataset(attestation, store.ref("conformance_attestation", attestation), state)
        derived["dataset_units"] = dataset
        if state["analysis"] is not None:
            derived[ANALYSIS_ROLE] = analysis_document(
                contract=state["analysis"],
                dataset=dataset,
                dataset_evidence=store.ref("dataset_units", dataset).document(),
            )
    # A `package` killed before its manifest leaves members it derived (T4-014),
    # in the order it writes them.  The member this run derives now is that same
    # member and is not refused.  Any other member of a derived role - or one
    # whose predecessors are missing - is not the leftover of a killed seal.
    interrupted = False
    for role in ("conformance_attestation", "dataset_units", ANALYSIS_ROLE):
        own = Path(store.ref(role, derived[role]).path).name if role in derived else None
        held = {path.name for path in (root / "evidence-v2" / role).glob("*.json")}
        if held - {own} or (held and interrupted):
            raise EvidenceError(f"the run already carries {role} evidence")
        interrupted = interrupted or (own is not None and not held)
    evidence = store.put("conformance_attestation", attestation)
    for role in ("dataset_units", ANALYSIS_ROLE):
        if role in derived:
            store.put(role, derived[role])
    members = collect_manifest4_members(root)
    missing = sorted(set(attestation["required_roles"]) - {m.role for m in members})
    if missing:
        raise PackageRefusedV4([f"the package lacks IR-required roles {missing}"])
    manifest = ManifestV4(
        "CONFORMANCE",
        identity_from_document(PlanIdentity, attestation["plan"], "attested plan"),
        members,
        CONFORMANCE_LIMITATIONS,
    )
    path = write_manifest4(root, manifest)
    problems = verify_package_v4(root)
    if problems:
        # SV-09: a refused seal leaves no manifest - the run is not SEALED by a
        # package its own builder did not verify, and it can be sealed once
        # what refused it is put right
        path.unlink(missing_ok=True)
        raise PackageRefusedV4(problems)
    return ConformancePackageV4(root, manifest, path, attestation, evidence)


def verify_package_v4(root: Path) -> list[str]:
    """Independently verify one manifest-4 package; ``[]`` means verified."""

    root = Path(root)
    try:
        manifest = read_manifest4(root / MANIFEST_NAME)
    except (EvidenceError, OSError) as error:
        return [f"{MANIFEST_NAME}: {error}"]
    problems = manifest.verify(root)
    if manifest.package_class != "CONFORMANCE":
        problems.append(
            f"no {manifest.package_class} verifier exists in K0 "
            "(BVL-REC-102 / BVL-REC-104); only CONFORMANCE packages verify"
        )
    absent = sorted(set(CONFORMANCE_LIMITATIONS) - set(manifest.limitations))
    if absent:
        problems.append(f"CONFORMANCE package omits limitations {absent}")

    listed = {member.path for member in manifest.members}
    present = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    } - {MANIFEST_NAME}
    problems.extend(f"unlisted file {path}" for path in sorted(present - listed))
    if problems:
        return problems

    try:
        attestation = derive_conformance_attestation_v4(root)
        collected = collect_manifest4_members(root)
    except PackageRefusedV4 as refused:
        return [*refused.problems]
    except (BoomvalleyError, OSError) as error:
        return [f"package does not reconcile: {error}"]

    if [m.document() for m in collected] != [
        m.document() for m in sorted(manifest.members, key=lambda item: item.path)
    ]:
        problems.append("manifest members are not exactly the reconciled package members")
    if manifest.plan.document() != attestation["plan"]:
        problems.append("manifest plan is not the authorized plan")
    try:
        stored = [
            document for _, document in _read_role(root, "conformance_attestation")
        ]
        if stored != [attestation]:
            problems.append(
                "conformance attestation does not re-derive from the package evidence")
        roles = {member.role for member in manifest.members}
        lacking = sorted(set(attestation["required_roles"]) - roles)
        if lacking:
            problems.append(f"package lacks IR-required roles {lacking}")
        problems.extend(_dataset_problems(root))
        if not problems:
            problems.extend(_analysis_problems(root))
    except (BoomvalleyError, OSError) as error:
        # SV-10: a derived member edited under its content address and listed by a
        # re-hashed manifest is a problem of this package, not an error of the verifier
        problems.append(f"package evidence does not read: {error}")
    return problems


def _dataset_problems(root: Path) -> list[str]:
    """An L1 package holds exactly its re-derived dataset units; others none."""

    stored = _read_role(root, "dataset_units")
    try:
        derived = derive_dataset_units_v4(root)
    except PackageRefusedV4 as refused:
        return [*refused.problems]
    if derived is None:
        return ["dataset_units evidence in a pre-L1 package"] if stored else []
    if len(stored) != 1:
        return [f"an L1 package holds one dataset_units member, found {len(stored)}"]
    if canonical_bytes(stored[0][1]) != canonical_bytes(derived):
        return ["dataset units do not re-derive from the package evidence"]
    return []


def derive_analysis_v4(root: Path) -> dict[str, Any] | None:
    """Recompute a plan-6 run's official analysis; None when the plan binds none.

    The population is the eligible units of the re-derived dataset, never the
    stored analysis; the output names the packaged dataset_units member.
    """

    root = Path(root)
    attestation, state = _derive_state(root)
    if state["analysis"] is None:
        return None
    dataset = derive_dataset_units_v4(root)
    stored = _read_role(root, "dataset_units")
    if dataset is None or len(stored) != 1 or canonical_bytes(stored[0][1]) != canonical_bytes(
        dataset
    ):
        raise PackageRefusedV4(["a bound analysis needs the run's one re-derived dataset"])
    return analysis_document(
        contract=state["analysis"], dataset=dataset, dataset_evidence=stored[0][0].document()
    )


def _analysis_problems(root: Path) -> list[str]:
    """A plan-6 package holds exactly its recomputed analysis; others none."""

    stored = _read_role(root, ANALYSIS_ROLE)
    try:
        derived = derive_analysis_v4(root)
    except PackageRefusedV4 as refused:
        return [*refused.problems]
    if derived is None:
        return [f"{ANALYSIS_ROLE} evidence in a package whose plan binds no analysis"] if (
            stored
        ) else []
    if len(stored) != 1:
        return [f"a bound-analysis package holds one {ANALYSIS_ROLE} member, found {len(stored)}"]
    if canonical_bytes(stored[0][1]) != canonical_bytes(derived):
        return ["the bound analysis does not recompute over the admitted dataset units"]
    return []
