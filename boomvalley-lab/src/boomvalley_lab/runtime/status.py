"""Run status from evidence alone — no provider is ever called.

`status` is the resume plan plus the lock identities and custody counts: it
runs the SAME assessment the executor and `resume` run (`resume.planner`), so
what status shows and what resume will do can never disagree.
"""

from __future__ import annotations

from pathlib import Path

from boomvalley_lab.custody.entries import FRESH, RECOVERED, CustodyLedger
from boomvalley_lab.resume.planner import plan
from boomvalley_lab.runtime.resume import evidence
from boomvalley_lab.runtime.run import Run


def status(directory: Path) -> dict:
    run = Run.open(directory)
    current = plan(evidence(run))
    accepted = [entry for held in CustodyLedger(run.directory).by_record().values()
                for entry in held]
    return {
        **current.document(),
        "lock": run.lock["identities"],
        "custody": {
            "entries": len(accepted),
            FRESH: sum(1 for e in accepted if e["origin"] == FRESH),
            RECOVERED: sum(1 for e in accepted if e["origin"] == RECOVERED),
        },
        "all_persisted": current.all_complete,
    }
