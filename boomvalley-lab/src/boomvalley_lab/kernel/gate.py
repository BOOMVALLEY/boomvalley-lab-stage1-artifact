"""gate-2: versioned pre-execution authorization decision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import EvidenceError, IdentityError
from boomvalley_lab.kernel.identity import (
    CoverageAttestationIdentity,
    GateDecisionIdentity,
    GNDCRWResultSetIdentity,
    PlanIdentity,
)

SCHEMA = "boomvalley-lab-gate-2"
_FIELDS = frozenset(
    {"schema", "plan", "coverage", "gndcrw_results", "policy_identity", "decision", "reasons"}
)


def identity_from_document(cls: type, document: Any, where: str) -> Any:
    """Rebuild one K0 digest identity from its ``{"kind", "digest"}`` document."""

    if (
        not isinstance(document, Mapping)
        or set(document) != {"kind", "digest"}
        or document["kind"] != cls.KIND
        or not isinstance(document["digest"], str)
    ):
        raise EvidenceError(f"{where} is not a {cls.KIND} identity")
    try:
        return cls(Digest.parse(document["digest"]))
    except (IdentityError, TypeError, ValueError) as error:
        raise EvidenceError(f"{where} digest is malformed: {error}") from error


@dataclass(frozen=True)
class GateDecisionV2:
    plan: PlanIdentity
    coverage: CoverageAttestationIdentity
    gndcrw_results: GNDCRWResultSetIdentity
    policy_identity: str
    cleared: bool
    reasons: Sequence[str]

    def __post_init__(self) -> None:
        if not isinstance(self.policy_identity, str) or not self.policy_identity:
            raise ValueError("policy_identity must be a non-empty string")
        if self.cleared and self.reasons:
            raise ValueError("a cleared gate-2 decision has no refusal reasons")
        if not self.cleared and not self.reasons:
            raise ValueError("a refused gate-2 decision has at least one reason")

    def document(self) -> dict:
        return {
            "schema": SCHEMA,
            "plan": self.plan.document(),
            "coverage": self.coverage.document(),
            "gndcrw_results": self.gndcrw_results.document(),
            "policy_identity": self.policy_identity,
            "decision": "CLEARED" if self.cleared else "REFUSED",
            "reasons": list(self.reasons),
        }

    def identity(self) -> GateDecisionIdentity:
        return GateDecisionIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> GateDecisionV2:
        if not isinstance(document, Mapping) or set(document) != _FIELDS:
            raise EvidenceError("gate-2 decision has the wrong closed shape")
        if document["schema"] != SCHEMA:
            raise EvidenceError(f"gate-2 decision schema is exactly {SCHEMA!r}")
        if document["decision"] not in ("CLEARED", "REFUSED"):
            raise EvidenceError("gate-2 decision is CLEARED or REFUSED")
        reasons = document["reasons"]
        if not isinstance(reasons, list) or not all(isinstance(r, str) and r for r in reasons):
            raise EvidenceError("gate-2 reasons is a list of non-empty strings")
        try:
            return cls(
                plan=identity_from_document(PlanIdentity, document["plan"], "gate-2 plan"),
                coverage=identity_from_document(
                    CoverageAttestationIdentity, document["coverage"], "gate-2 coverage"
                ),
                gndcrw_results=identity_from_document(
                    GNDCRWResultSetIdentity, document["gndcrw_results"], "gate-2 gndcrw_results"
                ),
                policy_identity=document["policy_identity"],
                cleared=document["decision"] == "CLEARED",
                reasons=tuple(reasons),
            )
        except ValueError as error:
            raise EvidenceError(f"gate-2 decision is invalid: {error}") from error
