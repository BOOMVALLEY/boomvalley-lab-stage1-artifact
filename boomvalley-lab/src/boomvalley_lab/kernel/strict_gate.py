"""P08 strict gate: one pre-execution gate-2 decision from durable inputs (T1-007).

The strict gate decides a frozen semantic plan before any actor call:

    reasons = coverage_refusals(attestation, plan)        P09-ERF (T1-006)
            + result_set_refusals(required set, results)  GNDCRW comparison set
            + plugin_refusals(plan, parsers, rules)       P06 / P07 preflight
    -> GateDecisionV2(plan, coverage identity, GNDCRWResultSetIdentity,
                      STRICT_GATE_POLICY, CLEARED iff no reason)

Plugin preflight resolves every plan parser contract (P06) and decision rule
contract (P07) against the implementations the run will execute, with the
same codes the step handlers use after a call (BVL-PROP-001/002,
BVL-DEC-001/002), so an unregistered or mis-identified plugin refuses the run
with zero calls instead of failing an episode mid-way.

A REFUSED decision opens nothing: ``open_run_v2`` journals RUN_REFUSED and no
scientific call or World transition is authorized.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.kernel.comparison import (
    GNDCRWResultSetV1,
    attestation_subjects,
    result_set_refusals,
)
from boomvalley_lab.kernel.coverage import CoverageAttestationV1, coverage_refusals
from boomvalley_lab.kernel.decisions import (
    BUILTIN_RULES,
    RULE_IDENTITY_MISMATCH,
    RULE_NOT_REGISTERED,
    DecisionContractSetV1,
)
from boomvalley_lab.kernel.gate import GateDecisionV2
from boomvalley_lab.kernel.identity import PlanIdentity
from boomvalley_lab.kernel.proposals import (
    PARSER_IDENTITY_MISMATCH,
    PARSER_NOT_REGISTERED,
    ProposalContractSetV1,
)

STRICT_GATE_POLICY = "bvl.p08-strict-gate:1"
PLUGIN_PREFLIGHT_FAILED = "BVL-GATE-006"


def _resolve(code_missing: str, code_identity: str, node: str, plugin: str,
             implementations: Mapping[str, Any]) -> list[str]:
    implementation = implementations.get(plugin)
    if implementation is None:
        return [f"{code_missing}:{node}:{plugin} is not registered"]
    reported = getattr(implementation, "plugin_identity", None)
    if reported != plugin:
        return [f"{code_identity}:{node}:implementation is {reported!r}"]
    return []


def plugin_refusals(
    plan_document: Mapping[str, Any],
    *,
    parsers: Mapping[str, Any] | None = None,
    rules: Mapping[str, Any] | None = None,
) -> list[str]:
    """Every plan parser / rule contract resolves to its implementation, pre-call."""

    reasons: list[str] = []
    try:
        if "proposals" in plan_document:
            proposals = ProposalContractSetV1.from_document(plan_document["proposals"])
            for node, contract in proposals.contracts.items():
                reasons += _resolve(PARSER_NOT_REGISTERED, PARSER_IDENTITY_MISMATCH, node,
                                    contract.parser, dict(parsers or {}))
        if "decisions" in plan_document:
            decisions = DecisionContractSetV1.from_document(plan_document["decisions"])
            available = {**BUILTIN_RULES, **dict(rules or {})}
            for node, contract in decisions.contracts.items():
                reasons += _resolve(RULE_NOT_REGISTERED, RULE_IDENTITY_MISMATCH, node,
                                    contract.rule, available)
    except BoomvalleyError as error:
        reasons.append(f"{PLUGIN_PREFLIGHT_FAILED}:plan:{error}")
    return reasons


@dataclass(frozen=True)
class StrictGateV1:
    """One strict gate-2 decision and the durable inputs it was decided on."""

    gate: GateDecisionV2
    coverage: Mapping[str, Any]
    gndcrw_results: Mapping[str, Any]


def decide_strict_gate_v2(
    plan_document: Mapping[str, Any],
    attestation: CoverageAttestationV1,
    results: GNDCRWResultSetV1,
    *,
    parsers: Mapping[str, Any] | None = None,
    rules: Mapping[str, Any] | None = None,
    policy_identity: str = STRICT_GATE_POLICY,
) -> StrictGateV1:
    """Decide gate-2 for *plan_document* (pure: no call, no journal, no write)."""

    plan = PlanIdentity.of_payload(plan_document)
    reasons = [
        *coverage_refusals(attestation, plan),
        *result_set_refusals(attestation_subjects(attestation), attestation.identity(), results),
        *plugin_refusals(plan_document, parsers=parsers, rules=rules),
    ]
    reasons = list(dict.fromkeys(reasons))
    gate = GateDecisionV2(
        plan=plan,
        coverage=attestation.identity(),
        gndcrw_results=results.identity(),
        policy_identity=policy_identity,
        cleared=not reasons,
        reasons=tuple(reasons),
    )
    return StrictGateV1(gate, attestation.document(), results.document())
