"""Fixed H9 LR/M0/SVM-RBF comparison on the private reviewed pilot120 bundle.

python -X utf8 -B compare_pilot120_fixed_models.py [--verify]
Reuse historical factories/seeds; no feature, parameter or threshold search.
"""
import argparse
import ast
from collections import Counter
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT, read, digest
from lr_posture_demo import FACTORY
from bundle_pilot120 import OUT as BUNDLE, SOURCE, validate_source, verify as verify_bundle
from evaluate_new_pilot_lr6 import metrics, write
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows

import numpy as np
import rf_experiment as rf
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

OUT = ROOT/"analysis/PILOT120_FIXED_MODELS_20261108"
SEEDS = (0,1,2,3,4)
NAMES = ("M0","SVM-RBF")


def factory(name,seed):
    node = next(n for n in ast.parse(FACTORY.read_text(encoding="utf-8")).body
                if isinstance(n,ast.FunctionDef) and n.name=="make_model")
    scope = dict(rf=rf,SVC=SVC)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(FACTORY),"exec"),scope)
    return scope["make_model"](name,seed)


def summarize(y,predictions):
    per_seed = [metrics(y,p) for p in predictions]
    keys = ("accuracy","macro_f1","macro_precision","macro_recall","weighted_f1")
    return dict(per_seed=per_seed,mean={k:float(np.mean([m[k] for m in per_seed])) for k in keys},
        sd={k:float(np.std([m[k] for m in per_seed])) for k in keys},
        recall=np.mean([[r["recall"] for r in m["per_class"]] for m in per_seed],axis=0).tolist())


def report(s):
    lines = ["# 균형120구간·9특징: 고정 LR/RF M0/SVM-RBF 비교", "",
        "실험 ID: `EXPLR-PILOT120-H9-FIXED-MODELS-20261108`. 같은2명의 반복 탐색자료다. "
        "모델을 바꿔 정상/거북목 오류를 줄일 수 있는지 확인하며 독립 검증·공식 모델 선정은 아니다.", "",
        "## 고정 조건과 통합 자료", "",
        "기존113개 적격 구간+P01 P5 기술적 보완7개=120개, 참가자당60개/자세당20개. "
        "이미 LR 평가에 사용한 동일 행렬·라벨·sample identity를 local_private/dataset120의 "
        "samples.csv와 bundle_info.json으로 묶었다. 처음24개·중단 실행·기술적 실패7개는 평가에 합치지 않는다. "
        "원본과 실패 이력은 별도 보존한다. CSV/묶음은 로컬 전용이며 canonical selection manifest가 아니다.", "",
        "모든 모델 입력은F1~F9. 기존 support/집계/적격 기준을 유지했다. 참가자 LOSO2fold 각60/60이며 "
        "P01 두 날짜 세션은 같은 fold다. LR은 저장된9특징 OOF를 재사용해 재학습0회다.", "",
        "기존 compare_fixed.py의 make_model을 그대로 재사용했다. M0=기존 rf_experiment.Forest, "
        "6-class/500trees/max_features=2/split_w=None, 추가 scaler 없음. "
        "SVM-RBF=C=1,gamma=1/9,tol=1e-3,probability=False,나머지 기존 설정 유지; "
        "StandardScaler는 train fold에서만 fit. seeds=(0,1,2,3,4)는 과거 탐색 비교와 같고 "
        "신규 학습은2모델×5seeds×2fold=20회다. 특징 조합·C/gamma·class weight·임계값을 탐색하지 않았다.", "",
        "## 전체 결과", "",
        "RF/SVM은 seed별120개 OOF 지표를 먼저 계산한 뒤5개 평균이다. 괄호는 seed SD(ddof=0)이며 "
        "신뢰구간/새 참가자 변동이 아니다. seed 반복을600개 독립 구간으로 세지 않는다. LR은seed0 한 결과다.", "",
        "|모델|Accuracy % (SD)|Macro-F1 % (SD)|Macro Precision %|Macro Recall %|P0 Recall %|P1 Recall %|P2 Recall %|P3 Recall %|P4 Recall %|P5 Recall %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["summary"].items():
        lines.append(f"|{name}|{r['mean']['accuracy']:.2f} ({r['sd']['accuracy']:.2f})|"
            f"{r['mean']['macro_f1']:.2f} ({r['sd']['macro_f1']:.2f})|"+
            "|".join(f"{v:.2f}" for v in [r["mean"]["macro_precision"],r["mean"]["macro_recall"],*r["recall"]])+"|")
    lines += ["", "## LR9 대비 오류 변화", "", "건수는 seed당 평균이다.", "",
        "|모델|오답→정답|정답→오답|오답→다른 오답|", "|---|---:|---:|---:|"]
    for name in NAMES:
        c = [changes(s["labels"],s["predictions"]["LR9"][0],p) for p in s["predictions"][name]]
        lines.append(f"|{name}|"+"|".join(f"{np.mean([r[k] for r in c]):.2f}" for k in
            ("wrong_to_correct","correct_to_wrong","wrong_to_wrong"))+"|")
    lines += ["", "## 오류 유형", "", "건수는 seed당 평균이다.", "",
        "|모델|실제→예측|평균 건수|", "|---|---|---:|"]
    for name,ps in s["predictions"].items():
        counts = Counter()
        for p in ps: counts.update(flows(s["labels"],p))
        for flow,n in sorted(counts.items()): lines.append(f"|{name}|{flow}|{n/len(ps):.2f}|")
    lines += ["", "## Seed별 결과", "", "|모델|seed|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|P5 Recall %|",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["summary"].items():
        for seed,m in enumerate(r["per_seed"]):
            vals = [m["accuracy"],m["macro_f1"],*[m["per_class"][i]["recall"] for i in (0,1,5)]]
            lines.append(f"|{name}|{seed}|"+"|".join(f"{v:.2f}" for v in vals)+"|")
    lines += ["", "## 해석·검증·보존", "",
        "현재120개로도 모델에 따른 관측 지표 차이를 비교할 수 있다. 개선은 결과로 판단하며 보장하지 않는다. "
        "정상 Recall만 올리고 거북목 Recall이나 다른 자세가 나빠지는지도 함께 확인한다. "
        "이 반복 탐색에서 우세한 모델이 새 사람/새 세션에서도 우세하다는 결론은 내리지 않는다.", "",
        "묶음/원본 hash·120개 identity/9열/라벨·동일 LOSO·train-only scaler·기존 생성기/seed·"
        "수렴·OOF1회·메모리상 직렬화 복원 예측·지표/CSV/MD를 확인했다. "
        "RF Tree/Forest AST가 과거 snapshot과 같은지도 확인했다. 전체 회귀·새 촬영·원본영상 열람·"
        "학습 비용 재측정·실시간 모델 변경은 하지 않았다.", "",
        "추가 파일은 compare_pilot120_fixed_models.py와 이 요약이다. 참가자별OOF/특징/계수 관련 "
        "fold자료·계획은local_private/에만 저장하고 모델파일은 추가 저장하지 않았다. "
        "공식8조합/B6/IRB HOLD/Patch8 실행 보류를 유지했다. Commit/Push 없음.", "",
        "실행: `python -X utf8 -B compare_pilot120_fixed_models.py`; 저장 검증은 `--verify`(학습 없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); s=read(OUT/"local_private/results.json"); source=read(SOURCE)
    assert s["labels"]==source["labels"] and s["subjects"]==source["subjects"] and s["sample_keys"]==source["sample_keys"]
    assert s["predictions"]["LR9"]==[source["results"]["LR9"]["predictions"]]
    y=np.array(s["labels"]); x=np.array(source["matrix"])
    for name,ps in s["predictions"].items():
        assert len(ps)==(1 if name=="LR9" else 5) and summarize(y,ps)==s["summary"][name]
    for name in NAMES:
        for seed in SEEDS:
            folds=[f for f in s["folds"] if f["model"]==name and f["seed"]==seed]
            assert len(folds)==2; seen=np.zeros(120,dtype=int)
            for f in folds:
                tr,te=f["train"],f["test"]
                assert tr==source["results"]["LR9"]["folds"][f["number"]]["train"]
                assert te==source["results"]["LR9"]["folds"][f["number"]]["test"]
                assert len(tr)==len(te)==60 and set(tr).isdisjoint(te)
                assert set(s["subjects"][i] for i in tr).isdisjoint(s["subjects"][i] for i in te)
                assert f["predictions"]==np.array(s["predictions"][name][seed])[te].tolist()
                if name=="SVM-RBF":
                    assert f["params"]==factory(name,seed).get_params() and f["fit_status"]==0
                    np.testing.assert_allclose(f["mean"],x[tr].mean(0),rtol=0,atol=1e-14)
                    np.testing.assert_allclose(f["scale"],x[tr].std(0),rtol=0,atol=1e-14)
                else: assert f["params"]==dict(n_classes=6,n_trees=500,max_features=2,split_w=None,seed=seed)
                seen[te]+=1
            assert seen.tolist()==[1]*120
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==1320
    for r in rows:
        i,seed=int(r["index"]),int(r["seed"])
        assert int(r["actual"])==y[i] and int(r["predicted"])==s["predictions"][r["model"]][seed][i]
    print("PASS: fixed120/H9/folds/parameters, train-only scalers, OOF metrics/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing outputs preserved; use --verify")
    verify_bundle(); source=read(SOURCE); validate_source(source)
    x=np.array(source["matrix"]); y=np.array(source["labels"])
    paths=[SOURCE,BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",FACTORY,ROOT/"rf_experiment.py",
           ROOT/"bundle_pilot120.py",ROOT/"evaluate_new_pilot_lr6.py",ROOT/"compare_lr_f2_f5.py",
           ROOT/"compare_new_pilot_lr9.py",Path(__file__).resolve()]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    snapshot=FACTORY.parent/"source/rf_experiment.py"
    def core(path):
        return [ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n,ast.ClassDef) and n.name in ("Tree","Forest")]
    assert core(ROOT/"rf_experiment.py")==core(snapshot)
    inputs[str(snapshot.relative_to(ROOT))]=digest(snapshot)
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_ONLY",samples=120,features=[f"F{i}" for i in range(1,10)],
        models=list(NAMES),seeds=list(SEEDS),new_fits=20,input_hashes=inputs,
        svm_params=factory("SVM-RBF",0).get_params(),rf_params=dict(n_classes=6,n_trees=500,max_features=2,split_w=None),
        hypothesis="fixed nonlinear classifiers may reduce P0/P1 errors versus LR9; no search"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    predictions={"LR9":[source["results"]["LR9"]["predictions"]],**{n:[] for n in NAMES}}; folds=[]
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        for seed in SEEDS:
            current={n:np.full(120,-1,dtype=int) for n in NAMES}
            for number,f in enumerate(source["results"]["LR9"]["folds"]):
                tr,te=f["train"],f["test"]
                for name in NAMES:
                    model=factory(name,seed); scaler=StandardScaler().fit(x[tr]) if name=="SVM-RBF" else None
                    train=scaler.transform(x[tr]) if scaler else x[tr]; test=scaler.transform(x[te]) if scaler else x[te]
                    model.fit(train,y[tr]); pred=model.predict(test); current[name][te]=pred
                    restored=pickle.loads(pickle.dumps(model,protocol=5))
                    np.testing.assert_array_equal(restored.predict(test),pred)
                    details=dict(model=name,seed=seed,number=number,train=tr,test=te,predictions=pred.tolist())
                    if scaler:
                        assert model.fit_status_==0
                        details.update(params=model.get_params(),fit_status=int(model.fit_status_),mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist())
                    else: details["params"]=dict(n_classes=model.K,n_trees=model.T,max_features=model.mf,split_w=model.sw,seed=model.seed)
                    folds.append(details)
            for name in NAMES: predictions[name].append(current[name].tolist())
    saved=dict(inputs=inputs,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
        predictions=predictions,summary={n:summarize(y,p) for n,p in predictions.items()},folds=folds,
        warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in recorded)),numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["model","seed","index","actual","predicted"]); writer.writeheader()
        for name,ps in predictions.items():
            for seed,p in enumerate(ps): writer.writerows(dict(model=name,seed=seed,index=i,actual=int(y[i]),predicted=v) for i,v in enumerate(p))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify()
    for name,s in saved["summary"].items(): print(name,s["mean"],"recall",s["recall"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
