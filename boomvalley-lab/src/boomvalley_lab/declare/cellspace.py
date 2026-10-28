"""Factors, the frozen cell space, replication and the schedule (R20, R21,
R27, R28; MVP: everything fixed at registration, R22/R25 out of scope).

    Factor        a name and its legal levels (a set: canonical = sorted)
    Cell          one value for EVERY declared factor; canonical coordinates
                  sorted by factor; key `f1=l1/f2=l2`
    CellSpace     the complete frozen set of executable cells — the full
                  product, or an explicit subset (sparse, ragged,
                  non-Cartesian). Never inferred from data.
    Replication   replicates per cell: one uniform count, or counts per stratum
                  of a projection. Never encoded by repeating cells.
    ExecutionRecord  (cell, replicate r) — one scheduled execution
    Schedule      the frozen order of ALL execution records, each exactly once.
                  Order is meaning (counterbalancing). Declared explicitly, or
                  as the canonical order (cell key, then replicate).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.declare.collection import NamedCollection
from boomvalley_lab.declare.names import REPLICATE, RESERVED_FACTOR_NAMES, check_name
from boomvalley_lab.declare.projection import Projection, UnitKey


@dataclass(frozen=True)
class Factor:
    name: str
    levels: tuple[str, ...]

    @classmethod
    def of(cls, name: str, levels: Iterable[str]) -> Factor:
        check_name(name, "a factor name")
        if name in RESERVED_FACTOR_NAMES:
            raise DeclarationError(f"{name!r} is reserved and cannot name a factor")
        levels = tuple(levels)
        if not levels:
            raise DeclarationError(f"factor {name!r} declares no levels")
        for level in levels:
            check_name(level, f"a level of factor {name!r}")
        repeated = sorted({lv for lv in levels if levels.count(lv) > 1})
        if repeated:
            raise DeclarationError(f"factor {name!r} lists levels twice: {repeated}")
        return cls(name, tuple(sorted(levels)))

    def document(self) -> dict:
        return {"name": self.name, "levels": list(self.levels)}


@dataclass(frozen=True, order=True)
class Cell:
    """Canonical coordinates: ((factor, level), ...) sorted by factor."""

    coordinates: tuple[tuple[str, str], ...]

    @property
    def key(self) -> str:
        return "/".join(f"{factor}={level}" for factor, level in self.coordinates)

    def as_mapping(self) -> dict[str, str]:
        return dict(self.coordinates)

    def level(self, factor: str) -> str:
        return self.as_mapping()[factor]

    def document(self) -> dict[str, str]:
        return self.as_mapping()


@dataclass(frozen=True, order=True)
class ExecutionRecord:
    cell: Cell
    replicate: int

    @property
    def key(self) -> str:
        return f"{self.cell.key}#r{self.replicate}"

    def coordinates(self) -> dict[str, str]:
        """Factor levels plus the reserved `replicate` coordinate."""
        return {**self.cell.as_mapping(), REPLICATE: str(self.replicate)}

    def document(self) -> list:
        return [self.cell.key, self.replicate]


class Factors:
    """The declared factors, by name."""

    def __init__(self, factors: Iterable[Factor]) -> None:
        self._collection = NamedCollection.of(factors, what="factor")
        if not len(self._collection):
            raise DeclarationError("a design declares at least one factor")

    @property
    def names(self) -> tuple[str, ...]:
        return self._collection.names

    def get(self, name: str) -> Factor:
        return self._collection.get(name)

    def levels(self) -> dict[str, tuple[str, ...]]:
        return {factor.name: factor.levels for factor in self._collection}

    def __iter__(self):
        return iter(self._collection)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Factors) and self._collection == other._collection

    def __hash__(self) -> int:
        return hash(self._collection)

    def cell(self, coordinates: Mapping[str, str], where: str = "a cell") -> Cell:
        """A cell from coordinates that name every factor with a declared level."""
        if not isinstance(coordinates, Mapping):
            raise DeclarationError(f"{where} must map factor -> level: {coordinates!r}")
        levels = self.levels()
        unknown = sorted(set(coordinates) - set(levels))
        if unknown:
            raise DeclarationError(f"{where} names undeclared factors {unknown}")
        missing = sorted(set(levels) - set(coordinates))
        if missing:
            raise DeclarationError(f"{where} gives no level for factors {missing}")
        for factor, level in coordinates.items():
            if level not in levels[factor]:
                raise DeclarationError(f"{where} names undeclared level {factor}={level!r}")
        return Cell(tuple(sorted(coordinates.items())))

    def product(self) -> tuple[Cell, ...]:
        names = self.names
        levels = self.levels()
        return tuple(
            Cell(tuple(zip(names, combination, strict=True)))
            for combination in itertools.product(*(levels[n] for n in names))
        )

    def check_projection(self, projection: Projection, where: str,
                         *, allow_replicate: bool) -> None:
        allowed = set(self.names) | ({REPLICATE} if allow_replicate else set())
        unknown = sorted(set(projection.factors) - allowed)
        if unknown:
            raise DeclarationError(f"{where} projects onto undeclared factors {unknown}")


@dataclass(frozen=True)
class CellSpace:
    """The complete frozen executable cell set. `explicit` records the form."""

    cells: tuple[Cell, ...]
    explicit: bool

    @classmethod
    def build(cls, factors: Factors, explicit_cells: Sequence[Mapping[str, str]] | None
              ) -> CellSpace:
        if explicit_cells is None:
            return cls(tuple(sorted(factors.product())), explicit=False)
        if not explicit_cells:
            raise DeclarationError("an explicit cell space declares no cells")
        cells = [factors.cell(c, f"cells[{i}]") for i, c in enumerate(explicit_cells)]
        repeated = sorted({c.key for c in cells if cells.count(c) > 1})
        if repeated:
            raise DeclarationError(f"the cell space lists cells twice: {repeated[:3]}")
        return cls(tuple(sorted(cells)), explicit=True)

    def __contains__(self, cell: Cell) -> bool:
        return cell in set(self.cells)

    def by_key(self) -> dict[str, Cell]:
        return {cell.key: cell for cell in self.cells}


@dataclass(frozen=True)
class Replication:
    """Replicates per cell: uniform, or per stratum of `strata` (R21/R27)."""

    uniform: int | None = None
    strata: Projection | None = None
    counts: tuple[tuple[UnitKey, int], ...] = field(default=())

    def __post_init__(self) -> None:
        if (self.uniform is None) == (self.strata is None):
            raise DeclarationError("replication is either uniform or stratified, not both")
        if self.uniform is not None and not _positive(self.uniform):
            raise DeclarationError(f"a replicate count is a positive integer: {self.uniform!r}")
        for key, count in self.counts:
            if not _positive(count):
                raise DeclarationError(
                    f"stratum {dict(key)} replicate count must be a positive integer: {count!r}"
                )

    def check(self, factors: Factors, cells: CellSpace) -> None:
        if self.strata is None:
            return
        factors.check_projection(self.strata, "replication strata", allow_replicate=False)
        present = {self.strata.key(cell.as_mapping()) for cell in cells.cells}
        declared = [key for key, _count in self.counts]
        repeated = sorted({str(dict(k)) for k in declared if declared.count(k) > 1})
        if repeated:
            raise DeclarationError(f"replication declares strata twice: {repeated[:3]}")
        missing = sorted(str(dict(k)) for k in present - set(declared))
        if missing:
            raise DeclarationError(f"replication gives no count for strata {missing[:3]}")
        unused = sorted(str(dict(k)) for k in set(declared) - present)
        if unused:
            raise DeclarationError(
                f"replication counts strata that no declared cell belongs to: {unused[:3]}"
            )

    def replicates(self, cell: Cell) -> int:
        if self.uniform is not None:
            return self.uniform
        return dict(self.counts)[self.strata.key(cell.as_mapping())]

    def document(self) -> dict:
        if self.uniform is not None:
            return {"uniform": self.uniform}
        return {
            "strata": self.strata.document(),
            "counts": [{"stratum": dict(key), "replicates": count}
                       for key, count in sorted(self.counts)],
        }


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def execution_records(cells: CellSpace, replication: Replication) -> tuple[ExecutionRecord, ...]:
    """Every scheduled execution: each cell times its replicate count."""
    return tuple(
        ExecutionRecord(cell, r)
        for cell in cells.cells
        for r in range(replication.replicates(cell))
    )


@dataclass(frozen=True)
class Schedule:
    """The frozen execution order. `declared` records whether an explicit order
    was given (True) or the canonical order was chosen (False)."""

    order: tuple[ExecutionRecord, ...]
    declared: bool

    @classmethod
    def build(cls, records: Sequence[ExecutionRecord], order: Sequence[str] | None,
              ) -> Schedule:
        if order is None:
            return cls(tuple(sorted(records)), declared=False)
        by_key = {record.key: record for record in records}
        repeated = sorted({k for k in order if list(order).count(k) > 1})
        if repeated:
            raise DeclarationError(f"the schedule lists executions twice: {repeated[:3]}")
        unknown = sorted(set(order) - set(by_key))
        if unknown:
            raise DeclarationError(
                f"the schedule names executions the design does not declare: {unknown[:3]}"
            )
        missing = sorted(set(by_key) - set(order))
        if missing:
            raise DeclarationError(f"the schedule omits declared executions: {missing[:3]}")
        return cls(tuple(by_key[key] for key in order), declared=True)

    def document(self) -> list:
        return [record.document() for record in self.order]
