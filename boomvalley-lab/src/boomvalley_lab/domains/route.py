"""Route choice: one trip per transition over the network the state holds.

    state   bvl.route-state:1   ``costs``       route -> integer travel cost
                                ``closed``      the routes that cannot be taken
                                ``trips``       trips made so far
                                ``total_cost``  what they cost together
    action  bvl.route-action:1  ``route``       the route to take

The domain rule: an open route of the network is ADMISSIBLE and travelled at
its cost; a closed one is CLIPPED - the trip is diverted to the cheapest open
route (ties by name); a route the network does not have, or any route when
none is open, is INADMISSIBLE and no trip is made.  A travelled route costs
``CONGESTION`` more next time, so a round's state is the next round's input.
NO_ACTION is NO_TRANSITION: no trip, the state is kept.  The World states no
exogenous event and is DETERMINISTIC.

The domain of the state (SV-13, ``state_domain``): every cost, ``trips`` and
``total_cost`` are counts - integers >= 0, never a boolean - and ``closed``
lists route names.  The rule keeps a state of the domain in it and says
nothing of a state outside it (a negative cost makes a trip pay), so a study
that declares one is refused before anything runs (BVL-WORLD-003).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boomvalley_lab.kernel.world import (
    ACTION_INPUT,
    NO_ACTION_INPUT,
    NO_ACTION_VERDICT,
    NO_TRANSITION,
    WorldActionSchemaV1,
    WorldProgressionV1,
    WorldStateSchemaV1,
    WorldTransition,
)

ROUTE_WORLD = "bvl.route-world:1"
ROUTE_STATE = WorldStateSchemaV1(
    "bvl.route-state", 1,
    {"closed": "array", "costs": "object", "total_cost": "integer", "trips": "integer"},
)
ROUTE_ACTION = WorldActionSchemaV1("bvl.route-action", 1, {"route": "string"})
ROUTE_PROGRESSION = WorldProgressionV1(no_action=NO_TRANSITION)
CONGESTION = 1
ROUTE_DOMAIN = (
    ("string", "closed.#"), ("count", "costs.*"), ("count", "total_cost"), ("count", "trips"),
)


@dataclass(frozen=True)
class RouteWorldV1:
    """One trip over the chosen route of the state's network."""

    plugin_identity: str = ROUTE_WORLD
    state_schema: WorldStateSchemaV1 = ROUTE_STATE
    action_schema: WorldActionSchemaV1 = ROUTE_ACTION
    progression: WorldProgressionV1 = ROUTE_PROGRESSION
    state_domain: tuple[tuple[str, ...], ...] = ROUTE_DOMAIN

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any] | None, *, seed: int
    ) -> WorldTransition:
        del seed
        costs = dict(state["costs"])
        requested = {} if requested_action is None else dict(requested_action)
        open_routes = sorted(
            (cost, route) for route, cost in costs.items() if route not in state["closed"]
        )
        route = requested.get("route")
        if route not in costs or not open_routes:
            # NO_ACTION, no such route, or nothing to divert to: no trip is made
            return WorldTransition(
                requested_action=requested,
                admissibility_verdict=(
                    NO_ACTION_VERDICT if requested_action is None else "INADMISSIBLE"
                ),
                admissible_action={},
                executed_action={},
                pre_state=dict(state),
                post_state=dict(state),
                outcome={"travelled": False, "total_cost": state["total_cost"]},
                executed=False,
                action_input=ACTION_INPUT if requested_action is not None else NO_ACTION_INPUT,
            )
        diverted = route in state["closed"]
        if diverted:
            route = open_routes[0][1]
        cost = costs[route]
        travelled = {"route": route}
        post = {
            "closed": list(state["closed"]),
            "costs": {**costs, route: cost + CONGESTION},
            "total_cost": state["total_cost"] + cost,
            "trips": state["trips"] + 1,
        }
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict="CLIPPED" if diverted else "ADMISSIBLE",
            admissible_action=travelled,
            executed_action=travelled,
            pre_state=dict(state),
            post_state=post,
            outcome={
                "travelled": True, "route": route, "cost": cost,
                "total_cost": post["total_cost"],
            },
            executed=True,
        )
