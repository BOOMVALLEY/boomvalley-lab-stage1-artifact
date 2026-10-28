"""Central code registry: STATUS / REASON / ERROR / LIMITATION are kept apart.

    STATUS  a state or a judgement: verdicts, eligibility, run / anchor / record
            states, resume decisions, Input Lock classification and verification,
            the GNDCRW outcome and finding status BVL reads, the baseline match,
            and (#76) the execution gate status, the verification status reported
            beside it, and the request content status.
    REASON  a normal decision reason: the GNDCRW finding reason codes BVL binds
            (a RUN preflight is decided by them; none of them is a failure of BVL),
            and (#76) the execution gate reasons and the request content reasons,
            and (#80) the reason a same-run re-lock is refused.
    ERROR   a contract / parse / system failure: the error categories (the CLI's
            `error` member and exit code), the Input Contract §20 refusal classes,
            and every closed refusal code (`InputRefusal.code`, `StrictInputError.code`).
    LIMITATION  (#88) what a package or record does not establish: the closed `code`
            of a limitation (`evidence.limitations`); its free_text is never a code.

Every identifier is a fixed English token and a public name: nothing here is
renamed, only indexed. The domain keeps its own enums and constants (`Verdict`,
`RunState`, `resume.classify.State`, `gndcrw.REASONS`, ...) for its layer;
`tests/lab/test_lab_c1_foundation.py` holds this registry equal to them, keeps
the three namespaces disjoint, and requires every refusal code a module passes
as a literal to be registered here. Human wording lives in `core.i18n`; nothing
here depends on the locale.

One field reuses an ERROR token as a value on purpose (historical, public): the
`input_lock.classification` of a run whose lock does not verify is the refusal
class `INPUT_DRIFT`. It is registered once, as an ERROR class.
"""

from __future__ import annotations

from enum import StrEnum

from boomvalley_lab.core.errors import BOUNDARY_CODES, CLASS_CATEGORY, Category


class Namespace(StrEnum):
    STATUS = "STATUS"
    REASON = "REASON"
    ERROR = "ERROR"
    LIMITATION = "LIMITATION"


# ===================================================================== STATUS
VERDICTS = frozenset({"VERIFIED", "VIOLATED", "NO_CLAIM"})
#: the EPC rule code each verdict is written as (`evidence.epc.CODES`)
RULE_CODES = frozenset({"OK", "VIOLATED", "NO_CLAIM"})
ELIGIBILITY = frozenset({"ELIGIBLE", "NOT_ELIGIBLE"})
RUN_STATES = frozenset({"OPEN", "SEALED", "ABORTED"})
ANCHOR_STATES = frozenset({"VALID", "INVALID", "ABSENT"})
RECORD_STATES = frozenset({"NOT_STARTED", "CALL_OUTCOME_UNKNOWN", "CALL_RETURNED_NOT_PERSISTED",
                           "PERSISTED_UNRECORDED", "PERSISTED", "INCONSISTENT"})
RESUME_DECISIONS = frozenset({"EXECUTE", "SKIP", "ABORT", "OPERATOR_DECISION"})
INPUT_LOCK_CLASSIFICATIONS = frozenset({"INPUT_LOCKED", "NOT_INPUT_LOCKED"})
INPUT_LOCK_VERIFICATIONS = frozenset({"INPUT_LOCK_OK"})
BASELINE_STATUSES = frozenset({"MATCH", "DIFFERS"})
GNDCRW_OUTCOMES = frozenset({"RUN", "BLOCK", "UNVERIFIABLE"})
GNDCRW_FINDING_STATUSES = frozenset({"PASS", "FAIL", "WARNING", "UNVERIFIABLE",
                                     "NOT_APPLICABLE"})
#: #76 C: `execution_gate_status` (`experiment_input.gate.STATUSES`)
EXECUTION_GATE_STATUSES = frozenset({"CLEARED", "MANDATORY_REQUIREMENT_NOT_MET",
                                     "EXECUTION_NOT_POSSIBLE", "NOT_EVALUATED"})
#: #76 C / #81: `verification_status`, reported beside the gate status and never merged
#: with it (ERROR: the verifier could not read the evidence - its error document)
VERIFICATION_STATUSES = frozenset({"VERIFIED", "REJECTED", "ERROR"})
#: #81: `execution_status` of a `bvl run` / a gate record (`experiment_input.gate`)
EXECUTION_STATUSES = frozenset({"STARTED", "NOT_STARTED"})
#: #153: `schedule_preflight_status` (`experiment_input.schedule_gate.STATUSES`)
SCHEDULE_PREFLIGHT_STATUSES = frozenset({"EXACT_MATCH", "MISMATCH", "ERROR", "UNVERIFIABLE",
                                         "NOT_REQUESTED"})
#: #175: `experiment_input_preflight_status` (`experiment_input.input_gate.STATUSES`)
EXPERIMENT_INPUT_PREFLIGHT_STATUSES = frozenset({"EXACT_MATCH", "MISMATCH", "ERROR",
                                                 "UNVERIFIABLE", "NOT_REQUESTED"})
#: #76 D: `request_content_status` (`evidence.requests.STATUSES`)
REQUEST_CONTENT_STATUSES = frozenset({"AVAILABLE", "WITHHELD", "UNAVAILABLE"})

STATUS = frozenset().union(VERDICTS, RULE_CODES, ELIGIBILITY, RUN_STATES, ANCHOR_STATES,
                           RECORD_STATES, RESUME_DECISIONS, INPUT_LOCK_CLASSIFICATIONS,
                           INPUT_LOCK_VERIFICATIONS, BASELINE_STATUSES, GNDCRW_OUTCOMES,
                           GNDCRW_FINDING_STATUSES, EXECUTION_GATE_STATUSES,
                           VERIFICATION_STATUSES, EXECUTION_STATUSES,
                           REQUEST_CONTENT_STATUSES, SCHEDULE_PREFLIGHT_STATUSES,
                           EXPERIMENT_INPUT_PREFLIGHT_STATUSES)

# ===================================================================== REASON
#: GNDCRW-STRICT-0.1 finding reason codes (pinned RESULT_CONTRACT §20-§21)
GNDCRW_REASONS = frozenset({
    "EXPECTED_CHANGE_ASSEMBLED", "EXPECTED_CHANGE_MISSING", "INVARIANT_HELD",
    "INVARIANT_VIOLATED", "UNDECLARED_DIFFERENCE", "DECLARED_CONSEQUENCE_OBSERVED",
    "DECLARED_CONSEQUENCE_NOT_OBSERVED", "DECLARED_CONSEQUENCE_UNOBSERVABLE",
    "COMPOSITION_CHANGE_ASSEMBLED", "COMPOSITION_CHANGE_MISSING", "COMPOSITION_INVARIANT_HELD",
    "COMPOSITION_INVARIANT_VIOLATED", "ENTITY_COMPARABILITY_UNKNOWN",
    "ENTITY_COMPARABILITY_NOT_ESTABLISHED", "ENTITY_MAPPING_MISSING", "TARGET_UNOBSERVABLE",
    "TARGET_MISSING", "TARGET_UNSUPPORTED", "TARGET_AMBIGUOUS", "TARGET_ASSERTED_ONLY",
    "INVALID_DECLARATION_TARGET", "INVALID_DECLARATION_SCOPE", "INVALID_DECLARATION_OPERATION",
    "CONTRADICTORY_DECLARATION", "NO_FOCAL_EXPECTED_CHANGE", "INVALID_COMPARISON_MODE",
    "ASSEMBLY_EQUIVALENCE_PROVEN", "ASSEMBLY_EQUIVALENCE_MISSING",
    "ASSEMBLY_EQUIVALENCE_MISMATCH", "REQUIRED_PROVENANCE_MISSING", "ATTRIBUTED_PREMISE_USED",
})

#: #76 C / #81: execution gate reason codes (`experiment_input.gate.REASONS`)
EXECUTION_GATE_REASONS = frozenset({
    "GNDCRW_PREFLIGHT_NOT_CLEARED", "REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE",
    "VALIDATION_ONLY", "EXECUTION_PROFILE_ABSENT", "LEGACY_RUN_NOT_GATED",
    "EXECUTION_GATE_NOT_RECORDED",
})
#: #76 D: request content reason codes (`evidence.requests.REASONS`)
REQUEST_CONTENT_REASONS = frozenset({
    "REQUEST_WITHHELD_CONFIDENTIAL", "REQUEST_WITHHELD_PERSONAL_DATA",
    "REQUEST_WITHHELD_LICENSE_RESTRICTED", "REQUEST_BUILDER_NOT_RECORDED",
})

#: #80: why a re-lock is refused (`experiment_input.pipeline.RELOCK_REASON`): the Input
#: Lock of a run is never re-bound; a changed input is a new EII and a new run lineage
INPUT_LOCK_RELOCK_REASONS = frozenset({"RELOCK_REQUIRES_NEW_EII_NEW_RUN"})

REASON = frozenset().union(GNDCRW_REASONS, EXECUTION_GATE_REASONS, REQUEST_CONTENT_REASONS,
                           INPUT_LOCK_RELOCK_REASONS)

# ===================================================================== ERROR
#: the CLI `error` member / exit-code category (lower case, historical)
ERROR_CATEGORIES = frozenset(category.value for category in Category)
#: Input Contract §20 refusal classes
REFUSAL_CLASSES = frozenset(CLASS_CATEGORY)
#: `bvl-strict-json-1` parse refusals (`core.strict_json.StrictInputError.code`)
STRICT_JSON_CODES = frozenset({
    "BOM", "INVALID_UTF8", "EMPTY_INPUT", "INVALID_JSON", "TRAILING_CONTENT",
    "TOP_LEVEL_NOT_OBJECT", "DUPLICATE_KEY", "RESOURCE_LIMIT", "NEGATIVE_ZERO",
    "NUMBER_OUT_OF_DOMAIN", "NON_FINITE_NUMBER", "LONE_SURROGATE",
})
#: every closed `InputRefusal.code`
REFUSAL_CODES = frozenset({
    # CLI usage
    "ARGUMENT_INVALID", "ARGUMENT_MISSING", "OPTION_NOT_SUPPORTED",
    # I0-I3 envelope / references / profile
    "CARRIER_UNKNOWN", "YAML_NOT_SUPPORTED", "DECLARATION_STRUCTURE",
    "DERIVED_EXECUTION_NOT_IN_CLI", "LINEAGE_NOT_IN_V1", "ENVELOPE_SCHEMA_MISSING",
    "ENVELOPE_UNKNOWN_FIELD", "EXTENSIONS_INVALID", "FIELD_INVALID", "GNDCRW_ATTACHMENT_INVALID",
    "INFORMATIONAL_INVALID", "NULL_NOT_ALLOWED", "SOURCE_NOT_EXACTLY_ONE", "UNSUPPORTED_SCHEMA",
    "BUILDER_RESERVED_FACTOR", "EXECUTION_PROFILE_REQUIRED_FOR_RUN",
    "EXPECTATION_UNSATISFIABLE_BY_PROFILE", "PROFILE_PROMPT_UNSATISFIABLE", "RUN_ID_REQUIRED",
    "REF_ALIAS", "REF_CARRIER_NOT_JSON", "REF_CASE_ALIAS", "REF_DIGEST_MISMATCH", "REF_HARDLINK",
    "REF_LINK", "REF_MISSING", "REF_NOT_REGULAR", "REF_PATH_INVALID", "REF_TOO_LARGE",
    "REF_YAML_NOT_SUPPORTED",
    "ADAPTER_NOT_IN_V1", "NON_EMPTY_STRING_INVALID", "PROFILE_UNKNOWN_FIELD",
    "REQUEST_BUILDER_UNKNOWN",
    # I4 / I6 GNDCRW
    "GNDCRW_NOT_INSTALLED", "GNDCRW_CAPABILITY_UNSUPPORTED", "GNDCRW_VERSION_UNSUPPORTED",
    "TOOL_CHANGED", "ABNORMAL_EXIT", "GNDCRW_ERROR_UNCLASSIFIED", "GNDCRW_MANIFEST_REFUSED",
    "GNDCRW_USAGE", "GNDCRW_PROVIDER", "GNDCRW_INTERNAL", "GNDCRW_OUTPUT",
    "GNDCRW_SNAPSHOT_INTEGRITY", "GNDCRW_INPUT_INVALID", "GNDCRW_BINDING_MISMATCH",
    "RESULT_TOO_LARGE", "RESULT_INVALID", "RESULT_CONTRACT_MISMATCH", "EXIT_OUTCOME_MISMATCH",
    "RESULT_SEMANTICS_INVALID",
    # Input Lock verification (ILV) / journal anchor
    "EII_MISMATCH", "EXECUTION_BINDING_CHANGED", "INPUT_BINDING_MISSING",
    "INPUT_LOCKED_RUN_REQUIRES_BVL", "INPUT_LOCK_ANCHOR_INVALID", "INPUT_LOCK_DIGEST_MISMATCH",
    "INPUT_LOCK_INVALID", "INPUT_LOCK_MISSING", "INPUT_LOCK_SUBSTITUTED",
    "INTENT_PROFILE_MISMATCH", "JOURNAL_INVALID", "LOCK_BINDING_MISMATCH", "LOCK_SUBSTITUTED",
    "NORMALIZED_MISMATCH", "PREFLIGHT_MISMATCH", "PROFILE_MISMATCH", "REQUEST_BINDING_MISMATCH",
    "RUN_ID_MISMATCH", "RUN_JSON_BINDING_MISMATCH", "RUN_JSON_INVALID", "RUN_NOT_INPUT_LOCKED",
    "UNANCHORED_INPUT_LOCK",
    # #76 B: the Input Lock of a run is never re-bound
    "INPUT_LOCK_RELOCK_REFUSED",
    # #153: the schedule preflight (`experiment_input.schedule_gate.CODES`)
    "SCHEDULE_PREFLIGHT_ORDER_MISMATCH", "SCHEDULE_PREFLIGHT_LENGTH_MISMATCH",
    "SCHEDULE_PREFLIGHT_IDENTITY_MISMATCH", "SCHEDULE_PREFLIGHT_PATH_ERROR",
    "SCHEDULE_PREFLIGHT_PARSE_ERROR", "SCHEDULE_PREFLIGHT_COMPARATOR_FAILED",
    "SCHEDULE_PREFLIGHT_SCHEDULE_MISSING", "SCHEDULE_PREFLIGHT_UNVERIFIABLE",
    "SCHEDULE_PREFLIGHT_BINDING_MISMATCH",
    # #175: the experiment-input preflight (`experiment_input.input_gate.CODES`)
    "EXPERIMENT_INPUT_PREFLIGHT_IDENTITY_MISMATCH", "EXPERIMENT_INPUT_PREFLIGHT_PATH_ERROR",
    "EXPERIMENT_INPUT_PREFLIGHT_PARSE_ERROR", "EXPERIMENT_INPUT_PREFLIGHT_UNVERIFIABLE",
    "EXPERIMENT_INPUT_PREFLIGHT_BINDING_MISMATCH",
    # #176: adapter kind <-> provenance namespace (`runtime.adapters.namespace.CODES`;
    # I3 profile and ILV-15) and the pre-run adapter identity (`runtime.adapters.ollama`)
    "ADAPTER_PROVENANCE_NAMESPACE_MISMATCH", "ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH",
    "ACTUAL_EXECUTION_NOT_INTENDED", "OLLAMA_IDENTITY_MISMATCH", "OLLAMA_TIMEOUT",
    "OLLAMA_UNREACHABLE", "OLLAMA_HTTP_ERROR", "OLLAMA_MODEL_NOT_FOUND",
    "OLLAMA_INVALID_RESPONSE",
    # T1-010: the gated lifecycle (`lifecycle.study` / `lifecycle.gated`) and the
    # retired ungated `boomvalley-lab run` / `resume`
    "BVL-LIFE-001", "BVL-LIFE-002", "BVL-LIFE-003", "BVL-LIFE-004", "BVL-LIFE-005",
    "BVL-LIFE-006", "BVL-LIFE-007", "BVL-LIFE-008", "LEGACY_EXECUTION_RETIRED",
    # T2-006: resuming an interrupted episode (`kernel.replay.RES_CODES`, `lifecycle.gated`)
    "BVL-LIFE-009", "BVL-RES-001", "BVL-RES-002", "BVL-RES-003",
    # T4-011: an installed plugin entry point the lifecycle does not admit
    # (`lifecycle.plugins`)
    "BVL-LIFE-010",
    # SV-09: a gated run directory has one writer (`lifecycle.gated.writing`)
    "BVL-LIFE-011",
    # SV-09 remediation: a run is bound to its tool site and its human desk
    # (`lifecycle.gated._binding`)
    "BVL-LIFE-012",
}) | STRICT_JSON_CODES

#: #126 the CLI boundary's codes for an error without a closed refusal code
#: (`core.errors.error_code`: category default, I/O, parse, unsupported schema)
CLI_BOUNDARY_CODES = BOUNDARY_CODES

ERROR = frozenset().union(ERROR_CATEGORIES, REFUSAL_CLASSES, REFUSAL_CODES, CLI_BOUNDARY_CODES)

# ===================================================================== LIMITATION
#: #88: the EPC manifest's closed limitation codes (`evidence.limitations.CODES`)
EPC_LIMITATIONS = frozenset({
    "NOT_SIGNED", "RUN_ID_LEGACY_LABEL", "PRODUCT_INTERNAL_STEPS_ATTESTED", "CLAIMS_NOT_EMITTED",
    "PROVENANCE_PACKAGE_TIME_ONLY", "DATASET_NOT_ADMITTED", "REQUEST_CONTENT_WITHHELD",
    "REQUEST_UNAVAILABLE", "MODEL_VERSION_NOT_PINNED", "JOURNAL_TORN_TAIL",
    "GNDCRW_DECLARATION_NOT_DERIVED_FROM_EXPERIMENT", "GNDCRW_EXTERNAL_SUBJECT_PROVIDER_ATTESTED",
    "GNDCRW_TOOL_CODE_SELF_REPORTED",
})
#: a gate record's limitations (`experiment_input.gate.RECORD_LIMITATIONS`)
GATE_RECORD_LIMITATIONS = frozenset({"EXECUTION_CAPABILITY_ATTESTED", "NOT_SIGNED"})

LIMITATION = frozenset().union(EPC_LIMITATIONS, GATE_RECORD_LIMITATIONS)

REGISTRY: dict[Namespace, frozenset[str]] = {
    Namespace.STATUS: STATUS,
    Namespace.REASON: REASON,
    Namespace.ERROR: ERROR,
    Namespace.LIMITATION: LIMITATION,
}


def namespace_of(code: str) -> Namespace | None:
    """The one namespace `code` belongs to, or None when it is not a registered code."""
    for namespace, members in REGISTRY.items():
        if code in members:
            return namespace
    return None
