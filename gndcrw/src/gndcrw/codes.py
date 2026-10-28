"""Central code registry: STATUS / REASON / ERROR are kept apart.

- STATUS  finding statuses and workflow outcomes: `core.vocabulary` (STATUSES, OUTCOMES).
- REASON  normal decision reasons carried by a finding: `core.vocabulary.REASONS`.
- ERROR   contract violation / parse / system failure: this module, the closed
          manifest-mode table of CLI_SPEC_V0_2 §5 with its exit codes, plus the
          few legacy-mode (CLI_SPEC v0.1) codes that table has no member for.

Every identifier is a fixed English token. Human-readable wording lives in
`gndcrw.i18n`; nothing here depends on the locale. This module imports nothing
from the package so `errors` can depend on it.
"""

from __future__ import annotations

from enum import StrEnum


class Error(StrEnum):
    MIXED_MODE = "MIXED_MODE"
    MANIFEST_ARGUMENT_COUNT = "MANIFEST_ARGUMENT_COUNT"
    STDIN_NOT_SUPPORTED = "STDIN_NOT_SUPPORTED"
    OPTION_NOT_SUPPORTED = "OPTION_NOT_SUPPORTED"
    OPTION_REPEATED = "OPTION_REPEATED"
    OUTPUT_IS_INPUT = "OUTPUT_IS_INPUT"
    MANIFEST_YAML_NOT_SUPPORTED = "MANIFEST_YAML_NOT_SUPPORTED"
    MANIFEST_NOT_JSON = "MANIFEST_NOT_JSON"
    MANIFEST_NOT_FOUND = "MANIFEST_NOT_FOUND"
    MANIFEST_LINK = "MANIFEST_LINK"
    MANIFEST_NOT_REGULAR = "MANIFEST_NOT_REGULAR"
    MANIFEST_HARDLINK = "MANIFEST_HARDLINK"
    MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"
    MANIFEST_BOM = "MANIFEST_BOM"
    MANIFEST_INVALID_UTF8 = "MANIFEST_INVALID_UTF8"
    MANIFEST_INVALID_JSON = "MANIFEST_INVALID_JSON"
    MANIFEST_DUPLICATE_KEY = "MANIFEST_DUPLICATE_KEY"
    MANIFEST_NOT_OBJECT = "MANIFEST_NOT_OBJECT"
    MANIFEST_VERSION_MISSING = "MANIFEST_VERSION_MISSING"
    MANIFEST_VERSION_UNSUPPORTED = "MANIFEST_VERSION_UNSUPPORTED"
    MANIFEST_UNKNOWN_FIELD = "MANIFEST_UNKNOWN_FIELD"
    MANIFEST_FIELD_INVALID = "MANIFEST_FIELD_INVALID"
    MANIFEST_PATH_INVALID = "MANIFEST_PATH_INVALID"
    MANIFEST_DUPLICATE_PATH = "MANIFEST_DUPLICATE_PATH"
    REF_LINK = "REF_LINK"
    REF_MISSING = "REF_MISSING"
    REF_NOT_REGULAR = "REF_NOT_REGULAR"
    REF_CASE_ALIAS = "REF_CASE_ALIAS"
    REF_HARDLINK = "REF_HARDLINK"
    REF_ALIAS = "REF_ALIAS"
    REF_SIZE_MISMATCH = "REF_SIZE_MISMATCH"
    REF_DIGEST_MISMATCH = "REF_DIGEST_MISMATCH"
    SUBJECT_CONTRACT_INVALID = "SUBJECT_CONTRACT_INVALID"
    EXTERNAL_SUBJECT_NOT_IN_SURFACE = "EXTERNAL_SUBJECT_NOT_IN_SURFACE"
    PLATFORM_NO_SAFE_RESOLUTION = "PLATFORM_NO_SAFE_RESOLUTION"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    OUTPUT_WRITE_FAILED = "OUTPUT_WRITE_FAILED"


# Exit code per error (CLI_SPEC_V0_2 §4-§5). No code maps to 0, 10 or 11.
ERROR_EXIT: dict[Error, int] = {
    **dict.fromkeys((Error.MIXED_MODE, Error.MANIFEST_ARGUMENT_COUNT, Error.STDIN_NOT_SUPPORTED,
                     Error.OPTION_NOT_SUPPORTED, Error.OPTION_REPEATED), 2),
    **dict.fromkeys((Error.MANIFEST_YAML_NOT_SUPPORTED, Error.MANIFEST_NOT_JSON,
                     Error.MANIFEST_NOT_FOUND, Error.MANIFEST_LINK, Error.MANIFEST_NOT_REGULAR,
                     Error.MANIFEST_HARDLINK, Error.MANIFEST_TOO_LARGE, Error.MANIFEST_BOM,
                     Error.MANIFEST_INVALID_UTF8, Error.MANIFEST_INVALID_JSON,
                     Error.MANIFEST_DUPLICATE_KEY, Error.MANIFEST_NOT_OBJECT,
                     Error.MANIFEST_VERSION_MISSING, Error.MANIFEST_VERSION_UNSUPPORTED,
                     Error.MANIFEST_UNKNOWN_FIELD, Error.MANIFEST_FIELD_INVALID,
                     Error.MANIFEST_PATH_INVALID, Error.MANIFEST_DUPLICATE_PATH,
                     Error.REF_LINK, Error.REF_MISSING, Error.REF_NOT_REGULAR,
                     Error.REF_CASE_ALIAS, Error.REF_HARDLINK, Error.REF_ALIAS,
                     Error.REF_SIZE_MISMATCH, Error.REF_DIGEST_MISMATCH,
                     Error.SUBJECT_CONTRACT_INVALID, Error.EXTERNAL_SUBJECT_NOT_IN_SURFACE), 3),
    **dict.fromkeys((Error.PLATFORM_NO_SAFE_RESOLUTION, Error.INTERNAL_ERROR), 5),
    **dict.fromkeys((Error.OUTPUT_IS_INPUT, Error.OUTPUT_EXISTS, Error.OUTPUT_WRITE_FAILED), 6),
}


class LegacyError(StrEnum):
    """Legacy-mode (CLI_SPEC v0.1) failures with no CLI_SPEC_V0_2 §5 equivalent.

    Kept apart from `Error` so the closed manifest-mode table stays closed.
    Where the meaning is the same, legacy mode reuses the `Error` member
    (OUTPUT_IS_INPUT, OUTPUT_EXISTS, OUTPUT_WRITE_FAILED, INTERNAL_ERROR).
    """

    USAGE_INVALID = "USAGE_INVALID"
    INPUT_NOT_FOUND = "INPUT_NOT_FOUND"
    INPUT_UNREADABLE = "INPUT_UNREADABLE"
    INPUT_INVALID = "INPUT_INVALID"
    PROVIDER_FAILED = "PROVIDER_FAILED"


# Exit code per legacy-mode error (CLI_SPEC §11).
LEGACY_ERROR_EXIT: dict[str, int] = {
    LegacyError.USAGE_INVALID: 2,
    **dict.fromkeys((LegacyError.INPUT_NOT_FOUND, LegacyError.INPUT_UNREADABLE,
                     LegacyError.INPUT_INVALID), 3),
    LegacyError.PROVIDER_FAILED: 4,
    Error.INTERNAL_ERROR: 5,
    **dict.fromkeys((Error.OUTPUT_IS_INPUT, Error.OUTPUT_EXISTS, Error.OUTPUT_WRITE_FAILED), 6),
}
