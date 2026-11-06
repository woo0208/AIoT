"""Synthetic structure tests only: no participant data, models or hardware."""

import csv
import json
from pathlib import Path
import statistics
import tempfile
import unittest

import earz_adapter as adapter
from f1_sample_aggregator import H9_FEATURE_NAMES
from h6_offline import load_labeled_probe_h_samples
from posture_geometry import Point, Point3D, compute_candidate_geometry
from posture_geometry_probe import exploratory_csv_row


def frame(index=1, *, ear_z=0.9, scale=1.0):
    xyz = dict(left_shoulder=(-0.2, 0.0, 1.0), right_shoulder=(0.2, 0.0, 1.0),
               left_ear=(-0.1, -0.2, ear_z), right_ear=(0.1, -0.2, ear_z))
    result = compute_candidate_geometry(
        {name: Point(100 + 100*x, 100 + 100*y, z*scale) for name, (x, y, z) in xyz.items()},
        points_3d={name: Point3D(x*scale, y*scale, z*scale) for name, (x, y, z) in xyz.items()},
    )
    row = exploratory_csv_row(result, pose_detected=True, device_timestamp_ms=index*33.0,
                              timestamp_utc=f"synthetic-{index}", label="upright",
                              subject="synthetic-subject", recording_id="synthetic-recording",
                              segment_id=1)
    row.update({name: 0.1 for name in H9_FEATURE_NAMES})
    return {name: "" if value is None else str(value) for name, value in row.items()}


def fixture(root):
    rows = [frame(i, ear_z=0.8 + i/1000) for i in range(1, 33)]
    rows[0]["label"] = "PREP"
    rows[1][H9_FEATURE_NAMES[-1]] = ""  # EARZ exists but is outside H9 support.
    path = root / "saved.csv"
    write_csv(path, rows)
    sample, = load_labeled_probe_h_samples([path])
    saved = dict(feature_order=list(H9_FEATURE_NAMES),
                 sample_keys=[list(sample.sample_key)], subjects=[sample.subject],
                 matrix=[list(sample.ordered_values("H9"))], labels=[0], class_order=["upright"])
    support = dict(preservation=dict(sha256_before={path.name: adapter.digest(path)}),
                   segments=[dict(subject=sample.subject, recording_id=sample.sample_key[1],
                                 segment_id=sample.sample_key[2],
                                 common_frame_indices=list(sample.common_valid_frame_indices))])
    h9, prior = root / "samples.json", root / "support.json"
    h9.write_text(json.dumps(saved), encoding="utf-8")
    prior.write_text(json.dumps(support), encoding="utf-8")
    return rows, path, h9, prior


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class EarzTests(unittest.TestCase):
    def test_existing_function_formula_sign_and_units(self):
        for ear_z in (0.9, 1.0, 1.1):
            for scale in (1.0, 3.0):
                value, reasons, error = adapter.frame_earz(frame(ear_z=ear_z, scale=scale))
                self.assertEqual(reasons, ())
                self.assertAlmostEqual(value, (1.0-ear_z)/0.4)
                self.assertAlmostEqual(error, 0.0)

    def test_missing_nonfinite_width_and_flags(self):
        changes = [(adapter.EARZ_FEATURE, v) for v in ("", "nan", "inf")]
        changes += [("shoulder_width_3d_m", v) for v in ("0", "-1", "1e-7", "nan", "inf")]
        for name in adapter.POINTS:
            changes += [(f"{name}_3d_{axis}_m", v) for axis in "xyz" for v in ("", "nan", "inf")]
            changes += [(f"{name}_depth_valid", "False"), (f"{name}_landmark_valid", "False")]
        for name, value in changes:
            with self.subTest(field=name, value=value):
                row = frame()
                row[name] = value
                actual, reasons, _ = adapter.frame_earz(row)
                self.assertIsNone(actual)
                self.assertTrue(reasons)

    def test_formula_mismatch_is_missing_and_float32_roundoff_retains_saved_value(self):
        row = frame()
        row[adapter.EARZ_FEATURE] = "-0.25"
        self.assertIsNone(adapter.frame_earz(row)[0])
        row = frame()
        row["left_ear_3d_z_m"] = str(0.9 + 2e-8)
        self.assertEqual(adapter.frame_earz(row)[0], float(row[adapter.EARZ_FEATURE]))
        row["shoulder_width_3d_m"] = "0.5"
        self.assertIsNone(adapter.frame_earz(row)[0])

    def test_exact_support_and_median_without_imputation(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, path, h9, prior = fixture(Path(tmp))
            report = adapter.adapt([path], h9, prior)
            segment, = report["segments"]
            self.assertTrue(segment["valid"])
            self.assertEqual(segment["h9_common_frame_indices"], list(range(3, 33)))
            self.assertEqual(segment["earz_valid_frame_indices"], list(range(3, 33)))
            self.assertEqual(segment["earz_median"], statistics.median(
                float(row[adapter.EARZ_FEATURE]) for row in rows[2:]))
            rows[2][adapter.EARZ_FEATURE] = ""
            write_csv(path, rows)
            data = adapter.read_json(prior)
            data["preservation"]["sha256_before"][path.name] = adapter.digest(path)
            prior.write_text(json.dumps(data), encoding="utf-8")
            segment, = adapter.adapt([path], h9, prior)["segments"]
            self.assertFalse(segment["valid"])
            self.assertEqual(segment["earz_valid_count"], 29)
            self.assertIn("earz_support_differs_from_h9", segment["failure_reasons"])
            self.assertEqual(segment["earz_median"], statistics.median(
                float(row[adapter.EARZ_FEATURE]) for row in rows[3:]))

    def test_equal_count_different_frame_identities_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, path, h9, prior = fixture(Path(tmp))
            data = adapter.read_json(prior)
            data["segments"][0]["common_frame_indices"][0] = 2
            prior.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frame identity/support mismatch"):
                adapter.adapt([path], h9, prior)

    def test_reordered_source_with_same_counts_and_medians_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, path, h9, prior = fixture(Path(tmp))
            rows[3], rows[4] = rows[4], rows[3]
            write_csv(path, rows)
            with self.assertRaisesRegex(ValueError, "source hash"):
                adapter.adapt([path], h9, prior)

    def test_duplicate_and_mismatched_segment_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, path, h9, prior = fixture(Path(tmp))
            data = adapter.read_json(prior)
            data["segments"].append(dict(data["segments"][0]))
            prior.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                adapter.adapt([path], h9, prior)
            data["segments"] = data["segments"][:1]
            data["segments"][0]["segment_id"] = "different"
            prior.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identities mismatch"):
                adapter.adapt([path], h9, prior)


if __name__ == "__main__":
    unittest.main()
