"""Teammate H5/H9 feature ablation (guide tasks A-1, A-2, B) — M0 only.

Exploratory pilot analysis on P01/P02.  Existing code is imported, never
modified: samples come from ``h6_offline.load_labeled_probe_h_samples`` and the
model is ``rf_experiment.Forest`` with the same arguments ``rf.fit_models``
uses for M0.  Every condition uses the same 24 H9-eligible segments; removing a
feature only drops a column and retrains from scratch.

Usage (from the repository root):

    python -B analysis/teammate_feature_ablation_20261029/ablation.py \
        --task A-1 --probe-csv <P01 csv> <P02 csv> \
        --baseline-json pilot/h6_pilot_20261024_174708.json
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

import rf_experiment as rf  # noqa: E402
from f1_sample_aggregator import H9_FEATURE_NAMES  # noqa: E402
from h6_offline import LAB6, POSTURE_IDS, analysis_label, load_labeled_probe_h_samples  # noqa: E402

FEATURE_IDS = tuple(f"F{i}" for i in range(1, 10))
TASKS = {
    "A-1": "A-1_depth_add_one",
    "A-2": "A-2_depth_drop_one",
    "B": "B_h5_drop_one",
}
CODE_FILES = ("h6_offline.py", "rf_experiment.py", "f1_sample_aggregator.py",
              "posture_geometry_probe.py")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_fixed_samples(csv_paths):
    """Return the fixed H9-eligible sample set in h6_offline's order.

    Mirrors h6_offline.evaluate_samples: drop non-evaluation labels, keep only
    jointly eligible samples, keep the loader's sorted order.
    """
    samples = [s for s in load_labeled_probe_h_samples(csv_paths) if s.eligible]
    keys = [list(s.sample_key) for s in samples]
    if len({tuple(k) for k in keys}) != len(keys):
        raise ValueError("duplicate sample keys")
    X = np.array([s.ordered_values("H9") for s in samples], dtype=float)
    y = np.array([LAB6.index(analysis_label(s.label)) for s in samples], dtype=int)
    participants = np.array([s.subject for s in samples])
    if X.shape != (len(y), 9) or not np.isfinite(X).all():
        raise ValueError("expected a finite (n, 9) H9 matrix")
    return X, y, participants, keys


def select_columns(X, feature_ids):
    """Select F-columns keeping the H9 column order; reject bad requests."""
    if not feature_ids or len(set(feature_ids)) != len(feature_ids):
        raise ValueError(f"empty or duplicate feature list: {feature_ids}")
    unknown = [f for f in feature_ids if f not in FEATURE_IDS]
    if unknown:
        raise ValueError(f"unknown feature ids: {unknown}")
    idx = [FEATURE_IDS.index(f) for f in feature_ids]
    if idx != sorted(idx):
        raise ValueError(f"feature ids must follow F1..F9 order: {feature_ids}")
    return X[:, idx]


def loso_m0(X, y, participants, seeds, n_trees, max_features):
    """Participant-level LOSO, M0 retrained per fold.  Returns predictions per seed."""
    subjects = sorted(set(participants))
    if len(subjects) < 2:
        raise ValueError("LOSO requires at least two participants")
    preds, folds = [], []
    for seed in seeds:
        pred = np.full(len(y), -1, dtype=int)
        for subject in subjects:
            test = participants == subject
            train = ~test
            if set(y[train]) != set(range(len(LAB6))):
                raise ValueError(f"training fold without all classes: held_out={subject}")
            model = rf.Forest(len(LAB6), n_trees, max_features, None, seed).fit(X[train], y[train])
            pred[test] = model.predict(X[test])
            folds.append(dict(seed=seed, held_out_participant=subject,
                              training_participants=sorted(set(participants[train])),
                              train_indices=np.flatnonzero(train).tolist(),
                              test_indices=np.flatnonzero(test).tolist()))
        if (pred < 0).any():
            raise ValueError("some samples were never predicted")
        preds.append(pred)
    return preds, folds


def confusion(y, p):
    cm = np.zeros((len(LAB6), len(LAB6)), dtype=int)
    np.add.at(cm, (y, p), 1)
    return cm


def scores(y, p):
    """Accuracy, macro-F1 (rf.macro_f1) and per-class P/R/F1 for one prediction."""
    cm = confusion(y, p)
    support = cm.sum(1)
    predicted = cm.sum(0)
    tp = np.diag(cm)
    precision = np.divide(tp, predicted, out=np.zeros(len(LAB6)), where=predicted > 0)
    recall = np.divide(tp, support, out=np.full(len(LAB6), np.nan), where=support > 0)
    denom = precision + recall
    f1 = np.divide(2 * precision * recall, denom, out=np.zeros(len(LAB6)), where=denom > 0)
    per_class = {
        POSTURE_IDS[k]: dict(label=LAB6[k], support=int(support[k]), predicted=int(predicted[k]),
                             precision=float(precision[k]),
                             recall=None if support[k] == 0 else float(recall[k]),
                             f1=None if support[k] == 0 else float(f1[k]))
        for k in range(len(LAB6))
    }
    return dict(accuracy=float(np.mean(p == y)), macro_f1=rf.macro_f1(y, p, len(LAB6)),
                per_class=per_class, confusion_matrix=cm.tolist(),
                p1_to_p0=int(cm[1, 0]), p1_to_p5=int(cm[1, 5]))


def _mean(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def summarize(per_seed):
    """Mean over seeds (seeds are computational repeats, not new samples)."""
    acc = [s["accuracy"] for s in per_seed]
    f1 = [s["macro_f1"] for s in per_seed]
    per_class = {
        pid: {m: _mean([s["per_class"][pid][m] for s in per_seed])
              for m in ("precision", "recall", "f1")}
        for pid in POSTURE_IDS
    }
    cms = np.array([s["confusion_matrix"] for s in per_seed])
    return dict(accuracy=float(np.mean(acc)), accuracy_seed_sd=float(np.std(acc)),
                macro_f1=float(np.mean(f1)), macro_f1_seed_sd=float(np.std(f1)),
                per_class=per_class,
                p1_to_p0_mean=float(np.mean([s["p1_to_p0"] for s in per_seed])),
                p1_to_p5_mean=float(np.mean([s["p1_to_p5"] for s in per_seed])),
                confusion_matrix_sum_over_seeds=cms.sum(0).tolist())


def evaluate_condition(X, y, participants, feature_ids, seeds, n_trees, max_features):
    preds, folds = loso_m0(select_columns(X, feature_ids), y, participants,
                           seeds, n_trees, max_features)
    pooled = [dict(seed=seed, **scores(y, p)) for seed, p in zip(seeds, preds)]
    by_participant = {}
    for subject in sorted(set(participants)):
        mask = participants == subject
        rows = [dict(seed=seed, **scores(y[mask], p[mask])) for seed, p in zip(seeds, preds)]
        by_participant[subject] = dict(summary=summarize(rows), per_seed=rows)
    return dict(feature_ids=list(feature_ids),
                feature_names=[H9_FEATURE_NAMES[FEATURE_IDS.index(f)] for f in feature_ids],
                pooled=dict(summary=summarize(pooled), per_seed=pooled),
                by_participant=by_participant,
                predictions_per_seed=[p.tolist() for p in preds],
                folds=folds)


def delta_pp(condition, baseline):
    """Condition minus baseline in percentage points (pooled and per participant)."""
    def diff(a, b):
        out = dict(accuracy=100 * (a["accuracy"] - b["accuracy"]),
                   macro_f1=100 * (a["macro_f1"] - b["macro_f1"]))
        for pid in POSTURE_IDS:
            for m in ("precision", "recall"):
                va, vb = a["per_class"][pid][m], b["per_class"][pid][m]
                out[f"{pid}_{m}"] = None if va is None or vb is None else 100 * (va - vb)
        out["p1_to_p0_mean"] = a["p1_to_p0_mean"] - b["p1_to_p0_mean"]
        out["p1_to_p5_mean"] = a["p1_to_p5_mean"] - b["p1_to_p5_mean"]
        return out
    return dict(unit="percentage points (counts for p1_to_* )",
                pooled=diff(condition["pooled"]["summary"], baseline["pooled"]["summary"]),
                by_participant={s: diff(condition["by_participant"][s]["summary"],
                                        baseline["by_participant"][s]["summary"])
                                for s in condition["by_participant"]})


def check_against_stored_baseline(result, stored, feature_set, keys):
    """The rerun baseline must equal the stored h6_pilot M0 result exactly."""
    metric = next(m for m in stored["metrics"]
                  if m["feature_set"] == feature_set and m["model"] == "M0")
    rerun_cms = [s["confusion_matrix"] for s in result["pooled"]["per_seed"]]
    summary = result["pooled"]["summary"]
    checks = dict(
        sample_keys_identical=keys == stored["eligible_sample_keys"],
        confusion_matrices_identical=rerun_cms == metric["confusion_matrices"],
        accuracy_identical=summary["accuracy"] == metric["accuracy"],
        macro_f1_identical=summary["macro_f1"] == metric["macro_f1"],
    )
    return dict(feature_set=feature_set, stored_accuracy=metric["accuracy"],
                stored_macro_f1=metric["macro_f1"], **checks, all_identical=all(checks.values()))


def git_provenance():
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    return dict(branch=git("branch", "--show-current"), commit=git("rev-parse", "HEAD"),
                tracked_files_modified=bool(git("status", "--porcelain", "--untracked-files=no")),
                code_sha256={f: sha256(REPO / f) for f in CODE_FILES},
                ablation_py_sha256=sha256(__file__),
                environment=dict(python=platform.python_version(), numpy=np.__version__))


def verify_inputs(config, csv_paths, baseline_path):
    expected = [c["sha256"] for c in config["inputs"]["feature_csvs"]]
    actual = [sha256(p) for p in csv_paths]
    if actual != expected:
        raise SystemExit(f"input CSV SHA-256 differs from config.json: {actual}")
    if sha256(baseline_path) != config["inputs"]["baseline_result"]["sha256"]:
        raise SystemExit("baseline JSON SHA-256 differs from config.json")
    return [dict(file=c["file"], subject=c["subject"], sha256=h)
            for c, h in zip(config["inputs"]["feature_csvs"], actual)]


def run_task(task, config, csv_paths, baseline_path):
    spec = config["conditions"][TASKS[task]]
    model = config["model"]
    seeds, n_trees, max_features = model["seeds"], model["n_trees"], model["max_features"]
    inputs = verify_inputs(config, csv_paths, baseline_path)
    stored = json.loads(Path(baseline_path).read_text(encoding="utf-8-sig"))

    X, y, participants, keys = load_fixed_samples(csv_paths)
    if len(keys) != config["samples"]["expected_sample_count"]:
        raise SystemExit(f"expected {config['samples']['expected_sample_count']} samples, got {len(keys)}")

    base_name = spec["baseline"]
    base_ids = config["baselines"][base_name]["features"]
    baseline = evaluate_condition(X, y, participants, base_ids, seeds, n_trees, max_features)
    check = check_against_stored_baseline(baseline, stored, base_name, keys)
    if not check["all_identical"]:
        raise SystemExit(f"baseline {base_name} not reproduced; stop before ablation: {check}")

    conditions = {}
    for name, ids in spec["conditions"].items():
        result = evaluate_condition(X, y, participants, ids, seeds, n_trees, max_features)
        result["delta_vs_baseline"] = dict(baseline=base_name, **delta_pp(result, baseline))
        conditions[name] = result

    return dict(
        kind="teammate-feature-ablation-result",
        task=task, guide_section=spec["guide_section"], run_date=date.today().isoformat(),
        scope=config["scope"],
        config_sha256=sha256(HERE / "config.json"),
        provenance=git_provenance(), inputs=inputs,
        class_order=list(LAB6), posture_ids=list(POSTURE_IDS),
        confusion_matrix_axes=config["evaluation"]["confusion_matrix_axes"],
        model=dict(name="M0", n_trees=n_trees, max_features=max_features, seeds=seeds,
                   split_weights=None, retrained_per_condition_and_fold=True),
        samples=dict(count=len(keys),
                     per_participant={s: int(np.sum(participants == s))
                                      for s in sorted(set(participants))},
                     class_counts={pid: int(np.sum(y == k)) for k, pid in enumerate(POSTURE_IDS)},
                     sample_keys=keys, y_true=y.tolist(), participants=participants.tolist()),
        seed_note=config["evaluation"]["seed_note"],
        baseline=dict(name=base_name, stored_baseline_check=check, result=baseline),
        conditions=conditions,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", required=True, choices=sorted(TASKS))
    parser.add_argument("--probe-csv", required=True, nargs=2, metavar="CSV")
    parser.add_argument("--baseline-json", required=True)
    parser.add_argument("--out", help="default: the output file named in config.json")
    args = parser.parse_args()

    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else HERE / config["conditions"][TASKS[args.task]]["output"]
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing result: {out}")
    result = run_task(args.task, config, args.probe_csv, args.baseline_json)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
