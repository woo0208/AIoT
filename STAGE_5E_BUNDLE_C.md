# Stage 5-E 묶음 C — 정밀도·UI·기록 비용 진단

2026-11-05. **엔지니어링 구현/회귀 완료. 실제 D455 변경 후 효과는 미측정.**

## 1. 요약과 판정

| 항목 | 판정 | 범위 |
|---|---|---|
| C-1 | PASS | coarse monotonic clock 원인 확인 및 재현, 독립 고해상도 sidecar 구현. 과거 개별 호출의 정밀 시간은 복구 불가 |
| C-2 | PASS | `--views none`의 UI 실행 확인, opt-in headless와 이미지 구성/imshow/waitKey 분리 관측 구현·합성 검증 |
| C-3 | PASS | 원본 기록 경로 분석, 결정적 입력 마이크로벤치마크. 실제 timing-only/live Performance 엄격 A/B는 BLOCKED |
| C-4 | PASS | 최적화 **1개**: headless의 화면 구성 생략. 통제된 이미지 구성 비용 제거만 정량 확인. 실제 D455 전체 효과는 NOT_PROVEN. journal 최적화는 NO_CHANGE |
| C-5 | PARTIAL | B 원본 재계산, 마이크로벤치마크 및 합성 동등성 비교 완료. 새 D455 실측/전체 pipeline 전후 차이는 NOT_MEASURED |

참가자/파일럿/외부4명 자료 접근, 재학습, 모델 선정, CAP-007 실행 및 IRB HOLD/DEFERRED 해제는 하지 않았다.
FPS 향상을 완료 조건으로 삼지 않았고, 합성 시험을 6-class 성능 근거로 사용하지 않았다.

## 2. Git 기준점과 보존

- 시작 HEAD = 종료 HEAD = **`ed22f0fc83fa923fcb4425d7e76eaac79348ed0a`** (`ed22f0f`).
- 시작 status는 `?? artifacts/`뿐이었다. `artifacts/` 내용 확인·수정·삭제·스테이징을 하지 않았다.
- 변경은 모두 위 HEAD 기준이다. reset/clean/commit/push 없음. 기존 묶음 B 및 사용자 파일 덮어쓰기 없음.
- 묶음 B 파일 **32개**(PREVIEW 포함)의 시작/종료 SHA-256 일치. 시작에 pin한 source/규칙 21개 중 실제 수정 source는 아래 2개뿐이며 나머지19개는 일치한다.
- 종료 status: `M posture_geometry_probe.py`, `M probe_timing.py`; 신규 `STAGE_5E_BUNDLE_C.md`, `probe_diagnostics.py`, `stage5e_bundle_c.py`, `test_stage5e_bundle_c.py`, `verify_stage5e_bundle_c.py`; 기존 `?? artifacts/` 유지.
- `git diff --check` PASS. Git ignore 설정/`.pytest_cache`의 기존 권한 warning은 그대로 두었다.

## 3. 실제 수정·추가 파일

| 파일 | 이유/동작 |
|---|---|
| `posture_geometry_probe.py` | 명시적 `--headless`, `--engineering-diagnostics-dir NEW_DIR`. 기본 UI/`--views none` 유지. headless는 duration 필수, 내장 UI·키 처리만 생략하며 추가3D/PyVista와 병용 거부 |
| `probe_timing.py` | diagnostics가 선택된 경우에만 별도 QPC 관측 전달. 기존 monotonic clock·시간 단위·stage 통계 및 H9 시간창/판정은 유지 |
| `probe_diagnostics.py` (신규) | 독립 manifest/diagnostics JSON. raw ns, phase별 ms p50/p95, source/clock 정보, 종료·예외 상태. 기존 JSON/CSV 스키마로 섞지 않음 |
| `stage5e_bundle_c.py` (신규) | B JSON/journal/CSV 재계산·대조, clock/기록/화면 구성 마이크로벤치마크. 카메라 실행 없음 |
| `test_stage5e_bundle_c.py` (신규) | 15개 단위 테스트: headless·clock·기존 경로·종료·예외·중단·journal·경로 충돌 |
| `verify_stage5e_bundle_c.py` (신규) | 원본 ed22f0f 소스와 현재 기본 경로의 결정적 비교, 관련 통합 회귀, 보존 hash 기록 |
| `STAGE_5E_BUNDLE_C.md` (신규) | 본 보고서 |

`performance_output.py`, `engineering_ab.py`, `engineering_exports.py`, `model_benchmark.py`, `prediction_adapter.py`, 평가기/특징식/동결 문서는 수정하지 않았다.

## 4. C-1 계측 정밀도

묶음 B의 계측 source3개 SHA가 시작 source와 모두 일치했다. B와 현재 runtime은 Python **3.12.10 / Windows 11**이다.
현재 `time.get_clock_info`는 다음을 반환한다.

| clock | 구현 | 명시 해상도 |
|---|---|---|
| 기존 `monotonic_ns` | GetTickCount64() | **15.625ms** |
| 새 sidecar `perf_counter_ns` | QueryPerformanceCounter() | **100ns** |
| 기존 process CPU time | GetProcessTimes() | 100ns (실제 짧은 CPU 표본 정밀도를 보증하는 뜻은 아님) |

`_ns`라는 반환 단위가 고해상도를 뜻하지 않는다. B 원시 duration_ns 자체가 정수 ms 격자(0/15/16/31/32/46/47/62/63ms 등)에 놓인다.
기존 코드는 `end-start` ns를 **부동소수 `/1_000_000`**으로 변환하고 NumPy linear percentile을 계산한다. raw→JSON 통계→CSV를 전부 대조했으며 추가 반올림/버림 때문에 생긴 격자는 아니다.
`int(device_timestamp_ms)`와 +1 보정은 MediaPipe 입력 timestamp에 쓰일 뿐 host stage duration의 원인이 아니다.

제어된 busy interval 100개씩의 최초 진단에서 **100µs/500µs/2ms 작업이 기존 clock에서 각각99/97/87회 0ns**로 관측됐다. QPC에서는 이 세 그룹 모두 양수였다.
독립 sidecar 단위 테스트도 legacy 0ms와 QPC 12,345ns를 동시에 보존했고, 명시적 98,765ns 입력의 기존 통계가 0.098765ms로 남는 것을 확인했다.

해석 한계:

- B의 0ms는 비용0의 증거가 아니다. 대략 한 tick보다 짧은 단계의 크기·순위를 판별하기 어렵다. 긴 분포의 대략적인 비교는 가능하나 원래 정밀도가 올라가지는 않는다.
- waitKey/receive에는 실제 블로킹·이벤트 처리·스케줄링이 포함될 수 있다. **31ms 전부가 불필요한 대기라는 원인 분해는 불가**하다. 별도 1ms sleep 관측은 waitKey 대체 측정이 아니다.
- B 당시 clock_info, QPC 시작/끝, GUI queue/GPU completion/OS 스케줄 추적은 저장되지 않았다. 개별 호출의 실제 시간, waitKey 내부 원인, imshow와 화면 구성 각각의 B 비용은 소급 복구할 수 없다.
- B와 일치한 source/runtime 및 재현에서 coarse clock이 격자의 주된 설명이다. 그렇다고 모든 지연 변동을 clock 하나의 탓으로 확정하지 않는다.
- 우선 QPC 관측이 필요한 단계: image build, imshow, waitKey, face, depth_geometry, input.convert, align 및 recording 호출. Pose/전체 frame도 비교용 QPC를 함께 남긴다.

새 옵션은 기존 clock을 교체하지 않는다. H9의4초/1초/2초 시간 의미도 그대로다. 별도 clock끼리나 sensor clock과 차감하지 않는다.

## 5. C-2 UI 경로와 headless

기존 실제 경로는 `draw_geometry_overlay → draw_engineering_panel → imshow → waitKey(1)`이다.
`--views none`은 추가3D viewer만 끄고 위 기본 경로와 H9 창은 유지한다. B에서도 ui.render_submit/ui.key_wait 원시 이벤트가 존재한다.

새 headless는 그 경로와 H9 **화면 제출**을 생략한다. RGB-D 수신/정렬/변환, Pose/Face, geometry, 선택한 F1/RF/H9 처리, callback/파일 기록은 유지한다.
H9 독립 timer/집계/예측은 계속 실행되지만 UI 제출/age 측정은 생성하지 않는다. headless UI latency는 **NOT_MEASURED**이며0으로 대체하지 않는다.
timeout/invalid pair에서도 UI 없이 duration 종료한다. 내장 q/reset/라벨 키는 없으며 callback 내부의 외부 UI까지 막는 옵션은 아니다. 이 모드를 정식 라벨 촬영기로 승격하지 않는다.

opt-in QPC sidecar는 `ui.image_build`, `ui.imshow`, 기존 `ui.key_wait`, `ui.render_submit`, `frame.processing`, host input→UI submit을 분리 관측한다.
이미지 구성·imshow·waitKey는 분리되지만 nested stage p95를 더하지 않는다. UI endpoint는 host application 제출이고 실제 화면 표시 시각이 아니다.

## 6. C-3 기록 오버헤드

Timing-only도 stage 목록·Counter·1Hz CPU/process memory monitor와 종료 통계를 수집한다.
Performance는 추가로 sensor identity·frame lifecycle/event를 생성하고, 각 event마다 lock 안에서 canonical JSON 직렬화→events.jsonl write→flush→메모리 event 목록 append를 수행한다.
종료에는 journal close/hash, performance JSON, raw/summary CSV4개 투영이 추가된다. `ProbeMetrics.finish`의 종료 비용과 stream duration은 다른 지표다.

같은 결정적 stage payload **3,000개 × 3회/모드**, 순서 교대, 실제 QPC 관측 결과:

| 호출 비용(ms, 실행별 분위수의 평균) | Timing-only | Performance | 절대 차이 | 상대 변화 |
|---|---:|---:|---:|---:|
| record_ns p50 | 0.000300 | 0.005400 | +0.005100 | +1700% |
| record_ns p95 | 0.000333 | 0.005867 | +0.005533 | +1660% |

이는 극히 작은 기준 호출에 대한 변화율이다. **실제 pipeline CPU/FPS 변화율이 아니다.** raw 호출·메모리 before/after·CPU·종료 관측은 recorder.json에 보존했다.
분리 마이크로 관측 p50/p95(ms): 직렬화0.0023/0.0024, write0.0003/0.0003, flush0.0019/0.0022, resource read0.02935/0.07515, 통계(3,000값)0.1013/0.1180.
종료 총비용은 Timing-only **41.0776/0.6537/0.4915ms**, Performance **54.8767/55.4100/56.1353ms**였다. 최초 timing-only outlier의 원인은 미확정이며 제거하지 않았다. 이를 정상 반복의 순수 종료 개선으로 해석하지 않는다.

B는 Performance 실행뿐이다. timing-only와 동일한 live 입력·payload를 재생했다는 증거가 없으므로 **엄격 A/B BLOCKED**다.
장치 설정·live-unlabelled ID·source hash가 같은 것은 동일 입력의 증명이 아니다. `engineering_ab.py` 조건은 변경하지 않았다.

## 7. C-4 선정과 미적용

**headless 1개만 적용.** 실제 B에서 UI 경로가 관측됐고, 독립된1280×720 합성 검정 이미지/빈 geometry의 실제 화면 구성 비용이 반복 관측됐다.
같은 입력에서 120호출×3회, 초기 cache warmup, 조건 순서 교대로 구성 수행과 생략 control을 비교했다.

| 이미지 구성만(ms) | 구성 수행 | 생략 control | 절대 차이 | 상대 변화 |
|---|---:|---:|---:|---:|
| p50의 실행 간 평균 | 7.745500 | 0.000067 | −7.745433 | −99.9991% |
| p95의 실행 간 평균 | 8.433723 | 0.000100 | −8.433623 | −99.9988% |

control 값은 clock/loop 비용 수준이며 정확한0 또는 전체 pipeline의99.99% 개선이라는 뜻이 아니다.
**imshow/waitKey는 이 마이크로벤치마크에서 실행하지 않았다.** 측정한 것은 이미지 구성 생략뿐이다. 실제 사람/모델/센서 입력과의 성능 동등성이나 D455 전체 지연 개선은 NOT_PROVEN이다.

**journal buffering/flush 변경은 NO_CHANGE.** 작은 결정적 기록 호출 비용만으로 live 병목이라고 입증되지 않았고, 관측된 비용에 비해 crash-loss 계약 변경의 이점이 입증되지 않았다. serialization/write/flush와 raw 이벤트 수를 그대로 유지했다.
Pose는 긴 관측 stage지만 모델/입력 변경을 뒷받침하는 근거가 없어 최적화하지 않았다.

## 8. C-5 실제 B 기준선과 이후 범위

아래는 원본 이벤트/JSON에서 재계산·대조한 **실제 비인체 B**다. PREVIEW는20초/291처리/14.55FPS COMPLETED였고 따로 검토했으며90초3회 기준선에서 제외했다.

| 지표 | B-01 | B-02 | B-03 | C 이후 실제 live |
|---|---:|---:|---:|---|
| processed FPS | 14.900000 | 14.864024 | 14.877778 | NOT_MEASURED |
| delivered FPS | 14.911111 | 14.875133 | 14.888889 | NOT_MEASURED |
| frame.processing p50/p95 ms | 47/63 | 47/63 | 47/63 | NOT_MEASURED |
| host input→UI submit p50/p95 ms | 31/47 | 31/47 | 31/47 | NOT_MEASURED（headless에서는 endpoint 없음） |
| Pose p50/p95 ms | 16/31 | 16/32 | 16/31 | NOT_MEASURED |
| UI render_submit p50/p95 ms | 0/16 | 0/31 | 15/16 | NOT_MEASURED |
| UI key_wait p50/p95 ms | 16/31 | 16/31 | 16/31 | NOT_MEASURED |
| CPU one-core% p50/p95 | 15.625/25.000 | 17.188/26.386 | 17.188/27.697 | NOT_MEASURED |
| RSS MiB p50/p95 | 287.312/295.393 | 283.980/294.723 | 284.109/294.539 | NOT_MEASURED |
| Private MiB p50/p95 | 988.910/994.615 | 985.680/993.396 | 986.223/993.924 | NOT_MEASURED |
| 처리/전달 framesets | 1341/1342 | 1338/1339 | 1339/1340 | NOT_MEASURED |
| frameset 중복 ID | 5 | 9 | 8 | NOT_MEASURED |
| RGB/depth 재사용 delivery | 11/5 | 9/9 | 11/8 | NOT_MEASURED |
| timeout / runtime error | 2/0 | 3/0 | 3/0 | NOT_MEASURED |
| duration 경계 skip | 1 | 1 | 1 | NOT_MEASURED |
| journal 이벤트 수 | 21566 | 21520 | 21536 | NOT_MEASURED |

MiB=2^20 bytes. raw byte 값과 나머지 모든 stage p50/p95는 baseline_postcheck.json에 있다.
평균 처리 FPS **14.88060065**, 실행 간 표본 SD **0.01815328**, 범위14.864024~14.9. 처리/전달 총계는 **4018/4021**으로 참고값과 일치한다.
15FPS ceiling의 약99.2%이므로 큰 FPS 향상을 목표로 하지 않는다. 수신 대기와 UI 대기 일부가 겹쳐 입력 pacing에 흡수될 수 있어 stage 감소가 그대로 FPS 증가가 되지 않는다.
RGB/depth 재사용은 원래 sensor 번호·timestamp 근거이며 payload 동등성 증명이 아니다. 센서 missing_rate는 기존대로 NOT_MEASURED다.

새 D455 stream은 시작하지 않았다. 추가 acquisition 없이 진단/제한된 최적화의 근거를 확보했으며, 동일 입력 재생도 없다.
따라서 B 대비 C의 live 절대 차이/변화율, 안정성·CPU/RAM 개선은 **NOT_MEASURED**다. 미래 다른 시점의 live 실행은 동일 입력이 입증되지 않는 한 **OBSERVATIONAL**로만 비교해야 한다. 장치를 시험하지 않았으므로 장치 사용 불가라고 판정하지도 않았다.

## 9. 실제 테스트

| 실행 | 수 | PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|---:|
| 신규 C 최초 단위 | 13 | 9 | 0 | 4 | 0 |
| 수정 후 C 단위 | 13 | 13 | 0 | 0 | 0 |
| journal/오류 검증 추가 후 C 단위 | 15 | 15 | 0 | 0 | 0 |
| 관련 통합 회귀 | **170** | **170** | **0** | **0** | **0** |
| raw count/resource 교차검증 보강 후 해당 단위만 | 1 | 1 | 0 | 0 | 0 |

반복 포함212 test case 실행,208 PASS/0 FAIL/4 ERROR/0 SKIP. 최초4 ERROR는 Python API의 기존 `show_3d_views=False` 기본값을 headless guard가 거부한 문제였고 허용값을 수정했다. 현재 미해결 실패0.
마지막 보강은 B 분석 교차검증뿐이며 전체 suite를 불필요하게 다시 돌리지 않았다. 개발 실행 기록은 development_test_history.json, 최종 통합170개 개별 로그는 final_verification/integrated_tests.log에 있다.

170개는 묶음 A 관련142개 + C15개 + F0/F_cal 특징13개다. 무관한 전체 suite와 실제 모델 fit/정식 평가 pipeline은 실행하지 않았다.
기존 capture 테스트의 녹화 안내 출력은 temp SYN fixture/가상 SDK이며 실제 녹화가 아니다.

## 10. 연구 동결·회귀 보존 근거

- source hash: formal6_evaluation, RF, F0/F_cal, H5/H9 집계, H9 runtime/모델, Schema/Decision/Master/5-D-8 문서 등 변경 없음.
- F0/F_cal/H5/H9/H9−F9 = **6/6/5/9/8열**, 기존 계산식·support/coverage·참조 P0 제외 유지.
- RF/LR 입력/결과 의미, RF seeds=(0,1,2), 개발2 LOSO, 승인 후보5+기준선3의 **8조합**, 동점/zero-support 규칙 유지. 모델 fit/재선정 없음.
- 같은 가상 SDK 입력으로 **ed22f0f 원본 probe vs 현재 기본 probe의 timing JSON 전체/설정이 동일**했다. 세 조건(원본 기본/현재 기본/현재 headless)의 count·Pose/Face/geometry/callback 호출수가 동일했다.
- 합성 H9 leaf 모델에서 headless 전후 예측/이벤트/집계 입력·호출수 동일, 독립 timer 종료 확인. 기존3-class/5-class, 6-class SYNTHETIC DEMO, adapter5상태 및 A CSV 회귀 통과.
- 기존 performance/timing JSON·CSV 컬럼/단위·통계 기본 계약 유지. headless는 없는 UI 관측을 만들지 않고 opt-in mode를 metadata/config에 표시한다. QPC 수치는 별도 sidecar에만 있다.
- 위 동등성은 합성/가상 SDK 범위다. 실제 사람 영상의 특징 품질·예측 동등성이나 실제6 모델 유효성을 증명하지 않는다.

## 11. 출처와 재현

기존 실제 증거는 `analysis/ENGINEERING_ONLY_B_RETRY_20261105_140118/`다. 새 증거는 별도 경로:

`analysis/ENGINEERING_ONLY_STAGE_5E_BUNDLE_C_20261105/run_143250/`

- start_state.json, source_before/: 시작 source/HEAD/status/clock 정보와 B32개 hash.
- before_diagnostics/: **변경 전** B 분석, 실제 clock 실험, 결정적 recorder 호출/component bench, 합성 화면 구성 bench.
- final_verification/: 통합 로그/verification, 현재 clock·화면 구성 bench, 원본/현재/default/headless 합성 원본 JSON/CSV/journal, default_equivalence.json, 별도 synthetic_qpc_diagnostics/.
- baseline_postcheck.json: 마지막 보강 이후 원본 raw event count·자원·통계·CSV까지 대조한 기준선.
- preview_excluded.json: PREVIEW 별도 검토. final_state.json: 종료 Git/원본 보존/신규 source hash.

마이크로벤치마크는 실제 PC clock으로 측정한 **합성 결정적 workload**이며 D455·연구 성능이 아니다. synthetic_qpc_diagnostics는 Mock SDK 함수의 시간을 측정한 구조 예시이므로 실제 Pose/imshow/waitKey 속도 근거로 사용하지 않는다.
analysis/는 기존 gitignore 정책을 유지했고 강제 stage하지 않았다. artifacts/는 사용하지 않았다.

```powershell
$py = 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe'
# B read-only 분석/합성 마이크로벤치마크: 출력 폴더는 새 경로
& $py -X utf8 -B stage5e_bundle_c.py analysis/ENGINEERING_ONLY_B_RETRY_20261105_140118 'analysis/<새 진단 폴더>'
# 별도 승인·확인된 비인체 장면에서 향후 사용할 예시; 이번에는 실행하지 않음
& $py -X utf8 -B posture_geometry_probe.py --views none --duration-seconds 90 --timing-warmup-frames 150 --timing-h9-warmup-calls 5 --performance-output-dir 'analysis/<새 UI run>' --engineering-diagnostics-dir 'analysis/<새 UI diagnostics>'
& $py -X utf8 -B posture_geometry_probe.py --headless --duration-seconds 90 --timing-warmup-frames 150 --timing-h9-warmup-calls 5 --performance-output-dir 'analysis/<새 headless run>' --engineering-diagnostics-dir 'analysis/<새 headless diagnostics>'
```

## 12. 미측정과 BLOCKED

엄격한 live timing-only/Performance A/B와 실제 입력/분류 동등성은 **BLOCKED(동일 입력 증거 없음)**다. 비인체 replay framework는 새로 만들지 않았다.
추가 D455 전후 실측·실제 GUI/GPU 완료·실제 사람 모델 품질·operation peak/GPU 메모리·power-loss 복구 검증은 NOT_MEASURED/NOT_RUN이다.
기존 flush는 유지되며 정상/RuntimeError/KeyboardInterrupt/CSV·timing publication 실패에서 journal/오류 상태를 확인했다. flush를 fsync/power-loss 내구성으로 해석하지 않는다.
새 diagnostic raw는 메모리에 있다가 정상/예외 종료에 별도 JSON으로 쓰므로 강제 kill이면 manifest만 남을 수 있다. 이를 COMPLETED로 해석하지 않으며 기존 flush journal의 보존 동작을 약화시키지 않는다.

## 13. 묶음 D 인계

**비인체 엔지니어링 묶음 D 진행 가능.** QPC sidecar가 활성화된 UI/headless 반복 실측으로 실제 image build/imshow/waitKey를 관측하고 CPU/RSS/private 및 종료 overhead를 분리할 수 있다.
동일 입력 재생이 없으면 OBSERVATIONAL 표기와 반복 변동을 유지하고, event buffering은 새 근거가 생기기 전 적용하지 않는다.
정식 참가자/외부4명/최종6 모델 검증과 CAP-007/IRB release는 이번 결과로 진행 가능해진 것이 아니다. HOLD/DEFERRED는 유지한다.
