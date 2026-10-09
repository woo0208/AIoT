"""Synthetic evaluation-mask tests; predictions are controlled, not research results."""
import contextlib
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import rf_experiment as rf
from patch5_test_fixtures import mocked_model_inputs


def run_experiment(mode, module=rf):
    # A is a unique row identifier for controlled predictions in every feature mode.
    Xp = np.arange(60, dtype=float).reshape(10, 6)
    Xp[:, 0] = np.arange(1, 11)
    yp = np.tile(np.arange(5), 2)
    gp = np.repeat(["P1", "P2"], 5)
    Xo = np.arange(36, dtype=float).reshape(6, 6)
    Xo[:, 0] = np.arange(11, 17)
    yo = np.array([0, 1, 0, 2, -1, 3])
    labels = ["upright", "forward_head", "upright", "lean_back", "body_forward", "lean_left"]
    meta = [("P01", "1", i + 1, label) for i, label in enumerate(labels)]
    predictions = np.array([0, 1, 0, 3, 0] * 2 + [0, 1, 1, 2, 0, 0])
    training = []

    def fit(X, y, *args):
        training.append((X.copy(), y.copy()))
        predict = lambda X: predictions[X[:, 0].astype(int) - 1]
        return {name: predict for name in ("M0", "M1", "M2(λ=0)")}, np.ones(X.shape[1])

    with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
            patch.object(module, "OUT_DIR", directory), \
            patch.object(module, "fit_models", side_effect=fit), \
            patch.object(module, "plot") as plot, \
            patch.object(module, "loso", wraps=module.loso) as loso, \
            patch.object(module, "external", wraps=module.external) as external, \
            patch.object(module, "macro_f1", wraps=module.macro_f1) as f1, \
            patch("sys.argv", ["rf_experiment.py", "--features", mode, "--ours", "P01",
                               "--seeds", "1", "--trees", "2", "--lams", "0"]):
        with mocked_model_inputs(module, directory, (Xp, yp, gp), (Xo, yo, meta)):
            module.main()
        rows = plot.call_args.args[0]
        log = Path(directory, "rf_results.txt").read_text(encoding="utf-8")
        with Path(directory, "rf_results.csv").open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        return dict(rows=rows, csv_rows=csv_rows, log=log, training=training,
                    paper_ref=loso.call_args.kwargs.get("ref_mask"),
                    ours_ref=external.call_args.kwargs.get("ref_mask"),
                    f1_labels=[call.args[0].copy() for call in f1.call_args_list])


class RelativeEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {mode: run_experiment(mode) for mode in ("all", "invariant", "relative")}

    def test_reference_transform(self):
        X = np.array([[1, 10, 20, 30, 40, 70], [1.2, 12, 21, 31, 42, 73],
                      [1, 15, 25, 35, 45, 80], [0.8, 14, 24, 34, 43, 77]])
        groups = np.array(["A", "A", "B", "B"])
        reference = np.array([True, False, True, False])
        original = X.copy()
        transformed = rf.transform(X, groups, reference, "relative")
        np.testing.assert_array_equal(transformed[reference, 1:], np.zeros((2, 5)))
        np.testing.assert_array_equal(transformed[:, 0], X[:, 0])
        np.testing.assert_array_equal(X, original)

    def test_paper_reference_exclusion(self):
        run = self.runs["relative"]
        expected_ref = np.array([True, False, False, False, False] * 2)
        np.testing.assert_array_equal(run["paper_ref"], expected_ref)
        nonref_labels = np.tile(np.arange(5), 2)[~run["paper_ref"]]
        np.testing.assert_array_equal(nonref_labels, [1, 2, 3, 4] * 2)
        for row in run["rows"][:3]:
            self.assertEqual(row["relative_nonref_n"], 8)
            self.assertEqual(row["acc"], 0.6)
            self.assertEqual(row["relative_nonref_acc"], 0.5)
            self.assertAlmostEqual(row["relative_nonref_f1"], 0.5)
            self.assertIn("no upright class", row["relative_nonref_note"])
        masked_f1_labels = [labels for labels in run["f1_labels"] if len(labels) == 8]
        self.assertEqual(len(masked_f1_labels), 3)
        for labels in masked_f1_labels:
            np.testing.assert_array_equal(labels, nonref_labels)
        self.assertIn("참가자당 나머지 4개 posture", run["log"])
        self.assertIn("정상 class 평가 샘플 0개", run["log"])

    def test_ours_only_reference_upright_excluded(self):
        run = self.runs["relative"]
        np.testing.assert_array_equal(run["ours_ref"], [True, False, False, False, False, False])
        y = np.array([0, 1, 0, 2, -1, 3])
        np.testing.assert_array_equal((y >= 0) & ~run["ours_ref"],
                                      [False, True, True, True, False, True])
        for row in run["rows"][3:]:
            self.assertEqual(row["relative_nonref_n"], 4)
            self.assertEqual(row["relative_nonref_acc"], 0.5)
            self.assertAlmostEqual(row["relative_nonref_f1"], 5 / 12)
        self.assertIn("이후 upright 유지", run["log"])

    def test_body_forward_stays_excluded(self):
        # body_forward is always a mismatch (-1 vs a known prediction). Including
        # it would change full accuracy to 3/6 and non-reference accuracy to 2/5.
        for mode, run in self.runs.items():
            for row in run["rows"][3:]:
                with self.subTest(mode=mode, model=row["model"]):
                    self.assertEqual(row["acc"], 3 / 5)
                    if mode == "relative":
                        self.assertEqual(row["relative_nonref_acc"], 2 / 4)

    def test_all_invariant_and_relative_full_results_preserved(self):
        for mode, run in self.runs.items():
            if mode != "relative":
                self.assertIsNone(run["paper_ref"])
                self.assertIsNone(run["ours_ref"])
                self.assertNotIn("non-reference evaluation", run["log"])
            for i, row in enumerate(run["rows"]):
                with self.subTest(mode=mode, row=i):
                    expected = dict(dataset=(f"[A] 원 논문 Dataset.xlsx ({mode})" if i < 3
                                             else f"C_ours_external ({mode})"),
                                    model=("M0", "M1", "M2(λ=0)")[i % 3],
                                    features=mode, acc=0.6, acc_sd=0.0)
                    if i < 3:
                        expected.update(f1=0.5, f1_sd=0.0, min_subject_acc=0.6)
                    # Step 4 adds external diagnostics; preserve every original field.
                    legacy = {k: v for k, v in row.items()
                              if not k.startswith("external_") and k not in rf.RESULT_LINEAGE_FIELDS}
                    full = {k: v for k, v in legacy.items() if not k.startswith("relative_nonref_")}
                    self.assertEqual(full, expected)
                    if mode != "relative":
                        self.assertEqual(legacy, expected)

    def test_reference_remains_in_training_and_calibration(self):
        training = self.runs["relative"]["training"]
        self.assertEqual(len(training), 3)  # Two LOSO folds, then external training.
        for X, y in training:
            self.assertIn(len(y), (5, 10))
            np.testing.assert_array_equal(X[y == 0, 1:], np.zeros(((y == 0).sum(), 5)))
        self.assertEqual([int((y == 0).sum()) for _, y in training], [1, 1, 2])

    def test_additional_metrics_exported_without_overwriting_full_metrics(self):
        run = self.runs["relative"]
        self.assertEqual(len(run["csv_rows"]), 6)
        for i, row in enumerate(run["csv_rows"]):
            self.assertEqual(float(row["acc"]), 0.6)
            self.assertEqual(float(row["relative_nonref_acc"]), 0.5)
            self.assertEqual(int(row["relative_nonref_n"]), 8 if i < 3 else 4)
            self.assertIn("calibration upright excluded", row["relative_nonref_note"])
        self.assertIn("relative non-reference evaluation (calibration upright excluded)", run["log"])


if __name__ == "__main__":
    unittest.main()
