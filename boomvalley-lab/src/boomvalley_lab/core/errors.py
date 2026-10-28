"""Error categories.

Few on purpose. Each category is something the CLI must tell apart, because
each means something different to the person running an experiment:

    DECLARATION       the experiment as written is invalid          (fix the file)
    CANONICALISATION  a value cannot become a canonical document    (fix the input)
    IDENTITY          an identity is malformed, or used as another  (a bug or tampering)
    VERIFICATION      evidence was checked and a claim is refused   (the dataset is not eligible)
    EXECUTION         the runtime failed                            (operational)
    EVIDENCE          an evidence package is unreadable/inconsistent
    INTERNAL          an invariant of this code broke               (a bug)

Named `ExecutionError`, not `RuntimeError`, so the builtin is never shadowed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from boomvalley_lab.core.strict_json import MalformedJSON, StrictInputError


class Category(StrEnum):
    DECLARATION = "declaration"
    CANONICALISATION = "canonicalisation"
    IDENTITY = "identity"
    VERIFICATION = "verification"
    EXECUTION = "execution"
    EVIDENCE = "evidence"
    INTERNAL = "internal"


class BoomvalleyError(Exception):
    """Base of every product error. `category` is what the CLI dispatches on."""

    category: Category = Category.INTERNAL

    def __init__(self, message: str, *, problems: tuple[str, ...] = (),
                 code: str | None = None) -> None:
        super().__init__(message)
        self.problems = tuple(problems)
        #: a closed code where the raise site states one (#126); else the boundary
        #: derives it (`error_code`)
        self.code = code


class DeclarationError(BoomvalleyError):
    category = Category.DECLARATION


class CanonicalisationError(BoomvalleyError):
    category = Category.CANONICALISATION


class IdentityError(BoomvalleyError):
    category = Category.IDENTITY


class VerificationRefusal(BoomvalleyError):
    """A declared claim was checked and does not hold (or could not be checked)."""

    category = Category.VERIFICATION


class ExecutionError(BoomvalleyError):
    category = Category.EXECUTION


class EvidenceError(BoomvalleyError):
    category = Category.EVIDENCE


class InternalError(BoomvalleyError):
    category = Category.INTERNAL


#: Distinct process exit codes, so scripts can tell refusal from failure.
EXIT_CODES: dict[Category, int] = {
    Category.DECLARATION: 2,
    Category.CANONICALISATION: 2,
    Category.IDENTITY: 3,
    Category.VERIFICATION: 4,
    Category.EXECUTION: 5,
    Category.EVIDENCE: 6,
    Category.INTERNAL: 70,
}

#: #81: `bvl check` / `bvl run` whose execution gate did not clear. Not an error: the
#: result is printed on stdout (a normal decision with its reasons), no run executes.
EXIT_GATE_NOT_CLEARED = 8

#: T5-002: `bvl run` / `bvl resume` that stopped WAITING for a human actor's answer. Not
#: an error and not a completion: the request is delivered and the run continues on resume.
EXIT_WAITING = 9


# ---------------------------------------------------------------------
# #126 the external error-code boundary: every error a CLI reports carries one
# stable code, read from the exception's type and its closed code, never from its
# wording or the locale. Domain raises stay category + free text; the boundary
# classifies them (the category's code, or the I/O / parse cause they wrap).
# ---------------------------------------------------------------------

INTERNAL_ERROR = "INTERNAL_ERROR"
#: a category-only error: the code of its category
CATEGORY_CODES: dict[Category, str] = {
    Category.DECLARATION: "DECLARATION_INVALID",
    Category.CANONICALISATION: "CANONICALISATION_FAILED",
    Category.IDENTITY: "IDENTITY_INVALID",
    Category.VERIFICATION: "VERIFICATION_REFUSED",
    Category.EXECUTION: "EXECUTION_FAILED",
    Category.EVIDENCE: "EVIDENCE_INVALID",
    Category.INTERNAL: INTERNAL_ERROR,
}
#: a file / path / permission / I/O failure (the error itself or the cause it wraps)
PATH_NOT_FOUND = "PATH_NOT_FOUND"
PERMISSION_DENIED = "PERMISSION_DENIED"
IO_ERROR = "IO_ERROR"
#: a document that does not parse (`bvl-strict-json-1` codes where the parser has one)
INVALID_JSON = "INVALID_JSON"
INVALID_UTF8 = "INVALID_UTF8"
#: a document of a schema / version this build does not read
UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
BOUNDARY_CODES = frozenset({*CATEGORY_CODES.values(), PATH_NOT_FOUND, PERMISSION_DENIED,
                            IO_ERROR, INVALID_JSON, INVALID_UTF8, UNSUPPORTED_SCHEMA})


def _cause_code(error: BaseException) -> str | None:
    """The code of an I/O or parse failure, from its type (never its text)."""
    if isinstance(error, StrictInputError):
        return error.code
    if isinstance(error, FileNotFoundError):
        return PATH_NOT_FOUND
    if isinstance(error, PermissionError):
        return PERMISSION_DENIED
    if isinstance(error, OSError):
        return IO_ERROR
    if isinstance(error, UnicodeDecodeError):
        return INVALID_UTF8
    if isinstance(error, (json.JSONDecodeError, MalformedJSON)):
        return INVALID_JSON
    return None


def error_code(error: BaseException) -> str:
    """The stable external code of `error`: its own closed code, else the I/O / parse
    cause it wraps (`raise ... from`), else its category's; anything else is a bug
    (INTERNAL_ERROR)."""
    if isinstance(error, BoomvalleyError) and error.code:
        return error.code
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        found = _cause_code(cause)
        if found is not None:
            return found
        cause = cause.__cause__
    if isinstance(error, BoomvalleyError):
        return CATEGORY_CODES[error.category]
    return INTERNAL_ERROR


# ---------------------------------------------------------------------
# Experiment-input refusals (Input Contract §20): one class, one closed code.
# The refusal class maps onto the categories above, so exit codes do not change.
# ---------------------------------------------------------------------

CLASS_CATEGORY: dict[str, Category] = {
    "SERIALIZATION_ERROR": Category.DECLARATION,
    "SCHEMA_ERROR": Category.DECLARATION,
    "REFERENCE_ERROR": Category.DECLARATION,
    "DECLARATION_ERROR": Category.DECLARATION,
    "COMBINATION_ERROR": Category.DECLARATION,
    "OUT_OF_MVP": Category.DECLARATION,
    "USAGE_ERROR": Category.DECLARATION,
    "IDENTITY_ERROR": Category.IDENTITY,
    "INPUT_DRIFT": Category.IDENTITY,
    "GNDCRW_INPUT_ERROR": Category.VERIFICATION,
    "GNDCRW_REFUSAL": Category.VERIFICATION,
    # #153: the schedule preflight did not return an explicit exact match
    "SCHEDULE_PREFLIGHT_REFUSAL": Category.VERIFICATION,
    # #175: the experiment-input preflight did not return an explicit exact match
    "EXPERIMENT_INPUT_PREFLIGHT_REFUSAL": Category.VERIFICATION,
    # #176: the server would answer with another identity than the pinned one
    "EXECUTION_IDENTITY_REFUSAL": Category.VERIFICATION,
    "CAPABILITY_ERROR": Category.EXECUTION,
    "GNDCRW_TOOL_FAILURE": Category.EXECUTION,
}


class InputRefusal(BoomvalleyError):
    def __init__(self, klass: str, code: str, detail: str, *, layer: str,
                 path: str = "", evidence: Mapping[str, Any] | None = None) -> None:
        if klass not in CLASS_CATEGORY:
            raise ValueError(f"unknown refusal class {klass!r}")
        super().__init__(f"{klass} {code}: {detail}")
        self.category = CLASS_CATEGORY[klass]
        self.klass = klass
        self.code = code
        self.detail = detail
        self.layer = layer
        self.path = path
        self.evidence = dict(evidence) if evidence else None

    def document(self) -> dict:
        """The §20.5 error document (plus `evidence` when there is some)."""
        return {"class": self.klass, "code": self.code, "layer": self.layer,
                "path": self.path, "detail": self.detail, "evidence": self.evidence}
