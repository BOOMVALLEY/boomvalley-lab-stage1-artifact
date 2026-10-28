"""P18 L4 conformance claim over one manifest-4 package (T4-GATE).

An L3 claim (``l3_conformance.py``) says one authoritative decision changed an
explicit environment through the plan's generic Protocol IR, and that somebody
holding only the World's code recomputed it.  An L4 claim is about time: the
organization met the World it left, round after round, until a declared rule
said stop, and whatever it remembered on the way is evidence an actor was
handed through a declared source.  ``assess_l4_conformance_v1`` decides it
(study-neutral: the plan is the only source of expected structure):

    X1 l3_conformant           the package's L3 claim is ``L3`` (so it is L1,
                               freezes a World contract, and its transitions
                               were replayed by the verifier)
    X2 longitudinal_declared   the plan's Protocol IR carries a round contract
                               (``bvl-round-contract-1`` / ``-2``: a safety
                               bound and one registered termination rule), the
                               plan carries no ``initial_memory``, every
                               ``memory_update`` node declares a closed memory
                               lifecycle (none keeps the K0 spike semantics)
                               and every ``memory_artifact`` source names such
                               a node; the attestation states the round
                               contract, the state chain and the memory
                               lifecycle it was verified on
    X3 rounds_terminated       per episode the journal opens and closes rounds
                               1..n exactly once each, n within the safety
                               bound; every termination verdict is of the
                               plan's rule, every one but the last is
                               CONTINUE, and the last - after round n - is the
                               one TERMINATE; EPISODE_COMPLETED and the
                               attestation state n rounds
    X4 state_chain_continuous  World(t) -> World(t+1): the chain re-walked
                               from the package's evidence
                               (``state_chain.run_state_chain``) is CONTINUOUS,
                               covers exactly the executed rounds and the
                               journaled transitions, and its origin and heads
                               are the ones the attestation states
    X5 memory_explicit         memory is evidence and a declared P05 source,
                               and nothing else: one MEMORY_RECORDED and one
                               memory member per executed ``memory_update``
                               step, each of its node's declared owner and key
                               and derived from a World transition committed
                               earlier in its own round; a request names
                               memory exactly for the ``memory_artifact``
                               sources its actor is granted, and every
                               artifact it names was recorded before the call
                               intent, by that source's node, and is valid in
                               the request's round or episode.  A plan with no
                               ``memory_update`` node passes on zero artifacts

X1 carries the L3 claim's dependence on the caller's World replay: without one
it is NOT_EVALUATED and the claim is ``NOT_L4``.  The claim is ``L4`` iff every
criterion passes.  The exact content of every round, verdict and artifact is
``verify_package_v4``'s to recompute (the L1 claim requires it); this claim
counts that the longitudinal structure the plan declares is the one the
evidence holds.  Nothing is written.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.core.strict_json import load_bytes
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    EPISODE_COMPLETED,
    EPISODE_OPENED,
    MEMORY_RECORDED,
    ROUND_COMPLETED,
    ROUND_OPENED,
    TERMINATION_EVALUATED,
    WORLD_APPLIED,
    Journal2,
)
from boomvalley_lab.kernel.l1_conformance import (
    FAIL,
    NOT_EVALUATED,
    PASS,
    _member_documents,
    assess_l1_conformance_v1,
)
from boomvalley_lab.kernel.l2_conformance import _step_keys
from boomvalley_lab.kernel.l3_conformance import L3, assess_l3_conformance_v1
from boomvalley_lab.kernel.manifest4 import read_manifest4
from boomvalley_lab.kernel.memory import MEMORY_CHECK, memory_policies
from boomvalley_lab.kernel.package4 import MANIFEST_NAME, ROUND_CHECK, verify_package_v4
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.rounds import TERMINATE
from boomvalley_lab.kernel.state_chain import (
    CONTINUOUS,
    STATE_CHAIN_CHECK,
    attested_chain,
    run_state_chain,
)

L4_CONFORMANCE_SCHEMA = "bvl-l4-conformance-1"
L4 = "L4"
NOT_L4 = "NOT_L4"
MEMORY_ARTIFACT = "memory_artifact"

CRITERIA = (
    ("X1", "l3_conformant"),
    ("X2", "longitudinal_declared"),
    ("X3", "rounds_terminated"),
    ("X4", "state_chain_continuous"),
    ("X5", "memory_explicit"),
)


def _l3_status(l3: Mapping[str, Any]) -> list[str] | None:
    """X1: [] when L3, None when only the caller's replay is missing, else why not."""

    if l3["level"] == L3:
        return []
    open_ = [item for item in l3["criteria"] if item["status"] != PASS]
    if [(item["id"], item["status"]) for item in open_] == [("W5", NOT_EVALUATED)]:
        return None
    return [f"the package is {l3['level']}: {', '.join(item['id'] for item in open_)}"]


def _declared(plan: Mapping[str, Any], protocol: ProtocolIR, attestation: Mapping[str, Any]
              ) -> tuple[list[str], dict[str, Any]]:
    """X2, and the plan's memory lifecycles and ``memory_artifact`` sources."""

    contract = protocol.round
    if contract is None:
        return ["the plan's Protocol IR carries no round contract: its rounds are a bare "
                "repetition count without termination evidence (not an L4 run)"], {}
    problems: list[str] = []
    if plan.get("initial_memory"):
        problems.append("the plan carries initial_memory: memory that no evidence produced")
    nodes = [node.node_id for node in protocol.nodes if node.kind is NodeKind.MEMORY_UPDATE]
    policies = memory_policies(protocol)
    if nodes and not policies:
        problems.append(f"memory_update nodes {nodes} declare no memory lifecycle (the K0 "
                        "spike semantics): their memory is no declared P05 source")
    information = plan.get("information")
    sources = {source["source_id"]: source["producer"]
               for source in (information or {}).get("sources", ())
               if source.get("source_kind") == MEMORY_ARTIFACT}
    problems += [f"memory_artifact source {source!r} names no memory_update node declaring a "
                 f"lifecycle ({producer!r})"
                 for source, producer in sorted(sources.items()) if producer not in policies]
    checks = list(attestation["checks"])
    stated = attestation.get("round_contract") or {}
    if ROUND_CHECK not in checks or stated.get("termination") != \
            contract.termination.identity.document() \
            or stated.get("max_rounds") != contract.max_rounds:
        problems.append("the attestation does not state the plan's round contract")
    if STATE_CHAIN_CHECK not in checks:
        problems.append("the attestation states no World state chain")
    lifecycle = attestation.get("memory_lifecycle") or {}
    if policies and (MEMORY_CHECK not in checks
                     or sorted(lifecycle.get("nodes", ())) != sorted(policies)
                     or dict(lifecycle.get("sources", {})) != sources):
        problems.append("the attestation does not state the plan's memory lifecycle")
    return problems, {"policies": policies, "sources": sources}


def _rounds(protocol: ProtocolIR, journal: list[dict], episodes: list[Mapping]
            ) -> tuple[list[str], dict[str, Any]]:
    contract = protocol.round
    rule = contract.termination.identity.document()
    opened_at = {str(r["episode"]): r["episode_key"] for r in journal
                 if r["event"] == EPISODE_OPENED}
    events: dict[str, list[dict]] = {key: [] for key in opened_at.values()}
    for record in journal:
        if record["event"] in (ROUND_OPENED, ROUND_COMPLETED, TERMINATION_EVALUATED,
                               EPISODE_COMPLETED):
            events.setdefault(opened_at.get(str(record.get("episode")), "?"), []).append(record)
    problems: list[str] = []
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    executed: dict[str, int] = {}
    if "?" in events:
        problems.append(f"{len(events.pop('?'))} round events name no opened episode")
    if sorted(events) != sorted(episode["episode_key"] for episode in episodes):
        problems.append(f"the journal opens episodes {sorted(events)}, the attestation states "
                        f"{sorted(episode['episode_key'] for episode in episodes)}")
    for episode in episodes:
        key = episode["episode_key"]
        mine = events.get(key, [])
        opened = [r["round"] for r in mine if r["event"] == ROUND_OPENED]
        closed = [r["round"] for r in mine if r["event"] == ROUND_COMPLETED]
        verdicts = [r for r in mine if r["event"] == TERMINATION_EVALUATED]
        completed = [r for r in mine if r["event"] == EPISODE_COMPLETED]
        n = len(opened)
        executed[key] = n
        counts.update(episodes=1, rounds_opened=n, rounds_closed=len(closed),
                      verdicts=len(verdicts),
                      terminations=sum(1 for r in verdicts if r["terminate"] is True))
        label = f"episode {key!r}"
        if not n or opened != list(range(1, n + 1)) or closed != opened:
            problems.append(f"{label} opens rounds {opened} and closes {closed}: not rounds "
                            "1..n, each once")
            continue
        if n > contract.max_rounds:
            problems.append(f"{label} executed {n} rounds beyond the safety bound "
                            f"{contract.max_rounds}")
        if len(completed) != 1 or completed[0]["rounds"] != n \
                or episode["rounds_executed"] != n:
            problems.append(f"{label} opened {n} rounds; EPISODE_COMPLETED and the attestation "
                            "state another count")
        if any(r["termination"].get("rule") != rule
               or r["terminate"] is not (r["termination"].get("verdict") == TERMINATE)
               for r in verdicts):
            problems.append(f"{label} has a termination verdict that is not of the plan's rule")
            continue
        last = verdicts[-1] if verdicts else None
        # a rule timed before_observation ends the episode on the round it never opens
        if last is None or last["terminate"] is not True or last["round"] not in (n, n + 1) \
                or any(r["terminate"] for r in verdicts[:-1]):
            problems.append(f"{label} does not end at exactly one TERMINATE verdict, at its "
                            f"last round {n}")
            continue
        if not set(range(1, n)) <= {r["round"] for r in verdicts}:
            problems.append(f"{label} continued past a round without a termination verdict")
            continue
        reasons[str(last["termination"].get("reason"))] += 1
    return problems, {"counts": dict(sorted(counts.items())), "executed": executed,
                      "terminated_by": dict(sorted(reasons.items()))}


def _chain(root: Path, attestation: Mapping[str, Any], executed: Mapping[str, int],
           applied: int, chain: Mapping[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    if chain is None:
        chain = run_state_chain(root)[1]
    problems = [str(problem) for problem in chain.get("problems", ())]
    summary = {"verdict": chain.get("verdict"), "origin": chain.get("origin"),
               "reset": chain.get("reset"), "rounds": chain.get("rounds"),
               "transitions": chain.get("transitions"), "links": chain.get("links")}
    if chain.get("verdict") != CONTINUOUS:
        problems.append(f"the World state chain is {chain.get('verdict')}")
        return problems, summary
    if {key: item["rounds"] for key, item in chain["episodes"].items()} != dict(executed):
        problems.append("the chain does not cover exactly the executed rounds of every episode")
    walked = sum(item["transitions"] for item in chain["episodes"].values())
    if walked != applied:
        problems.append(f"the chain walks {walked} transitions; {applied} are journaled")
    if attested_chain(chain) != attestation.get("state_chain"):
        problems.append("the attestation states another chain (origin, heads or links) than "
                        "the evidence re-walks to")
    return problems, summary


def _memory(root: Path, manifest: Any, plan: Mapping[str, Any], protocol: ProtocolIR,
            journal: list[dict], keys: Mapping[str, tuple], episodes: list[Mapping],
            declared: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    policies, sources = declared["policies"], declared["sources"]
    identity_of = {episode["episode_key"]: dict(episode["episode"]) for episode in episodes}
    members = {m["identity"]["digest"]: m for m in _member_documents(root, manifest, "memory")}
    requests = {Path(member.path).name: member.path for member in manifest.members
                if member.role == "request"}
    grants = {grant["actor_id"]: sorted(s for s in grant["sources"] if s in sources)
              for grant in (plan.get("information") or {}).get("grants", ())}
    applied: dict[str, tuple] = {}
    recorded: dict[str, tuple[int, tuple]] = {}
    problems: list[str] = []
    planned = sum(1 for where in keys.values()
                  if protocol.node(where[2]).kind is NodeKind.MEMORY_UPDATE)
    scopes: Counter[str] = Counter()
    observed = observing = 0
    for record in journal:
        where = keys.get(record.get("step"))
        if record["event"] == WORLD_APPLIED and where is not None:
            applied[record["transition"]["digest"]] = (record["sequence"], where)
        elif record["event"] == MEMORY_RECORDED:
            label = f"journal-2 #{record['sequence']} MEMORY_RECORDED"
            digest = record["memory"]["identity"]["digest"]
            member = members.get(digest)
            policy = None if where is None else policies.get(where[2])
            if where is None or policy is None or member is None or digest in recorded:
                problems.append(f"{label} is of no memory_update step declaring a lifecycle, "
                                "has no memory member, or repeats an artifact")
                continue
            recorded[digest] = (record["sequence"], where)
            if (member.get("owner"), member.get("key"), member.get("scope"),
                    member.get("round"), member.get("episode")) != (
                    policy.owner, policy.key, policy.scope, where[1], identity_of[where[0]]) \
                    or (record["memory"].get("owner"), record["memory"].get("key")) != (
                        policy.owner, policy.key):
                problems.append(f"{label} is not its node's declared owner, key and scope in "
                                "its own episode and round")
                continue
            source = applied.get((member.get("source_transition") or {}).get("digest"))
            if source is None or source[1][:2] != where[:2] \
                    or source[1][2] not in protocol.node(where[2]).depends_on:
                problems.append(f"{label} derives from no World transition its node depends "
                                "on, committed earlier in its round")
                continue
            scopes[policy.scope] += 1
        elif record["event"] == CALL_INTENT_RECORDED and where is not None:
            label = f"request of {where}"
            path = requests.get(record["request"].get("name"))
            request = None if path is None else load_bytes((root / path).read_bytes())
            if not isinstance(request, Mapping):
                problems.append(f"{label} is no package member")
                continue
            granted = grants.get(protocol.node(where[2]).config.get("actor"), [])
            named = request.get("memory")
            if not granted:
                if named is not None:
                    problems.append(f"{label} names memory; its actor is granted no "
                                    "memory_artifact source")
                continue
            if not isinstance(named, list) or [item.get("source_id") for item in named] \
                    != granted or any(item.get("producer") != sources[item["source_id"]]
                                      for item in named):
                problems.append(f"{label} does not name exactly the memory_artifact sources "
                                f"its actor is granted {granted}")
                continue
            observing += 1
            for item in named:
                for artifact in item["artifacts"]:
                    held = recorded.get(artifact.get("digest"))
                    member = members.get(artifact.get("digest"))
                    if held is None or member is None or held[0] > record["sequence"] \
                            or held[1][2] != item["producer"]:
                        problems.append(f"{label} names an artifact of {item['source_id']!r} "
                                        "its node did not record before the call intent")
                        continue
                    valid = member.get("valid") or {}
                    same = held[1][0] == where[0]
                    if not (valid.get("from_round", 0) <= where[1]
                            <= valid.get("through_round", -1) if same
                            else where[0] in valid.get("episodes", ())):
                        problems.append(f"{label} names an artifact of {item['source_id']!r} "
                                        "outside its validity (round, or carry episodes)")
                        continue
                    observed += 1
    counts = {"planned_updates": planned, "recorded": len(recorded),
              "memory_members": len(members), "requests_observing_memory": observing,
              "artifacts_observed": observed}
    if not (planned == len(recorded) == len(members)):
        problems.append(f"{len(recorded)} recorded and {len(members)} memory members for "
                        f"{planned} executed memory_update steps")
    return problems, {"counts": counts, "scopes": dict(sorted(scopes.items())),
                      "nodes": {node: {"owner": p.owner, "key": p.key, "scope": p.scope,
                                       "retention": p.retention,
                                       **({"regime_change": p.regime_change}
                                          if p.extended else {})}
                                for node, p in sorted(policies.items())},
                      "sources": dict(sorted(sources.items()))}


def assess_l4_conformance_v1(root: Path, *, problems: list[str] | None = None,
                             l1: Mapping[str, Any] | None = None,
                             l3: Mapping[str, Any] | None = None,
                             replay: Mapping[str, Any] | None = None,
                             state_chain: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Decide the P18 L4 conformance claim of the package at *root* (pure).

    *problems* is a ``verify_package_v4`` result, *l1* and *l3* the claims the
    caller already holds, *replay* the World replay report an L3 claim is
    decided with when *l3* is not given, and *state_chain* the
    ``run_state_chain`` document of this package when the caller has walked it.
    """

    root = Path(root)
    if l3 is None:
        if l1 is None:
            l1 = assess_l1_conformance_v1(
                root, problems=verify_package_v4(root) if problems is None else problems)
        l3 = assess_l3_conformance_v1(root, problems=problems, l1=l1, replay=replay)
    results: dict[str, list[str] | None] = {name: None for _, name in CRITERIA}
    results["l3_conformant"] = _l3_status(l3)
    detail: dict[str, Any] = {}
    contract = None
    # the structure below reads a package whose World lineage holds (W1 to W4)
    readable = all(item["status"] == PASS for item in l3["criteria"] if item["id"] != "W5")
    if readable:
        try:
            manifest = read_manifest4(root / MANIFEST_NAME)
            (plan_document,) = _member_documents(root, manifest, "plan")
            (attestation,) = _member_documents(root, manifest, "conformance_attestation")
            plan = plan_document["plan"]
            protocol = ProtocolIR.from_document(plan["protocol"])
            contract = protocol.round
            results["longitudinal_declared"], declared = _declared(plan, protocol, attestation)
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
            results["longitudinal_declared"] = [f"package does not read as an L4 run: {error}"]
    if contract is not None and results["longitudinal_declared"] == []:
        try:
            journal = Journal2(root).read()
            episodes = list(attestation["episodes"])
            results["rounds_terminated"], rounds = _rounds(protocol, journal, episodes)
            detail["rounds"] = rounds["counts"]
            detail["terminated_by"] = rounds["terminated_by"]
            if not results["rounds_terminated"]:
                results["state_chain_continuous"], detail["state_chain"] = _chain(
                    root, attestation, rounds["executed"],
                    l3.get("transitions", {}).get("applied", 0), state_chain)
                results["memory_explicit"], memory = _memory(
                    root, manifest, plan, protocol, journal, _step_keys(protocol, episodes),
                    episodes, declared)
                detail["memory"] = memory
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                AttributeError) as error:
            results["rounds_terminated"] = [
                *(results["rounds_terminated"] or ()),
                f"package does not read as an L4 run: {error}"]
    criteria = [
        {"id": key, "criterion": name,
         "status": NOT_EVALUATED if results[name] is None else FAIL if results[name] else PASS,
         "problems": list(results[name] or ())}
        for key, name in CRITERIA
    ]
    conformant = all(item["status"] == PASS for item in criteria)
    return {
        "schema": L4_CONFORMANCE_SCHEMA,
        "level": L4 if conformant else NOT_L4,
        "criteria": criteria,
        "round_contract": None if contract is None else {
            "schema": contract.schema, "max_rounds": contract.max_rounds,
            "termination_rule": contract.termination.rule,
            # a contract that declares no timing (T4-001) states none
            **({} if contract.timing is None else {"timing": contract.timing})},
        **detail,
    }
