"""No fitting: aggregate actual node/path diagnostics from results.json."""
from collections import Counter
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent


def aggregate(rows):
    split_hist, first_hist = Counter(), Counter()
    for row in rows:
        split_hist.update({int(k): v for k, v in row['split_depth_histograms']['8'].items()})
        for s in row['samples']:
            first_hist.update({int(k): v for k, v in s['c3_first_depth_histogram'].items()})
    trees = sum(d['total_trees'] for d in rows)
    roots = sum(d['root_counts'].get('8', 0) for d in rows)
    splits = sum(d['total_internal_splits'] for d in rows)
    c3 = sum(d['c3_split_count'] for d in rows)
    pairs = sum(d['total_trees'] * len(d['samples']) for d in rows)
    path_c3 = sum(s['c3_path_tree_count'] for d in rows for s in d['samples'])
    assert c3 == sum(split_hist.values()) and path_c3 == sum(first_hist.values())
    by_class = {}
    for k in range(5):
        samples = [s for d in rows for s in d['samples'] if s['actual'] == k]
        groups = {}
        for name in ('root_c3', 'root_other', 'path_c3', 'path_no_c3'):
            gs = [s['observational_tree_groups'][name] for s in samples]
            n = sum(g['tree_count'] for g in gs)
            p = sum(np.array(g['mean_probabilities']) * g['tree_count'] for g in gs if g['tree_count']) / n if n else None
            groups[name] = dict(tree_sample_pairs=n,
                                wrong_tree_count=sum(g['wrong_tree_count'] for g in gs),
                                wrong_tree_rate=sum(g['wrong_tree_count'] for g in gs)/n if n else None,
                                mean_probabilities=p.tolist() if n else None,
                                hard_prediction_counts=np.sum([g['hard_prediction_counts'] for g in gs], axis=0).tolist())
        by_class[f'P{k}'] = dict(sample_seed_count=len(samples), observational_tree_groups=groups,
                                 c3_path_tree_count=sum(s['c3_path_tree_count'] for s in samples),
                                 predicted_support=np.bincount([s['predicted'] for s in samples], minlength=5).tolist(),
                                 mean_forest_probabilities=np.mean([s['mean_probabilities'] for s in samples], axis=0).tolist())
    thresholds = [n['threshold'] for d in rows for n in d['c3_nodes']]
    return dict(total_trees=trees, c3_root_count=roots, c3_root_rate=roots/trees,
                total_internal_splits=splits, c3_splits=c3, c3_split_rate=c3/splits,
                trees_with_c3=sum(d['c3_tree_count'] for d in rows),
                c3_split_depth_histogram=dict(sorted(split_hist.items())),
                c3_split_mean_depth=sum(k*v for k,v in split_hist.items())/c3,
                c3_threshold_range=[min(thresholds), max(thresholds)],
                test_tree_sample_pairs=pairs, c3_path_pairs=path_c3, c3_path_rate=path_c3/pairs,
                first_c3_depth_histogram=dict(sorted(first_hist.items())), by_class=by_class)


def main():
    target = OUT / 'summary.json'
    if target.exists():
        raise FileExistsError(target)
    r = json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    diag = r['tree_diagnostics']
    summary = dict(metrics=r['metrics'], comparisons=r['comparisons'],
                   pooled={m: aggregate([d for d in diag if d['model'] == m]) for m in ('M0', 'M2', 'M3-G')},
                   held_out={s: {m: aggregate([d for d in diag if d['model'] == m and d['held_out_participant'] == s])
                                  for m in ('M0', 'M2', 'M3-G')} for s in ('P01', 'P02')},
                   c3_segment_values=[dict(sample_key=k, subject=s, actual=f'P{y}', c3=x[8])
                                      for k,s,y,x in zip(r['sample_keys'],r['participants'],r['true_labels'],r['matrices']['H9-v2'])])
    with target.open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
    for m, d in summary['pooled'].items():
        print('POOLED',m,{k:v for k,v in d.items() if k!='by_class'})
    for s, models in summary['held_out'].items():
        for m, d in models.items():
            print('HELDOUT',s,m,{k:v for k,v in d.items() if k!='by_class'})
            for label in ('P0','P1','P3'):
                c=d['by_class'][label]
                print('CLASS',label,'forest',np.round(c['mean_forest_probabilities'],4).tolist(),'predictions',c['predicted_support'])
                for group in ('root_c3','root_other','path_c3','path_no_c3'):
                    g=c['observational_tree_groups'][group]
                    print(group,g['tree_sample_pairs'],'error',round(g['wrong_tree_rate'],4) if g['tree_sample_pairs'] else None,
                          'prob',np.round(g['mean_probabilities'],4).tolist() if g['tree_sample_pairs'] else None)
    print('C3_SEGMENTS',summary['c3_segment_values'])


if __name__ == '__main__':
    main()
