"""The expectation-family interface (type only in Phase 0).

A family plugs into the one rule engine (selector -> expected document) by
saying three things:

    validate_expected   is this expected document well-formed for the family?
    observe             what does the evidence say actually happened for a cell?
                        None when the family's evidence records nothing
    compare             expected vs observed -> Finding (core.verdict rules:
                        declared but unobservable is VIOLATED)

`precondition_steps` names the gate steps that must be VERIFIED before the
family may compare (execution: binding; derivation: parent reconciliation), so
a family never reads unverified evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from boomvalley_lab.core.verdict import Finding


@runtime_checkable
class ExpectationFamily(Protocol):
    name: str
    precondition_steps: tuple[str, ...]

    def validate_expected(self, expected: Mapping[str, Any]) -> list[str]: ...

    def observe(self, evidence: Any, cell: str) -> Mapping[str, Any] | None: ...

    def compare(
        self, cell: str, expected: Mapping[str, Any], observed: Mapping[str, Any] | None
    ) -> Finding: ...
