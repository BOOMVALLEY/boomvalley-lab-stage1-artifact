"""The experiment envelope `bvl-experiment-2` (I0 serialization, I1 structure).

    { "schema":        "bvl-experiment-2"                                    REQUIRED
      "declaration":   {"inline": <boomvalley-lab-declaration-1>} | {"ref": FileRef}
      "execution":     {"profile": {"inline": Profile} | {"ref": FileRef}}  (run: REQUIRED)
      "run":           {"label": Token}                                     (run: REQUIRED)
      "pre_execution": {"gndcrw": GndcrwAttachment}                         OPTIONAL
      "extensions":    {"x-<org>-<name>": JSON without null}                INFORMATIONAL
      "informational": {Token: string | [string]}                           INFORMATIONAL }

    FileRef          = {"path": RelPath, "sha256"?: "sha256:<hex>"}
    GndcrwAttachment = { "manifest_version": "gndcrw-manifest/v0.2",
                         "result_version":   "gndcrw-result/v0.2",
                         "contracts":        <GNDCRW result v0.2 `contracts`, six members>,
                         "policy":           "GNDCRW-STRICT-0.1",
                         "require_outcome":  "RUN",
                         "external_subject_scheme": "boomvalley-lab-contract-identity",
                         "inputs": { declaration, target_catalog, base_surface,
                                     candidate_surface, pair_context: FileRef } }

`-2` differs from the v1 design only in the GNDCRW attachment: the user still
references five subject files and never authors a GNDCRW manifest; BVL
snapshots them and generates the manifest (MANIFEST_TRACEABILITY §6-§7). A v1
envelope is refused here rather than half-read (UNSUPPORTED_SCHEMA).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes
from boomvalley_lab.core.errors import BoomvalleyError
from boomvalley_lab.core.strict_json import StrictInputError, load_input_bytes
from boomvalley_lab.experiment_input import profile as profiles
from boomvalley_lab.experiment_input.errors import InputRefusal
from boomvalley_lab.experiment_input.resolve import (
    DIGEST,
    KIB64,
    MIB16,
    Resolver,
    Snapshot,
    read_regular,
)

ENVELOPE_SCHEMA = "bvl-experiment-2"
MEMBERS = ("schema", "declaration", "execution", "run", "pre_execution", "extensions",
           "informational")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
EXT_KEY = re.compile(r"x-[a-z0-9]+-[a-z0-9-]+")

ROLES = ("declaration", "target_catalog", "base_surface", "candidate_surface", "pair_context")
EXTERNAL_SCHEME = "boomvalley-lab-contract-identity"
GNDCRW_CONTRACTS = {
    "declaration": "gndcrw-declaration/v0.1", "manifest": "gndcrw-manifest/v0.2",
    "pair": "gndcrw-pair/v0.1", "surface": "gndcrw-surface/v0.1",
    "target_catalog": "gndcrw-target-catalog/v0.1", "verification": "gndcrw-verification/v0.1",
}
GNDCRW_ATTACHMENT = {
    "manifest_version": "gndcrw-manifest/v0.2",
    "result_version": "gndcrw-result/v0.2",
    "contracts": GNDCRW_CONTRACTS,
    "policy": "GNDCRW-STRICT-0.1",
    "require_outcome": "RUN",
    "external_subject_scheme": EXTERNAL_SCHEME,
}


def _schema(code: str, detail: str, pointer: str = "") -> InputRefusal:
    return InputRefusal("SCHEMA_ERROR", code, detail, layer="I1", path=f"envelope#{pointer}")


# ===================================================================== I0
def read_envelope(path: Path) -> tuple[bytes, dict]:
    """The envelope's source bytes (read once) and its logical value."""
    path = Path(path)
    name = path.name
    if name.lower().endswith((".yaml", ".yml")):
        raise InputRefusal("SERIALIZATION_ERROR", "YAML_NOT_SUPPORTED",
                           f"{name}: the experiment input is strict JSON only", layer="I0",
                           path="envelope#")
    if not name.endswith(".json"):
        raise InputRefusal("SERIALIZATION_ERROR", "CARRIER_UNKNOWN",
                           f"{name}: the experiment input's file name ends in .json", layer="I0",
                           path="envelope#")
    try:
        data, _ = read_regular(path.parent if str(path.parent) else Path("."), name, MIB16,
                               "envelope")
    except InputRefusal as refusal:
        raise InputRefusal("USAGE_ERROR", "ARGUMENT_INVALID",
                           f"--experiment: {refusal.detail}", layer="CLI",
                           path="argv#") from None
    return data, parse_document(data, "envelope")


def parse_document(data: bytes, selector: str) -> dict:
    try:
        return load_input_bytes(data)
    except StrictInputError as error:
        raise InputRefusal("SERIALIZATION_ERROR", error.code, error.detail, layer="I0",
                           path=f"{selector}#") from None


# ===================================================================== I1
def _null_at(value: Any, pointer: str, skip: tuple[str, ...]) -> str | None:
    if pointer in skip:
        return None
    if value is None:
        return pointer
    if isinstance(value, dict):
        for key in sorted(value):
            found = _null_at(value[key], f"{pointer}/{key}", skip)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _null_at(item, f"{pointer}/{index}", skip)
            if found is not None:
                return found
    return None


def _source(value: Any, pointer: str, inline_type: type) -> dict:
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in ("inline",
                                                                                     "ref"):
        raise _schema("SOURCE_NOT_EXACTLY_ONE", "exactly one of inline or ref", pointer)
    if "inline" in value and not isinstance(value["inline"], inline_type):
        raise _schema("FIELD_INVALID", "inline is an object", f"{pointer}/inline")
    if "ref" in value:
        _file_ref(value["ref"], f"{pointer}/ref")
    return value


def _file_ref(value: Any, pointer: str) -> dict:
    if not isinstance(value, dict) or not set(value) <= {"path", "sha256"} or "path" not in value:
        raise _schema("FIELD_INVALID", "a FileRef is {path, sha256?}", pointer)
    if not isinstance(value["path"], str):
        raise _schema("FIELD_INVALID", "path is a string", f"{pointer}/path")
    if "sha256" in value and not (isinstance(value["sha256"], str)
                                  and DIGEST.fullmatch(value["sha256"])):
        raise _schema("FIELD_INVALID", "sha256 is sha256:<64 lowercase hex>", f"{pointer}/sha256")
    return value


def check_envelope(document: dict) -> dict:
    """I1 in the fixed order of §20.2."""
    if "schema" not in document:
        raise _schema("ENVELOPE_SCHEMA_MISSING", "schema is required", "/schema")
    if document["schema"] != ENVELOPE_SCHEMA:
        raise _schema("UNSUPPORTED_SCHEMA",
                      f"schema {document['schema']!r}; this build reads {ENVELOPE_SCHEMA!r}",
                      "/schema")
    if "lineage" in document:
        raise InputRefusal("OUT_OF_MVP", "LINEAGE_NOT_IN_V1", "lineage is not an input member",
                           layer="I1", path="envelope#/lineage")
    unknown = sorted(set(document) - set(MEMBERS))
    if unknown:
        raise _schema("ENVELOPE_UNKNOWN_FIELD", f"unknown member {unknown[0]!r}", f"/{unknown[0]}")
    null_at = _null_at(document, "", ("/declaration/inline", "/execution/profile/inline"))
    if null_at is not None:
        raise _schema("NULL_NOT_ALLOWED", f"null at {null_at}", null_at)
    if "declaration" not in document:
        raise _schema("FIELD_INVALID", "declaration is required", "/declaration")
    _source(document["declaration"], "/declaration", dict)
    if "execution" in document:
        execution = document["execution"]
        if not isinstance(execution, dict) or set(execution) != {"profile"}:
            raise _schema("FIELD_INVALID", "execution is exactly {profile}", "/execution")
        _source(execution["profile"], "/execution/profile", dict)
    if "run" in document:
        run = document["run"]
        if (not isinstance(run, dict) or set(run) != {"label"} or not isinstance(run["label"], str)
                or not TOKEN.fullmatch(run["label"]) or len(run["label"].encode()) > 255):
            raise _schema("FIELD_INVALID", "run is exactly {label: Token}", "/run")
    if "pre_execution" in document:
        _gndcrw_attachment(document["pre_execution"])
    if "extensions" in document:
        extensions = document["extensions"]
        if not isinstance(extensions, dict) or any(not EXT_KEY.fullmatch(k) for k in extensions) \
                or len(canonical_bytes(extensions)) > KIB64:
            raise _schema("EXTENSIONS_INVALID", "x-<org>-<name> keys, <= 64 KiB", "/extensions")
    if "informational" in document:
        info = document["informational"]
        if (not isinstance(info, dict) or any(not TOKEN.fullmatch(k) for k in info)
                or any(not (isinstance(v, str) or (isinstance(v, list)
                                                   and all(isinstance(i, str) for i in v)))
                       for v in info.values())
                or len(canonical_bytes(info)) > KIB64):
            raise _schema("INFORMATIONAL_INVALID", "Token -> string | [string], <= 64 KiB",
                          "/informational")
    return document


def _gndcrw_attachment(value: Any) -> None:
    pointer = "/pre_execution"
    if not isinstance(value, dict) or set(value) != {"gndcrw"}:
        raise _schema("GNDCRW_ATTACHMENT_INVALID", "pre_execution is exactly {gndcrw}", pointer)
    attachment = value["gndcrw"]
    pointer += "/gndcrw"
    expected = {*GNDCRW_ATTACHMENT, "inputs"}
    if not isinstance(attachment, dict) or set(attachment) != expected:
        raise _schema("GNDCRW_ATTACHMENT_INVALID",
                      f"the attachment is exactly {sorted(expected)}", pointer)
    for key, const in GNDCRW_ATTACHMENT.items():
        if attachment[key] != const:
            raise _schema("GNDCRW_ATTACHMENT_INVALID", f"{key} must be {const!r}",
                          f"{pointer}/{key}")
    inputs = attachment["inputs"]
    if not isinstance(inputs, dict) or set(inputs) != set(ROLES):
        raise _schema("GNDCRW_ATTACHMENT_INVALID", f"inputs is exactly {list(ROLES)}",
                      f"{pointer}/inputs")
    for role in ROLES:
        _file_ref(inputs[role], f"{pointer}/inputs/{role}")


# ===================================================================== I2..I5
@dataclass
class Materialized:
    """Everything I0..I5 established, in memory. Nothing is re-read after this."""

    source: bytes
    envelope: dict
    declaration: dict
    declaration_source: Snapshot | None       # None: inline
    profile: dict | None
    profile_source: Snapshot | None
    label: str | None
    attachment: dict | None
    subjects: dict[str, Snapshot] = field(default_factory=dict)
    lock: dict = field(default_factory=dict)

    @property
    def contract(self) -> str:
        """ContractIdentity, as lock.json writes it (`sha256:<hex>`)."""
        return self.lock["identities"]["contract"]

    @property
    def source_digest(self) -> dict:
        return {"carrier": "bvl-strict-json-1", "sha256": str(sha256_bytes(self.source)),
                "size": len(self.source)}


def materialize(path: Path) -> Materialized:
    from boomvalley_lab.identity.lock import lock as make_lock

    path = Path(path)
    source, document = read_envelope(path)
    check_envelope(document)
    resolver = Resolver(path.parent if str(path.parent) else Path("."))

    # I2, in the fixed order: declaration, profile, the five GNDCRW inputs
    declaration_source = None
    if "ref" in document["declaration"]:
        declaration_source = resolver.read(document["declaration"]["ref"], limit=MIB16,
                                           selector="declaration")
        declaration = parse_document(declaration_source.data, "declaration")
    else:
        declaration = document["declaration"]["inline"]

    profile, profile_source = None, None
    if "execution" in document:
        chosen = document["execution"]["profile"]
        if "ref" in chosen:
            profile_source = resolver.read(chosen["ref"], limit=KIB64, selector="profile")
            profile = parse_document(profile_source.data, "profile")
        else:
            profile = chosen["inline"]

    attachment = (document.get("pre_execution") or {}).get("gndcrw")
    subjects: dict[str, Snapshot] = {}
    if attachment is not None:
        for role in ROLES:
            subjects[role] = resolver.read(attachment["inputs"][role], limit=MIB16,
                                           selector=f"gndcrw:{role}")

    # I3(a): the product's own loader, unchanged; I3(b): the profile
    where = "envelope#/declaration/inline" if declaration_source is None else "declaration#"
    try:
        locked = make_lock(declaration)
    except BoomvalleyError as error:
        raise InputRefusal("DECLARATION_ERROR", "DECLARATION_STRUCTURE", str(error),
                           layer="I3", path=where) from None
    if profile is not None:
        profiles.check_profile(profile, "profile" if profile_source else
                               "envelope#/execution/profile/inline")

    return Materialized(
        source=source, envelope=document, declaration=declaration,
        declaration_source=declaration_source, profile=profile, profile_source=profile_source,
        label=(document.get("run") or {}).get("label"), attachment=attachment,
        subjects=subjects, lock=locked,
    )


def check_for_run(materialized: Materialized) -> None:
    """I4 for `run`: what a run needs beyond a valid input (§20.2 I4 (1)-(5))."""
    def combination(code: str, detail: str, pointer: str = "") -> InputRefusal:
        return InputRefusal("COMBINATION_ERROR", code, detail, layer="I4",
                            path=f"envelope#{pointer}")

    if materialized.profile is None:
        raise combination("EXECUTION_PROFILE_REQUIRED_FOR_RUN", "run needs execution.profile",
                          "/execution")
    if materialized.label is None:
        raise combination("RUN_ID_REQUIRED", "run needs run.label", "/run")
    check_run_combination(materialized)


def check_run_combination(materialized: Materialized) -> None:
    """I4 (3)-(5) of `run` that need no run label: what the profile and the declaration
    must satisfy together. `check` applies it too when there is a profile (#175, BVVH
    #174 MINOR-3), so a check never CLEARS what `run` refuses before any call."""
    def combination(code: str, detail: str, pointer: str = "") -> InputRefusal:
        return InputRefusal("COMBINATION_ERROR", code, detail, layer="I4",
                            path=f"envelope#{pointer}")

    declaration = materialized.lock["declaration"]
    if declaration.get("derivation_expectations"):
        raise InputRefusal("OUT_OF_MVP", "DERIVED_EXECUTION_NOT_IN_CLI",
                           "derivation_expectations cannot be executed by bvl run", layer="I4",
                           path="declaration#")
    if any(factor["name"] == "cell" for factor in declaration["factors"]):
        raise combination("BUILDER_RESERVED_FACTOR", "a factor named 'cell'")
    adapter = materialized.profile["adapter"]
    wanted = {"model_identity": adapter["model_identity"],
              "adapter_provenance": adapter["adapter_provenance"]}
    for index, rule in enumerate(declaration.get("execution_expectations") or ()):
        if dict(rule["expect"]) != wanted:
            raise combination("EXPECTATION_UNSATISFIABLE_BY_PROFILE",
                              f"execution_expectations[{index}] expects {rule['expect']}, the "
                              f"profile answers {wanted}")
    problem = profiles.level_block_combination(materialized.profile, declaration["factors"])
    if problem is not None:
        raise combination("PROFILE_PROMPT_UNSATISFIABLE", problem,
                          "/execution/profile")
