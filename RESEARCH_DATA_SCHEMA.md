# Research Data Schema — recording / provenance / analysis

- 명세 버전: `research-data-schema/1.0.0`
- 작성일: 2026-09-30
- 상태: **Step 1 설계 명세. 아래 신규 schema와 경로는 아직 구현되지 않았다.**
- 적용 지침: [AGENTS.md](AGENTS.md). 연구 결과는 목표값이 아니라 증거로 취급한다.
- 이번 산출물은 이 문서뿐이다. 소스·테스트·기존 데이터의 변경, 파일 이동, 모델 다운로드, 성능 실험은 하지 않는다.

## 0. 현재 구현과 변경 금지 경계

현재 구현을 확인한 근거:

| 코드 | 현재 책임과 본 설계의 경계 |
|---|---|
| `capture_d455.py:make_config/record_phase` | color 1280×720 BGR8, depth 848×480 Z16, 각각 15 FPS. raw와 camera/markers/samples 기록 |
| `capture_d455.py:median_face_distance/quality_check/report` | face-only 전방 판정과 기존 일반 거리·품질 통계. 신규 evidence는 이 계산의 관찰값 |
| `analyze_d455.py:ensure_models/process_recording` | 모델 확보, raw+markers에서 최대 31개 frame 필드 추출 |
| `analyze_d455.py:summarize/load_frames_csv` | 현재 `(subject, round, step)` grouping과 CSV 재요약 |
| `rf_experiment.py:load_ours/transform/main` | frames CSV에서 단계별 입력 구성, 첫 upright 기준, feature 변환·평가 마스크 |
| `rf_experiment.py:Tree/Forest/rank_weights/fit_models` | 검증된 모델 핵심. provenance 구현 대상이 아님 |

현재 raw 파일명에는 촬영 timestamp가 있지만 frame row와 RF meta에는 촬영본 식별자가 없다. 같은 subject/round의 복수 촬영본이 분석 summary에서 합쳐질 수 있다. 모델 URL은 `latest`를 사용하며 모델 hash를 기록하지 않는다. 고정 이름의 summary/RF 출력은 재실행 시 덮어쓸 수 있다.

이 명세는 데이터의 식별·연결·관찰 기록을 정한다. 다음은 그대로 유지한다.

- Tree 분할, Forest RNG/Bootstrap pairing, M0/M1/M2 정의, rank weight, λ.
- all/invariant/relative 값, 좌표 환산, 기존 결측 제외 조건, LOSO 및 평가 정의.
- reference를 training/calibration에 유지하고 non-reference 평가만 추가하는 정책.
- body_forward의 정식 5-class 평가 제외와 보조 분석.
- 8~12 cm face-only hard gate, 일반 body fallback, 기존 촬영 sequence·label·FPS·시간.
- 어깨 이동·얼굴/어깨 비율을 새로운 촬영 acceptance criterion으로 삼지 않는다.

**현재 RF는 `summary_steps.csv`가 아니라 `*_frames.csv`를 직접 읽는다.** lineage를 위해 RF 입력을 summary로 바꾸지 않는다. raw→frames→summary와 raw→frames→RF의 두 경로를 모두 추적한다.

## A. recording_id

### A.1 신규 촬영의 규칙

한 번의 촬영 시도마다 아래 ID를 발급한다.

```text
<subject>_r<round>_<YYYYMMDD>_<HHMMSS>_<ffffff>_<uuid4_hex32>
```

구문 예시이며 실제 촬영 자료가 아니다:

```text
P03_r1_20261001_143025_123456_c7b4802066714dbdaf621f54d1dd0a6e
```

- subject: 익명화된 참가자 ID. 신규 ID는 영문·숫자·하이픈만 허용하고 `_`는 구분자로 예약한다.
- round: 양의 정수 의미를 가진 십진 문자열. 예: `"1"`. 기존 round 의미를 바꾸지 않는다.
- timestamp: 신규 수집에서는 `Asia/Seoul` 기준 촬영 시도 시작 시각, 마이크로초까지 사용한다. ISO 시각·offset은 metadata가 권위 있는 값이다.
- UUID: timestamp 중복, 동시 촬영, 시계 역행에 대비한 구별자다. 학습 RNG나 실험 seed를 소비해 만들지 않는다.
- ID는 촬영 시도 시작 전에 한 번 발급하고 변경하지 않는다. 촬영 중단·실패에도 소모된 ID를 재사용하지 않는다.
- registry와 대상 경로에서 유일성을 확인하고 배타적으로 생성한다. 충돌 시 새 ID를 발급하며 기존 파일을 덮어쓰지 않는다. UUID 자체만으로 충돌 방지를 보장한다고 간주하지 않는다.
- 같은 시도의 `.db3`→`.bag` 저장 형식 fallback은 같은 ID를 사용한다. 새 촬영/재촬영은 반드시 새 ID를 사용한다.

### A.2 전파와 불변성

| 단계 | ID 전달 방식 |
|---|---|
| raw | 파일 stem과 촬영 디렉터리 이름. raw 내부에 임의 필드를 삽입하지 않음 |
| capture metadata | 최상위 `recording_id` |
| markers/samples | 기존 열을 유지하고 각 row에 `recording_id` 추가 |
| quality | 최상위 ID와 evidence의 reference ID |
| frames/summary | 고정 schema의 필수 열 |
| RF meta/result | 입력 sample lineage와 결과의 dataset manifest 참조 |

파일명은 편의 수단이다. canonical 처리에서는 metadata/manifest의 ID를 읽고 파일명과의 불일치를 검출한다. 같은 ID에 다른 raw 내용이 연결되면 덮어쓰기 대신 오류로 처리한다. raw가 byte-identical하게 복사된 경우는 새 촬영이 아니라 기존 ID의 위치 alias로 등록한다.

## B. dataset_role

`dataset_role`은 `pilot | formal | external` 중 하나다.

| 값 | 의미 |
|---|---|
| `pilot` | 프로토콜 개발·점검용 자료. 기존 P01/P02는 이 값으로 유지 |
| `formal` | 사전에 정한 정식 수집 프로토콜로 수행한 촬영 시도 |
| `external` | 향후 다른 수집 조건에서 들여온 평가용 자료 |

- role은 촬영/등록 시 지정한다. 높은 성능이나 좋은 품질을 이유로 pilot을 formal로 승격하지 않는다.
- 새 face-only v2 촬영은 `formal`로 등록할 수 있다. 하지만 formal role 자체가 품질 통과나 분석 포함을 의미하지 않는다. 실패한 formal 시도도 그대로 등록한다.
- 참가자 이름만으로 미래 recording의 role을 자동 결정하지 않는다. 기존 P01/P02 촬영본의 pilot 지정은 촬영본별 registry에 남긴다.
- role과 실험 track은 별개다. formal 수집분을 기존 `[C] external()` 평가에 넣더라도 role을 external로 바꾸지 않는다.
- 수입 external 영상에 depth나 RealSense 정보가 없으면 `null/unknown`으로 기록한다. 없는 값을 추정 생성하지 않으며 현재 analyzer가 임의 영상 형식을 지원한다고 가정하지 않는다.

## C. capture provenance schema

### C.1 표현 규칙

- 신규 JSON은 UTF-8, schema별 `schema_version`을 가진다.
- 시간은 offset을 포함한 ISO-8601을 사용한다. 예: `2026-10-01T14:30:25.123456+09:00`. raw의 device timestamp와 구분한다.
- hash는 원본 byte에 대한 SHA-256 소문자 64자리다. 텍스트 줄바꿈을 정규화한 뒤 hash하지 않는다.
- 알 수 없는 값은 `null`과 `provenance_unknown_reasons`에 이유를 남긴다. 현재 실행 환경의 정보를 과거 촬영 환경으로 기입하지 않는다.
- 기존 JSON key와 값의 의미는 유지하고 새 필드를 추가한다. 기존 `start_time`, `target_range_m`, `record_file`을 삭제하거나 다른 뜻으로 사용하지 않는다.

### C.2 camera metadata 필드

`현재`는 이미 저장됨, `추가`는 신규 provenance, `명시화`는 현재 계산/설정에는 있지만 별도 metadata로 저장하지 않는 항목이다.

| 필드 | 형식·의미 | 구분 |
|---|---|---|
| `schema_version` | `capture-provenance/1.0.0` | 추가 |
| `recording_id` | A의 불변 ID | 추가 |
| `subject`, `round` | 기존 참가자·회차 의미; canonical round는 십진 문자열 | 현재 |
| `dataset_role` | B의 enum | 추가 |
| `protocol_version` | 신규 현재 동작에 부여할 ID: `capture-forward-face-v2.0.0` | 추가 |
| `capture_start_time` | ID 발급 시각, ISO-8601 offset 포함 | 추가 |
| `capture_timezone` | 신규 수집 `Asia/Seoul`; 외부 자료는 알려진 값/unknown | 추가 |
| `recording_started_at`, `recording_ended_at` | 성공한 스트림 시작·종료 시각. ID 발급 시각과 별도 | 추가 |
| `start_time` | 기존 파일 stem용 timestamp; 호환 목적으로 유지 | 현재 |
| `record_file` | 실제 선택된 raw basename | 현재 |
| `git_commit` | 촬영 프로세스가 실행한 checkout의 전체 commit SHA; 미확인 시 null | 추가 |
| `git_dirty` | 실행 시작 시 working tree 변경 여부 | 추가 |
| `capture_script_sha256` | 실행할 `capture_d455.py` 원본 byte hash | 추가 |
| `runtime_versions` | Python, pyrealsense2, OpenCV, NumPy, Pillow 버전 | 추가 |
| `capture_face_detector` | Haar cascade 파일명·SHA-256; MediaPipe와 혼동 금지 | 추가 |
| `fps` | 기존 설정 FPS=15 | 현재 |
| `color_resolution`, `depth_resolution` | 각각 `{width,height}`. 기존 intrinsics에도 크기가 있음 | 명시화 |
| `streams` | 요청 설정과 실제 profile의 stream/format/width/height/fps | 명시화 |
| `device`, `serial`, `firmware`, `usb` | RealSense 장치 정보. serial을 별도 중복 이름으로 바꾸지 않음 | 현재 |
| `depth_scale_m` | raw depth 단위→m 변환 계수 | 현재 |
| `color_intrinsics`, `depth_intrinsics` | width/height/fx/fy/ppx/ppy/model/coeffs | 현재 |
| `depth_to_color_extrinsics` | rotation, translation | 현재 |
| `stereo_baseline_mm` | 조회 불가 시 null | 현재 |
| `start_distance` | 초기 안내에서 얻은 거리와 mode; skip 표시 포함 | 현재 |
| `target_range_m` | 초기 착석 목표 `[0.70,0.80]`; 전방 목표가 아님 | 현재 |
| `initial_seating_distance_range_m` | `[0.70,0.80]`, 위 기존 값에서 생성하는 명시적 alias | 추가 |
| `sequence`, `prep_sec` | 기존 자세·유지 시간·준비 시간 | 현재 |
| `forward_target_min_m`, `forward_target_max_m` | 현 상수에서 읽은 0.08, 0.12 | 명시화 |
| `forward_validation_source` | `face_only` | 명시화 |
| `forward_gate_settings` | 아래 C.3의 실제 설정 snapshot | 명시화 |
| `capture_state` | `initializing / recording / completed / aborted / failed` | 추가 |
| `provenance_unknown_reasons` | 확인 불가 필드와 이유의 mapping | 추가 |

`protocol_version`은 schema 버전과 다르다. JSON 필드 추가만으로 연구 프로토콜을 변경한 것으로 취급하지 않는다. 반대로 실제 gate나 안내가 변경되면 protocol version을 별도 검토한다. 기존 P01/P02에는 이 신규 protocol ID를 소급 부여하지 않는다.

git commit만으로 dirty 실행 코드를 식별할 수 없으므로 file hash를 함께 기록한다. hash/버전 획득은 촬영 설정이나 모델 동작을 바꾸지 않는다. 환경을 조회할 수 없으면 그 사실을 보존한다.

### C.3 현재 판정 설정을 그대로 기록

`forward_gate_settings`에는 다음을 기록한다. 아래 값은 이번 문서가 새로 제안하는 threshold가 아니라 현재 코드의 값이다.

| key | 현재 값·규칙 |
|---|---|
| `target_bounds_inclusive` | true |
| `comparison_abs_tol_m`, `comparison_rel_tol` | `1e-12`, `0` |
| `valid_face_rule` | `mode == "face" and distance_m is not None` |
| `min_valid_face_fraction` | `0.5`, 분모는 해당 window의 모든 sample |
| `final_min_valid_face_samples` | `1` |
| `final_window` | `1.0 < t < phase_duration_s - 0.5` |
| `reference_policy` | 직전 hold upright. 부족한 직전 reference를 더 오래된 것으로 대체하지 않음 |
| `live_reference_window` | 직전 upright의 `t > 1.0`; final과 달리 종료 trim 없음 |
| `live_current_window` | 현재 phase의 `t > 0.5` 중 최근 10개 sample |
| `live_min_valid_face_samples` | `3` |
| `live_median_last_valid_faces` | `5` |
| `live_current_mode_required` | `face` |

초기 거리 안내의 일반 body fallback과 전방 face-only gate는 별개다. 위 metadata를 만드는 과정에서 `measure_distance()`, depth ROI, smoothing, CSV sample 기록 방식은 변경하지 않는다.

## D. forward hard-gate evidence

기존 quality JSON의 `verdict/fails/warnings/frames/total_sec/steps`를 유지하고, 최상위에 `schema_version`, `recording_id`, `dataset_role`, `protocol_version`, `forward_gate_evidence`를 추가한다.

`forward_gate_evidence`는 **forward_head/body_forward hold phase별 배열**이다. 현재 `quality_check()`가 실제로 사용한 값을 그대로 기록한다. 다른 라이브러리나 새 window로 다시 산출한 값을 판정 근거라고 쓰지 않는다.

| 필드 | 의미 |
|---|---|
| `step`, `phase_idx`, `label` | 현재 판정 대상 식별 |
| `reference_recording_id` | 현재 recording_id와 동일해야 함 |
| `reference_step`, `reference_phase_idx` | 직전 upright. 없으면 null |
| `reference_total_samples`, `current_total_samples` | 각각 기존 final trim 후 window의 전체 sample 수 |
| `reference_valid_face_samples`, `current_valid_face_samples` | 위 window에서 현재 valid_face_rule에 맞는 sample 수 |
| `reference_valid_face_fraction`, `current_valid_face_fraction` | valid/total. total=0이면 null |
| `reference_face_median_m`, `current_face_median_m` | gate에 실제 제공된 대표값. helper가 부족 판정으로 None을 반환했으면 null |
| `closer_m` | reference median−current median. 둘 중 하나라도 사용 불가이면 null |
| `forward_target_min_m`, `forward_target_max_m` | capture metadata의 동일 상수 값 |
| `forward_validation_source` | `face_only` |
| `forward_gate_result` | `pass / fail` |
| `forward_gate_reasons` | 아래 고정 reason code 배열 |

reason code: `below_target`, `above_target`, `missing_reference`, `insufficient_reference_face_samples`, `insufficient_current_face_samples`. 정상 범위이면 빈 배열이다. reference가 없으면 reference 관련 median은 null, sample 수는 0으로 명시한다. 없는 측정값을 0m로 저장하지 않는다.

- 최소 수 또는 50% 조건을 만족하지 않는 구간은 관측된 face 값이 일부 있어도 gate median을 null로 기록한다. 임의 진단용 중앙값을 사용된 값으로 오인시키지 않는다.
- 기존 `face_ratio`는 mode==face 비율이고, 위 fraction은 **유효 거리까지 있는 face 비율**이다. 기존 필드를 덮어쓰지 않는다.
- 기존 `steps[].median_m`에는 body fallback이 섞일 수 있다. 이를 face-only evidence로 대체하거나 재해석하지 않는다.
- 전방 gate의 pass가 전체 quality pass를 의미하지 않는다. 중단·프레임 누락·다른 기존 실패 사유는 기존 overall verdict에 반영된다.
- 이 단계의 필수 evidence는 final이다. live의 매 화면 상태를 영구 기록하는 새 로깅 체계는 필수로 추가하지 않는다.

## E. analysis provenance schema

### E.1 두 ID의 역할

- `recording_id`: **어떤 촬영본인가**. 재분석해도 동일하다.
- `analysis_run_id`: **그 촬영본을 어떤 코드·모델·옵션으로 처리한 한 번의 실행인가**. 같은 옵션의 재실행도 새 ID다.

analysis run은 recording 하나를 대상으로 한다. 복수 recording CLI 실행은 각각 run을 발급하고 선택적으로 공통 `analysis_batch_id`로 묶는다. ID 형식은 `ar_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>`로 한다. run 경로는 배타적으로 만들며 성공·실패 후 재사용하지 않는다.

### E.2 `analysis_manifest.json`

| 필드 | 요구사항 |
|---|---|
| `schema_version` | `analysis-provenance/1.0.0` |
| `analysis_run_id`, `recording_id` | 필수 식별 |
| `analysis_batch_id` | 선택적 batch 연결 |
| `analysis_mode` | `extract_raw` 또는 `summarize_existing_frames` |
| `parent_analysis_run_id` | 재요약의 frame 원본 run; 최초 추출은 null |
| `dataset_role`, `protocol_version` | capture/catalog에서 전달; 새로 추정하지 않음 |
| `started_at`, `ended_at`, `status` | ISO-8601 UTC; `running/completed/failed` |
| `inputs.recording` | filename, dataset-root-relative path, byte size, SHA-256, hash 상태 |
| `inputs.markers` | path, SHA-256, recording_id |
| `inputs.capture_metadata`, `inputs.quality` | 존재할 경우 path/hash, 없으면 이유 |
| `inputs.frames` | `--from-csv`이면 원본 frame CSV path/hash와 소유 analysis_run_id |
| `code` | git_commit, git_dirty, `analyze_d455.py` SHA-256 |
| `environment` | Python, mediapipe, pyrealsense2, OpenCV, NumPy, matplotlib 버전; OS/architecture |
| `models` | 아래 모델별 정확한 artifact 기록 |
| `options` | 원본 CLI와 실제 적용한 값; `--step` 요청값과 `max(1, step)` 적용값 모두 |
| `processing_settings` | trim 시작/종료, depth align target, ROI·유효 pixel 조건, 모델 task 옵션, landmark index 목록 등 현재 값 snapshot |
| `playback_calibration` | 분석이 실제 raw playback에서 얻은 intrinsics/depth scale; capture metadata와 구분 |
| `outputs` | 각 파일의 path, kind, schema_version, SHA-256, row count |
| `errors` | 실패 단계·원인. 실패 run을 completed로 간주하지 않음 |

model entry는 `role`, `filename`, `sha256`, `size_bytes`, `source_url`, `version_identifier`, `used_in_this_run`을 가진다.

현재 대상은 `blaze_face_short_range.tflite`, `face_landmarker.task`, `pose_landmarker_full.task`다. 향후 formal 분석은 **고정 모델 lock 목록의 hash와 실제 파일을 대조**한다. `latest`가 원래 다운로드 출처였어도 URL만으로 동일 모델이라 인정하지 않는다. 구체적으로 채택할 모델 artifact/hash는 실제 파일 확인 후 별도 고정하며 이 문서에서 가짜 hash를 채우지 않는다.

`--from-csv`도 새 run이다. 기존 frame 파일은 수정하지 않고 그 hash/parent run을 기록한다. 모델은 원본 추출 run의 provenance를 참조하고 `used_in_this_run=false`로 표시한다. 현재 설치 모델로 재추출한 것처럼 기록하지 않는다. 원본 run 정보가 없으면 legacy/unknown 상태다.

### E.3 큰 raw 파일의 hash 정책

1. raw writer가 닫힌 뒤 streaming SHA-256을 한 번 계산하여 artifact catalog에 등록한다. 녹화 중에는 `pending`으로 둘 수 있으나 formal 분석 입력 확정 전에는 hash가 필요하다.
2. formal 분석 직전에 raw와 markers의 전체 hash를 검증하는 것을 기본으로 한다. 전체 파일을 RAM에 적재하지 않는다.
3. 검증된 content-addressed 불변 보관소를 사용하는 경우에만 저장소의 검증된 digest를 재사용할 수 있다. 검증 방식·시각을 manifest에 기록한다.
4. size/mtime만 같은 파일을 내용까지 동일하다고 간주하지 않는다. 불완전 hash나 prefix hash를 SHA-256 전체 검증으로 표시하지 않는다.
5. 출력은 파일을 닫은 뒤 hash한다. manifest 자신의 hash는 해당 manifest의 내부 output 목록에 넣지 않고 상위 catalog/result에서 참조해 순환을 피한다.

## F. canonical frame schema

### F.1 fixed schema를 채택

신규 `frames-schema/1.0.0`은 **고정 열·고정 순서·명시적 단위**를 사용한다. 현재 `row.keys()` 합집합 방식은 신규 canonical writer에서는 사용하지 않는다.

- 아래 현재 31개 필드를 원래 의미 그대로, 표 순서대로 유지하고 F.3의 새 필드를 뒤에 붙인다.
- CSV는 UTF-8-sig와 header를 사용한다. 측정 누락은 빈 셀, JSON 대응은 null이다. 검출 실패를 숫자 0으로 채우지 않는다.
- boolean은 `true/false`, legacy에서 모르면 빈 셀이다. NaN/Infinity를 정상 측정값으로 저장하지 않는다. schema 오류를 새 posture drop 정책으로 전환하지 않는다.
- RGB/depth 부재, trim, `--step` 등 **기존 frame 선택은 유지**한다. 선택되지 않은 프레임을 가상 row로 만들거나 기존 row를 새 confidence 기준으로 제거하지 않는다.
- 검출 여부와 valid flag는 관찰용이다. 새로운 촬영/학습 acceptance threshold가 아니다.
- F0/F1/F2용 파생 feature 배열이나 수식은 이 문서에서 정하지 않는다.

### F.2 현재 추출 가능한 31개 필드

| 기존 필드(이 순서) | 형식·단위·현재 의미 |
|---|---|
| `subject`, `round`, `step`, `label` | 참가자, 회차 문자열, 단계 정수, 기존 posture label |
| `t`, `ts_ms` | 구간 시작 대비 초(현재 소수 3자리), 원래 frameset timestamp(ms). wall-clock 시각이 아님 |
| `face_x`, `face_y` | 얼굴 detector bbox 중심, color pixel 좌표 |
| `face_w_px`, `face_h_px` | detector bbox 폭·높이(px) |
| `face_area_px` | bbox 면적(px²). 기존 이름 유지 |
| `face_score` | 선택된 face detection category score; 없으면 null |
| `z_face_m` | 얼굴 depth(m). bbox 중앙 ROI 또는 face oval 중심 ROI 경로 |
| `face_size_cm2` | 기존 bbox 면적×depth²/(fx·fy) 기반 cm² 추정 |
| `oval_area_px`, `oval_size_cm2` | FACE_OVAL landmark polygon 면적(px²), 기존 cm² 추정 |
| `ipd_px`, `ipd_cm` | 기존 iris 468/473 간 거리와 depth 기반 cm 추정 |
| `box_to_oval` | 기존 bbox 면적/oval 면적 |
| `lsh_x`, `lsh_y`, `rsh_x`, `rsh_y` | color pixel 좌표, MediaPipe landmark 11/12; **사람 기준 좌/우** |
| `lsh_vis`, `rsh_vis` | 기존 MediaPipe visibility. detector confidence와 구분 |
| `z_lsh_m`, `z_rsh_m` | 좌·우 어깨 ROI depth(m) |
| `z_sh_m` | 현재 규칙대로 유효한 어깨 depth 평균. 한쪽만 유효하면 그 값 |
| `theta1_deg`, `theta2_deg`, `theta3_deg` | 기존 각도와 합(deg). 새 feature 정의를 뜻하지 않음 |

좌표계는 **원래 color 이미지의 비반전 pixel 좌표**다. capture의 거울 UI 좌표나 RF의 640×480 환산 좌표로 덮어쓰지 않는다. analysis는 depth를 color에 align한다. `lsh/rsh`의 사람 기준과 RF가 사용하는 화면 좌우 어깨 mapping을 명시적으로 구분한다.

### F.3 추가할 metadata/관찰 필드

아래 표 순서로 열을 추가한다. 모델·코드 hash 같은 run 공통 정보는 manifest에 저장하고 ID로 연결한다.

| 신규 필드 | 확보 방법·정책 |
|---|---|
| `frame_schema_version` | `frames-schema/1.0.0` |
| `recording_id`, `analysis_run_id` | manifest에서 전달 |
| `dataset_role`, `protocol_version` | catalog/capture에서 전달 |
| `frame_index` | playback 처리 순번 `n`을 보존; filtering 전에 증가하는 기존 순번 |
| `color_frame_number`, `depth_frame_number` | 실제 frame 객체에서 얻는 식별값; 현재 CSV에는 없음 |
| `mediapipe_ts_ms` | VIDEO API에 실제 전달한 `ts_int`; 현재 원래 timestamp와 별도로 보정할 수 있으므로 따로 보존 |
| `image_width`, `image_height` | 실제 color 이미지 W/H |
| `depth_alignment_target` | `color` |
| `face_bbox_x`, `face_bbox_y` | 이미 지역변수에 있는 bbox origin. 새 검출을 하지 않고 보존 |
| `face_depth_source` | `bbox_center / oval_center / missing / unknown_legacy`; **body fallback source가 아님** |
| `face_detected`, `face_mesh_detected`, `pose_detected` | 실제 task result 유무. 저장된 scalar 하나에서 검출 성공을 역추정하지 않음 |
| `face_depth_valid`, `lsh_depth_valid`, `rsh_depth_valid` | 기존 depth 계산이 유효 값을 반환했는지. 새 pixel/visibility threshold 없음 |
| `shoulder_depth_source` | `both / left_only / right_only / missing / unknown_legacy` |

신규 frame row의 기본키는 `(analysis_run_id, recording_id, frame_index)`다. timestamp만으로 유일성을 보장하지 않는다. 프레임 timestamp domain을 확인할 수 있으면 analysis manifest의 stream metadata에 기록하고, 확인 불가이면 unknown으로 둔다.

전체 face/pose landmark, deprojected 3D 좌표, IR 좌우 영상, 새로운 ROI 품질 통계는 이 고정 schema의 필수 원재료로 임의 채택하지 않는다. F1/F2 명세가 요구하는 경우 별도 schema version으로 확장한다. 현재 `z_face_m/z_lsh_m/z_rsh_m/z_sh_m`은 이미 사용 가능한 원재료다.

## G. step summary와 RF lineage

### G.1 summary

현재 최대 44개 컬럼을 유지한다.

- 기본: `subject, round, step, label, n_frames, face_detect_ratio, pose_detect_ratio`.
- 14개 `FEATS`와 각각의 `_sd`: `face_area_px, face_w_px, face_x, face_y, theta1_deg, theta2_deg, theta3_deg, z_face_m, z_sh_m, face_size_cm2, oval_area_px, oval_size_cm2, ipd_cm, box_to_oval`.
- 파생: `ref_step, A_ratio, A_ratio_oval, dZ_face_cm, dZ_sh_cm, D_head_cm, sh_face_ratio, area_err_est_pct, area_cv_pct`.

신규 열은 `summary_schema_version=summary-schema/1.0.0`, `recording_id`, `analysis_run_id`, `source_frames_analysis_run_id`, `dataset_role`, `protocol_version`, `reference_recording_id`, `reference_analysis_run_id`다.

- frame 입력 grouping key는 `(recording_id, frame의 analysis_run_id, step)`으로 바꾼다. 기존 `(subject, round, step)`만으로는 묶지 않는다.
- label·subject·round가 한 그룹 안에서 충돌하면 provenance/schema 오류다. 다른 촬영을 평균내 해결하지 않는다.
- summary의 upright reference 검색도 **같은 recording과 같은 frame run 안으로 제한**한다. 직전 upright라는 현재 시간적 규칙은 보존한다.
- 최초 raw 분석은 summary와 frames의 analysis_run_id가 같다.
- `--from-csv` 재요약은 summary의 analysis_run_id에 새 실행 ID를 쓰고, `source_frames_analysis_run_id`에는 원래 frame run ID를 쓴다. 원본 frames는 수정하지 않는다. reference_analysis_run_id는 reference row의 source frame run을 가리킨다.
- summary row 기본키는 `(analysis_run_id, recording_id, step)`. 한 summary run에 같은 recording의 서로 다른 frame run을 동시에 넣지 않는다.
- `face_detect_ratio`, `pose_detect_ratio`와 모든 통계 계산은 그대로다. 새 validity 열로 정의를 바꾸지 않는다.

### G.2 RF meta/result

- 현재 frames 직접 입력, 특징별 중앙값, 첫 upright A 기준, crop·환산·각도 재계산은 그대로 유지한다.
- 기존 RF `meta=(subject, round, step, label)` 인터페이스를 즉시 바꾸기보다, 동일 row 순서의 **별도 lineage 구조**를 추가하는 것을 우선한다.
- 각 RF 입력 sample은 `recording_id, analysis_run_id, step`, feature mode, calibration/reference step, 입력 frames hash를 추적할 수 있어야 한다. reference는 해당 recording에 속해야 한다.
- 기존 relative의 첫 upright 정책을 summary의 직전 upright 정책으로 통일하지 않는다. 역할이 다른 두 기준을 기록으로 구분한다.
- formal 입력은 H의 확정 manifest에서 읽는다. 같은 subject/round의 복수 take/run이 함께 선택되면 자동 병합·첫 파일 선택 대신 오류로 알린다.
- 참가자 LOSO의 group 단위는 계속 subject다. recording_id를 새로운 LOSO 참가자로 취급하지 않는다.
- RF 실행에는 별도 `experiment_run_id`와 dataset manifest의 ID/hash, RF 코드 hash·환경, 입력 sample lineage 목록을 기록한다.
- 기존 결과 CSV 필드는 유지하고 `experiment_run_id`, `dataset_manifest_sha256`, `lineage_manifest_path`, `lineage_manifest_sha256`을 추가한다. 기존 `root_provenance`는 유지한다.
- 집계 metric 하나에 여러 recording이 기여하므로 단일 recording_id를 그 metric의 원본처럼 쓰지 않는다. 결과→불변 lineage manifest→sample→frames run→recording으로 역추적한다.
- paper Dataset.xlsx 등 recording_id가 없는 외부 표 데이터에는 별도 `source_dataset_id + file hash + row identity`를 사용한다. 가짜 recording_id를 만들지 않는다.

## H. 재촬영 선택 정책

### H.1 확정 구조: versioned manifest + append-only 선택 이력

manifest 파일을 권위 있는 입력으로 채택한다. CLI의 recording 지정은 탐색·pilot용으로 허용할 수 있으나 formal 분석은 확정 manifest 경로/hash를 요구한다. 별도 inclusion table은 manifest의 표현 형식으로 둘 수 있지만 독립적인 두 선택 원장을 운영하지 않는다.

미래의 파일 구성:

- `recordings.jsonl`: 모든 시도와 artifact 위치/hash를 등록. 실패한 recording도 남김.
- `selection_events.jsonl`: 추가 전용 선택 이력. 과거 행을 수정·삭제하지 않음.
- `datasets/<dataset_manifest_id>.json`: 승인된 선택 snapshot. 한 번 확정하면 불변.

각 선택 entry는 subject/round, recording_id, 사용할 analysis_run_id, 역할, include 여부, 이전 선택 ID, 이유 코드·설명, 담당자, 결정 시각, 사전 등록된 selection policy version을 가진다. policy와 evidence/quality 파일 hash도 연결한다.

### H.2 A/B 재촬영의 규칙

- A/B 모두 저장한다. 파일 정렬, 최신 timestamp, 가장 높은 얼굴 검출률, 가장 좋은 RF 결과로 코드가 자동 선택하지 않는다.
- 정식 선택은 **사전에 정한 촬영 순서와 기술적 eligibility 규칙을 충족한 최초 시도**를 기본 정책으로 manifest에 명시한다. 자동 선택 대신 담당자가 원장에 결정을 기록한다.
- eligibility는 현재 protocol/quality gate와 별도의 파일 무결성 확인 결과를 사용한다. 얼굴/어깨 관계, 분류 정확도, 원하는 root split 비율로 판정하지 않는다.
- 실패 후 재촬영은 허용되지만 실패 이유·시도 순서·대체 관계를 남긴다. A가 이미 eligible이면 B의 성능/품질 수치가 더 좋아도 바꾸지 않는다.
- 촬영 당시 알 수 없던 파일 손상 등 기술적 사유로 선택을 바꾸려면 사건과 근거를 추가 기록하고 새 dataset manifest를 발급한다. 이미 발표/계산한 결과의 입력 manifest를 덮어쓰지 않는다.
- 같은 `(subject, round, 수집 protocol, 연구 방문/condition)`에서 둘 이상의 recording을 정식으로 사용할 계획이면 먼저 연구 단위와 반복측정 정책을 정한다. 현재처럼 모호한 round만으로 결합하지 않는다.
- `ok_with_warnings` 처리, 재촬영 상한, 예외 승인자는 수집 시작 전에 연구 policy로 확정해야 한다. 미확정 상태에서 formal selection을 임의 수행하지 않는다. 관측된 높은 성능으로 이 정책을 사후 결정하지 않는다.

## I. 권장 파일/폴더 구조

아래는 미래 구조이며 이번 Step에서 생성·이동하지 않는다.

```text
data/
  pilot/<recording_id>/
  formal/<recording_id>/
    <recording_id>.db3                 # 또는 실제 선택된 .bag
    <recording_id>_camera.json
    <recording_id>_markers.csv
    <recording_id>_samples.csv
    <recording_id>_quality.json
  external/<recording_id>/
analysis/
  <recording_id>/<analysis_run_id>/
    analysis_manifest.json
    <recording_id>_frames.csv
    summary_steps.csv
    summary_report.txt
    figures/
results/
  <experiment_run_id>/
    experiment_manifest.json
    sample_lineage.jsonl
    rf_results.csv
    rf_results.txt
    fig5_rf_compare.png
manifests/
  recordings.jsonl
  selection_events.jsonl
  model_lock.json
  datasets/<dataset_manifest_id>.json
```

- 기존 평면 경로는 그대로 읽을 수 있게 유지한다. 새 formal 실행만 명시적 registry/manifest 경로를 사용한다.
- run별 디렉터리 안에서는 기존 결과 basename을 유지할 수 있다. 실행 간 덮어쓰기는 금지한다.
- batch-level 보고서가 필요하면 별도 batch/experiment run 아래 저장하고 대상 child run ID를 기록한다. 서로 다른 run의 rows를 식별자 없이 합치지 않는다.
- raw는 불변 보관한다. 재시도나 새 분석을 위해 rename/delete하지 않는다. metadata 수정도 변경 이력과 artifact hash 연결을 남긴다.

## J. backward compatibility

### J.1 기존 P01/P02와 legacy 식별

- 기존 P01/P02는 `dataset_role=pilot`, `protocol_version=unknown_legacy`다. 현재 v2 gate 만족 여부를 소급 가정하지 않는다.
- 기존 raw/CSV/quality는 byte 그대로 보존한다. 새로운 provenance는 별도 catalog/sidecar 또는 메모리상의 canonical view로 보완한다.
- legacy ID는 `legacy_<원본 recording stem>_<등록된 raw SHA-256 앞 16자리>`를 기본으로 한다. 전체 SHA-256은 catalog에 보존하고 prefix 충돌 시 확장하여 해결한다.
- raw를 찾을 수 없으면 `legacy_csv_<CSV stem>_<CSV SHA-256 앞 16자리>`와 `identity_status=unresolved_raw`를 사용한다. 서로 다른 CSV를 동일 촬영이라고 추정 병합하지 않는다.
- legacy ID→원본 파일들 연결은 검증된 crosswalk에 기록한다. 파일명만으로 확신할 수 없는 연결은 unresolved 상태로 남긴다.
- 원본 capture 시각·commit·모델 hash를 모르면 null/unknown이다. 오늘 계산한 파일 hash는 현재 artifact의 hash일 뿐 과거 분석이 실제 사용한 모델의 증거가 아니다.

### J.2 loader 정책

- old CSV의 기존 31개/44개 측정 필드는 이름·단위·값을 유지한다. 누락 열은 canonical view에서 null로 표현한다.
- legacy import row를 구별할 필요가 있으면 adapter sidecar에 원본 CSV row 번호를 둔다. 그것을 실제 카메라 frame number라고 부르지 않는다.
- `face_depth_source`, 검출 boolean, frame number 등 알 수 없는 새 metadata를 기존 scalar만 보고 채우지 않는다. `unknown_legacy` 또는 null을 사용한다.
- legacy 입력은 명시적 pilot 경로/옵션으로 읽는다. 새 formal manifest로 조용히 편입하지 않는다.
- 중복 촬영이 없는 기존 입력의 숫자 결과는 호환성 기준으로 유지한다. 중복 자료가 모호하게 섞인 경우 canonical 경로는 오류/선택 요구로 처리하고, 임의로 과거 결과와 같게 만들기 위해 계속 병합하지 않는다.
- 현재 RF의 feature/drop/평가 규칙을 legacy adapter가 바꾸지 않는다.

## K. 이후 구현 순서 — 최소 patch 단위

각 patch는 별도 검토·회귀 검증 후 다음으로 진행한다. 아래 새 모듈·테스트 이름은 미래 계획이며 이번 Step의 생성 파일이 아니다.

| Patch | 수정/추가 대상 | 하는 일 | 하지 말아야 할 것 | 필요한 테스트 | 예상 위험 |
|---|---|---|---|---|---|
| 1. ID·artifact 계약 | 작은 `data_provenance.py`, 전용 테스트 | ID 발급·충돌 거부·schema/version·hash 유틸, legacy crosswalk 규약 | capture/RF 동작 변경, 전체 pipeline 재구성 | 동시/동일 timestamp ID, 기존 경로 overwrite 금지, hash·timezone·unknown | filename parser와 ID 길이, 대용량 hash 비용 |
| 2. capture metadata | `capture_d455.py`, provenance 테스트 | ID를 raw/metadata/markers/samples에 전파, protocol/code/settings 기록 | streams·시간·label·depth 계산·기존 CSV 열 의미 변경 | 기존 열/값 보존, 실패 시도 ID, dirty code hash, fallback 형식 동일 ID | 중단 시 metadata 미완성, 기존 flat 파일 소비자 |
| 3. gate evidence | `capture_d455.py`, `test_capture_protocol.py` | 기존 final gate 계산 근거를 quality에 추가 | threshold·window·median·face 비율·shoulder gate 변경 | pass/fail 값 동일, 정확한 counts/분모, 부족 시 null, 최신 upright 사용 | 진단 재계산과 실제 판정의 불일치 |
| 4. 모델 lock·analysis run | `analyze_d455.py`, 분석 provenance 테스트 | 고정 모델 hash 검증, run manifest·고유 출력 경로 | 다른 모델로 조용히 교체, 추출 옵션/trim 변경 | cached model 검증, hash mismatch, run overwrite 금지, from-csv parent 표기 | 기존 모델 정체 불명, 라이브러리 버전 차이 |
| 5. canonical frames | `analyze_d455.py`, frame schema 테스트 | 기존 31개 값 보존 + 고정 header + metadata/source 플래그 | F1/F2 구현, 새 confidence/depth drop 조건 | 검출 누락에도 header 고정, 기존 값 동일, 사람/화면 좌우, timestamp 두 종류 | 검출 실패와 unknown 혼동, RGB/depth 대응 |
| 6. summary·legacy | `analyze_d455.py`, summary/legacy 테스트 | recording/run 단위 grouping와 reference 격리, legacy 명시적 import | 직전 upright를 첫 upright로 교체, 기존 FEATS 통계 변경 | 두 retake 절대 병합 금지, 두 run 분리, 기존 단일 take 수치 동일 | 기존 오병합 결과와의 차이, from-csv lineage 누락 |
| 7. manifest 선택·RF 연결 | 선택 도구/manifest validator, `rf_experiment.py` 입력·출력부, 전용 테스트 | 선택 이력·snapshot, RF 병렬 lineage와 실행 디렉터리 | Tree/Forest/weight/λ/feature/평가 마스크 변경, root stats 변경 | 중복 선택 거부, seed/fold 불변, 기존 prediction/metrics 동일, 결과→raw 추적 | sample 순서·LOSO 그룹·relative reference의 우발 변경 |
| 8. 무결성·통합 검증 | `check_recording.py`, 통합 테스트, 운영 절차 | artifact/marker 연결과 run 완결성 검증, 실제 카메라 smoke test | 추가 검사 결과로 과거 데이터 자동 삭제, 새 연구 acceptance 조건 암묵 도입 | raw+sidecar mismatch, 실패 run 배제, end-to-end lineage, 전체 기존 unittest | 실제 SDK/장치 차이, EOF와 재생 실패 구분 |

테스트가 쓰는 synthetic 수치는 구조 검증용이다. 실제 연구 정확도나 과거 root 비율 재현을 목표로 하지 않는다. 정식 수집 전에는 사람에 의한 D455/GUI smoke test와 실제 artifact 확인이 필요하다.

## L. 확정 사항과 아직 연구 결정이 필요한 사항

이 문서에서 확정한 설계는 ID·role·provenance 필드·hash 정책·고정 frame schema·recording/run별 summary grouping·manifest 선택 이력·legacy 격리·구현 순서다.

다음은 구현자가 임의 결정하지 않는다.

1. **F0/F1/F2의 최종 연구상 정의와 입력 차원**. 현재 all/invariant/relative를 이름만 바꿔 F1/F2로 간주하지 않는다. 6개 초과 weight 정책도 별도 연구 결정이다.
2. formal/external의 모집·조건·반복측정 단위와 허용 촬영 회수, `ok_with_warnings`의 eligibility, 기술적 예외 승인자. 수집 전에 H의 selection policy를 완성한다.
3. 실제 고정할 MediaPipe 모델 artifact/hash 및 환경 조합. 현재 로컬에 없거나 확인하지 않은 파일의 버전을 추정하지 않는다.
4. F1/F2가 추가로 요구할 수 있는 전체 landmark·3D·IR 원재료. 필요 여부 확정 전 녹화 스트림이나 feature를 확장하지 않는다.
5. baseline 분석과 신규 연구에서 사용할 calibration 정의. 현재 capture/summary의 직전 upright와 RF의 첫 upright 정책은 서로 다른 것으로 보존하며, 통일은 별도 연구 변경이다.

이 명세는 기존 데이터나 성능 결과를 재해석하는 승인이 아니다. 이후 구현에서도 소스 변경 범위와 검증 결과를 보고하며 자동 commit/push는 하지 않는다.
