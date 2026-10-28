"""The one projection: cell coordinates -> the tuple of selected factors.

Analysis units (frozen R23/R31), assignment units (R33/R35) and relation
targets (R29/R32/R44) all group a design's cells by the levels of some of its
factors. They differ in meaning, not in mechanism, so the mechanism exists
once here and each declaration section says what its groups mean.

Semantics
    factors      a non-empty set: order is not meaning; canonical = sorted
    key          ((factor, level), ...) in canonical factor order
    group        unit key -> member ids, both in deterministic order
    missing      a record lacking a projected factor is a declaration error,
                 never a silent group of its own
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from boomvalley_lab.core.errors import DeclarationError

UnitKey = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Projection:
    """Projection onto a canonical set of factors. Build with `onto`."""

    factors: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.factors:
            raise DeclarationError("a projection must select at least one factor")
        if len(set(self.factors)) != len(self.factors):
            raise DeclarationError(f"a projection names a factor twice: {list(self.factors)}")
        if list(self.factors) != sorted(self.factors):
            raise DeclarationError("construct projections with Projection.onto(...)")

    @classmethod
    def onto(cls, factors: Iterable[str]) -> Projection:
        factors = tuple(factors)
        for factor in factors:
            if not isinstance(factor, str) or not factor.strip():
                raise DeclarationError(
                    f"a projection factor must be a non-empty string: {factor!r}"
                )
        if len(set(factors)) != len(factors):
            raise DeclarationError(f"a projection names a factor twice: {list(factors)}")
        return cls(tuple(sorted(factors)))

    def key(self, coordinates: Mapping[str, str]) -> UnitKey:
        missing = [factor for factor in self.factors if factor not in coordinates]
        if missing:
            raise DeclarationError(f"coordinates carry no level for {missing}")
        return tuple((factor, coordinates[factor]) for factor in self.factors)

    def group(
        self, records: Iterable[tuple[str, Mapping[str, str]]]
    ) -> dict[UnitKey, tuple[str, ...]]:
        """(record id, coordinates) pairs -> unit key -> sorted record ids.

        Keys are returned in sorted order; the result does not depend on the
        order records were given in.
        """
        grouped: dict[UnitKey, list[str]] = {}
        seen: set[str] = set()
        for record_id, coordinates in records:
            if record_id in seen:
                raise DeclarationError(f"record {record_id!r} is projected twice")
            seen.add(record_id)
            grouped.setdefault(self.key(coordinates), []).append(record_id)
        return {key: tuple(sorted(grouped[key])) for key in sorted(grouped)}

    def document(self) -> list[str]:
        return list(self.factors)
