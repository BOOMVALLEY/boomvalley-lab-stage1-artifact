"""Seasonal replenishment: one period per transition, under a demand regime.

    state   bvl.seasonal-restock-state:1   ``stock``         units on hand
                                           ``capacity``      the most the shelf holds
                                           ``demand``        units asked for each period:
                                                             the regime
                                           ``period``        periods elapsed
                                           ``sold``          units sold so far
                                           ``unmet``         demand that found no stock
                                           ``shift_at``      the period count after which
                                                             the regime shifts
                                           ``shift_demand``  the demand of the next regime
    action  bvl.seasonal-restock-action:1  ``order_qty``     units to order

The order rule is the restock one: an order within the free capacity is
ADMISSIBLE and delivered in full, one above it is CLIPPED, a negative one is
INADMISSIBLE.  Then the period's demand is served and stated as a ``demand``
exogenous event.

The regime (T4-004, P16 13.5).  ``demand`` is the World's regime field.  When
the period that just passed is period ``shift_at`` the demand becomes
``shift_demand``, and the transition states that as a ``demand_regime_shift``
exogenous event - the World's one regime event.  When the regime shifts is
read from the declared state alone, so it is part of the plan's initial World
state and of every state identity; nothing an actor decides moves it and no
transition moves it without stating the event.  NO_ACTION is
EXOGENOUS_PROGRESSION: nothing is executed, the period passes and the regime
shifts all the same.  The World is DETERMINISTIC.

The domain of the state (SV-11, ``state_domain``): every field but ``shift_at`` (an integer: one no
period reaches is a regime that never shifts) is a count, an
integer >= 0.  The rule keeps a state of the domain in it - stock never falls
below zero and never rises above the larger of the capacity and what was on
hand - and says nothing of a state outside it, so a study that declares one
is refused before anything runs (BVL-WORLD-003).
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

SEASONAL_WORLD = "bvl.seasonal-restock-world:1"
SEASONAL_STATE = WorldStateSchemaV1(
    "bvl.seasonal-restock-state", 1,
    {"capacity": "integer", "demand": "integer", "period": "integer",
     "shift_at": "integer", "shift_demand": "integer", "sold": "integer",
     "stock": "integer", "unmet": "integer"},
)
SEASONAL_ACTION = WorldActionSchemaV1(
    "bvl.seasonal-restock-action", 1, {"order_qty": "integer"}
)
DEMAND_EVENT = "demand"
REGIME_SHIFT_EVENT = "demand_regime_shift"
REGIME_FIELD = "demand"
SEASONAL_PROGRESSION = WorldProgressionV1(
    no_action=EXOGENOUS_PROGRESSION,
    exogenous_events=(DEMAND_EVENT, REGIME_SHIFT_EVENT),
    regime_events=(REGIME_SHIFT_EVENT,),
    regime_fields=(REGIME_FIELD,),
)
SEASONAL_DOMAIN = (
    *(("count", name) for name in ("capacity", "demand", "period", "shift_demand", "sold",
                                   "stock", "unmet")),
    ("integer", "shift_at"),
)


@dataclass(frozen=True)
class SeasonalRestockWorldV1:
    """The restock rule, then the period's demand; the demand regime shifts once."""

    plugin_identity: str = SEASONAL_WORLD
    state_schema: WorldStateSchemaV1 = SEASONAL_STATE
    action_schema: WorldActionSchemaV1 = SEASONAL_ACTION
    progression: WorldProgressionV1 = SEASONAL_PROGRESSION
    state_domain: tuple[tuple[str, ...], ...] = SEASONAL_DOMAIN

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any] | None, *, seed: int
    ) -> WorldTransition:
        del seed
        requested = {} if requested_action is None else dict(requested_action)
        quantity = requested.get("order_qty")
        verdict, admissible = "INADMISSIBLE", {}  # a negative order admits nothing
        if requested_action is None:
            verdict = NO_ACTION_VERDICT
        elif quantity >= 0:
            free = max(0, state["capacity"] - state["stock"])
            verdict = "ADMISSIBLE" if quantity <= free else "CLIPPED"
            admissible = {"order_qty": min(quantity, free)}
        delivered = admissible.get("order_qty", 0)
        on_hand = state["stock"] + delivered
        demand = state["demand"]
        sold = min(on_hand, demand)
        unmet = demand - sold
        period = state["period"] + 1
        events: list[dict[str, Any]] = [
            {"event": DEMAND_EVENT, "detail": {"demand": demand, "sold": sold, "unmet": unmet}}
        ]
        next_demand = demand
        if period == state["shift_at"] and state["shift_demand"] != demand:
            # the regime changes here, and only as this stated event
            next_demand = state["shift_demand"]
            events.append(
                {
                    "event": REGIME_SHIFT_EVENT,
                    "detail": {
                        "after_period": period, "from_demand": demand, "to_demand": next_demand,
                    },
                }
            )
        post = {
            "capacity": state["capacity"],
            "demand": next_demand,
            "period": period,
            "shift_at": state["shift_at"],
            "shift_demand": state["shift_demand"],
            "sold": state["sold"] + sold,
            "stock": on_hand - sold,
            "unmet": state["unmet"] + unmet,
        }
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict=verdict,
            admissible_action=admissible,
            executed_action=admissible,
            pre_state=dict(state),
            post_state=post,
            outcome={
                "delivered": delivered, "demand": demand, "sold": sold, "stock": post["stock"],
                "unmet": unmet,
            },
            executed=bool(admissible),
            action_input=ACTION_INPUT if requested_action is not None else NO_ACTION_INPUT,
            exogenous_events=tuple(events),
        )
