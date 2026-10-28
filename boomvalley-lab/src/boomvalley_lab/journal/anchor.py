"""The Input Lock anchor — one three-way rule for every reader (Input Contract §10.4).

An INPUT_LOCKED run is classified by its JOURNAL, never by `run.json` or
`input.json`:

    VALID    journal[0] is RUN_OPENED, journal[1] is INPUT_LOCK_BOUND, it is the
             only INPUT_LOCK_BOUND, it is a well-formed closed record, and its
             run equals RUN_OPENED.run                      -> INPUT_LOCKED
    INVALID  at least one INPUT_LOCK_BOUND exists and VALID does not hold
                                     -> INPUT_DRIFT INPUT_LOCK_ANCHOR_INVALID
    ABSENT   no INPUT_LOCK_BOUND anywhere                   -> NOT_INPUT_LOCKED

ABSENT is not INVALID. ABSENT is the legacy state; INVALID is always a refusal
and never falls back to NOT_INPUT_LOCKED, and it is never repaired.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from boomvalley_lab.core.errors import EvidenceError, InputRefusal
from boomvalley_lab.core.layout import INPUT_FILE, PREFLIGHT_DIR, RUN_FILE
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal.log import Journal

ANCHOR_KEYS = ("at", "event", "input_digest", "input_identity", "run")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
EII = re.compile(r"experiment_input:sha256:[0-9a-f]{64}")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

INPUT_LOCKED = "INPUT_LOCKED"
NOT_INPUT_LOCKED = "NOT_INPUT_LOCKED"


class AnchorState(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    ABSENT = "ABSENT"


@dataclass(frozen=True)
class Anchor:
    state: AnchorState
    event: Mapping | None = None
    problem: str | None = None

    @property
    def classification(self) -> str:
        if self.state is AnchorState.VALID:
            return INPUT_LOCKED
        if self.state is AnchorState.ABSENT:
            return NOT_INPUT_LOCKED
        return "INPUT_DRIFT"


def _malformed(event: Mapping) -> str | None:
    if tuple(sorted(event)) != ANCHOR_KEYS:
        return f"INPUT_LOCK_BOUND is a closed record of exactly {list(ANCHOR_KEYS)}"
    if not isinstance(event["at"], str):
        return "INPUT_LOCK_BOUND.at is not a string"
    if not isinstance(event["input_digest"], str) or not DIGEST.fullmatch(event["input_digest"]):
        return "INPUT_LOCK_BOUND.input_digest is not a sha256 digest"
    if not isinstance(event["input_identity"], str) or not EII.fullmatch(event["input_identity"]):
        return "INPUT_LOCK_BOUND.input_identity is not an ExperimentInputIdentity"
    if not isinstance(event["run"], str) or not TOKEN.fullmatch(event["run"]):
        return "INPUT_LOCK_BOUND.run is not a run id"
    return None


def classify(journal: Sequence[Mapping]) -> Anchor:
    """The anchor state of a journal already read under the frozen rules."""
    at = [i for i, event in enumerate(journal) if event.get("event") == ev.INPUT_LOCK_BOUND]
    if not at:
        return Anchor(AnchorState.ABSENT)
    if len(at) > 1:
        return Anchor(AnchorState.INVALID,
                      problem=f"the journal carries {len(at)} INPUT_LOCK_BOUND events at {at}")
    if at[0] != 1:
        return Anchor(AnchorState.INVALID,
                      problem=f"INPUT_LOCK_BOUND is at position {at[0]}, not 1")
    if not journal or journal[0].get("event") != ev.RUN_OPENED:
        return Anchor(AnchorState.INVALID, problem="INPUT_LOCK_BOUND does not follow RUN_OPENED")
    event = journal[1]
    problem = _malformed(event)
    if problem is not None:
        return Anchor(AnchorState.INVALID, problem=problem)
    if event["run"] != journal[0].get("run"):
        return Anchor(AnchorState.INVALID,
                      problem=f"INPUT_LOCK_BOUND names run {event['run']!r}, RUN_OPENED "
                              f"{journal[0].get('run')!r}")
    return Anchor(AnchorState.VALID, event=dict(event))


# ======================================================== the legacy side
def _drift(code: str, detail: str) -> InputRefusal:
    return InputRefusal("INPUT_DRIFT", code, detail, layer="IL", path="journal#")


def artifacts_present(directory: Path) -> list[str]:
    """The Input Lock artifacts a directory holds, whatever its journal says."""
    found = []
    if (directory / INPUT_FILE).exists():
        found.append(INPUT_FILE)
    if (directory / PREFLIGHT_DIR).exists():
        found.append(f"{PREFLIGHT_DIR}/")
    try:
        run_document = load_bytes((directory / RUN_FILE).read_bytes())
        if isinstance(run_document, Mapping) and "input" in run_document:
            found.append(f"{RUN_FILE}.input")
    except (OSError, MalformedJSON):
        pass
    return found


def legacy_guard(directory: Path) -> None:
    """IR-06: a legacy write path refuses an Input-Locked or unanchored directory
    BEFORE any write, in the order A (VALID) / B (INVALID) / C (artifacts, ABSENT)."""
    directory = Path(directory)
    try:
        journal = Journal(directory).read()
    except EvidenceError:
        return            # the legacy path refuses a broken journal on its own terms
    anchor = classify(journal)
    if anchor.state is AnchorState.VALID:
        raise _drift("INPUT_LOCKED_RUN_REQUIRES_BVL",
                    f"{directory} is an INPUT_LOCKED run; resume it with `bvl resume`")
    if anchor.state is AnchorState.INVALID:
        raise _drift("INPUT_LOCK_ANCHOR_INVALID", anchor.problem or "invalid anchor")
    present = artifacts_present(directory)
    if present:
        raise _drift("UNANCHORED_INPUT_LOCK",
                    f"{directory} holds Input Lock artifacts {present} but its journal has no "
                    "INPUT_LOCK_BOUND; start a new run directory")
