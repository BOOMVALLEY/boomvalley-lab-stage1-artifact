"""The provider plugins this installation ships (T4-010, P03 / P05).

A provider is the transport behind the request/provider boundary: it takes the
request-2 the kernel prepared, persisted and journaled, performs exactly one
external call inside the engine's adapter window and returns the bytes, the
model identity and the provenance the server stated.  It renders nothing,
parses no proposal, chooses no model, option or seed, retries nothing and
writes no evidence.

    bvl.openai-chat-adapter:1   ``providers.openai_chat``   one chat completion
                                                            of an OpenAI-compatible
                                                            HTTP server

``PROVIDERS`` is all the lifecycle reads: plugin identity -> adapter class.  A
class states its own P03 descriptor facts and config:

    ERF            the profile option names it consumes (its coverage contract)
    EXTERNAL_IO    whether it leaves the process
    STOCHASTIC     whether the same request may be answered differently
    from_config    plugin config -> adapter (an empty config -> unconfigured)
    require_profile  (optional) holds an ExecutionProfile to the adapter before
                   a run exists

The plugin catalog registers every entry as a ``PluginType.ADAPTER`` without
naming one, so adding a provider is a module here and a line in this table - no
kernel, lifecycle, verifier or CLI change.  A provider reaches the kernel's
request / adapter contract types (``kernel.request``, ``kernel.adapter2``) and
nothing else of the product.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from boomvalley_lab.providers.openai_chat import OPENAI_CHAT_ADAPTER, OpenAIChatAdapterV1

PROVIDERS: Mapping[str, Any] = MappingProxyType({OPENAI_CHAT_ADAPTER: OpenAIChatAdapterV1})

__all__ = ["PROVIDERS"]
