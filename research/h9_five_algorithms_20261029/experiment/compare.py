"""Isolated, fixed-plan H9-original five-classifier pilot comparison.

This script never imports from or writes into the original source directory.
Use --prepare before --evaluate. Outputs are exclusive, never overwritten.
"""
from collections import Counter
from datetime import datetime, timezone
import argparse
import csv
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pickle
import platform
import subprocess
import sys
import time
import warnings

import numpy as np

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT / 'source'))
import h6_offline as h6
import f1_sample_aggregator as agg
import rf_experiment as rf
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC, SVC
from threadpoolctl import threadpool_info, threadpool_limits

SEEDS = (0, 1, 2, 3, 4)
NAMES = ('M0', 'SVM-RBF', 'Linear-SVM', 'Logistic-Regression', 'KNN')
CSV_NAMES = ('P01_h9_20261024_170900.csv', 'P02_h9_20261024_173954.csv')
EXPECTED_CSV_HASHES = ('1d8f0c7e40b87f750bb4a351f52ed55b083a1c37e777a2e9088f54111ded3122',
                       '6bbad505e9333e4029fe1be155e73ce745c9709077b57fda65eb49e3fc8b9f2e')


def digest(p):
    with Path(p).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write_new(name, value):
    with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


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


def model_parameters():
    params = {}
    for name in NAMES:
        model = make_model(name, 0)
        params[name] = (dict(implementation='unchanged rf_experiment.Forest',
                            n_classes=6, n_trees=500, max_features=2,
                            split_w=None, criterion='gini', bootstrap=True,
                            seed='each of 0,1,2,3,4') if name == 'M0'
                        else model.get_params(deep=False))
    return params


def load_samples():
    for name, expected in zip(CSV_NAMES, EXPECTED_CSV_HASHES):
        assert digest(OUT / 'inputs' / name) == expected, name
    samples = h6.load_labeled_probe_h_samples([OUT / 'inputs' / n for n in CSV_NAMES])
    eligible = [s for s in samples if s.eligible]
    audit = h6.aggregation_audit(samples)
    assert len(samples) == len(eligible) == 24 and audit['common_valid_frame_count'] == 3613
    assert audit['excluded_sample_count'] == audit['excluded_frame_count'] == 0
    X = np.asarray([s.ordered_values('H9') for s in eligible], dtype=np.float64)
    y = np.asarray([h6.LAB6.index(h6.analysis_label(s.label)) for s in eligible])
    subjects = np.asarray([s.subject for s in eligible])
    assert X.shape == (24, 9) and np.isfinite(X).all()
    assert Counter(subjects) == {'P01': 12, 'P02': 12}
    assert len({s.sample_key for s in eligible}) == 24
    old = read(OUT / 'inputs' / 'h6_pilot_20261024_174708.json')
    ablation = read(OUT / 'inputs' / 'H9_feature_ablation_results_20261026.json')
    assert list(h6.LAB6) == old['class_order']
    assert list(agg.H9_FEATURE_NAMES) == old['feature_order']['H9']
    assert [list(s.sample_key) for s in eligible] == old['eligible_sample_keys']
    assert (old['tree_count'], old['max_features'], old['seeds']) == (500, 2, list(SEEDS))
    for i, (sample, previous) in enumerate(zip(eligible, ablation['samples'])):
        assert list(sample.sample_key) == previous['sample_key']
        assert sample.subject == previous['subject'] and sample.label == previous['label']
        np.testing.assert_array_equal(X[i], previous['h9_values'])
        assert (sample.n_frames, sample.common_valid_count) == (
            old['samples'][i]['frame_count'], old['samples'][i]['common_valid_frame_count'])
    return samples, eligible, X, y, subjects, audit, old, ablation


def fold_plans(subjects, y):
    plans = []
    for held_out in ('P01', 'P02'):
        train = np.flatnonzero(subjects != held_out)
        test = np.flatnonzero(subjects == held_out)
        assert not set(train) & set(test) and len(train) == len(test) == 12
        assert set(subjects[train]).isdisjoint(subjects[test])
        assert set(y[train]) == set(y[test]) == set(range(6))
        plans.append(dict(held_out=held_out, train_indices=train.tolist(),
                          test_indices=test.tolist(), train_subjects=sorted(set(subjects[train])),
                          test_subjects=sorted(set(subjects[test]))))
    return plans


def environment():
    names = ('numpy', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl', 'narwhals', 'cloudpickle')
    return dict(python=platform.python_version(), executable=sys.executable,
                platform=platform.platform(), processor=platform.processor(),
                machine=platform.machine(), logical_cpu_count=os.cpu_count(),
                packages={n: importlib.metadata.version(n) for n in names})


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


def structural_checks():
    # Synthetic values are used only to check metric bookkeeping and scaler leakage.
    y = np.repeat(np.arange(6), 2)
    p = y.copy(); p[2] = 0; p[3] = 5
    m = metrics(y, p)
    assert m['p1_errors']['P1_to_P0']['count'] == m['p1_errors']['P1_to_P5']['count'] == 1
    assert m['per_class'][1]['recall'] == 0 and m['accuracy'] == 10 / 12
    train = np.arange(108, dtype=float).reshape(12, 9)
    scaler = StandardScaler().fit(train)
    before = scaler.mean_.copy(), scaler.scale_.copy(), int(scaler.n_samples_seen_)
    scaler.transform(np.full((12, 9), 1e6))
    np.testing.assert_array_equal(scaler.mean_, before[0])
    np.testing.assert_array_equal(scaler.scale_, before[1])
    assert int(scaler.n_samples_seen_) == before[2] == 12
    return dict(metric_bookkeeping='PASS', held_out_transform_does_not_fit_scaler='PASS',
                synthetic_data='structural checks only; excluded from research metrics')


def prepare():
    assert not (OUT / 'PLAN.json').exists()
    _, eligible, X, y, subjects, audit, _, _ = load_samples()
    checks = structural_checks()
    data = dict(feature_order=list(agg.H9_FEATURE_NAMES), matrix=X.tolist(), labels=y.tolist(),
                subjects=subjects.tolist(), sample_keys=[list(s.sample_key) for s in eligible],
                class_order=list(h6.LAB6), aggregation_audit=audit)
    write_new('samples.json', data)
    plan = dict(kind='fixed exploratory offline classifier comparison; not execution approval',
                created_utc=datetime.now(timezone.utc).isoformat(), authority='explicit user request: P01/P02 six-class comparison',
                feature_set='original H9 F1..F9; no H9-v2, feature removal, recalibration or imputation',
                sample_count=24, seeds=list(SEEDS), folds=fold_plans(subjects, y),
                model_parameters=model_parameters(),
                preprocessing={'M0': 'raw original H9 to reproduce the unchanged baseline',
                               'other_four': 'StandardScaler mean and population SD fit on 12 training samples only; transform held-out without refit'},
                tuning='none; one fixed setting per model; no validation-based model or parameter search',
                seed_interpretation='five paired computational repeats, not independent participants; deterministic models may repeat identical predictions',
                selection_rule='rank pooled mean Macro-F1, inspect both participant scores and P1 errors, then cost; propose at most two follow-up candidates, not validated winners',
                benchmark=dict(unit='one already aggregated float64 H9 sample', threads=1,
                               warmup_calls_per_fitted_model=24, timed_calls_per_fitted_model=120,
                               input_schedule='held-out 12 samples cycled in fixed source order',
                               order='rotate five models by seed plus fold; round-robin timed calls',
                               classifier_only='predict on preallocated transformed row; excludes scaling/aggregation/I/O/startup',
                               pipeline='scaler.transform plus predict on preallocated raw row, timed separately',
                               gc='disabled during measured loops; restored afterward',
                               clock='time.perf_counter_ns',
                               model_size='len(pickle.dumps(model, protocol=5)); uncompressed; pipeline includes scaler; libraries excluded'),
                environment=environment(), structural_checks=checks,
                samples_sha256=digest(OUT / 'samples.json'),
                script_sha256=digest(__file__),
                source_files=[dict(path=str(p.relative_to(OUT)), sha256=digest(p))
                              for p in sorted((OUT / 'source').glob('*.py'))],
                references={n: digest(OUT / 'inputs' / n) for n in
                            (*CSV_NAMES, 'h6_pilot_20261024_174708.json', 'H9_feature_ablation_results_20261026.json')},
                documentation_urls=[
                    'https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVC.html',
                    'https://scikit-learn.org/stable/modules/generated/sklearn.svm.LinearSVC.html',
                    'https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html',
                    'https://scikit-learn.org/stable/modules/generated/sklearn.neighbors.KNeighborsClassifier.html',
                    'https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html'])
    write_new('PLAN.json', plan)
    print('PASS: plan fixed before fitting; exact 24 original H9 samples and baseline indices verified', flush=True)


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


def benchmark(fitted, raw_test, order):
    rows = [np.ascontiguousarray(row.reshape(1, 9)) for row in raw_test]
    times = {name: dict(classifier_ns=[], pipeline_ns=[]) for name in order}
    transformed = {name: [scaler.transform(r) if scaler else r for r in rows]
                   for name, (model, scaler) in fitted.items()}
    for name in order:
        model, scaler = fitted[name]
        for i in range(24):
            model.predict(transformed[name][i % 12])
            model.predict(scaler.transform(rows[i % 12]) if scaler else rows[i % 12])
    enabled = gc.isenabled()
    gc.disable()
    try:
        for i in range(120):
            for name in order:
                model, scaler = fitted[name]; j = i % 12
                start = time.perf_counter_ns()
                model.predict(transformed[name][j])
                times[name]['classifier_ns'].append(time.perf_counter_ns() - start)
                start = time.perf_counter_ns()
                model.predict(scaler.transform(rows[j]) if scaler else rows[j])
                times[name]['pipeline_ns'].append(time.perf_counter_ns() - start)
    finally:
        if enabled:
            gc.enable()
    return times


def protected_verification():
    pin = read(OUT / 'input_identities.json')
    changed = [p['path'] for p in pin['protected_files'] if digest(p['path']) != p['sha256']]
    status = subprocess.run(['git', 'status', '--porcelain=v1', '--untracked-files=normal'],
                            cwd=pin['original_root'], text=True, capture_output=True, check=True).stdout.strip()
    assert not changed, changed
    assert status == pin['git_status'], 'original Git working status changed'
    return dict(status='PASS', protected_files=len(pin['protected_files']), changed_files=changed,
                original_git_status_unchanged=True, no_hardware_or_candidate_changes=True)


def evaluate():
    assert not (OUT / 'results.json').exists()
    plan = read(OUT / 'PLAN.json'); plan_sha = digest(OUT / 'PLAN.json')
    assert model_parameters() == plan['model_parameters']
    assert digest(__file__) == plan['script_sha256']
    assert digest(OUT / 'samples.json') == plan['samples_sha256']
    for item in plan['source_files']:
        assert digest(OUT / item['path']) == item['sha256']
    for name, expected in plan['references'].items():
        assert digest(OUT / 'inputs' / name) == expected
    protected_verification()
    _, eligible, X, y, subjects, audit, old, ablation = load_samples()
    frozen = read(OUT / 'samples.json')
    np.testing.assert_array_equal(X, frozen['matrix'])
    plans = fold_plans(subjects, y)
    assert plans == plan['folds']
    predictions = {name: np.full((5, 24), -1, dtype=int) for name in NAMES}
    folds = []; benchmarks = []; warning_records = []
    started = datetime.now(timezone.utc).isoformat()
    with threadpool_limits(limits=1):
        pools = threadpool_info()
        assert all(p['num_threads'] == 1 for p in pools)
        for si, seed in enumerate(SEEDS):
            assigned = np.zeros(24, dtype=int)
            for fi, binding in enumerate(plans):
                train = np.asarray(binding['train_indices']); test = np.asarray(binding['test_indices'])
                previous = next(f for f in old['folds'] if f['seed'] == seed and f['held_out_participant'] == binding['held_out'])
                assert previous['train_indices'] == train.tolist() and previous['test_indices'] == test.tolist()
                fold = dict(seed=seed, **binding, models={}); fitted = {}
                for name in NAMES:
                    scaler = None if name == 'M0' else StandardScaler().fit(X[train])
                    if scaler:
                        np.testing.assert_array_equal(scaler.mean_, X[train].mean(axis=0))
                        np.testing.assert_allclose(scaler.var_, X[train].var(axis=0), rtol=1e-14, atol=1e-15)
                        assert int(scaler.n_samples_seen_) == 12
                    tr = scaler.transform(X[train]) if scaler else X[train]
                    te = scaler.transform(X[test]) if scaler else X[test]
                    model = make_model(name, seed)
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter('always')
                        model.fit(tr, y[train])
                    for w in caught:
                        warning_records.append(dict(seed=seed, held_out=binding['held_out'], model=name,
                                                    category=w.category.__name__, message=str(w.message)))
                        if issubclass(w.category, ConvergenceWarning):
                            raise RuntimeError('fixed model failed to converge; no post-hoc parameter adjustment')
                    pred = np.asarray(model.predict(te))
                    assert pred.shape == (12,) and set(pred).issubset(range(6))
                    predictions[name][si, test] = pred
                    if scaler:
                        assert int(scaler.n_samples_seen_) == 12
                        np.testing.assert_array_equal(scaler.mean_, X[train].mean(axis=0))
                    serialized = pickle.dumps(model, protocol=5)
                    restored = pickle.loads(serialized)
                    np.testing.assert_array_equal(pred, restored.predict(te))
                    pipeline_bytes = pickle.dumps(dict(classifier=model, scaler=scaler), protocol=5)
                    restored_pipeline = pickle.loads(pipeline_bytes)
                    rs = restored_pipeline['scaler']
                    np.testing.assert_array_equal(pred, restored_pipeline['classifier'].predict(rs.transform(X[test]) if rs else X[test]))
                    fold['models'][name] = dict(predictions=pred.tolist(), metrics=metrics(y[test], pred),
                        scaler=None if scaler is None else dict(mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                                                               variance=scaler.var_.tolist(), n_samples_seen=12),
                        classifier_pickle_bytes=len(serialized), pipeline_pickle_bytes=len(pipeline_bytes),
                        serialization_roundtrip_predictions_equal=True,
                        n_iter=np.asarray(model.n_iter_).tolist() if hasattr(model, 'n_iter_') else None)
                    fitted[name] = model, scaler
                shift = (si + fi) % 5
                order = NAMES[shift:] + NAMES[:shift]
                benchmarks.append(dict(seed=seed, held_out=binding['held_out'], order=order,
                                       values=benchmark(fitted, X[test], order)))
                assigned[test] += 1; folds.append(fold)
                print(f'PASS fixed models + benchmark: seed={seed}, held_out={binding["held_out"]}', flush=True)
            assert np.all(assigned == 1)
    assert all(np.all(p >= 0) for p in predictions.values())
    results = {name: dict(predictions_by_seed=p.tolist(),
                         scopes={s: summary(y, p, np.ones(24, dtype=bool) if s == 'pooled' else subjects == s)
                                 for s in ('pooled', 'P01', 'P02')}) for name, p in predictions.items()}
    reference = next(m for m in old['metrics'] if m['feature_set'] == 'H9' and m['model'] == 'M0')
    m0 = results['M0']['scopes']['pooled']
    assert [r['confusion_matrix'] for r in m0['per_seed']] == reference['confusion_matrices']
    np.testing.assert_allclose([m0['mean']['accuracy'], m0['mean']['macro_f1']],
                               [reference['accuracy'], reference['macro_f1']], rtol=0, atol=1e-15)
    for scope in ('pooled', 'P01', 'P02'):
        prior = ablation['results']['H9']['M0'][scope]
        assert [r['confusion_matrix'] for r in results['M0']['scopes'][scope]['per_seed']] == [r['confusion_matrix'] for r in prior['per_seed']]
    costs = {}
    for name in NAMES:
        measures = {}
        for key in ('classifier_ns', 'pipeline_ns'):
            times = np.array([t for b in benchmarks for t in b['values'][name][key]], dtype=float) / 1e6
            assert len(times) == 1200
            measures[key.replace('_ns', '_ms')] = dict(n_calls=len(times), median=float(np.median(times)),
                p95=float(np.percentile(times, 95)), p99=float(np.percentile(times, 99)), mean=float(times.mean()))
        for key in ('classifier_pickle_bytes', 'pipeline_pickle_bytes'):
            sizes = [f['models'][name][key] for f in folds]
            measures[key] = dict(mean=float(np.mean(sizes)), min=min(sizes), max=max(sizes))
        costs[name] = measures
    delta = {name: {scope: {key + '_pp': 100 * (results[name]['scopes'][scope]['mean'][key] - results['M0']['scopes'][scope]['mean'][key])
                            for key in ('accuracy', 'macro_f1')} for scope in ('pooled', 'P01', 'P02')}
             for name in NAMES}
    verification = protected_verification()
    assert digest(OUT / 'PLAN.json') == plan_sha
    d = dict(kind='P01/P02 exploratory original-H9 offline five-algorithm comparison',
             started_utc=started, ended_utc=datetime.now(timezone.utc).isoformat(), plan_sha256=plan_sha,
             environment=environment(), threadpools_under_limit=pools, class_order=list(h6.LAB6),
             feature_order=list(agg.H9_FEATURE_NAMES), seeds=list(SEEDS), sample_count=24,
             aggregation_audit=audit, results=results, folds=folds, benchmark_raw=benchmarks,
             costs=costs, delta_from_existing_M0_pp=delta,
             p1_sample_predictions=[dict(subject=s.subject, segment=s.sample_key[-1], sample_key=list(s.sample_key),
                                         predictions={n: p[:, i].tolist() for n, p in predictions.items()})
                                    for i, s in enumerate(eligible) if y[i] == 1],
             warnings=warning_records, verification=dict(**verification, baseline_m0_all_seed_all_scope_confusion_matrices='EXACT MATCH',
                original_H9_24_sample_keys_order_values='EXACT MATCH', all_models_same_folds='PASS',
                training_only_scalers='PASS', independent_metric_crosscheck='PASS',
                model_pickle_roundtrips='50/50 PASS', structural_checks=structural_checks()),
             limitations=['Two participants and 24 repeated posture segments; not independent external validation.',
                          'Five seeds repeat the same observations; seed SD is not uncertainty across people.',
                          'Fixed settings compare these implementations, not optimized algorithm families.',
                          'M0 remains the original raw-input baseline; other four use train-fold scaling.',
                          'Timing excludes image inference, aggregation, capture, D455, display and startup.',
                          'Pickle size excludes libraries and is not RAM footprint or a deployable model artifact.',
                          'Candidate selection on this reused pilot requires new independent data later.'])
    write_new('results.json', d)
    print(json.dumps(dict(status='PASS', metrics={n: r['scopes']['pooled']['mean'] for n, r in results.items()},
                          costs=costs, warnings=warning_records), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true'); group.add_argument('--evaluate', action='store_true')
    args = parser.parse_args()
    prepare() if args.prepare else evaluate()
