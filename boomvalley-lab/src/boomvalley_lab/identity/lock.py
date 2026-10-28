"""The experiment lock: the frozen pre-execution design later phases trust.

    lock(declaration document) -> lock document
        parse + validate (DeclarationError on any problem)
        -> canonicalise -> contract / design / schedule identities -> lock

The lock document (`boomvalley-lab-lock-1`) carries the canonical declaration
body itself, so its identities can always be recomputed from what it contains.
It holds no runtime evidence. Its canonical bytes (`lock_bytes`) are the
stored form: deterministic, versioned, not signed (D4 — operational tamper
evidence, not cryptographic assurance).

    verify_lock(lock document, declaration document=None) -> [Finding]
        never trusts a stored digest: re-parses the embedded declaration,
        recomputes all three identities and compares; with a declaration,
        also checks it is the locked one (by identity, so canonical-order-only
        differences match and any semantic difference does not).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import BoomvalleyError, DeclarationError
from boomvalley_lab.core.verdict import Finding, Verdict
from boomvalley_lab.core.versions import version_document
from boomvalley_lab.declare.experiment import Experiment, load
from boomvalley_lab.identity.derive import (
    contract_identity,
    denominator_document,
    design_identity,
    schedule_identity,
)

LOCK_SCHEMA = "boomvalley-lab-lock-1"


def summary(experiment: Experiment) -> dict:
    records = experiment.records
    replicates = {experiment.replication.replicates(c) for c in experiment.cells.cells}
    families = {}
    for name, rules in (("execution_expectations", experiment.execution_expectations),
                        ("artifact_provenance_rules", experiment.artifact_rules),
                        ("derivation_expectations", experiment.derivation_expectations)):
        if rules is not None:
            families[name] = {"rules": len(rules.rules),
                              "covered_cells": rules.covered(experiment.cells)}
    return {
        "factors": {f.name: len(f.levels) for f in experiment.factors},
        "cells": len(experiment.cells.cells),
        "cell_space": "explicit" if experiment.cells.explicit else "full_product",
        "execution_records": len(records),
        "replication": {
            "form": "uniform" if experiment.replication.uniform is not None else "stratified",
            "min": min(replicates), "max": max(replicates),
        },
        "schedule": "declared" if experiment.schedule.declared else "canonical",
        "analysis_views": [
            {"name": v.name, "basis": v.basis.value, "units": len(v.units(records))}
            for v in experiment.views
        ],
        "denominator": denominator_document(experiment),
        "relation": (
            {"view": experiment.relation.view, "roles": list(experiment.relation.roles),
             "invariant": experiment.relation.invariant is not None}
            if experiment.relation else None
        ),
        "assignment_mechanisms": [
            {"name": m.name, "units": len(m.unit.group((r.key, r.coordinates())
                                                       for r in records))}
            for m in experiment.mechanisms or ()
        ] or None,
        "expectation_families": families or None,
        "upstream_stages": (list(experiment.upstream_stages)
                            if experiment.upstream_stages else None),
        "analysis_binding": (experiment.analysis_binding.plugin
                             if experiment.analysis_binding else None),
    }


def lock(declaration: Mapping[str, Any]) -> dict:
    """Validate a declaration document and return its lock document."""
    experiment = load(declaration)
    return {
        "lock_schema": LOCK_SCHEMA,
        "versions": version_document(),
        "declaration": experiment.to_document(),
        "identities": {
            "contract": str(contract_identity(experiment).digest),
            "design": str(design_identity(experiment).digest),
            "schedule": str(schedule_identity(experiment).digest),
        },
        "summary": summary(experiment),
    }


def lock_bytes(lock_document: Mapping[str, Any]) -> bytes:
    """The stored, canonical form of a lock."""
    return canonical_bytes(lock_document)


def verify_lock(lock_document: Any, declaration: Mapping[str, Any] | None = None
                ) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(lock_document, Mapping) or lock_document.get("lock_schema") != LOCK_SCHEMA:
        return [Finding("lock_schema", Verdict.VIOLATED, ("not a boomvalley-lab-lock-1 document",))]
    try:
        locked = load(lock_document.get("declaration"))
    except BoomvalleyError as error:
        return [Finding("lock_declaration", Verdict.VIOLATED, (f"embedded declaration: {error}",))]
    recomputed = {
        "contract": str(contract_identity(locked).digest),
        "design": str(design_identity(locked).digest),
        "schedule": str(schedule_identity(locked).digest),
    }
    stored = lock_document.get("identities") or {}
    for kind, value in recomputed.items():
        if stored.get(kind) == value:
            findings.append(Finding(f"lock_{kind}_identity", Verdict.VERIFIED))
        else:
            findings.append(Finding(
                f"lock_{kind}_identity", Verdict.VIOLATED,
                (f"stored {stored.get(kind)!r}, recomputed {value}",),
            ))
    if declaration is None:
        findings.append(Finding("declaration_matches_lock", Verdict.NO_CLAIM))
        return findings
    try:
        candidate = load(declaration)
    except DeclarationError as error:
        findings.append(Finding("declaration_matches_lock", Verdict.VIOLATED,
                                (f"declaration: {error}",)))
        return findings
    differences = [
        kind for kind, identity in (
            ("contract", contract_identity(candidate)),
            ("design", design_identity(candidate)),
            ("schedule", schedule_identity(candidate)),
        ) if str(identity.digest) != recomputed[kind]
    ]
    findings.append(Finding(
        "declaration_matches_lock",
        Verdict.VIOLATED if differences else Verdict.VERIFIED,
        tuple(f"{kind} identity differs from the lock" for kind in differences),
    ))
    return findings
