"""BCP S2: 원본 BCP R 조건(2026-10-18)에서 구매자가 420,000 을 역제안한 직후 상태로
공급자 협상 담당자(N)와 공급자 관리자(M)를 한 명씩, OWNER 승인 후 정확히 한 번 호출한다.

    python bcp_s2.py init                         입력 복원·검증, 세션 생성 (모델 호출 없음)
    python bcp_s2.py status                       진행 상태
    python bcp_s2.py show N|M                     전체 입력 표시, request.json 저장 (모델 호출 없음)
    python bcp_s2.py call N|M --confirm CODE --owner NAME [--note TEXT]
                                                  정확히 한 번의 모델 호출, 기록 후 정지

기존 수동 하네스 harness/bcp_manual.py 와 harness/protocol.json 을 읽기 전용으로 가져다 쓴다
(요청 형식, 응답 형식 문구 seller_response.manual, 파싱, 스키마 검사, 규칙 검사).
BVL 코어(OpenAIChatAdapterV1, RequestV2, canonical_json, JsonProposalParserV1,
NegotiationWorldV1)도 읽기 전용으로 쓴다. 기록은 BVL 봉인 패키지가 아니며 FULLMT 검증 대상이 아니다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent
MANUAL_KIT = KIT / "harness"
sys.path.insert(0, str(MANUAL_KIT))

import bcp_manual as bm  # noqa: E402 - read-only reuse of the S1 harness
from boomvalley_lab.core.canonical import canonical_json  # noqa: E402
from boomvalley_lab.domains.negotiation import NegotiationWorldV1  # noqa: E402
from boomvalley_lab.kernel.proposals import ProposalSyntaxError  # noqa: E402
from boomvalley_lab.kernel.request import CorroborationGrade, RequestV2  # noqa: E402
from boomvalley_lab.lifecycle.plugins import JsonProposalParserV1  # noqa: E402
from boomvalley_lab.providers.openai_chat import OpenAIChatAdapterV1  # noqa: E402

SESSION = KIT / "runs" / "S2"
ORIGINAL_RUN = KIT / "inputs" / "original_R_run"
ORIGINAL_WORLD = ORIGINAL_RUN / "evidence-v2" / "world_state" / \
    "74ec4cc1dc0270380db5201f4f12ccd5f38ba82ae6b0113ffa478b7294cffe3a.json"
ORIGINAL_REQUESTS = {
    "N": ORIGINAL_RUN / "requests-v2" /
    "request-078d3acccfcf22ff10307959d8cac300daf2f6651eb15fcbb3ed185e6c10546c.json",
    "M": ORIGINAL_RUN / "requests-v2" /
    "request-c6e13f68083f532d8ba371da91875a0ee314e9623e934621221b4824a50d7b3f.json",
}
BRIEFS = {
    "N": ("supplier_negotiator_response_brief",
          MANUAL_KIT / "inputs" / "original" / "phase_rf" / "supplier_negotiator_response_brief.json"),
    "M": ("supplier_manager_response_brief",
          MANUAL_KIT / "inputs" / "original" / "phase_rf" / "supplier_manager_response_brief.json"),
}
STEPS = {
    "N": {"id": "N", "actor": "supplier_negotiator", "role_ko": "공급자 협상 담당자 (대응 초안)",
          "kind": "move", "side": "seller", "apply_world": False, "depends_on": [],
          "original_protocol_on_invalid": "NO_ACTION"},
    "M": {"id": "M", "actor": "supplier_manager", "role_ko": "공급자 관리자 (공식 대응 결정)",
          "kind": "move", "side": "seller", "apply_world": True, "depends_on": ["N"],
          "original_protocol_on_invalid": "NO_ACTION"},
}
EVIDENCE_CLASS = "MANUAL HARNESS RECORD — not a BVL sealed package, not FULLMT-verified"
Stop = bm.Stop


# ------------------------------------------------------------------ inputs
def kit_identity() -> dict:
    files = [Path(__file__), MANUAL_KIT / "bcp_manual.py", bm.PROTOCOL_FILE, ORIGINAL_WORLD,
             *ORIGINAL_REQUESTS.values(), *(path for _, path in BRIEFS.values())]
    return {str(path): bm.file_sha(path) for path in files}


def original_request(step: str) -> dict:
    return bm.load(ORIGINAL_REQUESTS[step])


def original_message(step: str) -> dict:
    return json.loads(original_request(step)["messages"][0]["content"])


def restored_world() -> dict:
    return bm.load(ORIGINAL_WORLD)["state"]


def brief_text(step: str, variant: str) -> str:
    """The frozen brief; variant 'original' keeps it, 'manual' swaps only the reply field."""
    proto = bm.protocol()
    reply = proto["replies"]["seller_response"]
    _, path = BRIEFS[step]
    raw = path.read_text(encoding="utf-8")
    brief = json.loads(raw)
    if brief.get("reply") != reply["original"]:
        raise Stop(f"{path}: reply 가 protocol.json 의 seller_response.original 과 다릅니다")
    if variant == "original":
        return raw
    brief["reply"] = reply["manual"]
    return bm.file_text(brief)


def message(step: str, variant: str, draft: dict | None) -> dict:
    key, _ = BRIEFS[step]
    information = {key: brief_text(step, variant)}
    if step == "M":
        information["supplier_draft"] = canonical_json(draft)
    return {"actor": STEPS[step]["actor"], "round": 1, "world": restored_world(),
            "information": information}


def verify_restoration() -> dict:
    """Rebuild the original R2/R3 messages from the frozen files; all checks must hold."""
    world = restored_world()
    original_draft = json.loads(original_message("M")["information"]["supplier_draft"])
    checks = {
        "world_state_file_matches_original_negotiator_request_world":
            world == original_message("N")["world"],
        "world_state_file_matches_original_manager_request_world":
            world == original_message("M")["world"],
        "world_is_after_buyer_counter_420000":
            world.get("offers") == {"buyer": 420000, "seller": 450000}
            and world.get("status") == "open" and world.get("turn") == "seller",
        "negotiator_message_rebuilt_byte_identical":
            canonical_json(message("N", "original", None))
            == original_request("N")["messages"][0]["content"],
        "manager_message_rebuilt_byte_identical_with_original_draft":
            canonical_json(message("M", "original", original_draft))
            == original_request("M")["messages"][0]["content"],
    }
    return {"checks": checks, "original_draft": original_draft}


# ------------------------------------------------------------------ session
class Session:
    def __init__(self):
        if not (SESSION / "state.json").exists():
            raise Stop(f"세션이 없습니다: {SESSION} (먼저 init)")
        self.state = bm.load(SESSION / "state.json")
        changed = [path for path, digest in kit_identity().items()
                   if self.state["kit"].get(path) != digest]
        if changed:
            raise Stop("init 이후 입력 파일이 바뀌었습니다: " + ", ".join(changed)
                       + " — 실험 조건이 달라졌으므로 진행하지 않습니다.")

    def save(self):
        bm.dump(SESSION / "state.json", self.state)

    def step_dir(self, step: str) -> Path:
        return SESSION / "calls" / step

    def record(self, step: str):
        return bm.load(self.step_dir(step) / "record.json")

    def status(self, step: str) -> str:
        if step in self.state["done"]:
            return "DONE"
        if (self.step_dir(step) / "failure.json").exists():
            return "FAILED"
        if (self.step_dir(step) / "approval.json").exists():
            return "INTENT_WITHOUT_RESULT"
        if all(d in self.state["done"] for d in STEPS[step]["depends_on"]):
            return "READY"
        return "WAITING"

    def build(self, step: str):
        proto = bm.protocol()
        draft = self.record("N")["action"] if step == "M" else None
        document = message(step, "manual", draft)
        original = original_request(step)
        request = RequestV2(
            messages=({"role": "user", "content": canonical_json(document)},),
            options=dict(proto["options"]["move"]),
            resolved_seed=original["resolved_seed"],
            model_identity=proto["model"],
            renderer_identity=bm.RENDERER,
            codec_identity=bm.CODEC,
            corroboration_grade=CorroborationGrade.CLIENT_CANONICAL,
        )
        key, path = BRIEFS[step]
        origins = {key: {"kind": "frozen_file", "file": str(path), "sha256": bm.file_sha(path),
                         "reply_variant": "seller_response", "changed_field": "reply"}}
        if step == "M":
            origins["supplier_draft"] = {
                "kind": "call_output", "call": "N",
                "what": "N 의 side/move/price 만 canonical JSON 으로 (원본 BVL actor_output 렌더링과 "
                        "같은 형식). N 의 판단 근거는 전달하지 않는다"}
        prepared = {"schema": "bcp-s2-request-1", "step": step, "actor": STEPS[step]["actor"],
                    "world_origin": {"file": str(ORIGINAL_WORLD), "sha256": bm.file_sha(ORIGINAL_WORLD)},
                    "information_origin": origins,
                    "original_request": {"file": str(ORIGINAL_REQUESTS[step]),
                                         "options": original["options"],
                                         "resolved_seed": original["resolved_seed"],
                                         "renderer_identity": original["renderer_identity"]},
                    "request": request.document()}
        data = (json.dumps(prepared, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return request, document, data


def halt(s: Session, step: str, reason: str, detail: dict):
    bm.dump(s.step_dir(step) / "failure.json", {"step": step, "at": bm.now(), "reason": reason,
                                                **detail})
    s.state["halted"] = {"step": step, "reason": reason, "at": bm.now()}
    s.save()
    print(f"\n*** 중단: {step} — {reason}")
    print("자동 재시도와 수정은 하지 않습니다. 기록: " + str(s.step_dir(step) / "failure.json"))
    sys.exit(3)


# ------------------------------------------------------------------ commands
def cmd_init(args):
    if SESSION.exists() and any(SESSION.iterdir()):
        raise Stop(f"이미 내용이 있는 폴더입니다: {SESSION} — S2 는 단일 세션입니다")
    restoration = verify_restoration()
    for name, ok in restoration["checks"].items():
        print(f"  {'OK ' if ok else 'FAIL'} {name}")
    if not all(restoration["checks"].values()):
        raise Stop("원본 상태를 정확히 복원할 수 없습니다. 세션을 만들지 않습니다.")
    proto = bm.protocol()
    (SESSION / "calls").mkdir(parents=True, exist_ok=True)
    state = {
        "schema": "bcp-s2-session-1",
        "session": "S2",
        "created_at": bm.now(),
        "endpoint": proto["endpoint"],
        "model": proto["model"],
        "model_server_record": bm.model_digest(proto["endpoint"], proto["model"]),
        "kit": kit_identity(),
        "bvl_reuse": bm.bvl_identity(),
        "restoration": restoration,
        "restored_world": restored_world(),
        "evidence_class": EVIDENCE_CLASS,
        "done": {},
        "sequence": 0,
        "halted": None,
    }
    bm.dump(SESSION / "state.json", state)
    print(f"세션 생성: {SESSION}")
    record = state["model_server_record"]
    if record["available"]:
        print(f"모델: {record['name']}  digest {record['digest']}")
    else:
        print(f"경고: 모델 서버 정보를 읽지 못했습니다 ({record['detail']}).")
    print("모델은 호출하지 않았습니다. 다음: python bcp_s2.py show N")


def cmd_status(args):
    s = Session()
    if s.state["halted"]:
        print(f"*** 중단됨: {s.state['halted']['step']} — {s.state['halted']['reason']}")
    for step, spec in STEPS.items():
        status = s.status(step)
        detail = canonical_json(s.record(step)["action"]) if status == "DONE" else ""
        print(f"{step}  {status:<22}{spec['actor']:<22}{spec['role_ko']} {detail}")


def cmd_show(args):
    s = Session()
    step = args.step
    status = s.status(step)
    if status != "READY":
        raise Stop(f"{step} 는 지금 실행할 수 없습니다 (상태 {status})")
    request, document, data = s.build(step)
    folder = s.step_dir(step)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_bytes(data)
    code = bm.sha256(data)[:12]
    spec = STEPS[step]
    print("=" * 78)
    print(f"단계 {step}  행위자 {spec['actor']}  ({spec['role_ko']})")
    print(f"모델 {request.model_identity}  옵션 {canonical_json(dict(request.options))}  "
          f"seed {request.resolved_seed} (원본 호출과 같은 seed)")
    print(f"World 적용: {'예' if spec['apply_world'] else '아니오'}")
    print("-" * 78)
    print(f"world: {canonical_json(document['world'])}")
    for source_id, text in document["information"].items():
        print(f"\n[{source_id}]\n{text.rstrip()}")
    print("-" * 78)
    print(f"저장된 요청: {folder / 'request.json'}")
    print(f"요청 SHA-256: {bm.sha256(data)}")
    print(f"\n확인 코드: {code}")
    print(f"  python bcp_s2.py call {step} --confirm {code} --owner <이름>")
    print("아직 모델은 호출하지 않았습니다.")


def cmd_call(args):
    s = Session()
    step = args.step
    if s.state["halted"]:
        raise Stop(f"세션이 중단된 상태입니다 ({s.state['halted']['step']}). 호출하지 않습니다.")
    status = s.status(step)
    if status != "READY":
        raise Stop(f"{step} 는 실행할 수 없습니다 (상태 {status}).")
    if not args.owner.strip():
        raise Stop("--owner 가 비어 있습니다")
    folder = s.step_dir(step)
    shown = folder / "request.json"
    if not shown.exists():
        raise Stop(f"먼저 show 로 입력 내용을 확인하십시오: python bcp_s2.py show {step}")
    request, document, data = s.build(step)
    if data != shown.read_bytes():
        raise Stop("show 이후 입력이 달라졌습니다. show 를 다시 실행해 확인하십시오.")
    request_sha = bm.sha256(data)
    if args.confirm != request_sha[:12]:
        raise Stop("확인 코드가 show 에 표시된 요청과 일치하지 않습니다. 호출하지 않습니다.")
    server = bm.model_digest(s.state["endpoint"], s.state["model"])
    if server.get("digest") != s.state["model_server_record"].get("digest"):
        raise Stop(f"init 이후 모델 digest 가 바뀌었습니다 ({server}). 호출하지 않습니다.")

    adapter = OpenAIChatAdapterV1.from_config(
        {"endpoint": s.state["endpoint"], "timeout_seconds": bm.protocol()["timeout_seconds"]})
    s.state["sequence"] += 1
    sequence = s.state["sequence"]
    approval = {"step": step, "sequence": sequence, "owner": args.owner, "note": args.note,
                "approved_at": bm.now(), "confirmed_request_sha256": request_sha}
    approval_sha = bm.dump(folder / "approval.json", approval)
    s.save()

    spec = STEPS[step]
    print(f"{step} 호출 중 ({spec['actor']}) — 모델 호출 1회")
    started, t0 = bm.now(), time.monotonic()
    try:
        response = adapter.invoke(request)
    except Exception as error:  # noqa: BLE001 - every failure halts the session
        halt(s, step, "PROVIDER_ERROR", {"error": f"{type(error).__name__}: {error}"[:500],
                                         "started_at": started})
    duration = round(time.monotonic() - t0, 3)
    finished = bm.now()
    raw = bytes(response.content)
    (folder / "response.bin").write_bytes(raw)
    base = {"step": step, "sequence": sequence, "raw_response": raw.decode("utf-8", "replace"),
            "response_sha256": bm.sha256(raw)}
    if response.model_identity != request.model_identity:
        halt(s, step, "MODEL_MISMATCH",
             {**base, "requested": request.model_identity, "answered": response.model_identity})
    try:
        value = JsonProposalParserV1().parse(raw, {})
    except ProposalSyntaxError as error:
        halt(s, step, "PARSE_FAILURE", {**base, "detail": str(error),
                                        "original_protocol_policy": spec["original_protocol_on_invalid"]})
    main, stated, extra, problems = bm.split_answer(spec, value)
    if problems:
        halt(s, step, "SCHEMA_INVALID", {**base, "problems": problems,
                                         "original_protocol_policy": spec["original_protocol_on_invalid"]})

    world = None
    if spec["apply_world"]:
        world = NegotiationWorldV1().apply(restored_world(), main,
                                           seed=request.resolved_seed).document()
    draft_action = s.record("N")["action"] if step == "M" else None
    record = {
        "schema": "bcp-s2-call-record-1",
        "evidence_class": EVIDENCE_CLASS,
        "step": step, "sequence": sequence, "actor": spec["actor"], "role_ko": spec["role_ko"],
        "information": list(document["information"]) + ["world"],
        "information_origin": json.loads(data)["information_origin"],
        "model_requested": request.model_identity,
        "model_answered": response.model_identity,
        "adapter_provenance": response.adapter_provenance,
        "model_server_record_at_call": server,
        "options": dict(request.options), "seed": request.resolved_seed,
        "started_at": started, "finished_at": finished, "duration_seconds": duration,
        "request_file": "request.json", "request_sha256": request_sha,
        "response_file": "response.bin", "response_sha256": bm.sha256(raw),
        "raw_response": raw.decode("utf-8"),
        "approval_file": "approval.json", "approval_sha256": approval_sha,
        "owner": args.owner,
        "action": main,
        "stated_rationale": {"kind": "SAME_CALL_STATED", **stated},
        "extra_fields": extra,
        "world_before_call": restored_world(),
        "world": world,
        "rule_checks": bm.rule_checks(bm.protocol(), spec, main, world, draft_action),
    }
    record_sha = bm.dump(folder / "record.json", record)
    s.state["done"][step] = {"sequence": sequence, "record_sha256": record_sha,
                             "finished_at": finished}
    s.save()

    print("=" * 78)
    print(f"{step} 완료 (#{sequence}, {duration}s, 모델 {response.model_identity})")
    print(f"응답 원문: {raw.decode('utf-8')}")
    print(f"구조화된 결정: {canonical_json(main)}")
    for key, item in stated.items():
        print(f"  {key}: {item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)}")
    if extra:
        print(f"  (스키마 밖 필드, 기록만 함: {canonical_json(extra)})")
    if world:
        print(f"World: {canonical_json(world['pre_state'])}")
        print(f"   →  {canonical_json(world['post_state'])}")
        print(f"   ruling {world['outcome'].get('ruling')}, {world['admissibility_verdict']}, "
              f"executed {world['executed']}")
    else:
        print("World: 적용하지 않음 (협상 담당자 초안)")
    for flag in record["rule_checks"]:
        print(f"  [검사] {flag}")
    print(f"기록: {folder / 'record.json'}")
    print("\n다음 호출은 자동으로 시작되지 않습니다.")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="bcp_s2.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    sub.add_parser("show").add_argument("step", choices=list(STEPS))
    call = sub.add_parser("call")
    call.add_argument("step", choices=list(STEPS))
    call.add_argument("--confirm", required=True, help="show 가 출력한 확인 코드")
    call.add_argument("--owner", required=True, help="승인한 연구자")
    call.add_argument("--note", default="", help="승인 메모 (선택)")
    args = parser.parse_args(argv)
    try:
        {"init": cmd_init, "status": cmd_status, "show": cmd_show, "call": cmd_call}[args.command](args)
    except Stop as refusal:
        print(f"거부: {refusal}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
