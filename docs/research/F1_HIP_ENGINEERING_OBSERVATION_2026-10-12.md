# F1 Hip Engineering Observation (2026-10-12)

- **Document status:** `NON-FORMAL ENGINEERING OBSERVATION` — not a research decision, not a measurement result, not Patch 8 validation
- **Gate:** Research Stage 1 Gate 1.7 (design review input)
- **Recorded on:** branch `feat/posture-integrated-v0`, HEAD `df3de85`
- **Authority unchanged:** `FEAT-009` (F1-5 core calculation, CONFIRMED — core only), `OPEN-002` (partially approved by `FEAT-009`, **DEFERRED**), `CAP-005` / `CAP-007` (Patch 8 design frozen; formal execution deferred), `frames-schema/1.0.0` (`DATA-003`)
- **Decision Log:** no entry is added or changed by this document

This document records engineering observations about MediaPipe hip landmarks on a
real D455 so that the F1 frame-to-sample aggregation review
(`F1_FRAME_TO_SAMPLE_AGGREGATION_REVIEW_2026-10-12.md`) can reason about Hip
availability. It does not change F1-5, Schema §F validity semantics, or any frozen contract.

---

## 1. Evidence classes used in this document

| Class | Meaning |
|---|---|
| **OBSERVED** | Seen directly in a previous audit output, viewer screen, or screenshot reported by the researcher. Not re-verified in this task unless stated. |
| **INFERRED** | A reasoned explanation or consequence of an observation. Plausible, untested. |
| **NOT VERIFIED** | A claim that the observations cannot support. Must not be cited as a finding. |

All observations below are non-formal engineering diagnostics: single-session,
non-repeated, no controlled distance grid, no independent anatomical ground truth.

---

## 2. Previous PREFLIGHT audit (reported, not re-verified)

Source: earlier F1 Gate audit over the Early Hardware Preflight canonical frame CSV
(`AIoT_RESEARCH_MASTER.md` "Early Hardware Preflight — DONE / NON-FORMAL": 649 canonical rows,
`frames-schema/1.0.0`). The Master records that preflight as engineering smoke evidence only,
**not** formal data and **not** a basis for threshold or protocol decisions.

| Family | Definition (FEAT-009 / contract §4–§5) | Available frames |
|---|---|---:|
| FS | face + both shoulders + `D_sh > 0` | 626 / 649 |
| SO | both shoulders + `D_sh > 0` | 649 / 649 |
| SH | both shoulders + both hips + `D_sh > 0` | 5 / 649 |

- These counts are **previously reported audit results**. They were **not independently
  re-verified in this task** (the preflight CSV is local-only and not in Git).
- Arithmetic consequence (not a new measurement): because SH requires a subset of the
  observations that a joint FS∧SH∧SO frame requires, the joint-valid count in that CSV is
  **at most 5 / 649** if the reported counts are correct.
- The preflight was captured with the original camera framing (see §3.1). Whether its low SH
  count is caused by that framing is **INFERRED**, not verified frame-by-frame here.

---

## 3. Recent D455 engineering observations

### 3.1 Framing (OBSERVED)

1. With the original camera framing, MediaPipe hip landmarks frequently fell **below the image
   boundary** (normalized `y >= 1`). Under Schema §F.4 such a hip is `*_hip_valid = false`,
   so SH is unavailable for that frame.
2. After adjusting the camera framing, **both hip landmarks were visible (in-frame) in upright posture**.

### 3.2 Body Forward hip displacement (OBSERVED, representative screenshot pair)

3. When the seated subject leaned the upper body forward, the MediaPipe hip estimates moved substantially.
4. Representative paired screenshots (normalized image coordinates, `y` positive downward):

| Quantity | Upright | Body Forward | Δy (Forward − Upright) |
|---|---:|---:|---:|
| Shoulder midpoint `y` | ≈ 0.502 | ≈ 0.552 | ≈ +0.050 |
| MediaPipe hip midpoint `y` | ≈ 0.856 | ≈ 0.960 | ≈ +0.104 |

   - These are **normalized image coordinates** (fraction of image height), **not physical
     forward-motion distances** and not F1-5 pixel-coordinate features.
   - The values come from one representative pair, read from the screen to ~3 decimals.

5. In the Body Forward screenshot:
   - both hip landmarks remained **IN** frame (normalized `y < 1`);
   - hip **visibility** ≈ 0.76–0.81;
   - hip **presence** ≈ 0.27–0.36.

   Note: `presence` is not a `frames-schema/1.0.0` field (Schema §F.4 stores only
   `*_hip_visibility`). Neither visibility nor presence is an acceptance threshold under
   Schema §F.4 / contract §5, and this document does not introduce one.

### 3.3 Fixed-hip diagnostic viewer (OBSERVED)

6. A fixed-hip diagnostic mode of the untracked engineering tool `debug_pose_landmark_viewer.py`
   was run on a real D455.
   - Baseline: manual capture (`b` key), 15 consecutive valid frames, coordinate-wise median,
     giving a fixed hip midpoint `H0` (and `S0`).
   - Live comparison:

     ```text
     SH_dynamic = (S(t) - H(t)) / D_sh(t)
     SH_fixed   = (S(t) - H0)   / D_sh(t)
     ```

   - The viewer displayed **different responses** between the dynamic and fixed hip methods
     during posture changes. No numeric series was recorded as evidence.

Implementation facts of that viewer (verified by reading its source in this task, static review only):

- All quantities are in **MediaPipe normalized image coordinates**; `D_sh(t)` is the Euclidean
  distance in normalized `(x, y)` units. Because normalized `x` and `y` are scaled by different
  image dimensions (e.g. 1280 vs 720), these ratios are **not numerically equivalent** to the
  F1-5 pixel-coordinate `sh_x`, `sh_y` (contract §2–§3).
- Live `H(t)` uses raw landmarks **without an in-frame requirement**
  (`_pair_midpoint`: "no in-frame requirement"), whereas F1-5 uses a hip only when Schema §F.4
  `*_hip_valid = true`. Baseline frames do require in-frame landmarks.
- No visibility/presence threshold is applied.

Therefore viewer outputs must **not** be reported as F1-5 values or as approved results.

---

## 4. Interpretation

### 4.1 INFERRED (plausible, untested)

- Original framing likely contributed to low SH availability in earlier data (hips below the image edge).
- In Body Forward, the hip midpoint moved ≈2× the shoulder midpoint in normalized `y` in the
  observed pair. Possible contributors, **not separable with this evidence**:
  - real anatomical pelvic motion / pelvic tilt while leaning;
  - perspective projection (the body moves toward a frontal camera, so lower body points move
    differently in the image);
  - framing (hips near the lower image edge);
  - MediaPipe estimation error under occlusion by the torso/desk/thighs (consistent with, but not
    proven by, the lower presence values).
- Because the forward hip midpoint (≈0.960) was close to the lower edge, a slightly larger lean,
  lower camera, or different subject could push hips out of frame, making `*_hip_valid = false`
  and SH unavailable **specifically in Body Forward**. This is a hypothesis about
  posture-dependent missingness, not a measured rate.
- A fixed hip reference changes what `sh_*` measures: it isolates shoulder motion relative to an
  earlier hip position rather than the current shoulder–hip relation.

### 4.2 NOT VERIFIED (must not be claimed)

- That MediaPipe hip landmarks are **incorrect** in Body Forward (no anatomical ground truth).
- That **Fixed-Hip is superior** to dynamic hip for classification or measurement quality.
- Any dataset-level SH / joint coverage rate under the new framing (no canonical recording analysed).
- Any repeatability, jitter, or distance dependence of hip landmarks (Patch 8 / `CAP-005` scope;
  formal execution deferred per `CAP-007`).
- Any visibility/presence threshold value; any `N_min`, `R_min`, or `D_sh` quality bound.
- That the preflight's 5/649 SH count is caused only by framing.
- Generalisation to other subjects, chairs, desks, clothing, or camera placements.

---

## 5. Status boundaries (unchanged by this document)

| Item | Status |
|---|---|
| F1-5 (`fs_x, fs_y, sh_x, sh_y, so_beta`), dynamic hip `H = (Lh + Rh)/2` from the same frame | **APPROVED** core calculation (`FEAT-009`) — unchanged |
| Hip input validity = Schema §F.4 `left_hip_valid` / `right_hip_valid` | Unchanged; no visibility/presence threshold added |
| Fixed-Hip (`H0` from earlier frames) | **Engineering candidate, NOT part of F1-5, NOT approved.** It uses a reference captured from previous frames, so it is a **calibration-based** candidate and is in tension with the `FEAT-002` calibration-free requirement for F1. Any adoption would need a separate researcher decision and Decision Log entry; it must not be labelled F1 or F1-5. |
| `OPEN-002` | Partially approved by `FEAT-009`; **DEFERRED** — not resolved |
| F1 full Design Freeze | **Not completed** |
| `CAP-005` / Patch 8 | Unchanged; these observations are **not** Patch 8 formal validation |
| `frames-schema/1.0.0` | Unchanged; hip midpoint is derived geometry, not a raw column (Schema §F.5) |

## 6. What would turn these observations into evidence

Recorded only as future evidence needs; nothing here is authorised or scheduled.

1. Canonical `frames-schema/1.0.0` recordings under the adjusted framing, analysed by the
   audited pipeline, with per-step FS/SH/SO/joint coverage and Schema §F invalid-reason counts.
2. Coverage broken down by posture step (`upright`, `forward_head`, `body_forward`, …) and by subject.
3. Repeated trials (not a single screenshot pair) to characterise hip displacement and variability.
4. Any measurement-quality claim must go through Patch 8 / `CAP-005` (formal execution currently deferred by `CAP-007`).
