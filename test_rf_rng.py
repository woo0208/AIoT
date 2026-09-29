"""Synthetic structural checks only; run: python3 -m unittest -v test_rf_rng."""
import copy
import unittest
from unittest.mock import patch

import numpy as np

import rf_experiment as rf


class CountingRNG:
    def __init__(self, rng):
        self.rng = rng
        self.calls = 0

    def permutation(self, n):
        self.calls += 1
        return self.rng.permutation(n)


def fit_recorded(X, y, seed, trees=12, extra_first_tree_draws=0):
    """Observe actual bootstrap rows and initial RNG states without production hooks."""
    forests = []
    tree_fit = rf.Tree.fit

    class RecordedForest(rf.Forest):
        def fit(self, X, y):
            rows = {tuple(row): i for i, row in enumerate(X)}
            if len(rows) != len(X):
                raise AssertionError("Test data must have unique feature rows")
            self.bootstraps, self.initial_states, self.permutation_counts = [], [], []

            def record_fit(tree, X_boot, Y_boot):
                self.bootstraps.append(np.array([rows[tuple(row)] for row in X_boot]))
                self.initial_states.append(copy.deepcopy(tree.rng.bit_generator.state))
                counter = CountingRNG(tree.rng)
                tree.rng = counter
                result = tree_fit(tree, X_boot, Y_boot)
                self.permutation_counts.append(counter.calls)
                if len(self.bootstraps) == 1:
                    for _ in range(extra_first_tree_draws):
                        counter.permutation(X.shape[1])
                return result

            with patch.object(rf.Tree, "fit", record_fit):
                super().fit(X, y)
            forests.append(self)
            return self

    with patch.object(rf, "Forest", RecordedForest):
        models, weights = rf.fit_models(X, y, 3, trees, seed, [0.0, 0.5, 1.0])
    return models, weights, dict(zip(models, forests))


def probabilities(forest, X):
    # Forest exposes predictions only; inspect the existing tree probabilities.
    return sum(tree.predict_proba(X) for tree in forest.trees) / forest.T


class ForestRNGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(20260929)
        cls.X = rng.normal(size=(120, 6))
        scores = np.column_stack((cls.X[:, 0] + cls.X[:, 1],
                                  cls.X[:, 2] - cls.X[:, 3],
                                  cls.X[:, 4] + cls.X[:, 5]))
        cls.y = np.argmax(scores + rng.normal(scale=0.4, size=scores.shape), axis=1)
        cls.X_eval = np.vstack((cls.X, rng.normal(size=(60, 6))))
        cls.runs = {seed: fit_recorded(cls.X, cls.y, seed) for seed in (0, 7, 42)}

    def test_1_lambda_zero_predictions_and_probabilities(self):
        for seed, (models, _, forests) in self.runs.items():
            with self.subTest(seed=seed):
                np.testing.assert_array_equal(models["M0"](self.X_eval),
                                              models["M2(λ=0)"](self.X_eval))
                np.testing.assert_array_equal(probabilities(forests["M0"], self.X_eval),
                                              probabilities(forests["M2(λ=0)"], self.X_eval))

    def test_2_m0_m1_predictions_and_probabilities(self):
        for seed, (models, weights, forests) in self.runs.items():
            with self.subTest(seed=seed):
                np.testing.assert_array_equal(models["M0"](self.X_eval), models["M1"](self.X_eval))
                np.testing.assert_array_equal(probabilities(forests["M0"], self.X_eval),
                                              probabilities(forests["M1"], self.X_eval * weights))

    def test_3_bootstrap_and_tree_initial_state_pairing(self):
        for seed, (_, _, forests) in self.runs.items():
            base = forests["M0"]
            for name, forest in forests.items():
                self.assertEqual(len(forest.bootstraps), 12)
                for i, (expected, actual) in enumerate(zip(base.bootstraps, forest.bootstraps)):
                    with self.subTest(seed=seed, model=name, tree=i):
                        self.assertEqual(actual.shape, (len(self.X),))
                        np.testing.assert_array_equal(expected, actual)
                        self.assertEqual(base.initial_states[i], forest.initial_states[i])
            # Confirm positive lambda really exercises differing RNG consumption.
            self.assertTrue(any(base.permutation_counts != forests[name].permutation_counts
                                for name in ("M2(λ=0.5)", "M2(λ=1)")))

    def test_4_different_seed_changes_bootstraps_and_tree_states(self):
        base = self.runs[0][2]["M0"]
        for seed in (7, 42):
            other = self.runs[seed][2]["M0"]
            self.assertFalse(np.array_equal(base.bootstraps, other.bootstraps))
            self.assertNotEqual(base.initial_states, other.initial_states)

    def test_5_deterministic_rerun(self):
        models, weights, forests = fit_recorded(self.X, self.y, 0)
        old_models, old_weights, old_forests = self.runs[0]
        np.testing.assert_array_equal(weights, old_weights)
        for name, forest in forests.items():
            with self.subTest(model=name):
                np.testing.assert_array_equal(models[name](self.X_eval), old_models[name](self.X_eval))
                inputs = self.X_eval * weights if name == "M1" else self.X_eval
                np.testing.assert_array_equal(probabilities(forest, inputs),
                                              probabilities(old_forests[name], inputs))
                np.testing.assert_array_equal(forest.bootstraps, old_forests[name].bootstraps)
                self.assertEqual(forest.initial_states, old_forests[name].initial_states)

    def test_6_extra_tree_draws_cannot_change_later_trees(self):
        models, _, forests = fit_recorded(self.X, self.y, 0, extra_first_tree_draws=37)
        old_models, _, old_forests = self.runs[0]
        for name, forest in forests.items():
            with self.subTest(model=name):
                np.testing.assert_array_equal(forest.bootstraps, old_forests[name].bootstraps)
                self.assertEqual(forest.initial_states, old_forests[name].initial_states)
                np.testing.assert_array_equal(models[name](self.X_eval), old_models[name](self.X_eval))


if __name__ == "__main__":
    unittest.main()
