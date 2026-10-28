"""GNDCRW as an external executable (I4 capability, I6 invocation, result checks).

    I4  P = --gndcrw <absolute path>, else one PATH lookup of `gndcrw`.
        h0 = SHA-256(P). `P capabilities` must list gndcrw-manifest/v0.2 with
        result gndcrw-result/v0.2, policy GNDCRW-STRICT-0.1, the five v0.1
        contracts, and a pinned tool version. Otherwise fail closed.
    I6  In a fresh private staging directory BVL writes the five snapshot byte
        strings under fixed names (`subjects/*.json`) and GENERATES
        `gndcrw-manifest.json` = canonical-json-1 of
            {"external_subject": {"digest": C, "scheme": "boomvalley-lab-contract-identity"},
             "manifest_version": "gndcrw-manifest/v0.2",
             "subjects": {role: {"path", "sha256", "size"}}}
        (no trailing newline). h0 is re-checked, then
            argv = [P, "check", "gndcrw-manifest.json", "--format", "json", "--gate"]
        runs with cwd = the staging directory. stdout is kept as exact bytes.

The result is never trusted on exit 0 alone (RESULT_CONTRACT_V0_2 §5): it is
read strictly and its raw `binding` must equal what BVL wrote — the manifest
bytes, the five snapshots, and {scheme, C}. GNDCRW's normalized digests are
never recomputed, and its result bytes are never re-serialized.

#76 C: a checked result with outcome BLOCK / UNVERIFIABLE (exit 10 / 11) is a
normal preflight outcome, returned like RUN. It is the execution gate
(`experiment_input.gate`) that decides MANDATORY_REQUIREMENT_NOT_MET from it;
it is no longer the GNDCRW_REFUSAL error it was before.

GM-07: a GNDCRW refusal (exit 3) is not a subprocess crash. Its closed code
(the `gndcrw: error: <CODE>: ...` stderr line) is extracted and recorded
with the exit and bounded stderr evidence, and classified:
    REF_*       on BVL's own private copies: snapshot integrity -> INPUT_DRIFT
    MANIFEST_*  BVL's generated manifest refused: tool mismatch -> GNDCRW_TOOL_FAILURE
    otherwise   (SUBJECT_CONTRACT_INVALID, EXTERNAL_SUBJECT_NOT_IN_SURFACE, ...)
                the subjects themselves were refused         -> GNDCRW_INPUT_ERROR

#75: GNDCRW >= cd05a4e localizes the human detail after the code (`--locale`,
GNDCRW_LOCALE) and can write JSON log lines to stderr (GNDCRW_LOG_LEVEL). BVL
reads only the stable code, never the wording, and runs GNDCRW in a controlled
environment - GNDCRW_LOCALE=en-US, no GNDCRW_LOG_FILE / GNDCRW_LOG_LEVEL - so
the recorded stderr evidence does not depend on the operator's locale or log
settings, and never carries a GNDCRW log record. BVL's own `--locale` is never
passed on.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core import log
from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.layout import GNDCRW_MANIFEST_FILE, GNDCRW_SUBJECT_FILES
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.experiment_input.envelope import (
    EXTERNAL_SCHEME,
    GNDCRW_ATTACHMENT,
    GNDCRW_CONTRACTS,
    ROLES,
)
from boomvalley_lab.experiment_input.errors import InputRefusal
from boomvalley_lab.experiment_input.resolve import MIB16, Snapshot

#: the GNDCRW releases this build is pinned to (exact match; a release decision)
PINNED_VERSIONS = ("0.2.0",)
#: the GNDCRW build BVL is integrated and tested against: the commit, and the
#: `tool.code_digest` its reproducible wheel (GNDCRW scripts/install_smoke.py) reports.
#: Reported by `check`/`run` as MATCH or DIFFERS; not enforced, because the value is
#: install-dependent (GM-04, BVL-REC-010). Issue #75 moved it from cace4dea (#49,
#: sha256:94ce94c1...e80e81c3) to the GNDCRW C1 foundation cd05a4e (#74,
#: sha256:7e79d5b7...5b010c61bd); RC validation #129 to dc30214 (#127, legacy error codes
#: and logging only). The manifest / result v0.2 contracts and the RESULT_CONTRACT tables
#: below are unchanged.
INTEGRATION_BASELINE = {
    "commit": "dc30214c39c4334d31253bae8d9aeffc0eb172be",
    "code_digest": "sha256:158b855c3e0ac899cda4dad7fbb69de6f879784e53a7215e0a7a35dc88f47fba",
}
LOG = log.get_logger("experiment_input.gndcrw")
#: GNDCRW presentation / diagnostics settings BVL controls for the subprocess (#75)
GNDCRW_LOCALE = "en-US"
GNDCRW_UNSET_ENV = ("GNDCRW_LOG_FILE", "GNDCRW_LOG_LEVEL")
#: how many stderr lines are searched for the `gndcrw: error:` line
STDERR_SCAN_LINES = 16


def baseline(tool: dict) -> dict:
    match = tool.get("code_digest") == INTEGRATION_BASELINE["code_digest"]
    return {**INTEGRATION_BASELINE, "status": "MATCH" if match else "DIFFERS"}
ARGV = ("check", GNDCRW_MANIFEST_FILE, "--format", "json", "--gate")
RESULT_KEYS = ("binding", "comparison_mode", "contracts", "findings", "limitations",
               "outcome", "policy_id", "premises", "result_version", "subject", "summary",
               "tool")
BINDING_LIMITATIONS = ["EXTERNAL_SUBJECT_PROVIDER_ATTESTED", "TOOL_CODE_SELF_REPORTED"]
GATE_EXIT = {"RUN": 0, "BLOCK": 10, "UNVERIFIABLE": 11}
#: RESULT_CONTRACT (v0.1 semantics, carried unchanged by v0.2 §1) §8-§9: the closed
#: finding status and policy-class vocabularies and their allowed combinations
STATUSES = ("PASS", "FAIL", "WARNING", "UNVERIFIABLE", "NOT_APPLICABLE")
POLICY_STATUSES = {
    "BLOCKING": ("PASS", "FAIL", "UNVERIFIABLE", "NOT_APPLICABLE"),
    "REQUIRED_NONBLOCKING": ("PASS", "FAIL", "WARNING", "UNVERIFIABLE", "NOT_APPLICABLE"),
    "ADVISORY": ("PASS", "WARNING", "NOT_APPLICABLE"),
}
#: declaration sections whose rules each yield a finding carrying their rule_id (§11)
DECLARED_RULES = ("expected_changes", "invariants", "declared_consequences")
#: MINOR-10, transcribed from GNDCRW cace4dea, unchanged at cd05a4e (RESULT_CONTRACT §6-§7,
#: §11, §20-§21, VERIFICATION_SEMANTICS §9-§19, DECLARATION_CONTRACT; the same table as its
#: independent qualification oracle `qualification/spec_oracle.py` REASONS). Every public
#: reason code fixes exactly one (status, policy_class): an expected-change / invariant rule
#: is BLOCKING, a declared consequence, an undeclared difference and a premise are ADVISORY, and
#: REQUIRED_NONBLOCKING is reserved in v0.1 (D-06) - no v0.1 finding carries it.
REASONS = {
    "EXPECTED_CHANGE_ASSEMBLED": ("PASS", "BLOCKING"),
    "EXPECTED_CHANGE_MISSING": ("FAIL", "BLOCKING"),
    "INVARIANT_HELD": ("PASS", "BLOCKING"),
    "INVARIANT_VIOLATED": ("FAIL", "BLOCKING"),
    "UNDECLARED_DIFFERENCE": ("WARNING", "ADVISORY"),
    "DECLARED_CONSEQUENCE_OBSERVED": ("WARNING", "ADVISORY"),
    "DECLARED_CONSEQUENCE_NOT_OBSERVED": ("NOT_APPLICABLE", "ADVISORY"),
    "DECLARED_CONSEQUENCE_UNOBSERVABLE": ("WARNING", "ADVISORY"),
    "COMPOSITION_CHANGE_ASSEMBLED": ("PASS", "BLOCKING"),
    "COMPOSITION_CHANGE_MISSING": ("FAIL", "BLOCKING"),
    "COMPOSITION_INVARIANT_HELD": ("PASS", "BLOCKING"),
    "COMPOSITION_INVARIANT_VIOLATED": ("FAIL", "BLOCKING"),
    "ENTITY_COMPARABILITY_UNKNOWN": ("UNVERIFIABLE", "BLOCKING"),
    "ENTITY_COMPARABILITY_NOT_ESTABLISHED": ("UNVERIFIABLE", "BLOCKING"),
    "ENTITY_MAPPING_MISSING": ("UNVERIFIABLE", "BLOCKING"),
    "TARGET_UNOBSERVABLE": ("UNVERIFIABLE", "BLOCKING"),
    "TARGET_MISSING": ("UNVERIFIABLE", "BLOCKING"),
    "TARGET_UNSUPPORTED": ("UNVERIFIABLE", "BLOCKING"),
    "TARGET_AMBIGUOUS": ("UNVERIFIABLE", "BLOCKING"),
    "TARGET_ASSERTED_ONLY": ("UNVERIFIABLE", "BLOCKING"),
    "INVALID_DECLARATION_TARGET": ("FAIL", "BLOCKING"),
    "INVALID_DECLARATION_SCOPE": ("FAIL", "BLOCKING"),
    "INVALID_DECLARATION_OPERATION": ("FAIL", "BLOCKING"),
    "CONTRADICTORY_DECLARATION": ("FAIL", "BLOCKING"),
    "NO_FOCAL_EXPECTED_CHANGE": ("FAIL", "BLOCKING"),
    "INVALID_COMPARISON_MODE": ("FAIL", "BLOCKING"),
    "ASSEMBLY_EQUIVALENCE_PROVEN": ("PASS", "BLOCKING"),
    "ASSEMBLY_EQUIVALENCE_MISSING": ("UNVERIFIABLE", "BLOCKING"),
    "ASSEMBLY_EQUIVALENCE_MISMATCH": ("FAIL", "BLOCKING"),
    "REQUIRED_PROVENANCE_MISSING": ("UNVERIFIABLE", "BLOCKING"),
    "ATTRIBUTED_PREMISE_USED": ("WARNING", "ADVISORY"),
}
#: §7 assignment and the VS §11.2 ladder: the reason codes each emitted finding kind carries.
#: ENTITY_COMPARABILITY (kind) and REFERENCE_COMPARISON_ONLY (reason) are reserved, never
#: emitted by check v0.1: neither is accepted.
_UNOBSERVED = ("TARGET_UNOBSERVABLE", "TARGET_MISSING", "TARGET_UNSUPPORTED", "TARGET_AMBIGUOUS",
               "TARGET_ASSERTED_ONLY", "ENTITY_COMPARABILITY_UNKNOWN",
               "ENTITY_COMPARABILITY_NOT_ESTABLISHED", "ENTITY_MAPPING_MISSING")
KIND_REASONS = {
    "EXPECTED_CHANGE": ("EXPECTED_CHANGE_ASSEMBLED", "EXPECTED_CHANGE_MISSING", *_UNOBSERVED),
    "INVARIANT": ("INVARIANT_HELD", "INVARIANT_VIOLATED", *_UNOBSERVED),
    "COMPOSITION": ("COMPOSITION_CHANGE_ASSEMBLED", "COMPOSITION_CHANGE_MISSING",
                    "COMPOSITION_INVARIANT_HELD", "COMPOSITION_INVARIANT_VIOLATED"),
    "DECLARED_CONSEQUENCE": ("DECLARED_CONSEQUENCE_OBSERVED",
                             "DECLARED_CONSEQUENCE_NOT_OBSERVED",
                             "DECLARED_CONSEQUENCE_UNOBSERVABLE"),
    "UNDECLARED_DIFFERENCE": ("UNDECLARED_DIFFERENCE",),
    "DECLARATION_PRECONDITION": ("INVALID_DECLARATION_TARGET", "INVALID_DECLARATION_SCOPE",
                                 "INVALID_DECLARATION_OPERATION", "CONTRADICTORY_DECLARATION",
                                 "NO_FOCAL_EXPECTED_CHANGE", "INVALID_COMPARISON_MODE"),
    "ASSEMBLY_FIDELITY": ("ASSEMBLY_EQUIVALENCE_PROVEN", "ASSEMBLY_EQUIVALENCE_MISSING",
                          "ASSEMBLY_EQUIVALENCE_MISMATCH"),
    "PROVENANCE": ("REQUIRED_PROVENANCE_MISSING",),
    "PREMISE": ("ATTRIBUTED_PREMISE_USED",),
}
#: kinds that evaluate one declared rule (finding_id = rule_id, §6.1, §11) -> the declaration
#: section it comes from (§7); COMPOSITION's section follows its reason's operation
RULE_KINDS = {"EXPECTED_CHANGE": "expected_changes", "INVARIANT": "invariants",
              "DECLARED_CONSEQUENCE": "declared_consequences", "COMPOSITION": None}
#: verifier-generated kinds whose rule_id / target / scope are null (§6.1)
NULL_TARGET_KINDS = ("ASSEMBLY_FIDELITY", "PROVENANCE", "PREMISE")
#: the closed finding member set (§6; the pinned result schema is additionalProperties false)
FINDING_MEMBERS = frozenset((
    "finding_version", "finding_id", "rule_id", "finding_kind", "status", "policy_class",
    "reason_code", "target", "observation_level", "scope", "expected", "observed",
    "evidence_pointers", "premise_refs", "limitation_refs"))
FINDING_VERSION = "gndcrw-finding/v0.1"
TARGET_KINDS = ("TARGET", "COMPOSITION")
V01_CONTRACTS = {key: value for key, value in GNDCRW_CONTRACTS.items() if key != "manifest"}
STDERR_LINE = re.compile(r"gndcrw: error: ([A-Z][A-Z0-9_]*): ?(.*)")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
CAPABILITY_TIMEOUT = 60
CHECK_TIMEOUT = 600


def _capability(code: str, detail: str, evidence: dict | None = None) -> InputRefusal:
    return InputRefusal("CAPABILITY_ERROR", code, detail, layer="I4", path="argv#",
                        evidence=evidence)


def _tool(code: str, detail: str, evidence: dict | None = None) -> InputRefusal:
    return InputRefusal("GNDCRW_TOOL_FAILURE", code, detail, layer="I6", path="gndcrw:result#",
                        evidence=evidence)


@dataclass(frozen=True)
class Executable:
    path: str
    sha256: str
    version: str
    capabilities: dict

    def document(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "version": self.version}


def locate(explicit: str | None) -> Path:
    """P: the operator's absolute path, or one PATH lookup."""
    if explicit is not None:
        path = Path(explicit)
        if not path.is_absolute():
            raise InputRefusal("USAGE_ERROR", "ARGUMENT_INVALID", "--gndcrw is an absolute path",
                               layer="CLI", path="argv#")
    else:
        found = shutil.which("gndcrw")
        if found is None:
            raise _capability("GNDCRW_NOT_INSTALLED", "no `gndcrw` on PATH; pass --gndcrw")
        path = Path(found)
    path = path.resolve()
    if not path.is_file():
        raise _capability("GNDCRW_NOT_INSTALLED", f"{path} is not an executable file")
    return path


def _digest_file(path: Path) -> str:
    try:
        return str(sha256_bytes(path.read_bytes()))
    except OSError as error:
        raise _capability("GNDCRW_NOT_INSTALLED", f"cannot read {path}: {error}") from None


def environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The GNDCRW subprocess environment: the caller's, with GNDCRW's presentation
    pinned to en-US and its diagnostic log sink removed (#75)."""
    env = {key: value for key, value in (os.environ if base is None else base).items()
           if key not in GNDCRW_UNSET_ENV}
    env["GNDCRW_LOCALE"] = GNDCRW_LOCALE
    return env


def _run(argv: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=timeout, check=False, env=environment())


def probe(explicit: str | None) -> Executable:
    """I4: resolve P and require manifest-mode capability. Fails closed."""
    path = locate(explicit)
    h0 = _digest_file(path)
    probe_dir = Path(tempfile.mkdtemp(prefix="bvl-gndcrw-probe-"))
    try:
        try:
            done = _run([str(path), "capabilities"], probe_dir, CAPABILITY_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as error:
            raise _capability("GNDCRW_NOT_INSTALLED", f"{path} capabilities: {error!r}") from None
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    if done.returncode != 0:
        raise _capability("GNDCRW_CAPABILITY_UNSUPPORTED",
                          f"`gndcrw capabilities` exited {done.returncode}",
                          evidence=_stderr_evidence(done.returncode, done.stderr))
    try:
        listing = load_bytes(done.stdout)
    except MalformedJSON as error:
        raise _capability("GNDCRW_CAPABILITY_UNSUPPORTED", f"capabilities: {error}") from None
    manifest = listing.get("manifest") if isinstance(listing, dict) else None
    tool = listing.get("tool") if isinstance(listing, dict) else None
    version = tool.get("version") if isinstance(tool, dict) else None
    problems = []
    if not isinstance(manifest, dict) or GNDCRW_ATTACHMENT["manifest_version"] not in (
            manifest.get("manifest_versions") or ()):
        problems.append("gndcrw-manifest/v0.2 is not supported")
    elif manifest.get("result_version") != GNDCRW_ATTACHMENT["result_version"]:
        problems.append(f"manifest result_version {manifest.get('result_version')!r}")
    if GNDCRW_ATTACHMENT["policy"] not in (listing.get("policy_ids") or ()):
        problems.append("policy GNDCRW-STRICT-0.1 is not listed")
    if listing.get("contracts") != V01_CONTRACTS:
        problems.append(f"contracts {listing.get('contracts')!r}")
    if not isinstance(tool, dict) or tool.get("name") != "gndcrw":
        problems.append("tool.name is not gndcrw")
    if problems:
        raise _capability("GNDCRW_CAPABILITY_UNSUPPORTED", "; ".join(problems))
    if version not in PINNED_VERSIONS:
        raise _capability("GNDCRW_VERSION_UNSUPPORTED",
                          f"gndcrw {version!r}; this build is pinned to {list(PINNED_VERSIONS)}")
    return Executable(str(path), h0, version, listing)


def manifest_bytes(subjects: dict[str, Snapshot], contract: str) -> bytes:
    """The BVL-generated `gndcrw-manifest/v0.2`: a deterministic function of C and
    the five {sha256, size} under BVL's fixed subject names."""
    return canonical_bytes({
        "external_subject": {"digest": contract, "scheme": EXTERNAL_SCHEME},
        "manifest_version": GNDCRW_ATTACHMENT["manifest_version"],
        "subjects": {role: {"path": GNDCRW_SUBJECT_FILES[role], **subjects[role].raw()}
                     for role in ROLES},
    })


@dataclass(frozen=True)
class Preflight:
    """What I6 established: the exact manifest and result bytes, and the facts
    BVL read off the result after checking it."""

    executable: Executable
    manifest: bytes
    result: bytes
    exit_code: int
    outcome: str
    tool: dict

    @property
    def argv(self) -> list[str]:
        return list(ARGV)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _stderr_line(raw: bytes) -> str:
    return raw.rstrip(b"\r")[:1024].decode("utf-8", "backslashreplace")


def error_code(stderr: bytes) -> str | None:
    """The stable GNDCRW error code: from the first `gndcrw: error: <CODE>: ...` line among
    the first STDERR_SCAN_LINES, never from the (localized) wording after it."""
    for raw in stderr.split(b"\n", STDERR_SCAN_LINES)[:STDERR_SCAN_LINES]:
        match = STDERR_LINE.fullmatch(_stderr_line(raw))
        if match:
            return match.group(1)
    return None


def _stderr_evidence(exit_code: int, stderr: bytes) -> dict:
    """Bounded stderr facts. Never an identity root."""
    first = _stderr_line(stderr.split(b"\n", 1)[0])
    return {"process_exit": exit_code,
            "gndcrw_error_code": error_code(stderr),
            "stderr_first_line": first or None,
            "stderr_sha256": str(sha256_bytes(stderr)), "stderr_size": len(stderr)}


def invoke(executable: Executable, subjects: dict[str, Snapshot], contract: str) -> Preflight:
    """I6: snapshot -> manifest -> `gndcrw check` -> checked result."""
    manifest = manifest_bytes(subjects, contract)
    staging = Path(tempfile.mkdtemp(prefix="bvl-preflight-"))   # 0700 on POSIX
    try:
        for role in ROLES:
            _write(staging / GNDCRW_SUBJECT_FILES[role], subjects[role].data)
        _write(staging / GNDCRW_MANIFEST_FILE, manifest)
        if _digest_file(Path(executable.path)) != executable.sha256:
            raise _tool("TOOL_CHANGED", f"{executable.path} changed after the capability check")
        try:
            done = _run([executable.path, *ARGV], staging, CHECK_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise _tool("ABNORMAL_EXIT", f"gndcrw check timed out after {CHECK_TIMEOUT}s") \
                from None
        except OSError as error:
            raise _tool("ABNORMAL_EXIT", f"gndcrw check could not start: {error!r}") from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    evidence = _stderr_evidence(done.returncode, done.stderr)
    log.event(LOG, logging.INFO, "gndcrw.checked", gndcrw_exit=done.returncode,
              gndcrw_error_code=evidence["gndcrw_error_code"])
    if done.returncode in (0, 10, 11):
        return _checked(executable, manifest, subjects, contract, done.stdout, done.returncode,
                        evidence)
    raise _refusal(done.returncode, evidence)


def _refusal(exit_code: int, evidence: dict) -> InputRefusal:
    code = evidence["gndcrw_error_code"]
    detail = evidence["stderr_first_line"] or f"gndcrw exited {exit_code}"
    if exit_code == 3:
        if code is None:
            return _tool("GNDCRW_ERROR_UNCLASSIFIED", detail, evidence)
        if code.startswith("REF_"):
            return InputRefusal("INPUT_DRIFT", "GNDCRW_SNAPSHOT_INTEGRITY",
                                f"GNDCRW refused BVL's private snapshot ({code}): {detail}",
                                layer="I6", path="gndcrw:result#", evidence=evidence)
        if code.startswith("MANIFEST_"):
            return _tool("GNDCRW_MANIFEST_REFUSED", detail, evidence)
        return InputRefusal("GNDCRW_INPUT_ERROR", "GNDCRW_INPUT_INVALID", detail, layer="I6",
                            path="gndcrw:result#", evidence=evidence)
    named = {2: "GNDCRW_USAGE", 4: "GNDCRW_PROVIDER", 5: "GNDCRW_INTERNAL", 6: "GNDCRW_OUTPUT"}
    return _tool(named.get(exit_code, "ABNORMAL_EXIT"), detail, evidence)


def aggregate(findings: list[dict]) -> str:
    """§10 GNDCRW-STRICT-0.1: the outcome the findings determine."""
    blocking = [f["status"] for f in findings if f["policy_class"] == "BLOCKING"]
    if "FAIL" in blocking:
        return "BLOCK"
    return "UNVERIFIABLE" if "UNVERIFIABLE" in blocking else "RUN"


def _enum(finding: dict, key: str, allowed) -> str | None:
    """A closed-vocabulary string member, or None. The isinstance test comes first, so an
    object / list value is never hashed (REC-028)."""
    value = finding.get(key)
    return value if isinstance(value, str) and value in allowed else None


def _target_problem(value) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"kind", "id"}
            or not isinstance(value["kind"], str) or value["kind"] not in TARGET_KINDS
            or not isinstance(value["id"], str)):
        return f"target {value!r} is not null or {{kind: TARGET|COMPOSITION, id: string}}"
    return None


def finding_problems(finding) -> list[str]:
    """REC-028 / MINOR-10 over one finding: first the member surface the semantic matrix
    reads (closed member set, types, closed vocabularies - never a traceback), then the
    pinned matrix: reason_code fixes (status, policy_class) (§20-§21), finding_kind fixes the
    reason codes (§7, VS §11.2) and the identity - a rule finding is finding_id = rule_id,
    a verifier-generated one has rule_id null (§6.1, §11)."""
    if not isinstance(finding, dict):
        return ["is not an object"]
    out = []
    if set(finding) != FINDING_MEMBERS:
        missing = sorted(FINDING_MEMBERS - set(finding))
        if "rule_id" in missing:
            out.append("has no rule_id member")
        return [*out, f"members: missing {missing}, "
                      f"unexpected {sorted(set(finding) - FINDING_MEMBERS)}"]
    if finding["finding_version"] != FINDING_VERSION:
        out.append(f"finding_version {finding['finding_version']!r} is not {FINDING_VERSION}")
    fid = finding["finding_id"]
    if not isinstance(fid, str) or not fid:
        out.append("has no finding_id")
    # MINOR-11: rule_id is a required member whose value is string | null (bool is not a
    # string; objects/lists are refused here, before anything hashes them)
    rule_id = finding["rule_id"]
    if rule_id is not None and not isinstance(rule_id, str):
        out.append(f"rule_id {rule_id!r} is not a string or null")
    policy = _enum(finding, "policy_class", POLICY_STATUSES)
    status = _enum(finding, "status", STATUSES)
    kind = _enum(finding, "finding_kind", KIND_REASONS)
    reason = _enum(finding, "reason_code", REASONS)
    if policy is None:
        out.append(f"policy_class {finding['policy_class']!r} is not one of "
                   f"{list(POLICY_STATUSES)}")
    elif status is None or status not in POLICY_STATUSES[policy]:
        out.append(f"status {finding['status']!r} is not allowed under {policy} "
                   f"{list(POLICY_STATUSES[policy])}")
    if kind is None:
        out.append(f"finding_kind {finding['finding_kind']!r} is not an emitted v0.1 kind")
    if reason is None:
        out.append(f"reason_code {finding['reason_code']!r} is not a v0.1 public reason code")
    target, scope = finding["target"], finding["scope"]
    if _target_problem(target):
        out.append(_target_problem(target))
    if scope is not None and not (isinstance(scope, dict) and isinstance(scope.get("kind"), str)):
        out.append(f"scope {scope!r} is not null or an object with a string kind")
    if out:
        return out   # the matrix is over well-typed closed values only
    if REASONS[reason] != (status, policy):
        out.append(f"reason_code {reason} is {'/'.join(REASONS[reason])} under "
                   f"GNDCRW-STRICT-0.1, not {status}/{policy}")
    if reason not in KIND_REASONS[kind]:
        out.append(f"reason_code {reason} is not a {kind} reason")
    if kind in RULE_KINDS:
        if rule_id is None or fid != rule_id or target is None or scope is None:
            out.append(f"a {kind} finding evaluates one declared rule: finding_id = rule_id "
                       f"(a string), target and scope present")
    elif kind == "UNDECLARED_DIFFERENCE":
        if (rule_id is not None or target is None or scope is None
                or fid != f"UD::{target['kind']}::{target['id']}"):
            out.append("an UNDECLARED_DIFFERENCE finding is UD::<target.kind>::<target.id> "
                       "with rule_id null and a scope")
    elif kind == "DECLARATION_PRECONDITION":
        if not fid.startswith(f"PRE::{reason}::"):
            out.append(f"a precondition finding_id starts PRE::{reason}::")
        if reason.startswith("INVALID_DECLARATION_"):
            if rule_id is None or fid != f"PRE::{reason}::{rule_id}":
                out.append(f"a rule-level precondition is PRE::{reason}::<rule_id> carrying "
                           f"that rule_id")
        elif rule_id is not None:
            out.append(f"a {reason} precondition has rule_id null")
    elif (not fid.startswith(f"PRE::{reason}::") or rule_id is not None
            or target is not None or scope is not None):   # NULL_TARGET_KINDS
        out.append(f"a {kind} finding is PRE::{reason}::<subject> with rule_id, target and "
                   f"scope null")
    return out


def declared_rules(declaration: bytes) -> dict[str, tuple[str, object]]:
    """rule_id -> (declaration section, rule target) over the declaration snapshot."""
    rules: dict[str, tuple[str, object]] = {}
    document = load_bytes(declaration)
    for key in DECLARED_RULES:
        for rule in document.get(key) or ():
            rule_id = rule["rule_id"]
            if not isinstance(rule_id, str) or rule_id in rules:
                raise TypeError(f"rule_id {rule_id!r} is not a unique string")
            rules[rule_id] = (key, rule.get("target"))
    return rules


def binding_problems(finding: dict, rules: dict) -> list[str]:
    """MINOR-10: a finding with a string rule_id is bound to that declared rule - its kind
    to the rule's section (§7) and its target to the rule's target (§6.1)."""
    rule_id, kind, reason = finding["rule_id"], finding["finding_kind"], finding["reason_code"]
    if rule_id is None:
        return []
    if rule_id not in rules:
        return [f"rule_id {rule_id} is not a declared rule"]
    if kind not in RULE_KINDS:
        return []   # INVALID_DECLARATION_*: the rule's own precondition, in any section
    section, target = rules[rule_id]
    wanted = RULE_KINDS[kind] or ("expected_changes" if reason.startswith("COMPOSITION_CHANGE_")
                                  else "invariants")
    out = []
    if section != wanted:
        out.append(f"a {kind} {reason} finding cannot evaluate the {section} rule {rule_id}")
    if finding["target"] != target:
        out.append(f"target {finding['target']} is not rule {rule_id}'s target {target}")
    elif (target["kind"] == "COMPOSITION") != (kind == "COMPOSITION") \
            and kind != "DECLARED_CONSEQUENCE":
        out.append(f"a {kind} finding cannot evaluate a {target['kind']} target (§7)")
    return out


def semantic_problems(result: dict, declaration: bytes | None = None) -> list[str]:
    """MINOR-6 / MINOR-10: the result means one thing. Per finding the typed member surface
    and the pinned semantic matrix (finding_problems); the summary recomputed from the
    findings (§17); the outcome recomputed by the STRICT aggregation (§10); and - with the
    declaration snapshot - exactly one finding per declared rule, bound to it (§7, §11,
    VS §11.2). So a RUN whose findings were removed, relabelled or demoted is not a RUN.
    Empty list: consistent."""
    problems: list[str] = []
    findings = result["findings"]
    ids = []
    for index, finding in enumerate(findings):
        problems += [f"findings[{index}] {p}" for p in finding_problems(finding)]
        if isinstance(finding, dict) and isinstance(finding.get("finding_id"), str):
            ids.append(finding["finding_id"])
    if len(ids) != len(set(ids)):
        problems.append("finding_id values repeat")
    if problems:
        return problems   # the summary and the outcome are over closed values only
    summary = {"finding_count": len(findings),
               "by_status": {s: sum(f["status"] == s for f in findings) for s in STATUSES},
               "by_policy_class": {c: sum(f["policy_class"] == c for f in findings)
                                   for c in POLICY_STATUSES}}
    if result["summary"] != summary:
        problems.append(f"summary {result['summary']} does not recompute from the findings "
                        f"({summary})")
    if aggregate(findings) != result["outcome"]:
        problems.append(f"outcome {result['outcome']} is not the STRICT aggregation of the "
                        f"findings ({aggregate(findings)})")
    if declaration is not None:
        try:
            rules = declared_rules(declaration)
        except (MalformedJSON, AttributeError, TypeError, KeyError) as error:
            return [*problems, f"the declaration snapshot cannot be read: {error!r}"]
        for index, finding in enumerate(findings):
            problems += [f"findings[{index}] {p}" for p in binding_problems(finding, rules)]
        # only a string rule_id covers a declared rule; a null finding covers none
        bound = [f["rule_id"] for f in findings if f["rule_id"] is not None]
        missing = sorted(set(rules) - set(bound))
        if missing:
            problems.append(f"declared rules {missing} have no finding")
        repeated = sorted({r for r in bound if bound.count(r) > 1})
        if repeated:
            problems.append(f"declared rules {repeated} have more than one finding")
    return problems


def check_result(data: bytes, *, manifest: bytes, subjects: dict[str, dict], contract: str,
                 version: str, exit_code: int | None, declaration: bytes | None = None) -> dict:
    """RESULT_CONTRACT_V0_2 §5 over exact result bytes. Returns the parsed result.

    `subjects` maps each role to the {sha256, size} BVL holds for it;
    `declaration`, the declaration snapshot bytes, adds the per-rule coverage check.
    """
    def invalid(detail: str) -> InputRefusal:
        return _tool("RESULT_INVALID", detail)

    def mismatch(detail: str) -> InputRefusal:
        return InputRefusal("INPUT_DRIFT", "GNDCRW_BINDING_MISMATCH", detail, layer="I6",
                            path="gndcrw:result#/binding")

    if len(data) > MIB16:
        raise _tool("RESULT_TOO_LARGE", f"{len(data)} bytes")
    try:
        result = load_bytes(data)
    except MalformedJSON as error:
        raise invalid(f"not strict JSON: {error}") from None
    if not isinstance(result, dict):
        raise invalid("the result is not an object")
    if tuple(sorted(result)) != RESULT_KEYS:
        raise invalid(f"top-level members {sorted(result)}")
    if result["result_version"] != GNDCRW_ATTACHMENT["result_version"]:
        raise invalid(f"result_version {result['result_version']!r}")
    if result["contracts"] != GNDCRW_CONTRACTS:
        raise _tool("RESULT_CONTRACT_MISMATCH", f"contracts {result['contracts']!r}")
    if result["policy_id"] != GNDCRW_ATTACHMENT["policy"]:
        raise invalid(f"policy_id {result['policy_id']!r}")
    tool = result["tool"]
    if (not isinstance(tool, dict) or tool.get("name") != "gndcrw"
            or tool.get("version") != version
            or tool.get("code_digest_method") != "gndcrw-code-digest/v0.2"
            or not DIGEST.fullmatch(str(tool.get("code_digest")))):
        raise invalid(f"tool {tool!r} (expected gndcrw {version})")
    for key, kind in (("findings", list), ("premises", list), ("limitations", list),
                      ("summary", dict), ("subject", dict)):
        if not isinstance(result[key], kind):
            raise invalid(f"{key} is not a{'n object' if kind is dict else ' list'}")
    outcome = result["outcome"]
    if outcome not in GATE_EXIT:
        raise invalid(f"outcome {outcome!r}")
    if exit_code is not None and GATE_EXIT[outcome] != exit_code:
        raise _tool("EXIT_OUTCOME_MISMATCH", f"exit {exit_code} with outcome {outcome}")
    semantics = semantic_problems(result, declaration)
    if semantics:
        raise _tool("RESULT_SEMANTICS_INVALID", "; ".join(semantics))

    binding = result["binding"]
    if not isinstance(binding, dict) or set(binding) != {"manifest", "subjects",
                                                         "external_subject", "limitations"}:
        raise invalid("binding is not the closed v0.2 binding")
    held_manifest = {"sha256": str(sha256_bytes(manifest)), "size": len(manifest)}
    if binding["manifest"] != held_manifest:
        raise mismatch(f"binding.manifest {binding['manifest']} != {held_manifest}")
    if not isinstance(binding["subjects"], dict) or set(binding["subjects"]) != set(ROLES):
        raise mismatch(f"binding.subjects names {sorted(binding['subjects'] or ())}")
    for role in ROLES:
        if binding["subjects"][role] != dict(subjects[role]):
            raise mismatch(f"binding.subjects.{role} {binding['subjects'][role]} != "
                           f"{dict(subjects[role])}")
    external = {"scheme": EXTERNAL_SCHEME, "digest": contract}
    if binding["external_subject"] != external:
        raise mismatch(f"binding.external_subject {binding['external_subject']} != {external}")
    if binding["limitations"] != BINDING_LIMITATIONS:
        raise invalid(f"binding.limitations {binding['limitations']}")
    return result


def _checked(executable: Executable, manifest: bytes, subjects: dict[str, Snapshot],
             contract: str, stdout: bytes, exit_code: int, evidence: dict) -> Preflight:
    result = check_result(stdout, manifest=manifest,
                          subjects={role: s.raw() for role, s in subjects.items()},
                          contract=contract, version=executable.version, exit_code=exit_code,
                          declaration=subjects["declaration"].data)
    # #76 C: a BLOCK / UNVERIFIABLE outcome is a checked result, not a failure. The
    # execution gate (`experiment_input.gate`) decides from it; no run is created.
    return Preflight(executable, manifest, stdout, exit_code, result["outcome"],
                     dict(result["tool"]))

