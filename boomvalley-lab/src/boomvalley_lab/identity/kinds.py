"""The identity taxonomy: one identity, one responsibility.

Each identity is its own type. Internally most wrap the same `Digest`; at the
domain level they never substitute for one another: a `DesignIdentity` is not
equal to a `ScheduleIdentity` holding the same bytes, and a function that needs
one refuses the other (`require`). The research instrument used one hex string
for everything, and at least one value (`m9s_design_digest`) carried a schedule
digest under a design name; that cannot be expressed here.

Every kind answers exactly one question, and the answer must read the same in
the code and in this docstring:

    "this identity is the same" means WHAT is the same?

    ContractIdentity           the declared experimental contract
    DesignIdentity             the experimental structure
    ScheduleIdentity           the frozen execution order
    RequestIdentity            the canonical request that was sent
    ExecutionIdentity          the actual execution semantics and conditions
                               - NOT what the provider returned (OD-05)
    ArtifactContentIdentity    the exact persisted raw bytes (OD-06)
    CustodyEvidenceIdentity    what a run accepted and sealed
    LineageIdentity            what a child artifact was made from
    DatasetIdentity            one experimental dataset INSTANCE (OD-01)
    AnalysisEvidenceIdentity   the normative analysis evidence - NOT when it
                               was written (OD-07)
    SessionIdentity            one process invocation of one run

Version discipline (OD-08): a change to an identity's semantic input set is a
change of identity, so it comes with an explicit schema/version bump carried
INSIDE the preimage, where old and new can never collide. An identity whose
inputs did not change keeps its version; versions are not bumped for tidiness.

-----------------------------------------------------------------------------
Explicit amendment - ArtifactContentIdentity (Owner decision OD-06)
-----------------------------------------------------------------------------
    Previous wording (this module, before this amendment):
        "what one artifact asserts (its canonical content, not its file bytes)"

    Authoritative wording:
        ArtifactContentIdentity identifies exact persisted raw bytes.
        Canonical digest: SHA-256(raw persisted bytes).

    Reason:
        Owner Decision OD-06 resolves the conflict between the prior wording
        and the intended content-identity responsibility. The implementation
        (`store.artifacts.content_identity`) already digests the raw persisted
        bytes, so this amendment corrects the SPECIFICATION to match the
        decision and the code - not the code to match the old wording. The
        semantic input set did not change, so under OD-08 there is no version
        bump here.

    Recorded in the open as an Owner-decision resolution: not a silent
    rewording, and not a new finding.
-----------------------------------------------------------------------------

Formation (which document each is computed over) is defined by the phase that
owns the concept; Phase 0 fixes the kinds, their meaning and their separation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

from boomvalley_lab.core.digest import Digest, sha256_document
from boomvalley_lab.core.errors import IdentityError


@dataclass(frozen=True)
class DigestIdentity:
    """Base for digest-backed identities. Never used directly."""

    digest: Digest

    KIND: ClassVar[str] = ""
    IDENTIFIES: ClassVar[str] = ""
    EXISTS: ClassVar[str] = ""          # "declaration" or "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        if type(self) is DigestIdentity:
            raise IdentityError("DigestIdentity is abstract; use a specific identity kind")
        if not isinstance(self.digest, Digest):
            raise IdentityError(f"{self.KIND} identity needs a Digest, got {self.digest!r}")

    @classmethod
    def of_document(cls, document: Any) -> DigestIdentity:
        """This kind of identity for a canonical document."""
        return cls(sha256_document(document))

    def document(self) -> dict[str, str]:
        return {"kind": self.KIND, "digest": str(self.digest)}

    def __str__(self) -> str:
        return f"{self.KIND}:{self.digest}"


@dataclass(frozen=True)
class ContractIdentity(DigestIdentity):
    KIND: ClassVar[str] = "contract"
    IDENTIFIES = "the whole declaration as written, incl. experiment id and analysis binding"
    EXISTS = "declaration"
    NEVER_STANDS_FOR = ("design", "schedule", "dataset")


@dataclass(frozen=True)
class DesignIdentity(DigestIdentity):
    KIND: ClassVar[str] = "design"
    IDENTIFIES = ("the experimental structure: cell space, replication, schedule order, "
                  "denominator, views, relation, invariant, assignment, expectations")
    EXISTS = "declaration"
    NEVER_STANDS_FOR = ("contract", "schedule", "dataset")


@dataclass(frozen=True)
class ScheduleIdentity(DigestIdentity):
    KIND: ClassVar[str] = "schedule"
    IDENTIFIES = "the frozen execution order of qualified cells"
    EXISTS = "declaration"
    NEVER_STANDS_FOR = ("design", "contract")


@dataclass(frozen=True)
class RequestIdentity(DigestIdentity):
    KIND: ClassVar[str] = "request"
    IDENTIFIES = "the canonical request document actually sent to an adapter"
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("execution", "artifact_content")


@dataclass(frozen=True)
class ArtifactContentIdentity(DigestIdentity):
    KIND: ClassVar[str] = "artifact_content"
    #: OD-06 (see the amendment in this module's docstring): the authoritative
    #: input is the exact persisted raw bytes, digested as they are.
    IDENTIFIES = "the exact persisted raw bytes of one artifact: SHA-256 over those bytes"
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("custody", "execution", "lineage")


@dataclass(frozen=True)
class CustodyEvidenceIdentity(DigestIdentity):
    KIND: ClassVar[str] = "custody"
    IDENTIFIES = "what a run recorded and sealed: every custody entry key"
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("dataset", "artifact_content")


@dataclass(frozen=True)
class ExecutionIdentity(DigestIdentity):
    KIND: ClassVar[str] = "execution"
    #: OD-05: the conditions one attempt actually ran under. What came back is
    #: the response's and the artifact's responsibility, never this one's.
    IDENTIFIES = ("the actual execution of one attempt: its canonical actual-execution "
                  "records, and nothing the provider returned")
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("intent", "declared expectation", "artifact_content",
                        "provider response bytes")


@dataclass(frozen=True)
class LineageIdentity(DigestIdentity):
    KIND: ClassVar[str] = "lineage"
    IDENTIFIES = "what a child artifact was made from: parent reference + transform"
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("artifact_content", "dataset")


@dataclass(frozen=True)
class AnalysisEvidenceIdentity(DigestIdentity):
    KIND: ClassVar[str] = "analysis_evidence"
    #: OD-07: what ran, on which dataset, under which binding, with which
    #: result. WHEN the document was written is metadata, never identity: the
    #: same normative evidence recorded twice is the same evidence.
    IDENTIFIES = ("the normative evidence of one analysis, excluding the wall-clock "
                  "time at which it was recorded")
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("dataset", "custody", "the time it was written")


@dataclass(frozen=True)
class DatasetIdentity(DigestIdentity):
    KIND: ClassVar[str] = "dataset"
    #: OD-01: an experimental dataset INSTANCE - which artifacts are analysed,
    #: under which design, produced by WHICH RUN. The run is part of the
    #: responsibility: two runs of one locked schedule that happen to record
    #: byte-identical evidence are still two datasets.
    #:
    #: The preimage is `dataset.manifest.dataset_preimage`, which since #10
    #: (F-005) carries the run and carries nothing that belongs to another
    #: kind: contract (ID-C002), execution/actual_execution (ID-C001, OD-05),
    #: lineage and custody origin (ID-C001) are all outside it, and the
    #: artifact is referenced by its ArtifactContentIdentity rather than by
    #: its bytes or its file name.
    IDENTIFIES = ("one experimental dataset instance: which artifacts are analysed, "
                  "under which design, by which run (OD-01)")
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("contract", "execution", "lineage", "custody",
                        "provider response bytes", "artifact bytes")


_SESSION_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True, order=True)
class SessionIdentity:
    """One process invocation of a run (frozen R15). Not a digest: an ordinal.

    A run has one or more *sequential* sessions (resume); never two active at
    once (frozen R8: one active session per run, concurrent writers out of MVP).
    """

    run_id: str
    ordinal: int

    KIND: ClassVar[str] = "session"
    IDENTIFIES = "one process invocation of one run"
    EXISTS = "runtime"
    NEVER_STANDS_FOR = ("run", "attempt")

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _SESSION_RUN.fullmatch(self.run_id):
            raise IdentityError(f"not a run id: {self.run_id!r}")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise IdentityError(f"a session ordinal is a positive integer: {self.ordinal!r}")

    def __str__(self) -> str:
        return f"{self.run_id}#s{self.ordinal}"


IDENTITY_KINDS: tuple[type, ...] = (
    ContractIdentity, DesignIdentity, ScheduleIdentity, RequestIdentity,
    ArtifactContentIdentity,
    CustodyEvidenceIdentity, ExecutionIdentity, LineageIdentity, DatasetIdentity,
    AnalysisEvidenceIdentity, SessionIdentity,
)

IdentityT = TypeVar("IdentityT")


def require(value: object, kind: type[IdentityT]) -> IdentityT:
    """`value` as exactly `kind`, or IdentityError - never a look-alike."""
    if type(value) is not kind:
        raise IdentityError(
            f"expected a {getattr(kind, 'KIND', kind.__name__)} identity, got "
            f"{getattr(value, 'KIND', type(value).__name__)}"
        )
    return value  # type: ignore[return-value]
