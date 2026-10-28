"""Typed plugin registry contract for generalized BVL execution.

It proves that plugin identity/type/capability metadata is explicit and that
no study supplies an arbitrary module path for execution.  Plugins enter either
in-process (``register``) or from installed ``boomvalley_lab.plugins`` entry
points (``from_entry_points``, T0-013).  Each plugin's origin (entry point and
owning distribution) and config digest are part of the PluginSetIdentity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.kernel.identity import PluginSetIdentity
from boomvalley_lab.kernel.package_binding import (
    PLUGIN_ENTRY_POINT_GROUP,
    EntryPointLoader,
    PluginEntryPointV1,
    config_digest,
    installed_plugin_entry_points,
    module_code_identity,
    qualified_name,
)

MANIFEST_SCHEMA = "boomvalley-lab-plugin-manifest-2"


class PluginType(StrEnum):
    ADAPTER = "adapter"
    SOURCE_RESOLVER = "source_resolver"
    RENDERER = "renderer"
    PROVIDER_CODEC = "provider_codec"
    PROPOSAL_PARSER = "proposal_parser"
    DECISION_RULE = "decision_rule"
    VALIDATION_POLICY = "validation_policy"
    VISIBILITY_TRANSFORM = "visibility_transform"
    WORLD = "world"
    TERMINATION_RULE = "termination_rule"
    MEMORY_TRANSFORM = "memory_transform"
    METRIC = "metric"
    HUMAN_CHANNEL = "human_channel"
    TOOL = "tool"


@dataclass(frozen=True)
class PluginDescriptorV1:
    plugin_id: str
    plugin_type: PluginType
    contract_version: str
    implementation_version: str
    code_identity: str
    capabilities: Sequence[str] = ()
    erf: Sequence[str] = ()
    arf: Sequence[str] = ()
    external_io: bool = False
    stochastic: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("plugin_id", self.plugin_id),
            ("contract_version", self.contract_version),
            ("implementation_version", self.implementation_version),
            ("code_identity", self.code_identity),
        ):
            if not isinstance(value, str) or not value.strip():
                raise DeclarationError(f"{name} must be a non-empty string")
        if not isinstance(self.plugin_type, PluginType):
            raise DeclarationError("plugin_type is a registered PluginType")
        for field_name, values in (
            ("capabilities", self.capabilities),
            ("erf", self.erf),
            ("arf", self.arf),
        ):
            if not all(isinstance(value, str) and value for value in values):
                raise DeclarationError(f"{field_name} contains non-empty strings")
            if len(values) != len(set(values)):
                raise DeclarationError(f"{field_name} contains unique values")

    def document(self) -> dict[str, Any]:
        return {
            "schema": "boomvalley-lab-plugin-descriptor-1",
            "plugin_id": self.plugin_id,
            "plugin_type": self.plugin_type.value,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "code_identity": self.code_identity,
            "capabilities": sorted(self.capabilities),
            "erf": sorted(self.erf),
            "arf": sorted(self.arf),
            "external_io": self.external_io,
            "stochastic": self.stochastic,
        }


@dataclass(frozen=True)
class RegisteredPluginV1:
    descriptor: PluginDescriptorV1
    implementation: object
    config_digest: str
    entry_point: PluginEntryPointV1 | None = None

    def document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "descriptor": self.descriptor.document(),
            "config_digest": self.config_digest,
        }
        if self.entry_point is not None:  # in-process plugins have no entry point
            document["entry_point"] = self.entry_point.document()
        return document


class PluginRegistryV1:
    def __init__(self) -> None:
        self._plugins: dict[str, RegisteredPluginV1] = {}

    def register(
        self,
        descriptor: PluginDescriptorV1,
        implementation: object,
        *,
        config: Mapping[str, Any] | None = None,
        entry_point: PluginEntryPointV1 | None = None,
    ) -> None:
        if descriptor.plugin_id in self._plugins:
            raise DeclarationError(f"plugin {descriptor.plugin_id!r} is already registered")
        if entry_point is not None and entry_point.name != descriptor.plugin_id:
            raise DeclarationError(
                f"entry point {entry_point.name!r} advertises another plugin than "
                f"{descriptor.plugin_id!r}"
            )
        self._plugins[descriptor.plugin_id] = RegisteredPluginV1(
            descriptor, implementation, config_digest(config or {}), entry_point
        )

    def resolve(self, plugin_id: str, expected_type: PluginType) -> object:
        registered = self._plugins.get(plugin_id)
        if registered is None:
            raise DeclarationError(f"plugin {plugin_id!r} is not registered")
        if registered.descriptor.plugin_type is not expected_type:
            raise DeclarationError(
                f"plugin {plugin_id!r} is {registered.descriptor.plugin_type.value}, "
                f"not {expected_type.value}"
            )
        return registered.implementation

    def descriptor(self, plugin_id: str) -> PluginDescriptorV1:
        registered = self._plugins.get(plugin_id)
        if registered is None:
            raise DeclarationError(f"plugin {plugin_id!r} is not registered")
        return registered.descriptor

    def descriptors(self) -> tuple[PluginDescriptorV1, ...]:
        return tuple(
            self._plugins[plugin_id].descriptor for plugin_id in sorted(self._plugins)
        )

    def manifest_document(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "plugins": [self._plugins[plugin_id].document() for plugin_id in sorted(self._plugins)],
        }

    def identity(self) -> PluginSetIdentity:
        return PluginSetIdentity.of_payload(self.manifest_document())

    @classmethod
    def from_registered(
        cls,
        plugins: Sequence[tuple[PluginDescriptorV1, object]],
    ) -> PluginRegistryV1:
        registry = cls()
        for descriptor, implementation in plugins:
            registry.register(descriptor, implementation)
        return registry

    @classmethod
    def from_entry_points(
        cls,
        *,
        load: EntryPointLoader,
        config: Mapping[str, Mapping[str, Any]] | None = None,
        group: str = PLUGIN_ENTRY_POINT_GROUP,
    ) -> PluginRegistryV1:
        """Register every installed plugin entry point of *group*.

        Each entry point names a factory ``factory(config) -> (descriptor,
        implementation)``.  *load* (injected by the caller; the kernel performs
        no dynamic import) resolves the entry point.  The factory must be
        exactly the advertised ``module:attr``, the descriptor's plugin id the
        entry-point name, and its ``code_identity`` the digest of the factory's
        module source.  Config for a plugin that is not installed is refused.
        """

        registry = cls()
        registry.register_entry_points(load=load, config=config, group=group)
        return registry

    def register_entry_points(
        self,
        *,
        load: EntryPointLoader,
        config: Mapping[str, Mapping[str, Any]] | None = None,
        group: str = PLUGIN_ENTRY_POINT_GROUP,
    ) -> tuple[str, ...]:
        """Register every installed entry point of *group* into this registry.

        The rules are ``from_entry_points``'s; the plugins join whatever is
        already registered (T4-011: a product catalog), and an entry point
        claiming a registered plugin id is refused like any second
        registration.  *config* names installed plugins only.  Returns the
        registered plugin ids, sorted.
        """

        config = dict(config or {})
        installed = installed_plugin_entry_points(group)
        unknown = sorted(set(config) - {bound.name for bound, _ in installed})
        if unknown:
            raise DeclarationError(f"config names plugins that are not installed: {unknown}")
        for bound, entry in installed:
            factory = load(entry)
            advertised = bound.value.replace(" ", "")
            if qualified_name(factory) != advertised:
                raise DeclarationError(
                    f"entry point {bound.name!r} advertises {advertised!r}, "
                    f"loaded {qualified_name(factory)!r}"
                )
            plugin_config = dict(config.get(bound.name, {}))
            produced = factory(plugin_config)
            if not (isinstance(produced, tuple) and len(produced) == 2):
                raise DeclarationError(
                    f"plugin factory {advertised!r} returns (descriptor, implementation)"
                )
            descriptor, implementation = produced
            if not isinstance(descriptor, PluginDescriptorV1):
                raise DeclarationError(f"plugin factory {advertised!r} returned no descriptor")
            code = module_code_identity(factory)
            if descriptor.code_identity != code:
                raise DeclarationError(
                    f"plugin {descriptor.plugin_id!r} declares code {descriptor.code_identity}, "
                    f"its installed module is {code}"
                )
            self.register(
                descriptor, implementation, config=plugin_config, entry_point=bound
            )
        return tuple(bound.name for bound, _ in installed)
