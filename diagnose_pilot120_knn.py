"""Explain saved pilot120 KNN OOF using exact train-fold distances, without fits.

python -X utf8 -B diagnose_pilot120_knn.py [--verify]
Append an aggregate explanation to the existing report; private neighbors stay local.
"""
import argparse
from collections import Counter
from pathlib import Path

from review_lr_features import ROOT,read,digest
from compare_pilot120_linear_knn import OUT
from bundle_pilot120 import SOURCE
from evaluate_new_pilot_lr6 import write

import numpy as np

RESULT = OUT/"local_private/results.json"
DIAGNOSIS = OUT/"local_private/knn_diagnosis.json"
IDS = [f"F{i}" for i in range(1,10)]


def analyze():
    saved,data = read(RESULT),read(SOURCE)
    x,y = np.array(data["matrix"]),np.array(saved["labels"])
    knn,svm,lr = (np.array(saved["predictions"][name][0]) for name in ("KNN","SVM-RBF","LR9"))
    assert x.shape==(120,9) and saved["sample_keys"]==data["sample_keys"]
    assert all(p==knn.tolist() for p in saved["predictions"]["KNN"])
    records=[]
    for f in saved["folds"]:
        if f["model"]!="KNN" or f["seed"]!=0: continue
        assert f["params"]["n_neighbors"]==3 and f["params"]["weights"]=="uniform" and f["params"]["p"]==2
        tr,te=np.array(f["train"]),np.array(f["test"])
        mean,scale=np.array(f["mean"]),np.array(f["scale"])
        np.testing.assert_allclose(mean,x[tr].mean(0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(scale,x[tr].std(0),rtol=0,atol=1e-14)
        z=(x-mean)/scale
        for i in te:
            terms=(z[tr]-z[i])**2; squared=terms.sum(1); order=np.argsort(squared,kind="stable")
            neighbors=tr[order[:3]]; labels=y[neighbors]; votes=np.bincount(labels,minlength=6)
            assert votes.max()>=2 and votes.argmax()==knn[i]
            assert all(saved["subjects"][j]!=saved["subjects"][i] for j in neighbors)
            gap=float(squared[order[3]]-squared[order[2]])
            assert gap>0  # No boundary tie in selecting the third neighbor.
            actual=tr[y[tr]==y[i]]; other=tr[y[tr]!=y[i]]
            nearest_actual=actual[np.argmin(((z[actual]-z[i])**2).sum(1))]
            nearest_other=other[np.argmin(((z[other]-z[i])**2).sum(1))]
            contrast=(z[nearest_other]-z[i])**2-(z[nearest_actual]-z[i])**2
            records.append(dict(index=int(i),sample_key=saved["sample_keys"][i],subject=saved["subjects"][i],
                actual=int(y[i]),predicted=int(knn[i]),lr_prediction=int(lr[i]),svm_prediction=int(svm[i]),
                neighbor_indices=neighbors.tolist(),neighbor_labels=labels.tolist(),votes=votes.tolist(),
                true_votes=int(votes[y[i]]),distances=np.sqrt(squared[order[:3]]).tolist(),
                squared_distance_terms=terms[order[:3]].tolist(),third_fourth_squared_gap=gap,
                nearest_actual_index=int(nearest_actual),nearest_other_index=int(nearest_other),
                true_other_squared_distance_contrast=dict(zip(IDS,contrast.tolist()))))
    records.sort(key=lambda r:r["index"])
    assert [r["index"] for r in records]==list(range(120))
    masks=dict(all=np.ones(120,dtype=bool),p0p1=y<2,p2p5=y>=2,
        svm_corrected=(svm!=y)&(knn==y),lr_corrected=(lr!=y)&(knn==y),errors=knn!=y)
    summary={}
    for name,mask in masks.items():
        rows=[r for r in records if mask[r["index"]]]
        positive=Counter(); negative=Counter()
        for r in rows:
            contrast=r["true_other_squared_distance_contrast"]
            positive[max(contrast,key=contrast.get)]+=1
            negative[min(contrast,key=contrast.get)]+=1
        summary[name]=dict(n=len(rows),correct=sum(r["actual"]==r["predicted"] for r in rows),
            true_vote_counts=dict(sorted(Counter(str(r["true_votes"]) for r in rows).items())),
            neighbor_patterns=dict(sorted(Counter(",".join(f"P{c}" for c in r["neighbor_labels"]) for r in rows).items())),
            largest_positive_distance_contrast=dict(positive),largest_negative_distance_contrast=dict(negative))
    summary["p0p1_model_correct"]={name:int(np.sum(np.array(saved["predictions"][name][0])[y<2]==y[y<2]))
                                    for name in ("LR9","SVM-RBF","KNN")}
    return dict(records=records,summary=summary,feature_order=IDS,no_new_fits=True)


def explanation(s):
    q=s["summary"]; pair=q["p0p1_model_correct"]
    lines=["", "## KNN이 앞선 이유: 실제 이웃 진단", "",
        "diagnose_pilot120_knn.py로 저장된 train-only scaler와 원래 학습행을 사용해 거리/표결을 재계산했다. "
        "재학습·새 설정 실험은0회다. 각 시험구간의 표준화9차원 거리 "
        "`d²=sum_j((x_j−train_mean_j)/train_sd_j−(neighbor_j−train_mean_j)/train_sd_j)²`를 "
        "구하고 가장 가까운3개의 다수결을 복원했다. 120개 예측이 저장된KNN OOF와 정확히 같았으며 "
        "3번째/4번째 거리 동점과 표결 동점은없었다. 모든 이웃은시험 참가자와 다른 사람의 학습행이다.", "",
        "### 현재 자료로 직접 확인한 내용", "",
        "|대상|구간 수|실제 라벨을 지지한 이웃 수|해석|", "|---|---:|---|---|",
        f"|P2~P5|{q['p2p5']['n']}|전부3/3|9차원 가까운 이웃의 자세가 모두 정답이었다|",
        f"|SVM 대비 교정|{q['svm_corrected']['n']}|전부2/3|경계 부근P1 두 구간에서 이웃 다수결이 맞았다|",
        f"|LR 대비 교정|{q['lr_corrected']['n']}|전부2/3|P0/P1 경계 구간에서 국소 표결이 맞았다|",
        f"|남은 오류|{q['errors']['n']}|전부0/3|가까운 이웃3개가 모두 다른 자세였다|", "",
        f"전체 KNN 정답111/120 중103개는정답 이웃3개,8개는정답 이웃2개였다. "
        f"정상/거북목40개만 보면 LR {pair['LR9']}/40, SVM {pair['SVM-RBF']}/40, "
        f"KNN {pair['KNN']}/40이다. KNN의 전체92.50%와 이 두 자세만의77.50%를 구분해야 한다.", "",
        "SVM 대비교정2개 모두 이웃 라벨이 P1 두 개/P0 한 개였다. 그중한 개는가장 가까운1개가P0였지만 "
        "2~3번째가P1이라다수결이P1을선택했다. 이는현재k=3 판정의실제 설명이며 k=1 모델을추가 평가한것은아니다.", "",
        "LR은클래스별선형점수, SVM-RBF는고정C/gamma로학습한비선형경계, KNN은근처3개표결을사용한다. "
        "이번두P1구간에서는KNN의국소표결이SVM경계보다맞았다. 이를모든비선형경계보다KNN이우수하다는증명이나 "
        "SVM하이퍼파라미터가잘못됐다는결론으로해석하지않는다.", "",
        "### 특징 거리와 실패 원인 단서", "",
        "각구간에서가장가까운정답라벨행과가장가까운다른라벨행을비교해 "
        "`D_j=(z_j−z_other_j)²−(z_j−z_true_j)²`를분해했다. 양수는정답쪽이그특징에서가깝다는뜻이다. "
        "SVM대비교정2개에서는F7(어깨 대비 흉부 깊이)의양의항이가장컸고, "
        "F9(어깨너비로정규화한코–흉부깊이)의음의항이가장컸다. "
        "따라서정답지지신호와오답지지신호가함께있는구간이었다. 이분해는선택된두이웃사이의거리대조이며 "
        "모델전체의특징중요도나인과효과가아니다.", "",
        "남은9개오류도F9의음의거리대조항이가장컸다. 특히P1오류8개는가까운3개가모두P0, "
        "P0오류1개는모두P1이었다. KNN도현재특징에서반대자세와더가깝게보이는구간은해결하지못했다. "
        "이관찰만으로F9를제거해야한다고결정하거나새조합을시험하지않았다.", "",
        "### 아직 가설인 부분", "",
        "- 두사람의반복자료에서자세별국소군집이비교적안정적이라거리기반다수결에유리했을가능성이있다. "
        "P2~P5의이웃일치와경계8개교정이이를지지하지만새사람/새세션에서의우세는미확인이다.",
        "- 남은P0/P1오류는개인별기준값·수행·카메라/ROI차이가특징공간의위치를옮겼을가능성이있다. "
        "F8/F9 등연관된깊이특징이거리에서중복영향을줄가능성도있다. 물리원인과개별특징의제거효과는미확인이다.",
        "- KNN은SVM보다정답2개가많다. 두사람반복탐색에서의작은차이이며독립검증·보편적우월성의증거는아니다.", "",
        "개별이웃identity/거리/9특징별거리항/표결/대조는local_private/knn_diagnosis.json에만저장했다. "
        "기존모델·데이터·평가규칙을바꾸지않았고Commit/Push는하지않았다.", ""]
    return "\n".join(lines)


def verify():
    saved=read(DIAGNOSIS)
    for path,sha in saved["inputs"].items(): assert digest(ROOT/path)==sha
    actual=analyze(); assert all(saved[k]==v for k,v in actual.items())
    assert explanation(saved) in (OUT/"REPORT.md").read_text(encoding="utf-8")
    print("PASS: exact120 neighbor/vote reconstruction, participant separation, distance decompositions, hashes/report; no fits")


def run():
    if DIAGNOSIS.exists(): raise FileExistsError("Existing diagnosis preserved; use --verify")
    source=read(RESULT)
    for path,sha in source["inputs"].items(): assert digest(ROOT/path)==sha
    paths=[RESULT,SOURCE,ROOT/"compare_pilot120_linear_knn.py",Path(__file__).resolve()]
    inputs={str(p.relative_to(ROOT)):digest(p) for p in paths}
    saved=analyze(); saved["inputs"]=inputs
    # Conditions below make the generated explanatory text fail closed if data change.
    q=saved["summary"]
    assert q["p2p5"]["true_vote_counts"]=={"3":80}
    assert q["svm_corrected"]["true_vote_counts"]=={"2":2}
    assert q["lr_corrected"]["true_vote_counts"]=={"2":8}
    assert q["errors"]["true_vote_counts"]=={"0":9}
    assert q["svm_corrected"]["largest_positive_distance_contrast"]=={"F7":2}
    assert q["svm_corrected"]["largest_negative_distance_contrast"]=={"F9":2}
    assert q["errors"]["largest_negative_distance_contrast"]=={"F9":9}
    write(DIAGNOSIS,saved)
    with (OUT/"REPORT.md").open("a",encoding="utf-8") as stream: stream.write(explanation(saved))
    verify(); print(saved["summary"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
