"""K0 lifecycle state and outcome lattice.

The state machine preserves the baseline's fail-closed distinctions while
making room for proposal, decision, World and round lifecycle events.

This lattice is the K0 design vocabulary, not an enforcement point (SV-09,
SV-04 m-13): no execution path calls ``ensure_transition``, and it knows
neither the human (T5-002) nor the tool (T5-004) call chain.  What holds a
run to its order is evidence, in three places: the engine's own control flow
(``kernel/engine.py``), the resume preflight and the commit-once rule of a
resumed episode (``kernel/replay.py``, with ``recovery2`` / ``human_recovery``
/ ``tool_call`` classifying each call history), and the package derivation,
which refuses a journal whose events are not exactly the IR's steps
(``kernel/package4.py``).  ``lifecycle/gated.py`` reads the run-level state
(OPENED .. SEALED) off the journal.
"""

from __future__ import annotations

from enum import StrEnum

from boomvalley_lab.core.errors import ExecutionError


class OutcomeClass(StrEnum):
    """Why a non-successful scientific step did not simply continue."""

    INTEGRITY = "INTEGRITY"
    SCIENTIFIC = "SCIENTIFIC"
    OPERATIONAL = "OPERATIONAL"


class RecoveryAction(StrEnum):
    """Permitted run-level consequences after a classified outcome."""

    CONTINUE = "CONTINUE"
    RETRY = "RETRY"
    FAIL_EPISODE = "FAIL_EPISODE"
    FAIL_RUN = "FAIL_RUN"
    OPERATOR_DECISION = "OPERATOR_DECISION"
    ABORT = "ABORT"


class StepState(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    PRE_TRANSPORT_REFUSED = "PRE_TRANSPORT_REFUSED"
    CALL_INTENT_RECORDED = "CALL_INTENT_RECORDED"
    TRANSPORT_STARTED = "TRANSPORT_STARTED"
    CALL_OUTCOME_UNKNOWN = "CALL_OUTCOME_UNKNOWN"
    CALL_RETURNED = "CALL_RETURNED"
    RESPONSE_REJECTED = "RESPONSE_REJECTED"
    CALL_PERSISTED = "CALL_PERSISTED"
    PERSISTED_UNRECORDED = "PERSISTED_UNRECORDED"
    CUSTODY_ACCEPTED = "CUSTODY_ACCEPTED"
    PROPOSAL_PARSED = "PROPOSAL_PARSED"
    DECISION_READY = "DECISION_READY"
    DECISION_RECORDED = "DECISION_RECORDED"
    WORLD_INTENT_RECORDED = "WORLD_INTENT_RECORDED"
    WORLD_OUTCOME_UNKNOWN = "WORLD_OUTCOME_UNKNOWN"
    WORLD_APPLIED = "WORLD_APPLIED"
    ROUND_COMPLETE = "ROUND_COMPLETE"
    TERMINATION_EVALUATED = "TERMINATION_EVALUATED"
    WAITING = "WAITING"
    EPISODE_COMPLETE = "EPISODE_COMPLETE"
    FAILED = "FAILED"
    INCONSISTENT = "INCONSISTENT"
    OPERATOR_DECISION = "OPERATOR_DECISION"
    ABORTED = "ABORTED"


_TERMINAL = {
    StepState.PRE_TRANSPORT_REFUSED,
    StepState.RESPONSE_REJECTED,
    StepState.EPISODE_COMPLETE,
    StepState.FAILED,
    StepState.INCONSISTENT,
    StepState.OPERATOR_DECISION,
    StepState.ABORTED,
}

_ALLOWED: dict[StepState, frozenset[StepState]] = {
    StepState.PLANNED: frozenset({StepState.READY, StepState.ABORTED}),
    StepState.READY: frozenset(
        {
            StepState.PRE_TRANSPORT_REFUSED,
            StepState.CALL_INTENT_RECORDED,
            StepState.DECISION_READY,
            StepState.WORLD_INTENT_RECORDED,
            StepState.WAITING,
            StepState.ABORTED,
        }
    ),
    StepState.CALL_INTENT_RECORDED: frozenset(
        {StepState.TRANSPORT_STARTED, StepState.ABORTED}
    ),
    StepState.TRANSPORT_STARTED: frozenset(
        {StepState.CALL_RETURNED, StepState.CALL_OUTCOME_UNKNOWN}
    ),
    StepState.CALL_OUTCOME_UNKNOWN: frozenset(
        {StepState.OPERATOR_DECISION, StepState.ABORTED}
    ),
    StepState.CALL_RETURNED: frozenset(
        {StepState.RESPONSE_REJECTED, StepState.CALL_PERSISTED}
    ),
    StepState.CALL_PERSISTED: frozenset(
        {StepState.PERSISTED_UNRECORDED, StepState.CUSTODY_ACCEPTED}
    ),
    StepState.PERSISTED_UNRECORDED: frozenset(
        {StepState.CUSTODY_ACCEPTED, StepState.OPERATOR_DECISION, StepState.ABORTED}
    ),
    StepState.CUSTODY_ACCEPTED: frozenset(
        {
            StepState.PROPOSAL_PARSED,
            StepState.DECISION_READY,
            StepState.ROUND_COMPLETE,
            StepState.EPISODE_COMPLETE,
        }
    ),
    StepState.PROPOSAL_PARSED: frozenset(
        {StepState.DECISION_READY, StepState.ROUND_COMPLETE, StepState.EPISODE_COMPLETE}
    ),
    StepState.DECISION_READY: frozenset(
        {StepState.DECISION_RECORDED, StepState.FAILED, StepState.ABORTED}
    ),
    StepState.DECISION_RECORDED: frozenset(
        {
            StepState.WORLD_INTENT_RECORDED,
            StepState.ROUND_COMPLETE,
            StepState.EPISODE_COMPLETE,
        }
    ),
    StepState.WORLD_INTENT_RECORDED: frozenset(
        {StepState.WORLD_APPLIED, StepState.WORLD_OUTCOME_UNKNOWN}
    ),
    StepState.WORLD_OUTCOME_UNKNOWN: frozenset(
        {StepState.OPERATOR_DECISION, StepState.ABORTED}
    ),
    StepState.WORLD_APPLIED: frozenset(
        {StepState.ROUND_COMPLETE, StepState.TERMINATION_EVALUATED}
    ),
    StepState.ROUND_COMPLETE: frozenset(
        {
            StepState.TERMINATION_EVALUATED,
            StepState.EPISODE_COMPLETE,
            StepState.READY,
        }
    ),
    StepState.TERMINATION_EVALUATED: frozenset(
        {StepState.READY, StepState.EPISODE_COMPLETE, StepState.ABORTED}
    ),
    StepState.WAITING: frozenset(
        {
            StepState.CALL_RETURNED,
            StepState.OPERATOR_DECISION,
            StepState.ABORTED,
        }
    ),
}


def ensure_transition(current: StepState, target: StepState) -> StepState:
    """Return *target* iff the lifecycle transition is explicitly permitted."""

    if current in _TERMINAL:
        raise ExecutionError(f"terminal lifecycle state {current.value} cannot advance")
    allowed = _ALLOWED.get(current, frozenset())
    if target not in allowed:
        raise ExecutionError(
            f"invalid lifecycle transition {current.value} -> {target.value}"
        )
    return target


def is_terminal(state: StepState) -> bool:
    return state in _TERMINAL


def default_recovery(
    outcome: OutcomeClass,
    *,
    external_side_effect_uncertain: bool = False,
) -> RecoveryAction:
    """K0 default; study/run policy may narrow but not weaken integrity safety."""

    if external_side_effect_uncertain:
        return RecoveryAction.OPERATOR_DECISION
    if outcome is OutcomeClass.INTEGRITY:
        return RecoveryAction.ABORT
    if outcome is OutcomeClass.SCIENTIFIC:
        return RecoveryAction.CONTINUE
    return RecoveryAction.FAIL_EPISODE
