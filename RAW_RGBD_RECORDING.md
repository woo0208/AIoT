# E0/B1 원본 RGB-D 저장 ON/OFF

2026-11-17. 사용자 요청에 따라 원본 저장 버튼과 시작 옵션을 추가했다.
이 문서는 engineering 저장 기능 설명이며 공식 수집/평가·B6·IRB·Patch 8 HOLD를 변경하지 않는다.
이번에는 실제 카메라·참가자 촬영이나 실제 자료 평가를 실행하지 않는다.

## 사용

기존 실행기에 `--save-raw on` 또는 `--save-raw off`를 추가한다. 기본은 **off**다.
두 경우 모두 조작창에 **원본 저장 ON/OFF** 버튼과 현재 상태·누적 저장 프레임 수·저장 경로가 나타난다.
E0 기본 조작창, 6자세 안내창, 연구 B의 E0/B1에 적용된다. 별도 `capture_six_pilot.py`의 저장 동작은 변경하지 않는다.

```powershell
# 카메라/GUI/출력 폴더 없이 옵션·기존 모델 binding만 점검
python -X utf8 -B run_research_b.py --check-only --variant B1 --save-raw on
python -X utf8 -B run_e0_check.py --check-only --save-raw off

# 향후 허용된 비정식 실행에서 사용할 예시. 이번 작업에서는 실행하지 않음.
python -X utf8 -B run_research_b.py --live --variant E0 --save-raw off
python -X utf8 -B run_research_b.py --live --variant B1 --save-raw on
python -X utf8 -B run_e0_check.py --live --save-raw on
```

- **ON:** 다음 수신 프레임부터 저장한다. 시작 옵션 on도 첫 프레임에서 기록을 시작한다.
- **OFF:** 현재 구간의 인덱스와 종료 정보를 닫는다. 이후 원본 프레임은 저장하지 않는다.
- **다시 ON:** 새 `clip_0002` 등으로 시작하며 이전 파일을 덮어쓰지 않는다.
- ON 후 프레임 수신 없이 OFF가 되면 빈 클립을 만들지 않는다. 계속 OFF면 `raw_rgbd/` 자체를 만들지 않는다.
- 원본 저장과 10초 측정 Start/Cancel은 독립이다. 원본 버튼은 모델·측정 상태를 변경하지 않는다.
  Start/Cancel/Q 및 외부 창으로 포커스 이동 시 구간 취소의 기존 동작은 유지한다.
- B1 유휴 추론 생략이나 검출 실패와 관계없이 ON 중 수신한 원시 프레임을 기록한다.
  이미 수신했지만 실행 시간 상한 때문에 처리하지 않는 마지막 입력도 기록한다.
- 정상 종료·Q·창 닫기에서는 열린 클립을 마무리한다. 저장 실패는 ERROR 표시 후 전체 실행 실패로 전파하고
  SDK/창을 정리한다. 일부 기록을 성공으로 숨기거나 자동 재시도하지 않는다.

OFF였던 구간은 나중에 복원할 수 없다. 전체 입력을 재생하려면 시작부터 종료까지 ON이어야 한다.

## 저장 형식

카메라를 재시작하지 않고 실행 중 전환하기 위해 **손실 없는 프레임별 NPZ**로 저장한다.
`.mp4` 영상이나 SDK `.db3/.bag` 파일은 아니다. 색상/Depth를 배열로 보존하므로 후속 재처리에 사용할 수 있다.
이 새 형식은 `e0-raw-rgbd-npz/1` engineering sidecar이며 기존 frozen scientific schema를 대체하지 않는다.

```text
<실행 출력 폴더>/
  summary.json                  # 기존 성능/판정 메타데이터
  segments.jsonl
  raw_rgbd/
    clip_0001/
      recording.json            # 저장 형식·카메라 보정·기존 모델 binding·코드 hash
      frames.jsonl              # 수신 순번·프레임 파일 hash·센서 시간/번호·측정 요청 상태
      frames/
        00000001.npz
        00000002.npz
      end.json                  # COMPLETED/FAILED·인덱스 hash·프레임 수
    clip_0002/
      ...
```

각 NPZ의 `color_bgr`는 BGR8 uint8 원본이고 `depth_z16`은 native Z16 uint16 원본이다.
Align·색 변환·추론·B1 gate **이전**에 복사하며 resize·양자화·손실 압축은 없다.
기본 profile은 기존 RGB1280×720 / Depth848×480 / 15FPS다.
깊이는 color 정합 전 배열이므로 재처리 시 저장된 intrinsics/extrinsics/depth scale로 정합해야 한다.

센서별 frame number·timestamp·domain, frameset 시간, host 수신 시각을 따로 저장한다.
원래 중복·역행을 수정하지 않는다. 어느 스트림이 없으면 해당 배열을 생략하고 상태를 기록하며
직전 프레임이나 0 영상으로 대체하지 않는다. 현재·미래 자세 정답을 자동 생성하지 않는다.
부모 `segments.jsonl`의 판정 및 측정 경계와 원시 시간/수신 순번을 통해 연결할 수 있다.

`end.json`이 없으면 미완료이며, FAILED 구간은 정상 완료 자료로 취급하지 않는다.
부분 쓰기 실패 시 인덱스에 없는 NPZ가 남을 수 있다. 종료 상태와 인덱스를 함께 확인해야 한다.
`raw_rgbd_recording.load_raw_frame(clip, record)`는 인덱스 경로·SHA-256과 dtype을 확인해 한 프레임을 읽는다.
이는 원본 로더이며 E0/B1 재생 실행기나 자동 정확도 평가기는 아니다.
파일 생성은 exclusive-create이고 기존 구간을 재사용하지 않는다.

## 성능·자료 보존

원본은 무압축이므로 기본 profile에서 초당 약54MB, 분당 약3.2GB(약3.0GiB)다.
이는 배열 크기로 계산한 저장 용량이며 실측 처리 속도나 무누락 보장이 아니다.
256MiB 디스크 여유를 남기는 사전 확인과 실제 쓰기 오류 처리를 적용했다.
동기식 기록이므로 I/O가 느리면 SDK 전달 누락이나 지연에 영향을 줄 수 있다.

기존 전체 루프/수신 후 지연·CPU/RSS에는 원본 기록 비용이 포함되고, `io.raw_rgbd` 단계도 추가 계측한다.
`summary.json`의 `environment.raw_recording`과 연구 B 보고서에 초기 상태·프레임/구간/토글 수·실패 상태를 기록한다.
E0/B1 성능을 비교할 때 원본 저장 상태와 ON 구간을 맞춰야 한다.
기존 숫자 로그만 측정한 결과와 저장 ON 실행을 같은 조건의 결과로 비교하지 않는다.

기본 OFF에서는 원본 배열 복사·캘리브레이션 읽기·원본 폴더 생성이 없다.
화면 버튼과 상태 확인은 추가됐지만 FS3 수식·H9 공동 support·10초 창·30/50 기준·모델/Scaler·평가 규칙은 유지한다.
`raw_rgbd/`는 출력 위치와 무관하게 `.gitignore`로 제외한다. 원본·식별 자료를 commit/push하지 않는다.

## 수정 파일

- `raw_rgbd_recording.py` (신규): 저장 상태·배열/시각/보정 기록·클립 종료·오류·프레임 로더.
- `e0_panel.py`: ON/OFF 버튼·상태·경로 표시 및 실행기 컨트롤 연결.
- `e0_guided_panel.py`: 안내창에도 같은 버튼을 배치하고 창 높이 확보.
- `run_e0_check.py`, `run_research_b.py`: `--save-raw on/off`, 기본 off, check-only 무생성.
- `posture_geometry_probe.py`: raw 수신 직후 저장 hook·I/O 계측·정상/예외 종료 연결.
- `e0_fs3.py`: 원본이 실제 저장된 실행의 summary 설명만 조건부 정정. 분류/평가 계산은 그대로다.
- `research_b_report.py`: 원본 저장 상태·raw I/O 시간을 보고서에 포함.
- `.gitignore`: 모든 `raw_rgbd/` 디렉터리 제외.
- `test_raw_rgbd_recording.py` (신규): 합성 저장·UI·SDK·실행기 검증.
- `E0_INSTRUMENTATION.md`, `RESEARCH_B_B1.md`: 이번 선택적 원본 저장 기능에 대한 후속 안내.
- 이 문서 (신규): 형식·명령·정합성과 실제 검증 결과.

## 검증

합성 배열·SDK·Tk·학습 없이 만든 fitted-state 대역만 사용한다.
ON/OFF/재시작, native 정합 전 배열 일치·시간 보존, 누락 스트림, 클립 충돌, disk/쓰기/종료 실패,
프레임 hash 검사, 버튼과 측정 독립성, E0/B1 동일 저장 입력, 유휴/실패/종료 경계 입력 보존,
측정 집계·Scaler 입력·판정 회귀, CLI check-only/전달을 검증한다.
실제 D455·실제 GUI 조작·저장 처리량·분류 정확도 유지는 이 작업에서 실측하지 않는다.

### 1차 요청 완료 체크포인트

- 신규 24개를 포함한 관련 회귀 **173 PASS**, FAIL/SKIP 0.
- 실제 기존 모델 binding의 E0/B1 및 E0 실행기 ON/OFF check-only 4회 PASS.
  카메라·GUI·원본 폴더 생성 없음.
- `git diff --check`, 신규/수정 Python 9파일 AST 검사 PASS. 원본 디렉터리 Git 제외 확인.
- 기존 E0 로그 842파일은 보관된 SHA-256과 전부 일치.
- 이전 조사에 등장한 workspace의 P01/P03/TECH DB3 3개는 이번 확인 시 파일이 존재하지 않았다.
  해시 변경으로 분류한 최초 보존 검사 결과는 **부재**로 정정한다. 이번 기능/테스트에는 DB3 삭제 연산이 없다.
  workspace 밖 PREFLIGHT 두 복사본과 ENG2 원본의 SHA-256은 이전 기록과 일치했다.
- 실제 장비/GUI 검증, 세션 이벤트 전체·식별 정보, 강한 세션 리더·native DB3 재생 검증은
  1차 버튼 요청의 범위 밖 또는 부분 구현이다. 사용자의 후속 요청에서 순차 보완한다.
- 1차 요청을 처음부터 다시 구현하지 않고 위 코드를 기준으로 후속 작업을 진행한다.
  Commit/Push 없음. 작업 시작 HEAD `85540f8` 유지.

## 후속 요청 보완 — 세션·이벤트·메타데이터·재생

위 1차 체크포인트 이후 누락분만 확장했다. 새 저장 알고리즘이나 B-Fixed/B-Adaptive는 구현하지 않았다.
기존 E0의 수식·모델·집계·측정 창·프로토콜과 연구 A 결과는 유지한다.

### 식별 정보와 자세 안내

두 실행기는 `--participant-id P03 --session-label S1 --repetition 2`를 추가로 받는다.
참가자 코드는 익명 `Pxx/Pxxx`, 세션은 S1/S2, 반복은 양의 정수만 허용한다.
미지정 값은 **UNASSIGNED/null**로 남기며 파일명·예측·안내 순서에서 추정하지 않는다.
6자세 안내 모드는 기존 `--subject`와 참가자 코드를 일치시키고, 반복은 기존 1..5 진행을 기록한다.
안내 모드에 수동 `--repetition`을 혼합할 수 없다. 일반 조작창에는 P0~P5 안내 버튼을 추가했다.
이 버튼은 지시만 기록하며 측정을 시작하거나 실제 자세를 확정하지 않는다.

```powershell
python -X utf8 -B run_research_b.py --check-only --variant B1 --save-raw on --participant-id P03 --session-label S1 --repetition 2
python -X utf8 -B run_e0_check.py --check-only --guided-six --subject P01 --session-label S2 --save-raw off
```

### 세션 파일과 이벤트

원본 OFF여도 별도 **`<실행폴더>/recording_metadata/`**에 세션 이벤트를 보존한다.
`raw_rgbd/`에는 여전히 ON 구간의 원본만 생성된다. 두 디렉터리는 모두 Git 제외다.

- `events.jsonl`: SESSION_START/END, RECORDING_START/STOP, IDLE_START/END,
  MEASUREMENT_START/END, POSTURE_INSTRUCTION, POSTURE_HOLD_START/END, RECORDING_ERROR.
- `session_manifest.json`: 세션 UUID·입력 참가자/S1·S2·반복 정보, 종료 상태, 설정/코드 버전,
  파일 SHA-256 목록, 저장/누락 프레임 수, 오류와 진단. 원본 NPZ는 인덱스의 개별 SHA-256으로 연결된다.
- `annotations_template.json`: 안내별 전환 ID와 실제 움직임 시작/목표 도달 **UNANNOTATED** 슬롯.

각 이벤트는 host perf-counter 시각과 직전 SDK 수신 프레임의 센서 시간·번호를 연결한다.
프레임은 같은 세션 ID·수신 순번·직전 이벤트 순번을 보존한다. 독립 clock domain을 같은 시각으로
간주하거나 이벤트 anchor를 실제 인체 움직임 시각으로 승격하지 않는다.
버튼을 빠르게 Start→Cancel 해도 두 측정 이벤트를 기록하되 입력이 없으면 HOLD_START를 만들지 않는다.
hold 시작은 기존 E0 측정 창 시작이며, 실제 목표 자세 도달 시각과 구분한다.

ON/OFF는 측정 이벤트와 독립이다. 사용자 Q/창 닫기 종료는 클립/세션 **INTERRUPTED**,
실행 시간 상한 등 정상 종료는 COMPLETED, 저장/실행 오류는 FAILED로 구분한다.
이미 OFF로 정상 닫은 클립은 이후 종료 때문에 다시 수정하지 않는다.
중복·누락 번호·시간 역행은 진단으로만 기록하며, 프레임 제거·시간 수정·적격 기준 변경은 없다.
OFF 구간을 건너뛴 번호 차이는 센서 누락으로 계산하지 않도록 클립 경계에서 진단을 분리한다.

카메라 기록은 native geometry 외에 장치 모델/serial/product ID/USB/펌웨어,
녹화 시점 SDK 버전, RGB/Depth profile, Align 설정, 노출/gain/자동 노출 및 주요 Depth 옵션을 포함한다.
설정은 조회만 하며 변경하지 않는다. 지원되지 않는 값은 `NOT_MEASURED`다.
옵션 값은 클립 시작 시점 snapshot이며 자동 노출의 모든 프레임 값을 수집했다는 뜻은 아니다.
장치 식별 정보는 private 원본 sidecar에만 남는다. 기존 숫자 성능 로그에 참가자/serial을 복사하지 않는다.
구형 DB3에서 읽은 SDK 버전은 **현재 재생 런타임**으로 표시하고 원본 작성 SDK를 추정하지 않는다.

### 읽기 전용 재생·무결성 확인

`raw_rgbd_replay.py`가 새 세션/클립 및 기존 DB3/BAG를 읽는다.
새 형식은 기존 `research_recording.RecordingReader`의 경로·순번·SHA·종료 상태·미인덱스 파일 검증 패턴과
엄격 JSON reader를 재사용했다. DB3는 기존 `capture_d455.count_frames`/`analyze_d455`와 같은
`enable_device_from_file(..., repeat_playback=False)` + `set_real_time(False)` 경로다.
장치를 검색하거나 물리 카메라로 fallback하지 않는다.

```powershell
# 새 기능으로 수집한 세션 폴더를 지정한다. 과거 숫자 로그 폴더에는 raw manifest가 없다.
python -X utf8 -B raw_rgbd_replay.py --input analysis/RESEARCH_B/local_private/new_b1_raw --allow-incomplete --output analysis/new_raw_replay_report.json
# 기존 DB3도 카메라 없이 파일만 읽는다.
python -X utf8 -B raw_rgbd_replay.py --input "<기존 DB3 파일>" --output analysis/new_db3_replay_report.json
```

보고서는 실제 읽은 프레임/쌍/누락 수, 원시 clock·번호·domain, profile/보정, 소스 SHA-256,
원본 수정 여부와 입력의 COMPLETED/INTERRUPTED/FAILED/UNFINALIZED 상태를 구분한다.
프레임 순서·profile 크기·pair 관계·이벤트 참조·파일 수·hash 불일치 또는 인덱스 밖 파일은 거부한다.
`--allow-incomplete`는 중단 입력 허용일 뿐 손상/미인덱스 파일의 자동 복구가 아니다.
보고서를 원본 내부나 기존 파일 위에 쓸 수 없다. 복사 후에도 상대 경로와 동일 SHA/세션 ID로 판별한다.
캡처 manifest의 재생 가능 수는 기록 시점에 **NOT_CHECKED_AT_CAPTURE/null**이며,
검증 보고서에서 실제 디코딩 수를 별도로 산출한다. 기록 수를 재생 성공 수로 가정하지 않는다.

### 향후 움직임 주석 연결

```powershell
python -X utf8 -B raw_rgbd_replay.py --input analysis/RESEARCH_B/local_private/new_b1_raw --allow-incomplete --make-annotation-copy analysis/new_motion_annotations.json
python -X utf8 -B raw_rgbd_replay.py --input analysis/RESEARCH_B/local_private/new_b1_raw --validate-annotations analysis/new_motion_annotations.json
```

원본 template은 수정하지 않고 새 파일에서 검토한다. 수동 검토 경계에는 원래 클립 경로·프레임 순번·SHA,
color/depth stream과 원래 timestamp/domain/frame number를 지정해야 한다.
실제 움직임 시작과 도달은 서로 다른 프레임 참조이며, 미확인 값은 계속 UNANNOTATED다.
검증기는 참조·순서를 확인할 뿐 주석의 실제 정확성을 자동 인증하지 않는다.
시간 해상도는 검토한 원본 프레임 경계이며 sub-frame 정확도를 주장하지 않는다.
중단 세션 주석 검토에서도 `--allow-incomplete`가 필요하다. 영상 주석 GUI는 구현하지 않았다.

### 후속 변경 파일과 실제 검증

추가 파일은 `raw_rgbd_events.py` (세션·이벤트·주석 연결), `raw_rgbd_replay.py` (강한 reader/CLI),
`test_raw_rgbd_followup.py` (추가 합성 테스트)다.
1차 파일 중 저장기·UI·실행기·SDK hook·Git 제외·테스트·이 문서를 필요한 범위만 확장했다.
자세 이름/순서는 연구 A의 `capture_six_pilot.LABELS`를 import하여 재사용하고 그 수식/결과는 변경하지 않았다.

최종 검증과 남은 범위는 `analysis/RESEARCH_B_RAW_FOLLOWUP_20261117_8e773c75/REPORT.md`에 기록한다.
E0 Replay의 실제 추론 루프 파일 입력 adapter, 실제 새 NPZ 카메라 촬영, 실제 GUI 조작,
실제 저장 처리량·지연·정확도·전환 감지 지연은 아직 완료 또는 PASS로 주장하지 않는다.
