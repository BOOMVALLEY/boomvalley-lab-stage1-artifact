# Run Record of Example B (S2)

**MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED.**

This folder holds the record of the manual decision-rationale experiment S2 of [`examples/bcp_s2_manual/`](../../examples/bcp_s2_manual/README.md), run on 2026-10-27 with two model calls. It is not a BOOMVALLEY Lab evidence package: there is no `MANIFEST-4.json`, and neither `bvl verify` nor FULLMT applies to it. The verification results of Example A (`results/bcp_demo/`) do not extend to it.

| Path | What |
|---|---|
| [`FINAL_RESULT_EN.md`](FINAL_RESULT_EN.md) | The result: inputs, differences from the sealed run, both answers, World outcome, the seven questions, limits |
| [`FINAL_COMPARISON_EN.md`](FINAL_COMPARISON_EN.md) | The sealed run (R, F), S1 (R, F) and S2 in one table |
| `S2/state.json` | Session: restoration checks, input hashes (`kit`), model server record, reused BVL modules, completed steps |
| `S2/calls/N/`, `S2/calls/M/` | Per call: `request.json` (the full request as shown to the researcher before approval), `approval.json`, `response.bin` (raw model response), `record.json` (parsed decision, stated rationale, World before/after, rule checks) |
| [`evidence/EVIDENCE_LINKS.md`](evidence/EVIDENCE_LINKS.md) | How every S2 input links to the sealed R package of Example A, the runner, and the path anonymization |
| `evidence/ANONYMIZATION_MANIFEST.json` | Original and distributed SHA-256 of every copied record, with the replacements made |
| `evidence/original_runner/bcp_s2.py` | The runner exactly as used (its SHA-256 is in `S2/state.json`) |
| `original_records_ko/` | The original Korean research records of S2 (`FINAL_BCP_S2_RESULT_KO.md`, `BCP_FINAL_COMPARISON_KO.md`), unchanged except for local paths |
| `reference_S1/` | The record of S1 (2026-10-27, 12 calls with the same manual harness, phases P, E, R, F run anew), cited in the comparison; same evidence class. Its Korean documents `RESULT_S1.md` and `RESULTS_FACTS.md` are the original research records |

To check the raw answers against the records without any tool, compare `response.bin` with `raw_response` in `record.json`, and the SHA-256 of `response.bin` with `response_sha256` in `record.json`.
