"""Vending replenishment: one order on one slot per transition.

    state   bvl.vending-state:1   ``slots``     slot -> ``stock`` units on the shelf,
                                                ``max_stock`` the most the slot holds,
                                                ``in_transit`` units ordered, not arrived
    action  bvl.vending-action:1  ``slot_id``   the slot to order for
                                  ``quantity``  units to order

The domain rule: a slot's room is ``max(0, max_stock - stock - in_transit)``.
An order within the room is ADMISSIBLE and raises the slot's ``in_transit`` by
its quantity; one above it is CLIPPED to the room; an order for a slot the
state does not have, of a non-positive quantity or on a slot with no room is
INADMISSIBLE, and nothing is ordered.  ``outcome.ruling`` states which.  Units
in transit take room, so an order narrows the next one on the same slot: a
round's state is the next round's input.

The rule is the order-admission rule of the legacy vending instrument, written
here from its statement under the World contract.  This module is the one
vending World of the product; the legacy implementation is a test oracle
(``tests/lab/legacy_vending_oracle.py``) and is imported by nothing here.  As
there, nothing arrives: this World has no lead time, demand or cost.  NO_ACTION
is NO_TRANSITION, the World states no exogenous event and is DETERMINISTIC.

The domain of the state (SV-11, ``state_domain``): every slot is an object
whose ``stock``, ``max_stock`` and ``in_transit`` are counts, integers >= 0.
The rule keeps a state of the domain in it - no count falls below zero, and
``stock + in_transit`` never rises above the larger of ``max_stock`` and what
it was - and says nothing of a state outside it, so a study that declares one
is refused before anything runs (BVL-WORLD-003).
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

VENDING_WORLD = "bvl.vending-world:1"
VENDING_STATE = WorldStateSchemaV1("bvl.vending-state", 1, {"slots": "object"})
VENDING_ACTION = WorldActionSchemaV1(
    "bvl.vending-action", 1, {"quantity": "integer", "slot_id": "string"}
)
VENDING_PROGRESSION = WorldProgressionV1(no_action=NO_TRANSITION)
VENDING_DOMAIN = tuple(
    ("count", f"slots.*.{name}") for name in ("in_transit", "max_stock", "stock")
)

ADMITTED = "admitted"
PARTIAL = "partial"
UNKNOWN_SLOT = "unknown_slot"
NON_POSITIVE_QUANTITY = "non_positive_quantity"
NO_ROOM = "no_room"
NOT_REQUESTED = "no_action"


@dataclass(frozen=True)
class VendingWorldV1:
    """An order is admitted up to the room its slot has left."""

    plugin_identity: str = VENDING_WORLD
    state_schema: WorldStateSchemaV1 = VENDING_STATE
    action_schema: WorldActionSchemaV1 = VENDING_ACTION
    progression: WorldProgressionV1 = VENDING_PROGRESSION
    state_domain: tuple[tuple[str, ...], ...] = VENDING_DOMAIN

    def apply(
        self, state: Mapping[str, Any], requested_action: Mapping[str, Any] | None, *, seed: int
    ) -> WorldTransition:
        del seed
        requested = {} if requested_action is None else dict(requested_action)
        slots = {slot_id: dict(slot) for slot_id, slot in state["slots"].items()}
        slot_id, quantity = requested.get("slot_id"), requested.get("quantity")
        slot = slots.get(slot_id)
        take = 0
        if requested_action is None:
            ruling = NOT_REQUESTED
        elif slot is None:
            ruling = UNKNOWN_SLOT
        elif quantity <= 0:
            ruling = NON_POSITIVE_QUANTITY
        else:
            room = max(0, slot["max_stock"] - slot["stock"] - slot["in_transit"])
            take = min(quantity, room)
            ruling = NO_ROOM if take == 0 else ADMITTED if take == quantity else PARTIAL
        if take == 0:
            return WorldTransition(
                requested_action=requested,
                admissibility_verdict=(
                    NO_ACTION_VERDICT if requested_action is None else "INADMISSIBLE"
                ),
                admissible_action={},
                executed_action={},
                pre_state=dict(state),
                post_state=dict(state),
                outcome={"ordered": 0, "ruling": ruling},
                executed=False,
                action_input=ACTION_INPUT if requested_action is not None else NO_ACTION_INPUT,
            )
        before = slot["in_transit"]
        slot["in_transit"] = before + take
        ordered = {"quantity": take, "slot_id": slot_id}
        return WorldTransition(
            requested_action=requested,
            admissibility_verdict="ADMISSIBLE" if ruling == ADMITTED else "CLIPPED",
            admissible_action=ordered,
            executed_action=ordered,
            pre_state=dict(state),
            post_state={"slots": slots},
            outcome={
                "ordered": take, "ruling": ruling, "slot_id": slot_id,
                "in_transit_before": before, "in_transit_after": before + take,
            },
            executed=True,
        )
