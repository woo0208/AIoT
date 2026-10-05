# PATCH_06 — Selection Manifest / Recapture Inclusion

- 문서 상태: **DESIGN FROZEN — IMPLEMENTATION IN PROGRESS / CLARIFICATION 1 APPLIED**
- 기준일: `2026-10-04`
- clarification date: `2026-10-05`
- 기준 repository state: `main = dbb6540` 인계 상태 / Patch 5 main-integrated source snapshot
- Decision Log authority: `PROV-006` + `PROV-007` clarification
- 선행 Foundation:
  - Foundation Prelude — DONE
  - Patch 1 Capture Recording Provenance — DONE
  - Patch 2 Forward Gate Evidence — DONE
  - Patch 3 Analysis Provenance — DONE
  - Patch 4 Canonical Fixed Frames Schema + Hip Raw Observations — DONE
  - Patch 4.5 MediaPipe Model Artifact Lock — DONE
  - Patch 5 End-to-End Lineage Hardening — DONE / MAIN-INTEGRATED
- baseline regression: `252 tests PASS`
- implementation status: **IN PROGRESS — independent audit I-1/OA-1 clarification pending code fix**
- `PROV-007` clarification 반영 및 independent re-audit 완료 전 Patch 6 implementation commit 금지

---

# 0. Freeze Boundary

Patch 6의 목적:

> **Which recording / analysis run should be selected, and why?**

Patch 5의 목적:

> **What exact bytes were actually used?**

Patch 6는 selection authority를 추가하되 Patch 5 actual-byte lineage를 재설계하지 않는다.

```text
capture / quality / analysis evidence
→ selection decision
→ immutable dataset selection
→ exact canonical frames resolution
→ Patch 5 RF lineage
```

본 문서 확정 전 다음을 하지 않는다.

```text
selection artifact implementation
retake auto-selection
formal include/exclude automation
RF --dataset-manifest implementation
formal policy 추정
frames-schema/1.0.0 변경
Patch 5 contract 변경
```

---

# 1. Current Repository Facts

## 1.1 Capture identity

`capture_d455.py`:

```text
subject
round
dataset_role
recording_id
protocol_version
```

을 capture provenance에 기록한다.

`round` validation:

```text
positive-integer decimal string
```

예:

```json
"round": "1"
```

capture attempt마다 unique `recording_id`를 발급한다.

---

## 1.2 Capture quality

`<recording_id>_quality.json`은:

```text
verdict
fails
warnings
forward_gate_evidence
recording_id
```

등을 기록한다.

verdict:

```text
ok
ok_with_warnings
retake
```

이는 technical evidence이며 selection decision 자체가 아니다.

---

## 1.3 Analysis identity

`analyze_d455.py`는:

```text
analysis/<recording_id>/<analysis_run_id>/
```

의 immutable analysis run archive를 사용한다.

`analysis_manifest.json`에는:

```text
recording_id
analysis_run_id
dataset_role
protocol_version
status
inputs
outputs
code/environment/model provenance
```

가 존재한다.

---

## 1.4 Canonical frames

`frames-schema/1.0.0`은 **exact 60 fields**다.

중요:

```text
dataset_role
protocol_version
```

은 canonical frame columns가 아니다.

Patch 6는 이 두 field를 frames에 추가하지 않는다.

canonical frames identity validation은 기존 Patch 4/5의:

```text
subject
round
recording_id
analysis_run_id
frame_schema_version
exact 60-field header
```

를 유지한다.

---

## 1.5 RF input safety

Patch 5는 이미:

```text
same recording + multiple completed frames runs
same subject/round + different recordings
```

ambiguity를 자동 선택하지 않고 reject한다.

따라서 Patch 6는 silent latest-selection bug 수정이 아니라
**명시적 selection authority 추가**다.

---

# 2. Confirmed Gaps

```text
GAP-1 selection decision authority 없음
GAP-2 explicit recapture relationship 없음
GAP-3 authoritative analysis-run selection reason 없음
GAP-4 exclusion history 없음
GAP-5 capture-stage failure를 dataset decision history에 남길 authority 없음
GAP-6 dataset manifest → RF binding 없음
```

---

# 3. Frozen Core Invariants

```text
INV-1  round = planned measurement slot, not capture-attempt counter.
INV-2  logical slot = (dataset_role, subject, round).
INV-3  round serialized type = positive-integer decimal string.
INV-4  every capture attempt has a unique recording_id.
INV-5  recapture relationship is explicit; never inferred.
INV-6  recapture relation != replacement/include/exclude.
INV-7  technical evidence != scientific selection decision.
INV-8  one manifest has at most one included recording per logical slot.
INV-9  included source binds exact recording + analysis run + frames hash.
INV-10 excluded recording may have no analysis run.
INV-11 selection ledger is append-only.
INV-12 dataset manifest is immutable.
INV-13 later supersession does not invalidate an old immutable manifest.
INV-14 dataset_role cannot be silently promoted/mixed.
INV-15 protocol_version consistency is checked capture↔analysis, not frame-row columns.
INV-16 frames-schema/1.0.0 remains exact 60 fields.
INV-17 manifest RF mode and manual RF modes are mutually exclusive.
INV-18 Patch 6 does not weaken Patch 5 actual-byte lineage.
```

---

# 4. DF-1 — Measurement Slot / Round / Recapture

**Status: FROZEN**

logical slot:

```text
(dataset_role, subject, round)
```

`round`:

```text
type = string
regex = ^[1-9][0-9]*$
canonical positive decimal string
leading zero forbidden
```

허용:

```text
"1"
"2"
"10"
```

금지:

```text
"0"
"01"
"001"
"+1"
"-1"
"1.0"
```

logical round 1의 canonical serialization은 오직 `"1"`이다.

same planned measurement recapture:

```text
same dataset_role
same subject
same round
new recording_id
```

Patch 6는 mandatory `attempt_number`/`take_number`를 추가하지 않는다.

현재 contract에서는 one logical slot → at most one included recording per dataset manifest다.

---

# 5. DF-2 — Selection Artifact Authority

**Status: FROZEN**

canonical artifacts:

```text
manifests/selection_events.jsonl
manifests/datasets/<dataset_manifest_id>.json
```

Patch 6는:

```text
manifests/recordings.jsonl
```

을 만들지 않는다.

capture/analysis provenance가 recording/run identity authority다.

---

# 6. DF-3 — Selection Event Ledger

**Status: FROZEN**

## 6.1 Path / schema

```text
path   = manifests/selection_events.jsonl
schema = selection-event/1.0.0
```

---

## 6.2 Event ID

```text
se_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>
```

repository history에서 unique해야 한다.

---

## 6.3 Event types

exact enum:

```text
recapture_relation
selection_decision
```

---

## 6.4 Exact top-level keys

모든 event:

```text
schema_version
selection_event_id
event_type
created_at
dataset_role
subject
round
recording_id
selection_policy_version
decided_by
supersedes_selection_event_id
recapture
decision
evidence
```

nullable field도 key는 존재한다.

---

## 6.5 Common field contract

```text
schema_version
= selection-event/1.0.0

created_at
= UTC ISO-8601 timestamp

dataset_role
= pilot | formal

subject
= capture provenance subject exact value

round
= positive-integer decimal string

recording_id
= event primary recording

decided_by
= non-empty stable decision-authority identifier
```

Patch 6는 사람 이름 형식/조직 체계를 강제하지 않는다.

---

## 6.6 Paths in selection artifacts

selection event / dataset manifest가 보존하는 artifact path는:

```text
repository-root-relative
normalized
```

여야 한다.

금지:

```text
absolute path
.. traversal
repository root 밖으로 resolve
```

consumer는 repository root에서 resolve한 뒤 actual file을 hash/validate한다.

Patch 5 `experiment_manifest.inputs.ours`의 resolved absolute-path contract는 유지한다.

---

## 6.7 `selection_policy_version`

type:

```text
string | null
```

formal `selection_decision`:

```text
non-empty required
```

pilot selection 또는 pure `recapture_relation`:

```text
null allowed
```

Patch 6는 policy의 scientific 내용 자체를 정의하지 않는다.

---

## 6.8 `supersedes_selection_event_id`

type:

```text
string | null
```

non-null이면 referenced event는:

```text
exists
event_type == selection_decision
same dataset_role
same subject
same round
new event ID != old event ID
```

이어야 한다.

selection event supersession에만 사용한다.
recapture event를 supersede하는 용도로 사용하지 않는다.

---

## 6.9 `recapture`

### `recapture_relation`

exact object:

```json
{
  "recapture_of_recording_id": "<parent recording id>"
}
```

validation:

```text
child recording_id != parent recording_id
same dataset_role
same subject
same round
child capture provenance resolves
parent capture provenance resolves
one child has at most one direct parent
self-link forbidden
cycle forbidden
```

recapture relation 자체는 include/exclude 상태를 만들지 않는다.

### `selection_decision`

```text
recapture = null
```

---

## 6.10 `decision`

### `selection_decision`

exact object keys:

```text
disposition
reason_code
reason_text
analysis_selection
```

`disposition`:

```text
include
exclude
```

`reason_code`:

```text
non-empty string
```

scientific enum 의미는 `selection_policy_version`에서 정의한다.

`reason_text`:

```text
string | null
```

### `recapture_relation`

```text
decision = null
```

---

## 6.11 `analysis_selection`

### include

non-null exact fields:

```text
analysis_run_id
frames_schema_version
frames_path
frames_sha256
analysis_manifest_path
analysis_manifest_sha256
```

required:

```text
frames_schema_version == frames-schema/1.0.0
analysis owner status == completed
owner recording_id == event.recording_id
owner analysis_run_id == analysis_selection.analysis_run_id
owner frames output path/hash match
actual frames SHA-256 match
actual analysis-manifest SHA-256 match
```

### exclude

canonical form:

```text
analysis_selection = null
```

exclude decision does not require analysis.

---

## 6.12 `evidence`

type:

```text
array<object>
```

each exact object:

```text
recording_id
kind
path
sha256
```

allowed `kind`:

```text
capture_provenance
quality
analysis_manifest
canonical_frames
other
```

hash:

```text
lowercase 64-hex SHA-256
```

### All selection decisions

정확히 하나의:

```text
kind == capture_provenance
recording_id == event.recording_id
```

evidence를 요구한다.

capture provenance identity:

```text
recording_id
subject
round
dataset_role
```

가 event와 exact match해야 한다.

### Pilot include

최소:

```text
capture_provenance
analysis_manifest
canonical_frames
```

를 요구한다.

### Formal include

최소:

```text
capture_provenance
quality
analysis_manifest
canonical_frames
```

를 각각 정확히 하나 요구한다.

`analysis_manifest`/`canonical_frames` evidence는
`decision.analysis_selection` path/hash와 exact match해야 한다.

### Exclude

최소:

```text
capture_provenance
```

만 요구한다.

quality/analysis artifact가 실제 존재하면 추가 pin할 수 있다.

### Recapture relation

정확히:

```text
child recording capture_provenance
parent recording capture_provenance
```

를 최소 요구한다.

두 evidence item은 `recording_id`로 구분한다.

---

## 6.13 Role / protocol validation

frames row에 `dataset_role` 또는 `protocol_version`을 요구하지 않는다.

selection validator는:

```text
capture provenance.dataset_role
== event.dataset_role
== selected analysis_manifest.dataset_role
```

를 검증한다.

dataset manifest를 검증할 때는 추가로:

```text
event.dataset_role
== manifest.dataset_role
```

을 검증한다.

protocol:

```text
capture provenance.protocol_version
== selected analysis_manifest.protocol_version
```

을 검증한다.

Patch 6는 특정 `protocol_version` 값을 scientific include criterion으로 만들지 않는다.

---

## 6.14 Canonical JSONL serialization

```python
json.dumps(
    event,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

file contract:

```text
UTF-8
no BOM
LF
one terminating LF per event
```

event-line SHA-256:

```text
canonical JSON bytes + terminating LF
```

exact bytes 기준이다.

---

## 6.15 Append-only behavior

writer는 기존 ledger를 rewrite/truncate하지 않는다.

새 event는 validation 후 append한다.

reader는 최소 다음을 hard error 처리한다.

```text
malformed JSON
duplicate selection_event_id
unsupported schema version
invalid event-type shape
invalid round type/value
broken supersedes reference
recapture self-link/cycle
multiple direct recapture parents
invalid path traversal
hash mismatch
```

---

# 7. DF-4 — Supersession Semantics

**Status: FROZEN — CLARIFIED BY PROV-007**

## 7.0 Single-terminal / linear-chain rule

logical slot:

```text
(dataset_role, subject, round)
```

마다 current terminal `selection_decision`은 최대 하나만 존재할 수 있다.

규칙:

```text
slot에 prior decision 없음
→ new decision.supersedes_selection_event_id == null

slot에 current terminal decision A 존재
→ new decision B MUST supersede A

A already superseded by B
→ A cannot be superseded again

therefore:
unlinked second decision = reject
branching supersession = reject
```

허용:

```text
A
↓
B supersedes A
↓
C supersedes B
```

금지:

```text
A
├─ B supersedes A
└─ C supersedes A
```

supersession currentness는 recording 단위가 아니라 logical slot 단위다.

따라서 recording이 바뀌어도 같은 slot의 history는 하나의 linear chain을 유지한다.

예:

```text
A: exclude R1
↓
B: include R2, supersedes A
↓
C: include R3, supersedes B
```

새 dataset manifest는 각 slot의 current terminal decision만 사용할 수 있고,
그 terminal decision의 disposition은 `include`여야 한다.

기존 immutable manifest는 자신이 pin한 historical event/source hashes로 검증하며,
later supersession만으로 invalid 처리하지 않는다.

---

selection decision 변경:

```text
old selection_decision
↓
new selection_decision
  supersedes_selection_event_id = old event ID
```

기존 event는 수정하지 않는다.

## 7.1 New-manifest build-time rule

새 dataset manifest를 만들 때 선택하려는 decision event는
해당 logical slot의 **유일한 current terminal decision**이어야 한다.

다음은 reject한다.

```text
already superseded decision
unlinked second decision
branch sibling
non-terminal decision
```

즉 새 snapshot은 build 시점의 single terminal authoritative decision만 사용할 수 있고,
그 decision의 disposition은 `include`여야 한다.

---

## 7.2 Existing-manifest revalidation rule

이미 생성된 manifest를 다시 읽을 때는:

```text
manifest-pinned selection_event_id
manifest-pinned selection_event_sha256
event contents
source artifacts/hashes
```

를 검증한다.

그 후 ledger에 새로운 superseding event가 append되었다는 사실만으로
기존 manifest를 invalid 처리하지 않는다.

따라서:

```text
M1 created from event A
later event B supersedes A
M2 created from B
```

여도 M1은 과거 experiment에 대한 immutable historical authority로 계속 유효하다.

---

# 8. DF-5 — Immutable Dataset Selection Manifest

**Status: FROZEN**

## 8.1 Path / schema

```text
manifests/datasets/<dataset_manifest_id>.json
dataset-selection-manifest/1.0.0
```

ID:

```text
dm_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>
```

same ID/path overwrite 금지.

---

## 8.2 Exact top-level fields

```text
schema_version
dataset_manifest_id
created_at
created_by
dataset_role
selection_policy_version
selection_events_path
entries
```

---

## 8.3 Dataset role

allowed:

```text
pilot
formal
```

single role per manifest.

source capture provenance, selection event, selected analysis manifest는
top-level role과 exact match해야 한다.

---

## 8.4 Policy version

type:

```text
string | null
```

formal manifest:

```text
non-empty required
```

각 included source selection event의 policy version과 exact match한다.

pilot manifest는 null 허용.

---

## 8.5 Selection ledger reference

```text
selection_events_path
= manifests/selection_events.jsonl
```

repository-relative normalized path다.

ledger 전체 hash를 manifest에 pin하지 않는다.

이유:

```text
ledger is append-only and legitimately grows
```

각 entry가 exact selected event line SHA-256을 pin한다.

---

## 8.6 Exact entry fields

```text
dataset_role
subject
round
recording_id
selection_event_id
selection_event_sha256
analysis_run_id
frames_schema_version
frames_path
frames_sha256
analysis_manifest_path
analysis_manifest_sha256
```

`round`:

```text
positive-integer decimal string
```

entry가 참조하는 event:

```text
event_type == selection_decision
decision.disposition == include
```

이어야 한다.

entry identity/path/hash는 event의 identity와 `analysis_selection`에 exact match한다.

---

## 8.7 Unique logical slot

manifest 내:

```text
(dataset_role, subject, round)
```

duplicate는 hard error다.

---

## 8.8 Deterministic ordering

```text
subject lexical ascending
then int(round) numeric ascending
```

---

## 8.9 Canonical manifest serialization

```text
UTF-8
no BOM
LF
json.dump(
    manifest,
    indent=2,
    ensure_ascii=False,
    sort_keys=True
)
final LF required
```

manifest external SHA-256은 final LF를 포함한 exact file bytes 기준이다.

manifest self-hash는 내부에 넣지 않는다.

---

## 8.10 Snapshot semantics

dataset manifest는 **included sources만 담는 immutable snapshot**이다.

excluded attempts, recapture relations, 과거 decisions는 ledger에 남는다.

manifest를 현재 ledger state의 dynamic view로 취급하지 않는다.

---

# 9. DF-6 — Dataset Manifest Build Validation

**Status: FROZEN**

새 manifest 생성 시:

```text
schema/version/path validation
dataset role validation
formal policy version validation
entry ordering
logical-slot uniqueness
selected event exists
selected event line hash exact
selected event is include
selected event is not currently superseded
capture provenance exact identity/hash
analysis manifest completed / exact owner
capture.dataset_role == analysis.dataset_role == manifest.dataset_role
capture.protocol_version == analysis.protocol_version
frames exact 60-field schema
frames recording/run/subject/round exact identity
frames actual SHA-256 exact
analysis manifest actual SHA-256 exact
```

을 검증한다.

---

# 10. DF-7 — Existing Manifest Revalidation

**Status: FROZEN**

이미 생성된 manifest 소비 시:

```text
manifest file exact hash
manifest schema/ID/path
entry ordering/uniqueness
pinned selection event exact ID + line hash
event was an include decision for same slot/source
capture/analysis/frames current bytes still match pinned hashes
Patch 5 canonical input validation
```

을 검증한다.

**나중 superseding event 존재 여부는 기존 manifest 무효화 조건이 아니다.**

선택 변경을 적용하려면 새 dataset manifest를 사용해야 한다.

---

# 11. DF-8 — Dataset Role Boundary

**Status: FROZEN**

self-recorded manifest role:

```text
pilot
formal
```

금지:

```text
pilot source in formal manifest
formal source in pilot manifest
mixed pilot/formal entries
external table row in self-recorded manifest
```

external source는 Patch 5 external-table lineage를 사용한다.

Early Hardware Preflight는 자동 formal 승격하지 않는다.

---

# 12. DF-9 — RF Manifest Mode

**Status: FROZEN**

## 12.1 CLI

```text
--dataset-manifest PATH
```

다음은 mutually exclusive:

```text
--ours
--ours-frames
--dataset-manifest
```

---

## 12.2 Resolution

```text
dataset manifest
→ existing-manifest validation
→ exact selected analysis/run/frames resolution
→ Patch 5 canonical input validation
→ existing ambiguity guard
→ normal RF sample construction
```

Patch 6가 numeric RF logic을 변경하지 않는다.

---

## 12.3 Experiment provenance

manifest mode:

```text
experiment_manifest.dataset_manifest.dataset_manifest_id
experiment_manifest.dataset_manifest.path
experiment_manifest.dataset_manifest.sha256
```

를 채운다.

`path`는 Patch 5 convention에 맞춰 execution에서 실제 resolve한 absolute path를 기록한다.

동시에:

```text
experiment_manifest.inputs.ours
```

도 기존 Patch 5 exact input fields로 계속 기록한다.

selection artifact 내부 path가 repository-relative인 것과
Patch 5 experiment provenance의 resolved absolute path는 서로 다른 책임이다.

---

## 12.4 Result provenance

manifest mode result row:

```text
dataset_manifest_sha256
```

은 exact current manifest hash다.

manual mode에서는 기존 Patch 5 null/empty behavior를 유지한다.

---

## 12.5 Sample lineage

`rf-sample-lineage/1.0.0` schema는 변경하지 않는다.

experiment-level dataset manifest provenance와
sample-level exact recording/run/frames lineage를 중복 역할로 만들지 않는다.

---

# 13. DF-10 — Scientific Policy Boundary

**Status: FROZEN**

Patch 6는 selection mechanism을 제공한다.

다음 scientific policy는 deferred:

```text
formal participant count
formal round count
ok_with_warnings handling
retake maximum count
formal eligibility criteria
technical exception approval
scientific exclusion/outlier criteria
```

formal selection event / formal manifest:

```text
selection_policy_version != null
and non-empty
```

를 요구한다.

그 policy 내용 자체는 별도 Research Decision으로 freeze한다.

---

# 14. Hashing / Path / Line-ending Rules

**Status: FROZEN**

all artifact hashes:

```text
SHA-256
lowercase 64 hex
exact bytes
```

selection artifact path:

```text
repository-root-relative normalized path
no absolute path
no .. traversal
```

selection event line hash:

```text
canonical compact JSON + LF
```

dataset manifest hash:

```text
canonical pretty JSON exact bytes + final LF
```

Patch 6 implementation은 Windows checkout에서도 canonical manifest bytes가 변하지 않도록
repository-level EOL protection을 추가해야 한다.

최소 target:

```gitattributes
/manifests/selection_events.jsonl text eol=lf
/manifests/datasets/*.json text eol=lf
```

exact `.gitattributes` patch는 implementation에서 source tree 상태에 맞춰 적용한다.

---

# 15. Explicit Rejected Behaviors

```text
latest recording auto-selection
latest analysis run auto-selection
glob/path order auto-selection
quality/RF performance based auto-selection
recapture relation => automatic exclusion/replacement
quality verdict alone => scientific include/exclude
pilot => formal silent promotion
same logical slot multiple included recordings
dataset manifest overwrite
selection event rewrite/delete
manual RF source + manifest source merge
recordings.jsonl duplicate authority
frames-schema/1.0.0 expansion for dataset_role/protocol_version
old immutable manifest invalidation because of later supersession
absolute/traversing paths in selection artifacts
```

---

# 16. Backward Compatibility

유지:

```text
capture-provenance/1.0.0
analysis-provenance/1.0.0
frames-schema/1.0.0 exact 60 fields
summary-schema/1.0.0
mediapipe-model-lock/1.0.0
rf-sample-lineage/1.0.0
rf-experiment-provenance/1.0.0

existing --ours
existing --ours-frames
existing LOSO subject grouping
existing RF feature/drop/evaluation semantics
existing first-upright RF reference behavior
existing Patch 5 resolved-absolute-path experiment provenance
```

legacy/pilot data를 formal manifest에 조용히 편입하지 않는다.

---

# 17. Non-Goals

```text
F1 exact formula / feature count / normalization / missing policy
F2 exact formula / feature count / geometry / missing-depth policy
p > 6 rank_weights exact policy

formal participant count
formal round count
formal scientific inclusion/exclusion criteria
ok_with_warnings formal policy
retake maximum count
exception approval policy
outlier policy

exact seed list
exact λ selection rule
formal metric set

Patch 7 general integrity scanner
Patch 8 distance grid / repeat count / hardware acceptance criteria

data subtree full relocation
historical artifact rename/delete
unrelated Patch 5 accepted MINOR cleanup
```

---

# 18. Acceptance Criteria

```text
AC-01 same-slot candidates are never auto-selected
AC-02 recapture keeps same round and gets new recording_id
AC-03 round matches canonical regex ^[1-9][0-9]*$; leading zero forbidden
AC-04 recapture relation requires explicit child→parent link
AC-05 recapture self-link/cycle/multiple-parent rejected
AC-06 recapture relation does not change selection state
AC-07 every selection_decision pins exactly one own capture provenance
AC-08 pilot include pins capture + completed analysis + frames
AC-09 formal include additionally pins quality + non-empty policy version
AC-10 exclude works without analysis run
AC-11 capture.dataset_role == analysis.dataset_role == manifest.dataset_role
AC-12 capture.protocol_version == analysis.protocol_version
AC-13 canonical frames remain exact frames-schema/1.0.0 60 fields
AC-14 no frames dataset_role/protocol_version columns are required
AC-15 evidence/path hashes are exact and traversal-safe
AC-16 ledger duplicate/malformed/broken-reference events rejected
AC-17 selection history append-only
AC-18 each logical slot has at most one current terminal decision; unlinked second decisions and branching supersession are rejected
AC-19 new manifest uses only the current terminal include decision; later supersession does not invalidate an old immutable manifest
AC-20 dataset manifest cannot overwrite existing ID/path
AC-21 logical slot unique in manifest
AC-22 entry order deterministic by subject + int(round)
AC-23 selection-event line hash tamper rejected
AC-24 pilot/formal role mismatch rejected
AC-25 --dataset-manifest mutually exclusive with --ours/--ours-frames
AC-26 manifest resolves through existing Patch 5 canonical-input validator
AC-27 experiment_manifest.dataset_manifest exact ID/path/hash populated
AC-28 experiment_manifest.inputs.ours remains exact resolved input record
AC-29 result dataset_manifest_sha256 matches experiment manifest
AC-30 existing rf-sample-lineage/1.0.0 remains unchanged
AC-31 existing manual RF modes unchanged
AC-32 full pre-Patch-6 regression remains PASS
AC-33 canonical JSON/JSONL LF bytes stable on supported development OSes
AC-34 valid linear supersession chain A→B→C passes
AC-35 supersession may cross recording_id values within the same logical slot
AC-36 new capture round input rejects non-canonical values such as "01"
```

---

# 19. Minimum Test Matrix

```text
A. selection-event schema exact keys/types
B. canonical round validation (`^[1-9][0-9]*$`); reject leading zero
C. append-only writer behavior
D. duplicate event ID rejection
E. malformed JSONL rejection
F. recapture parent/child provenance
G. recapture self-link/cycle/multiple-parent rejection
H. recapture != selection
I. own capture provenance required for all selection decisions
J. pilot include evidence minimum
K. formal include evidence + policy minimum
L. exclude without analysis
M. dataset_role mismatch rejection
N. protocol_version capture↔analysis mismatch rejection
O. exact frame 60-field schema preservation
P. evidence hash/path traversal rejection
Q. valid linear supersession chain
Q2. unlinked second decision in same logical slot rejection
Q3. branching supersession rejection
Q4. same-slot supersession across different recording_id values
R. new-manifest requires the current terminal include decision
S. old-manifest later-supersession stability
T. dataset manifest exact schema
U. no-overwrite
V. unique logical slot
W. deterministic subject/int(round) ordering
X. event-line hash pinning
Y. pilot/formal role guard
Z. CLI mutual exclusion
AA. manifest → Patch 5 canonical-input resolution
AB. experiment manifest binding
AC. inputs.ours preservation
AD. result dataset_manifest_sha256
AE. existing Patch 5 ambiguity guards
AF. Windows/LF exact-byte hash test where applicable
AG. full regression
```

---

# 20. Implementation Map

## 20.1 New module

권장:

```text
selection_manifest.py
```

책임:

```text
selection event validate/read/append
recapture graph validation
selection decision validation
supersession resolution
dataset manifest build/validate
event-line hash
path normalization/safe resolution
source role/protocol validation
selected canonical source resolution
```

함수명 자체는 implementation detail이다.

---

## 20.2 `rf_experiment.py`

추가:

```text
--dataset-manifest
mutual exclusion
manifest validation/resolution
experiment_manifest.dataset_manifest population
result dataset_manifest_sha256 population
```

RF numeric semantics 수정 금지.

---

## 20.3 Capture / analysis

`capture_d455.py`:

```text
selection logic 추가하지 않음
new capture round input은 canonical regex ^[1-9][0-9]*$ 적용
leading-zero round 신규 생성 금지
```

이 변경은 selection policy 추가가 아니라 identity canonicalization이다.

`analyze_d455.py`:

```text
selection decision 역삽입하지 않음
frames-schema/1.0.0 변경하지 않음
```

---

## 20.4 `.gitattributes`

implementation에서 generated selection artifact의 LF contract 보호를 추가한다.

---

## 20.5 Tests

권장 신규:

```text
test_patch6_selection.py
```

필요하면 fixture helper 추가.

---

# 21. Documentation Consistency

`RESEARCH_DATA_SCHEMA.md`는 동일 docs-only Design Freeze change에서 다음을 sync한다.

```text
1. manifests/recordings.jsonl future authority 제거
2. 2-layer selection authority 반영
3. round = planned measurement slot 명시
4. technical evidence != scientific inclusion 명시
5. automatic first-eligible policy 제거
6. formal selection_policy_version requirement
7. include/exclude/recapture history separation
8. immutable snapshot + supersession historical validity
9. pilot/formal role guard
10. RF --dataset-manifest binding
11. frames-schema/1.0.0 exact 60 fields 유지
```

---

# 22. Definition of Done

## Design Freeze

```text
[ ] PROV-006 내용 확정
[ ] PATCH_06 문서 확정
[ ] RESEARCH_DATA_SCHEMA sync
[ ] git diff --check PASS
[ ] docs-only change 확인
[ ] docs-only Design Freeze commit
```

## Implementation

```text
[ ] selection-event/1.0.0
[ ] dataset-selection-manifest/1.0.0
[ ] append-only event ledger
[ ] explicit recapture graph
[ ] exact include binding
[ ] exclude without analysis
[ ] supersession semantics
[ ] immutable dataset snapshots
[ ] role/protocol validation
[ ] --dataset-manifest
[ ] manual/manifest mutual exclusion
[ ] Patch 5 experiment/result linkage
[ ] LF canonical artifact protection
```

## Verification / closure

```text
[ ] targeted tests PASS
[ ] full regression PASS
[ ] independent READ-ONLY implementation audit
[ ] BLOCKER 0
[ ] IMPORTANT 0
[ ] implementation commit
[ ] Foundation documentation closure
[ ] main merge
[ ] post-merge regression
[ ] status sync
```

---

# 23. Design Freeze Commit Boundary

Design Freeze commit은 docs-only다.

대상:

```text
docs/research/RESEARCH_DECISION_LOG.md
docs/foundation/PATCH_06_selection_manifest_recapture_inclusion.md
RESEARCH_DATA_SCHEMA.md
```

금지:

```text
*.py implementation
test implementation
generated selection JSON/JSONL
formal selection execution
```

권장 commit message:

```text
docs: freeze Patch 6 selection manifest and recapture inclusion design
```

---

# 24. Audit Clarification 1 — I-1 / OA-1

**Authority:** `PROV-007`

Independent READ-ONLY implementation audit에서 implementation commit을 막는
`I-1`과 open ambiguity `OA-1`이 확인되어 다음을 Design Freeze clarification으로 확정했다.

```text
I-1
one logical slot
→ at most one current terminal selection_decision
→ linear supersession chain only
→ unlinked second decision reject
→ branching supersession reject

OA-1
round
→ canonical regex ^[1-9][0-9]*$
→ leading zero forbidden
```

implementation commit 전 최소 required tests:

```text
same-slot unlinked second decision → reject
branching supersession → reject
valid A→B→C chain → PASS
same-slot chain across different recording_id → PASS
new manifest from non-terminal event → reject
old immutable manifest after later supersession → PASS
round "1" → PASS
round "01" → reject
new capture round "01" → reject
```

본 clarification은 scientific selection criteria를 새로 정하지 않는다.

---

# 25. Current Disposition

현재 문서는 `PROV-007` clarification을 포함한 Patch 6 Design Freeze contract다.

현재 구현은 이미 working tree에 존재하며 independent READ-ONLY audit에서:

```text
BLOCKER = 0
IMPORTANT = 1 (I-1)
OPEN AMBIGUITY = OA-1
```

이 확인되었다.

따라서 다음 순서를 따른다.

```text
1. RESEARCH_DECISION_LOG.md와 본 PATCH_06 문서에 clarification 반영
2. 두 문서만 stage하여 docs-only clarification commit
3. Codex로 I-1/OA-1 targeted implementation fix
4. required targeted tests + Patch 5 regression + full regression
5. independent READ-ONLY re-audit
6. BLOCKER=0 / IMPORTANT=0 확인
7. 그 이후에만 Patch 6 implementation commit
8. documentation closure / main integration은 후속 단계
```

권장 clarification commit message:

```text
docs: clarify Patch 6 supersession and canonical round
```

본 clarification은 Patch 6 implementation 완료 또는 formal scientific selection policy 확정을 의미하지 않는다.
