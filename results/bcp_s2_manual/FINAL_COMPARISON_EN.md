# BCP — Comparison of the Sealed Run, S1 and S2

English edition of `original_records_ko/BCP_FINAL_COMPARISON_KO.md`. The three runs differ in information, reply instructions and model settings as shown below; they are not assumed to be the same. Each condition ran once.

| Run | Record | Evidence class |
|---|---|---|
| Sealed run, conditions R and F (Example A) | `results/bcp_demo/run_2026-10-23/` (the same decisions on 2026-10-18; R with the same package identity) | BOOMVALLEY Lab sealed packages (`MANIFEST-4.json`), `bvl verify` `VERIFIED`, FULLMT `VERIFIED CONFORMANCE` |
| S1, 2026-10-27, 12 calls (phases P, E, R, F run anew) | `reference_S1/` | MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED |
| S2, 2026-10-27, 2 calls (Example B) | `S2/` | MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED |

## 1. Conditions [FACT]

| Item | Sealed run | S1 | S2 |
|---|---|---|---|
| Scope | P and E fixed (sealed 2026-10-18) → R, F | P, E, R, F all run anew | only the two supplier actors, from the sealed R state after the 420,000 counter-offer |
| Model | `qwen2.5:7b-instruct`; digest not bound in the evidence | `qwen2.5:7b-instruct`, digest `845dbda0…` | `qwen2.5:7b-instruct`, digest `845dbda0…` |
| Reply instruction | `side`/`move`/`price` | + `rationale`/`evidence_used`/`concerns` | as S1 |
| `max_tokens` (decision calls) | 96 | 512 | 512 |
| temperature | 0 | 0 | 0 |
| Seed | derived by BVL from the plan | derived by the harness (different from the sealed run) | the sealed R seeds |
| Stated reasons recorded | no | yes, same response | yes, same response |

## 2. Results [FACT]

| Item | Sealed R | Sealed F | S1 R | S1 F | **S2** |
|---|---|---|---|---|---|
| Supplier's first offer | 450,000 | 450,000 | 450,000 | 450,000 | 450,000 (sealed state) |
| Director's move | `offer` 420,000 | `accept` 450,000 | `accept` 450,000 | `accept` 450,000 | (the sealed R `offer` 420,000 is the input) |
| Negotiator draft | `offer` 440,000 | `accept` 450,000 | `accept` 450,000 | `accept` 450,000 | **`offer` 440,000** |
| Manager decision | `accept` 420,000 | `accept` 450,000 | `accept` 450,000 | `accept` 450,000 | **`accept` 420,000** |
| Manager departs from the draft | yes | no | no | no | **yes** |
| Below the lowest acceptable price (430,000) | **yes** (−10,000) | no | no | no | **yes** (−10,000) |
| Manager decision applied by the World | `accepted` | `closed` (talks already agreed; not applied) | `closed` (not applied) | `closed` (not applied) | **`accepted`** |
| Final state | agreed 420,000 | agreed 450,000 | agreed 450,000 | agreed 450,000 | **agreed 420,000** |
| Manager's stated reasons [MODEL-STATED] | not recorded | not recorded | "The price offered matches our minimum acceptable price, and the deal is important for our quarterly sales target." | "The price offered matches our minimum acceptable price, and the deal is important for our sales target." | "To close the deal and meet the quarter's sales target, we accept the buyer's offer." |

- In S1 the director accepted 450,000 at once, so the supplier manager never had to choose between the lowest acceptable price and the sales target. A manager decision on an offer below that price was observed only in the sealed R run and in S2.
- The S1 manager's reason ("matches our minimum acceptable price") does not agree with the numbers (450,000 ≠ 430,000).

## 3. The question S2 addressed

**Why did the supplier manager accept an offer 10,000 below its lowest acceptable price?**

- [FACT] The sealed answer carries no reason. The reason for the sealed acceptance remains **unknown**.
- [FACT] From the restored state, the S2 manager took the same action (`accept` 420,000).
- [MODEL-STATED] The S2 manager's explanation: closing the deal and the quarter's sales target, citing the sales-target sentence and the buyer's offer. It did not mention the lowest acceptable price, did not say it was making an exception, and listed no concerns.
- [FACT] The S2 explanation was generated under a reply instruction and `max_tokens` different from the sealed run. It is not the reason of the sealed call.
- [INFERENCE] In S2 the stated reasons point only to the sales target, and the sentence on the lowest acceptable price in the same brief does not appear in them. This is one observation; it establishes neither a cause nor general reproducibility.

## 4. Closure

The sealed records and the S1 records were not changed, and S2 results were not mixed into them. Only the sealed run is a BOOMVALLEY Lab sealed package; S1 and S2 are manual harness records. The BCP experiments ended with S2.
