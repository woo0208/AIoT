"""One fixed exploratory B0 vs B0+EARZ pilot run; no raw frames or tuning.

Run: python -X utf8 -B compare_earz_lr.py
Only the four aggregate summary files are suitable for public Git. Everything
under local_private/ (including models and benchmark traces) stays local.
Existing inputs and outputs are never overwritten.
"""
import os
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

import argparse
import csv
import gc
import itertools
import json
from pathlib import Path
import pickle
import platform
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import sklearn
from sklearn.base import clone
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_info, threadpool_limits

from earz_adapter import digest, read_json, unique_segments
from lr_posture_demo import DATA, DATA_SHA256, FEATURE_ORDER, fixed_lr, pilot_data
import engineering_exports as exports
from model_benchmark import run_benchmark
from probe_timing import _stats
import performance_output as perf

ROOT = Path(__file__).resolve().parent
EXPERIMENT = "EXPLR-H9-EARZ-LR-20261106"
EARZ = ROOT / "analysis/EXPLR-H9-EARZ-20261106/verified"
NAMES = ("B0_ORIGINAL", "B1_ADD_EARZ")
WARMUP, CALLS = 24, 120


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def load_joined():
    data, base, y = pilot_data()  # Existing pinned original 24 aggregates.
    report = read_json(EARZ / "results.json")
    with (EARZ / "segments.csv").open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = unique_segments(list(csv.DictReader(stream)))
    rows = unique_segments(report["segments"])
    keys = [(str(subject), str(key[1]), str(key[2]))
            for subject, key in zip(data["subjects"], data["sample_keys"])]
    require(len(keys) == len(set(keys)) == 24 and set(keys) == set(rows) == set(csv_rows),
            "EARZ JSON/CSV and H9 segment identity mismatch")
    require(report["experiment_id"] == "EXPLR-H9-EARZ-20261106"
            and report["segment_count"] == report["valid_segment_count"] == 24
            and report["identity_and_saved_h9_aggregates_match"], "unverified EARZ source")
    require([i["sha256"] for i in report["inputs"] if i["name"] == DATA.name] == [DATA_SHA256],
            "EARZ source H9 hash mismatch")
    values = []
    for key in keys:  # Identity lookup, never positional zip with EARZ values.
        row, saved = rows[key], csv_rows[key]
        require(row["valid"] is True and saved["valid"] == "True"
                and not row["failure_reasons"], "invalid EARZ segment")
        require(row["h9_common_frame_indices"] == row["earz_valid_frame_indices"]
                and row["h9_common_support_count"] == row["earz_valid_count"]
                == len(row["earz_valid_frame_indices"]), "EARZ saved support mismatch")
        require(float(saved["earz_median"]) == row["earz_median"], "EARZ CSV/JSON median mismatch")
        values.append(row["earz_median"])
    require(sum(rows[k]["earz_valid_count"] for k in keys) == 3613, "saved support total mismatch")
    added = np.column_stack((base, values))
    require(added.shape == (24, 9) and np.isfinite(added).all(), "nonfinite features")
    return data, keys, {NAMES[0]: base, NAMES[1]: added}, y


def score(y, pred):
    cm = confusion_matrix(y, pred, labels=range(6))
    require(cm.sum() == 24 and cm.sum(1).tolist() == [4] * 6, "wrong evaluated support")
    return dict(accuracy_pct=float(100 * np.trace(cm) / 24),
                macro_f1_pct=float(100 * f1_score(y, pred, labels=range(6), average="macro", zero_division=0)),
                recall_pct=(100 * np.diag(cm) / cm.sum(1)).tolist(),
                correct=int(np.trace(cm)), confusion_matrix=cm.tolist())


def run(output):
    inputs = (DATA, EARZ / "results.json", EARZ / "segments.csv")
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    data, keys, matrices, y = load_joined()
    template = fixed_lr()  # Reuse original factory; source parsing outside timers.
    require(clone(template).get_params() == template.get_params(), "LR settings changed")
    output.mkdir(exist_ok=False)
    private = output / "local_private"
    private.mkdir()
    people = np.asarray(data["subjects"])
    predictions = {name: np.full(24, -1, dtype=int) for name in NAMES}
    records = []
    environment = dict(perf.environment(), sklearn=sklearn.__version__, numpy=np.__version__,
                       cpu=platform.processor(), desktop_load="uncontrolled")
    git = perf.git_identity()
    with threadpool_limits(limits=1):
        environment["threadpools"] = threadpool_info()
        # Both solvers/scalers receive an untimed initialization on training data.
        warm_train = np.flatnonzero(people == "P01")
        for name in NAMES:
            scaler = StandardScaler().fit(matrices[name][warm_train])
            clone(template).fit(scaler.transform(matrices[name][warm_train]), y[warm_train])
        for fold, heldout in enumerate(("P02", "P01"), 1):
            train, test = np.flatnonzero(people != heldout), np.flatnonzero(people == heldout)
            require(len(train) == len(test) == 12 and not set(train) & set(test)
                    and set(train) | set(test) == set(range(24)), "invalid LOSO split")
            order = NAMES if fold == 1 else NAMES[::-1]
            for name in order:
                X = matrices[name]
                start = time.perf_counter_ns()
                model = clone(template)
                scaler = StandardScaler().fit(X[train])
                model.fit(scaler.transform(X[train]), y[train])
                training_ns = time.perf_counter_ns() - start
                require(int(scaler.n_samples_seen_) == 12, "scaler saw validation rows")
                np.testing.assert_allclose(scaler.mean_, X[train].mean(0), rtol=0, atol=1e-14)
                require(np.all(model.n_iter_ < model.max_iter), "LR did not converge")
                pred = model.predict(scaler.transform(X[test]))
                predictions[name][test] = pred
                # Identical, minimal serialization: actual classifier+scaler, no metadata.
                path = private / f"fold{fold}_{name}.pkl"
                with path.open("xb") as stream:
                    pickle.dump((model, scaler), stream, protocol=5)
                with path.open("rb") as stream:
                    restored, restored_scaler = pickle.load(stream)
                np.testing.assert_array_equal(restored.predict(restored_scaler.transform(X[test])), pred)
                record = dict(method=name, fold=fold, train_indices=train.tolist(), test_indices=test.tolist(),
                              training_ns=training_ns, model_bytes=path.stat().st_size, raw_ns={})
                rows = [np.ascontiguousarray(X[i:i+1]) for i in test]
                transformed = [scaler.transform(row) for row in rows]
                identity = dict(scope="NON_FORMAL_ENGINEERING", run_id=EXPERIMENT,
                    data_id="reused_24_segment_pilot", model_id=name, config_id="fixed_lr_b0_plus_earz",
                    config_sha256=exports.digest(template.get_params()), git=git, environment=environment)
                enabled = gc.isenabled()
                gc.disable()
                try:
                    for operation, values, callback in (
                        ("classifier", transformed, lambda m, iterator: m.predict(next(iterator))),
                        ("pipeline", rows, lambda m, iterator: m.predict(scaler.transform(next(iterator))))):
                        result = run_benchmark(private / f"fold{fold}_{name}_{operation}",
                            identity=identity, input_value=itertools.cycle(values), input_id=f"fold{fold}_heldout12",
                            input_sha256=exports.digest(hashes), feature_order=list(FEATURE_ORDER) + (["EARZ"] if X.shape[1] == 9 else []),
                            seed=0, model=model, predict=callback, model_path=path, calls=CALLS, warmup_calls=WARMUP)
                        record["raw_ns"][operation] = result["raw_inference_ns"]
                finally:
                    if enabled:
                        gc.enable()
                records.append(record)
    scores = {name: score(y, predictions[name]) for name in NAMES}
    b0 = scores[NAMES[0]]
    require(b0["correct"] == 21 and b0["accuracy_pct"] == 87.5
            and round(b0["macro_f1_pct"], 2) == 86.84
            and b0["recall_pct"] == [50, 75, 100, 100, 100, 100], "B0 reference not reproduced")
    changed = []
    for i, key in enumerate(keys):
        if predictions[NAMES[0]][i] != predictions[NAMES[1]][i]:
            changed.append(dict(subject=key[0], recording_id=key[1], segment_id=key[2],
                true_label=int(y[i]), b0=int(predictions[NAMES[0]][i]), b1=int(predictions[NAMES[1]][i])))
    summary = []
    for name in NAMES:
        own = [r for r in records if r["method"] == name]
        times = {op: [t for r in own for t in r["raw_ns"][op]] for op in ("classifier", "pipeline")}
        row = dict(method=name, features=matrices[name].shape[1], samples=24,
                   accuracy_pct=scores[name]["accuracy_pct"], macro_f1_pct=scores[name]["macro_f1_pct"],
                   correct=scores[name]["correct"])
        row.update({f"P{i}_recall_pct": v for i, v in enumerate(scores[name]["recall_pct"])})
        row.update(delta_accuracy_pp=row["accuracy_pct"] - b0["accuracy_pct"],
                   delta_macro_f1_pp=row["macro_f1_pct"] - b0["macro_f1_pct"],
                   training_mean_ms=float(np.mean([r["training_ns"] for r in own]) / 1e6),
                   model_bytes_mean=float(np.mean([r["model_bytes"] for r in own])),
                   earz_compute_cost="NOT_MEASURED")
        for op in times:
            require(len(times[op]) == 2 * CALLS, "unequal inference call count")
            stats = _stats([t / 1e6 for t in times[op]])
            row.update({f"{op}_p{p}_ms": stats[f"p{p}"] for p in (50, 95)})
            row[f"{op}_predictions_per_second"] = len(times[op]) * 1e9 / sum(times[op])
        require(all(np.isfinite(v) for v in row.values() if isinstance(v, (int, float))), "nonfinite metrics")
        summary.append(row)
    require(hashes == {str(p.relative_to(ROOT)): digest(p) for p in inputs}, "inputs changed")
    write_json(private / "results.json", dict(experiment_id=EXPERIMENT, inputs=hashes,
        environment=environment, git=git, lr_params=template.get_params(), records=records, scores=scores,
        predictions={name: p.tolist() for name, p in predictions.items()}, labels=y.tolist(),
        identities=keys, changes=changed, summary=summary))
    exports.csv_write(output / "comparison.csv", list(summary[0]), summary)
    # Read back persisted metrics and independently recompute from confusion counts.
    with (output / "comparison.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            cm = np.asarray(scores[row["method"]]["confusion_matrix"])
            np.testing.assert_allclose(float(row["accuracy_pct"]), 100 * np.trace(cm) / cm.sum())
            np.testing.assert_allclose(float(row["macro_f1_pct"]), np.mean(200 * np.diag(cm) / (cm.sum(0) + cm.sum(1))))
            for i in range(6):
                np.testing.assert_allclose(float(row[f"P{i}_recall_pct"]), 100 * cm[i, i] / cm[i].sum())
    report_and_plots(output, summary, scores, changed, environment)
    write_json(private / "validation.json", dict(status="PASS", identity_join=24, equal_loso_splits=True,
        scaler_training_only=True, b0_reproduced=True, saved_metrics_match_confusion=True, finite_metrics=True,
        input_hashes_unchanged=True, warmup_calls_per_fold_operation=WARMUP, calls_per_fold_operation=CALLS))
    print(json.dumps(dict(status="PASS", summary=summary, changed_count=len(changed)), allow_nan=False))


def report_and_plots(output, summary, scores, changed, environment):
    lines = [f"# {EXPERIMENT}", "", "Exploratory only: repeatedly explored two-person, 24-segment pilot; not independent generalization evidence.",
        "B1_ADD_EARZ = F1-F8 + verified segment-median EARZ (9 features). Distinct from the historical personal-P0-calibrated B1 and C3-added B1.",
        "No calibration, F9/C3, feature removal, hyperparameter tuning or first-P0 exclusion. No formal model selection.", "",
        "Both methods evaluated anew: P01 train12/P02 test12, then P02 train12/P01 test12. Scaler fits training12 only.",
        "EARZ joined by subject/recording_id/segment_id; saved JSON and CSV agree. 3,613 support frames remain 24 segment samples.",
        "Original fixed LR factory reused: C=1, l1_ratio=0, lbfgs, tol=1e-4, intercept=True, class_weight=None, max_iter=10000, random_state=0.", "",
        "| Method | Accuracy % | Macro-F1 % | P0 Recall % | P1 Recall % | P5 Recall % | ΔAccuracy pp | ΔMacro-F1 pp | Correct |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary:
        lines.append(f"| {r['method']} | {r['accuracy_pct']:.2f} | {r['macro_f1_pct']:.2f} | {r['P0_recall_pct']:.2f} | {r['P1_recall_pct']:.2f} | {r['P5_recall_pct']:.2f} | {r['delta_accuracy_pp']:+.2f} | {r['delta_macro_f1_pp']:+.2f} | {r['correct']}/24 |")
    lines += ["", "| Method | Train mean ms | Pipeline p50 ms | Pipeline p95 ms | Pipeline predictions/sec | Model bytes mean | LR-only p50 ms | LR-only p95 ms |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary:
        lines.append(f"| {r['method']} | {r['training_mean_ms']:.4f} | {r['pipeline_p50_ms']:.4f} | {r['pipeline_p95_ms']:.4f} | {r['pipeline_predictions_per_second']:.0f} | {r['model_bytes_mean']:.0f} | {r['classifier_p50_ms']:.4f} | {r['classifier_p95_ms']:.4f} |")
    lines += ["", "Training mean = two observed LOSO fits (constructor + scaler fit/transform + LR fit, excluding I/O/evaluation). Both receive untimed training initialization.",
        f"Existing model_benchmark.run_benchmark: {WARMUP} untimed warmups + {CALLS} timed single-row predict calls per fold and operation; same 12 heldout rows cycled. Two folds pooled (240 timings/method/operation).",
        "B0/B1 block order reversed in fold2; one process, one native thread, GC disabled during inference. Timing is descriptive; desktop load uncontrolled, no significance/robust speedup claim.",
        "Throughput = number of timed calls / summed timed callback durations (iterator selection included); not sustained camera throughput or D455 FPS.",
        "Model bytes = actual uncompressed protocol5 pickle of (classifier, scaler), mean of two fold files; no metadata, dependencies or deployment training.",
        "EARZ extraction/aggregation cost: NOT_MEASURED (saved medians reused; no separate existing EARZ timing callback). No MediaPipe/D455 run. Approx. 15 D455 FPS is separate, unmeasured context.",
        "Existing tool records same-process memory snapshots locally; they do not isolate model memory. CPU operation cost: NOT_MEASURED.",
        f"Environment: Python {environment['python']}; sklearn {environment['sklearn']}; NumPy {environment['numpy']}; {environment['platform']}; {environment['cpu']}.", "",
        "| Method | P0 | P1 | P2 | P3 | P4 | P5 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name in NAMES:
        lines.append("| " + name + " | " + " | ".join(f"{v:.2f}%" for v in scores[name]["recall_pct"]) + " |")
    for name in NAMES:
        lines += ["", f"{name} confusion matrix: rows=true, columns=predicted; P0..P5.", "```text",
                  *[" ".join(map(str, row)) for row in scores[name]["confusion_matrix"]], "```", ""]
    fixed = [c for c in changed if c["b0"] != c["true_label"] and c["b1"] == c["true_label"]]
    broken = [c for c in changed if c["b0"] == c["true_label"] and c["b1"] != c["true_label"]]
    lines += [f"Changed predictions: {len(changed)}; error→correct {len(fixed)}; correct→error {len(broken)}."]
    for kind, cases in (("Error→correct", fixed), ("Correct→error", broken)):
        counts = {}
        for c in cases:
            key = f"true P{c['true_label']}: P{c['b0']}→P{c['b1']}"
            counts[key] = counts.get(key, 0) + 1
        lines += [f"{kind}: {counts or 'none'}."]
    b0, b1 = summary
    lines += ["", f"Q1 Accuracy change: {b1['delta_accuracy_pp']:+.2f} pp. Q2 Macro-F1 change: {b1['delta_macro_f1_pp']:+.2f} pp.",
        f"Q3 P0/P1 Recall changes: {b1['P0_recall_pct']-b0['P0_recall_pct']:+.2f}/{b1['P1_recall_pct']-b0['P1_recall_pct']:+.2f} pp.",
        "Q4 Other recall changes (pp): " + ", ".join(f"P{i}={b1[f'P{i}_recall_pct']-b0[f'P{i}_recall_pct']:+.2f}" for i in range(2, 6)) + ".",
        f"Q5 Pipeline p50/p95 changes: {b1['pipeline_p50_ms']-b0['pipeline_p50_ms']:+.4f}/{b1['pipeline_p95_ms']-b0['pipeline_p95_ms']:+.4f} ms; throughput change {b1['pipeline_predictions_per_second']/b0['pipeline_predictions_per_second']*100-100:+.2f}%; model size change {b1['model_bytes_mean']-b0['model_bytes_mean']:+.0f} bytes.",
        "Q6 " + ("EARZ can remain an exploratory candidate based on the observed Macro-F1 gain; independent validation is still required." if b1['macro_f1_pct'] > b0['macro_f1_pct'] else "This run provides no overall Macro-F1 improvement supporting EARZ adoption; retain B0 as the baseline."),
        "No further tuning or feature search performed. Participant identities, EARZ values, fold predictions, models and raw timing evidence remain in local_private/ and are excluded from Git.",
        "Minimum validation PASS: 24-key join, common splits, training-only scaler, B0 reproduction, saved CSV/CM consistency, finite numbers, unchanged input hashes."]
    with (output / "EARZ_LR_COMPARISON.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    for filename, labels, values in (
        ("accuracy_macro_f1.png", ["Accuracy", "Macro-F1"], [[r['accuracy_pct'], r['macro_f1_pct']] for r in summary]),
        ("recall_comparison.png", [f"P{i}" for i in range(6)], [scores[n]['recall_pct'] for n in NAMES])):
        values = list(values)
        fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
        x = np.arange(len(labels))
        for i, name in enumerate(NAMES):
            bars = ax.bar(x + (i - .5) * .36, values[i], .36, label=name)
            ax.bar_label(bars, fmt="%.1f", padding=3)
        ax.set(xticks=x, xticklabels=labels, ylim=(0, 116), ylabel="Percent (%)",
               title="Exploratory two-person LOSO | 24 segments")
        ax.legend(loc="upper center", ncols=2, fontsize=8)
        fig.savefig(output / filename, dpi=160)
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "analysis" / EXPERIMENT)
    run(parser.parse_args().output_dir)
