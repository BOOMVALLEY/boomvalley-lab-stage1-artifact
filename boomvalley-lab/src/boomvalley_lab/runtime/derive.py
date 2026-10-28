"""Deriving a run from a parent package — the same execution path, one hop.

A derived record is realised exactly like any other record: durable intent,
one attempt, a fact-reporting component, persist, read back, custody. The only
difference is what answers: instead of a provider adapter, a transform reads
ONE accepted parent artifact and returns the child bytes, reporting what it
did as a derivation record (R41).

    declared derivation (lock)  -> which stage, which parent cell, which transform
    parent package (evidence)   -> the accepted parent entry and its bytes
    transform.apply             -> the child bytes
    derivation record           -> parent seal/run/design/cell/record/digest
                                   + the transform that actually ran

One read, verified, consumed
----------------------------
The parent bytes are read ONCE, through the store, which verifies them in
memory against the digest custody accepted — and those exact bytes are what
the transform is handed and what the derivation record is computed from:

    verify A  ->  consume A

Not:

    verify A  ->  reopen the path  ->  consume B

A second read is a second object. Between a check and a re-open the file can
change, and then the sealed provenance says one thing while the child was
computed from another — with nothing left on disk to show it, because the
record still names the digest that was verified. The parent digest in the
record is therefore taken from the bytes that went into the transform, not
copied from the custody entry's claim: the two agree by construction rather
than by assumption (R41, OD-06 — exact persisted raw bytes).

This is not a workflow engine: one child, one parent, one hop, no graph, no
scheduling, no fan-in or fan-out. A record whose parent cannot be resolved
unambiguously in the evidence handed in is refused — never guessed, never
"the latest".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.custody.derivation import derivation_document
from boomvalley_lab.custody.packages import Package, gather
from boomvalley_lab.declare.cellspace import Cell, ExecutionRecord
from boomvalley_lab.declare.experiment import Experiment
from boomvalley_lab.declare.rules import DerivationExpected
from boomvalley_lab.identity.kinds import ArtifactContentIdentity
from boomvalley_lab.lineage.parents import parent_records
from boomvalley_lab.lineage.transform import Transform
from boomvalley_lab.runtime.adapter import AdapterRequest, AdapterResponse
from boomvalley_lab.runtime.executor import ExecutionSummary, execute
from boomvalley_lab.runtime.run import Run
from boomvalley_lab.store.artifacts import ArtifactRef, content_identity

TRANSFORM_PROVENANCE = "boomvalley-lab-transform-1"

#: how a derived record's parent is chosen. Replaceable only to TEST that a
#: parent other than the declared one is refused by R43 — never as a feature.
ParentChoice = Callable[[Cell, DerivationExpected, Experiment], Cell]


def declared_parent(cell: Cell, expected: DerivationExpected, experiment: Experiment) -> Cell:
    return expected.parent_of(cell, experiment.factors)


def parent_record_key(parent: Cell, record: ExecutionRecord) -> str:
    """One hop, same replicate: the parent realisation of this child record."""
    return f"{parent.key}#r{record.replicate}"


def derivation_payload(record: ExecutionRecord) -> dict:
    return {"cell": record.cell.key, "replicate": record.replicate}


class DerivingAdapter:
    """Answers a record by transforming its one declared parent."""

    def __init__(self, transform: Transform, packages: Mapping[str, Package],
                 experiment: Experiment, *, choose_parent: ParentChoice = declared_parent) -> None:
        self.transform = transform
        self.packages = packages
        self.experiment = experiment
        self._choose = choose_parent
        self.max_attempts = 1
        self.intended = {"model_identity": transform.identity,
                         "adapter_provenance": TRANSFORM_PROVENANCE}
        self.derived: list[str] = []

    def call(self, request: AdapterRequest) -> AdapterResponse:
        self.derived.append(request.record)
        cell = self.experiment.cells.by_key()[request.payload["cell"]]
        expected = _expectation(self.experiment, cell)
        record = ExecutionRecord(cell, request.payload["replicate"])
        parent_cell = self._choose(cell, expected, self.experiment)
        key = parent_record_key(parent_cell, record)
        holders = parent_records(self.packages, key)
        if len(holders) != 1:
            raise ExecutionError(
                f"{request.record}: {len(holders)} accepted parent realisations of {key} were "
                "handed in; a derivation needs exactly one, and never 'the latest'"
            )
        package, entry = holders[0]
        # one read, verified in memory against the digest custody accepted. The
        # store refuses bytes that are not that digest, so a file swapped after
        # the parent package was verified cannot reach the transform.
        reference = ArtifactRef(
            entry["artifact"],
            ArtifactContentIdentity(Digest.parse(entry["artifact_content"])),
        )
        content = package.store.read(reference)
        # and the record names the digest of what was CONSUMED, computed from
        # those same bytes, rather than repeating the entry's claim about them
        consumed = str(content_identity(content).digest)
        child = self.transform.apply(content, dict(request.payload))
        record_document = derivation_document(
            stage=expected.parent_stage,
            parent={"seal": package.seal, "run": package.run,
                    "design": package.identities["design"], "cell": entry["cell"],
                    "record": entry["record"], "artifact_content": consumed},
            transform={"identity": self.transform.identity, "version": self.transform.version},
        )
        return AdapterResponse(content=child, model_identity=self.transform.identity,
                               adapter_provenance=TRANSFORM_PROVENANCE,
                               derivation=record_document)


def _expectation(experiment: Experiment, cell: Cell) -> DerivationExpected:
    rules = experiment.derivation_expectations
    expected = rules.lookup(cell) if rules is not None else None
    if expected is None:
        raise ExecutionError(
            f"cell {cell.key} declares no derivation; this run cannot derive it"
        )
    return expected


def derive(run: Run, transform: Transform, parents: Iterable[Path | str], *,
           clock: Callable[[], str], hook: Callable[[str], None] | None = None,
           stop_after: int | None = None) -> ExecutionSummary:
    """Realise a derived run from the parent evidence handed in."""
    packages = gather(parents)
    unusable = [p for p in packages.values() if not p.usable]
    if unusable:
        raise ExecutionError(
            f"parent evidence does not verify: {unusable[0].run or unusable[0].directory}: "
            f"{unusable[0].problems[0]}"
        )
    for record in run.records:  # refuse before a session opens
        _expectation(run.experiment, record.cell)
    adapter = DerivingAdapter(transform, packages, run.experiment)
    return execute(run, adapter, derivation_payload, clock=clock, hook=hook,
                   stop_after=stop_after)
