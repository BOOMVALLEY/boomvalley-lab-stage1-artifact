"""P17 Human Actor contract (T5-001).

A human actor is a plan actor (P04) whose answers come from a person, through
a registered ``human_channel`` plugin, instead of from a provider adapter.  It
is the same organizational participant - same ActorIdentity, same information
rights (P05), same proposal and decision path (P06 / P07) - and four things a
model call leaves implicit are made explicit, each with its own identity:

    contract   the terms the actor answers under      HumanActorContractIdentity
               (declaration, frozen into the plan as ``semantic-plan-9``)
    consent    one participant's consent record       HumanConsentIdentity
    intent     the intent to ask one participant one  HumanRequestIntentIdentity
               persisted request-2
    response   the participant's answer to that       HumanResponseIdentity
               intent, and how it reached the product

The chain is one way and closed::

    request-2 (RequestIdentity)
        -> human request intent  = step x actor x request x contract
                                   x channel x participant x consent x privacy
        -> human response        = intent x participant x content digest
                                   x provenance x consent

so a response names exactly one intent and through it exactly one persisted
request, one participant and one consent record; it cannot be attached to
another request, actor, round or person (BVL-HUMAN-006 / -007).

Request intent.  The scientific request a person is shown is the same
request-2 every actor gets (P05 renders it from the actor's authorized
sources; nothing here renders).  Its ``model_identity`` is the reserved
``HUMAN_MODEL`` - a human profile states that no model answers - and it carries
no generation options.  The intent is built from the persisted request, before
anything is delivered.

Provenance.  How an answer reached the product is graded, never assumed:

    CHANNEL_AUTHENTICATED  the channel authenticated the participant itself
    OPERATOR_ENTERED       an operator entered the answer for the participant
    UNVERIFIABLE           nothing corroborates who answered

A contract states the least grade it accepts and a channel the grade it can
attest; a response claims no more than its channel attests and no less than
the contract accepts (BVL-HUMAN-008).  An operator-entered answer names the
operator.

Consent and privacy.  A contract names the consent basis and the digest of
the consent terms; a participant is asked only under a GRANTED record for
exactly those terms (BVL-HUMAN-004).  A participant is only ever a pseudonym
(``participant:<token>``); no identity document here has a field for a name
or a contact.  The contract classifies the data and says whether the answer's
content enters the evidence package or only its digest does; PERSONAL content
never enters a package, which is immutable and cannot honour a deletion
(BVL-HUMAN-005).

What this module does not do: deliver a request, wait for an answer or resume
after one.  Those are the WAITING lifecycle (T5-002, ``kernel/waiting.py``),
which asks through the contracts and documents defined here.  A plan it cannot
ask for - no desk to ask through, a channel the desk does not carry, answers
whose content may not enter the run - is refused at ``run`` before anything is
written (BVL-HUMAN-009): running nothing is better than approximating a person
with a call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.identity.kinds import RequestIdentity
from boomvalley_lab.kernel.actors import ActorBindingSetV1, ActorBindingV1
from boomvalley_lab.kernel.identity import ActorIdentity, StepIdentity, _KernelIdentity
from boomvalley_lab.kernel.request import RequestV2

# The four P17 identities.  They are K0-shaped digest identities owned here, not
# in ``kernel.identity``: that module is the identity set T0-GATE froze and
# re-derives from run evidence, and no run can evidence a human exchange yet.


@dataclass(frozen=True)
class HumanActorContractIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "human_actor_contract"
    IDENTIFIES: ClassVar[str] = (
        "the terms one human actor answers under: channel, response form, provenance, "
        "consent and privacy"
    )
    EXISTS: ClassVar[str] = "declaration"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("actor", "execution_profile", "participant")
    SCHEMA: ClassVar[str] = "bvl-human-actor-contract-identity-1"


@dataclass(frozen=True)
class HumanConsentIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "human_consent"
    IDENTIFIES: ClassVar[str] = "one participant's consent record under one human actor contract"
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("participant", "the consent form's content")
    SCHEMA: ClassVar[str] = "bvl-human-consent-identity-1"


@dataclass(frozen=True)
class HumanRequestIntentIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "human_request_intent"
    IDENTIFIES: ClassVar[str] = (
        "the intent to ask one participant one persisted request: step x actor x request x "
        "contract x participant x consent"
    )
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("request", "call", "human_response")
    SCHEMA: ClassVar[str] = "bvl-human-request-intent-identity-1"


@dataclass(frozen=True)
class HumanResponseIdentity(_KernelIdentity):
    KIND: ClassVar[str] = "human_response"
    IDENTIFIES: ClassVar[str] = (
        "one participant's answer to one human request intent: its content digest and how "
        "it reached the product"
    )
    EXISTS: ClassVar[str] = "runtime"
    NEVER_STANDS_FOR: ClassVar[tuple[str, ...]] = ("proposal", "decision", "participant")
    SCHEMA: ClassVar[str] = "bvl-human-response-identity-1"


CONTRACT_SCHEMA = "bvl-human-actor-contract-1"
CONTRACT_SET_SCHEMA = "bvl-human-actor-contract-set-1"
CONSENT_SCHEMA = "bvl-human-consent-record-1"
INTENT_SCHEMA = "bvl-human-request-intent-1"
RESPONSE_SCHEMA = "bvl-human-response-1"

#: the model identity of a human profile: no model answers this actor
HUMAN_MODEL = "bvl:human-participant:1"

# P17 stable reason-code family
HUMAN_CONTRACT_INVALID = "BVL-HUMAN-001"
HUMAN_CHANNEL_UNSUPPORTED = "BVL-HUMAN-002"
HUMAN_PROFILE_MISMATCH = "BVL-HUMAN-003"
HUMAN_CONSENT_NOT_GRANTED = "BVL-HUMAN-004"
HUMAN_PRIVACY_VIOLATED = "BVL-HUMAN-005"
HUMAN_INTENT_MISMATCH = "BVL-HUMAN-006"
HUMAN_RESPONSE_IDENTITY_MISMATCH = "BVL-HUMAN-007"
HUMAN_PROVENANCE_INVALID = "BVL-HUMAN-008"
HUMAN_EXECUTION_UNSUPPORTED = "BVL-HUMAN-009"
# T5-002: one intent is delivered once and answered once
HUMAN_EXCHANGE_CONTRADICTED = "BVL-HUMAN-010"

HUMAN_CODES = frozenset(
    {
        HUMAN_CONTRACT_INVALID,
        HUMAN_CHANNEL_UNSUPPORTED,
        HUMAN_PROFILE_MISMATCH,
        HUMAN_CONSENT_NOT_GRANTED,
        HUMAN_PRIVACY_VIOLATED,
        HUMAN_INTENT_MISMATCH,
        HUMAN_RESPONSE_IDENTITY_MISMATCH,
        HUMAN_PROVENANCE_INVALID,
        HUMAN_EXECUTION_UNSUPPORTED,
        HUMAN_EXCHANGE_CONTRADICTED,
    }
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_PLUGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_PARTICIPANT = re.compile(r"participant:[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_OPERATOR = re.compile(r"operator:[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_IDENTITY_KEYS = frozenset({"kind", "digest"})


class HumanError(DeclarationError):
    """A P17 refusal carrying one stable ``BVL-HUMAN-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in HUMAN_CODES:
            raise ValueError(f"unknown human reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


class ResponseModality(StrEnum):
    TEXT = "text"


class ProvenanceGrade(StrEnum):
    CHANNEL_AUTHENTICATED = "CHANNEL_AUTHENTICATED"
    OPERATOR_ENTERED = "OPERATOR_ENTERED"
    UNVERIFIABLE = "UNVERIFIABLE"

    @property
    def strength(self) -> int:
        return _STRENGTH[self]


_STRENGTH = {
    ProvenanceGrade.UNVERIFIABLE: 0,
    ProvenanceGrade.OPERATOR_ENTERED: 1,
    ProvenanceGrade.CHANNEL_AUTHENTICATED: 2,
}


class ConsentBasis(StrEnum):
    INFORMED_CONSENT = "INFORMED_CONSENT"
    RESEARCHER_PARTICIPANT = "RESEARCHER_PARTICIPANT"


class ConsentStatus(StrEnum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class PrivacyClassification(StrEnum):
    NO_PERSONAL_DATA = "NO_PERSONAL_DATA"
    PSEUDONYMOUS = "PSEUDONYMOUS"
    PERSONAL = "PERSONAL"


class ResponseContent(StrEnum):
    IN_PACKAGE = "IN_PACKAGE"
    DIGEST_ONLY = "DIGEST_ONLY"


def _closed(value: Any, keys: frozenset[str] | set[str], what: str, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise HumanError(code, f"{what} is an object with exactly the keys {sorted(keys)}")
    return value


def _enum(kind: type[StrEnum], value: Any, what: str, code: str) -> Any:
    if isinstance(value, kind):
        return value
    if not isinstance(value, str) or value not in {item.value for item in kind}:
        raise HumanError(
            code, f"{what} {value!r} is not one of {sorted(item.value for item in kind)}"
        )
    return kind(value)


def _sha256(value: Any, what: str, code: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise HumanError(code, f"{what} is a 'sha256:<64 hex>' digest, not {value!r}")
    return value


def require_participant(value: Any) -> str:
    """A participant is a pseudonym and nothing else (BVL-HUMAN-005)."""

    if not isinstance(value, str) or not _PARTICIPANT.fullmatch(value):
        raise HumanError(
            HUMAN_PRIVACY_VIOLATED,
            "a participant is named by a pseudonym 'participant:<token>' (letters, digits, "
            "'_' and '-'); a name, an address or a contact never enters evidence",
        )
    return value


def _identity(value: Any, kind: str, what: str, code: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != _IDENTITY_KEYS
        or value["kind"] != kind
        or not isinstance(value["digest"], str)
        or not _SHA256.fullmatch(value["digest"])
    ):
        raise HumanError(code, f"{what} is a {kind!r} identity document")
    return {"kind": kind, "digest": value["digest"]}


# ------------------------------------------------------------------ contract
@dataclass(frozen=True)
class HumanResponseFormV1:
    """The form of the answer the actor is asked for."""

    modality: ResponseModality
    max_chars: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "modality",
            _enum(ResponseModality, self.modality, "response modality", HUMAN_CONTRACT_INVALID),
        )
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int) or not (
            1 <= self.max_chars <= 1_000_000
        ):
            raise HumanError(
                HUMAN_CONTRACT_INVALID, "response max_chars is an integer in 1..1000000"
            )

    def document(self) -> dict[str, Any]:
        return {"modality": self.modality.value, "max_chars": self.max_chars}

    @classmethod
    def from_document(cls, document: Any) -> HumanResponseFormV1:
        document = _closed(document, {"modality", "max_chars"}, "response", HUMAN_CONTRACT_INVALID)
        return cls(document["modality"], document["max_chars"])


@dataclass(frozen=True)
class HumanConsentTermsV1:
    """The consent a participant is asked under: its basis and the terms' digest."""

    basis: ConsentBasis
    document_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "basis", _enum(ConsentBasis, self.basis, "consent basis", HUMAN_CONTRACT_INVALID)
        )
        _sha256(self.document_sha256, "consent document_sha256", HUMAN_CONTRACT_INVALID)

    def document(self) -> dict[str, Any]:
        return {"basis": self.basis.value, "document_sha256": self.document_sha256}

    @classmethod
    def from_document(cls, document: Any) -> HumanConsentTermsV1:
        document = _closed(
            document, {"basis", "document_sha256"}, "consent", HUMAN_CONTRACT_INVALID
        )
        return cls(document["basis"], document["document_sha256"])


@dataclass(frozen=True)
class HumanPrivacyV1:
    """What kind of data the answers are and where their content may live."""

    classification: PrivacyClassification
    response_content: ResponseContent

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "classification",
            _enum(
                PrivacyClassification,
                self.classification,
                "privacy classification",
                HUMAN_CONTRACT_INVALID,
            ),
        )
        object.__setattr__(
            self,
            "response_content",
            _enum(
                ResponseContent,
                self.response_content,
                "privacy response_content",
                HUMAN_CONTRACT_INVALID,
            ),
        )
        if (
            self.classification is PrivacyClassification.PERSONAL
            and self.response_content is not ResponseContent.DIGEST_ONLY
        ):
            raise HumanError(
                HUMAN_PRIVACY_VIOLATED,
                "PERSONAL response content never enters an evidence package (a sealed package "
                "cannot honour a deletion); declare response_content DIGEST_ONLY",
            )

    def document(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "response_content": self.response_content.value,
        }

    @classmethod
    def from_document(cls, document: Any) -> HumanPrivacyV1:
        document = _closed(
            document, {"classification", "response_content"}, "privacy", HUMAN_CONTRACT_INVALID
        )
        return cls(document["classification"], document["response_content"])


@dataclass(frozen=True)
class HumanActorContractV1:
    """The terms one plan actor answers under as a person."""

    actor_id: str
    channel: str  # the human_channel's registered plugin identity
    response: HumanResponseFormV1
    minimum_provenance: ProvenanceGrade
    consent: HumanConsentTermsV1
    privacy: HumanPrivacyV1

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not _ID.fullmatch(self.actor_id):
            raise HumanError(
                HUMAN_CONTRACT_INVALID, f"human actor id {self.actor_id!r} is not an identifier"
            )
        if not isinstance(self.channel, str) or not _PLUGIN.fullmatch(self.channel):
            raise HumanError(
                HUMAN_CONTRACT_INVALID,
                f"human actor {self.actor_id!r} channel is a registered plugin identity",
            )
        for name, kind in (
            ("response", HumanResponseFormV1),
            ("consent", HumanConsentTermsV1),
            ("privacy", HumanPrivacyV1),
        ):
            if not isinstance(getattr(self, name), kind):
                raise HumanError(
                    HUMAN_CONTRACT_INVALID, f"human actor {self.actor_id!r} {name} is undeclared"
                )
        object.__setattr__(
            self,
            "minimum_provenance",
            _enum(
                ProvenanceGrade,
                self.minimum_provenance,
                "provenance minimum_grade",
                HUMAN_CONTRACT_INVALID,
            ),
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "actor_id": self.actor_id,
            "channel": self.channel,
            "response": self.response.document(),
            "provenance": {"minimum_grade": self.minimum_provenance.value},
            "consent": self.consent.document(),
            "privacy": self.privacy.document(),
        }

    def identity(self) -> HumanActorContractIdentity:
        return HumanActorContractIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> HumanActorContractV1:
        """Read one ``bvl-human-actor-contract-1`` back (closed shape)."""

        document = _closed(
            document,
            {"schema", "actor_id", "channel", "response", "provenance", "consent", "privacy"},
            "human actor contract",
            HUMAN_CONTRACT_INVALID,
        )
        if document["schema"] != CONTRACT_SCHEMA:
            raise HumanError(HUMAN_CONTRACT_INVALID, f"human actor contract is {CONTRACT_SCHEMA}")
        provenance = _closed(
            document["provenance"], {"minimum_grade"}, "provenance", HUMAN_CONTRACT_INVALID
        )
        return cls(
            actor_id=document["actor_id"],
            channel=document["channel"],
            response=HumanResponseFormV1.from_document(document["response"]),
            minimum_provenance=provenance["minimum_grade"],
            consent=HumanConsentTermsV1.from_document(document["consent"]),
            privacy=HumanPrivacyV1.from_document(document["privacy"]),
        )

    def require_binding(self, binding: ActorBindingV1) -> None:
        """The actor's frozen profile is a human profile on this channel (BVL-HUMAN-003)."""

        profile = binding.profile
        if binding.actor_id != self.actor_id:
            raise HumanError(
                HUMAN_PROFILE_MISMATCH,
                f"the contract of {self.actor_id!r} is held to actor {binding.actor_id!r}",
            )
        if profile.model != HUMAN_MODEL:
            raise HumanError(
                HUMAN_PROFILE_MISMATCH,
                f"human actor {self.actor_id!r} is bound to model {profile.model!r}; a human "
                f"profile states the model {HUMAN_MODEL!r}",
            )
        if profile.provider != self.channel:
            raise HumanError(
                HUMAN_PROFILE_MISMATCH,
                f"human actor {self.actor_id!r} is contracted on channel {self.channel!r}; its "
                f"profile names {profile.provider!r}",
            )
        if profile.options:
            raise HumanError(
                HUMAN_PROFILE_MISMATCH,
                f"human actor {self.actor_id!r} profile carries generation options "
                f"{sorted(profile.options)}; a person has none",
            )

    def require_channel(self, channel: object) -> None:
        """The registered channel carries this contract (BVL-HUMAN-002).

        A channel states the modalities it carries (``MODALITIES``) and the
        strongest provenance it can attest (``PROVENANCE_GRADE``).
        """

        modalities = getattr(channel, "MODALITIES", None)
        grade = getattr(channel, "PROVENANCE_GRADE", None)
        try:
            attested = ProvenanceGrade(grade)
            carried = frozenset(ResponseModality(item) for item in modalities)
        except (TypeError, ValueError):
            raise HumanError(
                HUMAN_CHANNEL_UNSUPPORTED,
                f"human channel {self.channel!r} does not state its MODALITIES and "
                "PROVENANCE_GRADE",
            ) from None
        if self.response.modality not in carried:
            raise HumanError(
                HUMAN_CHANNEL_UNSUPPORTED,
                f"human channel {self.channel!r} carries {sorted(carried)}; actor "
                f"{self.actor_id!r} answers in {self.response.modality.value!r}",
            )
        if attested.strength < self.minimum_provenance.strength:
            raise HumanError(
                HUMAN_CHANNEL_UNSUPPORTED,
                f"human channel {self.channel!r} attests {attested.value}; actor "
                f"{self.actor_id!r} accepts no less than {self.minimum_provenance.value}",
            )


@dataclass(frozen=True)
class HumanActorContractSetV1:
    """The human actors of one plan; this is what enters the plan (plan-9)."""

    contracts: Mapping[str, HumanActorContractV1] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.contracts:
            raise HumanError(
                HUMAN_CONTRACT_INVALID, "a human contract set declares at least one human actor"
            )
        for actor_id, contract in self.contracts.items():
            if not isinstance(contract, HumanActorContractV1) or contract.actor_id != actor_id:
                raise HumanError(
                    HUMAN_CONTRACT_INVALID, f"human contract {actor_id!r} names another actor"
                )
        object.__setattr__(self, "contracts", MappingProxyType(dict(self.contracts)))

    def __contains__(self, actor_id: object) -> bool:
        return actor_id in self.contracts

    @classmethod
    def of(cls, contracts: Any) -> HumanActorContractSetV1:
        unique: dict[str, HumanActorContractV1] = {}
        for contract in contracts:
            if contract.actor_id in unique:
                raise HumanError(
                    HUMAN_CONTRACT_INVALID,
                    f"human actor {contract.actor_id!r} is contracted twice",
                )
            unique[contract.actor_id] = contract
        return cls(unique)

    def contract(self, actor_id: str) -> HumanActorContractV1:
        contract = self.contracts.get(actor_id) if isinstance(actor_id, str) else None
        if contract is None:
            raise HumanError(
                HUMAN_PROFILE_MISMATCH, f"actor {actor_id!r} is not a human actor of the plan"
            )
        return contract

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SET_SCHEMA,
            "actors": [self.contracts[key].document() for key in sorted(self.contracts)],
        }

    @classmethod
    def from_document(cls, document: Any) -> HumanActorContractSetV1:
        document = _closed(
            document, {"schema", "actors"}, "human contract set", HUMAN_CONTRACT_INVALID
        )
        if document["schema"] != CONTRACT_SET_SCHEMA or not isinstance(document["actors"], list):
            raise HumanError(HUMAN_CONTRACT_INVALID, f"human contract set is {CONTRACT_SET_SCHEMA}")
        parsed = cls.of(HumanActorContractV1.from_document(item) for item in document["actors"])
        if parsed.document() != document:
            raise HumanError(HUMAN_CONTRACT_INVALID, "human contract set is not canonical")
        return parsed

    def require_actors(self, actors: ActorBindingSetV1 | None) -> None:
        """Exactly the contracted actors are human, before anything runs (BVL-HUMAN-003).

        Every contract names a plan actor on a human profile, and no other
        actor claims the human model: a person is never asked without terms.
        """

        if actors is None:
            raise HumanError(
                HUMAN_PROFILE_MISMATCH, "human contracts are held to the actors of a P04 plan"
            )
        for actor_id in sorted(self.contracts):
            if actor_id not in actors:
                raise HumanError(
                    HUMAN_PROFILE_MISMATCH,
                    f"human actor {actor_id!r} is not an actor of the frozen plan",
                )
            self.contracts[actor_id].require_binding(actors.binding(actor_id))
        require_no_uncontracted_human(actors, self)


def require_no_uncontracted_human(
    actors: ActorBindingSetV1 | None, humans: HumanActorContractSetV1 | None
) -> None:
    """No actor states the human model without a contract (BVL-HUMAN-003)."""

    for actor_id, binding in sorted((actors.bindings if actors is not None else {}).items()):
        if binding.profile.model == HUMAN_MODEL and (humans is None or actor_id not in humans):
            raise HumanError(
                HUMAN_PROFILE_MISMATCH,
                f"actor {actor_id!r} states the human model {HUMAN_MODEL!r} and has no human "
                "actor contract: consent, privacy and provenance are undeclared",
            )


# ------------------------------------------------------------------ consent
@dataclass(frozen=True)
class HumanConsentRecordV1:
    """One participant's consent under one contract.  It holds no personal data:
    the signed form stays with the researcher; its terms are named by digest."""

    participant: str
    contract: Mapping[str, str]  # HumanActorContractIdentity document
    basis: ConsentBasis
    document_sha256: str
    status: ConsentStatus

    def __post_init__(self) -> None:
        require_participant(self.participant)
        object.__setattr__(
            self,
            "contract",
            _identity(
                self.contract,
                HumanActorContractIdentity.KIND,
                "consent contract",
                HUMAN_CONSENT_NOT_GRANTED,
            ),
        )
        object.__setattr__(
            self,
            "basis",
            _enum(ConsentBasis, self.basis, "consent basis", HUMAN_CONSENT_NOT_GRANTED),
        )
        object.__setattr__(
            self,
            "status",
            _enum(ConsentStatus, self.status, "consent status", HUMAN_CONSENT_NOT_GRANTED),
        )
        _sha256(self.document_sha256, "consent document_sha256", HUMAN_CONSENT_NOT_GRANTED)

    @classmethod
    def granted(cls, contract: HumanActorContractV1, participant: str) -> HumanConsentRecordV1:
        return cls(
            participant,
            contract.identity().document(),
            contract.consent.basis,
            contract.consent.document_sha256,
            ConsentStatus.GRANTED,
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONSENT_SCHEMA,
            "participant": self.participant,
            "contract": dict(self.contract),
            "basis": self.basis.value,
            "document_sha256": self.document_sha256,
            "status": self.status.value,
        }

    def identity(self) -> HumanConsentIdentity:
        return HumanConsentIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> HumanConsentRecordV1:
        document = _closed(
            document,
            {"schema", "participant", "contract", "basis", "document_sha256", "status"},
            "consent record",
            HUMAN_CONSENT_NOT_GRANTED,
        )
        if document["schema"] != CONSENT_SCHEMA:
            raise HumanError(HUMAN_CONSENT_NOT_GRANTED, f"consent record is {CONSENT_SCHEMA}")
        return cls(
            document["participant"],
            document["contract"],
            document["basis"],
            document["document_sha256"],
            document["status"],
        )

    def require(self, contract: HumanActorContractV1, participant: str) -> None:
        """GRANTED, by this participant, for exactly the contract's terms (BVL-HUMAN-004)."""

        if self.participant != participant:
            raise HumanError(
                HUMAN_CONSENT_NOT_GRANTED,
                f"the consent record is {self.participant}'s, not {participant}'s",
            )
        if dict(self.contract) != contract.identity().document():
            raise HumanError(
                HUMAN_CONSENT_NOT_GRANTED,
                f"the consent record was given under another contract than "
                f"{contract.actor_id!r}'s",
            )
        if (self.basis, self.document_sha256) != (
            contract.consent.basis,
            contract.consent.document_sha256,
        ):
            raise HumanError(
                HUMAN_CONSENT_NOT_GRANTED,
                "the consent record names other terms than the contract's "
                f"({contract.consent.basis.value}, {contract.consent.document_sha256})",
            )
        if self.status is not ConsentStatus.GRANTED:
            raise HumanError(
                HUMAN_CONSENT_NOT_GRANTED,
                f"consent of {self.participant} is {self.status.value}; nobody is asked "
                "without a GRANTED record",
            )


# ------------------------------------------------------------------- intent
@dataclass(frozen=True)
class HumanRequestIntentV1:
    """The intent to ask one participant one persisted request-2."""

    step: Mapping[str, str]
    actor: Mapping[str, str]
    request: Mapping[str, str]
    contract: Mapping[str, str]
    channel: str
    participant: str
    consent: Mapping[str, str]
    privacy: Mapping[str, str]

    def __post_init__(self) -> None:
        for name, kind in (
            ("step", StepIdentity.KIND),
            ("actor", ActorIdentity.KIND),
            ("request", RequestIdentity.KIND),
            ("contract", HumanActorContractIdentity.KIND),
            ("consent", HumanConsentIdentity.KIND),
        ):
            object.__setattr__(
                self,
                name,
                _identity(getattr(self, name), kind, f"intent {name}", HUMAN_INTENT_MISMATCH),
            )
        if not isinstance(self.channel, str) or not _PLUGIN.fullmatch(self.channel):
            raise HumanError(HUMAN_INTENT_MISMATCH, "intent channel is a plugin identity")
        require_participant(self.participant)
        object.__setattr__(self, "privacy", HumanPrivacyV1.from_document(self.privacy).document())

    def document(self) -> dict[str, Any]:
        return {
            "schema": INTENT_SCHEMA,
            "step": dict(self.step),
            "actor": dict(self.actor),
            "request": dict(self.request),
            "contract": dict(self.contract),
            "channel": self.channel,
            "participant": self.participant,
            "consent": dict(self.consent),
            "privacy": dict(self.privacy),
        }

    def identity(self) -> HumanRequestIntentIdentity:
        return HumanRequestIntentIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> HumanRequestIntentV1:
        keys = {
            "schema", "step", "actor", "request", "contract", "channel", "participant",
            "consent", "privacy",
        }
        document = _closed(document, keys, "human request intent", HUMAN_INTENT_MISMATCH)
        if document["schema"] != INTENT_SCHEMA:
            raise HumanError(HUMAN_INTENT_MISMATCH, f"human request intent is {INTENT_SCHEMA}")
        return cls(**{key: document[key] for key in keys - {"schema"}})


def human_request_intent(
    contract: HumanActorContractV1,
    binding: ActorBindingV1,
    *,
    step: StepIdentity,
    request: RequestV2,
    consent: HumanConsentRecordV1,
    participant: str,
) -> HumanRequestIntentV1:
    """Build the intent for one persisted request, or refuse before anyone is asked.

    The request is the actor's own request-2: the human model, the profile's
    renderer, no options (BVL-HUMAN-006).  The participant holds a GRANTED
    consent record for the contract's terms (BVL-HUMAN-004).
    """

    contract.require_binding(binding)
    require_participant(participant)
    if not isinstance(request, RequestV2) or request.model_identity != HUMAN_MODEL:
        raise HumanError(
            HUMAN_INTENT_MISMATCH,
            f"the request of human actor {contract.actor_id!r} states the model "
            f"{getattr(request, 'model_identity', None)!r}, not {HUMAN_MODEL!r}",
        )
    if request.renderer_identity != binding.profile.renderer or dict(request.options):
        raise HumanError(
            HUMAN_INTENT_MISMATCH,
            f"the request of human actor {contract.actor_id!r} is not rendered under its "
            "profile (renderer and no options)",
        )
    consent.require(contract, participant)
    return HumanRequestIntentV1(
        step=step.document(),
        actor=binding.identity.document(),
        request=request.identity().document(),
        contract=contract.identity().document(),
        channel=contract.channel,
        participant=participant,
        consent=consent.identity().document(),
        privacy=contract.privacy.document(),
    )


# ----------------------------------------------------------------- response
@dataclass(frozen=True)
class HumanProvenanceV1:
    """How one answer reached the product: graded, never assumed."""

    grade: ProvenanceGrade
    channel: str
    entered_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "grade",
            _enum(ProvenanceGrade, self.grade, "provenance grade", HUMAN_PROVENANCE_INVALID),
        )
        if not isinstance(self.channel, str) or not _PLUGIN.fullmatch(self.channel):
            raise HumanError(HUMAN_PROVENANCE_INVALID, "provenance channel is a plugin identity")
        entered = self.grade is ProvenanceGrade.OPERATOR_ENTERED
        named = isinstance(self.entered_by, str) and bool(_OPERATOR.fullmatch(self.entered_by))
        if entered != (self.entered_by is not None) or (entered and not named):
            raise HumanError(
                HUMAN_PROVENANCE_INVALID,
                "an OPERATOR_ENTERED answer names its operator as 'operator:<token>', and "
                "only such an answer does",
            )

    def document(self) -> dict[str, Any]:
        return {"grade": self.grade.value, "channel": self.channel, "entered_by": self.entered_by}

    @classmethod
    def from_document(cls, document: Any) -> HumanProvenanceV1:
        # canonical evidence has no null: an answer no operator entered is
        # persisted without ``entered_by`` and reads back as it was (T5-008)
        required = {"grade", "channel"}
        if not isinstance(document, Mapping) or not (
            required <= set(document) <= required | {"entered_by"}
        ):
            raise HumanError(
                HUMAN_PROVENANCE_INVALID,
                "provenance is an object with the keys ['channel', 'grade'] and, when an "
                "operator entered the answer, 'entered_by'",
            )
        return cls(document["grade"], document["channel"], document.get("entered_by"))


@dataclass(frozen=True)
class HumanResponseV1:
    """One participant's answer to one intent.  It carries the content's digest
    and size, never the content."""

    intent: Mapping[str, str]
    participant: str
    consent: Mapping[str, str]
    modality: ResponseModality
    content_sha256: str
    size: int
    provenance: HumanProvenanceV1

    def __post_init__(self) -> None:
        code = HUMAN_RESPONSE_IDENTITY_MISMATCH
        object.__setattr__(
            self,
            "intent",
            _identity(self.intent, HumanRequestIntentIdentity.KIND, "response intent", code),
        )
        object.__setattr__(
            self,
            "consent",
            _identity(self.consent, HumanConsentIdentity.KIND, "response consent", code),
        )
        require_participant(self.participant)
        object.__setattr__(
            self, "modality", _enum(ResponseModality, self.modality, "response modality", code)
        )
        _sha256(self.content_sha256, "response content_sha256", code)
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise HumanError(code, "response size is a non-negative byte count")
        if not isinstance(self.provenance, HumanProvenanceV1):
            raise HumanError(HUMAN_PROVENANCE_INVALID, "a response states its provenance")

    def document(self) -> dict[str, Any]:
        return {
            "schema": RESPONSE_SCHEMA,
            "intent": dict(self.intent),
            "participant": self.participant,
            "consent": dict(self.consent),
            "modality": self.modality.value,
            "content_sha256": self.content_sha256,
            "size": self.size,
            "provenance": self.provenance.document(),
        }

    def identity(self) -> HumanResponseIdentity:
        return HumanResponseIdentity.of_payload(self.document())

    @classmethod
    def from_document(cls, document: Any) -> HumanResponseV1:
        keys = {
            "schema", "intent", "participant", "consent", "modality", "content_sha256", "size",
            "provenance",
        }
        document = _closed(document, keys, "human response", HUMAN_RESPONSE_IDENTITY_MISMATCH)
        if document["schema"] != RESPONSE_SCHEMA:
            raise HumanError(
                HUMAN_RESPONSE_IDENTITY_MISMATCH, f"human response is {RESPONSE_SCHEMA}"
            )
        return cls(
            intent=document["intent"],
            participant=document["participant"],
            consent=document["consent"],
            modality=document["modality"],
            content_sha256=document["content_sha256"],
            size=document["size"],
            provenance=HumanProvenanceV1.from_document(document["provenance"]),
        )


def human_response(
    contract: HumanActorContractV1,
    intent: HumanRequestIntentV1,
    content: bytes,
    provenance: HumanProvenanceV1,
) -> HumanResponseV1:
    """Identify the answer to *intent*: by the intent's participant, under its consent."""

    if not isinstance(content, bytes):
        raise HumanError(HUMAN_RESPONSE_IDENTITY_MISMATCH, "a response's content is bytes")
    response = HumanResponseV1(
        intent=intent.identity().document(),
        participant=intent.participant,
        consent=intent.consent,
        modality=contract.response.modality,
        content_sha256=str(sha256_bytes(content)),
        size=len(content),
        provenance=provenance,
    )
    _require_content(contract, response, content)
    return response


def _require_content(
    contract: HumanActorContractV1, response: HumanResponseV1, content: bytes
) -> None:
    if (str(sha256_bytes(content)), len(content)) != (response.content_sha256, response.size):
        raise HumanError(
            HUMAN_RESPONSE_IDENTITY_MISMATCH,
            "the content is not the content the response identifies (digest and size)",
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HumanError(
            HUMAN_RESPONSE_IDENTITY_MISMATCH, "a text response is UTF-8"
        ) from None
    if len(text) > contract.response.max_chars:
        raise HumanError(
            HUMAN_RESPONSE_IDENTITY_MISMATCH,
            f"the response has {len(text)} characters; the contract admits "
            f"{contract.response.max_chars}",
        )


def verify_human_exchange(
    contract: HumanActorContractV1,
    binding: ActorBindingV1,
    *,
    step: StepIdentity,
    request: RequestIdentity,
    channel: object,
    consent: Any,
    intent: Any,
    response: Any,
    content: bytes | None,
) -> dict[str, Any]:
    """Re-derive one human exchange from its documents, or refuse it.

    *consent*, *intent* and *response* are the persisted documents; *request*
    and *step* the identities the evidence already holds for this actor call;
    *content* the answer's bytes as the evidence holds them - present exactly
    when the contract keeps content IN_PACKAGE.  Nothing is trusted because it
    is stated: every reference is recomputed from the document it names.
    """

    contract.require_binding(binding)
    contract.require_channel(channel)
    record = HumanConsentRecordV1.from_document(consent)
    asked = HumanRequestIntentV1.from_document(intent)
    answer = HumanResponseV1.from_document(response)

    # the intent is this step's, this actor's, this request's, under this contract
    expected = {
        "step": step.document(),
        "actor": binding.identity.document(),
        "request": request.document(),
        "contract": contract.identity().document(),
        "channel": contract.channel,
        "consent": record.identity().document(),
        "privacy": contract.privacy.document(),
    }
    for name, value in expected.items():
        held = getattr(asked, name)
        if (dict(held) if isinstance(held, Mapping) else held) != value:
            raise HumanError(
                HUMAN_INTENT_MISMATCH,
                f"the intent's {name} is not the {name} of this exchange",
            )
    record.require(contract, asked.participant)

    # the response is this intent's, by the participant who was asked
    if dict(answer.intent) != asked.identity().document():
        raise HumanError(
            HUMAN_RESPONSE_IDENTITY_MISMATCH, "the response answers another intent"
        )
    if answer.participant != asked.participant or dict(answer.consent) != dict(asked.consent):
        raise HumanError(
            HUMAN_RESPONSE_IDENTITY_MISMATCH,
            "the response is not by the participant who was asked, under the consent "
            "they were asked under",
        )
    if answer.modality is not contract.response.modality:
        raise HumanError(
            HUMAN_RESPONSE_IDENTITY_MISMATCH,
            f"the response is {answer.modality.value!r}; the contract asks for "
            f"{contract.response.modality.value!r}",
        )

    # provenance: the contract's channel, no more than it attests, no less than accepted
    provenance = answer.provenance
    attested = ProvenanceGrade(channel.PROVENANCE_GRADE)  # type: ignore[attr-defined]
    if provenance.channel != contract.channel:
        raise HumanError(
            HUMAN_PROVENANCE_INVALID,
            f"the response arrived through {provenance.channel!r}, not the contract's "
            f"channel {contract.channel!r}",
        )
    if provenance.grade.strength > attested.strength:
        raise HumanError(
            HUMAN_PROVENANCE_INVALID,
            f"the response claims {provenance.grade.value}; its channel attests "
            f"{attested.value}",
        )
    if provenance.grade.strength < contract.minimum_provenance.strength:
        raise HumanError(
            HUMAN_PROVENANCE_INVALID,
            f"the response is {provenance.grade.value}; the contract accepts no less than "
            f"{contract.minimum_provenance.value}",
        )

    # privacy: the content is where the contract says it is, and nowhere else
    in_package = contract.privacy.response_content is ResponseContent.IN_PACKAGE
    if in_package != (content is not None):
        raise HumanError(
            HUMAN_PRIVACY_VIOLATED,
            f"the contract keeps response content {contract.privacy.response_content.value}; "
            f"the evidence {'holds' if content is not None else 'does not hold'} it",
        )
    if content is not None:
        _require_content(contract, answer, content)
    return {
        "actor": contract.actor_id,
        "participant": asked.participant,
        "contract": contract.identity().document(),
        "consent": record.identity().document(),
        "request": request.document(),
        "intent": asked.identity().document(),
        "response": answer.identity().document(),
        "provenance_grade": provenance.grade.value,
        "response_content": contract.privacy.response_content.value,
    }


def execution_unsupported(actors: Any, why: str) -> HumanError:
    """The refusal of a run that cannot ask its human actors (BVL-HUMAN-009)."""

    return HumanError(
        HUMAN_EXECUTION_UNSUPPORTED,
        f"the plan asks human actors {sorted(actors)}; {why}, and a person is never "
        "approximated by a call: nothing is opened, nothing is asked",
    )
