"""K0 actor-adapter contract with pre-intent request preparation.

An adapter prepares the complete scientific request without external side
effects, then performs exactly one engine-authorized external call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from boomvalley_lab.kernel.request import RequestV2


@dataclass(frozen=True)
class ActorResponseV2:
    content: bytes
    model_identity: str
    adapter_provenance: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes):
            raise TypeError("ActorResponseV2.content must be bytes")
        if not self.model_identity:
            raise ValueError("model_identity must be non-empty")
        if not self.adapter_provenance:
            raise ValueError("adapter_provenance must be non-empty")


@runtime_checkable
class ActorAdapterV2(Protocol):
    """One prepared request -> one externally realized response."""

    plugin_identity: str

    def invoke(self, request: RequestV2) -> ActorResponseV2: ...


@dataclass
class FakeAdapterV2:
    """Deterministic spike adapter with externally countable call semantics."""

    response: bytes
    model_identity: str = "fake:model:1"
    adapter_provenance: str = "boomvalley-lab-fake-v2"
    plugin_identity: str = "builtin.fake-adapter-v2:1"
    calls: int = 0

    def invoke(self, request: RequestV2) -> ActorResponseV2:
        del request
        self.calls += 1
        return ActorResponseV2(
            content=self.response,
            model_identity=self.model_identity,
            adapter_provenance=self.adapter_provenance,
        )
