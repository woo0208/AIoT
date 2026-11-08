"""Four predeclared F2/F5 ablations after F9 removal, on five fixed classifiers.

python -X utf8 -B compare_pilot120_feature_sets.py [--verify]
Same120/LOSO; reuse KNN8, LR6 and all prior H9 results. No adaptive search.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT,read,digest
from bundle_pilot120 import SOURCE,OUT as BUNDLE,verify as verify_bundle
from compare_pilot120_linear_knn import OUT as PRIOR
from compare_pilot120_knn_drop_f9 import OUT as DROP
from compare_pilot120_fixed_models import factory as rf_factory,summarize,SEEDS
from compare_six_feature_svm_knn import factory as sklearn_factory
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from evaluate_new_pilot_lr6 import write
from lr_posture_demo import fixed_lr,FACTORY

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT=ROOT/"analysis/PILOT120_FEATURE_SETS_20261108"
CONFIGS={"H8":tuple(range(8)),"H7_DROP_F2":(0,2,3,4,5,6,7),
         "H7_DROP_F5":(0,1,2,3,5,6,7),"H6":(0,2,3,5,6,7)}
MODELS=("LR","M0","SVM-RBF","Linear-SVM","KNN")


def seeds_for(name):
    return (0,) if name in ("LR","KNN") else SEEDS


def factory(name,seed):
    if name=="LR": return fixed_lr()
    if name=="M0": return rf_factory(name,seed)
    return sklearn_factory(name,seed)


def expected_params(name,seed):
    if name=="M0": return dict(n_classes=6,n_trees=500,max_features=2,split_w=None,seed=seed)
    return factory(name,seed).get_params()


def reuse(config,name,source,drop):
    if (config,name)==("H8","KNN"): return [drop["results"]["KNN8_DROP_F9"]["predictions"]]
    if (config,name)==("H6","LR"): return [source["results"]["LR6"]["predictions"]]
    return None


def report(s):
    lines=["# 같은120구간: 6·7·8특징과 기존5개 알고리즘 고정 비교", "",
        "실험 ID: `EXPLR-PILOT120-F2-F5-AFTER-F9-20261108`. 사용자 요청에 따라 F9 제거 후 "
        "기존 F2/F5 가설의 네 구성을 사전에 고정했다. 수치에 따라 다음 조합을 고르는 자동 탐색이 아니다. "
        "두 사람의 반복 탐색자료이며 독립 검증·공식 선정·일반화 성능 향상으로 해석하지 않는다.", "",
        "## 특징 구성과 변경 범위", "",
        "현재 직전 후보는8특징 F1~F8이며 이전6특징과 다르다. 이번에는 수식을 바꾸거나 새 특징을 만들지 않고 "
        "저장된 동일9열 집계에서 열만 선택했다.", "",
        "|구성|사용 특징|F1~F9 기준 제외|",
        "|---|---|---|"]
    for name,cols in CONFIGS.items():
        lines.append(f"|{name}|{','.join(f'F{j+1}' for j in cols)}|{','.join(f'F{j+1}' for j in range(9) if j not in cols)}|")
    lines += ["", "|특징|실제 의미|이번 처리|", "|---|---|---|",
        "|F1|어깨 대비 머리 중심 좌우 위치/2D 어깨너비|네 구성에서 유지|",
        "|F2|어깨 대비 머리 중심 수직 위치/2D 어깨너비|H8·H7_DROP_F5에서 유지, 나머지 제외|",
        "|F3|iris 중점→턱 방향의 영상 내 기울기|네 구성에서 유지|",
        "|F4|귀 중점−iris 중점의 수직 차/2D 어깨너비|네 구성에서 유지|",
        "|F5|코–턱 2D 거리/2D 어깨너비|H8·H7_DROP_F2에서 유지, 나머지 제외|",
        "|F6|어깨로 정한 흉부ROI의 metric 깊이|네 구성에서 유지|",
        "|F7|어깨 깊이−흉부ROI 깊이|네 구성에서 유지|",
        "|F8|흉부ROI 깊이−코 깊이|네 구성에서 유지|",
        "|F9|F8/3D 어깨너비|네 구성 모두 제외, 기존 H9 결과를 비교 기준으로 재사용|", "",
        "## 평가와 재사용", "",
        "120구간, 참가자당60개·자세당20개, 동일 identity/라벨/H9 공동지원·집계·적격 기준을 유지했다. "
        "참가자LOSO 각 train60/test60이며 P01 두 날짜 세션은 같은 fold다. 처음24개·기술적 실패7개·"
        "중단 실행은 합치지 않았다. StandardScaler는 LR/SVM/Linear SVM/KNN의 train fold에서만 fit, "
        "M0는 기존대로 scaler 없이 원값을 사용했다.", "",
        "모든 알고리즘은 기존 생성기를 재사용했다. LR=C1/L2/lbfgs, RF M0=500trees/max_features2, "
        "SVM-RBF=C1/gamma1/9, LinearSVC=C1/L2/squared_hinge/dualFalse, KNN=k3/uniform/Euclidean이다. "
        "특징 수를 줄여도 gamma를 바꾸지 않았다. 다른 파라미터·가중치·임계값은 고정했다.", "",
        "LR은 기존 결정적 seed0, KNN은 난수 인수가 없어 동일 결과 반복 비용을 줄이고 각 구성당2fold만 fit했다. "
        "RF/SVM/Linear SVM은 기존 seeds=(0,1,2,3,4)를 유지했다. RF 이외의 seed 반복이 독립 표본을 늘리지는 않는다. "
        f"기존 H8 KNN·H6 LR·H9 다섯 모델은 저장 결과를 재사용했다. 신규 학습은 {s['new_fits']}회다. "
        "후보 학습 전에 PLAN.json을 저장했다.", "",
        "## 정확도 개요", "",
        "단위 %. LR/KNN은 한 OOF 결과, RF/SVM/Linear SVM은 seed별120개 OOF 지표의 평균이다.", "",
        "|모델|기존 H9|H8|H7_DROP_F2|H7_DROP_F5|H6|", "|---|---:|---:|---:|---:|---:|"]
    for name in MODELS:
        vals=[s["baseline9"][name]["mean"]["accuracy"],*[s["summary"][c][name]["mean"]["accuracy"] for c in CONFIGS]]
        lines.append(f"|{name}|"+"|".join(f"{v:.2f}" for v in vals)+"|")
    lines += ["", "## 모든 고정 구성의 상세 지표", "",
        "괄호는 seed SD(ddof=0)이며 신뢰구간이 아니다. Macro-F1은 seed별로 계산한 뒤 평균했다.", "",
        "|구성|모델|Accuracy % (SD)|Macro-F1 % (SD)|Macro Precision %|Macro Recall %|P0 Recall %|P1 Recall %|P2 Recall %|P3 Recall %|P4 Recall %|P5 Recall %|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for config in ("H9",*CONFIGS):
        for name in MODELS:
            r=s["baseline9"][name] if config=="H9" else s["summary"][config][name]
            m,sd=r["mean"],r["sd"]
            lines.append(f"|{config}|{name}|{m['accuracy']:.2f} ({sd['accuracy']:.2f})|{m['macro_f1']:.2f} ({sd['macro_f1']:.2f})|"+
                "|".join(f"{v:.2f}" for v in [m["macro_precision"],m["macro_recall"],*r["recall"]])+"|")
    lines += ["", "## 동일 모델 H9 대비 오류 변화", "", "건수는 seed당 평균이다.", "",
        "|구성|모델|오답→정답|정답→오답|오답→다른 오답|", "|---|---|---:|---:|---:|"]
    for config in CONFIGS:
        for name in MODELS:
            ps=s["predictions"][config][name]; ref=s["baseline9_predictions"][name]
            paired=[changes(s["labels"],ref[min(i,len(ref)-1)],p) for i,p in enumerate(ps)]
            lines.append(f"|{config}|{name}|"+"|".join(f"{np.mean([c[k] for c in paired]):.2f}" for k in
                ("wrong_to_correct","correct_to_wrong","wrong_to_wrong"))+"|")
    lines += ["", "## 각 구성 오류 유형", "", "건수는 seed당 평균이다.", "",
        "|구성|모델|실제→예측|평균 건수|", "|---|---|---|---:|"]
    for config in CONFIGS:
        for name in MODELS:
            ps=s["predictions"][config][name]; counter=Counter()
            for p in ps: counter.update(flows(s["labels"],p))
            for flow,n in sorted(counter.items()): lines.append(f"|{config}|{name}|{flow}|{n/len(ps):.2f}|")
    lines += ["", "## 검증·보존·제한", "",
        "동일120개 identity/행렬/라벨·고정 열과 파라미터·참가자 분리·train-only scaler·기존 열별 통계와의 일치·"
        "각 seed OOF1회·수렴·메모리상 직렬화 복원·지표/CSV/MD·입력 hash를 확인했다. "
        "전체 회귀·새 특징·촬영·원본영상 열람·실행비용 재측정은 하지 않았다.", "",
        "추가한 파일은 compare_pilot120_feature_sets.py와 이 요약이다. 참가자별 특징/OOF/표준화/모델별 "
        "fold·계획·경고는 local_private/에만 보관한다. 기존 데이터·보고서·실시간 모델·공식8조합/B6/IRB HOLD/"
        "Patch8 실행 보류는 유지했고 Commit/Push는 하지 않았다.", "",
        "최고 수치만으로 F2/F5/F9가 항상 불필요하다고 판단하지 않는다. 이 실험은 기존 탐색 결과를 보고 정한 "
        "네 구성을 다시 비교한 것이며 독립 검증이 아니다. 각 클래스 Recall과 신규 오류도 함께 판단한다. "
        "추가 알고리즘/조합을 결과에 따라 자동 확장하지 않았다.", "",
        "실행: `python -X utf8 -B compare_pilot120_feature_sets.py`; 저장 검증은 `--verify`(학습 없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); s=read(OUT/"local_private/results.json"); source=read(SOURCE); prior=read(PRIOR/"local_private/results.json"); drop=read(DROP/"local_private/results.json")
    for key in ("labels","subjects","sample_keys"): assert s[key]==source[key]==prior[key]==drop[key]
    y=np.array(s["labels"]); full=np.array(source["matrix"])
    assert s["new_fits"]==len(s["folds"])==132
    for name in MODELS:
        n="LR9" if name=="LR" else name
        assert s["baseline9_predictions"][name]==prior["predictions"][n]
        assert s["baseline9"][name]==summarize(y,prior["predictions"][n])
    for config,cols in CONFIGS.items():
        matrix=full[:,cols]
        for name in MODELS:
            ps=s["predictions"][config][name]
            assert len(ps)==len(seeds_for(name)) and s["summary"][config][name]==summarize(y,ps)
            reused=reuse(config,name,source,drop)
            if reused is not None:
                assert ps==reused
                continue
            for i,seed in enumerate(seeds_for(name)):
                folds=[f for f in s["folds"] if f["config"]==config and f["model"]==name and f["seed"]==seed]
                assert len(folds)==2; seen=np.zeros(120,dtype=int)
                for f in folds:
                    tr,te=f["train"],f["test"]; ref=source["results"]["LR9"]["folds"][f["number"]]
                    assert tr==ref["train"] and te==ref["test"] and len(tr)==len(te)==60 and set(tr).isdisjoint(te)
                    assert set(s["subjects"][j] for j in tr).isdisjoint(s["subjects"][j] for j in te)
                    assert f["params"]==expected_params(name,seed)
                    assert f["predictions"]==np.array(ps[i])[te].tolist()
                    if name!="M0":
                        np.testing.assert_allclose(f["mean"],matrix[tr].mean(0),rtol=0,atol=1e-14)
                        np.testing.assert_allclose(f["scale"],matrix[tr].std(0),rtol=0,atol=1e-14)
                    if name=="SVM-RBF": assert f["fit_status"]==0 and f["params"]["gamma"]==1/9
                    if name in ("LR","Linear-SVM"): assert f["n_iter"]<f["params"]["max_iter"]
                    seen[te]+=1
                assert seen.tolist()==[1]*120
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==8160
    for row in rows:
        config,name,i,seed=row["config"],row["model"],int(row["index"]),int(row["seed"])
        position=list(seeds_for(name)).index(seed)
        assert int(row["actual"])==y[i] and int(row["predicted"])==s["predictions"][config][name][position][i]
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: four fixed feature sets/five models, reused results, same120/LOSO/params/scalers, OOF metrics/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing outputs preserved; use --verify")
    verify_bundle(); source=read(SOURCE); prior=read(PRIOR/"local_private/results.json"); drop=read(DROP/"local_private/results.json")
    for saved in (source,prior,drop):
        for path,sha in saved["inputs"].items(): assert digest(ROOT/path)==sha
    for key in ("labels","subjects","sample_keys"): assert source[key]==prior[key]==drop[key]
    paths=[SOURCE,PRIOR/"local_private/results.json",DROP/"local_private/results.json",BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",
        FACTORY,ROOT/"rf_experiment.py",ROOT/"lr_posture_demo.py",ROOT/"compare_pilot120_fixed_models.py",
        ROOT/"compare_six_feature_svm_knn.py",ROOT/"compare_lr_f2_f5.py",ROOT/"evaluate_new_pilot_lr6.py",Path(__file__).resolve()]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_PREDECLARED_FOUR_FEATURE_SETS",configs={k:list(v) for k,v in CONFIGS.items()},
        models=list(MODELS),seeds={n:list(seeds_for(n)) for n in MODELS},params={n:expected_params(n,0) for n in MODELS},
        input_hashes=inputs,new_fits=132,reused=["H8 KNN","H6 LR","H9 all five"],
        hypothesis="F9 removal across existing models; fixed F2/F5 effects using H8, H7-F2, H7-F5, H6 only; no adaptive combinations"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    x,y=np.array(source["matrix"]),np.array(source["labels"])
    predictions={}; folds=[]
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        for config,cols in CONFIGS.items():
            matrix=x[:,cols]; predictions[config]={}
            for name in MODELS:
                reused=reuse(config,name,source,drop)
                if reused is not None:
                    predictions[config][name]=reused; continue
                predictions[config][name]=[]
                for seed in seeds_for(name):
                    pred=np.full(120,-1,dtype=int)
                    for number,f in enumerate(source["results"]["LR9"]["folds"]):
                        tr,te=f["train"],f["test"]
                        scaler=StandardScaler().fit(matrix[tr]) if name!="M0" else None
                        train=scaler.transform(matrix[tr]) if scaler else matrix[tr]
                        test=scaler.transform(matrix[te]) if scaler else matrix[te]
                        model=factory(name,seed); model.fit(train,y[tr]); pred[te]=model.predict(test)
                        restored=pickle.loads(pickle.dumps(model,protocol=5)); np.testing.assert_array_equal(restored.predict(test),pred[te])
                        details=dict(config=config,model=name,seed=seed,number=number,train=tr,test=te,predictions=pred[te].tolist(),params=expected_params(name,seed))
                        if scaler:
                            assert model.get_params()==expected_params(name,seed)
                            prior_scaler=next(a for a in prior["folds"] if a["model"]=="KNN" and a["seed"]==0 and a["number"]==number)
                            np.testing.assert_allclose(scaler.mean_,np.array(prior_scaler["mean"])[list(cols)],rtol=0,atol=1e-14)
                            np.testing.assert_allclose(scaler.scale_,np.array(prior_scaler["scale"])[list(cols)],rtol=0,atol=1e-14)
                            details.update(mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist())
                        else:
                            assert (model.K,model.T,model.mf,model.sw,model.seed)==(6,500,2,None,seed)
                        if name in ("LR","Linear-SVM"):
                            count=int(np.max(model.n_iter_)); assert count<model.max_iter; details["n_iter"]=count
                        if name=="SVM-RBF": assert model.fit_status_==0; details["fit_status"]=int(model.fit_status_)
                        folds.append(details)
                    predictions[config][name].append(pred.tolist())
            print(config,"completed",flush=True)
    baseline={n:prior["predictions"]["LR9" if n=="LR" else n] for n in MODELS}
    saved=dict(inputs=inputs,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
        features={k:[f"F{j+1}" for j in v] for k,v in CONFIGS.items()},predictions=predictions,
        summary={c:{n:summarize(y,p) for n,p in models.items()} for c,models in predictions.items()},
        baseline9_predictions=baseline,baseline9={n:summarize(y,p) for n,p in baseline.items()},folds=folds,new_fits=len(folds),
        warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in recorded)),numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["config","model","seed","index","actual","predicted"]); writer.writeheader()
        for c,models in predictions.items():
            for n,ps in models.items():
                for seed,p in zip(seeds_for(n),ps): writer.writerows(dict(config=c,model=n,seed=seed,index=i,actual=int(y[i]),predicted=v) for i,v in enumerate(p))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify()
    for c,models in saved["summary"].items():
        for n,r in models.items(): print(c,n,{k:r["mean"][k] for k in ("accuracy","macro_f1")},"recall",r["recall"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
