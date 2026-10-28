"""Custody: what a run ACCEPTED as evidence — not what it happens to store.

An artifact on disk is a file. A custody entry is the run's statement that
this artifact is the realisation of one scheduled record, produced by one
attempt, by the execution the journal recorded, with the content the adapter
returned (R2: complete means accepted here, never "a path exists").

A custody entry is an evidence FACT, not a judgement. It records what
happened; it does not say whether the execution matched what was declared —
that comparison is the gate's (R39/R40), on this evidence.

Each entry binds, so that the whole chain can be reconstructed from the
package alone:

    design + schedule identity      which declaration this cell belongs to (R18)
    run + session                   which run, and which session wrote it (R15)
    record + cell + replicate + position    which scheduled record
    attempt                         which attempt (exactly one in MVP, R3)
    request                         the canonical request that was sent
    actual_execution + execution    what answered, and the digest of that
                                    attempt's actual-execution records (R38);
                                    recomputing it detects journal edits
    response + artifact_content     what came back, and what was stored (R4)
    artifact                        where those bytes are (a location)
    origin                          FRESH (written at execution time) or
                                    RECOVERED (operator-confirmed, R16)
    derivation + lineage            when a transform produced this artifact:
                                    the derivation record and its digest (R41);
                                    absent when nothing derived it (NO CLAIM)

Entries are appended to `custody/entries.jsonl` with the journal's durability.
At most one entry per record: a duplicate is refused, never merged (R3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.layout import CUSTODY_DIR, ENTRIES_FILE
from boomvalley_lab.custody.derivation import check_derivation, lineage_identity
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.identity.kinds import ArtifactContentIdentity, ExecutionIdentity
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal.grammar import RunContext
from boomvalley_lab.journal.grammar import problems as grammar_problems
from boomvalley_lab.journal.log import AppendOnlyLog
from boomvalley_lab.store.artifacts import ArtifactRef, ArtifactStore, artifact_name

ENTRY_SCHEMA = "boomvalley-lab-custody-entry-1"

#: bumped from the unversioned v1 preimage because the semantic input set
#: changed: the provider response digest is no longer part of what identifies
#: an execution (OD-05, OD-08). The version lives inside the preimage.
EXECUTION_IDENTITY_SCHEMA = "boomvalley-lab-execution-identity-2"

FRESH = "FRESH"
RECOVERED = "RECOVERED"
ORIGINS = (FRESH, RECOVERED)

RECORDED = "RECORDED"

REQUIRED_KEYS = (
    "schema", "run", "design", "schedule", "record", "cell", "replicate", "position",
    "attempt", "session", "origin", "request", "actual_execution", "execution",
    "response", "artifact", "artifact_content", "custody_state", "at",
)


def check_entry(entry: Any, where: str) -> dict:
    if not isinstance(entry, Mapping) or entry.get("schema") != ENTRY_SCHEMA:
        raise EvidenceError(f"{where}: not a custody entry: {entry!r}")
    missing = [key for key in REQUIRED_KEYS if key not in entry]
    if missing:
        raise EvidenceError(f"{where}: a custody entry lacks {missing}")
    if entry["origin"] not in ORIGINS:
        raise EvidenceError(f"{where}: origin is {list(ORIGINS)}, got {entry['origin']!r}")
    if entry["origin"] == RECOVERED and not str(entry.get("operator_decision", "")).strip():
        raise EvidenceError(f"{where}: a RECOVERED entry records the operator decision (R16)")
    ev.execution_document(entry["actual_execution"], where)
    if entry.get("derivation") is not None:
        recorded = check_derivation(entry["derivation"], f"{where}: derivation")
        if entry.get("lineage") != str(lineage_identity(recorded).digest):
            raise EvidenceError(f"{where}: the lineage digest is not this derivation record")
    elif entry.get("lineage") is not None:
        raise EvidenceError(f"{where}: a lineage digest without a derivation record")
    return dict(entry)


class CustodyLedger(AppendOnlyLog):
    """The run's custody entries, append-only and durable."""

    def __init__(self, directory: Path) -> None:
        super().__init__(Path(directory) / CUSTODY_DIR / ENTRIES_FILE, check_entry, "custody")

    def by_record(self) -> dict[str, list[dict]]:
        entries: dict[str, list[dict]] = {}
        for entry in self.read():
            entries.setdefault(entry["record"], []).append(entry)
        return entries


def execution_identity(attempt: str, events: Sequence[Mapping]) -> ExecutionIdentity:
    """R38/OD-05: the digest of one attempt's ACTUAL-EXECUTION records.

    What answered, under what conditions — computed by custody from the
    journal, never supplied by the adapter or the caller.

    What came back is deliberately NOT here. Version 1 of this preimage also
    digested the response, which made ExecutionIdentity change whenever the
    provider returned different bytes: one identity carrying two
    responsibilities. Response and artifact content are identified by
    `artifact_content` (OD-06) and re-checked by custody reconciliation, so
    removing them narrows what this identity MEANS without removing any
    verification — the bytes are still recomputed and compared, one layer out.

    The schema is inside the preimage, so a v1 digest and a v2 digest of the
    same attempt can never be mistaken for one another (OD-08).
    """
    returned = [e for e in events if e["event"] == ev.CALL_RETURNED]
    return ExecutionIdentity.of_document({
        "identity_schema": EXECUTION_IDENTITY_SCHEMA,
        "attempt": attempt,
        "actual_execution": [ev.execution_document(e["actual_execution"], "journal")
                             for e in returned],
    })


def _scheduled(records: Sequence[ExecutionRecord], record_key: str
               ) -> tuple[int, ExecutionRecord]:
    for position, record in enumerate(records):
        if record.key == record_key:
            return position, record
    raise EvidenceError(
        f"custody refuses {record_key}: the locked schedule does not contain it"
    )


def recompute_chain(record_key: str, position: int, events: Sequence[Mapping],
                    store: ArtifactStore, *, origin: str = FRESH,
                    context: RunContext | None = None) -> dict:
    """The evidence chain one accepted record rests on, recomputed from the
    journal and the artifacts — or EvidenceError saying exactly what broke.

    Used twice, on purpose: once when custody ACCEPTS a record, and again
    whenever the evidence is reconciled. An auditor must be able to rebuild
    the chain from the bytes, so a journal edited after sealing (a deleted or
    duplicated intent, a changed request identity, a second attempt) is caught
    by recomputation rather than trusted because custody once agreed.
    """
    # A legal history first: an event set that could not have happened is not
    # evidence, however complete it looks (R1, R3, R7, R8, R18, R37, R2).
    illegal = grammar_problems(record_key, events, context)
    if illegal:
        raise EvidenceError(f"custody refuses {illegal[0]}", problems=tuple(illegal))
    kinds = [e["event"] for e in events]
    if kinds.count(ev.INTENT_RECORDED) != 1 or (kinds and kinds[0] != ev.INTENT_RECORDED):
        raise EvidenceError(f"custody refuses {record_key}: one durable intent must come first")
    intent = events[0]
    if intent["position"] != position:
        raise EvidenceError(f"custody refuses {record_key}: the intent names another position")
    returned = [e for e in events if e["event"] == ev.CALL_RETURNED]
    if len(returned) != 1:
        raise EvidenceError(f"custody refuses {record_key}: no single returned call to accept")
    persisted = [e for e in events if e["event"] == ev.ARTIFACT_PERSISTED]
    if origin == FRESH and len(persisted) != 1:
        raise EvidenceError(f"custody refuses {record_key}: its artifact was never journaled")
    name = artifact_name(position)
    if persisted:
        if persisted[0]["artifact"] != name:
            raise EvidenceError(f"custody refuses {record_key}: the artifact is not this record's")
        if persisted[0]["artifact_content"] != returned[0]["response"]:
            raise EvidenceError(
                f"custody refuses {record_key}: the stored content is not the returned response"
            )
    content = returned[0]["response"]
    derivation = returned[0].get("derivation")
    ref = ArtifactRef(name, ArtifactContentIdentity(Digest.parse(content)))
    try:
        store.read(ref)
    except (OSError, EvidenceError) as error:
        raise EvidenceError(
            f"custody refuses {record_key}: its artifact is not readable as the returned "
            f"response ({error})"
        ) from error
    return {
        "attempt": intent["attempt"],
        "request": intent["request"],
        "actual_execution": ev.execution_document(returned[0]["actual_execution"], "journal"),
        "execution": str(execution_identity(intent["attempt"], events).digest),
        "response": content,
        "artifact": name,
        "artifact_content": content,
        "journaled_persistence": bool(persisted),
        "derivation": check_derivation(derivation, "journal derivation") if derivation else None,
    }


def accept(directory: Path, *, run_id: str, identities: Mapping[str, str],
           records: Sequence[ExecutionRecord], record_key: str, session: str,
           journal: Sequence[Mapping], store: ArtifactStore, at: str,
           origin: str = FRESH, operator_decision: str | None = None) -> dict:
    """Accept one record's artifact into custody, or refuse with the reason.

    Refuses: an unscheduled record, a second entry for a record (R3), a broken
    or incomplete evidence chain, an artifact that does not read back as the
    response the journal recorded (R2, R4). Nothing here is a judgement about
    whether the execution was the declared one (R39/R40 decide that later).
    """
    if origin not in ORIGINS:
        raise ExecutionError(f"custody origin is {list(ORIGINS)}, got {origin!r}")
    if origin == RECOVERED and not (operator_decision or "").strip():
        raise ExecutionError("a RECOVERED custody entry requires the operator decision (R16)")
    position, record = _scheduled(records, record_key)
    ledger = CustodyLedger(directory)
    if record_key in ledger.by_record():
        raise ExecutionError(
            f"custody already holds {record_key}; at most one accepted realisation per "
            "scheduled record (R3)"
        )
    events = [e for e in journal if e.get("record") == record_key]
    chain = recompute_chain(record_key, position, events, store, origin=origin,
                            context=RunContext.of(journal, run_id))
    entry = {
        "schema": ENTRY_SCHEMA,
        "run": run_id,
        "design": identities["design"],
        "schedule": identities["schedule"],
        "record": record_key,
        "cell": record.cell.key,
        "replicate": record.replicate,
        "position": position,
        "attempt": chain["attempt"],
        "session": session,
        "origin": origin,
        "request": chain["request"],
        "actual_execution": chain["actual_execution"],
        "execution": chain["execution"],
        "response": chain["response"],
        "artifact": chain["artifact"],
        "artifact_content": chain["artifact_content"],
        "custody_state": RECORDED,
        "at": at,
    }
    if chain["derivation"] is not None:  # R41: custody seals the lineage with the child
        entry["derivation"] = chain["derivation"]
        entry["lineage"] = str(lineage_identity(chain["derivation"]).digest)
    if origin == RECOVERED:
        entry["operator_decision"] = operator_decision
        entry["recovered_from"] = {
            "journaled_persistence": chain["journaled_persistence"],
            "response": chain["response"],
            "artifact_content": chain["artifact_content"],
            "attempt": chain["attempt"],
            "run": run_id,
            "schedule": identities["schedule"],
        }
    return ledger.append(entry)


def recover(directory: Path, *, operator_decision: str, **kwargs: Any) -> dict:
    """The operator-confirmed recovery path (R16, frozen resume policy).

    Never called automatically: a record whose artifact is persisted but not in
    custody stays OPERATOR_DECISION until a person decides. The entry it writes
    is marked RECOVERED with its evidence chain, so it can never be mistaken
    for one written at execution time.
    """
    return accept(directory, origin=RECOVERED, operator_decision=operator_decision, **kwargs)
