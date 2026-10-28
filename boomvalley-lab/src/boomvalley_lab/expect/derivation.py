"""R43 — declared derivation vs the derivation that actually happened.

The design may state, per covered cell: which upstream stage the parent comes
from, which parent cell (the child's own coordinates with declared overrides),
and which transform identity and version must have produced it. The gate
compares that against the RECONCILED derivation record (R41 recorded, R42
resolved), never against a configuration value or a developer's intention.

    declared   {parent_stage, parent_cell, transform{identity, version}}
    actual     the same shape, read off the derivation record

Fail closed: mismatch -> VIOLATED; a covered cell whose derivation cannot be
checked (no record, unresolved parent) -> VIOLATED; a cell no rule covers ->
NO_CLAIM.

A VERIFIED derivation means the declared producer-side lineage is
reconstructable and agrees with what ran. It says nothing about whether the
transformation was scientifically appropriate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.verdict import Finding, Verdict, decide
from boomvalley_lab.declare.rules import DerivationExpected

FAMILY = "derivation"
PRECONDITION_STEPS = ("custody_integrity", "parent_reconciliation")


class DerivationFamily:
    """Compares reconciled derivation facts with the declared expectation."""

    name = FAMILY
    precondition_steps = PRECONDITION_STEPS

    def validate_expected(self, expected: Mapping[str, Any]) -> list[str]:
        try:
            DerivationExpected.from_document(expected)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return [str(error)]
        return []

    def observe(self, evidence: Mapping[str, Any], cell: str) -> Mapping[str, Any] | None:
        """`evidence`: cell -> the reconciled derivations of its records."""
        observed = evidence.get(cell)
        if not observed:
            return None
        return {"derivations": list(observed)}

    def compare(self, cell: str, expected: Mapping[str, Any],
                observed: Mapping[str, Any] | None) -> Finding:
        step = f"{FAMILY}:{cell}"
        if observed is None:
            return Finding(step, Verdict.VIOLATED,
                           ("a derivation is declared for this cell and no reconciled "
                            "derivation record was found: the claim cannot be checked",))
        declared = DerivationExpected.from_document(expected)
        reasons = []
        for record, actual in observed["derivations"]:
            if actual["parent_stage"] != declared.parent_stage:
                reasons.append(f"{record}: derived from stage {actual['parent_stage']!r}, "
                               f"declared {declared.parent_stage!r}")
            if actual["parent_cell"] != _declared_parent(cell, declared):
                reasons.append(f"{record}: parent cell {actual['parent_cell']}, declared "
                               f"{_declared_parent(cell, declared)}")
            if actual["transform"] != {"identity": declared.transform_identity,
                                       "version": declared.transform_version}:
                reasons.append(f"{record}: transform {actual['transform']}, declared "
                               f"{{'identity': {declared.transform_identity!r}, "
                               f"'version': {declared.transform_version!r}}}")
        verdict = decide(claimed=True, checkable=True, holds=not reasons)
        return Finding(step, verdict, tuple(reasons))


def _declared_parent(cell: str, declared: DerivationExpected) -> str:
    """The parent cell key the declaration names for `cell`.

    The child's coordinates with the declared overrides applied — computed on
    the cell key so the family needs no factor model at comparison time.
    """
    coordinates = dict(part.split("=", 1) for part in cell.split("/"))
    coordinates.update(dict(declared.parent_overrides))
    return "/".join(f"{name}={coordinates[name]}" for name in sorted(coordinates))
