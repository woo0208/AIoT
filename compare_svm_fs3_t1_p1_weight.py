"""One preregistered comparison: SVM-FS3-V0-T0 vs P1 class weight 1.5 T1.

python -X utf8 -B compare_svm_fs3_t1_p1_weight.py [--verify]
Reuse the two saved T0 models/scalers; fit T1 exactly twice, without a search.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT,read,digest
from bundle_pilot120 import SOURCE,OUT as BUNDLE,verify as verify_bundle
from review_pilot120_seven_candidates import OUT as BASE,COLUMNS,FEATURES
from compare_pilot120_feature_sets import OUT as FEATURE_RESULTS
from compare_six_feature_svm_knn import factory
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from evaluate_new_pilot_lr6 import metrics,write
from lr_posture_demo import FACTORY

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

OUT=ROOT/"analysis/SVM_FS3_V0_T1_P1W15_20261108"
T0="SVM-FS3-V0-T0"
T1="SVM-FS3-V0-T1"
WEIGHTS={0:1.0,1:1.5,2:1.0,3:1.0,4:1.0,5:1.0}


def criteria(candidate,baseline):
    recall=[r["recall"] for r in candidate["per_class"]]
    return dict(p1_recall_at_least_80=recall[1]>=80-1e-12,
        p0_recall_at_least_95=recall[0]>=95-1e-12,
        p2_p3_p4_p5_recall_100=all(r>=100-1e-12 for r in recall[2:]),
        accuracy_at_least_t0=candidate["accuracy"]>=baseline["accuracy"]-1e-12,
        macro_f1_at_least_t0=candidate["macro_f1"]>=baseline["macro_f1"]-1e-12)


def load_baseline():
    benchmark=read(BASE/"local_private/results.json"); source=read(SOURCE)
    reference=read(FEATURE_RESULTS/"local_private/results.json")
    for saved in (benchmark,source,reference):
        for path,sha in saved["inputs"].items(): assert digest(ROOT/path)==sha
    x=np.array(source["matrix"])[:,COLUMNS]; y=np.array(source["labels"])
    assert x.shape==(120,7) and np.bincount(y,minlength=6).tolist()==[20]*6
    assert source["sample_keys"]==reference["sample_keys"] and source["labels"]==reference["labels"]
    predictions=np.full(120,-1,dtype=int); scores=np.zeros((120,6)); pair=np.zeros(120); folds=[]; models=[]
    for number in (0,1):
        r=next(r for r in benchmark["records"] if r["model"]=="SVM-RBF" and r["repetition"]==0 and r["fold"]==number)
        path=ROOT/r["model_path"]; assert digest(path)==r["model_sha256"]
        with path.open("rb") as stream: model,scaler=pickle.load(stream)
        tr,te=r["train"],r["test"]
        assert model.get_params()==factory("SVM-RBF",0).get_params() and model.class_weight is None
        assert scaler.n_samples_seen_==60
        np.testing.assert_allclose(scaler.mean_,x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(scaler.scale_,x[tr].std(0),rtol=0,atol=1e-14)
        test=scaler.transform(x[te]); predictions[te]=model.predict(test)
        scores[te]=model.decision_function(test); pair[te]=model._decision_function(test)[:,0]
        folds.append(dict(number=number,train=tr,test=te,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
            params=model.get_params(),model_path=r["model_path"],model_sha256=r["model_sha256"],
            n_support=model.n_support_.tolist(),fit_status=int(model.fit_status_)))
        models.append((model,scaler,tr,te))
    assert predictions.tolist()==reference["predictions"]["H7_DROP_F2"]["SVM-RBF"][0]
    return source,x,y,dict(predictions=predictions.tolist(),scores=scores.tolist(),pair01_scores=pair.tolist(),
        folds=folds,metrics=metrics(y,predictions)),models


def report(s):
    a,b=(s["results"][name]["metrics"] for name in (T0,T1)); checks=s["adoption_checks"]
    adopted=all(checks.values()); c=s["changes"]
    lines=["# SVM-FS3-V0: P1 가중치1.5 단일 T0/T1 비교", "",
        "실험 ID: `EXPLR-SVM-FS3-V0-T1-P1W15-20261108`. 사용자 지정의 단일 학습 설정 가설이다. "
        "최근 적격120구간의 개발 탐색 결과이며 공식 선정·독립 검증·새 참가자 일반화 결과가 아니다.", "",
        "## 연구 질문과 사전 고정", "",
        "7특징 SVM-RBF에서 정상 자세 인식 성능을 크게 희생하지 않으면서 거북목 미탐률을 낮출 수 있는가?", "",
        "FS3=F1,F3,F4,F5,F6,F7,F8. 방법 V0=SVM-RBF, C=1,gamma=1/9 및 기존 생성기의 "
        "모든 나머지 설정을 유지했다. T0는class_weight=None, T1만 "
        "`class_weight={0:1.0,1:1.5,2:1.0,3:1.0,4:1.0,5:1.0}`이다. "
        "P1은 label_id=1인forward_head다. 평균1로 가중치를 정규화하거나 balanced 모드를 사용하지 않았다. "
        "SVM의 sample별 C×class_weight는 P1=1.5, 나머지=1.0이다. 학습 설정 변경이며 알고리즘 구조 개량이 아니다.", "",
        "같은120개 identity/라벨/H9 집계/적격 기준과 참가자LOSO 각 train60/test60을 유지했다. "
        "참가자별·자세별 학습support는10개, 전체 평가support는각20개다. P01 두 날짜는 같은fold다. "
        "기존24구간·중단 실행·기술적 실패7개는 추가하지 않았다. 기존 train-only StandardScaler를 그대로 재사용했다.", "",
        "기존 T0 모델2개를 hash 확인 후 복원해120개 예측을 재현했다. T0 fit=0회, "
        "T1 fit=2fold의2회뿐이다. seed0을 유지했고 다른가중치/C/gamma/특징/임계값은시험하지 않았다. "
        "후보fit 전에 PLAN.json에설정·입력hash·채택기준을저장했다.", "",
        "채택기준은 P1 Recall≥80%,P0 Recall≥95%,P2~P5 Recall100% 유지, "
        "Accuracy와Macro-F1이저장된T0 원값이상이며 모두충족해야한다. 비교허용오차1e-12는수치반올림용이다. "
        "조건미달이면T0 유지로사전에정했다.", "",
        "## 전체 지표", "", "|조건|정답/120|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|Weighted-F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["results"].items():
        m=r["metrics"]
        lines.append(f"|{name}|{m['correct']}/120|"+"|".join(f"{m[k]:.2f}" for k in
            ("accuracy","macro_f1","macro_precision","macro_recall","weighted_f1"))+"|")
    lines += ["", "## 자세별 지표", "", "|자세|support|T0 Precision %|T0 Recall %|T0 F1 %|T1 Precision %|T1 Recall %|T1 F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i in range(6):
        aa,bb=a["per_class"][i],b["per_class"][i]
        lines.append(f"|P{i} {aa['label']}|20|"+"|".join(f"{r[k]:.2f}" for r in (aa,bb) for k in ("precision","recall","f1"))+"|")
    lines += ["", f"ΔAccuracy {b['accuracy']-a['accuracy']:+.2f}pp, ΔMacro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp. "
        f"P1 미탐률은{100-a['per_class'][1]['recall']:.2f}%→{100-b['per_class'][1]['recall']:.2f}%다.", "",
        "## 오류 변화", "",
        f"오답→정답{c['wrong_to_correct']}개,정답→오답{c['correct_to_wrong']}개, "
        f"오답→다른오답{c['wrong_to_wrong']}개,전체예측변경{c['changed']}개.", "",
        "|실제→예측|T0|T1|", "|---|---:|---:|"]
    fa,fb=(flows(s["labels"],s["results"][n]["predictions"]) for n in (T0,T1))
    for f in sorted(set(fa)|set(fb)): lines.append(f"|{f}|{fa.get(f,0)}|{fb.get(f,0)}|")
    for name,r in s["results"].items():
        lines += ["",f"### {name} 혼동행렬", "", "행=실제P0~P5,열=예측P0~P5,건수다.", "", "```text",
            *[" ".join(map(str,row)) for row in r["metrics"]["confusion_matrix"]],"```"]
    descriptions=dict(p1_recall_at_least_80="P1 Recall≥80%",p0_recall_at_least_95="P0 Recall≥95%",
        p2_p3_p4_p5_recall_100="P2~P5 Recall100%",accuracy_at_least_t0="Accuracy≥T0",macro_f1_at_least_t0="Macro-F1≥T0")
    lines += ["", "## 사전 채택 조건 판정", "", "|조건|판정|", "|---|---|"]
    for key,passed in checks.items(): lines.append(f"|{descriptions[key]}|{'PASS' if passed else 'FAIL'}|")
    lines += ["",f"**결정: {'T1을 개발 후보로 채택' if adopted else 'T1 미채택, T0 유지'}.** "
        "이는이번개발실험의사전조건판정이며 공식모델선정규칙을바꾸지않는다.", "",
        "## 검증·보존·한계", "",
        "동일120개/7열/라벨/fold·T0재현·train-only scaler 불변·class_weight만변경·실제적용가중치·"
        "수렴·OOF1회·모델복원·점수/이웃없는전체6-class지표·CSV/MD·원본hash를확인했다. "
        "OVR/OVO 점수는비확률진단자료이며 채택지표는model.predict 결과로계산했다.", "",
        "실행코드compare_svm_fs3_t1_p1_weight.py와이요약을추가했다. 참가자별OOF/점수/가중치/모델/계획은 "
        "local_private/에만보관한다. T1의실행비용은이번에새로측정하지않았으며 T0의기존비용을T1비용으로전용하지않았다.", "",
        "현재자료를반복탐색한뒤사전고정한후속가설이다. 독립검증/유의성/일반화성능으로주장하지않는다. "
        "다른후보가중치·특징추가·새촬영·원본영상열람·전체회귀·실시간모델변경은없다. "
        "공식8조합/B6/IRB HOLD/Patch8보류를유지했고Commit/Push는하지않았다.", "",
        "실행: `python -X utf8 -B compare_svm_fs3_t1_p1_weight.py`; 저장검증은 `--verify`(학습없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); s=read(OUT/"local_private/results.json"); source,x,y,baseline,_=load_baseline()
    for key in ("labels","subjects","sample_keys"): assert s[key]==source[key]
    assert s["features"]==FEATURES and s["results"][T0]==baseline
    assert s["new_fits"]==2 and s["weights"]=={str(k):v for k,v in WEIGHTS.items()}
    for name,r in s["results"].items(): assert metrics(y,r["predictions"])==r["metrics"]
    r=s["results"][T1]; seen=np.zeros(120,dtype=int)
    for number,f in enumerate(r["folds"]):
        tr,te=f["train"],f["test"]; before=baseline["folds"][number]
        assert tr==before["train"] and te==before["test"] and len(tr)==len(te)==60 and set(tr).isdisjoint(te)
        assert set(s["subjects"][i] for i in tr).isdisjoint(s["subjects"][i] for i in te)
        np.testing.assert_allclose(f["mean"],x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(f["scale"],x[tr].std(0),rtol=0,atol=1e-14)
        assert f["mean"]==before["mean"] and f["scale"]==before["scale"] and f["fit_status"]==0
        path=ROOT/f["model_path"]; assert digest(path)==f["model_sha256"]
        with path.open("rb") as stream: model,scaler=pickle.load(stream)
        expected=factory("SVM-RBF",0).get_params(); expected["class_weight"]=WEIGHTS
        assert model.get_params()==expected
        np.testing.assert_array_equal(model.class_weight_,[1,1.5,1,1,1,1])
        test=scaler.transform(x[te]); np.testing.assert_array_equal(model.predict(test),np.array(r["predictions"])[te])
        np.testing.assert_allclose(model.decision_function(test),np.array(r["scores"])[te],rtol=0,atol=1e-14)
        np.testing.assert_allclose(model._decision_function(test)[:,0],np.array(r["pair01_scores"])[te],rtol=0,atol=1e-14)
        seen[te]+=1
    assert seen.tolist()==[1]*120
    assert criteria(r["metrics"],baseline["metrics"])==s["adoption_checks"]
    assert s["selected"]==(T1 if all(s["adoption_checks"].values()) else T0)
    assert changes(y,baseline["predictions"],r["predictions"])==s["changes"]
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==240
    for row in rows:
        i=int(row["index"]); assert int(row["actual"])==y[i] and int(row["predicted"])==s["results"][row["condition"]]["predictions"][i]
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: fixed120/FS3/LOSO/scalers, exact T0 replay, only raw P1 weight1.5 changed, models/OOF/criteria/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing outputs preserved; use --verify")
    verify_bundle(); source,x,y,baseline,models=load_baseline()
    paths=[SOURCE,BASE/"local_private/results.json",FEATURE_RESULTS/"local_private/results.json",BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",
        FACTORY,ROOT/"compare_six_feature_svm_knn.py",ROOT/"compare_lr_f2_f5.py",ROOT/"evaluate_new_pilot_lr6.py",Path(__file__).resolve()]
    paths += [ROOT/f["model_path"] for f in baseline["folds"]]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_SINGLE_T0_T1_COMPARISON",question="reduce P1 misses without major P0 loss",
        conditions={T0:factory("SVM-RBF",0).get_params(),T1:factory("SVM-RBF",0).set_params(class_weight=WEIGHTS).get_params()},
        features=FEATURES,columns=list(COLUMNS),input_hashes=inputs,new_fits=2,baseline_fits=0,
        normalized_weights=False,adoption=dict(p1_recall_min=80,p0_recall_min=95,p2_p3_p4_p5_recall=100,
            accuracy_min=baseline["metrics"]["accuracy"],macro_f1_min=baseline["metrics"]["macro_f1"],all_required=True),
        failure_action="retain T0; no additional weights or settings tried"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    pred=np.full(120,-1,dtype=int); scores=np.zeros((120,6)); pair=np.zeros(120); folds=[]
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        for number,(_,scaler,tr,te) in enumerate(models):
            model=factory("SVM-RBF",0).set_params(class_weight=WEIGHTS)
            expected=dict(baseline["folds"][number]["params"]); expected["class_weight"]=WEIGHTS
            assert model.get_params()==expected and np.bincount(y[tr],minlength=6).tolist()==[10]*6
            model.fit(scaler.transform(x[tr]),y[tr]); assert model.fit_status_==0
            np.testing.assert_array_equal(model.class_weight_,[1,1.5,1,1,1,1])
            test=scaler.transform(x[te]); pred[te]=model.predict(test); scores[te]=model.decision_function(test); pair[te]=model._decision_function(test)[:,0]
            path=private/f"T1_fold{number}.pkl"
            with path.open("xb") as stream: pickle.dump((model,scaler),stream,protocol=5)
            folds.append(dict(number=number,train=tr,test=te,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                applied_class_weights=model.class_weight_.tolist(),model_path=str(path.relative_to(ROOT)),model_sha256=digest(path),
                n_support=model.n_support_.tolist(),fit_status=int(model.fit_status_)))
    candidate=dict(predictions=pred.tolist(),scores=scores.tolist(),pair01_scores=pair.tolist(),folds=folds,metrics=metrics(y,pred))
    checks=criteria(candidate["metrics"],baseline["metrics"])
    saved=dict(inputs=inputs,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],features=FEATURES,
        weights=WEIGHTS,new_fits=2,results={T0:baseline,T1:candidate},adoption_checks=checks,selected=T1 if all(checks.values()) else T0,
        changes=changes(y,baseline["predictions"],pred.tolist()),warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in caught)),
        numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["condition","index","actual","predicted"]); writer.writeheader()
        for name,r in saved["results"].items(): writer.writerows(dict(condition=name,index=i,actual=int(y[i]),predicted=p) for i,p in enumerate(r["predictions"]))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify(); print(candidate["metrics"]); print(saved["changes"]); print(checks,"selected",saved["selected"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
