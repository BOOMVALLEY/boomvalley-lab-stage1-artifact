# BOOMVALLEY Lab — Clean Anonymous Edition

Research software for computational organization experiments, prepared for anonymous review. This edition holds the source code of the three components, the official sample study (Example A), a follow-up manual decision-rationale example (Example B), the English researcher manual, and instructions for running them from source.

Readers new to BOOMVALLEY Lab may start with [`OVERVIEW_FOR_REVIEWERS.md`](OVERVIEW_FOR_REVIEWERS.md): the research motivation, the architecture, the worked example and its interpretation, in about three pages.

## 1. What is BOOMVALLEY Lab?

BOOMVALLEY Lab is an experiment runner. It executes, as declared, **a process in which multiple actors (AI models, people, tools) view information, make proposals and make decisions according to a fixed procedure, and those decisions change an environment (the World)**. It leaves that process behind as evidence that can be recomputed later.

The researcher does not write a program. The whole study is declared as one data file, `study.json` (format `bvl-study-1`). The declaration contains no code or module paths; it refers to registered components by name only.

## 2. Research Purpose

The software makes organization experiments with AI actors **declared, controlled and auditable**:

- **Declared:** who the actors are, what each one may see (information access is default-deny), who decides and by which rule (single, majority, plurality, veto), what the World is and how rounds and memory work — all in one file, fixed before the run.
- **Controlled:** before the run, a separate tool (GNDCRW) checks that two compared conditions differ only in what the researcher declared and are otherwise the same.
- **Auditable:** every call, response, proposal, decision, World transition and memory is recorded and sealed. A separate program (FULLMT) that shares no code with the runner verifies the sealed record from its bytes alone.

Research questions it can express include the effects of role division and decision authority, of information access rights, of replacing one actor's model, of decisions and memory across rounds, and of negotiation with a counterpart outside the organization. What it cannot do is listed in section 1.7 of the researcher manual.

## 3. Architecture

```text
Prepare research declaration   study.json, sources\*.json        (the researcher)
            ↓
GNDCRW preflight               bvl check --experiment study.json --cell <cell>   → gate CLEARED only if GNDCRW returns RUN
                               (standalone: gndcrw check manifest.json  → RUN / BLOCK / UNVERIFIABLE)
            ↓
BVL execution                  bvl run --experiment study.json --cell <cell> --into RUN   → COMPLETED
            ↓
Evidence packaging             bvl package RUN                   → RUN\MANIFEST-4.json
            ↓
FULLMT verification            python fullmt\epc_reader.py RUN   → VERIFIED / REJECTED / ERROR
```

| Stage | Tool | What it does | What it does not do |
|---|---|---|---|
| Preflight | GNDCRW 0.2.0 | Checks whether two experimental conditions differ only in what is declared and are otherwise the same. | Does not run the experiment, fix anything, or claim scientific validity. |
| Run | BVL `bvl run` | Runs a declaration that passed its gate and records requests, responses, proposals, decisions and World transitions as evidence. | Does not retry failed calls or rewrite responses. |
| Seal | BVL `bvl package` | Writes `MANIFEST-4.json`, binding every evidence file by SHA-256 and size. | Makes only `CONFORMANCE` packages, not `SCIENTIFIC` ones. |
| Independent verification | FULLMT 0.12.0 | Recomputes from the package bytes alone, without BVL code. | Does not call models again, re-run World code, or re-run GNDCRW. |

## 4. Components

| Folder | Component | Version | What it is |
|---|---|---|---|
| [`boomvalley-lab/`](boomvalley-lab/README.md) | BOOMVALLEY Lab (BVL) | release `v1.0.0`, package `boomvalley` `1.0.0rc3` | The runner and sealer. Commands `bvl` and `boomvalley-lab`. |
| [`gndcrw/`](gndcrw/README.md) | GNDCRW | `0.2.0` | The pre-execution integrity gate. Command `gndcrw`. |
| [`fullmt/`](fullmt/README.md) | FULLMT | `0.12.0` | The independent verifier of evidence packages. Script `epc_reader.py`. |
| [`examples/`](examples/) | Sample study and follow-up | — | Example A: `bcp_demo/`, the buying center study (`bvl-study-1`, two conditions). Example B: [`bcp_s2_manual/`](examples/bcp_s2_manual/README.md), a manual follow-up that restores one decision state of Example A and records each actor's stated reasons (manual harness, not a BVL run). The official examples of the development repository are not included in this edition. |
| [`docs/`](docs/) | Researcher manual | — | `RESEARCHER_MANUAL_EN.md` and its PDF edition; `RESEARCHER_MANUAL_EN_ADDENDUM_EXAMPLE_B.md` and its PDF edition. |
| [`results/`](results/bcp_demo/README.md) | Run records | — | `bcp_demo/`: the sealed evidence packages of the two conditions (run of 2026-10-23) and of the two runs that produced the sample's fixed inputs (2026-10-18), with their FULLMT results. [`bcp_s2_manual/`](results/bcp_s2_manual/README.md): the manual harness record of Example B (2026-10-27), not a sealed package. |

None of the three components has a runtime dependency outside the Python standard library.

## 5. Requirements

| Item | Requirement |
|---|---|
| Operating system | Windows 10 / 11, x64. This is the platform on which the software was run. Other operating systems were not checked. |
| Python | 3.11 or later (64-bit), from python.org or the `py` launcher. |
| Network | Only for `pip` to fetch the `setuptools` build backend when installing the two packages. Running, sealing and verifying need no network (except the model server below). |
| Model server (for the sample) | [Ollama](https://ollama.com) running locally, with the model `qwen2.5:7b-instruct` (`ollama pull qwen2.5:7b-instruct`). The sample calls `http://127.0.0.1:11434/v1`. |

## 6. Installation

The full steps, checks, uninstallation and troubleshooting are in [`INSTALL.md`](INSTALL.md). In short:

In PowerShell, from the folder that holds this README (use a short path without spaces, for example `C:\bvl`):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\gndcrw .\boomvalley-lab
```

This installs the commands `gndcrw`, `bvl` and `boomvalley-lab` into `.venv\Scripts\`. FULLMT is not installed; it runs as a script with the same Python. To call the commands by name, activate the environment in each new window:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script, use `Set-ExecutionPolicy -Scope Process Bypass` in that window first, or call the commands by their full path (`.\.venv\Scripts\bvl.exe`, `.\.venv\Scripts\gndcrw.exe`).

## 7. Quick Start

With the environment active:

```powershell
gndcrw --version
bvl --help
python .\fullmt\epc_reader.py --help
```

Then follow the sample study below. Exact commands for every step, with what to look at, are in [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md).

## 8. Sample Study: Buying Center

[`examples/bcp_demo/`](examples/bcp_demo/README_EN.md) asks whether a buying organization whose evaluators are each in favor of a purchase can still fail to buy, and whether the scope of the evaluations its decision maker can see changes what it does. Four evaluators of Buyer Co. (IT, finance, operations, procurement) have assessed Supplier Co.'s offer for an enterprise software subscription; all four are in favor. The purchasing director then accepts, counter-offers or walks away, and Supplier Co.'s negotiator and manager respond. All actors answer with `qwen2.5:7b-instruct`.

The study declares one factor with two levels: in condition R the director sees the procurement evaluation only, in condition F all four. Before any model call, BVL derives the two cells and GNDCRW checks that they differ in the director's information grant and in nothing else. The supplier's first offer and the four evaluations are fixed inputs taken from two earlier sealed runs, which are included with a script that checks the correspondence.

Copy the folder to a working folder and run, for each condition, `bvl check`, `bvl run`, `bvl package` and FULLMT. The sample guide is [`SAMPLE_GUIDE_EN.md`](examples/bcp_demo/SAMPLE_GUIDE_EN.md), and the expected outputs with their basis are in [`EXPECTED_OUTPUTS_EN.md`](examples/bcp_demo/EXPECTED_OUTPUTS_EN.md).

### Example B: restoring one decision and recording stated reasons

In condition R of the sample, Supplier Co.'s manager accepted 420,000, below the lowest acceptable price of 430,000 in its own brief and against its negotiator's draft of 440,000; the sealed answers carry no reasons. [`examples/bcp_s2_manual/`](examples/bcp_s2_manual/README.md) restores the table just after the buyer's counter-offer from the sealed R package and runs the negotiator and the manager again, one call at a time, each started by the researcher, asking in the same response for the move and its stated reasons. On 2026-10-27 the negotiator drafted `offer` 440,000 and the manager accepted 420,000, citing the deal and the quarter's sales target and not addressing the lowest acceptable price; the World admitted the acceptance and the deal was agreed at 420,000. Example B is a **manual harness record — not a BVL sealed package, not FULLMT verified**; the verification results of the sample do not extend to it. Result: [`results/bcp_s2_manual/FINAL_RESULT_EN.md`](results/bcp_s2_manual/FINAL_RESULT_EN.md).

## 9. Evidence Package

A run folder (`RUN\`) holds the event journal (`journal-2.jsonl`), the requests and responses, and the evidence files (plan, gate, coverage, call binding, proposals, decisions, World states and transitions, memory). `bvl package RUN` seals it: `RUN\MANIFEST-4.json` (schema `boomvalley-lab-manifest-4`) lists the path, role, SHA-256 and size of every member. The package identity (`manifest sha256:` of `bvl package`, the value FULLMT prints) is a digest computed from the content of `MANIFEST-4.json`; it is not the SHA-256 of the file's bytes.

`VERIFIED CONFORMANCE` means: every file is the same as when it was sealed; the run followed its fixed plan and protocol; the links between calls, proposals, decisions, World and memory match the declared dependencies; the decisions, dataset and analysis recompute to the same values; there was no hidden call. It does **not** mean that the model really answered so (models are not called again), that a new run gives the same result, that the package was signed, or that a research conclusion is right (section 6 of the researcher manual).

## 10. Reproducibility

[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) gives the commands from installation to FULLMT verification and what each step must show. Three kinds of reproduction are distinct:

- **Verification of a sealed package** (FULLMT, `bvl verify`): deterministic — the same package gives the same result on any machine.
- **Recomputation of the analysis and replay of the World** (FULLMT rule `M4-ANA`, `bvl verify --replay-world`): deterministic from the sealed record. `bvl analyse RUN` shows the analysis result recorded at sealing and recomputed at verification.
- **A new run** of the same declaration: the plan hash is the same, but a real model is not guaranteed to answer the same way, so the decisions can differ.

## 11. License

| Material | Licence |
|---|---|
| Software: `boomvalley-lab/`, `gndcrw/`, `fullmt/`, and the sample run code in `examples/` (`.json`, `.py`, `.txt`) | Apache License 2.0 — [`LICENSE`](LICENSE) |
| Documentation: `docs/` (manual and PDF), this README, `OVERVIEW_FOR_REVIEWERS.md`, `INSTALL.md`, `REPRODUCIBILITY.md`, the component READMEs, and the `.md` documents in `examples/` and `results/` | CC BY 4.0 — [`LICENSE-DOCS`](LICENSE-DOCS) |

See [`NOTICE`](NOTICE) and [`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt). The authors' names are withheld for anonymous review.

## 12. Known Limitations

- **Platform.** Running was done on Windows 11. The commands in this edition are for Windows PowerShell; other operating systems were not checked.
- **Checked from this edition.** On 2026-10-23 every step of `INSTALL.md` and `REPRODUCIBILITY.md` was run from this edition, extracted from its ZIP into a new folder, as written, on Windows 11 with Python 3.14.5 and Ollama `qwen2.5:7b-instruct`: the installation, the provenance check of the fixed inputs (6 `MATCH`), `bvl check` `CLEARED` for both cells (GNDCRW `RUN`, 149 `PASS`), `bvl run` `COMPLETED` (3 calls per cell), `bvl package` (29 and 28 members), `bvl verify` `VERIFIED` (L1–L3, World replayed) and FULLMT `VERIFIED CONFORMANCE` (20 of 20 rules) for both packages. That run is the record in `results/bcp_demo/run_2026-10-23/`; an earlier run on the same day from the source folder gave the same package identities. The checks reported in the manual (2026-10-16/17) used the Windows Toolkit installation of the same source (sections 0.2 and 4.6 of the manual). Python 3.11 to 3.13 were not checked from this edition.
- **The manual describes the Windows Toolkit installation.** It was written for the Windows installer, which is not part of this edition. Its path abbreviations correspond to this edition as follows: `PKG` → `boomvalley-lab\src\boomvalley_lab`, `GND` → `gndcrw\src\gndcrw`, `EX` → `examples` (only `bcp_demo` is included; the `EX\...` examples the manual cites, such as `EX\k0_study`, `EX\conformance` or `EX\bvl_input_v2`, are not, nor is the negotiation demo `manual_negotiation_demo` that the manual uses as its worked example in sections 2.5.9, 4.6 and 5.13; see manual section 0.1), `FMT\app\` → `fullmt\`, `FMT\docs\` → `fullmt\`. The Toolkit command `bvt` (version report, `bvt gndcrw-digest`) is not included; the manual's section 2.5.9 also gives the Python one-liners that compute the GNDCRW digests (use `.venv\Scripts\python.exe` for `%GPY%`). References to repository paths outside this edition (for example `artifacts\...`, `packaging\...`) point to the development repository, which is not part of this edition.
- **The sample's example outputs** are from one run of each condition on 2026-10-23 with this edition. Its run record is in `results/bcp_demo/` (the sealed packages, which FULLMT verifies as `VERIFIED CONFORMANCE`, and the FULLMT result documents).
- **The sample runs the last two phases of a four-phase study.** The supplier's first offer and the four evaluations are fixed inputs from sealed runs of 2026-10-18 (`results/bcp_demo/frozen_inputs_2026-10-18/`); a reviewer does not re-run those phases. Their declarations are in `examples/bcp_demo/provenance/`.
- **Example B is a manual harness record.** It was produced by `examples/bcp_s2_manual/bcp_s2.py`, which reuses BVL components read-only but does not run through `bvl run`, the gate, `bvl package` or FULLMT. Its reply instruction (with reasons) and `max_tokens` (512) differ from the sealed run; each of its two steps ran once. Local paths in its records are replaced by placeholders, which changes the hashes of five of its record files; `results/bcp_s2_manual/evidence/` gives the original and distributed hashes.
- **The FULLMT result names the producer contract it was frozen against** (`verifier.producer_contract` in the FULLMT result documents, a constant in `fullmt\manifest4_reader.py`). It is provenance only and is never executed. In this edition its `repository` value is `boomvalley-lab`, without the owner of the development repository; this one line is the only change to the code of the three components.
- **Code identity.** BVL and FULLMT record the git commit of their own source when they run from a git checkout. Outside a checkout they record it as unknown, and FULLMT prints a `WARNING ... not a git repository` line; the result is unaffected.
- **No signing.** Evidence packages are not signed (`NOT_SIGNED`), and only `CONFORMANCE` packages can be made.
- **Messages in Korean.** BVL, GNDCRW and FULLMT carry message catalogues in English and Korean (`i18n.py`, `fullmt\locales\`). English is the default.
