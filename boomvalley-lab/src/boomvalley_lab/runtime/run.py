"""A run: one execution realisation of one verified experiment lock.

Layout (a storage convention, never identity or provenance):

    <run>/lock.json        the lock, canonical bytes, written once
    <run>/run.json         {run, lock identities}, written once
                           (INPUT_LOCKED: {input, lock, run})
    <run>/input.json       INPUT_LOCKED runs only: the complete Input Lock
    <run>/preflight/       INPUT_LOCKED runs only: GNDCRW preflight evidence
    <run>/journal.jsonl    every event (journal.log)
    <run>/sessions/ACTIVE  exclusive marker of the one active session (R8)
    <run>/artifacts/       persisted artifacts (store.artifacts)
    <run>/custody/         accepted custody entries and the seal (custody)

States: OPEN (created, not terminal) · ABORTED (terminal; never executed
again — a replacement is a new run with a new run id, never pooled) · SEALED
(every scheduled record is in custody and the custody head is written:
terminal, and the only state in which the run's evidence is complete).

The lock is authoritative: a run is created only from a lock that verifies
(every identity recomputes), and it is re-verified from disk every time the
run is opened. Design semantics are never re-derived from anything else.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes, canonical_json
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.layout import INPUT_FILE, LOCK_FILE, PREFLIGHT_DIR, RUN_FILE
from boomvalley_lab.core.strict_json import MalformedJSON, load_file
from boomvalley_lab.core.verdict import Verdict
from boomvalley_lab.custody.seal import head_path
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.declare.experiment import Experiment, load
from boomvalley_lab.declare.names import check_name
from boomvalley_lab.identity.lock import verify_lock
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import opening
from boomvalley_lab.journal.log import Journal
from boomvalley_lab.store.artifacts import ArtifactStore


class RunState(StrEnum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class InputLockArtifacts:
    """The in-memory Input Lock values `Run.create` persists (Input Contract §10.6).

    `preflight` maps a path under `preflight/` to its exact bytes, written in
    the mapping's order; `input_bytes` and `run_bytes` are the exact bytes of
    `input.json` and `run.json`; `anchor` is the INPUT_LOCK_BOUND record.
    """

    preflight: Mapping[str, bytes]
    input_bytes: bytes
    run_bytes: bytes
    anchor: Mapping[str, Any]


def opened_event(run_id: str, identities: Mapping[str, str], at: str) -> dict:
    """The RUN_OPENED record of a run over a lock with these identities."""
    return {
        "event": ev.RUN_OPENED, "run": run_id, "at": at,
        "lock_contract": identities["contract"], "lock_design": identities["design"],
        "lock_schedule": identities["schedule"],
    }


def _exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(bytes(data))
        handle.flush()
        os.fsync(handle.fileno())


def _verified(lock_document: Any) -> None:
    violations = [f for f in verify_lock(lock_document) if f.verdict is Verdict.VIOLATED]
    if violations:
        raise ExecutionError(
            f"the lock does not verify: {violations[0].step}: {violations[0].reasons[0]}",
            problems=tuple(f"{f.step}: {r}" for f in violations for r in f.reasons),
        )


@dataclass(frozen=True)
class Run:
    directory: Path
    run_id: str
    lock: dict
    experiment: Experiment

    # ---------------------------------------------------------------- create
    @classmethod
    def create(cls, directory: Path, lock_document: dict, run_id: str, *, at: str,
               input_lock: InputLockArtifacts | None = None) -> Run:
        """Create a run. With `input_lock`, an INPUT_LOCKED run (Input Contract §10.6):

            lock.json -> preflight/* -> input.json -> run.json
                      -> journal RUN_OPENED -> journal INPUT_LOCK_BOUND

        every file with exclusive create, from the caller's in-memory bytes.
        Without it, the unchanged legacy (NOT_INPUT_LOCKED) run.
        """
        check_name(run_id, "a run id")
        _verified(lock_document)
        directory = Path(directory)
        if directory.exists() and any(directory.iterdir()):
            raise ExecutionError(f"{directory} is not empty; a run directory holds one run")
        directory.mkdir(parents=True, exist_ok=True)
        _exclusive(directory / LOCK_FILE, canonical_bytes(lock_document))
        identities = lock_document["identities"]
        if input_lock is None:
            with open(directory / RUN_FILE, "x", encoding="utf-8") as handle:
                handle.write(canonical_json({"run": run_id, "lock": identities}))
        else:
            for name, data in input_lock.preflight.items():
                _exclusive(directory / PREFLIGHT_DIR / name, data)
            _exclusive(directory / INPUT_FILE, input_lock.input_bytes)
            _exclusive(directory / RUN_FILE, input_lock.run_bytes)
        Journal(directory).append(opened_event(run_id, identities, at))
        if input_lock is not None:
            Journal(directory).append(dict(input_lock.anchor))
        return cls.open(directory)

    # ------------------------------------------------------------------ open
    @classmethod
    def open(cls, directory: Path) -> Run:
        directory = Path(directory)
        try:
            lock_document = load_file(directory / LOCK_FILE)
            run_document = load_file(directory / RUN_FILE)
        except (OSError, MalformedJSON) as error:
            raise EvidenceError(f"{directory} is not a readable run: {error}") from error
        for name, document in ((LOCK_FILE, lock_document), (RUN_FILE, run_document)):
            if not isinstance(document, Mapping):
                raise EvidenceError(f"{directory}: {name} is not a JSON object")
        _verified(lock_document)
        if run_document.get("lock") != lock_document["identities"]:
            raise EvidenceError("run.json names a different lock than lock.json holds")
        journal = Journal(directory).read()
        wrong = opening.problems(journal, run_document["run"])
        if wrong:
            raise EvidenceError(f"this is not a run that can be opened: {wrong[0]}")
        return cls(directory, run_document["run"], lock_document,
                   load(lock_document["declaration"]))

    # --------------------------------------------------------------- queries
    @property
    def records(self) -> tuple[ExecutionRecord, ...]:
        """The locked schedule, materialised: every record once, in order."""
        return self.experiment.records

    @property
    def journal(self) -> Journal:
        return Journal(self.directory)

    @property
    def store(self) -> ArtifactStore:
        return ArtifactStore(self.directory)

    def events(self) -> list[dict]:
        return self.journal.read()

    def state(self) -> RunState:
        kinds = {e["event"] for e in self.events()}
        if ev.RUN_ABORTED in kinds:
            return RunState.ABORTED
        # the custody head IS the seal; the RUN_SEALED event is its narrative.
        if head_path(self.directory).exists() or ev.RUN_SEALED in kinds:
            return RunState.SEALED
        return RunState.OPEN
