"""Reading a JSON document back: one document, one meaning (`canonical-json-1`).

`canonical.py` decides what the product writes; this module decides what a
document read back may mean. Python's `json` reader is lenient exactly where
the canonical format is not, and every leniency lets one byte string mean two
things to two readers — the product and a third party recomputing the package
(ANALYSIS_AND_PACKAGE §7). So the reader refuses what the writer can never
produce:

    text         UTF-8 exactly. Bytes that do not decode are refused; so is a
                 byte-order mark and a string escaping a lone surrogate
                 (`"\\ud800"`), which has no UTF-8 form and so no canonical bytes
    members      a member named twice in one object is refused: which one wins
                 must never matter (CLI_AND_PACKAGING §5), and first-wins and
                 last-wins readers disagree
    numbers      NaN, Infinity and -Infinity are not JSON and are refused; so is
                 a number that is JSON but has no finite value (`1e400`), or an
                 integer the interpreter refuses to convert (thousands of digits)
    nesting      a document nested deeper than the reader can follow is refused,
                 never an error of the reader

Nothing else changes: whatever this reads, `json.loads` reads identically, so a
valid document keeps its meaning, its canonical bytes and its identities. The
reader never writes, never normalises and never guesses.

Every refusal is a `MalformedJSON` (a ValueError). It carries no product error
category on purpose: the caller knows whether the document is evidence, a
declaration or a lock, and raises its own domain error from it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

__all__ = ["MalformedJSON", "StrictInputError", "load_bytes", "load_file", "load_input_bytes",
           "loads"]


class MalformedJSON(ValueError):
    """The text is not one JSON document with one meaning."""


def _refuse_constant(name: str) -> Any:
    raise MalformedJSON(f"{name} is not a JSON number")


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise MalformedJSON(f"the number {text} has no finite value")
    return value


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise MalformedJSON(
                f"member {key!r} is named twice; which one wins must never matter"
            )
        document[key] = value
    return document


def _encodable(value: Any) -> None:
    """Every string (and member name) has a UTF-8 form."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as error:
                raise MalformedJSON(
                    f"the string {item!r} has no UTF-8 form (a lone surrogate)"
                ) from error
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def loads(text: str) -> Any:
    """The one meaning of `text`, or MalformedJSON."""
    try:
        document = json.loads(text, object_pairs_hook=_object,
                              parse_constant=_refuse_constant, parse_float=_finite)
    except json.JSONDecodeError as error:
        raise MalformedJSON(str(error)) from error
    except MalformedJSON:
        raise
    except RecursionError as error:
        # SV-11: nesting the reader cannot follow is a refusal of the text, not a
        # failure of the reader
        raise MalformedJSON("the document is nested too deeply to be read") from error
    except ValueError as error:
        # SV-11: an integer lexeme beyond the interpreter's conversion limit
        raise MalformedJSON(f"a number has no value this reader can state: {error}") from error
    _encodable(document)
    return document


def load_bytes(data: bytes) -> Any:
    """`loads` over bytes that must be UTF-8 (no byte-order mark)."""
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as error:
        raise MalformedJSON(f"not UTF-8 text: {error}") from error
    return loads(text)


def load_file(path: str | Path) -> Any:
    """`load_bytes` over a whole file. OSError (missing, unreadable) is the caller's."""
    return load_bytes(Path(path).read_bytes())


# =====================================================================
# bvl-strict-json-1: the experiment-input profile (IR-09)
# =====================================================================
# The reader above is the product's read-back reader and stays as it is. User
# input for `bvl` is held to a narrower profile (Input Contract §6.2): an
# integer is an exact integer in ±(2^53-1), `-0` has no meaning, the top level
# is an object, depth is bounded, and every refusal carries a closed code.

INTEGER_LIMIT = 2**53 - 1
MAX_INPUT_DEPTH = 64
MAX_NUMBER_LEXEME = 1024
_WHITESPACE = " \t\n\r"


class StrictInputError(MalformedJSON):
    """A `bvl-strict-json-1` refusal with its closed code (§6.2)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _input_int(text: str) -> int:
    if len(text) > MAX_NUMBER_LEXEME:
        raise StrictInputError("RESOURCE_LIMIT", f"a number lexeme of {len(text)} characters")
    if text == "-0":
        raise StrictInputError("NEGATIVE_ZERO", "-0 has no meaning in this profile")
    value = int(text)
    if abs(value) > INTEGER_LIMIT:
        raise StrictInputError("NUMBER_OUT_OF_DOMAIN", f"the integer {text} is outside ±(2^53-1)")
    return value


def _input_float(text: str) -> float:
    if len(text) > MAX_NUMBER_LEXEME:
        raise StrictInputError("RESOURCE_LIMIT", f"a number lexeme of {len(text)} characters")
    value = float(text)
    if not math.isfinite(value):
        raise StrictInputError("NUMBER_OUT_OF_DOMAIN", f"the number {text} has no finite value")
    if value == 0.0 and math.copysign(1.0, value) < 0:
        raise StrictInputError("NEGATIVE_ZERO", f"the number {text} is negative zero")
    return value


def _input_constant(name: str) -> Any:
    raise StrictInputError("NON_FINITE_NUMBER", f"{name} is not a JSON number")


def _input_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise StrictInputError("DUPLICATE_KEY", f"member {key!r} is named twice")
        document[key] = value
    return document


def _depth_within(document: Any) -> None:
    stack = [(document, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (dict, list)):
            if depth > MAX_INPUT_DEPTH:
                raise StrictInputError("RESOURCE_LIMIT", f"nesting deeper than {MAX_INPUT_DEPTH}")
            items = value.values() if isinstance(value, dict) else value
            stack.extend((item, depth + 1) for item in items)


def load_input_bytes(data: bytes) -> dict:
    """The one logical value of experiment-input bytes under `bvl-strict-json-1`."""
    data = bytes(data)
    if data.startswith(b"\xef\xbb\xbf"):
        raise StrictInputError("BOM", "the input starts with a UTF-8 byte-order mark")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StrictInputError("INVALID_UTF8", str(error)) from error
    stripped = text.lstrip(_WHITESPACE)
    if not stripped:
        raise StrictInputError("EMPTY_INPUT", "no JSON value")
    first = stripped[0]
    if first != "{":
        if first in "NI" or stripped.startswith("-I"):
            raise StrictInputError("NON_FINITE_NUMBER", "a non-finite number token")
        if first in '["tfn0123456789' or (first == "-" and stripped[1:2].isdigit()):
            raise StrictInputError("TOP_LEVEL_NOT_OBJECT", "the top level must be an object")
        raise StrictInputError("INVALID_JSON", f"unexpected {first!r} at the top level")
    try:
        document = json.loads(text, object_pairs_hook=_input_object,
                              parse_constant=_input_constant, parse_int=_input_int,
                              parse_float=_input_float)
    except RecursionError as error:
        raise StrictInputError("RESOURCE_LIMIT", "nesting too deep") from error
    except json.JSONDecodeError as error:
        code = "TRAILING_CONTENT" if error.msg == "Extra data" else "INVALID_JSON"
        raise StrictInputError(code, f"{error.msg} at offset {error.pos}") from error
    try:
        _encodable(document)
    except MalformedJSON as error:
        raise StrictInputError("LONE_SURROGATE", str(error)) from error
    _depth_within(document)
    return document
