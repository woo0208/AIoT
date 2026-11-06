"""One authorized F2+F5 removal hypothesis, reusing three verified conditions.

python -X utf8 -B compare_lr_f2_f5.py
python -X utf8 -B compare_lr_f2_f5.py --verify   # no fits
Only this source and REPORT.md are intended for Git; local_private stays ignored.
"""
from collections import Counter
import argparse
import csv
import json
from pathlib import Path
import warnings

# Import first to retain the prior analysis's native-thread environment settings.
from review_lr_features import IDS, PRIVATE as PRIOR_PRIVATE, digest, read, score
from lr_posture_demo import DATA, FACTORY, ROOT, fixed_lr, pilot_data

import numpy as np
import sklearn
from sklearn.base import clone
from sklearn.metrics import confusion_matrix
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/LR_DROP_F2_F5_20261106"
PRIOR = PRIOR_PRIVATE / "results.json"
NEW = "B0-F2-F5"
CONDITIONS = {
    "B0": list(range(8)),
    "B0-F2": [0, 2, 3, 4, 5, 6, 7],
    "B0-F5": [0, 1, 2, 3, 5, 6, 7],
    NEW: [0, 2, 3, 5, 6, 7],
}


def changes(y, old, new):
    flows = Counter()
    counts = dict(correct_to_wrong=0, wrong_to_correct=0, wrong_to_wrong=0)
    for actual, a, b in zip(y, old, new):
        if a == b:
            continue
        category = "correct_to_wrong" if a == actual else (
            "wrong_to_correct" if b == actual else "wrong_to_wrong")
        counts[category] += 1
        flows[f"실제 P{actual}: P{a}→P{b}"] += 1
    return dict(**counts, changed=sum(counts.values()), flows=dict(sorted(flows.items())))


def report(saved):
    results = saved["results"]
    rows = ["# LR F2·F5 동시 제거 — 단일 가설 실험", "",
            "실험 ID: `EXPLR-LR-DROP-F2-F5-20261106`. 반복 사용한 2인·24구간의 탐색 결과다. "
            "일반화·통계적 유의성·공식 모델 선정 결과로 해석하지 않는다.", "",
            "가설: F2 제거의 P1 이득을 유지하면서 F5 제거의 P0 이득도 얻을 수 있는가? "
            "네 조건만 비교하며 새 특징·추가 조합 탐색·하이퍼파라미터 튜닝은 하지 않았다.", "",
            "## 고정 조건", "",
            "원래 H9 24×9 집계에서 F1~F8 열만 선택했다. 기존 H9 support/집계/라벨/표본 순서와 "
            "첫 P0 포함을 유지했다. 참가자당 12구간, 참가자×자세당 2구간, P0~P5 각각 전체 support=4다. "
            "개인 보정·제외·결측 채움·재집계가 없다.", "",
            "기존 `pilot_data()`/`fixed_lr()`/`score()` 재사용. LR C=1, L2(l1_ratio=0), lbfgs, "
            "tol=1e-4, max_iter=10000, intercept=True, class_weight=None, random_state=0. "
            "동일 참가자 LOSO 두 fold(학습12/시험12), StandardScaler는 각 학습 fold에서만 fit한다. "
            "두 fold의 24개 OOF를 pool한 Accuracy·고정6 Macro-F1·Recall이며 참가자별 지표 평균이 아니다.", "",
            "B0/B0−F2/B0−F5는 이전 검증된 결과를 재사용했다. 입력 hash·identity·라벨·설정·"
            "환경·fold·scaler·지표를 다시 확인했고 **새 fit은 F2+F5 제거 2회뿐**이다. "
            "이전 B0의 seed 0~4 예측은 동일했으며 이번도 기존 결정적 seed 0을 유지했다.", "",
            f"환경: NumPy {saved['numpy']}, scikit-learn {saved['sklearn']}, native thread 1개.", "",
            "## 전체 결과", "",
            "단위 %. P0=정상, P1=전방 머리, P2=뒤로 기대기, P3/P4=좌/우 기대기, P5=몸통 전방.", "",
            "|구성|입력|정답/24|Accuracy|Macro-F1|P0 Recall|P1 Recall|P2 Recall|P3 Recall|P4 Recall|P5 Recall|",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in results.items():
        m = result["metrics"]
        values = [m["accuracy"], m["macro_f1"], *m["recall"]]
        rows.append(f"|{name}|{','.join(result['features'])}|{sum(np.diag(m['cm']))}/24|"
                    + "|".join(f"{v:.2f}" for v in values) + "|")
    rows += ["", "## 오분류 변화", "",
             "각 행은 같은 24구간의 쌍별 비교다. 오답→다른 오답도 예측 변경으로 구분한다.", "",
             "|비교 기준|구성|예측 변경|오답→정답|정답→오답|오답→다른 오답|변경 유형·건수|",
             "|---|---|---:|---:|---:|---:|---|"]
    for reference in ("B0", "B0-F2"):
        for name, result in results.items():
            c = changes(saved["labels"], results[reference]["predictions"], result["predictions"])
            flows = "; ".join(f"{k} {v}건" for k, v in c["flows"].items()) or "없음"
            rows.append(f"|{reference}|{name}|{c['changed']}|{c['wrong_to_correct']}|"
                        f"{c['correct_to_wrong']}|{c['wrong_to_wrong']}|{flows}|")
    a, b = results["B0-F2"]["metrics"], results[NEW]["metrics"]
    rows += ["", "## 해석", "",
             f"F2 단독 제거 대비 동시 제거의 변화: Accuracy {b['accuracy']-a['accuracy']:+.2f}pp, "
             f"Macro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp, "
             f"P0 Recall {b['recall'][0]-a['recall'][0]:+.2f}pp, "
             f"P1 Recall {b['recall'][1]-a['recall'][1]:+.2f}pp. "
             "P0/P1 각각 4개 구간이므로 Recall 25pp는 한 구간이다. "
             "단독 제거 효과를 합산해 동시 제거 결과를 예측할 수 없으며 실제 쌍별 예측을 기준으로 판단한다.", "",
             "## 혼동행렬", "", "행=실제 P0~P5, 열=예측 P0~P5, 정수 건수다."]
    for name, result in results.items():
        rows += ["", f"### {name}", "", "```text", "     P0 P1 P2 P3 P4 P5"]
        rows += [f"P{i}   " + "  ".join(map(str, row)) for i, row in enumerate(result["metrics"]["cm"])]
        rows += ["```"]
    rows += ["", "## 검증·보존", "",
             "입력 불변·이전3조건 정합성·새2fold 분리·train-only scaler·고정 LR·수렴·표본당 OOF 1회·"
             "저장 예측으로 지표/변화 재계산·CSV/보고 표 일치 확인을 수행했다. 전체 회귀 테스트는 실행하지 않았다.", "",
             "공개 대상은 `compare_lr_f2_f5.py`와 이 보고서뿐이다. "
             "참가자별 예측·sample identity·fold/scaler·참가자별 혼동행렬·입력 hash·설정은 "
             "`local_private/results.json`, 구간별 전체 예측표는 `local_private/predictions.csv`에만 둔다. "
             "기존 자료/결과는 덮어쓰지 않았다.", "",
             "기존 B0/실시간 실행 모델, 공식 8조합, B6, IRB HOLD, Patch 8 실행 보류는 유지한다. "
             "촬영·원본 영상 열람·새 특징·자동 선정·후속 조합 실험·Push는 하지 않았다.", "",
             "실행: `python -X utf8 -B compare_lr_f2_f5.py`. "
             "저장 검증만: `python -X utf8 -B compare_lr_f2_f5.py --verify` (fit 없음).", ""]
    return "\n".join(rows)


def validate(saved):
    data, base, y = pilot_data()
    assert saved["labels"] == y.tolist() and saved["sample_keys"] == data["sample_keys"]
    assert saved["subjects"] == data["subjects"] and saved["lr_params"] == fixed_lr().get_params()
    assert list(saved["results"]) == list(CONDITIONS) and saved["new_fit_count"] == 2
    people = np.asarray(data["subjects"])
    for name, columns in CONDITIONS.items():
        result = saved["results"][name]
        assert result["features"] == [IDS[j] for j in columns]
        assert score(y, result["predictions"]) == result["metrics"]
        seen = np.zeros(24, dtype=int)
        assert len(result["folds"]) == 2
        for fold in result["folds"]:
            train, test = np.asarray(fold["train"]), np.asarray(fold["test"])
            assert len(train) == len(test) == 12 and not set(train) & set(test)
            assert len(set(people[train])) == len(set(people[test])) == 1
            assert people[train][0] != people[test][0]
            assert set(train) | set(test) == set(range(24))
            scaler = StandardScaler().fit(base[train][:, columns])
            np.testing.assert_allclose(fold["scaler_mean"], scaler.mean_, rtol=0, atol=1e-14)
            np.testing.assert_allclose(fold["scaler_scale"], scaler.scale_, rtol=0, atol=1e-14)
            seen[test] += 1
        assert seen.tolist() == [1] * 24
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha


def verify():
    saved = read(OUT / "local_private/results.json")
    validate(saved)
    assert report(saved) in (OUT / "REPORT.md").read_text(encoding="utf-8")
    with (OUT / "local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        actual = list(csv.DictReader(stream))
    assert len(actual) == 96
    for row, expected in zip(actual, prediction_rows(saved)):
        assert row == {key: str(value) for key, value in expected.items()}
    print("PASS: four conditions, fixed inputs/settings/LOSO/scalers, metrics, OOF CSV and report; no LR fits")


def prediction_rows(saved):
    for name, result in saved["results"].items():
        for i, pred in enumerate(result["predictions"]):
            yield dict(condition=name, subject=saved["subjects"][i],
                       sample_key=json.dumps(saved["sample_keys"][i]),
                       actual=saved["labels"][i], predicted=pred)


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    inputs = (DATA, FACTORY, PRIOR, ROOT / "review_lr_features.py",
              ROOT / "lr_posture_demo.py", Path(__file__).resolve())
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    prior = read(PRIOR)
    template = fixed_lr()
    assert prior["lr_params"] == template.get_params()
    assert prior["numpy"] == np.__version__ and prior["sklearn"] == sklearn.__version__
    for path, sha in prior["inputs"].items():
        assert digest(ROOT / path) == sha
    results = {name: prior["results"][name] for name in CONDITIONS if name != NEW}
    saved = dict(labels=prior["labels"], sample_keys=prior["sample_keys"], subjects=prior["subjects"],
                 lr_params=template.get_params(), numpy=np.__version__, sklearn=sklearn.__version__,
                 inputs=hashes, new_fit_count=2, results=results)
    data, base, y = pilot_data()
    assert np.array_equal(np.asarray(prior["matrix"])[:, :8], base)
    matrix = base[:, CONDITIONS[NEW]]
    pred, folds = np.full(24, -1, dtype=int), []
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error")
        for reference_fold in results["B0-F2"]["folds"]:
            train, test = reference_fold["train"], reference_fold["test"]
            scaler = StandardScaler().fit(matrix[train])
            assert int(scaler.n_samples_seen_) == 12
            model = clone(template)
            assert model.get_params() == template.get_params()
            model.fit(scaler.transform(matrix[train]), y[train])
            assert np.all(model.n_iter_ < model.max_iter)
            pred[test] = model.predict(scaler.transform(matrix[test]))
            folds.append(dict(train=train, test=test, scaler_mean=scaler.mean_.tolist(),
                              scaler_scale=scaler.scale_.tolist(), n_iter=model.n_iter_.tolist()))
    results[NEW] = dict(features=[IDS[j] for j in CONDITIONS[NEW]], predictions=pred.tolist(),
                        metrics=score(y, pred), folds=folds)
    validate(saved)
    people = np.asarray(saved["subjects"])
    saved["participant_confusion_matrices"] = {
        name: {person: confusion_matrix(y[people == person], np.asarray(result["predictions"])[people == person],
                                       labels=range(6)).tolist() for person in sorted(set(people))}
        for name, result in results.items()}
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    with (private / "results.json").open("x", encoding="utf-8") as stream:
        json.dump(saved, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    with (private / "predictions.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["condition", "subject", "sample_key", "actual", "predicted"])
        writer.writeheader()
        writer.writerows(prediction_rows(saved))
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    for name, result in results.items():
        print(name, result["metrics"])
    print("New LR fits: 2; historical conditions reused: 3; no further combinations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    verify() if args.verify else run()
