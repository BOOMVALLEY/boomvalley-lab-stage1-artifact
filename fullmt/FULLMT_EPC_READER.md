# FULLMT package reader — EPC (`EVIDENCE.json`) and MANIFEST-4 (`MANIFEST-4.json`)

```
FULLMT 0.12.0
├─ EPC reader       EVIDENCE.json     (historical BOOMVALLEY EPC, manifest-1 / -3)
└─ MANIFEST-4       MANIFEST-4.json   (current bvl-study-1 conformance package)
```

```
Status        IMPLEMENTED  (issue #344, reader 0.12.0)
Command       fullmt <package-dir>            (one executable; scripts/fullmt/epc_reader.py)
EPC reader    scripts/fullmt/epc_reader.py        unchanged semantics since 0.11.3
MANIFEST-4    scripts/fullmt/manifest4_reader.py  FULLMT-owned, stdlib only, no BVL import
Vectors       fixtures/fullmt_manifest4/          frozen producer output (BVL v1.0.0)
Tests         scripts/fullmt/test_epc_reader.py · scripts/fullmt/test_manifest4_reader.py
```

This document was the EPC reader's document and keeps its path. Everything from
"Historical EPC reader" down describes the EPC reader and is unchanged; the MANIFEST-4
part is this section.

## MANIFEST-4 (#344, reader 0.12.0)

```
GNDCRW
   ↓
bvl-study-1  (bvl run)
   ↓
bvl package  →  MANIFEST-4.json
   ↓
fullmt <RUN>
   ↓
independent VERIFIED / REJECTED
```

The current BOOMVALLEY Lab execution (`bvl-study-1`) packages a run as `MANIFEST-4.json`
(`boomvalley-lab-manifest-4`). FULLMT 0.11.3 refused such a directory as
`NOT_AN_EPC_PACKAGE`. FULLMT 0.12.0 verifies it with its own code.

### Dispatch — the package root decides, nothing is guessed

| package root holds | reader | result |
|---|---|---|
| `EVIDENCE.json` only | EPC reader, exactly as in 0.11.3 | `fullmt-epc-verification-result/1` |
| `MANIFEST-4.json` only, schema `boomvalley-lab-manifest-4` | MANIFEST-4 verifier | `fullmt-manifest4-verification-result/1` |
| both | none | `ERROR AMBIGUOUS_PACKAGE_FORMAT` |
| neither | none | `ERROR NOT_AN_EPC_PACKAGE` (`PACKAGE.json` is never a fallback) |
| `MANIFEST-4.json` with any other schema | none | `ERROR UNSUPPORTED_MANIFEST_SCHEMA` |
| a manifest-4 document named `EVIDENCE.json` | none | `ERROR UNSUPPORTED_MANIFEST_SCHEMA` |
| `MANIFEST-4.json` that is a directory or a link | none | `ERROR MANIFEST_NOT_READABLE` |
| `MANIFEST-4.json` that is not strict JSON | none | `ERROR JSON_PARSE_ERROR` |

An `EVIDENCE.json` package is never reinterpreted as MANIFEST-4 and no EPC rule changed.
The test suite holds every historical vector to the byte-identical 0.11.3 result
(verdict, failed rules, every rule status and problem text, observations, limitations).
EPC `boomvalley-epc-manifest-2` stays outside FULLMT's EPC support, as it was in 0.11.3
(`ERROR UNSUPPORTED_MANIFEST_SCHEMA`).

### What a MANIFEST-4 package means (`meaning`)

- **CONFORMANCE** — the manifest lists a conformance attestation or states the CONFORMANCE
  limitation set. All 20 M4 rules are evaluated, ending in FULLMT's own re-derivation of
  the attestation, which must equal the stored one exactly. `VERIFIED` says the run
  conformed to its frozen plan and protocol. **A CONFORMANCE package is not scientific
  evidence** and FULLMT never reports it as such: every result carries the producer
  limitation `CONFORMANCE_PACKAGE_NOT_SCIENTIFIC_EVIDENCE` and the consumer limitation
  `CONFORMANCE_NOT_SCIENTIFIC_EVIDENCE`.
- **MEMBER_INVENTORY** — a pre-attestation manifest-4 (a bare member list, written before
  conformance semantics existed). Only `M4-MAN`, `M4-MEM`, `M4-CLS` are evaluated; the
  other 17 rules are `NOT_EVALUATED`, the result says `conformance: "NOT_CLAIMED"` and
  nothing is attested. It is never upgraded to a conformance claim.
- **SCIENTIFIC** — the frozen producer defines no scientific manifest-4 semantics
  (BVL-REC-102 / BVL-REC-104), so there is no versioned scientific contract to verify
  against. `package_class: "SCIENTIFIC"` is `REJECTED` by `M4-CLS` (result field
  `scientific: "NOT_SUPPORTED"`), with or without an attestation.

### Rules

| rule | layer | checks |
|---|---|---|
| `M4-MAN` | L2 | manifest closed and canonical-json-1 at rest; plan is a PlanIdentity; members closed, portable unique paths in path order, known roles; limitations sorted and unique |
| `M4-MEM` | L1 | every member is a regular file inside the root (no link, junction or reparse point) with the listed SHA-256 and the listed size (reported separately) |
| `M4-UNL` | L1 | no file under the root other than members and `MANIFEST-4.json` |
| `M4-ROL` | L2 | each member's role is the one its layout place prescribes; evidence and request members are canonical and named by their content digest |
| `M4-CLS` | L2 | class CONFORMANCE with exactly the CONFORMANCE limitation set |
| `M4-JRN` | L3 | journal-2: canonical JSONL, no torn tail, sequence 0..n-1, one run, RUN_OPENED at 0 only, no refused / unknown / rejected / failed / aborted event |
| `M4-AUT` | L3 | gate-2 CLEARED for the plan; execution binding, build / plugin-set and AuthorizationIdentity recompute; RUN_OPENED names exactly them |
| `M4-PLN` | L3 | the plan member recomputes the manifest PlanIdentity; closed Protocol IR; actor / information / proposal / decision / analysis / seed / World / memory / round contracts in closed form |
| `M4-EPI` | L3 | Episode / Step / Round / DAG / schedule identities recompute; steps are rounds × topological order; termination verdicts re-derived; completed once |
| `M4-CMT` | L3 | one commit event per step by node kind, after every dependency's commit |
| `M4-ART` | L3 | proposal / decision / memory identities recompute from content and are the ones journal-2 commits |
| `M4-CUS` | L3 | custody entries canonical; CustodyEntryIdentity recomputes; request and response members hold the recorded bytes |
| `M4-WLD` | L3 | World transition / intent / state identities; state chain; admissibility; progression; RNG policy and seed binding; each transition confirmed once |
| `M4-LIN` | L3 | every IR dependency edge is the evidence lineage; builtin decision rules recompute; memory lifecycle, cross-episode carry, regime interaction |
| `M4-L1C` | L3 | L1 call bindings: Call / Actor / Role / ExecutionProfile identities, request-2 parameters and seed, default-deny access trace, upstream and memory observations |
| `M4-RQR` | L3 | every evidence role the IR's node kinds require is present |
| `M4-ATT` | L5 | exactly one conformance attestation, equal to FULLMT's own re-derivation (incl. ERF coverage and the GNDCRW comparison set when the gate bound them) |
| `M4-L1D` | L5 | L1 dataset units equal FULLMT's own reconstruction byte for byte |
| `M4-ANA` | L5 | the bound analysis output equals FULLMT's own recomputation (exact rational arithmetic) |
| `M4-EXT` | L3 | external actors (P17): every actor call is answered by the caller its plan declares; each human exchange (consent, request intent, delivery, response) and tool call (intent, arguments, result) is re-derived from the evidence journal-2 names, under the plan's contract; no human / tool record or member is unaccounted for. Evaluated when every rule above passed |

Rule ids live in `fullmt_rules.M4_RULES`, a registry separate from the EPC `RULES`. The
full rule text is the module docstring of `manifest4_reader.py`. When a rule fails, the
rules that depend on it are `NOT_EVALUATED` (`note: "not reached: an earlier rule failed"`).

### Human and tool actors (P17: plan-9, plan-10, `M4-EXT`)

The reader covers the whole MANIFEST-4 vocabulary of BOOMVALLEY Lab `v1.0.0`: all 26
member roles of its `manifest4.py` (the five P17 roles `human_consent`, `human_intent`,
`human_response`, `tool_intent`, `tool_result` included) and every semantic plan its
`package4.py` accepts, `spike-1` and `plan-2` … `plan-10`. plan-9 (`humans`, BVL T5-001)
is a seeded plan (7 / 8) that freezes the human actor contracts; plan-10 (`tools`,
BVL T5-003) is a seeded plan (7 / 8 / 9) that freezes the tool actor contracts. An
unknown later plan schema is refused by `M4-PLN`, never guessed forward.

What FULLMT re-derives, from the package bytes alone:

- **the contracts** (`M4-PLN`) — a `humans` / `tools` member is a closed, canonically
  ordered set of current contracts (`bvl-human-actor-contract-1`;
  `bvl-tool-actor-contract-2`, or `-3` with its `argument_selection`). Every contract is
  held to its actor's frozen binding: the reserved model (`bvl:human-participant:1` /
  `bvl:tool-actor:1`), the contract's channel / tool as the provider, no generation
  options. No other actor states a reserved model, nobody is contracted as both, and a
  tool selects its arguments only from sources its actor is granted. The ERF coverage
  walk (`M4-ATT`) maps the contracts and takes a human / tool actor's provider as a
  `human_channel` / `tool` plugin.
- **a human exchange** (`M4-EXT`) — `CALL_INTENT_RECORDED` names one `human_intent`
  member by content address; its HumanRequestIntentIdentity recomputes and is this
  step × actor × request under the plan's contract, channel and privacy. The intent names
  one `human_consent` member: HumanConsentIdentity recomputes, the record is `GRANTED`,
  the participant's (a pseudonym), under this contract and exactly its terms. The request
  is delivered once and answered once, transport → delivery → answer → return, and the
  journaled delivery is the persisted request's messages under the contract.
  `HUMAN_RESPONSE_RECEIVED` names one `human_response` member: HumanResponseIdentity
  recomputes, it answers that intent, participant and consent, states the digest and size
  of the accepted response bytes (text within `max_chars`), and arrived through the
  contract's channel at no less than its minimum grade, an operator-entered answer naming
  its operator.
- **a tool call** (`M4-EXT`) — the call names its tool intent and contract; the step
  journals that one intent, and its history classifies (attempts in order; a mutating
  tool is never started again while an earlier attempt is unproven; an unknown outcome of
  an `IDEMPOTENT_BY_KEY` tool is reconciled; one result). The `tool_intent` member
  recomputes its identity (read and mutation intents never stand for each other), is
  this step × actor × request under the contract's tool, operation and resource, and
  carries the contract's typed arguments: a constant, or a field of an `actor_output`
  source re-derived from what the round committed. The `tool_result` member recomputes
  the journaled identity, answers that intent in the contract's result type, and the
  accepted response bytes are exactly the ones it derives.
- **nothing unaccounted for** (`M4-EXT`) — a member is an exchange's only when a
  journal-2 record of that exchange names it. An intent, response or result named by two
  exchanges is refused; a `HUMAN_*` / `TOOL_*` record or a human / tool member that no
  declared exchange accounts for is refused; a model actor's call carries none.

Every problem of these checks starts with FULLMT's own reason code:

| code | rule | refused because |
|---|---|---|
| `T5-PLN-001` | `M4-PLN` | a `humans` / `tools` member is not a closed set of current contracts (unknown schema, missing or undeclared term, value outside its domain) |
| `T5-PLN-002` | `M4-PLN` | contracts not unique, or not in canonical order |
| `T5-PLN-003` | `M4-PLN` | a contract disagrees with its actor's frozen binding (model, channel / tool, options), names no plan actor, or one actor is contracted twice |
| `T5-PLN-004` | `M4-PLN` | an actor states a reserved model without a contract |
| `T5-PLN-005` | `M4-PLN` | a tool argument is selected from a source its actor is not granted |
| `T5-EXT-001` | `M4-EXT` | a call is not answered by its declared caller |
| `T5-EXT-002` | `M4-EXT` | a human / tool record or member no declared exchange accounts for |
| `T5-EXT-003` | `M4-EXT` | one intent / response / result named by two exchanges |
| `T5-HUM-001` | `M4-EXT` | request intent missing, malformed, identity mismatch, or not this call's under the contract |
| `T5-HUM-002` | `M4-EXT` | consent record missing, malformed, identity mismatch, or not GRANTED to the contract's terms |
| `T5-HUM-003` | `M4-EXT` | not delivered once and answered once in order; delivery is not the persisted request |
| `T5-HUM-004` | `M4-EXT` | response missing, malformed, identity mismatch, or another exchange's |
| `T5-HUM-005` | `M4-EXT` | answer provenance (channel, grade, operator) outside the contract |
| `T5-HUM-006` | `M4-EXT` | the accepted response bytes are not the content the answer states |
| `T5-TOOL-001` | `M4-EXT` | the call does not name / journal its one tool intent; its history is not a classified call |
| `T5-TOOL-002` | `M4-EXT` | tool intent missing, malformed, identity mismatch, or not this call's under the contract |
| `T5-TOOL-003` | `M4-EXT` | arguments are not the contract's typed, declared selection |
| `T5-TOOL-004` | `M4-EXT` | tool result missing, malformed, identity mismatch, or another intent's |
| `T5-TOOL-005` | `M4-EXT` | the accepted response bytes are not the ones the recorded result derives |

A VERIFIED result reports FULLMT's own count under `observed.external_actors`
(`model_calls`, `human_exchanges`, `tool_calls`, `tool_attempts`,
`tool_reconciliations`, `arguments_re_derived`, `arguments_from_frozen_sources`,
`participants`, `provenance_grades`, `mutations`). A package no person and no tool took
part in passes `M4-EXT` with zero human exchanges and tool calls, and its other 19 rule
results are unchanged.

### Independence

- `manifest4_reader.py` imports `hashlib`, `json`, `math`, `collections`, `fractions`
  and FULLMT's own `fullmt_codes` / `fullmt_rules`. It imports no `boomvalley_lab`, no BVL
  helper, verifier or package builder, starts no process and opens no file itself
  (tests A6–A9 enforce this on the source).
- Bytes reach it only through `epc_reader.Package`: contained, link-free reads. Every file
  is read exactly once and every rule works on those bytes, so a file swapped after its
  read cannot change what was verified (test G8).
- The rule set is the one BOOMVALLEY Lab froze for its manifest-4 producer at `v1.0.0`
  (`db21f4275c512e0b220d8a7ee7889b7bf71296de`) and demonstrated in its T0-015 and T5-008
  (P17) reference readers. It was promoted from those references into FULLMT, which now
  owns, tests and releases it. The references are a specification and a test oracle; they
  are not on FULLMT's import path and are not executed.
- The one process FULLMT ever starts is `git` on its own checkout, in `epc_reader._git`,
  to compute `verifier.code_digest`; it never touches a package or the producer and no
  verdict depends on it. Test M runs the P17 verdicts under `python -I -S` with an audit
  hook that refuses every process start, socket and producer import: the verdicts and
  every rule status are the same, with `code_digest` reported unavailable.
- `verifier.code_digest` covers `manifest4_reader.py` (it is in `READER_SOURCES`). Both
  readers report the one FULLMT version and code identity; the MANIFEST-4 result also
  names the producer contract it was written against (`verifier.producer_contract`).

### What `VERIFIED CONFORMANCE` does not establish

Stated in every result (`limitations.consumer`), never implied:

| code | meaning |
|---|---|
| `CONFORMANCE_NOT_SCIENTIFIC_EVIDENCE` | conformance to the frozen plan and protocol only; no scientific claim |
| `NOT_SIGNED` | no signature: who produced the bytes is not established |
| `WORLD_CODE_NOT_REPLAYED` | World transitions are checked as evidenced; the World's code is not executed |
| `ACTOR_CALLS_NOT_REEXECUTED` | responses are bound by digest to custody; no model call is repeated |
| `BUILD_AND_PLUGIN_SET_SELF_REPORTED` | build / plugin-set identities recompute from a document that is the producer's own statement |
| `GATE_INPUTS_SUPPLIED_NOT_DERIVED` | gate-2 inputs are bound and re-walked as supplied; GNDCRW is not re-run |
| `OBSERVATION_DIGESTS_ATTESTED_NOT_RECOMPUTED` | (L1 packages) observation digests in the dataset units are the producer's |
| `HUMAN_AND_TOOL_ACTS_NOT_REENACTED` | (packages a person or a tool answered in) exchanges are re-derived from evidence; nobody is asked and no tool is called; who the pseudonym is, what the operator was told and what a tool changed on its site are not established; an argument from a frozen resource is held to one value, not re-read |

The producer's own limitation codes are reported verbatim in
`limitations.producer_declared`. One of them is still named
`FULLMT_MANIFEST4_SPIKE_READER_REQUIRED`: it is a frozen producer code (part of the
CONFORMANCE limitation set that `M4-CLS` requires exactly), not a statement about this
reader.

### Result document `fullmt-manifest4-verification-result/1`

```
result_schema, verifier{name: fullmt-manifest4-reader, version, code_digest, ...,
                        handlers, producer_contract}
input{package_path, manifest_file, manifest_digest}
dispatch{manifest_file, manifest_schema, handler, meaning}
outcome  VERIFIED | REJECTED | ERROR          failed_rules[]
meaning  CONFORMANCE | MEMBER_INVENTORY       package_class, plan
manifest_identity{kind: evidence_manifest, digest}   package_identity (= that digest)
conformance: NOT_CLAIMED      (MEMBER_INVENTORY only)
scientific:  NOT_SUPPORTED    (package_class SCIENTIFIC only)
rules[]{rule_id, layer, title, status, problems?, note?}     summary{PASS, FAIL, NOT_EVALUATED}
observed{members, evidence_level, dataset_units?, analysis?, external_actors?, attested?}
limitations{producer_declared, producer_declared_codes, consumer[]}
error{code, detail}, error_code     (ERROR only; then no meaning / failed_rules)
```

`manifest_identity` is the identity `bvl package` prints for the same package.
`--quiet` prints one line: `VERIFIED CONFORMANCE sha256:… failed=[]` (the EPC line keeps
its 0.11.3 form, without a meaning token). Exit codes are 0 / 1 / 2, and `--out` keeps
the verdict-vs-delivery separation of 0.11.1: an undeliverable result file leaves the
verdict untouched, adds `delivery{status: FAILED, error_code: OUTPUT_WRITE_ERROR}` to
stdout and exits 2.

### Tests and vectors

`fixtures/fullmt_manifest4/vectors.zip` holds 33 frozen package directories produced once
by BOOMVALLEY Lab `v1.0.0` (`make_vectors.py`, the only place BVL code ever runs for
FULLMT, and only to produce bytes). `VECTORS.json` records the provenance, a digest per
case, the producer's own verdict and the T0-015 reference reader's result.
`EPC_BASELINE_0_11_3.json` records what reader 0.11.3 said about the `EVIDENCE.json`
cases (`freeze_epc_baseline.py`).

| cases | what | expected |
|---|---|---|
| N01, N02 | genuine CONFORMANCE (T0-014 P01, P02) | VERIFIED, also after relocation |
| N03 | response artifact byte altered | REJECTED `M4-MEM` |
| N04 | unlisted decision member | REJECTED `M4-UNL` |
| N05 | attestation forged, manifest resealed | REJECTED `M4-ATT` |
| N06 | EPISODE_COMPLETED dropped, resealed | REJECTED `M4-EPI` |
| N07 | resealed as SCIENTIFIC | REJECTED `M4-CLS` |
| N08 | CONFORMANCE limitations removed | REJECTED `M4-CLS` |
| N09 | proposal value forged, re-addressed, resealed | REJECTED `M4-ART` |
| N10 | decision relabelled as proposal | REJECTED `M4-ROL` |
| I01 / I02 | pre-attestation inventory / altered member | VERIFIED MEMBER_INVENTORY / REJECTED `M4-MEM` |
| E01–E04 | both / neither / unknown schema / disguised | ERROR |
| H01, H03–H05 | historical EPC manifest-1 / -3 | VERIFIED, result identical to 0.11.3 |
| H02 | historical EPC manifest-2 | ERROR `UNSUPPORTED_MANIFEST_SCHEMA`, as in 0.11.3 |
| H06 | historical EPC, artifact byte altered | REJECTED `MEM-002`, `CUS-002`, as in 0.11.3 |
| S01–S11 | real `bvl run` → `bvl package` of the producer's example `bvl-study-1` studies (ledger World, World contract, seeded RNG, NO_ACTION, bounded revision, memory lifecycle, round contract, timed termination, cross-episode regime, majority, route choice) | VERIFIED CONFORMANCE, 20 / 20 rules PASS, L1 |

`fixtures/fullmt_manifest4/vectors_t5.zip` holds 15 more, the P17 cases, produced once by
the same producer commit from a byte-exact tree (`make_t5_vectors.py`): the producer's
example studies run through its real CLI — a person's run stops `WAITING` (exit 9) once
per round and is answered by a separate operator process, a tool's run acts on a site
outside the run directory — sealed by `bvl package` and accepted by
`bvl verify --l1 --l2 --l3 --replay-world --calls`. `VECTORS_T5.json` records the
provenance (commit, source digests, harness), a digest per case, the producer's verdicts
and the result of its stdlib P17 reference reader.

| cases | what | expected |
|---|---|---|
| P01 | B11: a person answers the store manager's call, delayed (plan-9; 4 human exchanges, 4 model calls) | VERIFIED CONFORMANCE, 20 / 20 rules PASS, L1 |
| P02 | B12: tools read a table and write a ledger on a site (plan-10; 8 tool calls, 4 model calls) | VERIFIED CONFORMANCE, 20 / 20 |
| P03 | B12 killed after a mutation was applied, resumed by reconciliation (plan-10) | VERIFIED CONFORMANCE, 20 / 20; 1 reconciliation |
| P04 | B12 with its manager answered by a person: plan-10 over plan-9, no model in the run | VERIFIED CONFORMANCE, 20 / 20 |
| P05 | Worker → Manager study whose manager is a person (plan-9, ledger World) | VERIFIED CONFORMANCE, 20 / 20 |
| Q01–Q07 | P04 re-sealed by the producer's T5-008 forger so that every digest holds: answer re-attributed, provenance downgraded, consent withdrawn, read result restated, order argument restated, frozen-source argument restated, declined mutation restated as applied | REJECTED `M4-EXT` (`T5-HUM-004`, `-005`, `-002`, `T5-TOOL-005`, `-003`, `-003`, `-005`) |
| Q08–Q10 | P04 damaged in transit: answer bit flipped, tool result lost, consent record lost | REJECTED `M4-MEM` |

H02 is the one row where FULLMT differs from the BVL T0-015 matrix: BVL's historical
reader (`epc_consume`) reads manifest-2, FULLMT's EPC reader never did. The requirement
is that historical EPC behaviour is preserved, so it stays an ERROR.

`test_manifest4_reader.py` adds FULLMT-owned adversarial cases built with its own forgers
(a careful forger re-addresses documents and reseals the manifest, so only cross-document
bindings can expose the edit): manifest path traversal and non-portable paths; a member
directory replaced by a junction, a junction as the package root, symlinked members and
roots (skipped where the OS does not permit symlinks); duplicate and reordered members;
malformed and non-canonical JSON; unknown roles and hostile member shapes; digest and size
mismatch separately; one flipped byte in each member in turn; single-read and
swap-after-read race cases; nested extra files; future schemas; corrupt, duplicated,
removed and downgraded attestations; SCIENTIFIC relabelling; cross-document forgeries
caught by `M4-WLD`, `M4-AUT`, `M4-ART`, `M4-PLN`, `M4-CUS`, `M4-JRN`; and a sweep removing
each top-level member of each evidence document of a real study (316 coherent forgeries,
none VERIFIED).

For P17 it adds its own deep forgers (sections L): `forge_exchange` rewrites human / tool
exchange documents and the journal, optionally carries every moved identity to whatever
names it, re-addresses every changed member and reseals; `replan` rewrites the frozen
plan and carries the new PlanIdentity through the plan evidence, gate-2, the execution
binding, the AuthorizationIdentity, `RUN_OPENED` and the manifest, so only the plan's own
content can expose it. 99 cases, each REJECTED by the one expected rule and T5 reason:
missing consent / intent / response / tool intent / tool result; consent, response, tool
intent and tool result restated under a stale identity (content / identity mismatch) and
with the identity carried (semantic mismatch); consent of another participant, contract
or terms; answers and tool results exchanged between calls or reused; unreferenced
`human_consent` / `human_intent` / `human_response` / `tool_intent` / `tool_result`
members; a real name as participant; provenance below the contract; a forged delivery; a
model actor claiming a person; plan-9 and plan-10 contracts against actor bindings; 22
malformed or unknown contract shapes; `humans` / `tools` under the wrong plan schema and
an unknown plan-11; and the tool call history classifier rule by rule.

```text
python scripts/fullmt/test_manifest4_reader.py     MANIFEST-4 (incl. P17), dispatch, EPC regression, CLI
python scripts/fullmt/test_epc_reader.py           the existing EPC suite (unchanged)
```

---

# Historical EPC reader (`EVIDENCE.json`)

The sections below are the EPC reader's record as accepted through reader 0.11.3.

## First GNDCRW → BVL → FULLMT E2E (EPC)

```
Status        IMPLEMENTED · E2E smoke run  (2026-09-27, issue #50; #52 remediation)
Reader        scripts/fullmt/epc_reader.py 0.2.0   (stdlib only, no BVL import)
Input         BVL impl/bvl-output-epc @ b34e38c · artifacts/bvl_epc_ex001/package
Result        artifacts/fullmt/epc_ex001/verification.json   → VERIFIED
Backlog       docs/IMPLEMENTATION_RECOMMENDATIONS.md
```

## Release disclosure — what `VERIFIED` does and does not mean (#131; #117 MINOR-1)

FULLMT `VERIFIED` means that the package passed every check this reader performs itself:
the evidence bytes, identities, seal, Input Lock / GNDCRW bindings and the C1 contract
rules listed below, checked against the package bytes. It does **not** mean that FULLMT
re-ran or independently re-derived the BVL execution gate. For manifest-3 packages FULLMT
checks that `execution_gate` is present (MEM-001) and is an object (LIM-001); the gate
decision itself is taken as the producer's (BVL's) decision and is not recomputed. Every such result discloses this
as the consumer limitation `MANIFEST_3_SECTIONS_NOT_REDERIVED`. Likewise the product-internal
eligibility steps are attested, not re-derived (`ELIGIBILITY_STEPS_ATTESTED`, ELG-005
NOT_EVALUATED).

Do not read "FULLMT VERIFIED" as "BVL execution gate independently re-derived". This
disclosure changes no rule, verdict or result field.

## Run

```text
python scripts/fullmt/epc_reader.py <package-dir> [--out result.json] [--quiet]
    exit 0 VERIFIED · 1 REJECTED · 2 ERROR, or --out not written (stdout `delivery`)

python scripts/fullmt/e2e_smoke.py [--package DIR] [--out DIR]    genuine + 21 tamper cases
python scripts/fullmt/test_epc_reader.py                          dev tests
```

`--package` defaults to `$BVL_EPC_PACKAGE`, then to the BVL #49 reference path.

## What the reader does

1. Reads `EVIDENCE.json` only. If it is missing, the result is `ERROR NOT_AN_EPC_PACKAGE`.
   It never falls back to `PACKAGE.json`.
2. **Version dispatch.** `manifest_schema` selects the handler (`boomvalley-epc-manifest-1`).
   The handler refuses any `canonical_format`, `digest_algorithm` or identity version it
   was not written for (`ERROR UNSUPPORTED_*`).
3. **Containment.** Member paths must match `[A-Za-z0-9][A-Za-z0-9._-]*` segments, with no
   `..`, `\`, `:`, absolute paths, reserved device names, or two spellings of one path.
   Every path component is `lstat`-ed, and links and reparse points are refused. The
   resolved path must lie inside the root.
4. **Strict JSON** everywhere, which refuses BOMs, duplicate names, NaN/Infinity, lone
   surrogates and integers outside ±(2^53−1). canonical-json-1 applies to the producer's
   own documents; GNDCRW documents are only strict-read (REC-002).
5. Recomputes from raw bytes, with no producer code involved: member digests, `evidence_root`,
   `package_identity`, contract/design/schedule, RunIdentity, custody digest, the **Output
   Seal** (head seal), `sessions_digest`, DatasetIdentity, request digests,
   ExperimentInputIdentity and `preflight_record_sha256`.
6. **Input Lock / GNDCRW** (INP-001/002). The reader identifies each preflight member by
   its declared manifest **role** (`gndcrw_manifest`, `gndcrw_result`,
   `gndcrw_subject_<name>`), never by its filename. It then requires the same bytes to be
   named by EVIDENCE `input_lock.preflight`, the EII preimage, the preflight record, the
   GNDCRW result binding and the GNDCRW manifest. It also requires `external_subject` to
   be the ContractIdentity, the outcome to be RUN, and every BLOCKING finding to PASS.
7. **input.json content ↔ EII** (INP-003, #52 MAJOR-1). `input.json` must be a closed
   `bvl-input-lock-2` document (top level, `eii_preimage`, `normalized`,
   `execution_profile`, `declaration`, `pre_execution`: known member sets only). The
   reader recomputes `SHA-256(canonical(execution_profile.document))` and requires it to
   equal `execution_profile.digest` and `eii_preimage.execution`; the normalized profile
   must equal `execution_profile.document`; `normalized.sha256` must recompute;
   `normalized.run.label` must be the run id; the declared lock identities must be the
   lock's; normalized GNDCRW inputs/versions/policy must be the EII's. The embedded
   declaration is compared with `lock.declaration` portably (order of factors, levels and
   expectation rules ignored); lock-only members are producer defaults and surface as
   consumer limitation `DECLARATION_DEFAULTS_NOT_REDERIVED` (BVL re-lock is not
   reproduced).
8. **GNDCRW version pin** (INP-004, #52 MAJOR-2). `result_version`, `manifest_version`,
   `policy_id` and the six `contracts` must be identical across the GNDCRW result,
   GNDCRW manifest, preflight record, EII, normalized input and the EVIDENCE member
   `schema` column (skew → REJECTED), and must lie in the reader's own support table
   `GNDCRW_SUPPORTED` (result v0.2, manifest v0.2, `GNDCRW-STRICT-0.1`, the v0.1/v0.2
   contract set). Consistent but unsupported → `ERROR UNSUPPORTED_GNDCRW_VERSION`.
9. **Producer eligibility report** (ELG-001…005, #53 MAJOR-3). The report is located by
   its declared role `eligibility_report` (a relocated report is still found; its file name
   is never consulted). ELG-001: strict, canonical, schema `boomvalley-epc-eligibility-1`
   (document = manifest member `schema`; consistent but other → `ERROR
   UNSUPPORTED_ELIGIBILITY_SCHEMA`), closed members (`schema, run, producer, verdict,
   findings` + optional `informational`), producer `boomvalley-lab`, verdict in
   {ELIGIBLE, NOT_ELIGIBLE}, each finding closed (`step_id, rule_id, verdict, code` +
   optional `subject{cell}`), verdict ∈ {VERIFIED, NO_CLAIM, VIOLATED} with the matching
   code (OK / NO_CLAIM / VIOLATED), `rule_id` = the §19 step→rule map. ELG-002 (and RUN-001):
   `run` = `{kind: run, version: run/1, digest}` and the digest = FULLMT's recomputed
   RunIdentity = the manifest's. ELG-003: verdict ELIGIBLE, no finding other than
   VERIFIED/NO_CLAIM, verdict consistent with its findings, every gate step present once,
   and every step FULLMT recomputes itself stated VERIFIED (input_lock NO_CLAIM only
   without an Input Lock). ELG-004: for those steps the producer's verdict must agree with
   FULLMT's own rule (ID-003, JRN-002, SCH-001/002, CUS-003, DS-001, INP-001). ELG-005 stays
   NOT_EVALUATED: product-internal steps are attested, not re-derived (consumer limitation
   `ELIGIBILITY_STEPS_ATTESTED`) — but an explicit negative verdict on them still rejects.
   `observed.eligibility` exposes member, schema, producer, verdict, `custody_integrity`,
   per-step verdicts, finding verdict counts, `run_binding{report,manifest,recomputed}`,
   `cross_check` and `attested_steps`.

## Result document `fullmt-epc-verification-result/1`

| field | content |
|---|---|
| `result_schema`, `verifier{name,version,code_digest,code_digest_method,source_commit,source_tree,handlers}` | format/version and which committed reader sources produced it |
| `input{package_path,manifest_digest}`, `package_identity` | what was read |
| `dispatch{manifest_schema,handler,formats}` | the version dispatch taken |
| `outcome` | `VERIFIED` / `REJECTED` / `ERROR` (+ `error{code,detail}`) |
| `failed_rules`, `rules[{rule_id,layer,title,status,problems?,note?}]`, `summary` | per-rule PASS / FAIL / NOT_EVALUATED |
| `observed` | declared vs recomputed identities, seal, GNDCRW outcome/tool/findings, counts |
| `limitations{producer_declared,consumer}` | the producer's list, verbatim, plus FULLMT's own |

## Real run (reference package)

`VERIFIED` · `package_identity sha256:66077ee054ea3267…decca5c3` (recomputed = declared) ·
45 members / 12 records · head SEALED, seal `sha256:d2d6f78e…` recomputed · GNDCRW 0.2.0 RUN
(CHG findings PASS) · reader 0.3.0: 31 PASS / 0 FAIL / 2 NOT_EVALUATED (CLM-001:
`CLAIMS_NOT_EMITTED`; ELG-005: attested) · producer eligibility ELIGIBLE, custody_integrity
VERIFIED, run binding = recomputed RunIdentity `sha256:6d063209…` · consumer limitations
`RUN_UNIQUENESS_NOT_ESTABLISHED` (legacy-label run id), `DECLARATION_DEFAULTS_NOT_REDERIVED`,
`ELIGIBILITY_STEPS_ATTESTED`.

## Tamper smoke (copies only; BVL is never written)

| case | outcome | failing rules |
|---|---|---|
| artifact byte flip | REJECTED | MEM-002, CUS-002 |
| artifact flip + manifest resealed | REJECTED | CUS-002 |
| extra file | REJECTED | MEM-003 |
| manifest path `../` | REJECTED | MEM-001 (+ MEM-003/004, ID-001/002) |
| GNDCRW result edited + resealed | REJECTED | INP-002 |
| GNDCRW base/candidate swapped + resealed | REJECTED | INP-002 |
| input.json edited + resealed | REJECTED | INP-001 |
| custody head edited + resealed | REJECTED | CUS-003, SEAL-001 |
| no EVIDENCE.json | ERROR | NOT_AN_EPC_PACKAGE |
| manifest_schema -2 | ERROR | UNSUPPORTED_MANIFEST_SCHEMA |
| profile model swapped, EII kept (BVVH P13) | REJECTED | INP-003 |
| same, normalized.sha256 recomputed | REJECTED | INP-003 |
| declaration level + design_identity swapped, EII kept (BVVH P14) | REJECTED | INP-003 |
| embedded factor level only, identities kept | REJECTED | INP-003 |
| normalized run.label swapped | REJECTED | INP-003 |
| unknown input.json top-level member | REJECTED | INP-003 |
| normalized GNDCRW inputs diverge from EII | REJECTED | INP-003 |
| result_version v9.9 in every copy | ERROR | UNSUPPORTED_GNDCRW_VERSION |
| result contracts.verification v9.9 only (BVVH P16) | REJECTED | INP-004 |
| contracts.verification v9.9 in every copy | ERROR | UNSUPPORTED_GNDCRW_VERSION |
| policy GNDCRW-LAX-9 in every copy | ERROR | UNSUPPORTED_GNDCRW_VERSION |
| eligibility NOT_ELIGIBLE + custody VIOLATED (BVVH P03) | REJECTED | ELG-003, ELG-004 |
| eligibility run.digest of another run (BVVH P04) | REJECTED | RUN-001, ELG-002 |
| eligibility verdict NOT_ELIGIBLE only | REJECTED | ELG-003 |
| custody finding VIOLATED, verdict ELIGIBLE | REJECTED | ELG-003, ELG-004 |
| attested step (session_provenance) VIOLATED | REJECTED | ELG-003 |
| verdict PROVISIONAL | REJECTED | ELG-001, ELG-003 |
| unknown top-level member | REJECTED | ELG-001 (+002…004) |
| finding code contradicts verdict | REJECTED | ELG-001 |
| step rule_id swapped | REJECTED | ELG-001 |
| custody_integrity finding dropped | REJECTED | ELG-003 |
| schema -9 in report and manifest | ERROR | UNSUPPORTED_ELIGIBILITY_SCHEMA |
| report relocated to another path, role kept (control) | VERIFIED | — |

"Resealed" means the forger also recomputed every member digest, `evidence_root` and
`package_identity`. Those edits are caught only by cross-document bindings, which is the
reason FULLMT recomputes them itself.

## BVVH Wave 1 remediation (#52)

`python assurance/wave1/probe_wave1.py --only P00 P00a P00b P13 P14 P15b P16 P16b` (BVVH
`assurance/post-e2e-wave1 @ 0f65995`, run with `--out` outside the BVVH repo):

| probe | before (0.1.0) | after (0.2.0) |
|---|---|---|
| P00 / P00a / P00b | VERIFIED | VERIFIED |
| P13 | VERIFIED (fail-open) | REJECTED INP-003 |
| P14 | VERIFIED (fail-open) | REJECTED INP-003 |
| P15b | VERIFIED (fail-open) | REJECTED INP-003, INP-004 (the probe leaves the normalized copy at v0.2) |
| P16 | VERIFIED (fail-open) | REJECTED INP-004 |
| P16b | VERIFIED (fail-open) | ERROR UNSUPPORTED_GNDCRW_VERSION |

Raw results: `artifacts/fullmt/bvvh_wave1_remediation/{baseline_results,results}.json`.

## BVVH Wave 1 remediation (#53 MAJOR-3)

`python assurance/wave1/probe_wave1.py` (all probes; BVVH `@ 0f65995`, `--out`/`--scratch`
outside the BVVH repo), reader 0.3.0:

| probe | before (0.2.0) | after (0.3.0) |
|---|---|---|
| P00 / P00a / P00b | VERIFIED | VERIFIED |
| P03 | VERIFIED (fail-open) | REJECTED ELG-001, ELG-003, ELG-004 |
| P04 | VERIFIED (fail-open), RUN-001 PASS | REJECTED RUN-001, ELG-002 |
| P13 / P14 / P15b / P16 / P16b | REJECTED / ERROR | unchanged |

P03 also fails ELG-001 because the probe sets `code=ARTIFACT_DIGEST_MISMATCH`, which is not
the code the §18 vocabulary pairs with VIOLATED. No accept-expected probe changed outcome.
Raw results: `artifacts/fullmt/bvvh_wave1_remediation/major3_results.{json,txt}`.

## BVVH Wave 1 MINOR bundle A (#56, reader 0.5.0)

Reader-only hardening; the reference package keeps `package_identity
sha256:66077ee0…decca5c3` and stays VERIFIED.

- **MINOR-1** (MEM-001): EVIDENCE.json top level is closed. Required `manifest_schema,
  formats, run, identities, members, journal, limitations, evidence_root,
  package_identity`; optional `input_lock, parents, informational`.
- **MINOR-2** (STR-002): every acknowledged line of the `journal` and `custody_entries`
  members is canonical-json-1 + LF (no spaces, sorted keys, no CRLF). The torn tail is not
  a line (MINOR-4/5, common with BVL, out of scope).
- **MINOR-3** (CUS-002, MEM-005): a custody entry's `artifact` name binds exactly the
  role=artifact member `artifacts/<name>` (the run's artifact store, in place per §5/DEC-08);
  no basename match elsewhere; a role=artifact member outside `artifacts/<name>` is refused.
  Requests and the eligibility report are still found by role wherever they sit.
- **MINOR-7** (MEM-001): `members[]` must be listed in path order (segments case-folded,
  then code points — the reference producer's order), so a reordered listing is no longer
  a second valid `package_identity` (REC-015 records the POSIX compatibility caveat).
- **MINOR-8** (INP-003): every `INTENT_RECORDED.intended` = `execution_profile.document.adapter
  {adapter_provenance, model_identity}`.
- **MINOR-9** (INP-004): GNDCRW `tool` closed; `tool.name = gndcrw`;
  `code_digest_method ∈ {gndcrw-code-digest/v0.2}` (else ERROR UNSUPPORTED_GNDCRW_VERSION);
  every `tool.version` = preflight record `executable.version`.

BVVH `assurance/post-e2e-wave1 @ 4656c9b`, all Wave 1 probes and all closure seam probes,
`--out`/`--scratch` outside the BVVH repo:

| probe | #55 (0.4.0) | #56 (0.5.0) |
|---|---|---|
| P01 | VERIFIED | REJECTED MEM-001 |
| P07 | VERIFIED | REJECTED MEM-001, CUS-002, MEM-005 |
| P09 | VERIFIED | REJECTED STR-002 |
| P27 | VERIFIED | REJECTED STR-002 |
| P29 | VERIFIED | REJECTED MEM-001 |
| S02 | VERIFIED | REJECTED INP-003 |
| S06 | VERIFIED | REJECTED INP-004 |
| P00/P00a/P00b, P02, P06, P24, P30, S02b, S03, S04, S06b, S16, S17 | VERIFIED | VERIFIED |
| P03/P04/P05/P08/P13/P14/P15/P15b/P16/P16b/P20/P26/P28, S01/S05/S07–S15/S18–S21 | REJECTED / ERROR | unchanged |

No other probe changed outcome. P10–P12, P17–P19, P21–P23 and P25 remain fail-open (common
MINOR-4/5/6 and next-wave items). Raw results and a diff against #55:
`artifacts/fullmt/minor_bundle_a/`.

## BVVH Wave 1 MINOR bundle B2 (#58, reader 0.6.0) — consumer parity with BVL #57

FULLMT's own code, same meaning as BVL `impl/bvl-minor-bundle-b1 @ 5b96dd1` (no BVL/GNDCRW
import). Reference package still VERIFIED, `package_identity sha256:66077ee0…decca5c3`;
GNDCRW pin `cace4dea` unchanged; `members[]` comparator is the same `member_order` BVL #57
now uses (no drift, no new identity semantics).

- **MINOR-4** (CUS-001): the `custody_entries` member is consumed in full: bytes after the
  last LF (a torn or forged, unterminated record) are refused. A sealed ledger has no torn
  tail. P10 → REJECTED CUS-001.
- **MINOR-5** (JRN-004): the journal torn tail is observed from the raw bytes and must agree
  both ways with the producer limitation `JOURNAL_TORN_TAIL` (§17, DEC-05). Undeclared tail
  → REJECTED; declared without tail → REJECTED; declared tail → VERIFIED with consumer
  limitation `JOURNAL_TORN_TAIL_NOT_READ`. `observed.journal` records extent + declaration.
- **MINOR-6** (new rule **INP-005**, only when INPUT_LOCKED): the GNDCRW result means one
  thing. Closed `status` / `policy_class` vocabularies and the RESULT_CONTRACT §9 table
  (BLOCKING: PASS/FAIL/UNVERIFIABLE/NOT_APPLICABLE; REQUIRED_NONBLOCKING: all five;
  ADVISORY: PASS/WARNING/NOT_APPLICABLE); unique `finding_id`; `outcome ∈ {RUN, BLOCK,
  UNVERIFIABLE}`; `summary` recomputed from findings; under `GNDCRW-STRICT-0.1` the outcome
  recomputed from BLOCKING findings (FAIL → BLOCK, else UNVERIFIABLE → UNVERIFIABLE, else
  RUN); every `rule_id` of the `gndcrw_subject_declaration` member's `expected_changes`,
  `invariants`, `declared_consequences` has a finding; empty findings refused (DECLARATION
  §19: a result always carries at least the focal-change finding). Unsupported policy
  versions remain INP-004 ERROR. `observed.gndcrw_semantics` records the recomputation.

BVVH `assurance/post-e2e-wave1 @ 4656c9b`, all Wave 1 + closure probes, `--out`/`--scratch`
outside the BVVH repo (`artifacts/fullmt/minor_bundle_b2/`):

| probe | #56 (0.5.0) | #58 (0.6.0) |
|---|---|---|
| P10 | VERIFIED | REJECTED CUS-001 |
| P11 | VERIFIED | REJECTED JRN-004 |
| P17 | VERIFIED | REJECTED INP-005 |
| P18 | VERIFIED | REJECTED INP-005 |
| P19 | VERIFIED | REJECTED INP-005 |
| P20 | REJECTED INP-002 | REJECTED INP-002, INP-005 |
| every other Wave 1 / closure probe | — | unchanged |

e2e_smoke: 11 new cases (73 total incl. genuine; legal control `journal_torn_tail_declared`
VERIFIED); tests 137/137.

## Codes, i18n and logging (#125, reader 0.11.0)

Three vocabularies, each defined once, never localized, never mixed:

| vocabulary | defined in | appears in the result as | when |
|---|---|---|---|
| StatusCode `Outcome` VERIFIED / REJECTED / ERROR, `RuleStatus` PASS / FAIL / NOT_EVALUATED | `scripts/fullmt/fullmt_codes.py` | `outcome`, `rules[].status` | always |
| rule id (MEM-001 … LIM-002: id → layer, title) | `scripts/fullmt/fullmt_rules.py` `RULES` | `rules[].rule_id`, `failed_rules` | REJECTED names rules; no error code |
| `ErrorCode` | `scripts/fullmt/fullmt_codes.py` | `error{code,detail}` + `error_code` | ERROR only; no `failed_rules` |

`ErrorCode` covers externally observable program failures only: `USAGE_ERROR` (CLI
arguments, stderr only), `PACKAGE_NOT_A_DIRECTORY`, `PACKAGE_ROOT_IS_A_LINK`,
`NOT_AN_EPC_PACKAGE`, `PERMISSION_DENIED`, `IO_ERROR`, `OUTPUT_WRITE_ERROR` (`--out` not
writable: stdout still carries the result plus `delivery`, exit 2; see below), `JSON_PARSE_ERROR` (EVIDENCE.json not
strict JSON), `UNSUPPORTED_MANIFEST_SCHEMA` / `_FORMAT` / `_IDENTITY_VERSION` /
`_ELIGIBILITY_SCHEMA` / `_GNDCRW_VERSION`, `CONSUMER_RUNTIME_ERROR` (recursion / memory
limit), `INTERNAL_ERROR` (any unexpected exception; `verify_package` never raises).

Public contract changes in 0.11.0 (additive except the first):

- A malformed EVIDENCE.json is `ERROR JSON_PARSE_ERROR` (was `REJECTED STR-001`); STR-001
  is now evaluated at one place only (member documents), and still REJECTS there.
- ERROR results also carry top-level `error_code` (= `error.code`).
- Deep nesting / unexpected exceptions give `ERROR CONSUMER_RUNTIME_ERROR` /
  `INTERNAL_ERROR` instead of a traceback; a permission failure is `PERMISSION_DENIED`.
- `verifier.code_digest` covers every reader source (`READER_SOURCES`), not epc_reader.py
  alone.
- INP-004: "consistent but unsupported GNDCRW version → ERROR" is decided on a structured
  copy-skew flag, no longer on the text "disagree" in a problem line.

Unchanged: exit codes 0 / 1 / 2, the result JSON on stdout, the `--quiet` line, every rule
id, title and verdict.

Human text goes through `scripts/fullmt/fullmt_i18n.py` with resources
`scripts/fullmt/locales/{en-US,ko-KR}.json` (same key set; lookup falls back to en-US,
then to the key). Locale: `--locale` > `$FULLMT_LOCALE` > en-US. Only CLI help and stderr
diagnostics are localized; stdout is byte-identical across locales.

Diagnostics go to the `fullmt` logger on stderr (`--log-level` > `$FULLMT_LOG_LEVEL` >
WARNING); used as a library it is silent. `print` remains only for the CLI contract
output (reader: result JSON / `--quiet` line; smoke: its report) and in the dev test
runner's PASS/FAIL lines. Machine paths live in `scripts/fullmt/fullmt_config.py`
(`$BVL_ROOT`, `$BVL_EPC_PACKAGE`).

## Result delivery (`--out`) — RC129-N2 (#131, reader 0.11.1)

The verdict and the delivery of the result file are separate axes. A failed `--out` write
never changes `outcome`: a VERIFIED package stays `VERIFIED` and a REJECTED one stays
`REJECTED` with the same `failed_rules`. The failure is reported beside the verdict:

| verdict | `--out` | exit | stdout (JSON) | `--quiet` line | result file | stderr |
|---|---|---|---|---|---|---|
| VERIFIED | none / written | 0 | result (= file, byte for byte) | `VERIFIED <id> failed=[]` | written | — |
| REJECTED | none / written | 1 | result (= file) | `REJECTED <id> failed=[...]` | written | — |
| ERROR | none / written | 2 | result + `error{code,detail}`, `error_code` | `ERROR ...` | written | `[<code>]` |
| VERIFIED / REJECTED | write failed | 2 | result + `delivery` | outcome line + ` delivery=OUTPUT_WRITE_ERROR` | not written | `[OUTPUT_WRITE_ERROR]` |
| ERROR | write failed | 2 | ERROR result + `delivery` | `ERROR ... delivery=OUTPUT_WRITE_ERROR` | not written | both codes |

`delivery = {status: "FAILED", error_code: "OUTPUT_WRITE_ERROR", out, detail}` appears only
on stdout and only when the write failed; `detail` is `<OS exception class>: <OS message>`
(diagnostic, not a contract). `error` / `error_code` stay reserved for an ERROR verdict.
Exit 2 therefore means: stdout carries an ErrorCode, in `error_code` (no verdict) or in
`delivery.error_code` (verdict computed, file not delivered). Every write failure in the
supported range — target is a directory, parent is a file, permission / read-only target,
invalid path, I/O error — has the one stable code `OUTPUT_WRITE_ERROR`. The file is written
to a temp file beside the target and then replaced in one step, so a failure leaves no
partial result; an existing file at the target is left as it was (and is not this run's
result). Codes and statuses are identical under en-US and ko-KR; only stderr text is
localized. Unchanged: exit codes 0 / 1 / 2, successful stdout, rules and verdicts.
Development tests N1–N9 (`test_out_delivery`).

## Reader code identity — RC133-N1 (#135, reader 0.11.2)

`verifier.code_digest` is the identity of the reader's sources **as committed in Git**, not
of the checkout bytes. Before 0.11.2 it hashed the working copy, so a Windows checkout with
`core.autocrlf=true` (CRLF) reported a different digest from a Linux/macOS (LF) checkout of
the same commit.

`code_digest_method = "git-source-manifest-v1"`:

1. source set = `READER_SOURCES` (unchanged: `epc_reader.py`, `fullmt_codes.py`,
   `fullmt_rules.py`, `fullmt_i18n.py`, `fullmt_log.py`, `locales/en-US.json`,
   `locales/ko-KR.json`), as repo-relative POSIX paths (`scripts/fullmt/...`);
2. paths sorted lexicographically (duplicates collapse);
3. each path read as its Git blob at `source_commit` (= `HEAD`; `git cat-file blob
   <commit>:<path>`, the committed bytes — no EOL conversion, no filter);
4. `code_digest = sha256(canonical-json-1({"algorithm": "git-source-manifest-v1",
   "entries": [{"path": <path>, "sha256": "sha256:<hex of blob>"}, ...]}))`.

It can be recomputed from Git alone on any platform (`epc_reader.git_source_manifest(repo,
commit, paths)`, or `git cat-file blob` + SHA-256 by hand).

The working tree is evidence beside the digest, never part of it: `source_tree` is `clean`
when `git status` shows no change to those paths (a CRLF checkout of LF blobs is clean), or
`dirty` (the running code differs from `source_commit`; `code_digest` still names the
commit's content). Files outside the set — untracked or not — cannot change the digest.
Outside a Git checkout (or without `git`), `code_digest` / `source_commit` are `null` and
`source_tree` is `unavailable`; no checkout-bytes digest is ever reported under this name.
Additive fields only; outcome, rules, failed_rules, exit codes and `--out` delivery are
unchanged. Development tests P1–P10 (`test_code_identity`).

## Adapter provenance parity — BVL-REC-087 (#176/#179, reader 0.11.3)

New rule **INP-006** (L3, only when INPUT_LOCKED). FULLMT reads the provider contract of each
BVL adapter kind from the locked profile and the journal with its own code (no BVL import):

| adapter.kind | adapter_provenance | model_identity |
|---|---|---|
| `local` | exactly `boomvalley-lab-local-1` | non-empty, never a pinned digest (`@sha256:`) — the local adapter calls no model |
| `ollama` | `boomvalley-lab-ollama-1;ollama=<version>` | `<adapter.ollama.model>@sha256:<64 hex>` |
| other | — (no namespace in this reader) | — |

The rule applies to the intended identity (`execution_profile.document.adapter`) and to every
`CALL_RETURNED.actual_execution`, and every actual execution must equal the intended identity.
Each problem starts with a machine-readable code:
`ADAPTER_PROVENANCE_NAMESPACE_MISMATCH`, `ADAPTER_MODEL_IDENTITY_FORMAT_MISMATCH`,
`ACTUAL_EXECUTION_NOT_INTENDED`; `observed.adapter_parity` = `{kind, problems, codes}`.

| package | 0.11.2 | 0.11.3 |
|---|---|---|
| BVVH #174 A4 (`kind=local`, pinned Qwen identity, Ollama provenance, 0 model calls) | VERIFIED | REJECTED INP-006 |
| BVL local reference (`bvl_epc_c1_canonical`, `bvl_epc_ex001`) | VERIFIED | VERIFIED |
| BVL real Qwen (`bvl_157_epc`, `bvl_162_stage_c`, BVVH #174 control) | VERIFIED | VERIFIED |
| smoke S02b `profile_swap_intents_follow` (profile + intents say gpt-4o, actual local-echo) | VERIFIED | REJECTED INP-006 |

Not established (BVVH #174 NE-1/NE-2): that an Ollama server reports its identity or output
truthfully. The namespace is a contract on what the producer states, not an attestation.
Development tests Q1–Q15 (`test_adapter_parity`).
