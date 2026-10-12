# F1 PREFLIGHT Coverage — Engineering Audit (2026-10-12)

- **Document status:** `NON-FORMAL ENGINEERING COVERAGE AUDIT` — not a research decision, not Patch 8 validation, not formal data, not classification evidence
- **Gate:** Research Stage 1 Gate 1.9
- **Recorded on:** branch `feat/posture-integrated-v0`, HEAD `df3de85` (new files untracked, not committed)
- **Tools:** `f1_csv_adapter.py` (`f1-csv-adapter-prototype-gate1.9-unapproved`) → unchanged `f1_features.compute_f1_5_frame` (`FEAT-009`) → unchanged `f1_sample_aggregator.aggregate_f1_sample` (`f1-sample-aggregation-prototype-gate1.8-unapproved`); report produced by `f1_preflight_coverage.py`
- **Unchanged authority:** `FEAT-009` (core only), `OPEN-002` (partially approved, **DEFERRED**), `frames-schema/1.0.0` (`DATA-003`), `CAP-005` / `CAP-007`, F1 full Design Freeze (**not completed**). No Decision Log or Master entry is added.

The counts below are canonical-validity counts of **one** pilot recording captured with the **original** camera framing. They are not anatomical localisation accuracy, not measurement-quality evidence, not sample eligibility, and must not be used to choose thresholds or policies (Master: preflight is not threshold/protocol evidence).

---

## 1. Input CSV

| Item | Value |
|---|---|
| Path | `C:\Users\user\Downloads\AIoT-git\analysis\PREFLIGHT_r1_20261002_152053_246273_535d92550a4141dd89d6fc77165c3f92_frames.csv` |
| SHA-256 (before audit) | `b5bdcf7e22b6865848041744bc4cd02f58182fed50e04a628ca7d091693de142` |
| SHA-256 (after audit) | `b5bdcf7e22b6865848041744bc4cd02f58182fed50e04a628ca7d091693de142` (unchanged) |
| Size / rows | 477,694 bytes; 1 header + 649 data rows |
| Archived copy | `analysis\PREFLIGHT_r1_…\ar_20261002T071440140840Z_…\…_frames.csv` — same SHA-256 |

The file was only read. It was not copied, modified or re-selected; the CLI was given this explicit path with `--expected-sha256`.

## 2. Schema and identification

| Field | Value |
|---|---|
| Header | exact 60-field `frames-schema/1.0.0` order (`analyze_d455.FRAME_FIELDS`) |
| `frame_schema_version` | `frames-schema/1.0.0` (all rows) |
| `recording_id` | `PREFLIGHT_r1_20261002_152053_246273_535d92550a4141dd89d6fc77165c3f92` |
| `analysis_run_id` | `ar_20261002T071440140840Z_bafefc0c15b3494c9f919794e860f7e9` |
| `subject` / `round` | `PREFLIGHT` / `1` (engineering placeholder subject, not a participant ID) |
| steps (step → label) | 1 `upright`, 2 `forward_head`, 3 `upright`, 4 `body_forward`, 5 `upright` |
| Duplicate frame keys / identity conflicts / ragged rows | none (adapter fails closed on any of these) |

## 3. Provenance / manifest status

| Link | Status |
|---|---|
| `…_frames.csv.provenance.json` sidecar | present; `frames_sha256` matches the source |
| Sidecar → `analysis_manifest.json` | present; manifest SHA-256 `0d3f9255…729ef2` matches the sidecar |
| Manifest | `analysis-provenance/1.0.0`, `status: completed`, `analysis_mode: extract_raw`, `inference_performed: true`, `--step 1`; lists this CSV (name + SHA-256, `row_count` 649) as its `frames` output; `provenance_unknown_reasons: {}` |
| `dataset_role` / `protocol_version` | `pilot` / `capture-forward-face-v2.0.0` (from capture metadata and manifest) |
| Analysis code | `git_commit 872dfe65…`, `git_dirty false` |
| Raw inputs | DB3, camera, markers, quality sidecars hashed in the manifest and present locally (not re-hashed in this task) |
| **GAP — capture-side Git provenance** | capture metadata `git_commit: null`, `git_dirty: null` (`git rev-parse` failed: capture ran from an old ZIP folder, as recorded in the Master) |
| **GAP — model artifacts** | MediaPipe models recorded by SHA-256 but sourced from `/latest/` URLs with `version_identifier: null`; the manifest references no model-lock entry |
| **GAP — Patch 6 selection authority** | no `selection-event/1.0.0` or `dataset-selection-manifest/1.0.0` exists for this recording (searched `AIoT-git` data/analysis). The recording is not bound to any `(dataset_role, subject, round)` slot |

Conclusion: the frames CSV → analysis run → raw recording chain is unambiguous and hash-consistent. There is no dataset-selection chain, and capture-side code provenance is unknown. This is acceptable for an engineering coverage audit only. It is not research sample selection.

## 4. Whole-recording coverage

Frame-level families as defined by `FEAT-009` (contract §4–§5); joint = FS ∧ SH ∧ SO.

| n_frames | FS | SH | SO | joint |
|---:|---:|---:|---:|---:|
| 649 | 626 (96.46%) | 5 (0.77%) | 649 (100.00%) | 5 (0.77%) |

Invalid-reason distribution (frames carrying each reason; one frame may carry several):

- FS: `face_detected:false` × 23
- SH: `left_hip_valid:false` × 644, `right_hip_valid:false` × 643
- SO: none

`D_sh:zero`, non-finite geometry, `*:unknown` and `*_xy:missing` reasons did not occur.

## 5. Per-step and per-posture coverage

### 5.1 Per step

| step | label | n | FS | SH | SO | joint |
|---|---|---:|---:|---:|---:|---:|
| 1 | upright | 278 | 278 (100.00%) | 5 (1.80%) | 278 (100.00%) | 5 (1.80%) |
| 2 | forward_head | 128 | 105 (82.03%) | 0 (0.00%) | 128 (100.00%) | 0 (0.00%) |
| 3 | upright | 53 | 53 (100.00%) | 0 (0.00%) | 53 (100.00%) | 0 (0.00%) |
| 4 | body_forward | 128 | 128 (100.00%) | 0 (0.00%) | 128 (100.00%) | 0 (0.00%) |
| 5 | upright | 62 | 62 (100.00%) | 0 (0.00%) | 62 (100.00%) | 0 (0.00%) |

All 23 FS failures are in step 2 (`forward_head`, `face_detected:false`).

### 5.2 Per posture label (pooled frame counts, not averaged step percentages)

| label | steps | n | FS | SH | SO | joint |
|---|---|---:|---:|---:|---:|---:|
| upright | 1, 3, 5 | 393 | 393 (100.00%) | 5 (1.27%) | 393 (100.00%) | 5 (1.27%) |
| forward_head | 2 | 128 | 105 (82.03%) | 0 (0.00%) | 128 (100.00%) | 0 (0.00%) |
| body_forward | 4 | 128 | 128 (100.00%) | 0 (0.00%) | 128 (100.00%) | 0 (0.00%) |

No other labels occur in this recording.

## 6. Hip-related findings

| scope | n | L hip true/false/unknown | R hip true/false/unknown | both hips | both shoulders | SH ok | SH fail: hip only | SH fail: shoulder/other only | SH fail: both |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|
| recording | 649 | 5/644/0 | 6/643/0 | 5 | 649 | 5 | 644 | 0 | 0 |
| upright (1, 3, 5) | 393 | 5/388/0 | 6/387/0 | 5 | 393 | 5 | 388 | 0 | 0 |
| forward_head (2) | 128 | 0/128/0 | 0/128/0 | 0 | 128 | 0 | 128 | 0 | 0 |
| body_forward (4) | 128 | 0/128/0 | 0/128/0 | 0 | 128 | 0 | 128 | 0 | 0 |

Observed from the canonical data:

- `pose_detected = true` in all 649 frames. Hip invalidity is therefore not caused by a missing pose result. Under Schema §F.4 it means the hip landmark was non-finite or outside the normalized bounds `0 <= x, y < 1`. Invalid hip x/y are empty by contract, so the CSV cannot show which bound was crossed.
- All valid-hip frames are consecutive frames 101–106 in step 1 (`upright`; step 1 spans frame_index 80–357). Their hip `y_px` values are 704.95–719.73 on a 720-px-high colour image, i.e. within ~15 px of the bottom edge. Frame 103 has a valid right hip only.
- Every SH failure is hip-only. No shoulder was invalid and `D_sh > 0` held in every frame.

INFERRED (not verified frame-by-frame): the near-total hip invalidity is consistent with the hips lying at or below the lower image edge under the original framing, as reported in `F1_HIP_ENGINEERING_OBSERVATION_2026-10-12.md` §3.1. Because SH is ~0 in every posture, this recording **cannot** show posture-dependent hip missingness (for example, whether Body Forward loses hips more often than Upright). Canonical validity is not anatomical localisation accuracy.

## 7. Joint vs family aggregation

Sample key `(analysis_run_id, recording_id, step)`. The unchanged aggregator was run separately with `support="joint"` and `support="family"`. The values are engineering candidate outputs only. They are **not** model-eligible samples, and no N_min / R_min / threshold / imputation was applied.

| step | label | policy | n_used (fs_x, fs_y, sh_x, sh_y, so_beta) | defined | undefined (reason) | so_beta R |
|---|---|---|---|---|---|---:|
| 1 | upright | joint | 5, 5, 5, 5, 5 | all five | — | 0.9993 |
| 1 | upright | family | 278, 278, 5, 5, 278 | all five | — | 0.9993 |
| 2 | forward_head | joint | 0, 0, 0, 0, 0 | — | all five: `no_supported_frames:joint` | — |
| 2 | forward_head | family | 105, 105, 0, 0, 128 | fs_x, fs_y, so_beta | sh_x, sh_y: `no_supported_frames:SH` | 0.9941 |
| 3 | upright | joint | 0 × 5 | — | all five: `no_supported_frames:joint` | — |
| 3 | upright | family | 53, 53, 0, 0, 53 | fs_x, fs_y, so_beta | sh_x, sh_y: `no_supported_frames:SH` | 0.9997 |
| 4 | body_forward | joint | 0 × 5 | — | all five: `no_supported_frames:joint` | — |
| 4 | body_forward | family | 128, 128, 0, 0, 128 | fs_x, fs_y, so_beta | sh_x, sh_y: `no_supported_frames:SH` | 0.9993 |
| 5 | upright | joint | 0 × 5 | — | all five: `no_supported_frames:joint` | — |
| 5 | upright | family | 62, 62, 0, 0, 62 | fs_x, fs_y, so_beta | sh_x, sh_y: `no_supported_frames:SH` | 0.9998 |

- Under **joint** support, four of five steps have no defined feature. Hip invalidity removes the FS and SO information of those steps too, including all 128 `body_forward` and 128 `forward_head` frames.
- Under **family** support, FS and SO are defined in every step. SH is defined only in step 1, from 5 of 278 frames. In step 1 the family features therefore summarise different frame subsets (`defined_features_same_frames = False`): FS/SO use 278 frames and SH uses 5. For example, step 1 `so_beta` is −0.0091 rad under joint (5 frames) and −0.0280 rad under family (278 frames).
- These differences show the support-policy trade-off described in the Gate 1.7 review §C/§D.3. They do not select a policy.

## 8. Can a complete F1-5 engineering sample be constructed?

**Yes, exactly one:** step 1 (`upright`), under either policy, with all five features defined. SH-derived values come from only 5 consecutive frames (101–106) whose hips lie at the image bottom edge. No `forward_head` or `body_forward` sample has `sh_x` / `sh_y` under either policy. This recording therefore cannot provide a complete F1-5 sample for any non-upright posture, and cannot support any posture contrast that uses SH.

## 9. Integrity invariants

52 / 52 checks passed:

- `0 <= joint <= min(FS, SH, SO)` and every count `<= n_frames`, for the recording, each step and each label
- per-step and per-label totals reconcile with the recording, for n_frames, FS, SH, SO and joint
- each of the 649 frame keys appears in exactly one sample group
- aggregator counts and frame indices match the audit counts for every step and both policies
- SH outcome categories partition the frames, and `SH_available <= min(both hips, both shoulders)`

Cross-check against the previously reported reference observations (FS 626/649, SH 5/649, SO 649/649): **identical**. The earlier "joint ≤ 5/649" bound is met with equality (joint = 5). Nothing was forced, dropped or selected to reach these counts.

## 10. Limits of this evidence

- One engineering recording, one placeholder subject, one round, one take, `dataset_role = pilot`. This is not formal or IRB data and must not be relabelled as such.
- Original camera framing only. It says nothing about coverage under the adjusted framing; no coverage rate is inferred from screenshots.
- No claim of generalisation across subjects, chairs, clothing, desks or camera placements, and no general Body Forward failure rate.
- Canonical validity ≠ landmark accuracy. No anatomical ground truth exists, and visibility/presence were not used.
- Not Patch 8 / `CAP-005` validation. No D455 measurement-quality claim is made, and no D455 was operated in this task.
- No RF training, LOSO or classification evaluation, and no claim of RF readiness.
- Capture-side Git provenance is unknown, model artifacts were sourced from `/latest/` URLs, and there is no Patch 6 selection binding.
- `FEAT-009`, `OPEN-002`, Fixed-Hip status (separate, unapproved, calibration-based candidate) and all frozen contracts are unchanged.

## 11. Requirements for a new dataset with the improved framing (recorded needs, not authorisations)

1. Capture from a Git checkout so the capture metadata records `git_commit` / `git_dirty`, with the declared `dataset_role` and `protocol_version`, unchanged capture invariants, and model artifacts under the model lock.
2. Analyse with the current audited `analyze_d455.py`, producing `frames-schema/1.0.0` CSVs with sidecar and manifest.
3. If any recording is to serve as a research sample, bind it through Patch 6 selection events and a dataset-selection manifest. Do not select by coverage outcome.
4. Run `f1_preflight_coverage.py` with the explicit path and SHA-256 of each recording, and report per-step FS/SH/SO/joint coverage and hip diagnostics **per posture and per subject**.
5. Record the camera framing used (placement and aim) alongside each capture so that framing changes are traceable. Persisting new fields would need its own schema decision.
6. Use more than one subject and round before any support-policy, N_min, R_min, D_sh or visibility decision (`OPEN-002`, review §F). The new data must also be able to show whether Body Forward loses hips selectively, which this preflight cannot.
