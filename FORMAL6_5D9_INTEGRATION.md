# 5-D-9 — 공통 정식 6-class 평가 경로

**2026-11-02 후속 상태:** 아래 마무리 절 / EXP-007에 따라 F0/F_cal/H5 + RF M0가 비교 기준선으로 확정·연결됐다. 원문의 모델 조합 미동결 서술은 최초 5-D-9 시점의 기록이다.

추가 파일은 `formal6_evaluation.py`, `test_formal6_evaluation.py`, 이 보고서 3개다. 기준은 AGENTS.md, 5-D-3, 5-D-8 및 EXP-005/006이다. 기존 RF/LR·H 계산식·capture/loader·5-B·보호 모델·원본·스냅샷·frozen schema·고정8열 실행기는 수정하지 않았다. 실제 자료·최종 선정/학습 artifact·정식 평가 결과를 만들지 않았다.

## 입력 연결과 적격성

`Row`는 exact sample_key, subject, label, session, 검증된 window `(time_basis, start_s, end_s)`, values, 원천 eligible/reasons, 독립 label review 상태 및 feature support를 받는다. window는 정확한 10초이며 별도 upstream에서 marker/시간축을 검증한 값이어야 한다. 시간이나 confirmed 상태를 이 평가기가 추정하지 않는다.

| 인터페이스 | 역할 |
|---|---|
| `rows_from_f0(samples, timed_segments, review_states, development_subjects)` | 기존 5-D-4/6/7 loader/어댑터 결과의 F0/F_cal 6열·고정 참조 실패/제외·support를 보존해 Row로 변환 |
| `rows_from_h(samples, windows, review_states, development_subjects, key_map=...)` | 기존 H 집계의 H5/H9 및 H9 첫8열 H9−F9를 그대로 투영. 새로운 계산/집계/프레임 필터 없음 |
| `align_development(..., feature_sets=...)` | 5/6/8/9열 형상 검증과 exact key 공통 적격 구간 정렬, 결측 마스크·원인·각 family support 감사 출력 |
| `evaluate_development(families, development_subjects, reference_keys)` | 승인된 다섯 후보만 개발2명 LOSO, 공통 표본, fold-local 학습/지표 및 개발 추천 순위 |

개발 참가자 두 ID와 참가자별 사전 고정 첫 P0 reference key를 명시해야 한다. 선택된 직접 비교에선 그 P0를 모든 family의 학습/평가 표본에서 제외한다. 참가자·라벨·session·10초 window가 같은 key에서 다르면 오류이며, 다른 family에 표본이 없거나 기술 부적격·결측·라벨 미확인이면 공통 교집합에서 제외하고 원인을 보존한다. confirmed 이외의 ambiguous/mismatch/not_reviewable 등은 포함하지 않는다. 프레임 support 교집합은 강제하지 않는다.

H key의 문자열 step과 F0 integer step은 **호출자가 명시한 key_map**으로만 연결할 수 있다. 같은 recording/run과 같은 step 표기여야 하며 probe의 합성 analysis_run_id를 canonical lineage로 추정 변환하지 않는다. 실제 촬영의 QA/시간/동일 구간 출처 연결은 기존 loader 결과와 별도 사전 고정 metadata가 필요하다.

참조가 행 목록에 없더라도 사전 reference_keys가 그 제외 기준이다. F0/F_cal 실패는 H5/H9 자체 평가를 바꾸지 않는다. 선정 비교의 교집합은 H9/H9−F9다. F0/F_cal/H5를 포함한 별도 직접 비교는 `align_development`로 동일 표본을 만들 수 있으나, 아래 미동결 모델 조합에 대해 임의 학습을 추가하지 않는다.

## 연결한 특징·모델

| 선정 순서 | 특징 | 연결 모델 | 기존 구현 재사용 |
|---|---|---|---|
| 1 | H9 9열 | RF M0 | `rf_experiment.fit_models` |
| 2 | H9 9열 | RF M1 | 동일 함수, 학습 fold MDI/rank weights |
| 3 | H9 9열 | RF M2 λ=0.5 | 동일 함수, 학습 fold split weights |
| 4 | H9−F9 8열 | RF M0 | 기존 `Forest(6,500,2,None,seed)` 직접 재사용 |
| 5 | H9−F9 8열 | LR B0 | 기존 baseline의 `make_model('Logistic-Regression',0)`와 `StandardScaler` |

RF seed는 0,1,2이며 tree=500/max_features=2다. RF 원시 입력을 재표준화하지 않는다. 8열 M0는 가중치가 필요 없으므로 p=8에 대해 승인되지 않은 `rank_weights`/M1/M2를 호출하지 않는다. LR B0는 기존 C=1/L2/lbfgs 등의 설정 그대로 한 번의 결정적 LOSO 결과만 산출한다. scaler는 해당 학습 참가자의 표본에만 fit한다. LR 결과를 세 RF seed 결과처럼 복제하지 않는다.

F0/F_cal(6열), H5(5열)는 공통 입력/표본 정렬과 비교 기준선의 지위를 지원한다. **그룹별 정식 모델 조합이 명시적으로 동결되지 않아** `MODEL_COMBINATION_NOT_FROZEN`으로 남긴다. 과거 파일럿 코드에 조합이 있다는 이유로 정식 조합을 자동 추가하지 않는다.

## 지표·클래스 부족·개발 순위

완전6-class에는 기존 LR baseline의 `metrics`를 직접 재사용한다. 불완전 자료는 같은 기존 sklearn confusion matrix/클래스 지표 함수를 사용하되 EXP-006 정책으로 감싼다: 클래스 순서 고정6, 실제 support=0 Recall은 Python None(보고 시 N/A), 공식 Macro-F1=None, INCOMPLETE 표시다. 선택적인 고정6 zero_division=0 진단 점수는 별도다. 빈 평가도 공식 점수/Accuracy가 없고 진단 점수와 혼용하지 않는다. P0/P1/P5의 모든 방향 오류와 참가자·S1/S2 지표/실제 support를 보존한다.

개발 두 참가자의 어느 쪽이든 공통 적격 표본에서 필수 클래스가 부족하면 어떤 모델도 fit하지 않고 BLOCKED·참가자별 support·사유를 반환한다. fold/클래스/참가자 삭제나 검증 자료 보충으로 자동 선정을 진행하지 않는다.

RF는 seed별 두 fold OOF를 합쳐 지표를 구한 뒤 seed 평균을 사용한다. `rank_candidates`는 다섯 후보 전체의 완전한 지표가 있어야 동작하며 반올림 전 절댓값 차이 <=1e-12를 동점으로 처리한다. 우선순위는 Macro-F1→P0 Recall→P1 Recall→P5 Recall→Accuracy→적은 특징 수→고정 후보 순서다. 반환은 **DEVELOPMENT_RECOMMENDATION_ONLY**이며 최종 모델 선정/재학습·artifact 저장·동결을 수행하지 않는다.

## 독립4명 접근 경계

개발 함수와 bridge는 개발2명 이외의 참가자가 들어오면 특징값 접근/학습 전에 거부한다. 개발 평가 인자로 검증 loader를 받지 않으며 검증4명을 전체 LOSO에 섞지 않는다.

별도 `load_frozen_heldout(freeze_path, freeze_sha256=..., loader=...)`는 아래를 모두 확인한 후에만 lazy loader를 호출한다.

- 외부에서 고정한 freeze JSON SHA 및 status=FROZEN.
- 승인된 후보 ID·고정6 class order·정확한 feature order·전처리/모델 설정과 seed.
- 현재 평가/특징/입력 경로 및 기존 RF/LR 의존 소스 hash 집합 일치.
- 개발2명/검증4명 ID 독립 분리.
- RF 각 seed 또는 결정적 LR의 최종 artifact 파일 SHA 확인. 학습된 scaler 등 추론에 필요한 전처리도 외부에서 동결하는 artifact bundle에 포함해야 한다.

freeze 입력은 status, candidate, class_order, `frozen_settings(candidate)`와 동일한 settings, `code_hashes()` 결과, development_subjects, heldout_subjects, model_artifacts(seed/path/sha256)를 요구한다. 이 함수는 freeze를 생성하거나 model pickle을 역직렬화하지 않으며, 실제 artifact의 내용과 metadata 일치를 새로 감사하지 않는다. **외부에서 검토·고정한 freeze hash가 신뢰 경계**다. 검증/IRB 승인 문서를 발급하지 않으며 OS 파일 권한 자체를 통제하는 기능도 아니다.

이번 연결은 독립 검증 자료의 사전 접근을 막는 API 경계까지다. 실제 최종 모델 학습·동결 bundle 작성/검증, 실제 독립4명 loader 및 artifact 기반 추론 실행 연결은 남아 있다. 기존 고정8열 synthetic-only validate/evaluate 경로를 우회하거나 6열을 8열로 채우지 않는다.

## 합성 검증과 남은 차단

기존 평가 환경 `analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe`를 재사용했다. 기본 Python에는 sklearn이 없어 그 환경의 첫 실행은 import 단계에서 실패했으며 새 설치는 하지 않았다.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B -m unittest -v test_formal6_evaluation
```

**9 tests PASS.** 작은 합성 자료에 한해 RF tree 수를 테스트 중 2로 patch하여 모델 재사용·전처리/분할 경계를 검증했고 즉시 복구했다. 실제 정식 설정은 500이며 테스트 출력에는 structural_test_settings를 표시한다. 연구 정확도·후보 성능 우열·실제 최종 선정의 근거가 아니다.

검증 범위: 다섯 입력군 5/6/8/9열, 공통 key/라벨/window 정렬과 참조 제외·결측/QA, 기존 bridge, 개발 외 자료 접근 차단, LR fold-local scaler, 필수 클래스 부족 시 fit/선정 차단, zero-support·1e-12 순위, 동결 전 lazy loader 차단 및 hash 검증, 기존8열 synthetic fixture 검증 유지(8열 파일 hash 동일). 기존8열 모델 fit은 실행하지 않았다.

남은 차단: F0/F_cal/H5 정식 모델 조합 결정, 실제 QA/window/lineage 입력 연결과 runtime 검증, 최종 artifact/scaler 동결 및 독립 추론 실행, IRB·재촬영/접근 운영 및 기타 실행 조건. 누락률 세부 산식은 구현하지 않았다. CAP-007 보류와 OPEN-005 잔여 범위를 해소하지 않으며 실제 참가자 자료·재학습·새 ablation·최종 모델 선정·commit/push 없음.

## 2026-11-02 마무리 — 비교 기준선 3개 연결

연구자의 명시적 승인 / EXP-007에 따라 RF_M0_F0(6열), RF_M0_F_cal(6열), RF_M0_H5(5열)를 BASELINES에 등록했다. 기존 Forest(6 classes, 500 trees, max_features=2, split_w=None), seeds=(0,1,2), 원시 입력을 재사용한다. F0/F_cal의 기존 보정/입력 및 rows_from_f0 bridge는 유지하며 scaler·rank weights·0 패딩·새 계산/탐색은 추가하지 않았다.

최종 지원은 **선정 후보5 + 비교 기준선3**이다. CANDIDATES·선정 우선순위·1e-12와 독립 검증 gate는 그대로다. `evaluate_development`는 기존 H9/H9−F9 공통 표본의 선정 경로를 유지하고 별도 `baseline_comparison`을 반환한다. `evaluate_baseline_comparison`도 직접 호출할 수 있다.

비교 부분은 다섯 특징군의 동일 참가자·목표 구간·10초 창·공통 적격 key에서 8개 조합을 평가한다. 참조 제외·결측/confirmed·원천 적격성·개별 support를 유지하며 원시 프레임 교집합은 강제하지 않는다. 선정용 표본과 같으면 기존 후보 결과를 재사용하고, 다르면 후보5도 비교 공통 표본에서 별도 평가한다. 이 비교는 selection=None이며 기존 선정 범위/순위를 대체하지 않는다.

F0/F_cal 실패는 H9/H9−F9 자체 평가에 영향을 주지 않는다. 비교 공통 표본의 개발 참가자별 필수 클래스가 부족하면 비교 BLOCKED와 support/사유를 기록하고 기준선을 학습하지 않는다. N/A/INCOMPLETE/공식 Macro-F1 미산출 규칙은 그대로다. 입력 특징군 미제공은 NOT_PROVIDED이며 0열을 만들지 않는다.

위 테스트 명령으로 신규3+기존9, **12 tests PASS**. 합성 테스트에서만 tree=2를 임시 적용했다. 기존 보정 bridge를 통한 세 기준선 실행, 5/6/8/9열 독립 처리, 표본 변경 시 8개 조합의 동일 key 정렬, 보정 실패의 H 후보 격리와 두 공개 API의 독립 자료 접근 차단을 확인했다. 모델 최종 선정·실제 참가자 사용·새 탐색·추가 ablation은 없다.

이번 수정은 formal6_evaluation.py, test_formal6_evaluation.py와 본 문서·Decision Log·Master·5-D-8 후속 기록이다. 기준선 조합 미확정은 해소됐고 실제 QA/window/lineage 입력·runtime 검증, 최종 artifact/scaler/코드 hash 동결·독립 추론, IRB/운영·기타 실행 조건과 누락률 세부 산식은 남아 있다. 원본·보호 모델·계산식·5-B·frozen schema 변경 및 commit/push 없음.
