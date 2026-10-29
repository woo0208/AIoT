# Logistic Regression 특징 구성 1차 비교

participant_1/participant_2 기존 2인 파일럿의 6-class 탐색 결과다. 최종 모델 선정이나 일반화 검증으로 주장하지 않는다. 4명 최종 독립 검증 자료는 열람·사용하지 않았다.

## 입력·비교 조건

- A: H9 원본 F1~F9, 9차원.
- B: A의 F9 열만 제거한 F1~F8, 8차원. 재집계나 표본 재선택 없음.
- C: 기존 H9-v2 loader/aggregation이 반환하는 F1~F8+C3, 9차원. C3는 기존 sagittal_torso_lean_deg이며 수식·유효성·집계 규칙을 바꾸지 않음.
- 기존 적격 24구간(참가자당 12, 각 클래스당 참가자별 2), 6 classes P0~P5, 동일 라벨·표본 순서·참가자 LOSO.
- participant_1 학습→participant_2 검증, participant_2 학습→participant_1 검증. 각 학습 fold는 12구간.
- 기존 성공 평가 코드 compare_fixed.py를 byte-identical baseline.py로 복사하여 LR 생성기, 원본 H9 loader, fold/metric/summary 함수를 직접 재사용. H9-v2도 기존 소스 snapshot을 수정 없이 사용.
- LR: C=1, L2(l1_ratio=0), solver=lbfgs multinomial, tol=1e-4, max_iter=10000, class_weight=None, fit_intercept=True. 전체 API 인수는 PLAN.json에 보존.
- seed=0,1,2,3,4 고정. 각 조건·학습 fold에서만 StandardScaler를 fit하고 검증에는 transform만 적용. 튜닝·추가 모델 비교 없음.
- 모델 생성 전에 PLAN.json과 3개 입력 행렬을 배타 생성해 고정. 신규 실행 코드는 evaluate.py, 결측/정렬/표준화 최소 구조 검사는 test_controls.py.

## 공통 표본·support 확인

세 조건 모두 원래 24구간을 유지했다. C3 결측 frame cell=0, H9/H9-v2 공통 유효 frame 합=3,613이며 24구간 모두 frame index 집합이 정확히 같다. C3의 적격 조건을 맞추기 위한 보정·대체·구간 제외는 없었다. F1~F8 집계값도 A/B/C에서 정확히 같았다.
따라서 B−A는 이 고정 LR에서 F9를 제거한 구성 차이, C−B는 C3를 추가한 구성 차이다. C−A는 F9→C3 교체 효과다. 이 파일럿에서 통제된 구성 비교이지 특징의 보편적 유용성이나 해부학적 측정 타당성의 인과 증거는 아니다.

## 지표 계산 방식

각 seed에서 두 LOSO의 24개 OOF 예측을 합친 6×6 혼동행렬로 클래스 F1_k=2TP/(2TP+FP+FN)를 구하고 여섯 F1의 평균을 전체 Macro-F1로 계산했다. 보고값은 다섯 seed 지표의 평균이다. 참가자별 Macro-F1은 각 12구간에서 별도로 계산하며 전체 Macro-F1과 혼용하지 않는다.
모든 조건에서 seed별 예측은 동일했다. seed SD는 모두 0(부동소수점 반올림 수준 제외)이며, 이는 추가 참가자나 일반화 신뢰도를 의미하지 않는다. 독립 참가자는 2명, 관측 구간은 24개다.

## 전체 성능

단위 %, 차이는 A 대비 pp.

|조건|특징|Accuracy|Macro-F1|P0 Recall|P1 Recall|ΔAccuracy|ΔMacro-F1|
|---|---|---|---|---|---|---|---|
|A|original H9 F1..F9|87.50|86.84|50.00|75.00|+0.00|+0.00|
|B|same H9 matrix with F9 column removed; no reaggregation|87.50|86.84|50.00|75.00|+0.00|+0.00|
|C|native H9-v2 F1..F8+C3, unchanged existing calculation and aggregation|83.33|82.01|50.00|50.00|-4.17|-4.83|

A는 기존 5종 비교 LR의 모든 seed·구간 예측, 전체/참가자별 모든 지표, 10개 학습 fold scaler mean/scale을 정확히 재현했다. B도 A와 모든 구간·seed의 예측이 같다.

## 참가자별 결과

시험 참가자 participant_1은 participant_2로 학습, participant_2는 participant_1로 학습했다.

|시험 참가자|조건|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|ΔMacro-F1 vs A pp|
|---|---|---|---|---|---|---|
|participant_1|A|83.33|82.78|50.00|50.00|+0.00|
|participant_1|B|83.33|82.78|50.00|50.00|+0.00|
|participant_1|C|83.33|82.78|50.00|50.00|+0.00|
|participant_2|A|91.67|91.11|50.00|100.00|+0.00|
|participant_2|B|91.67|91.11|50.00|100.00|+0.00|
|participant_2|C|83.33|82.78|50.00|50.00|-8.33|

C는 participant_1에서 A/B와 모든 예측이 같았고, participant_2 Accuracy 91.67%→83.33%, Macro-F1 91.11%→82.78%, P1 Recall 100%→50%로 낮아졌다. 두 참가자에게 동일한 방향의 악화가 관찰된 것은 아니다.

## P0/P1 오분류 변화

전체 P0 실제 support=4, P1 실제 support=4다. 아래 건수는 seed당 값이며 다섯 seed에서 동일하다.

|조건|P0→P1|P0→P2|P1→P0|P1→P5|P0 정답|P1 정답|
|---|---|---|---|---|---|---|
|A|1.0|1.0|1.0|0.0|2/4|3/4|
|B|1.0|1.0|1.0|0.0|2/4|3/4|
|C|1.0|1.0|1.0|1.0|2/4|2/4|

A/B: P0→P1 1건, P0→P2 1건, P1→P0 1건. C: 이 오류는 그대로이고 P1→P5 1건이 추가됐다. P0 Recall은 세 조건 모두 50%로 개선되지 않았다.
추가 오류는 **participant_2 P1 segment, 실제 P1** 한 구간이다. A/B는 seed 0~4 모두 P1, C는 모두 P5를 예측했다. 다섯 번의 독립 오류가 아니라 같은 구간의 반복 예측이다. P2~P5 실제 클래스의 Recall은 세 조건 모두 100%이며, C에서 P1→P5가 추가돼 P5 Precision은 100%→80%가 된다.

## 혼동행렬

행=실제 P0~P5, 열=예측 P0~P5. 다섯 seed가 모두 같아 아래 행렬은 각 seed의 정수 count와 같다. 전체 행 합=4, 참가자별 행 합=2. 모든 클래스의 Precision/Recall/F1도 results.json에 보존했다.

### pooled / A

```text
       P0 P1 P2 P3 P4 P5
P0     2  1  1  0  0  0
P1     1  3  0  0  0  0
P2     0  0  4  0  0  0
P3     0  0  0  4  0  0
P4     0  0  0  0  4  0
P5     0  0  0  0  0  4
```

### pooled / B

```text
       P0 P1 P2 P3 P4 P5
P0     2  1  1  0  0  0
P1     1  3  0  0  0  0
P2     0  0  4  0  0  0
P3     0  0  0  4  0  0
P4     0  0  0  0  4  0
P5     0  0  0  0  0  4
```

### pooled / C

```text
       P0 P1 P2 P3 P4 P5
P0     2  1  1  0  0  0
P1     1  2  0  0  0  1
P2     0  0  4  0  0  0
P3     0  0  0  4  0  0
P4     0  0  0  0  4  0
P5     0  0  0  0  0  4
```

### participant_1 / A

```text
       P0 P1 P2 P3 P4 P5
P0     1  0  1  0  0  0
P1     1  1  0  0  0  0
P2     0  0  2  0  0  0
P3     0  0  0  2  0  0
P4     0  0  0  0  2  0
P5     0  0  0  0  0  2
```

### participant_1 / B

```text
       P0 P1 P2 P3 P4 P5
P0     1  0  1  0  0  0
P1     1  1  0  0  0  0
P2     0  0  2  0  0  0
P3     0  0  0  2  0  0
P4     0  0  0  0  2  0
P5     0  0  0  0  0  2
```

### participant_1 / C

```text
       P0 P1 P2 P3 P4 P5
P0     1  0  1  0  0  0
P1     1  1  0  0  0  0
P2     0  0  2  0  0  0
P3     0  0  0  2  0  0
P4     0  0  0  0  2  0
P5     0  0  0  0  0  2
```

### participant_2 / A

```text
       P0 P1 P2 P3 P4 P5
P0     1  1  0  0  0  0
P1     0  2  0  0  0  0
P2     0  0  2  0  0  0
P3     0  0  0  2  0  0
P4     0  0  0  0  2  0
P5     0  0  0  0  0  2
```

### participant_2 / B

```text
       P0 P1 P2 P3 P4 P5
P0     1  1  0  0  0  0
P1     0  2  0  0  0  0
P2     0  0  2  0  0  0
P3     0  0  0  2  0  0
P4     0  0  0  0  2  0
P5     0  0  0  0  0  2
```

### participant_2 / C

```text
       P0 P1 P2 P3 P4 P5
P0     1  1  0  0  0  0
P1     0  1  0  0  0  1
P2     0  0  2  0  0  0
P3     0  0  0  2  0  0
P4     0  0  0  0  2  0
P5     0  0  0  0  0  2
```

## 표준화 포함 모델 추론 비용

동일 host·process, BLAS/OpenMP 1 thread, gc 비활성 측정 구간, perf_counter_ns. 이미 집계된 1×d raw 특징 한 개에서 StandardScaler.transform+LR.predict를 함께 측정했다. 조건별 각 fold×seed마다 24회 warm-up 뒤 120회, 총 1,200회다. 조건 순서를 회전하고 round-robin으로 측정했다. 프레임 특징 계산·집계·카메라·UI·startup·I/O는 제외한다.

|조건|차원|scaler+LR p50 ms|p95 ms|평균 ms|scaler+LR pickle bytes|
|---|---|---|---|---|---|
|A|9|0.1081|0.1486|0.1164|1684|
|B|8|0.1082|0.1546|0.1162|1612|
|C|9|0.1080|0.1615|0.1162|1684|

B의 p50은 A보다 0.0001ms 길고, C는 A보다 0.0001ms 짧다. 이런 미세 차이를 실제 속도 개선·열화로 해석하지 않는다. 약 0.108ms 수준의 구현 호출 비용은 거의 같았다. 이전 실험의 scaler+LR p50 0.1130ms와 이번 A의 0.1081ms 차이도 별도 시점·측정 순서의 차이가 있으므로 개선으로 주장하지 않는다.
모델 크기는 동일 비압축 pickle protocol=5로 scaler와 classifier를 함께 직렬화한 길이로, B는 A보다 72bytes(약 4.28%) 작다. 직렬화 객체를 파일로 저장하거나 5-B 모델을 교체하지 않았다. 이 값은 라이브러리 크기·RAM 또는 D455 전체 성능이 아니다.

## 후속 개선 가치와 한계

**B(F9 제거)는 간소화 후보로 유지할 가치가 있다.** 이 파일럿의 모든 예측·지표를 유지하면서 9→8차원, scaler+모델 객체 1,684→1,612bytes로 줄었다. 다만 성능 향상도 추론시간 단축도 확인되지 않았다. F9가 일반적으로 불필요하다거나 독립 참가자에서 동등하다고 단정하지 않는다. A는 기존 기준선으로 보존한다.
**C(H9-v2)는 이번 LR 개선 후보로 우선할 근거가 없다.** A/B 대비 전체 Accuracy −4.17pp, Macro-F1 −4.83pp, P1 Recall −25pp이며 P0 Recall 이득은 없다. 손실은 participant_2의 한 P1 구간에 집중됐다. C3 관측 결측이나 공통 support 차이가 이번 차이를 설명하지 않지만, C3 자체가 보편적으로 해롭다거나 실패 원인이 특정 체형/촬영 조건이라고 주장할 수 없다.
여러 차례 재사용한 2인·24구간 파일럿이며 train fold마다 참가자는 한 명이다. 같은 자료에서 후보를 골랐으므로 독립 검증이 아니다. 최종 독립 4명 자료는 이번 선택·분석·튜닝에 사용하지 않았고, 최종 모델 선정·설정 변경도 하지 않았다. 기존 H9/H9-v2/M0/M1/M2/M3-G 및 5-B 계약은 그대로 유지한다.


## Sharing and archived code

Only aggregate results, historical evaluator and tests are shared. No raw CSV/recording, feature matrix, segment prediction, fitted scaler/model or host path is included. Diagnostics are separate local-only work and are not in this commit. Archived scripts require the original private plan/dataset/source/input bundle; do not fabricate missing inputs. Run python -B verify_public.py and python -B -m unittest -v test_public.py for saved-result verification without fitting.
