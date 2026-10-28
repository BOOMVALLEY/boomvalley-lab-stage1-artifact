"""Direct-parent lineage of an EPC package (C1, #86): LIN-001 and LIN-002.

The contract is the one manifest-1 and -2 already carry, not a new one:

    parents   absent            a root: nothing was derived, nothing is declared
              [{"seal": S}, …]  non-empty, sorted, unique; S = sha256:<64 hex>, the
                                custody seal (custody-head-2) of a direct parent

A parent's identity is its Output Seal: the child's custody entries record, per
derived record, the sealed derivation (R41) - parent seal, run, design, cell,
record and the digest of the bytes that were read - and the child's own seal
covers those records. So what a child names is fixed before any parent is
packaged, and the binding is checked against the parent's evidence, never
believed from the pointer:

    LIN-001  the declared parents are well-formed and are exactly the seals the
             child's custody derives from; every derivation record is closed and
             its lineage digest recomputes
    LIN-002  every declared parent is handed to the verifier as an EPC package that
             verifies on its own, whose Output Seal is the declared seal, which is
             not the child itself (seal, RunIdentity), and which holds every record
             the child says it read: same run, design, cell, and the artifact bytes
             whose digest the derivation recorded

Scope: direct parent only. A parent is verified with its own rules, its OWN
parents are not (LIN-002 of the parent is NO_CLAIM, "not traversed"): no
grandparent, no cycle detection, no ancestry-wide continuity (backlog).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import EvidenceError
from boomvalley_lab.core.layout import CUSTODY_DIR, ENTRIES_FILE, EVIDENCE_FILE
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.custody.derivation import DERIVATION_SCHEMA, PARENT_KEYS, TRANSFORM_KEYS

SEAL = re.compile(r"sha256:[0-9a-f]{64}")
NOT_TRAVERSED = "direct parent only: this package is read as a parent, its own parents are " \
                "not traversed"


def declared_seals(parents: Any) -> tuple[list[str], list[str]]:
    """The seals a manifest's `parents` declares, and why it is malformed if it is."""
    if parents is None:
        return [], []
    if not isinstance(parents, list) or not parents:
        return [], [f"parents is {parents!r}; a root omits it, a child lists its direct "
                    "parents"]
    seals, problems = [], []
    for index, parent in enumerate(parents):
        if not isinstance(parent, dict) or set(parent) != {"seal"} \
                or not isinstance(parent["seal"], str) or not SEAL.fullmatch(parent["seal"]):
            problems.append(f"parents[{index}] is not {{\"seal\": \"sha256:<64 hex>\"}}: "
                            f"{parent!r}")
            continue
        seals.append(parent["seal"])
    if len(set(seals)) != len(seals):
        problems.append("a parent is declared twice")
    if seals != sorted(seals):
        problems.append("parents are not sorted by seal")
    return seals, problems


def derivations(entries: Iterable[Mapping]) -> list[tuple[Mapping, list[str]]]:
    """Each custody entry that records a derivation, with its record's shape problems."""
    found = []
    for entry in entries:
        record = entry.get("derivation")
        if record is None:
            continue
        where = f"{entry.get('record')}"
        problems = []
        if not isinstance(record, dict) or set(record) != {"schema", "stage", "parent",
                                                           "transform"} \
                or record.get("schema") != DERIVATION_SCHEMA:
            problems.append(f"{where}: not a closed {DERIVATION_SCHEMA} record")
        else:
            for key, keys in (("parent", PARENT_KEYS), ("transform", TRANSFORM_KEYS)):
                value = record[key]
                if not isinstance(value, dict) or set(value) != set(keys) or not all(
                        isinstance(value[k], str) and value[k].strip() for k in keys):
                    problems.append(f"{where}: derivation {key} is not {list(keys)}")
            if not isinstance(record["stage"], str) or not record["stage"].strip():
                problems.append(f"{where}: derivation stage")
            if not problems and not SEAL.fullmatch(record["parent"]["seal"]):
                problems.append(f"{where}: derivation parent seal {record['parent']['seal']!r}")
            if not problems and entry.get("lineage") != str(sha256_document(record)):
                problems.append(f"{where}: the lineage digest is not this derivation record")
        found.append((entry, problems))
    return found


def named_parents(manifest: Mapping, entries: Sequence[Mapping]) -> list[str]:
    """LIN-001: declared parents well-formed and exactly the custody's derivation seals."""
    seals, problems = declared_seals(manifest.get("parents"))
    recorded = derivations(entries)
    for _, shape in recorded:
        problems.extend(shape)
    authority = sorted({entry["derivation"]["parent"]["seal"] for entry, shape in recorded
                        if not shape})
    if not problems and seals != authority:
        problems.append(f"the manifest declares parents {seals} and this run's custody "
                        f"derives from {authority}")
    return problems


def _entries(directory: Path) -> list[dict]:
    data = (directory / CUSTODY_DIR / ENTRIES_FILE).read_bytes()
    end = data.rfind(b"\n") + 1
    return [load_bytes(line) for line in data[:end].split(b"\n")[:-1]]


def _manifest(directory: Path) -> dict:
    manifest = load_bytes((directory / EVIDENCE_FILE).read_bytes())
    if not isinstance(manifest, dict):
        raise EvidenceError(f"{EVIDENCE_FILE} is not an object")
    return manifest


def _binding(seal: str, manifest: Mapping, directory: Path, entries: Sequence[Mapping],
             records: Sequence[Mapping]) -> list[str]:
    """Does the parent package hold what each derivation record says it read?"""
    problems = []
    run_id = (manifest.get("run") or {}).get("run_id")
    design = ((manifest.get("identities") or {}).get("design") or {}).get("digest")
    accepted = {e.get("record"): e for e in entries}
    members = {m.get("path"): m for m in manifest.get("members") or [] if isinstance(m, dict)}
    for record in records:
        parent = record["derivation"]["parent"]
        where = f"{record.get('record')} -> {seal[:19]}…"
        if parent["run"] != run_id:
            problems.append(f"{where}: the derivation names run {parent['run']!r}, the parent "
                            f"package is run {run_id!r}")
        if parent["design"] != design:
            problems.append(f"{where}: the derivation names another design than the parent's")
        entry = accepted.get(parent["record"])
        if entry is None:
            problems.append(f"{where}: the parent accepted no record {parent['record']}")
            continue
        if entry.get("cell") != parent["cell"]:
            problems.append(f"{where}: the parent record is cell {entry.get('cell')}, not "
                            f"{parent['cell']}")
        if entry.get("artifact_content") != parent["artifact_content"]:
            problems.append(f"{where}: the bytes read are not the bytes the parent's custody "
                            "accepted")
        path = f"artifacts/{entry.get('artifact')}"
        member = members.get(path)
        try:
            data = (directory / path).read_bytes()
        except OSError:
            data = None
        if member is None or data is None or str(sha256_bytes(data)) != parent[
                "artifact_content"] or member.get("digest") != parent["artifact_content"]:
            problems.append(f"{where}: the parent artifact {path} is not a member holding the "
                            "bytes that were read")
    return problems


def direct_parent_problems(*, manifest: Mapping, entries: Sequence[Mapping], own_seal: Any,
                           own_run_identity: str, parents: Sequence[Path]) -> list[str]:
    """LIN-002: every declared direct parent resolves in the handed packages and binds."""
    from boomvalley_lab.evidence.epc import read_evidence

    seals, malformed = declared_seals(manifest.get("parents"))
    if malformed:
        return ["the declared parents are malformed (LIN-001); none is resolved"]
    if not seals:
        return []
    handed: dict[str, list[tuple[Path, dict]]] = {}
    unreadable = []
    for directory in parents:
        try:
            parent_manifest = _manifest(directory)
        except (OSError, MalformedJSON, EvidenceError) as error:
            unreadable.append(f"{directory.name}: {error}")
            continue
        parent_seal = ((parent_manifest.get("identities") or {}).get("custody_seal")
                       or {}).get("digest")
        handed.setdefault(parent_seal, []).append((directory, parent_manifest))
    problems = []
    derived = [entry for entry, shape in derivations(entries) if not shape]
    for seal in seals:
        if seal == own_seal:
            problems.append(f"the package declares itself as its parent ({seal[:19]}…)")
            continue
        bound = [e for e in derived if e["derivation"]["parent"]["seal"] == seal]
        if not bound:
            problems.append(f"the parent sealed {seal[:19]}… is declared and no derivation "
                            "record binds it; a pointer alone is not a parent")
            continue
        candidates = handed.get(seal)
        if not candidates:
            problems.append(f"no parent package sealed {seal[:19]}… was handed to the verifier"
                            + (f" (unreadable: {'; '.join(unreadable)})" if unreadable else ""))
            continue
        failures = []
        for directory, parent_manifest in candidates:
            parent_run = ((parent_manifest.get("run") or {}).get("run_identity")
                          or {}).get("digest")
            if parent_run == own_run_identity:
                failures.append(f"the parent sealed {seal[:19]}… is this run (RunIdentity)")
                continue
            try:
                report = read_evidence(directory, parents=parents, traverse=False)
            except EvidenceError as error:
                failures.append(f"the parent package sealed {seal[:19]}… is unreadable: "
                                f"{error}")
                continue
            if not report.verified:
                broken = sorted({r.rule_id for r in report.rules if r.verdict.value ==
                                 "VIOLATED"})
                failures.append(f"the parent package sealed {seal[:19]}… does not verify: "
                                f"{', '.join(broken)}")
                continue
            try:
                parent_entries = _entries(directory)
            except (OSError, MalformedJSON) as error:
                failures.append(f"the parent custody is unreadable: {error}")
                continue
            binding = _binding(seal, parent_manifest, directory, parent_entries, bound)
            if not binding:
                failures = []
                break
            failures.extend(binding)
        problems.extend(failures)
    return problems


__all__ = ["NOT_TRAVERSED", "declared_seals", "derivations", "direct_parent_problems",
           "named_parents"]
