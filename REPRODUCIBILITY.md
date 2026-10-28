# Reproducibility Guide

How to install this edition from source and reproduce the sample study (the buying center study, `examples\bcp_demo\`): preparing the research declaration, the gate with the GNDCRW comparison, the BVL run, the evidence package and the FULLMT verification, for each of the two conditions.

```text
Prepare Research Declaration     examples\bcp_demo\study.json, sources\
            ↓
Gate with GNDCRW comparison      bvl check --experiment study.json --cell <cell>
            ↓
BVL Execution                    bvl run --experiment study.json --cell <cell> --into RUN-R | RUN-F
            ↓
Evidence Packaging               bvl package RUN-R | RUN-F
            ↓
FULLMT Verification              python <edition>\fullmt\epc_reader.py RUN-R | RUN-F --out fullmt-R.json | fullmt-F.json --quiet
```

All commands are for Windows PowerShell. The commands are the components' own command lines, as in the sample guide (`examples\bcp_demo\SAMPLE_GUIDE_EN.md`) and the researcher manual (`docs\RESEARCHER_MANUAL_EN.md`, Part 5). The values shown under "Look at" are from a run of this guide on 2026-10-23 from this edition, on Windows 11 with Python 3.14.5 and Ollama `qwen2.5:7b-instruct`.

## 0. Requirements

- Windows 10 / 11 x64, Python 3.11 or later (64-bit).
- Ollama running locally, with `qwen2.5:7b-instruct`:

```powershell
ollama pull qwen2.5:7b-instruct
ollama list
```

`ollama list` must show `qwen2.5:7b-instruct`. The sample calls the model at `http://127.0.0.1:11434/v1` (declared in `study.json`).

## 1. Install

In short (the full steps, checks and troubleshooting are in [`INSTALL.md`](INSTALL.md)):

Extract the edition to a short path without spaces, here `C:\bvl`.

```powershell
cd C:\bvl
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\gndcrw .\boomvalley-lab
.\.venv\Scripts\Activate.ps1
$BV = 'C:\bvl'
```

(`pip` fetches the `setuptools` build backend from the package index; the two packages have no other dependency. If the activation script is refused, run `Set-ExecutionPolicy -Scope Process Bypass` first.) Keep the environment active: `bvl check` and `bvl run` call `gndcrw` by name.

Check:

```powershell
gndcrw --version
python $BV\fullmt\epc_reader.py --help
```

Look at: `gndcrw 0.2.0`, and the FULLMT usage line (`fullmt-epc-verify`).

## 2. Prepare the research declaration

The declaration is already written: `study.json` (the study, `bvl-study-1`, with the factor `visibility` and its two levels) and nine fixed source files in `sources\` (the director's brief, the deal terms, the supplier's offer, the four evaluations, and the briefs of the supplier's negotiator and manager). Copy the sample to a working folder; do not run it inside the edition. If `C:\bvdemo\bcp` already exists (for example from an earlier run), use another folder name in the two commands below; otherwise the copy lands in a subfolder of the existing folder.

```powershell
New-Item -ItemType Directory -Force C:\bvdemo | Out-Null
Copy-Item -Recurse $BV\examples\bcp_demo C:\bvdemo\bcp
cd C:\bvdemo\bcp
```

Check that the files are the bytes the plan is computed from:

```powershell
Get-FileHash study.json, sources\*.json -Algorithm SHA256 | Select-Object Hash, @{n='File';e={Split-Path $_.Path -Leaf}}
```

Look at (lower case in the documents, upper case on screen): `study.json` `764c1cf66440c90c19343c13313565ec97592facc67a5d99f26d42d3398da540`; the values of the nine source files are in `examples\bcp_demo\EXPECTED_OUTPUTS_EN.md`, step 0. A different value means the file was changed, for example by an editor that converted the line endings. Copy it again.

The supplier's offer and the four evaluations are outputs of two earlier runs (phases P and E of the study), sealed and included in `results\bcp_demo\frozen_inputs_2026-10-18\`. Check that the inputs are those outputs:

```powershell
python provenance\check_frozen_inputs.py . $BV\results\bcp_demo\frozen_inputs_2026-10-18
```

Look at: six lines `MATCH`, exit code 0. To write your own declaration, see Part 2 of the researcher manual; a design with two conditions is section 4.5.

Optional: `bvl validate --experiment study.json` (manual section 5.3) validates the declaration without calling GNDCRW and prints both cells with their plan hashes (`valid: bcp-minimal-demo-phase-rf (2 design cell(s))`).

## 3. Gate with the GNDCRW comparison

```powershell
bvl check --experiment study.json --cell cell.visibility-restricted
bvl check --experiment study.json --cell cell.visibility-full
```

Look at:

```text
gate-2 CLEARED for cell.visibility-restricted (plan sha256:87c9967d90058b9112dfd96d6ede83ea154ee98bd125d14fdd35ef1c70ca6ed2)
  execution: NOT_STARTED
gate-2 CLEARED for cell.visibility-full (plan sha256:bcc45faa6a5a39cc1c190d9f1b8eff080101414088e25a2ea618d7080b694c66)
  execution: NOT_STARTED
```

Meaning: BVL derives the two cells of the factor, builds the plan of each, and calls GNDCRW on the pair. The gate is `CLEARED` only if GNDCRW returns `RUN`: the cells differ in the declared contrast, the director's information grant, and are the same in everything else (148 invariants). Anything else stops here, before any model call. Nothing is written. The GNDCRW result is bound into the run in step 4 and can be read there (sample guide, step 2).

## 4. BVL execution

```powershell
bvl run --experiment study.json --cell cell.visibility-restricted --into RUN-R
bvl run --experiment study.json --cell cell.visibility-full --into RUN-F
```

Each takes well under a minute. Look at, for each:

```text
run bcp-minimal-demo-phase-rf.cell.visibility-restricted: COMPLETED
  calls: 3 custody-accepted, 0 pending
  execution: COMPLETED
```

(`...cell.visibility-full: COMPLETED` for the second.) If a run ends `FAILED` (for example, Ollama is not running), run again into a new folder (`--into RUN-R2`); a failed run cannot be continued.

Observe who received which information and who decided what: the two commands of the sample guide, step 2. In the run of 2026-10-23 the director who saw the procurement evaluation only made a counter-offer of 420,000, which Supplier Co. accepted; the director who saw all four evaluations accepted 450,000. A real model is not guaranteed to answer the same way, so the decisions can differ. Section 5.13 of the manual shows how to read a run record.

## 5. Evidence packaging

```powershell
bvl package RUN-R
bvl package RUN-F
```

Look at:

```text
sealed CONFORMANCE package: 29 members, manifest sha256:dc582037559a7d8499c1576e19154b6d8e79aa5a18d038011c467ab9a8472442
sealed CONFORMANCE package: 28 members, manifest sha256:007c4a8771fbf0ebefdeebd1daf103535d90a54847f58a6adf7897f38d7fa66c
```

The package identity (`manifest sha256:` of `bvl package`, the value FULLMT prints) is a digest computed from the content of `MANIFEST-4.json`; it is not the SHA-256 of the file's bytes. It is the same only when a run recorded exactly the same answers, byte for byte (condition R gave `dc582037…` also on 2026-10-18; condition F gave the same decisions then, with one answer laid out differently, and the identity `0cdfd3e2…`). After sealing, do not change any file in `RUN-R` or `RUN-F`.

Optional: `bvl verify RUN-R --l1 --l2 --l3 --replay-world --experiment study.json --cell cell.visibility-restricted` (and the same for `RUN-F` with `--cell cell.visibility-full`) recomputes the package with BVL itself and replays the World (manual section 5.8; judge by the exit code, 0 = met). This one-round study is `NOT_L4` by design; do not add `--l4`.

## 6. FULLMT verification

```powershell
python $BV\fullmt\epc_reader.py RUN-R --out fullmt-R.json --quiet
python $BV\fullmt\epc_reader.py RUN-F --out fullmt-F.json --quiet
```

Look at:

```text
VERIFIED CONFORMANCE sha256:<the package identity from step 5> failed=[]
```

A `WARNING fullmt.reader: reader code identity unavailable: ... not a git repository` line on standard error can be ignored. Each result document lists the 20 rules (all `PASS`) and the 7 limitations FULLMT states about itself.

| Result | Exit code | Meaning |
|---|---|---|
| `VERIFIED` | 0 | All 20 rules passed. |
| `REJECTED` | 1 | A file changed after sealing, or the records do not agree; `failed=[...]` lists the rules. |
| `ERROR` | 2 | No verdict: the input could not be read (wrong path, or step 5 was not done). |

The sealed records of this edition can be verified the same way without running anything: `results\bcp_demo\README.md`, "Verifying this record".

## 7. What is reproducible

| What | Reproducible? |
|---|---|
| The plan hashes, the gate and the GNDCRW result for the same `study.json` and `sources\` | Expected to be the same with the same component versions (step 3). |
| The information each actor receives | Yes: fixed by the declaration and recorded in the requests. |
| The FULLMT verdict for the same sealed folder | Yes, the same verdict and package identity on any machine. |
| The World replay and the analysis recomputed from the same sealed folder | Yes (step 5 optional, FULLMT rule `M4-ANA`). |
| The model answers of a new run | Not guaranteed. On one PC, temperature 0 gave the same decisions in both conditions on 2026-10-18 and 2026-10-23. Another PC, model build or Ollama version can give other answers. |
| Phases P and E (the supplier's first offer, the four evaluations) | Not re-run in this guide; their sealed records are included and verifiable, and their declarations are in `examples\bcp_demo\provenance\`. |

The expected outputs of every step with their basis are in `examples\bcp_demo\EXPECTED_OUTPUTS_EN.md`.

## 8. Example B: manual decision-rationale experiment (S2)

Example B (`examples\bcp_s2_manual\`) is not a BOOMVALLEY Lab run: it uses a manual runner that reuses BVL components read-only, and its records are **manual harness records — not a BVL sealed package, not FULLMT verified**. Steps 3 to 6 above (gate, `bvl run`, `bvl package`, FULLMT) do not apply to it.

| What | How |
|---|---|
| Read the recorded run of 2026-10-27 | `results\bcp_s2_manual\FINAL_RESULT_EN.md`; raw answers in `results\bcp_s2_manual\S2\calls\N\` and `...\M\` (`response.bin`) |
| Check its inputs against the sealed R package | `results\bcp_s2_manual\evidence\EVIDENCE_LINKS.md`: every input SHA-256 recorded by the runner, and the file in this edition that holds it |
| Run the two steps yourself (2 model calls, each confirmed by you) | `examples\bcp_s2_manual\MANUAL_RUN_GUIDE.md`; requires the environment of step 1 and Ollama with `qwen2.5:7b-instruct` |

What is reproducible: the restored World state and the sealed supplier requests (checked byte for byte at `init`) and the model-facing request of the first step. The model answers are not guaranteed to be the same, and the second step's request depends on the first step's answer.
