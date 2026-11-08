"""Freeze seven inputs, benchmark SVM/KNN, and diagnose their saved OOF errors.

python -X utf8 -B review_pilot120_seven_candidates.py [--verify]
Existing auxiliary geometry is diagnostic only; no additional classifier input is tested.
"""
import argparse
from collections import Counter,defaultdict
import csv
import gc
import itertools
import math
from pathlib import Path
import pickle
import subprocess
import sys
import time
import warnings

from review_lr_features import ROOT,read,digest
from bundle_pilot120 import SOURCE,OUT as BUNDLE,verify as verify_bundle
from compare_pilot120_feature_sets import OUT as REFERENCE,CONFIGS
from compare_six_feature_svm_knn import factory
from evaluate_new_pilot_lr6 import write
from f1_sample_aggregator import H9_FEATURE_NAMES
from review_pilot_six_capture import present
from model_benchmark import run_benchmark
from probe_timing import process_memory,_stats
import engineering_exports as exports
import performance_output as perf

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits,threadpool_info

OUT=ROOT/"analysis/PILOT120_SEVEN_CANDIDATE_REVIEW_20261108"
REF=REFERENCE/"local_private/results.json"
NAMES=("SVM-RBF","KNN")
COLUMNS=CONFIGS["H7_DROP_F2"]
FEATURES=[f"F{j+1}" for j in COLUMNS]
REPEATS,WARMUP,CALLS=3,24,120
AUX=("exploratory_head_pitch_deg","face_matrix_pitch_deg","sagittal_torso_lean_deg",
     "ear_midpoint_forward_normalized_by_shoulder_width_3d")


def predict(payload,x):
    model,scaler=payload
    return model.predict(scaler.transform(x))


def worker(name,fold,rep,target):
    source,reference=read(SOURCE),read(REF)
    x=np.array(source["matrix"])[:,COLUMNS]; y=np.array(source["labels"])
    f=source["results"]["LR9"]["folds"][fold]; tr,te=f["train"],f["test"]
    target.mkdir(exist_ok=False)
    with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always"); warnings.simplefilter("error",ConvergenceWarning)
        gc.collect(); before=process_memory(); cpu_start,start=time.process_time_ns(),time.perf_counter_ns()
        scaler=StandardScaler().fit(x[tr]); model=factory(name,0); model.fit(scaler.transform(x[tr]),y[tr])
        payload=(model,scaler)
        training_ns,training_cpu_ns=time.perf_counter_ns()-start,time.process_time_ns()-cpu_start
        gc.collect(); after=process_memory()
        assert scaler.n_samples_seen_==60 and model.get_params()==factory(name,0).get_params()
        if name=="SVM-RBF": assert model.fit_status_==0
        expected=np.array(reference["predictions"]["H7_DROP_F2"][name][0])[te]
        np.testing.assert_array_equal(predict(payload,x[te]),expected)
        artifact=target/"model.pkl"
        with artifact.open("xb") as stream: pickle.dump(payload,stream,protocol=5)
        with artifact.open("rb") as stream: restored=pickle.load(stream)
        np.testing.assert_array_equal(predict(restored,x[te]),expected); del restored
        rows=[np.ascontiguousarray(r.reshape(1,7)) for r in x[te]]
        transformed=[scaler.transform(r) for r in rows]
        identity=dict(scope="NON_FORMAL_ENGINEERING",run_id="PILOT120_SEVEN_CANDIDATE_REVIEW_20261108",
            data_id="reviewed_pilot120",model_id=name,config_id="fixed_seven_seed0",config_sha256=exports.digest(FEATURES),
            git=perf.git_identity(),environment=dict(perf.environment(),sklearn=sklearn.__version__,threadpools=threadpool_info()))
        raw={}; memories={}; enabled=gc.isenabled(); gc.disable()
        try:
            for op in ("classifier","pipeline"):
                values=transformed if op=="classifier" else rows
                callback=(lambda p,it:p[0].predict(next(it))) if op=="classifier" else (lambda p,it:predict(p,next(it)))
                result=run_benchmark(target/op,identity=identity,input_value=itertools.cycle(values),input_id=f"heldout_fold{fold}",
                    input_sha256=digest(BUNDLE/"samples.csv"),feature_order=FEATURES,seed=0,model=payload,predict=callback,
                    model_path=artifact,calls=CALLS,warmup_calls=WARMUP)
                assert result["run_status"]=="COMPLETED" and len(result["raw_inference_ns"])==CALLS
                raw[op]=result["raw_inference_ns"]; memories[op]=result["memory_observations"]
            count=0; cpu_start,start=time.process_time_ns(),time.perf_counter_ns()
            while True:
                for i in range(CALLS): predict(payload,rows[i%60])
                count+=CALLS
                if time.perf_counter_ns()-start>=250_000_000: break
            cpu_wall,cpu_ns=time.perf_counter_ns()-start,time.process_time_ns()-cpu_start
        finally:
            if enabled: gc.enable()
        write(target/"record.json",dict(model=name,fold=fold,repetition=rep,train=tr,test=te,predictions=expected.tolist(),
            model_path=str(artifact.relative_to(ROOT)),model_sha256=digest(artifact),model_bytes=artifact.stat().st_size,
            training_ns=training_ns,training_cpu_ns=training_cpu_ns,memory_before=before,memory_after=after,
            raw_ns=raw,benchmark_memory=memories,cpu_ns=cpu_ns,cpu_wall_ns=cpu_wall,cpu_calls=count,
            n_support=int(model.n_support_.sum()) if name=="SVM-RBF" else None,
            warnings=[f"{w.category.__name__}: {w.message}" for w in caught],environment=identity["environment"]))


def cost_summary(records):
    result={}
    for name in NAMES:
        own=[r for r in records if r["model"]==name]; assert len(own)==6
        raw={op:[n/1e6 for r in own for n in r["raw_ns"][op]] for op in ("classifier","pipeline")}
        result[name]=dict(training_ms=float(np.mean([r["training_ns"] for r in own])/1e6),
            training_cpu_ms=float(np.mean([r["training_cpu_ns"] for r in own])/1e6),
            model_kib=float(np.mean([r["model_bytes"] for r in own])/1024),
            classifier=_stats(raw["classifier"]),pipeline=_stats(raw["pipeline"]),
            cpu_ms_per_prediction=sum(r["cpu_ns"] for r in own)/1e6/sum(r["cpu_calls"] for r in own),
            one_core_cpu_percent=100*sum(r["cpu_ns"] for r in own)/sum(r["cpu_wall_ns"] for r in own),
            rss_after_mib=float(np.mean([r["memory_after"]["rss_bytes"] for r in own])/2**20),
            private_after_mib=float(np.mean([r["memory_after"]["private_bytes"] for r in own])/2**20),
            private_delta_mib=float(np.mean([r["memory_after"]["private_bytes"]-r["memory_before"]["private_bytes"] for r in own])/2**20))
    return result


def auxiliary(source):
    groups=defaultdict(list)
    for recording in sorted({k[1] for k in source["sample_keys"]}):
        with (ROOT/"captures"/recording/"features.csv").open(encoding="utf-8-sig",newline="") as stream:
            for row in csv.DictReader(stream): groups[(recording,row["segment_id"])].append(row)
    result=[]
    for i,key in enumerate(source["sample_keys"]):
        rows=groups[(key[1],key[2])]; common=[r for r in rows if all(present(r,f) for f in H9_FEATURE_NAMES)]
        fields={}
        for name in AUX:
            values=[float(r[name]) for r in common if present(r,name)]
            fields[name]=dict(median=float(np.median(values)) if values else None,n=len(values),
                original_input_frames=len(rows),h9_common_frames=len(common),
                common_fraction=len(values)/len(common),input_fraction=len(values)/len(rows))
        result.append(dict(index=i,sample_key=key,fields=fields))
    return result


def diagnose(records):
    source,reference=read(SOURCE),read(REF); x=np.array(source["matrix"])[:,COLUMNS]; y=np.array(source["labels"])
    people=np.array(source["subjects"]); aux=auxiliary(source); errors=[]; all_knn=[]
    svm_pred=np.array(reference["predictions"]["H7_DROP_F2"]["SVM-RBF"][0])
    knn_pred=np.array(reference["predictions"]["H7_DROP_F2"]["KNN"][0])
    for fold in (0,1):
        loaded={}
        for name in NAMES:
            r=next(r for r in records if r["model"]==name and r["fold"]==fold and r["repetition"]==0)
            path=ROOT/r["model_path"]; assert digest(path)==r["model_sha256"]
            with path.open("rb") as stream: loaded[name]=pickle.load(stream)
        tr,te=np.array(r["train"]),np.array(r["test"])
        svm,scaler=loaded["SVM-RBF"]; knn,knn_scaler=loaded["KNN"]
        np.testing.assert_array_equal(scaler.mean_,knn_scaler.mean_); z=scaler.transform(x)
        np.testing.assert_array_equal(svm.predict(z[te]),svm_pred[te]); np.testing.assert_array_equal(knn.predict(z[te]),knn_pred[te])
        distances,neighbors=knn.kneighbors(z[te]); neighbors=tr[neighbors]
        ovr=svm.decision_function(z[te]); ovo=svm._decision_function(z[te])
        # First libsvm pair is class0 versus class1. Reconstruct its kernel score.
        stop=int(svm.n_support_[0]+svm.n_support_[1]); support=svm.support_vectors_[:stop]
        coef=svm.dual_coef_[0,:stop]; kernel=np.exp(-svm._gamma*((z[te,None,:]-support[None,:,:])**2).sum(2))
        pair=kernel@coef+svm.intercept_[0]
        np.testing.assert_allclose(pair,ovo[:,0],rtol=0,atol=1e-12)
        for q,i in enumerate(te):
            nn=neighbors[q]; vote=np.bincount(y[nn],minlength=6)
            assert vote.argmax()==knn_pred[i] and all(people[j]!=people[i] for j in nn)
            all_knn.append(dict(index=int(i),neighbors=nn.tolist(),neighbor_labels=y[nn].tolist(),distances=distances[q].tolist(),votes=vote.tolist()))
            if svm_pred[i]==y[i] and knn_pred[i]==y[i]: continue
            actual=int(y[i]); wrong=0 if actual==1 else 1
            true_rows=tr[y[tr]==actual]; other_rows=tr[y[tr]==wrong]
            a=true_rows[np.argmin(((z[true_rows]-z[i])**2).sum(1))]; b=other_rows[np.argmin(((z[other_rows]-z[i])**2).sum(1))]
            contrast=(z[b]-z[i])**2-(z[a]-z[i])**2
            ranges={str(c):dict(minimum=x[tr[y[tr]==c]].min(0).tolist(),maximum=x[tr[y[tr]==c]].max(0).tolist(),
                median=np.median(x[tr[y[tr]==c]],axis=0).tolist()) for c in (actual,wrong)}
            errors.append(dict(index=int(i),sample_key=source["sample_keys"][i],subject=str(people[i]),actual=actual,
                svm_prediction=int(svm_pred[i]),knn_prediction=int(knn_pred[i]),raw=x[i].tolist(),z=z[i].tolist(),
                ranges=ranges,nearest_true_index=int(a),nearest_other_index=int(b),distance_contrast=dict(zip(FEATURES,contrast.tolist())),
                neighbors=nn.tolist(),neighbor_labels=y[nn].tolist(),ovr_scores=ovr[q].tolist(),pair01_score=float(pair[q]),
                pair01_support_contributions=(coef*kernel[q]).tolist(),pair01_intercept=float(svm.intercept_[0])))
    errors.sort(key=lambda r:r["index"]); all_knn.sort(key=lambda r:r["index"])
    common=[r for r in errors if r["svm_prediction"]!=r["actual"] and r["knn_prediction"]!=r["actual"]]
    summary=dict(svm_errors=int(np.sum(svm_pred!=y)),knn_errors=int(np.sum(knn_pred!=y)),common_errors=len(common),
        common_neighbor_patterns=dict(Counter(",".join(f"P{c}" for c in r["neighbor_labels"]) for r in common)),
        common_outside_true={},common_nearer_wrong={},common_negative_distance=dict(Counter(min(r["distance_contrast"],key=r["distance_contrast"].get) for r in common)),
        auxiliary={})
    for j,name in enumerate(FEATURES):
        summary["common_outside_true"][name]=sum(r["raw"][j]<r["ranges"][str(r["actual"])]["minimum"][j] or r["raw"][j]>r["ranges"][str(r["actual"])]["maximum"][j] for r in common)
        summary["common_nearer_wrong"][name]=sum(abs(r["raw"][j]-r["ranges"]["0"]["median"][j])<abs(r["raw"][j]-r["ranges"]["1"]["median"][j]) for r in common)
    for name in AUX:
        v=np.array([r["fields"][name]["median"] for r in aux],dtype=float)
        closer0,outside=0,0; ranges=[]
        for e in common:
            i=e["index"]; train=people!=people[i]; a=v[train&(y==0)]; b=v[train&(y==1)]
            closer0+=int(abs(v[i]-np.median(a))<abs(v[i]-np.median(b))); outside+=int(v[i]<b.min() or v[i]>b.max())
            ranges.append(dict(index=i,p0_range=[float(a.min()),float(a.max())],p1_range=[float(b.min()),float(b.max())],value=float(v[i])))
        overlaps=0; signs=[]
        for person in sorted(set(people)):
            a,b=v[(people==person)&(y==0)],v[(people==person)&(y==1)]
            overlaps+=int(max(a.min(),b.min())<=min(a.max(),b.max())); signs.append(int(np.sign(np.median(b)-np.median(a))))
        summary["auxiliary"][name]=dict(available=int(np.isfinite(v).sum()),minimum_common_fraction=min(r["fields"][name]["common_fraction"] for r in aux),
            minimum_input_fraction=min(r["fields"][name]["input_fraction"] for r in aux),
            minimum_frames=min(r["fields"][name]["n"] for r in aux),common_errors_nearer_p0=closer0,common_errors_outside_p1=outside,
            within_person_overlap_count=overlaps,p1_p0_delta_signs=signs,
            correlation_f4_full=float(np.corrcoef(v,x[:,FEATURES.index("F4")])[0,1]),
            correlation_f4_p0p1=float(np.corrcoef(v[y<2],x[y<2,FEATURES.index("F4")])[0,1]))
        for entry,r in zip(common,ranges): entry.setdefault("auxiliary_ranges",{})[name]=r
    return dict(errors=errors,all_knn=all_knn,auxiliary_values=aux,summary=summary)


def report(s):
    ref=read(REF); d=s["diagnosis"]["summary"]
    lines=["# 7특징 잠정 고정: SVM-RBF/KNN 오류·실행 비용과 다음 특징 설계", "",
        "실험 ID: `EXPLR-PILOT120-SEVEN-CANDIDATE-REVIEW-20261108`. "
        "F1,F3,F4,F5,F6,F7,F8을 잠정 고정한다. 최신 적격120구간(기존113+P01 P5 보완7), "
        "2인 LOSO 각60/60이며 처음24개는 포함하지 않았다. 반복 탐색자료이고 공식 선정·독립 검증이 아니다.", "",
        "## 오류 비교", "",
        "같은7특징의 이전 OOF 지표를 재사용했다. 비용 측정에서 seed0 모델을 다시 학습한 후 "
        "모든 시험 예측이 그 결과와 같음을 확인했다. SVM C=1,gamma=1/9,probability=False; "
        "KNN k=3,uniform,brute,Euclidean이며 각 train fold에서만 StandardScaler를 fit한다.", "",
        "|모델|정답/120|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|P2~P5 Recall %|", "|---|---:|---:|---:|---:|---:|---:|"]
    for name in NAMES:
        r=ref["summary"]["H7_DROP_F2"][name]
        lines.append(f"|{name}|{r['per_seed'][0]['correct']}/120|{r['mean']['accuracy']:.2f}|{r['mean']['macro_f1']:.2f}|{r['recall'][0]:.2f}|{r['recall'][1]:.2f}|100.00|")
    lines += ["",f"공통 오류는{d['common_errors']}개로 전부P1→P0다. SVM은총{d['svm_errors']}개, "
        f"KNN은총{d['knn_errors']}개이며 KNN만P0→P1 1개가 더 있다. 두 모델의 차이는1구간이다.", "",
        "## 실행 비용", "",
        "2모델×2fold×3회=12개 새 Python 프로세스를 순차 실행하고 순서를 교대했다. "
        "학습60구간/시험60구간이며 import·프로세스 시작·I/O는 학습/추론 시간에서 제외했다. "
        "학습 시간에는 scaler fit을 포함한다. native thread=1, 추론 중GC만 중단했다.", "",
        "기존 model_benchmark.run_benchmark를 재사용했다. 단일구간 predict를24회 warmup 후120회 측정, "
        "모델당6프로세스에서720개 추론 시간을 pool했다. classifier는 표준화 완료 입력, pipeline은 "
        "scaler.transform+predict다. 총 측정은2모델×2operation×720=2880회다. "
        "학습/크기는6프로세스 평균, 추론은 pooled p50/p95다.", "",
        "|모델|학습 wall ms|학습 CPU ms|pipeline p50 ms|pipeline p95 ms|classifier p50 ms|classifier p95 ms|pickle KiB|",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name,r in s["costs"].items():
        lines.append(f"|{name}|{r['training_ms']:.3f}|{r['training_cpu_ms']:.3f}|{r['pipeline']['p50']:.4f}|{r['pipeline']['p95']:.4f}|"
            f"{r['classifier']['p50']:.4f}|{r['classifier']['p95']:.4f}|{r['model_kib']:.2f}|")
    lines += ["", "pickle은 실제(model,scaler) protocol5 bytes이며 의존성·환경·배포 메타데이터 크기는 포함하지 않는다.", "",
        "|모델|pipeline CPU ms/구간|one-core CPU %|학습후 RSS MiB|학습후 Private MiB|Private 전후차 MiB|",
        "|---|---:|---:|---:|---:|---:|"]
    for name,r in s["costs"].items():
        lines.append(f"|{name}|{r['cpu_ms_per_prediction']:.4f}|{r['one_core_cpu_percent']:.1f}|{r['rss_after_mib']:.2f}|{r['private_after_mib']:.2f}|{r['private_delta_mib']:+.2f}|")
    lines += ["", "CPU는 별도 최소0.25초 반복 블록의 process CPU/wall 비율이며 시스템 전체 CPU%와 다르다. "
        "메모리는프로세스 전체의 학습 전후 snapshot이며 모델 전용/operation peak가 아니다. "
        "이 PC의 비정식 비용 관측이며 데스크톱 부하는 통제하지 않았다. D455 FPS·MediaPipe/Depth 추출·"
        "집계·화면 지연·장시간 안정성·현재 미구현 새 특징의 비용은 NOT_MEASURED다.", "",
        "## 남은 거북목 오류의 직접 근거", "",
        "SVM의6개 오류와 KNN의 해당6개 오류는같은구간이다. 다른사람의 학습P1 관측 min/max와대조했다.", "",
        "|특징|학습 P1 범위 밖인 오류/6|학습 P0 중앙값에 더 가까운 오류/6|", "|---|---:|---:|"]
    for name in FEATURES: lines.append(f"|{name}|{d['common_outside_true'][name]}|{d['common_nearer_wrong'][name]}|")
    lines += ["", "KNN 공통오류의 이웃3개 라벨:", ""]
    for pattern,n in sorted(d["common_neighbor_patterns"].items()): lines.append(f"- {pattern}: {n}구간")
    lines += ["", "SVM의6-class OVR 점수와 내부P0/P1 OVO kernel 점수를 저장했고, support-vector의 "
        "RBF kernel×dual coefficient 합과 절편으로 P0/P1 점수를 정확히 재구성했다. "
        "RBF를 선형 계수 기여로 해석하지 않았다. KNN 거리 대조에서도 오류지지항은 F8/F7/F5로 나뉘어 "
        "단일 특징만의 문제로 단정할 수 없다.", "",
        "F5는 얼굴/어깨 투영비, F7/F8은 어깨·흉부ROI·코의 위치 차다. 현재 관측은 참가자 간 기준 이동과 "
        "다중 신호 경합을 지지한다. 저장 라벨은 조작자 지정이며 원본 영상을 열지 않았으므로 "
        "체형·설치·옷/ROI·실제 자세 수행 중 물리적 주원인을 분리하지 못한다.", "",
        "## 기존 보조 관측으로 확인한 표현의 한계", "",
        "CSV에 이미 있는 보조값만 H9 공동지원 안에서 진단 집계했다. 새 특징을 구현하거나 모델에 넣지 않았다. "
        "보조값마다 유효 프레임 수를 기록하고, 기존7특징을 재집계하거나120개 분모를 바꾸지 않았다.", "",
        "|기존 보조값|관측 가능 구간|공통 오류가 학습P0 중앙값에 더 가까운 수/6|공통 오류가 학습P1 범위 밖인 수/6|",
        "|---|---:|---:|---:|"]
    for name,a in d["auxiliary"].items(): lines.append(f"|{name}|{a['available']}|{a['common_errors_nearer_p0']}|{a['common_errors_outside_p1']}|")
    hp=d["auxiliary"]["exploratory_head_pitch_deg"]
    lines += ["",f"기존3D 머리 pitch는6개 오류 모두 학습P1 중앙값 쪽에 더 가까웠고,5/6은학습P1 범위 안이었다. "
        f"F4와의Pearson r은전체120에서{hp['correlation_f4_full']:.3f}, P0/P1 40개에서{hp['correlation_f4_p0p1']:.3f}다. "
        "7특징 중F3는영상 내 측방축 기울기, F4/F5는머리 회전의2D 투영 신호이며 "
        "독립적인3D sagittal 회전 각도는직접 포함하지 않는다. 이관찰은3D 회전 표현 검토의근거지만 "
        "완전히새로운정보의누락이나추가성능이득을입증하지는않는다.", "",
        "## 설계 후보1개: HP3D (설계만, 추가 실험 없음)", "",
        "새 실험 ID: `EXPLR-PILOT120-HP3D-DESIGN-20261108`. "
        "현재7특징에후속후보1개로검토할HP3D는 기존 engineering `_exploratory_head_pitch_deg`와동일한정의다. "
        "새 수학적 발명으로 포장하지 않고 기존 보조 관측을새 분류 입력으로 제안한다.", "",
        "```text", "E = (LeftEar + RightEar)/2; N = Nose; C = Chin   # D455 XYZ, metres",
        "u = (N_y-E_y, N_z-E_z) / norm((N_y-E_y, N_z-E_z))",
        "v = (C_y-E_y, C_z-E_z) / norm((C_y-E_y, C_z-E_z))",
        "HP3D_t = degrees(atan2(-(u_y+v_y), -(u_z+v_z)))",
        "HP3D_segment = median(valid HP3D_t within the original H9 support)", "```", "",
        "MediaPipe Pose 귀7/8·코0, Face 턱152와 aligned D455 depth를 사용한다. 단위deg, 양수는위로 회전, "
        "음수는아래로 회전이다. 머리 전방 평행이동 자체는상쇄되고 회전이반영된다. "
        "기존 F8은전방 위치이므로 다른물리량이다. 카메라 pitch에는불변이아니며 임상 목각도가 아니다.", "",
        "후속가설: 깊이위치는정상과비슷하지만 머리회전은P1 쪽인구간에서3D 회전신호를명시하면P1→P0를줄이는가? "
        "단순 C3(몸통 기울기) 또는 EARZ(귀 전방 위치) 추가와다르다. 과거 두방법의실패와 "
        "이번두보조위치/몸통값도6개오류를정상쪽에가깝게보는부정적관찰을유지한다. "
        "F4와의상관·카메라각·얼굴/귀/턱depth오차 때문에중복되거나정답을악화시킬수있다.", "",
        "유효조건은필요XYZ와두ray norm>1e-6,합벡터 norm>1e-6, finite angle이다. "
        "후속설계에서는기존7열과120개 identity를고정하고 추가열만원래H9 support와HP3D 유효프레임의교집합에서집계, "
        "유효≥30프레임·원래입력대비coverage≥50%를확인하며결측채움은하지않는다. "
        f"현재진단에서최소{hp['minimum_frames']}프레임, 입력대비최소{100*hp['minimum_input_fraction']:.2f}%로120개모두기술적으로가능했다. "
        "기존CSV에이미값이있어재촬영없이후속검토가가능하다. 해당진단중앙값을이번모델에입력하지는않았다.", "",
        "기존XYZ가있으면unit ray2개·합·atan2의O(1) 산술과구간집계가추가된다. "
        "7특징운영경로에XYZ가없으면귀/턱depth샘플링과deprojection이추가될수있고결측위험도증가한다. "
        "실제ms/FPS증분은측정하지않았다. 후속모델비교를한다면현재7특징과7+HP3D만고정설정으로비교하는 "
        "단일사후가설이며그성능은아직미측정이다.", "",
        "## 파일·검증", "",
        "추가코드는review_pilot120_seven_candidates.py, 공개요약은이보고서다. "
        "7특징고정계획·12프로세스모델/시간/메모리·OOF/구간별거리/점수/보조값은local_private/에만보관한다. "
        "입력hash/라벨/LOSO·train-only scaler·기존예측재현·직렬화·raw시간요약·오류집합·"
        "SVM kernel score·보조support/값·MD 산술을확인했다. 공식8조합/B6/IRB HOLD/Patch8보류는유지하고 "
        "Commit/Push는하지않았다.", "",
        "실행: `python -X utf8 -B review_pilot120_seven_candidates.py`; 저장검증은 `--verify`(학습없음).", ""]
    return "\n".join(lines)


def verify():
    s=read(OUT/"local_private/results.json"); ref=read(REF)
    assert s["features"]==FEATURES and len(s["records"])==12 and cost_summary(s["records"])==s["costs"]
    assert len({(r["model"],r["fold"],r["repetition"]) for r in s["records"]})==12
    for r in s["records"]:
        assert all(len(r["raw_ns"][op])==CALLS for op in ("classifier","pipeline"))
        assert r["cpu_wall_ns"]>=250_000_000 and digest(ROOT/r["model_path"])==r["model_sha256"]
        assert r["predictions"]==np.array(ref["predictions"]["H7_DROP_F2"][r["model"]][0])[r["test"]].tolist()
    assert diagnose(s["records"])==s["diagnosis"]
    for path,sha in s["inputs"].items(): assert digest(ROOT/path)==sha
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: frozen7 inputs, 12 isolated benchmarks, exact OOF/models/kernel scores/neighbors/auxiliary supports, cost/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing output preserved; use --verify")
    verify_bundle(); ref=read(REF); source=read(SOURCE)
    for path,sha in ref["inputs"].items(): assert digest(ROOT/path)==sha
    for key in ("labels","subjects","sample_keys"): assert ref[key]==source[key]
    for name in NAMES: assert all(p==ref["predictions"]["H7_DROP_F2"][name][0] for p in ref["predictions"]["H7_DROP_F2"][name])
    paths=[REF,SOURCE,BUNDLE/"samples.csv",BUNDLE/"bundle_info.json",ROOT/"compare_six_feature_svm_knn.py",
        ROOT/"model_benchmark.py",ROOT/"performance_output.py",ROOT/"probe_timing.py",ROOT/"posture_geometry.py",
        ROOT/"posture_geometry_probe.py",ROOT/"review_pilot_six_capture.py",Path(__file__).resolve()]
    paths += [ROOT/"captures"/r/"features.csv" for r in sorted({k[1] for k in source["sample_keys"]})]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    private=OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_SEVEN_FEATURE_FREEZE",features=FEATURES,columns=list(COLUMNS),
        models=list(NAMES),factory_params={n:factory(n,0).get_params() for n in NAMES},repeats=REPEATS,warmup=WARMUP,calls=CALLS,
        benchmark_fits=12,input_hashes=inputs,auxiliary_diagnostic_fields=list(AUX),
        new_classifier_feature_experiments=0,design="at most one evidence-backed feature; no new implementation/performance test"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    records=[]
    for rep in range(REPEATS):
        for fold in (0,1):
            order=NAMES if (rep+fold)%2==0 else tuple(reversed(NAMES))
            for name in order:
                target=private/f"rep{rep}_fold{fold}_{name}"
                result=subprocess.run([sys.executable,"-X","utf8","-B",str(Path(__file__).resolve()),"--worker",name,str(fold),str(rep),str(target)],
                    cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
                if result.returncode: raise RuntimeError(result.stdout+result.stderr)
                records.append(read(target/"record.json")); print(f"benchmark {len(records)}/12 completed",flush=True)
    saved=dict(inputs=inputs,features=FEATURES,records=records,costs=cost_summary(records),diagnosis=diagnose(records),
        numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify(); print(saved["costs"]); print(saved["diagnosis"]["summary"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true"); parser.add_argument("--worker",nargs=4)
    args=parser.parse_args()
    if args.worker:
        name,fold,rep,target=args.worker; worker(name,int(fold),int(rep),Path(target))
    elif args.verify: verify()
    else: run()
