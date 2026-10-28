"""Locale-aware presentation of human-readable messages.

The renderer asks for `message_key + params`; this module turns them into text.
CLI syntax, JSON members, status / reason / error codes (`core.codes`) and every
machine-readable value stay English and locale-independent: `--json` output is
the same bytes in every locale. A missing or broken translation falls back to
en-US and then to the bare key, so presentation can never change a verdict, a
status or an exit code.

Locale precedence (first set wins): explicit `--locale` > config > the
BVL_LOCALE environment variable > en-US. BVL has no config file today; the
`config` slot is kept so a future one slots in without a new rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = ("en-US", "ko-KR")
LOCALE_ENV = "BVL_LOCALE"

#: en-US is the reference catalog: its wording is the CLI's historical wording.
EN_US: dict[str, str] = {
    # CLI error headers (stderr, human mode)
    "error.header": "{category}: {message}",
    "error.evidence": "  evidence: {evidence}",
    "error.problem": "  - {problem}",
    "error.os": "execution: {error}",
    "error.os_declaration": "declaration: {error}",
    "error.internal": "unexpected {exc_type}",
    "usage.locale_value": "--locale {value!r}: expected one of {supported}",
    # validate / check
    "render.validated": "valid: {experiment} ({records} execution records)",
    "render.checked": "checked: {experiment} ({records} execution records)",
    "render.written": "written: {output}",
    # run / resume / status
    "render.released": "released: {released}",
    "render.recovered": "recovered: {record} ({origin})",
    "render.progress": "executed {executed}, skipped {skipped}, remaining {remaining}",
    "render.run_state": "run {run}: {state}",
    "render.active_session": "  active session: {session}   sessions: {sessions}",
    "render.none": "none",
    "render.scheduled": "  {scheduled} scheduled: {counts}",
    "render.decisions": "  decisions: {decisions}",
    "render.custody": "  custody: {entries} entries (FRESH {fresh}, RECOVERED {recovered})",
    "render.resume_permitted": "  resume permitted: {permitted}",
    "render.blocking": "    - {reason}",
    "render.operator_decision": "    operator decision required: {record}",
    # the gated lifecycle (T1-010)
    "render.gated_valid": "valid: {experiment} ({cells} design cell(s))",
    "render.gated_cell": "  {cell}: plan {plan}",
    "render.gated_gate": "gate-2 {decision} for {cell} (plan {plan})",
    "render.gated_run": "run {run}: {state}",
    "render.gated_calls": "  calls: {accepted} custody-accepted, {pending} pending",
    "render.gated_resume": "  resume: {action}",
    "render.gated_package": "sealed {package_class} package: {members} members, "
                            "manifest {manifest}",
    "render.gated_analysis": "analysis {analysis}: {status}",
    "render.gated_l1": "P18 L1 conformance: {level} (hidden calls: {hidden})",
    "render.gated_l2": "P18 L2 conformance: {level} (actor-to-actor hand-overs: {edges})",
    "render.gated_world_replay": "World replay: {verdict} (transitions: {transitions})",
    "render.gated_l3": "P18 L3 conformance: {level} (decision-to-World transitions: "
                       "{transitions})",
    "render.gated_l4": "P18 L4 conformance: {level} (rounds closed: {rounds}, memory "
                       "artifacts: {memory})",
    "render.gated_call_provenance": "Call provenance: {verdict} (hidden calls: {hidden}; model "
                                    "{model}, human {human}, tool {tool})",
    "render.gated_l5": "P18 L5 conformance: {level} (human exchanges closed: {humans}, tool "
                       "calls resolved: {tools})",
    "render.gated_l5_arguments": "  limitation: {rederived} of {declared} tool arguments were "
                                 "re-derived from their declared selection (frozen sources "
                                 "not handed to the verifier are not recomputed)",
    # experiment input
    "render.contract_identity": "  ContractIdentity: {value}",
    "render.eii": "  ExperimentInputIdentity: {value}",
    "render.input_digest": "  input.json: {value}",
    "render.preflight_tool": "    gndcrw {version}  manifest {manifest}  result {result}",
    "render.limitations_indented": "    limitations: {limitations}",
    "render.input_lock": "  input lock: {classification}{verification}{code}",
    # audit / analyse
    "render.audit_head": "{eligibility}  run {run}",
    "render.dataset": "  dataset {identity} ({records} records)",
    "render.analysed": "analysed {records} records of dataset {dataset}",
    "render.analysis": "  analysis: {plugin} {version}",
    "render.analysis_result": "  result: {result}",
    # package / verify (EPC)
    "render.epc_package": "EPC package {run}: {members} members (input lock: {input_lock})",
    "render.package_identity": "  package_identity: {value}",
    "render.evidence_root": "  evidence_root:    {value}",
    "render.identity": "  {kind}: {digest}",
    "render.self_check": "  producer self-check: {value}",
    "render.limitations": "  limitations: {limitations}",
    "render.verified": "VERIFIED",
    "render.refused": "REFUSED",
    # package / verify (legacy)
    "render.package": "package {run}: {members} members",
    "render.package_dataset": "  dataset: {identity}",
    "render.analysis_outputs": "  analysis outputs: {count}",
    "render.recomputed_dataset": "  recomputed dataset: {value}",
    "render.recomputed_eligibility": "  recomputed eligibility: {value}",
    # execution gate (#81): status, reasons, evidence, execution status
    "render.gate": "  execution gate: {status} - {message}",
    "render.gate_reason": "    - [{rule_id}] {reason_code}: {message}",
    "render.gate_evidence": "      evidence: {evidence}",
    "render.execution_status": "  execution: {status}",
    "render.human_waiting": "  waiting for {actor} ({participant}): intent {intent} on desk "
                            "{desk}",
    "render.human_enrolled": "enrolled {participant} as {actor} (consent {consent})",
    "render.human_pending": "desk {desk}: {pending} pending of {delivered} delivered",
    "render.human_request": "  {actor} ({participant}) intent {intent}",
    "render.human_message": "    {role}: {content}",
    "render.human_answered": "answered intent {intent} for {actor} ({participant})",
    "render.gate_record": "  gate record: {path}",
    "render.gate_record_verified": "{verification}  {record} (execution gate: {status}, "
                                   "execution: {execution})",
    "gate.status.CLEARED": "pre-execution gate cleared; execution may start",
    "gate.status.MANDATORY_REQUIREMENT_NOT_MET": "a mandatory research / protocol / contract "
                                                 "requirement is not met; the experiment MUST "
                                                 "NOT execute",
    "gate.status.EXECUTION_NOT_POSSIBLE": "this installation cannot execute the experiment "
                                          "(a required runtime capability is unavailable)",
    "gate.status.NOT_EVALUATED": "the execution gate was not evaluated",
    "gate.reason.GNDCRW_PREFLIGHT_NOT_CLEARED": "the GNDCRW preflight outcome is {outcome}, "
                                                "the attachment requires {required_outcome} "
                                                "(findings: {findings})",
    "gate.reason.REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE": "the {capability} {implementation} "
                                                           "is unavailable here: {detail} "
                                                           "(missing: {missing})",
    "gate.reason.VALIDATION_ONLY": "validate does not evaluate the gate; run 'bvl check'",
    "gate.reason.EXECUTION_PROFILE_ABSENT": "the experiment input has no execution profile",
    "gate.reason.LEGACY_RUN_NOT_GATED": "a legacy (NOT_INPUT_LOCKED) run was never gated",
    "gate.reason.EXECUTION_GATE_NOT_RECORDED": "the evidence records no gate decision",
    # #153 schedule preflight (codes stay English; only this wording is localized)
    "error.schedule_preflight": "  schedule preflight: {status} - {message}",
    "render.schedule_preflight": "  schedule preflight: {status} - {message}",
    "schedule_preflight.status.EXACT_MATCH": "the frozen schedule matches exactly ({length} "
                                             "records); execution may start",
    "schedule_preflight.status.NOT_REQUESTED": "no expected schedule was given",
    "schedule_preflight.SCHEDULE_PREFLIGHT_ORDER_MISMATCH": "order differs at position "
                                                           "{position}: expected {expected}, "
                                                           "locked {actual}; nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_LENGTH_MISMATCH": "expected {expected} records, the "
                                                            "locked schedule has {actual}; "
                                                            "nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_IDENTITY_MISMATCH": "the schedule identity does not "
                                                              "bind (locked {locked}, "
                                                              "recomputed {recomputed}, stated "
                                                              "{stated}); nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_PATH_ERROR": "the expected schedule cannot be read "
                                                       "({path}: {error}); nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_PARSE_ERROR": "the expected schedule cannot be "
                                                        "parsed ({problem}); nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_COMPARATOR_FAILED": "the schedule comparison failed "
                                                              "({error}); nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_SCHEDULE_MISSING": "no frozen schedule on the "
                                                             "{side} side ({problem}); nothing "
                                                             "started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_UNVERIFIABLE": "the comparison cannot be judged "
                                                         "({problem}); nothing started",
    "schedule_preflight.SCHEDULE_PREFLIGHT_BINDING_MISMATCH": "the opened run is not the gated "
                                                             "schedule (gated {gated}, opened "
                                                             "{opened}); nothing executed",
    # #175 experiment-input preflight (codes stay English; only this wording is localized)
    "error.experiment_input_preflight": "  experiment input preflight: {status} - {message}",
    "render.experiment_input_preflight": "  experiment input preflight: {status} - {message}",
    "experiment_input_preflight.status.EXACT_MATCH": "the frozen experiment input matches "
                                                     "exactly ({identity}); execution may start",
    "experiment_input_preflight.status.NOT_REQUESTED": "no expected experiment input was given",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_IDENTITY_MISMATCH":
        "the experiment input is not the frozen one (expected {expected}, actual {actual}); "
        "nothing started",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_PATH_ERROR":
        "the expected experiment input cannot be read ({path}: {error}); nothing started",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_PARSE_ERROR":
        "the expected experiment input cannot be parsed ({path}: {problem}); nothing started",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_UNVERIFIABLE":
        "the actual experiment input identity cannot be computed ({problem}); nothing started",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_BINDING_MISMATCH":
        "the opened run is not the gated experiment input (gated {gated}, opened {opened}); "
        "nothing executed",
    # request content (#84): AVAILABLE / WITHHELD / UNAVAILABLE, never the content itself
    "render.request_content": "  request content: {status} - {message}",
    "render.request_content_reason": "    - {reason_code}: {message}",
    "request_content.status.AVAILABLE": "the exact request bytes are in the package",
    "request_content.status.WITHHELD": "the request bytes exist and are deliberately not "
                                       "published; their digest and size are bound",
    "request_content.status.UNAVAILABLE": "the request bytes were not retained or cannot be "
                                          "recovered",
    "request_content.reason.REQUEST_WITHHELD_CONFIDENTIAL": "confidential research input",
    "request_content.reason.REQUEST_WITHHELD_PERSONAL_DATA": "contains personal data",
    "request_content.reason.REQUEST_WITHHELD_LICENSE_RESTRICTED": "publication is restricted "
                                                                  "by license",
    "request_content.reason.REQUEST_BUILDER_NOT_RECORDED": "the run never recorded its "
                                                           "request builder (legacy run)",
    # producer provenance (#87): the two trust classes, never merged
    "render.provenance_verified": "  verified provenance (recomputed from the package): "
                                  "{fields}",
    "render.provenance_self_reported": "  self-reported provenance (stated by the producer, "
                                       "an adapter or a tool; not independently verified): "
                                       "{fields}",
    "render.provenance_unclassified": "  provenance ({schema}): not trust-classified; every "
                                      "item is read as self-reported",
}

KO_KR: dict[str, str] = {
    "error.header": "{category}: {message}",
    "error.evidence": "  증거: {evidence}",
    "error.problem": "  - {problem}",
    "error.os": "execution: 실행 오류: {error}",
    "error.os_declaration": "declaration: 입력 오류: {error}",
    "error.internal": "예기치 않은 내부 오류 {exc_type}",
    "usage.locale_value": "--locale {value!r}: 다음 중 하나여야 합니다: {supported}",
    "render.validated": "유효함: {experiment} (실행 레코드 {records}개)",
    "render.checked": "검사 완료: {experiment} (실행 레코드 {records}개)",
    "render.written": "기록됨: {output}",
    "render.released": "해제됨: {released}",
    "render.recovered": "복구됨: {record} ({origin})",
    "render.progress": "실행 {executed}, 건너뜀 {skipped}, 남음 {remaining}",
    "render.run_state": "실행(run) {run}: {state}",
    "render.active_session": "  활성 세션: {session}   세션: {sessions}",
    "render.none": "없음",
    "render.scheduled": "  예정 {scheduled}개: {counts}",
    "render.decisions": "  결정: {decisions}",
    "render.custody": "  보관(custody): 항목 {entries}개 (FRESH {fresh}, RECOVERED {recovered})",
    "render.resume_permitted": "  재개 허용: {permitted}",
    "render.blocking": "    - {reason}",
    "render.operator_decision": "    운영자 결정 필요: {record}",
    "render.gated_valid": "유효함: {experiment} (설계 셀 {cells}개)",
    "render.gated_cell": "  {cell}: 계획 {plan}",
    "render.gated_gate": "gate-2 {decision}: {cell} (계획 {plan})",
    "render.gated_run": "실행(run) {run}: {state}",
    "render.gated_calls": "  호출: custody 수락 {accepted}개, 대기 {pending}개",
    "render.gated_resume": "  재개: {action}",
    "render.gated_package": "봉인된 {package_class} 패키지: 멤버 {members}개, "
                            "manifest {manifest}",
    "render.gated_analysis": "분석 {analysis}: {status}",
    "render.gated_l1": "P18 L1 적합성: {level} (숨은 호출: {hidden})",
    "render.gated_l2": "P18 L2 적합성: {level} (actor 간 전달: {edges})",
    "render.gated_world_replay": "World 재생: {verdict} (전이: {transitions})",
    "render.gated_l3": "P18 L3 적합성: {level} (결정→World 전이: {transitions})",
    "render.gated_l4": "P18 L4 적합성: {level} (종료된 라운드: {rounds}, 메모리 아티팩트: "
                       "{memory})",
    "render.gated_call_provenance": "호출 출처: {verdict} (숨은 호출: {hidden}; 모델 {model}, 사람 "
                                    "{human}, 도구 {tool})",
    "render.gated_l5": "P18 L5 적합성: {level} (완료된 사람 교환: {humans}, 해결된 도구 호출: "
                       "{tools})",
    "render.gated_l5_arguments": "  제한: 도구 인자 {declared}개 중 {rederived}개만 선언된 선택 "
                                 "규칙에서 재도출됨 (검증기에 전달되지 않은 고정 자료는 재계산되지 "
                                 "않음)",
    "render.contract_identity": "  ContractIdentity: {value}",
    "render.eii": "  ExperimentInputIdentity: {value}",
    "render.input_digest": "  input.json: {value}",
    "render.preflight_tool": "    gndcrw {version}  manifest {manifest}  result {result}",
    "render.limitations_indented": "    제한 사항: {limitations}",
    "render.input_lock": "  입력 잠금(input lock): {classification}{verification}{code}",
    "render.audit_head": "{eligibility}  실행(run) {run}",
    "render.dataset": "  데이터셋 {identity} (레코드 {records}개)",
    "render.analysed": "데이터셋 {dataset}의 레코드 {records}개를 분석함",
    "render.analysis": "  분석: {plugin} {version}",
    "render.analysis_result": "  결과: {result}",
    "render.epc_package": "EPC 패키지 {run}: 멤버 {members}개 (input lock: {input_lock})",
    "render.package_identity": "  package_identity: {value}",
    "render.evidence_root": "  evidence_root:    {value}",
    "render.identity": "  {kind}: {digest}",
    "render.self_check": "  생산자 자체 검사: {value}",
    "render.limitations": "  제한 사항: {limitations}",
    "render.verified": "VERIFIED (검증됨)",
    "render.refused": "REFUSED (거부됨)",
    "render.package": "패키지 {run}: 멤버 {members}개",
    "render.package_dataset": "  데이터셋: {identity}",
    "render.analysis_outputs": "  분석 산출물: {count}개",
    "render.recomputed_dataset": "  재계산된 데이터셋: {value}",
    "render.recomputed_eligibility": "  재계산된 적격성: {value}",
    "render.gate": "  실행 게이트(execution gate): {status} - {message}",
    "render.gate_reason": "    - [{rule_id}] {reason_code}: {message}",
    "render.gate_evidence": "      증거: {evidence}",
    "render.execution_status": "  실행 상태(execution): {status}",
    "render.human_waiting": "  응답 대기(waiting) {actor} ({participant}): intent {intent}, "
                            "데스크(desk) {desk}",
    "render.human_enrolled": "{participant} 을(를) {actor} 로 등록(enrolled) (consent {consent})",
    "render.human_pending": "데스크(desk) {desk}: 전달 {delivered}건 중 대기 {pending}건",
    "render.human_request": "  {actor} ({participant}) intent {intent}",
    "render.human_message": "    {role}: {content}",
    "render.human_answered": "intent {intent} 응답 기록(answered): {actor} ({participant})",
    "render.gate_record": "  게이트 기록(gate record): {path}",
    "render.gate_record_verified": "{verification}  {record} (실행 게이트: {status}, "
                                   "실행 상태: {execution})",
    "gate.status.CLEARED": "실행 전 게이트 통과; 실행을 시작할 수 있음",
    "gate.status.MANDATORY_REQUIREMENT_NOT_MET": "필수 연구/프로토콜/계약 조건이 충족되지 "
                                                 "않음; 실험을 실행해서는 안 됨",
    "gate.status.EXECUTION_NOT_POSSIBLE": "이 설치 환경에서는 실험을 실행할 수 없음 "
                                          "(필요한 런타임 기능 없음)",
    "gate.status.NOT_EVALUATED": "실행 게이트가 평가되지 않음",
    "gate.reason.GNDCRW_PREFLIGHT_NOT_CLEARED": "GNDCRW 사전 검사 결과가 {outcome}; "
                                                "첨부 조건은 {required_outcome} "
                                                "(findings: {findings})",
    "gate.reason.REQUIRED_RUNTIME_CAPABILITY_UNAVAILABLE": "{capability} {implementation}을(를) "
                                                           "이 환경에서 사용할 수 없음: "
                                                           "{detail} (없음: {missing})",
    "gate.reason.VALIDATION_ONLY": "validate는 게이트를 평가하지 않음; 'bvl check'를 실행",
    "gate.reason.EXECUTION_PROFILE_ABSENT": "실험 입력에 실행 프로파일이 없음",
    "gate.reason.LEGACY_RUN_NOT_GATED": "레거시(NOT_INPUT_LOCKED) 실행은 게이트를 거치지 않음",
    "gate.reason.EXECUTION_GATE_NOT_RECORDED": "증거에 게이트 결정이 기록되어 있지 않음",
    "error.schedule_preflight": "  스케줄 사전 검사(schedule preflight): {status} - {message}",
    "render.schedule_preflight": "  스케줄 사전 검사(schedule preflight): {status} - {message}",
    "schedule_preflight.status.EXACT_MATCH": "고정 스케줄이 정확히 일치함 (레코드 {length}개); "
                                             "실행을 시작할 수 있음",
    "schedule_preflight.status.NOT_REQUESTED": "기대 스케줄이 주어지지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_ORDER_MISMATCH": "{position}번 위치에서 순서가 다름: "
                                                           "기대 {expected}, 잠금 {actual}; "
                                                           "아무것도 시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_LENGTH_MISMATCH": "기대 레코드 {expected}개, 잠긴 "
                                                            "스케줄 {actual}개; 아무것도 "
                                                            "시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_IDENTITY_MISMATCH": "스케줄 identity가 바인딩되지 "
                                                              "않음 (잠금 {locked}, 재계산 "
                                                              "{recomputed}, 명시 {stated}); "
                                                              "아무것도 시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_PATH_ERROR": "기대 스케줄을 읽을 수 없음 ({path}: "
                                                       "{error}); 아무것도 시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_PARSE_ERROR": "기대 스케줄을 해석할 수 없음 "
                                                        "({problem}); 아무것도 시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_COMPARATOR_FAILED": "스케줄 비교가 실패함 ({error}); "
                                                              "아무것도 시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_SCHEDULE_MISSING": "{side} 쪽에 고정 스케줄이 없음 "
                                                             "({problem}); 아무것도 시작하지 "
                                                             "않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_UNVERIFIABLE": "비교 결과를 판정할 수 없음 "
                                                         "({problem}); 아무것도 시작하지 않음",
    "schedule_preflight.SCHEDULE_PREFLIGHT_BINDING_MISMATCH": "열린 실행이 게이트를 통과한 "
                                                             "스케줄이 아님 (게이트 {gated}, 실행 "
                                                             "{opened}); 아무것도 실행하지 않음",
    "error.experiment_input_preflight": "  실험 입력 사전 검사(experiment input preflight): "
                                        "{status} - {message}",
    "render.experiment_input_preflight": "  실험 입력 사전 검사(experiment input preflight): "
                                         "{status} - {message}",
    "experiment_input_preflight.status.EXACT_MATCH": "고정 실험 입력과 정확히 일치함 "
                                                     "({identity}); 실행을 시작할 수 있음",
    "experiment_input_preflight.status.NOT_REQUESTED": "기대 실험 입력이 주어지지 않음",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_IDENTITY_MISMATCH":
        "실험 입력이 고정된 것과 다름 (기대 {expected}, 실제 {actual}); 아무것도 시작하지 않음",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_PATH_ERROR":
        "기대 실험 입력을 읽을 수 없음 ({path}: {error}); 아무것도 시작하지 않음",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_PARSE_ERROR":
        "기대 실험 입력을 해석할 수 없음 ({path}: {problem}); 아무것도 시작하지 않음",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_UNVERIFIABLE":
        "실제 실험 입력 identity를 계산할 수 없음 ({problem}); 아무것도 시작하지 않음",
    "experiment_input_preflight.EXPERIMENT_INPUT_PREFLIGHT_BINDING_MISMATCH":
        "열린 실행이 게이트를 통과한 실험 입력이 아님 (게이트 {gated}, 실행 {opened}); "
        "아무것도 실행하지 않음",
    "render.request_content": "  요청 내용(request content): {status} - {message}",
    "render.request_content_reason": "    - {reason_code}: {message}",
    "request_content.status.AVAILABLE": "정확한 요청 바이트가 패키지에 포함됨",
    "request_content.status.WITHHELD": "요청 바이트는 존재하나 의도적으로 공개하지 않음; "
                                       "digest와 크기는 바인딩됨",
    "request_content.status.UNAVAILABLE": "요청 바이트가 보존되지 않았거나 복구할 수 없음",
    "request_content.reason.REQUEST_WITHHELD_CONFIDENTIAL": "기밀 연구 입력",
    "request_content.reason.REQUEST_WITHHELD_PERSONAL_DATA": "개인정보 포함",
    "request_content.reason.REQUEST_WITHHELD_LICENSE_RESTRICTED": "라이선스상 공개 제한",
    "request_content.reason.REQUEST_BUILDER_NOT_RECORDED": "실행이 요청 빌더를 기록하지 "
                                                           "않음 (레거시 실행)",
    "render.provenance_verified": "  검증된 provenance (패키지 바이트로 재계산): {fields}",
    "render.provenance_self_reported": "  자기보고 provenance (생산자·어댑터·도구의 주장; "
                                       "독립 검증되지 않음): {fields}",
    "render.provenance_unclassified": "  provenance ({schema}): 신뢰 수준 미분류; 모든 "
                                      "항목을 자기보고로 읽음",
}

CATALOGS: dict[str, dict[str, str]] = {"en-US": EN_US, "ko-KR": KO_KR}


def translate(key: str, params: Mapping[str, Any] | None = None,
              locale: str = DEFAULT_LOCALE) -> str:
    """Render `key` in `locale`; fall back to en-US, then to the bare key. Never raises."""
    params = dict(params or {})
    for name in dict.fromkeys((locale, DEFAULT_LOCALE)):
        template = CATALOGS.get(name, {}).get(key)
        if template is None:
            continue
        try:
            return template.format_map(params)
        except Exception:  # a broken template is a presentation defect, never a verdict
            continue
    try:
        return key + ("" if not params else " " + repr(sorted(params.items())))
    except Exception:
        return key


def resolve_locale(cli: str | None = None, config: str | None = None,
                   environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(locale, source). An explicit CLI value must be supported (the caller checks);
    an unsupported config or environment value is ignored."""
    if cli is not None:
        return cli, "cli"
    if config in SUPPORTED_LOCALES:
        return config, "config"
    env = (environ or {}).get(LOCALE_ENV)
    if env in SUPPORTED_LOCALES:
        return env, "environment"
    return DEFAULT_LOCALE, "default"


def split_locale(argv: list[str]) -> tuple[str | None, list[str]]:
    """A leading global `--locale X` / `--locale=X`; the subcommand grammars are untouched.
    Returns (value or None, the remaining argv). An unsupported value is returned as is:
    the caller refuses it as a usage error."""
    if not argv or not (argv[0] == "--locale" or argv[0].startswith("--locale=")):
        return None, argv
    if argv[0] == "--locale":
        if len(argv) < 2:
            return "", argv[1:]
        return argv[1], argv[2:]
    return argv[0].split("=", 1)[1], argv[1:]
