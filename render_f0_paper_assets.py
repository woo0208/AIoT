#!/usr/bin/env python3
"""Render publication assets from one completed F0 LOSO result directory.

This script is analysis-only. It validates immutable result artifacts, recomputes
metrics from recorded held-out predictions, and never imports or runs the RF
training implementation.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


REQUIRED_FILES = (
    "experiment_manifest.json",
    "rf_results.csv",
    "rf_results.txt",
    "loso_predictions.csv",
    "confusion_matrices.csv",
    "sample_lineage.jsonl",
)
PREDICTION_FIELDS = (
    "experiment_run_id", "dataset_track", "feature_mode", "sample_index", "subject",
    "held_out_subject", "seed", "model", "lambda", "true_label_id", "predicted_label_id", "correct",
)
CONFUSION_FIELDS = (
    "experiment_run_id", "dataset_track", "feature_mode", "seed", "model", "lambda",
    "true_label_id", "predicted_label_id", "count",
)
CLASS_NAMES = ("Upright", "Forward head", "Lean back", "Lean left", "Lean right")
FEATURE_NAMES = ("A", "x_c", "y_c", "thetaL", "thetaR", "theta1")
FEATURE_DISPLAY = ("A", "x_c", "y_c", "theta_L", "theta_R", "theta_1")
REFERENCE_ACCURACY = 0.96
REFERENCE_MACRO_F1 = 0.9604752970606629
FLOAT_TOLERANCE = 1e-12


def fail(message: str) -> None:
    raise ValueError(message)


def sha256_file(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = path.stat()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    signatures = {(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) for s in (before, opened, after)}
    if len(signatures) != 1:
        fail(f"source artifact changed while hashing: {path}")
    return digest.hexdigest()


def artifact_identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def read_csv(path: Path, expected_fields: tuple[str, ...] | None = None) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or ())
        rows = list(reader)
    if expected_fields is not None and fields != list(expected_fields):
        fail(f"unexpected CSV header in {path.name}: {fields}")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        fail(f"malformed CSV row in {path.name}")
    return fields, rows


def parse_int(row: dict[str, str], field: str, source: str) -> int:
    try:
        value = int(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid integer {field!r} in {source}") from error
    if str(value) != row[field]:
        fail(f"non-canonical integer {field!r} in {source}: {row[field]!r}")
    return value


def parse_optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def model_lambdas(lambdas: list[float]) -> dict[str, float | None]:
    models: dict[str, float | None] = {"M0": None, "M1": None}
    for lam in lambdas:
        models[f"M2(lambda={lam:g})"] = float(lam)
    return models


def source_model_name(display_name: str) -> str:
    return display_name.replace("lambda", "λ")


def display_model_name(source_name: str) -> str:
    if source_name.startswith("M2(λ="):
        return f"M2(lambda={float(source_name.removeprefix('M2(λ=').removesuffix(')')):.1f})"
    return source_name


def close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def macro_f1(rows: list[dict], class_count: int = 5) -> float:
    scores = []
    for class_id in range(class_count):
        tp = sum(row["true_label_id"] == class_id and row["predicted_label_id"] == class_id for row in rows)
        fp = sum(row["true_label_id"] != class_id and row["predicted_label_id"] == class_id for row in rows)
        fn = sum(row["true_label_id"] == class_id and row["predicted_label_id"] != class_id for row in rows)
        support = tp + fn
        if not support:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return statistics.fmean(scores) if scores else 0.0


def confusion_from_predictions(rows: list[dict]) -> list[list[int]]:
    matrix = [[0 for _ in CLASS_NAMES] for _ in CLASS_NAMES]
    for row in rows:
        matrix[row["true_label_id"]][row["predicted_label_id"]] += 1
    return matrix


def per_class_metrics(rows: list[dict]) -> list[dict]:
    result = []
    for class_id, class_name in enumerate(CLASS_NAMES):
        tp = sum(row["true_label_id"] == class_id and row["predicted_label_id"] == class_id for row in rows)
        fp = sum(row["true_label_id"] != class_id and row["predicted_label_id"] == class_id for row in rows)
        fn = sum(row["true_label_id"] == class_id and row["predicted_label_id"] != class_id for row in rows)
        support = tp + fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result.append({"class_id": class_id, "class_name": class_name, "precision": precision,
                       "recall": recall, "f1": f1, "support": support})
    return result


def validate_manifest(input_dir: Path) -> tuple[dict, dict[str, dict]]:
    manifest_path = input_dir / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = input_dir.name
    if manifest.get("schema_version") != "rf-experiment-provenance/1.0.0":
        fail("unexpected experiment manifest schema")
    if manifest.get("experiment_run_id") != run_id:
        fail("manifest run ID does not match the input directory")
    if manifest.get("status") != "completed":
        fail("experiment manifest is not completed")
    errors = manifest.get("errors")
    if not isinstance(errors, list) or any(not str(error).startswith("optional plot failure:") for error in errors):
        fail("completed manifest contains a non-optional experiment error")

    missing = [name for name in REQUIRED_FILES if not (input_dir / name).is_file()]
    if missing:
        fail(f"required result artifacts are missing: {', '.join(missing)}")

    recorded_outputs = manifest.get("outputs")
    if not isinstance(recorded_outputs, list):
        fail("manifest outputs is not a list")
    output_by_kind: dict[str, dict] = {}
    for output in recorded_outputs:
        kind = output.get("kind")
        if kind in output_by_kind:
            fail(f"duplicate manifest output record: {kind}")
        output_by_kind[kind] = output
    for name in ("rf_results.csv", "rf_results.txt", "loso_predictions.csv", "confusion_matrices.csv"):
        recorded = output_by_kind.get(name)
        actual = artifact_identity(input_dir / name)
        if recorded is None:
            fail(f"manifest does not record output {name}")
        if Path(recorded.get("path", "")).name != name:
            fail(f"manifest output path basename mismatch for {name}")
        if recorded.get("size_bytes") != actual["size_bytes"] or recorded.get("sha256") != actual["sha256"]:
            fail(f"manifest output identity mismatch for {name}")

    lineage = manifest.get("sample_lineage") or {}
    lineage_path = input_dir / "sample_lineage.jsonl"
    if lineage.get("schema_version") != "rf-sample-lineage/1.0.0" or lineage.get("path") != lineage_path.name:
        fail("invalid sample lineage descriptor")
    if lineage.get("sha256") != sha256_file(lineage_path):
        fail("sample lineage SHA-256 mismatch")

    paper = (manifest.get("inputs") or {}).get("paper")
    if not isinstance(paper, dict):
        fail("paper dataset input record is missing")
    paper_path = Path(paper.get("path", ""))
    if not paper_path.is_file():
        fail(f"recorded paper dataset is unavailable for identity validation: {paper_path}")
    paper_actual = artifact_identity(paper_path)
    if paper.get("size_bytes") != paper_actual["size_bytes"] or paper.get("sha256") != paper_actual["sha256"]:
        fail("recorded paper dataset identity mismatch")

    options = manifest.get("options") or {}
    if (options.get("multiposture") is not None or (manifest.get("inputs") or {}).get("multiposture") is not None or
            options.get("ours") is not None or options.get("ours_frames") is not None or
            options.get("dataset_manifest") is not None or (manifest.get("inputs") or {}).get("ours") != [] or
            options.get("features") != ["all"] or options.get("skip_paper_loso") is not False):
        fail("input run is not the isolated paper_loso F0/all track")
    if not isinstance(options.get("trees"), int) or not isinstance(options.get("seeds"), int):
        fail("invalid tree or seed count in manifest options")
    return manifest, {name: artifact_identity(input_dir / name) for name in REQUIRED_FILES}


def load_lineage(input_dir: Path, manifest: dict) -> tuple[list[dict], dict[int, dict]]:
    rows = []
    with (input_dir / "sample_lineage.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid sample lineage JSON at line {line_number}") from error
            rows.append(row)
    descriptor = manifest["sample_lineage"]
    if len(rows) != descriptor.get("row_count"):
        fail("sample lineage row count mismatch")
    by_index = {}
    paper = manifest["inputs"]["paper"]
    run_id = manifest["experiment_run_id"]
    for row in rows:
        index = row.get("sample_index")
        if (row.get("schema_version") != "rf-sample-lineage/1.0.0" or row.get("experiment_run_id") != run_id or
                row.get("dataset_track") != "paper_loso" or row.get("feature_mode") != "all" or
                row.get("source_kind") != "external_table" or row.get("source_dataset_id") != "paper_dataset" or
                row.get("source_file_sha256") != paper["sha256"] or type(index) is not int or index in by_index or
                type(row.get("label")) is not int or not 0 <= row["label"] < len(CLASS_NAMES) or
                not isinstance(row.get("subject"), str) or not row["subject"]):
            fail("invalid or duplicate paper_loso sample lineage row")
        by_index[index] = row
    if sorted(by_index) != list(range(len(rows))):
        fail("sample lineage indices are not contiguous from zero")
    return rows, by_index


def load_predictions(input_dir: Path, manifest: dict, lineage_by_index: dict[int, dict]) -> list[dict]:
    _, raw_rows = read_csv(input_dir / "loso_predictions.csv", PREDICTION_FIELDS)
    expected_models = model_lambdas([float(value) for value in manifest["options"]["lams"]])
    source_models = {source_model_name(name): lam for name, lam in expected_models.items()}
    run_id = manifest["experiment_run_id"]
    seeds = manifest["options"]["seeds"]
    seen = set()
    rows = []
    for raw in raw_rows:
        row = dict(raw)
        for field in ("sample_index", "seed", "true_label_id", "predicted_label_id", "correct"):
            row[field] = parse_int(raw, field, "loso_predictions.csv")
        row["lambda"] = parse_optional_float(raw["lambda"])
        source = lineage_by_index.get(row["sample_index"])
        if (source is None or row["experiment_run_id"] != run_id or row["dataset_track"] != "paper_loso" or
                row["feature_mode"] != "all" or row["subject"] != source["subject"] or
                row["held_out_subject"] != source["subject"] or row["true_label_id"] != source["label"] or
                row["model"] not in source_models or row["lambda"] != source_models[row["model"]] or
                not 0 <= row["seed"] < seeds or not 0 <= row["predicted_label_id"] < len(CLASS_NAMES) or
                row["correct"] != int(row["true_label_id"] == row["predicted_label_id"])):
            fail("prediction row does not match run, lineage, fold, model, or label identity")
        key = (row["sample_index"], row["seed"], row["model"])
        if key in seen:
            fail("duplicate prediction record")
        seen.add(key)
        rows.append(row)
    expected_count = len(lineage_by_index) * seeds * len(source_models)
    if len(rows) != expected_count or len(seen) != expected_count:
        fail(f"prediction count mismatch: expected {expected_count}, found {len(rows)}")
    return rows


def load_confusions(input_dir: Path, manifest: dict, predictions: list[dict]) -> dict[tuple[str, int], list[list[int]]]:
    _, raw_rows = read_csv(input_dir / "confusion_matrices.csv", CONFUSION_FIELDS)
    expected: dict[tuple[str, int], list[list[int]]] = {}
    grouped_predictions: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in predictions:
        grouped_predictions[(row["model"], row["seed"])].append(row)
    for key, rows in grouped_predictions.items():
        expected[key] = confusion_from_predictions(rows)

    observed: dict[tuple[str, int], list[list[int | None]]] = {}
    seen = set()
    for raw in raw_rows:
        seed = parse_int(raw, "seed", "confusion_matrices.csv")
        true_id = parse_int(raw, "true_label_id", "confusion_matrices.csv")
        predicted_id = parse_int(raw, "predicted_label_id", "confusion_matrices.csv")
        count = parse_int(raw, "count", "confusion_matrices.csv")
        lam = parse_optional_float(raw["lambda"])
        key = (raw["model"], seed)
        cell = (*key, true_id, predicted_id)
        sample_row = next((row for row in predictions if (row["model"], row["seed"]) == key), None)
        if (sample_row is None or raw["experiment_run_id"] != manifest["experiment_run_id"] or
                raw["dataset_track"] != "paper_loso" or raw["feature_mode"] != "all" or
                lam != sample_row["lambda"] or not 0 <= true_id < 5 or not 0 <= predicted_id < 5 or count < 0 or
                cell in seen):
            fail("invalid or duplicate confusion matrix record")
        seen.add(cell)
        observed.setdefault(key, [[None for _ in CLASS_NAMES] for _ in CLASS_NAMES])[true_id][predicted_id] = count
    if set(observed) != set(expected):
        fail("confusion matrix model/seed groups do not match predictions")
    for key, matrix in observed.items():
        if any(value is None for row in matrix for value in row) or matrix != expected[key]:
            fail(f"confusion matrix orientation/count mismatch for {key}")
        if sum(sum(row) for row in matrix) != len(lineage_by_seed(predictions, key)):
            fail(f"confusion matrix total mismatch for {key}")
    return {key: [[int(value) for value in row] for row in matrix] for key, matrix in observed.items()}


def lineage_by_seed(predictions: list[dict], key: tuple[str, int]) -> list[dict]:
    return [row for row in predictions if (row["model"], row["seed"]) == key]


def load_results(input_dir: Path, manifest: dict) -> tuple[list[str], dict[str, dict]]:
    fields, rows = read_csv(input_dir / "rf_results.csv")
    required = {"acc", "acc_sd", "dataset", "f1", "f1_sd", "features", "min_subject_acc", "model",
                "root_provenance", "experiment_run_id", "dataset_manifest_sha256", "lineage_manifest_path",
                "lineage_manifest_sha256"}
    if set(fields) != required:
        fail("rf_results.csv schema differs from the expected paper_loso result schema")
    by_model = {}
    expected = {source_model_name(name) for name in model_lambdas(manifest["options"]["lams"])}
    for row in rows:
        model = row["model"]
        if (model not in expected or model in by_model or row["features"] != "all" or
                row["experiment_run_id"] != manifest["experiment_run_id"] or
                row["dataset_manifest_sha256"] != "" or row["lineage_manifest_path"] != "sample_lineage.jsonl" or
                row["lineage_manifest_sha256"] != manifest["sample_lineage"]["sha256"] or
                not row["dataset"].startswith("[A]")):
            fail("invalid, duplicate, or mixed-track rf_results.csv row")
        parsed = dict(row)
        for field in ("acc", "acc_sd", "f1", "f1_sd", "min_subject_acc"):
            parsed[field] = float(row[field])
        try:
            parsed["root_provenance"] = json.loads(row["root_provenance"])
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid root_provenance JSON for {model}") from error
        by_model[model] = parsed
    if set(by_model) != expected:
        fail("rf_results.csv does not contain exactly the four requested models")
    return fields, by_model


def validate_metrics(manifest: dict, predictions: list[dict], results: dict[str, dict]) -> dict[str, dict]:
    by_model_seed: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in predictions:
        by_model_seed[(row["model"], row["seed"])].append(row)
    metrics = {}
    for model, result in results.items():
        accuracies, f1_values = [], []
        for seed in range(manifest["options"]["seeds"]):
            rows = by_model_seed[(model, seed)]
            if len(rows) != manifest["sample_lineage"]["row_count"]:
                fail(f"seed sample count mismatch for {model}, seed {seed}")
            accuracies.append(statistics.fmean(row["correct"] for row in rows))
            f1_values.append(macro_f1(rows))
        calculated = {
            "accuracy": statistics.fmean(accuracies),
            "accuracy_sd": statistics.pstdev(accuracies),
            "macro_f1": statistics.fmean(f1_values),
            "macro_f1_sd": statistics.pstdev(f1_values),
            "per_seed_accuracy": accuracies,
            "per_seed_macro_f1": f1_values,
        }
        for actual, field in ((calculated["accuracy"], "acc"), (calculated["accuracy_sd"], "acc_sd"),
                              (calculated["macro_f1"], "f1"), (calculated["macro_f1_sd"], "f1_sd")):
            if not close(actual, result[field]):
                fail(f"recalculated metric differs from rf_results.csv for {model}: {field}")
        if not close(calculated["accuracy"], REFERENCE_ACCURACY) or not close(calculated["macro_f1"], REFERENCE_MACRO_F1):
            fail(f"observed results differ from the verified reference audit for {model}; rendering stopped")
        metrics[model] = calculated
    return metrics


def validate_prediction_equivalence(predictions: list[dict], sample_count: int) -> bool:
    values: dict[int, set[int]] = defaultdict(set)
    truths: dict[int, set[int]] = defaultdict(set)
    for row in predictions:
        values[row["sample_index"]].add(row["predicted_label_id"])
        truths[row["sample_index"]].add(row["true_label_id"])
    identical = (len(values) == sample_count and all(len(predicted) == 1 for predicted in values.values()) and
                 all(len(true) == 1 for true in truths.values()))
    if not identical:
        fail("observed predictions differ across models/seeds, contrary to the verified reference audit")
    return True


def validate_supports(predictions: list[dict], manifest: dict) -> dict[int, int]:
    reference = [row for row in predictions if row["model"] == "M0" and row["seed"] == 0]
    supports = Counter(row["true_label_id"] for row in reference)
    if set(supports) != set(range(len(CLASS_NAMES))):
        fail("the five-class order/support is incomplete")
    for model in {row["model"] for row in predictions}:
        for seed in range(manifest["options"]["seeds"]):
            current = Counter(row["true_label_id"] for row in predictions
                              if row["model"] == model and row["seed"] == seed)
            if current != supports:
                fail("class supports differ across model/seed prediction sets")
    return dict(sorted(supports.items()))


def validate_subject_samples(lineage: list[dict]) -> None:
    by_subject: dict[str, Counter] = defaultdict(Counter)
    for row in lineage:
        by_subject[row["subject"]][row["label"]] += 1
    expected = Counter({class_id: 1 for class_id in range(len(CLASS_NAMES))})
    if not by_subject or any(counts != expected for counts in by_subject.values()):
        fail("paper_loso lineage is not exactly one sample per class per subject")


def validate_roots(manifest: dict, results: dict[str, dict], subjects: set[str]) -> dict[str, dict]:
    roots = {}
    expected_pairs = {(seed, subject) for seed in range(manifest["options"]["seeds"]) for subject in subjects}
    for model, row in results.items():
        records = row["root_provenance"]
        pairs = set()
        counts = Counter({name: 0 for name in FEATURE_NAMES})
        total_trees = split_roots = leaf_only = 0
        for record in records:
            pair = (record.get("seed"), record.get("held_out_subject"))
            stats = record.get("root_statistics") or {}
            if (record.get("model") != model or record.get("feature_set") != "all" or pair in pairs or
                    record.get("tree_count") != manifest["options"]["trees"] or record.get("max_features") != 2 or
                    stats.get("feature_names") != list(FEATURE_NAMES)):
                fail(f"invalid root provenance identity for {model}")
            pairs.add(pair)
            stat_counts = stats.get("counts") or {}
            if set(stat_counts) != set(FEATURE_NAMES) or any(type(value) is not int or value < 0 for value in stat_counts.values()):
                fail(f"invalid root feature counts for {model}")
            if (sum(stat_counts.values()) != stats.get("split_trees") or
                    stats.get("split_trees", 0) + stats.get("leaf_only_trees", 0) != stats.get("total_trees") or
                    len(stats.get("root_feature_indices") or []) != stats.get("total_trees")):
                fail(f"root count denominator mismatch for {model}")
            observed_indices = Counter(index for index in stats["root_feature_indices"] if index is not None)
            if any(observed_indices[index] != stat_counts[name] for index, name in enumerate(FEATURE_NAMES)):
                fail(f"root index/count mapping mismatch for {model}")
            counts.update(stat_counts)
            total_trees += stats["total_trees"]
            split_roots += stats["split_trees"]
            leaf_only += stats["leaf_only_trees"]
        if pairs != expected_pairs:
            fail(f"root provenance does not cover every seed and LOSO fold for {model}")
        if sum(counts.values()) != split_roots:
            fail(f"aggregate splitting-root denominator mismatch for {model}")
        roots[model] = {"counts": dict(counts), "split_roots": split_roots, "total_trees": total_trees,
                        "leaf_only_trees": leaf_only,
                        "percentages": {name: 100 * counts[name] / split_roots for name in FEATURE_NAMES}}
    if roots["M0"]["counts"] != roots["M1"]["counts"]:
        fail("M0/M1 root counts differ from the verified reference audit")
    return roots


def analyze(input_dir: Path) -> dict:
    input_dir = input_dir.resolve(strict=True)
    manifest, identities = validate_manifest(input_dir)
    lineage, lineage_by_index = load_lineage(input_dir, manifest)
    predictions = load_predictions(input_dir, manifest, lineage_by_index)
    confusions = load_confusions(input_dir, manifest, predictions)
    _, results = load_results(input_dir, manifest)
    metrics = validate_metrics(manifest, predictions, results)
    validate_prediction_equivalence(predictions, len(lineage))
    supports = validate_supports(predictions, manifest)
    validate_subject_samples(lineage)
    subjects = {row["subject"] for row in lineage}
    roots = validate_roots(manifest, results, subjects)
    return {"input_dir": input_dir, "manifest": manifest, "identities": identities, "lineage": lineage,
            "predictions": predictions, "confusions": confusions, "results": results, "metrics": metrics,
            "supports": supports, "subjects": subjects, "roots": roots, "predictions_identical": True}


def write_table_1(output_dir: Path, analysis: dict) -> None:
    manifest = analysis["manifest"]
    paper = manifest["inputs"]["paper"]
    seeds = sorted({row["seed"] for row in analysis["predictions"]})
    lines = [
        "# Table 1. F0 experiment settings", "",
        "| Setting | Recorded value |", "|---|---|",
        f"| Data source | Original-paper external table (`{paper['source_dataset_id']}`) |",
        f"| Subjects | {len(analysis['subjects'])} |",
        f"| Unique samples | {len(analysis['lineage'])} ({', '.join(str(analysis['supports'][i]) for i in range(5))} per class) |",
        "| Five classes (ID order) | 0 Upright; 1 Forward head; 2 Lean back; 3 Lean left; 4 Lean right |",
        "| Feature family | F0 original baseline (`all`) |",
        "| F0 features | `A`, `x_c`, `y_c`, `thetaL`, `thetaR`, `theta1` |",
        f"| Evaluation | Subject-level leave-one-subject-out (LOSO), {len(analysis['subjects'])} folds |",
        f"| Trees per fitted forest | {manifest['options']['trees']} |",
        f"| Random seeds (0-based) | {', '.join(map(str, seeds))} |",
        "| `max_features` | 2 |",
        f"| M2 exploratory lambda values | {', '.join(f'{float(x):.1f}' for x in manifest['options']['lams'])} |",
        f"| Experiment provenance schema | `{manifest['schema_version']}` |",
        f"| Experiment run ID | `{manifest['experiment_run_id']}` |",
        f"| Recorded Git commit | `{manifest['code']['git_commit']}` (dirty={str(manifest['code']['git_dirty']).lower()}) |",
        f"| RF script SHA-256 | `{manifest['code']['rf_script_sha256']}` |",
        f"| Dataset size | {paper['size_bytes']} bytes |",
        f"| Dataset SHA-256 | `{paper['sha256']}` |", "",
        "Note: lambda values were exploratory settings reported side by side, not a held-out-data selection rule.", "",
    ]
    (output_dir / "table_1_settings.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def ordered_models(analysis: dict) -> list[str]:
    expected = ["M0", "M1", *(source_model_name(f"M2(lambda={float(lam):g})")
                               for lam in analysis["manifest"]["options"]["lams"])]
    return expected


def write_table_2(output_dir: Path, analysis: dict) -> None:
    fields = ("model", "accuracy", "accuracy_seed_sd", "macro_f1", "macro_f1_seed_sd", "seed_count",
              "unique_samples_per_seed")
    with (output_dir / "table_2_performance.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for model in ordered_models(analysis):
            source = analysis["results"][model]
            writer.writerow({"model": display_model_name(model), "accuracy": f"{source['acc']:.12f}",
                             "accuracy_seed_sd": f"{source['acc_sd']:.12f}",
                             "macro_f1": f"{source['f1']:.12f}", "macro_f1_seed_sd": f"{source['f1_sd']:.12f}",
                             "seed_count": analysis["manifest"]["options"]["seeds"],
                             "unique_samples_per_seed": len(analysis["lineage"])})


def write_table_3(output_dir: Path, analysis: dict) -> None:
    fields = ("model", "lambda", "seed", "aggregation_method", "class_id", "class_name", "precision",
              "recall", "f1", "support", "unique_samples")
    with (output_dir / "table_3_per_class.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for model in ordered_models(analysis):
            rows = [row for row in analysis["predictions"] if row["model"] == model and row["seed"] == 0]
            lam = rows[0]["lambda"]
            for metric in per_class_metrics(rows):
                writer.writerow({"model": display_model_name(model), "lambda": "" if lam is None else f"{lam:.1f}",
                                 "seed": 0, "aggregation_method": "single recorded seed; no seed pooling",
                                 **{key: metric[key] for key in ("class_id", "class_name")},
                                 "precision": f"{metric['precision']:.12f}", "recall": f"{metric['recall']:.12f}",
                                 "f1": f"{metric['f1']:.12f}", "support": metric["support"],
                                 "unique_samples": len(rows)})


def configure_matplotlib():
    try:
        import matplotlib
    except ImportError as error:
        raise RuntimeError("Matplotlib is required to render figures; install it in the active environment") from error
    matplotlib.use("Agg")
    matplotlib.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 12, "axes.labelsize": 11,
        "legend.fontsize": 9, "xtick.labelsize": 9, "ytick.labelsize": 9, "svg.hashsalt": "f0-paper-assets-v1",
    })
    import matplotlib.pyplot as plt
    return matplotlib, plt


def save_figure(fig, output_dir: Path, stem: str) -> None:
    metadata = {"Creator": "render_f0_paper_assets.py"}
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight", metadata=metadata)
    fig.savefig(output_dir / f"{stem}.svg", bbox_inches="tight", metadata={"Creator": metadata["Creator"], "Date": None})


def render_confusion(output_dir: Path, analysis: dict, plt) -> None:
    matrix = analysis["confusions"][("M0", 0)]
    fig, ax = plt.subplots(figsize=(7.2, 6.1), constrained_layout=True)
    image = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=max(max(row) for row in matrix))
    colorbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    colorbar.set_label("Count")
    ax.set_title("M0 LOSO confusion matrix (seed 0)")
    ax.set_xlabel("Predicted class")
    ax.set_ylabel("True class")
    ax.set_xticks(range(5), CLASS_NAMES, rotation=30, ha="right")
    ax.set_yticks(range(5), CLASS_NAMES)
    threshold = max(max(row) for row in matrix) / 2
    for true_id, row in enumerate(matrix):
        for predicted_id, count in enumerate(row):
            ax.text(predicted_id, true_id, str(count), ha="center", va="center",
                    color="white" if count > threshold else "#17202a", fontweight="semibold")
    save_figure(fig, output_dir, "figure_1_confusion_matrix")
    plt.close(fig)


def render_roots(output_dir: Path, analysis: dict, plt) -> None:
    models = ordered_models(analysis)
    colors = ("#4c78a8", "#72b7b2", "#f2cf5b", "#e45756")
    width = 0.19
    positions = list(range(len(FEATURE_NAMES)))
    fig, ax = plt.subplots(figsize=(9.2, 5.7), constrained_layout=True)
    for model_index, (model, color) in enumerate(zip(models, colors)):
        offsets = [position + (model_index - 1.5) * width for position in positions]
        values = [analysis["roots"][model]["percentages"][name] for name in FEATURE_NAMES]
        ax.bar(offsets, values, width=width, label=display_model_name(model), color=color,
               edgecolor="white", linewidth=0.5)
    ax.set_title("Root split feature distribution across LOSO fits")
    ax.set_xlabel("Root split feature")
    ax.set_ylabel("Share of splitting roots (%)")
    ax.set_xticks(positions, FEATURE_DISPLAY)
    ax.set_ylim(0, 35)
    ax.yaxis.grid(True, color="#d9d9d9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(ncol=2, frameon=False, loc="upper right")
    denominator = analysis["roots"][models[0]]["split_roots"]
    folds = len(analysis["subjects"])
    seeds = analysis["manifest"]["options"]["seeds"]
    trees = analysis["manifest"]["options"]["trees"]
    ax.text(0.0, -0.22, f"Denominator per model: n={denominator:,} splitting roots "
            f"({folds} LOSO folds x {seeds} seeds x {trees} trees).",
            transform=ax.transAxes, ha="left", va="top", fontsize=9, color="#333333")
    save_figure(fig, output_dir, "figure_2_root_feature_distribution")
    plt.close(fig)


def write_report(output_dir: Path, analysis: dict, matplotlib_version: str) -> None:
    manifest = analysis["manifest"]
    run_id = manifest["experiment_run_id"]
    model = analysis["results"]["M0"]
    matrix = analysis["confusions"][("M0", 0)]
    errors = "; ".join(manifest["errors"]) if manifest["errors"] else "None"
    source_prefix = f"../../../results/{run_id}"
    roots = analysis["roots"]
    root_lines = ["| Model | A | x_c | y_c | thetaL | thetaR | theta1 | Splitting roots |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in ordered_models(analysis):
        values = roots[name]["percentages"]
        root_lines.append("| " + display_model_name(name) + " | " + " | ".join(
            f"{values[feature]:.2f}%" for feature in FEATURE_NAMES) + f" | {roots[name]['split_roots']:,} |")
    hashes = analysis["identities"]
    artifact_lines = [f"- [{name}]({source_prefix}/{name}) — SHA-256 `{hashes[name]['sha256']}`"
                      for name in REQUIRED_FILES]
    lines = [
        "# F0 preliminary results", "",
        f"Experiment run: `{run_id}`", "",
        "## Scope and settings", "",
        f"This report is a read-only analysis of the completed original-paper F0 run. It contains "
        f"{len(analysis['lineage'])} unique samples from {len(analysis['subjects'])} subjects and five classes, "
        f"evaluated by {len(analysis['subjects'])}-fold subject-level LOSO. Each fitted forest used "
        f"{manifest['options']['trees']} trees, `max_features=2`, and seeds 0–{manifest['options']['seeds'] - 1}. "
        "M2 lambda values 0.5 and 1.0 are exploratory settings; they were not selected using a frozen formal "
        "lambda-selection rule. Full settings are in [Table 1](table_1_settings.md).", "",
        "## Numerical findings", "",
        f"All four model configurations recorded Accuracy {model['acc']:.6f} (seed SD {model['acc_sd']:.6f}) "
        f"and Macro-F1 {model['f1']:.6f} (seed SD {model['f1_sd']:.6f}). Independent recomputation from the "
        f"{len(analysis['predictions']):,} held-out prediction records reproduced these values. All "
        f"{len(analysis['lineage'])} sample predictions were identical across the four models and three seeds. "
        "Thus this run does not show an M2 classification-accuracy improvement.", "",
        "Per-class precision, recall, F1, and support are reported for each model at seed 0 in "
        "[Table 3](table_3_per_class.csv). A single seed is used because the recorded predictions are identical; "
        "the three seed repeats are not pooled or treated as independent subjects. Each class has support 20.", "",
        "## Figures", "",
        "**Figure 1. Five-class confusion matrix for M0, seed 0.** Rows are true classes and columns are "
        f"predicted classes. Cell labels are counts over {sum(sum(row) for row in matrix)} unique held-out samples, "
        "not percentages. The same held-out predictions were recorded for M1 and both M2 variants at every seed. "
        "[PNG](figure_1_confusion_matrix.png) | [SVG](figure_1_confusion_matrix.svg)", "",
        "**Figure 2. Root split feature distribution.** Counts from `root_provenance` were aggregated over 20 LOSO "
        f"folds, 3 seeds, and 500 trees: {roots['M0']['split_roots']:,} splitting roots per model. Bars show each "
        "feature's percentage of actual splitting roots. M0 and M1 have identical root selections in aggregate; "
        "M2 changes root split selection. These frequencies are neither feature-selection frequencies across "
        "independent datasets nor measures of predictive importance or accuracy. "
        "[PNG](figure_2_root_feature_distribution.png) | [SVG](figure_2_root_feature_distribution.svg)", "",
        *root_lines, "",
        "## Integrity validation", "",
        f"The manifest run ID matches the directory and its status is `completed`. The recorded dataset size and "
        f"SHA-256 were rechecked. Output sizes and SHA-256 values were rechecked against the manifest; the lineage "
        f"hash and {len(analysis['lineage'])}-row count were rechecked. Prediction keys are unique, all "
        f"{len(analysis['predictions']):,} expected prediction records are present, every confusion matrix totals "
        f"{len(analysis['lineage'])}, and archived matrices match matrices independently reconstructed with true "
        "labels on rows and predicted labels on columns. Metrics and class supports were independently recalculated.", "",
        f"The completed manifest records a historical `{errors}`. This was an optional Matplotlib plot failure, "
        "not a model-training failure; the completed numerical artifacts remain present and hash-verified. "
        f"These paper figures were rendered separately with Matplotlib {matplotlib_version}.", "",
        "## Limitations", "",
        "This is a preliminary result from a small, balanced dataset with 20 subjects and one sample per class per "
        "subject. Seed SD quantifies only the three recorded algorithm seeds and is not subject-level uncertainty. "
        "Identical held-out predictions do not imply identical learned structures: M2 changed root split selection "
        "without changing predictions in this run. The exploratory lambda comparison does not establish a selected "
        "lambda or stable gain. This F0 analysis does not test MultiPosture, F1, or F2, and it does not confirm F1/F2 "
        "effectiveness.", "",
        "## Source artifacts", "", *artifact_lines, "",
        f"- Dataset SHA-256 recorded and rechecked: `{manifest['inputs']['paper']['sha256']}`", "",
        "No RF model was retrained, and no file in the source result directory was modified.", "",
    ]
    (output_dir / "F0_preliminary_results.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def render_all(input_dir: Path, output_dir: Path) -> dict:
    analysis = analyze(input_dir)
    before = {name: sha256_file(analysis["input_dir"] / name) for name in REQUIRED_FILES}
    output_dir = output_dir.resolve()
    if output_dir == analysis["input_dir"] or analysis["input_dir"] in output_dir.parents:
        fail("output directory must not be inside the immutable experiment result directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_table_1(output_dir, analysis)
    write_table_2(output_dir, analysis)
    write_table_3(output_dir, analysis)
    matplotlib, plt = configure_matplotlib()
    render_confusion(output_dir, analysis, plt)
    render_roots(output_dir, analysis, plt)
    write_report(output_dir, analysis, matplotlib.__version__)
    after = {name: sha256_file(analysis["input_dir"] / name) for name in REQUIRED_FILES}
    if before != after:
        fail("a source result artifact changed during rendering")
    return analysis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="Completed results/<experiment_run_id> directory")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Separate destination for tables, figures, and report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis = render_all(args.input_dir, args.output_dir)
    print(f"Validated {len(analysis['predictions'])} prediction records and rendered F0 assets to "
          f"{args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
