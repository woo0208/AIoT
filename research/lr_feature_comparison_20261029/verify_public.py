"""Check aggregate LR feature evidence only; no fitting or private inputs."""
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'h9_five_algorithms_20261029'))
from verify_results import close, metrics, require

NAMES=('A','B','C')
SCOPES=('pooled','participant_1','participant_2')


def verify(d):
    require(set(d['results'])==set(NAMES),'three fixed conditions required')
    require(d['seeds']==[0,1,2,3,4] and d['sample_count']==24,'fixed sample/seed contract')
    count=0
    for n in NAMES:
        require(set(d['results'][n])=={'scopes'},'sample-level data forbidden')
        scopes=d['results'][n]['scopes'];require(set(scopes)==set(SCOPES),'anonymous scopes required')
        for scope,s in scopes.items():
            require([r['seed'] for r in s['per_seed']]==d['seeds'],'seed mismatch')
            for r in s['per_seed']:
                m=metrics(r['confusion_matrix'])
                for key in ('accuracy','macro_f1'):close(r[key],m[key],key)
                for k,c in enumerate(r['per_class']):
                    for key in ('support','precision','recall','f1'):close(c[key],m['per_class'][k][key],'class '+key)
                for key,v in r['p1_errors'].items():
                    for field in ('support','count','rate'):close(v[field],m['p1_errors'][key][field],'P1 errors')
                count+=1
            for key in ('accuracy','macro_f1'):
                values=[r[key] for r in s['per_seed']]
                close(s['mean'][key],statistics.mean(values),'mean '+key)
                close(s['sd_ddof0'][key],statistics.pstdev(values),'SD '+key)
            for k in range(6):
                close(s['mean_per_class'][k]['recall'],statistics.mean(r['per_class'][k]['recall'] for r in s['per_seed']),'mean recall')
                for j in range(6):close(s['mean_confusion_matrix'][k][j],statistics.mean(r['confusion_matrix'][k][j] for r in s['per_seed']),'mean matrix')
        for si in range(5):
            a=scopes['participant_1']['per_seed'][si]['confusion_matrix'];b=scopes['participant_2']['per_seed'][si]['confusion_matrix']
            require(scopes['pooled']['per_seed'][si]['confusion_matrix']==[[a[k][j]+b[k][j] for j in range(6)] for k in range(6)],'pooling')
        for scope in SCOPES:
            s=scopes[scope];a=d['results']['A']['scopes'][scope]
            values=dict(**s['mean'],p0_recall=s['mean_per_class'][0]['recall'],p1_recall=s['mean_per_class'][1]['recall'])
            base=dict(**a['mean'],p0_recall=a['mean_per_class'][0]['recall'],p1_recall=a['mean_per_class'][1]['recall'])
            for key in values:close(d['delta_from_A_pp'][n][scope][key+'_pp'],100*(values[key]-base[key]),'delta')
    require(d['common_support']['all_24_samples_retained'] and d['common_support']['all_24_frame_supports_equal'],'common support')
    require(d['common_support']['c3_missing_frame_cells']==0,'no C3 imputation')
    return dict(status='PASS',saved_metric_cases=count,no_training_or_diagnostics=True)


if __name__=='__main__':
    print(json.dumps(verify(json.loads(Path(__file__).with_name('aggregate_results.json').read_text(encoding='utf-8'))),indent=2))
