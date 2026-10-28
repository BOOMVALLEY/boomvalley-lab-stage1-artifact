"""Failure / resume policy and analysis binding — declared, not executed.

FailurePolicy records the only MVP policy (frozen R7, R8; R15/R16 are built in
Phase 4). Any other value is refused: MVP has exactly one policy, and a
declaration that asked for another would be claiming a capability the product
does not have.

    attempts_per_cell            1   (no multi-attempt cells, no first-success)
    call_outcome_unknown         ABORT
    returned_not_persisted       ABORT
    persisted_not_in_custody     OPERATOR_CONFIRMED_RECOVERY (recorded RECOVERED)
    active_sessions_per_run      1   (owner decision R8; concurrent writers out)

`design_text` keeps the design's own words about failure handling verbatim
(D1: per-cell granularity); it is recorded, never interpreted.

AnalysisBinding names the analysis plugin the design pre-binds, by name, with
its declared parameters; nothing is loaded or run (plan §10).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.declare.document import section
from boomvalley_lab.declare.names import check_name

MVP_FAILURE_POLICY: dict[str, Any] = {
    "attempts_per_cell": 1,
    "call_outcome_unknown": "ABORT",
    "returned_not_persisted": "ABORT",
    "persisted_not_in_custody": "OPERATOR_CONFIRMED_RECOVERY",
    "active_sessions_per_run": 1,
}


@dataclass(frozen=True)
class FailurePolicy:
    design_text: str | None = None

    @classmethod
    def from_document(cls, document: Any) -> FailurePolicy:
        if not isinstance(document, Mapping):
            raise DeclarationError("failure_policy is a mapping")
        unknown = sorted(set(document) - set(MVP_FAILURE_POLICY) - {"design_text"})
        if unknown:
            raise DeclarationError(f"failure_policy: unknown settings {unknown}")
        for key, value in document.items():
            if key == "design_text":
                continue
            if value != MVP_FAILURE_POLICY[key] or type(value) is not type(MVP_FAILURE_POLICY[key]):
                raise DeclarationError(
                    f"failure_policy.{key} = {value!r} is not supported in MVP "
                    f"(the only policy is {MVP_FAILURE_POLICY[key]!r})"
                )
        text = document.get("design_text")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise DeclarationError("failure_policy.design_text is a non-empty string")
        return cls(text)

    def document(self) -> dict:
        return {**MVP_FAILURE_POLICY, "design_text": self.design_text}


_SCALAR = (str, int, float, bool)


@dataclass(frozen=True)
class AnalysisBinding:
    plugin: str
    version: str | None
    parameters: tuple[tuple[str, Any], ...]

    @classmethod
    def from_document(cls, document: Any) -> AnalysisBinding:
        if not isinstance(document, Mapping) or "plugin" not in document or set(document) - {
            "plugin", "version", "parameters"
        }:
            raise DeclarationError("analysis_binding has plugin, optional version and parameters")
        check_name(document["plugin"], "the analysis plugin name")
        version = document.get("version")
        if version is not None and (not isinstance(version, str) or not version.strip()):
            raise DeclarationError("analysis_binding.version is a non-empty string")
        parameters = section(document, "parameters", {})
        if not isinstance(parameters, Mapping):
            raise DeclarationError("analysis_binding.parameters maps name -> scalar")
        for name, value in parameters.items():
            check_name(name, "an analysis parameter name")
            if not isinstance(value, _SCALAR):
                raise DeclarationError(f"analysis parameter {name!r} must be a scalar")
        return cls(document["plugin"], version, tuple(sorted(parameters.items())))

    def document(self) -> dict:
        return {"plugin": self.plugin, "version": self.version,
                "parameters": dict(self.parameters)}
