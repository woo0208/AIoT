# PATCH_04 — Canonical Frame Schema + Hip Raw Observations

> 상태: **IMPLEMENTED / SOFTWARE-VERIFIED / INDEPENDENTLY AUDITED / HARDWARE VALIDATION PENDING**
>
> 운영상 Patch 번호: **Foundation Patch 4**
>
> canonical frame schema:
>
> ```text
> frames-schema/1.0.0
> ```
>
> 구현 commit:
>
> ```text
> 110cce6170c307d8cbf9bac4a619454a36498980
> feat: implement Patch 4 frame schema contract
> ```
>
> parent / Design Freeze commit:
>
> ```text
> 7e36a464d0a242d6baca508fb97cb4a99b2bd2bd
> docs: freeze Patch 4 frame schema contract
> ```
>
> commit timestamp:
>
> ```text
> 2026-10-01T23:54:53+09:00
> ```
>
> documentation closure milestone:
>
> ```text
> 2026-10-02
> ```
>
> 작성 목적: `DATA-003`과 `RESEARCH_DATA_SCHEMA.md` §F에서 먼저 동결한
> `frames-schema/1.0.0` exact 60-field raw-observation/storage contract를
> 실제 Python writer/reader와 frame extraction에 구현한 Foundation Patch 4의
> 범위, 호환성, 검증, hardening, 독립 review 결과와 남은 한계를 기록한다.

---

# 1. 이 Patch의 위치

Foundation 흐름:

```text
FOUNDATION_PRELUDE_00
algorithm / evaluation / capture hardening
        ↓
PATCH 1
capture recording provenance
        ↓
PATCH 2
forward gate evidence
        ↓
PATCH 3
analysis provenance
        ↓
PATCH 4  ← 이 문서
canonical frame schema + hip raw observations
        ↓
PATCH 4.5
MediaPipe model artifact lock
```

Patch 3이 분석 실행과 artifact provenance를 만들었다면,
Patch 4는 각 frame observation을 고정된 canonical contract로 저장하고 다시 읽는 기반을 구현한다.

Patch 4는 다음이 아니다.

```text
F1/F2 feature-engineering Patch
trunk geometry 정의 Patch
posture class 변경 Patch
capture acceptance threshold 변경 Patch
실제 D455 measurement-quality validation Patch
```

---

# 2. 증거 수준

### `[GIT-VERIFIED]`

commit `110cce6`의 source, test, diff, metadata에서 확인한 구현 사실.

### `[TEST-VERIFIED]`

commit `110cce6`에서 `python3 -B -m unittest -q`를 실행하여 확인한 software test 결과.

### `[SCHEMA-VERIFIED]`

`DATA-003`과 `RESEARCH_DATA_SCHEMA.md` §F의 frozen contract에서 확인한 schema 의미.

### `[CHAT-RECONSTRUCTED]`

초기 Claude 독립 READ-ONLY audit와 post-hardening targeted READ-ONLY re-audit의
진행·판정 기록에서 복원한 review chronology.

### `[UNKNOWN]`

현재 확보된 evidence로 확정할 수 없는 항목. 실제 D455 hardware 동작은 이 범주에 남는다.

---

# 3. 목적과 경계

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

Patch 4의 목적은 이미 동결된 canonical raw frame observation/storage contract를 구현하는 것이다.

```text
raw detector/sensor observation
→ fixed canonical frame row
→ canonical CSV serialization
→ validated canonical reader
```

raw observation, derived geometry, model feature를 분리한다.

```text
Canonical Raw Observation
≠ Derived Geometry
≠ F0 / F_cal / F1 / F2 model feature
```

따라서 bilateral hip observation을 저장할 수 있게 되었지만,
hip midpoint, trunk axis, trunk angle, sagittal projection 또는 classifier input은 정의하지 않았다.

---

# 4. Frozen Output

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

canonical schema label:

```text
frames-schema/1.0.0
```

고정 구조:

```text
legacy ordered prefix             31 fields
Patch 4 metadata/state            17 fields
bilateral hip raw observation     12 fields
-------------------------------------------
total                             60 fields
```

exact field 이름·순서·의미는 `DATA-003`과 `RESEARCH_DATA_SCHEMA.md` §F가 권위다.
본 Foundation Record는 해당 contract를 재정의하지 않는다.

elbow/wrist field는 `frames-schema/1.0.0`에 포함하지 않고 빈 예약 열도 두지 않는다.
향후 추가하려면 별도의 research decision과 명시적 frame-schema version update가 필요하다.

---

# 5. Legacy 31 Preservation

`[GIT-VERIFIED + TEST-VERIFIED]`

기존 31개 field는 다음을 유지한다.

```text
이름
순서
단위
계산 의미
```

신규 field는 legacy ordered prefix 뒤에 append되었다.
신규 canonical validity가 legacy numeric 값을 소급 재계산하거나 비우지 않는다.

특히 기존 계산 경로의 key-presence behavior를 보존했다.

```python
if "face_x" in row:
```

위와 같은 legacy 분기는 값의 truthiness가 아니라 기존 key 존재 여부를 계속 사용한다.
Patch 4는 legacy 31 계산 흐름을 전체 60-key prefill 구조로 바꾸지 않았다.

generic `write_csv()`도 변경하지 않았고,
canonical frame output 전용 `write_frames_csv()`를 별도로 추가했다.

---

# 6. Canonical Writer

`[GIT-VERIFIED + TEST-VERIFIED]`

`write_frames_csv()`는 frame output에만 적용되는 fixed writer다.

주요 동작:

```text
exact 60-field header/order
frames-schema/1.0.0 label 검증
non-empty recording_id / analysis_run_id 검증
strict positive Python int frame_index 검증
한 파일 안의 recording/run identity 일관성 검증
canonical frame key 중복 거부
source enum 검증
canonical boolean type 검증
non-finite numeric value 거부
unknown field 거부
```

serialization:

```text
None          → empty CSV cell
True          → true
False         → false
unknown bool  → empty CSV cell
```

numeric missing sentinel, numeric boolean, NaN, Infinity 또는 synthetic interpolation을 추가하지 않았다.

---

# 7. Canonical Reader

`[GIT-VERIFIED + TEST-VERIFIED]`

`load_frames_csv()`는 canonical header가 존재하면 canonical branch를 사용한다.

canonical branch는 다음을 검증·복원한다.

```text
exact 60-field header
exact schema label
recording_id / analysis_run_id presence and consistency
source enum
canonical boolean true / false / empty
numeric parseability and finiteness
positive integer-valued frame_index
```

canonical boolean은 다음 Python 값으로 복원한다.

```text
true   → True
false  → False
empty  → None
```

legacy/unversioned reader의 permissive name-based semantics는 별도로 유지했다.

---

# 8. Identity와 Frame Provenance

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

canonical frame-row key:

```text
(analysis_run_id, recording_id, frame_index)
```

`recording_id`는 source recording identity,
`analysis_run_id`는 현재 analysis execution identity다.

`frame_index`는 trim 또는 `--step` filtering 전에 증가하는
1-based source playback traversal counter다.
따라서 저장된 canonical row에서 연속일 필요가 없다.

supporting source provenance:

```text
color_frame_number
depth_frame_number
```

두 값은 alignment 전 원래 frameset의 color/depth frame 객체에서 읽는다.
canonical key에는 포함하지 않는다.

`mediapipe_ts_ms`는 MediaPipe VIDEO API에 실제 전달한 monotonic-corrected `ts_int`다.
legacy `ts_ms`의 기존 의미를 바꾸지 않는다.

---

# 9. Detection, Source, Validity State

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

새 state는 raw observation availability를 명시한다.

```text
face_detected
face_mesh_detected
pose_detected
face_depth_valid
lsh_valid / rsh_valid
lsh_depth_valid / rsh_depth_valid
left_hip_valid / right_hip_valid
left_hip_depth_valid / right_hip_depth_valid
```

face depth source:

```text
bbox_roi
oval_center_roi
missing
```

bbox depth가 없고 face mesh oval-center depth가 있으면
legacy bbox → oval fallback 결과와 canonical source가 함께 보존된다.

shoulder depth source:

```text
both
left_only
right_only
missing
```

shoulder canonical in-frame/depth validity는 legacy clipped ROI depth 계산값을 소급 변경하지 않는다.

---

# 10. Bilateral Hip Raw Observation

`[SCHEMA-VERIFIED + GIT-VERIFIED + TEST-VERIFIED]`

사람 기준 left/right hip 각각 다음 6개 field를 저장한다.

```text
x pixel coordinate
y pixel coordinate
depth meters
raw MediaPipe visibility
geometric in-frame validity
depth validity
```

pixel coordinate는 원래 color image의 비반전 좌표다.

```text
x_px = normalized_x × image_width
y_px = normalized_y × image_height
```

hip validity는 visibility threshold가 아니라 finite normalized x/y와 image bounds에 따른 geometry/state다.
invalid hip은 x/y/depth가 missing이고 depth lookup을 호출하지 않는다.
visibility는 pose result에 존재하면 raw observation으로 유지한다.

valid hip의 depth는 새로운 hip-specific algorithm을 만들지 않고 기존 `median_depth()` primitive를 재사용한다.

```text
ROI half-width                 6 px
valid raw depth               raw_depth > 0
minimum valid depth pixels    10
reduction                     median
unit conversion               recording depth_scale → meters
```

hip가 in-frame이지만 depth를 얻지 못하면 x/y/visibility와 `hip_valid=true`는 유지하고,
depth만 missing, `hip_depth_valid=false`로 기록한다.

---

# 11. 변경 파일

`[GIT-VERIFIED]`

commit `110cce6`:

```text
analyze_d455.py
test_analysis_provenance.py
test_frame_schema.py
```

Git stat:

```text
3 files changed, 850 insertions(+), 12 deletions(-)
```

Patch 4에서 변경하지 않은 주요 파일:

```text
capture_d455.py
rf_experiment.py
compare_paper.py
research formulas / thresholds / posture classes
```

---

# 12. Validation Evidence

`[TEST-VERIFIED + CHAT-RECONSTRUCTED]`

test progression:

```text
pre-Patch-4 baseline     146 tests PASS
initial implementation  163 tests PASS
post-hardening           171 tests PASS
```

final verification at commit `110cce6`:

```text
python3 -B -m unittest -q
Ran 171 tests
OK
```

독립 software review chronology:

```text
initial Claude independent READ-ONLY implementation audit    PASS
post-hardening Claude targeted READ-ONLY re-audit             PASS
remaining BLOCKER findings                                    0
remaining IMPORTANT findings                                  0
```

이 evidence는 source/test/static review 수준이다.
실제 D455, `pyrealsense2`, MediaPipe model artifact와 실제 recording을 사용한 hardware evidence가 아니다.

---

# 13. Post-Audit Hardening

`[GIT-VERIFIED + TEST-VERIFIED + CHAT-RECONSTRUCTED]`

초기 구현 audit 이후 canonical reader/writer round-trip에서 latent type asymmetry가 확인되었다.

```text
writer requirement
frame_index = Python int and >= 1

old canonical reader result
CSV "1" → Python 1.0
```

따라서 canonical writer가 만든 row를 reader로 읽은 뒤 다시 canonical writer에 전달하면
strict writer guard가 올바르게 거부하는 문제가 있었다.

final implementation은 canonical `load_frames_csv()` branch에서만 `frame_index`를 특별 처리한다.

```text
present
numeric
finite
integer-valued
>= 1
→ Python int로 복원
```

writer의 strict integer guard는 완화하지 않았다.
legacy/unversioned reader semantics도 이 hardening 때문에 변경하지 않았다.

추가 regression coverage:

```text
writer → reader → writer round-trip
loaded frame_index Python int 확인
empty / zero / negative / fractional rejection
non-numeric / non-finite rejection
```

이 수정은 serialization/reader round-trip defect correction이며
field, meaning, ordering 또는 schema version 변경이 아니다.

---

# 14. 주요 Regression Coverage

`[TEST-VERIFIED]`

```text
exact 60 fields / unique names / exact legacy prefix
no elbow/wrist/reserve columns
canonical missing / boolean / enum contract
nullable boolean None round-trip
writer/reader schema and identity rejection
frame_index traversal gap and type round-trip
source frame number and corrected MediaPipe timestamp
face bbox-depth failure → oval-center fallback
shoulder left/right out-of-frame mirror cases
non-square W/H hip pixel geometry
bilateral hip non-swap and spatially distinct depth
shared median_depth() and frozen 6 px half-width
invalid hip skips depth lookup
legacy reader permissiveness
legacy 31 extraction regression
```

---

# 15. Known Limitation — `pose_detect_ratio`

`[GIT-VERIFIED]`

기존 summary의 `pose_detect_ratio`는 새 `pose_detected` flag가 아니라
`z_sh_m` availability를 기준으로 계산한다.

이것은 Patch 4 전부터 이어진 summary semantic debt다.
Patch 4 closure에서 의미를 변경하지 않았으며 별도 scope에서 명시적으로 다뤄야 한다.

---

# 16. Hardware Validation 상태

`[UNKNOWN]`

Patch 4 software implementation은 완료됐지만 다음은 검증되지 않았다.

```text
real D455 playback/extraction end-to-end behavior
actual face/shoulder/hip acquisition coverage
actual depth valid rate
depth repeatability / jitter
RGB landmark + aligned-depth coupling stability
3D geometry repeatability
distance-dependent feature stability
```

실제 D455 validation은 Foundation Patch 8의 formal milestone이다.

필요하면 그 전에 제한된 Early Hardware Preflight를 수행할 수 있으나,
그 성격은 non-formal engineering smoke/preflight로 한정한다.

```text
Patch 8 대체 아님
research evidence 아님
formal participant collection 아님
threshold / protocol decision 도출 근거 아님
```

---

# 17. Deferred Research Decisions

Patch 4 구현 완료는 다음 OPEN item을 해소하지 않는다.

```text
OPEN-002  F1 exact definition
OPEN-003  F2 exact definition
OPEN-004  rank_weights policy for >6 features
OPEN-005  formal experiment exact protocol
OPEN-006  D455 validation exact grid / metric / acceptance criterion
```

formal collection은 시작하지 않았다.

Patch 4는 다음을 정의하거나 변경하지 않았다.

```text
F1/F2 exact formulas
trunk geometry
posture class
capture acceptance threshold
formal inclusion/exclusion
evaluation rule
```

---

# 18. Patch 4 완료 판단

현재 repository evidence 기준:

```text
[완료]
DATA-003 exact contract implementation
fixed 60-field canonical writer
canonical reader
recording/run/frame identity
source frame provenance
corrected MediaPipe timestamp
canonical detection/source/validity state
bilateral hip raw observation/depth
legacy 31 calculation preservation
generic write_csv() preservation
frame_index reader hardening
171/171 tests
initial independent READ-ONLY audit PASS
targeted post-hardening READ-ONLY re-audit PASS

[미완료 / 후속]
actual D455 hardware validation
Patch 4.5 model artifact lock
Patch 5~7 lineage/selection/integrity work
Patch 8 actual D455 validation
OPEN-002~OPEN-006 research decisions
```

따라서 운영상:

```text
Patch 4 implementation = DONE
Patch 4 software verification/audit = DONE
Patch 4 hardware validation = PENDING / Patch 8
```

---

# 19. 관련 Commit

```text
Design Freeze parent
7e36a464d0a242d6baca508fb97cb4a99b2bd2bd
docs: freeze Patch 4 frame schema contract

Patch 4 implementation
110cce6170c307d8cbf9bac4a619454a36498980
feat: implement Patch 4 frame schema contract
```

---

# 20. 현재 문서 상태

```text
contract freeze                 COMPLETE
implementation                 COMPLETE
software tests                 COMPLETE — 171 PASS
initial independent audit      COMPLETE — PASS
post-hardening re-audit        COMPLETE — PASS
Foundation Record              CREATED
actual D455 evidence           DEFERRED — Patch 8
formal collection              NOT STARTED
```

---

# 21. Source Priority

본 기록은 다음 우선순위를 적용한다.

```text
1. commit 110cce6 source / Git diff
2. commit 110cce6 tests and reproduced test result
3. DATA-003 + RESEARCH_DATA_SCHEMA.md §F
4. independent audit/re-audit handoff record
5. 추정
```

원칙:

```text
Git/source/test가 현재 implementation fact의 권위다.
DATA-003과 Schema §F가 frozen field/data contract의 권위다.
Foundation Record는 구현·검증 이력을 기록하지만 schema를 재정의하지 않는다.
software PASS를 hardware 또는 research evidence로 확대 해석하지 않는다.
```
