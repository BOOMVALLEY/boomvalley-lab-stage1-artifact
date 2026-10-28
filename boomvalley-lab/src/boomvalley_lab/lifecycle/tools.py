"""The reference tools the `bvl` lifecycle ships (P17, T5-003 / T5-004).

A tool is an external capability a tool actor answers through.  It states

    EFFECT       READ_ONLY | MUTATING
    SIDE_EFFECT  NONE | IDEMPOTENT_BY_KEY | IRREVERSIBLE: what calling it
                 again may do to its resource
    OPERATIONS   per operation, the types of its arguments and result

and is called through one signature::

    call(*, operation, resource, arguments, idempotency_key)
        READ_ONLY  -> the typed value
        MUTATING   -> {"outcome": "APPLIED", "receipt", "value"}
                      | {"outcome": "NOT_APPLIED", "receipt": None, "value": None}
    reconcile(*, operation, resource, idempotency_key)      IDEMPOTENT_BY_KEY only
        -> the same answer, for the change the key was called with

One reference per side effect, each over plain files under a *site* directory
(``<site>/<kind>/<name>`` for the resource ``<kind>:<name>``), so what a call
did to its resource can be read by anyone:

    bvl.table-lookup-tool:1     NONE               ``lookup``: one row of a JSON
                                                   table by key
    bvl.record-append-tool:1    IDEMPOTENT_BY_KEY  ``append``: one record onto a
                                                   ledger; a key it has already
                                                   appended is answered with the
                                                   record it has, not appended again
    bvl.notice-dispatch-tool:1  IRREVERSIBLE       ``dispatch``: one notice into an
                                                   outbox; every call sends one more
                                                   and it keeps no key

A tool constructed without a site states its contract and cannot be called.
A run binds its tools to one site (``bound``, T5-007: ``bvl run --tool-site``),
an operational input like a human desk: the site is outside the run's evidence
and what a tool did there enters the run only as its journaled result.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_Shape = Mapping[str, Mapping[str, Mapping[str, str]]]
_NOT_APPLIED: Mapping[str, Any] = {"outcome": "NOT_APPLIED", "receipt": None, "value": None}


class _SiteTool:
    """A tool over the files of one site directory."""

    def __init__(self, site: Path | None = None) -> None:
        self.site = None if site is None else Path(site)

    def bound(self, site: Path) -> _SiteTool:
        """This tool over the files of *site*."""

        return type(self)(site)

    def _file(self, resource: str, suffix: str) -> Path:
        if self.site is None:
            raise RuntimeError(f"{type(self).__name__} is not bound to a site")
        kind, _, name = resource.partition(":")
        parts = name.split("/")
        if not kind or not name or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"resource {resource!r} does not name a file of the site")
        return self.site.joinpath(kind, *parts[:-1], parts[-1] + suffix)

    def _lines(self, resource: str) -> list[dict[str, Any]]:
        path = self._file(resource, ".jsonl")
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line
        ]

    def _append(self, resource: str, record: Mapping[str, Any]) -> None:
        path = self._file(resource, ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class TableLookupToolV1(_SiteTool):
    """Reads one row of a table by key; it changes nothing."""

    EFFECT = "READ_ONLY"
    SIDE_EFFECT = "NONE"
    OPERATIONS: _Shape = {
        "lookup": {
            "arguments": {"key": "string"},
            "result": {"found": "boolean", "quantity": "integer"},
        },
    }

    def call(
        self, *, operation: str, resource: str, arguments: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        del idempotency_key  # a read is the same read under any key
        _operation(self, operation)
        table = json.loads(self._file(resource, ".json").read_text(encoding="utf-8"))
        quantity = table.get(arguments["key"])
        return {"found": quantity is not None, "quantity": quantity or 0}


class RecordAppendToolV1(_SiteTool):
    """Appends one record onto an external ledger, once per idempotency key."""

    EFFECT = "MUTATING"
    SIDE_EFFECT = "IDEMPOTENT_BY_KEY"
    OPERATIONS: _Shape = {
        "append": {
            "arguments": {"key": "string", "quantity": "integer"},
            "result": {"sequence": "integer"},
        },
    }

    def call(
        self, *, operation: str, resource: str, arguments: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        _operation(self, operation)
        held = self.reconcile(
            operation=operation, resource=resource, idempotency_key=idempotency_key
        )
        if held["outcome"] == "APPLIED":
            return held  # this key's record is on the ledger: it is not appended again
        if arguments["quantity"] <= 0:
            return dict(_NOT_APPLIED)  # declined: nothing to record
        sequence = len(self._lines(resource)) + 1
        self._append(
            resource,
            {"idempotency_key": idempotency_key, "sequence": sequence,
             "record": dict(arguments)},
        )
        return _applied(resource, sequence)

    def reconcile(
        self, *, operation: str, resource: str, idempotency_key: str
    ) -> Mapping[str, Any]:
        """What the ledger holds for *idempotency_key*: its record, or nothing."""

        _operation(self, operation)
        for line in self._lines(resource):
            if line["idempotency_key"] == idempotency_key:
                return _applied(resource, line["sequence"])
        return dict(_NOT_APPLIED)


class NoticeDispatchToolV1(_SiteTool):
    """Sends one notice into an outbox; every call sends one more."""

    EFFECT = "MUTATING"
    SIDE_EFFECT = "IRREVERSIBLE"
    OPERATIONS: _Shape = {
        "dispatch": {
            "arguments": {"key": "string", "quantity": "integer"},
            "result": {"sequence": "integer"},
        },
    }

    def call(
        self, *, operation: str, resource: str, arguments: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        del idempotency_key  # a sent notice is not kept by key and cannot be recalled
        _operation(self, operation)
        sequence = len(self._lines(resource)) + 1
        self._append(resource, {"sequence": sequence, "notice": dict(arguments)})
        return _applied(resource, sequence)


def _operation(tool: object, operation: str) -> None:
    if operation not in tool.OPERATIONS:  # type: ignore[attr-defined]
        raise ValueError(f"{type(tool).__name__} has no operation {operation!r}")


def _applied(resource: str, sequence: int) -> dict[str, Any]:
    return {
        "outcome": "APPLIED",
        "receipt": f"{resource}/{sequence:06d}",
        "value": {"sequence": sequence},
    }
