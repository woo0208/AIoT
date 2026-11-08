"""Fixed LR6 evaluation of the reviewed pre-supplement 113 eligible pilot segments.

python -X utf8 -B evaluate_new_pilot_lr6.py
Append --verify to check saved predictions/metrics without training.
Participant features, predictions and fold models remain in local_private/.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import pickle
import warnings

from review_lr_features import ROOT, read, digest
from lr_posture_demo import FACTORY, fixed_lr
from h6_offline import LAB6, load_labeled_probe_h_samples
from f1_sample_aggregator import H9_FEATURE_NAMES

import numpy as np
import sklearn
from sklearn.base import clone
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, f1_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/LR6_PRE_SUPPLEMENT_20261106"
REVIEW = ROOT / "analysis/PILOT_SIX_CAPTURE_REVIEW_20261106/local_private/results.json"
COLUMNS = (0,2,3,5,6,7)
FEATURES = [f"F{j+1}" for j in COLUMNS]


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def metrics(y, predictions):
    cm = confusion_matrix(y, predictions, labels=range(6))
    precision, recall, f1, support = precision_recall_fscore_support(
        y, predictions, labels=range(6), zero_division=0)
    assert np.all(support > 0) and int(cm.sum()) == len(y)
    return dict(samples=len(y), correct=int(np.trace(cm)), accuracy=100*float(np.mean(np.asarray(y)==predictions)),
                macro_f1=100*float(np.mean(f1)), macro_precision=100*float(np.mean(precision)),
                macro_recall=100*float(np.mean(recall)),
                weighted_f1=100*float(f1_score(y,predictions,labels=range(6),average="weighted",zero_division=0)),
                confusion_matrix=cm.tolist(),
                per_class=[dict(posture=f"P{i}",label=LAB6[i],support=int(support[i]),
                                precision=float(100*precision[i]),recall=float(100*recall[i]),f1=float(100*f1[i]))
                           for i in range(6)])


def prediction_rows(saved):
    for i, predicted in enumerate(saved["predictions"]):
        yield dict(subject=saved["subjects"][i], sample_key=json.dumps(saved["sample_keys"][i]),
                   actual=saved["labels"][i], predicted=predicted,
                   margin=saved["margins"][i], probabilities=json.dumps(saved["probabilities"][i]))


def report(saved):
    m = saved["metrics"]
    lines = ["# 재촬영 전 신규 탐색자료 — 고정6특징 LR 평가", "",
             "실험 ID: `EXPLR-LR6-PRE-SUPPLEMENT-20261106`. 현재 완료 촬영120구간 중 기존 기준 적격113구간만 "
             "사용했다. 기존24구간·P02 중단 실행·후속P5 보완 촬영은 포함하지 않았다. "
             "같은 두 사람의 반복 탐색자료이며 새 참가자 독립 검증이나 정식 평가가 아니다.", "",
             "## 고정 입력·평가", "",
             "F1,F3,F4,F6,F7,F8, C=1, L2(l1_ratio=0), lbfgs, tol=1e-4, max_iter=10000, "
             "intercept=True, class_weight=None, random_state=0. 기존 fixed_lr 생성기를 그대로 재사용했다. "
             "특징·가중치·규제·라벨·창·seed를 튜닝하지 않았다.", "",
             "기존 loader의 H9 공동지원 집계(F3 방향성 원형평균, 나머지 중앙값), 유효≥30프레임·coverage≥50%를 "
             "유지했다. 저장된 검토의 sample identity·라벨·support·적격성이 재집계와 일치했다. "
             "P01 53구간/P02 60구간이며 P5 support는각3/10이다. "
             "첫P0를 제외하거나 개인별 참조를 빼지 않았다. 이번은 기존 파일럿의 무보정 LR 경로다.", "",
             "참가자 단위 LOSO2fold: 학습60/시험53과 학습53/시험60. 같은 사람의 모든 반복은 한쪽에만 속한다. "
             "StandardScaler는 각 학습 fold에서만 fit하고 시험에는 transform만 적용했다. "
             "정확히2회 학습했으며 113개 OOF를 pool해 고정6-class 지표를 산출했다. "
             "참가자별 지표 평균·프레임 분류 정확도·훈련 정확도가 아니다.", "",
             f"환경: NumPy {saved['numpy']}, scikit-learn {saved['sklearn']}, native thread=1. "
             "학습 warning을 오류로 처리했으며 수렴 확인을 통과했다.", "",
             "## 전체 결과", "",
             "|지표|값|", "|---|---:|",
             f"|정답 / 평가 구간|{m['correct']} / {m['samples']}|",
             f"|Accuracy|{m['accuracy']:.2f}%|",
             f"|Macro-F1|{m['macro_f1']:.2f}%|",
             f"|Macro Precision|{m['macro_precision']:.2f}%|",
             f"|Macro Recall / Balanced Accuracy|{m['macro_recall']:.2f}%|",
             f"|Weighted-F1|{m['weighted_f1']:.2f}%|", "",
             "## 자세별 지표", "", "단위 %. support는 실제 평가 구간 수다.", "",
             "|자세|support|Precision|Recall|F1|", "|---|---:|---:|---:|---:|"]
    for r in m["per_class"]:
        lines.append(f"|{r['posture']} {r['label']}|{r['support']}|{r['precision']:.2f}|{r['recall']:.2f}|{r['f1']:.2f}|")
    lines += ["", "## 혼동행렬", "", "행=실제, 열=예측이며 P0~P5 순서다.", "",
              "|실제 / 예측|P0|P1|P2|P3|P4|P5|", "|---|---:|---:|---:|---:|---:|---:|"]
    for i,row in enumerate(m["confusion_matrix"]):
        lines.append(f"|P{i}|"+"|".join(map(str,row))+"|")
    lines += ["", "## 오류 유형", "", "|실제→예측|건수|", "|---|---:|"]
    flows = Counter((t,p) for t,p in zip(saved["labels"],saved["predictions"]) if t!=p)
    for (actual,predicted),count in sorted(flows.items()):
        lines.append(f"|P{actual}→P{predicted}|{count}|")
    if not flows:
        lines.append("|없음|0|")
    lines += ["", "## 해석의 한계", "",
              "- P01 P5 7구간은 얼굴 iris/턱 관측 결측으로 제외됐다. 값을 채우거나 기준을 완화하지 않았다. "
              "사용자는 과도한 고개 숙임으로 얼굴이 보이지 않았다고 보고했다. "
              "예측 오류에 따른 제외가 아니며 원본120구간과7개 실패 이력을 보존했다.",
              "- P0~P4는각20개, P5는13개다. P01을 학습하는 fold의 P5는3개뿐이다. "
              "이 불균형은 학습 경계와 P5 평가에 영향을 줄 수 있으므로120개 균형자료의 성능으로 보고하지 않는다.",
              "- Accuracy 한 건은약0.885pp, P0/P1 Recall 한 건은5pp다. 구간 수가 늘어도 독립 참가자는2명이다.",
              "- 기존24구간 결과와는 자료·반복·촬영 조건·제외 분모가 다르다. "
              "표시 점수 차이를 일반화 개선/악화의 확증으로 해석하지 않는다. 카메라 설치 metadata도unknown이다.",
              "- 자세 label은 수집 시 조작자가 지정한 값이며 영상 기반 수행 QA나 임상적 정확성을 검증하지 않았다. "
              "이전 모델 실행 비용은 별도12구간 학습 벤치마크이며 이번113구간에서 재측정하지 않았다.", "",
              "## 검증·보존", "",
              "대상113구간 identity/적격성·입력 hash·6열 순서·6-class support·참가자 분리·train-only scaler·"
              "고정 LR/수렴·OOF1회·직렬화 복원·저장 지표/CSV/MD 산술을 확인했다. "
              "전체 회귀 테스트·새 특징·하이퍼파라미터 탐색·다른 알고리즘 비교는 하지 않았다.", "",
              "실행 코드는 evaluate_new_pilot_lr6.py, 공개 요약은 이 보고서다. sample key·특징값·"
              "라벨·OOF·확률·점수·margin·참가자별 지표·fold scaler/계수/모델·입력 hash·사전계획은 "
              "local_private/에만 저장한다. 기존 파일·실시간 모델·공식8조합/B6/IRB HOLD/Patch8 보류를 유지했다. "
              "촬영·원본 영상 열람·commit/push는 하지 않았다.", "",
              "실행: `python -X utf8 -B evaluate_new_pilot_lr6.py`. 저장 검증만: 같은 명령에 `--verify` (학습 없음).", ""]
    return "\n".join(lines)


def verify():
    saved = read(OUT / "local_private/results.json")
    assert len(saved["labels"]) == len(saved["predictions"]) == 113
    assert metrics(saved["labels"],saved["predictions"]) == saved["metrics"]
    assert saved["lr_params"] == fixed_lr().get_params()
    assert saved["features"] == FEATURES
    seen = np.zeros(113,dtype=int)
    x = np.asarray(saved["matrix"])
    for f in saved["folds"]:
        tr,te = f["train"],f["test"]
        assert set(tr).isdisjoint(te) and set(tr)|set(te)==set(range(113))
        assert set(saved["subjects"][i] for i in tr).isdisjoint(saved["subjects"][i] for i in te)
        np.testing.assert_allclose(f["mean"],x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(f["scale"],x[tr].std(0),rtol=0,atol=1e-14)
        seen[te]+=1
    assert seen.tolist()==[1]*113
    for path,sha in saved["inputs"].items():
        assert digest(ROOT/path)==sha
    assert report(saved) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    with (OUT/"local_private/predictions.csv").open(encoding="utf-8",newline="") as stream:
        actual=list(csv.DictReader(stream))
    assert len(actual)==113
    for row,expected in zip(actual,prediction_rows(saved)):
        assert row=={k:str(v) for k,v in expected.items()}
    print("PASS: fixed 113 samples, participant LOSO/scalers, saved metrics/CSV/report/hashes; no fits")


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    review=read(REVIEW)
    for path,sha in review["inputs"].items():
        assert digest(ROOT/path)==sha
    runs=[r for r in review["inventory"] if r["status"]=="COMPLETED"]
    assert Counter(r["subject"] for r in runs)=={"P01":1,"P02":1}
    paths=[ROOT/r["directory"]/"features.csv" for r in runs]
    sources=[*paths,REVIEW,FACTORY,ROOT/"lr_posture_demo.py",ROOT/"h6_offline.py",
             ROOT/"f1_sample_aggregator.py",ROOT/"posture_geometry.py",Path(__file__).resolve()]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    all_samples=load_labeled_probe_h_samples(paths)
    prior={(s["subject"],tuple(s["sample_key"])):s for s in review["samples"]}
    assert len(all_samples)==120
    for s in all_samples:
        before=prior[(s.subject,s.sample_key)]
        assert s.label==before["label"] and s.eligible==before["eligible"]
        assert s.common_valid_count==before["common_valid"] and s.common_coverage==before["coverage"]
    samples=[s for s in all_samples if s.eligible]
    assert len(samples)==113
    x=np.array([[s.features[H9_FEATURE_NAMES[j]] for j in COLUMNS] for s in samples],dtype=float)
    y=np.array([LAB6.index(s.label) for s in samples],dtype=int)
    people=np.array([s.subject for s in samples])
    assert x.shape==(113,6) and np.isfinite(x).all()
    assert np.bincount(y,minlength=6).tolist()==[20,20,20,20,20,13]
    assert Counter(people)=={"P01":53,"P02":60}
    template=fixed_lr()
    private=OUT/"local_private"
    private.mkdir(parents=True,exist_ok=False)
    plan=dict(scope="EXPLORATORY_PILOT_ONLY",stage="PRE_SUPPLEMENT",sample_keys=[list(s.sample_key) for s in samples],
              features=FEATURES,lr_params=template.get_params(),input_hashes=hashes,
              excluded=[dict(subject=s.subject,sample_key=s.sample_key,label=s.label,reasons=s.eligibility_reasons)
                        for s in all_samples if not s.eligible],new_fits=2)
    write(private/"PLAN.json",plan)  # fixed before fitting
    hashes[str((private/"PLAN.json").relative_to(ROOT))]=digest(private/"PLAN.json")
    pred=np.full(113,-1,dtype=int)
    scores=np.zeros((113,6)); probabilities=np.zeros((113,6)); seen=np.zeros(113,dtype=int); folds=[]
    with threadpool_limits(limits=1),warnings.catch_warnings():
        warnings.simplefilter("error")
        for number,heldout in enumerate(("P01","P02")):
            tr,te=np.flatnonzero(people!=heldout),np.flatnonzero(people==heldout)
            assert set(y[tr])==set(range(6)) and set(y[te])==set(range(6))
            scaler=StandardScaler().fit(x[tr]); model=clone(template)
            assert int(scaler.n_samples_seen_)==len(tr) and model.get_params()==template.get_params()
            model.fit(scaler.transform(x[tr]),y[tr])
            assert np.all(model.n_iter_<model.max_iter)
            test=scaler.transform(x[te]); pred[te]=model.predict(test)
            scores[te]=model.decision_function(test); probabilities[te]=model.predict_proba(test); seen[te]+=1
            artifact=private/f"fold{number}.pkl"
            with artifact.open("xb") as stream: pickle.dump((model,scaler),stream,protocol=5)
            with artifact.open("rb") as stream: restored,restored_scaler=pickle.load(stream)
            np.testing.assert_array_equal(restored.predict(restored_scaler.transform(x[te])),pred[te])
            folds.append(dict(heldout=heldout,train=tr.tolist(),test=te.tolist(),
                              train_support=np.bincount(y[tr],minlength=6).tolist(),
                              test_support=np.bincount(y[te],minlength=6).tolist(),
                              mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                              coef=model.coef_.tolist(),intercept=model.intercept_.tolist(),n_iter=model.n_iter_.tolist(),
                              metrics=metrics(y[te],pred[te]),model_sha256=digest(artifact)))
    assert seen.tolist()==[1]*113
    margins=[float(scores[i,y[i]]-np.max(np.delete(scores[i],y[i]))) for i in range(113)]
    saved=dict(inputs=hashes,features=FEATURES,lr_params=template.get_params(),matrix=x.tolist(),
               labels=y.tolist(),subjects=people.tolist(),sample_keys=[list(s.sample_key) for s in samples],
               predictions=pred.tolist(),scores=scores.tolist(),probabilities=probabilities.tolist(),margins=margins,
               folds=folds,metrics=metrics(y,pred),numpy=np.__version__,sklearn=sklearn.__version__)
    for path,sha in hashes.items(): assert digest(ROOT/path)==sha
    write(private/"results.json",saved)
    with (private/"predictions.csv").open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["subject","sample_key","actual","predicted","margin","probabilities"])
        writer.writeheader();writer.writerows(prediction_rows(saved))
    with (OUT/"REPORT.md").open("x",encoding="utf-8") as stream: stream.write(report(saved))
    verify()
    print(json.dumps(saved["metrics"],ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
