"""Inventory replenishment: one period per transition.

    state   bvl.restock-state:1   ``stock``     units on hand
                                  ``capacity``  the most the shelf holds
                                  ``demand``    units asked for each period
                                  ``period``    periods elapsed
                                  ``sold``      units sold so far
                                  ``unmet``     demand that found no stock
    action  bvl.restock-action:1  ``order_qty`` units to order

The domain rule: an order within the free capacity is ADMISSIBLE and delivered
in full; one above it is CLIPPED to the free capacity; a negative one is
INADMISSIBLE and nothing is delivered.  Then the period's demand is served
from what is on hand.  The demand is the environment's, not the decision's:
it occurs whatever was ordered - under an INADMISSIBLE order and under
NO_ACTION too - and every transition states it as a ``demand`` exogenous
event.  NO_ACTION is therefore EXOGENOUS_PROGRESSION: nothing is executed and
the period still passes.  The World is DETERMINISTIC.

The domain of the state (SV-11, ``state_domain``): every field is a count, an
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

RESTOCK_WORLD = "bvl.restock-world:1"
RESTOCK_STATE = WorldStateSchemaV1(
    "bvl.restock-state", 1,
    {"capacity": "integer", "demand": "integer", "period": "integer", "sold": "integer",
     "stock": "integer", "unmet": "integer"},
)
RESTOCK_ACTION = WorldActionSchemaV1("bvl.restock-action", 1, {"order_qty": "integer"})
DEMAND_EVENT = "demand"
RESTOCK_PROGRESSION = WorldProgressionV1(
    no_action=EXOGENOUS_PROGRESSION, exogenous_events=(DEMAND_EVENT,)
)
RESTOCK_DOMAIN = tuple(
    ("count", name) for name in ("capacity", "demand", "period", "sold", "stock", "unmet")
)


@dataclass(frozen=True)
class RestockWorldV1:
    """An order is delivered up to capacity, then the period's demand is served."""

    plugin_identity: str = RESTOCK_WORLD
    state_schema: WorldStateSchemaV1 = RESTOCK_STATE
    action_schema: WorldActionSchemaV1 = RESTOCK_ACTION
    progression: WorldProgressionV1 = RESTOCK_PROGRESSION
    state_domain: tuple[tuple[str, ...], ...] = RESTOCK_DOMAIN

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
        sold = min(on_hand, state["demand"])
        unmet = state["demand"] - sold
        post = {
            "capacity": state["capacity"],
            "demand": state["demand"],
            "period": state["period"] + 1,
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
                "delivered": delivered, "sold": sold, "unmet": unmet, "stock": post["stock"],
            },
            executed=bool(admissible),
            action_input=ACTION_INPUT if requested_action is not None else NO_ACTION_INPUT,
            exogenous_events=(
                {
                    "event": DEMAND_EVENT,
                    "detail": {"demand": state["demand"], "sold": sold, "unmet": unmet},
                },
            ),
        )
