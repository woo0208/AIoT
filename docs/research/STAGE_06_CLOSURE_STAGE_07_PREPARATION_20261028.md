# 연구 6단계 종료 / 7단계 준비 — 2026-10-28

상태: **6단계 파일럿 탐색 종료, 추가 정확도 튜닝 중단. 7단계는 정식 연구 준비만 진행 가능. 정식 촬영·평가 실행 승인 아님.** 이번 사용자 지시에 따른 종료 기록이다. 기존 코드·데이터·결과·canonical 문서는 변경하지 않는다. 연구 단계 번호와 Foundation Patch 번호는 다르다.

## 종료 결정과 근거

- 현재 파일럿 기준선은 **H9+M0**다. primary5, P01/P02 동일 20구간, 참가자 LOSO, seeds 0~4, 500 trees, max_features=2의 기존 결과는 Accuracy 87.00%, Macro-F1 86.75%, P1 Recall 75.00%, Precision 69.00%다. 독립 검증·정식 성능·최종 특징 계약은 아니다.
- H9-v2+M0는 Accuracy 81.00%, Macro-F1 79.57%, P1 Recall 55.00%다. 같은 support/F1~F8에서 F9→C3 교체 구성의 pooled 성능이 낮아졌으나 참가자 방향은 달랐다(P01 F1 −21.87pp, P02 +6.40pp). 표현 전체의 우월성은 확인되지 않았다.
- M1은 두 표현 모두 M0와 예측 동일. M2(λ=0.5)는 H9에서 Accuracy 78.00%/F1 75.70%, H9-v2에서 77.00%/73.72%로 각 M0보다 낮았다. 모델 정의와 비교 역할을 유지하며 성능에 맞춰 λ/가중치를 바꾸지 않는다.
- H9-v2+M3-G는 Accuracy 50.00%/F1 47.60%. 실제 C3 split 비율은 M0 11.33%→M3-G 33.23%, 시험 경로 방문률은 24.15%→58.94%다. 평균 C3 split 깊이는 1.186→1.206으로 더 얕아지지 않았다. P01의 P0/P1/P3→P3, P02의 같은 자세→P1 쏠림과 실제 C3 라우팅/leaf 확률의 연관은 확인됐다.
- **원인 가설은 별도다:** 참가자/촬영 조건에 민감한 C3를 자주 노출해 비일반화 규칙을 증폭했을 가능성은 관측과 부합한다. C3만의 인과 효과, 체형/카메라/실제 자세/측정 오차 중 원인은 미확인이다. M3-S 등 미평가 변형으로 일반화하지 않는다.
- Depth 검토에서는 primary5 2,951프레임 중 10개 스파이크형 후보를 메모리에서 제외했을 때 최대 구간 집계 변화가 F7 0.125mm, F9 0.00146(무차원), F6/F8 0이었다. 기존 중앙값이 단발 이상값의 영향을 대부분 억제하므로 **자동 Depth 필터 구현은 보류**한다. 이는 모든 Depth 오류가 제거됐다는 뜻이 아니다. finite validity만으로 이상값은 차단되지 않으며 지속 편향은 미측정이다.
- 구간 양끝 각 1초 제외 시 F3 최대 1.77° 변화는 자세/라벨 경계 민감도다. 해당 프레임을 확정 오류로 판정하거나 실제 특징에서 삭제하지 않는다. 현재 추가 필터·특징·모델 튜닝을 진행하지 않는다.

근거: [6단계 상세 결과](../../analysis/h9/stage6_20261028/REPORT.md), [검증 기록](../../analysis/h9/stage6_20261028/verification.json), [Depth 검토 결과](../../analysis/h9/quality_review_20261028/results.json). 새 학습·정확도 재계산 없이 저장 결과만 인용했다.

## 보존 대상과 확인 범위

- 기준 Git HEAD `0bdd2a4a22d6d05c6ce0915950966c0ecc51037a`, branch `feat/mediapipe-master-v1.2`에 **현재 작업 트리 내용**을 함께 보존해야 한다. HEAD만으로 미커밋 구현을 복구할 수 없다.
- 기존 수정 파일 `f1_sample_aggregator.py`, `h6_offline.py`; 미추적 `h9_v2.py`, `h9_v2_loso.py`, `m3_g.py` 및 `test_h9_v2.py`, `test_h9_v2_loso.py`, `test_h9_v2_offline.py`, `test_m3_g.py`를 보존한다. 관련 RF/geometry/live 코드·테스트와 model lock/runtime artifacts도 목록에 포함했다.
- ignored `analysis/h9/` 전체: 이전 설계/ablation/분할 진단, 기존 H9-v2 primary5 평가, 6단계의 사전 기록·evaluate.py·summarize.py·원 결과/요약/verification JSON, Depth inspect_quality.py·결과 JSON을 함께 보존한다. 평가 스크립트를 검증용으로 재실행하면 학습을 수행할 수 있으므로 이번 종료 작업에서는 실행하지 않았다.
- ignored `captures/` 전체와 기존 root `h6*.json`을 보존한다. 기준선 입력은 P01 `170900`, P02 `173954` 성공 CSV 및 각 face/upper13/session sidecar이며 다른 시도와 합치지 않는다. 기존 다른 시도도 원본 그대로 별도로 남긴다.
- [보존 목록 JSON](STAGE_06_PRESERVATION_20261028.json)에 파일별 SHA-256/크기와 Git 상태를 기록한다. 기존 기록의 24개 파일 참조 해시가 모두 일치함을 확인했다. 이것은 보존 대상의 현 상태 확인이며 별도 백업·Git 반영 완료가 아니다. ignored 파일은 일반 commit/push로 보호되지 않는다. 과거 촬영 환경/모델 이력을 현재 파일 해시로 소급 확정하지 않는다.

## 정식 촬영·평가의 차단 조건

1. IRB/동의·연구 및 촬영 승인, 참가자 identity 관리가 선행되어야 한다. 이번 종료로 신규 촬영은 승인되지 않는다.
2. EXP-002가 요구하는 Foundation 완료와 EXPERIMENT_PROTOCOL freeze가 필요하다. **Patch 8은 CAP-007/009에 따라 EXECUTION DEFERRED**, 정식 D455 측정품질은 미판정이다. 실행 승인·코드 고정·사전 등록 등 기존 governance 없이 촬영/검증을 시작하지 않는다.
3. OPEN-002/003/005의 미해결 범위: 정식 특징/좌표/결측·집계 계약, 촬영/라벨·전환·framing, 참가자/라운드 수, 포함/제외, 독립 개발/평가 분리, LOSO/seed/지표/모델·λ 정책을 승인·고정해야 한다. 파일럿 조건이 자동으로 정식 조건이 되지 않는다. p=9 rank 정책은 FEAT-010에서 해결된 사항이며 다시 OPEN으로 취급하지 않는다.
4. engineering H9 입력→canonical raw/analysis/model-lock lineage, dataset role·selection manifest·formal output 연결을 확정하고 필요한 연결 구현을 별도 범위로 검증해야 한다. 기존 frozen schema를 암묵적으로 확장하지 않는다.
5. 파일럿을 재사용하지 않는 독립 참가자 평가와 촬영 조건/측정품질 판정 계획이 필요하다. 최종 external은 method freeze 전 봉인한다. primary5를 유지하며 별도 승인 없는 6-class 평가는 수행하지 않는다.

## 기존 실시간 코드의 처리시간 측정 지점

현재 `posture_geometry_probe.py` RF 데모는 **프레임별 F1-5**다. 구간 집계 H9+M0가 이미 실시간으로 연결됐다고 간주하지 않는다. H9 온라인 집계 창/출력 시점/모델 artifact 연결은 별도 미정 사항이다. 아래는 정적 소스에서 식별한 계측 경계이며 실제 측정값이나 병목 판정이 아니다.

| 구간 | 기존 코드의 전후 계측 경계 |
|---|---|
| 시작 비용 | probe:2136 모델 artifact load/검증; :2192~2197 MediaPipe 생성. steady-state와 분리 |
| 수신 대기 | probe:2223 `pipeline.wait_for_frames()` 전후. 대기를 계산 처리시간과 분리 |
| 정렬·입력 변환 | probe:2225 `align.process()`; :2231~2234 array/BGR→RGB/mp.Image 생성 |
| Pose/Face 추론 | probe:2242 `run_frame_inference()` 전체 및 :590/591 각 `detect_for_video()` 전후 |
| 선택적 F1 경로 | probe:2266 `face_detector.detect()`와 :2265 `compute_live_f1()`; :1397 함수의 F1-5 계산. 전체/내부 시간을 중복 합산하지 않음 |
| RF 예측 | probe:2273 `rf_demo_frame()` 및 :1656 `state.model.predict()`; 실제 순회는 f1_demo_rf:194. F1-5 데모 시간으로 명시 |
| Depth·XYZ·H9 기하 | probe:2274~2304 pose/face sampling→chest ROI→deprojection→compute_candidate_geometry. 내부 샘플링은 posture_geometry:632/388 |
| 시각화 | probe:2305~2329 overlay/panel/OpenCV/선택적 3D·PyVista. 화면 옵션별 비용 분리 |
| 출력 I/O | probe:2248 upper13 writerows+flush, :2344/:2358 CSV writerow+flush, :2369 waitKey. 계산 중간의 upper13 I/O도 빠뜨리지 않음 |
| 웹 전달·렌더 | probe:2333 callback→run_mesh_avatar:52 publisher→mesh_avatar_bridge:289 publish/:305 HTTP; app.js:480 poll/fetch, :551 frame/render. `POLL_MS=33`에 요청 소요시간이 더해짐. latest-only store이므로 생성/수신/중복·누락 frame_id와 stale age를 구분 |
| H9 구간 집계 | f1_sample_aggregator:431/446 기존 집계 함수는 offline에서 사용. 향후 실제 연결 시 함수 시간과 창을 채우는 대기시간을 별도 측정 |

`live_f1_d455.py:302`의 별도 preview_loop도 wait_for_frames(:319), align(:321), Face/Pose(:331/332), geometry(:336), F1 계산(:347), display(:348)로 구분할 수 있으나 해당 loop에는 RF 예측이 없다.

향후 계측은 같은 host의 monotonic/perf_counter_ns, 브라우저의 performance.now로 **각 clock 안의 구간 시간**을 측정한다. 장치 timestamp·UTC·브라우저 clock을 직접 빼서 sensor-to-screen 지연을 주장하지 않는다. frame_id로 연결하고 clock 기준을 정의한다. startup/warm-up과 steady-state, 카메라 wait와 compute, 옵션별 I/O/UI를 분리하며 p50/p95/p99, 고유 프레임 처리율·누락률을 보고한다. 15 FPS의 66.7ms는 nominal frame 간격이지 현재 성능 실측값이 아니다. H9 창 지연은 별도다.

## 다음 작업과 이번 변경

다음 작업은 연구자가 위 차단 조건과 실시간 평가 범위를 결정하고, **새 최적화 없이 계측만 하는 별도 작업의 범위**를 고정하는 것이다. 현 단계에서 모델 학습·정확도 재평가·실시간 실행·카메라 접근·새 최적화·전체 테스트·commit/push는 하지 않았다. 기존 42개 테스트 PASS는 과거 실행 기록이며 이번에 재실행하지 않았다.

이번에 새로 만든 파일은 본 종료 기록과 보존 목록 JSON 두 개뿐이다. 기존 코드·데이터·분석 결과·연구 결정 문서는 그대로다. 이 종료는 Patch 8 완료나 formal 실행 허가를 의미하지 않는다.
