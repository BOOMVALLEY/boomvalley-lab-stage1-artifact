"""Link-refusing, handle-based, single-read file access (MANIFEST_CONTRACT §6.2).

Every file is opened once, relative to a directory handle that is held for the whole
check, without following links; its bytes are read through that handle and never
re-read. Two conforming mechanisms:

- POSIX: `openat(parent, seg, O_NOFOLLOW)` along the path; exact name by scanning the
  parent directory and matching the inode.
- Windows: path-based `CreateFileW` with `FILE_FLAG_OPEN_REPARSE_POINT`, every ancestor
  handle from the base held open without `FILE_SHARE_DELETE` (so no ancestor can be
  renamed or removed), each handle checked for a reparse tag, and the exact final name
  confirmed with `GetFinalPathNameByHandleW`.

A platform offering neither raises PLATFORM_NO_SAFE_RESOLUTION (exit 5).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from gndcrw.codes import Error
from gndcrw.errors import CodedError


@dataclass(frozen=True)
class FileRead:
    data: bytes
    identity: tuple[int, int]      # (device / volume, inode / file index), as os.stat reports


def _refuse(code: Error, message_key: str, **params: object) -> CodedError:
    return CodedError(code, message_key, **params)


# --------------------------------------------------------------------------- Windows

if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _k32.CreateFileW
    _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _k32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]

    class _ByHandleInfo(ctypes.Structure):
        _fields_ = [("dwFileAttributes", wintypes.DWORD),
                    ("ftCreationTime", wintypes.FILETIME),
                    ("ftLastAccessTime", wintypes.FILETIME),
                    ("ftLastWriteTime", wintypes.FILETIME),
                    ("dwVolumeSerialNumber", wintypes.DWORD),
                    ("nFileSizeHigh", wintypes.DWORD),
                    ("nFileSizeLow", wintypes.DWORD),
                    ("nNumberOfLinks", wintypes.DWORD),
                    ("nFileIndexHigh", wintypes.DWORD),
                    ("nFileIndexLow", wintypes.DWORD)]

    _GetInfo = _k32.GetFileInformationByHandle
    _GetInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleInfo)]
    _GetFinalPath = _k32.GetFinalPathNameByHandleW
    _GetFinalPath.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    _GetFinalPath.restype = wintypes.DWORD

    _INVALID = wintypes.HANDLE(-1).value
    _GENERIC_READ = 0x80000000
    _FILE_READ_ATTRIBUTES = 0x80
    _SHARE_READ_WRITE = 0x1 | 0x2                   # never FILE_SHARE_DELETE
    _OPEN_EXISTING = 3
    _FLAG_BACKUP = 0x02000000
    _FLAG_REPARSE = 0x00200000
    _ATTR_DIRECTORY = 0x10
    _ATTR_REPARSE = 0x400
    _NOT_FOUND = (2, 3, 123, 161)                   # file / path not found, bad name, bad path

    class _Handle:
        def __init__(self, path: str, directory: bool) -> None:
            flags = _FLAG_REPARSE | (_FLAG_BACKUP if directory else 0)
            access = _FILE_READ_ATTRIBUTES if directory else _GENERIC_READ
            handle = _CreateFileW(path, access, _SHARE_READ_WRITE, None, _OPEN_EXISTING, flags,
                                  None)
            if handle in (None, _INVALID):
                self.handle = None
                self.error = ctypes.get_last_error()
                return
            self.handle, self.error = handle, 0
            info = _ByHandleInfo()
            if not _GetInfo(handle, ctypes.byref(info)):
                self.close()
                raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle failed")
            self.attributes = info.dwFileAttributes
            self.links = info.nNumberOfLinks
            self.size = (info.nFileSizeHigh << 32) | info.nFileSizeLow

        def final_name(self) -> str:
            buffer = ctypes.create_unicode_buffer(32768)
            length = _GetFinalPath(self.handle, buffer, 32768, 0)
            if length == 0 or length >= 32768:
                raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
            return buffer.value.replace("/", "\\").rsplit("\\", 1)[-1]

        def close(self) -> None:
            if self.handle not in (None, _INVALID):
                _CloseHandle(self.handle)
            self.handle = None

    class Base:
        """The held directory handle every reference resolves against."""

        def __init__(self, directory: str) -> None:
            self.path = os.path.abspath(directory)
            self.held: list[_Handle] = []
            handle = _Handle(self.path, directory=True)
            if handle.handle is None:
                raise _refuse(Error.MANIFEST_NOT_FOUND, "base.cannot_open", path=self.path)
            self.held.append(handle)

        def read(self, segments: list[str], limit: int, codes: dict) -> FileRead:
            """Open `segments` below the base (no links anywhere), check, read once."""
            path, ref = self.path, "/".join(segments)
            for segment in segments[:-1]:
                path = os.path.join(path, segment)
                directory = _Handle(path, directory=True)
                if directory.handle is None:
                    raise _refuse(codes["missing"], "ref.no_such_directory", ref=ref)
                self.held.append(directory)          # held without FILE_SHARE_DELETE
                if directory.attributes & _ATTR_REPARSE:
                    raise _refuse(codes["link"], "ref.link_or_reparse", ref=ref)
                if not directory.attributes & _ATTR_DIRECTORY:
                    raise _refuse(codes["not_regular"], "ref.not_directory", ref=ref)
                if directory.final_name() != segment:
                    raise _refuse(codes["case"], "ref.case", ref=ref)
            path = os.path.join(path, segments[-1])
            handle = _Handle(path, directory=False)
            if handle.handle is None:
                if handle.error in _NOT_FOUND:
                    raise _refuse(codes["missing"], "ref.no_such_file", ref=ref)
                if handle.error == 5:                  # access denied: e.g. a directory
                    raise _refuse(codes["not_regular"], "ref.not_readable", ref=ref)
                raise _refuse(codes["missing"], "ref.cannot_open", ref=ref,
                              error=handle.error)
            try:
                if handle.attributes & _ATTR_REPARSE:
                    raise _refuse(codes["link"], "ref.link_or_reparse", ref=ref)
                if handle.attributes & _ATTR_DIRECTORY:
                    raise _refuse(codes["not_regular"], "ref.not_regular_file", ref=ref)
                if handle.final_name() != segments[-1]:
                    raise _refuse(codes["case"], "ref.case", ref=ref)
                if handle.links != 1:
                    raise _refuse(codes["hardlink"], "ref.hardlinks", ref=ref,
                                  links=handle.links)
                fd = msvcrt.open_osfhandle(handle.handle, os.O_RDONLY | os.O_BINARY)
                handle.handle = None                   # the descriptor owns it now
                try:
                    return _read_fd(fd, limit)
                finally:
                    os.close(fd)
            finally:
                handle.close()

        def close(self) -> None:
            for handle in reversed(self.held):
                handle.close()
            self.held.clear()

    def platform_supported() -> bool:
        return True

# --------------------------------------------------------------------------- POSIX

else:
    import errno
    import stat

    def platform_supported() -> bool:
        return (os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
                and hasattr(os, "O_DIRECTORY") and os.listdir in os.supports_fd)

    class Base:
        def __init__(self, directory: str) -> None:
            try:
                self.fd = os.open(directory or ".", os.O_RDONLY | os.O_DIRECTORY)
            except OSError as exc:
                raise _refuse(Error.MANIFEST_NOT_FOUND, "base.cannot_open_error",
                              error=exc) from None
            self.held = [self.fd]

        def read(self, segments: list[str], limit: int, codes: dict) -> FileRead:
            parent = self.fd
            label = "/".join(segments)
            for index, segment in enumerate(segments):
                last = index == len(segments) - 1
                flags = os.O_RDONLY | os.O_NOFOLLOW | (0 if last else os.O_DIRECTORY)
                try:
                    fd = os.open(segment, flags, dir_fd=parent)
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise _refuse(codes["link"], "ref.link", ref=label) from None
                    if exc.errno in (errno.ENOTDIR,):
                        raise _refuse(codes["link"], "ref.link_or_not_directory",
                                      ref=label) from None
                    if exc.errno == errno.ENOENT:
                        raise _refuse(codes["missing"], "ref.no_such_file", ref=label) from None
                    raise _refuse(codes["missing"], "ref.os_error", ref=label, error=exc) from None
                info = os.fstat(fd)
                entries = os.listdir(parent)
                if segment not in entries or os.stat(segment, dir_fd=parent,
                                                     follow_symlinks=False).st_ino != info.st_ino:
                    os.close(fd)
                    raise _refuse(codes["case"], "ref.name_differs", ref=label)
                if not last:
                    self.held.append(fd)
                    parent = fd
                    continue
                try:
                    if not stat.S_ISREG(info.st_mode):
                        raise _refuse(codes["not_regular"], "ref.not_regular_file", ref=label)
                    if info.st_nlink != 1:
                        raise _refuse(codes["hardlink"], "ref.hardlinks", ref=label,
                                      links=info.st_nlink)
                    return _read_fd(fd, limit)
                finally:
                    os.close(fd)
            raise AssertionError("unreachable")

        def close(self) -> None:
            for fd in reversed(self.held):
                os.close(fd)
            self.held.clear()


def _read_fd(fd: int, limit: int) -> FileRead:
    """Read at most `limit + 1` bytes through `fd`; identity from the same descriptor."""
    info = os.fstat(fd)
    chunks, remaining = [], limit + 1
    while remaining > 0:
        chunk = os.read(fd, min(remaining, 1 << 20))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return FileRead(b"".join(chunks), (info.st_dev, info.st_ino))


def open_base(directory: str) -> Base:
    if not platform_supported():
        raise _refuse(Error.PLATFORM_NO_SAFE_RESOLUTION, "platform.no_safe_open")
    return Base(directory)
