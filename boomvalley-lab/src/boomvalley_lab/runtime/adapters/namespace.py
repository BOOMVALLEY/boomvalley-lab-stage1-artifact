"""Adapter kind <-> provenance namespace <-> model identity form (#176, BVVH #174 MAJOR-1).

An execution identity is a pair {model_identity, adapter_provenance}. Which pairs
an adapter kind may state - as the identity a profile intends, and as the identity
a run's evidence says answered - is fixed by the provider contract of that kind:

    local    adapter_provenance  exactly "boomvalley-lab-local-1"
             model_identity      any non-empty label that is NOT a pinned model
                                 digest (no "@sha256:"): the local adapter calls no
                                 model, so it can never stand for one
    ollama   adapter_provenance  "boomvalley-lab-ollama-1;ollama=<version>"
             model_identity      "<adapter.ollama.model>@sha256:<64 hex>"

and, after execution, every actual execution of a run is the identity its locked
profile intends: the local adapter answers with exactly what it was configured
with, and the Ollama adapter refuses to call a server whose resolved identity is
not the pinned one (`OLLAMA_IDENTITY_MISMATCH`, before `POST /api/chat`), so an
actual identity other than the intended one is evidence that something else
answered (`ACTUAL_EXECUTION_NOT_INTENDED`).

`profile.check_profile` applies `intended_problems` before any model call (I3); the
Input Lock verification applies `actual_problems` to the sealed evidence (ILV-15),
so a producer's self-report is checked again by every reader.

What this does not establish (NOT_EVIDENCED, BVVH #174 NE-1 / NE-2): that a local
Ollama server tells the truth about its own identity or output, or applies the
options it was sent. The namespace is a contract on what BVL states, not an
attestation of the server.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

LOCAL_PROVENANCE = "boomvalley-lab-local-1"
OLLAMA_PROVENANCE = "boomvalley-lab-ollama-1"

#: closed reason codes (each problem is (code, detail))
PROVENANCE_NAMESPACE_MISMATCH = "ADAPTER_PROVENANCE_NAMESPACE_MISMATCH"
MODEL_IDENTITY_FORMAT_MISMATCH = "ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH"
ACTUAL_EXECUTION_NOT_INTENDED = "ACTUAL_EXECUTION_NOT_INTENDED"
CODES = (PROVENANCE_NAMESPACE_MISMATCH, MODEL_IDENTITY_FORMAT_MISMATCH,
         ACTUAL_EXECUTION_NOT_INTENDED)

_OLLAMA_PROVENANCE = re.compile(re.escape(OLLAMA_PROVENANCE) + r";ollama=[^\s;]+")
_PINNED = re.compile(r"@sha256:", re.IGNORECASE)
_DIGEST = r"@sha256:[0-9a-f]{64}"


def _ollama_model(profile_adapter: Mapping[str, Any]) -> str | None:
    config = profile_adapter.get("ollama")
    model = config.get("model") if isinstance(config, Mapping) else None
    return model if isinstance(model, str) and model else None


def identity_problems(kind: Any, identity: Mapping[str, Any], *,
                      ollama_model: str | None = None) -> list[tuple[str, str]]:
    """Is `identity` one an adapter of `kind` may state? [] = yes."""
    model, provenance = identity.get("model_identity"), identity.get("adapter_provenance")
    if not isinstance(model, str) or not isinstance(provenance, str):
        return [(MODEL_IDENTITY_FORMAT_MISMATCH, "model_identity / adapter_provenance are "
                 "not strings")]
    problems: list[tuple[str, str]] = []
    if kind == "local":
        if provenance != LOCAL_PROVENANCE:
            problems.append((PROVENANCE_NAMESPACE_MISMATCH,
                             f"adapter kind 'local' states adapter_provenance {provenance!r}; "
                             f"its namespace is exactly {LOCAL_PROVENANCE!r}"))
        if _PINNED.search(model):
            problems.append((MODEL_IDENTITY_FORMAT_MISMATCH,
                             f"adapter kind 'local' states model_identity {model!r}, a pinned "
                             "model digest; the local adapter calls no model"))
    elif kind == "ollama":
        if not _OLLAMA_PROVENANCE.fullmatch(provenance):
            problems.append((PROVENANCE_NAMESPACE_MISMATCH,
                             f"adapter kind 'ollama' states adapter_provenance {provenance!r}; "
                             f"its namespace is '{OLLAMA_PROVENANCE};ollama=<version>'"))
        form = (re.escape(ollama_model) if ollama_model else r"[^@\s]+") + _DIGEST
        if not re.fullmatch(form, model):
            expected = ollama_model or "<model>"
            problems.append((MODEL_IDENTITY_FORMAT_MISMATCH,
                             f"adapter kind 'ollama' states model_identity {model!r}; its form "
                             f"is '{expected}@sha256:<64 hex>'"))
    else:
        problems.append((PROVENANCE_NAMESPACE_MISMATCH, f"adapter kind {kind!r} has no "
                         "provenance namespace"))
    return problems


def intended_problems(profile_adapter: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Pre-execution: the identity a profile's adapter intends is in its kind's namespace."""
    return identity_problems(profile_adapter.get("kind"), profile_adapter,
                             ollama_model=_ollama_model(profile_adapter))


def actual_problems(profile_adapter: Mapping[str, Any],
                    actual: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Post-execution: one actual execution against the locked profile's adapter."""
    problems = identity_problems(profile_adapter.get("kind"), actual,
                                 ollama_model=_ollama_model(profile_adapter))
    intended = {k: profile_adapter.get(k) for k in ("model_identity", "adapter_provenance")}
    stated = {k: actual.get(k) for k in ("model_identity", "adapter_provenance")}
    if stated != intended:
        problems.append((ACTUAL_EXECUTION_NOT_INTENDED,
                         f"actual execution {stated} is not the locked adapter's intended "
                         f"identity {intended}"))
    return problems


__all__ = ["ACTUAL_EXECUTION_NOT_INTENDED", "CODES", "LOCAL_PROVENANCE",
           "MODEL_IDENTITY_FORMAT_MISMATCH", "OLLAMA_PROVENANCE",
           "PROVENANCE_NAMESPACE_MISMATCH", "actual_problems", "identity_problems",
           "intended_problems"]
