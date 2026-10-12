# F1 Frame-to-Sample Aggregation Review (2026-10-12)

- **Document status:** `DESIGN REVIEW / PROPOSALS ONLY` — not a research decision, not an implementation, not an experiment
- **Gate:** Research Stage 1 Gate 1.7
- **Recorded on:** branch `feat/posture-integrated-v0`, HEAD `df3de85`
- **Authority used:** `FEAT-009` + `docs/research/F1_FEATURE_CORE_CALCULATION_CONTRACT.md`;
  `RESEARCH_DATA_SCHEMA.md` §F (`frames-schema/1.0.0`), §G.1 (`summary-schema/1.0.0`), §H (Patch 6 selection);
  `f1_features.py` / `test_f1_features.py` at `df3de85`; `analyze_d455.py` (frame emission and summary grouping, read-only)
- **Companion:** `F1_HIP_ENGINEERING_OBSERVATION_2026-10-12.md`
- **Unchanged:** F1-5 (`FEAT-009`), `OPEN-002` (partially approved / **DEFERRED**), F1 full Design Freeze (**not completed**),
  `OPEN-003`–`OPEN-005`, `frames-schema/1.0.0`, `summary-schema/1.0.0`, `CAP-005`. No Decision Log entry is added.

Every aggregation approach below is a **proposal**. Contract §6 lists frame→sample median aggregation,
`so_beta` angular aggregation, joint support, `N_min`, `R_min`, the `D_sh` quality bound, and model-level
missing handling as **not approved**; this review does not change that.

Status vocabulary: `APPROVED` (existing confirmed authority), `PROPOSED` (candidate for researcher review),
`DEFERRED` (needs evidence or a later decision), `NOT VERIFIED` (claim without supporting evidence).

---

## A. Grouping and provenance

### A.1 Identifiers that actually exist

| Concept | Source of truth | In frame CSV? | Notes |
|---|---|---|---|
| Frame row identity | `(analysis_run_id, recording_id, frame_index)` (Schema §F.3) | yes | `frame_index` is a 1-based source traversal index; not contiguous (trim, `--step`). Timestamps are not identity. |
| Recording | `recording_id` (Schema §A, §F.3 #33) | yes | One capture attempt. Recapture = new `recording_id`, same `round`. |
| Analysis run | `analysis_run_id` (Schema §F.3 #34) | yes | Two runs of the same recording must never be pooled (`summarize()` raises on this). |
| Subject | `subject` (legacy prefix #1); authoritative via capture metadata of `recording_id` (Schema §C.2) | yes | LOSO group unit is subject (Schema §G.2). |
| Round / "session" | `round` (prefix #2), positive-integer decimal string (Schema §H.1) | yes | `round` is a **planned measurement slot**, not a capture attempt. There is **no separate `session` field**. |
| Posture step | `step` (prefix #3) | yes | Per-recording hold-phase index. `label` repeats (`upright` appears 3× in `SEQ_CORE`), so **`step`, not `label`, identifies the posture segment**. |
| Posture label | `label` (prefix #4) | yes | Must be constant within a step. |
| Dataset role, protocol version | capture/run manifest & catalog (Schema §F.3: deliberately **not** frame columns) | **no** | Present in `summary-schema/1.0.0`; must be joined from provenance, never guessed. |
| Which recording represents a slot | Patch 6 dataset manifest `(dataset_role, subject, round)` (Schema §H) | **no** | The aggregator must not choose among recaptures. |

Facts from `analyze_d455.py` (static read):
- Only **hold-phase** frames are emitted, after `TRIM_START`/`TRIM_END` trimming (lines ~783–788).
  Transition frames are not in the canonical CSV; an aggregator must not re-trim or redefine segments.
- The analysis CLI option `--step N` (analyse every N-th frame) is **unrelated** to the posture `step`
  column, but it changes frames per sample — so per-sample frame counts depend on the `analysis_run_id`.

### A.2 Proposed sample key

```text
sample key (PROPOSED) = (analysis_run_id, recording_id, step)
```

- This is the existing `summary-schema/1.0.0` grouping key / primary key (Schema §G.1), so it is a
  precedent rather than a new invention. It is still a proposal for F1.
- Within a group, `subject`, `round`, and `label` must be identical; any conflict is a
  provenance/schema error (same rule as `summarize()`), never resolved by averaging.
- Never combine frames across subjects, recordings, analysis runs, rounds, or steps.
- Cross-recording selection (original vs recapture) stays with the Patch 6 dataset manifest.
- Legacy unversioned frame CSVs lack `recording_id` / `analysis_run_id` / hips and are out of scope
  (contract §7: the paper dataset has no bilateral hip raw material).

---

## B. Frame-level validity (APPROVED, unchanged)

As implemented in `f1_features.compute_f1_5_frame` and specified by contract §4–§5:

| Family | Requires | Validity source |
|---|---|---|
| FS | `face_detected = true` + finite `face_x/face_y`; both shoulders; `D_sh > 0` | `face_detected`; `lsh_valid`, `rsh_valid` |
| SH | both shoulders + both hips; `D_sh > 0` | `lsh_valid`, `rsh_valid`, `left_hip_valid`, `right_hip_valid` |
| SO | both shoulders; `D_sh > 0` | `lsh_valid`, `rsh_valid` |

- An observation is used only when its state is **explicit `true`** and x/y are finite. Legacy shoulder
  numbers that remain when `*_valid = false` are not used (Schema §F.3 D02 note).
- `D_sh > 0` is a mathematical condition, not a quality threshold.
- No visibility, presence, `face_score`, or extra face in-frame threshold is introduced.
- `F1FrameResult.family_reasons` gives per-family reason strings (e.g. `left_hip_valid:false`,
  `face_detected:unknown`, `d_sh:zero`); these are diagnostics, not eligibility decisions.

Note: `F1FrameResult` carries **no frame key or group identity**. An aggregator must receive those
alongside each result (see §Gate 1.8).

---

## C. Joint-support candidate J (PROPOSED, not approved)

```text
J = { frames where FS, SH and SO are all available }
  = { frames with valid face, both shoulders, both hips, D_sh > 0 }   (SO is implied by FS or SH)
```

| Aspect | Assessment |
|---|---|
| Why it may help | All five features in a sample then summarise the **same frames**, so the sample vector describes one consistent set of body configurations. Avoids a sample whose `fs_*` reflects one subset of the step and whose `sh_*` reflects a different subset (e.g. only the few frames where hips happened to be valid). |
| Why it can hurt | `|J| <= min(|FS|, |SH|, |SO|)`. The scarcest family dictates coverage for **all** features. With the previously reported preflight counts (SH 5/649), `|J| <= 5/649` — SO and FS information in ~640 frames would be discarded. |
| Body Forward hip effect | If hips go out of frame or become `*_hip_valid = false` more often in `body_forward` (hypothesis; see companion doc §4.1), J shrinks **selectively in that posture**, so posture categories end up supported by very different frame counts. |
| Why family-specific coverage must still be reported | Under J, an SH failure is indistinguishable from an FS failure in the output unless per-family counts and reasons are kept. Family counts show *which* observation limits coverage and are needed to evaluate J versus family-specific support at all. |
| Relation to AC-4 | AC-4 ("same-frame geometry first") is satisfied by both policies, because every feature is computed per frame before aggregation. J is an additional, stronger *support* choice, not something AC-4 requires. |

Both J and family-specific support should be available to a prototype only as an **explicit,
recorded option**; neither is a default policy.

---

## D. Aggregation candidates (PROPOSED)

### D.1 Component-wise median for `fs_x`, `fs_y`, `sh_x`, `sh_y`

```text
fs_x_agg = median({fs_x_i : i in support})      (likewise fs_y, sh_x, sh_y)
```

- Robust to a minority of outlier frames (landmark jumps) and order-invariant (frames need not be contiguous).
- Consistent with the existing summary convention (`analyze_d455.med()` uses `statistics.median`;
  even counts → mean of the two middle values).
- Limitation: the component-wise median of `(fs_x, fs_y)` need not equal any single frame's vector.
- It does not remove systematic bias (e.g. a hip estimate that drifts consistently in one posture).

### D.2 Axial mean for `so_beta`

```text
C = mean(cos(2 * beta_i))
S = mean(sin(2 * beta_i))
R = sqrt(C*C + S*S)                     # 0 <= R <= 1
beta_agg = wrap_pi(0.5 * atan2(S, C))   # [-pi/2, pi/2)
```

- **Period-π orientation:** `so_beta` is an axis (W and −W give the same β). Doubling maps the axis
  to an ordinary period-2π angle where vector averaging is valid; halving maps back.
- **Why the arithmetic mean can fail:** values near the wrap boundary are close as axes but far as
  numbers. Example (synthetic): β = −π/2 + 0.01 and π/2 − 0.01 are both nearly vertical axes; the
  arithmetic mean is 0 (horizontal), while the axial mean is ≈ −π/2 (vertical). For near-horizontal
  shoulder lines the two usually agree, but the arithmetic mean has no guarantee.
- **Undefined R = 0:** when the doubled unit vectors cancel, no mean axis exists; `atan2(0, 0)` must not
  be used as a valid β (same principle as contract §4 for `D_sh = 0`).
- **Why a numerical threshold needs evidence:** an exact `R == 0` test is insufficient in floating
  point. Synthetic check in this task: β = {0, π/2} gives `C = 0.0`, `S ≈ 6.1e-17`, `R ≈ 6.1e-17`,
  and `0.5 * atan2(S, C) = π/4` — an arbitrary axis reported as if defined. Small `R` also means the
  shoulder-line orientation genuinely varied within the step. Choosing `R_min` (statistical
  dispersion) or a numerical tolerance requires data on observed `R` distributions; neither is approved.
- `R` must always be reported alongside `beta_agg`.
- F1-6 note (out of scope): aggregating `sin 2β`, `cos 2β` directly yields `(S, C)`, whose length is `R`,
  whereas `sin/cos(2·beta_agg)` is unit length. The choice matters if F1-6 is later compared; not decided here.

### D.3 Should all features share support J?

| Option | Pro | Con |
|---|---|---|
| Family-specific support (FS→FS frames, SH→SH frames, SO→SO frames) | Maximises use of available frames; SO is unaffected by hip failures | Components of one sample vector may summarise different frame subsets |
| Joint support J for all five | One consistent frame set per sample | Coverage limited by the scarcest family (hips) |
| Hybrid (e.g. J for FS+SH, SO on its own support) | Middle ground | More policy surface; still a research choice |

No option is recommended for approval here. The deciding evidence is real per-step family and joint
coverage (§F).

---

## E. Missing-data diagnostics (PROPOSED, separate artefact)

Minimum per-sample diagnostics:

| Diagnostic | Definition |
|---|---|
| `n_frames` | frames in the group (hold-phase canonical rows) |
| FS / SH / SO valid counts | frames with each family available |
| joint valid count | frames in J |
| coverage % | each count / `n_frames` |
| invalid-reason distribution | per family, counts of `family_reasons` strings (a frame may contribute several) |
| axial resultant `R` | for `so_beta` on the support used |
| per-feature `n_used` and undefined reason | e.g. `no_supported_frames`, `axial_resultant_zero` |
| provenance | sample key, `subject`, `round`, `label`, support policy, `FEAT-009`, prototype version label |
| selected-frame references | `frame_index` values (with run/recording) actually used per feature |

These belong to a **separate diagnostics output**. `frames-schema/1.0.0` and `summary-schema/1.0.0` are
not modified; no column is added to canonical frames. Any persisted F1 sample format would need its own
schema decision later.

---

## F. Deferred policies and the evidence each needs

No numeric values are proposed. Two screenshots and a 649-frame preflight under old framing are **not**
a basis for thresholds (Master: preflight is not threshold/protocol evidence).

| Policy | Evidence required before deciding |
|---|---|
| `N_min` (frames per sample) | Distribution of family/joint valid counts per step across real canonical recordings under the formal framing, per posture and subject; effect of `--step` on counts |
| `R_min` | Distribution of axial `R` per step; synthetic vs real noise floor; behaviour at small support sizes |
| `D_sh` quality lower bound | `D_sh` pixel distribution per distance/subject; cases of shoulder occlusion or collapse; relation to Patch 8 measurement quality |
| Visibility / presence thresholds | Relation between visibility (and presence, not stored in schema) and landmark error — requires ground truth or repeated measurement; would also require a schema/validity decision. Not introduced. |
| Complete-case vs imputation vs missing indicators | Size and posture dependence of missingness; whether missingness is informative of class (leakage risk) |
| Model-eligible sample criteria | All of the above plus `OPEN-005` inclusion/exclusion and `ok_with_warnings` policy |
| Subject-held-out / LOSO population | `OPEN-005` participant/round counts; per-subject coverage so no subject is silently dropped |
| F1-specific M1/M2 weighting | Separate decision; p = 5 (F1-5) / 6 (F1-6) avoids the `OPEN-004` `p > 6` gate, but that is not a policy approval |

---

## G. Impact of the Hip observations

| Affected item | Observed (engineering, companion doc §3) | Untested dataset-level hypothesis |
|---|---|---|
| SH availability | Original framing put hips below the image edge; adjusted framing showed both hips in upright | SH coverage under adjusted framing is substantially higher than the preflight's 5/649 — **NOT VERIFIED** |
| Joint-valid coverage | Body Forward hip midpoint ≈ 0.960 of image height (near edge), still IN | `body_forward` steps lose hips more often → J coverage lower in that posture — **NOT VERIFIED** |
| Sample eligibility | — | Any `N_min` applied to SH or J support would exclude `body_forward` samples disproportionately — **NOT VERIFIED** |
| Posture-dependent missingness | Hip visibility ≈ 0.76–0.81, presence ≈ 0.27–0.36 in one forward screenshot | Missingness correlates with class → complete-case analysis biases class composition and missingness itself becomes a class cue (leakage risk) — **NOT VERIFIED** |
| Comparability between postures | Hip midpoint Δy ≈ 2× shoulder Δy in one pair (normalized units) | `sh_*` in `body_forward` mixes posture signal with hip-estimation behaviour; per-posture comparisons may differ in measurement quality, not only posture — **NOT VERIFIED** |

The observed behaviour justifies **measuring** per-posture coverage before choosing a support policy; it
does not justify any threshold, a Fixed-Hip substitute, or a change to F1-5.

---

## Decision matrix

| # | Design item | Current authority | Proposed approach | Benefits | Risks | Evidence required | Safe for synthetic prototype? | Researcher approval required? | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | F1-5 frame features | `FEAT-009`, contract §3 | Use `compute_f1_5_frame` as-is | Fixed, tested definition | — | — | Yes (exists) | Already given | **APPROVED** |
| 2 | Frame family validity | `FEAT-009`, contract §5, Schema §F | Use `family_available` / `family_reasons` as-is | No new thresholds | Validity ≠ quality | — | Yes (exists) | Already given | **APPROVED** |
| 3 | Sample key | Schema §G.1 precedent | `(analysis_run_id, recording_id, step)` | Matches summary lineage; no cross-recording mixing | Recapture choice must come from manifest | — (structural) | Yes | Yes (for F1 use) | PROPOSED |
| 4 | Identity consistency | `summarize()` precedent | Error on mixed subject/round/label/key; duplicate frame key | Fail-closed provenance | — | — | Yes | Yes | PROPOSED |
| 5 | Family-specific support | Contract §6 (not approved) | Each feature uses its family's frames | Max coverage; SO robust to hip loss | Components from different frames | Real per-step coverage | Yes, as explicit option | Yes | PROPOSED |
| 6 | Joint support J | Contract §6 (not approved) | All features on J | Frame-consistent sample | Coverage collapse; posture-selective loss | Real per-step joint coverage by posture | Yes, as explicit option | Yes | PROPOSED |
| 7 | Median for fs/sh | Contract §6 (not approved) | Component-wise `statistics.median` | Robust, order-invariant | Bias not removed; vector may match no frame | Within-step variability on real data | Yes | Yes | PROPOSED |
| 8 | Axial mean for `so_beta` | Contract §6 (not approved) | Doubled-angle mean, report `R` | Correct for period-π | Small-R instability | `R` distribution | Yes | Yes | PROPOSED |
| 9 | `R = 0` handling | Contract §4 principle (`atan2(0,0)` invalid) | Undefined on exact `C = S = 0`; always report `R` | No fabricated axis at exact zero | Near-zero R still yields arbitrary angle | `R` distribution; numeric analysis | Yes | Tolerance: yes | PROPOSED (tolerance DEFERRED) |
| 10 | `N_min` | Contract §6 | None | — | Posture-selective exclusion | §F | No value in prototype | Yes | DEFERRED |
| 11 | `R_min` | Contract §6 | None | — | — | §F | No value in prototype | Yes | DEFERRED |
| 12 | `D_sh` quality bound | Contract §4/§6 | None (`D_sh > 0` only) | — | — | §F, Patch 8 | No value in prototype | Yes | DEFERRED |
| 13 | Visibility/presence thresholds | Schema §F.4, contract §5 (not thresholds) | None | — | — | Ground truth / repeated measurement | Not introduced | Yes (+ schema decision) | DEFERRED |
| 14 | Face extra in-frame policy | Contract §5/§6 | None | — | Off-image bbox centres | Real failure cases | Not introduced | Yes | DEFERRED |
| 15 | Model-level missing handling | Contract §6, `OPEN-002` | None | — | Leakage via missingness | §F, §G | No | Yes | DEFERRED |
| 16 | Model-eligible sample criteria | `OPEN-005` | None | — | Selection bias | §F + protocol freeze | No | Yes | DEFERRED |
| 17 | LOSO / subject-held-out population | `OPEN-005`, Schema §G.2 | None | — | Subject dropout | Per-subject coverage | No | Yes | DEFERRED |
| 18 | F1 M1/M2 weighting | `OPEN-004` context, contract §6 | None | — | — | Separate decision | No | Yes | DEFERRED |
| 19 | Diagnostics output | — | Separate in-memory diagnostics (§E); no schema change | Makes coverage visible | Mistaken for a frozen format | — | Yes | Yes (before persisting) | PROPOSED |
| 20 | Fixed-Hip (`H0`) | None; calibration-based, outside F1-5 / `FEAT-002` tension | Not part of aggregation | — | Hidden reference dependency | Controlled comparison + new decision | Not in Gate 1.8 | Yes (new Decision Log entry) | NOT VERIFIED |
| 21 | Body Forward hip coverage impact | Companion doc | Measure before deciding | — | — | Real canonical recordings | — | — | NOT VERIFIED |
| 22 | F1-6 aggregation | Contract AC-5 (comparison candidate) | Out of scope | — | `R`-scaled vs unit encoding | Separate comparison | Not in Gate 1.8 | Yes | DEFERRED |

---

## Gate 1.8 boundary (proposal; not implemented in this task)

**Smallest next task:** a standalone, hardware-independent F1 sample aggregator module (e.g.
`f1_aggregation.py` + `test_f1_aggregation.py`) that consumes per-frame F1 results for **one** sample
group and returns aggregated values plus diagnostics. It reads no files, calls no camera, writes nothing,
and makes no eligibility decision.

### Minimal input contract

```text
F1FrameRecord (frozen):
  analysis_run_id : str      # frame key part (Schema §F.3)
  recording_id    : str      # frame key part
  frame_index     : int      # frame key part
  subject         : str      # copied from the same canonical row
  round           : str
  step            : str      # posture step (not the --step CLI option)
  label           : str
  result          : F1FrameResult   # from compute_f1_5_frame, unchanged

aggregate_f1_sample(records: Sequence[F1FrameRecord], *, support: "family" | "joint") -> F1SampleResult
```

- `support` has **no default**: callers must choose, and the choice is recorded.
- Fail-closed (`ValueError`): empty input; records from more than one `(analysis_run_id, recording_id, step)`;
  conflicting `subject` / `round` / `label`; duplicate frame key; `family_available = true` with a
  missing or non-finite feature value; `family_available = false` with a non-`None` value.

### Minimal result contract

```text
F1SampleResult (frozen):
  sample_key            : (analysis_run_id, recording_id, step)
  subject, round, label : str
  support_policy        : "family" | "joint"
  source_decision       : "FEAT-009"
  prototype_label       : non-frozen version label (not a schema version)
  n_frames              : int
  family_valid_counts   : {FS, SH, SO -> int}
  joint_valid_count     : int
  coverage              : {FS, SH, SO, joint -> float}       # count / n_frames
  invalid_reason_counts : {FS, SH, SO -> {reason -> int}}
  features              : {fs_x, fs_y, sh_x, sh_y, so_beta -> float | None}   # F1-5 order
  feature_n_used        : {name -> int}
  undefined_reasons     : {name -> None | "no_supported_frames" | "axial_resultant_zero"}
  so_beta_resultant     : float | None                       # R
  support_frame_indices : {FS, SH, SO, joint -> tuple[int, ...]}   # frame_index, sorted
```

No `eligible`, `N_min`, `R_min`, imputation, or label-derived field.

### Calculation behaviour

- Median: `statistics.median` per feature over the chosen support; even counts → mean of middle two.
- Axial mean: as §D.2; `beta_agg` via existing `f1_features.wrap_pi`; undefined only when `C == 0` and
  `S == 0` exactly; `R` always returned when support is non-empty.
- `None` is never replaced by `0`, a sentinel, or an interpolated value; outputs are finite or `None`.
- Input order must not affect results; inputs are not mutated.

### Required synthetic unit tests (structural only; not research evidence)

1. Constant-feature frames → aggregate equals the constant; `R = 1`.
2. Median odd/even counts and a single outlier frame.
3. Axial wrap: β = {−π/2 + ε, π/2 − ε} → `beta_agg` axially equivalent to vertical (compare with a period-π distance, not raw difference), not 0; result in `[-π/2, π/2)`. (Checked in this task with ε = 0.01: axial mean −π/2, arithmetic mean 0.)
4. Exact `C = S = 0` path (via the internal axial helper) → `so_beta = None`, reason `axial_resultant_zero`.
5. Near-cancellation β = {0, π/2} → `R` reported as tiny; test documents the limitation without asserting a "correct" angle.
6. Family policy: all hips invalid → `sh_* = None` (`no_supported_frames`) while `fs_*`, `so_beta` are aggregated.
7. Joint policy: same fixture → all five `None`; counts show SH as the limiting family.
8. `joint_valid_count <= min(family counts)`; support frame indices consistent with counts.
9. Invalid-reason counting (e.g. `left_hip_valid:false`, `face_detected:unknown`, `d_sh:zero`).
10. Fail-closed cases: mixed recording / run / step, conflicting label/subject/round, duplicate frame key, empty input, inconsistent `F1FrameResult`.
11. Order invariance (shuffled input) and immutability of the result.
12. `n_frames = 1` still aggregates (proves no hidden `N_min`).
13. A synthetic "forward-like" fixture with partial hip invalidity, clearly labelled synthetic.
14. `test_f1_features.py` continues to pass unchanged.

### Scope separation

| Category | Items |
|---|---|
| **A. Safe to implement with synthetic fixtures** | Input/result dataclasses; group/identity validation; family and joint support counting; reason counting; component-wise median; axial mean with exact-zero undefined path; `R` reporting; frame-index references; tests 1–14 |
| **B. Configurable experimental candidates (explicit option, no default, recorded in result)** | `support = "family"` vs `"joint"`; optionally a hybrid support or a numeric near-zero `R` tolerance — only as caller-supplied parameters with **no default value**, and only if the researcher asks for them |
| **C. Decisions requiring actual dataset coverage** | Choice of support policy; `N_min`; `R_min`; `D_sh` quality bound; visibility/presence thresholds; face in-frame policy; complete-case vs imputation vs indicators; model-eligible criteria; LOSO population; F1 M1/M2 weighting; F1-5 vs F1-6 final selection |
| **D. Out of scope** | Reading/writing CSVs or new persisted schemas; changes to `frames-schema/1.0.0`, `summary-schema/1.0.0`, `f1_features.py`, `analyze_d455.py`, `rf_experiment.py`; RF training; LOSO experiments; D455 capture or Patch 8 execution; Fixed-Hip; F1-6 aggregation; F2; Decision Log / Master edits; F1 full Design Freeze |

---

## Researcher decisions still needed

1. Whether to authorise Gate 1.8 as scoped above (synthetic prototype only).
2. Whether the sample key `(analysis_run_id, recording_id, step)` is accepted for F1.
3. Whether the prototype should expose both `family` and `joint` support (recommended: both, no default).
4. Whether a numeric near-zero `R` tolerance parameter is wanted in the prototype (value remains deferred).
5. Which real canonical recordings (under the adjusted framing, with Patch 6 manifest selection) will be used to
   measure per-step family/joint coverage before any support policy, `N_min`, or `R_min` decision.
6. Whether Fixed-Hip should ever be evaluated as a separate, explicitly calibration-based comparison (requires its own Decision Log entry).
