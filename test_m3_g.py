"""Synthetic M3-G structural checks only; no participant data or accuracy claims.

Run: python -B -m unittest -v test_m3_g
"""

import copy
from fractions import Fraction
from itertools import combinations
import unittest
from unittest.mock import patch

import numpy as np

import h9_v2
import m3_g as m3
import rf_experiment as rf


class FirstBatchRNG:
    """Choose an enumerated first batch, then use a real RNG for the tail."""

    def __init__(self, groups, positions, reverse):
        self.groups, self.positions = groups, iter(positions)
        self.reverse = reverse
        self.source = np.random.default_rng(4321)
        self.first_choice = True
        self.first_order = True

    def choice(self, active, size, replace):
        if self.first_choice:
            self.first_choice = False
            assert tuple(active) == (0, 1, 2) and size == 2 and not replace
            return np.array(self.groups)
        return self.source.choice(active, size=size, replace=replace)

    def integers(self, high):
        return next(self.positions, None) if self.first_order else self.source.integers(high)

    def permutation(self, batch):
        if self.first_order:
            self.first_order = False
            return np.array(batch[::-1] if self.reverse else batch)
        return self.source.permutation(batch)


class GroupPermutationTests(unittest.TestCase):
    def test_exact_partition_and_h9_v2_feature_order(self):
        self.assertEqual(m3.FEATURE_NAMES, h9_v2.H9_V2_FEATURE_NAMES)
        self.assertEqual(m3.FEATURE_NAMES[-1], "sagittal_torso_lean_deg")
        self.assertEqual(m3.FEATURE_GROUPS, ((0, 1, 2, 3, 4), (5, 6, 7), (8,)))
        self.assertEqual(m3.N_FEATURES, 9)

    def test_exhaustive_first_batch_probabilities_and_full_permutation(self):
        inclusion = [Fraction(0) for _ in range(9)]
        total = Fraction(0)
        for g, h in combinations(range(3), 2):
            ng, nh = len(m3.FEATURE_GROUPS[g]), len(m3.FEATURE_GROUPS[h])
            for j in range(ng):
                for k in range(nh):
                    for reverse in (False, True):
                        order = m3.grouped_feature_permutation(
                            FirstBatchRNG((g, h), (j, k), reverse)
                        )
                        expected = [m3.FEATURE_GROUPS[g][j], m3.FEATURE_GROUPS[h][k]]
                        if reverse:
                            expected.reverse()
                        np.testing.assert_array_equal(order[:2], expected)
                        np.testing.assert_array_equal(np.sort(order), np.arange(9))
                        probability = Fraction(1, 3 * ng * nh * 2)
                        total += probability
                        for feature in order[:2]:
                            inclusion[feature] += probability
        self.assertEqual(total, 1)
        self.assertEqual(inclusion, [Fraction(2, 15)] * 5
                         + [Fraction(2, 9)] * 3 + [Fraction(2, 3)])

    def test_real_rng_group_and_feature_probabilities_and_no_replacement(self):
        rng = np.random.default_rng(20261027)
        draws = 12000
        inclusion, first, pairs = np.zeros(9), np.zeros(9), np.zeros(3)
        group_of = {feature: g for g, group in enumerate(m3.FEATURE_GROUPS) for feature in group}
        pair_index = {pair: i for i, pair in enumerate(combinations(range(3), 2))}
        for _ in range(draws):
            order = m3.grouped_feature_permutation(rng)
            self.assertEqual(sorted(order.tolist()), list(range(9)))
            # Check every batch, including the single-group tail, not only its prefix.
            remaining = set(range(9))
            for start in range(0, 9, 2):
                active = {group_of[f] for f in remaining}
                batch = order[start:start + 2]
                if len(active) >= 2:
                    self.assertEqual(len({group_of[f] for f in batch}), 2)
                remaining.difference_update(batch)
            inclusion[order[:2]] += 1
            first[order[0]] += 1
            pair = tuple(sorted(group_of[f] for f in order[:2]))
            pairs[pair_index[pair]] += 1
        expected = np.array([2 / 15] * 5 + [2 / 9] * 3 + [2 / 3])
        # Fixed seed; six binomial SDs, declared independently of observed counts.
        for actual, probabilities in ((inclusion, expected), (first, expected / 2),
                                      (pairs, np.full(3, 1 / 3))):
            tolerance = 6 * np.sqrt(probabilities * (1 - probabilities) / draws)
            self.assertTrue(np.all(np.abs(actual / draws - probabilities) <= tolerance))

    def test_permutation_is_deterministic_and_adapter_rejects_other_dimensions(self):
        left, right = np.random.default_rng(7), np.random.default_rng(7)
        for _ in range(30):
            np.testing.assert_array_equal(m3.grouped_feature_permutation(left),
                                          m3.grouped_feature_permutation(right))
        with self.assertRaisesRegex(ValueError, "nine"):
            m3._GroupedFeatureRNG(left).permutation(8)


class TreeSemanticsTests(unittest.TestCase):
    def fit_ordered(self, X, y, order):
        tree = m3.M3GTree(2, np.random.default_rng(0))
        with patch.object(m3, "grouped_feature_permutation", return_value=np.array(order)):
            tree.fit(X, np.eye(2)[y])
        return tree

    def test_existing_tree_methods_reused_with_unit_weights(self):
        tree = m3.M3GTree(2, np.random.default_rng(0))
        self.assertIs(m3.M3GTree.fit, rf.Tree.fit)
        self.assertIs(m3.M3GTree._grow, rf.Tree._grow)
        self.assertIs(m3.M3GTree.predict_proba, rf.Tree.predict_proba)
        self.assertEqual(tree.mf, 2)
        np.testing.assert_array_equal(tree.sw, np.ones(9))

    def test_raw_gini_wins_between_first_two_features(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        X = np.zeros((6, 9))
        X[:, 0] = [0, 0, 1, 1, 2, 2]  # best gain 1/4
        X[:, 8] = y                   # gain 1/2
        tree = self.fit_ordered(X, y, [0, 8, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(tree.feat[0], 8)
        self.assertEqual(tree.thr[0], 0.5)
        np.testing.assert_array_equal(np.argmax(tree.predict_proba(X), axis=1), y)

    def test_constant_prefix_fallback_stops_at_first_valid_later_feature(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        X = np.zeros((6, 9))
        X[:, 1] = [0, 0, 1, 1, 2, 2]
        X[:, 8] = y
        tree = self.fit_ordered(X, y, [0, 5, 1, 8, 2, 3, 4, 6, 7])
        self.assertEqual(tree.feat[0], 1)  # do not scan onward for the better F8/C3 gain

    def test_valid_zero_gain_prefix_keeps_budget_and_is_not_pruned(self):
        y = np.array([0, 1, 0, 1])
        X = np.zeros((4, 9))
        X[:, 0] = [0, 0, 1, 1]  # a valid zero-gain split
        X[:, 8] = y
        tree = self.fit_ordered(X, y, [0, 5, 8, 1, 2, 3, 4, 6, 7])
        self.assertEqual(tree.feat[0], 0)
        self.assertEqual(tree.mdi[0], 0.0)

    def test_feature_tie_uses_scan_order_and_threshold_tie_uses_first_maximum(self):
        y = np.array([0, 0, 1, 1])
        X = np.zeros((4, 9))
        X[:, 0] = X[:, 5] = y
        for prefix in ([5, 0], [0, 5]):
            order = prefix + [f for f in range(9) if f not in prefix]
            tree = self.fit_ordered(X, y, order)
            self.assertEqual(tree.feat[0], prefix[0])
        X = np.zeros((4, 9))
        X[:, 0] = np.arange(4)
        tree = self.fit_ordered(X, np.array([0, 1, 1, 0]), list(range(9)))
        self.assertEqual(tree.thr[0], 0.5)

    def test_all_constant_inputs_produce_soft_leaf_and_no_mdi(self):
        y = np.array([0, 0, 0, 1])
        tree = self.fit_ordered(np.ones((4, 9)), y, list(range(9)))
        self.assertEqual(tree.feat.tolist(), [-1])
        np.testing.assert_array_equal(tree.predict_proba(np.ones((2, 9))),
                                      [[0.75, 0.25], [0.75, 0.25]])
        np.testing.assert_array_equal(tree.mdi, np.zeros(9))

    def test_full_permutation_requested_once_per_impure_node(self):
        X = np.zeros((2, 9))
        X[1] = 1
        with patch.object(m3, "grouped_feature_permutation", wraps=m3.grouped_feature_permutation) as draw:
            tree = m3.M3GTree(2, np.random.default_rng(0)).fit(X, np.eye(2))
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(len(tree.feat), 3)
        with patch.object(m3, "grouped_feature_permutation", side_effect=AssertionError("pure node")):
            m3.M3GTree(2, np.random.default_rng(0)).fit(X[:1], np.array([[1, 0]]))


def synthetic_inputs():
    rng = np.random.default_rng(1234)
    X = rng.normal(size=(36, 9))
    X[:, 0] = np.arange(len(X))  # unique rows for exact bootstrap comparison
    y = np.tile(np.arange(3), 12)
    return X, y


def recorded_fit(model, X, y, *, extra_first_tree_draws=0):
    """Observe bootstrap rows and initial states; restore the patched test spy."""

    original = rf.Tree.fit
    records = []

    def observe(tree, X_boot, Y_boot):
        source = tree.rng.source if isinstance(tree.rng, m3._GroupedFeatureRNG) else tree.rng
        records.append((X_boot.copy(), copy.deepcopy(source.bit_generator.state)))
        result = original(tree, X_boot, Y_boot)
        if len(records) == 1:
            source.random(extra_first_tree_draws)
        return result

    with patch.object(rf.Tree, "fit", observe):
        model.fit(X, y)
    return records


class ForestSemanticsTests(unittest.TestCase):
    def test_defaults_and_actual_default_tree_count(self):
        model = m3.M3GForest(2)
        self.assertEqual((model.T, model.mf, model.seed), (500, 2, 0))
        self.assertIsNone(model.sw)
        X = np.repeat(np.arange(4, dtype=float)[:, None], 9, axis=1)
        self.assertIs(model.fit(X, np.array([0, 0, 1, 1])), model)
        self.assertEqual(len(model.trees), 500)

    def test_bootstraps_and_tree_initial_rng_states_match_existing_forest(self):
        X, y = synthetic_inputs()
        for seed in rf.H_EVAL_SEEDS:
            baseline = recorded_fit(rf.Forest(3, 5, 2, None, seed), X, y)
            candidate = recorded_fit(m3.M3GForest(3, 5, seed), X, y)
            for (expected_rows, expected_state), (rows, state) in zip(baseline, candidate):
                np.testing.assert_array_equal(rows, expected_rows)
                self.assertEqual(state, expected_state)

    def test_repeated_fits_predict_identically_and_do_not_mutate_inputs(self):
        X, y = synthetic_inputs()
        old_X, old_y = X.copy(), y.copy()
        for seed in rf.H_EVAL_SEEDS:
            left = m3.M3GForest(3, 5, seed).fit(X, y)
            right = m3.M3GForest(3, 5, seed).fit(X, y)
            np.testing.assert_array_equal(left.predict(X), right.predict(X))
            np.testing.assert_array_equal(left.predict_proba(X), right.predict_proba(X))
            np.testing.assert_array_equal(left.mdi, right.mdi)
            for first, second in zip(left.trees, right.trees):
                for field in ("feat", "thr", "left", "right", "value"):
                    np.testing.assert_array_equal(getattr(first, field), getattr(second, field))
        np.testing.assert_array_equal(X, old_X)
        np.testing.assert_array_equal(y, old_y)

    def test_different_seed_changes_bootstraps_and_extra_draws_do_not_change_later_trees(self):
        X, y = synthetic_inputs()
        base = m3.M3GForest(3, 5, 0)
        first = recorded_fit(base, X, y)
        changed = m3.M3GForest(3, 5, 0)
        second = recorded_fit(changed, X, y, extra_first_tree_draws=100)
        for (rows, state), (other_rows, other_state) in zip(first, second):
            np.testing.assert_array_equal(rows, other_rows)
            self.assertEqual(state, other_state)
        np.testing.assert_array_equal(base.predict_proba(X), changed.predict_proba(X))
        third = recorded_fit(m3.M3GForest(3, 5, 1), X, y)
        self.assertFalse(np.array_equal(first[0][0], third[0][0]))
        self.assertNotEqual(first[0][1], third[0][1])

    def test_inference_averages_soft_probabilities_and_uses_existing_prediction(self):
        # Three constant synthetic trees: hard majority=0, soft mean predicts 1.
        model = m3.M3GForest(2, 3)
        model.trees = []
        for counts in ((51, 49), (51, 49), (1, 99)):
            y = np.repeat(np.arange(2), counts)
            model.trees.append(m3.M3GTree(2, np.random.default_rng(0)).fit(
                np.zeros((100, 9)), np.eye(2)[y]))
        X = np.zeros((2, 9))
        expected = np.tile([103 / 300, 197 / 300], (2, 1))
        np.testing.assert_allclose(model.predict_proba(X), expected, rtol=0, atol=1e-15)
        np.testing.assert_array_equal(model.predict(X), [1, 1])
        np.testing.assert_array_equal(model.predict(X), rf.Forest.predict(model, X))
        self.assertEqual(model.predict_proba(np.empty((0, 9))).shape, (0, 2))
        self.assertEqual(model.predict(np.empty((0, 9))).shape, (0,))

    def test_invalid_inputs_fail_closed_without_imputation(self):
        X, y = synthetic_inputs()
        for args in ((0,), (2, 0), (True,), (2, 1.5)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                m3.M3GForest(*args)
        invalid = [np.zeros((3, 8)), np.zeros(9), np.zeros((0, 9)),
                   np.full((3, 9), np.nan), np.full((3, 9), np.inf)]
        for bad in invalid:
            with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                m3.M3GForest(3, 2).fit(bad, np.zeros(len(bad), dtype=int))
        for bad_y in (y[:-1], y.astype(float), y[:, None], np.full(len(y), -1),
                      np.full(len(y), 3), np.zeros(len(y), dtype=bool)):
            with self.assertRaisesRegex(ValueError, "labels"):
                m3.M3GForest(3, 2).fit(X, bad_y)
        with self.assertRaisesRegex(ValueError, "fitted"):
            m3.M3GForest(3).predict(X)
        model = m3.M3GForest(3, 2).fit(X, y)
        for bad in (np.zeros((2, 8)), np.full((2, 9), np.nan)):
            with self.assertRaises(ValueError):
                model.predict_proba(bad)
            with self.assertRaises(ValueError):
                model.predict(bad)


if __name__ == "__main__":
    unittest.main()
