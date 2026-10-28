"""P18 L1 conformance claim over one manifest-4 package (T1-GATE).

A package that verifies (``verify_package_v4``) proves that its evidence is
internally consistent.  An L1 conformance claim is stronger: it says the run
was produced from a declaration and registered plugins only, under the P08
strict gate, with every provider call accounted for and its official numbers
read from the pre-bound analysis only.  ``assess_l1_conformance_v1`` decides
that claim from the package alone (study-neutral: the plan is the only source
of expected structure), criterion by criterion:

    C1 package_verified    ``verify_package_v4`` returns no problem
    C2 declared_plan       the frozen plan binds every T1 section: P04 actors,
                           P06 proposal contracts (plan-4) for every parse node,
                           P07 decision contracts (plan-5) for every decision
                           node, the P1x analysis contract (plan-6) and the K0
                           seed tree (plan-7); every plugin the plan names is in
                           the run's bound plugin set (a kernel builtin rule is
                           kernel code, bound by the build)
    C3 strict_gate         the run's one gate-2 decision is the P08 strict
                           policy, CLEARED, over this plan, and the package
                           re-derived its ERF coverage and GNDCRW comparison set
    C4 l1_evidence         every accepted call is call-bound (evidence level L1)
                           and the dataset units re-derived
    C5 hidden_calls        zero: every transport the journal records is exactly
                           one intent, one custody acceptance and one dataset
                           call unit of a plan actor_call node by its plan
                           actor's provider and model, one per node x round
                           executed - no call outside the plan's call steps
    C6 bound_analysis      the plan pre-binds an analysis and the package holds
                           exactly its recomputation over the admitted units;
                           no other analysis is part of the claim

The claim is ``L1`` iff every criterion passes, else ``NOT_L1`` with the
failing criteria's problems.  Nothing is written.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.core.strict_json import load_bytes
from boomvalley_lab.kernel.bound_analysis import ANALYSIS_ROLE
from boomvalley_lab.kernel.decisions import BUILTIN_RULES
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CUSTODY_ACCEPTED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.l1_evidence import L1_CALL_CHECK
from boomvalley_lab.kernel.manifest4 import read_manifest4
from boomvalley_lab.kernel.package4 import (
    COVERAGE_CHECK,
    GNDCRW_CHECK,
    MANIFEST_NAME,
    verify_package_v4,
)
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.strict_gate import STRICT_GATE_POLICY

L1_CONFORMANCE_SCHEMA = "bvl-l1-conformance-1"
L1 = "L1"
NOT_L1 = "NOT_L1"
PASS = "PASS"
FAIL = "FAIL"
NOT_EVALUATED = "NOT_EVALUATED"

#: plan sections an L1 claim requires (P04, P06, P07, P1x analysis, K0 seed tree)
REQUIRED_SECTIONS = ("actors", "proposals", "decisions", "analysis", "seed")
CRITERIA = (
    ("C1", "package_verified"),
    ("C2", "declared_plan"),
    ("C3", "strict_gate"),
    ("C4", "l1_evidence"),
    ("C5", "hidden_calls"),
    ("C6", "bound_analysis"),
)


def _member_documents(root: Path, manifest: Any, role: str) -> list[Any]:
    return [load_bytes((root / member.path).read_bytes())
            for member in sorted(manifest.members, key=lambda item: item.path)
            if member.role == role]


def _nodes(plan: Mapping[str, Any], kind: NodeKind) -> list[Mapping[str, Any]]:
    return [node for node in plan["protocol"]["nodes"] if node["kind"] == kind.value]


def _declared_plan(plan: Mapping[str, Any], plugin_ids: set[str]) -> list[str]:
    problems = [f"plan binds no {section!r} section ({plan.get('schema')})"
                for section in REQUIRED_SECTIONS if section not in plan]
    if problems:
        return problems
    parse_nodes = {node["id"] for node in _nodes(plan, NodeKind.PROPOSAL_PARSE)}
    decision_nodes = {node["id"] for node in _nodes(plan, NodeKind.DECISION)}
    proposals = {c["node_id"]: c for c in plan["proposals"]["contracts"]}
    decisions = {c["node_id"]: c for c in plan["decisions"]["contracts"]}
    problems += [f"proposal_parse node {node!r} has no P06 contract"
                 for node in sorted(parse_nodes - set(proposals))]
    problems += [f"decision node {node!r} has no P07 contract"
                 for node in sorted(decision_nodes - set(decisions))]
    named: set[str] = set()
    for actor in plan["actors"]["actors"]:
        named |= {actor["profile"]["provider"], actor["profile"]["renderer"]}
    named |= {contract["parser"] for contract in proposals.values()}
    named |= {contract["rule"] for contract in decisions.values()
              if contract["rule"] not in BUILTIN_RULES}
    named |= {node["config"]["world"] for node in _nodes(plan, NodeKind.WORLD_TRANSITION)
              if "world" in node["config"]}
    problems += [f"plugin {plugin!r} named by the plan is not in the bound plugin set"
                 for plugin in sorted(named - plugin_ids)]
    return problems


def _strict_gate(gates: list[Any], plan_identity: Mapping[str, Any],
                 checks: list[str]) -> list[str]:
    if len(gates) != 1:
        return [f"an L1 run has exactly one gate-2 decision, found {len(gates)}"]
    gate = gates[0]
    problems = []
    if gate.get("policy_identity") != STRICT_GATE_POLICY:
        problems.append(f"gate-2 policy is {gate.get('policy_identity')!r}, "
                        f"not {STRICT_GATE_POLICY!r}")
    if gate.get("decision") != "CLEARED" or gate.get("reasons"):
        problems.append(f"gate-2 decision is {gate.get('decision')!r}")
    if gate.get("plan") != plan_identity:
        problems.append("gate-2 decided another plan")
    problems += [f"the package did not re-derive {check!r}"
                 for check in (COVERAGE_CHECK, GNDCRW_CHECK) if check not in checks]
    return problems


def _hidden_calls(plan: Mapping[str, Any], journal: list[dict], calls: list[Mapping],
                  episodes: list[Mapping]) -> tuple[list[str], dict[str, int]]:
    transports = Counter(r["call"] for r in journal if r["event"] == TRANSPORT_STARTED)
    intents = Counter(r["call"] for r in journal if r["event"] == CALL_INTENT_RECORDED)
    custody = Counter(r["call"] for r in journal if r["event"] == CUSTODY_ACCEPTED)
    units = Counter(f"{u['unit']['kind']}:{u['unit']['digest']}" for u in calls)
    call_nodes = {node["id"]: node["config"].get("actor")
                  for node in _nodes(plan, NodeKind.ACTOR_CALL)}
    profiles = {actor["actor_id"]: actor["profile"] for actor in plan["actors"]["actors"]}
    problems: list[str] = []
    hidden = sum(transports.values()) - sum(
        min(count, intents[call], custody[call], units[call]) for call, count in
        transports.items())
    for name, counter in (("transport", transports), ("intent", intents),
                          ("custody acceptance", custody), ("dataset call unit", units)):
        repeated = sorted(call for call, count in counter.items() if count != 1)
        problems += [f"call {call} has {counter[call]} {name}s" for call in repeated]
    if not set(transports) == set(intents) == set(custody) == set(units):
        problems.append("transports, intents, custody acceptances and dataset call units "
                        "are not one set of calls")
    positions = Counter()
    for unit in calls:
        node = unit["node"]
        if node not in call_nodes:
            problems.append(f"call unit at {node!r} is not a plan actor_call node")
            continue
        actor = call_nodes[node]
        profile = profiles.get(actor, {})
        if unit["actor_id"] != actor:
            problems.append(f"call unit at {node!r} is by {unit['actor_id']!r}, the plan "
                            f"names {actor!r}")
        if (unit["provider"], unit["model"]) != (profile.get("provider"), profile.get("model")):
            problems.append(f"call unit at {node!r} used {unit['provider']}/{unit['model']}, "
                            "not its plan actor's profile")
        positions[(unit["episode_key"], node, unit["round"])] += 1
    problems += [f"{count} calls at {position}" for position, count in positions.items()
                 if count != 1]
    # the call steps each episode executed (a timed round contract may cut its last round)
    protocol = ProtocolIR.from_document(plan["protocol"])
    expected = sum(
        protocol.executions(episode["rounds_executed"], episode.get("steps"))[node]
        for episode in episodes for node in call_nodes
    )
    if len(calls) != expected:
        problems.append(f"{len(calls)} call units for {expected} planned call steps")
    return problems, {"transports": sum(transports.values()), "planned_call_steps": expected,
                      "call_units": len(calls), "hidden_calls": hidden}


def assess_l1_conformance_v1(root: Path, *, problems: list[str] | None = None) -> dict[str, Any]:
    """Decide the P18 L1 conformance claim of the package at *root* (pure).

    *problems* is a ``verify_package_v4`` result the caller already holds.
    """

    root = Path(root)
    results: dict[str, list[str] | None] = {name: None for _, name in CRITERIA}
    counts: dict[str, int] = {}
    build: Mapping[str, Any] | None = None
    plugins: list[str] = []
    results["package_verified"] = list(verify_package_v4(root) if problems is None
                                       else problems)
    if not results["package_verified"]:
        try:
            manifest = read_manifest4(root / MANIFEST_NAME)
            (plan_document,) = _member_documents(root, manifest, "plan")
            (binding,) = _member_documents(root, manifest, "execution_binding")
            (attestation,) = _member_documents(root, manifest, "conformance_attestation")
            plan = plan_document["plan"]
            build = binding["build"]
            plugins = sorted(entry["descriptor"]["plugin_id"]
                             for entry in binding["plugin_manifest"]["plugins"])
            checks = list(attestation["checks"])
            results["declared_plan"] = _declared_plan(plan, set(plugins))
            results["strict_gate"] = _strict_gate(
                _member_documents(root, manifest, "gate"), manifest.plan.document(), checks)
            datasets = _member_documents(root, manifest, "dataset_units")
            results["l1_evidence"] = ([] if L1_CALL_CHECK in checks and len(datasets) == 1
                                      else ["the run is not call-bound (evidence level PRE_L1)"])
            if not results["declared_plan"] and not results["l1_evidence"]:
                results["hidden_calls"], counts = _hidden_calls(
                    plan, Journal2(root).read(), datasets[0]["calls"], attestation["episodes"])
            analyses = _member_documents(root, manifest, ANALYSIS_ROLE)
            results["bound_analysis"] = (
                [] if "analysis" in plan and len(analyses) == 1
                else ["the plan pre-binds no analysis: an L1 claim reports bound numbers only"]
                if "analysis" not in plan
                else [f"the package holds {len(analyses)} {ANALYSIS_ROLE} members"])
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                AttributeError) as error:
            # SV-10 (SV-03 M-15): beside what the criterion already decided, never
            # instead of it
            results["declared_plan"] = [*(results["declared_plan"] or ()),
                                        f"package does not read as an L1 run: {error}"]
    criteria = [
        {"id": key, "criterion": name,
         "status": NOT_EVALUATED if results[name] is None else FAIL if results[name] else PASS,
         "problems": list(results[name] or ())}
        for key, name in CRITERIA
    ]
    conformant = all(item["status"] == PASS for item in criteria)
    return {
        "schema": L1_CONFORMANCE_SCHEMA,
        "level": L1 if conformant else NOT_L1,
        "criteria": criteria,
        "hidden_calls": counts.get("hidden_calls"),
        "calls": counts,
        "build": None if build is None else {"code_digest": build["code_digest"],
                                             "file_count": build["file_count"]},
        "plugins": plugins,
    }
