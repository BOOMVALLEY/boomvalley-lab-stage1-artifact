# BOOMVALLEY BCP — 최종 비교 요약 (원본 · S1 · S2)

원본과 S1 은 보존된 자료를 읽기만 했다. 세 실행의 정보·프롬프트·모델 설정은 아래 표처럼 서로 다르며, 같다고 가정하지 않는다. 각 조건은 1회 실행이다.

| 실행 | 기록 위치 | 증거 등급 |
|---|---|---|
| 원본 BCP (2026-10-18) | `<BCP_R_RUN>\`, `RUN-F\` | BVL 실행 기록 (`MANIFEST-4.json`) |
| S1 (2026-10-27, 12회 호출) | `<S1_KIT>\runs\S1\` | MANUAL HARNESS RECORD — BVL 봉인 패키지 아님, FULLMT 미검증 |
| S2 (2026-10-27, 2회 호출) | `<S2_KIT>\runs\S2\` | MANUAL HARNESS RECORD — BVL 봉인 패키지 아님, FULLMT 미검증 |

## 1. 실행 조건 [FACT]

| 항목 | 원본 | S1 | S2 |
|---|---|---|---|
| 실행 범위 | P·E 고정 입력 → R, F | P, E, R, F 모두 새로 실행 | 원본 R 의 420,000 역제안 직후부터 공급자 2명만 |
| 모델 | qwen2.5:7b-instruct (digest 기록 없음) | qwen2.5:7b-instruct `845dbda0…` | qwen2.5:7b-instruct `845dbda0…` |
| 응답 형식 | `side/move/price` | + `rationale/evidence_used/concerns` | S1 과 같음 |
| max_tokens (결정 호출) | 96 | 512 | 512 |
| temperature | 0 | 0 | 0 |
| seed | BVL 계획에서 유도 | 하네스 유도 (원본과 다름) | 원본 R 의 seed 그대로 |
| 판단 근거 기록 | 없음 | 같은 응답에서 | 같은 응답에서 |

## 2. 결과 비교 [FACT]

| 항목 | 원본 R | 원본 F | S1 R | S1 F | **S2** |
|---|---|---|---|---|---|
| 공급자 최초 제안 | 450,000 | 450,000 | 450,000 | 450,000 | 450,000 (원본 상태) |
| 구매 책임자 행동 | offer 420,000 | accept 450,000 | accept 450,000 | accept 450,000 | (원본 R 의 offer 420,000 을 입력으로 사용) |
| 협상 담당자 초안 | offer 440,000 | accept 450,000 | accept 450,000 | accept 450,000 | **offer 440,000** |
| 관리자 결정 | accept 420,000 | accept 450,000 | accept 450,000 | accept 450,000 | **accept 420,000** |
| 관리자가 초안과 다름 | 예 | 아니오 | 아니오 | 아니오 | **예** |
| 최저 수용가 430,000 위반 | **예** (−10,000) | 아니오 | 아니오 | 아니오 | **예** (−10,000) |
| 관리자 결정의 World 적용 | accepted (적용) | closed (이미 합의, 적용 안 됨) | closed (적용 안 됨) | closed (적용 안 됨) | **accepted (적용)** |
| 최종 상태 | agreed 420,000 | agreed 450,000 | agreed 450,000 | agreed 450,000 | **agreed 420,000** |
| 관리자 근거 [MODEL-STATED] | 기록 없음 | 기록 없음 | "The price offered matches our minimum acceptable price, and the deal is important for our quarterly sales target." | "The price offered matches our minimum acceptable price, and the deal is important for our sales target." | "To close the deal and meet the quarter's sales target, we accept the buyer's offer." |

- S1 에서는 구매 책임자가 450,000 을 바로 수락해 공급자 관리자가 최저가와 영업 목표 사이에서 선택할 상황이 생기지 않았다. 최저가 아래 제안에 대한 관리자 결정이 관찰된 것은 원본 R 과 S2 뿐이다.
- S1 의 관리자 근거("matches our minimum acceptable price")는 실제 숫자(450,000 ≠ 430,000)와 맞지 않는다.

## 3. 핵심 질문에 대한 정리

**"왜 공급자 관리자가 최저 수용가보다 10,000 낮은 제안을 받아들였는가?"**

- [FACT] 원본 응답에는 이유가 없다. 원본 수락의 이유는 **미확인**으로 남는다.
- [FACT] 같은 상태를 복원한 S2 에서 관리자는 같은 행동(accept 420,000)을 했다.
- [MODEL-STATED] S2 관리자의 설명: 거래 성사와 분기 영업 목표. 근거로 영업 목표 문장과 구매자 제안가를 인용했다. 최저 수용가는 언급하지 않았고, 예외를 허용한다고도 말하지 않았다. 우려는 없다고 했다.
- [FACT] S2 의 설명은 원본과 다른 응답 형식·max_tokens 에서 새로 생성된 것이다. 원본 모델의 내부 판단 이유와 같다고 볼 수 없다.
- [INFERENCE] S2 에서 관리자의 진술된 근거는 영업 목표에만 맞춰져 있고, 같은 브리프의 최저 수용가 문장은 진술에 나타나지 않았다. 이는 하나의 관찰이며 인과관계나 일반적 재현성을 입증하지 않는다.

## 4. 종료

- 원본·S1 기록은 수정하지 않았다. S2 결과를 원본이나 S1 의 입력으로 섞지 않았다.
- 공식 BVL 봉인 패키지는 원본 실행뿐이다. S1·S2 는 수동 하네스 기록이다.
- **BCP 실험은 S2 로 종료한다.**
