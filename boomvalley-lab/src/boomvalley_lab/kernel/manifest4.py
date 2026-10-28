"""manifest-4 package skeleton for K0 generalized evidence.

Historical manifests are not reinterpreted.  This module is a new versioned
reader/writer used by the vertical slice and later FULLMT co-evolution.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import CanonicalisationError, EvidenceError, IdentityError
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.kernel.custody2 import reconcile_custody_v2
from boomvalley_lab.kernel.identity import EvidenceManifestIdentity, PlanIdentity

SCHEMA = "boomvalley-lab-manifest-4"
PACKAGE_CLASSES = frozenset({"CONFORMANCE", "SCIENTIFIC"})
ROLES = frozenset(
    {
        "plan",
        "execution_binding",
        "class_manifest",
        "plugin_manifest",
        "request",
        "response",
        "custody",
        "call_binding",
        "proposal",
        "decision",
        "world_transition",
        "world_state",
        "memory",
        "episode_lineage",
        "coverage",
        "gndcrw_results",
        "gate",
        "analysis_binding",
        "analysis_output",
        "conformance_attestation",
        "dataset_units",
        # P17 (T5-002): the consent record, request intent and response of a
        # human actor call
        "human_consent",
        "human_intent",
        "human_response",
        # P17 (T5-004): the intent and the result of a tool call
        "tool_intent",
        "tool_result",
    }
)


def _relative_member(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("manifest member path must be non-empty")
    value = path.replace("\\", "/")
    parts = value.split("/")
    if value.startswith("/") or ":" in parts[0] or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"manifest member path is not package-relative: {path!r}")
    return value


@dataclass(frozen=True)
class ManifestMemberV4:
    path: str
    role: str
    digest: str
    size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_member(self.path))
        if self.role not in ROLES:
            raise ValueError(f"unknown manifest-4 role {self.role!r}")
        if not isinstance(self.digest, str) or not self.digest.startswith("sha256:"):
            raise ValueError("manifest member digest must be sha256")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("manifest member size must be a non-negative integer")

    @classmethod
    def from_file(cls, root: Path, path: str, role: str) -> ManifestMemberV4:
        relative = _relative_member(path)
        if not _held_inside(Path(root), relative):
            raise EvidenceError(f"manifest-4 member {relative} resolves outside the package")
        data = (Path(root) / relative).read_bytes()
        return cls(relative, role, str(sha256_bytes(data)), len(data))

    def document(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role,
            "digest": self.digest,
            "size": self.size,
        }


def _held_inside(root: Path, relative: str) -> bool:
    """Whether a member is a file of the package directory itself (SV-13 P-02): a link or
    a junction on the way leads to bytes the package does not carry."""

    try:
        (root / relative).resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class ManifestV4:
    package_class: str
    plan: PlanIdentity
    members: Sequence[ManifestMemberV4]
    limitations: Sequence[str] = ()

    def __post_init__(self) -> None:
        if self.package_class not in PACKAGE_CLASSES:
            raise ValueError(f"unknown package class {self.package_class!r}")
        paths = [member.path for member in self.members]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest-4 member paths are unique")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("manifest-4 limitations are unique")

    def document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "package_class": self.package_class,
            "plan": self.plan.document(),
            "members": [
                member.document() for member in sorted(self.members, key=lambda item: item.path)
            ],
            "limitations": sorted(self.limitations),
        }

    def identity(self) -> EvidenceManifestIdentity:
        return EvidenceManifestIdentity.of_payload(self.document())

    def verify(self, root: Path) -> list[str]:
        root = Path(root)
        problems: list[str] = []
        for member in self.members:
            path = root / member.path
            if not path.is_file():
                problems.append(f"missing member {member.path}")
                continue
            if not _held_inside(root, member.path):
                problems.append(f"{member.path}: resolves outside the package")
                continue
            data = path.read_bytes()
            if len(data) != member.size:
                problems.append(f"{member.path}: size mismatch")
            if str(sha256_bytes(data)) != member.digest:
                problems.append(f"{member.path}: digest mismatch")
        return problems


def write_manifest4(root: Path, manifest: ManifestV4) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / "MANIFEST-4.json"
    partial = root / ".MANIFEST-4.json.partial"
    data = canonical_bytes(manifest.document())

    if final.exists():
        raise EvidenceError("manifest-4 is immutable and already exists")
    # A partial without its manifest is the leftover of a crashed seal: nothing
    # references it (single writer, R8), so it is discarded (T4-014).
    partial.unlink(missing_ok=True)

    with open(partial, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.rename(partial, final)
    if final.read_bytes() != data:
        raise EvidenceError("manifest-4 does not read back as written")
    return final


def read_manifest4(path: Path) -> ManifestV4:
    data = Path(path).read_bytes()
    try:
        document = load_bytes(data)
    except MalformedJSON as error:
        raise EvidenceError(f"manifest-4 is unreadable: {error}") from error
    # SV-09 (SV-04 m-07): `null` has no canonical form; it is a manifest that
    # does not verify (exit 4), not a declaration error
    if not isinstance(document, Mapping):
        raise EvidenceError("manifest-4 has the wrong closed shape")
    try:
        canonical = canonical_bytes(document)
    except CanonicalisationError as error:
        # SV-10: a value with no canonical form (-0.0, a null in a list) is a
        # manifest that does not verify (exit 4), as `null` is (SV-09)
        raise EvidenceError(f"manifest-4 is not canonical JSON: {error}") from error
    if canonical != data:
        raise EvidenceError("manifest-4 is not canonical JSON")
    if set(document) != {
        "schema",
        "package_class",
        "plan",
        "members",
        "limitations",
    }:
        raise EvidenceError("manifest-4 has the wrong closed shape")
    if document.get("schema") != SCHEMA:
        raise EvidenceError(f"manifest-4 schema is exactly {SCHEMA!r}")

    plan_doc = document["plan"]
    if not isinstance(plan_doc, Mapping) or set(plan_doc) != {"kind", "digest"}:
        raise EvidenceError("manifest-4 plan identity is malformed")
    if plan_doc["kind"] != PlanIdentity.KIND:
        raise EvidenceError("manifest-4 plan identity has the wrong kind")
    from boomvalley_lab.core.digest import Digest

    try:
        plan = PlanIdentity(Digest.parse(plan_doc["digest"]))
    except IdentityError as error:
        raise EvidenceError(f"manifest-4 plan identity is malformed: {error}") from error
    members_doc = document["members"]
    if not isinstance(members_doc, list):
        raise EvidenceError("manifest-4 members is a list")
    try:
        members = tuple(
            ManifestMemberV4(
                item["path"],
                item["role"],
                item["digest"],
                item["size"],
            )
            for item in members_doc
            if isinstance(item, Mapping) and set(item) == {"path", "role", "digest", "size"}
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError(f"manifest-4 member is malformed: {error}") from error
    if len(members) != len(members_doc):
        raise EvidenceError("manifest-4 contains a malformed member")
    limitations = document["limitations"]
    if not isinstance(limitations, list) or not all(isinstance(x, str) for x in limitations):
        raise EvidenceError("manifest-4 limitations is a string list")
    try:
        return ManifestV4(document["package_class"], plan, members, tuple(limitations))
    except (TypeError, ValueError) as error:
        raise EvidenceError(f"manifest-4 is invalid: {error}") from error


def collect_manifest4_members(root: Path) -> tuple[ManifestMemberV4, ...]:
    """Collect the versioned K0 evidence members already persisted in *root*.

    This collector is intentionally structural: the role comes from a
    product-owned directory/member class, never from study-provided metadata.

    A persisted response is packaged only after its request/journal/artifact
    chain recomputes against custody-v2; the custody ledger is a member with
    the explicit ``custody`` role.

    Scientific evidence is packaged only under the run's verified gate-2
    authorization (T0-012); a refused run packages its refusal only.
    """
    root = Path(root)
    # Local import: authorization -> document_store -> manifest4 (ROLES).
    from boomvalley_lab.kernel.authorization import reconcile_authorization_v2

    authorization_state = reconcile_authorization_v2(root)
    if not authorization_state.complete:
        raise EvidenceError(
            "manifest-4 refuses evidence without a verified gate-2 authorization: "
            + "; ".join(authorization_state.problems)
        )
    custody_state = reconcile_custody_v2(root)
    if not custody_state.complete:
        reasons = [
            f"call {call} is persisted but not custody-accepted" for call in custody_state.pending
        ]
        raise EvidenceError(
            "manifest-4 refuses unreconciled call custody: "
            + "; ".join([*reasons, *custody_state.problems])
        )
    # Local import: world_executor -> document_store -> manifest4 (ROLES).
    from boomvalley_lab.kernel.world_executor import reconcile_world_v2

    world_state = reconcile_world_v2(root)
    if not world_state.complete:
        reasons = [
            f"world intent {intent} is {state}, not applied"
            for intent, state in world_state.pending
        ]
        raise EvidenceError(
            "manifest-4 refuses unreconciled World transitions: "
            + "; ".join([*reasons, *world_state.problems])
        )
    members: list[ManifestMemberV4] = []

    request_root = root / "requests-v2"
    if request_root.is_dir():
        for path in sorted(request_root.glob("request-*.json")):
            members.append(
                ManifestMemberV4.from_file(root, path.relative_to(root).as_posix(), "request")
            )

    artifact_root = root / "artifacts"
    if artifact_root.is_dir():
        for path in sorted(artifact_root.glob("call-*.bin")):
            members.append(
                ManifestMemberV4.from_file(root, path.relative_to(root).as_posix(), "response")
            )

    evidence_root = root / "evidence-v2"
    if evidence_root.is_dir():
        for role_dir in sorted(path for path in evidence_root.iterdir() if path.is_dir()):
            role = role_dir.name
            if role not in ROLES:
                raise EvidenceError(f"unregistered evidence-v2 role directory {role!r}")
            for path in sorted(role_dir.glob("*.json")):
                members.append(
                    ManifestMemberV4.from_file(
                        root,
                        path.relative_to(root).as_posix(),
                        role,
                    )
                )

    custody = root / "custody-v2" / "entries.jsonl"
    if custody.is_file():
        members.append(
            ManifestMemberV4.from_file(root, "custody-v2/entries.jsonl", "custody")
        )

    journal = root / "journal-2.jsonl"
    if journal.is_file():
        members.append(ManifestMemberV4.from_file(root, "journal-2.jsonl", "episode_lineage"))

    paths = [member.path for member in members]
    if len(paths) != len(set(paths)):
        raise EvidenceError("manifest-4 collector produced duplicate member paths")
    return tuple(sorted(members, key=lambda item: item.path))
