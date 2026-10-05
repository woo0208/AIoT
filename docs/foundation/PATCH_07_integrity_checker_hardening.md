# PATCH_07 — Integrity Checker / Hardening

- 문서 상태: **DESIGN FREEZE CONTRACT — READY TO COMMIT / IMPLEMENTATION NOT STARTED**
- 기준일: `2026-10-05`
- 기준 branch: `main`
- 기준 HEAD / origin/main: `6e6f577`
- 기준 regression: `330 PASS`
- 기준 audit state: `Patch 6 independent re-audit — BLOCKER 0 / IMPORTANT 0`
- 기준 working tree: `clean`
- 선행 Foundation:
  - Foundation Prelude — DONE
  - Patch 1 Capture Recording Provenance — DONE
  - Patch 2 Forward Gate Evidence — DONE
  - Patch 3 Analysis Provenance — DONE
  - Patch 4 Canonical Fixed Frames Schema + Hip Raw Observations — DONE
  - Patch 4.5 MediaPipe Model Artifact Lock — DONE
  - Patch 5 End-to-End Lineage Hardening — DONE / MAIN-INTEGRATED
  - Patch 6 Selection Manifest / Recapture Inclusion — DONE / MAIN-INTEGRATED / POST-MERGE VERIFIED
- Decision Log authority target: `PROV-008 — Patch 7 Integrity Checker / Hardening Design Freeze`
- 구현 상태: **NOT STARTED**

> 본 문서는 Patch 7 implementation 전에 고정할 exact contract다.
> Repository authority로서의 Design Freeze는 본 문서와 대응하는 `PROV-008` Decision Log entry가 동일 Design Freeze commit에 포함될 때 효력이 발생한다.
> 그 commit 전에는 Python source/test를 수정하지 않는다.

---

# 0. Freeze Boundary

Patch 1~6은 연구 artifact가 실제 pipeline에서 사용될 때 강한 fail-closed validation을 제공한다.

현재 핵심 구조는 다음과 같다.

```text
artifact 생성
→ 특정 consumer가 artifact를 사용
→ 그 시점에 identity / owner / hash / schema를 검증
```

하지만 repository 전체를 독립적으로 순회하여 다음을 검사하는 계층은 아직 없다.

```text
all managed artifacts
→ inventory
→ ownership / identity graph
→ stored hash ↔ actual bytes
→ missing / mixed / malformed / torn / orphan detection
→ repository-wide integrity result
```

Patch 7의 목적은 다음 질문에 답하는 것이다.

> **현재 repository에 존재하는 Patch 1~6 연구 artifact 전체가, 기존 frozen authority가 선언한 identity / ownership / hash / lineage 관계와 서로 모순 없이 일치하는가?**

Patch 7은 기존 scientific semantics를 재설계하지 않는다.

Patch 7의 핵심 성격은 다음으로 고정한다.

```text
read-only audit
repository-wide inventory
existing-authority validation
fail closed on authoritative contradiction
non-destructive diagnostics
no scientific decision
no historical rewrite
```

---

# 1. Authority / Source Priority

Patch 7은 새로운 provenance meaning을 발명하지 않고 기존 Foundation authority를 검사한다.

우선순위:

```text
1. Current implementation + committed tests
2. Existing frozen Foundation contracts
3. RESEARCH_DECISION_LOG.md decisions
4. RESEARCH_DATA_SCHEMA.md current schema documentation
5. descriptive/current-state docs
```

충돌 시 Patch 7 checker가 임의로 의미를 선택하지 않는다.

기존 frozen contract를 우선하고, 해결되지 않은 ambiguity는 checker가 새로운 scientific rule로 채우지 않는다.

Patch 7의 주요 선행 authority:

```text
capture-provenance/1.0.0
analysis-provenance/1.0.0
frames-schema/1.0.0
summary-schema/1.0.0
mediapipe-model-lock/1.0.0
rf-sample-lineage/1.0.0
rf-experiment-provenance/1.0.0
selection-event/1.0.0
dataset-selection-manifest/1.0.0
PROV-005
PROV-006
PROV-007
```

---

# 2. Confirmed Gap / Patch 7 Handoff

## 2.1 Patch 3 handoff

Patch 3는 후속 Integrity Checker의 역할을 다음과 같이 남겼다.

```text
repo/data 전체 스캔
→ 누락
→ 혼입
→ hash mismatch
→ orphan artifact
```

을 자동 검사하는 독립 checker.

## 2.2 Patch 5 handoff

Patch 5는 `_samples.csv` boundary와 함께 다음을 Patch 7 general integrity scope로 남겼다.

```text
all companion artifact inventory
orphan detection
missing artifact detection
repository-wide hash audit
```

또한 `experiment_manifest.json` 자신의 SHA-256은 자기 내부에 기록하지 않으며, 별도 external integrity authority는 Patch 7에서 검토할 수 있다고 명시했다.

## 2.3 Patch 6 handoff

Patch 6 independent audit closure는 다음을 Patch 7 hardening candidate로 남겼다.

```text
M-2 evidence-kind deep semantic type checks
M-3 crash/torn-write recovery / integrity scanning guidance
```

따라서 Patch 7은 다음 gap을 해결한다.

```text
GAP-1 repository-wide managed artifact inventory 없음
GAP-2 repository-wide stored-hash revalidation 없음
GAP-3 structural missing/orphan detection 없음
GAP-4 cross-layer identity/ownership contradiction audit 없음
GAP-5 selection evidence kind의 deep semantic validation이 제한적
GAP-6 torn/partial authoritative artifact의 독립 진단 계층 없음
GAP-7 checker가 없는 상태에서 unused/historical artifact는 consumer validation을 영원히 통과하지 않을 수 있음
```

---

# 3. Frozen Core Invariants

```text
INV-1  Patch 7 is read-only with respect to research artifacts.
INV-2  Existing Patch 1–6 authority remains authoritative; Patch 7 does not redefine it.
INV-3  ERROR means an authoritative contradiction, not merely an unused or incomplete historical state.
INV-4  failed/running/incomplete state is not corruption by itself.
INV-5  A declared fact that contradicts actual bytes/identity/path is corruption.
INV-6  No artifact is selected, excluded, retaken, promoted, or replaced by Patch 7.
INV-7  No latest/newest/timestamp heuristic may create provenance or ownership.
INV-8  Stored SHA-256 is rechecked against exact bytes when the referenced artifact is accessible.
INV-9  mtime/size never substitute for a required content hash.
INV-10 Canonical frames validation reuses the existing Patch 4/5 validator and exact 60-field schema.
INV-11 Selection ledger / dataset manifest validation reuses Patch 6 history and snapshot semantics.
INV-12 Historical immutable dataset manifests remain valid after later selection supersession.
INV-13 Compatibility copies are not promoted into canonical provenance authority.
INV-14 External unavailable artifacts are not silently substituted with similar files.
INV-15 Checker findings never rewrite append-only selection history.
INV-16 Checker does not require real D455 hardware or network access.
INV-17 Full pre-Patch-7 regression must remain PASS.
INV-18 Patch 7 does not change numerical outputs, sample inclusion, or scientific evaluation behavior.
```

---

# 4. DF-1 — Checker Entry Point / Side-Effect Contract

**Status: FROZEN**

Patch 7 adds one repository-level checker entry point.

Recommended canonical module/path:

```text
integrity_check.py
```

Minimum CLI:

```bash
python integrity_check.py
python integrity_check.py --repo-root <path>
```

Default repository root:

```text
directory containing integrity_check.py
```

The checker MUST NOT require a Git working tree to inspect artifact integrity.

The checker MUST NOT:

```text
create research artifact
modify research artifact
truncate file
rewrite JSON/JSONL
repair hash
rename/move/delete artifact
download model
open camera
run inference
rerun RF experiment
make selection decision
```

The checker MAY create ordinary process-local in-memory structures only.

No persistent integrity report file is required by Patch 7.

---

# 5. DF-2 — Exit / Severity Contract

**Status: FROZEN**

Findings are classified as:

```text
ERROR
WARNING
INFO
```

## 5.1 ERROR

`ERROR` means the checker completed enough inspection to prove a contradiction with existing authority.

Examples:

```text
stored SHA != actual SHA
authority-recorded artifact missing
recording_id mismatch
analysis_run_id mismatch
owner mismatch
canonical schema violation
selection graph violation
dataset event hash mismatch
completed RF output hash mismatch
malformed canonical immutable manifest
```

Success condition:

```text
ERROR == 0
```

## 5.2 WARNING

`WARNING` means the state is incomplete/unverifiable/suspicious but current frozen authority does not justify calling it corruption.

Examples:

```text
failed capture companion set incomplete
running/failed run partial state
inaccessible external absolute-path artifact
recognized temporary crash residue
unowned legacy capture companion that is not used downstream
```

Warnings do not by themselves fail repository integrity.

## 5.3 INFO

`INFO` records normal historical/unused states.

Examples:

```text
capture never selected
completed analysis never selected
historical dataset manifest later superseded
optional local model cache absent
```

## 5.4 Exit codes

```text
0 = audit completed and ERROR == 0
1 = audit completed and ERROR > 0
2 = checker could not complete the audit because of invocation/internal audit failure
```

A WARNING-only result MUST exit `0`.

A checker bug/uncaught internal exception MUST NOT be misreported as repository PASS.

---

# 6. DF-3 — Deterministic Reporting

**Status: FROZEN**

Every finding must expose at least:

```text
severity
stable category/code
artifact/path or logical identity when available
human-readable reason
```

Stable top-level finding categories:

```text
HASH_MISMATCH
MISSING_ARTIFACT
IDENTITY_MISMATCH
OWNER_MISMATCH
SCHEMA_INVALID
SERIALIZATION_INVALID
GRAPH_INVALID
STRUCTURAL_ORPHAN
TORN_AUTHORITY
EXTERNAL_UNVERIFIABLE
INCOMPLETE_NONTERMINAL
TEMP_RESIDUE
REPOSITORY_CHANGED_DURING_CHECK
```

Implementation MAY define more specific subcodes beneath these categories.

Output ordering must be deterministic for a stable repository state.

Recommended ordering:

```text
severity
→ category/code
→ normalized path/logical identity
```

Final human-readable summary must include at least:

```text
ERROR count
WARNING count
INFO count
final PASS / FAIL
```

Patch 7 does not freeze a persistent JSON report schema.

---

# 7. DF-4 — Managed Repository Namespace

**Status: FROZEN**

Patch 7 inventory scope:

```text
data/**
analysis/**
manifests/selection_events.jsonl
manifests/datasets/*.json
results/**
mediapipe_model_lock.json
models/<locked filename>          # only if locally present
```

The scan is recursive where applicable.

Patch 7 MUST NOT require one future directory layout when current producers do not require it.

For capture artifacts, recognized artifacts sharing one basename stem in the same directory form one capture-attempt group.

Recognized capture suffixes:

```text
.db3
.bag
_camera.json
_markers.csv
_samples.csv
_quality.json
```

A flat or nested `data/**` location may be inventoried, but Patch 7 does not move files into a target layout.

---

# 8. DF-5 — Empty / Not-Yet-Generated Repository State

**Status: FROZEN**

The absence of generated research data is not corruption.

Therefore all of the following may be absent without ERROR when nothing references them:

```text
data/
analysis/
manifests/
results/
models/
```

The tracked `mediapipe_model_lock.json` remains independently validateable.

An empty research-artifact set may produce INFO but must not fail solely because data collection has not begun.

---

# 9. DF-6 — Repository Stability During Audit

**Status: FROZEN**

Patch 7 MUST NOT claim PASS for a moving repository snapshot.

At minimum:

```text
1. managed path inventory is captured at audit start
2. each hashed file uses mutation-detecting full-byte hashing
3. managed path inventory is checked again before final PASS
```

If the managed path set changes during the audit:

```text
REPOSITORY_CHANGED_DURING_CHECK
→ ERROR
```

If a file changes while being hashed, existing mutation-detection semantics must fail closed.

Patch 7 does not introduce a global writer lock for every pipeline component.

Recommended operator practice remains:

```text
run integrity audit while capture/analysis/selection/RF writers are quiescent
```

---

# 10. DF-7 — Capture Artifact Inventory / Identity

**Status: FROZEN**

## 10.1 Modern capture authority

A valid current capture authority is a `_camera.json` declaring:

```text
schema_version = capture-provenance/1.0.0
```

Patch 7 validates at minimum the frozen identity/provenance fields used by Patch 1/6:

```text
schema_version
recording_id
subject
round
dataset_role
protocol_version
record_file
sidecar_files
```

Current canonical `round` rule follows Patch 6 clarification:

```text
^[1-9][0-9]*$
```

Current `dataset_role` values follow existing producer authority.

Patch 7 does not retroactively reject a properly marked legacy analysis solely because a modern capture sidecar is absent.

## 10.2 Recording file

If modern capture provenance has:

```text
record_file = null
```

this may be a preserved failed attempt and is not ERROR by itself.

If:

```text
record_file != null
```

then the declared recording basename must correspond to the same recording stem and the referenced raw recording must exist.

Missing declared raw recording:

```text
MISSING_ARTIFACT
→ ERROR
```

Patch 7 does not open/play the raw RealSense recording to judge content quality.

## 10.3 Sidecar mapping

`sidecar_files` is an explicit naming map for:

```text
camera
markers
samples
quality
```

The mapping must be internally consistent with the recording stem.

However it is not treated as an unconditional proof that every sidecar was successfully created, because Patch 1 intentionally preserves failed attempts and `_samples.csv` is conditionally emitted only when samples exist.

Therefore a missing companion sidecar at capture-inventory level is not automatically ERROR.

It is classified according to downstream authority:

```text
unreferenced incomplete failed attempt
→ WARNING/INFO

artifact explicitly required/pinned by downstream authority
→ ERROR
```

## 10.4 Existing sidecars

When present:

```text
_markers.csv
_samples.csv
_quality.json
```

must not carry a conflicting `recording_id`.

For CSV sidecars, every row containing the frozen `recording_id` field must match the capture authority.

For `_quality.json`:

```text
valid JSON object
recording_id present
recording_id matches capture/event identity when bound
```

are required.

Patch 7 does not invent a new exact quality schema.

---

# 11. DF-8 — Capture MUST NOT

**Status: FROZEN**

Patch 7 must not:

```text
replay .bag/.db3
judge FPS adequacy
judge posture correctness
recalculate quality verdict
change ok / ok_with_warnings / retake
select a retake
infer a recapture relation
assign a new recording_id
backfill missing modern capture provenance
```

Those are capture/hardware/scientific policy concerns, not repository integrity.

Patch 8 remains the real D455 formal hardware validation scope.

---

# 12. DF-9 — Analysis Run Discovery / Manifest Integrity

**Status: FROZEN**

Recognized canonical analysis run directory:

```text
analysis/<recording_id>/<analysis_run_id>/
```

with current run IDs beginning:

```text
ar_
```

Canonical owner:

```text
analysis_manifest.json
schema_version = analysis-provenance/1.0.0
```

Patch 7 validates at minimum:

```text
manifest is valid JSON object
schema_version
recording_id
analysis_run_id
analysis_batch_id
analysis_mode
parent_analysis_run_id
status
inputs
outputs
```

Directory identity and manifest identity must agree.

```text
path recording_id == manifest.recording_id
path analysis_run_id == manifest.analysis_run_id
```

Mismatch:

```text
IDENTITY_MISMATCH
→ ERROR
```

Patch 7 MUST NOT impose a new exact-key top-level schema where Patch 3 did not freeze one.

---

# 13. DF-10 — Analysis Status Semantics

**Status: FROZEN**

Allowed lifecycle states already produced by the current implementation:

```text
running
completed
failed
```

State itself is not integrity failure.

```text
status == failed
→ not ERROR by itself

status == running
→ not ERROR by itself
```

Patch 7 does not define a timeout after which `running` becomes failed/stale.

Patch 7 does not rewrite status.

However any fact already recorded in a running/failed manifest is still auditable.

For example:

```text
manifest output path/hash exists
→ actual artifact must match
```

If a manifest declares an artifact/hash and actual bytes contradict it, status does not excuse the contradiction.

---

# 14. DF-11 — Analysis Stored-Hash Audit

**Status: FROZEN**

For every repository-accessible analysis input/output carrying a stored complete SHA-256:

```text
expected SHA-256
==
SHA-256(actual exact bytes)
```

must hold.

If an analysis artifact record states:

```text
hash_status = complete
```

then a missing/invalid/mismatching hash is ERROR.

If historical provenance explicitly records hash unavailability according to an existing contract, Patch 7 does not fabricate a hash or silently upgrade the record.

Formal-role requirements already enforced by prior patches remain in force; Patch 7 does not weaken them.

---

# 15. DF-12 — Canonical Frames

**Status: FROZEN**

Patch 7 does not implement a second frames validator.

It reuses the existing Patch 4/5 canonical-input validation semantics, including:

```text
frames-schema/1.0.0
exact 60-field header
non-empty canonical identity rows
recording_id
analysis_run_id
subject
round
path identity
owner analysis_manifest identity
owner status == completed
unique owner output binding
owner output SHA-256
actual frames SHA-256
```

Any contradiction is ERROR.

Patch 7 does not add:

```text
dataset_role column
protocol_version column
new frame field
new missing-value semantic
```

---

# 16. DF-13 — Raw Identity Collision

**Status: FROZEN**

Patch 5 raw identity rule remains authoritative.

Across discovered `extract_raw` analysis manifests with usable full raw SHA-256:

```text
same raw SHA-256
+ multiple recording_id values
```

is an integrity conflict.

Result:

```text
IDENTITY_MISMATCH / GRAPH_INVALID
→ ERROR
```

Patch 7 audits existing repository state even when no new analysis operation is being started.

This is the repository-wide counterpart to the existing `validate_raw_identity()` guard.

---

# 17. DF-14 — Analysis Batch Integrity

**Status: FROZEN**

Recognized current batch authority:

```text
analysis/batches/<analysis_batch_id>/analysis_batch.json
```

Current batch object contains:

```text
analysis_batch_id
analysis_run_ids
outputs
run_manifests
```

Patch 7 validates at minimum:

```text
analysis_batch_id matches directory
analysis_run_ids are well formed/non-contradictory
run_manifests resolve to discovered run authorities
referenced run manifests declare the matching analysis_batch_id
shared output paths exist when recorded
stored complete output hashes match actual bytes
shared output analysis_run_ids agree with batch contributors when recorded
```

Patch 7 does not invent `analysis-batch/1.0.0` or another new batch schema version.

Additional descriptive fields are not rejected merely because Patch 7 did not freeze an exact-key batch schema.

---

# 18. DF-15 — Compatibility Analysis Artifacts

**Status: FROZEN**

Flat compatibility artifacts are not canonical provenance authority.

Examples:

```text
analysis/<recording_id>_frames.csv
analysis/<recording_id>_frames.csv.provenance.json
analysis/rf_results.csv
analysis/rf_results.txt
analysis/fig5_rf_compare.png
summary/report/plot compatibility copies
```

Absence of a compatibility copy is not ERROR.

Patch 7 does not infer latest/current canonical run from flat output timestamps.

If a flat frames file and its provenance sidecar explicitly claim a canonical owner, that claim must be true.

At minimum validate:

```text
recording_id
analysis_run_id
frames_sha256
analysis_manifest path
analysis_manifest_sha256
canonical owner output binding
```

A false compatibility provenance claim is ERROR.

Flat RF/report copies without a provenance claim are not promoted into canonical authority and are not used to judge the canonical results archive.

---

# 19. DF-16 — Selection Ledger Integrity

**Status: FROZEN**

Canonical selection ledger:

```text
manifests/selection_events.jsonl
schema = selection-event/1.0.0
```

If the ledger exists, Patch 7 validates the complete ledger from first byte to last byte using Patch 6 semantics.

Required checks include:

```text
canonical UTF-8 JSONL + LF
no malformed line
no duplicate JSON key
exact event schema where Patch 6 freezes exact fields
selection_event_id uniqueness
canonical round
logical slot validity
evidence shape/path/hash
single-terminal decision rule
linear supersession chain
broken supersedes reference
branching supersession
recapture self-link
multiple direct recapture parent
recapture cycle
role/protocol/source ownership checks
```

The entire ledger is checked; a checker may not validate only events currently used by the newest dataset manifest.

Malformed/torn final line is authoritative corruption:

```text
TORN_AUTHORITY
→ ERROR
```

Patch 7 never truncates the ledger.

---

# 20. DF-17 — Selection Evidence Deep Semantic Hardening

**Status: FROZEN**

Patch 6 M-2 is closed in Patch 7 by deeper checker-side semantic validation without changing `selection-event/1.0.0`.

## 20.1 `capture_provenance`

Must be:

```text
valid JSON object
schema_version = capture-provenance/1.0.0
recording_id matches pinned evidence identity
slot identity compatible with event
protocol_version present for modern provenance
exact pinned bytes hash matches
```

## 20.2 `analysis_manifest`

Must resolve to the exact pinned analysis authority and agree with:

```text
recording_id
analysis_run_id
selected canonical frames
status requirements already frozen by Patch 6
stored hash
```

Existing canonical-input validation is reused.

## 20.3 `canonical_frames`

Must satisfy the full existing canonical frames validator.

## 20.4 `quality`

Patch 7 validates only integrity semantics already justified by existing authority:

```text
valid JSON object
recording_id exists
recording_id matches pinned evidence/event identity
exact pinned bytes hash matches
```

Patch 7 does **not** newly require an exact top-level quality schema.

Patch 7 does **not** decide:

```text
verdict == ok required?
ok_with_warnings accepted for formal?
retake automatically excluded?
```

Those remain scientific selection-policy questions.

## 20.5 `other`

No frozen deep content schema exists for `kind == other`.

Patch 7 therefore validates only:

```text
normalized safe repository-relative path
artifact existence when pinned
exact pinned SHA-256
existing event evidence shape
```

It does not infer the meaning of arbitrary `other` bytes.

---

# 21. DF-18 — Selection Subtree Absence

**Status: FROZEN**

If no selection has yet been performed, the absence of:

```text
manifests/selection_events.jsonl
manifests/datasets/
```

is not ERROR.

However partial authority combinations are audited.

Examples:

```text
dataset manifest exists but canonical ledger missing
→ ERROR

RF experiment pins dataset manifest but manifest missing
→ ERROR

ledger exists with zero events and no dataset manifest
→ valid
```

---

# 22. DF-19 — Dataset Selection Manifest Integrity

**Status: FROZEN**

Canonical dataset manifests:

```text
manifests/datasets/<dataset_manifest_id>.json
schema = dataset-selection-manifest/1.0.0
```

Every discovered canonical dataset manifest is independently validated.

Required checks reuse Patch 6 semantics:

```text
canonical UTF-8 pretty JSON + LF bytes
exact frozen top-level/entry fields
valid dataset_manifest_id
ID/path identity
immutable canonical path
valid dataset_role
selection_policy_version rule
selection_events_path == canonical ledger path
unique logical slot
subject + int(round) deterministic ordering
selection event exists
selection event line SHA-256 matches
entry equals pinned event identity
selected analysis/run/frames identity matches
selected source hash matches
role/policy consistency
Patch 5 input ambiguity guard
```

Historical snapshot rule remains unchanged.

```text
old immutable dataset manifest
+ later superseding selection event
→ NOT corruption
```

Existing-manifest revalidation must not require its event to remain the current terminal selection.

---

# 23. DF-20 — RF Experiment Discovery / Manifest Integrity

**Status: FROZEN**

Recognized canonical RF experiment directory:

```text
results/<experiment_run_id>/
```

with current run IDs beginning:

```text
er_
```

Canonical owner:

```text
experiment_manifest.json
schema_version = rf-experiment-provenance/1.0.0
```

Patch 7 validates at minimum:

```text
valid JSON object
schema_version
experiment_run_id
run directory identity
status
inputs
dataset_manifest
sample_lineage
outputs
```

Patch 7 does not newly freeze exact top-level key equality beyond the existing RF provenance contract.

---

# 24. DF-21 — RF Status Semantics

**Status: FROZEN**

Existing RF lifecycle states:

```text
running
completed
failed
```

As with analysis:

```text
running != corruption
failed != corruption
```

Patch 7 does not define run staleness or timeout semantics.

Already recorded hashes/paths remain auditable in any state.

A terminal `completed` run receives stricter completeness checks below.

---

# 25. DF-22 — RF Inputs / Dataset Manifest Binding

**Status: FROZEN**

For every accessible recorded RF input:

```text
stored SHA-256 == actual exact-byte SHA-256
```

must hold.

For manifest-driven runs:

```text
experiment_manifest.dataset_manifest
```

must resolve to the exact immutable dataset manifest bytes pinned by:

```text
dataset_manifest_id
path
sha256
```

and re-resolution must produce the same canonical `inputs.ours` records recorded in the experiment manifest.

Patch 7 reuses the Patch 6 dataset-manifest resolver semantics; it does not independently choose replacement inputs.

---

# 26. DF-23 — RF Sample Lineage

**Status: FROZEN**

Canonical sample lineage:

```text
sample_lineage.jsonl
schema = rf-sample-lineage/1.0.0
```

When a manifest records a non-null lineage SHA or a completed run requires lineage, Patch 7 validates:

```text
file existence
stored SHA-256
row_count
exact LINEAGE_FIELDS set
schema_version
experiment_run_id
dataset_track
feature_mode
sample_index uniqueness/source key uniqueness
source_kind
canonical vs external required/null field separation
recording_id / analysis_run_id
frames path/hash
external source path/hash
reference recording/run identity constraints
```

Canonical-frame rows must resolve to the exact selected analysis/run/frame source.

External-table rows must remain tied to the exact recorded external artifact identity and physical source row.

Patch 7 does not recompute model features to validate scientific correctness.

---

# 27. DF-24 — Completed RF Outputs

**Status: FROZEN**

For `status == completed`, the run must satisfy the output relationships frozen by Patch 5.

Required canonical completion artifacts:

```text
experiment_manifest.json
sample_lineage.jsonl
rf_results.csv
rf_results.txt
```

`fig5_rf_compare.png` remains optional because current implementation explicitly permits optional plot failure.

For every output recorded in `experiment_manifest.outputs`:

```text
path exists
stored size is consistent when recorded
stored SHA-256 == actual SHA-256
```

must hold.

`rf_results.csv` lineage fields must not contradict experiment authority:

```text
experiment_run_id
dataset_manifest_sha256
lineage_manifest_path
lineage_manifest_sha256
```

Patch 7 does not validate model accuracy/F1 values against a scientific expected value.

---

# 28. DF-25 — Failed / Running RF Runs

**Status: FROZEN**

For a failed/running run, absence of not-yet-produced final outputs is not ERROR by itself.

Example:

```text
status = failed
rf_results.csv absent
→ not automatically ERROR
```

But if the manifest already records:

```text
sample_lineage SHA
output path/hash
input path/hash
```

those recorded facts must match accessible bytes.

---

# 29. DF-26 — External Input Rule

**Status: FROZEN**

Patch 5 RF provenance may store absolute paths for external source files.

Patch 7 distinguishes repository-owned and external-owned artifacts.

## 29.1 Repository-owned path

If a recorded path resolves inside the repository root:

```text
missing
or hash mismatch
→ ERROR
```

## 29.2 External path currently accessible

If a recorded path is outside the repository but currently exists:

```text
actual SHA == stored SHA
```

is required.

Hash mismatch:

```text
HASH_MISMATCH
→ ERROR
```

## 29.3 External path currently inaccessible

If a valid historical external path is outside the repository and no longer exists on the current machine:

```text
EXTERNAL_UNVERIFIABLE
→ WARNING
```

Patch 7 does not search the filesystem for a same-named substitute.

Patch 7 does not change the provenance record to a new location.

---

# 30. DF-27 — Repository-Wide Stored Hash Audit

**Status: FROZEN**

Patch 7 rechecks every stored SHA-256 relation that can be evaluated from existing authority.

Examples include:

```text
analysis input hashes
analysis output hashes
canonical frames hashes
selection evidence hashes
selection-event line hashes pinned by dataset manifests
dataset-manifest selected source hashes
RF input hashes
RF dataset-manifest hash
RF sample-lineage hash
RF output hashes
accessible external source hashes
local model artifact hash when present
```

Patch 7 does not require every file in the repository to have a stored SHA.

It audits existing hash assertions; it does not invent a new global hash catalog.

---

# 31. DF-28 — Missing Artifact Definition

**Status: FROZEN**

`missing artifact` means:

> Existing frozen authority requires an artifact to exist, or an authority record explicitly says that artifact exists, but the artifact is not present at the resolved location.

Examples:

```text
analysis manifest output record exists → output file absent
selection evidence path exists in event → evidence file absent
dataset manifest entry points to selected canonical frames → frames absent
completed RF manifest records output → output absent
```

These are ERROR.

The following are not unconditional missing errors:

```text
_samples.csv when no samples were produced
optional fig5_rf_compare.png
selection subtree before first selection
future output of failed/running run
local model cache before provisioning
compatibility copy
```

---

# 32. DF-29 — Structural Orphan Definition

**Status: FROZEN**

`orphan` does **not** mean:

```text
not selected
not used by RF
not latest
not current terminal selection
```

Structural orphan means:

> An artifact occupies a canonical managed derivative namespace or makes an explicit ownership claim, but no valid frozen owner/authority relation can account for it.

Examples:

```text
canonical-looking frames in analysis/<rid>/<ar_*> with no owning analysis manifest/output record
sample_lineage.jsonl in results/<er_*> with no matching experiment authority
compatibility provenance sidecar that points to a nonexistent owner
canonical dataset manifest whose referenced selection event does not exist
```

Structural orphan of a canonical derivative artifact is ERROR.

## 32.1 Empty/incomplete run directory exception

A recognized run directory may be created before its owner manifest is safely persisted.

Therefore:

```text
empty/temporary-only analysis or RF run directory with no manifest
→ WARNING INCOMPLETE_NONTERMINAL
```

But:

```text
canonical-looking derived artifacts present
+ owner manifest absent
→ ERROR STRUCTURAL_ORPHAN
```

## 32.2 Capture root exception

A capture attempt is a root of provenance, not a derivative that must be selected downstream.

Therefore an unused capture is never an orphan merely because nothing references it.

A capture companion with no valid modern camera authority may be WARNING when it can represent a failed/legacy partial capture, unless another authority explicitly depends on it; then the contradiction is ERROR.

---

# 33. DF-30 — Mixed Artifact / Identity Contamination

**Status: FROZEN**

Patch 7 must detect explicit cross-identity contamination.

Examples:

```text
recording A camera + recording B sidecar row
analysis directory recording_id != manifest recording_id
analysis directory run ID != manifest analysis_run_id
frames rows belong to another run
analysis manifest output points to another owner/run
selection event pins evidence for conflicting recording
selection analysis_selection differs from canonical source identity
dataset entry differs from pinned selection event bytes/hash
RF lineage row uses another experiment_run_id
canonical RF row uses another recording/run source
```

Result:

```text
IDENTITY_MISMATCH / OWNER_MISMATCH / GRAPH_INVALID
→ ERROR
```

Patch 7 does not merge identities to repair the graph.

---

# 34. DF-31 — Torn / Partial / Malformed Authority

**Status: FROZEN**

Patch 6 M-3 is addressed at minimum through explicit detection and diagnostics.

Patch 7 must detect:

```text
torn/malformed selection ledger line
partial malformed dm_*.json occupying canonical immutable dataset-manifest path
malformed canonical JSON authority
canonical serialization violation where serialization is frozen
recognized leftover temporary publication file
```

Canonical final authority that is malformed/torn:

```text
TORN_AUTHORITY / SERIALIZATION_INVALID
→ ERROR
```

A recognized temporary file that does not replace/claim final authority:

```text
TEMP_RESIDUE
→ WARNING
```

Recognized current temporary patterns may include, when present:

```text
.manifest-*.tmp
.experiment_manifest.tmp
.model-*.tmp
```

Implementation must avoid treating arbitrary user `.tmp` files outside known producer patterns as research authority.

---

# 35. DF-32 — Recovery Behavior

**Status: FROZEN**

Patch 7 checker is detect/classify/report only.

Automatic recovery is forbidden.

The checker must not:

```text
truncate torn JSONL tail
remove malformed event
rewrite selection history
rewrite dataset manifest
regenerate selection event
change stored SHA
rewrite analysis/RF manifest
change status running→failed
remove orphan
remove temp file
rename recording
```

Operator recovery guidance may be documented after a finding, but the checker itself remains non-destructive.

Any future repair command would require a separate explicit contract because append-only/immutable historical artifacts must not be rewritten casually.

---

# 36. DF-33 — MediaPipe Model Lock

**Status: FROZEN**

Tracked authority:

```text
mediapipe_model_lock.json
schema = mediapipe-model-lock/1.0.0
```

Patch 7 reuses the existing lock validator for:

```text
exact top-level structure
roles
filenames
source/version contract
SHA-256 format
```

No network call is allowed.

For each locked model file under `models/`:

```text
if file exists
→ actual SHA must match lock
```

Mismatch is ERROR.

If the local cache file does not exist:

```text
not ERROR
```

because model provisioning is an existing runtime operation and the cache is not required to be committed.

Patch 7 does not download or replace model artifacts.

---

# 37. DF-34 — Manifest Self-Hash / External Integrity Anchor

**Status: FROZEN — EXPLICITLY OUT OF PATCH 7 v1**

Patch 5 noted that `experiment_manifest.json` cannot record its own SHA-256 internally without circularity and that Patch 7 could introduce a separate authority.

Patch 7 v1 intentionally does **not** introduce:

```text
global manifest hash registry
repository root hash
Merkle tree
signed manifest catalog
external timestamp/notary
new integrity-catalog schema
```

Reason:

```text
such a registry becomes a new provenance authority with its own lifecycle,
immutability, update, signing, and recovery rules.
```

Patch 7 v1 instead completes:

```text
existing-authority internal consistency
repository-wide stored-hash audit
missing/orphan detection
cross-identity graph audit
```

Explicit limitation:

> If an attacker coherently replaces an unexternally-anchored authority manifest and every dependent value that is not anchored elsewhere, Patch 7 v1 is not a cryptographic tamper-proofing system.

This limitation is accepted and does not block Patch 7 closure.

---

# 38. DF-35 — Scientific Semantics MUST NOT CHANGE

**Status: FROZEN**

Patch 7 must not modify or newly decide:

```text
frames-schema/1.0.0 exact 60 fields
summary-schema/1.0.0
rf-sample-lineage/1.0.0
rf-experiment-provenance/1.0.0
selection-event/1.0.0
dataset-selection-manifest/1.0.0

F1/F2 formula
RF feature calculation
M0/M1/M2 algorithm
Tree / Forest behavior
weighting
lambda semantics
seed policy
LOSO grouping
relative-reference semantics
calibration semantics
missing-value scientific semantics
class/label scientific meaning
formal participant count
formal round count
formal inclusion/exclusion policy
retake scientific policy
ok_with_warnings formal acceptance policy
Patch 8 hardware-validation criteria
```

Patch 7 implementation must not require schema field additions to existing frozen schemas.

---

# 39. DF-36 — Authority Expansion / Provenance Inference MUST NOT OCCUR

**Status: FROZEN**

Patch 7 must not infer missing authority from convenience heuristics.

Forbidden examples:

```text
legacy raw filename → inferred modern recording_id
newest timestamp → canonical analysis run
largest ar_* ID → canonical analysis run
same basename → assumed same artifact despite hash mismatch
missing external file → substitute another same-named file
old running run → automatically failed
similar SHA prefix → same recording
flat compatibility file → canonical authority
latest dataset manifest → current scientific dataset
```

When frozen linkage is absent:

```text
unknown / unresolved / warning
```

is preferable to invented provenance.

---

# 40. Explicit Rejected Behaviors

Patch 7 explicitly rejects:

```text
repair-on-scan
best-effort silent skip of corrupted authority
warning-only downgrade of proven hash mismatch
auto-deletion of orphan artifacts
auto-truncation of selection ledger
auto-regeneration of immutable dataset manifest
auto-selection of latest analysis run
auto-retake choice
auto formal inclusion/exclusion
network-based artifact replacement
hardware-dependent integrity PASS
scientific metric recalculation as integrity authority
```

---

# 41. Backward / Historical Compatibility

Patch 7 must distinguish modern canonical authority from explicitly supported legacy provenance.

A legacy analysis record that prior patches intentionally allow must not be rejected solely because it lacks modern capture provenance fields.

Patch 7 validates the legacy record according to what the existing authority actually knows.

It must not backfill:

```text
recording_id
protocol_version
capture provenance
model provenance
selection decision
```

from guesses.

Compatibility outputs remain non-authoritative unless they carry an explicit provenance sidecar/claim that can be validated.

---

# 42. Acceptance Criteria

## Integrity failures that MUST be detected

```text
AC-01  stored SHA-256 mismatch is ERROR.
AC-02  authority-recorded required artifact missing is ERROR.
AC-03  modern capture recording_id vs existing sidecar recording_id mismatch is ERROR.
AC-04  modern capture record_file points to missing raw artifact is ERROR.
AC-05  analysis directory recording_id vs manifest recording_id mismatch is ERROR.
AC-06  analysis directory run ID vs manifest analysis_run_id mismatch is ERROR.
AC-07  analysis complete-hash input/output mismatch is ERROR.
AC-08  canonical frames wrong exact header/schema is ERROR.
AC-09  canonical frames owner/path/run/recording mismatch is ERROR.
AC-10  canonical frames owner output SHA mismatch is ERROR.
AC-11  same authoritative raw SHA mapped to multiple recording_id values is ERROR.
AC-12  analysis batch/run ownership contradiction is ERROR.
AC-13  false flat frames provenance sidecar claim is ERROR.
AC-14  malformed/torn selection ledger line is ERROR.
AC-15  duplicate/broken/branching selection history is ERROR.
AC-16  recapture self-link/multiple-parent/cycle is ERROR.
AC-17  selection evidence pinned hash mismatch is ERROR.
AC-18  selection evidence recording identity mismatch is ERROR.
AC-19  selected analysis/canonical frames owner mismatch is ERROR.
AC-20  malformed/partial canonical dataset manifest is ERROR.
AC-21  dataset manifest ID/path mismatch is ERROR.
AC-22  dataset manifest selection-event line hash mismatch is ERROR.
AC-23  dataset manifest references nonexistent event/source is ERROR.
AC-24  RF directory ID vs experiment manifest ID mismatch is ERROR.
AC-25  accessible RF input hash mismatch is ERROR.
AC-26  manifest-driven RF dataset manifest hash/binding mismatch is ERROR.
AC-27  sample_lineage stored hash mismatch is ERROR.
AC-28  sample_lineage row experiment/source identity mismatch is ERROR.
AC-29  completed RF required canonical output missing is ERROR.
AC-30  completed RF output hash mismatch is ERROR.
AC-31  rf_results.csv lineage authority fields contradict experiment manifest is ERROR.
AC-32  canonical derivative artifact with missing owner is structural-orphan ERROR.
AC-33  accessible external artifact hash mismatch is ERROR.
AC-34  local locked model artifact present with wrong SHA is ERROR.
AC-35  managed path set changes during audit and checker therefore cannot claim stable PASS.
```

## States that MUST NOT be false-positive ERROR

```text
AC-36  capture not selected downstream is valid.
AC-37  completed analysis not selected downstream is valid.
AC-38  preserved failed capture with record_file=null is not ERROR by itself.
AC-39  missing _samples.csv is not ERROR when no frozen relation requires it.
AC-40  failed analysis with partial future outputs absent is not ERROR by itself.
AC-41  running analysis is not ERROR solely because it is running.
AC-42  failed RF run without final outputs is not ERROR solely for that absence.
AC-43  running RF run is not ERROR solely because it is running.
AC-44  historical immutable dataset manifest remains valid after later supersession.
AC-45  missing optional fig5_rf_compare.png is not ERROR when not recorded as an output.
AC-46  selection subtree not yet created is not ERROR.
AC-47  missing local MediaPipe cache is not ERROR.
AC-48  inaccessible external absolute-path artifact is WARNING, not silent PASS and not automatic substitute.
AC-49  compatibility copy absence is not ERROR.
AC-50  legacy supported provenance is not rejected solely for lacking modern capture sidecar.
AC-51  warning-only repository exits 0.
```

## Non-destructive / regression criteria

```text
AC-52  checker does not modify artifact bytes.
AC-53  checker does not alter selection ledger length/content.
AC-54  checker does not rewrite immutable dataset manifests.
AC-55  checker performs no network access.
AC-56  checker requires no RealSense hardware.
AC-57  pre-Patch-7 330-test regression remains PASS.
AC-58  Patch 7 introduces no change to RF numerical semantics.
AC-59  Patch 7 introduces no change to selection scientific policy.
AC-60  repeated audit of a stable repository produces deterministic severity/count/path ordering.
```

---

# 43. Minimum Test Matrix

Patch 7 targeted tests must include at least the following categories.

## 43.1 Clean states

```text
empty generated-artifact repository
modern valid capture
failed reserved capture
valid completed analysis
valid failed/running analysis
valid batch
valid selection ledger
valid historical superseded dataset manifest
valid completed RF run
valid failed/running RF run
missing optional plot
missing model cache
```

## 43.2 Hash corruption

```text
analysis input hash mismatch
analysis output hash mismatch
selection evidence hash mismatch
dataset event-line SHA mismatch
RF input hash mismatch
sample-lineage hash mismatch
RF output hash mismatch
local model artifact hash mismatch
```

## 43.3 Identity / ownership corruption

```text
capture sidecar recording mismatch
analysis path/manifest recording mismatch
analysis path/manifest run mismatch
frames row owner mismatch
raw SHA identity fork
batch/run mismatch
flat provenance false owner
selection evidence identity mismatch
selected frames owner mismatch
RF experiment path/ID mismatch
sample lineage experiment/run mismatch
```

## 43.4 Missing / orphan

```text
declared raw missing
declared analysis output missing
dataset source missing
completed RF output missing
canonical frames without owner
sample lineage without experiment owner
empty run directory without owner = warning
```

## 43.5 Torn / malformed

```text
torn final JSONL line
partial dm_*.json
malformed camera JSON
malformed experiment/analysis authority
recognized temp residue warning
```

## 43.6 External artifact

```text
external accessible + matching hash
external accessible + mismatching hash
external inaccessible
repository-owned absolute input missing
```

## 43.7 Side-effect checks

Before/after digest or exact-byte assertions for fixture authorities must prove the checker performs no repair/rewrite.

---

# 44. Implementation Map

**Status: FROZEN AT MODULE BOUNDARY; INTERNAL FUNCTION NAMES NOT FROZEN**

## 44.1 New module

```text
integrity_check.py
```

Responsibilities:

```text
managed inventory
finding collection
capture checks
analysis checks
selection checks
dataset-manifest checks
RF checks
model-lock checks
cross-layer graph checks
stable reporting / exit status
```

## 44.2 New tests

Recommended:

```text
test_patch7_integrity.py
```

The test file name may differ if repository test organization requires, but Patch 7-specific targeted tests must remain identifiable.

## 44.3 Existing validators

Patch 7 should reuse rather than duplicate proven validators where practical, including semantics from:

```text
analyze_d455.py
rf_experiment.py
selection_manifest.py
```

Reusing a validator must not make the checker write artifacts or trigger network/hardware behavior.

## 44.4 Existing producer changes

Patch 7 does not require producer schema changes.

Producer code may be refactored only when necessary to expose pure validation logic or correct a proven integrity bug found during implementation.

Such refactor must preserve current producer behavior and existing tests.

Automatic repair/failure-recovery write paths are not part of Patch 7 v1.

---

# 45. Out of Scope / Non-Goals

```text
automatic repair
automatic deletion
automatic artifact migration
automatic selection/exclusion
automatic retake decision
legacy provenance reconstruction by guessing
new scientific schema
new RF algorithm
new metric
formal study policy
formal participant/round freeze
D455 real-hardware validation
raw video semantic/content inspection
model download
cryptographic signing
external manifest hash registry
Merkle/root integrity catalog
remote storage verification
cloud backup verification
```

---

# 46. Accepted Limitations

Patch 7 closure may still have the following explicit limitations.

## L-1 — No external cryptographic anchor

A coherently rewritten unanchored authority graph may be outside detection if all internally compared values are changed consistently and no surviving external/pinned hash contradicts it.

## L-2 — External file availability

An external historical input that is absent from the current machine cannot have its bytes rehashed; this is WARNING, not proof of integrity.

## L-3 — No scientific truth validation

The checker proves consistency with recorded authority, not that an experiment design or label is scientifically correct.

## L-4 — No hardware truth validation

The checker does not prove camera timing, USB mode, physical posture quality, or RealSense recording usability.

## L-5 — No automatic recovery

A torn authority can be detected without the checker modifying it.

These limitations are intentional and do not block Patch 7 completion.

---

# 47. Patch 7 Invariant

Before and after Patch 7 implementation, for an unchanged valid repository:

```text
same research bytes
same canonical schemas
same capture identities
same analysis identities
same selection history
same dataset manifests
same RF sample inclusion
same numerical outputs
same scientific evaluation behavior
```

Patch 7 adds only:

```text
repository-wide observability
integrity contradiction detection
deep existing-authority validation
torn/partial diagnostics
```

---

# 48. Definition of Done

## 48.1 Design Freeze

Design Freeze is complete when:

```text
PATCH_07_integrity_checker_hardening.md committed
PROV-008 appended in RESEARCH_DECISION_LOG.md
no Python implementation change in the freeze commit
no test implementation change in the freeze commit
base remains main 6e6f577 unless an explicitly documented pre-freeze sync changes it
```

Recommended branch:

```text
patch7/integrity-checker-hardening
```

Recommended Design Freeze commit message:

```text
docs: freeze Patch 7 integrity checker design
```

## 48.2 Implementation

Implementation is complete when:

```text
checker entry point implemented
managed inventory implemented
all frozen ERROR/WARNING/INFO semantics implemented
Patch 1–6 validators reused or faithfully enforced
Patch 7 targeted tests PASS
pre-existing tests PASS
```

## 48.3 Independent audit

Before closure:

```text
independent READ-ONLY implementation audit
→ BLOCKER / IMPORTANT / MINOR classification
→ no implementation mutation during audit
```

Any BLOCKER/IMPORTANT is resolved or explicitly prevents closure.

## 48.4 Closure

After software verification and independent audit:

```text
closure docs synchronized
main merge
post-merge full regression
working tree clean
origin/main sync
```

Status documents are synchronized at closure, not prematurely at Design Freeze.

---

# 49. Design Freeze Commit Boundary

The Design Freeze commit SHOULD contain only authority documentation required to freeze the contract.

Expected files:

```text
docs/foundation/PATCH_07_integrity_checker_hardening.md
docs/research/RESEARCH_DECISION_LOG.md   # append PROV-008 only
```

The freeze commit must not modify:

```text
capture_d455.py
analyze_d455.py
rf_experiment.py
selection_manifest.py
existing tests
research data artifacts
generated manifests/results
```

`AGENTS.md`, `CLAUDE.md`, `RESEARCH_DATA_SCHEMA.md`, and `docs/research/AIoT_RESEARCH_MASTER.md` do not need premature Patch 7 completion claims at Design Freeze.

They are synchronized when implementation/audit/closure state is known.

---

# 50. Frozen Objective

Patch 7 objective is frozen as follows:

> **Patch 7 shall provide a read-only repository-wide integrity checker that inventories the existing Patch 1–6 research artifacts, revalidates every frozen ownership, identity, hash, serialization, and lineage relationship that can be verified from existing authority, detects missing, mixed, hash-mismatched, structurally orphaned, malformed, and torn authoritative artifacts, and fails closed on proven contradictions, while making no scientific selection decision, no numerical-semantic change, no historical rewrite, no automatic repair, and no new provenance inference.**

---

# 51. Current Disposition

At this Design Freeze boundary:

```text
READ-ONLY investigation        DONE
gap analysis                   DONE
exact contract                 DONE
Design Freeze document         READY TO COMMIT
PROV-008 Decision Log sync     REQUIRED IN SAME FREEZE COMMIT
implementation                 NOT STARTED
targeted tests                 NOT STARTED
independent READ-ONLY audit    NOT STARTED
closure                        NOT STARTED
main integration               NOT STARTED
```

Next action after the Design Freeze commit:

```text
implement Patch 7 exactly against this frozen contract
→ targeted tests
→ full regression
→ independent READ-ONLY audit
```

Real D455 formal hardware validation remains:

```text
Patch 8 scope
```


---

# Post-Freeze Clarification — PROV-009

Status: CONFIRMED
Logged: 2026-10-05

This addendum clarifies the historical CSV-mode compatibility-input
semantics identified during the independent Patch 7 implementation audit.

## C-1. Mutable flat compatibility publication

The following paths are mutable compatibility publications, not persistent
historical byte anchors:

analysis/<recording_id>_frames.csv
analysis/<recording_id>_frames.csv.provenance.json

A later legitimate raw re-analysis of the same recording may replace these
files.

Therefore:

historical CSV-mode stored flat-input SHA
!=
current flat compatibility publication SHA

MUST NOT by itself produce an integrity ERROR.

## C-2. Historical CSV-mode authority

Historical CSV-mode source integrity MUST instead be verified through:

historical CSV-mode run
→ archived source_frames
→ parent analysis identity
→ parent analysis_manifest
→ parent canonical frames/output hash

Missing, corrupted, hash-mismatched, or identity-inconsistent immutable
artifacts in this chain remain ERROR conditions.

## C-3. Scope

This clarification applies only to historical CSV-mode references to the
mutable flat compatibility publication.

It does NOT weaken stored-hash verification for:

- run-scoped archived analysis artifacts
- canonical analysis outputs
- selection evidence
- dataset-manifest sources
- RF inputs
- sample lineage
- RF outputs
- other immutable authoritative artifacts

No latest/newest/mtime heuristic becomes provenance authority.

The checker remains READ-ONLY.

## C-4. Required regression

Patch 7 tests MUST demonstrate:

1. raw A → CSV B → later raw re-analysis C
   → B remains valid when its immutable archived lineage is intact.

2. Same scenario with archived source_frames corruption
   → ERROR.

3. Same scenario with authoritative parent source missing/corrupt
   → ERROR.

Authority:
PROV-009 — Patch 7 Mutable Compatibility Input Integrity Clarification

---
# Post-Freeze Clarification — PROV-010

Status: CONFIRMED
Logged: 2026-10-05

This addendum clarifies two additional authority boundaries identified by the
Patch 7 Round 2 independent READ-ONLY re-audit:

1. how mutable compatibility publication identity is established across
   modern and legacy-pilot naming; and
2. when selection evidence requires a completed analysis owner.

Authority:
PROV-010 — Patch 7 Compatibility Identity and Selection-Evidence Completion Clarification

## D-1. Mutable compatibility identity is provenance-defined

The literal modern path:

analysis/<recording_id>_frames.csv

is an example of a mutable flat compatibility publication, not the complete
identity rule for that artifact role.

Patch 7 MUST identify the mutable compatibility publication through the
explicit frozen provenance relationship recorded by the parent analysis
output, including its `compatibility_path`, rather than by a filename pattern
alone.

Therefore both of the following may represent the same mutable semantic role:

modern:
analysis/<recording_id>_frames.csv

legacy-pilot:
analysis/<raw-stem>_frames.csv

when the parent authoritative frames output explicitly identifies that path as
its compatibility publication.

The `.provenance.json` sibling associated with the explicitly identified flat
publication follows the same historical compatibility semantics.

## D-2. No wildcard or currentness inference

Patch 7 MUST NOT infer mutable compatibility identity from:

- `*_frames.csv` naming alone
- basename similarity
- mtime
- ctime
- directory order
- lexical ordering
- newest/largest analysis_run_id
- any latest/newest heuristic

An unrelated or immutable `*_frames.csv` remains subject to ordinary stored-hash
verification.

PROV-009's mutable-publication exception applies only when the artifact role is
established by an explicit frozen provenance relationship.

## D-3. Legacy historical CSV lifecycle

The following legal legacy lifecycle MUST NOT fail solely because the flat
publication was legitimately replaced:

legacy raw analysis A
→ parent frames output explicitly records legacy compatibility_path
→ CSV-mode analysis B consumes that publication
→ B preserves archived source_frames and explicit parent lineage
→ later legacy raw analysis C replaces the same flat publication
→ historical B flat-input SHA differs from the current flat SHA

If B's immutable archived source and parent lineage remain intact, the historical
flat SHA mismatch alone is NOT an integrity ERROR.

Historical integrity remains anchored by:

historical CSV-mode run
→ archived source_frames
→ explicit parent analysis identity
→ parent analysis_manifest
→ parent canonical frames/output
→ authoritative stored hash

The following remain ERROR:

- archived source_frames missing
- archived source_frames hash mismatch
- archived source identity/schema mismatch
- parent manifest missing
- parent recording_id mismatch
- parent analysis_run_id mismatch
- parent canonical output missing
- parent output ownership mismatch
- parent authoritative hash mismatch
- false current compatibility ownership claim

## D-4. Selection evidence role is not selected-source role

Patch 7 MUST preserve the Patch 6 distinction between:

A. historical evidence referenced by a selection event; and
B. a canonical analysis source selected for downstream consumption.

Merely referencing an `analysis_manifest` as evidence does NOT automatically
turn that analysis into a completed consumable canonical source.

## D-5. Exclude evidence may reference a non-completed analysis

For a Patch 6-valid exclude decision, a failed/running/incomplete analysis may be
referenced as historical decision evidence when that role is allowed by the
frozen Patch 6 contract.

Patch 7 MUST NOT report OWNER_MISMATCH solely because:

analysis status != completed

when validating that exclude evidence.

However, all applicable historical-evidence integrity checks remain mandatory,
including:

- manifest existence and parseability
- recording_id
- analysis_run_id
- recorded output path
- declared artifact existence
- stored SHA versus actual bytes
- canonical frames header/schema
- row identity
- owner/output relation
- selection-event reference consistency

Non-completed status is not corruption by itself; corrupted evidence remains
ERROR.

## D-6. Include-selected canonical source still requires completion

Where an include decision selects an analysis as the canonical source for
dataset/RF/downstream consumption, all existing Patch 6 completed-owner
requirements remain in force.

Applicable include/consumer validation continues to require:

- completed analysis owner
- exact recording_id
- exact analysis_run_id
- exact frames artifact
- exact hash
- existing dataset-role and lineage constraints

This clarification MUST NOT weaken completed-owner enforcement for:

- include-selected analysis sources
- dataset-manifest canonical sources
- RF canonical inputs
- parent authoritative sources where completion is required by frozen authority
- current compatibility claims of canonical ownership

## D-7. DF-17 interpretation

DF-17 evidence validation does not create a new global rule that every
`analysis_manifest` or `canonical_frames` artifact used as evidence must have a
completed owner.

Patch 7 MUST preserve status requirements already frozen by Patch 6 according
to the artifact's role.

For this ambiguity:

exclude historical evidence
→ historical/evidence integrity validation
→ completion not required by status alone

include-selected canonical source
→ canonical consumer validation
→ completion required

This PROV-010 interpretation controls this specific conflict.

## D-8. Required regressions

Before Patch 7 implementation commit, targeted tests MUST demonstrate at least:

### Legacy compatibility lifecycle

1. legacy raw A → CSV B → later legacy raw C
   → NO ERROR solely because B's historical flat SHA differs from the current
     explicitly identified compatibility publication.

2. Same lifecycle + archived source corruption
   → ERROR.

3. Same lifecycle + parent canonical source loss/corruption
   → ERROR.

4. Unrelated/non-compatibility `*_frames.csv` hash mismatch
   → ERROR.

### Selection evidence completion

5. failed analysis + valid recorded output + Patch 6-valid exclude event using
   that analysis as evidence
   → NO ERROR solely because the analysis status is failed.

6. Same exclude evidence + output hash corruption
   → ERROR.

7. Same exclude evidence + schema/identity corruption
   → ERROR.

8. Include decision selecting a non-completed analysis
   → ERROR.

## D-9. Scope / invariants

This clarification does NOT change:

- frames-schema/1.0.0
- summary-schema
- selection-event serialization
- dataset-selection-manifest schema
- RF experiment schema
- sample-lineage schema
- Patch 6 include semantics
- RF completed-owner requirements
- scientific inclusion/exclusion policy
- retake policy
- F1/F2 definitions
- Patch 8 hardware-validation criteria

The following invariants remain mandatory:

1. Patch 7 remains READ-ONLY.
2. PROV-009 remains in force.
3. Compatibility identity is established through explicit provenance, not
   filename guessing or currentness heuristics.
4. Modern and legacy naming may represent the same mutable compatibility role.
5. Historical CSV integrity remains anchored by immutable archived source +
   explicit parent lineage.
6. Exclude evidence is not promoted into a consumable canonical source merely
   because it references an analysis manifest.
7. Failed/running/incomplete status alone is not corruption.
8. Corrupted historical evidence remains ERROR.
9. Include-selected canonical sources retain completed-owner enforcement.
10. RF/dataset consumer completion rules remain unchanged.
11. Scientific/numerical behavior remains unchanged.
12. Patch 1–6 schemas and selection semantics are not rewritten.

## D-10. Round 3 commit gate

Patch 7 implementation remains uncommitted until the focused Round 3 repair:

- resolves Round 2 re-audit N-1
- resolves Round 2 re-audit N-2
- adds the required regressions above
- passes targeted and full regression
- passes a subsequent independent READ-ONLY re-audit with:

BLOCKER == 0
IMPORTANT == 0
