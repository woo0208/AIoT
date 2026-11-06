"""Fixed exploratory LR comparison; reads existing aggregate JSONs only.

Run with the prior benchmark's Python, -X utf8 -B. No raw-data loaders.
Every output is exclusive. Re-execution requires a new output directory.
"""
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
import ast
import csv
import gc
from functools import lru_cache
import hashlib
import importlib.metadata
import json
from pathlib import Path
import pickle
import platform
import subprocess
import sys
import time
import warnings

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_info, threadpool_limits

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DATA = ROOT / "analysis/research_h9_algorithms_20261029_7c3e91"
C3_PATH = ROOT / "analysis/h9/pilot_20261026/H9_v2_candidate_validity_20261027.json"
OLD = ROOT / "analysis/ALGORITHM_BENCHMARK_20261105_cb313c52"
NAMES = ("B0", "B1", "B2")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    with Path(path).open("x", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.write("\n")


def csv_write(path, rows):
    with Path(path).open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def relative(values, baseline):
    """Aggregate subtraction; directed F3 in [-180,180), never ratio/imputation."""
    result = np.asarray(values, dtype=np.float64) - baseline
    result[..., 2] = (result[..., 2] + 180.0) % 360.0 - 180.0
    return result


def references(data, segments):
    """Metadata-only chronology check, independent of numeric feature quality."""
    keys = [tuple(k) for k in data["sample_keys"]]
    by_key = {(s["subject"], s["recording_id"], s["segment_id"]): s for s in segments}
    if len(by_key) != len(keys) or len(set(keys)) != len(keys):
        raise ValueError("BLOCKED: duplicate/missing segment identity")
    refs, audit = {}, []
    for person in sorted(set(data["subjects"])):
        rows = []
        for i, (key, subject) in enumerate(zip(keys, data["subjects"])):
            if subject != person:
                continue
            s = by_key[(subject, key[1], key[2])]
            indices = s["common_frame_indices"]
            if not indices or indices != sorted(set(indices)):
                raise ValueError("BLOCKED: frame chronology unavailable")
            if key[0] != "probe-csv:" + key[1] or s["posture_id"] != f"P{data['labels'][i]}":
                raise ValueError("BLOCKED: identity/label mismatch")
            rows.append((min(indices), max(indices), i, s))
        if len({r[3]["recording_id"] for r in rows}) != 1:
            raise ValueError("BLOCKED: cross-recording chronology not established")
        rows.sort(key=lambda r: r[0])
        for a, b in zip(rows, rows[1:]):
            if a[1] >= b[0] or int(a[3]["segment_id"]) >= int(b[3]["segment_id"]):
                raise ValueError("BLOCKED: inconsistent segment/frame chronology")
        p0 = [r for r in rows if r[3]["posture_id"] == "P0"]
        if not p0 or rows[0][2] != p0[0][2]:
            raise ValueError("BLOCKED: no P0 preceding evaluated segments")
        refs[person] = p0[0][2]
        for lo, hi, i, s in rows:
            audit.append(dict(subject=person, source_index=i, sample_key=list(keys[i]),
                posture_id=s["posture_id"], first_frame=lo, last_frame=hi,
                is_reference=i == refs[person]))
    return refs, audit


def load():
    data = read(DATA / "samples.json")
    assert digest(DATA / "samples.json") == "69d64dca60a1f70ff60cd9663febc52b19d0e26540ffc97508ff3178a01deb20"
    candidate = read(C3_PATH)
    # Only segments (aggregates + provenance) are consumed. frame_values are unused.
    refs, audit = references(data, candidate["segments"])
    base = read(DATA / "inputs/h6_pilot_20261024_174708.json")
    assert candidate["preservation"]["sha256_before"]["h6_pilot_20261024_174708.json"] == digest(DATA / "inputs/h6_pilot_20261024_174708.json")
    assert candidate["checks"]["stored_C3_vs_existing_function_max_abs_deg"] == 0
    assert data["sample_keys"] == base["eligible_sample_keys"]
    X = np.asarray(data["matrix"], dtype=np.float64)[:, :8]
    lr = read(ROOT / "analysis/lr_fixed_comparison_20261029_b0r1w1/dataset.json")
    assert data["sample_keys"] == lr["sample_keys"] and data["labels"] == lr["labels"]
    np.testing.assert_array_equal(X, np.asarray(lr["matrix"])[:, :8])
    segments = {(s["subject"], s["recording_id"], s["segment_id"]): s for s in candidate["segments"]}
    c3 = []
    for i, (person, key, saved) in enumerate(zip(data["subjects"], data["sample_keys"], base["samples"])):
        assert saved["sample_key"] == key and saved["eligible"]
        s = segments[(person, key[1], key[2])]
        n = saved["frame_count"]
        # All historical supports coincide here; no new support/aggregation choice.
        assert s["h9_eligible"] and s["H9_C1_C3_eligibility"]["eligible"]
        assert s["validity"]["total_frames"] == s["validity"]["H9_valid"] == s["validity"]["H9_C1_C3_joint"] == n
        assert len(s["common_frame_indices"]) == saved["common_valid_frame_count"] == n
        assert s["features"]["F4"] == X[i, 3] and s["features"]["F8"] == X[i, 7]
        c3.append(s["features"]["C3"])
    raw = np.column_stack((X, c3))
    assert raw.shape == (24, 9) and np.isfinite(raw).all()
    keep = np.asarray([i for i in range(24) if i not in refs.values()])
    people, y = np.asarray(data["subjects"]), np.asarray(data["labels"])
    baselines = np.asarray([raw[refs[p]] for p in people])
    calibrated = relative(raw, baselines)
    assert len(keep) == 22 and list(np.bincount(y[keep], minlength=6)) == [2, 4, 4, 4, 4, 4]
    matrices = dict(B0=raw[:, :8], B1=calibrated[:, :8], B2=calibrated)
    return data, raw, matrices, people, y, refs, audit, keep


@lru_cache(maxsize=1)
def model_factory():
    # Reuse only the existing fixed LR constructor, never other models/loaders.
    path = DATA / "compare_fixed.py"
    node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == "make_model")
    ns = dict(LogisticRegression=LogisticRegression)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    return ns["make_model"]


def make_model():
    return model_factory()("Logistic-Regression", 0)


def score(y, pred):
    cm = confusion_matrix(y, pred, labels=range(6))
    support = cm.sum(1)
    assert np.all(support > 0)
    return dict(accuracy=float(np.trace(cm) / cm.sum()),
        macro_f1=float(f1_score(y, pred, labels=range(6), average="macro", zero_division=0)),
        recall=(np.diag(cm) / support).tolist(), confusion_matrix=cm.tolist(), support=support.tolist())


def environment():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
        cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0]
    return dict(python=platform.python_version(), executable=sys.executable, os=platform.platform(), cpu=cpu,
        packages={k: importlib.metadata.version(k) for k in ("numpy", "scikit-learn", "scipy", "matplotlib", "threadpoolctl")},
        threads=threadpool_info(), clock=vars(time.get_clock_info("perf_counter")),
        desktop_load="uncontrolled", power_plan="NOT_MEASURED")


def worker(run):
    dest = OUT / f"run_{run}"
    dest.mkdir(exist_ok=False)
    data, raw, matrices, people, y, refs, audit, keep = load()
    model_factory()  # Source parsing/compilation stays outside all timers.
    records = []
    predictions = {name: np.full(24, -1, dtype=int) for name in NAMES}
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        env = environment()
        for fold, heldout in enumerate(("P01", "P02")):
            train = keep[people[keep] != heldout]
            test = keep[people[keep] == heldout]
            assert len(train) == len(test) == 11
            assert not set(train) & set(test) and not (set(train) | set(test)) & set(refs.values())
            fitted = {}
            order = list(NAMES[(run + fold) % 3:] + NAMES[:(run + fold) % 3])
            for name in order:
                X = matrices[name]
                t0 = time.perf_counter_ns()
                model = make_model()
                scaler = StandardScaler().fit(X[train])
                model.fit(scaler.transform(X[train]), y[train])
                training_ns = time.perf_counter_ns() - t0
                assert int(scaler.n_samples_seen_) == 11
                np.testing.assert_allclose(scaler.mean_, X[train].mean(0), rtol=0, atol=1e-14)
                assert np.all(model.n_iter_ < model.max_iter)
                rows = [np.ascontiguousarray(X[j:j+1]) for j in test]
                raw_rows = [np.ascontiguousarray(raw[j:j+1, :X.shape[1]]) for j in test]
                baseline = np.ascontiguousarray(raw[refs[heldout], :X.shape[1]])
                transformed = [scaler.transform(row) for row in rows]
                pred = model.predict(np.concatenate(transformed))
                predictions[name][test] = pred
                payload = dict(model=model, scaler=scaler, scope="EXPLORATORY_LOSO_ONLY", variant=name,
                    feature_order=data["feature_order"][:8] + (["sagittal_torso_lean_deg"] if name == "B2" else []),
                    class_order=data["class_order"], train_subjects=sorted(set(people[train])),
                    calibration="none" if name == "B0" else "subtract own fixed first P0; F3 wrapped [-180,180)")
                path = dest / f"{name}_heldout_{heldout}.pkl"
                with path.open("xb") as f:
                    pickle.dump(payload, f, protocol=5)
                with path.open("rb") as f:
                    restored = pickle.load(f)
                np.testing.assert_array_equal(restored["model"].predict(restored["scaler"].transform(X[test])), pred)
                for i in range(24):
                    model.predict(transformed[i % 11])
                    model.predict(scaler.transform(rows[i % 11]))
                    if name != "B0":
                        relative(raw_rows[i % 11], baseline)
                fitted[name] = dict(model=model, scaler=scaler, rows=rows, raw_rows=raw_rows,
                    transformed=transformed, baseline=baseline, path=path, training_ns=training_ns,
                    raw_ns={k: [] for k in ("classifier", "pipeline", "calibration")})
            enabled = gc.isenabled()
            gc.disable()
            try:
                for i in range(120):
                    for name in order:
                        f = fitted[name]; j = i % 11
                        t0 = time.perf_counter_ns()
                        f["model"].predict(f["transformed"][j])
                        f["raw_ns"]["classifier"].append(time.perf_counter_ns() - t0)
                        t0 = time.perf_counter_ns()
                        f["model"].predict(f["scaler"].transform(f["rows"][j]))
                        f["raw_ns"]["pipeline"].append(time.perf_counter_ns() - t0)
                        if name != "B0":
                            t0 = time.perf_counter_ns()
                            relative(f["raw_rows"][j], f["baseline"])
                            f["raw_ns"]["calibration"].append(time.perf_counter_ns() - t0)
            finally:
                if enabled:
                    gc.enable()
            for name in NAMES:
                f = fitted[name]
                records.append(dict(name=name, run=run, heldout=heldout, train_indices=train.tolist(), test_indices=test.tolist(),
                    training_ns=f["training_ns"], raw_ns=f["raw_ns"], model_file=f["path"].name,
                    model_bytes=f["path"].stat().st_size, model_sha256=digest(f["path"]),
                    scaler_n_samples=11, scaler_mean=f["scaler"].mean_.tolist(),
                    scores=score(y[test], predictions[name][test])))
        warning_rows = [dict(category=w.category.__name__, message=str(w.message)) for w in caught]
    assert all(np.all(p[keep] >= 0) and np.all(p[list(refs.values())] == -1) for p in predictions.values())
    write(dest / "results.json", dict(scope="EXPLORATORY", environment=env, records=records, warnings=warning_rows,
        predictions={n: p[keep].tolist() for n, p in predictions.items()},
        scores={n: score(y[keep], p[keep]) for n, p in predictions.items()}, eligible_indices=keep.tolist(),
        references={p: data["sample_keys"][i] for p, i in refs.items()}))
    print(f"run {run}: 6 LR fits completed", flush=True)


def stats(ns):
    values = np.asarray(ns, dtype=float) / 1e6
    return dict(p50_ms=float(np.percentile(values, 50)), p95_ms=float(np.percentile(values, 95)),
                predictions_per_second=float(len(values) * 1000 / values.sum()), calls=len(values))


def summarize():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    runs = [read(OUT / f"run_{i}/results.json") for i in (1, 2, 3)]
    assert all(r["predictions"] == runs[0]["predictions"] for r in runs)
    rows, per_process = [], []
    for name in NAMES:
        s = runs[0]["scores"][name]
        records = [r for run in runs for r in run["records"] if r["name"] == name]
        resource = {k: stats([n for r in records for n in r["raw_ns"][k]]) for k in ("classifier", "pipeline")}
        cal = stats([n for r in records for n in r["raw_ns"]["calibration"]]) if name != "B0" else None
        baseline = runs[0]["scores"]["B0"]
        row = dict(model=name, scope="EXPLORATORY", status="MEASURED_THIS_RUN", n=22, features=9 if name == "B2" else 8,
            accuracy=s["accuracy"], macro_f1=s["macro_f1"], p0_recall=s["recall"][0], p1_recall=s["recall"][1], p5_recall=s["recall"][5],
            accuracy_delta_pp=100*(s["accuracy"]-baseline["accuracy"]), macro_f1_delta_pp=100*(s["macro_f1"]-baseline["macro_f1"]),
            p0_recall_delta_pp=100*(s["recall"][0]-baseline["recall"][0]), p1_recall_delta_pp=100*(s["recall"][1]-baseline["recall"][1]),
            p5_recall_delta_pp=100*(s["recall"][5]-baseline["recall"][5]),
            training_mean_ms=float(np.mean([r["training_ns"] for r in records])/1e6),
            training_min_ms=min(r["training_ns"] for r in records)/1e6, training_max_ms=max(r["training_ns"] for r in records)/1e6,
            model_bytes_mean=float(np.mean([r["model_bytes"] for r in records])),
            model_bytes_min=min(r["model_bytes"] for r in records), model_bytes_max=max(r["model_bytes"] for r in records),
            calibration_p50_ms=cal["p50_ms"] if cal else "NOT_APPLICABLE",
            calibration_p95_ms=cal["p95_ms"] if cal else "NOT_APPLICABLE",
            c3_extraction_cost="NOT_MEASURED", feature_extraction_cost="NOT_MEASURED",
            p0_acquisition_cost="NOT_MEASURED", reference_payload_bytes=72 if name == "B2" else 64 if name == "B1" else 0)
        for scope, values in resource.items():
            row.update({scope+"_"+k: v for k, v in values.items()})
        rows.append(row)
        for i, run in enumerate(runs, 1):
            rr = [r for r in run["records"] if r["name"] == name]
            per_process.append(dict(model=name, run=i, **stats([n for r in rr for n in r["raw_ns"]["pipeline"]])))
    csv_write(OUT / "comparison.csv", rows)
    csv_write(OUT / "resource_by_process.csv", per_process)
    cm_rows = [dict(model=n, actual=f"P{i}", **{f"pred_P{j}": v for j, v in enumerate(row)})
               for n in NAMES for i, row in enumerate(runs[0]["scores"][n]["confusion_matrix"])]
    csv_write(OUT / "confusion_matrices.csv", cm_rows)
    data, raw, matrices, people, y, refs, audit, keep = load()
    csv_write(OUT / "predictions.csv", [dict(model=n, source_index=int(i), subject=people[i],
        recording_id=data["sample_keys"][i][1], segment_id=data["sample_keys"][i][2], actual=f"P{y[i]}", predicted=f"P{p}")
        for n in NAMES for i, p in zip(keep, runs[0]["predictions"][n])])
    write(OUT / "results_summary.json", dict(comparison=rows, scores=runs[0]["scores"], class_order=data["class_order"]))
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    colors = ["#64748b", "#0284c7", "#d97706"]
    def grouped(filename, metrics, labels, title):
        fig, ax = plt.subplots(figsize=(8, 4.4), layout="constrained")
        x = np.arange(len(metrics)); width = .24
        for j, (row, color) in enumerate(zip(rows, colors)):
            values = [100*row[k] for k in metrics]
            bars = ax.bar(x + (j-1)*width, values, width, label=row["model"], color=color)
            ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=10)
        ax.set(xticks=x, xticklabels=labels, ylim=(0, 115), ylabel="%", title=title)
        ax.legend(loc="upper right", ncol=3)
        fig.savefig(OUT / filename, dpi=170); plt.close(fig)
    grouped("accuracy_f1.png", ["accuracy", "macro_f1"], ["Accuracy", "Macro-F1"], "EXPLORATORY | same 22 segments, two-person LOSO")
    grouped("recall_comparison.png", ["p0_recall", "p1_recall", "p5_recall"], ["P0 (n=2)", "P1 (n=4)", "P5 (n=4)"], "Recall | fixed first P0 references excluded")
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.8), layout="constrained")
    for ax, field, label in zip(axes.flat,
        ("training_mean_ms", "classifier_p50_ms", "pipeline_p50_ms", "pipeline_p95_ms", "pipeline_predictions_per_second", "model_bytes_mean"),
        ("Training mean (ms)", "Classifier p50 (ms)", "Scaler + LR p50 (ms)", "Scaler + LR p95 (ms)", "Predictions / second", "Serialized model (bytes)")):
        bars = ax.bar(NAMES, [r[field] for r in rows], color=colors)
        ax.bar_label(bars, fmt="%.3g", padding=3)
        ax.set_title(label); ax.margins(y=.22)
    fig.suptitle("EXPLORATORY | model inference; excludes calibration and feature extraction")
    fig.savefig(OUT / "resource_comparison.png", dpi=170); plt.close(fig)
    write_report(rows, runs, data)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def write_report(rows, runs, data):
    lines = ["# LR B0 → B1 → B2 — EXPLORATORY", "", "2026-11-05 · 실제 파일럿 집계 자료 직접 학습·평가 · 공식8조합/선정 규칙 변경 없음", "",
        "**공통 22구간 / 2명 LOSO**. P01/P02 각 첫 P0(segment 1) 총2구간을 모든 방법의 학습·평가에서 제외했다. 각 fold train11/test11, P0~P5 support=2/4/4/4/4/4. 세 방법 모두 구현·측정 완료.", "",
        "|방법|n|Accuracy %|Macro-F1 %|P0 Recall %|P1 Recall %|P5 Recall %|ΔAccuracy %p|ΔF1 %p|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"|{r['model']}|22|{100*r['accuracy']:.2f}|{100*r['macro_f1']:.2f}|{100*r['p0_recall']:.2f}|{100*r['p1_recall']:.2f}|{100*r['p5_recall']:.2f}|{r['accuracy_delta_pp']:+.2f}|{r['macro_f1_delta_pp']:+.2f}|")
    lines += ["", "아래 해석은 동일22구간의 B0 대비다. 과거24구간 B0 Accuracy87.5%는 비교 기준으로 사용하지 않았다.", "",
        "## 고정 구현과 참조 확인", "",
        "B0=기존 H9−F9 첫8열. B1=각 집계 특징−동일 참가자의 고정 첫 P0 특징. F3는 `(각도−참조+180)%360−180` 방향각 차이, 나머지는 원래 단위의 차이이며 비율 보정은 없다. 기존 F_cal의 참조 고정·차이 원칙만 재사용한 새 탐색 후보이며 F_cal 자체와 같다고 주장하지 않는다. B2=B1+C3의 동일 P0 대비 차이. C3는 기존 H9-v2가 사용하는 sagittal_torso_lean_deg이며 기존 검증 JSON의 scalar 중앙값을 그대로 사용했다. 공식 특징 계약 변경은 없다.", "",
        "Participant-specific reference identities and chronology remain in local reference_audit.json; they are excluded from this public checkpoint.", "",
        "C3의24구간 recording/segment/subject/label과 H6 identity가 일치하고 F4/F8 값도 정확히 일치했다. 기존 H9·C3·공동 support가 모든 구간에서 전체 자세 프레임과 같아 새 support 선택/재집계 없이22구간 모두 B2 적격이다. C3 원식은 `degrees(atan2(hip_z−shoulder_z, hip_y−shoulder_y))`; 과거 검증에서 저장값과 기존 함수 차이0°를 확인한 값을 재사용했다. 이번 원본/프레임 재처리는 없다.", "",
        "LR는 기존 make_model의 LR 분기 그대로: C=1, L2(l1_ratio=0), lbfgs, tol=1e−4, max_iter=10000, intercept=True, class_weight=None, random_state=0. StandardScaler는 각 train11개에서만 fit하고 n_samples_seen/평균을 검증했다. 허용된 heldout 첫 P0 외 통계·라벨·점수로 입력이나 모델을 보정하지 않았다. 3개 순차 프로세스에서 같은 고정 학습을 반복했으며 예측은 모두 같았다. 비용 반복은 연구 표본 증가가 아니다.", "",
        "클래스 매핑은 기존 파일럿 그대로: " + ", ".join(f"P{i}={label}" for i, label in enumerate(data["class_order"])) + ". body_forward 원라벨은 기존 adapter의 lean_forward(P5)와 같다.", "",
        "## 계산 비용", "", "|방법|학습 평균 ms|모델 p50/p95 ms|Scaler+LR p50/p95 ms|예측/s|파일 평균 bytes|보정 p50/p95 ms|", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        cal = "해당없음" if r["model"] == "B0" else f"{r['calibration_p50_ms']:.5f}/{r['calibration_p95_ms']:.5f}"
        lines.append(f"|{r['model']}|{r['training_mean_ms']:.3f}|{r['classifier_p50_ms']:.4f}/{r['classifier_p95_ms']:.4f}|{r['pipeline_p50_ms']:.4f}/{r['pipeline_p95_ms']:.4f}|{r['pipeline_predictions_per_second']:.1f}|{r['model_bytes_mean']:.0f}|{cal}|")
    env = runs[0]["environment"]
    lines += ["", f"환경: {env['cpu']} / {env['os']} / Python{env['python']} / " + ", ".join(f"{k} {v}" for k,v in env["packages"].items()) + ". 이전 benchmark와 동일 Python 실행파일·패키지·threadpool1 조건을 사용했다. desktop 부하/전원계획은 통제하지 않았다.", "",
        "이전 방법의 warmup24 / 단일1×d 입력120회 / perf_counter_ns(QPC) / GC off-restore / 모델 순서 회전 round-robin을 재사용했다. heldout11구간을 순환하며 각 방법3process×2fold=720회/scope. 학습시간은6회 fit 평균이며 기존 생성자 재사용, scaler fit/transform+LR fit 포함, 보정 배열 계산·I/O 제외다. 모델 생성자 재사용을 위한 AST 추출 비용도 포함되므로 순수 solver 시간은 아니다. pooled latency percentile(linear), 처리량=call수/측정 duration합이다. `resource_by_process.csv`에 프로세스별 변동을 분리했다.", "",
        "classifier=사전 scaling된 입력 predict. pipeline=scaler.transform+predict, 이미 보정된 집계 입력 사용. B1/B2 보정은 고정 참조 배열에 대한 차이+F3 wrap을 별도 timer로 직접 측정했다(참조 조회 제외). p50/p95의 차감이나 단순 합으로 전체 latency를 추정하지 않는다. C3 원본 계산·H9 특징 추출·P0 획득/집계 비용은 NOT_MEASURED. 전체 D455 FPS는 측정하지 않았다.", "",
        "파일은 실제 uncompressed pickle protocol5의 classifier+scaler+동일형태 metadata다. 코드/라이브러리/개인별 참조는 제외했다. 보정용 참조 float64 payload는 참가자당 B1 64bytes/B2 72bytes(컨테이너 overhead 제외). 모든18개 모델 파일을 다시 읽어 해당 fold 예측 일치를 확인했다. 정식 배포/최종 refit 모델이 아니다.", "",
        "## 6×6 혼동행렬", "", "행=실제, 열=예측; 순서 P0 P1 P2 P3 P4 P5. 각 행렬은 첫 프로세스의 두 fold pooled OOF22개이며 반복 합산이 아니다."]
    for n in NAMES:
        lines += ["", f"### {n}", "", "```text", "       P0 P1 P2 P3 P4 P5"]
        lines += [f"P{i}     " + "  ".join(map(str, row)) for i,row in enumerate(runs[0]["scores"][n]["confusion_matrix"])]
        lines += ["```"]
    lines += ["", "## 해석 및 한계", "", "개별 예측 변화와 참가자별 점수는 predictions.csv 및 run_1/results.json에 보관했다. B1−B0는 고정 개인 보정의 전체 효과, B2−B1은 이 설정에서 C3 추가의 전체 효과다. 개별 F1~F8 중 어느 열이 원인인지는 추가 ablation을 하지 않아 단정하지 않는다. P0 평가 표본은2개뿐이라 한 오류로 Recall이50%p 바뀌며, 2명 파일럿으로 통계적 우월성·외부 일반화를 주장할 수 없다. 비용은 소형 단일 호출의 Python/sklearn overhead와 desktop 변동을 포함한다. B1/B2는 탐색 후보이며 공식8조합·B6·IRB HOLD·CAP-007 상태는 유지한다.", "",
        "## 산출물·검증", "", "신규 폴더만 생성했다. measure.py=고정 비교·측정·보고서/그림 생성, test_experiment.py=원형 경계·참조 순서·누수/부적절 참조 거부 구조검증. comparison.csv=분류/개선량/비용, accuracy_f1.png·recall_comparison.png·resource_comparison.png=실측 그림. reference_audit.json=참조/순서/공통 적격 목록, measurement_conditions.json=입력 hash/환경 조건, run_1~3=실측 raw timing·OOF·fold 점수·모델파일, results_summary.json·predictions.csv·confusion_matrices.csv·resource_by_process.csv=검토 가능한 결과. 검증 실행 기록은 validation.json 및 structural_tests.log. 기존 파일 수정 없음.", "",
        "다음 작업 1개: 이22구간에서 B1/B2가 바꾼 P0/P1 오분류 사례를 저장 예측표로 검토한다(추가 학습 없음).", ""]
    with (OUT / "LR_B0_B1_B2_RESULTS.md").open("x", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def main():
    data, raw, matrices, people, y, refs, audit, keep = load()
    pins = [DATA/"samples.json", DATA/"PLAN.json", DATA/"compare_fixed.py", DATA/"inputs/h6_pilot_20261024_174708.json",
            C3_PATH, ROOT/"analysis/lr_fixed_comparison_20261029_b0r1w1/dataset.json", ROOT/"h9_v2.py",
            ROOT/"posture_geometry.py", ROOT/"f0_fcal_features.py", Path(__file__)]
    before = {str(p.relative_to(ROOT)): digest(p) for p in pins}
    write(OUT / "reference_audit.json", dict(status="CONFIRMED_BEFORE_EVALUATION", references={p:data["sample_keys"][i] for p,i in refs.items()},
        chronology=audit, eligible_indices=keep.tolist(), c3_status="AVAILABLE_ALL_24_AGGREGATES_SAME_SUPPORT", eligible_n=22))
    write(OUT / "measurement_conditions.json", dict(scope="EXPLORATORY", inputs=before,
        authorization="current explicit user request; pilot aggregate-only comparison; not formal execution",
        methods="B0 raw F1..F8; B1 subtract own first P0, F3 circular difference; B2 append C3 difference",
        split="two-person LOSO train11/test11; both references excluded", seed=0, tuning=False,
        processes=3, warmup=24, calls_per_fold_scope=120, threads=1, raw_data_used=False, external_data_used=False,
        c3_extraction_cost="NOT_MEASURED", camera_fps="NOT_MEASURED", model_parameters=make_model().get_params()))
    for run in (1,2,3):
        with (OUT / f"run_{run}.log").open("x", encoding="utf-8") as log:
            subprocess.run([sys.executable,"-X","utf8","-B",str(Path(__file__).resolve()),str(run)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(f"Completed sequential run {run}/3", flush=True)
    assert before == {str(p.relative_to(ROOT)):digest(p) for p in pins}
    summarize()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        worker(int(sys.argv[1]))
    else:
        main()
