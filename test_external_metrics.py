"""Synthetic external metrics and loader logging checks, not research results."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import rf_experiment as rf


Y = np.array([0, 1, 0, 2, 3, 4, -1, -1])
PREDICTIONS = np.array([[0, 1, 1, 2, 0, 4, 4, 0], [0, 0, 0, 2, 3, 3, 0, 4]])
META = [(sub, "1", i + 1, rf.LAB5[y] if y >= 0 else "body_forward")
        for i, (sub, y) in enumerate(zip(["P01"] * 3 + ["P02"] * 3 + ["P01", "P03"], Y))]
REFERENCE = np.array([True, False, False, False, False, False, False, False])


def evaluate(y=Y, predictions=PREDICTIONS, meta=META, reference=REFERENCE, module=rf):
    logs, observed = [], []

    def fit(X, y, K, trees, seed, lams):
        def predict(X):
            observed.append(predictions[seed].copy())
            return predictions[seed].copy()
        return {name: predict for name in ("M0", "M1", "M2(λ=0)")}, np.ones(6)

    with patch.object(module, "fit_models", side_effect=fit):
        rows = module.external(np.zeros((5, 6)), np.arange(5), np.zeros((len(y), 6)),
                               y, meta, 5, 2, len(predictions), [0], logs.append,
                               ref_mask=reference)
    return rows, logs, observed


def load_fixture(module=rf):
    def row(round_, step, label, **values):
        return dict(round=str(round_), step=step, label=label, face_x=640, face_y=300,
                    rsh_x=500, rsh_y=450, lsh_x=780, lsh_y=450, oval_area_px=100) | values

    files = {
        "P01_r1_frames.csv": [row(1, 1, "upright"),
                              row(1, 2, "forward_head", face_x=""),
                              row(1, 2, "forward_head", face_x=646),
                              row(1, 3, "lean_left", face_x="", oval_area_px=""),
                              row(1, 4, "body_forward", oval_area_px=200),
                              row(1, 5, "lean_back", rsh_y="")],
        "P02_r2_frames.csv": [row(2, 1, "upright", oval_area_px=""), row(2, 2, "lean_right")],
        "P02_r3_frames.csv": [row(3, 1, "upright", oval_area_px=0), row(3, 2, "lean_right")],
        "P02_r4_frames.csv": [row(4, 1, "forward_head"), row(4, 2, "lean_back")],
        "P03_r1_frames.csv": [row(1, 1, "upright", face_x=""), row(1, 2, "lean_back")],
    }
    logs = []
    with tempfile.TemporaryDirectory() as directory, patch.object(module, "OUT_DIR", directory):
        for name, rows in files.items():
            with Path(directory, name).open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        # Older loaders have no logging argument; this also supports baseline comparison.
        import inspect
        kwargs = {"log": logs.append} if "log" in inspect.signature(module.load_ours).parameters else {}
        result = module.load_ours(["P01", "P02", "P03"], **kwargs)
    return result, logs


class ExternalMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.logs, cls.observed = evaluate()

    def test_accuracy_and_macro_f1(self):
        for row in self.rows:
            self.assertEqual(row["external_n"], 6)
            self.assertAlmostEqual(row["acc"], 4 / 6)
            expected = [19 / 30, 37 / 75]
            self.assertAlmostEqual(row["external_f1"], np.mean(expected))
            self.assertAlmostEqual(row["external_f1_sd"], np.std(expected))

    def test_confusion_matrix_orientation_counts_and_class_order(self):
        expected = np.array([
            [[1, 1, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0, 1, 0, 0], [1, 0, 0, 0, 0], [0, 0, 0, 0, 1]],
            [[2, 0, 0, 0, 0], [1, 0, 0, 0, 0], [0, 0, 1, 0, 0], [0, 0, 0, 1, 0], [0, 0, 0, 1, 0]]])
        for row in self.rows:
            matrices = np.array(json.loads(row["external_confusion_matrices"]))
            np.testing.assert_array_equal(matrices, expected)
            np.testing.assert_array_equal(matrices.sum(axis=(1, 2)), [6, 6])
            self.assertEqual(json.loads(row["external_class_order"]), rf.LAB5)

    def test_body_forward_excluded_from_all_metrics(self):
        keep = Y >= 0
        filtered, _, _ = evaluate(Y[keep], PREDICTIONS[:, keep],
                                  [item for item, yes in zip(META, keep) if yes], REFERENCE[keep])
        for before, after in zip(self.rows, filtered):
            for key in ("acc", "acc_sd", "external_f1", "external_f1_sd", "external_n",
                        "external_confusion_matrices", "external_recalls", "relative_nonref_f1"):
                self.assertEqual(before[key], after[key])
            self.assertEqual(json.loads(before["external_participants"])["P01"],
                             json.loads(after["external_participants"])["P01"])
        self.assertTrue(any("몸 전체 앞으로" in line and "M0가 판정" in line for line in self.logs))

    def test_participant_metrics_and_sample_counts(self):
        for row in self.rows:
            subjects = json.loads(row["external_participants"])
            self.assertEqual(sum(s["n"] for s in subjects.values()), 6)
            self.assertEqual([subjects[s]["n"] for s in ("P01", "P02", "P03")], [3, 3, 0])
            self.assertAlmostEqual(subjects["P01"]["acc"], 2 / 3)
            self.assertAlmostEqual(subjects["P01"]["f1"], 8 / 15)
            self.assertAlmostEqual(subjects["P02"]["f1"], 11 / 18)
            self.assertIsNone(subjects["P03"]["acc"])
            self.assertIsNone(subjects["P03"]["f1"])

    def test_posture_recall_and_absent_class(self):
        for row in self.rows:
            self.assertEqual(json.loads(row["external_recalls"]),
                             dict(zip(rf.LAB5, [0.75, 0.5, 1.0, 0.5, 0.5])))
        keep = Y != 4
        rows, logs, _ = evaluate(Y[keep], PREDICTIONS[:, keep],
                                 [item for item, yes in zip(META, keep) if yes], REFERENCE[keep])
        for row in rows:
            self.assertIsNone(json.loads(row["external_recalls"])["lean_right"])
        self.assertTrue(any("recall lean_right: N/A (n=0" in line for line in logs))

    def test_relative_f1_excludes_only_reference_and_unknown(self):
        for row in self.rows:
            self.assertEqual(row["relative_nonref_n"], 5)
            self.assertAlmostEqual(row["relative_nonref_acc"], 3 / 5)
            self.assertAlmostEqual(row["relative_nonref_f1"], 0.5)
            self.assertAlmostEqual(row["relative_nonref_f1_sd"], 1 / 30)

    def test_predictions_unchanged_by_reporting(self):
        np.testing.assert_array_equal(self.observed, np.repeat(PREDICTIONS, 3, axis=0))

    def test_new_metrics_saved_to_csv(self):
        from test_relative_eval import run_experiment
        run = run_experiment("relative")
        for row in run["csv_rows"][3:]:
            self.assertAlmostEqual(float(row["external_f1"]), 13 / 24)
            self.assertAlmostEqual(float(row["relative_nonref_f1"]), 5 / 12)
            self.assertEqual(np.sum(json.loads(row["external_confusion_matrices"])), 5)
            self.assertEqual(json.loads(row["external_participants"])["P01"]["n"], 5)
            self.assertIsNone(json.loads(row["external_recalls"])["lean_right"])

    def test_no_known_samples(self):
        keep = Y < 0
        rows, logs, _ = evaluate(Y[keep], PREDICTIONS[:, keep],
                                 [item for item, yes in zip(META, keep) if yes], REFERENCE[keep])
        for row in rows:
            self.assertTrue(np.isnan(row["acc"]))
            self.assertTrue(np.isnan(row["external_f1"]))
            self.assertTrue(np.isnan(row["relative_nonref_f1"]))
            self.assertEqual(np.sum(json.loads(row["external_confusion_matrices"])), 0)
            self.assertTrue(all(value is None for value in json.loads(row["external_recalls"]).values()))


class DropLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.logs = load_fixture()

    def test_included_samples_unchanged(self):
        X, y, meta = self.result
        self.assertEqual(meta, [("P01", "1", 1, "upright"), ("P01", "1", 2, "forward_head"),
                                ("P01", "1", 4, "body_forward"), ("P03", "1", 2, "lean_back")])
        np.testing.assert_array_equal(y, [0, 1, -1, 2])
        np.testing.assert_array_equal(X[:, 0], [1, 1, 2, 1])
        np.testing.assert_allclose(X[:, 1], [320, 324, 320, 320])

    def test_missing_reasons_and_sample_identity_logged(self):
        text = "\n".join(self.logs)
        self.assertIn("[DROP] P01 r1 step3 lean_left: missing feature median; missing features: face_x, oval_area_px", text)
        self.assertIn("[DROP] P01 r1 step5 lean_back: missing feature median; missing features: rsh_y", text)
        self.assertIn("[DROP] P02 r2 step2 lean_right: missing calibration oval_area_px", text)
        self.assertIn("[DROP] P02 r3 step2 lean_right: zero calibration oval_area_px", text)
        self.assertIn("[DROP] P02 r4 step1 forward_head: missing upright calibration", text)

    def test_drop_summary(self):
        self.assertEqual(sum(line.startswith("[DROP]") for line in self.logs), 9)
        self.assertIn("[OURS] loaded samples: 4; dropped samples: 9", self.logs)
        self.assertIn("   drop reason: missing upright calibration: 2", self.logs)
        self.assertIn("   drop reason: missing feature median: 4", self.logs)


if __name__ == "__main__":
    unittest.main()
