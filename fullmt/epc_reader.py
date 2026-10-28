"""FULLMT package reader — an independent consumer of BOOMVALLEY Lab packages.

This file is the one entry point (the `fullmt` command) and the historical EPC reader.
It dispatches on the package root, and nothing is guessed forward:

    EVIDENCE.json only      historical EPC (this module, unchanged semantics)
    MANIFEST-4.json only    current `bvl-study-1` package (manifest4_reader, FULLMT-owned)
    both                    ERROR AMBIGUOUS_PACKAGE_FORMAT
    neither                 ERROR NOT_AN_EPC_PACKAGE (PACKAGE.json is never a fallback)

EPC: FULLMT is handed a directory. It reads `EVIDENCE.json` and the members that file
lists, and it recomputes everything it checks from those bytes. It shares no code
with the producer (BVL): no product module, no BVL helper, no BVL verifier. It never
uses `PACKAGE.json` semantics and never decides what a file *is* from its name when
the manifest already declares a role for it (EPC design §6.1, §20, §21).

Version dispatch: `manifest_schema` selects a handler; the handler then refuses any
canonical format, digest algorithm or identity version it was not written for.
Nothing is guessed forward.

    python scripts/fullmt/epc_reader.py <package-dir> [--out result.json]

Exit codes: 0 VERIFIED · 1 REJECTED · 2 ERROR (not an EPC, unsupported, unreadable), or a
VERIFIED / REJECTED verdict whose --out file could not be written (stdout `delivery`).
The result document is `fullmt-epc-verification-result/1` (see RESULT_SCHEMA) for an EPC
and `fullmt-manifest4-verification-result/1` for a MANIFEST-4 package.

Codes: outcome / rule status (fullmt_codes.Outcome / RuleStatus), program-failure codes
(fullmt_codes.ErrorCode, only on ERROR) and rule ids (fullmt_rules.RULES, only on
REJECTED) are separate vocabularies, each defined once and never localized. stdout is
the CLI contract; diagnostics go to the "fullmt" logger on stderr (--log-level), human
text through fullmt_i18n (--locale / $FULLMT_LOCALE: en-US, ko-KR).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from fullmt_codes import (EXIT_CODES, EXIT_DELIVERY_FAILED, DeliveryStatus, ErrorCode, Outcome,
                          RuleStatus)
from fullmt_i18n import SUPPORTED_LOCALES, set_locale, t
from fullmt_log import LEVELS, configure as configure_logging, get_logger
from fullmt_rules import RULES

import manifest4_reader as m4

READER_NAME = "fullmt-epc-reader"
READER_VERSION = "0.12.0"
RESULT_SCHEMA = "fullmt-epc-verification-result/1"

MANIFEST = "EVIDENCE.json"

VERIFIED, REJECTED, ERROR = Outcome.VERIFIED, Outcome.REJECTED, Outcome.ERROR
PASS, FAIL, NOT_EVALUATED = RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.NOT_EVALUATED
# the reader's own code: the modules its verdicts and messages come from (code_digest)
CODE_DIGEST_METHOD = "git-source-manifest-v1"
READER_SOURCES = ("epc_reader.py", "manifest4_reader.py", "fullmt_codes.py", "fullmt_rules.py",
                  "fullmt_i18n.py", "fullmt_log.py", "locales/en-US.json", "locales/ko-KR.json")

log = get_logger("reader")

SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}
MAX_SAFE_INTEGER = 2 ** 53 - 1


class ReaderError(Exception):
    """The reader could not act on the input at all → outcome ERROR (never a rule)."""

    def __init__(self, code: ErrorCode, detail: str):
        code = ErrorCode(code)  # an unregistered code is a defect, not a new vocabulary
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


class Malformed(ValueError):
    """A document is not strict JSON / not canonical (a conformance failure)."""


# ============================================================ strict read (§16.4)
def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Malformed(f"duplicate member name {key!r}")
        out[key] = value
    return out


def _no_constant(name):
    raise Malformed(f"{name} is not JSON")


def _check_values(value, where="$", allow_null=False):
    if value is None and allow_null:
        return
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise Malformed(f"{where}: integer outside ±(2^53-1)")
    elif isinstance(value, float):
        if not math.isfinite(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
            raise Malformed(f"{where}: number has no canonical form")
    elif isinstance(value, str):
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise Malformed(f"{where}: lone surrogate")
    elif isinstance(value, dict):
        for key, item in value.items():
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in key):
                raise Malformed(f"{where}: lone surrogate in a member name")
            if item is None and not allow_null:
                raise Malformed(f"{where}.{key}: null never appears in canonical-json-1")
            _check_values(item, f"{where}.{key}", allow_null)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if item is None and not allow_null:
                raise Malformed(f"{where}[{index}]: null never appears in canonical-json-1")
            _check_values(item, f"{where}[{index}]", allow_null)


def strict_json(data: bytes, allow_null: bool = False):
    """Parse one JSON document under the EPC read rules.

    allow_null is for foreign documents (GNDCRW's own contracts) carried as raw-bound
    snapshots: they must still be strict JSON, but canonical-json-1's null ban is the
    producer's rule for its own normative documents, not theirs."""
    if data.startswith(b"\xef\xbb\xbf"):
        raise Malformed("BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Malformed(f"invalid UTF-8: {error}") from None
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_no_constant)
    except json.JSONDecodeError as error:
        raise Malformed(str(error)) from None
    _check_values(value, allow_null=allow_null)
    return value


def strict_jsonl(data: bytes) -> tuple[list, int]:
    """Parse JSONL; a trailing segment without a newline is a torn tail (discarded).

    Returns (documents, acknowledged_bytes)."""
    end = data.rfind(b"\n") + 1
    lines = data[:end].split(b"\n")[:-1]
    return [strict_json(line) for line in lines], end


# ====================================================== canonical-json-1 (§16.2)
def canonical(value) -> bytes:
    _check_values(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def raw_ref(data: bytes) -> dict:
    return {"sha256": sha(data), "size": len(data)}


# ============================================================== version dispatch
# What this reader was written against. Anything else is refused, never assumed.
EPC_1_FORMATS = {"canonical_format": "canonical-json-1", "digest_algorithm": "sha256"}
EPC_1_IDENTITY_VERSIONS = {
    "artifact_content": "raw-1",
    "contract": "declaration-1",
    "custody_seal": "custody-head-2",
    "dataset": "dataset-identity-2",
    "design": "design-1",
    "evidence_root": "evidence-root/1",
    "experiment_input": "bvl-experiment-input-identity-2",
    "package": "package/1",
    "request": "request-1",
    "run": "run/1",
    "schedule": "schedule-1",
}
EPC_1_ROLES = {
    "lock", "run", "journal", "custody_entries", "custody_head", "declaration", "design",
    "schedule", "dataset", "claims", "eligibility_report", "producer_provenance",
    "environment", "legacy_package_manifest", "artifact", "request", "request_envelope",
    "analysis", "experiment_input", "gndcrw_manifest", "gndcrw_result",
    "gndcrw_subject_declaration", "gndcrw_subject_target_catalog",
    "gndcrw_subject_base_surface", "gndcrw_subject_candidate_surface",
    "gndcrw_subject_pair_context",
}
REQUIRED_ONCE = ("lock", "run", "journal", "custody_entries", "custody_head", "declaration",
                 "design", "schedule", "dataset", "eligibility_report",
                 "producer_provenance", "environment")
OPTIONAL_ONCE = ("legacy_package_manifest", "claims")
SUBJECT_PREFIX = "gndcrw_subject_"
INPUT_LOCK_ROLES = ("experiment_input", "gndcrw_manifest", "gndcrw_result",
                    "gndcrw_subject_declaration", "gndcrw_subject_target_catalog",
                    "gndcrw_subject_base_surface", "gndcrw_subject_candidate_surface",
                    "gndcrw_subject_pair_context")
CANONICAL_AT_REST = {"lock", "run", "custody_head", "declaration", "design", "schedule",
                     "dataset", "eligibility_report", "producer_provenance", "environment",
                     "request", "request_envelope", "analysis", "legacy_package_manifest",
                     "experiment_input", "gndcrw_manifest", "claims"}
# GNDCRW-contract documents: bound by raw digest, strict-read, but not canonical-json-1.
FOREIGN_JSON_ROLES = {"gndcrw_result", "gndcrw_subject_declaration",
                      "gndcrw_subject_target_catalog", "gndcrw_subject_base_surface",
                      "gndcrw_subject_candidate_surface", "gndcrw_subject_pair_context"}
# EVIDENCE.json top level (§4 Package row, §6.4) is closed: an unknown member is refused
# (§16.4), even when package_identity was recomputed over it. input_lock is the Input Lock
# section; parents is LIN-001's input; informational sits outside package_identity.
MANIFEST_REQUIRED = {"manifest_schema", "formats", "run", "identities", "members", "journal",
                     "limitations", "evidence_root", "package_identity"}
MANIFEST_OPTIONAL = {"input_lock", "parents", "informational"}

# ------------------------------------------------ manifest-3 / producer-2 (BVL #114)
MANIFEST_1 = "boomvalley-epc-manifest-1"
MANIFEST_3 = "boomvalley-epc-manifest-3"
# -3 adds the gate decision and request-content sections to the closed top level. They
# are required and must be objects; request_content is checked by REQ-004, the gate is not
# re-derived (consumer limitation).
MANIFEST_3_SECTIONS = {"execution_gate", "request_content"}
# the producer_provenance member a -3 package must carry
PRODUCER_SCHEMA_3 = "boomvalley-epc-producer-2"
# LIM-001: the frozen limitation vocabulary (13 codes). -3 states each limitation as
# {code, free_text}; the code is the only decision input. free_text is checked as a
# bounded string and never read for a verdict.
LIMITATION_CODES = frozenset({
    "CLAIMS_NOT_EMITTED", "DATASET_NOT_ADMITTED",
    "GNDCRW_DECLARATION_NOT_DERIVED_FROM_EXPERIMENT",
    "GNDCRW_EXTERNAL_SUBJECT_PROVIDER_ATTESTED", "GNDCRW_TOOL_CODE_SELF_REPORTED",
    "JOURNAL_TORN_TAIL", "MODEL_VERSION_NOT_PINNED", "NOT_SIGNED",
    "PRODUCT_INTERNAL_STEPS_ATTESTED", "PROVENANCE_PACKAGE_TIME_ONLY",
    "REQUEST_CONTENT_WITHHELD", "REQUEST_UNAVAILABLE", "RUN_ID_LEGACY_LABEL",
})
LIMITATION_MEMBERS = {"code", "free_text"}
FREE_TEXT_MAX_CODE_POINTS = 1024
# LIM-002 (-3): the limitations the evidence establishes must be stated (BVL LIM-002).
# Standing: true of every package this producer writes; the GNDCRW_* set is exactly the
# Input Lock preflight record's; the others follow from the member set / input lock.
STANDING_LIMITATIONS = ("CLAIMS_NOT_EMITTED", "NOT_SIGNED", "PRODUCT_INTERNAL_STEPS_ATTESTED",
                        "PROVENANCE_PACKAGE_TIME_ONLY", "RUN_ID_LEGACY_LABEL")
GNDCRW_LIMITATION_PREFIX = "GNDCRW_"
DATASET_NOT_ADMITTED = "DATASET_NOT_ADMITTED"
MODEL_VERSION_NOT_PINNED = "MODEL_VERSION_NOT_PINNED"
# REQ-004 (-3): request_content is exactly one of three closed shapes, never mixed.
REQUEST_AVAILABLE, REQUEST_WITHHELD, REQUEST_UNAVAILABLE = "AVAILABLE", "WITHHELD", "UNAVAILABLE"
REQUEST_CONTENT_SHAPES = {
    REQUEST_AVAILABLE: {"request_content_status", "requests"},
    REQUEST_WITHHELD: {"request_content_status", "reason_code", "requests"},
    REQUEST_UNAVAILABLE: {"request_content_status", "reason_code"},
}
REQUEST_CONTENT_ENTRY_SHAPES = {
    REQUEST_AVAILABLE: {"record", "position", "digest", "size", "member"},
    REQUEST_WITHHELD: {"record", "position", "digest", "size"},
}
# reason_code -> the one status it belongs to
REQUEST_CONTENT_REASONS = {
    "REQUEST_WITHHELD_CONFIDENTIAL": REQUEST_WITHHELD,
    "REQUEST_WITHHELD_PERSONAL_DATA": REQUEST_WITHHELD,
    "REQUEST_WITHHELD_LICENSE_RESTRICTED": REQUEST_WITHHELD,
    "REQUEST_BUILDER_NOT_RECORDED": REQUEST_UNAVAILABLE,
}
# status -> the limitation that is stated iff the package has that status
REQUEST_CONTENT_LIMITATIONS = {REQUEST_WITHHELD: "REQUEST_CONTENT_WITHHELD",
                               REQUEST_UNAVAILABLE: "REQUEST_UNAVAILABLE"}
REQUEST_CONTENT_MEMBER = "requests/record-{position:06d}.json"
# stable problem codes of the -3 rules (LIM-002, REQ-004): the prefix of each problem line
PROBLEM_CODES = frozenset({
    "LIMITATION_NOT_STATED", "LIMITATION_NOT_ESTABLISHED", "LIMITATION_SET_UNREADABLE",
    "REQUEST_CONTENT_SHAPE_INVALID", "REQUEST_CONTENT_STATUS_UNKNOWN",
    "REQUEST_CONTENT_REASON_MISMATCH", "REQUEST_CONTENT_LIMITATION_MISMATCH",
    "REQUEST_CONTENT_UNAVAILABLE_ON_INPUT_LOCKED", "REQUEST_CONTENT_ENTRY_INVALID",
    "REQUEST_CONTENT_DIGEST_MISMATCH", "REQUEST_CONTENT_BYTES_MISMATCH",
    "REQUEST_CONTENT_NOT_ONE_PER_INTENT", "REQUEST_CONTENT_MEMBER_SET_MISMATCH",
    "REQUEST_ENVELOPE_NOT_IN_MANIFEST_3",
})
# JSONL members this reader consumes: every acknowledged line is canonical-json-1 + LF
# (§4 Journal row "canonical per line, LF"; custody entries are the same product records).
# The torn tail after the last LF is not a line (§17) and is left to JRN-004.
CANONICAL_JSONL = {"journal", "custody_entries"}
# A custody entry's `artifact` is a name in the run's artifact store (RUNTIME_AND_JOURNAL §8);
# the in-place package keeps that store at artifacts/ (§5, DEC-08: existing members keep
# their paths), so the sealed name binds exactly one member path.
ARTIFACT_STORE = "artifacts"
JSON_MEDIA = {"application/json"}
JSONL_MEDIA = {"application/x-ndjson", "application/jsonl"}
# JRN-003 journal grammar (EPC §17, RUNTIME_AND_JOURNAL): one attempt's history is
# INTENT_RECORDED -> (CALL_RETURNED -> ARTIFACT_PERSISTED | CALL_FAILED | RESPONSE_REJECTED);
# the run-terminal events end the run, after which only session teardown may follow.
ATTEMPT_TRANSITIONS = {
    (None, "INTENT_RECORDED"): "INTENT_RECORDED",
    ("INTENT_RECORDED", "CALL_RETURNED"): "CALL_RETURNED",
    ("INTENT_RECORDED", "CALL_FAILED"): "CALL_FAILED",
    ("INTENT_RECORDED", "RESPONSE_REJECTED"): "RESPONSE_REJECTED",
    ("CALL_RETURNED", "ARTIFACT_PERSISTED"): "ARTIFACT_PERSISTED",
}
ATTEMPT_EVENTS = {"INTENT_RECORDED", "CALL_RETURNED", "CALL_FAILED", "RESPONSE_REJECTED",
                  "ARTIFACT_PERSISTED"}
RUN_TERMINAL_EVENTS = {"RUN_ABORTED", "RUN_SEALED"}
AFTER_TERMINAL_EVENTS = {"SESSION_CLOSED", "SESSION_RELEASED"}
JOURNAL_EVENTS = {"RUN_OPENED", "INPUT_LOCK_BOUND", "SESSION_OPENED", "SESSION_CLOSED",
                  "SESSION_RELEASED", "INTENT_RECORDED", "CALL_RETURNED", "CALL_FAILED",
                  "RESPONSE_REJECTED", "ARTIFACT_PERSISTED", "RUN_SEALED", "RUN_ABORTED",
                  "RECOVERED"}
DATASET_ROW_KEYS = ("record", "cell", "replicate", "position", "artifact_content")
EXTERNAL_SUBJECT_SCHEME = "boomvalley-lab-contract-identity"
RUN_ID_SCHEMES = {"uuid4", "legacy-label"}
# Request persistence (§12) as this reader knows it: one schema per role, closed documents.
REQUEST_ROLES = ("request", "request_envelope")
REQUEST_SCHEMAS = {"request": "boomvalley-lab-request-1",
                   "request_envelope": "boomvalley-epc-request-envelope-1"}
REQUEST_MEMBERS = {"schema", "record", "payload"}
ENVELOPE_MEMBERS = {"schema", "record", "request", "availability"}
ENVELOPE_OPTIONAL = {"redacted", "external", "reason_code"}
ENVELOPE_AVAILABILITY = {"redacted", "external", "unavailable"}
ENVELOPE_REASONS = {"SECRET", "PERSONAL_DATA", "LICENSE", "SIZE", "LOST"}
# availability state -> the producer limitation that must accompany it (§12.2 table)
REQUEST_LIMITATIONS = {"redacted": "REQUEST_REDACTED", "external": "REQUEST_EXTERNAL",
                       "unavailable": "REQUEST_UNAVAILABLE"}
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")

# input.json (bvl-input-lock-2) as this reader knows it: closed member sets, pinned tags.
INPUT_LOCK_SCHEMA = "bvl-input-lock-2"
INPUT_MEMBERS = {"schema", "experiment_input_identity", "eii_preimage", "source", "normalized",
                 "declaration", "execution_profile"}
INPUT_PRE_EXECUTION_MEMBERS = {"preflight_record", "preflight_record_sha256"}
EII_PREIMAGE_MEMBERS = {"identity_schema", "contract", "execution"}
EII_PRE_EXECUTION_MEMBERS = {"contracts", "external_subject", "inputs", "manifest",
                             "manifest_version", "policy", "require_outcome", "result",
                             "result_version"}
NORMALIZED_SCHEMA = "bvl-normalized-input-2"
NORMALIZED_ENVELOPE = "bvl-experiment-2"
NORMALIZED_MEMBERS = {"schema", "envelope_schema", "declaration", "execution", "pre_execution",
                      "run", "extensions", "informational"}
EXECUTION_PROFILE_MEMBERS = {"binding", "digest", "document"}
EXECUTION_PROFILE_SCHEMA = "bvl-execution-profile-1"
DECLARATION_IDENTITY_KEYS = {"contract_identity": "contract", "design_identity": "design",
                             "schedule_identity": "schedule"}
PREFLIGHT_RECORD_SCHEMA = "bvl-preflight-record-2"
# BVL lockdoc.PREFLIGHT_LIMITATIONS (GM-07/GM-01): the frozen list every preflight record
# states, compared exactly (content and order). The GNDCRW_* codes LIM-002 takes from the
# record are trusted only once INP-003 has pinned the record to this list.
PREFLIGHT_LIMITATIONS = ("GNDCRW_DECLARATION_NOT_DERIVED_FROM_EXPERIMENT",
                         "GNDCRW_EXTERNAL_SUBJECT_PROVIDER_ATTESTED",
                         "GNDCRW_TOOL_CODE_SELF_REPORTED")

# GNDCRW versions this reader was written against (EPC §21: nothing is guessed forward).
# A package whose GNDCRW result / manifest / contracts / policy fall outside this table is
# ERROR UNSUPPORTED_GNDCRW_VERSION even when every copy agrees.
GNDCRW_SUPPORTED = {
    "result_version": {"gndcrw-result/v0.2"},
    "manifest_version": {"gndcrw-manifest/v0.2"},
    "policy": {"GNDCRW-STRICT-0.1"},
    "code_digest_method": {"gndcrw-code-digest/v0.2"},
    "contracts": [{"declaration": "gndcrw-declaration/v0.1",
                   "manifest": "gndcrw-manifest/v0.2",
                   "pair": "gndcrw-pair/v0.1",
                   "surface": "gndcrw-surface/v0.1",
                   "target_catalog": "gndcrw-target-catalog/v0.1",
                   "verification": "gndcrw-verification/v0.1"}],
}
GNDCRW_TOOL_NAME = "gndcrw"
GNDCRW_TOOL_MEMBERS = {"name", "version", "code_digest", "code_digest_method"}
# GNDCRW result semantics (RESULT_CONTRACT §8-§11, §17, carried by v0.2 §1): closed finding
# status / policy_class vocabularies and their allowed combinations (§9 table), the summary
# recomputed from the findings, the STRICT outcome recomputed from the BLOCKING findings, and
# one finding per declared rule. Own code; same meaning as BVL #57 RESULT_SEMANTICS_INVALID.
GNDCRW_STATUSES = ("PASS", "FAIL", "WARNING", "UNVERIFIABLE", "NOT_APPLICABLE")
GNDCRW_POLICY_STATUSES = {
    "BLOCKING": ("PASS", "FAIL", "UNVERIFIABLE", "NOT_APPLICABLE"),
    "REQUIRED_NONBLOCKING": ("PASS", "FAIL", "WARNING", "UNVERIFIABLE", "NOT_APPLICABLE"),
    "ADVISORY": ("PASS", "WARNING", "NOT_APPLICABLE"),
}
GNDCRW_OUTCOMES = {"RUN", "BLOCK", "UNVERIFIABLE"}
GNDCRW_STRICT_POLICY = "GNDCRW-STRICT-0.1"
# declaration sections whose every rule yields a finding carrying its rule_id (§11)
GNDCRW_DECLARED_RULES = ("expected_changes", "invariants", "declared_consequences")
# MINOR-10: the pinned GNDCRW cace4dea finding semantics (RESULT_CONTRACT §6-§7, §11, §20-§21,
# VERIFICATION_SEMANTICS §11.2), transcribed into this reader's own tables. Every public
# reason_code fixes one (status, policy_class) under GNDCRW-STRICT-0.1; REQUIRED_NONBLOCKING
# is reserved in v0.1, so no v0.1 finding carries it.
GNDCRW_REASONS = {
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
# §7 / VS §11.2: the reason codes each emitted finding_kind may carry. The reserved kind
# ENTITY_COMPARABILITY and reason REFERENCE_COMPARISON_ONLY are never emitted by v0.1.
_GNDCRW_UNOBSERVED = ("TARGET_UNOBSERVABLE", "TARGET_MISSING", "TARGET_UNSUPPORTED",
                      "TARGET_AMBIGUOUS", "TARGET_ASSERTED_ONLY",
                      "ENTITY_COMPARABILITY_UNKNOWN", "ENTITY_COMPARABILITY_NOT_ESTABLISHED",
                      "ENTITY_MAPPING_MISSING")
GNDCRW_KIND_REASONS = {
    "EXPECTED_CHANGE": ("EXPECTED_CHANGE_ASSEMBLED", "EXPECTED_CHANGE_MISSING",
                        *_GNDCRW_UNOBSERVED),
    "INVARIANT": ("INVARIANT_HELD", "INVARIANT_VIOLATED", *_GNDCRW_UNOBSERVED),
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
# kinds that evaluate one declared rule (finding_id = rule_id) -> the declaration section
# (§7); a COMPOSITION finding's section follows its reason (change vs invariant)
GNDCRW_RULE_KINDS = {"EXPECTED_CHANGE": "expected_changes", "INVARIANT": "invariants",
                     "DECLARED_CONSEQUENCE": "declared_consequences", "COMPOSITION": None}
# the closed finding member set (§6; the pinned result schema is additionalProperties false)
GNDCRW_FINDING_MEMBERS = {
    "finding_version", "finding_id", "rule_id", "finding_kind", "status", "policy_class",
    "reason_code", "target", "observation_level", "scope", "expected", "observed",
    "evidence_pointers", "premise_refs", "limitation_refs"}
GNDCRW_FINDING_VERSION = "gndcrw-finding/v0.1"
GNDCRW_TARGET_KINDS = ("TARGET", "COMPOSITION")
# EPC §17 / DEC-05: the producer limitation that declares a journal torn tail
JOURNAL_TORN_TAIL = "JOURNAL_TORN_TAIL"


# reports/eligibility.json (boomvalley-epc-eligibility-1) as this reader knows it (EPC §18/§19).
ELIGIBILITY_SCHEMA = "boomvalley-epc-eligibility-1"
# #176 (BVVH #174 MAJOR-1): the provider contract of each BVL adapter kind - which
# {model_identity, adapter_provenance} it may state, intended or actual. Read from the
# locked profile and the journal; this reader shares no code with the producer.
ADAPTER_LOCAL_PROVENANCE = "boomvalley-lab-local-1"
ADAPTER_OLLAMA_PROVENANCE = re.compile(r"boomvalley-lab-ollama-1;ollama=[^\s;]+")


def _adapter_identity_problems(kind, model, identity, where):
    name, provenance = identity.get("model_identity"), identity.get("adapter_provenance")
    if not isinstance(name, str) or not isinstance(provenance, str):
        return [f"ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH: {where}: identity is not strings"]
    found = []
    if kind == "local":
        if provenance != ADAPTER_LOCAL_PROVENANCE:
            found.append(f"ADAPTER_PROVENANCE_NAMESPACE_MISMATCH: {where}: adapter kind local "
                         f"states provenance {provenance!r}")
        if not name:
            found.append(f"ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH: {where}: adapter kind local "
                         "states an empty model identity")
        elif "@sha256:" in name.lower():
            found.append(f"ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH: {where}: adapter kind local "
                         f"states a pinned model {name!r} (no model is called)")
    elif kind == "ollama":
        if not ADAPTER_OLLAMA_PROVENANCE.fullmatch(provenance):
            found.append(f"ADAPTER_PROVENANCE_NAMESPACE_MISMATCH: {where}: adapter kind ollama "
                         f"states provenance {provenance!r}")
        if not (isinstance(model, str) and re.fullmatch(
                re.escape(model) + r"@sha256:[0-9a-f]{64}", name)):
            found.append(f"ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH: {where}: adapter kind ollama "
                         f"states model {name!r}")
    else:
        found.append(f"ADAPTER_PROVENANCE_NAMESPACE_MISMATCH: {where}: adapter kind {kind!r} "
                     "has no provenance namespace in this reader")
    return found


def _adapter_parity(adapter, intended, journal):
    """INP-006 (#176/#179): the locked adapter kind fixes the namespace of the intended identity
    and of every CALL_RETURNED actual_execution, and each actual is the intended one."""
    kind = adapter.get("kind")
    config = adapter.get("ollama") if isinstance(adapter.get("ollama"), dict) else {}
    model = config.get("model") if kind == "ollama" else None
    problems = _adapter_identity_problems(kind, model, intended, "locked profile")
    for index, event in enumerate(journal):
        if not isinstance(event, dict) or event.get("event") != "CALL_RETURNED":
            continue
        actual = event.get("actual_execution")
        actual = actual if isinstance(actual, dict) else {}
        problems += _adapter_identity_problems(kind, model, actual, f"journal[{index}]")
        if {k: actual.get(k) for k in intended} != intended:
            problems.append(f"ACTUAL_EXECUTION_NOT_INTENDED: journal[{index}] answered "
                            f"{ {k: actual.get(k) for k in intended} }, the locked profile "
                            f"intends {intended}")
    return problems


ELIGIBILITY_PRODUCER = "boomvalley-lab"
ELIGIBILITY_MEMBERS = {"schema", "run", "producer", "verdict", "findings"}
ELIGIBILITY_FINDING_MEMBERS = {"step_id", "rule_id", "verdict", "code"}
ELIGIBILITY_VERDICTS = {"ELIGIBLE", "NOT_ELIGIBLE"}
FINDING_CODES = {"VERIFIED": "OK", "NO_CLAIM": "NO_CLAIM", "VIOLATED": "VIOLATED"}
# gate step -> portable rule id (§19); any other step is PRODUCT-INTERNAL
ELIGIBILITY_STEP_RULES = {
    "contract_validity": "ID-003", "lock_match": "JRN-002", "topology": "SCH-001",
    "schedule_order": "SCH-002", "attempt_serialization": "JRN-003",
    "custody_integrity": "CUS-003", "session_provenance": "SES-001",
    "execution_binding": "CUS-004", "declared_vs_actual": "EXP-001",
    "parent_reconciliation": "LIN-001", "dataset_identity": "DS-001", "input_lock": "INP-001",
}
ELIGIBILITY_CELL_STEPS = {"declared_vs_actual", "artifact_provenance",
                          "declared_vs_actual_derivation"}
# run-level steps that may be absent (only emitted when something is recorded for them)
ELIGIBILITY_OPTIONAL_STEPS = {"parent_reconciliation"}
# steps whose portable rule FULLMT itself recomputes (ELG-003 / ELG-004)
ELIGIBILITY_RECOMPUTED_STEPS = {"contract_validity", "lock_match", "topology", "schedule_order",
                                "attempt_serialization", "custody_integrity",
                                "dataset_identity", "input_lock"}


# ================================================================ package access
def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    # Windows junctions / other reparse points
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def member_path_problem(path) -> str | None:
    """Why a manifest path is not an acceptable member path (None if it is)."""
    if not isinstance(path, str) or not path:
        return "path is not a non-empty string"
    if "\\" in path or ":" in path or path.startswith("/"):
        return "path is not a relative POSIX path"
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            return f"segment {segment!r} is not allowed"
        if not SEGMENT.match(segment):
            return f"segment {segment!r} does not match [A-Za-z0-9][A-Za-z0-9._-]*"
        if segment.split(".")[0].upper() in WINDOWS_RESERVED:
            return f"segment {segment!r} is a reserved device name"
        if segment.endswith("."):
            return f"segment {segment!r} ends with a dot"
    return None


class Package:
    """A package root. Reads bytes only through contained, link-free paths."""

    def __init__(self, directory: Path):
        self.directory = directory
        if not directory.is_dir():
            raise ReaderError(ErrorCode.PACKAGE_NOT_A_DIRECTORY, str(directory))
        if _is_link(directory):
            raise ReaderError(ErrorCode.PACKAGE_ROOT_IS_A_LINK, str(directory))
        self.root = directory.resolve()

    def read(self, rel: str) -> bytes:
        """Raw bytes of a member path; raises LookupError if absent/uncontained."""
        problem = member_path_problem(rel)
        if problem:
            raise LookupError(problem)
        current = self.directory
        for segment in rel.split("/"):
            current = current / segment
            if _is_link(current):
                raise LookupError(f"{rel}: {current.name} is a link or reparse point")
        if not current.is_file():
            raise LookupError(f"{rel}: missing or not a regular file")
        resolved = current.resolve()
        if not resolved.is_relative_to(self.root):
            raise LookupError(f"{rel}: resolves outside the package root")
        return resolved.read_bytes()

    def files(self) -> tuple[set[str], list[str]]:
        """All regular files under the root (POSIX relative) + anything odd found."""
        found, odd = set(), []
        for current, dirs, names in os.walk(self.directory, followlinks=False):
            base = Path(current)
            for name in list(dirs):
                if _is_link(base / name):
                    odd.append((base / name).relative_to(self.directory).as_posix())
                    dirs.remove(name)
            for name in names:
                full = base / name
                rel = full.relative_to(self.directory).as_posix()
                if _is_link(full) or not full.is_file():
                    odd.append(rel)
                else:
                    found.add(rel)
        return found, odd


# ================================================================== the verifier
class Verification:
    def __init__(self):
        self.rules: list[dict] = []
        self.observed: dict = {}
        self.consumer_limitations: list[dict] = []

    def rule(self, rule_id: str, fn):
        """Run one registered rule (fullmt_rules.RULES). fn(problems) appends problems;
        may return a NOT_EVALUATED reason."""
        layer, title = RULES[rule_id]
        problems: list[str] = []
        status, note = PASS, None
        try:
            reason = fn(problems)
            if isinstance(reason, str):
                status, note = NOT_EVALUATED, reason
        except (KeyError, TypeError, ValueError, AttributeError, IndexError,
                LookupError) as error:
            problems.append(f"could not evaluate: {type(error).__name__}: {error}")
        if problems:
            status = FAIL
        entry = {"rule_id": rule_id, "layer": layer, "title": title, "status": status}
        if problems:
            entry["problems"] = problems
        if note:
            entry["note"] = note
        self.rules.append(entry)
        return status

    def limit(self, code: str, detail: str):
        self.consumer_limitations.append({"code": code, "detail": detail})


def _dispatch(manifest) -> str:
    if not isinstance(manifest, dict):
        raise ReaderError(ErrorCode.NOT_AN_EPC_PACKAGE, "EVIDENCE.json is not a JSON object")
    schema = manifest.get("manifest_schema")
    if schema not in HANDLERS:
        raise ReaderError(ErrorCode.UNSUPPORTED_MANIFEST_SCHEMA,
                          f"{schema!r}; this reader handles {sorted(HANDLERS)}")
    return schema


def limitation_codes(limitations, structured: bool) -> list[str]:
    """The codes stated - what every rule keys on. -3 entries are {code, free_text};
    -1 entries are the code strings. Lenient on shape (LIM-001 refuses a bad list) and
    blind to free_text."""
    if not isinstance(limitations, list):
        return []
    if structured:
        return [item["code"] for item in limitations
                if isinstance(item, dict) and isinstance(item.get("code"), str)]
    return [item for item in limitations if isinstance(item, str)]


def free_text_problem(text) -> str | None:
    """free_text is a bounded human note: a non-blank string of at most
    FREE_TEXT_MAX_CODE_POINTS code points without control characters. Its content is
    never compared or interpreted."""
    if not isinstance(text, str):
        return f"free_text is a {type(text).__name__}, not a string"
    if not text.strip():
        return "free_text is empty"
    if len(text) > FREE_TEXT_MAX_CODE_POINTS:
        return f"free_text has {len(text)} code points (limit {FREE_TEXT_MAX_CODE_POINTS})"
    if any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in text):
        return "free_text contains a control character"
    return None


def limitation_problems(limitations) -> list[str]:
    """LIM-001 (-3): a list of exactly {code, free_text}; code in the frozen vocabulary
    (unknown / missing refused, never skipped); free_text bounded; one entry per code
    (a duplicate is refused whatever its free_text); sorted by code."""
    if not isinstance(limitations, list):
        return [f"limitations is a {type(limitations).__name__}, not a list"]
    found, stated = [], []
    for index, item in enumerate(limitations):
        where = f"limitations[{index}]"
        if not isinstance(item, dict):
            found.append(f"{where} is not a {{code, free_text}} object")
            continue
        extra = sorted(set(item) - LIMITATION_MEMBERS)
        if extra:
            found.append(f"{where} has unknown members {extra}")
        if "free_text" not in item:
            found.append(f"{where} has no free_text")
        else:
            problem = free_text_problem(item["free_text"])
            if problem:
                found.append(f"{where}: {problem}")
        if "code" not in item:
            found.append(f"{where} has no code")
            continue
        code = item["code"]
        if not isinstance(code, str):
            found.append(f"{where} code is a {type(code).__name__}")
            continue
        if code not in LIMITATION_CODES:
            found.append(f"{where} {code!r} is not in the frozen limitation vocabulary")
        stated.append(code)
    for code in sorted({c for c in stated if stated.count(c) > 1}):
        found.append(f"{code} is stated {stated.count(code)} times")
    if stated != sorted(stated):
        found.append("limitations are not in code order")
    return found


def problem(code: str, detail: str) -> str:
    """A problem line of the -3 rules: '<CODE>: detail', CODE from PROBLEM_CODES."""
    if code not in PROBLEM_CODES:
        raise ValueError(f"unregistered problem code {code!r}")
    return f"{code}: {detail}"


def limitation_expected(stated: list[str], dataset_admitted: bool, locked: bool,
                        preflight) -> list[str]:
    """LIM-002 (-3): the limitations the evidence establishes are stated, and no GNDCRW_*
    code the preflight record does not establish. Keys on codes only (never free_text).
    preflight is the Input Lock preflight record's limitation list (None when not locked)."""
    have = set(stated)
    found = [problem("LIMITATION_NOT_STATED", code)
             for code in STANDING_LIMITATIONS if code not in have]
    if dataset_admitted == (DATASET_NOT_ADMITTED in have):
        found.append(problem("LIMITATION_NOT_ESTABLISHED" if dataset_admitted
                             else "LIMITATION_NOT_STATED",
                             f"{DATASET_NOT_ADMITTED} does not match the dataset member "
                             f"({'present' if dataset_admitted else 'absent'})"))
    if preflight is not None and (not isinstance(preflight, list)
                                  or not all(isinstance(c, str) for c in preflight)):
        return [*found, problem("LIMITATION_SET_UNREADABLE",
                                "the preflight record limitations are not a list of codes")]
    record = set(preflight or ())
    gndcrw = {c for c in have if c.startswith(GNDCRW_LIMITATION_PREFIX)}
    found += [problem("LIMITATION_NOT_STATED", f"{c} (preflight record)")
              for c in sorted(record - gndcrw)]
    found += [problem("LIMITATION_NOT_ESTABLISHED", f"{c} (not in the preflight record)")
              for c in sorted(gndcrw - record)]
    if not locked and MODEL_VERSION_NOT_PINNED not in have:
        found.append(problem("LIMITATION_NOT_STATED",
                             f"{MODEL_VERSION_NOT_PINNED} (run is not INPUT_LOCKED)"))
    return found


def _is_digest(value) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71 \
        and set(value[7:]) <= set("0123456789abcdef")


def request_content_problems(content, intents: list[dict], custody: dict, held: dict,
                             listed: set[str], locked: bool, stated: list[str]) -> list[str]:
    """REQ-004 (-3): request_content is AVAILABLE / WITHHELD / UNAVAILABLE, never mixed.
    AVAILABLE - one entry per intent, in position order, naming the request member whose
    bytes have the entry's digest (= the intent's request) and size; WITHHELD - the same
    entries without members, no request member at all; UNAVAILABLE - no request member and
    never for an INPUT_LOCKED run. The status's limitation is stated iff it holds.
    intents are the INTENT_RECORDED events; custody maps record -> custody entry."""
    if not isinstance(content, dict):
        return [problem("REQUEST_CONTENT_SHAPE_INVALID", "request_content is not an object")]
    status = content.get("request_content_status")
    if status not in REQUEST_CONTENT_SHAPES:
        return [problem("REQUEST_CONTENT_STATUS_UNKNOWN", f"{status!r}")]
    if set(content) != REQUEST_CONTENT_SHAPES[status]:
        return [problem("REQUEST_CONTENT_SHAPE_INVALID",
                        f"{status} request_content members {sorted(content)} != "
                        f"{sorted(REQUEST_CONTENT_SHAPES[status])}")]
    found = []
    if status != REQUEST_AVAILABLE and \
            REQUEST_CONTENT_REASONS.get(content.get("reason_code")) != status:
        found.append(problem("REQUEST_CONTENT_REASON_MISMATCH",
                             f"{status} with reason_code {content.get('reason_code')!r}"))
    for other, code in REQUEST_CONTENT_LIMITATIONS.items():
        if (code in stated) != (status == other):
            found.append(problem("REQUEST_CONTENT_LIMITATION_MISMATCH",
                                 f"{code} {'stated' if code in stated else 'not stated'} "
                                 f"for {status}"))
    if status == REQUEST_UNAVAILABLE:
        if listed:
            found.append(problem("REQUEST_CONTENT_MEMBER_SET_MISMATCH",
                                 f"UNAVAILABLE with request members {sorted(listed)}"))
        if locked:
            found.append(problem("REQUEST_CONTENT_UNAVAILABLE_ON_INPUT_LOCKED",
                                 "an INPUT_LOCKED run is AVAILABLE or WITHHELD"))
        return found
    requests = content["requests"]
    if not isinstance(requests, list):
        return [*found, problem("REQUEST_CONTENT_SHAPE_INVALID",
                                f"{status} requests is not a list")]
    by_position = {e.get("position"): e for e in intents}
    seen = set()
    for index, item in enumerate(requests):
        where = f"requests[{index}]"
        if not isinstance(item, dict) or set(item) != REQUEST_CONTENT_ENTRY_SHAPES[status]:
            found.append(problem("REQUEST_CONTENT_ENTRY_INVALID", f"{where} is not a {status} "
                                 f"{sorted(REQUEST_CONTENT_ENTRY_SHAPES[status])} entry"))
            continue
        position = item["position"]
        intent = by_position.get(position) \
            if isinstance(position, int) and not isinstance(position, bool) else None
        if intent is None or item["record"] != intent.get("record"):
            found.append(problem("REQUEST_CONTENT_ENTRY_INVALID",
                                 f"{where} names no recorded intent"))
            continue
        seen.add(position)
        entry = custody.get(intent.get("record")) or {}
        if not _is_digest(item["digest"]) or item["digest"] != intent.get("request") \
                or item["digest"] != entry.get("request"):
            found.append(problem("REQUEST_CONTENT_DIGEST_MISMATCH",
                                 f"{where}: digest is not the intent's and custody entry's "
                                 "request"))
        size = item["size"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            found.append(problem("REQUEST_CONTENT_ENTRY_INVALID",
                                 f"{where}: size is not a positive byte count"))
        if status == REQUEST_WITHHELD:
            continue
        if item["member"] != REQUEST_CONTENT_MEMBER.format(position=position) \
                or item["member"] not in listed:
            found.append(problem("REQUEST_CONTENT_MEMBER_SET_MISMATCH",
                                 f"{where}: member {item['member']!r} is not the listed "
                                 f"request member of position {position}"))
            continue
        data = held.get(item["member"])
        if data is None or sha(data) != item["digest"] or len(data) != size:
            found.append(problem("REQUEST_CONTENT_BYTES_MISMATCH",
                                 f"{item['member']}: not the listed request bytes"))
    positions = [i.get("position") for i in requests if isinstance(i, dict)]
    if positions != sorted(p for p in by_position if isinstance(p, int)) \
            or seen != set(by_position):
        found.append(problem("REQUEST_CONTENT_NOT_ONE_PER_INTENT",
                             "the request list is not one entry per intent, in position order"))
    expected = {REQUEST_CONTENT_MEMBER.format(position=p) for p in by_position
                if isinstance(p, int)} if status == REQUEST_AVAILABLE else set()
    if listed != expected:
        found.append(problem("REQUEST_CONTENT_MEMBER_SET_MISMATCH",
                             f"request members {sorted(listed ^ expected)} "
                             + ("missing or extra" if status == REQUEST_AVAILABLE
                                else "published although WITHHELD")))
    return found


def verify_epc_manifest_1(pkg: Package, manifest_bytes: bytes, manifest: dict,
                          v: Verification) -> None:
    _verify_epc(pkg, manifest_bytes, manifest, v, structured=False)


def verify_epc_manifest_3(pkg: Package, manifest_bytes: bytes, manifest: dict,
                          v: Verification) -> None:
    """manifest-3 / producer-2 (BVL #114): the manifest/1 rules plus the -3 deltas -
    execution_gate / request_content sections, {code, free_text} limitations (LIM-001)
    and the producer-2 provenance member (PRD-001)."""
    _verify_epc(pkg, manifest_bytes, manifest, v, structured=True)


def _verify_epc(pkg: Package, manifest_bytes: bytes, manifest: dict, v: Verification,
                structured: bool) -> None:
    formats = manifest.get("formats")
    if not isinstance(formats, dict):
        raise ReaderError(ErrorCode.UNSUPPORTED_FORMAT, "manifest has no formats table")
    for key, expected in EPC_1_FORMATS.items():
        if formats.get(key) != expected:
            raise ReaderError(ErrorCode.UNSUPPORTED_FORMAT, f"{key}={formats.get(key)!r}")
    versions = formats.get("identity_versions")
    if not isinstance(versions, dict):
        raise ReaderError(ErrorCode.UNSUPPORTED_FORMAT, "no identity_versions")
    for kind, version in versions.items():
        if kind in EPC_1_IDENTITY_VERSIONS and EPC_1_IDENTITY_VERSIONS[kind] != version:
            raise ReaderError(ErrorCode.UNSUPPORTED_IDENTITY_VERSION, f"{kind}={version!r}")
        if kind not in EPC_1_IDENTITY_VERSIONS:
            v.limit("IDENTITY_KIND_NOT_RECOMPUTED",
                    f"{kind}={version}: declared by the producer, unknown to this reader")
    for kind in ("evidence_root", "package", "run", "custody_seal", "dataset",
                 "experiment_input", "contract", "design", "schedule"):
        if versions.get(kind) != EPC_1_IDENTITY_VERSIONS[kind]:
            raise ReaderError(ErrorCode.UNSUPPORTED_IDENTITY_VERSION,
                              f"{kind}={versions.get(kind)!r} (need "
                              f"{EPC_1_IDENTITY_VERSIONS[kind]})")

    members = manifest.get("members") if isinstance(manifest.get("members"), list) else []
    by_path: dict[str, dict] = {}
    roles: dict[str, list[str]] = {}
    held: dict[str, bytes] = {}
    parsed: dict[str, object] = {}
    declared_limitations = limitation_codes(manifest.get("limitations") or [], structured)
    required = MANIFEST_REQUIRED | (MANIFEST_3_SECTIONS if structured else set())
    locked = (manifest.get("input_lock") or {}).get("classification") == "INPUT_LOCKED"

    # ---------------------------------------------------------------- L2 manifest
    def mem_001(p):
        if canonical(manifest) != manifest_bytes:
            p.append("EVIDENCE.json is not canonical-json-1 at rest")
        missing = sorted(required - set(manifest))
        unknown = sorted(set(manifest) - required - MANIFEST_OPTIONAL)
        if missing:
            p.append(f"EVIDENCE.json lacks top-level members {missing}")
        if unknown:
            p.append(f"EVIDENCE.json has unknown top-level members {unknown} (closed, §16.4)")
        if not isinstance(manifest.get("members"), list) or not members:
            p.append("members is not a non-empty list")
        folded: dict[str, str] = {}
        for member in members:
            if not isinstance(member, dict):
                p.append(f"member is not an object: {member!r}")
                continue
            path = member.get("path")
            problem = member_path_problem(path)
            if problem:
                p.append(f"{path!r}: {problem}")
                continue
            if path in by_path:
                p.append(f"{path} listed twice")
                continue
            if path.casefold() in folded:
                p.append(f"{path} and {folded[path.casefold()]} are two spellings of one file")
            folded[path.casefold()] = path
            if path == MANIFEST:
                p.append("EVIDENCE.json lists itself")
            role = member.get("role")
            if role not in EPC_1_ROLES:
                p.append(f"{path}: role {role!r} is not in the manifest/1 role vocabulary")
            digest, size = member.get("digest"), member.get("bytes")
            if not (isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
                p.append(f"{path}: digest is not sha256:<64 lowercase hex>")
            if not (isinstance(size, int) and not isinstance(size, bool) and size >= 0):
                p.append(f"{path}: bytes is not a non-negative integer")
            if not isinstance(member.get("media_type"), str):
                p.append(f"{path}: no media_type")
            by_path[path] = member
            roles.setdefault(role, []).append(path)
        # package_identity/1 hashes members[] as listed, so one member set must have one
        # listing: path order (segment-wise, case-folded, then code points - the order the
        # reference producer writes). Any other order is a second identity for the same set.
        listed = [m["path"] for m in members if isinstance(m, dict)
                  and isinstance(m.get("path"), str)]
        ordered = sorted(listed, key=member_order)
        if listed != ordered:
            first = next(i for i, (a, b) in enumerate(zip(listed, ordered)) if a != b)
            p.append(f"members[] is not in path order (index {first}: {listed[first]!r}, "
                     f"expected {ordered[first]!r}); a reordered listing would be another "
                     f"package_identity for the same member set")
    v.rule("MEM-001", mem_001)

    if structured:
        def lim_001(p):
            p.extend(limitation_problems(manifest.get("limitations")))
            for key in sorted(MANIFEST_3_SECTIONS):
                if key in manifest and not isinstance(manifest[key], dict):
                    p.append(f"{key} is not an object")
            v.observed["limitation_codes"] = sorted(set(declared_limitations))
        v.rule("LIM-001", lim_001)
        v.limit("MANIFEST_3_SECTIONS_NOT_REDERIVED",
                "execution_gate is a producer decision carried in the manifest; this reader "
                "checks its presence, it does not re-derive the gate (request_content is "
                "checked by REQ-004)")

    # ------------------------------------------------------------------ L1 bytes
    def mem_002(p):
        for path, member in by_path.items():
            try:
                data = pkg.read(path)
            except (LookupError, OSError) as error:
                p.append(f"{path}: {error}")
                continue
            held[path] = data
            if member.get("digest") != sha(data):
                p.append(f"{path}: digest {sha(data)} != listed {member.get('digest')}")
            if member.get("bytes") != len(data):
                p.append(f"{path}: {len(data)} bytes != listed {member.get('bytes')}")
    v.rule("MEM-002", mem_002)

    def mem_003(p):
        present, odd = pkg.files()
        for rel in sorted(odd):
            p.append(f"{rel}: link, reparse point or non-regular file under the root")
        for rel in sorted(present - set(by_path) - {MANIFEST}):
            p.append(f"{rel} is under the package root but is not a member")
    v.rule("MEM-003", mem_003)

    def mem_004(p):
        for role in REQUIRED_ONCE:
            if len(roles.get(role, [])) != 1:
                p.append(f"role {role}: {len(roles.get(role, []))} members, need 1")
        for role in OPTIONAL_ONCE:
            if len(roles.get(role, [])) > 1:
                p.append(f"role {role}: {len(roles.get(role, []))} members, at most 1")
        for role in INPUT_LOCK_ROLES:
            need = 1 if locked else 0
            if len(roles.get(role, [])) != need:
                p.append(f"role {role}: {len(roles.get(role, []))} members, need {need} "
                         f"(input_lock {'INPUT_LOCKED' if locked else 'absent'})")
        if not roles.get("claims") and "CLAIMS_NOT_EMITTED" not in declared_limitations:
            p.append("no claims member and no CLAIMS_NOT_EMITTED limitation")
    v.rule("MEM-004", mem_004)

    def one(role) -> bytes:
        paths = roles.get(role, [])
        if len(paths) != 1:
            raise LookupError(f"role {role}: {len(paths)} members")
        if paths[0] not in held:
            raise LookupError(f"role {role}: {paths[0]} was not readable")
        return held[paths[0]]

    def doc(role):
        path = roles[role][0] if len(roles.get(role, [])) == 1 else None
        if path is None:
            raise LookupError(f"role {role}: not exactly one member")
        if path not in parsed:
            parsed[path] = strict_json(one(role), allow_null=role in FOREIGN_JSON_ROLES)
        return parsed[path]

    # --------------------------------------------------------------- L2 documents
    def str_001(p):
        for path, member in sorted(by_path.items()):
            if path not in held:
                continue
            media = member.get("media_type")
            try:
                foreign = member.get("role") in FOREIGN_JSON_ROLES
                if media in JSON_MEDIA:
                    parsed[path] = strict_json(held[path], allow_null=foreign)
                    schema = member.get("schema")
                    tag = _schema_tag(parsed[path])
                    if schema and tag is not None and tag != schema:
                        p.append(f"{path}: document says {tag!r}, manifest says {schema!r}")
                elif media in JSONL_MEDIA:
                    strict_jsonl(held[path])
            except Malformed as error:
                p.append(f"{path}: {error}")
    v.rule("STR-001", str_001)

    if structured:
        def prd_001(p):
            path = roles["producer_provenance"][0] \
                if len(roles.get("producer_provenance", [])) == 1 else None
            if path is None:
                return "no single producer_provenance member (MEM-004)"
            document = doc("producer_provenance")
            tag = document.get("schema") if isinstance(document, dict) else None
            if by_path[path].get("schema") != PRODUCER_SCHEMA_3 or tag != PRODUCER_SCHEMA_3:
                p.append(f"{path}: manifest-3 needs {PRODUCER_SCHEMA_3!r}; manifest says "
                         f"{by_path[path].get('schema')!r}, document says {tag!r}")
            v.observed["producer_schema"] = tag
        v.rule("PRD-001", prd_001)

    def str_002(p):
        for path in sorted(held):
            if by_path[path].get("role") in CANONICAL_JSONL:
                _jsonl_canonical(path, held[path], p)
                continue
            if by_path[path].get("role") not in CANONICAL_AT_REST:
                continue
            try:
                if canonical(strict_json(held[path])) != held[path]:
                    p.append(f"{path} is not canonical-json-1 at rest")
            except Malformed as error:
                p.append(f"{path}: {error}")
    v.rule("STR-002", str_002)

    journal: list = []
    entries: list = []

    def load_logs():
        nonlocal journal, entries
        journal, _ = strict_jsonl(one("journal"))
        entries, _ = strict_jsonl(one("custody_entries"))

    # ---------------------------------------------------------------- L3 identity
    observed = v.observed

    def id_001(p):
        recomputed = sha(canonical({"epc_identity": "evidence-root/1",
                                    "members": sorted(members, key=lambda m: m["path"])}))
        observed["evidence_root"] = {"declared": manifest.get("evidence_root"),
                                     "recomputed": recomputed}
        if manifest.get("evidence_root") != recomputed:
            p.append(f"evidence_root {manifest.get('evidence_root')} != recomputed {recomputed}")
    v.rule("ID-001", id_001)

    def id_002(p):
        body = {k: val for k, val in manifest.items()
                if k not in ("package_identity", "informational")}
        recomputed = sha(canonical({"epc_identity": "package/1", **body}))
        observed["package_identity"] = {"declared": manifest.get("package_identity"),
                                        "recomputed": recomputed}
        if manifest.get("package_identity") != recomputed:
            p.append(f"package_identity {manifest.get('package_identity')} != recomputed "
                     f"{recomputed}")
    v.rule("ID-002", id_002)

    def id_003(p):
        lock, run = doc("lock"), doc("run")
        identities = manifest["identities"]
        for role, kind in (("declaration", "contract"), ("design", "design"),
                           ("schedule", "schedule")):
            raw = sha(one(role))
            ref = identities[kind]
            observed[kind] = raw
            if not (raw == lock["identities"][kind] == run["lock"][kind] == ref["digest"]):
                p.append(f"{kind}: SHA-256(raw) / lock / run.json / manifest disagree")
            if ref.get("kind") != kind or ref.get("version") != EPC_1_IDENTITY_VERSIONS[kind]:
                p.append(f"{kind}: typed reference kind/version mismatch")
            if ref.get("member") is not None and ref["member"] not in roles.get(role, []):
                p.append(f"{kind}: typed reference locator is not the {role} member")
        if canonical(lock["declaration"]) != one("declaration"):
            p.append("design/declaration.json is not canonical(lock.declaration)")
    v.rule("ID-003", id_003)

    def id_004(p):
        lock, run = doc("lock"), doc("run")
        section = manifest["run"]
        scheme = section.get("run_id_scheme")
        recomputed = sha(canonical({"epc_identity": "run/1", "run_id": run["run"],
                                    "lock": {k: lock["identities"][k]
                                             for k in ("contract", "design", "schedule")}}))
        observed["run"] = {"run_id": section.get("run_id"), "run_id_scheme": scheme,
                           "run_identity": recomputed}
        if section.get("run_id") != run["run"]:
            p.append("manifest run_id is not run.json's run")
        if section["run_identity"].get("digest") != recomputed:
            p.append(f"RunIdentity {section['run_identity'].get('digest')} != {recomputed}")
        if scheme not in RUN_ID_SCHEMES:
            p.append(f"run_id_scheme {scheme!r} is not in the closed enum")
        if scheme == "uuid4" and not UUID4.match(str(section.get("run_id"))):
            p.append("run_id_scheme uuid4 but run_id is not a lowercase UUIDv4")
        if scheme == "legacy-label":
            v.limit("RUN_UNIQUENESS_NOT_ESTABLISHED",
                    "run_id_scheme legacy-label: RunIdentity recomputes, but the run id is an "
                    "operator label, so run uniqueness is not established (§7.3, L3 PARTIAL)")
    v.rule("ID-004", id_004)

    # ---------------------------------------------------------- journal / custody
    def run_001(p):
        load_logs()
        run_id = manifest["run"]["run_id"]
        for index, event in enumerate(journal):
            if event.get("run") != run_id:
                p.append(f"journal[{index}] names run {event.get('run')!r}")
        for entry in entries:
            if entry.get("run") != run_id:
                p.append(f"custody entry {entry.get('record')} names run {entry.get('run')!r}")
        if doc("custody_head").get("run") != run_id:
            p.append("custody head names another run")
        if doc("dataset").get("run") != run_id:
            p.append("dataset names another run")
        report = doc("eligibility_report")
        run_ref = report.get("run") if isinstance(report, dict) else None
        if not isinstance(run_ref, dict) or                 run_ref.get("digest") != manifest["run"]["run_identity"].get("digest"):
            p.append("eligibility report names another RunIdentity")
    v.rule("RUN-001", run_001)

    def jrn_001(p):
        for index, event in enumerate(journal):
            if event.get("event") not in JOURNAL_EVENTS:
                p.append(f"journal[{index}]: unknown event {event.get('event')!r}")
            if not isinstance(event.get("at"), str):
                p.append(f"journal[{index}]: no 'at'")
    v.rule("JRN-001", jrn_001)

    def jrn_002(p):
        opened = [i for i, e in enumerate(journal) if e.get("event") == "RUN_OPENED"]
        if opened != [0]:
            p.append(f"RUN_OPENED at {opened}, need exactly once at index 0")
            return
        first, lock = journal[0], doc("lock")
        for kind in ("contract", "design", "schedule"):
            if first.get(f"lock_{kind}") != lock["identities"][kind]:
                p.append(f"RUN_OPENED lock_{kind} is not the lock's")
    v.rule("JRN-002", jrn_002)

    def jrn_003(p):
        # replay the acknowledged journal as a state machine: the run is OPEN until its
        # first terminal event (RUN_ABORTED / RUN_SEALED); a terminal run accepts only
        # session teardown, so an abort followed by a seal (or by more execution) is refused
        terminal = None
        attempts: dict = {}
        for index, event in enumerate(journal):
            kind = event.get("event")
            if terminal is not None and kind not in AFTER_TERMINAL_EVENTS:
                p.append(f"journal[{index}]: {kind} after {terminal[1]} at journal"
                         f"[{terminal[0]}]; a terminated run accepts no further events")
                continue
            if kind in RUN_TERMINAL_EVENTS:
                terminal = (index, kind)
                continue
            if kind not in ATTEMPT_EVENTS:
                continue
            attempt = event.get("attempt")
            if not isinstance(attempt, str):
                p.append(f"journal[{index}]: {kind} names no attempt")
                continue
            state = attempts.get(attempt)
            nxt = ATTEMPT_TRANSITIONS.get((state, kind))
            if nxt is None:
                p.append(f"journal[{index}]: attempt {attempt!r}: {kind} cannot follow "
                         f"{state or 'the start of the attempt'}")
                continue
            attempts[attempt] = nxt
        observed["journal_grammar"] = {"attempts": len(attempts),
                                       "terminal": terminal[1] if terminal else None}
    v.rule("JRN-003", jrn_003)

    def jrn_004(p):
        data = one("journal")
        _, acknowledged = strict_jsonl(data)
        expected = {"acknowledged_bytes": acknowledged,
                    "torn_tail_bytes": len(data) - acknowledged}
        if manifest.get("journal") != expected:
            p.append(f"journal extent {manifest.get('journal')} != {expected}")
        # §17 / DEC-05: a torn tail is carried iff the producer declares JOURNAL_TORN_TAIL
        torn = expected["torn_tail_bytes"]
        declared = JOURNAL_TORN_TAIL in declared_limitations
        observed["journal"] = {**expected, "torn_tail_declared": declared}
        if torn and not declared:
            p.append(f"the journal ends in a {torn}-byte torn tail and the limitation "
                     f"{JOURNAL_TORN_TAIL} is not declared")
        if declared and not torn:
            p.append(f"{JOURNAL_TORN_TAIL} is declared and the journal has no torn tail")
        if torn and declared:
            v.limit("JOURNAL_TORN_TAIL_NOT_READ",
                    f"the journal's {torn}-byte torn tail is declared by the producer; it is "
                    f"not an acknowledged event and is not read (§17)")
        kinds = [e.get("event") for e in journal]
        sealed = [i for i, k in enumerate(kinds) if k == "RUN_SEALED"]
        if len(sealed) != 1:
            p.append(f"{len(sealed)} RUN_SEALED events")
            return
        tail = kinds[sealed[0] + 1:]
        if tail not in ([], ["SESSION_CLOSED"]):
            p.append(f"events after RUN_SEALED: {tail}")
        elif tail and journal[-1].get("session") != journal[sealed[0]].get("session"):
            p.append("SESSION_CLOSED after RUN_SEALED is not the sealing session")
    v.rule("JRN-004", jrn_004)

    def sch_001(p):
        order = doc("schedule")["order"]
        observed["records"] = len(entries)
        if len(entries) != len(order):
            p.append(f"{len(entries)} custody entries for {len(order)} scheduled positions")
        positions = sorted(e.get("position") for e in entries)
        if positions != list(range(len(order))):
            p.append("custody positions are not exactly the schedule indices")
        for entry in entries:
            position = entry.get("position")
            if isinstance(position, int) and 0 <= position < len(order):
                cell, replicate = order[position]
                if (entry.get("cell"), entry.get("replicate")) != (cell, replicate):
                    p.append(f"position {position}: entry is {entry.get('cell')}#"
                             f"{entry.get('replicate')}, schedule says {cell}#{replicate}")
    v.rule("SCH-001", sch_001)

    def sch_002(p):
        positions = [e.get("position") for e in journal if e.get("event") == "INTENT_RECORDED"]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            p.append(f"INTENT_RECORDED positions out of schedule order: {positions}")
    v.rule("SCH-002", sch_002)

    def cus_001(p):
        head = doc("custody_head")
        # a sealed custody ledger has no torn-tail state (unlike the journal): every byte
        # must belong to a complete LF-terminated record
        data = one("custody_entries")
        trailing = len(data) - (data.rfind(b"\n") + 1)
        if trailing:
            p.append(f"custody entries end in {trailing} bytes that are not a complete "
                     f"record; a sealed custody ledger has no torn tail")
        for entry in entries:
            if entry.get("schema") != "boomvalley-lab-custody-entry-1":
                p.append(f"{entry.get('record')}: entry schema {entry.get('schema')!r}")
            for kind in ("design", "schedule"):
                if entry.get(kind) != manifest["identities"][kind]["digest"]:
                    p.append(f"{entry.get('record')}: {kind} is not the manifest's")
        if head.get("schema") != "boomvalley-lab-custody-head-2":
            p.append(f"head schema {head.get('schema')!r}")
        records = [e.get("record") for e in entries]
        if len(set(records)) != len(records):
            p.append("a record has more than one custody entry")
    v.rule("CUS-001", cus_001)

    def cus_002(p):
        for entry in entries:
            artifact_path = _artifact_member(entry.get("artifact"), roles)
            if artifact_path is None:
                p.append(f"{entry.get('record')}: no artifact member for "
                         f"{entry.get('artifact')!r}")
                continue
            digest = sha(held[artifact_path]) if artifact_path in held else None
            if not (digest == entry.get("artifact_content") == entry.get("response")):
                p.append(f"{entry.get('record')}: SHA-256(artifact) / artifact_content / "
                         f"response disagree")
    v.rule("CUS-002", cus_002)

    def cus_003(p):
        head = doc("custody_head")
        custody = sha(canonical(entries))
        seal = sha(canonical({k: val for k, val in head.items() if k != "seal"}))
        sessions = sha(canonical(head.get("sessions")))
        observed["custody_seal"] = {"declared": manifest["identities"]["custody_seal"]["digest"],
                                    "head_seal": head.get("seal"), "recomputed": seal}
        if head.get("custody") != custody:
            p.append(f"head custody {head.get('custody')} != recomputed {custody}")
        if head.get("seal") != seal:
            p.append(f"head seal {head.get('seal')} != recomputed {seal}")
        if head.get("sessions_digest") != sessions:
            p.append("head sessions_digest does not recompute")
        if head.get("entries") != len(entries):
            p.append(f"head entries {head.get('entries')} != {len(entries)}")
        if head.get("scheduled") != len(doc("schedule")["order"]):
            p.append("head scheduled != schedule length")
        origins = {}
        for entry in entries:
            origins[entry.get("origin")] = origins.get(entry.get("origin"), 0) + 1
        if {k: n for k, n in (head.get("origins") or {}).items() if n} != origins:
            p.append(f"head origins {head.get('origins')} != {origins}")
        for kind in ("contract", "design", "schedule"):
            if head["identities"].get(kind) != manifest["identities"][kind]["digest"]:
                p.append(f"head identities.{kind} is not the manifest's")
    v.rule("CUS-003", cus_003)

    def seal_001(p):
        head = doc("custody_head")
        ref = manifest["identities"]["custody_seal"]
        seal = sha(canonical({k: val for k, val in head.items() if k != "seal"}))
        if head.get("state") != "SEALED":
            p.append(f"custody head state {head.get('state')!r}, need SEALED")
        if ref.get("digest") != seal:
            p.append("manifest custody_seal is not the recomputed seal of the head")
        if ref.get("member") is not None and ref["member"] not in roles.get("custody_head", []):
            p.append("custody_seal locator is not the custody_head member")
        sealed = [e for e in journal if e.get("event") == "RUN_SEALED"]
        if len(sealed) != 1 or sealed[0].get("seal") != seal:
            p.append("RUN_SEALED does not carry the recomputed seal exactly once")
        elif sealed[0].get("custody") != head.get("custody") or \
                sealed[0].get("entries") != head.get("entries"):
            p.append("RUN_SEALED custody/entries disagree with the head")
        if sealed and head.get("sealed_by") != sealed[0].get("session"):
            p.append("head sealed_by is not the RUN_SEALED session")
    v.rule("SEAL-001", seal_001)

    def mem_005(p):
        wanted = {_artifact_member(e.get("artifact"), roles) for e in entries}
        listed = set(roles.get("artifact", []))
        if None in wanted:
            p.append("a custody entry names an artifact that is not a member")
        for path in sorted(listed - wanted):
            p.append(f"{path}: artifact member no custody entry names")
        for path in sorted(listed):
            head, _, name = path.partition("/")
            if head != ARTIFACT_STORE or not name or "/" in name:
                p.append(f"{path}: role artifact outside the artifact store "
                         f"{ARTIFACT_STORE}/<name>")
        intents = [e for e in journal if e.get("event") == "INTENT_RECORDED"]
        requests = roles.get("request", []) + roles.get("request_envelope", [])
        if requests and len(requests) != len(intents):
            p.append(f"{len(requests)} request members for {len(intents)} intents")
    v.rule("MEM-005", mem_005)

    def ds_001(p):
        dataset = doc("dataset")
        preimage = {"identity_schema": "boomvalley-lab-dataset-identity-2",
                    "run": dataset["run"], "design": dataset["design"],
                    "schedule": dataset["schedule"], "records": dataset["records"],
                    "rows": [{k: row[k] for k in DATASET_ROW_KEYS if k in row}
                             for row in dataset["rows"]]}
        recomputed = sha(canonical(preimage))
        observed["dataset"] = recomputed
        if recomputed != manifest["identities"]["dataset"]["digest"]:
            p.append(f"DatasetIdentity {recomputed} != manifest")
        by_position = sorted(entries, key=lambda e: e["position"])
        if [{k: e.get(k) for k in DATASET_ROW_KEYS} for e in by_position] != \
                [{k: r.get(k) for k in DATASET_ROW_KEYS} for r in dataset["rows"]]:
            p.append("dataset rows are not the custody entries in position order")
        if dataset["records"] != len(dataset["rows"]):
            p.append("dataset records count != rows")
        for kind in ("design", "schedule"):
            if dataset[kind] != manifest["identities"][kind]["digest"]:
                p.append(f"dataset {kind} is not the manifest's")
    v.rule("DS-001", ds_001)

    # ------------------------------------------------------------ requests (§12)
    # Request members are found by their declared role (request / request_envelope), never
    # by path. Each is read as its declared schema; the record it names, the request digest
    # it carries (raw bytes for a materialised request, request.digest for an envelope) and
    # its availability state are then bound to the journal intents and the custody entries,
    # which the custody seal covers independently of EVIDENCE.json.
    requests: dict = {"members": {}, "problems": []}
    # -3: the producer's request_content claim (checked by REQ-004); None under -1
    content = manifest.get("request_content") if structured else None
    content_status = content.get("request_content_status")         if isinstance(content, dict) and         content.get("request_content_status") in REQUEST_CONTENT_SHAPES else None
    observed["requests"] = {}

    def req_002(p):
        read = requests["members"]
        for role in REQUEST_ROLES:
            for path in roles.get(role, []):
                if path not in held:
                    p.append(f"{path}: role {role} member not readable")
                    continue
                member = by_path[path]
                expected = REQUEST_SCHEMAS[role]
                if member.get("media_type") not in JSON_MEDIA:
                    p.append(f"{path}: media_type {member.get('media_type')!r} is not JSON")
                try:
                    document = strict_json(held[path])
                except Malformed as error:
                    p.append(f"{path}: {error}")
                    continue
                tag = document.get("schema") if isinstance(document, dict) else None
                if member.get("schema") != expected or tag != expected:
                    p.append(f"{path}: role {role} needs schema {expected!r}; manifest says "
                             f"{member.get('schema')!r}, document says {tag!r}")
                    continue
                if canonical(document) != held[path]:
                    p.append(f"{path}: not canonical-json-1 at rest")
                if role == "request":
                    if not _closed(document, REQUEST_MEMBERS, path, p):
                        continue
                    if not isinstance(document["record"], str) or \
                            not isinstance(document["payload"], dict):
                        p.append(f"{path}: record is not a string or payload is not an object")
                        continue
                    read[path] = {"role": role, "record": document["record"],
                                  "availability": "materialized", "digest": sha(held[path])}
                    continue
                if not _envelope_structure(document, path, p):
                    continue
                read[path] = {"role": role, "record": document["record"],
                              "availability": document["availability"],
                              "digest": document["request"]["digest"]}
    v.rule("REQ-002", req_002)

    def req_001(p):
        intents: dict[str, list[dict]] = {}
        for event in journal:
            if event.get("event") == "INTENT_RECORDED":
                intents.setdefault(event.get("record"), []).append(event)
        by_record = {e.get("record"): e for e in entries}
        read = requests["members"]
        listed = [path for role in REQUEST_ROLES for path in roles.get(role, [])]
        availability: dict[str, int] = {}
        for item in read.values():
            availability[item["availability"]] = availability.get(item["availability"], 0) + 1
        observed["requests"].update({
            "intents": sum(len(x) for x in intents.values()),
            "intent_records": len(intents),
            "members": {role: len(roles.get(role, [])) for role in REQUEST_ROLES},
            "availability": availability,
        })
        if not listed:
            observed["requests"]["bound_records"] = 0
            if not intents:
                return "no INTENT_RECORDED and no request member"
            if content_status == REQUEST_WITHHELD:
                v.limit("REQUEST_CONTENT_NOT_VERIFIED",
                        "request_content WITHHELD: each request digest and size is bound to "
                        "its intent and custody entry (REQ-004), the request bytes are not in "
                        "the package and are not recomputed")
                return "request_content WITHHELD: no request member; bound by REQ-004"
            if "REQUEST_UNAVAILABLE" in declared_limitations:
                v.limit("REQUEST_CONTENT_NOT_VERIFIED",
                        "REQUEST_UNAVAILABLE and no request member: the requests sent are not "
                        "in the package; RequestIdentity is not recomputed (§12.2)")
                return "REQUEST_UNAVAILABLE declared by the producer and no request member"
            p.append(f"{len(intents)} intent records but no request member and no "
                     f"REQUEST_UNAVAILABLE")
            return None
        unread = [path for path in listed if path not in read]
        if unread:
            p.append(f"request members that did not read (see REQ-002): {unread}")
        seen: dict[str, str] = {}
        bound = 0
        for path, item in sorted(read.items()):
            record, digest = item["record"], item["digest"]
            if record in seen:
                p.append(f"{path}: record {record!r} already covered by {seen[record]}")
                continue
            seen[record] = path
            record_intents = intents.get(record)
            if not record_intents:
                p.append(f"{path}: record {record!r} has no INTENT_RECORDED")
                continue
            entry = by_record.get(record)
            if entry is None:
                p.append(f"{path}: record {record!r} has no custody entry")
                continue
            ok = True
            for event in record_intents:
                if event.get("request") != digest:
                    p.append(f"{path} ({item['availability']}): request {digest} is not the "
                             f"INTENT_RECORDED request {event.get('request')} for {record!r}")
                    ok = False
                if event.get("position") != entry.get("position"):
                    p.append(f"{record}: intent position {event.get('position')} != custody "
                             f"position {entry.get('position')}")
                    ok = False
            if entry.get("request") != digest:
                p.append(f"{path} ({item['availability']}): request {digest} is not the custody "
                         f"entry's request {entry.get('request')} for {record!r}")
                ok = False
            bound += ok
        for record in sorted(set(intents) - set(seen), key=str):
            p.append(f"intent {record}: no request or request_envelope member")
        observed["requests"]["bound_records"] = bound
        withheld = sum(n for state, n in availability.items() if state != "materialized")
        if withheld:
            v.limit("REQUEST_CONTENT_NOT_VERIFIED",
                    f"{withheld} request envelope(s) bind a request digest to the intent and "
                    f"custody entry, but the request bytes are not recomputed (§12.2)")
    v.rule("REQ-001", req_001)

    def req_003(p):
        read = requests["members"]
        states = {item["availability"] for item in read.values()}
        listed = any(roles.get(role) for role in REQUEST_ROLES)
        declared = sorted(code for code in declared_limitations
                          if code in REQUEST_LIMITATIONS.values())
        observed["requests"]["producer_declared"] = declared
        for state, code in REQUEST_LIMITATIONS.items():
            has_state = state in states
            if state == "unavailable" and not listed:
                has_state = code in declared_limitations  # the whole-run form (§12.2, P06)
            if code in declared_limitations and not has_state:
                p.append(f"{code} declared, but no request member has availability "
                         f"{state!r} (members: {sorted(states) or 'none'})")
            if has_state and code not in declared_limitations:
                p.append(f"request envelope(s) with availability {state!r}, but {code} is not "
                         f"declared")
        status = ("NO_REQUESTS" if not listed and not declared_limitations else
                  "UNAVAILABLE" if not listed else
                  "MATERIALIZED" if states == {"materialized"} else
                  "ENVELOPED" if "materialized" not in states else "MIXED")
        if content_status == REQUEST_WITHHELD and not listed:
            status = REQUEST_WITHHELD
        observed["requests"]["status"] = status
    v.rule("REQ-003", req_003)

    if structured:
        def req_004(p):
            observed["requests"]["content_status"] = content_status
            envelopes = roles.get("request_envelope", [])
            if envelopes:
                p.append(problem("REQUEST_ENVELOPE_NOT_IN_MANIFEST_3",
                                 f"request_envelope members {sorted(envelopes)}"))
            p.extend(request_content_problems(
                content, [e for e in journal if e.get("event") == "INTENT_RECORDED"],
                {e.get("record"): e for e in entries}, held, set(roles.get("request", [])),
                locked, declared_limitations))
        v.rule("REQ-004", req_004)

        def lim_002(p):
            if limitation_problems(manifest.get("limitations")):
                return "limitations are malformed (LIM-001)"
            preflight = None
            if locked:
                pre = doc("experiment_input").get("pre_execution")
                preflight = None if pre is None else pre["preflight_record"]["limitations"]
            p.extend(limitation_expected(declared_limitations, bool(roles.get("dataset")),
                                         locked, preflight))
        v.rule("LIM-002", lim_002)

    # ------------------------------------------------------------- Input Lock
    def inp_001(p):
        anchors = [e for e in journal if e.get("event") == "INPUT_LOCK_BOUND"]
        if not locked:
            if anchors:
                p.append("the journal anchors an Input Lock the manifest does not declare")
            return "no Input Lock declared (input_lock absent)"
        section = manifest["input_lock"]
        run = doc("run")
        data = one("experiment_input")
        document = doc("experiment_input")
        eii = "experiment_input:" + sha(canonical(document["eii_preimage"]))
        observed["experiment_input_identity"] = eii
        observed["input_digest"] = sha(data)
        anchor = anchors[0] if len(anchors) == 1 else {}
        if not anchors or journal.index(anchors[0]) != 1:
            p.append("INPUT_LOCK_BOUND is not the second journal event exactly once")
        if not (sha(data) == run["input"]["digest"] == anchor.get("input_digest")
                == section["input_digest"]):
            p.append("SHA-256(input) / run.json / INPUT_LOCK_BOUND / manifest disagree")
        if not (eii == document["experiment_input_identity"] == anchor.get("input_identity")
                == run["input"]["identity"] == section["experiment_input_identity"]
                == "experiment_input:" + manifest["identities"]["experiment_input"]["digest"]):
            p.append("ExperimentInputIdentity does not recompute / bind")
        if document["eii_preimage"].get("identity_schema") != \
                EPC_1_IDENTITY_VERSIONS["experiment_input"]:
            p.append("eii_preimage identity_schema is not the dispatched version")
        if document["eii_preimage"].get("contract") != manifest["identities"]["contract"]["digest"]:
            p.append("the Input Lock names another contract")
        if section.get("member") not in roles.get("experiment_input", []):
            p.append("input_lock.member is not the experiment_input member")
        if section.get("verification") != "INPUT_LOCK_OK":
            p.append(f"input_lock verification {section.get('verification')!r}")
    v.rule("INP-001", inp_001)

    def inp_002(p):
        if not locked:
            return "no Input Lock declared"
        section = manifest["input_lock"]["preflight"]
        document = doc("experiment_input")
        pre = document["eii_preimage"]["pre_execution"]
        record_wrap = document["pre_execution"]
        record = record_wrap["preflight_record"]
        gnd = record["gndcrw"]
        result = doc("gndcrw_result")
        gmanifest = doc("gndcrw_manifest")

        if sha(canonical(record)) != record_wrap["preflight_record_sha256"]:
            p.append("preflight_record_sha256 does not recompute")
        if record.get("experiment_input_identity") != document["experiment_input_identity"]:
            p.append("preflight record names another ExperimentInputIdentity")

        # the declared role, never the file name, decides what each member is
        for role, key in (("gndcrw_manifest", "manifest"), ("gndcrw_result", "result")):
            member_path = roles[role][0]
            actual = raw_ref(one(role))
            if section[key].get("member") != member_path or gnd[key].get("member") != member_path:
                p.append(f"{key}: manifest/record locator is not the {role} member")
            declared = {k: section[key][k] for k in ("sha256", "size")}
            recorded = {k: gnd[key][k] for k in ("sha256", "size")}
            if not (actual == declared == recorded == pre[key]):
                p.append(f"{key}: bytes / EVIDENCE preflight / record / EII disagree")
        if raw_ref(one("gndcrw_manifest")) != result["binding"]["manifest"]:
            p.append("GNDCRW result binding does not name the packaged manifest bytes")

        subject_roles = sorted(r for r in INPUT_LOCK_ROLES if r.startswith(SUBJECT_PREFIX))
        subjects = {role[len(SUBJECT_PREFIX):]: role for role in subject_roles}
        for table, where in ((section["subjects"], "EVIDENCE preflight"),
                             (gnd["inputs"], "preflight record"), (pre["inputs"], "EII"),
                             (result["binding"]["subjects"], "GNDCRW result binding"),
                             (gmanifest["subjects"], "GNDCRW manifest")):
            if set(table) != set(subjects):
                p.append(f"{where}: subjects {sorted(table)} != {sorted(subjects)}")
        for name, role in subjects.items():
            actual = raw_ref(one(role))
            member_path = roles[role][0]
            for table, where in ((section["subjects"], "EVIDENCE preflight"),
                                 (gnd["inputs"], "preflight record"), (pre["inputs"], "EII"),
                                 (result["binding"]["subjects"], "GNDCRW result binding"),
                                 (gmanifest["subjects"], "GNDCRW manifest")):
                entry = table.get(name, {})
                if {k: entry.get(k) for k in ("sha256", "size")} != actual:
                    p.append(f"{name}: {where} does not name the bytes of role {role}")
                if "member" in entry and entry["member"] != member_path:
                    p.append(f"{name}: {where} locator is not the {role} member")

        external = {"digest": manifest["identities"]["contract"]["digest"],
                    "scheme": EXTERNAL_SUBJECT_SCHEME}
        for value, where in ((section["external_subject"], "EVIDENCE preflight"),
                             (pre["external_subject"], "EII"),
                             (gnd["external_subject"], "preflight record"),
                             (result["binding"]["external_subject"], "GNDCRW result"),
                             (gmanifest["external_subject"], "GNDCRW manifest")):
            if value != external:
                p.append(f"{where}: external_subject is not the ContractIdentity")
        for value, where in ((result.get("outcome"), "GNDCRW result"),
                             (gnd.get("outcome"), "preflight record"),
                             (section.get("outcome"), "EVIDENCE preflight"),
                             (pre.get("require_outcome"), "EII require_outcome")):
            if value != "RUN":
                p.append(f"{where}: outcome {value!r}, need RUN")
        if gnd.get("exit_code") != 0:
            p.append(f"GNDCRW exit_code {gnd.get('exit_code')!r}")
        if not (result["tool"] == section["tool"] == gnd["tool"]):
            p.append("GNDCRW tool identity differs between result / EVIDENCE / record")
        if not (result["result_version"] == gnd["result_version"] == pre["result_version"]):
            p.append("GNDCRW result_version differs")
        if not (gmanifest["manifest_version"] == gnd["manifest_version"]
                == pre["manifest_version"]):
            p.append("GNDCRW manifest_version differs")
        if not (result["policy_id"] == gnd["policy"] == pre["policy"]):
            p.append("GNDCRW policy differs")
        summary = result.get("summary", {})
        if summary.get("finding_count") != len(result.get("findings", [])):
            p.append("GNDCRW summary finding_count != findings")
        blocking_fail = [f.get("finding_id") for f in result.get("findings", [])
                         if f.get("policy_class") == "BLOCKING" and f.get("status") != "PASS"]
        if blocking_fail:
            p.append(f"GNDCRW BLOCKING findings not PASS: {blocking_fail}")
        # MINOR-12: only a string finding_id becomes a JSON object key; any other id
        # (number, null, bool, object, list - INP-005 refuses it) is kept by index instead
        keyed, unkeyed = {}, []
        for index, f in enumerate(result.get("findings", [])):
            fid = f.get("finding_id")
            if isinstance(fid, str):
                keyed[fid] = f.get("status")
            else:
                unkeyed.append({"index": index, "finding_id": fid, "status": f.get("status")})
        observed["gndcrw"] = {
            "outcome": result.get("outcome"), "tool": result.get("tool"),
            "result_version": result.get("result_version"), "policy": result.get("policy_id"),
            "findings": keyed,
            "result_digest": sha(one("gndcrw_result")),
            "manifest_digest": sha(one("gndcrw_manifest")),
        }
        if unkeyed:
            observed["gndcrw"]["findings_without_string_id"] = unkeyed
    v.rule("INP-002", inp_002)

    def inp_003(p):
        if not locked:
            return "no Input Lock declared"
        document = doc("experiment_input")
        _input_structure(document, p)
        if p:
            return None  # the content checks below assume the closed structure
        normalized = document["normalized"]["document"]
        preimage = document["eii_preimage"]
        lock = doc("lock")

        # profile (BVL ILV-10 meaning): digest recomputes, is the EII's, is the normalized one
        profile = document["execution_profile"]
        recomputed = sha(canonical(profile["document"]))
        if not (recomputed == profile["digest"] == preimage["execution"]):
            p.append(f"execution_profile: SHA-256(canonical(document)) {recomputed} / digest "
                     f"{profile['digest']} / eii_preimage.execution {preimage['execution']} "
                     f"disagree")
        if normalized["execution"]["profile"]["document"] != profile["document"]:
            p.append("normalized execution profile is not execution_profile.document")

        # every intent was recorded under the locked profile (BVL ILV-14 meaning, own code):
        # INTENT_RECORDED.intended = profile adapter {adapter_provenance, model_identity}
        adapter = profile["document"].get("adapter")
        if not isinstance(adapter, dict):
            p.append("execution_profile.document.adapter is not an object")
        else:
            intended = {k: adapter.get(k) for k in ("adapter_provenance", "model_identity")}
            intents = [e for e in journal if e.get("event") == "INTENT_RECORDED"]
            off = [e.get("record") for e in intents if e.get("intended") != intended]
            observed["intended_profile"] = {"profile": intended, "intents": len(intents),
                                            "mismatched": len(off)}
            if off:
                p.append(f"{len(off)} INTENT_RECORDED.intended differ from the locked profile "
                         f"adapter {intended} (first: {off[0]!r})")

        # normalized (ILV-11): its digest recomputes; its GNDCRW inputs are the EII's
        recomputed = sha(canonical(normalized))
        if recomputed != document["normalized"]["sha256"]:
            p.append(f"normalized.sha256 {document['normalized']['sha256']} != recomputed "
                     f"{recomputed}")

        # the run label is the run (ILV-8)
        if (normalized.get("run") or {}).get("label") != manifest["run"]["run_id"]:
            p.append(f"normalized run.label {(normalized.get('run') or {}).get('label')!r} "
                     f"is not the run {manifest['run']['run_id']!r}")

        # declared lock identities = the lock (ILV-9, first half)
        stated = {kind: document["declaration"][key]
                  for key, kind in DECLARATION_IDENTITY_KEYS.items()}
        if stated != lock["identities"]:
            p.append(f"input.json declaration identities {stated} are not the lock's")
        _declaration_matches_lock(normalized["declaration"]["document"], lock["declaration"],
                                  p, v)

        # pre_execution present in all three places or none; inputs agree
        pre = preimage.get("pre_execution")
        normalized_pre = (normalized.get("pre_execution") or {}).get("gndcrw")
        if not ((pre is None) == (normalized_pre is None) == ("pre_execution" not in document)):
            p.append("pre_execution present in some of eii_preimage / normalized / input.json "
                     "and not others")
        elif pre is not None:
            stripped = {name: {k: ref.get(k) for k in ("sha256", "size")}
                        for name, ref in normalized_pre["inputs"].items()}
            if stripped != pre["inputs"]:
                p.append("normalized GNDCRW inputs != EII inputs")
            for key in ("contracts", "manifest_version", "result_version", "policy",
                        "require_outcome"):
                if normalized_pre.get(key) != pre.get(key):
                    p.append(f"normalized GNDCRW {key} != EII {key}")
            if normalized_pre.get("external_subject_scheme") != \
                    pre["external_subject"].get("scheme"):
                p.append("normalized GNDCRW external_subject_scheme != EII external_subject")
            record = document["pre_execution"]["preflight_record"]
            if record.get("schema") != PREFLIGHT_RECORD_SCHEMA:
                p.append(f"preflight record schema {record.get('schema')!r}")
            if record.get("limitations") != list(PREFLIGHT_LIMITATIONS):
                p.append(f"preflight record limitations {record.get('limitations')!r} are "
                         f"not the frozen list {list(PREFLIGHT_LIMITATIONS)!r}")
    v.rule("INP-003", inp_003)

    unsupported: list[str] = []
    copy_skew: list[str] = []  # INP-004 copies that disagree with each other (REJECTED)

    def inp_004(p):
        if not locked:
            return "no Input Lock declared"
        document = doc("experiment_input")
        result, gmanifest = doc("gndcrw_result"), doc("gndcrw_manifest")
        pre = document["eii_preimage"]["pre_execution"]
        gnd = document["pre_execution"]["preflight_record"]["gndcrw"]
        normalized_pre = document["normalized"]["document"]["pre_execution"]["gndcrw"]
        copies = {
            "result_version": [(result.get("result_version"), "GNDCRW result"),
                               (gnd.get("result_version"), "preflight record"),
                               (pre.get("result_version"), "EII"),
                               (normalized_pre.get("result_version"), "normalized input")],
            "manifest_version": [(gmanifest.get("manifest_version"), "GNDCRW manifest"),
                                 (gnd.get("manifest_version"), "preflight record"),
                                 (pre.get("manifest_version"), "EII"),
                                 (normalized_pre.get("manifest_version"), "normalized input")],
            "policy": [(result.get("policy_id"), "GNDCRW result policy_id"),
                       (gnd.get("policy"), "preflight record"), (pre.get("policy"), "EII"),
                       (normalized_pre.get("policy"), "normalized input")],
            "contracts": [(result.get("contracts"), "GNDCRW result"),
                          (gnd.get("contracts"), "preflight record"),
                          (pre.get("contracts"), "EII"),
                          (normalized_pre.get("contracts"), "normalized input")],
        }
        # the manifest's own schema column, when present, is one more copy
        for role, key in (("gndcrw_result", "result_version"),
                          ("gndcrw_manifest", "manifest_version")):
            schema = by_path[roles[role][0]].get("schema")
            if schema is not None:
                copies[key].append((schema, f"EVIDENCE member schema ({role})"))
        # the result's contracts.manifest names the manifest version it read
        contracts = result.get("contracts")
        if isinstance(contracts, dict) and "manifest" in contracts:
            copies["manifest_version"].append((contracts["manifest"],
                                               "GNDCRW result contracts.manifest"))
        for key, values in copies.items():
            first = values[0][0]
            skew = [where for value, where in values[1:] if value != first]
            if skew:
                copy_skew.append(key)
                p.append(f"GNDCRW {key}: {values[0][1]} says {first!r}; "
                         f"{', '.join(skew)} disagree")
            supported = GNDCRW_SUPPORTED[key]
            for value, where in values:
                if value not in supported:
                    unsupported.append(f"{key}={value!r} ({where})")
        # GNDCRW tool identity: pinned name and digest method; its version is the version
        # of the executable the preflight record says was run (BVL check_result meaning)
        executable = gnd.get("executable")
        run_version = executable.get("version") if isinstance(executable, dict) else None
        if not isinstance(run_version, str):
            p.append("preflight record executable.version is not a string")
        tools = [(result.get("tool"), "GNDCRW result"), (gnd.get("tool"), "preflight record"),
                 (manifest["input_lock"]["preflight"].get("tool"), "EVIDENCE preflight")]
        for tool, where in tools:
            if not _closed(tool, GNDCRW_TOOL_MEMBERS, f"{where} tool", p):
                continue
            if tool["name"] != GNDCRW_TOOL_NAME:
                p.append(f"{where}: tool.name {tool['name']!r}, need {GNDCRW_TOOL_NAME!r}")
            if tool["version"] != run_version:
                copy_skew.append(f"{where} tool.version")
                p.append(f"{where}: tool.version {tool['version']!r} and preflight record "
                         f"executable.version {run_version!r} disagree")
            if tool["code_digest_method"] not in GNDCRW_SUPPORTED["code_digest_method"]:
                unsupported.append(f"code_digest_method={tool['code_digest_method']!r} "
                                   f"({where})")
        for item in unsupported:
            p.append(f"UNSUPPORTED_GNDCRW_VERSION: {item}; this reader supports "
                     f"{_support_summary()}")
        observed["gndcrw_versions"] = {key: values[0][0] for key, values in copies.items()}
        observed["gndcrw_tool"] = {"tool": result.get("tool"), "executable_version": run_version}
    v.rule("INP-004", inp_004)

    def inp_005(p):
        if not locked:
            return "no Input Lock declared"
        result = doc("gndcrw_result")
        declaration = doc("gndcrw_subject_declaration")
        _gndcrw_semantics(result, declaration, p, observed)
    v.rule("INP-005", inp_005)

    def inp_006(p):
        # #176/#179 (BVVH #174 MAJOR-1, BVL-REC-087): adapter kind <-> provenance namespace
        # <-> model identity format <-> what answered; FULLMT's own reading, no BVL code
        if not locked:
            return "no Input Lock declared"
        profile = (doc("experiment_input").get("execution_profile") or {}).get("document")
        adapter = profile.get("adapter") if isinstance(profile, dict) else None
        if not isinstance(adapter, dict):
            p.append("ADAPTER_PROVENANCE_NAMESPACE_MISMATCH: execution_profile.document.adapter "
                     "is not an object")
            return None
        intended = {k: adapter.get(k) for k in ("adapter_provenance", "model_identity")}
        parity = _adapter_parity(adapter, intended, journal)
        observed["adapter_parity"] = {
            "kind": adapter.get("kind"), "problems": len(parity),
            "codes": sorted({problem.split(":", 1)[0] for problem in parity})}
        p.extend(parity)
    v.rule("INP-006", inp_006)

    # ---------------------------------------------------------------- L5 claims
    def clm(p):
        if roles.get("claims"):
            v.limit("CLAIMS_PRESENT_NOT_VERIFIED",
                    "a claims member exists; this reader version does not evaluate claims")
            return "claims member present; CLM rules not implemented in reader 0.1.0"
        return "CLAIMS_NOT_EMITTED declared by the producer; no claim to verify"
    v.rule("CLM-001", clm)

    # ------------------------------------------------------- L5 eligibility report
    # The producer's gate result, located by its declared role. FULLMT does not re-run the
    # producer's gate; it refuses a report it cannot read, one bound to another run, and
    # one that states (or implies) anything but ELIGIBLE — an explicit negative verdict is
    # never promoted to VERIFIED because the rest of the report is not re-derived.
    eligibility: dict = {}

    def elg_001(p):
        path = roles["eligibility_report"][0] if len(roles.get("eligibility_report", [])) == 1 \
            else None
        if path is None:
            raise LookupError("role eligibility_report: not exactly one member")
        member = by_path[path]
        report = doc("eligibility_report")
        declared = member.get("schema")
        tag = report.get("schema") if isinstance(report, dict) else None
        observed["eligibility"] = {"member": path, "member_schema": declared,
                                   "digest": sha(one("eligibility_report"))}
        if member.get("media_type") not in JSON_MEDIA:
            p.append(f"{path}: media_type {member.get('media_type')!r} is not JSON")
        if tag != declared:
            p.append(f"{path}: document schema {tag!r} != manifest member schema {declared!r}")
        if tag != ELIGIBILITY_SCHEMA:
            if tag == declared and isinstance(tag, str):
                eligibility["unsupported"] = tag
            p.append(f"eligibility report schema {tag!r}; this reader supports "
                     f"{ELIGIBILITY_SCHEMA!r}")
            return None
        if not _closed(report, ELIGIBILITY_MEMBERS, "eligibility report", p,
                       optional={"informational"}):
            return None
        if report["producer"] != ELIGIBILITY_PRODUCER:
            p.append(f"eligibility producer {report['producer']!r}, need "
                     f"{ELIGIBILITY_PRODUCER!r}")
        if not isinstance(report.get("informational", {}), dict):
            p.append("eligibility informational is not an object")
        if report["verdict"] not in ELIGIBILITY_VERDICTS:
            p.append(f"eligibility verdict {report['verdict']!r} is not in "
                     f"{sorted(ELIGIBILITY_VERDICTS)}")
        run_ref = report["run"]
        if _closed(run_ref, {"kind", "version", "digest"}, "eligibility run", p,
                   optional={"member"}):
            eligibility["run"] = run_ref
        findings = report["findings"]
        if not isinstance(findings, list) or not findings:
            p.append("eligibility findings is not a non-empty list")
            return None
        good = []
        for index, finding in enumerate(findings):
            where = f"eligibility findings[{index}]"
            if not _closed(finding, ELIGIBILITY_FINDING_MEMBERS, where, p,
                           optional={"subject"}):
                continue
            step, rule_id = finding["step_id"], finding["rule_id"]
            verdict, code = finding["verdict"], finding["code"]
            if not all(isinstance(x, str) for x in (step, rule_id, verdict, code)):
                p.append(f"{where}: step_id/rule_id/verdict/code are not strings")
                continue
            if verdict not in FINDING_CODES:
                p.append(f"{where} ({step}): verdict {verdict!r} is not in "
                         f"{sorted(FINDING_CODES)}")
            elif code != FINDING_CODES[verdict]:
                p.append(f"{where} ({step}): code {code!r} contradicts verdict {verdict!r}")
            expected_rule = ELIGIBILITY_STEP_RULES.get(step, "PRODUCT-INTERNAL")
            if rule_id != expected_rule:
                p.append(f"{where}: step {step} carries rule_id {rule_id!r}, need "
                         f"{expected_rule!r}")
            if "subject" in finding:
                subject = finding["subject"]
                if not (_closed(subject, {"cell"}, f"{where}.subject", p)
                        and isinstance(subject["cell"], str)):
                    p.append(f"{where}: subject is not {{cell: string}}")
                if step not in ELIGIBILITY_CELL_STEPS:
                    p.append(f"{where}: step {step} is not a per-cell step")
            good.append(finding)
        eligibility["report"] = report
        eligibility["findings"] = good
        counts: dict[str, int] = {}
        for finding in good:
            counts[finding["verdict"]] = counts.get(finding["verdict"], 0) + 1
        steps = {f["step_id"]: f["verdict"] for f in good if "subject" not in f}
        observed["eligibility"].update({
            "schema": tag, "producer": report["producer"], "verdict": report["verdict"],
            "run": run_ref, "finding_verdicts": counts,
            "custody_integrity": steps.get("custody_integrity"), "steps": steps})
    v.rule("ELG-001", elg_001)

    def elg_002(p):
        run_ref = eligibility.get("run")
        if run_ref is None:
            raise LookupError("eligibility run reference not readable (see ELG-001)")
        lock, run = doc("lock"), doc("run")
        recomputed = sha(canonical({"epc_identity": "run/1", "run_id": run["run"],
                                    "lock": {k: lock["identities"][k]
                                             for k in ("contract", "design", "schedule")}}))
        declared = manifest["run"]["run_identity"].get("digest")
        observed["eligibility"]["run_binding"] = {"report": run_ref.get("digest"),
                                                  "manifest": declared,
                                                  "recomputed": recomputed}
        if run_ref.get("kind") != "run" or run_ref.get("version") != \
                EPC_1_IDENTITY_VERSIONS["run"]:
            p.append(f"eligibility run reference kind/version {run_ref.get('kind')!r}/"
                     f"{run_ref.get('version')!r}, need run/{EPC_1_IDENTITY_VERSIONS['run']}")
        if not (run_ref.get("digest") == recomputed == declared):
            p.append(f"eligibility run.digest {run_ref.get('digest')} / recomputed RunIdentity "
                     f"{recomputed} / manifest run_identity {declared} disagree")
        if "member" in run_ref and run_ref["member"] not in roles.get("run", []):
            p.append("eligibility run locator is not the run member")
    v.rule("ELG-002", elg_002)

    def elg_003(p):
        report = eligibility.get("report")
        if report is None:
            raise LookupError("eligibility report not readable (see ELG-001)")
        findings = eligibility["findings"]
        verdict = report["verdict"]
        violated = [f"{f['step_id']}" + (f"[{f['subject']['cell']}]" if "subject" in f else "")
                    for f in findings if f["verdict"] != "VERIFIED" and
                    f["verdict"] != "NO_CLAIM"]
        if verdict != "ELIGIBLE":
            p.append(f"producer eligibility verdict is {verdict!r}")
        if violated:
            p.append(f"producer findings not VERIFIED/NO_CLAIM: {violated}")
        # the report must agree with itself: ELIGIBLE iff nothing VIOLATED
        if (verdict == "ELIGIBLE") == bool(violated):
            p.append(f"verdict {verdict!r} contradicts its own findings (violated: {violated})")
        step_findings: dict[str, list[str]] = {}
        for finding in findings:
            if "subject" not in finding:
                step_findings.setdefault(finding["step_id"], []).append(finding["verdict"])
        for step, rule_id in ELIGIBILITY_STEP_RULES.items():
            if step in ELIGIBILITY_OPTIONAL_STEPS:
                continue
            got = step_findings.get(step, [])
            if len(got) != 1:
                p.append(f"step {step} ({rule_id}): {len(got)} run-level findings, need 1")
        # the steps FULLMT recomputes itself are claims the producer must have made
        for step in ELIGIBILITY_RECOMPUTED_STEPS:
            got = step_findings.get(step, [])
            need = "VERIFIED" if step != "input_lock" or locked else "NO_CLAIM"
            if got and got != [need]:
                p.append(f"step {step}: producer says {got[0]!r}, need {need!r}")
    v.rule("ELG-003", elg_003)

    def elg_004(p):
        findings = eligibility.get("findings")
        if findings is None:
            raise LookupError("eligibility findings not readable (see ELG-001)")
        status = {r["rule_id"]: r["status"] for r in v.rules}
        cross = {}
        for finding in findings:
            rule_id = finding["rule_id"]
            if "subject" in finding or rule_id not in status or \
                    finding["step_id"] not in ELIGIBILITY_RECOMPUTED_STEPS:
                continue
            cross[finding["step_id"]] = {"rule_id": rule_id, "producer": finding["verdict"],
                                         "fullmt": status[rule_id]}
            if finding["verdict"] == "VERIFIED" and status[rule_id] != PASS:
                p.append(f"{finding['step_id']}: producer VERIFIED, FULLMT {rule_id} "
                         f"{status[rule_id]}")
            if finding["verdict"] == "VIOLATED" and status[rule_id] == PASS:
                p.append(f"{finding['step_id']}: producer VIOLATED, FULLMT {rule_id} PASS "
                         f"(the producer's negative verdict stands)")
        observed["eligibility"]["cross_check"] = cross
        attested = sorted({f["step_id"] for f in findings
                           if f["step_id"] not in ELIGIBILITY_RECOMPUTED_STEPS})
        observed["eligibility"]["attested_steps"] = attested
    v.rule("ELG-004", elg_004)

    def elg_005(p):
        attested = (observed.get("eligibility") or {}).get("attested_steps") or []
        v.limit("ELIGIBILITY_STEPS_ATTESTED",
                f"producer gate steps {attested} are not re-derived by this reader; an explicit "
                f"negative verdict on them still rejects (ELG-003)")
        return "product-internal gate steps are attested (PRODUCT_INTERNAL_STEPS_ATTESTED); " \
               "not re-derived"
    v.rule("ELG-005", elg_005)

    observed.update({
        "members": len(members),
        "run_id": manifest.get("run", {}).get("run_id"),
        "input_lock": (manifest.get("input_lock") or {}).get("classification"),
        "custody_state": _safe(lambda: doc("custody_head").get("state")),
        "manifest_digest": sha(manifest_bytes),
    })
    if eligibility.get("unsupported"):
        raise ReaderError(ErrorCode.UNSUPPORTED_ELIGIBILITY_SCHEMA,
                          f"{eligibility['unsupported']!r}; this reader supports "
                          f"{ELIGIBILITY_SCHEMA!r}")
    # Consistent but outside the support table: the reader cannot judge this GNDCRW version
    # at all (ERROR), as opposed to copies that disagree with each other (REJECTED).
    if unsupported and not copy_skew:
        raise ReaderError(ErrorCode.UNSUPPORTED_GNDCRW_VERSION, "; ".join(unsupported))


def _closed(value, members: set, where: str, p: list, optional: set = frozenset()) -> bool:
    if not isinstance(value, dict):
        p.append(f"{where} is not an object")
        return False
    missing, extra = members - set(value), set(value) - members - set(optional)
    if missing or extra:
        p.append(f"{where}: members {sorted(value)} (missing {sorted(missing)}, "
                 f"unknown {sorted(extra)})")
        return False
    return True


def _closed_str(value, allowed) -> str | None:
    """A string inside a closed vocabulary, else None. The type test comes first so an
    object / list value is never hashed (no traceback on malformed input)."""
    return value if isinstance(value, str) and value in allowed else None


def _gndcrw_finding_problems(finding) -> list[str]:
    """One GNDCRW finding: first the typed member surface the semantic matrix reads, then
    the pinned matrix - reason_code fixes (status, policy_class), finding_kind fixes the
    allowed reason codes and the identity (rule finding: finding_id = rule_id; UD::, PRE::
    verifier-generated findings: rule_id null, except rule-level INVALID_DECLARATION_*)."""
    if not isinstance(finding, dict):
        return ["is not an object"]
    if set(finding) != GNDCRW_FINDING_MEMBERS:
        missing = sorted(GNDCRW_FINDING_MEMBERS - set(finding))
        return [("has no rule_id member; " if "rule_id" in missing else "") +
                f"members: missing {missing}, "
                f"unknown {sorted(set(finding) - GNDCRW_FINDING_MEMBERS)}"]
    out = []
    if finding["finding_version"] != GNDCRW_FINDING_VERSION:
        out.append(f"finding_version {finding['finding_version']!r} is not "
                   f"{GNDCRW_FINDING_VERSION}")
    fid, rule_id = finding["finding_id"], finding["rule_id"]
    if not isinstance(fid, str) or not fid:
        out.append("has no finding_id")
    # rule_id is required, value string | null (bool, number, object, list are refused)
    if rule_id is not None and not isinstance(rule_id, str):
        out.append(f"rule_id {rule_id!r} is neither a string nor null")
    policy = _closed_str(finding["policy_class"], GNDCRW_POLICY_STATUSES)
    status = _closed_str(finding["status"], GNDCRW_STATUSES)
    kind = _closed_str(finding["finding_kind"], GNDCRW_KIND_REASONS)
    reason = _closed_str(finding["reason_code"], GNDCRW_REASONS)
    if policy is None:
        out.append(f"policy_class {finding['policy_class']!r} is not in "
                   f"{list(GNDCRW_POLICY_STATUSES)}")
    elif status is None or status not in GNDCRW_POLICY_STATUSES[policy]:
        out.append(f"status {finding['status']!r} is not allowed under {policy} "
                   f"{list(GNDCRW_POLICY_STATUSES[policy])}")
    if kind is None:
        out.append(f"finding_kind {finding['finding_kind']!r} is not an emitted v0.1 kind")
    if reason is None:
        out.append(f"reason_code {finding['reason_code']!r} is not a v0.1 public reason code")
    target, scope = finding["target"], finding["scope"]
    if target is not None and not (
            isinstance(target, dict) and set(target) == {"kind", "id"}
            and _closed_str(target["kind"], GNDCRW_TARGET_KINDS) and
            isinstance(target["id"], str)):
        out.append(f"target {target!r} is not null or {{kind: TARGET|COMPOSITION, id: string}}")
    if scope is not None and not (isinstance(scope, dict) and
                                  isinstance(scope.get("kind"), str)):
        out.append(f"scope {scope!r} is not null or an object with a string kind")
    if out:
        return out  # the matrix is only evaluated over well-typed closed values
    if GNDCRW_REASONS[reason] != (status, policy):
        out.append(f"reason_code {reason} is {'/'.join(GNDCRW_REASONS[reason])} under "
                   f"{GNDCRW_STRICT_POLICY}, not {status}/{policy}")
    if reason not in GNDCRW_KIND_REASONS[kind]:
        out.append(f"reason_code {reason} is not a {kind} reason")
    if kind in GNDCRW_RULE_KINDS:
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
            or target is not None or scope is not None):  # ASSEMBLY_FIDELITY/PROVENANCE/PREMISE
        out.append(f"a {kind} finding is PRE::{reason}::<subject> with rule_id, target and "
                   f"scope null")
    return out


def _gndcrw_binding_problems(finding: dict, rules: dict) -> list[str]:
    """A finding with a string rule_id is bound to that declared rule: its kind to the
    rule's section (§7) and its target to the rule's target (§6.1)."""
    rule_id, kind, reason = finding["rule_id"], finding["finding_kind"], finding["reason_code"]
    if rule_id is None:
        return []
    if rule_id not in rules:
        return [f"rule_id {rule_id} is not a declared rule"]
    if kind not in GNDCRW_RULE_KINDS:
        return []  # INVALID_DECLARATION_*: the rule's own precondition, in any section
    section, target = rules[rule_id]
    wanted = GNDCRW_RULE_KINDS[kind] or (
        "expected_changes" if reason.startswith("COMPOSITION_CHANGE_") else "invariants")
    out = []
    if section != wanted:
        out.append(f"a {kind} {reason} finding cannot evaluate the {section} rule {rule_id}")
    if finding["target"] != target:
        out.append(f"target {finding['target']} is not rule {rule_id}'s target {target}")
    elif ((target["kind"] == "COMPOSITION") != (kind == "COMPOSITION")
            and kind != "DECLARED_CONSEQUENCE"):
        out.append(f"a {kind} finding cannot evaluate a {target['kind']} target (§7)")
    return out


def _gndcrw_semantics(result, declaration, p: list, observed: dict) -> None:
    """The GNDCRW result's findings, summary and outcome agree (RESULT_CONTRACT §6-§11, §17,
    §19-§21; DECLARATION_CONTRACT §19; VS §11.2). The declaration is the
    gndcrw_subject_declaration member, found by role. Per finding the typed member surface
    and the pinned semantic matrix; then the summary and the STRICT outcome recomputed; then
    exactly one finding per declared rule, bound to that rule. Unknown values fail closed."""
    if not isinstance(result, dict):
        p.append("GNDCRW result is not an object")
        return
    findings = result.get("findings")
    if not isinstance(findings, list):
        p.append("GNDCRW findings is not a list")
        return
    # §19 focal-change requirement: a declaration without expected_changes still yields a
    # BLOCKING NO_FOCAL_EXPECTED_CHANGE finding, so a contract result never has zero findings
    if not findings:
        p.append("GNDCRW findings is empty; the pinned contract always yields at least one "
                 "finding (focal-change requirement)")
    closed = True
    ids = []
    for index, finding in enumerate(findings):
        problems = _gndcrw_finding_problems(finding)
        if problems:
            fid = finding.get("finding_id") if isinstance(finding, dict) else None
            p.extend(f"GNDCRW findings[{index}] ({fid!r}): {item}" for item in problems)
            closed = False
        if isinstance(finding, dict) and isinstance(finding.get("finding_id"), str):
            ids.append(finding["finding_id"])
    if len(ids) != len(set(ids)):
        p.append("GNDCRW finding_id values repeat")
    outcome = result.get("outcome")
    if not isinstance(outcome, str) or outcome not in GNDCRW_OUTCOMES:
        p.append(f"GNDCRW outcome {outcome!r} is not in {sorted(GNDCRW_OUTCOMES)}")
    # rule_id -> (declaration section, rule target); None when the declaration is unreadable
    rules: dict | None = {}
    if not isinstance(declaration, dict):
        p.append("GNDCRW declaration snapshot is not an object")
        rules = None
    else:
        for key in GNDCRW_DECLARED_RULES:
            section = declaration.get(key)
            if section is None:
                continue
            if not isinstance(section, list) or not all(isinstance(r, dict) and
                                                        isinstance(r.get("rule_id"), str)
                                                        for r in section):
                p.append(f"GNDCRW declaration {key} is not a list of rules with rule_id")
                rules = None
                break
            for rule in section:
                if rule["rule_id"] in rules:
                    p.append(f"GNDCRW declaration rule_id {rule['rule_id']} repeats")
                rules[rule["rule_id"]] = (key, rule.get("target"))
    observed["gndcrw_semantics"] = {"findings": len(findings),
                                    "declared_rules": sorted(rules or ())}
    if not closed:
        return  # the summary, outcome and binding are only evaluated over closed findings
    summary = {"finding_count": len(findings),
               "by_status": {s: sum(f["status"] == s for f in findings)
                             for s in GNDCRW_STATUSES},
               "by_policy_class": {c: sum(f["policy_class"] == c for f in findings)
                                   for c in GNDCRW_POLICY_STATUSES}}
    observed["gndcrw_semantics"]["summary_recomputed"] = summary
    if result.get("summary") != summary:
        p.append(f"GNDCRW summary {result.get('summary')} does not recompute from the findings "
                 f"({summary})")
    if result.get("policy_id") == GNDCRW_STRICT_POLICY:
        blocking = [f["status"] for f in findings if f["policy_class"] == "BLOCKING"]
        strict = ("BLOCK" if "FAIL" in blocking else
                  "UNVERIFIABLE" if "UNVERIFIABLE" in blocking else "RUN")
        observed["gndcrw_semantics"]["outcome_recomputed"] = strict
        if outcome != strict:
            p.append(f"GNDCRW outcome {outcome!r} is not the {GNDCRW_STRICT_POLICY} "
                     f"aggregation of the findings ({strict!r})")
    if rules is None:
        return
    for index, finding in enumerate(findings):
        p.extend(f"GNDCRW findings[{index}] ({finding['finding_id']!r}): {item}"
                 for item in _gndcrw_binding_problems(finding, rules))
    # only a string rule_id covers a declared rule; a null rule_id covers none
    bound = [f["rule_id"] for f in findings if f["rule_id"] is not None]
    missing = sorted(set(rules) - set(bound))
    if missing:
        p.append(f"GNDCRW declared rules {missing} have no finding")
    repeated = sorted({r for r in bound if bound.count(r) > 1})
    if repeated:
        p.append(f"GNDCRW declared rules {repeated} have more than one finding")


def _envelope_structure(document, where: str, p: list) -> bool:
    """A closed boomvalley-epc-request-envelope-1 document (§12.2)."""
    if not _closed(document, ENVELOPE_MEMBERS, where, p, optional=ENVELOPE_OPTIONAL):
        return False
    ok = True
    availability = document["availability"]
    if not isinstance(document["record"], str):
        p.append(f"{where}: record is not a string")
        ok = False
    if availability not in ENVELOPE_AVAILABILITY:
        p.append(f"{where}: availability {availability!r} is not in "
                 f"{sorted(ENVELOPE_AVAILABILITY)} (a materialised request is a request "
                 f"member, not an envelope)")
        ok = False
    ref = document["request"]
    if _closed(ref, {"kind", "version", "digest"}, f"{where}.request", p):
        if ref["kind"] != "request" or ref["version"] != EPC_1_IDENTITY_VERSIONS["request"]:
            p.append(f"{where}: request reference kind/version {ref['kind']!r}/"
                     f"{ref['version']!r}, need request/{EPC_1_IDENTITY_VERSIONS['request']}")
            ok = False
        if not (isinstance(ref["digest"], str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", ref["digest"])):
            p.append(f"{where}: request.digest is not sha256:<64 lowercase hex>")
            ok = False
    else:
        ok = False
    for state, key, fields in (("redacted", "redacted", {"document_skeleton", "commitments"}),
                               ("external", "external", {"locator", "custodian"})):
        if (availability == state) != (key in document):
            p.append(f"{where}: member {key!r} is required with, and only with, "
                     f"availability {state!r}")
            ok = False
        elif key in document:
            ok = _closed(document[key], fields, f"{where}.{key}", p) and ok
    if "reason_code" in document and document["reason_code"] not in ENVELOPE_REASONS:
        p.append(f"{where}: reason_code {document['reason_code']!r} is not in "
                 f"{sorted(ENVELOPE_REASONS)}")
        ok = False
    return ok


def _input_structure(document, p: list) -> None:
    """input.json is a closed bvl-input-lock-2 document (BVL ILV-6 meaning, own code)."""
    if not isinstance(document, dict) or document.get("schema") != INPUT_LOCK_SCHEMA:
        p.append(f"input.json is not a {INPUT_LOCK_SCHEMA} document")
        return
    if not _closed(document, INPUT_MEMBERS, "input.json", p, optional={"pre_execution"}):
        return
    if "pre_execution" in document:
        _closed(document["pre_execution"], INPUT_PRE_EXECUTION_MEMBERS,
                "input.json pre_execution", p)
    preimage = document["eii_preimage"]
    if _closed(preimage, EII_PREIMAGE_MEMBERS, "eii_preimage", p, optional={"pre_execution"})             and "pre_execution" in preimage:
        _closed(preimage["pre_execution"], EII_PRE_EXECUTION_MEMBERS,
                "eii_preimage.pre_execution", p)
    _closed(document["declaration"], set(DECLARATION_IDENTITY_KEYS), "input.json declaration", p)
    profile = document["execution_profile"]
    if _closed(profile, EXECUTION_PROFILE_MEMBERS, "execution_profile", p):
        if not isinstance(profile["document"], dict) or                 profile["document"].get("schema") != EXECUTION_PROFILE_SCHEMA:
            p.append(f"execution_profile.document is not {EXECUTION_PROFILE_SCHEMA}")
    normalized = document["normalized"]
    if not _closed(normalized, {"sha256", "document"}, "normalized", p):
        return
    body = normalized["document"]
    if not isinstance(body, dict) or body.get("schema") != NORMALIZED_SCHEMA             or body.get("envelope_schema") != NORMALIZED_ENVELOPE:
        p.append(f"normalized.document is not {NORMALIZED_SCHEMA}/{NORMALIZED_ENVELOPE}")
        return
    if not set(body) <= NORMALIZED_MEMBERS:
        p.append(f"normalized.document: unknown members {sorted(set(body) - NORMALIZED_MEMBERS)}")
    for path in (("declaration", "document"), ("execution", "profile", "document")):
        node = body
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            p.append(f"normalized.document.{'.'.join(path)} is not an object")


def _declaration_matches_lock(embedded, locked, p: list, v: "Verification") -> None:
    """The declaration input.json carries is the one the lock was made from.

    The lock holds a normalized declaration (factors and levels sorted, defaults filled in).
    Re-locking is producer semantics this reader does not reproduce, so the comparison is
    portable: every member the embedded declaration states must equal the lock's, with the
    order of factors, levels and expectation rules ignored. Members only the lock has are
    producer-filled defaults and are reported as a consumer limitation, not re-derived."""
    if not isinstance(embedded, dict) or not isinstance(locked, dict):
        p.append("embedded or locked declaration is not an object")
        return

    def portable(key, value):
        if key == "factors" and isinstance(value, list):
            return sorted((f.get("name"), sorted(f.get("levels") or [], key=canonical))
                          if isinstance(f, dict) else canonical(f) for f in value)
        if key == "execution_expectations" and isinstance(value, list):
            return sorted(canonical(rule) for rule in value)
        return value

    for key in sorted(embedded):
        if key not in locked:
            p.append(f"embedded declaration member {key!r} is not in the lock's declaration")
        elif portable(key, embedded[key]) != portable(key, locked[key]):
            p.append(f"embedded declaration {key} differs from the lock's declaration")
    defaults = sorted(set(locked) - set(embedded))
    if defaults:
        v.limit("DECLARATION_DEFAULTS_NOT_REDERIVED",
                f"lock declaration members {defaults} are producer-filled; the embedded "
                f"declaration omits them and this reader does not re-derive defaults")


def _support_summary() -> str:
    parts = []
    for key, values in GNDCRW_SUPPORTED.items():
        shown = sorted(canonical(x).decode() if isinstance(x, dict) else x for x in values)
        parts.append(f"{key}={shown}")
    return ", ".join(parts)


def _schema_tag(document):
    if not isinstance(document, dict):
        return None
    for key in ("schema", "document", "lock_schema", "manifest_version", "result_version",
                "package_schema"):
        if isinstance(document.get(key), str):
            return document[key]
    return None


def _artifact_member(name, roles):
    """The artifact member a custody entry names: exactly the role=artifact member at
    artifacts/<name>. Never a basename match elsewhere in the package."""
    if not isinstance(name, str) or "/" in name or member_path_problem(name):
        return None
    path = f"{ARTIFACT_STORE}/{name}"
    return path if path in roles.get("artifact", []) else None


def member_order(path: str):
    """members[] order: path segments case-folded, then the exact path (code points)."""
    return [segment.casefold() for segment in path.split("/")], path


def _jsonl_canonical(path: str, data: bytes, p: list) -> None:
    """Each acknowledged JSONL line is its canonical-json-1 form followed by one LF."""
    end = data.rfind(b"\n") + 1
    bad = []
    for number, line in enumerate(data[:end].split(b"\n")[:-1], 1):
        try:
            if canonical(strict_json(line)) != line:
                bad.append(number)
        except Malformed as error:
            p.append(f"{path} line {number}: {error}")
            return
    if bad:
        crlf = b"\r\n" in data[:end]
        p.append(f"{path}: {len(bad)} line(s) not canonical-json-1 + LF (first: line {bad[0]}"
                 f"{'; CRLF line ends' if crlf else ''})")


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — observational only
        return None


# manifest-2 is not handled: no -2 package was ever consumed here, and -3 supersedes it.
HANDLERS = {MANIFEST_1: verify_epc_manifest_1, MANIFEST_3: verify_epc_manifest_3}


def _git(repo: Path, *argv) -> bytes:
    proc = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *argv],
                          capture_output=True, stdin=subprocess.DEVNULL)
    if proc.returncode:
        raise LookupError(f"git {' '.join(argv)}: "
                          f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def git_source_manifest(repo: Path, commit: str, paths) -> str:
    """git-source-manifest-v1: the identity of `paths` as committed at `commit`.

    Each repo-relative path is read as its Git blob (the committed bytes, never the
    checkout: no EOL conversion, no filter), the entries {path, sha256} are sorted by
    path, and the canonical-json-1 manifest {algorithm, entries} is hashed. The working
    tree, its EOL settings and any file outside `paths` cannot change the result."""
    entries = [{"path": path, "sha256": sha(_git(repo, "cat-file", "blob", f"{commit}:{path}"))}
               for path in sorted(set(paths))]
    return sha(canonical({"algorithm": CODE_DIGEST_METHOD, "entries": entries}))


@lru_cache(maxsize=1)
def reader_identity() -> dict:
    """code_digest over READER_SOURCES as committed at HEAD, plus the commit and whether
    the checkout of those sources differs from it (`source_tree`, kept out of the digest).
    Without git or a commit holding every source: code_digest null, source_tree
    "unavailable" (never a checkout-bytes digest under the same name)."""
    here = Path(__file__).resolve().parent
    try:
        top = Path(_git(here, "rev-parse", "--show-toplevel").decode("utf-8").strip())
        prefix = _git(here, "rev-parse", "--show-prefix").decode("utf-8").strip()
        commit = _git(top, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
        paths = [prefix + name for name in READER_SOURCES]
        digest = git_source_manifest(top, commit, paths)
        dirty = _git(top, "status", "--porcelain", "--untracked-files=all", "--",
                     *paths).strip()
    except (LookupError, OSError, UnicodeDecodeError) as error:
        log.warning("reader code identity unavailable: %s", error)
        return {"code_digest": None, "code_digest_method": CODE_DIGEST_METHOD,
                "source_commit": None, "source_tree": "unavailable"}
    return {"code_digest": digest, "code_digest_method": CODE_DIGEST_METHOD,
            "source_commit": commit, "source_tree": "dirty" if dirty else "clean"}


def _failure(error: BaseException) -> tuple[ErrorCode, str]:
    """The stable error code of an exception that stopped the reader."""
    if isinstance(error, (ReaderError, m4.Refused)):
        return error.code, error.detail
    detail = f"{type(error).__name__}: {error}"
    if isinstance(error, PermissionError):
        return ErrorCode.PERMISSION_DENIED, detail
    if isinstance(error, OSError):
        return ErrorCode.IO_ERROR, detail
    if isinstance(error, (RecursionError, MemoryError)):
        return ErrorCode.CONSUMER_RUNTIME_ERROR, detail
    return ErrorCode.INTERNAL_ERROR, detail


def _at_root(directory: Path, name: str) -> bool:
    """Whether the package root has an entry of this name (of any kind: a link or a
    directory there still makes the root claim that format)."""
    try:
        return os.path.lexists(directory / name)
    except (OSError, ValueError):
        return False


def verify_package(directory: Path) -> dict:
    """Verify one package directory. Never raises; the outcome says what happened.

    The package root decides the reader: MANIFEST-4.json alone -> the MANIFEST-4 verifier;
    anything else -> the EPC reader (which refuses a root holding both manifests as
    ambiguous, and a root holding neither as not a package)."""
    if _at_root(directory, m4.MANIFEST_4) and not _at_root(directory, MANIFEST):
        return _verify_manifest_4_package(directory)
    return _verify_epc_package(directory)


def _verify_manifest_4_package(directory: Path) -> dict:
    """One MANIFEST-4 package through manifest4_reader, in the FULLMT result envelope."""
    result = {
        "result_schema": m4.RESULT_SCHEMA,
        "verifier": {"name": m4.READER_NAME, "version": READER_VERSION, **reader_identity(),
                     "handlers": [m4.MANIFEST_4_SCHEMA],
                     "producer_contract": dict(m4.PRODUCER_CONTRACT)},
        "input": {"package_path": str(directory), "manifest_file": m4.MANIFEST_4},
    }
    try:
        m4.verify(Package(directory), result)
        log.debug("dispatch %s -> %s (%s)", m4.MANIFEST_4, m4.HANDLER, result["meaning"])
    except Exception as error:  # noqa: BLE001 - every stop becomes one stable error code
        code, detail = _failure(error)
        if code is ErrorCode.INTERNAL_ERROR or code is ErrorCode.CONSUMER_RUNTIME_ERROR:
            log.debug("reader stopped on %s", code, exc_info=True)
        for name in ("failed_rules", "meaning"):  # an ERROR is not a verdict
            result.pop(name, None)
        result["outcome"] = ERROR
        result["error"] = {"code": code, "detail": detail}
        result["error_code"] = code
        result["rules"] = []
        result["observed"] = {}
    result.setdefault("package_identity", None)
    result.setdefault("limitations", {"producer_declared": [], "producer_declared_codes": [],
                                      "consumer": []})
    result["summary"] = {s: sum(1 for r in result["rules"] if r["status"] == s)
                         for s in (PASS, FAIL, NOT_EVALUATED)}
    return result


def _verify_epc_package(directory: Path) -> dict:
    """The historical EPC reader (EVIDENCE.json): semantics unchanged since 0.11.3."""
    v = Verification()
    result = {
        "result_schema": RESULT_SCHEMA,
        "verifier": {"name": READER_NAME, "version": READER_VERSION, **reader_identity(),
                     "handlers": sorted(HANDLERS)},
        "input": {"package_path": str(directory)},
    }
    manifest = None
    try:
        pkg = Package(directory)
        if _at_root(directory, m4.MANIFEST_4):
            raise ReaderError(ErrorCode.AMBIGUOUS_PACKAGE_FORMAT,
                              f"both {MANIFEST} and {m4.MANIFEST_4} at the package root; "
                              f"neither is preferred")
        try:
            manifest_bytes = pkg.read(MANIFEST)
        except LookupError as error:
            raise ReaderError(ErrorCode.NOT_AN_EPC_PACKAGE,
                              f"no readable EVIDENCE.json ({error}) and no "
                              f"{m4.MANIFEST_4}; PACKAGE.json is never used as a "
                              f"fallback") from None
        result["input"]["manifest_digest"] = sha(manifest_bytes)
        # An EVIDENCE.json that is not strict JSON is not a document this reader can act
        # on: a program failure (JSON_PARSE_ERROR), not a rule. Member documents that fail
        # the strict read stay STR-001 rejections.
        try:
            manifest = strict_json(manifest_bytes)
        except Malformed as error:
            raise ReaderError(ErrorCode.JSON_PARSE_ERROR, f"{MANIFEST}: {error}") from None
        schema = _dispatch(manifest)
        result["dispatch"] = {"manifest_schema": schema,
                              "handler": HANDLERS[schema].__name__,
                              "formats": manifest.get("formats")}
        log.debug("dispatch %s -> %s", schema, HANDLERS[schema].__name__)
        HANDLERS[schema](pkg, manifest_bytes, manifest, v)
        failed = [r["rule_id"] for r in v.rules if r["status"] == FAIL]
        outcome = REJECTED if failed else VERIFIED
        result["outcome"] = outcome
        result["failed_rules"] = failed
    except Exception as error:  # noqa: BLE001 - every stop becomes one stable error code
        code, detail = _failure(error)
        if code is ErrorCode.INTERNAL_ERROR or code is ErrorCode.CONSUMER_RUNTIME_ERROR:
            log.debug("reader stopped on %s", code, exc_info=True)
        result["outcome"] = ERROR
        result["error"] = {"code": code, "detail": detail}
        result["error_code"] = code

    result["package_identity"] = (manifest or {}).get("package_identity") \
        if isinstance(manifest, dict) else None
    result["rules"] = v.rules
    result["summary"] = {s: sum(1 for r in v.rules if r["status"] == s)
                         for s in (PASS, FAIL, NOT_EVALUATED)}
    result["observed"] = v.observed
    result["limitations"] = {
        "producer_declared": list((manifest or {}).get("limitations") or [])
        if isinstance(manifest, dict) else [],
        "producer_declared_codes": sorted(set(limitation_codes(
            manifest.get("limitations"), manifest.get("manifest_schema") == MANIFEST_3)))
        if isinstance(manifest, dict) else [],
        "consumer": v.consumer_limitations,
    }
    return result


def _string_keys(value):
    """A copy whose object keys are all strings: a non-string key becomes
    "<non-string key> " + its JSON text (deterministic; no real string key collides)."""
    if isinstance(value, dict):
        return {(k if isinstance(k, str) else
                 f"<non-string key> {json.dumps(k, sort_keys=True, default=repr)}"):
                _string_keys(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_string_keys(v) for v in value]
    return value


def result_json(result: dict) -> str:
    """The result as stable (sort_keys) JSON. MINOR-12: hostile observed data never makes
    serialization raise - a non-string key / unserializable value is rendered
    deterministically; outcome and rule statuses are untouched."""
    try:
        return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(_string_keys(result), indent=2, sort_keys=True, ensure_ascii=False,
                          default=repr)


def write_result(result: dict, out: Path) -> None:
    """Write the result to `out` whole or not at all: a temp file beside it, then one
    replace. A failure raises (OSError / ValueError) and leaves no partial result file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(result_json(result) + "\n", encoding="utf-8")
        os.replace(temp, out)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        raise


def delivery_failure(out: Path, error: Exception) -> dict:
    """RC129-N2: the --out delivery axis. The verdict (`outcome`) is not touched; the
    undelivered file is reported beside it with its own stable code."""
    return {"status": DeliveryStatus.FAILED, "error_code": ErrorCode.OUTPUT_WRITE_ERROR,
            "out": str(out), "detail": f"{type(error).__name__}: {error}"}


EXIT = EXIT_CODES


class _Parser(argparse.ArgumentParser):
    """argparse whose usage failures are a stable USAGE_ERROR on stderr (exit 2)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        log.error("%s [%s] %s", t("error.USAGE_ERROR"), ErrorCode.USAGE_ERROR, message)
        self.exit(EXIT[ERROR])


def _pre_scan(argv, flag):
    """The value of --locale / --log-level before argparse runs (help and usage text)."""
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    set_locale(_pre_scan(argv, "--locale"))
    configure_logging(_pre_scan(argv, "--log-level"))
    parser = _Parser(prog="fullmt-epc-verify", description=t("cli.reader.description"))
    parser.add_argument("package", type=Path, help=t("cli.reader.package"))
    parser.add_argument("--out", type=Path, help=t("cli.reader.out"))
    parser.add_argument("--quiet", action="store_true", help=t("cli.reader.quiet"))
    parser.add_argument("--locale", choices=SUPPORTED_LOCALES, help=t("cli.locale"))
    parser.add_argument("--log-level", choices=LEVELS, type=str.upper, help=t("cli.log_level"))
    args = parser.parse_args(argv)
    log.info(t("log.reader.start", package=args.package))
    result = verify_package(args.package)
    outcome = result["outcome"]
    if outcome == ERROR:
        code = result["error"]["code"]
        log.error("%s [%s] %s", t(f"error.{code}"), code, result["error"]["detail"])
    else:
        log.info(t("log.reader.outcome", outcome=outcome,
                   failed=", ".join(result.get("failed_rules", [])) or "-"))
    status = EXIT[outcome]
    report = result
    if args.out:
        try:
            write_result(result, args.out)
        except (OSError, ValueError) as error:
            log.error("%s [%s] %s: %s", t("error.OUTPUT_WRITE_ERROR"),
                      ErrorCode.OUTPUT_WRITE_ERROR, args.out, error)
            # the verdict stands; the undelivered file is reported on its own axis
            report = dict(result, delivery=delivery_failure(args.out, error))
            status = EXIT_DELIVERY_FAILED
    # the CLI contract output: the only thing this program writes to stdout
    if args.quiet:
        meaning = f"{result['meaning']} " if result.get("meaning") else ""
        print(f"{outcome} {meaning}{result.get('package_identity')} "
              f"failed={result.get('failed_rules', [])}"
              + (f" delivery={ErrorCode.OUTPUT_WRITE_ERROR}" if "delivery" in report else ""))
    else:
        print(result_json(report))
    return status


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
