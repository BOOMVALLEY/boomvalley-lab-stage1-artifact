# Example B — S2 Manual Decision-Rationale Experiment

**Evidence class: MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED.**

Example B is a follow-up to the buying center study of Example A ([`examples/bcp_demo/`](../bcp_demo/README_EN.md)). It restores one decision state of Example A's condition R, the moment just after Buyer Co.'s purchasing director counter-offered 420,000, and runs the two Supplier Co. actors again, one call at a time, each started by the researcher. Each actor is asked for its move **and**, in the same response, for its stated reasons.

It is a case of **a mismatch between an organization's internal limit and the decision of the AI manager who holds the decision authority**, not a negotiation success story.

## Why this decision

In Example A's condition R, Supplier Co.'s manager accepted 420,000, below the lowest acceptable price of 430,000 stated in its own brief, and against its negotiator's draft of 440,000. The sealed answers contain only `side`, `move` and `price`, so they say nothing about the reasons. Example B records the reasons that the model states, under the same state and information.

## Input state

| | |
|---|---|
| Supplier's first offer | 450,000 |
| Buyer's counter-offer | 420,000 |
| Supplier's lowest acceptable price | 430,000 (supplier briefs only) |
| Sales target | "The quarter's sales target makes this deal important." (supplier briefs) |
| World | talks open, supplier to move: `{"deadline":10,"moves":2,"offers":{"buyer":420000,"seller":450000},"price":0,"status":"open","turn":"seller"}` |

The state and the briefs are files of Example A's sealed R package and sources; the runner checks that it rebuilds the sealed supplier requests byte for byte before it creates a session.

## Steps and what was recorded on 2026-10-27

| Step | Actor | Receives | Decision | Stated reason (excerpt) | World |
|---|---|---|---|---|---|
| N | Supplier Negotiator | own brief, World | `offer` 440,000 | "We aim to close the deal while ensuring a reasonable profit margin." | not applied (a draft) |
| M | Supplier Manager | own brief, the draft's `side`/`move`/`price`, World | `accept` 420,000 | "To close the deal and meet the quarter's sales target, we accept the buyer's offer." | `accepted`, `ADMISSIBLE`; agreed at 420,000 |

- The manager's decision differs from the negotiator's draft.
- The manager's decision is 10,000 below the lowest acceptable price.
- The World judged the acceptance `ADMISSIBLE` (its rule knows the table, not the supplier's floor), and the deal was agreed at 420,000.
- The manager cited the sales target. It did not explicitly address the conflict with the lowest acceptable price.

That the manager cited the sales target does not show that the sales target caused the decision; that it did not mention the lowest acceptable price does not show that it did not register it. Full result and the seven questions: [`results/bcp_s2_manual/FINAL_RESULT_EN.md`](../../results/bcp_s2_manual/FINAL_RESULT_EN.md).

## What Example B adds, and what it does not

**Adds:** a way to restore a recorded decision state, run each AI call only after the researcher has seen its full input, and keep the action and the stated reasons of the same response together with the World outcome.

**Does not establish:** behavior of human managers; the causal mechanism of the rule violation; the model's internal reasoning; statistical reproducibility (each step ran once); the reasons of the sealed run's call (those answers carry no reasons, and the reply instruction and `max_tokens` differ).

## Folder

| Path | What |
|---|---|
| [`EXPERIMENT_PROTOCOL.md`](EXPERIMENT_PROTOCOL.md) | Design, information access, reply instruction, options, World rule, stopping rules, differences from Example A |
| [`MANUAL_RUN_GUIDE.md`](MANUAL_RUN_GUIDE.md) | How to run the two steps yourself, and what can and cannot be reproduced |
| `bcp_s2.py` | The runner (`init`, `status`, `show`, `call`); messages are in Korean, translated in the guide |
| `harness/` | The S1 manual harness it reuses read-only (`bcp_manual.py`, `protocol.json`) and the two supplier briefs |
| `inputs/original_R_run/` | The three files of the sealed R package that S2 starts from: the World state after the counter-offer and the sealed requests of the negotiator and the manager (byte-identical to `results/bcp_demo/run_2026-10-23/RUN-R/`) |

The record of the 2026-10-27 run is in [`results/bcp_s2_manual/`](../../results/bcp_s2_manual/README.md).
