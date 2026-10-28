"""The experiment declaration: one strict document in, one frozen model out.

Document (`boomvalley-lab-declaration-1`), every other key refused:

    schema                       "boomvalley-lab-declaration-1"
    experiment                   {id, title?, description?}
    factors                      [{name, levels}]                       required
    cells                        [{factor: level, ...}]    absent = full product
    replication                  {uniform: n} | {strata: [f], counts: [{stratum, replicates}]}
    schedule                     [record key, ...]         absent = canonical order
    denominator_policy           {policy: FULL_FACTOR} | {policy: DECLARED_FACTORS, factors}
    analysis_views               [{name, unit, basis, units?}]   absent = one default view
    relation                     {view?, role_factor, roles, invariant?}
    assignment_mechanisms        [{name, unit, assigned}]
    upstream_stages              [name, ...]
    execution_expectations       [{select, expect: {model_identity, adapter_provenance}}]
    artifact_provenance_rules    [{select, required_provenance, foreign_markers?}]
    derivation_expectations      [{select, parent_stage, parent_overrides?, transform}]
    failure_policy               {…MVP values…, design_text?}
    analysis_binding             {plugin, version?, parameters?}

Absent sections take their one written meaning (`declare.sections`). There is
no field for conditional cells, branching, runtime-created cells or adaptive
schedules (R22/R25 are out of MVP): such a key is an unknown key and refused.

`Experiment.from_document` parses structure; `validate` runs the semantic
checks in a fixed order and returns every problem found at the first failing
stage. `load` = both, raising DeclarationError with the problems.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.errors import UNSUPPORTED_SCHEMA, DeclarationError
from boomvalley_lab.declare.cellspace import (
    CellSpace,
    ExecutionRecord,
    Factor,
    Factors,
    Replication,
    Schedule,
    execution_records,
)
from boomvalley_lab.declare.collection import NamedCollection
from boomvalley_lab.declare.document import section
from boomvalley_lab.declare.names import REPLICATE, check_name
from boomvalley_lab.declare.policy import AnalysisBinding, FailurePolicy
from boomvalley_lab.declare.projection import Projection
from boomvalley_lab.declare.rules import (
    ArtifactPolicy,
    DerivationExpected,
    ExecutionExpected,
    RuleSet,
    artifact_rule_parse,
    derivation_problems,
    derivation_rule_parse,
    execution_rule_parse,
)
from boomvalley_lab.declare.structure import (
    AnalysisView,
    AssignmentMechanism,
    CountingBasis,
    Denominator,
    DenominatorPolicy,
    Relation,
    assignment_problems,
    denominator_expectation,
    relation_problems,
)

SCHEMA = "boomvalley-lab-declaration-1"
DEFAULT_VIEW = "default"

SECTIONS = (
    "schema", "experiment", "factors", "cells", "replication", "schedule",
    "denominator_policy", "analysis_views", "relation", "assignment_mechanisms",
    "upstream_stages", "execution_expectations", "artifact_provenance_rules",
    "derivation_expectations", "failure_policy", "analysis_binding",
)


@dataclass(frozen=True)
class ExperimentMeta:
    id: str
    title: str | None = None
    description: str | None = None

    def document(self) -> dict:
        return {"id": self.id, "title": self.title, "description": self.description}


@dataclass(frozen=True)
class Experiment:
    meta: ExperimentMeta
    factors: Factors
    cells: CellSpace
    replication: Replication
    schedule: Schedule
    denominator: Denominator
    views: NamedCollection[AnalysisView]
    views_declared: bool
    relation: Relation | None
    mechanisms: NamedCollection[AssignmentMechanism] | None
    upstream_stages: tuple[str, ...] | None
    execution_expectations: RuleSet[ExecutionExpected] | None
    artifact_rules: RuleSet[ArtifactPolicy] | None
    derivation_expectations: RuleSet[DerivationExpected] | None
    failure_policy: FailurePolicy
    analysis_binding: AnalysisBinding | None

    # ------------------------------------------------------------------ parse
    @classmethod
    def from_document(cls, document: Any) -> Experiment:
        if not isinstance(document, Mapping):
            raise DeclarationError("a declaration is a mapping of sections")
        unknown = sorted(set(document) - set(SECTIONS))
        if unknown:
            raise DeclarationError(
                f"unknown declaration sections {unknown}; the MVP declaration has "
                f"{list(SECTIONS)} (outcome-dependent designs are out of MVP)"
            )
        if document.get("schema") != SCHEMA:
            raise DeclarationError(f"schema must be {SCHEMA!r}, got {document.get('schema')!r}",
                                   code=UNSUPPORTED_SCHEMA)
        meta = _meta(document.get("experiment"))
        factors = Factors(_factor(entry, i) for i, entry in enumerate(_list(document, "factors")))
        cells_doc = document.get("cells")
        if cells_doc is not None and not isinstance(cells_doc, list):
            raise DeclarationError("cells is a list of {factor: level} mappings")
        cells = CellSpace.build(factors, cells_doc)
        replication = _replication(document.get("replication"))
        replication.check(factors, cells)
        records = execution_records(cells, replication)
        schedule_doc = document.get("schedule")
        if schedule_doc is not None and (
            not isinstance(schedule_doc, list) or not all(isinstance(k, str) for k in schedule_doc)
        ):
            raise DeclarationError("schedule is a list of execution record keys")
        schedule = Schedule.build(records, schedule_doc)
        denominator = _denominator(document.get("denominator_policy"), factors)
        views_doc = document.get("analysis_views")
        if views_doc is None:
            views = NamedCollection.of(
                [AnalysisView.of(DEFAULT_VIEW, [*factors.names, REPLICATE],
                                 CountingBasis.EXECUTION_RECORD.value)], what="analysis view")
        else:
            views = NamedCollection.of(
                [_view(entry, i) for i, entry in enumerate(_nonempty(views_doc, "analysis_views"))],
                what="analysis view",
            )
        for view in views:
            factors.check_projection(view.unit, f"view {view.name!r}", allow_replicate=True)
        relation = _relation(document.get("relation"), views)
        mechanisms = None
        if document.get("assignment_mechanisms") is not None:
            mechanisms = NamedCollection.of(
                [_mechanism(entry, i) for i, entry in enumerate(
                    _nonempty(document["assignment_mechanisms"], "assignment_mechanisms"))],
                what="assignment mechanism",
            )
        stages = None
        if document.get("upstream_stages") is not None:
            stages_doc = _nonempty(document["upstream_stages"], "upstream_stages")
            stages = tuple(sorted(check_name(s, "an upstream stage") for s in stages_doc))
            if len(set(stages)) != len(stages):
                raise DeclarationError("upstream_stages lists a stage twice")
        return cls(
            meta=meta, factors=factors, cells=cells, replication=replication,
            schedule=schedule, denominator=denominator, views=views,
            views_declared=views_doc is not None, relation=relation, mechanisms=mechanisms,
            upstream_stages=stages,
            execution_expectations=_rules(document, "execution_expectations",
                                          execution_rule_parse),
            artifact_rules=_rules(document, "artifact_provenance_rules", artifact_rule_parse),
            derivation_expectations=_rules(document, "derivation_expectations",
                                           derivation_rule_parse),
            failure_policy=FailurePolicy.from_document(section(document, "failure_policy", {})),
            analysis_binding=(AnalysisBinding.from_document(document["analysis_binding"])
                              if document.get("analysis_binding") is not None else None),
        )

    # ------------------------------------------------------------- semantics
    @property
    def records(self) -> tuple[ExecutionRecord, ...]:
        return self.schedule.order

    def validate(self) -> list[str]:
        """Semantic problems, stage by stage; later stages run only when the
        earlier ones hold (a composition report on a broken design would name
        units nobody declared)."""
        records = self.records
        problems: list[str] = []
        for view in self.views:
            units = view.units(records)
            if view.declared_units is not None and view.declared_units != len(units):
                problems.append(
                    f"view {view.name!r} declares {view.declared_units} units; its projection "
                    f"of the declared records composes {len(units)}"
                )
            try:
                denominator_expectation(self.denominator, view, records)
            except DeclarationError as error:
                problems.append(str(error))
        if problems:
            return problems
        if self.relation is not None:
            problems += relation_problems(self.relation, {v.name: v for v in self.views},
                                          self.factors, records)
        for mechanism in self.mechanisms or ():
            problems += assignment_problems(mechanism, self.factors, records)
        if problems:
            return problems
        for rules in (self.execution_expectations, self.artifact_rules,
                      self.derivation_expectations):
            if rules is not None:
                problems += rules.problems(self.factors, self.cells)
        if problems:
            return problems
        if self.derivation_expectations is not None or self.upstream_stages is not None:
            if self.derivation_expectations is None:
                problems.append("upstream_stages are declared but no derivation uses them")
            else:
                problems += derivation_problems(self.derivation_expectations,
                                                self.upstream_stages or (), self.factors,
                                                self.cells)
        return problems

    # -------------------------------------------------------------- document
    def to_document(self) -> dict:
        """The canonical declaration document (absent sections omitted)."""
        return {
            "schema": SCHEMA,
            "experiment": self.meta.document(),
            "factors": [factor.document() for factor in self.factors],
            "cells": ([cell.document() for cell in self.cells.cells]
                      if self.cells.explicit else None),
            "replication": self.replication.document(),
            "schedule": [r.key for r in self.schedule.order] if self.schedule.declared else None,
            "denominator_policy": self.denominator.document(),
            "analysis_views": [v.document() for v in self.views] if self.views_declared else None,
            "relation": self.relation.document() if self.relation else None,
            "assignment_mechanisms": ([m.document() for m in self.mechanisms]
                                      if self.mechanisms else None),
            "upstream_stages": list(self.upstream_stages) if self.upstream_stages else None,
            "execution_expectations": _rules_doc(self.execution_expectations),
            "artifact_provenance_rules": _rules_doc(self.artifact_rules),
            "derivation_expectations": _rules_doc(self.derivation_expectations),
            "failure_policy": self.failure_policy.document(),
            "analysis_binding": self.analysis_binding.document() if self.analysis_binding else None,
        }


def load(document: Any) -> Experiment:
    """Parse and validate; DeclarationError carries every problem found."""
    experiment = Experiment.from_document(document)
    problems = experiment.validate()
    if problems:
        raise DeclarationError(
            f"{len(problems)} declaration problem(s): {problems[0]}", problems=tuple(problems)
        )
    return experiment


# ---------------------------------------------------------------------------
# section parsers
# ---------------------------------------------------------------------------
def _keys(entry: Any, where: str, required: set[str], optional: set[str] = frozenset()
          ) -> Mapping:
    if not isinstance(entry, Mapping):
        raise DeclarationError(f"{where} is a mapping")
    missing = sorted(required - set(entry))
    unknown = sorted(set(entry) - required - set(optional))
    if missing or unknown:
        raise DeclarationError(f"{where}: missing {missing} / unknown {unknown}")
    return entry


def _list(document: Mapping, key: str) -> list:
    if key not in document:
        raise DeclarationError(f"the declaration has no {key}")
    return _nonempty(document[key], key)


def _nonempty(value: Any, key: str) -> list:
    if not isinstance(value, list) or not value:
        raise DeclarationError(f"{key} is a non-empty list (or omit the section)")
    return value


def _meta(entry: Any) -> ExperimentMeta:
    entry = _keys(entry, "experiment", {"id"}, {"title", "description"})
    check_name(entry["id"], "the experiment id")
    for key in ("title", "description"):
        if entry.get(key) is not None and not isinstance(entry[key], str):
            raise DeclarationError(f"experiment.{key} is a string")
    return ExperimentMeta(entry["id"], entry.get("title"), entry.get("description"))


def _factor(entry: Any, index: int) -> Factor:
    entry = _keys(entry, f"factors[{index}]", {"name", "levels"})
    if not isinstance(entry["levels"], list):
        raise DeclarationError(f"factors[{index}].levels is a list")
    return Factor.of(entry["name"], entry["levels"])


def _replication(entry: Any) -> Replication:
    if entry is None:
        return Replication(uniform=1)
    if not isinstance(entry, Mapping):
        raise DeclarationError("replication is a mapping")
    if set(entry) == {"uniform"}:
        return Replication(uniform=entry["uniform"])
    entry = _keys(entry, "replication", {"strata", "counts"})
    strata = Projection.onto(entry["strata"])
    counts = []
    for index, item in enumerate(_nonempty(entry["counts"], "replication.counts")):
        item = _keys(item, f"replication.counts[{index}]", {"stratum", "replicates"})
        if not isinstance(item["stratum"], Mapping) or set(item["stratum"]) != set(strata.factors):
            raise DeclarationError(
                f"replication.counts[{index}].stratum must give exactly {list(strata.factors)}"
            )
        counts.append((strata.key(item["stratum"]), item["replicates"]))
    return Replication(strata=strata, counts=tuple(counts))


def _denominator(entry: Any, factors: Factors) -> Denominator:
    if entry is None:
        return Denominator.of(DenominatorPolicy.FULL_FACTOR.value, None, factors.names)
    entry = _keys(entry, "denominator_policy", {"policy"}, {"factors"})
    return Denominator.of(entry["policy"], entry.get("factors"), factors.names)


def _view(entry: Any, index: int) -> AnalysisView:
    entry = _keys(entry, f"analysis_views[{index}]", {"name", "unit", "basis"}, {"units"})
    if not isinstance(entry["unit"], list):
        raise DeclarationError(f"analysis_views[{index}].unit is a list of factors")
    return AnalysisView.of(entry["name"], entry["unit"], entry["basis"], entry.get("units"))


def _relation(entry: Any, views: NamedCollection[AnalysisView]) -> Relation | None:
    if entry is None:
        return None
    entry = _keys(entry, "relation", {"role_factor", "roles"}, {"view", "invariant"})
    view = entry.get("view")
    if view is None:
        if len(views) != 1:
            raise DeclarationError(
                "relation: the design declares several views; say which one the relation targets"
            )
        view = views.names[0]
    if not isinstance(entry["roles"], list):
        raise DeclarationError("relation.roles is a list")
    return Relation.of(view, entry["role_factor"], entry["roles"], entry.get("invariant"))


def _mechanism(entry: Any, index: int) -> AssignmentMechanism:
    entry = _keys(entry, f"assignment_mechanisms[{index}]", {"name", "unit", "assigned"})
    if not isinstance(entry["unit"], list) or not isinstance(entry["assigned"], list):
        raise DeclarationError(f"assignment_mechanisms[{index}]: unit and assigned are lists")
    return AssignmentMechanism.of(entry["name"], entry["unit"], entry["assigned"])


def _rules(document: Mapping, key: str, parse) -> RuleSet | None:
    if document.get(key) is None:
        return None
    return RuleSet.of(key, document[key], parse)


def _rules_doc(rules: RuleSet | None) -> list | None:
    return rules.document() if rules is not None else None
