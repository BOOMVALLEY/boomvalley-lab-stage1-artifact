"""Durable K0 World transition boundary (T0-011).

Ordering is structural:

    require the run's gate-2 authorization (T0-012)
    -> verify the decision's source call is custody-accepted (custody-entry-2)
    -> derive WorldTransitionIntent (binds pre-state, decision, custody, seed)
    -> journal WORLD_INTENT_RECORDED (carries the full intent payload)
    -> world.apply exactly once
    -> persist world_transition evidence (binds the intent)
    -> persist world_state evidence
    -> journal WORLD_APPLIED (binds intent + both evidence refs)

WORLD_APPLIED is the commit: a transition is applied to the episode only when
it is journaled.  Before any write the executor classifies the step from
durable evidence; classification is read-only and deterministic and never
invokes a World:

    (nothing)                        NOT_STARTED          -> EXECUTE
    intent only, no outcome evidence INTENT_RECORDED      -> EXECUTE (continue
                                     the recorded intent; a PureWorld left no
                                     durable outcome, nothing was committed)
    intent + transition evidence     TRANSITION_PERSISTED -> RECOVER (journal
                                     WORLD_APPLIED from the persisted evidence;
                                     the World is never re-applied)
    intent + WORLD_OUTCOME_UNKNOWN   OUTCOME_UNKNOWN      -> OPERATOR_DECISION
    intent + WORLD_APPLIED, whole
        chain re-verifies            APPLIED              -> SKIP
    anything else / tamper / a
        different intent for the
        same step                    INCONSISTENT         -> ABORT

There is no RETRY decision: once a durable outcome exists (evidence, unknown
or commit) the World is never applied again for that step.

Under a plan's World contract (T3-001, ``kernel/world.py``) every state this
boundary names is a state of the contract's schema version: the intent is
``world-intent-3`` and the evidence ``world-transition-evidence-3`` /
``world-state-evidence-2``, each stating the ``state_schema`` its versioned
pre/post state identities are derived under.  The pre-state must be, and the
post-state is checked to be, a state of that schema (BVL-WORLD-007: the
transition is never committed).  Without a contract the K0 documents
(intent-2, evidence-2, state-evidence-1) keep their meaning.

Under a contract the intent is ``world-intent-5`` (T3-002): it carries
``action``, the exact action the World is handed, and the chain

    DECISION_RECORDED.requested_action            the Decision Artifact's action
    == WORLD_INTENT_RECORDED ... payload.action   durable before apply
    == the argument of World.apply                decoded from the intent
    == world_transition.transition.requested_action

is closed at every link.  Nothing is intended for an action that is not the
committed decision's; the World receives a copy decoded from the intent's own
canonical bytes, never the caller's object; a World reporting a transition of
another action commits nothing (BVL-WORLD-006).  ``world_action_problems`` is
the verifier's recomputation of the same chain from the journal and the
evidence alone.

Domain admissibility (T3-003) is the World's verdict, preserved as data.  The
contract freezes the World's action schema and the ``bvl-world-admissibility-1``
vocabulary; the transition states its requested, admissible and executed
actions separately and the boundary derives none of them from another:

    requested action outside the action schema  BVL-WORLD-004, before any intent:
                                                nothing is journaled, no World runs
    a verdict outside the vocabulary, or one    BVL-WORLD-006: nothing is committed
        its three actions contradict

A CLIPPED or INADMISSIBLE verdict is not a failure: the transition commits
with all three actions as the World stated them.  ``world_admissibility_problems``
is the verifier's recomputation from the committed evidence.

NO_ACTION and exogenous events (T3-004) are the contract's frozen progression
(``bvl-world-progression-1``, ``kernel/world.py``).  The intent is
``world-intent-5``: it states ``action_input``, so a NO_ACTION decision is
intended as NO_ACTION, never as the empty action, and its World is handed
``None``.  The committed transition is a ``bvl-world-transition-2`` stating
whether an action was executed and every exogenous event that occurred:

    a NO_ACTION decision, no World contract     refused: K0 has no such semantics
    a NO_ACTION decision, meaning UNDECLARED    BVL-WORLD-008, before any intent
    an intent input that is not its decision's  refused before any intent
        outcome
    a transition of another input, an           BVL-WORLD-006: nothing is committed
        undeclared event kind, a NO_ACTION
        outside its frozen meaning, or a
        post-state no executed action or
        stated event accounts for

A plan without a contract states no progression the kernel reads: its World's
transition is committed as stated (a transition-1, or a transition-2 from a
World that states one), and a NO_ACTION decision is refused.

The state chain (T3-001) already admits no state change outside a committed
transition, so a transition is the only place an environment can progress.
``world_progression_problems`` is the verifier's recomputation.

State serialization and replay (T3-005, ``bvl-world-replay-1``).  Under a
contract the World is handed a state decoded from the pre-state's own
serialization - a fresh copy per invocation, never the caller's object - and
the committed transition is read back from its evidence bytes, so only a
deserialized post-state reaches the next step.  Before anything is committed an
independent instance of the World replays the same serialized inputs:

    the World is not copyable to an             BVL-WORLD-009: nothing is committed
        independent instance, or that
        instance states another transition

The registered instance is still applied exactly once; the replica is applied
once more, to bytes.  ``world_replay_problems`` is what a verifier without the
World's code recomputes (one transition per serialized input); with the code,
``kernel/world_replay.py`` replays every committed transition.

Stochastic World seed binding (T3-006, ``bvl-world-rng-1``).  The contract
freezes the World's RNG policy and every apply of a contracted World - the
registered instance's and each replay's - goes through
``world_rng.apply_under_policy``: a SEEDED World is handed the declared RNG of
the intent's seed (never the seed), a DETERMINISTIC one the seed, and hidden
plugin RNG is held shut for the call.  The committed evidence is
``world-transition-evidence-4``: it states ``rng`` - the policy the transition
was made under and, when SEEDED, the algorithm and how much was drawn - and the
transition's identity binds it.

    a World whose entry point is not its        BVL-WORLD-013: nothing is committed
        policy's, a transition that reached
        hidden plugin RNG, a DETERMINISTIC
        transition another seed changes, or
        a replay that drew differently

``world_rng_problems`` is the verifier's recomputation: every intent's seed is
the plan's seed tree's world seed of its episode, round and transition, every
transition evidences the contract's RNG policy, and no two DETERMINISTIC
transitions of the same serialized pre-state and input differ, whatever their
seeds.

Crash, resume and custody (T3-007).  A transition is *confirmed* by its one
WORLD_APPLIED.  A refusal of this boundary to continue is a
``WorldCustodyRefusedError``: nothing is applied and nothing is written - not
even an EPISODE_FAILED, the refusal is no result of the World - so the run
stays interrupted and refuses the same way again.

    the outcome of an intended apply is not     BVL-WORLD-011: OUTCOME_UNKNOWN, a torn
        established                             journal tail, or evidence that
                                                contradicts its intent
    continuing would confirm a second           BVL-WORLD-012: the step holds another
        transition                              intent or outcome, an intent holds two
                                                outcomes, or it is another run's

Under a contract a World is a function of its durable intent (T3-005, T3-006),
which is what a resume may rely on and what it must therefore check:

    INTENT_RECORDED       the interrupted apply left nothing durable; the intent
                          is applied under every check of an uninterrupted apply
    TRANSITION_PERSISTED  the evidence an interrupted run left is confirmed
                          before it is committed: it must state a transition of
                          the contract, and an independent instance of the
                          World, handed the intent's serialized inputs under
                          the frozen RNG policy, must make exactly it.  The
                          registered instance is not applied.  Evidence the
                          World does not make is BVL-WORLD-011: it is never
                          committed, and never replaced by a second apply

Without a contract the K0 boundary keeps its meaning: persisted evidence is
committed as found.  ``world_custody_problems`` is the verifier's
recomputation: every intent is confirmed exactly once, by a WORLD_APPLIED of
its own run, episode, step and round; no transition or evidence member is
confirmed twice; and every intent consumes one custody-accepted call of its
episode, accepted before it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import Digest, sha256_bytes
from boomvalley_lab.core.errors import BoomvalleyError, EvidenceError, ExecutionError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.journal.log import held_members
from boomvalley_lab.kernel.authorization import require_run_authorization_v2
from boomvalley_lab.kernel.containment import WORLD, invoke_pure, plugin_window
from boomvalley_lab.kernel.custody2 import CustodyLedgerV2, verify_call_v2
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentRefV2,
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.identity import (
    CallIdentity,
    CustodyEntryIdentity,
    DecisionArtifactIdentity,
    EpisodeIdentity,
    StepIdentity,
    WorldTransitionIdentity,
    WorldTransitionIntentIdentity,
)
from boomvalley_lab.kernel.journal2 import (
    CUSTODY_ACCEPTED,
    DECISION_RECORDED,
    EPISODE_OPENED,
    ROUND_COMPLETED,
    WORLD_APPLIED,
    WORLD_INTENT_RECORDED,
    WORLD_OUTCOME_UNKNOWN,
    Journal2,
)
from boomvalley_lab.kernel.request_store import RequestStoreV2
from boomvalley_lab.kernel.seed import SeedDerivation
from boomvalley_lab.kernel.world import (
    ACTION_INPUT,
    ACTION_SCHEMA_INVALID,
    ADMISSIBILITY_VERDICTS,
    DUPLICATE_APPLY_RISK,
    HIDDEN_WORLD_STATE,
    NO_ACTION_INPUT,
    NO_ACTION_UNDECLARED,
    POST_STATE_INVALID,
    RESUME_TRANSITION_UNCERTAIN,
    RNG_EVIDENCE,
    RNG_POLICY_INVALID,
    STATE_EVIDENCE_SCHEMA_V1,
    TRANSITION_FAILED,
    TRANSITION_INTENT_MISSING,
    TRANSITION_SCHEMA,
    TRANSITION_SCHEMA_V2,
    UNDECLARED,
    WORLD_IDENTITY_MISMATCH,
    PureWorld,
    WorldContractV1,
    WorldRngPolicyV1,
    WorldTransition,
    deserialize_state,
    replay_problems,
    serialize_state,
    state_evidence_document,
    state_identity,
)
from boomvalley_lab.kernel.world_rng import apply_under_policy, entry_point_problems
from boomvalley_lab.store.artifacts import ArtifactStore

INTENT_SCHEMA = "boomvalley-lab-world-intent-2"
TRANSITION_EVIDENCE_SCHEMA = "boomvalley-lab-world-transition-evidence-2"
STATE_EVIDENCE_SCHEMA = STATE_EVIDENCE_SCHEMA_V1
# The same documents under a World contract: versioned state identities
# (T3-001) and, in the intent, the exact action handed to the World (T3-002)
# and whether that input is an action or NO_ACTION (T3-004).  intent-3 (no
# action) and intent-4 (no action_input) are not read: nothing relabels them.
INTENT_SCHEMA_V5 = "boomvalley-lab-world-intent-5"
_INTENT_FIELDS_V5 = frozenset(
    {
        "schema", "episode", "step", "round", "node", "decision", "source_custody",
        "world", "seed", "pre_state", "state_schema", "action", "action_input",
    }
)
# evidence-4 (T3-006) also states the RNG context the transition was made under;
# evidence-3 (no RNG context) is not read: nothing relabels it
TRANSITION_EVIDENCE_SCHEMA_V4 = "boomvalley-lab-world-transition-evidence-4"
_EVIDENCE_FIELDS = frozenset(
    {"schema", "identity", "intent", "world", "decision", "seed", "transition"}
)
_VERSIONED_FIELDS = frozenset({"state_schema", "pre_state", "post_state", "rng"})
_WORLD_EVENTS = (WORLD_INTENT_RECORDED, WORLD_OUTCOME_UNKNOWN, WORLD_APPLIED)
_SCOPE = ("run", "episode", "step", "round")
_TRANSITION_FIELDS = (
    "requested_action",
    "admissibility_verdict",
    "admissible_action",
    "executed_action",
    "pre_state",
    "post_state",
    "outcome",
)
# a bvl-world-transition-2 (T3-004) also states its progression
_PROGRESSION_FIELDS = ("action_input", "executed", "exogenous_events")


class WorldTransitionStateV2(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    INTENT_RECORDED = "INTENT_RECORDED"
    TRANSITION_PERSISTED = "TRANSITION_PERSISTED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    APPLIED = "APPLIED"
    INCONSISTENT = "INCONSISTENT"


class WorldResumeDecisionV2(StrEnum):
    EXECUTE = "EXECUTE"
    RECOVER = "RECOVER"
    SKIP = "SKIP"
    ABORT = "ABORT"
    OPERATOR_DECISION = "OPERATOR_DECISION"


WORLD_POLICY_V2: dict[WorldTransitionStateV2, WorldResumeDecisionV2] = {
    WorldTransitionStateV2.NOT_STARTED: WorldResumeDecisionV2.EXECUTE,
    WorldTransitionStateV2.INTENT_RECORDED: WorldResumeDecisionV2.EXECUTE,
    WorldTransitionStateV2.TRANSITION_PERSISTED: WorldResumeDecisionV2.RECOVER,
    WorldTransitionStateV2.OUTCOME_UNKNOWN: WorldResumeDecisionV2.OPERATOR_DECISION,
    WorldTransitionStateV2.APPLIED: WorldResumeDecisionV2.SKIP,
    WorldTransitionStateV2.INCONSISTENT: WorldResumeDecisionV2.ABORT,
}


class WorldCustodyRefusedError(ExecutionError):
    """The World boundary may not continue a transition (T3-007); nothing is written.

    An integrity or operator outcome, not a result of the World: the engine
    does not journal it as EPISODE_FAILED and the run stays interrupted.
    """

    def __init__(self, code: str, detail: str) -> None:
        if code not in (RESUME_TRANSITION_UNCERTAIN, DUPLICATE_APPLY_RISK):
            raise ValueError(f"unknown World custody reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


@dataclass(frozen=True)
class AppliedWorldTransitionV2:
    identity: WorldTransitionIdentity
    transition: WorldTransition
    transition_evidence: EvidenceDocumentRefV2
    state_evidence: EvidenceDocumentRefV2


@dataclass(frozen=True)
class WorldIntentV2:
    """One engine-authorized intent to apply one World action at one step."""

    identity: WorldTransitionIntentIdentity
    payload: Mapping[str, Any]

    @classmethod
    def derive(
        cls,
        *,
        episode: EpisodeIdentity,
        step: StepIdentity,
        round_index: int,
        node_id: str,
        decision: DecisionArtifactIdentity,
        source_custody: Mapping[str, Any],
        world_plugin_identity: str,
        seed: int,
        pre_state: Mapping[str, Any],
        state_schema: str | None = None,
        action: Mapping[str, Any] | None = None,
        no_action: bool = False,
    ) -> WorldIntentV2:
        if no_action and (state_schema is None or action):
            raise ValueError(
                f"a NO_ACTION input is a {INTENT_SCHEMA_V5} intent carrying the empty action"
            )
        if (state_schema is None) != (action is None):
            raise ValueError(
                f"exactly a {INTENT_SCHEMA_V5} intent (one stating a state_schema) carries "
                "the action handed to its World"
            )
        payload = {
            "schema": INTENT_SCHEMA if state_schema is None else INTENT_SCHEMA_V5,
            "episode": episode.document(),
            "step": step.document(),
            "round": round_index,
            "node": node_id,
            "decision": decision.document(),
            "source_custody": dict(source_custody),
            "world": world_plugin_identity,
            "seed": seed,
            "pre_state": state_identity(pre_state, state_schema).document(),
        }
        if state_schema is not None:
            payload["state_schema"] = state_schema
            payload["action"] = _decoded(action)
            payload["action_input"] = NO_ACTION_INPUT if no_action else ACTION_INPUT
        return cls(WorldTransitionIntentIdentity.of_payload(payload), payload)

    @classmethod
    def from_document(cls, document: Any) -> WorldIntentV2:
        if not isinstance(document, Mapping) or set(document) != {"identity", "payload"}:
            raise EvidenceError("world intent carries exactly identity and payload")
        payload = document["payload"]
        schema = payload.get("schema") if isinstance(payload, Mapping) else None
        if schema not in (INTENT_SCHEMA, INTENT_SCHEMA_V5):
            raise EvidenceError(
                f"world intent payload schema is {INTENT_SCHEMA!r} or {INTENT_SCHEMA_V5!r}"
            )
        versioned = isinstance(payload.get("state_schema"), str) and bool(payload["state_schema"])
        if ("state_schema" in payload) != (schema == INTENT_SCHEMA_V5) or (
            schema == INTENT_SCHEMA_V5 and not versioned
        ):
            raise EvidenceError(
                f"exactly a {INTENT_SCHEMA_V5} world intent states its state_schema"
            )
        if schema == INTENT_SCHEMA_V5 and (
            set(payload) != _INTENT_FIELDS_V5 or not isinstance(payload["action"], Mapping)
        ):
            raise EvidenceError(
                f"a {INTENT_SCHEMA_V5} world intent carries exactly the action handed to its "
                "World"
            )
        if schema == INTENT_SCHEMA_V5 and (
            payload["action_input"] not in (ACTION_INPUT, NO_ACTION_INPUT)
            or (payload["action_input"] == NO_ACTION_INPUT and payload["action"])
        ):
            raise EvidenceError(
                f"a {INTENT_SCHEMA_V5} world intent states its input: an action, or "
                "NO_ACTION and no action"
            )
        if schema == INTENT_SCHEMA and "action" in payload:
            raise EvidenceError(f"a {INTENT_SCHEMA} world intent carries no action")
        identity = WorldTransitionIntentIdentity.of_payload(dict(payload))
        if identity.document() != document["identity"]:
            raise EvidenceError("world intent payload does not re-derive its identity")
        return cls(identity, dict(payload))

    @property
    def state_schema(self) -> str | None:
        """The schema version this intent's states are identified under, if any."""

        return self.payload.get("state_schema")

    @property
    def evidences_action(self) -> bool:
        return "action" in self.payload

    @property
    def no_action(self) -> bool:
        """Whether this intent hands its World NO_ACTION instead of an action (T3-004)."""

        return self.payload.get("action_input") == NO_ACTION_INPUT

    def handed_action(self) -> dict[str, Any] | None:
        """A fresh copy of the evidenced action, decoded from its canonical bytes.

        This - not a caller's object - is what the World is handed, so the
        action applied is the action the durable intent states (T3-002).  A
        NO_ACTION input hands ``None``: it is not the empty action (T3-004).
        """

        return None if self.no_action else _decoded(self.payload["action"])

    def document(self) -> dict[str, Any]:
        return {"identity": self.identity.document(), "payload": dict(self.payload)}


@dataclass(frozen=True)
class ClassifiedWorldTransitionV2:
    intent: str
    state: WorldTransitionStateV2
    decision: WorldResumeDecisionV2
    reason: str = ""
    # why a transition that may not continue may not (T3-007): BVL-WORLD-011 / -012
    code: str = ""


def _decoded(value: Mapping[str, Any]) -> dict[str, Any]:
    """*value* as its canonical serialization decodes: no shared mutable parts."""

    return load_bytes(canonical_bytes(dict(value)))


def _stated(value: Any) -> Any:
    """The document of what a World returned; a transition that has none is refused."""

    if not isinstance(value, WorldTransition):
        return value
    try:
        return value.document()
    except (TypeError, ValueError) as error:
        raise ExecutionError(
            f"{TRANSITION_FAILED}: World.apply returned a transition whose actions, states "
            f"or outcome are not objects: {error}",
            code=TRANSITION_FAILED,
        ) from error


def _same(left: Any, right: Any) -> bool:
    try:
        return canonical_bytes(left) == canonical_bytes(right)
    except (BoomvalleyError, TypeError, ValueError):
        return False


def _transition_identity(document: Mapping[str, Any]) -> WorldTransitionIdentity:
    payload = {
        "decision": document["decision"],
        "world_plugin_identity": document["world"],
        "seed_identity": f"seed:{document['seed']}",
        "transition": document["transition"],
    }
    if "state_schema" in document:
        payload["state_schema"] = document["state_schema"]
    if "rng" in document:
        payload["rng"] = document["rng"]
    return WorldTransitionIdentity.of_payload(payload)


def _transition_from(document: Mapping[str, Any]) -> WorldTransition:
    body = document["transition"]
    schema = body.get("schema") if isinstance(body, Mapping) else None
    if schema not in (TRANSITION_SCHEMA, TRANSITION_SCHEMA_V2):
        raise EvidenceError(
            f"world transition evidence does not carry {TRANSITION_SCHEMA} or "
            f"{TRANSITION_SCHEMA_V2}"
        )
    fields = _TRANSITION_FIELDS + (_PROGRESSION_FIELDS if schema == TRANSITION_SCHEMA_V2 else ())
    if set(body) != {"schema", *fields}:
        raise EvidenceError("world transition body has unexpected fields")
    stated = {name: body[name] for name in fields}
    if schema == TRANSITION_SCHEMA_V2:
        if not isinstance(stated["executed"], bool) or not isinstance(
            stated["exogenous_events"], list
        ):
            raise EvidenceError(
                f"a {TRANSITION_SCHEMA_V2} states executed (a boolean) and its exogenous events"
            )
        stated["exogenous_events"] = tuple(stated["exogenous_events"])
    return WorldTransition(**stated)


def _load_member(path: Path) -> Any:
    data = path.read_bytes()
    if sha256_bytes(data).hex != path.stem:
        raise EvidenceError(f"{path.parent.name}/{path.name} contradicts its content address")
    try:
        document = load_bytes(data)
    except MalformedJSON as error:
        raise EvidenceError(f"{path.parent.name}/{path.name} is unreadable: {error}") from error
    if canonical_bytes(document) != data:
        raise EvidenceError(f"{path.parent.name}/{path.name} is not canonical")
    return document


def transition_evidence_by_intent(run_directory: Path) -> dict[str, list[tuple[str, dict]]]:
    """Every persisted world_transition document, grouped by the intent it binds.

    Any unreadable member refuses the whole store (EvidenceError): a corrupted
    outcome can never be attributed, so it can never be ignored.
    """

    root = Path(run_directory) / "evidence-v2" / "world_transition"
    grouped: dict[str, list[tuple[str, dict]]] = {}
    if not root.is_dir():
        return grouped

    def load(path: Path) -> tuple[str, dict]:
        document = _load_member(path)
        intent = document.get("intent") if isinstance(document, Mapping) else None
        if not isinstance(intent, Mapping) or not isinstance(intent.get("digest"), str):
            raise EvidenceError(f"world_transition/{path.name} binds no world intent")
        return intent["digest"], document

    for name, (digest, document) in held_members(root, load):
        grouped.setdefault(digest, []).append((name, dict(document)))
    return grouped


def _verify_transition_evidence(document: Mapping[str, Any], intent: WorldIntentV2) -> None:
    payload = intent.payload
    state_schema = intent.state_schema
    schema = TRANSITION_EVIDENCE_SCHEMA if state_schema is None else TRANSITION_EVIDENCE_SCHEMA_V4
    if document.get("schema") != schema:
        raise EvidenceError(f"world transition evidence is not {schema}")
    expected = _EVIDENCE_FIELDS if state_schema is None else _EVIDENCE_FIELDS | _VERSIONED_FIELDS
    if set(document) != expected:
        raise EvidenceError("world transition evidence has unexpected fields")
    if document["intent"] != intent.identity.document():
        raise EvidenceError("world transition evidence binds another intent")
    for field in ("world", "decision", "seed"):
        if document[field] != payload[field]:
            raise EvidenceError(f"world transition evidence {field} contradicts its intent")
    transition = _transition_from(document)
    if state_schema is not None and document["transition"]["schema"] != TRANSITION_SCHEMA_V2:
        raise EvidenceError(f"a transition under a World contract is a {TRANSITION_SCHEMA_V2}")
    if transition.pre_state_identity(state_schema).document() != payload["pre_state"]:
        raise EvidenceError("world transition evidence pre-state is not the intended pre-state")
    if state_schema is not None and transition.action_input != payload["action_input"]:
        raise EvidenceError(
            f"{TRANSITION_FAILED}: world transition evidence is of another input than its "
            "intent handed to the World"
        )
    if intent.evidences_action and not _same(
        dict(transition.requested_action), payload["action"]
    ):
        raise EvidenceError(
            f"{TRANSITION_FAILED}: world transition evidence requested action is not the "
            "action its intent handed to the World"
        )
    if state_schema is not None and (
        not isinstance(document["rng"], Mapping) or document["rng"].get("schema") != RNG_EVIDENCE
    ):
        raise EvidenceError(
            f"{RNG_POLICY_INVALID}: world transition evidence states no {RNG_EVIDENCE}"
        )
    if state_schema is not None and (
        document["state_schema"] != state_schema
        or document["pre_state"] != payload["pre_state"]
        or document["post_state"] != transition.post_state_identity(state_schema).document()
    ):
        raise EvidenceError(
            "world transition evidence state identities are not its states under "
            f"{state_schema}"
        )
    if _transition_identity(document).document() != document["identity"]:
        raise EvidenceError("world transition evidence does not re-derive its identity")


def _world_event(record: Mapping[str, Any]) -> bool | None:
    return True if record["event"] in _WORLD_EVENTS else None


def classify_world_transition_v2(
    *,
    run_directory: Path,
    intent: WorldIntentV2,
    journal: Journal2,
) -> ClassifiedWorldTransitionV2:
    run_directory = Path(run_directory)
    intent_key = str(intent.identity)
    intent_doc = intent.identity.document()
    step_doc = intent.payload["step"]
    step_key = f"{step_doc['kind']}:{step_doc['digest']}"

    def result(
        state: WorldTransitionStateV2, reason: str = "", code: str = ""
    ) -> ClassifiedWorldTransitionV2:
        return ClassifiedWorldTransitionV2(intent_key, state, WORLD_POLICY_V2[state], reason, code)

    def inconsistent(
        reason: str, code: str = RESUME_TRANSITION_UNCERTAIN
    ) -> ClassifiedWorldTransitionV2:
        return result(WorldTransitionStateV2.INCONSISTENT, reason, code)

    try:
        # every World event of the run: only these belong to, or rival, an intent
        records = journal.selected("world", _world_event, True)
        evidence = transition_evidence_by_intent(run_directory).get(intent_doc["digest"], [])
    except (EvidenceError, OSError) as error:
        return inconsistent(str(error))

    def belongs(record: Mapping[str, Any]) -> bool:
        if record["event"] == WORLD_INTENT_RECORDED:
            held = record["transition_intent"]
            return isinstance(held, Mapping) and held.get("identity") == intent_doc
        if record["event"] == WORLD_OUTCOME_UNKNOWN:
            return record["transition"] == intent_doc
        if record["event"] == WORLD_APPLIED:
            return record["transition_intent"] == intent_doc
        return False

    events = [record for record in records if belongs(record)]
    rivals = [
        record
        for record in records
        if record["event"] in _WORLD_EVENTS and not belongs(record) and record["step"] == step_key
    ]
    if rivals:
        return inconsistent(
            f"step already holds a different World intent/outcome "
            f"(sequence {rivals[0]['sequence']}); a second transition is never applied",
            DUPLICATE_APPLY_RISK,
        )
    kinds = [record["event"] for record in events]

    if not events:
        if evidence:
            return inconsistent("world transition evidence exists without a durable intent")
        return result(WorldTransitionStateV2.NOT_STARTED)

    opened = events[0]
    if opened["event"] != WORLD_INTENT_RECORDED:
        return inconsistent(f"world history does not open with {WORLD_INTENT_RECORDED}: {kinds}")
    for record in events[1:]:
        for field in _SCOPE:
            if record[field] != opened[field]:
                return inconsistent(
                    f"{record['event']} at sequence {record['sequence']} {field} "
                    "contradicts the world intent"
                )
    try:
        recorded = WorldIntentV2.from_document(opened["transition_intent"])
    except EvidenceError as error:
        return inconsistent(str(error))
    if recorded != intent:
        return inconsistent("recorded world intent payload is not the derived intent")
    if opened["decision"] != intent.payload["decision"] or opened["step"] != step_key:
        return inconsistent("world intent event step/decision contradicts its payload")
    try:
        verify_source_custody(run_directory, intent.payload["source_custody"], journal)
    except (EvidenceError, OSError, ValueError) as error:
        return inconsistent(f"source call custody does not re-verify: {error}")
    if len(evidence) > 1:
        return inconsistent(
            f"{len(evidence)} world transition evidence members bind one intent",
            DUPLICATE_APPLY_RISK,
        )
    try:
        for _, document in evidence:
            _verify_transition_evidence(document, intent)
    except (EvidenceError, KeyError, TypeError) as error:
        return inconsistent(str(error))

    if kinds == [WORLD_INTENT_RECORDED]:
        if evidence:
            return result(
                WorldTransitionStateV2.TRANSITION_PERSISTED,
                "transition evidence is durable but WORLD_APPLIED is not journaled",
            )
        return result(
            WorldTransitionStateV2.INTENT_RECORDED,
            "intent is durable but no outcome evidence exists; nothing was committed",
        )

    if kinds == [WORLD_INTENT_RECORDED, WORLD_OUTCOME_UNKNOWN]:
        if evidence:
            return inconsistent("world outcome is unknown but transition evidence exists")
        return result(
            WorldTransitionStateV2.OUTCOME_UNKNOWN,
            "World apply did not return a transition; only an operator may decide",
            RESUME_TRANSITION_UNCERTAIN,
        )

    if kinds == [WORLD_INTENT_RECORDED, WORLD_APPLIED]:
        if not evidence:
            return inconsistent("WORLD_APPLIED has no transition evidence")
        try:
            _verify_applied(run_directory, events[-1], evidence[0][1])
        except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
            return inconsistent(str(error))
        return result(WorldTransitionStateV2.APPLIED)

    return inconsistent(
        f"unsupported or contradictory world event history: {kinds}",
        # more than one intent or outcome event: a transition is confirmed at most once
        DUPLICATE_APPLY_RISK if len(kinds) > 2 else RESUME_TRANSITION_UNCERTAIN,
    )


def verify_source_custody(
    run_directory: Path, source_custody: Any, journal: Journal2
) -> CallIdentity:
    """Re-verify the custody-entry-2 a World intent consumed; returns its call."""

    run_directory = Path(run_directory)
    matches = CustodyLedgerV2(run_directory).of_identity(source_custody)
    if len(matches) != 1:
        raise EvidenceError(f"{len(matches)} custody-v2 entries match the intent's source custody")
    kind, _, digest = str(matches[0]["call"]).partition(":")
    if kind != CallIdentity.KIND:
        raise EvidenceError("source custody entry does not name a call")
    call = CallIdentity(Digest.parse(digest))
    verify_call_v2(
        run_directory=run_directory,
        call=call,
        journal=journal,
        requests=RequestStoreV2(run_directory),
        artifacts=ArtifactStore(run_directory),
    )
    return call


def _verify_applied(
    run_directory: Path,
    applied: Mapping[str, Any],
    transition_document: Mapping[str, Any],
) -> AppliedWorldTransitionV2:
    documents = EvidenceDocumentStoreV2(run_directory)
    held = applied["evidence"]
    if not isinstance(held, Mapping) or set(held) != {"transition", "state"}:
        raise EvidenceError("WORLD_APPLIED evidence carries exactly transition and state")
    transition_ref = evidence_ref_from_document(held["transition"], "world_transition")
    state_ref = evidence_ref_from_document(held["state"], "world_state")
    if documents.read(transition_ref) != transition_document:
        raise EvidenceError("WORLD_APPLIED transition evidence is not the intent's evidence")
    if applied["transition"] != transition_document["identity"]:
        raise EvidenceError("WORLD_APPLIED transition identity contradicts its evidence")
    transition = _transition_from(transition_document)
    state_schema = transition_document.get("state_schema")
    if applied["post_state"] != transition.post_state_identity(state_schema).document():
        raise EvidenceError("WORLD_APPLIED post-state contradicts the transition evidence")
    if documents.read(state_ref) != state_evidence_document(transition.post_state, state_schema):
        raise EvidenceError("WORLD_APPLIED state evidence is not the transition post-state")
    return AppliedWorldTransitionV2(
        _transition_identity(transition_document), transition, transition_ref, state_ref
    )


@dataclass(frozen=True)
class WorldReconciliationV2:
    """Run-level reconciliation of World intents against their outcome evidence.

    ``applied`` intents re-verify end to end.  ``pending`` intents have no
    commit yet (intent-only, persisted-unrecorded or unknown outcome).
    ``problems`` are contradictions that no resume or package may skip past.
    """

    applied: tuple[str, ...]
    pending: tuple[tuple[str, str], ...]
    problems: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.pending and not self.problems


def reconcile_world_v2(run_directory: Path) -> WorldReconciliationV2:
    """Classify every journaled World intent and bind every World evidence member."""

    run_directory = Path(run_directory)
    journal = Journal2(run_directory)
    try:
        records = journal.read()
        evidence = transition_evidence_by_intent(run_directory)
    except (EvidenceError, OSError) as error:
        return WorldReconciliationV2((), (), (str(error),))

    applied: list[str] = []
    pending: list[tuple[str, str]] = []
    problems: list[str] = []
    intents: dict[str, WorldIntentV2] = {}
    for record in records:
        if record["event"] != WORLD_INTENT_RECORDED:
            continue
        try:
            intent = WorldIntentV2.from_document(record["transition_intent"])
        except EvidenceError as error:
            problems.append(f"sequence {record['sequence']}: {error}")
            continue
        intents.setdefault(intent.identity.document()["digest"], intent)

    known = {intent.identity.document()["digest"] for intent in intents.values()}
    for record in records:
        if record["event"] == WORLD_OUTCOME_UNKNOWN:
            bound = record["transition"]
        elif record["event"] == WORLD_APPLIED:
            bound = record["transition_intent"]
        else:
            continue
        if not isinstance(bound, Mapping) or bound.get("digest") not in known:
            problems.append(f"{record['event']} at sequence {record['sequence']} has no intent")

    expected_states: set[str] = set()
    # The initial state of a plan under a World contract (T3-001) is bound by
    # its plan: the member is durable before the episode that opens on it.
    try:
        for path in sorted((run_directory / "evidence-v2" / "plan").glob("*.json")):
            plan = _load_member(path)["plan"]
            if "world" in plan:
                ref = WorldContractV1.from_document(plan["world"]).state_schema.ref
                data = canonical_bytes(state_evidence_document(plan["initial_world_state"], ref))
                expected_states.add(f"{sha256_bytes(data).hex}.json")
    except (BoomvalleyError, OSError, KeyError, TypeError) as error:
        problems.append(f"plan evidence does not state its World contract: {error}")
    for intent in intents.values():
        classified = classify_world_transition_v2(
            run_directory=run_directory, intent=intent, journal=journal
        )
        if classified.state is WorldTransitionStateV2.INCONSISTENT:
            problems.append(f"{classified.code}: {classified.intent}: {classified.reason}")
            continue
        if classified.state is WorldTransitionStateV2.APPLIED:
            applied.append(classified.intent)
        else:
            pending.append((classified.intent, classified.state.value))
        for _, document in evidence.get(intent.identity.document()["digest"], []):
            post_state = document["transition"]["post_state"]
            data = canonical_bytes(
                state_evidence_document(post_state, document.get("state_schema"))
            )
            expected_states.add(f"{sha256_bytes(data).hex}.json")

    for digest in sorted(set(evidence) - known):
        problems.append(f"world transition evidence binds unjournaled intent {digest}")

    state_root = run_directory / "evidence-v2" / "world_state"
    if state_root.is_dir():
        for path in sorted(state_root.glob("*.json")):
            if path.name not in expected_states:
                problems.append(f"world_state/{path.name} is bound by no World transition")

    return WorldReconciliationV2(tuple(applied), tuple(pending), tuple(problems))


WORLD_STATE_CHECK = "world_states_versioned_and_chained"


def world_state_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why a run's World states are not explicit and versioned under its plan (T3-001).

    Under a plan-8 World contract: every episode opens on evidence of the
    plan's initial state under the contract's schema version; every intent is
    the contract's World on the state the episode is then in (the initial
    state, or the last committed post-state); every committed pre- and
    post-state is a state of the schema; every round closes on the current
    state.  Under any other plan no document may claim a state schema.
    """

    run_directory = Path(run_directory)
    contract = (
        WorldContractV1.from_document(plan_document["world"])
        if "world" in plan_document
        else None
    )
    ref = None if contract is None else contract.state_schema.ref
    initial = plan_document["initial_world_state"]
    documents = EvidenceDocumentStoreV2(run_directory)
    evidence = transition_evidence_by_intent(run_directory)
    problems: list[str] = []
    current: dict[str, Any] = {}
    for record in records:
        where = f"journal-2 #{record['sequence']} {record['event']}"
        if record["event"] == EPISODE_OPENED:
            opened = record.get("initial_state")
            if contract is None:
                if opened is not None:
                    problems.append(f"{where} names an initial state; the plan has no World "
                                    "contract")
                continue
            expected = state_identity(initial, ref).document()
            if (
                not isinstance(opened, Mapping)
                or set(opened) != {"identity", "evidence"}
                or opened["identity"] != expected
            ):
                problems.append(f"{where} does not open on the plan's initial {ref} state")
                continue
            member = documents.read(evidence_ref_from_document(opened["evidence"], "world_state"))
            if member != state_evidence_document(initial, ref):
                problems.append(f"{where} initial state evidence is not the plan's initial state")
            current[record["episode"]] = expected
        elif record["event"] == WORLD_INTENT_RECORDED:
            intent = WorldIntentV2.from_document(record["transition_intent"])
            if intent.state_schema != ref:
                problems.append(
                    f"{where} identifies its states under {intent.state_schema}; the plan's "
                    f"World contract is {ref}"
                )
                continue
            if contract is None:
                continue
            if intent.payload["world"] != contract.plugin:
                problems.append(f"{where} intends World {intent.payload['world']!r}, not the "
                                f"plan's {contract.plugin!r}")
            if intent.payload["pre_state"] != current.get(record["episode"]):
                problems.append(f"{where} pre-state is not the state its episode was in")
        elif record["event"] == WORLD_APPLIED and contract is not None:
            held = evidence.get(record["transition_intent"]["digest"], [])
            for _, document in held:
                body = document["transition"]
                for role in ("pre_state", "post_state"):
                    problems.extend(
                        f"{where} {role} is not a {ref} state: {problem}"
                        for problem in contract.state_schema.problems(body[role])
                    )
            current[record["episode"]] = record["post_state"]
        elif record["event"] == ROUND_COMPLETED and contract is not None:
            if record["post_state"] != current.get(record["episode"]):
                problems.append(f"{where} does not close on the episode's current World state")
    return problems


WORLD_ACTION_CHECK = "world_action_evidenced_before_apply"


def _decision_members(run_directory: Path) -> dict[str, dict]:
    """Every ``decision`` evidence member by its identity digest."""

    root = Path(run_directory) / "evidence-v2" / "decision"
    found: dict[str, dict] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        document = _load_member(path)
        held = document.get("identity") if isinstance(document, Mapping) else None
        if isinstance(held, Mapping) and isinstance(held.get("digest"), str):
            found[held["digest"]] = dict(document)
    return found


def decided_action(
    records: list[dict], decision: Mapping[str, Any], scope: Mapping[str, Any]
) -> Mapping[str, Any]:
    """The requested action of the one committed decision *decision* names.

    *scope* (``episode``, ``round`` and optionally ``before``, a journal
    sequence) is where the decision must have been committed.  Raises
    EvidenceError when no such single DECISION_RECORDED exists.
    """

    held = [
        record
        for record in records
        if record["event"] == DECISION_RECORDED
        and isinstance(record["decision"], Mapping)
        and record["decision"].get("identity") == decision
    ]
    if len(held) != 1:
        raise EvidenceError(f"{len(held)} DECISION_RECORDED events commit the intended decision")
    (record,) = held
    if record["episode"] != scope["episode"] or record["round"] != scope["round"]:
        raise EvidenceError("the intended decision was committed in another episode or round")
    if "before" in scope and record["sequence"] >= scope["before"]:
        raise EvidenceError("the intended decision was committed after its World intent")
    action = record["decision"].get("requested_action")
    if not isinstance(action, Mapping):
        raise EvidenceError("the intended decision commits no requested action")
    return action


def decided_no_action(records: list[dict], decision: Mapping[str, Any]) -> bool:
    """Whether the committed decision *decision* names is a NO_ACTION decision."""

    return any(
        record["event"] == DECISION_RECORDED
        and isinstance(record["decision"], Mapping)
        and record["decision"].get("identity") == decision
        and record["decision"].get("outcome") == NO_ACTION_INPUT
        for record in records
    )


def world_action_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why the exact action handed to a World is not evidenced before apply (T3-002).

    Under a plan-8 World contract, for every World intent: it is an intent-4
    whose ``action`` is the requested action of the decision it names - the
    DECISION_RECORDED committed earlier in the same episode and round and that
    decision's own evidence member, whose identity re-derives; every
    WORLD_APPLIED follows the durable intent it binds (BVL-WORLD-005) and its
    transition evidence reports exactly the handed action (BVL-WORLD-006).
    Under any other plan no intent may claim to carry its action.
    """

    contracted = "world" in plan_document
    problems: list[str] = []
    try:
        decisions = _decision_members(run_directory)
        evidence = transition_evidence_by_intent(run_directory)
    except (EvidenceError, OSError) as error:
        return [str(error)]
    intended: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for record in records:
        where = f"journal-2 #{record['sequence']} {record['event']}"
        if record["event"] == WORLD_INTENT_RECORDED:
            try:
                intent = WorldIntentV2.from_document(record["transition_intent"])
            except EvidenceError as error:
                problems.append(f"{where}: {error}")
                continue
            if intent.evidences_action != contracted:
                problems.append(
                    f"{where} is a {intent.payload['schema']}; "
                    + (
                        f"under the plan's World contract an intent is {INTENT_SCHEMA_V5}"
                        if contracted
                        else "the plan has no World contract"
                    )
                )
                continue
            if not contracted:
                continue
            payload = intent.payload
            intended[intent.identity.document()["digest"]] = (record["sequence"], payload)
            if payload["decision"] != record["decision"]:
                problems.append(f"{where} names another decision than its intent")
                continue
            try:
                decided = decided_action(
                    records,
                    payload["decision"],
                    {
                        "episode": record["episode"],
                        "round": record["round"],
                        "before": record["sequence"],
                    },
                )
            except EvidenceError as error:
                problems.append(f"{where}: {error}")
                continue
            if not _same(dict(decided), payload["action"]):
                problems.append(
                    f"{where} hands the World an action that is not its decision's "
                    "requested action"
                )
            if intent.no_action != decided_no_action(records, payload["decision"]):
                problems.append(
                    f"{where} input {payload['action_input']} is not its decision's outcome"
                )
            member = decisions.get(payload["decision"].get("digest"))
            body = (
                None
                if member is None
                else {k: v for k, v in member.items() if k not in ("schema", "identity")}
            )
            if (
                body is None
                or DecisionArtifactIdentity.of_payload(body).document() != payload["decision"]
                or not _same(body.get("requested_action"), payload["action"])
                or (body.get("outcome") == NO_ACTION_INPUT) != intent.no_action
            ):
                problems.append(
                    f"{where} hands the World an action that is not its Decision "
                    "Artifact's requested action"
                )
        elif record["event"] == WORLD_APPLIED and contracted:
            bound = record["transition_intent"]
            digest = bound.get("digest") if isinstance(bound, Mapping) else None
            if digest not in intended or intended[digest][0] >= record["sequence"]:
                problems.append(
                    f"{TRANSITION_INTENT_MISSING}: {where} is preceded by no durable World "
                    "intent"
                )
                continue
            for _, document in evidence.get(digest, []):
                body = document.get("transition")
                if not isinstance(body, Mapping) or not _same(
                    body.get("requested_action"), intended[digest][1]["action"]
                ):
                    problems.append(
                        f"{TRANSITION_FAILED}: {where} transition is not of the action its "
                        "intent handed to the World"
                    )
    return problems


WORLD_ADMISSIBILITY_CHECK = "world_admissibility_preserved"


def world_admissibility_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why a run's requested/admissible/executed actions are not preserved (T3-003).

    Under a plan-8 World contract, for every committed transition: the
    requested action is an action of the contract's action schema
    (BVL-WORLD-004) and the transition states one verdict of the contract's
    vocabulary that its admissible and executed actions - each read from the
    evidence as the World stated it - do not contradict (BVL-WORLD-006).  A
    plan without a contract states no admissibility the kernel reads.
    """

    if "world" not in plan_document:
        return []
    contract = WorldContractV1.from_document(plan_document["world"])
    try:
        evidence = transition_evidence_by_intent(run_directory)
    except (EvidenceError, OSError) as error:
        return [str(error)]
    problems: list[str] = []
    for record in records:
        if record["event"] != WORLD_APPLIED:
            continue
        where = f"journal-2 #{record['sequence']} {record['event']}"
        bound = record["transition_intent"]
        digest = bound.get("digest") if isinstance(bound, Mapping) else None
        for _, document in evidence.get(digest, []):
            body = document.get("transition")
            if not isinstance(body, Mapping):
                problems.append(f"{TRANSITION_FAILED}: {where} evidences no transition")
                continue
            if body.get("action_input") == NO_ACTION_INPUT:
                continue  # no action was requested or assessed (T3-004's check)
            problems.extend(
                f"{ACTION_SCHEMA_INVALID}: {where} requested action is not a "
                f"{contract.action_schema.ref} action: {problem}"
                for problem in contract.action_problems(body.get("requested_action"))
            )
            problems.extend(
                f"{TRANSITION_FAILED}: {where} {problem}"
                for problem in contract.admissibility_problems(body)
            )
    return problems


def admissibility_counts(run_directory: Path, records: list[dict]) -> dict[str, int]:
    """Committed transitions per stated verdict (the attestation's summary).

    Only what ``world_admissibility_problems`` accepts is counted: a transition
    stating no verdict of the vocabulary is that check's refusal, not a count.
    """

    counts = {verdict: 0 for verdict in ADMISSIBILITY_VERDICTS}
    try:
        evidence = transition_evidence_by_intent(run_directory)
    except (EvidenceError, OSError):
        return counts
    for record in records:
        bound = record.get("transition_intent")
        if record["event"] != WORLD_APPLIED or not isinstance(bound, Mapping):
            continue
        for _, document in evidence.get(bound.get("digest"), []):
            body = document.get("transition")
            verdict = body.get("admissibility_verdict") if isinstance(body, Mapping) else None
            if isinstance(verdict, str) and verdict in counts:
                counts[verdict] += 1
    return counts


WORLD_PROGRESSION_CHECK = "world_progression_explicit"


def _committed_bodies(
    run_directory: Path, records: list[dict]
) -> list[tuple[str, Mapping[str, Any], Any]]:
    """(where, intent payload, transition body) of every committed transition."""

    evidence = transition_evidence_by_intent(run_directory)
    payloads = {
        record["transition_intent"]["identity"]["digest"]: record["transition_intent"]["payload"]
        for record in records
        if record["event"] == WORLD_INTENT_RECORDED
    }
    found = []
    for record in records:
        bound = record.get("transition_intent")
        if record["event"] != WORLD_APPLIED or not isinstance(bound, Mapping):
            continue
        where = f"journal-2 #{record['sequence']} {record['event']}"
        for _, document in evidence.get(bound.get("digest"), []):
            found.append((where, payloads.get(bound.get("digest"), {}), document.get("transition")))
    return found


def world_progression_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why a null action or an environment progression is a hidden mutation (T3-004).

    Under a plan-8 World contract, every committed transition is a
    ``bvl-world-transition-2`` of the input its intent states - NO_ACTION
    exactly when the intended decision is a NO_ACTION decision, within the
    meaning the contract froze - and states whether an action was executed and
    every exogenous event, each of a declared kind; a post-state that is not
    the pre-state follows from an executed action or a stated event
    (BVL-WORLD-006).  A plan without a contract states no progression the
    kernel reads: what its World states of one is kept as stated, unchecked.
    """

    if "world" not in plan_document:
        return []
    try:
        bodies = _committed_bodies(run_directory, records)
    except (EvidenceError, OSError, KeyError, TypeError) as error:
        return [str(error)]
    problems: list[str] = []
    contract = WorldContractV1.from_document(plan_document["world"])
    for where, payload, body in bodies:
        if not isinstance(body, Mapping):
            problems.append(f"{TRANSITION_FAILED}: {where} evidences no transition")
            continue
        found = contract.progression_problems(body)
        if not found and body["action_input"] != payload.get("action_input"):
            found = ["the transition is of another input than its intent handed to the World"]
        if (
            body.get("action_input") == NO_ACTION_INPUT
            and contract.progression.no_action == UNDECLARED
        ):
            problems.append(f"{NO_ACTION_UNDECLARED}: {where} applies a NO_ACTION input")
        problems.extend(f"{TRANSITION_FAILED}: {where} {problem}" for problem in found)
    return problems


def progression_counts(run_directory: Path, records: list[dict]) -> dict[str, Any]:
    """What the committed transitions state of their progression (the attestation's summary)."""

    counts: dict[str, Any] = {
        "no_action_transitions": 0,
        "unexecuted_transitions": 0,
        "exogenous_events": {},
    }
    try:
        bodies = _committed_bodies(run_directory, records)
    except (EvidenceError, OSError, KeyError, TypeError):
        return counts
    for _, _, body in bodies:
        if not isinstance(body, Mapping):
            continue
        counts["no_action_transitions"] += body.get("action_input") == NO_ACTION_INPUT
        counts["unexecuted_transitions"] += body.get("executed") is False
        for event in body.get("exogenous_events") or []:
            kind = event.get("event") if isinstance(event, Mapping) else None
            if isinstance(kind, str):
                counts["exogenous_events"][kind] = counts["exogenous_events"].get(kind, 0) + 1
    counts["exogenous_events"] = dict(sorted(counts["exogenous_events"].items()))
    return counts


WORLD_REPLAY_CHECK = "world_transitions_replayable"


def replay_key(world: Any, payload: Mapping[str, Any], body: Mapping[str, Any]) -> bytes:
    """The serialized inputs one committed transition is a function of."""

    return canonical_bytes(
        {
            "world": world,
            "state_schema": payload.get("state_schema"),
            "seed": payload.get("seed"),
            "action_input": payload.get("action_input"),
            "action": payload.get("action"),
            "pre_state": dict(body["pre_state"]),
        }
    )


def world_replay_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why a run's committed transitions are not replayable from its evidence (T3-005).

    Under a plan-8 World contract every committed pre- and post-state is its
    own serialization read back (the object ``deserialize_state`` gives of
    ``serialize_state``), and the contract's World is one function of its
    serialized inputs: no two committed transitions of the same World, schema,
    seed, input and serialized pre-state differ (BVL-WORLD-009).  This is what
    the evidence alone decides; replaying the World's code is
    ``kernel/world_replay.py``.  A plan without a contract states no
    serialization the kernel reads.
    """

    if "world" not in plan_document:
        return []
    try:
        bodies = _committed_bodies(run_directory, records)
        world = WorldContractV1.from_document(plan_document["world"]).plugin
    except (BoomvalleyError, OSError, KeyError, TypeError) as error:
        return [str(error)]
    problems: list[str] = []
    seen: dict[bytes, tuple[str, bytes]] = {}
    for where, payload, body in bodies:
        if not isinstance(body, Mapping):
            problems.append(f"{HIDDEN_WORLD_STATE}: {where} evidences no transition")
            continue
        try:
            for role in ("pre_state", "post_state"):
                if deserialize_state(serialize_state(body[role])) != body[role]:
                    raise EvidenceError(f"{role} is not its own serialization read back")
            key, stated = replay_key(world, payload, body), canonical_bytes(dict(body))
        except (BoomvalleyError, KeyError, TypeError, ValueError) as error:
            problems.append(f"{HIDDEN_WORLD_STATE}: {where} is not replayable: {error}")
            continue
        first = seen.setdefault(key, (where, stated))
        if first[1] != stated:
            problems.append(
                f"{HIDDEN_WORLD_STATE}: {where} and {first[0]} are transitions of the same "
                "serialized pre-state, input and seed, and differ"
            )
    return problems


WORLD_RNG_CHECK = "world_rng_bound"


def world_seed(tree: SeedDerivation, record: Mapping[str, Any], payload: Mapping[str, Any]) -> int:
    """The K0 world seed of the transition a WORLD_INTENT_RECORDED *record* intends."""

    return tree.world(
        record["episode"], round_index=payload["round"], transition_id=payload["node"]
    )


def _committed_evidence(
    run_directory: Path, records: list[dict]
) -> list[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    """(where, intent payload, evidence document) of every committed transition."""

    evidence = transition_evidence_by_intent(run_directory)
    payloads = {
        record["transition_intent"]["identity"]["digest"]: record["transition_intent"]["payload"]
        for record in records
        if record["event"] == WORLD_INTENT_RECORDED
    }
    found = []
    for record in records:
        bound = record.get("transition_intent")
        if record["event"] != WORLD_APPLIED or not isinstance(bound, Mapping):
            continue
        where = f"journal-2 #{record['sequence']} {record['event']}"
        for _, document in evidence.get(bound.get("digest"), []):
            found.append((where, payloads.get(bound.get("digest"), {}), document))
    return found


def world_rng_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why a run's World randomness is not its plan's declared RNG (T3-006).

    Under a plan-8 World contract: every intent's seed is the world seed the
    plan's K0 seed tree derives for its episode, round and transition; every
    committed transition evidences the RNG policy the contract froze - nothing
    drawn under DETERMINISTIC, the declared algorithm and its draw counts under
    SEEDED; and no two DETERMINISTIC transitions of the same World, schema,
    input and serialized pre-state differ, whatever their seeds
    (BVL-WORLD-013).  This is what the evidence alone decides; that the World's
    code reaches no hidden RNG is the boundary's refusal and
    ``kernel/world_replay.py``.  A plan without a contract states no RNG policy
    the kernel reads.
    """

    if "world" not in plan_document:
        return []
    try:
        contract = WorldContractV1.from_document(plan_document["world"])
        tree = SeedDerivation.from_document(plan_document["seed"])
        committed = _committed_evidence(run_directory, records)
    except (BoomvalleyError, OSError, KeyError, TypeError, ValueError) as error:
        return [str(error)]
    problems: list[str] = []
    for record in records:
        if record["event"] != WORLD_INTENT_RECORDED:
            continue
        where = f"journal-2 #{record['sequence']} {record['event']}"
        try:
            payload = record["transition_intent"]["payload"]
            bound = payload["seed"] == world_seed(tree, record, payload)
        except (KeyError, TypeError, ValueError) as error:
            problems.append(f"{RNG_POLICY_INVALID}: {where} binds no world seed: {error}")
            continue
        if not bound:
            problems.append(
                f"{RNG_POLICY_INVALID}: {where} seed is not the world seed the plan's seed "
                "tree derives for its episode, round and transition"
            )
    seen: dict[bytes, tuple[str, bytes]] = {}
    for where, payload, document in committed:
        problems.extend(
            f"{RNG_POLICY_INVALID}: {where} {problem}"
            for problem in contract.rng.evidence_problems(document.get("rng"))
        )
        body = document.get("transition")
        if contract.rng.seeded or not isinstance(body, Mapping):
            continue
        try:
            key = replay_key(contract.plugin, {**payload, "seed": None}, body)
            stated = canonical_bytes(dict(body))
        except (BoomvalleyError, KeyError, TypeError, ValueError) as error:
            problems.append(f"{RNG_POLICY_INVALID}: {where} is not comparable: {error}")
            continue
        first = seen.setdefault(key, (where, stated))
        if first[1] != stated:
            problems.append(
                f"{RNG_POLICY_INVALID}: {where} and {first[0]} are DETERMINISTIC transitions "
                "of the same serialized pre-state and input, and differ"
            )
    return problems


def rng_counts(run_directory: Path, records: list[dict]) -> dict[str, int]:
    """What the committed transitions drew from the declared RNG (the attestation's summary)."""

    counts = {"stochastic_transitions": 0, "draws": 0, "bits": 0}
    try:
        committed = _committed_evidence(run_directory, records)
    except (EvidenceError, OSError, KeyError, TypeError):
        return counts
    for _, _, document in committed:
        used = document.get("rng")
        draws = used.get("draws") if isinstance(used, Mapping) else None
        bits = used.get("bits") if isinstance(used, Mapping) else None
        if isinstance(draws, int) and isinstance(bits, int) and draws > 0:
            counts["stochastic_transitions"] += 1
            counts["draws"] += draws
            counts["bits"] += bits
    return counts


WORLD_CUSTODY_CHECK = "world_transitions_confirmed_once"


def _world_custody(
    run_directory: Path, records: list[dict]
) -> tuple[dict[str, int], list[str]]:
    counts = {"intents": 0, "confirmed": 0, "unconfirmed": 0, "duplicate_confirmed": 0}
    problems: list[str] = []
    ledger = [
        (CustodyEntryIdentity.of_payload(entry).document(), entry)
        for entry in CustodyLedgerV2(Path(run_directory)).read()
    ]
    accepted = {
        record["call"]: record for record in records if record["event"] == CUSTODY_ACCEPTED
    }
    intents: dict[str, dict] = {}
    by_step: set[tuple[Any, Any]] = set()
    for record in records:
        if record["event"] != WORLD_INTENT_RECORDED:
            continue
        where = f"journal-2 #{record['sequence']} {record['event']}"
        counts["intents"] += 1
        held = record["transition_intent"]
        digest = held["identity"]["digest"]
        step = (record["episode"], record["step"])
        if digest in intents or step in by_step:
            problems.append(
                f"{DUPLICATE_APPLY_RISK}: {where} is a second World intent of its step"
            )
            continue
        intents[digest] = record
        by_step.add(step)
        # custody: the intent consumes one custody-accepted call of its episode
        consumed = held["payload"].get("source_custody")
        entries = [entry for identity, entry in ledger if identity == consumed]
        source = accepted.get(entries[0].get("call")) if len(entries) == 1 else None
        if (
            source is None
            or source["sequence"] >= record["sequence"]
            or source["episode"] != record["episode"]
            or source["run"] != record["run"]
        ):
            problems.append(
                f"{RESUME_TRANSITION_UNCERTAIN}: {where} consumes no single call "
                "custody-accepted before it in its run and episode"
            )
    confirmed: dict[str, int] = {}
    transitions: set[str] = set()
    members: set[str] = set()
    for record in records:
        where = f"journal-2 #{record['sequence']} {record['event']}"
        if record["event"] == WORLD_OUTCOME_UNKNOWN:
            problems.append(
                f"{RESUME_TRANSITION_UNCERTAIN}: {where}: the outcome of an intended apply is "
                "unknown"
            )
        if record["event"] != WORLD_APPLIED:
            continue
        bound = record["transition_intent"]
        digest = bound.get("digest") if isinstance(bound, Mapping) else None
        opened = intents.get(digest)
        if opened is None or opened["sequence"] >= record["sequence"]:
            problems.append(
                f"{RESUME_TRANSITION_UNCERTAIN}: {where} confirms no World intent recorded "
                "before it"
            )
            continue
        transition = canonical_bytes(record["transition"]).decode("utf-8")
        member = canonical_bytes(record["evidence"]).decode("utf-8")
        if digest in confirmed or transition in transitions or member in members:
            counts["duplicate_confirmed"] += 1
            problems.append(
                f"{DUPLICATE_APPLY_RISK}: {where} confirms a transition "
                + (
                    f"journal-2 #{confirmed[digest]} already confirmed"
                    if digest in confirmed
                    else "another WORLD_APPLIED already confirmed"
                )
            )
            continue
        confirmed[digest] = record["sequence"]
        transitions.add(transition)
        members.add(member)
        if any(record[field] != opened[field] for field in _SCOPE):
            problems.append(
                f"{RESUME_TRANSITION_UNCERTAIN}: {where} is not of the run, episode, step and "
                "round of the intent it confirms"
            )
    counts["confirmed"] = len(confirmed)
    for digest, opened in intents.items():
        if digest not in confirmed:
            counts["unconfirmed"] += 1
            problems.append(
                f"{RESUME_TRANSITION_UNCERTAIN}: journal-2 #{opened['sequence']} "
                f"{opened['event']} is confirmed by no WORLD_APPLIED"
            )
    return counts, problems


def world_custody_problems(
    run_directory: Path, records: list[dict], plan_document: Mapping[str, Any]
) -> list[str]:
    """Why a run's World transitions are not each confirmed exactly once (T3-007).

    Under a plan's World contract: a step holds one World intent; every intent
    consumes one call custody-accepted before it in its run and episode, and
    is confirmed by exactly one WORLD_APPLIED of its own run, episode, step
    and round; no transition identity and no evidence member is confirmed
    twice (BVL-WORLD-012); and no intended apply is left unknown or
    unconfirmed (BVL-WORLD-011).  Read from the journal and the custody ledger
    alone.  A plan without a contract states no custody the kernel reads here.
    """

    if "world" not in plan_document:
        return []
    try:
        return _world_custody(run_directory, records)[1]
    except (BoomvalleyError, OSError, KeyError, TypeError, ValueError, AttributeError) as error:
        return [f"{RESUME_TRANSITION_UNCERTAIN}: World custody is not readable: {error}"]


def custody_counts(run_directory: Path, records: list[dict]) -> dict[str, int]:
    """How the run's World intents were confirmed (the attestation's summary)."""

    return _world_custody(run_directory, records)[0]


def replica_of(world: PureWorld) -> PureWorld:
    """An independent instance of *world* (BVL-WORLD-009 when it has none)."""

    try:
        return copy.deepcopy(world)
    except Exception as error:  # noqa: BLE001 - whatever a plugin's copy raises
        raise ExecutionError(
            f"{HIDDEN_WORLD_STATE}: World {getattr(world, 'plugin_identity', None)!r} has no "
            f"independent instance to replay its transition on: {type(error).__name__}: {error}",
            code=HIDDEN_WORLD_STATE,
        ) from error


def require_replayed(
    world: PureWorld,
    stated: Mapping[str, Any],
    apply: Callable[[PureWorld], Any],
    *,
    reseeded: Callable[[PureWorld], Any] | None = None,
) -> None:
    """Replay one transition on an independent instance; refuse another transition.

    *apply* hands a World the same serialized inputs the stated transition was
    of (fresh decodes).  A World whose instance carries what its transition
    depends on - or cannot be copied at all - commits nothing (BVL-WORLD-009).

    *reseeded* is the replay of a DETERMINISTIC World (T3-006): the same inputs
    under another seed.  A transition only the bound seed reproduces is
    randomness the contract does not declare (BVL-WORLD-013).
    """

    replica = replica_of(world)
    with plugin_window(WORLD, str(world.plugin_identity)):
        replayed = (reseeded or apply)(replica)
    differing = replay_problems(stated, _stated(replayed))
    if differing and reseeded is not None:
        # which input the transition is not a function of: its seed, or something hidden
        again = replica_of(world)
        with plugin_window(WORLD, str(world.plugin_identity)):
            same_seed = apply(again)
        if not replay_problems(stated, _stated(same_seed)):
            raise ExecutionError(
                f"{RNG_POLICY_INVALID}: World {world.plugin_identity!r} declares a "
                "DETERMINISTIC rng policy, but its transition depends on its seed: replayed "
                f"under another seed it did not reproduce it ({'; '.join(differing)})",
                code=RNG_POLICY_INVALID,
            )
    if differing:
        raise ExecutionError(
            f"{HIDDEN_WORLD_STATE}: World {world.plugin_identity!r} is not a function of its "
            "serialized pre-state, input and seed: an independent instance did not "
            f"reproduce its transition ({'; '.join(differing)})",
            code=HIDDEN_WORLD_STATE,
        )


class DurableWorldTransitionV2:
    def __init__(
        self,
        run_directory: Path,
        *,
        run_id: str,
        journal: Journal2 | None = None,
        documents: EvidenceDocumentStoreV2 | None = None,
    ) -> None:
        if not run_id:
            raise ValueError("run_id must be non-empty")
        self.run_directory = Path(run_directory)
        self.run_id = run_id
        self.journal = journal if journal is not None else Journal2(self.run_directory)
        self.documents = (
            documents if documents is not None else EvidenceDocumentStoreV2(self.run_directory)
        )

    def source_custody(self, call: CallIdentity) -> dict[str, Any]:
        """The custody-entry-2 identity of the call a decision derives from.

        A World never applies a decision whose actor-call evidence is not
        custody-accepted and re-verifiable end to end.
        """

        try:
            identity = verify_call_v2(
                run_directory=self.run_directory,
                call=call,
                journal=self.journal,
                requests=RequestStoreV2(self.run_directory),
                artifacts=ArtifactStore(self.run_directory),
            )
        except (EvidenceError, OSError, ValueError) as error:
            raise ExecutionError(
                f"World refuses a decision whose source call {call} is not custody-accepted: "
                f"{error}"
            ) from error
        return identity.document()

    def apply(
        self,
        *,
        episode: EpisodeIdentity,
        step: StepIdentity,
        round_index: int,
        node_id: str,
        decision: DecisionArtifactIdentity,
        requested_action: Mapping[str, Any],
        source_call: CallIdentity,
        world: PureWorld,
        seed: int,
        pre_state: Mapping[str, Any],
        contract: WorldContractV1 | None = None,
        no_action: bool = False,
    ) -> AppliedWorldTransitionV2:
        if no_action and contract is None:
            # P07 §13.4: never a skip-World shortcut, and K0 gives it no meaning
            raise ExecutionError(
                "a NO_ACTION decision has no World transition semantics without a World "
                "contract"
            )
        declared = getattr(world, "rng", None)
        if contract is None and isinstance(declared, WorldRngPolicyV1) and declared.seeded:
            # T3-006: K0 binds no RNG; a stochastic World is never run as a seeded guess
            raise ExecutionError(
                f"{RNG_POLICY_INVALID}: World {world.plugin_identity!r} declares a SEEDED "
                "rng policy; it is applied only under a World contract that freezes it",
                code=RNG_POLICY_INVALID,
            )
        if self.journal.torn_tail():
            # T3-007: an outcome record may be the torn one
            raise WorldCustodyRefusedError(
                RESUME_TRANSITION_UNCERTAIN,
                "journal-2 has a torn tail; refusing to append World evidence",
            )
        require_run_authorization_v2(self.run_directory, run_id=self.run_id, journal=self.journal)
        state_schema = None if contract is None else contract.state_schema.ref
        if contract is not None:
            if world.plugin_identity != contract.plugin:
                raise ExecutionError(
                    f"{WORLD_IDENTITY_MISMATCH}: World {world.plugin_identity!r} is not the "
                    f"plan's World {contract.plugin!r}",
                    code=WORLD_IDENTITY_MISMATCH,
                )
            # T3-006: nothing is intended for a World that is not of the frozen RNG
            # policy, or whose entry point is another policy's
            stated = declared if isinstance(declared, WorldRngPolicyV1) else WorldRngPolicyV1()
            unfit = entry_point_problems(world, contract.rng)
            if stated != contract.rng:
                unfit = [f"it declares the RNG policy {stated.policy}, the plan froze "
                         f"{contract.rng.policy}"]
            if unfit:
                raise ExecutionError(
                    f"{RNG_POLICY_INVALID}: World {world.plugin_identity!r}: "
                    f"{'; '.join(unfit)}",
                    code=RNG_POLICY_INVALID,
                )
            unfit = contract.state_schema.problems(pre_state)
            if unfit:  # nothing is intended on a state outside the frozen schema
                raise ExecutionError(
                    f"World pre-state is not a {state_schema} state: {'; '.join(unfit)}"
                )
            # T3-002: nothing is intended for an action that is not the committed
            # decision's (P15 acceptance 4)
            try:
                decided = decided_action(
                    self.journal.of_event(DECISION_RECORDED),
                    decision.document(),
                    {"episode": str(episode), "round": round_index},
                )
            except EvidenceError as error:
                raise ExecutionError(f"World refuses decision {decision}: {error}") from error
            if not _same(dict(decided), dict(requested_action)):
                raise ExecutionError(
                    "World refuses an action that is not the requested action of decision "
                    f"{decision}"
                )
            # T3-004: NO_ACTION is intended exactly for a NO_ACTION decision, and
            # only under a contract that froze what it means to this World
            if no_action != decided_no_action(
                self.journal.of_event(DECISION_RECORDED), decision.document()
            ):
                raise ExecutionError(
                    f"World refuses decision {decision}: its outcome is not the "
                    f"{NO_ACTION_INPUT if no_action else ACTION_INPUT} input it is handed as"
                )
            if no_action and contract.progression.no_action == UNDECLARED:
                raise ExecutionError(
                    f"{NO_ACTION_UNDECLARED}: decision {decision} is NO_ACTION; the contract "
                    f"of World {contract.plugin!r} declares no NO_ACTION meaning",
                    code=NO_ACTION_UNDECLARED,
                )
            # T3-003: nothing is intended for an action the World does not accept;
            # whether an accepted action is admissible is the World's verdict
            unfit = [] if no_action else contract.action_problems(requested_action)
            if unfit:
                raise ExecutionError(
                    f"{ACTION_SCHEMA_INVALID}: the requested action of decision {decision} is "
                    f"not a {contract.action_schema.ref} action of World "
                    f"{contract.plugin!r}: {'; '.join(unfit)}",
                    code=ACTION_SCHEMA_INVALID,
                )
        intent = WorldIntentV2.derive(
            episode=episode,
            step=step,
            round_index=round_index,
            node_id=node_id,
            decision=decision,
            source_custody=self.source_custody(source_call),
            world_plugin_identity=world.plugin_identity,
            seed=seed,
            pre_state=pre_state,
            state_schema=state_schema,
            action=None if contract is None else requested_action,
            no_action=no_action,
        )
        classified = classify_world_transition_v2(
            run_directory=self.run_directory, intent=intent, journal=self.journal
        )
        scope = {
            "run": self.run_id,
            "episode": str(episode),
            "step": str(step),
            "round": round_index,
        }
        state = classified.state
        if state is WorldTransitionStateV2.APPLIED:
            return self._recorded(intent)
        if state is WorldTransitionStateV2.TRANSITION_PERSISTED:
            self._require_run(intent)
            if contract is None:  # K0: persisted evidence is committed as found
                return self._commit(intent, self._persisted(intent), scope)
        elif state is WorldTransitionStateV2.NOT_STARTED:
            self.journal.append_event(
                WORLD_INTENT_RECORDED,
                **scope,
                transition_intent=intent.document(),
                decision=decision.document(),
            )
        elif state is WorldTransitionStateV2.INTENT_RECORDED:
            self._require_run(intent)
        else:
            raise WorldCustodyRefusedError(
                classified.code,
                f"world intent {intent.identity} is {state.value}; resume decision "
                f"{classified.decision.value}; the executor never re-applies a World"
                + (f" ({classified.reason})" if classified.reason else ""),
            )

        # The intent is durable.  Under a contract the World is handed what the
        # intent evidences - its action decoded from the intent's own canonical
        # bytes, a fresh copy per invocation - never the caller's object.
        def handed() -> Mapping[str, Any] | None:
            return intent.handed_action() if intent.evidences_action else requested_action

        # T3-005: and the state it is handed is the pre-state's serialization
        # read back, so what a World does is a function of serialized state
        serialized = None if contract is None else serialize_state(pre_state)

        def handed_state() -> Mapping[str, Any]:
            return pre_state if serialized is None else deserialize_state(serialized)

        # T3-006: under a contract the World is applied under its frozen RNG policy -
        # the declared RNG of the intent's seed or none - with hidden RNG held shut
        drawn: list[dict[str, Any]] = []

        def applied(plugin: PureWorld, probe: str | None = None) -> Any:
            if contract is None:
                return plugin.apply(handed_state(), handed(), seed=intent.payload["seed"])
            made, used = apply_under_policy(
                plugin, contract.rng, handed_state(), handed(),
                seed=intent.payload["seed"], probe=probe,
            )
            drawn.append(used)
            return made

        def reseeded(plugin: PureWorld) -> Any:
            return applied(plugin, "engine")

        if state is WorldTransitionStateV2.TRANSITION_PERSISTED:
            # T3-007: evidence an interrupted run left is committed only as the
            # transition the contract's World makes of this intent
            document = self._persisted(intent)
            self._confirm(
                world, contract, intent, document, applied,
                None if contract.rng.seeded else reseeded, drawn,
            )
            return self._commit(intent, _decoded(document), scope)

        try:
            transition = invoke_pure(WORLD, world, applied, _stated)
            if not isinstance(transition, WorldTransition):
                raise ExecutionError("World.apply did not return a WorldTransition")
            stated = _stated(transition)
            if canonical_bytes(dict(transition.pre_state)) != canonical_bytes(dict(pre_state)):
                raise ExecutionError("World.apply transition pre-state is not its input state")
            if intent.evidences_action and not _same(
                dict(transition.requested_action), intent.payload["action"]
            ):
                raise ExecutionError(
                    f"{TRANSITION_FAILED}: World {world.plugin_identity!r} reports a "
                    "transition of another requested action than the one it was handed",
                    code=TRANSITION_FAILED,
                )
            # T3-004: a null action or an environment progression is committed only
            # as what the contract's frozen progression lets the transition state
            hidden = [] if contract is None else contract.progression_problems(stated)
            if not hidden and contract is not None and (
                stated["action_input"] != intent.payload["action_input"]
            ):
                hidden = ["it reports another input than the one it was handed"]
            if hidden:
                raise ExecutionError(
                    f"{TRANSITION_FAILED}: World {world.plugin_identity!r} did not state "
                    f"the progression of its transition: {'; '.join(hidden)}",
                    code=TRANSITION_FAILED,
                )
            unstated = [] if contract is None else contract.admissibility_problems(stated)
            if unstated:  # T3-003: the three actions are committed only as one verdict
                raise ExecutionError(
                    f"{TRANSITION_FAILED}: World {world.plugin_identity!r} did not state "
                    f"the admissibility of its transition: {'; '.join(unstated)}",
                    code=TRANSITION_FAILED,
                )
            unfit = [] if contract is None else contract.state_schema.problems(
                transition.post_state
            )
            if unfit:
                raise ExecutionError(
                    f"{POST_STATE_INVALID}: World {world.plugin_identity!r} post-state is not "
                    f"a {state_schema} state: {'; '.join(unfit)}",
                    code=POST_STATE_INVALID,
                )
            if contract is not None:
                require_replayed(
                    world, stated, applied,
                    reseeded=None if contract.rng.seeded else reseeded,
                )
                if any(used != drawn[0] for used in drawn):
                    raise ExecutionError(
                        f"{RNG_POLICY_INVALID}: World {world.plugin_identity!r} did not draw "
                        "the same from the declared RNG when its transition was replayed",
                        code=RNG_POLICY_INVALID,
                    )
        except Exception as error:
            self.journal.append_event(
                WORLD_OUTCOME_UNKNOWN,
                **scope,
                transition=intent.identity.document(),
                reason=type(error).__name__,
            )
            raise

        identity = transition.identity(
            decision=decision,
            world_plugin_identity=world.plugin_identity,
            seed_identity=f"seed:{seed}",
            state_schema=state_schema,
            rng=drawn[0] if contract is not None else None,
        )
        document = {
            "schema": TRANSITION_EVIDENCE_SCHEMA,
            "identity": identity.document(),
            "intent": intent.identity.document(),
            "world": world.plugin_identity,
            "decision": decision.document(),
            "seed": seed,
            "transition": transition.document(),
        }
        if state_schema is not None:
            document.update(
                schema=TRANSITION_EVIDENCE_SCHEMA_V4,
                rng=drawn[0],
                state_schema=state_schema,
                pre_state=transition.pre_state_identity(state_schema).document(),
                post_state=transition.post_state_identity(state_schema).document(),
            )
        self.documents.put("world_transition", document)
        # T3-005: what is committed and carried forward is the evidence read back
        return self._commit(intent, document if contract is None else _decoded(document), scope)

    def _require_run(self, intent: WorldIntentV2) -> None:
        opened = next(
            record
            for record in self.journal.of_event(WORLD_INTENT_RECORDED)
            if record["transition_intent"]["identity"] == intent.identity.document()
        )
        if opened["run"] != self.run_id:
            raise WorldCustodyRefusedError(
                DUPLICATE_APPLY_RISK, f"world intent {intent.identity} belongs to another run"
            )

    @staticmethod
    def _confirm(
        world: PureWorld,
        contract: WorldContractV1,
        intent: WorldIntentV2,
        document: Mapping[str, Any],
        applied: Callable[..., Any],
        reseeded: Callable[[PureWorld], Any] | None,
        drawn: list[dict[str, Any]],
    ) -> None:
        """Confirm persisted transition evidence before it is committed (T3-007).

        The evidence already binds *intent* (the classifier re-verified it).
        Here it must also be what an uninterrupted apply would have committed:
        a transition of the contract that an independent instance of the World
        makes of the intent's serialized inputs, drawing what it states.  The
        registered instance is not applied.
        """

        stated = document["transition"]
        unconfirmed = [
            *contract.progression_problems(stated),
            *contract.admissibility_problems(stated),
            *contract.state_schema.problems(stated["post_state"]),
            *contract.rng.evidence_problems(document["rng"]),
        ]
        if not unconfirmed:
            try:
                require_replayed(world, stated, applied, reseeded=reseeded)
            except Exception as error:  # noqa: BLE001 - whatever a plugin raises
                unconfirmed.append(f"{type(error).__name__}: {error}")
        if not unconfirmed and any(used != document["rng"] for used in drawn):
            unconfirmed.append("the World does not draw from the declared RNG what it states")
        if unconfirmed:
            raise WorldCustodyRefusedError(
                RESUME_TRANSITION_UNCERTAIN,
                f"world intent {intent.identity} holds transition evidence World "
                f"{world.plugin_identity!r} does not confirm; it is never committed and the "
                f"World is never applied a second time for it ({'; '.join(unconfirmed)})",
            )

    def _persisted(self, intent: WorldIntentV2) -> dict:
        digest = intent.identity.document()["digest"]
        ((_, document),) = transition_evidence_by_intent(self.run_directory)[digest]
        return document

    def _commit(
        self,
        intent: WorldIntentV2,
        document: Mapping[str, Any],
        scope: Mapping[str, Any],
    ) -> AppliedWorldTransitionV2:
        transition = _transition_from(document)
        state_schema = document.get("state_schema")
        transition_ref = self.documents.put("world_transition", dict(document))
        state_ref = self.documents.put(
            "world_state", state_evidence_document(transition.post_state, state_schema)
        )
        self.journal.append_event(
            WORLD_APPLIED,
            **scope,
            transition_intent=intent.identity.document(),
            transition=document["identity"],
            post_state=transition.post_state_identity(state_schema).document(),
            evidence={"transition": transition_ref.document(), "state": state_ref.document()},
        )
        return AppliedWorldTransitionV2(
            _transition_identity(document), transition, transition_ref, state_ref
        )

    def _recorded(self, intent: WorldIntentV2) -> AppliedWorldTransitionV2:
        applied = next(
            record
            for record in self.journal.of_event(WORLD_APPLIED)
            if record["transition_intent"] == intent.identity.document()
        )
        return _verify_applied(self.run_directory, applied, self._persisted(intent))
