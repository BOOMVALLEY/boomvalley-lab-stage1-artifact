"""Package limitations (#88, C1 C2b): a closed `code` plus a human `free_text`.

A limitation states what the package does NOT establish. From
`boomvalley-epc-manifest-3` on, each one has two layers:

    code       a closed, stable English identifier (`CODES`, registered as the
               LIMITATION namespace of `core.codes`). It is the only thing a machine
               decides on: which limitations are stated, and what they mean.
    free_text  a human explanation. It may say more than the code, but no rule reads
               it: it is never parsed, compared or used for a verdict. It is checked
               only as a string (`free_text_problems`), so that it is bounded.

    "limitations": [{"code": "<CODE>", "free_text": "<text>"}, ...]   sorted by code

The same code with another free_text means the same thing: every rule verdict and
every code set this module returns is identical (the package identity differs, as it
does for any byte of the manifest - free_text is sealed, not interpreted).

Rules (both readers; the consumer re-derives them without importing this module):

    LIM-001  the limitation list is well formed and closed. -3: a list of exactly
             {code, free_text} objects; code a registered string (an unknown or
             missing code is refused, never skipped); free_text a string of 1..
             FREE_TEXT_MAX_CHARS code points, not blank, without control characters;
             one entry per code (the same code twice is refused whether or not the
             free_text agrees - a duplicate is never merged or resolved by order);
             sorted by code. -1 / -2: a list of registered code strings, sorted and
             unique (P25 unknown token, T15 duplicate token: refused).
    LIM-002  the limitations the evidence establishes are stated: every STANDING code;
             DATASET_NOT_ADMITTED iff no dataset is admitted; exactly the Input Lock
             preflight record's GNDCRW_* limitations (none for a run without one);
             MODEL_VERSION_NOT_PINNED for a run that is not INPUT_LOCKED.
             JOURNAL_TORN_TAIL is JRN-004's and REQUEST_* are REQ-001's; a
             contradictory pair (REQUEST_CONTENT_WITHHELD with REQUEST_UNAVAILABLE) is
             refused there.

A limitation is not provenance. GNDCRW_TOOL_CODE_SELF_REPORTED says that
`tool.code_digest` is GNDCRW's self-report; the provenance member classifies that
value as self-reported on its own (PRV-001..003). The limitation being stated is a
disclosure, never a verification claim, and neither reading is derived from the
other.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

#: code -> the free_text this producer writes (English; never read by a rule)
FREE_TEXT: dict[str, str] = {
    "NOT_SIGNED": "The package is sealed by digests only; no signature binds it to a "
                  "producer key.",
    "RUN_ID_LEGACY_LABEL": "The run id is a producer-chosen label, not a generated unique "
                           "identifier.",
    "PRODUCT_INTERNAL_STEPS_ATTESTED": "Some eligibility steps are product-internal: the "
                                       "producer attests them and a consumer cannot recompute "
                                       "them.",
    "CLAIMS_NOT_EMITTED": "The package carries evidence, not scientific claims; no claim is "
                          "emitted.",
    "PROVENANCE_PACKAGE_TIME_ONLY": "Environment provenance is recorded when the package is "
                                    "written, not when the run executed.",
    "DATASET_NOT_ADMITTED": "The evidence does not admit a dataset; none is packaged.",
    "REQUEST_CONTENT_WITHHELD": "The request content is deliberately not published; only its "
                                "digest and size are bound.",
    "REQUEST_UNAVAILABLE": "The request content was not retained and cannot be rebuilt.",
    "MODEL_VERSION_NOT_PINNED": "The model version used for execution is not pinned.",
    "JOURNAL_TORN_TAIL": "The journal ends in an unterminated tail after the last "
                         "acknowledged line.",
    "GNDCRW_DECLARATION_NOT_DERIVED_FROM_EXPERIMENT": "The GNDCRW declaration, catalog and "
                                                      "pair were selected by the author, not "
                                                      "derived from the experiment.",
    "GNDCRW_EXTERNAL_SUBJECT_PROVIDER_ATTESTED": "The external subject GNDCRW checked is the "
                                                 "producer's attestation of the contract "
                                                 "identity.",
    "GNDCRW_TOOL_CODE_SELF_REPORTED": "The GNDCRW tool code digest is GNDCRW's self-report; "
                                      "it is disclosed, not verified.",
}
CODES = frozenset(FREE_TEXT)

# the codes the writer and the rules name (the other rules key on these, never on text)
DATASET_NOT_ADMITTED = "DATASET_NOT_ADMITTED"
MODEL_VERSION_NOT_PINNED = "MODEL_VERSION_NOT_PINNED"
JOURNAL_TORN_TAIL = "JOURNAL_TORN_TAIL"

#: limitations every package of this producer states (§24 item 11)
STANDING = ("NOT_SIGNED", "RUN_ID_LEGACY_LABEL", "PRODUCT_INTERNAL_STEPS_ATTESTED",
            "CLAIMS_NOT_EMITTED", "PROVENANCE_PACKAGE_TIME_ONLY")
#: the limitations an Input Lock's preflight record carries into the package
PREFLIGHT_PREFIX = "GNDCRW_"

#: the free_text bound (code points): a human note, not a document
FREE_TEXT_MAX_CHARS = 1024
ENTRY_MEMBERS = frozenset({"code", "free_text"})

# closed LIM-001 / LIM-002 reason tokens (the text after the token is diagnostic only)
NOT_A_LIST = "LIMITATIONS_NOT_A_LIST"
ENTRY_INVALID = "LIMITATION_ENTRY_INVALID"
CODE_MISSING = "LIMITATION_CODE_MISSING"
CODE_UNKNOWN = "LIMITATION_CODE_UNKNOWN"
FREE_TEXT_INVALID = "LIMITATION_FREE_TEXT_INVALID"
DUPLICATE = "LIMITATION_DUPLICATE"
NOT_SORTED = "LIMITATIONS_NOT_SORTED"
NOT_STATED = "LIMITATION_NOT_STATED"
NOT_ESTABLISHED = "LIMITATION_NOT_ESTABLISHED"

def entry(code: str) -> dict:
    """The -3 entry this producer writes for `code` (a registered code only)."""
    if code not in CODES:
        raise ValueError(f"{code!r} is not a registered limitation code")
    return {"code": code, "free_text": FREE_TEXT[code]}


def entries(codes: Iterable[str]) -> list[dict]:
    return [entry(code) for code in sorted(set(codes))]


def codes(limitations: Any, *, structured: bool) -> list[str]:
    """The codes stated, for the rules that key on a code (JRN-004, REQ-001). Lenient
    on shape - LIM-001 is where a malformed list is refused - and blind to free_text."""
    if not isinstance(limitations, list):
        return []
    if structured:
        return [item["code"] for item in limitations
                if isinstance(item, dict) and isinstance(item.get("code"), str)]
    return [item for item in limitations if isinstance(item, str)]


def free_text_problems(text: Any) -> list[str]:
    if not isinstance(text, str):
        return [f"free_text is a {type(text).__name__}, not a string"]
    if not text.strip():
        return ["free_text is empty"]
    if len(text) > FREE_TEXT_MAX_CHARS:
        return [f"free_text has {len(text)} code points (limit {FREE_TEXT_MAX_CHARS})"]
    if any(unicodedata.category(c) == "Cc" for c in text):
        return ["free_text contains a control character"]
    return []


def problems(limitations: Any, *, structured: bool) -> list[str]:
    """LIM-001: the limitation list is well formed and every code is closed."""
    if not isinstance(limitations, list):
        return [f"{NOT_A_LIST}: limitations is a {type(limitations).__name__}"]
    found: list[str] = []
    stated: list[str] = []
    for index, item in enumerate(limitations):
        where = f"limitations[{index}]"
        if structured:
            if not isinstance(item, dict):
                found.append(f"{ENTRY_INVALID}: {where} is not an object")
                continue
            if "code" not in item:
                found.append(f"{CODE_MISSING}: {where} has no code")
            extra = sorted(set(item) - ENTRY_MEMBERS)
            if extra:
                found.append(f"{ENTRY_INVALID}: {where} has unknown members {extra}")
            if "free_text" not in item:
                found.append(f"{ENTRY_INVALID}: {where} has no free_text")
            else:
                found += [f"{FREE_TEXT_INVALID}: {where}: {p}"
                          for p in free_text_problems(item["free_text"])]
            if "code" not in item:
                continue
            code = item["code"]
        else:
            code = item
        if not isinstance(code, str):
            found.append(f"{CODE_UNKNOWN}: {where} code is a {type(code).__name__}")
            continue
        if code not in CODES:
            found.append(f"{CODE_UNKNOWN}: {where} {code!r} is not a registered limitation")
        stated.append(code)
    for code in sorted({c for c in stated if stated.count(c) > 1}):
        found.append(f"{DUPLICATE}: {code} is stated {stated.count(code)} times")
    if stated != sorted(stated):
        found.append(f"{NOT_SORTED}: limitations are not in code order")
    return found


def expected_problems(stated: Sequence[str], *, dataset_admitted: bool, locked: bool,
                      preflight: Sequence[str] | None) -> list[str]:
    """LIM-002: the limitations the evidence establishes are the ones stated."""
    have = set(stated)
    found = [f"{NOT_STATED}: {code}" for code in STANDING if code not in have]
    if dataset_admitted == (DATASET_NOT_ADMITTED in have):
        found.append(f"{NOT_STATED if not dataset_admitted else NOT_ESTABLISHED}: "
                     f"{DATASET_NOT_ADMITTED} for a run whose dataset is "
                     f"{'admitted' if dataset_admitted else 'not admitted'}")
    gndcrw = {c for c in have if c.startswith(PREFLIGHT_PREFIX)}
    record = set(preflight or ())
    found += [f"{NOT_STATED}: {c} (the Input Lock preflight record states it)"
              for c in sorted(record - gndcrw)]
    found += [f"{NOT_ESTABLISHED}: {c} (no Input Lock preflight record states it)"
              for c in sorted(gndcrw - record)]
    if not locked and MODEL_VERSION_NOT_PINNED not in have:
        found.append(f"{NOT_STATED}: {MODEL_VERSION_NOT_PINNED} for a run that is not "
                     "INPUT_LOCKED")
    return found


def reading(limitations: Any, *, structured: bool) -> dict:
    """What a reader may rely on: the codes. free_text is carried for people only."""
    stated = sorted(set(codes(limitations, structured=structured)))
    return {"codes": stated,
            "free_text": ({item["code"]: item.get("free_text") for item in limitations
                           if isinstance(item, dict) and isinstance(item.get("code"), str)}
                          if structured and isinstance(limitations, list) else None)}


__all__ = ["CODES", "FREE_TEXT", "STANDING", "codes", "entries", "entry",
           "expected_problems", "free_text_problems", "problems", "reading"]
