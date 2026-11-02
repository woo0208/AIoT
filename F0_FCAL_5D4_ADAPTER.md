# 5-D-4 — F0/F_cal 독립 6열 평가 입력 경로

기준: `AGENTS.md`, `docs/research/F0_FCAL_5D3_EVALUATION_FREEZE.md`, Master §24/25 및 Decision Log EXP-003/004. 추가 파일은 `f0_fcal_evaluation.py`, `test_f0_fcal_evaluation.py`, 이 보고서뿐이다. 기존 계산 모듈·H5/H9/H9−F9·정식 평가기·데이터·모델·5-B·보호 파일은 수정하지 않았다.

## 연결 범위와 호출 순서

1. 호출자가 참가자/recording/run/step/order/label을 가진 기존 `f0_fcal_features.Segment`와 `TimedSegment`의 session, hold_start_s, hold_end_s, time_basis를 제공한다. 프레임별 `frame_index`, 동일 time_basis의 `time_s`(초), `phase`(hold/transition/prep), 기존 bbox/양 어깨 관측 열이 필요하다. timestamp 단위나 S1/S2를 경로·step에서 추정하지 않는다. core 입력의 bbox 중심·면적이 원 bbox에서 왔다는 provenance는 호출자 책임이다.
2. `prepare_samples(items, reference_keys)`에 참가자별 사전 고정 S1 첫 P0 key를 전달한다. `body_forward`/`lean_forward` 입력을 명시적으로 정규화하고 `h6_offline.LAB6` / `analysis_label`을 직접 재사용한다. 결과 label 순서는 upright, forward_head, lean_back, lean_left, lean_right, lean_forward다. 특징 순서는 기존 core FEATURE_NAMES 그대로 6개다.
3. `[종료-10초, 종료)`의 hold 프레임을 실제 입력 분모로 사용한다. 각 프레임을 core 계산으로 검사하고, F0 6개가 정의되는 공동 관측만 남긴다. 이때 단위 참조 면적은 관측 유효성 검사에만 사용하며 참가자 baseline이 아니다. 공동 support로 제한한 Segment를 core의 기존 보정/원시 중앙값/특징 계산 함수에 전달한다.
4. 목표와 참조의 공동 유효 >=30 및 coverage >=0.5, 참조 양수 면적·기준5개 유효성을 확인한다. 참조 실패는 해당 참가자 F0/F_cal 전체 평가 불가이며 이후 P0로 대체하지 않는다. H5/H9 결과를 수정하지 않는다. 참조는 학습/평가 모두에서 제외한다.
5. `evaluation_input(samples, other_families=..., participant_splits=...)`가 별도 6열 X/y/participant/키/마스크 경로를 반환한다. participant_splits는 명시적 train/heldout이며 개발2/검증4 미충족을 blocker로 기록한다. split은 모델/scaler fit을 수행하지 않는다.

`Sample`은 f0/f_cal, 특징별 missing mask, reference key/flag, eligible/status, 제외·보정 실패 사유, 입력/공동 support frame indices와 coverage를 보존한다. 입력 부족·짧은 유지 구간·중복 frame identity는 unprocessed로 반환한다. 잘못된 참조 지정·충돌한 구간 식별자는 오류로 거부한다. 참조가 없으면 자동 선택하지 않고 unprocessed다.

전송 배열의 None은 NaN으로 표현하고 별도 missing mask를 제공한다. 0 채움·보간·임의 열 추가는 없다. 낮은 count/coverage의 유한 집계값은 진단용으로 보존할 수 있지만 eligible/common/train/heldout mask에서는 제외된다. 결측 마스크와 제외 마스크는 서로 다른 의미다.

## 공통 표본 정렬

다른 특징군은 기존 집계 결과를 `ComparableSample(sample_key, subject, label, values, eligible, reasons)`로 제공한다. exact key로 join하고 참가자/라벨 일치를 검사한다. 누락·중복·부적격·비유한 관측을 보고하며 참조 제외를 모든 공통 비교에 적용한다. 다른 특징군의 자체 적격성은 변경하지 않는다. caller는 같은 원래 구간의 key를 동일 타입으로 제공해야 한다(step 문자열/정수의 추정 변환 없음).

반환값의 `matrices`, `y`, `participants`, `sample_keys`, `missing_masks`, `reference_mask`, `eligible_mask`, `exclusion_reasons`는 전체 동일 정렬이다. `common_mask`, `common_sample_keys`, `common_matrices`, `common_y`, `common_participants`는 비교 특징군 간 공통 적격 구간만 동일 정렬로 제공한다. train/heldout mask도 공통 mask와 참조 제외를 반영한다. family audit에는 누락·추가 key와 부적격 사유를 보존한다. **특징군 간 원시 프레임 교집합은 강제하지 않는다.**

## 기존 실행기 보존과 차단

`analysis/formal6_evaluator_20261030_93bd72/run.py`의 고정 8열 fixture/validate/evaluate는 그대로다. 이 어댑터는 그 함수에 6열을 억지로 넣거나 고정 synthetic guard를 우회하지 않는다. 새 6열 준비 인터페이스이며 기존 학습/지표 루틴은 호출하지 않는다. 평가 입력과 클래스 정렬까지 연결한 것이며 실제 정식 fit/predict/metrics 실행은 연결하지 않았다.

실제 촬영 loader, 시간축·종료 marker·phase 및 참조의 provenance 연결은 미연결이다. time_basis는 호출자의 명시적 동일 시간축 선언이며 장치 clock 변환을 검증하지 않는다. 부족한 시간/세션/프레임 identity는 추정하지 않는다. frame_loss_rate는 None이며 기대 프레임 수를 만들지 않는다. 불완전 클래스·seed/metric 정책도 적용하지 않고 `execution_blockers`에 표시한다. 실제 인물 독립성 확인·프로토콜 전체 freeze 및 실행 승인은 별도다.

## 합성 검증

`python -B -m unittest -v test_f0_fcal_evaluation test_f0_fcal_features`: 신규 어댑터 9개 + 기존 core 13개, 총 **22개 PASS**. 특징 차원/라벨 순서, 공동 support·30/50 경계, 반개구간/전환 제외, S2 고정 참조/참가자 격리, 참조 부분 실패, 미처리/결측, 공통 key 정렬 및 train2/heldout4 참조 제외 mask를 검증했다. 실제 자료·학습·Ablation·전체 감사·commit/push 없음.
