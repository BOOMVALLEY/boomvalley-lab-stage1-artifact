"""The derivation record (R41): what a derived artifact was actually made from.

Lineage is never inferred. Two artifacts existing in the same package, or in
the right order, or with plausible names, say nothing: a derived artifact has a
parent only because the run RECORDED the derivation it performed, and custody
sealed that record with the child (R41 places it in the child's custody entry).

    stage       the declared upstream stage this parent came from
    parent      seal (the parent package's custody seal — content-addressed,
                so identical manifests are the same evidence), run, design
                identity, qualified cell, record, and the digest of the bytes
                that were actually read
    transform   the identity and version read off the transform that ran —
                not the declared one, so the two can disagree

`LineageIdentity` is the digest of that document. It is deliberately NOT the
child's content identity: the same bytes produced from a different parent, or
by a different transform, are the same artifact with a different history, and
the product must keep them apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.identity.kinds import LineageIdentity

DERIVATION_SCHEMA = "boomvalley-lab-derivation-1"

PARENT_KEYS = ("artifact_content", "cell", "design", "record", "run", "seal")
TRANSFORM_KEYS = ("identity", "version")


def _strings(value: Any, keys: tuple[str, ...], where: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or tuple(sorted(value)) != keys:
        raise EvidenceError(f"{where}: expected exactly {list(keys)}")
    for key in keys:
        if not isinstance(value[key], str) or not value[key].strip():
            raise EvidenceError(f"{where}: {key} must be a non-empty string")
    return {key: value[key] for key in keys}


def derivation_document(*, stage: str, parent: Mapping[str, str],
                        transform: Mapping[str, str]) -> dict:
    return check_derivation({
        "schema": DERIVATION_SCHEMA,
        "stage": stage,
        "parent": dict(parent),
        "transform": dict(transform),
    }, "derivation")


def check_derivation(value: Any, where: str) -> dict:
    if not isinstance(value, Mapping) or value.get("schema") != DERIVATION_SCHEMA:
        raise EvidenceError(f"{where}: not a {DERIVATION_SCHEMA} record")
    if tuple(sorted(value)) != ("parent", "schema", "stage", "transform"):
        raise EvidenceError(f"{where}: a derivation record is schema, stage, parent, transform")
    if not isinstance(value["stage"], str) or not value["stage"].strip():
        raise EvidenceError(f"{where}: stage must be a non-empty string")
    return {
        "schema": DERIVATION_SCHEMA,
        "stage": value["stage"],
        "parent": _strings(value["parent"], PARENT_KEYS, f"{where}.parent"),
        "transform": _strings(value["transform"], TRANSFORM_KEYS, f"{where}.transform"),
    }


def lineage_identity(document: Mapping) -> LineageIdentity:
    """What this child was made from — never what it says."""
    return LineageIdentity.of_document(check_derivation(document, "derivation"))


def actual_derivation(document: Mapping) -> dict:
    """The comparable facts: the stage, the parent cell and the transform.

    The parent's seal, run and digests are reconciliation evidence (R42); what
    a DESIGN declares about a derivation (R43) is which stage and which parent
    cell it must come from, and which transform must have produced it.
    """
    record = check_derivation(document, "derivation")
    return {
        "parent_stage": record["stage"],
        "parent_cell": record["parent"]["cell"],
        "transform": dict(record["transform"]),
    }
