"""P16 Memory Artifact lifecycle (T4-003).

Memory is explicit evidence, and the only way it reaches an actor is a
declared P05 ``memory_artifact`` source:

    World transition (committed)          the declared source evidence
      -> registered memory transform      ``builtin.outcome-memory-v2:1``
      -> MemoryArtifact                   owner / key / scope / retention /
                                          validity interval; evidence + journal
      -> P05 ``memory_artifact`` source   default-deny, granted per actor
      -> a later round's observation      request-2 names the exact artifacts

A ``memory_update`` node declares the lifecycle in its config:

    {"owner": <plan actor>, "key": <name>, "scope": "episode",
     "retention": <rounds >= 1>, "transform": "builtin.outcome-memory-v2:1"}

The artifact produced in round *r* is valid for rounds ``r+1 .. r+retention``
of the episode that produced it and of no other (episode isolation is the
default, P16 13.4).  It is produced only after its source evidence exists: a
round a timed contract cut before its World transition (T4-002) produces no
memory, and one cut after it produces none either - no later observation of
the episode exists to consume it.

Under the lifecycle nothing else carries memory: the plan has no
``initial_memory``, the engine keeps no memory dict (a handler returning one
is BVL-ROUND-008), and a renderer's context holds neither memory nor the
artifact ledger.  A ``memory_update`` node without ``scope`` keeps the K0
spike semantics (``boomvalley-lab-memory-artifact-1``, plan bytes unchanged);
the two are never mixed in one plan.

Cross-episode scope, reset and regime change (T4-004, P16 13.4 / 13.5)

Episode isolation stays the default.  A node opts out of it only by declaring
every part of the carry in its config:

    {"owner": ..., "key": ..., "retention": ..., "transform": ...,
     "scope": "cross_episode",
     "carry": {"episodes": [<episode key>, ...],     producing / consuming
                                                     episodes, in order
               "reset_before": [<episode key>, ...]},  the reset boundaries
     "regime_change": "retain" | "reset"}            the regime-change interaction

An artifact produced in episode *p* is, besides its rounds of *p*, observable
in every round of the carry's later episodes up to the next reset boundary: an
episode named in ``reset_before`` opens without any memory recorded before it.
The run's ExperimentSchedule must order the carry's episodes as declared
(BVL-ROUND-011), and the carry never leaves the run: the engine rebuilds it
from the run's own committed evidence and from nothing else.

``regime_change`` is what a declared exogenous regime event of the plan's
World (``bvl-world-progression-2``) does to the node's memory.  Under
``reset`` an artifact recorded before a regime-change transition is observable
in no round after that transition's round; under ``retain`` it is kept.  A
node of ``scope: "episode"`` may declare it too.  The World state itself is
never carried: every episode opens on the plan's initial state.

A node declaring ``regime_change`` produces ``boomvalley-lab-memory-artifact-3``,
which also binds its episode key, the interaction and the consuming episodes
(``valid.episodes``).  A node declaring none keeps artifact-2 and its bytes.

This module is pure: the engine, both package verifiers' BVL side and the
tests derive the artifact, its validity and the observed source content from
the same functions.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR, ProtocolNode
from boomvalley_lab.kernel.rounds import (
    CROSS_EPISODE_STATE_UNDECLARED,
    HIDDEN_ACTOR_MEMORY,
    MEMORY_SCOPE_INVALID,
    MEMORY_SOURCE_MISSING,
    RoundError,
)

MEMORY_ARTIFACT_SCHEMA_V1 = "boomvalley-lab-memory-artifact-1"
MEMORY_ARTIFACT_SCHEMA_V2 = "boomvalley-lab-memory-artifact-2"
MEMORY_ARTIFACT_SCHEMA_V3 = "boomvalley-lab-memory-artifact-3"  # T4-004
MEMORY_OBSERVATION_SCHEMA = "bvl-memory-observation-1"
MEMORY_CHECK = "memory_artifact_lifecycle_is_explicit_p05_source"

OUTCOME_TRANSFORM = "builtin.outcome-memory-v2:1"
MEMORY_TRANSFORMS = frozenset({OUTCOME_TRANSFORM})
SCOPE_EPISODE = "episode"
SCOPE_CROSS_EPISODE = "cross_episode"
MEMORY_SCOPES = (SCOPE_EPISODE, SCOPE_CROSS_EPISODE)
REGIME_RETAIN, REGIME_RESET = "retain", "reset"
REGIME_INTERACTIONS = (REGIME_RETAIN, REGIME_RESET)

SPIKE_KEYS = frozenset({"owner", "key"})
LIFECYCLE_KEYS = frozenset({"owner", "key", "scope", "retention", "transform"})
# T4-004: the regime-change interaction (either scope) and the carry (cross-episode)
REGIME_KEYS = LIFECYCLE_KEYS | {"regime_change"}
CROSS_EPISODE_KEYS = REGIME_KEYS | {"carry"}
CARRY_KEYS = frozenset({"episodes", "reset_before"})
MEMORY_FIELDS_V1 = ("owner", "source_transition", "transform", "round", "value")
MEMORY_FIELDS_V2 = (
    "episode",
    "step",
    "round",
    "owner",
    "key",
    "scope",
    "retention",
    "transform",
    "source_transition",
    "valid",
    "value",
)
MEMORY_FIELDS_V3 = (*MEMORY_FIELDS_V2, "episode_key", "regime_change")


@dataclass(frozen=True)
class MemoryPolicyV1:
    """The declared lifecycle of one ``memory_update`` node."""

    node_id: str
    owner: str
    key: str
    scope: str
    retention: int
    transform: str
    source: str  # the world_transition node whose evidence it derives from
    # T4-004: None when the node declares no regime-change interaction (artifact-2)
    regime_change: str | None = None
    carry_episodes: tuple[str, ...] = ()
    reset_before: tuple[str, ...] = ()

    @property
    def extended(self) -> bool:
        """Whether the node declares the T4-004 semantics (artifact-3)."""

        return self.regime_change is not None

    @property
    def artifact_schema(self) -> str:
        return MEMORY_ARTIFACT_SCHEMA_V3 if self.extended else MEMORY_ARTIFACT_SCHEMA_V2

    def consumers(self, episode_key: str) -> list[str]:
        """The later episodes that observe what *episode_key* recorded: the
        carry's episodes after it, up to the next reset boundary."""

        if episode_key not in self.carry_episodes:
            return []
        consumers: list[str] = []
        for key in self.carry_episodes[self.carry_episodes.index(episode_key) + 1:]:
            if key in self.reset_before:
                break
            consumers.append(key)
        return consumers

    def valid(self, round_index: int, episode_key: str | None = None) -> dict[str, Any]:
        """The rounds an artifact produced in *round_index* may be observed in,
        and under T4-004 the later episodes that observe it in every round."""

        valid: dict[str, Any] = {
            "from_round": round_index + 1,
            "through_round": round_index + self.retention,
        }
        if self.extended:
            valid["episodes"] = self.consumers(episode_key or "")
        return valid


def _carry(config: Mapping[str, Any], where: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    carry = config["carry"]
    if not isinstance(carry, Mapping) or set(carry) != CARRY_KEYS:
        raise RoundError(
            CROSS_EPISODE_STATE_UNDECLARED,
            f"{where} carry declares exactly {sorted(CARRY_KEYS)}: the producing and "
            "consuming episodes in order, and the reset boundaries",
        )
    episodes, resets = carry["episodes"], carry["reset_before"]
    for name, keys in (("episodes", episodes), ("reset_before", resets)):
        if (
            not isinstance(keys, list)
            or any(not isinstance(key, str) or not key for key in keys)
            or len(set(keys)) != len(keys)
        ):
            raise RoundError(
                CROSS_EPISODE_STATE_UNDECLARED,
                f"{where} carry.{name} is a list of distinct episode keys",
            )
    if len(episodes) < 2:
        raise RoundError(
            CROSS_EPISODE_STATE_UNDECLARED,
            f"{where} carry.episodes names fewer than two episodes: nothing is carried",
        )
    stray = [key for key in resets if key not in episodes[1:]]
    if stray:
        raise RoundError(
            CROSS_EPISODE_STATE_UNDECLARED,
            f"{where} carry.reset_before {stray} is not a boundary inside the carry "
            f"{episodes} (a reset is declared before a consuming episode)",
        )
    return tuple(episodes), tuple(key for key in episodes if key in resets)


def node_policy(node: ProtocolNode) -> MemoryPolicyV1:
    """The lifecycle one ``memory_update`` node's config declares (closed form)."""

    config = node.config
    where = f"memory_update {node.node_id!r}"
    if config.get("scope") == SCOPE_CROSS_EPISODE and set(config) != CROSS_EPISODE_KEYS:
        # P16 13.4: cross-episode memory is opt-in and declared in full
        raise RoundError(
            CROSS_EPISODE_STATE_UNDECLARED,
            f"{where} config is {sorted(config)}: cross-episode memory declares exactly "
            f"{sorted(CROSS_EPISODE_KEYS)}",
        )
    if set(config) not in (LIFECYCLE_KEYS, REGIME_KEYS, CROSS_EPISODE_KEYS) or (
        "carry" in config and config.get("scope") != SCOPE_CROSS_EPISODE
    ):
        raise RoundError(
            MEMORY_SCOPE_INVALID,
            f"{where} config is {sorted(config)}: a memory lifecycle declares exactly "
            f"{sorted(LIFECYCLE_KEYS)}, on every memory_update node of the plan "
            "(optionally regime_change; carry under scope cross_episode)",
        )
    if "regime_change" in config and config["regime_change"] not in REGIME_INTERACTIONS:
        raise RoundError(
            MEMORY_SCOPE_INVALID,
            f"{where} regime_change {config['regime_change']!r} is not one of "
            f"{list(REGIME_INTERACTIONS)}",
        )
    for name in ("owner", "key"):
        if not isinstance(config[name], str) or not config[name]:
            raise RoundError(MEMORY_SCOPE_INVALID, f"{where} {name} is a non-empty string")
    if config["scope"] not in MEMORY_SCOPES:
        raise RoundError(
            MEMORY_SCOPE_INVALID,
            f"{where} scope {config['scope']!r} is not one of {list(MEMORY_SCOPES)}",
        )
    retention = config["retention"]
    if isinstance(retention, bool) or not isinstance(retention, int) or retention < 1:
        raise RoundError(
            MEMORY_SCOPE_INVALID,
            f"{where} retention {retention!r} is not a positive number of rounds",
        )
    if config["transform"] not in MEMORY_TRANSFORMS:
        raise RoundError(
            MEMORY_SOURCE_MISSING,
            f"{where} transform {config['transform']!r} is not a registered memory "
            f"transform {sorted(MEMORY_TRANSFORMS)}",
        )
    if len(node.depends_on) != 1:
        raise RoundError(
            MEMORY_SOURCE_MISSING, f"{where} derives from exactly one world_transition node"
        )
    episodes, resets = _carry(config, where) if "carry" in config else ((), ())
    return MemoryPolicyV1(
        node.node_id,
        config["owner"],
        config["key"],
        config["scope"],
        retention,
        config["transform"],
        node.depends_on[0],
        config.get("regime_change"),
        episodes,
        resets,
    )


def memory_policies(protocol: ProtocolIR) -> dict[str, MemoryPolicyV1]:
    """node id -> lifecycle of every ``memory_update`` node; {} for a spike plan.

    Refused before anything runs: a plan mixing lifecycle and spike nodes, a
    scope or retention outside the closed forms (BVL-ROUND-006), an
    unregistered transform, and a node that does not derive from exactly one
    World transition (BVL-ROUND-007).
    """

    nodes = [node for node in protocol.nodes if node.kind is NodeKind.MEMORY_UPDATE]
    declared = [node for node in nodes if set(node.config) - SPIKE_KEYS]
    if not declared:
        return {}
    policies: dict[str, MemoryPolicyV1] = {}
    for node in nodes:
        kinds = [protocol.node(dependency).kind for dependency in node.depends_on]
        if kinds != [NodeKind.WORLD_TRANSITION]:
            raise RoundError(
                MEMORY_SOURCE_MISSING,
                f"memory_update {node.node_id!r} depends on "
                f"{[kind.value for kind in kinds]}: its source evidence is exactly one "
                "world_transition node",
            )
        policies[node.node_id] = node_policy(node)
    slots = [(policy.owner, policy.key) for policy in policies.values()]
    if len(set(slots)) != len(slots):
        raise RoundError(
            MEMORY_SCOPE_INVALID, "two memory_update nodes declare the same owner and key"
        )
    return policies


def require_memory_lifecycle(
    protocol: ProtocolIR,
    *,
    actors: Any,
    information: Any,
    initial_memory: Mapping[str, Any] | None,
    world: Any = None,
) -> dict[str, MemoryPolicyV1]:
    """The plan's memory is declared end to end, before anything runs.

    Every ``memory_artifact`` source names a lifecycle node (BVL-ROUND-007),
    every owner is a plan actor (BVL-ROUND-006), a lifecycle plan starts
    without undeclared memory (BVL-ROUND-008) and a node resets its memory on
    a regime change only of a World that declares its regime events
    (BVL-ROUND-006; *world* is the plan's World contract).
    """

    policies = memory_policies(protocol)
    sources = {} if information is None else dict(information.memory_artifacts)
    for source_id, descriptor in sorted(sources.items()):
        if descriptor.producer not in policies:
            raise RoundError(
                MEMORY_SOURCE_MISSING,
                f"memory_artifact source {source_id!r} producer {descriptor.producer!r} is "
                "not a memory_update node declaring a memory lifecycle",
            )
    if not policies:
        return {}
    if initial_memory:
        raise RoundError(
            HIDDEN_ACTOR_MEMORY,
            f"initial memory {sorted(initial_memory)} is not a Memory Artifact: under a "
            "memory lifecycle an actor observes memory only as a granted memory_artifact "
            "source",
        )
    for policy in policies.values():
        if actors is None or policy.owner not in actors:
            raise RoundError(
                MEMORY_SCOPE_INVALID,
                f"memory_update {policy.node_id!r} owner {policy.owner!r} is not a plan actor",
            )
        if policy.regime_change == REGIME_RESET and not regime_events(world):
            raise RoundError(
                MEMORY_SCOPE_INVALID,
                f"memory_update {policy.node_id!r} resets on a regime change, but the "
                "plan's World contract declares no regime event",
            )
        # SV-13: a regime change is known by its round (``held``).  With a second
        # World transition in the round, an artifact of the transition before the
        # change would be one of the round of the change, and kept after the reset
        transitions = [n for n in protocol.nodes if n.kind is NodeKind.WORLD_TRANSITION]
        if policy.regime_change == REGIME_RESET and len(transitions) > 1:
            raise RoundError(
                MEMORY_SCOPE_INVALID,
                f"memory_update {policy.node_id!r} resets on a regime change, and the plan "
                f"applies {len(transitions)} World transitions a round: a reset is decided "
                "by round and holds for a plan of one transition a round",
            )
    return policies


def regime_events(world: Any) -> tuple[str, ...]:
    """The regime event kinds a plan's World contract declares (none without one)."""

    return () if world is None else tuple(world.progression.regime_events)


def require_carry_schedule(
    policies: Mapping[str, MemoryPolicyV1], schedule: Sequence[str], *, journaled: bool
) -> None:
    """BVL-ROUND-011, before an episode opens: the run executes the episodes of
    every declared carry in the declared order, and carries only its own
    committed evidence."""

    for policy in policies.values():
        if policy.scope != SCOPE_CROSS_EPISODE:
            continue
        where = f"memory_update {policy.node_id!r}"
        if not journaled:
            raise RoundError(
                CROSS_EPISODE_STATE_UNDECLARED,
                f"{where} carries memory across episodes; without a journaled run there "
                "is no committed evidence to carry it from",
            )
        ordered = [key for key in schedule if key in policy.carry_episodes]
        if ordered != list(policy.carry_episodes):
            raise RoundError(
                CROSS_EPISODE_STATE_UNDECLARED,
                f"{where} declares the carry {list(policy.carry_episodes)}; the run's "
                f"experiment schedule {list(schedule)} does not order exactly these episodes "
                "so",
            )


@dataclass(frozen=True)
class EpisodeMemoryV1:
    """One episode's committed memory of one node, and where its regime changed."""

    key: str
    episode: Mapping[str, str]  # EpisodeIdentity document
    artifacts: tuple[Mapping[str, Any], ...] = ()
    # the rounds whose World transition stated a declared regime event
    regime_rounds: tuple[int, ...] = ()


def held(
    policy: MemoryPolicyV1, timeline: Sequence[EpisodeMemoryV1], round_index: int
) -> list[Mapping[str, Any]]:
    """The node's artifacts the engine holds when *round_index* of the last
    episode of *timeline* (the run's episodes so far, in opened order) opens.

    Its own artifacts, and under a declared carry the artifacts of the earlier
    episodes it consumes (no reset boundary in between).  Under
    ``regime_change: reset`` an artifact recorded before a regime-change
    transition is dropped from the round after that transition's round on;
    the carry counts the regime changes of its own episodes only.
    """

    *earlier, current = timeline
    reset = policy.regime_change == REGIME_RESET
    turned = [g for g in current.regime_rounds if g < round_index]
    kept: list[Mapping[str, Any]] = []
    blocked = False  # a regime change after the entry, in a later carry episode
    for entry in reversed(earlier):
        if policy.scope != SCOPE_CROSS_EPISODE or entry.key not in policy.carry_episodes:
            continue
        if current.key in policy.consumers(entry.key) and not (reset and (blocked or turned)):
            kept[:0] = [
                artifact
                for artifact in sorted(entry.artifacts, key=lambda item: item["round"])
                if not (reset and any(g > artifact["round"] for g in entry.regime_rounds))
            ]
        blocked = blocked or bool(entry.regime_rounds)
    kept += [
        artifact
        for artifact in sorted(current.artifacts, key=lambda item: item["round"])
        if not (reset and any(artifact["round"] < g for g in turned))
    ]
    return kept


def artifact_payload(
    policy: MemoryPolicyV1,
    *,
    episode: Mapping[str, str],
    step: Mapping[str, str],
    round_index: int,
    source_transition: Mapping[str, str],
    value: Mapping[str, Any],
    episode_key: str | None = None,
) -> dict[str, Any]:
    """What a MemoryArtifactIdentity binds under the lifecycle (P16 13.2):
    source evidence, transform, owner, scope and the validity interval - and
    under T4-004 the episode key, the consuming episodes and the regime-change
    interaction."""

    payload = {
        "episode": dict(episode),
        "step": dict(step),
        "round": round_index,
        "owner": policy.owner,
        "key": policy.key,
        "scope": policy.scope,
        "retention": policy.retention,
        "transform": policy.transform,
        "source_transition": dict(source_transition),
        "valid": policy.valid(round_index, episode_key),
        "value": json.loads(canonical_json(dict(value))),
    }
    if policy.extended:
        if not isinstance(episode_key, str) or not episode_key:
            raise RoundError(
                CROSS_EPISODE_STATE_UNDECLARED,
                f"memory_update {policy.node_id!r} records memory of an unnamed episode",
            )
        payload["episode_key"] = episode_key
        payload["regime_change"] = policy.regime_change
    return payload


def transformed(transform: str, transition: Mapping[str, Any]) -> dict[str, Any]:
    """The value a registered memory transform derives from one World transition."""

    if transform != OUTCOME_TRANSFORM:
        raise RoundError(
            MEMORY_SOURCE_MISSING, f"memory transform {transform!r} is not registered"
        )
    return dict(transition["outcome"])


def _valid_in(
    artifact: Mapping[str, Any], round_index: int, episode: Mapping[str, str] | None = None
) -> bool:
    if episode is not None and artifact.get("episode") != dict(episode):
        return True  # carried from an earlier episode (``held``): valid in every round
    valid = artifact.get("valid")
    if not isinstance(valid, Mapping) or not isinstance(artifact.get("round"), int):
        return False  # a malformed interval is valid nowhere (artifact_problems names it)
    bounds = (valid.get("from_round"), valid.get("through_round"))
    if any(isinstance(bound, bool) or not isinstance(bound, int) for bound in bounds):
        return False
    return bounds[0] <= round_index <= bounds[1]


def observable(
    artifacts: Iterable[Mapping[str, Any]],
    round_index: int,
    episode: Mapping[str, str] | None = None,
) -> list[Mapping[str, Any]]:
    """The artifact documents of one node valid in *round_index*, oldest first.

    With *episode* (the observing episode's identity) *artifacts* are the
    ``held`` ones, in order: those of an earlier episode come first and are
    valid in every round.
    """

    valid = [artifact for artifact in artifacts if _valid_in(artifact, round_index, episode)]
    if episode is not None:
        return valid
    return sorted(valid, key=lambda artifact: artifact["round"])


def observation_content(artifacts: Sequence[Mapping[str, Any]]) -> bytes:
    """The bytes a ``memory_artifact`` source carries for its valid artifacts."""

    return canonical_json(
        {
            "schema": MEMORY_OBSERVATION_SCHEMA,
            "artifacts": [
                {
                    "identity": dict(artifact["identity"]),
                    "owner": artifact["owner"],
                    "key": artifact["key"],
                    "round": artifact["round"],
                    "value": artifact["value"],
                    # T4-004: an artifact-3 says which episode recorded it
                    **(
                        {"episode_key": artifact["episode_key"]}
                        if "episode_key" in artifact
                        else {}
                    ),
                }
                for artifact in artifacts
            ],
        }
    ).encode("utf-8")


def memory_lineage(
    source_id: str, producer: str, artifacts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The committed memory one source carried into a request-2 (its ``memory``)."""

    return {
        "source_id": source_id,
        "producer": producer,
        "artifacts": [dict(artifact["identity"]) for artifact in artifacts],
        "content_sha256": sha256_bytes(observation_content(artifacts)).hex,
    }


def source_view(
    source_id: str,
    producer: str,
    artifacts: Iterable[Mapping[str, Any]],
    round_index: int,
    episode: Mapping[str, str] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """(content, request-2 lineage) of one memory source observed in *round_index*."""

    valid = observable(artifacts, round_index, episode)
    return observation_content(valid), memory_lineage(source_id, producer, valid)


def artifact_problems(
    document: Mapping[str, Any],
    policy: MemoryPolicyV1,
    *,
    episode: Mapping[str, str],
    step: Mapping[str, str],
    round_index: int,
    record: Mapping[str, Any],
    transition: Mapping[str, Any] | None,
    episode_key: str | None = None,
) -> list[str]:
    """Why one committed artifact is not its node's declared lifecycle."""

    problems: list[str] = []
    if document.get("schema") != policy.artifact_schema or set(document) != {
        "schema", "identity", *(MEMORY_FIELDS_V3 if policy.extended else MEMORY_FIELDS_V2)
    }:
        problems.append(f"is not a closed {policy.artifact_schema}")
    if document.get("episode") != dict(episode) or document.get("step") != dict(step):
        problems.append("belongs to another episode / step")
    if policy.extended and (
        document.get("episode_key") != episode_key
        or document.get("regime_change") != policy.regime_change
    ):
        problems.append("is not its episode's key and the declared regime-change interaction")
    declared = {
        "owner": policy.owner,
        "key": policy.key,
        "scope": policy.scope,
        "retention": policy.retention,
        "transform": policy.transform,
    }
    if {name: document.get(name) for name in declared} != declared:
        problems.append("is not the plan's declared owner / key / scope / retention / transform")
    if document.get("valid") != policy.valid(round_index, episode_key):
        problems.append(
            "validity interval is not its round, declared retention and declared carry"
        )
    if record != {
        "identity": document.get("identity"),
        "owner": policy.owner,
        "key": policy.key,
        "value": document.get("value"),
    }:
        problems.append("is not what MEMORY_RECORDED committed")
    if transition is None:
        problems.append("has no committed World transition as source evidence")
    elif document.get("value") != transformed(policy.transform, transition):
        problems.append("value is not its transform of the source World transition")
    return problems


def memory_request_problems(
    request: Mapping[str, Any],
    granted: Sequence[str],
    expected: Mapping[str, Mapping[str, Any] | None],
) -> list[str]:
    """request-2 ``memory`` is exactly the committed artifacts of every granted
    memory_artifact source; a request observing none has no ``memory``."""

    sources = sorted(source for source in granted if source in expected)
    if not sources:
        if "memory" in request:
            return ["request-2 binds memory but observes no memory_artifact source"]
        return []
    if request.get("memory") != [expected[source] for source in sources]:
        return ["request-2 memory is not the exact committed Memory Artifacts valid in its round"]
    return []


__all__ = [
    "CARRY_KEYS",
    "CROSS_EPISODE_KEYS",
    "LIFECYCLE_KEYS",
    "MEMORY_ARTIFACT_SCHEMA_V1",
    "MEMORY_ARTIFACT_SCHEMA_V2",
    "MEMORY_ARTIFACT_SCHEMA_V3",
    "MEMORY_CHECK",
    "MEMORY_FIELDS_V1",
    "MEMORY_FIELDS_V2",
    "MEMORY_FIELDS_V3",
    "REGIME_INTERACTIONS",
    "REGIME_KEYS",
    "REGIME_RESET",
    "REGIME_RETAIN",
    "SCOPE_CROSS_EPISODE",
    "EpisodeMemoryV1",
    "held",
    "regime_events",
    "require_carry_schedule",
    "MEMORY_OBSERVATION_SCHEMA",
    "MEMORY_SCOPES",
    "MEMORY_TRANSFORMS",
    "OUTCOME_TRANSFORM",
    "SCOPE_EPISODE",
    "MemoryPolicyV1",
    "artifact_payload",
    "artifact_problems",
    "memory_lineage",
    "memory_policies",
    "memory_request_problems",
    "node_policy",
    "observable",
    "observation_content",
    "require_memory_lifecycle",
    "source_view",
    "transformed",
]
