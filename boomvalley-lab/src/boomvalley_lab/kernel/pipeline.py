"""P05 renderer/codec pipeline: the one path from source to request-2 (T1-003).

Every actor call of a plan that declares actors builds its scientific request
through exactly one explicit, kernel-owned pipeline:

    source        InformationSourceStoreV1: frozen, plan-digest-verified bytes
    -> access     InformationAccessSetV1: default-deny grants of the actor
    -> transform  per-grant registered transform (P05 §2: REDACT, ...), run
                  on granted bytes only; the actor's observation is the
                  transformed content (AuthorizedObservationV1)
    -> renderer   the profile's renderer turns the observation into
                  provider-neutral scientific messages (RenderingV1) - it does
                  not choose model, options, seed or transport encoding
    -> codec      the provider's codec encodes those messages for its
                  provider and declares the corroboration grade (P05 §13.4)
    -> request-2  the kernel assembles RequestV2 from the codec's messages and
                  the frozen ExecutionProfile (model/options/seed), checks it
                  for withheld content and hands it to the durable executor

Each layer contributes one identity (transform identity+config in the plan,
renderer and codec identity in request-2) and no layer repeats another's work.
Every refusal happens before intent, so it costs zero provider calls.

A provider without a registered codec is encoded by the core
``builtin.chat-messages-codec:1`` (pass-through, ``CLIENT_CANONICAL``).

Upstream dataflow is not information (T2-001): the renderer's context carries
no value of the round's earlier nodes (``RendererContextV1``; reading one is
BVL-INFO-011).  Another actor's output reaches the renderer only as a granted
``actor_output`` source in its observation, i.e. through an explicit P05
access rule over a P13 visibility the plan binds.  request-2 then binds the
exact committed identity of each granted actor_output (``upstream``, T2-003):
its producer, CallIdentity / ProposalIdentity and source digest.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, Protocol

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import CanonicalisationError, ExecutionError
from boomvalley_lab.kernel.actors import (
    PROFILE_IDENTITY_MISMATCH,
    ActorBindingV1,
    ActorError,
)
from boomvalley_lab.kernel.containment import (
    CODEC,
    RENDERER,
    TRANSFORM,
    active_session,
    invoke_pure,
)
from boomvalley_lab.kernel.engine import EngineContext
from boomvalley_lab.kernel.information import (
    ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
    REQUEST_RENDER_FAILED,
    UNDECLARED_SOURCE_READ,
    AuthorizedObservationV1,
    InformationError,
    InformationSourceStoreV1,
    TransformSpecV1,
    actor_output_content,
    actor_output_lineage,
)
from boomvalley_lab.kernel.memory import source_view
from boomvalley_lab.kernel.protocol import ProtocolNode
from boomvalley_lab.kernel.request import CorroborationGrade, RequestV2, UpstreamLineageV1

RENDERING_SCHEMA = "bvl-rendering-1"
PIPELINE_TRACE_SCHEMA = "bvl-request-pipeline-trace-1"
MESSAGE_ROLES = frozenset({"system", "user", "assistant"})


# --------------------------------------------------------------------------
# stage contracts
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RenderingV1:
    """Provider-neutral scientific content: ordered ``role``/``content`` messages.

    A renderer returns this and nothing else; model, options, seed and
    provider encoding are not its to choose.
    """

    messages: tuple[Mapping[str, str], ...]

    def __post_init__(self) -> None:
        messages = tuple(self.messages) if isinstance(self.messages, Sequence) else ()
        if not messages or isinstance(self.messages, str | bytes):
            raise InformationError(REQUEST_RENDER_FAILED, "a rendering has at least one message")
        frozen = []
        for message in messages:
            if (
                not isinstance(message, Mapping)
                or set(message) != {"role", "content"}
                or message["role"] not in MESSAGE_ROLES
                or not isinstance(message["content"], str)
            ):
                raise InformationError(
                    REQUEST_RENDER_FAILED,
                    f"a rendered message is exactly role in {sorted(MESSAGE_ROLES)} + string "
                    f"content, got {message!r}",
                )
            frozen.append(MappingProxyType(dict(message)))
        object.__setattr__(self, "messages", tuple(frozen))

    def document(self) -> dict[str, Any]:
        return {
            "schema": RENDERING_SCHEMA,
            "messages": [dict(message) for message in self.messages],
        }


class SourceTransformV1(Protocol):
    """A registered source-level transform: granted bytes -> observed bytes."""

    plugin_identity: str

    def transform(self, content: bytes, config: Mapping[str, Any]) -> bytes: ...


class ActorRendererV1(Protocol):
    """Observation -> provider-neutral scientific messages."""

    plugin_identity: str

    def render(
        self,
        node: ProtocolNode,
        context: EngineContext,
        *,
        observation: AuthorizedObservationV1,
    ) -> RenderingV1: ...


class ProviderCodecV1(Protocol):
    """Rendering -> the provider's message encoding, with an honest grade."""

    plugin_identity: str
    corroboration_grade: CorroborationGrade

    def encode(self, rendering: RenderingV1) -> Sequence[Mapping[str, Any]]: ...


def _withheld(node_id: Any) -> InformationError:
    return InformationError(
        UNDECLARED_SOURCE_READ,
        f"upstream value {node_id!r} reaches a renderer only as a granted "
        "actor_output information source (P05/P13)",
    )


class WithheldRoundV1(MutableMapping[str, Any]):
    """The round's dataflow as a renderer sees it: nothing is readable.

    Writes pass through to the engine-owned round, so an injected value is
    still judged by the engine's T0-016 step snapshot (never hidden by the
    view); reads refuse with BVL-INFO-011.  The round itself is held only in
    the writer closures, never as an attribute.
    """

    __slots__ = ("_write", "_delete")

    def __init__(self, current: dict[str, Any]) -> None:
        def write(node_id: str, value: Any) -> None:
            current[node_id] = value

        def delete(node_id: str) -> None:
            del current[node_id]

        self._write, self._delete = write, delete

    def __getitem__(self, node_id: str) -> Any:
        raise _withheld(node_id)

    def __setitem__(self, node_id: str, value: Any) -> None:
        self._write(node_id, value)

    def __delitem__(self, node_id: str) -> None:
        self._delete(node_id)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0

    def __repr__(self) -> str:
        return "WithheldRoundV1()"


class RendererContextV1:
    """The engine context a renderer receives: no upstream dataflow (T2-001).

    World state, memory, round and plan bindings read through to the engine
    context; the values of the round's earlier nodes do not
    (``WithheldRoundV1``), nor does the Memory Artifact ledger (T4-003: memory
    is observed only as a granted ``memory_artifact`` source).  Attribute
    writes pass through, so the engine's T0-016 snapshot still judges a
    rebinding.  The engine context is held
    only in per-call property closures (``renderer_context``), never as an
    attribute.  An actor observes another actor's output only as a granted
    ``actor_output`` source.
    """

    __slots__ = ()

    def dependency(self, node_id: str) -> Any:
        raise _withheld(node_id)


_WITHHELD = ("current_round", "memory_artifacts", "episode_key")
_VIEWED = tuple(item.name for item in fields(EngineContext) if item.name not in _WITHHELD)
_NO_MEMORY: Mapping[str, Any] = MappingProxyType({})


def renderer_context(context: EngineContext) -> RendererContextV1:
    withheld = WithheldRoundV1(context.current_round)

    def forwarded(name: str) -> property:
        def read(_view: RendererContextV1) -> Any:
            if name == "memory_artifacts":
                return _NO_MEMORY
            if name == "episode_key":
                return ""  # T4-004: the schedule is the engine's, not an observation
            return withheld if name == "current_round" else getattr(context, name)

        def write(_view: RendererContextV1, value: Any) -> None:
            setattr(context, name, value)

        return property(read, write)

    namespace: dict[str, Any] = {
        name: forwarded(name) for name in (*_VIEWED, *_WITHHELD)
    }
    namespace["__slots__"] = ()
    namespace["__dict__"] = property(
        lambda _view: {**{name: getattr(context, name) for name in _VIEWED},
                       "current_round": withheld, "memory_artifacts": _NO_MEMORY,
                       "episode_key": ""}
    )
    return type("RendererContextV1", (RendererContextV1,), namespace)()


# --------------------------------------------------------------------------
# core registered transforms / codec
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RedactJsonKeysTransformV1:
    """REDACT: drop the configured top-level keys of a JSON object source.

    config: ``{"keys": [<key>, ...]}``; output is canonical JSON bytes.
    """

    plugin_identity: str = "builtin.redact-json-keys:1"

    def transform(self, content: bytes, config: Mapping[str, Any]) -> bytes:
        keys = config.get("keys")
        if set(config) != {"keys"} or not isinstance(keys, list) or not all(
            isinstance(key, str) and key for key in keys
        ):
            raise InformationError(
                REQUEST_RENDER_FAILED, f"{self.plugin_identity} config is {{'keys': [str]}}"
            )
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise InformationError(
                REQUEST_RENDER_FAILED, f"{self.plugin_identity} needs a JSON source: {error}"
            ) from error
        if not isinstance(value, dict):
            raise InformationError(
                REQUEST_RENDER_FAILED, f"{self.plugin_identity} needs a JSON object source"
            )
        kept = {key: item for key, item in value.items() if key not in set(keys)}
        return canonical_json(kept).encode("utf-8")


@dataclass(frozen=True)
class ChatMessagesCodecV1:
    """Pass-through chat-messages codec for providers taking role/content lists.

    BVL holds the client-canonical messages, not post-template server bytes.
    """

    plugin_identity: str = "builtin.chat-messages-codec:1"
    corroboration_grade: CorroborationGrade = CorroborationGrade.CLIENT_CANONICAL

    def encode(self, rendering: RenderingV1) -> Sequence[Mapping[str, Any]]:
        return tuple(dict(message) for message in rendering.messages)


BUILTIN_TRANSFORMS: Mapping[str, SourceTransformV1] = MappingProxyType(
    {RedactJsonKeysTransformV1.plugin_identity: RedactJsonKeysTransformV1()}
)
DEFAULT_CODEC: ProviderCodecV1 = ChatMessagesCodecV1()


# --------------------------------------------------------------------------
# evidence of one pipeline run
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PipelineTraceV1:
    """Which information the actor could observe and what was sent (P05 §4)."""

    actor_id: str
    considered: tuple[str, ...]
    granted: tuple[str, ...]
    denied: tuple[str, ...]
    transforms: Mapping[str, TransformSpecV1]
    observation: Mapping[str, str]  # source -> sha256 of the observed bytes
    renderer: str
    rendering_sha256: str
    codec: str
    corroboration_grade: CorroborationGrade
    request_identity: str

    def document(self) -> dict[str, Any]:
        return {
            "schema": PIPELINE_TRACE_SCHEMA,
            "actor_id": self.actor_id,
            "considered": list(self.considered),
            "granted": list(self.granted),
            "denied": list(self.denied),
            "transforms": {
                key: self.transforms[key].document() for key in sorted(self.transforms)
            },
            "observation": dict(sorted(self.observation.items())),
            "renderer": self.renderer,
            "rendering_sha256": self.rendering_sha256,
            "codec": self.codec,
            "corroboration_grade": self.corroboration_grade.value,
            "request_identity": self.request_identity,
        }


@dataclass(frozen=True)
class BuiltRequestV1:
    request: RequestV2
    trace: PipelineTraceV1


def _rendering_document(value: Any) -> Any:
    return value.document() if isinstance(value, RenderingV1) else repr(value)


def _encoded_document(value: Any) -> Any:
    try:
        return json.loads(canonical_json(list(value)))
    except (CanonicalisationError, TypeError, ValueError):
        return repr(value)


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------
class RequestPipelineV1:
    """source -> access -> transform -> renderer -> codec -> request-2.

    Kernel-owned and stateless across calls; the source store never leaves
    it, and plugins see only what their stage is entitled to.
    """

    def __init__(
        self,
        *,
        sources: InformationSourceStoreV1 | None = None,
        transforms: Mapping[str, SourceTransformV1] | None = None,
    ) -> None:
        supplied = dict(transforms or {})
        clash = sorted(set(supplied) & set(BUILTIN_TRANSFORMS))
        if clash:
            raise ValueError(f"transforms {clash} would shadow core registered transforms")
        for identity, plugin in supplied.items():
            if getattr(plugin, "plugin_identity", None) != identity:
                raise ValueError(f"transform supplied as {identity!r} is another plugin")
        self._sources = sources
        self._transforms = {**BUILTIN_TRANSFORMS, **supplied}

    # stage 1-3 ------------------------------------------------------------
    def observe(
        self, context: EngineContext, actor_id: str
    ) -> tuple[AuthorizedObservationV1, Mapping[str, TransformSpecV1]]:
        """Source, access and transform stages: the actor's observation."""

        access = context.information
        if access is None:
            if self._sources is not None:
                raise ExecutionError("information sources are supplied for a plan without them")
            return AuthorizedObservationV1(actor_id, {}), {}
        sources = self._sources
        if sources is None:
            raise InformationError(
                UNDECLARED_SOURCE_READ, "the plan declares information but no source store"
            )
        session = active_session()
        if session is not None:
            exposed = [str(path) for path in sources.paths if not session.denies(path)]
            if exposed:
                raise InformationError(
                    UNDECLARED_SOURCE_READ,
                    f"information sources {exposed} are readable from plugin windows",
                )
        produced: dict[str, bytes] = {}
        for source_id in access.granted(actor_id):
            remembered = access.memory_artifacts.get(source_id)
            if remembered is not None:
                # T4-003: the node's committed artifacts valid in this round
                produced[source_id], _ = source_view(
                    source_id,
                    remembered.producer,
                    context.memory_artifacts.get(remembered.producer, ()),
                    context.round_index,
                    context.episode_identity.document(),
                )
                continue
            descriptor = access.actor_outputs.get(source_id)
            if descriptor is None:
                continue
            if descriptor.producer not in context.current_round:
                raise InformationError(
                    ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
                    f"actor_output {source_id!r}: producer {descriptor.producer!r} has no "
                    f"committed output in round {context.round_index}",
                )
            produced[source_id] = actor_output_content(
                context.current_round[descriptor.producer]
            )
        # default-deny; denied sources (and denied actor outputs) are never read
        granted = sources.observation(access, actor_id, produced)
        specs = access.transforms_of(actor_id)
        contents = dict(granted.contents)
        for source_id, spec in sorted(specs.items()):
            plugin = self._transforms.get(spec.transform)
            if plugin is None:
                raise InformationError(
                    REQUEST_RENDER_FAILED,
                    f"transform {spec.transform!r} of actor {actor_id!r} source {source_id!r} "
                    "is not registered",
                )
            raw = contents[source_id]
            config = json.loads(canonical_json(dict(spec.config)))
            output = invoke_pure(
                TRANSFORM,
                plugin,
                lambda transform, raw=raw, config=config: transform.transform(raw, config),
                lambda value: sha256_bytes(value).hex if isinstance(value, bytes) else repr(value),
            )
            if not isinstance(output, bytes):
                raise InformationError(
                    REQUEST_RENDER_FAILED, f"transform {spec.transform!r} did not return bytes"
                )
            contents[source_id] = output
        return AuthorizedObservationV1(actor_id, contents), specs

    @staticmethod
    def upstream(context: EngineContext, actor_id: str) -> tuple[UpstreamLineageV1, ...]:
        """The committed identity of every actor_output the actor observes (T2-003).

        The producer's value was admitted on its committed journal-2 evidence
        (T2-002), so its identity is the committed call / proposal identity.
        """

        access = context.information
        if access is None:
            return ()
        lineage = []
        for source_id in sorted(access.granted(actor_id)):
            descriptor = access.actor_outputs.get(source_id)
            if descriptor is None:
                continue
            if descriptor.producer not in context.current_round:
                raise InformationError(
                    ACTOR_OUTPUT_SOURCE_NOT_AVAILABLE,
                    f"actor_output {source_id!r}: producer {descriptor.producer!r} has no "
                    f"committed output in round {context.round_index}",
                )
            lineage.append(actor_output_lineage(
                source_id, descriptor.producer, context.current_round[descriptor.producer]
            ))
        return tuple(lineage)

    @staticmethod
    def memory(context: EngineContext, actor_id: str) -> tuple[Mapping[str, Any], ...]:
        """The committed Memory Artifacts of every memory source the actor observes."""

        access = context.information
        if access is None:
            return ()
        return tuple(
            source_view(
                source_id,
                access.memory_artifacts[source_id].producer,
                context.memory_artifacts.get(access.memory_artifacts[source_id].producer, ()),
                context.round_index,
                context.episode_identity.document(),
            )[1]
            for source_id in sorted(access.granted(actor_id))
            if source_id in access.memory_artifacts
        )

    # stage 4-6 ------------------------------------------------------------
    def build(
        self,
        *,
        node: ProtocolNode,
        context: EngineContext,
        binding: ActorBindingV1,
        renderer: ActorRendererV1,
        codec: ProviderCodecV1,
        seed: int,
    ) -> BuiltRequestV1:
        profile = binding.profile
        if getattr(renderer, "plugin_identity", None) != profile.renderer:
            raise ActorError(
                PROFILE_IDENTITY_MISMATCH,
                f"actor {binding.actor_id!r} renderer is {renderer.plugin_identity!r}, "
                f"its profile binds {profile.renderer!r}",
            )
        observation, specs = self.observe(context, binding.actor_id)
        upstream = self.upstream(context, binding.actor_id)
        remembered = self.memory(context, binding.actor_id)
        view = renderer_context(context)

        rendering = invoke_pure(
            RENDERER,
            renderer,
            lambda plugin: plugin.render(node, view, observation=observation),
            _rendering_document,
        )
        if not isinstance(rendering, RenderingV1):
            raise InformationError(
                REQUEST_RENDER_FAILED,
                f"renderer {profile.renderer!r} returned {type(rendering).__name__}, "
                "not a RenderingV1 (it renders content only)",
            )

        try:
            grade = CorroborationGrade(codec.corroboration_grade)
        except (AttributeError, ValueError) as error:
            raise InformationError(
                REQUEST_RENDER_FAILED,
                f"codec {getattr(codec, 'plugin_identity', codec)!r} declares no "
                "corroboration grade",
            ) from error
        encoded = invoke_pure(
            CODEC,
            codec,
            lambda plugin: tuple(plugin.encode(rendering)),
            _encoded_document,
        )
        if not encoded or not all(isinstance(message, Mapping) for message in encoded):
            raise InformationError(
                REQUEST_RENDER_FAILED, f"codec {codec.plugin_identity!r} encoded no messages"
            )
        try:
            messages = tuple(json.loads(canonical_json(dict(message))) for message in encoded)
        except (CanonicalisationError, TypeError, ValueError) as error:
            raise InformationError(
                REQUEST_RENDER_FAILED,
                f"codec {codec.plugin_identity!r} encoded non-canonical messages: {error}",
            ) from error

        request = RequestV2(
            messages=messages,
            options=dict(profile.options),
            resolved_seed=seed,
            model_identity=profile.model,
            renderer_identity=renderer.plugin_identity,
            codec_identity=codec.plugin_identity,
            corroboration_grade=grade,
            upstream=tuple(item.document() for item in upstream),
            memory=remembered,
        )
        access = context.information
        if access is not None:
            self._sources.require_no_denied_content(
                access, binding.actor_id, request.document(), visible=observation.contents
            )
        trace = PipelineTraceV1(
            actor_id=binding.actor_id,
            considered=tuple(sorted(access.sources)) if access is not None else (),
            granted=observation.source_ids,
            denied=access.denied(binding.actor_id) if access is not None else (),
            transforms=MappingProxyType(dict(specs)),
            observation=MappingProxyType(
                {key: sha256_bytes(observation.contents[key]).hex for key in observation.source_ids}
            ),
            renderer=renderer.plugin_identity,
            rendering_sha256=sha256_bytes(canonical_json(rendering.document()).encode()).hex,
            codec=codec.plugin_identity,
            corroboration_grade=grade,
            request_identity=str(request.identity()),
        )
        return BuiltRequestV1(request, trace)
