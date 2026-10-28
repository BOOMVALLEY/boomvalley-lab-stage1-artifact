"""P05 information source registry and default-deny access (T1-002).

Information rights are runtime semantics, not prompt conventions.  The path
from a declared source to an actor request is structural:

    InformationSourceV1         declared, frozen content (``frozen_resource``)
    -> AccessRuleV1             ALLOW / DENY per actor x source, optionally
                                ``when`` one design cell's factor levels
    -> InformationAccessSetV1   resolved per plan: actor -> granted sources;
                                enters the frozen plan (``semantic-plan-3``)
    -> AuthorizedObservationV1  exactly the granted contents of one actor;
                                the only information a renderer receives
    -> request-2 / intent

Access is **default-deny**: an actor observes a source only when an ALLOW rule
matches it in the cell, and no DENY rule does (both matching is ambiguous and
refused, never silently ordered).  A rule's ``when`` levels only select; the
resolved access set carries grants, never the factor labels, so a factor the
access rules do not name cannot change access or request content.

Denied content never reaches a plugin: the kernel builds the observation from
granted sources only, a renderer reading anything else is refused
(BVL-INFO-011), source files are denied for direct reads inside plugin
windows, and the rendered request-2 is checked for denied content before
intent (BVL-INFO-005), so a refusal costs zero provider calls.

The plan carries each source's content digest and size, not its location: the
file path is not scientific meaning, the frozen bytes are.

Actor output as a named source (T2-001, P05 x P13 visibility)
-------------------------------------------------------------
Another actor's output reaches an actor only as a declared ``actor_output``
source (``ActorOutputSourceV1``): a name bound to one producer node of the
protocol - an ``actor_call`` (the custody-accepted response bytes) or a
``proposal_parse`` (the parsed proposal as canonical JSON).  It passes the
same default-deny access and transform stages as a frozen resource; nothing
else carries upstream values to a renderer (the pipeline hands renderers a
context without the round's dataflow).  Its content does not exist when the
plan is frozen, so the plan binds the producer instead of a digest
(``bvl-information-access-3``), and the visibility is checked against the
protocol before any call: every call node of a granted actor must have the
producer as a same-round ancestor, otherwise BVL-INFO-012.

Memory as a named source (T4-003, P05 x P16)
--------------------------------------------
Memory reaches an actor only as a declared ``memory_artifact`` source
(``MemoryArtifactSourceV1``): a name bound to one ``memory_update`` node that
declares a memory lifecycle (``kernel/memory``).  In round *r* it carries the
node's committed Memory Artifacts valid in *r* - produced in earlier rounds
of the same episode - so it exists, possibly empty, for every call.  The plan
binds the producer (``bvl-information-access-4``); access stays default-deny.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import CanonicalisationError, DeclarationError
from boomvalley_lab.kernel.actors import ActorBindingSetV1
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.request import UpstreamLineageV1

ACCESS_SET_SCHEMA = "bvl-information-access-1"
# access-2 (T1-003) adds per-grant registered transforms; an access set
# without transforms keeps the access-1 document byte-for-byte.
ACCESS_SET_SCHEMA_V2 = "bvl-information-access-2"
# access-3 (T2-001) adds actor_output sources (P13 visibility); an access set
# without them keeps its access-1/-2 document byte-for-byte.
ACCESS_SET_SCHEMA_V3 = "bvl-information-access-3"
# access-4 (T4-003) adds memory_artifact sources (P16 lifecycle); an access
# set without them keeps its access-1/-2/-3 document byte-for-byte.
ACCESS_SET_SCHEMA_V4 = "bvl-information-access-4"
_ACCESS_SCHEMAS = (
    ACCESS_SET_SCHEMA,
    ACCESS_SET_SCHEMA_V2,
    ACCESS_SET_SCHEMA_V3,
    ACCESS_SET_SCHEMA_V4,
)
ACTOR_OUTPUT_PRODUCERS = frozenset({NodeKind.ACTOR_CALL, NodeKind.PROPOSAL_PARSE})

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_HEX64 = re.compile(r"[0-9a-f]{64}")

# P05 §8 stable reason-code family
SOURCE_UNKNOWN = "BVL-INFO-001"
SOURCE_UNRESOLVED = "BVL-INFO-002"
ACCESS_RULE_AMBIGUOUS = "BVL-INFO-003"
ACCESS_EFFECT_UNKNOWN = "BVL-INFO-004"
DENIED_SOURCE_LEAK = "BVL-INFO-005"
RENDERER_NOT_REGISTERED = "BVL-INFO-006"
RENDERER_IDENTITY_MISMATCH = "BVL-INFO-007"
REQUEST_RENDER_FAILED = "BVL-INFO-008"
REQUEST_IDENTITY_MISMATCH = "BVL-INFO-009"
POST_INTENT_SCIENTIFIC_MUTATION = "BVL-INFO-010"
UNDECLARED_SOURCE_READ = "BVL-INFO-011"
ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE = "BVL-INFO-012"

INFO_CODES = frozenset(
    {
        SOURCE_UNKNOWN,
        SOURCE_UNRESOLVED,
        ACCESS_RULE_AMBIGUOUS,
        ACCESS_EFFECT_UNKNOWN,
        DENIED_SOURCE_LEAK,
        RENDERER_NOT_REGISTERED,
        RENDERER_IDENTITY_MISMATCH,
        REQUEST_RENDER_FAILED,
        REQUEST_IDENTITY_MISMATCH,
        POST_INTENT_SCIENTIFIC_MUTATION,
        UNDECLARED_SOURCE_READ,
        ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
    }
)


class InformationError(DeclarationError):
    """A P05 refusal carrying one stable ``BVL-INFO-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in INFO_CODES:
            raise ValueError(f"unknown information reason code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code


class SourceKind(StrEnum):
    FROZEN_RESOURCE = "frozen_resource"
    ACTOR_OUTPUT = "actor_output"  # P13 visibility (T2-001)
    WORLD_OBSERVATION = "world_observation"  # P15
    MEMORY_ARTIFACT = "memory_artifact"  # P16


class AccessEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


def _require_id(value: Any, what: str, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise InformationError(code, f"{what} is not a valid identifier: {value!r}")
    return value


@dataclass(frozen=True)
class SourceDescriptorV1:
    """What the plan knows of one source: kind, content digest and size."""

    source_id: str
    source_kind: SourceKind
    content_sha256: str
    size: int

    def document(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind.value,
            "content_sha256": self.content_sha256,
            "size": self.size,
        }


def _descriptor(source_id: str, kind: SourceKind, content: bytes) -> SourceDescriptorV1:
    return SourceDescriptorV1(source_id, kind, sha256_bytes(content).hex, len(content))


@dataclass(frozen=True)
class ActorOutputDescriptorV1:
    """What the plan knows of one actor_output source: its producer node.

    The content is produced in each round, so the plan binds where it comes
    from; the observed digest is evidenced per call and recomputed by the
    verifier from the producer's committed output.
    """

    source_id: str
    producer: str
    source_kind: SourceKind = SourceKind.ACTOR_OUTPUT

    def document(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind.value,
            "producer": self.producer,
        }


@dataclass(frozen=True)
class MemoryArtifactDescriptorV1:
    """What the plan knows of one memory_artifact source: its memory_update node.

    The content is the node's Memory Artifacts valid in the observing round;
    the observed digest is evidenced per call and recomputed by the verifier
    from the committed artifacts.
    """

    source_id: str
    producer: str
    source_kind: SourceKind = SourceKind.MEMORY_ARTIFACT

    def document(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind.value,
            "producer": self.producer,
        }


def actor_output_content(value: Any) -> bytes:
    """The bytes an actor_output source carries for one committed producer value.

    actor_call: the custody-accepted response content.  proposal_parse: the
    parsed proposal value as canonical JSON (what the verifier re-derives from
    proposal evidence).
    """

    response = getattr(value, "response", None)
    if response is not None and isinstance(getattr(response, "content", None), bytes):
        return response.content
    proposal = getattr(value, "value", None)
    if getattr(value, "actor_call", None) is not None and isinstance(proposal, Mapping):
        return canonical_json(dict(proposal)).encode("utf-8")
    raise InformationError(
        ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
        f"{type(value).__name__} is not an actor_call or proposal_parse output",
    )


def actor_output_lineage(source_id: str, producer: str, value: Any) -> UpstreamLineageV1:
    """The committed identity an actor_output source carries into request-2 (T2-003).

    actor_call: the custody-accepted CallIdentity.  proposal_parse: the
    committed ProposalIdentity.  Both with the digest of the source bytes
    (``actor_output_content``), so the request names exactly which upstream
    output it observed.
    """

    content = actor_output_content(value)
    if getattr(value, "actor_call", None) is not None:
        kind, identity = "proposal_parse", getattr(value, "identity", None)
    else:
        kind, identity = "actor_call", getattr(value, "call_identity", None)
    if identity is None or not callable(getattr(identity, "document", None)):
        raise InformationError(
            ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
            f"actor_output {source_id!r}: producer {producer!r} output has no committed identity",
        )
    return UpstreamLineageV1(
        source_id=source_id,
        producer=producer,
        producer_kind=kind,
        identity=identity.document(),
        content_sha256=sha256_bytes(content).hex,
    )


@dataclass(frozen=True)
class ActorOutputSourceV1:
    """One declared actor_output source: a name for one producer node's output."""

    source_id: str
    producer: str

    def __post_init__(self) -> None:
        _require_id(self.source_id, "source id", SOURCE_UNKNOWN)
        _require_id(self.producer, f"source {self.source_id!r} producer", SOURCE_UNRESOLVED)

    @property
    def kind(self) -> SourceKind:
        return SourceKind.ACTOR_OUTPUT


@dataclass(frozen=True)
class MemoryArtifactSourceV1:
    """One declared memory_artifact source: a name for one memory_update node's memory."""

    source_id: str
    producer: str

    def __post_init__(self) -> None:
        _require_id(self.source_id, "source id", SOURCE_UNKNOWN)
        _require_id(self.producer, f"source {self.source_id!r} producer", SOURCE_UNRESOLVED)

    @property
    def kind(self) -> SourceKind:
        return SourceKind.MEMORY_ARTIFACT


@dataclass(frozen=True)
class InformationSourceV1:
    """One declared source.  At L1 only ``frozen_resource`` is executable."""

    source_id: str
    kind: SourceKind
    ref: Path

    def __post_init__(self) -> None:
        _require_id(self.source_id, "source id", SOURCE_UNKNOWN)
        try:
            kind = SourceKind(self.kind)
        except ValueError as error:
            raise InformationError(
                SOURCE_UNRESOLVED,
                f"source {self.source_id!r} kind {self.kind!r} is not one of "
                f"{sorted(item.value for item in SourceKind)}",
            ) from error
        if kind is SourceKind.ACTOR_OUTPUT:
            raise InformationError(
                ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
                f"source {self.source_id!r}: actor output is not a frozen file; declare it "
                "as an ActorOutputSourceV1 naming its producer node",
            )
        if kind is SourceKind.MEMORY_ARTIFACT:
            raise InformationError(
                SOURCE_UNRESOLVED,
                f"source {self.source_id!r}: memory is not a frozen file; declare it as a "
                "MemoryArtifactSourceV1 naming its memory_update node",
            )
        if kind is not SourceKind.FROZEN_RESOURCE:
            raise InformationError(
                SOURCE_UNRESOLVED,
                f"source {self.source_id!r} kind {kind.value!r} is not executable at L1",
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "ref", Path(self.ref))

    def load(self) -> bytes:
        try:
            return self.ref.read_bytes()
        except OSError as error:
            raise InformationError(
                SOURCE_UNRESOLVED, f"source {self.source_id!r} cannot be read: {error}"
            ) from error


def _json_config(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InformationError(ACCESS_RULE_AMBIGUOUS, f"{what} is not an object")
    try:
        return json.loads(canonical_json(dict(value)))
    except (CanonicalisationError, TypeError, ValueError) as error:
        raise InformationError(ACCESS_RULE_AMBIGUOUS, f"{what} is not JSON: {error}") from error


@dataclass(frozen=True)
class TransformSpecV1:
    """One registered transform applied to one granted source (P05 §2).

    ``transform`` is the transform's registered plugin identity; ``config``
    its canonical JSON configuration.  Both enter the plan.
    """

    transform: str
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.transform, str) or not self.transform.strip():
            raise InformationError(ACCESS_RULE_AMBIGUOUS, "a transform names its identity")
        config = _json_config(self.config, f"transform {self.transform!r} config")
        object.__setattr__(self, "config", MappingProxyType(config))

    def document(self) -> dict[str, Any]:
        return {
            "transform": self.transform,
            "config": json.loads(canonical_json(dict(self.config))),
        }


@dataclass(frozen=True)
class AccessRuleV1:
    actor: str
    source: str
    effect: AccessEffect
    when: Mapping[str, str] = field(default_factory=dict)
    # ALLOW only: the actor observes the source through this transform
    transform: TransformSpecV1 | None = None

    def __post_init__(self) -> None:
        _require_id(self.actor, "access rule actor", ACCESS_RULE_AMBIGUOUS)
        _require_id(self.source, "access rule source", SOURCE_UNKNOWN)
        try:
            effect = AccessEffect(self.effect)
        except ValueError as error:
            raise InformationError(
                ACCESS_EFFECT_UNKNOWN,
                f"access effect {self.effect!r} is not one of "
                f"{sorted(item.value for item in AccessEffect)}",
            ) from error
        if not isinstance(self.when, Mapping) or not all(
            isinstance(key, str) and _ID.fullmatch(key) and isinstance(level, str) and level
            for key, level in self.when.items()
        ):
            raise InformationError(
                ACCESS_RULE_AMBIGUOUS, f"access rule when {self.when!r} is not factor -> level"
            )
        if self.transform is not None:
            if not isinstance(self.transform, TransformSpecV1):
                raise InformationError(
                    ACCESS_RULE_AMBIGUOUS,
                    f"access rule transform {self.transform!r} is not a TransformSpecV1",
                )
            if effect is not AccessEffect.ALLOW:
                raise InformationError(
                    ACCESS_RULE_AMBIGUOUS,
                    f"access rule {self.actor}/{self.source}: only ALLOW carries a transform",
                )
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "when", MappingProxyType(dict(self.when)))

    def matches(self, cell: Mapping[str, str]) -> bool:
        for factor, level in self.when.items():
            if factor not in cell:
                raise InformationError(
                    ACCESS_RULE_AMBIGUOUS,
                    f"access rule {self.actor}/{self.source} reads factor {factor!r}, "
                    "which the cell does not assign",
                )
            if cell[factor] != level:
                return False
        return True

    def document(self) -> dict[str, Any]:
        document = {
            "actor": self.actor,
            "source": self.source,
            "effect": self.effect.value,
            "when": dict(sorted(self.when.items())),
        }
        if self.transform is not None:
            document["transform"] = self.transform.document()
        return document


@dataclass(frozen=True)
class InformationAccessSetV1:
    """The resolved access of one plan: semantic content only, canonical.

    ``grants`` names every plan actor; an empty grant is an actor that may
    observe nothing.  This document enters the plan, so PlanIdentity binds
    which content each actor may observe.
    """

    sources: Mapping[
        str, SourceDescriptorV1 | ActorOutputDescriptorV1 | MemoryArtifactDescriptorV1
    ]
    grants: Mapping[str, tuple[str, ...]]
    # actor -> granted source -> the transform its observation passes through
    transforms: Mapping[str, Mapping[str, TransformSpecV1]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for source_id, descriptor in self.sources.items():
            if descriptor.source_id != source_id:
                raise InformationError(SOURCE_UNKNOWN, f"descriptor {source_id!r} names another")
        for actor_id, granted in self.grants.items():
            for source_id in granted:
                if source_id not in self.sources:
                    raise InformationError(
                        SOURCE_UNKNOWN, f"actor {actor_id!r} is granted undeclared {source_id!r}"
                    )
        transforms: dict[str, Mapping[str, TransformSpecV1]] = {}
        for actor_id, specs in self.transforms.items():
            for source_id, spec in specs.items():
                if source_id not in self.grants.get(actor_id, ()):
                    raise InformationError(
                        ACCESS_RULE_AMBIGUOUS,
                        f"actor {actor_id!r} has a transform for ungranted source {source_id!r}",
                    )
                if not isinstance(spec, TransformSpecV1):
                    raise InformationError(ACCESS_RULE_AMBIGUOUS, f"{spec!r} is not a transform")
            if specs:
                transforms[actor_id] = MappingProxyType(dict(specs))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))
        object.__setattr__(
            self,
            "grants",
            MappingProxyType(
                {key: tuple(sorted(set(value))) for key, value in self.grants.items()}
            ),
        )
        object.__setattr__(self, "transforms", MappingProxyType(transforms))

    def granted(self, actor_id: str) -> tuple[str, ...]:
        if actor_id not in self.grants:
            raise InformationError(
                ACCESS_RULE_AMBIGUOUS, f"actor {actor_id!r} has no resolved access in the plan"
            )
        return self.grants[actor_id]

    def denied(self, actor_id: str) -> tuple[str, ...]:
        granted = set(self.granted(actor_id))
        return tuple(sorted(source for source in self.sources if source not in granted))

    def transforms_of(self, actor_id: str) -> Mapping[str, TransformSpecV1]:
        self.granted(actor_id)
        return self.transforms.get(actor_id, MappingProxyType({}))

    @property
    def actor_outputs(self) -> Mapping[str, ActorOutputDescriptorV1]:
        """source id -> producer descriptor of every actor_output source."""

        return MappingProxyType(
            {
                key: value
                for key, value in sorted(self.sources.items())
                if isinstance(value, ActorOutputDescriptorV1)
            }
        )

    @property
    def memory_artifacts(self) -> Mapping[str, MemoryArtifactDescriptorV1]:
        """source id -> producer descriptor of every memory_artifact source."""

        return MappingProxyType(
            {
                key: value
                for key, value in sorted(self.sources.items())
                if isinstance(value, MemoryArtifactDescriptorV1)
            }
        )

    def require_protocol(self, protocol: ProtocolIR) -> None:
        """P13 visibility is satisfiable by the protocol, before any call.

        Each actor_output producer is an actor_call or proposal_parse node,
        and is a same-round ancestor of every call node of an actor granted it
        (so the output exists, deterministically, when the actor observes).
        """

        nodes = {node.node_id: node for node in protocol.nodes}
        for source_id, descriptor in self.actor_outputs.items():
            producer = nodes.get(descriptor.producer)
            if producer is None or producer.kind not in ACTOR_OUTPUT_PRODUCERS:
                raise InformationError(
                    ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
                    f"source {source_id!r} producer {descriptor.producer!r} is not an "
                    "actor_call or proposal_parse node of the protocol",
                )
        for actor_id in sorted(self.grants):
            outputs = [s for s in self.grants[actor_id] if s in self.actor_outputs]
            calls = [
                node
                for node in protocol.nodes
                if node.kind is NodeKind.ACTOR_CALL and node.config.get("actor") == actor_id
            ]
            for node in calls if outputs else ():
                ancestors = _ancestors(nodes, node.node_id)
                for source_id in outputs:
                    producer = self.actor_outputs[source_id].producer
                    if producer not in ancestors:
                        raise InformationError(
                            ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
                            f"actor {actor_id!r} is granted actor_output {source_id!r}, but "
                            f"its call {node.node_id!r} does not depend on producer "
                            f"{producer!r} in the round",
                        )

    def document(self) -> dict[str, Any]:
        if self.memory_artifacts:
            schema = ACCESS_SET_SCHEMA_V4
        elif self.actor_outputs:
            schema = ACCESS_SET_SCHEMA_V3
        elif self.transforms:
            schema = ACCESS_SET_SCHEMA_V2
        else:
            schema = ACCESS_SET_SCHEMA
        document: dict[str, Any] = {
            "schema": schema,
            "sources": [self.sources[key].document() for key in sorted(self.sources)],
            "grants": [
                {"actor_id": key, "sources": list(self.grants[key])}
                for key in sorted(self.grants)
            ],
        }
        if self.transforms or schema in (ACCESS_SET_SCHEMA_V3, ACCESS_SET_SCHEMA_V4):
            document["transforms"] = [
                {"actor_id": actor_id, "source_id": source_id, **spec.document()}
                for actor_id in sorted(self.transforms)
                for source_id, spec in sorted(self.transforms[actor_id].items())
            ]
        return document

    def require_actors(self, actors: ActorBindingSetV1) -> None:
        """Access is resolved for exactly the plan's actors."""

        if set(self.grants) != set(actors.bindings):
            raise InformationError(
                ACCESS_RULE_AMBIGUOUS,
                f"access is resolved for {sorted(self.grants)}, "
                f"the plan executes {sorted(actors.bindings)}",
            )

    @classmethod
    def from_document(cls, document: Any) -> InformationAccessSetV1:
        """Read one ``bvl-information-access-1`` .. ``-4`` back (closed, canonical)."""

        bad = InformationError(SOURCE_UNRESOLVED, "information access set has the wrong shape")
        keys = {"schema", "sources", "grants"}
        if isinstance(document, Mapping) and document.get("schema") in (
            ACCESS_SET_SCHEMA_V2,
            ACCESS_SET_SCHEMA_V3,
            ACCESS_SET_SCHEMA_V4,
        ):
            keys = keys | {"transforms"}
        v4 = isinstance(document, Mapping) and document.get("schema") == ACCESS_SET_SCHEMA_V4
        v3 = v4 or (
            isinstance(document, Mapping) and document.get("schema") == ACCESS_SET_SCHEMA_V3
        )
        if (
            not isinstance(document, Mapping)
            or set(document) != keys
            or document["schema"] not in _ACCESS_SCHEMAS
            or not isinstance(document["sources"], list)
            or not isinstance(document["grants"], list)
            or not isinstance(document.get("transforms", []), list)
        ):
            raise bad
        sources: dict[
            str, SourceDescriptorV1 | ActorOutputDescriptorV1 | MemoryArtifactDescriptorV1
        ] = {}
        for item in document["sources"]:
            if (
                v4
                and isinstance(item, Mapping)
                and item.get("source_kind") == SourceKind.MEMORY_ARTIFACT.value
            ):
                if set(item) != {"source_id", "source_kind", "producer"}:
                    raise bad
                source_id = _require_id(item["source_id"], "source id", SOURCE_UNKNOWN)
                producer = _require_id(item["producer"], "producer", SOURCE_UNRESOLVED)
                if source_id in sources:
                    raise bad
                sources[source_id] = MemoryArtifactDescriptorV1(source_id, producer)
                continue
            if (
                v3
                and isinstance(item, Mapping)
                and item.get("source_kind") == SourceKind.ACTOR_OUTPUT.value
            ):
                if set(item) != {"source_id", "source_kind", "producer"}:
                    raise bad
                source_id = _require_id(item["source_id"], "source id", SOURCE_UNKNOWN)
                producer = _require_id(item["producer"], "producer", SOURCE_UNRESOLVED)
                if source_id in sources:
                    raise bad
                sources[source_id] = ActorOutputDescriptorV1(source_id, producer)
                continue
            if not isinstance(item, Mapping) or set(item) != {
                "source_id",
                "source_kind",
                "content_sha256",
                "size",
            }:
                raise bad
            source_id = _require_id(item["source_id"], "source id", SOURCE_UNKNOWN)
            if (
                source_id in sources
                or item["source_kind"] != SourceKind.FROZEN_RESOURCE.value
                or not isinstance(item["content_sha256"], str)
                or not _HEX64.fullmatch(item["content_sha256"])
                or not isinstance(item["size"], int)
                or isinstance(item["size"], bool)
                or item["size"] < 0
            ):
                raise bad
            sources[source_id] = SourceDescriptorV1(
                source_id, SourceKind.FROZEN_RESOURCE, item["content_sha256"], item["size"]
            )
        grants: dict[str, tuple[str, ...]] = {}
        for item in document["grants"]:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"actor_id", "sources"}
                or not isinstance(item["sources"], list)
            ):
                raise bad
            actor_id = _require_id(item["actor_id"], "actor id", ACCESS_RULE_AMBIGUOUS)
            if actor_id in grants:
                raise bad
            grants[actor_id] = tuple(item["sources"])
        transforms: dict[str, dict[str, TransformSpecV1]] = {}
        for item in document.get("transforms", ()):
            if not isinstance(item, Mapping) or set(item) != {
                "actor_id",
                "source_id",
                "transform",
                "config",
            }:
                raise bad
            specs = transforms.setdefault(item["actor_id"], {})
            if item["source_id"] in specs:
                raise bad
            specs[item["source_id"]] = TransformSpecV1(item["transform"], item["config"])
        if document["schema"] == ACCESS_SET_SCHEMA_V2 and not transforms:
            raise bad  # access-2 exists only to carry transforms
        parsed = cls(sources, grants, transforms)
        if parsed.document() != json.loads(canonical_json(dict(document))):
            raise InformationError(SOURCE_UNRESOLVED, "information access set is not canonical")
        return parsed


class InformationSourceStoreV1:
    """Kernel-held frozen source contents, verified against the plan.

    Plugins never receive this object; ``observation`` hands one actor its
    granted contents only.
    """

    def __init__(self, contents: Mapping[str, bytes], paths: Sequence[Path] = ()) -> None:
        self._contents = {key: bytes(value) for key, value in contents.items()}
        self._paths = tuple(Path(path) for path in paths)

    @property
    def paths(self) -> tuple[Path, ...]:
        """Source locations a contained engine denies to every plugin window."""

        return self._paths

    def _verified(
        self,
        access: InformationAccessSetV1,
        source_id: str,
        produced: Mapping[str, bytes] | None = None,
    ) -> bytes:
        descriptor = access.sources.get(source_id)
        if isinstance(descriptor, MemoryArtifactDescriptorV1):
            content = (produced or {}).get(source_id)
            if not isinstance(content, bytes):
                raise InformationError(
                    SOURCE_UNRESOLVED,
                    f"memory_artifact {source_id!r} of producer {descriptor.producer!r} has "
                    "no engine-held Memory Artifacts in this round",
                )
            return content
        if isinstance(descriptor, ActorOutputDescriptorV1):
            content = (produced or {}).get(source_id)
            if not isinstance(content, bytes):
                raise InformationError(
                    ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
                    f"actor_output {source_id!r} of producer {descriptor.producer!r} has no "
                    "committed output in this round",
                )
            return content
        content = self._contents.get(source_id)
        if content is None or descriptor is None:
            raise InformationError(
                SOURCE_UNRESOLVED, f"source {source_id!r} has no frozen content"
            )
        if _descriptor(source_id, descriptor.source_kind, content) != descriptor:
            raise InformationError(
                SOURCE_UNRESOLVED,
                f"source {source_id!r} content does not match its frozen plan digest",
            )
        return content

    def observation(
        self,
        access: InformationAccessSetV1,
        actor_id: str,
        produced: Mapping[str, bytes] | None = None,
    ) -> AuthorizedObservationV1:
        """Exactly the granted, digest-verified contents of *actor_id*.

        *produced* holds the round's granted actor_output contents (T2-001)
        and the granted memory_artifact contents valid in it (T4-003).
        Denied sources are not read, copied or referenced here.
        """

        return AuthorizedObservationV1(
            actor_id,
            {
                source_id: self._verified(access, source_id, produced)
                for source_id in access.granted(actor_id)
            },
        )

    def require_no_denied_content(
        self,
        access: InformationAccessSetV1,
        actor_id: str,
        request_document: Any,
        *,
        visible: Mapping[str, bytes] | None = None,
    ) -> None:
        """Refuse a rendered request carrying content withheld from the actor.

        Withheld is every denied source, and the raw bytes of a granted source
        the actor observes only through a transform (``visible`` holds the
        observed contents; default: the granted raw bytes).  A withheld text
        that also occurs in observed content is lawfully observable.
        """

        # actor_output content is withheld structurally: a renderer's context
        # carries no upstream values (BVL-REC-142), nor memory (T4-003)
        frozen = [
            source
            for source in access.sources
            if source not in access.actor_outputs and source not in access.memory_artifacts
        ]
        granted = [source for source in access.granted(actor_id) if source in frozen]
        if visible is None:
            visible = {source: self._verified(access, source) for source in granted}
        observed = list(visible.values())
        withheld = [source for source in access.denied(actor_id) if source in frozen]
        withheld += [
            source for source in granted if visible.get(source) != self._verified(access, source)
        ]
        strings = list(_strings(request_document))
        strings.append(canonical_json(request_document))
        for source_id in withheld:
            for needle in _needles(self._verified(access, source_id)):
                if any(needle.encode("utf-8") in content for content in observed):
                    continue
                if any(needle in value for value in strings):
                    raise InformationError(
                        DENIED_SOURCE_LEAK,
                        f"actor {actor_id!r} request carries denied source {source_id!r}",
                    )


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _needles(content: bytes) -> tuple[str, ...]:
    """Textual forms denied content takes inside a request document."""

    try:
        text = content.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ()
    if not text:
        return ()
    needles = {text, json.dumps(text)[1:-1]}
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict | list):
        canonical = canonical_json(parsed)
        needles.update({canonical, json.dumps(canonical)[1:-1]})
    return tuple(sorted(needles))


@dataclass(frozen=True)
class AuthorizedObservationV1:
    """The information one actor may observe in one call; nothing else."""

    actor_id: str
    contents: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "contents", MappingProxyType(dict(self.contents)))

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.contents))

    def read(self, source_id: str) -> bytes:
        if source_id not in self.contents:
            raise InformationError(
                UNDECLARED_SOURCE_READ,
                f"actor {self.actor_id!r} is not granted source {source_id!r}",
            )
        return self.contents[source_id]

    def text(self, source_id: str) -> str:
        return self.read(source_id).decode("utf-8")

    def json(self, source_id: str) -> Any:
        return json.loads(self.read(source_id))

    def document(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "sources": {key: sha256_bytes(self.contents[key]).hex for key in self.source_ids},
        }


class InformationRegistryV1:
    """The declared sources and access rules of one experiment."""

    def __init__(
        self,
        *,
        sources: Sequence[InformationSourceV1 | ActorOutputSourceV1 | MemoryArtifactSourceV1],
        access: Sequence[AccessRuleV1],
    ) -> None:
        self._sources: dict[
            str, InformationSourceV1 | ActorOutputSourceV1 | MemoryArtifactSourceV1
        ] = {}
        for source in sources:
            if source.source_id in self._sources:
                raise InformationError(
                    ACCESS_RULE_AMBIGUOUS, f"source id {source.source_id!r} is declared twice"
                )
            self._sources[source.source_id] = source
        self._access = tuple(access)
        for rule in self._access:
            if rule.source not in self._sources:
                raise InformationError(
                    SOURCE_UNKNOWN,
                    f"access rule for actor {rule.actor!r} names undeclared source "
                    f"{rule.source!r}",
                )

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))

    def frozen_contents(self) -> dict[str, bytes]:
        """The bytes of every declared frozen resource that can be read now.

        What a verifier is handed with a study (T5-008): whether they are the
        bytes a plan froze is the reader's check against that plan's digests.
        """

        found: dict[str, bytes] = {}
        for source_id, source in sorted(self._sources.items()):
            if isinstance(source, InformationSourceV1):
                try:
                    found[source_id] = source.load()
                except InformationError:
                    continue
        return found

    def factors(self) -> tuple[str, ...]:
        """The factors access resolution depends on (and nothing else does)."""

        return tuple(sorted({factor for rule in self._access for factor in rule.when}))

    def document(self) -> dict[str, Any]:
        """Canonical declaration: independent of source and rule order."""

        return {
            "sources": {key: _declared(self._sources[key]) for key in sorted(self._sources)},
            "access": sorted(
                (rule.document() for rule in self._access), key=canonical_json
            ),
        }

    def resolve(
        self, actors: ActorBindingSetV1, cell: Mapping[str, str] | None = None
    ) -> tuple[InformationAccessSetV1, InformationSourceStoreV1]:
        """Resolve default-deny access for the plan's actors in one design cell.

        Every source is loaded and digested here, before any run exists, so a
        missing or unreadable source refuses with zero calls.
        """

        cell = dict(cell or {})
        effects: dict[tuple[str, str], set[AccessEffect]] = {}
        allowed_via: dict[tuple[str, str], set[str]] = {}  # "" = untransformed
        specs: dict[str, TransformSpecV1] = {}
        for rule in self._access:
            actors.binding(rule.actor)  # BVL-ACTOR-009 for a rule outside the plan
            if rule.matches(cell):
                effects.setdefault((rule.actor, rule.source), set()).add(rule.effect)
                if rule.effect is AccessEffect.ALLOW:
                    key = canonical_json(rule.transform.document()) if rule.transform else ""
                    if rule.transform is not None:
                        specs[key] = rule.transform
                    allowed_via.setdefault((rule.actor, rule.source), set()).add(key)
        for (actor_id, source_id), found in sorted(allowed_via.items()):
            if len(found) > 1:
                raise InformationError(
                    ACCESS_RULE_AMBIGUOUS,
                    f"actor {actor_id!r} source {source_id!r} is ALLOWed through different "
                    "transforms in this cell",
                )
        for (actor_id, source_id), found in sorted(effects.items()):
            if len(found) > 1:
                raise InformationError(
                    ACCESS_RULE_AMBIGUOUS,
                    f"actor {actor_id!r} source {source_id!r} is both ALLOWed and DENYed "
                    "in this cell",
                )
        frozen = {
            key: source
            for key, source in sorted(self._sources.items())
            if isinstance(source, InformationSourceV1)
        }
        contents = {key: source.load() for key, source in frozen.items()}
        descriptors: dict[
            str, SourceDescriptorV1 | ActorOutputDescriptorV1 | MemoryArtifactDescriptorV1
        ] = {key: _descriptor(key, frozen[key].kind, contents[key]) for key in contents}
        for key, source in sorted(self._sources.items()):
            if isinstance(source, ActorOutputSourceV1):
                descriptors[key] = ActorOutputDescriptorV1(key, source.producer)
            elif isinstance(source, MemoryArtifactSourceV1):
                descriptors[key] = MemoryArtifactDescriptorV1(key, source.producer)
        access = InformationAccessSetV1(
            dict(sorted(descriptors.items())),
            {
                actor_id: tuple(
                    source_id
                    for source_id in sorted(self._sources)
                    if effects.get((actor_id, source_id)) == {AccessEffect.ALLOW}
                )
                for actor_id in sorted(actors.bindings)
            },
            {
                actor_id: {
                    source_id: specs[key]
                    for (actor, source_id), (key,) in sorted(allowed_via.items())
                    if actor == actor_id
                    and key
                    and effects[(actor, source_id)] == {AccessEffect.ALLOW}
                }
                for actor_id in sorted(actors.bindings)
            },
        )
        store = InformationSourceStoreV1(contents, [frozen[key].ref for key in frozen])
        return access, store


def _declared(
    source: InformationSourceV1 | ActorOutputSourceV1 | MemoryArtifactSourceV1,
) -> dict[str, Any]:
    if isinstance(source, ActorOutputSourceV1 | MemoryArtifactSourceV1):
        return {"kind": source.kind.value, "producer": source.producer}
    return {"kind": source.kind.value}


def _ancestors(nodes: Mapping[str, Any], node_id: str) -> set[str]:
    found: set[str] = set()
    pending = list(nodes[node_id].depends_on)
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(nodes[current].depends_on)
    return found
