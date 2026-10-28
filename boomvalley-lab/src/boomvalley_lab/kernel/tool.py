"""P17 Tool Actor contract (T5-003, T5-004).

A tool actor is a plan actor (P04) whose answers come from an external tool,
through a registered ``tool`` plugin, instead of from a provider adapter.  It
is the same organizational participant - same ActorIdentity, same information
rights (P05), same proposal and decision path (P06 / P07) - and what a model
call leaves implicit is declared and typed:

    contract   what the actor's tool does: the tool,    ToolActorContractIdentity
               its effect, its side effect, one
               operation on one resource, the types of
               its arguments and of its result
               (declaration, frozen into the plan as ``semantic-plan-10``)
    intent     the intent to call the tool once, with   ToolReadIntentIdentity
               typed arguments, for one persisted       ToolMutationIntentIdentity
               request-2
    result     what the tool returned for that intent   ToolReadResultIdentity
                                                        ToolMutationResultIdentity

Effect.  A tool either only reads its resource (``READ_ONLY``) or may change
it (``MUTATING``); the contract says which and the registered tool states the
same (BVL-TOOL-002).  The two effects have different intent and result types,
with different schemas and identity kinds, and neither stands for the other
(BVL-TOOL-004):

    READ_ONLY   bvl-tool-read-intent-1      -> bvl-tool-read-result-1
                the result is the typed value the tool observed; it states no
                outcome and no receipt, because a read changes nothing
    MUTATING    bvl-tool-mutation-intent-1  -> bvl-tool-mutation-result-1
                the result states what happened to the resource: APPLIED, with
                the tool's receipt for the change and the typed value, or
                NOT_APPLIED, with neither

A mutation result has no third outcome: a call whose effect is not known has
no result.  What may happen next is decided from the journal of the call and
the contract's declared side effect (T5-004, ``kernel/tool_call.py``):

    NONE               a READ_ONLY tool: calling it changes nothing, so a read
                       whose value was lost is read again
    IDEMPOTENT_BY_KEY  a MUTATING tool that applies the change of one
                       idempotency key at most once and answers, by key,
                       whether it applied it (``reconcile``)
    IRREVERSIBLE       a MUTATING tool whose every call may change the
                       resource again and that cannot be asked what it did

The contract states one of them and the registered tool states the same
(BVL-TOOL-002): what an unknown outcome permits is frozen into the plan, not
chosen when a call fails.

The chain is one way and closed::

    request-2 (RequestIdentity)
        -> tool intent  = step x actor x request x contract x tool
                          x operation x resource x arguments
        -> tool result  = intent x (value | outcome x receipt x value)

so a result names exactly one intent and through it exactly one persisted
request, one operation on one resource and one set of arguments; it cannot be
attached to another request, actor, round or call (BVL-TOOL-006 / -007).

Types.  Arguments and results are closed typed objects in the P06 field
vocabulary (``integer``, ``number``, ``string``, ``boolean``): every declared
field is present with its type and no other key is (BVL-TOOL-005 / -008).  An
intent is built from the persisted request, before anything is called; its
``model_identity`` is the reserved ``TOOL_MODEL`` - a tool profile states that
no model answers - and it carries no generation options.

Arguments.  The arguments of a call are never chosen when it is made.  A
contract that declares an ``argument_selection`` (T5-007, a
``bvl-tool-actor-contract-3``) names, per argument, where its value comes
from: a constant (``{"value": ...}``) or one field of a JSON source the actor
is granted (``{"source": ..., "field": ...}``, P05).  The selection is frozen
into the plan, independent of the actor's renderer, and anyone holding the
actor's observation recomputes the arguments from it
(``select_tool_arguments``).  A contract without a selection stays a
``bvl-tool-actor-contract-2``: it states what the tool is and cannot be
executed (BVL-TOOL-009) - running nothing is better than calling a tool with
undeclared arguments, or approximating it with a model call.

What this module does not do: call a tool.  The journaled call and its
recovery are ``kernel/tool_call.py`` (T5-004); the actor call a tool answers
is ``kernel/tool_actor_call.py`` (T5-007).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

from boomvalley_lab.core.canonical import canonical_bytes, canonical_json
from boomvalley_lab.core.errors import (
    BoomvalleyError,
    CanonicalisationError,
    DeclarationError,
)
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.identity.kinds import RequestIdentity
from boomvalley_lab.kernel.actors import ActorBindingSetV1, ActorBindingV1
from boomvalley_lab.kernel.identity import ActorIdentity, StepIdentity, _KernelIdentity
from boomvalley_lab.kernel.proposals import FIELD_TYPES, _type_ok
from boomvalley_lab.kernel.request import RequestV2

# The P17 tool identities.  Like the human ones (``kernel.human``) they are
# K0-shaped digest identities owned here, not in ``kernel.identity``: that
# module is the identity set T0-GATE froze and re-derives from run evidence,
# and no run can evidence a tool call yet.


@dataclass(frozen=True)
class ToolActorContractIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "tool_actor_contract"
    IDENTIFIES: ClassVar[str] = (
        "what one tool actor's tool does: the tool, its effect, its side effect, the "
        "operation, the resource and the types of its arguments and result"
    )
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("actor", "execution_profile", "tool code")
    SCHEMA: ClassVar[str] = "bvl-tool-actor-contract-identity-1"


@dataclass(frozen=True)
class ToolReadIntentIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "tool_read_intent"
    IDENTIFIES: ClassVar[str] = (
        "the intent to call a read-only tool once: step x actor x request x contract x "
        "arguments"
    )
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "request", "call", "tool_mutation_intent", "tool_read_result",
    )
    SCHEMA: ClassVar[str] = "bvl-tool-read-intent-identity-1"


@dataclass(frozen=True)
class ToolMutationIntentIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "tool_mutation_intent"
    IDENTIFIES: ClassVar[str] = (
        "the intent to call a mutating tool once: step x actor x request x contract x "
        "arguments"
    )
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "request", "call", "tool_read_intent", "tool_mutation_result", "the applied change",
    )
    SCHEMA: ClassVar[str] = "bvl-tool-mutation-intent-identity-1"


@dataclass(frozen=True)
class ToolReadResultIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "tool_read_result"
    IDENTIFIES: ClassVar[str] = "the typed value a read-only tool returned for one read intent"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "proposal", "decision", "tool_mutation_result",
    )
    SCHEMA: ClassVar[str] = "bvl-tool-read-result-identity-1"


@dataclass(frozen=True)
class ToolMutationResultIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "tool_mutation_result"
    IDENTIFIES: ClassVar[str] = (
        "what a mutating tool returned for one mutation intent: the outcome, the tool's "
        "receipt and the typed value"
    )
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = (
        "proposal", "decision", "tool_read_result", "proof the resource changed",
    )
    SCHEMA: ClassVar[str] = "bvl-tool-mutation-result-identity-1"


CONTRACT_SCHEMA = "bvl-tool-actor-contract-2"
#: a contract that declares where its arguments come from (T5-007)
CONTRACT_SCHEMA_V3 = "bvl-tool-actor-contract-3"
CONTRACT_SET_SCHEMA = "bvl-tool-actor-contract-set-1"
READ_INTENT_SCHEMA = "bvl-tool-read-intent-1"
MUTATION_INTENT_SCHEMA = "bvl-tool-mutation-intent-1"
READ_RESULT_SCHEMA = "bvl-tool-read-result-1"
MUTATION_RESULT_SCHEMA = "bvl-tool-mutation-result-1"

#: the model identity of a tool profile: no model answers this actor
TOOL_MODEL = "bvl:tool-actor:1"

# P17 stable reason-code family (tool actors)
TOOL_CONTRACT_INVALID = "BVL-TOOL-001"
TOOL_UNSUPPORTED = "BVL-TOOL-002"
TOOL_PROFILE_MISMATCH = "BVL-TOOL-003"
TOOL_EFFECT_MISMATCH = "BVL-TOOL-004"
TOOL_ARGUMENTS_INVALID = "BVL-TOOL-005"
TOOL_INTENT_MISMATCH = "BVL-TOOL-006"
TOOL_RESULT_IDENTITY_MISMATCH = "BVL-TOOL-007"
TOOL_RESULT_INVALID = "BVL-TOOL-008"
TOOL_EXECUTION_UNSUPPORTED = "BVL-TOOL-009"
# T5-004 (``kernel/tool_call.py``): the journaled call and its recovery
TOOL_OUTCOME_UNKNOWN = "BVL-TOOL-010"
TOOL_CALL_EVIDENCE_MISMATCH = "BVL-TOOL-011"
TOOL_RECONCILIATION_FAILED = "BVL-TOOL-012"

TOOL_CODES = frozenset(
    {
        TOOL_CONTRACT_INVALID,
        TOOL_UNSUPPORTED,
        TOOL_PROFILE_MISMATCH,
        TOOL_EFFECT_MISMATCH,
        TOOL_ARGUMENTS_INVALID,
        TOOL_INTENT_MISMATCH,
        TOOL_RESULT_IDENTITY_MISMATCH,
        TOOL_RESULT_INVALID,
        TOOL_EXECUTION_UNSUPPORTED,
        TOOL_OUTCOME_UNKNOWN,
        TOOL_CALL_EVIDENCE_MISMATCH,
        TOOL_RECONCILIATION_FAILED,
    }
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_PLUGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_RESOURCE = re.compile(r"[a-z][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9_./-]*")
_RECEIPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTITY_KEYS = frozenset({"kind", "digest"})


class ToolError(DeclarationError):
    """A P17 tool refusal carrying one stable ``BVL-TOOL-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in TOOL_CODES:
            raise ValueError(f"unknown tool reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


class ToolEffect(StrEnum):
    READ_ONLY = "READ_ONLY"
    MUTATING = "MUTATING"


class ToolSideEffect(StrEnum):
    """What calling the tool again may do to its resource (T5-004)."""

    NONE = "NONE"
    IDEMPOTENT_BY_KEY = "IDEMPOTENT_BY_KEY"
    IRREVERSIBLE = "IRREVERSIBLE"


class MutationOutcome(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"


def _closed(value: Any, keys: frozenset[str] | set[str], what: str, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ToolError(code, f"{what} is an object with exactly the keys {sorted(keys)}")
    return value


def _enum(kind: type[StrEnum], value: Any, what: str, code: str) -> Any:
    if isinstance(value, kind):
        return value
    if not isinstance(value, str) or value not in {item.value for item in kind}:
        raise ToolError(
            code, f"{what} {value!r} is not one of {sorted(item.value for item in kind)}"
        )
    return kind(value)


def _identity(value: Any, kind: str, what: str, code: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != _IDENTITY_KEYS
        or value["kind"] != kind
        or not isinstance(value["digest"], str)
        or not _SHA256.fullmatch(value["digest"])
    ):
        raise ToolError(code, f"{what} is a {kind!r} identity document")
    return {"kind": kind, "digest": value["digest"]}


def _types(value: Any, what: str, code: str) -> Mapping[str, str]:
    """A closed typed shape: field name -> one P06 field type."""

    if not isinstance(value, Mapping):
        raise ToolError(code, f"{what} is an object of field name -> type")
    for name, kind in value.items():
        if not isinstance(name, str) or not _FIELD.fullmatch(name):
            raise ToolError(code, f"{what} field {name!r} is not a field name")
        if not isinstance(kind, str) or kind not in FIELD_TYPES:
            raise ToolError(
                code, f"{what} field {name!r} type {kind!r} is not one of {sorted(FIELD_TYPES)}"
            )
    return MappingProxyType(dict(sorted(value.items())))


def _typed(value: Any, types: Mapping[str, str], what: str, code: str) -> Mapping[str, Any]:
    """*value* is exactly the declared fields, each of its declared type."""

    if not isinstance(value, Mapping) or set(value) != set(types):
        raise ToolError(
            code,
            f"{what} has exactly the fields {sorted(types)}, not "
            f"{sorted(map(str, value)) if isinstance(value, Mapping) else type(value).__name__}",
        )
    for name, kind in types.items():
        if not _type_ok(kind, value[name]):
            raise ToolError(code, f"{what} field {name!r} is not a {kind}: {value[name]!r}")
    return _frozen(value, what, code)


def _frozen(value: Any, what: str, code: str) -> Mapping[str, Any]:
    """An object of JSON scalars, as canonical data (no NaN, no nesting)."""

    if not isinstance(value, Mapping):
        raise ToolError(code, f"{what} is an object")
    for name, item in value.items():
        if not isinstance(name, str) or not isinstance(item, (str, int, float, bool)):
            raise ToolError(
                code, f"{what} field {name!r} is not a string, integer, number or boolean"
            )
    try:
        return MappingProxyType(json.loads(canonical_json(dict(value))))
    except (CanonicalisationError, TypeError, ValueError) as error:
        raise ToolError(code, f"{what} is not canonical data: {error}") from None


def _selection(
    value: Any, arguments: Mapping[str, str], what: str, code: str
) -> Mapping[str, Mapping[str, Any]]:
    """Where each argument comes from: a constant, or one field of a granted source."""

    if not isinstance(value, Mapping) or set(value) != set(arguments):
        raise ToolError(
            code, f"{what} names the origin of exactly the arguments {sorted(arguments)}"
        )
    origins: dict[str, Mapping[str, Any]] = {}
    for name in sorted(arguments):
        origin = value[name]
        if isinstance(origin, Mapping) and set(origin) == {"value"}:
            if not _type_ok(arguments[name], origin["value"]):
                raise ToolError(
                    code, f"{what} constant of {name!r} is not a {arguments[name]}: "
                    f"{origin['value']!r}"
                )
            origins[name] = _frozen(origin, f"{what} constant of {name!r}", code)
        elif isinstance(origin, Mapping) and set(origin) == {"source", "field"}:
            if not isinstance(origin["source"], str) or not _ID.fullmatch(origin["source"]):
                raise ToolError(code, f"{what} source of {name!r} is an information source id")
            if not isinstance(origin["field"], str) or not _FIELD.fullmatch(origin["field"]):
                raise ToolError(code, f"{what} field of {name!r} is a field name")
            origins[name] = MappingProxyType(
                {"source": origin["source"], "field": origin["field"]}
            )
        else:
            raise ToolError(
                code,
                f"{what} origin of {name!r} is {{'value': constant}} or "
                "{'source': granted source, 'field': field of its JSON object}",
            )
    return MappingProxyType(origins)


# ------------------------------------------------------------------ contract
@dataclass(frozen=True)
class ToolActorContractV1:
    """What one plan actor's tool does, and in which types."""

    actor_id: str
    tool: str  # the tool's registered plugin identity
    effect: ToolEffect
    side_effect: ToolSideEffect  # what an unknown outcome of the call permits
    operation: str
    resource: str  # the external resource the operation reads or changes
    arguments: Mapping[str, str]
    result: Mapping[str, str]
    # where each argument's value comes from (T5-007); None: the contract
    # states the tool and is not executable
    argument_selection: Mapping[str, Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        code = TOOL_CONTRACT_INVALID
        if not isinstance(self.actor_id, str) or not _ID.fullmatch(self.actor_id):
            raise ToolError(code, f"tool actor id {self.actor_id!r} is not an identifier")
        if not isinstance(self.tool, str) or not _PLUGIN.fullmatch(self.tool):
            raise ToolError(
                code, f"tool actor {self.actor_id!r} tool is a registered plugin identity"
            )
        object.__setattr__(self, "effect", _enum(ToolEffect, self.effect, "tool effect", code))
        object.__setattr__(
            self, "side_effect",
            _enum(ToolSideEffect, self.side_effect, "tool side effect", code),
        )
        if (self.effect is ToolEffect.READ_ONLY) != (self.side_effect is ToolSideEffect.NONE):
            raise ToolError(
                code,
                f"tool actor {self.actor_id!r} is {self.effect.value} with the side effect "
                f"{self.side_effect.value}: a READ_ONLY tool has the side effect NONE, a "
                "MUTATING one is IDEMPOTENT_BY_KEY or IRREVERSIBLE",
            )
        if not isinstance(self.operation, str) or not _ID.fullmatch(self.operation):
            raise ToolError(
                code, f"tool actor {self.actor_id!r} operation {self.operation!r} is not an "
                "identifier"
            )
        if not isinstance(self.resource, str) or not _RESOURCE.fullmatch(self.resource):
            raise ToolError(
                code,
                f"tool actor {self.actor_id!r} names the resource its tool "
                f"{'changes' if self.effect is ToolEffect.MUTATING else 'reads'} as "
                f"'<kind>:<name>', not {self.resource!r}",
            )
        object.__setattr__(
            self, "arguments", _types(self.arguments, f"{self.actor_id!r} arguments", code)
        )
        object.__setattr__(self, "result", _types(self.result, f"{self.actor_id!r} result", code))
        if self.effect is ToolEffect.READ_ONLY and not self.result:
            raise ToolError(
                code, f"read-only tool actor {self.actor_id!r} declares the value it reads: "
                "its result has at least one field"
            )
        if self.argument_selection is not None:
            object.__setattr__(
                self, "argument_selection",
                _selection(
                    self.argument_selection, self.arguments,
                    f"{self.actor_id!r} argument_selection", code,
                ),
            )

    @property
    def executable(self) -> bool:
        """The origin of every argument is declared: the engine can call this tool."""

        return self.argument_selection is not None

    def selected_sources(self) -> tuple[str, ...]:
        """The information sources the argument selection reads."""

        return tuple(sorted({
            origin["source"] for origin in (self.argument_selection or {}).values()
            if "source" in origin
        }))

    def document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": CONTRACT_SCHEMA,
            "actor_id": self.actor_id,
            "tool": self.tool,
            "effect": self.effect.value,
            "side_effect": self.side_effect.value,
            "operation": self.operation,
            "resource": self.resource,
            "arguments": dict(self.arguments),
            "result": dict(self.result),
        }
        if self.argument_selection is not None:
            document["schema"] = CONTRACT_SCHEMA_V3
            document["argument_selection"] = {
                name: dict(origin) for name, origin in self.argument_selection.items()
            }
        return document

    def identity(self) -> ToolActorContractIdentity:
        return ToolActorContractIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> ToolActorContractV1:
        """Read one ``bvl-tool-actor-contract-2`` or ``-3`` back (closed shape).

        A contract-3 is a contract-2 with its ``argument_selection``.
        """

        keys = {
            "schema", "actor_id", "tool", "effect", "side_effect", "operation", "resource",
            "arguments", "result",
        }
        schema = CONTRACT_SCHEMA
        if isinstance(document, Mapping) and document.get("schema") == CONTRACT_SCHEMA_V3:
            keys, schema = keys | {"argument_selection"}, CONTRACT_SCHEMA_V3
        document = _closed(document, keys, "tool actor contract", TOOL_CONTRACT_INVALID)
        if document["schema"] != schema:
            raise ToolError(
                TOOL_CONTRACT_INVALID,
                f"tool actor contract is {CONTRACT_SCHEMA} or {CONTRACT_SCHEMA_V3}",
            )
        return cls(**{key: document[key] for key in keys - {"schema"}})

    def require_binding(self, binding: ActorBindingV1) -> None:
        """The actor's frozen profile is a tool profile on this tool (BVL-TOOL-003)."""

        profile = binding.profile
        if binding.actor_id != self.actor_id:
            raise ToolError(
                TOOL_PROFILE_MISMATCH,
                f"the contract of {self.actor_id!r} is held to actor {binding.actor_id!r}",
            )
        if profile.model != TOOL_MODEL:
            raise ToolError(
                TOOL_PROFILE_MISMATCH,
                f"tool actor {self.actor_id!r} is bound to model {profile.model!r}; a tool "
                f"profile states the model {TOOL_MODEL!r}",
            )
        if profile.provider != self.tool:
            raise ToolError(
                TOOL_PROFILE_MISMATCH,
                f"tool actor {self.actor_id!r} is contracted on tool {self.tool!r}; its "
                f"profile names {profile.provider!r}",
            )
        if profile.options:
            raise ToolError(
                TOOL_PROFILE_MISMATCH,
                f"tool actor {self.actor_id!r} profile carries generation options "
                f"{sorted(profile.options)}; a tool has none",
            )

    def require_tool(self, tool: object) -> None:
        """The registered tool is the contracted one (BVL-TOOL-002).

        A tool states its effect (``EFFECT``), its side effect
        (``SIDE_EFFECT``) and, per operation, the types of its arguments and
        result (``OPERATIONS``).  The contract restates them, so the plan
        freezes what the tool is held to: a tool that may change its resource
        is never contracted as read-only, a tool that cannot be asked what it
        did is never contracted as idempotent, and a typed field the tool
        does not have is never declared.
        """

        try:
            effect = ToolEffect(getattr(tool, "EFFECT", None))
            side_effect = ToolSideEffect(getattr(tool, "SIDE_EFFECT", None))
            operations = {
                name: (
                    _types(shape["arguments"], "arguments", TOOL_UNSUPPORTED),
                    _types(shape["result"], "result", TOOL_UNSUPPORTED),
                )
                for name, shape in dict(getattr(tool, "OPERATIONS", None)).items()
            }
        except (TypeError, ValueError, KeyError, ToolError):
            raise ToolError(
                TOOL_UNSUPPORTED,
                f"tool {self.tool!r} does not state its EFFECT, its SIDE_EFFECT and typed "
                "OPERATIONS",
            ) from None
        if effect is not self.effect:
            raise ToolError(
                TOOL_UNSUPPORTED,
                f"tool {self.tool!r} is {effect.value}; actor {self.actor_id!r} contracts it "
                f"as {self.effect.value}",
            )
        if side_effect is not self.side_effect:
            raise ToolError(
                TOOL_UNSUPPORTED,
                f"tool {self.tool!r} has the side effect {side_effect.value}; actor "
                f"{self.actor_id!r} contracts it as {self.side_effect.value}",
            )
        if side_effect is ToolSideEffect.IDEMPOTENT_BY_KEY and not callable(
            getattr(tool, "reconcile", None)
        ):
            raise ToolError(
                TOOL_UNSUPPORTED,
                f"tool {self.tool!r} states IDEMPOTENT_BY_KEY and cannot be asked, by key, "
                "whether it applied a change (it has no reconcile)",
            )
        if self.operation not in operations:
            raise ToolError(
                TOOL_UNSUPPORTED,
                f"tool {self.tool!r} has the operations {sorted(operations)}; actor "
                f"{self.actor_id!r} contracts {self.operation!r}",
            )
        arguments, result = operations[self.operation]
        for name, declared, stated in (
            ("arguments", self.arguments, arguments),
            ("result", self.result, result),
        ):
            if dict(declared) != dict(stated):
                raise ToolError(
                    TOOL_UNSUPPORTED,
                    f"tool {self.tool!r} operation {self.operation!r} has the {name} "
                    f"{dict(stated)}; actor {self.actor_id!r} declares {dict(declared)}",
                )


@dataclass(frozen=True)
class ToolActorContractSetV1:
    """The tool actors of one plan; this is what enters the plan (plan-10)."""

    contracts: Mapping[str, ToolActorContractV1] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.contracts:
            raise ToolError(
                TOOL_CONTRACT_INVALID, "a tool contract set declares at least one tool actor"
            )
        for actor_id, contract in self.contracts.items():
            if not isinstance(contract, ToolActorContractV1) or contract.actor_id != actor_id:
                raise ToolError(
                    TOOL_CONTRACT_INVALID, f"tool contract {actor_id!r} names another actor"
                )
        object.__setattr__(self, "contracts", MappingProxyType(dict(self.contracts)))

    def __contains__(self, actor_id: object) -> bool:
        return actor_id in self.contracts

    @classmethod
    def of(cls, contracts: Any) -> ToolActorContractSetV1:
        unique: dict[str, ToolActorContractV1] = {}
        for contract in contracts:
            if contract.actor_id in unique:
                raise ToolError(
                    TOOL_CONTRACT_INVALID, f"tool actor {contract.actor_id!r} is contracted twice"
                )
            unique[contract.actor_id] = contract
        return cls(unique)

    def contract(self, actor_id: str) -> ToolActorContractV1:
        contract = self.contracts.get(actor_id) if isinstance(actor_id, str) else None
        if contract is None:
            raise ToolError(
                TOOL_PROFILE_MISMATCH, f"actor {actor_id!r} is not a tool actor of the plan"
            )
        return contract

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SET_SCHEMA,
            "actors": [self.contracts[key].document() for key in sorted(self.contracts)],
        }

    @classmethod
    def from_document(cls, document: Any) -> ToolActorContractSetV1:
        document = _closed(
            document, {"schema", "actors"}, "tool contract set", TOOL_CONTRACT_INVALID
        )
        if document["schema"] != CONTRACT_SET_SCHEMA or not isinstance(document["actors"], list):
            raise ToolError(TOOL_CONTRACT_INVALID, f"tool contract set is {CONTRACT_SET_SCHEMA}")
        parsed = cls.of(ToolActorContractV1.from_document(item) for item in document["actors"])
        if parsed.document() != document:
            raise ToolError(TOOL_CONTRACT_INVALID, "tool contract set is not canonical")
        return parsed

    def require_actors(self, actors: ActorBindingSetV1 | None) -> None:
        """Exactly the contracted actors are tools, before anything runs (BVL-TOOL-003).

        Every contract names a plan actor on a tool profile, and no other
        actor claims the tool model: a tool is never called without a
        declared effect and declared types.
        """

        if actors is None:
            raise ToolError(
                TOOL_PROFILE_MISMATCH, "tool contracts are held to the actors of a P04 plan"
            )
        for actor_id in sorted(self.contracts):
            if actor_id not in actors:
                raise ToolError(
                    TOOL_PROFILE_MISMATCH,
                    f"tool actor {actor_id!r} is not an actor of the frozen plan",
                )
            self.contracts[actor_id].require_binding(actors.binding(actor_id))
        require_no_uncontracted_tool(actors, self)

    def unexecutable(self) -> tuple[str, ...]:
        """The tool actors whose arguments have no declared origin."""

        return tuple(
            actor_id for actor_id in sorted(self.contracts)
            if not self.contracts[actor_id].executable
        )

    def require_granted(self, granted: Callable[[str], Any] | None) -> None:
        """Every selected source is one its actor is granted (BVL-TOOL-001).

        *granted* maps an actor to the sources its P05 access grants in this
        plan; None when the plan declares no information.  An argument is
        never read from a source the actor may not observe.
        """

        for actor_id in sorted(self.contracts):
            wanted = self.contracts[actor_id].selected_sources()
            held = () if granted is None else tuple(granted(actor_id))
            missing = sorted(set(wanted) - set(held))
            if missing:
                raise ToolError(
                    TOOL_CONTRACT_INVALID,
                    f"tool actor {actor_id!r} selects arguments from {missing}, which its "
                    "information access does not grant it",
                )


def require_no_uncontracted_tool(
    actors: ActorBindingSetV1 | None, tools: ToolActorContractSetV1 | None
) -> None:
    """No actor states the tool model without a contract (BVL-TOOL-003)."""

    for actor_id, binding in sorted((actors.bindings if actors is not None else {}).items()):
        if binding.profile.model == TOOL_MODEL and (tools is None or actor_id not in tools):
            raise ToolError(
                TOOL_PROFILE_MISMATCH,
                f"actor {actor_id!r} states the tool model {TOOL_MODEL!r} and has no tool "
                "actor contract: its effect and the types of its arguments and result are "
                "undeclared",
            )


# ------------------------------------------------------------------- intent
_INTENT_KEYS = frozenset(
    {"schema", "step", "actor", "request", "contract", "tool", "operation", "resource",
     "arguments"}
)


@dataclass(frozen=True)
class _ToolIntent:
    """The intent to call one tool once, with typed arguments, for one request-2."""

    step: Mapping[str, str]
    actor: Mapping[str, str]
    request: Mapping[str, str]
    contract: Mapping[str, str]
    tool: str
    operation: str
    resource: str
    arguments: Mapping[str, Any]

    SCHEMA: ClassVar[str]
    EFFECT: ClassVar[ToolEffect]
    IDENTITY: ClassVar[type[_KernelIdentity]]

    def __post_init__(self) -> None:
        code = TOOL_INTENT_MISMATCH
        for name, kind in (
            ("step", StepIdentity.KIND),
            ("actor", ActorIdentity.KIND),
            ("request", RequestIdentity.KIND),
            ("contract", ToolActorContractIdentity.KIND),
        ):
            object.__setattr__(
                self, name, _identity(getattr(self, name), kind, f"intent {name}", code)
            )
        if not isinstance(self.tool, str) or not _PLUGIN.fullmatch(self.tool):
            raise ToolError(code, "intent tool is a plugin identity")
        if not isinstance(self.operation, str) or not _ID.fullmatch(self.operation):
            raise ToolError(code, "intent operation is an identifier")
        if not isinstance(self.resource, str) or not _RESOURCE.fullmatch(self.resource):
            raise ToolError(code, "intent resource is a '<kind>:<name>' resource")
        object.__setattr__(
            self,
            "arguments",
            _frozen(self.arguments, "intent arguments", TOOL_ARGUMENTS_INVALID),
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "step": dict(self.step),
            "actor": dict(self.actor),
            "request": dict(self.request),
            "contract": dict(self.contract),
            "tool": self.tool,
            "operation": self.operation,
            "resource": self.resource,
            "arguments": dict(self.arguments),
        }

    def identity(self) -> _KernelIdentity:
        return self.IDENTITY.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> Any:
        _require_effect_schema(document, cls.SCHEMA, _INTENT_SCHEMAS, "tool intent")
        document = _closed(document, _INTENT_KEYS, "tool intent", TOOL_INTENT_MISMATCH)
        if document["schema"] != cls.SCHEMA:
            raise ToolError(TOOL_INTENT_MISMATCH, f"tool intent is {cls.SCHEMA}")
        return cls(**{key: document[key] for key in _INTENT_KEYS - {"schema"}})

    @classmethod
    def of(
        cls,
        contract: ToolActorContractV1,
        binding: ActorBindingV1,
        *,
        step: StepIdentity,
        request: RequestV2,
        arguments: Mapping[str, Any],
    ) -> Any:
        """Build this intent for one persisted request, or refuse before any call.

        The contract has this intent's effect (BVL-TOOL-004).  The request is
        the actor's own request-2: the tool model, the profile's renderer, no
        options (BVL-TOOL-006).  The arguments are exactly the contract's
        fields in their declared types (BVL-TOOL-005).
        """

        if contract.effect is not cls.EFFECT:
            raise ToolError(
                TOOL_EFFECT_MISMATCH,
                f"tool actor {contract.actor_id!r} is contracted {contract.effect.value}; a "
                f"{cls.SCHEMA} is the intent of a {cls.EFFECT.value} tool",
            )
        contract.require_binding(binding)
        if not isinstance(request, RequestV2) or request.model_identity != TOOL_MODEL:
            raise ToolError(
                TOOL_INTENT_MISMATCH,
                f"the request of tool actor {contract.actor_id!r} states the model "
                f"{getattr(request, 'model_identity', None)!r}, not {TOOL_MODEL!r}",
            )
        if request.renderer_identity != binding.profile.renderer or dict(request.options):
            raise ToolError(
                TOOL_INTENT_MISMATCH,
                f"the request of tool actor {contract.actor_id!r} is not rendered under its "
                "profile (renderer and no options)",
            )
        return cls(
            step=step.document(),
            actor=binding.identity.document(),
            request=request.identity().document(),
            contract=contract.identity().document(),
            tool=contract.tool,
            operation=contract.operation,
            resource=contract.resource,
            arguments=_typed(
                arguments, contract.arguments,
                f"the arguments of {contract.operation!r}", TOOL_ARGUMENTS_INVALID,
            ),
        )


@dataclass(frozen=True)
class ToolReadIntentV1(_ToolIntent):
    """The intent to read: calling it changes nothing outside the product."""

    SCHEMA: ClassVar[str] = READ_INTENT_SCHEMA
    EFFECT: ClassVar[ToolEffect] = ToolEffect.READ_ONLY
    IDENTITY: ClassVar[type[_KernelIdentity]] = ToolReadIntentIdentity


@dataclass(frozen=True)
class ToolMutationIntentV1(_ToolIntent):
    """The intent to change the contract's resource once."""

    SCHEMA: ClassVar[str] = MUTATION_INTENT_SCHEMA
    EFFECT: ClassVar[ToolEffect] = ToolEffect.MUTATING
    IDENTITY: ClassVar[type[_KernelIdentity]] = ToolMutationIntentIdentity


_INTENT_SCHEMAS = frozenset({READ_INTENT_SCHEMA, MUTATION_INTENT_SCHEMA})
_RESULT_SCHEMAS = frozenset({READ_RESULT_SCHEMA, MUTATION_RESULT_SCHEMA})
INTENT_TYPES: Mapping[ToolEffect, type[_ToolIntent]] = MappingProxyType(
    {ToolEffect.READ_ONLY: ToolReadIntentV1, ToolEffect.MUTATING: ToolMutationIntentV1}
)


def _require_effect_schema(
    document: Any, schema: str, family: frozenset[str], what: str
) -> None:
    """A document of the other effect's type is not this one (BVL-TOOL-004)."""

    stated = document.get("schema") if isinstance(document, Mapping) else None
    if isinstance(stated, str) and stated != schema and stated in family:
        raise ToolError(
            TOOL_EFFECT_MISMATCH,
            f"the {what} is a {stated}; a {schema} is expected: a read and a mutation "
            "never stand for each other",
        )


def tool_intent(
    contract: ToolActorContractV1,
    binding: ActorBindingV1,
    *,
    step: StepIdentity,
    request: RequestV2,
    arguments: Mapping[str, Any],
) -> ToolReadIntentV1 | ToolMutationIntentV1:
    """The intent of the contract's effect for one persisted request."""

    return INTENT_TYPES[contract.effect].of(
        contract, binding, step=step, request=request, arguments=arguments
    )


# ------------------------------------------------------------------- result
@dataclass(frozen=True)
class ToolReadResultV1:
    """The typed value a read-only tool returned for one read intent.

    It has no outcome and no receipt: a read states no side effect.
    """

    intent: Mapping[str, str]
    value: Mapping[str, Any]

    SCHEMA: ClassVar[str] = READ_RESULT_SCHEMA
    EFFECT: ClassVar[ToolEffect] = ToolEffect.READ_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "intent",
            _identity(
                self.intent, ToolReadIntentIdentity.KIND, "result intent",
                TOOL_RESULT_IDENTITY_MISMATCH,
            ),
        )
        object.__setattr__(
            self, "value", _frozen(self.value, "read result value", TOOL_RESULT_INVALID)
        )

    def document(self) -> dict[str, Any]:
        return {"schema": self.SCHEMA, "intent": dict(self.intent), "value": dict(self.value)}

    def identity(self) -> ToolReadResultIdentity:
        return ToolReadResultIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> ToolReadResultV1:
        _require_effect_schema(document, cls.SCHEMA, _RESULT_SCHEMAS, "tool result")
        document = _closed(
            document, {"schema", "intent", "value"}, "tool read result",
            TOOL_RESULT_IDENTITY_MISMATCH,
        )
        if document["schema"] != cls.SCHEMA:
            raise ToolError(TOOL_RESULT_IDENTITY_MISMATCH, f"tool read result is {cls.SCHEMA}")
        return cls(document["intent"], document["value"])

    def require(self, contract: ToolActorContractV1) -> None:
        """The value is the contract's result type (BVL-TOOL-008)."""

        _typed(self.value, contract.result, "the read result value", TOOL_RESULT_INVALID)


@dataclass(frozen=True)
class ToolMutationResultV1:
    """What a mutating tool returned for one mutation intent.

    APPLIED names the tool's receipt for the change and carries the typed
    value; NOT_APPLIED - the tool declined and changed nothing - carries
    neither.  It is the tool's statement, not proof the resource changed.
    """

    intent: Mapping[str, str]
    outcome: MutationOutcome
    receipt: str | None = None
    value: Mapping[str, Any] | None = None

    SCHEMA: ClassVar[str] = MUTATION_RESULT_SCHEMA
    EFFECT: ClassVar[ToolEffect] = ToolEffect.MUTATING

    def __post_init__(self) -> None:
        code = TOOL_RESULT_INVALID
        object.__setattr__(
            self,
            "intent",
            _identity(
                self.intent, ToolMutationIntentIdentity.KIND, "result intent",
                TOOL_RESULT_IDENTITY_MISMATCH,
            ),
        )
        object.__setattr__(
            self, "outcome", _enum(MutationOutcome, self.outcome, "mutation outcome", code)
        )
        applied = self.outcome is MutationOutcome.APPLIED
        if applied != (self.receipt is not None) or applied != (self.value is not None):
            raise ToolError(
                code,
                "an APPLIED mutation names the tool's receipt and carries its value; a "
                "NOT_APPLIED one has neither",
            )
        if applied:
            if not isinstance(self.receipt, str) or not _RECEIPT.fullmatch(self.receipt):
                raise ToolError(
                    code, "a mutation receipt is the tool's token for the applied change "
                    "(1..128 of letters, digits and '_.:/-')"
                )
            object.__setattr__(
                self, "value", _frozen(self.value, "mutation result value", code)
            )

    def document(self) -> dict[str, Any]:
        # canonical evidence has no null: a NOT_APPLIED result has no receipt
        # and no value member, so the document reads back as it was persisted
        document: dict[str, Any] = {
            "schema": self.SCHEMA,
            "intent": dict(self.intent),
            "outcome": self.outcome.value,
        }
        if self.receipt is not None:
            document["receipt"] = self.receipt
        if self.value is not None:
            document["value"] = dict(self.value)
        return document

    def identity(self) -> ToolMutationResultIdentity:
        return ToolMutationResultIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> ToolMutationResultV1:
        _require_effect_schema(document, cls.SCHEMA, _RESULT_SCHEMAS, "tool result")
        required = {"schema", "intent", "outcome"}
        if not isinstance(document, Mapping) or not (
            required <= set(document) <= required | {"receipt", "value"}
        ):
            raise ToolError(
                TOOL_RESULT_IDENTITY_MISMATCH,
                f"tool mutation result is an object with the keys {sorted(required)} and, "
                "when APPLIED, 'receipt' and 'value'",
            )
        if document["schema"] != cls.SCHEMA:
            raise ToolError(
                TOOL_RESULT_IDENTITY_MISMATCH, f"tool mutation result is {cls.SCHEMA}"
            )
        return cls(
            document["intent"], document["outcome"], document.get("receipt"),
            document.get("value"),
        )

    def require(self, contract: ToolActorContractV1) -> None:
        """An applied value is the contract's result type (BVL-TOOL-008)."""

        if self.value is not None:
            _typed(self.value, contract.result, "the mutation result value", TOOL_RESULT_INVALID)


RESULT_TYPES: Mapping[ToolEffect, type[ToolReadResultV1] | type[ToolMutationResultV1]] = (
    MappingProxyType(
        {ToolEffect.READ_ONLY: ToolReadResultV1, ToolEffect.MUTATING: ToolMutationResultV1}
    )
)


def _require_intent_effect(
    contract: ToolActorContractV1, intent: object, effect: ToolEffect, what: str
) -> None:
    if contract.effect is not effect or not isinstance(intent, INTENT_TYPES[effect]):
        raise ToolError(
            TOOL_EFFECT_MISMATCH,
            f"a {what} answers the {INTENT_TYPES[effect].SCHEMA} of a {effect.value} tool; "
            f"actor {contract.actor_id!r} is contracted {contract.effect.value} and the "
            f"intent is a {getattr(intent, 'SCHEMA', type(intent).__name__)}",
        )


def tool_read_result(
    contract: ToolActorContractV1, intent: ToolReadIntentV1, value: Mapping[str, Any]
) -> ToolReadResultV1:
    """Identify the value a read-only tool returned for *intent*."""

    _require_intent_effect(contract, intent, ToolEffect.READ_ONLY, READ_RESULT_SCHEMA)
    result = ToolReadResultV1(intent.identity().document(), value)
    result.require(contract)
    return result


def tool_mutation_result(
    contract: ToolActorContractV1,
    intent: ToolMutationIntentV1,
    outcome: MutationOutcome,
    *,
    receipt: str | None = None,
    value: Mapping[str, Any] | None = None,
) -> ToolMutationResultV1:
    """Identify what a mutating tool returned for *intent*."""

    _require_intent_effect(contract, intent, ToolEffect.MUTATING, MUTATION_RESULT_SCHEMA)
    result = ToolMutationResultV1(intent.identity().document(), outcome, receipt, value)
    result.require(contract)
    return result


def require_tool_intent(
    contract: ToolActorContractV1,
    binding: ActorBindingV1,
    intent: Any,
    *,
    step: StepIdentity,
    request: RequestIdentity | None = None,
) -> None:
    """*intent* is this step's and this actor's, under this contract, typed.

    Given *request*, it is also that persisted request's (BVL-TOOL-006); the
    arguments are the contract's fields in their declared types (BVL-TOOL-005).
    """

    if not isinstance(intent, INTENT_TYPES[contract.effect]):
        raise ToolError(
            TOOL_EFFECT_MISMATCH,
            f"actor {contract.actor_id!r} is contracted {contract.effect.value}; its intent "
            f"is a {INTENT_TYPES[contract.effect].SCHEMA}, not a "
            f"{getattr(intent, 'SCHEMA', type(intent).__name__)}",
        )
    expected = {
        "step": step.document(),
        "actor": binding.identity.document(),
        "contract": contract.identity().document(),
        "tool": contract.tool,
        "operation": contract.operation,
        "resource": contract.resource,
    }
    if request is not None:
        expected["request"] = request.document()
    for name, value in expected.items():
        held = getattr(intent, name)
        if (dict(held) if isinstance(held, Mapping) else held) != value:
            raise ToolError(
                TOOL_INTENT_MISMATCH, f"the intent's {name} is not the {name} of this exchange"
            )
    _typed(
        intent.arguments, contract.arguments, f"the arguments of {contract.operation!r}",
        TOOL_ARGUMENTS_INVALID,
    )


def verify_tool_exchange(
    contract: ToolActorContractV1,
    binding: ActorBindingV1,
    *,
    step: StepIdentity,
    request: RequestIdentity,
    tool: object,
    intent: Any,
    result: Any,
) -> dict[str, Any]:
    """Re-derive one tool exchange from its documents, or refuse it.

    *intent* and *result* are the persisted documents; *request* and *step*
    the identities the evidence already holds for this actor call; *tool* the
    registered tool.  Nothing is trusted because it is stated: the documents
    are read as the types of the contract's effect, and every reference is
    recomputed from the document it names.
    """

    contract.require_binding(binding)
    contract.require_tool(tool)
    called = INTENT_TYPES[contract.effect].from_document(intent)
    returned = RESULT_TYPES[contract.effect].from_document(result)

    # the intent is this step's, this actor's, this request's, under this contract
    require_tool_intent(contract, binding, called, step=step, request=request)

    # the result is this intent's, in the contract's result type
    if dict(returned.intent) != called.identity().document():
        raise ToolError(TOOL_RESULT_IDENTITY_MISMATCH, "the result answers another intent")
    returned.require(contract)
    summary = {
        "actor": contract.actor_id,
        "tool": contract.tool,
        "effect": contract.effect.value,
        "operation": contract.operation,
        "resource": contract.resource,
        "contract": contract.identity().document(),
        "request": request.document(),
        "intent": called.identity().document(),
        "result": returned.identity().document(),
    }
    if isinstance(returned, ToolMutationResultV1):
        summary["outcome"] = returned.outcome.value
        summary["receipt"] = returned.receipt
    return summary


def select_tool_arguments(
    contract: ToolActorContractV1, observe: Callable[[str], bytes]
) -> dict[str, Any]:
    """The arguments of one call, from the contract's declared selection.

    *observe* returns the bytes the actor observes of one granted source (its
    P05 observation: after access and transform).  A selected source is a JSON
    object and the selected field one of its members; whether the value has
    the argument's declared type is the intent's check (BVL-TOOL-005).
    """

    if contract.argument_selection is None:
        raise execution_unsupported([contract.actor_id])
    observed: dict[str, Any] = {}
    arguments: dict[str, Any] = {}
    for name, origin in contract.argument_selection.items():
        if "value" in origin:
            arguments[name] = origin["value"]
            continue
        source = origin["source"]
        if source not in observed:
            try:
                observed[source] = load_bytes(observe(source))
            except (MalformedJSON, BoomvalleyError, ValueError) as error:
                raise ToolError(
                    TOOL_ARGUMENTS_INVALID,
                    f"tool actor {contract.actor_id!r} selects {name!r} from source "
                    f"{source!r}, which it does not observe as JSON: {error}",
                ) from None
        held = observed[source]
        if not isinstance(held, Mapping) or origin["field"] not in held:
            raise ToolError(
                TOOL_ARGUMENTS_INVALID,
                f"tool actor {contract.actor_id!r} selects {name!r} from field "
                f"{origin['field']!r} of source {source!r}, which has no such field",
            )
        arguments[name] = held[origin["field"]]
    return arguments


def tool_response_content(result: ToolReadResultV1 | ToolMutationResultV1) -> bytes:
    """The response bytes of the actor call *result* answers (T5-007).

    The canonical JSON of the typed value the tool returned; a mutation the
    tool declined carries no value and is stated as that.  What the bytes mean
    for the actor's proposal is its parser contract's (P06), as for any call.
    """

    if result.value is None:
        return canonical_bytes({"outcome": MutationOutcome.NOT_APPLIED.value})
    return canonical_bytes(dict(result.value))


def tool_response_provenance(contract: ToolActorContractV1) -> str:
    """What a tool actor's call states as its adapter provenance."""

    return f"{contract.tool}:{contract.operation}:{contract.effect.value}"


def execution_unsupported(actors: Any) -> ToolError:
    """The refusal of a run whose tool actors cannot be called (BVL-TOOL-009)."""

    return ToolError(
        TOOL_EXECUTION_UNSUPPORTED,
        f"the plan calls tool actors {sorted(actors)} without an engine-owned way to call "
        "them (a declared argument_selection and a bound tool): arguments are never chosen "
        "at call time and a tool is never approximated by a model call: nothing is opened, "
        "nothing is called",
    )
