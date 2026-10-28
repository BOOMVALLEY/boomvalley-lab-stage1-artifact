# Installation

How to install BOOMVALLEY Lab, GNDCRW and FULLMT from the source in this edition, on Windows.

| Component | How it is installed | Command after installation |
|---|---|---|
| BOOMVALLEY Lab (`boomvalley-lab/`) | `pip` package `boomvalley` 1.0.0rc3 | `bvl`, `boomvalley-lab` |
| GNDCRW (`gndcrw/`) | `pip` package `gndcrw` 0.2.0 | `gndcrw` |
| FULLMT (`fullmt/`) | not installed; a script run with the same Python | `python fullmt\epc_reader.py` |

None of the three has a runtime dependency outside the Python standard library.

**Status.** On 2026-10-23 every step of `INSTALL.md` and `REPRODUCIBILITY.md` was run from this edition, extracted from its ZIP into a new folder, as written, on Windows 11 with Python 3.14.5 and Ollama `qwen2.5:7b-instruct`: the installation, the provenance check (6 `MATCH`), `bvl check` `CLEARED` for both cells (GNDCRW `RUN`, 149 `PASS`), `bvl run` `COMPLETED` (3 calls per cell), `bvl package` (29 and 28 members), `bvl verify` `VERIFIED` (L1–L3, World replayed) and FULLMT `VERIFIED CONFORMANCE` (20 of 20 rules) for both packages.

## 1. Requirements

| Item | Requirement |
|---|---|
| Operating system | Windows 10 / 11, x64. Other operating systems were not checked. |
| Python | 3.11 or later, 64-bit, from <https://www.python.org/downloads/windows/>. The commands below use the `py` launcher that the python.org installer adds. |
| Network | Needed only during installation: `pip` fetches the `setuptools` build backend from the package index. |
| Model server (only for the sample study) | Ollama (<https://ollama.com>) with the model `qwen2.5:7b-instruct`. |

Check Python:

```powershell
py -3 --version
```

It must print `Python 3.11` or later.

## 2. Extract the edition

Extract `boomvalley-anonymous.zip` to a **short path without spaces**, for example `C:\bvl`. Run folders contain deep file names, and Windows limits a full path to 260 characters unless long paths are enabled (researcher manual, section 5.1).

```powershell
Expand-Archive .\boomvalley-anonymous.zip -DestinationPath C:\
Rename-Item C:\boomvalley-anonymous C:\bvl
cd C:\bvl
```

To check the download first, compare its SHA-256 with the published value:

```powershell
(Get-FileHash .\boomvalley-anonymous.zip -Algorithm SHA256).Hash
```

## 3. Create an environment and install

```powershell
cd C:\bvl
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\gndcrw .\boomvalley-lab
```

This installs the two packages into `C:\bvl\.venv` only; nothing else on the computer changes, and no administrator rights are needed. The commands are in `C:\bvl\.venv\Scripts\`: `bvl.exe`, `boomvalley-lab.exe`, `gndcrw.exe`.

## 4. Use the commands in a new window

Activate the environment in every new PowerShell window:

```powershell
cd C:\bvl
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the script (execution policy), allow it for this window only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

Without activation, call the commands by their full path, for example `C:\bvl\.venv\Scripts\bvl.exe`.

## 5. Check the installation

```powershell
gndcrw --version
bvl --help
python C:\bvl\fullmt\epc_reader.py --help
```

| Command | Expected |
|---|---|
| `gndcrw --version` | `gndcrw 0.2.0` |
| `bvl --help` | the usage of `bvl` with its subcommands (`validate`, `check`, `run`, `package`, `verify`, `analyse`, …) |
| `python C:\bvl\fullmt\epc_reader.py --help` | the FULLMT usage line (program name `fullmt-epc-verify`) |

## 6. Model server for the sample study

Only running the sample study needs a model; verifying the sealed records in `results\` does not. Install Ollama, then:

```powershell
ollama pull qwen2.5:7b-instruct
ollama list
```

`ollama list` must show `qwen2.5:7b-instruct`. The sample calls the model at `http://127.0.0.1:11434/v1` (declared in its `study.json`). Ollama must be running when you run the study.

## 7. Next

Run the sample study: [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md), from section 2. Write your own study: Part 2 of the researcher manual (`docs/RESEARCHER_MANUAL_EN.md`).

## 8. Uninstall

Delete the folder `C:\bvl` (with `.venv` inside it). Your study folders and run results outside it stay. Ollama and its models are removed with Ollama's own uninstaller.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `py` is not recognized | Install Python from python.org (the installer adds the `py` launcher), or use the full path of `python.exe` instead of `py -3`. |
| `pip install` cannot reach the package index | Installation needs a network connection once, for the build backend. Behind a proxy, set `pip`'s proxy option (`--proxy`). |
| `bvl` or `gndcrw` is not recognized | The environment is not active in this window: run `.\.venv\Scripts\Activate.ps1` (section 4). |
| A run fails with `No such file or directory: '...partial'` | The path of the run folder is too long. Use a shorter working folder (researcher manual, section 5.1). |

Licence: this document is under CC BY 4.0 (`LICENSE-DOCS`).
