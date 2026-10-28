"""SurfacePairContext (`gndcrw-pair/v0.1`, SURFACE §14-17, D-24.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gndcrw.contracts import _check as c
from gndcrw.contracts.surface import Surface
from gndcrw.core.vocabulary import CONTRACTS
from gndcrw.errors import ContractError

PAIR_VERSION = CONTRACTS["pair"]
MODES = ("CONTROL", "CONFIG_PERTURBATION", "REFERENCE")
COMPARABILITY_STATUS = ("ESTABLISHED", "NOT_ESTABLISHED", "UNKNOWN", "NOT_APPLICABLE")
METHODS = ("STABLE_DOMAIN_ID", "EXPLICIT_MAPPING", "DECLARED_PREMISE", "NONE")
ESTABLISHED_METHODS = ("STABLE_DOMAIN_ID", "EXPLICIT_MAPPING", "DECLARED_PREMISE")


@dataclass(frozen=True)
class Pair:
    comparison_mode: str
    base_surface_id: str
    candidate_surface_id: str
    comparability_status: str
    comparability_method: str
    authority: dict | None
    mapping: dict | None
    limitations: tuple[str, ...]
    document: dict

    def pairs(self, base: Surface, candidate: Surface) -> dict[str, str]:
        """BASE id -> CANDIDATE id for every safely comparable entity (D-24.6).

        Empty unless comparability is ESTABLISHED. Pairing is never inferred
        from matching IDs unless the declared method authorizes it.
        """
        if self.comparability_status != "ESTABLISHED":
            return {}
        if self.mapping is not None:
            return dict(self.mapping)
        candidate_ids = set(candidate.entity_ids)
        return {eid: eid for eid in base.entity_ids if eid in candidate_ids}


def parse(doc: Any, base: Surface, candidate: Surface) -> Pair:
    ptr = "pair:"
    c.obj(doc, ptr, (
        "pair_version", "comparison_mode", "base_surface_id", "candidate_surface_id",
        "entity_comparability",
    ))
    c.const(doc["pair_version"], f"{ptr}/pair_version", PAIR_VERSION)
    mode = c.enum(doc["comparison_mode"], f"{ptr}/comparison_mode", MODES)
    base_id = c.string(doc["base_surface_id"], f"{ptr}/base_surface_id")
    cand_id = c.string(doc["candidate_surface_id"], f"{ptr}/candidate_surface_id")
    if base_id != base.surface_id:
        raise ContractError(
            f"base_surface_id {base_id!r} does not match supplied base {base.surface_id!r}",
            pointer=f"{ptr}/base_surface_id",
        )
    if cand_id != candidate.surface_id:
        raise ContractError(
            f"candidate_surface_id {cand_id!r} does not match supplied candidate "
            f"{candidate.surface_id!r}",
            pointer=f"{ptr}/candidate_surface_id",
        )

    ec = doc["entity_comparability"]
    eptr = f"{ptr}/entity_comparability"
    c.obj(ec, eptr, ("status", "method", "authority", "mapping", "limitations"))
    status = c.enum(ec["status"], f"{eptr}/status", COMPARABILITY_STATUS)
    method = c.enum(ec["method"], f"{eptr}/method", METHODS)
    if status == "ESTABLISHED":
        if method not in ESTABLISHED_METHODS:
            raise ContractError("ESTABLISHED requires a pairing method", pointer=f"{eptr}/method")
    elif method != "NONE":
        raise ContractError(f"{status} requires method NONE", pointer=f"{eptr}/method")

    authority = ec["authority"]
    if method == "NONE":
        if authority is not None:
            raise ContractError("method NONE requires authority = null (D-26.7)",
                                pointer=f"{eptr}/authority")
    else:
        c.authority(authority, f"{eptr}/authority")

    mapping = ec["mapping"]
    if method == "EXPLICIT_MAPPING" and mapping is None:
        raise ContractError("EXPLICIT_MAPPING requires a mapping object", pointer=f"{eptr}/mapping")
    if method in ("STABLE_DOMAIN_ID", "NONE") and mapping is not None:
        raise ContractError(f"method {method} requires mapping = null", pointer=f"{eptr}/mapping")
    if mapping is not None:
        if not isinstance(mapping, dict):
            raise ContractError("expected an object", pointer=f"{eptr}/mapping")
        base_ids = set(base.entity_ids)
        cand_ids = set(candidate.entity_ids)
        targets_seen: set[str] = set()
        for key, value in mapping.items():
            c.string(value, f"{eptr}/mapping/{key}")
            if key not in base_ids:
                raise ContractError(
                    f"mapping key {key!r} is not a base entity", pointer=f"{eptr}/mapping"
                )
            if value not in cand_ids:
                raise ContractError(
                    f"mapping value {value!r} is not a candidate entity",
                    pointer=f"{eptr}/mapping/{key}",
                )
            if value in targets_seen:
                raise ContractError(
                    f"candidate entity {value!r} is mapped twice", pointer=f"{eptr}/mapping"
                )
            targets_seen.add(value)

    limitations = c.string_list(ec["limitations"], f"{eptr}/limitations", unique=False)

    return Pair(
        comparison_mode=mode,
        base_surface_id=base_id,
        candidate_surface_id=cand_id,
        comparability_status=status,
        comparability_method=method,
        authority=authority,
        mapping=mapping,
        limitations=tuple(limitations),
        document=doc,
    )
