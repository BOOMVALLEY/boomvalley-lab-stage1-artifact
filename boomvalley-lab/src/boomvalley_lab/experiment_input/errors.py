"""Input refusals (Input Contract §20). The type lives in `core.errors` so the
journal-level legacy guard can raise it; this module is its home for the
experiment-input path."""

from __future__ import annotations

from boomvalley_lab.core.errors import CLASS_CATEGORY, InputRefusal

__all__ = ["CLASS_CATEGORY", "InputRefusal", "drift"]


def drift(code: str, detail: str, *, path: str = "", layer: str = "IL") -> InputRefusal:
    return InputRefusal("INPUT_DRIFT", code, detail, layer=layer, path=path)
