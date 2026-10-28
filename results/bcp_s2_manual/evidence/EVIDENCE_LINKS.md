# Example B — Evidence Links

**MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED.**

This file links every input of S2 to the file in this edition that holds it, and every S2 record to the hash recorded at run time. Paths are relative to the edition folder.

## 1. Inputs recorded in `S2/state.json` (`kit`) and where they are in this edition

At `init` the runner recorded the SHA-256 of each file it reads; every command refused to proceed if one of them changed. Local absolute paths are replaced by placeholders (section 3).

| SHA-256 recorded in `S2/state.json` | Recorded as | In this edition (byte-identical) |
|---|---|---|
| `74ec4cc1dc0270380db5201f4f12ccd5f38ba82ae6b0113ffa478b7294cffe3a` | `<BCP_R_RUN>\evidence-v2\world_state\74ec4cc1….json` | `results/bcp_demo/run_2026-10-23/RUN-R/evidence-v2/world_state/74ec4cc1….json` (a member of the sealed R package) and its copy `examples/bcp_s2_manual/inputs/original_R_run/evidence-v2/world_state/74ec4cc1….json` |
| `078d3acccfcf22ff10307959d8cac300daf2f6651eb15fcbb3ed185e6c10546c` | `<BCP_R_RUN>\requests-v2\request-078d3acc….json` (sealed negotiator request) | `results/bcp_demo/run_2026-10-23/RUN-R/requests-v2/request-078d3acc….json`; copy in `examples/bcp_s2_manual/inputs/original_R_run/requests-v2/` |
| `c6e13f68083f532d8ba371da91875a0ee314e9623e934621221b4824a50d7b3f` | `<BCP_R_RUN>\requests-v2\request-c6e13f68….json` (sealed manager request) | `results/bcp_demo/run_2026-10-23/RUN-R/requests-v2/request-c6e13f68….json`; copy in `examples/bcp_s2_manual/inputs/original_R_run/requests-v2/` |
| `fd6246284cff688f208b7f4d7d55c70073aca0ad5c59c510bed74c12aaa9cf0c` | `<S1_KIT>\inputs\original\phase_rf\supplier_negotiator_response_brief.json` | `examples/bcp_demo/sources/supplier_negotiator_response_brief.json`; copy `examples/bcp_s2_manual/harness/inputs/original/phase_rf/` |
| `0ca754d674ccb08ac775dc65244ee24f49fb8de494f7938c4e7bcd81a8b2c509` | `<S1_KIT>\inputs\original\phase_rf\supplier_manager_response_brief.json` | `examples/bcp_demo/sources/supplier_manager_response_brief.json`; copy `examples/bcp_s2_manual/harness/inputs/original/phase_rf/` |
| `afc1b57d29eea71c7b017c82538fc48458bf5d4e4a56d98df7ce88de7ff0113a` | `<S1_KIT>\bcp_manual.py` (S1 manual harness) | `examples/bcp_s2_manual/harness/bcp_manual.py` |
| `bbb863280fdf15234d07aabe2e07e31a0b643b2adaa6103f7973f457dd976009` | `<S1_KIT>\protocol.json` (S1 protocol: reply texts, options, facts) | `examples/bcp_s2_manual/harness/protocol.json` |
| `c4a2ad009fb433c748c1dd1057259b1443c61439bef674d7d4a19219471e360c` | `<S2_KIT>\bcp_s2.py` (the runner as used) | `results/bcp_s2_manual/evidence/original_runner/bcp_s2.py` |

The run folder `<BCP_R_RUN>` that S2 read was byte-identical, file by file, to `results/bcp_demo/run_2026-10-23/RUN-R` (checked when this edition was assembled). That sealed package is verified by FULLMT (`results/bcp_demo/run_2026-10-23/fullmt-R.json`); the verification covers those input files, not the S2 records.

## 2. The runner in `examples/bcp_s2_manual/`

`examples/bcp_s2_manual/bcp_s2.py` (SHA-256 `db6714fe64d48066cd068684cd0e78e512456a74af195ea4c96ca654873d5883`) is the runner of section 1 with three lines changed so that it finds its inputs inside the example folder:

```diff
-기존 수동 하네스 ../bcp-manual/bcp_manual.py 와 protocol.json 을 읽기 전용으로 가져다 쓴다
+기존 수동 하네스 harness/bcp_manual.py 와 harness/protocol.json 을 읽기 전용으로 가져다 쓴다
-MANUAL_KIT = KIT.parent / "bcp-manual"
+MANUAL_KIT = KIT / "harness"
-ORIGINAL_RUN = KIT.parent / "bcp" / "RUN-R"
+ORIGINAL_RUN = KIT / "inputs" / "original_R_run"
```

When this edition was assembled, the changed runner was run from a copy of the example folder with `init` and `show N` only (no model call): the five restoration checks passed, and the model-facing request it built for step N (the `request` object of `request.json`: message, options, seed, model) was identical to the one recorded in `S2/calls/N/request.json`. Step M cannot be checked this way, because its request contains the draft of a new step-N answer.

## 3. Path anonymization

Local absolute paths in the S2 and S1 records are replaced by placeholders:

| Placeholder | Stands for |
|---|---|
| `<S2_KIT>` | working folder of the S2 runner and its session |
| `<S1_KIT>` | working folder of the S1 manual harness |
| `<BCP_R_RUN>` | run folder of condition R, byte-identical to `results/bcp_demo/run_2026-10-23/RUN-R` |
| `<BCP_RUN_DIR>` | the folder holding that run folder |
| `<VENV>` | Python virtual environment in which BOOMVALLEY Lab `1.0.0rc3` was installed |

`ANONYMIZATION_MANIFEST.json` lists every copied record with its original SHA-256, its distributed SHA-256, whether it is byte-identical, and the replacements made. Of 62 files, 54 are byte-identical; 8 were changed only by these replacements:

| File | Placeholders | SHA-256 as recorded → in this edition |
|---|---|---|
| `S2/calls/N/request.json` | `<S1_KIT>`, `<BCP_R_RUN>` | `8c6fbdd8fa0d…` → `1ba3a80ffcff…` |
| `S2/calls/M/request.json` | `<S1_KIT>`, `<BCP_R_RUN>` | `f7eb86c3d083…` → `be2152a40305…` |
| `S2/calls/N/record.json` | `<S1_KIT>` | `cd0e45577cab…` → `0d754a5ff239…` |
| `S2/calls/M/record.json` | `<S1_KIT>` | `512c60ef30b5…` → `1dbd44853910…` |
| `S2/state.json` | all four JSON placeholders | `9397e898af0e…` → `f744ea7a670c…` |
| `reference_S1/state.json` | `<VENV>` | see the manifest |
| `original_records_ko/FINAL_BCP_S2_RESULT_KO.md` | `<S2_KIT>`, `<S1_KIT>`, `<BCP_R_RUN>`, `<BCP_RUN_DIR>` | see the manifest |
| `original_records_ko/BCP_FINAL_COMPARISON_KO.md` | `<S2_KIT>`, `<S1_KIT>`, `<BCP_R_RUN>` | see the manifest |

The replacements touch only the `information_origin`, `world_origin`, `original_request`, `kit` and `bvl_reuse` fields. The `request` object (the message sent to the model, with model, options and seed), the raw responses (`response.bin`), the approvals (`approval.json`, which carry the recorded request SHA-256) and all decisions, rationales and World states are unchanged. The confirmation codes in the approvals are the first 12 characters of the request SHA-256 as recorded, not of the distributed files.

The originals are kept unchanged outside this edition.
