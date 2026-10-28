"""Structural validation helpers.

Every failure raises ContractError with a JSON-pointer-like location, so a
contract error always says where the input broke. These helpers only decide
structure; semantic outcomes are the core's job.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from gndcrw.errors import ContractError
from gndcrw.jsonio import is_digest


def obj(value: Any, ptr: str, required: Iterable[str], optional: Iterable[str] = ()) -> dict:
    """An object with exactly the required keys plus any of the optional keys."""
    if not isinstance(value, dict):
        raise ContractError("expected an object", pointer=ptr)
    required = tuple(required)
    allowed = set(required) | set(optional)
    for key in required:
        if key not in value:
            raise ContractError(f"missing required field {key!r}", pointer=ptr)
    for key in value:
        if key not in allowed:
            raise ContractError(f"unknown field {key!r}", pointer=ptr)
    return value


def string(value: Any, ptr: str, *, nullable: bool = False) -> str | None:
    """A non-empty string (or null when `nullable`)."""
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ContractError("expected a string" + (" or null" if nullable else ""), pointer=ptr)
    if value == "":
        raise ContractError("empty string is not permitted", pointer=ptr)
    return value


def any_string(value: Any, ptr: str) -> str:
    """A string that may be empty (free text)."""
    if not isinstance(value, str):
        raise ContractError("expected a string", pointer=ptr)
    return value


def boolean(value: Any, ptr: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError("expected a boolean", pointer=ptr)
    return value


def integer(value: Any, ptr: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError("expected an integer", pointer=ptr)
    if minimum is not None and value < minimum:
        raise ContractError(f"expected an integer >= {minimum}", pointer=ptr)
    return value


def enum(value: Any, ptr: str, allowed: Iterable[str]) -> str:
    allowed = tuple(allowed)
    if not isinstance(value, str) or value not in allowed:
        raise ContractError(f"expected one of {', '.join(allowed)}; got {value!r}", pointer=ptr)
    return value


def array(value: Any, ptr: str) -> list:
    if not isinstance(value, list):
        raise ContractError("expected an array", pointer=ptr)
    return value


def string_list(value: Any, ptr: str, *, unique: bool = True, nonempty: bool = False) -> list:
    items = array(value, ptr)
    for index, item in enumerate(items):
        string(item, f"{ptr}/{index}")
    if unique and len(set(items)) != len(items):
        raise ContractError("duplicate entries", pointer=ptr)
    if nonempty and not items:
        raise ContractError("expected a non-empty array", pointer=ptr)
    return items


def digest(value: Any, ptr: str) -> str:
    if not is_digest(value):
        raise ContractError("expected sha256:<64 lowercase hex>", pointer=ptr)
    return value


def const(value: Any, ptr: str, expected: str) -> str:
    if value != expected:
        raise ContractError(f"unsupported version {value!r}; expected {expected!r}", pointer=ptr)
    return value


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
RESERVED_PREMISE_IDS = ("pair.entity_comparability",)


def identifier(value: Any, ptr: str) -> str:
    """rule_id / premise_id / context_id grammar (D-26.3)."""
    string(value, ptr)
    if not IDENTIFIER_RE.match(value):
        raise ContractError(f"identifier {value!r} must match [A-Za-z0-9._-]+ (D-26.3)",
                            pointer=ptr)
    return value


def premise_identifier(value: Any, ptr: str) -> str:
    identifier(value, ptr)
    if value in RESERVED_PREMISE_IDS:
        raise ContractError(f"premise_id {value!r} is reserved (D-26.3)", pointer=ptr)
    return value


AUTHORITY_KINDS = ("RESEARCHER", "PROVIDER", "CONTRACT")


def authority(value: Any, ptr: str) -> dict:
    obj(value, ptr, ("kind", "id"))
    enum(value["kind"], f"{ptr}/kind", AUTHORITY_KINDS)
    string(value["id"], f"{ptr}/id")
    return value
