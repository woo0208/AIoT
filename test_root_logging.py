"""Read-only root observations and provenance, using synthetic data only."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import rf_experiment as rf
from patch5_test_fixtures import mocked_model_inputs


class RootStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(19)
        cls.X = rng.normal(size=(60, 6))
        cls.y = np.tile(np.arange(5), 12)
        cls.models, _ = rf.fit_models(cls.X, cls.y, 5, 12, 7, [0, 0.5, 1])

    def test_counts_match_split_tree_count(self):
        for model in self.models.values():
            stats = rf.root_statistics(model.forest, "all")
            self.assertEqual(stats["total_trees"], 12)
            self.assertEqual(sum(stats["counts"].values()), stats["split_trees"])
            self.assertEqual(stats["split_trees"], sum(t.feat[0] >= 0 for t in model.forest.trees))
            self.assertEqual(stats["split_trees"] + stats["leaf_only_trees"], 12)

    def test_percentages_sum_to_100(self):
        for model in self.models.values():
            stats = rf.root_statistics(model.forest, "all")
            self.assertGreater(stats["split_trees"], 0)
            self.assertAlmostEqual(sum(stats["percentages"].values()), 100)

    def test_leaf_only_trees(self):
        forest = rf.Forest(5, 4, seed=2).fit(np.zeros((10, 6)), np.zeros(10, dtype=int))
        stats = rf.root_statistics(forest, "all")
        self.assertEqual(stats["total_trees"], 4)
        self.assertEqual(stats["split_trees"], 0)
        self.assertEqual(stats["leaf_only_trees"], 4)
        self.assertEqual(stats["root_feature_indices"], [None] * 4)
        self.assertTrue(all(count == 0 for count in stats["counts"].values()))
        self.assertTrue(all(value is None for value in stats["percentages"].values()))
        json.dumps(stats, allow_nan=False)

    def test_feature_index_mapping(self):
        expected = {
            "all": ["A", "x_c", "y_c", "thetaL", "thetaR", "theta1"],
            "invariant": ["A", "thetaL", "thetaR", "theta1"],
            "relative": ["A", "delta_x_c", "delta_y_c", "delta_thetaL", "delta_thetaR", "delta_theta1"],
        }
        for mode, names in expected.items():
            # Unequal counts make an incorrect index/name mapping observable.
            roots = [i for i in range(len(names)) for _ in range(i + 1)]
            forest = SimpleNamespace(mdi=np.zeros(len(names)),
                                     trees=[SimpleNamespace(feat=np.array([i])) for i in roots])
            with self.subTest(mode=mode):
                stats = rf.root_statistics(forest, mode)
                self.assertEqual(stats["feature_names"], names)
                self.assertEqual(stats["counts"], {name: i + 1 for i, name in enumerate(names)})
                self.assertEqual(stats["root_feature_indices"], roots)

    def test_mixed_split_and_leaf_denominator(self):
        forest = SimpleNamespace(mdi=np.zeros(4), trees=[SimpleNamespace(feat=np.array([i]))
                                                        for i in (0, 1, -1, -1)])
        stats = rf.root_statistics(forest, "invariant")
        self.assertEqual(stats["split_trees"], 2)
        self.assertEqual(stats["percentages"], dict(A=50, thetaL=50, thetaR=0, theta1=0))

    def test_models_and_lambdas_recorded_separately(self):
        records, logs = {}, []
        rf.log_root_statistics(self.models, records, "synthetic", "all", "S1", logs.append)
        self.assertEqual(set(records), {"M0", "M1", "M2(λ=0)", "M2(λ=0.5)", "M2(λ=1)"})
        for name, lam in (("M0", None), ("M1", None), ("M2(λ=0)", 0), ("M2(λ=0.5)", 0.5), ("M2(λ=1)", 1)):
            record = records[name][0]
            self.assertEqual(record["model"], name)
            self.assertEqual(record["lambda"], lam)
            self.assertEqual(record["seed"], 7)
            self.assertEqual(record["tree_count"], 12)
            self.assertEqual(record["max_features"], 2)
            self.assertEqual(record["held_out_subject"], "S1")
            self.assertEqual(record["root_statistics"], rf.root_statistics(self.models[name].forest, "all"))
        self.assertIsNot(records["M2(λ=0.5)"][0], records["M2(λ=1)"][0])
        roots0 = records["M0"][0]["root_statistics"]["root_feature_indices"]
        roots1 = records["M1"][0]["root_statistics"]["root_feature_indices"]
        self.assertEqual(records["M1"][0]["root_features_equal_m0"], roots0 == roots1)
        self.assertTrue(any("M1 root features identical to M0:" in line for line in logs))

    def test_observation_preserves_predictions_and_rng_states(self):
        predictions = {name: model(self.X) for name, model in self.models.items()}
        states = {name: [copy.deepcopy(t.rng.bit_generator.state) for t in model.forest.trees]
                  for name, model in self.models.items()}
        rf.log_root_statistics(self.models, {}, "synthetic", "all", None, lambda _: None)
        for name, model in self.models.items():
            np.testing.assert_array_equal(predictions[name], model(self.X))
            self.assertEqual(states[name], [t.rng.bit_generator.state for t in model.forest.trees])


class RootProvenanceIntegrationTests(unittest.TestCase):
    def run_main(self, observe=True):
        rng = np.random.default_rng(21)
        X = rng.normal(size=(15, 6))
        y = np.tile(np.arange(5), 3)
        groups = np.repeat(["S1", "S2", "S3"], 5)
        meta = [("P01", "1", i + 1, label) for i, label in enumerate(rf.LAB5)]
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(rf, "OUT_DIR", directory))
            stack.enter_context(patch.object(rf, "plot"))
            stack.enter_context(patch("sys.argv", ["rf_experiment.py", "--features", "all", "invariant", "relative",
                                                   "--ours", "P01", "--multiposture", "synthetic.csv",
                                                   "--trees", "3", "--seeds", "2", "--lams", "0.5", "1"]))
            if not observe:
                stack.enter_context(patch.object(rf, "log_root_statistics"))
            with mocked_model_inputs(rf, directory, (X, y, groups), (X[:5], y[:5], meta), (X, y, groups)):
                rf.main()
            with Path(directory, "rf_results.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            return rows, Path(directory, "rf_results.txt").read_text(encoding="utf-8")

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.logs = cls().run_main()

    def test_csv_covers_tracks_models_seeds_and_folds(self):
        self.assertEqual(len(self.rows), 28)  # A/C x 3 feature sets, plus B; 4 models each.
        for row in self.rows:
            records = json.loads(row["root_provenance"])
            external = row["dataset"].startswith("C_")
            self.assertEqual(len(records), 2 if external else 6)
            self.assertEqual({r["seed"] for r in records}, {0, 1})
            self.assertEqual({r["held_out_subject"] for r in records},
                             {None} if external else {"S1", "S2", "S3"})
            expected_mode = row["features"] or "all"  # B already uses all features.
            for record in records:
                self.assertEqual(record["feature_set"], expected_mode)
                self.assertEqual(record["model"], row["model"])
                self.assertEqual(record["tree_count"], 3)
                self.assertEqual(record["max_features"], 2)
                self.assertTrue(record["dataset"].startswith("C_" if external else row["dataset"][:3]))
                self.assertEqual(len(record["root_statistics"]["feature_names"]),
                                 4 if expected_mode == "invariant" else 6)
        self.assertIn("percentage denominator=root split trees", self.logs)

    def test_logging_preserves_every_existing_metric(self):
        before, old_logs = self.run_main(observe=False)
        before = [{k: v for k, v in row.items() if k not in rf.RESULT_LINEAGE_FIELDS} for row in before]
        after = [{key: value for key, value in row.items()
                  if key != "root_provenance" and key not in rf.RESULT_LINEAGE_FIELDS} for row in self.rows]
        self.assertEqual(before, after)
        lines = iter(self.logs.splitlines())
        self.assertTrue(all(any(line == expected for line in lines) for expected in old_logs.splitlines()))


if __name__ == "__main__":
    unittest.main()
