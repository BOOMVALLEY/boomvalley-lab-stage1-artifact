"""FULLMT i18n — human-facing text only (CLI help, stderr diagnostics, report prose).

Resources: locales/<locale>.json, a flat {key: template} map with str.format fields.
Locale: explicit argument > $FULLMT_LOCALE > en-US. Lookup falls back to en-US, then to
the key itself, so a missing translation never fails a run. Codes, statuses and rule ids
are never translated: they are passed in as format fields.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = ("en-US", "ko-KR")
LOCALE_ENV = "FULLMT_LOCALE"

_active = DEFAULT_LOCALE


def resolve_locale(requested: str | None = None) -> str:
    """The supported locale for a request ('ko', 'ko_KR', 'ko-KR.UTF-8' -> ko-KR)."""
    raw = requested or os.environ.get(LOCALE_ENV) or DEFAULT_LOCALE
    tag = raw.split(".")[0].replace("_", "-").lower()
    for locale in SUPPORTED_LOCALES:
        if tag in (locale.lower(), locale.split("-")[0].lower()):
            return locale
    return DEFAULT_LOCALE


def set_locale(requested: str | None = None) -> str:
    global _active
    _active = resolve_locale(requested)
    return _active


def get_locale() -> str:
    return _active


@lru_cache(maxsize=None)
def catalog(locale: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{locale}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def t(key: str, locale: str | None = None, **fields) -> str:
    """Localized text for key; falls back to en-US, then to the key."""
    locale = locale or _active
    template = catalog(locale).get(key)
    if template is None:
        template = catalog(DEFAULT_LOCALE).get(key, key)
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return template
