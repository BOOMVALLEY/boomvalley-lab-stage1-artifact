"""FULLMT status and error codes — the single definition.

Vocabularies, never mixed:

- StatusCode: what a verification says. `Outcome` is the package verdict, `RuleStatus`
  the per-rule status. A rule-based rejection is `REJECTED` with the failing rule ids in
  `failed_rules`; it carries no error code.
- ErrorCode: an externally observable program failure (the reader could not act on the
  input at all). Only an `ERROR` outcome carries one as `error_code`; it names no rule.
- DeliveryStatus: whether the CLI delivered the result to `--out`. A separate axis from
  the verdict: a failed write never changes `outcome` (VERIFIED stays VERIFIED); it is
  reported as `delivery{status,error_code,...}` with `OUTPUT_WRITE_ERROR` and exit 2.

Rule ids (MEM-001, REQ-004, ...) live in fullmt_rules.RULES and are not error codes.
All values are fixed ASCII tokens, independent of locale.
"""
from __future__ import annotations

from enum import StrEnum


class Outcome(StrEnum):
    """Package verdict (result `outcome`)."""
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class RuleStatus(StrEnum):
    """Per-rule status (result `rules[].status`)."""
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class ErrorCode(StrEnum):
    """Externally observable program failures (result `error.code` / `error_code`)."""
    # CLI argument / input
    USAGE_ERROR = "USAGE_ERROR"
    PACKAGE_NOT_A_DIRECTORY = "PACKAGE_NOT_A_DIRECTORY"
    PACKAGE_ROOT_IS_A_LINK = "PACKAGE_ROOT_IS_A_LINK"
    NOT_AN_EPC_PACKAGE = "NOT_AN_EPC_PACKAGE"
    # package format dispatch (EVIDENCE.json / MANIFEST-4.json at the package root)
    AMBIGUOUS_PACKAGE_FORMAT = "AMBIGUOUS_PACKAGE_FORMAT"
    MANIFEST_NOT_READABLE = "MANIFEST_NOT_READABLE"
    # file / path / permission / I/O
    PERMISSION_DENIED = "PERMISSION_DENIED"
    IO_ERROR = "IO_ERROR"
    OUTPUT_WRITE_ERROR = "OUTPUT_WRITE_ERROR"
    # JSON parse / malformed document (the top-level EVIDENCE.json / MANIFEST-4.json)
    JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
    # unsupported schema / version
    UNSUPPORTED_MANIFEST_SCHEMA = "UNSUPPORTED_MANIFEST_SCHEMA"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNSUPPORTED_IDENTITY_VERSION = "UNSUPPORTED_IDENTITY_VERSION"
    UNSUPPORTED_ELIGIBILITY_SCHEMA = "UNSUPPORTED_ELIGIBILITY_SCHEMA"
    UNSUPPORTED_GNDCRW_VERSION = "UNSUPPORTED_GNDCRW_VERSION"
    # consumer runtime failure (resource / recursion limits of this reader)
    CONSUMER_RUNTIME_ERROR = "CONSUMER_RUNTIME_ERROR"
    # anything unexpected: a FULLMT defect, never a verdict
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DeliveryStatus(StrEnum):
    """Result delivery to --out (stdout `delivery.status`, present only on failure)."""
    FAILED = "FAILED"


# CLI exit code per outcome (unchanged public contract: 0 / 1 / 2).
EXIT_CODES = {Outcome.VERIFIED: 0, Outcome.REJECTED: 1, Outcome.ERROR: 2}
# A computed verdict whose --out delivery failed: a process failure, same exit as ERROR.
EXIT_DELIVERY_FAILED = EXIT_CODES[Outcome.ERROR]
