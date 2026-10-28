"""Dependency-ready execution: a step runs only on committed upstream evidence (T2-002).

The engine orders steps topologically, but an in-memory value of an earlier
node is not evidence.  Before a journaled engine admits a step (STEP_READY),
every same-round dependency whose node kind commits evidence must already
carry its one durable commit event in journal-2 (the same ``COMMIT_EVENT``
the manifest-4 verifier demands), and the value the engine holds for it must
be exactly what that event committed:

    actor_call      CUSTODY_ACCEPTED: same call identity and response
                    artifact, and the held response bytes hash to it
    proposal_parse  PROPOSAL_PARSED: same proposal identity and value
    decision / world_transition / memory_update
                    their commit event exists for the step

A dependency without its commit event is BVL-DEP-001; a held value that is
not the committed one is BVL-DEP-002.  Both refuse before the dependent's
STEP_READY, so a downstream actor call is never intended before an upstream
actor's call is custody-accepted and its proposal committed.  Readiness is inductive: each
dependency was itself admitted only on its own dependencies' evidence, so a
step's whole same-round ancestry is evidenced.  The refusal is journaled as
EPISODE_FAILED (``DependencyNotReadyError:<code>``) under the refused step.

An unjournaled (in-memory) engine has no evidence to require; it keeps the
topological value check only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.kernel.journal2 import (
    CUSTODY_ACCEPTED,
    DECISION_RECORDED,
    MEMORY_RECORDED,
    PROPOSAL_PARSED,
    WORLD_APPLIED,
)
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolNode

DEPENDENCY_EVIDENCE_MISSING = "BVL-DEP-001"
DEPENDENCY_EVIDENCE_MISMATCH = "BVL-DEP-002"
DEP_CODES = frozenset({DEPENDENCY_EVIDENCE_MISSING, DEPENDENCY_EVIDENCE_MISMATCH})

# The one commit event each node kind's built-in K0 handler journals per step.
COMMIT_EVENT: dict[NodeKind, str] = {
    NodeKind.ACTOR_CALL: CUSTODY_ACCEPTED,
    NodeKind.PROPOSAL_PARSE: PROPOSAL_PARSED,
    NodeKind.DECISION: DECISION_RECORDED,
    NodeKind.WORLD_TRANSITION: WORLD_APPLIED,
    NodeKind.MEMORY_UPDATE: MEMORY_RECORDED,
}


class DependencyNotReadyError(ExecutionError):
    """A step's dependency has no (matching) committed evidence yet."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in DEP_CODES:
            raise ValueError(f"unknown dependency reason code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code


def _canonical(value: Any) -> str | None:
    try:
        return canonical_json(value)
    except Exception:  # noqa: BLE001 - an uncanonical value matches nothing
        return None


def _held_mismatch(kind: NodeKind, record: Mapping[str, Any], value: Any) -> str | None:
    """Why the engine-held *value* is not what *record* committed, or None."""

    if kind is NodeKind.ACTOR_CALL:
        call = getattr(value, "call_identity", None)
        artifact = getattr(value, "artifact", None)
        content = getattr(getattr(value, "response", None), "content", None)
        if str(call) != record["call"]:
            return "the held call is not the custody-accepted call"
        if artifact is None or artifact.document() != record["artifact"]:
            return "the held response artifact is not the custody-accepted artifact"
        if not isinstance(content, bytes) or (
            str(sha256_bytes(content)) != record["artifact"].get("content")
        ):
            return "the held response bytes are not the custody-accepted bytes"
        return None
    if kind is NodeKind.PROPOSAL_PARSE:
        proposal = record["proposal"]
        identity = getattr(value, "identity", None)
        held = getattr(value, "value", None)
        if identity is None or identity.document() != proposal.get("identity"):
            return "the held proposal is not the committed proposal"
        if not isinstance(held, Mapping) or _canonical(dict(held)) != _canonical(
            proposal.get("value")
        ):
            return "the held proposal value is not the committed value"
        return None
    return None


def require_dependencies_ready(
    *,
    node: ProtocolNode,
    nodes: Callable[[str], ProtocolNode],
    records: Iterable[Mapping[str, Any]],
    episode: str,
    round_index: int,
    step_of: Callable[[ProtocolNode], str],
    held: Mapping[str, Any],
) -> None:
    """Refuse *node* unless every evidencing dependency is committed and held.

    *records* are the journal-2 records so far, *step_of* the engine's
    StepIdentity (as a string) of a node in this round, *held* the engine's
    values of the round's earlier nodes.
    """

    wanted: dict[str, tuple[ProtocolNode, str]] = {}
    for dependency in node.depends_on:
        upstream = nodes(dependency)
        event = COMMIT_EVENT.get(upstream.kind)
        if event is not None:
            wanted[step_of(upstream)] = (upstream, event)
    if not wanted:
        return
    committed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        step = record.get("step")
        if (
            step in wanted
            and record.get("event") == wanted[step][1]
            and record.get("episode") == episode
            and record.get("round") == round_index
        ):
            committed.setdefault(step, record)
    for step, (upstream, event) in sorted(wanted.items(), key=lambda item: item[1][0].node_id):
        record = committed.get(step)
        if record is None:
            raise DependencyNotReadyError(
                DEPENDENCY_EVIDENCE_MISSING,
                f"step {node.node_id!r} round {round_index} is not ready: dependency "
                f"{upstream.node_id!r} has no committed {event} evidence",
            )
        problem = _held_mismatch(upstream.kind, record, held.get(upstream.node_id))
        if problem is not None:
            raise DependencyNotReadyError(
                DEPENDENCY_EVIDENCE_MISMATCH,
                f"step {node.node_id!r} round {round_index} is not ready: dependency "
                f"{upstream.node_id!r}: {problem} (journal-2 #{record.get('sequence')})",
            )
