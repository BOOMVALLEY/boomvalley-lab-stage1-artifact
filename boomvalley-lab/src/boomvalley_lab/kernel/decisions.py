"""P07 decision rule registry (T1-005).

Typed proposals are not yet a decision.  P07 turns the proposals of a
decision node, through one registered decision rule bound in the frozen plan,
into one runtime Decision Artifact or one explicit decision failure:

    P06 proposals (VALID | NO_ACTION) of the declared authority
        -> registered decision rule (plugin identity + frozen config)
        -> kernel settlement (order invariance, action contract, policy)
        -> Decision Artifact (SELECTED | AGGREGATE | NO_ACTION) or FAILED

Declaration: ``DecisionRegistryV1`` holds one ``DecisionDeclV1`` per decision
node: rule plugin identity, authority (the eligible actors), rule config and
the policy for an unresolved rule outcome.  It resolves against the plan's
Protocol IR, P04 actors and P06 contracts into a ``DecisionContractSetV1``
that enters the frozen plan (``semantic-plan-5``).  The authority mapping
(eligible actor -> its one proposal_parse input) is derived by the kernel from
the IR (parse -> actor_call -> plan actor), never from call order, node
config or prompt wording.

Order independence (P07 §6.2, BVL-DEC-012): a rule only ever sees
``CandidateV1`` tuples (actor, proposal identity, verdict, value) - never node
ids, call order or raw responses.  The kernel runs it contained and pure on
the candidates in canonical (actor) order *and* on their permutations; a rule
whose outcome depends on the order is refused.  Authority policies naming an
order (FIRST, CALL_ORDER ...) are refused at declaration.

Ownership (P07 §13.2): the kernel validates that the selected/aggregated
action conforms to the action contract (the candidates' P06 schema); whether
it is admissible in the domain is the World's verdict (P15).  A NO_ACTION
proposal is an explicit abstention.  A NO_ACTION *decision* exists only under
a declared ``on_unresolved: NO_ACTION`` policy and is never a generic
skip-World shortcut: handing one to a World is refused until P15 defines its
transition semantics.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import CanonicalisationError, DeclarationError
from boomvalley_lab.kernel.actors import ActorBindingSetV1
from boomvalley_lab.kernel.containment import (
    DECISION_RULE,
    ContainmentViolationV2,
    active_session,
    invoke_pure,
)
from boomvalley_lab.kernel.proposals import ProposalContractSetV1, ProposalSchemaV1
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR

CONTRACT_SCHEMA = "bvl-decision-contract-1"
CONTRACT_SET_SCHEMA = "bvl-decision-contract-set-1"
# decision evidence: -1 is the historical T0 single-authority artifact (node
# config binding), -2 binds the plan contract, candidates and outcome (T1-005)
EVIDENCE_SCHEMA_V1 = "boomvalley-lab-decision-1"
EVIDENCE_SCHEMA_V2 = "boomvalley-lab-decision-2"
EVIDENCE_FIELDS_V1 = ("episode", "step", "round", "rule", "selected_proposal", "requested_action")
EVIDENCE_FIELDS_V2 = (
    "episode",
    "step",
    "round",
    "rule",
    "contract",
    "candidates",
    "outcome",
    "selected_proposal",
    "supporting_proposals",
    "requested_action",
    "tally",
    "reason",
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")

# P07 §8 stable reason-code family
RULE_NOT_REGISTERED = "BVL-DEC-001"
RULE_IDENTITY_MISMATCH = "BVL-DEC-002"
REQUIRED_PROPOSAL_MISSING = "BVL-DEC-003"
PROPOSAL_INVALID = "BVL-DEC-004"
AUTHORITY_SET_INVALID = "BVL-DEC-005"
TIE_UNRESOLVED = "BVL-DEC-006"
VETO_TRIGGERED = "BVL-DEC-007"
FALLBACK_NOT_ALLOWED = "BVL-DEC-008"
DECISION_RULE_FAILED = "BVL-DEC-009"
DECISION_LINEAGE_MISMATCH = "BVL-DEC-010"
ACTION_SCHEMA_INVALID = "BVL-DEC-011"
AUTHORITY_BY_ORDER_FORBIDDEN = "BVL-DEC-012"

DECISION_CODES = frozenset(
    {
        RULE_NOT_REGISTERED,
        RULE_IDENTITY_MISMATCH,
        REQUIRED_PROPOSAL_MISSING,
        PROPOSAL_INVALID,
        AUTHORITY_SET_INVALID,
        TIE_UNRESOLVED,
        VETO_TRIGGERED,
        FALLBACK_NOT_ALLOWED,
        DECISION_RULE_FAILED,
        DECISION_LINEAGE_MISMATCH,
        ACTION_SCHEMA_INVALID,
        AUTHORITY_BY_ORDER_FORBIDDEN,
    }
)
#: the codes a rule may report for an unresolved outcome (policy applies)
UNRESOLVED_CODES = frozenset({REQUIRED_PROPOSAL_MISSING, TIE_UNRESOLVED, VETO_TRIGGERED})

#: policies that would invent an action; never a decision behavior (P07 §5)
_FALLBACK_POLICIES = frozenset(
    {"FALLBACK", "DEFAULT", "DEFAULT_ACTION", "RANDOM", "RETRY", "REPROMPT", "OVERRIDE"}
)
#: policies that would infer authority from order (P07 §1, §11)
_ORDER_POLICIES = frozenset(
    {"FIRST", "FIRST_ACTOR", "FIRST_PROPOSAL", "LAST", "CALL_ORDER", "ORDER", "EARLIEST"}
)
#: all permutations up to this many candidates; rotations + reversals above
_FULL_PERMUTATIONS = 5


class DecisionError(DeclarationError):
    """A P07 refusal carrying one stable ``BVL-DEC-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in DECISION_CODES:
            raise ValueError(f"unknown decision reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


class UnresolvedPolicy(StrEnum):
    # an unresolved rule outcome fails the episode (durable failed decision)
    FAIL_EPISODE = "FAIL_EPISODE"
    # an explicit, evidenced NO_ACTION decision (never a skip-World shortcut)
    NO_ACTION = "NO_ACTION"


class DecisionOutcome(StrEnum):
    SELECTED = "SELECTED"  # one candidate proposal is authoritative
    AGGREGATE = "AGGREGATE"  # an action derived from several proposals
    NO_ACTION = "NO_ACTION"  # declared policy for an unresolved outcome
    FAILED = "FAILED"  # declared policy failed the episode


def _frozen(value: Any, code: str, what: str) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (CanonicalisationError, TypeError, ValueError) as error:
        raise DecisionError(code, f"{what} is not canonical data: {error}") from error


def _require_id(value: Any, what: str, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DecisionError(code, f"{what} is not a valid identifier: {value!r}")
    return value


# ---------------------------------------------------------------- rule plugin API
@dataclass(frozen=True)
class CandidateV1:
    """What a rule sees of one eligible actor's proposal - and nothing else."""

    actor: str
    proposal: str  # ProposalIdentity, ``kind:digest``
    verdict: str  # VALID | NO_ACTION (an INVALID proposal never reaches a rule)
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", MappingProxyType(dict(self.value)))


@dataclass(frozen=True)
class RuleOutcomeV1:
    """A rule's answer; the kernel settles it into a Decision Artifact."""

    kind: str  # SELECTED | AGGREGATE | UNRESOLVED
    selected: str | None = None  # actor (SELECTED)
    supporting: tuple[str, ...] = ()  # actors whose proposals carry the action
    action: Mapping[str, Any] | None = None
    code: str | None = None  # UNRESOLVED: one of UNRESOLVED_CODES
    detail: str = ""
    tally: Mapping[str, Any] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "selected": self.selected,
            "supporting": sorted(self.supporting),
            "action": None if self.action is None else dict(self.action),
            "code": self.code,
            "detail": self.detail,
            "tally": dict(self.tally),
        }


class DecisionRuleV1(Protocol):
    """A registered P07 rule: pure, order-independent, no actor/provider access."""

    plugin_identity: str

    def check(self, authority: tuple[str, ...], config: Mapping[str, Any]) -> None:
        """Raise ``DecisionError`` when the rule cannot decide for this authority/config."""

    def decide(
        self, candidates: tuple[CandidateV1, ...], config: Mapping[str, Any]
    ) -> RuleOutcomeV1: ...


def _no_config(rule: str, config: Mapping[str, Any]) -> None:
    if config:
        raise DecisionError(AUTHORITY_SET_INVALID, f"{rule} takes no config, got {dict(config)}")


def _votes(candidates: tuple[CandidateV1, ...]) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """VALID proposals grouped by canonical action; NO_ACTION is an abstention."""

    groups: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.verdict == "VALID":
            groups.setdefault(canonical_json(dict(candidate.value)), []).append(candidate.actor)
    tally = {
        "eligible": len(candidates),
        "abstained": sorted(c.actor for c in candidates if c.verdict != "VALID"),
        "votes": [
            {"action": json.loads(action), "actors": sorted(actors)}
            for action, actors in sorted(groups.items())
        ],
    }
    return groups, tally


@dataclass(frozen=True)
class SingleAuthorityRuleV1:
    """The one declared authority's VALID proposal is the decision."""

    plugin_identity: str = "builtin.single-authority:1"

    def check(self, authority: tuple[str, ...], config: Mapping[str, Any]) -> None:
        if len(authority) != 1:
            raise DecisionError(
                AUTHORITY_SET_INVALID, f"single authority binds exactly one actor, not {authority}"
            )
        _no_config(self.plugin_identity, config)

    def decide(
        self, candidates: tuple[CandidateV1, ...], config: Mapping[str, Any]
    ) -> RuleOutcomeV1:
        (only,) = candidates
        if only.verdict != "VALID":
            return RuleOutcomeV1(
                "UNRESOLVED",
                code=REQUIRED_PROPOSAL_MISSING,
                detail=f"binding actor {only.actor!r} proposed NO_ACTION",
            )
        return RuleOutcomeV1("SELECTED", only.actor, (only.actor,), dict(only.value))


@dataclass(frozen=True)
class MajorityRuleV1:
    """An action proposed by more than half of the eligible actors (abstentions count)."""

    plugin_identity: str = "builtin.majority:1"

    def check(self, authority: tuple[str, ...], config: Mapping[str, Any]) -> None:
        if len(authority) < 2:
            raise DecisionError(AUTHORITY_SET_INVALID, "majority needs at least two actors")
        _no_config(self.plugin_identity, config)

    def decide(
        self, candidates: tuple[CandidateV1, ...], config: Mapping[str, Any]
    ) -> RuleOutcomeV1:
        groups, tally = _votes(candidates)
        for action, actors in groups.items():
            if 2 * len(actors) > len(candidates):
                return RuleOutcomeV1(
                    "AGGREGATE", None, tuple(sorted(actors)), json.loads(action), tally=tally
                )
        return RuleOutcomeV1(
            "UNRESOLVED",
            code=TIE_UNRESOLVED,
            detail=f"no action holds an absolute majority of {len(candidates)} eligible",
            tally=tally,
        )


@dataclass(frozen=True)
class PluralityRuleV1:
    """The single most-proposed action; a tie for the top (or no vote) is unresolved."""

    plugin_identity: str = "builtin.plurality:1"

    def check(self, authority: tuple[str, ...], config: Mapping[str, Any]) -> None:
        if len(authority) < 2:
            raise DecisionError(AUTHORITY_SET_INVALID, "plurality needs at least two actors")
        _no_config(self.plugin_identity, config)

    def decide(
        self, candidates: tuple[CandidateV1, ...], config: Mapping[str, Any]
    ) -> RuleOutcomeV1:
        groups, tally = _votes(candidates)
        top = max((len(actors) for actors in groups.values()), default=0)
        leaders = [action for action, actors in groups.items() if len(actors) == top]
        if top == 0 or len(leaders) != 1:
            return RuleOutcomeV1(
                "UNRESOLVED",
                code=TIE_UNRESOLVED,
                detail=f"{len(leaders)} actions tie at {top} proposals",
                tally=tally,
            )
        return RuleOutcomeV1(
            "AGGREGATE", None, tuple(sorted(groups[leaders[0]])), json.loads(leaders[0]),
            tally=tally,
        )


@dataclass(frozen=True)
class VetoRuleV1:
    """Act only on an action every eligible actor proposes; any dissent is a veto.

    The decision of a bounded revision block (T2-005, ``kernel/revision.py``):
    the final reviewer endorses the final draft by proposing the same action.
    A different action or an abstention vetoes it (BVL-DEC-007), and the
    declared unresolved policy applies.
    """

    plugin_identity: str = "builtin.veto:1"

    def check(self, authority: tuple[str, ...], config: Mapping[str, Any]) -> None:
        if len(authority) < 2:
            raise DecisionError(AUTHORITY_SET_INVALID, "a veto needs at least two actors")
        _no_config(self.plugin_identity, config)

    def decide(
        self, candidates: tuple[CandidateV1, ...], config: Mapping[str, Any]
    ) -> RuleOutcomeV1:
        groups, tally = _votes(candidates)
        endorsed = [action for action, actors in groups.items() if len(actors) == len(candidates)]
        if not endorsed:
            return RuleOutcomeV1(
                "UNRESOLVED",
                code=VETO_TRIGGERED,
                detail=f"{len(groups)} distinct actions, {len(tally['abstained'])} abstained "
                f"of {len(candidates)} eligible",
                tally=tally,
            )
        return RuleOutcomeV1(
            "AGGREGATE", None, tuple(sorted(groups[endorsed[0]])), json.loads(endorsed[0]),
            tally=tally,
        )


SINGLE_AUTHORITY = SingleAuthorityRuleV1.plugin_identity
MAJORITY = MajorityRuleV1.plugin_identity
PLURALITY = PluralityRuleV1.plugin_identity
VETO = VetoRuleV1.plugin_identity
#: the builtin rules that count equal proposals (``_votes``): by canonical action
VOTE_RULES = frozenset({MAJORITY, PLURALITY, VETO})
#: generic rules the kernel ships; a third-party rule registers the same way
BUILTIN_RULES: Mapping[str, DecisionRuleV1] = MappingProxyType(
    {
        SINGLE_AUTHORITY: SingleAuthorityRuleV1(),
        MAJORITY: MajorityRuleV1(),
        PLURALITY: PluralityRuleV1(),
        VETO: VetoRuleV1(),
    }
)


# ---------------------------------------------------------------- declaration
@dataclass(frozen=True)
class DecisionContractV1:
    """One decision node's frozen P07 binding (enters PlanIdentity)."""

    node_id: str
    rule: str  # the rule's registered plugin identity
    authority: tuple[str, ...]  # eligible actors, canonical order
    candidates: Mapping[str, str]  # eligible actor -> its proposal_parse node
    config: Mapping[str, Any]
    on_unresolved: UnresolvedPolicy

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "node_id": self.node_id,
            "rule": self.rule,
            "authority": list(self.authority),
            "candidates": dict(self.candidates),
            "config": dict(self.config),
            "on_unresolved": self.on_unresolved.value,
        }


@dataclass(frozen=True)
class DecisionDeclV1:
    """Declared authority of one decision node (P01 declaration)."""

    node_id: str
    rule: str
    authority: Sequence[str]
    config: Mapping[str, Any] = field(default_factory=dict)
    on_unresolved: str = UnresolvedPolicy.FAIL_EPISODE.value


def _policy(value: Any, node_id: str) -> UnresolvedPolicy:
    name = value.upper() if isinstance(value, str) else value
    if name in _ORDER_POLICIES:
        raise DecisionError(
            AUTHORITY_BY_ORDER_FORBIDDEN, f"{node_id!r}: {value!r} infers authority from order"
        )
    if name in _FALLBACK_POLICIES:
        raise DecisionError(
            FALLBACK_NOT_ALLOWED, f"{node_id!r}: {value!r} would invent an undeclared action"
        )
    try:
        return UnresolvedPolicy(value)
    except ValueError as error:
        raise DecisionError(
            FALLBACK_NOT_ALLOWED, f"{node_id!r}: unknown unresolved policy {value!r}"
        ) from error


def _authority_inputs(protocol: ProtocolIR, node_id: str) -> dict[str, list[str]]:
    """actor -> the decision node's proposal_parse inputs authored by that actor."""

    found: dict[str, list[str]] = {}
    for dependency in protocol.node(node_id).depends_on:
        parse = protocol.node(dependency)
        if parse.kind is not NodeKind.PROPOSAL_PARSE or len(parse.depends_on) != 1:
            continue
        call = protocol.node(parse.depends_on[0])
        actor = call.config.get("actor") if call.kind is NodeKind.ACTOR_CALL else None
        if isinstance(actor, str):
            found.setdefault(actor, []).append(dependency)
    return found


@dataclass(frozen=True)
class DecisionRegistryV1:
    """Declared decision authority per decision node."""

    decisions: Sequence[DecisionDeclV1]

    def resolve(
        self,
        protocol: ProtocolIR,
        actors: ActorBindingSetV1 | None,
        proposals: ProposalContractSetV1 | None,
    ) -> DecisionContractSetV1:
        if proposals is None or actors is None:
            raise DecisionError(
                AUTHORITY_SET_INVALID, "decision rules decide over P06 proposals of plan actors"
            )
        decision_nodes = {n.node_id for n in protocol.nodes if n.kind is NodeKind.DECISION}
        contracts: dict[str, DecisionContractV1] = {}
        for decl in self.decisions:
            node_id = _require_id(decl.node_id, "decision node id", RULE_NOT_REGISTERED)
            if node_id in contracts:
                raise DecisionError(RULE_NOT_REGISTERED, f"{node_id!r} is bound twice")
            if node_id not in decision_nodes:
                raise DecisionError(
                    AUTHORITY_SET_INVALID, f"contract {node_id!r} binds no decision node"
                )
            if protocol.node(node_id).config:
                raise DecisionError(
                    AUTHORITY_SET_INVALID,
                    f"decision {node_id!r}: authority is the plan's decision contract, "
                    "not node config",
                )
            rule = _require_id(decl.rule, "decision rule plugin identity", RULE_NOT_REGISTERED)
            authority = decl.authority
            if (
                isinstance(authority, str)
                or not isinstance(authority, Sequence)
                or not authority
                or len(set(authority)) != len(authority)
            ):
                raise DecisionError(
                    AUTHORITY_SET_INVALID, f"{node_id!r}: authority is a non-empty set of actors"
                )
            inputs = _authority_inputs(protocol, node_id)
            candidates: dict[str, str] = {}
            for actor in sorted(authority):
                if actor not in actors.bindings:
                    raise DecisionError(
                        AUTHORITY_SET_INVALID, f"{node_id!r}: {actor!r} is not a plan actor"
                    )
                mine = inputs.get(actor, [])
                if len(mine) != 1:
                    raise DecisionError(
                        AUTHORITY_SET_INVALID,
                        f"{node_id!r}: actor {actor!r} has {len(mine)} proposal inputs, not one",
                    )
                candidates[actor] = mine[0]
            schemas = {proposals.contract(parse).schema.ref for parse in candidates.values()}
            if len(schemas) != 1:
                raise DecisionError(
                    ACTION_SCHEMA_INVALID,
                    f"{node_id!r}: candidates follow different proposal schemas {sorted(schemas)}",
                )
            if rule in VOTE_RULES:
                # SV-08: votes are equal by canonical form and a parser never coerces,
                # so `4` and `4.0` of a `number` field would be two actions of one number
                voted = proposals.contract(next(iter(candidates.values()))).schema
                loose = sorted(name for name, kind in voted.fields.items() if kind == "number")
                if loose:
                    raise DecisionError(
                        ACTION_SCHEMA_INVALID,
                        f"{node_id!r}: {rule} counts equal proposals by canonical form, and "
                        f"`number` field(s) {loose} of {voted.ref} spell one number two ways "
                        "(4 and 4.0); declare them integer or string",
                    )
            config = _frozen(dict(decl.config), AUTHORITY_SET_INVALID, "decision rule config")
            contract = DecisionContractV1(
                node_id,
                rule,
                tuple(sorted(authority)),
                MappingProxyType(candidates),
                MappingProxyType(config),
                _policy(decl.on_unresolved, node_id),
            )
            if rule in BUILTIN_RULES:
                BUILTIN_RULES[rule].check(contract.authority, contract.config)
            contracts[node_id] = contract
        for node_id in sorted(decision_nodes - set(contracts)):
            raise DecisionError(RULE_NOT_REGISTERED, f"decision {node_id!r} has no rule contract")
        return DecisionContractSetV1(contracts)


@dataclass(frozen=True)
class DecisionContractSetV1:
    """The resolved P07 contracts of one plan, keyed by decision node."""

    contracts: Mapping[str, DecisionContractV1]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contracts", MappingProxyType(dict(sorted(self.contracts.items())))
        )

    def contract(self, node_id: Any) -> DecisionContractV1:
        if not isinstance(node_id, str) or node_id not in self.contracts:
            raise DecisionError(
                RULE_NOT_REGISTERED, f"decision {node_id!r} has no plan rule contract"
            )
        return self.contracts[node_id]

    def declarations(self) -> list[DecisionDeclV1]:
        return [
            DecisionDeclV1(c.node_id, c.rule, c.authority, c.config, c.on_unresolved.value)
            for c in self.contracts.values()
        ]

    def require_protocol(
        self,
        protocol: ProtocolIR,
        actors: ActorBindingSetV1,
        proposals: ProposalContractSetV1,
    ) -> None:
        """The contracts re-derive from the plan's IR, actors and P06 contracts."""

        resolved = DecisionRegistryV1(self.declarations()).resolve(protocol, actors, proposals)
        if resolved.document() != self.document():
            raise DecisionError(
                DECISION_LINEAGE_MISMATCH, "decision contracts do not re-derive from the plan"
            )

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SET_SCHEMA,
            "contracts": [contract.document() for contract in self.contracts.values()],
        }

    @classmethod
    def from_document(cls, document: Any) -> DecisionContractSetV1:
        """Read one ``bvl-decision-contract-set-1`` back (closed shape).

        The authority mapping is re-derived against the plan by
        ``require_protocol``; this reader only restores the frozen values.
        """

        if (
            not isinstance(document, Mapping)
            or set(document) != {"schema", "contracts"}
            or document["schema"] != CONTRACT_SET_SCHEMA
            or not isinstance(document["contracts"], list)
        ):
            raise DecisionError(DECISION_LINEAGE_MISMATCH, f"not a {CONTRACT_SET_SCHEMA}")
        keys = {"schema", "node_id", "rule", "authority", "candidates", "config", "on_unresolved"}
        contracts: dict[str, DecisionContractV1] = {}
        for item in document["contracts"]:
            if (
                not isinstance(item, Mapping)
                or set(item) != keys
                or item["schema"] != CONTRACT_SCHEMA
                or not isinstance(item["authority"], list)
                or not isinstance(item["candidates"], Mapping)
                or not isinstance(item["config"], Mapping)
            ):
                raise DecisionError(DECISION_LINEAGE_MISMATCH, "a contract has the wrong shape")
            contracts[item["node_id"]] = DecisionContractV1(
                item["node_id"],
                item["rule"],
                tuple(item["authority"]),
                MappingProxyType(dict(item["candidates"])),
                MappingProxyType(dict(item["config"])),
                _policy(item["on_unresolved"], item["node_id"]),
            )
        parsed = cls(contracts)
        if parsed.document() != _frozen(dict(document), DECISION_LINEAGE_MISMATCH, "contracts"):
            raise DecisionError(DECISION_LINEAGE_MISMATCH, "contract set is not canonical")
        return parsed


# ---------------------------------------------------------------- runtime settlement
@dataclass(frozen=True)
class SettledDecisionV1:
    """The kernel's settled decision: what a Decision Artifact records."""

    outcome: DecisionOutcome
    selected: str | None  # selected candidate's proposal identity (SELECTED)
    supporting: tuple[str, ...]  # proposal identities carrying the action, sorted
    action: Mapping[str, Any]
    tally: Mapping[str, Any]
    reason: Mapping[str, str] | None  # {"code", "detail"} for NO_ACTION / FAILED


def orderings(candidates: tuple[CandidateV1, ...]) -> list[tuple[CandidateV1, ...]]:
    """The candidate orders a rule must decide identically (canonical first)."""

    if len(candidates) <= _FULL_PERMUTATIONS:
        return list(itertools.permutations(candidates))
    rotations = [candidates[i:] + candidates[:i] for i in range(len(candidates))]
    return rotations + [tuple(reversed(order)) for order in rotations]


def _outcome_document(outcome: Any) -> Any:
    if not isinstance(outcome, RuleOutcomeV1):
        return {"not_a_rule_outcome": repr(outcome)}
    try:
        return json.loads(canonical_json(outcome.document()))
    except (CanonicalisationError, TypeError, ValueError):
        return {"not_canonical": repr(outcome)}


def run_rule(
    rule: DecisionRuleV1,
    contract: DecisionContractV1,
    candidates: tuple[CandidateV1, ...],
) -> RuleOutcomeV1:
    """Run *rule* contained and pure on every candidate order; refuse order dependence."""

    canonical = tuple(sorted(candidates, key=lambda c: c.actor))
    config = dict(contract.config)

    def every_order(plugin: DecisionRuleV1) -> list[Any]:
        plugin.check(contract.authority, dict(config))
        return [plugin.decide(order, dict(config)) for order in orderings(canonical)]

    try:
        outcomes = invoke_pure(
            DECISION_RULE,
            rule,
            every_order,
            lambda found: [_outcome_document(o) for o in found],
        )
    except (ContainmentViolationV2, DecisionError):
        raise
    except Exception as error:  # noqa: BLE001 - a rule defect is a decision failure
        session = active_session()
        if session is not None:
            session.check()  # a recorded containment violation outranks the defect
        raise DecisionError(
            DECISION_RULE_FAILED, f"rule {contract.rule} raised {type(error).__name__}: {error}"
        ) from error
    session = active_session()
    if session is not None:
        session.check()
    documents = [_outcome_document(outcome) for outcome in outcomes]
    if any(document != documents[0] for document in documents):
        raise DecisionError(
            AUTHORITY_BY_ORDER_FORBIDDEN,
            f"rule {contract.rule} decides differently when the same proposals arrive "
            "in another order",
        )
    if not isinstance(outcomes[0], RuleOutcomeV1) or "not_canonical" in documents[0]:
        raise DecisionError(
            DECISION_RULE_FAILED, f"rule {contract.rule} returned no canonical RuleOutcomeV1"
        )
    return outcomes[0]


def settle(
    contract: DecisionContractV1,
    candidates: tuple[CandidateV1, ...],
    outcome: RuleOutcomeV1,
    schema: ProposalSchemaV1,
) -> SettledDecisionV1:
    """Kernel-owned validation of a rule outcome + the declared unresolved policy."""

    by_actor = {candidate.actor: candidate for candidate in candidates}
    if sorted(by_actor) != list(contract.authority):
        raise DecisionError(AUTHORITY_SET_INVALID, "candidates are not exactly the authority")
    tally = _frozen(dict(outcome.tally), DECISION_RULE_FAILED, "rule tally")

    def rule_failed(detail: str) -> DecisionError:
        return DecisionError(DECISION_RULE_FAILED, f"rule {contract.rule}: {detail}")

    supporting = tuple(outcome.supporting)
    if outcome.kind == "UNRESOLVED":
        if outcome.code not in UNRESOLVED_CODES:
            raise rule_failed(f"unresolved code {outcome.code!r} is not one of {UNRESOLVED_CODES}")
        reason = {"code": outcome.code, "detail": str(outcome.detail)}
        if contract.on_unresolved is UnresolvedPolicy.NO_ACTION:
            return SettledDecisionV1(DecisionOutcome.NO_ACTION, None, (), {}, tally, reason)
        return SettledDecisionV1(DecisionOutcome.FAILED, None, (), {}, tally, reason)
    if outcome.kind not in ("SELECTED", "AGGREGATE"):
        raise rule_failed(f"outcome kind {outcome.kind!r} is not SELECTED/AGGREGATE/UNRESOLVED")
    if not supporting or len(set(supporting)) != len(supporting) or any(
        actor not in by_actor or by_actor[actor].verdict != "VALID" for actor in supporting
    ):
        raise rule_failed("supporting actors are not distinct VALID candidates")
    action = _frozen(dict(outcome.action or {}), ACTION_SCHEMA_INVALID, "decided action")
    problems = schema.problems(action)
    if problems:
        raise DecisionError(
            ACTION_SCHEMA_INVALID, f"decided action violates {schema.ref}: {'; '.join(problems)}"
        )
    proposals = tuple(sorted(by_actor[actor].proposal for actor in supporting))
    if outcome.kind == "SELECTED":
        if supporting != (outcome.selected,) or action != dict(by_actor[outcome.selected].value):
            raise rule_failed("a SELECTED outcome is exactly the selected candidate's proposal")
        return SettledDecisionV1(
            DecisionOutcome.SELECTED, proposals[0], proposals, action, tally, None
        )
    if outcome.selected is not None:
        raise rule_failed("an AGGREGATE outcome selects no single proposal")
    return SettledDecisionV1(DecisionOutcome.AGGREGATE, None, proposals, action, tally, None)


def candidate_document(candidate: CandidateV1, node_id: str, identity: Any) -> dict[str, Any]:
    return {
        "actor": candidate.actor,
        "node": node_id,
        "proposal": identity,
        "verdict": candidate.verdict,
        "value": dict(candidate.value),
    }


# ---------------------------------------------------------------- verification
def committed_decision_problems(
    document: Mapping[str, Any],
    contract: DecisionContractV1,
    upstream: Mapping[str, Mapping[str, Any] | None],
    schema: ProposalSchemaV1,
    key: Callable[[Any], str],
) -> list[str]:
    """Verifier check of one committed decision-2 against its plan contract.

    *upstream* maps each candidate parse node to the proposal evidence its IR
    step committed (or None).  Builtin rules are recomputed from that evidence
    (P07 §10); a registered third-party rule's outcome is checked for kernel
    settlement consistency only.
    """

    def mismatch(detail: str) -> list[str]:
        return [f"{DECISION_LINEAGE_MISMATCH}: {detail}"]

    if document.get("contract") != contract.document():
        return mismatch("decision contract is not the plan's")
    if document.get("rule") != contract.rule:
        return mismatch("decision rule is not the plan's")
    candidates: list[CandidateV1] = []
    expected: list[dict[str, Any]] = []
    for actor, node_id in sorted(contract.candidates.items()):
        proposal = upstream.get(node_id)
        if proposal is None or proposal.get("verdict") not in ("VALID", "NO_ACTION"):
            return mismatch(f"candidate {actor!r} has no committed proposal of {node_id!r}")
        candidate = CandidateV1(
            actor, key(proposal["identity"]), proposal["verdict"], proposal["value"]
        )
        candidates.append(candidate)
        expected.append(candidate_document(candidate, node_id, proposal["identity"]))
    if document.get("candidates") != expected:
        return mismatch("decision candidates are not the IR's committed proposals")
    ids = {candidate.proposal: candidate for candidate in candidates}
    by_key = {key(c["proposal"]): c["proposal"] for c in expected}
    rule = BUILTIN_RULES.get(contract.rule)
    if rule is not None:
        try:
            settled = settle(
                contract, tuple(candidates), rule.decide(tuple(candidates), contract.config), schema
            )
        except DecisionError as error:
            return mismatch(f"builtin rule does not settle on the evidence: {error}")
        recomputed = {
            "outcome": settled.outcome.value,
            "selected_proposal": by_key.get(settled.selected),
            "supporting_proposals": [by_key[p] for p in settled.supporting],
            "requested_action": dict(settled.action),
            "tally": dict(settled.tally),
            "reason": None if settled.reason is None else dict(settled.reason),
        }
        found = {name: document.get(name) for name in recomputed}
        if found != recomputed:
            return mismatch(f"builtin rule recomputes {recomputed}, artifact holds {found}")
        if settled.outcome is DecisionOutcome.FAILED:
            return mismatch("a FAILED decision was committed")
        return []
    # third-party rule: settlement consistency only
    outcome = document.get("outcome")
    supporting = [key(p) for p in document.get("supporting_proposals") or []]
    action = document.get("requested_action")
    if outcome in (DecisionOutcome.SELECTED.value, DecisionOutcome.AGGREGATE.value):
        if (
            not supporting
            or supporting != sorted(set(supporting))
            or any(p not in ids or ids[p].verdict != "VALID" for p in supporting)
            or schema.problems(action)
        ):
            return mismatch("decided action/supporting proposals are not settled candidates")
        selected = document.get("selected_proposal")
        if outcome == DecisionOutcome.SELECTED.value and (
            selected is None
            or [key(selected)] != supporting
            or dict(ids[supporting[0]].value) != action
        ):
            return mismatch("SELECTED decision is not its selected candidate's proposal")
        if outcome == DecisionOutcome.AGGREGATE.value and selected is not None:
            return mismatch("AGGREGATE decision names a selected proposal")
        return []
    if outcome == DecisionOutcome.NO_ACTION.value:
        reason = document.get("reason") or {}
        if (
            contract.on_unresolved is not UnresolvedPolicy.NO_ACTION
            or action != {}
            or reason.get("code") not in UNRESOLVED_CODES
        ):
            return mismatch("NO_ACTION decision outside its declared policy")
        return []
    return mismatch(f"a {outcome!r} decision was committed")
