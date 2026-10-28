"""The generic verification core (VERIFICATION_SEMANTICS, D-01..D-25).

Input: five validated, immutable contract objects. Output: one normative
`gndcrw-result/v0.1` document. The core never reads files, never talks to a
provider and never recomputes anything a renderer shows.

Every declaration rule gets exactly one finding, decided by the per-rule
ladder (VS §11.2, D-25.2). No finding hides another (VS §21-22): every rule
with a valid meaning is evaluated even when the outcome is already BLOCK.
Finding content follows the frozen per-kind table (RESULT §6.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gndcrw.contracts.catalog import TargetCatalog
from gndcrw.contracts.declaration import (
    DECLARED_CONSEQUENCE,
    EXPECTED_CHANGE,
    INVARIANT,
    Declaration,
    Rule,
)
from gndcrw.contracts.pair import Pair
from gndcrw.contracts.surface import Surface
from gndcrw.core import vocabulary as v
from gndcrw.equality import values_equal
from gndcrw.errors import ContractError

_NON_OBSERVED_REASON = {
    "MISSING": "TARGET_MISSING",
    "UNOBSERVABLE": "TARGET_UNOBSERVABLE",
    "UNSUPPORTED": "TARGET_UNSUPPORTED",
    "AMBIGUOUS": "TARGET_AMBIGUOUS",
    "ASSERTED_ONLY": "TARGET_ASSERTED_ONLY",
}
_ENTITY_SCOPES = ("ALL_COMPARABLE", "EXPLICIT_ENTITY_IDS")
_CONTAINER = {
    EXPECTED_CHANGE: "expected_changes",
    INVARIANT: "invariants",
    DECLARED_CONSEQUENCE: "declared_consequences",
}
PAIR_SUBJECT = "pair.entity_comparability"


@dataclass
class Inputs:
    declaration: Declaration
    catalog: TargetCatalog
    base: Surface
    candidate: Surface
    pair: Pair
    subject: dict


@dataclass
class _State:
    findings: list[dict] = field(default_factory=list)
    limitations: dict[str, dict] = field(default_factory=dict)

    def limit(self, code: str, subject: str, scope: list[str],
              details: dict | None = None) -> str:
        if code not in v.LIMITATION_CODES:
            raise AssertionError(code)
        lid = f"LIM::{code}::{subject}"
        self.limitations[lid] = {"limitation_id": lid, "code": code, "scope": sorted(scope),
                                 "details": details or {}}
        return lid

    def add(self, reason: str, **kwargs: Any) -> None:
        self.findings.append(_finding(reason, **kwargs))


def _finding(
    reason: str, *, finding_id: str, kind: str, level: str, rule_id: str | None = None,
    target: dict | None = None, scope: dict | None = None, expected: dict | None = None,
    observed: dict | None = None, pointers: list[str] | None = None,
    premise_refs: tuple[str, ...] | list[str] = (), limitation_refs: list[str] | None = None,
) -> dict:
    status, policy_class = v.REASONS[reason]
    v.check_legal(status, policy_class, reason)
    if kind not in v.FINDING_KINDS or level not in v.OBSERVATION_LEVELS:
        raise AssertionError((kind, level))
    return {
        "finding_version": v.FINDING_VERSION,
        "finding_id": finding_id,
        "rule_id": rule_id,
        "finding_kind": kind,
        "status": status,
        "policy_class": policy_class,
        "reason_code": reason,
        "target": target,
        "observation_level": level,
        "scope": scope,
        "expected": expected or {},
        "observed": observed or {},
        "evidence_pointers": sorted(set(pointers or [])),
        "premise_refs": sorted(premise_refs),
        "limitation_refs": sorted(limitation_refs or []),
    }


def _target(rule: Rule) -> dict:
    return {"kind": rule.target_kind, "id": rule.target_id}


def _rule_pointer(rule: Rule) -> str:
    return f"declaration/{_CONTAINER[rule.family]}/{rule.rule_id}"


def _pointers(rule: Rule, *extra: str) -> list[str]:
    out = [_rule_pointer(rule)]
    if rule.target_kind == "TARGET":
        out += [f"surface:base/targets/{rule.target_id}",
                f"surface:candidate/targets/{rule.target_id}",
                f"catalog/targets/{rule.target_id}"]
    else:
        out += ["surface:base/composition", "surface:candidate/composition",
                f"catalog/composition_targets/{rule.target_id}"]
    return out + list(extra)


# --------------------------------------------------------------------------
# ladder step 0: declaration preconditions (VS §9, D-24.1, D-25.2, D-25.3)
# --------------------------------------------------------------------------

def _level_of(rule: Rule, catalog: TargetCatalog) -> str | None:
    if rule.target_kind == "TARGET":
        desc = catalog.targets.get(rule.target_id)
        return desc.level if desc else None
    return "COMPOSITION" if rule.target_id in catalog.composition_targets else None


def _precondition_reason(rule: Rule, catalog: TargetCatalog) -> str | None:
    level = _level_of(rule, catalog)
    if level is None:
        return "INVALID_DECLARATION_TARGET"
    wanted = {EXPECTED_CHANGE: "MUST_DIFFER", INVARIANT: "MUST_EQUAL"}.get(rule.family)
    if wanted is not None and rule.operation != wanted:
        return "INVALID_DECLARATION_OPERATION"
    scope_kind = rule.scope["kind"]
    if level == "ENTITY_FIELD":
        if scope_kind not in _ENTITY_SCOPES:
            return "INVALID_DECLARATION_SCOPE"
    elif scope_kind != "WHOLE_TARGET":
        return "INVALID_DECLARATION_SCOPE"
    return None


def _normalized_scope(scope: dict) -> dict:
    if scope["kind"] == "EXPLICIT_ENTITY_IDS":
        return {"kind": scope["kind"], "entity_ids": sorted(scope["entity_ids"])}
    return {"kind": scope["kind"]}


def _preconditions(inp: Inputs, st: _State) -> list[Rule]:
    """Emit precondition findings; return the rules that have a valid meaning."""
    decl, catalog = inp.declaration, inp.catalog
    valid: list[Rule] = []
    for rule in decl.rules:
        reason = _precondition_reason(rule, catalog)
        if reason is None:
            valid.append(rule)
            continue
        pointers = [_rule_pointer(rule)]
        st.add(reason, finding_id=f"PRE::{reason}::{rule.rule_id}", rule_id=rule.rule_id,
               kind="DECLARATION_PRECONDITION", level="DECLARATION", target=_target(rule),
               scope=_normalized_scope(rule.scope),
               observed={"container": _CONTAINER[rule.family]}, pointers=pointers)

    groups: dict[tuple, list[Rule]] = {}
    for rule in valid:
        if rule.family in (EXPECTED_CHANGE, INVARIANT):
            groups.setdefault((rule.target_kind, rule.target_id, rule.scope_key), []).append(rule)
    for key in sorted(groups):
        members = groups[key]
        if {"MUST_DIFFER", "MUST_EQUAL"} <= {rule.operation for rule in members}:
            ids = sorted(rule.rule_id for rule in members)
            st.add("CONTRADICTORY_DECLARATION",
                   finding_id="PRE::CONTRADICTORY_DECLARATION::" + "+".join(ids),
                   kind="DECLARATION_PRECONDITION", level="DECLARATION",
                   target=_target(members[0]), scope=_normalized_scope(members[0].scope),
                   observed={"rule_ids": ids},
                   pointers=[_rule_pointer(rule) for rule in members])

    if not decl.expected_changes:
        st.add("NO_FOCAL_EXPECTED_CHANGE", finding_id="PRE::NO_FOCAL_EXPECTED_CHANGE::declaration",
               kind="DECLARATION_PRECONDITION", level="DECLARATION",
               pointers=["declaration/expected_changes"])

    if inp.pair.comparison_mode != decl.required_mode:
        st.add("INVALID_COMPARISON_MODE", finding_id="PRE::INVALID_COMPARISON_MODE::pair",
               kind="DECLARATION_PRECONDITION", level="PAIR",
               expected={"required_mode": decl.required_mode},
               observed={"comparison_mode": inp.pair.comparison_mode},
               pointers=["declaration/comparison", "pair/comparison_mode"])
    return valid


# --------------------------------------------------------------------------
# fidelity and provenance (D-17, D-18, D-24.7)
# --------------------------------------------------------------------------

def _fidelity(surface: Surface, side: str, st: _State) -> None:
    if surface.mode == "DIRECT":
        return  # satisfied by definition; no finding (D-17)
    equivalence = surface.assembly["equivalence"]
    if equivalence["status"] == "UNPROVEN" or equivalence["method"] != "EXACT_BYTES":
        reason = "ASSEMBLY_EQUIVALENCE_MISSING"
    elif any(item["expected"] != item["observed"] for item in equivalence["evidence"]):
        reason = "ASSEMBLY_EQUIVALENCE_MISMATCH"
    else:
        reason = "ASSEMBLY_EQUIVALENCE_PROVEN"
    st.add(reason, finding_id=f"PRE::{reason}::surface:{side}", kind="ASSEMBLY_FIDELITY",
           level="ASSEMBLY",
           observed={"surface": side, "mode": surface.mode,
                     "equivalence_status": equivalence["status"],
                     "method": equivalence["method"]},
           pointers=[f"surface:{side}/assembly"])


def _provenance(surface: Surface, side: str, st: _State) -> None:
    missing = surface.missing_provenance()
    if missing:
        st.add("REQUIRED_PROVENANCE_MISSING",
               finding_id=f"PRE::REQUIRED_PROVENANCE_MISSING::surface:{side}",
               kind="PROVENANCE", level="PROVENANCE",
               observed={"surface": side, "missing": missing},
               pointers=[f"surface:{side}/" + path.replace(".", "/") for path in missing])


# --------------------------------------------------------------------------
# entity pairing (D-24.6, D-25.1)
# --------------------------------------------------------------------------

def _scoped(rule: Rule, inp: Inputs) -> tuple[dict[str, str], list[str], int]:
    """(paired scoped BASE->CANDIDATE, unmapped scoped IDs, scoped count).

    Only called when comparability is ESTABLISHED.
    """
    pairs = inp.pair.pairs(inp.base, inp.candidate)
    if rule.scope["kind"] == "ALL_COMPARABLE":
        return pairs, [], len(pairs)
    wanted = sorted(rule.scope["entity_ids"])
    paired = {eid: pairs[eid] for eid in wanted if eid in pairs}
    unmapped = [eid for eid in wanted if eid not in pairs]
    return paired, unmapped, len(wanted)


def _differs(desc_equality: str, base_values: dict, cand_values: dict,
             pairs: dict[str, str]) -> list[str]:
    return sorted(b for b, c in pairs.items()
                  if not values_equal(desc_equality, base_values[b], cand_values[c]))


# --------------------------------------------------------------------------
# ladder steps 1-4: expected changes and invariants
# --------------------------------------------------------------------------

def _evaluate_rule(rule: Rule, inp: Inputs, st: _State) -> None:
    must_differ = rule.operation == "MUST_DIFFER"
    common = dict(finding_id=rule.rule_id, rule_id=rule.rule_id, target=_target(rule),
                  scope=_normalized_scope(rule.scope), premise_refs=rule.premise_refs)

    if rule.target_kind == "COMPOSITION":
        equal = _composition_equal(rule.target_id, inp.base, inp.candidate)
        if must_differ:
            reason = "COMPOSITION_CHANGE_MISSING" if equal else "COMPOSITION_CHANGE_ASSEMBLED"
        else:
            reason = "COMPOSITION_INVARIANT_HELD" if equal else "COMPOSITION_INVARIANT_VIOLATED"
        st.add(reason, kind="COMPOSITION", level="COMPOSITION",
               expected={"operation": rule.operation},
               observed=composition_facts(inp.base, inp.candidate),
               pointers=_pointers(rule), **common)
        return

    kind = "EXPECTED_CHANGE" if rule.family == EXPECTED_CHANGE else "INVARIANT"
    desc = inp.catalog.targets[rule.target_id]
    base_rec = inp.base.targets[rule.target_id]
    cand_rec = inp.candidate.targets[rule.target_id]
    entity = desc.level == "ENTITY_FIELD"
    expected = {"operation": rule.operation}
    if entity:
        expected["quantifier"] = "ALL_SCOPED"
    pointers = _pointers(rule, "pair/entity_comparability") if entity else _pointers(rule)

    # step 1: observability, base then candidate (ASSERTED_ONLY is non-OBSERVED here)
    for record in (base_rec, cand_rec):
        if record.observability != "OBSERVED":
            st.add(_NON_OBSERVED_REASON[record.observability], kind=kind, level=desc.level,
                   expected=expected,
                   observed={"base_observability": base_rec.observability,
                             "candidate_observability": cand_rec.observability},
                   pointers=pointers, **common)
            return

    if not entity:
        equal = values_equal(desc.equality, base_rec.value, cand_rec.value)
        st.add(_verdict(must_differ, holds=(not equal) if must_differ else equal), kind=kind,
               level=desc.level, expected=expected, observed={"equal": equal},
               pointers=pointers, **common)
        return

    # step 2: comparability
    status = inp.pair.comparability_status
    if status in ("UNKNOWN", "NOT_ESTABLISHED"):
        reason = f"ENTITY_COMPARABILITY_{status}"
        st.add(reason, kind=kind, level="ENTITY_FIELD", expected=expected,
               observed={"comparability": status}, pointers=pointers, **common)
        return

    # steps 3-4: pair set and the D-25.1 verdict
    paired, unmapped, scoped = _scoped(rule, inp)
    differing = _differs(desc.equality, base_rec.entity_values, cand_rec.entity_values, paired)
    violating = sorted(set(paired) - set(differing)) if must_differ else differing
    observed = {
        "scoped_entities": scoped,
        "comparable_entities": len(paired),
        "satisfied_entities": len(paired) - len(violating),
        "violating_entities": len(violating),
        "violating_entity_ids": violating,
        "unmapped_entity_ids": unmapped,
    }
    if violating:
        reason = _verdict(must_differ, holds=False)
    elif unmapped or not paired:
        reason = "ENTITY_MAPPING_MISSING"
    else:
        reason = _verdict(must_differ, holds=True)
    st.add(reason, kind=kind, level="ENTITY_FIELD", expected=expected, observed=observed,
           pointers=pointers, **common)


def _verdict(must_differ: bool, *, holds: bool) -> str:
    if must_differ:
        return "EXPECTED_CHANGE_ASSEMBLED" if holds else "EXPECTED_CHANGE_MISSING"
    return "INVARIANT_HELD" if holds else "INVARIANT_VIOLATED"


def composition_facts(base: Surface, candidate: Surface) -> dict:
    base_ids, cand_ids = set(base.entity_ids), set(candidate.entity_ids)
    added = sorted(cand_ids - base_ids)
    removed = sorted(base_ids - cand_ids)
    return {
        "base_count": len(base_ids),
        "candidate_count": len(cand_ids),
        "added_count": len(added),
        "removed_count": len(removed),
        "intersection_size": len(base_ids & cand_ids),
        "added_ids": added,
        "removed_ids": removed,
    }


def _composition_equal(target_id: str, base: Surface, candidate: Surface) -> bool:
    if target_id == "entity_count":
        return values_equal("JSON_STRUCTURAL", len(base.entity_ids), len(candidate.entity_ids))
    return values_equal("SET_EXACT", list(base.entity_ids), list(candidate.entity_ids))


# --------------------------------------------------------------------------
# declared consequences (VS §17, D-19, D-25.4)
# --------------------------------------------------------------------------

def _evaluate_consequence(rule: Rule, inp: Inputs, st: _State) -> None:
    common = dict(finding_id=rule.rule_id, rule_id=rule.rule_id, target=_target(rule),
                  scope=_normalized_scope(rule.scope), kind="DECLARED_CONSEQUENCE",
                  expected={"authority": rule.authority}, premise_refs=rule.premise_refs)

    if rule.target_kind == "COMPOSITION":
        equal = _composition_equal(rule.target_id, inp.base, inp.candidate)
        reason = "DECLARED_CONSEQUENCE_NOT_OBSERVED" if equal else "DECLARED_CONSEQUENCE_OBSERVED"
        st.add(reason, level="COMPOSITION", observed=composition_facts(inp.base, inp.candidate),
               pointers=_pointers(rule), **common)
        return

    desc = inp.catalog.targets[rule.target_id]
    base_rec = inp.base.targets[rule.target_id]
    cand_rec = inp.candidate.targets[rule.target_id]
    entity = desc.level == "ENTITY_FIELD"
    pointers = _pointers(rule, "pair/entity_comparability") if entity else _pointers(rule)

    limitations: list[str] = []
    asserted = [side for side, rec in (("base", base_rec), ("candidate", cand_rec))
                if rec.observability == "ASSERTED_ONLY"]
    if asserted:
        records = {"base": base_rec, "candidate": cand_rec}
        limitations.append(st.limit(
            "ASSERTED_ONLY_EVIDENCE", rule.rule_id, [rule.target_id],
            {"sides": asserted, "authorities": [records[s].authority for s in asserted]},
        ))

    def unobservable(observed: dict) -> None:
        lid = st.limit("OBSERVATION_UNAVAILABLE", rule.rule_id, [rule.target_id])
        st.add("DECLARED_CONSEQUENCE_UNOBSERVABLE", level=desc.level, observed=observed,
               pointers=pointers, limitation_refs=[*limitations, lid], **common)

    if not (base_rec.carries_value and cand_rec.carries_value):
        unobservable({"base_observability": base_rec.observability,
                      "candidate_observability": cand_rec.observability})
        return
    if entity and inp.pair.comparability_status != "ESTABLISHED":
        unobservable({"comparability": inp.pair.comparability_status})
        return

    if not entity:
        equal = values_equal(desc.equality, base_rec.value, cand_rec.value)
        reason = "DECLARED_CONSEQUENCE_NOT_OBSERVED" if equal else "DECLARED_CONSEQUENCE_OBSERVED"
        st.add(reason, level=desc.level, observed={"equal": equal}, pointers=pointers,
               limitation_refs=limitations, **common)
        return

    paired, unmapped, scoped = _scoped(rule, inp)
    differing = _differs(desc.equality, base_rec.entity_values, cand_rec.entity_values, paired)
    observed = {"scoped_entities": scoped, "comparable_entities": len(paired),
                "differing_entities": len(differing), "differing_entity_ids": differing,
                "unmapped_entity_ids": unmapped}
    if not paired:
        unobservable(observed)
    elif differing:
        st.add("DECLARED_CONSEQUENCE_OBSERVED", level=desc.level, observed=observed,
               pointers=pointers, limitation_refs=limitations, **common)
    elif unmapped:
        unobservable(observed)
    else:
        st.add("DECLARED_CONSEQUENCE_NOT_OBSERVED", level=desc.level, observed=observed,
               pointers=pointers, limitation_refs=limitations, **common)


# --------------------------------------------------------------------------
# undeclared differences (VS §18, D-21, D-24.8, D-25.7)
# --------------------------------------------------------------------------

def _undeclared(inp: Inputs, valid: list[Rule], st: _State) -> None:
    referenced = {(rule.target_kind, rule.target_id) for rule in valid}
    # D-29 (ER-03): a target referenced only through EXPLICIT_ENTITY_IDS scopes is excluded
    # only for the union of those scoped BASE IDs, not as a whole (D-24.8 superseded there).
    scoped_ids: dict[str, set[str]] = {}
    whole: set[str] = set()
    for rule in valid:
        if rule.target_kind != "TARGET":
            continue
        if rule.scope["kind"] == "EXPLICIT_ENTITY_IDS":
            scoped_ids.setdefault(rule.target_id, set()).update(rule.scope["entity_ids"])
        else:
            whole.add(rule.target_id)
    established = inp.pair.comparability_status == "ESTABLISHED"
    skipped: list[str] = []
    for target_id, desc in sorted(inp.catalog.targets.items()):
        partly = ("TARGET", target_id) in referenced
        if target_id in whole:
            continue
        base_rec = inp.base.targets[target_id]
        cand_rec = inp.candidate.targets[target_id]
        if base_rec.observability != "OBSERVED" or cand_rec.observability != "OBSERVED":
            continue  # no fabricated equality or difference; no limitation (D-25.7)
        if desc.level == "ENTITY_FIELD" and not established:
            if not partly:
                skipped.append(target_id)
            continue
        pointers = [f"surface:base/targets/{target_id}", f"surface:candidate/targets/{target_id}",
                    f"catalog/targets/{target_id}"]
        if desc.level == "ENTITY_FIELD":
            pairs = inp.pair.pairs(inp.base, inp.candidate)
            if partly:
                pairs = {b: c for b, c in pairs.items() if b not in scoped_ids[target_id]}
            differing = _differs(desc.equality, base_rec.entity_values,
                                 cand_rec.entity_values, pairs)
            if not differing:
                continue
            scope = {"kind": "ALL_COMPARABLE"}
            observed = {"comparable_entities": len(pairs), "differing_entities": len(differing),
                        "differing_entity_ids": differing}
            pointers.append("pair/entity_comparability")
        else:
            if values_equal(desc.equality, base_rec.value, cand_rec.value):
                continue
            scope = {"kind": "WHOLE_TARGET"}
            observed = {"equal": False}
        st.add("UNDECLARED_DIFFERENCE", finding_id=f"UD::TARGET::{target_id}",
               kind="UNDECLARED_DIFFERENCE", level=desc.level,
               target={"kind": "TARGET", "id": target_id}, scope=scope, observed=observed,
               pointers=pointers)
    if skipped:
        st.limit("ENTITY_UNDECLARED_SCAN_NOT_PERFORMED", "scan", skipped,
                 {"comparability": inp.pair.comparability_status})

    for target_id in sorted(inp.catalog.composition_targets):
        if ("COMPOSITION", target_id) in referenced:
            continue
        if _composition_equal(target_id, inp.base, inp.candidate):
            continue
        st.add("UNDECLARED_DIFFERENCE", finding_id=f"UD::COMPOSITION::{target_id}",
               kind="UNDECLARED_DIFFERENCE", level="COMPOSITION",
               target={"kind": "COMPOSITION", "id": target_id}, scope={"kind": "WHOLE_TARGET"},
               observed=composition_facts(inp.base, inp.candidate),
               pointers=["surface:base/composition", "surface:candidate/composition",
                         f"catalog/composition_targets/{target_id}"])


# --------------------------------------------------------------------------
# premises (D-20, D-25.8)
# --------------------------------------------------------------------------

def _premises(inp: Inputs, valid: list[Rule], st: _State) -> list[dict]:
    using: dict[str, list[str]] = {}
    for rule in valid:
        for pid in rule.premise_refs:
            using.setdefault(pid, []).append(rule.rule_id)

    decl_premises = {p["premise_id"]: p for p in inp.declaration.premises}
    premise_limits: dict[str, list[str]] = {}
    for pid in sorted(using):
        lid = st.limit("ATTRIBUTED_PREMISE_NOT_INDEPENDENTLY_VERIFIED", pid, [pid])
        premise_limits[pid] = [lid]
        st.add("ATTRIBUTED_PREMISE_USED", finding_id=f"PRE::ATTRIBUTED_PREMISE_USED::{pid}",
               kind="PREMISE", level="DECLARATION", observed={"premise_id": pid},
               pointers=[f"declaration/premises/{pid}"], premise_refs=[pid],
               limitation_refs=[lid])
    if inp.pair.comparability_method == "DECLARED_PREMISE":
        lid = st.limit("ATTRIBUTED_PREMISE_NOT_INDEPENDENTLY_VERIFIED", PAIR_SUBJECT,
                       [PAIR_SUBJECT])
        st.add("ATTRIBUTED_PREMISE_USED",
               finding_id=f"PRE::ATTRIBUTED_PREMISE_USED::{PAIR_SUBJECT}",
               kind="PREMISE", level="DECLARATION", observed={"subject": PAIR_SUBJECT},
               pointers=["pair/entity_comparability"], limitation_refs=[lid])

    records = []
    for pid, premise in decl_premises.items():
        records.append({
            "premise_id": pid,
            "statement": premise["statement"],
            "authority": premise["authority"],
            "scope": sorted(premise.get("scope", [])),
            "accepted_by_rules": sorted(using.get(pid, [])),
            "limitations": premise_limits.get(pid, []),
        })
    for surface in (inp.base, inp.candidate):
        for premise in surface.premises:
            records.append({
                "premise_id": premise["premise_id"],
                "statement": premise["statement"],
                "authority": premise["authority"],
                "scope": [],
                "accepted_by_rules": [],
                "limitations": [],
            })
    return sorted(records, key=lambda p: p["premise_id"])


# --------------------------------------------------------------------------
# aggregation and result
# --------------------------------------------------------------------------

def aggregate(findings: list[dict]) -> str:
    blocking = [f["status"] for f in findings if f["policy_class"] == v.BLOCKING]
    if v.FAIL in blocking:
        return v.BLOCK
    if v.UNVERIFIABLE in blocking:
        return v.UNVERIFIABLE
    return v.RUN


def summarize(findings: list[dict]) -> dict:
    by_status = {status: 0 for status in v.STATUSES}
    by_policy = {policy: 0 for policy in v.POLICY_CLASSES}
    for finding in findings:
        by_status[finding["status"]] += 1
        by_policy[finding["policy_class"]] += 1
    return {"finding_count": len(findings), "by_status": by_status,
            "by_policy_class": by_policy}


def _sort_key(finding: dict) -> tuple:
    target = finding["target"] or {"kind": "", "id": ""}
    return (v.POLICY_CLASSES.index(finding["policy_class"]), finding["finding_id"],
            target["kind"], target["id"])


def verify(inp: Inputs) -> dict:
    st = _State()
    valid = _preconditions(inp, st)

    if inp.pair.comparability_status == "NOT_APPLICABLE" and any(
        rule.family in (EXPECTED_CHANGE, INVARIANT) and rule.target_kind == "TARGET"
        and inp.catalog.targets[rule.target_id].level == "ENTITY_FIELD"
        for rule in valid
    ):
        raise ContractError(
            "entity_comparability NOT_APPLICABLE while a BLOCKING ENTITY_FIELD rule is in "
            "scope (D-24.6)",
            pointer="pair:/entity_comparability/status",
        )

    _fidelity(inp.base, "base", st)
    _fidelity(inp.candidate, "candidate", st)
    _provenance(inp.base, "base", st)
    _provenance(inp.candidate, "candidate", st)

    for rule in valid:
        if rule.family == DECLARED_CONSEQUENCE:
            _evaluate_consequence(rule, inp, st)
        else:
            _evaluate_rule(rule, inp, st)

    _undeclared(inp, valid, st)
    premises = _premises(inp, valid, st)

    findings = sorted(st.findings, key=_sort_key)
    ids = [f["finding_id"] for f in findings]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"duplicate finding ids {ids}")

    return {
        "result_version": v.RESULT_VERSION,
        "tool": {"name": v.TOOL_NAME, "version": v.TOOL_VERSION},
        "contracts": dict(v.CONTRACTS),
        "policy_id": v.POLICY_ID,
        "subject": inp.subject,
        "comparison_mode": inp.pair.comparison_mode,
        "outcome": aggregate(findings),
        "findings": findings,
        "premises": premises,
        "limitations": [st.limitations[key] for key in sorted(st.limitations)],
        "summary": summarize(findings),
    }
