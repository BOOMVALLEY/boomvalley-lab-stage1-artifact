# Sample Demo — Buying Center: Does the Director's View of the Evaluations Change the Purchase?

The sample study of this edition. A buyer organization with four functional evaluators and a purchasing director negotiates the purchase of an enterprise software subscription with a supplier organization. Two conditions differ in one thing only: **which of the four evaluations the purchasing director may see.** The user runs both conditions by **typing the commands one line at a time**.

```text
Researcher (user)
   ↓
BOOMVALLEY Lab   check and gate     bvl check --experiment study.json --cell <cell>       → gate-2 CLEARED
                 (GNDCRW inside)    GNDCRW compares the two cells: only the declared difference
   ↓
BOOMVALLEY Lab   run and seal       bvl run --experiment study.json --cell <cell> --into RUN-R
                                    bvl package RUN-R                                       → MANIFEST-4.json
   ↓
FULLMT 0.12.0    independent check  python fullmt\epc_reader.py RUN-R --out fullmt-R.json   → VERIFIED / REJECTED / ERROR
   ↓
Research evidence (two sealed packages, one per condition)
```

Run it from a copy in a working folder with a short path (for example `C:\bvdemo\bcp`). The steps are in [`SAMPLE_GUIDE_EN.md`](SAMPLE_GUIDE_EN.md).

## Research question

Can the members of a buying organization each judge a purchase favorably while the organization, as a whole, does not buy? A secondary question: does the scope of the evaluations the decision maker can see change what the organization does and how the counterpart responds?

This study calls the first case the **Buying Center Paradox (BCP)**: all evaluators are in favor, yet the purchasing director walks away. The name is a working label for the phenomenon to be observed, not an established theory.

## Scenario

| Organization | Actor | Role | Official authority |
|---|---|---|---|
| Buyer Co. | IT evaluator | Technical fit, security, integration | — |
| Buyer Co. | Finance evaluator | Cost, budget, return on investment | — |
| Buyer Co. | Operations evaluator | Operational fit, usability, timeline | — |
| Buyer Co. | Procurement evaluator | Purchasing process, contract and supplier risk | — |
| Buyer Co. | `purchasing_director` | Purchasing director | Buyer Co.'s move: `accept`, `offer` (counter-offer) or `walk_away` |
| Supplier Co. | `supplier_negotiator` | Sales negotiator; drafts the supplier's response | — |
| Supplier Co. | `supplier_manager` | Commercial manager | Supplier Co.'s move (`builtin.single-authority:1`) |

All actors answer with `qwen2.5:7b-instruct` (local Ollama, temperature 0).

- Subject: a 3-year subscription to the fictitious "DocStream AI" document-processing platform, including implementation. List price 520,000 USD.
- Each actor receives only the information of its own function. The supplier's lowest acceptable price (430,000 USD) is known only to Supplier Co.; Buyer Co.'s approved budget (480,000 USD) was known only to the finance evaluator. No actor is told to refuse or to create conflict.
- The common deal terms include a liability cap of 12 months of fees; Buyer Co.'s procurement rule requires at least 24 months for a critical supplier (known only to the procurement evaluator).

## Design: the short path

The full study has four phases. This sample runs **the last two (conditions R and F)**; the first two are fixed inputs, recorded and sealed on 2026-10-18.

| Phase | What happens | In this sample |
|---|---|---|
| P | Supplier Co. makes its first offer (negotiator drafts 470,000, manager decides **450,000**). | Fixed input: `sources\supplier_offer.json` and `initial_world_state` in `study.json` |
| E | The four evaluators assess the offer independently, without seeing each other. **All four are in favor.** The same four evaluations are used in both conditions. | Fixed input: `sources\eval_*.json` |
| R | Restricted: the director sees the procurement evaluation only. The director decides; Supplier Co. responds. | **You run it** (3 model calls) |
| F | Full: the director sees all four evaluations. The director decides; Supplier Co. responds. | **You run it** (3 model calls) |

`study.json` declares R and F as the two cells of one factor, `visibility` (`restricted`, `full`). The only declared difference is the director's information grant (three access rules that apply when `visibility` is `full`). Before any model call, `bvl check` and `bvl run` derive both cells, and GNDCRW checks that they differ in that grant and in nothing else (149 checks).

Where the fixed inputs come from is checked by `provenance\check_frozen_inputs.py`: it compares them with the sealed phase P and phase E packages in `results\bcp_demo\frozen_inputs_2026-10-18\` of this edition (sample guide, Preparation). The declarations of phases P and E are in `provenance\phase_p\` and `provenance\phase_e\`.

## Files

| File | Role | Read by |
|---|---|---|
| `study.json` | The study declaration (`bvl-study-1`): actors, protocol, information access, the factor `visibility`, decision rules, World, analysis | `bvl` |
| `sources\director_brief.json` | The purchasing director's situation, authority and reply format | `bvl` → model |
| `sources\deal_terms.json` | The common deal terms | `bvl` → model |
| `sources\supplier_offer.json` | Supplier Co.'s offer (from phase P) | `bvl` → model |
| `sources\eval_it.json`, `eval_finance.json`, `eval_operations.json`, `eval_procurement.json` | The four evaluations (from phase E) | `bvl` → model (director; in R only `eval_procurement`) |
| `sources\supplier_negotiator_response_brief.json` | Instructions for the sales negotiator | `bvl` → model |
| `sources\supplier_manager_response_brief.json` | Authority of the commercial manager | `bvl` → model |
| `provenance\check_frozen_inputs.py` | Checks the fixed inputs against the sealed phase P and E packages (reads only, standard library) | user |
| `provenance\phase_p\`, `provenance\phase_e\` | The declarations that produced the fixed inputs | user |
| `SAMPLE_GUIDE_EN.md` | **Sample guide**: the steps, what to look at, what it means | user |
| `EXPECTED_OUTPUTS_EN.md` | The output of each step, its meaning and its basis | user |
| `README_EN.md` | This introduction | user |

The `.json` files use LF line endings. Git is told not to change them (`.gitattributes` at the root of this edition): a changed byte changes the plan hash.

## What the sample does not show

- Each condition is run once. A difference between R and F may be chance. The two cells share the root seed, but each call carries a seed derived for its cell (`resolved_seed` in the request records), so the two director calls do not use the same seed.
- The director answers with three fields (move, price, side); the reasons for the decision are not recorded.
- The four evaluations come from one run of phase E and are shared by both conditions; variation in the evaluations is not part of this sample.
- A small open model (`qwen2.5:7b-instruct`) is used. Other models may behave differently.
- Nothing in this sample shows that AI actors behave like real buying organizations.

## Start

Follow [`SAMPLE_GUIDE_EN.md`](SAMPLE_GUIDE_EN.md) from "Preparation". The run record is in `results/bcp_demo/` of this edition.

## Licence

| Files | Licence |
|---|---|
| Sample run code: `study.json`, `sources/*.json`, `provenance/**/*.json`, `provenance/check_frozen_inputs.py` | Apache License 2.0 |
| Explanatory documents: `README_EN.md`, `SAMPLE_GUIDE_EN.md`, `EXPECTED_OUTPUTS_EN.md` | CC BY 4.0 |

Copyright holder: the BOOMVALLEY Lab authors (names withheld for anonymous review), 2026.
