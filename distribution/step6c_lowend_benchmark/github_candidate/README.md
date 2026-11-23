# 연구 B STEP 6C Windows 오프라인 벤치마크

이 패키지는 연구 B STEP 5E의 승인된 개발용 Clip 2를 동일한 입력으로 반복 실행한다. 비교 정책은 E0 + Face, 동일 유휴 Fixed 2 + Face, Uniform-85 + Face, Adaptive-V2-85 + Face다. Face VIDEO 입력을 전체 클립에서 유지한다. E0는 유휴에도 전량 정밀 분석한다. 나머지 세 정책은 동일한 유휴 처리 규칙을 사용한다. 승인 라벨은 추론이 끝난 뒤 별도로 읽어 채점한다.

실행 전 연구 책임자에게 대상 PC, 담당자, 보관 기간 및 원본·주석·모델의 별도 전달 범위를 확인한다. 자료의 서명 또는 SHA-256 매니페스트를 신뢰할 수 있는 경로에서 받는다. 데이터와 결과의 위치는 [입력 배치 안내](data/README_DATA.md)에 따른다.

## 1. Python과 입력 준비

Windows x64용 CPython **3.12.10**에서 아래 명령을 실행한다. 실행할 코드를 별도 작업 폴더에 풀고 그 폴더를 현재 위치로 사용한다. `$private`를 승인된 실제 로컬 경로로 바꾼다. CPython 3.12가 여러 개라면 정확한 `python.exe` 절대 경로로 첫 명령을 실행한다.

```powershell
py -3.12 -m venv .venv
$py = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $py -c "import struct, sys; assert sys.version_info[:3] == (3,12,10) and struct.calcsize('P') == 8; print(sys.version)"
& $py -m pip install --only-binary=:all: --no-deps -r .\requirements.txt

$private = 'D:\approved-research\step6c'
$clip = Join-Path $private 'clip_0002'
$inputs = Join-Path $private 'inputs'
$artifact = Join-Path $private 'model\model.pkl'
$manifest = Join-Path $private 'DATA_TRANSFER_MANIFEST.csv'
$tasks = Join-Path $private 'tasks'
$hardware = Join-Path $private 'hardware_PC02.json'
$runs = Join-Path $private 'runs_PC02_take01'
$scores = Join-Path $private 'scores_PC02_take01'
New-Item -ItemType Junction -Path .\src\models -Target $tasks | Out-Null
& $py -E -s -B -X utf8 .\scripts\record_hardware.py --output $hardware
powercfg /getactivescheme
```

MediaPipe의 메타데이터는 `opencv-contrib-python`을 선언하지만 STEP 5E 런타임의 `cv2` 공급자는 `opencv-python`이었다. 따라서 명시한 전체 버전 목록을 `--no-deps`로 설치한다. 두 OpenCV wheel이 같은 `cv2`를 제공하므로 패키지 사전 검사가 중복 설치를 차단한다. 이 설치 조건에서는 `pip check`가 MediaPipe의 선언 한 건을 보고할 수 있다. 실행 전 사전 검사와 샘플 출력을 함께 검증한다. 의존성 버전·OpenCV 배포본을 바꿨다면 동등 조건 비교를 보류하고 차이를 기록한다.

Windows CIM을 사용할 수 없으면 작업 관리자 **성능 → CPU**에서 모델명과 물리 코어 수를 확인한다. `record_hardware.py`에 확인한 `--cpu-model`과 `--physical-cores`를 함께 전달한다.

## 2. 해시, 승인 창 및 Replay

각 명령의 종료 코드를 확인한다. 대상 PC의 전원 모드와 부하를 기록하고 가능한 한 두 PC에서 동일하게 유지한다. STEP 5E와 같이 기본 스레드 설정을 사용한다.

```powershell
Remove-Item Env:OMP_NUM_THREADS,Env:OPENBLAS_NUM_THREADS,Env:MKL_NUM_THREADS,Env:NUMEXPR_NUM_THREADS -ErrorAction SilentlyContinue
$sourceArgs = @('--manifest', $manifest, '--clip', $clip, '--inputs', $inputs, '--artifact', $artifact)
& $py -E -s -B -X utf8 .\scripts\benchmark.py inspect @sourceArgs
if ($LASTEXITCODE -ne 0) { throw 'Inspect failed. Check the approved inputs and installed packages.' }
& $py -E -s -B -X utf8 .\scripts\benchmark.py run @sourceArgs --hardware $hardware --pc-id PC02 --output $runs --repeats 3
if ($LASTEXITCODE -ne 0) { throw 'Replay failed. Keep the private raw logs.' }
$ref = Join-Path $inputs 'reference_predictions.csv'
$compare = @()
if (Test-Path -LiteralPath $ref) { $compare = @('--baseline', $ref) }
& $py -E -s -B -X utf8 .\scripts\score_replay.py --clip $clip --inputs $inputs --runs $runs --output $scores @compare
if ($LASTEXITCODE -ne 0) { throw 'Post-Replay scorer failed.' }
```

`inspect`가 코드·원본·모델 SHA-256, RGB/Depth와 보정 입력, 2,078개 페어 및 승인된 여섯 창을 검사한다. `run`은 기존 실행기의 E0 1회 워밍업 후 네 정책을 고정 시드 순서로 3회씩 직렬 실행한다. `run`과 `score_replay.py`에는 매번 새 출력 경로를 사용한다. 이미 승인된 개발 PC에서 코드 분리만 확인하는 경우에 한해 `--repeats 1 --engineering-smoke`를 쓴다. 본 저사양 실험에서는 정책당 3회 이상 반복한다.

`$runs`에는 `plan.json`, `result.json`, 워밍업 및 반복별 Replay/계측 로그가 남는다. `$scores`에는 `window_predictions.csv`, `cost_by_repeat.csv`, Accuracy·Macro-F1·Recall·혼동행렬·비용 중앙값·RSS를 담은 `development_metrics.json`이 생긴다. `plan.json`과 `result.json`에서 Windows 빌드, CPU·스레드, RAM, SDK 버전, 실제 실행 순서와 FPS/pacing을 확인한다. 참조 예측을 받았다면 숫자 클래스와 H9 동일 여부를 함께 확인한다. 비용은 개발 PC의 같은 모드 개별값 및 정책별 중앙값에 대조한다.

process CPU와 wall은 스트림 경계에서 측정한다. p50/p95는 파일 읽기부터 입력 처리 완료까지며, RSS는 프레임 단위 프로세스 샘플이다. 기본 MediaPipe CPU 경로의 런타임을 확인하고 NVIDIA 계측이 사용 가능하면 보조 기록으로 남긴다. 장치 노출 시각이나 화면 표시까지의 지연에는 별도 측정이 필요하다. 반복 횟수는 시간 측정 표본 수다. 자세 평가 표본은 여섯 창이다.
