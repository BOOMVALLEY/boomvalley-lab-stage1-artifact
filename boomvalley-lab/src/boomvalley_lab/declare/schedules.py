"""Explicit schedule orders a declaration can freeze into its `schedule` section.

    balanced_paired_order(records, factor, levels)   -> [record key, ...]

The canonical order runs every cell's replicates as one block, so a factor is
confounded with call order (and with whatever state a runtime carries between
calls). `balanced_paired_order` interleaves instead: the records that differ
only in `factor` and share a replicate index are one group (one pair when the
factor has two levels), groups run in replicate order, and within replicate r
the levels run in the declared order rotated by r:

    two levels (a, b):  r0 a,b   r1 b,a   r2 a,b   ...

so over a number of replicates that is a multiple of the number of levels
(even, for two) every level holds every within-group position equally often;
over any other number it does not, and nothing here refuses that. It is a pure
function of the declaration: no randomness, no seed, the same order every
time. The result is written into
the declaration's `schedule` BEFORE the run; the lock then carries it as the
schedule identity, and the journal must follow it exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.declare.cellspace import ExecutionRecord


def balanced_paired_order(records: Sequence[ExecutionRecord], factor: str,
                          levels: Sequence[str]) -> list[str]:
    levels = list(levels)
    if len(set(levels)) != len(levels) or len(levels) < 2:
        raise DeclarationError(f"{factor!r} needs two or more distinct levels to interleave")
    groups: dict[tuple, dict[str, ExecutionRecord]] = {}
    for record in records:
        coordinates = record.cell.as_mapping()
        if factor not in coordinates:
            raise DeclarationError(f"{record.key} has no level of {factor!r}")
        rest = tuple(sorted((k, v) for k, v in coordinates.items() if k != factor))
        groups.setdefault((record.replicate, rest), {})[coordinates[factor]] = record
    incomplete = sorted(f"r{r} {dict(rest)}" for (r, rest), group in groups.items()
                        if sorted(group) != sorted(levels))
    if incomplete:
        raise DeclarationError(f"not every level of {factor!r} is present in each replicate "
                               f"group: {incomplete[:3]}")
    order = []
    for (replicate, _rest), group in sorted(groups.items()):
        shift = replicate % len(levels)
        order += [group[level].key for level in levels[shift:] + levels[:shift]]
    return order
