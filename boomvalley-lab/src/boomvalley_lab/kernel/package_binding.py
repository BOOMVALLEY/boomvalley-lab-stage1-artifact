"""Real BuildIdentity / PluginSetIdentity package binding (T0-013).

Software identity is bound *beside* the plan, never into it:

    PlanIdentity            (semantic plan only)
    BuildIdentity           installed distribution + loaded product code
    PluginSetIdentity       registered plugins + entry points + plugin config
    -> ExecutionBindingIdentity (plan x build x plugin set)
    -> AuthorizationIdentity    (gate-2)

A build is what this process actually executes: the ``boomvalley_lab``
package files it imported, digested file by file, plus how they were
installed (an installed wheel, an editable install, or a bare source tree)
and the distribution metadata that owns them.  Distribution metadata that
does not own the loaded code is not bound - a stale or foreign
``boomvalley`` dist-info must not vouch for code it did not install.

Plugins are bound through the installed ``boomvalley_lab.plugins`` entry
points.  The kernel only *discovers* entry points from installed metadata; the
caller injects the loader (no dynamic import in the kernel).  An entry-point
plugin's factory must be exactly the advertised ``module:attr`` and its
declared ``code_identity`` must be the digest of that module's source file.
"""

from __future__ import annotations

import functools
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import (
    CanonicalisationError,
    DeclarationError,
    EvidenceError,
    ExecutionError,
)
from boomvalley_lab.core.versions import PACKAGE_VERSION
from boomvalley_lab.kernel.gate import identity_from_document
from boomvalley_lab.kernel.identity import (
    BuildIdentity,
    ExecutionBindingIdentity,
    PlanIdentity,
    PluginSetIdentity,
    execution_binding_identity,
)

BUILD_SCHEMA = "bvl-build-descriptor-1"
BINDING_SCHEMA = "bvl-execution-binding-2"
CODE_DIGEST_METHOD = "bvl-package-code-digest-1"
DISTRIBUTION = "boomvalley"
PRODUCT_PACKAGE = "boomvalley_lab"
PLUGIN_ENTRY_POINT_GROUP = "boomvalley_lab.plugins"
ORIGINS = frozenset({"installed", "editable", "source_tree"})

_PRODUCT_ROOT = Path(__file__).resolve().parents[1]
_BUILD_FIELDS = frozenset(
    {
        "schema",
        "package",
        "package_version",
        "origin",
        "code_digest_method",
        "code_digest",
        "file_count",
    }
)


# -- build -----------------------------------------------------------------------


def package_code_digest(package_dir: Path) -> tuple[str, int]:
    """``bvl-package-code-digest-1``: every ``*.py`` under *package_dir*.

    Paths are package-relative POSIX paths, sorted; ``__pycache__`` is
    excluded.  Returns ``(digest, file_count)``.
    """

    root = Path(package_dir)
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": str(sha256_bytes(path.read_bytes())),
        }
        for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix())
        if "__pycache__" not in path.relative_to(root).parts
    ]
    if not files:
        raise ExecutionError(f"{root} holds no product code to bind")
    return str(sha256_document({"method": CODE_DIGEST_METHOD, "files": files})), len(files)


@dataclass(frozen=True)
class BuildDescriptorV1:
    """One installed BVL product build, as this process executes it."""

    package: str
    package_version: str
    origin: str
    distribution: Mapping[str, str] | None
    code_digest: str
    file_count: int

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ValueError(f"build origin is one of {sorted(ORIGINS)}")
        if (self.origin == "source_tree") != (self.distribution is None):
            raise ValueError("only a source-tree build has no owning distribution")
        if self.distribution is not None and set(self.distribution) != {"name", "version"}:
            raise ValueError("build distribution is exactly {name, version}")
        if not self.code_digest.startswith("sha256:") or self.file_count < 1:
            raise ValueError("build code digest is sha256 over at least one file")

    def document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": BUILD_SCHEMA,
            "package": self.package,
            "package_version": self.package_version,
            "origin": self.origin,
            "code_digest_method": CODE_DIGEST_METHOD,
            "code_digest": self.code_digest,
            "file_count": self.file_count,
        }
        if self.distribution is not None:  # canonical form omits absent members
            document["distribution"] = dict(self.distribution)
        return document

    def identity(self) -> BuildIdentity:
        return BuildIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> BuildDescriptorV1:
        if not isinstance(document, Mapping) or set(document) - {"distribution"} != _BUILD_FIELDS:
            raise EvidenceError("build descriptor has the wrong closed shape")
        if document["schema"] != BUILD_SCHEMA:
            raise EvidenceError(f"build descriptor schema is exactly {BUILD_SCHEMA!r}")
        if document["code_digest_method"] != CODE_DIGEST_METHOD:
            raise EvidenceError(f"build code digest method is exactly {CODE_DIGEST_METHOD!r}")
        try:
            return cls(
                package=document["package"],
                package_version=document["package_version"],
                origin=document["origin"],
                distribution=document.get("distribution"),
                code_digest=document["code_digest"],
                file_count=document["file_count"],
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise EvidenceError(f"build descriptor is invalid: {error}") from error


def _owning_origin(dist: metadata.Distribution, init_file: Path) -> str | None:
    """How *dist* installed the loaded package, or None if it did not."""

    for path in dist.files or ():
        if path.as_posix() == f"{PRODUCT_PACKAGE}/__init__.py":
            try:
                if Path(dist.locate_file(path)).resolve() == init_file:
                    return "installed"
            except OSError:
                return None
    text = dist.read_text("direct_url.json")
    if text:
        try:
            direct = json.loads(text)
        except ValueError:
            return None
        if isinstance(direct, Mapping) and (direct.get("dir_info") or {}).get("editable"):
            parsed = urlparse(str(direct.get("url", "")))
            if parsed.scheme == "file":
                location = unquote(parsed.path)
                if sys.platform == "win32" and location.startswith("/") and ":" in location:
                    location = location.lstrip("/")
                project = Path(location).resolve()
                if init_file.is_relative_to(project):
                    return "editable"
    return None


@functools.lru_cache(maxsize=8)
def _installed_build(distribution: str, package_dir: Path) -> BuildDescriptorV1:
    digest, count = package_code_digest(package_dir)
    init_file = (package_dir / "__init__.py").resolve()
    origin, owner = "source_tree", None
    # Every metadata copy on sys.path is a candidate (an in-tree egg-info may
    # shadow the real install); the owner is the one that installed this code.
    for dist in metadata.distributions(name=distribution):
        owned = _owning_origin(dist, init_file)
        if owned is not None:
            origin = owned
            owner = {"name": dist.metadata["Name"], "version": dist.version}
            break
    return BuildDescriptorV1(PRODUCT_PACKAGE, PACKAGE_VERSION, origin, owner, digest, count)


def installed_build_v1(
    *, distribution: str = DISTRIBUTION, package_dir: Path | None = None
) -> BuildDescriptorV1:
    """The build this process executes (cached per process: loaded code is fixed)."""

    return _installed_build(distribution, Path(package_dir or _PRODUCT_ROOT).resolve())


# -- plugin entry points -----------------------------------------------------------


@dataclass(frozen=True)
class PluginEntryPointV1:
    """One installed entry point advertising a BVL plugin factory."""

    group: str
    name: str
    value: str
    distribution: str
    distribution_version: str

    def document(self) -> dict[str, str]:
        return {
            "group": self.group,
            "name": self.name,
            "value": self.value,
            "distribution": self.distribution,
            "distribution_version": self.distribution_version,
        }


def installed_plugin_entry_points(
    group: str = PLUGIN_ENTRY_POINT_GROUP,
) -> tuple[tuple[PluginEntryPointV1, metadata.EntryPoint], ...]:
    """Entry points of *group* from installed distribution metadata, sorted by name.

    Duplicate names (two distributions claiming one plugin id) are refused.
    """

    found: list[tuple[PluginEntryPointV1, metadata.EntryPoint]] = []
    for entry in metadata.entry_points(group=group):
        dist = entry.dist
        if dist is None:
            raise DeclarationError(f"entry point {entry.name!r} has no owning distribution")
        found.append(
            (
                PluginEntryPointV1(
                    group, entry.name, entry.value, dist.metadata["Name"], dist.version
                ),
                entry,
            )
        )
    names = [bound.name for bound, _ in found]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise DeclarationError(f"plugin entry points are claimed twice: {duplicates}")
    return tuple(sorted(found, key=lambda item: item[0].name))


def qualified_name(target: object) -> str:
    return f"{getattr(target, '__module__', '?')}:{getattr(target, '__qualname__', '?')}"


def module_code_identity(target: object) -> str:
    """sha256 of the source file of the (already loaded) module defining *target*."""

    module = sys.modules.get(getattr(target, "__module__", ""))
    source = getattr(module, "__file__", None)
    if not source or not str(source).endswith(".py"):
        raise DeclarationError(f"{qualified_name(target)} has no loaded Python source to bind")
    return str(sha256_bytes(Path(source).read_bytes()))


def config_digest(config: Mapping[str, Any]) -> str:
    if not isinstance(config, Mapping):
        raise DeclarationError("plugin config is a mapping")
    try:
        return str(sha256_bytes(canonical_bytes(dict(config))))
    except CanonicalisationError as error:
        raise DeclarationError(f"plugin config is not canonical JSON: {error}") from error


EntryPointLoader = Callable[[metadata.EntryPoint], object]


# -- execution binding -------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionBindingV2:
    """One plan bound to one build and one plugin set (persisted as evidence)."""

    plan: PlanIdentity
    build: BuildDescriptorV1
    plugin_manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_manifest, Mapping) or not str(
            self.plugin_manifest.get("schema", "")
        ).startswith("boomvalley-lab-plugin-manifest-"):
            raise ValueError("plugin_manifest is a plugin registry manifest document")

    def build_identity(self) -> BuildIdentity:
        return self.build.identity()

    def plugin_set_identity(self) -> PluginSetIdentity:
        return PluginSetIdentity.of_payload(dict(self.plugin_manifest))

    def identity(self) -> ExecutionBindingIdentity:
        return execution_binding_identity(
            self.plan,
            build_identity=self.build_identity(),
            plugin_set_identity=self.plugin_set_identity(),
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema": BINDING_SCHEMA,
            "plan": self.plan.document(),
            "build": self.build.document(),
            "build_identity": self.build_identity().document(),
            "plugin_manifest": dict(self.plugin_manifest),
            "plugin_set_identity": self.plugin_set_identity().document(),
            "execution_binding_identity": self.identity().document(),
        }

    @classmethod
    def from_document(cls, document: Any) -> ExecutionBindingV2:
        fields = {
            "schema",
            "plan",
            "build",
            "build_identity",
            "plugin_manifest",
            "plugin_set_identity",
            "execution_binding_identity",
        }
        if not isinstance(document, Mapping) or set(document) != fields:
            raise EvidenceError("execution binding has the wrong closed shape")
        if document["schema"] != BINDING_SCHEMA:
            raise EvidenceError(f"execution binding schema is exactly {BINDING_SCHEMA!r}")
        try:
            binding = cls(
                identity_from_document(PlanIdentity, document["plan"], "binding plan"),
                BuildDescriptorV1.from_document(document["build"]),
                document["plugin_manifest"],
            )
            recomputed = canonical_bytes(binding.document())
        except (ValueError, CanonicalisationError) as error:
            raise EvidenceError(f"execution binding is invalid: {error}") from error
        if recomputed != canonical_bytes(dict(document)):
            raise EvidenceError(
                "execution binding identities do not recompute from its build and plugin set"
            )
        return binding


def bind_execution_v2(
    plan: PlanIdentity,
    registry: Any,
    *,
    build: BuildDescriptorV1 | None = None,
) -> ExecutionBindingV2:
    """Bind *plan* to this process's installed build and *registry*'s plugin set.

    *plan* is taken as given: nothing here can reach PlanIdentity.
    """

    if not isinstance(plan, PlanIdentity):
        raise TypeError("bind_execution_v2 binds a PlanIdentity")
    return ExecutionBindingV2(
        plan,
        build if build is not None else installed_build_v1(),
        registry.manifest_document(),
    )


def verify_current_build_v2(binding: ExecutionBindingV2) -> None:
    """Refuse to (re)open a run under a build other than the one it is bound to."""

    current = installed_build_v1()
    if current != binding.build:
        raise ExecutionError(
            f"run is bound to build {binding.build_identity()} "
            f"({binding.build.origin}, code {binding.build.code_digest}); "
            f"this process executes {current.identity()} "
            f"({current.origin}, code {current.code_digest})"
        )
