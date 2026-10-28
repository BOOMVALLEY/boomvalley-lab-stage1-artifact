"""The study-neutral reference plugins the `bvl` lifecycle ships (T1-010).

A `bvl-study-1` declaration names its plugins by registered identity; this
installation resolves them from one closed catalog, registered in-process into
the run's ``PluginRegistryV1`` (P03), so every one is bound into the run's
PluginSetIdentity with its code identity and config digest.  No declaration
supplies a module path, and no plugin here knows a study:

    bvl.scripted-adapter:1       ADAPTER          deterministic local provider:
                                                  answers the declared response
                                                  of the request's model for the
                                                  rendered round (config-bound)
    bvl.json-renderer:1          RENDERER         the actor's authorized view as
                                                  one canonical JSON message (no
                                                  upstream dataflow: another
                                                  actor's output only as a granted
                                                  actor_output source, T2-001)
    bvl.json-proposal-parser:1   PROPOSAL_PARSER  one UTF-8 JSON object
    bvl.ledger-world:1           WORLD            the executed action merged into
                                                  the World state; the outcome is
                                                  the executed action (state
                                                  schema bvl.ledger-state:1 and
                                                  action schema
                                                  bvl.ledger-action:1, both open)
    bvl.tally-world:1            WORLD            an integer ``amount`` added to
                                                  ``total`` and counted in
                                                  ``applied``; anything else is
                                                  inadmissible and changes
                                                  nothing (state schema
                                                  bvl.tally-state:1, closed;
                                                  action schema
                                                  bvl.tally-action:1, an integer
                                                  ``amount``); NO_ACTION
                                                  means NO_TRANSITION
    bvl.shock-world:1            WORLD            the tally World under an
                                                  exogenous integer ``shock`` in
                                                  [-3, 3] drawn from the declared
                                                  RNG and stated as a ``shock``
                                                  event (state schema
                                                  bvl.shock-state:1, action
                                                  schema bvl.shock-action:1; rng
                                                  policy SEEDED)

Every catalog World declares the schema version of its state (T3-001) and of
the actions it accepts (T3-003), so a study may freeze it as the plan's World
contract.  Under that contract an action outside the action schema never
reaches the World (BVL-WORLD-004); the tally World's own INADMISSIBLE verdict
is what a contract-less (K0) plan still observes.  Each also states its
progression (T3-004): whether it executed an action and - none here - its
exogenous events.  The tally World's contract freezes NO_ACTION as
NO_TRANSITION (a NO_ACTION decision is a committed transition that keeps the
state); the ledger World declares no NO_ACTION meaning, so a NO_ACTION
decision never reaches it (BVL-WORLD-008).  Both are functions of the serialized
state, the handed input and the seed and hold no state of their own, so an
independent instance replays their transitions (T3-005, ``bvl-world-replay-1``).
Both are DETERMINISTIC (T3-006): the seed they are handed changes nothing.  The
shock World is the catalog's stochastic World: its contract freezes the SEEDED
RNG policy, it is handed the declared RNG of its transition's bound seed - never
the seed - and its only randomness is what it draws there.

The Worlds above are study-neutral references.  A domain World - one that owns
a domain rule making CLIPPED and INADMISSIBLE reachable under its contract - is
not written here: the catalog registers every World of ``boomvalley_lab.domains``
by its plugin identity, each bound to its own module's code identity, and names
none of them (T3-008).  This module and the lifecycle know no domain.

A provider - an adapter that leaves the process - is not written here either:
the catalog registers every entry of ``boomvalley_lab.providers`` by its plugin
identity, bound to its own module's code identity, with the ERF (the profile
options it consumes) and the external-IO / stochastic facts its class states,
and names none of them (T4-010).  A provider that declares ``require_profile``
holds each profile that names it to its config and option domains when the
study is compiled, so a misdeclared provider is refused before a run exists.

A human channel - how a request reaches a person and the answer comes back -
is a ``human_channel`` plugin (P17, T5-001).  This build ships one reference:

    bvl.operator-entry-channel:1  HUMAN_CHANNEL   an operator shows the request
                                                  to the participant and enters
                                                  the answer; it carries text
                                                  and attests OPERATOR_ENTERED,
                                                  never more

A channel states what it carries and the strongest provenance it can attest
(``MODALITIES``, ``PROVENANCE_GRADE``); a human actor contract is held to
both when the study is compiled (BVL-HUMAN-002), and how its exchanges travel
(``TRANSPORT``): the operator-entry channel's travel over the kernel-owned desk
(T5-002, ``kernel.waiting``), where the operator finds the request and enters
the answer.  A channel is not a
catalog plugin of every run: ``plugin_registry(config, channels=...)``
registers exactly the channels a study's human actor contracts name, so the
registry - and the PluginSetIdentity - of a study without human actors is
what it was.

A tool - an external capability a tool actor answers through - is a ``tool``
plugin (P17, T5-003 / T5-004).  This build ships three references
(``lifecycle/tools.py``), one per side effect:

    bvl.table-lookup-tool:1     TOOL  READ_ONLY  NONE               ``lookup``
    bvl.record-append-tool:1    TOOL  MUTATING   IDEMPOTENT_BY_KEY  ``append``
    bvl.notice-dispatch-tool:1  TOOL  MUTATING   IRREVERSIBLE       ``dispatch``

A tool states its effect, its side effect and, per operation, the types of its
arguments and result (``EFFECT``, ``SIDE_EFFECT``, ``OPERATIONS``); a tool
actor contract is held to all three when the study is compiled
(BVL-TOOL-002).  A registered reference is not bound to a site and cannot be
called: the journaled call is ``kernel/tool_call.py`` and a run binds its
tools to the site it is given (``lifecycle.gated``, ``--tool-site``, T5-007).
Like a channel, a tool joins a registry only when a study's
tool actor contracts name it (``plugin_registry(config, tools=...)``).

An installed plugin - one a distribution outside this product advertises under
the ``boomvalley_lab.plugins`` entry-point group - joins the same registry
(T4-011, P03): ``plugin_registry(config, load=...)`` registers every installed
entry point after the catalog, through the kernel's entry-point rules (the
loaded factory is the advertised one, the descriptor's plugin id the entry-point
name, its code identity the digest of the factory's module), so the plugin is
bound into the PluginSetIdentity with its distribution and version.  *load* is
injected by the CLI: nothing here imports.  Only the plugin types whose author
contract is published (``boomvalley_lab.plugin_api``) are admitted; an entry
point that does not load, breaks a rule, claims a catalog identity or provides
another type is ``BVL-LIFE-010`` for every study of that installation, before
anything is written.  Without *load* the registry is the catalog and its
identity is what it was.

An installed plugin's module runs when it is imported, so the import and the
factory call happen under an armed containment session (T4-014,
``kernel.containment.contained_load``): a module that opens a connection,
starts a process or rebinds a product callable while it loads is
``BVL-LIFE-010`` as well, and the product is put back.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from boomvalley_lab.core import strict_json
from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.domains import WORLDS as DOMAIN_WORLDS
from boomvalley_lab.kernel.adapter2 import ActorResponseV2
from boomvalley_lab.kernel.containment import ContainmentViolationV2, contained_load
from boomvalley_lab.kernel.package_binding import (
    EntryPointLoader,
    installed_plugin_entry_points,
    module_code_identity,
)
from boomvalley_lab.kernel.pipeline import RenderingV1
from boomvalley_lab.kernel.plugin_registry import (
    PluginDescriptorV1,
    PluginRegistryV1,
    PluginType,
)
from boomvalley_lab.kernel.proposals import ProposalSyntaxError
from boomvalley_lab.kernel.request import RequestV2
from boomvalley_lab.kernel.world import (
    NO_ACTION_INPUT,
    NO_ACTION_VERDICT,
    NO_TRANSITION,
    SEEDED,
    DeclaredRng,
    WorldActionSchemaV1,
    WorldProgressionV1,
    WorldRngPolicyV1,
    WorldStateSchemaV1,
    WorldTransition,
)
from boomvalley_lab.lifecycle.tools import (
    NoticeDispatchToolV1,
    RecordAppendToolV1,
    TableLookupToolV1,
)
from boomvalley_lab.providers import PROVIDERS

SCRIPTED_ADAPTER = "bvl.scripted-adapter:1"
OPERATOR_ENTRY_CHANNEL = "bvl.operator-entry-channel:1"
TABLE_LOOKUP_TOOL = "bvl.table-lookup-tool:1"
RECORD_APPEND_TOOL = "bvl.record-append-tool:1"
NOTICE_DISPATCH_TOOL = "bvl.notice-dispatch-tool:1"
JSON_RENDERER = "bvl.json-renderer:1"
JSON_PARSER = "bvl.json-proposal-parser:1"
LEDGER_WORLD = "bvl.ledger-world:1"
TALLY_WORLD = "bvl.tally-world:1"
SHOCK_WORLD = "bvl.shock-world:1"
LEDGER_STATE = WorldStateSchemaV1("bvl.ledger-state", 1, {}, open=True)
TALLY_STATE = WorldStateSchemaV1("bvl.tally-state", 1, {"applied": "integer", "total": "integer"})
LEDGER_ACTION = WorldActionSchemaV1("bvl.ledger-action", 1, {}, open=True)
TALLY_ACTION = WorldActionSchemaV1("bvl.tally-action", 1, {"amount": "integer"})
TALLY_PROGRESSION = WorldProgressionV1(no_action=NO_TRANSITION)
SHOCK_STATE = WorldStateSchemaV1("bvl.shock-state", 1, {"applied": "integer", "total": "integer"})
SHOCK_ACTION = WorldActionSchemaV1("bvl.shock-action", 1, {"amount": "integer"})
SHOCK_EVENT = "shock"
SHOCK_PROGRESSION = WorldProgressionV1(exogenous_events=(SHOCK_EVENT,))
SHOCK_RNG = WorldRngPolicyV1(SEEDED)
SHOCK_SPREAD = 3
ANY_ROUND = "*"
INSTALLED_PLUGIN_REFUSED = "BVL-LIFE-010"
#: the plugin types an installed plugin may provide: those with a published
#: author contract (``boomvalley_lab.plugin_api``)
INSTALLED_TYPES = frozenset({PluginType.WORLD})


def _content(value: Any) -> bytes:
    """A declared response: a string is sent as its UTF-8 bytes, anything else as JSON."""

    return value.encode("utf-8") if isinstance(value, str) else canonical_json(value).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class ScriptedAdapterV1:
    """Deterministic local provider: ``responses[model][round | "*"]``.

    The round is read from the reference renderer's message, so a resumed call
    receives the same answer a first attempt would have.
    """

    responses: Mapping[str, Mapping[str, Any]]
    plugin_identity: str = SCRIPTED_ADAPTER

    def invoke(self, request: RequestV2) -> ActorResponseV2:
        script = self.responses.get(request.model_identity)
        if script is None:
            raise DeclarationError(f"no scripted responses for model {request.model_identity!r}")
        rendered = json.loads(request.messages[-1]["content"])
        key = str(rendered.get("round"))
        if key not in script and ANY_ROUND not in script:
            raise DeclarationError(
                f"model {request.model_identity!r} has no scripted response for round {key}"
            )
        return ActorResponseV2(
            content=_content(script.get(key, script.get(ANY_ROUND))),
            model_identity=request.model_identity,
            adapter_provenance=f"{SCRIPTED_ADAPTER}:local",
        )


@dataclass(frozen=True)
class JsonRendererV1:
    """P05 renderer: the actor, round, World state, memory and authorized
    information (frozen sources and granted actor outputs) as one canonical
    JSON user message."""

    plugin_identity: str = JSON_RENDERER

    def render(self, node, context, *, observation=None) -> RenderingV1:  # noqa: ANN001
        document: dict[str, Any] = {
            "actor": node.config["actor"],
            "round": context.round_index,
            "world": dict(context.world_state),
        }
        if context.memory:
            document["memory"] = dict(context.memory)
        if observation is not None and observation.source_ids:
            document["information"] = {
                source: observation.text(source) for source in observation.source_ids
            }
        return RenderingV1(({"role": "user", "content": canonical_json(document)},))


@dataclass(frozen=True)
class JsonProposalParserV1:
    """P06 parser: one UTF-8 JSON object; anything else is a syntax verdict."""

    plugin_identity: str = JSON_PARSER

    def parse(self, content: bytes, config: Mapping[str, Any]) -> Mapping[str, Any]:
        del config
        try:
            # strict (SV-04): an answer that states a member twice, or a constant
            # that is no JSON number, does not say which value it means
            value = strict_json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, strict_json.MalformedJSON) as error:
            raise ProposalSyntaxError(f"not a UTF-8 JSON document: {error}") from error
        if not isinstance(value, dict):
            raise ProposalSyntaxError(f"JSON {type(value).__name__} is not an object")
        return value


@dataclass(frozen=True)
class LedgerWorldV1:
    """The executed action is merged into the state; nothing is inadmissible."""

    plugin_identity: str = LEDGER_WORLD
    state_schema: WorldStateSchemaV1 = LEDGER_STATE
    action_schema: WorldActionSchemaV1 = LEDGER_ACTION

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any], *, seed: int
    ) -> WorldTransition:
        del seed
        action = dict(requested_action)
        return WorldTransition(
            requested_action=action,
            admissibility_verdict="ADMISSIBLE",
            admissible_action=action,
            executed_action=action,
            pre_state=dict(state),
            post_state={**dict(state), **action},
            outcome=action,
            executed=True,
        )


@dataclass(frozen=True)
class TallyWorldV1:
    """A typed state: an integer ``amount`` is added to ``total`` and counted."""

    plugin_identity: str = TALLY_WORLD
    state_schema: WorldStateSchemaV1 = TALLY_STATE
    action_schema: WorldActionSchemaV1 = TALLY_ACTION
    progression: WorldProgressionV1 = TALLY_PROGRESSION

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any] | None, *, seed: int
    ) -> WorldTransition:
        del seed
        if requested_action is None:  # NO_ACTION: no transition of the state
            return WorldTransition(
                requested_action={},
                admissibility_verdict=NO_ACTION_VERDICT,
                admissible_action={},
                executed_action={},
                pre_state=dict(state),
                post_state=dict(state),
                outcome={"applied": False, "total": state["total"]},
                executed=False,
                action_input=NO_ACTION_INPUT,
            )
        requested = dict(requested_action)
        amount = requested.get("amount")
        admissible = isinstance(amount, int) and not isinstance(amount, bool)
        executed = {"amount": amount} if admissible else {}
        post = dict(state)
        if admissible:
            post = {"applied": state["applied"] + 1, "total": state["total"] + amount}
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict="ADMISSIBLE" if admissible else "INADMISSIBLE",
            admissible_action=executed,
            executed_action=executed,
            pre_state=dict(state),
            post_state=post,
            outcome={"applied": admissible, "total": post["total"]},
            executed=admissible,
        )


@dataclass(frozen=True)
class ShockWorldV1:
    """The tally World under an exogenous shock drawn from the declared RNG."""

    plugin_identity: str = SHOCK_WORLD
    state_schema: WorldStateSchemaV1 = SHOCK_STATE
    action_schema: WorldActionSchemaV1 = SHOCK_ACTION
    progression: WorldProgressionV1 = SHOCK_PROGRESSION
    rng: WorldRngPolicyV1 = SHOCK_RNG

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any], *, rng: DeclaredRng
    ) -> WorldTransition:
        requested = dict(requested_action)
        amount = requested.get("amount")
        admissible = isinstance(amount, int) and not isinstance(amount, bool)
        executed = {"amount": amount} if admissible else {}
        post, events, shock = dict(state), (), 0
        if admissible:  # an inadmissible action draws nothing and changes nothing
            shock = rng.randbelow(2 * SHOCK_SPREAD + 1) - SHOCK_SPREAD
            post = {"applied": state["applied"] + 1, "total": state["total"] + amount + shock}
            events = ({"event": SHOCK_EVENT, "detail": {"shock": shock}},)
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict="ADMISSIBLE" if admissible else "INADMISSIBLE",
            admissible_action=executed,
            executed_action=executed,
            pre_state=dict(state),
            post_state=post,
            outcome={"applied": admissible, "shock": shock, "total": post["total"]},
            executed=admissible,
            exogenous_events=events,
        )


class OperatorEntryChannelV1:
    """An operator relays the request and enters the participant's answer."""

    MODALITIES = frozenset({"text"})
    PROVENANCE_GRADE = "OPERATOR_ENTERED"
    TRANSPORT = "desk"


@dataclass(frozen=True)
class _Entry:
    plugin_type: PluginType
    factory: Any
    configurable: bool = False
    erf: tuple[str, ...] = field(default_factory=tuple)
    external_io: bool = False
    stochastic: bool = False
    # plugin config -> implementation, for a provider (T4-010)
    configure: Any = None


def _scripted_config(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    responses = config.get("responses") if isinstance(config, Mapping) else None
    if set(config) != {"responses"} or not isinstance(responses, Mapping) or not all(
        isinstance(model, str) and isinstance(script, Mapping) and script
        for model, script in responses.items()
    ):
        raise DeclarationError(
            f"{SCRIPTED_ADAPTER} config is {{'responses': {{model: {{round | '*': response}}}}}}"
        )
    return {model: dict(script) for model, script in responses.items()}


CATALOG: Mapping[str, _Entry] = {
    SCRIPTED_ADAPTER: _Entry(PluginType.ADAPTER, ScriptedAdapterV1, configurable=True),
    JSON_RENDERER: _Entry(PluginType.RENDERER, JsonRendererV1),
    JSON_PARSER: _Entry(PluginType.PROPOSAL_PARSER, JsonProposalParserV1),
    LEDGER_WORLD: _Entry(PluginType.WORLD, LedgerWorldV1),
    TALLY_WORLD: _Entry(PluginType.WORLD, TallyWorldV1),
    SHOCK_WORLD: _Entry(PluginType.WORLD, ShockWorldV1),
    **{
        plugin_id: _Entry(PluginType.WORLD, factory)
        for plugin_id, factory in DOMAIN_WORLDS.items()
    },
    **{
        plugin_id: _Entry(
            PluginType.ADAPTER, provider, configurable=True, erf=tuple(provider.ERF),
            external_io=provider.EXTERNAL_IO, stochastic=provider.STOCHASTIC,
            configure=provider.from_config,
        )
        for plugin_id, provider in PROVIDERS.items()
    },
}


#: the human channels this build ships; one joins a registry only when a study's
#: human actor contracts name it (T5-001)
CHANNELS: Mapping[str, _Entry] = {
    OPERATOR_ENTRY_CHANNEL: _Entry(PluginType.HUMAN_CHANNEL, OperatorEntryChannelV1),
}


#: the tools this build ships; one joins a registry only when a study's tool
#: actor contracts name it (T5-003); one per side effect (T5-004)
TOOLS: Mapping[str, _Entry] = {
    TABLE_LOOKUP_TOOL: _Entry(PluginType.TOOL, TableLookupToolV1, external_io=True),
    RECORD_APPEND_TOOL: _Entry(PluginType.TOOL, RecordAppendToolV1, external_io=True),
    NOTICE_DISPATCH_TOOL: _Entry(PluginType.TOOL, NoticeDispatchToolV1, external_io=True),
}


def _refused(detail: str) -> DeclarationError:
    return DeclarationError(
        f"{INSTALLED_PLUGIN_REFUSED} an installed plugin is refused: {detail}",
        code=INSTALLED_PLUGIN_REFUSED,
    )


def _register_installed(
    registry: PluginRegistryV1, load: EntryPointLoader, config: Mapping[str, Mapping[str, Any]]
) -> None:
    """Every installed entry point, under the kernel's rules and the published types."""

    def loaded(entry: Any) -> object:
        try:
            return load(entry)
        except Exception as error:  # whatever an import raises is a refusal
            raise _refused(
                f"entry point {entry.name!r} = {entry.value!r} does not load: "
                f"{type(error).__name__}: {error}"
            ) from error

    try:
        if installed_plugin_entry_points():
            # a plugin module runs when it is imported: armed, like its calls (T4-014)
            names = contained_load(
                lambda: registry.register_entry_points(load=loaded, config=config)
            )
        else:
            names = registry.register_entry_points(load=loaded, config=config)
    except ContainmentViolationV2 as violation:
        raise _refused(
            f"loading the installed plugins broke containment: {violation}"
        ) from violation
    except DeclarationError as error:
        if error.code == INSTALLED_PLUGIN_REFUSED:
            raise
        raise _refused(str(error)) from error
    except Exception as error:  # a factory that raises registers nothing
        raise _refused(f"a plugin factory failed: {type(error).__name__}: {error}") from error
    for name in names:
        plugin_type = registry.descriptor(name).plugin_type
        if plugin_type not in INSTALLED_TYPES:
            raise _refused(
                f"plugin {name!r} is a {plugin_type.value}; the published author contract "
                f"covers {sorted(kind.value for kind in INSTALLED_TYPES)}"
            )


def plugin_registry(
    config: Mapping[str, Mapping[str, Any]],
    load: EntryPointLoader | None = None,
    channels: Sequence[str] = (),
    tools: Sequence[str] = (),
) -> PluginRegistryV1:
    """Every catalog plugin, registered with its declared config, and - given
    *load* - every installed plugin; config names one of them and nothing else.
    *channels* are the human channels the study's contracts name: the shipped
    ones among them are registered (another name stays unregistered and is
    refused where the study resolves it); *tools* likewise the tools its tool
    actor contracts name."""

    try:
        installed = set() if load is None else {
            bound.name for bound, _ in installed_plugin_entry_points()
        }
    except DeclarationError as error:
        raise _refused(str(error)) from error
    unknown = sorted(set(config) - set(CATALOG) - installed)
    if unknown:
        raise DeclarationError(f"plugin config names plugins this build does not ship: {unknown}")
    registry = PluginRegistryV1()
    for plugin_id, entry in CATALOG.items():
        given = dict(config.get(plugin_id, {}))
        if given and not entry.configurable:
            raise DeclarationError(f"plugin {plugin_id!r} takes no config")
        implementation = (
            entry.configure(given) if entry.configure is not None
            else entry.factory(_scripted_config(given)) if plugin_id == SCRIPTED_ADAPTER and given
            else entry.factory({}) if plugin_id == SCRIPTED_ADAPTER else entry.factory()
        )
        descriptor = PluginDescriptorV1(
            plugin_id, entry.plugin_type, "1", "1", module_code_identity(entry.factory),
            erf=entry.erf, external_io=entry.external_io, stochastic=entry.stochastic,
        )
        registry.register(descriptor, implementation, config=given)
    named = {
        **{name: CHANNELS[name] for name in set(channels) & set(CHANNELS)},
        **{name: TOOLS[name] for name in set(tools) & set(TOOLS)},
    }
    for plugin_id, entry in sorted(named.items()):
        registry.register(
            PluginDescriptorV1(
                plugin_id, entry.plugin_type, "1", "1", module_code_identity(entry.factory),
                external_io=entry.external_io,
            ),
            entry.factory(),
            config={},
        )
    if load is not None:
        _register_installed(
            registry, load, {name: config[name] for name in config if name in installed}
        )
    return registry


def resolved(registry: PluginRegistryV1, plugin_type: PluginType) -> dict[str, Any]:
    """plugin identity -> implementation, for one plugin type."""

    return {
        descriptor.plugin_id: registry.resolve(descriptor.plugin_id, plugin_type)
        for descriptor in registry.descriptors()
        if descriptor.plugin_type is plugin_type
    }
