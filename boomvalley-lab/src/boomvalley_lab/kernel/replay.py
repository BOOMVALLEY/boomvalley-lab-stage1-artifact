"""Evidence-driven resume of an interrupted episode (T2-006).

A restarted episode is the same deterministic execution, continued: the
engine walks the frozen IR again from round 1 and every boundary is
*committed once*.

    human call         a call whose intent names a human request intent waits
                       on its channel (T5-002, ``kernel/waiting.py``): its
                       request is delivered once and its answer collected
                       once, so it is continued where a provider call past
                       transport is not (``kernel/human_recovery.py``).
    provider call      a custody-accepted call is never re-invoked: the step
                       re-derives its request-2 from the restored upstream
                       evidence, and the durable executor returns the recorded
                       call (response bytes read back through the re-verified
                       custody chain).  An intent that never reached transport
                       is continued (T0-010); every other state refuses.
    World.apply        an APPLIED transition is returned from its evidence and
                       never re-applied (T0-011).
    pure steps         parser / decision rule / memory are recomputed from the
                       restored inputs (they are contained, deterministic
                       plugins) and their commit event must be exactly the one
                       already journaled; it is not appended a second time.
    engine events      EPISODE_OPENED, STEP_READY, ROUND_COMPLETED and
                       EPISODE_COMPLETED likewise.

So a dependency output is never fabricated: a downstream request is built only
from a value whose commit event is journaled and re-derives from
custody-accepted bytes (T2-002 readiness applies to restored values too), and
a step whose re-derived request is not the journaled call refuses
(``BVL-RES-001``) instead of making a second call.  And it is never
duplicated: one call, one custody entry and one commit event per step, so the
resumed journal is the journal an uninterrupted run would have written.

A refusal (``ResumeRefusedError``) is an integrity or operator outcome, not a
scientific one: the engine does not journal it as EPISODE_FAILED and the run
stays interrupted.

``plan_episode_resume`` is the read-only preflight: it classifies every
journaled call (recovery2) and World intent and reconciles custody, and names
the one action the evidence allows before anything executes.  A journal that
carries an engine event twice in its scope (T4-006: a round opened or closed
twice, a second verdict of one point, an episode opened or completed twice) is
a duplicated round, not an interrupted one, and is never continued:

    EXECUTE            every boundary is committed, or provably not started
    OPERATOR_DECISION  an external outcome is not proven (never auto-repeated)
    ABORT              the evidence contradicts itself
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.layout import ARTIFACT_DIR
from boomvalley_lab.kernel.custody2 import CustodyLedgerV2, call_artifact_name, call_from_key
from boomvalley_lab.kernel.human_recovery import classify_actor_call
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CUSTODY_ACCEPTED,
    DECISION_FAILED,
    DECISION_RECORDED,
    EPISODE_COMPLETED,
    EPISODE_FAILED,
    EPISODE_OPENED,
    MEMORY_RECORDED,
    PROPOSAL_PARSE_FAILED,
    PROPOSAL_PARSED,
    ROUND_COMPLETED,
    ROUND_OPENED,
    STEP_READY,
    TERMINATION_EVALUATED,
    WORLD_APPLIED,
    Journal2,
)
from boomvalley_lab.kernel.recovery2 import ResumeDecisionV2
from boomvalley_lab.kernel.request_store import RequestStoreV2
from boomvalley_lab.kernel.world import RESUME_TRANSITION_UNCERTAIN
from boomvalley_lab.kernel.world_executor import WorldTransitionStateV2, reconcile_world_v2
from boomvalley_lab.store.artifacts import ArtifactStore

RESUME_EVIDENCE_MISMATCH = "BVL-RES-001"
RESUME_OUTCOME_NOT_PROVEN = "BVL-RES-002"
RESUME_EPISODE_CLOSED = "BVL-RES-003"
RES_CODES = frozenset({RESUME_EVIDENCE_MISMATCH, RESUME_OUTCOME_NOT_PROVEN, RESUME_EPISODE_CLOSED})

EXECUTE = "EXECUTE"
OPERATOR_DECISION = "OPERATOR_DECISION"
ABORT = "ABORT"

# ``point`` tells a round's termination verdicts apart (T4-002: the rule's
# timing point and the core's safety-bound verdict may share a round)
_SCOPE = ("episode", "step", "round", "call", "point")
# a step (or episode) commits one of these, never both
_EXCLUSIVE: dict[str, str] = {
    PROPOSAL_PARSED: PROPOSAL_PARSE_FAILED,
    PROPOSAL_PARSE_FAILED: PROPOSAL_PARSED,
    DECISION_RECORDED: DECISION_FAILED,
    DECISION_FAILED: DECISION_RECORDED,
    EPISODE_COMPLETED: EPISODE_FAILED,
}
# the one commit event a step may carry once (kernel/readiness.COMMIT_EVENT)
_STEP_COMMITS = (
    CUSTODY_ACCEPTED,
    PROPOSAL_PARSED,
    PROPOSAL_PARSE_FAILED,
    DECISION_RECORDED,
    DECISION_FAILED,
    WORLD_APPLIED,
    MEMORY_RECORDED,
)
# an engine event is journaled once in its scope (T4-006): an episode and a
# round open and close once, a step is admitted once and a round carries one
# termination verdict per point; a second one is a duplicated round, never a
# boundary to continue from
_ENGINE_ONCE: dict[str, tuple[str, ...]] = {
    EPISODE_OPENED: ("episode",),
    EPISODE_COMPLETED: ("episode",),
    ROUND_OPENED: ("episode", "round"),
    ROUND_COMPLETED: ("episode", "round"),
    TERMINATION_EVALUATED: ("episode", "round", "point"),
    STEP_READY: ("step",),
}


class ResumeRefusedError(ExecutionError):
    """A resumed episode may not continue; nothing is journaled for it."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in RES_CODES:
            raise ValueError(f"unknown resume reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


def commit(journal: Journal2, event: str, *, resumed: bool, run: str, **fields: Any) -> dict:
    """Append *event*, or - in a resumed episode - match the one already journaled.

    A resumed step that recomputes another commit than the durable one is
    BVL-RES-001: the evidence it was restored from does not reproduce it.
    """

    if not resumed:
        return journal.append_event(event, run=run, **fields)
    scope = {name: fields[name] for name in _SCOPE if name in fields}
    held = []
    for record in journal.read():
        if any(record.get(name) != value for name, value in scope.items()):
            continue
        if record["event"] == _EXCLUSIVE.get(event):
            raise ResumeRefusedError(
                RESUME_EVIDENCE_MISMATCH,
                f"{event} is recomputed where journal-2 #{record['sequence']} committed "
                f"{record['event']}",
            )
        if record["event"] == event:
            held.append(record)
    if not held:
        return journal.append_event(event, run=run, **fields)
    expected = {"run": run, **fields}
    recorded = {k: v for k, v in held[0].items() if k not in ("schema", "sequence", "event")}
    if len(held) > 1 or canonical_json(recorded) != canonical_json(expected):
        raise ResumeRefusedError(
            RESUME_EVIDENCE_MISMATCH,
            f"{event} recomputed on resume is not the committed journal-2 "
            f"#{held[0]['sequence']}"
            + (f" ({len(held)} such events are journaled)" if len(held) > 1 else ""),
        )
    return held[0]


@dataclass(frozen=True)
class EpisodeResumePlanV1:
    """What the durable evidence of an interrupted run allows next (read-only)."""

    action: str
    calls: tuple[Mapping[str, Any], ...]
    world_transitions: tuple[Mapping[str, Any], ...]
    reasons: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "calls": [dict(call) for call in self.calls],
            "world_transitions": [dict(world) for world in self.world_transitions],
            "reasons": list(self.reasons),
        }


def plan_episode_resume(run_directory: Path) -> EpisodeResumePlanV1:
    """Classify every journaled call and World intent; never writes, never calls."""

    run_directory = Path(run_directory)
    journal = Journal2(run_directory)
    abort: list[str] = []
    operator: list[str] = []
    try:
        records = journal.read()
        ledger = CustodyLedgerV2(run_directory)
        accepted = set(ledger.by_call())
        if journal.torn_tail():
            operator.append("journal-2 has a torn tail")
        if ledger.torn_tail():
            operator.append("custody-v2 has a torn tail")
    except EvidenceError as error:
        return EpisodeResumePlanV1(ABORT, (), (), (str(error),))

    requests = RequestStoreV2(run_directory)
    artifacts = ArtifactStore(run_directory)
    calls: list[dict[str, Any]] = []
    by_step: dict[str, set[str]] = {}
    commits: dict[tuple[str, str], int] = {}
    seen: set[str] = set()
    members: set[str] = set()
    engine: dict[tuple[Any, ...], int] = {}
    for record in records:
        step = record.get("step")
        if record["event"] in _ENGINE_ONCE:
            scope = (record["event"],
                     *(record.get(name) for name in _ENGINE_ONCE[record["event"]]))
            engine[scope] = engine.get(scope, 0) + 1
        if record["event"] in _STEP_COMMITS:
            key = (step, record["event"])
            commits[key] = commits.get(key, 0) + 1
        call_key = record.get("call")
        if call_key is None or call_key in seen:
            continue
        seen.add(call_key)
        by_step.setdefault(step, set()).add(call_key)
        if record["event"] != CALL_INTENT_RECORDED:
            abort.append(f"{call_key}: call history does not open with its intent")
            continue
        try:
            call = call_from_key(call_key)
            members.add(call_artifact_name(call))
            # a human call's request and answer outlive the process (T5-002)
            classified = classify_actor_call(
                run_directory=run_directory, call=call, journal=journal,
                requests=requests, artifacts=artifacts,
            )
        except (EvidenceError, ValueError) as error:
            abort.append(f"{call_key}: {error}")
            continue
        calls.append({
            "call": call_key, "step": step, "round": record["round"],
            "state": classified.state.value, "decision": classified.decision.value,
            "reason": classified.reason,
        })
        detail = f"{call_key} is {classified.state.value}" + (
            f" ({classified.reason})" if classified.reason else "")
        if classified.decision is ResumeDecisionV2.ABORT:
            abort.append(detail)
        elif classified.decision is ResumeDecisionV2.OPERATOR_DECISION:
            operator.append(detail)
    for step, keys in sorted(by_step.items()):
        if len(keys) > 1:
            abort.append(f"step {step} carries {len(keys)} calls; a step makes one call")
    for (step, event), count in sorted(commits.items()):
        if count > 1:
            abort.append(f"step {step} carries {count} {event} events")
    for (event, *scope), count in engine.items():
        if count > 1:
            where = ", ".join(
                f"{name} {value}" for name, value in zip(_ENGINE_ONCE[event], scope, strict=True)
                if value is not None)
            abort.append(f"{where} carries {count} {event} events")
    for call_key in sorted(accepted - seen):
        abort.append(f"custody-v2 holds an entry for unjournaled {call_key}")
    stored = run_directory / ARTIFACT_DIR
    if stored.is_dir():
        for path in sorted(stored.glob("call-*.bin")):
            if path.name not in members:
                abort.append(f"response member {path.name} belongs to no journaled call")

    reconciled = reconcile_world_v2(run_directory)
    abort.extend(reconciled.problems)
    worlds = [{"intent": intent, "state": WorldTransitionStateV2.APPLIED.value}
              for intent in reconciled.applied]
    for intent, state in reconciled.pending:
        worlds.append({"intent": intent, "state": state})
        if state == WorldTransitionStateV2.OUTCOME_UNKNOWN.value:
            operator.append(f"{RESUME_TRANSITION_UNCERTAIN}: {intent} is {state}")

    action = ABORT if abort else OPERATOR_DECISION if operator else EXECUTE
    reasons = tuple(dict.fromkeys([*abort, *operator]))
    return EpisodeResumePlanV1(action, tuple(calls), tuple(worlds), reasons)
