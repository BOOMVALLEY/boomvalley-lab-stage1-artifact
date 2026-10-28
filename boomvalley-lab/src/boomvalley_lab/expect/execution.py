"""R39 — declared execution vs what actually answered.

The declaration may state, per covered cell, the actual-execution document a
realisation must have been produced with. The gate compares that expectation
against the execution facts custody bound to the artifact (R38), which came
off the RESPONSE (R37).

Two things this must never do:

  * use the adapter's INTENDED identity as evidence of success — a run that
    asked for model X and was answered by model Y matched nothing;
  * pass because nothing was observed — a covered cell with no bound execution
    is a declared claim that cannot be checked, which is VIOLATED.

A cell no rule selects carries no claim at all (NO_CLAIM).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.verdict import Finding, Verdict, decide
from boomvalley_lab.declare.rules import ExecutionExpected

FAMILY = "execution"
PRECONDITION_STEPS = ("custody_integrity", "execution_binding")


class ExecutionFamily:
    """Observes bound actual-execution documents; compares by exact equality."""

    name = FAMILY
    precondition_steps = PRECONDITION_STEPS

    def validate_expected(self, expected: Mapping[str, Any]) -> list[str]:
        try:
            ExecutionExpected.from_document(expected)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return [str(error)]
        return []

    def observe(self, evidence: Mapping[str, Any], cell: str) -> Mapping[str, Any] | None:
        """`evidence`: cell -> the bound actual-execution documents of its records."""
        observed = evidence.get(cell)
        if not observed:
            return None
        return {"actual_execution": list(observed)}

    def compare(self, cell: str, expected: Mapping[str, Any],
                observed: Mapping[str, Any] | None) -> Finding:
        step = f"{FAMILY}:{cell}"
        if observed is None:
            return Finding(step, Verdict.VIOLATED,
                           ("declared, and no bound actual execution was recorded for this "
                            "cell: the claim cannot be checked",))
        wanted = dict(expected)
        differing = [document for document in observed["actual_execution"]
                     if dict(document) != wanted]
        verdict = decide(claimed=True, checkable=True, holds=not differing)
        if verdict is Verdict.VERIFIED:
            return Finding(step, verdict)
        first = differing[0]
        return Finding(step, verdict, (
            f"declared {wanted}, {len(differing)} of {len(observed['actual_execution'])} "
            f"realisation(s) were executed as {dict(first)}",
        ))
