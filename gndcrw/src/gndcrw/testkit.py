"""Deterministic builders for synthetic contract documents.

Used by the test suite and by the synthetic part of the qualification corpus
(Q1-Q3, Q5, Q6). Historical Q4 fixtures are NOT built here: they are derived
from their source repositories (D-23).

`scenario()` returns the five documents of a clean CONTROL comparison that
yields RUN. Cases mutate a copy and call `seal()` so digests recompute.
"""

from __future__ import annotations

import copy
from typing import Any

from gndcrw.contracts.catalog import compute_digest
from gndcrw.contracts.declaration import compute_intent_digest
from gndcrw.core.vocabulary import CONTRACTS
from gndcrw.jsonio import digest

PROVIDER = "fixture-provider"
ENTITIES = ("slot-01", "slot-02", "slot-03")
RECENCY = "manager.raw_state.recency"
ROLE = "manager.role_instruction"
LENGTH = "manager.payload.length"


def sha(label: str) -> str:
    return digest({"fixture-input": label})


def catalog() -> dict:
    doc = {
        "catalog_version": CONTRACTS["target_catalog"],
        "catalog_id": "fixture-catalog",
        "profile_id": "default",
        "provider_id": PROVIDER,
        "catalog_digest": "",
        "targets": {
            RECENCY: {"level": "ENTITY_FIELD", "value_kind": "INTEGER",
                      "availability": "SUPPORTED", "equality": "JSON_STRUCTURAL"},
            ROLE: {"level": "SUBSTRUCTURE", "value_kind": "JSON",
                   "availability": "SUPPORTED", "equality": "JSON_STRUCTURAL"},
            LENGTH: {"level": "SURFACE", "value_kind": "INTEGER",
                     "availability": "SUPPORTED", "equality": "JSON_STRUCTURAL"},
        },
        "composition_targets": {
            "entity_count": {"value_kind": "INTEGER", "availability": "SUPPORTED",
                             "equality": "JSON_STRUCTURAL"},
            "entity_set": {"value_kind": "STRING_SET", "availability": "SUPPORTED",
                           "equality": "SET_EXACT"},
        },
    }
    return doc


def surface(role: str, surface_id: str, recency: list[int], *, length: int = 400,
            items: list[str] | None = None, entities: tuple[str, ...] = ENTITIES) -> dict:
    return {
        "surface_version": CONTRACTS["surface"],
        "surface_id": surface_id,
        "role": role,
        "provider": {"provider_id": PROVIDER, "provider_version": "1.0.0",
                     "adapter_id": "fixture-adapter", "adapter_version": "1.0.0"},
        "assembly": {"mode": "DIRECT", "assembly_entrypoint": "fixture.assemble",
                     "equivalence": None},
        "targets": {
            RECENCY: {"level": "ENTITY_FIELD", "observability": "OBSERVED",
                      "entity_values": dict(zip(entities, recency, strict=True))},
            ROLE: {"level": "SUBSTRUCTURE", "observability": "OBSERVED",
                   "value": {"items": items if items is not None else ["observe", "order"]}},
            LENGTH: {"level": "SURFACE", "observability": "OBSERVED", "value": length},
        },
        "composition": {"entity_kind": "slot", "entity_count": len(entities),
                        "entity_ids": list(entities), "identity_namespace": "fixture.slot/v1"},
        "provenance": {"input_digests": {"config": sha(f"{surface_id}:config"),
                                         "seed": sha("seed:7")}},
        "premises": [],
    }


def pair(mode: str = "CONTROL", status: str = "ESTABLISHED",
         method: str = "STABLE_DOMAIN_ID") -> dict:
    return {
        "pair_version": CONTRACTS["pair"],
        "comparison_mode": mode,
        "base_surface_id": "base",
        "candidate_surface_id": "candidate",
        "entity_comparability": {
            "status": status,
            "method": method,
            "authority": ({"kind": "PROVIDER", "id": PROVIDER} if method != "NONE" else None),
            "mapping": None,
            "limitations": [],
        },
    }


def rule(rule_id: str, target_id: str, operation: str, scope: str = "WHOLE_TARGET", *,
         kind: str = "TARGET", entity_ids: list[str] | None = None,
         premise_refs: list[str] | None = None) -> dict:
    scope_doc: dict[str, Any] = {"kind": scope}
    if scope == "EXPLICIT_ENTITY_IDS":
        scope_doc["entity_ids"] = list(entity_ids or [])
    return {"rule_id": rule_id, "target": {"kind": kind, "id": target_id},
            "operation": operation, "scope": scope_doc,
            "premise_refs": list(premise_refs or [])}


def consequence(rule_id: str, target_id: str, scope: str = "WHOLE_TARGET", *,
                kind: str = "TARGET") -> dict:
    return {"rule_id": rule_id, "target": {"kind": kind, "id": target_id},
            "scope": {"kind": scope},
            "authority": {"kind": "RESEARCHER", "id": "experiment-author"},
            "justification": "known accompanying change", "premise_refs": []}


def declaration(cat: dict) -> dict:
    return {
        "declaration_version": CONTRACTS["declaration"],
        "declaration_id": "EXP-FIXTURE-001",
        "intent": {"intent_id": "fixture-intent", "intent_digest": ""},
        "catalog_ref": {
            "provider_id": cat["provider_id"],
            "catalog_id": cat["catalog_id"],
            "catalog_version": cat["catalog_version"],
            "profile_id": cat["profile_id"],
            "catalog_digest": cat["catalog_digest"],
        },
        "comparison": {"required_mode": "CONTROL"},
        "expected_changes": [rule("CHG-001", RECENCY, "MUST_DIFFER", "ALL_COMPARABLE")],
        "invariants": [rule("INV-001", ROLE, "MUST_EQUAL")],
        "declared_consequences": [],
        "premises": [],
        "context": [],
    }


def seal(docs: dict) -> dict:
    """Recompute catalog_digest, re-bind catalog_ref and recompute intent_digest."""
    docs["catalog"]["catalog_digest"] = compute_digest(docs["catalog"])
    ref = docs["declaration"]["catalog_ref"]
    for key in ("provider_id", "catalog_id", "catalog_version", "profile_id",
                "catalog_digest"):
        ref[key] = docs["catalog"][key]
    docs["declaration"]["intent"]["intent_digest"] = compute_intent_digest(docs["declaration"])
    return docs


def scenario() -> dict:
    """A clean CONTROL comparison: recency changes 3/3, role instruction equal -> RUN."""
    cat = catalog()
    docs = {
        "catalog": cat,
        "base": surface("BASE", "base", [1, 2, 3]),
        "candidate": surface("CANDIDATE", "candidate", [11, 12, 13]),
        "pair": pair(),
        "declaration": declaration(cat),
    }
    return seal(docs)


def clone(docs: dict) -> dict:
    return copy.deepcopy(docs)
