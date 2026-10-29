"""Fixed three-condition LR experiment using the verified five-model evaluator.

Only A=original H9, B=drop F9, C=H9-v2 are fitted. No tuning or other models.
"""
from datetime import datetime, timezone
import argparse
import gc
import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import time
import warnings

import baseline as ev
import h9_v2 as v2
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_info, threadpool_limits

OUT = Path(__file__).resolve().parent
NAMES = ('A', 'B', 'C')
SEEDS = ev.SEEDS


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_new(name, value):
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def protected_check():
    pin=read(OUT/'input_identities.json')
    changed=[x['path'] for x in pin['protected_files'] if sha(x['path']) != x['sha256']]
    if changed:
        raise ValueError('protected files changed: '+repr(changed))
    status=subprocess.run(['git','status','--porcelain=v1','--untracked-files=normal'],
        cwd=pin['original_root'], capture_output=True, text=True, check=True).stdout.strip()
    if status != pin['status']:
        raise ValueError('original Git status changed')
    return dict(status='PASS', protected_original_file_count=len(pin['protected_files']),
                changed_files=[], original_git_status_unchanged=True)


def aligned_candidate(original, candidates):
    """Fail closed instead of imputing, dropping a segment or replacing labels."""
    keys=[s.sample_key for s in original]
    mapping={s.sample_key:s for s in candidates}
    if len(mapping)!=len(candidates) or set(mapping)!=set(keys):
        raise ValueError('H9/H9-v2 sample-key mismatch or duplicate')
    aligned=[]
    for a in original:
        c=mapping[a.sample_key]
        if (a.subject,a.label,a.input_frame_indices)!=(c.subject,c.label,c.input_frame_indices):
            raise ValueError('H9/H9-v2 identity, label or segment-frame mismatch')
        if not a.eligible or not c.eligible:
            raise ValueError('C3/common-support eligibility cannot retain original sample: '+repr(c.sample_key))
        aligned.append(c)
    return aligned


def matrices(original, candidates):
    ordered=aligned_candidate(original,candidates)
    a=np.array([s.ordered_values('H9') for s in original],dtype=np.float64)
    c=np.array([s.ordered_values() for s in ordered],dtype=np.float64)
    if not np.isfinite(a).all() or not np.isfinite(c).all():
        raise ValueError('non-finite observations; no imputation allowed')
    return {'A':a,'B':a[:,:8].copy(),'C':c},ordered


def load_data():
    _, eligible, a, y, subjects, audit, _, _ = ev.load_samples()
    candidates=ev.h6.load_labeled_probe_h9_v2_samples([OUT/'inputs'/n for n in ev.CSV_NAMES])
    x, ordered=matrices(eligible,candidates)
    np.testing.assert_array_equal(a,x['A'])
    previous=read(OUT/'inputs/baseline_samples.json')
    np.testing.assert_array_equal(x['A'],previous['matrix'])
    assert y.tolist()==previous['labels'] and subjects.tolist()==previous['subjects']
    prior_plan=read(OUT/'inputs/baseline_PLAN.json')
    folds=ev.fold_plans(subjects,y)
    assert folds==prior_plan['folds']
    rows=[]
    for i,(original,candidate) in enumerate(zip(eligible,ordered)):
        rows.append(dict(sample_key=list(original.sample_key), subject=original.subject,
            label=original.label, posture=int(y[i]), input_frame_indices=list(original.input_frame_indices),
            same_common_frame_support=original.common_valid_frame_indices==candidate.common_valid_frame_indices,
            original_support_count=original.common_valid_count,candidate_support_count=candidate.common_valid_count,
            original_common_valid_frame_indices=list(original.common_valid_frame_indices),
            candidate_common_valid_frame_indices=list(candidate.common_valid_frame_indices),
            c3_missing_frame_count=candidate.missing_counts[v2.H9_V2_C3_FEATURE],
            candidate_missing_counts=dict(candidate.missing_counts), candidate_eligible=candidate.eligible))
    # Record native support; never reaggregate A/B on C support or silently intersect samples.
    return x,y,subjects,folds,rows,audit


def prepare():
    assert not (OUT/'PLAN.json').exists()
    protected_check()
    try:
        x,y,subjects,folds,rows,audit=load_data()
    except ValueError as error:
        write_new('BLOCKED.json',dict(reason=str(error),imputation=False,new_model_fit=False))
        raise
    before=read(OUT/'inputs/baseline_PLAN.json')
    params=ev.make_model('Logistic-Regression',0).get_params()
    assert params==before['model_parameters']['Logistic-Regression']
    features={'A':list(ev.agg.H9_FEATURE_NAMES),'B':list(ev.agg.H9_FEATURE_NAMES[:8]),
              'C':list(v2.H9_V2_FEATURE_NAMES)}
    data=dict(matrices={n:a.tolist() for n,a in x.items()},labels=y.tolist(),subjects=subjects.tolist(),
        class_order=list(ev.h6.LAB6),features=features,support_audit=rows,original_aggregation_audit=audit)
    write_new('dataset.json',data)
    plan=dict(created_utc=datetime.now(timezone.utc).isoformat(), purpose='fixed LR feature configurations; two-person pilot exploration',
        conditions={'A':'original H9 F1..F9','B':'same H9 matrix with F9 column removed; no reaggregation',
                    'C':'native H9-v2 F1..F8+C3, unchanged existing calculation and aggregation'},
        sample_count=24,class_count=6,seeds=list(SEEDS),folds=folds,features=features,
        model_parameters_seed0=params,model_factory='byte-identical verified baseline.make_model(Logistic-Regression, seed)',
        preprocessing='Separate StandardScaler per condition and training fold only; 12 training samples; no imputation',
        no_parameter_search=True, no_additional_model=True,
        benchmark=dict(threads=1,warmup_calls_per_condition_fold_seed=24,timed_calls_per_condition_fold_seed=120,
            boundary='StandardScaler.transform(raw 1xd row) plus LR.predict; preallocated already aggregated row; no feature aggregation/image processing/I/O',
            clock='perf_counter_ns',schedule='round-robin conditions; rotate start by seed+fold; cycle the same 12 held-out segments',
            gc='disabled in measured loops and restored',model_size='uncompressed pickle protocol=5 classifier+scaler; not RAM or library size'),
        metric_semantics='Per seed pool 24 OOF predictions, average six class F1s; then mean and population SD across seeds. Participant F1 means reported separately. Seeds are not additional people.',
        common_support=dict(all_24_samples_retained=True,
            all_24_frame_supports_equal=all(r['same_common_frame_support'] for r in rows),
            first_eight_aggregated_columns_exactly_equal=bool(np.array_equal(x['A'][:,:8],x['C'][:,:8])),
            c3_missing_frame_cells=sum(r['c3_missing_frame_count'] for r in rows),
            candidate_common_frames=sum(r['candidate_support_count'] for r in rows)),
        baseline_results_sha256=sha(OUT/'inputs/baseline_results.json'),
        baseline_plan_sha256=sha(OUT/'inputs/baseline_PLAN.json'),dataset_sha256=sha(OUT/'dataset.json'),
        evaluator_sha256=sha(__file__),baseline_evaluator_sha256=sha(OUT/'baseline.py'),
        source_files=[dict(path=str(p.relative_to(OUT)),sha256=sha(p)) for p in sorted((OUT/'source').glob('*.py'))],
        inputs=[dict(path=str(p.relative_to(OUT)),sha256=sha(p)) for p in sorted((OUT/'inputs').glob('*'))],
        environment=ev.environment(),external_four_participant_data_used=False)
    write_new('PLAN.json',plan)
    print(json.dumps(dict(status='PASS; plan frozen before fitting',common_support=plan['common_support'],
                         lr_parameters=params),indent=2))


def benchmark(fitted,x,indices,order):
    raw={n:[np.ascontiguousarray(row.reshape(1,-1)) for row in x[n][indices]] for n in NAMES}
    for n in order:
        model,scaler=fitted[n]
        for i in range(24):model.predict(scaler.transform(raw[n][i%12]))
    times={n:[] for n in NAMES}; enabled=gc.isenabled();gc.disable()
    try:
        for i in range(120):
            for n in order:
                model,scaler=fitted[n]
                start=time.perf_counter_ns()
                model.predict(scaler.transform(raw[n][i%12]))
                times[n].append(time.perf_counter_ns()-start)
    finally:
        if enabled:gc.enable()
    return times


def key_metrics(scope):
    return dict(**scope['mean'],p0_recall=scope['mean_per_class'][0]['recall'],
                p1_recall=scope['mean_per_class'][1]['recall'])


def evaluate():
    assert not (OUT/'results.json').exists()
    plan=read(OUT/'PLAN.json');plan_sha=sha(OUT/'PLAN.json')
    assert sha(__file__)==plan['evaluator_sha256'] and sha(OUT/'baseline.py')==plan['baseline_evaluator_sha256']
    assert sha(OUT/'dataset.json')==plan['dataset_sha256']
    for row in plan['inputs']+plan['source_files']:assert sha(OUT/row['path'])==row['sha256']
    assert ev.make_model('Logistic-Regression',0).get_params()==plan['model_parameters_seed0']
    protected_check();x,y,subjects,plans,support,audit=load_data()
    assert plans==plan['folds']
    frozen=read(OUT/'dataset.json')
    for n in NAMES:np.testing.assert_array_equal(x[n],frozen['matrices'][n])
    old=read(OUT/'inputs/baseline_results.json')
    assert old['seeds']==list(SEEDS)
    preds={n:np.full((5,24),-1,dtype=int) for n in NAMES};folds=[];timings=[];recorded_warnings=[]
    started=datetime.now(timezone.utc).isoformat()
    with threadpool_limits(limits=1):
        pools=threadpool_info();assert all(p['num_threads']==1 for p in pools)
        for si,seed in enumerate(SEEDS):
            assigned=np.zeros(24,dtype=int)
            for fi,binding in enumerate(plans):
                train=np.asarray(binding['train_indices']);test=np.asarray(binding['test_indices'])
                fitted={};fold=dict(seed=seed,**binding,conditions={})
                for n in NAMES:
                    scaler=StandardScaler().fit(x[n][train]);assert int(scaler.n_samples_seen_)==12
                    np.testing.assert_array_equal(scaler.mean_,x[n][train].mean(0))
                    np.testing.assert_allclose(scaler.var_,x[n][train].var(0),rtol=1e-14,atol=1e-15)
                    tr=scaler.transform(x[n][train]);te=scaler.transform(x[n][test])
                    model=ev.make_model('Logistic-Regression',seed)
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter('always');model.fit(tr,y[train])
                    for w in caught:
                        recorded_warnings.append(dict(condition=n,seed=seed,held_out=binding['held_out'],
                            category=w.category.__name__,message=str(w.message)))
                        if issubclass(w.category,ConvergenceWarning):
                            raise RuntimeError('fixed LR did not converge; no post-hoc iteration tuning allowed')
                    pred=np.asarray(model.predict(te));assert pred.shape==(12,) and set(pred).issubset(range(6))
                    preds[n][si,test]=pred
                    np.testing.assert_array_equal(scaler.mean_,x[n][train].mean(0))
                    if n=='A':
                        np.testing.assert_array_equal(pred,np.asarray(old['results']['Logistic-Regression']['predictions_by_seed'][si])[test])
                        previous=next(f for f in old['folds'] if f['seed']==seed and f['held_out']==binding['held_out'])['models']['Logistic-Regression']
                        np.testing.assert_array_equal(scaler.mean_,previous['scaler']['mean'])
                        np.testing.assert_array_equal(scaler.scale_,previous['scaler']['scale'])
                    blob=pickle.dumps(dict(classifier=model,scaler=scaler),protocol=5)
                    restored=pickle.loads(blob)
                    np.testing.assert_array_equal(pred,restored['classifier'].predict(restored['scaler'].transform(x[n][test])))
                    fold['conditions'][n]=dict(predictions=pred.tolist(),metrics=ev.metrics(y[test],pred),
                        scaler=dict(mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),n_samples_seen=12),
                        pipeline_pickle_bytes=len(blob),n_iter=model.n_iter_.tolist(),
                        serialized_roundtrip_equal=True)
                    fitted[n]=model,scaler
                shift=(si+fi)%3;order=NAMES[shift:]+NAMES[:shift]
                timings.append(dict(seed=seed,held_out=binding['held_out'],order=order,
                                    pipeline_ns=benchmark(fitted,x,test,order)))
                folds.append(fold);assigned[test]+=1
                print(f'PASS fixed A/B/C LR: seed={seed}, held_out={binding["held_out"]}',flush=True)
            assert np.all(assigned==1)
    result={n:dict(predictions_by_seed=preds[n].tolist(),
        scopes={scope:ev.summary(y,preds[n],np.ones(24,dtype=bool) if scope=='pooled' else subjects==scope)
                for scope in ('pooled','P01','P02')}) for n in NAMES}
    assert result['A']['predictions_by_seed']==old['results']['Logistic-Regression']['predictions_by_seed']
    assert result['A']['scopes']==old['results']['Logistic-Regression']['scopes']
    costs={}
    for n in NAMES:
        values=np.array([v for r in timings for v in r['pipeline_ns'][n]],dtype=float)/1e6
        assert len(values)==1200
        sizes=[f['conditions'][n]['pipeline_pickle_bytes'] for f in folds]
        costs[n]=dict(pipeline_ms=dict(n_calls=len(values),median=float(np.median(values)),
            p95=float(np.percentile(values,95)),p99=float(np.percentile(values,99)),mean=float(values.mean())),
            pipeline_pickle_bytes=dict(mean=float(np.mean(sizes)),min=min(sizes),max=max(sizes)))
    deltas={n:{scope:{k+'_pp':100*(v-key_metrics(result['A']['scopes'][scope])[k])
            for k,v in key_metrics(result[n]['scopes'][scope]).items()}
            for scope in ('pooled','P01','P02')} for n in NAMES}
    comparisons={scope:{k+'_pp':100*(v-key_metrics(result['B']['scopes'][scope])[k])
            for k,v in key_metrics(result['C']['scopes'][scope]).items()}
            for scope in ('pooled','P01','P02')}
    changes=[]
    for i in range(24):
        if any(np.any(preds[n][:,i]!=preds['A'][:,i]) for n in ('B','C')):
            changes.append(dict(sample_key=support[i]['sample_key'],subject=subjects[i],actual=int(y[i]),
                predictions={n:preds[n][:,i].tolist() for n in NAMES}))
    verification=protected_check();assert sha(OUT/'PLAN.json')==plan_sha
    write_new('results.json',dict(kind='fixed LR A/B/C features, two-person six-class pilot exploration',
        started_utc=started,ended_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=plan_sha,
        conditions=plan['conditions'],features=plan['features'],seeds=list(SEEDS),class_order=list(ev.h6.LAB6),
        sample_count=24,results=result,folds=folds,costs=costs,timing_raw=timings,
        delta_from_A_pp=deltas,C_minus_B_pp=comparisons,changed_samples=changes,
        warnings=recorded_warnings,environment=ev.environment(),threadpools=pools,
        common_support=plan['common_support'],verification=dict(**verification,
            original_LR_all_predictions_metrics_scalers='EXACT MATCH',
            all_conditions_identical_keys_labels_folds='PASS',train_fold_only_scaling='PASS',
            serialized_roundtrip='30/30 PASS',fit_count=30,other_model_fit_count=0,
            external_four_participant_data_used=False)))
    print(json.dumps(dict(status='PASS',metrics={n:key_metrics(result[n]['scopes']['pooled']) for n in NAMES},
        costs=costs,differences=deltas,warnings=recorded_warnings),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--evaluate',action='store_true');a=p.parse_args()
    prepare() if a.prepare else evaluate()
