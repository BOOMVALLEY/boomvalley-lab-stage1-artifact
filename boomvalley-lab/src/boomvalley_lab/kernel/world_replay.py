"""Replay of a run's committed World transitions from its evidence (T3-005).

A contracted World is a deterministic function of its bound inputs
(``bvl-world-replay-1``, ``kernel/world.py``).  Everything one transition is a
function of is serialized in the run's evidence:

    the pre-state     world_transition.transition.pre_state (canonical bytes)
    the input         WORLD_INTENT_RECORDED payload: action_input and action
    the seed          WORLD_INTENT_RECORDED payload: seed
    the World         the plan's World contract (plugin, schemas, progression,
                      RNG policy)

so a verifier that holds the World's code - and nothing of the process that
ran it - recomputes every transition.  ``replay_world_transitions`` does, on
instances of the registered World that never saw the run:

    independent   one fresh instance per transition, in journal order
    shared        one instance for every transition, in reverse order: what a
                  transition states does not depend on what was applied before
    chained       per episode, from the plan's initial state: each replayed
                  post-state, serialized and read back, is the next pre-state

Each replay is handed states and actions decoded from the evidence bytes and
must state the committed transition byte for byte (BVL-WORLD-009).

Every replay is made under the contract's RNG policy (T3-006,
``kernel/world_rng.py``), with hidden plugin RNG held shut.  A SEEDED World is
handed a fresh declared RNG of the intent's seed and must also draw what the
committed transition evidences; a DETERMINISTIC World is handed the bound seed
in the first pass and another seed in each of the others, and must state the
committed transition under all three (BVL-WORLD-013).  The World
is the one the caller registers; that it is the run's World - the same plugin
set and build - is the caller's binding to check (``lifecycle.gated.verify``).

A plan without a World contract states no serialization the kernel reads:
its verdict is NOT_APPLICABLE, never REPLAYED.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import BoomvalleyError, EvidenceError
from boomvalley_lab.kernel.journal2 import (
    EPISODE_OPENED,
    WORLD_APPLIED,
    WORLD_INTENT_RECORDED,
    Journal2,
)
from boomvalley_lab.kernel.world import (
    HIDDEN_WORLD_STATE,
    REPLAY,
    RNG_POLICY_INVALID,
    STATE_SERIALIZATION,
    PureWorld,
    WorldContractV1,
    deserialize_state,
    replay_problems,
    serialize_state,
)
from boomvalley_lab.kernel.world_executor import (
    WorldIntentV2,
    _load_member,
    _stated,
    replica_of,
    transition_evidence_by_intent,
)
from boomvalley_lab.kernel.world_registry import WorldRegistryV1
from boomvalley_lab.kernel.world_rng import apply_under_policy

REPLAY_REPORT_SCHEMA = "bvl-world-replay-report-1"
REPLAYED, NOT_REPLAYED, NOT_APPLICABLE = "REPLAYED", "NOT_REPLAYED", "NOT_APPLICABLE"
PASSES = ("independent", "shared_reversed", "chained")


@dataclass(frozen=True)
class WorldReplayV1:
    """What replaying a run's committed transitions on fresh instances found."""

    verdict: str
    world: str | None
    state_schema: str | None
    transitions: int
    applies: int
    final_states: Mapping[str, Any]
    problems: tuple[str, ...]
    rng_policy: str | None = None

    @property
    def replayed(self) -> bool:
        return self.verdict == REPLAYED

    def document(self) -> dict[str, Any]:
        return {
            "schema": REPLAY_REPORT_SCHEMA,
            "rule": REPLAY,
            "state_serialization": STATE_SERIALIZATION,
            "verdict": self.verdict,
            "world": self.world,
            "rng_policy": self.rng_policy,
            "state_schema": self.state_schema,
            "transitions": self.transitions,
            "passes": list(PASSES) if self.world is not None else [],
            "world_applies": self.applies,
            "final_states": dict(self.final_states),
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class _Committed:
    where: str
    episode: str
    intent: WorldIntentV2
    body: Mapping[str, Any]
    rng: Any


def _plan_document(run_directory: Path) -> Mapping[str, Any]:
    members = sorted((run_directory / "evidence-v2" / "plan").glob("*.json"))
    if len(members) != 1:
        raise EvidenceError(f"{len(members)} plan evidence members; a run has one plan")
    return _load_member(members[0])["plan"]


def _committed(run_directory: Path, records: list[dict]) -> list[_Committed]:
    evidence = transition_evidence_by_intent(run_directory)
    intents = {
        record["transition_intent"]["identity"]["digest"]: WorldIntentV2.from_document(
            record["transition_intent"]
        )
        for record in records
        if record["event"] == WORLD_INTENT_RECORDED
    }
    found = []
    for record in records:
        if record["event"] != WORLD_APPLIED:
            continue
        where = f"journal-2 #{record['sequence']} {record['event']}"
        digest = record["transition_intent"]["digest"]
        held = evidence.get(digest, [])
        if digest not in intents or len(held) != 1:
            raise EvidenceError(f"{where} does not name one intent and one transition member")
        body = held[0][1]["transition"]
        found.append(
            _Committed(where, record["episode"], intents[digest], body, held[0][1].get("rng"))
        )
    return found


def replay_world_transitions(run_directory: Path, worlds: WorldRegistryV1) -> WorldReplayV1:
    """Recompute every committed transition of *run_directory* on fresh Worlds."""

    run_directory = Path(run_directory)

    def refused(problem: str, world: str | None = None, ref: str | None = None) -> WorldReplayV1:
        return WorldReplayV1(NOT_REPLAYED, world, ref, 0, 0, {}, (problem,))

    try:
        records = Journal2(run_directory).read()
        plan = _plan_document(run_directory)
        if "world" not in plan:
            return WorldReplayV1(
                NOT_APPLICABLE, None, None, 0, 0, {},
                ("the plan has no World contract: its states have no serialization contract "
                 "and its World no replay rule",),
            )
        contract = WorldContractV1.from_document(plan["world"])
        ref = contract.state_schema.ref
        world = worlds.resolve(contract)
        committed = _committed(run_directory, records)
        initial = serialize_state(plan["initial_world_state"])
    except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
        return refused(f"the run's evidence does not state what to replay: {error}")

    applies = 0
    problems: list[str] = []
    reproduced: set[str] = set()  # transitions the first pass restated under their seed

    def replay(instance: PureWorld, one: _Committed, name: str) -> Mapping[str, Any] | None:
        """*one* replayed on *instance* from bytes; its document when it is the committed one."""

        nonlocal applies
        applies += 1
        # T3-006: only the first pass hands a DETERMINISTIC World its bound seed
        reseeded = not contract.rng.seeded and name != PASSES[0]
        try:
            made, used = apply_under_policy(
                instance,
                contract.rng,
                deserialize_state(serialize_state(one.body["pre_state"])),
                one.intent.handed_action(),
                seed=one.intent.payload["seed"],
                probe=name if reseeded else None,
            )
            stated = _stated(made)
        except Exception as error:  # noqa: BLE001 - whatever the World's code raises
            code = getattr(error, "code", None)
            problems.append(
                f"{code if code == RNG_POLICY_INVALID else HIDDEN_WORLD_STATE}: {one.where} "
                f"({name}) the replayed World raised {type(error).__name__}: {error}"
            )
            return None
        differing = replay_problems(one.body, stated)
        if not differing and not reseeded:
            reproduced.add(one.where)
        # a transition only its bound seed reproduces is undeclared randomness; one
        # this instance's history changed is hidden state.  A fresh instance under the
        # same other seed tells them apart
        seed_driven = False
        if differing and reseeded and one.where in reproduced:
            applies += 1
            try:
                alone, _ = apply_under_policy(
                    replica_of(world),
                    contract.rng,
                    deserialize_state(serialize_state(one.body["pre_state"])),
                    one.intent.handed_action(),
                    seed=one.intent.payload["seed"],
                    probe=name,
                )
                seed_driven = bool(replay_problems(one.body, _stated(alone)))
            except Exception:  # noqa: BLE001 - not attributable to the seed
                seed_driven = False
        if seed_driven:
            problems.extend(
                f"{RNG_POLICY_INVALID}: {one.where} ({name}) is not reproduced under "
                f"another seed, and the World contract declares DETERMINISTIC: {problem}"
                for problem in differing
            )
        else:
            problems.extend(
                f"{HIDDEN_WORLD_STATE}: {one.where} ({name}) is not reproduced from its "
                f"serialized pre-state, input and seed: {problem}"
                for problem in differing
            )
        if used != one.rng:
            problems.append(
                f"{RNG_POLICY_INVALID}: {one.where} ({name}) the replay's use of the "
                f"declared RNG ({used}) is not the committed transition's ({one.rng})"
            )
            return None
        return None if differing else stated

    try:
        for one in committed:
            replay(replica_of(world), one, PASSES[0])
        shared = replica_of(world)
        for one in reversed(committed):
            replay(shared, one, PASSES[1])
        # the episodes, folded from the plan's initial state through serialization
        current = {
            record["episode"]: initial for record in records if record["event"] == EPISODE_OPENED
        }
        chain = replica_of(world)
        broken: set[str] = set()
        for one in committed:
            if one.episode in broken:
                continue
            held = current.get(one.episode)
            if held is None or held != canonical_bytes(dict(one.body["pre_state"])):
                problems.append(
                    f"{HIDDEN_WORLD_STATE}: {one.where} ({PASSES[2]}) pre-state is not the "
                    "state its episode replays to"
                )
                broken.add(one.episode)
                continue
            stated = replay(chain, one, PASSES[2])
            if stated is None:
                broken.add(one.episode)
                continue
            current[one.episode] = serialize_state(stated["post_state"])
    except (BoomvalleyError, KeyError, TypeError, ValueError) as error:
        problems.append(f"{HIDDEN_WORLD_STATE}: the run is not replayable: {error}")
        current = {}

    return WorldReplayV1(
        NOT_REPLAYED if problems else REPLAYED,
        contract.plugin,
        ref,
        len(committed),
        applies,
        {episode: deserialize_state(data) for episode, data in sorted(current.items())}
        if not problems
        else {},
        tuple(problems),
        contract.rng.policy,
    )
