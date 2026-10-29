"""Preregistered primary5 pilot comparison and read-only fitted-tree diagnostics.

Run from repository root: python -B analysis/h9/stage6_20261028/evaluate.py
Uses existing feature/model implementations without overrides. New output only.
"""

from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import f1_sample_aggregator as agg
import h6_offline as h6
import h9_v2 as v2
import h9_v2_loso as ev
import m3_g as m3
import rf_experiment as rf

OUT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'analysis/h9/pilot_20261027_h9v2_loso_primary5/h9v2_loso_primary5_20261027.json'
SEEDS = (0, 1, 2, 3, 4)
TREES, MF, LAMBDA = 500, 2, 0.5
CLASSES = tuple(rf.LAB5)
M2 = 'M2(λ=0.5)'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def counts(values):
    return dict(sorted(Counter(int(x) for x in values).items()))


def metric_summary(y, predictions, mask):
    rows = [dict(seed=seed, **ev._metrics(y[mask], p[mask], CLASSES))
            for seed, p in zip(SEEDS, predictions)]
    out = dict(**ev._summary(rows), per_seed=rows)
    for key in ('recall', 'precision'):
        values = [row['classes'][1][key] for row in rows]
        out['p1_' + key + '_mean'] = float(np.mean(values))
        out['p1_' + key + '_seed_sd'] = float(np.std(values))
    cms = np.array([r['confusion_matrix'] for r in rows])
    out['confusion_matrix_seed_sum'] = cms.sum(0).tolist()
    out['major_errors'] = sorted([
        dict(actual=f'P{i}', predicted=f'P{j}', seed_sum=int(cms[:, i, j].sum()),
             mean_per_seed=float(cms[:, i, j].mean()))
        for i in range(5) for j in range(5) if i != j and cms[:, i, j].sum()],
        key=lambda r: (-r['seed_sum'], r['actual'], r['predicted']))
    return out


def path(tree, row, feature_names):
    node, visited = 0, []
    while tree.feat[node] >= 0:
        f = int(tree.feat[node])
        left = bool(row[f] <= tree.thr[node])
        visited.append(dict(node=node, depth=len(visited), feature=feature_names[f],
                            feature_index=f, threshold=float(tree.thr[node]),
                            value=float(row[f]), branch='left' if left else 'right'))
        node = int(tree.left[node] if left else tree.right[node])
    return dict(splits=visited, leaf_node=node, leaf_probabilities=tree.value[node].tolist(),
                leaf_argmax=int(np.argmax(tree.value[node])))


def tree_diagnostics(forest, Xtr, ytr, Xte, yte):
    """Inspect actual node arrays/leaf probabilities; no model mutations/refits."""
    roots, split_features, depths_by_feature = [], [], {f: [] for f in range(9)}
    c3_nodes, containing = [], 0
    probabilities, first_depths, path_lengths, visits = [], [], [], []
    for ti, tree in enumerate(forest.trees):
        root = int(tree.feat[0])
        roots.append(root)
        containing += int(np.any(tree.feat == 8))
        todo = [(0, 0, np.arange(len(Xtr)), np.arange(len(Xte)))]
        seen = set()
        while todo:
            node, depth, tr, te = todo.pop()
            assert node not in seen
            seen.add(node)
            f = int(tree.feat[node])
            if f < 0:
                continue
            split_features.append(f)
            depths_by_feature[f].append(depth)
            tr_left, te_left = Xtr[tr, f] <= tree.thr[node], Xte[te, f] <= tree.thr[node]
            if f == 8:
                c3_nodes.append(dict(tree_index=ti, node_index=node, depth=depth,
                                    threshold=float(tree.thr[node]),
                                    original_train_left=np.bincount(ytr[tr[tr_left]], minlength=5).tolist(),
                                    original_train_right=np.bincount(ytr[tr[~tr_left]], minlength=5).tolist(),
                                    test_left=np.bincount(yte[te[te_left]], minlength=5).tolist(),
                                    test_right=np.bincount(yte[te[~te_left]], minlength=5).tolist()))
            todo.extend([(int(tree.left[node]), depth + 1, tr[tr_left], te[te_left]),
                         (int(tree.right[node]), depth + 1, tr[~tr_left], te[~te_left])])
        assert len(seen) == len(tree.feat)
        prob = tree.predict_proba(Xte)
        td, tl, tv = [], [], []
        for i, row in enumerate(Xte):
            p = path(tree, row, v2.H9_V2_FEATURE_NAMES)
            np.testing.assert_array_equal(p['leaf_probabilities'], prob[i])
            c3 = [s['depth'] for s in p['splits'] if s['feature_index'] == 8]
            td.append(c3[0] if c3 else -1)
            tl.append(len(p['splits']))
            tv.append(len(c3))
        probabilities.append(prob)
        first_depths.append(td)
        path_lengths.append(tl)
        visits.append(tv)
    probabilities = np.asarray(probabilities)
    first_depths, path_lengths, visits = map(np.asarray, (first_depths, path_lengths, visits))
    soft = probabilities.mean(0)
    np.testing.assert_allclose(soft.sum(1), 1, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(soft.argmax(1), forest.predict(Xte))
    sample_rows = []
    for i in range(len(Xte)):
        row = dict(test_local_index=i, actual=int(yte[i]), predicted=int(soft[i].argmax()),
                   mean_probabilities=soft[i].tolist(),
                   tree_hard_predictions=np.bincount(probabilities[:, i].argmax(1), minlength=5).tolist(),
                   c3_path_tree_count=int((first_depths[:, i] >= 0).sum()),
                   c3_first_depth_histogram=counts(first_depths[first_depths[:, i] >= 0, i]),
                   c3_split_visits=int(visits[:, i].sum()),
                   mean_path_length=float(path_lengths[:, i].mean()))
        groups = {}
        for name, mask in (
            ('root_c3', np.array(roots) == 8), ('root_other', np.array(roots) != 8),
            ('path_c3', first_depths[:, i] >= 0), ('path_no_c3', first_depths[:, i] < 0)):
            p = probabilities[mask, i]
            groups[name] = dict(tree_count=len(p),
                                mean_probabilities=p.mean(0).tolist() if len(p) else None,
                                hard_prediction_counts=np.bincount(p.argmax(1), minlength=5).tolist() if len(p) else [0]*5,
                                wrong_tree_count=int((p.argmax(1) != yte[i]).sum()) if len(p) else 0)
        row['observational_tree_groups'] = groups
        assert row['c3_path_tree_count'] == sum(row['c3_first_depth_histogram'].values())
        sample_rows.append(row)
    assert len(c3_nodes) == len(depths_by_feature[8])
    return dict(total_trees=len(roots), root_feature_indices=roots,
                root_counts=counts(roots), internal_split_counts=counts(split_features),
                total_internal_splits=len(split_features),
                split_depth_histograms={f: counts(d) for f, d in depths_by_feature.items()},
                c3_split_count=len(c3_nodes), c3_tree_count=containing,
                c3_depth_mean=float(np.mean(depths_by_feature[8])) if c3_nodes else None,
                c3_nodes=c3_nodes, samples=sample_rows)


def comparison(a, b):
    def label(d, parts):
        if d >= .05 - 1e-12 and all(x >= -1e-12 for x in parts):
            return '개선 방향(탐색적)'
        if d <= -.05 + 1e-12 and all(x <= 1e-12 for x in parts):
            return '악화 방향(탐색적)'
        return '차이 불확실'
    out = {k + '_difference': a[k + '_mean'] - b[k + '_mean']
           for k in ('accuracy', 'macro_f1', 'p1_recall', 'p1_precision')}
    out['participants'] = {s: {k + '_difference': a['participants'][s][k + '_mean'] - b['participants'][s][k + '_mean']
                              for k in ('accuracy', 'macro_f1', 'p1_recall', 'p1_precision')}
                           for s in a['participants']}
    for metric in ('macro_f1', 'p1_recall'):
        key = metric + '_difference'
        out[metric + '_description'] = label(out[key], [p[key] for p in out['participants'].values()])
    out['paired_seed_differences'] = [dict(seed=seed, accuracy=ra['accuracy'] - rb['accuracy'],
                                         macro_f1=ra['macro_f1'] - rb['macro_f1'])
                                    for seed, ra, rb in zip(SEEDS, a['per_seed'], b['per_seed'])]
    return out


def main():
    target = OUT / 'results.json'
    if target.exists():
        raise FileExistsError(target)
    started = datetime.now(timezone.utc).isoformat()
    old = load(REFERENCE)
    assert (ev.SEEDS, ev.TREE_COUNT, ev.MAX_FEATURES, ev.M2_LAMBDA) == (SEEDS, TREES, MF, LAMBDA)
    assert ev._class_contract('primary5', None) == CLASSES
    assert (old['scope'], old['seeds'], old['trees'], old['max_features'], old['m2_lambda']) == ('primary5', list(SEEDS), TREES, MF, LAMBDA)
    ev._verify_files(old['inputs'] + old['code'])
    pinned = [rf.file_identity(p) for p in (REFERENCE, __file__, OUT/'PREREGISTRATION.md')]
    paths = [x['path'] for x in old['inputs']]
    sources = ev._probe_sources(paths)
    native = {'H9': h6.load_labeled_probe_h_samples(paths),
              'H9-v2': h6.load_labeled_probe_h9_v2_samples(paths)}
    v2_selected, v2_audit = ev._prepare_samples(native['H9-v2'], sources, CLASSES)
    bykey = {name: {s.sample_key: s for s in samples} for name, samples in native.items()}
    assert set(bykey['H9']) == set(bykey['H9-v2'])
    keys = [s.sample_key for s in v2_selected if bykey['H9'][s.sample_key].eligible]
    assert [list(k) for k in keys] == old['evaluated_sample_keys']
    support = []
    for key, a in bykey['H9'].items():
        b = bykey['H9-v2'][key]
        assert (a.subject, a.label, a.input_frame_indices) == (b.subject, b.label, b.input_frame_indices)
        row = dict(sample_key=key, subject=a.subject, label=a.label,
                   status='evaluated' if key in keys else ('outside_primary_class_set' if a.label not in CLASSES else 'outside_joint_eligible_samples'),
                   input_frame_indices=a.input_frame_indices,
                   common_support_equal=a.common_valid_frame_indices == b.common_valid_frame_indices)
        for name, sample in (('H9', a), ('H9-v2', b)):
            row[name] = dict(eligible=sample.eligible, reasons=sample.eligibility_reasons,
                             frame_count=sample.n_frames, common_valid_count=sample.common_valid_count,
                             common_coverage=sample.common_coverage,
                             common_valid_frame_indices=sample.common_valid_frame_indices,
                             missing_counts=dict(sample.missing_counts),
                             aggregated_features=dict(sample.features))
        row['h9_only_support'] = sorted(set(a.common_valid_frame_indices) - set(b.common_valid_frame_indices))
        row['v2_only_support'] = sorted(set(b.common_valid_frame_indices) - set(a.common_valid_frame_indices))
        support.append(row)
    feature_support = []
    names = tuple(dict.fromkeys((*agg.H9_FEATURE_NAMES, *v2.H9_V2_FEATURE_NAMES)))
    for source in sources:
        c = Counter()
        with open(source['path'], encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['label'] in h6.NON_EVALUATION_LABELS or h6.analysis_label(row['label']) not in CLASSES:
                    continue
                c['primary5_frames'] += 1
                for name in names:
                    if row[name].strip() and np.isfinite(float(row[name])):
                        c[name] += 1
        feature_support.append(dict(subject=source['subject'], counts=dict(c)))
    matrices = {'H9': np.array([bykey['H9'][k].ordered_values('H9') for k in keys]),
                'H9-v2': np.array([bykey['H9-v2'][k].ordered_values() for k in keys])}
    y = np.array([CLASSES.index(bykey['H9'][k].label) for k in keys])
    subjects = np.array([bykey['H9'][k].subject for k in keys])
    np.testing.assert_array_equal(matrices['H9-v2'], old['feature_matrix'])
    np.testing.assert_array_equal(y, old['true_labels'])
    np.testing.assert_array_equal(subjects, old['participants'])
    if all(r['common_support_equal'] for r in support):
        np.testing.assert_array_equal(matrices['H9'][:, :8], matrices['H9-v2'][:, :8])
    predictions = {name: {m: np.full((5, len(keys)), -1, dtype=int)
                          for m in (('M0', 'M1', 'M2') if name == 'H9' else ev.MODEL_NAMES)}
                   for name in matrices}
    folds, diagnostics, examples = [], [], []
    for si, seed in enumerate(SEEDS):
        for subject in sorted(set(subjects)):
            tr, te = np.flatnonzero(subjects != subject), np.flatnonzero(subjects == subject)
            assert set(y[tr]) == set(range(5)) and set(y[te]) == set(range(5))
            reference_fold = next(f for f in old['folds'] if f['seed'] == seed and f['held_out_participant'] == subject)
            assert tr.tolist() == reference_fold['train_indices'] and te.tolist() == reference_fold['test_indices']
            for feature_set, X in matrices.items():
                models, weights = rf.fit_models(X[tr], y[tr], 5, TREES, seed, [LAMBDA])
                forests = {m: models[m if m != 'M2' else M2].forest for m in ('M0', 'M1', 'M2')}
                if feature_set == 'H9-v2':
                    forests['M3-G'] = m3.M3GForest(5, n_trees=TREES, seed=seed).fit(X[tr], y[tr])
                    np.testing.assert_array_equal(forests['M0'].mdi, reference_fold['training_m0_mdi'])
                    np.testing.assert_array_equal(weights, reference_fold['rank_weights'])
                for model, forest in forests.items():
                    assert (forest.T, forest.mf, forest.seed) == (TREES, MF, seed)
                    p = forest.predict(X[te] * weights) if model == 'M1' else forest.predict(X[te])
                    predictions[feature_set][model][si, te] = p
                    if feature_set == 'H9-v2':
                        np.testing.assert_array_equal(p, np.asarray(old['predictions'][model])[si, te])
                np.testing.assert_array_equal(predictions[feature_set]['M0'][si, te], predictions[feature_set]['M1'][si, te])
                folds.append(dict(seed=seed, held_out_participant=subject, feature_set=feature_set,
                                  train_indices=tr.tolist(), test_indices=te.tolist(),
                                  training_m0_mdi=forests['M0'].mdi.tolist(), rank_weights=weights.tolist()))
                if feature_set == 'H9-v2':
                    for model in ('M0', 'M2', 'M3-G'):
                        d = tree_diagnostics(forests[model], X[tr], y[tr], X[te], y[te])
                        for row, ix in zip(d['samples'], te):
                            row['sample_index'] = int(ix)
                            row['sample_key'] = keys[ix]
                        diagnostics.append(dict(seed=seed, held_out_participant=subject, model=model, **d))
                    for i, ix in enumerate(te):
                        if predictions[feature_set]['M0'][si, ix] == y[ix] and predictions[feature_set]['M3-G'][si, ix] != y[ix]:
                            tis = [j for j, t in enumerate(forests['M3-G'].trees)
                                   if t.feat[0] == 8 and path(t, X[ix], v2.H9_V2_FEATURE_NAMES)['leaf_argmax'] != y[ix]]
                            if tis:
                                ti = tis[0]
                                examples.append(dict(seed=seed, held_out_participant=subject, sample_index=int(ix),
                                                     sample_key=keys[ix], actual=int(y[ix]), tree_index=ti,
                                                     forest_predictions={m: int(predictions[feature_set][m][si, ix]) for m in forests},
                                                     paths={m: path(forests[m].trees[ti], X[ix], v2.H9_V2_FEATURE_NAMES) for m in ('M0', 'M2', 'M3-G')}))
                                break
                print(f'completed seed={seed} held_out={subject} feature_set={feature_set}', flush=True)
    metrics = {}
    for feature_set, models in predictions.items():
        metrics[feature_set] = {}
        for model, p in models.items():
            assert np.all((p >= 0) & (p < 5))
            row = metric_summary(y, p, np.ones(len(y), dtype=bool))
            row['participants'] = {s: metric_summary(y, p, subjects == s) for s in sorted(set(subjects))}
            row['participant_macro_f1_mean'] = float(np.mean([r['macro_f1_mean'] for r in row['participants'].values()]))
            if feature_set == 'H9-v2':
                assert row['per_seed'] == old['metrics'][model]['per_seed']
            metrics[feature_set][model] = row
    comparisons = {f'H9-v2 - H9 | {m}': comparison(metrics['H9-v2'][m], metrics['H9'][m]) for m in ('M0', 'M1', 'M2')}
    comparisons.update({f'{f} | M2 - M0': comparison(metrics[f]['M2'], metrics[f]['M0']) for f in metrics})
    comparisons.update({f'H9-v2 | M3-G - {m}': comparison(metrics['H9-v2']['M3-G'], metrics['H9-v2'][m]) for m in ('M0', 'M2')})
    ev._verify_files(old['inputs'] + old['code'] + pinned)
    result = dict(kind='stage6-exploratory-pilot-primary5-comparison-and-tree-diagnosis',
                  started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
                  preregistration=pinned[-1], inputs=old['inputs'], code=old['code'], new_artifact_identities=pinned,
                  git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  environment=dict(python=platform.python_version(), numpy=np.__version__),
                  scope='primary5', class_order=CLASSES, seeds=SEEDS, trees=TREES, max_features=MF, m2_lambda=LAMBDA,
                  feature_order={'H9': agg.H9_FEATURE_NAMES, 'H9-v2': v2.H9_V2_FEATURE_NAMES},
                  support=support, per_feature_finite_frame_support=feature_support,
                  sample_keys=keys, participants=subjects.tolist(), true_labels=y.tolist(),
                  matrices={k: x.tolist() for k, x in matrices.items()},
                  folds=folds, predictions={f: {m: p.tolist() for m, p in rows.items()} for f, rows in predictions.items()},
                  metrics=metrics, comparisons=comparisons, tree_diagnostics=diagnostics, path_examples=examples,
                  verification=dict(existing_h9v2_predictions_metrics_mdi_weights_folds_exact=True,
                                    source_and_code_hashes_unchanged=True, same_samples_labels_folds=True,
                                    native_support_equal=all(r['common_support_equal'] for r in support),
                                    first_eight_aggregate_columns_equal=bool(np.array_equal(matrices['H9'][:, :8], matrices['H9-v2'][:, :8]))),
                  diagnostic_notes=dict(depth='root=0', split_denominator='all internal nodes, not all trees',
                                        class_counts='routing original unbootstrapped training samples; not bootstrap node counts',
                                        groups='observational subsets of fitted trees; not model ablations or causal estimates',
                                        soft_prediction='mean leaf class probabilities, then argmax; hard tree counts are diagnostic only',
                                        repeated_units='seeds/trees/frames are not independent participants'))
    with target.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
    print('WROTE', target)
    for f, rows in metrics.items():
        for m, row in rows.items():
            print(f, m, {k: row[k] for k in ('accuracy_mean', 'macro_f1_mean', 'p1_recall_mean', 'p1_precision_mean')})


if __name__ == '__main__':
    main()
