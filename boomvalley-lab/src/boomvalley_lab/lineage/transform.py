"""The transform protocol: a derivation is performed, then reported as fact.

    identity / version   what this transform IS, read off the object that ran
    apply(parent, where) the child bytes, from one parent's bytes

A transform is as dumb as an adapter: it produces bytes and reports what it
is. It does not decide whether it was the declared transform (R43 does, on the
recorded facts), and it never touches custody, the journal or the store.

MVP lineage is one child from one parent, one hop. There is no registry, no
code hashing, no dependency graph and no scheduler — a transform is simply the
thing whose identity the derivation record names.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transform(Protocol):
    identity: str
    version: str

    def apply(self, parent: bytes, where: Mapping[str, str]) -> bytes: ...
