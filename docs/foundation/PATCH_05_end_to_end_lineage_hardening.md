# PATCH_05 — End-to-End Lineage Hardening

> 상태: **IMPLEMENTED / SOFTWARE-VERIFIED / INDEPENDENTLY AUDITED / DOCUMENTATION-CLOSED / HARDWARE RUN NOT REQUIRED FOR CLOSURE**
>
> 운영상 Patch 번호: **Foundation Patch 5**
>
> Design Freeze authority:
>
> ```text
> docs/research/RESEARCH_DECISION_LOG.md
> → PROV-005 — Patch 5 End-to-End Lineage Hardening Design Freeze
> ```
>
> Design Freeze baseline:
>
> ```text
> branch: patch5/end-to-end-lineage-hardening
> base:   0f8bb81
>         docs: sync Patch 4.5 main merge status
> ```
>
> pre-implementation software baseline:
>
> ```text
> 204 tests PASS
> ```
>
> Design Freeze commit:
>
> ```text
> d4dc23f
> docs: freeze Patch 5 end-to-end lineage hardening design
> ```
>
> implementation commit:
>
> ```text
> dd0464e
> feat: implement Patch 5 end-to-end lineage hardening
> ```
>
> software verification:
>
> ```text
> baseline             204 PASS
> Patch 5 targeted      48 PASS
> final suite          252 PASS
> ```
>
> independent READ-ONLY audit:
>
> ```text
> verdict    PASS WITH MINOR FINDINGS
> BLOCKER    0
> IMPORTANT  0
> MINOR      6
> commit recommendation: YES
> ```
>
> documentation closure milestone:
>
> ```text
> 2026-10-04
> ```
>
> 본 문서는 `PROV-005` Design Freeze contract와 Patch 5의 구현·검증·독립 audit·closure evidence를 함께 기록하는 canonical Foundation Record다.
> Patch 5 closure는 formal research data 승인, Patch 6 selection policy 완료, Patch 7 integrity checker 완료 또는 Patch 8 actual D455 formal validation 완료를 의미하지 않는다.

---

# 1. 목적

Patch 5의 목적은 다음 연구 산출물 흐름 전체에서 artifact identity와 parent lineage를 잃지 않도록 하는 것이다.

```text
capture
→ recording
→ analysis
→ canonical frames
→ summary
→ RF input
→ RF experiment/result
```

최종 RF 결과에서 최소한 다음 역추적이 가능해야 한다.

```text
RF result
→ exact experiment run
→ exact RF input sample lineage
→ exact canonical frames bytes
→ exact analysis run
→ exact raw recording content
→ recording identity
```

Patch 5의 기본 원칙은 다음과 같다.

```text
ambiguity
→ 자동 추론하지 않음
→ 자동 최신 선택하지 않음
→ 자동 retake 선택하지 않음
→ fail closed
```

---

# 2. 이미 완료된 Foundation과 경계

다음 Foundation은 완료 상태이며 Patch 5에서 재설계하지 않는다.

```text
Foundation Prelude = DONE

Patch 1
Capture Recording Provenance
= DONE

Patch 2
Forward Gate Evidence
= DONE

Patch 3
Analysis Provenance
= DONE
= analysis-provenance/1.0.0

Patch 4
Canonical Fixed Frames Schema + Hip Raw Observations
= DONE
= frames-schema/1.0.0
= exact 60 fields

Patch 4.5
MediaPipe Model Artifact Lock
= DONE
= mediapipe-model-lock/1.0.0
= 204 tests PASS
```

특히 다음 contract는 유지한다.

```text
recording_id
= 촬영 시도의 identity

analysis_run_id
= 분석 실행의 identity

frame_index
= 1-based

raw inference
= Patch 4.5 locked model verification 필요

--from-csv historical reprocessing
= current model provisioning을 강제하지 않음
= historical parent provenance 유지
```

---

# 3. Repository에서 확인된 현재 구조

## 3.1 Analysis run archive

현재 canonical provenance archive:

```text
analysis/
└── <recording_id>/
    └── <analysis_run_id>/
        ├── analysis_manifest.json
        └── run archive outputs
```

`analysis_manifest.json`:

```text
schema_version = analysis-provenance/1.0.0
```

주요 identity:

```text
recording_id
analysis_run_id
analysis_batch_id
parent_analysis_run_id
analysis_mode
dataset_role
protocol_version
inputs
code
environment
models
outputs
```

---

## 3.2 Analysis batch archive

현재 shared summary/report/plot archive:

```text
analysis/
└── batches/
    └── <analysis_batch_id>/
        ├── analysis_batch.json
        ├── summary_steps.csv
        ├── summary_report.txt
        └── plots...
```

flat compatibility output도 유지된다.

```text
analysis/summary_steps.csv
analysis/<recording>_frames.csv
analysis/<recording>_frames.csv.provenance.json
```

원칙:

```text
run/batch archive
= provenance authority

flat output
= compatibility surface
```

Patch 5에서도 이 구분을 유지한다.

---

# 4. Confirmed Gaps

READ-ONLY repository investigation과 synthetic probes에서 다음이 확인됐다.

## GAP-1 — 동일 raw bytes가 서로 다른 recording identity를 가질 수 있음

현재 legacy ID는 legacy filename stem과 raw SHA-256을 이용해 생성될 수 있다.

따라서 byte-identical raw가:

```text
modern recording_id
```

와

```text
legacy_<different stem>_<same raw SHA prefix>
```

로 이중 식별될 수 있다.

현재 구현은:

```text
same recording_id
+ different raw bytes
→ reject
```

는 수행하지만,

```text
same raw bytes
+ different recording_id
```

를 repository-wide identity conflict로 막지 않는다.

---

## GAP-2 — Summary가 recording/run 경계를 넘어 병합될 수 있음

현재 summary grouping은:

```text
(subject, round, step)
```

을 사용한다.

canonical frames에는 이미:

```text
recording_id
analysis_run_id
```

가 존재하므로 동일 subject/round/step의 서로 다른 take가 한 summary aggregate에 섞일 수 있다.

Synthetic probe에서 실제 병합이 재현됐다.

---

## GAP-3 — Summary reference가 다른 recording에서 올 수 있음

현재 upright reference 검색도 subject/round/step 수준에서 이루어진다.

따라서 여러 take가 한 batch에 존재하면 reference lineage가 recording boundary를 넘을 수 있다.

---

## GAP-4 — RF가 mutable flat frames를 직접 discovery함

현재 `rf_experiment.py`는:

```text
analysis/<subject>_r*_frames.csv
```

형태의 flat compatibility output을 직접 glob한다.

flat path는 후속 analysis run이 재publish할 수 있으므로 immutable input identity가 아니다.

---

## GAP-5 — RF sample에서 recording/run lineage가 사라짐

현재 RF meta는 실질적으로:

```text
(subject, round, step, label)
```

이다.

따라서 서로 다른 recording/run이 같은 research position을 가지면 RF sample identity가 충돌한다.

---

## GAP-6 — RF relative reference가 recording boundary를 넘을 수 있음

현재 RF relative grouping key는 subject/round 수준이다.

같은 subject/round의 복수 recording을 함께 읽으면 다른 recording의 first upright가 reference가 될 수 있음이 synthetic probe로 확인됐다.

---

## GAP-7 — RF experiment/result가 immutable provenance run이 아님

현재 결과:

```text
analysis/rf_results.csv
analysis/rf_results.txt
analysis/fig5_rf_compare.png
```

는 후속 실행에서 덮어쓸 수 있다.

현재 결과만으로는 exact frames bytes, exact analysis run, RF code/config를 복구할 수 없다.

---

# 5. Frozen Core Invariants

## INV-1 — Raw content identity must not silently fork

```text
known raw SHA-256
+ same recording_id
→ allowed

known raw SHA-256
+ different recording_id
→ hard error
```

동일 raw content에 새로운 independent recording identity를 자동 발급하지 않는다.

---

## INV-2 — Summary must not cross recording lineage

서로 다른 `recording_id`는 하나의 summary aggregate로 병합할 수 없다.

---

## INV-3 — Summary must preserve source analysis lineage

summary row는:

```text
이 summary를 만든 current analysis run
```

과

```text
source canonical frames의 analysis run
```

을 구분한다.

---

## INV-4 — Ambiguous analysis-run selection fails closed

동일 recording에서 둘 이상의 candidate analysis run이 downstream 입력 후보가 되면 자동으로 latest/first를 선택하지 않는다.

명시적 selection contract가 없으면 실패한다.

---

## INV-5 — RF input must be content-pinned

RF가 사용하는 canonical frames는 최소:

```text
recording_id
analysis_run_id
frames SHA-256
```

로 고정되어야 한다.

mutable path만으로는 RF input identity를 인정하지 않는다.

---

## INV-6 — RF sample lineage must survive process exit

각 RF sample은 persistent artifact를 통해 source recording/run/frames까지 역추적 가능해야 한다.

---

## INV-7 — RF experiment is an immutable run

RF 실행 1회는 고유 `experiment_run_id`를 가진 immutable run이다.

완료된 run의 provenance와 outputs를 후속 실행이 덮어쓰지 않는다.

---

# 6. DF-1 — Raw SHA Identity Authority

**Status: FROZEN**

## 6.1 Patch 5 authority universe

Patch 5에서 raw SHA ↔ recording identity의 repository authority는 다음 per-run manifest 집합이다.

```text
analysis/*/ar_*/analysis_manifest.json
```

다음은 제외한다.

```text
analysis/batches/*
flat frames provenance sidecar
filename-only evidence
directory name alone
raw file path alone
```

manifest가 다음 조건을 만족하면 raw identity evidence로 사용한다.

```text
analysis_mode == "extract_raw"
recording_id is non-empty
inputs.recording.sha256 is a valid 64-hex SHA-256
```

`status`가:

```text
running
completed
failed
```

중 무엇이더라도 위 identity evidence가 이미 manifest에 기록되어 있으면 raw identity collision check에 포함한다.

이유:

```text
analysis 성공 여부
!=
recording identity가 이미 발급·검증되었는지 여부
```

---

## 6.2 Collision index rule

Patch 5 raw extraction 시작 시 repository manifest들을 읽어:

```text
raw_sha256
→ set(recording_id)
```

index를 만든다.

이미 하나의 raw SHA에 둘 이상의 recording ID가 존재하면:

```text
repository raw identity conflict
```

로 hard error 처리한다.

현재 input의 raw SHA가 기존 index에 존재하면:

```text
existing set == {current recording_id}
→ allow

current recording_id not in existing set
→ hard error
```

---

## 6.3 Check timing

collision check는 다음 이후에 수행한다.

```text
current raw SHA 계산
current proposed recording_id 검증/결정
```

하지만 다음 이전에 수행한다.

```text
새 analysis_run_id directory 생성
새 running manifest 기록
MediaPipe inference
```

즉 identity conflict가 새로운 run artifact를 만들기 전에 실패해야 한다.

---

## 6.4 Out of scope for DF-1

Patch 5는 다음을 만들지 않는다.

```text
manifests/recordings.jsonl
global raw catalog
automatic legacy alias crosswalk
directory-wide raw byte scanner
```

이들은 Patch 6/7의 registry/selection/integrity 역할과 충돌할 수 있다.

---

# 7. Summary Schema — `summary-schema/1.0.0`

**Status: FROZEN**

Patch 5에서 `summary_steps.csv`의 canonical schema를 다음과 같이 freeze한다.

## 7.1 Exact field count

```text
existing summary fields = 44
new lineage fields      = 8
--------------------------------
total                   = 52
```

기존 44-field prefix의 이름과 순서를 유지하고 lineage 8 fields를 뒤에 append한다.

---

## 7.2 Exact ordered header

```text
subject
round
step
label
n_frames
face_detect_ratio
pose_detect_ratio

face_area_px
face_area_px_sd
face_w_px
face_w_px_sd
face_x
face_x_sd
face_y
face_y_sd
theta1_deg
theta1_deg_sd
theta2_deg
theta2_deg_sd
theta3_deg
theta3_deg_sd
z_face_m
z_face_m_sd
z_sh_m
z_sh_m_sd
face_size_cm2
face_size_cm2_sd
oval_area_px
oval_area_px_sd
oval_size_cm2
oval_size_cm2_sd
ipd_cm
ipd_cm_sd
box_to_oval
box_to_oval_sd

ref_step
A_ratio
A_ratio_oval
dZ_face_cm
dZ_sh_cm
D_head_cm
sh_face_ratio
area_err_est_pct
area_cv_pct

summary_schema_version
recording_id
analysis_run_id
source_frames_analysis_run_id
dataset_role
protocol_version
reference_recording_id
reference_analysis_run_id
```

`summary_schema_version`의 exact value:

```text
summary-schema/1.0.0
```

---

## 7.3 Grouping key

canonical frame input grouping key:

```text
(recording_id, frame.analysis_run_id, step)
```

다음만으로 grouping하지 않는다.

```text
(subject, round, step)
```

한 group 내부에서 다음이 충돌하면 schema/provenance error다.

```text
subject
round
label
recording_id
frame analysis_run_id
dataset_role
protocol_version
```

충돌을 평균/median으로 해결하지 않는다.

---

## 7.4 Summary run identity semantics

### Raw extraction

```text
analysis_run_id
= current analysis run
= source_frames_analysis_run_id
```

### `--from-csv`

```text
analysis_run_id
= current re-summary analysis run

source_frames_analysis_run_id
= input canonical frames가 원래 속한 analysis run
```

원본 canonical frames row의 `analysis_run_id`를 변경하지 않는다.

---

## 7.5 Summary primary identity

한 summary row의 logical primary key:

```text
(analysis_run_id, recording_id, step)
```

한 summary operation 안에서 같은 `recording_id`에 서로 다른 `source_frames_analysis_run_id`가 동시에 존재하면 hard error다.

---

## 7.6 Reference isolation

upright reference 검색은 반드시:

```text
same recording_id
same source_frames_analysis_run_id
```

안에서만 수행한다.

기존 summary reference 시간 규칙:

```text
바로 앞 upright
```

은 변경하지 않는다.

Patch 5는 이를 RF의 first-upright policy로 통일하지 않는다.

---

## 7.7 Reference lineage fields

reference가 존재하면:

```text
reference_recording_id
reference_analysis_run_id
```

는 실제 reference row의 source frame lineage를 기록한다.

reference가 존재하지 않으면 CSV empty field로 기록한다.

---

# 8. DF-2 — Exact RF Input Declaration

**Status: FROZEN**

## 8.1 No standalone Patch-5 dataset-selection manifest

Patch 5는 별도의 selection ledger 또는 dataset selection manifest를 만들지 않는다.

Patch 6의 책임:

```text
어떤 recording을 왜 include/exclude 했는가
retake 중 무엇을 선택했는가
selection history
```

Patch 5의 책임:

```text
실제로 이번 RF run이 어떤 exact bytes를 사용했는가
```

따라서 Patch 5의 exact RF input declaration은:

```text
results/<experiment_run_id>/experiment_manifest.json
```

의 `inputs` block에 기록한다.

별도 `rf_input_manifest.json`은 Patch 5에서 만들지 않는다.

---

## 8.2 Canonical lineage-safe RF input mode

Patch 5는 explicit immutable frames 입력을 위한 CLI를 추가한다.

```text
--ours-frames PATH [PATH ...]
```

`--ours-frames`와 기존:

```text
--ours SUBJECT [SUBJECT ...]
```

는 mutually exclusive다.

`--ours-frames` PATH는 다음 canonical run archive frames여야 한다.

```text
analysis/<recording_id>/<analysis_run_id>/<recording>_frames.csv
```

각 frames path는 다음을 검증해야 한다.

```text
frames-schema/1.0.0 exact 60-field header
single recording_id
single analysis_run_id
owner analysis_manifest.json 존재
owner manifest status == completed
owner manifest recording_id == frames recording_id
owner manifest analysis_run_id == frames analysis_run_id
owner manifest outputs에 해당 frames artifact 존재
owner manifest output SHA-256 == actual frames SHA-256
```

flat compatibility path를 `--ours-frames` canonical input으로 인정하지 않는다.

---

## 8.3 Existing `--ours` compatibility mode

기존:

```text
--ours P01 P02 ...
```

는 pilot/backward-compatibility mode로 유지한다.

그러나 discovery한 flat frames마다:

```text
<frames>.provenance.json
```

을 검증하여 immutable owner run으로 resolve해야 한다.

다음을 모두 검증한다.

```text
flat frames actual SHA == sidecar frames_sha256

sidecar analysis_manifest path exists

actual analysis_manifest SHA
== sidecar analysis_manifest_sha256

manifest status == completed

manifest recording_id
== sidecar recording_id
== canonical frames recording_id

manifest analysis_run_id
== sidecar analysis_run_id
== canonical frames analysis_run_id

manifest output archive frames SHA
== flat frames SHA
```

RF가 실제 provenance authority로 기록하는 path는 flat path가 아니라 resolved immutable run archive frames path다.

---

## 8.4 `--ours` ambiguity rejection

기존 subject-based mode가 다음 중 하나를 만나면 hard error다.

### Multiple completed analysis runs for one recording

```text
same recording_id
+ more than one completed frames-producing analysis run
```

이면 subject-only CLI가 어느 run을 사용할지 자동 결정하지 않는다.

사용자는 exact `--ours-frames` path를 지정해야 한다.

### Multiple recordings for same subject/round

```text
same subject
same round
+ different recording_id
```

가 입력 후보에 둘 이상 존재하면 자동 선택/병합하지 않는다.

사용자는 exact `--ours-frames` path를 지정해야 한다.

---

## 8.5 Explicit input conflict rejection

`--ours-frames`에서도 다음은 금지한다.

```text
same recording_id
+ different analysis_run_id
→ reject

same subject + same round
+ different recording_id
→ reject
```

Patch 5는 둘 중 어느 source가 연구적으로 더 좋은지 결정하지 않는다.

---

## 8.6 Frozen `inputs.ours` fields

`experiment_manifest.json`의 `inputs.ours`는 actual model input order를 만들기 전에 검증된 immutable source 목록이다.

각 entry exact required fields:

```text
recording_id
analysis_run_id
subject
round
frames_schema_version
frames_path
frames_sha256
analysis_manifest_path
analysis_manifest_sha256
```

`frames_schema_version`:

```text
frames-schema/1.0.0
```

`frames_path`와 `analysis_manifest_path`는 resolved absolute paths를 기록한다.

hash는 exact on-disk bytes의 SHA-256이다.

---

# 9. DF-3 — RF Sample Lineage Artifact

**Status: FROZEN**

## 9.1 Canonical file

각 RF experiment run은 다음 file을 가진다.

```text
results/<experiment_run_id>/sample_lineage.jsonl
```

schema:

```text
rf-sample-lineage/1.0.0
```

---

## 9.2 Row correspondence

한 JSONL object는:

```text
특정 dataset track
+ 특정 feature_mode
+ 특정 model sample_index
```

에 대응한다.

logical key:

```text
(experiment_run_id, dataset_track, feature_mode, sample_index)
```

`sample_index`는 해당 dataset track의 in-memory X/y sample order와 동일한 **0-based index**다.

feature transform은 sample order를 바꾸지 않는다.

---

## 9.3 Exact top-level fields

각 JSONL row는 다음 exact top-level fields를 가진다.

```text
schema_version
experiment_run_id
dataset_track
feature_mode
sample_index
source_kind
subject
round
step
label
recording_id
analysis_run_id
frames_path
frames_sha256
source_dataset_id
source_file_path
source_file_sha256
source_row_number
calibration_reference_step
relative_reference_step
reference_recording_id
reference_analysis_run_id
```

---

## 9.4 `source_kind`

허용 enum:

```text
canonical_frames
external_table
```

### `canonical_frames`

우리 D455 canonical frames에서 만들어진 RF sample.

필수 non-null:

```text
recording_id
analysis_run_id
frames_path
frames_sha256
subject
round
step
label
```

다음은 null:

```text
source_dataset_id
source_file_path
source_file_sha256
source_row_number
```

### `external_table`

paper `Dataset.xlsx` 또는 MultiPosture 등 recording identity가 없는 외부 표 데이터.

필수 non-null:

```text
source_dataset_id
source_file_path
source_file_sha256
source_row_number
```

다음은 null:

```text
recording_id
analysis_run_id
frames_path
frames_sha256
```

외부 표 데이터에 가짜 `recording_id`를 만들지 않는다.

---

## 9.5 `source_dataset_id`

현재 loader의 exact values:

```text
paper_dataset
multiposture_dataset
```

dataset semantic role을 나타내며 exact byte version은 반드시 `source_file_sha256`으로 구분한다.

---

## 9.6 External row numbering

`source_row_number`는 source table의 **1-based physical row number**다.

예:

```text
Excel:
header row = 1
first data row = 2

CSV:
header row = 1
first data row = 2
```

stride/drop 후 sample index가 달라져도 original source row number를 기록한다.

---

## 9.7 Dataset track enum

현재 RF code의 frozen track names:

```text
paper_loso
ours_external
multiposture_loso
```

---

## 9.8 Feature mode

현재 허용 feature mode:

```text
all
invariant
relative
```

MultiPosture current path는:

```text
all
```

만 사용한다.

Patch 5는 feature formula를 변경하지 않는다.

---

## 9.9 Reference lineage for our canonical frames

현재 `load_ours()`가 얼굴 면적 A를 만들기 위해 사용하는 first-upright calibration step을:

```text
calibration_reference_step
```

에 기록한다.

`feature_mode == relative`이면 `transform()`에서 실제 사용하는 first-upright step을:

```text
relative_reference_step
```

에 기록한다.

현재 RF semantics를 변경하지 않는다.

reference가 우리 canonical frame sample에 존재하는 경우:

```text
reference_recording_id
reference_analysis_run_id
```

는 source sample과 같은 recording/run이어야 한다.

cross-recording reference는 hard error다.

`relative`가 아닌 mode에서 `relative_reference_step`은 null이다.

---

## 9.10 External-table reference handling

외부 표 데이터는 Patch 5의 recording lineage 대상이 아니다.

외부 input의 exact reproducibility는:

```text
source_dataset_id
source file SHA-256
source physical row number
RF code SHA-256
options
```

로 보존한다.

외부 데이터에 recording/reference recording identity를 임의 생성하지 않는다.

---

## 9.11 JSONL canonical serialization

`sample_lineage.jsonl`은:

```text
encoding = UTF-8
BOM      = none
newline  = LF
```

각 line object는 다음 canonical JSON serialization을 사용한다.

```python
json.dumps(
    row,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

각 object 뒤에는 정확히 하나의 `\n`을 기록한다.

`lineage_manifest_sha256`은 이 exact file bytes 전체의 SHA-256이다.

---

# 10. DF-4 — Immutable RF Experiment Run

**Status: FROZEN**

## 10.1 Experiment run ID

exact format:

```text
er_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>
```

example:

```text
er_20261004T091530123456Z_0123456789abcdef0123456789abcdef
```

timezone은 UTC다.

---

## 10.2 Canonical result directory

```text
results/
└── <experiment_run_id>/
    ├── experiment_manifest.json
    ├── sample_lineage.jsonl
    ├── rf_results.csv
    ├── rf_results.txt
    └── fig5_rf_compare.png
```

run directory는 exclusive create한다.

```text
exist_ok = false
```

동일 experiment_run_id directory를 재사용하지 않는다.

---

## 10.3 Experiment manifest schema

```text
rf-experiment-provenance/1.0.0
```

exact top-level fields:

```text
schema_version
experiment_run_id
started_at
ended_at
status
dataset_manifest
inputs
code
environment
options
sample_lineage
outputs
errors
provenance_unknown_reasons
```

---

## 10.4 Status lifecycle

허용 status:

```text
running
completed
failed
```

run directory를 만든 뒤 가능한 빨리 `running` manifest를 기록한다.

성공한 모든 required output이 기록되고 hash된 뒤에만:

```text
status = completed
```

로 finalize한다.

오류가 발생하면 가능한 범위에서:

```text
status = failed
errors = [...]
```

를 기록한다.

completed manifest와 completed run outputs는 이후 수정하지 않는다.

---

## 10.5 `dataset_manifest`

Patch 5에서 exact structure:

```json
{
  "dataset_manifest_id": null,
  "path": null,
  "sha256": null
}
```

Patch 5 current/pilot execution에서는 세 값 모두 null이다.

Patch 6에서 formal dataset manifest가 구현되면 이 동일 slot을 사용한다.

Patch 5는 Patch 6 selection artifact를 생성하지 않는다.

---

## 10.6 `inputs`

exact structure:

```text
inputs.paper
inputs.multiposture
inputs.ours
```

### `inputs.paper`

required when current RF run loads `--paper`.

fields:

```text
source_dataset_id = paper_dataset
path
sha256
size_bytes
```

### `inputs.multiposture`

null if not used.

사용 시:

```text
source_dataset_id = multiposture_dataset
path
sha256
size_bytes
```

### `inputs.ours`

ordered list of the exact entries defined in DF-2 §8.6.

---

## 10.7 RF code provenance

`code` exact fields:

```text
git_commit
git_dirty
rf_script_sha256
path
```

`rf_script_sha256`는 actual `rf_experiment.py` bytes의 SHA-256이다.

Git unavailable은 provenance unknown으로 기록할 수 있으나 script SHA-256은 RF run의 critical code identity다.

---

## 10.8 Environment provenance

`environment`에는 최소 다음 exact keys를 기록한다.

```text
python
os
architecture
numpy
matplotlib
openpyxl
```

설치되지 않아 사용하지 않은 package는 null + provenance reason을 허용한다.

실제 실행에 필요한 package가 없어 실행 자체가 불가능한 경우 기존 runtime error를 숨기지 않는다.

---

## 10.9 Options provenance

`options` exact keys:

```text
argv
paper
multiposture
ours
ours_frames
trees
seeds
stride
lams
skip_paper_loso
features
```

`argv`는 실제 CLI argument list를 기록한다.

Patch 5는 이 option들의 scientific semantics를 변경하지 않는다.

---

## 10.10 Sample lineage descriptor

`sample_lineage` exact fields:

```text
schema_version
path
sha256
row_count
```

values:

```text
schema_version = rf-sample-lineage/1.0.0
path           = sample_lineage.jsonl
```

`path`는 experiment run directory 기준 relative path다.

---

## 10.11 Outputs

`outputs`는 최소 다음 artifacts를 기록한다.

```text
rf_results.csv
rf_results.txt
fig5_rf_compare.png
```

각 output entry는 최소:

```text
kind
path
size_bytes
sha256
```

를 가진다.

`path`는 resolved absolute path를 기록한다.

plot 생성이 기존 코드상 optional failure로 허용되는 경우:

```text
fig5_rf_compare.png
```

가 없을 수 있으며 해당 실패는 manifest error/provenance에 기록한다.

Patch 5는 plot failure를 새 scientific acceptance criterion으로 바꾸지 않는다.

---

## 10.12 Result CSV lineage fields

기존 RF result CSV fields는 유지하고 다음 exact fields를 추가한다.

```text
experiment_run_id
dataset_manifest_sha256
lineage_manifest_path
lineage_manifest_sha256
```

semantics:

```text
experiment_run_id
= current experiment run

dataset_manifest_sha256
= Patch 5 current/pilot에서는 CSV empty field
= Patch 6 formal dataset manifest 사용 시 exact manifest bytes SHA-256

lineage_manifest_path
= sample_lineage.jsonl

lineage_manifest_sha256
= exact sample_lineage.jsonl bytes SHA-256
```

모든 result row는 동일 experiment run에서 동일한 lineage manifest path/hash를 가진다.

기존 `root_provenance` field는 유지한다.

---

## 10.13 Hash cycle prohibition

다음 구조로 circular hashing을 만들지 않는다.

```text
sample_lineage.jsonl
→ 먼저 finalize + hash

rf_results.csv
→ lineage hash를 기록
→ finalize + hash

experiment_manifest.json
→ result hashes를 기록
→ 마지막 finalize
```

`experiment_manifest.json` 자신의 SHA-256을 자기 내부에 기록하지 않는다.

외부 integrity checker가 필요하면 Patch 7에서 manifest 자체의 hash를 별도 authority로 관리할 수 있다.

---

## 10.14 Flat compatibility publication

기존 소비자를 위해 성공한 run의:

```text
rf_results.csv
rf_results.txt
fig5_rf_compare.png
```

를 `analysis/` flat compatibility path로 copy할 수 있다.

그러나 provenance authority는 항상:

```text
results/<experiment_run_id>/
```

이다.

flat copy는 RF input/output identity authority가 아니다.

failed run은 flat compatibility result를 publish하지 않는다.

---

# 11. DF-5 — Patch 6 Selection Interface Boundary

**Status: FROZEN**

Patch 5와 Patch 6의 책임을 다음처럼 분리한다.

## Patch 5

```text
what exact bytes were actually used?
which recording/run did each sample come from?
which exact run produced this result?
```

## Patch 6

```text
which recording/run should be selected?
why was it included/excluded?
which retake replaced which attempt?
who/what policy approved the selection?
```

---

## 11.1 Patch 5 must not create Patch 6 ledgers

Patch 5에서 생성 금지:

```text
manifests/recordings.jsonl
manifests/selection_events.jsonl
manifests/datasets/<dataset_manifest_id>.json
```

이들은 Patch 6에서 별도 Design Freeze 후 구현한다.

---

## 11.2 Forward-compatible slot

Patch 5 `experiment_manifest.json`은 다음 slot만 미리 freeze한다.

```text
dataset_manifest.dataset_manifest_id
dataset_manifest.path
dataset_manifest.sha256
```

Patch 5에서는 모두 null이다.

---

## 11.3 Patch 6 integration rule

향후 Patch 6 formal dataset manifest가 존재하면:

```text
dataset manifest
= selection authority
```

가 된다.

RF experiment는 Patch 6 manifest를 검증하고 선택된 recording/run을 exact canonical frames로 resolve한다.

그 후에도 Patch 5 experiment manifest의:

```text
inputs.ours
```

에는 실제 resolved frames path/hash/run identity를 다시 기록한다.

즉 future chain은:

```text
dataset selection manifest
→ resolved exact frames
→ experiment_manifest.inputs
→ sample_lineage
→ result
```

이다.

Patch 6 manifest만 가리키고 actual resolved frames identity를 생략하지 않는다.

---

## 11.4 No mixed selection authority

향후 formal dataset manifest가 사용되는 실행에서는:

```text
formal dataset manifest selection
+
manual --ours / --ours-frames additions
```

을 조용히 병합하지 않는다.

한 formal run에는 하나의 selection authority를 사용한다.

구체적인 Patch 6 CLI는 Patch 6 Design Freeze에서 결정한다.

Patch 5는 future CLI 이름을 선점하지 않는다.

---

# 12. Hashing Rules

**Status: FROZEN**

artifact content hash:

```text
algorithm = SHA-256
scope     = exact on-disk file bytes
```

다음을 content identity로 사용하지 않는다.

```text
mtime
file size only
filename
path
Git blob assumption
```

대용량 file은 streaming hash한다.

hash 중 file size/mtime이 바뀌면 current Patch 3 원칙처럼:

```text
file changed while hashing
```

으로 실패 처리한다.

---

# 13. Resolved Design-Freeze Decisions

이전 DRAFT의 DF-1~DF-5 open question은 모두 해소됐다.

| DF | Frozen decision |
|---|---|
| DF-1 | raw SHA authority는 `analysis/*/ar_*/analysis_manifest.json`의 raw-extraction identity evidence. 동일 SHA→다른 recording ID는 pre-run hard error |
| DF-2 | 별도 selection manifest를 만들지 않고 `experiment_manifest.inputs`가 actual RF input declaration. canonical explicit input은 `--ours-frames` immutable run archive path |
| DF-3 | `results/<er>/sample_lineage.jsonl`, `rf-sample-lineage/1.0.0`, canonical JSONL, exact sample→source lineage |
| DF-4 | `results/<er>/experiment_manifest.json`, `rf-experiment-provenance/1.0.0`, `er_<UTC>_<uuid>`, immutable result directory |
| DF-5 | Patch 6 selection artifacts는 만들지 않음. `dataset_manifest` nullable slot만 freeze하고 formal selection authority는 Patch 6로 넘김 |

따라서 Patch 5에는 **구현 전 추가 schema/identity open question이 없다.**

구현 중 현재 repository 사실과 충돌하는 BLOCKER가 발견되면 임의 변경하지 않고 새 Decision Log entry 또는 Design Freeze revision을 먼저 수행한다.

---

# 14. Explicit Rejected Behaviors

다음은 Patch 5 contract 위반이다.

```text
same raw bytes
→ different independent recording identity
```

```text
different recording_id
→ same summary aggregate
```

```text
different source analysis_run_id
→ silently collapsed summary
```

```text
sample from recording A
→ reference from recording B
```

```text
same recording
+ multiple candidate analysis runs
→ latest/first automatic selection
```

```text
RF exact input
= mutable flat path only
```

```text
RF sample identity
= subject/round/step only
```

```text
new RF run
→ overwrite previous canonical result run
```

```text
Patch 5
→ retake selection policy 결정
```

---

# 15. Backward Compatibility

## 15.1 Canonical frames

유지:

```text
frames-schema/1.0.0
exact 60 fields
frame_index 1-based
```

Patch 5 때문에 60-field frame schema에 새 field를 추가하지 않는다.

---

## 15.2 Historical `--from-csv`

유지:

```text
historical parent provenance
current model provisioning not required
```

Patch 4.5 semantics를 변경하지 않는다.

---

## 15.3 Existing RF numeric behavior

Patch 5는 다음을 변경하지 않는다.

```text
Tree implementation
Forest implementation
M0/M1/M2
PAPER_RANK_W
λ behavior
seed meaning
LOSO subject grouping
existing feature calculation
existing class mapping
existing evaluation masks
current first-upright RF reference rule
```

lineage-safe isolation 때문에 ambiguous multi-take input이 기존처럼 조용히 계산되지 않고 error가 될 수 있다.

이는 의도된 behavior change다.

---

## 15.4 LOSO grouping

`recording_id`를 새로운 participant로 취급하지 않는다.

LOSO group 단위는 계속 subject다.

---

# 16. Non-Goals

Patch 5에서 결정/구현하지 않는다.

```text
F1 exact formula
F1 feature count
F1 normalization
F1 missing policy

F2 exact formula
F2 feature count
F2 sagittal geometry
F2 trunk-axis definition
F2 depth-derived geometry
F2 missing-depth policy

p > 6 rank_weights exact policy

formal participant count
formal round count
formal inclusion/exclusion policy
retake scientific selection policy
exact seed list
exact λ selection rule
formal metric set

Patch 8 distance grid
Patch 8 repeat count
Patch 8 hardware acceptance criteria
```

---

# 17. `_samples.csv` Boundary

Capture `_samples.csv`는 current canonical frames/RF computational parent가 아니다.

Patch 5에서는 mandatory end-to-end computational lineage에 승격하지 않는다.

다음은 Patch 7 general integrity scope로 남길 수 있다.

```text
all companion artifact inventory
orphan detection
missing artifact detection
repository-wide hash audit
```

---

# 18. Acceptance Criteria

## AC-1 — Raw identity conflict

byte-identical raw가 기존 recording ID와 다른 proposed recording ID를 가지면 새 run directory를 만들기 전에 실패한다.

---

## AC-2 — Same raw / same identity

동일 raw SHA와 동일 recording ID는 기존 valid path에서 허용한다.

---

## AC-3 — Existing repository conflict

기존 manifests 자체가:

```text
same raw SHA
→ multiple recording IDs
```

를 포함하면 임의 canonical ID를 고르지 않고 실패한다.

---

## AC-4 — Summary exact schema

새 canonical summary header는 exact 52 fields이며:

```text
summary_schema_version
= summary-schema/1.0.0
```

이다.

---

## AC-5 — No cross-recording summary merge

같은 subject/round/step이어도 recording ID가 다르면 같은 summary row로 병합하지 않는다.

---

## AC-6 — No cross-run summary collapse

동일 recording의 서로 다른 source frame runs가 한 summary operation에 들어오면 실패한다.

---

## AC-7 — Summary reference isolation

reference recording/run은 current summary row의 source recording/run과 같아야 한다.

---

## AC-8 — `--from-csv` dual run identity

re-summary에서:

```text
analysis_run_id
!= source_frames_analysis_run_id
```

가 정상적으로 표현되고 parent frame identity가 유지된다.

---

## AC-9 — `--ours-frames` immutable validation

owner manifest/path/hash/run identity가 모두 검증되지 않은 frames path는 거부한다.

---

## AC-10 — Subject compatibility ambiguity

기존 `--ours SUBJECT...`에서 multiple runs 또는 same subject/round retakes가 존재하면 자동 선택하지 않고 실패한다.

---

## AC-11 — RF sample lineage

모든 실제 RF input sample은 `sample_lineage.jsonl`에서 exact source를 찾을 수 있다.

---

## AC-12 — Cross-recording RF reference rejection

same subject/round의 다른 recording을 reference로 사용하는 경로가 존재하지 않아야 한다.

---

## AC-13 — External table provenance

paper/MultiPosture sample에는 fake recording ID 대신:

```text
source_dataset_id
source file hash
physical source row
```

가 기록된다.

---

## AC-14 — Experiment immutability

서로 다른 RF 실행은 서로 다른 `experiment_run_id` 및 result directory를 사용한다.

이전 completed run을 덮어쓰지 않는다.

---

## AC-15 — Result linkage

모든 RF result CSV row는:

```text
experiment_run_id
lineage_manifest_path
lineage_manifest_sha256
```

를 가진다.

Patch 5 pilot에서는:

```text
dataset_manifest_sha256
```

가 empty다.

---

## AC-16 — Lineage tamper detection

`sample_lineage.jsonl` bytes가 변경되면 stored SHA-256과 불일치해야 한다.

---

## AC-17 — Frames tamper detection

experiment input declaration 이후 frames bytes가 바뀌면 stored frames SHA-256 검증이 실패해야 한다.

---

## AC-18 — Result integrity

experiment manifest의 completed output hash와 실제 result bytes가 다르면 검증 가능해야 한다.

---

## AC-19 — Existing Foundation regression

기존:

```text
204 tests
```

가 계속 PASS해야 한다.

---

## AC-20 — Patch 4/4.5 regression

다음 exact contracts가 유지된다.

```text
frames-schema/1.0.0
mediapipe-model-lock/1.0.0
historical --from-csv provenance behavior
```

---

# 19. Minimum New Test Matrix

최소 다음 targeted tests를 추가한다.

```text
1. same raw bytes / modern ID + legacy alias ID
   → hard reject

2. same raw SHA / same recording ID
   → allow

3. pre-existing SHA→multiple-ID manifest conflict
   → hard reject

4. summary exact 52-field header/order

5. two recordings / same subject-round-step
   → never one aggregate

6. one recording / two source frame runs in one summary operation
   → reject

7. summary reference cannot cross recording/run

8. --from-csv:
   current summary run ID vs source frame run ID preserved

9. --ours-frames:
   exact archive frames + completed owner manifest + SHA
   → accept

10. --ours-frames:
    flat compatibility path
    → reject

11. --ours subject compatibility:
    one unambiguous run
    → resolve to archive and accept

12. --ours subject compatibility:
    multiple completed runs for one recording
    → reject

13. same subject/round different recordings
    → reject before RF reference construction

14. RF sample lineage row count/order matches actual model samples

15. canonical-frames RF sample traces to recording/run/hash

16. relative reference remains same recording/run

17. external paper row stores file hash + physical row

18. MultiPosture stride sample stores original physical row

19. sample_lineage canonical serialization/hash deterministic

20. second RF execution creates a different er_* directory

21. completed RF run cannot be silently overwritten

22. rf_results.csv carries frozen four lineage columns

23. modified frames after pinning
    → hash failure

24. modified sample_lineage after creation
    → hash failure

25. existing 204-test baseline remains green
```

Synthetic data는 lineage/schema verification용이며 연구 성능 근거로 사용하지 않는다.

---

# 20. Implementation Map

Design Freeze 이후 구현자는 최소 변경 원칙을 따른다.

## `analyze_d455.py`

필요 범위:

```text
raw SHA→recording ID conflict check
summary-schema/1.0.0 exact writer
recording/run-aware summary grouping
reference isolation
raw vs --from-csv current/source run mapping
```

금지:

```text
frame schema 변경
F1/F2 구현
summary 통계 공식 변경
MediaPipe inference semantics 변경
```

---

## `rf_experiment.py`

필요 범위:

```text
experiment_run_id
results/<er_*> canonical run directory
--ours-frames
legacy --ours safe resolver
input artifact hashing/verification
sample_lineage.jsonl
experiment_manifest.json
result lineage columns
successful flat compatibility publish
```

금지:

```text
Tree/Forest algorithm 변경
feature formula 변경
weight policy 변경
λ policy 변경
seed semantics 변경
LOSO semantics 변경
metric semantics 변경
```

---

## Tests

기존 test를 가능한 범위에서 유지하고 Patch 5 전용 provenance/lineage tests를 추가한다.

test filename은 구현자가 repository convention에 맞춰 정할 수 있다.

test filename 자체는 research contract가 아니다.

---

# 21. Independent Audit Requirements

implementation + tests 이후 별도 Claude Code / Opus READ-ONLY audit은 최소 다음을 확인한다.

```text
raw SHA duplicate identity fail-closed 여부
summary exact 52-field contract
raw vs re-summary run identity semantics
cross-recording summary/reference 차단
RF explicit immutable input validation
legacy --ours ambiguity handling
sample_lineage row↔model sample alignment
external row identity
RF reference recording isolation
experiment run immutability
result→lineage→frames→analysis→recording 역추적
Patch 4 regression
Patch 4.5 regression
204 baseline + new tests
```

audit 이후 수정 기준:

```text
BLOCKER
IMPORTANT
```

를 우선한다.

MINOR는 Foundation closure를 막는 실제 contract violation인지 별도 판단한다.

---

# 22. Definition of Done

Patch 5 Foundation closure 기준은 다음과 같이 충족됐다.

```text
[x] READ-ONLY repository investigation

[x] confirmed gaps identified

[x] exact contract decided

[x] Design Freeze document created

[x] PROV-005 Decision Log contract prepared

[x] docs-only Design Freeze commit created
    → d4dc23f

[x] implementation started only after Design Freeze commit

[x] implementation completed
    → dd0464e

[x] full tests PASS
    → 252 PASS

[x] new Patch 5 targeted tests PASS
    → 48 PASS

[x] independent READ-ONLY audit completed
    → PASS WITH MINOR FINDINGS

[x] BLOCKER = 0

[x] IMPORTANT = 0

[x] implementation commit created
    → dd0464e

[x] Foundation Record / documentation closure completed
    → this documentation-closure change
```

`MINOR = 6`은 아래 closure disposition에 따라 Patch 5 contract blocker가 아닌 것으로 수용한다.
Patch 5 main integration은 Foundation documentation closure 이후 별도 Git 단계이며, 위 software closure 조건과 구분한다.

---

# 23. Active Freeze Statement

**This statement is ACTIVE for Patch 5 Design Freeze.**

> Patch 5 establishes end-to-end artifact lineage from raw recording content through RF experiment results. A known raw content hash may not silently acquire a second independent recording identity. Canonical summaries use `summary-schema/1.0.0` with exact recording/source-run boundaries and may not aggregate or reference across those boundaries. RF execution must resolve inputs to immutable canonical frame artifacts identified by recording ID, analysis run ID, and exact SHA-256. Every RF sample is persisted in `rf-sample-lineage/1.0.0`, and every RF execution is stored as an immutable `rf-experiment-provenance/1.0.0` run under `results/<experiment_run_id>/`. Ambiguous recording/run selection fails closed. Patch 5 records what exact data was used but does not decide which retake or analysis run is scientifically preferred; that selection authority remains Patch 6.

---

# 24. Implementation and Verification Closure

## 24.1 Implementation commit

```text
dd0464e
feat: implement Patch 5 end-to-end lineage hardening
```

구현 대상:

```text
analyze_d455.py
rf_experiment.py
test_analysis_provenance.py
test_external_metrics.py
test_relative_eval.py
test_root_logging.py
patch5_test_fixtures.py
test_patch5_lineage.py
```

Design Freeze 문서와 Patch 4 / 4.5 frozen contracts는 implementation commit에서 변경하지 않았다.

---

## 24.2 Implemented contract mapping

### DF-1 — Raw SHA Identity Authority

구현 완료:

```text
analysis/*/ar_*/analysis_manifest.json
→ extract_raw identity evidence
→ raw SHA-256 ↔ recording_id conflict detection
→ conflicting identity는 새 analysis run 생성 전에 fail closed
```

`running / completed / failed` manifest의 valid identity evidence를 모두 포함한다.

### Summary lineage

구현 완료:

```text
summary-schema/1.0.0
exact 52 fields
```

기존 44-field ordered prefix를 유지하고 frozen 8 lineage fields를 append한다.

summary aggregation과 reference는:

```text
same recording_id
same source frames analysis run
```

경계를 넘지 않는다.

`--from-csv`에서는 current re-summary run과 source frame run을 구분한다.

### DF-2 — Immutable RF Input Resolution

구현 완료:

```text
--ours-frames
verified --ours compatibility resolver
owner manifest validation
frames / manifest SHA-256 verification
multi-run / retake ambiguity rejection
```

mutable flat path 자체는 provenance authority로 사용하지 않는다.

### DF-3 — RF Sample Lineage

구현 완료:

```text
rf-sample-lineage/1.0.0
results/<experiment_run_id>/sample_lineage.jsonl
```

canonical frames sample은 recording/run/frames hash로 추적하고,
external table sample은 source dataset/file hash/physical row identity로 추적한다.

### DF-4 — Immutable RF Experiment Run

구현 완료:

```text
rf-experiment-provenance/1.0.0
results/<experiment_run_id>/experiment_manifest.json
```

각 experiment는 고유 `er_*` directory를 사용하고,
running/completed/failed lifecycle, exact input provenance, sample lineage hash,
result artifact hash 및 compatibility publish order를 기록한다.

### DF-5 — Patch 6 boundary

구현 완료:

```text
dataset_manifest.dataset_manifest_id = null
dataset_manifest.path                = null
dataset_manifest.sha256              = null
```

Patch 5는 selection ledger, retake selection 또는 formal inclusion/exclusion policy를 구현하지 않았다.

---

# 25. Software Verification

Windows validation command:

```powershell
python -X utf8 -m unittest -q
```

Windows default `cp949`에서는 일부 UTF-8 repository text를 읽을 때 `UnicodeDecodeError`가 발생하므로,
Patch 5 baseline/final verification은 Python UTF-8 mode를 사용했다.
이를 해결하기 위한 source/test 수정은 하지 않았다.

검증 결과:

```text
pre-implementation baseline
204 PASS

Patch 5 targeted
python -X utf8 -m unittest -q test_patch5_lineage
48 PASS

final full suite
252 PASS

git diff --check
PASS
```

implementation commit 이후 재검증:

```text
Ran 252 tests
OK
working tree clean
```

synthetic fixtures/probes는 lineage/schema software verification용이며,
실제 연구 성능 또는 actual D455 formal validation 근거가 아니다.

---

# 26. Independent READ-ONLY Audit

독립 Claude Opus READ-ONLY audit:

```text
VERDICT: PASS WITH MINOR FINDINGS

BLOCKER:   0
IMPORTANT: 0
MINOR:     6

IMPLEMENTATION COMMIT RECOMMENDATION: YES
```

audit에서 별도로 확인한 핵심 사항:

```text
baseline d4dc23f: 204 PASS
working implementation: 252 PASS
Patch 5 targeted: 48 PASS

기존 수정 test 4개:
assertion weakening 없음
fixture/provenance setup 변경만 확인

Patch 4 / Patch 4.5 protected code:
scientific / frozen semantics 유지

RF end-to-end output:
baseline scientific numeric semantics 유지

sample lineage:
source bytes까지 positional trace 검증
cross-recording / cross-run silent path 없음
```

---

# 27. Accepted MINOR Findings

Patch 5 workflow는 `BLOCKER` / `IMPORTANT`를 closure 전 필수 수정 대상으로 삼는다.
독립 audit의 6개 MINOR는 frozen Patch 5 contract 위반이 아니며 다음과 같이 disposition한다.

| ID | Finding | Closure disposition |
|---|---|---|
| M-1 | `fig1` 및 text report의 subject/round-level presentation grouping은 복수 take를 시각적으로 함께 묶을 수 있음 | **ACCEPTED MINOR RESIDUAL.** canonical `summary_steps.csv`와 RF lineage에는 cross-recording 경로가 없으며 research figure/report presentation cleanup 후보로 남긴다. |
| M-2 | RF owner-manifest archive path 검증이 absolute path에 민감하여 repo relocation/reclone 후 historical run 사용성이 낮음 | **ACCEPTED CURRENT-CONTRACT LIMITATION.** PROV-005가 resolved absolute paths를 freeze한 현재 contract와 일치한다. portable provenance는 future schema revision 후보다. |
| M-3 | `rf_experiment.py`가 `analyze_d455.FRAME_FIELDS` import를 통해 `cv2` dependency를 transitively 요구 | **ACCEPTED MINOR DEPENDENCY.** lineage correctness 영향 없음. constants 분리 또는 OpenCV environment provenance 확장은 future cleanup 후보다. |
| M-4 | 일부 fail-closed negative branch가 dedicated unit test에는 없지만 independent probe에서는 정상 reject 확인 | **ACCEPTED TEST COVERAGE GAP.** current behavior는 audit probe로 검증됐으며 Patch 5 closure blocker가 아니다. |
| M-5 | `--skip-paper-loso`에서도 `paper_loso` lineage rows가 `ours_external` training source evidence로 남아 track 명칭 의미가 넓음 | **DOCUMENTED SEMANTIC NOTE.** lineage evidence 보존 자체는 정확하며 current schema revision에서 code change를 요구하지 않는다. |
| M-6 | `KeyboardInterrupt`의 `str(error)`가 빈 문자열이라 failed-manifest diagnostic에 exception type이 남지 않음 | **ACCEPTED MINOR DIAGNOSTIC LIMITATION.** artifact lineage/integrity 또는 scientific result에 영향 없음. |

M-1~M-6은 Patch 6 selection policy로 자동 흡수하지 않는다.
필요한 cleanup은 별도 범위로 결정한다.

---

# 28. Closure Boundaries

Patch 5 closure가 의미하는 것:

```text
same raw bytes의 independent recording identity fork 차단

canonical summary:
recording/source-run isolation

RF input:
immutable owner run + SHA pinning

RF sample:
persistent source lineage

RF result:
immutable experiment run provenance

result
→ sample_lineage
→ exact frames
→ exact analysis run
→ raw SHA / recording identity
역추적 가능
```

Patch 5 closure가 의미하지 않는 것:

```text
F1/F2 formula 확정
formal participant/round 수 확정
formal inclusion/exclusion 확정
retake selection policy 구현
Patch 6 selection manifest 구현
Patch 7 repository-wide integrity checker 구현
Patch 8 actual D455 formal hardware validation 완료
formal collection 승인
연구 성능 향상 증명
```

---

# 29. Next Action After Documentation Closure

현재 Patch 5 branch에서 다음 순서로 진행한다.

```text
1. docs-only documentation closure commit
2. full 252-test regression
3. branch final review / push
4. Patch 5를 main에 merge
5. post-merge 252-test regression
6. origin/main push
7. 필요 시 main-merge status sync
8. 그 이후 Patch 6 — Selection Manifest / Recapture Inclusion
```

권장 documentation closure commit message:

```text
docs: close Patch 5 end-to-end lineage hardening milestone
```

Patch 6 구현은 Patch 5 main integration 전 조용히 시작하지 않는다.
