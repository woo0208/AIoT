"""Evaluate the authorized fixed F1/F3/F4/F5 subset on the existing pilot120.

python -X utf8 -B compare_pilot120_2d4.py [--verify]
Reuse historical factories, seeds, sample support and LOSO; no tuning.
"""
import argparse
from collections import Counter
import csv
import pickle
import sys
import warnings

from review_lr_features import ROOT, read, digest
from bundle_pilot120 import SOURCE, OUT as BUNDLE, verify as verify_bundle
from compare_pilot120_feature_sets import (
    OUT as PRIOR, MODELS, factory, expected_params, seeds_for,
    verify as verify_prior,
)
from compare_pilot120_fixed_models import summarize
from evaluate_new_pilot_lr6 import write
from compare_lr_f2_f5 import changes
from compare_new_pilot_lr9 import flows
from lr_posture_demo import FACTORY

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/PILOT120_2D4_20261111"
COLUMNS = (0, 2, 3, 4)
FEATURES = ("F1", "F3", "F4", "F5")
BASELINE = "H7_DROP_F2"


def report(saved):
    lines = [
        "# 기존120구간: 선별 2D 4특징과 7특징의 고정5모델 비교", "",
        "실험 ID: `EXPLR-PILOT120-2D4-20261111`. 사용자 요청에 따른 개발 탐색 평가다. "
        "동일 참가자2명의 반복 사용 자료이며 독립 검증이나 공식 모델 선정 결과가 아니다.", "",
        "## 고정 입력과 평가", "",
        "2D 입력은 **F1,F3,F4,F5**다. 각각 어깨 대비 머리 중심 좌우 위치/2D 어깨너비, "
        "홍채 중점→턱의 영상 내 기울기, 귀 중점−홍채 중점 수직 차/2D 어깨너비, "
        "코−턱 2D 거리/2D 어깨너비다. Depth F6/F7/F8과 F2/F9는 모델 입력에서 제외했다.", "",
        "기존 적격120구간(113+기술적 P5 보완7), 참가자당60·클래스당20개를 그대로 사용했다. "
        "원래 H9 공동 support·집계·라벨·표본 순서·적격성을 유지하고 저장9열에서 네 열만 선택했다. "
        "F3는 기존 원형 평균, 다른 입력은 기존 중앙값이다. 2D 전용 support로 재집계하지 않았으므로 "
        "Depth 없는 촬영의 획득률·적격률 또는 RGB-only 전체 파이프라인을 검증한 결과는 아니다.", "",
        "참가자 LOSO2fold(train60/test60), 동일 참가자의 두 세션은 같은 fold다. "
        "StandardScaler는 LR/SVM/Linear SVM/KNN의 train fold에만 fit했고 RF M0는 원값을 사용했다. "
        "기존 생성기와 설정을 그대로 재사용했다: LR C1/L2/lbfgs; M0 500trees/max_features2; "
        "SVM-RBF C1/gamma1/9; LinearSVC C1/L2/squared_hinge/dualFalse; KNN k3/uniform/Euclidean. "
        "특징 수에 맞춰 gamma를 바꾸거나 파라미터를 탐색하지 않았다.", "",
        "LR/KNN은 seed0의 한 OOF 결과, M0/SVM/Linear SVM은 기존 seeds0~4의 seed별 OOF 지표 평균이다. "
        "신규 학습은34회다. seed 반복은 독립 표본이 아니다. 7특징(F1,F3,F4,F5,F6,F7,F8)은 "
        "검증된 기존 저장 예측을 재사용했다. 학습 전에 입력hash/특징/설정/분할 계획을 저장했다.", "",
        "## 전체 결과", "", "단위 %, 차이는 percentage points다.", "",
        "|모델|2D4 Accuracy|7특징 Accuracy|차이 pp|2D4 Macro-F1|7특징 Macro-F1|차이 pp|",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in MODELS:
        current = saved["summary"][name]["mean"]
        old = saved["baseline7"][name]["mean"]
        vals = [current["accuracy"], old["accuracy"], current["accuracy"]-old["accuracy"],
                current["macro_f1"], old["macro_f1"], current["macro_f1"]-old["macro_f1"]]
        lines.append(f"|{name}|" + "|".join(f"{v:.2f}" for v in vals) + "|")
    lines += ["", "## 클래스별 Recall", "",
              "|모델|구성|P0|P1|P2|P3|P4|P5|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for name in MODELS:
        for config, summary in (("2D4", saved["summary"]), ("7특징", saved["baseline7"])):
            lines.append(f"|{name}|{config}|" + "|".join(f"{v:.2f}" for v in summary[name]["recall"]) + "|")
    lines += ["", "## 2D4 오류 유형", "", "건수는 seed당 평균이다.", "",
              "|모델|실제→예측|평균 건수|", "|---|---|---:|"]
    for name, predictions in saved["predictions"].items():
        counts = Counter()
        for pred in predictions:
            counts.update(flows(saved["labels"], pred))
        for flow, count in sorted(counts.items()):
            lines.append(f"|{name}|{flow}|{count/len(predictions):.2f}|")
    lines += ["", "## 7특징에서 2D4로 바꾼 오류 변화", "",
              "|모델|오답→정답|정답→오답|오답→다른 오답|", "|---|---:|---:|---:|"]
    for name in MODELS:
        paired = [changes(saved["labels"], old, new) for old, new in
                  zip(saved["baseline7_predictions"][name], saved["predictions"][name])]
        lines.append(f"|{name}|" + "|".join(f"{np.mean([c[k] for c in paired]):.2f}"
                     for k in ("wrong_to_correct", "correct_to_wrong", "wrong_to_wrong")) + "|")
    lines += ["", "## 2D4 seed별 결과", "",
              "|모델|seed|Accuracy|Macro-F1|P0 Recall|P1 Recall|P5 Recall|",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name in MODELS:
        for seed, m in zip(seeds_for(name), saved["summary"][name]["per_seed"]):
            vals = [m["accuracy"], m["macro_f1"], *[m["per_class"][i]["recall"] for i in (0, 1, 5)]]
            lines.append(f"|{name}|{seed}|" + "|".join(f"{v:.2f}" for v in vals) + "|")
    lines += ["", "## 검증과 한계", "",
        "기존120 bundle/7특징 검증, 입력hash 불변, 동일 표본/라벨/참가자 분리, train-only scaler, "
        "고정 파라미터, seed별 각 표본 OOF1회, 수렴, 직렬화 복원 예측, "
        "저장예측→정확도/Macro-F1/혼동행렬/클래스지표 재계산, CSV와 보고서 일치를 확인했다. "
        "환경은 Python " + saved["python"] + ", NumPy " + saved["numpy"] + ", sklearn " + saved["sklearn"] + ".", "",
        "논문6특징(F0)은 이 자료에서 계산하지 않았다. 논문 특징과의 비교, 촬영, 실행비용 측정, "
        "실시간 모델 교체, 공식 평가 또는 추가 탐색을 이번 결과로 수행하지 않았다. "
        "기존 공식 평가 규약과 Patch8 실행 보류는 유지한다. 원본과 과거 결과는 보존한다.", "",
        "추가 소스: compare_pilot120_2d4.py. 요약은 이 REPORT.md이며 "
        "계획/입력identity/OOF/fold/scaler/warnings는 local_private/에만 저장했다. 모델파일 저장·commit·push 없음.", "",
        "실행: `python -X utf8 -B compare_pilot120_2d4.py`; "
        "저장 산술/입력 검증: 같은 명령에 `--verify`(학습 없음).", ""]
    return "\n".join(lines)


def verify():
    verify_bundle()
    verify_prior()
    saved = read(OUT / "local_private/results.json")
    source = read(SOURCE)
    prior = read(PRIOR / "local_private/results.json")
    plan = read(OUT / "local_private/PLAN.json")
    assert plan["columns"] == list(COLUMNS) and plan["features"] == list(FEATURES)
    assert plan["models"] == list(MODELS) and plan["new_fits"] == 34
    assert saved["new_fits"] == len(saved["folds"]) == 34
    for key in ("labels", "subjects", "sample_keys"):
        assert saved[key] == source[key] == prior[key]
    y = np.array(saved["labels"])
    x = np.array(source["matrix"])[:, COLUMNS]
    assert x.shape == (120, 4) and np.isfinite(x).all()
    assert plan["folds"] == source["results"]["LR9"]["folds"]
    for name in MODELS:
        ps = saved["predictions"][name]
        assert len(ps) == len(seeds_for(name))
        assert plan["seeds"][name] == list(seeds_for(name))
        assert saved["summary"][name] == summarize(y, ps)
        assert saved["baseline7_predictions"][name] == prior["predictions"][BASELINE][name]
        assert saved["baseline7"][name] == summarize(y, saved["baseline7_predictions"][name])
        for i, seed in enumerate(seeds_for(name)):
            pred = np.array(ps[i])
            assert pred.shape == (120,) and set(pred) <= set(range(6))
            m = saved["summary"][name]["per_seed"][i]
            cm = confusion_matrix(y, pred, labels=range(6))
            assert cm.tolist() == m["confusion_matrix"]
            assert cm.sum(1).tolist() == [20] * 6 and int(cm.sum()) == 120
            assert m["correct"] == int(np.trace(cm))
            np.testing.assert_allclose(m["accuracy"], 100*np.trace(cm)/120, rtol=0, atol=1e-12)
            np.testing.assert_allclose(m["macro_f1"], 100*f1_score(y, pred, labels=range(6), average="macro", zero_division=0), rtol=0, atol=1e-12)
            seen = np.zeros(120, dtype=int)
            folds = [f for f in saved["folds"] if f["model"] == name and f["seed"] == seed]
            assert len(folds) == 2
            for f in folds:
                ref = source["results"]["LR9"]["folds"][f["number"]]
                tr, te = f["train"], f["test"]
                assert tr == ref["train"] and te == ref["test"] and len(tr) == len(te) == 60
                assert set(tr).isdisjoint(te)
                assert set(saved["subjects"][j] for j in tr).isdisjoint(saved["subjects"][j] for j in te)
                assert f["predictions"] == pred[te].tolist()
                assert f["params"] == expected_params(name, seed)
                if name != "M0":
                    scaler = StandardScaler().fit(x[tr])
                    np.testing.assert_array_equal(f["mean"], scaler.mean_)
                    np.testing.assert_array_equal(f["scale"], scaler.scale_)
                    assert f["scaler_fit_samples"] == 60
                if name == "SVM-RBF":
                    assert f["fit_status"] == 0 and f["params"]["gamma"] == 1/9
                if name in ("LR", "Linear-SVM"):
                    assert f["n_iter"] < f["params"]["max_iter"]
                assert f["serialization_predictions_equal"] is True
                seen[te] += 1
            assert seen.tolist() == [1]*120
    for path, sha in saved["inputs"].items():
        assert digest(ROOT/path) == sha
    for path, sha in plan["input_hashes"].items():
        assert saved["inputs"][path] == sha
    with (OUT / "local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == sum(len(seeds_for(n)) for n in MODELS)*120 == 2040
    assert len({(r["model"], r["seed"], r["index"]) for r in rows}) == len(rows)
    for row in rows:
        name, seed, i = row["model"], int(row["seed"]), int(row["index"])
        assert int(row["actual"]) == y[i]
        assert int(row["predicted"]) == saved["predictions"][name][list(seeds_for(name)).index(seed)][i]
    assert (OUT / "REPORT.md").read_text(encoding="utf-8") == report(saved)
    print("PASS: fixed2D4/five models, same120/LOSO/train-only scaler/parameters, 34 fits, OOF metrics/CSV/report/hashes; verification performs no fits")


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    verify_prior()
    source = read(SOURCE)
    prior = read(PRIOR / "local_private/results.json")
    paths = [SOURCE, BUNDLE/"samples.csv", BUNDLE/"bundle_info.json", PRIOR/"local_private/results.json",
             FACTORY, ROOT/"rf_experiment.py", ROOT/"lr_posture_demo.py", ROOT/"review_lr_features.py",
             ROOT/"bundle_pilot120.py", ROOT/"compare_pilot120_feature_sets.py",
             ROOT/"compare_pilot120_fixed_models.py", ROOT/"compare_six_feature_svm_knn.py",
             ROOT/"evaluate_new_pilot_lr6.py", ROOT/"compare_lr_f2_f5.py", ROOT/"compare_new_pilot_lr9.py",
             ROOT/"compare_pilot120_2d4.py"]
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    write(private/"PLAN.json", dict(scope="EXPLORATORY_USER_REQUESTED_FIXED_2D4", columns=list(COLUMNS),
          features=list(FEATURES), models=list(MODELS), new_fits=34, baseline=BASELINE,
          seeds={n:list(seeds_for(n)) for n in MODELS}, params={n:expected_params(n, 0) for n in MODELS},
          folds=source["results"]["LR9"]["folds"], input_hashes=inputs,
          support="unchanged H9 joint support and original120 eligibility; no reaggregation",
          hypothesis="F1/F3/F4/F5 only versus saved seven-feature results; no parameter or subset search"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))] = digest(private/"PLAN.json")
    x = np.array(source["matrix"])[:, COLUMNS]
    y = np.array(source["labels"])
    predictions, folds = {}, []
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        warnings.simplefilter("error", ConvergenceWarning)
        for name in MODELS:
            predictions[name] = []
            for seed in seeds_for(name):
                pred = np.full(120, -1, dtype=int)
                for number, ref in enumerate(source["results"]["LR9"]["folds"]):
                    tr, te = ref["train"], ref["test"]
                    scaler = StandardScaler().fit(x[tr]) if name != "M0" else None
                    train = scaler.transform(x[tr]) if scaler else x[tr]
                    test = scaler.transform(x[te]) if scaler else x[te]
                    model = factory(name, seed)
                    model.fit(train, y[tr])
                    pred[te] = model.predict(test)
                    restored = pickle.loads(pickle.dumps(model, protocol=5))
                    np.testing.assert_array_equal(restored.predict(test), pred[te])
                    details = dict(model=name, seed=seed, number=number, train=tr, test=te,
                                   predictions=pred[te].tolist(), params=expected_params(name, seed),
                                   serialization_predictions_equal=True)
                    if scaler:
                        assert model.get_params() == expected_params(name, seed)
                        details.update(mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                                       scaler_fit_samples=int(scaler.n_samples_seen_))
                    else:
                        assert (model.K, model.T, model.mf, model.sw, model.seed) == (6, 500, 2, None, seed)
                    if name == "SVM-RBF":
                        assert model.fit_status_ == 0
                        details["fit_status"] = int(model.fit_status_)
                    if name in ("LR", "Linear-SVM"):
                        details["n_iter"] = int(np.max(model.n_iter_))
                        assert details["n_iter"] < model.max_iter
                    folds.append(details)
                predictions[name].append(pred.tolist())
            print(name, "completed", flush=True)
    saved = dict(inputs=inputs, labels=source["labels"], subjects=source["subjects"], sample_keys=source["sample_keys"],
                 features=list(FEATURES), predictions=predictions, folds=folds, new_fits=len(folds),
                 summary={n:summarize(y, p) for n, p in predictions.items()},
                 baseline7_predictions=prior["predictions"][BASELINE], baseline7=prior["summary"][BASELINE],
                 warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in recorded)),
                 python=sys.version.split()[0], numpy=np.__version__, sklearn=sklearn.__version__)
    write(private/"results.json", saved)
    with (private/"predictions.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["model", "seed", "index", "actual", "predicted"])
        writer.writeheader()
        for name, ps in predictions.items():
            for seed, pred in zip(seeds_for(name), ps):
                writer.writerows(dict(model=name, seed=seed, index=i, actual=int(y[i]), predicted=v) for i, v in enumerate(pred))
    with (OUT/"REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    for name, result in saved["summary"].items():
        print(name, {k:result["mean"][k] for k in ("accuracy", "macro_f1")}, "recall", result["recall"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    verify() if parser.parse_args().verify else run()
