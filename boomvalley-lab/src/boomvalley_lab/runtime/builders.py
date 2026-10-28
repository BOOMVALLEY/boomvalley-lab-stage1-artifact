"""Request builders: the payload an execution record is sent as.

A builder is named by an id, and an id names one payload shape forever: a
change in the shape a builder produces is a new id (`...-2`), never an edit
under the old one (Input Contract §15). The files that implement each id are
listed in `registry`, so an installation's code can be digested and bound.

    boomvalley-lab-record-coordinates-1
        {"cell": <cell key>, "replicate": <int>} plus {<factor>: <level>} for
        every factor, spread after `cell` (a factor named `cell` would
        overwrite the key; `bvl` refuses such a declaration, BUILDER_RESERVED_FACTOR)
"""

from __future__ import annotations

from boomvalley_lab.declare.cellspace import ExecutionRecord

RECORD_COORDINATES = "boomvalley-lab-record-coordinates-1"


def record_coordinates(record: ExecutionRecord) -> dict:
    """The request a local run sends: the record's own coordinates, nothing else."""
    return {"cell": record.cell.key, "replicate": record.replicate, **record.cell.as_mapping()}


BUILDERS = {RECORD_COORDINATES: record_coordinates}
