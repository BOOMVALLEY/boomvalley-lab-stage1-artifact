"""The domain World plugins this installation ships (T3-008, P15).

A domain is a World plugin and a declaration, nothing else.  Each module here
is one domain: a World that owns a domain rule under the kernel's World
contract (``kernel.world``) - its state schema, its action schema, what
NO_ACTION means to it and the exogenous events it may state.  A domain World
reads its whole domain from the serialized state it is handed, holds no state
of its own, and reaches nothing but ``kernel.world``: it orchestrates no actor,
decides no authority and writes no evidence.

    bvl.route-world:1    ``domains.route``    route choice over a network with
                                              closures and congestion
    bvl.restock-world:1  ``domains.restock``  inventory replenishment under a
                                              per-period demand
    bvl.vending-world:1  ``domains.vending``  vending replenishment: an order is
                                              admitted up to its slot's room
    bvl.seasonal-restock-world:1  ``domains.seasonal``  replenishment under a
                                              demand regime that shifts once, as
                                              a declared regime event (T4-004)
    bvl.vending-world:2  ``domains.vending_days``  longitudinal vending: an order,
                                              then a business day - deliveries
                                              after a lead time, demand, costs
                                              (T4-007)
    bvl.seasonal-vending-world:1  ``domains.seasonal_vending``  that day under
                                              seasons: the demand regime changes by
                                              a declared calendar, each change a
                                              declared regime event (T4-008)
    bvl.negotiation-world:1  ``domains.negotiation``  bilateral price negotiation:
                                              one move of one side per transition,
                                              to an agreement, a walk-away or a
                                              deadline (T4-009)

``WORLDS`` is all the lifecycle reads: plugin identity -> factory.  The plugin
catalog registers every entry as a ``PluginType.WORLD`` without naming one, so
adding a domain is a module here and a line in this table - no kernel,
lifecycle, verifier or CLI change.  Nothing outside this package names a
domain World, its schemas or its fields.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from boomvalley_lab.domains.negotiation import NEGOTIATION_WORLD, NegotiationWorldV1
from boomvalley_lab.domains.restock import RESTOCK_WORLD, RestockWorldV1
from boomvalley_lab.domains.route import ROUTE_WORLD, RouteWorldV1
from boomvalley_lab.domains.seasonal import SEASONAL_WORLD, SeasonalRestockWorldV1
from boomvalley_lab.domains.seasonal_vending import (
    SEASONAL_VENDING_WORLD,
    SeasonalVendingWorldV1,
)
from boomvalley_lab.domains.vending import VENDING_WORLD, VendingWorldV1
from boomvalley_lab.domains.vending_days import VENDING_DAYS_WORLD, VendingDaysWorldV2

WORLDS: Mapping[str, Callable[[], Any]] = MappingProxyType(
    {
        ROUTE_WORLD: RouteWorldV1,
        RESTOCK_WORLD: RestockWorldV1,
        VENDING_WORLD: VendingWorldV1,
        SEASONAL_WORLD: SeasonalRestockWorldV1,
        VENDING_DAYS_WORLD: VendingDaysWorldV2,
        SEASONAL_VENDING_WORLD: SeasonalVendingWorldV1,
        NEGOTIATION_WORLD: NegotiationWorldV1,
    }
)
