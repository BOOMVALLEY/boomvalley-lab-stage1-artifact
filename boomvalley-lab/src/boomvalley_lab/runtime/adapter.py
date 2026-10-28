"""The adapter contract: facts in, facts out — never verdicts.

    Adapter.intended       the execution identity the runner INTENDS to call
                           {model_identity, adapter_provenance} (journaled in
                           the intent, never copied into the actual record)
    Adapter.max_attempts   must be 1. An adapter (or a provider library under
                           it) that may realise a request more than once is
                           refused before any session opens: MVP has one
                           attempt per execution record and no hidden retry.
    Adapter.call(request) -> AdapterResponse
                           performs the call; returns the content and the
                           ACTUAL execution identity it answered with (R37)

Adapters do not decide eligibility, write custody, touch the schedule, create
cells or retry. The runtime owns orchestration.

The request payload is built by the experiment from the locked execution
record ALONE (`RequestBuilder(record)`); the runtime gives it no channel to
earlier responses. One adapter call per attempt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.custody.derivation import check_derivation
from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.identity.kinds import RequestIdentity

REQUEST_SCHEMA = "boomvalley-lab-request-1"

RequestBuilder = Callable[[ExecutionRecord], Mapping[str, Any]]


@dataclass(frozen=True)
class AdapterRequest:
    record: str
    identity: RequestIdentity
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class AdapterResponse:
    content: Any
    model_identity: Any
    adapter_provenance: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)
    #: set only when a derivation produced this content (R41): the parent it
    #: was made from and the transform that ran. Facts, never a claim.
    derivation: Mapping[str, Any] | None = None


class ResponseRejected(Exception):
    """The adapter returned something that is not a valid response."""


def validate_response(response: Any) -> AdapterResponse:
    if not isinstance(response, AdapterResponse):
        raise ResponseRejected(f"not an AdapterResponse: {type(response).__name__}")
    if not isinstance(response.content, (bytes, bytearray)):
        raise ResponseRejected("response content is not bytes")
    for name in ("model_identity", "adapter_provenance"):
        value = getattr(response, name)
        if not isinstance(value, str) or not value.strip():
            raise ResponseRejected(f"response {name} is missing or empty")
    if response.derivation is not None:
        try:
            check_derivation(response.derivation, "response derivation")
        except EvidenceError as error:
            raise ResponseRejected(str(error)) from error
    return response


def request_document(record: ExecutionRecord, payload: Mapping[str, Any]) -> dict:
    """The canonical request actually sent: the record and the built payload."""
    return {"schema": REQUEST_SCHEMA, "record": record.key, "payload": dict(payload)}


@runtime_checkable
class Adapter(Protocol):
    intended: Mapping[str, str]
    max_attempts: int

    def call(self, request: AdapterRequest) -> AdapterResponse: ...
