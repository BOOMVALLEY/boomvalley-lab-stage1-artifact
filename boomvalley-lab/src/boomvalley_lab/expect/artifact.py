"""R40 — did this artifact come from the right execution for THIS cell?

R38 binds an artifact to an attempt and R39 checks that the attempt was
executed as declared. Neither notices an artifact whose own content belongs to
a different cell: a run can be perfectly bound and perfectly executed and still
have stored the wrong bytes under the right name.

The declaration states, per covered cell, the provenance the artifact must
record and the markers that are foreign to it. The observation rule is
deliberately narrow and generic:

    the artifact's recorded provenance = the markers from the DECLARED
    vocabulary (required + foreign) that appear in its content

so the product never invents an artifact format. Content that cannot be read
as text at all is not "no markers" — it is a declared claim that cannot be
checked, which is VIOLATED.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.verdict import Finding, Verdict
from boomvalley_lab.declare.rules import ArtifactPolicy

FAMILY = "artifact"
PRECONDITION_STEPS = ("custody_integrity",)


def markers_in(content: bytes, vocabulary: tuple[str, ...]) -> list[str] | None:
    """The declared markers this artifact records, or None if it cannot be read."""
    try:
        text = bytes(content).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return [marker for marker in vocabulary if marker in text]


class ArtifactFamily:
    """Observes the provenance an artifact records; compares against the rule."""

    name = FAMILY
    precondition_steps = PRECONDITION_STEPS

    def validate_expected(self, expected: Mapping[str, Any]) -> list[str]:
        try:
            ArtifactPolicy.from_document(expected)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return [str(error)]
        return []

    def observe(self, evidence: Mapping[str, Any], cell: str) -> Mapping[str, Any] | None:
        """`evidence`: cell -> [(record key, artifact content bytes), ...]."""
        observed = evidence.get(cell)
        if not observed:
            return None
        return {"artifacts": list(observed)}

    def compare(self, cell: str, expected: Mapping[str, Any],
                observed: Mapping[str, Any] | None) -> Finding:
        step = f"{FAMILY}:{cell}"
        policy = ArtifactPolicy.from_document(expected)
        vocabulary = (policy.required_provenance, *policy.foreign_markers)
        if observed is None:
            return Finding(step, Verdict.VIOLATED,
                           ("declared, and no accepted artifact was recorded for this cell: "
                            "the claim cannot be checked",))
        reasons = []
        for record, content in observed["artifacts"]:
            recorded = markers_in(content, vocabulary)
            if recorded is None:
                reasons.append(f"{record}: its artifact cannot be read as text, so the "
                               "provenance it records cannot be checked")
                continue
            if policy.required_provenance not in recorded:
                reasons.append(f"{record}: records no {policy.required_provenance!r} provenance")
            foreign = [m for m in policy.foreign_markers if m in recorded]
            if foreign:
                reasons.append(f"{record}: records provenance foreign to this cell: {foreign}")
        if reasons:
            return Finding(step, Verdict.VIOLATED, tuple(reasons))
        return Finding(step, Verdict.VERIFIED)
