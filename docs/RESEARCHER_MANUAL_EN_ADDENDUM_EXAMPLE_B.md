# Researcher Manual — Addendum: Example B (Manual Decision-Rationale Experiment)

This addendum belongs to `RESEARCHER_MANUAL_EN.md` of this edition. It adds Example B to the anonymous review edition and changes nothing else in the manual. The PDF edition of the manual predates Example B; where it says (section 0.1) that the edition "includes one example only", this addendum applies.

## B.1 What Example B is

`examples\bcp_s2_manual\` restores one decision state of the buying center study (`examples\bcp_demo\`, condition R, just after the purchasing director's counter-offer of 420,000) and runs the two Supplier Co. actors again, one call at a time. Each call is started by the researcher after reading its full input, and each actor is asked, in the same response, for its move and its stated reasons. The run of 2026-10-27 is recorded in `results\bcp_s2_manual\`.

**Evidence class: MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED.**

## B.2 Why it is not a `bvl run`

`bvl run` calls the actors of a cell one after another without stopping. The per-call stop option `--stop-after` is refused for `bvl-study-1` studies (`USAGE_ERROR OPTION_NOT_SUPPORTED`, section 7.8), and `bvl resume` continues a run to its end. Declaring the recorded state as the `initial_world_state` of a new study would make a new plan, with requests and seeds of its own, rather than replay the sealed calls. Example B therefore uses a small runner (`bcp_s2.py`) that reuses read-only, without changing them, the BVL components `OpenAIChatAdapterV1` (one attempt, no retry), `RequestV2` and `canonical_json` (the message layout of `bvl.json-renderer:1`), `JsonProposalParserV1`, the closed move schema, and `NegotiationWorldV1`. It does not use the gate, GNDCRW, the journal, custody, `bvl package`, `bvl verify` or FULLMT, so the guarantees of Part 6 for those tools do not apply to its records.

## B.3 How it relates to the sealed run

- Its inputs are files of the sealed R package `results\bcp_demo\run_2026-10-23\RUN-R\` and the sample's two supplier briefs; before creating a session the runner rebuilds the sealed supplier requests from them and requires byte identity.
- Information access, decision authority (the manager alone) and the World rule are those of the sealed run.
- Changed: the `reply` field of the briefs (asks also for `rationale`, `evidence_used`, `concerns`) and `max_tokens` (512 instead of 96). Temperature 0 and the sealed seeds are kept. The model digest is recorded at each call; the sealed evidence does not bind it.

## B.4 Where to read and how to run

| Purpose | File |
|---|---|
| Overview | `examples\bcp_s2_manual\README.md` |
| Protocol | `examples\bcp_s2_manual\EXPERIMENT_PROTOCOL.md` |
| Running it (2 model calls, each confirmed) | `examples\bcp_s2_manual\MANUAL_RUN_GUIDE.md`; `REPRODUCIBILITY.md`, section 8 |
| Result, with FACT / MODEL-STATED / INFERENCE kept apart | `results\bcp_s2_manual\FINAL_RESULT_EN.md` |
| Comparison with the sealed run and the earlier manual session S1 | `results\bcp_s2_manual\FINAL_COMPARISON_EN.md` |
| Input links, hashes, path anonymization | `results\bcp_s2_manual\evidence\EVIDENCE_LINKS.md` |

## B.5 Interpretation (in the sense of Part 6)

A stated reason is what the model wrote, not a record of how the decision was computed. In Example B the manager accepted 420,000, below the lowest acceptable price of 430,000 in its brief, and stated the deal and the quarter's sales target as its reasons. This does not establish that the sales target caused the decision, that the manager did not register the price limit, how human managers behave, or that the result would recur. Each step ran once.
