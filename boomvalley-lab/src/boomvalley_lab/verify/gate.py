"""The minimal eligibility gate — a producer-side self-check, nothing more.

It answers exactly one question:

    may this dataset enter analysis, given the locked experiment, the runtime
    evidence the run recorded, and the artifact/custody/provenance rules the
    declaration made?

It does not decide whether the experiment was worth running, whether the
construct is valid, whether a causal reading holds, or whether the numbers are
true. It is not independent assurance, a certification or a trust score
(FULLMT's boundary), and it never reads the scientific content of an artifact.

Steps (plan §12):

    1  contract_validity       the lock verifies by recomputation
    2  lock_match              this run is the run of that lock: the journal
                               opens exactly once, in the frozen opening
                               position, against those identities
    3  topology                custody membership is the locked schedule
                               exactly (R3, R9, R11) and the declared
                               denominator holds on it (R10)
    3b schedule_order          the run began its attempts in the registered
                               order — a frozen schedule is a sequence, not a
                               member list (ScheduleIdentity, R1)
    3c attempt_serialization   and it ran them one at a time: no record's
                               attempt begins before the previous one ended.
                               Sequential execution semantics; a legal
                               per-attempt grammar and a legal intent order
                               still admit an overlap neither can see
    4  custody_integrity       accepted bytes are still those bytes and the
                               seal recomputes (R2, R4, R5, R6, R13, R18)
    5  session_provenance      the session lifecycle is a legal sequence of
                               transitions, every entry's session is the one
                               that wrote it, the prior-session authorisation
                               is committed, no aborted run (R7, R8, R15, R16,
                               R18, OD-02)
    6  execution_binding       custody's execution digests still recompute
                               from the journal (R38)
    7  declared_vs_actual      R39, per covered cell
    8  artifact_provenance     R40, per covered cell, observed on the bytes
                               custody accepted — read once and bound to their
                               digest, never reopened after reconciliation
    9  parent_reconciliation   every recorded parent resolves by its exact seal
                               in the parent evidence handed in, and its cell
                               and digests match (R41 recorded, R42 resolved)
    10 declared_vs_actual_derivation   R43, per covered cell
    11 dataset_identity        the deterministic identity of what would be analysed
    12 eligibility             ELIGIBLE iff nothing above is VIOLATED
    +  input_lock              INPUT_LOCKED runs only: ILV-1..15 (minus ILV-13,
                               an installation question) recomputes from the
                               persisted input.json and preflight/ bytes

Every step reads evidence only. A declared claim that cannot be checked is
VIOLATED, never a softer state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core.digest import Digest
from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.core.layout import LOCK_FILE, RUN_FILE
from boomvalley_lab.core.strict_json import MalformedJSON, load_file
from boomvalley_lab.core.verdict import Finding, Verdict, all_hold
from boomvalley_lab.custody.derivation import actual_derivation, lineage_identity
from boomvalley_lab.custody.packages import gather
from boomvalley_lab.custody.seal import Reconciliation, reconcile
from boomvalley_lab.dataset.manifest import dataset_identity, manifest, rows
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.declare.experiment import Experiment, load
from boomvalley_lab.declare.structure import denominator_expectation
from boomvalley_lab.expect.artifact import ArtifactFamily
from boomvalley_lab.expect.derivation import DerivationFamily
from boomvalley_lab.expect.execution import ExecutionFamily
from boomvalley_lab.identity.derive import denominator_document
from boomvalley_lab.identity.kinds import ArtifactContentIdentity
from boomvalley_lab.identity.lock import verify_lock
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal import opening
from boomvalley_lab.journal.log import Journal
from boomvalley_lab.lineage.parents import resolve
from boomvalley_lab.store.artifacts import ArtifactRef, ArtifactStore

AUDIT_SCHEMA = "boomvalley-lab-eligibility-1"
ELIGIBLE = "ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE"

STEPS = ("contract_validity", "lock_match", "topology", "schedule_order",
         "attempt_serialization", "custody_integrity",
         "session_provenance", "execution_binding", "declared_vs_actual",
         "artifact_provenance", "parent_reconciliation", "declared_vs_actual_derivation",
         "dataset_identity")

#: INPUT_LOCKED runs only (IR-07): the Input Lock verifies from the evidence.
INPUT_LOCK_STEP = "input_lock"


@dataclass(frozen=True)
class Audit:
    """One run's eligibility report: every verdict, and what was measured."""

    run: str
    identities: dict
    findings: tuple[Finding, ...]
    dataset: dict | None = None
    #: the analysis the lock pre-binds, for the one gated analysis entry (R12)
    binding: dict | None = None

    @property
    def eligible(self) -> bool:
        return all_hold(finding.verdict for finding in self.findings)

    @property
    def verdicts(self) -> dict[str, str]:
        return {finding.step: finding.verdict.value for finding in self.findings}

    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict is Verdict.VIOLATED]

    def document(self) -> dict:
        return {
            "schema": AUDIT_SCHEMA,
            "run": self.run,
            "identities": self.identities,
            "eligibility": ELIGIBLE if self.eligible else NOT_ELIGIBLE,
            "findings": [{"step": f.step, "verdict": f.verdict.value,
                          "reasons": list(f.reasons)} for f in self.findings],
            "dataset": (None if self.dataset is None
                        else {"identity": str(dataset_identity(self.dataset).digest),
                              "records": self.dataset["records"]}),
        }


def _verdict(step: str, problems: Sequence[str]) -> Finding:
    if problems:
        return Finding(step, Verdict.VIOLATED, tuple(problems))
    return Finding(step, Verdict.VERIFIED)


def _read(path: Path) -> dict:
    try:
        document = load_file(path)
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"{path.name} is unreadable: {error}") from error
    if not isinstance(document, Mapping):
        raise EvidenceError(f"{path.name} is not a JSON object")
    return document


def _topology_problems(experiment: Experiment, records: Sequence[ExecutionRecord],
                       check: Reconciliation) -> list[str]:
    problems = list(check.membership)
    if problems:
        return problems
    accepted = [record for record in records if record.key in check.entries]
    declared = denominator_document(experiment)
    for view in experiment.views:
        found = denominator_expectation(experiment.denominator, view, accepted)
        if found != declared[view.name]:
            problems.append(
                f"view {view.name!r}: the declared denominator does not hold on the "
                f"accepted dataset (R10)"
            )
    return problems


def _session_problems(check: Reconciliation, journal: Sequence[Mapping]) -> list[str]:
    problems = [*check.lifecycle, *check.sessions]
    if any(event["event"] == ev.RUN_ABORTED for event in journal):
        problems.append("the run was ABORTED; its evidence is never pooled into a dataset")
    return problems


def _family_findings(step: str, family, ruleset, experiment: Experiment,
                     evidence: Mapping[str, object], blocked: list[str]) -> list[Finding]:
    """One expectation family over the declared cells. Absent rules: NO CLAIM."""
    if ruleset is None:
        return [Finding(step, Verdict.NO_CLAIM)]
    covered = [cell for cell in experiment.cells.cells if ruleset.lookup(cell) is not None]
    if not covered:
        return [Finding(step, Verdict.NO_CLAIM)]
    if blocked:
        return [Finding(step, Verdict.VIOLATED,
                        (f"{len(covered)} cell(s) declare this claim and its evidence "
                         f"precondition failed: {blocked[0]}",))]
    findings = []
    for cell in covered:
        expected = ruleset.lookup(cell)
        observed = family.observe(evidence, cell.key)
        findings.append(family.compare(cell.key, expected.document(), observed))
    violations = [f for f in findings if f.verdict is Verdict.VIOLATED]
    reasons = tuple(f"{f.step}: {reason}" for f in violations for reason in f.reasons)
    summary = Finding(step, Verdict.VIOLATED, reasons) if violations \
        else Finding(step, Verdict.VERIFIED)
    return [summary, *findings]


def accepted_bytes(store: ArtifactStore, entry: Mapping) -> bytes:
    """The artifact custody accepted, read once and bound to its digest.

    Reconciliation reads every artifact and compares it with the digest
    custody accepted. The gate then needed those bytes again, for R40 — what
    provenance does this artifact record? — and it used to get them by
    reopening the path:

        store.path(entry["artifact"]).read_bytes()

    A second read is a second object. Between the two, the file can change,
    and then the run is admitted on evidence that was never reconciled: the
    substituted bytes decide the provenance verdict while `custody_integrity`
    still reports on the bytes that were replaced. Substituting an artifact
    that carries a foreign marker with one that does not turns NOT_ELIGIBLE
    into ELIGIBLE, which is the whole of the finding.

        verify A  ->  consume A

    So the read is bound: `store.read` hashes what it read, compares it with
    the digest custody accepted, and returns THOSE bytes. The object the
    comparison verified and the object the rule observes are the same object,
    and a mismatch is refused rather than observed (R13, R40).
    """
    reference = ArtifactRef(entry["artifact"],
                            ArtifactContentIdentity(Digest.parse(entry["artifact_content"])))
    try:
        return store.read(reference)
    except (OSError, EvidenceError) as error:
        raise EvidenceError(
            f"{entry['record']}: the artifact the gate would read is not the one custody "
            f"accepted ({error})"
        ) from error


def _reconcile_parents(check: Reconciliation, parents: Iterable[Path | str]
                       ) -> tuple[list[str], dict[str, list[tuple[str, dict]]], int]:
    """R41/R42: resolve every recorded parent in the evidence handed in."""
    derived = {key: entry for key, entry in check.entries.items()
               if entry.get("derivation") is not None}
    if not derived:
        return [], {}, 0
    packages = gather(parents)
    problems: list[str] = []
    by_cell: dict[str, list[tuple[str, dict]]] = {}
    for key, entry in derived.items():
        record = entry["derivation"]
        if entry.get("lineage") != str(lineage_identity(record).digest):
            problems.append(f"{key}: the lineage digest is not this derivation record (R41)")
            continue
        parent, found = resolve(packages, record["parent"])
        if parent is None:
            problems.extend(f"{key}: {reason}" for reason in found)
            continue
        by_cell.setdefault(entry["cell"], []).append((key, actual_derivation(record)))
    return problems, by_cell, len(derived)


def audit(directory: Path, parents: Iterable[Path | str] = ()) -> Audit:
    """Audit a run directory from its evidence alone. No provider is called.

    `parents` is the upstream evidence handed to the verifier: a recorded
    parent must resolve among exactly these packages, by its exact seal."""
    directory = Path(directory)
    lock_document = _read(directory / LOCK_FILE)
    run_document = _read(directory / RUN_FILE)
    run_id = run_document.get("run", "")
    identities = dict(lock_document.get("identities") or {})
    findings: list[Finding] = []

    lock_findings = verify_lock(lock_document)
    lock_problems = [f"{f.step}: {reason}" for f in lock_findings
                     if f.verdict is Verdict.VIOLATED for reason in f.reasons]
    findings.append(_verdict("contract_validity", lock_problems))
    if lock_problems:
        return Audit(run_id, identities, tuple(findings))

    experiment = load(lock_document["declaration"])
    records = experiment.records
    journal = Journal(directory).read()
    match_problems = []
    if run_document.get("lock") != identities:
        match_problems.append("run.json names a different lock than lock.json holds")
    badly_opened = opening.problems(journal, run_id)
    if badly_opened:
        match_problems.extend(badly_opened)
    else:
        # the opening the invariant just accepted, not whatever is on line 0:
        # this step compares identities and has no second opinion about where
        # the opening is.
        opened = journal[opening.openings(journal)[0]]
        if {k: opened[f"lock_{k}"] for k in ("contract", "design", "schedule")} != identities:
            match_problems.append("the run was opened against other lock identities")
    findings.append(_verdict("lock_match", match_problems))
    if match_problems:
        return Audit(run_id, identities, tuple(findings))

    store = ArtifactStore(directory)
    check = reconcile(directory, run_id=run_id, identities=identities, records=records,
                      journal=journal, store=store)
    findings.append(_verdict("topology", _topology_problems(experiment, records, check)))
    findings.append(_verdict("schedule_order", check.order))
    findings.append(_verdict("attempt_serialization", check.serialization))
    findings.append(_verdict("custody_integrity", [*check.integrity, *check.sealing]))
    findings.append(_verdict("session_provenance", _session_problems(check, journal)))
    findings.append(_verdict("execution_binding", check.binding))

    blocked = [f"{f.step} is {f.verdict.value}" for f in findings
               if f.step in ("topology", "schedule_order", "attempt_serialization",
                             "custody_integrity", "execution_binding")
               and f.verdict is Verdict.VIOLATED]
    executions: dict[str, list[dict]] = {}
    artifacts: dict[str, list[tuple[str, bytes]]] = {}
    if not blocked:
        for key, entry in check.entries.items():
            executions.setdefault(entry["cell"], []).append(entry["actual_execution"])
            try:
                artifacts.setdefault(entry["cell"], []).append(
                    (key, accepted_bytes(store, entry)))
            except EvidenceError as error:
                # nothing downstream may observe bytes this gate could not bind
                blocked.append(str(error))
                executions, artifacts = {}, {}
                break
    findings.extend(_family_findings(
        "declared_vs_actual", ExecutionFamily(), experiment.execution_expectations,
        experiment, executions, blocked))
    findings.extend(_family_findings(
        "artifact_provenance", ArtifactFamily(), experiment.artifact_rules,
        experiment, artifacts, blocked))

    lineage_problems, derivations, recorded = ([], {}, 0) if blocked else \
        _reconcile_parents(check, parents)
    if blocked:
        findings.append(Finding("parent_reconciliation", Verdict.VIOLATED,
                                (f"the evidence this would be reconciled against is not "
                                 f"trustworthy: {blocked[0]}",)))
    elif not recorded:
        findings.append(Finding("parent_reconciliation", Verdict.NO_CLAIM,
                                ("no derivation was recorded for any accepted record",)))
    else:
        findings.append(_verdict("parent_reconciliation", lineage_problems))
    lineage_blocked = [*blocked, *(["parent_reconciliation is VIOLATED"]
                                   if lineage_problems or blocked else [])]
    findings.extend(_family_findings(
        "declared_vs_actual_derivation", DerivationFamily(),
        experiment.derivation_expectations, experiment, derivations, lineage_blocked))

    dataset = None
    if any(f.step == "topology" and f.verdict is Verdict.VIOLATED for f in findings):
        findings.append(Finding("dataset_identity", Verdict.VIOLATED,
                                ("the accepted evidence is not the locked schedule, so no "
                                 "dataset identity is computed",)))
    else:
        dataset = manifest(identities, rows(records, check.entries), run=run_id)
        findings.append(Finding("dataset_identity", Verdict.VERIFIED))
    if check.recovered:
        findings.append(Finding("recovered_custody", Verdict.NO_CLAIM,
                                (f"{len(check.recovered)} entry(ies) were recovered by an "
                                 f"operator, not written at execution time (R16)",)))
    findings.extend(_input_lock_findings(directory, journal))
    binding = (experiment.analysis_binding.document()
               if experiment.analysis_binding is not None else None)
    return Audit(run_id, identities, tuple(findings), dataset, binding)


def _input_lock_findings(directory: Path, journal: Sequence[Mapping]) -> list[Finding]:
    """IR-07/IR-10: an INPUT_LOCKED run is admitted only on a verified Input Lock.

    Present only when the question exists: a run whose journal carries an
    INPUT_LOCK_BOUND anchor, or a directory holding Input Lock artifacts with
    no anchor (a spoof or a partial creation). A legacy run has neither, gets
    no finding, and its audit is byte-identical to what it was before.

    The verification is ILV in its evidence-only form: every step recomputes
    from persisted bytes; only the comparison with this installation's code
    (ILV-13, a resume question) is left out.
    """
    from boomvalley_lab.experiment_input.errors import InputRefusal
    from boomvalley_lab.experiment_input.verify import verify_input_lock
    from boomvalley_lab.journal.anchor import AnchorState, artifacts_present, classify

    anchor = classify(journal)
    if anchor.state is AnchorState.ABSENT:
        present = artifacts_present(directory)
        if not present:
            return []
        return [Finding(INPUT_LOCK_STEP, Verdict.VIOLATED,
                        (f"UNANCHORED_INPUT_LOCK: {present} without an INPUT_LOCK_BOUND anchor",))]
    try:
        verify_input_lock(directory, installation=False)
    except InputRefusal as refusal:
        return [Finding(INPUT_LOCK_STEP, Verdict.VIOLATED, (f"{refusal.code}: {refusal.detail}",))]
    return [Finding(INPUT_LOCK_STEP, Verdict.VERIFIED)]
