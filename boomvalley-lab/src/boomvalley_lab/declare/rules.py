"""Per-cell evidence expectations — ONE rule engine, three declared families.

The declaration side of R39 / R40 / R43. A rule is a `Selector` (the one
selector language) and a family payload. The engine owns everything the
families share; each family owns only its payload:

    coverage     partial: a cell no rule selects carries NO CLAIM
    overlap      several rules may select one cell only if their payloads are
                 canonically equal; otherwise the declaration is refused
    selectors    validated against the declared factors; each must select at
                 least one declared cell; no selector twice
    order        rule order is not meaning (canonical: sorted by selector)

Families (payloads):

    execution    ExecutionExpected    the actual-execution identity facts a
                                      covered cell must be produced with:
                                      model_identity, adapter_provenance
    artifact     ArtifactPolicy       the provenance a covered cell's artifact
                                      must record, and markers foreign for it
    derivation   DerivationExpected   the upstream stage, the one parent cell
                                      (the child's coordinates with overrides),
                                      the transform identity and version

What is *observed* and how it is *compared* (with which preconditions) lives in
`expect`, which may import this module; the declaration never imports it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.declare.cellspace import Cell, CellSpace, Factors
from boomvalley_lab.declare.document import section
from boomvalley_lab.declare.names import check_name
from boomvalley_lab.declare.selector import Selector


@dataclass(frozen=True)
class ExecutionExpected:
    model_identity: str
    adapter_provenance: str

    @classmethod
    def from_document(cls, document: Any) -> ExecutionExpected:
        if not isinstance(document, Mapping) or set(document) != {
            "model_identity", "adapter_provenance"
        }:
            raise DeclarationError(
                "an execution expectation expects exactly model_identity and adapter_provenance"
            )
        for key, value in document.items():
            if not isinstance(value, str) or not value.strip():
                raise DeclarationError(f"execution expectation {key} must be a non-empty string")
        return cls(document["model_identity"], document["adapter_provenance"])

    def document(self) -> dict:
        return {"model_identity": self.model_identity,
                "adapter_provenance": self.adapter_provenance}

    def rule_body(self) -> dict:
        return {"expect": self.document()}


@dataclass(frozen=True)
class ArtifactPolicy:
    required_provenance: str
    foreign_markers: tuple[str, ...]

    @classmethod
    def from_document(cls, document: Any) -> ArtifactPolicy:
        if not isinstance(document, Mapping) or set(document) - {
            "required_provenance", "foreign_markers"
        } or "required_provenance" not in document:
            raise DeclarationError(
                "an artifact provenance rule has required_provenance and optional foreign_markers"
            )
        required = document["required_provenance"]
        if not isinstance(required, str) or not required.strip():
            raise DeclarationError("required_provenance must be a non-empty string")
        markers = section(document, "foreign_markers", [])
        if not isinstance(markers, list) or any(
            not isinstance(m, str) or not m.strip() for m in markers
        ):
            raise DeclarationError("foreign_markers must be a list of non-empty strings")
        if len(set(markers)) != len(markers):
            raise DeclarationError("foreign_markers lists a marker twice")
        inside = sorted(m for m in markers if m in required)
        if inside:
            raise DeclarationError(
                f"markers {inside} occur inside the required provenance {required!r}; the "
                "cell's own artifacts would be foreign"
            )
        return cls(required, tuple(sorted(markers)))

    def document(self) -> dict:
        return {"required_provenance": self.required_provenance,
                "foreign_markers": list(self.foreign_markers)}

    def rule_body(self) -> dict:
        return self.document()


@dataclass(frozen=True)
class DerivationExpected:
    parent_stage: str
    parent_overrides: tuple[tuple[str, str], ...]
    transform_identity: str
    transform_version: str

    @classmethod
    def from_document(cls, document: Any) -> DerivationExpected:
        keys = {"parent_stage", "parent_overrides", "transform"}
        if not isinstance(document, Mapping) or set(document) - keys or not {
            "parent_stage", "transform"
        } <= set(document):
            raise DeclarationError(
                "a derivation expectation has parent_stage, transform and optional "
                "parent_overrides"
            )
        stage = check_name(document["parent_stage"], "a parent stage")
        overrides = section(document, "parent_overrides", {})
        if not isinstance(overrides, Mapping):
            raise DeclarationError("parent_overrides maps factor -> level")
        transform = document["transform"]
        if not isinstance(transform, Mapping) or set(transform) != {"identity", "version"}:
            raise DeclarationError("a transform is exactly {identity, version}")
        for key, value in transform.items():
            if not isinstance(value, str) or not value.strip():
                raise DeclarationError(f"transform {key} must be a non-empty string")
        return cls(stage, tuple(sorted(overrides.items())),
                   transform["identity"], transform["version"])

    def parent_of(self, child: Cell, factors: Factors) -> Cell:
        return factors.cell({**child.as_mapping(), **dict(self.parent_overrides)},
                            f"the parent of {child.key}")

    def document(self) -> dict:
        return {"parent_stage": self.parent_stage,
                "parent_overrides": dict(self.parent_overrides),
                "transform": {"identity": self.transform_identity,
                              "version": self.transform_version}}

    def rule_body(self) -> dict:
        return self.document()


P = TypeVar("P")


@dataclass(frozen=True)
class Rule(Generic[P]):
    selector: Selector
    payload: P


@dataclass(frozen=True)
class RuleSet(Generic[P]):
    """Canonically ordered rules of one family."""

    family: str
    rules: tuple[Rule[P], ...]

    @classmethod
    def of(cls, family: str, entries: Sequence[Any],
           parse: Callable[[Any], P]) -> RuleSet[P]:
        if not isinstance(entries, list) or not entries:
            raise DeclarationError(
                f"{family}: declare a non-empty list of rules, or omit the section"
            )
        rules = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping) or "select" not in entry:
                raise DeclarationError(f"{family}[{index}]: a rule has a 'select' mapping")
            selector = Selector.of(entry["select"]) if isinstance(entry["select"], Mapping) \
                else _refuse(f"{family}[{index}]: 'select' maps factor -> level")
            payload = parse({k: v for k, v in entry.items() if k != "select"})
            rules.append(Rule(selector, payload))
        selectors = [str(rule.selector) for rule in rules]
        repeated = sorted({s for s in selectors if selectors.count(s) > 1})
        if repeated:
            raise DeclarationError(f"{family}: selectors declared twice: {repeated}")
        return cls(family, tuple(sorted(rules, key=lambda rule: rule.selector.constraints)))

    def problems(self, factors: Factors, cells: CellSpace) -> list[str]:
        problems = []
        levels = factors.levels()
        for rule in self.rules:
            found = rule.selector.problems_against(levels)
            if found:
                problems.extend(f"{self.family} [{rule.selector}]: {p}" for p in found)
            elif not any(rule.selector.matches(c.as_mapping()) for c in cells.cells):
                problems.append(f"{self.family} [{rule.selector}]: selects no declared cell")
        if problems:
            return problems
        for cell in cells.cells:
            payloads = {canonical_bytes(_doc(rule.payload)) for rule in self.rules
                        if rule.selector.matches(cell.as_mapping())}
            if len(payloads) > 1:
                problems.append(
                    f"{self.family}: cell {cell.key} is given {len(payloads)} different "
                    "expectations by overlapping rules"
                )
        return problems

    def lookup(self, cell: Cell) -> P | None:
        """The payload covering `cell`, or None: NO CLAIM for this cell."""
        for rule in self.rules:
            if rule.selector.matches(cell.as_mapping()):
                return rule.payload
        return None

    def covered(self, cells: CellSpace) -> int:
        return sum(1 for cell in cells.cells if self.lookup(cell) is not None)

    def document(self) -> list:
        return [{"select": dict(rule.selector.constraints), **rule.payload.rule_body()}
                for rule in self.rules]


def _doc(payload: Any) -> dict:
    return payload.document()


def _refuse(message: str) -> Any:
    raise DeclarationError(message)


def artifact_rule_parse(entry: Mapping) -> ArtifactPolicy:
    return ArtifactPolicy.from_document(entry)


def execution_rule_parse(entry: Mapping) -> ExecutionExpected:
    if set(entry) != {"expect"}:
        raise DeclarationError("an execution expectation rule is {select, expect}")
    return ExecutionExpected.from_document(entry["expect"])


def derivation_rule_parse(entry: Mapping) -> DerivationExpected:
    return DerivationExpected.from_document(entry)


def derivation_problems(rules: RuleSet[DerivationExpected], stages: Sequence[str],
                        factors: Factors, cells: CellSpace) -> list[str]:
    """Stage vocabulary and parent resolution: one declared parent per child."""
    problems = []
    declared = set(cells.cells)
    for rule in rules.rules:
        if rule.payload.parent_stage not in stages:
            problems.append(
                f"derivation [{rule.selector}]: parent stage {rule.payload.parent_stage!r} "
                "is not a declared upstream stage"
            )
    used = {rule.payload.parent_stage for rule in rules.rules}
    for stage in stages:
        if stage not in used:
            problems.append(f"upstream stage {stage!r} is used by no derivation expectation")
    if problems:
        return problems
    for cell in cells.cells:
        payload = rules.lookup(cell)
        if payload is None:
            continue
        try:
            parent = payload.parent_of(cell, factors)
        except DeclarationError as error:
            problems.append(f"derivation for {cell.key}: {error}")
            continue
        if parent not in declared:
            problems.append(
                f"derivation for {cell.key}: parent {parent.key} is not a declared cell"
            )
    return problems
