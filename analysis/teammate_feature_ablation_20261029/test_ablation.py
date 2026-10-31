"""Tests for ablation.py.

Synthetic tests check structure only (column selection, LOSO isolation,
metric arithmetic, safety stops); they are not research evidence.  The
real-data test only checks that the new tool reproduces the stored baseline,
and is skipped when the local pilot files are absent.  The cross-check tests
compare saved results with the PI's 2026-10-26 diagnostics (same data, same
M0 settings) and are skipped when those files are absent.  The task B
observation tests back a sentence in summary.md (H5-F4 predicts exactly like
H5 although F4 is used in training) and are skipped when files are absent.
The change-source tests back summary.md tables 8 / B-8 and the related
limitation sentences; they read only the result JSONs in this folder.
The F0 reproducibility tests back f0_h5_comparison.md (task C): the pilot
CSVs have no face detection box and no per-shoulder 2D columns, and the
stored H5 F1..F5 equal the code formulas applied to the CSV's own 2D
columns.  They are skipped when the local pilot files are absent.

Run from the repository root:

    python -B -m unittest discover -s analysis/teammate_feature_ablation_20261029 -p "test_*.py"
"""

import csv
import json
import math
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
PI_ABLATION_JSON = REPO / "pilot/H9_feature_ablation_results_20261026.json"
PI_DIAGNOSTICS_JSON = REPO / "pilot/H9_feature_diagnostics_20261026.json"
DROP_ONE_JSON = HERE / "depth_drop_one.json"
H5_DROP_ONE_JSON = HERE / "h5_drop_one.json"


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


def average_ranks(v):
    """Ranks starting at 1, ties get their average rank (Spearman convention)."""
    order = np.argsort(v, kind="stable")
    ranks = np.empty(len(v))
    ranks[order] = np.arange(1, len(v) + 1)
    for value in np.unique(v):
        tied = v == value
        ranks[tied] = ranks[tied].mean()
    return ranks


@unittest.skipUnless(DROP_ONE_JSON.exists() and PI_ABLATION_JSON.exists(),
                     "A-2 result or PI ablation file not available")
class PiAblationCrossCheckTests(unittest.TestCase):
    """A-2 vs PI's 2026-10-26 M0 ablation (H9, H9-F8, H9-F9 were run by both)."""

    def test_overlapping_conditions_match_every_prediction(self):
        ours = json.loads(DROP_ONE_JSON.read_text(encoding="utf-8"))
        pi = json.loads(PI_ABLATION_JSON.read_text(encoding="utf-8-sig"))
        self.assertEqual([s["sample_key"] for s in pi["samples"]], ours["samples"]["sample_keys"])
        pairs = {"H9": ours["baseline"]["result"],
                 "H9-F8": ours["conditions"]["H9-F8"],
                 "H9-F9": ours["conditions"]["H9-F9"]}
        for name, result in pairs.items():
            with self.subTest(condition=name):
                self.assertEqual(pi["results"][name]["M0"]["predictions_by_seed"],
                                 result["predictions_per_seed"])


@unittest.skipUnless(P01_CSV.exists() and P02_CSV.exists() and PI_DIAGNOSTICS_JSON.exists()
                     and PI_ABLATION_JSON.exists(), "local pilot files not available")
class ReusedCorrelationCheckTests(unittest.TestCase):
    """Correlations reused in summary.md (A-3 item 4) equal a recompute on the 24 segments."""

    @classmethod
    def setUpClass(cls):
        cls.X, _, cls.participants, _ = ab.load_fixed_samples([P01_CSV, P02_CSV])
        cls.corr = json.loads(PI_DIAGNOSTICS_JSON.read_text(encoding="utf-8-sig"))["correlations"]
        cls.f8_f9 = json.loads(PI_ABLATION_JSON.read_text(encoding="utf-8-sig"))["correlations_f8_f9"]

    def test_pearson_and_spearman_match_recompute(self):
        groups = {"all_24": np.ones(len(self.X), dtype=bool),
                  "subject_P01_12": self.participants == "P01",
                  "subject_P02_12": self.participants == "P02"}
        for key, mask in groups.items():
            for i, a in enumerate(ab.FEATURE_IDS):
                for j, b in enumerate(ab.FEATURE_IDS):
                    with self.subTest(group=key, pair=f"{a}-{b}"):
                        r = np.corrcoef(self.X[mask, i], self.X[mask, j])[0, 1]
                        self.assertAlmostEqual(r, self.corr[key]["pearson"][a][b], places=6)
                        rho = np.corrcoef(average_ranks(self.X[mask, i]),
                                          average_ranks(self.X[mask, j]))[0, 1]
                        self.assertAlmostEqual(rho, self.corr[key]["spearman"][a][b], places=6)

    def test_f8_f9_values_in_ablation_file_match(self):
        self.assertAlmostEqual(np.corrcoef(self.X[:, 7], self.X[:, 8])[0, 1],
                               self.f8_f9["all_samples"], places=9)
        for subject in ("P01", "P02"):
            mask = self.participants == subject
            self.assertAlmostEqual(np.corrcoef(self.X[mask, 7], self.X[mask, 8])[0, 1],
                                   self.f8_f9["by_participant"][subject], places=9)


@unittest.skipUnless(P01_CSV.exists() and P02_CSV.exists() and H5_DROP_ONE_JSON.exists(),
                     "task B result or local pilot files not available")
class H5MinusF4ObservationTests(unittest.TestCase):
    """summary.md task B observation 5: H5-F4 predicts exactly like H5 although F4 is used."""

    def test_f4_removed_but_predictions_unchanged(self):
        result = json.loads(H5_DROP_ONE_JSON.read_text(encoding="utf-8"))
        condition = result["conditions"]["H5-F4"]
        self.assertEqual(condition["feature_ids"], ["F1", "F2", "F3", "F5"])
        self.assertEqual(condition["predictions_per_seed"],
                         result["baseline"]["result"]["predictions_per_seed"])

    def test_f4_has_positive_training_importance_in_h5_models(self):
        config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        model = config["model"]
        X, y, participants, _ = ab.load_fixed_samples([P01_CSV, P02_CSV])
        X5 = ab.select_columns(X, config["baselines"]["H5"]["features"])
        shares = []
        for seed in model["seeds"]:
            for subject in sorted(set(participants)):
                train = participants != subject
                forest = ab.rf.Forest(6, model["n_trees"], model["max_features"], None, seed)
                mdi = forest.fit(X5[train], y[train]).mdi
                shares.append(mdi[3] / mdi.sum())
        self.assertEqual(len(shares), 10)
        self.assertTrue(all(share > 0 for share in shares), shares)
        self.assertAlmostEqual(min(shares), 0.179, places=3)
        self.assertAlmostEqual(max(shares), 0.221, places=3)


RESULT_JSONS = [HERE / "depth_add_one.json", HERE / "depth_drop_one.json", H5_DROP_ONE_JSON]


@unittest.skipUnless(all(p.exists() for p in RESULT_JSONS), "result JSON files not available")
class ChangeSourceObservationTests(unittest.TestCase):
    """summary.md tables 8 / B-8: net change, changed predictions, changed segments."""

    # condition: (net correct change, predictions differing from baseline,
    #             {(participant, true class, segment id): (baseline correct seeds, condition correct seeds)})
    EXPECTED = {
        "H5+F6": (0, 19, {("P02", 0, "13"): (5, 2), ("P02", 1, "15"): (0, 3)}),
        "H5+F7": (7, 14, {("P01", 1, "3"): (0, 5), ("P02", 1, "15"): (0, 2)}),
        "H5+F8": (3, 16, {("P01", 1, "3"): (0, 5), ("P02", 0, "13"): (5, 3)}),
        "H5+F9": (-5, 17, {("P02", 0, "13"): (5, 0)}),
        "H9-F6": (-2, 9, {("P01", 0, "13"): (3, 0), ("P01", 1, "3"): (3, 4),
                          ("P02", 0, "13"): (1, 3), ("P02", 1, "15"): (2, 0)}),
        "H9-F7": (-7, 9, {("P01", 0, "13"): (3, 0), ("P01", 1, "3"): (3, 1),
                          ("P02", 0, "13"): (1, 0), ("P02", 1, "15"): (2, 1)}),
        "H9-F8": (-1, 13, {("P01", 0, "1"): (5, 4), ("P01", 0, "13"): (3, 0), ("P01", 1, "3"): (3, 0),
                           ("P02", 0, "13"): (1, 4), ("P02", 1, "15"): (2, 5)}),
        "H9-F9": (5, 13, {("P01", 0, "1"): (5, 4), ("P01", 0, "13"): (3, 0), ("P01", 1, "3"): (3, 5),
                          ("P02", 0, "13"): (1, 5), ("P02", 1, "15"): (2, 5)}),
        "H5-F1": (-5, 5, {("P02", 0, "13"): (5, 0)}),
        "H5-F2": (1, 6, {("P01", 0, "1"): (0, 1)}),
        "H5-F3": (-3, 7, {("P02", 0, "13"): (5, 2)}),
        "H5-F4": (0, 0, {}),
        "H5-F5": (-2, 17, {("P02", 0, "13"): (5, 3)}),
    }

    @classmethod
    def setUpClass(cls):
        cls.results = [json.loads(p.read_text(encoding="utf-8")) for p in RESULT_JSONS]

    def test_change_sources_match_summary_tables(self):
        seen = set()
        observed = {}
        for result in self.results:
            y = result["samples"]["y_true"]
            participants = result["samples"]["participants"]
            keys = result["samples"]["sample_keys"]
            base = result["baseline"]["result"]["predictions_per_seed"]
            for name, condition in result["conditions"].items():
                with self.subTest(condition=name):
                    pred = condition["predictions_per_seed"]
                    seeds = range(len(base))
                    net = sum((pred[s][i] == y[i]) - (base[s][i] == y[i])
                              for s in seeds for i in range(len(y)))
                    changed = sum(pred[s][i] != base[s][i] for s in seeds for i in range(len(y)))
                    segments = {}
                    for i in range(len(y)):
                        before = sum(base[s][i] == y[i] for s in seeds)
                        after = sum(pred[s][i] == y[i] for s in seeds)
                        if before != after:
                            segments[(participants[i], y[i], keys[i][2])] = (before, after)
                    self.assertEqual((net, changed, segments), self.EXPECTED[name])
                    seen.add(name)
                    observed[name] = set(segments)
        self.assertEqual(seen, set(self.EXPECTED))
        # summary.md overall line under table 8: 5 segments in total, P02 P0 #13 in 10 of 13
        self.assertEqual(len(set().union(*observed.values())), 5)
        self.assertEqual(sum(("P02", 0, "13") in s for s in observed.values()), 10)

    def test_training_folds_and_h5_never_predicts_p1(self):
        for result in self.results:
            y = result["samples"]["y_true"]
            for name, condition in result["conditions"].items():
                for fold in condition["folds"]:
                    with self.subTest(condition=name, seed=fold["seed"],
                                      held_out=fold["held_out_participant"]):
                        train = [y[i] for i in fold["train_indices"]]
                        self.assertEqual(len(train), 12)
                        self.assertEqual(sorted(train), sorted(list(range(6)) * 2))
            if result["baseline"]["name"] == "H5":
                predictions = result["baseline"]["result"]["predictions_per_seed"]
                self.assertEqual(sum(p.count(1) for p in predictions), 0)


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def finite_or_none(text):
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@unittest.skipUnless(P01_CSV.exists() and P02_CSV.exists(), "local pilot files not available")
class F0ReproducibilityTests(unittest.TestCase):
    """f0_h5_comparison.md sections 2 and 4: CSV columns and H5 formulas."""

    @classmethod
    def setUpClass(cls):
        cls.tables = {"P01": read_csv_rows(P01_CSV), "P02": read_csv_rows(P02_CSV)}

    def test_csv_has_no_face_box_or_per_shoulder_2d_columns(self):
        for subject, (columns, _) in self.tables.items():
            with self.subTest(subject=subject):
                self.assertEqual(len(columns), 161)
                lowered = [c.lower() for c in columns]
                for word in ("face_x", "face_y", "face_w", "face_h", "face_area", "bbox", "box"):
                    self.assertFalse([c for c in lowered if word in c], word)
                for side in ("left", "right"):
                    self.assertNotIn(f"{side}_shoulder_2d_x_px", columns)
                    self.assertNotIn(f"{side}_shoulder_2d_y_px", columns)
                    self.assertIn(f"{side}_shoulder_3d_x_m", columns)
                for present in ("shoulder_midpoint_2d_x_px", "shoulder_width_px", "shoulder_tilt_deg"):
                    self.assertIn(present, columns)
                # 2D points stored per frame: no face outline, so no box or area can be redrawn
                points_2d = {c[:-len("_2d_x_px")] for c in columns if c.endswith("_2d_x_px")}
                self.assertEqual(points_2d, {
                    "nose", "left_eye", "right_eye", "left_ear", "right_ear", "chin",
                    "ear_midpoint", "eye_midpoint", "hipless_f1_head_center",
                    "hipless_chest_roi_center", "shoulder_midpoint", "hip_midpoint",
                    "exploratory_neck_proxy", "exploratory_upper_chest_proxy"})

    def test_h5_formulas_match_stored_values(self):
        stored_names = dict(zip(("F1", "F2", "F3", "F4", "F5"), (
            "hipless_f1_candidate_head_center_dx_sw", "hipless_f1_candidate_head_center_dy_sw",
            "hipless_f1_candidate_face_axis_tilt_deg", "hipless_f1_candidate_ear_eye_dy_sw",
            "hipless_f1_candidate_nose_chin_distance_sw")))
        expected = {"P01": (3613, 0), "P02": (2553, 36)}
        for subject, (_, rows) in self.tables.items():
            missing = 0
            for row in rows:
                def point(name):
                    x = finite_or_none(row[f"{name}_2d_x_px"])
                    y = finite_or_none(row[f"{name}_2d_y_px"])
                    return None if x is None or y is None else (x, y)

                six = [point(n) for n in ("left_eye", "right_eye", "left_ear", "right_ear", "nose", "chin")]
                shoulder_mid, eye_mid = point("shoulder_midpoint"), point("eye_midpoint")
                ear_mid, nose, chin = point("ear_midpoint"), point("nose"), point("chin")
                width = finite_or_none(row["shoulder_width_px"])
                calc = dict.fromkeys(stored_names)
                if all(six) and shoulder_mid and width and width > 1e-6:
                    center = (sum(p[0] for p in six) / 6, sum(p[1] for p in six) / 6)
                    calc["F1"] = (center[0] - shoulder_mid[0]) / width
                    calc["F2"] = (center[1] - shoulder_mid[1]) / width
                if eye_mid and chin and math.hypot(chin[0] - eye_mid[0], chin[1] - eye_mid[1]) > 1e-6:
                    calc["F3"] = math.degrees(math.atan2(chin[0] - eye_mid[0], chin[1] - eye_mid[1]))
                if ear_mid and eye_mid and width and width > 1e-6:
                    calc["F4"] = (ear_mid[1] - eye_mid[1]) / width
                if nose and chin and width and width > 1e-6:
                    calc["F5"] = math.hypot(nose[0] - chin[0], nose[1] - chin[1]) / width
                stored = {k: finite_or_none(row[name]) for k, name in stored_names.items()}
                if all(v is None for v in stored.values()):
                    missing += 1
                for k in stored_names:
                    if stored[k] is None or calc[k] is None:
                        self.assertIsNone(stored[k], (subject, k))
                        self.assertIsNone(calc[k], (subject, k))
                    else:
                        self.assertAlmostEqual(calc[k], stored[k], places=9, msg=(subject, k))
            self.assertEqual((len(rows), missing), expected[subject])

    def test_p01_row_count_only_coincides_with_baseline_frame_count(self):
        stable = {subject: sum(r["label"] not in ("PREP", "TRANSITION") for r in rows)
                  for subject, (_, rows) in self.tables.items()}
        self.assertEqual(stable, {"P01": 1939, "P02": 1674})
        baseline = json.loads((HERE / "baseline_check.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["samples"]["input_frame_count"], sum(stable.values()))


if __name__ == "__main__":
    unittest.main()
