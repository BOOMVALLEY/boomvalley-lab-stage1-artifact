"""What an analysis is allowed to be, and what it is allowed to see.

A plugin is the experiment's own code. The product gives it exactly the
records the eligibility gate admitted — nothing else — and records what it
was and what it produced:

    name / version   read off the object that ran, never off the declaration
    analyse(records, parameters) -> a canonical result document

A plugin never decides eligibility, never reads the artifact directory, never
reaches back into the journal or custody, and cannot admit a record the gate
refused: it is handed `AnalysisRecord`s and nothing more.

The reference plugin below exists so the product can test the gated path end
to end without shipping statistics. It counts; it does not model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AnalysisRecord:
    """One admitted realisation, as the analysis sees it."""

    record: str
    cell: str
    replicate: int
    coordinates: Mapping[str, str]
    content: bytes


@runtime_checkable
class AnalysisPlugin(Protocol):
    name: str
    version: str

    def analyse(self, records: Sequence[AnalysisRecord],
                parameters: Mapping[str, Any]) -> Mapping[str, Any]: ...


class CountingPlugin:
    """The reference plugin: deterministic, arithmetic-free, pure counting."""

    name = "counting"
    version = "v1"

    def analyse(self, records: Sequence[AnalysisRecord],
                parameters: Mapping[str, Any]) -> dict:
        per_cell: dict[str, int] = {}
        for record in records:
            per_cell[record.cell] = per_cell.get(record.cell, 0) + 1
        return {
            "records": len(records),
            "cells": dict(sorted(per_cell.items())),
            "bytes": sum(len(record.content) for record in records),
            "parameters": dict(sorted(parameters.items())),
        }
