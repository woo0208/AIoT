# Stage 5-E — 묶음 A (5-E-5~5-E-9)

2026-11-05. **합성 구조 검증 기준 A-1~A-4 PASS. 실제 D455·연구 모델 성능은 미측정.**

시작/종료 HEAD: `35e7a467cefc1219f57834fbe6c7e8c8ea37e82f`, branch `feat/aiot-stage5e-d455-readiness`.
시작부터 `posture_geometry_probe.py`, `probe_timing.py`가 modified였고,
`performance_output.py`, `test_performance_output.py`, `STAGE_5E4_PERFORMANCE.md`가 untracked였다.
기존 5-E-4 변경을 보존했다. 지정 문서의 관련 규칙을 확인했으며 동결 규칙·특징식·8조합·선정 우선순위·seed·LOSO를 변경하지 않았다.

| 범위 | 상태 | 구현/검증 |
|---|---|---|
| A-1 | PASS | 모델 독립 prediction adapter, P0 정상/P1 거북목/P2 상체 후방/P3 좌측/P4 우측/P5 상체 전방. NEW/HOLDING/STALE/INSUFFICIENT_DATA/MODEL_UNAVAILABLE, ID/이름/나이 표시. 기존 H9 async snapshot envelope와 상태 의미 재사용. opt-in 독립 Tk 패널은 한글 표시를 지원하고 카메라 없이 SYNTHETIC DEMO만 재생 |
| A-2 | PASS | timing-only와 Performance의 FPS·stage p50/p95·CPU/RSS/Private RAM 비교. 동일 단위의 부호 있는 B−A와 `(B−A)/A*100`. 0 기준 상대 변화는 null. JSON SHA-bound 실행 조건 누락/불일치 또는 필수 관측 부족은 BLOCKED |
| A-3 | PASS | train()/predict(model,input) 콜백으로 기존 모델 인터페이스 연결 가능. 학습초·추론ms p50/p95·모델 파일 bytes·학습/추론 전후 process RSS/private 관측. 모델/특징순서/seed/환경/입력/hash/호출·warmup 조건과 조건 hash 기록 |
| A-4 | PASS | 기존 formal6 결과의 baseline_comparison 8조합만 투영. Accuracy/Macro-F1/클래스 P/R/F1/support·혼동행렬·예측·seed/참가자/세션 근거 보존. rule 문서 hash·전체 공통 입력 hash·첫 P0 제외·10초 창·개발2 LOSO fold 검증. 후보 선정 실행 없음 |

## 파일별 변경

| 파일 | 이번 변경 |
|---|---|
| `posture_geometry_probe.py` | `--six-class-synthetic-demo` 옵션과 main의 조기 분기만 추가. 기본 probe/run_probe/H9/F1 경로에 새 처리를 넣지 않음 |
| `prediction_adapter.py` (신규) | 공통 event→표시 adapter, 한글6 자세, 합성 이벤트와 독립 패널. producer class_order 강제; 3/5→6 변환 없음 |
| `engineering_exports.py` (신규) | 새 디렉터리 예약, 입력/출력 중첩 차단, exclusive CSV, 기존 공통 컬럼 투영, 합성/engineering scope 검증 |
| `engineering_ab.py` (신규) | read-only A/B 비교 CLI, 원본 byte 복사·hash·조건 검증, 별도 JSON/CSV |
| `model_benchmark.py` (신규) | 모델 독립 opt-in 측정 API, 기존 model_benchmarks.csv와 별도 상세 CSV/JSON |
| `evaluation_csv_adapter.py` (신규) | 기존 formal6 결과 변환 CLI, 기존 experiment_comparisons.csv와 별도 class_metrics.csv/evaluation_details.json |
| `test_prediction_adapter.py` (신규) | 8개: 6자세/25개 상태 간 조합/age/기존3·5클래스/기존 H9 snapshot·호출수 불변/카메라 우회 |
| `test_engineering_ab.py` (신규) | 6개: 차이·단위·조건 부족/불일치·미측정·0기준·hash/덮어쓰기·합성 격리 |
| `test_model_benchmark.py` (신규) | 6개: p50/p95·학습초·크기·메모리·미실행·오류·경로·합성 격리 |
| `test_evaluation_csv_adapter.py` (신규) | 6개: 8조합·지표 대조·N/A/INCOMPLETE/NOT_MEASURED·seed/참조/LOSO·보조모델 차단·CSV/원본 보존 |
| `verify_stage5e_bundle_a.py` (신규) | 합성 산출물과 관련 통합 검증 재현. `--artifacts-only`는 테스트를 실행하지 않음 |
| `STAGE_5E_BUNDLE_A.md` (신규) | 본 결과/사용법/한계 |
| `analysis/SYNTHETIC_ONLY_STAGE_5E_BUNDLE_A_20261105/` (신규, gitignore 적용) | 합성 원본·투영·검증 기록. 기존 evidence 덮어쓰기 없음 |

`probe_timing.py`, `performance_output.py`, `test_performance_output.py`, `STAGE_5E4_PERFORMANCE.md`는 이번 작업에서 편집하지 않았다.
기존 5-E-4의 CSV 필드/순서·빈 숫자 cell·JSON null·원본 timing 의미를 유지했다.
벤치마크의 기존 CSV 행은 **추론 분포**다. 학습시간/파일크기/메모리는 `model_benchmark_details.csv`와 `benchmark.json`에 연결하며 p50에 다른 종류의 값을 넣지 않는다.

## 실제 검증 결과

- 기능 구현 중 단위 실행: **49 test case 실행**(반복 포함). 중간 두 실행에서 보조 CSV maximum 컬럼 누락 오류3개, 평가 합성 identity의 run_status 누락 오류6개(subtest 포함)가 있었고 수정 후 해당 범위를 통과했다.
- 기능 구현 후 통합 **142 tests: PASS 141 / ERROR 1 / FAIL 0 / SKIP 0**. 새 회귀 fixture의 frame index=0이 기존 positive-index 계약을 위반했다. 최초 로그/verification은 그대로 보존했다.
- 수정 후 관련 범위만 재검증: prediction **8 PASS**, benchmark+evaluation **12 PASS**, A/B **6 PASS**; FAIL/ERROR/SKIP 모두0. benchmark의 기존 run_status identity 수용·측정조건 hash, 참조 P0 소유자 확인, A/B 필수 조건 항목도 해당 범위에서 확인했다.
- **현재 142개 고유 검증은 모두 통과 근거가 있으며 미해결 실패0. 실제 실행 횟수는 반복을 포함해217 test case, 오류 기록10개(subtest 포함), FAIL 0, SKIP 0. 전체 통합 suite를 다시 실행하지 않았다.** 최초 통합 실행 자체를 전부 PASS라고 기재하지 않는다.
- 통합 대상은 verifier의 MODULES 14개와 formal6의 학습 없는 gate/metric/bridge 7개 테스트다. 실제 평가기·RF fit 호출이 필요한 별도 full synthetic pipeline 및 저장소 전체 suite는 실행하지 않았다.
- 기존 timing/H9 feature 집계·예측·호출수·3/5-class 표시·CSV 필드/값 회귀 통과. performance JSON과 CSV4개의 재생성본이 원본과 byte 일치. 보호 source/schema/rule의 통합 전후 hash 일치.
- `git diff --check` PASS. Git 사용자 ignore 및 `.pytest_cache` 읽기 권한 warning은 기존 상태이며 수정하지 않았다.

근거: `analysis/SYNTHETIC_ONLY_STAGE_5E_BUNDLE_A_20261105/`의 `integrated_tests.log`, 최초 `verification.json`, `followup_results.json`, `final_verification.json`.
최종 코드로 새로 생성한 산출물은 그 아래 **`final_synthetic_outputs/`**에 있다. `artifacts.json.tests_run=0`은 이 산출물 재생성이 테스트 재실행을 뜻하지 않음을 명시한다.

주요 산출물:

- `prediction_demo.json`: SYNTHETIC DEMO 26개 상태 이벤트의 표시 결과.
- `ab_comparable/`: 원본 JSON3개 + A/B JSON/CSV. `ab_blocked/`는 조건 부족을 BLOCKED로 보존.
- `benchmark/`: `benchmark.json`, `model_benchmarks.csv`, `model_benchmark_details.csv`; 합성 train=2초, infer p50=20ms/p95=38ms는 가상 clock 시험값이다.
- `evaluation_complete/`, `evaluation_incomplete/`: 원본 결과/metadata 복사, CSV, per-class CSV, 전체 상세 JSON. 합성 Accuracy=5/6, P1 Recall=0, Macro-F1=(2/3+4)/6 대조. 실제 연구 점수 아님.
- `legacy_performance/`, `legacy_regenerated/`: 기존 performance 출력의 합성 생성/byte 일치 증거.

## 사용과 남은 범위

```powershell
$py = 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe'
& $py -X utf8 -B posture_geometry_probe.py --six-class-synthetic-demo
& $py -X utf8 -B verify_stage5e_bundle_a.py 'analysis/<존재하지 않는 새 합성 검증 폴더>'
& $py -X utf8 -B engineering_ab.py TIMING.json PERFORMANCE.json CONDITIONS.json NEW_DIR
& $py -X utf8 -B evaluation_csv_adapter.py EVALUATION.json METADATA.json NEW_DIR
```

A/B CONDITIONS의 `timing_only`/`performance` 각 항목은 `json_sha256`와 동일한 `conditions`를 갖는다.
conditions에는 device(name/serial/firmware/USB/RGB/depth profile), input(id/sha256), config, environment, models,
source_sha256, measurement(warmup_frames/h9_warmup_calls/requested_duration_seconds/resource_sampler/stage_clock)가 필요하다.
원본의 실제 관측 환경/Performance identity와도 대조한다. timing-only에 없는 장치·입력·설정 근거는 **운영자가 실행 당시 기록한 sidecar**로 제공해야 한다.
sidecar는 운영자 기록이지 독립 장치 인증은 아니다. 두 원본만으로 조건을 추정하지 않으며 기존 미기록 실행은 BLOCKED다.

평가 METADATA는 identity(기존 공통 컬럼의 실행 식별자), result_sha256, dataset_sha256,
evaluation_rule_id/hash, 참가자별 reference_keys, sample_key별 windows를 요구한다.
최종 합성 산출물의 `*.metadata.synthetic.json`이 형식 예시다. 이 adapter가 원본 평가 규칙/결과를 재정의하지 않는다.
N/A는 class_metrics의 metric_status로 표시하고 Recall/F1 숫자 cell은 빈칸, JSON은 null이다.
공식 Macro-F1 미산출은 INCOMPLETE, 실행하지 않은 조합은 NOT_MEASURED다. zero_division 진단점수는 원본 상세에만 보존한다.

최종 6-class 모델은 없으므로 실제6 판정 연결은 **MODEL_UNAVAILABLE/미구현**이다. 합성 데모가 그 모델을 대신하지 않는다.
Tk 실제 창의 육안 검수와 D455 실시간 화면 검증은 NOT_RUN; 자동 검증은 표시 문자열/상태 및 opt-in 분기 범위다.
실제 모델 학습/추론 벤치마크·메모리와 D455 오버헤드·정확도는 **NOT_MEASURED**다.
메모리 before/after는 관측 process memory이며 operation peak/할당량, GPU/external process 메모리는 측정하지 않는다.
미실행 train/predict는 NOT_MEASURED이며 단순 A/B 차이에 유의성·개선 주장을 붙이지 않는다.
합성 scope를 FORMAL 또는 일반 engineering으로 재표시하는 경로는 거부한다. 보조 모델은 8조합에 편입하지 않았다.

## 다음 D455 엔지니어링 실측 명령 (이번에는 실행하지 않음)

별도 실행 조건·동일 입력/장치/설정 근거를 마련한 후 사용할 템플릿이다. 두 번의 live 촬영이 같은 입력이라는 사실을 명령만으로 증명하지 않는다.
정식 Patch8 실행 승인·IRB/운영 release를 대체하지 않는다. 실제6 모델 명령은 제공할 수 없으며 아래 H9는 기존 **5-class 개발 artifact**다.

```powershell
$py = 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe'
$h9 = '<기존 5-class H9 M0 artifact의 명시 경로>'
$runRoot = 'analysis/<존재하지 않는 새 engineering 폴더>'
New-Item -ItemType Directory -Path $runRoot
& $py -X utf8 -B posture_geometry_probe.py --h9-model $h9 --views none --duration-seconds 90 --timing-warmup-frames 150 --timing-h9-warmup-calls 5 --timing-output "$runRoot/timing_only.json"
& $py -X utf8 -B posture_geometry_probe.py --h9-model $h9 --views none --duration-seconds 90 --timing-warmup-frames 150 --timing-h9-warmup-calls 5 --performance-data-id '<고정 입력 식별자>' --performance-output-dir "$runRoot/performance"
# 실행 당시 두 run의 조건을 원본 SHA와 결합한 conditions.json이 있어야 비교 가능
& $py -X utf8 -B engineering_ab.py "$runRoot/timing_only.json" "$runRoot/performance/performance.json" "$runRoot/conditions.json" "$runRoot/comparison"
```

실제 D455, 정식/파일럿/외부4명 데이터 접근, 연구 모델 재학습·정식 평가·최종 모델 선정/동결,
기존 데이터/모델/JSON/CSV 덮어쓰기, execution registry/ID 생성, CAP-007·IRB HOLD/DEFERRED 해제는 수행하지 않았다.
**commit/push 없음.** 최종 status 원문은 evidence의 `git_status.txt`에 보존한다.
