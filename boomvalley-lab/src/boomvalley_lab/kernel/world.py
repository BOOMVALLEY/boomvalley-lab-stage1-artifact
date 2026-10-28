"""Pure World contracts: the transition result and the P15 state contract.

A World does not own actor orchestration.  It receives one explicit state and
one authoritative requested action and returns an explicit transition result.
Domain inadmissibility is data unless the World contract itself is violated.

The state contract (T3-001, P15 §13.3) makes World state explicit and
versioned.  A World plugin declares one ``WorldStateSchemaV1`` (schema id,
version, typed fields); the plan freezes the resolved ``WorldContractV1``
(``semantic-plan-8``), and under it every state the kernel names - the initial
state of an episode, the pre-state a transition is intended on and the
post-state it commits - is one state *of that schema version*:

    WorldStateIdentity.of_versioned(state_schema="id:version", state=...)
    world_state evidence-2  {schema, identity, state_schema, state}

A plan without a World contract keeps the K0 meaning (a bare state payload,
identity-1, evidence-1); nothing relabels one as the other.

Domain admissibility (T3-003, P15 §13.1) is the World's verdict and is data.
The contract (``bvl-world-contract-2``) also freezes the World's
``WorldActionSchemaV1`` and the closed vocabulary ``bvl-world-admissibility-1``
under which a transition states three actions, none derived from another:

    requested_action   the Decision Artifact's action, exactly as handed
    admissible_action  what the domain admits of it
    executed_action    what the World executed; ``{}`` when nothing was

    ADMISSIBLE    the admissible action is the requested action
    CLIPPED       the admissible action is another action of the schema
    INADMISSIBLE  nothing is admissible and nothing was executed

The executed action is the World's own statement: under ADMISSIBLE or CLIPPED
it is ``{}`` or any action of the schema, never assumed to be the admissible
one.  ``admissibility_problems`` is the one rule the engine applies before a
transition is committed and both verifiers recompute.

    BVL-WORLD-001  WORLD_NOT_REGISTERED     no registered World carries the contract
    BVL-WORLD-002  WORLD_IDENTITY_MISMATCH  the registered World is not the declared one
    BVL-WORLD-003  INITIAL_STATE_INVALID    the initial state is not a state of the schema
                                            or, where the World states one, of its
                                            state domain (SV-11)
    BVL-WORLD-004  ACTION_SCHEMA_INVALID    the requested action is not an action of the
                                            contract's action schema (T3-003)
    BVL-WORLD-005  TRANSITION_INTENT_MISSING  an apply no durable intent precedes (T3-002)
    BVL-WORLD-006  TRANSITION_FAILED        the World did not transition the action it was
                                            handed (T3-002), or stated an admissibility
                                            the contract does not admit (T3-003)
    BVL-WORLD-007  POST_STATE_INVALID       a transition left the declared state schema
    BVL-WORLD-008  NO_ACTION_UNDECLARED     a NO_ACTION decision reached a World whose
                                            contract declares no NO_ACTION meaning (T3-004)

NO_ACTION and exogenous events (T3-004, P15 §13.4-13.5) are frozen in the
contract (since ``bvl-world-contract-3``) as its ``WorldProgressionV1``
(``bvl-world-progression-1``): what a NO_ACTION decision means to this World,
and the kinds of exogenous event it may state.

    UNDECLARED             NO_ACTION is not an input of this World (BVL-WORLD-008)
    NO_TRANSITION          nothing is executed, no event occurs, the state is kept
    EXOGENOUS_PROGRESSION  nothing is executed; the environment may progress,
                           only through stated exogenous events
    NULL_ACTION            the World executes the contract's declared null action

A NO_ACTION decision is never the empty action: the intent and the transition
state ``action_input: NO_ACTION`` (the World is handed ``None``) and the
transition's verdict is ``NO_ACTION``.  A contracted transition
(``bvl-world-transition-2``) also states ``executed`` - whether the World
executed an action, which ``executed_action == {}`` cannot say under an open
field-less action schema - and its ``exogenous_events``, each of a kind the
contract declares.  One rule closes hidden mutation: a post-state that is not
the pre-state is stated to follow from an executed action or from at least one
exogenous event.  ``progression_problems`` is that rule; the engine applies it
before a transition is committed and both verifiers recompute it.

Regime change (T4-004, P16 13.5).  A World whose environment has regimes
declares them in the same progression (``bvl-world-progression-2``): the
``regime_events`` - the exogenous event kinds that are a regime change - and
the ``regime_fields`` - the state fields that are the regime.  A transition
that moves a regime field states a regime event - also when an executed action
caused it: the action is then in evidence as every action is, and the event
says that the regime changed.  Anything else is a hidden regime change.  A
World declaring no regime keeps ``bvl-world-progression-1`` and its bytes.

State serialization and replay (T3-005, P15 §3, §13.3).  A contracted state
has one serialization, ``bvl-canonical-json-1``: ``serialize_state`` gives its
bytes and ``deserialize_state`` the one object those bytes decode to.  A value
the serialization would drop (a null) is not a state of any schema, so a state
always survives its own serialization.  The World is only ever handed a
deserialized state, and only the deserialized committed post-state reaches the
next step: what a World does is a function of serialized state by construction.

A contracted World is a deterministic function of its bound inputs - the
serialized pre-state, the handed input and the seed (``bvl-world-replay-1``).
An independent instance replaying the same serialized inputs states the same
transition, byte for byte; ``replay_problems`` is that comparison.  The engine
applies it before a transition is committed, and ``kernel/world_replay.py``
recomputes every committed transition from a package's evidence alone.

    BVL-WORLD-009  HIDDEN_WORLD_STATE       a transition an independent instance does
                                            not reproduce from the serialized inputs

Stochastic Worlds and seed binding (T3-006, P15 §3, K0 §6).  The contract
(``bvl-world-contract-4``) freezes the World's ``WorldRngPolicyV1``
(``bvl-world-rng-1``): whether a transition may be random at all, and through
which generator.

    DETERMINISTIC  a transition is a function of the serialized pre-state and the
                   handed input alone; the bound seed does not change it
    SEEDED         a transition may also draw from the declared RNG: the one
                   ``bvl-rng-sha256-ctr-1`` stream of the transition's bound
                   K0 world seed (``kernel/world_rng.py``)

A SEEDED World's entry point is ``apply(state, action, *, rng)``: it is handed
the declared RNG and never the seed, so no generator of its own can be keyed by
it.  A DETERMINISTIC World keeps ``apply(state, action, *, seed)`` and is
replayed under another seed.  Every other source of randomness is hidden plugin
RNG, and a transition that reaches one commits nothing.

    BVL-WORLD-013  RNG_POLICY_INVALID       randomness the contract's RNG policy does
                                            not declare: a World whose entry point is
                                            not its policy's, a DETERMINISTIC transition
                                            its seed changes, or a transition that
                                            reached hidden plugin RNG (the process
                                            ``random`` generator, an unseeded generator,
                                            OS entropy)

(P15 §8 numbers RNG_POLICY_INVALID 008; T3-004 took 008 for NO_ACTION_UNDECLARED
and 010 stays reserved for its P15 meaning.)

Crash, resume and custody (T3-007, P15 §6.9, ``kernel/world_executor.py``).  A
transition is *confirmed* by its one WORLD_APPLIED; an apply whose outcome the
durable evidence does not establish is never confirmed and never repeated.

    BVL-WORLD-011  RESUME_TRANSITION_UNCERTAIN  the outcome of an intended apply is not
                                            established: it is recorded unknown, its
                                            evidence contradicts its intent, or - under
                                            a contract - evidence left by an interrupted
                                            run is not the transition an independent
                                            instance of the World makes
    BVL-WORLD-012  DUPLICATE_APPLY_RISK     continuing would confirm a second transition:
                                            the step already holds another World intent
                                            or outcome, an intent holds more than one
                                            outcome, or the intent is another run's
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Protocol, Self

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import BoomvalleyError, DeclarationError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.kernel.identity import (
    DecisionArtifactIdentity,
    WorldStateIdentity,
    WorldTransitionIdentity,
)

WORLD_NOT_REGISTERED = "BVL-WORLD-001"
WORLD_IDENTITY_MISMATCH = "BVL-WORLD-002"
INITIAL_STATE_INVALID = "BVL-WORLD-003"
ACTION_SCHEMA_INVALID = "BVL-WORLD-004"
TRANSITION_INTENT_MISSING = "BVL-WORLD-005"
TRANSITION_FAILED = "BVL-WORLD-006"
POST_STATE_INVALID = "BVL-WORLD-007"
NO_ACTION_UNDECLARED = "BVL-WORLD-008"
HIDDEN_WORLD_STATE = "BVL-WORLD-009"
RESUME_TRANSITION_UNCERTAIN = "BVL-WORLD-011"
DUPLICATE_APPLY_RISK = "BVL-WORLD-012"
RNG_POLICY_INVALID = "BVL-WORLD-013"
WORLD_CODES = frozenset(
    {
        WORLD_NOT_REGISTERED,
        WORLD_IDENTITY_MISMATCH,
        INITIAL_STATE_INVALID,
        ACTION_SCHEMA_INVALID,
        TRANSITION_INTENT_MISSING,
        TRANSITION_FAILED,
        POST_STATE_INVALID,
        NO_ACTION_UNDECLARED,
        HIDDEN_WORLD_STATE,
        RESUME_TRANSITION_UNCERTAIN,
        DUPLICATE_APPLY_RISK,
        RNG_POLICY_INVALID,
    }
)

STATE_SCHEMA_SCHEMA = "bvl-world-state-schema-1"
ACTION_SCHEMA_SCHEMA = "bvl-world-action-schema-1"
# contract-1 (T3-001, no action schema), contract-2 (T3-003, no progression) and
# contract-3 (T3-004, no RNG policy) are not read: nothing relabels one as contract-4
CONTRACT_SCHEMA = "bvl-world-contract-4"
#: the closed verdict vocabulary a contracted transition states its admissibility in
ADMISSIBILITY = "bvl-world-admissibility-1"
ADMISSIBLE, CLIPPED, INADMISSIBLE = "ADMISSIBLE", "CLIPPED", "INADMISSIBLE"
ADMISSIBILITY_VERDICTS = (ADMISSIBLE, CLIPPED, INADMISSIBLE)
ACTION_ROLES = ("requested_action", "admissible_action", "executed_action")
#: what a NO_ACTION decision means to a World and which exogenous events it states
PROGRESSION = "bvl-world-progression-1"
PROGRESSION_V2 = "bvl-world-progression-2"  # T4-004: declares the World's regime
UNDECLARED, NO_TRANSITION, EXOGENOUS_PROGRESSION, NULL_ACTION = (
    "UNDECLARED", "NO_TRANSITION", "EXOGENOUS_PROGRESSION", "NULL_ACTION",
)
NO_ACTION_MEANINGS = (UNDECLARED, NO_TRANSITION, EXOGENOUS_PROGRESSION, NULL_ACTION)
#: what a World is handed: a decided action, or the explicit absence of one
ACTION_INPUT, NO_ACTION_INPUT = "ACTION", "NO_ACTION"
ACTION_INPUTS = (ACTION_INPUT, NO_ACTION_INPUT)
#: the verdict of a transition whose input is NO_ACTION (no action was assessed)
NO_ACTION_VERDICT = "NO_ACTION"
TRANSITION_SCHEMA = "bvl-world-transition-1"
TRANSITION_SCHEMA_V2 = "bvl-world-transition-2"
#: the one serialization a state has: its canonical JSON bytes
STATE_SERIALIZATION = "bvl-canonical-json-1"
#: the rule a contracted World is replayed under: one transition per serialized input
REPLAY = "bvl-world-replay-1"
#: whether a World's transitions may be random, and through which generator
RNG = "bvl-world-rng-1"
DETERMINISTIC, SEEDED = "DETERMINISTIC", "SEEDED"
RNG_POLICIES = (DETERMINISTIC, SEEDED)
#: the one generator a SEEDED World draws from (``kernel/world_rng.py``)
RNG_ALGORITHM = "bvl-rng-sha256-ctr-1"
#: what a committed transition evidences of the declared RNG
RNG_EVIDENCE = "bvl-world-rng-evidence-1"
STATE_EVIDENCE_SCHEMA_V1 = "boomvalley-lab-world-state-evidence-1"
STATE_EVIDENCE_SCHEMA_V2 = "boomvalley-lab-world-state-evidence-2"
#: closed state/action field types; domain ranges stay the World's own admissibility
STATE_FIELD_TYPES = frozenset({"integer", "number", "string", "boolean", "object", "array"})


class WorldError(DeclarationError):
    """A P15 refusal carrying one stable ``BVL-WORLD-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in WORLD_CODES:
            raise ValueError(f"unknown World reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


def _type_ok(kind: str, value: Any) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # a bool is never silently an integer/number
    if kind == "integer":
        return isinstance(value, int)
    if kind == "number":
        return isinstance(value, (int, float))
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "array":
        return isinstance(value, list)
    return isinstance(value, str)


@dataclass(frozen=True)
class _TypedObjectSchemaV1:
    """One version of an object shape: every declared field required and typed.

    An ``open`` schema's objects may carry further fields it does not name; a
    closed schema (the default) refuses them.
    """

    schema_id: str
    version: int
    fields: Mapping[str, str]
    open: bool = False

    SCHEMA: ClassVar[str]
    NOUN: ClassVar[str]

    def __post_init__(self) -> None:
        if not isinstance(self.schema_id, str) or not self.schema_id or ":" in self.schema_id:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"{self.NOUN} schema id is a non-empty string without ':'",
            )
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH, f"{self.NOUN} schema version is an integer >= 1"
            )
        if not isinstance(self.fields, Mapping) or not isinstance(self.open, bool):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"{self.NOUN} schema fields is an object and open a boolean",
            )
        if not self.fields and not self.open:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"a closed {self.NOUN} schema declares at least one field",
            )
        for name, kind in self.fields.items():
            if not isinstance(name, str) or not name or kind not in STATE_FIELD_TYPES:
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH,
                    f"{self.NOUN} field {name!r} type {kind!r} is not one of "
                    f"{sorted(STATE_FIELD_TYPES)}",
                )
        object.__setattr__(self, "fields", MappingProxyType(dict(sorted(self.fields.items()))))

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self  # immutable: a contained plugin's pristine copy shares it

    @property
    def ref(self) -> str:
        return f"{self.schema_id}:{self.version}"

    def document(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "schema_id": self.schema_id,
            "version": self.version,
            "fields": dict(self.fields),
            "open": self.open,
        }

    @classmethod
    def from_document(cls, document: Any) -> Self:
        keys = {"schema", "schema_id", "version", "fields", "open"}
        if (
            not isinstance(document, Mapping)
            or set(document) != keys
            or document["schema"] != cls.SCHEMA
        ):
            raise WorldError(WORLD_IDENTITY_MISMATCH, f"not a {cls.SCHEMA}")
        return cls(
            document["schema_id"], document["version"], document["fields"], document["open"]
        )

    def problems(self, state: Any) -> list[str]:
        """Why *state* is not an object of this schema version; never coerces."""

        if not isinstance(state, Mapping):
            return [f"{self.NOUN} is a {type(state).__name__}, not an object"]
        try:
            canonical_bytes(dict(state))
        except (BoomvalleyError, TypeError, ValueError) as error:
            return [f"{self.NOUN} has no canonical serialization: {error}"]
        problems = [f"missing field {name!r}" for name in self.fields if name not in state]
        if not self.open:
            problems += [
                f"undeclared field {name!r}" for name in sorted(set(state) - set(self.fields))
            ]
        problems += [
            f"field {name!r} is not {kind}"
            for name, kind in self.fields.items()
            if name in state and not _type_ok(kind, state[name])
        ]
        return problems


#: SV-11: what a World may state of a value of its state beyond the field types
STATE_DOMAIN_RULES = ("count", "positive", "integer", "string", "among", "carried")


def state_domain_problems(domain: Any, state: Any) -> list[str]:
    """Why *state* is outside the *domain* a World states for its rule (SV-11).

    A state schema types the top-level fields and no more; a World whose rule
    is defined on less than that states the rest as data (``state_domain``), a
    sequence of rules, and the declared initial state is held to it before
    anything runs (BVL-WORLD-003):

        ("count", path)     every value at *path* is an integer >= 0
        ("positive", path)  ... an integer >= 1
        ("integer", path)   ... an integer
        ("string", path)    ... a string
        ("among", path, name, ...)
                            ... one of the names the rule lists (SV-07: a value
                            the rule branches on, as a status, is not any string)
        ("carried", holders, field, orders, key, amount)
                            every item of the array *orders* names, by *key*, a
                            member of the object *holders*, and each member's
                            *field* is the sum of its orders' *amount*

    A path names members separated by ``.``; ``*`` is every member of an
    object, ``#`` every item of an array, and a member the path names must be
    there.  A boolean is never an integer.  The domain is not part of the World
    contract or of any identity: it rules a declaration in or out, and a World's
    transitions are held to it by the World's own tests.  One function, no
    helper: what runs is the same for every World, whatever it states.
    """

    problems: list[str] = []
    for rule in domain if isinstance(domain, (list, tuple)) else [domain]:
        ruled = (
            isinstance(rule, (list, tuple))
            and bool(rule)
            and rule[0] in STATE_DOMAIN_RULES
            and (
                len(rule) >= 3 if rule[0] == "among"
                else len(rule) == (6 if rule[0] == "carried" else 2)
            )
        )
        for part in rule if ruled else ():  # a loop, not a comprehension: see above
            ruled = ruled and isinstance(part, str) and bool(part)
        if not ruled:
            problems.append(f"the World states a domain rule that is not one: {rule!r}")
            continue
        kind = rule[0]
        if kind == "carried":
            holders, field, orders, key, amount = rule[1:]
            held = state.get(holders) if isinstance(state, Mapping) else None
            listed = state.get(orders) if isinstance(state, Mapping) else None
            if not isinstance(held, Mapping) or not isinstance(listed, list):
                problems.append(f"$.{holders} is not an object or $.{orders} is not an array")
                continue
            carried: dict[str, int] = {}
            for index, order in enumerate(listed):
                name = order.get(key) if isinstance(order, Mapping) else None
                units = order.get(amount) if isinstance(order, Mapping) else None
                if (
                    not isinstance(name, str)
                    or not isinstance(held.get(name), Mapping)
                    or isinstance(units, bool)
                    or not isinstance(units, int)
                ):
                    problems.append(
                        f"$.{orders}[{index}] is not an order of an integer {amount} for a "
                        f"member of $.{holders}"
                    )
                    continue
                carried[name] = carried.get(name, 0) + units
            for name in sorted(held, key=str):
                member = held[name]
                stated = member.get(field) if isinstance(member, Mapping) else None
                if stated != carried.get(name, 0) or isinstance(stated, bool):
                    problems.append(
                        f"$.{holders}.{name}.{field} is {stated!r}, its $.{orders} carry "
                        f"{carried.get(name, 0)}"
                    )
            continue
        found: list[tuple[str, Any]] = [("$", state)]
        for segment in rule[1].split("."):
            reached: list[tuple[str, Any]] = []
            for where, value in found:
                if segment == "*":
                    if not isinstance(value, Mapping):
                        problems.append(f"{where} is not an object")
                        continue
                    for name in sorted(value, key=str):
                        reached.append((f"{where}.{name}", value[name]))
                elif segment == "#":
                    if not isinstance(value, list):
                        problems.append(f"{where} is not an array")
                        continue
                    for index, item in enumerate(value):
                        reached.append((f"{where}[{index}]", item))
                elif not isinstance(value, Mapping) or segment not in value:
                    problems.append(f"{where}.{segment} is missing")
                else:
                    reached.append((f"{where}.{segment}", value[segment]))
            found = reached
        for where, value in found:
            whole = isinstance(value, int) and not isinstance(value, bool)
            if kind == "string":
                if not isinstance(value, str):
                    problems.append(f"{where} is {value!r}, not a string")
            elif kind == "among":
                if not isinstance(value, str) or value not in rule[2:]:
                    problems.append(f"{where} is {value!r}, not one of {list(rule[2:])}")
            elif not whole:
                problems.append(f"{where} is {value!r}, not an integer")
            elif kind == "count" and value < 0:
                problems.append(f"{where} is {value}, not a count (an integer >= 0)")
            elif kind == "positive" and value < 1:
                problems.append(f"{where} is {value}, not an integer >= 1")
    return list(dict.fromkeys(problems))


def _dropped(value: Any, path: str = "$") -> list[str]:
    """Where *value* holds a null, which ``bvl-canonical-json-1`` omits."""

    if isinstance(value, Mapping):
        return [
            found
            for key, item in value.items()
            for found in ([f"{path}.{key}"] if item is None else _dropped(item, f"{path}.{key}"))
        ]
    if isinstance(value, (list, tuple)):
        return [found for index, item in enumerate(value)
                for found in _dropped(item, f"{path}[{index}]")]
    return []


def serialization_problems(state: Any) -> list[str]:
    """Why *state* does not survive its own ``bvl-canonical-json-1`` serialization."""

    if not isinstance(state, Mapping):
        return [f"state is a {type(state).__name__}, not an object"]
    try:
        canonical_bytes(dict(state))
    except (BoomvalleyError, TypeError, ValueError) as error:
        return [f"state has no canonical serialization: {error}"]
    return [
        f"{where} is null: {STATE_SERIALIZATION} drops it, so the state does not survive "
        "its own serialization"
        for where in _dropped(state)
    ]


def serialize_state(state: Mapping[str, Any]) -> bytes:
    """The one serialization of a contracted state (``bvl-canonical-json-1``)."""

    problems = serialization_problems(state)
    if problems:
        raise WorldError(POST_STATE_INVALID, "; ".join(problems))
    return canonical_bytes(dict(state))


def deserialize_state(data: bytes) -> dict[str, Any]:
    """The state *data* serializes; only the canonical bytes of an object are read."""

    try:
        state = load_bytes(data)
    except MalformedJSON as error:
        raise WorldError(POST_STATE_INVALID, f"not a serialized state: {error}") from error
    if not isinstance(state, dict) or serialization_problems(state):
        raise WorldError(POST_STATE_INVALID, "a serialized state is one JSON object")
    if canonical_bytes(state) != bytes(data):
        raise WorldError(
            POST_STATE_INVALID, f"a serialized state is its {STATE_SERIALIZATION} bytes"
        )
    return state


def replay_problems(stated: Mapping[str, Any], replayed: Any) -> list[str]:
    """Why *replayed* is not the transition document *stated* (``bvl-world-replay-1``).

    Both are transition documents of the same serialized pre-state, input and
    seed; a deterministic World states one, whichever instance is asked.
    """

    if not isinstance(replayed, Mapping):
        return ["the replay stated no transition"]
    try:
        if canonical_bytes(dict(stated)) == canonical_bytes(dict(replayed)):
            return []
    except (BoomvalleyError, TypeError, ValueError) as error:
        return [f"a transition has no canonical serialization: {error}"]
    differing = sorted(
        name for name in set(stated) | set(replayed) if stated.get(name) != replayed.get(name)
    )
    return [f"the replay states another {', '.join(differing) or 'transition'}"]


@dataclass(frozen=True)
class WorldStateSchemaV1(_TypedObjectSchemaV1):
    """One version of a World's state shape (T3-001)."""

    SCHEMA: ClassVar[str] = STATE_SCHEMA_SCHEMA
    NOUN: ClassVar[str] = "state"

    def problems(self, state: Any) -> list[str]:
        # T3-005: a state of the schema is also one that survives its serialization
        return super().problems(state) or serialization_problems(state)


@dataclass(frozen=True)
class WorldActionSchemaV1(_TypedObjectSchemaV1):
    """One version of the actions a World accepts (T3-003, P15 §2)."""

    SCHEMA: ClassVar[str] = ACTION_SCHEMA_SCHEMA
    NOUN: ClassVar[str] = "action"


def admissibility_problems(
    action_schema: WorldActionSchemaV1, transition: Mapping[str, Any]
) -> list[str]:
    """Why a transition document's three actions are not a stated admissibility.

    The one ``bvl-world-admissibility-1`` rule: the engine applies it before a
    transition is committed, the verifiers to the committed evidence.  Each
    action is read as the World stated it; none is derived from another.
    """

    actions: dict[str, dict[str, Any]] = {}
    for role in ACTION_ROLES:
        value = transition.get(role)
        if not isinstance(value, Mapping):
            return [f"{role} is not an object"]
        actions[role] = dict(value)
    verdict = transition.get("admissibility_verdict")
    if verdict not in ADMISSIBILITY_VERDICTS:
        return [
            f"admissibility verdict {verdict!r} is not one of {list(ADMISSIBILITY_VERDICTS)}"
        ]
    requested, admissible, executed = (actions[role] for role in ACTION_ROLES)
    ref = action_schema.ref
    try:
        unchanged = canonical_bytes(admissible) == canonical_bytes(requested)
    except (BoomvalleyError, TypeError, ValueError) as error:
        return [f"an action has no canonical serialization: {error}"]
    problems: list[str] = []
    if verdict == ADMISSIBLE and not unchanged:
        problems.append("ADMISSIBLE, but the admissible action is not the requested action")
    if verdict == CLIPPED:
        if unchanged:
            problems.append("CLIPPED, but the admissible action is the requested action")
        problems += [
            f"the admissible action is not a {ref} action: {problem}"
            for problem in action_schema.problems(admissible)
        ]
    if verdict == INADMISSIBLE and (admissible or executed):
        problems.append("INADMISSIBLE, but an action is stated admissible or executed")
    if executed:
        problems += [
            f"the executed action is neither empty nor a {ref} action: {problem}"
            for problem in action_schema.problems(executed)
        ]
    return problems


@dataclass(frozen=True)
class WorldProgressionV1:
    """What NO_ACTION means to a World and the exogenous events it may state (T3-004).

    A World plugin declares one as ``progression``; a World declaring none
    carries the default: NO_ACTION is not its input and it states no event.
    """

    no_action: str = UNDECLARED
    null_action: Mapping[str, Any] | None = None
    exogenous_events: tuple[str, ...] = ()
    # T4-004: the event kinds that are a regime change and the state fields
    # that are the regime; both or neither
    regime_events: tuple[str, ...] = ()
    regime_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.no_action not in NO_ACTION_MEANINGS:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"NO_ACTION meaning {self.no_action!r} is not one of {list(NO_ACTION_MEANINGS)}",
            )
        if (self.no_action == NULL_ACTION) != isinstance(self.null_action, Mapping):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"exactly a {NULL_ACTION} World declares its null action (an object)",
            )
        events = self.exogenous_events
        if (
            not isinstance(events, (tuple, list))
            or any(not isinstance(kind, str) or not kind for kind in events)
            or len(set(events)) != len(events)
        ):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                "exogenous event kinds are distinct non-empty strings",
            )
        object.__setattr__(self, "exogenous_events", tuple(sorted(events)))
        for name in ("regime_events", "regime_fields"):
            names = getattr(self, name)
            if (
                not isinstance(names, (tuple, list))
                or any(not isinstance(item, str) or not item for item in names)
                or len(set(names)) != len(names)
            ):
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH, f"{name} are distinct non-empty strings"
                )
            object.__setattr__(self, name, tuple(sorted(names)))
        if bool(self.regime_events) != bool(self.regime_fields):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                "a World with regimes declares both its regime events and its regime "
                "state fields",
            )
        undeclared = sorted(set(self.regime_events) - set(self.exogenous_events))
        if undeclared:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"regime events {undeclared} are not exogenous event kinds the World "
                f"declares ({list(self.exogenous_events)})",
            )
        if self.null_action is not None:
            object.__setattr__(self, "null_action", MappingProxyType(dict(self.null_action)))

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self  # immutable, as the schemas

    def document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": PROGRESSION,
            "no_action": self.no_action,
            "exogenous_events": list(self.exogenous_events),
        }
        if self.null_action is not None:  # stated exactly by a NULL_ACTION World
            document["null_action"] = dict(self.null_action)
        if self.regime_events:  # stated exactly by a World with regimes
            document["schema"] = PROGRESSION_V2
            document["regime"] = {
                "events": list(self.regime_events),
                "fields": list(self.regime_fields),
            }
        return document

    @classmethod
    def from_document(cls, document: Any) -> Self:
        keys = {"schema", "no_action", "exogenous_events"}
        regime = document.get("regime") if isinstance(document, Mapping) else None
        if (
            not isinstance(document, Mapping)
            or set(document) - {"null_action", "regime"} != keys
            or document["schema"] != (PROGRESSION_V2 if "regime" in document else PROGRESSION)
            or not isinstance(document["exogenous_events"], (list, tuple))
            or ("null_action" in document and not isinstance(document["null_action"], Mapping))
            or (
                "regime" in document
                and (
                    not isinstance(regime, Mapping)
                    or set(regime) != {"events", "fields"}
                    or any(
                        not isinstance(regime[name], list) or not regime[name]
                        for name in ("events", "fields")
                    )
                )
            )
        ):
            raise WorldError(WORLD_IDENTITY_MISMATCH, f"not a {PROGRESSION}")
        made = cls(
            document["no_action"],
            document.get("null_action"),
            tuple(document["exogenous_events"]),
            tuple((regime or {}).get("events", ())),
            tuple((regime or {}).get("fields", ())),
        )
        if (
            made.exogenous_events != tuple(document["exogenous_events"])
            or (regime is not None and made.document()["regime"] != dict(regime))
        ):  # unsorted kinds
            raise WorldError(WORLD_IDENTITY_MISMATCH, f"not a canonical {PROGRESSION}")
        return made

    def regime_changes(self, transition: Mapping[str, Any]) -> list[str]:
        """The regime event kinds one transition document states, in stated order."""

        events = transition.get("exogenous_events")
        return [
            event["event"]
            for event in (events if isinstance(events, (list, tuple)) else ())
            if isinstance(event, Mapping) and event.get("event") in self.regime_events
        ]


def progression_problems(
    progression: WorldProgressionV1,
    action_schema: WorldActionSchemaV1,
    transition: Mapping[str, Any],
) -> list[str]:
    """Why a transition document is not one stated ``bvl-world-progression-1``.

    The rule that keeps a null action and environment progression from being
    hidden mutations: the engine applies it before a transition is committed,
    the verifiers to the committed evidence.
    """

    if transition.get("schema") != TRANSITION_SCHEMA_V2:
        return [
            f"the transition is not a {TRANSITION_SCHEMA_V2}: it does not state whether an "
            "action was executed or which exogenous events occurred"
        ]
    given = transition.get("action_input")
    if given not in ACTION_INPUTS:
        return [f"action input {given!r} is not one of {list(ACTION_INPUTS)}"]
    executed = transition.get("executed")
    if not isinstance(executed, bool):
        return ["executed is not a boolean"]
    events = transition.get("exogenous_events")
    if not isinstance(events, list):
        return ["exogenous_events is not an array"]
    problems: list[str] = []
    for index, event in enumerate(events):
        if (
            not isinstance(event, Mapping)
            or set(event) != {"event", "detail"}
            or not isinstance(event["detail"], Mapping)
        ):
            problems.append(f"exogenous event #{index} is not exactly {{event, detail}}")
        elif event["event"] not in progression.exogenous_events:
            problems.append(
                f"exogenous event {event['event']!r} is not a kind the World contract "
                f"declares ({list(progression.exogenous_events)})"
            )
    actions = {role: transition.get(role) for role in ACTION_ROLES}
    if any(not isinstance(action, Mapping) for action in actions.values()):
        return [*problems, "an action is not an object"]
    try:
        moved = canonical_bytes(dict(transition["post_state"])) != canonical_bytes(
            dict(transition["pre_state"])
        )
        null = progression.null_action is not None and canonical_bytes(
            dict(actions["executed_action"])
        ) == canonical_bytes(dict(progression.null_action))
    except (BoomvalleyError, KeyError, TypeError, ValueError) as error:
        return [*problems, f"a state or action has no canonical serialization: {error}"]
    done = actions["executed_action"]
    if not executed and done:
        problems.append("nothing was executed, but an executed action is stated")
    if executed:
        problems += [
            f"the executed action is not a {action_schema.ref} action: {problem}"
            for problem in action_schema.problems(done)
        ]
    verdict = transition.get("admissibility_verdict")
    if given == ACTION_INPUT:
        if verdict == INADMISSIBLE and executed:
            problems.append("INADMISSIBLE, but an action is stated executed")
    else:
        meaning = progression.no_action
        if meaning == UNDECLARED:
            problems.append("NO_ACTION is not an input the World contract declares")
        if verdict != NO_ACTION_VERDICT:
            problems.append(f"a NO_ACTION input states the verdict {NO_ACTION_VERDICT!r}")
        if actions["requested_action"] or actions["admissible_action"]:
            problems.append("NO_ACTION, but an action is stated requested or admissible")
        if meaning in (NO_TRANSITION, EXOGENOUS_PROGRESSION) and executed:
            problems.append(f"NO_ACTION means {meaning}, but an action is stated executed")
        if meaning == NO_TRANSITION and (events or moved):
            problems.append(
                "NO_ACTION means NO_TRANSITION, but the transition states an exogenous "
                "event or another post-state"
            )
        if meaning == NULL_ACTION and not (executed and null):
            problems.append(
                "NO_ACTION means NULL_ACTION, but the executed action is not the "
                "contract's declared null action"
            )
    if moved and not executed and not events:
        problems.append(
            "hidden mutation: the post-state is not the pre-state, but neither an "
            "executed action nor an exogenous event is stated"
        )
    # T4-004: a regime moves only in a transition that states a regime event
    pre, post = dict(transition["pre_state"]), dict(transition["post_state"])
    shifted = sorted(
        name
        for name in progression.regime_fields
        if (name in pre) != (name in post)
        or (name in pre and canonical_bytes({"v": pre[name]}) != canonical_bytes({"v": post[name]}))
    )
    if shifted and not progression.regime_changes(transition):
        problems.append(
            f"hidden regime change: regime fields {shifted} moved, but no declared "
            f"regime event ({list(progression.regime_events)}) is stated"
        )
    return problems


@dataclass(frozen=True)
class WorldRngPolicyV1:
    """Whether a World's transitions may be random, and through which RNG (T3-006).

    A World plugin declares one as ``rng``; a World declaring none is
    DETERMINISTIC.  A SEEDED World names the generator it draws from, and the
    kernel knows one.
    """

    policy: str = DETERMINISTIC
    algorithm: str | None = None

    def __post_init__(self) -> None:
        if self.policy not in RNG_POLICIES:
            raise WorldError(
                RNG_POLICY_INVALID,
                f"RNG policy {self.policy!r} is not one of {list(RNG_POLICIES)}",
            )
        if self.policy == SEEDED and self.algorithm is None:
            object.__setattr__(self, "algorithm", RNG_ALGORITHM)
        if (self.policy == SEEDED) != (self.algorithm == RNG_ALGORITHM):
            raise WorldError(
                RNG_POLICY_INVALID,
                f"exactly a {SEEDED} World names its RNG algorithm, and the declared RNG is "
                f"{RNG_ALGORITHM!r}; {self.algorithm!r} is not",
            )

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self  # immutable, as the schemas

    @property
    def seeded(self) -> bool:
        return self.policy == SEEDED

    def document(self) -> dict[str, Any]:
        document: dict[str, Any] = {"schema": RNG, "policy": self.policy}
        if self.algorithm is not None:  # stated exactly by a SEEDED World
            document["algorithm"] = self.algorithm
        return document

    @classmethod
    def from_document(cls, document: Any) -> Self:
        if (
            not isinstance(document, Mapping)
            or set(document) - {"algorithm"} != {"schema", "policy"}
            or document["schema"] != RNG
        ):
            raise WorldError(RNG_POLICY_INVALID, f"not a {RNG}")
        made = cls(document["policy"], document.get("algorithm"))
        if made.document() != dict(document):  # a SEEDED policy states its algorithm
            raise WorldError(RNG_POLICY_INVALID, f"not a canonical {RNG}")
        return made

    def evidence(self, *, draws: int = 0, bits: int = 0) -> dict[str, Any]:
        """What a committed transition evidences of the declared RNG."""

        document: dict[str, Any] = {"schema": RNG_EVIDENCE, "policy": self.policy}
        if self.seeded:
            document.update(algorithm=self.algorithm, draws=draws, bits=bits)
        return document

    def evidence_problems(self, evidence: Any) -> list[str]:
        """Why *evidence* is not what a transition under this policy evidences."""

        if not isinstance(evidence, Mapping) or evidence.get("schema") != RNG_EVIDENCE:
            return [f"the transition evidences no {RNG_EVIDENCE}"]
        if evidence.get("policy") != self.policy:
            return [
                f"the transition was made under RNG policy {evidence.get('policy')!r}; the "
                f"World contract declares {self.policy}"
            ]
        if not self.seeded:
            if set(evidence) != {"schema", "policy"}:
                return ["a DETERMINISTIC transition states draws from an RNG"]
            return []
        if set(evidence) != {"schema", "policy", "algorithm", "draws", "bits"}:
            return [f"a {SEEDED} transition states exactly its algorithm, draws and bits"]
        problems = []
        if evidence["algorithm"] != self.algorithm:
            problems.append(
                f"the transition drew from {evidence['algorithm']!r}, not the declared "
                f"{self.algorithm!r}"
            )
        draws, bits = evidence["draws"], evidence["bits"]
        counted = all(
            isinstance(count, int) and not isinstance(count, bool) and count >= 0
            for count in (draws, bits)
        )
        if not counted or bits < draws:
            problems.append("draws and bits are not the counts of one stream of draws")
        return problems


@dataclass(frozen=True)
class WorldContractV1:
    """The plan's frozen World binding (enters PlanIdentity as ``world``)."""

    plugin: str  # the World's registered plugin identity
    state_schema: WorldStateSchemaV1
    action_schema: WorldActionSchemaV1
    progression: WorldProgressionV1 = WorldProgressionV1()
    rng: WorldRngPolicyV1 = WorldRngPolicyV1()

    def __post_init__(self) -> None:
        if not isinstance(self.plugin, str) or not self.plugin:
            raise WorldError(WORLD_NOT_REGISTERED, "a World contract names its World plugin")
        if not isinstance(self.state_schema, WorldStateSchemaV1):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH, "a World contract carries a WorldStateSchemaV1"
            )
        if not isinstance(self.action_schema, WorldActionSchemaV1):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH, "a World contract carries a WorldActionSchemaV1"
            )
        if not isinstance(self.progression, WorldProgressionV1):
            raise WorldError(
                WORLD_IDENTITY_MISMATCH, "a World contract carries a WorldProgressionV1"
            )
        if not isinstance(self.rng, WorldRngPolicyV1):
            raise WorldError(RNG_POLICY_INVALID, "a World contract carries a WorldRngPolicyV1")
        foreign = sorted(set(self.progression.regime_fields) - set(self.state_schema.fields))
        if foreign:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"regime fields {foreign} are not fields of {self.state_schema.ref}",
            )
        null = self.progression.null_action
        unfit = [] if null is None else self.action_schema.problems(null)
        if unfit:
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"the declared null action is not a {self.action_schema.ref} action: "
                f"{'; '.join(unfit)}",
            )

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "plugin": self.plugin,
            "state_schema": self.state_schema.document(),
            "state_serialization": STATE_SERIALIZATION,
            "action_schema": self.action_schema.document(),
            "admissibility": ADMISSIBILITY,
            "progression": self.progression.document(),
            "rng": self.rng.document(),
        }

    @classmethod
    def from_document(cls, document: Any) -> WorldContractV1:
        keys = {
            "schema", "plugin", "state_schema", "state_serialization", "action_schema",
            "admissibility", "progression", "rng",
        }
        if (
            not isinstance(document, Mapping)
            or set(document) != keys
            or document["schema"] != CONTRACT_SCHEMA
            or document["state_serialization"] != STATE_SERIALIZATION
            or document["admissibility"] != ADMISSIBILITY
        ):
            raise WorldError(WORLD_IDENTITY_MISMATCH, f"not a {CONTRACT_SCHEMA}")
        return cls(
            document["plugin"],
            WorldStateSchemaV1.from_document(document["state_schema"]),
            WorldActionSchemaV1.from_document(document["action_schema"]),
            WorldProgressionV1.from_document(document["progression"]),
            WorldRngPolicyV1.from_document(document["rng"]),
        )

    def action_problems(self, action: Any) -> list[str]:
        """Why *action* is not an action this World accepts (BVL-WORLD-004)."""

        return self.action_schema.problems(action)

    def admissibility_problems(self, transition: Mapping[str, Any]) -> list[str]:
        """An assessed action's three actions; a NO_ACTION input assessed none."""

        if transition.get("action_input") == NO_ACTION_INPUT:
            return []
        return admissibility_problems(self.action_schema, transition)

    def progression_problems(self, transition: Mapping[str, Any]) -> list[str]:
        return progression_problems(self.progression, self.action_schema, transition)

    def require_initial_state(self, state: Any) -> None:
        """BVL-WORLD-003, before anything runs."""

        problems = self.state_schema.problems(state)
        if problems:
            raise WorldError(
                INITIAL_STATE_INVALID,
                f"the initial state is not a {self.state_schema.ref} state of World "
                f"{self.plugin!r}: {'; '.join(problems)}",
            )


def state_identity(state: Mapping[str, Any], state_schema: str | None) -> WorldStateIdentity:
    """A state's identity: versioned under a schema ref, identity-1 without one."""

    if state_schema is None:
        return WorldStateIdentity.of_payload(dict(state))
    return WorldStateIdentity.of_versioned(state_schema=state_schema, state=dict(state))


def state_evidence_document(
    state: Mapping[str, Any], state_schema: str | None = None
) -> dict[str, Any]:
    """The ``world_state`` evidence member of one explicit state."""

    if state_schema is None:
        return {
            "schema": STATE_EVIDENCE_SCHEMA_V1,
            "identity": state_identity(state, None).document(),
            "state": dict(state),
        }
    return {
        "schema": STATE_EVIDENCE_SCHEMA_V2,
        "identity": state_identity(state, state_schema).document(),
        "state_schema": state_schema,
        "state": dict(state),
    }


@dataclass(frozen=True)
class WorldTransition:
    """One explicit requested -> admissible -> executed domain transition."""

    requested_action: Mapping[str, Any]
    admissibility_verdict: str
    admissible_action: Mapping[str, Any]
    executed_action: Mapping[str, Any]
    pre_state: Mapping[str, Any]
    post_state: Mapping[str, Any]
    outcome: Mapping[str, Any]
    # T3-004: a World that states ``executed`` returns a transition-2, which also
    # states its input and its exogenous events; a K0 World states none of them
    executed: bool | None = None
    action_input: str = ACTION_INPUT
    exogenous_events: tuple[Mapping[str, Any], ...] = ()

    def document(self) -> dict[str, Any]:
        document = {
            "schema": TRANSITION_SCHEMA,
            "requested_action": dict(self.requested_action),
            "admissibility_verdict": self.admissibility_verdict,
            "admissible_action": dict(self.admissible_action),
            "executed_action": dict(self.executed_action),
            "pre_state": dict(self.pre_state),
            "post_state": dict(self.post_state),
            "outcome": dict(self.outcome),
        }
        if self.executed is None:
            if self.action_input != ACTION_INPUT or self.exogenous_events:
                raise ValueError(
                    "a transition stating a NO_ACTION input or an exogenous event states "
                    "whether an action was executed"
                )
            return document
        document.update(
            schema=TRANSITION_SCHEMA_V2,
            action_input=self.action_input,
            executed=self.executed,
            exogenous_events=[dict(event) for event in self.exogenous_events],
        )
        return document

    def pre_state_identity(self, state_schema: str | None = None) -> WorldStateIdentity:
        return state_identity(self.pre_state, state_schema)

    def post_state_identity(self, state_schema: str | None = None) -> WorldStateIdentity:
        return state_identity(self.post_state, state_schema)

    def identity(
        self,
        *,
        decision: DecisionArtifactIdentity,
        world_plugin_identity: str,
        seed_identity: str,
        state_schema: str | None = None,
        rng: Mapping[str, Any] | None = None,
    ) -> WorldTransitionIdentity:
        payload = {
            "decision": decision.document(),
            "world_plugin_identity": world_plugin_identity,
            "seed_identity": seed_identity,
            "transition": self.document(),
        }
        if state_schema is not None:
            payload["state_schema"] = state_schema
        if rng is not None:  # T3-006: the RNG context a contracted transition was made under
            payload["rng"] = dict(rng)
        return WorldTransitionIdentity.of_payload(payload)


class PureWorld(Protocol):
    """A spike-level World: explicit input state, no hidden mutable state."""

    plugin_identity: str

    def apply(
        self,
        state: Mapping[str, Any],
        requested_action: Mapping[str, Any] | None,
        *,
        seed: int,
    ) -> WorldTransition: ...


class ContractedWorld(PureWorld, Protocol):
    """A P15 World: a PureWorld that declares the schema versions of its state
    and of the actions it accepts.  It may declare a ``progression``
    (``WorldProgressionV1``); only a World whose progression gives NO_ACTION a
    meaning is ever handed ``None`` as its requested action.  Declaring no
    ``rng`` it is DETERMINISTIC: its seed does not change what it states."""

    state_schema: WorldStateSchemaV1
    action_schema: WorldActionSchemaV1


class DeclaredRng(Protocol):
    """The declared RNG a SEEDED World draws from (``kernel/world_rng.WorldRng``)."""

    def randbits(self, k: int) -> int: ...

    def randbelow(self, n: int) -> int: ...

    def random(self) -> float: ...

    def choice(self, items: Any) -> Any: ...

    def shuffled(self, items: Any) -> list[Any]: ...


class StochasticWorld(Protocol):
    """A P15 World whose ``rng`` is SEEDED (T3-006): it is handed the declared
    RNG of its transition and never a seed."""

    plugin_identity: str
    state_schema: WorldStateSchemaV1
    action_schema: WorldActionSchemaV1
    rng: WorldRngPolicyV1

    def apply(
        self,
        state: Mapping[str, Any],
        requested_action: Mapping[str, Any] | None,
        *,
        rng: DeclaredRng,
    ) -> WorldTransition: ...
