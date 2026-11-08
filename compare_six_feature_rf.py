"""Fixed six-column RF M0/M1/M2 pilot comparison, with saved LR reference.

Run: python -X utf8 -B compare_six_feature_rf.py
Check saved results without training: append --verify.
Only this code and REPORT.md are public; participant derivatives stay private.
"""
import argparse
import ast
from collections import Counter
import csv
import json
from pathlib import Path

from review_lr_features import digest, read, score  # prior single-thread setup
from lr_posture_demo import DATA, ROOT, fixed_lr, pilot_data
from compare_lr_f2_f5 import CONDITIONS, NEW, OUT as LR_OUT

import numpy as np
import rf_experiment as rf
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/SIX_FEATURE_RF_LR_20261106"
LR_SOURCE = LR_OUT / "local_private/results.json"
HISTORY = ROOT / "analysis/h9/pilot_20261026/H9_feature_ablation_results_20261026.json"
SNAPSHOT = DATA.parent / "source/rf_experiment.py"
NAMES = ("M0", "M1", "M2(λ=0.5)")
COLUMNS = CONDITIONS[NEW]
FEATURES = [f"F{j+1}" for j in COLUMNS]


def summarize(y, predictions):
    metrics = [score(y, p) for p in predictions]
    return dict(per_seed=metrics,
                accuracy=float(np.mean([m["accuracy"] for m in metrics])),
                macro_f1=float(np.mean([m["macro_f1"] for m in metrics])),
                accuracy_sd=float(np.std([m["accuracy"] for m in metrics])),
                macro_f1_sd=float(np.std([m["macro_f1"] for m in metrics])),
                recall=np.mean([m["recall"] for m in metrics], axis=0).tolist(),
                mean_cm=np.mean([m["cm"] for m in metrics], axis=0).tolist())


def report(saved):
    rows = ["# 6특징 RF M0·M1·M2와 LR 비교", "",
            "실험 ID: `EXPLR-SIX-FEATURE-RF-LR-20261106`. 기존 2명·24구간·6-class 탐색 자료의 재사용이다. "
            "일반화·유의성·독립 검증·공식 모델 선정 결과가 아니다.", "",
            "입력은 **F1,F3,F4,F6,F7,F8**이다. 원래 H9 공통 support/집계/24구간/라벨/순서를 보존하고 열만 선택했다. "
            "참가자당 12구간, 자세별 전체 4구간이며 첫 P0도 유지한다. 촬영·원본 영상 열람·보정·채움·튜닝·추가 조합은 없다.", "",
            "## 평가 조건", "",
            "기존 `rf_experiment.fit_models`를 그대로 호출했다. 6-class, 500 trees, max_features=2, "
            "seeds=(0,1,2,3,4), M2 λ=0.5, 각 fold 학습12/시험12의 동일 참가자 LOSO다. "
            "RF는 과거와 같이 추가 표준화 없이 원래 특징값을 사용한다.", "",
            "M0의 학습 fold MDI 순위로만 기존 p=6 rank weights (0.30,0.20,0.15,0.15,0.15,0.05)를 배정한다. "
            "동점은 현재 열 순서다. M1은 입력에 w를 곱한 뒤 일반 RF, M2는 분할 점수에 "
            "`(1−λ)+λ·w/mean(w)`를 곱한다. 시험 자료로 순위·가중치를 정하지 않는다.", "",
            "새 RF는 5 seeds×2 folds×3모델=30 forest fits다. LR 6특징 결과는 이전 고정 LR·train-only scaler "
            "결과를 재사용하고 재학습하지 않았다. 과거 H9 RF도 저장 예측을 재사용했다. "
            "RF 핵심 Tree/Forest/rank_weights/fit_models AST는 과거 소스 snapshot과 같음을 확인했다.", "",
            "RF 지표는 각 seed의 24 OOF로 계산한 뒤 5개를 평균했다. Macro-F1은 평균 혼동행렬에서 계산하지 않는다. "
            "LR은 결정적 seed 0 한 결과이며 5번 독립 실행한 것으로 세지 않는다. seed 반복도 새 참가자가 아니다.", "",
            "## 동일 6특징 결과", "", "단위 %, 괄호는 seed SD(ddof=0). P0~P5 열은 Recall이다.", "",
            "|모델|Accuracy (SD)|Macro-F1 (SD)|P0|P1|P2|P3|P4|P5|",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r in saved["results"].items():
        rows.append(f"|{name}|{r['accuracy']:.2f} ({r['accuracy_sd']:.2f})|"
                    f"{r['macro_f1']:.2f} ({r['macro_f1_sd']:.2f})|"
                    + "|".join(f"{v:.2f}" for v in r["recall"]) + "|")
    rows += ["", "## 이전 H9 RF 대비", "",
             "H9 9열→현재6열은 F2/F5뿐 아니라 F9도 제거한 비교다. 개별 특징 효과로 분해하지 않는다. "
             "p=9→6에서 rank 정책·후보 특징 선택확률·트리 난수 경로도 달라진다.", "",
             "|모델|이전 H9 Acc|이전 H9 F1|ΔAcc pp|ΔF1 pp|이전→현재 P0|이전→현재 P1|",
             "|---|---:|---:|---:|---:|---|---|"]
    for name in NAMES:
        old, new = saved["historical"][name], saved["results"][name]
        rows.append(f"|{name}|{old['accuracy']:.2f}|{old['macro_f1']:.2f}|"
                    f"{new['accuracy']-old['accuracy']:+.2f}|{new['macro_f1']-old['macro_f1']:+.2f}|"
                    f"{old['recall'][0]:.2f}→{new['recall'][0]:.2f}|{old['recall'][1]:.2f}→{new['recall'][1]:.2f}|")
    rows += ["", "## 오류 변화", "",
             "각 count는 seed당 평균이며 소수일 수 있다. LR 비교는 동일 LR 예측을 각 RF seed와 대조한다.", "",
             "|기준|모델|오답→정답|정답→오답|오답→다른 오답|",
             "|---|---|---:|---:|---:|"]
    lr = saved["predictions"]["LR"][0]
    y = saved["labels"]
    for ref in ("기존 H9 RF", "동일6 LR"):
        for name in NAMES:
            counts = []
            for seed, pred in enumerate(saved["predictions"][name]):
                old = saved["historical_predictions"][name][seed] if ref == "기존 H9 RF" else lr
                counts.append([sum(a != t and b == t for t, a, b in zip(y, old, pred)),
                               sum(a == t and b != t for t, a, b in zip(y, old, pred)),
                               sum(a != t and b != t and a != b for t, a, b in zip(y, old, pred))])
            rows.append(f"|{ref}|{name}|" + "|".join(f"{v:.2f}" for v in np.mean(counts, axis=0)) + "|")
    rows += ["", "### 현재 오류 유형 (seed당 평균 건수)", "",
             "|모델|실제→오답|건수|", "|---|---|---:|"]
    for name, predictions in saved["predictions"].items():
        flows = Counter((t, p) for pred in predictions for t, p in zip(y, pred) if t != p)
        for (t, p), n in sorted(flows.items()):
            rows.append(f"|{name}|P{t}→P{p}|{n/len(predictions):.2f}|")
    rows += ["", "## Seed별 결과", "",
             "|모델|seed|Accuracy|Macro-F1|P0|P1|P2|P3|P4|P5|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in saved["results"].items():
        for seed, m in enumerate(result["per_seed"]):
            rows.append(f"|{name}|{seed}|" + "|".join(f"{v:.2f}" for v in
                        [m["accuracy"], m["macro_f1"], *m["recall"]]) + "|")
    rows += ["", "## 검증·보존", "",
             f"M0/M1 전체 seed·OOF 예측 동일: {saved['m0_m1_equal']}. "
             "M1의 양수 입력 배율은 CART의 특징 내 순서를 보존하므로 같은 예측이 가능하다. "
             "M2는 다른 분할 점수를 쓰므로 별도로 해석한다.", "",
             "24구간 identity/라벨/행렬·기존 LR·역사적 H9·모델 설정·train-only MDI/weights·fold 분리·"
             "OOF 1회·입력 불변·지표/CSV/보고 표 일치를 확인했다. 기존 RF 가중치/RNG 합성 구조 테스트 "
             "14개 PASS이며 실제 파일럿 결과와 구분한다. 전체 회귀 테스트는 하지 않았다.", "",
             "참가자별 예측·가중치/MDI·fold·입력 hash는 local_private/results.json, 전체 OOF는 "
             "local_private/predictions.csv에만 보관한다. 공개 요약은 이 보고서이며 실행 코드는 "
             "compare_six_feature_rf.py다. 기존 결과·실시간 모델·공식8조합·B6·IRB HOLD·Patch8 실행 보류는 유지한다.", "",
             "실행: `python -X utf8 -B compare_six_feature_rf.py`. 저장 검증만: 같은 명령에 `--verify` (학습 없음).", ""]
    return "\n".join(rows)


def prediction_rows(saved):
    for name, predictions in saved["predictions"].items():
        for seed, pred in enumerate(predictions):
            for i, value in enumerate(pred):
                yield dict(model=name, seed=seed, subject=saved["subjects"][i],
                           sample_key=json.dumps(saved["sample_keys"][i]), actual=saved["labels"][i], predicted=value)


def verify():
    saved = read(OUT / "local_private/results.json")
    data, _, y = pilot_data()
    for key in ("subjects", "labels", "sample_keys"):
        assert saved[key] == data[key]
    for name, predictions in saved["predictions"].items():
        assert len(predictions) == (1 if name == "LR" else 5)
        assert summarize(y, predictions) == saved["results"][name]
    for name, predictions in saved["historical_predictions"].items():
        assert summarize(y, predictions) == saved["historical"][name]
    for fold in saved["folds"]:
        tr, te = fold["train"], fold["test"]
        assert len(tr) == len(te) == 12 and not set(tr) & set(te)
        assert set(tr) | set(te) == set(range(24))
        np.testing.assert_array_equal(rf.rank_weights(np.array(fold["mdi"])), fold["weights"])
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    assert report(saved) in (OUT / "REPORT.md").read_text(encoding="utf-8")
    with (OUT / "local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 384
    for actual, expected in zip(rows, prediction_rows(saved)):
        assert actual == {k: str(v) for k, v in expected.items()}
    print("PASS: immutable inputs, saved OOF/metrics/weights/CSV/report; no training")


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    inputs = (DATA, LR_SOURCE, HISTORY, SNAPSHOT, ROOT / "rf_experiment.py", ROOT / "lr_posture_demo.py",
              ROOT / "review_lr_features.py", ROOT / "compare_lr_f2_f5.py", Path(__file__).resolve())
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    definitions = [{n.name: ast.dump(n, include_attributes=False) for n in ast.parse(
        path.read_text(encoding="utf-8-sig")).body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
        for path in (ROOT / "rf_experiment.py", SNAPSHOT)]
    assert all(definitions[0][n] == definitions[1][n] for n in ("Tree", "Forest", "rank_weights", "fit_models"))
    assert (rf.H_EVAL_TREES, rf.H_EVAL_MAX_FEATURES, rf.H_EVAL_SEEDS, rf.H_EVAL_M2_LAMBDA) == (500, 2, (0,1,2,3,4), .5)
    data, base, y = pilot_data()
    lr, old = read(LR_SOURCE), read(HISTORY)
    for path, sha in lr["inputs"].items():
        assert digest(ROOT / path) == sha
    assert lr["lr_params"] == fixed_lr().get_params()
    for key in ("subjects", "labels", "sample_keys"):
        assert lr[key] == data[key]
    assert lr["results"][NEW]["features"] == FEATURES
    assert score(y, lr["results"][NEW]["predictions"]) == lr["results"][NEW]["metrics"]
    assert len(old["samples"]) == 24
    for i, sample in enumerate(old["samples"]):
        assert sample["sample_key"] == data["sample_keys"][i] and sample["subject"] == data["subjects"][i]
        assert sample["posture"] == f"P{y[i]}" and sample["h9_values"] == data["matrix"][i]
    matrix = base[:, COLUMNS]
    assert matrix.shape == (24, 6) and np.isfinite(matrix).all()
    predictions = {n: [] for n in NAMES}
    folds = []
    with threadpool_limits(limits=1):
        for seed in rf.H_EVAL_SEEDS:
            current = {n: np.full(24, -1, dtype=int) for n in NAMES}
            seen = np.zeros(24, dtype=int)
            for prior_fold in lr["results"][NEW]["folds"]:
                tr, te = prior_fold["train"], prior_fold["test"]
                assert len(tr) == len(te) == 12 and not set(tr) & set(te)
                assert set(data["subjects"][i] for i in tr).isdisjoint(data["subjects"][i] for i in te)
                assert np.bincount(y[tr], minlength=6).tolist() == [2] * 6
                models, weights = rf.fit_models(matrix[tr], y[tr], 6, 500, seed, [.5])
                assert tuple(models) == NAMES
                mdi = models["M0"].forest.mdi
                np.testing.assert_array_equal(rf.rank_weights(mdi), weights)
                for name, predict in models.items():
                    assert predict.forest.T == 500 and predict.forest.mf == 2 and predict.forest.seed == seed
                    current[name][te] = predict(matrix[te])
                folds.append(dict(seed=seed, train=tr, test=te, mdi=mdi.tolist(), weights=weights.tolist()))
                seen[te] += 1
                print(f"Completed seed {seed}, fold {len(folds)%2 or 2}", flush=True)
            assert seen.tolist() == [1] * 24
            for name in NAMES:
                predictions[name].append(current[name].tolist())
    predictions["LR"] = [lr["results"][NEW]["predictions"]]
    historical = {n: old["results"]["H9"][n]["predictions_by_seed"] for n in NAMES}
    saved = dict(inputs=hashes, features=FEATURES, labels=y.tolist(), subjects=data["subjects"],
                 sample_keys=data["sample_keys"], predictions=predictions, folds=folds,
                 results={n: summarize(y, p) for n, p in predictions.items()},
                 historical_predictions=historical, historical={n: summarize(y, p) for n, p in historical.items()},
                 m0_m1_equal=predictions["M0"] == predictions["M1"])
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
        writer.writerows(prediction_rows(saved))
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    for name, result in saved["results"].items():
        print(name, {k: result[k] for k in ("accuracy", "macro_f1", "recall")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    run() if not parser.parse_args().verify else verify()
