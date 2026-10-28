"""Durable content-addressed storage for request-2 documents.

The scientific request is persisted before an external call intent is recorded.
The member name is storage only; RequestIdentity is the scientific identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import EvidenceError, ExecutionError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.identity.kinds import RequestIdentity
from boomvalley_lab.kernel.request import RequestV2


@dataclass(frozen=True)
class RequestRefV2:
    name: str
    identity: RequestIdentity
    size: int

    def document(self) -> dict:
        return {
            "schema": "boomvalley-lab-request-ref-2",
            "name": self.name,
            "identity": self.identity.document(),
            "size": self.size,
        }


class RequestStoreV2:
    def __init__(self, run_directory: Path) -> None:
        self.root = Path(run_directory) / "requests-v2"

    def _name(self, identity: RequestIdentity) -> str:
        return f"request-{identity.digest.hex}.json"

    def path(self, ref: RequestRefV2) -> Path:
        return self.root / ref.name

    def put(self, request: RequestV2) -> RequestRefV2:
        data = canonical_bytes(request.document())
        identity = request.identity()
        name = self._name(identity)
        ref = RequestRefV2(name, identity, len(data))

        self.root.mkdir(parents=True, exist_ok=True)
        final = self.root / name

        if final.exists():
            held = final.read_bytes()
            if held != data:
                raise EvidenceError(
                    f"request-2 member {name} exists with bytes that contradict its identity"
                )
            return ref

        partial = self.root / f".{name}.partial"
        # A partial without its final member is the leftover of a crash before
        # CALL_INTENT_RECORDED: nothing references it (single writer, R8), so
        # it is discarded rather than blocking a pre-intent resume (T0-010).
        partial.unlink(missing_ok=True)
        try:
            with open(partial, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if final.exists():
                held = final.read_bytes()
                if held != data:
                    raise EvidenceError(
                        f"request-2 member {name} appeared with contradictory bytes"
                    )
                partial.unlink(missing_ok=True)
                return ref
            os.rename(partial, final)
        except FileExistsError as error:
            raise ExecutionError(f"request-2 partial already exists for {name}") from error

        if final.read_bytes() != data:
            raise ExecutionError(f"request-2 member {name} does not read back as written")
        return ref

    def read(self, ref: RequestRefV2) -> bytes:
        data = self.path(ref).read_bytes()
        if len(data) != ref.size:
            raise EvidenceError(f"request-2 member {ref.name} size changed")
        try:
            document = load_bytes(data)
        except MalformedJSON as error:
            raise EvidenceError(f"request-2 member {ref.name} is unreadable: {error}") from error
        if canonical_bytes(document) != data:
            raise EvidenceError(f"request-2 member {ref.name} is not canonical request-2 bytes")
        expected = RequestIdentity.of_document(document)
        if expected != ref.identity:
            raise EvidenceError(f"request-2 member {ref.name} identity changed")
        return data
