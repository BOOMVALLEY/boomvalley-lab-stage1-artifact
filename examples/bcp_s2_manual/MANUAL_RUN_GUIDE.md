# Example B — Manual Run Guide

**Evidence class of any run made with this guide: MANUAL HARNESS RECORD — NOT A BVL SEALED PACKAGE — NOT FULLMT VERIFIED.**

This guide runs the two steps of Example B yourself. It makes **two model calls**, each only after you have read its input and typed its confirmation code. Reading the recorded result needs no run: [`results/bcp_s2_manual/`](../../results/bcp_s2_manual/README.md).

## 0. Requirements

- This edition installed as in [`INSTALL.md`](../../INSTALL.md) (the environment `.venv` with BOOMVALLEY Lab `1.0.0rc3`). The runner uses only the Python standard library and `boomvalley_lab`.
- Ollama running locally with `qwen2.5:7b-instruct` (`ollama list`). The runner calls `http://127.0.0.1:11434/v1` and reads the model digest from `http://127.0.0.1:11434/api/tags`.

All commands are for Windows PowerShell, with the environment active and `$BV` set to the edition folder (as in `REPRODUCIBILITY.md`).

## 1. Copy the example to a working folder

The runner writes its session into `runs\S2\` next to itself. Do not run it inside the edition.

```powershell
Copy-Item -Recurse $BV\examples\bcp_s2_manual C:\bvdemo\s2
cd C:\bvdemo\s2
$env:PYTHONDONTWRITEBYTECODE = 1
```

## 2. Create the session (no model call)

```powershell
python bcp_s2.py init
```

Look at: five lines `OK` (the restoration checks of `EXPERIMENT_PROTOCOL.md`, section 3), then `세션 생성: …\runs\S2` (session created) and `모델: qwen2.5:7b-instruct  digest …`. If a line reads `FAIL`, the inputs are not the sealed ones; no session is made. The digest recorded on 2026-10-27 was `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`; another digest is recorded as it is.

## 3. Step N — Supplier Negotiator

```powershell
python bcp_s2.py show N
```

This prints the full input (World, brief) and saves it as `runs\S2\calls\N\request.json`. Nothing is sent. Optionally, check that the model-facing request is the one recorded on 2026-10-27:

```powershell
python -c "import json;a=json.load(open(r'runs\S2\calls\N\request.json',encoding='utf-8'))['request'];b=json.load(open(r'$BV\results\bcp_s2_manual\S2\calls\N\request.json',encoding='utf-8'))['request'];print(a==b)"
```

Look at: `True`. Then make the call, with the code printed after `확인 코드:` (confirmation code) and your name or role:

```powershell
python bcp_s2.py call N --confirm <code> --owner <name>
```

The code is the first 12 characters of the SHA-256 of `request.json`; it depends on the folder you run in, so it differs from the recorded one. The call prints the raw answer, the parsed decision (`구조화된 결정`), the stated reasons and `World: 적용하지 않음` (not applied: a draft), then stops (`다음 호출은 자동으로 시작되지 않습니다`: the next call does not start by itself).

## 4. Step M — Supplier Manager

```powershell
python bcp_s2.py show M
python bcp_s2.py call M --confirm <code> --owner <name>
```

`show M` includes your step-N draft (`supplier_draft`). If your step N answered `offer` 440,000, as on 2026-10-27, the manager's message is the recorded one; otherwise it differs from it. The call prints the decision, the stated reasons, the World before and after with its ruling, and the rule checks (`[검사]`): `SELLER_BELOW_FLOOR` (below the lowest acceptable price), `DIFFERS_FROM_DRAFT`, `TALKS_ALREADY_CLOSED`, and the buyer-side flag `AGREED_WITH_LIABILITY_CAP_BELOW_BUYER_RULE` that is attached to every agreement.

`python bcp_s2.py status` shows the state of both steps at any time.

## 5. Runner messages

| Message | Meaning |
|---|---|
| `거부: …` | refused; nothing was called |
| `… 는 지금 실행할 수 없습니다 (상태 WAITING)` | the step cannot run yet (step M before step N) |
| `INTENT_WITHOUT_RESULT` | an approval was written but no result; the step is not run again |
| `init 이후 입력 파일이 바뀌었습니다` | an input file changed after `init`; every command is refused |
| `init 이후 모델 digest 가 바뀌었습니다` | the model digest changed after `init`; no call |
| `*** 중단: … PROVIDER_ERROR / MODEL_MISMATCH / PARSE_FAILURE / SCHEMA_INVALID` | the session halted; no retry. To try again, start from a fresh copy (step 1) and report both sessions |

## 6. What is and is not reproducible

| What | Reproducible? |
|---|---|
| The restored World state and the two sealed requests | Yes: checked byte for byte at `init` |
| The model-facing request of step N | Yes: identical to the recorded one (step 3) |
| The model-facing request of step M | Only if your step N gives the same draft |
| The answers of both steps | Not guaranteed. Temperature 0 and the recorded seeds were used, but another PC, model build or Ollama version can answer differently |
| A BOOMVALLEY Lab seal or FULLMT verification of your run | No: the runner produces manual harness records only |
| The reasons of the sealed run of Example A | No: those answers carry no reasons |
