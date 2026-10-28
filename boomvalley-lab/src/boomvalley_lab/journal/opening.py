"""Where a run's opening event belongs — one rule, for every reader.

`Run.create` writes RUN_OPENED into an empty directory, once, as the journal's
first line, and the journal is append-only. So the frozen contract is not only
"a RUN_OPENED exists for this run" — it is:

    exactly one RUN_OPENED, at position 0, naming this run

Both halves were enforced, in different places, by different readers:

    Run.open        journal[0] is RUN_OPENED for this run   placement, not count
    gate lock_match exactly one RUN_OPENED for this run      count, not placement

Each half is a true reading of the contract and neither is the contract, so a
journal could satisfy one reader and not the other — in both directions:

    RUN_OPENED moved behind the first INTENT_RECORDED
        runtime REFUSED (not first) -> gate ELIGIBLE (still exactly one)
        -> package VERIFIED

    a second RUN_OPENED appended
        runtime accepted (the first line is still right) -> gate VIOLATED

The first direction is the dangerous one. A journal the runtime will not open
— one it says did not happen — was certified as admissible evidence and
packaged as verified, and the disagreement itself was the only thing that
could have revealed it. A reader who only ran the gate saw nothing wrong.

Whether a persisted journal opens legally is one fact about that journal, so
it is decided once, here, and the runtime and the gate both ask. They still
differ in what they do with the answer: the runtime refuses to open the run at
all, because an object it cannot trust the opening of is not a run it can hand
out; the gate records a violation, because its job is to report on evidence it
was given rather than to disappear. Same verdict, two honest responses to it.

What this deliberately does NOT decide: whether the identities RUN_OPENED
names are the lock's (`lock_match`, which owns that comparison), whether the
event is well formed (`journal.events`, which owns the grammar), or what may
follow it (`journal.grammar` and `journal.session`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal.anchor import AnchorState, classify


def openings(journal: Sequence[Mapping]) -> list[int]:
    """Every position at which this journal claims to open a run."""
    return [i for i, event in enumerate(journal) if event["event"] == ev.RUN_OPENED]


def problems(journal: Sequence[Mapping], run: str) -> list[str]:
    """Where this journal's opening departs from the frozen contract."""
    at = openings(journal)
    if not at:
        return ["the journal never opens: it carries no RUN_OPENED"]
    if len(at) > 1:
        return [f"the journal opens {len(at)} times, at positions {at}: "
                "a run is opened once"]
    if at[0] != 0:
        return [f"the journal opens at position {at[0]}, behind "
                f"{journal[0]['event']}: a run's journal begins with RUN_OPENED"]
    named = journal[0]["run"]
    if named != run:
        return [f"the journal opens for run {named!r}, not {run!r}"]
    # an Input Lock anchor, if there is one, belongs at position 1 and nowhere
    # else; an INVALID anchor is never read past (Input Contract §10.4)
    found = classify(journal)
    if found.state is AnchorState.INVALID:
        return [f"INPUT_LOCK_ANCHOR_INVALID: {found.problem}"]
    return []
