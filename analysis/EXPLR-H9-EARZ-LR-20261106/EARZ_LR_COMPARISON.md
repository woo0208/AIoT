# EXPLR-H9-EARZ-LR-20261106

Exploratory only: repeatedly explored two-person, 24-segment pilot; not independent generalization evidence.
B1_ADD_EARZ = F1-F8 + verified segment-median EARZ (9 features). Distinct from the historical personal-P0-calibrated B1 and C3-added B1.
No calibration, F9/C3, feature removal, hyperparameter tuning or first-P0 exclusion. No formal model selection.

Both methods evaluated anew: P01 train12/P02 test12, then P02 train12/P01 test12. Scaler fits training12 only.
EARZ joined by subject/recording_id/segment_id; saved JSON and CSV agree. 3,613 support frames remain 24 segment samples.
Original fixed LR factory reused: C=1, l1_ratio=0, lbfgs, tol=1e-4, intercept=True, class_weight=None, max_iter=10000, random_state=0.

| Method | Accuracy % | Macro-F1 % | P0 Recall % | P1 Recall % | P5 Recall % | ΔAccuracy pp | ΔMacro-F1 pp | Correct |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_ORIGINAL | 87.50 | 86.84 | 50.00 | 75.00 | 100.00 | +0.00 | +0.00 | 21/24 |
| B1_ADD_EARZ | 83.33 | 81.48 | 25.00 | 75.00 | 100.00 | -4.17 | -5.36 | 20/24 |

| Method | Train mean ms | Pipeline p50 ms | Pipeline p95 ms | Pipeline predictions/sec | Model bytes mean | LR-only p50 ms | LR-only p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0_ORIGINAL | 2.1376 | 0.1074 | 0.1211 | 9048 | 1588 | 0.0576 | 0.0633 |
| B1_ADD_EARZ | 2.2679 | 0.1087 | 0.1691 | 8470 | 1660 | 0.0576 | 0.0639 |

Training mean = two observed LOSO fits (constructor + scaler fit/transform + LR fit, excluding I/O/evaluation). Both receive untimed training initialization.
Existing model_benchmark.run_benchmark: 24 untimed warmups + 120 timed single-row predict calls per fold and operation; same 12 heldout rows cycled. Two folds pooled (240 timings/method/operation).
B0/B1 block order reversed in fold2; one process, one native thread, GC disabled during inference. Timing is descriptive; desktop load uncontrolled, no significance/robust speedup claim.
Throughput = number of timed calls / summed timed callback durations (iterator selection included); not sustained camera throughput or D455 FPS.
Model bytes = actual uncompressed protocol5 pickle of (classifier, scaler), mean of two fold files; no metadata, dependencies or deployment training.
EARZ extraction/aggregation cost: NOT_MEASURED (saved medians reused; no separate existing EARZ timing callback). No MediaPipe/D455 run. Approx. 15 D455 FPS is separate, unmeasured context.
Existing tool records same-process memory snapshots locally; they do not isolate model memory. CPU operation cost: NOT_MEASURED.
Environment: Python 3.12.10; sklearn 1.9.1; NumPy 2.5.3; Windows-11-10.0.22631-SP0; Intel64 Family 6 Model 183 Stepping 1, GenuineIntel.

| Method | P0 | P1 | P2 | P3 | P4 | P5 |
|---|---:|---:|---:|---:|---:|---:|
| B0_ORIGINAL | 50.00% | 75.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| B1_ADD_EARZ | 25.00% | 75.00% | 100.00% | 100.00% | 100.00% | 100.00% |

B0_ORIGINAL confusion matrix: rows=true, columns=predicted; P0..P5.
```text
2 1 1 0 0 0
1 3 0 0 0 0
0 0 4 0 0 0
0 0 0 4 0 0
0 0 0 0 4 0
0 0 0 0 0 4
```


B1_ADD_EARZ confusion matrix: rows=true, columns=predicted; P0..P5.
```text
1 2 1 0 0 0
1 3 0 0 0 0
0 0 4 0 0 0
0 0 0 4 0 0
0 0 0 0 4 0
0 0 0 0 0 4
```

Changed predictions: 1; error→correct 0; correct→error 1.
Error→correct: none.
Correct→error: {'true P0: P0→P1': 1}.

Q1 Accuracy change: -4.17 pp. Q2 Macro-F1 change: -5.36 pp.
Q3 P0/P1 Recall changes: -25.00/+0.00 pp.
Q4 Other recall changes (pp): P2=+0.00, P3=+0.00, P4=+0.00, P5=+0.00.
Q5 Pipeline p50/p95 changes: +0.0013/+0.0479 ms; throughput change -6.39%; model size change +72 bytes.
Q6 This run provides no overall Macro-F1 improvement supporting EARZ adoption; retain B0 as the baseline.
No further tuning or feature search performed. Participant identities, EARZ values, fold predictions, models and raw timing evidence remain in local_private/ and are excluded from Git.
Minimum validation PASS: 24-key join, common splits, training-only scaler, B0 reproduction, saved CSV/CM consistency, finite numbers, unchanged input hashes.

Execution baseline: e1ba0ffa0a5a9d3375430c47e21e1467c3b8a872; branch experiment/lr-feature-b1-b2.
Related tests actually run: python -X utf8 -B -m unittest -q test_earz_adapter test_model_benchmark — 13 tests PASS (synthetic structural tests, separate from measured pilot results).
