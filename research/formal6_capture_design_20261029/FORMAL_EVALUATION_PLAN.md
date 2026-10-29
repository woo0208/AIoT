# 정식 6인·학습2/보류검증4 평가 계획 초안

작성일: 2026-10-29. 상태: **DRAFT / 원문·승인·연구 결정 확인 전 / 데이터 수집·평가 미실행**.

이 문서는 [기존 평가 지표 체계](../evaluation_framework_20261029/METRIC_DEFINITIONS.md)를 유지하면서 6명×6자세×5회 설계에 대한 데이터 분리와 평가 단위를 제안한다. 최종 feature/model을 선정하거나 기존 알고리즘·하이퍼파라미터를 바꾸지 않는다. IRB 원문 미확인 항목은 [IRB_PROTOCOL_DIFF.md](IRB_PROTOCOL_DIFF.md)를 따른다.

## 1. 주 평가 과제와 아직 확정되지 않은 범위

이번 요청의 촬영 설계는 P0~P5 여섯 자세를 포함한다. **6-class를 정식 주 평가로 사용할지는 아직 연구 결정·IRB 범위 확인이 필요하다.** 현재 Research Master/기존 evaluator의 primary5를 이 초안으로 자동 대체하지 않는다.

| 과제 | 포함 라벨 | 이번 초안의 위치 |
|---|---|---|
| 6-class 후보 평가 | P0 upright, P1 forward_head, P2 lean_back, P3 lean_left, P4 lean_right, P5 lean_forward | 요청된 정식 설계의 평가안. 승인/연구 freeze 후 적용 가능 여부 확인 |
| 기존 primary5 | P0~P4, P5는 fit/metrics에서 제외 | 별도 과제. 기존 역할 유지 |

촬영을 6자세로 한다는 것과 6-class primary endpoint 채택은 같은 결정이 아니다. 별도 5-class 평가가 필요하면 그 학습/표본/metric을 별도 트랙으로 고정한다. 6-class confusion matrix에서 P5 행/열을 지워 5-class 성능으로 보고하지 않는다.

## 2. 참가자·데이터 역할 분리

아래 ID는 실제 참가자 발급이 아닌 설계 자리표시자다. 실제 인물 배정은 모델 성능·특징 분포를 보기 전에 확정하고 근거를 기록해야 한다.

| 자료/집단 | 자리표시자 | 목적 | 사용 가능 시점/금지 |
|---|---|---|---|
| 기존 파일럿 | 기존 P01/P02와 통제되지 않은 legacy | 과거 탐색·방법 개발 이력 | pilot 유지; 정식 목표 수/최종 외부검증에 편입 금지 |
| 정식 학습/개발 2명 | F01, F02 | 정식 모델 학습·허용된 개발 검토 | 동일 두 사람의 S1/S2·5회 전체를 개발 측에만 사용 |
| 정식 보류검증 4명 | F03~F06 | participant-independent held-out validation | method/model/scaler/분석 정책 freeze 전 모델 개발에 열람·사용 금지 |

실제 모집한 사람이 과거 파일럿/개발에 참여했는지 확인한다. ID가 새로 바뀌어도 같은 사람은 독립 검증 참가자가 아니다. 개발 2명이 과거 파일럿과 겹칠 경우 그 이력을 공개하되 파일럿 raw를 formal로 바꾸지 않는다. 보류검증 4명의 인물 독립성은 별도 보호된 연결표로 확인한다.

동일 승인된 정식 촬영으로 획득한 자료의 원천 `dataset_role`은 formal로 설계하되, 분석상 train/heldout 사용 구분을 따로 둔다. 검증용 사람이라는 이유만으로 schema의 `dataset_role=external`로 자동 변환하지 않는다. 같은 장소·프로토콜의 보류 참가자 검증을 기관/환경까지 다른 강한 외부 일반화 검증으로 과장하지 않는다.

## 3. 목표 표본 수와 세션별 배분

| 집단 | S1: 3회×6자세 | S2: 2회×6자세 | 전체 목표 | 클래스당 목표 |
|---|---:|---:|---:|---:|
| 학습/개발 2명 | 36 | 24 | **60** | **10** |
| 보류검증 4명 | 72 | 48 | **120** | **20** |
| 전체 6명 | 108 | 72 | **180** | **30** |

1인당 30목표 구간, 클래스당 5회다. 세션은 1인에게 속한 반복 조건으로 기록하며 신규 참가자나 독립 학습/검증 집단으로 취급하지 않는다. 목표 외 복귀 upright는 분모에 넣지 않는 설계안이며 원본에서 삭제하지 않는다.

이 숫자는 계획된 완전 자료 기준이다. 실제 유효 수가 줄면 실제 포함/제외·클래스 support와 이유를 보고한다. 이 초안은 180개/120개 결과를 생성하거나 누락 결과를 추정하지 않는다.

## 4. 단계별 분리·봉인 흐름 제안

1. IRB 범위/윤리·동의, Foundation 및 공식 실행 조건, 6-class 여부·촬영/라벨/분석 창·포함/재시도 정책을 먼저 확인한다. 현재는 시작하지 않는다.
2. 실제 참가자 6명의 분석 집단을 데이터 분포/정답률을 보기 전에 배정하고 고정한다. same-person·동일 recording·동일 raw frame의 집단 간 중복이 없는지 확인한다.
3. **우선 운영안:** 학습/개발 2명의 두 세션을 완료하고 허용된 개발 검토를 끝낸 뒤, 특징/알고리즘·하이퍼파라미터·전처리·metric·선택/제외·run 정책을 freeze한다. 이는 이 초안에서 개발/학습을 실행한다는 뜻이 아니다.
4. 그 후 학습 2명의 승인된 적격 구간만으로 scaler와 최종 평가용 모델을 학습·고정하는 절차를 계획한다. 모델 hash·train input manifest·software/artifact lock·feature/class 순서를 남기는 방식은 기존 lineage 계약과 연결한다.
5. 보류검증 4명은 위 freeze 이후 같은 승인 protocol로 촬영·라벨 QA·평가하는 순서를 우선 검토한다. 동시 수집이 불가피한 경우에는 사전 지정 보관/검토 담당자의 최소 접근과 개발 분석자의 열람 차단, freeze 이전 정보 노출 여부를 명시한 별도 절차가 필요하다.
6. 고정된 모델/scaler를 외부 4명의 적격 구간에 적용한다. 점수/오류를 보고 창·특징·label·threshold·classifier를 바꾸거나 train에 외부 사람을 추가하지 않는다.

보류 자료의 수집/라벨 검토 담당자가 수행 품질을 확인하는 것과 개발자가 결과·특징을 열람하는 것을 구분한다. 접근 권한·봉인·해제 시점은 동의/IRB 범위와 실제 운영 절차에 맞춰 먼저 정해야 한다. 독립성 훼손이나 누출이 확인되면 숨기지 말고 판정/한계를 기록한다.

## 5. 학습·표준화와 split 단위

- 최종 2→4 평가의 scaler mean/scale은 **학습 2명의 적격 구간만**으로 계산한다. 완전 자료이면 60구간이다. 보류 120구간의 분포·세션별 평균·P0 baseline으로 재표준화하거나 재학습하지 않는다.
- 모든 classifier를 사전 비교하기로 확정하는 경우 동일 구간·라벨·분할을 쓰며, scaler가 필요한 모델은 각각 학습 자료 안에서만 fit한다. 기존 M0 원시 입력/구현과 M0/M1/M2/M3-G 정의는 변경하지 않는다.
- 기존 LR C=1/L2/lbfgs/tol=1e-4/max_iter=10000 등은 과거 파일럿의 설정이다. 정식 방법으로 그대로 유지할지와 후보/보조 모델 목록은 freeze 항목이며, 이 문서가 LR/B를 최종 채택하거나 새로운 탐색을 승인하지 않는다.
- 필요하다면 개발 2명 내 participant LOSO를 내부 sanity/development 평가로만 별도 계획할 수 있다. 완전 자료이면 fold마다 train 30/test 30이고 test 사람의 두 세션을 함께 보류한다. 최종 외부 4명의 성능과 섞지 않는다.
- 6명 전체 LOSO, 세션별 무작위 train/test, 같은 사람의 반복/프레임 분할은 요청된 **학습2/외부4 독립 검증의 대체물이 아니다**. 외부 4명을 학습 fold에 넣는 전체 LOSO는 이번 주 평가안에 포함하지 않는다.
- 5회 반복은 다섯 번 재학습하거나 seed마다 다른 사람을 고르는 뜻이 아니다. seed 수와 목록은 사전 고정 항목이다. 기존 0~4를 유지하는 방안은 후보지만 OPEN-005의 정식 결정을 이 문서가 확정하지 않는다.

## 6. 표본 구성·라벨·과학적 포함

한 목표 자세의 한 반복을 하나의 기본 분석 구간으로 제안한다. 영상 frame, sliding window, auxiliary upright, 동일 구간의 seed 반복을 독립 표본처럼 늘리지 않는다. 향후 window 단위 평가를 추가하려면 구간/사람 종속성과 분모를 별도 명시해야 한다.

P0는 해당 full-series의 첫 upright에서 하나만 목표로 선정하는 설계이며 나머지 upright는 reference/return 역할로 분리한다. P1/P5의 수행 정의·사람 검토·capture face-only gate는 [촬영 초안](CAPTURE_PROTOCOL_DRAFT.md) §6을 따른다. classifier 결과나 F8/F9/C3의 값으로 ground truth를 만들지 않는다.

유효 분석 창 W1(각 목표10초)의 적용 여부, 라벨 불확실성, ok_with_warnings, 기술 실패·재촬영/선택, 공통 유효 frame/coverage 정책은 **수집/외부 열람 전 freeze할 후보**다. 기존 engineering H9 eligibility를 정식 포함 승인으로 자동 승격하지 않는다. 부족한 클래스를 만들기 위해 기간/역치/누락값을 사후 보정하지 않는다.

정식 canonical raw/frames/selection manifest와 H9 derived sample/evaluator의 연결은 별도 검증할 필요가 있다. 현재 탐색 CSV adapter가 동작했다는 사실만으로 정식 provenance/모델 lock/selection 연결이 완료됐다고 보지 않는다. frozen scientific schema에 임의 열·version을 추가하지 않는다.

## 7. 평가 지표와 출력

6-class 주 평가안이 확인되고 완전 자료가 들어온 경우에만 아래 분모가 성립한다.

| 출력 | 전체 보류검증 | 참가자/세션별 |
|---|---|---|
| Accuracy | 120개 보류 예측 중 정답 비율 | 검증 4명 각각 30구간; S1 72/S2 48도 별도 |
| Macro-F1 | 각 seed에서 보류 120개 예측을 pooled → 여섯 클래스 F1 평균 → 사전 고정 seed 평균 | 참가자 4명의 F1과 그 동등 평균을 별도 지표로 보고 |
| 클래스 Precision/Recall/F1 | 각 클래스 실제 support 목표20, 실제 포함 support도 표기 | 참가자별 클래스 목표5; S1 검증 집단 클래스12/S2 클래스8 |
| 혼동행렬 | 실제 P0~P5×예측 P0~P5, seed별 정수 count | 참가자별·S1/S2 같은 순서/형식 |
| P0/P1/P5 오류 | 모든 방향 count와 실제 클래스 support를 분모로 한 rate | P0→P1/P2, P1→P0/P5, P5→P0/P1을 포함해 같은 형식 |
| 누락/제외 | 계획·시도·완료·라벨 확인·적격·최종 포함 수 | participant×session×repeat×class와 이유 |

`Accuracy=trace(C)/N`, `Precision_k=TP/(TP+FP)`, `Recall_k=TP/(TP+FN)`, `F1_k=2TP/(2TP+FP+FN)`이며 기본 정의는 기존 평가 체계를 유지한다. 전체 pooled Macro-F1과 참가자 F1 평균을 혼용하지 않는다.

예측 support=0일 때 기존 Precision=0 규칙, 실제 support=0 클래스 처리와 complete-class 표시, 불완전 참가자/세션의 집계 정책은 명시적으로 freeze한다. 이번 제안은 기존 `rf.macro_f1`의 의미를 바꾸지 않는다.

독립 검증 참가자는 **4명**이다. 120구간이나 수천 frame, seed 반복을 120명/추가 독립 참가자로 해석하지 않는다. 불확실성·통계 비교가 필요하면 참가자 내 반복/세션 종속성을 반영할 계획을 사전 정의하고, n=4의 한계를 명시한다. 이 초안은 검증 결과·CI·유의성·목표 정확도를 생성하지 않는다.

## 8. 분류 성능과 계산 효율의 분리

과거 표준화 포함 분류 p50/p95·classifier+scaler 직렬화 크기는 이미 집계된 특징 한 개의 offline host 측정이다. 정식 영상의 CPU/RAM/FPS/host 지연/물리 E2E와 다르다. [기존 시스템 실측 초안](../evaluation_framework_20261029/D455_MEASUREMENT_PROTOCOL_DRAFT.md)의 측정 경계를 유지하며 실제 D455 계측은 별도 승인·구현/환경 확인 전 실행하지 않는다.

현재 5-B artifact는 5-class M0 개발 모델이다. 6-class 정식 평가 모델/LR와 같은 학습 객체가 아니고, 이 문서가 runtime 연결·모델 교체를 승인하지 않는다. 성능 표의 높은 수치만으로 배포/실시간 적합성·측정품질 PASS를 주장하지 않는다.

## 9. 동결·개방 전 확인표

| 확인 대상 | 초안의 현재 상태 |
|---|---|
| 제출 IRB·동의서·공통 SOP 원문/version 및 적용 범위 | 미확인 |
| **5회 반복·3+2 세션의 범위/부담 관련 확인(R1)** | 미확인, 별도 확인 필요 |
| **알고리즘/특징/6-class 평가 변경 범위 관련 확인(R2)** | 미확인, 별도 확인 필요 |
| 실제 정식 6명 모집·분할·기존 파일럿 중복/외부4 독립성 | 미확인 |
| class scope·정식 feature/model/scaler·hyperparameter·seed·metric freeze | 미완료/확인 필요; 이번 초안은 결정하지 않음 |
| 라벨/분석 창/포함·제외/재촬영·selection 정책 | 검토안만 있음, freeze 필요 |
| Foundation/Patch 8/EXPERIMENT_PROTOCOL·실행 승인 조건 | 기존 보류/선행 요구 유지; 실제 측정·수집 없음 |
| 데이터·source/model hash·canonical lineage·접근/봉인/해제 절차 | 구현·운영 검증과 사전 고정 필요 |

위 확인이 끝나기 전에 학습·외부 자료 열람/평가·정식 수집을 시작하지 않는다. 이 문서는 결정 로그·승인 기록·실행 Registry를 대신하지 않는다.

근거: [Research Master](../../docs/research/AIoT_RESEARCH_MASTER.md), [Decision Log](../../docs/research/RESEARCH_DECISION_LOG.md) DATA-001/002, EXP-001/002, CAP-007/009, OPEN-005; [Schema](../../RESEARCH_DATA_SCHEMA.md) §B/G/H; [평가 체계](../evaluation_framework_20261029/README.md).
