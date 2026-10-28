# Expected Outputs — Buying Center Sample

What each step of [`SAMPLE_GUIDE_EN.md`](SAMPLE_GUIDE_EN.md) prints, what it means, and what the statement rests on. Values marked **fixed** follow from the input files and the component versions and are expected to be the same on any machine. Values marked **model** come from the model's answers and can differ in a new run.

Basis of the values: two runs of this sample with the same input files and component versions.

| Run | Software | Where |
|---|---|---|
| 2026-10-18 | The development copy of the same component code (`boomvalley_lab` source identical to this edition, GNDCRW 0.2.0, FULLMT 0.12.0) | The fixed inputs were produced in this run (phases P and E); its R and F packages are not part of this edition |
| 2026-10-23 | This edition, installed from source as in `INSTALL.md`, commands typed as in the sample guide | `results/bcp_demo/run_2026-10-23/` |

Both on Windows 11 with Ollama `qwen2.5:7b-instruct` (digest `845dbda0…`).

## 0. Input files — fixed

| File | SHA-256 |
|---|---|
| `study.json` | `764c1cf66440c90c19343c13313565ec97592facc67a5d99f26d42d3398da540` |
| `sources\deal_terms.json` | `949c89ff9bbd60ebbb5c0a194a122707a8b3bea62f4021a04e9add6b736e1e42` |
| `sources\director_brief.json` | `28a60a82036284beb163986ba1a64fbdc97f2dc25ab53c3ad26ec7048d76169e` |
| `sources\eval_finance.json` | `e0e6d33d14ecff3985a7d72fb2006dcf393dbcdc35cdeb07df0022ec748b43a6` |
| `sources\eval_it.json` | `e9103cb2a89430319c84669825a61445e8f88b9eb3353249e6215aec090b544b` |
| `sources\eval_operations.json` | `e97c8ab0dd351259a358f5f5aeae5cca41633e96c1d55d3fc7e31fbeb13272f7` |
| `sources\eval_procurement.json` | `0e1e4b53c89f2ac004ba9345fcd2b7b5139ee1b4838990cb99adcf64f06daaf1` |
| `sources\supplier_manager_response_brief.json` | `0ca754d674ccb08ac775dc65244ee24f49fb8de494f7938c4e7bcd81a8b2c509` |
| `sources\supplier_negotiator_response_brief.json` | `fd6246284cff688f208b7f4d7d55c70073aca0ad5c59c510bed74c12aaa9cf0c` |
| `sources\supplier_offer.json` | `da21fa9249bf03f745195012eaa9e936aa788fb37870349e00f10b0333083df6` |

`Get-FileHash` prints them in upper case.

**Provenance check** (`provenance\check_frozen_inputs.py`) — fixed: six lines `MATCH`, exit code 0. The script reads the phase P package's single World transition and the phase E package's four proposals, each only after checking its bytes against the package's `MANIFEST-4.json`, and compares them with `study.json` and `sources\`. It does not verify the packages as a whole; FULLMT does that (`results/bcp_demo/README.md`).

## 1. `bvl check` — fixed

| Cell | Output | Exit code |
|---|---|---|
| `cell.visibility-restricted` | `gate-2 CLEARED ... (plan sha256:87c9967d90058b9112dfd96d6ede83ea154ee98bd125d14fdd35ef1c70ca6ed2)`, `execution: NOT_STARTED` | 0 |
| `cell.visibility-full` | `gate-2 CLEARED ... (plan sha256:bcc45faa6a5a39cc1c190d9f1b8eff080101414088e25a2ea618d7080b694c66)`, `execution: NOT_STARTED` | 0 |
| no `--cell` | `declaration: BVL-LIFE-001 study declaration is invalid: the design has 2 cells; name one with --cell (cell.visibility-restricted, cell.visibility-full)` | 2 |

Basis: the design (`design.factors.visibility`, `design.contrasts.visibility = ["information.grant.purchasing_director"]`) gives two cells; the plan of each is computed from the declaration and the bytes of the source files. Both runs gave these plan hashes. The gate calls GNDCRW on the pair of cells (`edge.visibility.restricted-full`); `CLEARED` requires its outcome `RUN` (researcher manual, sections 2.4 and 5.4). `bvl check --json` names the GNDCRW result set and the coverage it used.

## 2. `bvl run` — status fixed, answers model

| | Condition R | Condition F |
|---|---|---|
| Output | `run bcp-minimal-demo-phase-rf.cell.visibility-restricted: COMPLETED`, `calls: 3 custody-accepted, 0 pending` | `run bcp-minimal-demo-phase-rf.cell.visibility-full: COMPLETED`, `calls: 3 custody-accepted, 0 pending` |
| Information sent to the director (fixed) | `deal_terms`, `director_brief`, `eval_procurement`, `supplier_offer`, `world` | the same and `eval_finance`, `eval_it`, `eval_operations` |
| Director (model) | `offer` 420,000 | `accept` 450,000 |
| Table after the director | `tabled`, open | `accepted`, agreed at 450,000 |
| Sales negotiator draft (model) | `offer` 440,000 | `accept` 450,000 |
| Commercial manager decision (model) | `accept` 420,000 | `accept` 450,000 |
| Table after the supplier | `accepted`, agreed at 420,000 | `closed` (the talks had ended), agreed at 450,000 |

Both runs gave these answers.

Basis of the fixed rows: the access rules of `study.json` (`eval_it`, `eval_finance` and `eval_operations` are allowed to the director only `when` `visibility` is `full`); the observation command reads them from the recorded requests (`requests-v2\`), which are what the model received. Every call is three actors in a fixed order (`protocol.nodes`): director, negotiator, manager. The supplier is called in both conditions, also when the talks are already closed; the World then rules the move `closed` and the table stays as it is.

Basis of the model rows: the parsed proposals (`PROPOSAL_PARSED`), decisions (`DECISION_RECORDED`, rule `builtin.single-authority:1`) and World transitions (`evidence-v2\world_transition\`) of each run. All six proposals were `VALID` in both runs.

**GNDCRW result in the run** — fixed: `Outcome RUN`; `EXPECTED_CHANGE, PASS` 1 (`information.grant.purchasing_director`); `INVARIANT, PASS` 148. The same result set is bound into both packages.

## 3. `bvl package` — counts fixed for these answers, identity model

| | Members | Package identity, 2026-10-23 | Package identity, 2026-10-18 |
|---|---|---|---|
| Condition R | 29 | `dc582037559a7d8499c1576e19154b6d8e79aa5a18d038011c467ab9a8472442` | the same |
| Condition F | 28 | `007c4a8771fbf0ebefdeebd1daf103535d90a54847f58a6adf7897f38d7fa66c` | `0cdfd3e2fae26c861c5f0af95a6d939106ec347982df0bccc8e69ca2a4d21f1b` |

Condition R was reproduced byte for byte: same answers, same package identity. In condition F the decisions were the same, but the sales negotiator's answer differed in layout only: `{"side":"seller","move":"accept","price":450000}` on one line on 2026-10-23, the same three fields over five lines on 2026-10-18. The raw answer is part of the record, so the call records, the manager's request (which contains the draft), and with them the package identity differ. Members per role: 3 requests, 3 responses, 3 call bindings, 3 proposals, 2 decisions, 2 World transitions, 3 (R) or 2 (F) World states, and one each of plan, gate, GNDCRW result set, coverage, execution binding, custody, conformance attestation, dataset units, analysis output and episode lineage.

The package identity (`manifest sha256:`) is computed from the content of `MANIFEST-4.json`; it is not the SHA-256 of the file's bytes.

**`bvl verify`** (optional) — fixed for these packages: `VERIFIED`, `L1`, `L2`, `World replay: REPLAYED (transitions: 2)`, `L3`, exit code 0 with `--l1 --l2 --l3 --replay-world`. The output also prints `P18 L4 conformance: NOT_L4` (the plan has no round contract) and `NOT_L5` (no human or tool actor); these are not failures unless `--l4` or `--l5` is asked for. **`bvl analyse`**: `analysis bcp-phase-rf: COMPUTED`, `decisions` `2/1`.

## 4. FULLMT — verdict fixed for a given package

`VERIFIED CONFORMANCE sha256:<identity of step 3> failed=[]`, exit code 0, for each package. The result documents (`fullmt-R.json`, `fullmt-F.json`) list the 20 rules, all `PASS`, and the 7 limitations FULLMT states about itself (among them: actor calls are not re-executed, GNDCRW is not re-run, the package is not signed, and a conformance package is not scientific evidence).

Basis: FULLMT reads only the package bytes. The same sealed folder gives the same verdict and identity on any machine. On standard error it prints `WARNING fullmt.reader: reader code identity unavailable: ... not a git repository`, because this edition is not a Git checkout; the verdict is not affected.

## What is and is not reproducible

| What | Reproducible? |
|---|---|
| Plan hashes, the gate and the GNDCRW result for the same input files | Yes, with the same component versions. |
| The information each actor receives | Yes: it is fixed by the declaration and recorded in the requests. |
| FULLMT's verdict and the package identity for the same sealed folder | Yes, on any machine. |
| The answers of the model in a new run | Not guaranteed. Temperature 0 gave the same decisions twice on one PC, and the same bytes for condition R; the layout of one answer in condition F differed. Another PC, model build or Ollama version can give other answers. |
