"""Strict JSON parsing, canonical serialization and digests.

Parse boundary (SURFACE §4):
    - duplicate object keys are rejected;
    - NaN / Infinity / -Infinity are rejected;
    - the document must be JSON-compatible values only.

Canonical form (SURFACE §22, RESULT §5):
    UTF-8, object keys sorted lexicographically, no insignificant whitespace,
    arrays in declared order, finite numbers only. `null` is a value and is
    kept - GNDCRW contracts give `null` meaning (e.g. `equivalence: null`).
    Set-like lists are normalized by the contract that owns them, never here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from gndcrw.errors import ContractError

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _reject_constant(name: str) -> Any:
    raise ContractError(f"non-finite number {name} is not permitted")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ContractError(f"duplicate object key {key!r}")
        out[key] = value
    return out


# Implementation limit (D-26.2): no v0.1 contract object needs more; deeper input
# is refused at the boundary instead of exhausting the stack later.
MAX_DEPTH = 64


def _validate_parsed(document: Any, label: str) -> None:
    """Depth limit and UTF-8 encodability of every string (iterative, no recursion)."""
    stack: list[tuple[Any, int]] = [(document, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (dict, list)):
            if depth > MAX_DEPTH:
                raise ContractError(f"nesting deeper than {MAX_DEPTH} levels", pointer=label)
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for key, item in items:
                if isinstance(key, str):
                    _encodable(key, label)
                stack.append((item, depth + 1))
        elif isinstance(value, str):
            _encodable(value, label)


def _encodable(text: str, label: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ContractError("string contains an unpaired surrogate escape", pointer=label) from None


MAX_INT_DIGITS = 4300  # D-27.2: fixed, not the platform's parser limit


def _parse_int(lexeme: str) -> int:
    if len(lexeme.lstrip("-")) > MAX_INT_DIGITS:
        raise ContractError(f"integer literal longer than {MAX_INT_DIGITS} digits (D-27.2)")
    return int(lexeme)


def _parse_float(lexeme: str) -> float:
    value = float(lexeme)
    if not math.isfinite(value):
        raise ContractError(f"number {lexeme[:40]} overflows binary64 (D-27.2)")
    return value


def loads(text: str, *, label: str = "$") -> Any:
    """Parse JSON text strictly. Every failure is a ContractError."""
    try:
        document = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
            parse_int=_parse_int,
            parse_float=_parse_float,
        )
    except ContractError as exc:
        raise ContractError(exc.message, pointer=label) from None
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        # ValueError covers Python's integer-length limit (> 4300 digits).
        raise ContractError(f"malformed JSON: {exc}", pointer=label) from None
    _validate_parsed(document, label)
    return document


def load_bytes(data: bytes, *, label: str = "$") -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"input is not UTF-8: {exc}", pointer=label) from None
    if text.startswith("﻿"):
        raise ContractError("input starts with a byte-order mark", pointer=label)
    return loads(text, label=label)


def _check(value: Any, path: str) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("non-finite number", pointer=path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"non-string key {key!r}", pointer=path)
            _check(item, f"{path}/{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check(item, f"{path}/{index}")
        return
    raise ContractError(f"{type(value).__name__} is not a JSON value", pointer=path)


def canonical_json(document: Any) -> str:
    _check(document, "$")
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(document: Any) -> bytes:
    return canonical_json(document).encode("utf-8")


def digest(document: Any) -> str:
    """`sha256:<64 lowercase hex>` over the canonical bytes of `document`."""
    return "sha256:" + hashlib.sha256(canonical_bytes(document)).hexdigest()


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_RE.match(value) is not None
