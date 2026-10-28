"""custody-entry-2 for generalized Episode/Step/Call execution.

The old custody contract is intentionally not reinterpreted: it is tied to
ExecutionRecord(cell, replicate, position).  This version keeps the same core
principle — "stored" is not "accepted evidence" — but binds one K0 actor call.

The accepted call chain is intent -> transport -> returned -> persisted
(BVL-REC-092).  custody-entry-2 was amended to bind the TRANSPORT_STARTED
sequence before any scientific run produced custody-entry-2 evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import CanonicalisationError, canonical_json
from boomvalley_lab.core.digest import Digest, sha256_bytes
from boomvalley_lab.core.errors import EvidenceError, ExecutionError, IdentityError
from boomvalley_lab.core.layout import ARTIFACT_DIR
from boomvalley_lab.identity.kinds import ArtifactContentIdentity, RequestIdentity
from boomvalley_lab.journal.log import AppendOnlyLog
from boomvalley_lab.kernel.identity import CallIdentity, CustodyEntryIdentity
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CALL_PERSISTED,
    CALL_RETURNED,
    CUSTODY_ACCEPTED,
    TRANSPORT_STARTED,
    Journal2,
)
from boomvalley_lab.kernel.request_store import RequestRefV2, RequestStoreV2
from boomvalley_lab.store.artifacts import ArtifactRef, ArtifactStore

SCHEMA = "boomvalley-lab-custody-entry-2"
RECORDED = "RECORDED"
REQUIRED = (
    "schema",
    "run",
    "episode",
    "step",
    "round",
    "call",
    "request",
    "response",
    "artifact",
    "journal_sequences",
    "custody_state",
)

_REQUEST_REF_SCHEMA = "boomvalley-lab-request-ref-2"
_RECORDED_CHAIN = [CALL_INTENT_RECORDED, TRANSPORT_STARTED, CALL_RETURNED, CALL_PERSISTED]
_SEQUENCE_KEYS = ("intent", "transport", "returned", "persisted")
_ACCEPTED_CHAIN = [*_RECORDED_CHAIN, CUSTODY_ACCEPTED]
_CALL_SCOPE = ("run", "episode", "step", "round", "call")


def _check_entry(value: Any, where: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED):
        raise EvidenceError(f"{where}: custody-entry-2 has exactly {list(REQUIRED)}")
    if value.get("schema") != SCHEMA:
        raise EvidenceError(f"{where}: custody-entry-2 schema is exactly {SCHEMA!r}")
    if value.get("custody_state") != RECORDED:
        raise EvidenceError(f"{where}: custody state is exactly {RECORDED!r}")
    if not isinstance(value.get("round"), int) or isinstance(value.get("round"), bool):
        raise EvidenceError(f"{where}: round is an integer")
    sequence = value.get("journal_sequences")
    if (
        not isinstance(sequence, Mapping)
        or set(sequence) != set(_SEQUENCE_KEYS)
        or not all(
            isinstance(sequence[name], int) and not isinstance(sequence[name], bool)
            for name in sequence
        )
    ):
        raise EvidenceError(f"{where}: journal_sequences is closed and integer-valued")
    ordered = [sequence[name] for name in _SEQUENCE_KEYS]
    if ordered != sorted(set(ordered)):
        raise EvidenceError(
            f"{where}: journal sequence order is intent < transport < returned < persisted"
        )
    return dict(value)


def _entry_call(entry: dict) -> Any:
    return entry["call"]


def _entry_identity(entry: dict) -> str:
    return canonical_json(CustodyEntryIdentity.of_payload(entry).document())


class CustodyLedgerV2(AppendOnlyLog):
    def __init__(self, run_directory: Path) -> None:
        super().__init__(
            Path(run_directory) / "custody-v2" / "entries.jsonl",
            _check_entry,
            "custody-v2",
        )

    def by_call(self) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for entry in self.read():
            result.setdefault(entry["call"], []).append(entry)
        return result

    def of_call(self, call_key: str) -> list[dict]:
        """The entries of one call: ``by_call().get(call_key, [])`` without the scan."""

        return self.selected("call", _entry_call, call_key)

    def of_identity(self, identity: Any) -> list[dict]:
        """The entries whose CustodyEntryIdentity document is *identity*."""

        try:
            wanted = canonical_json(identity)
        except (CanonicalisationError, TypeError, ValueError):
            return []
        return self.selected("identity", _entry_identity, wanted)


def call_artifact_name(call: CallIdentity) -> str:
    """The storage member that holds the persisted response of *call*."""

    return f"call-{call.digest.hex}.bin"


def call_from_key(call_key: Any) -> CallIdentity:
    prefix = f"{CallIdentity.KIND}:"
    if not isinstance(call_key, str) or not call_key.startswith(prefix):
        raise EvidenceError(f"custody-entry-2: not a call identity: {call_key!r}")
    return CallIdentity(Digest.parse(call_key[len(prefix) :]))


def _request_ref(document: Any) -> RequestRefV2:
    if (
        not isinstance(document, Mapping)
        or set(document) != {"schema", "name", "identity", "size"}
        or document["schema"] != _REQUEST_REF_SCHEMA
    ):
        raise EvidenceError("custody-entry-2: malformed request reference")
    identity = document["identity"]
    if (
        not isinstance(identity, Mapping)
        or set(identity) != {"kind", "digest"}
        or identity["kind"] != RequestIdentity.KIND
    ):
        raise EvidenceError("custody-entry-2: malformed RequestIdentity")
    size = document["size"]
    if isinstance(size, bool) or not isinstance(size, int):
        raise EvidenceError("custody-entry-2: request size is an integer")
    request = RequestIdentity(Digest.parse(str(identity["digest"])))
    # the member is the one its identity names, inside requests-v2 (SV-13 P-01): any
    # other name is a path the journal chose, read from wherever it points
    if document["name"] != f"request-{request.digest.hex}.json":
        raise EvidenceError(
            "custody-entry-2: request reference names another member than its identity"
        )
    return RequestRefV2(document["name"], request, size)


def _artifact_ref(document: Any) -> ArtifactRef:
    if not isinstance(document, Mapping) or set(document) != {"name", "content"}:
        raise EvidenceError("custody-entry-2: malformed artifact reference")
    return ArtifactRef(
        str(document["name"]),
        ArtifactContentIdentity(Digest.parse(str(document["content"]))),
    )


def _call_events(journal: Journal2, call_key: str) -> list[dict]:
    return journal.of_call(call_key)


def _recompute_entry(
    *,
    call: CallIdentity,
    events: list[dict],
    requests: RequestStoreV2,
    artifacts: ArtifactStore,
) -> dict:
    """Recompute custody-entry-2 from journal, request and artifact evidence.

    *events* is exactly the intent/transport/returned/persisted chain of *call*.  Every
    reference is re-read and re-digested; nothing is trusted because it was
    written down earlier.
    """

    call_key = str(call)
    intent, transport, returned, persisted = events
    for event in (transport, returned, persisted):
        for field in _CALL_SCOPE:
            if event[field] != intent[field]:
                raise EvidenceError(
                    f"custody-v2 refuses {call_key}: {event['event']} {field} "
                    "contradicts the call intent"
                )

    requests.read(_request_ref(intent["request"]))

    artifact = _artifact_ref(persisted["artifact"])
    if artifact.name != call_artifact_name(call):
        raise EvidenceError(
            f"custody-v2 refuses {call_key}: persisted artifact {artifact.name!r} "
            "is not this call's response member"
        )
    content = artifacts.read(artifact)
    response = returned["response"]
    if not isinstance(response, Mapping) or response.get("content_digest") != str(
        sha256_bytes(content)
    ):
        raise EvidenceError(
            f"custody-v2 refuses {call_key}: artifact bytes are not the returned response"
        )

    return {
        "schema": SCHEMA,
        "run": intent["run"],
        "episode": intent["episode"],
        "step": intent["step"],
        "round": intent["round"],
        "call": call_key,
        "request": intent["request"],
        "response": returned["response"],
        "artifact": persisted["artifact"],
        "journal_sequences": {
            "intent": intent["sequence"],
            "transport": transport["sequence"],
            "returned": returned["sequence"],
            "persisted": persisted["sequence"],
        },
        "custody_state": RECORDED,
    }


def read_intent_request_v2(intent: Mapping[str, Any], requests: RequestStoreV2) -> bytes:
    """Re-read and re-verify the request-2 bytes a CALL_INTENT_RECORDED binds."""

    return requests.read(_request_ref(intent["request"]))


def recompute_recorded_call_v2(
    *,
    call: CallIdentity,
    events: list[dict],
    requests: RequestStoreV2,
    artifacts: ArtifactStore,
) -> dict:
    """Read-only recompute of the custody-entry-2 a recorded chain would yield."""

    if [event["event"] for event in events] != _RECORDED_CHAIN:
        raise EvidenceError(
            f"custody-v2 recompute for {call}: expected intent/transport/returned/persisted"
        )
    return _recompute_entry(call=call, events=events, requests=requests, artifacts=artifacts)


def accept_call_v2(
    *,
    run_directory: Path,
    run_id: str,
    call: CallIdentity,
    journal: Journal2,
    requests: RequestStoreV2,
    artifacts: ArtifactStore,
) -> tuple[dict, CustodyEntryIdentity]:
    """Recompute and accept one completed call evidence chain.

    A persisted response is not complete until this returns: the
    request/journal/artifact chain is recomputed, appended to custody-v2 and
    acknowledged by CUSTODY_ACCEPTED.
    """

    ledger = CustodyLedgerV2(run_directory)
    call_key = str(call)
    if ledger.torn_tail() or journal.torn_tail():
        # Appending after unacknowledged bytes would merge them into the next
        # record and corrupt the log (T0-010).
        raise ExecutionError(f"custody-v2 refuses {call_key}: a log has a torn tail")
    if ledger.of_call(call_key):
        raise ExecutionError(f"custody-v2 already accepts call {call_key}")

    events = _call_events(journal, call_key)
    kinds = [event["event"] for event in events]
    if kinds != _RECORDED_CHAIN:
        raise EvidenceError(
            f"custody-v2 refuses {call_key}: "
            f"expected intent/transport/returned/persisted, got {kinds}"
        )
    if events[0]["run"] != run_id:
        raise EvidenceError(f"custody-v2 refuses {call_key}: call belongs to another run")

    entry = _recompute_entry(call=call, events=events, requests=requests, artifacts=artifacts)
    accepted = ledger.append(entry)
    identity = CustodyEntryIdentity.of_payload(accepted)

    journal.append_event(
        CUSTODY_ACCEPTED,
        run=run_id,
        episode=entry["episode"],
        step=entry["step"],
        round=entry["round"],
        call=call_key,
        artifact=entry["artifact"],
        custody=identity.document(),
    )
    return accepted, identity


def verify_call_v2(
    *,
    run_directory: Path,
    call: CallIdentity,
    journal: Journal2,
    requests: RequestStoreV2,
    artifacts: ArtifactStore,
) -> CustodyEntryIdentity:
    """Recompute one accepted call chain from durable evidence.

    No stored digest is trusted merely because custody once accepted it.
    """

    call_key = str(call)
    entries = CustodyLedgerV2(run_directory).of_call(call_key)
    if len(entries) != 1:
        raise EvidenceError(
            f"custody-v2 verification needs exactly one entry for {call_key}; "
            f"found {len(entries)}"
        )
    entry = entries[0]
    identity = CustodyEntryIdentity.of_payload(entry)

    events = _call_events(journal, call_key)
    kinds = [event["event"] for event in events]
    if kinds != _ACCEPTED_CHAIN:
        raise EvidenceError(
            f"custody-v2 verification for {call_key}: expected {_ACCEPTED_CHAIN}, got {kinds}"
        )
    *chain, accepted = events

    for field in _CALL_SCOPE:
        if accepted[field] != chain[0][field]:
            raise EvidenceError(
                f"custody-v2 verification for {call_key}: CUSTODY_ACCEPTED {field} "
                "contradicts the call intent"
            )
    if accepted["custody"] != identity.document():
        raise EvidenceError(f"custody-v2 verification for {call_key}: custody identity changed")
    if accepted["artifact"] != chain[-1]["artifact"]:
        raise EvidenceError(f"custody-v2 verification for {call_key}: accepted artifact changed")

    try:
        expected_entry = _recompute_entry(
            call=call, events=chain, requests=requests, artifacts=artifacts
        )
    except EvidenceError as error:
        raise EvidenceError(f"custody-v2 verification for {call_key}: {error}") from error
    if entry != expected_entry:
        raise EvidenceError(
            f"custody-v2 verification for {call_key}: accepted chain no longer recomputes"
        )
    return identity


@dataclass(frozen=True)
class CustodyReconciliationV2:
    """Run-level reconciliation of persisted responses against custody-v2.

    ``accepted`` calls recompute end to end.  ``pending`` calls have a
    persisted response that custody never accepted: they are not complete
    evidence.  ``problems`` are contradictions that no resume may skip past.
    """

    accepted: tuple[str, ...]
    pending: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.pending and not self.problems


def reconcile_custody_v2(run_directory: Path) -> CustodyReconciliationV2:
    """Recompute every persisted call of a run against its custody evidence."""

    run_directory = Path(run_directory)
    journal = Journal2(run_directory)
    requests = RequestStoreV2(run_directory)
    artifacts = ArtifactStore(run_directory)

    try:
        events = journal.read()
        ledger = CustodyLedgerV2(run_directory).by_call()
    except EvidenceError as error:
        return CustodyReconciliationV2((), (), (str(error),))

    persisted = {event["call"] for event in events if event["event"] == CALL_PERSISTED}
    acknowledged = {event["call"] for event in events if event["event"] == CUSTODY_ACCEPTED}
    accepted: list[str] = []
    pending: list[str] = []
    problems: list[str] = []
    bound: set[str] = set()

    for call_key in sorted(persisted | acknowledged | set(ledger)):
        try:
            call = call_from_key(call_key)
        except (EvidenceError, IdentityError, ValueError) as error:
            problems.append(f"{call_key}: {error}")
            continue
        bound.add(call_artifact_name(call))
        if call_key not in ledger and call_key not in acknowledged:
            pending.append(call_key)
            continue
        try:
            verify_call_v2(
                run_directory=run_directory,
                call=call,
                journal=journal,
                requests=requests,
                artifacts=artifacts,
            )
        except (EvidenceError, IdentityError, OSError, ValueError) as error:
            problems.append(str(error))
            continue
        accepted.append(call_key)

    artifact_root = run_directory / ARTIFACT_DIR
    if artifact_root.is_dir():
        for path in sorted(artifact_root.glob("call-*.bin")):
            if path.name not in bound:
                problems.append(f"response member {path.name} has no persisted call")

    return CustodyReconciliationV2(tuple(accepted), tuple(pending), tuple(problems))
