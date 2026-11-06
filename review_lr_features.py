"""Fixed B0 leave-one-feature-out review; no candidate implementation or search.

Run from the repository: python -X utf8 -B review_lr_features.py
Verify saved arithmetic/report only: append --verify (no fits).
Participant derivatives are exclusively written under ignored local_private/.
Requires the original access-controlled pilot and saved reference artifacts.
"""
import os
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
import sklearn
from sklearn.base import clone
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from lr_posture_demo import DATA, FACTORY, ROOT, fixed_lr, pilot_data

OUT = ROOT / "analysis/FEATURE_REVIEW_20261106"
PRIVATE = OUT / "local_private"
REFERENCE = ROOT / "analysis/lr_feature_comparison_20261029_1a6c42/results.json"
IDS = [f"F{i}" for i in range(1, 10)]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(y, pred):
    cm = confusion_matrix(y, pred, labels=range(6))
    assert cm.sum() == 24 and cm.sum(1).tolist() == [4] * 6
    return dict(accuracy=100 * float(np.trace(cm)) / 24,
                macro_f1=100 * float(f1_score(y, pred, labels=range(6),
                                            average="macro", zero_division=0)),
                recall=(100 * np.diag(cm) / cm.sum(1)).tolist(), cm=cm.tolist())


def table(results):
    base = results["B0"]["metrics"]
    rows = ["|구성|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|ΔAccuracy pp|ΔMacro-F1 pp|ΔP0 pp|ΔP1 pp|",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in results.items():
        m = result["metrics"]
        values = [m["accuracy"], m["macro_f1"], *m["recall"][:2]]
        differences = [m["accuracy"] - base["accuracy"], m["macro_f1"] - base["macro_f1"],
                       m["recall"][0] - base["recall"][0], m["recall"][1] - base["recall"][1]]
        rows.append("|" + name + "|" + "|".join(f"{v:.2f}" for v in values)
                    + "|" + "|".join(f"{v:+.2f}" for v in differences) + "|")
    return "\n".join(rows)


def verify():
    saved = read(PRIVATE / "results.json")
    data, _, y = pilot_data()
    assert saved["labels"] == y.tolist() and saved["sample_keys"] == data["sample_keys"]
    assert saved["subjects"] == data["subjects"]
    for name, result in saved["results"].items():
        assert score(y, result["predictions"]) == result["metrics"]
        expected = IDS[:8] if name == "B0" else [f for f in IDS[:8] if f != name[3:]]
        assert result["features"] == expected
        assert len(result["folds"]) == 2
        for fold in result["folds"]:
            train, test = fold["train"], fold["test"]
            assert len(train) == len(test) == 12 and not set(train) & set(test)
            assert set(train) | set(test) == set(range(24))
            assert {data["subjects"][i] for i in train} != {data["subjects"][i] for i in test}
    assert table(saved["results"]) in (OUT / "FEATURE_IMPROVEMENT_REVIEW.md").read_text(encoding="utf-8")
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    print("PASS: saved metrics, feature deletion, labels, LOSO and report table; no fitting")


def run():
    inputs = (DATA, FACTORY, REFERENCE, ROOT / "lr_posture_demo.py", Path(__file__).resolve())
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    data, base, y = pilot_data()
    x = np.asarray(data["matrix"], dtype=float)
    subjects = np.asarray(data["subjects"])
    prior = read(REFERENCE)["results"]["B"]["predictions_by_seed"]
    # Historical seeds 0..4 are identical under the deterministic lbfgs factory.
    expected = prior["0"] if isinstance(prior, dict) else prior[0]
    assert all(np.array_equal(v, expected) for v in (prior.values() if isinstance(prior, dict) else prior))
    template = fixed_lr()
    results = {}
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error")
        for drop in (None, *range(8)):
            columns = [j for j in range(8) if j != drop]
            matrix = base[:, columns]
            pred, seen, folds = np.full(24, -1, dtype=int), np.zeros(24, dtype=int), []
            for heldout in ("P02", "P01"):
                train, test = np.flatnonzero(subjects != heldout), np.flatnonzero(subjects == heldout)
                assert len(train) == len(test) == 12 and not set(train) & set(test)
                assert np.bincount(y[train], minlength=6).tolist() == [2] * 6
                scaler = StandardScaler().fit(matrix[train])
                assert int(scaler.n_samples_seen_) == 12
                np.testing.assert_allclose(scaler.mean_, matrix[train].mean(0), rtol=0, atol=1e-14)
                model = clone(template)
                assert model.get_params() == template.get_params()
                model.fit(scaler.transform(matrix[train]), y[train])
                assert np.all(model.n_iter_ < model.max_iter)
                pred[test] = model.predict(scaler.transform(matrix[test]))
                seen[test] += 1
                folds.append(dict(train=train.tolist(), test=test.tolist(),
                                  scaler_mean=scaler.mean_.tolist(), scaler_scale=scaler.scale_.tolist()))
            assert seen.tolist() == [1] * 24
            name = "B0" if drop is None else f"B0-F{drop + 1}"
            results[name] = dict(features=[IDS[j] for j in columns], predictions=pred.tolist(),
                                 metrics=score(y, pred), folds=folds)
            if drop is None:
                np.testing.assert_array_equal(pred, expected)
    details = {}
    for j, name in enumerate(IDS):
        values = {}
        for scope, mask in [("pooled", np.ones(24, dtype=bool)),
                            *((p, subjects == p) for p in sorted(set(subjects)))]:
            a, b = x[mask & (y == 0), j], x[mask & (y == 1), j]
            lo, hi = max(a.min(), b.min()), min(a.max(), b.max())
            values[scope] = dict(p0_range=[float(a.min()), float(a.max())],
                                 p1_range=[float(b.min()), float(b.max())],
                                 overlap=[float(lo), float(hi)] if lo <= hi else None,
                                 p0_median=float(np.median(a)), p1_median=float(np.median(b)),
                                 delta=float(np.median(b) - np.median(a)))
        values["p0_between_subject_delta"] = values["P02"]["p0_median"] - values["P01"]["p0_median"]
        details[name] = values
    correlations = {}
    for scope, mask in [("pooled24", np.ones(24, dtype=bool)), ("p0p1", y < 2),
                        *((p, subjects == p) for p in sorted(set(subjects))),
                        *((p + "_p0p1", (subjects == p) & (y < 2)) for p in sorted(set(subjects)))]:
        correlations[scope] = np.corrcoef(x[mask].T).tolist()
    errors = []
    for i, pred in enumerate(results["B0"]["predictions"]):
        if pred == y[i]:
            continue
        train = subjects != subjects[i]
        errors.append(dict(index=i, subject=str(subjects[i]), sample_key=data["sample_keys"][i],
                           actual=int(y[i]), predicted=pred, features=x[i].tolist(),
                           training_actual_ranges=np.column_stack((x[train & (y == y[i])].min(0),
                                                                   x[train & (y == y[i])].max(0))).tolist(),
                           training_predicted_ranges=np.column_stack((x[train & (y == pred)].min(0),
                                                                      x[train & (y == pred)].max(0))).tolist()))
    payload = dict(scope="LOCAL_PRIVATE_EXPLORATORY", inputs=hashes, labels=y.tolist(),
                   sample_keys=data["sample_keys"], subjects=data["subjects"], matrix=x.tolist(),
                   lr_params=template.get_params(), sklearn=sklearn.__version__, numpy=np.__version__,
                   fit_count=18, results=results, distributions=details, correlations=correlations, errors=errors)
    assert hashes == {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    OUT.mkdir(exist_ok=True)
    PRIVATE.mkdir(exist_ok=False)
    with (PRIVATE / "results.json").open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    rows = ["# LOCAL PRIVATE — 참가자 특징·범위·예측·파생값 (Git 제외)", "",
            "각 참가자×클래스 n=2; pooled 클래스 n=4. 구간 집계값의 관측 min/max와 중앙값이며 모집단 구간이 아니다.", "",
            "|특징|범위 집단|P0 min/max|P1 min/max|겹침|P0 중앙값|P1−P0 중앙값|", "|---|---|---|---|---|---|---|"]
    for name, scopes in details.items():
        for scope in ("pooled", "P01", "P02"):
            v = scopes[scope]
            rows.append(f"|{name}|{scope}|{v['p0_range']}|{v['p1_range']}|{v['overlap']}|{v['p0_median']:.6g}|{v['delta']:+.6g}|")
        rows.append(f"\n{name}: 참가자간 P0 중앙값차(P02−P01)={scopes['p0_between_subject_delta']:+.6g}\n")
    rows += ["", "오분류 3구간의 F1~F9 전체값·학습 실제/오답 클래스 범위, 24개 OOF 예측 및 6개 범위별 전체 9×9 상관행렬은 results.json에 저장했다."]
    with (PRIVATE / "DETAILS.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(rows) + "\n")
    print(table(results))
    print("PASS: B0 exact saved OOF reproduction; 18 fixed fits; train-only scaler; immutable inputs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    verify() if args.verify else run()
