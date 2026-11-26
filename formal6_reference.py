"""Reusable model factory and six-class metrics for the formal evaluation."""
import importlib.metadata
import os
import platform
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC, SVC

import f1_sample_aggregator as agg
import h6_offline as h6
import rf_experiment as rf


SEEDS = (0, 1, 2, 3, 4)


def make_model(name, seed):
    if name == 'M0':
        return rf.Forest(6, n_trees=500, max_features=2, split_w=None, seed=seed)
    if name == 'SVM-RBF':
        return SVC(C=1.0, kernel='rbf', gamma=1.0 / 9, shrinking=True,
                   probability=False, tol=1e-3, cache_size=200, class_weight=None,
                   max_iter=-1, decision_function_shape='ovr', break_ties=False,
                   random_state=seed)
    if name == 'Linear-SVM':
        return LinearSVC(C=1.0, penalty='l2', loss='squared_hinge', dual=False,
                         tol=1e-4, multi_class='ovr', fit_intercept=True,
                         intercept_scaling=1, class_weight=None, max_iter=10000,
                         random_state=seed)
    if name == 'Logistic-Regression':
        return LogisticRegression(C=1.0, l1_ratio=0.0, solver='lbfgs',
                                  tol=1e-4, fit_intercept=True, class_weight=None,
                                  max_iter=10000, random_state=seed)
    if name == 'KNN':
        return KNeighborsClassifier(n_neighbors=3, weights='uniform',
                                    algorithm='brute', metric='minkowski', p=2,
                                    metric_params=None, n_jobs=1)
    raise ValueError(name)


def metrics(y, prediction):
    cm = confusion_matrix(y, prediction, labels=range(6))
    pr, re, f1, support = precision_recall_fscore_support(
        y, prediction, labels=range(6), zero_division=0)
    accuracy = float(np.trace(cm) / cm.sum())
    macro = rf.macro_f1(y, prediction, 6)
    assert accuracy == accuracy_score(y, prediction)
    np.testing.assert_allclose(macro, f1_score(y, prediction, labels=range(6),
                                            average='macro', zero_division=0), rtol=0, atol=1e-15)
    assert list(cm.sum(1)) == list(support) and sum(support) == len(y)
    return dict(accuracy=accuracy, macro_f1=macro, confusion_matrix=cm.tolist(),
                per_class=[dict(posture=f'P{i}', label=h6.LAB6[i], support=int(support[i]),
                                precision=float(pr[i]), recall=float(re[i]), f1=float(f1[i]))
                           for i in range(6)],
                p1_errors={f'P1_to_P{k}': dict(count=int(cm[1, k]), support=int(support[1]),
                                             rate=float(cm[1, k] / support[1])) for k in (0, 5)})


def summary(y, predictions, mask):
    rows = [dict(seed=seed, **metrics(y[mask], p[mask])) for seed, p in zip(SEEDS, predictions)]
    return dict(sample_count=int(mask.sum()), per_seed=rows,
                mean={k: float(np.mean([r[k] for r in rows])) for k in ('accuracy', 'macro_f1')},
                sd_ddof0={k: float(np.std([r[k] for r in rows])) for k in ('accuracy', 'macro_f1')},
                mean_confusion_matrix=np.mean([r['confusion_matrix'] for r in rows], axis=0).tolist(),
                mean_per_class=[dict(posture=f'P{k}', label=h6.LAB6[k], support=rows[0]['per_class'][k]['support'],
                                     **{field: float(np.mean([r['per_class'][k][field] for r in rows]))
                                        for field in ('precision', 'recall', 'f1')}) for k in range(6)],
                mean_p1_errors={f'P1_to_P{k}': dict(
                    count=float(np.mean([r['p1_errors'][f'P1_to_P{k}']['count'] for r in rows])),
                    rate=float(np.mean([r['p1_errors'][f'P1_to_P{k}']['rate'] for r in rows])),
                    support=rows[0]['p1_errors'][f'P1_to_P{k}']['support']) for k in (0, 5)})


def environment():
    names = ('numpy', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl', 'narwhals', 'cloudpickle')
    return dict(python=platform.python_version(), executable=sys.executable,
                platform=platform.platform(), processor=platform.processor(),
                machine=platform.machine(), logical_cpu_count=os.cpu_count(),
                packages={n: importlib.metadata.version(n) for n in names})
