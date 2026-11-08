"""One FS3/FS4 comparison: add the predesigned HP3D median to fixed SVM V0-T0.

python -X utf8 -B compare_svm_fs4_hp3d.py [--verify]
Preserve the original seven aggregates and120 identities; no setting search.
"""
import argparse
from collections import Counter,defaultdict
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT,read,digest
from bundle_pilot120 import SOURCE,OUT as BUNDLE,verify as verify_bundle
from review_pilot120_seven_candidates import OUT as BASE,FEATURES,COLUMNS
from compare_svm_fs3_t1_p1_weight import load_baseline,criteria,T0
from compare_six_feature_svm_knn import factory
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from evaluate_new_pilot_lr6 import metrics,write
from review_pilot_six_capture import csv_rows,present
from f1_sample_aggregator import H9_FEATURE_NAMES
from h6_offline import LAB6,load_labeled_probe_h_samples
from posture_geometry import Point3D,_exploratory_head_pitch_deg
from lr_posture_demo import FACTORY

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT=ROOT/"analysis/SVM_FS4_HP3D_20261108"
FS4="SVM-FS4-V0-T0"
FIELD="exploratory_head_pitch_deg"
FEATURES4=[*FEATURES,"HP3D"]
FORMULA_TOLERANCE_DEG=1e-9


def point(row,prefix):
    keys=[f"{prefix}_{axis}_m" for axis in ("x","y","z")]
    if not all(present(row,k) for k in keys): return None
    return Point3D(*(float(row[k]) for k in keys))


def extract_hp3d(source):
    paths=[ROOT/"captures"/recording/"features.csv" for recording in sorted({k[1] for k in source["sample_keys"]})]
    all_samples=load_labeled_probe_h_samples(paths)
    samples={s.sample_key:s for s in all_samples}; groups=defaultdict(list)
    assert len(all_samples)==127 and {s.sample_key for s in all_samples if s.eligible}=={tuple(k) for k in source["sample_keys"]}
    for path in paths:
        for index,row in enumerate(csv_rows(path),1): groups[(row["recording_id"],row["segment_id"])].append((index,row))
    old=read(BASE/"local_private/results.json")["diagnosis"]["auxiliary_values"]
    quality=[]; values=[]; maximum_difference=0.0
    for i,key in enumerate(source["sample_keys"]):
        sample=samples[tuple(key)]; rows=groups[(key[1],key[2])]
        assert sample.eligible and sample.subject==source["subjects"][i] and sample.label==LAB6[source["labels"][i]]
        np.testing.assert_array_equal(sample.ordered_values("H9"),source["matrix"][i])
        common=[(idx,row) for idx,row in rows if all(present(row,f) for f in H9_FEATURE_NAMES)]
        assert [idx for idx,_ in common]==list(sample.common_valid_frame_indices)
        assert len(rows)==sample.n_frames and len(common)==sample.common_valid_count
        valid=[]; valid_indices=[]
        for idx,row in common:
            e=point(row,"ear_midpoint_3d"); n=point(row,"nose_3d"); c=point(row,"chin_3d")
            calculated=_exploratory_head_pitch_deg(e,n,c)
            stored=float(row[FIELD]) if present(row,FIELD) else None
            assert (calculated is None)==(stored is None)
            if calculated is None: continue
            difference=abs(calculated-stored); assert difference<=FORMULA_TOLERANCE_DEG
            maximum_difference=max(maximum_difference,difference)
            valid.append(stored); valid_indices.append(idx)
        assert len(valid)>=30 and len(valid)/len(rows)>=.5, "Stop; no sample exclusion/imputation to retain120"
        value=float(np.median(valid)); values.append(value)
        before=old[i]
        assert before["sample_key"]==key and before["fields"][FIELD]["n"]==len(valid)
        assert before["fields"][FIELD]["median"]==value
        quality.append(dict(index=i,sample_key=key,original_frames=len(rows),h9_common_frames=len(common),
            hp3d_valid_frames=len(valid),input_coverage=len(valid)/len(rows),common_fraction=len(valid)/len(common),
            valid_frame_indices=valid_indices,median=value,eligible=True))
    return values,dict(samples=quality,maximum_formula_difference_deg=maximum_difference,
        h9_common_frames=sum(q["h9_common_frames"] for q in quality),hp3d_valid_frames=sum(q["hp3d_valid_frames"] for q in quality),
        minimum_valid_frames=min(q["hp3d_valid_frames"] for q in quality),
        minimum_input_coverage=min(q["input_coverage"] for q in quality)),paths


def report(s):
    a,b=(s["results"][n]["metrics"] for n in (T0,FS4)); q=s["quality"]; c=s["changes"]
    lines=["# FS4: 고정7특징 SVM에 HP3D 한 개 추가", "",
        "실험 ID: `EXPLR-SVM-FS4-HP3D-20261108`. 사용자 지정의 단일 특징 추가 가설이다. "
        "두 사람 반복 탐색자료의 현재120개를 사용하며 독립 검증·공식 선정 결과가 아니다.", "",
        "## 사전 고정 특징과 가설", "",
        "FS3=F1,F3,F4,F5,F6,F7,F8. FS4=FS3+HP3D의8차원이다. "
        "V0/T0 SVM-RBF의 C=1,gamma=1/9,class_weight=None 및 나머지 생성기 설정·seed0은 그대로다. "
        "이전 T1 가중치나T2 gamma 변경을 이어받지 않았다. 알고리즘 변경이 아닌 특징 분기 비교다.", "",
        "기존7열에서 전방 위치·투영비가 정상에 가깝던P1 오류가 보조3D 머리 pitch에서는 "
        "학습P1 중앙값 쪽에 더 가까웠다는 사후 관찰을 근거로, 명시적인 머리 회전각을 추가하면 "
        "P1→P0가 줄어드는지 검토한다. 이전 관찰은 성공 보장이나 독립 검증 근거가 아니다.", "",
        "```text", "E = midpoint(LeftEar, RightEar); N = Nose; C = Chin  # aligned D455 XYZ, metres",
        "u = (N_y-E_y, N_z-E_z) / norm((N_y-E_y, N_z-E_z))",
        "v = (C_y-E_y, C_z-E_z) / norm((C_y-E_y, C_z-E_z))",
        "HP3D_t = degrees(atan2(-(u_y+v_y), -(u_z+v_z)))",
        "HP3D = median(valid HP3D_t in original H9 common support)", "```", "",
        "기존 posture_geometry._exploratory_head_pitch_deg와 같은 정의이며 새 기하 수식의 발명은 아니다. "
        "MediaPipe Pose귀7/8·코0, Face턱152와 D455 metric depth를 사용한다. +Y는아래,+Z는카메라에서멀어짐, "
        "HP3D 양수는위로회전이다. 전방평행이동은상쇄되지만카메라pitch에불변이거나임상목각도인것은아니다.", "",
        "## 입력·지원 프레임 검증", "",
        "기존113개+P01 P5 보완7개=120개 identity/라벨을 그대로 유지했다. 원래127개 관측 중 "
        "기술적 부적격7개는 기존처럼 제외하고 실패원본은 보존했다. 기존24구간·중단실행은 합치지 않았다.", "",
        "기존7열은원래H9 공동지원 집계값과 bit-for-bit 같고 재집계하지 않았다. "
        "HP3D만그지원안에서필요XYZ가유효한프레임을사용한다. 기존 helper의finite XYZ/양의Z, "
        "ray norm>1e-6,합벡터norm>1e-6 조건을재사용했다. 결측채움·새센서임계값·후보선택은없다.", "",
        f"120개모두HP3D 유효≥30 및 원래입력대비coverage≥50%를통과했다. 최소유효{q['minimum_valid_frames']}프레임, "
        f"최소coverage{100*q['minimum_input_coverage']:.2f}%, 총H9공동{q['h9_common_frames']}프레임 중 "
        f"HP3D지원{q['hp3d_valid_frames']}프레임이다. 기존CSV에저장된값을XYZ/원래helper로재검산했고 "
        f"최대차이는{q['maximum_formula_difference_deg']:.3g}deg였다(사전허용오차1e-9deg). "
        "구간중앙값과유효수는이전보조값진단과정확히같았다.", "",
        "## 평가·채택 기준", "",
        "같은참가자LOSO2fold 각train60/test60,각클래스학습10개/전체평가20개다. "
        "P01두날짜는같은fold에둔다. 새8열StandardScaler는train에서만fit하고첫7열통계는기존T0와같음을확인했다. "
        "T0의두모델을복원해기존OOF를재현하고FS4만2회fit했다. 후보fit 전에PLAN.json에 "
        "수식·지원규칙·120개identity·입력hash·전체params·채택기준·추가탐색없음을기록했다.", "",
        "모든조건을동시에충족해야한다: P1 Recall≥80%,P0 Recall≥95%,P2~P5 각각Recall100%, "
        "Accuracy≥95.00%,Macro-F1≥T0의반올림전값. 미달이면FS3 T0를유지한다. "
        "판정은 반올림 전 값과 수치 허용오차1e-12를 사용한다.", "",
        "## 전체 결과", "",
        "|조건|정답/120|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|Weighted-F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["results"].items():
        m=r["metrics"]
        lines.append(f"|{name}|{m['correct']}/120|"+"|".join(f"{m[k]:.2f}" for k in
            ("accuracy","macro_f1","macro_precision","macro_recall","weighted_f1"))+"|")
    lines += ["", "## 자세별 결과", "",
        "|자세|support|FS3 Precision %|FS3 Recall %|FS3 F1 %|FS4 Precision %|FS4 Recall %|FS4 F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i in range(6):
        aa,bb=a["per_class"][i],b["per_class"][i]
        lines.append(f"|P{i} {aa['label']}|20|"+"|".join(f"{r[k]:.2f}" for r in (aa,bb) for k in ("precision","recall","f1"))+"|")
    lines += ["",f"ΔAccuracy {b['accuracy']-a['accuracy']:+.2f}pp,ΔMacro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp. "
        f"P1 미탐률{100-a['per_class'][1]['recall']:.2f}%→{100-b['per_class'][1]['recall']:.2f}%.", "",
        "## 오류 변화", "",
        f"오답→정답{c['wrong_to_correct']}개,정답→오답{c['correct_to_wrong']}개, "
        f"오답→다른오답{c['wrong_to_wrong']}개,전체예측변경{c['changed']}개.", "",
        "|실제→예측|FS3|FS4|", "|---|---:|---:|"]
    fa,fb=(flows(s["labels"],s["results"][n]["predictions"]) for n in (T0,FS4))
    for f in sorted(set(fa)|set(fb)): lines.append(f"|{f}|{fa.get(f,0)}|{fb.get(f,0)}|")
    for name,r in s["results"].items():
        lines += ["",f"### {name} 혼동행렬", "", "행=실제P0~P5,열=예측P0~P5,건수다.", "", "```text",
            *[" ".join(map(str,row)) for row in r["metrics"]["confusion_matrix"]],"```"]
    names=dict(p1_recall_at_least_80="P1 Recall≥80%",p0_recall_at_least_95="P0 Recall≥95%",
        p2_p3_p4_p5_recall_100="P2~P5 각각Recall100%",accuracy_at_least_t0="Accuracy≥95.00%",macro_f1_at_least_t0="Macro-F1≥T0 원값")
    lines += ["", "## 사전 채택 조건 판정", "", "|조건|판정|", "|---|---|"]
    for key,passed in s["adoption_checks"].items(): lines.append(f"|{names[key]}|{'PASS' if passed else 'FAIL'}|")
    lines += ["",f"**결정: {'FS4를개발후보로채택' if all(s['adoption_checks'].values()) else 'FS4 미채택, FS3 T0 유지'}.**", "",
        "## 검증·보존·한계", "",
        "동일120개·원래7열·H9frame identity·HP3D원식/지원/중앙값·train-only scaler·"
        "고정SVMparams/실제gamma/가중치·수렴·OOF1회·모델복원·지표/CSV/MD·사전계획/원본hash를확인했다. "
        "기존 raw RGB/Depth 영상을 열지 않고 저장된 CSV만 사용했다.", "",
        "새코드는compare_svm_fs4_hp3d.py,요약은이보고서다. 구간별HP3D/지원프레임/8열행렬/OOF/점수/"
        "모델/스케일러/계획은local_private/에만보관한다. 기존capture/geometry/공식schema/실시간모델은수정하지않았다. "
        "FS4 실행비용은이번에측정하지않았으며T0 비용을FS4 비용으로사용하지않았다.", "",
        "오류를보고정한후속가설이고동일120개를반복탐색했으므로독립검증/유의성/일반화근거가아니다. "
        "HP3D는앞으로목이동이아닌턱숙임·카메라각·이파일럿수행방식을학습할위험이있다. "
        "다른새특징/수식/집계/가중치/C/gamma를탐색하지않았다. 공식8조합/B6/IRB HOLD/Patch8보류를유지했고 "
        "새촬영·전체회귀·Commit/Push는없다.", "",
        "실행: `python -X utf8 -B compare_svm_fs4_hp3d.py`; 저장검증은 `--verify`(학습없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle(); s=read(OUT/"local_private/results.json"); source,x7,y,baseline,_=load_baseline()
    hp,quality,_=extract_hp3d(source); x=np.column_stack((x7,hp))
    assert s["features"]==FEATURES4 and s["quality"]==quality and s["matrix"]==x.tolist() and s["new_fits"]==2
    for key in ("labels","subjects","sample_keys"): assert s[key]==source[key]
    assert s["results"][T0]==baseline
    for r in s["results"].values(): assert r["metrics"]==metrics(y,r["predictions"])
    r=s["results"][FS4]; seen=np.zeros(120,dtype=int)
    for number,f in enumerate(r["folds"]):
        tr,te=f["train"],f["test"]; before=baseline["folds"][number]
        assert tr==before["train"] and te==before["test"] and set(tr).isdisjoint(te) and len(tr)==len(te)==60
        assert set(s["subjects"][i] for i in tr).isdisjoint(s["subjects"][i] for i in te)
        path=ROOT/f["model_path"]; assert digest(path)==f["model_sha256"]
        with path.open("rb") as stream: model,scaler=pickle.load(stream)
        assert model.get_params()==factory("SVM-RBF",0).get_params() and model._gamma==1/9 and model.n_features_in_==8
        assert scaler.n_samples_seen_==60 and model.fit_status_==0
        np.testing.assert_array_equal(model.class_weight_,np.ones(6))
        np.testing.assert_allclose(scaler.mean_,x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(scaler.scale_,x[tr].std(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(scaler.mean_[:7],before["mean"],rtol=0,atol=1e-14)
        np.testing.assert_allclose(scaler.scale_[:7],before["scale"],rtol=0,atol=1e-14)
        test=scaler.transform(x[te]); np.testing.assert_array_equal(model.predict(test),np.array(r["predictions"])[te])
        np.testing.assert_allclose(model.decision_function(test),np.array(r["scores"])[te],rtol=0,atol=1e-14)
        seen[te]+=1
    assert seen.tolist()==[1]*120
    assert criteria(r["metrics"],baseline["metrics"])==s["adoption_checks"]
    assert s["selected"]==(FS4 if all(s["adoption_checks"].values()) else T0)
    assert s["changes"]==changes(y,baseline["predictions"],r["predictions"])
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    with (OUT/"local_private/features.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==120
    np.testing.assert_array_equal([[float(row[f]) for f in FEATURES4] for row in rows],x)
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==240
    for row in rows:
        i=int(row["index"]); assert int(row["actual"])==y[i] and int(row["predicted"])==s["results"][row["condition"]]["predictions"][i]
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: exact120/original7/H9 support, HP3D formula/median/eligibility, fixedSVM/train-only8D scalers, OOF/criteria/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing output preserved; use --verify")
    verify_bundle(); source,x7,y,baseline,_=load_baseline(); hp,quality,raw_paths=extract_hp3d(source)
    assert baseline["metrics"]["accuracy"]==95.0
    x=np.column_stack((x7,hp)); assert x.shape==(120,8) and np.isfinite(x).all()
    np.testing.assert_array_equal(x[:,:7],x7)
    paths=[SOURCE,BASE/"local_private/results.json",BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",FACTORY,
        ROOT/"compare_svm_fs3_t1_p1_weight.py",ROOT/"review_pilot120_seven_candidates.py",ROOT/"review_pilot_six_capture.py",
        ROOT/"h6_offline.py",ROOT/"f1_sample_aggregator.py",ROOT/"posture_geometry.py",ROOT/"posture_geometry_probe.py",
        ROOT/"compare_six_feature_svm_knn.py",ROOT/"compare_lr_f2_f5.py",ROOT/"evaluate_new_pilot_lr6.py",Path(__file__).resolve(),*raw_paths]
    paths += [ROOT/f["model_path"] for f in baseline["folds"]]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_SINGLE_FS4_FEATURE_ADDITION",features=FEATURES4,baseline_features=FEATURES,
        definition="existing exploratory_head_pitch_deg; median on original H9 support intersect valid HP3D; original7 unchanged",
        validity="existing finite positive-Z XYZ; two YZ ray norms and sum norm >1e-6; >=30frames and input coverage>=0.5",
        formula_tolerance_deg=FORMULA_TOLERANCE_DEG,params=factory("SVM-RBF",0).get_params(),
        sample_keys=source["sample_keys"],quality=quality,input_hashes=inputs,new_fits=2,baseline_fits=0,
        adoption=dict(p1_recall_min=80,p0_recall_min=95,p2_p3_p4_p5_recall=100,accuracy_min=95.0,
            macro_f1_min=baseline["metrics"]["macro_f1"],all_required=True),failure_action="retain FS3 V0 T0; no automatic expansion"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    pred=np.full(120,-1,dtype=int); scores=np.zeros((120,6)); pair=np.zeros(120); folds=[]
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        for number,before in enumerate(baseline["folds"]):
            tr,te=before["train"],before["test"]; scaler=StandardScaler().fit(x[tr]); model=factory("SVM-RBF",0)
            np.testing.assert_allclose(scaler.mean_[:7],before["mean"],rtol=0,atol=1e-14)
            np.testing.assert_allclose(scaler.scale_[:7],before["scale"],rtol=0,atol=1e-14)
            model.fit(scaler.transform(x[tr]),y[tr]); assert model.fit_status_==0 and model._gamma==1/9
            test=scaler.transform(x[te]); pred[te]=model.predict(test); scores[te]=model.decision_function(test); pair[te]=model._decision_function(test)[:,0]
            path=private/f"FS4_fold{number}.pkl"
            with path.open("xb") as stream: pickle.dump((model,scaler),stream,protocol=5)
            folds.append(dict(number=number,train=tr,test=te,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                model_path=str(path.relative_to(ROOT)),model_sha256=digest(path),n_support=model.n_support_.tolist(),fit_status=int(model.fit_status_)))
    candidate=dict(predictions=pred.tolist(),scores=scores.tolist(),pair01_scores=pair.tolist(),folds=folds,metrics=metrics(y,pred))
    checks=criteria(candidate["metrics"],baseline["metrics"])
    saved=dict(inputs=inputs,features=FEATURES4,matrix=x.tolist(),quality=quality,labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
        new_fits=2,results={T0:baseline,FS4:candidate},adoption_checks=checks,selected=FS4 if all(checks.values()) else T0,
        changes=changes(y,baseline["predictions"],pred.tolist()),warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in caught)),
        numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"features.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["index","label",*FEATURES4]); writer.writeheader()
        writer.writerows(dict(index=i,label=int(y[i]),**dict(zip(FEATURES4,row.tolist()))) for i,row in enumerate(x))
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["condition","index","actual","predicted"]); writer.writeheader()
        for name,r in saved["results"].items(): writer.writerows(dict(condition=name,index=i,actual=int(y[i]),predicted=p) for i,p in enumerate(r["predictions"]))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify(); print(candidate["metrics"]); print(saved["changes"]); print(checks,"selected",saved["selected"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
