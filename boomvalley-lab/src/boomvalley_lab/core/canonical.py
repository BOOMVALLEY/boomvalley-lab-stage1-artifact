"""The one canonical-document serializer (`canonical-json-1`).

Every identity in the product is a digest of bytes produced here, so this
module is the single place where "two equal documents give identical bytes" is
decided. Policy:

    types        dict (str keys) · list/tuple · str · int · finite float · bool
                 · None is NOT a value — see omission
    mappings     keys sorted by code point; no duplicate keys possible
    sequences    order preserved (order is meaning unless declared otherwise)
    unordered    a semantically unordered collection is passed through
                 `unordered(...)`, which sorts it by each element's canonical
                 bytes — callers say which collections are sets, the
                 serializer never guesses
    omission     ONE rule: a mapping entry whose value is None (or ABSENT) is
                 omitted. An absent optional section therefore has exactly one
                 representation - it is not there. `null` never appears in a
                 canonical document; None inside a sequence is refused.
    text         UTF-8, non-ASCII kept as-is (ensure_ascii off), no Unicode
                 normalisation: strings are identities as given; a string with
                 no UTF-8 form (a lone surrogate) has no canonical bytes
    numbers      int as-is; floats must be finite (NaN/inf refused); -0.0 is
                 refused so zero has one form; bool is not an int
    refusals     every value without a canonical form is a
                 `CanonicalisationError` - also one nested too deeply, or an
                 integer too long, for the serializer to write
    layout       no insignificant whitespace (",", ":")

Reviewed from the research instrument's `canonical_json` (REUSE ALGORITHM WITH
REVIEW): same key order, separators and encoding; this version additionally
refuses NaN/inf, non-string keys, sets and None, which the original emitted or
coerced silently. Clean-build bytes are therefore not guaranteed to equal the
mock's, and are never pinned to them.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from boomvalley_lab.core.errors import CanonicalisationError
from boomvalley_lab.core.versions import CANONICAL_FORMAT

__all__ = ["ABSENT", "CANONICAL_FORMAT", "canonical_bytes", "canonical_json", "unordered"]


class _Absent:
    """The explicit marker for an absent optional section. Omitted like None."""

    _instance: _Absent | None = None

    def __new__(cls) -> _Absent:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT = _Absent()


def _normalise(value: Any, path: str) -> Any:
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalisationError(f"{path}: non-finite number {value!r}")
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise CanonicalisationError(f"{path}: -0.0 has no canonical form; use 0.0")
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalisationError(f"{path}: non-string key {key!r}")
            if item is None or item is ABSENT:
                continue  # the one omission rule
            out[key] = _normalise(item, f"{path}.{key}")
        return out
    if isinstance(value, (set, frozenset)):
        raise CanonicalisationError(
            f"{path}: a set has no order; pass it through unordered(...)"
        )
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = []
        for index, item in enumerate(value):
            if item is None or item is ABSENT:
                raise CanonicalisationError(
                    f"{path}[{index}]: absent values are omitted from mappings, "
                    "never placed in sequences"
                )
            items.append(_normalise(item, f"{path}[{index}]"))
        return items
    raise CanonicalisationError(f"{path}: {type(value).__name__} is not a document value")


class _Unserialisable(CanonicalisationError, ValueError):
    """A value the serializer itself cannot write (SV-11).

    A `CanonicalisationError` like every other refusal here, and still the
    `ValueError` the interpreter raised before it was one, so a caller written
    against either keeps refusing.
    """


def _dumps(document: Any, *, ensure_ascii: bool) -> str:
    if document is None or document is ABSENT:
        raise CanonicalisationError("$: an absent document has no canonical form")
    try:
        return json.dumps(
            _normalise(document, "$"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=ensure_ascii,
            allow_nan=False,
        )
    except RecursionError as error:
        raise _Unserialisable("$: nested too deeply to have a canonical form") from error
    except CanonicalisationError:
        raise
    except ValueError as error:  # an integer beyond the interpreter's conversion limit
        raise _Unserialisable(f"$: a number has no canonical form: {error}") from error


def canonical_json(document: Any) -> str:
    """The canonical text of `document` under `canonical-json-1`."""
    return _dumps(document, ensure_ascii=False)


def wire_json(document: Any) -> str:
    """The same document as `canonical_json`, every non-ASCII character escaped.

    For machine-readable output on a stream (stdout/stderr), never for digests:
    the text is pure ASCII, so it survives any console code page, redirect or
    pipe encoding unchanged and `json.loads` gives back exactly the document
    `canonical_json` describes (a supplementary-plane character is written as
    its standard UTF-16 surrogate-pair escape, e.g. U+1F600 -> "\\ud83d\\ude00").
    """
    return _dumps(document, ensure_ascii=True)


def canonical_bytes(document: Any) -> bytes:
    """The digest input: canonical text encoded as UTF-8."""
    text = canonical_json(document)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as error:
        # SV-11: a lone surrogate has no UTF-8 form, so no canonical bytes
        raise _Unserialisable(
            f"$: a string has no UTF-8 form (a lone surrogate): {error.reason}"
        ) from error


def unordered(items: Iterable[Any], *, unique: bool = True) -> list[Any]:
    """A semantically unordered collection in its one canonical order.

    Sorted by each element's canonical bytes, so the order is defined for any
    document value and never depends on how the caller built the collection.
    With `unique`, repeated elements are refused rather than silently merged:
    a declaration that lists a thing twice has said something odd.
    """
    keyed = [(canonical_bytes(item), item) for item in items]
    keyed.sort(key=lambda pair: pair[0])
    if unique:
        for (left, _), (right, _) in zip(keyed, keyed[1:], strict=False):
            if left == right:
                raise CanonicalisationError(
                    f"an unordered collection lists {left.decode('utf-8')} twice"
                )
    return [item for _, item in keyed]
