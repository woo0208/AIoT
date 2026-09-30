# PATCH_03 — Analysis Provenance

> 상태: **소급 복원(Retrospective Reconstruction), 최종 후보 v2 (Final Candidate v2)**
>
> v2 반영: **2026-10-01 Claude READ-ONLY 1차 검토 Finding 1~7 반영. Targeted 재검토 전 상태.**
>
> 운영상 Patch 번호: **Foundation Patch 3**
>
> 최종 관련 commit:
>
> ```text
> 1cdc52831cfb66b901db58279caf3e777a354546
> feat: add verified analysis provenance tracking
> ```
>
> parent:
>
> ```text
> a262c6d87366ccb4af50cda3f80a4c3ac94d0bda
> feat: record forward gate evidence
> ```
>
> commit timestamp:
>
> ```text
> 2026-09-30T22:54:17+09:00
> ```
>
> 작성 목적: `analyze_d455.py`의 각 분석 실행에 고유 `analysis_run_id`와
> 입력·코드·환경·모델·처리 설정·출력 lineage를 부여하고,
> modern provenance-aware 입력과 legacy pilot 입력을 명시적으로 구분하도록 만든
> Foundation Patch 3의 목적, 구현, 검증, 독립 리뷰 이력을 복원한다.

---

# 1. 이 Patch의 위치

Foundation 흐름:

```text
FOUNDATION_PRELUDE_00
알고리즘·평가·촬영 hardening
        ↓
PATCH 1
capture recording provenance
        ↓
PATCH 2
forward gate evidence
        ↓
PATCH 3  ← 이 문서
analysis provenance
        ↓
PATCH 4
canonical fixed frame schema + hip
```

Patch 1이:

> **“이 촬영본은 무엇인가?”**

를 해결했다면,

Patch 3은:

> **“이 분석 결과는 어떤 촬영본을, 어떤 코드·환경·모델·옵션으로 분석해서 만든 것인가?”**

를 해결한다.

---

# 2. 복원에 사용한 증거 수준

본 문서는 다음 표기를 사용한다.

### `[GIT-VERIFIED]`

commit `1cdc528`의 실제 source tree / diff에서 확인.

### `[TEST-VERIFIED]`

commit `1cdc528`를 detached worktree로 checkout하여
현재 복원 과정에서 테스트를 재실행해 확인.

### `[SCHEMA-VERIFIED]`

당시 `RESEARCH_DATA_SCHEMA.md`의 analysis provenance 계약에서 확인.

### `[CHAT-RECONSTRUCTED]`

당시 Codex/Claude 작업·리뷰 대화에서 복원.

### `[UNKNOWN]`

현재 확보된 증거로는 확정할 수 없는 사항.

---

# 3. Patch 전 문제

Patch 2까지는 촬영 단계에:

```text
recording_id
dataset_role
protocol_version
capture code provenance
forward gate evidence
```

가 존재했다.

하지만 분석 후 생성되는:

```text
*_frames.csv
summary_steps.csv
summary_report.txt
plots
```

만 보면 다음 질문에 충분히 답할 수 없었다.

```text
이 CSV는 정확히 어떤 recording에서 나왔는가?
같은 recording을 몇 번째 분석한 결과인가?
어떤 analyze_d455.py byte를 사용했는가?
Git HEAD와 dirty 상태는 무엇이었는가?
어떤 MediaPipe model file을 실제로 사용했는가?
model file의 SHA-256은 무엇인가?
--step은 요청값과 실제 적용값이 무엇이었는가?
ROI / trim / depth valid 규칙은 무엇이었는가?
raw에서 새로 inference한 것인가?
아니면 기존 frames.csv를 다시 요약한 것인가?
실패한 분석을 completed 결과로 오인할 가능성은 없는가?
```

따라서 capture provenance만으로는
최종 분석 결과의 재현성과 lineage가 충분하지 않았다.

---

# 4. Patch 3 핵심 목표

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

Patch 3의 실제 목표는 다음과 같이 정리된다.

```text
1. 분석 실행마다 새로운 analysis_run_id 발급
2. recording_id와 analysis_run_id를 분리
3. raw 분석과 --from-csv 재요약을 명확히 구분
4. 입력 artifact를 full SHA-256으로 기록
5. capture / markers / quality identity를 교차검증
6. 분석 코드 Git/hash와 runtime environment 기록
7. MediaPipe model artifact 실제 hash 기록
8. 실제 processing settings snapshot 기록
9. 분석 출력 artifact를 run별로 보존
10. manifest를 running/completed/failed 상태로 관리
11. legacy 입력을 modern provenance로 가장하지 않음
12. legacy 사용은 명시적 --legacy-pilot opt-in으로 제한
13. 기존 수치 계산과 기존 flat output 호환성을 최대한 보존
```

---

# 5. 변경 파일

`[GIT-VERIFIED]`

commit `1cdc528`에서 변경된 파일:

```text
analyze_d455.py
test_analysis_provenance.py
```

Git stat:

```text
2 files changed
1317 insertions(+)
47 deletions(-)
```

세부 numstat:

```text
analyze_d455.py             +538 / -47
test_analysis_provenance.py +779 / -0
```

다음은 이 commit에서 변경하지 않았다.

```text
capture_d455.py
rf_experiment.py
기존 RF model definition
기존 capture gate
```

---

# 6. `analysis_run_id`

## 형식

`[GIT-VERIFIED]`

각 분석 실행마다:

```text
ar_<UTC timestamp>_<UUID32>
```

형식의 새 ID를 생성한다.

예:

```text
ar_20261001T000000000000Z_<32hex>
```

함수:

```python
def new_analysis_id():
    return f"ar_{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}"
```

---

## recording_id와의 차이

동일 raw recording을 두 번 분석하면:

```text
recording_id
= 동일

analysis_run_id
= 매번 새 값
```

이다.

즉:

```text
recording_id
= 촬영 시도의 identity

analysis_run_id
= 분석 실행의 identity
```

로 분리한다.

---

# 7. 분석 출력 디렉터리

`[GIT-VERIFIED]`

run별 출력 기본 구조:

```text
analysis/
└── <recording_id>/
    └── <analysis_run_id>/
        ├── analysis_manifest.json
        └── run별 archive output
```

batch 공통 출력은:

```text
analysis/
└── batches/
    └── <analysis_batch_id>/
        ├── analysis_batch.json
        ├── summary_steps.csv
        ├── summary_report.txt
        └── plots...
```

에 저장한다.

기존 consumer 호환을 위해
`analysis/` 최상위 flat output도 계속 제공한다.

원칙:

```text
per-run / per-batch archive
= provenance 보존용

flat output
= 기존 workflow 호환용
```

이다.

---

# 8. `analysis_manifest.json`

`[GIT-VERIFIED]`

manifest schema:

```text
analysis-provenance/1.0.0
```

주요 field:

```text
schema_version
analysis_run_id
analysis_batch_id
recording_id
analysis_mode
parent_analysis_run_id
dataset_role
protocol_version
legacy_input
identity_status

started_at
ended_at
status

inputs
code
environment
models
inference_performed
options
processing_settings
playback_calibration
outputs
errors
provenance_unknown_reasons
```

---

# 9. Analysis Mode

Patch 3는 두 경로를 명확하게 구분한다.

## Raw extraction

```text
analysis_mode = extract_raw
```

흐름:

```text
.bag / .db3
→ MediaPipe inference
→ frames.csv
→ summary / report / plot
```

---

## Existing frames re-summary

```text
analysis_mode = summarize_existing_frames
```

CLI:

```bash
python analyze_d455.py ... --from-csv
```

흐름:

```text
기존 verified frames.csv
→ 새 analysis run
→ summary / report / plot
```

이 경우 새 MediaPipe inference를 수행한 것처럼 기록하지 않는다.

---

# 10. Raw Input Artifact Provenance

`[GIT-VERIFIED]`

raw 분석 시 최소 다음 입력을 확인한다.

```text
recording
capture_metadata
markers
quality
```

각 artifact에 대해 가능한 경우:

```text
filename
absolute path
size_bytes
mtime_ns
sha256
hash_status
```

를 기록한다.

SHA-256은:

```text
전체 파일 streaming read
```

로 계산한다.

size/mtime를 content hash 대신 사용하지 않는다.

---

# 11. Hash 중 파일 변경 감지

`[GIT-VERIFIED]`

`artifact_info()`는:

```text
hash 전 stat
→ full streaming SHA-256
→ hash 후 stat
```

을 비교한다.

hashing 중:

```text
size
mtime_ns
```

가 변경되면:

```text
file changed while hashing
```

으로 취급한다.

즉 불완전한 hash를 complete SHA-256으로 가장하지 않는다.

---

# 12. Capture / Markers / Quality Identity 검증

`[GIT-VERIFIED]`

raw 분석 시:

```text
camera.json recording_id
markers.csv recording_id
quality.json recording_id
```

을 실제 파일에서 읽는다.

non-empty ID가 둘 이상 존재하며 서로 다르면:

```text
ValueError:
capture/markers/quality recording_id mismatch
```

로 거부한다.

---

# 13. Patch 3.1 — Claude Review에서 발견된 Lineage Bug

`[CHAT-RECONSTRUCTED]`

초기 Patch 3 구현 후
Claude 독립 READ-ONLY review에서 중요한 문제가 발견됐다.

대표 상황:

```text
camera.json recording_id = A
markers.csv recording_id = B
```

인데,
초기 구현이 실제 markers CSV의 ID를 검증하지 않고
capture의 A를 markers identity처럼 기록할 수 있는 경로가 있었다.

이 경우:

> **다른 recording의 posture marker file이 잘못 결합되어도 정상 provenance처럼 보일 수 있음**

이 문제는 독립 리뷰에서 **B1** 수준의 핵심 문제로 다뤄졌다.

초기 review 판정:

```text
FIX BEFORE COMMIT
```

으로 복원된다.

---

# 14. Patch 3.1 수정 — 실제 Sidecar ID 관찰

`[GIT-VERIFIED + CHAT-RECONSTRUCTED]`

최종 구현에서는:

```python
csv_identity()
json_identity()
```

가 **파일 내부에 실제 존재하는 ID만** 읽는다.

중요한 원칙:

> **없는 ID를 capture metadata 값으로 임의 보완하지 않는다.**

markers CSV의 경우:

```text
ID column 없음
→ legacy_no_id_column

ID column은 있으나 non-empty 값 없음
→ empty_id_column

1개의 일관된 ID
→ verified

2개 이상의 서로 다른 non-empty ID
→ error
```

로 구분한다.

quality JSON도:

```text
실제 recording_id field
```

만 관찰한다.

---

# 15. Modern Input의 Silent Legacy Downgrade 방지

`[CHAT-RECONSTRUCTED]`

초기 review에서 **I1**로 지적된 또 다른 문제는:

> provenance-aware modern input이 불완전할 때
> 이를 legacy로 조용히 낮춰 받아들이면 안 된다.

는 점이었다.

예:

```text
modern filename 형식인데 camera metadata가 없음
markers에 recording_id 흔적이 있음
capture-provenance schema 흔적이 있음
formal/external role 흔적이 있음
```

같은 경우를:

```text
"옛날 파일인가 보다"
```

라고 자동 처리하면
provenance 손실을 정상 상태로 숨기게 된다.

---

# 16. Modern Raw Downgrade 방지

`[GIT-VERIFIED]`

다음 modern evidence가 하나라도 있으면,
capture `recording_id`가 빠진 raw를 legacy로 자동 취급하지 않는다.

대표 조건:

```text
modern recording filename
sidecar에서 관찰된 recording_id
camera JSON에 recording_id key 존재
capture-provenance schema
modern protocol_version
formal/external dataset_role
markers에 ID column 존재
```

이 경우:

```text
new recording requires capture metadata recording_id;
legacy downgrade forbidden
```

으로 거부한다.

---

# 17. Explicit `--legacy-pilot` — Patch 3.2

`[CHAT-RECONSTRUCTED]`

review/fix를 진행하면서
legacy input을 자동 수용하는 대신:

```text
--legacy-pilot
```

을 **명시적 opt-in**으로 요구하는 방향으로 확정했다.

이 단계는 대화상:

```text
Patch 3.2
```

로 관리되었다.

별도 Git commit으로 나뉜 것이 아니라,
최종 `1cdc528` commit 안에 합쳐진 상태다.

---

# 18. Legacy Raw 정책

`[GIT-VERIFIED]`

legacy raw가 다음 조건을 만족하면:

```text
modern provenance evidence 없음
+
--legacy-pilot 명시
```

분석을 허용한다.

legacy identity는:

```text
legacy_<sanitized stem>_<SHA-256 prefix>
```

형태로 만든다.

충돌 시 full SHA-256까지 확장할 수 있다.

그리고:

```text
dataset_role = pilot
protocol_version = unknown_legacy
historical_provenance = unknown
```

으로 기록한다.

중요:

> 과거 provenance를 알 수 없는데 아는 것처럼 채우지 않는다.

---

# 19. Legacy CSV 정책

`[GIT-VERIFIED]`

provenance sidecar가 없는 old frames CSV도
자동 수용하지 않는다.

명시적으로:

```bash
--from-csv --legacy-pilot
```

이 필요하다.

legacy CSV identity:

```text
legacy_csv_<sanitized stem>_<SHA-256 prefix>
```

형태다.

parent analysis run을 알 수 없으므로:

```text
parent_analysis_run_id = null
```

이며,
unknown reason을 기록한다.

---

# 20. `--legacy-pilot`의 제한

`[GIT-VERIFIED]`

`--legacy-pilot`을 줬다고 해서
modern provenance 문제를 우회할 수는 없다.

특히:

```text
formal
external
```

role과 legacy flag가 충돌하면 거부한다.

또:

```text
modern frame identity column 존재
modern managed output 흔적 존재
modern parent sidecar가 깨짐
```

상태도 legacy opt-in으로 우회할 수 없다.

즉:

> `--legacy-pilot`은 provenance 손상을 무시하는 escape hatch가 아니라,
> **진짜 old pilot input을 명시적으로 인정하는 옵션**

이다.

---

# 21. Formal Input Hash 요구

`[GIT-VERIFIED]`

raw 분석(`extract_raw`) 경로에서 dataset role이:

```text
formal
```

이면 최소:

```text
recording
markers
```

의 complete SHA-256을 요구한다.

둘 중 hash가 없으면:

```text
formal input requires full recording/markers hashes
```

로 거부한다.

`--from-csv` 경로에는 이 raw-input hash rule을 그대로 적용하지 않는다.
그 경로는 parent analysis manifest/status, source frames membership와 SHA-256 등
**parent lineage 검증**으로 입력 정합성을 확인한다.

---

# 22. 동일 recording_id의 Raw Content 불변성

`[GIT-VERIFIED]`

같은 `recording_id` 아래
이전 analysis manifest가 존재하면
그때의 raw SHA-256과 현재 raw SHA-256을 비교한다.

다르면:

```text
same recording_id has different raw content
```

으로 거부한다.

즉:

```text
동일 recording_id
≠
서로 다른 raw bytes 허용
```

이다.

---

# 23. `--from-csv` Parent Verification

`[GIT-VERIFIED]`

modern frames CSV를 `--from-csv`로 재요약할 때는
다음 sidecar를 사용한다.

```text
<frames.csv>.provenance.json
```

검증 흐름:

```text
frames.csv SHA-256
        ↓
provenance sidecar의 frames_sha256과 비교
        ↓
parent analysis_manifest 경로 확인
        ↓
parent manifest SHA-256 검증
        ↓
parent status == completed 확인
        ↓
recording_id / analysis_run_id 연결 확인
        ↓
frames가 parent outputs에 실제 등록되었는지 확인
```

하나라도 맞지 않으면 거부한다.

---

# 24. Frame Row Identity 교차검증

`[GIT-VERIFIED]`

frames CSV에 이미:

```text
recording_id
analysis_run_id
```

column이 존재하는 경우,
그 값이 parent manifest와 다르면:

```text
frames/parent identity mismatch
```

로 거부한다.

Patch 3 시점의 legacy 31-column CSV에는
이 column이 없을 수 있으므로
없는 경우 자체는 별도로 취급한다.

향후 Patch 4 fixed schema에서
frame-level ID를 항상 포함시키는 기반이 된다.

---

# 25. Parent Output Membership 검증

`[GIT-VERIFIED]`

단순히 SHA-256이 같은 파일이라는 이유만으로
parent output으로 인정하지 않는다.

parent manifest `outputs[]`에:

```text
kind == frames
sha256 일치
filename 일치
```

하는 entry가 실제로 있어야 한다.

따라서:

> 동일 bytes를 다른 이름으로 복사했다고 해서
> 자동으로 그 parent의 공식 frames output이 되지 않는다.

---

# 26. Analysis Code Provenance

`[GIT-VERIFIED]`

manifest `code`에는:

```text
git_commit
git_dirty
analyze_script_sha256
path
```

를 기록한다.

Git 조회:

```bash
git rev-parse HEAD
git status --porcelain --untracked-files=normal
```

실제 `analyze_d455.py`는
byte-level SHA-256으로 기록한다.

Git 정보 조회 실패는
분석 전체를 무조건 중단하지 않고:

```text
null
+
provenance_unknown_reasons
```

에 이유를 남긴다.

---

# 27. Environment Provenance

`[GIT-VERIFIED]`

가능한 경우 다음 runtime 정보를 기록한다.

```text
Python
OS
architecture
mediapipe
pyrealsense2
opencv-python
numpy
matplotlib
```

version lookup 실패 시:

```text
null
+
unknown reason
```

으로 남긴다.

---

# 28. MediaPipe Model Artifact Provenance

`[GIT-VERIFIED]`

raw inference 시 사용 가능한 model role:

```text
face
mesh
pose
```

각 model에 대해:

```text
role
filename
path
size_bytes
mtime_ns
sha256
hash_status
source_url
source_url_kind
version_identifier
used_in_this_run
```

을 기록한다.

중요:

```text
URL만 기록
```

하는 것이 아니라,

> **실제로 filesystem에 존재하는 model artifact의 SHA-256**

을 기록한다.

---

# 29. Model 사용 여부

`[GIT-VERIFIED]`

model file이 존재한다는 것과
그 run에서 실제 inference에 사용했다는 것은 다르다.

따라서:

```text
used_in_this_run
inference_performed
```

를 별도로 기록한다.

실제 detector가 실행될 때
해당 model role을 used로 표시한다.

---

# 30. `--from-csv`에서는 Model 사용을 가장하지 않음

`[GIT-VERIFIED]`

`--from-csv`는 새 inference가 아니다.

따라서 parent run의 model provenance를 참조하더라도:

```text
used_in_this_run = false
```

로 복사한다.

또:

```text
source_analysis_run_id
```

를 통해 어느 parent run의 model provenance인지 남긴다.

즉 현재 설치된 model을 사용해
새로 inference한 것처럼 기록하지 않는다.

---

# 31. Model Lock은 아직 아님

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

Patch 3은:

```text
실제 model SHA-256 기록
```

까지 수행한다.

하지만 model URL은 여전히:

```text
.../latest/...
```

형태이고,

```text
허용 hash 목록과 강제 대조
```

는 아직 구현되지 않았다.

따라서:

```text
Model provenance recording  ✅
Model artifact lock         ❌
```

이다.

정식 formal data 분석 전에
별도 Foundation 작업으로 model lock이 필요하다.

현재 roadmap에서는 이를:

```text
Foundation Patch 4.5 — MediaPipe Model Artifact Lock
```

으로 명시적으로 분리한다.

---

# 32. Existing Model File 보존

`[GIT-VERIFIED]`

model file이 이미 존재하면
무조건 다시 다운로드하거나 덮어쓰지 않는다.

따라서:

```text
실제 사용 artifact
```

를 hash해서 기록할 수 있다.

---

# 33. Processing Settings — Review I2

`[CHAT-RECONSTRUCTED]`

초기 독립 review에서 **I2**로:

> 분석 결과에 영향을 줄 수 있는 실제 processing option snapshot이 충분하지 않다.

는 문제가 지적됐다.

최종 Patch 3에서는
현재 raw extraction에 영향을 주는 주요 설정을 manifest에 기록한다.

---

# 34. `processing_settings`

`[GIT-VERIFIED]`

raw extraction mode에서 최소 다음을 기록한다.

```text
raw_extraction_applied

trim_start_s
trim_end_s

depth_alignment_target

face_oval_indices
iris_indices
shoulder_indices

task options:
- face
- mesh
- pose

depth ROI:
- face bbox fraction
- oval center half-width
- shoulder half-width
- min valid pixels
- valid depth rule
- bounds rule
- reduction

face_selection
face_depth_fallback
shoulder_depth_reduction
video_timestamp_rule
```

또한:

```text
BOUNDARY_DELTA_PX
```

도 snapshot한다.

---

# 35. Runtime Task Option 기록

`[GIT-VERIFIED]`

실제 MediaPipe option object에서 가능한 항목을 다시 읽어:

```text
running_mode
min_detection_confidence
num_faces
num_poses
...
```

를 기록한다.

즉 단순히 개발자가 생각한 설정이 아니라
runtime option에 존재하는 실제 값을
manifest에 반영하도록 했다.

---

# 36. Playback Calibration

`[GIT-VERIFIED]`

raw playback 중 실제 구현에서 기록하는 값은:

```text
depth_scale_m
color_intrinsics
  - width
  - height
  - fx
  - fy
  - ppx
  - ppy
  - model
  - coeffs
```

이다.

이 값을 capture metadata와 별도로 기록하여:

```text
capture 시 기록값
≠
analysis playback에서 실제 관찰한 값
```

을 구분한다.

현재 Patch 3 구현은 **playback depth intrinsics와 depth-to-color extrinsics를
analysis manifest에 기록하지 않는다.**
따라서 이 두 항목은 구현 완료로 주장하지 않으며, 필요 시 후속 provenance 확장 대상으로 남긴다.

---

# 37. 기존 수치 계산 보존

`[TEST-VERIFIED]`

Patch 3은 provenance를 추가하는 작업이지
기존 geometry 계산을 새로 정의하는 작업이 아니다.

테스트에는:

```text
CSV numerical reading golden values
real extraction loop feature values/schema
```

확인이 포함되어 있다.

즉 기존:

```text
face
oval
IPD
shoulder
angle
depth
```

계산 결과가 provenance 추가 때문에
의도치 않게 바뀌지 않는지 확인한다.

---

# 38. Analysis Manifest Atomic Write

`[GIT-VERIFIED]`

manifest는 직접 덮어쓰기보다:

```text
temporary file 생성
→ JSON write
→ flush
→ fsync
→ os.replace
```

방식으로 저장한다.

함수:

```python
write_json()
```

목적:

> write 도중 실패해서 `analysis_manifest.json` 자체가
> 깨진 partial JSON으로 남는 위험을 줄임

이다.

---

# 39. Manifest 상태

run 시작:

```text
status = running
ended_at = null
```

정상 종료:

```text
status = completed
ended_at = ...
```

예외:

```text
status = failed
errors[]에 이유 기록
```

`completed` 또는 `failed` 같은 terminal 상태는
나중 호출로 다시 뒤집지 않는다.

---

# 40. Failure Manifest

`[GIT-VERIFIED]`

run이 이미 생성된 이후 처리 중 예외가 발생하면
가능한 경우:

```text
failed manifest
```

를 남긴다.

단, input validation에서
run manifest를 만들기 전에 즉시 reject되는 경우까지
항상 failed manifest가 생성되는 것은 아니다.

이 점은 Known Limitation에 별도로 기록한다.

---

# 41. Run별 Output Archive

`[GIT-VERIFIED]`

각 run output은 해당 run directory로 archive한다.

`archive_output()`은 신규 destination에:

```text
exclusive create
```

를 사용하여
이미 존재하는 artifact를 조용히 덮어쓰지 않는다.

각 output에는:

```text
filename
path
size
mtime
sha256
kind
row_count
schema_version
compatibility_path
```

등을 기록한다.

Patch 3 시점에는
canonical frame schema version이 아직 없으므로
일부 `schema_version`은 `null`이다.

---

# 42. Batch Provenance

`[GIT-VERIFIED]`

여러 recording을 함께 분석하는 경우
공통 summary/plot은 batch output이다.

`analysis_batch.json`에:

```text
analysis_batch_id
analysis_run_ids
outputs
run_manifests
```

를 기록한다.

각 shared output에도:

```text
analysis_run_ids
```

를 넣어
어떤 run들이 결과에 기여했는지 남긴다.

---

# 43. Flat Compatibility Output

기존 workflow가:

```text
analysis/summary_steps.csv
analysis/<recording>_frames.csv
```

같은 평면 경로를 사용하므로
Patch 3은 flat compatibility copy를 계속 제공한다.

하지만 canonical provenance의 기준은:

```text
run archive + manifest
```

다.

---

# 44. Frames Provenance Sidecar

`[GIT-VERIFIED]`

raw extraction이 성공하면
flat frames CSV 옆에:

```text
<frames.csv>.provenance.json
```

을 생성한다.

핵심 field:

```text
recording_id
analysis_run_id
frames_sha256
analysis_manifest
analysis_manifest_sha256
```

이 sidecar가
추후 `--from-csv` parent verification의 연결점이다.

---

# 45. Completed Parent만 허용

`[GIT-VERIFIED]`

`--from-csv`는 parent manifest의:

```text
status == completed
```

를 요구한다.

`failed` 또는 `running` source run은
parent로 사용할 수 없다.

따라서 실패 중간산출물을
정상 분석 결과의 부모로 승격시키지 않는다.

---

# 46. Source Frames Snapshot

`[GIT-VERIFIED]`

`--from-csv` 실행 시
입력 frames CSV를 run archive 안에:

```text
source_frames
```

로 복사한다.

복사 후 SHA-256이
처음 입력 hash와 같지 않으면:

```text
source frames changed before reprocessing
```

으로 거부한다.

즉 re-summary 중 입력 CSV가 변한 경우를 탐지한다.

---

# 47. 독립 Review Chronology

## 47.1 초기 구현

`[CHAT-RECONSTRUCTED]`

Codex가 Patch 3 초안을 구현했다.

목표는:

```text
analysis_run_id
input/output hashes
code/environment/model provenance
raw/from-csv lineage
```

였다.

---

## 47.2 Claude 독립 리뷰

`[CHAT-RECONSTRUCTED]`

Claude READ-ONLY review에서
초기 구현을 그대로 commit하지 않고:

```text
FIX BEFORE COMMIT
```

판정을 내렸다.

핵심 지적:

```text
B1
markers recording_id를 실제 파일에서 검증하지 않고
capture identity로 보완할 수 있는 lineage 오류

I1
modern provenance-aware input이
legacy로 silent downgrade될 수 있는 경로

I2
processing settings / 실제 분석 option 기록 부족
```

---

## 47.3 Patch 3.1

`[CHAT-RECONSTRUCTED + GIT-VERIFIED]`

B1/I1/I2를 중심으로:

```text
markers / quality actual ID validation
modern downgrade rejection
processing_settings 확장
atomic manifest / failure handling
parent validation 강화
```

등을 보강했다.

---

## 47.4 Patch 3.2

`[CHAT-RECONSTRUCTED + GIT-VERIFIED]`

legacy raw/CSV를 자동 허용하지 않고:

```text
--legacy-pilot
```

명시적 opt-in을 요구하도록 강화했다.

formal/external과의 충돌도 거부한다.

---

## 47.5 최종 리뷰

`[CHAT-RECONSTRUCTED]`

최종 독립 review verdict:

```text
COMMIT OK / HARDWARE SMOKE TEST PENDING
```

으로 복원된다.

즉:

```text
software provenance / lineage patch
→ commit 가능

실제 D455 end-to-end
→ 별도 hardware smoke 필요
```

로 구분했다.

---

# 48. Test Suite

`[GIT-VERIFIED]`

Patch 3에서 새로 추가된:

```text
test_analysis_provenance.py
```

에는 **52개 test method**가 있다.

파일 header에도:

```text
no camera, models, or network required
```

인 temporary/synthetic provenance test임을 명시한다.

---

# 49. 주요 테스트 범주

## Identity

- 같은 recording 재분석 시 새 analysis_run_id
- recording_id와 analysis_run_id 분리
- run directory collision 방지

## Legacy policy

- legacy raw 명시적 opt-in
- legacy CSV 명시적 opt-in
- legacy identity가 input SHA 기반
- formal/external role에서 legacy flag 금지

## Silent downgrade 방지

- modern raw가 capture metadata 없다고 legacy로 내려가지 않음
- modern metadata 흔적이 있으면 downgrade 금지
- modern frames identity가 있으면 sidecar 없이 legacy 처리 금지

## Sidecar identity

- markers recording_id mismatch reject
- markers 내부 서로 다른 ID reject
- quality ID mismatch reject
- 실제 관찰 ID만 기록

## Raw identity

- 같은 recording_id에 다른 raw bytes 금지

## Code/environment

- Git commit/dirty
- script SHA-256
- package / OS provenance failure handling

## Model

- model artifact hash
- used_in_this_run
- existing model 보존
- from-csv에서 model 사용으로 가장하지 않음

## `--from-csv`

- frames hash tamper reject
- parent manifest hash tamper reject
- failed parent reject
- parent output membership 확인
- recording/run row identity mismatch reject
- identical bytes를 다른 filename으로 복사한 경우 자동 parent 인정 안 함

## Manifest state

- failure manifest
- completed terminal
- atomic replace failure에서도 valid JSON 보존
- serialization failure에서도 valid JSON 보존

## Output publishing

- flat publish 실패 시 completed로 기록하지 않음
- provenance sidecar publish 실패 시 completed 금지
- shared output contributor run 기록

## Processing settings

- runtime depth threshold와 snapshot 일치
- task option 기록
- 실제 extraction loop에서 기존 feature 수치 유지

---

# 50. 전체 테스트 재실행

`[TEST-VERIFIED]`

현재 복원 과정에서
commit `1cdc528`를 별도 detached worktree로 checkout하여:

```bash
python3 -m unittest discover -v
```

를 재실행했다.

결과:

```text
Ran 146 tests
OK
```

즉:

```text
146 / 146 PASS
```

를 재현했다.

Patch 2 시점:

```text
94 tests
```

에서
Patch 3의 52개 provenance tests가 추가된 수와 정확히 일치한다.

---

# 51. Diff Hygiene

`[TEST-VERIFIED]`

현재 복원 과정에서:

```bash
git diff --check a262c6d 1cdc528
```

실행 결과:

```text
PASS
```

whitespace error가 확인되지 않았다.

detached worktree의:

```bash
git status --short
```

도 clean 상태였다.

---

# 52. Known Residual / Deferred Items

최종 review에서 commit을 막지는 않았지만
후속 lineage/integrity 작업으로 넘긴 항목들이 있다.

---

## 52.1 동일 Raw Byte의 Legacy Alias 가능성

`[CHAT-RECONSTRUCTED + GIT-VERIFIED]`

현재 explicit `--legacy-pilot`을 사용하면:

```text
modern raw bytes를 다른 old-style filename으로 복사
+
modern sidecar 제거
```

한 파일을
legacy SHA-based ID로 분석할 수 있는 여지가 있다.

즉 동일 bytes가 과거 formal recording으로 이미 존재했는지를
repository 전체에서 content-addressed 방식으로 조회해
alias를 막는 기능까지는 Patch 3에서 구현하지 않았다.

이 문제는:

```text
global lineage / catalog
```

성격이므로 후속 lineage 작업으로 넘겼다.

중요:

```text
legacy flag로 formal/external role을 직접 우회하는 것은 금지되어 있음
```

과는 별개다.

---

## 52.2 Legacy Parent Re-summary 표시

linked parent 자체가 legacy run인 경우,
child manifest에서:

```text
dataset_role = pilot
protocol_version = unknown_legacy
parent_analysis_run_id = ...
```

는 상속되지만,
child 자신의:

```text
legacy_input
```

이 반드시 동일 legacy 설명을 반복하지는 않는다.

parent manifest를 따라가면 lineage는 확인 가능하나,
self-contained 표시 측면에서 개선 여지가 있다.

---

## 52.3 Flat Compatibility Publish의 완전한 Transaction 보장 아님

Patch 3은:

```text
run manifest atomic write
completed status gating
```

을 강화했고
publish 실패 시 completed로 기록하지 않도록 테스트한다.

그러나 여러 flat compatibility artifact를
filesystem transaction 하나로 동시에 교체하는 구조는 아니다.

따라서 publish 중간 실패 시
flat 영역이 일시적으로 일부 새 파일/일부 옛 파일 상태가 될 가능성까지
완전히 제거한 것은 아니다.

canonical provenance는 run archive/manifest를 기준으로 본다.

---

## 52.4 Input Validation Reject와 빈 Batch Directory

`run_analysis()`는 batch directory를 먼저 만든다.

그 뒤 `start_analysis_run()` 단계에서
입력 provenance 검증이 즉시 reject되면:

```text
run manifest 없이
빈 batch directory
```

가 남을 수 있다.

이는 연구 결과를 completed로 오인시키지는 않지만
cleanup 측면의 minor issue다.

---

## 52.5 Batch ID Prefix

batch ID도 현재:

```text
new_analysis_id()
```

를 사용하므로
형식상 `ar_...` prefix를 쓴다.

기능 오류는 아니지만
run/batch ID를 문자열만 보고 구분하는 가독성은 낮다.

---

## 52.6 Raw Hash 이후 TOCTOU

raw는 full hash를 계산하며
hash 도중 변경도 감지한다.

하지만:

```text
hash 완료
→ 실제 playback 시작
```

사이 이후에 raw가 변경되는 극단적 경우까지
immutable snapshot으로 봉쇄하는 구조는 아니다.

`--from-csv` 입력은 archive snapshot 후 hash를 재검증하지만,
큰 raw 전체를 매 run별 복사하지는 않는다.

후속 immutable storage / lineage 정책과 연결할 수 있다.

---

## 52.7 Absolute Path Portability

manifest에는 artifact의:

```text
absolute path
```

가 포함된다.

같은 머신에서 감사하기에는 명확하지만
다른 머신으로 repository/data를 이동할 때
path 자체는 portable identifier가 아니다.

content hash와 recording/run identity가
실질적 식별 근거다.

---

## 52.8 Package Version Lookup Failure

일부 Python package metadata가
환경에 따라 조회되지 않을 수 있다.

Patch 3은 이를 실패시키지 않고:

```text
null + provenance_unknown_reasons
```

로 기록한다.

즉 environment provenance가
항상 모든 package에서 완전하다고 보장하는 것은 아니다.

---

# 53. Hardware Validation 상태

Patch 3의 대부분은:

```text
파일 identity
hash
manifest
model artifact metadata
lineage
failure state
```

이므로 synthetic test로 구조 검증 가능하다.

그러나 실제:

```text
D455 raw playback
RealSense profile
실제 model inference
실제 generated frames
실제 GUI/camera path
```

end-to-end smoke는
Foundation Patch 8로 남긴다.

따라서 최종 review도:

```text
COMMIT OK / HARDWARE SMOKE TEST PENDING
```

으로 구분했다.

---

# 54. Patch 3에서 의도적으로 변경하지 않은 것

다음은 그대로 유지한다.

```text
M0 / M1 / M2 정의
RF weight 공식
기존 posture class 정의
기존 31-column frame numerical semantics
기존 face/mesh/shoulder 계산식
기존 frame 선택 / trim 의미
기존 8~12cm forward gate
기존 face-only gate
capture provenance format
```

Patch 3의 중심은:

> **분석이 어떻게 만들어졌는지를 기록·검증하는 것**

이지,
새 feature representation을 설계하는 것이 아니다.

---

# 55. Patch 3의 범위 밖

## Canonical Frame Schema

아직:

```text
FRAME_SCHEMA_VERSION
고정 header
hip observation
frame-level recording_id / analysis_run_id always present
```

은 완성하지 않는다.

→ Foundation Patch 4.

---

## Model Artifact Lock

Patch 3은 actual SHA-256을 기록하지만:

```text
allowed model hash를 강제
```

하지 않는다.

→ **Foundation Patch 4.5 — MediaPipe Model Artifact Lock.**

---

## Full Pipeline Lineage

Patch 3은:

```text
recording
→ analysis run
→ frames
→ re-summary parent
```

를 크게 강화했지만,

```text
selection manifest
RF experiment input manifest
최종 result까지의 end-to-end catalog
```

전체는 아직 아니다.

→ 후속 lineage Patch.

---

## Recapture Selection

여러 recording 중:

```text
왜 이 recording을 최종 사용했는가
```

를 명시적으로 기록하는 selection manifest는 별도다.

---

## Integrity Checker

repo/data 전체를 스캔해서:

```text
누락
혼입
hash mismatch
orphan artifact
```

를 자동 검사하는 독립 checker도 후속 작업이다.

---

# 56. Patch 3 완료 판단

현재 복원 가능한 근거 기준:

```text
[완료]
analysis_run_id
recording_id 전달/검증
raw/from-csv mode 분리
input full SHA-256
capture/markers/quality ID 검증
modern silent legacy downgrade 차단
explicit --legacy-pilot
legacy SHA-based identity
Git/script provenance
environment provenance
model artifact SHA-256
model used flag
processing settings
playback calibration
run/batch output archive
frames parent sidecar
parent manifest/hash validation
running/completed/failed manifest
atomic manifest write
146/146 tests
diff-check PASS
```

후속:

```text
Foundation Patch 4.5 model artifact lock
canonical frames schema + hip
global lineage / alias control
selection manifest
integrity checker
actual D455 E2E smoke
```

따라서 운영상:

```text
Patch 3 = DONE
```

으로 유지한다.

---

# 57. 연구상 의미

Patch 3 전에는:

```text
frames.csv
```

가 존재해도
그 파일이 어떤 분석 실행의 산물인지
완전하게 설명하기 어려웠다.

Patch 3 후에는 최소 다음 질문을 추적할 기반이 생겼다.

```text
어느 recording인가?
어느 analysis run인가?
raw인가 from-csv인가?
parent run은 무엇인가?
input bytes는 무엇인가?
capture/markers/quality ID가 일치하는가?
어떤 analyze_d455.py인가?
어떤 Git 상태인가?
어떤 Python/package environment인가?
어떤 MediaPipe model bytes인가?
그 model이 이번 run에 실제 사용됐는가?
어떤 ROI/trim/depth 규칙인가?
어떤 output bytes가 만들어졌는가?
run은 completed인가 failed인가?
```

즉 Patch 3은:

> **분석 결과를 “파일 하나”에서 “검증 가능한 분석 실행 artifact”로 바꾼 단계**

라고 정리할 수 있다.

---

# 58. 관련 Commit

```text
Parent / Patch 2
a262c6d87366ccb4af50cda3f80a4c3ac94d0bda
feat: record forward gate evidence

Patch 3
1cdc52831cfb66b901db58279caf3e777a354546
feat: add verified analysis provenance tracking

Next
9d8b081
chore: add Claude project instructions
```

Patch 3.1 / Patch 3.2는
최종 commit 전 review/fix iteration 명칭이며
별도 Git commit hash는 없다.

---

# 59. 현재 문서 상태

```text
기술적 복원                  COMPLETE
commit/diff 확인              COMPLETE
52개 Patch3 test 확인         COMPLETE
전체 146-test 재현            COMPLETE
diff check                    COMPLETE
초기 review 핵심 B1/I1/I2     CHAT-RECONSTRUCTED
최종 review verdict            CHAT-RECONSTRUCTED
actual D455 smoke             DEFERRED
```

최종 후보 전 내부 검토에서 다음을 확인했다.

1. Patch 1/2 Foundation Record와 용어 통일
2. 현재 `RESEARCH_DATA_SCHEMA.md`의 future design과
   Patch 3 당시 실제 구현 범위를 구분
3. residual/deferred 항목을 별도 유지
4. model provenance와 **Foundation Patch 4.5 — MediaPipe Model Artifact Lock**을 명확히 분리
5. 실제 D455 smoke는 Foundation Patch 8로 유지

남은 절차:

```text
Claude 1차 READ-ONLY review finding 반영본(v2) targeted 재검토
→ blocker 없으면 canonical Foundation Record로 확정
```

---

# 60. Source Priority

본 복원에서는 다음 우선순위를 적용했다.

```text
1. commit 1cdc528 실제 source / Git diff
2. commit 1cdc528 실제 test code와 재실행 결과
3. 당시 RESEARCH_DATA_SCHEMA.md
4. 당시 Patch 3 Claude/Codex 대화 이력
5. 후속 연구 정리 문서
6. 추정
```

원칙:

```text
Git/source와 대화가 충돌하면
실제 final source를 현재 구현 사실로 우선한다.

대화는
왜 수정했는지 / review chronology를 복원하는 데 사용한다.

확인되지 않은 intermediate code state는
임의로 재구성하지 않는다.
```
