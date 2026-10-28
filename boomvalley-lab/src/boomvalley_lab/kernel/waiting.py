"""P17 WAITING / delayed-response lifecycle of a human actor call (T5-002).

A model answers inside one call; a person answers hours later.  A human actor
call is therefore the same durable K0 call (``kernel/call_executor.py``) whose
process may stop between asking and the answer, any number of times, and what
is durable decides what happens next - never a process's memory:

    consent record, request intent    human_consent / human_intent evidence
    -> CALL_INTENT_RECORDED           names the intent evidence (``human_intent``)
    -> TRANSPORT_STARTED
    -> the request is on the desk     outbox member, created once per intent
    -> HUMAN_REQUEST_DELIVERED        committed once
       ................ WAITING: the process stops here ................
    -> the answer is on the desk      inbox member, created once per intent
    -> human_response evidence
    -> HUMAN_RESPONSE_RECEIVED        committed once
    -> CALL_RETURNED -> CALL_PERSISTED -> CUSTODY_ACCEPTED

A process that stops after CALL_RETURNED and before the call is accepted into
custody has lost nothing: the desk still holds the answer and the journal its
digest, so persistence and custody are finished from there
(``kernel/human_recovery.py``, ``HUMAN_RETURNED``), byte-checked - a model's
response in that window is gone or unproven, a person's is not, and a person
is not asked twice.  One window
stays every call's: a custody ledger entry whose CUSTODY_ACCEPTED was never
journaled is an operator's decision.

The call chain is the chain of every actor call, so custody, readiness, resume
and the package read a human call as they read a model call; the two HUMAN_*
events are keyed by the step and its HumanRequestIntentIdentity.

No duplicate request.  The intent is identified before anything is delivered
(step x actor x request x contract x participant x consent) and the desk holds
one delivery per intent, created exclusively: a restart that finds the delivery
finds the one it would have written, byte for byte, and writes nothing; a
delivery that differs is refused (BVL-HUMAN-010).  A restart whose enrollment
names another participant or consent derives another intent than the journaled
one and is refused (BVL-RES-001) before anybody else is asked.

No duplicate response.  The desk holds one answer per intent, created
exclusively: a second answer is refused where it is entered.  The response is
identified from that answer, and HUMAN_RESPONSE_RECEIVED and the call's
CALL_RETURNED are committed once; a restart after them returns the recorded
call from custody and reads no desk.

A desk that contradicts the run is not an outcome either.  A delivery that is
not the one the intent derives, or an answer that is unreadable or filed under
another intent, is ``HumanDeskRefusedError``: nothing is journaled, the run
stays where it was and the desk can be put right.

Waiting is not an outcome.  A call whose answer is not on the desk raises
``HumanResponsePending``: nothing is journaled for it, the episode is neither
failed nor completed, and the run's state is WAITING.  Asking again changes
nothing until the answer exists.

The desk (``HumanDeskV1``) is the kernel-owned transport of a channel that
states ``TRANSPORT = "desk"``: a directory outside the run's evidence, where
the operator finds what to show a participant and enters what they answered.
It is not evidence; what it carried becomes evidence only through the call
chain above.  Who answers as which actor, and under which consent record, is
its ``enrollment.json`` - a participant is never asked without one
(BVL-HUMAN-004).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes, canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.kernel.actors import ActorBindingV1
from boomvalley_lab.kernel.adapter2 import ActorResponseV2
from boomvalley_lab.kernel.authorization import require_run_authorization_v2
from boomvalley_lab.kernel.call_executor import (
    CompletedCallV2,
    DurableCallExecutorV2,
    call_identity_v2,
)
from boomvalley_lab.kernel.custody2 import CustodyLedgerV2, accept_call_v2, call_artifact_name
from boomvalley_lab.kernel.document_store import EvidenceDocumentRefV2, EvidenceDocumentStoreV2
from boomvalley_lab.kernel.human import (
    HUMAN_CONSENT_NOT_GRANTED,
    HUMAN_EXCHANGE_CONTRADICTED,
    HUMAN_EXECUTION_UNSUPPORTED,
    HUMAN_INTENT_MISMATCH,
    HUMAN_MODEL,
    HUMAN_PROVENANCE_INVALID,
    HUMAN_RESPONSE_IDENTITY_MISMATCH,
    HumanActorContractSetV1,
    HumanActorContractV1,
    HumanConsentRecordV1,
    HumanError,
    HumanProvenanceV1,
    HumanRequestIntentIdentity,
    HumanRequestIntentV1,
    ProvenanceGrade,
    ResponseContent,
    human_request_intent,
    human_response,
    require_participant,
    verify_human_exchange,
)
from boomvalley_lab.kernel.human_recovery import HumanCallStateV1, classify_actor_call
from boomvalley_lab.kernel.identity import EpisodeIdentity, StepIdentity
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_PERSISTED,
    CALL_RETURNED,
    HUMAN_REQUEST_DELIVERED,
    HUMAN_RESPONSE_RECEIVED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.recovery2 import CallStateV2
from boomvalley_lab.kernel.replay import (
    RESUME_EVIDENCE_MISMATCH,
    RESUME_OUTCOME_NOT_PROVEN,
    ResumeRefusedError,
    commit,
)
from boomvalley_lab.kernel.request import RequestV2
from boomvalley_lab.store.artifacts import ArtifactRef, content_identity

ENROLLMENT_SCHEMA = "bvl-human-enrollment-1"
DELIVERY_SCHEMA = "bvl-human-delivery-1"
ENTRY_SCHEMA = "bvl-human-entry-1"
CONSENT_EVIDENCE_SCHEMA = "bvl-human-consent-evidence-1"
INTENT_EVIDENCE_SCHEMA = "bvl-human-intent-evidence-1"
RESPONSE_EVIDENCE_SCHEMA = "bvl-human-response-evidence-1"

#: the transport a channel states when the kernel-owned desk carries its exchanges
DESK_TRANSPORT = "desk"
ENROLLMENT_NAME = "enrollment.json"
OUTBOX = "outbox"
INBOX = "inbox"

HUMAN_RESPONSE_PENDING = "HUMAN_RESPONSE_PENDING"


class HumanResponsePending(ExecutionError):
    """The request is with the participant and no answer exists yet.

    Not a refusal and not a scientific outcome: the engine journals nothing
    for it and the run stays WAITING.
    """

    def __init__(self, awaiting: Mapping[str, Any]) -> None:
        self.awaiting = dict(awaiting)
        super().__init__(
            f"{HUMAN_RESPONSE_PENDING}: human actor {self.awaiting['actor']!r} "
            f"({self.awaiting['participant']}) has not answered intent "
            f"{self.awaiting['intent']['digest']} of round {self.awaiting['round']}",
            code=HUMAN_RESPONSE_PENDING,
        )


class HumanDeskRefusedError(ExecutionError):
    """The desk does not hold what the run's evidence says it carries.

    An integrity refusal, not a scientific outcome: the engine journals
    nothing for it and the run stays interrupted.
    """

    def __init__(self, error: HumanError) -> None:
        super().__init__(str(error), code=error.code)


def _contradicted(detail: str) -> HumanError:
    return HumanError(HUMAN_EXCHANGE_CONTRADICTED, detail)


def _read(path: Path, what: str) -> Any:
    try:
        return load_bytes(path.read_bytes())
    except (OSError, MalformedJSON) as error:
        raise _contradicted(f"{what} {path.name} is unreadable: {error}") from None


def _create(path: Path, data: bytes) -> bool:
    """Create *path* holding *data*, never replacing: False when it already exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.parent / f".{path.name}.{os.getpid()}.partial"
    partial.unlink(missing_ok=True)
    try:
        with open(partial, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(partial, path)  # atomic and exclusive: an existing member wins
        except FileExistsError:
            return False
        return True
    finally:
        partial.unlink(missing_ok=True)


def _member(identity: Mapping[str, str]) -> str:
    return f"{identity['digest'].removeprefix('sha256:')}.json"


class HumanDeskV1:
    """One directory through which requests reach participants and answers come back."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------ enrollment
    def enroll(self, contract: HumanActorContractV1, participant: str) -> dict[str, Any]:
        """Record that *participant* answers as the contract's actor, under a
        GRANTED consent record for its terms.  An actor is enrolled once."""

        record = HumanConsentRecordV1.granted(contract, require_participant(participant))
        path = self.root / ENROLLMENT_NAME
        actors: dict[str, Any] = {}
        if path.exists():
            actors = dict(self._enrollment_document()["actors"])
        entry = {"participant": participant, "consent": record.document()}
        held = actors.get(contract.actor_id)
        if held is not None and canonical_json(held) != canonical_json(entry):
            raise _contradicted(
                f"human actor {contract.actor_id!r} is already enrolled as "
                f"{held.get('participant')!r} on this desk; an enrollment is not replaced"
            )
        actors[contract.actor_id] = entry
        document = {"schema": ENROLLMENT_SCHEMA,
                    "actors": {key: actors[key] for key in sorted(actors)}}
        self.root.mkdir(parents=True, exist_ok=True)
        staged = self.root / f".{ENROLLMENT_NAME}.partial"
        staged.write_bytes(canonical_bytes(document))
        os.replace(staged, path)
        return {"actor": contract.actor_id, "participant": participant,
                "consent": record.identity().document(), "status": record.status.value}

    def _enrollment_document(self) -> Mapping[str, Any]:
        path = self.root / ENROLLMENT_NAME
        if not path.is_file():
            raise HumanError(
                HUMAN_CONSENT_NOT_GRANTED,
                f"desk {self.root} holds no {ENROLLMENT_NAME}: nobody is enrolled, and a "
                "participant is never asked without a consent record",
            )
        document = _read(path, "enrollment")
        if (
            not isinstance(document, Mapping)
            or set(document) != {"schema", "actors"}
            or document["schema"] != ENROLLMENT_SCHEMA
            or not isinstance(document["actors"], Mapping)
        ):
            raise HumanError(HUMAN_CONSENT_NOT_GRANTED, f"enrollment is {ENROLLMENT_SCHEMA}")
        return document

    def enrolled(self, contract: HumanActorContractV1) -> tuple[str, HumanConsentRecordV1]:
        """The participant answering as the contract's actor and their consent
        record, held to the contract (BVL-HUMAN-004)."""

        entry = self._enrollment_document()["actors"].get(contract.actor_id)
        if not isinstance(entry, Mapping) or set(entry) != {"participant", "consent"}:
            raise HumanError(
                HUMAN_CONSENT_NOT_GRANTED,
                f"nobody is enrolled as human actor {contract.actor_id!r} on desk {self.root}",
            )
        participant = require_participant(entry["participant"])
        record = HumanConsentRecordV1.from_document(entry["consent"])
        record.require(contract, participant)
        return participant, record

    # -------------------------------------------------------------- delivery
    def deliver(
        self,
        contract: HumanActorContractV1,
        intent: HumanRequestIntentV1,
        request: RequestV2,
        grade: ProvenanceGrade,
    ) -> dict[str, Any]:
        """Put the request on the desk for *intent*, once.

        The delivery is a function of the intent, the request, the contract
        and the grade its channel attests (*grade*: what an entered answer
        must state) alone, so a second delivery of one intent is the first,
        byte for byte.  Returns the journaled delivery reference.
        """

        identity = intent.identity().document()
        document = {
            "schema": DELIVERY_SCHEMA,
            "intent": identity,
            "actor": contract.actor_id,
            "participant": intent.participant,
            "channel": contract.channel,
            "provenance_grade": grade.value,
            "messages": [dict(message) for message in request.messages],
            "response": contract.response.document(),
        }
        data = canonical_bytes(document)
        path = self.root / OUTBOX / _member(identity)
        if not _create(path, data) and path.read_bytes() != data:
            raise _contradicted(
                f"desk {self.root} already holds another delivery for intent "
                f"{identity['digest']}: a participant is asked one request per intent"
            )
        return {"schema": DELIVERY_SCHEMA, "digest": str(sha256_bytes(data)), "size": len(data)}

    def deliveries(self) -> list[dict[str, Any]]:
        """Every delivery on the desk and whether it is answered."""

        found = []
        for path in sorted((self.root / OUTBOX).glob("*.json")):
            document = _read(path, "delivery")
            if not isinstance(document, Mapping) or document.get("schema") != DELIVERY_SCHEMA:
                raise _contradicted(f"delivery {path.name} is not {DELIVERY_SCHEMA}")
            found.append({**document, "answered": (self.root / INBOX / path.name).is_file()})
        return found

    # ---------------------------------------------------------------- answer
    def answer(self, intent: str, text: str, entered_by: str | None) -> dict[str, Any]:
        """Enter the participant's answer to the delivered *intent*, once."""

        identity = {"kind": HumanRequestIntentIdentity.KIND, "digest": intent}
        delivered = self.root / OUTBOX / _member(identity) if isinstance(intent, str) else None
        if delivered is None or not delivered.is_file():
            raise HumanError(
                HUMAN_INTENT_MISMATCH,
                f"desk {self.root} delivered no request for intent {intent!r}: an answer "
                "answers one delivered request",
            )
        delivery = _read(delivered, "delivery")
        if not isinstance(text, str) or len(text) > delivery["response"]["max_chars"]:
            raise HumanError(
                HUMAN_RESPONSE_IDENTITY_MISMATCH,
                f"the answer has {len(text) if isinstance(text, str) else 'no'} characters; "
                f"the contract admits {delivery['response']['max_chars']}",
            )
        # how the answer reached the desk is stated as the channel attests it
        HumanProvenanceV1(delivery["provenance_grade"], delivery["channel"], entered_by)
        document = {"schema": ENTRY_SCHEMA, "intent": delivery["intent"], "text": text,
                    "entered_by": entered_by}
        data = canonical_bytes(document)
        path = self.root / INBOX / delivered.name
        if not _create(path, data) and path.read_bytes() != data:
            raise _contradicted(
                f"intent {intent} is already answered on desk {self.root}: an intent has "
                "one response, and an entered answer is not replaced"
            )
        return {"intent": delivery["intent"], "actor": delivery["actor"],
                "participant": delivery["participant"],
                "content_sha256": str(sha256_bytes(text.encode("utf-8"))),
                "entered_by": entered_by}

    def collect(self, intent: HumanRequestIntentV1) -> Mapping[str, Any] | None:
        """The entered answer to *intent*, or None while there is none."""

        identity = intent.identity().document()
        path = self.root / INBOX / _member(identity)
        if not path.is_file():
            return None
        entry = _read(path, "answer")
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"schema", "intent", "text", "entered_by"}
            or entry["schema"] != ENTRY_SCHEMA
            or not isinstance(entry["text"], str)
        ):
            raise HumanError(HUMAN_RESPONSE_IDENTITY_MISMATCH, f"answer {path.name} is "
                             f"{ENTRY_SCHEMA}")
        if entry["intent"] != identity:
            raise HumanError(
                HUMAN_RESPONSE_IDENTITY_MISMATCH,
                f"answer {path.name} answers another intent than the one it is filed under",
            )
        return entry


def require_desk_transport(contract: HumanActorContractV1, channel: object) -> None:
    """The desk carries this contract's exchanges, or nothing is asked (BVL-HUMAN-009)."""

    if getattr(channel, "TRANSPORT", None) != DESK_TRANSPORT:
        raise HumanError(
            HUMAN_EXECUTION_UNSUPPORTED,
            f"human channel {contract.channel!r} states no transport this build carries "
            f"({DESK_TRANSPORT!r})",
        )
    if contract.privacy.response_content is not ResponseContent.IN_PACKAGE:
        raise HumanError(
            HUMAN_EXECUTION_UNSUPPORTED,
            f"human actor {contract.actor_id!r} keeps response content "
            f"{contract.privacy.response_content.value}; this build executes a human call "
            "only through the custody chain, which holds the content (IN_PACKAGE)",
        )


def require_desk(
    desk: HumanDeskV1 | None,
    run_directory: Path,
    humans: HumanActorContractSetV1,
    channels: Mapping[str, object],
) -> dict[str, dict[str, Any]]:
    """Everything a run needs before it may ask a person; nothing is written.

    A desk outside the run's evidence, a desk transport for every contract and
    an enrolled participant with a GRANTED consent record for every human
    actor.  Returns ``actor -> {participant, consent}``.
    """

    if desk is None:
        raise HumanError(
            HUMAN_EXECUTION_UNSUPPORTED,
            f"the plan asks human actors {sorted(humans.contracts)} and no desk is given to "
            "ask them through (--human-desk DIR): a person is never approximated by a call",
        )
    here, run = desk.root.resolve(), Path(run_directory).resolve()
    if here == run or run in here.parents or here in run.parents:
        raise HumanError(
            HUMAN_EXECUTION_UNSUPPORTED,
            f"desk {desk.root} and run {run_directory} hold each other: the desk is not "
            "evidence and lies outside the run directory",
        )
    enrolled = {}
    for actor_id, contract in sorted(humans.contracts.items()):
        require_desk_transport(contract, channels.get(contract.channel))
        participant, record = desk.enrolled(contract)
        enrolled[actor_id] = {"participant": participant,
                              "consent": record.identity().document()}
    return enrolled


def require_unused_desk(desk: HumanDeskV1) -> None:
    """A new run is asked through a desk nothing was delivered to (SV-09).

    A desk belongs to one run.  A second run of one study cell derives the
    intents of the first, so on the first run's desk it would find every
    request "delivered" and every answer entered: it would complete with nobody
    asked, on answers given to another run.  Nothing is written.
    """

    held = sorted(
        f"{box}/{path.name}"
        for box in (OUTBOX, INBOX)
        for path in (desk.root / box).glob("*")
    )
    if held:
        raise HumanError(
            HUMAN_EXECUTION_UNSUPPORTED,
            f"desk {desk.root} already carries the exchanges of a run ({len(held)} members, "
            f"first {held[0]}): a desk belongs to one run, and a new run is asked through a "
            "desk nothing was delivered to",
        )


@dataclass(frozen=True)
class HumanExchangeV1:
    """What one human actor call is asked through: contract, binding, channel, desk."""

    contract: HumanActorContractV1
    binding: ActorBindingV1
    channel: object
    desk: HumanDeskV1


def awaiting(journal: Journal2) -> list[dict[str, Any]]:
    """Every delivered human request of the journal that has no received response."""

    received = {
        canonical_json(record["human_intent"])
        for record in journal.of_event(HUMAN_RESPONSE_RECEIVED)
    }
    return [
        {"episode": record["episode"], "step": record["step"], "round": record["round"],
         "intent": record["human_intent"]}
        for record in journal.of_event(HUMAN_REQUEST_DELIVERED)
        if canonical_json(record["human_intent"]) not in received
    ]


def execute_human_call(
    calls: DurableCallExecutorV2,
    *,
    episode: EpisodeIdentity,
    step: StepIdentity,
    round_index: int,
    request: RequestV2,
    exchange: HumanExchangeV1,
    binding: EvidenceDocumentRefV2 | None = None,
    resume: bool = False,
) -> CompletedCallV2:
    """One human actor call through the durable call chain, or ``HumanResponsePending``.

    Every boundary is committed once: whatever an earlier process of the run
    made durable is matched, not repeated.
    """

    contract, desk = exchange.contract, exchange.desk
    journal, documents = calls.journal, EvidenceDocumentStoreV2(calls.run_directory)
    require_run_authorization_v2(calls.run_directory, run_id=calls.run_id, journal=journal)
    contract.require_channel(exchange.channel)
    require_desk_transport(contract, exchange.channel)
    participant, record = desk.enrolled(contract)
    intent = human_request_intent(
        contract, exchange.binding, step=step, request=request, consent=record,
        participant=participant,
    )
    intent_identity = intent.identity().document()

    request_ref = calls.requests.put(request)
    call = call_identity_v2(
        episode=episode, step=step, round_index=round_index, request=request_ref,
        adapter_plugin_identity=contract.channel,
    )
    if binding is not None:
        bound = documents.read(binding)
        if binding.role != "call_binding" or bound.get("call") != call.document():
            raise ExecutionError(f"call binding {binding.path} is not call {call}'s")
    consent_document = {"schema": CONSENT_EVIDENCE_SCHEMA,
                        "identity": record.identity().document(),
                        "record": record.document()}
    intent_document = {"schema": INTENT_EVIDENCE_SCHEMA, "identity": intent_identity,
                       "intent": intent.document(),
                       "consent": documents.ref("human_consent", consent_document).document()}
    named = {"human_intent": documents.ref("human_intent", intent_document).document()}
    if binding is not None:
        named["call_binding"] = binding.document()

    if journal.torn_tail():
        raise ExecutionError("journal-2 has a torn tail; refusing to append call evidence")
    if CustodyLedgerV2(calls.run_directory).torn_tail():
        raise ExecutionError("custody-v2 has a torn tail; refusing to append call evidence")
    calls.require_step_call(episode=episode, step=step, call=call)
    classified = classify_actor_call(
        run_directory=calls.run_directory, call=call, journal=journal,
        requests=calls.requests, artifacts=calls.artifacts,
    )
    scope = {"run": calls.run_id, "episode": str(episode), "step": str(step),
             "round": round_index}
    state = classified.state
    if state is CallStateV2.NOT_STARTED:
        # consent and intent are evidence before the intent event that names them
        documents.put("human_consent", consent_document)
        documents.put("human_intent", intent_document)
        journal.append_event(
            CALL_INTENT_RECORDED, **scope, call=str(call), request=request_ref.document(), **named
        )
    else:
        recorded = journal.of_call(str(call))[0]
        if recorded["run"] != calls.run_id or any(
            recorded.get(name) != named.get(name) for name in ("human_intent", "call_binding")
        ):
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"call {call} was intended for another human request intent than "
                f"{intent_identity['digest']} re-derives: nobody else is asked for it",
            )
        if resume and state is CallStateV2.CUSTODY_ACCEPTED:
            return calls._recorded(call, request_ref, named)
        if state not in (CallStateV2.INTENT_RECORDED, HumanCallStateV1.AWAITING_HUMAN,
                         HumanCallStateV1.HUMAN_RETURNED):
            raise ResumeRefusedError(
                RESUME_OUTCOME_NOT_PROVEN,
                f"human call {call} is {state.value}; resume decision "
                f"{classified.decision.value}"
                + (f" ({classified.reason})" if classified.reason else ""),
            )
    if state in (CallStateV2.NOT_STARTED, CallStateV2.INTENT_RECORDED):
        journal.append_event(TRANSPORT_STARTED, **scope, call=str(call))

    # one delivery per intent: the desk creates it once, the journal commits it once
    grade = ProvenanceGrade(exchange.channel.PROVENANCE_GRADE)  # type: ignore[attr-defined]
    try:
        delivery = desk.deliver(contract, intent, request, grade)
    except HumanError as error:
        raise HumanDeskRefusedError(error) from None
    commit(journal, HUMAN_REQUEST_DELIVERED, resumed=True, **scope,
           human_intent=intent_identity, delivery=delivery)
    try:
        entry = desk.collect(intent)
    except HumanError as error:
        raise HumanDeskRefusedError(error) from None
    if entry is None:
        raise HumanResponsePending({
            "actor": contract.actor_id, "participant": participant, "channel": contract.channel,
            "intent": intent_identity, "step": str(step), "round": round_index,
            "desk": str(desk.root),
        })

    content = entry["text"].encode("utf-8")
    try:
        provenance = HumanProvenanceV1(grade, contract.channel, entry["entered_by"])
    except HumanError as error:
        raise HumanError(HUMAN_PROVENANCE_INVALID, f"the entered answer: {error}") from None
    response = human_response(contract, intent, content, provenance)
    verify_human_exchange(
        contract, exchange.binding, step=step, request=request.identity(),
        channel=exchange.channel, consent=record.document(), intent=intent.document(),
        response=response.document(), content=content,
    )
    response_document = {
        "schema": RESPONSE_EVIDENCE_SCHEMA, "identity": response.identity().document(),
        "response": response.document(),
    }
    # one response per intent: another answer than the committed one is BVL-RES-001,
    # refused before it becomes a member
    received = documents.ref("human_response", response_document)
    if any(
        record["event"] == HUMAN_RESPONSE_RECEIVED
        and record["human_response"] != received.document()
        for record in journal.of_step(str(step))
    ):
        raise ResumeRefusedError(
            RESUME_EVIDENCE_MISMATCH,
            f"human call {call} received another answer than desk {desk.root} holds now",
        )
    documents.put("human_response", response_document)
    commit(journal, HUMAN_RESPONSE_RECEIVED, resumed=True, **scope,
           human_intent=intent_identity, human_response=received.document())

    returned = ActorResponseV2(
        content=content, model_identity=HUMAN_MODEL,
        adapter_provenance=f"{contract.channel}:{provenance.grade.value}",
    )
    stated = {
        "content_digest": str(sha256_bytes(content)),
        "model_identity": returned.model_identity,
        "adapter_provenance": returned.adapter_provenance,
    }
    name = call_artifact_name(call)
    chain = {event["event"]: event for event in journal.of_call(str(call))}
    if state is HumanCallStateV1.HUMAN_RETURNED:
        # the call returned in an earlier process: the desk's answer is that one
        if chain[CALL_RETURNED]["response"] != stated:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"human call {call} returned another answer than desk {desk.root} holds",
            )
    else:
        journal.append_event(CALL_RETURNED, **scope, call=str(call), response=stated)
    if calls.artifacts.exists(name):
        # persisted by the process that stopped: the member is the answer
        artifact = ArtifactRef(name, content_identity(content))
        if calls.artifacts.path(name).read_bytes() != content:
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"human call {call} response member is not the answer desk {desk.root} holds",
            )
    else:
        artifact = calls.artifacts.put(name, content)
    if CALL_PERSISTED not in chain:
        journal.append_event(
            CALL_PERSISTED, **scope, call=str(call), artifact=artifact.document()
        )
    _, custody = accept_call_v2(
        run_directory=calls.run_directory, run_id=calls.run_id, call=call, journal=journal,
        requests=calls.requests, artifacts=calls.artifacts,
    )
    return CompletedCallV2(call, request_ref, returned, artifact, custody)
