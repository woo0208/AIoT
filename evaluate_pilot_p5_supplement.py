"""Audit the seven P01 P5 supplements and compare fixed LR6/LR9 on 120 slots.

python -X utf8 -B evaluate_pilot_p5_supplement.py [--verify]
The unchanged P02-training fold is reused; only two new models are fitted.
Participant derivatives and selection bindings remain under local_private/.
"""
import argparse
from collections import Counter, defaultdict
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT, read, digest
from capture_six_pilot import load_p5_supplement_binding
from review_pilot_six_capture import csv_rows, present
from evaluate_new_pilot_lr6 import metrics, write, COLUMNS, REVIEW
from compare_new_pilot_lr9 import OUT as BEFORE, flows
from compare_lr_f2_f5 import changes
from lr_posture_demo import fixed_lr
from h6_offline import load_labeled_probe_h_samples, LAB6
from f1_sample_aggregator import H9_FEATURE_NAMES

import numpy as np
import sklearn
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/LR6_LR9_POST_SUPPLEMENT_20261108"
CONDITIONS = {"LR6": COLUMNS, "LR9": tuple(range(9))}


def audit_supplement(directory):
    plan, summary = (read(directory/name) for name in ("plan.json","run_summary.json"))
    binding = load_p5_supplement_binding()
    assert plan["supplement_for"] == summary["supplement_for"] == binding
    assert plan["subject"] == summary["subject"] == "P01"
    assert plan["recording_id"] == summary["recording_id"] == directory.name
    assert plan["scope"] == summary["scope"] == "EXPLORATORY_PILOT_ONLY"
    assert summary["status"] == "COMPLETED" and summary["error"] is None
    assert plan["posture_order"] == [LAB6[5]] and plan["hold_seconds"] == 10
    assert plan["repeats"] == plan["target_segments"] == summary["completed_segments"] == 7
    for key in ("transition_frames_in_features","upright_resets_are_samples","model_prediction_used_for_capture"):
        assert plan[key] is False
    assert digest(directory/"features.csv") == summary["features_sha256"]
    for path,sha in plan["source_sha256"].items(): assert digest(ROOT/path) == sha
    rows = csv_rows(directory/"features.csv"); groups = defaultdict(list)
    for row in rows:
        assert row["subject"] == "P01" and row["recording_id"] == directory.name and row["label"] == LAB6[5]
        groups[int(row["segment_id"])].append(row)
    assert set(groups) == set(range(1,8))
    assert summary["counts"] == {label:7 if label == LAB6[5] else 0 for label in LAB6}
    assert len(summary["attempts"]) == len(list((directory/"attempts").glob("attempt_*.json")))
    for a in summary["attempts"]:
        sidecar = directory/"attempts"/f"attempt_{a['attempt_id']:03d}.json"
        assert read(sidecar) == a
        attempt_rows = csv_rows(sidecar.with_suffix(".csv")); assert len(attempt_rows) == a["frames"]
        if a["status"] == "COMPLETED":
            assert a in summary["segments"] and attempt_rows == groups[a["intended_segment"]]
        else:
            assert a["status"] == "ABORTED" and a not in summary["segments"]
    for sid,a in enumerate(summary["segments"],1):
        assert a["intended_segment"] == sid and a["status"] == "COMPLETED" and a["label"] == LAB6[5]
        assert a["supplement_for"] == dict(recording_id=binding["original_recording_id"],
                                          segment_id=binding["original_segment_ids"][sid-1])
        records = groups[sid]; stamps = [float(r["device_timestamp_ms"]) for r in records]
        start,end = a["first_device_ms"],a["window_end_device_ms"]
        assert len(records) == a["frames"] and stamps[0] == start and stamps[-1] == a["last_device_ms"]
        assert all(start <= t < end for t in stamps) and all(b>a for a,b in zip(stamps,stamps[1:]))
        assert abs(end-start-10000) < 1e-6 and a["observed_end_device_ms"] >= end
        assert a["first_frame_index"] <= a["last_frame_index"] < a["end_boundary_frame_index"]
        mask = [all(present(r,f) for f in H9_FEATURE_NAMES) for r in records]
        assert mask == [all(present(r,H9_FEATURE_NAMES[j]) for j in COLUMNS) for r in records]
    samples = load_labeled_probe_h_samples([directory/"features.csv"])
    assert len(samples) == 7 and all(s.eligible for s in samples), "Stop before model fits if any supplement is ineligible"
    quality = [dict(sample_key=list(s.sample_key), original_segment_id=binding["original_segment_ids"][int(s.sample_key[2])-1],
                    frames=s.n_frames,common_valid=s.common_valid_count,coverage=s.common_coverage,eligible=s.eligible,
                    missing_counts=dict(s.missing_counts)) for s in samples]
    return samples, dict(binding=binding, samples=quality, attempt_status_counts=dict(Counter(a["status"] for a in summary["attempts"])),
        operator_metadata=plan["operator_metadata"],frames=len(rows),common_valid=sum(s.common_valid_count for s in samples))


def report(saved):
    q = saved["quality"]
    lines = ["# P01 P5 7구간 보완 검토와 6·9특징 LR 재평가", "",
        "실험 ID: `EXPLR-LR6-LR9-POST-SUPPLEMENT-20261108`. 기존 탐색자료의 기술적 결측7구간 보완이다. "
        "정식 평가·독립 검증·최종 모델 선정 결과가 아니다.", "", "## 촬영 품질과 포함 기준", "",
        f"P01 상체 전방(P5) 7구간 완료·7구간 적격. 총{q['frames']}프레임 중 H9 공동 유효{q['common_valid']}개다. "
        f"구간별 공동 coverage {100*min(s['coverage'] for s in q['samples']):.2f}~{100*max(s['coverage'] for s in q['samples']):.2f}%. "
        "원래 예정한7개 기술적 실패 slot과 일대일 연결했으며 모델 예측을 보고 선택하지 않았다.", "",
        "기존113구간+보완7구간=120구간. 참가자당60개, 참가자×자세당10개, 각 자세20개다. "
        "원래 실패7개를 학습/평가에 중복 포함하지 않고 원본·사유·연결 이력은 보존한다. "
        "기존24구간·P02 중단 실행은 합치지 않았다. 물리적 CSV 합치기나 원본 덮어쓰기는 없다.", "",
        "기존 H9 9열 공동지원≥30프레임·coverage≥50%, F3 방향성 원형평균/나머지 중앙값을 유지했다. "
        "6특징=F1,F3,F4,F6,F7,F8; 9특징=F1~F9. 기준 완화·결측 채움·새 특징·튜닝은 없다.", "",
        "## 고정 평가", "",
        "동일 참가자 LOSO2fold(각 train60/test60). P01의 원래 촬영과 보완 촬영은 반드시 같은 fold에 둔다. "
        "StandardScaler는 train에서만 fit. LR C=1,L2(l1_ratio=0),lbfgs,tol=1e-4,max_iter=10000, "
        "intercept=True,class_weight=None,random_state=0을 유지했다. 새로 fit한 모델은2개다. "
        "P02를 학습하는 fold는 입력·행 순서가 이전과 같아 기존6/9특징 모델2개를 hash 확인 후 재사용했다. "
        "120개 OOF pooled6-class 지표이며 학습자료 정확도가 아니다.", "",
        "|모델|정답/120|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|Weighted-F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name,r in saved["results"].items():
        m = r["metrics"]
        lines.append(f"|{name}|{m['correct']}/120|"+"|".join(f"{m[k]:.2f}" for k in
            ("accuracy","macro_f1","macro_precision","macro_recall","weighted_f1"))+"|")
    lines += ["", "|자세|support|6특징 Precision %|6특징 Recall %|6특징 F1 %|9특징 Precision %|9특징 Recall %|9특징 F1 %|",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i in range(6):
        a,b = (saved["results"][n]["metrics"]["per_class"][i] for n in CONDITIONS)
        lines.append(f"|P{i} {LAB6[i]}|20|"+"|".join(f"{r[k]:.2f}" for r in (a,b) for k in ("precision","recall","f1"))+"|")
    lines += ["", "## 보완 전후와 기존 표본의 예측 변화", "",
        "보완 전113개와 보완 후120개의 전체 점수 차이는 시험 분모·구성도 달라져 순수한 학습 개선량이 아니다. "
        "그래서 기존113개만 따로 고정한 후속 OOF도 함께 기록한다. 기존 표본의 실제 값/라벨은 바뀌지 않았다.", "",
        "|모델·평가 대상|정답/구간|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|P5 Recall %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name,r in saved["results"].items():
        for scope,m in (("보완 전113",saved["before"][name]),("보완 후 기존113",r["common113_metrics"]),("보완 후 전체120",r["metrics"])):
            values = [m["accuracy"],m["macro_f1"],*[m["per_class"][i]["recall"] for i in (0,1,5)]]
            lines.append(f"|{name} {scope}|{m['correct']}/{m['samples']}|"+"|".join(f"{v:.2f}" for v in values)+"|")
        c = r["common113_changes"]
        lines += ["",f"{name} 기존113개: 오답→정답{c['wrong_to_correct']}건, 정답→오답{c['correct_to_wrong']}건, "
            f"오답→다른 오답{c['wrong_to_wrong']}건. 새7개 정답{r['supplement_correct']}/7.", ""]
    lines += ["## 오류 유형과 혼동행렬", "", "|오류 유형|6특징|9특징|", "|---|---:|---:|"]
    fa,fb = (flows(saved["labels"],saved["results"][n]["predictions"]) for n in CONDITIONS)
    for flow in sorted(set(fa)|set(fb)): lines.append(f"|{flow}|{fa.get(flow,0)}|{fb.get(flow,0)}|")
    for name,r in saved["results"].items():
        lines += ["",f"### {name}","","행=실제P0~P5, 열=예측P0~P5, 건수다.","","```text",
                  *[" ".join(map(str,row)) for row in r["metrics"]["confusion_matrix"]],"```"]
    lines += ["", "## 해석과 다음 단계", "",
        "- 보완 후 P5가 균형을 갖췄지만 별도 날짜의 세션이다. 얼굴 관측과 자세 수행이 함께 달라졌을 수 있어 "
        "점수 변화를 표본 수 효과로만 설명할 수 없다. 설치 높이·거리·각도·조명은 여전히 미기록이다.",
        "- 참가자는여전히2명이고 같은 사람의 반복 탐색자료다. 보완 촬영은 이전 모델 결과를 이미 본 이후이나 "
        "대상7개는 예측 이전에 기술적 결측으로 정했다. 독립 검증/유의성/일반화 성능 향상으로 주장하지 않는다.",
        "- P0/P1의 혼동은 별도 확인해야 한다. 전체 Accuracy만으로 최종 모델을 정하거나 P5 보완이 "
        "P0/P1까지 해결했다고 가정하지 않는다. 틀린 구간 삭제·추가 재촬영·가중치/C 탐색을 하지 않았다.",
        "- 필요하면 다음 단계는 기존 고정 RF M0/SVM-RBF를 동일 자료에서 비교하는 것이다. 이번에는 "
        "데이터 보완 확인과 LR6/LR9 평가까지만 수행했고 다른 알고리즘·실행 비용은 재측정하지 않았다.", "",
        "## 검증·생성 파일", "",
        "실행 코드 evaluate_pilot_p5_supplement.py와 이 보고서를 추가했다. 입력/코드 hash, "
        "원래 실패7개 연결, attempt/main 행 일치,10초 경계·엄격 증가,공동지원,기존113개 불변, "
        "120개 slot/참가자/클래스 균형, train-only scaler,fold 재사용 동등성,수렴,OOF1회, "
        "모델 복원·점수/확률·지표/CSV/MD를 검증했다. 전체 회귀·원본영상 열람·카메라 실행은 하지 않았다.", "",
        "참가자별 특징값·예측·모델·연결표·품질·사전계획은local_private/에만 보관한다. 기존 파일/실시간 "
        "모델·공식8조합/B6/IRB HOLD/Patch8 실행 보류는 유지했다. Commit/Push는 하지 않았다.", "",
        "실행: `python -X utf8 -B evaluate_pilot_p5_supplement.py`; 저장 검증은 `--verify`(학습 없음).", ""]
    return "\n".join(lines)


def verify():
    s = read(OUT/"local_private/results.json"); before = read(BEFORE/"local_private/results.json")
    x,y,people = np.array(s["matrix"]),np.array(s["labels"]),np.array(s["subjects"])
    assert x.shape == (120,9) and np.bincount(y,minlength=6).tolist() == [20]*6
    assert Counter(people) == {"P01":60,"P02":60}
    assert s["sample_keys"][:113] == before["sample_keys"] and len({tuple(k) for k in s["sample_keys"]}) == 120
    np.testing.assert_array_equal(x[:113],before["matrix"])
    assert y[:113].tolist() == before["labels"] and people[:113].tolist() == before["subjects"]
    for name,cols in CONDITIONS.items():
        r = s["results"][name]; seen = np.zeros(120,dtype=int)
        assert r["metrics"] == metrics(y,r["predictions"])
        assert r["common113_metrics"] == metrics(y[:113],r["predictions"][:113])
        assert r["common113_changes"] == changes(y[:113],before["results"][name]["predictions"],r["predictions"][:113])
        assert r["supplement_correct"] == sum(p==5 for p in r["predictions"][113:])
        for i,f in enumerate(r["folds"]):
            tr,te = f["train"],f["test"]
            assert len(tr) == len(te) == 60 and set(tr).isdisjoint(te) and set(tr)|set(te) == set(range(120))
            assert set(people[tr]).isdisjoint(people[te]) and np.bincount(y[tr],minlength=6).tolist() == [10]*6
            artifact = OUT/"local_private"/f"{name}_fold{i}.pkl"; assert digest(artifact) == f["model_sha256"]
            with artifact.open("rb") as stream: model,scaler = pickle.load(stream)
            assert model.get_params() == fixed_lr().get_params() == s["lr_params"] and scaler.n_samples_seen_ == 60
            np.testing.assert_allclose(scaler.mean_,x[tr][:,cols].mean(0),rtol=0,atol=1e-14)
            np.testing.assert_allclose(scaler.scale_,x[tr][:,cols].std(0),rtol=0,atol=1e-14)
            test = scaler.transform(x[te][:,cols])
            np.testing.assert_array_equal(model.predict(test),np.array(r["predictions"])[te])
            np.testing.assert_allclose(model.decision_function(test),np.array(r["scores"])[te],rtol=0,atol=1e-14)
            np.testing.assert_allclose(model.predict_proba(test),np.array(r["probabilities"])[te],rtol=0,atol=1e-14)
            assert np.all(model.n_iter_ < model.max_iter)
            if f["reused"]:
                assert i == 0
                np.testing.assert_array_equal(model.coef_,before["results"][name]["folds"][0]["coef"])
                np.testing.assert_array_equal(np.array(r["predictions"])[te[:53]],np.array(before["results"][name]["predictions"])[:53])
            seen[te] += 1
        assert seen.tolist() == [1]*120
    for path,sha in s["inputs"].items(): assert digest(ROOT/path) == sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream: rows = list(csv.DictReader(stream))
    assert len(rows) == 240
    for row in rows:
        i = int(row["index"])
        assert int(row["actual"]) == y[i] and row["subject"] == people[i]
        assert int(row["predicted"]) == s["results"][row["model"]]["predictions"][i]
    assert report(s) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: supplement bindings/quality hashes, fixed120 samples/LOSO/scalers, model reuse/restoration, metrics/CSV/report; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing output preserved; use --verify")
    candidates = list((ROOT/"captures").glob("P01_p5supp_*"))
    assert len(candidates) == 1, "Require one explicit supplement; no latest-run selection"
    directory = candidates[0]; new_samples,quality = audit_supplement(directory)
    before = read(BEFORE/"local_private/results.json"); review = read(REVIEW)
    inputs = {**before["inputs"],**review["inputs"]}
    sources = [BEFORE/"local_private/results.json",REVIEW,Path(__file__).resolve(),ROOT/"capture_six_pilot.py",
        ROOT/"review_pilot_six_capture.py",ROOT/"evaluate_new_pilot_lr6.py",ROOT/"compare_new_pilot_lr9.py",
        ROOT/"compare_lr_f2_f5.py"]
    sources += [p for p in directory.rglob("*") if p.is_file() and p.suffix in (".json",".csv")]
    for path in sources: inputs[str(path.relative_to(ROOT))] = digest(path)
    for path,sha in inputs.items(): assert digest(ROOT/path) == sha
    runs = [r for r in review["inventory"] if r["status"] == "COMPLETED"]
    original = load_labeled_probe_h_samples([ROOT/r["directory"]/"features.csv" for r in runs])
    retained = [s for s in original if s.eligible]
    assert len(original) == 120 and len(retained) == 113
    assert [list(s.sample_key) for s in retained] == before["sample_keys"]
    samples = retained + list(new_samples)
    x = np.array([s.ordered_values("H9") for s in samples]); y = np.array([LAB6.index(s.label) for s in samples])
    people = np.array([s.subject for s in samples])
    assert x.shape == (120,9) and np.isfinite(x).all()
    np.testing.assert_array_equal(x[:113],before["matrix"])
    for person in ("P01","P02"): assert np.bincount(y[people==person],minlength=6).tolist() == [10]*6
    private = OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_ONLY",selection="existing113 plus all seven prospectively bound technical supplements",
        quality=quality,conditions={n:list(c) for n,c in CONDITIONS.items()},lr_params=fixed_lr().get_params(),
        input_hashes=inputs,new_fits=2,reused_folds=2,comparison="pooled120 and unchanged113 OOF; no search"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))] = digest(private/"PLAN.json")
    results = {}
    with threadpool_limits(limits=1),warnings.catch_warnings():
        warnings.simplefilter("error")
        for name,cols in CONDITIONS.items():
            matrix = x[:,cols]; pred = np.full(120,-1,dtype=int)
            scores = np.zeros((120,6)); probabilities = np.zeros((120,6)); folds = []
            for number,heldout in enumerate(("P01","P02")):
                tr,te = np.flatnonzero(people!=heldout),np.flatnonzero(people==heldout)
                if number == 0:
                    prior = before["results"][name]["folds"][0]
                    np.testing.assert_array_equal(matrix[tr],np.array(before["matrix"])[prior["train"]][:,cols])
                    artifact = (ROOT/"analysis/LR6_PRE_SUPPLEMENT_20261106" if name == "LR6" else BEFORE)/"local_private/fold0.pkl"
                    assert digest(artifact) == prior["model_sha256"]
                    inputs[str(artifact.relative_to(ROOT))] = digest(artifact)
                    with artifact.open("rb") as stream: model,scaler = pickle.load(stream)
                else:
                    scaler = StandardScaler().fit(matrix[tr]); model = fixed_lr()
                    model.fit(scaler.transform(matrix[tr]),y[tr])
                assert model.get_params() == fixed_lr().get_params() and np.all(model.n_iter_ < model.max_iter)
                test = scaler.transform(matrix[te]); pred[te] = model.predict(test)
                scores[te] = model.decision_function(test); probabilities[te] = model.predict_proba(test)
                artifact = private/f"{name}_fold{number}.pkl"
                with artifact.open("xb") as stream: pickle.dump((model,scaler),stream,protocol=5)
                folds.append(dict(heldout=heldout,train=tr.tolist(),test=te.tolist(),reused=number==0,
                    model_sha256=digest(artifact),n_iter=model.n_iter_.tolist()))
            results[name] = dict(features=[f"F{j+1}" for j in cols],predictions=pred.tolist(),scores=scores.tolist(),
                probabilities=probabilities.tolist(),folds=folds,metrics=metrics(y,pred),
                common113_metrics=metrics(y[:113],pred[:113]),
                common113_changes=changes(y[:113],before["results"][name]["predictions"],pred[:113].tolist()),
                supplement_correct=int(np.sum(pred[113:]==y[113:])))
    saved = dict(inputs=inputs,quality=quality,lr_params=fixed_lr().get_params(),new_fits=2,reused_folds=2,
        matrix=x.tolist(),labels=y.tolist(),subjects=people.tolist(),sample_keys=[list(s.sample_key) for s in samples],
        before={n:r["metrics"] for n,r in before["results"].items()},results=results,numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=["model","index","subject","actual","predicted","supplement"]); writer.writeheader()
        for name,r in results.items():
            writer.writerows(dict(model=name,index=i,subject=str(people[i]),actual=int(y[i]),predicted=p,supplement=i>=113) for i,p in enumerate(r["predictions"]))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify()
    for name,r in results.items():
        print(name,r["metrics"])
        print("existing113 changes",r["common113_changes"],"new7 correct",r["supplement_correct"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
