# 5-E-4 — Performance JSON + CSV 연결

2026-11-04. **비정식 엔지니어링 출력 구현 / 합성 구조 검증 PASS. 실제 성능 측정 NOT_RUN.**

## 시작 상태와 권위

- Branch: `feat/aiot-stage5e-d455-readiness`.
- 시작 HEAD: `35e7a467cefc1219f57834fbe6c7e8c8ea37e82f`, 요청한 기준과 일치.
- 시작 `git status --short`: 변경 항목 없음. Git 사용자 ignore 설정과 `.pytest_cache/`의 읽기 권한 warning은 있었으며 해당 내용을 수정하지 않았다.
- 확인: `AGENTS.md`, `docs/research/AIoT_RESEARCH_MASTER.md`(현재 §24~28), `docs/research/RESEARCH_DECISION_LOG.md`(EXP-003~007 / CAP-007 보류 포함), `RESEARCH_DATA_SCHEMA.md`, `docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md`, `STAGE_5E3_READINESS.md`, 기존 `probe_timing.py` / `posture_geometry_probe.py`와 timing/H9 테스트.
- 기존 동결 문서·Schema·평가기·특징식·전처리·H9/RF/LR 규칙은 변경하지 않았다. OPEN/DEFERRED 결정도 변경하지 않았다.

## 출력과 사용

신규 `--performance-output-dir NEW_DIR`가 opt-in이다. 상위 디렉터리는 존재해야 하며 NEW_DIR 자체는 없어야 한다. `--performance-data-id ID`는 기본값 `live-unlabelled-engineering`인 엔지니어링 입력 식별자다. 연구 dataset role이나 참가자/분석 ID를 자동 부여하지 않는다.

이 옵션만 사용하면 기존 timing 수집기도 활성화하고 NEW_DIR 안에 `host_timing.json`을 쓴다. 기존 `--timing-output PATH`를 함께 지정하면 기존 JSON은 그 PATH에 쓴다. 기존 timing JSON의 필드·통계 계산·의미를 유지하며, 별도 `performance.json`의 `timing`에 같은 보고서를 그대로 포함한다. performance 옵션을 끄면 센서 식별자 읽기나 성능 파일 생성도 하지 않는다.

새 파일 종류는 `engineering-performance/1.0.0`, scope는 `NON_FORMAL_ENGINEERING`이다. 기존 scientific schema나 Patch 8 operational ledger의 새 버전이 아니다. `run_id=perf_<uuid>`는 엔지니어링 출력 식별자이며 Patch 8 `execution_id`가 아니다.

| 파일 | 역할 |
|---|---|
| `manifest.json` | 최초 RUNNING 예약 기록. run/data/config/Git/환경/계측 소스 hash. 완료 여부는 최종 JSON으로 판별 |
| `events.jsonl` | 이벤트마다 flush하는 원시 stage·프레임·센서·자원·모델/환경 근거 |
| `host_timing.json` | `--timing-output` 미지정 시의 기존 timing JSON |
| `performance.json` | 최종 run 상태, 기존 timing 보고서, 원시 이벤트 전체, journal SHA-256, identity |
| `performance_runs.csv` | 실행·metric·phase별 요약 행. count/value/p50/p95/maximum |
| `performance_samples.csv` | 개별 stage·프레임 lifecycle·센서 identity·자원 관측 행 |
| `model_benchmarks.csv` | 명시적 NOT_MEASURED 1행. 독립 모델 벤치마크 미실행 |
| `experiment_comparisons.csv` | 명시적 NOT_MEASURED 1행. 정확도·공통 표본 비교 미실행 |

기존 출력·입력과 alias/상하위 경로가 충돌하면 측정 전에 거부한다. 새 디렉터리 `mkdir`와 모든 산출물의 exclusive `x` open으로 기존 파일 덮어쓰기를 차단한다. 기존 CSV 출력 옵션을 병용해도 기존 파일은 재사용하지 않는다.

## 식별자와 컬럼

4개 CSV의 공통 prefix는 아래 순서다. 모든 CSV 행이 같은 run의 JSON으로 연결된다.

```text
run_id,data_id,model_id,config_id,config_sha256,git_commit,git_dirty,
environment_json,run_status,evidence
```

- `model_id`: 역할→실제 파일 SHA-256의 canonical JSON map. 모델 미연결은 `{}`이며 가짜 모델 ID를 만들지 않는다. 모델 경로와 hash는 최종 JSON과 journal에도 보존한다.
- `config_id=probe-options/1`, `config_sha256`: 실제 전달된 processing/UI/duration/warmup/설치 옵션 및 부가 출력의 활성 여부를 정렬한 canonical UTF-8 JSON의 SHA-256. 출력 경로·stream/subject 문자열·모델 경로는 hash에서 제외한다. 모델 bytes는 별도 `model_id`로 비교한다. run/data/model/config를 함께 대조해야 한다.
- `git_commit`/`git_dirty`: 실행 준비 시 Git 상태. 조회 실패 시 JSON에 NOT_MEASURED와 사유를 기록하고 CSV 해당 값은 빈칸이다. dirty tree를 commit만으로 동일하다고 취급하지 않도록 계측 관련 소스 3개의 SHA-256도 JSON에 기록한다. 전체 저장소 snapshot hash는 아니다.
- `environment_json`: Python/OS/machine/processor/관련 배포 패키지 버전. 실제 probe에서는 읽을 수 있는 장치 이름·serial·firmware·USB 정보 및 원래 RGB/depth profile의 크기/nominal FPS/format도 추가한다. 조회 불가 항목은 NOT_MEASURED/사유를 남긴다. nominal profile FPS는 측정 FPS가 아니다.
- `evidence=performance.json`: 같은 디렉터리의 최종 JSON. JSON에 원시 이벤트가 포함되어 재생성 시 SDK·모델·데이터를 다시 열지 않는다.

| CSV | 공통 prefix 뒤 컬럼(순서대로) |
|---|---|
| `performance_runs.csv` | `metric,phase,unit,measurement_status,reason,count,value,p50,p95,maximum` |
| `performance_samples.csv` | `sample_index,kind,phase,name,frame_id,token,host_monotonic_ns,duration_ns,value,unit,measurement_status,source_frameset_number,source_frame_number,device_timestamp_ms,timestamp_domain,process_cpu_ns,cpu_one_core_percent,rss_bytes,private_bytes,os_peak_rss_bytes,details_json` |
| `model_benchmarks.csv` | `measurement_status,reason,model_sha256,input_id,calls,unit,p50,p95` |
| `experiment_comparisons.csv` | `measurement_status,reason,comparison_id,dataset_sha256,evaluation_rule_id,support,accuracy,macro_f1` |

`MEASURED`는 해당 관측값 존재, `NOT_MEASURED`는 값 없음이다. 숫자가 없는 CSV cell은 빈칸, JSON 값은 null이다. 0으로 대체하지 않는다. `count=0`인 자원 분포는 p50/p95/maximum이 비어 있고 NOT_MEASURED다. 미관측 stage의 행을 임의로 만들지 않는다. 자원 샘플 행은 sampling 사실을 나타내며, 개별 미지원 자원 필드는 빈칸/JSON 사유와 요약 count=0으로 구별한다.

요약 stage 통계는 기존 `_stats`의 결과를 복사한다. p50/p95는 기존 NumPy percentile(default linear)이며, raw `duration_ns / 1e6`로 대조 가능하다. 중첩 stage들의 p95를 더하지 않는다. 각 분포는 warmup/steady/collection을 유지한다. H9 full-window warmup과 frame warmup을 합치지 않는다.

단위는 stage/latency=`ms`, raw duration/host/process CPU clock=`ns`, stream duration=`s`, FPS=`1/s`, 수=`count`, 메모리=`bytes`, CPU=`percent_one_core`(1 core=100%)다. raw resource 행은 각 명명된 컬럼의 단위를 따른다. 누락률 예약 단위는 `ratio`이나 이번 구현은 산식을 정하거나 값을 산출하지 않는다.

## FPS·프레임·UI 해석

- `frameset_fps`는 기존 `delivered_input_fps` 그대로, 전체 stream의 실제 전달 framesets / 기존 `stream_seconds`다. 유효 처리 FPS와 다르며 warmup·invalid pair·deadline 경계 입력도 기존 규칙대로 남긴다.
- `processed_fps`는 기존 처리 완료 수 / 같은 stream 시간이다. unfinished frame은 별도 수와 원시 input 근거에 남긴다.
- `rgb_unique_frames` / `depth_unique_frames`는 **정렬 전 원래 SDK child의 관측 고유 frame number** 수다. `*_unique_fps`는 각각의 수 / 같은 Host stream 시간이다. SDK 전달에서 관측한 고유 입력률이며 센서 전체 발생률을 증명하지 않는다.
- 동일 sensor 번호·timestamp·domain의 재사용은 고유 수에서 한 번만 센다. `*_reused_deliveries`로 별도 수를 남긴다. 원래 frameset 입력과 geometry/landmark 실행은 삭제·캐시·재정렬·+1 보정하지 않는다. 기존 MediaPipe용 timestamp 처리도 그대로다.
- sensor ID/timestamp/domain 누락, domain 변경, 번호/시간 역행, 재사용 번호의 timestamp 변경 시 그 sensor의 고유 수/FPS는 NOT_MEASURED다. payload 동등성은 이번 계측기가 검사하지 않으며, 5-E-3 offline 재사용 적격성 판정을 대체하지 않는다.
- `rgb_missing_rate`와 `depth_missing_rate`는 항상 NOT_MEASURED다. 센서별 연속성 신뢰성과 누락률 상세 계약이 확인되지 않았기 때문이다. 기존 frameset source gap count를 누락률로 바꾸거나 coverage/nominal FPS로 추정하지 않는다.
- raw `token`은 전달 frameset input에, `frame_started`/`frame_completed`는 token과 기존 processed `frame_id`에 연결된다. sensor 이벤트는 token을 통해 연결한다. 실패한 frame도 started/input 근거를 유지한다.
- raw stage의 `host_monotonic_ns`는 기록 시점이며 duration의 정확한 시작 시각이나 sensor clock으로 해석하지 않는다. H9 이벤트에는 prediction ID와 마지막 입력 frame ID만 추가하며 새 특징·예측값·라벨은 수집하지 않는다.
- UI stage/latency는 **Host application 제출까지**다. 물리적 화면 표시·GPU completion·sensor-to-screen latency는 NOT_MEASURED다. H9 최초 준비/최초 UI 제출 시간과 성공 inference 수는 기존 보고서에서 별도 요약한다.
- 자원은 기존 1Hz process monitor와 시작/종료 샘플을 재사용한다. 외부 browser·GPU 메모리를 측정하지 않는다. opt-in journal/CSV 준비의 계측 overhead가 생기므로 실제 실행 수치를 비계측 실행과 동일하다고 주장하지 않는다.

## 오류·중단과 재생성

`run_status`는 COMPLETED(정상 duration/completed), INTERRUPTED(q/KeyboardInterrupt), FAILED(runtime/cleanup/timing publication 오류), INCOMPLETE(기타 미완료)로 나눈다. 측정 종료 상태이며 scientific PASS·baseline 선정·실행 승인이 아니다. 기존 timing JSON의 `error`, `cleanup_errors`, `termination`, baseline 차단 사유는 그대로 포함한다.

초기 모델/SDK 준비도 기존 cleanup/finalization 범위 안으로 옮겨 초기화 오류를 기록한다. metrics 객체 생성 전 예약 경쟁 실패는 `setup_failure.json`에 FAILED를 남긴다. 측정값이 없으므로 가짜 timing/CSV를 생성하지 않는다. 기존 timing 파일이 마지막 publication에서 충돌해도 해당 파일을 보존하고 performance JSON에 publication error/FAILED를 남긴다.

최종 JSON을 CSV보다 먼저 기록한다. CSV 저장 실패 시 `export_failure.json`의 FAILED/사유와 기존 JSON/journal을 보존한다. 이 경우 `performance.json.run_status`는 측정 자체의 상태이고 export 상태는 별도 실패 기록이다. 재실행으로 같은 디렉터리를 덮어쓰지 않는다.

강제 kill/전원 상실로 finalization이 없으면 최초 manifest와 flush된 journal만 남을 수 있다. 최종 JSON 부재를 성공으로 해석하지 않는다. 강제 kill 후 자동 복구/이어찍기는 구현하지 않았다.

다음 명령은 **재측정 없이** 새 디렉터리에 JSON과 CSV만 재생성한다. 기존 디렉터리는 거부한다.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B performance_output.py analysis/ENGINEERING_ONLY_5E4_20261104/synthetic_example/performance.json analysis/ENGINEERING_ONLY_5E4_20261104/new_regeneration
```

## 실제 실행한 검증

최종 **109 tests PASS / failures 0 / errors 0 / skipped 0**, 10개 모듈. 신규 성능 테스트는 17개, 기존 timing/H9 probe 3개 모듈은 33개, 기타 관련 합성 회귀는 59개다. 저장소 전체 검사나 독립 감사는 아니다. `git diff --check`도 PASS다.

최종 실행:

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B analysis/ENGINEERING_ONLY_5E4_20261104/verify_synthetic.py
```

이 스크립트가 실행한 모듈: `test_performance_output`, `test_probe_timing`, `test_h9_probe_timing`, `test_h9_probe_integration`, `test_h9_async_runtime`, `test_h9_time_window`, `test_h9_csv_replay`, `test_stage5e_readiness`, `test_live_f1_d455`, `test_capture_end_timing`.

검증 범위: 필드/순서·단위·p50/p95·warmup/collection·카운트·원본 timing JSON 구조/값 보존·JSON/CSV 재생성 byte 일치·raw event/journal hash 대조·CPU/RAM·RGB 재사용/new depth·정렬 전 ID 보존·미측정 누락률·sensor 신뢰성 부족·경로 alias/중첩/기존 파일·runtime/cleanup/KeyboardInterrupt/q·초기화/출력 경쟁 실패·CSV 저장 실패. 기존 추론/geometry 호출 수가 opt-in 전후 같음도 가상 SDK로 확인했다.

예시의 `data_id=SYNTHETIC_STRUCTURAL_TEST_ONLY`, config/metadata의 `measurement_source=SYNTHETIC_VIRTUAL_CLOCK`를 명시했다. 예시의 모든 duration/FPS/CPU/RAM 숫자는 합성 구조 시험값이며 실제 성능·연구 결과가 아니다. 일부 기존 테스트의 pilot/formal 문자열·녹화 안내 출력도 temp fixture와 가상 SDK 대상이며 실제 촬영이 아니다.

증거 및 생성 파일(`analysis/ENGINEERING_ONLY_5E4_20261104/`):

이 경로는 기존 `.gitignore`의 `analysis/` 규칙에 해당한다. 파일은 로컬에 보존했으며 ignore 규칙 변경이나 강제 stage는 하지 않았다.

- `verify_synthetic.py`: 위 합성 예시·재생성 대조·회귀 실행 스크립트. 재실행 시 기존 파일 덮어쓰기 거부.
- `final_tests.log`: 109개 테스트별 결과.
- `verification.json`: 실제 실행 수·결과, JSON/CSV 5개 파일의 byte 일치 SHA-256, 미실행 범위.
- `synthetic_example/manifest.json`, `events.jsonl`, `host_timing.json`, `performance.json`, `performance_runs.csv`, `performance_samples.csv`, `model_benchmarks.csv`, `experiment_comparisons.csv`: 합성 원본 예시 8개.
- `regenerated_example/performance.json`, `performance_runs.csv`, `performance_samples.csv`, `model_benchmarks.csv`, `experiment_comparisons.csv`: 동일 JSON으로 재생성한 5개. 원본 예시와 byte 일치. 원 journal은 원본 예시 폴더에 보존한다.

## 변경 파일·남은 조건

| 파일 | 변경 동작 |
|---|---|
| `performance_output.py` (신규) | engineering identity/경로 예약, raw journal·최종 JSON, 4종 CSV projection, 재생성 CLI |
| `probe_timing.py` | 기존 샘플·카운트의 opt-in 전달, 자원/프레임/H9 이벤트, timing 저장 실패 시 성능 근거 보존. 기존 report contract 유지 |
| `posture_geometry_probe.py` | 신규 옵션/자동 timing 연결, 설정·모델·환경 pin, 정렬 전 sensor identity, 실패 frame 연결, 초기화 오류 finalization |
| `test_performance_output.py` (신규) | 합성 전용 17개 테스트. 기존 테스트 수정 없음 |
| `STAGE_5E4_PERFORMANCE.md` (신규) | 본 상태/스키마/해석/검증/미실행 범위 |
| `analysis/ENGINEERING_ONLY_5E4_20261104/` (신규) | 위에 열거한 스크립트·합성 예시·재생성본·검증 로그 |

실제 D455 성능 실행·센서별 누락률 신뢰성 검증·독립 모델 벤치마크·정확도 비교는 미구현/미실행 범위다. 모델/특징/전처리/최적화, 학습과 평가 규칙 변경은 없다. 기존 데이터셋·파일럿/정식/외부 원본·실제 참가자를 사용하지 않았다.

실측 비교에는 별도로 명시된 입력/모델/설정·장치 환경과 적절한 실행 조건이 필요하다. 5-E-3의 IRB/동의/운영 release 및 최종 선정/동결·독립성 조건, OPEN-005의 남은 항목과 CAP-007 정식 Patch 8 execution 보류는 유지한다. 이번 작업은 실제 D455나 정식 Patch 8을 실행하지 않았고 registry/execution_id를 만들지 않았다. commit/push 없음.
