"""Compare fixed LR9 with the saved LR6 OOF on identical pre-supplement samples.

python -X utf8 -B compare_new_pilot_lr9.py [--verify]
Only LR9 is fitted (two LOSO folds). All participant derivatives stay private.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT, read, digest
from lr_posture_demo import DATA, FACTORY, fixed_lr, pilot_data
from evaluate_new_pilot_lr6 import OUT as BASE_OUT, REVIEW, COLUMNS, metrics, write
from compare_lr_f2_f5 import changes
from h6_offline import LAB6, load_labeled_probe_h_samples
from f1_sample_aggregator import H9_FEATURE_NAMES

import numpy as np
import sklearn
from sklearn.base import clone
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/LR6_LR9_PRE_SUPPLEMENT_20261106"
HISTORY = DATA.parent / "results.json"
OLD6 = ROOT / "analysis/LR_DROP_F2_F5_20261106/local_private/results.json"
IDS = [f"F{i}" for i in range(1, 10)]


def distributions(x, y, people):
    result = {}
    for j, feature in enumerate(IDS):
        by_person = {}
        for person in sorted(set(people)):
            classes = {}
            for c in range(6):
                v = x[(people == person) & (y == c), j]
                classes[str(c)] = dict(n=len(v), minimum=float(v.min()), maximum=float(v.max()),
                                       median=float(np.median(v)))
            by_person[str(person)] = classes
        pairs = {}
        for a, b in ((0, 1), (1, 5)):
            overlaps, deltas = [], []
            for classes in by_person.values():
                u, v = classes[str(a)], classes[str(b)]
                overlaps.append(max(u["minimum"], v["minimum"]) <= min(u["maximum"], v["maximum"]))
                deltas.append(v["median"] - u["median"])
            av, bv = x[y == a, j], x[y == b, j]
            pairs[f"P{a}_P{b}"] = dict(within_overlap_count=sum(overlaps),
                median_delta_signs=np.sign(deltas).astype(int).tolist(),
                pooled_overlap=bool(max(av.min(), bv.min()) <= min(av.max(), bv.max())))
        result[feature] = dict(by_person=by_person, pairs=pairs)
    return result


def diagnose(x, y, people, result, columns):
    errors, training = [], []
    for fold in result["folds"]:
        tr, te = np.array(fold["train"]), np.array(fold["test"])
        mean, scale = np.array(fold["mean"]), np.array(fold["scale"])
        coef, intercept = np.array(fold["coef"]), np.array(fold["intercept"])
        z = (x[:, columns] - mean) / scale
        scores = z @ coef.T + intercept
        np.testing.assert_allclose(scores[te], np.array(result["scores"])[te], rtol=0, atol=1e-12)
        np.testing.assert_array_equal(np.argmax(scores[te], axis=1), np.array(result["predictions"])[te])
        training.append(dict(heldout=fold["heldout"], samples=len(tr),
                             correct=int(np.sum(scores[tr].argmax(1) == y[tr]))))
        for i in te:
            actual, wrong = int(y[i]), result["predictions"][i]
            if actual == wrong:
                continue
            contribution = (coef[actual] - coef[wrong]) * z[i]
            bias = float(intercept[actual] - intercept[wrong])
            margin = float(scores[i, actual] - scores[i, wrong])
            np.testing.assert_allclose(contribution.sum() + bias, margin, rtol=0, atol=1e-12)
            ranges = {}
            for c in (actual, wrong):
                rows = x[tr[y[tr] == c]][:, columns]
                ranges[str(c)] = dict(minimum=rows.min(0).tolist(), maximum=rows.max(0).tolist(),
                                      median=np.median(rows, axis=0).tolist())
            errors.append(dict(index=int(i), subject=str(people[i]), actual=actual, predicted=wrong,
                raw=x[i, columns].tolist(), z=z[i].tolist(), margin=margin,
                feature_contributions=dict(zip([IDS[j] for j in columns], contribution.tolist())),
                intercept_contribution=bias, training_ranges=ranges))
    return dict(errors=errors, training=training)


def flows(y, pred):
    return dict(sorted(Counter(f"P{a}→P{b}" for a,b in zip(y,pred) if a != b).items()))


def report(saved):
    lines = ["# 신규 탐색자료: 6특징·기존9특징 LR 비교와 정확도 하락 재진단", "",
        "실험 ID: `EXPLR-LR6-LR9-PRE-SUPPLEMENT-20261106`. 직전 모델은7특징이 아닌 "
        "**6특징(F1,F3,F4,F6,F7,F8)**이었다. 이번9특징은F1~F9 전체다. "
        "기존B0는별도로F1~F8의8특징 모델이며9특징과 혼동하지 않는다.", "",
        "## 동일 조건 비교", "",
        "재촬영 전 완료120구간 중 기존H9 기준 적격113구간, 동일 sample identity/라벨/9열 공동지원/집계, "
        "참가자 LOSO2fold를 유지했다. P0~P4각20개, P5는13개다. 7개 얼굴 결측 구간은 두 모델에서 "
        "동일하게 제외했고 값을 채우거나 적격 기준을 바꾸지 않았다. 중단 실행·기존24구간·보완 촬영은 "
        "새 평가에 합치지 않았다. 6특징은 저장된 OOF/모델을 재사용했고 새 학습은9특징2회뿐이다.", "",
        "LR C=1, L2(l1_ratio=0), lbfgs, tol=1e-4, max_iter=10000, intercept=True, "
        "class_weight=None, random_state=0. 기존fixed_lr 생성기를 재사용하고 StandardScaler는 "
        "각 train fold에서만 fit했다. 평가 단위는 구간이며113개 OOF pooled6-class 지표다. "
        "각 모델에서 특징 수만 다르다. 추가 조합·다른 알고리즘·튜닝은 하지 않았다.", "",
        "|모델|정답/113|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|Weighted-F1 %|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name, r in saved["results"].items():
        m = r["metrics"]
        lines.append(f"|{name}|{m['correct']}/113|" + "|".join(f"{m[k]:.2f}" for k in
            ("accuracy", "macro_f1", "macro_precision", "macro_recall", "weighted_f1")) + "|")
    lines += ["", "|자세|support|6특징 Precision %|6특징 Recall %|6특징 F1 %|9특징 Precision %|9특징 Recall %|9특징 F1 %|",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    a, b = (saved["results"][n]["metrics"] for n in ("LR6", "LR9"))
    for c in range(6):
        aa, bb = a["per_class"][c], b["per_class"][c]
        values = [r[k] for r in (aa,bb) for k in ("precision","recall","f1")]
        lines.append(f"|P{c} {LAB6[c]}|{aa['support']}|" + "|".join(f"{v:.2f}" for v in values) + "|")
    change = saved["changes"]
    lines += ["", f"6→9특징: Accuracy {b['accuracy']-a['accuracy']:+.2f}pp, "
        f"Macro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp. 예측 변경{change['changed']}건: "
        f"오답→정답{change['wrong_to_correct']}, 정답→오답{change['correct_to_wrong']}, "
        f"오답→다른 오답{change['wrong_to_wrong']}.", "", "|오류 유형|6특징|9특징|", "|---|---:|---:|"]
    fa, fb = (flows(saved["labels"],saved["results"][n]["predictions"]) for n in ("LR6","LR9"))
    for flow in sorted(set(fa)|set(fb)):
        lines.append(f"|{flow}|{fa.get(flow,0)}|{fb.get(flow,0)}|")
    lines += ["", "## 혼동행렬", "", "행=실제P0~P5, 열=예측P0~P5, 정수 건수다."]
    for name,r in saved["results"].items():
        lines += ["", f"### {name}", "", "```text", *[" ".join(map(str,row)) for row in r["metrics"]["confusion_matrix"]], "```"]
    lines += ["", "## 이전24구간과 새113구간", "",
        "이 표는 서로 다른 자료의 관측 차이다. 동일 시험세트 전후 개선/악화나 인과 효과가 아니다. "
        "24구간의 저장된 예측을 재사용했으며 추가 학습은 없다.", "",
        "|자료·모델|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|P2 Recall %|P3 Recall %|P4 Recall %|P5 Recall %|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for scope in ("old24","new113"):
        for name in ("LR6","LR9"):
            m = saved["historical"][name] if scope == "old24" else saved["results"][name]["metrics"]
            values = [m["accuracy"],m["macro_f1"],*[r["recall"] for r in m["per_class"]]]
            lines.append(f"|{scope} {name}|"+"|".join(f"{v:.2f}" for v in values)+"|")
    lines += ["", "## 재진단: 관측 근거", "",
        "다음은 원인을 확정하는 검정이 아닌 설명용 탐색이다. 저장된 fold의 점수와 "
        "`(coef_true−coef_wrong)×z` 및 절편 차이를 재계산했다. 합은 실제−오답 margin과 일치한다. "
        "상관된 특징·표준화 기준점에 의존하는 대수 분해이며 인과적 중요도가 아니다.", "",
        "|모델|오류 유형|건수|가장 음의 특징 기여로 가장 자주 나타난 항|", "|---|---|---:|---|"]
    for name,diagnosis in saved["diagnostics"].items():
        for flow in sorted(flows(saved["labels"],saved["results"][name]["predictions"])):
            errors = [e for e in diagnosis["errors"] if f"P{e['actual']}→P{e['predicted']}" == flow]
            counter = Counter()
            for e in errors:
                feature = min(e["feature_contributions"],key=e["feature_contributions"].get)
                if e["feature_contributions"][feature] < 0:
                    counter[feature] += 1
            summary = ", ".join(f"{f} {n}건" for f,n in counter.most_common()) or "음의 특징 항 없음"
            lines.append(f"|{name}|{flow}|{len(errors)}|{summary}|")
    lines += ["", "P0/P1 구간별 min/max 겹침(겹치는 참가자 수/2). 표본이 늘면 관측 범위가 "
        "넓어질 수 있으므로 겹침 증가만으로 측정 품질 악화를 단정하지 않는다. 개인별 원값은 로컬에만 둔다.", "",
        "|특징|기존24 내부 겹침|신규113 내부 겹침|기존24 pooled 겹침|신규113 pooled 겹침|",
        "|---|---:|---:|---|---|"]
    for feature in IDS:
        old, new = (saved["distributions"][scope][feature]["pairs"]["P0_P1"] for scope in ("old24","new113"))
        lines.append(f"|{feature}|{old['within_overlap_count']}/2|{new['within_overlap_count']}/2|"
            f"{'있음' if old['pooled_overlap'] else '없음'}|{'있음' if new['pooled_overlap'] else '없음'}|")
    for name,diag in saved["diagnostics"].items():
        total = sum(r["samples"] for r in diag["training"])
        correct = sum(r["correct"] for r in diag["training"])
        lines += ["", f"{name}: 두 학습 fold를 합친 재대입 정답{correct}/{total}; "
            f"참가자를 바꾼 OOF 정답{saved['results'][name]['metrics']['correct']}/113. "
            "학습 재대입은 일반화 지표가 아니며 OOF와 구분한다."]
    lines += ["", "## 해석 범위·보존·검증", "",
        "- 반복 구간 수는 늘었지만 독립 참가자는여전히2명이다. 기존24구간은 반복 탐색·특징 선택에 "
        "사용한 작은 자료다. 그때의91.67%를 새 자료에서 보장할 수 없다. 정확도는 예측 정답 비율이며 "
        "개별 예측확률이나 확률 보정 성능과 다른 지표다.",
        "- P5 얼굴 결측7구간은 모두 한 사람에게 발생해 학습 P5가3개인 fold가 있다. P5 오류와 "
        "동시에 관찰되지만 결측 수·수행 방식·개인차 중 무엇이 원인인지는 이 비교로 분리되지 않는다. "
        "7구간 보완만으로 P0/P1까지 개선된다고 보장하지 않는다.",
        "- 카메라 설치·체형·의복/흉부ROI·자세 수행·세션 차이가 특징 분포를 바꿀 수 있다. "
        "설치 metadata 미기록이고 원본 영상을 보지 않았으므로 특정 물리적 원인으로 확정하지 않는다. "
        "시험 참가자의 분포를 scaler fit이나 모델 학습에 사용하지 않았다.",
        "- 동일113 identity/6열 일치/9열 순서·원본/이전 결과 hash, train-only scaler/참가자 분리/OOF1회, "
        "LR 파라미터/수렴, 모델 복원, 점수·확률·계수 기여 합, 지표/CSV/MD 일치를 검증했다. "
        "전체 회귀·원본영상 열람·촬영·새 특징 구현은 하지 않았다.",
        "- 실행 코드 compare_new_pilot_lr9.py와 이 요약 외에 참가자 특징·범위·예측·판정점수·"
        "계수 기여·fold별 모델·사전계획은 local_private/에만 저장한다. 기존 파일과 실시간 모델, "
        "공식8조합/B6/IRB HOLD/Patch8 실행 보류를 유지하며 commit/push는 하지 않았다.", "",
        "실행: `python -X utf8 -B compare_new_pilot_lr9.py`; 저장 검증만은 `--verify`(학습 없음).", ""]
    return "\n".join(lines)


def verify():
    saved = read(OUT/"local_private/results.json")
    x, y, people = np.array(saved["matrix"]), np.array(saved["labels"]), np.array(saved["subjects"])
    assert x.shape == (113,9) and np.bincount(y,minlength=6).tolist() == [20,20,20,20,20,13]
    base = read(BASE_OUT/"local_private/results.json")
    np.testing.assert_array_equal(x[:,COLUMNS],base["matrix"])
    assert saved["sample_keys"] == base["sample_keys"] and saved["subjects"] == base["subjects"]
    assert saved["labels"] == base["labels"]
    assert saved["results"]["LR6"]["predictions"] == base["predictions"]
    for name,columns in (("LR6",COLUMNS),("LR9",tuple(range(9)))):
        r = saved["results"][name]
        assert r["metrics"] == metrics(y,r["predictions"])
        assert r["features"] == [IDS[j] for j in columns]
        seen = np.zeros(113,dtype=int)
        for number,f in enumerate(r["folds"]):
            tr,te = f["train"],f["test"]
            assert set(tr).isdisjoint(te) and set(tr)|set(te) == set(range(113))
            assert set(people[tr]).isdisjoint(people[te])
            assert tr == base["folds"][number]["train"] and te == base["folds"][number]["test"]
            np.testing.assert_allclose(f["mean"],x[tr][:,columns].mean(0),rtol=0,atol=1e-14)
            np.testing.assert_allclose(f["scale"],x[tr][:,columns].std(0),rtol=0,atol=1e-14)
            artifact = (BASE_OUT if name == "LR6" else OUT)/"local_private"/f"fold{number}.pkl"
            assert digest(artifact) == f["model_sha256"]
            with artifact.open("rb") as stream: model,scaler = pickle.load(stream)
            assert model.get_params() == fixed_lr().get_params() == saved["lr_params"]
            assert scaler.n_samples_seen_ == len(tr)
            np.testing.assert_array_equal(model.predict(scaler.transform(x[te][:,columns])),np.array(r["predictions"])[te])
            np.testing.assert_allclose(model.predict_proba(scaler.transform(x[te][:,columns])),np.array(r["probabilities"])[te],rtol=0,atol=1e-14)
            seen[te] += 1
        assert seen.tolist() == [1]*113
        assert diagnose(x,y,people,r,columns) == saved["diagnostics"][name]
    assert changes(y,saved["results"]["LR6"]["predictions"],saved["results"]["LR9"]["predictions"]) == saved["changes"]
    for path,sha in saved["inputs"].items(): assert digest(ROOT/path) == sha
    assert report(saved) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 226
    for row in rows:
        i = int(row["index"])
        assert row["subject"] == people[i] and int(row["actual"]) == y[i]
        assert int(row["predicted"]) == saved["results"][row["model"]]["predictions"][i]
    print("PASS: identical113 samples, fixed LOSO/LR/train-only scalers, restored predictions, contributions, metrics/CSV/report/hashes; no fits")


def run():
    if OUT.exists(): raise FileExistsError("Existing output preserved; use --verify")
    base = read(BASE_OUT/"local_private/results.json")
    review = read(REVIEW)
    inputs = {**base["inputs"],**review["inputs"]}
    sources = [BASE_OUT/"local_private/results.json", REVIEW, HISTORY, DATA, OLD6, FACTORY,
               Path(__file__).resolve(), ROOT/"evaluate_new_pilot_lr6.py",ROOT/"compare_lr_f2_f5.py"]
    for path in sources: inputs[str(path.relative_to(ROOT))] = digest(path)
    for path,sha in inputs.items(): assert digest(ROOT/path) == sha
    runs = [r for r in review["inventory"] if r["status"] == "COMPLETED"]
    all_samples = load_labeled_probe_h_samples([ROOT/r["directory"]/"features.csv" for r in runs])
    assert len(all_samples) == 120 and sum(not s.eligible for s in all_samples) == 7
    samples = [s for s in all_samples if s.eligible]
    x = np.array([[s.features[f] for f in H9_FEATURE_NAMES] for s in samples])
    y = np.array([LAB6.index(s.label) for s in samples]); people = np.array([s.subject for s in samples])
    assert [list(s.sample_key) for s in samples] == base["sample_keys"]
    assert people.tolist() == base["subjects"] and y.tolist() == base["labels"]
    np.testing.assert_array_equal(x[:,COLUMNS],base["matrix"])
    assert x.shape == (113,9) and np.isfinite(x).all()
    template = fixed_lr(); assert template.get_params() == base["lr_params"]
    old,_,oldy = pilot_data()
    historic = read(HISTORY)["results"]["Logistic-Regression"]["predictions_by_seed"]
    assert all(p == historic[0] for p in historic)
    old6 = read(OLD6)
    assert old6["labels"] == old["labels"] and old6["sample_keys"] == old["sample_keys"]
    private = OUT/"local_private"; private.mkdir(parents=True,exist_ok=False)
    write(private/"PLAN.json",dict(scope="EXPLORATORY_ONLY_PRE_SUPPLEMENT",features=IDS,
        reference="saved LR6 OOF; no refits",new_fits=2,lr_params=template.get_params(),
        input_hashes=inputs, sample_keys=base["sample_keys"],
        diagnostics="old/new distributions, training-vs-LOSO, score contributions; no tuning"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))] = digest(private/"PLAN.json")
    pred = np.full(113,-1,dtype=int); scores = np.zeros((113,6)); prob = np.zeros((113,6)); folds = []
    with threadpool_limits(limits=1),warnings.catch_warnings():
        warnings.simplefilter("error")
        for number,f in enumerate(base["folds"]):
            tr,te = f["train"],f["test"]
            scaler = StandardScaler().fit(x[tr]); model = clone(template)
            model.fit(scaler.transform(x[tr]),y[tr])
            assert np.all(model.n_iter_ < model.max_iter)
            test = scaler.transform(x[te]); pred[te] = model.predict(test)
            scores[te] = model.decision_function(test); prob[te] = model.predict_proba(test)
            artifact = private/f"fold{number}.pkl"
            with artifact.open("xb") as stream: pickle.dump((model,scaler),stream,protocol=5)
            folds.append(dict(heldout=f["heldout"],train=tr,test=te,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                coef=model.coef_.tolist(),intercept=model.intercept_.tolist(),n_iter=model.n_iter_.tolist(),model_sha256=digest(artifact)))
    results = dict(LR6={k:base[k] for k in ("features","predictions","scores","probabilities","folds","metrics")},
        LR9=dict(features=IDS,predictions=pred.tolist(),scores=scores.tolist(),probabilities=prob.tolist(),folds=folds,metrics=metrics(y,pred)))
    saved = dict(inputs=inputs,lr_params=template.get_params(),new_fit_count=2,
        matrix=x.tolist(),labels=y.tolist(),subjects=people.tolist(),sample_keys=base["sample_keys"],results=results,
        historical=dict(LR6=metrics(oldy,old6["results"]["B0-F2-F5"]["predictions"]),LR9=metrics(oldy,historic[0])),
        changes=changes(y,base["predictions"],pred.tolist()),
        distributions=dict(old24=distributions(np.array(old["matrix"]),oldy,np.array(old["subjects"])),
                           new113=distributions(x,y,people)),
        diagnostics={n:diagnose(x,y,people,results[n],cols) for n,cols in (("LR6",COLUMNS),("LR9",tuple(range(9))))},
        numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=["model","index","subject","actual","predicted"]); writer.writeheader()
        for name,r in results.items():
            writer.writerows(dict(model=name,index=i,subject=str(people[i]),actual=int(y[i]),predicted=p) for i,p in enumerate(r["predictions"]))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify()
    for name,r in results.items(): print(name,r["metrics"])
    print("changes",saved["changes"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
