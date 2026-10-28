"""Provider SPI (CLI_SPEC §3, TARGET_CATALOG §16, D-12).

A provider is an acquisition path, not a second verifier. It materializes the
same four documents materialized mode reads from files; the caller supplies
the declaration. Anything a provider returns goes through exactly the same
contract validation as a file would, and a provider has no way to hand the
core a verdict.

Every document is reduced to plain JSON before the core sees it (SURFACE §4,
§24): exact JSON value types only (subclasses, tuples, sets and other language
objects are refused), then serialized and re-parsed by the same strict parser
materialized mode uses, so the D-26.2 / D-27.2 input limits apply identically.
A value that carries its own `__eq__` can therefore never reach the verdict.

Provider failures are operational (exit 4), never experiment findings.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Protocol

from gndcrw.errors import ContractError, ProviderError
from gndcrw.jsonio import MAX_DEPTH, MAX_INT_DIGITS, loads
from gndcrw.load import Documents

_INT_LIMIT = 10**MAX_INT_DIGITS
_SCALARS = (str, int, float, bool, type(None))


def _check_plain(document: Any, label: str) -> None:
    """Exact JSON value types only; enforce the depth / digit limits before serializing."""
    stack: list[tuple[Any, str, int]] = [(document, ":", 1)]
    while stack:
        value, path, depth = stack.pop()
        kind = type(value)
        if kind in (dict, list):
            if depth > MAX_DEPTH:
                raise ContractError(f"nesting deeper than {MAX_DEPTH} levels", pointer=label)
            if kind is dict:
                for key, item in value.items():
                    if type(key) is not str:
                        raise ProviderError(f"{label}{path}: non-string or non-plain key "
                                            f"of type {type(key).__name__}")
                    stack.append((item, f"{path}/{key}", depth + 1))
            else:
                for index, item in enumerate(value):
                    stack.append((item, f"{path}/{index}", depth + 1))
        elif kind not in _SCALARS:
            raise ProviderError(f"{label}{path}: {kind.__name__} is not a plain JSON value "
                                "(SURFACE s4)")
        elif kind is int and abs(value) >= _INT_LIMIT:
            raise ContractError(f"integer literal longer than {MAX_INT_DIGITS} digits (D-27.2)",
                                pointer=label)


def to_plain_json(document: Any, *, label: str) -> Any:
    """The plain-JSON object materialized mode would have parsed for `document`."""
    _check_plain(document, label)
    # ensure_ascii keeps unpaired surrogates as escapes so the strict parser
    # rejects them exactly as it does for files; NaN/Infinity are written as
    # bare constants and rejected by the same parser.
    text = json.dumps(document, ensure_ascii=True, allow_nan=True)
    return loads(text, label=label)


class Provider(Protocol):
    def target_catalog(self, profile_id: str) -> Any:
        """The TargetCatalog document for `profile_id`."""

    def describe(self, request: Any, catalog: Any) -> Any:
        """An ExperimentSurface document assembled for `request`."""

    def compare_context(self, base_request: Any, candidate_request: Any, catalog: Any) -> Any:
        """The SurfacePairContext document for the two requests."""


def acquire(provider: Provider, declaration: Any, *, profile_id: str, base_request: Any,
            candidate_request: Any) -> Documents:
    """Materialize the five logical inputs through `provider`.

    Each document is snapshotted the moment it is obtained, so nothing a
    provider keeps, reuses or mutates afterwards can reach the check
    (TARGET_CATALOG §16, SURFACE ES-I07). Every provider call gets its own plain
    copy of the catalog snapshot, never an object the check will use.
    """
    declaration = to_plain_json(declaration, label="declaration")
    catalog = to_plain_json(_call(provider.target_catalog, profile_id), label="catalog")
    base = to_plain_json(_call(provider.describe, base_request, copy.deepcopy(catalog)),
                         label="base")
    candidate = to_plain_json(_call(provider.describe, candidate_request, copy.deepcopy(catalog)),
                              label="candidate")
    pair = to_plain_json(_call(provider.compare_context, base_request, candidate_request,
                               copy.deepcopy(catalog)), label="pair")
    return Documents(declaration=declaration, catalog=catalog, base=base, candidate=candidate,
                     pair=pair)


def _call(method: Any, *args: Any) -> Any:
    try:
        return method(*args)
    except ProviderError:
        raise
    except Exception as exc:  # any provider failure is operational, not a finding
        raise ProviderError(f"provider acquisition failed: {type(exc).__name__}: {exc}") from exc
