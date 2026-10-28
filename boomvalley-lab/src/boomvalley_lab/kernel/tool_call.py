"""Journaled tool call and its side-effect policy (P17, T5-004).

A tool call reaches outside the product, and a mutating one changes something
there.  This boundary makes one tool intent durable before the tool is called
and decides, from durable evidence only, what may happen after an
interruption.  Ordering is structural:

    require the run's gate-2 authorization (nothing is written or called
    under a refused, missing or unverifiable gate)
    -> hold the contract to the actor's profile and to the registered tool
    -> persist the tool intent (``tool_intent`` evidence)
    -> journal TOOL_INTENT_RECORDED
    -> journal TOOL_CALL_STARTED (attempt n)
    -> tool.call exactly once, under the intent's idempotency key
    -> persist the typed result (``tool_result`` evidence)
    -> journal TOOL_RETURNED

Every prefix of that chain maps to one state, and the state and the
contract's declared side effect (``kernel/tool.py``) to one decision:

    (nothing)                    NOT_STARTED         -> EXECUTE
    intent                       INTENT_RECORDED     -> EXECUTE (no call was
                                                        started)
    ... started [, unknown]      OUTCOME_UNKNOWN     -> by side effect:
          NONE               EXECUTE            a read changed nothing; it is
                                                read again
          IDEMPOTENT_BY_KEY  RECONCILE          the tool is asked, by key,
                                                whether it applied the change
          IRREVERSIBLE       OPERATOR_DECISION  nothing is called
    ... reconciled NOT_APPLIED   NOT_APPLIED_PROVEN  -> EXECUTE (the next
                                                        attempt, same key)
    ... returned, or
    ... reconciled APPLIED       RETURNED            -> SKIP (the recorded
                                                        result, re-verified)
    anything else / tamper       INCONSISTENT        -> ABORT

There is deliberately no RETRY decision.  A mutating tool is called again for
one intent only after a journaled reconciliation proved that the earlier
attempt changed nothing, and then under the same idempotency key, so a call
that was lost in flight and lands late is still applied once.  A call that
raised, or returned something that is not the contract's typed result, has an
unknown outcome like one the process died in: the tool may have changed its
resource before it failed.

The idempotency key is the digest of the intent's identity: step x actor x
request x contract x arguments.  It is derived, never chosen, so two attempts
of one intent carry one key and two intents never share one.

A journal in which a mutating tool was started again while its earlier
attempt was unresolved is INCONSISTENT: evidence of a blind retry is never
continued.  A step calls its tool for one intent; a second intent on a step
is refused before anything is written.

The tool is called inside a containment window of its own (T5-005,
``kernel/containment.py``): ``tool`` for a mutating tool, ``tool_read`` for a
read-only one and for every reconciliation, in which a write is HIDDEN_WRITE.
Only the engine calls a tool: an execute reached from inside a plugin window
is HIDDEN_TOOL_CALL before anything is written, and a violation inside the
call leaves the outcome unknown and is raised as itself.

Classification is read-only.  ``APPLIED``, ``NOT_APPLIED`` and a receipt are
the tool's statements under its contract, not proof about the resource.

What this module does not do: orchestrate.  Which step calls which tool with
which arguments is the engine's: the tool actor call
(``kernel/tool_actor_call.py``, T5-007) reaches this boundary inside the
actor's call chain.  What an operator's decision on an unknown outcome records
is not in this build: such a call is refused on every resume.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.kernel.actors import ActorBindingV1
from boomvalley_lab.kernel.authorization import require_run_authorization_v2
from boomvalley_lab.kernel.containment import (
    HIDDEN_TOOL_CALL,
    TOOL,
    TOOL_READ,
    ContainmentViolationV2,
    active_session,
    plugin_window,
)
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentRefV2,
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.identity import EpisodeIdentity, StepIdentity
from boomvalley_lab.kernel.journal2 import (
    TOOL_CALL_STARTED,
    TOOL_INTENT_RECORDED,
    TOOL_OUTCOME_UNKNOWN,
    TOOL_RECONCILED,
    TOOL_RETURNED,
    Journal2,
)
from boomvalley_lab.kernel.tool import (
    RESULT_TYPES,
    TOOL_CALL_EVIDENCE_MISMATCH,
    TOOL_RECONCILIATION_FAILED,
    TOOL_RESULT_INVALID,
    TOOL_UNSUPPORTED,
    MutationOutcome,
    ToolActorContractV1,
    ToolEffect,
    ToolError,
    ToolMutationIntentV1,
    ToolMutationResultV1,
    ToolReadIntentV1,
    ToolReadResultV1,
    ToolSideEffect,
    require_tool_intent,
    tool_mutation_result,
    tool_read_result,
)
from boomvalley_lab.kernel.tool import TOOL_OUTCOME_UNKNOWN as OUTCOME_UNKNOWN_CODE

INTENT_ROLE = "tool_intent"
RESULT_ROLE = "tool_result"

_TOOL_EVENTS = frozenset(
    {TOOL_INTENT_RECORDED, TOOL_CALL_STARTED, TOOL_OUTCOME_UNKNOWN, TOOL_RETURNED,
     TOOL_RECONCILED}
)
_SCOPE = ("run", "episode", "step", "round")
_MUTATION_ANSWER = frozenset({"outcome", "receipt", "value"})

ToolIntent = ToolReadIntentV1 | ToolMutationIntentV1
ToolResult = ToolReadResultV1 | ToolMutationResultV1


class ToolCallStateV1(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    INTENT_RECORDED = "INTENT_RECORDED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    NOT_APPLIED_PROVEN = "NOT_APPLIED_PROVEN"
    RETURNED = "RETURNED"
    INCONSISTENT = "INCONSISTENT"


class ToolResumeDecisionV1(StrEnum):
    EXECUTE = "EXECUTE"
    RECONCILE = "RECONCILE"
    SKIP = "SKIP"
    OPERATOR_DECISION = "OPERATOR_DECISION"
    ABORT = "ABORT"


#: what an unknown outcome permits, by the contract's declared side effect
UNKNOWN_OUTCOME_POLICY: Mapping[ToolSideEffect, ToolResumeDecisionV1] = MappingProxyType(
    {
        ToolSideEffect.NONE: ToolResumeDecisionV1.EXECUTE,
        ToolSideEffect.IDEMPOTENT_BY_KEY: ToolResumeDecisionV1.RECONCILE,
        ToolSideEffect.IRREVERSIBLE: ToolResumeDecisionV1.OPERATOR_DECISION,
    }
)

_STATE_POLICY: Mapping[ToolCallStateV1, ToolResumeDecisionV1] = MappingProxyType(
    {
        ToolCallStateV1.NOT_STARTED: ToolResumeDecisionV1.EXECUTE,
        ToolCallStateV1.INTENT_RECORDED: ToolResumeDecisionV1.EXECUTE,
        ToolCallStateV1.NOT_APPLIED_PROVEN: ToolResumeDecisionV1.EXECUTE,
        ToolCallStateV1.RETURNED: ToolResumeDecisionV1.SKIP,
        ToolCallStateV1.INCONSISTENT: ToolResumeDecisionV1.ABORT,
    }
)


def resume_decision(state: ToolCallStateV1, side_effect: ToolSideEffect) -> ToolResumeDecisionV1:
    """The one decision of a call in *state* under a declared *side_effect*."""

    if state is ToolCallStateV1.OUTCOME_UNKNOWN:
        return UNKNOWN_OUTCOME_POLICY[side_effect]
    return _STATE_POLICY[state]


def tool_idempotency_key(intent: ToolIntent) -> str:
    """The key every attempt of *intent* is called under: its identity's digest."""

    return str(intent.identity().digest)


@dataclass(frozen=True)
class ClassifiedToolCallV1:
    intent: str
    state: ToolCallStateV1
    decision: ToolResumeDecisionV1
    attempts: int = 0  # the tool calls the journal says were started
    reason: str = ""


@dataclass(frozen=True)
class CompletedToolCallV1:
    """One tool intent and the one result the journal holds for it."""

    intent: ToolIntent
    result: ToolResult
    intent_evidence: EvidenceDocumentRefV2
    result_evidence: EvidenceDocumentRefV2
    attempts: int
    #: CALL (the tool returned it), RECONCILIATION (the tool stated it by key)
    #: or RECORDED (an earlier process journaled it)
    source: str


@dataclass(frozen=True)
class _Inspected:
    classified: ClassifiedToolCallV1
    intent_evidence: EvidenceDocumentRefV2 | None = None
    result: ToolResult | None = None
    result_evidence: EvidenceDocumentRefV2 | None = None


def _inspect(
    *,
    run_directory: Path,
    journal: Journal2,
    contract: ToolActorContractV1,
    step: StepIdentity,
    intent: ToolIntent,
) -> _Inspected:
    identity = intent.identity()
    key, step_key = str(identity), str(step)
    side_effect = contract.side_effect
    store = EvidenceDocumentStoreV2(run_directory)
    attempt = 0

    def result(state: ToolCallStateV1, reason: str = "", **held: Any) -> _Inspected:
        return _Inspected(
            ClassifiedToolCallV1(
                key, state, resume_decision(state, side_effect), attempt, reason
            ),
            **held,
        )

    def inconsistent(reason: str) -> _Inspected:
        return result(ToolCallStateV1.INCONSISTENT, reason)

    try:
        events = journal.of_tool_intent(key)
        rivals = [
            record for record in journal.of_step(step_key)
            if record["event"] in _TOOL_EVENTS and record["tool_intent"] != key
        ]
    except EvidenceError as error:
        return inconsistent(str(error))
    if rivals:
        return inconsistent(
            f"step already journals another tool intent (sequence {rivals[0]['sequence']}); a "
            "step calls its tool for one intent"
        )
    if not events:
        return result(ToolCallStateV1.NOT_STARTED)

    opened = events[0]
    if opened["event"] != TOOL_INTENT_RECORDED:
        return inconsistent(
            f"tool call history does not open with {TOOL_INTENT_RECORDED}: "
            f"{[record['event'] for record in events]}"
        )
    if opened["step"] != step_key:
        return inconsistent("the tool intent is journaled on another step")
    for record in events[1:]:
        for name in _SCOPE:
            if record[name] != opened[name]:
                return inconsistent(
                    f"{record['event']} at sequence {record['sequence']} {name} contradicts "
                    "the tool intent"
                )
    try:
        intent_ref = evidence_ref_from_document(opened["evidence"], INTENT_ROLE)
        if store.read(intent_ref) != intent.document():
            return inconsistent("the journaled tool intent evidence is not this intent")
    except (EvidenceError, OSError, ValueError) as error:
        return inconsistent(f"tool intent evidence does not re-verify: {error}")

    started = False  # an attempt is started and neither returned nor reconciled
    unknown = False
    proven = False  # the last attempt was reconciled NOT_APPLIED
    terminal: dict | None = None
    for record in events[1:]:
        event = record["event"]
        if terminal is not None:
            return inconsistent(
                f"{event} at sequence {record['sequence']} follows the result of the call"
            )
        if event == TOOL_CALL_STARTED:
            if record["attempt"] != attempt + 1:
                return inconsistent(
                    f"attempt {record['attempt']!r} is started after attempt {attempt}"
                )
            if attempt and contract.effect is ToolEffect.MUTATING and not proven:
                return inconsistent(
                    f"a mutating tool was called again (attempt {attempt + 1}) while the "
                    f"outcome of attempt {attempt} was not proven: a blind retry"
                )
            attempt, started, unknown, proven = attempt + 1, True, False, False
            continue
        if event == TOOL_INTENT_RECORDED or not started or record["attempt"] != attempt:
            return inconsistent(
                f"{event} at sequence {record['sequence']} does not continue attempt {attempt}"
            )
        if event == TOOL_OUTCOME_UNKNOWN:
            if unknown:
                return inconsistent(f"attempt {attempt} is journaled unknown twice")
            unknown = True
        elif event == TOOL_RETURNED:
            if unknown:
                return inconsistent(f"attempt {attempt} returned after it was journaled unknown")
            terminal = record
        else:  # TOOL_RECONCILED
            if side_effect is not ToolSideEffect.IDEMPOTENT_BY_KEY:
                return inconsistent(
                    f"a {side_effect.value} tool call is journaled as reconciled; only an "
                    "IDEMPOTENT_BY_KEY tool answers by key"
                )
            recovered = "tool_result" in record
            if recovered != ("evidence" in record) or recovered != (
                record["outcome"] == MutationOutcome.APPLIED.value
            ) or record["outcome"] not in {item.value for item in MutationOutcome}:
                return inconsistent(
                    f"TOOL_RECONCILED at sequence {record['sequence']} is neither NOT_APPLIED "
                    "nor APPLIED with its recovered result"
                )
            if recovered:
                terminal = record
            else:
                started, proven = False, True

    if terminal is not None:
        try:
            result_ref = evidence_ref_from_document(terminal["evidence"], RESULT_ROLE)
            returned = RESULT_TYPES[contract.effect].from_document(store.read(result_ref))
            returned.require(contract)
        except (EvidenceError, ToolError, OSError, ValueError) as error:
            return inconsistent(f"tool result evidence does not re-verify: {error}")
        if dict(returned.intent) != identity.document():
            return inconsistent("the journaled tool result answers another intent")
        if terminal["tool_result"] != str(returned.identity()):
            return inconsistent("the journaled tool result identity is not its evidence's")
        if terminal["event"] == TOOL_RECONCILED and (
            getattr(returned, "outcome", None) is not MutationOutcome.APPLIED
        ):
            return inconsistent("a reconciliation recovered a result that is not APPLIED")
        return result(
            ToolCallStateV1.RETURNED, intent_evidence=intent_ref, result=returned,
            result_evidence=result_ref,
        )
    if not attempt:
        return result(
            ToolCallStateV1.INTENT_RECORDED,
            "intent is durable but no call was started; the tool was not reached",
            intent_evidence=intent_ref,
        )
    if proven:
        return result(
            ToolCallStateV1.NOT_APPLIED_PROVEN,
            f"the tool stated, by key, that attempt {attempt} changed nothing",
            intent_evidence=intent_ref,
        )
    return result(
        ToolCallStateV1.OUTCOME_UNKNOWN,
        f"attempt {attempt} started and its outcome is not proven"
        + (f" ({events[-1]['reason']})" if unknown else ""),
        intent_evidence=intent_ref,
    )


def classify_tool_call(
    *,
    run_directory: Path,
    journal: Journal2,
    contract: ToolActorContractV1,
    step: StepIdentity,
    intent: ToolIntent,
) -> ClassifiedToolCallV1:
    """What the durable evidence proves about *intent*'s call, and what may follow."""

    return _inspect(
        run_directory=run_directory, journal=journal, contract=contract, step=step,
        intent=intent,
    ).classified


class DurableToolCallExecutorV1:
    def __init__(self, run_directory: Path, *, run_id: str) -> None:
        if not run_id:
            raise ValueError("run_id must be non-empty")
        self.run_id = run_id
        self.run_directory = Path(run_directory)
        self.documents = EvidenceDocumentStoreV2(run_directory)
        self.journal = Journal2(run_directory)

    def classify(
        self, *, contract: ToolActorContractV1, step: StepIdentity, intent: ToolIntent
    ) -> ClassifiedToolCallV1:
        return classify_tool_call(
            run_directory=self.run_directory, journal=self.journal, contract=contract,
            step=step, intent=intent,
        )

    def execute(
        self,
        *,
        episode: EpisodeIdentity,
        step: StepIdentity,
        round_index: int,
        contract: ToolActorContractV1,
        binding: ActorBindingV1,
        tool: object,
        intent: ToolIntent,
    ) -> CompletedToolCallV1:
        """Call *tool* once for *intent*, or continue what the journal proves.

        Refusals: an unknown outcome of an IRREVERSIBLE tool (BVL-TOOL-010:
        only an operator may decide), contradictory evidence (BVL-TOOL-011), a
        reconciliation that did not answer (BVL-TOOL-012).  A call that fails
        now is journaled unknown and raises BVL-TOOL-010; one that containment
        refused is journaled unknown and raises that violation.
        """

        session = active_session()
        if session is not None:
            window = session.open_window()
            if window is not None:
                session.refuse(
                    HIDDEN_TOOL_CALL,
                    f"tool {contract.tool!r} was called from {window}: only the engine "
                    "calls a tool actor's tool",
                )
        require_run_authorization_v2(
            self.run_directory, run_id=self.run_id, journal=self.journal
        )
        contract.require_binding(binding)
        contract.require_tool(tool)
        if not callable(getattr(tool, "call", None)):
            raise ToolError(TOOL_UNSUPPORTED, f"tool {contract.tool!r} cannot be called")
        require_tool_intent(contract, binding, intent, step=step)
        if self.journal.torn_tail():
            raise ExecutionError("journal-2 has a torn tail; refusing to append tool evidence")
        scope = {
            "run": self.run_id, "episode": str(episode), "step": str(step),
            "round": round_index, "tool_intent": str(intent.identity()),
        }

        held = self._inspect(contract, step, intent)
        if held.classified.decision is ToolResumeDecisionV1.RECONCILE:
            recovered = self._reconcile(scope, contract, tool, intent, held)
            if recovered is not None:
                return recovered
            held = self._inspect(contract, step, intent)
        classified = held.classified
        if classified.decision is ToolResumeDecisionV1.SKIP:
            assert held.intent_evidence and held.result and held.result_evidence
            return CompletedToolCallV1(
                intent, held.result, held.intent_evidence, held.result_evidence,
                classified.attempts, "RECORDED",
            )
        if classified.decision is ToolResumeDecisionV1.OPERATOR_DECISION:
            raise ToolError(
                OUTCOME_UNKNOWN_CODE,
                f"the outcome of the {contract.side_effect.value} call of {contract.tool!r} "
                f"for {classified.intent} is unknown ({classified.reason}): the tool is not "
                "called again; only an operator may decide",
            )
        if classified.decision is not ToolResumeDecisionV1.EXECUTE:
            raise ToolError(
                TOOL_CALL_EVIDENCE_MISMATCH,
                f"tool call {classified.intent} is {classified.state.value} "
                f"({classified.reason}): nothing is called",
            )

        if classified.state is ToolCallStateV1.NOT_STARTED:
            intent_ref = self.documents.put(INTENT_ROLE, intent.document())
            self.journal.append_event(
                TOOL_INTENT_RECORDED, **scope, evidence=intent_ref.document()
            )
        else:
            assert held.intent_evidence is not None
            intent_ref = held.intent_evidence
        attempt = classified.attempts + 1
        self.journal.append_event(TOOL_CALL_STARTED, **scope, attempt=attempt)
        try:
            with plugin_window(_window(contract), contract.tool):
                answer = tool.call(  # type: ignore[attr-defined]
                    operation=contract.operation,
                    resource=contract.resource,
                    arguments=dict(intent.arguments),
                    idempotency_key=tool_idempotency_key(intent),
                )
            result = _typed_result(contract, intent, answer)
        except Exception as error:
            self.journal.append_event(
                TOOL_OUTCOME_UNKNOWN, **scope, attempt=attempt, reason=type(error).__name__
            )
            if isinstance(error, ContainmentViolationV2):
                raise  # what the tool did outside its contract is not a tool outcome
            raise ToolError(
                OUTCOME_UNKNOWN_CODE,
                f"the call of {contract.tool!r} for {classified.intent} did not return its "
                f"typed result ({type(error).__name__}: {error}); its outcome is unknown",
            ) from error
        result_ref = self.documents.put(RESULT_ROLE, result.document())
        self.journal.append_event(
            TOOL_RETURNED, **scope, attempt=attempt, tool_result=str(result.identity()),
            evidence=result_ref.document(),
        )
        return CompletedToolCallV1(intent, result, intent_ref, result_ref, attempt, "CALL")

    def _inspect(
        self, contract: ToolActorContractV1, step: StepIdentity, intent: ToolIntent
    ) -> _Inspected:
        return _inspect(
            run_directory=self.run_directory, journal=self.journal, contract=contract,
            step=step, intent=intent,
        )

    def _reconcile(
        self,
        scope: Mapping[str, Any],
        contract: ToolActorContractV1,
        tool: object,
        intent: ToolIntent,
        held: _Inspected,
    ) -> CompletedToolCallV1 | None:
        """Ask the tool, by key, what the unresolved attempt did; journal the answer.

        APPLIED recovers the result and the tool is not called.  NOT_APPLIED
        (None) is the proof the next attempt needs.  No answer leaves the
        outcome unknown: nothing is journaled and nothing is called.
        """

        attempt = held.classified.attempts
        try:
            # asking what was applied changes nothing: a read-only window
            with plugin_window(TOOL_READ, contract.tool):
                answer = tool.reconcile(  # type: ignore[attr-defined]
                    operation=contract.operation,
                    resource=contract.resource,
                    idempotency_key=tool_idempotency_key(intent),
                )
            result = _typed_result(contract, intent, answer)
        except ContainmentViolationV2:
            raise
        except Exception as error:
            raise ToolError(
                TOOL_RECONCILIATION_FAILED,
                f"tool {contract.tool!r} did not state whether it applied "
                f"{held.classified.intent} ({type(error).__name__}: {error}); the outcome "
                "stays unknown and the tool is not called",
            ) from error
        assert isinstance(result, ToolMutationResultV1) and held.intent_evidence is not None
        if result.outcome is MutationOutcome.NOT_APPLIED:
            self.journal.append_event(
                TOOL_RECONCILED, **scope, attempt=attempt, outcome=result.outcome.value
            )
            return None
        result_ref = self.documents.put(RESULT_ROLE, result.document())
        self.journal.append_event(
            TOOL_RECONCILED, **scope, attempt=attempt, outcome=result.outcome.value,
            tool_result=str(result.identity()), evidence=result_ref.document(),
        )
        return CompletedToolCallV1(
            intent, result, held.intent_evidence, result_ref, attempt, "RECONCILIATION"
        )


def _window(contract: ToolActorContractV1) -> str:
    """The containment window *contract*'s tool is called in."""

    return TOOL if contract.effect is ToolEffect.MUTATING else TOOL_READ


def _typed_result(contract: ToolActorContractV1, intent: ToolIntent, answer: Any) -> ToolResult:
    """What the tool answered, as the contract's typed result (BVL-TOOL-008)."""

    if isinstance(intent, ToolReadIntentV1):
        return tool_read_result(contract, intent, answer)
    if not isinstance(answer, Mapping) or set(answer) != _MUTATION_ANSWER:
        raise ToolError(
            TOOL_RESULT_INVALID,
            f"a mutating tool answers exactly {sorted(_MUTATION_ANSWER)}",
        )
    return tool_mutation_result(
        contract, intent, answer["outcome"], receipt=answer["receipt"], value=answer["value"]
    )
