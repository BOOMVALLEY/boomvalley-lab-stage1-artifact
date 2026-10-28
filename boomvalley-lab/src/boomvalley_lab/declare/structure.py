"""Denominator, analysis views, relation + invariant, assignment mechanisms.

All checked from the frozen declaration alone — no data, no outcomes.

    Denominator (R10/R26)   FULL_FACTOR: groups are every combination of all
                            factors; DECLARED_FACTORS: groups are combinations
                            of a declared non-empty subset. Expected counts per
                            group are summed from the declaration.
    AnalysisView (R23/R31)  named; a unit projection over factors (and
                            optionally `replicate`); a counting basis
                            (EXECUTION_RECORD | ANALYSIS_UNIT); optionally the
                            declared number of units, which must match
    Relation (R29/R32)      one relation, targeting exactly one view: a role
                            factor and >= 2 declared roles; the role factor may
                            not be part of the unit projection
    Realisability (R44)     every unit of the target view holds >= 2 distinct
                            declared roles among its declared records
    Invariant (R30)         per-unit role cardinalities covering every declared
                            role; checked only if R44 holds
    Assignment (R33-R36)    named mechanisms: unit projection -> assigned
                            factors (disjoint); within each unit every assigned
                            factor takes exactly one level; each mechanism at
                            its own scope
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.declare.cellspace import ExecutionRecord, Factors
from boomvalley_lab.declare.names import REPLICATE, check_name
from boomvalley_lab.declare.projection import Projection, UnitKey


class DenominatorPolicy(StrEnum):
    FULL_FACTOR = "FULL_FACTOR"
    DECLARED_FACTORS = "DECLARED_FACTORS"


class CountingBasis(StrEnum):
    EXECUTION_RECORD = "EXECUTION_RECORD"
    ANALYSIS_UNIT = "ANALYSIS_UNIT"


@dataclass(frozen=True)
class Denominator:
    policy: DenominatorPolicy
    factors: tuple[str, ...] = ()

    @classmethod
    def of(cls, policy: str, factors: Sequence[str] | None, all_factors: Sequence[str]
           ) -> Denominator:
        try:
            policy = DenominatorPolicy(policy)
        except ValueError:
            known = [p.value for p in DenominatorPolicy]
            raise DeclarationError(
                f"denominator policy {policy!r} is not one of {known}"
            ) from None
        if policy is DenominatorPolicy.FULL_FACTOR:
            if factors is not None and sorted(factors) != sorted(all_factors):
                raise DeclarationError(
                    "a FULL_FACTOR denominator groups by every factor; a projection "
                    "is a different promise and must be declared as DECLARED_FACTORS"
                )
            return cls(policy, tuple(sorted(all_factors)))
        if not factors:
            raise DeclarationError("a DECLARED_FACTORS denominator names no factors")
        unknown = sorted(set(factors) - set(all_factors))
        if unknown:
            raise DeclarationError(f"denominator factors {unknown} are not declared factors")
        if len(set(factors)) != len(factors):
            raise DeclarationError("denominator factors name a factor twice")
        return cls(policy, tuple(sorted(factors)))

    def document(self) -> dict:
        if self.policy is DenominatorPolicy.FULL_FACTOR:
            return {"policy": self.policy.value}
        return {"policy": self.policy.value, "factors": list(self.factors)}


@dataclass(frozen=True)
class AnalysisView:
    name: str
    unit: Projection
    basis: CountingBasis
    declared_units: int | None = None

    @classmethod
    def of(cls, name: str, unit: Sequence[str], basis: str,
           declared_units: int | None = None) -> AnalysisView:
        check_name(name, "an analysis view name")
        try:
            basis = CountingBasis(basis)
        except ValueError:
            raise DeclarationError(
                f"view {name!r}: basis {basis!r} is not one of {[b.value for b in CountingBasis]}"
            ) from None
        if declared_units is not None and (
            isinstance(declared_units, bool) or not isinstance(declared_units, int)
            or declared_units < 1
        ):
            raise DeclarationError(f"view {name!r}: units must be a positive integer")
        return cls(name, Projection.onto(unit), basis, declared_units)

    def units(self, records: Sequence[ExecutionRecord]) -> dict[UnitKey, tuple[str, ...]]:
        return self.unit.group((r.key, r.coordinates()) for r in records)

    def document(self) -> dict:
        return {"name": self.name, "unit": self.unit.document(), "basis": self.basis.value,
                "units": self.declared_units}


@dataclass(frozen=True)
class Relation:
    view: str
    role_factor: str
    roles: tuple[str, ...]
    invariant: tuple[tuple[str, int], ...] | None = None

    @classmethod
    def of(cls, view: str, role_factor: str, roles: Sequence[str],
           invariant: Mapping[str, int] | None) -> Relation:
        check_name(view, "the relation's view")
        check_name(role_factor, "the relation's role factor")
        roles = tuple(roles)
        for role in roles:
            check_name(role, "a relation role")
        if len(set(roles)) != len(roles):
            raise DeclarationError("the relation declares a role twice")
        if len(roles) < 2:
            raise DeclarationError("a relation declares at least two roles")
        pairs = None
        if invariant is not None:
            if not isinstance(invariant, Mapping) or not invariant:
                raise DeclarationError("a relation invariant maps role -> count")
            if set(invariant) != set(roles):
                raise DeclarationError(
                    "the relation invariant must give a count for every declared role "
                    f"(declared {sorted(roles)}, counted {sorted(invariant)})"
                )
            for role, count in invariant.items():
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise DeclarationError(
                        f"invariant count for role {role!r} is a non-negative integer"
                    )
            if not any(invariant.values()):
                raise DeclarationError("a relation invariant that requires no record says nothing")
            pairs = tuple(sorted(invariant.items()))
        return cls(view, role_factor, tuple(sorted(roles)), pairs)

    def document(self) -> dict:
        return {"view": self.view, "role_factor": self.role_factor, "roles": list(self.roles),
                "invariant": dict(self.invariant) if self.invariant is not None else None}


@dataclass(frozen=True)
class AssignmentMechanism:
    name: str
    unit: Projection
    assigned: tuple[str, ...]

    @classmethod
    def of(cls, name: str, unit: Sequence[str], assigned: Sequence[str]) -> AssignmentMechanism:
        check_name(name, "an assignment mechanism name")
        if not assigned:
            raise DeclarationError(f"mechanism {name!r} assigns no factor")
        if len(set(assigned)) != len(assigned):
            raise DeclarationError(f"mechanism {name!r} assigns a factor twice")
        projection = Projection.onto(unit)
        overlap = sorted(set(projection.factors) & set(assigned))
        if overlap:
            raise DeclarationError(
                f"mechanism {name!r}: {overlap} both identify the unit and are assigned to it"
            )
        return cls(name, projection, tuple(sorted(assigned)))

    def document(self) -> dict:
        return {"name": self.name, "unit": self.unit.document(), "assigned": list(self.assigned)}


# ---------------------------------------------------------------------------
# semantic checks over the frozen records
# ---------------------------------------------------------------------------
def unit_role_counts(view: AnalysisView, relation: Relation,
                     records: Sequence[ExecutionRecord]) -> dict[UnitKey, dict[str, int]]:
    """Unit -> declared role -> records. The one computation R44 and R30 share."""
    by_key = {r.key: r for r in records}
    counts: dict[UnitKey, dict[str, int]] = {}
    for unit, members in view.units(records).items():
        per_role = dict.fromkeys(relation.roles, 0)
        for key in members:
            level = by_key[key].cell.level(relation.role_factor)
            if level in per_role:
                per_role[level] += 1
        counts[unit] = per_role
    return counts


def relation_problems(relation: Relation, views: Mapping[str, AnalysisView],
                      factors: Factors, records: Sequence[ExecutionRecord]) -> list[str]:
    """R29, then R44, then R30 — each stage only if the previous one holds."""
    where = "relation"
    if relation.view not in views:
        return [f"{where}: targets view {relation.view!r}, which is not declared"]
    view = views[relation.view]
    levels = factors.levels()
    if relation.role_factor not in levels:
        return [f"{where}: role factor {relation.role_factor!r} is not a declared factor"]
    undeclared = sorted(set(relation.roles) - set(levels[relation.role_factor]))
    if undeclared:
        return [f"{where}: roles {undeclared} are not levels of {relation.role_factor!r}"]
    if relation.role_factor in view.unit.factors:
        return [
            f"{where}: role factor {relation.role_factor!r} identifies the units of view "
            f"{view.name!r}; every unit would hold one role"
        ]
    counts = unit_role_counts(view, relation, records)
    unrealisable = [
        f"{where}: unit {_show(unit)} of view {view.name!r} cannot realise the relation over "
        f"{relation.role_factor!r}: only {sorted(r for r, n in per_role.items() if n)} of the "
        f"declared roles occur in its declared records"
        for unit, per_role in counts.items()
        if sum(1 for n in per_role.values() if n) < 2
    ]
    if unrealisable:
        return unrealisable
    if relation.invariant is None:
        return []
    required = dict(relation.invariant)
    return [
        f"{where}: unit {_show(unit)} of view {view.name!r} holds {per_role[role]} record(s) "
        f"in role {role!r}; the invariant requires {want}"
        for unit, per_role in counts.items()
        for role, want in sorted(required.items())
        if per_role[role] != want
    ]


def assignment_problems(mechanism: AssignmentMechanism, factors: Factors,
                        records: Sequence[ExecutionRecord]) -> list[str]:
    """R34/R36 for one mechanism at its own scope."""
    where = f"assignment mechanism {mechanism.name!r}"
    levels = factors.levels()
    unknown = sorted((set(mechanism.unit.factors) - {REPLICATE}) - set(levels))
    unknown += sorted(set(mechanism.assigned) - set(levels))
    if unknown:
        return [f"{where}: names undeclared factors {unknown}"]
    if REPLICATE in mechanism.assigned:
        return [f"{where}: the replicate cannot be assigned"]
    by_key = {r.key: r for r in records}
    problems = []
    for unit, members in mechanism.unit.group((r.key, r.coordinates()) for r in records).items():
        for factor in mechanism.assigned:
            seen = sorted({by_key[k].cell.level(factor) for k in members})
            if len(seen) != 1:
                problems.append(
                    f"{where}: unit {_show(unit)} receives {len(seen)} levels of "
                    f"{factor!r} {seen}; an assignment unit receives exactly one"
                )
    return problems


def denominator_expectation(denominator: Denominator, view: AnalysisView,
                            records: Sequence[ExecutionRecord]) -> dict[str, int]:
    """Group key -> the count the declaration registers, for one view's basis."""
    group = Projection.onto(denominator.factors)
    if view.basis is CountingBasis.EXECUTION_RECORD:
        counted = [r.coordinates() for r in records]
    else:
        by_key = {r.key: r for r in records}
        counted = []
        for unit, members in view.units(records).items():
            keys = {group.key(by_key[k].coordinates()) for k in members}
            if len(keys) != 1:
                raise DeclarationError(
                    f"view {view.name!r}: unit {_show(unit)} spans several denominator groups; "
                    f"denominator factors {list(denominator.factors)} must be constant "
                    "within an analysis unit"
                )
            counted.append(by_key[members[0]].coordinates())
    expected: dict[str, int] = {}
    for coordinates in counted:
        key = _show(group.key(coordinates))
        expected[key] = expected.get(key, 0) + 1
    return dict(sorted(expected.items()))


def _show(unit: UnitKey) -> str:
    return "/".join(f"{factor}={level}" for factor, level in unit)
