"""Bilateral price negotiation: one move of one side per transition.

    state   bvl.negotiation-state:1   ``status``    ``open``, ``agreed``, ``broken`` or
                                                    ``expired``
                                      ``turn``      the side to move: ``buyer`` or
                                                    ``seller``
                                      ``offers``    side -> the price it has on the
                                                    table (no member: none yet)
                                      ``price``     the price agreed (0 until agreed)
                                      ``moves``     turns taken so far
                                      ``deadline``  the turns after which open talks
                                                    expire
    action  bvl.negotiation-action:1  ``side``      the side that moves
                                      ``move``      ``offer``, ``accept`` or
                                                    ``walk_away``
                                      ``price``     the price offered or accepted

The domain rule, on open talks and for the side whose turn it is:

    offer      a positive price goes on the table.  A side does not take back
               what it offered: a buyer's lower bid, a seller's higher ask, is
               CLIPPED to the offer it already has on the table.  An offer that
               reaches the other side's (a bid at or above the ask, an ask at or
               below the bid) is CLIPPED to accepting it at its price.
    accept     ADMISSIBLE only at the price the other side has on the table;
               the talks are ``agreed`` at that price.
    walk_away  ADMISSIBLE; the talks are ``broken``.

A move out of turn, an unknown side or move, a non-positive offer and an
accept of a price that is not on the table are INADMISSIBLE: nothing is
executed.  Every transition on open talks is one turn all the same - an
INADMISSIBLE move and NO_ACTION forfeit it (EXOGENOUS_PROGRESSION): the turn
passes as a ``turn_passed`` event, and when the turn count reaches the
``deadline`` with the talks still open they are ``expired``, as a ``deadline``
event.  Talks that are not open take no move and state no event: the state is
kept.  The World is DETERMINISTIC.

The domain of the state (SV-13, ``state_domain``): a price on the table is a
positive integer - what the rule admits of an offer - ``price``, ``moves`` and
``deadline`` are counts, integers >= 0, ``status`` is one of the four the talks
can have and ``turn`` one of the two sides (SV-07).  The rule says nothing of a state
outside it (an accept of a declared negative ask agrees at it), so a study
that declares one is refused before anything runs (BVL-WORLD-003).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.kernel.world import (
    ACTION_INPUT,
    EXOGENOUS_PROGRESSION,
    NO_ACTION_INPUT,
    NO_ACTION_VERDICT,
    WorldActionSchemaV1,
    WorldProgressionV1,
    WorldStateSchemaV1,
    WorldTransition,
)

NEGOTIATION_WORLD = "bvl.negotiation-world:1"
NEGOTIATION_STATE = WorldStateSchemaV1(
    "bvl.negotiation-state", 1,
    {"deadline": "integer", "moves": "integer", "offers": "object", "price": "integer",
     "status": "string", "turn": "string"},
)
NEGOTIATION_ACTION = WorldActionSchemaV1(
    "bvl.negotiation-action", 1, {"move": "string", "price": "integer", "side": "string"}
)
TURN_EVENT = "turn_passed"
DEADLINE_EVENT = "deadline"
NEGOTIATION_PROGRESSION = WorldProgressionV1(
    no_action=EXOGENOUS_PROGRESSION, exogenous_events=(DEADLINE_EVENT, TURN_EVENT)
)

BUYER = "buyer"
SELLER = "seller"
OTHER = {BUYER: SELLER, SELLER: BUYER}
OPEN = "open"
AGREED = "agreed"
BROKEN = "broken"
EXPIRED = "expired"
NEGOTIATION_DOMAIN = (
    ("count", "deadline"), ("count", "moves"), ("positive", "offers.*"), ("count", "price"),
    # SV-07: the rule branches on both; a status it does not know closed the talks
    # unsaid, and a turn it does not know is no side of them
    ("among", "status", OPEN, AGREED, BROKEN, EXPIRED), ("among", "turn", BUYER, SELLER),
)
OFFER = "offer"
ACCEPT = "accept"
WALK_AWAY = "walk_away"

TABLED = "tabled"
HELD = "held"
CROSSED = "crossed"
ACCEPTED = "accepted"
WALKED_AWAY = "walked_away"
CLOSED = "closed"
OUT_OF_TURN = "out_of_turn"
UNKNOWN_MOVE = "unknown_move"
NON_POSITIVE_PRICE = "non_positive_price"
NOT_ON_TABLE = "price_not_on_table"
NOT_REQUESTED = "no_action"


def _ruled(
    state: Mapping[str, Any], requested_action: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """The ruling on a move and the move admitted (empty: none), on open talks."""

    if requested_action is None:
        return NOT_REQUESTED, {}
    side, move, price = (requested_action.get(name) for name in ("side", "move", "price"))
    if side != state["turn"]:
        return OUT_OF_TURN, {}
    theirs = state["offers"].get(OTHER[side])
    if move == WALK_AWAY:
        return WALKED_AWAY, dict(requested_action)
    if move == ACCEPT:
        if theirs is None or price != theirs:
            return NOT_ON_TABLE, {}
        return ACCEPTED, dict(requested_action)
    if move != OFFER:
        return UNKNOWN_MOVE, {}
    if price <= 0:
        return NON_POSITIVE_PRICE, {}
    mine = state["offers"].get(side)
    ruling = TABLED
    if mine is not None and (price < mine if side == BUYER else price > mine):
        ruling, price = HELD, mine
    if theirs is not None and (price >= theirs if side == BUYER else price <= theirs):
        return CROSSED, {"move": ACCEPT, "price": theirs, "side": side}
    return ruling, {"move": OFFER, "price": price, "side": side}


@dataclass(frozen=True)
class NegotiationWorldV1:
    """One turn of the talks: the move of the side whose turn it is, then the clock."""

    plugin_identity: str = NEGOTIATION_WORLD
    state_schema: WorldStateSchemaV1 = NEGOTIATION_STATE
    action_schema: WorldActionSchemaV1 = NEGOTIATION_ACTION
    progression: WorldProgressionV1 = NEGOTIATION_PROGRESSION
    state_domain: tuple[tuple[str, ...], ...] = NEGOTIATION_DOMAIN

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any] | None, *, seed: int
    ) -> WorldTransition:
        del seed
        requested = {} if requested_action is None else dict(requested_action)
        given = ACTION_INPUT if requested_action is not None else NO_ACTION_INPUT
        status, offers, price = state["status"], dict(state["offers"]), state["price"]
        if status != OPEN:
            # closed talks take no move and no turn passes
            return WorldTransition(
                requested_action=requested,
                admissibility_verdict=(
                    NO_ACTION_VERDICT if requested_action is None else "INADMISSIBLE"
                ),
                admissible_action={},
                executed_action={},
                pre_state=dict(state),
                post_state=dict(state),
                outcome={
                    "moves": state["moves"], "offers": offers, "price": price,
                    "ruling": NOT_REQUESTED if requested_action is None else CLOSED,
                    "side": state["turn"], "status": status,
                },
                executed=False,
                action_input=given,
            )

        side = state["turn"]
        ruling, admitted = _ruled(state, requested_action)
        if admitted.get("move") == OFFER:
            offers[side] = admitted["price"]
        elif admitted.get("move") == ACCEPT:
            status, price = AGREED, admitted["price"]
        elif admitted.get("move") == WALK_AWAY:
            status = BROKEN

        moves = state["moves"] + 1
        events: list[dict[str, Any]] = [
            {"event": TURN_EVENT, "detail": {"from": side, "moves": moves, "to": OTHER[side]}}
        ]
        if status == OPEN and moves >= state["deadline"]:
            status = EXPIRED
            events.append(
                {"event": DEADLINE_EVENT, "detail": {"deadline": state["deadline"], "moves": moves}}
            )
        post = {
            "deadline": state["deadline"],
            "moves": moves,
            "offers": offers,
            "price": price,
            "status": status,
            "turn": OTHER[side],
        }
        if requested_action is None:
            verdict = NO_ACTION_VERDICT
        elif not admitted:
            verdict = "INADMISSIBLE"
        else:
            verdict = "ADMISSIBLE" if admitted == requested else "CLIPPED"
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict=verdict,
            admissible_action=admitted,
            executed_action=admitted,
            pre_state=dict(state),
            post_state=post,
            outcome={
                "moves": moves, "offers": offers, "price": price, "ruling": ruling,
                "side": side, "status": status,
            },
            executed=bool(admitted),
            action_input=given,
            exogenous_events=tuple(events),
        )
