"""One fixed F8 -> C1/TREAR comparison on the existing 120 pilot segments.

python -X utf8 -B compare_svm_fs3_f8_to_c1.py
python -X utf8 -B compare_svm_fs3_f8_to_c1.py --verify  # no fits or writes
Only the candidate's two LOSO folds are fitted. All derivatives stay private.
"""
import argparse
import ast
from collections import Counter
import csv
import math
import hashlib
from pathlib import Path
import pickle
import subprocess
import warnings

from compare_svm_fs3_t1_p1_weight import criteria, T0, FEATURE_RESULTS
from compare_svm_fs4_hp3d import BASE, BUNDLE, SOURCE, ROOT, digest, read, write
from compare_svm_fs4_hp3d import OUT as HP3D_OUT
from compare_svm_fs4_hp3d import factory, metrics, changes, verify_bundle, LAB6
from review_pilot120_seven_candidates import FEATURES, COLUMNS
from review_pilot_six_capture import csv_rows
from h6_offline import load_labeled_probe_h_samples
from f1_sample_aggregator import H_MIN_VALID_FRAMES, H_MIN_COVERAGE

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = ROOT / "analysis/SVM_FS3_F8_TO_C1_20261111"
REVIEW = ROOT / "analysis/P0_P1_METHOD_REVIEW_20261110"
OLD = ROOT / "analysis/h9/pilot_20261026/h9_v2_candidate_validity_20261027.py"
EXPERIMENT = "EXPLR-SVM-FS3-F8_TO_C1-20261111"
CANDIDATE = "SVM-FS3-F8_TO_C1-V0-T0"
C1_FEATURES = [*FEATURES[:6], "C1"]
POINTS = ("left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_hip", "right_hip")


def capture_source_proof(benchmark):
    """Bind the old capture source exactly; never waive data/model hash checks."""
    commit = "fa1a07c021c182a51896fb56468202ccc2232c46"
    blob = subprocess.check_output(["git", "show", f"{commit}:posture_geometry_probe.py"], cwd=ROOT)
    historical = blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    expected = benchmark["inputs"]["posture_geometry_probe.py"]
    assert hashlib.sha256(historical).hexdigest() == expected
    old = ast.parse(historical.decode("utf-8-sig"))
    current = ast.parse((ROOT / "posture_geometry_probe.py").read_text(encoding="utf-8-sig"))
    functions = lambda tree: {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    before, after = functions(old), functions(current)
    unchanged = sorted(set(before) - {"run_probe"})
    assert all(name in after and ast.dump(before[name]) == ast.dump(after[name]) for name in unchanged)
    proof = dict(path="posture_geometry_probe.py", historical_sha256=expected,
                 current_sha256=digest(ROOT / "posture_geometry_probe.py"),
                 historical_commit=commit, newline="CRLF", unchanged_helper_count=len(unchanged),
                 explanation="later E0/E1 capture instrumentation; all prior helpers outside run_probe unchanged; saved CSV and model predictions checked separately")
    return proof, historical


def load_baseline():
    """Replay saved T0, accounting explicitly for the later capture-only edit."""
    benchmark = read(BASE / "local_private/results.json")
    source = read(SOURCE)
    reference = read(FEATURE_RESULTS / "local_private/results.json")
    proof, _ = capture_source_proof(benchmark)
    for saved in (benchmark, source, reference):
        for path, sha in saved["inputs"].items():
            if path == "posture_geometry_probe.py":
                assert sha == proof["historical_sha256"]
            else:
                assert digest(ROOT / path) == sha, path
    baseline = read(HP3D_OUT / "local_private/results.json")["results"][T0]
    x = np.array(source["matrix"])[:, COLUMNS]
    y = np.array(source["labels"])
    assert x.shape == (120, 7) and np.bincount(y, minlength=6).tolist() == [20] * 6
    assert source["sample_keys"] == reference["sample_keys"] and source["labels"] == reference["labels"]
    pred = np.full(120, -1, dtype=int)
    seen = np.zeros(120, dtype=int)
    for number, fold in enumerate(baseline["folds"]):
        record = next(r for r in benchmark["records"] if r["model"] == "SVM-RBF" and r["repetition"] == 0 and r["fold"] == number)
        assert fold["model_path"] == record["model_path"] and fold["model_sha256"] == record["model_sha256"]
        assert fold["train"] == record["train"] and fold["test"] == record["test"]
        path = ROOT / fold["model_path"]
        assert digest(path) == fold["model_sha256"]
        with path.open("rb") as stream:
            model, scaler = pickle.load(stream)
        tr, te = fold["train"], fold["test"]
        assert len(tr) == len(te) == 60 and set(tr).isdisjoint(te)
        assert set(source["subjects"][i] for i in tr).isdisjoint(source["subjects"][i] for i in te)
        assert model.get_params() == fold["params"] == factory("SVM-RBF", 0).get_params()
        assert scaler.n_samples_seen_ == 60 and model._gamma == 1 / 9
        assert scaler.mean_.tolist() == fold["mean"] and scaler.scale_.tolist() == fold["scale"]
        np.testing.assert_allclose(scaler.mean_, x[tr].mean(0), rtol=0, atol=1e-14)
        np.testing.assert_allclose(scaler.scale_, x[tr].std(0), rtol=0, atol=1e-14)
        test = scaler.transform(x[te])
        pred[te] = model.predict(test)
        np.testing.assert_allclose(model.decision_function(test), np.array(baseline["scores"])[te], rtol=0, atol=1e-14)
        np.testing.assert_allclose(model._decision_function(test)[:, 0], np.array(baseline["pair01_scores"])[te], rtol=0, atol=1e-14)
        seen[te] += 1
    assert seen.tolist() == [1] * 120
    assert pred.tolist() == baseline["predictions"] == reference["predictions"]["H7_DROP_F2"]["SVM-RBF"][0]
    assert baseline["metrics"] == metrics(y, pred)
    return source, x, y, baseline, proof


def c1_value(s, h, e, width):
    """Existing C1 equation; validity guards fixed in the prior design review."""
    if not all(math.isfinite(v) for p in (s, h, e) for v in p):
        return None
    u, v = h[1] - s[1], h[2] - s[2]
    length = math.hypot(u, v)
    if not math.isfinite(width) or width <= 1e-6 or length <= 1e-6 or u <= 0:
        return None
    value = (u * (s[2] - e[2]) - v * (s[1] - e[1])) / (length * width)
    return value if math.isfinite(value) else None


def observations(row):
    points, reasons = {}, []
    for name in POINTS:
        if any(str(row.get(f"{name}_{flag}", "")).strip().lower() != "true"
               for flag in ("landmark_valid", "depth_valid")):
            reasons.append(f"{name}:invalid_flag")
        try:
            xyz = tuple(float(row[f"{name}_3d_{axis}_m"]) for axis in "xyz")
        except (KeyError, TypeError, ValueError):
            xyz = ()
        if len(xyz) != 3 or not all(math.isfinite(v) for v in xyz) or xyz[2] <= 0:
            reasons.append(f"{name}:invalid_xyz")
        else:
            points[name] = xyz
    if reasons:
        return None, tuple(reasons)
    mid = lambda a, b: tuple((x + y) / 2 for x, y in zip(points[a], points[b]))
    s = mid("left_shoulder", "right_shoulder")
    h = mid("left_hip", "right_hip")
    e = mid("left_ear", "right_ear")
    width = math.dist(points["left_shoulder"], points["right_shoulder"])
    return (s, h, e, width), ()


def frame_c1(row):
    geometry, reasons = observations(row)
    if geometry is None:
        return None, reasons
    value = c1_value(*geometry)
    return (value, ()) if value is not None else (None, ("invalid_axis_or_width",))


def replacement(x7, values):
    x = np.array(x7, dtype=float, copy=True)
    values = np.asarray(values, dtype=float)
    if x.ndim != 2 or x.shape[1] != 7 or values.shape != (len(x),):
        raise ValueError("one C1 value per original seven-feature sample required")
    if not np.isfinite(x).all() or not np.isfinite(values).all():
        raise ValueError("missing values must not be filled")
    x[:, 6] = values
    return x


def extract(source):
    paths = [ROOT / "captures" / recording / "features.csv"
             for recording in sorted({k[1] for k in source["sample_keys"]})]
    all_samples = load_labeled_probe_h_samples(paths)
    samples = {s.sample_key: s for s in all_samples}
    assert len(all_samples) == 127
    assert {s.sample_key for s in all_samples if s.eligible} == {tuple(k) for k in source["sample_keys"]}
    rows = {}
    for path in paths:
        for index, row in enumerate(csv_rows(path), 1):
            identity = (row["recording_id"], row["segment_id"], index)
            assert identity not in rows
            rows[identity] = row
    # Reuse only the old pure equation for an independent implementation check.
    node = next(n for n in ast.parse(OLD.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == "c1_value")
    scope = {"math": math}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(OLD), "exec"), scope)
    old_equation = scope["c1_value"]
    prior = read(REVIEW / "local_private/availability.json")
    prior_rows = {tuple(r["sample_key"]): r for r in prior["segments"]}
    quality, values, maximum_error = [], [], 0.0
    for i, key in enumerate(source["sample_keys"]):
        sample = samples[tuple(key)]
        assert sample.eligible and sample.subject == source["subjects"][i]
        assert sample.label == LAB6[source["labels"][i]]
        np.testing.assert_array_equal(sample.ordered_values("H9"), source["matrix"][i])
        valid, indices, failures = [], [], Counter()
        for index in sample.common_valid_frame_indices:
            row = rows[(key[1], str(key[2]), index)]
            value, reasons = frame_c1(row)
            if value is None:
                failures.update(reasons)
                continue
            geometry, _ = observations(row)
            difference = abs(value - old_equation(*geometry))
            assert difference <= 1e-12
            maximum_error = max(maximum_error, difference)
            valid.append(value)
            indices.append(index)
        before = prior_rows[tuple(key)]
        assert sample.n_frames == before["input_frames"] and sample.common_valid_count == before["h9_frames"]
        assert len(valid) == before["required_valid_frames"]
        assert len(valid) >= H_MIN_VALID_FRAMES and len(valid) / sample.n_frames >= H_MIN_COVERAGE
        value = float(np.median(valid))
        values.append(value)
        quality.append(dict(index=i, sample_key=key, input_frames=sample.n_frames,
                            h9_frames=sample.common_valid_count, valid_frames=len(valid),
                            coverage=len(valid) / sample.n_frames, valid_indices=indices,
                            median=value, failures=dict(failures), eligible=True))
    summary = dict(samples=len(quality), eligible=sum(r["eligible"] for r in quality),
                   h9_frames=sum(r["h9_frames"] for r in quality),
                   valid_frames=sum(r["valid_frames"] for r in quality),
                   minimum_frames=min(r["valid_frames"] for r in quality),
                   minimum_coverage=min(r["coverage"] for r in quality),
                   maximum_old_equation_difference=maximum_error)
    assert summary["valid_frames"] == prior["summary"]["required_valid_frames"]
    return values, dict(summary=summary, segments=quality), paths


def report(saved):
    a, b = (saved["results"][n]["metrics"] for n in (T0, CANDIDATE))
    c, q = saved["changes"], saved["quality"]["summary"]
    adopted = all(saved["adoption_checks"].values())
    lines = ["# FS3: F8 → C1/TREAR 단일 교체 비교", "",
             f"실험 ID: `{EXPERIMENT}`. 최신 적격120구간(기존113+기술적 보완7), 참가자2명, 2인 LOSO의 반복 탐색 결과다. 최초24구간·중단 촬영은 합치지 않았으며 독립 검증·일반화·유의성 결과가 아니다.", "",
             "## 고정 가설·평가", "",
             "기존 F8(흉부−코 깊이)을 몸통축 기준 귀 전방 잔차 C1/TREAR 한 열로 교체하면 P0 성능을 유지하며 P1 미탐을 줄일 수 있는가? 기존 C1 정의를 재사용하며 새로운 SVM 알고리즘을 제안한 실험이 아니다.", "",
             "기준은 F1,F3,F4,F5,F6,F7,F8, 후보는 F1,F3,F4,F5,F6,F7,C1이다. 첫6열의 기존 집계값은 그대로 보존했다. C1만 원래 H9 공동지원 프레임 중 필요한 관측이 유효한 프레임에서 계산 후 중앙값을 냈다. 개인 P0 보정·결측 채움·프레임 선택 튜닝은 없다.", "",
             "```text", "S=양 어깨 XYZ 중점; H=양 골반 XYZ 중점; E=양 귀 XYZ 중점",
             "W=3D 어깨너비; U=H_y-S_y; V=H_z-S_z; L=sqrt(U^2+V^2)",
             "C1_t=[U*(S_z-E_z)-V*(S_y-E_y)]/(L*W)",
             "C1_segment=median(valid C1_t in original H9 common support)", "```", "",
             "D455 XYZ(m), +Y 아래/+Z 멀어짐, C1 무차원. 필요한 6점의 landmark/depth valid·finite XYZ·양의 Z와 W,L>1e-6·U>0를 확인했다. 10초 집계·기존 H9 support·유효30프레임·coverage50% 적격 기준을 유지했다.", "",
             "같은120개 identity/라벨/순서, LOSO 각 train60/test60(클래스당10), StandardScaler는 train만 fit했다. SVM C=1, gamma=1/9, class_weight=None, probability=False, tol=1e-3, random_state=0 및 원래 생성기의 나머지 설정을 유지했다. gamma를1/7 또는scale로 바꾸지 않았다. T0 저장모델2개를 재사용하고 후보만2회 fit했다. 계획·조건·입력hash는 후보fit 전에 local_private/PLAN.json에 저장했다.", "",
             "채택 조건: P1≥80%, P0≥95%, P2~P5 각각100%, Accuracy≥T0(95%), Macro-F1≥T0 반올림 전 값. 모두 충족해야 채택하며 미달하면 T0 유지, 추가 후보 자동 탐색 없음.", "",
             "## 전체·자세별 결과", "",
             "|조건|정답/120|Accuracy %|Macro-F1 %|", "|---|---:|---:|---:|",
             f"|기존 T0|{a['correct']}/120|{a['accuracy']:.2f}|{a['macro_f1']:.2f}|",
             f"|F8→C1 후보|{b['correct']}/120|{b['accuracy']:.2f}|{b['macro_f1']:.2f}|", "",
             "|자세|support|T0 Recall %|교체 Recall %|변화 %p|", "|---|---:|---:|---:|---:|"]
    for old, new in zip(a["per_class"], b["per_class"]):
        lines.append(f"|{old['posture']} {old['label']}|{old['support']}|{old['recall']:.2f}|{new['recall']:.2f}|{new['recall']-old['recall']:+.2f}|")
    lines += ["", f"Accuracy 변화 {b['accuracy']-a['accuracy']:+.2f}%p, Macro-F1 변화 {b['macro_f1']-a['macro_f1']:+.2f}%p.", "",
              "## 오류 변화·채택 판단", "",
              f"예측 변경 {c['changed']}건: 오답→정답 {c['wrong_to_correct']}건, 정답→오답 {c['correct_to_wrong']}건, 오답→다른 오답 {c['wrong_to_wrong']}건.", "",
              "|실제 자세: 이전→교체 판정|건수|", "|---|---:|"]
    lines += [f"|{flow}|{count}|" for flow, count in c["flows"].items()] or ["|변경 없음|0|"]
    for name, m in (("기존 T0", a), ("F8→C1", b)):
        lines += ["", f"### {name} 혼동행렬", "", "행=실제, 열=예측, P0~P5 순서.", "", "```text",
                  *[" ".join(map(str, row)) for row in m["confusion_matrix"]], "```"]
    lines += ["", "|사전 채택 조건|충족|", "|---|---|"]
    lines += [f"|{key}|{'PASS' if value else 'FAIL'}|" for key, value in saved["adoption_checks"].items()]
    lines += ["", "**결정: " + ("교체 후보가 이번 개발 채택 조건을 충족했다." if adopted else "교체 후보 미채택, 기존 SVM-FS3-V0-T0 유지.") + "**", "",
              "## 적격성·검증·보존", "",
              f"원래 H9 공동지원 {q['h9_frames']:,}프레임 중 C1 유효 {q['valid_frames']:,}프레임, 120개 전부 적격이다. 최소 유효 {q['minimum_frames']}프레임, 최소 입력 coverage {100*q['minimum_coverage']:.2f}%다. 전일 관측 유효성 점검과 일치했고 기존 C1 원식과 최대 차이는 {q['maximum_old_equation_difference']:.3g}다. 기존120개 분모와 첫6열을 유지했다.", "",
              "원자료/모델/기존결과 hash, 원래 H9 집계와 지원 인덱스, 이전 T0 예측 재현, 후보7열과 첫6열 보존, train-only scaler, 고정SVM 설정/실제gamma, OOF1회, 저장모델 재예측, 지표·오류·CSV·보고서 일치를 검증했다. --verify는 추가fit 없이 저장결과를 재검산한다.", "",
              "과거 benchmark에 기록된 posture_geometry_probe.py는 이후 E0/E1 계측 추가로 현재 hash와 달랐다. 과거 hash에 정확히 일치하는 fa1a07c의 CRLF 원문을 Git에서 복원해 local_private/에 별도 보존했다. run_probe 외 기존 helper들의 AST가 같음을 확인하고, CSV·특징·모델·설정 hash 및 T0의120개 예측/점수를 별도로 재검증했다. 기존 파일이나 과거 hash 기록은 수정하지 않았다. 이 예외의 두 hash·commit·검증 근거는 계획/결과에 기록했다.", "",
              "실행한 구조 단위 테스트: `python -X utf8 -B -m unittest -v test_svm_fs3_f8_to_c1` — 4개 PASS. 부호/퇴화/EARZ 환원, 평행이동·배율·YZ 회전 불변성, 결측 flag/Depth 차단, 첫6열·원본 보존을 합성 입력으로 확인했다. 합성 검증은 실제120구간 분류 결과와 구분하며 전체 회귀 테스트는 실행하지 않았다.", "",
              "V=0,U>0이면 C1은EARZ와 같다. 과거 C1과F8의 높은 상관·P1/P5 중첩·골반결측 위험은 여전히 반대 근거다. 이번결과로 참가자 기준차의 인과적 원인이나 독립 일반화·임상적 타당성·논문 신규성을 확정하지 않는다. 성분별 인과 기여를 분리한 실험도 아니다.", "",
              "참가자별 특징·coverage·지원 프레임·판정 점수·오류 상세·모델/scaler·계획·입력hash는 local_private/에만 보관한다. 새 특징계산/집계의 실행비용·실시간FPS는 NOT_MEASURED다. 기존 원본 영상은 열지 않았고 촬영·실시간 모델 교체·다른 설정/특징 탐색을 하지 않았다. 공식8조합/B6/IRB HOLD/Patch8 실행보류는 유지했다. Commit·Push 없음.", "",
              "추가 코드: compare_svm_fs3_f8_to_c1.py, test_svm_fs3_f8_to_c1.py. 기존 실행 코드·데이터·보고서는 변경하지 않았다.", ""]
    return "\n".join(lines)


def verify():
    verify_bundle()
    saved = read(OUT / "local_private/results.json")
    source, x7, y, baseline, provenance = load_baseline()
    values, quality, _ = extract(source)
    x = replacement(x7, values)
    assert saved["matrix"] == x.tolist() and saved["quality"] == quality
    assert saved["features"] == C1_FEATURES and saved["new_fits"] == 2
    assert saved["results"][T0] == baseline
    assert saved["capture_source_proof"] == provenance
    assert digest(OUT / "local_private/historical_posture_geometry_probe.py") == provenance["historical_sha256"]
    for key in ("labels", "subjects", "sample_keys"):
        assert saved[key] == source[key]
    np.testing.assert_array_equal(x[:, :6], x7[:, :6])
    candidate = saved["results"][CANDIDATE]
    seen = np.zeros(120, dtype=int)
    for number, fold in enumerate(candidate["folds"]):
        before = baseline["folds"][number]
        tr, te = fold["train"], fold["test"]
        assert tr == before["train"] and te == before["test"] and len(tr) == len(te) == 60
        assert set(tr).isdisjoint(te)
        assert set(source["subjects"][i] for i in tr).isdisjoint(source["subjects"][i] for i in te)
        assert np.bincount(y[tr], minlength=6).tolist() == [10] * 6
        path = ROOT / fold["model_path"]
        assert digest(path) == fold["model_sha256"]
        with path.open("rb") as stream:
            model, scaler = pickle.load(stream)
        assert model.get_params() == before["params"] == factory("SVM-RBF", 0).get_params()
        assert model._gamma == 1 / 9 and model.n_features_in_ == 7 and model.fit_status_ == 0
        assert scaler.n_samples_seen_ == 60
        np.testing.assert_array_equal(model.class_weight_, np.ones(6))
        np.testing.assert_allclose(scaler.mean_, x[tr].mean(0), rtol=0, atol=1e-14)
        np.testing.assert_allclose(scaler.scale_, x[tr].std(0), rtol=0, atol=1e-14)
        assert scaler.mean_.tolist() == fold["mean"] and scaler.scale_.tolist() == fold["scale"]
        np.testing.assert_allclose(scaler.mean_[:6], before["mean"][:6], rtol=0, atol=1e-14)
        np.testing.assert_allclose(scaler.scale_[:6], before["scale"][:6], rtol=0, atol=1e-14)
        test = scaler.transform(x[te])
        np.testing.assert_array_equal(model.predict(test), np.array(candidate["predictions"])[te])
        np.testing.assert_allclose(model.decision_function(test), np.array(candidate["scores"])[te], rtol=0, atol=1e-14)
        np.testing.assert_allclose(model._decision_function(test)[:, 0], np.array(candidate["pair01_scores"])[te], rtol=0, atol=1e-14)
        seen[te] += 1
    assert seen.tolist() == [1] * 120
    for result in saved["results"].values():
        assert result["metrics"] == metrics(y, result["predictions"])
    assert saved["adoption_checks"] == criteria(candidate["metrics"], baseline["metrics"])
    assert saved["selected"] == (CANDIDATE if all(saved["adoption_checks"].values()) else T0)
    assert saved["changes"] == changes(y, baseline["predictions"], candidate["predictions"])
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    plan = read(OUT / "local_private/PLAN.json")
    assert plan["params"] == factory("SVM-RBF", 0).get_params() and plan["features"] == C1_FEATURES
    assert plan["sample_keys"] == source["sample_keys"] and plan["new_fits"] == 2 and plan["baseline_fits"] == 0
    with (OUT / "local_private/features.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 120
    np.testing.assert_array_equal([[float(r[f]) for f in C1_FEATURES] for r in rows], x)
    with (OUT / "local_private/predictions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 240
    for row in rows:
        i = int(row["index"])
        assert int(row["actual"]) == y[i]
        assert int(row["predicted"]) == saved["results"][row["condition"]]["predictions"][i]
    assert (OUT / "REPORT.md").read_text(encoding="utf-8") == report(saved)
    print("PASS: exact120/H9 support, original C1 equation, first6 preserved, train-only scalers, fixedSVM, OOF/models/criteria/CSV/report/hashes; no fits")


def run():
    if OUT.exists():
        raise FileExistsError("Existing outputs preserved; use --verify")
    verify_bundle()
    source, x7, y, baseline, provenance = load_baseline()
    values, quality, raw_paths = extract(source)
    x = replacement(x7, values)
    paths = [SOURCE, BASE / "local_private/results.json", BUNDLE / "samples.csv", BUNDLE / "bundle_info.json",
             REVIEW / "REPORT.md", REVIEW / "local_private/availability.json", OLD,
             HP3D_OUT / "local_private/results.json", ROOT / "posture_geometry_probe.py",
             Path(__file__).resolve(), ROOT / "test_svm_fs3_f8_to_c1.py", *raw_paths]
    paths += [ROOT / fold["model_path"] for fold in baseline["folds"]]
    for name in ("compare_svm_fs3_t1_p1_weight.py", "compare_svm_fs4_hp3d.py", "compare_six_feature_svm_knn.py",
                 "h6_offline.py", "f1_sample_aggregator.py", "compare_lr_f2_f5.py", "evaluate_new_pilot_lr6.py"):
        paths.append(ROOT / name)
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    _, historical = capture_source_proof(read(BASE / "local_private/results.json"))
    snapshot = private / "historical_posture_geometry_probe.py"
    with snapshot.open("xb") as stream:
        stream.write(historical)
    inputs[str(snapshot.relative_to(ROOT))] = digest(snapshot)
    write(private / "PLAN.json", dict(experiment=EXPERIMENT, scope="EXPLORATORY_SINGLE_F8_REPLACEMENT",
          features=C1_FEATURES, baseline_features=FEATURES, sample_keys=source["sample_keys"],
          definition="existing C1/TREAR frame equation, median on original H9 intersect candidate-valid support; first6 unchanged",
          params=factory("SVM-RBF", 0).get_params(), quality=quality, input_hashes=inputs, capture_source_proof=provenance,
          new_fits=2, baseline_fits=0, validity="six valid positive-Z XYZ points; W,L>1e-6; U>0; >=30 and input coverage>=0.5",
          adoption=dict(p1_recall_min=80, p0_recall_min=95, p2_p3_p4_p5_recall=100,
                        accuracy_min=baseline["metrics"]["accuracy"], macro_f1_min=baseline["metrics"]["macro_f1"], all_required=True),
          failure_action="retain T0; no other feature/setting search"))
    inputs[str((private / "PLAN.json").relative_to(ROOT))] = digest(private / "PLAN.json")
    pred = np.full(120, -1, dtype=int)
    scores, pair, folds = np.zeros((120, 6)), np.zeros(120), []
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.simplefilter("error", ConvergenceWarning)
        for number, before in enumerate(baseline["folds"]):
            tr, te = before["train"], before["test"]
            scaler = StandardScaler().fit(x[tr])
            model = factory("SVM-RBF", 0)
            assert model.get_params() == before["params"]
            np.testing.assert_allclose(scaler.mean_[:6], before["mean"][:6], rtol=0, atol=1e-14)
            np.testing.assert_allclose(scaler.scale_[:6], before["scale"][:6], rtol=0, atol=1e-14)
            model.fit(scaler.transform(x[tr]), y[tr])
            assert model.fit_status_ == 0 and model._gamma == 1 / 9
            test = scaler.transform(x[te])
            pred[te] = model.predict(test)
            scores[te] = model.decision_function(test)
            pair[te] = model._decision_function(test)[:, 0]
            path = private / f"C1_fold{number}.pkl"
            with path.open("xb") as stream:
                pickle.dump((model, scaler), stream, protocol=5)
            folds.append(dict(number=number, train=tr, test=te, mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                              model_path=str(path.relative_to(ROOT)), model_sha256=digest(path),
                              n_support=model.n_support_.tolist(), fit_status=int(model.fit_status_)))
    candidate = dict(predictions=pred.tolist(), scores=scores.tolist(), pair01_scores=pair.tolist(),
                     folds=folds, metrics=metrics(y, pred))
    checks = criteria(candidate["metrics"], baseline["metrics"])
    saved = dict(experiment=EXPERIMENT, inputs=inputs, features=C1_FEATURES, matrix=x.tolist(), quality=quality, capture_source_proof=provenance,
                 labels=source["labels"], subjects=source["subjects"], sample_keys=source["sample_keys"], new_fits=2,
                 results={T0: baseline, CANDIDATE: candidate}, adoption_checks=checks,
                 selected=CANDIDATE if all(checks.values()) else T0,
                 changes=changes(y, baseline["predictions"], pred.tolist()),
                 warnings=dict(Counter(f"{w.category.__name__}: {w.message}" for w in caught)),
                 numpy=np.__version__, sklearn=sklearn.__version__)
    write(private / "results.json", saved)
    with (private / "features.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["index", "label", *C1_FEATURES])
        writer.writeheader()
        writer.writerows(dict(index=i, label=int(y[i]), **dict(zip(C1_FEATURES, row.tolist()))) for i, row in enumerate(x))
    with (private / "predictions.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["condition", "index", "actual", "predicted"])
        writer.writeheader()
        for name, result in saved["results"].items():
            writer.writerows(dict(condition=name, index=i, actual=int(y[i]), predicted=p) for i, p in enumerate(result["predictions"]))
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    print(dict(baseline=baseline["metrics"], candidate=candidate["metrics"], changes=saved["changes"], checks=checks, selected=saved["selected"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    verify() if parser.parse_args().verify else run()
