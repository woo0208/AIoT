"""Three fixed existing classifiers on the selected six pilot features.

python -X utf8 -B compare_six_feature_svm_knn.py
Append --verify to check saved outputs without training.
Participant derivatives in local_private/ must remain outside Git.
"""
import argparse
import ast
from collections import Counter
import csv
import json
from pathlib import Path
import warnings

from review_lr_features import digest, read, score
from lr_posture_demo import DATA, FACTORY, ROOT, pilot_data
from compare_six_feature_rf import OUT as RF_OUT, COLUMNS, FEATURES, summarize
from compare_lr_f2_f5 import OUT as LR_OUT, NEW as LR_CONDITION

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC, SVC
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/SIX_FEATURE_SVM_KNN_20261106"
RF_SOURCE = RF_OUT / "local_private/results.json"
LR_SOURCE = LR_OUT / "local_private/results.json"
HISTORY = DATA.parent / "results.json"
NAMES = ("SVM-RBF", "Linear-SVM", "KNN")
SEEDS = (0, 1, 2, 3, 4)


def factory(name, seed):
    node = next(n for n in ast.parse(FACTORY.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == "make_model")
    scope = dict(SVC=SVC, LinearSVC=LinearSVC, KNeighborsClassifier=KNeighborsClassifier)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(FACTORY), "exec"), scope)
    return scope["make_model"](name, seed)


def rows(saved):
    for name, predictions in saved["predictions"].items():
        for seed, pred in enumerate(predictions):
            for i, value in enumerate(pred):
                yield dict(model=name, seed=seed, subject=saved["subjects"][i],
                           sample_key=json.dumps(saved["sample_keys"][i]), actual=saved["labels"][i], predicted=value)


def report(saved):
    lines = ["# 동일6특징 SVM-RBF·Linear SVM·KNN 추가 비교", "",
             "실험 ID: `EXPLR-SIX-FEATURE-SVM-KNN-20261106`. 반복 사용한 2인·24구간의 6-class 탐색 비교다. "
             "독립 검증·통계적 유의성·새 참가자 일반화 결과가 아니다.", "",
             "## 고정 조건", "",
             "입력 **F1,F3,F4,F6,F7,F8**, 원래 H9 지원 프레임·집계·24구간·라벨·순서·첫 P0 포함을 유지했다. "
             "2인 LOSO 각 학습12/시험12, 참가자×자세당 2구간, 자세별 전체 support=4다. "
             "새 특징·추가 조합·보정·채움·재집계·튜닝·촬영·원본 영상 열람은 없다.", "",
             "기존 compare_fixed.py의 make_model 함수 AST를 직접 재사용했다. "
             "SVM-RBF: C=1, gamma=1/9, tol=1e-3, probability=False. "
             "Linear SVM: C=1, L2/squared_hinge, dual=False, OVR, tol=1e-4, max_iter=10000. "
             "KNN: k=3, uniform, brute, Minkowski p=2. 나머지 설정도 원래 생성기와 같다. "
             "특징이 6개여도 gamma를 1/6 또는 scale로 바꾸지 않았다.", "",
             "세 모델은 각 학습 fold에서만 StandardScaler fit 후 시험에는 transform만 적용했다. "
             "학습 mean/scale은 이전 동일6 LR 통계와 일치했다. seeds=(0,1,2,3,4), "
             "신규 학습은 3모델×5 seeds×2fold=30회다. LR/RF는 검증된 저장 결과만 재사용했다.", "",
             f"환경: NumPy {saved['numpy']}, scikit-learn {saved['sklearn']}, native thread 1. "
             "수렴 경고는 오류로 처리한다. 기존 설정에 대한 API 폐기 예고는 설정을 바꾸지 않고 기록했다.", "",
             "## 동일6특징 전체 비교", "",
             "단위 %. RF/추가3모델은 각 seed의 24 OOF 지표를 계산한 뒤 5 seeds 평균이다. "
             "LR은 기존 결정적 seed0 한 결과다. seed 반복은 독립 참가자/구간이 아니다. P0~P5는 Recall이다.", "",
             "|모델|Accuracy|Macro-F1|P0|P1|P2|P3|P4|P5|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in saved["results"].items():
        lines.append(f"|{name}|" + "|".join(f"{v:.2f}" for v in
                     [result["accuracy"], result["macro_f1"], *result["recall"]]) + "|")
    lines += ["", "## 추가3모델 seed별 결과", "",
              "|모델|seed|Accuracy|Macro-F1|P0|P1|P2|P3|P4|P5|",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in NAMES:
        for seed, metric in enumerate(saved["results"][name]["per_seed"]):
            lines.append(f"|{name}|{seed}|" + "|".join(f"{v:.2f}" for v in
                         [metric["accuracy"], metric["macro_f1"], *metric["recall"]]) + "|")
    lines += ["", "## LR 대비 예측 변화", "",
              "건수는 seed당 평균이다. 오답→다른 오답도 구분한다.", "",
              "|모델|오답→정답|정답→오답|오답→다른 오답|",
              "|---|---:|---:|---:|"]
    y, lr = saved["labels"], saved["predictions"]["LR"][0]
    for name in NAMES:
        counts = [[sum(a != t and b == t for t, a, b in zip(y, lr, pred)),
                   sum(a == t and b != t for t, a, b in zip(y, lr, pred)),
                   sum(a != t and b != t and a != b for t, a, b in zip(y, lr, pred))]
                  for pred in saved["predictions"][name]]
        lines.append(f"|{name}|" + "|".join(f"{v:.2f}" for v in np.mean(counts, axis=0)) + "|")
    lines += ["", "### 오류 유형 (seed당 평균 건수)", "", "|모델|실제→오답|건수|", "|---|---|---:|"]
    for name in ("LR", *NAMES):
        predictions = saved["predictions"][name]
        flows = Counter((t, p) for pred in predictions for t, p in zip(y, pred) if t != p)
        if not flows:
            lines.append(f"|{name}|없음|0.00|")
        for (t, p), count in sorted(flows.items()):
            lines.append(f"|{name}|P{t}→P{p}|{count/len(predictions):.2f}|")
    lines += ["", "## 기존9특징 대비 추가3모델", "",
              "F2/F5/F9가 함께 제거된 비교다. 개별 특징 효과로 분해하지 않는다. 과거 결과는 재학습하지 않았다.", "",
              "|모델|이전 Accuracy|현재 Accuracy|ΔAcc pp|이전 Macro-F1|현재 Macro-F1|ΔF1 pp|",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name in NAMES:
        a, b = saved["historical"][name], saved["results"][name]
        lines.append(f"|{name}|{a['accuracy']:.2f}|{b['accuracy']:.2f}|{b['accuracy']-a['accuracy']:+.2f}|"
                     f"{a['macro_f1']:.2f}|{b['macro_f1']:.2f}|{b['macro_f1']-a['macro_f1']:+.2f}|")
    lines += ["", "## 검증·보존", "",
              "입력 hash/identity/라벨·기존 결과 정합성·fold 분리·train-only scaler·생성기 설정·수렴·"
              "표본당 OOF 1회·입력 불변·저장 예측/지표/CSV/보고 표 일치를 확인했다. 전체 회귀 테스트는 하지 않았다.", "",
              f"API 등 비수렴 경고 기록: {sum(saved['warnings'].values())}건. 상세 메시지와 건수는 로컬 JSON에 보존한다.", "",
              "공개 요약은 이 보고서, 실행 코드는 compare_six_feature_svm_knn.py다. "
              "참가자별 identity/예측·fold scaler·설정·입력 hash·seed별 혼동행렬은 local_private/results.json, "
              "전체 OOF는 local_private/predictions.csv에만 보관한다. 기존 파일과 모델은 덮어쓰지 않았다.", "",
              "공식8조합·B6·IRB HOLD·Patch8 실행 보류·실시간 모델은 유지한다. 실행속도/메모리/CPU는 측정하지 않았다. "
              "이 결과만으로 최종 모델을 자동 선정하지 않는다.", "",
              "실행: `python -X utf8 -B compare_six_feature_svm_knn.py`. "
              "저장 검증만: 같은 명령에 `--verify` (모델 학습 없음).", ""]
    return "\n".join(lines)


def verify():
    saved = read(OUT / "local_private/results.json")
    data, base, y = pilot_data()
    for key in ("labels", "subjects", "sample_keys"):
        assert saved[key] == data[key]
    assert saved["features"] == FEATURES
    for name, predictions in saved["predictions"].items():
        assert len(predictions) == (1 if name == "LR" else 5)
        assert summarize(y, predictions) == saved["results"][name]
    assert len(saved["folds"]) == 10
    for fold in saved["folds"]:
        tr, te = fold["train"], fold["test"]
        assert len(tr) == len(te) == 12 and not set(tr) & set(te)
        assert set(tr) | set(te) == set(range(24))
        assert set(data["subjects"][i] for i in tr).isdisjoint(data["subjects"][i] for i in te)
        np.testing.assert_allclose(fold["mean"], base[tr][:, COLUMNS].mean(0), rtol=0, atol=1e-14)
        np.testing.assert_allclose(fold["scale"], base[tr][:, COLUMNS].std(0), rtol=0, atol=1e-14)
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    assert report(saved) in (OUT / "REPORT.md").read_text(encoding="utf-8")
    with (OUT / "local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        actual = list(csv.DictReader(stream))
    assert len(actual) == 744
    for row, expected in zip(actual, rows(saved)):
        assert row == {k: str(v) for k, v in expected.items()}
    print("PASS: inputs/LOSO/scalers/metrics/OOF CSV/report; no model training")


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    inputs = (DATA, FACTORY, RF_SOURCE, LR_SOURCE, HISTORY, ROOT / "compare_six_feature_rf.py",
              ROOT / "lr_posture_demo.py", ROOT / "review_lr_features.py", Path(__file__).resolve())
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    prior, lr, historical = read(RF_SOURCE), read(LR_SOURCE), read(HISTORY)
    for saved in (prior, lr):
        for path, sha in saved["inputs"].items():
            assert digest(ROOT / path) == sha
    data, base, y = pilot_data()
    for key in ("labels", "subjects", "sample_keys"):
        assert prior[key] == lr[key] == data[key]
    assert prior["features"] == lr["results"][LR_CONDITION]["features"] == FEATURES
    assert historical["feature_order"] == data["feature_order"] and historical["class_order"] == data["class_order"]
    assert historical["sample_count"] == 24 and historical["seeds"] == list(SEEDS)
    matrix = base[:, COLUMNS]
    predictions = {n: prior["predictions"][n] for n in ("LR", "M0", "M1", "M2(λ=0.5)")}
    for name, values in predictions.items():
        assert summarize(y, values) == prior["results"][name]
    templates = {n: factory(n, 0).get_params() for n in NAMES}
    folds = []
    added = {n: [] for n in NAMES}
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        warnings.simplefilter("error", ConvergenceWarning)
        for seed in SEEDS:
            current = {n: np.full(24, -1, dtype=int) for n in NAMES}
            seen = np.zeros(24, dtype=int)
            for prior_fold in lr["results"][LR_CONDITION]["folds"]:
                tr, te = prior_fold["train"], prior_fold["test"]
                assert np.bincount(y[tr], minlength=6).tolist() == [2] * 6
                scaler = StandardScaler().fit(matrix[tr])
                assert int(scaler.n_samples_seen_) == 12
                np.testing.assert_allclose(scaler.mean_, prior_fold["scaler_mean"], rtol=0, atol=1e-14)
                np.testing.assert_allclose(scaler.scale_, prior_fold["scaler_scale"], rtol=0, atol=1e-14)
                train, test = scaler.transform(matrix[tr]), scaler.transform(matrix[te])
                iterations = {}
                for name in NAMES:
                    model = factory(name, seed)
                    expected = dict(templates[name])
                    if "random_state" in expected:
                        expected["random_state"] = seed
                    assert model.get_params() == expected
                    model.fit(train, y[tr])
                    if name == "SVM-RBF":
                        assert model.fit_status_ == 0
                    if name == "Linear-SVM":
                        assert model.n_iter_ < model.max_iter
                    current[name][te] = model.predict(test)
                    iterations[name] = np.asarray(getattr(model, "n_iter_", [])).tolist()
                folds.append(dict(seed=seed, train=tr, test=te, mean=scaler.mean_.tolist(),
                                  scale=scaler.scale_.tolist(), iterations=iterations))
                seen[te] += 1
            assert seen.tolist() == [1] * 24
            for name in NAMES:
                added[name].append(current[name].tolist())
    predictions.update(added)
    old = {n: historical["results"][n]["predictions_by_seed"] for n in NAMES}
    saved = dict(inputs=hashes, features=FEATURES, labels=y.tolist(), subjects=data["subjects"],
                 sample_keys=data["sample_keys"], params=templates, folds=folds, predictions=predictions,
                 results={n: summarize(y, p) for n, p in predictions.items()}, historical_predictions=old,
                 historical={n: summarize(y, p) for n, p in old.items()},
                 numpy=np.__version__, sklearn=sklearn.__version__,
                 warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in recorded_warnings)))
    for path, sha in hashes.items():
        assert digest(ROOT / path) == sha
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    with (private / "results.json").open("x", encoding="utf-8") as stream:
        json.dump(saved, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with (private / "predictions.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["model", "seed", "subject", "sample_key", "actual", "predicted"])
        writer.writeheader()
        writer.writerows(rows(saved))
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    for name in NAMES:
        print(name, {k: saved["results"][name][k] for k in ("accuracy", "macro_f1", "recall")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    verify() if parser.parse_args().verify else run()
