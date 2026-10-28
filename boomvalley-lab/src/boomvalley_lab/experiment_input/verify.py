"""Post-create comparison (PC-1..8) and Input Lock verification (ILV-1..15).

ILV is read-only and runs, in this order, before any write of any kind: after
run creation (before the first execution), at the start of every `bvl resume`,
and for `status`. The first failure wins; the class is INPUT_DRIFT unless
stated. The v2 differences from the v1 table (Input Contract §10.5) are in
ILV-12, which re-verifies the whole preflight chain from the persisted bytes:

    SHA-256(preflight/subjects/*)  = record.inputs = EII inputs = result binding.subjects
    SHA-256(preflight/gndcrw-manifest.json) = record.manifest = EII manifest
                                   = result binding.manifest, and the manifest
                                     re-derives from C and the five raw digests
    SHA-256(preflight/gndcrw-result.json)   = record.result = EII result
    result binding.external_subject = {scheme, C}; outcome RUN

Legacy (NOT_INPUT_LOCKED) runs never reach ILV; `legacy_guard` is the order a
legacy write path refuses in (§10.7 A/B/C).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes, canonical_json
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import BoomvalleyError, EvidenceError
from boomvalley_lab.core.layout import (
    GNDCRW_MANIFEST_FILE,
    GNDCRW_RESULT_FILE,
    GNDCRW_SUBJECT_FILES,
    INPUT_FILE,
    JOURNAL_FILE,
    LOCK_FILE,
    PREFLIGHT_DIR,
    RUN_FILE,
)
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.experiment_input import gndcrw
from boomvalley_lab.experiment_input import lockdoc as docs
from boomvalley_lab.experiment_input import profile as profiles
from boomvalley_lab.experiment_input.envelope import (
    ENVELOPE_SCHEMA,
    EXTERNAL_SCHEME,
    GNDCRW_ATTACHMENT,
    ROLES,
)
from boomvalley_lab.experiment_input.errors import InputRefusal, drift
from boomvalley_lab.experiment_input.resolve import Snapshot
from boomvalley_lab.journal import events as ev
from boomvalley_lab.journal.anchor import (
    AnchorState,
    artifacts_present,
    classify,
)
from boomvalley_lab.journal.log import Journal

INPUT_MEMBERS = {"schema", "experiment_input_identity", "eii_preimage", "source", "normalized",
                 "declaration", "execution_profile"}
NORMALIZED_MEMBERS = {"schema", "envelope_schema", "declaration", "execution", "pre_execution",
                      "run", "extensions", "informational"}


@dataclass(frozen=True)
class LockedInput:
    """What an INPUT_LOCK_OK run is bound to, read off verified evidence."""

    run: str
    identity: str
    digest: str
    document: dict

    @property
    def profile(self) -> dict:
        return self.document["execution_profile"]["document"]


# ========================================================== classification
def _journal(directory: Path) -> list[dict]:
    try:
        journal = Journal(directory).read()
    except EvidenceError as error:
        raise drift("JOURNAL_INVALID", str(error), path="journal#") from None
    if not journal or journal[0]["event"] != ev.RUN_OPENED:
        raise drift("JOURNAL_INVALID", "journal[0] is not RUN_OPENED", path="journal#")
    return journal


def classification(directory: Path) -> dict:
    """Read-only: the journal-derived classification and, for an INPUT_LOCKED run,
    the ILV verdict. Never raises for a refusal; reports it."""
    directory = Path(directory)
    try:
        anchor = classify(Journal(directory).read())
    except EvidenceError as error:
        return {"classification": "JOURNAL_INVALID", "detail": str(error)}
    if anchor.state is AnchorState.ABSENT:
        present = artifacts_present(directory)
        if present:
            return {"classification": "INPUT_DRIFT", "code": "UNANCHORED_INPUT_LOCK",
                    "artifacts": present}
        return {"classification": anchor.classification}
    if anchor.state is AnchorState.INVALID:
        return {"classification": "INPUT_DRIFT", "code": "INPUT_LOCK_ANCHOR_INVALID",
                "detail": anchor.problem}
    try:
        locked = verify_input_lock(directory)
    except InputRefusal as refusal:
        return {"classification": "INPUT_DRIFT", "code": refusal.code, "detail": refusal.detail}
    return {"classification": anchor.classification, "verification": "INPUT_LOCK_OK",
            "experiment_input_identity": locked.identity, "input_digest": locked.digest}


# ===================================================================== ILV
def _read_json(path: Path, code: str, selector: str) -> Any:
    try:
        return load_bytes(path.read_bytes())
    except (OSError, MalformedJSON) as error:
        raise drift(code, f"{path.name}: {error}", path=f"{selector}#") from None


def verify_input_lock(directory: Path, *, installation: bool = True) -> LockedInput:
    """ILV-1..15. Read-only. INPUT_LOCK_OK or InputRefusal.

    `installation=False` is the evidence-only reading a package verifier uses
    (IR-07): ILV-13 compares the execution binding with THIS installation's
    builder/adapter code, which is a question about whether the run may be
    resumed here, not about what the evidence says. Every other step is a
    recomputation from the persisted bytes and runs unchanged."""
    from boomvalley_lab.declare.experiment import load
    from boomvalley_lab.identity.lock import lock as relock
    from boomvalley_lab.identity.lock import verify_lock

    directory = Path(directory)
    # ILV-1 journal and anchor
    journal = _journal(directory)
    anchor = classify(journal)
    if anchor.state is AnchorState.INVALID:
        raise drift("INPUT_LOCK_ANCHOR_INVALID", anchor.problem or "invalid", path="journal#")
    # ILV-2 an ABSENT anchor is a legacy run, or a spoof
    if anchor.state is AnchorState.ABSENT:
        present = artifacts_present(directory)
        if present:
            raise drift("UNANCHORED_INPUT_LOCK", f"artifacts {present} without an anchor")
        raise InputRefusal("COMBINATION_ERROR", "RUN_NOT_INPUT_LOCKED",
                           f"{directory} is a legacy (NOT_INPUT_LOCKED) run; use "
                           "`boomvalley-lab resume`", layer="IL", path="journal#")
    bound = anchor.event
    opened = journal[0]
    # ILV-3 run.json names this run
    run_document = _read_json(directory / RUN_FILE, "RUN_JSON_INVALID", "run.json")
    if not isinstance(run_document, dict) or run_document.get("run") != opened["run"]:
        raise drift("RUN_ID_MISMATCH", "run.json.run is not RUN_OPENED.run", path="run.json#/run")
    # ILV-4 the projection equals the anchor
    if "input" not in run_document:
        raise drift("INPUT_BINDING_MISSING", "run.json has no input binding", path="run.json#")
    if run_document["input"] != {"digest": bound["input_digest"],
                                 "identity": bound["input_identity"]}:
        raise drift("RUN_JSON_BINDING_MISMATCH", "run.json.input differs from INPUT_LOCK_BOUND",
                    path="run.json#/input")
    # ILV-5 input.json is the anchored bytes
    try:
        data = (directory / INPUT_FILE).read_bytes()
    except OSError:
        raise drift("INPUT_LOCK_MISSING", "input.json is missing", path="input.json#") from None
    if str(sha256_bytes(data)) != bound["input_digest"]:
        raise drift("INPUT_LOCK_DIGEST_MISMATCH", "SHA-256(input.json) != input_digest",
                    path="input.json#")
    # ILV-6 closed, canonical, loadable
    document = _input_document(data)
    normalized = document["normalized"]["document"]
    # ILV-7 EII recomputes
    eii = docs.eii_of(document["eii_preimage"])
    if not (eii == document["experiment_input_identity"] == bound["input_identity"]):
        raise drift("EII_MISMATCH", f"recomputed {eii}", path="input.json#/eii_preimage")
    # ILV-8 the run label is the run
    if (normalized.get("run") or {}).get("label") != bound["run"]:
        raise drift("RUN_ID_MISMATCH", "normalized run.label != INPUT_LOCK_BOUND.run",
                    path="input.json#/normalized/document/run")
    # ILV-9 lock binding, and the re-lock
    lock_document = _read_json(directory / LOCK_FILE, "LOCK_BINDING_MISMATCH", "lock.json")
    if any(f.verdict.value == "VIOLATED" for f in verify_lock(lock_document)):
        raise drift("LOCK_BINDING_MISMATCH", "lock.json does not verify", path="lock.json#")
    identities = lock_document["identities"]
    declared = document["declaration"]
    opened_lock = {"contract": opened["lock_contract"], "design": opened["lock_design"],
                   "schedule": opened["lock_schedule"]}
    stated = {"contract": declared["contract_identity"], "design": declared["design_identity"],
              "schedule": declared["schedule_identity"]}
    if not (stated == identities == run_document.get("lock") == opened_lock):
        raise drift("LOCK_BINDING_MISMATCH", "input.json / lock.json / run.json / RUN_OPENED "
                    "name different lock identities", path="input.json#/declaration")
    if document["eii_preimage"]["contract"] != identities["contract"]:
        raise drift("LOCK_BINDING_MISMATCH", "EII contract != ContractIdentity",
                    path="input.json#/eii_preimage/contract")
    try:
        relocked = relock(normalized["declaration"]["document"])["identities"]
    except BoomvalleyError as error:
        raise drift("LOCK_BINDING_MISMATCH", f"re-lock: {error}") from None
    if relocked != identities:
        raise drift("LOCK_BINDING_MISMATCH", "re-lock of the normalized declaration differs")
    # ILV-10 the profile
    profile_entry = document["execution_profile"]
    digest = profiles.profile_digest(profile_entry["document"])
    if not (digest == profile_entry["digest"] == document["eii_preimage"].get("execution")):
        raise drift("PROFILE_MISMATCH", "profile digest", path="input.json#/execution_profile")
    if normalized["execution"]["profile"]["document"] != profile_entry["document"]:
        raise drift("PROFILE_MISMATCH", "normalized profile differs from execution_profile")
    # ILV-11 normalized
    if str(sha256_document(normalized)) != document["normalized"]["sha256"]:
        raise drift("NORMALIZED_MISMATCH", "normalized.sha256", path="input.json#/normalized")
    preimage_pre = document["eii_preimage"].get("pre_execution")
    normalized_pre = (normalized.get("pre_execution") or {}).get("gndcrw")
    if (preimage_pre is None) != (normalized_pre is None) \
            or (preimage_pre is None) != ("pre_execution" not in document):
        raise drift("NORMALIZED_MISMATCH", "pre_execution present in some members and not others")
    if preimage_pre is not None:
        # MINOR-16: the normalized attachment is the EII's, not only its inputs
        if not isinstance(normalized_pre, dict) or set(normalized_pre) != {*GNDCRW_ATTACHMENT,
                                                                             "inputs"}:
            raise drift("NORMALIZED_MISMATCH", "normalized GNDCRW attachment is not closed")
        attached = {**{k: preimage_pre.get(k) for k in GNDCRW_ATTACHMENT
                       if k != "external_subject_scheme"},
                    "external_subject_scheme": (preimage_pre.get("external_subject") or {}
                                                ).get("scheme")}
        for key, value in attached.items():
            if normalized_pre[key] != value:
                raise drift("NORMALIZED_MISMATCH", f"normalized GNDCRW {key} != EII {key}",
                            path=f"input.json#/normalized/document/pre_execution/gndcrw/{key}")
        stripped = {role: {"sha256": ref["sha256"], "size": ref["size"]}
                    for role, ref in normalized_pre["inputs"].items()}
        if stripped != preimage_pre["inputs"]:
            raise drift("NORMALIZED_MISMATCH", "normalized GNDCRW inputs != EII inputs")
        # ILV-12 the whole preflight chain, from persisted bytes
        _preflight(directory, document, eii, identities["contract"])
    # ILV-13 the installation's code (resume/run only; see `installation`)
    if installation and profiles.binding(profile_entry["document"]) != profile_entry["binding"]:
        raise drift("EXECUTION_BINDING_CHANGED", "this installation's builder/adapter code or "
                    "product differs from execution_profile.binding")
    # ILV-14 journal intents <-> the locked profile
    _intents(journal, profile_entry["document"], load(lock_document["declaration"]))
    # ILV-15 adapter kind <-> provenance namespace <-> actual execution (#176)
    _provenance_parity(journal, profile_entry["document"])
    return LockedInput(bound["run"], eii, bound["input_digest"], document)


def _input_document(data: bytes) -> dict:
    from boomvalley_lab.declare.experiment import load

    def invalid(detail: str) -> InputRefusal:
        return drift("INPUT_LOCK_INVALID", detail, path="input.json#")

    try:
        document = load_bytes(data)
    except MalformedJSON as error:
        raise invalid(str(error)) from None
    if not isinstance(document, dict) or document.get("schema") != docs.INPUT_LOCK_SCHEMA:
        raise invalid(f"not a {docs.INPUT_LOCK_SCHEMA} document")
    expected = INPUT_MEMBERS | ({"pre_execution"} if "pre_execution" in document else set())
    if set(document) != expected:
        raise invalid(f"members {sorted(document)}")
    if canonical_bytes(document) != data:
        raise invalid("input.json is not in canonical-json-1")
    normalized = document["normalized"]
    if not isinstance(normalized, dict) or set(normalized) != {"sha256", "document"}:
        raise invalid("normalized is {sha256, document}")
    body = normalized["document"]
    if (not isinstance(body, dict) or body.get("schema") != docs.NORMALIZED_SCHEMA
            or body.get("envelope_schema") != ENVELOPE_SCHEMA
            or not set(body) <= NORMALIZED_MEMBERS or "execution" not in body):
        raise invalid("normalized.document is not a closed bvl-normalized-input-2")
    try:
        load(body["declaration"]["document"])
        profiles.check_profile(body["execution"]["profile"]["document"], "input.json",
                               parity=False)    # the namespace is ILV-15, under its own code
    except (BoomvalleyError, KeyError, TypeError) as error:
        raise invalid(f"normalized document: {error}") from None
    preimage = document["eii_preimage"]
    if not isinstance(preimage, dict) or preimage.get("identity_schema") != docs.IDENTITY_SCHEMA:
        raise invalid("eii_preimage.identity_schema")
    return document


def _preflight(directory: Path, document: dict, eii: str, contract: str) -> None:
    def mismatch(detail: str) -> InputRefusal:
        return drift("PREFLIGHT_MISMATCH", detail, path="input.json#/pre_execution")

    pre = document["pre_execution"]
    record = pre["preflight_record"]
    preimage = document["eii_preimage"]["pre_execution"]
    if str(sha256_document(record)) != pre["preflight_record_sha256"]:
        raise mismatch("preflight_record_sha256")
    if record.get("schema") != docs.PREFLIGHT_SCHEMA or record.get(
            "experiment_input_identity") != eii:
        raise mismatch("the record names another EII or schema")
    if record.get("limitations") != docs.PREFLIGHT_LIMITATIONS:
        raise mismatch(f"limitations {record.get('limitations')}")
    tool = record["gndcrw"]
    for key in ("contracts", "manifest_version", "result_version", "policy"):
        if tool.get(key) != preimage.get(key):
            raise mismatch(f"record {key} != EII {key}")
    external = {"digest": contract, "scheme": EXTERNAL_SCHEME}
    if not (tool.get("external_subject") == preimage["external_subject"] == external):
        raise mismatch("external_subject is not {ContractIdentity, scheme}")
    if tool.get("exit_code") != 0 or tool.get("outcome") != "RUN" \
            or preimage.get("require_outcome") != GNDCRW_ATTACHMENT["require_outcome"]:
        raise mismatch("the recorded preflight is not exit 0 / RUN")
    base = directory / PREFLIGHT_DIR
    snapshots: dict[str, Snapshot] = {}
    for role in ROLES:
        name = GNDCRW_SUBJECT_FILES[role]
        try:
            data = (base / name).read_bytes()
        except OSError:
            raise mismatch(f"{PREFLIGHT_DIR}/{name} is missing") from None
        snapshots[role] = Snapshot(name, data)
        held = snapshots[role].raw()
        if not (held == preimage["inputs"][role]
                == {k: tool["inputs"][role][k] for k in ("sha256", "size")}):
            raise mismatch(f"{role}: persisted snapshot != record != EII")
    try:
        manifest = (base / GNDCRW_MANIFEST_FILE).read_bytes()
        result = (base / GNDCRW_RESULT_FILE).read_bytes()
    except OSError as error:
        raise mismatch(f"preflight evidence missing: {error}") from None
    if not (docs.raw(manifest) == preimage["manifest"]
            == {k: tool["manifest"][k] for k in ("sha256", "size")}):
        raise mismatch("gndcrw-manifest.json != record.manifest != EII manifest")
    if manifest != gndcrw.manifest_bytes(snapshots, contract):
        raise mismatch("the manifest does not re-derive from C and the five snapshots")
    if not (docs.raw(result) == preimage["result"]
            == {k: tool["result"][k] for k in ("sha256", "size")}):
        raise mismatch("gndcrw-result.json != record.result != EII result")
    try:
        parsed = gndcrw.check_result(result, manifest=manifest,
                                     subjects={r: s.raw() for r, s in snapshots.items()},
                                     contract=contract,
                                     version=tool["executable"]["version"], exit_code=0,
                                     declaration=snapshots["declaration"].data)
    except InputRefusal as refusal:
        raise mismatch(f"the persisted result: {refusal.code}: {refusal.detail}") from None
    if parsed["outcome"] != "RUN" or parsed["tool"] != tool.get("tool"):
        raise mismatch("the persisted result's outcome/tool differ from the record")


def rebuilt_request(profile: dict, record) -> bytes:
    """The exact request bytes the locked builder makes for `record` (ILV-14, REQ-001)."""
    from boomvalley_lab.runtime.adapter import request_document

    return canonical_bytes(request_document(record, profiles.builder_for(profile)(record)))


def _intents(journal: list[dict], profile: dict, experiment) -> None:
    from boomvalley_lab.runtime.adapter import request_document

    adapter = profile["adapter"]
    intended = {"adapter_provenance": adapter["adapter_provenance"],
                "model_identity": adapter["model_identity"]}
    builder = profiles.builder_for(profile)
    records = {record.key: record for record in experiment.records}
    for position, event in enumerate(journal):
        if event["event"] != ev.INTENT_RECORDED:
            continue
        if dict(event["intended"]) != intended:
            raise drift("INTENT_PROFILE_MISMATCH",
                        f"journal line {position}: intended {event['intended']} != profile")
        record = records.get(event["record"])
        if record is None:
            raise drift("REQUEST_BINDING_MISMATCH", f"journal line {position}: unknown record")
        expected = str(sha256_document(request_document(record, builder(record))))
        if event["request"] != expected:
            raise drift("REQUEST_BINDING_MISMATCH",
                        f"journal line {position}: request {event['request']} != {expected}")


def _provenance_parity(journal: list[dict], profile: dict) -> None:
    """ILV-15 (#176, BVVH #174 MAJOR-1): the locked adapter kind fixes the provenance
    namespace of the identity it intends and of every identity that answered, and
    what answered is what the locked profile intends. The producer's self-report
    (CALL_RETURNED.actual_execution) is read, never trusted."""
    from boomvalley_lab.runtime.adapters.namespace import actual_problems, intended_problems

    adapter = profile["adapter"]
    problems = intended_problems(adapter)
    if problems:
        code, detail = problems[0]
        raise drift(code, f"locked profile: {detail}",
                    path="input.json#/execution_profile/document/adapter")
    for position, event in enumerate(journal):
        if event["event"] != ev.CALL_RETURNED:
            continue
        problems = actual_problems(adapter, event.get("actual_execution") or {})
        if problems:
            code, detail = problems[0]
            raise drift(code, f"journal line {position} ({event.get('record')}): {detail}",
                        path="journal#")


# ====================================================================== PC
def post_create(directory: Path, *, lock_bytes: bytes, input_bytes: bytes, run_bytes: bytes,
                opened: dict, anchor: dict, preflight: Mapping[str, bytes],
                binding: dict, profile: dict) -> None:
    """PC-1..8: the disk holds exactly the in-memory values, read once."""
    directory = Path(directory)

    def substituted(detail: str) -> InputRefusal:
        return drift("INPUT_LOCK_SUBSTITUTED", detail, layer="I7")

    def read(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except OSError:
            return None

    if read(directory / LOCK_FILE) != lock_bytes:                            # PC-1
        raise InputRefusal("IDENTITY_ERROR", "LOCK_SUBSTITUTED", "lock.json differs",
                           layer="I7", path="lock.json#")
    if read(directory / INPUT_FILE) != input_bytes:                          # PC-2
        raise substituted("input.json differs from the in-memory Input Lock")
    if read(directory / RUN_FILE) != run_bytes:                              # PC-3
        raise substituted("run.json differs")
    lines = (read(directory / JOURNAL_FILE) or b"").split(b"\n")
    expected = [canonical_json(opened).encode("utf-8"), canonical_json(anchor).encode("utf-8")]
    if lines[:1] != expected[:1]:                                            # PC-4
        raise substituted("journal line 0 is not the in-memory RUN_OPENED")
    if lines[1:2] != expected[1:2]:                                          # PC-5
        raise substituted("journal line 1 is not the in-memory INPUT_LOCK_BOUND")
    for name, data in preflight.items():                                     # PC-6
        if read(directory / PREFLIGHT_DIR / name) != data:
            raise substituted(f"{PREFLIGHT_DIR}/{name} differs")
    if lines != [*expected, b""]:                                            # PC-7
        raise substituted("the journal holds more than RUN_OPENED and INPUT_LOCK_BOUND")
    if profiles.binding(profile) != binding:                                 # PC-8
        raise drift("EXECUTION_BINDING_CHANGED", "the installation changed during creation",
                    layer="I7")
