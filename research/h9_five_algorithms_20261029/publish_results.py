"""Export saved aggregate evidence only. No training, tuning or model imports."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

from verify_results import MODELS, SCOPES, verify


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, d):
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(d, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def table(lines, header, rows):
    lines.extend(['', '|' + '|'.join(header) + '|', '|' + '|'.join(['---'] * len(header)) + '|'])
    lines.extend('|' + '|'.join(map(str, row)) + '|' for row in rows)
    lines.append('')


def report(d, protocol):
    pct = lambda x: f'{100*x:.2f}'
    lines = ['# Original H9: five-algorithm pilot comparison — final aggregate record', '',
        '기존 두 참가자·6-class(P0~P5)·24개 적격 구간의 탐색 결과다. 최종 독립 검증으로 주장하지 않는다. 공유 결과의 참가자는 A/B로 표기하며 원본 CSV·영상·개인정보·구간별 특징/예측·scaler 통계·학습 모델·호스트 경로는 포함하지 않는다.', '',
        '## 전체 Macro-F1 계산 방식', '',
        '1. 각 seed에서 두 LOSO 검증 폴드의 OOF 예측 12개+12개를 합쳐 24개 표본의 6×6 혼동행렬을 만든다.',
        '2. 이 pooled 행렬에서 클래스별 F1_k = 2TP_k / (2TP_k+FP_k+FN_k)를 구하고, 6개 F1의 산술평균을 그 seed의 전체 Macro-F1로 삼는다. 여섯 클래스는 모든 폴드에 존재한다.',
        '3. 보고하는 전체 Macro-F1은 seed 0~4의 전체 Macro-F1 다섯 값의 산술평균이다. SD는 이 다섯 값의 모집단 표준편차(ddof=0)다.',
        '4. **참가자별 Macro-F1 두 값의 평균과 다르다.** seed를 합산한 120개 예측에서 F1을 한 번 계산한 값도 아니다. 평균 혼동행렬에서 다시 계산한 F1도 전체 보고값으로 사용하지 않는다.',
        '5. Precision과 Recall도 seed별 계산 후 평균한다. 예측 support가 0이면 Precision=0이다.', '',
        '**seed 반복의 의미:** 같은 24개 관측에 대한 계산상 반복이다. 독립 참가자는 2명, 구간은 24개이며 5 seeds를 10명 또는 120개 독립 관측으로 해석하지 않는다. seed SD는 인구 일반화 불확실성·신뢰구간·통계적 유의성이 아니다. 새 네 알고리즘의 예측은 모든 seed에서 같았다. 이들의 SD=0도 독립 검증의 확실성을 뜻하지 않는다.', '',
        '## 공통 입력·사전 고정 조건', '',
        '원본 H9 F1~F9와 기존 집계를 재사용했다. H9-v2, 특징 선택, 수식 변경, imputation, calibration, 새 모델 정의 변경은 없다. 참가자별 12구간·클래스당 2구간, 공동 유효 프레임 3,613개, 제외 구간·프레임 0이다. 모든 모델에 동일한 두 LOSO 분할을 적용했다.',
        '기존 M0는 직접 구현 rf_experiment.Forest, 500 trees, max_features=2, bootstrap/Gini와 원시 H9 입력을 유지했다. 새 네 모델은 학습 참가자 12구간에서만 StandardScaler를 fit했다. 검증 참가자는 transform만 적용했다. M0를 sklearn RF로 바꾸지 않았다. 전체 설정은 protocol.json에 있다.',
        'RBF-SVM: C=1, gamma=1/9. Linear SVM: C=1, L2/squared_hinge, dual=False, OVR. Logistic Regression: C=1, L2, lbfgs multinomial. 두 선형 모델 max_iter=10000. KNN: k=3, uniform, Euclidean, brute. 한 설정씩 실행 전에 고정했고 튜닝하지 않았다.', '',
        '## 전체 성능', '', '단위 %, ±는 seed SD(ddof=0), 차이는 기존 M0 대비 pp.']
    rows = []
    for n in MODELS:
        s = d['results'][n]['scopes']['pooled']; delta = d['delta_from_existing_M0_pp'][n]['pooled']
        rows.append([n, f"{pct(s['mean']['accuracy'])} ± {pct(s['sd_ddof0']['accuracy'])}",
            f"{pct(s['mean']['macro_f1'])} ± {pct(s['sd_ddof0']['macro_f1'])}",
            f"{delta['accuracy_pp']:+.2f}", f"{delta['macro_f1_pp']:+.2f}", pct(d['participant_mean_macro_f1'][n])])
    table(lines, ['모델', 'Accuracy', '전체 Macro-F1', 'ΔAccuracy', 'ΔMacro-F1', '참가자 Macro-F1 평균(별도 지표)'], rows)
    lines += ['## 참가자별 결과', '', 'A 검증은 B에서 학습, B 검증은 A에서 학습했다. 각각 12구간이다.']
    table(lines, ['범위', '모델', 'Accuracy %', 'Macro-F1 %', 'P0 Recall %', 'P1 Recall %'],
        [[scope,n,pct(s['mean']['accuracy']),pct(s['mean']['macro_f1']),pct(s['mean_per_class'][0]['recall']),pct(s['mean_per_class'][1]['recall'])]
         for scope in SCOPES[1:] for n in MODELS for s in [d['results'][n]['scopes'][scope]]])
    lines += ['## Logistic Regression: P0/P1 검토', '',
        '**전체 P0 Recall=2/4=50%, P1 Recall=3/4=75%.** P1→P5는 0/4다. 모든 seed에서 같은 결과다.',
        '전체 오분류는 P0→P1 1건, P0→P2 1건, P1→P0 1건으로 총 3/24다. 따라서 정확도는 21/24=87.50%다. P2~P5는 실제 클래스별 Recall 100%이나 P0→P2 때문에 P2 Precision은 80%다.',
        '참가자 A: P0 Recall 50%, P1 Recall 50%; P0→P2 및 P1→P0 각 1건. 참가자 B: P0 Recall 50%, P1 Recall 100%; P0→P1 1건.',
        '기존 M0 대비 P0 Recall은 45%→50%, P1 Recall은 25%→75%, P1→P5는 40%→0%다. A의 Accuracy는 M0 85%에서 83.33%로 낮아졌으므로 모든 참가자·지표에서 개선됐다고 주장하지 않는다.', '',
        '## 클래스별 Precision/Recall/F1', '', '표시값은 seed별 지표의 평균(%). 실제 support는 pooled 클래스당 4, 참가자별 클래스당 2다.']
    for scope in SCOPES:
        lines += ['', f'### {scope}']
        table(lines, ['모델','클래스','support','Precision %','Recall %','F1 %'],
            [[n,c['posture'],c['support'],pct(c['precision']),pct(c['recall']),pct(c['f1'])]
             for n in MODELS for c in d['results'][n]['scopes'][scope]['mean_per_class']])
    lines += ['## P1→P0 / P5', '', '분모는 실제 P1 구간 수다. M0 건수는 seed별 평균이므로 소수일 수 있다.']
    table(lines, ['범위','모델','P1 Recall %','P1→P0 평균 건수','P1→P0 %','P1→P5 평균 건수','P1→P5 %'],
        [[scope,n,pct(s['mean_per_class'][1]['recall']),s['mean_p1_errors']['P1_to_P0']['count'],pct(s['mean_p1_errors']['P1_to_P0']['rate']),
          s['mean_p1_errors']['P1_to_P5']['count'],pct(s['mean_p1_errors']['P1_to_P5']['rate'])]
         for scope in SCOPES for n in MODELS for s in [d['results'][n]['scopes'][scope]]])
    lines += ['## 혼동행렬', '',
        '행=실제 P0~P5, 열=예측 P0~P5. 아래는 seed별 count 평균이며 pooled 행 합=4, 참가자별 행 합=2다. 소수는 seed 반복 평균이다. 원시 seed별 정수 행렬과 수치 검증에 필요한 집계는 aggregate_results.json에 있다.']
    for scope in SCOPES:
        for n in MODELS:
            lines += ['', f'### {scope} / {n}', '', '```text', '       P0  P1  P2  P3  P4  P5']
            lines += [f'P{k}    ' + ' '.join(f'{v:3.1f}' for v in row)
                      for k,row in enumerate(d['results'][n]['scopes'][scope]['mean_confusion_matrix'])]
            lines.append('```')
    lines += ['', '## 연산 비용', '',
        '기존 측정 결과를 재사용했다. 이번 확정 작업에서는 학습·튜닝·추론시간 재측정을 하지 않았다. 같은 host·process에서 BLAS/OpenMP 1 thread, 단일 집계 표본 predict를 측정했다. 모델별 1,200회, 입력 표준화·집계·촬영·UI·startup은 모델 단독 timing에서 제외했다. 크기는 같은 비압축 pickle protocol=5를 사용한 10개 fold×seed 객체의 평균이며 라이브러리/RAM 크기가 아니다.']
    table(lines, ['모델','단독 p50 ms','단독 p95 ms','scaler+모델 p50 ms','모델 KiB','scaler+모델 KiB'],
        [[n,f"{c['classifier_ms']['median']:.4f}",f"{c['classifier_ms']['p95']:.4f}",f"{c['pipeline_ms']['median']:.4f}",
          f"{c['classifier_pickle_bytes']['mean']/1024:.3f}",f"{c['pipeline_pickle_bytes']['mean']/1024:.3f}"] for n in MODELS for c in [d['costs'][n]]])
    lines += ['M0에는 scaler가 없다. 따로 측정한 두 timing의 차이는 잡음을 포함하므로 scaler 비용의 추정치로 사용하지 않는다. 직접 구현 M0의 Python 객체/RNG와 sklearn의 구현 차이도 pickle 크기에 포함된다. D455 전체 성능이나 5-B 실측 결과로 해석하지 않는다.', '',
        '## 후속 후보와 제한', '',
        'Logistic Regression을 우선 후보로 유지한다. 전체 Macro-F1 86.84%(+11.11pp), P1 Recall 75%, 낮은 모델 비용을 함께 고려했다. P0 Recall 50%와 A의 소폭 Accuracy 감소가 남아 있다.',
        'RBF-SVM은 P0 Recall 75%로 정상 자세 오류 양상을 비교할 보조 후보다. P1 Recall은 25%, A의 P1 Recall은 0%여서 P1 감지 개선을 입증한 후보가 아니다.',
        'KNN은 A/B Macro-F1 60%/100%로 차이가 크고, Linear SVM은 P0 Recall 0%다. 이들 결과만으로 일반화 우위를 주장하지 않는다. 추가 독립 참가자 검증이 필요하며 본 파일럿을 재사용한 선정 자체가 탐색이다.', '',
        '## 검증·코드 보관·공유 범위', '',
        '저장된 구간별 예측에서 75개 모델×seed×범위의 혼동행렬과 지표를 재구성했다. participant 행렬의 합=pooled, seed별/평균 클래스 지표, P1 오류, 기존 M0 기준선, CSV 수치, 기존 보고서 표·행렬을 최종 대조했다. 검증 테스트는 학습 없이 저장 집계와 합성 혼동행렬의 계산/변조 검출만 확인한다.',
        '최초 실행은 마지막 참가자 기준 결과 조회 경로 오류로 출력 전에 중단됐다. 조회 경로만 고친 성공 평가 코드를 experiment/compare_fixed.py에 원문 보관했다. 원래 compare.py와 수정 diff도 보관한다. 모델·설정·분할은 바꾸지 않았다.',
        '공유 artifact의 code archive는 역사적 실행 코드다. 비공개 입력·소스 snapshot·원래 고정 계획이 없으면 실행할 수 없다. 민감 자료를 Git에 넣거나 synthetic 입력으로 연구 결과를 대체하지 않는다. 재현 절차는 experiment/README.md를 따른다.',
        '새 집계본은 원본 results.json·PLAN.json의 SHA-256을 provenance로 보관한다. 공개 JSON에는 표본별 특징/예측, 원본 입력, 학습 모델, fitted scaler, 사람/기기 identity, 절대 경로가 없다. 원본 결과와 5-B 후보/모델/스냅샷은 수정하지 않았다.', '',
        '검증: `python -B verify_results.py`, `python -B -m unittest -v test_verify_results.py`.', '',
        '참고: 원래 API 참고 링크는 protocol.json에 있다. 정식 연구 결정, 데이터 계약, Patch 8 실행 승인 또는 CAP-007 보류 상태는 변경하지 않는다.']
    return '\n'.join(lines) + '\n'


def export(private, public):
    source = load(private / 'results.json'); plan = load(private / 'PLAN.json')
    source_hash = digest(private / 'results.json'); plan_hash = digest(private / 'PLAN.json')
    if source['plan_sha256'] != plan_hash:
        raise ValueError('private result/plan mismatch')
    mapping = {'pooled':'pooled', 'P01':'participant_A', 'P02':'participant_B'}
    results = {name: dict(scopes={mapping[k]:v for k,v in r['scopes'].items()}) for name,r in source['results'].items()}
    cm = results['Logistic-Regression']['scopes']['pooled']['mean_confusion_matrix']
    d = dict(kind='shareable anonymous aggregate evidence; no sample-level records',
        sample_count=24, participant_count=2, class_order=source['class_order'], feature_order=source['feature_order'], seeds=source['seeds'],
        results=results, costs=source['costs'],
        participant_mean_macro_f1={n:statistics.mean(r['scopes'][s]['mean']['macro_f1'] for s in SCOPES[1:]) for n,r in results.items()},
        delta_from_existing_M0_pp={n:{mapping[s]:v for s,v in r.items()} for n,r in source['delta_from_existing_M0_pp'].items()},
        logistic_regression_error_summary=dict(P0_recall=cm[0][0]/sum(cm[0]),P1_recall=cm[1][1]/sum(cm[1]),
            off_diagonal_counts_per_seed={f'P{i}_to_P{j}':cm[i][j] for i in range(6) for j in range(6) if i!=j and cm[i][j]}),
        environment={k:source['environment'][k] for k in ('python','platform','processor','machine','logical_cpu_count','packages')},
        provenance=dict(private_result_sha256=source_hash,private_plan_sha256=plan_hash,
            successful_evaluator_sha256=digest(private/'compare_fixed.py'), original_evaluator_sha256=digest(private/'compare.py')),
        limits=source['limitations'])
    verified = verify(d)
    protocol = {k:plan[k] for k in ('feature_set','sample_count','seeds','model_parameters','preprocessing','tuning','seed_interpretation','selection_rule','benchmark','documentation_urls')}
    protocol.update(overall_macro_f1='For each seed: mean six class F1s on pooled 24 OOF samples; then mean across five seeds.',
        distinct_participant_mean_macro_f1='Mean of two participant-specific Macro-F1 seed means; reported separately.',
        original_plan_sha256=plan_hash, no_new_experiment=True)
    # Only aggregate fields and explicit code files are copied; no private tree traversal.
    write_json(public/'aggregate_results.json', d); write_json(public/'protocol.json',protocol)
    for name in ('performance.csv','class_metrics.csv'):
        with (private/name).open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
        with (public/name).open('x',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for row in rows:
                row['scope']=mapping[row['scope']];w.writerow(row)
    archive=public/'experiment';archive.mkdir(exist_ok=False)
    for name in ('compare.py','compare_fixed.py','EVALUATOR_FIX.json'):
        with (archive/name).open('xb') as f:f.write((private/name).read_bytes())
    with (public/'requirements.lock.txt').open('x',encoding='utf-8') as f:
        f.write((private/'requirements.lock.txt').read_text(encoding='utf-8'))
    with (public/'README.md').open('x',encoding='utf-8',newline='\n') as f:f.write(report(d,protocol))
    write_json(public/'verification.json',dict(**verified,created_utc=datetime.now(timezone.utc).isoformat(),
        no_training_tuning_or_new_measurement=True, publication_is_aggregate_only=True,
        result_sha256=digest(public/'aggregate_results.json'),protocol_sha256=digest(public/'protocol.json')))
    if digest(private/'results.json')!=source_hash or digest(private/'PLAN.json')!=plan_hash:
        raise ValueError('private evidence changed during export')
    print(json.dumps(verified,indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-analysis-dir',type=Path,required=True)
    p.add_argument('--public-dir',type=Path,default=Path(__file__).resolve().parent);a=p.parse_args()
    export(a.private_analysis_dir.resolve(strict=True),a.public_dir.resolve(strict=True))
