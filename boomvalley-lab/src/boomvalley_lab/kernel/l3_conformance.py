"""P18 L3 conformance claim over one manifest-4 package (T3-GATE).

An L1 claim (``l1_conformance.py``) says a run came from a declaration and
registered plugins only; an L2 claim (``l2_conformance.py``) adds the
actor-to-actor interaction.  An L3 claim is about what the organization's
decision did: an authoritative decision changed an explicit environment, the
step from the decision to the World was the plan's generic Protocol IR and
nothing else, every such step is evidenced end to end, and somebody who holds
the World's code - and nothing of the process that ran it - recomputes it.
``assess_l3_conformance_v1`` decides it (study-neutral: the plan is the only
source of expected structure):

    W1 l1_conformant           the package's L1 claim is ``L1``
    W2 world_declared          the plan freezes a World contract
                               (``bvl-world-contract-4``: plugin, versioned
                               state and action schemas, progression, RNG
                               policy), its IR has a ``world_transition`` node,
                               and every such node names the contract's World
                               and depends directly on exactly one ``decision``
                               node - a Decision -> World edge of the plan
    W3 generic_transition      the journal is the plan's closed
                               ``bvl-protocol-ir-1`` executed (L2's D3), and per
                               episode, executed round and World node there is
                               exactly one WORLD_INTENT_RECORDED followed by
                               exactly one WORLD_APPLIED that binds it; no
                               World event names another step, no outcome is
                               unknown, and the package holds one transition
                               member per WORLD_APPLIED: journaled World
                               transitions = plan World nodes x executed rounds
    W4 decision_world_lineage  per transition: the intent names the decision
                               its IR dependency committed earlier in the same
                               round, and hands the World exactly that
                               decision's requested action (NO_ACTION iff the
                               decision is NO_ACTION); the transition member
                               binds that intent and decision, keeps the
                               requested, admissible and executed actions, and
                               its pre- and post-state identities recompute
                               under the contract's state schema; per episode
                               the states chain from the plan's initial state
                               (each post-state is the next pre-state)
    W5 independently_replayed  a ``bvl-world-replay-report-1`` of this package
                               is REPLAYED on the contract's World, by all
                               passes, over exactly the journaled transitions
                               (``world_replay.replay_world_transitions`` on
                               the caller's own World instances)

W5 is the caller's to supply (*replay*): a package carries no World code, so
without a replay the criterion is NOT_EVALUATED and the claim is ``NOT_L3``.
The claim is ``L3`` iff every criterion passes.  It does not require an
actor-to-actor edge: the package's L2 level is the L2 claim's to state, and
the tier order (L3 proven needs L2 proven) is the gate's.  Nothing is written.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.kernel.journal2 import (
    DECISION_RECORDED,
    EPISODE_OPENED,
    WORLD_APPLIED,
    WORLD_INTENT_RECORDED,
    WORLD_OUTCOME_UNKNOWN,
    Journal2,
)
from boomvalley_lab.kernel.l1_conformance import (
    FAIL,
    L1,
    NOT_EVALUATED,
    PASS,
    _member_documents,
    assess_l1_conformance_v1,
)
from boomvalley_lab.kernel.l2_conformance import _generic_protocol, _step_keys
from boomvalley_lab.kernel.manifest4 import read_manifest4
from boomvalley_lab.kernel.package4 import MANIFEST_NAME, verify_package_v4
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.world import (
    ACTION_ROLES,
    NO_ACTION_INPUT,
    WorldContractV1,
    state_identity,
)
from boomvalley_lab.kernel.world_replay import PASSES, REPLAY_REPORT_SCHEMA, REPLAYED

L3_CONFORMANCE_SCHEMA = "bvl-l3-conformance-1"
L3 = "L3"
NOT_L3 = "NOT_L3"
WORLD_EVENTS = (WORLD_INTENT_RECORDED, WORLD_APPLIED, WORLD_OUTCOME_UNKNOWN)

CRITERIA = (
    ("W1", "l1_conformant"),
    ("W2", "world_declared"),
    ("W3", "generic_transition"),
    ("W4", "decision_world_lineage"),
    ("W5", "independently_replayed"),
)


def _same(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def world_edges(plan: Mapping[str, Any], protocol: ProtocolIR
                ) -> tuple[WorldContractV1 | None, list[dict], list[str]]:
    """The plan's Decision -> World edges: one per ``world_transition`` node."""

    if "world" not in plan:
        return None, [], ["the plan freezes no World contract: its states and actions are "
                          "unversioned (not an L3 run)"]
    contract = WorldContractV1.from_document(plan["world"])
    edges: list[dict] = []
    problems: list[str] = []
    for node in protocol.nodes:
        if node.kind is not NodeKind.WORLD_TRANSITION:
            continue
        if node.config.get("world") != contract.plugin:
            problems.append(f"{node.node_id!r} names World {node.config.get('world')!r}, the "
                            f"contract is of {contract.plugin!r}")
        decisions = [dep for dep in node.depends_on
                     if protocol.node(dep).kind is NodeKind.DECISION]
        if len(decisions) != 1:
            problems.append(f"{node.node_id!r} depends on {len(decisions)} decision nodes: "
                            "a World transition applies exactly one decision")
            continue
        edges.append({"decision": decisions[0], "world": node.node_id})
    if not edges and not problems:
        problems.append("the plan's IR has no world_transition node: no decision reaches the "
                        "World")
    return contract, edges, problems


def _world_events(root: Path, protocol: ProtocolIR, journal: list[dict],
                  keys: Mapping[str, tuple], planned: int
                  ) -> tuple[list[str], dict[tuple, tuple[dict, dict]], dict[str, int]]:
    """Per World step its (intent record, applied record), and why the journal is not that."""

    problems: list[str] = []
    found: dict[tuple, dict[str, list[dict]]] = {}
    for record in journal:
        if record["event"] not in WORLD_EVENTS:
            continue
        where = keys.get(record.get("step"))
        if where is None or protocol.node(where[2]).kind is not NodeKind.WORLD_TRANSITION:
            problems.append(f"journal-2 #{record['sequence']} {record['event']} names no "
                            "world_transition step of the IR")
            continue
        if record["event"] == WORLD_OUTCOME_UNKNOWN:
            problems.append(f"World step {where} has an unknown outcome")
            continue
        found.setdefault(where, {}).setdefault(record["event"], []).append(record)
    chains: dict[tuple, tuple[dict, dict]] = {}
    for where, events in sorted(found.items()):
        intents = events.get(WORLD_INTENT_RECORDED, [])
        applied = events.get(WORLD_APPLIED, [])
        if len(intents) != 1 or len(applied) != 1:
            problems.append(f"World step {where} has {len(intents)} intents and "
                            f"{len(applied)} applied transitions")
            continue
        intent, outcome = intents[0], applied[0]
        if intent["sequence"] > outcome["sequence"]:
            problems.append(f"World step {where} was applied before its intent")
        elif outcome["transition_intent"] != intent["transition_intent"]["identity"]:
            problems.append(f"World step {where} was applied under another intent")
        else:
            chains[where] = (intent, outcome)
    members = len(list((root / "evidence-v2" / "world_transition").glob("*.json")))
    counts = {"planned_transitions": planned, "intents": sum(
        len(e.get(WORLD_INTENT_RECORDED, ())) for e in found.values()),
        "applied": sum(len(e.get(WORLD_APPLIED, ())) for e in found.values()),
        "transition_members": members}
    if not (planned == counts["intents"] == counts["applied"] == members == len(chains)) \
            or not planned:
        problems.append(f"{counts['intents']} intents, {counts['applied']} applied and "
                        f"{members} transition members for {planned} planned World "
                        "transitions")
    return problems, chains, counts


def _lineage(root: Path, manifest: Any, plan: Mapping[str, Any], contract: WorldContractV1,
             edges: list[dict], journal: list[dict], keys: Mapping[str, tuple],
             chains: Mapping[tuple, tuple[dict, dict]], dataset: Mapping[str, Any],
             episodes: list[Mapping]) -> tuple[list[str], dict[str, Any]]:
    schema = contract.state_schema.ref
    decision_of = {edge["world"]: edge["decision"] for edge in edges}
    committed = {keys[r["step"]]: r for r in journal
                 if r["event"] == DECISION_RECORDED and r.get("step") in keys}
    units = {(u["episode_key"], u["round"], u["node"]): u for u in dataset["decisions"]}
    decisions = {d["identity"]["digest"]: d for d in _member_documents(root, manifest, "decision")}
    transitions = {t["intent"]["digest"]: t
                   for t in _member_documents(root, manifest, "world_transition")}
    opened = {r["episode_key"]: r for r in journal if r["event"] == EPISODE_OPENED}
    problems: list[str] = []
    bound = chained = 0
    inputs: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    for episode in episodes:
        key = episode["episode_key"]
        mine = sorted((where for where in chains if where[0] == key),
                      key=lambda where: chains[where][0]["sequence"])
        state = (opened.get(key) or {}).get("initial_state", {}).get("identity")
        first = True
        for where in mine:
            intent, outcome = chains[where]
            payload = intent["transition_intent"]["payload"]
            label = f"World step {where}"
            source = (where[0], where[1], decision_of[where[2]])
            decided = committed.get(source)
            unit = units.get(source)
            if decided is None or unit is None or decided["sequence"] > intent["sequence"]:
                problems.append(f"{label}: its decision dependency {source[2]!r} committed no "
                                "decision before the intent")
                continue
            identity = decided["decision"]["identity"]
            member = decisions.get(identity["digest"])
            if not (payload["decision"] == intent["decision"] == unit["unit"] == identity) \
                    or member is None:
                problems.append(f"{label}: the intent does not name the decision its IR "
                                "dependency committed")
                continue
            requested = [decided["decision"].get("requested_action"),
                         unit.get("requested_action"), member.get("requested_action")]
            if not all(isinstance(r, Mapping) and _same(r, payload["action"])
                       for r in requested):
                problems.append(f"{label}: the action handed to the World is not the "
                                "decision's requested action")
                continue
            no_action = payload["action_input"] == NO_ACTION_INPUT
            if no_action != (member.get("outcome") == NO_ACTION_INPUT) \
                    or (no_action and payload["action"]):
                problems.append(f"{label}: the intent's action input is "
                                f"{payload['action_input']}, the decision is "
                                f"{member.get('outcome')}")
                continue
            if (payload["node"], payload["round"], payload["world"], payload["state_schema"]) \
                    != (where[2], where[1], contract.plugin, schema):
                problems.append(f"{label}: the intent is of another node, round, World or "
                                "state schema")
                continue
            evidence = transitions.get(intent["transition_intent"]["identity"]["digest"])
            if evidence is None:
                problems.append(f"{label}: no transition member binds its intent")
                continue
            body = evidence["transition"]
            if (evidence["decision"], evidence["identity"], evidence["world"],
                    evidence["state_schema"]) != (identity, outcome["transition"],
                                                  contract.plugin, schema):
                problems.append(f"{label}: the transition member is of another decision, "
                                "transition, World or state schema")
                continue
            if not all(isinstance(body.get(role), Mapping) for role in ACTION_ROLES) \
                    or not _same(body["requested_action"], payload["action"]) \
                    or body.get("action_input") != payload["action_input"]:
                problems.append(f"{label}: the transition does not keep the requested, "
                                "admissible and executed actions of its intent")
                continue
            bound += 1
            inputs[payload["action_input"]] += 1
            verdicts[str(body.get("admissibility_verdict"))] += 1
            pre = state_identity(body["pre_state"], schema).document()
            post = state_identity(body["post_state"], schema).document()
            if not (pre == evidence["pre_state"] == payload["pre_state"]) \
                    or not (post == evidence["post_state"] == outcome["post_state"]):
                problems.append(f"{label}: a state identity does not recompute under {schema}")
                continue
            if pre != state or (first and not _same(body["pre_state"],
                                                    plan["initial_world_state"])):
                problems.append(f"{label}: its pre-state is not the state the episode was in")
                continue
            state, first = post, False
            chained += 1
    total = len(chains)
    if bound != total or chained != total:
        problems.append(f"{bound} decision-bound and {chained} state-chained transitions for "
                        f"{total} journaled")
    return problems, {"counts": {"decision_bound": bound, "state_chained": chained},
                      "action_inputs": dict(sorted(inputs.items())),
                      "admissibility": dict(sorted(verdicts.items()))}


def _replayed(replay: Mapping[str, Any], contract: WorldContractV1, applied: int) -> list[str]:
    problems = [str(problem) for problem in replay.get("problems", ())]
    if replay.get("schema") != REPLAY_REPORT_SCHEMA:
        problems.append(f"not a {REPLAY_REPORT_SCHEMA}")
    if replay.get("verdict") != REPLAYED:
        problems.append(f"the World replay is {replay.get('verdict')}")
    if replay.get("world") != contract.plugin:
        problems.append(f"the replay is of World {replay.get('world')!r}, the contract is of "
                        f"{contract.plugin!r}")
    if replay.get("transitions") != applied or list(replay.get("passes") or ()) != list(PASSES):
        problems.append(f"the replay covers {replay.get('transitions')} transitions by passes "
                        f"{replay.get('passes')}; {applied} are journaled")
    return problems


def assess_l3_conformance_v1(root: Path, *, problems: list[str] | None = None,
                             l1: Mapping[str, Any] | None = None,
                             replay: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Decide the P18 L3 conformance claim of the package at *root* (pure).

    *problems* is a ``verify_package_v4`` result, *l1* the L1 claim the caller
    already holds and *replay* the World replay report of this package (W5).
    """

    root = Path(root)
    if l1 is None:
        l1 = assess_l1_conformance_v1(
            root, problems=verify_package_v4(root) if problems is None else problems)
    results: dict[str, list[str] | None] = {name: None for _, name in CRITERIA}
    counts: dict[str, int] = {}
    detail: dict[str, Any] = {}
    edges: list[dict] = []
    contract: WorldContractV1 | None = None
    failing = [item["id"] for item in l1["criteria"] if item["status"] != PASS]
    results["l1_conformant"] = ([] if l1["level"] == L1 else
                                [f"the package is {l1['level']}: {', '.join(failing)}"])
    if not results["l1_conformant"]:
        try:
            manifest = read_manifest4(root / MANIFEST_NAME)
            (plan_document,) = _member_documents(root, manifest, "plan")
            (attestation,) = _member_documents(root, manifest, "conformance_attestation")
            (dataset,) = _member_documents(root, manifest, "dataset_units")
            plan = plan_document["plan"]
            protocol = ProtocolIR.from_document(plan["protocol"])
            contract, edges, results["world_declared"] = world_edges(plan, protocol)
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                AttributeError) as error:
            # SV-10 (SV-03 M-15): beside what the criterion already decided
            results["world_declared"] = [*(results["world_declared"] or ()),
                                         f"package does not read as an L3 run: {error}"]
    if contract is not None and not results["world_declared"]:
        try:
            journal = Journal2(root).read()
            episodes = list(attestation["episodes"])
            keys = _step_keys(protocol, episodes)
            generic, _, _ = _generic_protocol(protocol, journal, keys)
            planned = sum(
                protocol.executions(episode["rounds_executed"], episode.get("steps"))[edge["world"]]
                for episode in episodes for edge in edges
            )
            world, chains, counts = _world_events(root, protocol, journal, keys, planned)
            results["generic_transition"] = [*generic, *world]
            if not results["generic_transition"]:
                try:
                    results["decision_world_lineage"], detail = _lineage(
                        root, manifest, plan, contract, edges, journal, keys, chains,
                        dataset, episodes)
                    counts = {**counts, **detail.pop("counts")}
                except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                        AttributeError) as error:
                    results["decision_world_lineage"] = [
                        f"World lineage evidence does not read: {error}"]
                if replay is not None:
                    results["independently_replayed"] = _replayed(
                        replay, contract, counts["applied"])
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                AttributeError) as error:
            results["generic_transition"] = [*(results["generic_transition"] or ()),
                                             f"package does not read as an L3 run: {error}"]
    criteria = [
        {"id": key, "criterion": name,
         "status": NOT_EVALUATED if results[name] is None else FAIL if results[name] else PASS,
         "problems": list(results[name] or ())}
        for key, name in CRITERIA
    ]
    conformant = all(item["status"] == PASS for item in criteria)
    return {
        "schema": L3_CONFORMANCE_SCHEMA,
        "level": L3 if conformant else NOT_L3,
        "criteria": criteria,
        "world": None if contract is None else {
            "plugin": contract.plugin, "state_schema": contract.state_schema.ref,
            "action_schema": contract.action_schema.ref,
            "no_action": contract.progression.no_action, "rng_policy": contract.rng.policy},
        "edges": edges,
        "transitions": counts,
        **detail,
    }

