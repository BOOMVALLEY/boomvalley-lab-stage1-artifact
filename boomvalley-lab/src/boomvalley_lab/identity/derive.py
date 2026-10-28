"""Contract, design and schedule identities of a frozen declaration.

Each identity is the digest of its own canonical document (canonical-json-1,
one omission rule). The partition, derived from the frozen semantics:

    CONTRACT  the whole canonical declaration as written: experiment metadata,
              every section (including HOW the cell space and schedule were
              written — full product vs explicit list, canonical vs declared
              order), failure policy, analysis binding.

    DESIGN    the scientific design, independent of how it was written and of
              who declared it. Built from the MATERIALISED design:
                factors · the frozen cell set · replicates per cell ·
                the schedule order · denominator (policy, factors) ·
                analysis views (unit, basis, unit count) · relation +
                invariant · assignment mechanisms · upstream stages ·
                the three expectation-rule families
              Deliberately NOT in design identity (contract only):
                experiment id / title / description — naming is not design;
                analysis binding — which plugin analyses the data, not what
                  the experiment is (R14 binds results to dataset identity);
                failure policy — the single MVP policy; design_text is prose (D1).
              So the same design written as a full product or as an explicit
              list of the same cells has ONE design identity and two contract
              identities.

    SCHEDULE  the frozen execution order: [cell key, replicate] in order.
              Part of the design (order is counterbalancing), and identified
              separately because execution consumes it. Never called a
              "design digest".
"""

from __future__ import annotations

from boomvalley_lab.declare.experiment import Experiment
from boomvalley_lab.declare.structure import denominator_expectation
from boomvalley_lab.identity.kinds import ContractIdentity, DesignIdentity, ScheduleIdentity

DESIGN_DOCUMENT = "boomvalley-lab-design-1"
SCHEDULE_DOCUMENT = "boomvalley-lab-schedule-1"


def contract_document(experiment: Experiment) -> dict:
    return experiment.to_document()


def schedule_document(experiment: Experiment) -> dict:
    return {"document": SCHEDULE_DOCUMENT, "order": experiment.schedule.document()}


def design_document(experiment: Experiment) -> dict:
    views = []
    for view in experiment.views:
        views.append({
            "name": view.name, "unit": view.unit.document(), "basis": view.basis.value,
            "units": len(view.units(experiment.records)),
        })
    return {
        "document": DESIGN_DOCUMENT,
        "factors": [factor.document() for factor in experiment.factors],
        "cells": [
            {"cell": cell.document(), "replicates": experiment.replication.replicates(cell)}
            for cell in experiment.cells.cells
        ],
        "schedule": experiment.schedule.document(),
        "denominator": experiment.denominator.document(),
        "analysis_views": views,
        "relation": experiment.relation.document() if experiment.relation else None,
        "assignment_mechanisms": (
            [m.document() for m in experiment.mechanisms] if experiment.mechanisms else None
        ),
        "upstream_stages": list(experiment.upstream_stages) if experiment.upstream_stages else None,
        "execution_expectations": _rules(experiment.execution_expectations),
        "artifact_provenance_rules": _rules(experiment.artifact_rules),
        "derivation_expectations": _rules(experiment.derivation_expectations),
    }


def _rules(rules):
    return rules.document() if rules is not None else None


def contract_identity(experiment: Experiment) -> ContractIdentity:
    return ContractIdentity.of_document(contract_document(experiment))


def design_identity(experiment: Experiment) -> DesignIdentity:
    return DesignIdentity.of_document(design_document(experiment))


def schedule_identity(experiment: Experiment) -> ScheduleIdentity:
    return ScheduleIdentity.of_document(schedule_document(experiment))


def denominator_document(experiment: Experiment) -> dict:
    """Per view: the group -> count the declaration registers (for the lock)."""
    return {
        view.name: denominator_expectation(experiment.denominator, view, experiment.records)
        for view in experiment.views
    }
