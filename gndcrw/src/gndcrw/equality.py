"""Catalog equality semantics (TARGET_CATALOG §9, §14; D-10).

JSON_STRUCTURAL
    null      == null only
    boolean   == same boolean only (booleans are not numbers)
    string    == exact code-point sequence, no Unicode normalization
    number    == same finite mathematical value (1 == 1.0, -0 == 0)
    object    == same key set, values recursively equal; key order ignored
    array     == same length, positionally equal; order is semantic
    different JSON types are unequal ("1" != 1, false != 0, [] != {})

SET_EXACT
    equality of the sets of elements; order is non-semantic.

Library-default equality is deliberately not used: in Python `True == 1` and
`False == 0`, which the contract forbids.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

JSON_STRUCTURAL = "JSON_STRUCTURAL"
SET_EXACT = "SET_EXACT"
EQUALITY_KINDS = (JSON_STRUCTURAL, SET_EXACT)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def json_structural_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if _is_number(left) or _is_number(right):
        if not (_is_number(left) and _is_number(right)):
            return False
        # Exact rational comparison: no float rounding between int and float.
        return Fraction(left) == Fraction(right)
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, dict) or isinstance(right, dict):
        if not (isinstance(left, dict) and isinstance(right, dict)):
            return False
        if left.keys() != right.keys():
            return False
        return all(json_structural_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) or isinstance(right, list):
        if not (isinstance(left, list) and isinstance(right, list)):
            return False
        if len(left) != len(right):
            return False
        return all(json_structural_equal(a, b) for a, b in zip(left, right, strict=True))
    raise TypeError(f"not a JSON value: {type(left).__name__} / {type(right).__name__}")


def set_exact_equal(left: list[str], right: list[str]) -> bool:
    return set(left) == set(right)


def values_equal(equality: str, left: Any, right: Any) -> bool:
    if equality == JSON_STRUCTURAL:
        return json_structural_equal(left, right)
    if equality == SET_EXACT:
        return set_exact_equal(left, right)
    raise ValueError(f"unknown equality semantics {equality!r}")
