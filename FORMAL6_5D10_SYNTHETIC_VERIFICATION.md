# 5-D-10 — 합성 6인 개발 → 동결 → 독립 추론 통합 검증

**SYNTHETIC STRUCTURAL ONLY / 실제 정식 모델 동결·논문 성능 아님.**

기준은 AGENTS.md, 5-D-3, 5-D-8 및 EXP-005/006/007이다. 실제 참가자 데이터·D455·보호 모델은 사용하지 않았다. 후보/기준선 조합, 기존 모델 설정·특징식·평가 규칙을 변경하지 않았다. 이번 검증을 Decision Log의 실제 정식 artifact 동결이나 Patch 8 실행/완료로 기록하지 않는다.

## 변경 파일과 산출물

- `formal6_evaluation.py`: 기존 F0/H bridge와 key 정렬의 공통 내부 함수만 분리했다. 공개 개발 API의 정확히 2명 제한은 유지하고, 독립4명용 내부 정렬은 동결 gate 통과 후에만 사용한다. 모델·지표·순위·seed 설정은 그대로다.
- `formal6_synthetic.py`: 파일/실제 데이터 입력 옵션이 없는 고정 합성 fixture 및 통합 실행기. 실제 정식 모델을 선택하거나 동결하는 범용 실행기가 아니다.
- `test_formal6_synthetic.py`: 신규 통합 테스트 4개.
- 본 검증 기록.
- 새 [합성 전용 산출물](analysis/SYNTHETIC_ONLY_5d10_20261102_ce907974): `SYNTHETIC_ONLY_freeze.json`, seed 0/1/2의 `SYNTHETIC_ONLY_model_seed_*.pkl`, `SYNTHETIC_ONLY_verification.json`. 기존 파일을 덮어쓰지 않았다. 모든 모델/설정·검증 기록에 합성 kind/fixture 식별자를 기록했다.

## fixture와 실행 범위

SYN-F01/F02 개발2명, SYN-F03~F06 독립4명이다. 참가자마다 S1 첫 P0 1개(보정 전용)와 별도 평가용 P0를 포함한 6개 목표 구간, 총 7구간을 만든다. 각 구간은 정확한 10초 창의 합성 관측 30개이며, S1/S2는 별도 recording/run key로 구분한다. S2에서도 S1 참조를 재사용한다.

F0/F_cal은 기존 `prepare_samples`를 통해 raw bbox/어깨 관측·고정 참조·공동 support·적격성을 계산한다. H5/H9/H9−F9는 임의의 유한 H 프레임 값으로 기존 H 집계/bridge를 재사용한다. 이 H 값은 센서/사람 자세를 모사하거나 실제 자료에서 추정한 값이 아니다. 모든 라벨/confirmed 상태는 합성 구조 검증용으로 사전 지정했다.

첫 P0를 제외하면 개발12개/독립24개 구간이다. 선정용 H9/H9−F9 및 기준선 포함 다섯 특징군의 공통 적격 key를 별도 추적했고 이 완전 합성 fixture에서는 두 집합이 일치했다. 5/6/8/9열을 그대로 사용하며 0 패딩·새 특징·특징군 프레임 교집합은 없다.

## 개발 → 합성 동결 → 독립 추론

1. `run_synthetic_pipeline(새경로)`가 개발2명의 값만 먼저 생성한다. 독립 값은 아직 생성하지 않는다.
2. 기존 `evaluate_development`로 개발2명 LOSO와 8개 승인 조합을 실행한다. **RF 500 trees, max_features=2, seed 0/1/2, M2 λ=0.5 및 LR B0 기존 설정을 그대로 사용했다.** 이전 단위 테스트의 tree=2 축소는 이 통합 실행에 적용하지 않았다.
3. 기존 5개 후보만 EXP-005/006의 우선순위·1e-12 동점 규칙으로 비교해 **합성 모델만 선택**한다. 정확도 목표나 원하는 후보를 만들기 위한 반복 탐색은 없다.
4. 선택 조합을 개발12개만으로 최종 합성 학습한다. RF 가중치가 필요하면 개발 자료에서만 기존 방식으로 계산한다. LR인 경우 scaler도 개발 자료에만 fit한다. 학습 참가자·key·입력 digest·scaler 통계를 audit에 남긴다.
5. 모델/학습된 전처리를 함께 pickle bundle로 저장하고 settings·class/feature order·seed·코드/모델 hash·학습 audit를 `SYNTHETIC_ONLY_freeze.json`에 기록한다. status=FROZEN은 기존 gate의 상태값이지만 **freeze_scope=SYNTHETIC_TEST_ONLY, formal_model_frozen=false**로 실제 동결과 구분한다.
6. 기존 `load_frozen_heldout`가 hash·설정·모델 파일·개발2/검증4 roster를 검증한 뒤에만 독립 fixture 생성 callback을 호출한다. 검증4명의 고정 P0는 그 참가자의 특징 보정 입력으로만 사용하며 모델/scaler 학습에 사용하지 않는다.
7. 이후에는 동결 bundle의 transform/predict만 호출한다. 기존 지표 함수로 pooled·참가자별·세션별 6-class Macro-F1/Accuracy/클래스 P/R/F1·support·오류를 계산한다. 후보 재선정·모델/scaler fit은 없다. 합성 클래스 누락 사례는 N/A/INCOMPLETE와 공식 Macro-F1 미산출, 별도 진단 점수를 확인한다.

실행 결과는 `development → synthetic freeze → held-out inference` 연결 성공이다. 이벤트 순서와 접근/fit 금지 검사는 테스트와 verification JSON에 남겼다. 합성 점수는 구조 검증 기록에만 저장하며 연구 정확도·일반화·논문 결과·실제 후보 우열의 근거로 사용하지 않는다.

## 검증 명령과 결과

기존 평가용 가상환경을 재사용했으며 패키지 설치나 환경 변경은 없다.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B -m unittest -q test_formal6_synthetic test_formal6_evaluation test_f0_fcal_features test_f0_fcal_evaluation test_f0_fcal_input test_f0_fcal_native test_capture_end_timing
```

**55 tests PASS**(신규 통합4개 포함). 다음으로 기존8열 평가기의 원래 suite를 별도 실행했다.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B -m unittest discover -s analysis/formal6_evaluator_20261030_93bd72 -p test_runner.py -q
```

**8 tests PASS**, 총 **63개 테스트 PASS**. 전체 저장소 감사/전체 회귀 실행이 아니라 관련 경로만 확인했다. 영구 합성 산출물 생성도 같은 500-tree 설정으로 별도 1회 수행했다.

검증 항목:

- 6인/개발2·독립4 분리, 개발12/독립24, 8개 조합·선정 후보5개, 공통 표본 정렬과 참조 P0 제외/별도 평가 P0 유지.
- 개발만 사용한 최종 합성 학습·학습 전처리 audit 및 동결 후 독립 접근 순서.
- 독립 추론 중 Forest.fit, LR.fit, StandardScaler.fit, rank_candidates를 금지 mock으로 감싸도 정상 추론됨.
- 클래스 누락 시 고정6/support·N/A/INCOMPLETE 보존 및 공식 Macro-F1 없음.
- 조기 접근, DRAFT, freeze hash·code hash·model hash·설정 불일치가 독립 payload 생성 전에 차단됨.
- 기존8열 synthetic-only 실행과 5-D-4~9 관련 단위/loader/native mock 경로에 회귀 없음.

## 남은 차단

이 하니스는 자체 생성 합성 pickle만 소비하며 실제 정식 artifact/외부 pickle을 받는 배포 경로가 아니다. 실제 QA·종료 marker/시간축·native/runtime·동일 인물 독립성·원천/선택 lineage 검증, 실제 최종 모델/전처리 artifact 및 코드 hash 동결과 승인된 독립 추론 운영은 여전히 필요하다. 누락률 상세 산식·IRB/재촬영/접근 운영·기타 실행 조건도 미해소다.

기존 8개 조합·설정·규칙, protected 모델/5-B·원본·스냅샷·capture 코드·frozen schema는 변경하지 않았다. 실제 참가자 분석·실제 최종 모델 선정·촬영·새 특징/탐색/ablation·전체 감사·commit/push 없음.
