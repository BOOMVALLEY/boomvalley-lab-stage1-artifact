"""The one resume planner: a decision over evidence, never a second chance.

    runtime evidence -> deterministic classifier -> frozen R7 decision
                     -> allowed or refused operator action

Resume is not retry, replay, repair or inference. It continues exactly where
the evidence proves continuing is safe, and refuses everywhere else. The
planner therefore:

    * calls no provider and reads no scientific outcome;
    * writes nothing — no artifact, no journal event, no custody entry;
    * fabricates no missing evidence: an unknown call outcome stays unknown.

`assess` is the single per-record assessment (classifier + frozen R7 table)
used by the executor, by `status` and by `plan`, so those three can never
disagree. `plan` adds the run-level questions: is this run still resumable at
all, and who holds it?
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.journal import events as ev
from boomvalley_lab.resume.classify import POLICY, Decision, State, classify
from boomvalley_lab.store.artifacts import ArtifactStore, artifact_name

#: run states in which nothing may be resumed, and why.
TERMINAL = {
    "ABORTED": "the run is ABORTED; a replacement is a new run, never a continuation",
    "SEALED": "the run is SEALED; its evidence is complete and closed",
}


@dataclass(frozen=True)
class Planned:
    """One scheduled record: what the evidence says, and what may be done."""

    record: str
    position: int
    state: State
    decision: Decision
    reason: str = ""
    evidence: Mapping[str, object] | None = None

    def document(self) -> dict:
        return {"record": self.record, "position": self.position, "state": self.state.value,
                "decision": self.decision.value, "reason": self.reason,
                "evidence": dict(self.evidence or {})}


@dataclass(frozen=True)
class RunEvidence:
    """Everything the planner is allowed to look at, gathered by the caller."""

    run: str
    identities: Mapping[str, str]
    records: Sequence[ExecutionRecord]
    journal: Sequence[Mapping]
    store: ArtifactStore
    custody: Mapping[str, Sequence[Mapping]]
    state: str
    active_session: str | None


@dataclass(frozen=True)
class ResumePlan:
    run: str
    state: str
    active_session: str | None
    sessions: tuple[str, ...]
    records: tuple[Planned, ...]

    # ------------------------------------------------------------- counting
    @property
    def by_state(self) -> dict[str, int]:
        return {state.value: sum(1 for p in self.records if p.state is state) for state in State}

    @property
    def by_decision(self) -> dict[str, int]:
        return {decision.value: sum(1 for p in self.records if p.decision is decision)
                for decision in Decision}

    @property
    def to_execute(self) -> tuple[str, ...]:
        return tuple(p.record for p in self.records if p.decision is Decision.EXECUTE)

    @property
    def to_skip(self) -> tuple[str, ...]:
        return tuple(p.record for p in self.records if p.decision is Decision.SKIP)

    @property
    def operator_decisions(self) -> tuple[str, ...]:
        return tuple(p.record for p in self.records if p.decision is Decision.OPERATOR_DECISION)

    @property
    def all_complete(self) -> bool:
        return all(p.state is State.PERSISTED for p in self.records)

    # ------------------------------------------------------------- deciding
    @property
    def blocking(self) -> tuple[str, ...]:
        reasons = []
        if self.state in TERMINAL:
            reasons.append(TERMINAL[self.state])
        if self.active_session:
            reasons.append(
                f"session {self.active_session} still holds this run; an operator must release "
                "it before another session may open (R8)"
            )
        for planned in self.records:
            if planned.decision is Decision.ABORT:
                reasons.append(f"{planned.record}: {planned.state.value} — {planned.reason or ''}"
                               .rstrip(" —"))
        for record in self.operator_decisions:
            reasons.append(f"{record}: PERSISTED_UNRECORDED — an operator must decide whether to "
                           "recover it into custody (R16)")
        return tuple(reasons)

    @property
    def permitted(self) -> bool:
        """May a new session continue this run as it stands?"""
        return not self.blocking

    def document(self) -> dict:
        return {
            "run": self.run,
            "state": self.state,
            "active_session": self.active_session,
            "sessions": len(self.sessions),
            "session_history": list(self.sessions),
            "scheduled": len(self.records),
            "states": self.by_state,
            "decisions": self.by_decision,
            "resume_permitted": self.permitted,
            "blocking": list(self.blocking),
            "operator_decision_required": list(self.operator_decisions),
            "all_complete": self.all_complete,
        }


def assess(records: Sequence[ExecutionRecord], journal: Sequence[Mapping],
           store: ArtifactStore, custody: Mapping[str, Sequence[Mapping]] | None = None
           ) -> tuple[Planned, ...]:
    """Classify every locked record and apply the frozen R7 table to it."""
    classified = classify(records, journal, store, custody)
    custody = dict(custody or {})
    by_record: dict[str, list[Mapping]] = {}
    for event in journal:
        if "record" in event:
            by_record.setdefault(event["record"], []).append(event)
    planned = []
    for position, record in enumerate(records):
        found = classified[record.key]
        events = by_record.get(record.key, [])
        entries = custody.get(record.key, ())
        planned.append(Planned(
            record=record.key,
            position=position,
            state=found.state,
            decision=POLICY[found.state],
            reason=found.reason,
            evidence={
                "attempt": events[0]["attempt"] if events else None,
                "journal": [e["event"] for e in events],
                "artifact": (artifact_name(position)
                             if store.exists(artifact_name(position)) else None),
                "custody": entries[0]["origin"] if len(entries) == 1 else len(entries),
            },
        ))
    return tuple(planned)


def plan(evidence: RunEvidence) -> ResumePlan:
    """The whole run: per-record decisions plus whether resume is permitted."""
    sessions = tuple(event["session"] for event in evidence.journal
                     if event["event"] == ev.SESSION_OPENED)
    return ResumePlan(
        run=evidence.run,
        state=evidence.state,
        active_session=evidence.active_session,
        sessions=sessions,
        records=assess(evidence.records, evidence.journal, evidence.store, evidence.custody),
    )
