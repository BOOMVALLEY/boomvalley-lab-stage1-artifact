"""Actor-call provenance and hidden-call detection over one run (P17, T5-005).

An actor of a plan is answered by exactly one kind of caller, and the plan
says which: a model (its profile's provider and model), a person (a
``humans`` contract: channel, consent, minimum provenance) or a tool (a
``tools`` contract: tool, operation, resource, effect).  Whatever reached
outside the product during a run left journal-2 records and evidence
members.  ``assess_call_provenance_v1`` attributes every one of them to the
declared caller of one plan ``actor_call`` step, from the run directory alone
(packaged or not, complete or waiting), and whatever it cannot attribute is a
hidden call:

    P1 declared_callers   every actor_call node names a plan actor, and that
                          actor is answered by one declared kind: an actor on
                          the reserved human / tool model has its contract
    P2 model_calls        every transport is the one call of a plan actor_call
                          step, intended before it started; every returned,
                          persisted or accepted call was transported; a call
                          binding names the step's node, actor and provider;
                          no response artifact exists for a call that was
                          never transported
    P3 human_exchanges    a human actor's call names its ``human_intent``
                          evidence, which recomputes its identity and is this
                          actor's, for this call's request, under the plan's
                          contract; its participant was asked under a
                          ``human_consent`` record that recomputes and is
                          GRANTED for exactly the contract's terms; the answer
                          recomputes its identity and is that participant's
                          under that consent (T5-008: a package is verified
                          with no desk to ask); the request is delivered and the answer
                          received once, in order; the call returns only after
                          the answer was received, and the answer's provenance
                          is the contract's channel at no less than its
                          minimum grade; no HUMAN_* record and no response
                          evidence exists outside such a call
    P4 tool_calls         every TOOL_* record is on a tool actor's step, under
                          an intent that is this actor's under the plan's
                          contract and whose journaled chain classifies
                          (``classify_tool_call``: no start without an intent,
                          no blind retry); a tool actor's call names that
                          intent and its contract (``tool_call``), was called
                          with the arguments the contract's declared selection
                          derives (constants, fields of a granted proposal
                          the round committed, and fields of a granted frozen
                          resource whose declared bytes the verifier was
                          handed and whose digest is the plan's), returns only
                          after its tool
                          did, and returns the bytes its recorded result
                          derives; no result evidence exists that no journaled
                          call accounts for
    P5 containment        no record states that containment refused a hidden
                          call or effect while the run executed

The verdict is ``ALL_DECLARED`` iff every criterion passes, else
``NOT_DECLARED`` with the failing criteria's problems; ``hidden`` counts the
undeclared model calls, tool calls and human exchanges.  ``calls`` is the
provenance of every actor call the journal holds: who was declared to answer
the step and what the evidence says answered it.

Crash windows are not hidden calls.  Evidence that is durable one boundary
ahead of its journal record (a tool result whose call is started and
unresolved, an answer whose request is delivered, an artifact whose call is
transported) is what an interrupted process leaves and a resume continues.

This reads evidence; it proves nothing about what a process did without
leaving any.  That is the runtime half (``kernel/containment.py``): network,
process and file effects outside the engine's transport windows are refused
while the run executes, and P5 reads those refusals back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.kernel.actors import ActorBindingSetV1
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.human import (
    HUMAN_MODEL,
    HumanActorContractSetV1,
    HumanConsentRecordV1,
    HumanError,
    HumanRequestIntentV1,
    HumanResponseV1,
)
from boomvalley_lab.kernel.identity import StepIdentity
from boomvalley_lab.kernel.information import InformationAccessSetV1, SourceDescriptorV1
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_OUTCOME_UNKNOWN,
    CALL_PERSISTED,
    CALL_RETURNED,
    CUSTODY_ACCEPTED,
    EPISODE_FAILED,
    EPISODE_OPENED,
    HUMAN_REQUEST_DELIVERED,
    HUMAN_RESPONSE_RECEIVED,
    PROPOSAL_PARSED,
    RUN_OPENED,
    TOOL_CALL_STARTED,
    TOOL_INTENT_RECORDED,
    TOOL_OUTCOME_UNKNOWN,
    TOOL_RECONCILED,
    TOOL_RETURNED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR
from boomvalley_lab.kernel.tool import (
    INTENT_TYPES,
    RESULT_TYPES,
    TOOL_MODEL,
    ToolActorContractSetV1,
    tool_response_content,
    tool_response_provenance,
)
from boomvalley_lab.kernel.tool_call import (
    INTENT_ROLE,
    RESULT_ROLE,
    ToolCallStateV1,
    classify_tool_call,
)

CALL_PROVENANCE_SCHEMA = "bvl-call-provenance-1"
ALL_DECLARED = "ALL_DECLARED"
NOT_DECLARED = "NOT_DECLARED"
PASS = "PASS"
FAIL = "FAIL"
NOT_EVALUATED = "NOT_EVALUATED"

MODEL = "MODEL"
HUMAN = "HUMAN"
TOOL = "TOOL"

CRITERIA = (
    ("P1", "declared_callers"),
    ("P2", "model_calls"),
    ("P3", "human_exchanges"),
    ("P4", "tool_calls"),
    ("P5", "containment"),
)

_HUMAN_EVENTS = frozenset({HUMAN_REQUEST_DELIVERED, HUMAN_RESPONSE_RECEIVED})
_TOOL_EVENTS = frozenset(
    {TOOL_INTENT_RECORDED, TOOL_CALL_STARTED, TOOL_OUTCOME_UNKNOWN, TOOL_RETURNED,
     TOOL_RECONCILED}
)
_AFTER_TRANSPORT = (CALL_OUTCOME_UNKNOWN, CALL_RETURNED, CALL_PERSISTED, CUSTODY_ACCEPTED)
_CALL_STATUS = (
    (CUSTODY_ACCEPTED, "ACCEPTED"),
    (CALL_PERSISTED, "PERSISTED"),
    (CALL_RETURNED, "RETURNED"),
    (CALL_OUTCOME_UNKNOWN, "OUTCOME_UNKNOWN"),
    (TRANSPORT_STARTED, "TRANSPORT_STARTED"),
    (CALL_INTENT_RECORDED, "INTENT_RECORDED"),
)
_ARTIFACT = re.compile(r"call-([0-9a-f]{64})\.bin")
_REFUSED = "ContainmentViolationV2"


def _key(identity: Any) -> str:
    """The journal's string form of an identity document."""

    return f"{identity['kind']}:{identity['digest']}"


def _plain(value: Any) -> Any:
    return dict(value) if isinstance(value, Mapping) else value


def _run_plan(store: EvidenceDocumentStoreV2, journal: list[dict]) -> Mapping[str, Any]:
    """The frozen plan the run was opened on, from its own evidence."""

    opened = [record for record in journal if record["event"] == RUN_OPENED]
    if len(opened) != 1:
        raise ValueError(f"the journal opens {len(opened)} runs")
    held = [document for document in store.members("plan")
            if document.get("identity") == opened[0]["plan"]]
    if len(held) != 1:
        raise ValueError("the run holds no plan evidence for the plan it was opened on; "
                         "pass the plan")
    return held[0]["plan"]


class _Assessment:
    def __init__(self, root: Path, plan: Mapping[str, Any], journal: Journal2,
                 records: list[dict], resources: Mapping[str, bytes] | None = None) -> None:
        self.root = root
        # source id -> the bytes a study declares for a frozen resource (T5-008)
        self.resources = dict(resources or {})
        self.journal = journal
        self.records = records
        self.store = EvidenceDocumentStoreV2(root)
        self.protocol = ProtocolIR.from_document(plan["protocol"])
        self.actors = ActorBindingSetV1.from_document(plan["actors"])
        self.humans = (HumanActorContractSetV1.from_document(plan["humans"])
                       if "humans" in plan else None)
        self.tools = (ToolActorContractSetV1.from_document(plan["tools"])
                      if "tools" in plan else None)
        self.information = (InformationAccessSetV1.from_document(plan["information"])
                            if "information" in plan else None)
        self.problems: dict[str, list[str]] = {name: [] for _, name in CRITERIA}
        self.hidden = {"model_calls": 0, "tool_calls": 0, "human_exchanges": 0}
        self.calls: list[dict[str, Any]] = []
        self.episodes = {record["episode"]: record["episode_key"]
                         for record in records if record["event"] == EPISODE_OPENED}
        self._steps: dict[tuple[str, int], dict[str, tuple[str, StepIdentity]]] = {}

    # ------------------------------------------------------------ declaration
    def kind(self, actor: str) -> str:
        if self.tools is not None and actor in self.tools:
            return TOOL
        if self.humans is not None and actor in self.humans:
            return HUMAN
        return MODEL

    def declared_callers(self) -> None:
        problems = self.problems["declared_callers"]
        for node in self.protocol.nodes:
            if node.kind is not NodeKind.ACTOR_CALL:
                continue
            actor = node.config.get("actor")
            if actor not in self.actors:
                problems.append(f"actor_call node {node.node_id!r} names {actor!r}, which is "
                                "not an actor of the plan")
                continue
            model = self.actors.binding(actor).profile.model
            kind = self.kind(actor)
            for reserved, caller in ((HUMAN_MODEL, HUMAN), (TOOL_MODEL, TOOL)):
                if (model == reserved) != (kind == caller):
                    problems.append(
                        f"actor {actor!r} of node {node.node_id!r} is on the model {model!r} "
                        f"and is declared {kind}: who answers it is not declared")
        if self.humans is not None and self.tools is not None:
            both = sorted(set(self.humans.contracts) & set(self.tools.contracts))
            problems += [f"actor {actor!r} is contracted as a human and as a tool"
                         for actor in both]

    # ------------------------------------------------------------------ steps
    def located(self, record: dict) -> tuple[str, StepIdentity] | None:
        """The plan node (and StepIdentity) *record*'s step re-derives to."""

        episode, round_index = record.get("episode"), record.get("round")
        if (episode not in self.episodes or isinstance(round_index, bool)
                or not isinstance(round_index, int) or round_index < 1):
            return None
        steps = self._steps.get((episode, round_index))
        if steps is None:
            kind, _, digest = episode.partition(":")
            steps = {}
            for node in self.protocol.nodes:
                identity = StepIdentity.of_payload(
                    {"episode": {"kind": kind, "digest": digest}, "round": round_index,
                     "node": node.node_id, "kind": node.kind.value})
                steps[str(identity)] = (node.node_id, identity)
            self._steps[(episode, round_index)] = steps
        return steps.get(record["step"])

    def _undeclared(self, events: list[dict], where: str) -> None:
        """Calls on a step that is no actor_call step of the plan."""

        transports = [r for r in events if r["event"] == TRANSPORT_STARTED]
        calls = {r["call"] for r in events if "call" in r}
        started = [r for r in events if r["event"] == TOOL_CALL_STARTED]
        tools = [r for r in events if r["event"] in _TOOL_EVENTS]
        humans = [r for r in events if r["event"] in _HUMAN_EVENTS]
        if calls:
            self.hidden["model_calls"] += max(len(transports), 1)
            self.problems["model_calls"].append(
                f"{len(calls)} call(s) journaled at {where} (first at sequence "
                f"{min(r['sequence'] for r in events if 'call' in r)})")
        if tools:
            self.hidden["tool_calls"] += max(len(started), 1)
            self.problems["tool_calls"].append(
                f"tool records at {where} (first at sequence {tools[0]['sequence']})")
        if humans:
            self.hidden["human_exchanges"] += 1
            self.problems["human_exchanges"].append(
                f"human exchange records at {where} (first at sequence "
                f"{humans[0]['sequence']})")

    # ------------------------------------------------------------ model chain
    def _call_chain(self, events: list[dict], node: str, actor: str, where: str
                    ) -> tuple[str | None, dict | None, dict[str, Any]]:
        """Hold the step's call chain; (call, its intent record, provenance row part)."""

        problems = self.problems["model_calls"]
        chain = [r for r in events if "call" in r]
        calls = list(dict.fromkeys(r["call"] for r in chain))
        if not calls:
            return None, None, {"call": None, "status": "NOT_CALLED"}
        if len(calls) > 1:
            self.hidden["model_calls"] += len(calls) - 1
            problems.append(f"{where} journals {len(calls)} calls; a step makes one")
        call = calls[0]
        mine = [r for r in chain if r["call"] == call]
        intents = [r for r in mine if r["event"] == CALL_INTENT_RECORDED]
        transports = [r for r in mine if r["event"] == TRANSPORT_STARTED]
        if len(intents) != 1:
            problems.append(f"{call} at {where} has {len(intents)} intents")
        intended = intents[0]["sequence"] if intents else None
        for record in transports:
            if intended is None or record["sequence"] < intended:
                self.hidden["model_calls"] += 1
                problems.append(f"{call} at {where} was transported at sequence "
                                f"{record['sequence']} without a prior intent")
        if len(transports) > 1:
            self.hidden["model_calls"] += len(transports) - 1
            problems.append(f"{call} at {where} was transported {len(transports)} times")
        first = transports[0]["sequence"] if transports else None
        untransported = [r for r in mine if r["event"] in _AFTER_TRANSPORT
                         and (first is None or r["sequence"] < first)]
        if untransported:
            self.hidden["model_calls"] += 1
            problems.append(
                f"{call} at {where} is journaled {untransported[0]['event']} at sequence "
                f"{untransported[0]['sequence']} without a transport: nothing declared "
                "answered it")
        intent = intents[0] if intents else None
        if intent is not None and "call_binding" in intent:
            try:
                bound = self.store.read(
                    evidence_ref_from_document(intent["call_binding"], "call_binding"))
                profile = self.actors.binding(actor).profile
                stated = (bound.get("node"), (bound.get("actor") or {}).get("actor_id"),
                          bound.get("provider"), _key(bound["call"]))
                if stated != (node, actor, profile.provider, call):
                    problems.append(
                        f"the call binding of {call} at {where} states node / actor / "
                        f"provider {stated[:3]}, the plan declares "
                        f"{(node, actor, profile.provider)}")
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
                problems.append(f"the call binding of {call} at {where} does not read: {error}")
        events_of = {r["event"] for r in mine}
        status = next(name for event, name in _CALL_STATUS if event in events_of)
        row: dict[str, Any] = {"call": call, "status": status}
        returned = [r for r in mine if r["event"] == CALL_RETURNED]
        if returned:
            row["response"] = dict(returned[0]["response"])
        return call, intent, row

    # ---------------------------------------------------------------- human
    def _human(self, events: list[dict], actor: str, step: StepIdentity,
               intent: dict | None, where: str) -> dict[str, Any]:
        problems = self.problems["human_exchanges"]
        assert self.humans is not None
        contract = self.humans.contract(actor)
        row: dict[str, Any] = {"channel": contract.channel,
                               "minimum_grade": contract.minimum_provenance.value}
        delivered = [r for r in events if r["event"] == HUMAN_REQUEST_DELIVERED]
        received = [r for r in events if r["event"] == HUMAN_RESPONSE_RECEIVED]
        transports = [r for r in events if r["event"] == TRANSPORT_STARTED]
        returned = [r for r in events if r["event"] == CALL_RETURNED]
        identity: Mapping[str, str] | None = None
        asked: HumanRequestIntentV1 | None = None
        if intent is None:
            if delivered or received:
                self.hidden["human_exchanges"] += 1
                problems.append(f"{where} journals a human exchange without a call intent")
        elif "human_intent" not in intent:
            problems.append(f"the call of human actor {actor!r} at {where} names no "
                            "human_intent evidence: who was asked is not evidence")
        else:
            try:
                held = self.store.read(
                    evidence_ref_from_document(intent["human_intent"], "human_intent"))
                stated, identity = held["intent"], held["identity"]
                asked = HumanRequestIntentV1.from_document(stated)
                if asked.identity().document() != dict(identity):
                    problems.append(f"the human intent at {where} does not recompute the "
                                    "identity it is journaled under")
                expected = {
                    "actor": self.actors.binding(actor).identity.document(),
                    "contract": contract.identity().document(),
                    "step": step.document(),
                    "channel": contract.channel,
                    "request": dict(intent["request"]["identity"]),
                    "privacy": contract.privacy.document(),
                }
                wrong = sorted(name for name, value in expected.items()
                               if stated.get(name) != value)
                if wrong:
                    problems.append(
                        f"the human intent at {where} is not actor {actor!r}'s under the "
                        f"plan's contract ({', '.join(wrong)} differ)")
                row.update(participant=stated.get("participant"), intent=dict(identity))
                # who was asked, and under which consent, is evidence of its own
                consent = self.store.read(
                    evidence_ref_from_document(held["consent"], "human_consent"))
                record = HumanConsentRecordV1.from_document(consent["record"])
                mine = dict(consent["identity"])
                if record.identity().document() != mine or dict(asked.consent) != mine:
                    problems.append(f"the consent evidence at {where} is not the consent the "
                                    "intent asks under")
                try:
                    record.require(contract, asked.participant)
                except HumanError as error:
                    problems.append(f"the participant at {where} was asked without a granted "
                                    f"consent to the contract's terms: {error}")
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
                problems.append(f"the human intent evidence at {where} does not read: {error}")
        for name, found in (("delivered", delivered), ("received", received)):
            if len(found) > 1:
                self.hidden["human_exchanges"] += len(found) - 1
                problems.append(f"the request at {where} is {name} {len(found)} times")
            for record in found:
                if identity is not None and record["human_intent"] != identity:
                    self.hidden["human_exchanges"] += 1
                    problems.append(
                        f"{record['event']} at sequence {record['sequence']} names another "
                        "intent than the call's")
        if delivered and (not transports
                          or delivered[0]["sequence"] < transports[0]["sequence"]):
            problems.append(f"the request at {where} was delivered before its call started")
        if received and (not delivered
                         or received[0]["sequence"] < delivered[0]["sequence"]):
            self.hidden["human_exchanges"] += 1
            problems.append(f"an answer was received at {where} for a request that was not "
                            "delivered")
        if returned and (not received
                         or returned[0]["sequence"] < received[0]["sequence"]):
            self.hidden["model_calls"] += 1
            self.problems["model_calls"].append(
                f"the call of human actor {actor!r} at {where} returned without the "
                "participant's received answer: something else answered")
        if received:
            try:
                document = self.store.read(
                    evidence_ref_from_document(received[0]["human_response"], "human_response"))
                answer = HumanResponseV1.from_document(document["response"])
                provenance = answer.provenance
                row["provenance"] = provenance.document()
                row["response"] = dict(document["identity"])
                if identity is not None and dict(answer.intent) != dict(identity):
                    problems.append(f"the response at {where} answers another intent")
                if answer.identity().document() != dict(document["identity"]):
                    problems.append(f"the response at {where} does not recompute the "
                                    "identity it is held under")
                if asked is not None and (
                        answer.participant != asked.participant
                        or dict(answer.consent) != dict(asked.consent)):
                    problems.append(f"the response at {where} is not by the participant who "
                                    "was asked, under the consent they were asked under")
                graded = (provenance.channel == contract.channel
                          and provenance.grade.strength >= contract.minimum_provenance.strength)
                if provenance.channel != contract.channel:
                    problems.append(
                        f"the response at {where} arrived through {provenance.channel!r}, "
                        f"not the contract's {contract.channel!r}")
                if provenance.grade.strength < contract.minimum_provenance.strength:
                    problems.append(
                        f"the response at {where} is {provenance.grade.value}; the contract "
                        f"accepts no less than {contract.minimum_provenance.value}")
                # the call returned the bytes the participant's answer states, nothing
                # else's (SV-13 C-01): the tool branch holds its result the same way.  An
                # answer whose channel or grade is refused above is told once, there
                expected = {
                    "content_digest": answer.content_sha256,
                    "model_identity": HUMAN_MODEL,
                    "adapter_provenance": f"{provenance.channel}:{provenance.grade.value}",
                }
                stated = dict(returned[0]["response"]) if returned else expected
                if not graded:
                    stated.pop("adapter_provenance", None)
                    del expected["adapter_provenance"]
                if stated != expected:
                    self.hidden["model_calls"] += 1
                    self.problems["model_calls"].append(
                        f"the call of human actor {actor!r} at {where} returned another "
                        "response than the participant's received answer states: something "
                        "else answered")
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
                problems.append(f"the human response evidence at {where} does not read: "
                                f"{error}")
        row["state"] = ("RECEIVED" if received else "WAITING" if delivered else "NOT_DELIVERED")
        return row

    # ----------------------------------------------------------------- tool
    def _selected(self, record: dict, actor: str,
                  origin: Mapping[str, Any]) -> tuple[bool, Any]:
        """(re-derived, value) of one selected argument, from the run's evidence.

        A constant is the contract's.  A field of a granted, untransformed
        ``actor_output`` of a proposal_parse node is the value that node
        committed in the round (PROPOSAL_PARSED).  A field of a granted,
        untransformed frozen resource is read from the bytes the verifier was
        handed for it, and only when they are the plan's (digest and size): a
        package holds a frozen resource by digest, so without those bytes -
        and for any other origin - nothing is re-derived (T5-008).
        """

        if "value" in origin:
            return True, origin["value"]
        access = self.information
        frozen = None if access is None else access.sources.get(origin["source"])
        if isinstance(frozen, SourceDescriptorV1):
            content = self.resources.get(origin["source"])
            planned = (frozen.content_sha256, frozen.size)
            if content is None or origin["source"] in access.transforms_of(actor) or (
                    sha256_bytes(content).hex, len(content)) != planned:
                return False, None
            try:
                held = load_bytes(content)
            except (MalformedJSON, BoomvalleyError, ValueError):
                return False, None
            if not isinstance(held, Mapping) or origin["field"] not in held:
                return False, None
            return True, held[origin["field"]]
        descriptor = None if access is None else access.actor_outputs.get(origin["source"])
        if descriptor is None or origin["source"] in access.transforms_of(actor) or (
                descriptor.producer) not in {
                node.node_id for node in self.protocol.nodes
                if node.kind is NodeKind.PROPOSAL_PARSE}:
            return False, None
        steps = self._steps[(record["episode"], record["round"])]
        producer = next(key for key, (node_id, _) in steps.items()
                        if node_id == descriptor.producer)
        parsed = [r for r in self.journal.of_step(producer) if r["event"] == PROPOSAL_PARSED]
        value = parsed[0]["proposal"].get("value") if len(parsed) == 1 else None
        if not isinstance(value, Mapping) or origin["field"] not in value:
            return False, None
        return True, value[origin["field"]]

    def _tool(self, events: list[dict], actor: str, step: StepIdentity,
              call_intent: dict | None, where: str) -> dict[str, Any]:
        problems = self.problems["tool_calls"]
        assert self.tools is not None
        contract = self.tools.contract(actor)
        row: dict[str, Any] = {
            "tool": contract.tool, "operation": contract.operation,
            "resource": contract.resource, "effect": contract.effect.value,
            "side_effect": contract.side_effect.value, "state": "NOT_CALLED",
        }
        records = [r for r in events if r["event"] in _TOOL_EVENTS]
        intents = list(dict.fromkeys(r["tool_intent"] for r in records))
        for key in intents:
            mine = [r for r in records if r["tool_intent"] == key]
            started = sum(1 for r in mine if r["event"] == TOOL_CALL_STARTED)

            def hidden(reason: str, started: int = started) -> None:
                self.hidden["tool_calls"] += max(started, 1)
                problems.append(reason)

            if key != intents[0]:
                hidden(f"{where} journals a second tool intent {key}; a step calls its tool "
                       "for one intent")
                continue
            if mine[0]["event"] != TOOL_INTENT_RECORDED:
                hidden(f"{mine[0]['event']} at sequence {mine[0]['sequence']} ({where}) has no "
                       "recorded intent: the tool was called undeclared")
                continue
            try:
                intent = INTENT_TYPES[contract.effect].from_document(self.store.read(
                    evidence_ref_from_document(mine[0]["evidence"], INTENT_ROLE)))
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
                hidden(f"the tool intent evidence at {where} does not read as a "
                       f"{contract.effect.value} intent: {error}")
                continue
            expected = {
                "actor": self.actors.binding(actor).identity.document(),
                "contract": contract.identity().document(),
                "step": step.document(),
                "tool": contract.tool,
                "operation": contract.operation,
                "resource": contract.resource,
            }
            wrong = sorted(name for name, value in expected.items()
                           if _plain(getattr(intent, name)) != value)
            if wrong or str(intent.identity()) != key:
                hidden(f"the tool intent at {where} is not actor {actor!r}'s under the plan's "
                       f"contract ({', '.join(wrong) or 'identity'} differ): an undeclared "
                       "tool call")
                continue
            classified = classify_tool_call(
                run_directory=self.root, journal=self.journal, contract=contract, step=step,
                intent=intent)
            row.update(intent=intent.identity().document(), attempts=classified.attempts,
                       state=classified.state.value, arguments=dict(intent.arguments))
            if classified.state is ToolCallStateV1.INCONSISTENT:
                hidden(f"the tool call at {where} does not classify: {classified.reason}")
                continue
            # the actor call names this intent under this contract (T5-007)
            named = None if call_intent is None else call_intent.get("tool_call")
            if call_intent is not None and named != {
                    "intent": intent.identity().document(),
                    "contract": contract.identity().document()}:
                hidden(f"the call of tool actor {actor!r} at {where} does not name the tool "
                       "intent its step journals: the tool was called for another call")
                continue
            # the arguments are the contract's declared selection, not a choice
            derived = 0
            for name, origin in sorted((contract.argument_selection or {}).items()):
                known, value = self._selected(mine[0], actor, origin)
                if not known:
                    continue
                derived += 1
                if intent.arguments.get(name) != value or (
                        type(intent.arguments.get(name)) is not type(value)):
                    hidden(f"the tool at {where} was called with {name}="
                           f"{intent.arguments.get(name)!r}; the contract's selection "
                           f"derives {value!r}: undeclared arguments")
            if call_intent is not None and contract.argument_selection is None:
                problems.append(f"the tool at {where} was called and its contract declares "
                                "no argument selection: its arguments have no declared origin")
            row["arguments_rederived"] = f"{derived}/{len(contract.arguments)}"
            terminal = [r for r in mine if "tool_result" in r]
            if terminal:
                row["result"] = terminal[-1]["tool_result"]
                row["source"] = ("RECONCILIATION" if terminal[-1]["event"] == TOOL_RECONCILED
                                 else "CALL")
        answered = [r for r in records if "tool_result" in r]
        returned = [r for r in events if r["event"] == CALL_RETURNED]
        if returned and (not answered
                         or returned[0]["sequence"] < answered[0]["sequence"]):
            self.hidden["model_calls"] += 1
            self.problems["model_calls"].append(
                f"the call of tool actor {actor!r} at {where} returned without its tool's "
                "result: something else answered")
        elif returned:
            # the response is the bytes the recorded result derives, nothing else's
            try:
                result = RESULT_TYPES[contract.effect].from_document(self.store.read(
                    evidence_ref_from_document(answered[-1]["evidence"], RESULT_ROLE)))
                content = tool_response_content(result)
                expected = {
                    "content_digest": str(sha256_bytes(content)),
                    "model_identity": TOOL_MODEL,
                    "adapter_provenance": tool_response_provenance(contract),
                }
                if dict(returned[0]["response"]) != expected:
                    self.hidden["model_calls"] += 1
                    self.problems["model_calls"].append(
                        f"the call of tool actor {actor!r} at {where} returned another "
                        "response than its tool's recorded result derives: something else "
                        "answered")
                else:
                    row["response_content"] = content.decode("utf-8")
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
                problems.append(f"the tool result evidence at {where} does not read: {error}")
        if call_intent is not None and "tool_call" not in call_intent:
            problems.append(f"the call of tool actor {actor!r} at {where} names no tool call: "
                            "what answered it is not evidence")
        return row

    # ------------------------------------------------------------- the walk
    def walk(self) -> None:
        by_step: dict[tuple[str, int, str], list[dict]] = {}
        for record in self.records:
            if "step" in record and (
                    "call" in record or record["event"] in _TOOL_EVENTS | _HUMAN_EVENTS):
                by_step.setdefault(
                    (str(record.get("episode")), record.get("round"), record["step"]), []
                ).append(record)
        for (episode, round_index, _), events in by_step.items():
            found = self.located(events[0])
            if found is None:
                self._undeclared(
                    events, f"a step outside the plan ({episode}, round {round_index!r})")
                continue
            node_id, step = found
            node = self.protocol.node(node_id)
            episode_key = self.episodes[episode]
            where = f"{episode_key} round {round_index} {node_id!r}"
            actor = node.config.get("actor")
            if node.kind is not NodeKind.ACTOR_CALL or actor not in self.actors:
                self._undeclared(events, f"{where}, which is no actor_call step")
                continue
            kind = self.kind(actor)
            profile = self.actors.binding(actor).profile
            call, intent, row = self._call_chain(events, node_id, actor, where)
            row = {"episode_key": episode_key, "round": round_index, "node": node_id,
                   "actor": actor, "kind": kind, "provider": profile.provider,
                   "model": profile.model, **row}
            humans = [r for r in events if r["event"] in _HUMAN_EVENTS]
            tools = [r for r in events if r["event"] in _TOOL_EVENTS]
            if kind == HUMAN:
                row["human"] = self._human(events, actor, step, intent, where)
            elif humans or (intent is not None and "human_intent" in intent):
                self.hidden["human_exchanges"] += 1
                self.problems["human_exchanges"].append(
                    f"{where} is {kind} actor {actor!r}'s step and journals a human exchange")
            if kind == TOOL:
                row["tool"] = self._tool(events, actor, step, intent, where)
            elif intent is not None and "tool_call" in intent:
                self.hidden["tool_calls"] += 1
                self.problems["tool_calls"].append(
                    f"{where} is {kind} actor {actor!r}'s step and its call names a tool call: "
                    "no tool is declared for it")
            elif tools:
                self.hidden["tool_calls"] += max(
                    sum(1 for r in tools if r["event"] == TOOL_CALL_STARTED), 1)
                self.problems["tool_calls"].append(
                    f"{where} is {kind} actor {actor!r}'s step and journals a tool call "
                    f"(sequence {tools[0]['sequence']}): no tool is declared for it")
            self.calls.append(row)

    # ------------------------------------------------------ unjournaled evidence
    def orphans(self) -> None:
        records = self.records
        # a tool result no journaled call accounts for
        named = {r["tool_result"] for r in records if "tool_result" in r}
        open_intents = set()
        for key in {r["tool_intent"] for r in records if r["event"] in _TOOL_EVENTS}:
            mine = [r for r in records if r.get("tool_intent") == key]
            last_start = max((i for i, r in enumerate(mine)
                              if r["event"] == TOOL_CALL_STARTED), default=None)
            if last_start is not None and not any(
                    r["event"] in (TOOL_RETURNED, TOOL_RECONCILED) for r in mine[last_start:]):
                open_intents.add(key)
        for path in sorted((self.root / "evidence-v2" / RESULT_ROLE).glob("*.json")):
            try:
                document = self.store.read(evidence_ref_from_document(
                    {"schema": "boomvalley-lab-evidence-document-ref-2", "role": RESULT_ROLE,
                     "path": f"evidence-v2/{RESULT_ROLE}/{path.name}",
                     "digest": f"sha256:{path.stem}", "size": path.stat().st_size},
                    RESULT_ROLE))
                intent = _key(document["intent"])
                effect = next(effect for effect, kind in INTENT_TYPES.items()
                              if kind.IDENTITY.KIND == document["intent"]["kind"])
                identity = str(RESULT_TYPES[effect].from_document(document).identity())
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError,
                    StopIteration) as error:
                self.problems["tool_calls"].append(
                    f"tool result evidence {path.name} does not read: {error}")
                continue
            if identity not in named and intent not in open_intents:
                self.hidden["tool_calls"] += 1
                self.problems["tool_calls"].append(
                    f"tool result evidence {path.name} answers {intent}, which no journaled "
                    "tool call accounts for: a tool was called outside the journal")
        # an answer nobody was asked for
        received = {r["human_response"]["path"] for r in records
                    if r["event"] == HUMAN_RESPONSE_RECEIVED
                    and isinstance(r.get("human_response"), Mapping)}
        delivered = {_key(r["human_intent"]) for r in records
                     if r["event"] == HUMAN_REQUEST_DELIVERED}
        for path in sorted((self.root / "evidence-v2" / "human_response").glob("*.json")):
            relative = f"evidence-v2/human_response/{path.name}"
            if relative in received:
                continue
            try:
                document = self.store.read(evidence_ref_from_document(
                    {"schema": "boomvalley-lab-evidence-document-ref-2",
                     "role": "human_response", "path": relative,
                     "digest": f"sha256:{path.stem}", "size": path.stat().st_size},
                    "human_response"))
                intent = _key(document["response"]["intent"])
            except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
                self.problems["human_exchanges"].append(
                    f"human response evidence {path.name} does not read: {error}")
                continue
            if intent not in delivered:
                self.hidden["human_exchanges"] += 1
                self.problems["human_exchanges"].append(
                    f"human response evidence {path.name} answers {intent}, which was never "
                    "delivered: an answer outside the journal")
        # a response artifact of a call that was never transported
        transported = {r["call"] for r in records if r["event"] == TRANSPORT_STARTED}
        artifacts = self.root / "artifacts"
        for path in sorted(artifacts.glob("call-*.bin")) if artifacts.is_dir() else ():
            match = _ARTIFACT.fullmatch(path.name)
            if match is None or f"call:sha256:{match[1]}" not in transported:
                self.hidden["model_calls"] += 1
                self.problems["model_calls"].append(
                    f"response artifact {path.name} belongs to no transported call: a model "
                    "was called outside the journal")

    def containment(self) -> None:
        for record in self.records:
            reason = record.get("reason")
            if (record["event"] in (EPISODE_FAILED, CALL_OUTCOME_UNKNOWN, TOOL_OUTCOME_UNKNOWN)
                    and isinstance(reason, str) and reason.startswith(_REFUSED)):
                self.problems["containment"].append(
                    f"{record['event']} at sequence {record['sequence']}: {reason}")


def assess_call_provenance_v1(
    root: Path, *, plan: Mapping[str, Any] | None = None,
    resources: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Attribute every call of the run at *root* to a declared caller (pure).

    *plan* is the frozen plan document the run executed; without it the run's
    own ``plan`` evidence (the plan RUN_OPENED names) is read.  *resources*
    are the bytes a study declares for its frozen resources, by source id: a
    tool argument selected from one is re-derived from them when they are the
    bytes the plan froze, and not otherwise.
    """

    root = Path(root)
    results: dict[str, list[str] | None] = {name: None for _, name in CRITERIA}
    hidden: dict[str, int] | None = None
    calls: list[dict[str, Any]] = []
    try:
        journal = Journal2(root)
        records = journal.read()
        if plan is None:
            plan = _run_plan(EvidenceDocumentStoreV2(root), records)
        assessment = _Assessment(root, plan, journal, records, resources)
    except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
        results["declared_callers"] = [f"the run does not read as a planned run: {error}"]
    else:
        assessment.declared_callers()
        results["declared_callers"] = assessment.problems["declared_callers"]
        if not results["declared_callers"]:
            assessment.walk()
            assessment.orphans()
            assessment.containment()
            for _, name in CRITERIA[1:]:
                results[name] = assessment.problems[name]
            hidden, calls = assessment.hidden, assessment.calls
    criteria = [
        {"id": key, "criterion": name,
         "status": NOT_EVALUATED if results[name] is None else FAIL if results[name] else PASS,
         "problems": list(results[name] or ())}
        for key, name in CRITERIA
    ]
    declared = all(item["status"] == PASS for item in criteria)
    return {
        "schema": CALL_PROVENANCE_SCHEMA,
        "verdict": ALL_DECLARED if declared else NOT_DECLARED,
        "criteria": criteria,
        "hidden": hidden,
        "hidden_calls": None if hidden is None else sum(hidden.values()),
        "callers": ({} if hidden is None else
                    {kind: sum(1 for row in calls if row["kind"] == kind)
                     for kind in (MODEL, HUMAN, TOOL)}),
        "calls": calls,
    }
