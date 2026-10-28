"""Bound analysis and deterministic metrics (T1-009).

The official analysis of a run is pre-bound, admits evidence only through the
L1 dataset's eligibility, and is recomputable by any verifier:

    plan-6 ``analysis``  one frozen ``AnalysisContractV1`` (closed metric
                         kinds) enters PlanIdentity, so it is decided by
                         gate-2 before any call and cannot be chosen after
                         the data is seen
    admission            the analysis population is exactly the dataset's
                         eligible decision units, plus the proposals and
                         calls in their lineage; an ineligible unit is
                         listed with its reasons and never reaches a metric
    ``analysis_output``  written at seal from the verified ``dataset_units``
                         member it names; the product verifier and the
                         stdlib FULLMT reader each recompute it from their
                         own dataset reconstruction and require byte equality

Metrics are exact: every value is a reduced rational ``"p/q"`` (or
``UNDEFINED`` over an empty population), computed with integer arithmetic
from JSON numbers, so recomputation is bit-identical on every platform.

    unit_count          admitted units of one table (decisions / proposals /
                        calls)
    action_mean         mean of one numeric field of the requested action
    action_share        share of admitted decisions whose requested action
                        field equals one declared scalar
    proposal_agreement  share of admitted candidate proposals whose value
                        equals their decision's requested action

Every metric may be grouped ``by`` one unit coordinate (node, round,
episode_key).  Nothing here knows a study: fields and values come from the
frozen contract, rows from the dataset.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import DeclarationError

ANALYSIS_CONTRACT_SCHEMA = "bvl-analysis-contract-1"
ANALYSIS_OUTPUT_SCHEMA = "boomvalley-lab-analysis-output-1"
ANALYSIS_ROLE = "analysis_output"
ANALYSIS_CHECK = "bound_analysis_recomputes_over_admitted_units"
POPULATION = "ELIGIBLE_DECISION_UNITS"
COMPUTED = "COMPUTED"
NO_ADMITTED_UNITS = "NO_ADMITTED_UNITS"
UNDEFINED = "UNDEFINED"
ANALYSIS_LIMITATIONS = ("CLOSED_KERNEL_METRICS_ONLY", "SINGLE_RUN_POPULATION")

TABLES = ("calls", "decisions", "proposals")
GROUP_BY = ("episode_key", "node", "round")
# kind -> its required parameters beyond metric_id / kind / by
METRIC_KINDS: dict[str, frozenset[str]] = {
    "action_mean": frozenset({"field"}),
    "action_share": frozenset({"equals", "field"}),
    "proposal_agreement": frozenset(),
    "unit_count": frozenset({"table"}),
}
_COMMON = frozenset({"metric_id", "kind"})
_CONTRACT_KEYS = frozenset({"schema", "analysis_id", "metrics"})


def _invalid(detail: str) -> DeclarationError:
    return DeclarationError(f"BVL-ANA-001 analysis contract is invalid: {detail}")


def _scalar(value: Any) -> bool:
    """A declared comparison value: text, a boolean or an integer (never a float)."""

    return isinstance(value, (str, bool, int))


def _metric_problems(metric: Any) -> str | None:
    if not isinstance(metric, Mapping):
        return "a metric is not an object"
    kind = metric.get("kind")
    if kind not in METRIC_KINDS:
        return f"metric kind {kind!r} is not one of {sorted(METRIC_KINDS)}"
    allowed = _COMMON | METRIC_KINDS[kind] | {"by"}
    if not (_COMMON | METRIC_KINDS[kind]) <= set(metric) <= allowed:
        return f"metric {metric.get('metric_id')!r} has the wrong closed shape for {kind}"
    if not isinstance(metric["metric_id"], str) or not metric["metric_id"]:
        return "a metric_id is not a non-empty string"
    if "by" in metric and metric["by"] not in GROUP_BY:
        return f"metric {metric['metric_id']!r} groups by {metric['by']!r}, not one of {GROUP_BY}"
    if "table" in metric and metric["table"] not in TABLES:
        return f"metric {metric['metric_id']!r} counts table {metric['table']!r}"
    if "field" in metric and (not isinstance(metric["field"], str) or not metric["field"]):
        return f"metric {metric['metric_id']!r} names no requested-action field"
    if "equals" in metric and not _scalar(metric["equals"]):
        return f"metric {metric['metric_id']!r} compares with a non-scalar"
    return None


@dataclass(frozen=True)
class AnalysisContractV1:
    """One run's pre-bound official analysis: a closed list of metrics."""

    analysis_id: str
    metrics: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.analysis_id, str) or not self.analysis_id:
            raise _invalid("analysis_id is not a non-empty string")
        if not self.metrics:
            raise _invalid("an analysis binds at least one metric")
        for metric in self.metrics:
            problem = _metric_problems(metric)
            if problem:
                raise _invalid(problem)
        ids = [metric["metric_id"] for metric in self.metrics]
        if ids != sorted(set(ids)):
            raise _invalid("metric ids are not unique and sorted")

    @classmethod
    def of(cls, analysis_id: str, metrics: Sequence[Mapping[str, Any]]) -> AnalysisContractV1:
        """Declare a contract; metrics are ordered by metric_id."""

        return cls(analysis_id, tuple(sorted((dict(m) for m in metrics),
                                             key=lambda m: str(m.get("metric_id")))))

    @classmethod
    def from_document(cls, document: Any) -> AnalysisContractV1:
        if not isinstance(document, Mapping) or set(document) != _CONTRACT_KEYS:
            raise _invalid("the contract has the wrong closed shape")
        if document["schema"] != ANALYSIS_CONTRACT_SCHEMA:
            raise _invalid(f"the contract is not {ANALYSIS_CONTRACT_SCHEMA}")
        if not isinstance(document["metrics"], list):
            raise _invalid("metrics is not a list")
        return cls(document["analysis_id"], tuple(dict(m) if isinstance(m, Mapping) else m
                                                  for m in document["metrics"]))

    def require_action_fields(self, schemas: Sequence[Mapping[str, str]]) -> None:
        """A metric reads a declared field as a value of its declared type (SV-04).

        *schemas* are the field -> type maps of the plan's proposal schemas: a
        requested action is of one of them, closed and fully typed.  A share
        compares by canonical form, so a field that does not hold values of the
        declared comparison's own type can never be met (a ``number`` field may
        say ``5.0``, which is not the integer ``5``; a ``string`` is never
        ``2``), and a mean over a field that holds no number is over nothing:
        valid-looking numbers about nothing, so the declaration is refused.  A
        share against an integer is refused when any schema of the plan
        declares its field ``number`` (SV-08: an ``integer`` sibling does not
        make the ``2.0`` of the schema a decision follows the integer ``2``).
        A field no schema of the plan declares is not this check's (one
        contract may be bound to studies of several domains; such a metric
        counts no hit: ``hits`` 0 of ``n``).
        """

        for metric in self.metrics:
            if "field" not in metric:
                continue
            name, where = metric["field"], f"metric {metric['metric_id']!r}"
            types = sorted({fields[name] for fields in schemas if name in fields})
            if not types:
                continue
            if metric["kind"] == "action_mean":
                wanted = {"integer", "number"}
            else:
                equals = metric["equals"]
                wanted = {"boolean" if isinstance(equals, bool)
                          else "integer" if isinstance(equals, int) else "string"}
            if not wanted & set(types) or (wanted == {"integer"} and "number" in types):
                raise _invalid(f"{where} reads field {name!r} as {' or '.join(sorted(wanted))}; "
                               f"the plan's proposal schemas declare it {', '.join(types)}")

    def document(self) -> dict[str, Any]:
        return {
            "schema": ANALYSIS_CONTRACT_SCHEMA,
            "analysis_id": self.analysis_id,
            "metrics": [dict(metric) for metric in self.metrics],
        }


# ---------------------------------------------------------------- admission
def _key(identity: Mapping[str, Any]) -> str:
    return f"{identity['kind']}:{identity['digest']}"


def admitted_units(dataset: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The analysis population: eligible decision units and their lineage only."""

    eligible = {_key(row["unit"]) for row in dataset["eligibility"] if row["eligible"] is True}
    decisions = [row for row in dataset["decisions"] if _key(row["unit"]) in eligible]
    wanted = {_key(c) for row in decisions for c in row["candidates"]}
    proposals = [row for row in dataset["proposals"] if _key(row["unit"]) in wanted]
    called = {_key(row["call"]) for row in proposals}
    calls = [row for row in dataset["calls"] if _key(row["unit"]) in called]
    return {"calls": calls, "decisions": decisions, "proposals": proposals}


# ---------------------------------------------------------------- exact metrics
def _ratio(numerator: Fraction | int, denominator: int) -> str:
    if denominator == 0:
        return UNDEFINED
    value = Fraction(numerator) / denominator
    return f"{value.numerator}/{value.denominator}"


def _number(value: Any) -> Fraction | None:
    """A JSON number as an exact rational; anything else is not a number."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Fraction(value)


def _action(row: Mapping[str, Any], field: str) -> Any:
    action = row.get("requested_action")
    return action.get(field) if isinstance(action, Mapping) else None


def _grouped(
    rows: Sequence[Mapping[str, Any]],
    by: str | None,
    measure: Callable[[Sequence[Mapping[str, Any]]], dict[str, Any]],
) -> list[dict[str, Any]]:
    if by is None:
        return [{"group": "*", **measure(rows)}]
    groups: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row[by], []).append(row)
    return [{"group": group, **measure(groups[group])} for group in sorted(groups)]


def metric_result(
    metric: Mapping[str, Any], units: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """One declared metric over the admitted units."""

    kind, by = metric["kind"], metric.get("by")
    proposals = {_key(row["unit"]): row for row in units["proposals"]}

    if kind == "unit_count":
        def measure(rows):  # noqa: ANN001, ANN202
            return {"n": len(rows), "value": _ratio(len(rows), 1)}

        rows = units[metric["table"]]
    elif kind == "action_mean":
        def measure(rows):  # noqa: ANN001, ANN202
            numbers = [_number(_action(row, metric["field"])) for row in rows]
            present = [number for number in numbers if number is not None]
            return {"n": len(present), "missing": len(rows) - len(present),
                    "value": _ratio(sum(present, Fraction(0)), len(present))}

        rows = units["decisions"]
    elif kind == "action_share":
        def measure(rows):  # noqa: ANN001, ANN202
            target = canonical_json(metric["equals"])
            hits = sum(
                1 for row in rows
                if _action(row, metric["field"]) is not None
                and canonical_json(_action(row, metric["field"])) == target
            )
            return {"n": len(rows), "hits": hits, "value": _ratio(hits, len(rows))}

        rows = units["decisions"]
    else:  # proposal_agreement
        def measure(rows):  # noqa: ANN001, ANN202
            pairs = [(row, proposals[_key(c)]) for row in rows for c in row["candidates"]]
            hits = sum(
                1 for row, proposal in pairs
                if row.get("requested_action") is not None
                and canonical_json(proposal["value"]) == canonical_json(row["requested_action"])
            )
            return {"n": len(pairs), "hits": hits, "value": _ratio(hits, len(pairs))}

        rows = units["decisions"]
    return {
        "metric_id": metric["metric_id"],
        "kind": kind,
        "by": by,
        "groups": _grouped(rows, by, measure),
    }


def analysis_document(
    *,
    contract: AnalysisContractV1,
    dataset: Mapping[str, Any],
    dataset_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """The official analysis of one sealed L1 run, from its dataset units only."""

    units = admitted_units(dataset)
    admitted = {_key(row["unit"]) for row in units["decisions"]}
    return {
        "schema": ANALYSIS_OUTPUT_SCHEMA,
        "run": dataset["run"],
        "experiment_id": dataset["experiment_id"],
        "plan": dict(dataset["plan"]),
        "contract": contract.document(),
        "dataset": dict(dataset_evidence),
        "population": POPULATION,
        "status": COMPUTED if units["decisions"] else NO_ADMITTED_UNITS,
        "admitted": {
            table: [row["unit"] for row in units[table]] for table in TABLES
        },
        "excluded": [
            {"unit": row["unit"], "reasons": list(row["reasons"])}
            for row in dataset["eligibility"]
            if _key(row["unit"]) not in admitted
        ],
        "metrics": [metric_result(metric, units) for metric in contract.metrics],
        "limitations": sorted(ANALYSIS_LIMITATIONS),
    }


__all__ = [
    "ANALYSIS_CHECK",
    "ANALYSIS_CONTRACT_SCHEMA",
    "ANALYSIS_LIMITATIONS",
    "ANALYSIS_OUTPUT_SCHEMA",
    "ANALYSIS_ROLE",
    "COMPUTED",
    "GROUP_BY",
    "METRIC_KINDS",
    "NO_ADMITTED_UNITS",
    "POPULATION",
    "TABLES",
    "UNDEFINED",
    "AnalysisContractV1",
    "admitted_units",
    "analysis_document",
    "metric_result",
]
