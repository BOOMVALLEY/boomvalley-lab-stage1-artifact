"""FULLMT rule registry — the single definition of every rule id this reader evaluates.

rule_id -> (layer, title). A rule id names a check whose failure REJECTS a package; it is
never an error code (fullmt_codes.ErrorCode) and is never localized. Order = evaluation
order of the manifest-3 handler (manifest-1 skips the -3-only rules).
"""
from __future__ import annotations

RULES: dict[str, tuple[str, str]] = {
    "MEM-001": ("L2",
        "manifest well-formed and closed; member paths canonical, unique, "
        "contained, listed in path order"),
    "LIM-001": ("L2",
        "limitations are {code, free_text}: code in the frozen 13-code "
        "vocabulary, free_text <= 1024 code points and never interpreted; "
        "unique, sorted"),
    "MEM-002": ("L1", "every member exists with the listed raw digest and length"),
    "MEM-003": ("L1", "no file under the root other than members and EVIDENCE.json"),
    "MEM-004": ("L2", "role cardinalities (§6.3), Input Lock roles when INPUT_LOCKED"),
    "STR-001": ("L2", "every JSON/JSONL member passes the strict read rules (§16.4)"),
    "PRD-001": ("L2",
        "producer_provenance is boomvalley-epc-producer-2 (manifest and "
        "document)"),
    "STR-002": ("L2",
        "normative JSON members are canonical at rest; journal and custody "
        "entry lines are canonical-json-1 + LF"),
    "ID-001": ("L3", "evidence_root recomputes from the member table"),
    "ID-002": ("L3", "package_identity recomputes (self-seal, §6.4)"),
    "ID-003": ("L3", "contract/design/schedule = SHA-256(raw) = lock = run.json = manifest"),
    "ID-004": ("L3", "RunIdentity recomputes; run_id scheme declared"),
    "RUN-001": ("L3", "every run-scoped field names the manifest run_id"),
    "JRN-001": ("L2", "journal events are of known kinds"),
    "JRN-002": ("L3", "RUN_OPENED first, once, naming the lock identities"),
    "JRN-003": ("L3",
        "journal replays as a legal state machine: per-attempt grammar; "
        "RUN_ABORTED / RUN_SEALED terminal, only session teardown after"),
    "JRN-004": ("L3",
        "journal extent recorded; torn tail present iff JOURNAL_TORN_TAIL "
        "declared; ends with RUN_SEALED (+SESSION_CLOSED)"),
    "SCH-001": ("L3", "custody record set = schedule set, position = schedule index"),
    "SCH-002": ("L3", "INTENT_RECORDED order follows schedule order"),
    "CUS-001": ("L2",
        "custody entries: complete LF-terminated records (no trailing bytes), "
        "schema, one per record, identities = manifest"),
    "CUS-002": ("L1", "SHA-256(artifact bytes) = entry artifact_content = response"),
    "CUS-003": ("L3", "custody digest, head seal, counts, sessions_digest recompute"),
    "SEAL-001": ("L3",
        "Output Seal: manifest custody_seal = recomputed head seal = "
        "RUN_SEALED.seal; head SEALED"),
    "MEM-005": ("L2", "cross cardinalities: artifacts = entries, requests = intents"),
    "DS-001": ("L3", "DatasetIdentity recomputes; rows = schedule-ordered entries"),
    "REQ-002": ("L2",
        "request / request_envelope members (by declared role): strict, "
        "supported schema, closed structure, availability vocabulary"),
    "REQ-001": ("L3",
        "each request member (raw digest) or envelope (request.digest) = its "
        "intent's and custody entry's request; one per intent record"),
    "REQ-003": ("L3",
        "producer-declared request availability (REQUEST_* limitations) agrees "
        "with the request member set and envelope states"),
    "REQ-004": ("L3",
        "manifest-3 request_content: AVAILABLE (members bound by digest and "
        "size) / WITHHELD (digest and size only, no member) / UNAVAILABLE "
        "(never INPUT_LOCKED), one entry per intent, the matching limitation "
        "stated"),
    "LIM-002": ("L3",
        "the limitations the evidence establishes are stated: the standing "
        "codes, DATASET_NOT_ADMITTED iff no dataset member, exactly the "
        "preflight record's GNDCRW_* codes, MODEL_VERSION_NOT_PINNED when not "
        "INPUT_LOCKED"),
    "INP-001": ("L3", "Input Lock chain: input bytes, EII, run.json, anchor, manifest"),
    "INP-002": ("L3",
        "GNDCRW preflight members (by declared role) bind to the EII, preflight"
        " record, GNDCRW result and manifest; outcome RUN"),
    "INP-003": ("L3",
        "input.json content binds to its EII: closed structure, profile digest,"
        " normalized digest, run label, lock identities, GNDCRW inputs; journal"
        " intents = locked profile"),
    "INP-004": ("L3",
        "GNDCRW result/manifest version, policy, contracts and tool identity "
        "are within this reader's support table and identical across result, "
        "record, EII, input; tool.version = executable.version"),
    "INP-005": ("L3",
        "GNDCRW result means one thing: closed finding members and types, "
        "reason_code -> (status, policy_class) and finding_kind -> "
        "reasons/identity pinned, summary and STRICT outcome recomputed from "
        "the findings, exactly one bound finding per declared rule, findings "
        "never empty"),
    "INP-006": ("L3", (
        "adapter provenance parity: the locked adapter kind fixes the "
        "adapter_provenance namespace and model_identity format of the intended "
        "profile and of every CALL_RETURNED actual_execution, and each actual "
        "execution is the intended identity (#176/#179, BVL-REC-087)")),
    "CLM-001": ("L5", "claims document valid; claim ids recompute"),
    "ELG-001": ("L2",
        "eligibility report (by declared role): strict, supported schema, "
        "closed structure, finding verdict/code/rule vocabulary"),
    "ELG-002": ("L3", "eligibility report run binding = recomputed RunIdentity = manifest"),
    "ELG-003": ("L5",
        "producer eligibility verdict integrity: ELIGIBLE, no VIOLATED finding,"
        " verdict consistent with findings, gate steps present once"),
    "ELG-004": ("L5",
        "producer verdicts for portable steps agree with FULLMT's own "
        "recomputed rules"),
    "ELG-005": ("L5",
        "producer eligibility verdicts = recomputed portable rules (full "
        "re-derivation)"),
}

# MANIFEST-4 (boomvalley-lab-manifest-4) rules - manifest4_reader. A separate registry: an
# EPC package never evaluates an M4 rule and a MANIFEST-4 package never an EPC rule.
# Order = evaluation order under the CONFORMANCE meaning; a MEMBER_INVENTORY package
# evaluates M4-MAN / M4-MEM / M4-CLS only (the rest NOT_EVALUATED).
M4_RULES: dict[str, tuple[str, str]] = {
    "M4-MAN": ("L2",
        "manifest closed and canonical-json-1 at rest; schema; plan is a "
        "PlanIdentity; members closed, portable unique paths in path order, known "
        "roles; limitations a sorted list of unique codes"),
    "M4-MEM": ("L1",
        "every member is a regular file inside the root (no link) with the listed "
        "SHA-256 and the listed size"),
    "M4-UNL": ("L1", "no file under the root other than members and MANIFEST-4.json"),
    "M4-ROL": ("L2",
        "each member's role is the one its layout place prescribes; evidence and "
        "request members are canonical and named by their content digest"),
    "M4-CLS": ("L2",
        "package class CONFORMANCE with exactly the CONFORMANCE limitation set; "
        "SCIENTIFIC has no manifest-4 semantics and is refused"),
    "M4-JRN": ("L3",
        "journal-2: canonical JSONL, no torn tail, sequence 0..n-1, one run, "
        "RUN_OPENED at 0 only, no refused / unknown / rejected / failed / aborted "
        "event"),
    "M4-AUT": ("L3",
        "gate-2 CLEARED for the plan; execution binding, build / plugin-set and "
        "AuthorizationIdentity recompute; RUN_OPENED names exactly them"),
    "M4-PLN": ("L3",
        "one plan member recomputes the manifest PlanIdentity and holds one closed "
        "Protocol IR with its actor / information / proposal / decision / analysis / "
        "seed / World / memory / round contracts in closed form"),
    "M4-EPI": ("L3",
        "every episode recomputes from plan x authorization x episode_key; steps are "
        "rounds x topological order (StepIdentity, RoundIdentity, DAG and schedule "
        "identities recomputed); termination verdicts re-derived; completed once"),
    "M4-CMT": ("L3",
        "each step carries exactly the commit event its node kind prescribes, after "
        "every dependency's commit"),
    "M4-ART": ("L3",
        "proposal / decision / memory identities recompute from their content and "
        "are exactly the ones journal-2 commits, at their step and round"),
    "M4-CUS": ("L3",
        "custody entries canonical; each accepted call recomputes its "
        "CustodyEntryIdentity and names request and response members with the "
        "recorded bytes; accepted calls are the actor-call steps"),
    "M4-WLD": ("L3",
        "World transitions: transition / intent / state identities recompute; states "
        "versioned and chained; admissibility, progression, RNG policy and seed "
        "binding as the plan's World contract froze them; each confirmed once"),
    "M4-LIN": ("L3",
        "every IR dependency edge is the evidence lineage (call -> proposal -> "
        "decision -> World intent -> memory); builtin decision rules recompute; "
        "memory lifecycle, cross-episode carry and regime interaction as declared"),
    "M4-L1C": ("L3",
        "L1 call bindings: Call / Actor / Role / ExecutionProfile identities, "
        "request-2 model / renderer / options / seed, default-deny access trace, "
        "upstream and memory observations recompute from the plan"),
    "M4-RQR": ("L3", "the package holds every evidence role the IR's node kinds require"),
    "M4-ATT": ("L5",
        "exactly one conformance attestation, equal to this reader's own "
        "re-derivation from the evidence (incl. ERF coverage and the GNDCRW "
        "comparison set when the gate bound them)"),
    "M4-L1D": ("L5",
        "L1 dataset units equal this reader's own reconstruction byte for byte; a "
        "pre-L1 package holds none"),
    "M4-ANA": ("L5",
        "the bound analysis output equals this reader's own recomputation over the "
        "admitted units (exact rational arithmetic); none when no analysis is bound"),
    "M4-EXT": ("L3",
        "external actors (P17): every actor call is answered by the caller its plan "
        "declares - a human exchange (consent, request intent, delivery, response) or a "
        "tool call (intent, arguments, result) re-derived from its named evidence under "
        "the plan's contract; no human / tool record or member is unaccounted for"),
}
