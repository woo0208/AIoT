"""Independent projection of EXISTING formal6 eight-combination results.

No dataset loader, evaluator, fit, selection or held-out access is called.
Original JSON is preserved; per-class/seed/participant/session evidence stays
in a separate sidecar because the 5-E-4 CSV has only summary columns.
"""
import argparse
import json
import math
from pathlib import Path

import engineering_exports as out
import formal6_evaluation as ev
import performance_output as perf


RULE_ID = 'EXP-003+EXP-004+EXP-005+EXP-006+EXP-007'
FREEZE = Path(__file__).parent / 'docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md'
APPROVED = {name: (feature, model) for name, feature, model in (*ev.CANDIDATES, *ev.BASELINES)}
CLASS_FIELDS = ('comparison_id', 'scope', 'scope_id', 'seed', 'posture', 'label',
                'support', 'predicted_support', 'precision', 'recall', 'f1', 'metric_status')


def dataset_digest(aligned):
    # All five feature matrices, labels, identities and windows are bound.
    return out.digest({k: aligned[k] for k in ('class_order', 'feature_order', 'sample_keys',
                       'y', 'participants', 'sessions', 'X', 'audit')})


def _equal(a, b):
    return type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and math.isfinite(b) and abs(a-b) <= 1e-12


def _check_metrics(metric, n):
    """Cross-check already reported metrics against their CM; no predictions run."""
    cm, classes = metric['confusion_matrix'], metric['per_class']
    if (len(cm) != 6 or any(len(r) != 6 or any(type(v) is not int or v < 0 for v in r) for r in cm)
            or len(classes) != 6 or sum(map(sum, cm)) != n or metric['sample_count'] != n):
        raise ValueError('invalid confusion/support evidence')
    support = [sum(row) for row in cm]
    complete = all(support)
    if metric['status'] != ('COMPLETE' if complete else 'INCOMPLETE'):
        raise ValueError('completeness disagrees with actual support')
    for i, c in enumerate(classes):
        predicted = sum(row[i] for row in cm)
        precision = cm[i][i] / predicted if predicted else 0.
        recall = cm[i][i] / support[i] if support[i] else None
        f1 = 2*precision*recall/(precision+recall) if recall is not None and precision+recall else 0. if support[i] else None
        if (c['posture'] != f'P{i}' or c['label'] != ev.h6.LAB6[i] or c['support'] != support[i]
                or c['predicted_support'] != predicted or not _equal(c['precision'], precision)
                or (not _equal(c['recall'], recall) if recall is not None else c['recall'] is not None)
                or (not _equal(c['f1'], f1) if f1 is not None else c['f1'] is not None)):
            raise ValueError('per-class evidence mismatch')
    accuracy = sum(cm[i][i] for i in range(6))/n if n else None
    if (not _equal(metric['accuracy'], accuracy) if n else metric['accuracy'] is not None):
        raise ValueError('accuracy disagrees with confusion matrix')
    if complete:
        if not _equal(metric['macro_f1'], sum(c['f1'] for c in classes)/6):
            raise ValueError('macro_f1 disagrees with six-class evidence')
    elif metric['macro_f1'] is not None:
        raise ValueError('INCOMPLETE official macro_f1 must remain null')


def _check_summary(summary, n, seeds):
    rows = summary['per_seed']
    if [r['seed'] for r in rows] != list(seeds):
        raise ValueError('frozen seeds mismatch')
    for row in rows:
        _check_metrics(row, n)
    complete = all(r['status'] == 'COMPLETE' for r in rows)
    if summary['status'] != ('COMPLETE' if complete else 'INCOMPLETE'):
        raise ValueError('summary completeness mismatch')
    for source, dest in (('accuracy', 'mean_accuracy'), ('macro_f1', 'mean_macro_f1')):
        expected = sum(r[source] for r in rows)/len(rows) if all(r[source] is not None for r in rows) else None
        if (not _equal(summary[dest], expected) if expected is not None else summary[dest] is not None):
            raise ValueError('seed mean mismatch:' + dest)
    for k in range(6):
        values = [r['per_class'][k]['recall'] for r in rows]
        expected = sum(values)/len(values) if all(v is not None for v in values) else None
        actual = summary['mean_recall'][k]
        if (not _equal(actual, expected) if expected is not None else actual is not None):
            raise ValueError('mean recall mismatch')


def project(report, metadata):
    comparison = report.get('baseline_comparison', report)
    models = comparison.get('models', {})
    if set(models) - set(APPROVED):
        raise ValueError('auxiliary/unapproved models cannot enter frozen eight comparisons')
    if metadata['evaluation_rule_id'] != RULE_ID or metadata['evaluation_rule_sha256'] != perf.sha256(FREEZE):
        raise ValueError('evaluation rule evidence mismatch')
    identity = metadata['identity']
    out.validate_scope(identity)
    if report.get('scope', identity['scope']) != identity['scope']:
        raise ValueError('source/metadata scope mismatch')
    aligned = comparison.get('aligned')
    if not aligned:
        if models:
            raise ValueError('models require aligned input evidence')
        return _unmeasured(comparison, metadata)
    if (aligned['class_order'] != list(ev.h6.LAB6)
            or aligned['feature_order'] != {k: list(v) for k, v in ev.FEATURES.items()}):
        raise ValueError('fixed class/feature order mismatch')
    if metadata['dataset_sha256'] != dataset_digest(aligned):
        raise ValueError('common-input dataset digest mismatch')
    roster = aligned.get('development_subjects', aligned['participant_roster'])
    if len(roster) != 2 or len(set(roster)) != 2 or set(metadata['reference_keys']) != set(roster):
        raise ValueError('two-person development roster and fixed references required')
    keys = aligned['sample_keys']
    refs = list(metadata['reference_keys'].values())
    if any(k in refs for k in keys) or len(set(map(tuple, keys))) != len(keys):
        raise ValueError('reference P0 inclusion or duplicate common sample')
    audit = {tuple(r['sample_key']): r for r in aligned['audit']}
    for subject, ref in metadata['reference_keys'].items():
        row = audit.get(tuple(ref), {})
        if (row.get('label') != 'upright' or row.get('subject') != subject
                or row.get('session') != 'S1'
                or 'first_P0_reference_excluded_from_train_and_evaluation' not in row.get('reasons', [])):
            raise ValueError('fixed P0 exclusion audit missing')
    windows = {tuple(w['sample_key']): w['window'] for w in metadata['windows']}
    for key in keys:
        window = windows.get(tuple(key))
        if (not window or len(window) != 3 or not window[0]
                or any(type(t) not in (int, float) or not math.isfinite(t) for t in window[1:])
                or window[2] - window[1] != 10):
            raise ValueError('verified ten-second window evidence missing')
    n = len(keys)
    if any(len(aligned[k]) != n for k in ('y', 'participants', 'sessions')):
        raise ValueError('input identity length mismatch')
    if set(aligned['participants']) - set(roster) or any(s not in ('S1', 'S2') for s in aligned['sessions']):
        raise ValueError('development-only participant/session mismatch')
    for feature, columns in ev.FEATURES.items():
        matrix = aligned['X'][feature]
        if len(matrix) != n or any(len(r) != len(columns) for r in matrix):
            raise ValueError('feature dimensions mismatch')
    for key in keys:
        row = audit[tuple(key)]
        if not row['eligible'] or row['reasons'] or any(f['review'] != 'confirmed' or not f['eligible']
                                                      for f in row['families'].values()):
            raise ValueError('common sample eligibility evidence mismatch')
    settings = comparison['settings']
    if (settings['rf_seeds'] != list(ev.SEEDS) or settings['rf_trees'] != 500 or settings['max_features'] != 2
            or settings.get('structural_test_settings') is not False):
        raise ValueError('frozen RF settings mismatch')
    folds = comparison.get('folds', [])
    for fold in folds:
        if fold.get('heldout') not in roster:
            raise ValueError('LOSO heldout participant mismatch')
        if fold['model'] == 'LR_B0':
            if fold['seed'] != 0 or fold['train_participants'] != [s for s in roster if s != fold['heldout']]:
                raise ValueError('LR train-fold evidence mismatch')
        else:
            test = [k for k, s in zip(keys, aligned['participants']) if s == fold['heldout']]
            train = [k for k, s in zip(keys, aligned['participants']) if s != fold['heldout']]
            if fold['test_keys'] != test or fold['train_keys'] != train:
                raise ValueError('LOSO train/test common-key mismatch')
    rows, classes, details = [], [], {}
    for name, (feature, model) in APPROVED.items():
        result = models.get(name)
        base = dict(out.common(identity, 'evaluation_details.json'), comparison_id=name,
                    dataset_sha256=metadata['dataset_sha256'], evaluation_rule_id=RULE_ID)
        if result is None:
            rows.append(dict(base, measurement_status='NOT_MEASURED', reason='combination_not_evaluated'))
            continue
        if (result['feature_set'], result['model']) != (feature, model):
            raise ValueError('approved model identity mismatch')
        seeds = (0,) if model == 'LR_B0' else ev.SEEDS
        expected_fold_model = name if name in {b[0] for b in ev.BASELINES} else 'LR_B0' if model == 'LR_B0' else 'RF'
        for seed in seeds:
            for subject in roster:
                if sum(f['model'] == expected_fold_model and f['seed'] == seed and f['heldout'] == subject for f in folds) != 1:
                    raise ValueError('complete frozen LOSO fold evidence required')
        predictions = result['predictions']
        if len(predictions) != len(seeds) or any(len(p) != n for p in predictions):
            raise ValueError('prediction/common-sample alignment mismatch')
        scopes = [('pooled', 'all', result['pooled'], n)]
        if set(result['participants']) != set(roster) or set(result['sessions']) != {'S1', 'S2'}:
            raise ValueError('participant/session reports missing')
        scopes += [('participant', s, value, aligned['participants'].count(s)) for s, value in result['participants'].items()]
        scopes += [('session', s, value, aligned['sessions'].count(s)) for s, value in result['sessions'].items()]
        for scope, scope_id, summary, count in scopes:
            _check_summary(summary, count, seeds)
            keep = [i for i in range(n) if scope == 'pooled' or aligned[
                'participants' if scope == 'participant' else 'sessions'][i] == scope_id]
            for prediction, metric in zip(predictions, summary['per_seed']):
                cm = [[0]*6 for _ in range(6)]
                for i in keep:
                    truth, predicted = aligned['y'][i], prediction[i]
                    if type(truth) is not int or type(predicted) is not int or not 0 <= truth < 6 or not 0 <= predicted < 6:
                        raise ValueError('fixed six-class prediction labels required')
                    cm[truth][predicted] += 1
                if cm != metric['confusion_matrix']:
                    raise ValueError('predictions and confusion matrix disagree')
                for c in metric['per_class']:
                    row = {k: c[k] for k in ('posture', 'label', 'support', 'predicted_support', 'precision', 'recall', 'f1')}
                    row.update(comparison_id=name, scope=scope, scope_id=scope_id, seed=metric['seed'],
                               metric_status='N/A' if c['support'] == 0 else 'MEASURED')
                    # Missing numeric CSV cells stay blank; N/A is a separate status.
                    classes.append(row)
        pooled = result['pooled']
        rows.append(dict(base, measurement_status='MEASURED' if pooled['status'] == 'COMPLETE' else 'INCOMPLETE',
            reason='' if pooled['status'] == 'COMPLETE' else 'actual_class_support_missing; official_macro_f1_not_computed',
            support=n, accuracy=pooled['mean_accuracy'], macro_f1=pooled['mean_macro_f1']))
        details[name] = dict(role='COMPARISON_BASELINE' if name in {b[0] for b in ev.BASELINES} else 'SELECTION_CANDIDATE_COMPARISON_COPY',
                             result=result)
    return dict(status='COMPLETE' if all(r['measurement_status'] == 'MEASURED' for r in rows) else 'INCOMPLETE',
        scope=identity['scope'], metadata=metadata, combinations=details, comparison_rows=rows, class_rows=classes,
        alignment_evidence=aligned, folds=folds,
        note='No selection performed. These are eight common-sample comparison copies; auxiliary candidates excluded.')


def _unmeasured(comparison, metadata):
    identity = metadata['identity']
    return dict(status='NOT_MEASURED', scope=identity['scope'], metadata=metadata, combinations={}, class_rows=[],
        comparison_rows=[dict(out.common(identity, 'evaluation_details.json'), comparison_id=name,
            dataset_sha256=metadata.get('dataset_sha256'), evaluation_rule_id=RULE_ID,
            measurement_status='NOT_MEASURED', reason='evaluation_not_run:' + comparison.get('status', 'NOT_PROVIDED'))
                         for name in APPROVED])


def export(result_path, metadata_path, directory):
    sources = [Path(result_path), Path(metadata_path)]
    raw = [p.read_bytes() for p in sources]
    report, metadata = [json.loads(b) for b in raw]
    if metadata['result_sha256'] != perf.sha256(sources[0]):
        raise ValueError('result SHA-256 mismatch')
    result = project(report, metadata)
    root = out.reserve(directory, sources)
    for name, data in zip(('evaluation.original.json', 'metadata.original.json'), raw):
        with (root / name).open('xb') as stream:
            stream.write(data)
    result['sources'] = [dict(path=str(p.resolve()), sha256=perf.sha256(p)) for p in sources]
    perf._write_json(root / 'evaluation_details.json', result)
    out.csv_write(root / 'experiment_comparisons.csv', perf.COMPARISON_FIELDS, result['comparison_rows'])
    out.csv_write(root / 'class_metrics.csv', CLASS_FIELDS, result['class_rows'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('result_json', 'metadata_json', 'new_directory'):
        parser.add_argument(name)
    args = parser.parse_args(argv)
    print(export(args.result_json, args.metadata_json, args.new_directory)['status'])


if __name__ == '__main__':
    main()
