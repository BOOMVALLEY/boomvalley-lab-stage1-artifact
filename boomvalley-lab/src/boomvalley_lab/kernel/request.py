"""request-2: canonical scientific request persisted before call intent.

Upstream lineage (T2-003): a request whose actor observes another actor's
output (a granted ``actor_output`` source, T2-001) binds, in ``upstream``,
the exact committed identity of every such source - the producer node, its
CallIdentity (actor_call) or ProposalIdentity (proposal_parse) and the digest
of the bytes the source carried.  The RequestIdentity, and through it the
downstream CallIdentity, therefore names the upstream proposal / call it was
conditioned on, not only content that happens to equal it.  A request without
upstream sources has no ``upstream`` member, so its bytes are unchanged.

Memory lineage (T4-003): a request whose actor observes a granted
``memory_artifact`` source binds, in ``memory``, per source the producer
node, the MemoryArtifactIdentity of every artifact valid in its round and the
digest of the bytes the source carried.  A request observing no memory source
has no ``memory`` member.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from boomvalley_lab.identity.kinds import RequestIdentity


class CorroborationGrade(StrEnum):
    EXACT_TRANSPORT = "EXACT_TRANSPORT"
    CLIENT_CANONICAL = "CLIENT_CANONICAL"
    PROVIDER_BOUND_INDIRECT = "PROVIDER_BOUND_INDIRECT"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True)
class RequestV2:
    messages: Sequence[Mapping[str, Any]]
    options: Mapping[str, Any]
    resolved_seed: int
    model_identity: str
    renderer_identity: str
    codec_identity: str
    corroboration_grade: CorroborationGrade
    # T2-003: one UpstreamLineageV1 document per granted actor_output source
    upstream: Sequence[Mapping[str, Any]] = ()
    # T4-003: one memory lineage document per granted memory_artifact source
    memory: Sequence[Mapping[str, Any]] = ()

    def document(self) -> dict[str, Any]:
        document = {
            "schema": "boomvalley-lab-request-2",
            "messages": [dict(message) for message in self.messages],
            "options": dict(self.options),
            "resolved_seed": self.resolved_seed,
            "model_identity": self.model_identity,
            "renderer_identity": self.renderer_identity,
            "codec_identity": self.codec_identity,
            "corroboration_grade": self.corroboration_grade.value,
        }
        if self.upstream:
            document["upstream"] = [dict(item) for item in self.upstream]
        if self.memory:
            document["memory"] = [dict(item) for item in self.memory]
        return document

    def identity(self) -> RequestIdentity:
        return RequestIdentity.of_document(self.document())


UPSTREAM_KINDS = frozenset({"actor_call", "proposal_parse"})


@dataclass(frozen=True)
class UpstreamLineageV1:
    """The committed identity one actor_output source carried into a request.

    ``identity`` is the producer's CallIdentity (actor_call) or
    ProposalIdentity (proposal_parse) document; ``content_sha256`` the digest
    of the bytes the source carried (before any transform).
    """

    source_id: str
    producer: str
    producer_kind: str
    identity: Mapping[str, str]
    content_sha256: str

    def __post_init__(self) -> None:
        if self.producer_kind not in UPSTREAM_KINDS:
            raise ValueError(f"upstream producer kind {self.producer_kind!r} is not lineage")

    def document(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "producer": self.producer,
            "producer_kind": self.producer_kind,
            "identity": dict(self.identity),
            "content_sha256": self.content_sha256,
        }
