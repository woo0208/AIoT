# E0 FS3 실행 성능 계측 보완

2026-11-09. 비정식 engineering 계측 구현이며 실제 실행 성능 결과나 촬영 승인 문서가 아니다.
참조: [이전 로그 검토](analysis/PERFORMANCE_LOG_REUSE_REVIEW_20261108/REPORT.md).
최신 상태는 아래 **E0-P3 통합 검증** 절이다. 기존 P1/P2 기록은 당시 상태로 보존하며, P3에서는 로그 저장 방식을 보완했다.

## 연결과 보존 범위

- `posture_geometry_probe.run_probe(e0_session=...)`를 선택적으로 연결했다. 기본 경로는 그대로이며 기존4초 H9/RF 경로를10초 SVM 경로로 바꾸지 않았다.
- 기존 geometry 계산 결과의 H9 열을 재사용한다. FS3 열은 F1,F3,F4,F5,F6,F7,F8이다. 수식·MediaPipe 설정·Depth 처리 변경이나 결측 채움은 없다.
- 기존120구간 평가와 같이 원래 H9 9열 공동 유효 support에서 `aggregate_h5_h9_sample`을 호출한 뒤7개 열을 선택한다. 따라서 제외 열에 결측이 생겼다고7열만으로 적격 판정을 완화하지 않는다.
- F3 원형평균, 나머지 중앙값, 공동 유효≥30개·coverage≥50%, 정의되지 않은 원형평균의 부적격 처리를 그대로 사용한다.
- 수동 안정 자세 구간의 첫 프레임 장치시각을 기준으로 `[first, first+10000ms)`를 수집한다. 경계에 도달한 다음 관측은 앞 구간에서 제외한다. 준비·전환·취소 구간을 분석 표본으로 자동 편입하지 않는다. 장치시각 중복/역행은 해당 구간을 중단하고 보간하지 않는다.
- 선택한 **이미 학습된** SVC/StandardScaler를 호출자가 제공한다. C=1, gamma=1/9, class_weight=None, probability=False, random_state=0 등 T0 전체 estimator 설정, fitted gamma,7열·6클래스·scaler 형상을 확인한다. fit·자동 모델 선택·pickle 로드·학습은 하지 않는다. 학습 계보와 artifact hash는 이 메모리 객체 검사만으로 입증되지 않는다.
- 공식8조합·B6·IRB 관련 규칙·Patch8 실행 보류는 변경하지 않았다.

## 계측 내용과 시간 경계

모든 E0 interval은 `time.perf_counter_ns()`다. 합성 테스트에만 가상 clock을 주입한다. 기존 `ProbeDiagnostics`에 E0 전용 p99·예외 문자열 비식별 옵션을 추가했으며 기본 출력 형식은 유지한다.

|기록|의미|
|---|---|
|`receive.wait`|SDK 수신 호출 시작→반환. 타임아웃도 구분 기록|
|`receive.align`, `input.convert`|실제 기존 정합·변환 호출|
|`mediapipe.pose`, `mediapipe.face`|동일 프레임의 기존 검출 호출|
|`depth_geometry`|기존 Depth·기하·특징 계산 전체. FS3 외 기존 보조 계산도 포함|
|`fs3.feature_select`|이미 계산된 특징의 선택·유효성 점검. 실제 특징 추출 비용으로 오해하지 않음|
|`fs3.aggregate`|기존10초 구간 집계 함수의 실행 비용|
|`fs3.scale`, `fs3.svm`|transform과 predict를 각각 측정|
|`latency.receive_to_features`|SDK 반환 직후→프레임 특징 선택·유효성 점검 완료|
|`latency.receive_to_frame_complete`|SDK 반환 직후→해당 loop 완료. 경계 프레임에서 집계·판정이 발생하면 그 비용도 포함|
|`latency.receive_wait_start_to_frame_complete`|SDK 수신 대기까지 포함한 loop 지연|
|`latency.first_input_to_prediction`|구간 첫 수신→판정.10초 누적·경계 관측 대기 포함|
|`latency.last_input_to_prediction`|집계 대상 마지막 입력 수신→판정. 유효 support의 마지막 프레임만을 뜻하지 않음|
|`latency.boundary_input_to_prediction`|10초 종료 경계를 확인한 입력 수신→판정|

각 관측 단계는 count/p50/p95/p99/maximum을 기록한다. 미실행 단계에는 표본이 없으며, 단계를 합산해 전체 p95를 만들지 않는다. 센서 노출→물리 화면 표시, GPU 완료, 사용자 자세 변화→판정 반응시간은 측정하지 않는다. 10초 누적 지연과 순수 연산 비용을 구분한다.

## 프레임·구간·판정 로그

- `frames.jsonl`: RGB/Depth 각각 raw/aligned의 번호·timestamp·domain·stream/profile identity, 비교 결과, 프레임별7특징 성공 여부·H9 공동 support 여부·실패 사유, 관측 Pose/Face 검출 여부. 센서 접근·비교는 기존 `frame_provenance.snapshot/compare`를 재사용한다.
- 동일 identity 중복, 다른 센서가 진행하는 동안 child 재사용, 같은 번호/다른 시각, 번호 gap, 번호 역행(reset 또는 wrap), 시각 역행, domain/profile 경계를 구분한다. 픽셀 비교나 물리적 센서 리셋을 입증하는 것은 아니다. 정합 전후 선택 변경도 별도 기록한다.
- `segments.jsonl`: 로컬 순번,10초 경계, 입력 수·공동 유효 수·coverage·적격 사유·집계 시간·scale/SVM 개별 시간·판정 성공/실패·P0~P5 결과. 취소·종료 시 미완료 구간을 보존하고 예측하지 않는다. 실패한 판정을 이전 판정으로 대체하지 않는다.
- `summary.json`: 실제 수신을 분모로 하는 특징 계산 성공률, 미평가 수신 수·상태별 수, 판정 파이프라인 및 실제 SVM 호출 각각의 시도 대비 성공률, 처리/유효 FPS, 센서별 관측 사건 수. 무시도 비율은 null이다. FPS는 전체 stream 구간 기준이며 고유 새 RGB FPS와 구분한다.
- `timing/diagnostics.json`: 고해상도 raw duration과 percentile. 예외 메시지 대신 타입만 저장한다.
- 센서 전체 생산량·중복/유실의 원인을 확정할 수 없어 `sensor_missing_rate=NOT_MEASURED`를 유지한다. P1에서 미구현이었던 CPU/RAM 동시 수집과 조건부 GPU 관측은 아래 P2에서 추가했다. 기존 resource logger의 별도 과거 관측은 보존한다.

원본 RGB/Depth·영상·랜드마크 좌표·특징값·scaler 통계·학습 모델·정답 라벨·참가자/장치 식별자·UTC·임의 예외 문자열은 새 로그에 저장하지 않는다. 요구된 센서 timestamp와 로컬 프레임/구간 순번, 판정 결과는 기록하므로 실행 로그는 `local_private/` 등 Git 제외 위치에 보관한다. 식별자를 쓰는 기존 writer/performance bundle과 E0의 동시 활성화는 명시적으로 거부한다.

## 호출 인터페이스와 실제 실행 전 남은 일

카메라를 여는 새 CLI나 자동 실행은 추가하지 않았다. 향후 승인된 실행 제어기는 다음 API를 사용할 수 있다. 아래는 인터페이스 설명이며 이번 작업에서 실행하지 않았다.

```python
from e0_fs3 import E0Session
from posture_geometry_probe import run_probe

# model/scaler: 별도로 선택·계보와 hash를 확인한 기존 FS3 T0 객체.
session = E0Session("analysis/<new-run>/local_private/e0", model, scaler)
# 안정 자세에서 Enter 등의 조작으로 session.arm_segment() 호출.
# 전환·중단 시 session.cancel_segment() 호출. 다음 구간은 다시 명시적으로 arm.
# run_probe(e0_session=session, ui_poll=operator_panel_poll, show_3d_views="none")
```

실제 측정 전에는 사용할 artifact/학습 표본 수·hash 확정, 운영 패널의 안정 자세 시작·취소 연결, 화면·해상도·스레드·예열/반복·관측 구간 고정 및 대상자/실행 승인 범위 확인이 남아 있다. 기존120구간의 fold 모델을 전체120개 학습 배포 모델로 자동 간주하지 않는다. 실제D455 연결·타임아웃/리셋·장시간 overhead·자원 부담은 합성 테스트로 입증하지 않는다.

## 검증

합성 clock/SDK/geometry/추론 대역만 사용한다.10초 반개구간, 준비·취소 제외, 기존 batch 집계와 정확한 입력 일치, H9 support/30·50 경계·원형평균 무정의, 단계별 고해상도 percentile과 판정 지연, 센서 중복·gap·reset/domain 경계, 실패 시 부분 로그·예외 비식별·SDK cleanup, 계측 전후 geometry/callback 불변을 확인한다. 가상 clock을 주입한 E0 출력은 `SYNTHETIC_STRUCTURAL_TEST_ONLY`로 구분한다. 실제 카메라·모델 학습·실측 성능 비교는 수행하지 않는다.

관련 테스트는 **166개 통과: 신규18개 + 기존148개**다. 실행 명령:

```text
python -X utf8 -B -m unittest -q test_e0_fs3 test_frame_provenance test_probe_timing test_h9_probe_timing test_h9_probe_integration test_capture_six_pilot test_f1_sample_aggregator test_upper13_csv test_capture_protocol
```

소스4개의 AST/compile·공백 검사와 `git diff --check`도 통과했다. 전체 회귀는 실행하지 않았다. 기존 일부 인자 거부 테스트의 argparse 오류 출력은 예상된 음성 테스트 출력이며 전체 결과는 OK다. Stage·Commit·Push는 하지 않는다.

## E0-P2 보완 — CPU/RAM·조건부 GPU·모드별 오버헤드

FS3 수식·모델·10초 창·원래 H9 support·30/50 적격 기준·공식8조합·B6·IRB 규칙은 그대로다. `e0_resources.py`를 추가하고 `probe_timing.process_memory/_stats` 및 기존 `ProbeDiagnostics`를 재사용했다. 새 외부 패키지를 설치하지 않는다.

### 모드와 호환성

`E0Session(..., mode='detailed')`의 기본값은 기존 상세 계측이다.

|mode|동작|
|---|---|
|`off`|동일 FS3 수집·집계·판정·입력 검증 유지. 계측 시계·메타데이터 관측·자원 모니터·계측 파일 출력 없음. `directory=None`도 허용. 공통 E0 API 호출과 기능 상태 관리는 남음|
|`summary`|단계별 count/p50/p95/p99, 구간 결과·자원 시계열·누적 센서 사건 수. 프레임 상세 JSONL과 raw timing 레코드는 보존하지 않음|
|`detailed`|기존 프레임/구간/원시 timing 형식에 자원 기록을 추가. 모두 메모리에 모아 종료 시 출력|

요약 모드도 정확한 percentile을 위해 숫자 duration 표본은 보관한다. 일정 메모리 사용을 보장하는 방식은 아니다. 기존 상세 파일/필드와 일반 `ProbeDiagnostics` 기본 출력은 유지하며 요약 출력의 `raw=[]`에는 `raw_status=NOT_RETAINED_SUMMARY`를 표시한다. 기존 `test_e0_fs3.py`는 수정 없이 통과했다.

### 자원과 GPU

- `resources.jsonl`의 `host_perf_counter_ns`는 프레임 로그와 같은 주입 clock/실행 시 `time.perf_counter_ns`다. 기본1초 간격의 별도 observer thread와 시작/종료 경계 샘플을 사용한다. 가상 clock에는 가상 자원 reader를 명시적으로 제공하며 실제 자원 카운터와 혼합하지 않는다.
- 프로세스 CPU는 누적 process CPU time 차이/동일 host 경과 시간으로 계산한다. `process_cpu_one_core_percent`는1코어=100%, `process_cpu_percent`는 논리 코어 수로 나눈 전체 용량 기준이다. 논리 코어 수와 시스템 전체 CPU%도 기록한다. 최초 샘플·카운터 역행·미지원은 null/NOT_MEASURED이며0으로 채우지 않는다.
- RSS·Private Bytes·OS lifetime peak working set을 구분한다. 평균이 아닌 p50/p95·관측 최고·처음/마지막/변화량과 시계열을 보존한다. sampled peak는 순간 최고를 놓칠 수 있고 Private는 실제 상주 RAM과 다르다.
- Windows 시스템 CPU는 [GetSystemTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)의 kernel+user에서 idle을 분리한다.64개 초과 논리 코어의 다중 processor-group 환경 등 지원 범위 밖에서는 시스템 CPU를 확정하지 않는다. Linux는 `/proc/stat`을 지원하며 미지원 OS/실패는 NOT_MEASURED다.
- 선택적 읽기 전용 [nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html) provider가 GPU 모델·device-wide 사용률·VRAM 사용/총량을 조회한다. GPU query는 frame loop가 아닌 observer thread에서만 실행하며1초 timeout과 숨김 창을 사용한다. 도구/드라이버/권한/필드 미지원은 NOT_MEASURED다.0이라는 실제 응답과 미측정을 구분한다. 다른 vendor용 API는 추가하지 않았다.
- GPU 사용률/VRAM은 장치 전체이며 이 프로세스나 MediaPipe 추론에 귀속시키지 않는다. 실제 SVC 구현은 CPU/libsvm으로 식별한다. Pose/Face의 설정된 delegate는 읽기만 하고, 실제 runtime backend를 확인할 API가 없어 `actual=NOT_MEASURED`로 유지한다. delegate·실행 방식 변경이나 GPU warmup/부하 생성은 하지 않는다.
- JSON에는 하드웨어 모델명과 요청된 숫자 관측만 기록한다. 장치 serial/UUID·PC/사용자명·프로세스 목록·원본 stdout/stderr·원본 영상·랜드마크·특징값·임의 예외 메시지를 저장하지 않는다. GPU/CPU sampler의 자체 관측 시간도 기록한다.

### 대기열

현재 E0 경로는 동기식 수신→처리→집계/판정이다. 애플리케이션 작업 큐가 없으므로 길이·대기시간·드롭은 `NOT_APPLICABLE`이다. 가상 큐를 추가하거나10초 집계용 records를 미처리 작업 큐로 취급하지 않는다. 센서 수신 대기는 기존 `receive.wait`로 측정한다. SDK 내부 큐 길이·대기시간·드롭 수와 센서 누락률은 `NOT_MEASURED`를 유지한다.

### 합성 오버헤드 비교

본 결과: [E0_P2_OVERHEAD_20261109_FINAL/REPORT.md](analysis/E0_P2_OVERHEAD_20261109_FINAL/REPORT.md). 모드당 새 프로세스3개, 각20구간×151개 관측, 순서 교대다. 모든 모드에 동일 외부 프레임 타이머·CPU/RAM 관측기와 고정 합성 CPU 부하를 적용했다. 전체27,180개 관측의 입력 hash와 기능 결과 hash가 일치했다. 공통 timer/observer 비용은 OFF에도 있다.

|모드|외부 프레임 p95 ms|합성 처리량 frames/s|RSS 관측 최고 MiB|
|---|---:|---:|---:|
|OFF|0.3003|3855.44|126.07|
|요약|0.3644|3340.65|127.96|
|상세|0.3644|3260.75|154.03|

각 프로세스 지표의 중앙값이다. 실제 MediaPipe/Depth 추론을 실행하지 않고 기존 집계와 합성 SVC 대역을 사용했다. 실제15FPS·전체 FS3 지연·분류 성능이나 최적화 성과가 아니다. 상세 종료 출력은 중앙값118.04ms, 요약은3.64ms이며 loop 처리량과 분리했다. CPU·시스템 부하·Private·raw duration·자원 시계열은 보고서/로컬 전용 근거 파일에 보존한다. 짧은 약0.8~0.9초 loop이므로 본 비교의 자원 시계열은 시작/종료 샘플이며 장시간 안정성·CPU 우열을 주장하지 않는다. 주기 샘플 동작은 별도 합성 회귀로 확인했다.

`analysis/E0_P2_OVERHEAD_20261109/`는 짧은 예비 관측이며 테스트 실행과 일부 겹쳐 본 비교표에 사용하지 않았다. 원본은 덮어쓰지 않았다. 최종 비교는 테스트와 겹치지 않게 순차 실행했다. 상세 임시 로그는 합성 비교의 TemporaryDirectory에서만 만들고, 최종 근거 숫자는 `local_private/results.json`에 보관한다.

```text
python -X utf8 -B benchmark_e0_modes.py --segments 20 --repetitions 3 --output-dir analysis/E0_P2_OVERHEAD_20261109_FINAL
python -X utf8 -B benchmark_e0_modes.py --verify --output-dir analysis/E0_P2_OVERHEAD_20261109_FINAL
python -X utf8 -B -m unittest -q test_e0_p2 test_e0_fs3 test_frame_provenance test_probe_timing test_h9_probe_timing test_h9_probe_integration test_capture_six_pilot test_f1_sample_aggregator test_upper13_csv test_capture_protocol
```

P2 검증: **177개 통과(P1 관련166개+P2 신규11개)**. 모드별 입력/지원/예측·실제 probe의 합성 SDK callback 불변, CPU 정규화·미지원/리셋·메모리 추이, 주기 수집·종료/저장, GPU field 미지원·timeout 경로·frame thread 비차단, backend 설정 불변을 확인했다. 저장 timing·resource 통계와 표, 입력/결과/source hash도 재검증했다. 합성 입력 구조 검증과 합성 workload 비용 관측이며 실제 연구 데이터 결과가 아니다.

### E0-P3 전 남은 작업

모델/scaler artifact·학습 표본 수·hash 확정과 수동 안정 구간 시작/취소 패널 연결, 사용할 모드·주기·예열·지속시간·반복·화면/입력 profile 조건 고정이 남아 있다. 대상 장치의 GPU provider/실제 backend 확인 가능 범위·권한·clock·장시간 로그 메모리/출력 비용을 실제 승인된 실행에서 점검해야 한다. 실제 카메라 촬영·재학습·E1 최적화·Stage·Commit·Push는 수행하지 않았다.

## E0-P3 통합 검증 — 실제 실행 전

최종 근거는 [E0_P3_INTEGRATION_20261109_CHECKED/REPORT.md](analysis/E0_P3_INTEGRATION_20261109_CHECKED/REPORT.md)와 그 폴더의 `local_private/`다. 이전 `E0_P3_INTEGRATION_20261109/`는 검증기 문제로 MODEL_NOT_READY를 기록한 예비 결과, `_FINAL`·`_VERIFIED`는 환경/로그 경계 보강 전의 통합 결과이며 덮어쓰지 않았다. 모델·원본 촬영자료·기존 결과는 보존했다.

### 실제 모델과 Scaler

기존 repetition0의 LOSO fold0/1 SVM·Scaler가 모두 로드됐다. 각각60구간 학습 모델이며 전체120구간 학습 배포 모델로 간주하거나 실측용 한 모델을 자동 선정하지 않았다. 상태는 **MODEL_READY_FOR_EXISTING_LOSO_REPLAY / LIVE_ARTIFACT_NOT_SELECTED**다.

`e0_model.load_fs3`는 명시된 신뢰 가능한 로컬 artifact의 SHA-256을 먼저 확인한 후 `(model, scaler)`를 로드한다.7개 특징 순서·6클래스·T0 전체 파라미터·fitted gamma·Scaler 설정/형상·학습 수를 확인한다. 모델과 Scaler 각각의 SHA-256은 검증된 객체를 pickle protocol5로 메모리 직렬화한 component fingerprint이며 별도 원본 파일 hash인 것처럼 표현하지 않는다. 바이트/버전/순서/설정이 맞지 않거나 파일이 없으면 MODEL_NOT_READY이고 학습/대체하지 않는다.

개별 archive/model/scaler hash와 명시적 로드 경로는 로컬 전용 `model_fold0.json`, `model_fold1.json`에 저장했다. 실제 source 학습 행의 평균·분산 및 기존 held-out 예측과 대조했다. fit은 호출하지 않았다.

검증기에서 현재 scikit-learn 생성자의 `probability='deprecated'` 기본값에 의존하던 문제를 수정했다. 원래 생성기가 명시한 **probability=False**를 포함해 T0 설정을 명시적으로 비교한다. 실제 모델 설정/파일은 변경하지 않았으며 합성 fixture도 이 명시 설정으로 수정했다. 과거 합성 비용 관측을 실제 모델 연결 성공의 근거로 대체하지 않는다.

### 10초 구간 UI 연결

`e0_panel.OperatorPanel`의 Start/Enter→ARMED→첫 관측 COLLECTING→기존10초 경계에서 COMPLETED 또는 INELIGIBLE이 연결됐다. Cancel/T/Escape·포커스 이탈은 취소, Q/창 닫기는 취소 후 종료다. 키 반복으로 중복 시작하지 않으며 완료 뒤 자동 재시작하지 않는다. 원래 H9 지원/30개·50% 적격 기준을 그대로 사용한다.

`run_bound_probe`는 검증된 모델·Scaler→E0Session→운영 패널→기존 run_probe의 ui_poll 연결을 제공한다. 명시적인 `execution_authorized=True`가 없으면 실행을 거부한다. 이 인자는 IRB·CAP-007·정식 촬영 승인을 대신하지 않는다. 실제 Tk 창·카메라는 이번에 열지 않았으며 위젯 대역과 합성 probe runner로 연결을 검증했다.

### 로그 메모리·안전 저장

P2 누적 원인은 frame dict·원시 timing dict·정확한 percentile용 numeric duration·구간/자원 시계열을 모두 RAM에 보관한 것이다. P3 `e0_storage.CheckpointList`는 기본 **로그별256개 레코드**를 넘기기 전에 순서대로 디스크 체크포인트를 기록한다. timing duration도 동일 상한을 사용한다. 임의 샘플링·누락·eviction은 없다.

체크포인트는 `.partial`에 독점 생성→flush/fsync→rename하며, 기존 파일을 덮어쓰지 않는다. canonical frames/segments/resources JSONL과 diagnostics JSON은 같은 필드/순서 의미로 streaming publication한다. 최종 summary는 다른 출력 성공 후 마지막에 원자적으로 게시한다. 중단 시 이미 커밋된 checkpoint가 남고 미완료 `.partial`을 성공 결과로 읽지 않는다.

정확한 p50/p95/p99는 SQLite 임시 디스크 정렬과 NumPy와 같은 선형 보간으로 계산한다. SQLite cache1MiB·temp_store=FILE·mmap 비활성이고, 랜덤4097개를 포함한 수치 테스트에서 NumPy와 일치했다. 기존 기본 ProbeDiagnostics 경로는 보존한다. 프레임 checkpoint는 SDK 대기 시작 시각을 찍기 전에 기록하여 디스크 비용을 센서 대기시간으로 잘못 산입하지 않는다.

레코드 최대64KiB, spool별 최대64MiB이며 초과/디스크 오류는 명시적 LogStorageError로 중단한다. 자원 observer thread의 저장 실패도 frame loop에 전달한다. 구간 내 특징 버퍼·학습 모델·OS 파일 캐시까지 포함한 전체 RSS의 하드 상한은 아니다. SQLite 내부 메모리도 Python 레코드 상한과 구분한다. checkpoint와 canonical 출력·임시 통계를 위한 여유 디스크가 필요하다.

9,000개 동일 로그의 Python allocator 최고치 비교는 **29.45MiB→1.09MiB(96.30% 감소)**, 최대 보관 레코드9,000→256이었다. 모든 레코드와 checksum을 보존했다. 근거는 `local_private/memory_verification.json`이며 전체 프로세스 RSS·실제 D455·E1 성능 개선 수치는 아니다.

P3부터 RAM 상한을 위해 중간 checkpoint I/O가 생긴다. P2의 '종료 시에만 I/O' 서술은 P2 당시 방식이다. checkpoint 비용은 stream 처리량·수신 전 대기 간격 등에 영향을 줄 수 있고 buffer 상태에 flush 시간을 별도 기록한다. 과거 P2 비용을 P3 실측 기준값으로 재사용하지 않는다. 실측에서 observer 비용과 누락/유효율을 함께 확인해야 한다.

### 저장 입력·회귀 검증

기존 적격120구간×OFF/요약/상세=**360건**에서 원래 batch 집계7열과 기존 held-out 예측이 정확히 같았다. 원래9열 공동 support·원형평균·중앙값·30/50은 유지했다. 새 로그에는 원본 식별자/특징값/정답을 복사하지 않았다. 원래 장치시각 간격을 보존한 구간 상대시각과 가상 host clock을 쓰는 **post-geometry 저장 입력 검증**이다. 센서 번호/domain은 알 수 없어 NOT_MEASURED로 두고 RGB-D 프레임을 만들어 넣지 않았다. 이 재생의 FPS는 NOT_MEASURED다.

기존177개를 포함한 회귀 **193개 통과(신규16개)**. 저장 입력 검증, 모델 hash/설정·변경된 라이브러리 기본값, UI 키/버튼·취소/완료, 상한·정확한 percentile·순서 보존·쓰기 실패/부분 로그·observer 실패 전달·checkpoint와 센서 대기 경계 분리를 확인했다. 실제 사람/영상·카메라·새 학습·E1은 실행하지 않았다.

```text
python -X utf8 -B e0_p3_verify.py --output-dir analysis/E0_P3_INTEGRATION_20261109_CHECKED
python -X utf8 -B e0_p3_verify.py --verify --output-dir analysis/E0_P3_INTEGRATION_20261109_CHECKED
python -X utf8 -B -m unittest -q test_e0_p3 test_e0_p2 test_e0_fs3 test_frame_provenance test_probe_timing test_h9_probe_timing test_h9_probe_integration test_capture_six_pilot test_f1_sample_aggregator test_upper13_csv test_capture_protocol
```

### 실측 준비 조건 — 비정식 E0/E1 engineering 비교에 한정

1. PC별 익명 ID(PC01 등), OS/CPU/논리 코어·설치 RAM·Python/패키지 버전·Git commit/dirty·실행 소스 SHA를 `environment_record`로 기록한다. Windows 설치 RAM은 [GetPhysicallyInstalledSystemMemory](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getphysicallyinstalledsystemmemory) 조회값이다. hostname/사용자/serial/UUID는 쓰지 않는다. GPU 모델/사용률/VRAM은 resource 로그에 별도로 남긴다. 전원 모드·드라이버 버전·백그라운드 부하·카메라 설치 조건은 실행 전 운영 기록으로 확인한다.
2. E0/E1은 동일 PC·전원·모델/Scaler hash·7열 순서·10초/H9 support·입력 profile(RGB1280×720, Depth848×480,15FPS)·화면 옵션(추가3D 없음)·요약 모드·자원 주기1초·buffer256을 고정한다. 입력/장치 실제 profile과 승인된 자세/동작 절차도 같아야 한다. OFF/상세는 별도 observer 비용 진단이며 주 비교 모드와 섞지 않는다.
3. 조건당 새 프로세스3회, 회당 stream300초로 한다. 미래 E1 비교 순서는 E0/E1, E1/E0, E0/E1로 사전 고정한다. 모델/SDK 시작 시간은 별도 기록하고 stream 내 초기 프레임·첫 판정은 포함한다. 사후 예열 제외·빠른 구간 선택을 하지 않는다. 카메라 재시작·동일 초기화 조건을 유지한다. `run_bound_probe`의 probe_runner에 `run_probe(duration_seconds=300, ...)`를 전달하는 운영 연결로 이 시간을 지정한다.
4. 핵심 지표는 **SDK 수신→loop 완료 p95**, 처리 frameset/s, 수신 프레임 대비7특징 성공률이다.10초 누적 포함 첫/마지막 입력→판정, 단계 p50/p95/p99, 유효 특징FPS, CPU 두 정규화/시스템CPU, RSS/Private/peak, checkpoint/출력 비용을 함께 보고한다. 새 RGB 고유 FPS·실제 누락률·센서 노출→물리 화면 지연과 혼동하지 않는다. 번호 gap/재사용과 NOT_MEASURED 유지 조건은 그대로다.
5. **정확히 같은 입력**은 SHA/순서가 고정된 저장 특징 재생에서만 현재 확보됐다. 전체 RGB-D→Pose/Face 경로의 동일 프레임 비교에는 별도 승인된 입력 자료가 필요하며, 현재 원본 영상은 저장/열람하지 않았다. 실제 반복 촬영은 동일 조건 비교이지 동일 pixel 입력 비교라고 표현하지 않는다. E1 자료/코드/최적화는 이번에 만들지 않았다.

### 실측 가능 여부와 남은 차단

소프트웨어 통합은 PASS지만 **지금 실측을 시작할 상태로 승인된 것은 아니다**. 두 기존60학습 모델 중 사용할 artifact의 명시적 선택/hash 고정, 연구/engineering 실행·IRB/운영 범위 확인, 실제 Tk/키 포커스·D455 profile·시간축·장시간 저장/여유 디스크·observer 비용 점검이 남아 있다. 실제 MediaPipe backend/GPU 귀속 및 SDK 내부 큐·센서 누락률은 확인 전 NOT_MEASURED다. 최소1GiB 여유 디스크와 신규 출력 디렉토리를 실행 전 확인하고, 로그 저장 오류가 있으면 해당 측정을 실패로 처리한다. 모델·연구자료·기존 결과의 덮어쓰기, Stage·Commit·Push는 하지 않았다.

P3 수정 파일: `e0_fs3.py`, `e0_resources.py`, `probe_diagnostics.py`, `test_e0_fs3.py`(합성 fixture의 probability=False 명시), 이 문서. 신규 파일: `e0_storage.py`, `e0_model.py`, `e0_panel.py`, `e0_p3_verify.py`, `test_e0_p3.py`. 기존 실시간 `posture_geometry_probe.py`의 P1/P2 연결을 재사용했으며 이번 P3에서는 추가 수정하지 않았다.

## 한 명 사전점검 명령

`run_e0_check.py`는 기존 P3 모델 로드·구간 UI·run_probe 연결만 호출하는 실행 래퍼다. 기본은 카메라/GUI를 열지 않는 check-only이며, `--live`를 명시했을 때만 비정식 연결 점검을 시작한다. 검증된 repetition0/fold0의60구간 학습 artifact를 사전점검용으로 사용하며 정식/배포 모델 선정이나 촬영 승인을 뜻하지 않는다. 다른 artifact는 명시적인 `--binding`으로만 지정한다.

```powershell
python -X utf8 -B run_e0_check.py --check-only
python -X utf8 -B run_e0_check.py --live --duration-seconds 90 --mode summary --pc-id PC01
```

실시간 명령은 이미 허용된 비정식 점검·동의 범위에서 사용한다. P01/P02 중 한 명으로 정상 자세를 안정시킨 다음 E0 조작창에서 Start/Enter로10초 유지한다. COMPLETED를 확인한 뒤 한 번은 Enter→2~3초→T/Cancel로 취소를 점검하고, 다시 안정→Enter→10초 완료를 확인한다. 포커스를 잃으면 취소되므로 키 입력은 E0 조작창에서 한다. Q/Close로 종료하거나 stream90초 제한에서 종료한다. 기존 방향키 자세 라벨링·60회 반복·120구간 재수집 명령이 아니다.

MODEL_READY는 모델 해시/설정 확인 결과이며 D455 실측 성공을 의미하지 않는다. COMPLETED는 적격 집계와 SVM 판정 연결 성공이고, INELIGIBLE은 원래30/50 기준 등의 미달이다. 이 점검을 정확도나 E0 본 성능 결과로 사용하지 않는다.

실행마다 `analysis/E0_PREFLIGHT/local_private/check_<새 식별자>/`를 만들고 마지막에 실제 저장 경로를 출력한다. 원본 영상·랜드마크·특징값·참가자 식별자는 저장하지 않으며 숫자 성능/판정 로그만 기록한다. 기존 출력 덮어쓰기·모델 재학습은 없고 최소1GiB 여유 디스크를 확인한다. check-only는 출력 디렉토리도 만들지 않는다.

추가 파일은 `run_e0_check.py`, `test_run_e0_check.py`이며 기존 P3 핵심 코드는 수정하지 않았다. 명령/연결 관련 합성 테스트20개(새 CLI4개+P3 16개)와 실제 artifact의 check-only를 통과했다. 카메라/GUI 실행·Commit·Push는 하지 않았다.

첫 실시간 시도에서 상위 `analysis/E0_PREFLIGHT/local_private`가 없어 exclusive run-directory 생성 전에 실패한 실행 래퍼 오류를 수정했다. `--live`에서만 상위 폴더를 재귀 생성하고 실제 run 폴더는 기존 reserve의 독점 생성에 맡긴다. check-only의 무생성·기존 출력 거부는 유지한다. 첫 실행의 부모 폴더 부재→실제 reserve 경계와 재실행 거부를 검증한 회귀를 추가했다. CLI5개+P3 16개,21개 테스트 통과이며 카메라는 실행하지 않았다.

### 장치 시간 이상 시 구간 취소 후 실행 유지 (2026-11-09)

사용자 재점검에서 `Non-monotonic E0 segment device time` 예외로 전체 실행이 종료됐다. 저장 숫자 로그는 약48.91초 실행, 해당 구간53프레임/약3.54초 후 `timestamp_invalid` 중단 및 RGB/Depth 중복 identity 각1회를 보여준다. 요약 모드에는 개별 입력 timestamp 이력이 없어 예외를 일으킨 frameset 시간이 같은 값인지 역행인지까지 소급 확정하지 않는다. Enter의 종료 명령 처리나 MediaPipe 경고로 인한 예외는 아니다. 실패 실행은 보존하고 완료된 성능 측정으로 취급하지 않는다.

`e0_fs3.py`의 장치 시간 검사는 그대로 엄격하게 유지하되, 숫자 변환 불가·비유한·동일 시간·시간 역행 시 해당 hold 전체를 취소하고 receive loop는 계속한다. 중복 프레임만 빼서 hold를 유효화하거나 timestamp 보정·보간·자동 재시작·이전 판정 재사용을 하지 않는다. `segment_time_failure`(상세 frame), `timestamp_failure`(시작된 segment), `segment_time_failures`(모든 계측 모드의 summary)에 고정 사유만 추가한다. 준비 중 이상은 집계에 들어가지 않는다. UI는 `TIMESTAMP_INVALID`를 표시하며 안정된 입력에서 Start/Enter로 명시적으로 다시 시작해야 한다. 프로세스의 COMPLETED와 개별 구간의 INCOMPLETE/시간 이상 수는 구분해 검토한다.

FS3 수식·모델/Scaler·10초 장치 시간 창·H9 공동 support·30/50 적격 기준·공식8조합·B6·IRB는 변경하지 않았다. 변경 범위는 `e0_fs3.py`, `e0_panel.py`, `test_e0_fs3.py`, `test_e0_p3.py`, 이 문서다. 기존 fatal timestamp 가정의 테스트는 새 구간 취소 동작에 맞게 수정했다. 중복/역행 후 수동 재시작 및 정상10초 판정, 시작 시 비정상 시간 표시, 합성 SDK 경로의3모드 동일성·callback 보존·정상 cleanup을 검증했다. 아래 관련 회귀201개 PASS. 실제 카메라·사람 촬영·학습·E1·Commit·Push는 수행하지 않았다. 창 디자인과 UI 긴 지연 원인은 이번 수정 범위에 포함하지 않았다.

```powershell
python -X utf8 -B -m unittest -q test_e0_p3 test_e0_p2 test_e0_fs3 test_frame_provenance test_probe_timing test_h9_probe_timing test_h9_probe_integration test_capture_six_pilot test_f1_sample_aggregator test_upper13_csv test_capture_protocol test_run_e0_check
```

### E0 자세별5회 안내 모드 (2026-11-09)

사용자 지정 운영 순서는 P0×5→P1×5→P2×5→P3×5→P4×5→P5×5, 인당30개10초 hold다. 기존 파일럿의 `LABELS * repeats` 수집기는 변경하지 않고 `e0_guided_panel.py`가 기존 E0Session/OperatorControl의 수동 시작·취소·10초 완료만 재사용한다. `run_e0_check.py --guided-six --subject P01` 또는 P02로 선택한다. 단순 사전점검 명령의 기본90초 동작은 유지한다.

```powershell
python -X utf8 -B run_e0_check.py --check-only --guided-six --subject P01
python -X utf8 -B run_e0_check.py --live --guided-six --subject P01 --duration-seconds 1800 --mode summary --pc-id PC01
python -X utf8 -B run_e0_check.py --live --guided-six --subject P02 --duration-seconds 1800 --mode summary --pc-id PC01
```

두 실제 실행은 동시에 열지 않고 한 명 종료 후 다음 명령을 실행한다. `1800`은 준비/전환을 포함한30분 안전 상한이며, 정상 완료30개 후 UI가 자동 종료한다. 실제 stream 길이는 사람별로 다르므로 고정300초×3회 E0/E1 반복과 동일한 설계로 취급하지 않는다. 개선 전후 비교 시 이 안내 순서·전환/휴식 조건·UI·계측 모드도 동일하게 유지하고 실제 길이를 보고한다.

Space=P0 정상 복귀 및 목표P0 선택, H=P1, ↓=P2, ←=P3, →=P4, ↑=P5다. 매 hold마다 정상 복귀Space→화면의 목표 자세 키→안정 후Enter로 시작한다. P0에서는Space→Enter면 된다. 진행 중Enter 반복은 무시하며 T/Esc/취소·포커스 이탈은 취소한다. 전체 계측·카메라는 전환 중에도 돌지만 구간 집계에는 준비/전환 프레임을 넣지 않는다. 취소·시간 이상은 자동 재시작/진행하지 않고 같은 회차를 다시 준비한다. 기술 적격성을 만족하지 못해도10초가 완성된 INELIGIBLE은1회로 세고 보존한다. 예측 결과/정답 여부로 재시도·진행을 결정하지 않는다. 최종30회 완료는30회 모두 적격 또는 정확하다는 보장이 아니다.

창은820×540, 한국어 큰 글꼴·현재 목표/회차·진행 시간·명시적 시작/취소/종료 버튼을 사용한다. 참가자 코드는 화면용 메모리 입력에만 쓰며 출력 폴더/파일·environment에 저장하지 않는다. `analysis/E0_GUIDED/local_private/check_<unique>/`에 기존 숫자 성능/판정 로그와 익명 운영 진행 수·guide source hash만 남긴다. 입력 특징값·정답 자세 라벨·영상·랜드마크는 저장하지 않는다. 이 모드는 하드웨어 실행 성능용이며 새 분류 학습/정확도 데이터 수집이나 정식 촬영/IRB 승인을 대신하지 않는다. 참가자와 출력 경로의 대응이 필요하면 별도 로컬 운영 기록으로 관리한다.

추가 파일 `e0_guided_panel.py`, `test_e0_guided_panel.py`; 수정 `run_e0_check.py`, `test_run_e0_check.py`, 이 문서. 모델/Scaler·FS3 수식·집계·H9 support/30·50%·공식8조합·B6·IRB 규칙은 유지한다. 합성30hold 순서·정상복귀·잘못된 키·반복Enter·취소/시간 이상 복구·부적격 보존·예측과 무관한 진행·30회 자동 종료·화면용 참가자 코드 미저장·CLI 연결을 포함한 관련208개 테스트 PASS. 실제 카메라/사람 촬영·새 학습·E1 최적화·Commit·Push는 수행하지 않았다.

### E0/E1 공통 Tk·전체 루프 계측과 단일 E1 UI 후보 (2026-11-09)

사용자가 공통 계측 보완 및 `waitKey(1)`→`pollKey()` 단일 E1 구현·검증을 요청했다. 앞 절의 E1 미구현 상태는 당시 기록이며, 이번에 승인된 범위만 다음과 같이 추가했다. FS3 모델/Scaler·특징 수식·10초 장치 시간 집계·H9 공동 support·30개/50%·공식8조합·B6·IRB/정식Patch8 규칙은 그대로다. 실제 촬영이나 재학습은 하지 않았다.

`run_e0_check.py --variant E0`가 기본 대조군이고 `--variant E1`만 Win32 HighGUI의 `pollKey()`를 사용한다. UI 대기 함수 외 처리/화면/가이드 경로는 같다. E1은 E0Session·화면 표시 경로에만 허용하며, 현재 backend가WIN32이고 pollKey가 호출 가능한지 확인하지 못하면 카메라 시작 전에 거부한다. waitKey로 자동 대체하지 않는다. Q/기존 저위8비트 키 처리·Tk 시작/취소/자세키는 유지한다. headless/기존 RF/H9/공식 실행 경로에 E1을 자동 적용하지 않는다. CLI check-only도 E1 지원을 읽기 전용으로 확인하고 카메라·GUI·출력 폴더는 생성하지 않는다.

양쪽 실행 metadata에 `execution_variant`, `highgui_backend`, `ui_key_function`, `timing_contract=e0-e1-loop-timing/1`을 남긴다. HighGUI backend 확인은 Pose/Face GPU backend 확인과 별개다. E1 가이드 출력은 `analysis/E1_GUIDED/local_private/`, 단순 점검은 `analysis/E1_PREFLIGHT/local_private/`이며 E0 기존 경로를 유지한다. 기존 폴더는 덮어쓰지 않는다.

|계측 이름|정의/표본|
|---|---|
|`ui.tk_idle`|Tk update_idletasks 호출 시간|
|`ui.tk_update`|Tk update 호출 시간|
|`ui.tk_poll`|상태·문구 갱신을 포함한 전체 안내창 poll; 위 두 호출을 포함하므로 합산하지 않음|
|`ui.key_wait`|완료 프레임의 기존 HighGUI 호출 경계; E0=waitKey(1), E1=pollKey|
|`ui.idle_key_wait`|수신 timeout 뒤 HighGUI 처리; 기존 완료 프레임 표본과 분리|
|`latency.loop_start_to_frame_complete`|Tk poll 직전→완료 프레임 endpoint. 기존 프레임 지연과 같은 성공 프레임 집합|
|`loop.total`|Tk poll 직전→다음 루프 시작 또는 마지막 정리 작업 직전. timeout/invalid pair/deadline skip/control-only/예외 루프도 포함|

기존 `latency.receive_to_frame_complete`, `latency.receive_wait_start_to_frame_complete`는 경계와 필드명을 유지한다. 새 표본은 기존 bounded duration/checkpoint 저장을 재사용하며 새로운 무제한 배열이나 가상 큐를 만들지 않는다. 상세 프레임 행에는 loop_index/start/end/total_ns가 추가되고 summary에는 loop_count/status_counts와 경계 설명을 추가한다. 수신 전 종료한 control-only 루프는 프레임 행이 없어도 loop.total에 남는다. 전 루프와 완료 프레임만의 지표는 표본 수가 다르다. 이전 루프 표본 기록 비용은 새 루프에 포함시켜 루프 사이의 관측 공백을 만들지 않는다. SDK/모델 시작·최종 파일 발행/장치 cleanup·센서 노출→물리 화면까지를 전체 루프라고 주장하지 않는다.

저장된 과거 E0에는 Tk/전체 루프 지표가 없고 계측 부하도 달라졌으므로, 새 전체 루프 비교에는 공통 계측이 적용된 새 E0/E1 실행을 사용해야 한다. 기존 결과는 보존하며 새 지표를 소급 채우거나 계측 경계 확장을 개선 효과로 해석하지 않는다. 실제 재촬영은 같은 PC·모델 hash·카메라 profile·화면/순서/계측 모드·유사한 전환/휴식 조건의 비교이지 동일 RGB-D 프레임 입력 비교가 아니다. E0/E1 측정 순서 교대 및 반복 계획은 기존 문서 조건을 따르고, 자세별5회 가이드는 고정300초×3회 설계와 구분한다.

```powershell
python -X utf8 -B run_e0_check.py --check-only --guided-six --subject P01 --variant E0
python -X utf8 -B run_e0_check.py --check-only --guided-six --subject P01 --variant E1
# 승인된 비정식 실측에서 실행할 때 동일 나머지 옵션에 --variant E0 / --variant E1만 지정한다.
```

관련 회귀219개 PASS（기존208+신규11）. 합성 SDK/Tk/시계로 Tk 시간 포함·기존 endpoint 보존·세 모드 기능 동일성·E0/E1 특징/Scaler 입력/판정 동일성·Q 종료·timeout·invalid pair·deadline skip·예외 정리·미지원E1 실행 거부를 검증했다. 실제 artifact의 E0/E1 check-only도 PASS다. 테스트가 주입한 시간 차이는 구조 검증이며 p95/FPS/CPU/RAM의 실제 개선 수치가 아니다. 실측 개선 여부는 NOT_MEASURED다.

이번 수정은 `e0_fs3.py`（공통 loop 계측/summary）, `e0_panel.py`와 `e0_guided_panel.py`（동일 Tk 하위 단계）, `posture_geometry_probe.py`（공통 경계·E1 선택/지원 검사）, `run_e0_check.py`（variant 옵션/분리 출력）, `test_run_e0_check.py`, 신규 `test_e0_e1_ui.py`, 이 문서와 기존 검토 보고서다. 합성 근거는 `analysis/E0_GUIDED_REVIEW_20261109/local_private/e0_e1_common_timing_validation.json`에 보관한다. 원본 영상·특징값·랜드마크·참가자 식별자 저장·실제 카메라·새 학습·Commit·Push는 하지 않았다.
