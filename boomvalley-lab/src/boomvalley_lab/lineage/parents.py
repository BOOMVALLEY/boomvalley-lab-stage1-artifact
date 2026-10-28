"""Parent reconciliation (R42): a recorded parent must RESOLVE, never be believed.

A derivation record names its parent by the parent package's custody seal.
Reconciliation takes the parent evidence actually handed to the verifier and:

    1. uses only packages that verify with custody's own verification
       (`custody.packages`) — broken evidence is not a parent;
    2. resolves the recorded seal EXACTLY. There is no "latest parent": a
       re-run has a different seal and is a different parent. Seals are
       content-addressed, so identical manifests are the same evidence;
    3. matches the run, the design identity, the qualified cell and the digest
       of the bytes that were read, and re-reads those bytes to confirm.

Nothing here repairs a bad reference, searches for a near match, or trusts a
path on disk. A parent is an accepted custody entry in a sealed package, or it
is nothing.

Whether a package may be a parent AT ALL — sealed, internally consistent,
reconciling, and not abandoned — is `custody.packages`, which also states why
a parent the gate found NOT_ELIGIBLE is still admissible while an ABORTED one
is not. This module resolves a reference; it does not re-decide that.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boomvalley_lab.custody.packages import Package
from boomvalley_lab.store.artifacts import content_identity


def holding(packages: Mapping[str, Package], record_key: str) -> list[Package]:
    """Usable packages that hold an accepted entry for `record_key`."""
    return [p for p in packages.values() if p.usable and record_key in p.entries]


def parent_records(packages: Mapping[str, Package], record_key: str
                   ) -> Sequence[tuple[Package, Mapping]]:
    """Every accepted realisation of `record_key` in the handed evidence."""
    return [(p, p.entries[record_key]) for p in holding(packages, record_key)]


def resolve(packages: Mapping[str, Package], parent: Mapping[str, str]
            ) -> tuple[Mapping | None, list[str]]:
    """The accepted parent entry a derivation record names, or why not."""
    package = packages.get(parent["seal"])
    if package is None:
        return None, [
            f"no parent evidence sealed {parent['seal'][:23]}… was handed to the verifier; "
            "a re-run is a different parent, never a newer one"
        ]
    if not package.usable:
        return None, [f"the parent package {package.run} does not verify: {package.problems[0]}"]
    if package.run != parent["run"] or package.identities.get("design") != parent["design"]:
        return None, ["the derivation names another run or design than the package it seals"]
    entry = package.entries.get(parent["record"])
    if entry is None:
        return None, [f"the parent package accepted no record {parent['record']}"]
    problems = []
    if entry["cell"] != parent["cell"]:
        problems.append(f"the parent record is cell {entry['cell']}, not {parent['cell']}")
    if entry["artifact_content"] != parent["artifact_content"]:
        problems.append("the bytes read are not the bytes the parent's custody accepted")
    try:
        content = package.store.path(entry["artifact"]).read_bytes()
    except OSError as error:
        problems.append(f"the parent artifact cannot be read ({error})")
    else:
        if str(content_identity(content).digest) != parent["artifact_content"]:
            problems.append("the parent artifact on disk is not the one that was read")
    return (None, problems) if problems else (entry, [])
