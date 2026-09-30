# BASELINE_00 — Handoff Snapshot

> 상태: **소급 작성(Retrospective), 최종 후보 v2 (Final Candidate v2)**
>
> v2 반영: **2026-10-01 Claude READ-ONLY 1차 검토 Finding 1~7 반영. Targeted 재검토 전 상태.**
>
> 작성 목적: 팀원에게 전달받은 당시 코드 상태를 연구 이력의 출발점으로 고정한다.
> 이 문서는 “당시 왜 그렇게 설계했는가”를 추정하는 문서가 아니라,
> **전달받은 ZIP에서 실제로 확인되는 구현 상태가 무엇이었는지**를 기록한다.
>
> 작성 기준일: 2026-09-30

---

## 1. 이 문서의 역할

본 프로젝트는 완전한 제로베이스 연구 코드에서 시작한 것이 아니다.

사용자는 팀원에게서 이미 일부 구현된 자세 촬영·분석·분류 코드를 전달받았고,
그 이후 문제점을 발견하여 수정·확장했다.

그러나 초기 수정 구간에서는 현재와 같은 Git/Decision Log/Provenance 관리 체계가
완전히 적용되지 않았다.

따라서 연구 이력을 다음과 같이 구분한다.

```text
Phase 0
Handoff Snapshot
= 팀원에게 전달받은 코드 상태
= 이 문서가 기록하는 범위

Phase 0.5
Pre-Git / Pre-Controlled Modifications
= 전달받은 뒤 문제를 발견하고 수정했으나
  당시 변경 이유와 순서가 완전하게 기록되지 않은 구간
= 별도 RETROSPECTIVE 문서에서 복원 예정

Phase 1+
Git-Tracked / Progressively Controlled Phase
= 현재 research-main 계보의 root commit `64f8897`부터 Git 추적이 시작된 구간.
  schema, foundation record, 독립 코드 리뷰 체계는 이 시점부터 한 번에 완성된 것이 아니라
  후속 commit과 Foundation Patch를 통해 단계적으로 도입되었다.
```

중요:

- Phase 0과 Phase 0.5의 설계 의도는 **확인 가능한 근거가 없으면 추정하지 않는다.**
- 정확히 복원할 수 없는 사항은 `UNKNOWN` 또는 `PARTIALLY RECONSTRUCTED`로 남긴다.
- 현재의 구현 규칙을 과거 코드에 소급 적용하지 않는다.

---

## 2. 증거 수준 표기

본 문서에서는 다음 표기를 사용한다.

### `[USER-CONFIRMED]`

사용자가 본 ZIP을 **팀원에게 전달받았을 당시의 코드 snapshot**이라고 확인한 사항.

### `[SNAPSHOT-VERIFIED]`

첨부된 ZIP 내부 소스 코드를 직접 확인해 검증한 사항.

### `[CHAT-RECONSTRUCTED]`

이후 대화 기록을 통해 당시 문제 인식 또는 후속 수정 방향을 확인한 사항.

### `[UNKNOWN]`

현재 자료만으로는 확인할 수 없으며 추정하지 않는 사항.

---

# 3. Source Artifact

## 3.1 원본

`[USER-CONFIRMED]`

사용자가 제공한 다음 ZIP을 팀원으로부터 코드를 전달받은 시점의 snapshot으로 취급한다.

```text
새 폴더 (2).zip
```

## 3.2 ZIP SHA-256

`[SNAPSHOT-VERIFIED]`

```text
ddd5edb7181f6589f450699d1340a4363878f8bc5adf8efd923d67359ea4cda8
```

이 hash는 본 baseline source artifact를 식별하기 위한 값이다.

파일명을 이후 더 명확한 이름으로 복사/보관하더라도,
원본 bytes가 변경되지 않았다면 이 SHA-256을 기준으로 동일 snapshot인지 확인할 수 있다.

## 3.3 ZIP 내부 파일

`[SNAPSHOT-VERIFIED]`

```text
analyze_d455.py
capture_d455.py
check_recording.py
compare_paper.py
rf_experiment.py
```

개별 파일 hash:

| File | SHA-256 |
|---|---|
| `analyze_d455.py` | `3b3075a07da5a1fa0db48f57b3326b5cce8856cd8201e149163b4205d35a7e3b` |
| `capture_d455.py` | `9a3a02ea98f8353dbeaf8ae6d121439b66a204c5843f48c3223d16c933d3ae27` |
| `check_recording.py` | `3fecdffa63747ba052d4adbd364d537f12bd933e1b4a8e1bb0e643418f1e0a5c` |
| `compare_paper.py` | `203b79bcdf0f86fcfbe7089d49b5779291d2a385a6f8b891affd8b7daf9af343` |
| `rf_experiment.py` | `8f753008ff233831bc70513ced723047a91f5425b15f023f55778283383337c9` |

---

# 4. Handoff 시점 시스템의 큰 구조

`[SNAPSHOT-VERIFIED]`

전달받은 snapshot에는 이미 다음과 같은 전체 흐름이 존재했다.

```text
Intel RealSense D455
        ↓
capture_d455.py
        ↓
raw recording (.db3 / .bag)
+ _camera.json
+ _markers.csv
+ _samples.csv
+ _quality.json
        ↓
analyze_d455.py
        ↓
*_frames.csv
summary_steps.csv
summary_report.txt
그래프
        ↓
compare_paper.py / rf_experiment.py
        ↓
논문 데이터 및 자체 촬영 데이터 비교
RF / weighted-RF 계열 실험
```

즉, 전달 시점에 이미:

- D455 촬영
- 자세별 sequence 진행
- 촬영 품질 확인
- MediaPipe 기반 후처리
- frame-level CSV
- summary
- RF 기반 분류 비교

의 기본 골격이 있었다.

그러나 이후 연구용으로 필요한
**엄격한 provenance, lineage, fixed schema, hardware validation evidence**는
아직 구축되지 않은 상태였다.

---

# 5. Capture Baseline

## 5.1 D455 stream 설정

`[SNAPSHOT-VERIFIED]`

`capture_d455.py`에서 다음 stream을 사용한다.

```text
Color : 1280 × 720, BGR8, 15 FPS
Depth :  848 × 480, Z16,  15 FPS
```

촬영 시작 전 대상 거리 안내 범위는:

```text
0.70 ~ 0.80 m
```

이다.

---

## 5.2 자세 sequence

`[SNAPSHOT-VERIFIED]`

핵심 자세 sequence:

```text
upright
→ forward_head
→ upright
→ body_forward
→ upright
```

전체 sequence에서는 추가로:

```text
lean_back
lean_left
lean_right
upright
```

가 포함된다.

따라서 전달 시점부터
`forward_head`와 `body_forward`를 별도 posture로 취급하는 구조는 존재했다.

---

## 5.3 Forward posture의 live 안내 기준

`[SNAPSHOT-VERIFIED]`

전달받은 코드에는:

```python
LIVE_FWD_M = 0.04
```

가 존재한다.

즉 hold 중 live guidance는
직전 upright보다 약 4 cm 이상 가까워지지 않은 경우
“조금 더 앞으로” 안내를 출력하는 구조다.

화면 안내 문구에는 “목표 8~12cm”가 표시되지만,
**실제 live 판정 상수 자체는 4 cm**이다.

따라서 이 snapshot에서
“8~12 cm가 hard acceptance gate로 구현되어 있었다”고 기록하면 안 된다.

---

## 5.4 Final quality check의 forward 기준

`[SNAPSHOT-VERIFIED]`

최종 quality check에서는
`forward_head`, `body_forward`에 대해:

```text
직전 upright 대비 forward 이동 < 0.015 m
```

이면 실패로 처리한다.

즉 약 **1.5 cm 미만**인 경우에만
“얼굴이 앞으로 거의 나오지 않음”으로 fail된다.

따라서 handoff snapshot에서는:

- 안내 목표: 8~12 cm
- live hint 기준: 4 cm
- 최종 fail 기준: 1.5 cm

가 서로 다른 상태로 공존한다.

이는 이후 연구-controlled phase에서
forward posture protocol을 정리할 필요가 있었던 중요한 baseline 상태다.

원래 이러한 세 값이 다르게 설정된 **설계 이유는 확인되지 않는다.**

`[UNKNOWN]`

---

## 5.5 Face → Body distance fallback

`[SNAPSHOT-VERIFIED]`

거리 측정은 다음 순서다.

```text
face_distance()
    ↓ 실패
body_distance()
    ↓
none
```

즉 얼굴 거리 측정이 실패하면
body depth 영역을 사용한 fallback이 가능하다.

이 때문에 handoff snapshot의 forward 판정은
항상 face depth만 사용한다고 볼 수 없다.

---

## 5.6 Capture metadata

`[SNAPSHOT-VERIFIED]`

촬영 시 `_camera.json`에는 이미 다음 종류의 정보가 저장된다.

- subject
- round
- start time
- raw recording filename
- start distance
- target range
- FPS
- posture sequence
- prep time
- D455 device name
- serial number
- firmware version
- USB descriptor
- depth scale
- color/depth intrinsics
- depth-to-color extrinsics
- stereo baseline

즉 **일부 장비/촬영 metadata 저장 기능은 handoff 시점부터 존재했다.**

그러나 다음과 같은 연구 provenance 필드는 이 snapshot에서 확인되지 않는다.

```text
recording_id
dataset_role
capture protocol version
Git commit
Git dirty state
capture script SHA-256
formal/pilot/external role enforcement
```

---

# 6. Analysis Baseline

## 6.1 MediaPipe 모델

`[SNAPSHOT-VERIFIED]`

`analyze_d455.py`는 다음 계열 모델을 사용한다.

- Face Detector
- Face Landmarker
- Pose Landmarker Full

모델 URL은 `latest` 경로를 사용한다.

예:

```text
.../float16/latest/...
```

따라서 handoff snapshot에서는
실행 시점별 실제 artifact가 동일하다는 것을
고정 hash로 강제하는 model lock 구조가 없다.

---

## 6.2 MediaPipe 실행 설정

`[SNAPSHOT-VERIFIED]`

확인되는 주요 설정:

```text
FaceDetector:
min_detection_confidence = 0.5

FaceLandmarker:
running_mode = VIDEO
num_faces = 1

PoseLandmarker:
running_mode = VIDEO
num_poses = 1
```

---

## 6.3 Frame 추출 구조

`[SNAPSHOT-VERIFIED]`

`_markers.csv`를 읽어 posture hold 구간을 결정하고,
trim 후 frame을 처리한다.

처리 과정:

```text
raw recording
→ depth를 color에 align
→ Face Detector
→ Face Landmarker
→ Pose Landmarker
→ face / shoulder / depth / angle 계산
→ row append
```

---

## 6.4 Face depth

`[SNAPSHOT-VERIFIED]`

Face detector bbox가 있으면
bbox 내부 25~75% 영역의 depth median을 사용한다.

bbox 기반 face depth가 없고
face mesh가 존재하는 경우,
face oval 중심 부근 약 ±15 px 영역에서 depth를 다시 시도한다.

따라서 `z_face_m`은
서로 다른 두 source 중 하나에서 생성될 수 있지만,
handoff snapshot의 frame row에는
**어느 source가 사용되었는지 표시하는 field가 없다.**

---

## 6.5 Shoulder

`[SNAPSHOT-VERIFIED]`

Pose landmark:

```text
11 = left shoulder
12 = right shoulder
```

를 사용한다.

좌/우 shoulder 좌표는 color pixel 좌표로 변환하며,
각 shoulder 주변 약 ±6 px depth 영역에서 median depth를 구한다.

또한:

```text
z_sh_m
```

은 유효한 left/right shoulder depth들의 평균으로 계산된다.

한쪽만 depth가 있으면
그 한쪽 값만으로 `z_sh_m`이 생성될 수 있다.

---

## 6.6 Handoff 시점 frame fields

`[SNAPSHOT-VERIFIED]`

모든 detector/landmark가 성공한 row에서는
최대 31개 key가 생성된다.

### Identity / Time

```text
subject
round
step
label
t
ts_ms
```

### Face

```text
face_x
face_y
face_w_px
face_h_px
face_area_px
face_score
z_face_m
face_size_cm2
```

### Face mesh / geometry

```text
oval_area_px
oval_size_cm2
ipd_px
ipd_cm
box_to_oval
```

### Shoulder

```text
lsh_x
lsh_y
rsh_x
rsh_y
lsh_vis
rsh_vis
z_lsh_m
z_rsh_m
z_sh_m
```

### Angle

```text
theta1_deg
theta2_deg
theta3_deg
```

---

## 6.7 Fixed schema 부재

`[SNAPSHOT-VERIFIED]`

frame row는 검출 성공 여부에 따라 key가 추가되는 방식이다.

따라서 face/mesh/pose가 검출되지 않은 frame에서는
해당 key 자체가 row에 존재하지 않을 수 있다.

즉 handoff snapshot에는:

```text
FRAME_SCHEMA_VERSION
고정 field order
모든 row에 동일한 canonical key set
hip raw observation
explicit validity fields
```

가 아직 존재하지 않는다.

---

## 6.8 Analysis provenance 부재

`[SNAPSHOT-VERIFIED]`

다음 구조는 handoff snapshot에서 확인되지 않는다.

```text
analysis_run_id
recording_id lineage
analysis_manifest.json
analysis code Git commit
analysis script SHA-256
actual model SHA-256 provenance
used_in_this_run
raw / from-csv provenance separation
parent analysis validation
```

따라서 동일 raw를 여러 번 분석하거나,
분석 환경/모델이 달라졌을 때
결과 파일 자체만으로 정확한 생성 계보를 추적하기 어렵다.

---

# 7. RF / Classification Baseline

## 7.1 기존 M0 / M1 / M2 구조

`[SNAPSHOT-VERIFIED]`

`rf_experiment.py`에는 이미 다음 구조가 존재한다.

```text
M0
일반 Random Forest

M1
input feature weighting 후 Random Forest

M2
split score weighting을 적용한 팀 제안형 Random Forest
```

또한 feature mode:

```text
all
invariant
relative
```

가 존재한다.

즉 RF/WRF 비교 연구의 기본 골격 자체는
handoff snapshot에 이미 포함되어 있었다.

---

## 7.2 Handoff 시점 Random RNG 구조

`[SNAPSHOT-VERIFIED]`

Forest 학습에서 하나의 RNG를 만든 뒤:

```text
bootstrap index 생성
→ 같은 RNG 객체를 Tree에 전달
```

하는 구조다.

즉 bootstrap sampling과 tree 내부 random draw가
독립 RNG stream으로 분리되지 않았다.

이는 이후 research-controlled phase에서
RNG isolation이 필요한 baseline 상태였다.

원래 이 구조를 선택한 이유는 확인되지 않는다.

`[UNKNOWN]`

---

## 7.3 Reduced feature rank weight

`[SNAPSHOT-VERIFIED]`

6개 feature일 때에는:

```text
[0.30, 0.20, 0.15, 0.15, 0.15, 0.05]
```

rank weight를 배정한다.

그러나 feature 수가 6이 아니면
paper rank weight를 truncate/renormalize하지 않고:

```text
MDI / MDI.sum()
```

을 사용한다.

따라서 feature set에 따라 weight 정책 자체가 달라지는 상태였다.

---

## 7.4 Relative feature

`[SNAPSHOT-VERIFIED]`

`relative` mode에서는
그룹별 reference upright를 기준으로
feature 차이를 계산한다.

자체 촬영 데이터의 경우:

```text
각 subject-round의 첫 upright
```

를 reference로 선택하는 구조가 존재한다.

즉 participant/round reference 기반 calibration 성격의 feature가
handoff snapshot부터 존재했다.

---

# 8. 기타 도구

## 8.1 `check_recording.py`

`[SNAPSHOT-VERIFIED]`

raw recording을 재생하여:

- color frame 수
- depth frame 수
- 대략적 FPS
- 확인용 color/depth 이미지

를 생성/보고하는 단순 recording 확인 도구가 존재한다.

---

## 8.2 `compare_paper.py`

`[SNAPSHOT-VERIFIED]`

논문 Dataset과 자체 frames CSV를 비교하는 별도 분석 코드가 존재한다.

즉 handoff 시점부터
“원 논문 데이터와 자체 촬영 데이터를 비교하려는 연구 방향”은
코드 구조에 포함되어 있었다.

다만 이 코드가 어떤 연구 결론을 최종적으로 뒷받침하기 위해
작성됐는지에 대한 원래 의도 전체는 이 snapshot만으로 확정하지 않는다.

---

# 9. Handoff Snapshot에서 확인되는 주요 한계

본 절은 “당시 코드가 틀렸다”는 평가가 아니라,
**이후 연구용 controlled pipeline을 구축할 때 기준점이 된 상태**를 기록한다.

`[SNAPSHOT-VERIFIED]`

### 9.1 Capture validation 기준 불일치

```text
화면 목표       : 8~12 cm
live hint 기준  : 4 cm
final fail 기준 : 1.5 cm
```

가 공존한다.

### 9.2 Forward 판정 source가 고정되지 않음

face depth 실패 시 body fallback이 가능하다.

### 9.3 Recording identity 부재

촬영마다 고유한 persistent `recording_id`가 없다.

### 9.4 Analysis identity 부재

분석 실행마다 고유한 `analysis_run_id`가 없다.

### 9.5 Model artifact reproducibility 부족

MediaPipe 모델 URL이 `/latest/`이고
실제 artifact hash lock이 없다.

### 9.6 Frame schema가 canonical fixed schema가 아님

검출 상태에 따라 row key가 달라질 수 있다.

### 9.7 Hip raw observation 부재

향후 head–shoulder–hip 기반 body geometry를 만들기 위한
hip x/y/depth/validity가 저장되지 않는다.

### 9.8 RF RNG coupling

bootstrap과 tree random draw가 같은 RNG stream을 공유한다.

### 9.9 Reduced feature weight policy 일관성 부족

6 feature와 reduced feature에서 rank weight 정책이 다르다.

### 9.10 End-to-end research lineage 부재

다음을 하나의 identifier chain으로 연결하는 구조가 없다.

```text
capture
→ recording
→ analysis
→ frames
→ summary
→ RF result
```

---

# 10. 이 Snapshot만으로 확정할 수 없는 것

다음은 현재 자료만으로 확정하지 않는다.

## `[UNKNOWN]`

- 각 코드의 정확한 최초 작성자별 기여 범위
- 각 기능의 정확한 최초 작성 날짜
- threshold/ROI 값의 최초 선정 근거
- 4 cm / 1.5 cm / 8~12 cm가 서로 다르게 존재하게 된 정확한 개발 과정
- body fallback을 넣은 최초 의도
- shoulder ROI ±6 px를 선택한 최초 실험 근거
- MediaPipe `/latest/` 사용을 의도적으로 선택했는지 여부
- 과거 촬영 데이터 각각이 정확히 어떤 source code revision으로 만들어졌는지
- Git 도입 이전 사용자가 수정한 사항들의 정확한 순서와 날짜
- 이 snapshot이 과거 특정 보고 결과를 직접 생성한 정확한 실행본인지 여부

이 사항들은 추후 대화 기록, Git history, 별도 파일이 확인되는 경우에만
증거 수준을 올린다.

---

# 11. 이후 확인된 연구-controlled 개선 방향

> 주의:
> 이 절은 handoff snapshot 자체의 상태가 아니라,
> **이후 대화 및 Git-controlled 작업에서 확인된 후속 방향을 연결하기 위한 index**이다.
> 상세 근거는 각 Foundation Record에 기록한다.

`[CHAT-RECONSTRUCTED]`

후속 작업에서 다음과 같은 문제들이 단계적으로 정리되었다.

```text
RF RNG isolation
rank-weight policy 정리
relative evaluation 보완
external metric / drop logging 보강
root split provenance
forward protocol 8~12 cm 정렬
face-only forward hard gate
capture provenance
forward gate evidence
analysis provenance
canonical fixed schema / hip 설계
```

이 문서에서는 위 개선을 상세 설명하지 않는다.

그 역할은 다음 문서들이 담당한다.

```text
RETROSPECTIVE_01_PRE_GIT_CHANGES.md

PATCH_01_capture_provenance.md
PATCH_02_forward_gate_evidence.md
PATCH_03_analysis_provenance.md
...
```

---

# 12. Research History Boundary 정책

본 baseline 문서는 **과거를 완벽히 복원했다고 주장하지 않는다.**

현재 연구 기록의 원칙은 다음과 같다.

```text
과거 handoff snapshot
→ 실제 파일로 검증 가능한 상태만 기록

Git 이전 사용자 수정
→ 대화/코드/Git 비교로 가능한 만큼 소급 복원
→ 불확실성 표시

Git-tracked / progressively controlled phase
→ commit 단위 추적을 시작하고,
  schema / test / independent review / foundation record를 단계적으로 추가

Formal experiment 이후
→ contemporaneous decision log + experiment log + freeze log 적용
```

즉:

> “초기부터 모든 결정이 완벽하게 기록되어 있었다”

라고 소급해서 서술하지 않는다.

대신:

> “기존 prototype을 인수한 뒤 연구용 pipeline으로 점진적으로
> 통제·검증 가능한 상태로 전환했다”

는 실제 진행 과정을 기록한다.

---

# 13. 본 문서가 논문에서 의미하는 것

이 문서는 논문의 Method section에 그대로 삽입하기 위한 문서가 아니다.

역할은 다음과 같다.

1. 연구 시작 이전 prototype의 상태를 보존한다.
2. 어떤 문제가 이후 foundation 작업을 필요하게 했는지 설명할 근거를 남긴다.
3. 과거 설계 의도와 현재 연구 결정을 혼동하지 않게 한다.
4. Git 이전 변경을 소급 복원할 때 비교 기준을 제공한다.
5. 최종 논문 결과가 생성된 controlled pipeline과 legacy prototype을 구분한다.

---

# 14. 현재 문서 세트 상태와 다음 작업

현재 다음 소급 이력 문서가 작성되어 상호 검토되었다.

```text
BASELINE_00_HANDOFF_SNAPSHOT.md
RETROSPECTIVE_01_PRE_GIT_CHANGES.md
FOUNDATION_PRELUDE_00_algorithm_and_capture_hardening.md
PATCH_01_capture_provenance.md
PATCH_02_forward_gate_evidence.md
PATCH_03_analysis_provenance.md
```

현재 확인된 경계:

```text
Handoff Snapshot
→ Pre-Git RNG isolation
→ current research-main lineage root commit `64f8897`
→ Git-tracked hardening
→ provenance schema/setup
→ Foundation Patch 1~3
```

원본 handoff ZIP은 Git repository 밖 archival artifact로 보존하고,
본 문서에는 SHA-256으로 연결한다.

다음 순서:

```text
1. Claude 1차 READ-ONLY 검토 finding 반영본(v2) targeted 재검토
2. blocker가 없으면 canonical filename으로 확정
3. docs/history + docs/foundation commit/push
4. Patch 4 Design Freeze로 복귀
```

---

# 15. 최종 후보 상태에서 남겨 두는 불확실성

다음은 현재도 확정하지 않으며, 불확실성 자체를 기록으로 유지한다.

- 정확한 handoff 날짜가 별도 증거로 확인되지 않은 경우 그 날짜
- Git 이전 중간 시행착오/임시 버전의 존재 여부
- 일부 legacy threshold/ROI의 최초 선택 이유
- 각 과거 실험 결과의 정확한 실행 revision

이 항목은 문서 결함이 아니라,
소급 복원에서 확인할 수 없는 사실을 `UNKNOWN`으로 보존한 것이다.

본 문서는 현재 **Final Candidate**이며,
v2 targeted READ-ONLY 재검토 후 blocker가 없으면 canonical history record로 확정한다.
