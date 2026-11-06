# Stage 5-E C-6 — 프레임 재사용 원인 검토

2026-11-05. **C6_FINAL: PARTIAL. ROOT_CAUSE: LIKELY. CODE_FIX: REVIEW_REQUIRED.**

SDK 수신 시점에 이미 한쪽 스트림의 식별자가 재사용된다는 사실은 확인했다. Headless 증가분은 SDK의 최근 child 보관·frameset 구성과 더 짧아진 처리/수신 호출 주기가 상호작용한 현상이 가장 유력하다. 그러나 증가의 인과관계, 실제 align 후 식별자, 카메라의 실제 생성 수는 기존 기록으로 확정할 수 없다. 애플리케이션이 동일 RGB-D 쌍을 의도치 않게 재처리한 결함은 발견하지 못했다. 입력 필터·동기화·timestamp·연구 규칙은 수정하지 않았고, 부족한 경계를 관측할 opt-in 메타데이터 진단만 추가했다.

| 판정 | 결과 | 근거/제한 |
|---|---|---|
| DUPLICATE_METRIC | PASS | 원본 journal/JSON/CSV 재계산 일치; 번호+timestamp+domain으로 검증 |
| RECEIVE_PATH | PASS | 기존 raw child 로그와 실제 호출 순서로 수신 전후 경계 확인 |
| ALIGN_PATH | PARTIAL | SDK 소스와 가상 SDK 검증; 실제 C align 후 식별자는 NOT_MEASURED |
| ROOT_CAUSE | LIKELY | 수신 단계의 단일 child 재사용은 CONFIRMED; Headless 증가 원인의 배타적 입증은 미완료 |
| CODE_FIX | REVIEW_REQUIRED | 동작 결함 미입증; 진단만 추가, 수신/처리 수정 없음 |
| REGRESSION | PASS | 최종 관련 합성 회귀 181/181; 시작 source/HEAD 기본 경로 동등성 |
| C6_FINAL | PARTIAL | 하드웨어 경계 측정과 정식 입력 영향 검증이 남음 |

## 1. 기준과 Git 시작/종료 상태

기준/시작/종료 HEAD는 `ed22f0fc83fa923fcb4425d7e76eaac79348ed0a`다. Branch는 `feat/aiot-stage5e-d455-readiness`다. 상세 원본은 `start_state.json`, `end_state.json`에 있다.

시작 상태는 아래와 같았다. `artifacts/`는 status 조회의 pathspec에서도 제외했다. 기존 ignore 설정 및 `.pytest_cache/` 접근 권한 warning은 기록했으며 수정하지 않았다. 따라서 아래 목록은 artifacts를 제외한 범위의 목록이다.

```text
 M posture_geometry_probe.py
 M probe_timing.py
?? STAGE_5E_BUNDLE_C.md
?? probe_diagnostics.py
?? stage5e_bundle_c.py
?? test_stage5e_bundle_c.py
?? verify_stage5e_bundle_c.py
```

종료 시 위 항목은 유지되며 `frame_provenance.py`, `test_frame_provenance.py`가 추가된다. 이번 수정이 들어간 기존 파일은 `posture_geometry_probe.py` 하나다. `probe_timing.py`의 시작 변경 및 미추적 묶음 C 파일 5개는 시작 SHA-256 그대로 보존한다. 새 증거는 전부 이 보고서가 있는 신규 `analysis/ENGINEERING_ONLY_STAGE_5E_C6_20261105/` 아래에 생성했다. 기존 analysis ignore 정책을 변경하거나 강제 stage하지 않았다. reset/clean/commit/push/staging은 수행하지 않았다.

우선 확인한 권위: `AGENTS.md`, Research Master(현재 §24–28 포함), Decision Log(CAP-007 및 EXP-003–007), `RESEARCH_DATA_SCHEMA.md`(§F 포함), `docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md`, `STAGE_5E4_PERFORMANCE.md`, `STAGE_5E_BUNDLE_A.md`, `STAGE_5E_BUNDLE_C.md`. 과거 문서의 이전 시점 status는 후속 결정으로 읽었으며 소급 수정하지 않았다.

## 2. 실제 읽은 원본과 검증 방법

ZIP 대신 다음 디렉터리 원본을 사용했다. 파일 부재로 대체한 run은 없다.

- B: `analysis/ENGINEERING_ONLY_B_RETRY_20261105_140118/BASELINE_01`, `_02`, `_03`, `PREVIEW`. 각 8파일, 총 32파일.
- C: `analysis/ENGINEERING_ONLY_C_FINAL_20261105_152742/{UI_01,UI_02,UI_03,HEADLESS_01,HEADLESS_02,HEADLESS_03}`. 각 `performance/` 8파일과 `diagnostics/` 2파일, 총 60파일.
- performance 8파일: `manifest.json`, `events.jsonl`, `host_timing.json`, `performance.json`, `performance_runs.csv`, `performance_samples.csv`, `model_benchmarks.csv`, `experiment_comparisons.csv`.
- diagnostics 2파일: `manifest.json`, `diagnostics.json`.

원본 92파일의 경로와 시작/종료 SHA-256은 state JSON에 전부 기록했다. `review.py`는 원본 events를 다시 읽고 journal hash·순서·embedded events·timing JSON·config hash·manifest identity·raw stage/resource 통계·lifecycle count·4종 CSV의 컬럼/행 projection을 대조했다. C QPC diagnostics의 raw 분포도 다시 계산했다. 10개 run 모두 crosscheck PASS다. PREVIEW는 별도 20초 run으로 남기고 90초 비교 평균에서 제외했다.

새 계산 원본은 `recalculated.json`, 요약은 `run_summary.csv`, 추가 대조/예시는 `supplemental.json`이다. 이 분석은 원본을 수정하거나 과거 연구 결과를 다시 산출하지 않는다.

## 3. 중복 정의와 기존 계측의 의미

각 run을 분리하고 run의 장치 serial 및 스트림 문맥 아래 `(frame_number, timestamp_ms, timestamp_domain)` 조합을 비교했다. per-frame 물리 sensor ID와 profile UID는 기존 로그에 없으므로 NOT_MEASURED다. run의 serial이 같다는 사실만으로 재연결이나 센서 교체가 없었음을 입증하지 않는다. run 간 counter 초기화는 별도 run 경계로 취급하여 합쳐서 deduplicate하지 않았다.

- `received`: SDK가 ready=True로 반환하여 `input` token이 생성된 수. timeout 제외, deadline 경계 전달 포함.
- `processed`: `frame_completed`가 있는 token 수. `frame_started`와 token으로 연결한다.
- `unique`: 해당 경계의 전체 관측에서 서로 다른 식별 조합 수. `duplicate = 관측 수 − unique`, `ratio = duplicate / 관측 수`.
- `unique observed FPS = unique / 기존 timing.stream_seconds`. 신규 sensor 생성 FPS나 첫/마지막 sensor timestamp span 기반 rate가 아니다.
- source gap은 같은 run에서 역행/경계 없이 증가한 번호에 대해 `max(0, current−previous−1)`의 관측 합이다. 이것을 센서 missing_rate로 변환하지 않는다.

기존 `performance_output.csv_rows()`는 신뢰성 검사 후 고유 번호 수를 사용한다. 번호에 timestamp가 재할당되거나 domain 변화·역행 등이 있으면 NOT_MEASURED로 만든다. 이번 모든 원본에서는 번호만 반복한 수와 번호+timestamp+domain을 반복한 수가 정확히 같았다. 같은 번호/다른 timestamp, 다른 번호/같은 timestamp, 번호 재할당, domain 변경, 번호/시간 역행은 모두 0건이다. 모든 child의 domain은 `timestamp_domain.system_time`이었다. 이것을 hardware_clock이나 노출 시각으로 재해석하지 않았다.

`source_duplicate_ids`는 `frames.get_frame_number()`의 반복 수다. 독립적인 composite ID가 아니다. SDK composite는 첫 child의 번호/timestamp를 전달하며, 모든 B/C 원본에서 이 번호는 Depth child 번호와 일치했다. 따라서 C Headless의 source_duplicate_ids 60/71/88은 Depth 재사용 수이며, RGB-D 쌍 전체 중복 수로 읽으면 안 된다. 기존 필드·의미는 변경하지 않았다. [SDK composite-frame.h](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/src/composite-frame.h)

## 4. 실행별 재계산

아래 고유/중복·비율·FPS는 **received 경계**다. RGB/Depth는 각각 `고유 / 중복 (중복%)`로 표시했다. gap도 child별 관측 번호 gap 합이며 missing_rate가 아니다.

| run | 초 | received / processed | processed FPS | RGB 고유/중복 (%) | Depth 고유/중복 (%) | RGB / Depth 고유 FPS | RGB / Depth gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| B-01 | 90.000 | 1342 / 1341 | 14.900000 | 1331 / 11 (0.820) | 1337 / 5 (0.373) | 14.788889 / 14.855556 | 0 / 2 |
| B-02 | 90.016 | 1339 / 1338 | 14.864024 | 1330 / 9 (0.672) | 1330 / 9 (0.672) | 14.775151 / 14.775151 | 0 / 8 |
| B-03 | 90.000 | 1340 / 1339 | 14.877778 | 1329 / 11 (0.821) | 1332 / 8 (0.597) | 14.766667 / 14.800000 | 0 / 6 |
| UI-01 | 90.000 | 1338 / 1337 | 14.855556 | 1333 / 5 (0.374) | 1333 / 5 (0.374) | 14.811111 / 14.811111 | 0 / 5 |
| UI-02 | 90.000 | 1340 / 1339 | 14.877778 | 1333 / 7 (0.522) | 1336 / 4 (0.299) | 14.811111 / 14.844444 | 0 / 2 |
| UI-03 | 90.000 | 1337 / 1337 | 14.855556 | 1332 / 5 (0.374) | 1332 / 5 (0.374) | 14.800000 / 14.800000 | 1 / 5 |
| HEADLESS-01 | 90.015 | 1337 / 1336 | 14.841971 | 1269 / 68 (5.086) | 1277 / 60 (4.488) | 14.097650 / 14.186524 | 0 / 61 |
| HEADLESS-02 | 90.015 | 1339 / 1338 | 14.864189 | 1251 / 88 (6.572) | 1268 / 71 (5.302) | 13.897684 / 14.086541 | 3 / 71 |
| HEADLESS-03 | 90.015 | 1338 / 1337 | 14.853080 | 1236 / 102 (7.623) | 1250 / 88 (6.577) | 13.731045 / 13.886574 | 0 / 88 |
| B PREVIEW (평균 제외) | 20.000 | 291 / 291 | 14.550000 | 291 / 0 (0) | 290 / 1 (0.344) | 14.550000 / 14.500000 | 0 / 0 |

| 90초 × 3 | B | C UI | C Headless |
|---|---:|---:|---:|
| received / processed 합 | 4021 / 4018 | 4015 / 4013 | 4014 / 4011 |
| received RGB 고유 / 중복 | 3990 / 31 | 3998 / 17 | 3756 / 258 |
| received Depth 고유 / 중복 | 3999 / 22 | 4001 / 14 | 3795 / 219 |
| received RGB / Depth 중복% | 0.771 / 0.547 | 0.423 / 0.349 | 6.428 / 5.456 |
| processed RGB 고유 / 중복 | 3987 / 31 | 3996 / 17 | 3754 / 257 |
| processed Depth 고유 / 중복 | 3996 / 22 | 3999 / 14 | 3792 / 219 |
| processed FPS 평균 ± 실행간 표본 SD | 14.880601 ± 0.018153 | 14.862963 ± 0.012830 | 14.853080 ± 0.011109 |
| received RGB 고유 FPS 평균 ± SD | 14.776902 ± 0.011214 | 14.807407 ± 0.006415 | 13.908793 ± 0.183555 |
| received Depth 고유 FPS 평균 ± SD | 14.810236 ± 0.041168 | 14.818519 ± 0.023130 | 14.053213 ± 0.152727 |
| 완전히 동일한 RGB-D 쌍 재전달 | 0 | 0 | 0 |

사용자 참고값과 received 정의의 재계산은 일치한다. processed 경계에서는 Headless RGB 중복이 **257**이다. HEADLESS-01의 마지막 token 1337은 RGB 재사용 전달이지만 duration 경계에서 처리되지 않았으므로 received에는 68회, processed에는 67회다. UI-01/02도 각 1개 입력을 deadline에서 제외하며 UI-03에는 이 제외가 없다. B-01/02/03은 각 1개가 제외된다. 이는 집계 오류가 아니라 전달/처리 분모의 차이다.

## 5. timestamp 분포와 초기화 경계

아래는 전체 인접 전달의 SDK child timestamp 차이(ms), `p50 / p95 / 최대`다. 0 간격도 포함했다. RGB/Depth 각각 0 간격 수는 위 중복 수와 같고 음수는 없다. positive/new-number 분포와 histogram은 JSON에 따로 있다.

| run | RGB Δtimestamp ms | Depth Δtimestamp ms | 첫→마지막 RGB 번호 | 첫→마지막 Depth 번호 |
|---|---:|---:|---:|---:|
| B-01 | 66.721 / 67.064 / 145.296 | 66.724 / 67.087 / 605.094 | 5→1335 | 1→1339 |
| B-02 | 66.724 / 67.041 / 144.950 | 66.721 / 67.126 / 134.090 | 5→1334 | 2→1339 |
| B-03 | 66.718 / 67.035 / 145.296 | 66.719 / 67.129 / 133.659 | 5→1333 | 2→1339 |
| UI-01 | 66.719 / 67.005 / 144.508 | 66.719 / 67.088 / 133.760 | 5→1337 | 2→1339 |
| UI-02 | 66.726 / 66.988 / 208.164 | 66.724 / 67.055 / 134.114 | 4→1336 | 2→1339 |
| UI-03 | 66.723 / 67.000 / 207.128 | 66.720 / 67.040 / 133.598 | 4→1336 | 2→1338 |
| HEADLESS-01 | 66.712 / 81.930 / 212.197 | 66.733 / 70.748 / 200.550 | 4→1272 | 2→1339 |
| HEADLESS-02 | 66.703 / 138.915 / 266.789 | 66.722 / 79.508 / 604.313 | 1→1254 | 1→1339 |
| HEADLESS-03 | 66.684 / 139.100 / 274.273 | 66.732 / 132.850 / 267.250 | 4→1239 | 2→1339 |
| PREVIEW | 66.718 / 67.037 / 67.505 | 66.707 / 67.129 / 67.447 | 3→293 | 3→292 |

각 run의 첫/마지막 **정확한 timestamp와 domain**, input token/host 시각, 마지막 completed token, deadline token은 `recalculated.json`과 `supplemental.json`에 보존했다. run 내부 reset/wraparound/역행 징후는 없었다. run 사이 번호는 위처럼 다시 시작하므로 경계를 넘어 gap이나 중복을 계산하지 않았다. 시작 전/종료 후 관측하지 않은 프레임 수는 추정하지 않았다.

Headless RGB의 새 번호 사이 100ms 초과 간격은 66/81/92회이고 UI는 5/6/6회다. 특히 HEADLESS-01/03의 RGB 번호 gap 합이 0인데도 긴 timestamp 간격이 있다. 따라서 단순히 “애플리케이션이 빠르게 호출하여 같은 고정 15Hz 입력을 더 많이 보았다”만으로 고유 RGB rate 감소 전체를 설명했다고 할 수 없다. timestamp가 system_time인 점, sensor 노출/생성 메타데이터·auto exposure/priority·USB/driver 도착 추적이 없는 점 때문에 실제 카메라 cadence, SDK/OS timestamp 부여 및 전달 지연을 추가로 분리해야 한다.

## 6. 실제 수신→align→처리 경로

확인 소스는 `posture_geometry_probe.py`, `probe_timing.py`, `performance_output.py`, `probe_diagnostics.py`, `stage5e_bundle_c.py`, `h9_async_runtime.py`, `h9_probe_session.py`, `capture_d455.py` 및 관련 테스트다.

```text
duration check / H9 health
→ pipeline.try_wait_for_frames(250)        # B/C는 duration 지정; H9 없는 조건
→ ready이면 input token + frames.get_frame_number()
→ performance.sensor_frames(token, frames)
   → 원본 get_color_frame()/get_depth_frame()
   → child get_frame_number()/get_timestamp()/get_frame_timestamp_domain()
→ deadline 경계면 skip; timeout이면 처리 없음
→ device_timestamp_ms = frames.get_timestamp()
→ align = rs.align(rs.stream.color); aligned = align.process(frames)
→ aligned.get_color_frame()/get_depth_frame(); pair 유효성 확인
→ get_data(), BGR→RGB, MediaPipe 입력 구성
→ int(composite timestamp), 기존 monotonic +1 보장
→ frame_started → Pose/Face → geometry → 선택한 F1/H9/출력/UI
→ frame_completed; 다음 loop는 SDK 수신부터 다시 시작
```

`capture_d455.make_config()` 및 원본 환경은 RGB 1280×720 bgr8, Depth 848×480 z16, 둘 다 nominal 15FPS다. C6는 설정을 바꾸지 않았다. 현재 설치 및 모든 원본 환경의 Python SDK distribution은 **pyrealsense2 2.58.4.10922**다. 원본은 D455 firmware 5.17.3.10 / USB 3.2를 기록했다. 원본 설정에는 H9/F1/RF demo/callback/연구 CSV가 모두 비활성이다. 따라서 이 실측으로 분류 정확도나 H9 입력 품질을 평가했다고 주장할 수 없다.

duration/H9가 모두 없는 기존 경로는 `wait_for_frames()`다. 실제 B/C는 `try_wait_for_frames()` 경로이며, Python binding은 매 호출에서 새 fs 변수를 만들고 `(success, fs)`를 반환한다. C++ `try_wait_for_frames`는 aggregator queue에서 dequeue하고 false 시 현재 앱은 inference로 진행하지 않는다. 이전 `frames`를 timeout 때 재처리하는 분기는 없다. [Python binding](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/wrappers/python/pyrs_pipeline.cpp), [pipeline.cpp](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/src/pipeline/pipeline.cpp)

기존 MediaPipe용 +1은 입력 timestamp 정수화 뒤 VIDEO API에 필요한 단조 증가를 유지하는 기존 동작이다. raw sensor 이벤트 이전에 적용되지 않고 sensor 중복 통계에도 사용되지 않는다. 이를 제거·확대하거나 신규 프레임의 증거로 쓰지 않았다.

## 7. SDK 실제 구현과 질문별 답

검토한 primary source는 설치 major/minor/patch에 대응하는 librealsense **v2.58.4 tag**다. 설치 wheel native binary의 SHA-256은 `hardware_availability.json`에 기록했다. tag 소스 검토가 wheel 전체의 bit-for-bit 재현 빌드 검증을 의미하지는 않는다.

SDK는 color와 depth를 syncer에 보내고, 그 결과를 aggregator에 전달한다. aggregator는 들어온 child의 stream UID별 `_last_set`을 갱신하고, 필요한 stream이 모두 한 번 존재하면 그 시점의 `_last_set` 전체로 새 composite를 만들어 크기 1 queue에 넣는다. 한 child만 갱신된 입력에서도 나머지 child의 마지막 값이 유지될 수 있다. 따라서 새 queue 전달과 모든 child의 신규성은 동치가 아니다. [aggregator.cpp](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/src/pipeline/aggregator.cpp)

API 문서에도 stream rate가 다를 때 느린 stream의 matching frame이 반복 포함될 수 있고 최신 unread set을 받는다고 명시되어 있다. 다만 이번 설정은 nominal FPS가 같으므로, 이 문구만으로 Headless 증가 원인을 확정하지 않았다. [rs_pipeline.hpp](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/include/librealsense2/hpp/rs_pipeline.hpp)

align-to-color는 현재 frameset의 depth와 color를 선택하여 depth를 새 공간 profile로 투영한다. 새 depth frame의 original은 그 depth이며, SDK allocation은 original additional_data를 복사한다. generic output 준비는 처리되지 않은 color를 포함한다. 이 소스에서 시간상 과거 frame을 따로 선택하는 align cache 경로는 확인되지 않았다. 그러나 실제 원본 run의 post-align 메타데이터가 없으므로 실행 결과까지 확인한 것은 아니다. [align.cpp](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/src/proc/align.cpp), [synthetic-stream.cpp](https://raw.githubusercontent.com/realsenseai/librealsense/v2.58.4/src/proc/synthetic-stream.cpp)

| 질문 | 답과 근거 |
|---|---|
| 1. try_wait 수신 자체에 이전 child가 포함되는가? | **YES, 관측 확인.** sensor 이벤트는 align 이전이며 같은 번호+timestamp+domain 재사용이 있다. 전체 쌍 반복은 0. 메모리 주소/pixel 동등성은 NOT_MEASURED. |
| 2. align 후 반복되는가? | **실측 NOT_MEASURED.** SDK 구현상 원본 식별자가 이어질 것으로 예상되지만 실제 post-align 확인을 대신하지 않는다. |
| 3. Headless의 빠른 처리/호출 주기 영향인가? | **LIKELY, 인과 미확정.** QPC steady frame.processing p50 실행 평균 UI 43.893167ms→Headless 25.552033ms. receive.wait p50은 UI 22.445/23.102/22.700ms→40.704/40.634/41.669ms. 수신 호출 입장 absolute QPC가 없어 정확한 call-to-call 주기 복원은 NOT_MEASURED. |
| 4. 새 Depth+과거 RGB, 새 RGB+과거 Depth인가? | **둘 다 YES.** C UI 각각 17/14회, Headless 258/219회. 상대적으로 직전 수신 식별자와 비교한 의미이며 센서의 노출 순서를 주장하지 않는다. |
| 5. SDK 재사용과 앱 중복 처리를 구별할 수 있는가? | **수신 단계 단일 child 재사용은 구별 가능.** 모든 processed token은 한 번 시작/완료되고 입력 pair 전체 중복은 0. SDK aggregator와 일치하는 동작이다. 정상 정책이라고 해서 정식 연구 입력 품질까지 검증된 것은 아니다. Headless 증가의 유일한 trigger는 미확정. |
| 6. 실제 sensor 누락률을 계산할 수 있는가? | **NO / NOT_MEASURED.** 실제 생성 수·연속성 계약과 SDK에서 관측 이전의 누락 위치가 없다. frame gap, nominal 15FPS, duration 또는 processed FPS로 대체하지 않는다. |

직접적인 원본 예: HEADLESS-01 `events.jsonl` token 170→171에서 RGB #166 / timestamp 1793860171578.0596 / system_time은 같고 Depth #169→170으로 바뀐다. token 171→172에서는 Depth #170 / timestamp 1793860171638.515 / system_time이 같고 RGB #166→167로 바뀐다. input/sensor sample_index는 각각 2054–2056, 2066–2068, 2078–2080이며 모두 처리 완료됐다. `supplemental.json`에 원본 행을 보존했다.

Headless에서 새 RGB+재사용 Depth 전달의 host 입력 간격 p50은 16/31/16ms, UI는 47/47/47ms다. 반대로 재사용 RGB+새 Depth는 Headless p50 62/62/62ms다. host monotonic은 원본 Windows GetTickCount64의 약 15.625ms 격자이므로 0ms/16ms를 정밀 수신 간격으로 해석하지 않았다. 이 관측은 짧은 처리 후 부분 갱신 composite를 더 일찍 소비하는 설명을 지지하지만 동일 입력 A/B 또는 SDK 내부 callback 추적을 대신하지 않는다. 모든 비교는 **OBSERVATIONAL**이다.

## 8. 원인 판정과 미배제 원인

확인된 사실은 (a) 반복이 align 전에 존재, (b) 매 반복에는 다른 child의 새 식별자가 존재, (c) 앱 token별 processing은 1회, (d) 기존 통계와 원본 재계산 일치다. 따라서 앱의 이전 입력 변수 재처리나 aggregate 산술 오류를 주원인으로 지지하는 증거는 없다. align이 **기존 raw 중복 숫자**를 만든 원인도 될 수 없다.

가장 유력한 설명은 **SDK의 최신 child 재사용/동기화·aggregation + UI 생략으로 바뀐 소비 시점**이다. 다만 RGB 새 번호의 긴 system_time 간격도 증가하므로 수신 주기만으로 전부 설명한 것은 아니다. SDK syncer의 partial set 방출 조건, RGB 실제 출력 cadence/노출, Windows Media Foundation/USB 도착 지연 및 OS scheduling, system_time timestamp 부여의 영향은 아직 분리되지 않았다. align 이후 추가 문제가 없다는 실측 보증도 없다.

CASE A의 SDK 재사용 패턴에는 부합하지만 “기존 연구 입력 계약을 침해하지 않는다”까지 실증되지 않았다. CASE B 결함은 입증되지 않았고 CASE C 오류도 확인되지 않았다. 따라서 **CASE D의 REVIEW_REQUIRED를 유지**한다. Headless를 정식 수집·평가의 기본값으로 변경하지 않는다. 중복을 0으로 만들기 위한 skip/cache/보간/동기화 완화는 적용하지 않았다.

## 9. 이번 수정 파일과 opt-in 진단

| 파일 | C6에서 실제 바뀐 동작 |
|---|---|
| `posture_geometry_probe.py` | `--frame-provenance-dir NEW_DIR`/API 인수와 새 observer 호출만 추가. duration+timing/performance 요구, 출력 중첩/기존 경로 거부, cleanup에 sidecar 종료 연결. 비활성 시 기존 설정 hash/이벤트/timing 유지. |
| `frame_provenance.py` (신규) | SDK가 노출하는 numeric/string metadata만 수집. raw/aligned 번호·timestamp·domain·profile UID/type/index, 직전 대비 변경·gap/경계, pre/post align 비교, 수신 QPC 시작/반환·align 관측·inference 전 시작/처리 완료 시각, 상태·실행 비용. |
| `test_frame_provenance.py` (신규) | 합성 11개 테스트. 실제 장비/영상/학습 없음. |
| 이 폴더의 `review.py`, `supplement.py`, `verify.py`, `compare_start_source.py` (신규) | 원본 read-only 분석, hash/회귀/SDK availability 기록, 시작 C source의 SHA-일치 복원본과 현행의 동등성 검증. |
| 이 보고서와 이 폴더의 신규 JSON/CSV/log/diff/합성 예시 | 조사 증거. 과거 engineering evidence와 별도. |

`probe_timing.py`, `probe_diagnostics.py`, `performance_output.py`, `stage5e_bundle_c.py`, H9/F0/F_cal/모델/평가 소스와 기존 테스트는 C6에서 수정하지 않았다.

sidecar는 별도 신규 폴더의 `manifest.json`, `frames.jsonl`, `summary.json`이다. 기존 events.jsonl에 새 event kind를 섞지 않으며 기존 performance/host_timing JSON 및 4종 CSV의 필드·컬럼 순서를 바꾸지 않는다. 활성 시 performance config에 `frame_provenance_enabled=true`만 명시하여 비교 조건을 구별한다. 기본값은 비활성이다.

QPC 수신 시작은 `receive.wait` context 진입 직전, 반환은 SDK 호출 직후다. align 시각은 반환 후 child를 꺼내 observer가 관측한 시각이다. processing 시작은 기존 convert/frame_started 다음, inference 직전이며 완료는 기존 frame_completed 다음이다. 이 범위는 기존 `frame.processing` 전체와 같지 않다. sensor clock과 QPC/legacy clock을 차감하지 않는다.

영상 배열·frame handle·참가자 ID·landmark·예측값은 sidecar에 보관하지 않는다. 매 loop 파일 쓰기 없이 메모리에 작은 행을 축적하여 정상/예외 종료 시 JSONL로 출판한다. 따라서 kill/전원 상실 시 manifest만 남을 수 있으며 메모리 사용은 실행 길이에 비례한다. 기존 performance flush 정책은 유지한다. duration을 필수로 하여 명시적으로 유한 실행을 요구한다.

관측 getter/비교/상태갱신 호출 비용도 QPC로 수집한다. 최종 합성 Python accessor 1000쌍에서 4000 observer call의 p50 **0.0080ms**, p95 **0.0136ms**, 최대 **30.8106ms**, 합 **56.109ms**였다. outlier도 보존했다. 종료 JSONL 쓰기는 19.122ms였다. 이는 **합성 accessor 비용**이며 실제 SDK 비용·D455 cadence 변화율이 아니다. begin_receive/외부 분기·일부 clock 호출, setup/device query, summary/hash I/O 등은 이 call-cost 합에 포함되지 않는다. 진단 자체가 주기를 전혀 교란하지 않는다는 주장은 하지 않는다. 원본에는 이 진단이 없었으며 새 진단을 활성화한 수치는 원본 조건과 구분해야 한다.

## 10. 실제 수행한 합성/회귀 검증

최종 실행: **181 tests PASS / failures 0 / errors 0 / skipped 0**, 10.117초. 개별 목록은 `final_verification/regression.log`, 실행 모듈/결과는 `final_verification/verification.json`이다. 전체 저장소 suite나 실제 D455 검증은 아니다. 실제 학습을 막기 위해 이 실행에서는 `rf.Forest.fit` 및 `rf.fit_models`를 raise하도록 patch했다.

- 신규 11개: raw SDK metadata 위치, align 전후 비교/다른 profile UID, RGB만/Depth만/둘 다 재사용, 번호 동일+timestamp 다름, 번호 다름+timestamp 동일, gap/reset/wrap/domain/profile 경계, 누락/비정상 필드, timeout/invalid pair/duration, runtime/receive exception·KeyboardInterrupt, 경로 중첩/기존 파일 거부.
- 실제 probe 가상 SDK 통합: 진단 off/on에서 전체 timing/events 동일, Pose/Face/geometry 41회씩 동일, 4.1초 합성 H9에서 두 조건 모두 RF 예측 1회 및 이벤트 동일. SDK가 완전히 같은 쌍을 반환하는 합성 경우에도 기존 3회 처리 규칙을 보존하여 임의 필터를 추가하지 않았음을 확인했다.
- 기존 C15개, 묶음 A 관련142개, F0/F_cal13개 보존: 기존 3/5-class, 6-class SYNTHETIC DEMO, adapter·CSV·H9 특징/집계/예측, timeout/종료/오류 경로. 선택한 formal6 테스트는 구조/규칙 검증이며 정식 참가자 평가를 실행하지 않았다.
- `final_verification/default_equivalence.json`: Git HEAD ed22f0f 원본과 현행 기본 경로의 전체 legacy timing 및 config 동일. 원본 기본/현행 기본/현행 Headless의 Pose/Face/geometry/callback 모두 3회.
- `pre_c6_comparison/equivalence.json`: C6 추가분만 제거하여 만든 별도 시작 C source 복원본의 SHA-256이 기록된 시작 hash `5b9a244e11fac9722e1ae4a39b6b87ef278d9805e9f12952a22a6aeaa486b21b`와 일치. 이 복원본과 현행에서도 기본 timing/config 및 호출수 동일. 원래 파일을 되돌린 것이 아니라 새 폴더에 복원본을 만들었다.
- 원본 데이터 crosscheck는 별도로 10/10 PASS. 위 테스트 수에 실측 재계산을 합쳐 세지 않았다. `git diff --check` PASS.

개발 중 최초 신규 10개 실행은 3 PASS/7 ERROR였다. 신규 compare의 중복 keyword와 합성 invalid-pair fixture를 수정했고 다음 10개는 전부 PASS였다. 첫 통합180개 PASS 뒤 H9 검증을 4.1초/예측1회로 보강하고 전체 동일 입력 반환 보존 테스트1개를 추가하여 최종181개 PASS를 확인했다. 보조 분석의 장치 상세 열거는 아래 접근 거부를 기록하도록 보완했다. 미해결 테스트 실패는 없다.

## 11. 추가 D455 시험 — NOT_RUN

`rs.context().query_devices()`의 count는 1이었다. 상세 device 객체 열거는 Windows Media Foundation `MFCreateDeviceSource`의 HResult `0x80070005` 접근 거부로 확인하지 못했다. 장치 count만으로 현재 접근 가능한 D455/정상 스트리밍을 확인했다고 하지 않는다. 현재 장면이 빈 의자/고정 비인체인지도 확인할 근거가 없다. 따라서 하드웨어 streaming, 영상 읽기, UI/Headless 25초 실측은 **NOT_RUN**이다. 장비가 없다고 단정하지도, 실측한 척하지도 않았다. 데이터 재계산 및 가상 SDK만 실행했다.

향후 실제 운영자가 접근 가능한 D455와 비인체 고정 장면·동일 USB/조명 조건을 확인한 환경에서 사용할 정확한 PowerShell 명령은 다음과 같다. 아래 명령은 이번에 실행하지 않았다. 신규 GUID 폴더를 만들고 UI25초+Headless25초 각 1회만 실행한다. 영상 저장 옵션/모델/H9/연구 수집 옵션은 없다. 비교는 **OBSERVATIONAL**, strict 동일 입력 A/B가 아니다.

```powershell
$c6Py = Join-Path (Get-Location) 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe'
$c6Run = Join-Path (Get-Location) ('analysis/ENGINEERING_ONLY_STAGE_5E_C6_20261105/NONHUMAN_OBSERVATIONAL_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $c6Run -ErrorAction Stop | Out-Null
& $c6Py -X utf8 -B posture_geometry_probe.py --views none --duration-seconds 25 --timing-warmup-frames 150 --timing-h9-warmup-calls 5 --performance-output-dir (Join-Path $c6Run 'UI_performance') --engineering-diagnostics-dir (Join-Path $c6Run 'UI_qpc') --frame-provenance-dir (Join-Path $c6Run 'UI_frames')
if ($LASTEXITCODE -ne 0) { throw 'UI diagnostic failed; inspect the new evidence before proceeding' }
& $c6Py -X utf8 -B posture_geometry_probe.py --headless --duration-seconds 25 --timing-warmup-frames 150 --timing-h9-warmup-calls 5 --performance-output-dir (Join-Path $c6Run 'HEADLESS_performance') --engineering-diagnostics-dir (Join-Path $c6Run 'HEADLESS_qpc') --frame-provenance-dir (Join-Path $c6Run 'HEADLESS_frames')
if ($LASTEXITCODE -ne 0) { throw 'Headless diagnostic failed; inspect the new evidence' }
```

짧은 시험에서 재현되지 않으면 먼저 새 metadata의 pre/post 위치·수신 호출 간격·같은 SDK/설정/비인체 장면 및 observer 비용과 기존 run 차이를 검토한다. 이유 분석 없이 반복 수를 늘리거나 이전 90초×6을 반복하지 않는다. 이 sidecar로도 센서의 실제 생성 총수는 직접 측정되지 않으므로 missing_rate는 계속 NOT_MEASURED다.

## 12. 원본·동결 규칙 보존과 남은 정식 영향

시작 hash 대상은 219파일이며 그중 원본 B/C 92파일이다. 종료에 원본92파일 전부 SHA-256 일치를 확인했다. 시작 source/문서 중 변경은 의도한 probe 하나뿐이며 나머지218개는 일치한다. 동결 Schema/Master/Decision/5-D-8, 평가기, F0/F_cal/H5/H9/H9−F9 특징·입력 순서, RF seed/개발2 LOSO, 8조합과 support/coverage/시간창/라벨/선정 규칙, H9 runtime은 변경하지 않았다. `end_state.json`의 파일별 판정이 정확한 검증 범위이며 전체 저장소 무결성 감사로 과장하지 않는다.

기존 artifacts는 조회·변경·삭제·스테이징하지 않았다. 원본 영상·외부4명·파일럿 연구 자료를 열지 않았으며 실제 모델 학습/선정/정확도 생성·과거 결과 변경이 없다. CAP-007 execution/registry/execution_id 생성 및 IRB HOLD/DEFERRED 해제도 없다.

위험은 processed count를 독립 신규 sensor 관측 수로 오인하는 데 있다. 반복 RGB와 갱신 Depth 조합은 geometry가 새로 계산되더라도 RGB 관측은 독립적이지 않다. 이를 정식 support나 coverage에서 어떻게 해석할지 이번 조사로 새 규칙을 정하지 않는다. 고유 관측률 저하는 확인되지만 자세 특징·분류 결과 왜곡의 크기/방향은 **NOT_MEASURED**다. 실제 align 후 검증, 실제 cadence/SDK partial 방출 원인, 장면/노출/시각 부여와 호출 주기의 인과 분리가 남아 있다.

## 13. C-7 및 묶음 D 인계 판정

**C-7 커밋 후보 정리는 조건부 가능**하다. 이번 진단과 근거는 회귀 PASS인 엔지니어링 변경으로 review/커밋 대상이 될 수 있다. 단 C6=PARTIAL, ROOT_CAUSE=LIKELY, CODE_FIX=REVIEW_REQUIRED와 NOT_RUN을 그대로 명시해야 한다. “원인 완전 규명/결함 수정 완료/정식 Headless 적격”으로 종료하거나 커밋 설명을 쓰는 것은 불가하다. 실제 commit/push는 이번에 하지 않았다. 이 폴더는 ignored이므로 향후 증거의 보관·리뷰 경로도 C-7에서 명시해야 한다.

**묶음 D의 비인체 엔지니어링 진단·오프라인 검토는 진행 가능**하다. live 진단은 장치 접근과 비인체 조건이 실제 확인된 환경에서 위 최소 시험 범위로 수행해야 한다. 정식 참가자/독립4명/최종6 모델 학습·평가, Headless 기본값 승격, CAP-007 실행 및 IRB 해제는 진행 가능해진 것이 아니다. 현재 환경의 live 측정은 NOT_RUN 상태로 인계한다.

## 14. 재현과 산출물

분석 스크립트는 exclusive 생성으로 기존 증거를 덮어쓰지 않는다. `review.py start`는 시작에 한 번 실행했고, 인수 없는 실행으로 원본을 재계산했다. `supplement.py`가 세부 비교를 기록했다. 장치 상세 열거 실패 후 `supplement.py hardware`는 별도 hardware JSON만 생성했다. 최종 회귀 명령은 다음과 같다. 동일 디렉터리를 재사용하면 거부하므로 재검증 시 마지막 인수에 새로운 하위 디렉터리명을 사용한다.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B analysis/ENGINEERING_ONLY_STAGE_5E_C6_20261105/verify.py final_verification
```

`regression.log`, `verification.json`, `default_equivalence.json` 및 `SYNTHETIC_metadata_cost/`가 최종 근거다. 상위 폴더의 최초180개 로그/예시도 개발 이력으로 보존했으며 실제 D455 결과로 표현하지 않았다. `pre_c6_comparison/`은 시작 source hash 동등성 근거다. `c6_only.diff`는 시작 C probe와 현행의 차이를 별도로 보여준다. `start_state.json`/`end_state.json`은 원본과 동결 source 보존 근거다.

## 15. 2026-11-05 묶음 D 후속 확인 — 최종 25초 × 2 실측

위 본문은 당시 조사 기록으로 보존한다. 이 절은 **이미 저장된 비정식 엔지니어링 메타데이터**의 후속 확인이며 이번에 장치나 연구 모델을 실행한 결과가 아니다.

`git ls-files`와 `git ls-tree -r --name-only HEAD`에서 실제 추적 경로는 처음부터 이 파일의 정상 경로 `STAGE_5E_C6_FRAME_REUSE_REVIEW.md`였다. 하위 디렉터리의 `.md` 파일은 없으므로 이동/이력 변경을 하지 않았다. 확인 기준 HEAD는 `ce3bfba`, branch는 `feat/aiot-stage5e-d455-readiness`다.

원본 위치: `analysis/ENGINEERING_ONLY_C6_LIVE_20261105_170905/`의 `UI_frames`, `HEADLESS_frames`, `UI_performance`, `HEADLESS_performance`. 각 frames의 `frames.jsonl`·`summary.json`, performance의 `performance.json`을 읽었다. raw 영상·Depth 배열은 읽지 않았다. 저장 시작 시각은 UI `2026-11-05T08:09:05.587980+00:00`, Headless `2026-11-05T08:09:36.375687+00:00`다. H9/F1/demo/callback/연구 CSV는 비활성이므로 실제 6-class 영향 측정이 아니다.

| 완료 처리 경계의 재계산 | UI | Headless |
|---|---:|---:|
| 실제 run seconds (기존 monotonic 보고값) | 25.000 | 25.016 |
| 처리 완료 | 365 | 365 |
| raw→aligned child 식별자 일치 / 비교 수 | 730 / 730 | 730 / 730 |
| RGB 재사용 전달 수 | 0 | 25 |
| Depth 재사용 전달 수 | 1 | 23 |
| 완전히 동일한 RGB-D 식별자 쌍 반복 | 0 | 0 |

식별자는 `(number, timestamp_ms, timestamp_domain, stream_type, stream_index)`로 대조했다. align이 depth profile UID를 복제하는 차이는 별도이며 UID 동일성이나 pixel 동일성을 주장하지 않는다. timeout 등을 포함한 전체 receive call 수 367/368을 처리 수 365와 혼용하지 않는다. 사용자 제공 최종 관측값은 위 저장 증거와 일치한다. 이 절의 숫자는 사용자 관측만을 전사한 값이 아니다.

원 journal SHA-256은 UI `8b18b65fb777c0f577d8025de01b211e305fb39a65831bb865fe775520d8a806`, Headless `af22b91e647c357ed91d6b6e02dd588c726d63648cda00cfd80546db94536d45`이며 summary의 pin과 일치했다. summary에 기록된 `frame_provenance.py`와 `posture_geometry_probe.py`의 SHA-256도 현재 소스와 일치했다. 재계산 코드·상세/hash: `analysis/READ_ONLY_STAGE_5E_BUNDLE_D_20261105/review.py`, `saved_evidence_review.json`.

후속 판정: **SDK 수신 단계 child 재사용 CONFIRMED / align 식별자 보존 해당 실측 범위 PASS / Headless 증가 인과 원인 LIKELY / 정식 Headless 사용 적격 NOT_APPROVED / 실제 6-class 분류 영향 NOT_MEASURED**. 과거 §7의 align 실측 NOT_MEASURED는 이 제한된 후속 측정으로 보충됐다. 다른 장면·장치·촬영 조건까지 PASS를 확장하지 않는다. sensor 실제 생성 수와 missing_rate는 계속 NOT_MEASURED이며 입력 필터/보간/제거·촬영 기본값·과학적 support 계약은 바꾸지 않는다. C6 전체의 PARTIAL 및 CODE_FIX REVIEW_REQUIRED는 유지한다.
