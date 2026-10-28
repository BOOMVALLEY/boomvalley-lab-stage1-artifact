"""The single gated analysis entry (R12) and its evidence (R14).

    analyse(run, plugin, parents=…) -> the analysis evidence document

There is one product-facing way to produce an analysis output, and it begins
by running the gate itself:

    audit (the whole eligibility gate, recomputed here)
        -> ELIGIBLE?        no  -> refused, nothing is written, nothing runs
        -> EligibleDataset  the exact rows the gate admitted, read through
                            custody's digests, never off the directory
        -> the locked analysis binding decides which plugin may run
        -> plugin.analyse(records, declared parameters)
        -> analysis evidence, bound to the DatasetIdentity it was computed from

Direction matters: evidence decides eligibility, and eligibility decides
whether analysis may run. An analysis never looks at the data and decides it
"seems fine" — no result value, size, shape or beauty can rescue an
ineligible dataset.

The output evidence is downstream: it is written under `analysis/` and never
touches the journal, the artifacts, custody, lineage or the dataset that
established the identity it is bound to.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from boomvalley_lab.analysis.eligible import EligibleDataset, admit
from boomvalley_lab.analysis.plugin import AnalysisPlugin
from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_document
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.core.versions import version_document
from boomvalley_lab.identity.kinds import AnalysisEvidenceIdentity
from boomvalley_lab.verify.gate import audit

ANALYSIS_SCHEMA = "boomvalley-lab-analysis-1"
ANALYSIS_DIR = "analysis"

#: bumped from the unversioned v1 preimage because the semantic input set
#: changed: the wall-clock stamp is no longer part of what identifies analysis
#: evidence (OD-07, OD-08). The version lives inside the preimage.
ANALYSIS_EVIDENCE_SCHEMA = "boomvalley-lab-analysis-evidence-2"

#: recorded on the document, never part of its identity (OD-07).
NON_NORMATIVE_KEYS = ("at",)


def result_name(evidence: str) -> str:
    """Content-addressed: the same analysis of the same dataset is one file."""
    return f"result-{evidence.split(':')[-1][:16]}.json"


def _binding_problems(eligible: EligibleDataset, plugin: AnalysisPlugin) -> list[str]:
    """The lock says which analysis this design pre-bound. Fail closed."""
    binding = eligible.binding
    if binding is None:
        return ["the design pre-binds no analysis, so no analysis may be recorded for it"]
    problems = []
    if getattr(plugin, "name", None) != binding["plugin"]:
        problems.append(f"the design binds analysis {binding['plugin']!r}, "
                        f"{getattr(plugin, 'name', None)!r} ran")
    declared_version = binding.get("version")
    if declared_version is not None and getattr(plugin, "version", None) != declared_version:
        problems.append(f"the design binds version {declared_version!r}, "
                        f"{getattr(plugin, 'version', None)!r} ran")
    return problems


def analyse(directory: Path | str, plugin: AnalysisPlugin, *,
            parents: Iterable[Path | str] = (), clock: Callable[[], str]) -> dict:
    """Analyse a run — only if its evidence is eligible. The one entry (R12)."""
    directory = Path(directory)
    report = audit(directory, parents=parents)
    eligible = admit(directory, report)  # refuses unless the gate says ELIGIBLE
    problems = _binding_problems(eligible, plugin)
    if problems:
        raise ExecutionError(f"analysis refused: {problems[0]}", problems=tuple(problems))
    records = eligible.records()
    result = plugin.analyse(records, dict(eligible.parameters))
    document = {
        "schema": ANALYSIS_SCHEMA,
        "versions": version_document(),
        "run": eligible.run,
        "identities": dict(eligible.identities),
        # R14: the output names the exact dataset it was computed from
        "dataset": eligible.dataset_identity,
        "eligibility": {"verdict": report.document()["eligibility"],
                        "report": str(sha256_document(report.document()))},
        "declared": dict(eligible.binding),
        # read off the plugin that ran, never off the declaration
        "actual": {"plugin": plugin.name, "version": plugin.version},
        "records": len(records),
        "result": dict(result),
        "output": str(sha256_document(dict(result))),
        "at": clock(),
    }
    evidence = str(analysis_identity(document).digest)
    path = directory / ANALYSIS_DIR / result_name(evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(document))
    except FileExistsError as error:
        raise ExecutionError(
            f"this analysis of this dataset is already recorded as {path.name}; "
            "analysis evidence is written once"
        ) from error
    return document


def analysis_preimage(document: Mapping) -> dict:
    """What identifies one analysis as evidence (OD-07).

    Everything the recorded document says about what ran, on which dataset,
    under which binding, with which result — and nothing about WHEN it was
    written down. Two runs of the same analysis over the same dataset are the
    same evidence; the hour on the clock is not an experimental fact.
    """
    # `identity_schema`, not `schema`: the analysis record carries its own
    # `schema`, and the identity's version must not be shadowed by it (OD-08).
    return {"identity_schema": ANALYSIS_EVIDENCE_SCHEMA,
            **{key: value for key, value in dict(document).items()
               if key not in NON_NORMATIVE_KEYS}}


def analysis_identity(document: Mapping) -> AnalysisEvidenceIdentity:
    """The evidence identity of one analysis: what ran, on which dataset, with
    which result — never the result bytes alone, and never the clock."""
    return AnalysisEvidenceIdentity.of_document(analysis_preimage(document))
