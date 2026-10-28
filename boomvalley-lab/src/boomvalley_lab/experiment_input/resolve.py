"""Reference resolution (I2): a FileRef becomes bytes, read once, kept in memory.

    RelPath   1-32 `/`-separated segments, <= 255 bytes, each
              ^[A-Za-z0-9][A-Za-z0-9._-]*$, no `.`/`..`, none ending in `.`, no
              Windows reserved basename, final segment ending `.json`
              (Input Contract §12.1)

Resolution is relative to the directory holding the envelope and nothing else.
Each intermediate component must be a real directory, the final one a regular
file with one link; links, junctions and reparse points are refused; the name
on disk must match the segment byte for byte (a case alias is refused). The
file is opened, checked against what was walked, and read ONCE; no later stage
re-opens a reference. Everything after I2 — GNDCRW included — reads the
snapshot, never the user's path.

The walk is a portable approximation of §12.2 R2/R3 (lstat + open + fstat
identity comparison), not the handle-relative walk; see the backlog.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.experiment_input.errors import InputRefusal

SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RESERVED = ({"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)}
            | {f"LPT{i}" for i in range(1, 10)})
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

MIB16 = 16_777_216
KIB64 = 65_536


@dataclass(frozen=True)
class Snapshot:
    """The bytes of one reference, as read once."""

    path: str          # the RelPath as written (provenance, never identity)
    data: bytes

    @property
    def sha256(self) -> str:
        return str(sha256_bytes(self.data))

    @property
    def size(self) -> int:
        return len(self.data)

    def ref(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    def raw(self) -> dict:
        return {"sha256": self.sha256, "size": self.size}


def _refuse(code: str, detail: str, selector: str) -> InputRefusal:
    return InputRefusal("REFERENCE_ERROR", code, detail, layer="I2", path=f"{selector}#")


def check_relpath(path: object, selector: str) -> list[str]:
    """The segments of a RelPath, or REFERENCE_ERROR."""
    if not isinstance(path, str) or not path:
        raise _refuse("REF_PATH_INVALID", "a reference path is a non-empty string", selector)
    if len(path.encode("utf-8")) > 255:
        raise _refuse("REF_PATH_INVALID", "a reference path is at most 255 bytes", selector)
    if path.startswith("/") or "\\" in path or ":" in path:
        raise _refuse("REF_PATH_INVALID", f"{path!r} is not relative", selector)
    segments = path.split("/")
    if not 1 <= len(segments) <= 32:
        raise _refuse("REF_PATH_INVALID", f"{path!r} has {len(segments)} segments", selector)
    for segment in segments:
        if segment in (".", "..") or not SEGMENT.fullmatch(segment) or segment.endswith("."):
            raise _refuse("REF_PATH_INVALID", f"segment {segment!r} of {path!r}", selector)
        if segment.split(".")[0].upper() in RESERVED:
            raise _refuse("REF_PATH_INVALID", f"{segment!r} is a reserved name", selector)
    final = segments[-1]
    if final.lower().endswith((".yaml", ".yml")):
        raise _refuse("REF_YAML_NOT_SUPPORTED", f"{path!r}: YAML is not a carrier", selector)
    if not final.endswith(".json"):
        raise _refuse("REF_CARRIER_NOT_JSON", f"{path!r} does not end in .json", selector)
    return segments


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)


def read_regular(parent: Path, name: str, limit: int, selector: str) -> tuple[bytes, tuple]:
    """Read `parent/name` once: a regular, single-link, non-link file named exactly so."""
    target = parent / name
    try:
        walked = os.lstat(target)
    except FileNotFoundError:
        raise _refuse("REF_MISSING", f"{target} does not exist", selector) from None
    except OSError as error:
        raise _refuse("REF_MISSING", f"{target}: {error}", selector) from None
    if _is_link(walked):
        raise _refuse("REF_LINK", f"{target} is a link or reparse point", selector)
    if not stat.S_ISREG(walked.st_mode):
        raise _refuse("REF_NOT_REGULAR", f"{target} is not a regular file", selector)
    if name not in os.listdir(parent):
        raise _refuse("REF_CASE_ALIAS", f"{target}: no entry is named exactly {name!r}", selector)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
    except OSError as error:
        raise _refuse("REF_MISSING", f"{target}: {error}", selector) from None
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (walked.st_dev, walked.st_ino) \
                or not stat.S_ISREG(opened.st_mode):
            raise _refuse("REF_LINK", f"{target} changed between the walk and the open", selector)
        if opened.st_nlink != 1:
            raise _refuse("REF_HARDLINK", f"{target} has {opened.st_nlink} links", selector)
        if opened.st_size > limit:
            raise _refuse("REF_TOO_LARGE", f"{target} is {opened.st_size} bytes > {limit}",
                          selector)
        chunks, total = [], 0
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise _refuse("REF_TOO_LARGE", f"{target} exceeds {limit} bytes", selector)
            chunks.append(chunk)
        return b"".join(chunks), (opened.st_dev, opened.st_ino)
    finally:
        os.close(descriptor)


def _walk(base: Path, segments: list[str], selector: str) -> Path:
    here = base
    for segment in segments[:-1]:
        child = here / segment
        try:
            info = os.lstat(child)
        except OSError:
            raise _refuse("REF_MISSING", f"{child} does not exist", selector) from None
        if _is_link(info):
            raise _refuse("REF_LINK", f"{child} is a link or reparse point", selector)
        if not stat.S_ISDIR(info.st_mode):
            raise _refuse("REF_NOT_REGULAR", f"{child} is not a directory", selector)
        if segment not in os.listdir(here):
            raise _refuse("REF_CASE_ALIAS", f"{child}: no entry is named exactly {segment!r}",
                          selector)
        here = child
    return here


class Resolver:
    """Resolves every reference of one envelope against the envelope's directory."""

    def __init__(self, base: Path) -> None:
        self.base = Path(base)
        self._by_path: dict[str, tuple[bytes, tuple]] = {}
        self._by_object: dict[tuple, str] = {}

    def read(self, ref: dict, *, limit: int, selector: str) -> Snapshot:
        path = ref["path"]
        segments = check_relpath(path, selector)
        if path in self._by_path:           # R5: one path, one read, one byte string
            data, _ = self._by_path[path]
        else:
            parent = _walk(self.base, segments, selector)
            data, identity = read_regular(parent, segments[-1], limit, selector)
            other = self._by_object.get(identity)
            if other is not None:
                raise _refuse("REF_ALIAS", f"{path!r} is the same file as {other!r}", selector)
            self._by_path[path] = (data, identity)
            self._by_object[identity] = path
        snapshot = Snapshot(path, data)
        declared = ref.get("sha256")
        if declared is not None and declared != snapshot.sha256:
            raise _refuse("REF_DIGEST_MISMATCH",
                          f"{path!r}: declared {declared}, read {snapshot.sha256}", selector)
        return snapshot
