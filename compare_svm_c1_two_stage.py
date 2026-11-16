"""Fixed C1 seven features: saved flat SVM vs one hard-routed two-stage SVM.

python -X utf8 -B compare_svm_c1_two_stage.py [--verify]
Same pilot120, LOSO, scaler, SVC parameters and seed0; exactly four new fits.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path
import pickle
import sys
import warnings

from compare_svm_fs3_f8_to_c1 import (
    ROOT, OUT as PRIOR, CANDIDATE as FLAT, C1_FEATURES, factory,
    read, digest, write, metrics, changes, LAB6, verify as verify_prior,
)
import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import confusion_matrix
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/SVM_C1_TWO_STAGE_20261112"
EXPERIMENT = "EXPLR-SVM-C1-TWO-STAGE-20261112"
TWO_STAGE = "SVM-C1-HARD-TWO-STAGE"


def train_stages(train, labels, make_model):
    """Inputs already use the frozen outer-train scaler; no test inputs here."""
    train, labels = np.asarray(train), np.asarray(labels)
    if train.ndim != 2 or labels.shape != (len(train),) or set(labels) != set(range(6)):
        raise ValueError("Expected complete six-class training fold")
    gate, specialist = make_model(), make_model()
    gate.fit(train, (labels != 0).astype(int))
    abnormal = labels != 0
    specialist.fit(train[abnormal], labels[abnormal])
    return gate, specialist


def route(gate, specialist, test):
    """Route solely by gate prediction, never by a held-out target label."""
    test = np.asarray(test)
    gates = np.asarray(gate.predict(test), dtype=int)
    if gates.shape != (len(test),) or not set(gates) <= {0, 1}:
        raise ValueError("Invalid binary gate predictions")
    final = np.zeros(len(test), dtype=int)
    indices = np.flatnonzero(gates == 1)
    if len(indices):
        predicted = np.asarray(specialist.predict(test[indices]), dtype=int)
        if predicted.shape != indices.shape or not set(predicted) <= set(range(1, 6)):
            raise ValueError("Invalid abnormal posture predictions")
        final[indices] = predicted
    return final, gates, indices


def gate_metrics(y, gate_predictions):
    cm = confusion_matrix(np.asarray(y) != 0, gate_predictions, labels=[0, 1])
    normal, abnormal = cm.sum(axis=1)
    return dict(confusion_matrix=cm.tolist(), normal_recall=100*float(cm[0, 0]/normal),
                abnormal_recall=100*float(cm[1, 1]/abnormal),
                accuracy=100*float(np.trace(cm)/cm.sum()))


def report(saved):
    lines = ["# C1 포함7특징: 단일 SVM과 2단계 SVM 구조 비교", "",
        f"실험 ID: `{EXPERIMENT}`. 사용자 요청에 따라 현재 C1 7특징과 평가를 고정한 개발 탐색 비교다. "
        "같은 참가자2명의 반복 사용 자료이며 독립 검증·일반화·공식 모델 선정 결과가 아니다.", "",
        "## 고정 조건과 이번에 바꾼 부분", "",
        "특징은 **F1,F3,F4,F5,F6,F7,C1**, 기존 적격120구간(113+기술적 보완7), "
        "참가자당60·자세당20, 참가자LOSO2fold(train60/test60)다. "
        "기존 저장 C1 행렬을 그대로 사용하며 표본·원시 support·집계·결측/적격성·순서·최종6라벨을 변경하지 않았다.", "",
        "기존 단일 SVM의 저장모델2개를 hash 확인 후 복원해120개 예측을 재현했다. "
        "기준선 추가fit은0회다. 2단계의 각 SVC도 기존 생성기와 seed0, "
        "C=1,gamma=1/9,class_weight=None,probability=False,tol=1e-3 및 나머지 설정을 그대로 사용했다.", "",
        "**전처리도 고정:** 각 fold의 기존 학습60개로 fit한 StandardScaler를 두 단계에 동일하게 재사용했다. "
        "2차의50개만으로 scaler를 다시 fit하지 않았다. 따라서 전처리 통계 변경과 구조 변경을 섞지 않는다. "
        "scaler는 시험자료를 보지 않으며, 두 단계 모두 같은7열·같은 좌표변환을 사용한다.", "",
        "1차는 학습60개에서 P0=정상0, P1~P5=비정상1을 내부적으로 파생해 학습한다(정상10:비정상50). "
        "2차는 학습fold의 실제 P1~P5 50개만으로 원래 자세라벨1~5를 학습한다. "
        "시험에서는 **1차 predict가0이면 최종P0, 1이면 그 입력만2차 predict**로 보낸다. "
        "시험정답으로 경로를 선택하지 않는다. 최종6라벨 평가는120개 전부를 포함한다.", "",
        "신규fit은1차2회+2차2회=4회다. 학습 전 계획/입력hash/분할/설정을 저장했다. "
        "가중치·C/gamma·임계값·확률 보정·soft routing·PNN·특징 변경은 추가하지 않았다. "
        "2차는 five-class SVC 하나이며 자세별 독립 확률모델5개가 아니다.", "",
        "## 최종6-class 결과", "",
        "|구성|정답/120|Accuracy %|Macro-F1 %|Macro Precision %|Macro Recall %|",
        "|---|---:|---:|---:|---:|---:|"]
    for name, result in saved["results"].items():
        m = result["metrics"]
        lines.append(f"|{name}|{m['correct']}/120|" + "|".join(f"{m[k]:.2f}" for k in
                     ("accuracy", "macro_f1", "macro_precision", "macro_recall")) + "|")
    a, b = [saved["results"][name]["metrics"] for name in (FLAT, TWO_STAGE)]
    lines += ["", f"2단계−단일: Accuracy {b['accuracy']-a['accuracy']:+.2f}pp, "
              f"Macro-F1 {b['macro_f1']-a['macro_f1']:+.2f}pp.", "",
              "## 클래스별 Recall", "", "|자세|support|단일 %|2단계 %|차이 pp|",
              "|---|---:|---:|---:|---:|"]
    for i in range(6):
        old, new = a["per_class"][i], b["per_class"][i]
        lines.append(f"|P{i} {LAB6[i]}|{old['support']}|{old['recall']:.2f}|{new['recall']:.2f}|{new['recall']-old['recall']:+.2f}|")
    lines += ["", "## 정상/비정상 진단", "",
              "단일은 기존6-class 예측을 P0/그외로 묶은 진단이고, 2단계는 실제 학습한1차 gate 결과다.", "",
              "|구성|정상 Recall %|비정상 Recall %|이진 Accuracy %|실제비정상→정상|실제정상→비정상|",
              "|---|---:|---:|---:|---:|---:|"]
    for name, result in saved["results"].items():
        g = result["gate_metrics"]
        lines.append(f"|{name}|{g['normal_recall']:.2f}|{g['abnormal_recall']:.2f}|{g['accuracy']:.2f}|"
                     f"{g['confusion_matrix'][1][0]}|{g['confusion_matrix'][0][1]}|")
    lines += ["", "## 오류 변화와 경로별 오류", ""]
    c = saved["changes"]
    lines.append(f"예측 변경{c['changed']}개: 오답→정답{c['wrong_to_correct']}개, "
                 f"정답→오답{c['correct_to_wrong']}개, 오답→다른오답{c['wrong_to_wrong']}개.")
    lines += ["", "|구성|실제→예측|건수|", "|---|---|---:|"]
    for name, result in saved["results"].items():
        counts = Counter(f"P{y}→P{p}" for y, p in zip(saved["labels"], result["predictions"]) if y != p)
        for flow, count in sorted(counts.items()):
            lines.append(f"|{name}|{flow}|{count}|")
    lines += ["", "2단계 경로별 오류:"]
    error_names = dict(abnormal_stopped_as_normal="비정상을1차에서 정상으로 종료",
                       normal_routed_to_abnormal="정상을1차에서 비정상으로 보내 오분류",
                       wrong_subtype_after_correct_abnormal_route="실제비정상이1차를 통과했지만2차 자세가 오분류")
    for key, count in saved["routing_errors"].items():
        lines.append(f"- {error_names[key]}: {count}개")
    lines += ["", "경로별 진단은 전체120개 최종 평가의 보조값이다. 통과한 표본만의 정확도를 전체 정확도로 해석하지 않는다.", "",
              "## 최종 혼동행렬", "", "행=실제, 열=예측. P0~P5 순서다."]
    for name, result in saved["results"].items():
        lines += ["", name, "", "```text", *[" ".join(map(str, row)) for row in result["metrics"]["confusion_matrix"]], "```"]
    lines += ["", "## 해석과 한계", "",
        "현재 고정한 구조의 결과로만 판단한다. 다른 threshold/가중치/전처리를 추가하면 별도 실험이다. "
        "1차에서 정상으로 잘못 종료한 비정상 표본은2차가 복구하지 못한다. "
        "이진 표본은 정상20:비정상100이므로 전체 이진Accuracy만으로 개선을 주장하지 않는다. "
        "2단계 비교를 이유로 실시간 모델을 자동 교체하거나 공식 선정 규약을 바꾸지 않았다.", "",
        "두 사람의 반복 탐색 결과이며 새로운 사람/세션에서의 성능을 확정하지 않는다. "
        "확률 출력/확률 보정·새 특징·신장 정규화·PNN·추론비용/FPS는 이번에 측정하지 않았다. "
        "기존 촬영·raw·연구 authority·M0/M1/M2·frozen schema와 Patch8 실행 보류는 유지한다.", "",
        "## 파일·검증", "",
        "추가 소스 compare_svm_c1_two_stage.py, 구조 테스트 test_svm_c1_two_stage.py, 요약은 이 REPORT.md다. "
        "local_private/에는 PLAN.json, results.json, predictions.csv 및 fold별2개 bundle(model/scaler)을 저장했다. "
        "개별 특징/예측/모델은 Git 제외 위치에 보관한다. 기존 파일을 수정하거나 commit/push하지 않았다.", "",
        "단일모델 예측 재현·입력/모델hash·동일120/LOSO·scaler고정·학습subset·SVC설정·"
        "게이트만으로 시험경로 결정·정상 경로의2차 호출 생략·OOF1회·저장모델 재예측·지표/CSV/보고서 일치를 확인했다.", "",
        "학습 전 `python -X utf8 -B -m unittest -v test_svm_c1_two_stage test_svm_fs3_f8_to_c1`을 실행해 "
        "9개 PASS를 확인했다. 신규5개는 경로/학습subset/잘못된 라벨/오류분해를 검증한 합성 구조 테스트이며 "
        "기존 C1 구조 테스트4개도 유지했다. 실제120구간 분류 성능과 합성 테스트를 구분한다. 전체 회귀는 실행하지 않았다.", "",
        "실행: `python -X utf8 -B compare_svm_c1_two_stage.py`; "
        "저장 검증: 같은 명령에 `--verify`(추가학습 없음).", ""]
    return "\n".join(lines)


def load_flat(saved):
    result = saved["results"][FLAT]
    x, y = np.array(saved["matrix"]), np.array(saved["labels"])
    assert saved["features"] == C1_FEATURES and x.shape == (120, 7) and np.isfinite(x).all()
    assert np.bincount(y, minlength=6).tolist() == [20]*6
    pred = np.full(120, -1, dtype=int)
    bundles = []
    for f in result["folds"]:
        path = ROOT / f["model_path"]
        assert digest(path) == f["model_sha256"]
        with path.open("rb") as stream:
            model, scaler = pickle.load(stream)
        tr, te = f["train"], f["test"]
        assert len(tr) == len(te) == 60 and set(tr).isdisjoint(te)
        assert set(saved["subjects"][i] for i in tr).isdisjoint(saved["subjects"][i] for i in te)
        assert model.get_params() == factory("SVM-RBF", 0).get_params()
        assert scaler.n_samples_seen_ == 60
        np.testing.assert_allclose(scaler.mean_, x[tr].mean(0), rtol=0, atol=1e-14)
        np.testing.assert_allclose(scaler.scale_, x[tr].std(0), rtol=0, atol=1e-14)
        pred[te] = model.predict(scaler.transform(x[te]))
        bundles.append((f, model, scaler))
    assert pred.tolist() == result["predictions"] and result["metrics"] == metrics(y, pred)
    return x, y, bundles


def route_errors(y, final, gates):
    y, final, gates = map(np.asarray, (y, final, gates))
    return dict(abnormal_stopped_as_normal=int(((y != 0) & (gates == 0)).sum()),
                normal_routed_to_abnormal=int(((y == 0) & (gates == 1)).sum()),
                wrong_subtype_after_correct_abnormal_route=int(((y != 0) & (gates == 1) & (final != y)).sum()))


def verify():
    verify_prior()
    source = read(PRIOR / "local_private/results.json")
    x, y, baseline_bundles = load_flat(source)
    saved = read(OUT / "local_private/results.json")
    plan = read(OUT / "local_private/PLAN.json")
    assert saved["features"] == plan["features"] == source["features"]
    for key in ("labels", "subjects", "sample_keys"):
        assert saved[key] == source[key]
    assert plan["params"] == factory("SVM-RBF", 0).get_params()
    assert plan["new_fits"] == saved["new_fits"] == 4
    assert len(saved["folds"]) == len(plan["folds"]) == 2
    result = saved["results"][TWO_STAGE]
    pred, gates, seen = np.full(120, -1), np.full(120, -1), np.zeros(120, dtype=int)
    for f, (baseline_fold, _, baseline_scaler) in zip(saved["folds"], baseline_bundles):
        tr, te = baseline_fold["train"], baseline_fold["test"]
        assert f["train"] == tr and f["test"] == te
        assert plan["folds"][f["number"]] == dict(number=f["number"], train=tr, test=te,
                    specialist_train=[i for i in tr if y[i] != 0], scaler_path=baseline_fold["model_path"],
                    scaler_bundle_sha256=baseline_fold["model_sha256"])
        assert f["specialist_train"] == [i for i in tr if y[i] != 0] and len(f["specialist_train"]) == 50
        assert np.bincount(y[f["specialist_train"]], minlength=6).tolist() == [0,10,10,10,10,10]
        path = ROOT / f["model_path"]
        assert digest(path) == f["model_sha256"]
        with path.open("rb") as stream:
            gate, specialist, scaler = pickle.load(stream)
        for name in ("mean_", "scale_", "var_"):
            np.testing.assert_array_equal(getattr(scaler, name), getattr(baseline_scaler, name))
        assert scaler.n_samples_seen_ == 60
        for model, classes, size in ((gate, [0,1], 60), (specialist, [1,2,3,4,5], 50)):
            assert model.get_params() == plan["params"] and model.classes_.tolist() == classes
            assert model.shape_fit_ == (size, 7) and model.fit_status_ == 0 and model._gamma == 1/9
            np.testing.assert_array_equal(model.class_weight_, np.ones(len(classes)))
        test = scaler.transform(x[te])
        final, g, routed = route(gate, specialist, test)
        np.testing.assert_array_equal(gate.decision_function(test), f["gate_scores"])
        assert final.tolist() == f["predictions"] and g.tolist() == f["gate_predictions"]
        assert routed.tolist() == f["routed_test_positions"]
        pred[te], gates[te] = final, g
        seen[te] += 1
    assert seen.tolist() == [1]*120
    assert pred.tolist() == result["predictions"] and gates.tolist() == result["gate_predictions"]
    flat = saved["results"][FLAT]
    assert flat["predictions"] == source["results"][FLAT]["predictions"]
    for name, r in saved["results"].items():
        assert r["metrics"] == metrics(y, r["predictions"])
        g = r["gate_predictions"] if name == TWO_STAGE else (np.asarray(r["predictions"]) != 0).astype(int)
        assert r["gate_metrics"] == gate_metrics(y, g)
    assert saved["routing_errors"] == route_errors(y, pred, gates)
    assert sum(saved["routing_errors"].values()) == 120-result["metrics"]["correct"]
    assert saved["changes"] == changes(y, flat["predictions"], pred.tolist())
    for path, sha in saved["inputs"].items():
        assert digest(ROOT/path) == sha, path
    for path, sha in plan["input_hashes"].items():
        assert saved["inputs"][path] == sha
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 120 and [int(r["index"]) for r in rows] == list(range(120))
    for i, row in enumerate(rows):
        assert [int(row[k]) for k in ("actual","flat","gate","two_stage")] == [int(y[i]), flat["predictions"][i], int(gates[i]), int(pred[i])]
        assert row["stage2"] == (str(int(pred[i])) if gates[i] else "")
    assert (OUT/"REPORT.md").read_text(encoding="utf-8") == report(saved)
    print("PASS: fixed C1 seven features/same120/LOSO/shared frozen scaler/4 fits, hard routing, model replay, metrics/CSV/report/hashes; no new training")


def run():
    if OUT.exists():
        raise FileExistsError("Existing outputs preserved; use --verify")
    verify_prior()
    source_path = PRIOR/"local_private/results.json"
    source = read(source_path)
    x, y, bundles = load_flat(source)
    paths = [source_path, PRIOR/"local_private/PLAN.json", ROOT/"compare_svm_c1_two_stage.py",
             ROOT/"test_svm_c1_two_stage.py", ROOT/"compare_svm_fs3_f8_to_c1.py",
             ROOT/"compare_six_feature_svm_knn.py", ROOT/"evaluate_new_pilot_lr6.py",
             ROOT/"compare_lr_f2_f5.py", ROOT/"review_lr_features.py"]
    paths += [ROOT/f["model_path"] for f, _, _ in bundles]
    inputs = {str(p.relative_to(ROOT)):digest(p) for p in paths}
    private = OUT/"local_private"
    private.mkdir(parents=True, exist_ok=False)
    write(private/"PLAN.json", dict(experiment=EXPERIMENT, scope="EXPLORATORY_FIXED_C1_STRUCTURE_ONLY",
          features=C1_FEATURES, params=factory("SVM-RBF",0).get_params(), new_fits=4, baseline_fits=0,
          input_hashes=inputs, routing="gate.predict=0 -> P0; gate.predict=1 -> five-class specialist.predict",
          preprocessing="reuse identical baseline scaler fitted to outer-train60 for BOTH stages; no scaler refit",
          stage1_targets="0 normal / 1 abnormal derived from original training labels only",
          final_labels=list(range(6)), probability="disabled; no thresholds, calibration, or soft routing",
          folds=[dict(number=f["number"], train=f["train"], test=f["test"], specialist_train=[i for i in f["train"] if y[i] != 0],
                      scaler_path=f["model_path"], scaler_bundle_sha256=f["model_sha256"]) for f, _, _ in bundles],
          comparison="one predeclared hard-routing structure; no adaptive tuning or automatic deployment"))
    inputs[str((private/"PLAN.json").relative_to(ROOT))] = digest(private/"PLAN.json")
    predictions, gates = np.full(120,-1,dtype=int), np.full(120,-1,dtype=int)
    folds = []
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        warnings.simplefilter("error", ConvergenceWarning)
        for f, _, scaler in bundles:
            tr, te = f["train"], f["test"]
            gate, specialist = train_stages(scaler.transform(x[tr]), y[tr], lambda:factory("SVM-RBF",0))
            test = scaler.transform(x[te])
            final, g, routed = route(gate, specialist, test)
            path = private/f"fold{f['number']}_models.pkl"
            with path.open("xb") as stream:
                pickle.dump((gate,specialist,scaler),stream,protocol=5)
            folds.append(dict(number=f["number"],train=tr,test=te,specialist_train=[i for i in tr if y[i] != 0],
                              model_path=str(path.relative_to(ROOT)),model_sha256=digest(path),
                              predictions=final.tolist(),gate_predictions=g.tolist(),routed_test_positions=routed.tolist(),
                              gate_scores=gate.decision_function(test).tolist()))
            predictions[te], gates[te] = final, g
            print(f"fold{f['number']} completed; stage1 train60 / stage2 train50",flush=True)
    flat_predictions = source["results"][FLAT]["predictions"]
    saved = dict(experiment=EXPERIMENT,inputs=inputs,features=C1_FEATURES,new_fits=4,folds=folds,
                 labels=source["labels"],subjects=source["subjects"],sample_keys=source["sample_keys"],
                 results={FLAT:dict(predictions=flat_predictions,metrics=metrics(y,flat_predictions),
                                   gate_metrics=gate_metrics(y,(np.asarray(flat_predictions)!=0).astype(int))),
                          TWO_STAGE:dict(predictions=predictions.tolist(),gate_predictions=gates.tolist(),
                                         metrics=metrics(y,predictions),gate_metrics=gate_metrics(y,gates))},
                 routing_errors=route_errors(y,predictions,gates),changes=changes(y,flat_predictions,predictions.tolist()),
                 warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in recorded)),
                 python=sys.version.split()[0],numpy=np.__version__,sklearn=sklearn.__version__)
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["index","actual","flat","gate","stage2","two_stage"])
        writer.writeheader()
        writer.writerows(dict(index=i,actual=int(y[i]),flat=flat_predictions[i],gate=int(gates[i]),
                             stage2=int(predictions[i]) if gates[i] else "",two_stage=int(predictions[i])) for i in range(120))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    for name,r in saved["results"].items():
        print(name,dict(accuracy=r["metrics"]["accuracy"],macro_f1=r["metrics"]["macro_f1"],
                       recall=[c["recall"] for c in r["metrics"]["per_class"]],gate=r["gate_metrics"]))
    print("changes",saved["changes"],"routing errors",saved["routing_errors"])


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
