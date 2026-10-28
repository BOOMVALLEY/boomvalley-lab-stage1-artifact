"""Manifest mode: `gndcrw check <manifest.json>` (MANIFEST_CONTRACT, RESULT_CONTRACT_V0_2).

The manifest binds the five subject files by exact raw bytes. Each subject is read once
through a held, link-refusing handle; its size and SHA-256 are verified; exactly those
bytes are parsed, validated and verified by the unchanged v0.1 core. The v0.2 result is
the v0.1 result plus `binding`, `contracts.manifest` and `tool.code_digest*`, so its legacy
projection equals legacy mode byte for byte (MANIFEST_CONTRACT §11).

`external_subject` is a surface-scoped, provider-attested binding (GM-01): GNDCRW checks
only that both surfaces record it in `provenance.input_digests[scheme]`. Binding all five
subjects to an external experiment is the caller's job (BVL EII v2 / Input Lock).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gndcrw import fsread
from gndcrw.codeid import code_digest
from gndcrw.codes import Error
from gndcrw.core import vocabulary as v
from gndcrw.core.engine import verify
from gndcrw.errors import CodedError, ContractError
from gndcrw.jsonio import load_bytes, loads
from gndcrw.load import Documents, normalize

MAX_MANIFEST_BYTES = 65_536
MAX_SUBJECT_BYTES = 16_777_216
MAX_DEPTH = 8
ROLES = v.SUBJECT_ROLES
LEGACY_LABEL = {"declaration": "declaration", "target_catalog": "catalog", "base_surface": "base",
                "candidate_surface": "candidate", "pair_context": "pair"}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SCHEME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RESERVED = ({"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)}
            | {f"LPT{i}" for i in range(1, 10)})
MANIFEST_CODES = {"missing": Error.MANIFEST_NOT_FOUND, "link": Error.MANIFEST_LINK,
                  "not_regular": Error.MANIFEST_NOT_REGULAR, "case": Error.MANIFEST_NOT_FOUND,
                  "hardlink": Error.MANIFEST_HARDLINK}
REF_CODES = {"missing": Error.REF_MISSING, "link": Error.REF_LINK,
             "not_regular": Error.REF_NOT_REGULAR, "case": Error.REF_CASE_ALIAS,
             "hardlink": Error.REF_HARDLINK}


def _refuse(code: Error, message_key: str, **params: Any) -> CodedError:
    return CodedError(code, message_key, **params)


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- parse

def check_suffix(name: str) -> None:
    lower = name.lower()
    if lower.endswith(".yaml") or lower.endswith(".yml"):
        raise _refuse(Error.MANIFEST_YAML_NOT_SUPPORTED, "manifest.yaml", name=name)
    if not name.endswith(".json"):
        raise _refuse(Error.MANIFEST_NOT_JSON, "manifest.not_json", name=name)


def _relpath_ok(path: Any) -> bool:
    if not isinstance(path, str) or not path or len(path.encode("utf-8")) > 255:
        return False
    segments = path.split("/")
    if not 1 <= len(segments) <= 32:
        return False
    for segment in segments:
        if not SEGMENT_RE.match(segment) or segment.endswith("."):
            return False
        if segment.split(".")[0].upper() in RESERVED:
            return False
    return segments[-1].endswith(".json")


def _closed(value: Any, where: str, allowed: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        raise _refuse(Error.MANIFEST_FIELD_INVALID, "manifest.expected_object", where=where)
    for key in sorted(value):
        if key not in allowed:
            raise _refuse(Error.MANIFEST_UNKNOWN_FIELD, "manifest.unknown_member_at", where=where,
                          member=key)
    for key in allowed:
        if key not in value:
            raise _refuse(Error.MANIFEST_FIELD_INVALID, "manifest.missing_member", where=where,
                          member=key)
    return value


def parse_manifest(data: bytes) -> dict:
    """MANIFEST_CONTRACT §5 and §10 steps 5-15, in that order."""
    if len(data) > MAX_MANIFEST_BYTES:
        raise _refuse(Error.MANIFEST_TOO_LARGE, "manifest.too_large", size=len(data),
                      limit=MAX_MANIFEST_BYTES)
    if data.startswith(b"\xef\xbb\xbf"):
        raise _refuse(Error.MANIFEST_BOM, "manifest.bom")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _refuse(Error.MANIFEST_INVALID_UTF8, "manifest.invalid_utf8", error=exc) from None
    try:
        doc = loads(text, label="manifest")
    except ContractError as exc:
        code = (Error.MANIFEST_DUPLICATE_KEY if "duplicate object key" in exc.message
                else Error.MANIFEST_INVALID_JSON)
        raise _refuse(code, "manifest.json_error", detail=exc.message) from None
    stack = [(doc, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (dict, list)):
            if depth > MAX_DEPTH:
                raise _refuse(Error.MANIFEST_INVALID_JSON, "manifest.too_deep", limit=MAX_DEPTH)
            stack += [(item, depth + 1)
                      for item in (value.values() if isinstance(value, dict) else value)]
    if not isinstance(doc, dict):
        raise _refuse(Error.MANIFEST_NOT_OBJECT, "manifest.not_object")
    if "manifest_version" not in doc:
        raise _refuse(Error.MANIFEST_VERSION_MISSING, "manifest.version_missing")
    if doc["manifest_version"] != v.MANIFEST_VERSION:
        raise _refuse(Error.MANIFEST_VERSION_UNSUPPORTED, "manifest.version_unsupported",
                      version=doc["manifest_version"], supported=v.MANIFEST_VERSION)
    for key in sorted(doc):
        if key not in ("manifest_version", "subjects", "external_subject"):
            raise _refuse(Error.MANIFEST_UNKNOWN_FIELD, "manifest.unknown_member", member=key)
    subjects = _closed(doc.get("subjects"), "subjects", ROLES)
    for role in ROLES:
        ref = _closed(subjects[role], f"subjects.{role}", ("path", "sha256", "size"))
        if not _relpath_ok(ref["path"]):
            raise _refuse(Error.MANIFEST_PATH_INVALID, "manifest.path_invalid", role=role,
                          path=ref["path"])
        if not (isinstance(ref["sha256"], str) and DIGEST_RE.match(ref["sha256"])):
            raise _refuse(Error.MANIFEST_FIELD_INVALID, "manifest.field_invalid",
                          field=f"subjects.{role}.sha256")
        size = ref["size"]
        if type(size) is not int or not 1 <= size <= MAX_SUBJECT_BYTES:
            raise _refuse(Error.MANIFEST_FIELD_INVALID, "manifest.size_invalid", role=role,
                          limit=MAX_SUBJECT_BYTES)
    if "external_subject" in doc:
        external = _closed(doc["external_subject"], "external_subject", ("scheme", "digest"))
        if not (isinstance(external["scheme"], str) and SCHEME_RE.match(external["scheme"])):
            raise _refuse(Error.MANIFEST_FIELD_INVALID, "manifest.field_invalid",
                          field="external_subject.scheme")
        if not (isinstance(external["digest"], str) and DIGEST_RE.match(external["digest"])):
            raise _refuse(Error.MANIFEST_FIELD_INVALID, "manifest.field_invalid",
                          field="external_subject.digest")
    folded = [subjects[role]["path"].lower() for role in ROLES]
    if len(set(folded)) != len(folded):
        raise _refuse(Error.MANIFEST_DUPLICATE_PATH, "manifest.duplicate_path")
    return doc


# --------------------------------------------------------------------------- check

@dataclass
class Loaded:
    manifest: dict
    manifest_bytes: bytes
    subject_bytes: dict[str, bytes]
    identities: set[tuple[int, int]]


def load(manifest_path: Path) -> Loaded:
    """Steps 4-16: open and parse the manifest, then resolve and read every subject once."""
    base = fsread.open_base(str(manifest_path.parent) or ".")
    try:
        read = base.read([manifest_path.name], MAX_MANIFEST_BYTES, MANIFEST_CODES)
        manifest = parse_manifest(read.data)
        identities = {read.identity}
        subject_bytes: dict[str, bytes] = {}
        for role in ROLES:
            ref = manifest["subjects"][role]
            got = base.read(ref["path"].split("/"), ref["size"], REF_CODES)
            if got.identity in identities:
                raise _refuse(Error.REF_ALIAS, "ref.alias", role=role)
            identities.add(got.identity)
            if len(got.data) != ref["size"]:
                raise _refuse(Error.REF_SIZE_MISMATCH, "ref.size_mismatch", role=role,
                              declared=ref["size"], read=len(got.data))
            if sha256(got.data) != ref["sha256"]:
                raise _refuse(Error.REF_DIGEST_MISMATCH, "ref.digest_mismatch", role=role,
                              declared=ref["sha256"], read=sha256(got.data))
            subject_bytes[role] = got.data
        return Loaded(manifest, read.data, subject_bytes, identities)
    finally:
        base.close()


def evaluate(loaded: Loaded, tool_code_digest: str) -> dict:
    """Steps 18-20 and the v0.2 result (RESULT_CONTRACT_V0_2 §2-§3)."""
    try:
        docs = {LEGACY_LABEL[role]: load_bytes(loaded.subject_bytes[role], label=role)
                for role in ROLES}
        inputs = normalize(Documents(**docs))
    except ContractError as exc:
        raise _refuse(Error.SUBJECT_CONTRACT_INVALID, "subject.contract_invalid",
                      detail=exc.message) from None

    external = loaded.manifest.get("external_subject")
    if external is not None:
        surfaces = (("base_surface", inputs.base), ("candidate_surface", inputs.candidate))
        for side, surface in surfaces:
            recorded = surface.provenance["input_digests"].get(external["scheme"])
            if recorded != external["digest"]:
                raise _refuse(Error.EXTERNAL_SUBJECT_NOT_IN_SURFACE, "external.not_in_surface",
                              side=side, scheme=external["scheme"], recorded=recorded,
                              digest=external["digest"])
    try:
        result = verify(inputs)
    except ContractError as exc:
        raise _refuse(Error.SUBJECT_CONTRACT_INVALID, "subject.contract_invalid",
                      detail=exc.message) from None

    limitations = [v.TOOL_CODE_SELF_REPORTED, v.EXTERNAL_SUBJECT_PROVIDER_ATTESTED if external
                   else v.EXTERNAL_SUBJECT_ABSENT]
    result = dict(result)
    result["result_version"] = v.RESULT_VERSION_V02
    result["tool"] = {"name": v.TOOL_NAME, "version": v.TOOL_VERSION,
                      "code_digest_method": v.CODE_DIGEST_METHOD, "code_digest": tool_code_digest}
    result["contracts"] = dict(v.CONTRACTS_V02)
    result["binding"] = {
        "manifest": {"sha256": sha256(loaded.manifest_bytes), "size": len(loaded.manifest_bytes)},
        "subjects": {role: {"sha256": sha256(data), "size": len(data)}
                     for role, data in loaded.subject_bytes.items()},
        "external_subject": ({"scheme": external["scheme"], "digest": external["digest"]}
                             if external else None),
        "limitations": sorted(limitations),
    }
    return result


def compute_code_digest() -> str:
    try:
        return code_digest()
    except OSError as exc:
        raise CodedError(Error.INTERNAL_ERROR, "internal.code_digest", error=exc) from None


def capabilities() -> dict:
    return {
        "capabilities_version": v.CAPABILITIES_VERSION,
        "manifest": {"manifest_versions": [v.MANIFEST_VERSION],
                     "result_version": v.RESULT_VERSION_V02},
        "legacy": {"result_version": v.RESULT_VERSION},
        "contracts": dict(v.CONTRACTS),
        "policy_ids": [v.POLICY_ID],
        "code_digest_method": v.CODE_DIGEST_METHOD,
        "tool": {"name": v.TOOL_NAME, "version": v.TOOL_VERSION},
    }
