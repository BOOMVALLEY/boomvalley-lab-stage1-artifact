"""A local, deterministic adapter — no provider, no network, no credentials.

It exists so the CLI (and the shipped example) can execute a real run end to
end on any machine: it answers each request with the canonical bytes of the
request payload, and reports the identity it was configured with. Every
guarantee the product makes about execution evidence is exercised; none of
them depend on a model having been called.

It is not a stand-in for a provider in a real experiment: a design that
declares an execution expectation will see exactly this identity, which is the
point — what answered is recorded, whatever it was.
"""

from __future__ import annotations

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.runtime.adapter import AdapterRequest, AdapterResponse

LOCAL_PROVENANCE = "boomvalley-lab-local-1"


class LocalAdapter:
    def __init__(self, model_identity: str = "local-echo",
                 adapter_provenance: str = LOCAL_PROVENANCE) -> None:
        self.intended = {"model_identity": model_identity,
                         "adapter_provenance": adapter_provenance}
        self.max_attempts = 1

    def call(self, request: AdapterRequest) -> AdapterResponse:
        return AdapterResponse(
            content=canonical_bytes({"record": request.record, "payload": dict(request.payload)}),
            model_identity=self.intended["model_identity"],
            adapter_provenance=self.intended["adapter_provenance"],
        )
