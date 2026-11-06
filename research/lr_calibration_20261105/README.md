# Historical LR pilot checkpoint

Preserved on 2026-11-06 from existing saved results. No new training,
prediction, camera operation or research-data processing was performed for
this checkpoint. These are exploratory two-person pilot results, not formal
or independent validation. The official eight combinations, B6 selection
rules and IRB HOLD remain unchanged.

| Historical experiment | n | Method | Accuracy % | Macro-F1 % | P0/P1/P5 Recall % |
|---|---:|---|---:|---:|---|
| 2026-11-05 calibration | 22 | B0: F1..F8 | 81.82 | 77.04 | 50/25/100 |
| 2026-11-05 calibration | 22 | B1: own fixed first-P0 differences | 72.73 | 62.76 | 0/100/50 |
| 2026-11-05 calibration | 22 | B2: B1 + C3 difference | 72.73 | 62.76 | 0/100/50 |
| 2026-11-06 C3 | 24 | B0_ORIGINAL: F1..F8 | 87.50 | 86.84 | 50/75/100 |
| 2026-11-06 C3 | 24 | B1_ADD_C3: F1..F8 + C3 | 83.33 | 82.01 | 50/50/100 |
| 2026-11-06 C3 | 24 | B2_REPLACE_F6_WITH_C3 | 79.17 | 76.67 | 25/50/100 |

The 22-segment experiment excludes both first-P0 references from train/test;
each LOSO fold has 11/11 samples. B1 subtracts the participant's fixed first
P0; F3 uses a directed angle difference in [-180,180). B2 adds the corresponding
C3 difference. The 24-segment experiment uses no personal calibration or
reference exclusion and has 12/12 samples per fold. Its B1/B2 IDs denote
different methods. Do not compare these two sample populations as if they
were the same experiment. Neither experiment supported replacing B0.

C3 is the existing camera-coordinate sagittal torso proxy:
`degrees(atan2(hip_z - shoulder_z, hip_y - shoulder_y))`.
Both experiments used the existing fixed LR constructor (C=1, L2, lbfgs,
tol=1e-4, max_iter=10000, intercept, no class weights, random_state=0), with
StandardScaler fit on the training fold only. No tuning was performed.

CSV/JSON files contain pooled metrics, confusion matrices and process-level
cost summaries. PNGs are unchanged saved aggregate charts. Training and
inference timings describe the historical benchmark on Windows/i7-14700,
Python 3.12.10, NumPy 2.5.3 and scikit-learn 1.9.1, with one BLAS/OpenMP
thread. Feature extraction, original C3 calculation and full D455 FPS were
not measured. The calibration benchmark used three sequential processes;
the C3 comparison used one. Timings are not new measurements.

`measure.py` is a source snapshot of the existing calibration experiment.
Only one literal report paragraph containing recording/reference identities
was replaced with a generic statement. All other AST nodes, including every
computational function, are identical to the local source. The original
source and outputs remain untouched. `test_experiment.py` is an unchanged
synthetic structural test file. C3's original execution source was not present
among its four saved artifacts; no replacement algorithm was invented.

`checkpoint_manifest.json` records original and exported SHA-256 hashes.
Participant-level inputs, OOF predictions, recording/reference mappings,
scaler statistics, models and raw timing logs are intentionally excluded.
The snapshot requires the original access-controlled inputs and historical
factory dependencies; this public checkpoint alone cannot rerun the full
experiment and does not authorize execution. The source's old execution
authorization text describes its historical task only.

Structural verification without datasets or training:
`python -B -m unittest discover -s research/lr_calibration_20261105 -p test_experiment.py`.
Pooled CSV/JSON metrics and confusion matrices were checked arithmetically
against the saved results when exporting; this is not a new model evaluation.
