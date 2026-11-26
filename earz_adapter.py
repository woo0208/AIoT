"""Saved-probe EARZ adapter for EXPLR-H9-EARZ-20261106 (no training).

Run: python -B earz_adapter.py --probe-csv saved_a.csv saved_b.csv \
    --h9-samples samples.json --support-json candidate_validity.json \
    --output-dir analysis/EXPLR-H9-EARZ-20261106
Tests: python -B -m unittest test_earz_adapter

Reuse the saved output of posture_geometry.compute_candidate_geometry:
ear_midpoint_forward_normalized_by_shoulder_width_3d. That function divides
the shoulder-minus-ear *sensor depth* by metric 3D shoulder width. RealSense
camera +Z points away; depth and deprojected Z describe the same axis, but
SDK float32 deprojection can introduce rounding. We verify the requested
(shoulder_midpoint_z - ear_midpoint_z) / shoulder_width_3d against saved XYZ
within propagated float32 roundoff, and retain the original feature value.
All lengths are metres; EARZ is dimensionless and positive toward the camera.
Missing values are never filled. Outputs contain private derivatives: keep local.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

from f1_sample_aggregator import H9_FEATURE_NAMES
from h6_offline import NON_EVALUATION_LABELS, load_labeled_probe_h_samples


EXPERIMENT_ID = "EXPLR-H9-EARZ-20261106"
EARZ_FEATURE = "ear_midpoint_forward_normalized_by_shoulder_width_3d"
POINTS = ("left_ear", "right_ear", "left_shoulder", "right_shoulder")


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def frame_earz(row):
    """Return (saved value or None, failure reasons, absolute XYZ formula error)."""
    reasons, points = [], {}
    for name in POINTS:
        for flag in ("landmark_valid", "depth_valid"):
            if str(row.get(f"{name}_{flag}", "")).lower() != "true":
                reasons.append(f"{name}:{flag}_not_true")
        xyz = tuple(number(row.get(f"{name}_3d_{axis}_m")) for axis in "xyz")
        if any(value is None for value in xyz) or xyz[2] <= 0:
            reasons.append(f"{name}:xyz_missing_or_invalid")
        else:
            points[name] = xyz
    width = number(row.get("shoulder_width_3d_m"))
    if width is None or width <= 1e-6:  # Existing geometry's distance guard.
        reasons.append("shoulder_width_3d_invalid")
    if str(row.get("shoulder_width_3d_available", "")).lower() != "true":
        reasons.append("shoulder_width_3d_unavailable")
    value = number(row.get(EARZ_FEATURE))
    if value is None:
        reasons.append("stored_earz_missing_or_nonfinite")
    if reasons:
        return None, tuple(reasons), None
    expected_width = math.dist(points["left_shoulder"], points["right_shoulder"])
    if not math.isclose(width, expected_width, rel_tol=1e-12, abs_tol=1e-12):
        return None, ("stored_shoulder_width_mismatch",), None
    shoulder_z = (points["left_shoulder"][2] + points["right_shoulder"][2]) / 2
    ear_z = (points["left_ear"][2] + points["right_ear"][2]) / 2
    expected = (shoulder_z - ear_z) / width
    error = abs(value - expected)
    # IEEE-754 float32 relative epsilon propagated from the two midpoint Zs.
    # Numerical consistency bound only; no scientific acceptance threshold.
    roundoff = (2 ** -23) * (abs(shoulder_z) + abs(ear_z)) / width + 1e-12
    if not math.isfinite(expected) or error > roundoff:
        return None, ("stored_earz_xyz_formula_mismatch",), error
    return value, (), error


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def segment_key(row):
    return tuple(str(row[name]).strip() for name in ("subject", "recording_id", "segment_id"))


def unique_segments(rows):
    result = {}
    for row in rows:
        key = segment_key(row)
        if not all(key) or key in result:
            raise ValueError("duplicate or empty segment identity")
        result[key] = row
    return result


def adapt(probe_paths, h9_path, support_path):
    """Reproduce unchanged H9 aggregation and bind EARZ to its exact CSV rows.

    H9 frame indices are 1-based CSV data-row ordinals, including PREP and
    TRANSITION rows in the numbering. Timestamp pairs additionally detect
    duplicate observations. Compare actual indices with the saved support
    artifact, whose preservation hashes bind those ordinals to exact CSV bytes;
    equal counts alone never establish equal support.
    """
    paths = [Path(path) for path in probe_paths]
    inputs = [*paths, Path(h9_path), Path(support_path)]
    before = [digest(path) for path in inputs]
    samples = load_labeled_probe_h_samples(paths)
    saved, support = read_json(h9_path), read_json(support_path)
    preserved = support["preservation"]["sha256_before"]
    for path, sha in zip(paths, before):
        matches = [value for name, value in preserved.items()
                   if name.replace("\\", "/").split("/")[-1] == path.name]
        if not matches or set(matches) != {sha}:
            raise ValueError("probe CSV differs from saved support source hash")
    if saved["feature_order"] != list(H9_FEATURE_NAMES):
        raise ValueError("saved H9 feature order mismatch")
    n = len(saved["sample_keys"])
    if any(len(saved[field]) != n for field in ("subjects", "matrix", "labels")):
        raise ValueError("saved H9 sample lengths mismatch")
    expected = {}
    for i, (subject, key) in enumerate(zip(saved["subjects"], saved["sample_keys"])):
        if len(key) != 3 or key[0] != f"probe-csv:{key[1]}":
            raise ValueError("saved H9 sample key mismatch")
        identity = (subject, key[1], key[2])
        if identity in expected:
            raise ValueError("duplicate saved H9 sample")
        expected[identity] = i
    prior = unique_segments(support["segments"])
    current = {(s.subject, s.sample_key[1], s.sample_key[2]): s for s in samples}
    if len(current) != len(samples) or set(current) != set(expected) or set(prior) != set(expected):
        raise ValueError("saved/current/support segment identities mismatch")

    rows = {key: {} for key in current}
    for path in paths:
        timestamps, closed, previous = set(), set(), None
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for index, row in enumerate(reader, 1):
                # The legacy loader already validates headers, row shape and identity.
                if row["label"].strip() in NON_EVALUATION_LABELS:
                    continue
                key = segment_key(row)
                if key != previous:
                    if key in closed:
                        raise ValueError("noncontiguous duplicate segment")
                    if previous is not None:
                        closed.add(previous)
                    previous = key
                stamp = (row["timestamp_utc"], row["device_timestamp_ms"])
                if not stamp[0].strip() or number(stamp[1]) is None or stamp in timestamps:
                    raise ValueError("missing or duplicate frame timestamp")
                timestamps.add(stamp)
                rows[key][index] = row

    results, max_error = [], 0.0
    for key, i in sorted(expected.items(), key=lambda item: item[1]):
        sample, old = current[key], prior[key]
        indices = list(sample.common_valid_frame_indices)
        if (sorted(rows[key]) != list(sample.input_frame_indices)
                or old["common_frame_indices"] != indices
                or len(set(indices)) != len(indices)):
            raise ValueError("H9 frame identity/support mismatch")
        if ([sample.features[name] for name in H9_FEATURE_NAMES] != saved["matrix"][i]
                or saved["class_order"][saved["labels"][i]] != sample.label):
            raise ValueError("saved H9 aggregate/label mismatch")
        values, used, failures = [], [], Counter()
        for index in indices:
            value, reasons, error = frame_earz(rows[key][index])
            if error is not None:
                max_error = max(max_error, error)
            if value is None:
                failures.update(reasons)
            else:
                values.append(value)
                used.append(index)
        reasons = list(sample.eligibility_reasons)
        if not values:
            reasons.append("no_valid_earz_frames")
        if used != indices:
            reasons.append("earz_support_differs_from_h9")
        median = statistics.median(values) if values else None
        if median is not None and not math.isfinite(median):
            median = None
            reasons.append("earz_median_nonfinite")
        results.append(dict(subject=key[0], recording_id=key[1], segment_id=key[2],
                            h9_common_support_count=len(indices), earz_valid_count=len(used),
                            earz_median=median, valid=not reasons, failure_reasons=reasons,
                            frame_failure_counts=dict(failures),
                            h9_common_frame_indices=indices, earz_valid_frame_indices=used))
    if before != [digest(path) for path in inputs]:
        raise ValueError("input changed during validation")
    return dict(experiment_id=EXPERIMENT_ID, segment_count=len(results),
                valid_segment_count=sum(row["valid"] for row in results),
                h9_common_support_count=sum(row["h9_common_support_count"] for row in results),
                earz_valid_count=sum(row["earz_valid_count"] for row in results),
                max_abs_stored_vs_xyz_formula_error=max_error,
                identity_and_saved_h9_aggregates_match=True,
                support_verification="source SHA-256 + exact CSV row indices + unique timestamps",
                inputs=[dict(name=path.name, sha256=sha) for path, sha in zip(inputs, before)],
                segments=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-csv", nargs="+", required=True)
    parser.add_argument("--h9-samples", required=True)
    parser.add_argument("--support-json", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = adapt(args.probe_csv, args.h9_samples, args.support_json)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "results.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    fields = ("subject", "recording_id", "segment_id", "h9_common_support_count",
              "earz_valid_count", "earz_median", "valid", "failure_reasons")
    with (args.output_dir / "segments.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["segments"])
    print(json.dumps({k: v for k, v in report.items() if k not in ("segments", "inputs")}))
    return 0 if report["segment_count"] == report["valid_segment_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
