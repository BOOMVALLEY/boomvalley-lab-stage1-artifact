"""The public plugin author contract (``bvl-plugin-author-contract-1``; T4-011, P03 x P15).

This module is everything of the product an out-of-tree plugin imports.  A
plugin author needs no other ``boomvalley_lab`` module, and nothing else of the
product is a contract: a name that is not exported here may change without
notice.  The prose of the contract - what a World may and may not do, how a
study names it, how it is packaged, run and verified - is
``docs/BOOMVALLEY/V2_LAB/PLUGIN_AUTHOR_CONTRACT.md``.

The contract covers one plugin type, the World (``PluginType.WORLD``): the
domain extension point of a study at any level up to L4 (rounds, memory,
regime change, scheduled episodes).  A World is one class:

    plugin_identity   the plugin id it is installed under, ``"<name>:<version>"``
    state_schema      ``WorldStateSchemaV1`` - every state it reads and writes
    action_schema     ``WorldActionSchemaV1`` - the actions it accepts
    progression       (optional) ``WorldProgressionV1`` - what NO_ACTION means to
                      it, the exogenous events it may state, its regime
    rng               (optional) ``WorldRngPolicyV1(SEEDED)`` - a World whose
                      transitions draw from the declared RNG
    apply             ``apply(state, requested_action, *, seed)``, or
                      ``apply(state, requested_action, *, rng)`` when SEEDED,
                      returning one ``WorldTransition``

and a distribution advertises it as an entry point of ``ENTRY_POINT_GROUP``
whose name is the plugin id and whose value names a module-level factory:

    def plugin(config):
        return world_plugin(plugin, MyWorld(), config)

``world_plugin`` states the P03 descriptor - the plugin id and type, this
contract's version, the implementation version and the code identity of the
factory's module - so the World is bound into the PluginSetIdentity of every
run of the installation it is installed in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.kernel.package_binding import (
    PLUGIN_ENTRY_POINT_GROUP,
    module_code_identity,
)
from boomvalley_lab.kernel.plugin_registry import PluginDescriptorV1, PluginType
from boomvalley_lab.kernel.world import (
    ACTION_INPUT,
    ADMISSIBLE,
    CLIPPED,
    DETERMINISTIC,
    EXOGENOUS_PROGRESSION,
    INADMISSIBLE,
    NO_ACTION_INPUT,
    NO_ACTION_VERDICT,
    NO_TRANSITION,
    NULL_ACTION,
    SEEDED,
    UNDECLARED,
    DeclaredRng,
    WorldActionSchemaV1,
    WorldProgressionV1,
    WorldRngPolicyV1,
    WorldStateSchemaV1,
    WorldTransition,
)

CONTRACT = "bvl-plugin-author-contract-1"
#: the contract version a descriptor made here states
CONTRACT_VERSION = "1"
#: the entry-point group an installed plugin is advertised under
ENTRY_POINT_GROUP = PLUGIN_ENTRY_POINT_GROUP


def world_plugin(
    factory: object,
    world: object,
    config: Mapping[str, Any] | None = None,
    *,
    implementation_version: str = "1",
) -> tuple[PluginDescriptorV1, object]:
    """What a World plugin's entry-point factory returns: ``(descriptor, world)``.

    *factory* is the calling factory itself (its module is the code identity
    bound into every run) and *config* the plugin config it was handed.  A
    World reads its whole domain from the state it is handed, so a World
    plugin takes no config: a non-empty one is refused here.
    """

    plugin_id = getattr(world, "plugin_identity", None)
    if not isinstance(plugin_id, str) or not plugin_id:
        raise DeclarationError("a World states its plugin_identity (a non-empty string)")
    if config:
        raise DeclarationError(
            f"World plugin {plugin_id!r} takes no plugin_config: a World reads its whole "
            "domain from the state it is handed"
        )
    policy = getattr(world, "rng", None)
    descriptor = PluginDescriptorV1(
        plugin_id,
        PluginType.WORLD,
        CONTRACT_VERSION,
        implementation_version,
        module_code_identity(factory),
        stochastic=isinstance(policy, WorldRngPolicyV1) and policy.seeded,
    )
    return descriptor, world


__all__ = [
    "ACTION_INPUT",
    "ADMISSIBLE",
    "CLIPPED",
    "CONTRACT",
    "CONTRACT_VERSION",
    "DETERMINISTIC",
    "ENTRY_POINT_GROUP",
    "EXOGENOUS_PROGRESSION",
    "INADMISSIBLE",
    "NO_ACTION_INPUT",
    "NO_ACTION_VERDICT",
    "NO_TRANSITION",
    "NULL_ACTION",
    "SEEDED",
    "UNDECLARED",
    "DeclaredRng",
    "DeclarationError",
    "WorldActionSchemaV1",
    "WorldProgressionV1",
    "WorldRngPolicyV1",
    "WorldStateSchemaV1",
    "WorldTransition",
    "world_plugin",
]
