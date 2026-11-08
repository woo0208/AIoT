"""Complete the existing five-classifier H9 comparison on the same pilot120.

python -X utf8 -B compare_pilot120_linear_knn.py [--verify]
Fit only fixed Linear SVM and KNN; reuse LR/RF/SVM-RBF results.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT, read, digest
from lr_posture_demo import FACTORY
from bundle_pilot120 import SOURCE, OUT as BUNDLE, verify as verify_bundle
from compare_pilot120_fixed_models import OUT as PRIOR, SEEDS, summarize
from compare_six_feature_svm_knn import factory
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from evaluate_new_pilot_lr6 import write

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT/"analysis/PILOT120_FIVE_MODELS_20261108"
NAMES = ("Linear-SVM","KNN")


def report(saved):
    lines = ["# 같은120구간·9특징: 기존5개 분류기 비교 완료", "",
        "실험 ID: `EXPLR-PILOT120-H9-FIVE-MODELS-20261108`. 추가한 모델은 기존 Linear SVM/KNN뿐이다. "
        "LR/RF M0/SVM-RBF는 바로 이전의 동일120구간 결과를 재사용했다. 두 사람 반복 탐색자료이며 "
        "독립 검증·최종 운영 모델 선정·새 참가자 일반화 결과가 아니다.", "",
        "## 입력과 고정 조건", "",
        "기존113개 적격 구간+P01 P5 보완7개=120개. 참가자당60개, 자세별20개. "
        "F1~F9 전부, 동일H9 공동지원/집계/적격 기준/identity/라벨, 동일 참가자LOSO 각60/60을 유지했다. "
        "처음24구간·중단 실행·기술적 실패7개는 포함하지 않았다. P01의 두 날짜 세션은 같은 fold다.", "",
        "기존 compare_fixed.py의 make_model을 그대로 호출했다. LinearSVC는C=1,L2,squared_hinge, "
        "dual=False,OVR,tol=1e-4,max_iter=10000; KNN은k=3,uniform,brute,Minkowski p=2다. "
        "둘 다 각 train fold에서만 StandardScaler fit. seeds=(0,1,2,3,4)를 유지했다. "
        "새 학습은2모델×5seeds×2fold=20회이며 이전3개 모델은재학습0회다. "
        "특징 조합·하이퍼파라미터·임계값·가중치 탐색을 하지 않았다.", "",
        "## 전체 지표", "",
        "LR은seed0 단일 결과, 나머지는seed별120개 OOF 지표의5개 평균이다. 괄호는seed SD(ddof=0)다. "
        "반복seed는추가 참가자/600개 독립 구간/신뢰구간이 아니다.", "",
        "|모델|Accuracy % (SD)|Macro-F1 % (SD)|Macro Precision %|Macro Recall %|P0 Recall %|P1 Recall %|P2 Recall %|P3 Recall %|P4 Recall %|P5 Recall %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name,result in saved["summary"].items():
        m,sd = result["mean"],result["sd"]
        lines.append(f"|{name}|{m['accuracy']:.2f} ({sd['accuracy']:.2f})|{m['macro_f1']:.2f} ({sd['macro_f1']:.2f})|"+
            "|".join(f"{v:.2f}" for v in [m["macro_precision"],m["macro_recall"],*result["recall"]])+"|")
    lines += ["", "## 추가2개 모델: SVM-RBF 대비 예측 변화", "",
        "seed별 같은120개 구간을 대응 비교한 뒤 건수를 평균했다. SVM-RBF는5seed 예측이 같았다.", "",
        "|모델|오답→정답|정답→오답|오답→다른 오답|", "|---|---:|---:|---:|"]
    for name in NAMES:
        paired = [changes(saved["labels"],saved["predictions"]["SVM-RBF"][i],p) for i,p in enumerate(saved["predictions"][name])]
        lines.append(f"|{name}|"+"|".join(f"{np.mean([c[k] for c in paired]):.2f}" for k in
            ("wrong_to_correct","correct_to_wrong","wrong_to_wrong"))+"|")
    lines += ["", "## 오류 유형", "", "건수는seed당 평균이다.", "", "|모델|실제→예측|평균 건수|", "|---|---|---:|"]
    for name,ps in saved["predictions"].items():
        counter = Counter()
        for pred in ps: counter.update(flows(saved["labels"],pred))
        for flow,count in sorted(counter.items()): lines.append(f"|{name}|{flow}|{count/len(ps):.2f}|")
    lines += ["", "## 추가2개 seed별 지표", "", "|모델|seed|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|P5 Recall %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name in NAMES:
        for seed,m in enumerate(saved["summary"][name]["per_seed"]):
            v = [m["accuracy"],m["macro_f1"],*[m["per_class"][i]["recall"] for i in (0,1,5)]]
            lines.append(f"|{name}|{seed}|"+"|".join(f"{x:.2f}" for x in v)+"|")
    lines += ["", "## 검증·보존·해석", "",
        "통합자료/원본/이전 결과 hash, 120개 identity/9열/라벨, 동일fold·train-only scaler, "
        "생성기/고정params/seed·수렴·OOF1회, 메모리상 직렬화 복원 예측, 지표/CSV/MD를 확인했다. "
        "단위는프레임이 아닌구간이다. 전체 회귀·추가 촬영·원본 영상 열람·실행 비용 재측정은없다.", "",
        "코드 compare_pilot120_linear_knn.py와 이 보고서만 추가했다. 참가자별OOF/점수/학습통계/계획은 "
        "local_private/에만 저장하고 모델파일은 추가 저장하지 않았다. 이전보고서·기존모델·원본을 덮어쓰지 않았다. "
        "공식8조합/B6/IRB HOLD/Patch8 실행 보류는유지하며 Commit/Push는하지 않았다.", "",
        "현재 탐색 성적과 P0/P1/P5 Recall을 함께 판단해야 한다. 새 알고리즘을 계속 추가하거나 "
        "이 자료에서 최고점이 나올 때까지 설정을 탐색하지 않았다. 남은 오류 분석을 바탕으로 "
        "구체적 가설을 정하는 단계와 새 참가자/세션 확인은 별도다.", "",
        "실행: `python -X utf8 -B compare_pilot120_linear_knn.py`; 저장 검증은 `--verify`(학습 없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); saved=read(OUT/"local_private/results.json"); prior=read(PRIOR/"local_private/results.json"); source=read(SOURCE)
    for key in ("labels","subjects","sample_keys"): assert saved[key]==prior[key]==source[key]
    y=np.array(saved["labels"]); x=np.array(source["matrix"])
    for name,ps in saved["predictions"].items():
        assert summarize(y,ps)==saved["summary"][name]
        if name not in NAMES: assert ps==prior["predictions"][name]
    for name in NAMES:
        for seed in SEEDS:
            records=[f for f in saved["folds"] if f["model"]==name and f["seed"]==seed]
            assert len(records)==2; seen=np.zeros(120,dtype=int)
            for f in records:
                expected=source["results"]["LR9"]["folds"][f["number"]]; tr,te=f["train"],f["test"]
                assert tr==expected["train"] and te==expected["test"] and set(tr).isdisjoint(te)
                assert len(tr)==len(te)==60 and set(saved["subjects"][i] for i in tr).isdisjoint(saved["subjects"][i] for i in te)
                assert f["params"]==factory(name,seed).get_params()
                np.testing.assert_allclose(f["mean"],x[tr].mean(0),rtol=0,atol=1e-14)
                np.testing.assert_allclose(f["scale"],x[tr].std(0),rtol=0,atol=1e-14)
                assert f["predictions"]==np.array(saved["predictions"][name][seed])[te].tolist()
                if name=="Linear-SVM": assert f["n_iter"]<f["params"]["max_iter"]
                seen[te]+=1
            assert seen.tolist()==[1]*120
    for path,sha in saved["inputs"].items(): assert digest(ROOT/path)==sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==2520
    for row in rows:
        i,seed=int(row["index"]),int(row["seed"])
        assert int(row["actual"])==y[i] and int(row["predicted"])==saved["predictions"][row["model"]][seed][i]
    assert report(saved) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: identical120/H9/LOSO, unchanged prior3 predictions, fixed parameters/train-only scalers, OOF metrics/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing outputs preserved; use --verify")
    verify_bundle(); prior=read(PRIOR/"local_private/results.json"); source=read(SOURCE)
    for path,sha in prior["inputs"].items(): assert digest(ROOT/path)==sha
    for key in ("labels","subjects","sample_keys"): assert source[key]==prior[key]
    paths=[SOURCE,PRIOR/"local_private/results.json",BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",FACTORY,
        ROOT/"bundle_pilot120.py",ROOT/"compare_pilot120_fixed_models.py",ROOT/"compare_six_feature_svm_knn.py",
        ROOT/"compare_lr_f2_f5.py",ROOT/"compare_new_pilot_lr9.py",ROOT/"evaluate_new_pilot_lr6.py",Path(__file__).resolve()]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_ONLY",samples=120,features=[f"F{i}" for i in range(1,10)],
        models=list(NAMES),seeds=list(SEEDS),new_fits=20,params={n:factory(n,0).get_params() for n in NAMES},input_hashes=inputs,
        purpose="complete the previously used five fixed classifiers; no parameter or feature search"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    x,y=np.array(source["matrix"]),np.array(source["labels"]); folds=[]
    predictions={**prior["predictions"],**{n:[] for n in NAMES}}
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        for seed in SEEDS:
            current={n:np.full(120,-1,dtype=int) for n in NAMES}
            for number,f in enumerate(source["results"]["LR9"]["folds"]):
                tr,te=f["train"],f["test"]; scaler=StandardScaler().fit(x[tr])
                train,test=scaler.transform(x[tr]),scaler.transform(x[te])
                for name in NAMES:
                    model=factory(name,seed); model.fit(train,y[tr]); pred=model.predict(test); current[name][te]=pred
                    restored=pickle.loads(pickle.dumps(model,protocol=5)); np.testing.assert_array_equal(restored.predict(test),pred)
                    fold=dict(model=name,seed=seed,number=number,train=tr,test=te,params=model.get_params(),
                        mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),predictions=pred.tolist())
                    if name=="Linear-SVM":
                        assert model.n_iter_<model.max_iter
                        fold.update(n_iter=int(model.n_iter_),coef=model.coef_.tolist(),intercept=model.intercept_.tolist(),scores=model.decision_function(test).tolist())
                    folds.append(fold)
            for name in NAMES: predictions[name].append(current[name].tolist())
    saved=dict(inputs=inputs,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
        predictions=predictions,summary={n:summarize(y,p) for n,p in predictions.items()},folds=folds,
        warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in recorded)),numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["model","seed","index","actual","predicted"]); writer.writeheader()
        for name,ps in predictions.items():
            for seed,pred in enumerate(ps): writer.writerows(dict(model=name,seed=seed,index=i,actual=int(y[i]),predicted=p) for i,p in enumerate(pred))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify()
    for name in NAMES: print(name,saved["summary"][name]["mean"],"recall",saved["summary"][name]["recall"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
