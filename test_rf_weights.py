"""Weight policy and synthetic RF checks; no research accuracy reproduction."""
import itertools
import unittest

import numpy as np

import rf_experiment as rf


class RankWeightsTests(unittest.TestCase):
    def test_6_feature_backward_compatibility(self):
        paper_weights = [0.30, 0.20, 0.15, 0.15, 0.15, 0.05]
        cases = list(itertools.permutations(range(6)))
        cases += [(0, 0, 0, 0, 0, 0), (2, 1, 2, 0, 1, 0)]
        for values in cases:
            mdi = np.array(values, dtype=float)
            # Preserve the original assignment, including tied-MDI ordering.
            expected = np.zeros(6)
            for rank, j in enumerate(np.argsort(-mdi)):
                expected[j] = paper_weights[rank]
            with self.subTest(mdi=values):
                np.testing.assert_array_equal(rf.rank_weights(mdi), expected)

    def test_4_feature_rank_weights(self):
        mdi = np.array([0.10, 0.60, 0.05, 0.25])
        weights = rf.rank_weights(mdi)
        np.testing.assert_allclose(weights, [0.1875, 0.375, 0.1875, 0.250],
                                   rtol=0, atol=1e-15)
        np.testing.assert_allclose(weights[np.argsort(-mdi)],
                                   [0.375, 0.250, 0.1875, 0.1875], rtol=0, atol=1e-15)

    def test_1_to_5_positive_normalized(self):
        for p in range(1, 6):
            for mdi in (np.arange(p, dtype=float), np.zeros(p)):
                with self.subTest(p=p, mdi=mdi.tolist()):
                    weights = rf.rank_weights(mdi)
                    self.assertEqual(weights.shape, (p,))
                    self.assertTrue(np.all(weights > 0))
                    self.assertAlmostEqual(float(weights.sum()), 1.0)

    def test_mdi_magnitudes_do_not_change_rank_weights(self):
        for p in range(1, 6):
            mdi = np.arange(p, dtype=float)
            with self.subTest(p=p):
                np.testing.assert_array_equal(rf.rank_weights(mdi),
                                              rf.rank_weights(np.exp(mdi)))

    def test_more_than_6_features_raises(self):
        for p in (7, 8, 12):
            with self.subTest(p=p), self.assertRaisesRegex(
                ValueError, "at most 6 features; define a weighting policy explicitly"
            ):
                rf.rank_weights(np.arange(p, dtype=float))


class FourFeatureSanityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(20260929)
        X = rng.normal(size=(120, 4))
        scores = np.column_stack((X[:, 0] + X[:, 1], X[:, 2] - X[:, 3],
                                  X[:, 0] - X[:, 2]))
        y = np.argmax(scores + rng.normal(scale=0.4, size=scores.shape), axis=1)
        cls.X_eval = np.vstack((X, rng.normal(size=(60, 4))))
        cls.models = {seed: rf.fit_models(X, y, 3, 12, seed, [0.0])[0]
                      for seed in (0, 7, 42)}

    def test_m0_equals_m1(self):
        for seed, models in self.models.items():
            with self.subTest(seed=seed):
                np.testing.assert_array_equal(models["M0"](self.X_eval),
                                              models["M1"](self.X_eval))

    def test_m0_equals_m2_lambda_zero(self):
        for seed, models in self.models.items():
            with self.subTest(seed=seed):
                np.testing.assert_array_equal(models["M0"](self.X_eval),
                                              models["M2(λ=0)"](self.X_eval))


if __name__ == "__main__":
    unittest.main()
