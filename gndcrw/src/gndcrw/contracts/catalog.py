"""TargetCatalog / Profile (`gndcrw-target-catalog/v0.1`, TARGET_CATALOG_CONTRACT).

The catalog is the closed vocabulary: target name -> level, value kind,
availability, equality. There is no global registry; the core only ever sees
the one catalog object it was handed (D-11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gndcrw.contracts import _check as c
from gndcrw.core.vocabulary import CONTRACTS
from gndcrw.equality import JSON_STRUCTURAL, SET_EXACT
from gndcrw.errors import ContractError
from gndcrw.jsonio import digest

CATALOG_VERSION = CONTRACTS["target_catalog"]

LEVELS = ("SURFACE", "ENTITY_FIELD", "SUBSTRUCTURE")
VALUE_KINDS = ("STRING", "INTEGER", "NUMBER", "BOOLEAN", "NULL", "JSON")
AVAILABILITY = ("SUPPORTED", "KNOWN_UNSUPPORTED")
COMPOSITION_TARGETS = {
    # id -> (allowed value kind, allowed equality)
    "entity_count": ("INTEGER", JSON_STRUCTURAL),
    "entity_set": ("STRING_SET", SET_EXACT),
}


@dataclass(frozen=True)
class TargetDescriptor:
    target_id: str
    level: str
    value_kind: str
    availability: str
    equality: str


@dataclass(frozen=True)
class CompositionDescriptor:
    target_id: str
    value_kind: str
    availability: str
    equality: str


@dataclass(frozen=True)
class TargetCatalog:
    catalog_id: str
    profile_id: str
    provider_id: str
    catalog_digest: str
    targets: dict[str, TargetDescriptor]
    composition_targets: dict[str, CompositionDescriptor]
    document: dict

    def ref(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "catalog_id": self.catalog_id,
            "catalog_version": CATALOG_VERSION,
            "profile_id": self.profile_id,
            "catalog_digest": self.catalog_digest,
        }


def semantic_projection(doc: dict) -> dict:
    """The digest preimage: everything but `catalog_digest` (CATALOG §5)."""
    return {key: value for key, value in doc.items() if key != "catalog_digest"}


def compute_digest(doc: dict) -> str:
    return digest(semantic_projection(doc))


def value_conforms(kind: str, value: Any) -> bool:
    """Does a runtime value conform to a catalog value kind (CATALOG §8)?

    INTEGER is a lexical JSON integer; NUMBER is any finite number. Booleans
    are never numbers. JSON admits any JSON value.
    """
    if kind == "STRING":
        return isinstance(value, str)
    if kind == "INTEGER":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "NUMBER":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "BOOLEAN":
        return isinstance(value, bool)
    if kind == "NULL":
        return value is None
    if kind == "JSON":
        return True
    raise ValueError(kind)


def parse(doc: Any) -> TargetCatalog:
    ptr = "catalog:"
    c.obj(doc, ptr, (
        "catalog_version", "catalog_id", "profile_id", "provider_id",
        "catalog_digest", "targets", "composition_targets",
    ))
    c.const(doc["catalog_version"], f"{ptr}/catalog_version", CATALOG_VERSION)
    catalog_id = c.string(doc["catalog_id"], f"{ptr}/catalog_id")
    profile_id = c.string(doc["profile_id"], f"{ptr}/profile_id")
    provider_id = c.string(doc["provider_id"], f"{ptr}/provider_id")
    declared = c.digest(doc["catalog_digest"], f"{ptr}/catalog_digest")

    targets: dict[str, TargetDescriptor] = {}
    raw_targets = doc["targets"]
    if not isinstance(raw_targets, dict):
        raise ContractError("expected an object", pointer=f"{ptr}/targets")
    for target_id, desc in raw_targets.items():
        tptr = f"{ptr}/targets/{target_id}"
        c.string(target_id, tptr)
        c.obj(desc, tptr, ("level", "value_kind", "availability", "equality"))
        targets[target_id] = TargetDescriptor(
            target_id=target_id,
            level=c.enum(desc["level"], f"{tptr}/level", LEVELS),
            value_kind=c.enum(desc["value_kind"], f"{tptr}/value_kind", VALUE_KINDS),
            availability=c.enum(desc["availability"], f"{tptr}/availability", AVAILABILITY),
            equality=c.enum(desc["equality"], f"{tptr}/equality", (JSON_STRUCTURAL,)),
        )

    composition: dict[str, CompositionDescriptor] = {}
    raw_comp = doc["composition_targets"]
    if not isinstance(raw_comp, dict):
        raise ContractError("expected an object", pointer=f"{ptr}/composition_targets")
    for target_id, desc in raw_comp.items():
        tptr = f"{ptr}/composition_targets/{target_id}"
        if target_id not in COMPOSITION_TARGETS:
            raise ContractError(
                f"unknown composition target {target_id!r}; v0.1 allows "
                f"{', '.join(COMPOSITION_TARGETS)}",
                pointer=tptr,
            )
        kind, equality = COMPOSITION_TARGETS[target_id]
        c.obj(desc, tptr, ("value_kind", "availability", "equality"))
        composition[target_id] = CompositionDescriptor(
            target_id=target_id,
            value_kind=c.enum(desc["value_kind"], f"{tptr}/value_kind", (kind,)),
            # D-25.10: composition evidence is always observed; only SUPPORTED is valid.
            availability=c.enum(desc["availability"], f"{tptr}/availability", ("SUPPORTED",)),
            equality=c.enum(desc["equality"], f"{tptr}/equality", (equality,)),
        )

    for required in COMPOSITION_TARGETS:
        if required not in composition:
            raise ContractError(
                f"required composition target {required!r} is absent",
                pointer=f"{ptr}/composition_targets",
            )

    actual = compute_digest(doc)
    if actual != declared:
        raise ContractError(
            f"catalog_digest does not recompute (declared {declared}, computed {actual})",
            pointer=f"{ptr}/catalog_digest",
        )

    return TargetCatalog(
        catalog_id=catalog_id,
        profile_id=profile_id,
        provider_id=provider_id,
        catalog_digest=declared,
        targets=targets,
        composition_targets=composition,
        document=doc,
    )
