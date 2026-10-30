"""Tests for ablation.py.

Synthetic tests check structure only (column selection, LOSO isolation,
metric arithmetic, safety stops); they are not research evidence.  The
real-data test only checks that the new tool reproduces the stored baseline,
and is skipped when the local pilot files are absent.

Run from the repository root:

    python -B -m unittest discover -s analysis/teammate_feature_ablation_20261029 -p "test_*.py"
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ablation as ab  # noqa: E402

REPO = ab.REPO
P01_CSV = REPO / "pilot_data/P01_h9_20261024_170900.csv"
P02_CSV = REPO / "pilot_data/P02_h9_20261024_173954.csv"
BASELINE_JSON = REPO / "pilot/h6_pilot_20261024_174708.json"


def synthetic(per_class=2, seed=0):
    """Two participants, six classes, nine columns; column j carries value j*100+class."""
    rng = np.random.default_rng(seed)
    rows, y, participants = [], [], []
    for subject in ("P01", "P02"):
        for k in range(6):
            for _ in range(per_class):
                rows.append([j * 100 + k + rng.normal(0, 0.1) for j in range(9)])
                y.append(k)
                participants.append(subject)
    return np.array(rows), np.array(y), np.array(participants)


class SelectColumnsTests(unittest.TestCase):
    def test_keeps_requested_columns_in_h9_order(self):
        X, _, _ = synthetic()
        out = ab.select_columns(X, ["F1", "F2", "F3", "F4", "F5", "F8"])
        np.testing.assert_array_equal(out, X[:, [0, 1, 2, 3, 4, 7]])

    def test_rejects_bad_requests(self):
        X, _, _ = synthetic()
        for bad in ([], ["F1", "F1"], ["F10"], ["F2", "F1"], ["f1"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ab.select_columns(X, bad)

    def test_config_conditions_are_valid_and_match_guide(self):
        config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        X, _, _ = synthetic()
        h5 = ["F1", "F2", "F3", "F4", "F5"]
        h9 = h5 + ["F6", "F7", "F8", "F9"]
        expected = {
            "A-1_depth_add_one": {f"H5+{f}": h5 + [f] for f in ("F6", "F7", "F8", "F9")},
            "A-2_depth_drop_one": {f"H9-{f}": [g for g in h9 if g != f]
                                   for f in ("F6", "F7", "F8", "F9")},
            "B_h5_drop_one": {f"H5-{f}": [g for g in h5 if g != f] for f in h5},
        }
        for task, conds in expected.items():
            self.assertEqual(config["conditions"][task]["conditions"], conds)
            for ids in conds.values():
                ab.select_columns(X, ids)  # must not raise


class LosoTests(unittest.TestCase):
    def test_folds_never_mix_train_and_test_participants(self):
        X, y, participants = synthetic()
        preds, folds = ab.loso_m0(X, y, participants, seeds=[0, 1], n_trees=5, max_features=2)
        self.assertEqual(len(folds), 4)
        for fold in folds:
            train, test = set(fold["train_indices"]), set(fold["test_indices"])
            self.assertFalse(train & test)
            self.assertEqual(train | test, set(range(len(y))))
            self.assertEqual(set(participants[list(test)]), {fold["held_out_participant"]})
            self.assertNotIn(fold["held_out_participant"], set(participants[list(train)]))
        for p in preds:
            self.assertTrue(((p >= 0) & (p < 6)).all())

    def test_test_participant_rows_never_reach_fit(self):
        X, y, participants = synthetic()
        seen = []
        real_fit = ab.rf.Forest.fit

        def spy(self, Xtr, ytr):
            seen.append(Xtr.copy())
            return real_fit(self, Xtr, ytr)

        with mock.patch.object(ab.rf.Forest, "fit", spy):
            ab.loso_m0(X, y, participants, seeds=[0], n_trees=3, max_features=2)
        for Xtr, held_out in zip(seen, ("P01", "P02")):
            test_rows = X[participants == held_out]
            for row in test_rows:
                self.assertFalse(np.any(np.all(np.isclose(Xtr, row), axis=1)))

    def test_matches_existing_fit_models_m0(self):
        X, y, participants = synthetic(per_class=3, seed=1)
        preds, _ = ab.loso_m0(X, y, participants, seeds=[0, 3], n_trees=20, max_features=2)
        for seed, pred in zip([0, 3], preds):
            expected = np.empty(len(y), dtype=int)
            for subject in ("P01", "P02"):
                test = participants == subject
                models, _ = ab.rf.fit_models(X[~test], y[~test], 6, 20, seed, [])
                expected[test] = models["M0"](X[test])
            np.testing.assert_array_equal(pred, expected)

    def test_each_condition_retrains_with_only_its_columns(self):
        X, y, participants = synthetic()
        widths = []
        real_fit = ab.rf.Forest.fit

        def spy(self, Xtr, ytr):
            widths.append(Xtr.shape[1])
            return real_fit(self, Xtr, ytr)

        with mock.patch.object(ab.rf.Forest, "fit", spy):
            ab.evaluate_condition(X, y, participants, ["F1", "F2", "F3", "F4", "F5", "F6"],
                                  seeds=[0, 1], n_trees=3, max_features=2)
        self.assertEqual(widths, [6, 6, 6, 6])  # 2 seeds x 2 folds, all newly fitted

    def test_rejects_training_fold_missing_a_class(self):
        X, y, participants = synthetic()
        drop = (participants == "P02") & (y == 3)
        with self.assertRaises(ValueError):
            ab.loso_m0(X[~drop], y[~drop], participants[~drop], [0], 3, 2)


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.y = np.array([0, 0, 1, 1, 1, 1, 2, 3, 4, 5, 5, 5])
        self.p = np.array([0, 1, 0, 5, 5, 1, 2, 3, 4, 5, 5, 0])

    def test_confusion_matrix_and_accuracy_agree(self):
        s = ab.scores(self.y, self.p)
        cm = np.array(s["confusion_matrix"])
        self.assertEqual(cm.sum(), len(self.y))
        np.testing.assert_array_equal(cm.sum(1), np.bincount(self.y, minlength=6))
        self.assertAlmostEqual(s["accuracy"], np.trace(cm) / cm.sum())
        self.assertEqual(s["accuracy"], 7 / 12)

    def test_p1_errors_and_per_class(self):
        s = ab.scores(self.y, self.p)
        self.assertEqual((s["p1_to_p0"], s["p1_to_p5"]), (1, 2))
        self.assertEqual(s["per_class"]["P1"]["recall"], 0.25)
        self.assertEqual(s["per_class"]["P1"]["precision"], 0.5)
        self.assertEqual(s["per_class"]["P5"]["precision"], 0.5)

    def test_macro_f1_matches_manual_value(self):
        s = ab.scores(self.y, self.p)
        cm = np.array(s["confusion_matrix"])
        prec = np.diag(cm) / np.maximum(cm.sum(0), 1)
        rec = np.diag(cm) / cm.sum(1)
        f1 = np.where(prec + rec > 0, 2 * prec * rec / np.where(prec + rec > 0, prec + rec, 1), 0)
        self.assertAlmostEqual(s["macro_f1"], f1.mean())

    def test_delta_is_zero_against_itself_and_in_pp(self):
        X, y, participants = synthetic()
        r = ab.evaluate_condition(X, y, participants, ["F1", "F2"], [0], 3, 2)
        d = ab.delta_pp(r, r)
        self.assertEqual(d["pooled"]["accuracy"], 0)
        other = json.loads(json.dumps(r))
        other["pooled"]["summary"]["accuracy"] += 0.05
        for subject in other["by_participant"]:
            other["by_participant"][subject]["summary"]["accuracy"] += 0.05
        self.assertAlmostEqual(ab.delta_pp(other, r)["pooled"]["accuracy"], 5.0)

    def test_by_participant_uses_only_that_participants_rows(self):
        X, y, participants = synthetic()
        r = ab.evaluate_condition(X, y, participants, ["F1", "F2"], [0], 3, 2)
        for subject, block in r["by_participant"].items():
            cm = np.array(block["per_seed"][0]["confusion_matrix"])
            self.assertEqual(cm.sum(), int(np.sum(participants == subject)))


class SafetyStopTests(unittest.TestCase):
    def test_wrong_input_hash_stops(self):
        config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            a, b, base = (Path(tmp) / n for n in ("a.csv", "b.csv", "base.json"))
            for f in (a, b, base):
                f.write_text("not the real file", encoding="utf-8")
            with self.assertRaises(SystemExit):
                ab.verify_inputs(config, [a, b], base)

    def test_baseline_mismatch_is_detected(self):
        X, y, participants = synthetic()
        r = ab.evaluate_condition(X, y, participants, ["F1", "F2"], [0], 3, 2)
        keys = [["run", "rec", str(i)] for i in range(len(y))]
        cms = [s["confusion_matrix"] for s in r["pooled"]["per_seed"]]
        stored = dict(eligible_sample_keys=keys, metrics=[dict(
            feature_set="H5", model="M0", confusion_matrices=cms,
            accuracy=r["pooled"]["summary"]["accuracy"],
            macro_f1=r["pooled"]["summary"]["macro_f1"])])
        self.assertTrue(ab.check_against_stored_baseline(r, stored, "H5", keys)["all_identical"])
        stored["metrics"][0]["accuracy"] += 0.01
        self.assertFalse(ab.check_against_stored_baseline(r, stored, "H5", keys)["all_identical"])
        stored["metrics"][0]["accuracy"] -= 0.01
        self.assertFalse(ab.check_against_stored_baseline(r, stored, "H5", keys[::-1])["all_identical"])

    def test_refuses_to_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "exists.json"
            out.write_text("{}", encoding="utf-8")
            argv = ["ablation.py", "--task", "A-1", "--probe-csv", "a", "b",
                    "--baseline-json", "c", "--out", str(out)]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(ab, "run_task") as run:
                with self.assertRaises(SystemExit):
                    ab.main()
                run.assert_not_called()
            self.assertEqual(out.read_text(encoding="utf-8"), "{}")


@unittest.skipUnless(P01_CSV.exists() and P02_CSV.exists() and BASELINE_JSON.exists(),
                     "local pilot files not available")
class RealBaselineReproductionTests(unittest.TestCase):
    """New tool vs stored h6_pilot M0: must be identical (software check only)."""

    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        ab.verify_inputs(cls.config, [P01_CSV, P02_CSV], BASELINE_JSON)
        cls.stored = json.loads(BASELINE_JSON.read_text(encoding="utf-8-sig"))
        cls.X, cls.y, cls.participants, cls.keys = ab.load_fixed_samples([P01_CSV, P02_CSV])

    def test_fixed_sample_set(self):
        self.assertEqual(len(self.keys), 24)
        self.assertEqual(self.keys, self.stored["eligible_sample_keys"])
        self.assertEqual(sorted(np.bincount(self.y).tolist()), [4] * 6)

    def test_h5_and_h9_reproduce_exactly(self):
        model = self.config["model"]
        for name in ("H5", "H9"):
            with self.subTest(baseline=name):
                r = ab.evaluate_condition(self.X, self.y, self.participants,
                                          self.config["baselines"][name]["features"],
                                          model["seeds"], model["n_trees"], model["max_features"])
                check = ab.check_against_stored_baseline(r, self.stored, name, self.keys)
                self.assertTrue(check["all_identical"], check)


if __name__ == "__main__":
    unittest.main()
