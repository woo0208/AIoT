# 논문용 평가 지표 정의표 — 기존 결과 정리 / 정식 평가 전 초안

본 문서는 기존 2인 파일럿 결과를 설명하는 정의와 향후 실측 제안을 구분한다. 새 scientific schema, 정식 평가 freeze, 실행 승인 또는 CAP-007 보류 해제가 아니다.

## 분류 성능

혼동행렬 `C[i,j]`는 실제 i, 예측 j의 **구간 수**다. `N=sum(C)`, `TP_k=C[k,k]`, `FN_k=sum_j C[k,j]−TP_k`, `FP_k=sum_i C[i,k]−TP_k`. 이번 자료의 표본 단위는 적격 자세 구간이며 프레임이 아니다. [정의 참고: sklearn Precision/Recall/F-score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_fscore_support.html).

| 지표 | 정의 / 분모 | 현재 결과 집계 | 논문에 함께 표시할 조건 |
|---|---|---|---|
| Support | 실제 클래스 구간 수 `TP+FN` | 전체 클래스당 4, 참가자별 2 | 참가자 수=2, 총 구간=24, 적격/제외 수 |
| Accuracy | `trace(C)/N` | 각 seed의 24개 OOF 예측에서 계산 후 5 seeds 평균 | 6-class, participant LOSO, seed SD(ddof=0) |
| 클래스 Precision | `TP/(TP+FP)` | 클래스별 seed 지표 평균; 예측 support=0이면 0 | 실제/예측 support도 병기. 높은 Recall만으로 우수성 판단하지 않음 |
| 클래스 Recall | `TP/(TP+FN)` | 클래스별 seed 지표 평균 | P0/P1/P5를 포함한 전 클래스; 실제 support=0의 정책은 아래 한계 참조 |
| 클래스 F1 | `2TP/(2TP+FP+FN)` | 클래스별 seed 지표 평균 | 0회 예측이면서 실제 support가 있으면 0 |
| 전체 Macro-F1 | **seed별 두 test fold의 24개 OOF를 합친 행렬 → 여섯 클래스 F1 평균 → 5 seeds 평균** | 본 성능 표의 주 F1 | 참가자 F1 평균 또는 seed 합산 행렬의 F1로 대체하지 않음 |
| 참가자별 Accuracy/F1 | 해당 참가자 12개 OOF만 사용 | 각 참가자·seed 계산 후 5 seeds 평균 | 학습 참가자와 시험 참가자의 방향을 명시 |
| 참가자 동등 평균 F1 | 참가자별 Macro-F1 평균 | 별도 보조열; 전체 pooled F1과 다름 | 이름을 `participant_mean_macro_f1`로 구분 |
| 혼동행렬 | 행=실제, 열=예측, 순서 P0…P5 | seed별 정수 행렬 원문 보존; 보고서에는 seed count 평균 | 평균 행렬의 소수는 반복 평균이며 새로운 표본이 아님 |
| P0/P1/P5 방향 오류 | `C[i,j] / sum_j C[i,j]` | i∈{P0,P1,P5}, j≠i의 모든 방향을 같은 long 형식으로 출력 | seed별 count·support·rate 및 seed 평균/SD; 0건도 보존 |
| Seed SD | 동일 표본의 5개 seed 지표의 모집단 SD | ddof=0 | 참가자 간 변동·인구 일반화 CI·유의성으로 해석하지 않음 |

Macro-F1은 support 가중평균이나 micro-F1이 아닌 클래스 F1의 비가중 평균이다. [sklearn F1 정의](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.f1_score.html).

현재 `rf.macro_f1`은 실제 support=0인 클래스를 건너뛴다. 제공된 6-class 결과는 모든 클래스의 실제 support가 있으므로 이 분기 영향이 없다. 정식 평가에서 클래스 support가 없는 참가자/폴드를 어떻게 표시·집계할지는 명시적으로 결정해야 한다. 이번 정리는 기존 평가 함수를 변경하거나 그 미래 정책을 임의로 확정하지 않는다.

## 계산 효율과 시스템 지표

| 지표 | 동일 비교 기준 / 단위 | 현재 근거 상태 | 해석 경계 |
|---|---|---|---|
| 표준화 포함 분류 p50/p95 | 미리 집계된 raw `1×d` 입력에서 `scaler.transform + classifier.predict`; ms/call | 기존 host microbenchmark 실측 재사용 | M0는 scaler 없음, 원시 H9 유지. 영상·특징 계산·집계·UI·startup·I/O 제외 |
| 전체 분류 패키지 직렬화 크기 | `len(pickle.dumps({'classifier':model,'scaler':scaler}, protocol=5))`; 비압축 bytes와 KiB | 기존 인메모리 직렬화 길이 재사용 | scaler와 분류기를 포함. MediaPipe 모델·라이브러리·SDK·코드·전체 앱·RAM은 제외 |
| CPU 1-core 기준 | `100×Δ(process user+system CPU time)/Δ(host wall time)`; % | **D455 실측 미수행** | 여러 CPU thread면 100% 초과 가능; wait는 wall 분모에는 포함되나 CPU time에는 포함되지 않음 |
| CPU machine-normalized | 위 값을 logical CPU 수 L로 나눔 | **D455 실측 미수행** | OS task-manager 표시와 분모를 명시적으로 맞춰야 함 |
| RAM working set / RSS | 현재 프로세스 resident working set, MiB=`bytes/2^20` | **D455 실측 미수행** | Windows WorkingSetSize; Python heap만의 크기가 아님 |
| Private committed memory | Windows PrivateUsage, MiB | **D455 실측 미수행** | private commit charge이며 실제 물리 RAM 사용량과 같은 지표가 아님 |
| Peak memory | 측정 구간의 sampled RSS max, OS lifetime PeakWorkingSetSize를 별도 표시 | **D455 실측 미수행** | 1초 간격 sampling은 짧은 spike를 놓칠 수 있고 lifetime peak에는 startup이 포함될 수 있음 |
| 전체 처리 FPS | 고유 RGB-D pair 처리 완료 수 / 동일 host stream 경과초 | **D455 실측 미수행** | nominal 입력 FPS·UI redraw FPS·분류 update rate와 구분 |
| 신규 예측률 | 고유 PREDICTED prediction_id 수 / stream 경과초 | **D455 실측 미수행** | HOLDING/재표시/실패 호출 제외, FPS와 다른 단위 |
| Host frame latency | pair host receive→그 frame의 UI 제출, ms | **D455 실측 미수행** | 센서 노출·실제 화면 표시를 포함하지 않음 |
| H9 최신 사용 입력 latency | 실제 common-valid 입력의 H9 admission→해당 새 예측 첫 UI 제출 | **D455 실측 미수행** | 현재 source_last_input_host_ms는 geometry 이후 H9 admission clock이지 카메라 receive clock이 아님 |
| 첫 예측 대기 | stream/collection 시작→첫 PREDICTED 준비 및 첫 UI 제출을 각각 측정 | **D455 실측 미수행** | 4초 창 설정값을 실제 지연으로 대체하지 않음 |
| 물리 sensor-to-display E2E | exposure/실제 자세 사건→화면 실제 표시; 공통 clock 또는 외부 광학 계측 필요 | **미측정 / 현재 UI 계측만으로 산출 불가** | 장치 timestamp−host/browser clock을 그대로 빼지 않음 |

현재 process CPU clock과 단조 clock의 의미는 [Python time 문서](https://docs.python.org/3/library/time.html#time.process_time_ns)를 따른다. Windows working set·peak·private commit은 [PROCESS_MEMORY_COUNTERS_EX 정의](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex)를 구분해 사용한다.

## 동일 출력 형식

모든 결과는 `experiment_id / configuration_id / scope / class_set / feature_set / K / participant_count / sample_count / seed / measurement_status / source_hash`를 갖는 구분으로 묶는다.

- `performance.csv`: configuration×전체/참가자별 Accuracy·F1·P0/P1/P5 Recall.
- `class_metrics.csv`: configuration×scope×class의 Precision/Recall/F1/support.
- `confusion_matrices.csv`: configuration×scope×actual×predicted의 seed 평균 count, `seed_confusion_matrices.csv`에는 원시 seed 정수 count.
- `major_errors.csv`: 실제 P0/P1/P5의 모든 오답 방향에 대한 동일 count/support/rate 형식.
- `efficiency.csv`: 표준화 포함 p50/p95와 전체 분류 패키지 bytes/KiB, batch와 전처리 표시.
- `diagnostic_summary.csv`: 기존 LR A/B 오류 3건의 점수·확률·margin. 개별 관측을 다루므로 로컬 참고자료이며 성능 표의 추가 표본으로 합치지 않음.
- `measurement_status.csv`: 실측 재사용/설정값/미측정/설계만 존재를 구분. 미측정 숫자는 null로 보존하고 0으로 채우지 않음.

5종 비교의 LR-H9와 특징 비교의 A는 같은 구성·동일 예측의 재현 기록이다. 다른 batch provenance를 보존하되 두 결과를 독립 표본처럼 합산하지 않는다. LR 진단은 재현된 같은 모델의 설명 자료이며 새 모델 후보가 아니다.
