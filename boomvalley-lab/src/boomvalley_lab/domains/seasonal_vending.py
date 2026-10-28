"""Seasonal vending: one order and one business day per transition, under seasons.

    state   bvl.seasonal-vending-state:1  ``day``           business days elapsed
                                          ``cash``          cash on hand
                                          ``lead_time``     days from an order to its
                                                            delivery
                                          ``order_fee``     the fixed fee of one executed
                                                            order
                                          ``holding_cost``  the charge per unit on the
                                                            shelves at the close of a day
                                          ``slots``         slot -> ``stock``,
                                                            ``max_stock``, ``in_transit``,
                                                            ``price`` and ``unit_cost``
                                          ``pipeline``      the orders under way:
                                                            ``slot_id``, ``quantity``,
                                                            ``arrives_on``
                                          ``sold``          units sold so far
                                          ``unmet``         demand that found no stock
                                          ``season``        the name of the regime
                                          ``demand``        slot -> the units asked for
                                                            per day, a cycle over the
                                                            days: the regime
                                          ``calendar``      the seasons to come:
                                                            ``after_day``, ``season``,
                                                            ``demand``
    action  bvl.vending-action:1          ``slot_id``       the slot to order for
                                          ``quantity``      units to order

The day is the longitudinal vending day (``bvl.vending-world:2``), in its
order: the order is ruled on the state the round opened on - the room of a slot
is ``max(0, max_stock - stock - in_transit)``, and an order is paid when it is
placed (``unit_cost`` per unit and one ``order_fee``); ADMISSIBLE within the
room and the cash, CLIPPED above either, INADMISSIBLE for an unknown slot, a
non-positive quantity, a full slot or cash that cannot pay one unit - then the
pipeline orders due are delivered (a ``delivery`` event), each slot's demand of
the day is served from its stock (a ``demand`` event) and the units left are
charged (a ``holding_cost`` event).

The regime (T4-008, P16 13.5).  ``season`` and ``demand`` are the World's
regime fields: what the shop is asked for is the season's, not the slot's.
When the day that just closed is the ``after_day`` of a calendar entry, the
season and its demand become that entry's, and the transition states it as a
``season_change`` exogenous event - the World's one regime event.  A calendar
may hold any number of entries; of several for one day the last stated is the
season, and an entry that names the season the shop is already in changes
nothing and states nothing.  The calendar is read from the declared state
alone, so every season to come is part of the plan's initial World state and
of every state identity: nothing an actor decides moves the regime, and no
transition moves it without stating the event.  An INADMISSIBLE order and
NO_ACTION execute nothing; the day passes and the season changes all the same
(EXOGENOUS_PROGRESSION).  The World is DETERMINISTIC.

The domain of the state (SV-11, ``state_domain``): the counts - ``day``,
``lead_time``, ``order_fee``, ``holding_cost``, ``sold``, ``unmet``, each
slot's ``stock``, ``max_stock``, ``in_transit``, ``price`` and ``unit_cost``,
every demand of a cycle, of the season and of the calendar - are integers
>= 0; ``cash`` is an integer; a
pipeline order is a positive quantity for a slot of the state, due on a day,
and a slot's ``in_transit`` is what its pipeline orders carry.  The day keeps
a state of the domain in it - no count falls below zero, ``stock +
in_transit`` never rises above the larger of ``max_stock`` and what it was -
and says nothing of a state outside it, so a study that declares one is
refused before anything runs (BVL-WORLD-003).
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

SEASONAL_VENDING_WORLD = "bvl.seasonal-vending-world:1"
SEASONAL_VENDING_STATE = WorldStateSchemaV1(
    "bvl.seasonal-vending-state", 1,
    {"calendar": "array", "cash": "integer", "day": "integer", "demand": "object",
     "holding_cost": "integer", "lead_time": "integer", "order_fee": "integer",
     "pipeline": "array", "season": "string", "slots": "object", "sold": "integer",
     "unmet": "integer"},
)
SEASONAL_VENDING_ACTION = WorldActionSchemaV1(
    "bvl.vending-action", 1, {"quantity": "integer", "slot_id": "string"}
)
DELIVERY_EVENT = "delivery"
DEMAND_EVENT = "demand"
HOLDING_EVENT = "holding_cost"
SEASON_CHANGE_EVENT = "season_change"
REGIME_FIELDS = ("demand", "season")
SEASONAL_VENDING_PROGRESSION = WorldProgressionV1(
    no_action=EXOGENOUS_PROGRESSION,
    exogenous_events=(DELIVERY_EVENT, DEMAND_EVENT, HOLDING_EVENT, SEASON_CHANGE_EVENT),
    regime_events=(SEASON_CHANGE_EVENT,),
    regime_fields=REGIME_FIELDS,
)
SEASONAL_VENDING_DOMAIN = (
    *(("count", name) for name in ("day", "holding_cost", "lead_time", "order_fee", "sold",
                                   "unmet")),
    ("integer", "cash"),
    *(("count", f"slots.*.{name}") for name in ("in_transit", "max_stock", "price", "stock",
                                                "unit_cost")),
    ("positive", "pipeline.#.quantity"),
    ("integer", "pipeline.#.arrives_on"),
    ("carried", "slots", "in_transit", "pipeline", "slot_id", "quantity"),
    ("string", "season"),
    ("count", "demand.*.#"),
    ("integer", "calendar.#.after_day"),
    ("string", "calendar.#.season"),
    ("count", "calendar.#.demand.*.#"),
)

ADMITTED = "admitted"
PARTIAL = "partial"
UNKNOWN_SLOT = "unknown_slot"
NON_POSITIVE_QUANTITY = "non_positive_quantity"
NO_ROOM = "no_room"
NO_CASH = "insufficient_cash"
NOT_REQUESTED = "no_action"


def _ruled(
    state: Mapping[str, Any], requested_action: Mapping[str, Any] | None
) -> tuple[str, int]:
    """The ruling on an order and the units admitted, on the state the round opened on."""

    if requested_action is None:
        return NOT_REQUESTED, 0
    slot = state["slots"].get(requested_action.get("slot_id"))
    quantity = requested_action.get("quantity")
    if slot is None:
        return UNKNOWN_SLOT, 0
    if quantity <= 0:
        return NON_POSITIVE_QUANTITY, 0
    room = max(0, slot["max_stock"] - slot["stock"] - slot["in_transit"])
    if room == 0:
        return NO_ROOM, 0
    funds = state["cash"] - state["order_fee"]
    payable = quantity if slot["unit_cost"] <= 0 else max(0, funds) // slot["unit_cost"]
    if funds < 0 or payable == 0:
        return NO_CASH, 0
    take = min(quantity, room, payable)
    return (ADMITTED if take == quantity else PARTIAL), take


def _season_after(state: Mapping[str, Any], day: int) -> Mapping[str, Any] | None:
    """The calendar entry whose season opens when *day* closes, if it is another regime."""

    opening = [entry for entry in state["calendar"] if entry["after_day"] == day]
    if not opening:
        return None
    entry = opening[-1]
    if (entry["season"], entry["demand"]) == (state["season"], state["demand"]):
        return None
    return entry


@dataclass(frozen=True)
class SeasonalVendingWorldV1:
    """The longitudinal vending day; the season, and its demand, change by the calendar."""

    plugin_identity: str = SEASONAL_VENDING_WORLD
    state_schema: WorldStateSchemaV1 = SEASONAL_VENDING_STATE
    action_schema: WorldActionSchemaV1 = SEASONAL_VENDING_ACTION
    progression: WorldProgressionV1 = SEASONAL_VENDING_PROGRESSION
    state_domain: tuple[tuple[str, ...], ...] = SEASONAL_VENDING_DOMAIN

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any] | None, *, seed: int
    ) -> WorldTransition:
        del seed
        requested = {} if requested_action is None else dict(requested_action)
        day = state["day"] + 1
        slots = {slot_id: dict(slot) for slot_id, slot in state["slots"].items()}
        pipeline = [dict(order) for order in state["pipeline"]]
        cash = state["cash"]

        ruling, take = _ruled(state, requested_action)
        ordered: dict[str, Any] = {}
        order_cost = 0
        if take:
            slot_id = requested["slot_id"]
            ordered = {"quantity": take, "slot_id": slot_id}
            order_cost = take * slots[slot_id]["unit_cost"] + state["order_fee"]
            cash -= order_cost
            slots[slot_id]["in_transit"] += take
            pipeline.append(
                {"arrives_on": day + state["lead_time"], "quantity": take, "slot_id": slot_id}
            )

        events: list[dict[str, Any]] = []
        due = [order for order in pipeline if order["arrives_on"] <= day]
        if due:
            for order in due:
                slot = slots[order["slot_id"]]
                slot["in_transit"] -= order["quantity"]
                slot["stock"] += order["quantity"]
            pipeline = [order for order in pipeline if order["arrives_on"] > day]
            events.append({"event": DELIVERY_EVENT, "detail": {"day": day, "delivered": due}})

        season, demand = state["season"], state["demand"]
        served: dict[str, Any] = {}
        revenue = 0
        for slot_id in sorted(slots):
            slot = slots[slot_id]
            cycle = demand.get(slot_id) or []
            asked = cycle[(day - 1) % len(cycle)] if cycle else 0
            sold = min(slot["stock"], asked)
            slot["stock"] -= sold
            revenue += sold * slot["price"]
            served[slot_id] = {"demand": asked, "sold": sold, "unmet": asked - sold}
        cash += revenue
        events.append(
            {
                "event": DEMAND_EVENT,
                "detail": {"day": day, "revenue": revenue, "season": season, "slots": served},
            }
        )

        shelved = sum(slot["stock"] for slot in slots.values())
        charge = shelved * state["holding_cost"]
        cash -= charge
        events.append(
            {"event": HOLDING_EVENT, "detail": {"charge": charge, "day": day, "units": shelved}}
        )

        opening = _season_after(state, day)
        next_season, next_demand = season, demand
        if opening is not None:
            # the regime changes here, and only as this stated event
            next_season, next_demand = opening["season"], opening["demand"]
            events.append(
                {
                    "event": SEASON_CHANGE_EVENT,
                    "detail": {
                        "after_day": day, "from_demand": demand, "from_season": season,
                        "to_demand": next_demand, "to_season": next_season,
                    },
                }
            )

        sold_today = sum(row["sold"] for row in served.values())
        unmet_today = sum(row["unmet"] for row in served.values())
        post = {
            "calendar": state["calendar"],
            "cash": cash,
            "day": day,
            "demand": next_demand,
            "holding_cost": state["holding_cost"],
            "lead_time": state["lead_time"],
            "order_fee": state["order_fee"],
            "pipeline": pipeline,
            "season": next_season,
            "slots": slots,
            "sold": state["sold"] + sold_today,
            "unmet": state["unmet"] + unmet_today,
        }
        if requested_action is None:
            verdict = NO_ACTION_VERDICT
        elif not take:
            verdict = "INADMISSIBLE"
        else:
            verdict = "ADMISSIBLE" if ruling == ADMITTED else "CLIPPED"
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict=verdict,
            admissible_action=ordered,
            executed_action=ordered,
            pre_state=dict(state),
            post_state=post,
            outcome={
                "cash": cash, "day": day, "delivered": sum(o["quantity"] for o in due),
                "holding_charge": charge, "order_cost": order_cost, "ordered": take,
                "revenue": revenue, "ruling": ruling, "season": season, "sold": sold_today,
                "unmet": unmet_today,
            },
            executed=bool(take),
            action_input=ACTION_INPUT if requested_action is not None else NO_ACTION_INPUT,
            exogenous_events=tuple(events),
        )
