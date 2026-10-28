"""Structured diagnostic logging (standard `logging`, no dependency).

stdout belongs to the result renderer alone; this layer never touches it.
Records are JSON lines with a closed set of members:

    ts           UTC RFC 3339, millisecond precision, `Z` suffix
    component    `gndcrw.<module>`
    severity     DEBUG / INFO / WARNING / ERROR / CRITICAL
    message_key  the i18n key of the event (locale-independent)
    status / reason / error   registry codes, when the event has one
    context      safe context only (see SAFE_CONTEXT)
    exc_type, traceback       for exceptions: type and frames, never the message

Redaction is by allowlist: a context member outside SAFE_CONTEXT, or a string
value that is not a short code-like token, is replaced by "[REDACTED]". Error
details, paths, manifest content, request text and exception messages are
never logged.

Sink (CLI only; a library caller configures `logging` itself):
    GNDCRW_LOG_FILE=<path>   append JSON lines there
    GNDCRW_LOG_LEVEL=<name>  threshold (default WARNING); without a file, it
                             sends JSON lines to stderr
Neither set: nothing is emitted.

The stderr sink holds its lines until `release()` (the CLI calls it on exit),
so a user-facing `gndcrw: error: <CODE>: ...` line is always the first stderr
line and diagnostics follow it, at every level. stdout is never involved.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

ROOT = "gndcrw"
LOG_FILE_ENV = "GNDCRW_LOG_FILE"
LOG_LEVEL_ENV = "GNDCRW_LOG_LEVEL"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
REDACTED = "[REDACTED]"
SAFE_CONTEXT = frozenset({"mode", "role", "exit_code", "format", "gate", "locale",
                          "locale_source", "result_version", "finding_count", "field"})
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:/-]{0,64}$")
_SECRET = re.compile(r"(?i)(sk-|ghp_|gho_|xox[bp]-|AKIA|bearer|token|secret|passw|api[_-]?key)")

logging.getLogger(ROOT).addHandler(logging.NullHandler())


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{component}")


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str) and _SAFE_TOKEN.match(value) and not _SECRET.search(value):
        return value
    return REDACTED


def safe_context(context: Mapping[str, Any]) -> dict[str, Any]:
    return {key: (_safe_value(value) if key in SAFE_CONTEXT else REDACTED)
            for key, value in context.items()}


def event(logger: logging.Logger, level: int, message_key: str, *, status: str | None = None,
          reason: str | None = None, error: str | None = None, exc_info: bool = False,
          **context: Any) -> None:
    """Log one structured event. The record message is the key, never free text."""
    codes = {name: str(value) for name, value in
             (("status", status), ("reason", reason), ("error", error)) if value is not None}
    try:
        logger.log(level, message_key, exc_info=exc_info,
                   extra={"gndcrw": {"message_key": message_key, **codes, "context": context}})
    except Exception:  # diagnostics can never change a verdict or an exit code
        pass


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "gndcrw", None) or {"message_key": "log.unstructured"}
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
                          .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "component": record.name,
            "severity": record.levelname,
            "message_key": _safe_value(payload["message_key"]),
        }
        for name in ("status", "reason", "error"):
            if name in payload:
                out[name] = _safe_value(payload[name])
        out["context"] = safe_context(payload.get("context", {}))
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            out["exc_type"] = exc_type.__name__
            out["traceback"] = [{"file": frame.filename.replace("\\", "/").rsplit("/", 1)[-1],
                                 "line": frame.lineno, "function": frame.name}
                                for frame in traceback.extract_tb(tb)]
        return json.dumps(out, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class _QuietMixin:
    """A failing sink never reaches stdout and never changes the exit code."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)  # type: ignore[misc]
        except Exception:  # e.g. a delayed FileHandler whose directory does not exist
            pass

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        pass


class _FileHandler(_QuietMixin, logging.FileHandler):
    pass


class _DeferredStderrHandler(_QuietMixin, logging.Handler):
    """JSON lines for stderr, written by `release()` after the user-facing line."""

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._lines.append(self.format(record) + "\n")
        except Exception:
            pass

    def release(self) -> None:
        lines, self._lines = self._lines, []
        if not lines:
            return
        try:
            sys.stderr.write("".join(lines))
            sys.stderr.flush()
        except Exception:  # an unwritable stderr never changes the exit code
            pass

    def close(self) -> None:
        self.release()
        super().close()


def release() -> None:
    """Write any held stderr diagnostics. Never raises."""
    for handler in logging.getLogger(ROOT).handlers:
        if isinstance(handler, _DeferredStderrHandler):
            handler.release()


def configure(environ: Mapping[str, str]) -> logging.Handler | None:
    """Attach the configured sink to the `gndcrw` logger. Returns the handler, if any."""
    root = logging.getLogger(ROOT)
    for handler in [h for h in root.handlers if getattr(h, "_gndcrw_sink", False)]:
        root.removeHandler(handler)
        handler.close()
    path, level = environ.get(LOG_FILE_ENV), environ.get(LOG_LEVEL_ENV)
    if not path and not level:
        return None
    level = level.upper() if level and level.upper() in LEVELS else "WARNING"
    try:
        handler: logging.Handler = (_FileHandler(path, encoding="utf-8", delay=True) if path
                                    else _DeferredStderrHandler())
    except OSError:
        return None
    handler._gndcrw_sink = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    return handler
