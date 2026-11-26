"""Independent M3-G candidate for H9-v2 (F1..F8+C3), design section 5.

Only the feature-order distribution changes: draw up to two distinct nonempty
groups uniformly without replacement, then one remaining feature per group.
With one group left, draw up to two of its remaining features. Randomize each
batch's order and finish the entire nine-column permutation before inspecting
any split. The inherited Tree retains its two-column budget, constant-column
fallback, raw Gini, midpoint/tie rules and soft leaf probabilities.

Arrays must already be finite, eligible H9-v2 aggregates in FEATURE_NAMES order;
column meaning cannot be inferred from numeric arrays. No aggregation, labels,
participant splitting, calibration, file I/O or experiment runner is added.
This implementation and synthetic tests do not authorize formal evaluation.
"""

import numpy as np

from h9_v2 import H9_V2_FEATURE_NAMES
from rf_experiment import Forest, Tree


FEATURE_NAMES = H9_V2_FEATURE_NAMES
FEATURE_GROUPS = ((0, 1, 2, 3, 4), (5, 6, 7), (8,))
N_FEATURES = 9


def grouped_feature_permutation(rng):
    """Return all nine indices once, following the fixed 5/3/1 group law.

    No values, labels, MDI or split gains are consulted. At the first batch,
    each unordered group pair has probability 1/3; a feature's inclusion
    probability is 2/(3*group_size), before any constant-column fallback.
    """

    remaining = [list(group) for group in FEATURE_GROUPS]
    order = []
    while any(remaining):
        active = [g for g, features in enumerate(remaining) if features]
        if len(active) >= 2:
            selected = rng.choice(active, size=2, replace=False)
        else:
            selected = [active[0]] * min(2, len(remaining[active[0]]))
        batch = []
        for g in selected:
            features = remaining[g]
            batch.append(features.pop(int(rng.integers(len(features)))))
        order.extend(rng.permutation(batch).tolist())
    return np.asarray(order, dtype=int)


class _GroupedFeatureRNG:
    """Per-tree adapter for the sole RNG operation used by Tree._grow.

    This is not a general Generator replacement. It leaves the source tree
    stream local and never alters rf_experiment classes or module globals.
    """

    def __init__(self, source):
        self.source = source

    def permutation(self, n):
        if n != N_FEATURES:
            raise ValueError("M3-G requires exactly nine H9-v2 features")
        return grouped_feature_permutation(self.source)


class M3GTree(Tree):
    """Reuse the unchanged RF Tree; unit weights make the score raw Gini."""

    def __init__(self, n_classes, rng):
        super().__init__(n_classes, 2, np.ones(N_FEATURES), _GroupedFeatureRNG(rng))


def _feature_matrix(X, *, allow_empty=False):
    X = np.asarray(X, dtype=float)
    if X.ndim != 2 or X.shape[1] != N_FEATURES:
        raise ValueError("M3-G requires a two-dimensional H9-v2 matrix with nine columns")
    if (not allow_empty and len(X) == 0) or not np.isfinite(X).all():
        raise ValueError("M3-G requires finite eligible H9-v2 inputs; no imputation")
    return X


class M3GForest(Forest):
    """M3-G forest: 500 trees by default, fixed max_features=2, seed=0.

    n_trees may be reduced explicitly for synthetic structural tests. There
    is no split-weight, group-selection or max_features tuning interface.
    Bootstrap/tree seed derivation and MDI accumulation match Forest.fit;
    its small construction loop is repeated because it hardcodes Tree.
    Tree fitting/traversal and Forest.predict are reused unchanged.
    """

    def __init__(self, n_classes, n_trees=500, seed=0):
        for name, value in (("n_classes", n_classes), ("n_trees", n_trees)):
            if (isinstance(value, (bool, np.bool_))
                    or not isinstance(value, (int, np.integer)) or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        super().__init__(n_classes, n_trees, 2, None, seed)

    def fit(self, X, y):
        X = _feature_matrix(X)
        y = np.asarray(y)
        if (y.shape != (len(X),) or y.dtype.kind not in "iu"
                or np.any(y < 0) or np.any(y >= self.K)):
            raise ValueError("M3-G labels must be sample-aligned integers in 0..n_classes-1")

        boot_seed, tree_seed = np.random.SeedSequence(self.seed).spawn(2)
        boot_rng = np.random.default_rng(boot_seed)
        tree_seeds = tree_seed.spawn(self.T)
        Y1h = np.eye(self.K)[y]
        self.trees, mdi = [], np.zeros(X.shape[1])
        for seed in tree_seeds:
            b = boot_rng.integers(0, len(X), len(X))
            rng = np.random.default_rng(seed)
            t = M3GTree(self.K, rng).fit(X[b], Y1h[b])
            self.trees.append(t)
            mdi += t.mdi / max(t.mdi.sum(), 1e-12)
        self.mdi = mdi / self.T
        return self

    def _prediction_inputs(self, X):
        if not hasattr(self, "trees"):
            raise ValueError("M3-G must be fitted before prediction")
        return _feature_matrix(X, allow_empty=True)

    def predict(self, X):
        return super().predict(self._prediction_inputs(X))

    def predict_proba(self, X):
        """Average existing soft leaf probabilities, without hard voting."""

        X = self._prediction_inputs(X)
        return sum(tree.predict_proba(X) for tree in self.trees) / self.T
