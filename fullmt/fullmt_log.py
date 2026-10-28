"""FULLMT logging — internal diagnostics go to a logger (stderr), never to stdout.

stdout carries only the CLI contract output (result JSON / --quiet line / smoke report).
Imported as a library the "fullmt" logger is silent (NullHandler); a CLI calls configure().
Level: explicit argument > $FULLMT_LOG_LEVEL > WARNING.
"""
from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "fullmt"
LOG_LEVEL_ENV = "FULLMT_LOG_LEVEL"
DEFAULT_LEVEL = "WARNING"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
FORMAT = "%(levelname)s %(name)s: %(message)s"

logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def configure(level: str | None = None) -> logging.Logger:
    """Attach one stderr handler to the fullmt logger (idempotent)."""
    chosen = (level or os.environ.get(LOG_LEVEL_ENV) or DEFAULT_LEVEL).upper()
    if chosen not in LEVELS:
        chosen = DEFAULT_LEVEL
    if hasattr(sys.stderr, "reconfigure"):  # localized text must not depend on the codepage
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, "_fullmt_stderr", False):
            logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._fullmt_stderr = True
    handler.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(handler)
    logger.setLevel(chosen)
    logger.propagate = False
    return logger
