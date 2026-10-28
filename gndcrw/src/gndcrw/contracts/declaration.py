"""ExperimentDeclaration (`gndcrw-declaration/v0.1`, DECLARATION_CONTRACT).

Only structure is decided here (DECLARATION §17 "input/contract error"). A
readable declaration that names an unknown target, a wrong scope, a
contradiction or no focal change is valid input: those are findings, and the
core produces them (D-01, D-24.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gndcrw.contracts import _check as c
from gndcrw.contracts.catalog import TargetCatalog
from gndcrw.core.vocabulary import CONTRACTS
from gndcrw.errors import ContractError
from gndcrw.jsonio import digest

DECLARATION_VERSION = CONTRACTS["declaration"]
REQUIRED_MODES = ("CONTROL", "CONFIG_PERTURBATION")
OPERATIONS = ("MUST_DIFFER", "MUST_EQUAL")
TARGET_KINDS = ("TARGET", "COMPOSITION")
SCOPE_KINDS = ("WHOLE_TARGET", "ALL_COMPARABLE", "EXPLICIT_ENTITY_IDS")
CATALOG_REF_FIELDS = ("provider_id", "catalog_id", "catalog_version", "profile_id",
                      "catalog_digest")

EXPECTED_CHANGE = "EXPECTED_CHANGE"
INVARIANT = "INVARIANT"
DECLARED_CONSEQUENCE = "DECLARED_CONSEQUENCE"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    family: str                 # EXPECTED_CHANGE | INVARIANT | DECLARED_CONSEQUENCE
    target_kind: str
    target_id: str
    operation: str | None       # None for declared consequences
    scope: dict
    premise_refs: tuple[str, ...]
    authority: dict | None = None
    justification: str | None = None

    @property
    def scope_key(self) -> tuple:
        """Normalized scope as a structured value, for contradiction grouping (D-26.8)."""
        if self.scope["kind"] == "EXPLICIT_ENTITY_IDS":
            return (self.scope["kind"], tuple(sorted(self.scope["entity_ids"])))
        return (self.scope["kind"], ())


@dataclass(frozen=True)
class Declaration:
    declaration_id: str
    intent_id: str
    intent_digest: str
    content_digest: str
    catalog_ref: dict
    required_mode: str
    expected_changes: tuple[Rule, ...]
    invariants: tuple[Rule, ...]
    declared_consequences: tuple[Rule, ...]
    premises: tuple[dict, ...]
    context: tuple[dict, ...]
    document: dict

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self.expected_changes + self.invariants + self.declared_consequences


def _normalize_rule(rule: dict) -> dict:
    out = dict(rule)
    if "premise_refs" in out:
        out["premise_refs"] = sorted(out["premise_refs"])
    scope = dict(out["scope"])
    if "entity_ids" in scope:
        scope["entity_ids"] = sorted(scope["entity_ids"])
    out["scope"] = scope
    return out


def _normalize_premise(premise: dict) -> dict:
    out = dict(premise)
    out["scope"] = sorted(out.get("scope", []))  # absent scope is [] (D-26.7)
    return out


def _normalized_lists(doc: dict) -> dict:
    def by(key: str, items: list) -> list:
        return sorted(items, key=lambda item: item[key])

    return {
        "expected_changes": by("rule_id", [_normalize_rule(r) for r in doc["expected_changes"]]),
        "invariants": by("rule_id", [_normalize_rule(r) for r in doc["invariants"]]),
        "declared_consequences": by(
            "rule_id", [_normalize_rule(r) for r in doc["declared_consequences"]]
        ),
        "premises": by("premise_id", [_normalize_premise(p) for p in doc["premises"]]),
        "context": by("context_id", list(doc["context"])),
    }


def intent_projection(doc: dict) -> dict:
    """DECLARATION §5: what the research intent is, independent of carrier."""
    lists = _normalized_lists(doc)
    return {
        "catalog_ref": doc["catalog_ref"],
        "comparison": doc["comparison"],
        "expected_changes": lists["expected_changes"],
        "invariants": lists["invariants"],
        "declared_consequences": lists["declared_consequences"],
        "premises": lists["premises"],
        "context": [ctx for ctx in lists["context"] if ctx["normative"] is True],
    }


def compute_intent_digest(doc: dict) -> str:
    return digest(intent_projection(doc))


def normalized(doc: dict) -> dict:
    """Whole declaration after set-like normalization (D-24.4); content digest preimage."""
    out = dict(doc)
    out.update(_normalized_lists(doc))
    return out


def _target(value: Any, ptr: str) -> tuple[str, str]:
    c.obj(value, ptr, ("kind", "id"))
    kind = c.enum(value["kind"], f"{ptr}/kind", TARGET_KINDS)
    return kind, c.string(value["id"], f"{ptr}/id")


def _scope(value: Any, ptr: str) -> dict:
    if not isinstance(value, dict) or "kind" not in value:
        raise ContractError("expected a scope object with 'kind'", pointer=ptr)
    kind = c.enum(value["kind"], f"{ptr}/kind", SCOPE_KINDS)
    if kind == "EXPLICIT_ENTITY_IDS":
        c.obj(value, ptr, ("kind", "entity_ids"))
        c.string_list(value["entity_ids"], f"{ptr}/entity_ids", nonempty=True)
    else:
        c.obj(value, ptr, ("kind",))
    return value


def _rules(items: Any, ptr: str, family: str) -> list[Rule]:
    out = []
    for index, raw in enumerate(c.array(items, ptr)):
        rptr = f"{ptr}/{index}"
        if family == DECLARED_CONSEQUENCE:
            c.obj(raw, rptr, ("rule_id", "target", "scope", "authority", "justification",
                              "premise_refs"))
        else:
            c.obj(raw, rptr, ("rule_id", "target", "operation", "scope", "premise_refs"))
        rule_id = c.identifier(raw["rule_id"], f"{rptr}/rule_id")
        kind, target_id = _target(raw["target"], f"{rptr}/target")
        scope = _scope(raw["scope"], f"{rptr}/scope")
        refs = c.string_list(raw["premise_refs"], f"{rptr}/premise_refs")
        if family == DECLARED_CONSEQUENCE:
            out.append(Rule(
                rule_id=rule_id, family=family, target_kind=kind, target_id=target_id,
                operation=None, scope=scope, premise_refs=tuple(sorted(refs)),
                authority=c.authority(raw["authority"], f"{rptr}/authority"),
                justification=c.any_string(raw["justification"], f"{rptr}/justification"),
            ))
        else:
            operation = c.enum(raw["operation"], f"{rptr}/operation", OPERATIONS)
            out.append(Rule(
                rule_id=rule_id, family=family, target_kind=kind, target_id=target_id,
                operation=operation, scope=scope, premise_refs=tuple(sorted(refs)),
            ))
    return out


def parse(doc: Any, catalog: TargetCatalog) -> Declaration:
    ptr = "declaration:"
    c.obj(doc, ptr, (
        "declaration_version", "declaration_id", "intent", "catalog_ref", "comparison",
        "expected_changes", "invariants", "declared_consequences", "premises", "context",
    ))
    c.const(doc["declaration_version"], f"{ptr}/declaration_version", DECLARATION_VERSION)
    declaration_id = c.string(doc["declaration_id"], f"{ptr}/declaration_id")

    intent = doc["intent"]
    c.obj(intent, f"{ptr}/intent", ("intent_id", "intent_digest"))
    intent_id = c.string(intent["intent_id"], f"{ptr}/intent/intent_id")
    declared_digest = c.digest(intent["intent_digest"], f"{ptr}/intent/intent_digest")

    ref = doc["catalog_ref"]
    c.obj(ref, f"{ptr}/catalog_ref", CATALOG_REF_FIELDS)
    for name in CATALOG_REF_FIELDS:
        c.string(ref[name], f"{ptr}/catalog_ref/{name}")
    c.digest(ref["catalog_digest"], f"{ptr}/catalog_ref/catalog_digest")

    comparison = doc["comparison"]
    c.obj(comparison, f"{ptr}/comparison", ("required_mode",))
    required_mode = c.enum(
        comparison["required_mode"], f"{ptr}/comparison/required_mode", REQUIRED_MODES
    )

    expected = _rules(doc["expected_changes"], f"{ptr}/expected_changes", EXPECTED_CHANGE)
    invariants = _rules(doc["invariants"], f"{ptr}/invariants", INVARIANT)
    consequences = _rules(
        doc["declared_consequences"], f"{ptr}/declared_consequences", DECLARED_CONSEQUENCE
    )
    rule_ids = [rule.rule_id for rule in expected + invariants + consequences]
    duplicates = sorted({rid for rid in rule_ids if rule_ids.count(rid) > 1})
    if duplicates:
        raise ContractError(f"duplicate rule_id {', '.join(duplicates)}", pointer=ptr)

    premises = c.array(doc["premises"], f"{ptr}/premises")
    premise_ids: list[str] = []
    for index, premise in enumerate(premises):
        pptr = f"{ptr}/premises/{index}"
        c.obj(premise, pptr, ("premise_id", "statement", "authority"), ("scope",))
        premise_ids.append(c.premise_identifier(premise["premise_id"], f"{pptr}/premise_id"))
        c.any_string(premise["statement"], f"{pptr}/statement")
        c.authority(premise["authority"], f"{pptr}/authority")
        if "scope" in premise:
            for rid in c.string_list(premise["scope"], f"{pptr}/scope"):
                if rid not in rule_ids:
                    raise ContractError(
                        f"premise scope references unknown rule {rid!r} (D-24.3)",
                        pointer=f"{pptr}/scope",
                    )
    if len(set(premise_ids)) != len(premise_ids):
        raise ContractError("duplicate premise_id", pointer=f"{ptr}/premises")
    for rule in expected + invariants + consequences:
        for pid in rule.premise_refs:
            if pid not in premise_ids:
                raise ContractError(
                    f"rule {rule.rule_id} references unknown premise {pid!r} (D-24.3)",
                    pointer=f"{ptr}/{rule.rule_id}/premise_refs",
                )

    context = c.array(doc["context"], f"{ptr}/context")
    context_ids: list[str] = []
    for index, entry in enumerate(context):
        xptr = f"{ptr}/context/{index}"
        c.obj(entry, xptr, ("context_id", "normative", "kind", "value"))
        context_ids.append(c.identifier(entry["context_id"], f"{xptr}/context_id"))
        c.boolean(entry["normative"], f"{xptr}/normative")
        c.string(entry["kind"], f"{xptr}/kind")
    if len(set(context_ids)) != len(context_ids):
        raise ContractError("duplicate context_id", pointer=f"{ptr}/context")

    actual_digest = compute_intent_digest(doc)
    if actual_digest != declared_digest:
        raise ContractError(
            f"intent_digest does not recompute (declared {declared_digest}, "
            f"computed {actual_digest})",
            pointer=f"{ptr}/intent/intent_digest",
        )

    # Full five-field catalog binding (DECLARATION §6). Mismatch = input error.
    expected_ref = catalog.ref()
    for name in CATALOG_REF_FIELDS:
        if ref[name] != expected_ref[name]:
            raise ContractError(
                f"catalog_ref.{name} {ref[name]!r} does not match supplied catalog "
                f"{expected_ref[name]!r}",
                pointer=f"{ptr}/catalog_ref/{name}",
            )

    return Declaration(
        declaration_id=declaration_id,
        intent_id=intent_id,
        intent_digest=declared_digest,
        content_digest=digest(normalized(doc)),
        catalog_ref=ref,
        required_mode=required_mode,
        expected_changes=tuple(sorted(expected, key=lambda r: r.rule_id)),
        invariants=tuple(sorted(invariants, key=lambda r: r.rule_id)),
        declared_consequences=tuple(sorted(consequences, key=lambda r: r.rule_id)),
        premises=tuple(sorted(premises, key=lambda p: p["premise_id"])),
        context=tuple(sorted(context, key=lambda x: x["context_id"])),
        document=doc,
    )
