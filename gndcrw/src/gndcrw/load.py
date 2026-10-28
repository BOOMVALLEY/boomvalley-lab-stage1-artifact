"""Normalization of the five logical inputs into core objects.

Both input modes end here (SURFACE §24, D-11): materialized mode hands in five
parsed JSON documents; provider mode materializes the same five documents
from a provider first. The core cannot tell which path was used.

Each input is read exactly once (CLI §16): files are read to bytes, parsed,
and every digest is computed from those parsed documents. Nothing reopens a
path after validation.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gndcrw.codes import LegacyError
from gndcrw.contracts import catalog as catalog_contract
from gndcrw.contracts import declaration as declaration_contract
from gndcrw.contracts import pair as pair_contract
from gndcrw.contracts import surface as surface_contract
from gndcrw.core.engine import Inputs
from gndcrw.errors import ContractError
from gndcrw.jsonio import digest, load_bytes


@dataclass(frozen=True)
class Documents:
    """The five logical inputs as parsed JSON documents."""

    declaration: Any
    catalog: Any
    base: Any
    candidate: Any
    pair: Any


def read_documents(declaration: Path, catalog: Path, base: Path, candidate: Path,
                   pair: Path) -> Documents:
    def read(path: Path, label: str) -> Any:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ContractError(pointer=label, code=LegacyError.INPUT_NOT_FOUND,
                                message_key="legacy.input_not_found", role=label,
                                path=path) from None
        except OSError as exc:
            raise ContractError(pointer=label, code=LegacyError.INPUT_UNREADABLE,
                                message_key="legacy.input_unreadable", role=label, path=path,
                                error=exc) from None
        return load_bytes(data, label=label)

    return Documents(
        declaration=read(declaration, "declaration"),
        catalog=read(catalog, "catalog"),
        base=read(base, "base"),
        candidate=read(candidate, "candidate"),
        pair=read(pair, "pair"),
    )


def normalize(docs: Documents) -> Inputs:
    """Validate every contract and bind the normalized input digests.

    A deep copy isolates the check from any later mutation of the caller's
    objects (ES-I07).
    """
    docs = copy.deepcopy(docs)
    catalog = catalog_contract.parse(docs.catalog)
    base = surface_contract.parse(docs.base, catalog, label="base")
    candidate = surface_contract.parse(docs.candidate, catalog, label="candidate")
    if base.role != "BASE":
        raise ContractError("the base surface must have role BASE", pointer="base:/role")
    if candidate.role != "CANDIDATE":
        raise ContractError(
            "the candidate surface must have role CANDIDATE", pointer="candidate:/role"
        )
    base_pid, cand_pid = base.provider["provider_id"], candidate.provider["provider_id"]
    if base_pid is not None and cand_pid is not None and base_pid != cand_pid:
        raise ContractError(
            f"base provider_id {base_pid!r} != candidate provider_id {cand_pid!r} (D-22)",
            pointer="candidate:/provider/provider_id",
        )
    pair = pair_contract.parse(docs.pair, base, candidate)
    declaration = declaration_contract.parse(docs.declaration, catalog)

    # premise_id is unique across declaration, base and candidate (D-25.8)
    seen: dict[str, str] = {}
    for label, premises in (("declaration", declaration.premises), ("base", base.premises),
                            ("candidate", candidate.premises)):
        for premise in premises:
            pid = premise["premise_id"]
            if pid in seen:
                raise ContractError(
                    f"premise_id {pid!r} appears in both {seen[pid]} and {label} (D-25.8)",
                    pointer=f"{label}:/premises",
                )
            seen[pid] = label

    subject = {
        "declaration": {
            "id": declaration.declaration_id,
            "intent_digest": declaration.intent_digest,
            "content_digest": declaration.content_digest,
        },
        "catalog": {
            "id": catalog.catalog_id,
            "profile_id": catalog.profile_id,
            "catalog_digest": catalog.catalog_digest,
        },
        "base_surface": {
            "id": base.surface_id,
            "content_digest": digest(surface_contract.normalized(docs.base)),
        },
        "candidate_surface": {
            "id": candidate.surface_id,
            "content_digest": digest(surface_contract.normalized(docs.candidate)),
        },
        "pair": {"content_digest": digest(docs.pair)},
    }
    return Inputs(declaration=declaration, catalog=catalog, base=base, candidate=candidate,
                  pair=pair, subject=subject)
