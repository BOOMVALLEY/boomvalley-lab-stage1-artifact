# Package Manifest — BOOMVALLEY Lab, Anonymous Stage-1 Edition

Assembled 2026-10-27 from the clean anonymous edition of 2026-10-23, with Example B added. No model was called and no experiment was run to assemble it.

## 1. Files

**457 files** in total, including this manifest and `SHA256SUMS.txt` (the SHA-256 of every other file, as `<hash> *<path>`).

| Part | Files | What |
|---|---:|---|
| Root documents | 11 | `README.md`, `OVERVIEW_FOR_REVIEWERS.md`, `INSTALL.md`, `REPRODUCIBILITY.md`, `LICENSE`, `LICENSE-DOCS`, `NOTICE`, `THIRD_PARTY_NOTICES.txt`, `.gitattributes`, `PACKAGE_MANIFEST.md`, `SHA256SUMS.txt` |
| `boomvalley-lab/` | 182 | BOOMVALLEY Lab (BVL) source, package `boomvalley` `1.0.0rc3` |
| `gndcrw/` | 29 | GNDCRW `0.2.0` source |
| `fullmt/` | 10 | FULLMT `0.12.0` |
| `docs/` | 4 | `RESEARCHER_MANUAL_EN.md` / `.pdf` (89 pages); `RESEARCHER_MANUAL_EN_ADDENDUM_EXAMPLE_B.md` / `.pdf` |
| `examples/bcp_demo/` | 24 | **Example A** — the buying center study (`bvl-study-1`, conditions R and F) |
| `examples/bcp_s2_manual/` | 11 | **Example B** — the S2 manual decision-rationale experiment: runner, reused harness, inputs, protocol, run guide |
| `results/bcp_demo/` | 118 | Example A sealed evidence: R and F (2026-10-23), P and E (2026-10-18), FULLMT result documents |
| `results/bcp_s2_manual/` | 68 | Example B record: English result and comparison, S2 call records (9), evidence links and anonymization manifest (3), original Korean records (2), S1 reference record (51) |

## 2. Inclusion

| Item | Included | Evidence class |
|---|---|---|
| BVL, GNDCRW, FULLMT source | yes, unchanged from the 2026-10-23 edition | — |
| Example A (original BCP experiment: P, E, R, F) | yes, unchanged | BVL sealed packages; `bvl verify` `VERIFIED`; FULLMT `VERIFIED CONFORMANCE` (20/20) for R, F, P, E — re-checked in this edition on 2026-10-27 |
| Example B (S2) | yes, new | **MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED** |
| S1 manual session | as reference record only (`results/bcp_s2_manual/reference_S1/`) | MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED |
| Sealed R and F packages of 2026-10-18 | no (not kept; R had the same package identity as the included R of 2026-10-23) | — |
| Stage-1 proposal document | no | — |

## 3. Changes from the 2026-10-23 edition

| Change | Files |
|---|---|
| Example B added | `examples/bcp_s2_manual/`, `results/bcp_s2_manual/`, `docs/RESEARCHER_MANUAL_EN_ADDENDUM_EXAMPLE_B.md`, `.pdf` |
| Example B described | `README.md` (components table, section 8, known limitations), `OVERVIEW_FOR_REVIEWERS.md` (section 4.1, sections 6 and 7), `REPRODUCIBILITY.md` (section 8), `docs/RESEARCHER_MANUAL_EN.md` (one sentence in section 0.1) |
| Byte-conversion guard for Example B inputs | `.gitattributes` |
| Compiled caches removed | `fullmt/__pycache__/` (5 `.pyc` files, build products that embed local paths) |
| This manifest | `PACKAGE_MANIFEST.md`, `SHA256SUMS.txt` |

No file of `boomvalley-lab/`, `gndcrw/`, `fullmt/` (other than the removed caches), `examples/bcp_demo/` or `results/bcp_demo/` was changed. The PDF edition of the manual is unchanged; the edition note in its section 0.1 predates Example B, and the addendum applies there.

## 4. Anonymization

- Authors' names, e-mail addresses, development-repository owner and URLs, institutional names and the Windows account name do not occur in the files, the PDF metadata or the PDF content streams (scan of 2026-10-27). `github.com/notofonts` in `THIRD_PARTY_NOTICES.txt` is a third-party font project; "Corporation" in `LICENSE-DOCS` is part of the licence text.
- The folders `C:\bvl` and `C:\bvdemo\...` in the installation and run guides are instruction examples, as in the 2026-10-23 edition.
- Local absolute paths in the Example B and S1 records are replaced by placeholders; the original and distributed SHA-256 of every such file are in `results/bcp_s2_manual/evidence/ANONYMIZATION_MANIFEST.json`, explained in `results/bcp_s2_manual/evidence/EVIDENCE_LINKS.md`. Model responses, approvals and sealed evidence are byte-identical to the originals.
- The approvals of Example B and S1 record the approver as `OWNER`.
