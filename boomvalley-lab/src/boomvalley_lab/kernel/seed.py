"""Versioned deterministic seed derivation tree owned by K0.

A gated plan binds its seed tree (``document()``: tree version x root seed;
``semantic-plan-7``, T1-012), so every derived seed is re-derivable from the
frozen plan alone and a changed root seed is another plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.digest import sha256_document


@dataclass(frozen=True)
class SeedDerivation:
    root_seed: int
    version: str = "bvl-seed-tree-1"

    def __post_init__(self) -> None:
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, int):
            raise TypeError("root_seed must be an integer")

    def document(self) -> dict[str, Any]:
        return {"schema": self.version, "root_seed": self.root_seed}

    @classmethod
    def from_document(cls, document: Any) -> SeedDerivation:
        if (
            not isinstance(document, Mapping)
            or set(document) != {"schema", "root_seed"}
            or document["schema"] != cls.version
        ):
            raise ValueError(f"a seed tree is {{'schema': {cls.version!r}, 'root_seed': int}}")
        return cls(document["root_seed"])

    def derive(self, *path: str) -> int:
        if not path or not all(isinstance(item, str) and item for item in path):
            raise ValueError("seed path contains non-empty strings")
        digest = sha256_document(
            {
                "schema": self.version,
                "root_seed": self.root_seed,
                "path": list(path),
            }
        )
        # 63 bits keeps the value positive and portable to provider APIs that
        # accept signed 64-bit seeds.
        return int(digest.hex[:16], 16) & ((1 << 63) - 1)

    def episode(self, episode_key: str) -> int:
        return self.derive("episode", episode_key)

    def actor_call(
        self,
        episode_key: str,
        *,
        round_index: int,
        step_id: str,
        actor_id: str,
        attempt: int = 1,
    ) -> int:
        return self.derive(
            "episode",
            episode_key,
            "round",
            str(round_index),
            "step",
            step_id,
            "actor",
            actor_id,
            "attempt",
            str(attempt),
        )

    def world(
        self,
        episode_key: str,
        *,
        round_index: int,
        transition_id: str,
    ) -> int:
        return self.derive(
            "episode",
            episode_key,
            "round",
            str(round_index),
            "world",
            transition_id,
        )
