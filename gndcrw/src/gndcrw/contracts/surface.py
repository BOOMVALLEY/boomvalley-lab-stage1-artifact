"""ExperimentSurface (`gndcrw-surface/v0.1`, EXPERIMENT_SURFACE_CONTRACT).

Structural validation plus validation against the selected TargetCatalog
(SURFACE §20). Everything checked here is an input/contract error when it
fails. Semantically-missing states (MISSING observability, UNPROVEN
equivalence, null provenance) are valid input and pass through untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gndcrw.contracts import _check as c
from gndcrw.contracts.catalog import TargetCatalog, value_conforms
from gndcrw.core.vocabulary import CONTRACTS
from gndcrw.errors import ContractError

SURFACE_VERSION = CONTRACTS["surface"]
ROLES = ("BASE", "CANDIDATE")
MODES = ("DIRECT", "RECONSTRUCTED")
EQUIVALENCE_STATUS = ("PROVEN", "UNPROVEN")
EQUIVALENCE_METHODS = ("EXACT_BYTES", "CONTRACT_DEFINED_EQUIVALENCE")
OBSERVABILITY = (
    "OBSERVED", "UNOBSERVABLE", "MISSING", "UNSUPPORTED", "AMBIGUOUS", "ASSERTED_ONLY",
)
PROVIDER_FIELDS = ("provider_id", "provider_version", "adapter_id", "adapter_version")


@dataclass(frozen=True)
class TargetRecord:
    target_id: str
    observability: str
    value: Any = None
    entity_values: dict | None = None
    authority: dict | None = None

    @property
    def carries_value(self) -> bool:
        return self.observability in ("OBSERVED", "ASSERTED_ONLY")


@dataclass(frozen=True)
class Surface:
    surface_id: str
    role: str
    provider: dict
    assembly: dict
    targets: dict[str, TargetRecord]
    entity_kind: str
    entity_ids: tuple[str, ...]
    identity_namespace: str
    provenance: dict
    premises: tuple[dict, ...]
    document: dict

    @property
    def mode(self) -> str:
        return self.assembly["mode"]

    def missing_provenance(self) -> list[str]:
        """Semantically missing required provenance (D-18), sorted field paths."""
        missing = [f"provider.{name}" for name in PROVIDER_FIELDS if self.provider[name] is None]
        if self.assembly["assembly_entrypoint"] is None:
            missing.append("assembly.assembly_entrypoint")
        if not self.provenance["input_digests"]:
            missing.append("provenance.input_digests")
        return sorted(missing)


def normalized(doc: dict) -> dict:
    """Normalized object for the content digest (SURFACE §22)."""
    out = dict(doc)
    comp = dict(doc["composition"])
    comp["entity_ids"] = sorted(comp["entity_ids"])
    out["composition"] = comp
    return out


def _equivalence(value: Any, ptr: str) -> None:
    c.obj(value, ptr, ("status", "method", "evidence"))
    status = c.enum(value["status"], f"{ptr}/status", EQUIVALENCE_STATUS)
    evidence = c.array(value["evidence"], f"{ptr}/evidence")
    if status == "UNPROVEN":
        if value["method"] is not None:
            raise ContractError("UNPROVEN requires method = null", pointer=f"{ptr}/method")
        if evidence:
            raise ContractError("UNPROVEN requires evidence = []", pointer=f"{ptr}/evidence")
        return
    method = c.enum(value["method"], f"{ptr}/method", EQUIVALENCE_METHODS)
    if not evidence:
        raise ContractError("PROVEN requires non-empty evidence", pointer=f"{ptr}/evidence")
    for index, item in enumerate(evidence):
        iptr = f"{ptr}/evidence/{index}"
        if method == "EXACT_BYTES":
            c.obj(item, iptr, ("kind", "expected", "observed"))
            c.enum(item["kind"], f"{iptr}/kind", ("sha256",))
            c.digest(item["expected"], f"{iptr}/expected")
            c.digest(item["observed"], f"{iptr}/observed")
        elif not isinstance(item, dict):
            raise ContractError("expected an object", pointer=iptr)


def _assembly(value: Any, ptr: str) -> None:
    c.obj(value, ptr, ("mode", "assembly_entrypoint", "equivalence"))
    mode = c.enum(value["mode"], f"{ptr}/mode", MODES)
    c.string(value["assembly_entrypoint"], f"{ptr}/assembly_entrypoint", nullable=True)
    if mode == "DIRECT":
        if value["equivalence"] is not None:
            raise ContractError("DIRECT requires equivalence = null", pointer=f"{ptr}/equivalence")
    else:
        if value["equivalence"] is None:
            raise ContractError(
                "RECONSTRUCTED requires an equivalence object", pointer=f"{ptr}/equivalence"
            )
        _equivalence(value["equivalence"], f"{ptr}/equivalence")


def _record(
    target_id: str, value: Any, ptr: str, catalog: TargetCatalog, entity_ids: set[str]
) -> TargetRecord:
    desc = catalog.targets[target_id]
    c.obj(value, ptr, ("observability",), ("level", "value", "entity_values", "authority"))
    if "level" in value and value["level"] != desc.level:
        raise ContractError(
            f"level {value['level']!r} contradicts catalog level {desc.level!r}",
            pointer=f"{ptr}/level",
        )
    state = c.enum(value["observability"], f"{ptr}/observability", OBSERVABILITY)

    if desc.availability == "KNOWN_UNSUPPORTED" and state != "UNSUPPORTED":
        raise ContractError(
            "catalog availability is KNOWN_UNSUPPORTED; record must be UNSUPPORTED",
            pointer=f"{ptr}/observability",
        )
    if state == "UNSUPPORTED" and desc.availability != "KNOWN_UNSUPPORTED":
        raise ContractError(
            "UNSUPPORTED is valid only for a KNOWN_UNSUPPORTED catalog target",
            pointer=f"{ptr}/observability",
        )

    carries = state in ("OBSERVED", "ASSERTED_ONLY")
    if state == "ASSERTED_ONLY":
        if "authority" not in value:
            raise ContractError("ASSERTED_ONLY requires authority", pointer=ptr)
        c.authority(value["authority"], f"{ptr}/authority")
    elif "authority" in value:
        raise ContractError("authority is only valid for ASSERTED_ONLY", pointer=ptr)

    if not carries:
        for key in ("value", "entity_values"):
            if key in value:
                raise ContractError(f"{state} record must not carry {key!r}", pointer=ptr)
        return TargetRecord(target_id, state)

    if desc.level == "ENTITY_FIELD":
        if "value" in value:
            raise ContractError("ENTITY_FIELD record uses entity_values, not value", pointer=ptr)
        if "entity_values" not in value:
            raise ContractError(f"{state} ENTITY_FIELD requires entity_values", pointer=ptr)
        values = value["entity_values"]
        if not isinstance(values, dict):
            raise ContractError("expected an object", pointer=f"{ptr}/entity_values")
        if set(values) != entity_ids:
            raise ContractError(
                "entity_values keys must equal composition.entity_ids exactly (D-24.5)",
                pointer=f"{ptr}/entity_values",
            )
        for entity, item in values.items():
            if not value_conforms(desc.value_kind, item):
                raise ContractError(
                    f"value does not conform to catalog kind {desc.value_kind}",
                    pointer=f"{ptr}/entity_values/{entity}",
                )
        return TargetRecord(target_id, state, entity_values=values,
                            authority=value.get("authority"))

    if "entity_values" in value:
        raise ContractError(f"{desc.level} record uses value, not entity_values", pointer=ptr)
    if "value" not in value:
        raise ContractError(f"{state} {desc.level} requires value", pointer=ptr)
    if not value_conforms(desc.value_kind, value["value"]):
        raise ContractError(
            f"value does not conform to catalog kind {desc.value_kind}", pointer=f"{ptr}/value"
        )
    return TargetRecord(target_id, state, value=value["value"], authority=value.get("authority"))


def parse(doc: Any, catalog: TargetCatalog, *, label: str) -> Surface:
    ptr = f"{label}:"
    c.obj(doc, ptr, (
        "surface_version", "surface_id", "role", "provider", "assembly",
        "targets", "composition", "provenance", "premises",
    ))
    c.const(doc["surface_version"], f"{ptr}/surface_version", SURFACE_VERSION)
    surface_id = c.string(doc["surface_id"], f"{ptr}/surface_id")
    role = c.enum(doc["role"], f"{ptr}/role", ROLES)

    provider = doc["provider"]
    c.obj(provider, f"{ptr}/provider", PROVIDER_FIELDS)
    for name in PROVIDER_FIELDS:
        c.string(provider[name], f"{ptr}/provider/{name}", nullable=True)
    if provider["provider_id"] is not None and provider["provider_id"] != catalog.provider_id:
        raise ContractError(
            f"provider_id {provider['provider_id']!r} != catalog provider_id "
            f"{catalog.provider_id!r} (D-22)",
            pointer=f"{ptr}/provider/provider_id",
        )

    _assembly(doc["assembly"], f"{ptr}/assembly")

    comp = doc["composition"]
    cptr = f"{ptr}/composition"
    c.obj(comp, cptr, ("entity_kind", "entity_count", "entity_ids", "identity_namespace"))
    entity_kind = c.string(comp["entity_kind"], f"{cptr}/entity_kind")
    count = c.integer(comp["entity_count"], f"{cptr}/entity_count", minimum=0)
    ids = c.string_list(comp["entity_ids"], f"{cptr}/entity_ids")
    if count != len(ids):
        raise ContractError(
            f"entity_count {count} != number of unique entity_ids {len(ids)}",
            pointer=f"{cptr}/entity_count",
        )
    namespace = c.string(comp["identity_namespace"], f"{cptr}/identity_namespace")

    raw_targets = doc["targets"]
    if not isinstance(raw_targets, dict):
        raise ContractError("expected an object", pointer=f"{ptr}/targets")
    for target_id in catalog.targets:
        if target_id not in raw_targets:
            raise ContractError(
                f"catalog target {target_id!r} has no record (omission is not permitted)",
                pointer=f"{ptr}/targets",
            )
    for target_id in raw_targets:
        if target_id not in catalog.targets:
            raise ContractError(
                f"target record {target_id!r} is not in the selected catalog",
                pointer=f"{ptr}/targets",
            )
    entity_set = set(ids)
    records = {
        tid: _record(tid, raw_targets[tid], f"{ptr}/targets/{tid}", catalog, entity_set)
        for tid in sorted(raw_targets)
    }

    prov = doc["provenance"]
    c.obj(prov, f"{ptr}/provenance", ("input_digests",), _any_keys(prov))
    digests = prov["input_digests"]
    if not isinstance(digests, dict):
        raise ContractError("expected an object", pointer=f"{ptr}/provenance/input_digests")
    for name, value in digests.items():
        c.string(name, f"{ptr}/provenance/input_digests")
        c.digest(value, f"{ptr}/provenance/input_digests/{name}")

    premises = c.array(doc["premises"], f"{ptr}/premises")
    seen: set[str] = set()
    for index, premise in enumerate(premises):
        pptr = f"{ptr}/premises/{index}"
        c.obj(premise, pptr, ("premise_id", "statement", "authority"))
        pid = c.premise_identifier(premise["premise_id"], f"{pptr}/premise_id")
        if pid in seen:
            raise ContractError(f"duplicate premise_id {pid!r}", pointer=pptr)
        seen.add(pid)
        c.any_string(premise["statement"], f"{pptr}/statement")
        c.authority(premise["authority"], f"{pptr}/authority")

    return Surface(
        surface_id=surface_id,
        role=role,
        provider=provider,
        assembly=doc["assembly"],
        targets=records,
        entity_kind=entity_kind,
        entity_ids=tuple(sorted(ids)),
        identity_namespace=namespace,
        provenance=prov,
        premises=tuple(sorted(premises, key=lambda p: p["premise_id"])),
        document=doc,
    )


def _any_keys(value: Any) -> tuple[str, ...]:
    """Producer-specific provenance keys are permitted (SURFACE §19.1)."""
    return tuple(value) if isinstance(value, dict) else ()
