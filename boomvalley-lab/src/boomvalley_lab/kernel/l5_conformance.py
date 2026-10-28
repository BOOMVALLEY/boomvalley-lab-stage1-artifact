"""P18 L5 conformance claim over one manifest-4 package (T5-GATE).

L1 to L4 claims are about an organization whose every actor is a model: what
it was asked, who decided, what the World did, round after round.  An L5 claim
is about who answered: an actor of the plan may be a person (a ``humans``
contract, P17) or a tool (a ``tools`` contract), and then the package must
say, call by call, that the declared one answered - and nothing else did.
``assess_l5_conformance_v1`` decides it (study-neutral: the plan is the only
source of expected structure):

    Y1 l1_conformant           the package's L1 claim is ``L1``: it verifies,
                               was run from a declaration and registered
                               plugins under the strict gate, and its official
                               numbers are the pre-bound analysis's
    Y2 open_actors_declared    the plan contracts at least one human or tool
                               actor, every contracted actor answers an
                               ``actor_call`` node, and every actor is
                               answered by exactly one declared kind (call
                               provenance P1).  A plan whose every caller is a
                               model is not an L5 run
    Y3 calls_declared          hidden calls = 0: the call provenance of the
                               package (``call_provenance.py``, P1 to P5) is
                               ``ALL_DECLARED`` - every model transport, human
                               exchange and tool call is the one call of a
                               plan step by its declared caller
    Y4 human_exchanges_closed  every executed step of a human actor is one
                               accepted call answered by one received response
                               of a pseudonymous participant, delivered once
                               and received once; the package holds one
                               ``human_intent`` and one ``human_response``
                               member per exchange and a ``human_consent``
                               member for every consent an intent asks under.
                               No request is left waiting.  A plan with no
                               human actor passes on zero exchanges
    Y5 tool_calls_resolved     every executed step of a tool actor is one
                               accepted call answered by one tool intent that
                               reached its result, by the call or by a
                               journaled reconciliation, each after an attempt
                               that was started; no tool was started
                               again while an earlier attempt of a mutating
                               intent was unresolved (no blind retry), an
                               IRREVERSIBLE tool was started at most once per
                               intent, and no attempt is left with an unknown
                               outcome; the package holds one ``tool_intent``
                               and one ``tool_result`` member per call.  A
                               plan with no tool actor passes on zero calls

A contracted human or tool actor that no executed step called fails Y4 / Y5
(SV-04): zero exchanges of a declared person or tool are no evidence of who
answered.  A claim decided while some tool argument's declared selection was
not recomputed states ``limitations: ["TOOL_ARGUMENTS_NOT_REDERIVED"]`` and the
counts under ``tool.arguments``; the verifier re-derives an argument selected
from a frozen resource only from the bytes it is handed (``bvl verify
--experiment``).

The claim is ``L5`` iff every criterion passes.  It is a capability, not a rung
(PRD_MAP 2: a tier is a summary over a capability vector): it requires L1 and
neither a World nor rounds, and ``organization`` states the L1 to L4 claims the
caller holds for the same package.  The content of every exchange - identities,
consent terms, provenance grades, argument selection, response bytes - is the
call provenance's to recompute (Y3); Y4 and Y5 count that the participation
the plan declares is the participation the evidence closes.  Nothing is
written.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.kernel.call_provenance import (
    ALL_DECLARED,
    HUMAN,
    TOOL,
    assess_call_provenance_v1,
)
from boomvalley_lab.kernel.human import HumanActorContractSetV1
from boomvalley_lab.kernel.journal2 import (
    HUMAN_REQUEST_DELIVERED,
    HUMAN_RESPONSE_RECEIVED,
    TOOL_CALL_STARTED,
    TOOL_INTENT_RECORDED,
    TOOL_OUTCOME_UNKNOWN,
    TOOL_RECONCILED,
    TOOL_RETURNED,
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
from boomvalley_lab.kernel.l2_conformance import _step_keys
from boomvalley_lab.kernel.manifest4 import read_manifest4
from boomvalley_lab.kernel.package4 import MANIFEST_NAME, verify_package_v4
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.tool import ToolActorContractSetV1, ToolSideEffect
from boomvalley_lab.kernel.tool_call import ToolCallStateV1

L5_CONFORMANCE_SCHEMA = "bvl-l5-conformance-1"
L5 = "L5"
NOT_L5 = "NOT_L5"
#: SV-04: the claim was decided with tool arguments whose declared selection was
#: not recomputed (their frozen source was not handed to the verifier, T5-008)
ARGUMENTS_NOT_REDERIVED = "TOOL_ARGUMENTS_NOT_REDERIVED"
ACCEPTED = "ACCEPTED"
RECEIVED = "RECEIVED"

CRITERIA = (
    ("Y1", "l1_conformant"),
    ("Y2", "open_actors_declared"),
    ("Y3", "calls_declared"),
    ("Y4", "human_exchanges_closed"),
    ("Y5", "tool_calls_resolved"),
)

_PARTICIPANT = re.compile(r"participant:[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_TOOL_EVENTS = (TOOL_INTENT_RECORDED, TOOL_CALL_STARTED, TOOL_OUTCOME_UNKNOWN, TOOL_RETURNED,
                TOOL_RECONCILED)


def _failing(claim: Mapping[str, Any], what: str) -> list[str]:
    open_ = [item for item in claim["criteria"] if item["status"] != PASS]
    return [f"{what}: {', '.join(item['id'] for item in open_)}"] + [
        f"{item['id']} {problem}" for item in open_ for problem in item["problems"]]


def _declared(plan: Mapping[str, Any], protocol: ProtocolIR, calls: Mapping[str, Any]
              ) -> tuple[list[str], dict[str, Any]]:
    """Y2, and who the plan contracts: actor -> HUMAN | TOOL, and the tool contracts."""

    humans = (HumanActorContractSetV1.from_document(plan["humans"]).contracts
              if "humans" in plan else {})
    tools = (ToolActorContractSetV1.from_document(plan["tools"]).contracts
             if "tools" in plan else {})
    kinds = {**{actor: HUMAN for actor in humans}, **{actor: TOOL for actor in tools}}
    called = {node.config.get("actor") for node in protocol.nodes
              if node.kind is NodeKind.ACTOR_CALL}
    problems: list[str] = []
    if not kinds:
        problems.append("the plan contracts no human and no tool actor: every caller is a "
                        "model (not an L5 run)")
    problems += [f"{kinds[actor]} actor {actor!r} is contracted and answers no actor_call node"
                 for actor in sorted(kinds) if actor not in called]
    (declared,) = (item for item in calls["criteria"] if item["id"] == "P1")
    if declared["status"] != PASS:
        problems += [f"P1 {problem}" for problem in declared["problems"]] or [
            "who answers each actor is not declared (call provenance P1)"]
    return problems, {"kinds": kinds, "tools": tools}


def _steps(protocol: ProtocolIR, keys: Mapping[str, tuple], kinds: Mapping[str, str],
           kind: str) -> list[tuple]:
    """The executed (episode key, round, node) steps of the actors declared *kind*."""

    return sorted(where for where in keys.values()
                  if protocol.node(where[2]).kind is NodeKind.ACTOR_CALL
                  and kinds.get(protocol.node(where[2]).config.get("actor")) == kind)


def _unanswered(protocol: ProtocolIR, steps: list[tuple], kinds: Mapping[str, str],
                kind: str) -> list[str]:
    """SV-04: a contracted actor no executed step called answered nothing.

    Zero exchanges close zero steps, so the counts of Y4 / Y5 agree at zero; a
    run that ended before its person or its tool was ever asked is not evidence
    of who answered.
    """

    executed = {protocol.node(where[2]).config.get("actor") for where in steps}
    return [f"{kind} actor {actor!r} is contracted and no executed step called it: the run "
            "holds no exchange of it"
            for actor in sorted(kinds) if kinds[actor] == kind and actor not in executed]


def _rows(calls: Mapping[str, Any], kind: str) -> dict[tuple, list[Mapping[str, Any]]]:
    rows: dict[tuple, list[Mapping[str, Any]]] = {}
    for row in calls["calls"]:
        if row["kind"] == kind:
            rows.setdefault((row["episode_key"], row["round"], row["node"]), []).append(row)
    return rows


def _humans(root: Path, manifest: Any, journal: list[dict], steps: list[tuple],
            calls: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    rows = _rows(calls, HUMAN)
    problems = [f"a human exchange is journaled at {where}, which is no executed step of a "
                "human actor" for where in sorted(set(rows) - set(steps))]
    participants: Counter[str] = Counter()
    grades: Counter[str] = Counter()
    for where in steps:
        found = rows.get(where, [])
        label = f"{where[0]} round {where[1]} {where[2]!r}"
        if len(found) != 1:
            problems.append(f"{label} holds {len(found)} calls of its human actor; a step "
                            "is answered once")
            continue
        (row,) = found
        human = row.get("human") or {}
        if row["status"] != ACCEPTED or human.get("state") != RECEIVED:
            problems.append(f"{label} is {row['status']} with its request "
                            f"{human.get('state')}: the exchange is not closed")
            continue
        participant = human.get("participant")
        if not isinstance(participant, str) or not _PARTICIPANT.fullmatch(participant):
            problems.append(f"{label} was answered by {participant!r}, which is no "
                            "pseudonymous participant")
            continue
        if not human.get("intent") or not human.get("response") or not human.get("provenance"):
            problems.append(f"{label} states no intent, response or provenance of its answer")
            continue
        participants[participant] += 1
        grades[str(human["provenance"].get("grade"))] += 1
    delivered = sum(1 for r in journal if r["event"] == HUMAN_REQUEST_DELIVERED)
    received = sum(1 for r in journal if r["event"] == HUMAN_RESPONSE_RECEIVED)
    intents = _member_documents(root, manifest, "human_intent")
    responses = _member_documents(root, manifest, "human_response")
    consents = {str(document["identity"]["digest"])
                for document in _member_documents(root, manifest, "human_consent")}
    asked = {str(document["intent"]["consent"]["digest"]) for document in intents}
    counts = {"steps": len(steps), "delivered": delivered, "received": received,
              "intent_members": len(intents), "response_members": len(responses),
              "consent_members": len(consents)}
    if not (len(steps) == delivered == received == len(intents) == len(responses)):
        problems.append(f"{len(steps)} executed human steps; {delivered} requests delivered, "
                        f"{received} responses received, {len(intents)} intent and "
                        f"{len(responses)} response members")
    if asked != consents:
        problems.append(f"the intents ask under {len(asked)} consents; the package holds "
                        f"{len(consents)} consent members, {len(asked & consents)} of them")
    return problems, {"counts": counts, "participants": len(participants),
                      "provenance_grades": dict(sorted(grades.items()))}


def _attempts(journal: list[dict], side_effects: Mapping[str, ToolSideEffect]
              ) -> tuple[list[str], Counter[str]]:
    """Blind retries, read from the journal alone: (problems, counts)."""

    problems: list[str] = []
    counts: Counter[str] = Counter()
    chains: dict[str, list[dict]] = {}
    for record in journal:
        if record["event"] in _TOOL_EVENTS:
            chains.setdefault(record["tool_intent"], []).append(record)
    for key, chain in chains.items():
        side_effect = side_effects.get(key)
        started = 0
        unresolved = False
        for record in chain:
            event = record["event"]
            if event == TOOL_CALL_STARTED:
                started += 1
                if unresolved and side_effect is not ToolSideEffect.NONE:
                    problems.append(
                        f"tool intent {key} was started again at sequence "
                        f"{record['sequence']} while its earlier attempt was unresolved: a "
                        "blind retry")
                if started > 1 and side_effect is ToolSideEffect.IRREVERSIBLE:
                    problems.append(f"IRREVERSIBLE tool intent {key} was started {started} "
                                    "times")
                unresolved = True
            elif event == TOOL_OUTCOME_UNKNOWN:
                counts["unknown_outcomes"] += 1
            elif event in (TOOL_RETURNED, TOOL_RECONCILED):
                if not unresolved:
                    problems.append(
                        f"tool intent {key} is journaled {event} at sequence "
                        f"{record['sequence']} with no started attempt to answer")
                unresolved = False
                counts["reconciliations"] += event == TOOL_RECONCILED
        counts["attempts"] += started
        if unresolved:
            problems.append(f"tool intent {key} ends with an attempt whose outcome is unknown")
        if side_effect is None:
            problems.append(f"tool intent {key} is of no executed step of a tool actor")
    return problems, counts


def _tools(root: Path, manifest: Any, journal: list[dict], steps: list[tuple],
           calls: Mapping[str, Any], contracts: Mapping[str, Any]
           ) -> tuple[list[str], dict[str, Any]]:
    rows = _rows(calls, TOOL)
    problems = [f"a tool call is journaled at {where}, which is no executed step of a tool "
                "actor" for where in sorted(set(rows) - set(steps))]
    side_effects: dict[str, ToolSideEffect] = {}
    effects: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    arguments = {"declared": 0, "rederived": 0}
    for where in steps:
        found = rows.get(where, [])
        label = f"{where[0]} round {where[1]} {where[2]!r}"
        if len(found) != 1:
            problems.append(f"{label} holds {len(found)} calls of its tool actor; a step is "
                            "answered once")
            continue
        (row,) = found
        tool = row.get("tool") or {}
        rederived, _, declared = str(tool.get("arguments_rederived") or "").partition("/")
        if rederived.isdigit() and declared.isdigit():
            arguments["declared"] += int(declared)
            arguments["rederived"] += int(rederived)
        intent = tool.get("intent")
        if isinstance(intent, Mapping):
            side_effects[f"{intent.get('kind')}:{intent.get('digest')}"] = \
                contracts[row["actor"]].side_effect
        if row["status"] != ACCEPTED or tool.get("state") != ToolCallStateV1.RETURNED.value \
                or not tool.get("result"):
            problems.append(f"{label} is {row['status']} with its tool call "
                            f"{tool.get('state')}: the call did not reach its result")
            continue
        effects[str(tool.get("effect"))] += 1
        sources[str(tool.get("source"))] += 1
    retried, counts = _attempts(journal, side_effects)
    problems += retried
    intents = _member_documents(root, manifest, "tool_intent")
    results = _member_documents(root, manifest, "tool_result")
    if not (len(steps) == len(side_effects) == len(intents) == len(results)):
        problems.append(f"{len(steps)} executed tool steps; {len(side_effects)} tool intents "
                        f"called, {len(intents)} intent and {len(results)} result members")
    return problems, {
        "counts": {"steps": len(steps), "intent_members": len(intents),
                   "result_members": len(results), "attempts": counts["attempts"],
                   "reconciliations": counts["reconciliations"],
                   "unknown_outcomes": counts["unknown_outcomes"]},
        "arguments": arguments,
        "effects": dict(sorted(effects.items())),
        "result_sources": dict(sorted(sources.items())),
        "side_effects": dict(sorted(Counter(
            effect.value for effect in side_effects.values()).items())),
    }


def assess_l5_conformance_v1(root: Path, *, problems: list[str] | None = None,
                             l1: Mapping[str, Any] | None = None,
                             call_provenance: Mapping[str, Any] | None = None,
                             organization: Mapping[str, str | None] | None = None
                             ) -> dict[str, Any]:
    """Decide the P18 L5 conformance claim of the package at *root* (pure).

    *problems* is a ``verify_package_v4`` result, *l1* the L1 claim and
    *call_provenance* the ``assess_call_provenance_v1`` document the caller
    already holds for this package, and *organization* the levels of its other
    claims (stated back, never decided on).
    """

    root = Path(root)
    if l1 is None:
        l1 = assess_l1_conformance_v1(
            root, problems=verify_package_v4(root) if problems is None else problems)
    results: dict[str, list[str] | None] = {name: None for _, name in CRITERIA}
    results["l1_conformant"] = [] if l1["level"] == L1 else _failing(
        l1, f"the package is {l1['level']}")
    detail: dict[str, Any] = {}
    callers: dict[str, int] = {}
    if not results["l1_conformant"]:
        try:
            if call_provenance is None:
                call_provenance = assess_call_provenance_v1(root)
            manifest = read_manifest4(root / MANIFEST_NAME)
            (plan_document,) = _member_documents(root, manifest, "plan")
            (attestation,) = _member_documents(root, manifest, "conformance_attestation")
            plan = plan_document["plan"]
            protocol = ProtocolIR.from_document(plan["protocol"])
            results["open_actors_declared"], declared = _declared(
                plan, protocol, call_provenance)
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
            results["open_actors_declared"] = [f"package does not read as an L5 run: {error}"]
    if results["open_actors_declared"] == []:
        kinds = declared["kinds"]
        detail["open_actors"] = dict(sorted(kinds.items()))
        callers = dict(call_provenance["callers"])
        hidden = call_provenance.get("hidden_calls")
        results["calls_declared"] = (
            [] if call_provenance["verdict"] == ALL_DECLARED and hidden == 0
            else _failing(call_provenance, f"the call provenance is "
                                           f"{call_provenance['verdict']} ({hidden} hidden)"))
        try:
            journal = Journal2(root).read()
            keys = _step_keys(protocol, list(attestation["episodes"]))
            human_steps = _steps(protocol, keys, kinds, HUMAN)
            results["human_exchanges_closed"], detail["human"] = _humans(
                root, manifest, journal, human_steps, call_provenance)
            results["human_exchanges_closed"] += _unanswered(protocol, human_steps, kinds, HUMAN)
            tool_steps = _steps(protocol, keys, kinds, TOOL)
            results["tool_calls_resolved"], detail["tool"] = _tools(
                root, manifest, journal, tool_steps, call_provenance, declared["tools"])
            results["tool_calls_resolved"] += _unanswered(protocol, tool_steps, kinds, TOOL)
        except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                AttributeError) as error:
            name = ("human_exchanges_closed" if results["human_exchanges_closed"] is None
                    else "tool_calls_resolved")
            results[name] = [*(results[name] or ()),
                             f"package does not read as an L5 run: {error}"]
    criteria = [
        {"id": key, "criterion": name,
         "status": NOT_EVALUATED if results[name] is None else FAIL if results[name] else PASS,
         "problems": list(results[name] or ())}
        for key, name in CRITERIA
    ]
    conformant = all(item["status"] == PASS for item in criteria)
    arguments = detail.get("tool", {}).get("arguments", {})
    limited = arguments.get("rederived", 0) < arguments.get("declared", 0)
    return {
        "schema": L5_CONFORMANCE_SCHEMA,
        "level": L5 if conformant else NOT_L5,
        "criteria": criteria,
        # stated with the claim, never decided on (T5-008: a package holds a frozen
        # resource by digest, so its bytes are the verifier's to be handed)
        **({"limitations": [ARGUMENTS_NOT_REDERIVED]} if limited else {}),
        "hidden_calls": None if call_provenance is None else call_provenance.get("hidden_calls"),
        "callers": callers,
        **({} if organization is None else {"organization": dict(organization)}),
        **detail,
    }
