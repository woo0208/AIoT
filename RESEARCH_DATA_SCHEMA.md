# Research Data Schema — recording / provenance / analysis

- 명세 버전: `research-data-schema/1.1.0`
- 최초 작성일: 2026-09-30
- Canonicalization amendment: **2026-10-01 — GOV-005 / OPEN-001에 따른 Patch 4 pre-freeze authority/status overlay를 추가했다. 이 amendment는 field/data contract 또는 capture protocol 변경을 의미하지 않는다.**
- 상태: **Hybrid contract/design record. 현재 구현 사실은 Git/source/test와 canonical Foundation records가 우선한다. 아직 구현되지 않은 future schema/path는 설계안이며, Patch 4 exact canonical contract는 2026-10-01 Research Decision Log의 GOV-005/OPEN-001에 따라 Design Freeze 전 proposal이다.**
- 적용 지침: [AGENTS.md](AGENTS.md). 연구 결과는 목표값이 아니라 증거로 취급한다.
- 2026-09-30 Step 1.5 원작성 범위: 당시 산출물은 이 문서뿐이었으며, 소스·테스트·기존 데이터의 변경, 파일 이동, 모델 다운로드, 성능 실험은 수행하지 않았다.


### 2026-10-01 canonicalization 전 status overlay

이 문서에는 작성 당시의 **현재 구현 설명**, 이미 구현된 provenance 방향, 그리고 **future/unimplemented 설계안**이 함께 있다.
따라서 다음 권위 규칙을 적용한다.

```text
현재 구현 사실
→ Git / source / test + canonical docs/foundation 우선

future/unimplemented design
→ 설계 proposal 또는 confirmed direction으로 읽음
→ exact contract가 Decision Log의 OPEN item이면 Design Freeze 전 final contract로 간주하지 않음

Patch 4 exact canonical frame contract
→ GOV-005 / OPEN-001 우선
```

특히 §F.1/§F.3/§F.4의 candidate version/header/field detail과 이를 참조·요약하는 §K 5a/5b, §L, §N.2/§N.3의 exact contract 표현은
**Patch 4 pre-freeze proposal**이다. 아래 표와 이름은 설계 검토 재료로 보존하지만 자동 채택하지 않는다.
이 status overlay는 Patch 1~3에서 이미 구현·검증된 provenance/lineage 동작을 되돌리는 것이 아니다.

절별 해석은 다음과 같다.

```text
§0 및 A~E
→ 작성 시점의 구현 snapshot + provenance 설계 기록.
→ 현재 구현 여부/값은 최신 Git/source/test + canonical Foundation record로 재확인.

§F
→ Patch 4 fixed-frame/raw-observation proposal. exact contract는 OPEN-001.

§G~I
→ 후속 lineage/selection/file-layout target architecture. 현재 구현 완료를 뜻하지 않음.
→ exact 파일/필드/운영 계약은 해당 후속 Design Freeze/Decision Log가 있으면 그것을 우선.

§J
→ backward-compatibility 원칙/설계 기록. 실제 adapter 동작은 source/test로 확인.

§K
→ Step 1.5 당시 future implementation plan. 현재 operational Patch roadmap 권위가 아님.

§L~N
→ Step 1.5 상태 요약·validation proposal. Research Master/Decision Log의 현재 status가 우선.
```

## 0. 현재 구현과 변경 금지 경계

아래 표는 **2026-09-30 Step 1.5 작성 당시 구현 snapshot**을 설명하기 위해 사용한 근거다.
Patch 1~3 이후의 현재 구현 사실은 최신 Git/source/test와 canonical Foundation records를 우선한다.

작성 당시 확인 근거:

| 코드 | 현재 책임과 본 설계의 경계 |
|---|---|
| `capture_d455.py:make_config/record_phase` | color 1280×720 BGR8, depth 848×480 Z16, 각각 15 FPS. raw와 camera/markers/samples 기록 |
| `capture_d455.py:median_face_distance/quality_check/report` | face-only 전방 판정과 기존 일반 거리·품질 통계. 신규 evidence는 이 계산의 관찰값 |
| `analyze_d455.py:ensure_models/process_recording` | 모델 확보, raw+markers에서 최대 31개 frame 필드 추출 |
| `analyze_d455.py:summarize/load_frames_csv` | 현재 `(subject, round, step)` grouping과 CSV 재요약 |
| `rf_experiment.py:load_ours/transform/main` | frames CSV에서 단계별 입력 구성, 첫 upright 기준, feature 변환·평가 마스크 |
| `rf_experiment.py:Tree/Forest/rank_weights/fit_models` | 검증된 모델 핵심. provenance 구현 대상이 아님 |

Step 1.5 작성 당시 snapshot에서는 raw 파일명에 촬영 timestamp가 있어도 frame row/RF meta의 촬영본 식별, model hash, run-specific output이 충분하지 않았다.
이후 Foundation Patch 1~3에서 recording provenance, forward-gate evidence, analysis provenance/lineage가 구현되었으므로 이 문장을 **현재 구현 상태**로 인용하지 않는다.
현재 잔여 문제와 구현 상태는 최신 source/test 및 canonical Foundation records를 따른다.

이 명세는 데이터의 식별·연결·관찰 기록을 정한다. 다음은 그대로 유지한다.

- Tree 분할, Forest RNG/Bootstrap pairing, M0/M1/M2 정의, rank weight, λ.
- all/invariant/relative 값, 좌표 환산, 기존 결측 제외 조건, LOSO 및 평가 정의.
- 기존 relative 비교 실험에서 reference를 training/calibration에 유지하고 non-reference 평가만 추가하는 정책.
- body_forward의 정식 5-class 평가 제외와 보조 분석.
- 8~12 cm face-only hard gate, 일반 body fallback, 기존 촬영 sequence·label·FPS·시간.
- 어깨 이동·얼굴/어깨 비율을 새로운 촬영 acceptance criterion으로 삼지 않는다.

**현재 RF는 `summary_steps.csv`가 아니라 `*_frames.csv`를 직접 읽는다.** lineage를 위해 RF 입력을 summary로 바꾸지 않는다. raw→frames→summary와 raw→frames→RF의 두 경로를 모두 추적한다.

### 0.1 연구 feature 계층과 역할

원 논문의 RF/WRF 재현 및 M0/M1/M2 비교는 유지한다. 아래 명칭은 연구상 역할을 구분하며 현재 CLI mode나 코드의 이름을 변경하는 지시가 아니다.

| 계층 | 역할 | 개인별 upright reference 의존성 |
|---|---|---|
| `F0` | 원 논문의 기존 baseline feature set. 기존 재현 경로의 값·전처리·비교 정의 보존 | 기존 재현 정의를 그대로 보존하며 calibration-free라고 재해석하지 않음 |
| `F_cal` (`legacy_relative`) | 개인별/회차별 upright/reference 기반 기존 relative 비교 실험 | 기존 reference 사용. 최종 제안 방법의 필수 구성요소가 아님 |
| `F1` | **calibration-free body-relative 2D / upper-body skeletal geometry candidate family** | 개인별 사전 정상 자세 측정 없이 현재 프레임의 신체 지점 간 관계 사용 |
| `F2` | **F1 + RGB-D / metric 3D upper-body geometry + sagittal-plane geometry candidate family** | F1과 동일하게 개인별 사전 calibration 불필요 |

위 F1/F2 role wording은 §L.4 / §N.6의 현재 candidate 방향과 정합화한 설명이며 exact feature contract가 아니다.
F1/F2의 정확한 수식·feature 개수·선택 landmark 조합은 후속 연구에서 확정한다. all/invariant/relative를 이름만 바꿔 F1/F2로 간주하지 않는다. face/head, 양쪽 shoulder, 양쪽 hip의 원재료 확보는 trunk/head geometry 연구를 가능하게 하기 위한 것이며 특정 각도·비율을 모델 입력으로 확정하는 결정이 아니다. elbow/wrist는 선택적 원재료 후보다.

### 0.2 upright 촬영, 비교용 calibration, 최종 inference의 구분

1. **촬영 sequence의 upright**: 현재 sequence의 정상 자세와 8~12 cm face-only 촬영 gate의 기준이다. sequence·reference 계산·hard gate는 유지한다.
2. **F_cal의 calibration/reference upright**: 기존 relative 실험의 특징 계산 및 reference/non-reference 평가를 위한 것이다. 코드와 기존 비교 결과 경로를 삭제하지 않는다.
3. **F1/F2의 calibration-free inference**: 처음 몇 초 또는 20초 동안 개인의 올바른 자세를 먼저 측정하도록 요구하지 않는다. 이전 upright 값·개인 정상 자세 통계·reference 선택을 inference의 숨은 필수 입력으로 사용하지 않는다. 현재 프레임의 신체 기하관계와 장비의 intrinsics/depth scale 등 촬영 기하 정보는 구분한다.

촬영 품질 관리를 위해 upright를 촬영하는 것과 최종 모델이 그 upright에 의존하는 것은 별개다. 기존 F0/F_cal용 summary·RF 전처리를 그대로 F1/F2에 연결하여 의도치 않은 reference 의존성을 만들지 않는다. D455 장비 validation도 개인별 posture calibration과 별개다(M절).

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

### F.1 fixed schema proposal

현재 Step 1.5 proposal은 candidate label `frames-schema/1.1.0`과 **고정 열·고정 순서·명시적 단위**를 제안한다.
아래 candidate version label, exact field list/count/order는 `OPEN-001`이 닫히기 전 final Patch 4 contract가 아니다.
현재 `row.keys()` 합집합 방식에서 fixed writer로 이동한다는 방향과 exact header 계약을 구분한다.

- 현재 proposal은 기존 31개 field의 **기존 의미·값 보존**을 전제로 F.3/F.4 candidate field를 뒤에 배치한다. exact final list/count/order와 schema label은 `OPEN-001`이다.
- current proposal의 writer 표현은 UTF-8-sig/header, missing 빈 셀(JSON 대응 null), 검출 실패를 숫자 0으로 채우지 않는 방식을 사용한다. exact serialization contract는 Patch 4 Design Freeze에서 확정한다.
- current proposal의 boolean candidate 표현은 `true/false`이고 legacy unknown은 빈 셀이다. exact boolean writer/reader contract는 `OPEN-001`이다. NaN/Infinity를 정상 측정값으로 저장하지 않는 방향과 schema 오류를 새 posture drop 정책으로 전환하지 않는 원칙은 유지한다.
- RGB/depth 부재, trim, `--step` 등 **기존 frame 선택을 보존한다는 방향**은 유지한다. 선택되지 않은 프레임을 가상 row로 만들거나 기존 row를 새 confidence 기준으로 제거하는 변경은 이번 proposal의 목적이 아니다.
- 검출 여부와 valid flag는 관찰용이며 새로운 촬영/학습 acceptance threshold가 아니라는 방향을 유지한다.
- current proposal은 검출 실패/optional 비활성화에서도 fixed column을 유지하고 missing/validity로 상태를 구분한다. exact missing/validity serialization과 final column set은 `OPEN-001`에서 freeze한다.
- F0/F_cal 정의는 보존하고 F1/F2용 feature 배열이나 수식은 이 문서에서 정하지 않는다.

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

### F.3 candidate metadata/관찰 필드 (Patch 4 pre-freeze)

아래 표 순서는 **candidate metadata/header proposal**이다. 모델·코드 hash 같은 run 공통 정보는 manifest에 저장하고 ID로 연결하는 방향을 제안하며, exact Patch 4 열 목록·순서·채택 범위는 `OPEN-001`에서 확정한다.

| 신규 필드 | 확보 방법·정책 |
|---|---|
| `frame_schema_version` | `frames-schema/1.1.0` |
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

candidate frame-row 기본키로 `(analysis_run_id, recording_id, frame_index)`를 제안한다. exact Patch 4 key contract는 `OPEN-001`의 Design Freeze 대상이며, timestamp만으로 유일성을 보장하지 않는 방향은 유지한다. 프레임 timestamp domain을 확인할 수 있으면 analysis manifest의 stream metadata에 기록하고, 확인 불가이면 unknown으로 둔다.

### F.4 hip raw 방향과 arm 선택적 확장 후보 (Patch 4 pre-freeze)

현재 코드의 pose 저장 경로는 shoulder 값을 추출하며, 아래 hip/elbow/wrist 필드는 현재 31개 CSV에 없다. 다음은 **향후 formal canonical writer의 설계**이며 이미 구현·측정되었다는 뜻이 아니다. 현재 `z_face_m/z_lsh_m/z_rsh_m/z_sh_m`은 사용 가능한 기존 원재료다.

| 신규 필드(그룹 내 열 순서) | 단위·의미 | 수집 정책 |
|---|---|---|
| `left_hip_x`, `left_hip_y`, `left_hip_depth`, `left_hip_visibility`, `left_hip_valid`, `left_hip_depth_valid` | 원래 color pixel x/y, aligned depth의 m 단위 거리, 모델 visibility, 2D 좌표 유효 여부, depth 유효 여부 | candidate fields; hip observation 방향은 유지, exact naming/contract는 OPEN-001 |
| `right_hip_x`, `right_hip_y`, `right_hip_depth`, `right_hip_visibility`, `right_hip_valid`, `right_hip_depth_valid` | 위와 동일, 사람 기준 오른쪽 hip | candidate fields; hip observation 방향은 유지, exact naming/contract는 OPEN-001 |
| `left_elbow_x`, `left_elbow_y`, `left_elbow_depth`, `left_elbow_visibility`, `left_elbow_valid`, `left_elbow_depth_valid` | 위와 동일한 좌표·단위·플래그 규약 | optional 원재료 후보 |
| `right_elbow_x`, `right_elbow_y`, `right_elbow_depth`, `right_elbow_visibility`, `right_elbow_valid`, `right_elbow_depth_valid` | 위와 동일 | optional 원재료 후보 |
| `left_wrist_x`, `left_wrist_y`, `left_wrist_depth`, `left_wrist_visibility`, `left_wrist_valid`, `left_wrist_depth_valid` | 위와 동일 | optional 원재료 후보 |
| `right_wrist_x`, `right_wrist_y`, `right_wrist_depth`, `right_wrist_visibility`, `right_wrist_valid`, `right_wrist_depth_valid` | 위와 동일 | optional 원재료 후보 |

- 좌우는 모두 **사람 기준**이다. `*_depth`는 m 단위이며 모델의 정규화 z나 world landmark z와 혼용하지 않는다. 이 필드 자체를 완성된 3D 좌표로 부르지 않는다.
- hip는 핵심 observation 방향이지만, **exact column 의무/field naming/serialization은 OPEN-001**이다. 어떤 계약을 채택하더라도 모든 프레임의 hip non-null을 hard gate로 만드는 방향은 아니다. 가림·화면 밖·depth 누락을 이유로 임의 좌표를 생성하거나 새로운 posture drop 기준을 도입하지 않는다.
- candidate `*_valid` / `*_depth_valid` 의미는 2D 좌표 유효성과 depth 추출 유효성을 분리하는 것이다. exact field 이름과 serialization은 Design Freeze 전 proposal이다. 새로운 visibility 합격 threshold를 여기서 정하지 않는다.
- current proposal은 미검출/부분 depth 실패/비활성화/legacy unknown을 missing과 validity/state로 구분한다. exact missing representation은 `OPEN-001`에서 확정한다.
- analysis manifest의 `processing_settings.raw_observation_groups`에 `hip`, `elbow`, `wrist`별 `enabled / disabled / unknown_legacy`를 기록한다. 사용한 모델의 landmark index mapping·좌우 규약·depth ROI/추출 설정도 기록한다. 구체적인 추가 landmark 매핑은 구현 시 고정 모델 계약과 대조·테스트하며, 이번 문서에서 새 detector나 ROI threshold를 확정하지 않는다.
- 현재 proposal은 optional arm의 **수집 활성화**와 header 예약을 분리하여, disabled일 때 missing과 manifest 상태를 남기는 방식을 제안한다. 그러나 arm을 final Patch 4 header에 `include / reserve / exclude-and-version-later` 중 어떻게 둘지는 `OPEN-001`이며 아직 확정하지 않는다.
- elbow/wrist를 raw observation으로 저장할 경우 이후 오류 분석·ablation뿐 아니라 upper-body skeletal/context representation의 원재료로 재사용할 수 있다는 것이 proposal의 rationale다. 이는 arm field 저장을 이미 확정했다는 뜻이 아니며, primary 5-class classifier의 핵심 feature로도 확정하지 않는다. exact Patch 4 처리와 formal batch 활성화 정책은 `OPEN-001`을 따른다.

전체 face/pose landmark, deprojected 3D 좌표, IR 좌우 영상, 새로운 ROI 품질 통계는 이 schema의 필수 항목으로 추가 확정하지 않는다. 필요한 경우 별도 version으로 확장한다. shoulder/hip가 가려져 관측되지 않는 문제는 실제 수집·장비 validation에서 확인하며 좌표나 depth를 추정 생성하지 않는다.

### F.5 Raw / Derived / Model feature의 세 계층

| 계층 | 내용 | 저장·연결 원칙 |
|---|---|---|
| Canonical raw observations | 얼굴 위치·bbox·landmark polygon 면적, shoulder/hip x/y/depth, visibility/validity 등 관측값 | 측정 좌표계·단위·source와 recording/run/frame 식별자를 보존. 여기서 raw는 raw recording 컨테이너가 아니라 검출·측정 수준의 관찰값을 뜻함 |
| Derived geometry | midpoint, body width, normalized position, 2D/3D vector, angle 등 향후 후보 | 관측값에서 계산하는 별도 계층. geometry 정의/version·입력 hash·같은 frame key로 연결. 이번에 공식·threshold·필수 목록을 정하지 않음 |
| Model feature set | F0 / F_cal / F1 / F2 | 확정된 연구 명세가 관측/derived 값 중 입력을 선택. 선택·순서·정규화·feature version은 이후 별도 계약이며 provenance로 원재료까지 추적 |

hip midpoint와 trunk angle은 hip raw landmark 열이 아니다. 새 derived geometry나 모델용 정규화 값을 canonical raw column에 추가하여 연구 가설과 원재료 계약을 섞지 않는다.

호환성 예외로 기존 31개에는 이미 `theta*_deg`, `face_size_cm2`, `oval_size_cm2`, `ipd_cm`, `box_to_oval` 같은 계산값이 있다. 이들은 **legacy/current 계산 필드**로 명시하여 그대로 보존하고 순수 raw 관찰이라고 재명명하지 않는다. 기존 summary의 reference 기반 파생값도 그대로 보존하되 F1/F2의 필수 입력으로 자동 승계하지 않는다. 신규 derived 산출물의 구체적 파일 형식·수식은 후속 설계 대상으로 남긴다.

기존 `face_area_px`, `oval_area_px`, `oval_size_cm2`, `box_to_oval`은 rectangular bbox와 facial contour/oval representation의 approximation/fidelity를 재검토하는 **secondary exploratory analysis**에 사용할 수 있다. 이 가능성은 새 raw field나 sensor-calibration target을 요구하지 않으며, exact area-error formula·evaluation metric·F1/F2 포함 여부·최종 논문 채택 여부를 확정하지 않는다.

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
- 각 RF 입력 sample은 `recording_id, analysis_run_id, step`, feature mode, calibration/reference step, 입력 frames hash를 추적할 수 있어야 한다. 기존 reference 사용 경로에서 reference는 해당 recording에 속해야 한다. 향후 F1/F2는 `feature_set_id`/정의 version을 별도로 기록하고 개인 reference 필드는 null/not_applicable로 표현한다. 추적성을 위해 F1/F2에도 reference를 강제로 요구하지 않는다.
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

이 절은 Step 1.5 당시의 future implementation plan이다. 현재 operational Patch 번호/순서는 Research Master와 canonical Foundation records가 우선한다.
각 항목의 exact Patch 4 field 계약은 GOV-005/OPEN-001의 pre-freeze status를 따른다.
아래 새 모듈·테스트 이름은 미래 계획이며 이번 Step의 생성 파일이 아니다.

| Patch | 수정/추가 대상 | 하는 일 | 하지 말아야 할 것 | 필요한 테스트 | 예상 위험 |
|---|---|---|---|---|---|
| 1. ID·artifact 계약 | 작은 `data_provenance.py`, 전용 테스트 | ID 발급·충돌 거부·schema/version·hash 유틸, legacy crosswalk 규약 | capture/RF 동작 변경, 전체 pipeline 재구성 | 동시/동일 timestamp ID, 기존 경로 overwrite 금지, hash·timezone·unknown | filename parser와 ID 길이, 대용량 hash 비용 |
| 2. capture metadata | `capture_d455.py`, provenance 테스트 | ID를 raw/metadata/markers/samples에 전파, protocol/code/settings 기록 | streams·시간·label·depth 계산·기존 CSV 열 의미 변경 | 기존 열/값 보존, 실패 시도 ID, dirty code hash, fallback 형식 동일 ID | 중단 시 metadata 미완성, 기존 flat 파일 소비자 |
| 3. gate evidence | `capture_d455.py`, `test_capture_protocol.py` | 기존 final gate 계산 근거를 quality에 추가 | threshold·window·median·face 비율·shoulder gate 변경 | pass/fail 값 동일, 정확한 counts/분모, 부족 시 null, 최신 upright 사용 | 진단 재계산과 실제 판정의 불일치 |
| 4. 모델 lock·analysis run | `analyze_d455.py`, 분석 provenance 테스트 | 고정 모델 hash 검증, run manifest·고유 출력 경로 | 다른 모델로 조용히 교체, 추출 옵션/trim 변경 | cached model 검증, hash mismatch, run overwrite 금지, from-csv parent 표기 | 기존 모델 정체 불명, 라이브러리 버전 차이 |
| 5a. canonical frames 기반 | `analyze_d455.py`, frame schema 테스트 | 기존 31개 값 보존 + fixed-header candidate + metadata/source 플래그 + F.4 arm-handling proposal | F1/F2 구현, 새 confidence/depth drop 조건 | 검출 누락에도 header 고정 방향, 기존 값 동일, 사람/화면 좌우, timestamp 두 종류 | 검출 실패와 unknown 혼동, RGB/depth 대응; exact header/arm contract는 OPEN-001, hip 구현 전 formal schema 완성으로 간주 금지 |
| 5b. body raw observations | `analyze_d455.py`, landmark/schema 전용 테스트 | hip 관찰 추출, 선택적 elbow/wrist 추출·상태 기록; 모델 mapping과 기존 depth 추출 정책 대조 | midpoint/trunk angle/feature 구현, 기존 31개 재계산 변경, 새 shoulder/hip 촬영 gate | 좌우·pixel/m 단위, 화면 밖·가림·미검출·depth 결측, optional 비활성화에도 동일 header, 기존 row/값 보존 | hip 가시성·edge depth 불안정, 모델 좌표와 센서 depth 혼동 |
| 6. summary·legacy | `analyze_d455.py`, summary/legacy 테스트 | recording/run 단위 grouping와 reference 격리, legacy 명시적 import | 직전 upright를 첫 upright로 교체, 기존 FEATS 통계 변경 | 두 retake 절대 병합 금지, 두 run 분리, 기존 단일 take 수치 동일 | 기존 오병합 결과와의 차이, from-csv lineage 누락 |
| 7. manifest 선택·RF 연결 | 선택 도구/manifest validator, `rf_experiment.py` 입력·출력부, 전용 테스트 | 선택 이력·snapshot, RF 병렬 lineage와 실행 디렉터리 | Tree/Forest/weight/λ/feature/평가 마스크 변경, root stats 변경 | 중복 선택 거부, seed/fold 불변, 기존 prediction/metrics 동일, 결과→raw 추적 | sample 순서·LOSO 그룹·relative reference의 우발 변경 |
| 8. 무결성·통합 검증 | `check_recording.py`, 통합 테스트, 운영 절차 | artifact/marker 연결과 run 완결성 검증, 실제 카메라 smoke test | 추가 검사 결과로 과거 데이터 자동 삭제, 새 연구 acceptance 조건 암묵 도입 | raw+sidecar mismatch, 실패 run 배제, end-to-end lineage, 전체 기존 unittest | 실제 SDK/장치 차이, EOF와 재생 실패 구분 |

테스트가 쓰는 synthetic 수치는 구조 검증용이다. 실제 연구 정확도나 과거 root 비율 재현을 목표로 하지 않는다. 정식 수집 전에는 사람에 의한 D455/GUI smoke test와 실제 artifact 확인이 필요하다.

기존 patch 5를 5a/5b로 분리하여 raw 확장이 provenance·header 변경과 독립적으로 검토되게 한다. M절의 장비 validation 계획 확정과 측정은 formal 수집 전 별도 작업이다. 이 구현 순서에 F1/F2 feature 구현이나 RF 성능 실험을 포함하지 않는다.

## L. 확정 방향과 아직 연구 결정이 필요한 사항

현재 구현 여부와 설계 방향을 구분한다. ID·role·provenance 등 이미 구현된 부분은 Git/source/test 및 canonical Foundation records로 확인한다.
Step 1.5에서 확정 방향으로 유지하는 것은 feature 역할 분리, F1/F2의 zero-personal-calibration, raw/derived/model 계층 분리, head/shoulder/hip 관찰 필요성 같은 **연구/데이터 방향**이다.
반면 fixed raw writer의 exact version/header/field/missing/arm 계약은 GOV-005/OPEN-001에 따라 Patch 4 pre-freeze proposal이며, 이 문서의 과거 `확정` 표현만으로 final contract가 되지 않는다.

다음은 구현자가 임의 결정하지 않는다.

1. **F1/F2의 구체적 수식·입력 차원·missing 처리·derived geometry 계약**. F0의 기존 baseline과 F_cal의 relative 비교 역할은 보존한다. 현재 all/invariant/relative를 이름만 바꿔 F1/F2로 간주하지 않는다. 6개 초과 weight 정책도 별도 연구 결정이다.
2. formal/external의 모집·조건·반복측정 단위와 허용 촬영 회수, `ok_with_warnings`의 eligibility, 기술적 예외 승인자. 수집 전에 H의 selection policy를 완성한다.
3. 실제 고정할 MediaPipe 모델 artifact/hash 및 환경 조합. 현재 로컬에 없거나 확인하지 않은 파일의 버전을 추정하지 않는다.
4. face/head·shoulder·hip를 F1/F2에 필요한 핵심 observation 방향으로 유지한다. elbow/wrist는 upper-body skeletal/context representation에 유용한 추가 candidate raw observation이지만, exact `include / reserve / exclude-and-version-later`는 Patch 4 Design Freeze에서 결정한다. hip의 exact field naming/depth extraction/missing contract도 같은 freeze 대상이다. 그 밖의 전체 landmark·3D·IR 저장 필요성도 자동 확장하지 않는다.
5. F1/F2의 개인 사전 calibration 불필요 원칙은 확정 방향이다. 현재 capture/summary의 직전 upright와 기존 RF의 첫 upright 정책은 비교 경로에서 보존하며 통일하지 않는다. 연구자는 최종 feature 경로에 reference 의존성이 없는지 검증할 계획을 정한다.
6. M절 장비 validation의 거리·반복 수·landmark/depth/3D geometry 안정성 metric·오차/변동 산출법·허용 기준, hip를 관측할 실제 구도. 실제 결과 없이 범위 적합성이나 fallback 필요성을 확정하지 않는다.

이 명세는 기존 데이터나 성능 결과를 재해석하는 승인이 아니다. 이후 구현에서도 소스 변경 범위와 검증 결과를 보고하며 자동 commit/push는 하지 않는다.

## M. D455 operating range와 장비 validation

### M.1 실제 protocol 조건에서 확인할 항목

현재 설정은 color **1280×720**, depth **848×480**, **15 FPS**이며 초기 착석 안내 범위는 **0.70~0.80 m**, forward face 이동 gate는 기준 대비 **0.08~0.12 m**다. 초기 안내의 body fallback 가능성과 face-only forward reference는 구분한다. 따라서 이 설정만으로 모든 face/shoulder/hip의 실제 센서 거리를 단정하지 않고 capture evidence와 분석 관측값으로 확인한다.

다른 팀의 근거리 depth 문제 의견은 확인해야 할 가설이다. **40 cm fallback이나 새로운 거리 보정 규칙을 즉시 설계·추가하지 않는다.**
formal operating range는 특정 논문 한 편의 거리값을 그대로 채택하지 않고, 관련 literature/ergonomics/D455 특성으로 candidate range를 만든 뒤 실제 센서 validation 결과로 freeze한다.
formal experiment 전에 별도 validation으로 다음을 확인한다.

| 항목 | 기록·해석 원칙 |
|---|---|
| 실제 사용 거리 범위 | upright와 forward 자세에서 관측된 face/shoulder/hip 거리 및 camera 배치·시야를 기록. 초기 안내값으로 대체하지 않음 |
| depth valid rate | 센서 depth 유효률과 landmark 위치의 depth 획득률을 구분. ROI·유효 정의·분자/분모·frame window를 명시 |
| depth measurement variation | 같은 배치·거리에서 반복 측정 변동을 기록. 사람 움직임과 장비 반복성을 구분하여 조건을 명시 |
| face/shoulder/hip 획득률 | 2D landmark 검출, visibility, 유효 depth, 둘 다 사용 가능한 비율을 구분. 가림·화면 밖·landmark 위치의 depth 누락을 기록 |
| landmark/depth 결합 안정성 | RGB landmark 위치와 aligned depth를 결합했을 때의 반복성·유효성을 실제 profile·align·ROI 조건과 함께 기록 |
| 3D geometry repeatability | 같은 조건에서 head/shoulder/hip 기반 derived 3D geometry의 반복 변동을 기록. exact geometry/metric은 사전 계획에서 결정 |
| distance-dependent feature stability | candidate operating range 내 거리 변화에 따라 landmark/depth/derived geometry가 어떻게 변하는지 기록. formal feature acceptance 기준은 별도 결정 |

위 비율은 새로운 sample drop 또는 acceptance threshold가 아니다. 허용 오차와 기준은 측정 계획에서 사전에 정하고, 확인된 문제가 있으면 별도 연구·protocol 변경으로 검토한다. 현재 8~12 cm face-only gate, 일반 body fallback, depth 계산, shoulder hard gate 미도입은 유지한다.

### M.2 별도 camera validation experiment 후보

- **70 / 80 / 90 cm** 등을 거리 후보로 검토하되 확정된 테스트 grid나 적합 범위로 간주하지 않는다. 실제 forward 자세에서 접근하는 거리와 shoulder/hip의 거리도 포함되도록 계획을 결정한다.
- 실제 사용 거리에서 landmark acquisition stability, head/shoulder/hip depth valid rate, depth repeatability/jitter, 3D geometry repeatability를 반복 측정할 수 있도록 조건을 사전 정의한다.
- RGB landmark와 aligned depth의 결합 안정성, 그리고 거리 변화에 따른 candidate geometry/feature stability를 별도 항목으로 기록한다. exact metric·threshold·반복 수는 현재 확정하지 않는다.
- 현재 해상도와 15 FPS 조건에서 먼저 검증하도록 계획한다. 다른 설정 비교는 승인된 별도 validation 조건이며 formal 촬영 설정을 조용히 바꾸지 않는다.
- 장치 serial/firmware, intrinsics/extrinsics, depth scale, 코드·모델 hash, 실제 profile, 거리 기준, 반복 조건과 입력 artifact를 provenance에 남긴다. 기존 posture sequence/label에 장비 검증 단계를 끼워 넣지 않고 별도 validation 계획·실행으로 식별한다.

교수 피드백의 "십자가 / 졸라맨"을 checkerboard/cross/known-target calibration 요구로 해석하지 않는다. 해당 피드백의 주된 의미는 사람의 주요 관절점을 연결한 upper-body skeletal representation을 자세 판단에 활용하라는 방향으로 정정한다. 또한 "edge / 면적 / pixel / segment" 취지는 기존 face bbox와 contour/oval 표현의 approximation/fidelity를 재검토하는 secondary analysis 후보에 더 가깝다.

이것은 **장비의 측정 특성을 검증하는 실험**이지 참가자별 올바른 자세를 먼저 학습하는 calibration이 아니다. F1/F2 inference에 개인별 사전 촬영을 요구하는 근거로 사용하지 않는다. 이번 Step 1.5에서는 측정 실험을 실행하지 않았고 성능·오차·거리 적합성 결과를 제시하지 않는다.

## N. Step 1.5 변경 영향 및 후속 결정

1. **기존 31개 field 의미 변경: 없음.** 이름·단위·계산·누락 처리의 기존 동작은 보존 대상이다. legacy/current 계산 필드를 raw와 구분해서 설명했으며 삭제·재계산하지 않는다. 기존 summary와 RF/WRF 및 M0/M1/M2 비교도 유지한다.
2. **신규 canonical raw 후보**: 좌우 hip x/y/depth/visibility 및 2D/depth validity candidate를 설계했고, elbow/wrist도 upper-body skeletal/context representation에 활용 가능한 optional candidate로 기술했다. 이 exact field naming/count/order는 Patch 4 pre-freeze proposal이다. raw landmark 관찰과 derived skeletal/body geometry, 최종 model feature 선택을 분리하며 hip midpoint·trunk angle 등은 derived 계층으로 남긴다.
3. **Mandatory / optional status**: 기존 값 의미 보존과 head/shoulder/hip 관찰 필요성은 방향으로 유지한다. 그러나 formal Patch 4 header의 exact metadata/hip/arm 열 계약, arm 예약 여부, boolean/missing serialization은 `OPEN-001`이 닫히기 전 final mandatory contract가 아니다. legacy 미확인 metadata는 기존 unknown 원칙을 유지한다.
4. **P01/P02 compatibility**: 기존 pilot 원본·CSV·수치·legacy ID mapping을 유지한다. 새 hip/arm 값이 없으면 missing이며 임의 복원하거나 formal로 승격하지 않는다. 필요 시 raw를 새 analysis run으로 재분석할 수 있으나 이번에는 실행하지 않는다.
5. **후속 코드 patch 대상**: K의 1~4 provenance 기반 작업 후 `analyze_d455.py`의 5a 고정 schema, 5b hip/optional arm 관찰을 분리한다. 이후 `analyze_d455.py` summary/legacy, `rf_experiment.py` 입력·출력 lineage, `check_recording.py` schema·연결 검증으로 이어간다. `capture_d455.py`는 예정된 ID/metadata/evidence 관찰 기록만 대상이며 face-only gate를 바꾸지 않는다. 전용 테스트는 각 후속 patch에서 작성한다.
6. **F1/F2 미확정 범위**: calibration-free 2D upper-body skeletal/body-relative geometry와 RGB-D·metric 3D/sagittal candidate family라는 방향만 명시한다. head-forward relative to trunk / whole-trunk-forward / whole-body translation confounder를 분석하되, exact landmark set·graph/edge·수식·feature 개수·trunk-axis/angle 공식·projection·normalization·selection·threshold·성능은 확정하거나 추정하지 않는다. 정면 D455 proxy를 actual spine angle로 주장하지 않는다. 새로운 arm feature나 40 cm fallback도 정의하지 않는다.
7. **연구자 결정 사항**: 정확한 F1/F2·derived 계약과 결측 처리, Patch 4 arm include/reserve/exclude, 고정 모델/환경, 장비 validation의 literature-informed candidate range·거리 grid·반복·landmark/depth/3D-repeatability/RGB-depth coupling/distance-stability metric·허용 기준, hip 관측 가능 구도, 기존 selection policy의 warnings·재촬영·승인 기준을 후속 확정한다. bbox-vs-contour/oval의 exact error metric과 최종 연구 채택 여부도 deferred 상태다. 개인 사전 calibration을 최종 방법의 필수 조건으로 되돌리는 것은 미결정 항목이 아니다.
8. **기존 provenance 유지**: recording_id, analysis_run_id, dataset_role, protocol_version, git/file/model hash, selection manifest·이력, legacy pilot mapping, raw→frames→summary 및 raw→frames→RF traceability를 삭제·단순화하지 않았다. 문서/schema 설계 version 변경은 기존 촬영 protocol 변경을 의미하지 않는다.

2026-09-30 Step 1.5 원작성 당시 수정 대상은 `RESEARCH_DATA_SCHEMA.md` 한 파일이었다. 당시 Python 소스·테스트·데이터 변경, 새 파일 생성, F1/F2 구현, RF 실험, commit/push는 수행하지 않았다. 2026-10-01 canonicalization amendment는 GOV-005/OPEN-001 status/authority 정합화이며 field/data contract 또는 capture protocol을 새로 freeze하지 않는다.
