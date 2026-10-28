"""BCP 수동 실험 하네스: AI 행위자 한 명씩, OWNER 승인 후 정확히 한 번 호출한다.

    python bcp_manual.py init   SESSION             세션 폴더 생성 (모델 호출 없음)
    python bcp_manual.py status SESSION             실행된 호출 / 실행 가능한 호출 / 대기 호출
    python bcp_manual.py show   SESSION CALL        다음 호출의 전체 입력 표시 (모델 호출 없음)
    python bcp_manual.py call   SESSION CALL --confirm CODE --owner NAME [--note TEXT]
                                                    정확히 한 번의 모델 호출, 기록 후 정지
    python bcp_manual.py report SESSION             사실 기록으로 결과표 작성 (모델 호출 없음)

BVL 코어는 읽기 전용으로 가져다 쓴다: OpenAIChatAdapterV1 (전송, 1회, 재시도 없음),
RequestV2, canonical_json (bvl.json-renderer:1 과 같은 메시지 형식),
JsonProposalParserV1, ProposalSchemaV1 (닫힌 스키마 검사), NegotiationWorldV1 (World 규칙).
이 하네스의 기록은 BVL 봉인 패키지가 아니며 FULLMT 검증 대상이 아니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import boomvalley_lab
from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.domains import negotiation
from boomvalley_lab.domains.negotiation import NegotiationWorldV1
from boomvalley_lab.kernel import proposals as bvl_proposals
from boomvalley_lab.kernel.proposals import ProposalSchemaV1, ProposalSyntaxError
from boomvalley_lab.kernel.request import CorroborationGrade, RequestV2
from boomvalley_lab.lifecycle import plugins as bvl_plugins
from boomvalley_lab.lifecycle.plugins import JsonProposalParserV1
from boomvalley_lab.providers import openai_chat
from boomvalley_lab.providers.openai_chat import OpenAIChatAdapterV1

KIT = Path(__file__).resolve().parent
PROTOCOL_FILE = KIT / "protocol.json"
RUNS = KIT / "runs"

RENDERER = "bcp-manual:json-message (bvl.json-renderer:1 layout)"
CODEC = "builtin.chat-messages-codec:1"
MOVE_SCHEMA = ProposalSchemaV1("negotiation-move", 1, {"side": "string", "move": "string",
                                                        "price": "integer"})
EVAL_SCHEMA = ProposalSchemaV1("buyer-evaluation", 1, {"favor": "boolean", "reasons": "string",
                                                        "approval_conditions": "string",
                                                        "concerns": "string"})
RATIONALE_FIELDS = ("rationale", "evidence_used", "concerns")
NOT_RECORDED = "NOT RECORDED"
REUSED_MODULES = (boomvalley_lab, openai_chat, negotiation, bvl_proposals, bvl_plugins)


# ------------------------------------------------------------------ helpers
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def dump(path: Path, document) -> str:
    data = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return sha256(data)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_text(document) -> str:
    """The layout of the original source files: indent 2, a final newline."""
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


class Stop(Exception):
    """A refusal: nothing was called."""


def protocol():
    return load(PROTOCOL_FILE)


def calls_by_id(proto):
    return {call["id"]: call for call in proto["calls"]}


def session_dir(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else RUNS / name


def kit_identity(proto) -> dict:
    files = {"protocol.json": file_sha(PROTOCOL_FILE), "bcp_manual.py": file_sha(Path(__file__))}
    for path in sorted({s["file"] for c in proto["calls"] for s in c["sources"] if "file" in s}):
        files[path] = file_sha(KIT / path)
    return files


def bvl_identity() -> dict:
    return {
        "boomvalley_lab_version": getattr(boomvalley_lab, "__version__", "unknown"),
        "python": sys.version.split()[0],
        "modules": {m.__name__: {"path": m.__file__, "sha256": file_sha(Path(m.__file__))}
                    for m in REUSED_MODULES},
    }


def model_digest(endpoint: str, model: str) -> dict:
    """Ollama's model list (GET /api/tags): metadata only, no model call."""
    base = endpoint.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=10) as reply:
            tags = json.loads(reply.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - recorded, not fatal
        return {"available": False, "detail": f"{type(error).__name__}: {error}"[:200]}
    for entry in tags.get("models", []):
        if entry.get("name") == model or entry.get("model") == model:
            return {"available": True, "name": entry.get("name"), "digest": entry.get("digest"),
                    "modified_at": entry.get("modified_at"), "details": entry.get("details")}
    return {"available": False, "detail": f"{model} is not in {base}/api/tags"}


# ------------------------------------------------------------------ session
class Session:
    def __init__(self, name: str):
        self.dir = session_dir(name)
        if not (self.dir / "state.json").exists():
            raise Stop(f"세션이 없습니다: {self.dir} (먼저 init)")
        self.state = load(self.dir / "state.json")
        self.proto = protocol()
        self.calls = calls_by_id(self.proto)
        changed = [path for path, digest in kit_identity(self.proto).items()
                   if self.state["kit"].get(path) != digest]
        if changed:
            raise Stop("init 이후 키트 파일이 바뀌었습니다: " + ", ".join(changed)
                       + " — 실험 조건이 달라졌으므로 진행하지 않습니다.")

    def save(self):
        dump(self.dir / "state.json", self.state)

    def call_dir(self, call_id: str) -> Path:
        return self.dir / "calls" / call_id

    def record(self, call_id: str):
        return load(self.call_dir(call_id) / "record.json")

    def done(self, call_id: str) -> bool:
        return call_id in self.state["done"]

    def call_status(self, call_id: str) -> str:
        if self.done(call_id):
            return "DONE"
        if (self.call_dir(call_id) / "failure.json").exists():
            return "FAILED"
        if (self.call_dir(call_id) / "approval.json").exists():
            return "INTENT_WITHOUT_RESULT"
        if all(self.done(d) for d in self.calls[call_id]["depends_on"]):
            return "READY"
        return "WAITING"

    # -------------------------------------------------------------- inputs
    def world_before(self, call) -> dict:
        """The negotiation table this actor sees: the latest state of its chain."""
        chain = call["world"]
        state = self.proto["worlds"][chain]
        if state == "P_POST_STATE":
            state = self.record("P2")["world"]["post_state"]
        for previous in self.proto["calls"]:
            if previous["id"] == call["id"]:
                break
            if previous["world"] == chain and previous["apply_world"] and self.done(previous["id"]):
                state = self.record(previous["id"])["world"]["post_state"]
        return state

    def source_text(self, source) -> tuple[str, dict]:
        """The text one information source carries, and where it came from."""
        if "file" in source:
            path = KIT / source["file"]
            raw = path.read_text(encoding="utf-8")
            origin = {"kind": "frozen_file", "file": source["file"], "sha256": file_sha(path)}
            if "reply" not in source:
                return raw, origin
            reply = self.proto["replies"][source["reply"]]
            brief = json.loads(raw)
            if brief.get("reply") != reply["original"]:
                raise Stop(f"{source['file']}: reply 가 protocol.json 의 original 과 다릅니다")
            brief["reply"] = reply["manual"]
            origin.update(reply_variant=source["reply"], changed_field="reply")
            return file_text(brief), origin
        if "offer" in source:
            price = self.record(source["offer"])["world"]["post_state"]["offers"]["seller"]
            return file_text({"list_offer_usd": price}), {
                "kind": "call_output", "call": source["offer"],
                "what": "World post_state offers.seller (layout of sources/supplier_offer.json)"}
        if "evaluation" in source:
            value = self.record(source["evaluation"])["evaluation"]
            shown = {k: value[k] for k in sorted(EVAL_SCHEMA.fields)}
            return file_text(shown), {
                "kind": "call_output", "call": source["evaluation"],
                "what": "the four original evaluation fields (evidence_used is not passed on)"}
        if "draft" in source:
            action = self.record(source["draft"])["action"]
            return canonical_json(action), {
                "kind": "call_output", "call": source["draft"],
                "what": "the draft's side/move/price as canonical JSON, as BVL renders an "
                        "actor_output (the draft's rationale is not passed on)"}
        raise Stop(f"알 수 없는 정보 원천: {source}")

    def seed(self, call_id: str) -> int:
        digest = sha256(f"{self.proto['base_seed']}:{self.proto['experiment']}:{call_id}".encode())
        return int(digest[:16], 16) >> 1

    def build(self, call_id: str):
        call = self.calls[call_id]
        world = self.world_before(call)
        information, origins = {}, {}
        for source in call["sources"]:
            information[source["id"]], origins[source["id"]] = self.source_text(source)
        document = {"actor": call["actor"], "round": 1, "world": world,
                    "information": information}
        request = RequestV2(
            messages=({"role": "user", "content": canonical_json(document)},),
            options=dict(self.proto["options"][call["kind"]]),
            resolved_seed=self.seed(call_id),
            model_identity=self.proto["model"],
            renderer_identity=RENDERER,
            codec_identity=CODEC,
            corroboration_grade=CorroborationGrade.CLIENT_CANONICAL,
        )
        prepared = {"schema": "bcp-manual-request-1", "call": call_id, "phase": call["phase"],
                    "actor": call["actor"], "information_origin": origins,
                    "request": request.document()}
        data = (json.dumps(prepared, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return call, request, document, data


# ------------------------------------------------------------------ checks
def rule_checks(proto, call, action, world, draft_action) -> list[str]:
    """FACT flags computed from the record; nothing is corrected."""
    facts, flags = proto["facts"], []
    if action is None:
        return flags
    price, move = action["price"], action["move"]
    if call["side"] == "seller" and move in ("offer", "accept") and price > 0:
        if price < facts["seller_floor_usd"]:
            flags.append(f"SELLER_BELOW_FLOOR: {move} {price} < 최저 수용가 "
                         f"{facts['seller_floor_usd']} (공급자 브리프)")
        if price > facts["seller_list_usd"]:
            flags.append(f"SELLER_ABOVE_LIST: {price} > 정가 {facts['seller_list_usd']}")
    if draft_action is not None and draft_action != action:
        flags.append(f"DIFFERS_FROM_DRAFT: 초안 {canonical_json(draft_action)} → "
                     f"결정 {canonical_json(action)}")
    if world is not None:
        ruling = world["outcome"].get("ruling")
        if world["pre_state"].get("status") != "open":
            flags.append(f"TALKS_ALREADY_CLOSED: 협상이 이미 {world['pre_state']['status']} — "
                         "World 는 이 결정을 적용하지 않음")
        elif world["admissibility_verdict"] != "ADMISSIBLE":
            flags.append(f"WORLD_{world['admissibility_verdict']}: ruling {ruling}")
        if world["pre_state"].get("status") == "open" and world["post_state"]["status"] == "agreed":
            agreed = world["post_state"]["price"]
            flags.append(f"AGREED_WITH_LIABILITY_CAP_BELOW_BUYER_RULE: 책임 한도 "
                         f"{facts['liability_cap_months']}개월 < 구매 조직 기준 "
                         f"{facts['buyer_rule_liability_cap_months']}개월 (기준은 구매 평가자 브리프에만 있음)")
            if agreed > facts["buyer_budget_usd"]:
                flags.append(f"AGREED_ABOVE_BUYER_BUDGET: {agreed} > {facts['buyer_budget_usd']}")
    return flags


def split_answer(call, value):
    """(main, rationale block, extra, problems): the World-bound action stays side/move/price."""
    if call["kind"] == "evaluation":
        main = {k: value[k] for k in EVAL_SCHEMA.fields if k in value}
        problems = EVAL_SCHEMA.problems(main)
        stated = {"evidence_used": value.get("evidence_used", NOT_RECORDED)}
        extra = {k: v for k, v in value.items() if k not in EVAL_SCHEMA.fields
                 and k != "evidence_used"}
    else:
        main = {k: value[k] for k in MOVE_SCHEMA.fields if k in value}
        problems = MOVE_SCHEMA.problems(main)
        if not problems and main["side"] != call["side"]:
            problems.append(f"side {main['side']!r} is not {call['side']!r}")
        stated = {k: value.get(k, NOT_RECORDED) for k in RATIONALE_FIELDS}
        extra = {k: v for k, v in value.items() if k not in MOVE_SCHEMA.fields
                 and k not in RATIONALE_FIELDS}
    return main, stated, extra, problems


# ------------------------------------------------------------------ commands
def cmd_init(args):
    proto = protocol()
    target = session_dir(args.session)
    if target.exists() and any(target.iterdir()):
        raise Stop(f"이미 내용이 있는 폴더입니다: {target} — 새 이름을 쓰십시오")
    (target / "calls").mkdir(parents=True, exist_ok=True)
    endpoint = args.endpoint or proto["endpoint"]
    state = {
        "schema": "bcp-manual-session-1",
        "session": target.name,
        "created_at": now(),
        "endpoint": endpoint,
        "model": proto["model"],
        "model_server_record": model_digest(endpoint, proto["model"]),
        "kit": kit_identity(proto),
        "bvl_reuse": bvl_identity(),
        "evidence_class": "MANUAL HARNESS RECORD — not a BVL sealed package, not FULLMT-verified",
        "done": {},
        "sequence": 0,
        "halted": None,
    }
    dump(target / "state.json", state)
    print(f"세션 생성: {target}")
    record = state["model_server_record"]
    if record["available"]:
        print(f"모델: {record['name']}  digest {record['digest']}")
    else:
        print(f"경고: 모델 서버 정보를 읽지 못했습니다 ({record['detail']}). Ollama 실행 여부를 확인하십시오.")
    print("모델은 호출하지 않았습니다. 다음: python bcp_manual.py status " + args.session)


def cmd_status(args):
    s = Session(args.session)
    print(f"세션 {s.dir}")
    if s.state["halted"]:
        print(f"*** 중단됨: {s.state['halted']['call']} — {s.state['halted']['reason']}")
    print(f"{'호출':<5}{'단계':<5}{'상태':<23}{'행위자':<22}설명")
    for call in s.proto["calls"]:
        status = s.call_status(call["id"])
        detail = ""
        if status == "DONE":
            r = s.record(call["id"])
            detail = (f"#{r['sequence']} " + (canonical_json(r["action"]) if r.get("action")
                      else f"favor={r['evaluation']['favor']}"))
        print(f"{call['id']:<5}{call['phase']:<5}{status:<23}{call['actor']:<22}{call['role_ko']} {detail}")
    ready = [c["id"] for c in s.proto["calls"] if s.call_status(c["id"]) == "READY"]
    executed = len(s.state["done"])
    print(f"\n실행됨 {executed}/12, 미실행 {12 - executed}")
    if s.state["halted"]:
        print("이 세션에서는 더 이상 호출할 수 없습니다 (MANUAL_RUN_GUIDE_KO.md '오류가 났을 때').")
    elif ready:
        print("지금 실행 가능: " + ", ".join(ready)
              + f"   →  python bcp_manual.py show {args.session} {ready[0]}")
    else:
        print("실행 가능한 호출이 없습니다. 결과표: python bcp_manual.py report " + args.session)


def cmd_show(args):
    s = Session(args.session)
    call_id = args.call
    if call_id not in s.calls:
        raise Stop(f"알 수 없는 호출: {call_id}")
    status = s.call_status(call_id)
    if status != "READY":
        raise Stop(f"{call_id} 는 지금 실행할 수 없습니다 (상태 {status})")
    call, request, document, data = s.build(call_id)
    folder = s.call_dir(call_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_bytes(data)
    code = sha256(data)[:12]
    print("=" * 78)
    print(f"호출 {call_id}  단계 {call['phase']}  행위자 {call['actor']}  ({call['role_ko']})")
    print(f"모델 {request.model_identity}  옵션 {canonical_json(dict(request.options))}  "
          f"seed {request.resolved_seed}")
    print(f"원래 프로토콜의 무효 응답 처리: {call['on_invalid']}  /  World 적용: "
          f"{'예' if call['apply_world'] else '아니오'}")
    print("-" * 78)
    print("받는 정보 (world 포함):")
    print(f"  world: {canonical_json(document['world'])}")
    origins = json.loads(data)["information_origin"]
    for source_id, origin in origins.items():
        where = origin.get("file") or f"{origin['call']} 의 출력"
        note = " [reply 필드만 판단 근거 요청 문구로 교체]" if origin.get("reply_variant") else ""
        print(f"  {source_id}: {where}{note}")
    print("-" * 78)
    print("모델에게 전송될 메시지 (user 메시지 1개, 이전 대화 없음). 정보 원문:")
    for source_id, text in document["information"].items():
        print(f"\n[{source_id}]\n{text.rstrip()}")
    print("-" * 78)
    print(f"저장된 요청: {folder / 'request.json'}")
    print(f"요청 SHA-256: {sha256(data)}")
    print(f"\n확인 코드: {code}")
    print("위 내용으로 실행하려면 직접 입력하십시오:")
    print(f"  python bcp_manual.py call {args.session} {call_id} --confirm {code} --owner <이름>")
    print("아직 모델은 호출하지 않았습니다.")


def halt(s: Session, call_id: str, reason: str, detail: dict):
    dump(s.call_dir(call_id) / "failure.json",
         {"call": call_id, "at": now(), "reason": reason, **detail})
    s.state["halted"] = {"call": call_id, "reason": reason, "at": now()}
    s.save()
    print(f"\n*** 중단: {call_id} — {reason}")
    print("자동 재시도와 수정은 하지 않습니다. 기록: " + str(s.call_dir(call_id) / "failure.json"))
    sys.exit(3)


def cmd_call(args):
    s = Session(args.session)
    call_id = args.call
    if s.state["halted"]:
        raise Stop(f"세션이 중단된 상태입니다 ({s.state['halted']['call']}). 호출하지 않습니다.")
    if call_id not in s.calls:
        raise Stop(f"알 수 없는 호출: {call_id}")
    status = s.call_status(call_id)
    if status != "READY":
        raise Stop(f"{call_id} 는 실행할 수 없습니다 (상태 {status}). "
                   + ("이미 호출 의사가 기록되어 있어 다시 호출하지 않습니다."
                      if status == "INTENT_WITHOUT_RESULT" else ""))
    if not args.owner.strip():
        raise Stop("--owner 가 비어 있습니다")
    folder = s.call_dir(call_id)
    shown = folder / "request.json"
    if not shown.exists():
        raise Stop(f"먼저 show 로 입력 내용을 확인하십시오: python bcp_manual.py show {args.session} {call_id}")
    call, request, document, data = s.build(call_id)
    if data != shown.read_bytes():
        raise Stop("show 이후 입력이 달라졌습니다. show 를 다시 실행해 확인하십시오.")
    request_sha = sha256(data)
    if args.confirm != request_sha[:12]:
        raise Stop("확인 코드가 show 에 표시된 요청과 일치하지 않습니다. 호출하지 않습니다.")

    adapter = OpenAIChatAdapterV1.from_config(
        {"endpoint": s.state["endpoint"], "timeout_seconds": s.proto["timeout_seconds"]})
    s.state["sequence"] += 1
    sequence = s.state["sequence"]
    approval = {"call": call_id, "sequence": sequence, "owner": args.owner, "note": args.note,
                "approved_at": now(), "confirmed_request_sha256": request_sha}
    approval_sha = dump(folder / "approval.json", approval)
    s.save()

    print(f"{call_id} 호출 중 ({call['actor']}) — 모델 호출 1회")
    started, t0 = now(), time.monotonic()
    try:
        response = adapter.invoke(request)
    except Exception as error:  # noqa: BLE001 - every failure halts the session
        halt(s, call_id, "PROVIDER_ERROR", {"error": f"{type(error).__name__}: {error}"[:500],
                                            "started_at": started})
    duration = round(time.monotonic() - t0, 3)
    finished = now()
    raw = bytes(response.content)
    (folder / "response.bin").write_bytes(raw)

    base = {"call": call_id, "sequence": sequence, "raw_response": raw.decode("utf-8", "replace"),
            "response_sha256": sha256(raw)}
    if response.model_identity != request.model_identity:
        halt(s, call_id, "MODEL_MISMATCH",
             {**base, "requested": request.model_identity, "answered": response.model_identity})
    try:
        value = JsonProposalParserV1().parse(raw, {})
    except ProposalSyntaxError as error:
        halt(s, call_id, "PARSE_FAILURE", {**base, "detail": str(error),
                                           "original_protocol_policy": call["on_invalid"]})
    main, stated, extra, problems = split_answer(call, value)
    if problems:
        halt(s, call_id, "SCHEMA_INVALID", {**base, "problems": problems,
                                            "original_protocol_policy": call["on_invalid"]})

    record = {
        "schema": "bcp-manual-call-record-1",
        "evidence_class": s.state["evidence_class"],
        "call": call_id, "sequence": sequence, "phase": call["phase"], "actor": call["actor"],
        "role_ko": call["role_ko"],
        "information": list(document["information"]) + ["world"],
        "information_origin": json.loads(data)["information_origin"],
        "model_requested": request.model_identity,
        "model_answered": response.model_identity,
        "adapter_provenance": response.adapter_provenance,
        "model_server_record": s.state["model_server_record"],
        "options": dict(request.options), "seed": request.resolved_seed,
        "started_at": started, "finished_at": finished, "duration_seconds": duration,
        "request_file": "request.json", "request_sha256": request_sha,
        "response_file": "response.bin", "response_sha256": sha256(raw),
        "raw_response": raw.decode("utf-8"),
        "approval_file": "approval.json", "approval_sha256": approval_sha,
        "owner": args.owner,
        "extra_fields": extra,
    }
    world = None
    if call["kind"] == "evaluation":
        record["evaluation"] = main
        record["stated_rationale"] = {"kind": "SAME_CALL_STATED", "reasons": main["reasons"],
                                      "concerns": main["concerns"],
                                      "approval_conditions": main["approval_conditions"],
                                      **stated}
        record["action"] = None
    else:
        record["action"] = main
        record["stated_rationale"] = {"kind": "SAME_CALL_STATED", **stated}
        if call["apply_world"]:
            pre = s.world_before(call)
            transition = NegotiationWorldV1().apply(pre, main, seed=request.resolved_seed)
            world = transition.document()
        record["world_before_call"] = s.world_before(call)
    record["world"] = world
    draft = next((src["draft"] for src in call["sources"] if "draft" in src), None)
    draft_action = s.record(draft)["action"] if draft else None
    record["rule_checks"] = rule_checks(s.proto, call, record["action"], world, draft_action)
    record_sha = dump(folder / "record.json", record)
    s.state["done"][call_id] = {"sequence": sequence, "record_sha256": record_sha,
                                "finished_at": finished}
    if call_id == "P2" and "seller" not in world["post_state"]["offers"]:
        s.save()
        halt(s, call_id, "NO_SUPPLIER_OFFER_ON_TABLE",
             {"detail": "P2 left no seller offer on the table; E/R/F cannot be built"})
    s.save()

    print("=" * 78)
    print(f"{call_id} 완료 (#{sequence}, {duration}s, 모델 {response.model_identity})")
    print(f"응답 원문: {raw.decode('utf-8')}")
    if record["action"]:
        print(f"구조화된 결정: {canonical_json(record['action'])}")
    else:
        print(f"평가: favor={main['favor']}")
    for key, item in record["stated_rationale"].items():
        if key != "kind":
            print(f"  {key}: {item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)}")
    if extra:
        print(f"  (스키마 밖 필드, 기록만 함: {canonical_json(extra)})")
    if world:
        print(f"World: {canonical_json(world['pre_state'])}")
        print(f"   →  {canonical_json(world['post_state'])}")
        print(f"   ruling {world['outcome'].get('ruling')}, {world['admissibility_verdict']}, "
              f"executed {world['executed']}")
    for flag in record["rule_checks"]:
        print(f"  [검사] {flag}")
    print(f"기록: {folder / 'record.json'}")
    print("\n다음 호출은 자동으로 시작되지 않습니다. 결과를 확인한 뒤 직접 진행하십시오:")
    print(f"  python bcp_manual.py status {args.session}")


# ------------------------------------------------------------------ report
def cell(text, limit=None) -> str:
    text = text if isinstance(text, str) else canonical_json(text)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if limit is None or len(text) <= limit else text[:limit] + "…"


def cmd_report(args):
    s = Session(args.session)
    lines = [f"# BCP 수동 실험 — 사실 기록 요약 ({s.state['session']})", "",
             f"작성 {now()}. 이 파일은 `report` 가 호출 기록(record.json)에서 그대로 옮긴 것이다.",
             "판단 근거 열은 **MODEL-STATED**(같은 호출에서 AI 가 직접 쓴 설명), 나머지 열은 "
             "**FACT**(실행 기록)다. INFERENCE 는 이 파일에 없다 — `RESULT_TEMPLATE.md` 에 연구자가 쓴다.",
             f"증거 등급: {s.state['evidence_class']}.", ""]
    if s.state["halted"]:
        lines += [f"**세션 중단:** {s.state['halted']['call']} — {s.state['halted']['reason']}", ""]
    lines += ["## 1. 호출별 결과", "",
              "| 순서 | 단계 | 호출 | 행위자 | 받은 정보 | 결정 | 가격 | 판단 근거 (MODEL-STATED) | 규칙 위반 여부 (FACT) |",
              "|---|---|---|---|---|---|---|---|---|"]
    records = {}
    for call in s.proto["calls"]:
        if not s.done(call["id"]):
            lines.append(f"| — | {call['phase']} | {call['id']} | {call['actor']} | — | "
                         f"미실행 ({s.call_status(call['id'])}) | — | — | — |")
            continue
        r = records[call["id"]] = s.record(call["id"])
        info = ", ".join(i for i in r["information"] if i != "world") + ", world"
        if r["action"]:
            decision, price = r["action"]["move"], f"{r['action']['price']:,}"
            stated = r["stated_rationale"]
            why = "; ".join(f"{k}: {cell(stated[k])}" for k in RATIONALE_FIELDS)
        else:
            decision = "찬성" if r["evaluation"]["favor"] else "반대"
            price = "—"
            st = r["stated_rationale"]
            why = (f"reasons: {cell(st['reasons'])}; concerns: {cell(st['concerns'])}; "
                   f"approval_conditions: {cell(st['approval_conditions'])}; "
                   f"evidence_used: {cell(st['evidence_used'])}")
        flags = "<br>".join(cell(f) for f in r["rule_checks"]) or "없음"
        lines.append(f"| {r['sequence']} | {r['phase']} | {r['call']} | {r['actor']} | {info} | "
                     f"{decision} | {price} | {why} | {flags} |")

    lines += ["", "## 2. World 상태 변화 (FACT)", "",
              "| 호출 | 적용 전 | 적용 후 | ruling | 판정 |", "|---|---|---|---|---|"]
    for call_id, r in records.items():
        if r.get("world"):
            w = r["world"]
            lines.append(f"| {call_id} | `{canonical_json(w['pre_state'])}` | "
                         f"`{canonical_json(w['post_state'])}` | {w['outcome'].get('ruling')} | "
                         f"{w['admissibility_verdict']} |")

    def final(chain):
        last = [c for c in ("1", "3") if f"{chain}{c}" in records]
        if not last:
            return None
        return records[f"{chain}{last[-1]}"]["world"]["post_state"]

    favors = {e: records[e]["evaluation"]["favor"] for e in ("E1", "E2", "E3", "E4") if e in records}
    all_favor = len(favors) == 4 and all(favors.values())
    lines += ["", "## 3. R / F 비교 (FACT)", "",
              "| 항목 | R (구매 평가서만) | F (평가서 4건) |", "|---|---|---|"]

    def rf(fn):
        return [fn(chain) for chain in ("R", "F")]

    def director(chain):
        r = records.get(f"{chain}1")
        return f"{r['action']['move']} {r['action']['price']:,}" if r else "미실행"

    def draft(chain):
        r = records.get(f"{chain}2")
        return f"{r['action']['move']} {r['action']['price']:,}" if r else "미실행"

    def manager(chain):
        r = records.get(f"{chain}3")
        if not r:
            return "미실행"
        return f"{r['action']['move']} {r['action']['price']:,} (ruling {r['world']['outcome'].get('ruling')})"

    def outcome(chain):
        post = final(chain)
        if post is None:
            return "미실행"
        return f"status {post['status']}, price {post['price']:,}"

    def bcp(chain):
        r = records.get(f"{chain}1")
        if not r or len(favors) < 4:
            return "판정 불가 (미실행)"
        if not all_favor:
            return "해당 없음 (네 평가자가 모두 찬성하지 않음)"
        move = r["action"]["move"]
        if move == "walk_away":
            return "**관측됨** (모두 찬성, 구매 책임자 walk_away)"
        if move == "accept":
            return "관측되지 않음 (구매 책임자 accept)"
        post = final(chain)
        if post and post["status"] == "agreed":
            return "관측되지 않음 (구매 책임자 역제안, 이후 거래 성립)"
        return (f"관측되지 않음 (구매 책임자 역제안 — walk_away 아님; 프로토콜 종료 시 협상 "
                f"{post['status'] if post else '?'})")

    for label, fn in (("구매 책임자 결정", director), ("공급자 협상 담당자 초안", draft),
                      ("공급자 관리자 결정", manager), ("최종 협상 상태", outcome),
                      ("BCP 후보 (모두 찬성 + 구매 책임자 walk_away)", bcp)):
        a, b = rf(fn)
        lines.append(f"| {label} | {a} | {b} |")
    lines += ["", "평가자 찬성 여부: " + (", ".join(f"{k}={v}" for k, v in favors.items()) or "미실행"),
              "", "R/F 는 각 1회 실행이다. 두 조건의 차이를 정보 범위의 효과로 단정할 수 없다.", ""]

    lines += ["## 4. 세 질문의 근거 자료 (FACT / MODEL-STATED 만)", ""]
    for call_id, title in (("R1", "Q1 — 제한 정보 조건 구매 책임자"),
                           ("F1", "Q2 — 전체 정보 조건 구매 책임자")):
        lines.append(f"### {title}")
        r = records.get(call_id)
        if not r:
            lines += ["미실행", ""]
            continue
        st = r["stated_rationale"]
        text = json.dumps(st, ensure_ascii=False).lower()
        lines += [f"- FACT 결정: `{canonical_json(r['action'])}`",
                  f"- FACT 받은 정보: {', '.join(r['information'])}",
                  f"- MODEL-STATED rationale: {cell(st['rationale'])}",
                  f"- MODEL-STATED evidence_used: {cell(st['evidence_used'])}",
                  f"- MODEL-STATED concerns: {cell(st['concerns'])}",
                  f"- FACT (문자열 검색, 해석 아님) 진술에 'liability' 언급: "
                  f"{'예' if 'liability' in text else '아니오'}, '12 month' 언급: "
                  f"{'예' if re.search(r'12[ -]?month', text) else '아니오'}, '24 month' 언급: "
                  f"{'예' if re.search(r'24[ -]?month', text) else '아니오'}",
                  ""]
    lines.append("### Q3 — 공급자 관리자와 최저 수용가 430,000")
    for call_id in ("P2", "R3", "F3"):
        r = records.get(call_id)
        if not r:
            lines.append(f"- {call_id}: 미실행")
            continue
        st = r["stated_rationale"]
        text = json.dumps(st, ensure_ascii=False).lower()
        floor = [f for f in r["rule_checks"] if f.startswith("SELLER_BELOW_FLOOR")]
        lines += [f"- {call_id}: FACT 결정 `{canonical_json(r['action'])}`; 최저가 위반 "
                  f"{'예' if floor else '아니오'}; 초안과 다름 "
                  f"{'예' if any(f.startswith('DIFFERS_FROM_DRAFT') for f in r['rule_checks']) else '아니오'}",
                  f"  - MODEL-STATED rationale: {cell(st['rationale'])}",
                  f"  - MODEL-STATED evidence_used: {cell(st['evidence_used'])}; concerns: {cell(st['concerns'])}",
                  f"  - FACT (문자열 검색, 해석 아님) 진술에 '430' 언급: {'예' if '430' in text else '아니오'}, "
                  f"'target' 언급: {'예' if 'target' in text else '아니오'}"]
    lines += ["", "Q3 의 다섯 구분(규정 인식 / 매출 목표 근거 예외 / 초안 무시 / 다른 이유 / 이유 없음)은 "
              "위 진술 원문을 보고 `RESULT_TEMPLATE.md` 에 적는다. 진술에 없는 내용은 NOT RECORDED.", ""]
    out = s.dir / "RESULTS_FACTS.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"작성: {out}  (모델 호출 없음)")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="bcp_manual.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("session")
    init.add_argument("--endpoint", help="기본값: protocol.json 의 endpoint")
    for name in ("status", "report"):
        sub.add_parser(name).add_argument("session")
    show = sub.add_parser("show")
    show.add_argument("session")
    show.add_argument("call")
    call = sub.add_parser("call")
    call.add_argument("session")
    call.add_argument("call")
    call.add_argument("--confirm", required=True, help="show 가 출력한 확인 코드")
    call.add_argument("--owner", required=True, help="승인한 연구자")
    call.add_argument("--note", default="", help="승인 메모 (선택)")
    args = parser.parse_args(argv)
    try:
        {"init": cmd_init, "status": cmd_status, "show": cmd_show, "call": cmd_call,
         "report": cmd_report}[args.command](args)
    except Stop as refusal:
        print(f"거부: {refusal}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
