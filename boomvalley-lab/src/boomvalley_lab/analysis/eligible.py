"""`EligibleDataset` — the only thing an analysis is ever handed (R12).

It exists only where the gate said ELIGIBLE. It carries the dataset the gate
admitted (rows in locked schedule order, with their content digests), the
identities that dataset belongs to, and the analysis the lock pre-bound.

Reading a record goes through the recorded digest, so an artifact changed
after the audit cannot reach an analysis even inside the same process.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.analysis.plugin import AnalysisRecord
from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.dataset.manifest import dataset_identity
from boomvalley_lab.identity.kinds import ArtifactContentIdentity
from boomvalley_lab.store.artifacts import ArtifactRef, ArtifactStore


@dataclass(frozen=True)
class EligibleDataset:
    run: str
    identities: Mapping[str, str]
    dataset: Mapping
    dataset_identity: str
    binding: Mapping | None
    coordinates: Mapping[str, Mapping[str, str]]
    store: ArtifactStore

    @property
    def parameters(self) -> Mapping:
        return (self.binding or {}).get("parameters") or {}

    def records(self) -> list[AnalysisRecord]:
        """The admitted rows, read through custody's digests, in schedule order."""
        found = []
        for row in self.dataset["rows"]:
            ref = ArtifactRef(row["artifact"],
                              ArtifactContentIdentity(Digest.parse(row["artifact_content"])))
            try:
                content = self.store.read(ref)
            except (OSError, EvidenceError) as error:
                raise ExecutionError(
                    f"{row['record']}: the admitted artifact is no longer the one the gate "
                    f"accepted ({error})"
                ) from error
            found.append(AnalysisRecord(record=row["record"], cell=row["cell"],
                                        replicate=row["replicate"],
                                        coordinates=self.coordinates.get(row["cell"], {}),
                                        content=content))
        return found


def admit(directory: Path, report) -> EligibleDataset:
    """Turn a VERIFIED audit into an analysable dataset, or refuse (R12)."""
    if not report.eligible or report.dataset is None:
        violations = report.violations()
        first = f"{violations[0].step}: {violations[0].reasons[0]}" if violations else "no dataset"
        raise ExecutionError(
            f"run {report.run} is NOT_ELIGIBLE; analysis is reachable only through the "
            f"eligibility gate ({first})",
            problems=tuple(f"{f.step}: {r}" for f in violations for r in f.reasons),
        )
    coordinates = {row["cell"]: _coordinates(row["cell"]) for row in report.dataset["rows"]}
    return EligibleDataset(
        run=report.run,
        identities=dict(report.identities),
        dataset=report.dataset,
        dataset_identity=str(dataset_identity(report.dataset).digest),
        binding=report.binding,
        coordinates=coordinates,
        store=ArtifactStore(Path(directory)),
    )


def _coordinates(cell: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in cell.split("/"))


def eligible_records(rows: Sequence[Mapping]) -> list[str]:
    return [row["record"] for row in rows]
