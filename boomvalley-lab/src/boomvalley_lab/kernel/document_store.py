"""Content-addressed canonical document store for manifest-4 evidence members."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.kernel.manifest4 import ROLES

_REF_SCHEMA = "boomvalley-lab-evidence-document-ref-2"


@dataclass(frozen=True)
class EvidenceDocumentRefV2:
    role: str
    path: str
    digest: str
    size: int

    def document(self) -> dict[str, Any]:
        return {
            "schema": _REF_SCHEMA,
            "role": self.role,
            "path": self.path,
            "digest": self.digest,
            "size": self.size,
        }


def evidence_ref_from_document(document: Any, role: str) -> EvidenceDocumentRefV2:
    if not isinstance(document, Mapping) or document.get("schema") != _REF_SCHEMA:
        raise EvidenceError(f"{role} evidence reference is not {_REF_SCHEMA}")
    if set(document) != {"schema", "role", "path", "digest", "size"}:
        raise EvidenceError(f"{role} evidence reference has unexpected fields")
    digest = document["digest"]
    if document["role"] != role or not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise EvidenceError(f"{role} evidence reference role/digest is invalid")
    if document["path"] != f"evidence-v2/{role}/{digest.removeprefix('sha256:')}.json":
        raise EvidenceError(f"{role} evidence reference path is not its content address")
    size = document["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise EvidenceError(f"{role} evidence reference size is invalid")
    return EvidenceDocumentRefV2(role, document["path"], digest, size)


class EvidenceDocumentStoreV2:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ref(self, role: str, document: Any) -> EvidenceDocumentRefV2:
        """The reference *document* has as a member of *role* (nothing is written)."""

        if role not in ROLES:
            raise ValueError(f"unknown evidence role {role!r}")
        data = canonical_bytes(document)
        digest = sha256_bytes(data)
        return EvidenceDocumentRefV2(
            role, f"evidence-v2/{role}/{digest.hex}.json", str(digest), len(data)
        )

    def put(self, role: str, document: Any) -> EvidenceDocumentRefV2:
        ref = self.ref(role, document)
        data = canonical_bytes(document)
        relative = ref.path
        final = self.root / relative

        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            if final.read_bytes() != data:
                raise EvidenceError(f"{relative} contradicts its content address")
            return ref

        partial = final.parent / f".{final.name}.partial"
        # A partial without its final member is the leftover of a crashed
        # write: nothing references it (single writer, R8), so it is discarded
        # rather than blocking a resume (T0-011, as request-2 in T0-010).
        partial.unlink(missing_ok=True)
        try:
            with open(partial, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if final.exists():
                held = final.read_bytes()
                partial.unlink(missing_ok=True)
                if held != data:
                    raise EvidenceError(f"{relative} appeared with contradictory bytes")
                return ref
            os.rename(partial, final)
        except FileExistsError as error:
            raise ExecutionError(
                f"partial evidence member already exists for {relative}"
            ) from error

        if final.read_bytes() != data:
            raise ExecutionError(f"{relative} does not read back as written")
        return ref

    def members(self, role: str) -> list[Any]:
        """Every stored document of *role*, each read under its content address."""

        if role not in ROLES:
            raise ValueError(f"unknown evidence role {role!r}")
        found = []
        for path in sorted((self.root / "evidence-v2" / role).glob("*.json")):
            relative = f"evidence-v2/{role}/{path.name}"
            found.append(
                self.read(
                    EvidenceDocumentRefV2(
                        role, relative, f"sha256:{path.stem}", path.stat().st_size
                    )
                )
            )
        return found

    def read(self, ref: EvidenceDocumentRefV2) -> Any:
        data = (self.root / ref.path).read_bytes()
        if len(data) != ref.size or str(sha256_bytes(data)) != ref.digest:
            raise EvidenceError(f"{ref.path} no longer matches its content reference")
        try:
            document = load_bytes(data)
        except MalformedJSON as error:
            raise EvidenceError(f"{ref.path} is unreadable: {error}") from error
        if canonical_bytes(document) != data:
            raise EvidenceError(f"{ref.path} is not canonical evidence bytes")
        return document
