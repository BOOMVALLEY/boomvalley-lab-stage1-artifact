"""A sealed run, opened as evidence somebody else may rely on.

A parent package is not a directory of files: it is a run whose lock verifies,
whose custody is sealed, and whose custody reconciles with its own journal and
artifacts. Loading it applies custody's OWN verification (R42) — evidence that
does not verify for its own run cannot become the parent of another.

Two questions that look alike and are not
-----------------------------------------
    LINEAGE ADMISSIBILITY      may this evidence be a parent at all?
    SCIENTIFIC ELIGIBILITY     may this run's dataset enter analysis?

They are decided by different things, for different reasons, and one does not
follow from the other:

    Scientific eligibility is NOT recursively inherited as lineage
    admissibility. A parent that the gate found NOT_ELIGIBLE — a declared
    execution that did not match, an artifact provenance rule that failed — is
    still evidence of what it actually produced. If its custody verifies, its
    history is consistent and it was not abandoned, a child may derive from it
    and answer for its own eligibility separately (refined OD-03).

    ABORTED is lineage-inadmissible. A run that reached a terminal abort was
    abandoned; it is not a realisation anything may be built on, however well
    its remaining evidence verifies (OA-01).

    NOT_ELIGIBLE alone does not make an otherwise integrity-valid parent
    unusable.

So what this module decides is admissibility — sealed, internally consistent,
reconciling, and not abandoned — and nothing about whether the parent's own
science held up. It never calls the eligibility gate, and it must not start:
`if not parent.eligible: refuse` would quietly make every ancestor's science a
precondition for every descendant's lineage.

Scope, unchanged: one parent, one hop. No ancestor traversal, no recursive
evaluation, no graph.

This lives in `custody` because it is custody evidence being read; `lineage`
decides what to do with it (resolve a recorded parent), and the runtime reads
parent bytes through it rather than through the filesystem.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.core.layout import LOCK_FILE, RUN_FILE
from boomvalley_lab.core.strict_json import MalformedJSON, load_file
from boomvalley_lab.core.verdict import Verdict
from boomvalley_lab.custody.entries import CustodyLedger
from boomvalley_lab.custody.seal import read_head, reconcile
from boomvalley_lab.declare.experiment import load
from boomvalley_lab.identity.lock import verify_lock
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import opening
from boomvalley_lab.journal.log import Journal
from boomvalley_lab.store.artifacts import ArtifactStore


@dataclass(frozen=True)
class Package:
    """One sealed run: its identities, its seal and what it accepted."""

    directory: Path
    run: str
    identities: Mapping[str, str]
    seal: str
    entries: Mapping[str, Mapping]  # record key -> accepted custody entry
    store: ArtifactStore
    problems: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """May this evidence be relied on as a parent? (admissibility, not science)"""
        return not self.problems


def load_package(directory: Path | str) -> Package:
    directory = Path(directory)
    try:
        lock_document = load_file(directory / LOCK_FILE)
        run_document = load_file(directory / RUN_FILE)
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"{directory} is not a readable run: {error}") from error
    for name, document in ((LOCK_FILE, lock_document), (RUN_FILE, run_document)):
        if not isinstance(document, Mapping):
            raise EvidenceError(f"{directory}: {name} is not a JSON object")
    identities = dict(lock_document.get("identities") or {})
    run_id = run_document.get("run", "")
    store = ArtifactStore(directory)
    violations = tuple(f"{f.step}: {r}" for f in verify_lock(lock_document)
                       if f.verdict is Verdict.VIOLATED for r in f.reasons)
    if violations:
        return Package(directory, run_id, identities, "", {}, store, violations)
    experiment = load(lock_document["declaration"])
    journal = Journal(directory).read()
    head = read_head(directory)
    if head is None:
        return Package(directory, run_id, identities, "", {}, store,
                       (f"run {run_id} is not sealed; only sealed evidence may be relied on",))
    check = reconcile(directory, run_id=run_id, identities=identities,
                      records=experiment.records, journal=journal, store=store)
    problems = tuple([
        *abandoned(run_id, journal),
        # every way this run's own evidence can contradict itself: whether it
        # opens at all, which records it holds, in what order it ran them, one
        # attempt at a time, who wrote them, the bytes, the execution binding
        # and the seal. A parent whose history could not have happened is not
        # a parent — and a journal the runtime will not open is such a history.
        *opening.problems(journal, run_id),
        *check.membership, *check.order, *check.serialization, *check.lifecycle,
        *check.integrity, *check.binding, *check.sessions, *check.sealing,
    ])
    entries = {entry["record"]: entry for entry in CustodyLedger(directory).read()}
    return Package(directory, run_id, identities, head["seal"], entries, store, problems)


def abandoned(run_id: str, journal: Iterable[Mapping]) -> list[str]:
    """Was this run abandoned? (OA-01 — lineage admissibility, not eligibility)

    Read off the journal's own terminal events, which is where a run records
    that it stopped for good. Not from a stored status field and not from
    anything the package says about itself: a writer that could declare its
    own parent usable would be the whole finding.

    An abort is not a quality judgement to be weighed against the rest of the
    evidence. Custody may reconcile perfectly, every digest may recompute, the
    seal may be intact — and the run was still abandoned, so nothing may be
    built on it.
    """
    if not any(event["event"] == ev.RUN_ABORTED for event in journal):
        return []
    return [f"run {run_id} reached ABORTED; an abandoned run is not lineage evidence, "
            "whatever else about it verifies (OA-01)"]


def gather(directories: Iterable[Path | str]) -> dict[str, Package]:
    """The packages handed to a verifier, by seal.

    Seals are content-addressed: two identical manifests are the same evidence
    and collapse to one entry. A re-run has a different seal and stays a
    different parent — there is no "latest".
    """
    packages: dict[str, Package] = {}
    for index, directory in enumerate(directories):
        package = load_package(directory)
        packages[package.seal or f"unusable-{index}"] = package
    return packages
