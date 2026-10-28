"""Deterministic fake adapters. No network, no provider, no randomness.

    FakeAdapter(model, provenance, respond)     normal success; `respond(payload)`
                                                returns the content bytes
      report_as=(model, provenance)             answers with an identity other
                                                than the intended one; a
                                                callable(request) -> (model,
                                                provenance) varies it per record
      fail_on={record keys}                     raises (outcome unknown)
      malformed_on={record keys}                returns an invalid response
      max_attempts                              declared retry budget (must be 1)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from boomvalley_lab.runtime.adapter import AdapterRequest, AdapterResponse


class FakeProviderError(Exception):
    pass


class FakeAdapter:
    def __init__(
        self,
        model_identity: str,
        adapter_provenance: str,
        respond: Callable[[Mapping[str, Any]], bytes],
        *,
        report_as: tuple[str, str] | None = None,
        fail_on: set[str] | None = None,
        malformed_on: set[str] | None = None,
        max_attempts: int = 1,
        during_call: Callable[[str], None] | None = None,
    ) -> None:
        self.intended = {"model_identity": model_identity,
                         "adapter_provenance": adapter_provenance}
        self._respond = respond
        self._report = report_as or (model_identity, adapter_provenance)
        self._fail_on = fail_on or set()
        self._malformed_on = malformed_on or set()
        self.max_attempts = max_attempts
        self._during_call = during_call
        self.calls: list[str] = []

    def call(self, request: AdapterRequest) -> AdapterResponse:
        self.calls.append(request.record)
        if self._during_call:
            self._during_call(request.record)
        if request.record in self._fail_on:
            raise FakeProviderError(f"provider failed on {request.record}")
        if request.record in self._malformed_on:
            return AdapterResponse(content="not bytes", model_identity="",
                                   adapter_provenance="malformed")
        report = self._report(request) if callable(self._report) else self._report
        return AdapterResponse(content=self._respond(request.payload),
                               model_identity=report[0],
                               adapter_provenance=report[1],
                               metadata={"fake": True})
