"""Diagnose the fixed six-feature LR, then test only C=0.3 against C=1.

python -X utf8 -B diagnose_six_lr_regularization.py
Append --verify for saved-output verification without fits.
All participant derivatives and model states stay in local_private/.
"""
import argparse
import csv
import json
from pathlib import Path
import pickle
import warnings

from review_lr_features import read, digest, score
from lr_posture_demo import DATA, ROOT, fixed_lr, pilot_data
from compare_six_feature_rf import COLUMNS, FEATURES
from compare_lr_f2_f5 import changes

import numpy as np
from sklearn.base import clone
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/SIX_FEATURE_LR_REGULARIZATION_20261106"
BENCH = ROOT / "analysis/SIX_FEATURE_MODEL_COST_20261106/local_private"
REFERENCE = ROOT / "analysis/LR_DROP_F2_F5_20261106/local_private/results.json"
BASE, CANDIDATE = "LR6_C1", "LR6_C0.3"


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def prediction_rows(saved):
    for name, result in saved["results"].items():
        for i, predicted in enumerate(result["predictions"]):
            yield dict(condition=name, subject=saved["subjects"][i],
                       sample_key=json.dumps(saved["sample_keys"][i]), actual=saved["labels"][i],
                       predicted=predicted, margin=result["margins"][i])


def report(saved):
    a, b = (saved["results"][n]["metrics"] for n in (BASE, CANDIDATE))
    change = changes(saved["labels"], saved["results"][BASE]["predictions"],
                     saved["results"][CANDIDATE]["predictions"])
    lines = ["# 6특징 LR 오류 진단과 단일 규제 강화 가설", "",
             "실험 ID: `EXPLR-LR6-REGULARIZATION-20261106`. 기존2인·24구간 반복 탐색 자료다. "
             "일반화·유의성·독립 검증 결과가 아니다.", "",
             "## 기준 모델과 오류 진단", "",
             "F1,F3,F4,F6,F7,F8 + 기존 LR C=1. 각 학습12/시험12 LOSO의 seed0 모델을 "
             "이전 비용 측정의 로컬 pickle에서 hash 검증 후 복원했다. 기준 모델 재학습은0회다. "
             "24개 OOF 예측은 저장된 LR6 결과와 정확히 같았으며 오류는 P0→P1, P1→P0 각1건이다.", "",
             "각 fold에서 raw값과 train-only 표준화 z, 학습 실제/오답 클래스 범위, 전6클래스 decision score·"
             "확률·순위, 계수·절편을 확인했다. margin=실제 score−최고 다른 클래스 score다. "
             "오류별 기여 `(coef_true−coef_wrong)×z` 합에 절편 차이를 더하면 margin과 일치했다. "
             "상관된 특징의 기준점 의존 대수 분해이며 인과적 중요도는 아니다.", "",
             "- P0→P1: F7/F8이 가장 큰 음의 기여였다. 시험 P0의 깊이 상대값이 다른 사람의 학습 "
             "정상 범위와 달라 P1 쪽으로 점수를 밀었다. 절편은 오히려 P0를 지지했다.",
             "- P1→P0: F4의 음의 항과 절편이 오답을 지지했다. F8은 실제 P1을 지지해 "
             "두 오류의 기여 방향이 같지 않았다. F3 등 작은 음의 항도 있었다.",
             "- 두 fold 모두 학습12/12 정답이었다. 다른 사람의 기준값 이동과 작은 학습 표본, "
             "6-class 경계가 관련될 수 있다. 체형·수행·카메라·depth 원인은 이 자료로 분리할 수 없다.", "",
             "참가자별 raw/z/범위/점수/계수/기여·오류 margin은 local_private/DIAGNOSIS.md 및 "
             "baseline_diagnostics.json에만 저장한다. 각 학습 클래스 범위의 표본은2개이며 모집단 범위가 아니다.", "",
             "## 결과를 보기 전에 고정한 한 가설", "",
             "**C=1→0.3으로 L2 규제만 강화**해 참가자별 학습 경계에 대한 의존이 줄어드는지 확인한다. "
             "오류가 서로 반대 방향이고 절편 역할도 달라 특정 한 클래스 편향을 바로 추가하지 않았다. "
             "학습이 이미 완전 분류된 작은 자료에서 규제 강화를 검토할 근거는 있으나 성공을 보장하지 않는다.", "",
             "0.3은 이전8특징 실험의 사전 지정 값에서 재사용한 단일 수준이며 계수/오류를 맞추도록 "
             "수치 탐색하지 않았다. 당시8특징 C=0.3은 새 오류를 만들어 실패했다. "
             "그 부정적 결과를 유지하면서 현재6특징의 다른 경계를 별도 확인했다. "
             "클래스 가중치·다른 C·seed·특징·threshold는 시험하지 않았다.", "",
             "후보 fit 전에 진단을 저장하고 PLAN.json을 배타 생성했다. "
             "LR L2/lbfgs/tol=1e-4/max_iter=10000/intercept/class_weight=None/random_state=0은 동일하다. "
             "기준 fold의 train-only scaler를 그대로 재사용하고 실제 학습 행 mean/SD와 대조했다. "
             "새로운 fit은 후보2fold뿐이며 동일24구간·라벨·LOSO·support·집계를 유지했다.", "",
             "## 정량 결과", "", "단위 %. P0~P5는 Recall, 지표는24 OOF pooled6-class다.", "",
             "|조건|Accuracy|Macro-F1|P0|P1|P2|P3|P4|P5|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in saved["results"].items():
        m = result["metrics"]
        lines.append(f"|{name}|" + "|".join(f"{v:.2f}" for v in [m["accuracy"], m["macro_f1"], *m["recall"]]) + "|")
    lines += ["", f"기준 대비 ΔAccuracy {b['accuracy']-a['accuracy']:+.2f}pp, "
              f"ΔMacro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp. "
              f"예측 변경 {change['changed']}건: 오답→정답 {change['wrong_to_correct']}, "
              f"정답→오답 {change['correct_to_wrong']}, 오답→다른 오답 {change['wrong_to_wrong']}.", "",
              "|변경 유형|건수|", "|---|---:|"]
    for name, count in change["flows"].items():
        lines.append(f"|{name}|{count}|")
    if not change["flows"]:
        lines.append("|없음|0|")
    lines += ["", "## 혼동행렬", "", "행=실제P0~P5, 열=예측P0~P5, 정수 건수다."]
    for name, result in saved["results"].items():
        lines += ["", f"### {name}", "", "```text"]
        lines += [" ".join(map(str, row)) for row in result["metrics"]["cm"]]
        lines += ["```"]
    lines += ["", "## 검증·보존", "",
              "기준 예측 재현, fold/입력/설정 동일성, scaler 불변, 계수 분해 합, 수렴, "
              "표본당OOF1회, confusion-matrix 지표 산술, CSV/MD 표·입력 hash 불변을 확인했다. "
              "전체 회귀 테스트는 실행하지 않았다.", "",
              "실행 코드는 diagnose_six_lr_regularization.py, 공개 요약은 이 보고서다. "
              "모델 상태·참가자 상세·진단·계획·OOF·모든 margin은 local_private/에만 저장했다. "
              "기존 파일/실시간 모델·공식8조합·B6·IRB HOLD·Patch8 실행 보류를 변경하지 않았다. "
              "촬영·새 특징·추가 가설 탐색·commit/push는 하지 않았다.", "",
              "실행: `python -X utf8 -B diagnose_six_lr_regularization.py`. "
              "저장 검증만: 같은 명령에 `--verify` (학습 없음).", ""]
    return "\n".join(lines)


def diagnose(data, x, y, reference):
    baseline = dict(predictions=[-1]*24, margins=[None]*24, folds=[], scores=[None]*24, probabilities=[None]*24)
    loaded, errors = [], []
    for fold in range(2):
        path = BENCH / f"rep0_fold{fold}_0/model.pkl"
        record = read(path.parent / "record.json")
        assert digest(path) == record["model_sha256"] and record["model"] == "LR"
        with path.open("rb") as stream:
            model, scaler, weights = pickle.load(stream)  # trusted local artifact only
        assert weights is None and model.get_params() == fixed_lr().get_params()
        tr, te = record["train"], record["test"]
        assert len(tr) == len(te) == 12 and set(tr).isdisjoint(te)
        assert set(data["subjects"][i] for i in tr).isdisjoint(data["subjects"][i] for i in te)
        assert int(scaler.n_samples_seen_) == 12
        np.testing.assert_allclose(scaler.mean_, x[tr].mean(0), rtol=0, atol=1e-14)
        np.testing.assert_allclose(scaler.scale_, x[tr].std(0), rtol=0, atol=1e-14)
        z = scaler.transform(x[te])
        scores, probabilities = model.decision_function(z), model.predict_proba(z)
        preds = model.predict(z)
        for q, i in enumerate(te):
            actual, predicted = int(y[i]), int(preds[q])
            margin = float(scores[q, actual]-np.max(np.delete(scores[q], actual)))
            baseline["predictions"][i], baseline["margins"][i] = predicted, margin
            baseline["scores"][i], baseline["probabilities"][i] = scores[q].tolist(), probabilities[q].tolist()
            if actual != predicted:
                contributions = (model.coef_[actual]-model.coef_[predicted])*z[q]
                intercept = float(model.intercept_[actual]-model.intercept_[predicted])
                np.testing.assert_allclose(contributions.sum()+intercept, margin, rtol=0, atol=1e-12)
                errors.append(dict(index=i, subject=data["subjects"][i], sample_key=data["sample_keys"][i],
                    actual=actual, predicted=predicted, raw=x[i].tolist(), z=z[q].tolist(), margin=margin,
                    scores=scores[q].tolist(), probabilities=probabilities[q].tolist(),
                    true_rank=int(np.where(np.argsort(-scores[q]) == actual)[0][0]+1),
                    coefficient_difference=(model.coef_[actual]-model.coef_[predicted]).tolist(),
                    contributions=contributions.tolist(), intercept_difference=intercept,
                    train_actual_ranges=np.column_stack((x[np.asarray(tr)[y[tr]==actual]].min(0),
                                                         x[np.asarray(tr)[y[tr]==actual]].max(0))).tolist(),
                    train_wrong_ranges=np.column_stack((x[np.asarray(tr)[y[tr]==predicted]].min(0),
                                                        x[np.asarray(tr)[y[tr]==predicted]].max(0))).tolist()))
        baseline["folds"].append(dict(train=tr, test=te, mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
            coef=model.coef_.tolist(), intercept=model.intercept_.tolist(), n_iter=model.n_iter_.tolist(),
            train_correct=int(np.sum(model.predict(scaler.transform(x[tr]))==y[tr]))))
        loaded.append((model, scaler, tr, te))
    assert baseline["predictions"] == reference["results"]["B0-F2-F5"]["predictions"]
    assert len(errors) == 2 and {(e["actual"],e["predicted"]) for e in errors} == {(0,1),(1,0)}
    baseline["metrics"] = score(y, baseline["predictions"])
    return baseline, errors, loaded


def verify():
    saved = read(OUT / "local_private/results.json")
    data, _, y = pilot_data()
    for key in ("labels", "subjects", "sample_keys"):
        assert saved[key] == data[key]
    for name, result in saved["results"].items():
        assert score(y, result["predictions"]) == result["metrics"]
        assert len(result["folds"]) == 2
    for error in read(OUT / "local_private/baseline_diagnostics.json")["errors"]:
        np.testing.assert_allclose(sum(error["contributions"])+error["intercept_difference"], error["margin"], rtol=0, atol=1e-12)
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    assert report(saved) in (OUT / "REPORT.md").read_text(encoding="utf-8")
    with (OUT / "local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        actual = list(csv.DictReader(stream))
    assert len(actual) == 48
    for row, expected in zip(actual, prediction_rows(saved)):
        assert row == {k: str(v) for k, v in expected.items()}
    print("PASS: baseline, one fixed hypothesis, decomposition, saved metrics/CSV/report/inputs; no fits")


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    sources = [DATA, REFERENCE, ROOT / "lr_posture_demo.py", Path(__file__).resolve()]
    sources += [BENCH / f"rep0_fold{fold}_0/{name}" for fold in range(2) for name in ("model.pkl", "record.json")]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    reference = read(REFERENCE)
    for path, sha in reference["inputs"].items():
        assert digest(ROOT / path) == sha
    data, base, y = pilot_data()
    x = base[:, COLUMNS]
    baseline, errors, loaded = diagnose(data, x, y, reference)
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    write(private / "baseline_diagnostics.json", dict(features=FEATURES, errors=errors, baseline=baseline))
    lines = ["# LOCAL PRIVATE — LR6 오류 분해", "", "raw/z/계수·기여는 참가자 파생자료이므로 Git 제외."]
    for e in errors:
        lines += ["", f"## {e['subject']} / {e['sample_key']}: P{e['actual']}→P{e['predicted']}", "",
                  f"margin={e['margin']}; intercept difference={e['intercept_difference']}; true rank={e['true_rank']}",
                  f"scores={e['scores']}; probabilities={e['probabilities']}", "",
                  "|특징|raw|z|계수차|margin 기여|학습 실제 범위|학습 오답 범위|", "|---|---:|---:|---:|---:|---|---|"]
        for j, feature in enumerate(FEATURES):
            lines.append(f"|{feature}|{e['raw'][j]:.9g}|{e['z'][j]:.9g}|{e['coefficient_difference'][j]:.9g}|"
                         f"{e['contributions'][j]:.9g}|{e['train_actual_ranges'][j]}|{e['train_wrong_ranges'][j]}|")
    with (private / "DIAGNOSIS.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines)+"\n")
    plan = dict(hypothesis="stronger L2 may reduce participant-specific boundary sensitivity",
                baseline_C=1.0, candidate_C=.3, changed_parameter="C", class_weight=None,
                seed=0, features=FEATURES, new_fits=2, no_search=True,
                diagnostics_sha256=digest(private / "baseline_diagnostics.json"))
    write(private / "PLAN.json", plan)  # persisted BEFORE the candidate fits
    hashes[str((private / "PLAN.json").relative_to(ROOT))] = digest(private / "PLAN.json")
    candidate = dict(predictions=[-1]*24, margins=[None]*24, scores=[None]*24, probabilities=[None]*24, folds=[])
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error")
        for model, scaler, tr, te in loaded:
            new = clone(model).set_params(C=.3)
            assert [k for k,v in new.get_params().items() if v != model.get_params()[k]] == ["C"]
            before = (scaler.mean_.copy(), scaler.scale_.copy())
            new.fit(scaler.transform(x[tr]), y[tr])
            assert np.all(new.n_iter_ < new.max_iter)
            z = scaler.transform(x[te])
            scores, probabilities, predictions = new.decision_function(z), new.predict_proba(z), new.predict(z)
            for q,i in enumerate(te):
                candidate["predictions"][i] = int(predictions[q])
                candidate["margins"][i] = float(scores[q,y[i]]-np.max(np.delete(scores[q],y[i])))
                candidate["scores"][i], candidate["probabilities"][i] = scores[q].tolist(), probabilities[q].tolist()
            np.testing.assert_array_equal(before[0], scaler.mean_)
            np.testing.assert_array_equal(before[1], scaler.scale_)
            candidate["folds"].append(dict(train=tr, test=te, mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                coef=new.coef_.tolist(), intercept=new.intercept_.tolist(), n_iter=new.n_iter_.tolist(),
                train_correct=int(np.sum(new.predict(scaler.transform(x[tr]))==y[tr]))))
    candidate["metrics"] = score(y, candidate["predictions"])
    saved = dict(inputs=hashes, labels=y.tolist(), subjects=data["subjects"], sample_keys=data["sample_keys"],
                 results={BASE: baseline, CANDIDATE: candidate})
    for path, sha in hashes.items():
        assert digest(ROOT / path) == sha
    write(private / "results.json", saved)
    with (private / "predictions.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["condition","subject","sample_key","actual","predicted","margin"])
        writer.writeheader()
        writer.writerows(prediction_rows(saved))
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    print(json.dumps({n:r["metrics"] for n,r in saved["results"].items()}))
    print(json.dumps(changes(y.tolist(), baseline["predictions"], candidate["predictions"]), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    verify() if parser.parse_args().verify else run()
