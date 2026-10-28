# Run Record of the Buying Center Sample

This folder holds the sealed evidence of the sample [`examples/bcp_demo/`](../../examples/bcp_demo/README_EN.md): the two runs a reviewer repeats with the sample guide (conditions R and F), and the two earlier runs that produced the sample's fixed inputs (phases P and E).

| Folder | What | Produced |
|---|---|---|
| `run_2026-10-23/` | Conditions R and F: `RUN-R/`, `RUN-F/` (sealed packages), `fullmt-R.json`, `fullmt-F.json` | 2026-10-23, with this edition, by typing the commands of `SAMPLE_GUIDE_EN.md` one at a time |
| `frozen_inputs_2026-10-18/` | Phases P and E: `phase_p/`, `phase_e/` (sealed packages), `fullmt-phase_p.json`, `fullmt-phase_e.json` | Runs of 2026-10-18 with the same component code; the FULLMT results were produced on 2026-10-23 with the FULLMT of this edition |

Environment of both dates: Windows 11, Ollama `qwen2.5:7b-instruct` (digest `845dbda0…`), temperature 0. The run of 2026-10-23: Python 3.14.5, BOOMVALLEY Lab `1.0.0rc3` and GNDCRW `0.2.0` installed from this edition's source (`INSTALL.md`), FULLMT `0.12.0` from `fullmt/`.

## Conditions R and F (`run_2026-10-23/`)

| Step | Condition R (`cell.visibility-restricted`) | Condition F (`cell.visibility-full`) |
|---|---|---|
| `bvl check` | `gate-2 CLEARED`, plan `sha256:87c9967d…` | `gate-2 CLEARED`, plan `sha256:bcc45faa…` |
| GNDCRW (inside the gate) | `RUN`: 1 expected change (`information.grant.purchasing_director`), 148 invariants, all `PASS` | the same result set |
| `bvl run` | `COMPLETED`, 3 calls `custody-accepted`, `0 pending` | `COMPLETED`, 3 calls `custody-accepted`, `0 pending` |
| Director | sees `eval_procurement` only; counter-offer 420,000 | sees all four evaluations; accepts 450,000 |
| Supplier Co. | negotiator drafts 440,000; manager accepts 420,000 | negotiator and manager accept; the talks had already closed (`closed`) |
| Result | agreed at 420,000 | agreed at 450,000 |
| `bvl package` | 29 members, `sha256:dc582037559a7d8499c1576e19154b6d8e79aa5a18d038011c467ab9a8472442` | 28 members, `sha256:007c4a8771fbf0ebefdeebd1daf103535d90a54847f58a6adf7897f38d7fa66c` |
| `bvl verify --l1 --l2 --l3 --replay-world` | `VERIFIED`, exit code 0 | `VERIFIED`, exit code 0 |
| FULLMT | `VERIFIED CONFORMANCE`, 20 of 20 rules `PASS` | `VERIFIED CONFORMANCE`, 20 of 20 rules `PASS` |

The Buying Center Paradox (all four evaluators in favor, yet the director walks away) was not observed in either condition. What the two runs show and what they do not: `examples/bcp_demo/SAMPLE_GUIDE_EN.md`, step 2, and `README_EN.md`, "What the sample does not show".

The same conditions were first run on 2026-10-18. Condition R gave the same package identity. Condition F gave the same decisions, but one answer differed in layout (`EXPECTED_OUTPUTS_EN.md`, step 3), so its package identity then was `sha256:0cdfd3e2…`.

## Phases P and E (`frozen_inputs_2026-10-18/`)

| | Phase P — Supplier Co.'s first offer | Phase E — four independent evaluations |
|---|---|---|
| Declaration | `examples/bcp_demo/provenance/phase_p/` | `examples/bcp_demo/provenance/phase_e/` |
| Model calls | 2 | 4 |
| What was recorded | Negotiator draft `offer` 470,000; manager's official offer 450,000; World `tabled`, table open, Buyer Co.'s turn | IT, finance, operations and procurement evaluators: all `favor: true`. The procurement evaluator noted that the liability cap (12 months) is below the company rule (24 months) and was in favor anyway, with `approval_conditions` empty |
| Package identity | `sha256:c140329ac968d8a03357a620fd535721a87b52341d2637d0cab686b4cb5b2500` | `sha256:4b3d627fd87474c4574e9a4cb2a7bbc59c601c17274b17daf66f7188843423f9` |
| FULLMT | `VERIFIED CONFORMANCE` | `VERIFIED CONFORMANCE` |

These two runs have one cell each and nothing to compare, so no GNDCRW comparison took place in them (researcher manual, section 1.6). Their outputs were copied into the sample's `sources\` and into the `initial_world_state` of its `study.json` without change; `examples/bcp_demo/provenance/check_frozen_inputs.py` checks this against the sealed packages.

## Verifying this record

From this folder, with the environment active and `$BV` set to the edition folder:

```powershell
python $BV\fullmt\epc_reader.py run_2026-10-23\RUN-R --quiet
python $BV\fullmt\epc_reader.py run_2026-10-23\RUN-F --quiet
python $BV\fullmt\epc_reader.py frozen_inputs_2026-10-18\phase_p --quiet
python $BV\fullmt\epc_reader.py frozen_inputs_2026-10-18\phase_e --quiet
```

Each prints `VERIFIED CONFORMANCE sha256:<identity above> failed=[]`. Changing any file in a package turns its verdict into `REJECTED`. The observation commands of the sample guide, step 2, also work on `run_2026-10-23\RUN-R` and `run_2026-10-23\RUN-F` (set `$RUN` to that path).

The files were copied byte for byte from the working folders of the runs; after copying, the SHA-256 of every file was compared and matched. The `.gitattributes` of this edition keeps Git from converting them.
