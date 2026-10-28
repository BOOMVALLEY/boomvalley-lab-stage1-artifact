"""Dataset identity: exactly which artifacts are analysed, under which design.

A dataset is NOT "the files in the artifact directory" (frozen R11). It is the
set of scheduled records whose evidence was accepted into custody, each bound
to the execution that produced it and the content that was stored. Its rows are
built by walking the LOCKED SCHEDULE and looking custody up — so the order in
which custody entries happen to be written cannot change the dataset, while
the declared schedule order is preserved in the rows (R9).

    same accepted evidence                  -> the same DatasetIdentity
    different membership or different       -> a different DatasetIdentity
    binding (execution, content, origin,
    lineage)
    entries written in another order        -> the same DatasetIdentity

DatasetIdentity is not ScheduleIdentity: the schedule says what must be
executed, the dataset says what was, and with what. Two runs of one locked
schedule share a schedule identity and have different dataset identities
whenever anything they recorded differs.

Responsibility (Owner decision OD-01)
-------------------------------------
DatasetIdentity identifies one experimental dataset INSTANCE: which artifacts
are analysed, under which design, BY WHICH RUN. The run is part of the
responsibility. It does not identify the contract, the executions, the
lineage, the custody seal, the provider response bytes or the artifact bytes —
each of those has its own identity kind.

Two documents, not one (#10, F-005)
-----------------------------------
`manifest` describes the dataset: everything the gate admitted and everything
an analysis is handed, including where each artifact is stored and what
custody recorded about how it got there.

`dataset_preimage` is the strictly smaller thing DatasetIdentity is computed
over. Every field in it answers one question -

    why would a different value here mean a different experimental dataset
    instance?

- run                 a different run is a different instance, whatever it
                      produced. This is the whole of F-005: two runs of one
                      lock that record byte-identical evidence are two
                      datasets, not one (OD-01, ID-F001, AF01, Sol F-06)
- design, schedule    the experimental structure and the frozen order these
                      rows were produced under
- records             how many rows the dataset has
- record, cell,
  replicate, position which scheduled realisation each row is
- artifact_content    WHICH artifact is analysed, named by its content
                      identity. A reference to ArtifactContentIdentity, never
                      the bytes: the bytes are that identity's responsibility
                      and this one only points at it (OD-06 boundary)

and everything else is deliberately absent, because it is some other
identity's responsibility:

    contract            ContractIdentity            (ID-C002)
    execution,
    actual_execution    ExecutionIdentity, provider (ID-C001, OD-05)
    lineage             LineageIdentity             (ID-C001)
    origin              custody provenance          (ID-C001)
    artifact            a storage location, not an experimental fact
    the custody seal    CustodyEvidenceIdentity

DatasetIdentity is not "the hash of all the evidence". It answers one
question, and a run that changes its provider, recovers a record by operator
decision, or derives an artifact from a different parent still analysed the
same dataset instance.

Version (OD-08): the semantic input set changed, so the identity preimage
carries `boomvalley-lab-dataset-identity-2` inside itself, and the manifest
document - which gained `run` - is `boomvalley-lab-dataset-2`. A v1 digest and
a v2 digest of the same rows can never be mistaken for one another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.identity.kinds import DatasetIdentity

#: the manifest DOCUMENT: bumped because it gained `run` (#10).
DATASET_SCHEMA = "boomvalley-lab-dataset-2"

#: the identity PREIMAGE: bumped because its semantic input set changed -
#: `run` in, and contract/execution/actual_execution/lineage/origin/artifact
#: out (OD-01, OD-08). Carried inside the preimage, never only alongside it.
DATASET_IDENTITY_SCHEMA = "boomvalley-lab-dataset-identity-2"

#: what each row binds — every value is evidence recorded during execution.
#: `lineage` is present only where a derivation produced the artifact; canonical
#: JSON omits None, so a dataset with no lineage has exactly the identity it had
#: before lineage existed, and one with lineage cannot collide with it.
ROW_KEYS = ("record", "cell", "replicate", "position", "artifact", "artifact_content",
            "execution", "actual_execution", "origin", "lineage")

#: of those, the ones that say WHICH dataset instance this is (OD-01). The
#: rest describe how the row came about, which is another identity's question.
IDENTIFYING_ROW_KEYS = ("record", "cell", "replicate", "position", "artifact_content")


def rows(records: Sequence[ExecutionRecord], entries: Mapping[str, Mapping]) -> list[dict]:
    """One row per scheduled record, in schedule order. Refuses a partial set."""
    missing = [record.key for record in records if record.key not in entries]
    if missing:
        raise EvidenceError(
            f"the dataset is not complete: {len(missing)} scheduled record(s) have no "
            f"accepted custody evidence, the first is {missing[0]}"
        )
    return [{key: entries[record.key].get(key) for key in ROW_KEYS} for record in records]


def manifest(identities: Mapping[str, str], dataset_rows: Sequence[Mapping],
             *, run: str) -> dict:
    """What the gate admitted and an analysis is handed. Not the preimage."""
    return {
        "schema": DATASET_SCHEMA,
        "run": run,
        "contract": identities["contract"],
        "design": identities["design"],
        "schedule": identities["schedule"],
        "records": len(dataset_rows),
        "rows": [dict(row) for row in dataset_rows],
    }


def dataset_preimage(dataset_manifest: Mapping) -> dict:
    """What identifies this dataset INSTANCE, and nothing else (OD-01, OD-08).

    Built by selection, not by exclusion: a field arrives here only because
    someone could say why a different value would make it a different dataset.
    Anything added to the manifest later is outside the identity until that
    question is answered for it.
    """
    return {
        "identity_schema": DATASET_IDENTITY_SCHEMA,
        "run": dataset_manifest["run"],
        "design": dataset_manifest["design"],
        "schedule": dataset_manifest["schedule"],
        "records": dataset_manifest["records"],
        "rows": [{key: row.get(key) for key in IDENTIFYING_ROW_KEYS}
                 for row in dataset_manifest["rows"]],
    }


def dataset_identity(dataset_manifest: Mapping) -> DatasetIdentity:
    return DatasetIdentity.of_document(dataset_preimage(dict(dataset_manifest)))
