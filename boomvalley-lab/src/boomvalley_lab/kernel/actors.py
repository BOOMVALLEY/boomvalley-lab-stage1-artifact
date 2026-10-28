"""P04 actor registry, role and execution profile (T1-001).

An actor is a concrete organizational participant of a plan; it is not a
factor level, a prompt label, a file name or an adapter alias.  Three
separate semantics, each with its own identity:

    Role              organizational meaning            RoleIdentity
    Actor             participant identity in the plan  ActorIdentity
    ExecutionProfile  how the actor is executed         ExecutionProfileIdentity

``ActorIdentity`` is a function of the actor id and its role identity only.
It never depends on the declaration order of actors, roles or profiles, on
the profile the actor resolves to, or on the factor level (label) that
selected that profile.  A profile may be chosen per design cell, but only
through a declared ``by_factor`` rule over a closed set of levels; the level
label itself selects and is then gone: the resolved binding carries the
profile, never the label.

An ``ExecutionProfileV1`` binds everything that decides how one actor call
is executed: the provider adapter's registered plugin identity, the intended
model identity, the generation options, the seed policy and the renderer
binding.  Before intent the actor-call handler holds the rendered request-2
to exactly these values, and after the call it holds the reported model to
the intended one (``BVL-ACTOR-*`` refusals).

Seed derivation is owned by K0 (``SeedDerivation``); a profile only names a
closed seed policy that selects the actor-call seed namespace:

    bvl-seed-actor-1          one stream per actor: the path carries the
                              ActorIdentity (never the label or position)
    bvl-seed-shared-round-1   common random numbers: every actor under this
                              policy draws the same seed in one round
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import CanonicalisationError, DeclarationError
from boomvalley_lab.kernel.identity import (
    ActorIdentity,
    ExecutionProfileIdentity,
    RoleIdentity,
)
from boomvalley_lab.kernel.seed import SeedDerivation

REGISTRY_SCHEMA = "bvl-actor-registry-1"
PROFILE_SCHEMA = "bvl-actor-execution-profile-1"
BINDING_SET_SCHEMA = "bvl-actor-binding-set-1"

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

# P04 §8 stable reason-code family
ACTOR_ID_DUPLICATE = "BVL-ACTOR-001"
ROLE_MISSING = "BVL-ACTOR-002"
PROFILE_MISSING = "BVL-ACTOR-003"
PROFILE_RESOLUTION_AMBIGUOUS = "BVL-ACTOR-004"
PROFILE_IDENTITY_MISMATCH = "BVL-ACTOR-005"
PROVIDER_IDENTITY_MISMATCH = "BVL-ACTOR-006"
MODEL_IDENTITY_MISMATCH = "BVL-ACTOR-007"
SEED_POLICY_INVALID = "BVL-ACTOR-008"
ACTOR_NOT_IN_PLAN = "BVL-ACTOR-009"
UNDECLARED_PROFILE_OVERRIDE = "BVL-ACTOR-010"
ACTOR_CALL_OUTSIDE_ENGINE = "BVL-ACTOR-011"

ACTOR_CODES = frozenset(
    {
        ACTOR_ID_DUPLICATE,
        ROLE_MISSING,
        PROFILE_MISSING,
        PROFILE_RESOLUTION_AMBIGUOUS,
        PROFILE_IDENTITY_MISMATCH,
        PROVIDER_IDENTITY_MISMATCH,
        MODEL_IDENTITY_MISMATCH,
        SEED_POLICY_INVALID,
        ACTOR_NOT_IN_PLAN,
        UNDECLARED_PROFILE_OVERRIDE,
        ACTOR_CALL_OUTSIDE_ENGINE,
    }
)

#: option keys a profile may never carry: the seed is bound by the seed policy
_RESERVED_OPTIONS = frozenset({"seed", "random_seed"})


class ActorError(DeclarationError):
    """A P04 refusal carrying one stable ``BVL-ACTOR-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in ACTOR_CODES:
            raise ValueError(f"unknown actor reason code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code


class SeedPolicy(StrEnum):
    PER_ACTOR = "bvl-seed-actor-1"
    SHARED_ROUND = "bvl-seed-shared-round-1"


def _require_id(value: Any, what: str, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ActorError(code, f"{what} is not a valid identifier: {value!r}")
    return value


def _frozen(value: Any) -> Any:
    """Canonical-JSON round trip: plain, order-free, non-aliased data."""

    try:
        return json.loads(canonical_json(value))
    except CanonicalisationError as error:
        raise ActorError(PROFILE_IDENTITY_MISMATCH, f"not canonical data: {error}") from error


@dataclass(frozen=True)
class RoleV1:
    """Organizational meaning; never decision authority (that is P07)."""

    role_id: str

    def __post_init__(self) -> None:
        _require_id(self.role_id, "role id", ROLE_MISSING)

    def identity(self) -> RoleIdentity:
        return RoleIdentity.of_payload({"role_id": self.role_id})


@dataclass(frozen=True)
class ExecutionProfileV1:
    profile_id: str
    provider: str  # the provider adapter's registered plugin identity
    model: str  # the intended model identity
    options: Mapping[str, Any]
    seed_policy: SeedPolicy
    renderer: str  # the renderer binding (P05 owns rendering semantics)

    def __post_init__(self) -> None:
        _require_id(self.profile_id, "profile id", PROFILE_MISSING)
        for name in ("provider", "model", "renderer"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ActorError(
                    PROFILE_MISSING, f"profile {self.profile_id!r} {name} must be non-empty"
                )
        if not isinstance(self.options, Mapping) or not all(
            isinstance(key, str) for key in self.options
        ):
            raise ActorError(
                PROFILE_MISSING, f"profile {self.profile_id!r} options is a string-keyed object"
            )
        reserved = sorted(_RESERVED_OPTIONS & set(self.options))
        if reserved:
            raise ActorError(
                SEED_POLICY_INVALID,
                f"profile {self.profile_id!r} options carry {reserved}; "
                "the seed is bound by the seed policy",
            )
        try:
            policy = SeedPolicy(self.seed_policy)
        except ValueError as error:
            raise ActorError(
                SEED_POLICY_INVALID,
                f"profile {self.profile_id!r} seed policy {self.seed_policy!r} is not one of "
                f"{sorted(item.value for item in SeedPolicy)}",
            ) from error
        object.__setattr__(self, "seed_policy", policy)
        object.__setattr__(self, "options", MappingProxyType(_frozen(dict(self.options))))

    def semantic_document(self) -> dict[str, Any]:
        """What execution means; the profile id is a declaration-local name."""

        return {
            "schema": PROFILE_SCHEMA,
            "provider": self.provider,
            "model": self.model,
            "options": dict(self.options),
            "seed_policy": self.seed_policy.value,
            "renderer": self.renderer,
        }

    def identity(self) -> ExecutionProfileIdentity:
        return ExecutionProfileIdentity.of_payload(self.semantic_document())

    def resolve_seed(
        self,
        seeds: SeedDerivation,
        *,
        actor: ActorIdentity,
        episode_key: str,
        round_index: int,
        step_id: str,
        attempt: int = 1,
    ) -> int:
        if self.seed_policy is SeedPolicy.PER_ACTOR:
            return seeds.actor_call(
                episode_key,
                round_index=round_index,
                step_id=step_id,
                actor_id=str(actor),
                attempt=attempt,
            )
        return seeds.derive(
            "episode",
            episode_key,
            "round",
            str(round_index),
            "actor-shared",
            self.seed_policy.value,
            "attempt",
            str(attempt),
        )


@dataclass(frozen=True)
class ProfileByFactorV1:
    """Select a profile by the level of one declared factor (model-as-factor)."""

    factor: str
    cases: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_id(self.factor, "profile rule factor", PROFILE_RESOLUTION_AMBIGUOUS)
        if not isinstance(self.cases, Mapping) or not self.cases:
            raise ActorError(
                PROFILE_RESOLUTION_AMBIGUOUS,
                f"profile rule over {self.factor!r} has no level cases",
            )
        for level, profile in self.cases.items():
            if not isinstance(level, str) or not level:
                raise ActorError(
                    PROFILE_RESOLUTION_AMBIGUOUS, f"factor level {level!r} is not a string"
                )
            _require_id(profile, f"profile for level {level!r}", PROFILE_MISSING)
        object.__setattr__(self, "cases", MappingProxyType(dict(self.cases)))

    def document(self) -> dict[str, Any]:
        return {"by_factor": self.factor, "cases": dict(sorted(self.cases.items()))}


ProfileRef = str | ProfileByFactorV1


@dataclass(frozen=True)
class ActorV1:
    actor_id: str
    role: str
    profile: ProfileRef

    def __post_init__(self) -> None:
        _require_id(self.actor_id, "actor id", ACTOR_NOT_IN_PLAN)
        _require_id(self.role, f"actor {self.actor_id!r} role", ROLE_MISSING)
        if isinstance(self.profile, str):
            _require_id(self.profile, f"actor {self.actor_id!r} profile", PROFILE_MISSING)
        elif not isinstance(self.profile, ProfileByFactorV1):
            raise ActorError(
                PROFILE_MISSING, f"actor {self.actor_id!r} names no profile or profile rule"
            )

    def document(self) -> dict[str, Any]:
        profile = self.profile if isinstance(self.profile, str) else self.profile.document()
        return {"role": self.role, "profile": profile}


def actor_identity(actor_id: str, role: RoleIdentity) -> ActorIdentity:
    """The participant identity: actor id x role.  Nothing else enters."""

    return ActorIdentity.of_payload({"actor_id": actor_id, "role": role.document()})


@dataclass(frozen=True)
class ActorBindingV1:
    """One plan actor resolved to its frozen execution profile."""

    actor_id: str
    role: str
    profile: ExecutionProfileV1

    @property
    def role_identity(self) -> RoleIdentity:
        return RoleV1(self.role).identity()

    @property
    def identity(self) -> ActorIdentity:
        return actor_identity(self.actor_id, self.role_identity)

    @property
    def profile_identity(self) -> ExecutionProfileIdentity:
        return self.profile.identity()

    def document(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "role": self.role,
            "profile": self.profile.semantic_document(),
        }


@dataclass(frozen=True)
class ActorBindingSetV1:
    """The resolved actors one plan executes; this is what enters the plan.

    The document is canonical (sorted by actor id) and carries semantic
    content only - never identity references, so PlanIdentity stays a root.
    """

    bindings: Mapping[str, ActorBindingV1] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for actor_id, binding in self.bindings.items():
            if binding.actor_id != actor_id:
                raise ActorError(ACTOR_ID_DUPLICATE, f"binding {actor_id!r} names another actor")
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))

    def __contains__(self, actor_id: object) -> bool:
        return actor_id in self.bindings

    def binding(self, actor_id: str) -> ActorBindingV1:
        binding = self.bindings.get(actor_id) if isinstance(actor_id, str) else None
        if binding is None:
            raise ActorError(ACTOR_NOT_IN_PLAN, f"actor {actor_id!r} is not in the frozen plan")
        return binding

    def document(self) -> dict[str, Any]:
        return {
            "schema": BINDING_SET_SCHEMA,
            "actors": [self.bindings[key].document() for key in sorted(self.bindings)],
        }

    @classmethod
    def from_document(cls, document: Any) -> ActorBindingSetV1:
        """Read one ``bvl-actor-binding-set-1`` back (closed, canonical shape)."""

        if not isinstance(document, Mapping) or set(document) != {"schema", "actors"}:
            raise ActorError(PROFILE_IDENTITY_MISMATCH, "actor binding set has the wrong shape")
        if document["schema"] != BINDING_SET_SCHEMA or not isinstance(document["actors"], list):
            raise ActorError(
                PROFILE_IDENTITY_MISMATCH, f"actor binding set is not {BINDING_SET_SCHEMA}"
            )
        bindings: dict[str, ActorBindingV1] = {}
        for item in document["actors"]:
            if not isinstance(item, Mapping) or set(item) != {"actor_id", "role", "profile"}:
                raise ActorError(PROFILE_IDENTITY_MISMATCH, "actor binding has the wrong shape")
            profile = item["profile"]
            if not isinstance(profile, Mapping) or set(profile) != {
                "schema",
                "provider",
                "model",
                "options",
                "seed_policy",
                "renderer",
            } or profile["schema"] != PROFILE_SCHEMA:
                raise ActorError(PROFILE_IDENTITY_MISMATCH, "actor profile has the wrong shape")
            actor_id = _require_id(item["actor_id"], "actor id", ACTOR_NOT_IN_PLAN)
            if actor_id in bindings:
                raise ActorError(ACTOR_ID_DUPLICATE, f"actor {actor_id!r} is bound twice")
            bindings[actor_id] = ActorBindingV1(
                actor_id,
                _require_id(item["role"], "role id", ROLE_MISSING),
                ExecutionProfileV1(
                    profile_id="bound",
                    provider=profile["provider"],
                    model=profile["model"],
                    options=profile["options"],
                    seed_policy=profile["seed_policy"],
                    renderer=profile["renderer"],
                ),
            )
        parsed = cls(bindings)
        if parsed.document() != _frozen(dict(document)):
            raise ActorError(PROFILE_IDENTITY_MISMATCH, "actor binding set is not canonical")
        return parsed


class ActorRegistryV1:
    """The declared roles, execution profiles and actors of one experiment."""

    def __init__(
        self,
        *,
        roles: Sequence[RoleV1],
        profiles: Sequence[ExecutionProfileV1],
        actors: Sequence[ActorV1],
    ) -> None:
        self._roles = self._unique(roles, "role_id", "role", ROLE_MISSING)
        self._profiles = self._unique(
            profiles, "profile_id", "profile", PROFILE_RESOLUTION_AMBIGUOUS
        )
        self._actors = self._unique(actors, "actor_id", "actor", ACTOR_ID_DUPLICATE)
        if not self._actors:
            raise ActorError(ACTOR_NOT_IN_PLAN, "an actor registry declares at least one actor")
        for actor in self._actors.values():
            if actor.role not in self._roles:
                raise ActorError(
                    ROLE_MISSING, f"actor {actor.actor_id!r} names undeclared role {actor.role!r}"
                )
            for profile_id in self._profile_refs(actor):
                if profile_id not in self._profiles:
                    raise ActorError(
                        PROFILE_MISSING,
                        f"actor {actor.actor_id!r} names undeclared profile {profile_id!r}",
                    )

    @staticmethod
    def _unique(items: Sequence[Any], attribute: str, what: str, code: str) -> dict[str, Any]:
        unique: dict[str, Any] = {}
        for item in items:
            key = getattr(item, attribute)
            if key in unique:
                raise ActorError(code, f"{what} id {key!r} is declared twice")
            unique[key] = item
        return unique

    @staticmethod
    def _profile_refs(actor: ActorV1) -> tuple[str, ...]:
        if isinstance(actor.profile, str):
            return (actor.profile,)
        return tuple(sorted(set(actor.profile.cases.values())))

    @property
    def actor_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._actors))

    def factors(self) -> dict[str, frozenset[str]]:
        """The factors profile resolution depends on, with their closed levels."""

        factors: dict[str, frozenset[str]] = {}
        for actor in self._actors.values():
            if isinstance(actor.profile, ProfileByFactorV1):
                levels = frozenset(actor.profile.cases)
                known = factors.setdefault(actor.profile.factor, levels)
                if known != levels:
                    raise ActorError(
                        PROFILE_RESOLUTION_AMBIGUOUS,
                        f"factor {actor.profile.factor!r} is resolved over different level sets",
                    )
        return factors

    def actor_identity(self, actor_id: str) -> ActorIdentity:
        actor = self._actors.get(actor_id)
        if actor is None:
            raise ActorError(ACTOR_NOT_IN_PLAN, f"actor {actor_id!r} is not declared")
        return actor_identity(actor_id, self._roles[actor.role].identity())

    def document(self) -> dict[str, Any]:
        """Canonical declaration: independent of every declaration order."""

        return {
            "schema": REGISTRY_SCHEMA,
            "roles": sorted(self._roles),
            "profiles": {
                key: self._profiles[key].semantic_document() for key in sorted(self._profiles)
            },
            "actors": {key: self._actors[key].document() for key in sorted(self._actors)},
        }

    def resolve(self, cell: Mapping[str, str] | None = None) -> ActorBindingSetV1:
        """Bind every declared actor to exactly one profile for one design cell.

        Only the factors a ``by_factor`` rule names are read; a missing,
        unknown or extra-level assignment refuses (zero calls follow).
        """

        cell = dict(cell or {})
        factors = self.factors()
        for factor, levels in factors.items():
            if factor not in cell:
                raise ActorError(
                    PROFILE_RESOLUTION_AMBIGUOUS, f"cell assigns no level to factor {factor!r}"
                )
            if cell[factor] not in levels:
                raise ActorError(
                    PROFILE_RESOLUTION_AMBIGUOUS,
                    f"factor {factor!r} level {cell[factor]!r} is not one of {sorted(levels)}",
                )
        bindings: dict[str, ActorBindingV1] = {}
        for actor_id in sorted(self._actors):
            actor = self._actors[actor_id]
            profile_id = (
                actor.profile
                if isinstance(actor.profile, str)
                else actor.profile.cases[cell[actor.profile.factor]]
            )
            bindings[actor_id] = ActorBindingV1(actor_id, actor.role, self._profiles[profile_id])
        return ActorBindingSetV1(bindings)
