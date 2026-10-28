"""K0 adversarial containment for one engine execution (T0-016).

A K0 plugin (renderer, adapter, proposal parser, World) is untrusted study
code.  While GenericEpisodeEngine executes an episode, one containment session
is armed and four designed defences make the K0 attack classes fail closed:

- monkeypatch: a kernel seal compares every function/method defined in the
  loaded kernel modules (and the boomvalley_lab modules they import from)
  with code compiled from that module's source on disk, checks every
  ``from boomvalley_lab... import name`` binding, and pins a few stdlib
  primitives evidence depends on.  It is verified before the episode writes
  anything, after every plugin call and after every handler; a tampered
  kernel is restored to the session's pristine objects before the refusal is
  journaled, so the patch cannot also suppress EPISODE_FAILED.
- hidden HTTP: a process-wide audit hook refuses network and process/ctypes
  events everywhere in the session except network inside the one
  engine-authorized adapter transport window (DurableCallExecutorV2).
- denied-source direct read: inside plugin windows (and on any thread other
  than the engine thread) the hook refuses reads and listings of the run's
  own evidence directory and of every declared denied source.
- hidden memory: plugin windows refuse file writes; the engine refuses a
  handler that mutated or rebound world state, memory or the round's
  dependency values; renderers, parsers and Worlds are replayed and must
  produce identical output, so undeclared state carried across calls is
  refused as IMPURE_PLUGIN.

A tool actor's tool (P17, T5-005) is called inside its own window, opened by
``DurableToolCallExecutorV1`` only: it may reach the network like an adapter,
a mutating tool may write outside the run's evidence and the denied sources,
and a read-only one (and every reconciliation) may write nothing - a tool that
states READ_ONLY and changes a file is HIDDEN_WRITE.  A transport window is the
engine's to open: an adapter or tool window opened while a plugin window is
open is a model or tool call some plugin made on its own (HIDDEN_MODEL_CALL,
HIDDEN_TOOL_CALL), refused before the transport is reached.

A violation is recorded before it is raised, so a plugin that swallows the
exception is still refused at the next engine check.  Without an armed
session every window is a no-op, so direct use of the kernel boundaries is
unchanged.

The checker is itself plugin-reachable code, so it is held by what is not
(T4-014): when a session arms, the guard hook is handed the callables of this
module, of every loaded product module outside the sealed kernel and of the
session, and at every plugin-window exit it puts back and refuses whatever was
rebound, re-coded or shadowed since.  A plugin that replaces
``ContainmentSessionV2.check`` or ``KernelSealV2.problems`` before it patches
the kernel therefore meets the seal it tried to remove.  ``contained_load``
arms the same session around the import and construction of installed plugins,
so a module that patches the product or opens a connection when it is imported
is refused before a study exists.
"""

from __future__ import annotations

import ast
import builtins
import copy
import importlib.util
import io
import json
import os
import sys
import sysconfig
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import CodeType, FunctionType, ModuleType
from typing import Any, TypeVar

from boomvalley_lab.core import digest as _digest_service
from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.kernel.world import RNG_POLICY_INVALID
from boomvalley_lab.kernel.world_rng import hidden_rng_refused

KERNEL_TAMPERED = "KERNEL_TAMPERED"
HIDDEN_NETWORK = "HIDDEN_NETWORK"
HIDDEN_PROCESS = "HIDDEN_PROCESS"
DENIED_SOURCE_READ = "DENIED_SOURCE_READ"
HIDDEN_WRITE = "HIDDEN_WRITE"
HIDDEN_MEMORY_MUTATION = "HIDDEN_MEMORY_MUTATION"
IMPURE_PLUGIN = "IMPURE_PLUGIN"

VIOLATION_CODES = (
    KERNEL_TAMPERED,
    HIDDEN_NETWORK,
    HIDDEN_PROCESS,
    DENIED_SOURCE_READ,
    HIDDEN_WRITE,
    HIDDEN_MEMORY_MUTATION,
    IMPURE_PLUGIN,
)
# P17 (T5-005): an actor call the engine did not make.  A plugin that calls a
# model or a tool through a transport window of its own.
HIDDEN_MODEL_CALL = "HIDDEN_MODEL_CALL"
HIDDEN_TOOL_CALL = "HIDDEN_TOOL_CALL"
HIDDEN_CALL_CODES = (HIDDEN_MODEL_CALL, HIDDEN_TOOL_CALL)

ADAPTER = "adapter"
RENDERER = "renderer"
PARSER = "proposal_parser"
WORLD = "world"
TRANSFORM = "visibility_transform"
CODEC = "provider_codec"
DECISION_RULE = "decision_rule"
# the call of a tool actor's tool: TOOL of a mutating tool, TOOL_READ of a
# read-only tool and of every reconciliation
TOOL = "tool"
TOOL_READ = "tool_read"

#: the windows in which a plugin reaches outside the process, and the code of
#: one opened by anything but the engine
_TRANSPORT_WINDOWS = {
    ADAPTER: HIDDEN_MODEL_CALL,
    TOOL: HIDDEN_TOOL_CALL,
    TOOL_READ: HIDDEN_TOOL_CALL,
}

_NETWORK_EVENTS = frozenset(
    {
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
        "socket.getnameinfo",
        "urllib.Request",
        "http.client.connect",
        "ftplib.connect",
        "smtplib.connect",
        "poplib.connect",
        "imaplib.open",
        "nntplib.connect",
        "telnetlib.Telnet.open",
        "webbrowser.open",
    }
)
_PROCESS_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "os.fork",
        "os.forkpty",
        "pty.spawn",
    }
)
_CTYPES_EVENTS = frozenset({"ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function"})
_LISTING_EVENTS = frozenset({"os.listdir", "os.scandir", "glob.glob"})
_WRITE_EVENTS = frozenset(
    {
        "os.remove",
        "os.rename",
        "os.mkdir",
        "os.rmdir",
        "os.truncate",
        "os.chmod",
        "os.link",
        "os.symlink",
        "os.utime",
        "shutil.rmtree",
        "shutil.copyfile",
        "shutil.move",
    }
)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


class ContainmentViolationV2(ExecutionError):
    """A K0 plugin attempted an attack the containment session refuses."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ViolationV2:
    code: str
    event: str
    detail: str
    window: str
    thread: str

    def document(self) -> dict[str, str]:
        return {
            "code": self.code,
            "event": self.event,
            "detail": self.detail,
            "window": self.window,
            "thread": self.thread,
        }


# -- kernel seal ---------------------------------------------------------------

_SEALED_PREFIXES = ("boomvalley_lab.kernel",)

# stdlib primitives the evidence path depends on, pinned when the kernel loads.
_PINNED: tuple[tuple[object, str, object], ...] = tuple(
    (owner, name, getattr(owner, name))
    for owner, names in (
        (builtins, ("open",)),
        (io, ("open",)),
        (os, ("open", "replace", "fsync", "write")),
        (_digest_service.hashlib, ("sha256", "new")),  # the one hashlib user
        (json, ("dumps", "loads")),
        (sys, ("audit", "addaudithook")),
    )
    for name in names
)


@dataclass(frozen=True)
class _Pristine:
    codes: Mapping[str, tuple[CodeType, ...]]
    imports: tuple[tuple[str, str, str], ...]  # (bound name, source module, attribute)
    names: Mapping[str, frozenset[str]]  # "" = module, else class qualname


def _bound_names(body: Sequence[ast.stmt], scope: str, out: dict[str, set[str]]) -> None:
    """Names each module/class namespace binds in source (not in functions)."""

    names = out.setdefault(scope, set())
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            _bound_names(node.body, f"{scope}.{node.name}" if scope else node.name, out)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            for attribute in ("body", "orelse", "finalbody"):
                _bound_names(getattr(node, attribute, []), scope, out)
            for handler in getattr(node, "handlers", []):
                _bound_names(handler.body, scope, out)


_PRISTINE_CACHE: dict[tuple[str, str], _Pristine] = {}


def _nested_codes(code: CodeType) -> Iterator[CodeType]:
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            yield constant
            yield from _nested_codes(constant)


def _pristine(module: ModuleType) -> _Pristine | None:
    """Function code and import bindings compiled from *module*'s source."""

    filename = getattr(module, "__file__", None)
    if not filename or not filename.endswith(".py"):
        return None
    source = Path(filename).read_bytes()
    key = (filename, str(sha256_bytes(source)))
    cached = _PRISTINE_CACHE.get(key)
    if cached is not None:
        return cached
    module_code = compile(source, filename, "exec", optimize=sys.flags.optimize)
    codes: dict[str, list[CodeType]] = {}
    for code in _nested_codes(module_code):
        qualname = code.co_qualname
        if "<" in qualname:  # locals, lambdas, comprehensions
            continue
        if code.co_name == "__annotate__":
            # Python 3.14 compiles each annotated scope's annotations into a
            # function of this name that no namespace binds under it (a class
            # holds it as __annotate_func__, a function on itself): it is the
            # interpreter's, not a function the source defines.
            continue
        codes.setdefault(qualname, []).append(code)
    package = module.__name__ if hasattr(module, "__path__") else module.__name__.rpartition(".")[0]
    imports: list[tuple[str, str, str]] = []
    tree = ast.parse(source, filename)
    names: dict[str, set[str]] = {}
    _bound_names(tree.body, "", names)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        origin = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
        if not origin.startswith("boomvalley_lab"):
            continue
        for alias in node.names:
            if alias.name != "*":
                imports.append((alias.asname or alias.name, origin, alias.name))
    pristine = _Pristine(
        {name: tuple(found) for name, found in codes.items()},
        tuple(imports),
        {scope: frozenset(bound) for scope, bound in names.items()},
    )
    _PRISTINE_CACHE[key] = pristine
    return pristine


def _functions_of(raw: object) -> list[FunctionType] | None:
    """Functions behind a raw namespace value, or None if it has none."""

    if isinstance(raw, (staticmethod, classmethod)):
        raw = raw.__func__
    if isinstance(raw, property):
        found = [_functions_of(part) for part in (raw.fget, raw.fset, raw.fdel) if part]
        return [function for functions in found if functions for function in functions]
    if isinstance(getattr(raw, "func", None), FunctionType):  # cached_property
        raw = raw.func
    for _ in range(16):  # functools.wraps / contextmanager
        if not hasattr(raw, "__wrapped__"):
            break
        raw = raw.__wrapped__
    if isinstance(raw, FunctionType):
        return [raw]
    return None


def _codes_of(raw: object) -> list[CodeType] | None:
    functions = _functions_of(raw)
    return None if functions is None else [function.__code__ for function in functions]


@dataclass(frozen=True)
class _SealEntry:
    owner: object
    name: str
    raw: object
    codes: tuple[tuple[FunctionType, CodeType], ...] = ()


_MISSING = object()


class KernelSealV2:
    """Pristine kernel objects of one session, verified against source code."""

    def __init__(
        self,
        sources: Mapping[str, _Pristine],
        entries: Sequence[_SealEntry],
    ) -> None:
        self._sources = dict(sources)
        self._entries = tuple(entries)
        self.modules = tuple(sorted(sources))

    @classmethod
    def capture(cls) -> KernelSealV2:
        sources = {
            name: pristine
            for name in _sealed_module_names()
            if (pristine := _pristine(sys.modules[name])) is not None
        }
        problems, entries = _inspect(sources)
        if problems:
            raise ContainmentViolationV2(
                KERNEL_TAMPERED,
                "kernel is not pristine before execution: " + "; ".join(problems[:5]),
            )
        return cls(sources, entries)

    def problems(self) -> list[str]:
        found, _ = _inspect(self._sources)
        for entry in self._entries:
            if vars(entry.owner).get(entry.name, _MISSING) is not entry.raw:
                found.append(f"{_label(entry.owner)}.{entry.name} was rebound")
        return found

    def restore(self) -> None:
        for entry in self._entries:
            if vars(entry.owner).get(entry.name, _MISSING) is not entry.raw:
                setattr(entry.owner, entry.name, entry.raw)
            for function, code in entry.codes:
                if function.__code__ is not code:
                    function.__code__ = code


def _label(owner: object) -> str:
    return getattr(owner, "__qualname__", None) or getattr(owner, "__name__", repr(owner))


def _sealed_module_names() -> list[str]:
    names = {
        name
        for name in list(sys.modules)
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _SEALED_PREFIXES)
    }
    for name in list(names):
        pristine = _pristine(sys.modules[name])
        if pristine is not None:
            names.update(origin for _, origin, _ in pristine.imports if origin in sys.modules)
    return sorted(names)


def _resolve(module: ModuleType, qualname: str) -> tuple[object, str, object]:
    owner: object = module
    parts = qualname.split(".")
    raw: object = _MISSING
    for index, part in enumerate(parts):
        raw = vars(owner).get(part, _MISSING)
        if raw is _MISSING:
            break
        if index < len(parts) - 1:
            if not isinstance(raw, type):
                return owner, part, _MISSING
            owner = raw
    return owner, parts[-1], raw


def _inspect(sources: Mapping[str, _Pristine]) -> tuple[list[str], list[_SealEntry]]:
    problems: list[str] = []
    entries: list[_SealEntry] = []
    for module_name, pristine in sources.items():
        module = sys.modules.get(module_name)
        if module is None:
            problems.append(f"{module_name} was unloaded")
            continue
        problems += _injected(vars(module), pristine.names.get("", frozenset()), module_name)
        for scope, known in pristine.names.items():
            if scope:
                _, _, cls = _resolve(module, scope)
                if isinstance(cls, type):
                    problems += _injected(vars(cls), known, f"{module_name}.{scope}")
        for qualname, expected in pristine.codes.items():
            owner, name, raw = _resolve(module, qualname)
            if raw is _MISSING:
                problems.append(f"{module_name}.{qualname} is missing")
                continue
            if not isinstance(raw, type):  # a class body: methods have own qualnames
                live = _codes_of(raw)
                if live is None or not _same_codes(live, expected):
                    problems.append(f"{module_name}.{qualname} is not the source code")
                    continue
            functions = _functions_of(raw) or []
            entries.append(
                _SealEntry(owner, name, raw, tuple((f, f.__code__) for f in functions))
            )
        for bound, origin, attribute in pristine.imports:
            source = sys.modules.get(origin)
            if source is None:
                continue
            expected_value = getattr(source, attribute, _MISSING)
            live_value = vars(module).get(bound, _MISSING)
            if live_value is not expected_value:
                problems.append(f"{module_name}.{bound} is not {origin}.{attribute}")
            else:
                entries.append(_SealEntry(module, bound, live_value))
    for owner, name, original in _PINNED:
        if getattr(owner, name, _MISSING) is not original:
            problems.append(f"{_label(owner)}.{name} is not the pinned stdlib primitive")
        entries.append(_SealEntry(owner, name, original))
    return problems, entries


_STDLIB = tuple(
    os.path.normcase(os.path.abspath(sysconfig.get_paths()[key])) + os.sep
    for key in ("stdlib", "platstdlib")
)


def _foreign_code(code: CodeType) -> bool:
    """Code from a real file outside the stdlib (stdlib machinery is trusted)."""

    filename = code.co_filename
    if filename.startswith("<"):
        return False
    return not os.path.normcase(os.path.abspath(filename)).startswith(_STDLIB)


def _injected(namespace: Mapping[str, Any], known: frozenset[str], where: str) -> list[str]:
    """Callables bound into a sealed namespace that its source does not define.

    Interpreter-generated or stdlib code (dataclass, enum, Protocol machinery)
    is trusted; code from any other file under an undeclared name is an
    injected shadow of a builtin or inherited attribute.
    """

    found = []
    for key, value in list(namespace.items()):
        if key in known or isinstance(value, (type, ModuleType)):
            continue
        codes = _codes_of(value)
        if codes and any(_foreign_code(code) for code in codes):
            found.append(f"{where}.{key} was injected")
    return found


def _same_codes(live: Sequence[CodeType], expected: Sequence[CodeType]) -> bool:
    if len(live) != len(expected):
        return False
    remaining = list(expected)
    for code in live:
        for index, candidate in enumerate(remaining):
            if code == candidate:
                del remaining[index]
                break
        else:
            return False
    return True


# -- what the guard holds (T4-014) ------------------------------------------------

_PRODUCT = "boomvalley_lab"


def _guard_snapshot(session: ContainmentSessionV2) -> tuple[Any, ...]:
    """The callables the guard hook keeps as they are while *session* is armed.

    This module (the checker), every loaded product module the kernel seal does
    not cover, and the session's own instance: module-level callables and
    classes by identity, the callables of the classes those modules define, and
    the code of every function among them.  The other kernel modules stay the
    kernel seal's, which compares them with their source.
    """

    names: list[tuple[dict[str, Any], str, object, str]] = []
    members: list[tuple[type, Any, str, object, str]] = []
    shapes: list[tuple[type, Any, frozenset[str], str]] = []
    codes: list[tuple[FunctionType, CodeType, str]] = []
    for module_name in sorted(sys.modules):
        if module_name != _PRODUCT and not module_name.startswith(_PRODUCT + "."):
            continue
        if module_name != __name__ and any(
            module_name == prefix or module_name.startswith(prefix + ".")
            for prefix in _SEALED_PREFIXES
        ):
            continue
        module = sys.modules[module_name]
        if not isinstance(module, ModuleType):
            continue
        namespace = vars(module)
        for key, value in list(namespace.items()):
            if isinstance(value, ModuleType) or not (isinstance(value, type) or callable(value)):
                continue
            label = f"{module_name}.{key}"
            names.append((namespace, key, value, label))
            if getattr(value, "__module__", None) != module_name:
                continue
            for function in _functions_of(value) or []:
                codes.append((function, function.__code__, label))
            if isinstance(value, type):
                proxy = vars(value)
                shapes.append((value, proxy, frozenset(proxy), label))
                for member, raw in list(proxy.items()):
                    functions = _functions_of(raw)
                    if functions is None:
                        continue
                    members.append((value, proxy, member, raw, f"{label}.{member}"))
                    codes.extend((f, f.__code__, f"{label}.{member}") for f in functions)
    return (
        tuple(names),
        tuple(members),
        tuple(shapes),
        tuple(codes),
        vars(session),
        frozenset(vars(type(session))),
        session.seal,
    )


# -- the audit hook --------------------------------------------------------------

_ACTIVE: ContainmentSessionV2 | None = None
_REGISTRY_LOCK = threading.Lock()
_HOOK_INSTALLED = False
_LOCAL = threading.local()


def _audit(event: str, args: tuple[Any, ...]) -> None:
    session = _ACTIVE
    if session is None or getattr(_LOCAL, "busy", False):
        return
    _LOCAL.busy = True
    try:
        session._on_event(event, args)
    finally:
        _LOCAL.busy = False


def _install_hook() -> None:
    global _HOOK_INSTALLED
    with _REGISTRY_LOCK:
        if not _HOOK_INSTALLED:
            sys.addaudithook(_audit)
            sys.addaudithook(_make_guard())
            _HOOK_INSTALLED = True


# -- the guard hook (T0-016-R110 A1) -------------------------------------------
#
# ``_audit`` decides through plugin-reachable state (the module global
# ``_ACTIVE``, the session's window list, its methods), so a plugin that
# disarms the session first (M06) used to get one connection out before the
# next check.  The guard is a second hook whose state lives only in its own
# closure: the function object is never stored, so it is reachable only from
# its own frame (which CPython does not put in the refused caller's traceback).
# It refuses network, process and ctypes egress whenever a session is armed,
# except network inside the engine's adapter or tool window, and inside plugin windows
# it refuses the introspection that would reach the window token or install a
# competing hook.
# A window is opened with a fresh token that only the window generator holds,
# so a plugin can neither close its window nor disarm the guard.  The guard
# raises builtin PermissionError and touches no patchable Python object, so no
# plugin code runs inside it.
#
# The guard also holds the checker (T4-014): ``arm`` hands it the callables of
# ``_guard_snapshot``, and when the outermost plugin window closes (and on
# ``verify``) it puts back whatever of them was rebound, re-coded, injected or
# shadowed and refuses, so the session's own ``check`` runs as it was written
# however the plugin left it.

_GUARD_EVENT = "boomvalley_lab.containment.guard"
_GUARD_INTROSPECTION = frozenset(
    {
        "gc.get_objects",
        "gc.get_referrers",
        "gc.get_referents",
        "sys._current_frames",
        "sys.settrace",
        "sys.setprofile",
        "sys.monitoring.register_callback",
        "sys.addaudithook",
    }
)
_GUARD_FRAME_ATTRIBUTES = frozenset({"gi_frame", "cr_frame", "ag_frame"})


def _make_guard() -> Callable[[str, tuple[Any, ...]], None]:
    from _thread import get_ident

    network = _NETWORK_EVENTS
    egress = _PROCESS_EVENTS
    ctypes_events = _CTYPES_EVENTS
    introspection = _GUARD_INTROSPECTION
    frame_attributes = _GUARD_FRAME_ATTRIBUTES
    control = _GUARD_EVENT
    transports = frozenset(_TRANSPORT_WINDOWS)
    refused = PermissionError
    exact_str = str
    exact_type = type
    exact_list = list
    size = len
    exact_base = BaseException
    get_name = dict.get
    set_name = dict.__setitem__
    drop_name = dict.pop
    get_member = type(vars(type)).get
    set_member = type.__setattr__
    drop_member = type.__delattr__
    missing = object()
    is_callable = callable
    descriptors = (staticmethod, classmethod, property)
    armed = False
    owner = 0
    window: str | None = None
    token: object = None
    refusals = 0
    last = ""
    held: tuple[Any, ...] | None = None

    def refuse(event: str, where: str) -> None:
        nonlocal refusals, last
        refusals += 1
        last = event + " in " + where
        raise refused("K0 containment guard refused " + last)

    def restored() -> str | None:
        """Put back what the armed session's snapshot holds; the first thing moved."""

        if held is None:
            return None
        names, members, shapes, codes, instance, class_names, seal = held
        found: str | None = None
        for namespace, key, value, label in names:
            if get_name(namespace, key, missing) is not value:
                set_name(namespace, key, value)
                found = found or label + " was rebound"
        for cls, proxy, key, raw, label in members:
            if get_member(proxy, key, missing) is not raw:
                try:
                    set_member(cls, key, raw)
                except exact_base:  # noqa: BLE001 - reported below either way
                    pass
                found = found or label + " was rebound"
        for cls, proxy, keys, label in shapes:
            if size(proxy) != size(keys):
                for key in exact_list(proxy):
                    # the interpreter caches data on a class (``__slotnames__``);
                    # only something that can be called shadows a method
                    added = get_member(proxy, key, missing)
                    if key not in keys and (
                        is_callable(added) or exact_type(added) in descriptors
                    ):
                        try:
                            drop_member(cls, key)
                        except exact_base:  # noqa: BLE001
                            pass
                        found = found or label + "." + key + " was injected"
        for function, code, label in codes:
            if function.__code__ is not code:
                function.__code__ = code
                found = found or label + " was re-coded"
        for key in exact_list(instance):
            if key in class_names:
                drop_name(instance, key, None)
                found = found or "the session's " + key + " was shadowed"
        if get_name(instance, "seal", missing) is not seal:
            set_name(instance, "seal", seal)
            found = found or "the session's kernel seal was replaced"
        return found

    def guard(event: str, args: tuple[Any, ...]) -> None:
        nonlocal armed, owner, window, token, held, refusals, last
        if exact_type(event) is not exact_str:
            return
        if event == "object.__getattr__":
            if armed and size(args) == 2 and exact_type(args[1]) is exact_str:
                if args[1] in frame_attributes and (get_ident() != owner or window is not None):
                    refuse(event + " " + args[1], window or "foreign-thread")
            return
        if event == control:
            operation = args[0] if size(args) else None
            if exact_type(operation) is not exact_str:
                refuse(event, "a malformed control event")
            if operation == "status" and size(args) == 2 and exact_type(args[1]) is exact_list:
                args[1].append((refusals, last))
                return
            if operation == "arm" and size(args) == 2:
                if armed:
                    refuse(event + " arm", "an armed session")
                armed, owner, window, token = True, get_ident(), None, None
                held = args[1]
                return
            if not armed or get_ident() != owner:
                refuse(event + " " + operation, "a foreign thread")
            if operation == "open" and size(args) == 3 and exact_type(args[1]) is exact_str:
                if window is not None:
                    refuse(event + " open", "an open window")
                window, token = args[1], args[2]
                return
            if operation == "close" and size(args) == 2:
                if window is not None and args[1] is token:
                    closing = window
                    window, token = None, None
                    moved = restored()
                    if moved is not None:
                        refuse(moved, closing)
                    return
                if window is None and token is None:
                    return  # already closed (the generator closes idempotently)
                refuse(event + " close", "the plugin window")
            if operation == "verify" and size(args) == 2 and exact_type(args[1]) is exact_list:
                moved = restored()
                if moved is not None:
                    refusals += 1
                    last = moved + " in " + (window or "kernel")
                    args[1].append(moved)
                return
            if operation == "disarm" and size(args) == 1 and window is None:
                armed, owner, held = False, 0, None
                return
            refuse(event + " " + operation, "the plugin window")
        if not armed:
            return
        thread = get_ident()
        where = "foreign-thread" if thread != owner else (window or "kernel")
        if event in network:
            if thread != owner or window not in transports:
                refuse(event, where)
        elif event in egress:
            refuse(event, where)
        elif event in ctypes_events or event in introspection:
            if thread != owner or window is not None:
                refuse(event, where)

    return guard


def _event_path(value: Any) -> str | None:
    if isinstance(value, int) or value is None:
        return None
    try:
        path = os.fspath(value)
    except TypeError:
        return None
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    return os.path.normcase(os.path.abspath(path))


def _is_cache(path: str) -> bool:
    return "__pycache__" in Path(path).parts


def _opens_for_write(args: tuple[Any, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str) and any(letter in mode for letter in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


class ContainmentSessionV2:
    """One armed containment session; at most one per process at a time."""

    def __init__(self, *, denied_sources: Sequence[Path] = ()) -> None:
        roots: set[str] = set()
        for source in denied_sources:
            for form in (os.path.abspath(source), os.path.realpath(source)):
                roots.add(os.path.normcase(form))
        self.denied_sources = tuple(sorted(roots))
        self._policy = self.denied_sources
        self._watch: tuple[Callable[[], Any], Any, str] | None = None
        self.violations: list[ViolationV2] = []
        self._lock = threading.Lock()
        self._thread = threading.get_ident()
        self._windows: list[str] = []
        self.seal: KernelSealV2 | None = None
        self._pristine: dict[int, tuple[object, object | None]] = {}
        self._guarded = False
        self._guard_refusals = 0

    def pristine(self, plugin: object) -> object | None:
        """The plugin as first met in this session (None: not copyable)."""

        known = self._pristine.get(id(plugin))
        if known is None or known[0] is not plugin:
            try:
                clone: object | None = copy.deepcopy(plugin)
            except Exception:  # noqa: BLE001 - invoke_pure refuses a plugin with no copy
                clone = None
            known = (plugin, clone)
            self._pristine[id(plugin)] = known
        return known[1]

    # lifecycle ----------------------------------------------------------------
    def __enter__(self) -> ContainmentSessionV2:
        global _ACTIVE
        _install_hook()
        self.seal = KernelSealV2.capture()
        with _REGISTRY_LOCK:
            if _ACTIVE is not None:
                raise ExecutionError("a K0 containment session is already armed")
            _ACTIVE = self
        try:
            sys.audit(_GUARD_EVENT, "arm", _guard_snapshot(self))
        except BaseException:
            with _REGISTRY_LOCK:
                _ACTIVE = None
            raise
        self._guarded = True
        status: list[tuple[int, str]] = []
        sys.audit(_GUARD_EVENT, "status", status)
        self._guard_refusals = status[0][0]
        return self

    def __exit__(self, *exc_info: object) -> None:
        global _ACTIVE
        with _REGISTRY_LOCK:
            if _ACTIVE is self:
                _ACTIVE = None
        if self._guarded:
            self._guarded = False
            sys.audit(_GUARD_EVENT, "disarm")

    # windows ------------------------------------------------------------------
    @contextmanager
    def window(self, kind: str, plugin_identity: str) -> Iterator[None]:
        if threading.get_ident() != self._thread:
            yield
            return
        depth = len(self._windows)
        hidden = _TRANSPORT_WINDOWS.get(kind)
        if depth and hidden is not None:
            # only the engine opens a transport: this call is a plugin's own
            self._violate(
                hidden, "window",
                f"{kind}:{plugin_identity} was called from inside a plugin window",
                self._windows[-1],
            )
        # The guard window is outermost only; ``emit``, ``control`` and ``token``
        # live in this generator frame alone, so the plugin can neither close the
        # window, forge it nor keep its close from reaching the guard.
        emit, control = sys.audit, _GUARD_EVENT
        token: list[str] | None = [] if depth == 0 else None
        if token is not None:
            emit(control, "open", kind, token)
        self._windows.append(f"{kind}:{plugin_identity}")
        settle = True
        try:
            yield
        except ContainmentViolationV2:
            settle = False
            raise
        except Exception:
            raise  # a recorded violation outranks the plugin's own error (below)
        except BaseException:
            settle = False
            raise
        finally:
            del self._windows[depth:]
            moved: PermissionError | None = None
            if token is not None:
                try:
                    emit(control, "close", token)
                except PermissionError as refusal:
                    # the guard put the checker back and refused what moved it
                    moved = refusal
            if settle:
                self.check()
                if moved is not None:
                    self._record(KERNEL_TAMPERED, "guard", str(moved), kind)
                    raise ContainmentViolationV2(KERNEL_TAMPERED, str(moved))

    def check(self) -> None:
        """Refuse on a recorded violation or a tampered kernel."""

        global _ACTIVE
        problems = self.seal.problems() if self.seal is not None else []
        if _ACTIVE is not self:
            problems.append("the containment session was disarmed")
        if self.denied_sources != self._policy:
            problems.append("the denied-source policy was altered")
        if problems:
            if self.seal is not None:
                self.seal.restore()
            with _REGISTRY_LOCK:
                _ACTIVE = self
            self.denied_sources = self._policy
            self._record(KERNEL_TAMPERED, "seal", "; ".join(problems[:5]))
        status: list[tuple[int, str]] = []
        sys.audit(_GUARD_EVENT, "status", status)
        if status and status[0][0] > self._guard_refusals:
            self._guard_refusals, last = status[0]
            event, _, window = last.partition(" in ")
            code = HIDDEN_NETWORK if event in _NETWORK_EVENTS else (
                HIDDEN_PROCESS if event in _PROCESS_EVENTS or event in _CTYPES_EVENTS
                else KERNEL_TAMPERED
            )
            self._record(code, "guard", f"the guard hook refused {event}", window)
        with self._lock:
            first = self.violations[0] if self.violations else None
        if first is not None:
            raise ContainmentViolationV2(
                first.code, f"{first.event} in {first.window}: {first.detail}"
            )
        if self._watch is not None:
            snapshot, baseline, label = self._watch
            if snapshot() != baseline:
                self._watch = None
                self.refuse(
                    HIDDEN_MEMORY_MUTATION,
                    f"{label} changed engine-owned world state, memory or round values "
                    "outside HandlerResult",
                )

    def watch(self, snapshot: Callable[[], Any] | None, label: str) -> None:
        """Hold engine-owned state immutable until the next ``watch(None, ...)``."""

        self._watch = None if snapshot is None else (snapshot, snapshot(), label)

    def refuse(self, code: str, detail: str) -> None:
        """Record and raise an engine-detected violation."""

        self._record(code, "engine", detail)
        raise ContainmentViolationV2(code, detail)

    # audit events -------------------------------------------------------------
    def _current_window(self) -> tuple[bool, str]:
        if threading.get_ident() != self._thread:
            return True, "foreign-thread"
        if self._windows:
            return True, self._windows[-1]
        return False, "kernel"

    def open_window(self) -> str | None:
        """The plugin window the caller runs in (None: engine code)."""

        inside, window = self._current_window()
        return window if inside else None

    def denies(self, source: Path | str) -> bool:
        """Whether plugin windows refuse direct reads of *source*."""

        return all(
            self._denied(os.path.normcase(form))
            for form in (os.path.abspath(source), os.path.realpath(source))
        )

    def _denied(self, path: str) -> bool:
        for root in self.denied_sources:
            if path == root or path.startswith(root.rstrip(os.sep) + os.sep):
                return True
        return False

    def _on_event(self, event: str, args: tuple[Any, ...]) -> None:
        in_plugin, window = self._current_window()
        kind = window.partition(":")[0]
        transport = in_plugin and kind in _TRANSPORT_WINDOWS
        # a mutating tool changes its own resource; the run's evidence and the
        # denied sources are never a tool's resource
        writes = in_plugin and kind == TOOL
        if event in _NETWORK_EVENTS:
            if not transport:
                self._violate(HIDDEN_NETWORK, event, _describe(args), window)
        elif event in _PROCESS_EVENTS:
            self._violate(HIDDEN_PROCESS, event, _describe(args), window)
        elif event in _CTYPES_EVENTS:
            if in_plugin and not transport:
                self._violate(HIDDEN_PROCESS, event, _describe(args), window)
        elif not in_plugin:
            return
        elif event == "open":
            path = _event_path(args[0] if args else None)
            if path is None:
                return
            if _opens_for_write(args):
                if self._denied(path) if writes else not _is_cache(path):
                    self._violate(HIDDEN_WRITE, event, path, window)
            elif self._denied(path):
                self._violate(DENIED_SOURCE_READ, event, path, window)
        elif event in _LISTING_EVENTS:
            path = _event_path(args[0] if args else ".")
            if path is not None and self._denied(path):
                self._violate(DENIED_SOURCE_READ, event, path, window)
        elif event in _WRITE_EVENTS:
            path = _event_path(args[0] if args else None)
            if writes and path is not None:
                if self._denied(path):
                    self._violate(HIDDEN_WRITE, event, path, window)
            elif path is None or not _is_cache(path):
                self._violate(HIDDEN_WRITE, event, str(path), window)

    def _record(self, code: str, event: str, detail: str, window: str = "kernel") -> ViolationV2:
        thread = "engine" if threading.get_ident() == self._thread else "foreign"
        violation = ViolationV2(code, event, detail, window, thread)
        with self._lock:
            self.violations.append(violation)
        return violation

    def _violate(self, code: str, event: str, detail: str, window: str) -> None:
        self._record(code, event, detail, window)
        raise ContainmentViolationV2(code, f"{event} in {window}: {detail}")


def _describe(args: tuple[Any, ...]) -> str:
    text = ", ".join(repr(arg) for arg in args[1:] or args)
    return text[:200]


def active_session() -> ContainmentSessionV2 | None:
    return _ACTIVE


@contextmanager
def plugin_window(kind: str, plugin_identity: str) -> Iterator[None]:
    """Run one plugin call contained; a no-op outside an armed session."""

    session = _ACTIVE
    if session is None:
        yield
        return
    with session.window(kind, plugin_identity):
        yield


T = TypeVar("T")
P = TypeVar("P")


def contained_load(load: Callable[[], T]) -> T:
    """Import and construct installed plugins under an armed session (T4-014).

    A plugin module runs when it is imported, before any plugin window exists.
    Armed, that import can open no connection and start no process, and the
    guard reports - and puts back - every product callable it rebound, so a
    plugin that patches the product at import is refused instead of bound.
    """

    emit, control = sys.audit, _GUARD_EVENT
    moved: list[str] = []
    with ContainmentSessionV2() as session:
        check = session.check
        try:
            loaded = load()
        finally:
            emit(control, "verify", moved)
        if moved:
            raise ContainmentViolationV2(
                KERNEL_TAMPERED, "loading changed the product: " + "; ".join(moved[:5])
            )
        check()
    return loaded


def _fingerprint(value: Any) -> bytes:
    try:
        return canonical_bytes(value)
    except Exception:  # noqa: BLE001 - a non-canonical value is compared by repr
        return repr(value).encode("utf-8", "backslashreplace")


def _without_hidden_rng(
    session: ContainmentSessionV2, kind: str, identity: str, call: Callable[[P], T], plugin: P
) -> T:
    """One call of a pure plugin that may reach no randomness of its own (SV-05)."""

    if kind == WORLD:
        return call(plugin)  # held, under its declared RNG policy, where it is applied
    try:
        with hidden_rng_refused(identity, kind=kind):
            return call(plugin)
    except ExecutionError as error:
        if getattr(error, "code", None) != RNG_POLICY_INVALID:
            raise
        detail = str(error).removeprefix(f"{RNG_POLICY_INVALID}: ")
        session.refuse(IMPURE_PLUGIN, detail)
        raise  # unreachable: refuse raises


def invoke_pure(
    kind: str,
    plugin: P,
    call: Callable[[P], T],
    document: Callable[[T], Any],
) -> T:
    """Call a pure plugin contained and replay it on its pristine copy.

    The pristine copy is a deep copy taken the first time the session meets
    the plugin; the live plugin is still called exactly once.  State the
    plugin carried from earlier calls (instance or module level) makes the
    replay differ, and the differing output is refused as IMPURE_PLUGIN.

    A replay only sees randomness whose two draws differ.  So both calls are
    made with hidden plugin RNG held shut (SV-05): a plugin that reached the
    process generator, an unseeded generator or OS entropy is refused as
    IMPURE_PLUGIN whatever it returned.  A World is held by its own RNG policy
    inside its call (``world_rng.apply_under_policy``, BVL-WORLD-013).
    """

    session = _ACTIVE
    if session is None:
        return call(plugin)
    identity = str(getattr(plugin, "plugin_identity", type(plugin).__qualname__))
    pristine = session.pristine(plugin)
    if pristine is None:
        # SV-03: the live plugin replayed on itself repeats whatever state it carries
        session.refuse(
            IMPURE_PLUGIN,
            f"{kind} {identity} cannot be copied, so it has no pristine state to be "
            "replayed from; its output cannot be shown free of undeclared state",
        )
    with session.window(kind, identity):
        first = _without_hidden_rng(session, kind, identity, call, plugin)
    with session.window(kind, identity):
        second = _without_hidden_rng(session, kind, identity, call, copy.deepcopy(pristine))
    if _fingerprint(document(first)) != _fingerprint(document(second)):
        session.refuse(
            IMPURE_PLUGIN,
            f"{kind} {identity} gave a different result when replayed from its "
            "pristine state on the same input; its output depends on undeclared state",
        )
    return first


def state_fingerprint(
    world_state: Mapping[str, Any],
    memory: Mapping[str, Any],
    current_round: Mapping[str, Any],
) -> tuple[bytes, bytes, tuple[tuple[str, int], ...]]:
    return (
        _fingerprint(dict(world_state)),
        _fingerprint(dict(memory)),
        tuple((key, id(value)) for key, value in current_round.items()),
    )
