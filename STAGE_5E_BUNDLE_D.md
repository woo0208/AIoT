# Stage 5-E — 묶음 D 최종 통합 검토

검토일: **2026-11-05**. 기준 HEAD `ce3bfba`, branch `feat/aiot-stage5e-d455-readiness`.
범위: D-1~D-6 통합 read-only 연구/구현 검토, 저장 집계 결과의 산술 대조, 합성 구조 회귀, 인계 문서 작성. 새 촬영·연구 모델 fit·추론·정식 평가·모델 선정은 실행하지 않았다.

## 1. 작업 요약

**전체: PARTIAL_WITH_BLOCKERS.** 특징 수/열 순서와 공식8조합의 구현은 일치하며 추가 알고리즘 개발을 필수로 할 근거는 없다. 다만 F0/F_cal의 동일 조건 파일럿 수치가 없고, IRB만으로 해소되지 않는 Foundation·SOP·프레임 품질 실행 조건이 남는다. 이 문서는 새 연구 결정이나 실행 승인이 아니다.

| 항목 | 판정 | 의미 |
|---|---|---|
| D-1 | PARTIAL | 5개 특징군 정의/순서 확인. F0/F_cal 공정한 실증 비교는 NOT_MEASURED |
| D-2 | PASS | 기존 Depth 상관·Ablation 근거와 한계 정리 완료. 추가 실험 불필요/보류 구분 |
| D-3 | PARTIAL | 8조합/경계는 일치하나 epsilon 연쇄 동점의 순위 반례 발견. 자동 선정 전 명확화 필요 |
| D-4 | PASS | 기존 근거로 보조 모델 채택 필요성 판단 완료. 새 모델 추가 의무 없음 |
| D-5 | PASS | 기존 도구로 비용 측정 절차/출력/경계 명시. 정식 모델별 값은 NOT_MEASURED |
| D-6 | PARTIAL | 순서별 인계/중단 기준 작성 완료. 실행 release 조건 미충족 |

PASS는 해당 검토 완료를 뜻한다. 연구 효과/정식 측정 PASS나 IRB HOLD 해제와 다르다.

## 2. 시작/종료 Git 상태

시작에 `git status --short --branch`, `git log -5 --oneline`, `git diff --stat`, `git diff`, `git ls-files`, `git ls-tree -r --name-only HEAD`, 미추적 목록을 확인했다. 시작 tracked diff는 없었고 status는 `?? artifacts/`뿐이었다. 초기 Git 미추적 조회가 표시한 경로명 외 artifacts 내용은 열지 않았고 이후 상태 조회는 `:(exclude)artifacts`로 제한했다. ignore 설정과 `.pytest_cache/` 권한 warning은 기존 상태로 보존했다.

시작 log5: `ce3bfba` C6 기록 → `800faa3` headless/provenance → `ed22f0f` performance/묶음A → `35e7a46` formal capture/offline integration → `dfb8534` native sensor reuse 호환.

종료 HEAD/branch는 시작과 같다. 기존 tracked 수정은 **C6 보고서 후속 절 추가 1개**, 새 root 문서는 **이 문서와 STAGE_6_EXECUTION_HANDOFF.md 2개**다. 새 검토 증거는 ignored `analysis/READ_ONLY_STAGE_5E_BUNDLE_D_20261105/`에만 저장한다. stage/commit/push/reset/clean/mv 없음. 기존 C6 경로가 정상임을 ls-files/ls-tree로 확인했으므로 이동하지 않았다.

시작 tracked 161파일의 SHA-256을 pin했다. 종료 상세는 신규 폴더의 `start_state.json`, `end_state.json`; 기존 source/schema/결정 문서/진단 코드는 보존한다. C6 원문의 기존 본문을 바꾸지 않고 §15만 추가했다.

## 3. 사용한 기존 파일·실험 증거 목록

경로는 repository root 기준. ignored 분석 결과는 Git commit만으로 보관/재현됨을 보증할 수 없다. 아래 증거는 읽기 전용이며 신규 결과 JSON의 `input_sha256`에 실제 산술 대조 입력을 pin했다. 저장 결과의 날짜와 이번 재검토일을 구분한다.

| 근거 | 날짜/조건/구분 | 용도 |
|---|---|---|
| `AGENTS.md`, `docs/research/AIoT_RESEARCH_MASTER.md` §9/12/18/24~28 | 현재 연구 authority; 과거 snapshot은 후속 기록과 구분 | 범위/역할/수집 gate |
| `docs/research/RESEARCH_DECISION_LOG.md` EXP-002~007, FEAT-010, CAP-007~009; `RESEARCH_DATA_SCHEMA.md` §F/G/H | 결정/동결 계약; 실험 결과 아님 | 정식/외부 분리, 수치 규칙, lineage |
| `docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md`와 후속 EXP-006/007 절 | 2026-11-02 동결 | 최신 정식 평가 authority |
| `F0_FCAL_IMPLEMENTATION.md`, `FORMAL6_5D9_INTEGRATION.md`, `FORMAL6_5D10_SYNTHETIC_VERIFICATION.md`, `STAGE_5E3_READINESS.md` | 구현 선택/합성·비인체 준비 기록 | 계산식/참조/실행기 한계 |
| `STAGE_5E4_PERFORMANCE.md`, `STAGE_5E_BUNDLE_A.md`, `STAGE_5E_BUNDLE_C.md`, `STAGE_5E_C6_FRAME_REUSE_REVIEW.md` | 2026-11-04~05; 합성 또는 비정식 engineering | 계측/표시/프레임 문제 |
| `analysis/teammate_feature_ablation_20261029/{config.json,depth_add_one.json,depth_drop_one.json,summary.md}` | 결과 run_date 2026-10-30; P01/P02 24구간 6-class, LOSO, seeds0~4; EXPLORATORY | H5/H9/Depth 제거·추가 저장 결과 |
| `analysis/teammate_ablation_integration_20261101/INTEGRATION_REVIEW.md` | 2026-11-01 저장 결과 통합; EXPLORATORY | 동일 표본 확인/환경·hash 제한 |
| `analysis/h9/pilot_20261026/H9_feature_diagnostics_20261026.json` | 2026-10-26; 같은 24구간/2인 집계; EXPLORATORY | 기존 상관계수; 이번에 새 상관 분석 안 함 |
| `analysis/research_h9_algorithms_20261029_7c3e91/{PLAN.json,REPORT.md,results.json}` | 2026-10-29 04:05 UTC 실행; 24구간·2인 LOSO·seeds0~4; EXPLORATORY | RF/LR/SVM/KNN의 저장 혼동행렬 대조 |
| `analysis/lr_feature_comparison_20261029_1a6c42/{baseline.py,REPORT.md}` | 2026-10-29; A=H9/B=H9−F9/C=F1~F8+C3; EXPLORATORY | LR 생성기/특징 비교의 기존 근거 |
| `analysis/lr_fixed_comparison_20261029_b0r1w1/{REPORT.md,results.json}` | 2026-10-29 09:34 UTC; 같은24구간, B0/R1/W1; EXPLORATORY | LR 추가 설정의 근거 |
| `analysis/h9/stage6_20261028/REPORT.md`, `docs/research/STAGE_06_CLOSURE_STAGE_07_PREPARATION_20261028.md` | 2026-10-28; H9-v2, primary5, 20구간, seeds0~4; NON_COMPARABLE | M3-G 존재/기존 탐색 범위 |
| `analysis/formal6_capture_design_20261029_4d9f21/{CAPTURE_PROTOCOL_DRAFT.md,FORMAL_EVALUATION_PLAN.md,IRB_PROTOCOL_DIFF.md}` | 2026-10-29 DRAFT/미승인 | 3+2회·목표 수 원문 대조; 승인서 아님 |
| `analysis/ENGINEERING_ONLY_C6_LIVE_20261105_170905/{UI,HEADLESS}_frames/{frames.jsonl,summary.json}` 및 각 `_performance/performance.json` | 2026-11-05 08:09 UTC, H9 미연결 25초×2; NON_FORMAL_ENGINEERING | C6 최종 실제 메타데이터 검증 |

검토 source: `formal6_evaluation.py`, `rf_experiment.py`, `h9_m0.py`, `f0_fcal_features.py`, `f0_fcal_evaluation.py`, `f1_features.py`, `f1_sample_aggregator.py`, `posture_geometry.py`, `stage5e_native_h.py`, `stage5e_readiness.py`, `model_benchmark.py`, `performance_output.py`, `engineering_ab.py`, `probe_timing.py`, `probe_diagnostics.py`, `frame_provenance.py`, 관련 테스트. 원본 RGB/Depth·외부4명 자료·participant CSV loader는 실행/접근하지 않았다. DATA-002의 pilot 개발 역할, 각 기존 PLAN의 승인된 탐색 범위와 위 보고서의 집계 근거를 확인한 뒤 **기존 집계 JSON만** 산술 대조했다. IRB 승인 원문이 확인됐다는 주장은 하지 않는다.

## 4. D-1 특징군 비교표

### 4.1 실제 입력 열과 정의

F0/F_cal 열 순서는 `f0_fcal_features.FEATURE_NAMES` = **xc, yc, theta1_deg, theta2_deg, theta3_deg, A**. RGB bbox 중심을 `(xc,yc)`, 해부학적 좌/우 어깨를 `(xl,yl)/(xr,yr)`, bbox 면적을 `a`, 고정 P0 면적을 `a0`라 한다. 원 영상 픽셀/+y 아래 기준이다.

| 순서 | F0 (6열) | F_cal (6열) |
|---|---|---|
| 1 | bbox 중심 xc (px) | xc−xc0 |
| 2 | bbox 중심 yc (px) | yc−yc0 |
| 3 | theta1=theta2+theta3 (deg) | theta1−theta1_0 |
| 4 | theta2=degrees(atan((xc−xl)/(yc−yl))) | theta2−theta2_0 |
| 5 | theta3=degrees(atan((xc−xr)/(yc−yr))) | theta3−theta3_0 |
| 6 | A=a/a0 (무차원) | **동일 a/a0**, A−1 아님 |

분모0 각도, nonfinite·boolean 수치·유효하지 않은 면적은 None. 공식 준비 경로는 F0 필요 관측이 같은 프레임에서 유효한 공동 support의 **원시 입력 중앙값 후** 위 식을 계산한다. `segment_features` 단독의 열별 집계와 정식 `prepare_samples` 경로를 혼동하지 않는다. 첫 S1 P0의 기준5개/양수 면적, 참조/목표 각각 >=30·>=50%가 필요하다. 실패하면 해당 참가자 F0/F_cal 모두 부적격이며 후속 P0 교체/0 채움/보간 없음. F0도 면적 때문에 P0가 필요하다. RGB 2D 입력이며 Depth 수치나 신체너비로 정규화하지 않는다.

H 계열의 실제 공통 순서는 `f1_sample_aggregator.H9_FEATURE_NAMES`다. 아래의 짧은 이름 앞에는 실제로 `hipless_f1_candidate_`(1~5) 또는 `hipless_f2_candidate_`(6~9)가 붙는다. `S`=양 어깨 중점, `W2`=2D 어깨거리, `E`=양 눈 중점, `T`=턱, `H`=양 눈/양 귀/코/턱 6점의 평균, `C`=흉부 ROI 중심 3D, `N`=코 3D, `W3`=3D 어깨거리다.

| 열 | 실제 이름의 suffix | 정의/입력/단위 |
|---|---|---|
| F1 | head_center_dx_sw | (H.x−S.x)/W2; RGB 2D, 무차원 |
| F2 | head_center_dy_sw | (H.y−S.y)/W2; RGB 2D, 무차원 |
| F3 | face_axis_tilt_deg | degrees(atan2(T.x−E.x,T.y−E.y)); 영상 아래축 기준 방향각 |
| F4 | ear_eye_dy_sw | (양 귀 중점.y−E.y)/W2; RGB 2D, 무차원 |
| F5 | nose_chin_distance_sw | 코–턱 2D 거리/W2; RGB 2D, 무차원 |
| F6 | chest_depth_m | C.z; aligned Depth+intrinsics/scale, m |
| F7 | chest_forward_from_shoulders_m | 3D 양 어깨 중점.z−C.z; m |
| F8 | nose_forward_from_chest_m | C.z−N.z; m |
| F9 | nose_forward_from_chest_sw3d | F8/W3; 무차원 |

| 특징군 | 열 수/모델 순서 | 참조/정규화·결측 | 비용과 비교상 의미 |
|---|---|---|---|
| F0 | 6, 위 F0 순서 | 첫 S1 P0 필요; A 비율만 정규화 | bbox/어깨 검출·공동 support·원시 중앙값·각도 |
| F_cal | 6, 같은 순서 | 첫5개 참조 차감, A 유지 | F0 계산 공유+차감; 별도 모델 가설 |
| H5 | 5, F1~F5 | P0 불필요, W2/방향각; 현재 공식 bridge는 **공동9 support** | 2D 열만 학습하나 현재 입력 준비는 Depth 적격성에도 의존 |
| H9 | 9, F1~F9 | P0 불필요, W2/W3·m·deg 혼합 | align/Depth sampling/ROI/SDK deprojection/집계 추가 |
| H9−F9 | 8, H9 첫8열 | P0 불필요, **공동9 support 그대로** | 입력 열 제거이며 F9 계산·Depth 비용 제거 구현 아님 |

H scalar 8개는 frame feature 중앙값, F3은 `[-180,180)` directed circular mean이다. 결측 관측은 None; 공동9 유효 >=30 및 전체 실제 입력 대비 coverage>=0.5, 원형 평균 미정의도 차단한다. 2D/3D 거리의 기존 수학적 guard(예: >1e-6)와 ROI 유효 pixel>=10을 바꾸지 않았다. H5/H9−F9를 독립 support로 다시 집계하지 않았다. H 후보도 공통 평가에서는 참조 P0를 제외한다.

`f1_features.py`의 hip을 쓰는 F1-5 `(fs_x,fs_y,sh_x,sh_y,so_beta)`와 **H5는 다른 특징군**이다. H9-v2의 C3도 공식 H9의 F9가 아니다. `h9_m0.py`의 9열 H9 artifact는 **primary5 개발용**이며 6-class 공식 artifact로 재사용할 수 없다. RF는 raw 열, LR B0만 학습-fold StandardScaler를 거친 위 8열을 사용한다.

F0의 원 논문 각도 좌우/해상도/면적 참조·집계 모호성은 `F0_FCAL_IMPLEMENTATION.md`에 명시돼 있다. 현재 코드의 명시적 구현과 EXP-004 이후 평가 경로는 확인했지만 원 논문 실험의 완전 재현으로 주장하지 않는다. legacy `rf_experiment.load_ours/relative`는 crop/oval/참조 정의도 달라 수치를 새 F0/F_cal에 옮길 수 없다.

### 4.2 기존 파일럿 수치 — 정식 성능 아님

아래는 **EXPLORATORY** 2인(P01/P02)·24구간·6-class·2방향 LOSO(각 train12/test12), seeds0~4, RF500/max_features2, 기존 공동9 support(3,613프레임), PREP/TRANSITION 제외 조건이다. 첫 P0도 포함한 과거 집합이며 정식 참조 제외/신규 촬영/seed0~2와 **NON_COMPARABLE**하다. 각 seed의 24개 OOF 혼동행렬에서 점수를 계산한 뒤 seed 평균을 냈다. 같은 자료의 복사/재현을 추가 표본으로 세지 않는다.

| 특징·모델 | Accuracy % | Macro-F1 % | P0 Recall % | P1 Recall % | P5 Recall % | 출처 |
|---|---:|---:|---:|---:|---:|---|
| F0 RF M0 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | 같은24구간 재현 입력/평가 없음 |
| F_cal RF M0 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | legacy relative와 혼용 금지 |
| H5 RF M0 | 62.50 | 56.88 | 25.00 | 0.00 | 100.00 | depth_add_one.json baseline |
| H9 RF M0 | 78.33 | 75.72 | 45.00 | 25.00 | 100.00 | depth_drop_one.json baseline; ALG M0와 일치 |
| H9−F9 RF M0 | 82.50 | 80.92 | 45.00 | 50.00 | 100.00 | depth_drop_one.json H9-F9 |
| H9−F9 LR B0 | 87.50 | 86.84 | 50.00 | 75.00 | 100.00 | lr_fixed…/results.json B0 |

위 H 세 구성의 표본 조건 정합은 기존 통합 보고서에 있으며 이번에는 저장 CM의 산술만 재검산했다. 팀원 Python3.14.4/NumPy2.5.0과 ALG Python3.12.10/NumPy2.5.3 등의 환경이 달라 현재 source로 완전 재현했다는 주장은 하지 않는다. 기존 통합 검토가 기록한 config CRLF/LF hash 차이 및 일부 source hash 불일치도 남아 있다. 이 결과로 formal 순위/튜닝을 확정하지 않는다.

혼동행렬도 실제 확인했다. 행/열은 P0~P5, 아래는 **5 seed 합계(120회 반복 예측; 독립 n=120 아님)**다. seed별 CM과 재계산 전정밀도 점수는 `saved_evidence_review.json` 및 원 JSON에 있다. 표의 Macro-F1은 이 합계 CM의 F1이 아니라 seed별 F1 평균이다.

```text
H5 M0:    [5,0,10,0,0,5]; [0,0,10,0,0,10]; [10,0,10,0,0,0];
          [0,0,0,20,0,0]; [0,0,0,0,20,0]; [0,0,0,0,0,20]
H9 M0:    [9,9,2,0,0,0]; [7,5,0,0,0,8]; [0,0,20,0,0,0];
          [0,0,0,20,0,0]; [0,0,0,0,20,0]; [0,0,0,0,0,20]
H9-F9 M0: [9,5,6,0,0,0]; [5,10,0,0,0,5]; [0,0,20,0,0,0];
          [0,0,0,20,0,0]; [0,0,0,0,20,0]; [0,0,0,0,0,20]
LR B0:    [10,5,5,0,0,0]; [5,15,0,0,0,0]; [0,0,20,0,0,0];
          [0,0,0,20,0,0]; [0,0,0,0,20,0]; [0,0,0,0,0,20]
```

연구상 F0→H5는 좌표 원점/정규화뿐 아니라 중심 정의·각도·면적도 달라 단일 요인의 개선 실험이 아니다. H5→H9는 같은 support에서 Depth4열의 추가 가치를 질문할 수 있지만 max_features=2의 특징 후보율도 달라진다. M0/M1/M2는 모델 축, H9/H9−F9는 표현 축, LR B0는 별도 파이프라인 비교로 해석한다. 소표본 탐색 결과를 인과 효과나 일반화 성능으로 확장하지 않는다.

## 5. D-2 F6~F9 Ablation 검토

F6은 절대 흉부 거리라 카메라 배치/체형/세션 교란 가능성이 있다. F7은 어깨 대비 흉부, F8은 흉부 대비 코의 전방 차이로 P0/P1/P5 분리 질문과 연결된다. F9는 같은 F8을 어깨 3D 크기로 정규화한 표현이다. 이는 자세별 기여 **가설**이며 임상 자세/6-class 실제 기여가 검증됐다는 뜻은 아니다.

흉부 ROI는 어깨 국소좌표에서 아래0.35W2, 반폭0.25W2/반높이0.15W2이고 유효 양수 finite Depth pixel>=10의 median×scale을 사용한다(`sample_hipless_chest_roi`). ROI·코·양 어깨를 SDK로 deproject한 뒤 위 F6~F9 식을 적용한다. 결측/invalid depth·landmark·W3 실패는 None과 공동 support 감소로 전파된다. F8/F9는 코/흉부 오차를 공유하고 F9는 W3 오차도 추가로 받는다. 원시 Depth나 실제 측정오차 크기는 이번에 평가하지 않았다.

저장 diagnostics의 Pearson r(24구간, 2인; 2026-10-26):

| 쌍 | r |
|---|---:|
| F6–F7 | 0.803316124 |
| F6–F8 | −0.736662287 |
| F6–F9 | −0.730466539 |
| F7–F8 | −0.936811678 |
| F7–F9 | −0.928178818 |
| F8–F9 | 0.998188649 |

F8–F9는 P0/P1/P5 12구간에서0.994171396, P01/P02 각12구간에서0.999050831/0.999089504다. 이는 **기존 저장 상관값 인용**, 새 raw/feature 재계산이 아니다. 2인 군집·작은 표본·자세 간 차이가 상관을 지배할 수 있고 참가자/자세 내 일반화를 보증하지 않는다. frame 단위 F9를 집계하므로 구간 F8/구간 W3와 무조건 같지 않다.

기존 M0 제거 결과를 저장 CM으로 재검산했다(동일 탐색24구간·seeds0~4):

| 조건 | Accuracy % | Macro-F1 % | P0/P1/P5 Recall % | 범위/후속 판단 |
|---|---:|---:|---|---|
| H9 | 78.33 | 75.72 | 45/25/100 | 공식 후보 |
| H9−F9 | 82.50 | 80.92 | 45/50/100 | **A: 공식 후보 간 비교**, 그대로 유지 |
| H9−F6 | 76.67 | 73.10 | 40/20/100 | **B: 보조 탐색만**, 추가 정식 실험 HOLD |
| H9−F7 | 72.50 | 68.15 | 25/10/100 | B; F7 질문은 기존 결과로 보고, 추가 HOLD |
| H9−F8 | 77.50 | 74.73 | 40/25/100 | B; F9와 대체성 검토 근거, 추가 HOLD |

기존 H5+F6/F7/F8/F9의 Accuracy/Macro-F1도 각각62.50/60.10, 68.33/66.92, 65.00/62.65, 58.33/54.39%로 저장 CM과 일치했다. 조합마다 주효과/상호작용 및 RF 후보추출 확률이 섞이므로 가산 기여도로 해석하지 않는다. H9−F9의 M0 개선은 모든 참가자에서 같은 방향이 아니며 기존 LR A(H9)와 B(H9−F9)는 예측이 같았다(기존 통합 보고서). F9가 보편적으로 해롭거나 LR이 F9를 쓰지 않았다는 결론은 불가하다.

추가 H9−F6/7/8, add-one, MDI·상관 재탐색은 **현재 불필요**, 정식 전 별도 질문/승인이 생길 때까지 HOLD다. 기존 결과로 기여/중복 질문을 이미 설명할 수 있고, 1 fold 학습12개로 제거 조합을 늘리면 선택 편향과 다중 비교만 커진다. 새로운 permutation/상관 임계값·feature selection을 도입하지 않는다. H9−F9의 연산 감소는 모델 입력1열 감소로 제한하며 공유 geometry/Depth 추출은 계속 실행된다. 실제 비용 차이는 NOT_MEASURED다.

## 6. D-3 공식8조합·평가 설계 검증

`formal6_evaluation.BASELINES` 3개 + `CANDIDATES` 5개는 정확히 다음과 같다. 추가 보조 모델은 없다.

| 역할 | ID | 특징/열 | 모델 |
|---|---|---|---|
| baseline | RF_M0_F0 | F0/6 | RF M0 |
| baseline | RF_M0_F_cal | F_cal/6 | RF M0 |
| baseline | RF_M0_H5 | H5/5 | RF M0 |
| candidate1 | RF_M0_H9 | H9/9 | RF M0 |
| candidate2 | RF_M1_H9 | H9/9 | RF M1 |
| candidate3 | RF_M2_H9 | H9/9 | RF M2 λ=0.5 |
| candidate4 | RF_M0_H9-F9 | H9−F9/8 | RF M0 |
| candidate5 | LR_B0_H9-F9 | H9−F9/8 | LR B0 |

| 동결 항목 | 실제 코드/검토 결과 |
|---|---|
| 개발2인 LOSO | `_roster` 정확히2 ID, heldout subject 단위 `train=~test`. S1/S2는 같은 사람에 묶임 |
| RF | SEEDS=(0,1,2), TREE_COUNT=500, max_features=2. M0 split_w=None; M1 학습-fold MDI 양수 가중 입력, M2 같은 가중치로 split 점수 변경 |
| rank weight | FEAT-010 p=9 `[6,4,3,3,3,1,1,1,1]/23`; MDI 동점 낮은 열 index 우선; p=8 weighted 후보 없음 |
| LR B0 | C=1/L2(l1_ratio0)/lbfgs/tol1e-4/max_iter10000/intercept/class_weight=None, deterministic 1회; scaler는 학습 fold만 fit |
| 선정 표본 | H9/H9−F9의 구간 key 교집합; 기준선 실패가 후보 선정을 축소하지 않음 |
| 8조합 직접 비교 | 5개 특징군 공통 구간 교집합. 선정 표본과 다르면 후보5도 이 교집합으로 별도 계산, 비교 결과로 선정 대체 안 함 |
| P0·시간·적격성 | 지정 참조 train/test 제외, verified 10초 window·S1/S2·confirmed·finite/정확 열 수 검사. >=30/50%와 실제 종료−10초 반개구간은 upstream F0/H 준비 경로 책임 |
| 불충분 support | 참가자별 필수 클래스 부족 시 fit 전에 BLOCKED; fold/사람/클래스 삭제나 외부 자료 보충 없음 |
| 지표 | 고정6 CM/P/R/F1/support, 실제support0 Recall/F1=None(N/A), INCOMPLETE, 공식 Macro-F1=None. zero_division0 진단값 분리; 빈평가 Accuracy도 None |
| 요약 | seed별 두 fold OOF pool 후 seed 평균, participant/session별 별도; deterministic LR을 3개 독립 반복으로 세지 않음 |
| 선정 | Macro-F1→P0→P1→P5 Recall→Accuracy→적은 특징수→위 후보 순서. 원점수 abs 차<=1e-12 동점, N/A 차단. baseline은 순위 제외 |
| 외부 경계 | 개발 roster 외 row는 수치 접근 전에 거부. `load_frozen_heldout`는 최종 settings/code/model/manifest hash와 개발2/외부4 ID 불겹침 확인 후 lazy loader 호출 |

최종 주 지표는 외부4명 **pooled 6-class Macro-F1**이며 개발 점수는 모델 선정용이다. 참가자별 F1 평균·seed 합산 CM F1과 혼용하지 않는다. 정식 유의성 검정은 하지 않는다.

구조적 사후 선택 방어는 고정 후보/seed/순위, fit전 support 차단, 학습-fold 전처리, 외부 lazy gate로 준비돼 있다. 다만 아래 B6 순위 경계는 미해결이다. Python API가 운영자의 결과 열람/거짓 roster/위조 eligible를 막는 보안 경계도 아니다. 결과 열람 전 입력 manifest·비교집합·참조·계획·규칙/source hash를 봉인하고, 모든 seed/fold·제외를 저장하며, 외부4명을 파일 접근권한으로 격리해야 한다.

### 실행 전 차이/영향/차단/해결책

| ID | 원인/차이와 영향 | 차단 여부/정식 전 해결 |
|---|---|---|
| B1 | `CAPTURE_PROTOCOL_DRAFT.md`는 기존9 hold SEQ_FULL/P5 선행/복귀P0를 재사용하는 초안. 후속 `STAGE_5E3_READINESS.md`/`development_plan`은 P0~P5 6 hold 외부seq/명시 유지시간, `native_request`는13 marker만 수용. 초안의 S2 참조 문장도 이후 EXP-003/004의 고정 S1 참조와 다름 | **운영 release BLOCKER**. 최신 EXP 고정참조를 유지하고 승인 IRB/SOP가 어떤 sequence·유지/휴식·전방 안내를 허용하는지 대조/명시. 필요 변경은 승인 기록, SEQ_CORE/FULL/forward gate 임의 수정 금지 |
| B2 | current native/readiness는 전달 frameset을 입력/coverage 분모로 정의하고 상대 child 진행 시 재사용을 보존함. C6는 live child 재사용/Headless 증가 확인. 유효30개가 독립 신규 RGB30개를 보증하지 않음 | **정식 입력 품질 release BLOCKER**. 기존 정의대로 입력은 보존하고 raw/aligned ID·고유 RGB/Depth·coverage/support를 함께 QA. 과학적 적격성 보증/불충분 근거를 승인 전에 검토. 고유 기준으로 정의를 바꿔야 하면 후속 연구 결정 필요. 임의 dedup/보간 금지 |
| B3 | EXP-006은 missing_rate 세부 분모/단위를 확정하지 않음. current F0/Performance도 NOT_MEASURED; 센서 반복 있음 | 누락률 수치/그 수치에 의존한 적격 판정은 **차단**. 불확실 시 NOT_MEASURED 유지. 수치가 필수면 결과를 보기 전 상세 명세 승인; gap/nominal FPS로 대체 금지 |
| B4 | LR factory가 ignored `analysis/lr_feature_comparison…/baseline.py`에 의존. 현재 로컬에는 있으나 Git만 배포하면 부재 가능 | 재현/배포 gate. `code_hashes`가 이 파일도 pin하며 부재/불일치 시 진행 금지. 승인된 실행 bundle에 해당 dependency·환경·hash를 보존하고 gate 검사. 이번에 이동/리팩터링 안 함 |
| B5 | `formal6_synthetic.py`의 refit/serialization/외부 추론은 합성 고정 fixture 전용. `h9_m0.py`는 primary5. 실제6 모델/런타임 연결 완료 근거 없음 | 실데이터 refit/추론/UI 적격 주장 **차단**. 승인 이후 개발 단계에서만 audited adapter와 최종 모델/전처리를 동결. 합성 모델이나5-class artifact를 대체 사용하지 않음 |
| B6 | `rank_candidates`가 `cmp_to_key`에 pairwise epsilon 동점을 사용해 비교가 비추이적일 수 있음. 합성 API 점수에서 선정 후보보다 Macro-F1이 epsilon 이상 높은 후보가 뒤에 남는 반례 재현 | **정식 자동 선정 전 BLOCKER/명확화 필요**. EXP-006의 epsilon/우선순위는 보존하고 연쇄 동점 처리의 승인된 해석을 결과 보기 전에 확정한 뒤 별도 최소 수정/회귀 검토. 이번에 정책/코드 변경 안 함 |

B6 재현은 **SYNTHETIC API STRUCTURAL ONLY**다. 앞3후보의 Macro-F1 입력을 `0.5`, `0.5+0.75e-12`, `0.5+1.50e-12`, Recall 입력을 각각0.9/0.8/0.7로 두고 나머지후보 점수를 낮게 두었다. 이는 실험 정확도/성능을 생성한 것이 아니라 비교 함수 입력의 반례다. A와B, B와C는 epsilon 동점이라 Recall로 A>B>C가 되지만 C는 A보다 Macro-F1 차이가 epsilon보다 커 C>A가 된다. 실제 반환은 A 추천이며 C−A 차이 `1.500022328571049e-12`다. 계획58구간 CM에서 이 수치 조합이 실현 가능한지나 실제 연구결과에서 문제가 발생했는지는 **NOT_MEASURED**다. `design_checks.json`에 입력/반환을 보존했다. 임의 quantization·새 epsilon·최대값 기준 동점집합으로 고치지 않는다.

문서의 이전 미확정 수치/옛 5-class/seed0~4 기록은 후속 EXP-006/007와 범위를 구분하며 과거를 고치지 않았다. 새 epsilon·프레임 손실식·촬영시간·seed 선택 규칙을 추정해 추가하지 않았다.

## 7. D-4 보조 알고리즘 채택·보류표

모두 구현/기존 평가 기록이 있다. M3-G는 root `m3_g.py`, 나머지는 ALG 폴더 생성기와 고정 PLAN, LR 추가 설정은 FIX 폴더다. 아래 판단은 **현재 후속 실험 필요성**이며 범용 알고리즘의 우열 판정이 아니다.

| 알고리즘 | 실제 탐색 근거/조건 | 복잡도·추가 가치·제약 | 판정 |
|---|---|---|---|
| RF M3-G | H9-v2(F1~F8+C3)·primary5·20구간·seeds0~4·2인 LOSO, 2026-10-28 보고서 | 5/3/1 group sampling과500 trees; 공식 H9 6-class와 NON_COMPARABLE. C3 사용 변화가 일반화 이득 근거 아님 | **REJECT**: 이번6-class 후속 범위에서 제외 |
| LR A(H9) | ALG의24구간: Acc87.50/F1 86.84%, R0/R1/R5=50/75/100; LR-B와 기존 저장 예측 같음 | 선형6클래스 경계+train scaler; 공식 B0 외 추가9열 평가 필요성 낮음 | **HOLD**: B0 유지, 추가 fit 불필요 |
| LR R1 | FIX C=0.3, 같은24구간; Acc83.33/F1 82.01%, Recall50/50/100 | 규제 강화의 기존 통제 탐색. B0 대비 추가 가치 미확인; 새 C 탐색은 같은pilot 선택 편향 | **REJECT**: 정식 설정 추가 안 함 |
| LR W1 | FIX C=1, P0/P1 상대가중1.5; B0와 Acc/F1/예측 동일 | 가중치 추가 복잡성의 실증 이득 없음. 미래 다른 자료 효과는 미확인 | **REJECT**: B0로 충분 |
| Linear SVM | ALG H9, C1/L2/squared_hinge/dualFalse; Acc83.33/F1 76.30%, Recall0/100/100 | 선형 비교 역할이 LR와 겹침; 이pilot의 P0 완전 실패. 새 튜닝 근거 없음 | **REJECT**: 현재 보조 실험 축소 |
| RBF-SVM | ALG H9, C1/gamma1/9; Acc83.33/F1 81.48%, Recall75/25/100 | support-vector kernel 비용/메모리는 실제 SV수/환경 의존. P0/P1 tradeoff로 LR 대비 일관 이득 아님 | **HOLD**: 비선형 경계 질문이 별도 승인될 때 선택1순위, 지금 필수 아님 |
| KNN | ALG H9, k3/uniform/Euclidean/brute; Acc83.33/F1 82.41%, Recall50/50/100 | 학습표본 저장/추론 거리계산에 비용 의존. P01/P02 결과 편차, train12개로 neighborhood 안정성 부족 | **REJECT**: 현재 추가 가치 부족 |

숫자는 ALG/FIX 저장 CM에서 이번에 재계산한 **EXPLORATORY** 값이며 공식8조합의 정식 결과와 직접 비교하지 않는다. RF raw vs LR/SVM/KNN train-fold scaling도 파이프라인 차이다. n2/train12의 군집·작은 표본 때문에 선형/비선형 모델 모두 과적합 위험을 판단할 독립 근거가 부족하다. 위 복잡도 설명은 구현 과정에 대한 설명이며 속도/정확도의 우열 수치 예측이 아니다.

**ADOPT_AS_SECONDARY로 새로 채택할 모델은 없다.** 필수는 기존8조합/5후보와 그 비용 측정이다. 선택은 사전 질문/개발자료만의 별도 protocol이 마련된 경우 RBF-SVM 하나로 제한한다. 나머지 확장·grid search·추가 ablation은 현재 불필요다. 어떤 보조 결과도 외부4명으로 재선정·튜닝하거나 공식8조합에 편입할 수 없다.

## 8. D-5 연산 비용 측정 프로토콜

정식 모델이 없어 **8조합별 train/inference/bytes/feature extraction/CPU/RSS/Private Bytes는 모두 NOT_MEASURED**다. 구조상 차원은6/6/5/9/9/9/8/8로 확인됐지만 비용 수치가 아니다. 기존 ALG/FIX 비용은 pilot 소형모델·과거 환경의 기록이고, 합성 clock/비인체 H9 미연결 FPS는 실제6 모델 비용이 아니다.

| 지표 | 기존 측정/저장 위치 | 해석 경계 |
|---|---|---|
| 학습 wall seconds | `model_benchmark.run_benchmark(train=...)`, perf_counter_ns; `benchmark.json.metrics`, `model_benchmark_details.csv` | train callback만. scaler fit 포함 여부/모델 fit만 여부를 config로 명명; 추출/I/O/평가/직렬화 제외 |
| 단일 추론 p50/p95 ms | 같은 API predict callback raw ns→NumPy linear percentile, JSON/`model_benchmarks.csv` | input1×d, warmup 제외. 모델-only와 전처리+model을 **별도 run**으로 측정 |
| 모델 파일 bytes | 명시 `model_path.stat().st_size`+SHA pin, benchmark 상세 | 실제 파일 bytes. 과거 `len(pickle.dumps(...,protocol5))`와 파일 형식/압축이 같다는 근거 없이 비교 금지 |
| 특징 차원/순서 | benchmark JSON `feature_order`; formal6 FEATURES | csv 상세에 임의 차원 지표를 끼워 넣지 않음 |
| 특징 추출시간 | probe의 stage와 QPC `probe_diagnostics` raw 분포/phase | Pose/Face/align/depth_geometry/집계·변환 경계를 명시; 모델 추론과 분리. H5도 현재 공유9 경로라는 점 표시 |
| process CPU | `probe_timing` process_time_ns delta / wall delta ×100, 1Hz monitor; performance raw/요약 | 1core=100%; CPU time≠wall time. model_benchmark 자체에는 CPU 표본 없음 |
| RSS/Windows Private Bytes | `process_memory`: GetProcessMemoryInfo WorkingSetSize/PrivateUsage; train/infer before/after와 live1Hz | operation peak/isolated allocation 아님. OS PeakWorkingSetSize도 프로세스 누적 peak이며 모델 작업 peak 아님 |
| warmup/환경/반복 | benchmark measurement_conditions/hash, identity/Git/environment/input/model/config SHA; live timing phase | H9 full-window 수집·frame warmup·추론warmup을 분리. 단위/clock 간 차감 금지 |

정식 직전 승인된 비용 비교 계획(연구 모델/선정 규칙 변경 아님):

1. 동일 장치/전원모드/OS/Python/package/threadpool/코드/데이터·순서/serialization 조건을 pin한다. BLAS/OpenMP1 thread, idle background 조건을 기록한다. 다른 환경끼리 우열 표를 만들지 않는다.
2. 개발2 LOSO의 실제 공통 비교 표본과 fold/seed0,1,2를 사용하고 LR는 결정적1회로 표시한다. 학습 데이터 크기/클래스·feature/model별 input SHA·열 순서를 저장한다. 누락/다른 공통 표본이면 비교를 차단한다. 외부4명은 비용 비교에도 사용하지 않는다.
3. 각 모델/fold/seed의 기존 학습을 변경 없이 측정한다. M1/M2의 MDI용 M0 비용 및 재사용 여부를 구분해 총 pipeline train 비용에 포함/별도 표시한다. 공유 fit 시간과 개별 fit 시간을 더해 중복 계산하지 않는다. 학습시간은 각 완료 fit의 wall time으로 보고하고 반복 fold/seed를 독립 참가자로 해석하지 않는다.
4. 고정 이미 집계된1×d 입력 schedule로 각 모델/fold/seed에서 **warmup24회 후120회**, 회전순서/round-robin을 사용한다(기존 ALG/FIX 조건 재사용). 각 조건 **3개 별도 process run**에 같은 thread/GC 조건을 적용·기록한다. 각 run raw/quantile과 실행간 요약을 분리하며 p95 평균을 pooled p95로 부르지 않는다. 이 반복은 성능/seed 튜닝이 아니다.
5. 모델-only는 사전 변환 입력, pipeline은 raw 입력의 transform+predict로 별도 측정한다. 학습 callback, feature extraction, 파일 load/직렬화/출력은 이 추론 timer 밖이다. 전처리 유무가 다른 모델은 scope명을 함께 표시한다.
6. train/inference 전후 메모리 snapshot을 저장한다. CPU/시간별 메모리가 필요하면 기존 monitor로 전체 run을 계측하고 모델 단독 peak로 귀속하지 않는다. peak가 요구되면 현 도구로 **NOT_MEASURED**; 근거 없이 새 peak 숫자를 만들지 않는다.
7. 실제 posture pipeline에서는 QPC sidecar로 Pose/Face/align/geometry/집계/inference/UI 제출을 분리한다. 기존 monotonic 출력은 유지한다. 계측 enabled 조건과 recorder overhead를 명시하고 동일 입력 조건이 입증된 경우만 `engineering_ab.py` 비교를 사용한다. 별도 live 두 run을 같은 입력이라고 가정하지 않는다.

기존 API 사용 템플릿(이번 미실행; 실제 dataset/model 경로·승인된 adapter는 실행 단계에서 제공):

```python
from model_benchmark import run_benchmark
# identity: scope/run/data/model/config/Git/environment + 실제 hash
# one_row: 개발 fold에서 고정한 shape(1,d), feature_order와 일치
run_benchmark(NEW_DIR, identity=identity, input_value=one_row,
    input_id=input_id, input_sha256=input_sha256, feature_order=feature_order,
    seed=seed, model=frozen_development_model, predict=predict_adapter,
    model_path=existing_artifact_path, calls=120, warmup_calls=24)
# 학습 측정은 별도 NEW_DIR에서 train=기존_fit_callback, predict=None.
# scaler 포함/제외·fold·비용 귀속·환경 조건은 identity.config에 기록.
```

`model_benchmark.py`는 CLI 실행기가 아니라 callback API다. 아직 없는 실제6 모델용 명령을 실행 가능하다고 만들지 않았다. 재현 가능한 지금의 무학습 확인 명령은 §10에 있다. 기존 A/B 변환 명령은 `python -B engineering_ab.py TIMING.json PERFORMANCE.json CONDITIONS.json NEW_DIR`이며 촬영/학습을 실행하지 않는다.

출력 contract: `benchmark.json`의 kind=`engineering-model-benchmark/1`, raw_inference_ns/metric status/feature_order/seed/input·환경·조건hash/model SHA·size/memory observations/errors; 공통 identity prefix의 `model_benchmarks.csv`에는 **추론 ms count/p50/p95만**, 상세 CSV에는 metric/unit/status/reason/value/count/p50/p95/maximum을 쓴다. `performance.json`/4CSV는 `engineering-performance/1.0.0`, `diagnostics.json`은 별도 QPC, `frames.jsonl`/summary는 provenance다. 빈값은 null/빈 cell이며0이 아니다. 과학적 schema를 변경하거나 실제 모델 성능값을 채우지 않았다. 기존 도구로 충분하여 새 production 계측 구현은 추가하지 않았다.

## 9. D-6 정식 연구 준비 상태

인계는 [STAGE_6_EXECUTION_HANDOFF.md](STAGE_6_EXECUTION_HANDOFF.md)에 통합했다. 이번 사용자가 확정한 개발2명(기존pilot 동일인 신규 정식 촬영)+외부 독립4명, S1 자세당3/S2 자세당2를 적용한다. 원 초안의 미확인 인물 대응은 이번 사용자 지시로 개발 설계를 명확히 한 것이며 동의/실제 roster 확인이 완료된 것은 아니다.

개발1명30목표구간, 2명60, 첫 P0 각1 제외 후 **최대58**은 초안/EXP-003/5E3 및 source plan과 산술 일치한다. 결측 전 참가자별 class support는 `[4,5,5,5,5,5]`; 전체 `[8,10,10,10,10,10]`다. 실제 적격 수가 아니다. 외부도 같은3+2를 승인한 경우에만120목표−참조4=최대116이며 IRB 최종 protocol로 재확인한다.

현재6-class UI는 합성 구조 검증, 실제6 모델 없음. H9 primary5·비인체 FPS·합성 예측을 최종6 연구 결과로 사용할 수 없다. 6단계=개발 촬영/평가/선정/동결, 7단계=외부 독립 검증/실제6 UI와 실제 자세 성능·논문 결과 정리로 이 인계의 작업 번호를 명시한다. 2026-10-28 문서의 옛 ‘6단계 파일럿 탐색’ 명칭과 혼동하지 않는다.

## 10. 실제 테스트 결과

2026-11-05 이번 실행: **70 tests PASS / failures0 / errors0 / skipped0**. `rf_experiment.Forest.fit`와 `LogisticRegression.fit`를 금지 mock으로 감싼 상태에서 각각 호출0을 확인했다. 실제 데이터 수집/모델 fit/모델 선정/외부 접근/전체 suite 재실행 없음.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B analysis/READ_ONLY_STAGE_5E_BUNDLE_D_20261105/review.py tests
```

실행 대상: `test_f0_fcal_features`, `test_f0_fcal_evaluation`, `test_h5_h9_evaluation.HAggregationTests`, `test_model_benchmark`, `test_evaluation_csv_adapter`, `test_prediction_adapter`, `test_frame_provenance`, `test_stage5e_readiness` 및 formal6의 fit 없는7개(차원/참조/교집합, 결측·라벨·identity, bridge, 부족class fit전 차단, 외부row 차단, N/A/동점, freeze/hash/lazy loader). 로그의 argparse 오류 문구는 invalid CLI 거부를 확인한 예상 negative test이며 실패가 아니다.

정확8매핑/seed/전처리·fold 학습 경계는 source 및 위 합성 adapter 테스트로 확인했다. 추가 `review.py design`에서8매핑/차원/순서/seed를 assert하고 C6 원문 보존을 확인했으며, B6 epsilon 연쇄 반례를 별도 관측했다. **70개 기존 회귀 PASS가 B6 해소를 뜻하지 않는다. 완전8조합의 fit 동반 통합 테스트는 NOT_RUN**이며 과거 검증 PASS를 이번 실행 건수로 합치지 않았다. source 고정·기존 C6 진단 경로 보존은 hash로 별도 검사한다. 저장 CM의 Accuracy/Macro-F1은 독립 산식1e-12 대조, C6 journal hash/raw→align/처리수/중복수는 직접 재계산했다.

증거 폴더에는 `review.py`, `start_state.json`, `saved_evidence_review.json`, `synthetic_tests.log`, `test_results.json`, `design_checks.json`, `dependency_pins.json`, `document_checks.json`, `end_state.json`을 새로 생성했다. 기존 출력은 exclusive create로 덮어쓰지 않는다. 재검증 시 새 폴더를 사용해야 한다. `git diff --check` PASS, Markdown 절 수/로컬 링크/판정 및 선택한 핵심수치의 증거 대조 PASS다. 전체 과학적 문장 자동 감사로 확대하지 않는다.

## 11. 미검증·BLOCKED 항목

| 항목 | 상태/해소 조건 |
|---|---|
| IRB 승인/원문version/동의·영상 공유/라벨 검토·보관·독립성 | **BLOCKED**; 승인/운영 release 증빙 필요 |
| CAP-007/009, EXP-002 Foundation/Patch8·EXPERIMENT_PROTOCOL | **BLOCKED**; 별도 실행 승인·감사코드 pin·사전등록 및 요구된 hardware validation/프로토콜 동결 필요. 이번 registry/ID 생성 없음 |
| B1 SOP/sequence/유지시간·전방 gate 운영 대응 | **BLOCKED**; 현재6 hold 준비안과 승인 원문 대조/정리 필요 |
| B2 실제 입력 신규성·coverage/Depth 품질 적격 | **BLOCKED**; 전달frameset 정의 보존, scientific 품질 release 근거 필요. Headless NOT_APPROVED |
| B3 missing_rate | **NOT_MEASURED**; 별도 명세/신뢰성 검증 없이 숫자 산출 금지 |
| B6 epsilon 연쇄 동점 | **BLOCKED**; 승인된 순위 해석/별도 수정·회귀 전 정식 자동 선정 금지 |
| F0/F_cal 파일럿 직접비교·정식8조합 실제 score/비용 | **NOT_MEASURED**; 과거 자료 부족을 합성 수치로 보충 안 함 |
| 실제6 artifact freeze/독립 loader/추론/UI 연결·자세 FPS/지연 | **NOT_RUN**; 승인 후6→7단계 작업 |
| 전체 suite·정식fit/full synthetic fit통합·새 hardware 진단 | **NOT_RUN**; 이번 최소 회귀 범위 밖 |

## 12. 동결 규칙 보존 증거

161개 tracked 파일의 시작/종료 byte SHA 대조에서 의도한 C6 보고서 외 **160개 일치**를 확인했다. 새 source 변경은 없으며 기존 평가기/특징식/seed/LOSO/M0~M2/FEAT-010/8조합/선정 우선순위·epsilon/P0/시간창/30·50%/depth masks·ROI·production gate/SEQ_CORE/FULL/frames·summary/provenance/selection 계약을 보존했다. 원본 saved 집계·C6 evidence 입력과 별도 실행의존성 pin도 종료 대조에서 일치했다. 이 범위를 전체 ignored 자료 감사로 확대하지 않는다.

OPEN-002/003/005, CAP-007 실행 보류, IRB HOLD는 변경하지 않았다. FEAT-010에서 해소된 OPEN-004를 옛 AGENTS snapshot 때문에 다시 미해결로 되돌리지도 않았다. B1~B6는 새 결정으로 조용히 해결하지 않고 실행 gate로 남긴다. 규칙 변경이 실제 필요하면 기존 기록을 고치지 않고 후속 Decision Log/승인 원문에 Supersedes/Clarifies/Resolves를 해당 범위에 기록해야 한다.

C6 최종 실측은 기존 보고서 §15에 날짜·출처와 함께 추가했다: SDK child reuse CONFIRMED, align ID 해당 범위 PASS, 인과 LIKELY, 정식 Headless NOT_APPROVED, 실제6 영향 NOT_MEASURED. 진단 코드는 수정하지 않았다. artifacts 접근·수정·삭제·stage, 원본 영상/외부4인 접근, commit/push는 없다.

## 13. 5단계 최종 완료 가능 여부

**PARTIAL_WITH_BLOCKERS.** 묶음 D의 통합 검토와 실행 인계 문서는 완료했다. 현재 특징/8조합은 calibration 비교·2D/Depth 추가·가중RF·F9중복/LR 비교의 연구 질문에 답할 구조를 갖췄으며 모델 수 확장은 필수가 아니다. 실제 유효성·일반화 성능은 승인된 신규 개발/독립 자료로만 답할 수 있다.

READY_FOR_STAGE_6_WITH_IRB_HOLD는 아직 부여하지 않는다. IRB 외에도 EXP-002/CAP-007, 승인 SOP와 현재 계획의 연결, 프레임 신규성·coverage 품질 release, 실제 실행 dependency/adapter의 보관·검증, B6 연쇄 동점 처리 조건이 남기 때문이다. 해당 blocker를 정식 승인·검증 기록으로 해소하고 실행 bundle을 검토한 후 준비 완료 여부를 다시 판정한다. 이번 문서 작성/70개 합성 PASS는 정식 수집·학습을 시작할 권한이 아니다.
