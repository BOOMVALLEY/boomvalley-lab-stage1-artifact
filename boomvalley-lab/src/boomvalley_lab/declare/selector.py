"""The one selector language.

A selector is a non-empty conjunction of `(factor, level)` constraints over a
design's declared coordinates. It says which cells a declaration is about.
Execution expectations, artifact-provenance rules and derivation expectations
all select cells with it (frozen R39/R40/R43); there is exactly one
implementation.

Semantics
    matches      a cell matches when, for every constraint, its level of that
                 factor is exactly the constraint's level (string equality)
    canonical    constraints sorted by factor; declaration order is not meaning
    validity     non-empty; each factor at most once; non-empty strings;
                 against a design: known factors, declared levels
    identity     two selectors are equal iff their canonical forms are equal
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from boomvalley_lab.core.errors import DeclarationError


@dataclass(frozen=True)
class Selector:
    """A canonical conjunction of factor/level constraints. Build with `of`."""

    constraints: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.constraints:
            raise DeclarationError("a selector must constrain at least one factor")
        factors = [factor for factor, _level in self.constraints]
        if len(set(factors)) != len(factors):
            raise DeclarationError(f"a selector names a factor twice: {sorted(factors)}")
        for factor, level in self.constraints:
            if not isinstance(factor, str) or not factor.strip():
                raise DeclarationError(f"a selector factor must be a non-empty string: {factor!r}")
            if not isinstance(level, str) or not level.strip():
                raise DeclarationError(
                    f"a selector level must be a non-empty string: {factor}={level!r}"
                )
        if list(self.constraints) != sorted(self.constraints):
            raise DeclarationError("construct selectors with Selector.of(...)")

    @classmethod
    def of(cls, constraints: Mapping[str, str] | Iterable[Sequence[str]]) -> Selector:
        """From a mapping or (factor, level) pairs, in any order."""
        pairs = constraints.items() if isinstance(constraints, Mapping) else constraints
        normalised = []
        for pair in pairs:
            pair = tuple(pair)
            if len(pair) != 2:
                raise DeclarationError(f"a selector constraint is (factor, level): {pair!r}")
            normalised.append((pair[0], pair[1]))
        return cls(tuple(sorted(normalised)))

    @property
    def factors(self) -> tuple[str, ...]:
        return tuple(factor for factor, _level in self.constraints)

    def matches(self, coordinates: Mapping[str, str]) -> bool:
        return all(coordinates.get(factor) == level for factor, level in self.constraints)

    def problems_against(self, factors: Mapping[str, Sequence[str]]) -> list[str]:
        """What is wrong with this selector for a design with these factors."""
        problems = []
        for factor, level in self.constraints:
            if factor not in factors:
                problems.append(f"selector names undeclared factor {factor!r}")
            elif level not in factors[factor]:
                problems.append(f"selector names undeclared level {factor}={level!r}")
        return problems

    def document(self) -> list[list[str]]:
        """The canonical document form."""
        return [[factor, level] for factor, level in self.constraints]

    def __str__(self) -> str:
        return ",".join(f"{factor}={level}" for factor, level in self.constraints)
