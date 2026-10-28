# FULLMT

FULLMT independently verifies an evidence package produced by BOOMVALLEY Lab. It reads only the sealed files and recomputes what it can: member hashes, the plan, episode, decision and World identities, their links, the dataset and the analysis. It is a separate program from BOOMVALLEY Lab and does not import it.

- Reader: `epc_reader.py` (version 0.12.0). It picks the reader by the package root: `MANIFEST-4.json` (the current `bvl-study-1` conformance package) or `EVIDENCE.json` (historical).
- No installation: run it with Python 3.11 or later; it uses the Python standard library only.

```text
python fullmt/epc_reader.py <package-dir> [--out result.json] [--quiet] [--locale en-US|ko-KR] [--log-level LEVEL]

exit 0 VERIFIED · 1 REJECTED · 2 ERROR
```

The usage line prints the reader's own program name (`fullmt-epc-verify`). The rules are listed in `FULLMT_EPC_READER.md` and in sections 5.11 and 6.3 of the researcher manual in `../docs/`.

Files: `epc_reader.py`, `manifest4_reader.py`, `fullmt_rules.py`, `fullmt_codes.py`, `fullmt_i18n.py`, `fullmt_log.py`, `locales/` (message catalogues, English and Korean).

Licence: Apache License 2.0 (`../LICENSE`).
