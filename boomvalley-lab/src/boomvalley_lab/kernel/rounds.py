"""Round IR: repeated rounds as finite typed protocol semantics (P16, T4-001).

A longitudinal protocol does not carry a bare repetition count the engine
loops over.  It carries one ``RoundContractV1`` inside the same Protocol IR
(``bvl-protocol-ir-2``, P16 13.1: no second grammar):

    round
        max_rounds      the compile-time safety bound of the episode
        termination     one registered termination rule and its config

The round body is the protocol's node graph; the contract says how often it
repeats and who decides that it stops.  Termination is never a handler's
return value and never an inline condition: it is a rule of a closed core set
(P03 may register more, T4-002), evaluated by the engine when a round closes,
and its verdict is journal-2 evidence (``TERMINATION_EVALUATED``) that a
verifier re-derives from the frozen plan alone.

T4-001 registers the one rule every bounded protocol needs:

    builtin.fixed-count:1   ``{"count": N}``: CONTINUE after rounds 1..N-1,
                            TERMINATE after round N.  ``count`` may not exceed
                            ``max_rounds`` (BVL-ROUND-010 before anything
                            runs), so the episode executes exactly N rounds.

Every round is identified before its first step: ``RoundIdentity`` binds the
episode, the round index and the identity of the World state the round opens
on (``ROUND_OPENED``).  The contract is part of the Protocol IR document and
therefore of PlanIdentity: another bound or another termination rule is
another plan and another gate.

A protocol without a contract is the historical ``bvl-protocol-ir-1`` (a bare
``rounds`` bound, no termination evidence); its documents and identities are
unchanged.

Termination timing is explicit and identity-bearing (P16 13.6, T4-002).  A
termination that declares ``timing`` is a ``bvl-round-contract-2`` and names
the one point of the round its rule is evaluated at:

    before_observation       before the round opens, on the state it would
                             open on (TERMINATE: the round never exists)
    after_decision           after the round's last decision committed and
                             before any World transition, on the pre-World
                             state (TERMINATE: the round is cut, no transition)
    after_world_transition   after the round's last World transition
                             committed, on its post-state (TERMINATE: the
                             round is cut after the World)
    after_round_close        after ROUND_COMPLETED, on the closed state

``timing`` is part of the rule document, so of the TerminationRuleIdentity,
the Protocol IR and the PlanIdentity: the same predicate before and after the
World is two plans.  Each verdict (``bvl-termination-verdict-2``) names the
point it was evaluated at and the identity of the state it read.  Two further
rules are registered for these contracts, both deterministic predicates over
the admitted World state (so the plan needs a World contract):

    builtin.state-predicate:1   ``{path, op, value}``: TERMINATE when the
                                state member at ``path`` compares so
    builtin.terminal-state:1    ``{path, success, failure}``: TERMINATE when
                                the member is a declared terminal value

``builtin.fixed-count:1`` counts closed rounds and is timed
``after_round_close`` only.  When round ``max_rounds`` closes without a
TERMINATE the core records the safety-bound verdict itself (point
``safety_bound``): the bound ends the episode as evidence, not as a loop exit.
A ``bvl-round-contract-1`` (no ``timing``) stays the T4-001 fixed-count
document, byte for byte.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.kernel.identity import (
    EpisodeIdentity,
    RoundIdentity,
    TerminationRuleIdentity,
)

ROUND_CONTRACT_SCHEMA = "bvl-round-contract-1"
TERMINATION_VERDICT_SCHEMA = "bvl-termination-verdict-1"
# T4-002: a contract whose termination declares its timing
ROUND_CONTRACT_SCHEMA_V2 = "bvl-round-contract-2"
TERMINATION_VERDICT_SCHEMA_V2 = "bvl-termination-verdict-2"

FIXED_COUNT_RULE = "builtin.fixed-count:1"
STATE_PREDICATE_RULE = "builtin.state-predicate:1"
TERMINAL_STATE_RULE = "builtin.terminal-state:1"
#: The closed set of termination rules the core evaluates (rule id -> config keys).
TERMINATION_RULES: Mapping[str, frozenset[str]] = {
    FIXED_COUNT_RULE: frozenset({"count"}),
    STATE_PREDICATE_RULE: frozenset({"path", "op", "value"}),
    TERMINAL_STATE_RULE: frozenset({"path", "success", "failure"}),
}
#: Rules that read the admitted World state at their timing point.
STATE_RULES = frozenset({STATE_PREDICATE_RULE, TERMINAL_STATE_RULE})

# P16 13.6: the points of a round a termination rule is evaluated at
BEFORE_OBSERVATION = "before_observation"
AFTER_DECISION = "after_decision"
AFTER_WORLD_TRANSITION = "after_world_transition"
AFTER_ROUND_CLOSE = "after_round_close"
TIMINGS = (BEFORE_OBSERVATION, AFTER_DECISION, AFTER_WORLD_TRANSITION, AFTER_ROUND_CLOSE)
#: The node kind whose last commit of the round is a mid-round timing's point.
TIMING_ANCHOR_KIND: Mapping[str, str] = {
    AFTER_DECISION: "decision",
    AFTER_WORLD_TRANSITION: "world_transition",
}
#: The point of the core's own verdict when round ``max_rounds`` closed.
SAFETY_BOUND = "safety_bound"

EQUALITY_OPS = ("eq", "ne")
ORDER_OPS = ("lt", "le", "gt", "ge")

CONTINUE = "CONTINUE"
TERMINATE = "TERMINATE"
FIXED_COUNT_REACHED = "FIXED_COUNT_REACHED"
FIXED_COUNT_NOT_REACHED = "FIXED_COUNT_NOT_REACHED"
STATE_PREDICATE_HOLDS = "STATE_PREDICATE_HOLDS"
STATE_PREDICATE_NOT_HELD = "STATE_PREDICATE_NOT_HELD"
TERMINAL_STATE_SUCCESS = "TERMINAL_STATE_SUCCESS"
TERMINAL_STATE_FAILURE = "TERMINAL_STATE_FAILURE"
STATE_NOT_TERMINAL = "STATE_NOT_TERMINAL"
SAFETY_BOUND_REACHED = "SAFETY_BOUND_REACHED"

# P16 8 stable reason codes (the subset T4-001 / T4-002 / T4-003 raise)
ROUND_PLAN_INVALID = "BVL-ROUND-001"
ROUND_BOUND_MISSING = "BVL-ROUND-002"
TERMINATION_RULE_NOT_REGISTERED = "BVL-ROUND-003"
TERMINATION_RULE_FAILED = "BVL-ROUND-004"
STATE_CHAIN_MISMATCH = "BVL-ROUND-005"  # T4-005, ``kernel/state_chain.py``
MEMORY_SCOPE_INVALID = "BVL-ROUND-006"
MEMORY_SOURCE_MISSING = "BVL-ROUND-007"
HIDDEN_ACTOR_MEMORY = "BVL-ROUND-008"
MAX_ROUNDS_EXCEEDED = "BVL-ROUND-010"
CROSS_EPISODE_STATE_UNDECLARED = "BVL-ROUND-011"  # T4-004
ROUND_CODES = frozenset(
    {
        ROUND_PLAN_INVALID,
        ROUND_BOUND_MISSING,
        TERMINATION_RULE_NOT_REGISTERED,
        TERMINATION_RULE_FAILED,
        STATE_CHAIN_MISMATCH,
        MEMORY_SCOPE_INVALID,
        MEMORY_SOURCE_MISSING,
        HIDDEN_ACTOR_MEMORY,
        MAX_ROUNDS_EXCEEDED,
        CROSS_EPISODE_STATE_UNDECLARED,
    }
)

_CONTRACT_KEYS = {"schema", "max_rounds", "termination"}
_TERMINATION_KEYS = {"rule", "config"}
_TIMED_TERMINATION_KEYS = {"rule", "timing", "config"}


class RoundError(DeclarationError):
    """A round contract is refused; ``code`` is one P16 BVL-ROUND-* reason."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in ROUND_CODES:
            raise ValueError(f"unknown round reason code {code!r}")
        super().__init__(f"{code}: {detail}", code=code)


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _same(left: Any, right: Any) -> bool:
    """JSON scalar equality: a boolean is never a number, a string never either."""

    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if _number(left) and _number(right):
        return left == right
    return type(left) is type(right) and left == right


def _config_problem(rule: str, config: Mapping[str, Any]) -> str | None:
    """Why a registered rule's config (its exact keys already checked) is refused."""

    if rule == FIXED_COUNT_RULE:
        if not _positive(config["count"]):
            return f"count is a positive integer: {config['count']!r}"
        return None
    path = config["path"]
    if (
        not isinstance(path, list)
        or not path
        or any(not isinstance(key, str) or not key for key in path)
    ):
        return "path is a non-empty list of state member names"
    if rule == STATE_PREDICATE_RULE:
        if config["op"] not in EQUALITY_OPS + ORDER_OPS:
            return f"op is one of {list(EQUALITY_OPS + ORDER_OPS)}: {config['op']!r}"
        if not _scalar(config["value"]):
            return "value is a JSON scalar"
        if config["op"] in ORDER_OPS and not _number(config["value"]):
            return f"op {config['op']!r} compares numbers: {config['value']!r}"
        return None
    values: list[Any] = []
    for name in ("success", "failure"):
        if not isinstance(config[name], list) or any(not _scalar(v) for v in config[name]):
            return f"{name} is a list of JSON scalars"
        values += config[name]
    if not values:
        return "declares at least one terminal value"
    if any(_same(a, b) for i, a in enumerate(values) for b in values[i + 1:]):
        return "a terminal value is declared once"
    return None


def _state_verdict(rule: str, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    """The reason a state rule derives on one admitted state (pure)."""

    name = ".".join(config["path"])
    held: Any = state
    for key in config["path"]:
        if not isinstance(held, Mapping) or key not in held:
            raise RoundError(
                TERMINATION_RULE_FAILED, f"the observed state has no member {name!r}"
            )
        held = held[key]
    if not _scalar(held):
        raise RoundError(TERMINATION_RULE_FAILED, f"state member {name!r} is not a JSON scalar")
    if rule == TERMINAL_STATE_RULE:
        if any(_same(held, value) for value in config["success"]):
            return TERMINAL_STATE_SUCCESS
        if any(_same(held, value) for value in config["failure"]):
            return TERMINAL_STATE_FAILURE
        return STATE_NOT_TERMINAL
    op, value = config["op"], config["value"]
    if op in EQUALITY_OPS:
        holds = _same(held, value) is (op == "eq")
    elif not _number(held):
        raise RoundError(
            TERMINATION_RULE_FAILED, f"state member {name!r} is not a number: {held!r}"
        )
    else:
        holds = {
            "lt": held < value, "le": held <= value, "gt": held > value, "ge": held >= value
        }[op]
    return STATE_PREDICATE_HOLDS if holds else STATE_PREDICATE_NOT_HELD


_TERMINATING = frozenset(
    {FIXED_COUNT_REACHED, STATE_PREDICATE_HOLDS, TERMINAL_STATE_SUCCESS, TERMINAL_STATE_FAILURE,
     SAFETY_BOUND_REACHED}
)


@dataclass(frozen=True)
class TerminationRuleV1:
    """One registered termination rule, its frozen config and (T4-002) its timing.

    ``timing`` is ``None`` only for the T4-001 fixed-count document.
    """

    rule: str
    config: Mapping[str, Any]
    timing: str | None = None

    def __post_init__(self) -> None:
        if self.rule not in TERMINATION_RULES:
            raise RoundError(
                TERMINATION_RULE_NOT_REGISTERED,
                f"termination rule {self.rule!r} is not registered "
                f"(registered: {sorted(TERMINATION_RULES)})",
            )
        if not isinstance(self.config, Mapping) or set(self.config) != TERMINATION_RULES[self.rule]:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"termination rule {self.rule!r} config has exactly the keys "
                f"{sorted(TERMINATION_RULES[self.rule])}",
            )
        problem = _config_problem(self.rule, self.config)
        if problem is not None:
            raise RoundError(ROUND_PLAN_INVALID, f"{self.rule} {problem}")
        if self.timing is None:
            if self.rule != FIXED_COUNT_RULE:
                raise RoundError(
                    ROUND_PLAN_INVALID,
                    f"termination rule {self.rule!r} declares its timing (one of {list(TIMINGS)})",
                )
        elif self.timing not in TIMINGS:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"termination timing is one of {list(TIMINGS)}: {self.timing!r}",
            )
        elif self.rule == FIXED_COUNT_RULE and self.timing != AFTER_ROUND_CLOSE:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"{self.rule} counts closed rounds: its timing is {AFTER_ROUND_CLOSE!r}, "
                f"not {self.timing!r}",
            )

    @property
    def observes_state(self) -> bool:
        return self.rule in STATE_RULES

    def document(self) -> dict[str, Any]:
        if self.timing is None:
            return {"rule": self.rule, "config": dict(self.config)}
        return {"rule": self.rule, "timing": self.timing, "config": dict(self.config)}

    @property
    def identity(self) -> TerminationRuleIdentity:
        return TerminationRuleIdentity.of_payload(self.document())


@dataclass(frozen=True)
class RoundContractV1:
    """How often the protocol's node graph repeats, and what stops it."""

    max_rounds: int
    termination: TerminationRuleV1

    def __post_init__(self) -> None:
        if not _positive(self.max_rounds):
            raise RoundError(
                ROUND_BOUND_MISSING,
                f"a round contract has a positive integer max_rounds: {self.max_rounds!r}",
            )
        if not isinstance(self.termination, TerminationRuleV1):
            raise RoundError(ROUND_PLAN_INVALID, "a round contract has one termination rule")
        if (
            self.termination.rule == FIXED_COUNT_RULE
            and self.termination.config["count"] > self.max_rounds
        ):
            raise RoundError(
                MAX_ROUNDS_EXCEEDED,
                f"{self.termination.rule} count {self.termination.config['count']} exceeds "
                f"the safety bound max_rounds {self.max_rounds}",
            )

    @classmethod
    def fixed_count(cls, count: int, max_rounds: int | None = None) -> RoundContractV1:
        return cls(
            count if max_rounds is None else max_rounds,
            TerminationRuleV1(FIXED_COUNT_RULE, {"count": count}),
        )

    @classmethod
    def timed(
        cls, max_rounds: int, rule: str, timing: str, config: Mapping[str, Any]
    ) -> RoundContractV1:
        """A ``bvl-round-contract-2``: one rule evaluated at one declared point."""

        return cls(max_rounds, TerminationRuleV1(rule, dict(config), timing))

    @property
    def rounds(self) -> int:
        """The rounds the plan bounds: a fixed count, else the safety bound."""

        if self.termination.rule == FIXED_COUNT_RULE:
            return self.termination.config["count"]
        return self.max_rounds

    @property
    def timing(self) -> str | None:
        return self.termination.timing

    @property
    def schema(self) -> str:
        return ROUND_CONTRACT_SCHEMA if self.timing is None else ROUND_CONTRACT_SCHEMA_V2

    def document(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "max_rounds": self.max_rounds,
            "termination": self.termination.document(),
        }

    @classmethod
    def from_document(cls, document: Any) -> RoundContractV1:
        """Read one ``bvl-round-contract-1`` document (closed shape)."""

        if not isinstance(document, Mapping) or set(document) != _CONTRACT_KEYS:
            raise RoundError(ROUND_PLAN_INVALID, "round contract has the wrong closed shape")
        if document["schema"] not in (ROUND_CONTRACT_SCHEMA, ROUND_CONTRACT_SCHEMA_V2):
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"round contract schema is exactly {ROUND_CONTRACT_SCHEMA!r} or "
                f"{ROUND_CONTRACT_SCHEMA_V2!r}",
            )
        contract = cls(document["max_rounds"], _termination(document["termination"]))
        if contract.schema != document["schema"]:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"a {document['schema']} termination "
                + ("declares its timing" if contract.timing is None else "has no timing"),
            )
        return contract

    @classmethod
    def from_declaration(cls, declaration: Any) -> RoundContractV1:
        """A study's ``protocol.round``: ``{max_rounds, termination: {rule, [timing,] config}}``.

        The bound is never defaulted: a declaration without ``max_rounds`` is
        BVL-ROUND-002, one without a termination rule BVL-ROUND-001.  A
        termination that declares ``timing`` is a ``bvl-round-contract-2``.
        """

        if not isinstance(declaration, Mapping):
            raise RoundError(ROUND_PLAN_INVALID, "protocol.round is an object")
        if "max_rounds" not in declaration:
            raise RoundError(
                ROUND_BOUND_MISSING, "protocol.round declares its safety bound max_rounds"
            )
        if set(declaration) != {"max_rounds", "termination"}:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"protocol.round has exactly max_rounds and termination: {sorted(declaration)}",
            )
        return cls(declaration["max_rounds"], _termination(declaration["termination"]))

    def evaluate(self, rounds_closed: int) -> dict[str, Any]:
        """The verdict after *rounds_closed* rounds closed (pure, plan-derived).

        Evaluated past the safety bound it refuses (BVL-ROUND-010): no round
        beyond ``max_rounds`` is ever continued into.
        """

        if self.timing is not None:
            raise RoundError(
                ROUND_PLAN_INVALID, "a timed round contract is evaluated at its timing point"
            )
        if not _positive(rounds_closed) or rounds_closed > self.max_rounds:
            raise RoundError(
                MAX_ROUNDS_EXCEEDED,
                f"round {rounds_closed!r} is outside the safety bound 1..{self.max_rounds}",
            )
        reached = rounds_closed >= self.rounds
        return {
            "schema": TERMINATION_VERDICT_SCHEMA,
            "rule": self.termination.identity.document(),
            "rounds_closed": rounds_closed,
            "max_rounds": self.max_rounds,
            "verdict": TERMINATE if reached else CONTINUE,
            "reason": FIXED_COUNT_REACHED if reached else FIXED_COUNT_NOT_REACHED,
        }


    def evaluate_at(
        self,
        round_index: int,
        *,
        observed_state: Mapping[str, Any] | None = None,
        state: Mapping[str, Any] | None = None,
        point: str | None = None,
    ) -> dict[str, Any]:
        """The ``bvl-termination-verdict-2`` at one point of round *round_index* (pure).

        *point* is the contract's timing (the rule is evaluated; a state rule
        reads *state*, whose identity document is *observed_state*) or
        ``safety_bound`` (the core's verdict once round ``max_rounds`` closed).
        A state rule that cannot be evaluated on the state is BVL-ROUND-004.
        """

        if self.timing is None:
            raise RoundError(ROUND_PLAN_INVALID, "a contract without timing has no timing point")
        point = self.timing if point is None else point
        if not _positive(round_index) or round_index > self.max_rounds:
            raise RoundError(
                MAX_ROUNDS_EXCEEDED,
                f"round {round_index!r} is outside the safety bound 1..{self.max_rounds}",
            )
        closed = round_index if point in (AFTER_ROUND_CLOSE, SAFETY_BOUND) else round_index - 1
        if point == SAFETY_BOUND:
            if round_index != self.max_rounds:
                raise RoundError(
                    MAX_ROUNDS_EXCEEDED,
                    f"the safety bound is reached when round {self.max_rounds} closes, "
                    f"not round {round_index}",
                )
            reason, observed_state = SAFETY_BOUND_REACHED, None
        elif point != self.timing:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"the termination rule is evaluated {self.timing}, not {point}",
            )
        elif self.termination.observes_state:
            if not isinstance(state, Mapping) or not isinstance(observed_state, Mapping):
                raise RoundError(
                    TERMINATION_RULE_FAILED,
                    f"{self.termination.rule} has no admitted World state to read",
                )
            reason = _state_verdict(self.termination.rule, self.termination.config, state)
            observed_state = dict(observed_state)
        else:
            reached = closed >= self.termination.config["count"]
            reason = FIXED_COUNT_REACHED if reached else FIXED_COUNT_NOT_REACHED
            observed_state = None
        verdict = {
            "schema": TERMINATION_VERDICT_SCHEMA_V2,
            "rule": self.termination.identity.document(),
            "timing": self.timing,
            "point": point,
            "round": round_index,
            "rounds_closed": closed,
            "max_rounds": self.max_rounds,
            "verdict": TERMINATE if reason in _TERMINATING else CONTINUE,
            "reason": reason,
        }
        if observed_state is not None:
            # only a state rule reads a state; the verdict names exactly that one
            verdict["observed_state"] = observed_state
        return verdict

    def anchor(self, order: Sequence[tuple[str, str]]) -> str | None:
        """The node whose commit is this contract's mid-round timing point.

        *order* is the protocol's ``(node id, kind)`` in topological order.
        ``after_decision`` is the round's last decision, and every World
        transition follows it (it is *before* the World); ``after_world_
        transition`` is the round's last World transition.  A round-boundary
        timing has no anchor.
        """

        kind = TIMING_ANCHOR_KIND.get(self.timing or "")
        if kind is None:
            return None
        positions = [index for index, (_, held) in enumerate(order) if held == kind]
        if not positions:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"termination timing {self.timing} needs a {kind} node in the round body",
            )
        if self.timing == AFTER_DECISION:
            early = sorted(
                node for node, held in order[: positions[-1]] if held == "world_transition"
            )
            if early:
                raise RoundError(
                    ROUND_PLAN_INVALID,
                    f"termination timing {AFTER_DECISION} is before the World: World "
                    f"transitions {early} precede the round's last decision",
                )
        return order[positions[-1]][0]

    def require_plan(self, *, initial_state: Mapping[str, Any], world_contract: bool) -> None:
        """Refuse a plan this contract cannot terminate on evidence (BVL-ROUND-001).

        A state rule reads admitted World states, so the plan has a World
        contract; it evaluates on the plan's initial state; and a rule timed
        ``before_observation`` does not already hold there (the episode would
        execute no round).
        """

        if not self.termination.observes_state:
            return
        if not world_contract:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"{self.termination.rule} reads admitted World states: the plan declares a "
                "World contract",
            )
        try:
            reason = _state_verdict(
                self.termination.rule, self.termination.config, initial_state
            )
        except RoundError as error:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"{self.termination.rule} does not evaluate on the plan's initial state "
                f"({error})",
            ) from None
        if self.timing == BEFORE_OBSERVATION and reason in _TERMINATING:
            raise RoundError(
                ROUND_PLAN_INVALID,
                f"{self.termination.rule} timed {BEFORE_OBSERVATION} already terminates on the "
                "plan's initial state: the episode would execute no round",
            )


def _termination(document: Any) -> TerminationRuleV1:
    if not isinstance(document, Mapping) or set(document) not in (
        _TERMINATION_KEYS, _TIMED_TERMINATION_KEYS
    ):
        raise RoundError(
            ROUND_PLAN_INVALID,
            "round termination has exactly the keys ['config', 'rule'] and, to declare its "
            "timing, 'timing'",
        )
    if not isinstance(document["rule"], str):
        raise RoundError(ROUND_PLAN_INVALID, "round termination rule is a rule id")
    config = document["config"]
    if isinstance(config, Mapping):
        config = dict(config)
    if "timing" not in document:
        return TerminationRuleV1(document["rule"], config)
    if not isinstance(document["timing"], str):
        raise RoundError(ROUND_PLAN_INVALID, f"termination timing is one of {list(TIMINGS)}")
    return TerminationRuleV1(document["rule"], config, document["timing"])


def planned_rounds(protocol_document: Mapping[str, Any]) -> int:
    """The rounds a persisted Protocol IR document plans (ir-1 bound or ir-2 contract)."""

    if "round" in protocol_document:
        return RoundContractV1.from_document(protocol_document["round"]).rounds
    return protocol_document["rounds"]


def state_key(identity_document: Mapping[str, Any]) -> str:
    """One state identity document as a lookup key."""

    return json.dumps(identity_document, sort_keys=True, separators=(",", ":"))


def round_identity(
    episode: EpisodeIdentity, round_index: int, pre_state: Mapping[str, Any]
) -> RoundIdentity:
    """Episode x round index x the identity of the state the round opens on."""

    return RoundIdentity.of_payload(
        {"episode": episode.document(), "round": round_index, "pre_state": dict(pre_state)}
    )


def round_problems(
    *,
    contract: RoundContractV1 | None,
    episode: EpisodeIdentity,
    records: Sequence[Mapping[str, Any]],
    initial_state: Mapping[str, Any],
    label: str,
    order: Sequence[tuple[str, str]] = (),
    states: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Why one completed episode's rounds are not its plan's round contract.

    *records* are the episode's journal-2 records after EPISODE_OPENED, in
    journal order; *initial_state* is the identity document of the state the
    episode opened on.  Under a contract every executed round is opened once
    on the exact state the previous one closed on (its RoundIdentity
    recomputes), closes once, and is followed by exactly the verdict the
    contract derives; the episode completes at the one TERMINATE verdict and
    no round follows it.  Without a contract no round or termination evidence
    may exist.

    Under a timed contract (T4-002) the walk is the engine's: *order* is the
    protocol's ``(node id, kind)`` in topological order and *states* maps
    ``state_key`` of every evidenced World state to its document, so each
    verdict is re-derived at its declared point from the state the episode
    was then in.
    """

    if contract is not None and contract.timing is not None:
        return _timed_round_problems(
            contract, episode, records, initial_state, label, order, states or {}
        )

    lifecycle = [
        record
        for record in records
        if record["event"]
        in ("ROUND_OPENED", "STEP_READY", "ROUND_COMPLETED", "TERMINATION_EVALUATED",
            "EPISODE_COMPLETED")
    ]
    if contract is None:
        return [
            f"{label} journal-2 #{record['sequence']} is {record['event']}; the plan has no "
            "round contract"
            for record in lifecycle
            if record["event"] in ("ROUND_OPENED", "TERMINATION_EVALUATED")
        ]
    problems: list[str] = []
    shape: list[tuple[str, int | None]] = []
    for record in lifecycle:
        entry = (record["event"], record.get("round"))
        if record["event"] != "STEP_READY" or not shape or shape[-1] != entry:
            shape.append(entry)
    expected: list[tuple[str, int | None]] = []
    for index in range(1, contract.rounds + 1):
        expected += [
            ("ROUND_OPENED", index),
            ("STEP_READY", index),
            ("ROUND_COMPLETED", index),
            ("TERMINATION_EVALUATED", index),
        ]
    expected.append(("EPISODE_COMPLETED", None))
    if shape != expected:
        problems.append(
            f"{label} round lifecycle is not open -> steps -> close -> termination for "
            f"exactly rounds 1..{contract.rounds} of its round contract"
        )
        return problems
    current = dict(initial_state)
    for record in lifecycle:
        where = f"{label} journal-2 #{record['sequence']} {record['event']}"
        if record["event"] == "ROUND_OPENED":
            if record["pre_state"] != current:
                problems.append(f"{where} does not open on the state the previous round closed on")
            recomputed = round_identity(episode, record["round"], current).document()
            if record["round_identity"] != recomputed:
                problems.append(
                    f"{where} RoundIdentity does not recompute from episode x round x pre-state"
                )
        elif record["event"] == "ROUND_COMPLETED":
            current = dict(record["post_state"])
        elif record["event"] == "TERMINATION_EVALUATED":
            verdict = contract.evaluate(record["round"])
            # a timing point is a timed contract's evidence (T4-002), never this one's
            if "point" in record or record.get("termination") != verdict or record[
                "terminate"
            ] is not (verdict["verdict"] == TERMINATE):
                problems.append(f"{where} is not the verdict the plan's round contract derives")
        elif record["event"] == "EPISODE_COMPLETED" and record["rounds"] != contract.rounds:
            problems.append(
                f"{where} completed {record['rounds']} rounds; the round contract terminates "
                f"at {contract.rounds}"
            )
    return problems


_TIMED_LIFECYCLE = (
    "ROUND_OPENED", "STEP_READY", "ROUND_COMPLETED", "TERMINATION_EVALUATED",
    "EPISODE_COMPLETED",
)


def _timed_round_problems(
    contract: RoundContractV1,
    episode: EpisodeIdentity,
    records: Sequence[Mapping[str, Any]],
    initial_state: Mapping[str, Any],
    label: str,
    order: Sequence[tuple[str, str]],
    states: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """The timed lifecycle, re-walked: every verdict at its point, on its state."""

    wrong = [
        f"{label} round lifecycle is not its round contract's: every round opens, runs its "
        f"steps and closes, and the termination rule is evaluated {contract.timing}"
    ]
    try:
        anchor = contract.anchor(order)
    except RoundError as error:
        return [f"{label} {error}"]
    problems: list[str] = []
    current = dict(initial_state)
    pending = [
        r for r in records if r["event"] in _TIMED_LIFECYCLE or r["event"] == "WORLD_APPLIED"
    ]
    cursor = 0

    def take(event: str, round_index: int | None) -> Mapping[str, Any] | None:
        nonlocal cursor, current
        while cursor < len(pending) and pending[cursor]["event"] == "WORLD_APPLIED":
            current = dict(pending[cursor]["post_state"])
            cursor += 1
        if cursor == len(pending):
            return None
        record = pending[cursor]
        if record["event"] != event or (
            round_index is not None and record.get("round") != round_index
        ):
            return None
        cursor += 1
        return record

    def verdict(point: str, round_index: int) -> bool | None:
        record = take("TERMINATION_EVALUATED", round_index)
        if record is None:
            return None
        where = f"{label} journal-2 #{record['sequence']} TERMINATION_EVALUATED"
        state = states.get(state_key(current)) if contract.termination.observes_state else None
        try:
            expected = contract.evaluate_at(
                round_index, observed_state=current, state=state, point=point
            )
        except RoundError as error:
            problems.append(f"{where} cannot be re-derived: {error}")
            return True
        if (
            record.get("termination") != expected
            or record.get("point") != point
            or record["terminate"] is not (expected["verdict"] == TERMINATE)
        ):
            problems.append(
                f"{where} is not the verdict the plan's round contract derives {point} of "
                f"round {round_index}"
            )
        return expected["verdict"] == TERMINATE

    round_index, executed = 0, 0
    while True:
        round_index += 1
        if contract.timing == BEFORE_OBSERVATION:
            stop = verdict(BEFORE_OBSERVATION, round_index)
            if stop is None:
                return wrong
            if stop:
                break
        opened = take("ROUND_OPENED", round_index)
        if opened is None:
            return wrong
        where = f"{label} journal-2 #{opened['sequence']} ROUND_OPENED"
        if opened["pre_state"] != current:
            problems.append(f"{where} does not open on the state the previous round closed on")
        if opened["round_identity"] != round_identity(episode, round_index, current).document():
            problems.append(
                f"{where} RoundIdentity does not recompute from episode x round x pre-state"
            )
        cut = False
        for node_id, _ in order:
            ready = take("STEP_READY", round_index)
            if ready is None:
                return wrong
            if node_id != anchor:
                continue
            stop = verdict(contract.timing, round_index)
            if stop is None:
                return wrong
            evaluated = pending[cursor - 1]
            if any(
                r.get("step") == ready["step"] and r["sequence"] > evaluated["sequence"]
                for r in records
            ):
                problems.append(
                    f"{label} journal-2 #{evaluated['sequence']} TERMINATION_EVALUATED precedes "
                    f"the commit of its timing point {node_id!r}"
                )
            if stop:
                cut = True
                break
        closed = take("ROUND_COMPLETED", round_index)
        if closed is None:
            return wrong
        current = dict(closed["post_state"])
        executed = round_index
        if cut:
            break
        if contract.timing == AFTER_ROUND_CLOSE:
            stop = verdict(AFTER_ROUND_CLOSE, round_index)
            if stop is None:
                return wrong
            if stop:
                break
        if round_index == contract.max_rounds:
            if verdict(SAFETY_BOUND, round_index) is None:
                return wrong
            break
    completed = take("EPISODE_COMPLETED", None)
    if completed is None or cursor != len(pending):
        return wrong
    if completed["rounds"] != executed:
        problems.append(
            f"{label} journal-2 #{completed['sequence']} EPISODE_COMPLETED completed "
            f"{completed['rounds']} rounds; the round contract terminates at {executed}"
        )
    return problems
