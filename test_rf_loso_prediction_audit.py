"""Synthetic audit/reproducibility checks only, not empirical posture accuracy."""
from contextlib import ExitStack, redirect_stdout
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import rf_experiment as rf
from patch5_test_fixtures import mocked_model_inputs


def fixture(n_subjects=20):
    # Interleave subjects to detect accidental fold-order sorting/renumbering.
    y = np.repeat(np.arange(5), n_subjects)
    g = np.tile([f"P{s}" for s in range(n_subjects)], 5)
    X = np.arange(len(y) * 6, dtype=float).reshape(-1, 6)
    X[:, 0] = np.arange(1, len(y) + 1)
    return X, y, g


def controlled_fit(values, observed):
    X, y, g = values

    def fit(Xtr, ytr, K, trees, seed, lams):
        train = set(Xtr[:, 0].astype(int) - 1)
        held_out = set(g) - set(g[list(train)])
        if len(held_out) != 1:
            raise AssertionError("training must exclude exactly one participant")
        models = {}
        for model_index, (name, lam) in enumerate(rf.loso_model_lambdas(lams).items()):
            def predict(Xte, model_index=model_index, name=name):
                indices = Xte[:, 0].astype(int) - 1
                if train.intersection(indices) or set(g[indices]) != held_out:
                    raise AssertionError("training samples were predicted as held-out test samples")
                # M0/M1 match. An asymmetric confusion pattern detects transposition.
                predictions = y[indices].copy()
                predictions[(y[indices] == 0) & (indices % 2 == 0)] = 1
                if model_index > 1:
                    predictions = (predictions + seed + model_index - 1) % K
                observed.append((seed, name, indices.copy(), predictions.copy(), held_out.copy()))
                return predictions
            predict.lam = lam
            models[name] = predict
        return models, np.ones(X.shape[1])
    return fit


def run_fixture(root, values=None, *, features=("all",), seeds=3, multi=None, skip=False, lams=(.5, 1.)):
    values = fixture() if values is None else values
    root = Path(root)
    observed = []
    argv = ["rf_experiment.py", "--features", *features, "--seeds", str(seeds), "--trees", "2",
            "--lams", *map(str, lams)]
    if skip:
        argv.append("--skip-paper-loso")
    # Track-specific controlled models also verify MultiPosture test-fold isolation.
    def fit(Xtr, *args):
        source = multi if multi is not None and Xtr[:, 0].min() > 1000 else values
        if source is multi:
            adjusted = (multi[0].copy(), multi[1], multi[2])
            adjusted[0][:, 0] -= 1000
            Xtr = Xtr.copy()
            Xtr[:, 0] -= 1000
            models, weights = controlled_fit(adjusted, observed)(Xtr, *args)
            for name, fn in list(models.items()):
                def predict(Xte, fn=fn):
                    Xte = Xte.copy()
                    Xte[:, 0] -= 1000
                    return fn(Xte)
                predict.lam = fn.lam
                models[name] = predict
            return models, weights
        return controlled_fit(source, observed)(Xtr, *args)

    def plot(rows):
        (Path(rf.OUT_DIR) / "fig5_rf_compare.png").write_bytes(b"synthetic plot")

    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(patch.object(rf, "OUT_DIR", str(root)))
        stack.enter_context(patch.object(rf, "fit_models", side_effect=fit))
        stack.enter_context(patch.object(rf, "plot", side_effect=plot))
        stack.enter_context(patch("sys.argv", argv))
        stack.enter_context(mocked_model_inputs(
            rf, root, values, (np.empty((0, 6)), np.array([], int), []), multi))
        directory = rf.main()
    manifest = json.loads((directory / "experiment_manifest.json").read_text(encoding="utf-8"))
    return directory, manifest, observed


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


class PredictionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.values = fixture()
        cls.directory, cls.manifest, cls.observed = run_fixture(cls.root, cls.values)
        cls.fields, cls.rows = read_csv(cls.directory / "loso_predictions.csv")
        cls.cm_fields, cls.matrices = read_csv(cls.directory / "confusion_matrices.csv")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_default_counts_fields_and_unique_keys(self):
        self.assertEqual(self.fields, list(rf.PREDICTION_FIELDS))
        self.assertEqual(self.cm_fields, list(rf.CONFUSION_FIELDS))
        self.assertEqual(len(self.rows), 1200)
        self.assertEqual(len(self.matrices), 300)
        key_fields = ("experiment_run_id", "dataset_track", "feature_mode", "sample_index", "seed", "model")
        self.assertEqual(len({tuple(r[k] for k in key_fields) for r in self.rows}), 1200)
        self.assertEqual({int(r["seed"]) for r in self.rows}, {0, 1, 2})
        for seed in range(3):
            for model, lam in rf.loso_model_lambdas([.5, 1.]).items():
                rows = [r for r in self.rows if r["seed"] == str(seed) and r["model"] == model]
                self.assertEqual([int(r["sample_index"]) for r in rows], list(range(100)))
                self.assertEqual({r["lambda"] for r in rows}, {"" if lam is None else str(lam)})

    def test_exact_labels_subjects_and_test_only_prediction_calls(self):
        lineage = [json.loads(line) for line in
                   (self.directory / "sample_lineage.jsonl").read_text(encoding="utf-8").splitlines()]
        by_key = {(r["seed"], r["model"], int(r["sample_index"])): r for r in self.rows}
        self.assertEqual(len(self.observed), 3 * 20 * 4)  # One prediction per model/fold.
        observed_keys = set()
        for seed, model, indices, predictions, held_out in self.observed:
            for index, prediction in zip(indices, predictions):
                key = str(seed), model, int(index)
                self.assertNotIn(key, observed_keys)
                observed_keys.add(key)
                row, source = by_key[key], lineage[index]
                for field in ("experiment_run_id", "dataset_track", "feature_mode", "subject"):
                    self.assertEqual(row[field], source[field])
                self.assertEqual(row["held_out_subject"], source["subject"])
                self.assertEqual(held_out, {source["subject"]})
                self.assertEqual(int(row["true_label_id"]), source["label"])
                self.assertEqual(int(row["predicted_label_id"]), prediction)
                self.assertEqual(int(row["correct"]), int(prediction == source["label"]))
        self.assertEqual(observed_keys, set(by_key))

    def test_matrix_orientation_zeros_totals_supports_and_accuracy(self):
        for seed in range(3):
            for model in rf.loso_model_lambdas([.5, 1.]):
                predictions = [r for r in self.rows if r["seed"] == str(seed) and r["model"] == model]
                cells = [r for r in self.matrices if r["seed"] == str(seed) and r["model"] == model]
                self.assertEqual([(int(r["true_label_id"]), int(r["predicted_label_id"])) for r in cells],
                                 [(t, p) for t in range(5) for p in range(5)])
                matrix = np.array([int(r["count"]) for r in cells]).reshape(5, 5)
                expected = np.zeros((5, 5), int)
                for row in predictions:
                    expected[int(row["true_label_id"]), int(row["predicted_label_id"])] += 1
                np.testing.assert_array_equal(matrix, expected)
                self.assertTrue((matrix == 0).any())
                self.assertEqual(matrix.sum(), len(predictions))
                np.testing.assert_array_equal(matrix.sum(axis=1), [20] * 5)
                self.assertEqual(matrix.trace() / matrix.sum(),
                                 sum(int(r["correct"]) for r in predictions) / len(predictions))
                if model == "M0":
                    self.assertEqual(matrix[0, 1], 10)
                    self.assertEqual(matrix[1, 0], 0)
        _, results = read_csv(self.directory / "rf_results.csv")
        for result in results:
            rows = [r for r in self.rows if r["model"] == result["model"]]
            self.assertAlmostEqual(sum(int(r["correct"]) for r in rows) / len(rows), float(result["acc"]))

    def test_manifest_exact_paths_sizes_hashes_and_compatibility_copies(self):
        rf.verify_loso_audit(self.directory, self.manifest)
        for name in rf.LOSO_AUDIT_OUTPUTS:
            outputs = [o for o in self.manifest["outputs"] if o["kind"] == name]
            self.assertEqual(len(outputs), 1)
            path = self.directory / name
            self.assertEqual(outputs[0], dict(kind=name, path=str(path), size_bytes=path.stat().st_size,
                                            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            self.assertEqual(path.read_bytes(), (self.root / name).read_bytes())

    def test_separate_tracks_modes_and_source_label_ids(self):
        multi = fixture(2)
        multi[0][:, 0] += 1000
        with tempfile.TemporaryDirectory() as root:
            directory, manifest, _ = run_fixture(root, fixture(2), features=("all", "invariant", "relative"),
                                                 seeds=2, multi=multi)
            _, rows = read_csv(directory / "loso_predictions.csv")
            _, matrices = read_csv(directory / "confusion_matrices.csv")
            self.assertEqual(len(rows), (3 * 10 + 10) * 2 * 4)
            self.assertEqual(len(matrices), 4 * 2 * 4 * 25)
            self.assertEqual({(r["dataset_track"], r["feature_mode"]) for r in rows},
                             {("paper_loso", m) for m in ("all", "invariant", "relative")} |
                             {("multiposture_loso", "all")})
            self.assertEqual({r["true_label_id"] for r in rows if r["dataset_track"] == "multiposture_loso"},
                             {"0", "1", "2", "3", "4"})
            rf.verify_loso_audit(directory, manifest)

    def test_skipped_paper_has_no_predictions_or_matrices(self):
        with tempfile.TemporaryDirectory() as root:
            directory, manifest, observed = run_fixture(root, fixture(2), skip=True)
            self.assertEqual(observed, [])
            self.assertEqual(read_csv(directory / "loso_predictions.csv")[1], [])
            self.assertEqual(read_csv(directory / "confusion_matrices.csv")[1], [])
            rf.verify_loso_audit(directory, manifest)

    def test_nondefault_lambda_lists_and_unrounded_actual_lambda(self):
        for lams in ((), (.123456789,)):
            with self.subTest(lams=lams), tempfile.TemporaryDirectory() as root:
                directory, manifest, _ = run_fixture(root, fixture(2), seeds=1, lams=lams)
                _, rows = read_csv(directory / "loso_predictions.csv")
                _, cells = read_csv(directory / "confusion_matrices.csv")
                self.assertEqual(len(rows), 10 * (2 + len(lams)))
                self.assertEqual(len(cells), 25 * (2 + len(lams)))
                for row in rows + cells:
                    if row["model"].startswith("M2"):
                        self.assertEqual(row["model"], "M2(λ=0.123457)")
                        self.assertEqual(float(row["lambda"]), .123456789)
                rf.verify_loso_audit(directory, manifest)

    def test_create_only_and_existing_runs_preserved(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        # An empty new audit must not overwrite a previous artifact.
        with self.assertRaises(FileExistsError):
            with patch.object(rf, "validate_loso_predictions"):
                rf.write_loso_audit(self.directory, [], self.manifest)
        other = self.root / "another_execution"
        other.mkdir()
        run_fixture(other, fixture(2), seeds=1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})


class AuditFailureTests(unittest.TestCase):
    def assert_failed(self, root):
        path = next(Path(root).glob("results/*/experiment_manifest.json"))
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(manifest["errors"])
        self.assertFalse((Path(root) / "rf_results.csv").exists())
        self.assertFalse((Path(root) / "loso_predictions.csv").exists())
        self.assertTrue((path.parent / "sample_lineage.jsonl").exists())

    def test_missing_duplicate_or_mismatched_predictions_fail_closed(self):
        original = rf.write_loso_audit
        mutations = {
            "duplicate": lambda rows: rows.append(copy.deepcopy(rows[0])),
            "missing": lambda rows: rows.pop(),
            "subject": lambda rows: rows[0].update(subject="training participant"),
            "held_out": lambda rows: rows[0].update(held_out_subject="training participant"),
            "index": lambda rows: rows[0].update(sample_index=10000),
            "true_label": lambda rows: rows[0].update(true_label_id=4),
            "predicted_label": lambda rows: rows[0].update(predicted_label_id=5),
            "correct": lambda rows: rows[0].update(correct=9),
            "lambda": lambda rows: rows[0].update(**{"lambda": .5}),
            "model": lambda rows: rows[0].update(model="unexpected"),
            "seed": lambda rows: rows[0].update(seed=3),
            "mode": lambda rows: rows[0].update(feature_mode="relative"),
            "track": lambda rows: rows[0].update(dataset_track="multiposture_loso"),
            "run": lambda rows: rows[0].update(experiment_run_id="other run"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                def corrupt(directory, rows, manifest):
                    mutate(rows)
                    return original(directory, rows, manifest)
                with patch.object(rf, "write_loso_audit", side_effect=corrupt), self.assertRaises(ValueError):
                    run_fixture(root, fixture(2), seeds=1)
                self.assert_failed(root)

    def test_output_tampering_missing_files_and_write_or_hash_failures(self):
        execute = rf.execute_experiment
        identity = rf.file_identity
        for name in rf.LOSO_AUDIT_OUTPUTS:
            for failure in ("tamper", "missing", "write", "hash"):
                with self.subTest(name=name, failure=failure), tempfile.TemporaryDirectory() as root:
                    def corrupt(a, directory, manifest):
                        execute(a, directory, manifest)
                        path = directory / name
                        if failure == "missing":
                            path.unlink()
                        else:
                            path.write_bytes(path.read_bytes() + b"tampered")
                    def fail_hash(path):
                        if Path(path).name == name:
                            raise OSError("synthetic audit hash failure")
                        return identity(path)
                    original_open = Path.open
                    def fail_write(path, mode="r", *args, **kwargs):
                        if path.name == name and mode == "x":
                            raise OSError("synthetic audit write failure")
                        return original_open(path, mode, *args, **kwargs)
                    with ExitStack() as stack:
                        if failure == "hash":
                            stack.enter_context(patch.object(rf, "file_identity", side_effect=fail_hash))
                        elif failure == "write":
                            stack.enter_context(patch.object(Path, "open", fail_write))
                        else:
                            stack.enter_context(patch.object(rf, "execute_experiment", side_effect=corrupt))
                        with self.assertRaises((ValueError, OSError)):
                            run_fixture(root, fixture(2), seeds=1)
                    self.assert_failed(root)

    def test_matrix_mismatch_rejected_even_with_updated_hash(self):
        execute = rf.execute_experiment
        def corrupt(a, directory, manifest):
            execute(a, directory, manifest)
            path = directory / "confusion_matrices.csv"
            fields, rows = read_csv(path)
            rows[0]["count"] = str(int(rows[0]["count"]) + 1)
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            next(o for o in manifest["outputs"] if o["kind"] == path.name).update(rf.file_identity(path))
        with tempfile.TemporaryDirectory() as root:
            with patch.object(rf, "execute_experiment", side_effect=corrupt), \
                    self.assertRaisesRegex(ValueError, "confusion matrices do not match"):
                run_fixture(root, fixture(2), seeds=1)
            self.assert_failed(root)

    def test_serialized_duplicate_or_wrong_header_rejected_even_with_updated_hash(self):
        execute = rf.execute_experiment
        for failure in ("duplicate", "header", "malformed", "mismatch"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                def corrupt(a, directory, manifest):
                    execute(a, directory, manifest)
                    path = directory / "loso_predictions.csv"
                    fields, rows = read_csv(path)
                    if failure == "duplicate":
                        rows.append(rows[0].copy())
                    elif failure == "header":
                        fields.reverse()
                    elif failure == "mismatch":
                        rows[0]["held_out_subject"] = "training participant"
                    with path.open("w", encoding="utf-8-sig", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=fields)
                        writer.writeheader()
                        writer.writerows(rows)
                        if failure == "malformed":
                            stream.write("incomplete,row\n")
                    next(o for o in manifest["outputs"] if o["kind"] == path.name).update(rf.file_identity(path))
                with patch.object(rf, "execute_experiment", side_effect=corrupt), self.assertRaises(ValueError):
                    run_fixture(root, fixture(2), seeds=1)
                self.assert_failed(root)


class ActualRFCompatibilityTests(unittest.TestCase):
    def test_audit_preserves_fitting_calls_metrics_logs_roots_and_m0_m1(self):
        X, y, g = fixture(3)
        X = np.random.default_rng(19).normal(size=X.shape)
        runs = []
        for audit in (False, True):
            predictions, logs = [], []
            with redirect_stdout(io.StringIO()), patch.object(rf, "fit_models", wraps=rf.fit_models) as fit:
                rows = rf.loso(X, y, g, 5, 3, 2, [.5, 1.], "synthetic", logs.append,
                               prediction_rows=predictions if audit else None,
                               experiment_run_id="er_synthetic", dataset_track="paper_loso")
            self.assertEqual(fit.call_count, 3 * 2)
            runs.append((rows, logs, predictions))
        self.assertEqual(runs[0][:2], runs[1][:2])
        self.assertEqual(len(runs[1][2]), 15 * 2 * 4)
        for seed in range(2):
            by_model = {m: [r["predicted_label_id"] for r in runs[1][2] if r["model"] == m and r["seed"] == seed]
                        for m in ("M0", "M1")}
            self.assertEqual(by_model["M0"], by_model["M1"])


if __name__ == "__main__":
    unittest.main()
