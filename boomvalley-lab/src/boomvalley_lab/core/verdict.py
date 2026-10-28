"""The three-state verification verdict.

    VERIFIED   a claim was declared (or evidence recorded) and it holds
    VIOLATED   a claim was declared and it does not hold — OR it cannot be
               checked (evidence missing, precondition failed): fail closed
    NO_CLAIM   nothing was declared or recorded, so nothing is asserted

There is no fourth state. "Declared but we could not look" is VIOLATED, never
a softer "unknown": a claim nobody could check is not a claim the evidence
supports. NO_CLAIM is not a pass for a declared claim and is never read as
"verified".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from boomvalley_lab.core.errors import InternalError


class Verdict(StrEnum):
    VERIFIED = "VERIFIED"
    VIOLATED = "VIOLATED"
    NO_CLAIM = "NO_CLAIM"


@dataclass(frozen=True)
class Finding:
    """One step's verdict and the reasons a reader needs to audit it."""

    step: str
    verdict: Verdict
    reasons: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.verdict is Verdict.VIOLATED and not self.reasons:
            raise InternalError(f"{self.step}: a violation must say why")


def decide(*, claimed: bool, checkable: bool, holds: bool | None) -> Verdict:
    """The rule, once.

    `claimed`   a claim was declared, or evidence asserting one was recorded
    `checkable` the evidence needed to check it is present and usable
    `holds`     the result of the check (ignored unless claimed and checkable)
    """
    if not claimed:
        return Verdict.NO_CLAIM
    if not checkable:
        return Verdict.VIOLATED
    if holds is None:
        raise InternalError("a checkable claim must be decided true or false")
    return Verdict.VERIFIED if holds else Verdict.VIOLATED


def all_hold(verdicts: Iterable[Verdict]) -> bool:
    """Eligibility-style aggregation: nothing VIOLATED. NO_CLAIM does not fail
    and does not count as support; the report keeps each verdict separately."""
    return all(verdict is not Verdict.VIOLATED for verdict in verdicts)
