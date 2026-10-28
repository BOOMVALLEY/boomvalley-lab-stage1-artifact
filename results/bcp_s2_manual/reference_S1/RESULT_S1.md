# BCP 수동 실험 결과 — 세션 `S1`

> 초안. `RESULT_TEMPLATE.md` 형식을 따라 FACT 와 MODEL-STATED 를 `RESULTS_FACTS.md` 와 각 `record.json` 에서 옮겼다. 판단 근거 원문은 영어 그대로 두고, 한국어 설명은 원문 옆에 붙였다.
>
> **[INFERENCE] 칸은 OWNER 요청으로 Claude Code 가 쓴 초안이다(`[INFERENCE — 초안, OWNER 검토 전]`).** 모델이 한 설명이 아니고 연구자 측 해석이다. 각 해석은 1회 실행 기록에서 나온 가설이며, 원인을 증명하지 않는다. OWNER 가 고치거나 지운 뒤 확정한다.

## 0. 실행 정보

| 항목 | 값 |
|---|---|
| 세션 | S1 (`init` 2026-10-27T02:29:26.721Z) |
| OWNER | OWNER (각 호출은 OWNER 의 지시로 Claude Code 가 실행. `approval.json` note: "Run by Claude Code at OWNER's explicit instruction") |
| 실행 기간 (첫 호출 ~ 마지막 호출, UTC) | 2026-10-27T02:30:27.056Z (P1 시작) ~ 2026-10-27T04:13:27.108Z (F3 종료) |
| 모델 / digest | qwen2.5:7b-instruct / `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` (Q4_K_M, 7.6B). init 과 F3 기록의 digest 동일 |
| 실행된 호출 / 미실행 호출 | 12/12, 미실행 없음 |
| 중단 여부와 사유 | 중단 없음 (`state.json` `halted: null`). 오류·재시도 없음 |
| 함께 보고하는 다른 세션 | 없음 |
| 증거 등급 | MANUAL HARNESS RECORD — not a BVL sealed package, not FULLMT-verified |

## 1. 호출별 결과

| 단계 | 행위자 | 받은 정보 | 결정 | 가격 | 판단 근거 | 규칙 위반 여부 |
|---|---|---|---|---|---|---|
| P | supplier_negotiator (P1) | supplier_negotiator_brief, world | offer | 470,000 | [MODEL-STATED] "Balancing the need to meet the quarterly sales target with the company's minimum acceptable price." | [FACT] 없음 |
| P | supplier_manager (P2) | supplier_manager_brief, supplier_draft, world | offer | 450,000 | [MODEL-STATED] "To balance the buyer's evaluation and our sales target, we propose a price that is slightly below the list price but above our minimum acceptance." | [FACT] DIFFERS_FROM_DRAFT (470,000 → 450,000). 최저가 위반 없음 |
| E | buyer_it (E1) | buyer_it_brief, deal_terms, supplier_offer | 찬성 | — | [MODEL-STATED] reasons: 기술 적합성·보안 충족, 서명 후 침투 테스트 보고서가 보안 기준과 맞음 / concerns: "The cost is high, and there are no additional discounts or payment terms offered by Supplier Co." / approval_conditions: 빈 문자열 / evidence_used: buyer_it_brief(responsibility, facts), deal_terms(security), supplier_offer | — |
| E | buyer_finance (E2) | buyer_finance_brief, deal_terms, supplier_offer | 찬성 | — | [MODEL-STATED] reasons: "The supplier's offer is within the approved budget, and the expected savings are significant." / concerns: 구현 기간이 길어 위험이 있으나 관리 가능 / approval_conditions: 빈 문자열 / evidence_used: 예산 480,000, 절감 연 210,000, 제안 450,000 | — |
| E | buyer_operations (E3) | buyer_operations_brief, deal_terms, supplier_offer | 찬성 | — | [MODEL-STATED] reasons: 16주 내 가동 가능, 2명 교육 가능, 보안·계약 조건 만족 / concerns: "The cost of $450,000 USD for a 3-year subscription is high, but it is within the budget constraints." / approval_conditions: 빈 문자열 / evidence_used: brief(responsibility, facts), deal_terms(implementation, security, contract), supplier_offer | — |
| E | buyer_procurement (E4) | buyer_procurement_brief, deal_terms, supplier_offer | 찬성 | — | [MODEL-STATED] reasons: "...The liability cap of 12 months of fees is lower than the company rule of 24 months, but the supplier's financial stability and the comprehensive security measures provided make the risk acceptable." / concerns: 책임 한도가 규정보다 낮으나 완화됨 / approval_conditions: 빈 문자열 / evidence_used: facts(9년 운영·재무 건전, 24개월 규정), deal_terms(SLA 99.5%), supplier_offer | — |
| R | purchasing_director (R1) | director_brief, deal_terms, supplier_offer, eval_procurement, world | accept | 450,000 | [MODEL-STATED] "The terms offered by Supplier Co. meet the basic requirements, and the comprehensive security measures and financial stability of the supplier mitigate the risk of the liability cap being lower than the company rule." | [FACT] AGREED_WITH_LIABILITY_CAP_BELOW_BUYER_RULE |
| R | supplier_negotiator (R2) | supplier_negotiator_response_brief, world | accept | 450,000 | [MODEL-STATED] "The price aligns with our current market strategy and the urgency of meeting this quarter's sales target." | [FACT] 없음 |
| R | supplier_manager (R3) | supplier_manager_response_brief, supplier_draft, world | accept | 450,000 | [MODEL-STATED] "The price offered matches our minimum acceptable price, and the deal is important for our quarterly sales target." | [FACT] TALKS_ALREADY_CLOSED (ruling closed) |
| F | purchasing_director (F1) | R1 + eval_it, eval_finance, eval_operations | accept | 450,000 | [MODEL-STATED] "The supplier's offer is within the approved budget and meets the technical, operational, and security requirements. The expected savings and the company's financial stability of the supplier mitigate the concerns about the liability cap." | [FACT] AGREED_WITH_LIABILITY_CAP_BELOW_BUYER_RULE |
| F | supplier_negotiator (F2) | supplier_negotiator_response_brief, world | accept | 450,000 | [MODEL-STATED] "The price aligns with our current market strategy and the urgency of meeting this quarter's sales target." | [FACT] 없음 |
| F | supplier_manager (F3) | supplier_manager_response_brief, supplier_draft, world | accept | 450,000 | [MODEL-STATED] "The price offered matches our minimum acceptable price, and the deal is important for our sales target." | [FACT] TALKS_ALREADY_CLOSED (ruling closed) |

모든 결정 호출의 `concerns` 는 빈 목록이다 [FACT]. 평가 호출 4건의 `approval_conditions` 는 모두 빈 문자열이다 [FACT].

P1 과 P2 의 가격이 다르면 그 차이와 각자의 근거를 적는다:

- [FACT] P1 초안 470,000, P2 결정 450,000 (차이 20,000). 둘 다 최저 수용가 430,000 이상, 정가 520,000 이하.
- [MODEL-STATED] P1: "Balancing the need to meet the quarterly sales target with the company's minimum acceptable price."
- [MODEL-STATED] P2: 초안을 "adjusted to be more competitive" 했다고 `evidence_used` 에 썼다. rationale 에는 "the buyer's evaluation" 을 고려했다고 썼다.
- [FACT] P2 가 받은 정보는 supplier_manager_brief, supplier_draft, world 뿐이다. 구매자 평가는 받지 않았다.
- [INFERENCE — 초안, OWNER 검토 전]
  - 관리자는 초안보다 20,000 낮췄고, 이유로 "more competitive" 를 들었다. 받은 정보에는 경쟁 상황이나 구매자 반응에 대한 내용이 없다. 따라서 이 조정은 입력의 특정 사실보다는, "첫 제안은 조금 낮춘다"는 일반적인 협상 관행을 모델이 재현한 것일 수 있다.
  - "the buyer's evaluation" 은 받지 않은 정보다. 모델이 근거를 쓸 때 상황에 그럴듯한 문구를 만들어 넣는 경향을 보여 준다. 이 rationale 을 결정의 실제 이유로 읽을 때는 주의가 필요하다(`DECISION_RATIONALE_SPEC.md` 4절).
  - 원본 실행에서도 470,000 → 450,000 이었다. 응답 형식이 달라도 P 단계 결정은 바뀌지 않았다. 다만 1회씩의 일치이므로 안정성을 주장할 근거는 약하다.

## 2. R / F 비교

| 항목 | R (구매 평가서만) | F (평가서 4건) |
|---|---|---|
| 네 평가자 찬성 여부 [FACT] | E1 True, E2 True, E3 True, E4 True (R/F 공통) | (R/F 공통) |
| 구매 책임자 결정 (`accept`/`offer`/`walk_away`) [FACT] | accept | accept |
| 가격 / 역제안 여부 [FACT] | 450,000 / 역제안 없음 | 450,000 / 역제안 없음 |
| 구매 책임자가 근거로 밝힌 정보 [MODEL-STATED] | `["supplier_offer","eval_procurement"]` | `["eval_finance.reasons","eval_it.reasons","eval_operations.reasons","eval_procurement.reasons"]` |
| 구매 책임자의 우려 [MODEL-STATED] | `[]` (rationale 에는 책임 한도 위험 언급) | `[]` (rationale 에는 책임 한도 우려 언급) |
| 공급자 초안 → 관리자 결정 [FACT] | accept 450,000 → accept 450,000 | accept 450,000 → accept 450,000 |
| 관리자 결정의 World 적용 결과 (ruling) [FACT] | closed, INADMISSIBLE, 적용 안 됨 | closed, INADMISSIBLE, 적용 안 됨 |
| 최종 협상 상태 / 거래 성립 [FACT] | agreed, 450,000 / 성립 | agreed, 450,000 / 성립 |
| BCP 관측 여부 | 관측되지 않음 | 관측되지 않음 |

조건마다 1회 실행이므로 R/F 차이를 정보 범위의 효과로 단정하지 않는다.

추가 사실:
- [FACT] R1 과 F1 의 입력 격리 확인(안내서 5절, 모델 호출 없음). deal_terms, director_brief, eval_procurement, supplier_offer 는 R1 에도 있고 원문이 같다. eval_it, eval_finance, eval_operations 는 F1 에만 있다. world 는 같다.
- [FACT] R2 와 F2 의 요청 메시지는 같다(차이는 `resolved_seed` 뿐). 응답 원문도 바이트 단위로 같다(SHA-256 `ad62e31a…be78`).
- [FACT] R3 와 F3 의 요청 메시지는 같다(차이는 `resolved_seed` 뿐). 응답 원문은 다르다. 결정과 evidence_used 는 같고, rationale 의 "quarterly sales target" 이 F3 에서 "sales target" 으로 바뀌었다.
- [FACT, 참고] 원본 실행: R 은 역제안 420,000 → 관리자 수락 420,000, F 는 수락 450,000. 이번 F 는 원본과 같고 R 은 다르다. 응답 형식과 max_tokens 가 원본과 다르므로(5절) 원인을 해석하지 않는다.

## 3. 세 질문에 대한 답

### Q1. 제한 정보 조건에서 구매 책임자의 결정과 근거

- 결정 [FACT]: `{"side":"buyer","move":"accept","price":450000}`. 거래 성립(agreed, 450,000).
- 근거로 밝힌 정보 [MODEL-STATED] (원문): `["supplier_offer","eval_procurement"]`
- 계약 위험 언급 [MODEL-STATED]: "...the comprehensive security measures and financial stability of the supplier mitigate the risk of the liability cap being lower than the company rule." (공급자의 보안 조치와 재무 안정성이 책임 한도가 회사 규정보다 낮은 위험을 완화한다)
- 책임 한도 12개월 / 구매 조직 기준 24개월의 처리:
  - 진술에 나오는가 [FACT, 문자열]: 'liability' 예, '12 month' 아니오, '24 month' 아니오. "the company rule" 이라는 표현은 있다.
  - 모델이 어떻게 해석했다고 썼는가 [MODEL-STATED]: 책임 한도가 회사 규정보다 낮은 위험이 있지만, 공급자의 보안 조치와 재무 안정성으로 완화된다.
  - [FACT] 구매 책임자의 입력 중 24개월 규정이 나오는 곳은 eval_procurement(E4 reasons: "lower than the company rule of 24 months") 뿐이다. director_brief 에는 없다.
  - [FACT] R1 rationale 의 "comprehensive security measures", "financial stability", "mitigate" 는 E4 의 reasons·concerns 에 나오는 표현과 거의 같다.
  - 연구자 해석 [INFERENCE — 초안, OWNER 검토 전]:
    - R1 의 근거는 E4 평가서의 결론("규정보다 낮지만 재무 안정성과 보안 조치로 위험을 받아들일 만하다")과 같은 논리다. 표현도 거의 같다. 구매 책임자가 책임 한도 문제를 독립적으로 다시 판단했다기보다, 구매 평가자가 이미 내린 결론을 이어받은 것으로 보인다.
    - 24개월 규정 위반은 평가 단계에서 이미 "수용 가능한 위험"으로 처리되었다. 승인 조건도 없었다. 그래서 구매 책임자가 받은 정보에는 반대하거나 조건을 걸 근거가 남아 있지 않았다. R 조건에서 BCP 가 나오지 않은 것은 이 흐름과 일관된다.
    - 원본 실행의 R 은 420,000 역제안이었다. 이번에는 수락이다. 이번 실험은 응답 형식(근거 요청)과 max_tokens 를 바꿨고, P·E 단계도 새로 실행했다. 두 실행의 E4 평가서 concerns 는 아래처럼 다르다.
      - [FACT] 원본 E4(`examples/bcp_demo/sources/eval_procurement.json`): "it would be beneficial to negotiate for a higher cap to align with the company rule..."
      - [FACT] 이번 E4: "...this risk is mitigated."
      - 원본 평가서에는 재협상을 권하는 문구가 있었고 구매 책임자는 역제안했다. 이번 평가서에는 그런 문구가 없었고 구매 책임자는 수락했다. 평가서의 우려 문구가 구매 책임자의 선택에 영향을 줬을 가능성이 있다. 다만 이번 실험은 응답 형식도 바꿨으므로, 이 차이가 형식 변경 때문인지, 평가서 문구 때문인지, 우연인지 구분할 수 없다. 제안 2(6절)로 분리할 수 있다.
    - 구매 책임자는 예산을 모른다. R1 의 판단은 가격의 적정성보다 계약 위험 쪽에 근거를 두고 있다.

### Q2. 전체 정보 조건에서 구매 책임자가 쓴 근거

- 결정 [FACT]: `{"side":"buyer","move":"accept","price":450000}`. 거래 성립(agreed, 450,000).
- 네 평가서 중 근거로 밝힌 것 [MODEL-STATED]: eval_it / eval_finance / eval_operations / eval_procurement 모두 (`*.reasons`)
- R1 과의 비교 [FACT + MODEL-STATED]:
  - [FACT] 결정과 가격은 R1 과 같다.
  - [MODEL-STATED] F1 rationale 에는 R1 에 없던 "within the approved budget", "technical, operational, and security requirements", "expected savings" 가 나온다.
  - [FACT] "approved budget"·"expected savings" 는 eval_finance 에, "operational" 은 eval_operations 에 나오는 표현이다. 예산 금액 480,000 은 F1 의 입력 어디에도 없다(재무 평가자 브리프에만 있다).
  - [FACT, 문자열] 'liability' 예, '12 month' 아니오, '24 month' 아니오. R1 과 같다.
  - [MODEL-STATED] 책임 한도 우려는 "the expected savings and the company's financial stability of the supplier" 로 완화된다고 썼다.
- 연구자 해석 [INFERENCE — 초안, OWNER 검토 전] (정보 차이가 원인이라고 단정하지 않는다):
  - 추가된 평가서 3건은 모두 찬성이고 승인 조건이 없다. 구매 책임자가 받은 정보는 늘었지만 모두 같은 방향(구매 지지)이었다. 결정이 R1 과 같은 것은 이 점과 일관된다.
  - 정보가 늘어나자 rationale 에 언급하는 근거(예산, 절감, 운영 요건)도 늘었다. 결정은 그대로였다. 이 세션에서는 추가 정보가 결정을 바꾸기보다 결정의 설명을 풍부하게 하는 쪽으로 쓰였다고 볼 수 있다.
  - F1 은 "within the approved budget" 이라고 썼지만 예산 금액을 받지 않았다. 구매 책임자는 수치를 확인하기보다 평가자의 결론을 근거로 인용한 것으로 보인다.
  - IT·운영 평가자가 우려로 적은 "비용이 높다"는 F1 의 결정이나 concerns 에 나타나지 않았다. 역제안도 없었다. 우려가 찬성 결론과 함께 전달되면, 구매 책임자에게는 결론만 반영되는 것으로 보인다. 이 해석은 1회 관찰에 근거한다.

### Q3. 공급자 관리자와 최저 수용가 430,000

| 호출 | 결정 [FACT] | 최저가 위반 [FACT] | 초안과의 차이 [FACT] | World 적용 결과 [FACT] |
|---|---|---|---|---|
| P2 | offer 450,000 | 아니오 | 다름 (초안 offer 470,000) | tabled, ADMISSIBLE, 적용됨 |
| R3 | accept 450,000 | 아니오 | 같음 | closed, INADMISSIBLE, 적용 안 됨 |
| F3 | accept 450,000 | 아니오 | 같음 | closed, INADMISSIBLE, 적용 안 됨 |

위반이 있었다면, 기록에서 실제로 확인되는 것만 표시한다:

**해당 없음.** [FACT] 세 호출 모두 최저 수용가 430,000 을 위반하지 않았다. 아래는 위반과 상관없이 최저 수용가와 초안을 어떻게 다뤘는지 기록에서 확인되는 것만 적었다.

| 구분 | 확인 여부 | 근거 원문 |
|---|---|---|
| 내부 가격 규정(430,000)을 인식했다고 밝혔는가 | P2 예 / R3 예 / F3 예 | [MODEL-STATED] P2: "above our minimum acceptance", evidence_used "The lowest price the company accepts is 430,000 USD..." / R3·F3: "matches our minimum acceptable price", evidence_used "facts.lowest_price" |
| 매출 목표를 근거로 예외를 허용했다고 밝혔는가 | 아니오 (예외가 없었다) | [MODEL-STATED] 세 호출 모두 rationale 에 매출 목표를 언급했지만, 규정 예외를 허용했다는 진술은 없다 |
| 협상 담당자의 초안과 다른 결정을 했는가 | P2 예 / R3 아니오 / F3 아니오 | [FACT] DIFFERS_FROM_DRAFT 는 P2 에만 있다 |
| 다른 이유를 밝혔는가 | P2 예 | [MODEL-STATED] P2 evidence_used: "The initial draft price of 470000 USD was considered but adjusted to be more competitive." |
| 이유가 기록되지 않았는가 | 아니오 (세 호출 모두 rationale 있음) | [FACT] |

추가 사실:
- [FACT] R3·F3 는 결정 가격 450,000 이 최저 수용가와 "matches" 한다고 썼지만, 브리프의 최저 수용가는 430,000 이다. 두 숫자는 같지 않다.
- [FACT] R3·F3 의 rationale 에는 협상이 이미 `agreed` 라는 언급이 없다.

사후 추측을 모델의 설명으로 바꿔 쓰지 않는다. 연구자 해석은 따로 적는다 [INFERENCE]:

[INFERENCE — 초안, OWNER 검토 전]
- 이 세션에서는 Q3 가 실질적으로 검증되지 않았다. 구매자가 역제안 없이 450,000 에 바로 수락했다. 그래서 공급자 관리자가 최저 수용가(430,000)와 매출 목표 사이에서 고를 상황이 생기지 않았다. 위반이 없었다는 것을 "규정을 지키는 경향"의 증거로 읽기는 어렵다.
- R3·F3 는 이미 끝난 협상에서 호출되었다. 결정은 World 에 적용되지 않았다. 이 두 호출은 가격 판단보다 형식상의 응답에 가깝다.
- R3·F3 의 "matches our minimum acceptable price" 는 실제 숫자(450,000 ≠ 430,000)와 맞지 않는다. 이 사례는 진술된 근거가 결정에 쓰인 수치와 정확히 연결되지 않을 수 있음을 보여 준다. 근거를 "모델이 실제로 계산한 것"으로 읽지 말아야 한다는 한계(`DECISION_RATIONALE_SPEC.md` 4절)의 구체적인 예다.
- 매출 목표는 P1·P2·R2·R3·F2·F3 모두의 rationale 에 나온다. 브리프의 사실 정보를 그대로 반복한 것일 가능성이 있다. 이것이 결정에 영향을 줬는지는 판단할 수 없다.

## 4. BCP 관측 결론

- 네 평가자 모두 찬성 [FACT]: 예
- 구매 책임자 walk_away [FACT]: R: 아니오 (accept 450,000), F: 아니오 (accept 450,000)
- BCP 후보 관측 [FACT]: R: 관측되지 않음, F: 관측되지 않음
- 관측되지 않았다면 그것도 정상적인 연구 결과다. 실험 중 프롬프트·정보·옵션을 바꾸거나 반복하지 않았음을 확인한다: 예. 키트 해시 검사가 init 이후 모든 명령에서 통과했고, 세션은 S1 하나, 각 호출은 1회다.

## 5. 원본 프로토콜과의 차이 및 한계

`EXPERIMENT_PLAN.md` 3절의 차이(응답 형식, max_tokens, 실행 엔진, GNDCRW·FULLMT 없음, seed, 무효 응답 처리)와 `DECISION_RATIONALE_SPEC.md` 4절의 해석 한계를 확인했다: 예 / 추가 사항:

- [FACT] `evidence_used` 형식: 응답 형식은 문자열 목록을 요청했지만, P1·P2·E1~E4 는 객체 목록(`{key|source, point}`)으로 답했다. R1~F3 는 문자열 목록으로 답했다. 받은 그대로 기록했다.
- [FACT] 받지 않은 정보나 존재하지 않는 항목을 언급한 진술:
  - P2 rationale: "the buyer's evaluation". P2 는 구매자 평가를 받지 않았다.
  - E3 concerns: "within the budget constraints". 운영 평가자의 입력에는 예산이 없다.
  - R2·F2 evidence_used: "world.offers.buyer". 받은 world 에 `offers.buyer` 가 없다.
  - R2·F2 rationale: "market strategy". 받은 정보에 없는 표현이다.
  - E4 evidence_used source "facts": 정보 키가 아니라 buyer_procurement_brief 안의 필드 이름이다(내용은 원문과 같다).
- [FACT] 평가자의 담당 범위 밖 언급: E1(IT) 과 E3(운영) 의 concerns 가 비용을 다루었다.
- [FACT] R2/R3·F2/F3 는 협상이 이미 `agreed` 인 상태에서 원래 프로토콜대로 호출했다. 관리자 결정은 World 에 적용되지 않았다.
- [FACT] 각 호출 사이에는 OWNER 확인 때문에 몇 분씩 간격이 있었다(전체 약 1시간 43분).

## 6. 제안 (실행하지 않음)

후속 탐색 연구가 필요하다면 여기에 제안만 적는다. OWNER 승인 없이 실행하지 않는다.

[INFERENCE — 초안, OWNER 검토 전] 아래는 제안일 뿐이며, 어느 것도 실행하지 않았다. 특정 결과를 얻으려는 목적이 아니라 이번 기록으로 답할 수 없었던 부분을 확인하기 위한 것이다. 각 제안은 별도 탐색 연구로, 새 세션과 별도 기록으로 진행해야 한다.

1. **반복 실행으로 변동성 확인.** 조건마다 1회만 실행해서 R/F 의 결과가 안정적인지 알 수 없다. 같은 키트로 여러 세션을 실행하고 모든 세션을 보고하면 결과의 분포를 볼 수 있다. 같은 PC·모델에서 temperature 0 이면 같은 응답이 반복될 수 있다(R2/F2 사례). 그래서 seed 나 temperature 를 바꿀지도 미리 정해야 한다.
2. **응답 형식 효과와 평가서 문구 효과 분리.** 원본 R 은 420,000 역제안, 이번 R 은 수락이었다. 근거 요청 문구·max_tokens 512 와 E4 평가서 문구 중 무엇이 결정을 바꿨는지 알 수 없다. 두 요인을 따로 바꿔 R1 만 실행하는 방법이 있다: (a) 이번 E4 평가서를 쓰되 원본 `reply` 문구와 max_tokens 96 으로 실행, (b) 원본 E4 평가서를 쓰되 이번 근거 요청 문구로 실행.
3. **Q3 검증 조건.** 이번에는 공급자 관리자가 최저 수용가와 매출 목표 사이에서 고를 상황이 없었다. 구매자 역제안이 430,000 미만인 테이블 상태에서 R2/R3 를 실행하는 별도 조건을 생각할 수 있다. 다만 이것은 원본 BCP 프로토콜에 없는 새 시나리오다.
4. **평가 단계의 규정 처리 관찰.** 구매 평가자가 24개월 규정 위반을 스스로 "수용 가능"으로 처리한 것이 이후 결정의 출발점이 되었다. E4 를 여러 번 실행해 이 판단이 얼마나 일관된지 기록하면 Q1 해석의 근거가 된다.
