"""Verify published aggregate arithmetic without fitting or importing models."""
import argparse
import json
import math
from pathlib import Path
import statistics

MODELS = ('M0', 'SVM-RBF', 'Linear-SVM', 'Logistic-Regression', 'KNN')
SCOPES = ('pooled', 'participant_A', 'participant_B')
SEEDS = (0, 1, 2, 3, 4)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, context):
    require(isinstance(actual, (int, float)) and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12), context)


def metrics(cm):
    require(isinstance(cm, list) and len(cm) == 6, 'six confusion rows required')
    require(all(isinstance(row, list) and len(row) == 6 for row in cm), 'six confusion columns required')
    require(all(type(x) is int and x >= 0 for row in cm for x in row), 'nonnegative integer counts required')
    support = [sum(row) for row in cm]
    require(all(support), 'all six actual classes must be present')
    classes = []
    for k in range(6):
        predicted = sum(row[k] for row in cm)
        tp = cm[k][k]
        classes.append(dict(support=support[k], predicted_support=predicted,
                            precision=tp / predicted if predicted else 0.,
                            recall=tp / support[k],
                            f1=2 * tp / (support[k] + predicted)))
    return dict(accuracy=sum(cm[k][k] for k in range(6)) / sum(support),
                macro_f1=statistics.mean(c['f1'] for c in classes), per_class=classes,
                p1_errors={f'P1_to_P{k}': dict(count=cm[1][k], support=support[1],
                                             rate=cm[1][k] / support[1]) for k in (0, 5)})


def verify(d):
    require(set(d['results']) == set(MODELS), 'exact five models required')
    require(d['seeds'] == list(SEEDS), 'fixed computational seeds required')
    require(d['sample_count'] == 24 and d['participant_count'] == 2, '24 segments and two people required')
    checks = 0
    for name in MODELS:
        require(set(d['results'][name]) == {'scopes'}, 'sample-level model outputs are not publishable')
        scopes = d['results'][name]['scopes']
        require(set(scopes) == set(SCOPES), 'exact anonymized scopes required')
        for scope in SCOPES:
            s = scopes[scope]
            support = 4 if scope == 'pooled' else 2
            require(s['sample_count'] == support * 6, 'scope sample count mismatch')
            require([row['seed'] for row in s['per_seed']] == list(SEEDS), 'per-seed ordering mismatch')
            calculated = []
            for row in s['per_seed']:
                cm = row['confusion_matrix']; m = metrics(cm); calculated.append(m)
                require([sum(a) for a in cm] == [support] * 6, 'class support mismatch')
                for key in ('accuracy', 'macro_f1'):
                    close(row[key], m[key], f'{name}/{scope}/{key}')
                require(len(row['per_class']) == 6, 'six class metrics required')
                for k, c in enumerate(row['per_class']):
                    require(c['posture'] == f'P{k}' and c['label'] == d['class_order'][k], 'class label mismatch')
                    for field in ('support', 'precision', 'recall', 'f1'):
                        close(c[field], m['per_class'][k][field], f'{name}/{scope}/class {k}/{field}')
                for e, expected in m['p1_errors'].items():
                    for field in ('count', 'support', 'rate'):
                        close(row['p1_errors'][e][field], expected[field], f'{name}/{scope}/{e}/{field}')
                checks += 1
            for key in ('accuracy', 'macro_f1'):
                values = [m[key] for m in calculated]
                close(s['mean'][key], statistics.mean(values), f'{name}/{scope}/mean {key}')
                close(s['sd_ddof0'][key], statistics.pstdev(values), f'{name}/{scope}/seed SD {key}')
            for k in range(6):
                for j in range(6):
                    close(s['mean_confusion_matrix'][k][j], statistics.mean(r['confusion_matrix'][k][j] for r in s['per_seed']), 'mean matrix mismatch')
                for field in ('support', 'precision', 'recall', 'f1'):
                    close(s['mean_per_class'][k][field], statistics.mean(m['per_class'][k][field] for m in calculated), 'mean class metric mismatch')
            for e in calculated[0]['p1_errors']:
                for field in ('count', 'support', 'rate'):
                    close(s['mean_p1_errors'][e][field], statistics.mean(m['p1_errors'][e][field] for m in calculated), 'mean P1 error mismatch')
        for si in range(5):
            pooled = scopes['pooled']['per_seed'][si]['confusion_matrix']
            a = scopes['participant_A']['per_seed'][si]['confusion_matrix']
            b = scopes['participant_B']['per_seed'][si]['confusion_matrix']
            require(pooled == [[a[k][j] + b[k][j] for j in range(6)] for k in range(6)], 'participant matrices must sum to pooled')
        participant_mean = statistics.mean(scopes[s]['mean']['macro_f1'] for s in SCOPES[1:])
        close(d['participant_mean_macro_f1'][name], participant_mean, 'participant mean Macro-F1 mismatch')
        for scope in SCOPES:
            for key in ('accuracy', 'macro_f1'):
                expected = 100 * (scopes[scope]['mean'][key] - d['results']['M0']['scopes'][scope]['mean'][key])
                close(d['delta_from_existing_M0_pp'][name][scope][key + '_pp'], expected, 'M0 difference mismatch')
        for field in ('classifier_ms', 'pipeline_ms'):
            c = d['costs'][name][field]
            require(c['n_calls'] == 1200 and 0 < c['median'] <= c['p95'] <= c['p99'], 'timing summary mismatch')
        for field in ('classifier_pickle_bytes', 'pipeline_pickle_bytes'):
            c = d['costs'][name][field]
            require(0 < c['min'] <= c['mean'] <= c['max'], 'size summary mismatch')
    if d.get('logistic_regression_error_summary'):
        cm = d['results']['Logistic-Regression']['scopes']['pooled']['mean_confusion_matrix']
        require(d['logistic_regression_error_summary'] == {
            'P0_recall': cm[0][0] / sum(cm[0]), 'P1_recall': cm[1][1] / sum(cm[1]),
            'off_diagonal_counts_per_seed': {f'P{i}_to_P{j}': cm[i][j]
                for i in range(6) for j in range(6) if i != j and cm[i][j]}}, 'Logistic error summary mismatch')
    return dict(status='PASS', recomputed_seed_scope_cases=checks,
                pooled_equals_sum_of_participants=True, metric_and_seed_semantics='PASS',
                no_model_fitting=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', nargs='?', type=Path, default=Path(__file__).with_name('aggregate_results.json'))
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.result.read_text(encoding='utf-8'))), indent=2))
