"""The custody seal and its reconciliation.

    seal(...)        every scheduled record is in custody -> write
                     `custody/head.json` once: the entries digest, the session
                     ledger (R15) and a seal digest over both. A sealed head is
                     never rewritten.
    reconcile(...)   recompute everything from the evidence that is there —
                     the journal, the artifacts, the entries, the lock — and
                     report what does not agree, grouped by the question it
                     answers. It trusts no stored digest.

The seal covers the session ledger, so deleting or editing session history
invalidates it (R15). It is tamper EVIDENCE under an operational threat model,
not a cryptographic signature (accepted debt D4): an auditor recomputes it
from the bytes in the package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_document
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.layout import ACTIVE_MARKER, CUSTODY_DIR, HEAD_FILE, SESSIONS_DIR
from boomvalley_lab.core.strict_json import MalformedJSON, load_file
from boomvalley_lab.custody.entries import (
    FRESH,
    RECOVERED,
    CustodyLedger,
    recompute_chain,
)
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.identity.kinds import CustodyEvidenceIdentity
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import order as schedule_order
from boomvalley_lab.journal import serial
from boomvalley_lab.journal import session as lifecycle
from boomvalley_lab.journal.grammar import RunContext
from boomvalley_lab.store.artifacts import ArtifactStore, artifact_name, content_identity

#: bumped when the seal's semantic input changed: the committed session
#: provenance is now the full prior-session transition, not openings alone
#: (OD-02, which requires an explicit version bump when this input changes).
HEAD_SCHEMA = "boomvalley-lab-custody-head-2"
SEALED = "SEALED"


def head_path(directory: Path) -> Path:
    return Path(directory) / CUSTODY_DIR / HEAD_FILE


def session_ledger(journal: Sequence[Mapping]) -> list[dict]:
    """Which sessions contributed to this run, in the order they opened (R15)."""
    ledger: dict[str, dict] = {}
    for event in journal:
        if event["event"] == ev.SESSION_OPENED:
            ledger.setdefault(event["session"],
                              {"session": event["session"], "opened": event["at"],
                               "closed": None})
        elif event["event"] == ev.SESSION_CLOSED:
            entry = ledger.setdefault(event["session"],
                                      {"session": event["session"], "opened": None,
                                       "closed": None})
            entry["closed"] = event["at"]
            if "released_by" in event:
                entry["released_by"] = event["released_by"]
    return list(ledger.values())


def sealed_sessions(journal: Sequence[Mapping], *, sealed_by: str | None) -> list[dict]:
    """What the seal covers: how each writer got the run and gave it up (R15, OD-02).

    Every PRIOR session contributes its whole transition — opened, closed, who
    released it, on what decision, and which session it authorised next — so a
    later verifier can reconstruct why the next writer was allowed to write,
    and so deleting or editing that transition after sealing invalidates the
    seal. The SEALING session contributes its opening only: its close
    necessarily postdates the seal, and that exception is its alone.
    """
    return lifecycle.committed(journal, sealed_by=sealed_by)


def custody_identity(entries: Sequence[Mapping]) -> CustodyEvidenceIdentity:
    return CustodyEvidenceIdentity.of_document(list(entries))


def head_document(*, run_id: str, identities: Mapping[str, str], entries: Sequence[Mapping],
                  journal: Sequence[Mapping], scheduled: int, at: str,
                  sealed_by: str | None = None) -> dict:
    sessions = sealed_sessions(journal, sealed_by=sealed_by)
    body = {
        "schema": HEAD_SCHEMA,
        "run": run_id,
        "sealed_by": sealed_by,
        "identities": {k: identities[k] for k in ("contract", "design", "schedule")},
        "state": SEALED,
        "scheduled": scheduled,
        "entries": len(entries),
        "custody": str(custody_identity(entries).digest),
        "origins": {origin: sum(1 for e in entries if e["origin"] == origin)
                    for origin in (FRESH, RECOVERED)},
        "sessions": sessions,
        "sessions_digest": str(sha256_document(sessions)),
        "at": at,
    }
    return {**body, "seal": str(sha256_document(body))}


def seal(directory: Path, *, run_id: str, identities: Mapping[str, str],
         records: Sequence[ExecutionRecord], journal: Sequence[Mapping], at: str,
         session: str | None = None) -> dict:
    """Seal a run whose whole locked schedule is in custody."""
    entries = CustodyLedger(directory).read()
    held = {entry["record"] for entry in entries}
    missing = [record.key for record in records if record.key not in held]
    if missing:
        raise ExecutionError(
            f"custody holds {len(held)} of {len(records)} scheduled records; "
            f"the first missing is {missing[0]}"
        )
    path = head_path(directory)
    if path.exists():
        raise ExecutionError(f"run {run_id} is already sealed; a custody head is written once")
    document = head_document(run_id=run_id, identities=identities, entries=entries,
                             journal=journal, scheduled=len(records), at=at,
                             sealed_by=session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(document))
    return document


def read_head(directory: Path) -> dict | None:
    path = head_path(directory)
    if not path.exists():
        return None
    try:
        document = load_file(path)
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"the custody head is unreadable: {error}") from error
    if not isinstance(document, Mapping) or document.get("schema") != HEAD_SCHEMA:
        raise EvidenceError("the custody head is not a boomvalley-lab-custody-head-1 document")
    return dict(document)


@dataclass
class Reconciliation:
    """What the custody evidence says, and where it disagrees with itself."""

    entries: dict[str, dict] = field(default_factory=dict)  # record -> entry, schedule order
    membership: list[str] = field(default_factory=list)     # R3, R9, R18 (which records)
    order: list[str] = field(default_factory=list)          # frozen schedule order (in what order)
    serialization: list[str] = field(default_factory=list)  # one attempt at a time (overlap)
    lifecycle: list[str] = field(default_factory=list)      # R8, R15, R16, OD-02 (who wrote it)
    integrity: list[str] = field(default_factory=list)      # R2, R4, R6, R13 (the bytes)
    binding: list[str] = field(default_factory=list)        # R38 (execution <-> artifact)
    sessions: list[str] = field(default_factory=list)       # R15, R16 (who wrote it)
    sealing: list[str] = field(default_factory=list)        # R5 (the seal itself)
    recovered: list[str] = field(default_factory=list)      # R16 (informational)

    @property
    def clean(self) -> bool:
        return not (self.membership or self.order or self.serialization or self.lifecycle
                    or self.integrity or self.binding or self.sessions or self.sealing)


def reconcile(directory: Path, *, run_id: str, identities: Mapping[str, str],
              records: Sequence[ExecutionRecord], journal: Sequence[Mapping],
              store: ArtifactStore) -> Reconciliation:
    """Recompute the custody evidence from the bytes and report disagreements."""
    result = Reconciliation()
    try:
        entries = CustodyLedger(directory).read()
    except EvidenceError as error:
        result.membership.append(str(error))
        return result
    positions = {record.key: position for position, record in enumerate(records)}
    grammar = RunContext.of(journal, run_id)
    # the registered schedule is an ordered sequence, and the run either
    # followed it or executed something else (frozen schedule semantics).
    result.order.extend(schedule_order.problems(records, journal))
    # and it executed them one at a time: a history whose attempts overlap is
    # one no sequential runtime could have written (F-018).
    result.serialization.extend(serial.problems(journal))
    # who held the run, when they gave it up, and how the next writer was
    # authorised — a state machine, not a membership list (R8, R15, OD-02).
    result.lifecycle.extend(lifecycle.problems(journal, run_id))
    by_record: dict[str, dict] = {}
    for entry in entries:
        key = entry["record"]
        if key not in positions:
            result.membership.append(
                f"custody holds {key}, which the locked schedule does not contain"
            )
            continue
        if key in by_record:
            result.membership.append(f"custody holds {key} twice (R3)")
            continue
        by_record[key] = entry
    for record in records:
        if record.key not in by_record:
            result.membership.append(f"{record.key} is scheduled and not in custody")
    events_by_record: dict[str, list[Mapping]] = {}
    for event in journal:
        if "record" in event:
            # the schedule cannot grow through the journal either (R9, R18):
            # an event for a record the lock does not name is not evidence
            # about this run, whoever wrote it.
            if event["record"] not in positions:
                result.membership.append(
                    f"the journal names {event['record']}, which the locked schedule "
                    "does not contain"
                )
                continue
            events_by_record.setdefault(event["record"], []).append(event)
    ledger = {session["session"] for session in session_ledger(journal)}
    for record in records:  # schedule order, never file order
        entry = by_record.get(record.key)
        if entry is None:
            continue
        result.entries[record.key] = entry
        reconcile_entry(result, record, positions[record.key], entry,
                        events_by_record.get(record.key, []), run_id=run_id,
                        identities=identities, store=store, grammar=grammar, ledger=ledger)
    head = None
    try:
        head = read_head(directory)
    except EvidenceError as error:
        result.sealing.append(str(error))
    if head is None:
        result.sealing.append("the run's custody is not sealed")
        return result
    # nothing is appended to custody after the seal, so a sealed ledger has no
    # torn tail: trailing bytes are not a crash to discard but unsealed content
    # the seal would silently ignore (MINOR-4 / P10)
    torn = CustodyLedger(directory).torn_tail()
    if torn:
        result.sealing.append(f"the sealed custody entries end in {torn} bytes that are not a "
                              "complete record; a sealed ledger has no torn tail")
    marker = directory / SESSIONS_DIR / ACTIVE_MARKER
    try:
        holder = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    except (OSError, UnicodeDecodeError):
        holder = None
    recomputed = head_document(run_id=run_id, identities=identities, entries=entries,
                               journal=journal, scheduled=len(records), at=head.get("at", ""),
                               sealed_by=lifecycle.sealing_session(journal, holder=holder))
    if head.get("seal") != str(sha256_document({k: v for k, v in head.items() if k != "seal"})):
        result.sealing.append("the custody head does not recompute its own seal")
    if head.get("custody") != recomputed["custody"]:
        result.sealing.append("the sealed entries digest is not the entries on disk (R5)")
    if head.get("sessions_digest") != recomputed["sessions_digest"]:
        result.sealing.append("the sealed session history is not the journal's (R15/OD-02)")
    if head.get("sealed_by") != recomputed["sealed_by"]:
        result.sealing.append(
            f"the custody head names {head.get('sealed_by')!r} as the sealing session; the "
            f"evidence shows {recomputed['sealed_by']!r} held the run when it was sealed "
            "(the run was sealed by another session than the head records)"
        )
    if head.get("identities") != recomputed["identities"] or head.get("run") != run_id:
        result.sealing.append("the custody head is sealed against another run or lock")
    if head.get("entries") != len(entries) or head.get("scheduled") != len(records):
        result.sealing.append("the custody head does not count the evidence it seals")
    # the head is the seal; RUN_SEALED is its narrative and, when it was
    # journaled (a crash between the two leaves it absent), tells the same seal
    sealed_events = [event for event in journal if event["event"] == ev.RUN_SEALED]
    if len(sealed_events) > 1:
        result.sealing.append("the journal records RUN_SEALED more than once")
    for event in sealed_events:
        for name in ("seal", "custody", "entries"):
            if event.get(name) != head.get(name):
                result.sealing.append(
                    f"RUN_SEALED records {name} {event.get(name)!r}; the custody head, "
                    f"which is the seal, records {head.get(name)!r}"
                )
    return result


def reconcile_entry(result: Reconciliation, record: ExecutionRecord, position: int,
                    entry: Mapping, events: Sequence[Mapping], *, run_id: str,
                    identities: Mapping[str, str], store: ArtifactStore,
                    grammar: RunContext, ledger: set) -> None:
    """Recompute everything ONE accepted record rests on, from the bytes.

    Split out of `reconcile` because it answers a question that is also asked
    before a run is touched at all: does the evidence this record was accepted
    on still reconcile? A resume preflight asks it of a prefix, a seal asks it
    of a finished run, and both must get the same answer for the same bytes —
    so there is one implementation, not two (R7/OD-04).
    """
    where = f"custody {record.key}"
    if entry["run"] != run_id:
        result.membership.append(f"{where}: written for run {entry['run']!r}")
    if entry["design"] != identities["design"] or entry["schedule"] != identities["schedule"]:
        result.membership.append(f"{where}: bound to another design or schedule (R18)")
    if entry["cell"] != record.cell.key or entry["replicate"] != record.replicate \
            or entry["position"] != position:
        result.membership.append(f"{where}: does not describe this scheduled record")
    if entry["artifact"] != artifact_name(position):
        result.integrity.append(f"{where}: names another record's artifact")
    if entry["artifact_content"] != entry["response"]:
        result.integrity.append(f"{where}: stored content is not the response returned")
    try:
        content = store.path(entry["artifact"]).read_bytes()
    except OSError as error:
        result.integrity.append(f"{where}: its artifact cannot be read ({error})")
    else:
        if str(content_identity(content).digest) != entry["artifact_content"]:
            result.integrity.append(
                f"{where}: the artifact on disk is not the one custody accepted (R13)"
            )
    if not events:
        result.binding.append(f"{where}: the journal records no attempt for it")
    else:
        # rebuild the whole chain from the journal and the bytes, then
        # compare it with what custody sealed: R1's durable intent, R3's
        # single attempt, R4's digests and R38's execution binding are all
        # recomputed, never taken on custody's word.
        try:
            chain = recompute_chain(record.key, position, events, store,
                                    origin=entry["origin"], context=grammar)
        except EvidenceError as error:
            result.binding.append(f"{where}: {error}")
        else:
            for key in ("attempt", "request", "actual_execution", "execution",
                        "response", "artifact", "artifact_content"):
                if chain[key] != entry.get(key):
                    result.binding.append(
                        f"{where}: the evidence no longer produces the sealed {key} (R38)"
                    )
            if chain["derivation"] != entry.get("derivation"):
                result.binding.append(f"{where}: the recorded derivation was changed (R41)")
    if entry["session"] not in ledger:
        result.sessions.append(f"{where}: session {entry['session']!r} is not in the "
                               "session ledger (R15)")
    # the session custody names must be the session that actually wrote the
    # attempt — except for a RECOVERED entry, whose whole point is that an
    # operator session accepted what another session had written (R16).
    wrote = {event.get("session") for event in events}
    if entry["origin"] != RECOVERED and wrote and wrote != {entry["session"]}:
        result.sessions.append(
            f"{where}: custody says session {entry['session']!r} but the attempt was "
            f"written by {sorted(str(s) for s in wrote)} (R18/R38)"
        )
    if entry["origin"] == RECOVERED:
        result.recovered.append(record.key)
        if not str(entry.get("operator_decision", "")).strip():
            result.sessions.append(f"{where}: RECOVERED without an operator decision (R16)")
