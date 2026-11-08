"""One fixed T0/T2 comparison: change only gamma from 1/9 to 1/7.

python -X utf8 -B compare_svm_fs3_t2_gamma.py [--verify]
Reuse T0/scalers; two T2 fits only. No further settings are tried.
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
from compare_svm_fs3_t1_p1_weight import load_baseline,criteria,T0
from compare_six_feature_svm_knn import factory
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from evaluate_new_pilot_lr6 import metrics,write
from lr_posture_demo import FACTORY

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

OUT=ROOT/"analysis/SVM_FS3_V0_T2_GAMMA_1_7_20261108"
T2="SVM-FS3-V0-T2"
GAMMA=1/7


def report(s):
    a,b=(s["results"][name]["metrics"] for name in (T0,T2)); c=s["changes"]
    lines=["# SVM-FS3-V0: gamma 1/7 단일 T0/T2 비교", "",
        "실험 ID: `EXPLR-SVM-FS3-V0-T2-GAMMA1OVER7-20261108`. 사용자가 지정한 사전 고정 단일 가설이다. "
        "현재120구간 개발 탐색 결과이며 공식 선정·독립 검증·새 참가자 일반화 성능이 아니다.", "",
        "## 사전 기록과 고정 조건", "",
        "T0에서 gamma만1/9→1/7로 바꾼다. 현재7차원에 대한 차원 기반 설정을 검토하며 "
        "1/7이 최적이거나 성능 향상이 보장된 값이라고 가정하지 않는다. "
        "T1의P1 가중치1.5를 이어받지 않았다. 두 조건 모두 C=1,class_weight=None, "
        "기존 SVM-RBF 생성기의 나머지 설정과 seed0을 유지했다. 숫자1/7을 직접 지정했고 "
        "gamma='scale'이나 다른 후보값을 사용하지 않았다.", "",
        "FS3=F1,F3,F4,F5,F6,F7,F8, 최근 적격120구간(기존113+P01 P5 보완7), "
        "동일 identity/라벨/H9 support/집계/적격 기준이다. 각 자세20개, 참가자LOSO2fold는train60/test60, "
        "각 학습클래스10개다. P01 두 날짜 세션은같은fold다. 처음24개·실패7개·중단 실행은추가하지않았다.", "",
        "기존T0 두모델을hash 확인후복원해기존OOF120개를정확히재현했다. "
        "train-only StandardScaler를그대로재사용해전처리까지고정했다. "
        "후보fit 전에PLAN.json으로gamma·전체params·입력hash·채택기준·미달시T0유지및추가탐색없음을기록했다. "
        "T0 fit0회,T2 fit2fold의2회로한번만비교했다.", "",
        "채택은P1 Recall≥80%,P0 Recall≥95%,P2~P5 Recall100%,Accuracy/Macro-F1이T0 원값이상인 "
        "조건을모두만족해야한다. 반올림전값을비교하고수치허용오차는1e-12다.", "",
        "## 전체 지표", "",
        "|조건|정답/120|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|Weighted-F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["results"].items():
        m=r["metrics"]
        lines.append(f"|{name}|{m['correct']}/120|"+"|".join(f"{m[k]:.2f}" for k in
            ("accuracy","macro_f1","macro_precision","macro_recall","weighted_f1"))+"|")
    lines += ["", "## 자세별 지표", "",
        "|자세|support|T0 Precision %|T0 Recall %|T0 F1 %|T2 Precision %|T2 Recall %|T2 F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i in range(6):
        aa,bb=a["per_class"][i],b["per_class"][i]
        lines.append(f"|P{i} {aa['label']}|20|"+"|".join(f"{r[k]:.2f}" for r in (aa,bb) for k in ("precision","recall","f1"))+"|")
    lines += ["",f"ΔAccuracy {b['accuracy']-a['accuracy']:+.2f}pp, ΔMacro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp. "
        f"P1 미탐률은{100-a['per_class'][1]['recall']:.2f}%→{100-b['per_class'][1]['recall']:.2f}%다.", "",
        "## 오류 변화", "",
        f"오답→정답{c['wrong_to_correct']}개,정답→오답{c['correct_to_wrong']}개, "
        f"오답→다른오답{c['wrong_to_wrong']}개,전체변경{c['changed']}개.", "",
        "|실제→예측|T0|T2|", "|---|---:|---:|"]
    fa,fb=(flows(s["labels"],s["results"][n]["predictions"]) for n in (T0,T2))
    for f in sorted(set(fa)|set(fb)): lines.append(f"|{f}|{fa.get(f,0)}|{fb.get(f,0)}|")
    for name,r in s["results"].items():
        lines += ["",f"### {name} 혼동행렬", "", "행=실제P0~P5,열=예측P0~P5,건수다.", "", "```text",
            *[" ".join(map(str,row)) for row in r["metrics"]["confusion_matrix"]],"```"]
    names=dict(p1_recall_at_least_80="P1 Recall≥80%",p0_recall_at_least_95="P0 Recall≥95%",
        p2_p3_p4_p5_recall_100="P2~P5 Recall100%",accuracy_at_least_t0="Accuracy≥T0",macro_f1_at_least_t0="Macro-F1≥T0")
    lines += ["", "## 사전 채택 조건 판정", "", "|조건|판정|", "|---|---|"]
    for key,passed in s["adoption_checks"].items(): lines.append(f"|{names[key]}|{'PASS' if passed else 'FAIL'}|")
    lines += ["",f"**결정: {'T2를 개발 후보로 채택' if all(s['adoption_checks'].values()) else 'T2 미채택, T0 유지'}.**", "",
        "## 검증·보존·한계", "",
        "동일120개/7열/라벨/fold·T0재현·train-only scaler 불변·gamma만변경·실제적용gamma/C/가중치·"
        "수렴·OOF1회·모델복원·지표/CSV/MD·사전계획/원본hash를확인했다. "
        "OVR/OVO 점수는비확률진단자료로만저장하고채택지표는model.predict 결과로계산했다.", "",
        "추가코드는compare_svm_fs3_t2_gamma.py, 공개요약은이보고서다. "
        "참가자별OOF/점수/모델/스케일러/계획은local_private/에만보관한다. "
        "T2 실행비용은새로측정하지않았으며T0 비용을T2 비용으로표기하지않았다.", "",
        "현재120구간은이미특징/모델선정에반복사용한개발자료다. "
        "결과에맞춘조건완화·다른gamma/C/가중치·추가조합·새특징·촬영·원본영상열람·전체회귀는없다. "
        "실시간모델/공식8조합/B6/IRB HOLD/Patch8보류는유지하고Commit/Push는하지않았다.", "",
        "실행: `python -X utf8 -B compare_svm_fs3_t2_gamma.py`; 저장검증은 `--verify`(학습없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); s=read(OUT/"local_private/results.json"); source,x,y,baseline,_=load_baseline()
    for key in ("labels","subjects","sample_keys"): assert s[key]==source[key]
    assert s["features"]==FEATURES and s["results"][T0]==baseline and s["new_fits"]==2 and s["gamma"]==GAMMA
    for r in s["results"].values(): assert r["metrics"]==metrics(y,r["predictions"])
    r=s["results"][T2]; seen=np.zeros(120,dtype=int)
    for number,f in enumerate(r["folds"]):
        tr,te=f["train"],f["test"]; before=baseline["folds"][number]
        assert tr==before["train"] and te==before["test"] and len(tr)==len(te)==60 and set(tr).isdisjoint(te)
        assert set(s["subjects"][i] for i in tr).isdisjoint(s["subjects"][i] for i in te)
        assert f["mean"]==before["mean"] and f["scale"]==before["scale"] and f["fit_status"]==0
        path=ROOT/f["model_path"]; assert digest(path)==f["model_sha256"]
        with path.open("rb") as stream: model,scaler=pickle.load(stream)
        expected=factory("SVM-RBF",0).get_params(); expected["gamma"]=GAMMA
        assert model.get_params()==expected and model._gamma==GAMMA and model.class_weight is None
        np.testing.assert_array_equal(model.class_weight_,np.ones(6))
        np.testing.assert_allclose(scaler.mean_,x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(scaler.scale_,x[tr].std(0),rtol=0,atol=1e-14)
        assert scaler.n_samples_seen_==60
        test=scaler.transform(x[te]); np.testing.assert_array_equal(model.predict(test),np.array(r["predictions"])[te])
        np.testing.assert_allclose(model.decision_function(test),np.array(r["scores"])[te],rtol=0,atol=1e-14)
        np.testing.assert_allclose(model._decision_function(test)[:,0],np.array(r["pair01_scores"])[te],rtol=0,atol=1e-14)
        seen[te]+=1
    assert seen.tolist()==[1]*120
    assert s["adoption_checks"]==criteria(r["metrics"],baseline["metrics"])
    assert s["selected"]==(T2 if all(s["adoption_checks"].values()) else T0)
    assert s["changes"]==changes(y,baseline["predictions"],r["predictions"])
    plan=read(OUT/"local_private/PLAN.json")
    expected=factory("SVM-RBF",0).get_params(); expected["gamma"]=GAMMA
    assert plan["conditions"][T2]==expected and plan["new_fits"]==2 and plan["all_criteria_required"] is True
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==240
    for row in rows:
        i=int(row["index"]); assert int(row["actual"])==y[i] and int(row["predicted"])==s["results"][row["condition"]]["predictions"][i]
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: same120/FS3/LOSO/scalers/T0, gamma alone1/9-to-1/7, models/OOF/criteria/CSV/report/plan hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing output preserved; use --verify")
    verify_bundle(); source,x,y,baseline,models=load_baseline()
    paths=[SOURCE,BASE/"local_private/results.json",BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",FACTORY,
        ROOT/"compare_svm_fs3_t1_p1_weight.py",ROOT/"compare_six_feature_svm_knn.py",ROOT/"review_pilot120_seven_candidates.py",
        ROOT/"compare_lr_f2_f5.py",ROOT/"evaluate_new_pilot_lr6.py",Path(__file__).resolve()]
    paths += [ROOT/f["model_path"] for f in baseline["folds"]]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    params=factory("SVM-RBF",0).get_params(); params["gamma"]=GAMMA
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_SINGLE_T0_T2_COMPARISON",features=FEATURES,columns=list(COLUMNS),
        conditions={T0:factory("SVM-RBF",0).get_params(),T2:params},new_fits=2,baseline_fits=0,input_hashes=inputs,
        adoption=dict(p1_recall_min=80,p0_recall_min=95,p2_p3_p4_p5_recall=100,
            accuracy_min=baseline["metrics"]["accuracy"],macro_f1_min=baseline["metrics"]["macro_f1"]),
        all_criteria_required=True,failure_action="retain T0; no automatic further settings"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    pred=np.full(120,-1,dtype=int); scores=np.zeros((120,6)); pair=np.zeros(120); folds=[]
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        for number,(_,scaler,tr,te) in enumerate(models):
            model=factory("SVM-RBF",0).set_params(gamma=GAMMA)
            assert model.get_params()==params and np.bincount(y[tr],minlength=6).tolist()==[10]*6
            model.fit(scaler.transform(x[tr]),y[tr]); assert model.fit_status_==0 and model._gamma==GAMMA
            np.testing.assert_array_equal(model.class_weight_,np.ones(6))
            test=scaler.transform(x[te]); pred[te]=model.predict(test); scores[te]=model.decision_function(test); pair[te]=model._decision_function(test)[:,0]
            path=private/f"T2_fold{number}.pkl"
            with path.open("xb") as stream: pickle.dump((model,scaler),stream,protocol=5)
            folds.append(dict(number=number,train=tr,test=te,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                applied_gamma=float(model._gamma),applied_class_weights=model.class_weight_.tolist(),model_path=str(path.relative_to(ROOT)),
                model_sha256=digest(path),n_support=model.n_support_.tolist(),fit_status=int(model.fit_status_)))
    candidate=dict(predictions=pred.tolist(),scores=scores.tolist(),pair01_scores=pair.tolist(),folds=folds,metrics=metrics(y,pred))
    checks=criteria(candidate["metrics"],baseline["metrics"])
    saved=dict(inputs=inputs,features=FEATURES,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
        gamma=GAMMA,new_fits=2,results={T0:baseline,T2:candidate},adoption_checks=checks,selected=T2 if all(checks.values()) else T0,
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
