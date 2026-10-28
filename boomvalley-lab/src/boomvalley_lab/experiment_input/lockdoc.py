"""The Input Lock documents: EII v2, normalized input, preflight record, input.json.

ExperimentInputIdentity v2 (`bvl-experiment-input-identity-2`) — the literal
preimage, canonical-json-1:

    { "identity_schema": "bvl-experiment-input-identity-2",
      "contract":  C       -- ContractIdentity, byte-identical to lock.json identities.contract
      "execution": D       -- present iff a profile: SHA-256 of the profile's canonical bytes
      "pre_execution": {   -- present iff the GNDCRW attachment
          "contracts":        the six GNDCRW result v0.2 contracts,
          "external_subject": {"digest": C, "scheme": "boomvalley-lab-contract-identity"},
          "inputs":           {role: {"sha256", "size"}} of the five private snapshots,
          "manifest":         {"sha256", "size"} of the BVL-generated manifest bytes,
          "manifest_version": "gndcrw-manifest/v0.2",
          "policy":           "GNDCRW-STRICT-0.1",
          "require_outcome":  "RUN",
          "result":           {"sha256", "size"} of GNDCRW's exact stdout bytes,
          "result_version":   "gndcrw-result/v0.2" } }

    EII = "experiment_input:sha256:" + hex(SHA-256(canonical-json-1(preimage)))

Content, never location: no path, no file name, no run label, no host, no
executable path enters the preimage. The manifest's subject names are BVL's
FIXED names (`core.layout.GNDCRW_SUBJECT_FILES`), normative for identity-2, so
the manifest digest is a function of C and the five raw digests alone (GM-09).
The result digest makes EII specific to the GNDCRW build that produced it (its
`tool.code_digest` is in those bytes): the same input checked by another build
is a different input state.

No cycle: ContractIdentity -> manifest/external_subject -> GNDCRW result -> EII
-> preflight record -> input.json -> INPUT_LOCK_BOUND. Nothing earlier in the
chain names anything later.
"""

from __future__ import annotations

from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.layout import (
    GNDCRW_MANIFEST_FILE,
    GNDCRW_RESULT_FILE,
    GNDCRW_SUBJECT_FILES,
    PREFLIGHT_DIR,
)
from boomvalley_lab.experiment_input import profile as profiles
from boomvalley_lab.experiment_input.envelope import (
    ENVELOPE_SCHEMA,
    EXTERNAL_SCHEME,
    GNDCRW_ATTACHMENT,
    ROLES,
    Materialized,
)
from boomvalley_lab.experiment_input.gndcrw import Preflight
from boomvalley_lab.journal import events as ev

IDENTITY_SCHEMA = "bvl-experiment-input-identity-2"
INPUT_LOCK_SCHEMA = "bvl-input-lock-2"
NORMALIZED_SCHEMA = "bvl-normalized-input-2"
PREFLIGHT_SCHEMA = "bvl-preflight-record-2"
EII_PREFIX = "experiment_input:"

#: GM-07/GM-01: what the preflight does NOT establish, always stated.
PREFLIGHT_LIMITATIONS = [
    "GNDCRW_DECLARATION_NOT_DERIVED_FROM_EXPERIMENT",   # declaration/catalog/pair: author-selected
    "GNDCRW_EXTERNAL_SUBJECT_PROVIDER_ATTESTED",        # surfaces' C is the producer's attestation
    "GNDCRW_TOOL_CODE_SELF_REPORTED",                   # tool.code_digest is self-reported
]


def member(name: str) -> str:
    return f"{PREFLIGHT_DIR}/{name}"


def raw(data: bytes) -> dict:
    return {"sha256": str(sha256_bytes(data)), "size": len(data)}


# ----------------------------------------------------------------- normalized
def normalized_document(m: Materialized) -> dict:
    document: dict[str, Any] = {"schema": NORMALIZED_SCHEMA, "envelope_schema": ENVELOPE_SCHEMA}
    if m.declaration_source is None:
        document["declaration"] = {"source": "inline", "document": m.declaration}
    else:
        document["declaration"] = {"source": "ref", "ref": m.declaration_source.ref(),
                                   "document": m.declaration}
    if m.profile is not None:
        profile = ({"source": "inline", "document": m.profile} if m.profile_source is None else
                   {"source": "ref", "ref": m.profile_source.ref(), "document": m.profile})
        document["execution"] = {"profile": profile}
    if m.attachment is not None:
        document["pre_execution"] = {"gndcrw": {
            **GNDCRW_ATTACHMENT,
            "inputs": {role: m.subjects[role].ref() for role in ROLES},
        }}
    if m.label is not None:
        document["run"] = {"label": m.label}
    for key in ("extensions", "informational"):
        if key in m.envelope:
            document[key] = m.envelope[key]
    return document


# ------------------------------------------------------------------------ EII
def eii_preimage(m: Materialized, preflight: Preflight | None) -> dict:
    preimage: dict[str, Any] = {"identity_schema": IDENTITY_SCHEMA, "contract": m.contract}
    if m.profile is not None:
        preimage["execution"] = profiles.profile_digest(m.profile)
    if m.attachment is not None:
        if preflight is None:
            raise ValueError("an attached GNDCRW preflight must have run before EII exists")
        preimage["pre_execution"] = {
            "contracts": dict(GNDCRW_ATTACHMENT["contracts"]),
            "external_subject": {"digest": m.contract, "scheme": EXTERNAL_SCHEME},
            "inputs": {role: m.subjects[role].raw() for role in ROLES},
            "manifest": raw(preflight.manifest),
            "manifest_version": GNDCRW_ATTACHMENT["manifest_version"],
            "policy": GNDCRW_ATTACHMENT["policy"],
            "require_outcome": GNDCRW_ATTACHMENT["require_outcome"],
            "result": raw(preflight.result),
            "result_version": GNDCRW_ATTACHMENT["result_version"],
        }
    return preimage


def eii_of(preimage: dict) -> str:
    return EII_PREFIX + str(sha256_document(preimage))


# ------------------------------------------------------------ preflight record
def preflight_record(m: Materialized, preflight: Preflight, eii: str) -> dict:
    return {
        "schema": PREFLIGHT_SCHEMA,
        "experiment_input_identity": eii,
        "assertion": "PRODUCER_ASSERTION",
        "gndcrw": {
            "executable": preflight.executable.document(),
            "argv": preflight.argv,
            "contracts": dict(GNDCRW_ATTACHMENT["contracts"]),
            "manifest_version": GNDCRW_ATTACHMENT["manifest_version"],
            "result_version": GNDCRW_ATTACHMENT["result_version"],
            "policy": GNDCRW_ATTACHMENT["policy"],
            "external_subject": {"digest": m.contract, "scheme": EXTERNAL_SCHEME},
            "inputs": {role: {"member": member(GNDCRW_SUBJECT_FILES[role]),
                              **m.subjects[role].raw()} for role in ROLES},
            "manifest": {"member": member(GNDCRW_MANIFEST_FILE), **raw(preflight.manifest)},
            "result": {"member": member(GNDCRW_RESULT_FILE), **raw(preflight.result)},
            "exit_code": preflight.exit_code,
            "outcome": preflight.outcome,
            "tool": preflight.tool,
        },
        "limitations": list(PREFLIGHT_LIMITATIONS),
    }


def preflight_files(m: Materialized, preflight: Preflight) -> dict[str, bytes]:
    """`preflight/` members, in write order: the five snapshots, the manifest, the
    result. The manifest's relative paths resolve beside it, so the persisted
    manifest can be re-checked in place: `gndcrw check preflight/gndcrw-manifest.json`."""
    files = {GNDCRW_SUBJECT_FILES[role]: m.subjects[role].data for role in ROLES}
    files[GNDCRW_MANIFEST_FILE] = preflight.manifest
    files[GNDCRW_RESULT_FILE] = preflight.result
    return files


# ------------------------------------------------------------------ input.json
def input_lock(m: Materialized, preflight: Preflight | None, binding: dict) -> dict:
    preimage = eii_preimage(m, preflight)
    eii = eii_of(preimage)
    normalized = normalized_document(m)
    identities = m.lock["identities"]
    document: dict[str, Any] = {
        "schema": INPUT_LOCK_SCHEMA,
        "experiment_input_identity": eii,
        "eii_preimage": preimage,
        "source": m.source_digest,
        "normalized": {"sha256": str(sha256_document(normalized)), "document": normalized},
        "declaration": {"contract_identity": identities["contract"],
                        "design_identity": identities["design"],
                        "schedule_identity": identities["schedule"]},
        "execution_profile": {"digest": profiles.profile_digest(m.profile),
                              "document": m.profile, "binding": binding},
    }
    if preflight is not None:
        record = preflight_record(m, preflight, eii)
        document["pre_execution"] = {"preflight_record": record,
                                     "preflight_record_sha256": str(sha256_document(record))}
    return document


def run_projection(label: str, identities: dict, input_bytes: bytes, eii: str) -> dict:
    return {"input": {"digest": str(sha256_bytes(input_bytes)), "identity": eii},
            "lock": dict(identities), "run": label}


def anchor_event(label: str, input_bytes: bytes, eii: str, at: str) -> dict:
    return {"at": at, "event": ev.INPUT_LOCK_BOUND, "input_digest": str(sha256_bytes(input_bytes)),
            "input_identity": eii, "run": label}


def input_bytes(document: dict) -> bytes:
    return canonical_bytes(document)
