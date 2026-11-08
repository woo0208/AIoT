"""Isolated, fixed seed-0 cost benchmark for the seven existing six-feature models.

python -X utf8 -B benchmark_six_feature_models.py
Append --verify for arithmetic/output checks only. Local models/derivatives stay private.
"""
import argparse
import gc
import itertools
import json
import os
from pathlib import Path
import pickle
import platform
import subprocess
import sys
import time
import warnings

from review_lr_features import digest, read
from lr_posture_demo import DATA, ROOT, fixed_lr, pilot_data
from compare_six_feature_rf import COLUMNS, FEATURES
from compare_six_feature_svm_knn import OUT as REFERENCE_OUT, factory

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_info, threadpool_limits
import engineering_exports as exports
from model_benchmark import run_benchmark
import performance_output as perf
from probe_timing import _stats, process_memory
import rf_experiment as rf

OUT = ROOT / "analysis/SIX_FEATURE_MODEL_COST_20261106"
REFERENCE = REFERENCE_OUT / "local_private/results.json"
NAMES = ("LR", "M0", "M1", "M2(λ=0.5)", "SVM-RBF", "Linear-SVM", "KNN")
REPEATS, WARMUP, CALLS = 3, 24, 120
CPU_MIN_SECONDS = .25


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def fit(name, matrix, y):
    if name.startswith("M"):
        m0 = rf.Forest(6, 500, 2, None, 0).fit(matrix, y)
        if name == "M0":
            return m0, None, None
        weights = rf.rank_weights(m0.mdi)
        if name == "M1":
            return rf.Forest(6, 500, 2, None, 0).fit(matrix * weights, y), None, weights
        split = .5 + .5 * weights / weights.mean()
        return rf.Forest(6, 500, 2, split, 0).fit(matrix, y), None, None
    scaler = StandardScaler().fit(matrix)
    model = fixed_lr() if name == "LR" else factory(name, 0)
    model.fit(scaler.transform(matrix), y)
    return model, scaler, None


def transform(payload, values):
    _, scaler, weights = payload
    if scaler is not None:
        values = scaler.transform(values)
    return values * weights if weights is not None else values


def predict(payload, values):
    return payload[0].predict(transform(payload, values))


def worker(name, fold_index, repetition, target):
    data, base, y = pilot_data()
    reference = read(REFERENCE)
    person = ("P02", "P01")[fold_index]
    people = np.asarray(data["subjects"])
    train, test = np.flatnonzero(people != person), np.flatnonzero(people == person)
    matrix = base[:, COLUMNS]
    assert len(train) == len(test) == 12 and set(train).isdisjoint(test)
    target.mkdir(exist_ok=False)
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.simplefilter("error", ConvergenceWarning)
        gc.collect()
        before = process_memory()
        cpu_start, start = time.process_time_ns(), time.perf_counter_ns()
        payload = fit(name, matrix[train], y[train])
        training_ns, training_cpu_ns = time.perf_counter_ns() - start, time.process_time_ns() - cpu_start
        gc.collect()
        after = process_memory()
        if payload[1] is not None:
            assert int(payload[1].n_samples_seen_) == 12
            np.testing.assert_allclose(payload[1].mean_, matrix[train].mean(0), rtol=0, atol=1e-14)
        if name in ("LR", "Linear-SVM"):
            assert np.all(np.asarray(payload[0].n_iter_) < payload[0].max_iter)
        if name == "SVM-RBF":
            assert payload[0].fit_status_ == 0
        expected = np.asarray(reference["predictions"][name][0])[test]
        np.testing.assert_array_equal(predict(payload, matrix[test]), expected)
        artifact = target / "model.pkl"
        with artifact.open("xb") as stream:
            pickle.dump(payload, stream, protocol=5)
        with artifact.open("rb") as stream:
            restored = pickle.load(stream)  # locally created model only
        np.testing.assert_array_equal(predict(restored, matrix[test]), expected)
        del restored
        raw_rows = [np.ascontiguousarray(row.reshape(1, 6)) for row in matrix[test]]
        transformed = [transform(payload, row) for row in raw_rows]
        identity = dict(scope="NON_FORMAL_ENGINEERING", run_id="SIX_FEATURE_MODEL_COST_20261106",
                        data_id="reused_24_segment_pilot", model_id=name,
                        config_id="fixed_six_features_seed0", config_sha256=exports.digest(FEATURES),
                        git=perf.git_identity(), environment=dict(perf.environment(), sklearn=sklearn.__version__,
                                                                threadpools=threadpool_info()))
        timings, memories = {}, {}
        enabled = gc.isenabled()
        gc.disable()
        try:
            for operation in ("classifier", "pipeline"):
                values = transformed if operation == "classifier" else raw_rows
                callback = (lambda p, it: p[0].predict(next(it))) if operation == "classifier" else (
                    lambda p, it: predict(p, next(it)))
                result = run_benchmark(target / operation, identity=identity,
                    input_value=itertools.cycle(values), input_id=f"heldout_fold{fold_index}",
                    input_sha256=digest(DATA), feature_order=FEATURES, seed=0,
                    model=payload, predict=callback, model_path=artifact, calls=CALLS, warmup_calls=WARMUP)
                assert result["run_status"] == "COMPLETED" and len(result["raw_inference_ns"]) == CALLS
                timings[operation] = result["raw_inference_ns"]
                memories[operation] = result["memory_observations"]
            # Separate CPU block: avoids including benchmark export/I/O in CPU time.
            count = 0
            cpu_start, start = time.process_time_ns(), time.perf_counter_ns()
            while True:
                for i in range(CALLS):
                    predict(payload, raw_rows[i % 12])
                count += CALLS
                if time.perf_counter_ns() - start >= CPU_MIN_SECONDS * 1e9:
                    break
            cpu_wall_ns, cpu_ns = time.perf_counter_ns() - start, time.process_time_ns() - cpu_start
        finally:
            if enabled:
                gc.enable()
        record = dict(model=name, fold=fold_index, repetition=repetition,
                      train=train.tolist(), test=test.tolist(), predictions=expected.tolist(),
                      training_ns=training_ns, training_cpu_ns=training_cpu_ns,
                      memory_before=before, memory_after=after, benchmark_memory=memories,
                      cpu_inference_wall_ns=cpu_wall_ns, cpu_inference_ns=cpu_ns, cpu_calls=count,
                      model_bytes=artifact.stat().st_size, model_sha256=digest(artifact),
                      raw_ns=timings, warnings=[str(w.message) for w in caught],
                      environment=identity["environment"])
        write(target / "record.json", record)


def summarize(records):
    output = {}
    for name in NAMES:
        own = [r for r in records if r["model"] == name]
        assert len(own) == REPEATS * 2
        samples = {operation: [ns for r in own for ns in r["raw_ns"][operation]]
                   for operation in ("classifier", "pipeline")}
        cpu_wall = sum(r["cpu_inference_wall_ns"] for r in own)
        cpu_ns = sum(r["cpu_inference_ns"] for r in own)
        output[name] = dict(training_ms=float(np.mean([r["training_ns"] for r in own])/1e6),
            training_cpu_ms=float(np.mean([r["training_cpu_ns"] for r in own])/1e6),
            model_bytes=float(np.mean([r["model_bytes"] for r in own])),
            classifier=_stats([v/1e6 for v in samples["classifier"]]),
            pipeline=_stats([v/1e6 for v in samples["pipeline"]]),
            predictions_per_second=len(samples["pipeline"])*1e9/sum(samples["pipeline"]),
            cpu_one_core_percent=100*cpu_ns/cpu_wall,
            cpu_ms_per_prediction=cpu_ns/1e6/sum(r["cpu_calls"] for r in own),
            private_after_mib=float(np.mean([r["memory_after"]["private_bytes"] for r in own])/2**20),
            rss_after_mib=float(np.mean([r["memory_after"]["rss_bytes"] for r in own])/2**20),
            private_delta_mib=float(np.mean([r["memory_after"]["private_bytes"]-r["memory_before"]["private_bytes"]
                                             for r in own])/2**20))
    return output


def report(saved):
    lines = ["# 동일6특징 7개 모델 실행 비용 비교", "",
             "입력: **F1,F3,F4,F6,F7,F8**. 기존 24구간/2인 LOSO의 학습12·시험12를 재사용한 "
             "비정식 오프라인 engineering benchmark다. 새 촬영·영상 열람·특징 변경·튜닝은 없다.", "",
             "## 측정 조건", "",
             "모델×fold×반복별 **별도 새 Python 프로세스**, 총 7×2×3=42프로세스를 순차 실행했다. "
             "모든 모델은 seed0으로 고정했다. 이는 새 seed 탐색이나 일반화 실험이 아닌 비용 반복 측정이다. "
             "반복/fold마다 모델 순서를 미리 정한 회전 순서로 바꿨다. "
             "패키지 import/프로세스 시작/I/O는 시간에서 제외하며 첫 학습 호출의 초기화 비용은 포함한다.", "",
             "LR/SVM/KNN은 기존 생성기·학습 fold StandardScaler를 사용했다. SVM gamma=1/9, KNN k=3 유지. "
             "RF는 500 trees/max_features2, M2 λ=0.5, 추가 scaler 없이 원래 입력을 사용했다. "
             "M1/M2 학습 시간·CPU에는 가중치 산출용 M0 학습과 순위 계산도 포함한다. "
             "학습한 M0를 재활용하지 않고 각 방법을 독립 학습하는 총비용이다.", "",
             "기존 model_benchmark.run_benchmark로 단일 구간 predict를 24회 warmup 후 120회 측정했다. "
             "12개 시험 입력을 순환하며 모델당 6프로세스에서 operation별 720개 시간을 pool했다. "
             "classifier는 변환 완료 입력, pipeline은 scaler 또는 M1 가중치 적용+predict다. "
             "GC는 추론 측정 중만 껐고 native thread=1이다.", "",
             "모델 크기는 실제 protocol5 pickle의 (classifier, scaler, M1 weights) 3-tuple bytes이며 "
             "환경·의존성·메타데이터는 제외한다. RF split weight는 모델 안에 포함된다. "
             "각 모델의 전체 시험 예측과 저장/복원 예측이 이전 seed0 결과와 정확히 같음을 확인했다.", "",
             f"환경: {saved['environment']['python']}, {saved['environment']['platform']}, "
             f"{saved['environment']['processor']}; logical CPU={os.cpu_count()}, "
             f"NumPy={np.__version__}, sklearn={sklearn.__version__}. 데스크톱 부하는 통제하지 않았다.", "",
             "## 시간·크기", "",
             "학습/크기는 6프로세스 평균, 추론은 720회 pooled p50/p95다. 단위 ms, KiB.", "",
             "|모델|학습 wall ms|학습 CPU ms|pipeline p50|pipeline p95|classifier p50|classifier p95|모델 KiB|",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r in saved["summary"].items():
        lines.append(f"|{name}|{r['training_ms']:.3f}|{r['training_cpu_ms']:.3f}|"
                     f"{r['pipeline']['p50']:.4f}|{r['pipeline']['p95']:.4f}|"
                     f"{r['classifier']['p50']:.4f}|{r['classifier']['p95']:.4f}|{r['model_bytes']/1024:.2f}|")
    lines += ["", "## 프로세스 CPU·메모리", "",
              "CPU는 별도 pipeline 반복 블록을 프로세스당 최소0.25초 실행해 process_time_ns로 측정했다. "
              "one-core %=100×process CPU/wall이며 작업관리자의 전체 시스템 CPU%와 다르다. "
              "메모리는 Windows GetProcessMemoryInfo의 학습 전/후 snapshot, 단위 MiB다. "
              "프로세스 전체가 포함되며 delta는 모델 전용 할당량이나 peak가 아니다.", "",
              "|모델|pipeline CPU ms/구간|one-core CPU %|학습후 RSS MiB|학습후 Private MiB|Private 전후차 MiB|",
              "|---|---:|---:|---:|---:|---:|"]
    for name, r in saved["summary"].items():
        lines.append(f"|{name}|{r['cpu_ms_per_prediction']:.4f}|{r['cpu_one_core_percent']:.1f}|"
                     f"{r['rss_after_mib']:.2f}|{r['private_after_mib']:.2f}|{r['private_delta_mib']:+.2f}|")
    lines += ["", "## 측정 범위·한계", "",
              "- 학습 wall/CPU 42개, 단일 추론 시간 10,080개(7×2 operations×720)를 측정했다. "
              "가중치 산출 의존성을 포함하면 RF forest 학습은30회, sklearn 학습은24회다.",
              "- CPU timer는 OS 해상도/스케줄링의 영향을 받는다. 작은 차이·0ms를 비용0이나 유의한 속도 차이로 해석하지 않는다.",
              "- 메모리 전후차는 allocator/캐시·학습 임시 메모리 잔류의 영향을 받는다. operation peak·모델 전용 메모리는 NOT_MEASURED.",
              "- MediaPipe/Depth 특징 추출·집계·camera-to-screen 지연·실제 D455 FPS·연속 앱 안정성은 NOT_MEASURED. "
              "아래 추론 시간으로 실제 영상 FPS나 센서 병목을 판단하지 않는다.",
              "- 같은 개발 데이터·작은 모델의 이 PC 관측이다. 반복은 독립 참가자나 통계적 유의성을 만들지 않는다.", "",
              "## 파일·검증", "",
              "실행 코드는 benchmark_six_feature_models.py다. 보고서만 공개 가능한 요약이며 모델 pickle·"
              "참가자 예측·입력 hash·프로세스별 원시 시간·benchmark JSON/CSV·메모리는 local_private/에 보관한다. "
              "기존 결과·실행 모델·공식8조합·B6·IRB HOLD·Patch8 실행 보류를 변경하지 않았다.", "",
              "기존 벤치마크 합성 테스트 6개 PASS. 입력 불변, 42프로세스 완주, 동일 예측/직렬화 복원, "
              "동일 호출수, 원시값→요약/MD 표 산술 일치를 확인했다. 전체 회귀 테스트는 실행하지 않았다.", "",
              "실행: `python -X utf8 -B benchmark_six_feature_models.py`. 저장 검증만: 같은 명령에 `--verify` (학습 없음).", ""]
    return "\n".join(lines)


def verify():
    saved = read(OUT / "local_private/results.json")
    assert len(saved["records"]) == 42
    assert summarize(saved["records"]) == saved["summary"]
    assert len({(r["model"], r["fold"], r["repetition"]) for r in saved["records"]}) == 42
    reference = read(REFERENCE)
    for record in saved["records"]:
        assert np.asarray(reference["predictions"][record["model"]][0])[record["test"]].tolist() == record["predictions"]
        assert all(len(record["raw_ns"][op]) == CALLS for op in ("classifier", "pipeline"))
        assert record["cpu_inference_wall_ns"] >= CPU_MIN_SECONDS*1e9
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    assert report(saved) in (OUT / "REPORT.md").read_text(encoding="utf-8")
    print("PASS: 42 processes, reference predictions, input hashes, raw metrics and report; no training")


def run():
    if OUT.exists():
        raise FileExistsError("Existing output preserved; use --verify")
    paths = (DATA, REFERENCE, ROOT / "lr_posture_demo.py", ROOT / "rf_experiment.py",
             ROOT / "compare_six_feature_svm_knn.py", ROOT / "compare_six_feature_rf.py",
             ROOT / "model_benchmark.py", ROOT / "probe_timing.py", Path(__file__).resolve())
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    prior = read(REFERENCE)
    for path, sha in prior["inputs"].items():
        assert digest(ROOT / path) == sha
    data, _, _ = pilot_data()
    assert prior["features"] == FEATURES
    for key in ("sample_keys", "subjects", "labels"):
        assert data[key] == prior[key]
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    records = []
    for repetition in range(REPEATS):
        for fold in range(2):
            offset = (repetition*2+fold) % len(NAMES)
            order = NAMES[offset:] + NAMES[:offset]
            for name in order:
                target = private / f"rep{repetition}_fold{fold}_{NAMES.index(name)}"
                command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()),
                           "--worker", name, str(fold), str(repetition), str(target)]
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                records.append(read(target / "record.json"))
                print(f"Completed {len(records)}/42: {name}, fold {fold+1}, repeat {repetition+1}", flush=True)
    saved = dict(inputs=hashes, records=records, summary=summarize(records), environment=perf.environment(),
                 git=perf.git_identity())
    for path, sha in hashes.items():
        assert digest(ROOT / path) == sha
    write(private / "results.json", saved)
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    print(json.dumps(saved["summary"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--worker", nargs=4)
    args = parser.parse_args()
    if args.worker:
        name, fold, repetition, target = args.worker
        worker(name, int(fold), int(repetition), Path(target))
    elif args.verify:
        verify()
    else:
        run()
