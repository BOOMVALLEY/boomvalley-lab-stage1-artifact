"""journal-2 event vocabulary for generalized organizational execution.

This lives beside journal-1 during the spike.  It does not reinterpret old
events.  Every record is closed and sequence-ordered; logical order, not wall
clock time, establishes causality.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.journal.log import AppendOnlyLog, held

SCHEMA = "boomvalley-lab-journal-2"

RUN_OPENED = "RUN_OPENED"
RUN_REFUSED = "RUN_REFUSED"
EPISODE_OPENED = "EPISODE_OPENED"
STEP_READY = "STEP_READY"
PRE_TRANSPORT_REFUSED = "PRE_TRANSPORT_REFUSED"
CALL_INTENT_RECORDED = "CALL_INTENT_RECORDED"
TRANSPORT_STARTED = "TRANSPORT_STARTED"
CALL_OUTCOME_UNKNOWN = "CALL_OUTCOME_UNKNOWN"
CALL_RETURNED = "CALL_RETURNED"
RESPONSE_REJECTED = "RESPONSE_REJECTED"
CALL_PERSISTED = "CALL_PERSISTED"
CUSTODY_ACCEPTED = "CUSTODY_ACCEPTED"
# P17 (T5-002, ``kernel/waiting.py``): a human actor call's request reached its
# channel, and its answer came back; each is committed once per request intent.
# Neither names the call: the call chain of a human call is every call's.
HUMAN_REQUEST_DELIVERED = "HUMAN_REQUEST_DELIVERED"
HUMAN_RESPONSE_RECEIVED = "HUMAN_RESPONSE_RECEIVED"
# P17 (T5-004, ``kernel/tool_call.py``): the call of a tool actor's tool.  The
# intent is durable before the call starts; a call that started and neither
# returned nor was reconciled has an unknown outcome.  An attempt is one call
# of the tool: a mutating tool has a second one only after a reconciliation
# proved the first changed nothing.
TOOL_INTENT_RECORDED = "TOOL_INTENT_RECORDED"
TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"
TOOL_RETURNED = "TOOL_RETURNED"
TOOL_RECONCILED = "TOOL_RECONCILED"
PROPOSAL_PARSED = "PROPOSAL_PARSED"
# P06 (T1-004): the call succeeded, its response failed the parser contract
PROPOSAL_PARSE_FAILED = "PROPOSAL_PARSE_FAILED"
DECISION_RECORDED = "DECISION_RECORDED"
# P07 (T1-005): the declared rule left the decision unresolved under FAIL_EPISODE
DECISION_FAILED = "DECISION_FAILED"
WORLD_INTENT_RECORDED = "WORLD_INTENT_RECORDED"
WORLD_OUTCOME_UNKNOWN = "WORLD_OUTCOME_UNKNOWN"
WORLD_APPLIED = "WORLD_APPLIED"
MEMORY_RECORDED = "MEMORY_RECORDED"
# P16 (T4-001): a round of a plan with a round contract is identified before
# its first step (RoundIdentity = episode x round x pre-state)
ROUND_OPENED = "ROUND_OPENED"
ROUND_COMPLETED = "ROUND_COMPLETED"
TERMINATION_EVALUATED = "TERMINATION_EVALUATED"
EPISODE_COMPLETED = "EPISODE_COMPLETED"
EPISODE_FAILED = "EPISODE_FAILED"
RUN_ABORTED = "RUN_ABORTED"

_BASE = ("schema", "sequence", "event", "run")

REQUIRED: dict[str, tuple[str, ...]] = {
    RUN_OPENED: ("plan", "binding", "binding_evidence", "authorization", "gate"),
    RUN_REFUSED: ("plan", "binding", "binding_evidence", "gate", "reasons"),
    EPISODE_OPENED: ("episode", "episode_key", "plan"),
    STEP_READY: ("episode", "step", "round"),
    PRE_TRANSPORT_REFUSED: ("episode", "step", "round", "reason"),
    CALL_INTENT_RECORDED: ("episode", "step", "round", "call", "request"),
    TRANSPORT_STARTED: ("episode", "step", "round", "call"),
    CALL_OUTCOME_UNKNOWN: ("episode", "step", "round", "call", "reason"),
    CALL_RETURNED: ("episode", "step", "round", "call", "response"),
    RESPONSE_REJECTED: ("episode", "step", "round", "call", "reason"),
    CALL_PERSISTED: ("episode", "step", "round", "call", "artifact"),
    CUSTODY_ACCEPTED: ("episode", "step", "round", "call", "artifact", "custody"),
    HUMAN_REQUEST_DELIVERED: ("episode", "step", "round", "human_intent", "delivery"),
    HUMAN_RESPONSE_RECEIVED: ("episode", "step", "round", "human_intent", "human_response"),
    TOOL_INTENT_RECORDED: ("episode", "step", "round", "tool_intent", "evidence"),
    TOOL_CALL_STARTED: ("episode", "step", "round", "tool_intent", "attempt"),
    TOOL_OUTCOME_UNKNOWN: ("episode", "step", "round", "tool_intent", "attempt", "reason"),
    TOOL_RETURNED: (
        "episode", "step", "round", "tool_intent", "attempt", "tool_result", "evidence",
    ),
    TOOL_RECONCILED: ("episode", "step", "round", "tool_intent", "attempt", "outcome"),
    PROPOSAL_PARSED: ("episode", "step", "round", "proposal"),
    PROPOSAL_PARSE_FAILED: ("episode", "step", "round", "proposal"),
    DECISION_RECORDED: ("episode", "step", "round", "decision"),
    DECISION_FAILED: ("episode", "step", "round", "decision"),
    WORLD_INTENT_RECORDED: ("episode", "step", "round", "transition_intent", "decision"),
    WORLD_OUTCOME_UNKNOWN: ("episode", "step", "round", "transition", "reason"),
    WORLD_APPLIED: (
        "episode",
        "step",
        "round",
        "transition_intent",
        "transition",
        "post_state",
        "evidence",
    ),
    MEMORY_RECORDED: ("episode", "step", "round", "memory"),
    ROUND_OPENED: ("episode", "round", "round_identity", "pre_state"),
    ROUND_COMPLETED: ("episode", "round", "post_state"),
    TERMINATION_EVALUATED: ("episode", "round", "terminate"),
    EPISODE_COMPLETED: ("episode", "rounds"),
    EPISODE_FAILED: ("episode", "step", "round", "reason"),
    RUN_ABORTED: ("reason",),
}
# Members an event may carry beyond REQUIRED.  An L1 call intent (T1-008)
# names the call's ``call_binding`` evidence, durable before the intent.
# An episode names its intra-episode causal order and its experimental
# schedule place (T2-004, ``kernel/schedule.py``).  Under a plan's World
# contract (T3-001) it names the versioned initial state it opens on:
# ``initial_state = {identity, evidence}`` (a ``world_state`` evidence member).
# The intent of a human actor call (T5-002) names its ``human_intent`` evidence:
# who is asked, under which contract and consent record.  The intent of a tool
# actor call (T5-007) names its ``tool_call``: the identities of the tool intent
# and of its contract.
OPTIONAL: dict[str, tuple[str, ...]] = {
    CALL_INTENT_RECORDED: ("call_binding", "human_intent", "tool_call"),
    EPISODE_OPENED: ("protocol_dag", "schedule", "initial_state"),
    # the verdict the plan's round contract derived (``bvl-termination-verdict-1``);
    # under a timed contract (T4-002, ``-verdict-2``) also the point of the round
    # it was evaluated at (the declared timing, or the core's ``safety_bound``)
    TERMINATION_EVALUATED: ("termination", "point"),
    # a reconciliation that proved the change APPLIED names the result it
    # recovered from the tool (T5-004)
    TOOL_RECONCILED: ("tool_result", "evidence"),
}


def check_event_v2(value: Any, where: str) -> dict:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{where}: journal-2 event is not an object")
    event = value.get("event")
    if event not in REQUIRED:
        raise EvidenceError(f"{where}: unknown journal-2 event {event!r}")
    if value.get("schema") != SCHEMA:
        raise EvidenceError(f"{where}: schema is exactly {SCHEMA!r}")
    sequence = value.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise EvidenceError(f"{where}: sequence is a non-negative integer")
    run = value.get("run")
    if not isinstance(run, str) or not run:
        raise EvidenceError(f"{where}: run is a non-empty string")
    required = set(_BASE) | set(REQUIRED[event])
    if not required <= set(value) <= required | set(OPTIONAL.get(event, ())):
        raise EvidenceError(
            f"{where}: {event} carries exactly {sorted(required)} "
            f"(has {sorted(value)})"
        )
    return dict(value)


def _kind(record: dict) -> Any:
    return record["event"]


def _call(record: dict) -> Any:
    return record.get("call")


def _tool_intent(record: dict) -> Any:
    return record.get("tool_intent")


def _episode(record: dict) -> Any:
    return record.get("episode")


def _step(record: dict) -> Any:
    return record.get("step")


def _run(record: dict) -> Any:
    return record["run"]


def held_run(run_directory: Path):  # noqa: ANN201
    """Hold the logs and the committed transitions of one run for one operation."""

    root = Path(run_directory)
    return held(
        root / "journal-2.jsonl",
        root / "custody-v2" / "entries.jsonl",
        root / "evidence-v2" / "world_transition",
    )


class Journal2(AppendOnlyLog):
    def __init__(self, run_directory: Path) -> None:
        super().__init__(
            Path(run_directory) / "journal-2.jsonl",
            check_event_v2,
            "journal-2",
        )

    def append_event(self, event: str, *, run: str, **fields: Any) -> dict:
        sequence = self.count()
        return self.append(
            {
                "schema": SCHEMA,
                "sequence": sequence,
                "event": event,
                "run": run,
                **fields,
            }
        )

    def read(self) -> list[dict]:
        """Every acknowledged event, at its own sequence (``_admit``)."""

        return super().read()

    # One key's events without a scan of the journal (T4-013): each is the
    # ``read()`` filter it names, in journal order.
    def of_event(self, event: str) -> list[dict]:
        """``[r for r in read() if r["event"] == event]``."""

        return self.selected("event", _kind, event)

    def of_call(self, call_key: str) -> list[dict]:
        """``[r for r in read() if r.get("call") == call_key]``."""

        return self.selected("call", _call, call_key)

    def of_tool_intent(self, intent_key: str) -> list[dict]:
        """``[r for r in read() if r.get("tool_intent") == intent_key]``."""

        return self.selected("tool_intent", _tool_intent, intent_key)

    def of_episode(self, episode: str) -> list[dict]:
        """``[r for r in read() if r.get("episode") == episode]``."""

        return self.selected("episode", _episode, episode)

    def of_step(self, step: str) -> list[dict]:
        """``[r for r in read() if r.get("step") == step]``."""

        return self.selected("step", _step, step)

    def runs(self) -> list[str]:
        """Every run the journal's events name, in the order first named."""

        return list(self.grouped("run", _run))

    def _admit(self, records: list[dict], start: int) -> None:
        for expected in range(start, len(records)):
            if records[expected]["sequence"] != expected:
                raise EvidenceError(
                    f"journal-2 sequence {records[expected]['sequence']} at position {expected}"
                )
