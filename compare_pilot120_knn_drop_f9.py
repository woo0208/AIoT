"""One distance-redundancy hypothesis: fixed KNN9 versus KNN without F9.

python -X utf8 -B compare_pilot120_knn_drop_f9.py [--verify]
Same reviewed120/H9 support/LOSO/scaler settings, k=3; only F9 is removed.
"""
import argparse
import csv
from pathlib import Path
import pickle

from review_lr_features import ROOT, read, digest
from bundle_pilot120 import SOURCE, OUT as BUNDLE, verify as verify_bundle
from compare_pilot120_linear_knn import OUT as PRIOR
from compare_six_feature_svm_knn import factory
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from evaluate_new_pilot_lr6 import metrics,write

import numpy as np
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT=ROOT/"analysis/PILOT120_KNN_DROP_F9_20261108"
COLUMNS=tuple(range(8))


def report(s):
    lines=["# KNN 거리 중복 단일 가설: F9만 제거", "",
        "실험 ID: `EXPLR-PILOT120-KNN-DROP-F9-20261108`. 같은2명 반복 탐색자료의 사후 가설 실험이다. "
        "공식 선정·독립검증·유의성·일반화 성능 향상으로 주장하지 않는다.", "",
        "## 사전 근거와 가설", "",
        "F8=흉부ROI깊이−코깊이(m), F9=F8/3D어깨너비다. "
        f"현재120개에서두특징의Pearson r={s['correlation_all']:.4f}, P0/P1 40개에서는r={s['correlation_p0p1']:.4f}다. "
        "기존KNN 남은9개오류의가장가까운정답/다른라벨거리대조에서F9의오답지지항이가장컸다. "
        "이는거리중복검토의근거이며 F9의인과적악영향/제거효과를입증하지않는다.", "",
        "가설: 표준화거리에서연관된F8/F9의동시반영을줄이려고F9만제외하면P0/P1오류가줄어드는가? "
        "고정KNN9(F1~F9)와KNN8(F1~F8)만비교한다. 여기의8특징은이전6특징에F9를뺀것이아니며 "
        "F2/F5는유지한다. 다른열·k·가중치·거리정규화는변경하지않았다.", "",
        "## 고정 평가", "",
        "동일120구간/identity/라벨/H9공동지원/적격기준/집계를유지했다. 참가자당60개,자세당20개, "
        "LOSO각train60/test60, P01두날짜는같은fold다. "
        "StandardScaler는train에서만fit했고기존9특징scaler의첫8열과같았다. "
        "기존factory KNN(k=3,uniform,brute,Minkowski p=2,n_jobs=1)을재사용했다. "
        "기준KNN9는5seed 예측이같아저장된seed0 OOF를재사용했다. KNN은난수인수가없으며 "
        "새모델fit은후보2fold뿐이다. 후보fit전에PLAN.json을저장했다. 조합/하이퍼파라미터탐색은없다.", "",
        "## 정량 결과", "",
        "|조건|정답/120|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|P0 Recall %|P1 Recall %|P2 Recall %|P3 Recall %|P4 Recall %|P5 Recall %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["results"].items():
        m=r["metrics"]
        vals=[m["accuracy"],m["macro_f1"],m["macro_precision"],m["macro_recall"],*[a["recall"] for a in m["per_class"]]]
        lines.append(f"|{name}|{m['correct']}/120|"+"|".join(f"{v:.2f}" for v in vals)+"|")
    a,b=(s["results"][n]["metrics"] for n in ("KNN9","KNN8_DROP_F9")); c=s["changes"]
    lines += ["",f"ΔAccuracy {b['accuracy']-a['accuracy']:+.2f}pp, ΔMacro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp. "
        f"오답→정답{c['wrong_to_correct']}건,정답→오답{c['correct_to_wrong']}건,오답→다른오답{c['wrong_to_wrong']}건.", "",
        "## 오류 유형", "", "|실제→예측|기준KNN9|F9제외KNN8|", "|---|---:|---:|"]
    fa,fb=(flows(s["labels"],s["results"][n]["predictions"]) for n in ("KNN9","KNN8_DROP_F9"))
    for f in sorted(set(fa)|set(fb)): lines.append(f"|{f}|{fa.get(f,0)}|{fb.get(f,0)}|")
    for name,r in s["results"].items():
        lines += ["",f"### {name} 혼동행렬", "", "행=실제P0~P5,열=예측P0~P5,건수다.", "", "```text",
                  *[" ".join(map(str,row)) for row in r["metrics"]["confusion_matrix"]],"```"]
    lines += ["", "## 해석과 검증", "",
        "이실험은이미확인한오류에서정한하나의사후가설이다. 현재자료의관측차이를근거로새참가자에서의우세를 "
        "보장하거나추가조합을자동탐색하지않는다. 개선이없으면기준KNN9를유지하는판단근거로남긴다.", "",
        "120개identity/기존입력hash·제거열/고정params·참가자분리/train-only scaler·OOF1회·"
        "메모리상직렬화복원·이웃거리/표결·지표/CSV/MD를검증했다. 전체회귀·새촬영·원본영상열람은없다. "
        "코드compare_pilot120_knn_drop_f9.py와이요약을추가하고참가자별OOF/거리/이웃/계획은local_private/에만 "
        "저장했다. 기존원본/모델/공식8조합/B6/IRB HOLD/Patch8보류를유지했고Commit/Push는하지않았다.", "",
        "실행: `python -X utf8 -B compare_pilot120_knn_drop_f9.py`; 저장검증은 `--verify`(학습없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); s=read(OUT/"local_private/results.json"); source=read(SOURCE); prior=read(PRIOR/"local_private/results.json")
    for key in ("labels","subjects","sample_keys"): assert s[key]==source[key]==prior[key]
    x=np.array(source["matrix"])[:,COLUMNS]; y=np.array(s["labels"])
    assert s["results"]["KNN9"]["predictions"]==prior["predictions"]["KNN"][0]
    for r in s["results"].values(): assert r["metrics"]==metrics(y,r["predictions"])
    seen=np.zeros(120,dtype=int)
    for f in s["folds"]:
        tr,te=np.array(f["train"]),np.array(f["test"])
        reference=source["results"]["LR9"]["folds"][f["number"]]
        assert tr.tolist()==reference["train"] and te.tolist()==reference["test"]
        assert len(tr)==len(te)==60 and set(tr).isdisjoint(te)
        np.testing.assert_allclose(f["mean"],x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(f["scale"],x[tr].std(0),rtol=0,atol=1e-14)
        assert f["params"]==factory("KNN",0).get_params()
        z=(x-np.array(f["mean"]))/np.array(f["scale"])
        d2=((z[te,None,:]-z[None,tr,:])**2).sum(2)
        for q,i in enumerate(te):
            order=np.argsort(d2[q],kind="stable"); nn=tr[order[:3]]
            assert d2[q,order[3]]>d2[q,order[2]]
            assert nn.tolist()==f["neighbors"][q]
            np.testing.assert_allclose(np.sqrt(d2[q,order[:3]]),f["distances"][q],rtol=0,atol=1e-12)
            assert np.bincount(y[nn],minlength=6).argmax()==s["results"]["KNN8_DROP_F9"]["predictions"][i]
            assert all(s["subjects"][j]!=s["subjects"][i] for j in nn)
        seen[te]+=1
    assert seen.tolist()==[1]*120
    assert s["changes"]==changes(y,s["results"]["KNN9"]["predictions"],s["results"]["KNN8_DROP_F9"]["predictions"])
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==240
    for r in rows:
        i=int(r["index"]); assert int(r["actual"])==y[i] and int(r["predicted"])==s["results"][r["model"]]["predictions"][i]
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: identical120/LOSO/params, only F9 removed, train-only scalers, exact neighbors/votes, metrics/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing outputs preserved; use --verify")
    verify_bundle(); source=read(SOURCE); prior=read(PRIOR/"local_private/results.json")
    for path,sha in prior["inputs"].items(): assert digest(ROOT/path)==sha
    assert all(p==prior["predictions"]["KNN"][0] for p in prior["predictions"]["KNN"])
    paths=[SOURCE,PRIOR/"local_private/results.json",PRIOR/"local_private/knn_diagnosis.json",
        BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",ROOT/"compare_six_feature_svm_knn.py",ROOT/"lr_posture_demo.py",
        ROOT/"compare_lr_f2_f5.py",ROOT/"evaluate_new_pilot_lr6.py",Path(__file__).resolve()]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    full=np.array(source["matrix"]); y=np.array(source["labels"]); x=full[:,COLUMNS]
    corr_all=float(np.corrcoef(full[:,7],full[:,8])[0,1]); corr_pair=float(np.corrcoef(full[y<2,7],full[y<2,8])[0,1])
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_SINGLE_POSTHOC_HYPOTHESIS",columns=list(COLUMNS),
        hypothesis="remove F9 only to reduce duplicated standardized depth distance; inspect corrected AND new errors",
        correlation_all=corr_all,correlation_p0p1=corr_pair,params=factory("KNN",0).get_params(),new_fits=2,input_hashes=inputs))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    pred=np.full(120,-1,dtype=int); folds=[]
    with threadpool_limits(limits=1):
        for number,f in enumerate(source["results"]["LR9"]["folds"]):
            tr,te=f["train"],f["test"]; scaler=StandardScaler().fit(x[tr]); model=factory("KNN",0)
            before=next(r for r in prior["folds"] if r["model"]=="KNN" and r["seed"]==0 and r["number"]==number)
            np.testing.assert_array_equal(scaler.mean_,np.array(before["mean"])[:8])
            np.testing.assert_array_equal(scaler.scale_,np.array(before["scale"])[:8])
            model.fit(scaler.transform(x[tr]),y[tr]); test=scaler.transform(x[te]); pred[te]=model.predict(test)
            restored=pickle.loads(pickle.dumps(model,protocol=5)); np.testing.assert_array_equal(restored.predict(test),pred[te])
            distances,neighbors=model.kneighbors(test)
            folds.append(dict(number=number,train=tr,test=te,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                params=model.get_params(),distances=distances.tolist(),neighbors=np.array(tr)[neighbors].tolist()))
    results=dict(KNN9=dict(predictions=prior["predictions"]["KNN"][0],metrics=metrics(y,prior["predictions"]["KNN"][0])),
        KNN8_DROP_F9=dict(predictions=pred.tolist(),metrics=metrics(y,pred)))
    saved=dict(inputs=inputs,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
        results=results,folds=folds,correlation_all=corr_all,correlation_p0p1=corr_pair,
        changes=changes(y,results["KNN9"]["predictions"],pred.tolist()))
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["model","index","actual","predicted"]); writer.writeheader()
        for name,r in results.items(): writer.writerows(dict(model=name,index=i,actual=int(y[i]),predicted=p) for i,p in enumerate(r["predictions"]))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify(); print(results["KNN8_DROP_F9"]["metrics"]); print(saved["changes"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
