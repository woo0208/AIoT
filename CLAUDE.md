# Claude Code Project Instructions

@AGENTS.md

## Project Role

This repository contains research code for a sitting-posture classification study.

Claude must distinguish between:

1. software implementation,
2. experimental/data-pipeline design,
3. scientific methodology.

Do not treat these as interchangeable.

## Core Rules

- Follow `AGENTS.md` first.
- Do not commit or push unless the user explicitly requests it.
- Do not reset, revert, checkout, clean, or discard existing working-tree changes unless explicitly requested.
- Do not modify files outside the requested patch scope.
- Do not perform unrelated refactoring.
- Do not change research methodology merely because an alternative appears better.
- Do not tune code or parameters toward a desired accuracy.
- Do not fabricate experimental results, measurements, tests, or hardware observations.
- Synthetic data may be used only for structural/unit testing, not as evidence of real-world performance.

## Research-Sensitive Changes

Before research-sensitive work, read:

1. `docs/research/AIoT_RESEARCH_MASTER.md`
2. `docs/research/RESEARCH_DECISION_LOG.md`
3. `RESEARCH_DATA_SCHEMA.md`
4. relevant canonical History/Foundation records when historical context is needed

This read order is not a single precedence chain. Route conflicts by authority:

- current implementation facts → Git / source / tests
- current research direction, scope, terminology, and roadmap → `AIoT_RESEARCH_MASTER.md`
- research decision status, rationale, OPEN/DEFERRED state, and supersession/resolution history → `RESEARCH_DECISION_LOG.md`
- implemented data/schema contracts → `RESEARCH_DATA_SCHEMA.md`
- future Patch 4 exact schema → `GOV-005` / `OPEN-001` in the Decision Log until Patch 4 Design Freeze
- other unimplemented/future schema designs → confirm their status in `RESEARCH_DECISION_LOG.md` before treating them as implemented or frozen contracts

The Step 1.5 Patch 4 field details in `RESEARCH_DATA_SCHEMA.md` are pre-freeze
proposals where routed to `GOV-005` / `OPEN-001`; do not treat them as frozen
merely because candidate fields or values appear in that document.

This applies to research-sensitive areas including provenance, canonical schema,
landmark/depth extraction, participant or recording inclusion, F0/F_cal/F1/F2,
M0/M1/M2, calibration/reference behavior, evaluation splits/metrics, and
experiment selection/manifest logic.

If these authorities appear to conflict, stop and report the conflict rather
than silently choosing one interpretation.

## Scientific Methodology Boundary

The following require explicit user approval before implementation:

- defining or changing an F1 feature formula
- defining or changing an F2 feature formula
- changing a depth ROI or landmark measurement definition
- changing missing-value policy in a way that affects experiment inclusion
- changing calibration/reference semantics
- changing model/evaluation splits
- changing labels or class definitions
- changing inclusion/exclusion criteria
- changing M0/M1/M2 definitions
- selecting parameters based on observed final-test performance

When such a decision is not already defined, report it as a research decision
instead of inventing one.

If an item is already recorded as OPEN or DEFERRED, do not resolve it merely
because implementation requires a value. When the canonical documents require
a Design Freeze before implementation, that Design Freeze must first be
explicitly decided by the user and recorded in the Decision Log; do not perform
or infer it implicitly.

## Current Experimental Structure

The current research structure should be treated as follows.

These are operational summaries only. If they conflict with the canonical
Research Master or Decision Log, the canonical research documents govern.

### F0

Original baseline feature set derived from the reference paper.

### F_cal

Legacy/reference-based comparison feature set.

This may use a participant/round upright reference.

It is retained for comparison and ablation purposes.

It is NOT the required inference method for the final proposed approach.

### F1

Future calibration-free 2D body-relative / upper-body skeletal geometry candidate family.

The exact feature formulas are NOT automatically defined by this label.

Do not invent or implement F1 formulas unless they have been explicitly approved.

### F2

Future feature set extending F1 with RGB-D / metric 3D upper-body geometry
and sagittal-plane geometry candidates.

The exact feature formulas are NOT automatically defined by this label.

Do not invent or implement F2 formulas unless they have been explicitly approved.

## Calibration Policy

Keep the following three concepts separate:

1. upright posture used as part of the capture sequence,
2. upright/reference used by legacy relative-calibration experiments,
3. calibration-free inference intended for future F1/F2.

Do not remove the existing upright sequence merely because F1/F2 are intended
to be calibration-free.

Do not require a participant-specific initial upright calibration for F1/F2
unless the user explicitly changes the research design.

## Data Roles

Dataset roles must remain distinguishable.

- `pilot`
- `formal`
- `external`

Existing legacy/pilot recordings must not be silently reinterpreted as formal data.

Unknown historical information should remain unknown rather than being inferred.

Do not promote pilot data to formal data merely because the data appears usable.

## Provenance

Preserve traceability across:

capture
→ recording
→ analysis
→ canonical data
→ summary
→ RF experiment
→ result

Important identifiers include:

- `recording_id`
- `analysis_run_id`
- dataset role
- protocol version
- code/Git provenance
- model provenance
- selection manifest or inclusion history

Do not introduce automatic "latest file" selection where an explicit recording
or analysis selection is required.

## Existing Capture Invariants

Unless a task explicitly targets them, preserve the currently validated capture behavior.

Important invariants include:

- RGB resolution: 1280×720
- Depth resolution: 848×480
- 15 FPS
- existing posture sequence
- existing hold/preparation timing
- forward target range: 0.08–0.12 m
- both forward range boundaries are valid
- forward validation is face-only
- current forward posture requires valid face measurements
- reference upright requires valid face measurements
- body-only forward movement must not satisfy the forward hard gate
- mixed-source measurements must not satisfy the forward hard gate
- generic body fallback may remain available for ordinary distance display/recording

Do not alter these while working on unrelated provenance, schema, analysis,
or data-management tasks.

## Existing RF / WRF Invariants

Unless explicitly targeted, preserve the existing model definitions.

Important existing behavior includes:

- M0 baseline RF
- M1 input-weighted RF behavior
- M2 split-score weighting
- independent bootstrap RNG and tree RNG
- M0 = M2 when lambda = 0
- existing rank-weight policy
- existing relative-reference evaluation behavior
- existing class ordering
- existing confusion-matrix orientation
- existing external evaluation rules
- existing body_forward exclusion policy where currently defined
- existing root-split provenance behavior

Do not silently change these to improve performance.

## Canonical Data Design

Keep three conceptual layers separate.

### 1. Canonical Raw Observations

Examples:

- face position
- face depth
- shoulder landmarks
- shoulder depth
- hip landmarks
- hip depth
- landmark validity
- visibility
- detector confidence

Raw/canonical observations should describe measured or extracted values.

### 2. Derived Geometry

Examples:

- midpoint
- body width
- normalized coordinates
- 2D vector
- 3D vector
- angle
- distance relation

Derived geometry should be clearly distinguishable from raw observations.

### 3. Model Feature Sets

Examples:

- F0
- F_cal
- F1
- F2

Do not mix unapproved research feature formulas directly into the canonical
raw schema.

## Hip / Arm Policy

Hip landmarks are a confirmed core raw-observation direction for future
body/trunk geometry (`FEAT-003`). Candidate Patch 4 fields may include left/right
position, depth, visibility, and validity, but exact Patch 4 naming, depth
extraction, and missing/validity serialization remain governed by `OPEN-001`.

Do not define trunk-angle formulas merely by adding hip landmarks.

Elbow and wrist landmarks have strengthened rationale as candidate raw
observations for upper-body skeletal/context analysis. Their exact Patch 4
disposition — include, reserve, or exclude-and-version-later — remains
`OPEN-001` and must not be inferred here.

Raw observation storage does not imply F1/F2 model-feature use. Do not
automatically promote elbow/wrist data into F1 or F2 or add arm-up/down as a
new primary posture class.

## Missing Data Policy

For a fixed canonical schema:

- do not remove a column simply because a landmark was not detected,
- represent unavailable measurements using the schema-approved missing-value representation,
- preserve explicit validity/visibility information where defined.

Do not change missing-data handling if doing so can change sample inclusion or
evaluation results without explicit approval.

## MediaPipe / Analysis Reproducibility

When analysis provenance is relevant:

- identify the actual model artifact used,
- record file hashes where defined,
- do not assume the same filename means the same model,
- do not overwrite an existing local model merely because a `/latest/` URL exists,
- distinguish raw inference from CSV-only reprocessing,
- do not claim a model was used in a run when that run did not perform model inference.

Unknown provenance must remain explicitly unknown.

## Hardware Validation

Automated tests do not replace actual D455 validation.

Always distinguish:

- verified by unit/integration tests,
- verified by static code review,
- verified using actual D455 hardware,
- still pending hardware validation.

Do not report synthetic or mocked camera behavior as real hardware evidence.

## D455 Operating Range

Do not automatically introduce a special `<40 cm` fallback algorithm merely
because another experiment or team reported a possible near-range issue.

The intended process is:

1. measure the actual operating distances used by this experiment,
2. measure depth valid rate and measurement variation,
3. determine whether the issue actually occurs,
4. only then consider a fallback if justified.

Do not invent a fallback rule before empirical validation.

## Camera Validation

Camera/device validation must remain separate from participant calibration.

Patch 8 includes D455 measurement-quality validation (`CAP-004`). Validation
categories include:

- landmark acquisition stability,
- head / shoulder / hip depth valid rate,
- depth repeatability / jitter at relevant distances,
- 3D geometry repeatability,
- RGB-landmark + aligned-depth combination stability,
- distance-dependent feature stability.

Exact distance grids, repetitions, metrics, thresholds, and validation protocol
remain research decisions rather than defaults in this file. These measurements
characterize the camera/system and do not constitute participant-specific
posture calibration.

## Review Mode

When the user requests a read-only review:

- do not edit files,
- do not create files,
- do not run formatting tools that change files,
- do not commit,
- do not push,
- do not reset/revert/checkout working-tree changes,
- inspect `git status`,
- inspect `git diff`,
- inspect relevant implementation,
- inspect relevant tests,
- independently verify the patch against its stated objective,
- do not assume another coding agent's report is correct.

Use one of these conclusions:

- `COMMIT OK`
- `FIX BEFORE COMMIT`
- `COMMIT OK / HARDWARE SMOKE TEST PENDING`

When findings exist, classify them where appropriate as:

- `BLOCKING`
- `IMPORTANT`
- `MINOR`

## Independent Review Principle

When reviewing code implemented by Codex, Astra, Claude, or another coding agent:

- treat the previous agent's summary only as a claim to verify,
- inspect the actual diff and code,
- verify test quality rather than trusting the reported PASS count,
- look for shared assumptions between implementation and tests,
- specifically inspect negative and failure cases,
- distinguish code correctness from scientific-methodology correctness.

Agreement between AI agents is not experimental evidence.

## Testing

For normal code patches, run at least:

    python3 -B -m unittest -q
    git diff --check
    git status --short

When appropriate, also inspect:

    git diff --stat
    git diff

Do not weaken, delete, skip, or rewrite existing tests simply to make a patch pass.

A higher test count is acceptable when new tests are added.

Do not force a historical test count if legitimate tests were added.

## Test Interpretation

A passing unit test means only that the tested behavior passed.

It does NOT prove:

- the scientific assumption is valid,
- D455 hardware behaves the same way,
- the experimental protocol is valid,
- a feature improves generalization,
- a model performs better on real participants.

Keep software verification and research evidence separate.

## Working Tree Safety

Before continuing an interrupted task:

1. inspect the current working tree,
2. preserve valid partial work,
3. classify work as complete / partial / missing,
4. continue only the missing portion.

Do not restart the entire patch merely because the previous agent session ended.

Never discard uncommitted work unless the user explicitly requests it.

## Git Safety

Do not automatically:

- commit,
- push,
- force-push,
- reset,
- revert,
- checkout files,
- clean untracked files,
- rewrite history.

Only perform these when explicitly requested.

When a patch is complete, report that it is ready for commit rather than
committing automatically.

## Research Result Integrity

Never:

- tune parameters toward a desired result,
- remove inconvenient samples without a predefined rule,
- choose the best retake based on model accuracy,
- change feature definitions after viewing final external-test performance and still call that test untouched,
- fabricate missing measurements,
- fabricate hardware results,
- fabricate participant data.

If final-test data influences method design, explicitly treat that data as
development data rather than untouched final validation.

## External / Final Evaluation

The intended final external-condition evaluation should remain separate from
method development.

Do not use final external-condition results to repeatedly tune F1/F2 and then
present the same data as untouched external validation.

Any such reuse must be reported explicitly.

## Scientific Review Checklist

For research-sensitive changes, consider:

- data leakage
- participant leakage
- recording leakage
- calibration leakage
- train/test contamination
- preprocessing mismatch
- inconsistent coordinate systems
- inconsistent units
- feature definition drift
- missing-data bias
- selection bias
- retake selection bias
- different sample counts between compared methods
- differences caused only by additional feature count
- random-seed fairness
- model provenance
- camera-condition differences
- whether the claimed conclusion is stronger than the evidence

Do not change code simply because one of these risks exists.
Report the risk first unless the requested patch explicitly targets it.

## Current Development Strategy

The operational research roadmap is defined by
`docs/research/AIoT_RESEARCH_MASTER.md`. Do not maintain an independent numbered
research roadmap in `CLAUDE.md`.

At the current canonical state:

- agent-instruction alignment precedes Foundation Patch 4 work,
- Foundation Patch 4 requires an explicit Design Freeze before implementation,
- `OPEN-001` must not be implicitly resolved from Step 1.5 schema proposals.

Only perform the currently requested scope.

## Change Reporting

After implementation, report:

1. changed files
2. what was implemented
3. what was deliberately not changed
4. tests added or changed
5. full test result
6. `git diff --check` result
7. remaining risks
8. hardware/manual checks still required
9. items deferred to the next patch

For research-sensitive changes, additionally report:

10. whether numerical semantics changed
11. whether sample inclusion changed
12. whether evaluation behavior changed
13. which research decisions remain unresolved
