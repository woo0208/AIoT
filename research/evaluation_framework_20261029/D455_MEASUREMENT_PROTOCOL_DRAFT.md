# 향후 D455 시스템 실측 프로토콜 초안 — 미실행 / 미승인

이 문서는 측정 방법과 경계를 정의하는 초안이다. 실행 명령·Registry·execution_id·새 승인 기록을 생성하지 않는다. CAP-007/009의 Patch 8 실행 보류와 Foundation §16.1을 유지한다. 개발 계측은 formal slot/round/ledger를 사용하지 않으며, formal semantics로 실행한 run을 사후 rehearsal로 바꾸지 않는다.

## 1. 실행 전에 고정할 대상

1. 개발 계측의 대상/동의/저장 범위, 담당자, 실제 device/USB/firmware/host 상태와 별도 실행 허가를 확인한다. 본 초안은 이 항목을 충족시키지 않는다.
2. 코드·모델·전처리·feature 순서·class 순서·runtime adapter·설정의 SHA-256을 고정한다. 과거 offline fold 모델을 실시간 배포 모델로 자동 승격하지 않는다.
3. 현재 보존된 5-B 모델은 `h9_m0.CLASS_ORDER=LAB5`인 **5-class M0 개발 artifact**다. 여기서 재사용한 5종/LR 표는 **6-class offline LOSO fold 모델**이다. 같은 이름 M0라도 같은 학습 객체나 같은 평가 범위가 아니다.
4. 현재 H9 runtime은 M0 artifact 경로다. LR/SVM/KNN의 정식 streaming artifact/adapter·입력 정합성은 이 작업에서 구현·검증하지 않았다. 다른 분류기를 연결하려면 별도 범위의 구현·감사·승인부터 필요하며 기존 5-B 후보를 수정하지 않는다.

## 2. 기존 5-B 후보 설정과 적용 한계

다음은 candidate_settings의 **설정값** 재기록이며 실측값이 아니다. 원본 설정을 변경하지 않는다.

| 항목 | 기존 후보 값 | 이번 문서의 상태 |
|---|---|---|
| 입력 | color 1280×720 BGR8 / depth 848×480 Z16 / 15 FPS / align=color | 실제 active profile 확인 전 |
| H9 runtime 창 | 4000ms window, 1000ms update, 2000ms stale | 잠정 개발 설정, 관측 latency 아님 |
| UI | main 2D+H9 summary panel, extra 3D/PyVista/F1 live/demo/CSV/추가 callback 비활성 | 기존 M0 baseline 후보 구성 |
| Warm-up | 처리 frame 150개, full-window aggregate 5호출, 실제 M0 inference 5호출을 각각 분리 | 각 단계별 독립 warm-up; partial collection 제외 |
| 반복 | 요청 90초×3회, 매회 새 process | 실제 run 시간·정지 overrun을 별도 기록 |
| 해석 적격 조건 | run별 warm-up 후 실제 M0 prediction ≥60, 세 run 각각 충족, 정상 duration 종료·cleanup | 기존 후보 규칙 그대로; 속도/정확도 PASS 기준이나 실행 허가가 아님 |

새 모델 비교에 같은 기간/횟수/창을 적용할지는 별도로 승인·고정할 사항이다. 이번 문서가 위 M0 규칙을 LR/SVM/KNN에 확장하거나 더 짧게 바꾸지 않는다. Nominal 15 FPS와 4초 창을 실측 FPS/첫 결과 지연으로 보고하지 않는다.

## 3. 측정 경계와 clock

같은 host의 동일 monotonic/perf-counter clock으로 아래 사건을 연결한다. UTC는 파일 식별용이며 duration 계산에 사용하지 않는다. 장치·host·브라우저 clock 차이를 직접 duration으로 사용하지 않는다. [Python clock 정의](https://docs.python.org/3/library/time.html#time.perf_counter_ns).

| 기호 | 사건 | 현재 관측/추가 확인 필요 |
|---|---|---|
| t_stream | streaming 측정 시작 | 기존 begin_stream 경계 |
| t_rx | RGB-D frameset 수신 성공 직후 | input_received; receive.wait 시간은 그 이전 별도 |
| t_geom | align/MediaPipe/depth·geometry 완료 | 기존 단계 timer와 source frame 연결 필요 |
| t_admit | geometry를 H9 runtime에 등록한 host 시각 | source_last_input_host_ms의 clock 의미. t_rx와 다름 |
| t_sched / t_dispatch | 계획 update 시각 / 실제 timer dispatch | scheduled_host_monotonic_ms / dispatch clock. missed periods/lag 함께 보고 |
| t_ready | aggregate·모델 실행이 끝나 새 예측이 준비됨 | 실제 완료 시각. generated_host_ms/tick 시작과 혼용하지 않음 |
| t_submit | 해당 prediction_id를 UI API에 처음 제출 | OpenCV imshow 경계. 첫 ready와 첫 displayed id가 다를 수 있음 |
| t_present | 그 결과가 실제 화면에 표시됨 | 현재 코드로 확인하지 않음; 외부 optical measurement/검증된 presentation trace 필요 |
| t_exposure / t_event | 센서 노출 / 실제 자세 변화 사건 | 현재 host 계측으로 확인하지 않음; clock mapping 또는 외부 공통 계측 필요 |

단계 구간은 receive wait, align/변환, Pose/Face inference, depth sampling/geometry, H9 등록·창 대기, aggregate, scaler+classifier, UI render/submit, 선택 I/O로 나눈다. 중첩 단계나 병렬 단계의 p95를 더해서 전체 p95를 만들지 않는다. 전체 latency는 동일 사건 쌍의 원시 duration에서 직접 계산한다.

현재 `h9.prediction_tick_to_ui_submit`은 dispatch/tick 경계부터 UI 제출까지이며 완성된 prediction의 ready→UI 전용 시간이 아니다. `h9.latest_window_input_to_ui_submit`은 **실제로 사용한 최신 common-valid 입력의 H9 admission**부터 UI 제출까지다. 둘 다 sensor-to-screen latency가 아니다.

## 4. CPU와 RAM

- process CPU는 native threads를 포함한 해당 process의 user+system CPU time 증가량을 wall time 증가량으로 나눈다. 1-core=100%와 logical CPU 수로 나눈 machine-normalized 값을 함께 보고한다. 전체 구간 평균은 전체 CPU delta/전체 wall delta를 사용하고, 1초 구간별 p50/p95도 원시 표본으로 남긴다.
- RAM은 process WorkingSetSize/RSS와 PrivateUsage(commit)를 구분한다. sampled RSS의 p50/p95/max, startup baseline 대비 증가량, OS lifetime peak를 각각 보고한다. PrivateUsage를 물리 RAM이나 모델 파일 크기로 부르지 않는다. [Windows 원시 계수 정의](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex).
- 현재 resource monitor는 약 1초 간격, startup/stream/shutdown phase다. **150-frame warm-up 제외 steady CPU/RAM을 자동 산출하는 phase는 없다.** 향후 steady resource 경계를 쓰려면 명시적 phase timestamp와 필터 규칙을 사전 정의·검증해야 한다. 기존 stage warm-up 제거만 보고 resource도 제거됐다고 추정하지 않는다.
- main process만 측정했으면 그렇게 명시한다. 별도 브라우저·child process·GPU memory는 기본 범위에서 제외된다. 향후 전체 앱 비용을 원하면 대상 PID/GPU 범위를 사전 선언하고 별도 열로 측정한다. 여러 process RSS의 단순 합은 shared-page 중복을 포함할 수 있어 엄밀한 총 RAM으로 부르지 않는다.
- 전원 모드·background load·threadpool·온도/클록 상태와 CPU/OS/RAM/device 정보를 기록한다. 1초 sampling이 놓치는 짧은 peak를 인정한다. 이번 offline 결과로 CPU/RAM을 추정하지 않는다.

## 5. FPS와 output rate

- 동일 stream 구간 T를 분모로 입력 delivered framesets/T, 고유 pair/T, 처리 완료한 고유 pair/T, 실제 새 prediction_id/T를 각각 보고한다.
- UI redraw count/T와 HOLDING 재표시는 예측률에 넣지 않는다. 입력 15 FPS와 1초 update cadence가 같거나 측정된 값이라고 가정하지 않는다.
- source/session identity로 중복·frame gap·counter regression·receive timeout·color/depth 누락·deadline skip·unfinished frame·missed timer period를 구분한다. source counter가 불명확하면 loss rate를 추정하지 말고 미확인으로 남긴다.
- 현재 processed_fps/delivered_input_fps는 **전체 stream(수집·warm-up 포함)** 기준이다. count를 steady 시간으로만 나누지 않는다. steady FPS가 필요하면 count와 시간 모두 같은 phase에서 별도로 확보하는 계측 설계를 먼저 검증한다.

## 6. 지연 지표를 세 층으로 보고

| 지표 | 시작→종료 | 포함 / 제외 |
|---|---|---|
| Model microbenchmark | 준비된 구간 raw feature→scaler+predict 반환 | 이번 실측 재사용. 영상·집계·창 대기 제외 |
| Host processing / prediction latency | t_rx→같은 frame UI 제출; 별도로 최신 실제 사용 입력 t_admit→해당 새 prediction 첫 t_submit | 후자는 H9 창 update 대기·계산·UI 지연을 포함하되 그 입력 이전의 geometry/센서 경로 제외 |
| First-output latency | t_stream 또는 collection 시작→첫 t_ready / 첫 t_submit | 창 채우기와 warm-up이 겹칠 수 있어 각각 측정. 최초 생성/최초 표시 id 별도 |
| Physical E2E / response latency | t_exposure 또는 사전 정의 자세 사건 t_event→t_present | 현재 미측정. 외부 공통 시계·고속 촬영/광학표식 등 별도 승인된 방법과 시작 사건의 정의 필요 |

지속 창의 최신 입력 age는 자세 변화 response time과 다르다. 처음 채우는 4초와 steady 결과 age도 다르다. Browser 사용 시 performance.now는 브라우저 내부 구간만 직접 계산하며, host/server와 결합하려면 clock mapping/round-trip 오차를 함께 검증한다. 실제 화면 표출을 확인하지 않으면 'UI 제출 latency'로만 표기한다.

새 prediction_id당 첫 UI 제출을 한 번만 세고 first-ready와 first-displayed를 분리한다. 늦게 표시되거나 표시되지 않은 예측도 누락·drop count로 남긴다. 분모를 성공 표시만으로 제한했으면 그 조건과 미표시 비율을 함께 보고한다. stale/insufficient/holding/실패/수동 reset은 무단 제외하지 않고 별도 상태 count로 보존한다.

## 7. run별 산출·해석

기존 M0 후보를 승인 후 측정하는 경우, 3개 run 각각 요청/실제 시간·overrun·상태·오류·적격 판정·원시 시간과 자원 표본을 새 exclusive 파일에 기록한다. 기존 파일을 덮어쓰지 않는다. 적격성에 실패해도 원시 통계를 보존하고 기준선 결론을 차단한다. run별 p50/p95와 n을 먼저 보고하고 run 간 변동을 별도로 제시한다. 세 p95를 평균하거나 stage p95 합계를 전체 p95로 바꾸지 않는다.

원하는 FPS/CPU/latency 목표값을 보고 threshold·창·gate를 조정하지 않는다. 시스템 자원 적격성·성능 수용 기준은 정식 평가 전 별도 결정할 사항이며, 기존 5-B 적격 조건을 과학적 정확도 기준으로 재해석하지 않는다.

## 8. 5-class / 6-class와 정식 평가 전 결정표

| 항목 | 현재 사실 | 정식 평가 전 필요한 결정 |
|---|---|---|
| primary5 | P0 upright, P1 forward_head, P2 lean_back, P3 lean_left, P4 lean_right; 기존 primary5 evaluator는 P5를 fit/metrics에서 제외 | 주 평가 범위와 P5의 역할·보조 분석 승인 명시 |
| auxiliary6 | 이번 두 파일럿 5종·LR 비교는 P5 lean_forward 포함 K=6, 24구간 | 6-class를 정식으로 채택할지, 별도 보조 평가로 남길지 승인·고정 |
| 범위 비교 | K=5와 K=6은 task/학습 모델/표본/분모가 다름 | 같은 표의 직접 순위로 혼합하지 않기; 비교한다면 각각 별도 트랙 |
| 재평가 | 6-class 행렬의 P5 행/열 삭제는 5-class 재학습 평가가 아님 | 기존 6-class 점수로 primary5 성능을 새로 만들어 주장하지 않기 |
| 데이터 분리 | 파일럿 P01/P02는 반복 탐색에 사용됨 | 독립 개발/검증 역할·최종 4명 자료의 봉인·개방 시점·사용 권한 |
| 특징/집계/포함 | H9/H9-v2는 현재 탐색 구현이며 C3는 depth/hip 관측에 의존 | exact 특징·좌표·결측·support·라벨·framing·포함/제외/전환 정책을 해당 연구 권위에서 고정 |
| 분할·표준화 | 현재 참가자 LOSO, train-only scaler, seed 0~4 | 여러 학습 참가자를 가진 정식 split, scaler/feature 선택 leakage 방지, seed·모델·평가 정의 |
| 지표·통계 | pooled per-seed F1 및 참가자별 보조 지표; n=2 | 클래스 support=0 처리·참가자 집계·불확실성 산출 단위·오류별 분모·사전 수용 기준 |
| 실측/배포 | offline fold 모델과 5-B 5-class M0 artifact는 구분됨 | frozen 배포 artifact, 입력/class 순서, adapter 구현 검증, 시스템 workload·자원/clock/화면 경계 |
| 승인·Foundation | CAP-007/009 실행 보류, formal D455 측정품질 미판정 | 윤리/동의, 독립 개발 계측 승인, formal Patch 8의 별도 registry/code-pin/사전 등록 게이트 처리 |

OPEN/DEFERRED 연구 결정을 이 초안으로 해소하지 않는다. Foundation Patch 8의 frozen grid·threshold·window·gate·ledger 규칙은 바꾸지 않으며, 정식 측정품질·분류 성능·시스템 효율은 서로 다른 주장으로 유지한다.
