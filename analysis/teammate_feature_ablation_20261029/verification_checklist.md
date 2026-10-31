# 검증 체크리스트 — 가이드 §8·§9·§10 항목별 근거

- 가이드: 「AIoT 앉은 자세 분류 연구 — 팀원용 분석 업무 가이드」(원본 파일명 `AIoT_팀원용_H5_H9_특징기여_및_RF분석_작업가이드_20261029.md`) §8 "공통 결과 제출 규칙", §9 "연구 결과 해석·논문 반영 원칙", §10 "제출 순서·완료 기준".
- 업무 A~D를 마친 뒤(2026-10-31) 가이드 문장을 한 항목씩 놓고 결과물과 대조했다. 각 항목에 근거 위치와, 다시 확인하는 시험(`test_ablation.py`) 이름을 적었다.
- 시험 실행: 저장소 맨 위 폴더에서 `python -B -m unittest discover -s analysis/teammate_feature_ablation_20261029 -p "test_*.py"`. 파일럿 자료나 연구 주담당자 자료가 없으면 그 시험은 실패가 아니라 건너뜀(skip)으로 나온다.
- 결과 폴더의 다른 문서: `kickoff_report.md`(§10 "0. 착수 보고"), `summary.md`, `README.md`.

## 1. §8 필수 성능 지표

| 가이드 §8 | 위치 | 다시 확인하는 시험 |
|---|---|---|
| Accuracy, Macro-F1 | 결과 JSON `pooled.summary`, `pooled.per_seed`. `summary.md` 표 1·2(A), 표 B-0·B-1(B) | `ResultJsonRecomputeTests` |
| 클래스별 Precision / Recall | 결과 JSON `per_class`. `summary.md` 표 2·부록 1(A), 표 B-2(B). 정의되지 않는 Precision 표시 규칙은 표 2·B-2 아래 | `ResultJsonRecomputeTests` |
| 6×6 혼동행렬 | 결과 JSON `per_seed[].confusion_matrix`(seed별), `summary.md` 부록 3(A)·표 B-7(B)(seed 5개 합계, 행 = 실제, 열 = 예측) | `ResultJsonRecomputeTests` |
| P1→P0, P1→P5 오류 수 및 클래스별 표본 분모 | `summary.md` 표 1·3(A), 표 B-0·B-3(B). 분모: 자세마다 seed당 구간 4개(표 1·B-0 아래) | `ResultJsonRecomputeTests`(분모 4 포함) |
| 각 참가자를 시험으로 둔 fold별 결과 | 결과 JSON `by_participant`, `folds`. `summary.md` 표 4·5(A), 표 B-4·B-5(B) | `ResultJsonRecomputeTests` |
| seed 0~4 개별 결과 | 결과 JSON `predictions_per_seed`, `per_seed`. `summary.md` 표 5·6·부록 2(A), 표 B-5·B-6(B) | `ResultJsonRecomputeTests` |
| M0 기준선 대비 변화(Accuracy/Macro-F1은 %p) | 결과 JSON `delta_vs_baseline`(단위 %p). `summary.md` 모든 표의 괄호 안 값 | `ResultJsonRecomputeTests`, `MetricTests.test_delta_is_zero_against_itself_and_in_pp` |
| 예시 결과표 형식, 행마다 기준선(H5/H9) 표시 | `summary.md` 표 1(A, 마지막 열 "차이 기준선"), 표 B-0(B, 모두 H5) | — |

- 위 지표는 업무 A·B(실험 업무)에 해당한다. 업무 C는 정의 비교, 업무 D는 기존 자료 정리라서 새 성능 지표가 없다(가이드 §6, §7).

## 2. §8 결과 디렉터리

| 가이드 §8 파일 | 있음 | 내용 |
|---|---|---|
| `README.md` | ✅ | 코드 기준 SHA, 데이터 출처, 실행 방법 |
| `config.json` | ✅ | 특징 집합, 클래스, seed, RF 설정, 적격 조건, 13개 조건 |
| `baseline_check.json` | ✅ | H5/H9 기준선 재현 대조(`REPRODUCED_EXACTLY`) |
| `depth_add_one.json` | ✅ | 업무 A-1 |
| `depth_drop_one.json` | ✅ | 업무 A-2 |
| `h5_drop_one.json` | ✅ | 업무 B |
| `f0_h5_comparison.md` | ✅ | 업무 C |
| `rf_failure_analysis.md` | ✅ | 업무 D |
| `summary.md` | ✅ | 논문용 주요 표·해석·한계 |

- 가이드 목록 밖의 파일: `ablation.py`, `test_ablation.py`(가이드 §2-4 "별도 신규 분석 스크립트/테스트/결과 폴더를 만든다"), `kickoff_report.md`(§10 "0. 착수 보고"), 이 문서(§8 체크리스트의 근거), `guide_flow.md`(가이드 흐름 쉬운 설명), `work_rationale.md`(업무별 질문·답 형식의 근거). 기존 결과 파일은 덮어쓰지 않았다(`ablation.py`는 같은 이름의 결과가 있으면 멈춘다, `SafetyStopTests.test_refuses_to_overwrite_existing_output`).

## 3. §8 필수 기록

| 가이드 §8 필수 기록 | 위치 |
|---|---|
| 사용 코드 기준 commit | 결과 JSON `provenance.commit`(실행 당시), `README.md`·`kickoff_report.md`(기준 커밋 `8252b7b`) |
| 입력 파일의 식별자·SHA-256(민감 경로 제외) | 결과 JSON `inputs`, `config.json` `inputs`, `kickoff_report.md` 2절. 파일 이름만 적고 로컬 경로는 적지 않음 |
| 실험 날짜 | 결과 JSON `run_date`(세 결과 모두 2026-10-30) |
| 버전 | `config.json` `config_version`, 결과 JSON `provenance.environment`(Python 3.14.4, numpy 2.5.0), `provenance.code_sha256`(기존 코드 4개), `ablation_py_sha256` |
| 클래스 순서 | 결과 JSON `class_order`, `posture_ids`, `README.md` |
| 표본 ID(가명 코드만) | 결과 JSON `samples.sample_keys`(예: `P01_h9_20261024_170900`, 구간 번호). 실명·참가자 대응 정보 없음 |
| 모델 설정 | 결과 JSON `model`(M0, 트리 500개, `max_features=2`, seed 0~4, 조건·fold마다 재학습) |
| 각 fold의 학습/시험 대상자 | 결과 JSON `folds[].held_out_participant`, `training_participants`, `train_indices`, `test_indices` |
| 5 seeds | 결과 JSON `model.seeds`, `folds[].seed` |
| 실행 오류·부적격 이유 | `README.md` "데이터 출처"(부적격 0개, 실행 오류 없음), `baseline_check.json` `samples` |

## 4. §8 최소 검증 체크리스트

| 가이드 §8 체크리스트 | 판정 | 근거 | 다시 확인하는 시험 |
|---|---|---|---|
| 첫 실행에서 H5/H9 기준선 같은 데이터 조건으로 재현 또는 불일치 사유 보고 | ✅ | `baseline_check.json` `verdict` = `REPRODUCED_EXACTLY`(구간 명단, seed별 혼동행렬, 점수까지 같음). `ablation.py`는 실행할 때마다 기준선을 다시 대조하고, 다르면 멈춘다 | `RealBaselineReproductionTests`, `SafetyStopTests.test_baseline_mismatch_is_detected` |
| P01/P02 학습·평가 데이터 혼입 없음 | ✅ | 세 결과 JSON의 기준선 3개와 조건 13개, 각각 fold 10개(seed 5개 × 시험 참가자 2명), 모두 160개 fold에서 학습·시험 구간이 겹치지 않고, 시험 구간은 시험 참가자 것만 있다 | `ResultJsonRecomputeTests`, `LosoTests.test_folds_never_mix_train_and_test_participants`, `LosoTests.test_test_participant_rows_never_reach_fit` |
| 모든 특징 조합에서 24개 동일 구간 및 H9 공동 유효 지원 유지 | ✅ | 세 결과 JSON의 구간 명단이 서로 같고 `baseline_check.json` 명단과도 같다(24개). 특징을 빼도 구간을 다시 고르지 않는다(H9 공동 유효 기준으로 고정, 부적격 0개) | `ResultJsonRecomputeTests.test_same_24_samples_everywhere`, `RealBaselineReproductionTests.test_fixed_sample_set` |
| 모든 조건에서 M0 재학습·설정 고정 | ✅ | 결과 JSON `model.retrained_per_condition_and_fold` = true, 세 결과의 `config_sha256`이 모두 `517d78ca…`로 같다 | `LosoTests.test_each_condition_retrains_with_only_its_columns`, `LosoTests.test_matches_existing_fit_models_m0` |
| 혼동행렬 합계와 정확도·재현율 재계산 일치 | ✅ | 저장된 예측에서 혼동행렬(합계 24), Accuracy, Macro-F1, 클래스별 Precision/Recall/분모, P1→P0·P1→P5, 참가자별 정확도, 기준선 대비 변화를 다시 계산해 모두 일치 | `ResultJsonRecomputeTests.test_stored_metrics_match_recompute`, `MetricTests` |
| seed 반복을 독립 사람 표본처럼 세지 않음 | ✅ | 결과 JSON `seed_note`, `summary.md` 업무 A·B 한계("seed 5개는 같은 24개 구간의 계산 반복"), 업무 D 0절 | — |
| 원본 코드·모델·CSV·기존 결과 변경 없음 | ✅ | 기준 커밋 `8252b7b` 이후 결과 폴더 밖의 추적 파일 변경 0개(`git diff --name-only 8252b7b -- . ':(exclude)analysis/teammate_feature_ablation_20261029'`가 비어 있음). 세 결과 JSON의 `tracked_files_modified` = false, 기록된 기존 코드 4개와 `ablation.py`의 SHA-256이 지금 파일과 같다. 입력 CSV·기준 결과의 SHA-256이 `config.json`과 같다 | `SafetyStopTests.test_wrong_input_hash_stops` |
| 개인/원본 영상 데이터 Git stage·push 없음 | ✅ | 기준 커밋 이후 커밋한 파일은 결과 폴더의 파일뿐이다. 원본 영상·CSV·연구 주담당자 자료는 올리지 않았다. 파일을 하나씩 `git add -f`로 올리고 `git add .`/`git add -A`는 쓰지 않았다(가이드 §2). 아직 push하지 않았다 | — |
| `git diff --check`, 관련 최소 테스트 PASS | ✅ | `git diff --check` 통과, `test_ablation.py` 전체 통과(파일럿 자료가 없는 새 저장소 상태에서는 자료가 필요한 시험만 건너뜀) | 전체 |

## 5. §9 연구 결과 해석·논문 반영 원칙

| 가이드 §9 | 판정 | 근거 |
|---|---|---|
| 1. 2명·24개 구간, 일반화·유의성·임상 성능을 입증하지 않음 | ✅ | `summary.md` 범위와 업무 A·B·D 한계 |
| 2. 같은 두 사람의 LOSO로 특징을 고르고 최종 독립 정확도라고 주장하지 않음 | ✅ | 특징을 고르거나 버리지 않았다(`summary.md` 업무 A 한계, `config.json` `not_done`) |
| 3. 후속 학습·후보 선정은 연구 주담당자, 독립 검증 4명은 모델 선택·튜닝에 쓰지 않음 | ✅ | 후속 학습·후보 선정을 하지 않았다. 독립 검증 대상자 자료는 받지도 쓰지도 않았다 |
| 4. F0와 H5/H9, 5-class와 6-class, H9와 H9-v2, 구간 분류와 실시간 윈도 분류의 숫자를 합치지 않음 | ✅ | 업무 C는 F0 정확도를 만들지 않았다. 업무 D는 M3-G(H9-v2, 5-class) 숫자를 옮기지 않았다. 업무 A는 원 논문·4초 윈도 결과와 비교하지 않았다(`summary.md` 업무 A 한계) |
| 5. 부정적 결과도 삭제하지 않음 | ✅ | H5−F4 변화 0, H9−F9가 더 높음, P1 Recall 0%, M2 악화, F9를 빼도 M2 격차가 줄지 않음을 모두 남겼다 |
| 6. 새 촬영·정식 IRB 데이터 취급 없음 | ✅ | 기존 파일럿 CSV 2개만 썼다 |
| 7. `posture_geometry_probe.py`, `h9_async_runtime.py`, `h9_probe_session.py`, `probe_timing.py`, 개발 모델·보존 스냅샷 변경 없음 | ✅ | 기준 커밋 이후 네 파일 변경 0개(`git diff --stat 8252b7b -- <네 파일>`이 비어 있음). 모델 파일을 만들거나 바꾸지 않았다 |

## 6. §10 제출 순서·완료 기준

| 제출 차수 | 가이드 완료 조건 | 판정 | 위치 |
|---|---|---|---|
| 0. 착수 보고 | 기준 SHA, 데이터 접근 상태, 누락 파일 정리 | ✅ | `kickoff_report.md` |
| 1. 우선 결과 (업무 A) | 조건별 표·원본 JSON·P1 오류 및 간단한 해석 | ✅ | `depth_add_one.json`, `depth_drop_one.json`, `summary.md` 업무 A |
| 2. 추가 결과 (업무 B) | 조건별 표·혼동행렬·seed/fold별 결과 | ✅ | `h5_drop_one.json`, `summary.md` 업무 B |
| 3. 문헌 분석 (업무 C) | 대응표·재현 가능/불가 및 근거 | ✅ | `f0_h5_comparison.md`(결론: 재현 불가, 근거 R1~R4) |
| 4. 최종 정리 (업무 D) | 기존 증거 목록·원인 가설·보고서 및 코드 변경내역 | ✅ | `rf_failure_analysis.md`("자료" 표, 4절, 7절) |

**업무 완료 기준**

| 가이드 §10 완료 기준 | 판정 | 근거 |
|---|---|---|
| 기존 기준선 재현 여부를 설명할 수 있음 | ✅ | `baseline_check.json`, `kickoff_report.md` 3절 |
| 업무 A/B의 재현 가능한 결과가 있음 | ✅ | `ablation.py` 실행 방법(`README.md`), 다시 실행해 `provenance`·`run_date`를 빼고 비교하면 같다 |
| 업무 C/D에서 확인된 사실과 미확인 가설을 분리 | ✅ | `f0_h5_comparison.md` 6절, `rf_failure_analysis.md` 4·6절 |
| 기존 실험·실시간 시스템·원자료를 변경하지 않음 | ✅ | 위 4절 "원본 코드·모델·CSV·기존 결과 변경 없음", 5절 §9-7 |
| 팀원 전용 브랜치에서 결과를 제출 | ⏳ | 업무 A~D의 분석 결과는 커밋 `d002ae5`에서 브랜치 `research/h5-h9-ablation`에 올렸고, 그 뒤 외부 검증을 반영한 문서 수정은 그다음 커밋으로 올린다(이 문서가 어느 커밋의 판인지는 `git log`로 확인). push는 이 체크리스트와 외부 검증을 마친 뒤에 한다 |
