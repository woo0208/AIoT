"""Synthetic calculation/aggregation tests only; no capture, fitting or accuracy."""

from dataclasses import replace
import math
import unittest

import f1_sample_aggregator as legacy
import h9_v2 as v2
import posture_geometry as geometry


def values(index=1, *, angle=10.0, c3=20.0):
    result = {name: float(index) for name in v2.H9_V2_FEATURE_NAMES}
    result[legacy.H_FACE_AXIS_FEATURE] = angle
    result[v2.H9_V2_C3_FEATURE] = c3
    return result


def record(index, features=None):
    return v2.H9V2FrameRecord(
        analysis_run_id="synthetic-run", recording_id="synthetic-recording",
        frame_index=index, subject="synthetic-subject", round=None,
        step="1", label="upright", features=values(index) if features is None else features,
    )


def geometry_result(*, hips=True):
    points = {
        "left_eye": geometry.Point(40.0, 20.0),
        "right_eye": geometry.Point(60.0, 20.0),
        "left_ear": geometry.Point(35.0, 30.0),
        "right_ear": geometry.Point(65.0, 30.0),
        "nose": geometry.Point(50.0, 35.0, 0.7),
        "chin": geometry.Point(50.0, 50.0),
        "left_shoulder": geometry.Point(80.0, 100.0, 0.9),
        "right_shoulder": geometry.Point(20.0, 100.0, 0.9),
    }
    xyz = {
        "left_shoulder": geometry.Point3D(-0.3, 0.0, 0.9),
        "right_shoulder": geometry.Point3D(0.3, 0.0, 0.9),
        "nose": geometry.Point3D(0.0, -0.2, 0.7),
    }
    if hips:
        xyz.update(left_hip=geometry.Point3D(-0.2, 0.5, 1.1),
                   right_hip=geometry.Point3D(0.2, 0.5, 1.1))
    return geometry.compute_candidate_geometry(
        points, points_3d=xyz, chest_roi_point=geometry.Point(50.0, 121.0, 0.8),
        chest_roi_point_3d=geometry.Point3D(0.0, 0.2, 0.8),
    )


def from_geometry(result, index=1):
    identity = record(index)
    return v2.h9_v2_frame_from_geometry(
        result, analysis_run_id=identity.analysis_run_id, recording_id=identity.recording_id,
        frame_index=index, subject=identity.subject, round=identity.round,
        step=identity.step, label=identity.label,
    )


class H9V2Tests(unittest.TestCase):
    def test_existing_geometry_values_reused_in_exact_order(self):
        result = geometry_result()
        frame = from_geometry(result)
        self.assertAlmostEqual(result.features[v2.H9_V2_C3_FEATURE],
                               math.degrees(math.atan2(0.2, 0.5)))
        self.assertEqual(v2.H9_V2_FEATURE_NAMES, (
            "hipless_f1_candidate_head_center_dx_sw",
            "hipless_f1_candidate_head_center_dy_sw",
            "hipless_f1_candidate_face_axis_tilt_deg",
            "hipless_f1_candidate_ear_eye_dy_sw",
            "hipless_f1_candidate_nose_chin_distance_sw",
            "hipless_f2_candidate_chest_depth_m",
            "hipless_f2_candidate_chest_forward_from_shoulders_m",
            "hipless_f2_candidate_nose_forward_from_chest_m",
            "sagittal_torso_lean_deg",
        ))
        self.assertEqual(tuple(frame.features), v2.H9_V2_FEATURE_NAMES)
        self.assertEqual(dict(frame.features),
                         {name: result.features[name] for name in v2.H9_V2_FEATURE_NAMES})
        # An already-computed value is authoritative, even if XYZ would differ.
        stored = replace(result, features=dict(result.features, sagittal_torso_lean_deg=-7.25))
        self.assertEqual(from_geometry(stored).features[v2.H9_V2_C3_FEATURE], -7.25)
        sample = v2.aggregate_h9_v2_sample(from_geometry(result, i) for i in range(1, 31))
        self.assertTrue(sample.eligible)
        self.assertEqual(sample.ordered_values(), tuple(frame.features.values()))

    def test_missing_hip_geometry_keeps_c3_missing_without_reducing_legacy_h9(self):
        result = geometry_result(hips=False)
        frame = from_geometry(result)
        self.assertIsNone(frame.features[v2.H9_V2_C3_FEATURE])
        self.assertTrue(all(result.features[name] is not None for name in legacy.H9_FEATURE_NAMES))
        sample = v2.aggregate_h9_v2_sample(replace(frame, frame_index=i) for i in range(1, 31))
        self.assertFalse(sample.eligible)
        self.assertEqual(sample.common_valid_count, 0)
        self.assertTrue(all(value is None for value in sample.features.values()))
        self.assertEqual(sample.missing_counts[v2.H9_V2_C3_FEATURE], 30)
        with self.assertRaisesRegex(ValueError, "ineligible H9-v2"):
            sample.ordered_values()

    def test_exact_threshold_common_support_and_c3_scalar_median(self):
        frames = []
        for i in range(1, 61):
            frame_values = values(i, angle=170.0 if i <= 10 else -170.0,
                                  c3=170.0 if i <= 10 else -170.0)
            if i > 30:
                frame_values[v2.H9_V2_C3_FEATURE] = None
                frame_values[legacy.H5_FEATURE_NAMES[0]] = 10000.0
            frames.append(record(i, frame_values))
        sample = v2.aggregate_h9_v2_sample(reversed(frames))
        self.assertTrue(sample.eligible)
        self.assertEqual(sample.common_valid_count, 30)
        self.assertEqual(sample.common_coverage, 0.5)
        self.assertEqual(sample.common_valid_frame_indices, tuple(range(1, 31)))
        self.assertEqual(sample.features[legacy.H5_FEATURE_NAMES[0]], 15.5)
        self.assertEqual(sample.features[v2.H9_V2_C3_FEATURE], -170.0)
        self.assertGreater(abs(sample.features[legacy.H_FACE_AXIS_FEATURE]), 170.0)
        self.assertEqual(sample.ordered_values("H9-v2")[-1], -170.0)

    def test_thresholds_and_circular_cancellation_fail_closed(self):
        cases = (
            ([record(i) for i in range(1, 30)], "common_valid_frames<30"),
            ([record(i, values(i, c3=20.0 if i <= 30 else None)) for i in range(1, 62)],
             "common_coverage<0.5"),
            ([record(i, values(i, angle=0.0 if i <= 15 else 180.0)) for i in range(1, 31)],
             "face_axis_circular_mean_undefined"),
        )
        for frames, reason in cases:
            with self.subTest(reason=reason):
                sample = v2.aggregate_h9_v2_sample(frames)
                self.assertFalse(sample.eligible)
                self.assertIn(reason, sample.eligibility_reasons)
                with self.assertRaises(ValueError):
                    sample.ordered_values()

    def test_legacy_and_v2_support_results_and_types_remain_distinct(self):
        frames, old_frames = [], []
        for i in range(1, 33):
            frame = record(i, values(-1000 if i == 32 else i, c3=None if i == 31 else 20.0))
            frames.append(frame)
            old_values = {name: frame.features[name] for name in legacy.H9_FEATURE_NAMES[:8]}
            old_values[legacy.H9_FEATURE_NAMES[-1]] = None if i == 32 else 9.0
            old_frames.append(legacy.HFrameRecord(
                analysis_run_id=frame.analysis_run_id, recording_id=frame.recording_id,
                frame_index=i, subject=frame.subject, round=frame.round,
                step=frame.step, label=frame.label, features=old_values,
            ))
        old = legacy.aggregate_h5_h9_sample(old_frames)
        new = v2.aggregate_h9_v2_sample(frames)
        self.assertEqual(old.common_valid_frame_indices, tuple(range(1, 32)))
        self.assertEqual(new.common_valid_frame_indices, (*range(1, 31), 32))
        self.assertEqual(old.ordered_values("H9")[0], 16.0)
        self.assertEqual(old.ordered_values("H5"), old.ordered_values("H9")[:5])
        self.assertEqual(new.ordered_values()[0], 15.0)
        self.assertNotEqual(old.aggregation_spec, new.aggregation_spec)
        self.assertEqual(new.feature_set, "H9-v2")
        self.assertEqual(new.feature_names, v2.H9_V2_FEATURE_NAMES)
        self.assertNotIsInstance(new, legacy.HSampleResult)
        self.assertNotIsInstance(frames[0], legacy.HFrameRecord)
        for feature_set in ("H5", "H9"):
            with self.assertRaises(ValueError):
                new.ordered_values(feature_set)
        with self.assertRaises(ValueError):
            old.ordered_values("H9-v2")
        with self.assertRaises(ValueError):
            legacy.aggregate_h5_h9_sample(frames)
        with self.assertRaises(ValueError):
            v2.aggregate_h9_v2_sample(old_frames)

    def test_any_missing_input_excludes_whole_frame_and_is_counted(self):
        for name in v2.H9_V2_FEATURE_NAMES:
            with self.subTest(name=name):
                missing = values(10000)
                missing[name] = None
                sample = v2.aggregate_h9_v2_sample(
                    [record(i) for i in range(1, 31)] + [record(31, missing)])
                self.assertTrue(sample.eligible)
                self.assertEqual(sample.common_valid_frame_indices, tuple(range(1, 31)))
                self.assertEqual(sample.missing_counts[name], 1)
                self.assertEqual(sample.features[v2.H9_V2_C3_FEATURE], 20.0)

    def test_malformed_values_and_feature_keys_rejected(self):
        for bad in (True, "", "1.0", float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                record(1, values(c3=bad))
        wrong = values()
        wrong[legacy.H9_FEATURE_NAMES[-1]] = wrong.pop(v2.H9_V2_C3_FEATURE)
        with self.assertRaisesRegex(ValueError, "exact H9-v2 feature set"):
            record(1, wrong)

    def test_empty_duplicate_and_mixed_identity_rejected(self):
        frame = record(1)
        for frames in ([], [frame, frame], [frame, object()]):
            with self.assertRaises(ValueError):
                v2.aggregate_h9_v2_sample(frames)
        for field, value in (("analysis_run_id", "other-run"), ("recording_id", "other-rec"),
                             ("step", "2"), ("subject", "other-subject"),
                             ("round", "2"), ("label", "head_forward")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                v2.aggregate_h9_v2_sample([frame, replace(record(2), **{field: value})])


if __name__ == "__main__":
    unittest.main()
