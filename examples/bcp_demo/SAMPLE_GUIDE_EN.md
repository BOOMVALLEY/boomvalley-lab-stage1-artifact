# Sample Guide — Buying Center: Restricted versus Full View of the Evaluations

Run the two conditions of the buying center study yourself, one command at a time.

- **Buyer Co.:** four evaluators (IT, finance, operations, procurement) have already assessed Supplier Co.'s offer of 450,000 USD. All four are in favor. The **purchasing director** now decides Buyer Co.'s move: accept, counter-offer or walk away.
- **Supplier Co.:** a sales negotiator drafts the response to the director's move; the commercial manager decides it.
- **Condition R (restricted):** the director sees the procurement evaluation only.
- **Condition F (full):** the director sees all four evaluations.

All actors answer with Qwen (`qwen2.5:7b-instruct`, temperature 0). The two conditions are the two cells of one study, `study.json`; they differ only in the director's access to three evaluations. Why the offer and the evaluations are fixed inputs: `README_EN.md`, "Design: the short path".

The "Example" outputs below are from a run of this guide on 2026-10-23 with this edition (Windows 11, Python 3.14.5, Ollama `qwen2.5:7b-instruct`). Its run record is in `results/bcp_demo/` of this edition. A real model is not guaranteed to answer the same way on another machine, so the decisions can differ.

## Preparation

Install the edition first (`INSTALL.md`; in short: extract to `C:\bvl`, create `.venv`, install `gndcrw` and `boomvalley-lab`). In every new PowerShell window, activate the environment and name the edition folder:

```powershell
C:\bvl\.venv\Scripts\Activate.ps1
$BV = 'C:\bvl'
```

`bvl check` and `bvl run` call GNDCRW by name, so `gndcrw` must be on the path; activating the environment does that.

Copy the sample to a working folder with a short path and go there. Do not run it inside the edition.

```powershell
New-Item -ItemType Directory -Force C:\bvdemo | Out-Null
Copy-Item -Recurse $BV\examples\bcp_demo C:\bvdemo\bcp
cd C:\bvdemo\bcp
```

If `C:\bvdemo\bcp` already exists, the copy lands in a subfolder of it; use another name or move the old folder away.

Ollama must be running. `ollama list` must show `qwen2.5:7b-instruct`.

**Check the input files** (optional). These are the bytes the plan hash in step 1 is computed from:

```powershell
Get-FileHash study.json, sources\*.json -Algorithm SHA256 | Select-Object Hash, @{n='File';e={Split-Path $_.Path -Leaf}}
```

The values are listed in `EXPECTED_OUTPUTS_EN.md`, step 0. A different value means the file was changed, for example by an editor that converted the line endings. Copy it again.

**Check where the fixed inputs come from** (optional):

```powershell
python provenance\check_frozen_inputs.py . $BV\results\bcp_demo\frozen_inputs_2026-10-18
```

Example:

```text
MATCH    study.json initial_world_state == phase_p World post_state
MATCH    sources\supplier_offer.json list_offer_usd == phase_p offers.seller
MATCH    sources\eval_it.json == phase_e proposal e_it_parse
MATCH    sources\eval_finance.json == phase_e proposal e_fin_parse
MATCH    sources\eval_operations.json == phase_e proposal e_ops_parse
MATCH    sources\eval_procurement.json == phase_e proposal e_pro_parse
supplier first offer 450000; evaluations in favor: eval_it=True, eval_finance=True, eval_operations=True, eval_procurement=True
```

**Meaning:** the supplier's offer and the four evaluations given to the director are exactly the outputs of the sealed phase P and phase E runs of 2026-10-18. To check that those two packages are intact, run FULLMT on them as in step 4 (`results\bcp_demo\README.md`).

---

## 1. BVL check — the two conditions and the GNDCRW gate

```powershell
bvl check --experiment study.json --cell cell.visibility-restricted
bvl check --experiment study.json --cell cell.visibility-full
```

**Look at:** `CLEARED` for each cell.

```text
gate-2 CLEARED for cell.visibility-restricted (plan sha256:87c9967d90058b9112dfd96d6ede83ea154ee98bd125d14fdd35ef1c70ca6ed2)
  execution: NOT_STARTED
gate-2 CLEARED for cell.visibility-full (plan sha256:bcc45faa6a5a39cc1c190d9f1b8eff080101414088e25a2ea618d7080b694c66)
  execution: NOT_STARTED
```

**Meaning:** `study.json` declares one factor, `visibility`, with two levels, so BVL derives two cells. Before any model call it builds the plan of each cell and calls GNDCRW to compare them. The gate is `CLEARED` only if GNDCRW returns `RUN`: the cells differ in the director's information grant, as declared, and in nothing else. Nothing is written and no model is called. The plan hash is computed from the declaration; with the same files and the same component versions, the same value is expected.

Without `--cell`, `bvl check` stops with `BVL-LIFE-001 ... the design has 2 cells; name one with --cell` (exit code 2).

---

## 2. BVL — run the two conditions

Condition R:

```powershell
bvl run --experiment study.json --cell cell.visibility-restricted --into RUN-R
```

**Look at:** `COMPLETED` twice, `3 custody-accepted`, `0 pending`.

```text
gate-2 CLEARED for cell.visibility-restricted (plan sha256:87c9967d90058b9112dfd96d6ede83ea154ee98bd125d14fdd35ef1c70ca6ed2)
run bcp-minimal-demo-phase-rf.cell.visibility-restricted: COMPLETED
  calls: 3 custody-accepted, 0 pending
  execution: COMPLETED
```

Condition F:

```powershell
bvl run --experiment study.json --cell cell.visibility-full --into RUN-F
```

```text
gate-2 CLEARED for cell.visibility-full (plan sha256:bcc45faa6a5a39cc1c190d9f1b8eff080101414088e25a2ea618d7080b694c66)
run bcp-minimal-demo-phase-rf.cell.visibility-full: COMPLETED
  calls: 3 custody-accepted, 0 pending
  execution: COMPLETED
```

Each run takes well under a minute. Three calls per condition: the director, the sales negotiator, the commercial manager.

### Observe the two conditions

Run the commands below one at a time. They only **read** the run folder. Set `$RUN` first; repeat with `$RUN = 'RUN-F'` for condition F.

```powershell
$RUN = 'RUN-R'
```

**Who received which information:**

```powershell
Get-Content $RUN\journal-2.jsonl -Encoding UTF8 | ConvertFrom-Json | Where-Object event -eq CALL_INTENT_RECORDED | ForEach-Object { $m = (Get-Content "$RUN\requests-v2\$($_.request.name)" -Raw -Encoding UTF8 | ConvertFrom-Json).messages[0].content | ConvertFrom-Json; [pscustomobject]@{actor = $m.actor; information = ($m.information.PSObject.Properties.Name -join ', ')} }
```

Example, condition R:

```text
actor               information
-----               -----------
purchasing_director deal_terms, director_brief, eval_procurement, supplier_offer
supplier_negotiator supplier_negotiator_response_brief
supplier_manager    supplier_draft, supplier_manager_response_brief
```

Example, condition F:

```text
actor               information
-----               -----------
purchasing_director deal_terms, director_brief, eval_finance, eval_it, eval_operations, eval_procurement, supplier_offer
supplier_negotiator supplier_negotiator_response_brief
supplier_manager    supplier_draft, supplier_manager_response_brief
```

Every actor also receives `world`, the negotiation table. This is what was actually sent to the model, read from the recorded requests.

**Who answered what, what was decided, and what happened at the table:**

```powershell
$a = ''; Get-Content $RUN\journal-2.jsonl -Encoding UTF8 | ConvertFrom-Json | ForEach-Object { $e = $_; switch ($e.event) { 'CALL_INTENT_RECORDED' { $a = ((Get-Content "$RUN\requests-v2\$($e.request.name)" -Raw -Encoding UTF8 | ConvertFrom-Json).messages[0].content | ConvertFrom-Json).actor } 'PROPOSAL_PARSED' { [pscustomobject]@{record = 'answer'; actor = $a; content = $e.proposal.value | ConvertTo-Json -Compress} } 'DECISION_RECORDED' { [pscustomobject]@{record = 'decision'; actor = $a; content = $e.decision.requested_action | ConvertTo-Json -Compress} } 'WORLD_APPLIED' { $o = (Get-Content "$RUN\$($e.evidence.transition.path)" -Raw -Encoding UTF8 | ConvertFrom-Json).transition.outcome; [pscustomobject]@{record = 'table'; actor = ''; content = "$($o.ruling), status $($o.status), price $($o.price)"} } } }
```

Example, condition R:

```text
record   actor               content
------   -----               -------
answer   purchasing_director {"move":"offer","price":420000,"side":"buyer"}
decision purchasing_director {"move":"offer","price":420000,"side":"buyer"}
table                        tabled, status open, price 0
answer   supplier_negotiator {"move":"offer","price":440000,"side":"seller"}
answer   supplier_manager    {"move":"accept","price":420000,"side":"seller"}
decision supplier_manager    {"move":"accept","price":420000,"side":"seller"}
table                        accepted, status agreed, price 420000
```

Example, condition F:

```text
record   actor               content
------   -----               -------
answer   purchasing_director {"move":"accept","price":450000,"side":"buyer"}
decision purchasing_director {"move":"accept","price":450000,"side":"buyer"}
table                        accepted, status agreed, price 450000
answer   supplier_negotiator {"move":"accept","price":450000,"side":"seller"}
answer   supplier_manager    {"move":"accept","price":450000,"side":"seller"}
decision supplier_manager    {"move":"accept","price":450000,"side":"seller"}
table                        closed, status agreed, price 450000
```

**Meaning:**

| | Condition R (procurement evaluation only) | Condition F (all four evaluations) |
|---|---|---|
| Director's official move | Counter-offer 420,000 | Accept 450,000 |
| Table after the director | Open | Agreed at 450,000 |
| Supplier's draft → manager's decision | Counter-offer 440,000 → **accept 420,000** | Accept → accept; the talks were already closed (`closed`), so it has no effect |
| Final result | Agreed at **420,000** | Agreed at **450,000** |
| BCP (all in favor, yet the director walks away) | Not observed | Not observed |

- Both directors bought; neither walked away, so the paradox did not occur in this run.
- The director who saw only the procurement evaluation (which notes that the 12-month liability cap is below the company rule of 24 months, while still being in favor) made a counter-offer; the director who saw all four accepted at once. Each condition ran once, so this difference cannot be attributed to the information scope.
- Supplier Co.'s commercial manager accepted 420,000, below the company's lowest acceptable price in its own brief (430,000), and against the negotiator's draft (440,000). The decision rule records the manager's answer as the official move; it does not enforce the brief.

**The GNDCRW check, as recorded in the run** (optional):

```powershell
$g = (Get-Content (Get-ChildItem $RUN\evidence-v2\gndcrw_results\*.json).FullName -Raw -Encoding UTF8 | ConvertFrom-Json).results[0].result
"Outcome $($g.outcome)"; $g.findings | Group-Object finding_kind, status | Select-Object Count, Name
```

Example (both conditions):

```text
Outcome RUN

Count Name
----- ----
    1 EXPECTED_CHANGE, PASS
  148 INVARIANT, PASS
```

The one expected change is `information.grant.purchasing_director`. The 148 invariants cover the actors and their model settings, the protocol, the decision rules, the proposal schemas, the World, memory, the seed and the bytes of every source file.

---

## 3. BVL — create the evidence packages

```powershell
bvl package RUN-R
bvl package RUN-F
```

**Look at:**

```text
sealed CONFORMANCE package: 29 members, manifest sha256:dc582037559a7d8499c1576e19154b6d8e79aa5a18d038011c467ab9a8472442
sealed CONFORMANCE package: 28 members, manifest sha256:007c4a8771fbf0ebefdeebd1daf103535d90a54847f58a6adf7897f38d7fa66c
```

The package identity is the same only when a run recorded exactly the same answers, byte for byte. Condition F has one World state record fewer: the supplier's move came after the talks had closed and left the table unchanged, so the state after it is the same record as the state before it.

**Meaning:** each run record (requests, answers, decisions, changes of the negotiation table, the gate and the GNDCRW result) is sealed into one `MANIFEST-4.json`. After sealing, do not change any file in `RUN-R` or `RUN-F`.

Optional: `bvl verify RUN-R --l1 --l2 --l3 --replay-world --experiment study.json --cell cell.visibility-restricted` recomputes the package with BVL itself and replays the two World transitions (researcher manual, section 5.8; judge by the exit code, 0 = met). Do not add `--l4`: this study has one round and no round contract, so it is `NOT_L4` by design and `--l4` exits with 4. `bvl analyse RUN-R` shows the pre-bound analysis (`decisions` `2/1`).

---

## 4. FULLMT — independent verification

```powershell
python $BV\fullmt\epc_reader.py RUN-R --out fullmt-R.json --quiet
python $BV\fullmt\epc_reader.py RUN-F --out fullmt-F.json --quiet
```

**Look at:**

```text
VERIFIED CONFORMANCE sha256:dc582037559a7d8499c1576e19154b6d8e79aa5a18d038011c467ab9a8472442 failed=[]
VERIFIED CONFORMANCE sha256:007c4a8771fbf0ebefdeebd1daf103535d90a54847f58a6adf7897f38d7fa66c failed=[]
```

The identity must be the one step 3 printed for the same folder. A line `WARNING fullmt.reader: reader code identity unavailable: ... not a git repository` is printed with it; it can be ignored.

**Meaning:** a program separate from BVL (FULLMT) recomputed everything from the sealed files alone: the run followed its fixed plan and protocol, the gate and the GNDCRW result are bound to it, and no file changed after sealing.

| Result | Meaning |
|---|---|
| `VERIFIED` | Passed |
| `REJECTED` | A file changed, or the records do not agree. `failed=[...]` lists the failed rules. |
| `ERROR` | The check could not be done at all. The path is wrong, or step 3 was not done. |

What `VERIFIED` does **not** guarantee:

- that the model really gave those answers
- that running again gives the same result
- that a research conclusion is right

---

## If something goes wrong

| Symptom | What to do |
|---|---|
| Step 1 says `BVL-LIFE-001 ... name one with --cell` | Add `--cell cell.visibility-restricted` or `--cell cell.visibility-full`. |
| Step 1 or 2 cannot find `gndcrw` | The environment is not active in this window. Run `C:\bvl\.venv\Scripts\Activate.ps1`. |
| Step 2 says `FAILED` | Check that Ollama is running. To try again, use a new name such as `--into RUN-R2`, and use that name in the later steps. |
| Step 2 says `BVL-LIFE-002` | The run folder already exists. Use a new name. |
| Step 4 says `REJECTED` | A file in the run folder was touched after step 3. |

The expected output of each step with its basis is in `EXPECTED_OUTPUTS_EN.md`. How to read a run record in more detail is in section 5.13 of the researcher manual.

---

Licence: this guide is under CC BY 4.0; the sample run code (`study.json`, `sources\*.json`, `provenance\`) is under the Apache License 2.0. Copyright holder: the BOOMVALLEY Lab authors (names withheld for anonymous review), 2026.
