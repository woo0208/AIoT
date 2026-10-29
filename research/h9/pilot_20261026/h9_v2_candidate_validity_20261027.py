"""Read-only pilot diagnostics; no fitting, feature search, or input rewrites.

Run with python -B. Default prints an inspection summary; --write creates two
new artifacts exclusively. C2 values are computed only to verify availability.
"""
import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from f1_sample_aggregator import H9_FEATURE_NAMES, H_MIN_COVERAGE, H_MIN_VALID_FRAMES
from h6_offline import LAB6, POSTURE_IDS, analysis_label, load_labeled_probe_h_samples
from posture_geometry import Point3D, _sagittal_torso_lean_deg

STEM = "H9_v2_candidate_validity_20261027"
INPUTS = [ROOT / "captures" / n for n in (
    "P01_h9_20261024_170900.csv", "P02_h9_20261024_173954.csv")]
POSTURES = dict(zip(LAB6, POSTURE_IDS))
FEATURES = ("F4", "F8", "C1", "C3")
HEAD = ("left_eye", "right_eye", "left_ear", "right_ear", "nose", "chin")
SHOULDERS = ("left_shoulder", "right_shoulder")
HIPS = ("left_hip", "right_hip")


def git(*args):
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return dict(stdout=p.stdout.strip(), stderr=p.stderr.strip())


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def preservation_snapshot():
    paths = {ROOT / p for p in git("ls-files", "-z")["stdout"].split("\0") if p}
    paths.update(p for p in ROOT.iterdir() if p.is_file()
                 and p.suffix.lower() in (".csv", ".json", ".md", ".py"))
    for directory in ("captures", "analysis", "results", "models"):
        base = ROOT / directory
        if base.exists():
            paths.update(p for p in base.rglob("*") if p.is_file()
                         and "__pycache__" not in p.parts)
    paths.difference_update({Path(__file__).resolve(), OUT/(STEM+".json"), OUT/(STEM+".md")})
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths) if p.is_file()}


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def point(row, name):
    v = [number(row.get(f"{name}_3d_{a}_m")) for a in "xyz"]
    return np.array(v, dtype=float) if all(x is not None for x in v) else None


def reasons_for_points(row, names):
    reasons = []
    for name in names:
        for flag in ("landmark_valid", "depth_valid"):
            if row.get(f"{name}_{flag}", "").strip().lower() != "true":
                reasons.append(f"{name}:{flag}_not_true")
        if point(row, name) is None:
            reasons.append(f"{name}:xyz_missing_or_nonfinite")
    return reasons


def c1_value(s, h, e, w):
    u, v = h[1] - s[1], h[2] - s[2]
    length = math.hypot(u, v)
    if w is None or w <= 0 or length <= 0:
        return None
    value = (u * (s[2] - e[2]) - v * (s[1] - e[1])) / (length * w)
    return value if math.isfinite(value) else None


def candidates(row):
    reasons = {"C1": reasons_for_points(row, SHOULDERS + HIPS + ("left_ear", "right_ear")),
               "C3": reasons_for_points(row, SHOULDERS + HIPS),
               "C2": reasons_for_points(row, SHOULDERS + HEAD)}
    s, h, e = (point(row, n) for n in ("shoulder_midpoint", "hip_midpoint", "ear_midpoint"))
    w = number(row.get("shoulder_width_3d_m"))
    for name in ("C1", "C2"):
        if w is None or w <= 0:
            reasons[name].append("W_missing_nonfinite_or_nonpositive")
        if row.get("shoulder_width_3d_available", "").lower() != "true":
            reasons[name].append("shoulder_width_3d_unavailable")
    if s is None:
        for name in reasons:
            reasons[name].append("shoulder_midpoint_xyz_missing")
    if h is None:
        for name in ("C1", "C3"):
            reasons[name].append("hip_midpoint_xyz_missing")
    if e is None:
        reasons["C1"].append("ear_midpoint_xyz_missing")
    if s is not None and h is not None:
        if math.hypot(h[1] - s[1], h[2] - s[2]) <= 0:
            for name in ("C1", "C3"):
                reasons[name].append("L_nonpositive")
    c3 = number(row.get("sagittal_torso_lean_deg"))
    if c3 is None:
        reasons["C3"].append("stored_C3_missing_or_nonfinite")
    if row.get("sagittal_torso_lean_available", "").lower() != "true":
        reasons["C3"].append("stored_C3_unavailable")
    values = {"C1": None, "C3": None, "C2": None}
    if not reasons["C1"]:
        values["C1"] = c1_value(s, h, e, w)
        if values["C1"] is None:
            reasons["C1"].append("C1_arithmetic_nonfinite")
    if not reasons["C3"]:
        values["C3"] = c3  # Reuse saved value, never replace with recomputation.
    if not reasons["C2"]:
        q = np.mean([point(row, n) for n in HEAD], axis=0)
        value = float((s[1] - q[1]) / w)
        if math.isfinite(value):
            values["C2"] = value
        else:
            reasons["C2"].append("C2_arithmetic_nonfinite")
    return values, reasons


def self_checks():
    s, h, e, w = np.array([0., 0., 1.]), np.array([0., .5, 1.]), np.array([0., -.2, .9]), .4
    np.testing.assert_allclose(c1_value(s, h, e, w), .25)
    t = np.array([2., 3., 4.])
    np.testing.assert_allclose(c1_value(s+t, h+t, e+t, w), .25)
    np.testing.assert_allclose(c1_value(3*s, 3*h, 3*e, 3*w), .25)
    angle = .6
    r = np.array([[1., 0., 0.], [0., math.cos(angle), -math.sin(angle)],
                  [0., math.sin(angle), math.cos(angle)]])
    np.testing.assert_allclose(c1_value(r@s, r@h, r@e, w), .25)
    assert c1_value(s, s, e, w) is None and c1_value(s, h, e, 0.) is None
    np.testing.assert_allclose(c1_value(s, h, s + 2*(s-h), w), 0.)
    bad, reasons = candidates({})
    assert all(v is None for v in bad.values()) and all(reasons.values())
    row = {}
    pts = {n: e for n in HEAD}
    pts.update(left_shoulder=s+[-.2,0,0], right_shoulder=s+[.2,0,0],
               left_hip=h+[-.2,0,0], right_hip=h+[.2,0,0],
               shoulder_midpoint=s, hip_midpoint=h, ear_midpoint=e)
    for name, p in pts.items():
        row.update({f"{name}_3d_{a}_m": str(v) for a,v in zip("xyz",p)})
        row[f"{name}_landmark_valid"] = row[f"{name}_depth_valid"] = "True"
    row.update(shoulder_width_3d_m="0.4", shoulder_width_3d_available="True",
               sagittal_torso_lean_deg="9", sagittal_torso_lean_available="True")
    vals, _ = candidates(row)
    np.testing.assert_allclose([vals['C1'],vals['C2'],vals['C3']], [.25,.5,9.])
    for flag, expected_invalid in (("left_ear_depth_valid", {"C1","C2"}),
                                   ("left_hip_landmark_valid", {"C1","C3"}),
                                   ("left_eye_depth_valid", {"C2"})):
        vals, _ = candidates(dict(row, **{flag:"False"}))
        assert {k for k,v in vals.items() if v is None} == expected_invalid
    assert H_MIN_VALID_FRAMES == 30 and H_MIN_COVERAGE == .5
    assert eligible(30, 60)["eligible"] and not eligible(29, 60)["eligible"]
    assert not eligible(30, 61)["eligible"]
    np.testing.assert_array_equal(ranks([2, 1, 2]), [2.5, 1., 2.5])
    return "PASS: geometry sign/translation/scale/YZ rotation/axis/degeneracy, missing flags, eligibility boundaries, tied ranks (synthetic structural checks only)"


def eligible(n, total):
    reasons = []
    if n < H_MIN_VALID_FRAMES:
        reasons.append("valid_frames<30")
    if n / total < H_MIN_COVERAGE:
        reasons.append("coverage<0.5")
    return dict(valid_frames=n, total_frames=total, coverage=n/total,
                eligible=not reasons, ineligibility_reasons=reasons)


def stats(x):
    a = np.asarray(x, dtype=float)
    if not len(a):
        return dict(n=0)
    q = np.quantile(a, [.05, .25, .5, .75, .95], method="linear")
    return dict(n=len(a), minimum=float(a.min()), p05=float(q[0]), q25=float(q[1]),
                median=float(q[2]), q75=float(q[3]), p95=float(q[4]), maximum=float(a.max()))


def validity(frames):
    n = len(frames)
    out = dict(total_frames=n)
    for feature in ("C1", "C3", "C2"):
        valid = sum(f[feature] is not None for f in frames)
        out[feature] = dict(valid_frames=valid, invalid_frames=n-valid, rate=valid/n,
                            reason_counts=dict(Counter(r for f in frames for r in f["reasons"][feature])))
    out["C1_C3_joint"] = sum(f["C1"] is not None and f["C3"] is not None for f in frames)
    out["C1_C3_joint_rate"] = out["C1_C3_joint"] / n
    out["H9_valid"] = sum(f["h9_valid"] for f in frames)
    out["H9_C1_C3_joint"] = sum(f["h9_valid"] and f["C1"] is not None and f["C3"] is not None for f in frames)
    out["invalid_pattern_counts"] = dict(Counter(
        "+".join(k for k in ("C1", "C3", "C2") if f[k] is None) or "all_valid" for f in frames))
    return out


def ranks(a):
    a = np.asarray(a)
    order = np.argsort(a, kind="stable")
    result = np.empty(len(a))
    i = 0
    while i < len(a):
        j = i + 1
        while j < len(a) and a[order[j]] == a[order[i]]:
            j += 1
        result[order[i:j]] = (i + j + 1) / 2
        i = j
    return result


def correlations(rows, center=()):
    x = np.array([[r["features"][f] for f in FEATURES] for r in rows])
    if center:
        groups = defaultdict(list)
        for i, row in enumerate(rows):
            groups[tuple(row[k] for k in center)].append(i)
        for indices in groups.values():
            x[indices] -= x[indices].mean(axis=0)
    pairs = {}
    for i, j in itertools.combinations(range(len(FEATURES)), 2):
        a, b = x[:, i], x[:, j]
        p = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else None
        ra, rb = ranks(a), ranks(b)
        sp = float(np.corrcoef(ra, rb)[0, 1]) if np.std(ra) > 0 and np.std(rb) > 0 else None
        pairs[FEATURES[i] + ":" + FEATURES[j]] = dict(pearson=p, spearman=sp)
    return dict(n_segments=len(rows), descriptive_centering=list(center), pairs=pairs)


def overlap(a, b):
    lo, hi = max(min(a), min(b)), min(max(a), max(b))
    intersection = max(0., hi-lo)
    union = max(max(a), max(b))-min(min(a), min(b))
    return dict(a_min=min(a), a_max=max(a), b_min=min(b), b_max=max(b),
                ranges_overlap=bool(lo <= hi), signed_gap=lo-hi,
                range_intersection_over_union=intersection/union if union > 0 else None,
                b_minus_a_median=float(np.median(b)-np.median(a)),
                fraction_b_greater_a=float(np.mean([float(y>x)+.5*float(y==x) for x in a for y in b])))


def analyze():
    expected_hashes = ("1d8f0c7e40b87f750bb4a351f52ed55b083a1c37e777a2e9088f54111ded3122",
                       "6bbad505e9333e4029fe1be155e73ce745c9709077b57fda65eb49e3fc8b9f2e")
    assert tuple(digest(p) for p in INPUTS) == expected_hashes
    assert digest(ROOT / "h6_pilot_20261024_174708.json") == "850552faee27e6da61335f9dd6e5440dfe5c6f82b12d1f95386d318b14e22dd1"
    samples = load_labeled_probe_h_samples(INPUTS)
    base = json.loads((ROOT / "h6_pilot_20261024_174708.json").read_text(encoding="utf-8-sig"))
    assert POSTURES == dict(zip(base["class_order"], base["posture_ids"]))
    assert len(samples) == len(base["samples"]) == 24
    all_frames, groups = [], defaultdict(list)
    errors = Counter()
    maxima = Counter()
    for path in INPUTS:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            assert len(reader.fieldnames) == len(set(reader.fieldnames)) == 161
            for index, row in enumerate(reader, 1):
                assert None not in row and all(v is not None for v in row.values())
                values, reasons = candidates(row)
                f = dict(index=index, subject=row["subject"], recording_id=row["recording_id"],
                         segment_id=row["segment_id"], original_label=row["label"],
                         reasons=reasons, h9_valid=all(number(row[n]) is not None for n in H9_FEATURE_NAMES),
                         F4=number(row[H9_FEATURE_NAMES[3]]), F8=number(row[H9_FEATURE_NAMES[7]]), **values)
                if f["C3"] is not None:
                    s, h = point(row, "shoulder_midpoint"), point(row, "hip_midpoint")
                    actual = _sagittal_torso_lean_deg(Point3D(*h), Point3D(*s))
                    delta = abs(actual-f["C3"])
                    maxima["stored_C3_vs_existing_function_max_abs_deg"] = max(maxima["stored_C3_vs_existing_function_max_abs_deg"], delta)
                    assert delta < 1e-10
                # Validate saved proxies and scale against direct coordinates.
                for proxy, names in (("shoulder_midpoint", SHOULDERS), ("hip_midpoint", HIPS),
                                     ("ear_midpoint", ("left_ear", "right_ear"))):
                    points = [point(row, n) for n in names]
                    p = point(row, proxy)
                    if p is not None and all(v is not None for v in points):
                        assert np.allclose(p, np.mean(points, axis=0), rtol=0, atol=1e-12)
                if f["C1"] is not None:
                    w = number(row["shoulder_width_3d_m"])
                    assert abs(w-np.linalg.norm(point(row, SHOULDERS[1])-point(row, SHOULDERS[0]))) < 1e-12
                    s, h = point(row, "shoulder_midpoint"), point(row, "hip_midpoint")
                    f["W"] = w
                    f["L"] = math.hypot(h[1]-s[1], h[2]-s[2])
                    errors["C1_U_nonpositive"] += int(h[1] <= s[1])
                all_frames.append(f)
                if row["label"] not in ("PREP", "TRANSITION"):
                    f["posture_id"] = POSTURES[analysis_label(row["label"])]
                    groups[(row["recording_id"], row["segment_id"])].append(f)
    segments = []
    for sample, saved in zip(samples, base["samples"]):
        assert list(sample.sample_key) == saved["sample_key"]
        assert POSTURES[sample.label] == saved["posture_id"]
        frames = groups[(sample.sample_key[1], sample.sample_key[2])]
        support = [f for f in frames if f["h9_valid"]]
        assert [f["index"] for f in support] == list(sample.common_valid_frame_indices)
        assert len(frames) == sample.n_frames == saved["frame_count"]
        assert len(support) == sample.common_valid_count == saved["common_valid_frame_count"]
        assert sample.eligible == saved["eligible"]
        joint = [f for f in support if f["C1"] is not None and f["C3"] is not None]
        v = validity(frames)
        features = {"F4": sample.features[H9_FEATURE_NAMES[3]], "F8": sample.features[H9_FEATURE_NAMES[7]]}
        # Retain H9's sole circular exception F3. New scalar candidates use median.
        features.update({f: float(np.median([r[f] for r in joint])) if joint else None for f in ("C1", "C3")})
        for f in ("F4", "F8"):
            assert features[f] == float(np.median([r[f] for r in support]))
        c3s = [r["C3"] for r in joint]
        circular = math.degrees(math.atan2(sum(math.sin(math.radians(v)) for v in c3s),
                                          sum(math.cos(math.radians(v)) for v in c3s))) if c3s else None
        segments.append(dict(subject=sample.subject, recording_id=sample.sample_key[1],
                             segment_id=sample.sample_key[2], posture_id=POSTURES[sample.label],
                             original_label=frames[0]["original_label"], validity=v,
                             eligibility={f: eligible(v[f]["valid_frames"],len(frames)) for f in ("C1", "C3", "C2")},
                             joint_eligibility=eligible(v["C1_C3_joint"],len(frames)),
                             H9_C1_C3_eligibility=eligible(len(joint),len(frames)),
                             h9_eligible=sample.eligible, features=features,
                             common_frame_indices=[f["index"] for f in joint],
                             frame_distributions_on_common_support={f: stats([r[f] for r in joint]) for f in FEATURES},
                             C3_circular_mean_sensitivity_only=circular))
    assert all(s["H9_C1_C3_eligibility"]["eligible"] for s in segments)
    posture_frames = [f for fs in groups.values() for f in fs]
    target = [s for s in segments if s["posture_id"] in ("P0", "P1", "P5")]
    distributions, overlaps, corr = {}, {}, {}
    for scope in ("pooled", "P01", "P02"):
        rows = [s for s in target if scope == "pooled" or s["subject"] == scope]
        distributions[scope] = {p: {f: stats([s["features"][f] for s in rows if s["posture_id"] == p]) for f in FEATURES} for p in ("P0", "P1", "P5")}
        overlaps[scope] = {}
        for a, b in itertools.combinations(("P0", "P1", "P5"), 2):
            result = {f: overlap([s["features"][f] for s in rows if s["posture_id"] == a],
                                 [s["features"][f] for s in rows if s["posture_id"] == b]) for f in FEATURES}
            result["axis_aligned_rectangle_overlap"] = {
                "+".join(pair): all(result[f]["ranges_overlap"] for f in pair)
                for pair in (("F4", "F8"), ("C1", "C3"), ("F4", "F8", "C1", "C3"))}
            overlaps[scope][a+":"+b] = result
        for name, source in (("all24", segments), ("target12", target)):
            selected = [s for s in source if scope == "pooled" or s["subject"] == scope]
            corr[scope+":"+name] = correlations(selected)
    for name, source in (("all24", segments), ("target12", target)):
        corr["pooled:"+name+":within_subject"] = correlations(source, ("subject",))
        corr["pooled:"+name+":within_subject_class"] = correlations(source, ("subject", "posture_id"))
    shifts = {p: {f: dict(P02_minus_P01_median=distributions["P02"][p][f]["median"]-distributions["P01"][p][f]["median"],
                         participant_range_overlap=overlap([s["features"][f] for s in target if s["subject"] == "P01" and s["posture_id"] == p],
                                                          [s["features"][f] for s in target if s["subject"] == "P02" and s["posture_id"] == p])) for f in FEATURES} for p in ("P0", "P1", "P5")}
    summaries = {}
    for scope in ("pooled", "P01", "P02"):
        select = lambda fs: [f for f in fs if scope == "pooled" or f["subject"] == scope]
        summaries[scope] = dict(all_rows=validity(select(all_frames)), posture_rows=validity(select(posture_frames)),
                                H9_support=validity([f for f in select(posture_frames) if f["h9_valid"]]),
                                target_posture_rows=validity([f for f in select(posture_frames) if f["posture_id"] in ("P0", "P1", "P5")]),
                                non_evaluation_by_label={label: validity([f for f in select(all_frames) if f["original_label"] == label])
                                                         for label in ("PREP", "TRANSITION")
                                                         if any(f["original_label"] == label for f in select(all_frames))})
    frame_distributions = {scope: {p: {feature: stats([f[feature] for f in posture_frames
                           if f["posture_id"] == p and (scope == "pooled" or f["subject"] == scope)
                           and f["h9_valid"] and f["C1"] is not None and f["C3"] is not None])
                           for feature in FEATURES} for p in ("P0", "P1", "P5")}
                           for scope in ("pooled", "P01", "P02")}
    return dict(validity=summaries, segments=segments, distributions=distributions, overlaps=overlaps,
                frame_distributions=frame_distributions,
                participant_shifts=shifts, correlations=corr,
                C1_denominators_on_valid_posture_frames={k: stats([f[k] for f in posture_frames if f["C1"] is not None]) for k in ("W", "L")},
                checks=dict(baseline_sample_keys_support_counts_eligibility="PASS: 24 samples matched stored H6 artifact",
                            F4_F8_aggregation="PASS: exact medians equal existing aggregator", direct_proxy_and_width="PASS",
                            C3_reuse_and_formula="PASS", **dict(maxima), **dict(errors)),
                frame_values=[{k: f[k] for k in ("index", "subject", "recording_id", "segment_id", "posture_id", "C1", "C3", "F4", "F8")} for f in posture_frames])


def report(d):
    lines = ["# H9-v2 후보 특징 유효성 검증", "", "작성일: 2026-10-27. 동일한 P01/P02 파일럿의 탐색 결과다. 독립 검증·분류 성능·측정 정확도 결과가 아니다.", "",
             "## 방법과 보존 범위", "",
             "설계 보고서의 C1=[U(Sz−Ez)−V(Sy−Ey)]/(LW)를 각 프레임에서 계산했다. C3는 CSV의 sagittal_torso_lean_deg를 재사용했다. C2=(Sy−Qy)/W는 Face iris 468/473·Pose 귀/코·Face 턱의 6개 XYZ 평균으로 계산 가능성과 유효 여부만 확인했으며 값·분포·상관은 저장하거나 분석하지 않았다.", "",
             "두 성공 주 CSV만 사용했다. PREP/TRANSITION 제외, recording_id+segment_id로 구간을 구분하며 body_forward→P5의 기존 adapter를 유지했다. 기존 aggregate_h5_h9_sample을 통해 H9 support·F3 방향성 원형평균·나머지 8열 중앙값과 적격성(공동 유효 ≥30, coverage ≥50%)을 보존했다. C1/C3도 프레임별 계산 후 공동 support에서 중앙값으로 집계했다. C3는 이번 탐색에서 scalar 중앙값을 사용하며, 기존 F3의 원형평균 예외를 그대로 유지한다. JSON에는 C3 원형평균을 집계 선택의 민감도 참고치로만 함께 기록했다. 새 모델 계약을 동결하지 않는다.", "",
             "원본 valid flag가 true이고 필요한 XYZ가 finite인 경우만 후보 유효로 셌다. C1은 W>0/L>0, C2는 W>0를 요구하며 C3는 저장 availability와 값을 확인했다. 신규 confidence·작은 분모 임계값·보간·0 대입·개인별 P0 보정은 도입하지 않았다. 수학적 정의역 외에 관측 정확도 기준을 추가하지 않았다.", "",
             "연구 권위는 Research Master RQ4/RQ5, Decision Log CAP-009/FEAT-010, Schema §F.4/F.5를 참조했다. Engineering 161열과 canonical 60열을 구분하며 OPEN-002/003/005와 Patch 8 실행 보류는 그대로다. FEAT-010의 p=9 승인을 다른 차원으로 확대하지 않는다.", "",
             "## 프레임 유효율", "", "분모를 전체 행, 자세 유지 행, 기존 H9 support로 구분했다. 원인 count는 중복될 수 있으며 실패한 flag는 관측 상태이지 센서 결함의 원인을 확정하지 않는다.", "",
             "|대상|범위|전체 프레임|C1 유효|C3 유효|C1/C3 공동|C2 유효|", "|---|---|---:|---:|---:|---:|---:|"]
    for scope, scopes in d["validity"].items():
        for name in ("all_rows", "posture_rows", "H9_support", "target_posture_rows"):
            v = scopes[name]
            cell = lambda f: f"{v[f]['valid_frames']} ({100*v[f]['rate']:.2f}%)"
            lines.append(f"|{scope}|{name}|{v['total_frames']}|{cell('C1')}|{cell('C3')}|{v['C1_C3_joint']} ({100*v['C1_C3_joint_rate']:.2f}%)|{cell('C2')}|")
    lines += ["", "### 전체 행 결측 원인", ""]
    for scope in ("P01", "P02"):
        for f in ("C1", "C3", "C2"):
            v = d["validity"][scope]["all_rows"][f]
            lines.append(f"- {scope} {f}: 결측 {v['invalid_frames']}개; " + (", ".join(f"{k}={n}" for k,n in v['reason_counts'].items()) or "결측 없음"))
    lines += ["", "자세 유지 프레임에서는 결측 0개다. 전체 행의 C1/C3 결측 74개와 C2 결측 36개는 모두 PREP/TRANSITION에 있다. 원인별 flag count는 같은 프레임을 중복 집계하므로 합산하지 않는다. C1/C3의 경우 골반 관측 또는 depth 결측으로 몸통축을 구성할 수 없었고, C2는 P02의 양 iris·턱 관측이 없는 프레임이다. 프레임 상태만으로 가림·센서·실제 움직임 중 무엇이 원인인지 확정하지 않는다."]
    lines += ["", "### 구간별 적격성", "", "각 셀은 유효 수/전체 수다. H9+C1+C3의 동일 support를 분포·상관에 사용한다. C1/C3/C2 개별 적격 사유와 공동 적격 사유는 JSON에 모두 보존했다.", "", "|참가자|구간|자세|C1|C3|공동|H9+공동|C2|적격|", "|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for s in sorted(d["segments"], key=lambda s:(s["subject"],int(s["segment_id"]))):
        v, n = s["validity"], s["validity"]["total_frames"]
        counts = [v[f]["valid_frames"] for f in ("C1", "C3")] + [v["C1_C3_joint"],v["H9_C1_C3_joint"],v["C2"]["valid_frames"]]
        lines.append("|" + "|".join([s["subject"],s["segment_id"],s["posture_id"]]+[f"{c}/{n}" for c in counts]+["모두 적격" if all(x["eligible"] for x in s["eligibility"].values()) and s["H9_C1_C3_eligibility"]["eligible"] else "JSON 참조"]) + "|")
    lines += ["", "## P0/P1/P5 분포와 참가자 차이", "", "분석 단위는 자세 유지 구간이다. 전체 24구간 중 대상 자세는 12구간, 참가자·자세당 2구간이며 pooled 자세당 n=4다. 아래 중앙값 [최소, 최대]는 구간 대표값의 분포다. 프레임 분포는 JSON의 구간별 p05/q25/중앙값/q75/p95에 보존하며 프레임을 독립 표본으로 해석하지 않는다. F8 단위 m, C3 단위 °, F4/C1은 무차원이다.", "",
              "|대상|자세|n구간|F4|F8 (m)|C1|C3 (°)|", "|---|---|---:|---:|---:|---:|---:|"]
    for scope, classes in d["distributions"].items():
        for p, fs in classes.items():
            lines.append("|" + "|".join([scope,p,str(fs['C1']['n'])]+[f"{fs[f]['median']:.5f} [{fs[f]['minimum']:.5f}, {fs[f]['maximum']:.5f}]" for f in FEATURES]) + "|")
    lines += ["", "### 프레임 분포 (동일 support)", "", "중앙값 [p05, p95]. 자세당 프레임을 합친 기술 통계이며 구간 길이에 따라 가중되고 독립 표본 수가 아니다. 프레임 분포의 중첩과 구간 중앙값 범위의 분리는 동시에 나타날 수 있다.", "", "|대상|자세|프레임 수|F4|F8 (m)|C1|C3 (°)|", "|---|---|---:|---:|---:|---:|---:|"]
    for scope, classes in d["frame_distributions"].items():
        for p, fs in classes.items():
            lines.append("|"+"|".join([scope,p,str(fs['C1']['n'])]+[f"{fs[f]['median']:.5f} [{fs[f]['p05']:.5f}, {fs[f]['p95']:.5f}]" for f in FEATURES])+"|")
    lines += ["", "### 클래스 간 중첩", "", "gap=max(두 최소값)−min(두 최대값): 양수면 관측 범위가 분리, 0 이하면 접촉/중첩이다. IoU는 관측 min–max 구간 교집합 길이/합집합 길이다. P(B>A)는 모든 구간 쌍에서 B>A 비율(동률 0.5)이며 순서 진단일 뿐 학습·시험 정확도나 최적 방향 선택이 아니다.", "",
              "|대상|A:B|특징|gap|범위 중첩|IoU|P(B>A)|", "|---|---|---|---:|---|---:|---:|"]
    for scope, pairs in d["overlaps"].items():
        for pair, fs in pairs.items():
            for f in FEATURES:
                v = fs[f]
                lines.append(f"|{scope}|{pair}|{f}|{v['signed_gap']:.5f}|{'있음' if v['ranges_overlap'] else '없음'}|{v['range_intersection_over_union']:.3f}|{v['fraction_b_greater_a']:.3f}|")
    lines += ["", "2차원/4차원 축정렬 사각형의 중첩 여부도 JSON에 보존했다. 사각형 중첩은 결합 분포나 비선형 분리가 불가능하다는 증거가 아니며, 비중첩은 이 12구간 내 관측 범위만 설명한다.", "",
              "### 같은 자세의 참가자 이동", "", "P02−P01 구간 중앙값 차이이며, 중심화나 개인 보정에 사용하지 않았다.", "", "|자세|F4 차이|F8 차이 (m)|C1 차이|C3 차이 (°)|", "|---|---:|---:|---:|---:|"]
    for p, fs in d["participant_shifts"].items():
        lines.append("|" + "|".join([p]+[f"{fs[f]['P02_minus_P01_median']:+.5f}" for f in FEATURES]) + "|")
    lines += ["", "## F4/F8 대비 상관과 중복", "", "Pearson r / Spearman ρ를 구간 대표값으로 계산했다. target12와 all24를 분리하고, pooled 상관의 참가자/클래스 혼합 효과를 확인하도록 참가자별·참가자 중심화·참가자×클래스 중심화 진단을 병기했다. 중심화는 상관 진단에만 사용하며 모델 입력을 바꾸지 않았다. n=6의 참가자별 target 상관과 참가자×클래스당 2구간 잔차는 특히 불안정하다. 낮은 상관은 새 정보나 조건부 유용성의 증명이 아니고, 높은 상관도 대수적 동일성의 증명이 아니다.", "",
              "|범위|구간 수|F4:C1|F4:C3|F8:C1|F8:C3|C1:C3|F4:F8|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, v in d["correlations"].items():
        cells = []
        for pair in ("F4:C1", "F4:C3", "F8:C1", "F8:C3", "C1:C3", "F4:F8"):
            r = v["pairs"][pair]
            cells.append(f"{r['pearson']:+.3f} / {r['spearman']:+.3f}" if r['pearson'] is not None and r['spearman'] is not None else "정의 안 됨")
        lines.append("|"+"|".join([name,str(v['n_segments'])]+cells)+"|")
    lines += ["", "## 해석과 권장 구성", "", *d["interpretation"], "",
              "## 검증과 Git 상태", "", "- 독립 스크립트의 synthetic 구조 검증: " + d["checks"]["structural"],
              "- 실제 자료 대조: 저장 H6의 24개 sample key·frame support·유효 수·적격성이 일치. F4/F8은 기존 집계 함수의 중앙값과 정확히 일치. 저장 midpoint·W를 직접 XYZ와 대조했고, 저장 C3를 기존 geometry 함수와 대조했다.",
              f"- C3 재계산 최대 차이: {d['checks']['stored_C3_vs_existing_function_max_abs_deg']:.3g}°. 유효 C1 중 U≤0: {d['checks'].get('C1_U_nonpositive',0)}프레임.",
              "- 기존 H9 집계 회귀 테스트: " + d["checks"]["existing_tests"],
              f"- 기존 파일 SHA-256 보존 검사: {d['preservation']['checked_existing_files']}개, 변경 {len(d['preservation']['changed_files'])}개. 세 산출물 외 신규 파일 없음 확인은 종료 점검으로 수행했다.",
              f"- branch `{d['git']['branch']['stdout']}`, HEAD `{d['git']['head']['stdout']}`. `git status --short --untracked-files=all`: `{d['git']['status']['stdout'] or '(출력 없음)'}`. tracked/staged diff 없음. analysis/는 `.gitignore:7`에 포함되어 일반 status에 표시되지 않는다.",
              "- commit/push/staging, 재학습, 특징 선택 튜닝, 재촬영, H9-v2 모델 구현 없음. 기존 Git 전역 ignore 및 .pytest_cache 접근 경고는 환경 경고로 남기고 설정을 바꾸지 않았다.", "",
              "생성 파일:", "", f"- `{STEM}.md`: 분석·해석·권고", f"- `{STEM}.json`: 구간/프레임 값(C1/C3/F4/F8), 유효율·원인·적격성·분포·중첩·상관·입력 hash", "- `h9_v2_candidate_validity_20261027.py`: 독립 재현 스크립트 (`python -B ... --write`, 기존 출력이 있으면 중단)", "", "### 입력 파일 정체성", ""]
    for p in INPUTS:
        rel = p.relative_to(ROOT).as_posix()
        lines.append(f"- `{rel}` SHA-256 `{d['preservation']['sha256_before'][rel]}`")
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    targets = [OUT / (STEM+suffix) for suffix in (".json", ".md")]
    if args.write and any(p.exists() for p in targets):
        raise FileExistsError("Refusing to overwrite existing output")
    before = preservation_snapshot()
    structural = self_checks()
    d = analyze()
    d["checks"]["structural"] = structural
    if not args.write:
        print(json.dumps({k:v for k,v in d.items() if k not in ("frame_values", "segments")}, ensure_ascii=False, indent=2, allow_nan=False))
        return
    test = subprocess.run([sys.executable, "-B", "-m", "unittest", "test_h5_h9_evaluation.HAggregationTests", "-v"],
                          cwd=ROOT, capture_output=True, text=True)
    if test.returncode:
        raise RuntimeError(test.stdout+test.stderr)
    d["checks"]["existing_tests"] = "PASS: python -B -m unittest test_h5_h9_evaluation.HAggregationTests -v (4 tests, synthetic only)"
    d["checks"]["existing_test_output"] = test.stdout+test.stderr
    d["created_utc"] = datetime.now(timezone.utc).isoformat()
    d["environment"] = dict(python=platform.python_version(), numpy=np.__version__)
    d["method"] = dict(aggregation="H9 common support; medians for C1/C3; original F3 circular mean retained",
                       analysis_unit="posture segment; two participants; no independent validation",
                       correlation="Pearson + average-tie-rank Spearman; no p-values or fitting",
                       C2_scope="availability only; no C2 values/distributions/correlations stored",
                       definitions=dict(C1="[U*(Sz-Ez)-V*(Sy-Ey)]/(sqrt(U^2+V^2)*W)",
                                        C3="stored sagittal_torso_lean_deg", C2="(Sy-mean(head6_y))/W"))
    d["interpretation"] = interpretation(d)
    changed = [rel for rel, sha in before.items() if not (ROOT/rel).exists() or digest(ROOT/rel) != sha]
    assert not changed, changed
    d["preservation"] = dict(checked_existing_files=len(before), changed_files=changed, sha256_before=before)
    d["git"] = dict(branch=git("branch", "--show-current"), head=git("rev-parse", "HEAD"),
                    status=git("status", "--short", "--untracked-files=all"),
                    diff=git("diff", "--stat"), staged=git("diff", "--cached", "--stat"),
                    diff_check=git("diff", "--check"), ignored=git("check-ignore", "-v", str(targets[0].relative_to(ROOT))))
    assert not d["git"]["diff"]["stdout"] and not d["git"]["staged"]["stdout"]
    json_text = json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    md_text = report(d)
    for p, content in zip(targets, (json_text, md_text)):
        with p.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    print(json.dumps(dict(created=[p.relative_to(ROOT).as_posix() for p in targets],
                          preservation=d["preservation"]["checked_existing_files"], checks=d["checks"]), ensure_ascii=False, indent=2))


def interpretation(d):
    return [
        "**권장: 후속 검토의 우선 구성은 기존 F1~F8+C3(개념상 9열)로 두고 C1은 별도 보조 후보로 보존한다. C2는 이번 유효율 확인에서 종료한다.** 이는 이 자료의 정보 구조에 근거한 검토 우선순위이며 최적 특징 선택·성능 개선·새 입력 계약 승인 결론이 아니다. 기존 H9와 H9−F9를 비교 기준으로 유지하며 이번에 모델을 구현하거나 구성별로 학습하지 않았다.",
        "",
        "- C1/C3 각각 및 공동 유효는 P01 1,939/1,939, P02 1,674/1,674로 100%다. C2도 같은 3,613프레임에서 100%다. 모든 24구간은 126~196프레임/coverage 100%로 적격이며 기존 H9에서 후보 결측으로 추가 탈락한 프레임·구간은 없다. 이는 성공한 파일의 coverage이며 재촬영 실패 시도나 다른 참가자의 coverage를 추정하지 않는다.",
        "- C1은 P0→P1에서 양 참가자 모두 증가했다(중앙값 P01 0.34867→0.49945, P02 0.40382→0.58950). 합친 P0/P1 구간 대표값 범위는 겹치지 않는다. 다만 F8도 같은 구간 범위가 이미 분리돼 있으며, 무차원 C1의 gap과 m 단위 F8의 gap을 직접 비교해 분리도가 개선됐다고 말할 수 없다. 기존 LOSO P1 오류를 이 분포만으로 해소했다고 해석하지 않는다.",
        "- C1의 P1/P5 구간 대표값은 pooled에서 겹친다. P01은 P1 0.49945, P5 0.49049로 거의 같고 반복 범위도 겹친다. P02는 P1 0.58950, P5 0.51806으로 범위가 분리된다. 몸통축 보정이 모든 참가자에서 head-forward와 trunk-forward를 분리한다는 가설은 지지되지 않았다.",
        "- C3는 P1/P5 구간 대표값 범위를 두 참가자와 pooled에서 분리했다. P01 P1/P5 중앙값 −14.93975°/10.01404°, P02 −0.79765°/2.49400°다. F8의 P1/P5 범위가 P02와 pooled에서 겹치는 데 대해 몸통 방향 맥락을 제공한다. 그러나 F4도 이미 두 참가자의 P1/P5 구간 범위를 분리한다. F4+F8와 C1+C3 모두 대상 3개 클래스의 축정렬 사각형이 겹치지 않아, 이 12구간에서는 새 조합이 기존 조합보다 추가 분리됐다는 증거가 없다.",
        "- C3는 pooled P0/P1을 분리하지 못하고 P01에서도 반복 범위가 겹친다. 같은 P0의 참가자 차이가 +11.28315°, P1이 +14.14210°로 크며, P5에서는 −7.52004°로 이동 방향도 바뀐다. C1도 P02−P01이 P0 +0.05516, P1 +0.09005, P5 +0.02757로 이동했다. 공통 평행이동을 수식에서 제거해도 체형·자세 실행·설치각 등 참가자/세션 혼합 차이가 사라졌다는 근거는 없다. 설치각·촬영 조건의 원인을 구별할 수 없다.",
        "- C1과 F8은 target12 Pearson r=0.935/Spearman ρ=0.923, all24 r=0.929/ρ=0.960으로 높은 중복 신호를 보인다. target의 참가자별 r도 P01 0.943, P02 0.945다. 참가자 중심화 뒤 r=0.925로 단순 참가자 이동만의 상관도 아니다. C1의 기하학 정의는 F8과 다르지만 현재 파일럿에서는 우선적으로 둘 다 추가할 실증 근거가 약해 보조 후보로 둔다. 대수적 중복이나 완전한 대체 가능성을 단정하지 않는다.",
        "- C3와 F4는 target12 r=−0.827/ρ=−0.818(특히 P01 r=−0.990), C3와 F8은 r=0.708/ρ=0.713이다. 참가자×클래스 중심화 뒤 F4:C3 r=−0.396, F8:C1 r=0.620으로 변해, pooled 상관에 클래스/참가자 구조가 섞인다. C1:C3도 target r=0.487이지만 all24 r=0.779라 독립 특징이라고 부르지 않는다. C3를 우선하는 이유는 새 몸통 방향 표현과 F8의 P1/P5 중첩 보완 가능성이지 조건부 정보 증가나 정확도 향상 입증이 아니다.",
        "- F4/F8은 보존할 근거가 남는다. F4는 P1/P5 분리를 유지하고 F8은 P0/P1 신호를 가진다. 기존 F9는 F8의 어깨너비 정규화이며 기존 보고서의 높은 중복 결과를 비교 맥락으로 참조했다. 이번에는 F9 제거·새 구성의 우열을 재검증하지 않았다. F1~F8+C3는 F4/F8을 보존하며 몸통 방향을 검토하는 최소 후보안이다. C1까지 포함하는 안의 추가 가치는 별도 사전 명세와 독립 자료가 필요하다.",
        "- 유효 100%가 안정적 측정이라는 뜻은 아니다. P01:S1(P0)의 C3 p05/p95는 −16.91869°/+5.72208°, P01:S23(P5)는 −18.00482°/+9.22846°로 프레임 변동과 클래스 간 중첩이 있다. 구간 중앙값과 C3 원형평균의 최대 차이는 5.62585°(P01:S23)다. 기존 규칙을 유지하기 위해 프레임을 제거하거나 집계법을 바꾸지 않았다. 향후 집계 계약을 정할 때 고려할 관측이며 이번에 유리한 집계법을 선택하지 않는다.",
        "- C2는 전체 행에서 P01 3,613/3,613(100%), P02 2,517/2,553(98.59%), pooled 6,130/6,166(99.42%)다. 자세 유지에서는 둘 다 100%로 실제 계산 가능함을 확인했다. 유효율은 분류 유용성 근거가 아니며 C2의 값·분포·상관·본격 비교는 수행하지 않았다.",
        "- 이 파일럿으로 후보를 설계하고 다시 분석했으므로 재사용 편향이 있다. 참가자당 자세별 반복 2구간, 참가자 2명이며 프레임 수가 많아도 일반화 표본 수는 늘지 않는다. 임계값 탐색·유의확률·새 분류 정확도·특징 선택 튜닝은 수행하지 않았다. 권장 구성의 채택, M2 가중치/차원 승인, 실제 모델 구현은 이번 작업의 결론에 포함하지 않는다.",
    ]


if __name__ == "__main__":
    main()
