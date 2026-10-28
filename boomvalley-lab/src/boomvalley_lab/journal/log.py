"""The append-only log and its durability policy.

Write:   one canonical-JSON line per record, appended, then `flush()` and
         `os.fsync()` of the file before `append` returns. A record whose
         `append` returned is on stable storage as far as the OS can promise;
         the runtime acts on a record (e.g. calls the adapter after
         INTENT_RECORDED) only after that return.
Read:    lines are parsed in order. A final line without its newline is a
         torn write from a crash and is discarded — it was never
         acknowledged. Any other unreadable line — not UTF-8, or not one
         canonical-JSON document (core.strict_json) — is corruption and
         refuses the whole log (EvidenceError): the runtime never guesses.
Limits:  no directory fsync (not available for directories on Windows); no
         cryptographic protection (D4); a single writer is assumed and
         enforced by the session lock (R8).
Held:    inside `held(path, ...)` one operation of this process - an
         execution, which is the log's one writer, or a verification of a run
         nothing is writing - keeps the records it has already read and
         checked, so a read is not a re-parse of the whole file after every
         append or for every call verified (T4-013: both were quadratic in
         the run's length). The held records are served only while the file
         still has the size and modification time they were read at; anything
         else - a torn tail, a rewrite, another writer - is a full read
         again. Nothing is held across operations: every command parses the
         file itself. `held_members` is the same for a directory of
         content-addressed members. Limit: a rewrite that keeps both a file's
         size and its modification time inside one operation is not seen by
         that operation.

`Journal` is the attempt journal. Custody entries (Phase 3) are a second log
with the same durability, its own file and its own record check — one
implementation, so evidence durability cannot drift between the two.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.core.layout import JOURNAL_FILE
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.journal.events import check_event


def unterminated(data: bytes) -> int:
    """The bytes after the last newline: a torn tail, never an acknowledged record."""
    return len(data) - (data.rfind(b"\n") + 1)


@dataclass
class _Held:
    """What one operation has read of a path: the records and the file they are."""

    holders: int = 1
    records: list | None = None
    signature: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    groups: dict[str, tuple[int, dict]] = field(default_factory=dict)
    members: dict[str, tuple[tuple[int, int], Any]] = field(default_factory=dict)

    def drop(self) -> None:
        self.records, self.signature = None, None
        self.groups.clear()


def _group(groups: dict, records: list[dict], start: int, key: Callable[[dict], Any]) -> dict:
    for index in range(start, len(records)):
        value = key(records[index])
        if value is not None:
            groups.setdefault(value, []).append(records[index])
    return groups


_HELD: dict[str, _Held] = {}
_HELD_LOCK = threading.Lock()


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


def _listing(directory: Path) -> tuple[tuple[str, int, int], ...] | None:
    try:
        with os.scandir(directory) as entries:
            found = []
            for entry in entries:
                status = entry.stat()
                found.append((entry.name, status.st_size, status.st_mtime_ns))
    except OSError:
        return None
    return tuple(sorted(found))


def held_members(
    directory: Path, load: Callable[[Path], Any], suffix: str = ".json"
) -> list[tuple[str, Any]]:
    """``(name, load(path))`` of every *suffix* member of a directory, by name.

    While the directory is held a member is loaded once, and again only when
    its size or modification time moved, so a store that grows by one member
    is not re-read whole. What is returned is read, never changed: the caller
    copies what it hands on.
    """

    directory = Path(directory)
    held = _HELD.get(_key(directory))
    listing = None if held is None else _listing(directory)
    if held is None or listing is None:
        return [(path.name, load(path)) for path in sorted(directory.glob(f"*{suffix}"))]
    with held.lock:
        found: dict[str, tuple[tuple[int, int], Any]] = {}
        for name, size, modified in listing:
            if not name.endswith(suffix):
                continue
            kept = held.members.get(name)
            if kept is None or kept[0] != (size, modified):
                kept = ((size, modified), load(directory / name))
            found[name] = kept
        held.members = found
        return [(name, kept[1]) for name, kept in found.items()]


@contextmanager
def held(*paths: Path) -> Iterator[None]:
    """Hold what this process reads of *paths* for one operation.

    The operation is the paths' one writer or reads a run nothing is writing.
    Nested holds of a path share one set of records; the last exit drops them.
    """

    keys = [_key(Path(path)) for path in paths]
    with _HELD_LOCK:
        for key in keys:
            held = _HELD.get(key)
            if held is None:
                _HELD[key] = _Held()
            else:
                held.holders += 1
    try:
        yield
    finally:
        with _HELD_LOCK:
            for key in keys:
                held = _HELD[key]
                held.holders -= 1
                if not held.holders:
                    del _HELD[key]


class AppendOnlyLog:
    def __init__(self, path: Path, check: Callable[[object, str], dict], what: str) -> None:
        self.path = Path(path)
        self._check = check
        self._what = what

    def _admit(self, records: list[dict], start: int) -> None:
        """The log's own rule over ``records[start:]`` in their positions."""

    def append(self, record: dict) -> dict:
        record = self._check(record, "append")
        line = canonical_json(record) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        held = _HELD.get(_key(self.path))
        if held is None:
            self._write(line)
            return record
        with held.lock:
            before = held.signature
            current = held.records is not None and before == _signature(self.path)
            self._write(line)
            after = _signature(self.path)
            # The held records stay only if the file was the one they were read
            # from and grew by exactly this line.
            if (
                current
                and after is not None
                and after[0] == before[0] + len(line.encode("utf-8"))
            ):
                held.records.append(dict(record))
                try:
                    self._admit(held.records, len(held.records) - 1)
                except EvidenceError:
                    held.drop()  # the next read refuses it
                else:
                    held.signature = after
            else:
                held.drop()
        return record

    def _write(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _current(self, held: _Held) -> tuple[list[dict], bool]:
        """The log's records and whether they are *held*'s own (under its lock)."""

        signature = _signature(self.path)
        if held.records is None or signature is None or held.signature != signature:
            held.drop()
            records = self._parse()
            # Held only if the file did not move while it was parsed.
            if signature is None or _signature(self.path) != signature:
                return records, False
            held.records, held.signature = records, signature
        return held.records, True

    def count(self) -> int:
        """How many acknowledged records the log holds."""

        held = _HELD.get(_key(self.path))
        if held is None:
            return len(self._parse())
        with held.lock:
            return len(self._current(held)[0])

    def torn_tail(self) -> int:
        """How many unacknowledged bytes follow the last record (0 if none)."""
        return unterminated(self.path.read_bytes()) if self.path.exists() else 0

    def read(self) -> list[dict]:
        held = _HELD.get(_key(self.path))
        if held is None:
            return self._parse()
        with held.lock:
            records, shared = self._current(held)
            return [dict(record) for record in records] if shared else records

    def grouped(self, name: str, key: Callable[[dict], Any]) -> dict[Any, list[dict]]:
        """The records by ``key(record)`` in log order; a record keyed None is left out.

        *name* names the grouping. While the log is held it is built once and
        extended as the log grows, so looking one key up is not a scan of the
        log. The groups are read, never changed: ``selected`` hands out copies.
        """

        held = _HELD.get(_key(self.path))
        if held is None:
            return _group({}, self._parse(), 0, key)
        with held.lock:
            records, shared = self._current(held)
            if not shared:
                return _group({}, records, 0, key)
            done, groups = held.groups.get(name, (0, {}))
            held.groups[name] = (len(records), _group(groups, records, done, key))
            return groups

    def selected(self, name: str, key: Callable[[dict], Any], value: Any) -> list[dict]:
        """The records whose ``key(record)`` is *value*, in log order."""

        return [dict(record) for record in self.grouped(name, key).get(value, ())]

    def _parse(self) -> list[dict]:
        if not self.path.exists():
            return []
        parts = self.path.read_bytes().split(b"\n")
        # Every newline-terminated line was acknowledged. Whatever follows the
        # last newline is a torn write from a crash and is discarded - split
        # off as bytes, never decoded: a torn write may end inside a character.
        acknowledged = parts[:-1]
        records = []
        for number, line in enumerate(acknowledged, 1):
            try:
                parsed = load_bytes(line)
            except MalformedJSON as error:
                raise EvidenceError(
                    f"{self._what} line {number} is unreadable: {error}"
                ) from error
            records.append(self._check(parsed, f"{self._what} line {number}"))
        self._admit(records, 0)
        return records


class Journal(AppendOnlyLog):
    def __init__(self, directory: Path) -> None:
        super().__init__(Path(directory) / JOURNAL_FILE, check_event, "journal")
