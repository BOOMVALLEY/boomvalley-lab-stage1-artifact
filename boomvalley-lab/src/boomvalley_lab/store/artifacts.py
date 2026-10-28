"""The artifact-store boundary (not custody).

    put(name, content)  -> ArtifactRef   write to a temporary file (exclusive
                                         create), fsync, rename to its final
                                         name only if nothing is there (never
                                         overwrite), then READ IT BACK and
                                         compare the content identity (R2, R4)
    read(ref)           -> bytes         the persisted content, verified
                                         against the reference's identity

Artifacts here are opaque byte content; their content identity is the digest
of those bytes. The file name is a storage location, never provenance or
scientific identity.

This boundary answers "are these bytes still the bytes that were written?" —
nothing more. Whether a run ACCEPTED those bytes as evidence of a scheduled
realisation is custody (`custody`), which is a different question with a
different answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.layout import ARTIFACT_DIR
from boomvalley_lab.identity.kinds import ArtifactContentIdentity


def artifact_name(position: int) -> str:
    """Where the artifact of the record at schedule `position` is stored.
    A location only — identity comes from the recorded content digests."""
    return f"record-{position:06d}.bin"


@dataclass(frozen=True)
class ArtifactRef:
    name: str
    content: ArtifactContentIdentity

    def document(self) -> dict:
        return {"name": self.name, "content": str(self.content.digest)}


def content_identity(content: bytes) -> ArtifactContentIdentity:
    return ArtifactContentIdentity(sha256_bytes(content))


class ArtifactStore:
    def __init__(self, run_directory: Path) -> None:
        self.root = Path(run_directory) / ARTIFACT_DIR

    def path(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise EvidenceError(f"not an artifact name: {name!r}")
        return self.root / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def put(self, name: str, content: bytes) -> ArtifactRef:
        if not isinstance(content, (bytes, bytearray)):
            raise ExecutionError("artifact content must be bytes")
        self.root.mkdir(parents=True, exist_ok=True)
        final = self.path(name)
        if final.exists():
            raise ExecutionError(f"artifact {name} already exists; artifacts are never overwritten")
        temporary = self.root / f".{name}.partial"
        with open(temporary, "xb") as handle:
            handle.write(bytes(content))
            handle.flush()
            os.fsync(handle.fileno())
        if final.exists():
            temporary.unlink()
            raise ExecutionError(f"artifact {name} already exists; artifacts are never overwritten")
        os.rename(temporary, final)
        expected = content_identity(bytes(content))
        if content_identity(final.read_bytes()) != expected:
            raise ExecutionError(f"artifact {name} does not read back as written")
        return ArtifactRef(name, expected)

    def read(self, ref: ArtifactRef) -> bytes:
        data = self.path(ref.name).read_bytes()
        if content_identity(data) != ref.content:
            raise EvidenceError(f"artifact {ref.name} no longer matches its content identity")
        return data
