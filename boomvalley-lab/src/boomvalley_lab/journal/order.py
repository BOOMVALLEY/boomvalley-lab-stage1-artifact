"""The frozen schedule order — what the lock registered, not which cells exist.

A schedule is an ordered sequence, and freezing it froze the order as well as
the membership. Verification that only asks "is every scheduled record here?"
accepts a run that executed the registered records in a different order, which
is a different execution than the one that was registered:

    same scheduled members  !=  same frozen execution order

The invariant, read off the frozen schedule semantics:

    the records named by the journal's durable intents, in the order those
    intents were written, are exactly the first N records of the locked
    schedule — same records, same positions, no gaps and no reordering.

Everything follows from that one sentence. A run that stopped early is a
prefix and passes; a resumed run continues at the next registered record and
passes; a run that swapped two records, skipped one, or replayed one is not a
prefix and is refused.

Two things this deliberately does NOT do:

    it never reads an event's own `position` field — a forged journal carries
    whatever positions it likes, so position is evidence about a record, not
    about the order in which the run actually began its attempts;

    it says nothing about what happened *inside* an attempt. Legal predecessor,
    multiplicity, terminality and run/session attribution are the per-attempt
    grammar (`journal.grammar`), and a history can satisfy one and violate the
    other. They are separate invariants and stay separate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boomvalley_lab.declare.cellspace import ExecutionRecord
from boomvalley_lab.journal import events as ev


def intent_sequence(journal: Sequence[Mapping]) -> list[str]:
    """The records this run began an attempt on, in the order it began them.

    The durable intent is what marks an attempt as started (R1), so the order
    of intents in the append-only journal IS the order of execution. Nothing
    here is derived from the schedule.
    """
    return [event["record"] for event in journal
            if event["event"] == ev.INTENT_RECORDED and "record" in event]


def frozen_sequence(records: Sequence[ExecutionRecord]) -> list[str]:
    """The registered execution order, from the locked schedule."""
    return [record.key for record in records]


def problems(records: Sequence[ExecutionRecord], journal: Sequence[Mapping]) -> list[str]:
    """Where the run's execution order departs from the registered one."""
    frozen = frozen_sequence(records)
    started = intent_sequence(journal)

    if len(started) > len(frozen):
        return [f"the run began {len(started)} attempts for a schedule of {len(frozen)} "
                "records; the registered schedule cannot be extended"]

    for position, (began, registered) in enumerate(zip(started, frozen, strict=False)):
        if began != registered:
            return [f"execution order departs from the locked schedule at position "
                    f"{position}: the schedule registers {registered}, the run began "
                    f"{began}"]
    return []


def executed_prefix(records: Sequence[ExecutionRecord],
                    journal: Sequence[Mapping]) -> int:
    """How far into the registered schedule this run legally got.

    Only meaningful when `problems` is empty; a run whose order already
    departed from the schedule has no well-defined prefix.
    """
    return len(intent_sequence(journal))
