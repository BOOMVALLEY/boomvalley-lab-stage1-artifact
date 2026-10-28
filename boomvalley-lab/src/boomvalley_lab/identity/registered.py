"""Externally frozen identities — verified against, never recomputed.

A pre-registered study (M9-S is the first) arrives with identities that were
frozen before this product existed, computed by that study's own algorithms. The
clean product must not pretend to regenerate them through `canonical-json-1`,
and must not treat them as one of its own identity kinds. It records them
verbatim and later checks a value it computes, through an import adapter that
reproduces the study's algorithm, against them.

Phase 0 fixes only the type. Study-specific names live in import adapters, not
in generic APIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import IdentityError

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")


@dataclass(frozen=True)
class RegisteredIdentity:
    """A frozen external reference: which study, which quantity, what value.

    `quantity` names what the value is in the external study's terms, e.g.
    "schedule_digest" or "registration_manifest". `algorithm` names how that
    study computed it; it is recorded, not trusted to match ours.
    """

    study: str
    quantity: str
    algorithm: str
    value: Digest
    source: str

    def __post_init__(self) -> None:
        for field_name in ("study", "quantity", "algorithm"):
            text = getattr(self, field_name)
            if not isinstance(text, str) or not _TOKEN.fullmatch(text):
                raise IdentityError(f"registered identity {field_name} is malformed: {text!r}")
        if not isinstance(self.value, Digest):
            raise IdentityError("a registered identity's value is a Digest")
        if not isinstance(self.source, str) or not self.source.strip():
            raise IdentityError("a registered identity must say where it was frozen")

    def matches(self, computed: Digest) -> bool:
        """Whether a value computed by an import adapter equals the frozen one."""
        if not isinstance(computed, Digest):
            raise IdentityError("compare a registered identity with a Digest")
        return computed == self.value

    def document(self) -> dict[str, str]:
        return {
            "study": self.study, "quantity": self.quantity,
            "algorithm": self.algorithm, "value": str(self.value), "source": self.source,
        }
