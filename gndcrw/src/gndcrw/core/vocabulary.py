"""Frozen public vocabulary (RESULT_CONTRACT §3, §7-10, §20-21; D-06).

Nothing outside this module spells a status, policy class, finding kind or
reason code as a free string. A combination the contract forbids raises
InternalError at construction: an illegal finding is a verifier bug, never a
result (RESULT §9).
"""

from __future__ import annotations

from gndcrw.errors import InternalError

TOOL_NAME = "gndcrw"
TOOL_VERSION = "0.2.0"

RESULT_VERSION = "gndcrw-result/v0.1"
FINDING_VERSION = "gndcrw-finding/v0.1"
POLICY_ID = "GNDCRW-STRICT-0.1"
CONTRACTS = {
    "declaration": "gndcrw-declaration/v0.1",
    "target_catalog": "gndcrw-target-catalog/v0.1",
    "surface": "gndcrw-surface/v0.1",
    "pair": "gndcrw-pair/v0.1",
    "verification": "gndcrw-verification/v0.1",
}

# Manifest mode (MANIFEST_CONTRACT, RESULT_CONTRACT_V0_2, CLI_SPEC_V0_2)
MANIFEST_VERSION = "gndcrw-manifest/v0.2"
RESULT_VERSION_V02 = "gndcrw-result/v0.2"
CONTRACTS_V02 = {**CONTRACTS, "manifest": MANIFEST_VERSION}
CODE_DIGEST_METHOD = "gndcrw-code-digest/v0.2"
CAPABILITIES_VERSION = "gndcrw-capabilities/v0.2"
SUBJECT_ROLES = ("declaration", "target_catalog", "base_surface", "candidate_surface",
                 "pair_context")
EXTERNAL_SUBJECT_ABSENT = "EXTERNAL_SUBJECT_ABSENT"
EXTERNAL_SUBJECT_PROVIDER_ATTESTED = "EXTERNAL_SUBJECT_PROVIDER_ATTESTED"
TOOL_CODE_SELF_REPORTED = "TOOL_CODE_SELF_REPORTED"
BINDING_LIMITATIONS = (EXTERNAL_SUBJECT_ABSENT, EXTERNAL_SUBJECT_PROVIDER_ATTESTED,
                       TOOL_CODE_SELF_REPORTED)

# statuses
PASS = "PASS"
FAIL = "FAIL"
WARNING = "WARNING"
UNVERIFIABLE = "UNVERIFIABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
STATUSES = (PASS, FAIL, WARNING, UNVERIFIABLE, NOT_APPLICABLE)

# policy classes, in output priority order (RESULT §18)
BLOCKING = "BLOCKING"
REQUIRED_NONBLOCKING = "REQUIRED_NONBLOCKING"
ADVISORY = "ADVISORY"
POLICY_CLASSES = (BLOCKING, REQUIRED_NONBLOCKING, ADVISORY)

LEGAL = {
    BLOCKING: {PASS, FAIL, UNVERIFIABLE, NOT_APPLICABLE},
    REQUIRED_NONBLOCKING: {PASS, FAIL, WARNING, UNVERIFIABLE, NOT_APPLICABLE},
    ADVISORY: {PASS, WARNING, NOT_APPLICABLE},
}

# workflow outcomes
RUN = "RUN"
BLOCK = "BLOCK"
OUTCOMES = (RUN, BLOCK, UNVERIFIABLE)

FINDING_KINDS = (
    "EXPECTED_CHANGE", "INVARIANT", "DECLARED_CONSEQUENCE", "UNDECLARED_DIFFERENCE",
    "COMPOSITION", "ENTITY_COMPARABILITY", "DECLARATION_PRECONDITION",
    "ASSEMBLY_FIDELITY", "PROVENANCE", "PREMISE",
)

OBSERVATION_LEVELS = (
    "SURFACE", "COMPOSITION", "ENTITY_FIELD", "SUBSTRUCTURE",
    "DECLARATION", "PAIR", "ASSEMBLY", "PROVENANCE",
)

# reason code -> (status, policy_class) it may carry (RESULT §21, D-17..D-21)
REASONS: dict[str, tuple[str, str]] = {
    "EXPECTED_CHANGE_ASSEMBLED": (PASS, BLOCKING),
    "EXPECTED_CHANGE_MISSING": (FAIL, BLOCKING),
    "INVARIANT_HELD": (PASS, BLOCKING),
    "INVARIANT_VIOLATED": (FAIL, BLOCKING),
    "UNDECLARED_DIFFERENCE": (WARNING, ADVISORY),
    "DECLARED_CONSEQUENCE_OBSERVED": (WARNING, ADVISORY),
    "DECLARED_CONSEQUENCE_NOT_OBSERVED": (NOT_APPLICABLE, ADVISORY),
    "DECLARED_CONSEQUENCE_UNOBSERVABLE": (WARNING, ADVISORY),
    "COMPOSITION_CHANGE_ASSEMBLED": (PASS, BLOCKING),
    "COMPOSITION_CHANGE_MISSING": (FAIL, BLOCKING),
    "COMPOSITION_INVARIANT_HELD": (PASS, BLOCKING),
    "COMPOSITION_INVARIANT_VIOLATED": (FAIL, BLOCKING),
    "ENTITY_COMPARABILITY_UNKNOWN": (UNVERIFIABLE, BLOCKING),
    "ENTITY_COMPARABILITY_NOT_ESTABLISHED": (UNVERIFIABLE, BLOCKING),
    "ENTITY_MAPPING_MISSING": (UNVERIFIABLE, BLOCKING),
    "TARGET_UNOBSERVABLE": (UNVERIFIABLE, BLOCKING),
    "TARGET_MISSING": (UNVERIFIABLE, BLOCKING),
    "TARGET_UNSUPPORTED": (UNVERIFIABLE, BLOCKING),
    "TARGET_AMBIGUOUS": (UNVERIFIABLE, BLOCKING),
    "TARGET_ASSERTED_ONLY": (UNVERIFIABLE, BLOCKING),
    "INVALID_DECLARATION_TARGET": (FAIL, BLOCKING),
    "INVALID_DECLARATION_SCOPE": (FAIL, BLOCKING),
    "INVALID_DECLARATION_OPERATION": (FAIL, BLOCKING),
    "CONTRADICTORY_DECLARATION": (FAIL, BLOCKING),
    "NO_FOCAL_EXPECTED_CHANGE": (FAIL, BLOCKING),
    "INVALID_COMPARISON_MODE": (FAIL, BLOCKING),
    "ASSEMBLY_EQUIVALENCE_PROVEN": (PASS, BLOCKING),
    "ASSEMBLY_EQUIVALENCE_MISSING": (UNVERIFIABLE, BLOCKING),
    "ASSEMBLY_EQUIVALENCE_MISMATCH": (FAIL, BLOCKING),
    "REQUIRED_PROVENANCE_MISSING": (UNVERIFIABLE, BLOCKING),
    "ATTRIBUTED_PREMISE_USED": (WARNING, ADVISORY),
}

# Registered but never emitted by `gndcrw check` v0.1 (D-24.10).
RESERVED_REASONS = ("REFERENCE_COMPARISON_ONLY",)

LIMITATION_CODES = (
    "ATTRIBUTED_PREMISE_NOT_INDEPENDENTLY_VERIFIED",
    "ASSERTED_ONLY_EVIDENCE",
    "ENTITY_UNDECLARED_SCAN_NOT_PERFORMED",
    "OBSERVATION_UNAVAILABLE",
)


def check_legal(status: str, policy_class: str, reason_code: str) -> None:
    if status not in STATUSES:
        raise InternalError(f"illegal finding status {status!r}")
    if policy_class not in POLICY_CLASSES:
        raise InternalError(f"illegal policy_class {policy_class!r}")
    if status not in LEGAL[policy_class]:
        raise InternalError(f"illegal combination {policy_class} + {status}")
    if reason_code not in REASONS:
        raise InternalError(f"unregistered reason code {reason_code!r}")
    if REASONS[reason_code] != (status, policy_class):
        raise InternalError(
            f"reason {reason_code} carries {REASONS[reason_code]}, not ({status}, {policy_class})"
        )
