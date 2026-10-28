"""How a declaration document is read — OA-03, in one place.

A persisted schema says what each of its fields may be. Python says what is
truthy. Those are different statements, and when the second one is used to
decide the first, representations the grammar keeps apart get quietly merged:

    document.get("failure_policy") or {}

`[]` is falsy, so a list written where a mapping belongs became an empty
mapping and was accepted as "this section is absent". Four distinct
representations — missing, `null`, `{}`, `[]` — arrived at the same meaning,
and none of that was the grammar's decision.

`section` makes the one convention the declaration actually has explicit, and
leaves every other question to the field:

    missing   the section was not written
    null      the same thing, by the declaration's own convention, which is
              the same for all of its sections
    anything  handed to that section's grammar, which says whether it is
    else      valid — including saying that it is not

So an empty mapping where a mapping belongs is a valid empty mapping, and an
empty list in the same place is an error rather than a synonym for absence.
Whether an empty value is meaningful is the field's business; whether it looks
false to the interpreter is nobody's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def section(document: Mapping, name: str, absent: Any) -> Any:
    """One declaration section as written, with `absent` only for absence."""
    value = document.get(name)
    return absent if value is None else value
