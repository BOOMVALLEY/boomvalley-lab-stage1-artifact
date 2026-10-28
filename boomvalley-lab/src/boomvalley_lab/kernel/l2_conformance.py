"""P18 L2 conformance claim over one manifest-4 package (T2-GATE).

An L1 claim (``l1_conformance.py``) says a run came from a declaration and
registered plugins only, with every provider call accounted for.  An L2 claim
adds the interaction: one actor's committed output was an authorized input of
a later actor in the same episode, the order of that interaction was the plan's
generic Protocol IR and nothing else, and every such hand-over is evidenced end
to end.  ``assess_l2_conformance_v1`` decides it from the package alone
(study-neutral: the plan is the only source of expected structure):

    D1 l1_conformant        the package's L1 claim is ``L1`` (P18: L2 proven
                            requires L1 proven)
    D2 interaction_declared the plan grants at least one ``actor_output``
                            source to another actor than the one that produced
                            it, and every granted actor_output is produced by
                            an IR ancestor of the call that observes it - an
                            actor-to-actor edge of the plan
    D3 generic_protocol     no custom interaction runner: the plan protocol is
                            the closed ``bvl-protocol-ir-1`` (generic node
                            kinds only, no construct left), and the journal is
                            that IR executed: per episode and executed round
                            every IR node is ready exactly once and commits
                            exactly once with the event of its kind, never
                            before a dependency committed; no step and no call
                            exists outside the IR
    D4 actor_lineage        complete actor-to-actor evidence lineage: for every
                            plan edge, episode and executed round the producer
                            committed (call -> proposal) before the consumer's
                            call intent, the consumer observed exactly the
                            producer's committed bytes, its request-2
                            ``upstream`` names exactly the producer's committed
                            identity, and no request carries an ``upstream``
                            entry that is not a plan edge; a withheld
                            actor_output is observed by no call

The claim is ``L2`` iff every criterion passes, else ``NOT_L2`` with the
failing criteria's problems.  Nothing is written.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.core.strict_json import load_bytes
from boomvalley_lab.kernel.custody2 import read_intent_request_v2
from boomvalley_lab.kernel.identity import StepIdentity
from boomvalley_lab.kernel.journal2 import CALL_INTENT_RECORDED, STEP_READY, Journal2
from boomvalley_lab.kernel.l1_conformance import (
    FAIL,
    L1,
    NOT_EVALUATED,
    PASS,
    assess_l1_conformance_v1,
)
from boomvalley_lab.kernel.manifest4 import read_manifest4
from boomvalley_lab.kernel.package4 import MANIFEST_NAME, verify_package_v4
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.readiness import COMMIT_EVENT
from boomvalley_lab.kernel.request_store import RequestStoreV2

L2_CONFORMANCE_SCHEMA = "bvl-l2-conformance-1"
L2 = "L2"
NOT_L2 = "NOT_L2"
ACTOR_OUTPUT = "actor_output"

CRITERIA = (
    ("D1", "l1_conformant"),
    ("D2", "interaction_declared"),
    ("D3", "generic_protocol"),
    ("D4", "actor_lineage"),
)


def _member_documents(root: Path, manifest: Any, role: str) -> list[Any]:
    return [load_bytes((root / member.path).read_bytes())
            for member in sorted(manifest.members, key=lambda item: item.path)
            if member.role == role]


def _ancestors(protocol: ProtocolIR, node_id: str) -> set[str]:
    found: set[str] = set()
    pending = list(protocol.node(node_id).depends_on)
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(protocol.node(current).depends_on)
    return found


def _producing_call(protocol: ProtocolIR, producer: str) -> str | None:
    """The actor_call node whose output *producer* carries (itself, or the call it parses)."""

    node = protocol.node(producer)
    if node.kind is NodeKind.ACTOR_CALL:
        return producer
    calls = [dep for dep in node.depends_on
             if protocol.node(dep).kind is NodeKind.ACTOR_CALL]
    return calls[0] if node.kind is NodeKind.PROPOSAL_PARSE and len(calls) == 1 else None


def plan_edges(plan: Mapping[str, Any], protocol: ProtocolIR) -> tuple[list[dict], list[str]]:
    """The plan's actor-to-actor edges: one per (consumer call node, granted actor_output)."""

    information = plan.get("information")
    if not isinstance(information, Mapping):
        return [], ["plan binds no 'information' section: no actor_output can be granted"]
    outputs = {source["source_id"]: source["producer"] for source in information["sources"]
               if source.get("source_kind") == ACTOR_OUTPUT}
    grants = {grant["actor_id"]: [s for s in grant["sources"] if s in outputs]
              for grant in information["grants"]}
    edges: list[dict] = []
    problems: list[str] = []
    for node in protocol.nodes:
        if node.kind is not NodeKind.ACTOR_CALL:
            continue
        consumer = node.config.get("actor")
        for source in sorted(grants.get(consumer, ())):
            producer = outputs[source]
            if producer not in {item.node_id for item in protocol.nodes}:
                problems.append(f"actor_output {source!r} names no IR node ({producer!r})")
                continue
            call = _producing_call(protocol, producer)
            if call is None:
                problems.append(f"actor_output {source!r} is produced by no actor call")
                continue
            if producer not in _ancestors(protocol, node.node_id):
                problems.append(f"{node.node_id!r} observes {source!r} but does not depend on "
                                f"its producer {producer!r}")
                continue
            edges.append({
                "source": source, "producer": producer,
                "producer_kind": protocol.node(producer).kind.value,
                "producer_call": call,
                "producer_actor": protocol.node(call).config.get("actor"),
                "consumer": node.node_id, "consumer_actor": consumer,
            })
    return edges, problems


def _interaction(edges: list[dict], problems: list[str]) -> list[str]:
    if problems:
        return problems
    if not any(edge["producer_actor"] != edge["consumer_actor"] for edge in edges):
        return ["the plan grants no actor_output source to another actor: no actor-to-actor "
                "interaction is declared (an L1 run)"]
    return []


def _step_keys(protocol: ProtocolIR, episodes: list[Mapping]) -> dict[str, tuple]:
    """Recomputed StepIdentity -> (episode_key, round, node id) for every executed step."""

    return {
        str(StepIdentity.of_payload({"episode": dict(episode["episode"]), "round": round_index,
                                     "node": node.node_id, "kind": node.kind.value})):
        (episode["episode_key"], round_index, node.node_id)
        for episode in episodes
        for executed in (protocol.executions(episode["rounds_executed"], episode.get("steps")),)
        for round_index in range(1, episode["rounds_executed"] + 1)
        for node in protocol.nodes
        if round_index <= executed[node.node_id]
    }


def _generic_protocol(protocol: ProtocolIR, journal: list[dict], keys: Mapping[str, tuple]
                      ) -> tuple[list[str], dict[tuple, int], dict[str, int]]:
    """The journal is the IR executed.  Returns (problems, commit sequences, counts)."""

    problems: list[str] = []
    ready: dict[tuple, list[int]] = {}
    commits: dict[tuple, list[int]] = {}
    outside = 0
    for record in journal:
        step = record.get("step")
        if step is None:
            continue
        where = keys.get(step)
        if where is None:
            outside += 1
            continue
        kind = protocol.node(where[2]).kind
        if record["event"] == STEP_READY:
            ready.setdefault(where, []).append(record["sequence"])
        elif record["event"] == COMMIT_EVENT.get(kind):
            commits.setdefault(where, []).append(record["sequence"])
        elif record["event"] in COMMIT_EVENT.values():
            problems.append(f"step {where} of kind {kind.value} committed as {record['event']}")
        if record["event"] == CALL_INTENT_RECORDED and kind is not NodeKind.ACTOR_CALL:
            problems.append(f"a call intent at {where}, which is not an actor_call node")
    if outside:
        problems.append(f"{outside} journal records name a step outside the IR")
    committed: dict[tuple, int] = {}
    for where in keys.values():
        node = protocol.node(where[2])
        if len(ready.get(where, ())) != 1:
            problems.append(f"step {where} is ready {len(ready.get(where, ()))} times")
            continue
        expects_commit = node.kind in COMMIT_EVENT
        if len(commits.get(where, ())) != (1 if expects_commit else 0):
            problems.append(f"step {where} commits {len(commits.get(where, ()))} times")
            continue
        committed[where] = commits[where][0] if expects_commit else ready[where][0]
        if committed[where] < ready[where][0]:
            problems.append(f"step {where} committed before it was ready")
    for where in keys.values():
        if where not in committed:
            continue
        for dependency in protocol.node(where[2]).depends_on:
            upstream = committed.get((where[0], where[1], dependency))
            if upstream is None or upstream > ready[where][0]:
                problems.append(f"step {where} was ready before its dependency "
                                f"{dependency!r} committed")
    return problems, committed, {"steps": len(committed), "planned_steps": len(keys)}


def _produced(edge: Mapping[str, Any], position: tuple, calls: Mapping[tuple, Mapping],
              proposals: Mapping[tuple, Mapping]) -> tuple[dict | None, str | None]:
    """The committed (identity, content digest) an edge carries at *position*, or a problem."""

    episode_key, round_index = position
    call = calls.get((episode_key, round_index, edge["producer_call"]))
    if call is None:
        return None, f"producer call {edge['producer_call']!r} has no call unit"
    if call["actor_id"] != edge["producer_actor"]:
        return None, f"producer call is by {call['actor_id']!r}, not {edge['producer_actor']!r}"
    if edge["producer_kind"] == NodeKind.ACTOR_CALL.value:
        algorithm, _, digest = str(call["response"]["content"]).partition(":")
        if algorithm != "sha256":
            return None, "producer response is not a sha256 artifact"
        return {"identity": call["unit"], "content_sha256": digest}, None
    proposal = proposals.get((episode_key, round_index, edge["producer"]))
    if proposal is None:
        return None, f"producer {edge['producer']!r} has no proposal unit"
    if proposal["call"] != call["unit"] or proposal["actor_id"] != edge["producer_actor"]:
        return None, f"proposal at {edge['producer']!r} is not of its actor's call in the round"
    if not isinstance(proposal.get("value"), Mapping):
        return None, f"proposal at {edge['producer']!r} committed no value"
    digest = sha256_bytes(canonical_json(dict(proposal["value"])).encode("utf-8")).hex
    return {"identity": proposal["unit"], "content_sha256": digest}, None


def _actor_lineage(root: Path, plan: Mapping[str, Any], edges: list[dict], journal: list[dict],
                   keys: Mapping[str, tuple], committed: Mapping[tuple, int],
                   dataset: Mapping[str, Any], episodes: list[Mapping]
                   ) -> tuple[list[str], dict[str, int]]:
    def located(units: list[Mapping]) -> dict[tuple, Mapping]:
        return {(u["episode_key"], u["round"], u["node"]): u for u in units}

    calls, proposals = located(dataset["calls"]), located(dataset["proposals"])
    intents = {record["call"]: record for record in journal
               if record["event"] == CALL_INTENT_RECORDED}
    requests = RequestStoreV2(root)
    outputs = {source["source_id"] for source in plan["information"]["sources"]
               if source.get("source_kind") == ACTOR_OUTPUT}
    by_consumer: dict[str, list[dict]] = {}
    for edge in edges:
        by_consumer.setdefault(edge["consumer"], []).append(edge)
    problems: list[str] = []
    verified = carried = 0
    for where, unit in sorted(calls.items()):
        mine = by_consumer.get(where[2], [])
        key = f"{unit['unit']['kind']}:{unit['unit']['digest']}"
        intent = intents.get(key)
        if intent is None or keys.get(intent["step"]) != where:
            problems.append(f"call unit at {where} has no call intent at its IR step")
            continue
        request = load_bytes(read_intent_request_v2(intent, requests))
        expected = []
        for edge in mine:
            label = f"{edge['producer']} -> {where[2]} ({edge['source']}) round {where[1]}"
            found, problem = _produced(edge, where[:2], calls, proposals)
            if found is None:
                problems.append(f"{label}: {problem}")
                continue
            expected.append({"source_id": edge["source"], "producer": edge["producer"],
                             "producer_kind": edge["producer_kind"], **found})
            before = committed.get((where[0], where[1], edge["producer"]))
            if before is None or before > intent["sequence"]:
                problems.append(f"{label}: the consumer's call intent precedes the producer's "
                                "commit")
                continue
            access = unit["access"]
            if edge["source"] not in access["granted"]:
                problems.append(f"{label}: the consumer's access trace does not grant the source")
                continue
            if (edge["source"] not in access["transforms"]
                    and access["observation"].get(edge["source"]) != found["content_sha256"]):
                problems.append(f"{label}: the consumer observed other bytes than the producer "
                                "committed")
                continue
            verified += 1
        observed = sorted(set(unit["access"]["observation"]) & outputs)
        if observed != sorted(edge["source"] for edge in mine):
            problems.append(f"call at {where} observes actor outputs {observed}, the plan "
                            f"grants {sorted(edge['source'] for edge in mine)}")
        upstream = request.get("upstream", [])
        carried += len(upstream)
        if upstream != expected or ("upstream" in request) != bool(mine):
            problems.append(f"request-2 of the call at {where} does not bind exactly the "
                            "committed identities of its plan edges as upstream")
    protocol = ProtocolIR.from_document(plan["protocol"])
    planned = sum(
        protocol.executions(episode["rounds_executed"], episode.get("steps"))[edge["consumer"]]
        for episode in episodes for edge in edges
    )
    if verified != planned or carried != planned:
        problems.append(f"{verified} verified and {carried} carried actor-to-actor hand-overs "
                        f"for {planned} planned")
    elif not planned:
        # SV-04: zero of zero is no hand-over (the episode ended before any consumer ran)
        problems.append("the run executed no actor-to-actor hand-over: none of the plan's "
                        "edges had its consumer called in the rounds that ran")
    return problems, {"planned_edges": planned, "verified_edges": verified,
                      "upstream_entries": carried}


def assess_l2_conformance_v1(root: Path, *, problems: list[str] | None = None,
                             l1: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Decide the P18 L2 conformance claim of the package at *root* (pure).

    *problems* is a ``verify_package_v4`` result and *l1* the L1 claim the
    caller already holds.
    """

    root = Path(root)
    if l1 is None:
        l1 = assess_l1_conformance_v1(
            root, problems=verify_package_v4(root) if problems is None else problems)
    results: dict[str, list[str] | None] = {name: None for _, name in CRITERIA}
    counts: dict[str, int] = {}
    edges: list[dict] = []
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
            journal = Journal2(root).read()
            episodes = list(attestation["episodes"])
            edges, edge_problems = plan_edges(plan, protocol)
            results["interaction_declared"] = _interaction(edges, edge_problems)
            keys = _step_keys(protocol, episodes)
            results["generic_protocol"], committed, counts = _generic_protocol(
                protocol, journal, keys)
            if not results["interaction_declared"] and not results["generic_protocol"]:
                try:
                    results["actor_lineage"], lineage = _actor_lineage(
                        root, plan, edges, journal, keys, committed, dataset, episodes)
                    counts = {**counts, **lineage}
                except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                        AttributeError) as error:
                    results["actor_lineage"] = [f"lineage evidence does not read: {error}"]
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                AttributeError) as error:
            # SV-10 (SV-03 M-15): beside what the criterion already decided
            results["generic_protocol"] = [*(results["generic_protocol"] or ()),
                                           f"package does not read as an L2 run: {error}"]
    criteria = [
        {"id": key, "criterion": name,
         "status": NOT_EVALUATED if results[name] is None else FAIL if results[name] else PASS,
         "problems": list(results[name] or ())}
        for key, name in CRITERIA
    ]
    conformant = all(item["status"] == PASS for item in criteria)
    pairs = Counter(f"{edge['producer_actor']}->{edge['consumer_actor']}" for edge in edges)
    return {
        "schema": L2_CONFORMANCE_SCHEMA,
        "level": L2 if conformant else NOT_L2,
        "criteria": criteria,
        "edges": [{name: edge[name] for name in ("source", "producer", "producer_actor",
                                                 "consumer", "consumer_actor")}
                  for edge in edges],
        "actor_pairs": dict(sorted(pairs.items())),
        "lineage": counts,
    }
