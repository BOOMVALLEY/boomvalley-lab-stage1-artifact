"""World(t) -> World(t+1): the state chain of a run, re-walked from its evidence (P16 4, T4-005).

A longitudinal episode is one chain of World states.  Nothing but a committed
World transition moves it, and no round opens on anything but the state the
previous one closed on:

    origin        the episode opens on the plan's initial state.  Episode
                  isolation (P16 13.4) is the one declared reset: no World
                  state crosses an episode, so every episode's origin is that
                  state and no other
    round open    pre_state(round t+1) == post_state(round t); round 1 opens on
                  the origin
    transition    its pre-state is the state the episode is then in, and the
                  episode is in its post-state afterwards
    round close   the round closes on the state its last transition left, or
                  on the state it opened on when it committed none

``state_chain`` walks journal-2 in order and checks every link.  The states
are not taken from what the journal says of them: each transition's pre- and
post-state identity is recomputed from the state bytes of its own
``world_transition`` evidence member, and the origin from the plan.  A link
that does not hold is BVL-ROUND-005 STATE_CHAIN_MISMATCH.

The walk also folds every link into one digest per episode (``head``): the
origin, then each round opening, transition and round close, each hashed over
the one before it.  The conformance attestation carries the heads (plans with
a round contract and a World contract), so a sealed package states the exact
chain it was verified on.

The engine keeps the same chain while it runs (``kernel/engine.py``: a step
that is not a World transition cannot return a state); this module is the
verifier's side and reads nothing but the run directory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import sha256_document
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.kernel.journal2 import (
    EPISODE_OPENED,
    ROUND_COMPLETED,
    ROUND_OPENED,
    WORLD_APPLIED,
    WORLD_INTENT_RECORDED,
    Journal2,
)
from boomvalley_lab.kernel.rounds import STATE_CHAIN_MISMATCH
from boomvalley_lab.kernel.world import WorldContractV1, state_identity
from boomvalley_lab.kernel.world_executor import _load_member, transition_evidence_by_intent

STATE_CHAIN_SCHEMA = "bvl-world-state-chain-1"
STATE_CHAIN_RULE = "post_state(round t) == pre_state(round t+1)"
#: Added to an attestation's checks for a plan with a round contract and a World contract.
STATE_CHAIN_CHECK = "world_state_chain_continuous_across_rounds"
#: where every episode's chain starts, and the one declared reset between episodes
ORIGIN = "plan_initial_state"
RESET = "episode_isolation"
CONTINUOUS, BROKEN, NOT_APPLICABLE = "CONTINUOUS", "BROKEN", "NOT_APPLICABLE"


def _fold(head: str, link: Mapping[str, Any]) -> str:
    return sha256_document({"previous": head, "link": dict(link)}).hex


def _recomputed(body: Any, role: str, state_schema: str | None) -> dict[str, Any] | None:
    """The identity of the *role* state of one transition body, from its own bytes."""

    state = body.get(role) if isinstance(body, Mapping) else None
    if not isinstance(state, Mapping):
        return None
    try:
        return state_identity(state, state_schema).document()
    except (BoomvalleyError, TypeError, ValueError):
        return None


def state_chain(
    records: Sequence[Mapping[str, Any]],
    *,
    initial_state: Mapping[str, Any],
    state_schema: str | None,
    transitions: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[list[str], dict[str, Any]]:
    """Why a run's World states are not one chain per episode, and the chain.

    *records* is journal-2 in order; *initial_state* the plan's initial World
    state and *state_schema* its World contract's schema ref (None without a
    contract); *transitions* maps a World intent digest to the
    ``world_transition`` evidence documents that bind it.  Returns the
    BVL-ROUND-005 problems and the ``bvl-world-state-chain-1`` document.
    """

    origin = state_identity(initial_state, state_schema).document()
    problems: list[str] = []
    episodes: dict[str, dict[str, Any]] = {}

    def broken(where: str, detail: str) -> None:
        problems.append(f"{STATE_CHAIN_MISMATCH}: {where} {detail}")

    for opened in (record for record in records if record["event"] == EPISODE_OPENED):
        name = opened["episode"]
        label = f"episode {opened.get('episode_key')!r}"
        mine = [
            record
            for record in records
            if record.get("episode") == name and record["sequence"] > opened["sequence"]
        ]
        stated = opened.get("initial_state")
        if state_schema is not None and (
            not isinstance(stated, Mapping) or stated.get("identity") != origin
        ):
            broken(
                f"{label} journal-2 #{opened['sequence']} {EPISODE_OPENED}",
                "does not open on the plan's initial state, and no World state is declared "
                "to cross an episode",
            )
        current = origin
        head = _fold("", {"kind": "origin", "origin": ORIGIN, "state": origin})
        identified = any(record["event"] == ROUND_OPENED for record in mine)
        closed = 0  # the last round that closed
        open_round: int | None = None  # the round ROUND_OPENED identified and nothing closed
        intents: dict[str, Mapping[str, Any]] = {}
        links = applied = 0
        for record in mine:
            event = record["event"]
            where = f"{label} journal-2 #{record['sequence']} {event}"
            if event == ROUND_OPENED:
                if open_round is not None or record["round"] != closed + 1:
                    broken(where, f"opens round {record['round']} after round {closed} closed"
                                  + ("" if open_round is None else ", inside an open round"))
                if record["pre_state"] != current:
                    broken(
                        where,
                        f"pre_state(round {record['round']}) is not "
                        + ("the episode's initial state" if closed == 0
                           else f"post_state(round {closed})"),
                    )
                open_round = record["round"]
                head = _fold(head, {"kind": "round_open", "round": record["round"],
                                    "state": record["pre_state"]})
                links += 1
            elif event == WORLD_INTENT_RECORDED:
                intent = record["transition_intent"]
                payload = intent.get("payload", {})
                if record["round"] != closed + 1 or (identified and open_round != record["round"]):
                    broken(where, f"intends a transition of round {record['round']} outside "
                                  "that round")
                if payload.get("pre_state") != current:
                    broken(where, "pre-state is not the state its episode is in")
                intents[intent["identity"]["digest"]] = record
            elif event == WORLD_APPLIED:
                digest = record["transition_intent"]["digest"]
                intent = intents.pop(digest, None)
                held = transitions.get(digest, ())
                if intent is None or intent["round"] != record["round"] or len(held) != 1:
                    broken(where, "is not the one committed transition of an intent recorded "
                                  "before it in its round")
                    current = record["post_state"]
                    continue
                body = held[0].get("transition")
                before = _recomputed(body, "pre_state", state_schema)
                after = _recomputed(body, "post_state", state_schema)
                if before != current:
                    broken(where, "the pre-state its evidence serializes is not the state its "
                                  "episode is in")
                if after is None or after != record["post_state"]:
                    broken(where, "post_state is not the state its evidence serializes")
                current = record["post_state"]
                applied += 1
                head = _fold(head, {
                    "kind": "transition", "round": record["round"], "intent": digest,
                    "transition": record["transition"], "pre_state": before,
                    "post_state": record["post_state"]})
                links += 1
            elif event == ROUND_COMPLETED:
                if record["round"] != closed + 1 or (identified and open_round != record["round"]):
                    broken(where, f"closes round {record['round']} after round {closed}, "
                                  "which is not the round that is open")
                if record["post_state"] != current:
                    broken(where, f"post_state(round {record['round']}) is not the state its "
                                  "last committed transition left")
                closed, open_round = record["round"], None
                head = _fold(head, {"kind": "round_close", "round": record["round"],
                                    "state": record["post_state"]})
                links += 1
        episodes[str(opened.get("episode_key"))] = {
            "rounds": closed,
            "transitions": applied,
            "links": links,
            "final_state": current,
            "head": f"sha256:{head}",
        }
    counted = sum(item["transitions"] for item in episodes.values())
    document = {
        "schema": STATE_CHAIN_SCHEMA,
        "rule": STATE_CHAIN_RULE,
        "verdict": BROKEN if problems else CONTINUOUS if counted else NOT_APPLICABLE,
        "origin": ORIGIN,
        "reset": RESET,
        "state_schema": state_schema,
        "initial_state": origin,
        "episodes": dict(sorted(episodes.items())),
        "rounds": sum(item["rounds"] for item in episodes.values()),
        "transitions": counted,
        "links": sum(item["links"] for item in episodes.values()),
        "problems": list(problems),
    }
    return problems, document


def attested_chain(document: Mapping[str, Any]) -> dict[str, Any]:
    """What an attestation states of a verified chain: its origin and every head."""

    return {
        "rule": document["rule"],
        "origin": document["origin"],
        "reset": document["reset"],
        "initial_state": document["initial_state"],
        "episodes": {
            key: {name: item[name] for name in ("rounds", "transitions", "final_state", "head")}
            for key, item in document["episodes"].items()
        },
        "links": document["links"],
    }


def run_state_chain(
    run_directory: Path,
    records: Sequence[Mapping[str, Any]] | None = None,
    plan_document: Mapping[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """``state_chain`` of the run at *run_directory*, read from its evidence only."""

    run_directory = Path(run_directory)

    def unreadable(detail: str) -> tuple[list[str], dict[str, Any]]:
        problem = f"{STATE_CHAIN_MISMATCH}: the run's evidence states no chain: {detail}"
        return [problem], {
            "schema": STATE_CHAIN_SCHEMA, "rule": STATE_CHAIN_RULE, "verdict": BROKEN,
            "origin": ORIGIN, "reset": RESET, "episodes": {}, "problems": [problem]}

    try:
        if records is None:
            records = Journal2(run_directory).read()
        if plan_document is None:
            members = sorted((run_directory / "evidence-v2" / "plan").glob("*.json"))
            if len(members) != 1:
                return unreadable(f"{len(members)} plan evidence members")
            plan_document = _load_member(members[0])["plan"]
        state_schema = (
            WorldContractV1.from_document(plan_document["world"]).state_schema.ref
            if "world" in plan_document
            else None
        )
        return state_chain(
            records,
            initial_state=plan_document["initial_world_state"],
            state_schema=state_schema,
            transitions={
                digest: [document for _, document in held]
                for digest, held in transition_evidence_by_intent(run_directory).items()
            },
        )
    except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
        # an unreadable journal or member is no chain; it is never a continuous one
        return unreadable(str(error))

__all__ = [
    "BROKEN",
    "CONTINUOUS",
    "NOT_APPLICABLE",
    "ORIGIN",
    "RESET",
    "STATE_CHAIN_CHECK",
    "STATE_CHAIN_RULE",
    "STATE_CHAIN_SCHEMA",
    "attested_chain",
    "run_state_chain",
    "state_chain",
]
