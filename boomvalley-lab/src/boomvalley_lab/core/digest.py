"""The one digest service. No other product module imports `hashlib`.

A `Digest` carries its algorithm, so a value read back from an evidence
package says how it was made. MVP algorithm: SHA-256 over canonical bytes.

This is tamper *evidence* under an operational threat model, not
cryptographic assurance: nothing is signed (accepted debt D4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import IdentityError
from boomvalley_lab.core.versions import DIGEST_ALGORITHM

_HEX = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, order=True)
class Digest:
    """A digest value and the algorithm that produced it."""

    algorithm: str
    hex: str

    def __post_init__(self) -> None:
        if self.algorithm != DIGEST_ALGORITHM:
            raise IdentityError(f"unsupported digest algorithm {self.algorithm!r}")
        if not isinstance(self.hex, str) or not _HEX.fullmatch(self.hex):
            raise IdentityError(f"not a lowercase {self.algorithm} digest: {self.hex!r}")

    @classmethod
    def parse(cls, text: str) -> Digest:
        """`sha256:<hex>` -> Digest."""
        algorithm, _, value = str(text).partition(":")
        return cls(algorithm, value)

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.hex}"

    def short(self, length: int = 12) -> str:
        return self.hex[:length]


def sha256_bytes(data: bytes) -> Digest:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise IdentityError("sha256_bytes digests bytes; use sha256_document for documents")
    return Digest(DIGEST_ALGORITHM, hashlib.sha256(bytes(data)).hexdigest())


def sha256_document(document: Any) -> Digest:
    """The digest of a document's canonical bytes (`canonical-json-1`)."""
    return sha256_bytes(canonical_bytes(document))
