"""EPC-v1: the evidence package a reader without the product can consume.

Design source: lab-control `V2_LAB/EVIDENCE_PACKAGE_CONTRACT_V1_DESIGN.md`
(DRAFT, not frozen). This is its minimum-viable subset, implemented in place
and additively (DEC-07, DEC-08, §20 option A + C):

    <run>/
      EVIDENCE.json              boomvalley-epc-manifest-3 (not a member of itself)
      PACKAGE.json               the legacy manifest, role legacy_package_manifest
      lock.json run.json journal.jsonl custody/* artifacts/* analysis/*   as sealed
      input.json preflight/**    INPUT_LOCKED runs: the Input Lock (IR-07)
      design/declaration.json    raw digest = ContractIdentity
      design/design.json         raw digest = DesignIdentity
      design/schedule.json       raw digest = ScheduleIdentity
      dataset/dataset.json       the admitted dataset manifest (DatasetIdentity by selection)
      reports/eligibility.json   the producer's gate result as step/rule/verdict/code
      requests/record-NNNNNN.json  the exact request of each record (INPUT_LOCKED runs,
                                 rebuilt from the locked profile; raw digest = intent.request),
                                 absent when the request content is WITHHELD
      provenance/producer.json   what produced the evidence: boomvalley-epc-producer-2,
                                 self-reported vs verified provenance (`evidence.provenance`)
      provenance/environment.json  where it was packaged

Nothing sealed is rewritten; every added file is downstream of the seal, as
`analysis/` and `PACKAGE.json` already were. The raw-byte digest of every
member is in the manifest, and the manifest seals itself (§6.4):

    evidence_root    = SHA-256(canonical({"epc_identity": "evidence-root/1",
                                          "members": members sorted by path}))
    package_identity = SHA-256(canonical({"epc_identity": "package/1",
                                          **manifest minus {package_identity, informational}}))

The Output Seal - the custody head's `seal`, which RUN_SEALED must agree with -
is named in `identities.custody_seal` and so is inside `package_identity`.

#76 (C1 semantic freeze A) made the manifest `boomvalley-epc-manifest-2`: two new
required members, each a closed decision with registered codes -

    execution_gate   the pre-execution gate decision (`experiment_input.gate`,
                     bvl-execution-gate-1): an INPUT_LOCKED run exists only because
                     its gate was CLEARED; a legacy run was never gated
                     (NOT_EVALUATED, LEGACY_RUN_NOT_GATED)
    request_content  AVAILABLE / WITHHELD / UNAVAILABLE (`evidence.requests`)

#87 (C1 C2a) made the producer member `boomvalley-epc-producer-2`: every provenance
item is either self-reported (what the producer, an adapter or GNDCRW says of itself -
never a verified claim) or verified (recomputed from the package bytes), in two
sections, by a closed trust table (PRV-001..003). The manifest shape is unchanged;
a `boomvalley-epc-producer-1` member is still read, as entirely self-reported.

#88 (C1 C2b) made the manifest `boomvalley-epc-manifest-3`: the one shape change is
`limitations`, a code-sorted list of {code, free_text} (`evidence.limitations`): the
code is closed and is all a rule reads (LIM-001 closed and well formed, LIM-002 the
evidence's limitations stated); free_text is for people and never decides. A `-2`
package keeps its code-string list and is read under the same closed vocabulary.

A `-1` package keeps its meaning and still verifies: it has no gate decision
(reported NOT_EVALUATED, EXECUTION_GATE_NOT_RECORDED) and its request content
is read the `-1` way. The writer only writes `-3`; `-1` / `-2` are never re-labelled.

Neither digest is a signature (D4). The package is producer-side evidence; the
reader below is the producer's self-check, not FULLMT, and FULLMT conformance
is never "agrees with this file".
"""

from __future__ import annotations

import locale
import os
import platform
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import UNSUPPORTED_SCHEMA, EvidenceError, ExecutionError
from boomvalley_lab.core.layout import (
    ACTIVE_MARKER,
    CUSTODY_DIR,
    ENTRIES_FILE,
    EVIDENCE_FILE,
    HEAD_FILE,
    JOURNAL_FILE,
    LOCK_FILE,
    PACKAGE_FILE,
    REQUESTS_DIR,
    RUN_FILE,
    SESSIONS_DIR,
)
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.core.verdict import Verdict
from boomvalley_lab.core.versions import CANONICAL_FORMAT, DIGEST_ALGORITHM, PACKAGE_VERSION
from boomvalley_lab.evidence import limitations as limitation_codes
from boomvalley_lab.evidence.roles import (
    INPUT_LOCK,
    MATERIALISED,
    PACKAGE_MANIFEST_ROLE,
    REQUIRED,
    role_for,
)
from boomvalley_lab.journal.log import unterminated

MANIFEST_SCHEMA = "boomvalley-epc-manifest-3"
MANIFEST_SCHEMA_V2 = "boomvalley-epc-manifest-2"
MANIFEST_SCHEMA_V1 = "boomvalley-epc-manifest-1"
#: what this reader reads (the writer writes MANIFEST_SCHEMA only)
READABLE_MANIFESTS = (MANIFEST_SCHEMA_V1, MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA)
ELIGIBILITY_SCHEMA = "boomvalley-epc-eligibility-1"
PRODUCER_SCHEMA = "boomvalley-epc-producer-2"      # the writer; -1 is still read
ENVIRONMENT_SCHEMA = "boomvalley-epc-environment-1"
RUN_ID_SCHEME = "legacy-label"  # DEC-02 (uuid4 run ids) is an Owner decision not yet taken

#: kind -> version, every identity this manifest may reference (EPC-R033)
IDENTITY_VERSIONS = {
    "run": "run/1",
    "contract": "declaration-1",
    "design": "design-1",
    "schedule": "schedule-1",
    "request": "request-1",
    "artifact_content": "raw-1",
    "custody_seal": "custody-head-2",
    "dataset": "dataset-identity-2",
    "experiment_input": "bvl-experiment-input-identity-2",
    "evidence_root": "evidence-root/1",
    "package": "package/1",
}

#: role -> schema of the JSON members whose schema is fixed by their role
JSON_SCHEMAS = {
    "lock": "boomvalley-lab-lock-1",
    "custody_head": "boomvalley-lab-custody-head-2",
    "declaration": "boomvalley-lab-declaration-1",
    "design": "boomvalley-lab-design-1",
    "schedule": "boomvalley-lab-schedule-1",
    "dataset": "boomvalley-lab-dataset-2",
    "eligibility_report": ELIGIBILITY_SCHEMA,
    "producer_provenance": PRODUCER_SCHEMA,
    "environment": ENVIRONMENT_SCHEMA,
    "request": "boomvalley-lab-request-1",
    "analysis": "boomvalley-lab-analysis-1",
    PACKAGE_MANIFEST_ROLE: "boomvalley-lab-package-1",
    "experiment_input": "bvl-input-lock-2",
    "gndcrw_manifest": "gndcrw-manifest/v0.2",
    "gndcrw_result": "gndcrw-result/v0.2",
    "gndcrw_subject_declaration": "gndcrw-declaration/v0.1",
    "gndcrw_subject_target_catalog": "gndcrw-target-catalog/v0.1",
    "gndcrw_subject_base_surface": "gndcrw-surface/v0.1",
    "gndcrw_subject_candidate_surface": "gndcrw-surface/v0.1",
    "gndcrw_subject_pair_context": "gndcrw-pair/v0.1",
}
NDJSON_SCHEMAS = {"journal": "boomvalley-lab-journal-1",
                  "custody_entries": "boomvalley-lab-custody-entry-1"}
RUN_SCHEMAS = {"legacy": "boomvalley-lab-run-legacy-1",
               "input_locked": "boomvalley-lab-run-input-locked-1"}

#: roles whose stored bytes are canonical-json-1 (STR-002). The GNDCRW result
#: and subjects are another tool's bytes and are only hashed.
CANONICAL_AT_REST = {"lock", "run", "custody_head", "declaration", "design", "schedule",
                     "dataset", "eligibility_report", "producer_provenance", "environment",
                     "request", "analysis", PACKAGE_MANIFEST_ROLE, "experiment_input",
                     "gndcrw_manifest"}

#: gate step -> portable rule id (§19). Anything else is PRODUCT-INTERNAL:
#: producer-attested, not recomputable by a consumer (DEC-11).
RULE_IDS = {
    "contract_validity": "ID-003",
    "lock_match": "JRN-002",
    "topology": "SCH-001",
    "schedule_order": "SCH-002",
    "attempt_serialization": "JRN-003",
    "custody_integrity": "CUS-003",
    "session_provenance": "SES-001",
    "execution_binding": "CUS-004",
    "declared_vs_actual": "EXP-001",
    "parent_reconciliation": "LIN-001",
    "dataset_identity": "DS-001",
    "input_lock": "INP-001",
}
#: per-cell step prefix (the expectation family) -> its step_id (DEC-13)
FAMILY_STEPS = {"execution": "declared_vs_actual", "artifact": "artifact_provenance",
                "derivation": "declared_vs_actual_derivation"}
CODES = {Verdict.VERIFIED: "OK", Verdict.NO_CLAIM: "NO_CLAIM", Verdict.VIOLATED: "VIOLATED"}

#: limitations every package of this producer states (§24 item 11; `evidence.limitations`)
STANDING_LIMITATIONS = limitation_codes.STANDING


def typed(kind: str, digest: str, member: str | None = None) -> dict:
    """A typed identity reference (§8.1): the digest satisfies it, `member` only locates."""
    return {"kind": kind, "version": IDENTITY_VERSIONS[kind], "digest": digest, "member": member}


def run_identity(run_id: str, lock: Mapping[str, str]) -> str:
    return str(sha256_document({"epc_identity": IDENTITY_VERSIONS["run"], "run_id": run_id,
                                "lock": {k: lock[k] for k in ("contract", "design", "schedule")}}))


def evidence_root(members: Sequence[Mapping]) -> str:
    return str(sha256_document({"epc_identity": IDENTITY_VERSIONS["evidence_root"],
                                "members": sorted(members, key=lambda m: m["path"])}))


def package_identity(manifest: Mapping) -> str:
    body = {k: v for k, v in manifest.items() if k not in ("package_identity", "informational")}
    return str(sha256_document({"epc_identity": IDENTITY_VERSIONS["package"], **body}))


def member_order(path: str) -> tuple[list[str], str]:
    """The members[] order (REC-015), defined here and not by a filesystem or OS:
    path segments compared case-folded, then the exact path by code point as the
    tie-break. It equals the Windows `Path` order the reference packages were
    written in (portable paths are ASCII) and is the same on every host."""
    return [segment.casefold() for segment in path.split("/")], path


def journal_extent(data: bytes) -> dict:
    acknowledged = data.rfind(b"\n") + 1
    return {"acknowledged_bytes": acknowledged, "torn_tail_bytes": len(data) - acknowledged}


def _read_json(directory: Path, path: str) -> Any:
    try:
        return load_bytes((directory / path).read_bytes())
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"{path} is unreadable: {error}") from error


def _eii_digest(eii: str) -> str:
    return eii.removeprefix("experiment_input:")


# =====================================================================
# the writer
# =====================================================================
def _refuse_unpackageable(directory: Path) -> None:
    """JRN-004: only a SEALED run with no active session is ever packaged."""
    if not (directory / CUSTODY_DIR / HEAD_FILE).is_file():
        raise ExecutionError("the run is not SEALED (no custody head); a package is made only "
                             "of a sealed run")
    if (directory / SESSIONS_DIR / ACTIVE_MARKER).exists():
        raise ExecutionError("a session is active; release or finish it before packaging")
    if unterminated((directory / CUSTODY_DIR / ENTRIES_FILE).read_bytes()):
        raise ExecutionError("the sealed custody entries end in a torn tail (CUS-001); a "
                             "sealed ledger is complete, and this one is not packaged")
    taken = [p for p in (EVIDENCE_FILE, PACKAGE_FILE, *MATERIALISED.values())
             if (directory / p).exists()]
    if (directory / REQUESTS_DIR).exists():
        taken.append(f"{REQUESTS_DIR}/")
    if taken:
        raise ExecutionError(f"this run is already packaged ({', '.join(taken)} exist); a "
                             "package is written once and never rewritten")


def _write_once(directory: Path, path: str, data: bytes) -> None:
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "xb") as handle:
        handle.write(data)


def eligibility_document(report, run_ref: dict) -> dict:
    """The producer's gate result as codes (§18). Prose is informational."""
    findings = []
    for finding in report.findings:
        family, _, cell = finding.step.partition(":")
        step_id = FAMILY_STEPS.get(family, finding.step) if cell else finding.step
        findings.append({"step_id": step_id, "rule_id": RULE_IDS.get(step_id, "PRODUCT-INTERNAL"),
                         "verdict": finding.verdict.value, "code": CODES[finding.verdict],
                         "subject": {"cell": cell} if cell else None})
    reasons = {f.step: list(f.reasons) for f in report.findings if f.reasons}
    return {"schema": ELIGIBILITY_SCHEMA, "run": run_ref, "producer": "boomvalley-lab",
            "verdict": report.document()["eligibility"], "findings": findings,
            "informational": {"reasons": reasons} if reasons else None}


def _requests(directory: Path, journal: Sequence[Mapping], experiment,
              locked) -> tuple[dict[str, bytes], list[dict]] | None:
    """REQ-001: the exact request of every record, when it can be rebuilt.

    An INPUT_LOCKED run names its request builder in the verified Input Lock,
    so each request is rebuilt and must hash to the digest its intent
    recorded - a document that does not is refused, never written. A legacy
    run does not identify its builder: its requests are UNAVAILABLE (§12.2).
    Returns the member bytes and one {record, position, digest, size} per intent.
    """
    if locked is None:
        return None
    from boomvalley_lab.experiment_input.verify import rebuilt_request
    from boomvalley_lab.journal import events as ev
    from boomvalley_lab.store.artifacts import artifact_name

    records = {record.key: record for record in experiment.records}
    files: dict[str, bytes] = {}
    entries: list[dict] = []
    for event in journal:
        if event["event"] != ev.INTENT_RECORDED:
            continue
        record = records[event["record"]]
        data = rebuilt_request(locked.profile, record)
        if str(sha256_bytes(data)) != event["request"]:
            raise EvidenceError(f"{event['record']}: the rebuilt request is not the one its "
                                "intent recorded (REQ-001)")
        name = f"{REQUESTS_DIR}/{artifact_name(event['position']).removesuffix('.bin')}.json"
        if files.setdefault(name, data) != data:
            raise EvidenceError(f"{event['record']}: two attempts sent different requests")
        entries.append({"record": event["record"], "position": event["position"],
                        "digest": event["request"], "size": len(data)})
    return files, sorted(entries, key=lambda e: e["position"])


def _git(*argv: str) -> str | None:
    root = Path(__file__).resolve().parents[3]
    try:
        done = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True,
                              timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _source() -> dict:
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return {"status": "unknown"}
    status = _git("status", "--porcelain", "--untracked-files=no", "--", "src")
    if status is None:
        return {"status": "unknown"}  # SV-03: a status that failed is not a clean tree
    return {"status": "git", "commit": commit, "dirty": bool(status)}


def _runtime() -> dict:
    return {"name": platform.python_implementation(), "version": platform.python_version()}


def _os() -> dict:
    return {"name": platform.system(), "version": platform.release(), "arch": platform.machine()}


def _held_provenance(directory: Path, entries: Sequence[Mapping], locked):
    from boomvalley_lab.evidence.provenance import Held

    def optional(path: str) -> bytes | None:
        return (directory / path).read_bytes() if (directory / path).is_file() else None

    return Held(entries=entries,
                input_bytes=optional(INPUT_LOCK["experiment_input"]) if locked else None,
                run_document=_read_json(directory, RUN_FILE),
                result_bytes=optional(INPUT_LOCK["gndcrw_result"]) if locked else None,
                sha=lambda data: str(sha256_bytes(data)))


def producer_document(directory: Path, entries: Sequence[Mapping], locked) -> dict:
    """§13, core only: what produced this evidence, each item under its trust class."""
    from boomvalley_lab.evidence.provenance import producer_document as document

    return document(_held_provenance(directory, entries, locked),
                    host={"software": {"name": "boomvalley-lab", "version": PACKAGE_VERSION},
                          "source": _source(), "runtime": _runtime(), "os": _os()})


def environment_document() -> dict:
    return {"schema": ENVIRONMENT_SCHEMA, "runtime": _runtime(), "os": _os(),
            "encoding": {"filesystem": sys.getfilesystemencoding(),
                         "preferred": locale.getpreferredencoding(False)},
            "clock": {"source": "system-utc", "format": "rfc3339-seconds-z"}}


def _media(role: str, run_document: Mapping) -> dict:
    if role in NDJSON_SCHEMAS:
        return {"media_type": "application/x-ndjson", "schema": NDJSON_SCHEMAS[role]}
    if role == "run":
        kind = "input_locked" if "input" in run_document else "legacy"
        return {"media_type": "application/json", "schema": RUN_SCHEMAS[kind]}
    if role in JSON_SCHEMAS:
        return {"media_type": "application/json", "schema": JSON_SCHEMAS[role]}
    return {"media_type": "application/octet-stream", "media_type_source": "default"}


def member_records(directory: Path, entries: Sequence[Mapping]) -> list[dict]:
    """Every file under the root but EVIDENCE.json, typed by its role."""
    run_document = _read_json(directory, RUN_FILE)
    derived = {e["artifact"] for e in entries if e.get("derivation")}
    members = []
    files = {p.relative_to(directory).as_posix(): p for p in directory.rglob("*") if p.is_file()}
    for path in sorted(files, key=member_order):
        file = files[path]
        if path == EVIDENCE_FILE:
            continue
        role = role_for(path, epc=True)
        if role is None:
            raise EvidenceError(f"{path} is in the run directory and has no package role; "
                                "remove it or it would be packaged as unexplained evidence")
        data = file.read_bytes()
        record = {"path": path, "role": role, **_media(role, run_document),
                  "digest": str(sha256_bytes(data)), "bytes": len(data)}
        if role == "artifact":
            name = path.partition("/")[2]
            record["content_class"] = "derived_content" if name in derived \
                else "response_content"
        members.append(record)
    return members


def write_evidence_package(directory: Path | str, *, parents: Iterable[Path | str] = (),
                           at: str, withhold: str | None = None) -> dict:
    """Package a SEALED run: materialise, legacy PACKAGE.json, then EVIDENCE.json.

    `withhold` (a WITHHELD reason code of `evidence.requests.REASONS`) keeps the
    request bytes out of the package: their digests and sizes are stated, the bytes
    are not written.
    """
    from boomvalley_lab.custody.entries import CustodyLedger
    from boomvalley_lab.declare.experiment import load
    from boomvalley_lab.evidence import requests as request_content
    from boomvalley_lab.evidence.package import input_lock_state, parent_seals, write_package
    from boomvalley_lab.experiment_input import gate as gates
    from boomvalley_lab.experiment_input.verify import verify_input_lock
    from boomvalley_lab.identity.derive import design_document, schedule_document
    from boomvalley_lab.journal.log import Journal
    from boomvalley_lab.verify.gate import audit

    directory = Path(directory)
    parents = tuple(parents)
    if withhold is not None and request_content.REASONS.get(withhold) != request_content.WITHHELD:
        raise ValueError(f"{withhold!r} is not a WITHHELD request reason")
    _refuse_unpackageable(directory)
    report = audit(directory, parents=parents)
    lock_document = _read_json(directory, LOCK_FILE)
    identities = dict(lock_document["identities"])
    experiment = load(lock_document["declaration"])
    journal = Journal(directory).read()
    entries = CustodyLedger(directory).read()
    state = input_lock_state(directory)
    locked = None
    if state is not None:
        if state["classification"] != "INPUT_LOCKED":
            raise EvidenceError(f"the run's Input Lock does not verify ({state.get('code')}); "
                                "it is not packaged as an INPUT_LOCKED run")
        locked = verify_input_lock(directory, installation=False)

    run_id = report.run
    run_ref = typed("run", run_identity(run_id, identities))
    documents = {
        MATERIALISED["declaration"]: canonical_bytes(lock_document["declaration"]),
        MATERIALISED["design"]: canonical_bytes(design_document(experiment)),
        MATERIALISED["schedule"]: canonical_bytes(schedule_document(experiment)),
    }
    for role, kind in (("declaration", "contract"), ("design", "design"),
                       ("schedule", "schedule")):
        if str(sha256_bytes(documents[MATERIALISED[role]])) != identities[kind]:
            raise EvidenceError(f"the materialised {role} does not hash to the locked "
                                f"{kind} identity; nothing is packaged")
    limitations = set(STANDING_LIMITATIONS)
    if report.dataset is not None:
        documents[MATERIALISED["dataset"]] = canonical_bytes(report.dataset)
    else:
        limitations.add(limitation_codes.DATASET_NOT_ADMITTED)
    documents[MATERIALISED["eligibility_report"]] = canonical_bytes(
        eligibility_document(report, run_ref))
    producer = producer_document(directory, entries, locked)
    documents[MATERIALISED["producer_provenance"]] = canonical_bytes(producer)
    documents[MATERIALISED["environment"]] = canonical_bytes(environment_document())
    requests = _requests(directory, journal, experiment, locked)
    if requests is None:
        if withhold is not None:
            raise EvidenceError("this run's requests are UNAVAILABLE (its request builder was "
                                "never recorded); there is no request content to withhold")
        content = request_content.document(request_content.UNAVAILABLE,
                                           "REQUEST_BUILDER_NOT_RECORDED", None)
    else:
        files, stated = requests
        published = withhold is None
        if published:
            documents.update(files)
        content = request_content.document(
            request_content.AVAILABLE if published else request_content.WITHHELD, withhold,
            [request_content.entry(e["record"], e["position"], e["digest"], e["size"],
                                   published=published) for e in stated])
    if content["request_content_status"] in request_content.LIMITATION:
        limitations.add(request_content.LIMITATION[content["request_content_status"]])
    execution_gate = (gates.not_evaluated("LEGACY_RUN_NOT_GATED",
                                          contract=identities["contract"])
                      if locked is None else
                      gates.decision([], contract=identities["contract"], eii=locked.identity))
    from boomvalley_lab.evidence.provenance import model_entries

    if any(m.get("provider_version", {}).get("status") not in (None, "not_applicable")
           for m in model_entries(producer)) or locked is None:
        limitations.add(limitation_codes.MODEL_VERSION_NOT_PINNED)
    if locked is not None and locked.document.get("pre_execution") is not None:
        limitations.update(locked.document["pre_execution"]["preflight_record"]["limitations"])
    extent = journal_extent((directory / JOURNAL_FILE).read_bytes())
    if extent["torn_tail_bytes"]:
        limitations.add(limitation_codes.JOURNAL_TORN_TAIL)

    _refuse_unpackageable(directory)            # nothing appeared while we computed
    for path, data in documents.items():
        _write_once(directory, path, data)
    legacy = write_package(directory, parents=parents, at=at)

    head = _read_json(directory, f"{CUSTODY_DIR}/{HEAD_FILE}")
    members = member_records(directory, entries)
    manifest: dict[str, Any] = {
        "manifest_schema": MANIFEST_SCHEMA,
        "formats": {"canonical_format": CANONICAL_FORMAT, "digest_algorithm": DIGEST_ALGORITHM,
                    "identity_versions": dict(IDENTITY_VERSIONS)},
        "run": {"run_id": run_id, "run_id_scheme": RUN_ID_SCHEME, "run_identity": run_ref},
        "identities": {
            "contract": typed("contract", identities["contract"], MATERIALISED["declaration"]),
            "design": typed("design", identities["design"], MATERIALISED["design"]),
            "schedule": typed("schedule", identities["schedule"], MATERIALISED["schedule"]),
            "custody_seal": typed("custody_seal", head["seal"], f"{CUSTODY_DIR}/{HEAD_FILE}"),
            "dataset": None if report.dataset is None else typed(
                "dataset", legacy["dataset"]["identity"], MATERIALISED["dataset"]),
            "experiment_input": None if locked is None else typed(
                "experiment_input", _eii_digest(locked.identity), INPUT_LOCK["experiment_input"]),
        },
        "input_lock": state or {"classification": "NOT_INPUT_LOCKED"},
        "execution_gate": execution_gate,
        "request_content": content,
        "members": members,
        "journal": extent,
        "limitations": limitation_codes.entries(limitations),
        "parents": [{"seal": seal} for seal in parent_seals(directory)] or None,
        "evidence_root": evidence_root(members),
    }
    manifest["package_identity"] = package_identity(manifest)
    manifest["informational"] = {"created_at": at,
                                 "producer_self_check": legacy["producer_self_check"][
                                     "eligibility"]}
    _write_once(directory, EVIDENCE_FILE, canonical_bytes(manifest))
    return manifest


# =====================================================================
# the reader: the producer's own self-check over the EPC rules
# =====================================================================
@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    verdict: Verdict
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceReport:
    directory: Path
    rules: tuple[RuleResult, ...]
    package_identity: str | None
    evidence_root: str | None
    legacy: dict | None
    manifest_schema: str | None = None
    #: the package's gate decision (a `-1` package: NOT_EVALUATED, not recorded)
    execution_gate: dict | None = None
    #: `evidence.requests.reading` of the package's request content (codes, message keys)
    request_content: dict | None = None
    #: `evidence.provenance.reading`: verified and self-reported provenance, kept apart
    provenance: dict | None = None
    #: `evidence.limitations.reading`: the stated codes (machine) and free_text (people)
    limitations: dict | None = None

    @property
    def verified(self) -> bool:
        return all(r.verdict is not Verdict.VIOLATED for r in self.rules)

    def document(self) -> dict:
        """`verification_status` says whether the evidence holds; `execution_gate_status`
        says what the gate decided. Two questions, two members, never merged (#76 C)."""
        gate = self.execution_gate if isinstance(self.execution_gate, dict) else {}
        return {"manifest": EVIDENCE_FILE, "manifest_schema": self.manifest_schema,
                "verified": self.verified,
                "verification_status": "VERIFIED" if self.verified else "REJECTED",
                "execution_gate_status": gate.get("execution_gate_status"),
                "execution_gate": self.execution_gate,
                "request_content_status": (self.request_content or {}).get(
                    "request_content_status"),
                "request_content": self.request_content,
                "provenance": self.provenance,
                "limitations": self.limitations,
                "package_identity": self.package_identity, "evidence_root": self.evidence_root,
                "rules": [{"rule_id": r.rule_id, "verdict": r.verdict.value,
                           "reasons": list(r.reasons)} for r in self.rules],
                "legacy_package": self.legacy}


def _rule(rule_id: str, problems: Sequence[str]) -> RuleResult:
    return RuleResult(rule_id, Verdict.VIOLATED, tuple(problems)) if problems \
        else RuleResult(rule_id, Verdict.VERIFIED)


_SEGMENT_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def _portable(path: object) -> bool:
    if not isinstance(path, str) or not path:
        return False
    for segment in path.split("/"):
        if not segment or segment in (".", "..") or not segment[0].isalnum() \
                or not set(segment) <= _SEGMENT_OK or not segment.isascii():
            return False
    return True


def read_evidence(directory: Path | str, *, parents: Iterable[Path | str] = (),
                  traverse: bool = True) -> EvidenceReport:
    """Verify an EPC-v1 package by recomputation. Refuses nothing silently.

    `parents` are the packages handed to the verifier. `traverse=False` reads this
    package AS a direct parent: its own parents are not resolved (LIN-002 NO_CLAIM) -
    lineage is direct parent only (C1, #86)."""
    from boomvalley_lab.custody.entries import check_entry
    from boomvalley_lab.evidence.package import (
        _outside,
        input_lock_state,
        parent_seals,
        read_package,
    )
    from boomvalley_lab.verify.gate import audit

    directory = Path(directory)
    parents = tuple(Path(p) for p in parents)
    try:
        data = (directory / EVIDENCE_FILE).read_bytes()
        manifest = load_bytes(data)
    except (OSError, MalformedJSON) as error:
        raise EvidenceError(f"{EVIDENCE_FILE} is unreadable: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("manifest_schema") not in \
            READABLE_MANIFESTS:
        raise EvidenceError(f"not a {' / '.join(READABLE_MANIFESTS)} package",
                            code=UNSUPPORTED_SCHEMA)
    version_2 = manifest["manifest_schema"] in (MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA)
    #: -3 (#88): limitations are {code, free_text} entries; -1 / -2: code strings
    structured = manifest["manifest_schema"] == MANIFEST_SCHEMA
    stated_limitations = limitation_codes.codes(manifest.get("limitations"),
                                                structured=structured)
    rules: list[RuleResult] = []

    # ---- MEM-001 structure, MEM-002 bytes, MEM-003 no stray file
    required = {"manifest_schema", "formats", "run", "identities", "input_lock", "members",
                "journal", "limitations", "evidence_root", "package_identity"}
    if version_2:
        required |= {"execution_gate", "request_content"}
    structure = [f"missing manifest member {k}" for k in sorted(required - set(manifest))]
    structure += [f"unknown manifest member {k}" for k in sorted(
        set(manifest) - required - {"parents", "informational"})]
    if canonical_bytes(manifest) != data:
        structure.append(f"{EVIDENCE_FILE} is not canonical-json-1 at rest")
    members = manifest.get("members") if isinstance(manifest.get("members"), list) else []
    by_path: dict[str, dict] = {}
    for member in members:
        if not isinstance(member, dict) or not _portable(member.get("path")):
            structure.append(f"malformed member {member!r}")
            continue
        path = member["path"]
        if path in by_path:
            structure.append(f"{path} is listed twice")
            continue
        by_path[path] = member
        if member.get("role") != role_for(path, epc=True):
            structure.append(f"{path} is listed as {member.get('role')!r}; its role is "
                             f"{role_for(path, epc=True)!r}")
    listed = [m["path"] for m in members if isinstance(m, dict) and _portable(m.get("path"))]
    if listed != sorted(listed, key=member_order):
        structure.append("members[] is not in member order (case-folded segments, then code "
                         "points; REC-015)")
    rules.append(_rule("MEM-001", structure))

    root = directory.resolve()
    held: dict[str, bytes] = {}
    integrity = []
    for path, member in by_path.items():
        if not os.path.lexists(directory / path):
            integrity.append(f"{path} is listed and missing")
            continue
        escaped = _outside(root, directory, path)
        if escaped:
            integrity.append(escaped)
            continue
        raw = (directory / path).read_bytes()
        held[path] = raw
        if member.get("digest") != str(sha256_bytes(raw)) or member.get("bytes") != len(raw):
            integrity.append(f"{path} is not the bytes the manifest lists")
    rules.append(_rule("MEM-002", integrity))
    present = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    rules.append(_rule("MEM-003", [f"{p} is under the package root and is not a member"
                                   for p in sorted(present - set(by_path) - {EVIDENCE_FILE})]))

    # ---- MEM-004 role cardinalities
    roles: dict[str, list[str]] = {}
    for path, member in by_path.items():
        roles.setdefault(member.get("role"), []).append(path)
    state = input_lock_state(directory)
    once = {*REQUIRED, "declaration", "design", "schedule", "eligibility_report",
            "producer_provenance", "environment", PACKAGE_MANIFEST_ROLE}
    if (manifest.get("identities") or {}).get("dataset"):
        once.add("dataset")
    cardinality = [f"role {r} occurs {len(roles.get(r, []))} times, not once"
                   for r in sorted(once) if len(roles.get(r, [])) != 1]
    locked = state is not None and state.get("classification") == "INPUT_LOCKED"
    for role in INPUT_LOCK:
        count = len(roles.get(role, []))
        if count != (1 if locked else 0):
            cardinality.append(f"role {role} occurs {count} times in a "
                               f"{'INPUT_LOCKED' if locked else 'NOT_INPUT_LOCKED'} run")
    rules.append(_rule("MEM-004", cardinality))

    # ---- STR-002 canonical at rest
    canonical = []
    for path, raw in held.items():
        role = by_path[path]["role"]
        try:
            if role in CANONICAL_AT_REST:
                if canonical_bytes(load_bytes(raw)) != raw:
                    canonical.append(f"{path} is not canonical-json-1 at rest")
            elif role in NDJSON_SCHEMAS:
                extent = journal_extent(raw)["acknowledged_bytes"]
                for number, line in enumerate(raw[:extent].split(b"\n")[:-1]):
                    if canonical_bytes(load_bytes(line)) != line:
                        canonical.append(f"{path} line {number} is not canonical")
                        break
        except (MalformedJSON, ValueError, TypeError) as error:
            canonical.append(f"{path}: {error}")
    rules.append(_rule("STR-002", canonical))

    # ---- ID-001 / ID-002 the self-seal
    rules.append(_rule("ID-001", [] if manifest.get("evidence_root") == evidence_root(
        [m for m in members if isinstance(m, dict) and "path" in m]) else
        ["evidence_root does not recompute from the member table"]))
    rules.append(_rule("ID-002", [] if manifest.get("package_identity") == package_identity(
        manifest) else ["package_identity does not recompute from the manifest"]))

    # ---- ID-003 / ID-004 identities and run
    identity_problems = []
    lock_document = run_document = None
    try:
        lock_document = load_bytes(held[LOCK_FILE])
        run_document = load_bytes(held[RUN_FILE])
        locked_ids = lock_document["identities"]
        stated = manifest["identities"]
        for role, kind in (("declaration", "contract"), ("design", "design"),
                           ("schedule", "schedule")):
            raw_digest = str(sha256_bytes(held[MATERIALISED[role]]))
            if not (raw_digest == locked_ids[kind] == run_document["lock"][kind]
                    == stated[kind]["digest"]):
                identity_problems.append(f"{kind}: SHA-256({MATERIALISED[role]}) / lock / "
                                         "run.json / manifest disagree")
            if stated[kind].get("version") != IDENTITY_VERSIONS[kind]:
                identity_problems.append(f"{kind}: typed reference version")
    except (KeyError, TypeError, MalformedJSON) as error:
        identity_problems.append(f"the identity members cannot be read: {error!r}")
    rules.append(_rule("ID-003", identity_problems))
    run_problems = []
    run_entry = manifest.get("run") or {}
    if run_document is not None and lock_document is not None:
        if run_entry.get("run_id") != run_document.get("run"):
            run_problems.append("the manifest run_id is not run.json's run")
        if run_entry.get("run_id_scheme") != RUN_ID_SCHEME:
            run_problems.append(f"unknown run_id_scheme {run_entry.get('run_id_scheme')!r}")
        if (run_entry.get("run_identity") or {}).get("digest") != run_identity(
                str(run_document.get("run")), lock_document["identities"]):
            run_problems.append("RunIdentity does not recompute")
    rules.append(_rule("ID-004", run_problems))

    # ---- SEAL-001 the Output Seal
    seal_problems = []
    try:
        head = load_bytes(held[f"{CUSTODY_DIR}/{HEAD_FILE}"])
        if head.get("state") != "SEALED":
            seal_problems.append("the custody head is not SEALED")
        if manifest["identities"]["custody_seal"]["digest"] != head.get("seal"):
            seal_problems.append("the manifest names another custody seal than the head's")
        journal_lines = [load_bytes(line) for line in held[JOURNAL_FILE][
            :journal_extent(held[JOURNAL_FILE])["acknowledged_bytes"]].split(b"\n")[:-1]]
        sealed = [e for e in journal_lines if e.get("event") == "RUN_SEALED"]
        if len(sealed) != 1 or sealed[0].get("seal") != head.get("seal"):
            seal_problems.append("RUN_SEALED does not name the head's seal exactly once")
        tail = [e.get("event") for e in journal_lines[journal_lines.index(sealed[0]):]] \
            if len(sealed) == 1 else []
        if tail not in (["RUN_SEALED"], ["RUN_SEALED", "SESSION_CLOSED"]):
            seal_problems.append(f"the acknowledged journal does not end at the seal: {tail}")
        if manifest.get("journal") != journal_extent(held[JOURNAL_FILE]):
            seal_problems.append("the recorded journal extent is not the journal's")
    except (KeyError, TypeError, ValueError, MalformedJSON) as error:
        seal_problems.append(f"the seal cannot be read: {error!r}")
    rules.append(_rule("SEAL-001", seal_problems))

    # ---- JRN-004 (§17, DEC-05) a torn journal tail is carried only when declared
    torn_problems = []
    if JOURNAL_FILE in held:
        torn = unterminated(held[JOURNAL_FILE])
        declared = limitation_codes.JOURNAL_TORN_TAIL in stated_limitations
        if torn and not declared:
            torn_problems.append(f"the journal ends in a {torn}-byte torn tail and the "
                                 "limitation JOURNAL_TORN_TAIL is not listed")
        if declared and not torn:
            torn_problems.append("JOURNAL_TORN_TAIL is listed and the journal has no torn tail")
    rules.append(_rule("JRN-004", torn_problems))

    # ---- CUS-001 the sealed custody ledger is complete canonical JSONL: unlike
    # the journal it has no torn-tail state, so trailing bytes are refused
    entry_problems = []
    for path in roles.get("custody_entries", []):
        raw = held.get(path)
        if raw is None:
            continue
        torn = unterminated(raw)
        if torn:
            entry_problems.append(f"{path} ends in {torn} bytes that are not a complete "
                                  "record; a sealed custody ledger has no torn tail")
        for number, line in enumerate(raw[:len(raw) - torn].split(b"\n")[:-1], 1):
            try:
                check_entry(load_bytes(line), f"{path} line {number}")
            except (MalformedJSON, EvidenceError) as error:
                entry_problems.append(str(error))
                break
    rules.append(_rule("CUS-001", entry_problems))

    # ---- DS-001, ELG-001 against the producer's own recomputation
    report = audit(directory, parents=parents)
    dataset_problems = []
    stated_dataset = (manifest.get("identities") or {}).get("dataset")
    if report.dataset is None:
        if stated_dataset or MATERIALISED["dataset"] in held:
            dataset_problems.append("a dataset is packaged that the evidence does not admit")
    else:
        from boomvalley_lab.dataset.manifest import dataset_identity

        recomputed = str(dataset_identity(report.dataset).digest)
        if held.get(MATERIALISED["dataset"]) != canonical_bytes(report.dataset):
            dataset_problems.append("dataset/dataset.json is not the dataset the evidence "
                                    "recomputes")
        if not stated_dataset or stated_dataset.get("digest") != recomputed:
            dataset_problems.append("the manifest DatasetIdentity is not the recomputed one")
    rules.append(_rule("DS-001", dataset_problems))
    run_ref = typed("run", run_identity(report.run, report.identities))
    expected = canonical_bytes(eligibility_document(report, run_ref))
    rules.append(_rule("ELG-001", [] if held.get(MATERIALISED["eligibility_report"]) == expected
                       else ["the eligibility report is not the one the evidence recomputes"]))

    # ---- INP-001 the Input Lock
    input_problems = []
    if manifest.get("input_lock") != (state or {"classification": "NOT_INPUT_LOCKED"}):
        input_problems.append("the manifest's Input Lock is not the one the evidence recomputes")
    if state is not None and not locked:
        # the manifest records the code only; the reason carries the recomputed cause
        from boomvalley_lab.experiment_input.verify import classification

        detail = classification(directory).get("detail")
        input_problems.append(f"the Input Lock does not verify: {state.get('code')}"
                              + (f" ({detail})" if detail else ""))
    stated_eii = (manifest.get("identities") or {}).get("experiment_input")
    if locked and (not stated_eii or stated_eii.get("digest") != _eii_digest(
            state["experiment_input_identity"])):
        input_problems.append("the manifest ExperimentInputIdentity is not the verified one")
    if not locked and stated_eii:
        input_problems.append("an ExperimentInputIdentity is named for a run without one")
    rules.append(_rule("INP-001", input_problems))

    # ---- REQ-001 requests
    from boomvalley_lab.evidence import requests as request_content

    request_problems = []
    intents: dict[str, str] = {}
    intent_events: list[dict] = []
    for line in held.get(JOURNAL_FILE, b"").split(b"\n"):
        if line:
            try:
                event = load_bytes(line)
            except MalformedJSON:
                continue
            if event.get("event") == "INTENT_RECORDED":
                from boomvalley_lab.store.artifacts import artifact_name
                name = f"{REQUESTS_DIR}/{artifact_name(event['position'])[:-4]}.json"
                intents[name] = event["request"]
                intent_events.append(event)
    listed = set(roles.get("request", []))
    content = manifest.get("request_content")
    if version_2:
        request_problems = request_content.problems(
            content, intents=intent_events, held=held, listed=listed, locked=locked,
            limitations=stated_limitations,
            sha=lambda data: str(sha256_bytes(data)))
    elif listed or request_content.LIMITATION[request_content.UNAVAILABLE] \
            not in stated_limitations:
        for name in sorted(set(intents) - listed):
            request_problems.append(f"{name}: an intent with no request member")
        for name in sorted(listed - set(intents)):
            request_problems.append(f"{name}: a request with no intent")
        for name in sorted(listed & set(intents)):
            if str(sha256_bytes(held.get(name, b""))) != intents[name]:
                request_problems.append(f"{name} is not the request its intent recorded")
    rules.append(_rule("REQ-001", request_problems))
    if version_2:
        request_reading = request_content.read(content)
    elif listed:    # a -1 package: the status its members show
        request_reading = request_content.reading(request_content.AVAILABLE, None, len(listed))
    else:
        request_reading = request_content.reading(request_content.UNAVAILABLE,
                                                  "REQUEST_BUILDER_NOT_RECORDED", None)

    # ---- EXG-001 the execution gate decision (#76 C)
    from boomvalley_lab.experiment_input import gate as gates

    contract = ((manifest.get("identities") or {}).get("contract") or {}).get("digest")
    if version_2:
        execution_gate = manifest.get("execution_gate")
        gate_problems = gates.problems(execution_gate)
        if not gate_problems:
            eii = state.get("experiment_input_identity") if locked else None
            expected_gate = (gates.decision([], contract=contract, eii=eii) if locked else
                             gates.not_evaluated("LEGACY_RUN_NOT_GATED", contract=contract))
            if execution_gate != expected_gate:
                gate_problems.append(
                    f"the gate decision is {execution_gate['execution_gate_status']} "
                    f"{[r['reason_code'] for r in execution_gate['reasons']]}; the evidence "
                    f"establishes {expected_gate['execution_gate_status']} "
                    f"{[r['reason_code'] for r in expected_gate['reasons']]} for this "
                    f"{'INPUT_LOCKED' if locked else 'NOT_INPUT_LOCKED'} run (an executed "
                    "run was CLEARED; a legacy run was never gated)")
        rules.append(_rule("EXG-001", gate_problems))
    else:
        execution_gate = gates.not_evaluated("EXECUTION_GATE_NOT_RECORDED", contract=contract)

    # ---- LIM-001 closed limitation codes, LIM-002 the evidence's limitations stated (#88)
    limitation_shape = limitation_codes.problems(manifest.get("limitations"),
                                                 structured=structured)
    rules.append(_rule("LIM-001", limitation_shape))
    if limitation_shape:
        rules.append(RuleResult("LIM-002", Verdict.NO_CLAIM, ("LIM-001 does not hold",)))
    else:
        try:
            preflight = None
            if locked:
                pre = load_bytes(held[INPUT_LOCK["experiment_input"]]).get("pre_execution")
                preflight = None if pre is None else pre["preflight_record"]["limitations"]
            rules.append(_rule("LIM-002", limitation_codes.expected_problems(
                stated_limitations, dataset_admitted=report.dataset is not None,
                locked=bool(locked), preflight=preflight)))
        except (KeyError, TypeError, AttributeError, MalformedJSON) as error:
            rules.append(_rule("LIM-002", [f"the Input Lock limitations cannot be read: "
                                           f"{error!r}"]))

    # ---- LIN-001 parents named, LIN-002 each direct parent resolves and binds (#86)
    from boomvalley_lab.evidence import lineage

    try:
        custody_entries = [load_bytes(line) for path in roles.get("custody_entries", [])
                           for line in held.get(path, b"").split(b"\n") if line]
    except MalformedJSON:
        custody_entries = []
    named = lineage.named_parents(manifest, custody_entries)
    if not named and [p["seal"] for p in manifest.get("parents") or []] != parent_seals(
            directory):
        named.append("the manifest parents are not the seals this run's custody derives from")
    rules.append(_rule("LIN-001", named))
    if traverse:
        rules.append(_rule("LIN-002", lineage.direct_parent_problems(
            manifest=manifest, entries=custody_entries,
            own_seal=((manifest.get("identities") or {}).get("custody_seal") or {}).get(
                "digest"),
            own_run_identity=run_ref["digest"], parents=parents)))
    else:
        rules.append(RuleResult("LIN-002", Verdict.NO_CLAIM, (lineage.NOT_TRAVERSED,)))

    # ---- PRV-001..003 producer provenance: self-reported vs verified (#87)
    from boomvalley_lab.evidence import provenance

    provenance_reading = None
    producer_path = MATERIALISED["producer_provenance"]
    try:
        producer = load_bytes(held[producer_path]) if producer_path in held else None
        evidence = provenance.Held(
            entries=custody_entries,
            input_bytes=held.get(INPUT_LOCK["experiment_input"]) if locked else None,
            run_document=run_document, result_bytes=held.get(INPUT_LOCK["gndcrw_result"]),
            sha=lambda data: str(sha256_bytes(data)))
        if producer is None:
            shape = [f"{provenance.SHAPE_INVALID}: {producer_path} is not held"]
        else:
            shape = provenance.shape_problems(producer, evidence)
    except (KeyError, TypeError, AttributeError, MalformedJSON) as error:
        shape, producer = [f"{provenance.SHAPE_INVALID}: {error!r}"], None
    rules.append(_rule("PRV-001", shape))
    if shape:
        rules += [RuleResult(r, Verdict.NO_CLAIM, ("PRV-001 does not hold",))
                  for r in ("PRV-002", "PRV-003")]
    elif producer["schema"] == provenance.PRODUCER_SCHEMA_V1:
        provenance_reading = provenance.reading(producer)
        rules += [RuleResult(r, Verdict.NO_CLAIM, (provenance.V1_NOT_CLASSIFIED,))
                  for r in ("PRV-002", "PRV-003")]
    else:
        provenance_reading = provenance.reading(producer)
        for rule_id, check in (("PRV-002", provenance.verified_problems),
                               ("PRV-003", provenance.consistency_problems)):
            try:
                rules.append(_rule(rule_id, check(producer, evidence)))
            except (KeyError, TypeError, AttributeError) as error:
                rules.append(_rule(rule_id, [f"{provenance.SHAPE_INVALID}: {error!r}"]))

    # ---- the legacy manifest, read as its own reader reads it
    legacy = read_package(directory, parents=parents)
    rules.append(_rule("LEGACY-001", [f"{f.step}: {f.reasons[0] if f.reasons else ''}"
                                      for f in legacy.violations()]))
    return EvidenceReport(directory, tuple(rules), manifest.get("package_identity"),
                          manifest.get("evidence_root"), legacy.document(),
                          manifest_schema=manifest["manifest_schema"],
                          execution_gate=execution_gate, request_content=request_reading,
                          provenance=provenance_reading,
                          limitations=limitation_codes.reading(manifest.get("limitations"),
                                                               structured=structured))


def _request_reading(content: Mapping) -> dict:
    from boomvalley_lab.evidence import requests as request_content

    return request_content.read(content)


def summary(manifest: Mapping) -> dict:
    """What `bvl package` reports: the identities and the member counts by role."""
    counts: dict[str, int] = {}
    for member in manifest["members"]:
        counts[member["role"]] = counts.get(member["role"], 0) + 1
    return {"manifest": EVIDENCE_FILE, "package_identity": manifest["package_identity"],
            "evidence_root": manifest["evidence_root"], "run": manifest["run"],
            "identities": {k: v["digest"] for k, v in manifest["identities"].items() if v},
            "input_lock": manifest["input_lock"]["classification"],
            "members": len(manifest["members"]), "roles": counts,
            "limitations": manifest["limitations"],
            "limitation_codes": limitation_codes.codes(manifest["limitations"], structured=True),
            "manifest_schema": manifest["manifest_schema"],
            "execution_gate_status": manifest["execution_gate"]["execution_gate_status"],
            "request_content_status": manifest["request_content"]["request_content_status"],
            "request_content": _request_reading(manifest["request_content"]),
            "producer_self_check": manifest["informational"]["producer_self_check"]}


__all__ = ["EvidenceReport", "MANIFEST_SCHEMA", "read_evidence", "summary",
           "write_evidence_package"]
