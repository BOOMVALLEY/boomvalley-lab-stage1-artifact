"""Name and level rules shared by every declaration section.

Names (factors, levels, views, mechanisms, stages, roles) are plain tokens so
that a cell key like `arm=a/case=c1` is unambiguous: `=` `/` `#` never occur
inside a name. `replicate` is reserved: it is the coordinate every execution
record carries besides its factors, and a projection may use it.
"""

from __future__ import annotations

import re

from boomvalley_lab.core.errors import DeclarationError

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

#: The coordinate every execution record has in addition to its factors.
REPLICATE = "replicate"

RESERVED_FACTOR_NAMES = frozenset({REPLICATE})


def check_name(value: object, what: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise DeclarationError(
            f"{what} must be a token of letters, digits, '_', '.', '-' "
            f"(not starting with a symbol): {value!r}"
        )
    return value
