"""Finite Protocol IR primitives used by the K0 vertical slice.

This is deliberately not a scripting language.  A protocol is a closed set of
typed nodes plus explicit dependencies.  Repetition belongs to a finite round
bound, never an arbitrary executable expression; a bounded revision / veto
exchange is unrolled into ordinary nodes before it reaches the IR
(``kernel/revision.py``, T2-005).

A protocol that declares a ``RoundContractV1`` (P16, T4-001,
``kernel/rounds.py``) is ``bvl-protocol-ir-2``: its repetition is the typed
contract (safety bound x registered termination rule), ``rounds`` is derived
from it, and it has no ``termination`` node - the engine evaluates the
contract when a round closes.  A protocol without one stays the historical
``bvl-protocol-ir-1`` document, byte for byte.

A contract that declares its termination timing (T4-002) is evaluated at that
point of the round body; a mid-round timing is anchored on a node of this IR
(``termination_anchor``), so a body the timing cannot be placed in is refused
with the protocol (BVL-ROUND-001).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.kernel.rounds import ROUND_PLAN_INVALID, RoundContractV1, RoundError

PROTOCOL_IR_SCHEMA_V1 = "bvl-protocol-ir-1"
PROTOCOL_IR_SCHEMA_V2 = "bvl-protocol-ir-2"

_NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class NodeKind(StrEnum):
    ACTOR_CALL = "actor_call"
    PROPOSAL_PARSE = "proposal_parse"
    DECISION = "decision"
    WORLD_TRANSITION = "world_transition"
    MEMORY_UPDATE = "memory_update"
    TERMINATION = "termination"


@dataclass(frozen=True)
class ProtocolNode:
    node_id: str
    kind: NodeKind
    depends_on: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not _NODE_ID.fullmatch(self.node_id):
            raise DeclarationError(f"invalid protocol node id {self.node_id!r}")
        if not isinstance(self.kind, NodeKind):
            raise DeclarationError(f"invalid protocol node kind {self.kind!r}")
        if self.node_id in self.depends_on:
            raise DeclarationError(f"protocol node {self.node_id!r} depends on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise DeclarationError(f"protocol node {self.node_id!r} repeats a dependency")

    def document(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "kind": self.kind.value,
            "depends_on": list(self.depends_on),
            "config": dict(self.config),
        }


@dataclass(frozen=True)
class ProtocolIR:
    nodes: tuple[ProtocolNode, ...]
    rounds: int = 1
    round: RoundContractV1 | None = None

    def __post_init__(self) -> None:
        if self.round is not None:
            if not isinstance(self.round, RoundContractV1):
                raise RoundError(ROUND_PLAN_INVALID, "a protocol round is a RoundContractV1")
            if self.rounds not in (1, self.round.rounds):
                raise RoundError(
                    ROUND_PLAN_INVALID,
                    f"rounds {self.rounds!r} contradicts the round contract "
                    f"({self.round.rounds})",
                )
            # the one repetition bound of the protocol is its contract's
            object.__setattr__(self, "rounds", self.round.rounds)
            owned = sorted(
                node.node_id for node in self.nodes
                if isinstance(node, ProtocolNode) and node.kind is NodeKind.TERMINATION
            )
            if owned:
                raise RoundError(
                    ROUND_PLAN_INVALID,
                    f"termination nodes {owned} under a round contract: the contract's rule "
                    "terminates the episode, not a node handler",
                )
        if isinstance(self.rounds, bool) or not isinstance(self.rounds, int) or self.rounds < 1:
            raise DeclarationError(f"rounds must be a positive integer: {self.rounds!r}")
        if not self.nodes:
            raise DeclarationError("a protocol has at least one node")
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise DeclarationError("protocol node ids are unique")
        known = set(ids)
        for node in self.nodes:
            missing = sorted(set(node.depends_on) - known)
            if missing:
                raise DeclarationError(
                    f"protocol node {node.node_id!r} depends on unknown nodes {missing}"
                )
        self.topological_order()  # reject dependency cycles
        if self.round is not None:
            self.termination_anchor  # noqa: B018 - reject an unplaceable timing

    @property
    def termination_anchor(self) -> str | None:
        """The node whose commit is the round contract's mid-round timing point."""

        if self.round is None:
            return None
        return self.round.anchor(
            [(node_id, self.node(node_id).kind.value) for node_id in self.topological_order()]
        )

    def executions(self, rounds_executed: int, steps: int | None = None) -> dict[str, int]:
        """How many rounds of one completed episode executed each node.

        Every node runs in every executed round, except that a timed round
        contract (T4-002) may cut the last round at its timing point: of
        *steps* STEP_READY records (the attested step count) the last round
        then holds only a prefix of the topological order.
        """

        order = self.topological_order()
        if self.round is None or self.round.timing is None or steps is None:
            return dict.fromkeys(order, rounds_executed)
        last = steps - (rounds_executed - 1) * len(order)
        return {
            node_id: rounds_executed - (0 if index < last else 1)
            for index, node_id in enumerate(order)
        }

    def topological_order(self) -> tuple[str, ...]:
        by_id = {node.node_id: node for node in self.nodes}
        remaining = {node_id: set(node.depends_on) for node_id, node in by_id.items()}
        order: list[str] = []

        while remaining:
            ready = sorted(node_id for node_id, deps in remaining.items() if not deps)
            if not ready:
                cycle = sorted(remaining)
                raise DeclarationError(f"protocol dependency cycle among {cycle}")
            order.extend(ready)
            for node_id in ready:
                remaining.pop(node_id)
            for deps in remaining.values():
                deps.difference_update(ready)

        return tuple(order)

    def document(self) -> dict[str, Any]:
        by_id = {node.node_id: node for node in self.nodes}
        # Canonical semantics do not depend on declaration list order.
        ordered = [by_id[node_id].document() for node_id in sorted(by_id)]
        if self.round is not None:
            return {
                "schema": PROTOCOL_IR_SCHEMA_V2,
                "round": self.round.document(),
                "nodes": ordered,
            }
        return {
            "schema": PROTOCOL_IR_SCHEMA_V1,
            "rounds": self.rounds,
            "nodes": ordered,
        }

    @classmethod
    def from_document(cls, document: Any) -> ProtocolIR:
        """Read one ``bvl-protocol-ir-1`` / ``-2`` document back into the IR (closed shape).

        A package verifier re-derives the executed structure from the persisted
        plan through this reader, so it accepts exactly what ``document()``
        writes and nothing else.
        """

        if not isinstance(document, Mapping) or "schema" not in document:
            raise DeclarationError("protocol IR document has the wrong closed shape")
        if document["schema"] == PROTOCOL_IR_SCHEMA_V2:
            repetition = "round"
        elif document["schema"] == PROTOCOL_IR_SCHEMA_V1:
            repetition = "rounds"
        else:
            raise DeclarationError(
                "protocol IR schema is exactly 'bvl-protocol-ir-1' or 'bvl-protocol-ir-2'"
            )
        if set(document) != {"schema", repetition, "nodes"}:
            raise DeclarationError("protocol IR document has the wrong closed shape")
        nodes = document["nodes"]
        if not isinstance(nodes, list):
            raise DeclarationError("protocol IR nodes is a list")
        parsed: list[ProtocolNode] = []
        for item in nodes:
            if not isinstance(item, Mapping) or set(item) != {"id", "kind", "depends_on", "config"}:
                raise DeclarationError("protocol IR node has the wrong closed shape")
            if not isinstance(item["depends_on"], list) or not isinstance(item["config"], Mapping):
                raise DeclarationError("protocol IR node depends_on/config are malformed")
            try:
                kind = NodeKind(item["kind"])
            except ValueError as error:
                raise DeclarationError(f"unknown protocol node kind {item['kind']!r}") from error
            parsed.append(
                ProtocolNode(item["id"], kind, tuple(item["depends_on"]), dict(item["config"]))
            )
        if repetition == "round":
            protocol = cls(tuple(parsed), round=RoundContractV1.from_document(document["round"]))
        else:
            protocol = cls(tuple(parsed), document["rounds"])
        if protocol.document() != dict(document):
            raise DeclarationError("protocol IR document is not in canonical node order")
        return protocol

    def node(self, node_id: str) -> ProtocolNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)
