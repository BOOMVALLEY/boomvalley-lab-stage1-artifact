"""Bounded revision / veto construct, compiled into finite Protocol IR (T2-005).

A revision is not a loop.  ``BoundedRevisionV1`` declares one draft -> review
-> revise exchange with a fixed revision bound, and ``compile()`` unrolls it
into ordinary typed IR nodes plus the P05/P06/P07 declarations they need:

    <block>.draft.0           actor_call (authors[0])      the first draft
    <block>.draft.0.parse     proposal_parse               (schema, parser)
    <block>.review.r          actor_call (reviewers[r])    observes draft r
    <block>.review.r.parse    proposal_parse
    <block>.draft.r+1         actor_call (authors[r+1])    observes draft r and review r
    <block>.draft.r+1.parse   proposal_parse
    ...                       (r = 0 .. max_revisions - 1)
    <block>.review.R          actor_call (reviewers[R])    the veto holder, observes draft R
    <block>.decision          decision  builtin.veto:1 over {authors[R], reviewers[R]}

so a block of bound R is exactly ``4 * (R + 1) + 1`` nodes, acyclic by
construction (every edge points to a later stage) and re-checked as such by
``ProtocolIR``.  Every stage always executes: there is no condition, no
``until`` and no executable expression, only the integer bound
(``0 <= max_revisions <= MAX_REVISIONS``).  A review proposes the action it
endorses in the drafts' own proposal schema; the final review vetoes the final
draft by proposing anything else or abstaining (BVL-DEC-007), and the declared
``on_veto`` policy (FAIL_EPISODE | NO_ACTION) applies.

Visibility stays explicit P05/P13: each draft and review is a named
``actor_output`` source (``<block>.draft.r`` / ``<block>.review.r``) ALLOWed
only to the stage that consumes it.  A grant holds for every call of an actor
and its producer must be a same-round ancestor of each of them (T2-001), so
every stage is a distinct plan actor; one actor revising its own draft needs a
call-scoped P13 grant (BVL-REC-146).

The compiled nodes, contracts and grants enter the frozen plan like declared
ones, so PlanIdentity and the ProtocolDagIdentity (T2-004) bind the unrolled
structure, and both package verifiers re-check it with the rules they already
apply to any IR.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.kernel.decisions import VETO, DecisionDeclV1, UnresolvedPolicy
from boomvalley_lab.kernel.information import AccessRuleV1, ActorOutputSourceV1
from boomvalley_lab.kernel.proposals import ProposalContractDeclV1
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR, ProtocolNode
from boomvalley_lab.kernel.rounds import RoundContractV1

CONSTRUCT = "bounded_revision"
#: no study may declare a longer exchange; the unrolled block stays small
MAX_REVISIONS = 3
# the construct declaration is not a closed, finite bounded revision
REVISION_INVALID = "BVL-REV-001"
# a revision bound outside 0..MAX_REVISIONS (or no integer bound at all)
REVISION_UNBOUNDED = "BVL-REV-002"

REQUIRED = frozenset({"construct", "id", "max_revisions", "authors", "reviewers", "schema",
                      "parser"})
OPTIONAL = frozenset({"depends_on", "on_veto"})
_BLOCK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _invalid(detail: str, code: str = REVISION_INVALID) -> DeclarationError:
    return DeclarationError(f"{code} bounded revision is invalid: {detail}", code=code)


def _actors(value: Any, what: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        raise _invalid(f"{what} is a non-empty list of plan actors")
    if any(not isinstance(actor, str) or not actor for actor in value):
        raise _invalid(f"{what} names actors by non-empty string id")
    return tuple(value)


@dataclass(frozen=True)
class BoundedRevisionV1:
    """One draft / review / revise exchange with a fixed revision bound."""

    block_id: str
    max_revisions: int
    authors: tuple[str, ...]  # drafting actor per stage: draft 0, revisions 1..R
    reviewers: tuple[str, ...]  # reviewing actor per stage; the last one holds the veto
    schema: str  # "<schema_id>:<version>" of every draft and review proposal
    parser: str
    depends_on: tuple[str, ...] = ()
    on_veto: str = UnresolvedPolicy.FAIL_EPISODE.value

    def __post_init__(self) -> None:
        if not isinstance(self.block_id, str) or not _BLOCK_ID.fullmatch(self.block_id):
            raise _invalid(f"block id {self.block_id!r} is not a plain identifier (no dots)")
        bound = self.max_revisions
        if isinstance(bound, bool) or not isinstance(bound, int):
            raise _invalid(f"max_revisions is an integer bound, not {bound!r}",
                           REVISION_UNBOUNDED)
        if not 0 <= bound <= MAX_REVISIONS:
            raise _invalid(f"max_revisions {bound} is outside 0..{MAX_REVISIONS}",
                           REVISION_UNBOUNDED)
        authors = _actors(self.authors, "authors")
        reviewers = _actors(self.reviewers, "reviewers")
        if len(authors) != bound + 1 or len(reviewers) != bound + 1:
            raise _invalid(
                f"a bound of {bound} has {bound + 1} drafting and {bound + 1} reviewing stages, "
                f"not {len(authors)} authors and {len(reviewers)} reviewers"
            )
        everyone = authors + reviewers
        if len(set(everyone)) != len(everyone):
            raise _invalid(
                "every stage is a distinct plan actor (a P13 grant holds for all calls of "
                f"an actor): {list(everyone)}"
            )
        for name in ("schema", "parser"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise _invalid(f"{name} is a non-empty string")
        depends = self.depends_on
        if isinstance(depends, str) or not isinstance(depends, Sequence):
            raise _invalid("depends_on is a list of node ids")
        if self.on_veto not in {policy.value for policy in UnresolvedPolicy}:
            raise _invalid(
                f"on_veto is one of {[p.value for p in UnresolvedPolicy]}, not {self.on_veto!r}"
            )
        object.__setattr__(self, "authors", authors)
        object.__setattr__(self, "reviewers", reviewers)
        object.__setattr__(self, "depends_on", tuple(depends))

    @classmethod
    def from_document(cls, document: Any) -> BoundedRevisionV1:
        """The closed study declaration: nothing but the bound decides repetition."""

        if not isinstance(document, Mapping):
            raise _invalid("a construct is an object")
        keys = set(document)
        if not REQUIRED <= keys <= REQUIRED | OPTIONAL:
            raise _invalid(
                f"construct has keys {sorted(keys)}; required {sorted(REQUIRED)}, optional "
                f"{sorted(OPTIONAL)} (no condition, loop or expression keys)"
            )
        if document["construct"] != CONSTRUCT:
            raise _invalid(f"construct is exactly {CONSTRUCT!r}, not {document['construct']!r}")
        return cls(
            document["id"],
            document["max_revisions"],
            document["authors"],
            document["reviewers"],
            document["schema"],
            document["parser"],
            document.get("depends_on", ()),
            document.get("on_veto", UnresolvedPolicy.FAIL_EPISODE.value),
        )

    # ------------------------------------------------------------ node ids
    def draft(self, stage: int) -> str:
        return f"{self.block_id}.draft.{stage}"

    def review(self, stage: int) -> str:
        return f"{self.block_id}.review.{stage}"

    @property
    def decision(self) -> str:
        return f"{self.block_id}.decision"

    def compile(self) -> CompiledRevisionV1:
        bound = self.max_revisions
        nodes: list[ProtocolNode] = []
        sources: list[ActorOutputSourceV1] = []
        access: list[AccessRuleV1] = []
        proposals: list[ProposalContractDeclV1] = []

        def stage(call: str, actor: str, upstream: tuple[str, ...]) -> None:
            nodes.append(ProtocolNode(call, NodeKind.ACTOR_CALL, upstream, {"actor": actor}))
            nodes.append(ProtocolNode(f"{call}.parse", NodeKind.PROPOSAL_PARSE, (call,)))
            proposals.append(ProposalContractDeclV1(f"{call}.parse", self.schema, self.parser))
            sources.append(ActorOutputSourceV1(call, f"{call}.parse"))

        stage(self.draft(0), self.authors[0], self.depends_on)
        for index in range(bound + 1):
            stage(self.review(index), self.reviewers[index], (f"{self.draft(index)}.parse",))
            access.append(AccessRuleV1(self.reviewers[index], self.draft(index), "ALLOW"))
            if index < bound:
                reviser = self.authors[index + 1]
                stage(self.draft(index + 1), reviser, (f"{self.review(index)}.parse",))
                access.append(AccessRuleV1(reviser, self.draft(index), "ALLOW"))
                access.append(AccessRuleV1(reviser, self.review(index), "ALLOW"))
        nodes.append(ProtocolNode(
            self.decision,
            NodeKind.DECISION,
            (f"{self.draft(bound)}.parse", f"{self.review(bound)}.parse"),
        ))
        decision = DecisionDeclV1(
            self.decision, VETO, [self.authors[bound], self.reviewers[bound]], {}, self.on_veto
        )
        return CompiledRevisionV1(self, tuple(nodes), tuple(proposals), decision,
                                  tuple(sources), tuple(access))


@dataclass(frozen=True)
class CompiledRevisionV1:
    """One block unrolled: IR nodes and the declarations they bind."""

    block: BoundedRevisionV1
    nodes: tuple[ProtocolNode, ...]
    proposals: tuple[ProposalContractDeclV1, ...]
    decision: DecisionDeclV1
    sources: tuple[ActorOutputSourceV1, ...]
    access: tuple[AccessRuleV1, ...]


def compile_protocol(
    nodes: Sequence[ProtocolNode],
    blocks: Sequence[BoundedRevisionV1],
    rounds: int = 1,
    round: RoundContractV1 | None = None,
) -> tuple[ProtocolIR, tuple[CompiledRevisionV1, ...]]:
    """Declared nodes plus every unrolled block, as one finite, acyclic ProtocolIR.

    A declared node may depend on a block's nodes (typically its decision) and
    a block on declared nodes; ``ProtocolIR`` refuses an unknown id, a
    collision and any cycle, so no block can be re-entered.
    """

    ids = [block.block_id for block in blocks]
    if len(set(ids)) != len(ids):
        raise _invalid(f"block ids are unique: {ids}")
    compiled = tuple(block.compile() for block in blocks)
    declared = {node.node_id for node in nodes}
    for unit in compiled:
        clash = sorted(declared & {node.node_id for node in unit.nodes})
        if clash:
            raise _invalid(f"block {unit.block.block_id!r} node ids {clash} are declared nodes")
    protocol = ProtocolIR(
        tuple(nodes) + tuple(node for unit in compiled for node in unit.nodes), rounds, round
    )
    return protocol, compiled
