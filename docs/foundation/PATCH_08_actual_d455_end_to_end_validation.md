# PATCH_08 — Actual D455 Measurement-Quality / End-to-End Validation

CAP-005 / Foundation Patch 8 — D455 Measurement-Quality and End-to-End Validation Design Freeze

- 문서 상태: **DESIGN FREEZE CONTRACT — DESIGN-FROZEN / IMPLEMENTATION PENDING / HARDWARE EXECUTION PENDING**
- Decision Log authority: `CAP-005 — Foundation Patch 8 D455 Measurement-Quality and End-to-End Validation Design Freeze`
- Status: **CONFIRMED**
- Resolves: `OPEN-006`
- Supersedes: None
- Logged: `2026-10-07`
- Decision timing: pre-implementation / pre-formal-hardware-execution Design Freeze
- Patch 8 state: **DESIGN-FROZEN**
- Patch 8 implementation: **PENDING**
- Patch 8 implementation audit: **PENDING**
- Patch 8 execution authorization / registration: **PENDING** — execution registry 미생성, `execution_id` 미발급
- Patch 8 hardware execution: **PENDING** — formal Patch 8 D455 execution은 수행되지 않았다
- Patch 8 final result: **NOT DETERMINED** — Patch 8은 COMPLETE가 아니다
- Design Freeze baseline:
  - branch: `main`
  - HEAD / origin/main: `b2e090ffbbbaf378f4f8243d424bd374e57e1e44` (`b2e090f` — `docs: finalize Patch 7 post-merge status`)
  - working tree: `clean`
- Semantic source: audited draft `PATCH_08_DESIGN_FREEZE_V5.1.1_AUDIT_DRAFT.md` (V5.1.1; 55553 bytes; SHA-256 `4747c181eee5280151cd332e43ef7ed28b953cb3be004f201c56c2818af5b199`)
- Final V5.1.1 independent READ-ONLY Design Freeze audit: **BLOCKER 0 / IMPORTANT 0 / MINOR 1 — READY FOR DESIGN-FREEZE COMMIT**. 단일 MINOR(E2-R1 wording)는 §62에 clarification-only로 반영했다.
- 선행 Foundation:
  - Foundation Prelude — DONE
  - Patch 1 Capture Recording Provenance — DONE
  - Patch 2 Forward Gate Evidence — DONE
  - Patch 3 Analysis Provenance — DONE
  - Patch 4 Canonical Fixed Frames Schema + Hip Raw Observations — DONE
  - Patch 4.5 MediaPipe Model Artifact Lock — DONE
  - Patch 5 End-to-End Lineage Hardening — COMPLETE / MAIN-INTEGRATED
  - Patch 6 Selection Manifest / Recapture Inclusion — COMPLETE / MAIN-INTEGRATED
  - Patch 7 Integrity Checker / Hardening — COMPLETE / MAIN-INTEGRATED

> 본 문서는 Patch 8 implementation과 formal D455 hardware execution 전에 고정한 exact contract이며 `CAP-005`의 canonical Foundation 상세 authority다.
> Repository authority로서의 CAP-005 Design Freeze는 본 문서와 대응하는 `CAP-005` Decision Log entry가 동일한 documentation-only Design Freeze commit에 포함될 때 효력이 발생한다.
> 그 commit 전에는 Python source/test를 수정하지 않으며 Patch 8 implementation 또는 formal D455 execution을 시작하지 않는다.

---

# 0. Authority status

본 문서는 V5.1.1 Design Freeze draft의 semantic content를 repository에 통합한 CAP-005 canonical Foundation document다.

V5.1.1 draft는 다음 independent READ-ONLY audit gate를 만족했다.

```text
BLOCKER = 0
IMPORTANT = 0
```

CAP-005는 본 문서와 `docs/research/RESEARCH_DECISION_LOG.md`의 `CAP-005` entry를 포함하는 documentation-only Design Freeze commit을 통해 repository authority가 된다.

Design Freeze commit 전 (working-tree integration candidate) 상태:

```text
Patch 8 implementation              NOT AUTHORIZED
formal Patch 8 D455 execution       NOT AUTHORIZED
formal participant collection       NOT AUTHORIZED
OPEN-006                            remains DEFERRED
```

Design Freeze commit 이후 authority 상태:

```text
CAP-005                             CONFIRMED
OPEN-006                            RESOLVED BY CAP-005
OPEN-002 / OPEN-003 / OPEN-004 / OPEN-005
                                    remain DEFERRED

Patch 8                             DESIGN-FROZEN
Patch 8 implementation              PENDING
                                    (§12 lifecycle에 따라 Design Freeze commit 이후 본 문서를 따라 시작)
Patch 8 implementation audit        PENDING
execution authorization /
registration                        PENDING (§12 step 6 / §15)
formal Patch 8 D455 execution       NOT AUTHORIZED until §12 steps 3–6 complete
formal participant collection       NOT AUTHORIZED
Patch 8 final result                NOT DETERMINED
```

이다.

Design Freeze commit은 Patch 8 COMPLETE, actual D455 validation PASS, 또는 formal hardware execution 수행을 의미하지 않는다.

---

# 1. Decision scope

CAP-005는 Foundation Patch 8의 actual Intel RealSense D455 validation protocol을 freeze한다.

본 결정이 확정하는 항목:

```text
candidate operating-range derivation
static distance grid
mandatory anchor distances

validation subject/setup
camera/setup fixation
hip observability
device/software environment
model provisioning
warm-up / settling

Design Freeze baseline
implementation baseline
implementation-audit gate

execution identity
execution pre-registration
execution-start boundary
session identity
single-shot execution semantics
authorized re-execution governance

planned slots
round namespace
acquisition order
repetition count

recording protocol identity
validation-control ledger
ledger tamper evidence

attempt lifecycle
result sealing
closed pre-lock classification
invalidation timing
machine evidence
manual termination semantics
retry rules

canonical recording binding
canonical analysis-run semantics

static analysis window
frame-coverage rule

landmark acquisition metrics
head / shoulder / hip depth-valid metrics
IPD validity rule
depth temporal repeatability

validation-only 3D geometry
calibration/deprojection rules

RGB-landmark + aligned-depth availability
distance-dependent stability

static PASS / FAIL
validated static measurement envelope
formal initial seating range

forward-phase availability population
forward-gate hardware validation
body-only negative validation

full-posture E2E validation
exact slot-131 PASS predicate

recording reconciliation
analysis reconciliation
repository-wide integrity baseline/closure

Patch 8 final PASS / FAIL
```

본 결정이 확정하지 않는 항목:

```text
F1 exact scientific formula
F2 exact scientific formula
formal scientific feature set

formal participant count
formal participant rounds
formal participant inclusion / exclusion

formal selection_policy_version

RF λ grid
RF model-selection rule

final EXPERIMENT_PROTOCOL

participant-specific calibration

new shoulder / hip posture hard gate

new body fallback capable of forward PASS

new scientific depth ROI

frames-schema/1.0.0 field
summary-schema/1.0.0 field

OPEN-005 formal workstation framing
```

---

# 2. Frozen Patch 1–7 authority remains unchanged

본 결정은 다음 frozen authority를 수정하지 않는다.

```text
CAP-001
forward gate = 0.08–0.12 m inclusive
source = face_only
body-only / mixed source cannot PASS

CAP-002
shoulder / hip movement threshold is not
a capture hard gate

CAP-003
candidate evidence
→ actual D455 validation
→ formal distance/range freeze

CAP-004
Patch 8 includes D455 measurement-quality validation

DATA-003
frames-schema/1.0.0
exactly 60 fields

PROV-004
MediaPipe model-lock authority

PROV-005
analysis / summary lineage

PROV-006 / PROV-007
selection authority

PROV-008 / PROV-009 / PROV-010 / PROV-011
Patch 7 integrity authority
```

다음 OPEN decisions도 계속 DEFERRED다.

```text
OPEN-002
OPEN-003
OPEN-004
OPEN-005
```

---

# 3. Pre-data declaration

다음 protocol values는 Patch 8 formal validation 결과를 보기 전에 고정한다.

```text
static grid:
0.60 / 0.70 / 0.80 / 0.90 / 1.00 m

static repetitions:
3

static hold:
10.0 s

frame coverage:
>= 0.85

landmark / conditional depth:
>= 0.95

complete RGB-D geometry:
>= 0.90

depth SD:
<= 10 mm

within-take geometry CV:
<= 3%

between-take geometry spread:
<= 3%

distance stability:
<= 5%

minimum valid n:
30

production-guide timeout:
15 s
```

2026-10-02 Early Hardware Preflight는 위 값의 선택 근거로 사용하지 않는다.

Early Hardware Preflight는:

```text
local engineering evidence only

≠ Patch 8 validation evidence
≠ formal research data
≠ acceptance-threshold evidence
```

이다.

---

## 3.1 Post-hoc protocol changes

Patch 8 결과를 본 이후 CAP-005의 protocol 값을 변경해야 하면 CAP-005 본문을 소급 수정하지 않는다.

새 append-only authority entry에:

```text
Supersedes: CAP-005

POST-HOC PROTOCOL CHANGE:
This change was made after observing Patch 8 validation results.
```

를 명시한다.

또한 최소:

```text
prior execution_id
prior ledger SHA-256
prior report SHA-256
prior result

observed recordings/runs
change rationale
changed protocol items
required re-execution scope
```

를 기록한다.

기존 evidence는 삭제하지 않는다.

---

# 4. Candidate operating-range derivation

## 4.1 Evidence inputs

Candidate range는 다음 세 축을 사용한다.

### Existing repository target

```text
0.70–0.80 m
```

### D455 official operating region

D455 manufacturer-published ideal range lower bound:

```text
0.60 m
```

Evidence/Source:

```text
RealSense
D455 official product specification
Ideal Range: 0.6 m to 6 m
```

Source URL / access date:

```text
RealSense D455 official product specification / product page
URL:
https://www.realsenseai.com/products/real-sense-depth-camera-d455f/

relevant fact:
Ideal Range: 0.6 m to 6 m
(page text: "Ideal Range .6 m to 6 m")

access date:
2026-10-07
```

### Workstation ergonomics

일반 computer workstation preferred viewing region:

```text
approximately 0.50–1.00 m
```

Evidence/Source:

```text
U.S. Occupational Safety and Health Administration
eTools: Computer Workstations
Monitors
Preferred viewing distance:
20–40 inches
approximately 50–100 cm
```

Source URL / access date:

```text
OSHA eTools: Computer Workstations
Workstation Components — Monitors
URL:
https://www.osha.gov/etools/computer-workstations/components/monitors/

relevant fact:
preferred viewing distance 20–40 inches
(approximately 50–100 cm; eye to front surface of the screen)

access date:
2026-10-07
```

CAP-005 repository integration에서 위 source URL과 access date를 Evidence/Source로 기록했다 (`RESEARCH_DECISION_LOG.md` `CAP-005` Evidence / Source에도 동일하게 기록).

Ergonomic distance는 D455 accuracy specification이 아니다.
OSHA range는 workstation ergonomic evidence로만 사용하며 D455 sensor accuracy / depth-quality 근거로 사용하지 않는다.

---

## 4.2 Exact candidate derivation

Lower bound:

```text
max(
    D455 ideal lower bound = 0.60 m,
    ergonomic lower region = 0.50 m
)

= 0.60 m
```

Upper bound:

```text
ergonomic upper region
= 1.00 m
```

따라서 static candidate region:

```text
0.60–1.00 m
```

이다.

Repository target:

```text
0.70 m
0.80 m
```

을 mandatory anchors로 포함하고 0.10 m spacing을 적용한다.

Frozen grid:

```text
0.60
0.70
0.80
0.90
1.00 m
```

이다.

특정 논문의 distance 하나를 그대로 채택하지 않는다.

---

# 5. Range concepts

## 5.1 Formal initial seating range

Patch 8 전체 PASS 후 formal initial seating guidance:

```text
0.70–0.80 m
```

이다.

## 5.2 Validated static measurement envelope

0.60–1.00 m grid는:

```text
D455
+
MediaPipe
+
aligned depth
+
current analysis pipeline
```

의 static robustness를 characterization하기 위한 것이다.

결과로 별도:

```text
validated static measurement envelope
```

를 산출한다.

Envelope가 더 넓더라도 initial seating range는 자동 확대하지 않는다.

---

# 6. Validation claim boundary

Patch 8은 다음 전체 system의 practical repeatability/availability를 검증한다.

```text
D455
+
RGB/depth alignment
+
MediaPipe landmark acquisition
+
current ROI/depth logic
+
current analysis implementation
+
human seated micro-motion
```

다음을 주장하지 않는다.

```text
pure sensor-only noise
absolute metrological accuracy
ground-truth anatomical accuracy
population generalizability
hardware temporal synchronization accuracy
```

---

# 7. Validation subject and physical setup

## 7.1 Reserved validation subject

Patch 8은:

```text
one adult validation subject
```

를 사용한다.

Formal execution 전 다른 pilot/formal dataset과 충돌하지 않는:

```text
reserved validation subject ID
```

를 하나 freeze한다.

Dataset role:

```text
pilot
```

이다.

Formal participant research data가 아니다.

---

## 7.2 Camera fixation

Static session 전 D455를 rigid mount에 고정한다.

기록:

```text
camera reference height
mount identity / description
camera position
pitch
yaw
roll
```

첫 canonical static take 이후 static session 종료까지 camera pose를 변경하지 않는다.

거리 변화는 subject/chair 이동으로 수행한다.

---

## 7.3 Camera disturbance precedence

첫 canonical static take 전 camera가 materially disturbed되면:

```text
setup reset
new setup_verified event
new pose measurement
```

후 시작할 수 있다.

첫 canonical static take 후 disturbance가 발생하면:

```text
§7.3 overrides generic retry rules

current execution = FAIL

earlier canonical takes remain evidence

same execution에서
camera를 다시 맞추고 계속하지 않는다
```

이다.

---

## 7.4 Camera-pose re-check

Static setup 시:

```text
mount witness marks
reference height
pitch
yaw
roll
```

을 기록한다.

Static session 종료 시 다시 측정한다.

다음 중 하나이면 material change로 취급한다.

```text
height difference > 5 mm

pitch / yaw / roll difference > 1 degree

or

witness mark visibly displaced
```

그 경우 execution FAIL이다.

---

## 7.5 Hip observability

전체 static grid에서:

```text
face
both shoulders
both hips
```

가 실제 영상에 포함되어야 한다.

Hip body surface를 다음이 가리지 않아야 한다.

```text
desk
chair arm
monitor
external object
operator
subject hands
subject forearms
```

새 visibility numeric threshold는 만들지 않는다.

---

## 7.6 Pre-attempt setup check

다음 check는 `attempt_start` 전에 수행한다.

```text
hips_visually_unobstructed
hands_forearms_clear_of_hips
external_occluder_absent
```

하나라도 false:

```text
attempt 시작 안 함
recording_id 생성 안 함
```

이다.

---

## 7.7 Environment

Static grid 동안:

```text
same chair
same room
same background
materially unchanged lighting
same camera mount
same camera configuration
```

을 유지한다.

---

## 7.8 Reposition

각 repetition 사이:

```text
previous seated pose fully released
chair/backrest contact reset
re-seat
nominal position re-established
```

한다.

---

## 7.9 OPEN-005 guardrail

본 setup은:

```text
Patch 8 validation setup only
```

이다.

`OPEN-005` formal experimental framing을 해결하지 않는다.

---

# 8. Device / stream baseline

```text
color:
1280 × 720

depth:
848 × 480

FPS:
15

depth:
aligned to color
```

를 유지한다.

Execution 중 다음을 임의 변경하지 않는다.

```text
resolution
FPS
depth unit
visual preset
emitter state
laser power
exposure policy
analysis ROI
production forward gate
MediaPipe model artifacts
```

---

# 9. Execution environment pinning

Execution 시작 시 기록:

```text
capture host identity
analysis host identity

operating system

Python version

mediapipe package version
pyrealsense2 version
RealSense SDK version
OpenCV version
NumPy version

D455 serial
D455 firmware

USB mode
depth scale
stream profiles
device options
```

Capture host와 analysis host가 다르더라도:

```text
pyrealsense2 / RealSense SDK version
```

은 동일한 pinned version을 사용해야 한다.

각 physical session 시작 시 environment snapshot을 ledger에 다시 기록한다.

Canonical provenance와 비교하여 차이가 있으면 execution을 계속하지 않는다.

---

# 10. Model provisioning

허용:

```text
A.
verified locked artifact copy

B.
existing PROV-004-compliant
verified provisioning/download
```

Provisioning 후:

```text
mediapipe_model_lock.json
```

과 identity/hash를 비교한다.

PASS 전 hardware execution 금지.

---

# 11. Warm-up / settling

Initial D455 warm-up:

```text
60 seconds
```

이다.

Subject/chair reposition 후:

```text
10 seconds
```

settling한다.

Objective retry 후에도:

```text
10 seconds
```

settling한다.

---

# 12. Authority / implementation lifecycle

```text
1. Patch 7 main baseline
   b2e090f

2. Patch 8 Design Freeze commit

3. Patch 8 implementation commit

4. regression tests

5. independent implementation audit

6. execution authorization / registration commit

7. formal hardware execution
```

이다.

---

# 13. Implementation audit prerequisite

Hardware execution 전:

```text
BLOCKER = 0
IMPORTANT = 0
```

인 implementation audit가 필요하다.

최소 확인:

```text
source
tests
static acquisition
static provenance
production sealing wrapper
closed pre-lock classifier
ledger
validity lock
metrics
reconciliation
integrity interaction
```

이다.

---

# 14. Pre-execution software smoke

Formal execution 전에 non-execution workspace에서:

```text
Python imports
model loading
dependencies
filesystem publication
synthetic/test analysis
batch publication
integrity checker invocation
```

을 smoke-test한다.

Formal D455 slot data를 만들지 않는다.

---

# 15. Execution pre-registration

첫 formal D455 use 전에 tracked append-only execution registry에:

```text
execution_id
status = AUTHORIZED / NOT_STARTED

reserved validation subject

Design Freeze commit
audited implementation commit

capture host
analysis host

planned date/session
```

를 기록한다.

예:

```text
docs/research/PATCH_08_EXECUTION_REGISTRY.md
```

이다.

---

# 16. Execution start

Formal execution은:

```text
pre-registered execution_id 아래
첫 formal slot의
attempt_start event
```

시점에 시작한다.

---

## 16.1 No hidden rehearsal

Audited tooling을 formal slot semantics로 사용한 D455 run을 사후에:

```text
rehearsal
```

로 재분류할 수 없다.

Engineering rehearsal은 formal slot/round/ledger를 사용하지 않는다.

---

# 17. Execution identity

하나의 formal execution:

```text
one execution_id
```

를 사용한다.

모든 ledger/report와 연결한다.

---

# 18. Session identity

Execution은 여러 physical session을 가질 수 있다.

각 session:

```text
session_id
```

를 가진다.

최소:

```text
static-grid
forward-gate
body-only-negative
E2E
```

를 구분한다.

---

# 19. Single-shot execution

첫 formal execution은 single-shot이다.

FAIL한 뒤 아무 기록 없이 새 clone/worktree에서 다시 실행할 수 없다.

---

# 20. Execution code pinning

Pre-registration에:

```text
audited_implementation_commit
```

을 기록한다.

Execution 중 source/test implementation을 변경하지 않는다.

Mid-execution code/environment 변경:

```text
current execution = FAIL / terminated
```

이다.

---

# 21. Authorized re-execution

재실행하려면 새 append-only authorization entry가 필요하다.

반드시:

```text
prior execution_id(s)
prior result(s)

prior ledger SHA-256
prior report SHA-256
or
no final report — execution terminated

reason for re-execution

implementation changed?
new audited implementation commit if changed

new execution_id
```

를 기록한다.

Foundation Record에는 **모든 authorized execution_id와 최종 disposition**을 기록한다.

---

## 21.1 Protocol-changing re-execution

Protocol도 변경하면:

```text
Supersedes: CAP-005
```

인 새 authority가 필요하다.

---

# 22. Clean execution workspace

Formal execution은 clean clone/worktree에서 시작한다.

Required:

```text
git status clean

audited implementation baseline

execution authorization present

no previous execution runtime artifacts mixed in
```

---

# 23. Runtime paths

Existing authority locations:

```text
data/
analysis/
results/
```

은 유지한다.

Patch 8 helper/governance outputs:

```text
validation/patch8/<execution_id>/
```

아래에 둔다.

예:

```text
ledger
sealed stdout/stderr
wrapper state
probe logs
metrics report
reconciliation report
execution report
```

Implementation은 `.gitignore`에:

```text
validation/
```

을 추가한다.

---

## 23.1 Workspace retention

Formal execution workspace와 runtime evidence는 최소:

```text
Patch 8 closure
+
main integration
+
post-merge regression
```

완료까지 보존한다.

Foundation Record에 retained workspace location을 기록한다.

---

# 24. Dedicated static acquisition path

Static slots 1–15는 `SEQ_CORE/SEQ_FULL`을 사용하지 않는다.

Dedicated static path:

```text
one recording
=
10.0 s upright hold
```

이다.

---

# 25. Static operator-visible feedback firewall

Static path에서는 **10 s settling 시작부터 `validity_locked`까지** 모든 operator-visible channel에 같은 restriction을 적용한다.

허용:

```text
phase identity
elapsed timer
recording state
plain RGB preview without analytical overlays
```

금지:

```text
D455 measured distance
depth-derived distance
closer value

jitter
DON'T MOVE

face/person availability status

landmark status
depth-valid status

quality metric
gate result
predicted PASS/FAIL

static stdout/stderr result output
```

Static stdout/stderr와 static result-bearing files도 `validity_locked` 전에는 sealed 상태다.

---

# 26. Static protocol identity

Static slots 1–15:

```text
protocol_version
=
patch8-d455-static-validation-v1.0.0
```

을 actual capture provenance에 기록한다.

Analyzer/summary lineage에서도 유지한다.

---

# 27. Production protocol identity

Slots:

```text
101–113
121
131
```

은:

```text
capture-forward-face-v2.0.0
```

을 유지한다.

---

# 28. Static capture provenance

Static path도 existing:

```text
capture-provenance/1.0.0
```

구조를 반드시 사용한다.

다음 required identity/sidecar semantics를 유지한다.

```text
recording_id
record_file
dataset_role
sidecar_files
protocol_version
```

Static recording에서는 existing production field를 새 의미로 repurpose하지 않는다.

따라서:

```text
target_range_m
start_distance
```

가 schema상 optional이면 static capture에서는 omit한다.

필수 representation이 필요하다면 current schema가 허용하는 neutral/null representation만 사용하고, production semantics를 바꾸지 않는다.

Nominal distance는 ledger authority다.

```text
nominal_distance
repetition_index
attempt_index
execution_id
```

를 existing scientific field에 재사용하지 않는다.

Static hold marker label은:

```text
upright
```

을 사용한다.

Static protocol/sequence identity는:

```text
patch8-d455-static-validation-v1.0.0
```

로 별도 구분한다.

Production forward constants를 static data로 위장해 기록하지 않는다.

---

# 29. Static stabilization

```text
physical placement
→ 10 s settling
→ attempt_start / capture
→ 10 s static recording
```

순서다.

Settling은 canonical recording data가 아니다.

---

# 30. Static outer-distance behavior

Static path에서는 production 0.70–0.80 live start guide를 사용하지 않는다.

Independent placement를 사용한다.

---

# 31. Independent physical distance reference

Camera reference:

```text
front reference plane of D455 housing
at center of stereo/depth module
```

Subject reference:

```text
tip-of-nose vertical reference plane
in neutral seated upright pose
```

Measurement:

```text
approximately along optical axis
```

이다.

Static:

```text
nominal ±0.02 m
```

Production initial placement:

```text
0.75 ±0.02 m
```

이다.

---

# 32. Static slot mapping

```text
5 distances × 3 repetitions = 15 slots
```

Order:

```text
cycle 1:
0.60 → 0.70 → 0.80 → 0.90 → 1.00

cycle 2:
0.60 → 0.70 → 0.80 → 0.90 → 1.00

cycle 3:
0.60 → 0.70 → 0.80 → 0.90 → 1.00
```

Rounds:

```text
1–5
6–10
11–15
```

이다.

---

# 33. Non-static rounds

```text
101 forward_head / below
102 forward_head / pass
103 forward_head / above

111 body_forward / below
112 body_forward / pass
113 body_forward / above

121 body-only negative
designated phase = body_forward

131 full-posture E2E
```

이다.

---

# 34. Patch 6 selection boundary

Patch 8 retry bookkeeping은 scientific selection이 아니다.

Patch 6 selection schemas를 재정의하지 않는다.

---

# 35. Validation ledger

Format:

```text
patch8-validation-control/1.0.0
```

Mandatory path:

```text
validation/patch8/<execution_id>/
patch8_validation_ledger.jsonl
```

이다.

---

# 36. Ledger fields

Every event:

```text
ledger_format_version
execution_id
session_id
event_id
event_timestamp_utc
event_type
```

Attempt events:

```text
subject
round
attempt_index
validation_protocol_version
recording_id where available
status
reason_code where applicable
```

Static:

```text
nominal_distance
repetition_index
```

을 추가한다.

---

# 37. Ledger serialization / hash chain

Canonical JSON serialization:

```text
UTF-8
sort_keys = true
separators = (",", ":")
ensure_ascii = false
no insignificant whitespace
```

각 event:

```text
previous_event_sha256
event_sha256
```

를 가진다.

First event:

```text
previous_event_sha256 = null
```

이다.

`event_sha256` 자체를 제외한 canonical event serialization을 SHA-256한다.

기존 line 수정/삭제 금지.

---

# 38. Correction immutability

Validity lock 이후 correction으로 다음을 바꾸지 않는다.

```text
execution_id
session_id
subject
round
attempt_index

acquisition validity
validity reason

canonical recording

protocol_version

canonical analysis run

PASS / FAIL
```

---

# 39. Attempt reservation / recording binding

Setup checks 후:

```text
attempt_start
```

를 기록한다.

Production/static capture launch 전 `data/` recording identity inventory를 snapshot한다.

Capture 종료 후 pre/post inventory diff로 recording identity를 bind한다.

Pre-lock binding 시 `_camera.json`이 존재하는 경우 다음 key만 읽을 수 있다.

```text
recording_id
record_file
```

기타 content는 pre-lock result/information source로 사용하지 않는다.

---

## 39.1 Zero recording requires stage-aware classification

`zero new recording_id`만으로:

```text
RAW_FILE_NOT_CREATED
```

라고 분류하지 않는다.

먼저:

```text
GUIDE / PRE-RESERVATION stage
```

인지:

```text
POST-RESERVATION recording stage
```

인지 구분한다.

Closed rule은 §47을 따른다.

---

# 40. Attempt result firewall

Lifecycle:

```text
attempt_start

→ child launch / acquisition

→ child terminates

→ capture_finished

→ recording-stage classification

→ pre-result structural probes

→ validity_locked

→ attempt_end

→ only after lock:
   unseal result files/logs
   gate/quality inspection
   analysis
   Patch 8 metrics
```

핵심:

```text
acquisition validity is immutable
before result inspection
```

이다.

---

# 41. Production child-process sealing

Production slots:

```text
101–113
121
131
```

은 `capture_d455.py`를 child process로 실행한다.

stdout/stderr를 live-forward하지 않는다.

Mandatory:

```text
validation/patch8/<execution_id>/logs/
<attempt>.stdout.log

validation/patch8/<execution_id>/logs/
<attempt>.stderr.log
```

이다.

---

## 41.1 Result-bearing files sealed before lock

Pre-lock content inspection 금지:

```text
_quality.json
_samples.csv
_markers.csv

sealed stdout
sealed stderr

forward_gate_evidence

quality verdict
closer_m

person ratio
face ratio
frame ratio
```

Static path에도 동일한 principle을 적용한다.

---

# 42. Production live UI

Existing production UI semantics는 변경하지 않는다.

따라서 operator가 live D455 feedback을 볼 수 있다.

그 이유로 production slots에서는:

```text
EXTERNAL_PHYSICAL_INTERRUPTION
CAMERA_MOUNT_PHYSICALLY_DISTURBED
```

를 retry-eligible invalid reason으로 인정하지 않는다.

Live result를 본 뒤 사람 판단으로 retry하는 경로를 만들지 않는다.

---

# 43. Static operator reasons

Static utility는 §25 firewall을 사용하므로 static에서만:

```text
EXTERNAL_PHYSICAL_INTERRUPTION
```

을 retry-eligible operator reason으로 사용할 수 있다.

단 recording 중 즉시 ledger 기록이 필요하다.

`CAMERA_MOUNT_PHYSICALLY_DISTURBED`는:

```text
before first canonical static take:
retry/setup reset 가능

after first canonical static take:
§7.3 execution FAIL
```

이다.

---

# 44. Closed machine-invalid reason set

Retry-eligible machine reasons:

```text
CAMERA_DISCONNECT
USB_STREAM_FAILURE
POWER_FAILURE

RAW_FILE_NOT_CREATED
RAW_FILE_UNREADABLE_OR_CORRUPT
```

이다.

그러나 이 label은 §47의 closed classification을 통과해야 한다.

---

# 45. Machine evidence principle

단순:

```text
nonzero exit
signal
process disappeared
```

만으로 machine-invalid를 선언하지 않는다.

Operator-triggered termination과 genuine machine failure를 구분해야 한다.

분류 불가능하면:

```text
acquisition-valid / fail-closed
```

로 처리한다.

---

# 46. Manual termination rule

다음은 모두 manual abort다.

```text
q

Ctrl-C / SIGINT initiated by operator

SIGTERM initiated by operator

operator-issued kill

closing terminal/window/process manually
```

그 자체로 retry 권한을 주지 않는다.

Nonzero exit 또는 signal alone도 machine evidence가 아니다.

---

# 47. CLOSED PRE-LOCK CLASSIFICATION TABLE

본 section은 모든 generic retry rule보다 우선한다.

## 47.1 Guide/pre-reservation stage

Production path에서 아직 recording_id가 reserve되지 않은 상태는 guide/pre-reservation stage다.

### Guide q

```text
recording_id absent
process exits after guide q
```

결과:

```text
GUIDE_NOT_SATISFIED
acquisition_valid = true
canonical FAIL evidence
NO RETRY
```

이다.

`RAW_FILE_NOT_CREATED`가 아니다.

### Guide timeout

Timeout clock:

```text
child process launch
→ first valid _camera.json recording reservation
```

까지다.

15 seconds 안에 reservation이 생기지 않으면 orchestration이 child를 terminate한다.

결과:

```text
GUIDE_NOT_SATISFIED
acquisition_valid = true
canonical FAIL evidence
NO RETRY
```

이다.

Orchestration-issued timeout kill은 machine failure가 아니다.

### Production `s` skip

Formal production Patch 8 slot에서는 `s` guide skip 사용을 금지한다.

만약 사용되어 recording이 `_skipped` mode로 생성되었다면:

```text
recording은 삭제하지 않는다
validity lock 이후 mode 확인

GUIDE_NOT_SATISFIED
canonical FAIL evidence
NO RETRY
```

이다.

Skip을 machine failure로 재분류하지 않는다.

---

## 47.2 Post-reservation stage

Recording_id가 이미 reserve된 뒤 raw recording이 생성되지 않은 경우에만:

```text
RAW_FILE_NOT_CREATED
```

후보가 된다.

다만 machine evidence가 있어야 retry 가능하다.

Operator abort 또는 operator termination에 의해 raw가 없는 경우:

```text
MANUAL_ABORT
NO RETRY
```

이다.

---

## 47.3 Operator termination

다음은 항상:

```text
MANUAL_ABORT
```

이다.

```text
q
operator SIGINT
operator SIGTERM
operator kill
manual terminal/window closure
```

Result:

```text
NO RETRY
```

이다.

---

## 47.4 POWER_FAILURE

`POWER_FAILURE`는 다음과 같은 독립적인 power-loss evidence가 있어야 한다.

예:

```text
device/host power-loss event
UPS/system power event
unexpected hardware power loss
```

단순 process signal/nonzero exit은 POWER_FAILURE evidence가 아니다.

---

## 47.5 CAMERA_DISCONNECT / USB_STREAM_FAILURE

Pre-lock permitted evidence:

```text
post-exit D455/USB device enumeration

structured child exit status

whitelisted exception class extraction
```

이다.

Sealed stderr 전체를 operator가 읽지 않는다.

필요하면 wrapper가:

```text
exception class identifier only
```

를 whitelisted extractor로 파싱한다.

Error message body/quality output은 lock 전 노출하지 않는다.

분류가 객관적으로 안 되면:

```text
acquisition-valid
NO RETRY
```

이다.

---

## 47.6 Raw readability probe

`RAW_FILE_UNREADABLE_OR_CORRUPT` probe는 다음으로 제한한다.

```text
file exists

file can be opened

at least one readable color frame exists

at least one readable depth frame exists
```

Pre-lock에서 금지:

```text
total frame count

frame ratio

drop ratio

gap analysis

temporal completeness analysis

landmark analysis

face/person analysis

quality analysis

forward-gate analysis
```

Partial frame loss는 machine-invalid reason이 아니다.

나중에 frame coverage metric에서 FAIL한다.

---

## 47.7 Unclassified crash

Child가 예상치 못하게 종료됐지만 closed evidence로 machine reason을 분류할 수 없으면:

```text
UNCLASSIFIED_TERMINATION

acquisition_valid = true
NO RETRY
```

이다.

Fail-closed다.

---

# 48. Validity lock

Pre-lock classification 후:

```text
validity_locked
```

event를 기록한다.

포함:

```text
acquisition_valid
reason_code
machine_evidence_ref where applicable
```

이후 validity/canonical eligibility를 변경하지 않는다.

---

# 49. Static retry

Static slot:

```text
max 3 attempts
```

이다.

첫 non-invalid attempt가 canonical이다.

Retry는 preceding attempt가 pre-result `validity_locked`에서 objective invalid로 확정된 경우만 허용한다.

---

# 50. Production attempt launch

Production:

```text
one attempt_start
=
one child process launch
```

이다.

동일 attempt를 relaunch하지 않는다.

---

# 51. Production initial placement / guide

Independent initial placement:

```text
0.75 ±0.02 m
```

이다.

Production guide skip은 금지한다.

15 s reservation timeout은 §47을 따른다.

---

# 52. Explicit analysis

Canonical recording을 explicit identity로 분석한다.

Broad subject glob로 canonical selection하지 않는다.

Static:

```text
analysis_mode = extract_raw
one recording per invocation
step_effective = 1
```

이다.

---

# 53. Canonical analysis run

Manifest:

```text
status = completed
```

가 된 첫 run이 canonical이다.

첫 completed run이:

```text
analysis_mode != extract_raw

or

multiple recordings

or

step_effective != 1
```

이면 그 run 자체가 canonical FAIL이다.

좋은 run으로 교체하지 않는다.

---

# 54. Analysis retry

첫 run이 completed 되기 전 객관적 infrastructure failure만 재분석을 허용한다.

Machine evidence와:

```text
analysis_infrastructure_failure
```

event가 필요하다.

---

# 55. Static analysis window

```text
1.0 <= t < 9.5
```

이다.

---

# 56. Static frame coverage

```text
N_static
=
canonical rows within frozen window

N_static / 127.5 >= 0.85

therefore:
N_static >= 109
```

이다.

---

# 57. Landmark acquisition

Denominator:

```text
N_static
```

이다.

다음 모두:

```text
face_detection_rate             >= 0.95
face_mesh_rate                  >= 0.95
pose_detection_rate             >= 0.95
bilateral_shoulder_inframe_rate >= 0.95
bilateral_hip_inframe_rate      >= 0.95
```

이어야 한다.

---

# 58. Head depth-valid

Valid:

```text
face_detected
&& face_depth_valid
&& face_depth_source == "bbox_roi"
```

Rate:

```text
valid / face_detected
```

Mandatory:

```text
>= 0.95
```

이다.

---

# 59. Shoulder / hip depth-valid

각 point:

```text
count(point_valid && point_depth_valid)
/
count(point_valid)
```

Mandatory:

```text
>= 0.95
```

이다.

---

# 60. Complete RGB-D geometry

Complete mask:

```text
face_detected
face_mesh_detected
pose_detected

face_depth_valid
face_depth_source == bbox_roi

left/right shoulder valid + depth-valid

left/right hip valid + depth-valid
```

Rate:

```text
complete / N_static >= 0.90
```

이다.

---

# 61. Minimum-n

Within-take scalar metrics:

```text
depth temporal SD:
each of the five depth series defined in §62

IPD take median

shoulder_width_3d
hip_width_3d
trunk_length_3d
```

은:

```text
n >= 30
```

이어야 한다.

Depth temporal SD의 `n >= 30` requirement는 §62의 다섯 depth series 각각에 독립적으로 적용한다.

---

# 62. Depth temporal repeatability — exact series

10 mm temporal-SD acceptance criterion은 정확히 다음 5개 depth series에 각각 적용한다.

```text
1. face depth:
   z_face_m

2. left shoulder depth:
   z_lsh_m

3. right shoulder depth:
   z_rsh_m

4. left hip depth:
   left_hip_depth_m

5. right hip depth:
   right_hip_depth_m
```

각 series의 valid-frame mask는 다음과 같다.

### Face depth

```text
face_detected == true
&& face_depth_valid == true
&& face_depth_source == "bbox_roi"
&& z_face_m is not None
&& isfinite(z_face_m)
&& z_face_m > 0
```

`oval_center_roi` fallback sample은 blocking face temporal-SD series에 포함하지 않는다.

### Left shoulder depth

```text
lsh_valid == true
&& lsh_depth_valid == true
&& z_lsh_m is not None
&& isfinite(z_lsh_m)
&& z_lsh_m > 0
```

### Right shoulder depth

```text
rsh_valid == true
&& rsh_depth_valid == true
&& z_rsh_m is not None
&& isfinite(z_rsh_m)
&& z_rsh_m > 0
```

### Left hip depth

```text
left_hip_valid == true
&& left_hip_depth_valid == true
&& left_hip_depth_m is not None
&& isfinite(left_hip_depth_m)
&& left_hip_depth_m > 0
```

### Right hip depth

```text
right_hip_valid == true
&& right_hip_depth_valid == true
&& right_hip_depth_m is not None
&& isfinite(right_hip_depth_m)
&& right_hip_depth_m > 0
```

### Sample population — E2-R1 wording clarification

각 depth series의 sample은 정확히 다음이다.

```text
그 canonical take의 canonical rows
within the frozen static analysis window (§55: 1.0 <= t < 9.5)

INTERSECTED WITH

그 series의 위 validity mask
```

그 외 **어떠한 추가 filtering도 허용하지 않는다** (favorable이든 neutral이든 무관).

즉 sample population은:

```text
frozen static time window
INTERSECT
the exact validity mask of that series
```

뿐이다.

본 문구는 V5.1.1 final independent re-audit의 단일 MINOR(E2-R1 wording)를 반영한 **clarification only**다. 다음을 변경하지 않는다.

```text
the five depth series
n >= 30
ddof = 1
<= 10 mm threshold
validity masks
per-take semantics
three-take static point semantics
```

각 depth series는 각 canonical take에서 독립적으로:

```text
n >= 30
```

이어야 한다.

`n < 30`이면 해당 series는:

```text
not evaluable
→ canonical take FAIL
```

이다.

각 series의 temporal repeatability metric은:

```text
sample standard deviation
ddof = 1

temporal_depth_sd_mm
=
sample_sd(valid depth_m samples) × 1000
```

이다.

각 5개 series 모두:

```text
temporal_depth_sd_mm <= 10 mm
```

이어야 해당 canonical take가 depth temporal repeatability PASS다.

5개 중 하나라도 FAIL 또는 not evaluable이면 그 canonical take는 FAIL이다.

모든 nominal distance에서 세 canonical take 각각이 이 criterion을 PASS해야 한다.

Favorable outlier removal은 금지한다.

---

# 63. IPD rule

Valid IPD frame:

```text
ipd_cm is not None
finite
> 0

face_detected
face_depth_valid
face_depth_source == bbox_roi
```

Required:

```text
valid_ipd_n >= 30
```

이다.

Take metric:

```text
median(valid ipd_cm)
```

이다.

---

# 64. 3D point definitions

```text
P =
SDK deproject(
    color intrinsics,
    pixel,
    aligned_depth
)
```

Eligibility:

```text
shoulder:
*_valid && *_depth_valid

hip:
*_valid && *_depth_valid
```

이다.

---

# 65. 3D geometry

```text
shoulder_width_3d
=
||P_lsh - P_rsh||

hip_width_3d
=
||P_lhip - P_rhip||

M_sh
=
(P_lsh + P_rsh) / 2

M_hip
=
(P_lhip + P_rhip) / 2

trunk_length_3d
=
||M_sh - M_hip||
```

이다.

Validation-only이며 OPEN-003/F2를 결정하지 않는다.

---

# 66. Valid 3D scalar sample

각 blocking 3D scalar sample:

```text
finite
&& > 0
```

이어야 한다.

Non-finite/non-positive sample은 valid n에서 제외한다.

그 결과 n < 30이면 FAIL이다.

---

# 67. WITHIN-TAKE CV QUANTITY LIST — EXACT

Within-take:

```text
CV <= 0.03
```

을 적용하는 quantity는 **정확히 다음 세 개**다.

```text
shoulder_width_3d
hip_width_3d
trunk_length_3d
```

Metric:

```text
sample SD(ddof=1)
/
median
```

이다.

다음에는 within-take 3% CV threshold를 적용하지 않는다.

```text
ipd_cm
head depth
shoulder depth
hip depth
midpoint coordinate components
```

`ipd_cm`은 §63 evaluability와 §70 distance stability에서만 blocking이다.

---

# 68. BETWEEN-TAKE SPREAD QUANTITY LIST — EXACT

Same nominal distance의 세 canonical take에서:

```text
between_take_relative_spread
=
(max(take_medians) - min(take_medians))
/
median(take_medians)
```

을 계산한다.

```text
<= 0.03
```

threshold를 적용하는 quantity는 **정확히**:

```text
shoulder_width_3d
hip_width_3d
trunk_length_3d
```

이다.

`ipd_cm`에는 3% between-take spread threshold를 적용하지 않는다.

IPD는 distance stability metric에서만 blocking한다.

---

# 69. Distance median

각 blocking quantity의 각 nominal distance:

```text
distance_median
=
median(
    canonical take 1 median,
    canonical take 2 median,
    canonical take 3 median
)
```

이다.

---

# 70. Distance-dependent stability

Blocking quantities는 정확히:

```text
ipd_cm
shoulder_width_3d
hip_width_3d
trunk_length_3d
```

이다.

Anchor:

```text
0.70 m take medians ×3
+
0.80 m take medians ×3
```

총 6개 conventional median이다.

Metric:

```text
abs(distance_median - anchor)
/
anchor
<= 0.05
```

이다.

---

# 71. Static point PASS

Distance point PASS는:

```text
3 canonical takes

frame coverage PASS

landmark acquisition PASS

conditional depth PASS

complete RGB-D PASS

all five §62 depth series PASS
for every canonical take

IPD evaluability PASS

within-take CV PASS
for exactly the 3 quantities in §67

between-take spread PASS
for exactly the 3 quantities in §68

distance stability PASS
for exactly the 4 quantities in §70
```

을 모두 만족해야 한다.

---

# 72. Mandatory anchors

모든:

```text
0.60
0.70
0.80
0.90
1.00
```

을 실행한다.

Mandatory:

```text
0.70
0.80
```

이다.

둘 중 하나 FAIL이면 range validation FAIL이다.

---

# 73. Static envelope

Anchors가 모두 PASS한 경우:

```text
both anchors를 포함하는
maximal contiguous PASS grid interval
```

이다.

Anchor fail:

```text
envelope = NONE
```

이다.

---

# 74. Formal initial seating range

Patch 8 전체 PASS 후:

```text
0.70–0.80 m
```

로 freeze한다.

---

# 75. FORWARD AVAILABILITY ACCEPTANCE POPULATION — EXACT

§75 availability metrics는 **pooling하지 않고 canonical recording의 designated phase별로 개별 평가**한다.

적용 population은 정확히 다음과 같다.

| Slot | Evaluated phase under §75 | Blocking |
|---|---|---|
| 101 | `forward_head` | YES |
| 102 | `forward_head` | YES |
| 103 | `forward_head` | YES |
| 111 | `body_forward` | YES |
| 112 | `body_forward` | YES |
| 113 | `body_forward` | YES |
| 121 | none — use §80 only | NO |
| 131 | `forward_head` | YES |
| 131 | `body_forward` | YES |

101–103의 non-designated `body_forward` phase는 §75 PASS/FAIL population이 아니다.

111–113의 non-designated `forward_head` phase도 §75 PASS/FAIL population이 아니다.

Slot 121은 body-only negative protocol만 사용하므로 §75 generic availability criterion에서 제외한다.

Slot 131은 두 forward phase를 각각 독립적으로 PASS해야 한다.

---

## 75.1 Forward phase window

각 evaluated phase:

```text
1.0 < t < phase_duration - 0.5
```

이다.

10 s phase:

```text
1.0 < t < 9.5
```

이다.

---

## 75.2 Forward coverage

각 evaluated phase individually:

```text
N_forward / 127.5 >= 0.85
N_forward >= 109
```

이어야 한다.

---

## 75.3 Forward blocking rates

각 evaluated phase individually:

```text
face detection              >= 0.95
face mesh                   >= 0.95
pose detection              >= 0.95

head depth-valid            >= 0.95

left shoulder depth-valid   >= 0.95
right shoulder depth-valid  >= 0.95

left hip depth-valid        >= 0.95
right hip depth-valid       >= 0.95

complete RGB-D geometry     >= 0.90
```

이어야 한다.

Recording 간 pooling은 하지 않는다.

---

# 76. Production forward gate

Frozen production authority:

```text
0.08–0.12 m inclusive
face_only
```

이다.

Validation bands:

```text
below:
0.05 <= closer_m <= 0.07

pass:
0.09 <= closer_m <= 0.11

above:
0.13 <= closer_m <= 0.15
```

이다.

---

# 77. Forward evidence

Canonical:

```text
quality.json
→ forward_gate_evidence
```

이다.

---

# 78. Forward slots

```text
101 forward_head below
102 forward_head pass
103 forward_head above

111 body_forward below
112 body_forward pass
113 body_forward above
```

이다.

---

# 79. Forward slot attempt semantics

각 slot max:

```text
3 attempts
```

이다.

Attempt classification:

```text
objective machine-invalid
→ retry allowed

GUIDE_NOT_SATISFIED
→ FAIL, no retry

manual abort
→ FAIL, no retry

no gate evidence on acquisition-valid recording
→ FAIL

closer_m == null
→ FAIL

result inconsistent with closer_m
→ FAIL

in-band
→ canonical class evidence

non-null, internally consistent,
out-of-band
→ TARGET_MISS
→ bounded retry
```

이다.

---

# 80. Body-only negative slot

```text
round = 121
sequence = SEQ_CORE
designated phase = body_forward
```

이다.

Required target condition:

```text
reference face sufficient

current face insufficient

valid body-mode samples exist

closer_m == null

forward_gate_result != pass

forward_gate_reasons exactly:
["insufficient_current_face_samples"]
```

이다.

Body evidence:

```text
samples.csv

mode == "body"
distance_m non-null
inside frozen phase window
```

이다.

Dispositions:

```text
reference face insufficient
→ FAIL, no retry

current face still sufficient
→ target miss, bounded retry

current face insufficient + no body sample
→ target miss, bounded retry

quality/gate evidence absent
on acquisition-valid attempt
→ FAIL

target condition achieved but gate PASS
→ immediate FAIL
```

이다.

Max 3 attempts.

---

# 81. Slot 131 — EXACT E2E PASS PREDICATE

Slot:

```text
round = 131
sequence = SEQ_FULL
dataset_role = pilot
```

이다.

Maximum total acquisition attempts:

```text
3
```

이다.

Retry는 preceding attempt가 §47/§48에서 objective machine-invalid로 locked된 경우에만 허용한다.

세 attempts 모두 machine-invalid이면:

```text
slot 131 = FAIL
Patch 8 E2E = FAIL
```

이다.

첫 acquisition-valid attempt가 canonical E2E recording이다.

---

## 81.1 Capture verdict

Canonical slot-131 recording:

```text
capture quality verdict == "ok"
```

이어야 한다.

다음은 Patch 8 E2E closure FAIL이다.

```text
retake
ok_with_warnings
fail
aborted
or other non-ok result
```

이 `ok` requirement는 **Patch 8 validation closure 전용**이다.

Formal experiment에서 `ok_with_warnings`를 허용할지는 여전히 OPEN-005 / future experiment authority의 문제이며 CAP-005가 결정하지 않는다.

---

## 81.2 Forward availability

Canonical slot-131 recording에서:

```text
forward_head
```

가 §75 PASS해야 한다.

그리고:

```text
body_forward
```

도 §75 PASS해야 한다.

두 phase를 pooling하지 않는다.

---

## 81.3 Forward gate

Canonical slot-131 recording의 production `forward_gate_evidence`에서:

```text
forward_head:
forward_gate_result == pass

body_forward:
forward_gate_result == pass
```

둘 다 필요하다.

Face-only production gate semantics를 그대로 사용한다.

Body fallback 또는 mixed source는 PASS 근거가 될 수 없다.

---

## 81.4 Analysis predicate

Canonical slot-131 analysis는:

```text
analysis_mode == extract_raw
one recording per invocation
status == completed
step_effective == 1
```

이어야 한다.

---

## 81.5 Artifact / lineage predicate

다음이 모두 존재하고 authority-consistent해야 한다.

```text
raw recording

capture provenance

camera sidecar
markers sidecar
samples sidecar
quality sidecar

analysis manifest

canonical frames

analysis_batch.json

canonical summary_steps.csv

recording_id lineage

analysis_run_id lineage

artifact hashes

MediaPipe model lock identity
```

---

## 81.6 Reconciliation / integrity predicate

Slot 131 관련:

```text
recording-ledger reconciliation PASS

analysis-ledger reconciliation PASS
```

가 필요하다.

Patch 8 전체 closure에서는 repository checker도 별도로 PASS해야 한다.

---

## 81.7 Other SEQ_FULL phases

Slot 131의 `forward_head`와 `body_forward` 외 SEQ_FULL phase에는 CAP-005가 별도의 새로운 Patch 8 landmark/depth percentage threshold를 추가하지 않는다.

해당 phase의 기본 capture health는:

```text
capture verdict == ok
```

및 existing lineage/integrity requirements로 관리한다.

이는 future scientific phase acceptance rule을 새로 결정하지 않기 위함이다.

---

## 81.8 Slot 131 PASS

따라서:

```text
slot_131_pass =
    canonical acquisition-valid recording exists

    AND capture verdict == ok

    AND forward_head §75 PASS
    AND body_forward §75 PASS

    AND forward_head production gate PASS
    AND body_forward production gate PASS

    AND canonical analysis predicate PASS

    AND artifact/lineage predicate PASS

    AND recording reconciliation PASS
    AND analysis reconciliation PASS
```

이다.

하나라도 false이면:

```text
slot 131 FAIL
```

이다.

Result-based retry는 금지한다.

---

# 82. Recording reconciliation

모든 execution-created raw recording은:

```text
exactly one attempt_start
+
exactly one capture_finished binding
```

과 대응해야 한다.

Matching:

```text
subject
round
recording_id
protocol_version
```

이다.

---

# 83. Analysis reconciliation

Canonical recording마다:

```text
exactly one canonical_analysis_run_id
```

가 있어야 한다.

Unlogged completed run은 reconciliation FAIL이다.

---

# 84. Integrity baseline

Formal hardware execution 전:

```text
integrity_check.py
```

whole repository root 실행.

Required:

```text
exit status == 0
PASS summary
ERROR count == 0
```

이다.

---

# 85. Closure integrity

Closure에서도:

```text
exit status == 0
PASS summary
ERROR count == 0
```

이 필요하다.

WARNING은 기록하되 자동 FAIL은 아니다.

Preserved evidence 때문에 ERROR가 생겨도 삭제해서 해결하지 않는다.

---

# 86. E2E authority chain

```text
raw

→ capture provenance

→ immutable analysis run

→ canonical frames

→ analysis_batch.json

→ canonical summary
```

이다.

---

# 87. Final Foundation Record

최소:

```text
CAP-005 identity

Design Freeze commit

implementation commit
implementation audit

ALL authorized execution_id values
and each execution disposition

execution authorization commit

capture/analysis environment

D455 serial
firmware

SDK/package versions

model provisioning
model hashes

physical setup
camera pose

static slots and attempts

forward slots

body-only slot

E2E slot

canonical recordings

canonical analysis runs

ledger hash
last ledger-event hash

report hash

raw / analysis hashes

metric results

static outcomes
static envelope
formal seating range

forward outcomes
body-only result
E2E result

recording reconciliation

analysis reconciliation

pre-hardware integrity

closure integrity

final Patch 8 result
```

를 기록한다.

CAP-005 Evidence/Source에는 실제 source URL과 access date도 기록한다.

---

# 88. Explicit non-decisions

다음은 validation-only quantities다.

```text
head bbox depth
ipd_cm
shoulder_width_3d
hip_width_3d
shoulder midpoint
hip midpoint
trunk_length_3d
```

이는:

```text
OPEN-002 resolution 아님
OPEN-003 resolution 아님

F1 definition 아님
F2 definition 아님
```

이다.

`ok` requirement도 Patch 8 validation closure 전용이며 OPEN-005를 해결하지 않는다.

---

# 89. Companion-document integration

Design Freeze integration 시 반드시 sync:

```text
docs/research/RESEARCH_DECISION_LOG.md
docs/research/AIoT_RESEARCH_MASTER.md
RESEARCH_DATA_SCHEMA.md
AGENTS.md
CLAUDE.md
```

Mandatory Foundation doc:

```text
docs/foundation/
PATCH_08_actual_d455_end_to_end_validation.md
```

이다.

---

## 89.1 Decision Log

Append-only:

```text
CAP-005

Status: CONFIRMED
Resolves: OPEN-006
Supersedes: None
Impact: ...
Evidence / Source: ...
```

를 추가한다.

Historical OPEN-006는 back-edit하지 않는다.

---

## 89.2 Master

```text
OPEN-006 resolved by CAP-005

Patch 8:
DESIGN-FROZEN
IMPLEMENTATION PENDING
HARDWARE EXECUTION PENDING
```

으로 sync한다.

---

## 89.3 Schema

Scientific schema field/version을 바꾸지 않는다.

명시:

```text
static protocol_version =
patch8-d455-static-validation-v1.0.0

production protocol =
capture-forward-face-v2.0.0

patch8-validation-control/1.0.0 =
operational governance ledger
```

이다.

`target_range_m/start_distance` existing semantics는 변경하지 않는다.

---

## 89.4 AGENTS / CLAUDE

Camera Validation / Next Foundation 상태를 Design Freeze 상태로 sync한다.

Patch 1–7 frozen authority는 재작성하지 않는다.

---

# 90. Required implementation scope

Design Freeze 후 구현:

```text
dedicated static acquisition

static feedback firewall

static capture-provenance reuse

static protocol_version

production child-process wrapper

sealed stdout/stderr

sealed result-file handling

closed pre-lock classifier

guide timeout classifier

manual termination classifier

machine-evidence classifier

minimal raw readability probe

validity lock

validation/ gitignore

execution/session ledger

canonical JSON/hash chain

recording identity binding

explicit-recording analysis

canonical analysis tracking

environment provenance

static metrics

SDK deprojection

distortion enum test

calibration check

3D metrics

distance stability

forward availability evaluator

forward gate evaluator

body-only evaluator

slot-131 exact predicate evaluator

recording reconciliation

analysis reconciliation

Patch 8 report

tests
```

이다.

---

# 91. Implementation must not do

금지:

```text
SEQ_CORE semantics 변경

SEQ_FULL semantics 변경

production forward gate 변경

production live UI 변경

body-only/mixed-source PASS 허용

frames schema 변경

summary schema 변경

model lock authority 변경

Patch 5 lineage 변경

Patch 6 selection 변경

Patch 7 integrity 변경

OPEN-002 해결

OPEN-003 해결

OPEN-004 해결

OPEN-005 해결

observed result 기반 threshold tuning
```

이다.

---

# 92. Patch 8 PASS conditions

Patch 8 COMPLETE 조건:

```text
A.
CAP-005 committed

B.
implementation completed

C.
implementation audit:
BLOCKER 0
IMPORTANT 0

D.
execution pre-registered

E.
clean execution workspace

F.
models/environment verified

G.
pre-hardware integrity PASS

H.
formal execution_id started

I.
static setup frozen

J.
all static grid points executed

K.
three canonical takes per point

L.
0.70 PASS

M.
0.80 PASS

N.
static envelope derived

O.
formal seating range = 0.70–0.80 m

P.
slots 101–103:
designated forward_head availability PASS
and class/gate validation PASS

Q.
slots 111–113:
designated body_forward availability PASS
and class/gate validation PASS

R.
slot 121 body-only negative PASS

S.
slot 131 exact predicate in §81 PASS

T.
raw → provenance → analysis
→ frames → batch → summary verified

U.
recording reconciliation PASS

V.
analysis reconciliation PASS

W.
model identity PASS

X.
closure integrity PASS

Y.
ledger/report hashes recorded
```

이다.

---

# 93. Failure semantics

FAIL은 evidence다.

자동 변경 금지:

```text
grid
anchors
thresholds

camera settings
resolution
FPS

ROI

schema

models

production forward gate

body fallback semantics

scientific features
```

재실행은 §21 governance가 필요하다.

---

# 94. OPEN-006 disposition

CAP-005 V5.1.1은 OPEN-006에서 요구한:

```text
candidate-range procedure

grid

repetition protocol

measurement-quality metrics

variation calculations

depth/landmark/RGB-D criteria

3D repeatability

distance stability

acceptance criteria

validated-range procedure
```

를 모두 freeze한다.

Independent audit에서:

```text
BLOCKER = 0
IMPORTANT = 0
```

을 달성하고 repository에 commit된 시점부터:

```text
OPEN-006
→ RESOLVED BY CAP-005
```

이다.

Audit 결과 (V5.1.1 final independent READ-ONLY re-audit):

```text
BLOCKER   = 0
IMPORTANT = 0
MINOR     = 1  (E2-R1 wording; §62에 clarification-only로 반영)

Design Freeze readiness:
READY FOR DESIGN-FREEZE COMMIT
```

Append-only 원칙에 따라 `RESEARCH_DECISION_LOG.md`의 historical `OPEN-006` entry 본문·Status는 수정하지 않는다.
현재 해소 상태는 새 `CAP-005` entry의 `Resolves: OPEN-006`으로만 표현한다.

---

# 95. V5.1.1 resolution mapping — E-1

E-1을 다음 closed rule로 해결한다.

```text
§47
```

에서:

```text
guide q
guide timeout
s skip

operator termination

POWER_FAILURE

CAMERA_DISCONNECT
USB_STREAM_FAILURE

RAW_FILE_NOT_CREATED

raw readability probe

unclassified crash
```

를 서로 배타적으로 분류한다.

핵심:

```text
zero recording_id
!= automatically RAW_FILE_NOT_CREATED

operator signal
!= POWER_FAILURE

partial frame loss
!= machine failure

frame count / frame ratio
cannot be inspected pre-lock
```

이다.

Production operator가 live D455 결과를 본 뒤 termination해도 retry를 얻을 수 없다.

---

# 96. V5.1.1 resolution mapping — E-2

E-2 acceptance ambiguity를 다음으로 해결한다.

### §75

Forward availability population을 정확히:

```text
101–103:
designated forward_head only

111–113:
designated body_forward only

121:
excluded

131:
forward_head AND body_forward
```

로 고정한다.

각 recording/phase를 individually 평가하고 pooling하지 않는다.

### §81

Slot 131 exact PASS predicate를 고정한다.

```text
capture verdict == ok

both forward phases availability PASS

both production gates PASS

canonical analysis PASS

lineage/artifacts PASS

reconciliation PASS
```

이다.

### §67 / §68

3% within/between threshold 대상은 정확히:

```text
shoulder_width_3d
hip_width_3d
trunk_length_3d
```

세 개다.

`ipd_cm`은 3% CV/spread 대상이 아니며 5% distance-stability target만 blocking이다.

### §61 / §62 / §71 — E2-R1 depth temporal SD scope

10 mm temporal-SD threshold의 blocking depth series를 정확히 다음 5개로 freeze한다.

```text
z_face_m
z_lsh_m
z_rsh_m
left_hip_depth_m
right_hip_depth_m
```

Face는 `face_detected && face_depth_valid && face_depth_source == "bbox_roi"` mask를 사용한다.

Shoulder / hip은 해당 `*_valid && *_depth_valid` mask를 사용한다.

각 series에서 finite, positive sample만 사용하고 각 canonical take마다:

```text
n >= 30
sample SD(ddof=1) × 1000 <= 10 mm
```

를 각각 만족해야 한다.

다섯 series 중 하나라도 FAIL/not-evaluable이면 해당 canonical take는 FAIL이며, 각 nominal distance의 세 canonical take 모두 PASS해야 한다.

따라서 depth temporal repeatability의 quantity scope와 PASS/FAIL semantics는 implementation에서 선택할 수 없다.

---

# 97. V5.1.1 minor clarifications

V5 audit의 non-blocking residual 중 protocol ambiguity 가능성이 큰 항목을 함께 명시했다.

```text
static sealing scope expanded
_camera.json pre-lock key restriction
static capture-provenance reuse mandatory
target_range_m/start_distance not repurposed
15 s guide clock fixed
same pyrealsense2 version requirement
ledger serialization pinned
environment re-check per session
all execution IDs required in final record
source URL/access date required
```

이 항목은 Patch 1–7 frozen authority를 변경하지 않는다.

---

# 98. Impact

CAP-005 commit effect:

```text
OPEN-006
→ RESOLVED

Patch 8
→ DESIGN-FROZEN
```

No frozen authority change:

```text
Patch 4 schema
Patch 4.5 model lock
Patch 5 lineage
Patch 6 selection
Patch 7 integrity

CAP-001
CAP-002
CAP-003
CAP-004

OPEN-002
OPEN-003
OPEN-004
OPEN-005
```

이다.

---

# 99. Final Design Freeze audit gate

V5.1.1은 **E-1/E-2/E2-R1 resolution 중심 targeted READ-ONLY audit + authority regression check**를 수행한다.

Commit gate:

```text
BLOCKER = 0
IMPORTANT = 0
```

이다.

MINOR만 남고 다음이 없다면 non-blocking이다.

```text
authority ambiguity
PASS/FAIL ambiguity
retry/cherry-pick route
canonical-selection ambiguity
scientific-validity ambiguity
```

Audit 결과:

```text
BLOCKER   = 0
IMPORTANT = 0
MINOR     = 1

commit gate: SATISFIED
Design Freeze readiness: READY FOR DESIGN-FREEZE COMMIT
```

단일 MINOR는 §62 depth temporal repeatability의 sample population wording(E2-R1)에 관한 것이며 위 non-blocking 조건에 해당한다.
Repository integration에서 §62에 clarification-only 문구로 반영했고 frozen metric은 변경하지 않았다.

---

# 100. Post-commit authority state

Successful audit + Design Freeze integration commit 이후:

```text
Patch 7:
COMPLETE / MAIN-INTEGRATED

CAP-005:
CONFIRMED

OPEN-006:
RESOLVED BY CAP-005

OPEN-002:
DEFERRED

OPEN-003:
DEFERRED

OPEN-004:
DEFERRED

OPEN-005:
DEFERRED

Patch 8:
DESIGN-FROZEN

Patch 8 implementation:
PENDING

Patch 8 implementation audit:
PENDING

Patch 8 hardware execution:
PENDING
```

Patch 8 COMPLETE가 아니며 actual D455 formal validation은 수행되지 않았다.

---

# 101. Design Freeze repository integration record

## 101.1 Semantic source

```text
source:
PATCH_08_DESIGN_FREEZE_V5.1.1_AUDIT_DRAFT.md

version:
V5.1.1

size:
55553 bytes

SHA-256:
4747c181eee5280151cd332e43ef7ed28b953cb3be004f201c56c2818af5b199

final independent READ-ONLY audit:
BLOCKER 0 / IMPORTANT 0 / MINOR 1
READY FOR DESIGN-FREEZE COMMIT
```

§1–§98의 protocol content는 V5.1.1을 그대로 보존한다.

## 101.2 Integration-only edits

Repository integration에서 V5.1.1 대비 변경한 것은 다음뿐이다.

```text
header / §0
→ post-commit authority state로 재기술
  (CAP-005 CONFIRMED / Resolves OPEN-006 / DESIGN-FROZEN /
   implementation PENDING / hardware execution PENDING)

§4.1
→ D455 / OSHA evidence의 실제 source URL과 access date 기록
  (V5.1.1 §4.1 / §87 / §97 요구사항)

§62
→ E2-R1 wording clarification (clarification only)

§94 / §99
→ final audit 결과 기록

§100
→ "Intended post-commit state" 제목을 post-commit authority state로 변경
  (상태 목록 자체는 동일)

§101
→ 본 integration record 추가
```

다음은 변경하지 않았다.

```text
grid / anchors / spacing
repetitions / hold / windows
all thresholds and minimum-n
depth series / validity masks / ddof
within-take / between-take / distance-stability quantity lists
forward availability population
production forward gate / validation bands
body-only-negative semantics
slot-131 predicate
retry / result firewall / closed pre-lock classification
ledger format / serialization / hash chain
reconciliation / integrity closure
Patch 8 PASS conditions
explicit non-decisions
implementation scope / MUST NOT list
```

## 101.3 Companion authority sync

동일 Design Freeze integration에서 §89에 따라 다음을 status-sync한다.

```text
docs/research/RESEARCH_DECISION_LOG.md   CAP-005 append (Resolves OPEN-006)
docs/research/AIoT_RESEARCH_MASTER.md    Patch 8 DESIGN-FROZEN status
RESEARCH_DATA_SCHEMA.md                  protocol / ledger identity status (no schema field change)
AGENTS.md                                Patch 8 status + implementation guardrail
CLAUDE.md                                Camera Validation / Foundation status
```

`frames-schema/1.0.0`, `summary-schema/1.0.0`, `selection-event/1.0.0`, `dataset-selection-manifest/1.0.0`은 변경하지 않는다.
`patch8-validation-control/1.0.0`은 operational governance ledger이며 위 scientific schema의 새 version 또는 대체물이 아니다.

## 101.4 Explicitly not created by Design Freeze integration

```text
docs/research/PATCH_08_EXECUTION_REGISTRY.md  (§15)
execution_id
execution pre-registration
validation/ runtime directory or artifacts
.gitignore validation/ entry               (§23 implementation scope)
Python source / test changes
D455 recordings / analysis runs
```

Execution registration은:

```text
Design Freeze commit
→ Patch 8 implementation
→ regression tests
→ independent implementation audit
```

이후, formal hardware execution 전에 수행한다 (§12 / §15).
