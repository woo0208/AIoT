# Stage 6 정식 실행 인계

작성일 **2026-11-05**, 기준 `ce3bfba` / `feat/aiot-stage5e-d455-readiness`.
**현재 상태: HOLD / PARTIAL_WITH_BLOCKERS / 실행 승인 아님.** [묶음 D 검토](STAGE_5E_BUNDLE_D.md)의 B1~B6 및 아래 gate가 남는다. 정식6-class 모델은 아직 없고 UI는 합성 구조 검증 상태다.

이 문서에서 **6단계는 신규 정식 개발2명 촬영→LOSO→선정→artifact 동결**, **7단계는 외부 독립4명 최종 검증→실제6 UI/실제 자세 성능→논문화**다. 과거 `STAGE_06_CLOSURE_STAGE_07_PREPARATION_20261028.md`의 파일럿 단계 번호를 재해석하거나 되돌리는 문서가 아니다. 모든 아래 작업은 미래 순서이며 이번에 수행한 것은 문서/기존 증거 검토와 무학습 합성 회귀뿐이다.

## 1. 정식 실행 전 반드시 충족할 조건

권위는 `AGENTS.md`, Research Master §18/24~28, Decision Log EXP-002~007/FEAT-010/CAP-007~009, `RESEARCH_DATA_SCHEMA.md`, `docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md` 및 EXP-006/007 후속 절이다. 과거 초안은 현재 승인서가 아니다.

| gate | 현재 상태 | release에 필요한 기록 |
|---|---|---|
| IRB | **HOLD/승인 원문 미확인** | 공식 승인번호·version·유효기간, 적용 protocol/동의서 원문, 신규6자세/3+2세션/횟수/부담·영상 처리 범위 |
| 동의·공유 | 미확인 | 참가자별 서면동의, RGB/Depth/랜드마크·모델·논문 예시/제3자·협업 공유 범위, 보관/접근/철회 절차 |
| Foundation/운영 | **CAP-007 EXECUTION DEFERRED** | CAP-009의 별도 실행 승인·감사코드 pin/환경·사전 검증·registry 승인 gate 해결; EXP-002가 요구하는 Patch8 완료/EXPERIMENT_PROTOCOL freeze. 실제 승인 전 registry/execution_id 만들지 않음 |
| SOP | **B1 BLOCKED** | 2026-10-29 9 hold SEQ_FULL 초안과 최신5E3의6 hold 외부seq 중 승인 원문에 맞는 운영 절차·hold/prep/거리/휴식/세션간격 명시. capture 상수/forward gate 임의 변경 금지 |
| 프레임 품질 | **B2 BLOCKED** | 전달 frameset support/coverage와 child reuse의 관계를 보존해 실제 장치/운영 조건에서 적격성 release 검토. Headless 미승인 유지 |
| 재현/실행 bundle | 실제6 미완료 | dependencies/code/rules/environment hash pin, ignored LR factory 보관, raw→feature→evaluation adapter의 실제 provenance/에러 처리 확인 |
| 선정 경계 | **B6 BLOCKED** | pairwise epsilon 연쇄 동점의 비추이적 순위 반례에 대해 EXP-006을 보존한 승인 해석/별도 수정·회귀 완료. 실제 연구 결과의 오류 관측은 아님 |

IRB 승인만 확인하고 다른 gate를 건너뛰지 않는다. 이 인계 문서가 IRB/운영 release 또는 새 연구 결정을 대신하지 않는다. OPEN-005 전체 DEFERRED는 유지하며 잔여 항목을 승인된 범위별로 관리한다.

## 2. 단계별 실행 순서

각 완료 증거의 날짜·담당자·승인 문서/hash·입력/출력 identity를 새 기록에 남긴다. 미실행은 NOT_RUN, 미측정은 NOT_MEASURED다.

| 순서 | 단계 | 작업/완료 근거 |
|---:|---|---|
| 1 | 6 진입 전 | IRB 공식 승인·적용 원문/version 및 유효기간 대조 |
| 2 | 6 진입 전 | 참가자 동의·데이터/영상 공유 범위·라벨 QA/접근권한 확인 |
| 3 | 6 진입 전 | CAP-007/009·EXP-002/Foundation 및 별도 운영 release 조건 충족 |
| 4 | 6 | pilot 결과/원본은 별도 보관, 정식 신규자료와 입력 manifest 분리 |
| 5 | 6 | 신규 빈 dataset/run namespace·실행 상태/계획/roster를 준비. 이전 연구자료 삭제/재명명/재분류로 초기화하지 않음 |
| 6 | 6 | D455/USB/firmware/profile/intrinsics/scale·위치/각도/높이·거리/조명·저장공간/clock/모델lock 확인 |
| 7 | 6 | 참가자별 S1 round1 첫 목표P0를 고정 calibration key로 지정 |
| 8 | 6 | 승인된 S1 3회/S2 2회 신규 정식 촬영, 실패/중단 원본도 보존 |
| 9 | 6 | 참조P0는 F0/F_cal 학습·평가와 모든 공통 비교에서 제외 |
| 10 | 6 | 검증된 유지 종료 `[end−10초,end)`만 분석, prep/transition 제외 |
| 11 | 6 | confirmed·기술 적격·공동 support/coverage·구간 교집합·제외사유 확인 |
| 12 | 6 | 결과 열람 전 동결한 정확8조합 평가 준비/실행 |
| 13 | 6 | 개발2인 LOSO RF seeds0/1/2, LR B0 결정적1회, seed별 OOF/참가자/세션별 결과 저장 |
| 14 | 6 | 동결된5후보/순위·1e-12 동점 규칙으로 개발 최종 후보 선정; 클래스 부족 시 중단 |
| 15 | 6 종료 | 개발자료만의 최종 모델/전처리·특징·seed·코드/모델/평가 artifact hash 동결·검토 |
| 16 | 7 진입 | freeze gate와 별도 승인 통과 후에만 외부4명 독립검증 입력 접근 |
| 17 | 7 | 동결6-class 실제 모델을 UI producer에 연결, class/feature order와 상태/age 확인 |
| 18 | 7 | 승인된 실제 자세 입력으로 FPS/지연/자원/안정성 검증; 외부 평가 성적으로 모델 재선정 금지 |
| 19 | 7 | 연구 결과/혼동/비용/제외/표본·세션·측정 한계를 논문에 보고 |

7단계 UI 구현·성능검증은 독립검증의 모델/특징/seed를 바꾸는 근거가 아니다. inference 의미를 바꿔야 하는 결함이면 동결 위반으로 중단하고 외부자료 재사용 가능성부터 별도 검토한다.

## 3. 데이터셋·메타데이터 준비

- 개발2명은 기존 파일럿 참여자이지만 **승인 후 새로 촬영**한다(이번 사용자 확정). pilot을 formal로 승격하지 않는다. 외부4명은 pilot 탐색/개발과 사람 단위로 독립이며 최종 검증 전 봉인한다. ID만 다르게 발급해 독립성을 주장하지 않는다.
- 동일 사람의 S1/S2/반복/프레임은 한 분석 role에 묶는다. 새 formal namespace와 보류검증 집단은 데이터 관리자가 구분하고, 개발 evaluator는 외부 파일을 열 수 없는 접근 정책을 사용한다. 동일 승인 정식촬영의 train/heldout 분석 구분을 schema의 `dataset_role=external`로 자동 변환하지 않는다(`FORMAL_EVALUATION_PLAN.md` §2). 같은 장소/protocol의 독립참가자 검증을 기관·환경까지 다른 외부일반화로 과장하지 않는다.
- `recording_id`, `analysis_run_id`, canonical planned round 문자열1~5, session, participant alias, ordered target step, capture/analysis source hash, markers/hold-end 시간축, model lock, 장치/설치 metadata를 연결한다. 개인정보/실명 대응표는 동의·접근 규정에 따라 별도 보관한다.
- `frames-schema/1.0.0`, `summary-schema/1.0.0`, RF lineage, selection-event/dataset-manifest 계약을 유지한다. 선택정책 version/포함·제외/기술 QA와 scientific inclusion의 책임을 승인 protocol에 명시한다. 보존된 실패를 삭제하지 않는다.
- plan/order/reference key/review states/각 family support·입력수/coverage/윈도/공통키/hash를 결과 보기 전에 pin한다. source hash에는 ignored `analysis/lr_feature_comparison_20261029_1a6c42/baseline.py`도 포함한다. 파일이 없으면 현재 formal6은 LR metrics/factory 사용에 실패하므로 같은 commit만으로 실행가능하다고 가정하지 않는다.
- 시작 상태는 NOT_RUN으로 남기고 승인된 새 output directory를 사용한다. 분석 폴더·기존 results·artifacts를 지우는 ‘초기화’는 하지 않는다. registry/execution_id는 이번에 발급하지 않는다.

## 4. 2인 개발 촬영 및 P0 calibration

원문 대조: `analysis/formal6_capture_design_20261029_4d9f21/CAPTURE_PROTOCOL_DRAFT.md` §2/4의6자세×5회·S1=3/S2=2, EXP-003의 참조 제외 상한, 최신 `STAGE_5E3_READINESS.md`/`development_plan`이 수량상 일치한다. 초안 전체의 IRB 승인이나 기존9 hold를 그대로 실행할 권한은 아니다.

| 개발 목표 | 1명 | 2명 |
|---|---:|---:|
| S1: 자세당3구간×6 | 18 | 36 |
| S2: 자세당2구간×6 | 12 | 24 |
| 촬영 목표 합 | 30 | 60 |
| 첫 S1 P0 참조 제외 | 1 | 2 |
| 결측·부적격 전 공식 후보 상한 | **29** | **58** |

참조 제외 후 예정 class support는 1명 `[4,5,5,5,5,5]`, 2명 `[8,10,10,10,10,10]`이다. 목표/최대치이며 실제 유효 수가 아니다. 기술/라벨/시간/결측 제외는 이보다 감소시킨다. 기존 full sequence의 복귀5초 upright는 추가 P0 표본으로 세지 않는다.

촬영 전 승인 SOP에서6 hold 외부seq를 채택하는지, 자세별 명시 hold초6개(각>=10), prep/거리·전방 안내·휴식·세션간격·장면/카메라 위치를 확정한다. 현재 `development_plan`은 P0→P1→P2→P3→P4→P5, S1 round1~3/S2 round4~5, `native_request`는6 hold/13marker를 요구한다. 기존 SEQ_FULL 초안과 다름을 숨기지 않는다. `record_phase(...,seq,...)` 인터페이스 존재는 승인된 촬영 workflow 전체가 완성됐다는 증거가 아니다. production face-only8~12cm gate/SEQ_CORE/FULL을 고치거나 생략해 대응시키지 않는다.

첫 S1 목표P0 key는 값/예측을 보기 전에 지정하고 S2에서도 **같은 참조**를 사용한다. 촬영 거리 안내의 직전 upright와 모델 feature 보정 참조는 별개다. 후속 P0/다른 사람/평가구간으로 baseline을 교체하지 않는다. F0/F_cal 참조와 목표는 각각 공동유효>=30, coverage>=50%, 참조 면적>0/기준5개 finite를 요구한다. 부분 보정 실패도 해당 참가자 F0/F_cal을 차단하며 H 후보 자체 적격성은 유지한다.

추가 재촬영은 **계획 외0회**다. 예측 오류를 보고 재촬영하지 않고 기술실패·ambiguous/mismatch/not_reviewable도 원본/사유로 남긴다. 계획된 촬영 자체의 횟수/부담과 IRB 허용 범위는 사전 확인한다. 재촬영 규칙을 바꿔야 한다면 후속 결정/IRB 재확인 전 중단한다.

## 5. 평가 및 모델 선정

정확8조합: baseline F0+RF M0 / F_cal+RF M0 / H5+RF M0; candidate H9+RF M0 / H9+RF M1 / H9+RF M2(λ0.5) / H9−F9+RF M0 / H9−F9+LR B0. 차원6/6/5/9/9/9/8/8, 실제 열 순서는 [묶음 D §4/6](STAGE_5E_BUNDLE_D.md)의 source 정의다. F0/F_cal 두6열의 마지막 A는 모두 면적비이며 F_cal의 첫5개만 참조차감이다. H5는 F1-5 hip기반 feature와 다르다.

1. 동일 sensor 시간축/종료 근거의 마지막10초 반개구간만 사용한다. 검증된 hold<10초·종료 근거 부족은 unprocessed, 창 이동/host 대체/프레임 보충 없음.
2. F0 내부 공동 원시 support에서 원시 중앙값 후 특징 계산. H는 공동9 유효프레임에서 scalar median/F3 directed circular mean. 현재 H5/H9−F9도 같은 공동9 support를 투영한다. 특징군 전체에 같은 raw-frame 교집합을 강제하지 않는다.
3. confirmed 및 기술 적격인 동일 구간만 사용한다. 선정5개는 H9/H9−F9 공통 표본, 8개 직접비교는5특징군 공통 표본을 별도로 저장한다. 표본이 다르면8비교의 후보 결과도 그 표본에서 별도로 계산한다. 비교 점수로 원래 선정범위를 바꾸지 않는다.
4. 개발2인 LOSO에서 같은 사람의 두세션은 함께 holdout. RF500 trees/max_features2/seed0,1,2, M1/M2의 MDI/rank weights는 train fold만. LR B0의 StandardScaler도 train fold만 fit한다. B0=C1/L2/lbfgs/tol1e-4/max_iter10000/intercept/class_weightNone, 1회로 보고한다.
5. 각 참가자/fold의 필수 클래스 부족이면 fit 전 자동 선정 BLOCKED. 참가자·fold·클래스를 사후 삭제하거나 외부4명으로 보충하지 않는다. actual support0 Recall=N/A, INCOMPLETE, 공식6 Macro-F1 미산출. 고정6 zero_division0 진단점수는 별도 상태로 남긴다.
6. RF seed별 두 fold OOF를 pool해 지표를 계산한 뒤 seed 요약한다. Macro-F1→P0 Recall→P1 Recall→P5 Recall→Accuracy→적은feature수→위 candidate순서를 적용한다. 반올림 전 abs차<=1e-12가 동점이다. baseline은 선정 순위에 넣지 않는다. 현재 pairwise 구현의 연쇄동점 반례(B6)는 별도 승인 해석/수정·회귀 전 자동선정에 사용하지 않는다. 허용오차/우선순위를 임의 변경하지 않는다.
7. 선정은 개발자료만 사용한다. 결정적 LR을3 seed 결과로 복제해 독립 반복으로 세지 않는다. 새 seed/λ/C/특징/제외기준 탐색은 금지한다. 모든 비교·제외와 실제/예측support·6×6 CM을 선택적 누락 없이 저장한다.
8. 승인된 실제 실행 adapter를 통해 개발자료만 최종 refit/전처리·모델을 동결한다. 실제6 refit/serialization/독립추론 연결은 아직 NOT_RUN이다. `formal6_synthetic.py`는 합성 전용이며 실제 formal 실행기로 전용하지 않는다.

최종 동결에는 후보ID/class order/feature order·units/support 규칙, seed 전체, 모델파일/전처리/scaler, train participant/sample key/input hash, 설정·환경/의존성·code hash, 평가 rule 문서/hash, 비교/선정 결과 및 제외 audit를 포함한다. RF라면 승인seed0/1/2 artifact를 모두 보존하고 seed 하나를 성적으로 고르지 않는다. LR는 seed0 결정적 artifact다. `load_frozen_heldout`의 모델 존재/hash·settings·code pin 검사는 필요하지만 실제 학습자료/인물 독립성까지 증명하는 것은 아니므로 학습 audit/운영 검토도 필요하다.

## 6. 외부4인 독립 검증으로의 인계

**7단계 진입 조건:** IRB/동의·운영 gate 유지, 개발 선정 완료, 최종 model/feature/preprocessing/seed/code/model hash freeze와 검토 기록 완료. 외부4명 roster는 개발/pilot과 사람 단위로 독립임을 확인하고, 결과를 보기 전에 봉인한다. gate 통과 전 외부 feature/raw/예측·정답 분포를 개발에 제공하지 않는다.

외부 참가자 자신의 사전 지정 첫S1 P0는 F0/F_cal 특징용 허용 calibration 입력이며 해당 참조는 평가에서 제외한다. 다른 평가구간으로 보정하거나 외부자료로 scaler/model을 fit할 수 없다. 같은3+2회 protocol이 최종 승인된다면 외부120목표−참조4=최대116이지만 실제 적격분모는 따로 보고한다.

외부4명은 **최종 독립 검증에만** 사용한다. 모델 선택·feature 설계·hyperparameter tuning·seed 선택·보조모델 재선정에 사용하지 않는다. 성능이 낮아도 개발로 환류해 같은 외부자료를 다시 최종 검증이라고 부르지 않는다. 방법 변경이 필요하면 독립성 훼손/새 검증 계획을 별도 승인한다.

주 지표는4명 pooled6-class Macro-F1. seed별 예측에서 pooled지표 후 seed 요약, 참가자/세션별 보조지표·고정6 support/CM·P0/P1/P5 방향오류·INCOMPLETE를 함께 보고한다. 공식 유의성 검정 없음. 보조알고리즘 추가 실행은 이번 인계의 필수가 아니다.

## 7. D455/Headless/frame reuse 주의사항

2026-11-05 기존 **NON_FORMAL_ENGINEERING** 최종25초×2 저장 메타데이터를 이번에 대조했다. UI25.000초/Headless25.016초, 각365완료, 각각 raw→aligned child ID730/730일치, UI RGB0/Depth1 재사용, Headless RGB25/Depth23 재사용, 전체RGB-D쌍 반복0. 근거: `analysis/ENGINEERING_ONLY_C6_LIVE_20261105_170905/`의 frames journal/summary/performance 및 C6보고서 §15. H9미연결이라 최종6 분류 영향은 NOT_MEASURED다.

**SDK 수신 child 재사용 CONFIRMED / align ID 보존 해당범위 PASS / Headless 증가 인과 LIKELY / 정식 Headless NOT_APPROVED / 실제6 영향 NOT_MEASURED**를 유지한다. Headless를 정식 촬영 기본값으로 승격하지 않는다. UI에서도 재사용0을 보증하지 않는다.

품질 점검은 다음 경계를 구분한다.

- 실제 전달frameset/processed count와 센서별 고유 관측 수를 별도 기록한다. 메타데이터 동일성은 pixel동등성/실제 sensor 생성총수의 증명이 아니다.
- 기존 native계약은 한쪽 child가 같고 다른 쪽이 진행하는 전달을 보존한다. reuse 번호의 timestamp/domain/형식/크기/payload 변경, 역행/경계 불명확, 양쪽모두 동일인 완전재전달은 해당 native검증에서 차단한다. 현재 row index는 센서 신규 frame 번호가 아니다.
- 기존 coverage는 `해당 support 유효 전달입력수 / 창 실제 전달입력수`; 고유 RGBcoverage나 독립표본비율이 아니다. >=30개는30개 고유RGB라는 의미가 아니다. 과학적 입력품질 적격성 release에 이 관계를 명시한다. 변경이 필요하면 승인 후속결정 없이 denominator/N_min을 바꾸지 않는다.
- RGB 재사용이면 landmark는 재사용할 수 있으나 새Depth의 geometry는 매번 다시 계산한다. 과거H9 벡터 전체cache·source frame보간/삭제/임의중복제거로 결과를 개선하지 않는다.
- missing_rate는 검증된 동일스트림 번호의 내부간격만 허용하며 중복/리셋/출처 불확실이면 NOT_MEASURED. 상세분모/단위 미동결 상태에서 새 산식을 쓰지 않는다. nominal15FPS/row index/processed FPS/coverage를 누락률로 대체하지 않는다.
- QPC/monotonic/sensor timestamp를 교차 차감하지 않는다. 기존 Windows monotonic stage값의0ms는 연산비용0의 증거가 아니므로 정밀 분해는 별도 QPC sidecar를 사용한다. 실제 sensor-to-screen 지연은 UI제출 지연과 다르다.

실제6 UI에 연결할 때 기존 primary5 H9 artifact나 synthetic producer를 실제6 모델로 표기하지 않는다. 학습/비용 벤치마크 절차·기존 API/출력 스키마는 묶음 D §8을 적용한다. 승인 후 실제자세입력으로 FPS/지연·age/stale/insufficient/model unavailable·CPU/RSS/Private Bytes·종료/오류를 검증한다.

## 8. 실험 오류 발생 시 중단 기준

| 사건 | 처리 |
|---|---|
| IRB/동의/운영release 부재·만료·촬영범위 불일치 | 촬영/자료접근 시작 금지 또는 중단, 새승인 확인 |
| 승인SOP와 sequence/hold/gate/라벨/참조가 다름 | 중단; 원본/사유 보존, 임의 수정/추가 재촬영 금지 |
| 시간축/marker/종료/EOF·inventory/identity/hash 불일치 | 해당 분석 차단/unprocessed, host시간 대체/창이동/원본덮어쓰기 금지 |
| 첫S1 P0 부적격·부분보정실패 | F0/F_cal 해당참가자 부적격, 후속P0 대체 금지; H자체 결과와 공통비교 차단범위 구분 |
| 공동유효<30 또는coverage<50%·nonfinite | 해당family/구간 부적격/사유기록;0채움·보간금지 |
| 라벨 ambiguous/mismatch/not_reviewable | confirmed 비교에서 제외하되 참가자/계획/시도/실패를 보고서에서 삭제하지 않음 |
| 개발LOSO 필수클래스 부족 | 자동선정 중단/BLOCKED, 외부자료 보충금지 |
| 연쇄동점 순위해석 미승인/B6 미해소 | 정식 자동선정 중단; 결과를 보고 유리한 동점집합/정렬법을 선택하지 않음 |
| 외부평가 실제support0 | INCOMPLETE/Recall N/A/공식Macro-F1 미산출, 진단점수 분리 |
| frame reuse 계약/신규성 품질 문제 | 해당입력 검증/정식release 중단, 원인/경계기록, 임의dedup·headless승격 금지 |
| 모델/특징순서/전처리/코드hash·의존성·frozen manifest 불일치 | 추론/외부loader 진입 차단, 승인된freeze 복구/검토 |
| 런타임·cleanup·publication 오류/전원차단 | FAILED/INCOMPLETE·journal/원본 보존, 새run ID/출력으로만 재시도 승인검토 |
| 외부정보가 개발/선정에 유입 | 평가독립성 incident 기록·중단, 같은자료 재사용한 재선정 금지 |

동결 규칙을 변경해야 해결되는 문제는 **BLOCKER/변경승인 필요**로 올린다. 결과가 좋아지는 기준/표본/seed/threshold를 사후 선택하지 않는다. 과거 Decision Log를 재작성하지 않고 후속결정에 Supersedes/Clarifies/Resolves를 적용한다.

## 9. 연구 결과에 포함할 핵심 지표

- 개발2/외부4 분리, 참가자·세션·반복별 계획/시도/처리/적격/제외수·사유·참조key, 클래스 actual/predicted support, INCOMPLETE/NOT_MEASURED.
- 공식8조합 공통비교와5후보 선정scope별 sample key/hash·정확열순서·학습/시험fold·seed별6×6CM, Accuracy/Macro-F1/각class Precision/Recall/F1, P0/P1/P5 방향오류. absent class는 N/A 정책 유지.
- 외부4명 pooled6-class Macro-F1을 주지표, 참가자·세션별 점수와 seed요약을 보조로 보고. seed를 독립참가자나 유의성 근거로 쓰지 않음.
- 학습wall time/단일추론p50,p95/모델파일bytes/차원/특징추출시간, processCPU/RSS/WindowsPrivateBytes, warmup·반복·환경/hash/입력조건·계측오버헤드. before/after memory를 peak로 표현하지 않음.
- 실제자세 pipeline의 전달/처리/센서별고유FPS·frame reuse·coverage·host 지연·UI상태/안정성. H9미연결비인체FPS·synthetic timing을 실제6 모델 성능으로 쓰지 않음.
- 소표본2인개발/4인독립의 군집·세션/순서 교란, 파일럿반복사용/선택편향, F0원문재현한계, F8/F9중복의 알고리즘의존성, 실제Depth품질/누락률 미측정 한계를 명시.

## 10. 6단계 진입 승인 체크리스트

현재 아래 실제release 항목은 **미완료**다. 체크는 명시적 증빙 확인 후에만 한다.

- [ ] IRB 공식승인/적용문서/version/유효기간·6자세/3+2/부담 확인
- [ ] 개발2인 신규정식촬영 동의·pilot분리·외부4명 인물독립성/동의·공유/보관/접근 확인
- [ ] CAP-007/009 별도 실행조건·Foundation/Patch8/EXP-002·EXPERIMENT_PROTOCOL 동결 충족
- [ ] 승인SOP와6 hold 준비안/기존seq·gate/hold초·휴식·세션간격·라벨운영 대조완료
- [ ] D455/profile/설치/clock/metadata·저장공간/종료·실패보존 확인
- [ ] frame reuse와 전달기반30/50·coverage의 품질release 근거 확인, Headless 정식미승인 유지
- [ ] reference key/order/roster/구간역할·정식manifest·selection policy·비교scope 사전고정
- [ ] 실행의존성(LR ignored factory 포함)/코드/모델lock/환경hash 보관 및 해당adapter 검증
- [ ] B6 연쇄동점의 승인된 순위해석과 별도 최소수정/회귀 검토 완료
- [ ] actual6 평가/최종refit·동결artifact/독립추론 인계경계·오류처리 검토계획 확인
- [ ] 연구책임자가 실제 촬영/분석 범위의 운영release를 별도기록

이미 확인한 준비 근거는 공식8조합/열순서 검토, 이번 fit없는70합성회귀 PASS, 최종C6메타데이터 대조, 기존source/규칙 보존이다. 실제6 모델완료/실제연구성능/IRB승인 증거로 바꾸지 않는다. **5단계 현재판정 PARTIAL_WITH_BLOCKERS**, 정식6단계는 위gate 확인 전 시작하지 않는다. Commit/push 미실행.
