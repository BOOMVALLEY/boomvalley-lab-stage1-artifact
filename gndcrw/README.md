# GNDCRW

GNDCRW checks the experiment before takeoff: a pre-execution integrity gate. Given what the researcher declared (what must differ and what must stay the same between two configurations) and what was actually assembled, it decides whether the experiment may run.

```text
ExperimentDeclaration + TargetCatalog + Base/Candidate ExperimentSurface + SurfacePairContext
        -> findings (PASS / FAIL / WARNING / UNVERIFIABLE / NOT_APPLICABLE)
        -> outcome  RUN / BLOCK / UNVERIFIABLE   under GNDCRW-STRICT-0.1
```

GNDCRW never runs the experiment, never repairs it, and never claims scientific validity.

- Python package: `gndcrw` 0.2.0 (`src/gndcrw/`).
- Command: `gndcrw` (for example `gndcrw check manifest.json`), or `python -m gndcrw`.
- Runtime dependencies: none outside the Python standard library (Python 3.11 or later).

Install and use: see `../README.md` and `../REPRODUCIBILITY.md`; inputs and outcomes are explained in sections 2.5 and 5.10 of the researcher manual in `../docs/`.

Licence: Apache License 2.0 (`../LICENSE`).
