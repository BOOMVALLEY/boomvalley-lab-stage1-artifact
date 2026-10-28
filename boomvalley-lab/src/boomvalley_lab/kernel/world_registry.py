"""The World plugin registry (T3-001, P03 x P15).

A World is a typed plugin: it enters a run only as a ``PluginType.WORLD``
member of the run's ``PluginRegistryV1`` (so its code identity and config are
bound into the PluginSetIdentity), and this registry is the one place the
kernel reads what such a plugin *is*:

    plugin_identity   the identity the World itself states; it is exactly the
                      identity it is registered under (BVL-WORLD-002)
    apply             the one transition entry point
    state_schema      the ``WorldStateSchemaV1`` of every state it reads and
                      writes; a World without one is a K0 World and cannot
                      carry a plan's World contract (BVL-WORLD-001)
    action_schema     the ``WorldActionSchemaV1`` of the actions it accepts
                      (T3-003); a World carries a contract only with both
    progression       optionally, the ``WorldProgressionV1`` stating what
                      NO_ACTION means to it and the exogenous events it may
                      state (T3-004); without one NO_ACTION is not its input
    rng               optionally, the ``WorldRngPolicyV1`` stating whether its
                      transitions may be random (T3-006); without one it is
                      DETERMINISTIC.  Its ``apply`` is the entry point of that
                      policy - ``rng`` for a SEEDED World, ``seed`` otherwise
                      (BVL-WORLD-013)

``contract`` is what a compiler freezes into the plan; ``resolve`` hands the
engine the World of a frozen contract, and only the World whose registered
state schema is still exactly the plan's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.kernel.plugin_registry import PluginRegistryV1, PluginType
from boomvalley_lab.kernel.world import (
    RNG_POLICY_INVALID,
    WORLD_IDENTITY_MISMATCH,
    WORLD_NOT_REGISTERED,
    PureWorld,
    WorldActionSchemaV1,
    WorldContractV1,
    WorldError,
    WorldProgressionV1,
    WorldRngPolicyV1,
    WorldStateSchemaV1,
)
from boomvalley_lab.kernel.world_rng import entry_point_problems

REGISTRY_SCHEMA = "bvl-world-registry-1"


class WorldRegistryV1:
    """Every registered World of one plugin set, by plugin identity."""

    def __init__(self, worlds: Mapping[str, PureWorld]) -> None:
        self._worlds: dict[str, PureWorld] = {}
        for plugin_id in sorted(worlds):
            world = worlds[plugin_id]
            stated = getattr(world, "plugin_identity", None)
            if stated != plugin_id:
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH,
                    f"the World registered as {plugin_id!r} states plugin identity {stated!r}",
                )
            if not callable(getattr(world, "apply", None)):
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH, f"World {plugin_id!r} has no apply(state, action)"
                )
            schema = getattr(world, "state_schema", None)
            if schema is not None and not isinstance(schema, WorldStateSchemaV1):
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH,
                    f"World {plugin_id!r} state_schema is not a WorldStateSchemaV1",
                )
            actions = getattr(world, "action_schema", None)
            if actions is not None and not isinstance(actions, WorldActionSchemaV1):
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH,
                    f"World {plugin_id!r} action_schema is not a WorldActionSchemaV1",
                )
            progression = getattr(world, "progression", None)
            if progression is not None and not isinstance(progression, WorldProgressionV1):
                raise WorldError(
                    WORLD_IDENTITY_MISMATCH,
                    f"World {plugin_id!r} progression is not a WorldProgressionV1",
                )
            rng = getattr(world, "rng", None)
            if rng is not None and not isinstance(rng, WorldRngPolicyV1):
                raise WorldError(
                    RNG_POLICY_INVALID, f"World {plugin_id!r} rng is not a WorldRngPolicyV1"
                )
            unfit = entry_point_problems(world, rng or WorldRngPolicyV1())
            if unfit and schema is not None:  # a K0 World carries no RNG policy
                raise WorldError(RNG_POLICY_INVALID, f"World {plugin_id!r}: {'; '.join(unfit)}")
            self._worlds[plugin_id] = world

    @classmethod
    def from_plugins(cls, registry: PluginRegistryV1) -> WorldRegistryV1:
        return cls(
            {
                descriptor.plugin_id: registry.resolve(descriptor.plugin_id, PluginType.WORLD)
                for descriptor in registry.descriptors()
                if descriptor.plugin_type is PluginType.WORLD
            }
        )

    def worlds(self) -> dict[str, PureWorld]:
        return dict(self._worlds)

    def contract(self, plugin_id: Any) -> WorldContractV1:
        """The contract of the registered World *plugin_id* (what a plan freezes)."""

        world = self._worlds.get(plugin_id) if isinstance(plugin_id, str) else None
        if world is None:
            raise WorldError(
                WORLD_NOT_REGISTERED,
                f"no World plugin {plugin_id!r} is registered (registered: "
                f"{sorted(self._worlds)})",
            )
        schema = getattr(world, "state_schema", None)
        if schema is None:
            raise WorldError(
                WORLD_NOT_REGISTERED,
                f"World {plugin_id!r} declares no state schema: it carries no World contract",
            )
        actions = getattr(world, "action_schema", None)
        if actions is None:
            raise WorldError(
                WORLD_NOT_REGISTERED,
                f"World {plugin_id!r} declares no action schema: it carries no World contract",
            )
        progression = getattr(world, "progression", None)
        return WorldContractV1(
            plugin_id,
            schema,
            actions,
            progression or WorldProgressionV1(),
            getattr(world, "rng", None) or WorldRngPolicyV1(),
        )

    def resolve(self, contract: WorldContractV1) -> PureWorld:
        """The World that executes *contract*: registered, and still that contract."""

        registered = self.contract(contract.plugin)
        if registered.document() != contract.document():
            held = (registered.state_schema.ref, registered.action_schema.ref)
            frozen = (contract.state_schema.ref, contract.action_schema.ref)
            raise WorldError(
                WORLD_IDENTITY_MISMATCH,
                f"World {contract.plugin!r} is registered with state schema {held[0]} and "
                f"action schema {held[1]}, the plan froze {frozen[0]} and {frozen[1]}"
                + (
                    " with another definition, progression or RNG policy"
                    if held == frozen
                    else ""
                ),
            )
        return self._worlds[contract.plugin]

    def document(self) -> dict[str, Any]:
        """Every registered World and the state and action schemas it declares (or none)."""

        return {
            "schema": REGISTRY_SCHEMA,
            "worlds": [
                {
                    "plugin": plugin_id,
                    "state_schema": (
                        None
                        if getattr(world, "state_schema", None) is None
                        else world.state_schema.document()
                    ),
                    "action_schema": (
                        None
                        if getattr(world, "action_schema", None) is None
                        else world.action_schema.document()
                    ),
                    "progression": (
                        getattr(world, "progression", None) or WorldProgressionV1()
                    ).document(),
                    "rng": (getattr(world, "rng", None) or WorldRngPolicyV1()).document(),
                }
                for plugin_id, world in self._worlds.items()
            ],
        }
