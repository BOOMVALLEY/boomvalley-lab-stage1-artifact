"""The evidence package: what a run hands to a reader who was not there.

The run directory IS the package — nothing is copied or reorganised, because a
second copy would be a second truth. `write_package` adds one file,
`PACKAGE.json`, which says what the package CONTAINS: every member, its role
and its digest, plus the identities and the producer's own self-check.

    writer   emits evidence and its own labelled self-check
    reader   opens the package as hostile input, checks membership, and then
             RECOMPUTES the identities, the dataset and the eligibility for
             itself — the writer's verdict is evidence about the producer,
             never an answer the reader may adopt

That asymmetry is the point. A package whose `PACKAGE.json` says ELIGIBLE and
whose evidence says otherwise is refused by the reader, loudly.

The package is producer-side audit-ready evidence. It is not certified,
assured, attested or tamper-proof, and it makes no scientific claim;
independent audit is FULLMT's, not this file's.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from boomvalley_lab.analysis.binding import problems as binding_problems
from boomvalley_lab.analysis.binding import reconstruct
from boomvalley_lab.analysis.run import ANALYSIS_DIR, ANALYSIS_SCHEMA, analysis_identity
from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import UNSUPPORTED_SCHEMA, EvidenceError, ExecutionError
from boomvalley_lab.core.layout import ARTIFACT_DIR, EVIDENCE_FILE, REQUESTS_DIR
from boomvalley_lab.core.strict_json import MalformedJSON, load_file
from boomvalley_lab.core.verdict import Finding, Verdict, all_hold
from boomvalley_lab.core.versions import version_document
from boomvalley_lab.custody.entries import CustodyLedger
from boomvalley_lab.dataset.manifest import dataset_identity
from boomvalley_lab.evidence.roles import INPUT_LOCK, MATERIALISED, REQUIRED, role_for
from boomvalley_lab.verify.gate import audit

PACKAGE_SCHEMA = "boomvalley-lab-package-1"
PACKAGE_FILE = "PACKAGE.json"


def _member(directory: Path, path: str, role: str) -> dict:
    data = (directory / path).read_bytes()
    return {"path": path, "role": role, "digest": str(sha256_bytes(data)), "bytes": len(data)}


def _listed_paths(directory: Path, sub: str) -> list[str]:
    root = directory / sub
    if not root.exists():
        return []
    return sorted(f"{sub}/{p.name}" for p in root.iterdir() if p.is_file())


def write_package(directory: Path | str, *, parents: Iterable[Path | str] = (),
                  at: str) -> dict:
    """Describe the package. Writing it proves nothing; it records what is here."""
    directory = Path(directory)
    report = audit(directory, parents=parents)
    members = [_member(directory, path, role) for role, path in REQUIRED.items()]
    # the optional fixed members this run holds: the Input Lock of an
    # INPUT_LOCKED run (IR-07) and the documents the EPC packager materialised.
    # Whether the run may hold them is the gate's question (`input_lock`).
    members += [_member(directory, path, role)
                for role, path in {**INPUT_LOCK, **MATERIALISED}.items()
                if (directory / path).is_file()]
    members += [_member(directory, path, "artifact")
                for path in _listed_paths(directory, ARTIFACT_DIR)]
    members += [_member(directory, path, "request")
                for path in _listed_paths(directory, REQUESTS_DIR)]
    analyses = []
    for path in _listed_paths(directory, ANALYSIS_DIR):
        try:
            document = load_file(directory / path)
        except (OSError, MalformedJSON) as error:
            raise EvidenceError(f"{path} is unreadable: {error}") from error
        if not isinstance(document, Mapping):
            raise EvidenceError(f"{path} is not a JSON object")
        members.append(_member(directory, path, "analysis"))
        analyses.append({"path": path, "evidence": str(analysis_identity(document).digest),
                         "dataset": document.get("dataset"),
                         "output": document.get("output"),
                         "plugin": (document.get("actual") or {}).get("plugin")})
    document = {
        "package_schema": PACKAGE_SCHEMA,
        "versions": version_document(),
        "run": report.run,
        "identities": dict(report.identities),
        "dataset": None if report.dataset is None else {
            "identity": str(dataset_identity(report.dataset).digest),
            "records": report.dataset["records"],
        },
        # the producer's own gate result, labelled as exactly that
        "producer_self_check": {
            "eligibility": report.document()["eligibility"],
            "report": str(sha256_document(report.document())),
            "verdicts": report.verdicts,
        },
        "analysis": analyses or None,
        "parents": parent_seals(directory) or None,
        # absent for a legacy run, so its PACKAGE.json is byte-for-byte what it was
        "input_lock": input_lock_state(directory),
        "members": sorted(members, key=lambda m: m["path"]),
        "at": at,
    }
    path = directory / PACKAGE_FILE
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(document))
    except FileExistsError as error:
        raise ExecutionError(f"{PACKAGE_FILE} is written once; this package already has one"
                             ) from error
    return document


def input_lock_state(directory: Path) -> dict | None:
    """What the evidence says about this run's Input Lock, or None for a legacy run.

    Recomputed, never read off a label: the journal anchor classifies the run,
    and an anchored run's Input Lock is verified from its persisted bytes (ILV,
    evidence-only). The writer records this; the reader recomputes it and
    compares (`input_lock_claim`).
    """
    from boomvalley_lab.experiment_input.errors import InputRefusal
    from boomvalley_lab.experiment_input.verify import verify_input_lock
    from boomvalley_lab.journal.anchor import AnchorState, artifacts_present, classify
    from boomvalley_lab.journal.log import Journal

    try:
        anchor = classify(Journal(directory).read())
    except EvidenceError:
        return {"classification": "JOURNAL_INVALID"}
    if anchor.state is AnchorState.ABSENT:
        if artifacts_present(directory):
            return {"classification": "INPUT_DRIFT", "code": "UNANCHORED_INPUT_LOCK"}
        return None
    if anchor.state is AnchorState.INVALID:
        return {"classification": "INPUT_DRIFT", "code": "INPUT_LOCK_ANCHOR_INVALID"}
    try:
        locked = verify_input_lock(directory, installation=False)
    except InputRefusal as refusal:
        return {"classification": "INPUT_DRIFT", "code": refusal.code}
    state = {"classification": "INPUT_LOCKED", "verification": "INPUT_LOCK_OK",
             "experiment_input_identity": locked.identity, "input_digest": locked.digest,
             "member": INPUT_LOCK["experiment_input"]}
    pre = locked.document.get("pre_execution")
    if pre is not None:
        tool = pre["preflight_record"]["gndcrw"]
        state["preflight"] = {
            "outcome": tool["outcome"], "tool": tool["tool"],
            "external_subject": tool["external_subject"],
            "manifest": tool["manifest"], "result": tool["result"],
            "subjects": tool["inputs"],
        }
    return state


def parent_seals(directory: Path) -> list[str]:
    """The exact parent seals this run's evidence depends on (R41, R42).

    Read from the custody entries, where a derivation record actually lives.
    The dataset rows carry the LINEAGE digest, not the derivation record, so
    looking for `derivation` there found nothing and every derived package
    described itself as having no parents at all - an honest package omitting
    a dependency it really has.

    Content-addressed and therefore a set: two entries derived from the same
    parent package depend on it once, and a re-run is a different seal rather
    than a newer one.
    """
    return sorted({entry["derivation"]["parent"]["seal"]
                   for entry in CustodyLedger(directory).read()
                   if entry.get("derivation")})


# =====================================================================
# the reader: hostile input, own arithmetic
# =====================================================================
@dataclass(frozen=True)
class PackageReport:
    """What a reader who was not there can establish from the bytes."""

    directory: Path
    run: str
    findings: tuple[Finding, ...]
    recomputed: Mapping[str, object]

    @property
    def verified(self) -> bool:
        return all_hold(finding.verdict for finding in self.findings)

    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict is Verdict.VIOLATED]

    def document(self) -> dict:
        return {
            "run": self.run,
            "verified": self.verified,
            "findings": [{"step": f.step, "verdict": f.verdict.value,
                          "reasons": list(f.reasons)} for f in self.findings],
            "recomputed": dict(self.recomputed),
        }


def _safe(path: object) -> bool:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
        return False
    parts = Path(path).parts
    return ".." not in parts and not Path(path).is_absolute() and ":" not in path


def _verdict(step: str, problems: Sequence[str]) -> Finding:
    return Finding(step, Verdict.VIOLATED, tuple(problems)) if problems \
        else Finding(step, Verdict.VERIFIED)


def read_package(directory: Path | str, *, parents: Iterable[Path | str] = ()
                 ) -> PackageReport:
    """Open a package as hostile input and verify it by recomputation."""
    directory = Path(directory)
    findings: list[Finding] = []
    recomputed: dict[str, object] = {}
    try:
        document = load_file(directory / PACKAGE_FILE)
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"{PACKAGE_FILE} is unreadable: {error}") from error
    if not isinstance(document, Mapping) or document.get("package_schema") != PACKAGE_SCHEMA:
        raise EvidenceError(f"not a {PACKAGE_SCHEMA} package", code=UNSUPPORTED_SCHEMA)
    claimed = document.get("run")
    if not isinstance(claimed, str) or not claimed:
        raise EvidenceError("the package names no run")

    findings.append(_verdict("package_membership", _membership_problems(directory, document)))
    report = audit(directory, parents=parents)
    # whose evidence this is, decided by the evidence. The package's own label
    # is compared with it and never adopted - including in the report below,
    # which would otherwise repeat a forged label back to its reader.
    findings.append(_verdict("recomputed_run", _run_problems(claimed, report)))
    findings.append(_verdict("package_dependencies",
                             _dependency_problems(directory, document, recomputed)))
    findings.extend(_input_lock_claim(directory, document, recomputed))
    findings.extend(_recompute(document, report, recomputed))
    findings.extend(_analysis_findings(directory, document, report, recomputed))
    return PackageReport(directory, report.run, tuple(findings), recomputed)


def _run_problems(claimed: str, report) -> list[str]:
    """Is this package the run it says it is? (R14, OD-01)

    The evidence names its run in `run.json`, and the audit has already tied
    that to the journal this run opened and to the lock it verifies against.
    A package label is a claim about which body of evidence is inside, and a
    claim is exactly the thing this reader does not take.

        same bytes and same results  !=  same run evidence
    """
    if claimed == report.run:
        return []
    return [f"the package presents itself as run {claimed!r}; the evidence it contains "
            f"is run {report.run!r}"]


def _dependency_problems(directory: Path, document: Mapping, recomputed: dict) -> list[str]:
    """Does the package name exactly the parent evidence it depends on? (R41/R42)

    The authoritative set is rebuilt from the custody entries this run sealed,
    never from the package's own list. A handoff manifest whose dependencies
    are its own claim cannot be used to reconstruct provenance: omitting one
    hides a parent, naming another points the auditor at evidence that had no
    part in this run, and both verified before this check existed.

    R41/R42 are not touched. Whether each recorded derivation is real, and
    whether its parent resolves by its exact seal in the handed evidence, is
    still the gate's (`parent_reconciliation`). This asks only whether the
    package SAYS what the gate would have to be given.
    """
    authority = parent_seals(directory)
    recomputed["parents"] = authority
    listed = document.get("parents")
    if listed is None:
        listed = []
    if not isinstance(listed, list):
        return [f"the dependency list is {type(listed).__name__}, not a list"]

    problems: list[str] = []
    seen: set[str] = set()
    for seal in listed:
        if not isinstance(seal, str) or not seal.strip():
            problems.append(f"malformed parent dependency: {seal!r}")
            continue
        if seal in seen:
            problems.append(f"the parent {seal[:23]}… is named twice")
        seen.add(seal)
    for seal in sorted(set(authority) - seen):
        problems.append(f"this run derived from the parent sealed {seal[:23]}… and the "
                        "package does not name it as a dependency (R41/R42)")
    for seal in sorted(seen - set(authority)):
        problems.append(f"the package names a dependency on {seal[:23]}…, which no "
                        "derivation in this run's custody records")
    return problems


def _input_lock_claim(directory: Path, document: Mapping, recomputed: dict) -> list[Finding]:
    """Does the package say what the evidence says about its Input Lock? (IR-07)

    Asked only when there is something to ask: the package records an Input
    Lock, or the evidence has one (or holds its artifacts without an anchor).
    A legacy package of a legacy run gets no finding, exactly as before.
    """
    state = input_lock_state(directory)
    claimed = document.get("input_lock")
    if state is None and claimed is None:
        return []
    recomputed["input_lock"] = state
    problems: list[str] = []
    if state is None:
        problems.append("the package describes an Input Lock this run's journal does not anchor")
    elif claimed is None:
        problems.append(f"the evidence is {state['classification']} and the package does not "
                        "say so")
    elif claimed != state:
        problems.append("the package's Input Lock is not the one its evidence recomputes")
    if state is not None and state["classification"] != "INPUT_LOCKED":
        problems.append(f"the Input Lock does not verify: {state.get('code', state)}")
    return [_verdict("input_lock_claim", problems)]


#: The member grammar is `evidence.roles` (shared with the EPC manifest). A
#: member outside it is not a package member at all (OA-02: the normative
#: surface is the member path, its digest, and the role where consumer
#: semantics depend on it).
_role_for = role_for


def _outside(root: Path, directory: Path, path: str) -> str | None:
    """Where this member actually lands — resolved, not spelled.

    A member path can satisfy every lexical rule #14 imposes and still open a
    file somewhere else entirely: a directory junction, a symlink or another
    reparse point under the package turns `artifacts/result.bin` into
    `D:\\elsewhere\\result.bin` without changing a character of the manifest.

        lexically inside the package  !=  resolved inside the package

    A package that points at evidence instead of carrying it cannot be moved,
    handed over or re-verified anywhere else, which is the whole claim a
    package makes. So both sides are resolved — the ROOT as well as the
    member, since comparing against an unresolved root would just move the
    lie one level up — and containment is decided by path ancestry, never by
    string prefix: `C:/pkg-evil/a.bin` starts with `C:/pkg` and is not in it.

    Fail closed. A member that cannot be resolved at all — a dangling
    junction, a broken link, a target the process may not read — is refused
    rather than assumed innocent: not being able to tell is not a pass.
    """
    try:
        resolved = (directory / path).resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as error:
        return (f"{path} cannot be resolved to a file in this package "
                f"({type(error).__name__}: {error})")
    if not resolved.is_relative_to(root):
        return (f"{path} resolves to {resolved}, outside this package; a package "
                "carries its evidence rather than pointing at it")
    return None


def _canonical(path: str) -> str:
    """The one spelling of a member path this manifest may use.

    `analysis/./a.json`, `analysis//a.json` and `analysis\\a.json` all open the
    same file, so a manifest that spells one member two ways lists it twice
    while looking like two members. #14 fixes the SPELLING; whether the
    resolved file lies inside the package root is #15.
    """
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _membership_problems(directory: Path, document: Mapping) -> list[str]:
    members = document.get("members")
    if not isinstance(members, list) or not members:
        return ["the package lists no members"]
    problems: list[str] = []
    try:
        root = directory.resolve(strict=True)
    except OSError as error:
        return [f"the package directory cannot be resolved ({error})"]
    seen: dict[str, dict] = {}
    for member in members:
        if not isinstance(member, Mapping) or not _safe(member.get("path")) \
                or not isinstance(member.get("digest"), str):
            problems.append(f"malformed package member: {member!r}")
            continue
        path = member["path"]
        if _canonical(path) != path:
            problems.append(f"{path} is not the canonical spelling of a member path")
            continue
        if path in seen:
            problems.append(f"{path} is listed twice")
            continue
        seen[path] = member
        expected = _role_for(path)
        if expected is None:
            problems.append(f"{path} is not a member this package's grammar defines")
        elif member.get("role") != expected:
            problems.append(f"{path} is listed as {member.get('role')!r} and is this "
                            f"package's {expected}")
        # a member that is simply not there is missing; one that is there and
        # does not resolve into the package is an escape. `lexists` tells them
        # apart, because a dangling link exists and does not resolve.
        if not os.path.lexists(directory / path):
            problems.append(f"{path} is listed and missing")
            continue
        escaped = _outside(root, directory, path)
        if escaped is not None:
            problems.append(escaped)
            continue
        try:
            data = (directory / path).read_bytes()
        except OSError:
            problems.append(f"{path} is listed and missing")
            continue
        if str(sha256_bytes(data)) != member["digest"]:
            problems.append(f"{path} is not the bytes the package lists")
        # the size is recomputed from the same read as the digest, so it costs
        # nothing to verify - and a manifest should not ship a number it
        # presents as checked and does not check (OA-02).
        if member.get("bytes") != len(data):
            problems.append(f"{path} is {len(data)} bytes and the package says "
                            f"{member.get('bytes')!r}")
    for role, path in REQUIRED.items():
        if path not in seen:
            problems.append(f"the package is missing its {role} ({path})")
    # every file the package carries, not only the two directories that were
    # scanned before: a manifest that enumerates the evidence must enumerate
    # all of it, or an auditor cannot tell what was handed over (OM-F006).
    # PACKAGE.json is the manifest itself and is not a member of itself.
    present = {path.relative_to(directory).as_posix()
               for path in directory.rglob("*") if path.is_file()} - {PACKAGE_FILE}
    # EVIDENCE.json is the EPC manifest, written after this one and naming it
    # as its legacy member; it is not hidden by that - it must name THIS file.
    if EVIDENCE_FILE in present:
        present.discard(EVIDENCE_FILE)
        problems.extend(_evidence_manifest_problems(directory))
    for path in sorted(present - set(seen)):
        problems.append(f"{path} is in the package directory and is not a member of it")
    return problems


def _evidence_manifest_problems(directory: Path) -> list[str]:
    try:
        evidence = load_file(directory / EVIDENCE_FILE)
        own = (directory / PACKAGE_FILE).read_bytes()
    except (OSError, MalformedJSON) as error:
        return [f"{EVIDENCE_FILE} is unreadable: {error}"]
    listed = [m for m in (evidence.get("members") or []) if isinstance(m, Mapping)
              and m.get("path") == PACKAGE_FILE] if isinstance(evidence, Mapping) else []
    if len(listed) != 1 or listed[0].get("digest") != str(sha256_bytes(own)):
        return [f"{EVIDENCE_FILE} is in the package directory and does not name this "
                f"{PACKAGE_FILE} by its digest"]
    return []


def _recompute(document: Mapping, report, recomputed: dict) -> list[Finding]:
    """The reader's own audit. The writer's verdict is compared, never adopted."""
    findings = []
    recomputed["run"] = report.run
    recomputed["identities"] = dict(report.identities)
    recomputed["eligibility"] = report.document()["eligibility"]
    recomputed["verdicts"] = report.verdicts
    recomputed["dataset"] = (None if report.dataset is None
                             else str(dataset_identity(report.dataset).digest))
    findings.append(_verdict("recomputed_identities", [] if document.get(
        "identities") == report.identities else ["the package names other lock identities"]))
    findings.append(_verdict("recomputed_dataset", _dataset_problems(document, report,
                                                                     recomputed)))
    findings.append(_verdict("recomputed_eligibility", [] if report.eligible else [
        f"{report.violations()[0].step}: {report.violations()[0].reasons[0]}"]))
    findings.append(_verdict("producer_claim_matches_evidence",
                             _producer_claim_problems(document, report, recomputed)))
    return findings


def _producer_claim_problems(document: Mapping, report, recomputed: dict) -> list[str]:
    """Every field the producer's self-check retains, against the recomputation.

    OA-02 is explicit that a retained producer self-check must be compared in
    full: "Selectively checking only some fields is not acceptable." The
    verdict was compared and the report digest and the per-step verdicts were
    not, which is exactly that half state - a producer could report a clean
    step-by-step self-check that its own evidence does not produce.

    This is not a second certification layer. The reader has already decided
    eligibility for itself (`recomputed_eligibility`); what is checked here is
    only whether the producer told the truth about what it saw.
    """
    self_check = document.get("producer_self_check")
    if self_check is None:
        return ["the package records no producer self-check"]
    if not isinstance(self_check, Mapping):
        return [f"the producer self-check is {type(self_check).__name__}, not a document"]
    problems: list[str] = []
    claimed = self_check.get("eligibility")
    if claimed != recomputed["eligibility"]:
        problems.append(f"the package claims {claimed!r}; the evidence recomputes to "
                        f"{recomputed['eligibility']!r}")
    recomputed_report = str(sha256_document(report.document()))
    if self_check.get("report") != recomputed_report:
        problems.append("the producer names a self-check report this evidence does not "
                        "produce")
    if self_check.get("verdicts") != report.verdicts:
        problems.append("the producer's per-step verdicts are not the ones this evidence "
                        "recomputes")
    return problems


def _dataset_problems(document: Mapping, report, recomputed: dict) -> list[str]:
    recorded = document.get("dataset")
    if report.dataset is None:
        return ["no dataset can be recomputed from this evidence"]
    if not isinstance(recorded, Mapping):
        return ["the package records no dataset identity"]
    problems = []
    if recorded.get("identity") != recomputed["dataset"]:
        problems.append("the recorded DatasetIdentity is not the one the evidence recomputes")
    if recorded.get("records") != report.dataset["records"]:
        problems.append("the recorded dataset size is not the evidence's")
    return problems


def _indexed(document: Mapping) -> list[str]:
    """The paths the package's analysis index names, in the order it names them."""
    listed = document.get("analysis")
    if not isinstance(listed, list):
        return []
    return [entry.get("path") for entry in listed if isinstance(entry, Mapping)]


def _scope_problems(present: Sequence[str], document: Mapping) -> list[str]:
    """Does the package describe the analysis evidence it actually contains?

    A writer may describe evidence. A writer may not decide which of the
    evidence that IS here the verifier looks at. When the index was the scope,
    deleting one line hid an analysis that was on disk and listed as a member,
    and the reader answered NO_CLAIM about it — an omission reported as an
    absence (R12, R14).

    So the index is a claim, checked against what is present, and the scope
    comes from the evidence instead (`_analysis_findings` below).

    This stays inside OA-02: the question asked here is only whether the
    ANALYSIS index enumerates the analysis evidence. It does not promote the
    rest of the package's metadata to normative, and it does not decide
    whether members, roles or byte counts are complete — that is #14.
    """
    listed = document.get("analysis")
    if listed is not None and not isinstance(listed, list):
        return [f"the analysis index is {type(listed).__name__}, not a list"]

    problems: list[str] = []
    entries = listed or []
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not _safe(entry.get("path")):
            problems.append(f"malformed analysis index entry: {entry!r}")
            continue
        paths.append(entry["path"])

    seen: set[str] = set()
    for path in paths:
        if path in seen:
            problems.append(f"{path} is named twice by the analysis index")
        seen.add(path)

    members = {member.get("path") for member in (document.get("members") or [])
               if isinstance(member, Mapping) and member.get("role") == "analysis"}
    for path in sorted(set(present) - seen):
        problems.append(f"{path} is analysis evidence in this package and the analysis "
                        "index does not name it")
    for path in sorted(seen - set(present)):
        problems.append(f"the analysis index names {path}, which is not analysis evidence "
                        "in this package")
    for path in sorted(set(present) - members):
        problems.append(f"{path} is analysis evidence and is not a member of this package "
                        "as one")
    return problems


def _analysis_findings(directory: Path, document: Mapping, report,
                       recomputed: dict) -> list[Finding]:
    """Every analysis PRESENT, against a binding rebuilt from the evidence.

    Two questions, kept apart. `analysis_scope` asks whether the package
    describes the analysis evidence it contains (#12). `analysis_binding`
    asks whether each analysis belongs to this experiment (#13) — and it asks
    it of every analysis that is here, not of the ones the index chose to
    mention, so an index cannot remove a document from verification.

    NO_CLAIM is reserved for its one honest case: there is no analysis
    evidence in the package at all.
    """
    present = _listed_paths(directory, ANALYSIS_DIR)
    findings = [_verdict("analysis_scope", _scope_problems(present, document))]
    if not present:
        findings.append(Finding("analysis_binding", Verdict.NO_CLAIM,
                                ("this package contains no analysis output",)))
        recomputed["analysis"] = []
        return findings

    claims = {entry["path"]: entry for entry in (document.get("analysis") or [])
              if isinstance(entry, Mapping) and _safe(entry.get("path"))}
    authority = reconstruct(report)
    problems: list[str] = []
    outputs = []
    for path in present:
        try:
            recorded = load_file(directory / path)
        except (OSError, MalformedJSON) as error:
            problems.append(f"{path} is unreadable: {error}")
            continue
        if not isinstance(recorded, Mapping) or recorded.get("schema") != ANALYSIS_SCHEMA:
            problems.append(f"{path} is not a {ANALYSIS_SCHEMA} document")
            continue
        # integrity of the document as listed: it is the bytes the package
        # names, and its output digest is its own result. Neither says the
        # document belongs here, which is what `binding_problems` decides.
        evidence = str(analysis_identity(recorded).digest)
        claimed = claims.get(path)
        if claimed is not None and claimed.get("evidence") != evidence:
            problems.append(f"{path}: the package names another analysis evidence identity")
        if str(sha256_document(recorded.get("result") or {})) != recorded.get("output"):
            problems.append(f"{path}: its recorded output digest is not its result")
        problems.extend(binding_problems(recorded, authority, where=path))
        outputs.append({"path": path, "evidence": evidence, "output": recorded.get("output")})
    recomputed["analysis"] = outputs
    findings.append(_verdict("analysis_binding", problems))
    return findings
