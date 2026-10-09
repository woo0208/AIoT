import math
import types
import unittest

import numpy as np

import posture_geometry as geometry


def neutral_points(scale=1.0, nose_depth=0.70):
    center_x = 100.0 * scale
    return {
        "nose": geometry.Point(center_x, 40.0 * scale, nose_depth),
        "left_ear": geometry.Point(120.0 * scale, 50.0 * scale, 0.70),
        "right_ear": geometry.Point(80.0 * scale, 50.0 * scale, 0.70),
        "left_shoulder": geometry.Point(140.0 * scale, 100.0 * scale, 0.80),
        "right_shoulder": geometry.Point(60.0 * scale, 100.0 * scale, 0.80),
        "left_hip": geometry.Point(130.0 * scale, 160.0 * scale, 0.80),
        "right_hip": geometry.Point(70.0 * scale, 160.0 * scale, 0.80),
    }


def metric_body_points(shoulder_z=.80, hip_z=.80):
    return {
        "left_shoulder": geometry.Point3D(.20, -.30, shoulder_z),
        "right_shoulder": geometry.Point3D(-.20, -.30, shoulder_z),
        "left_hip": geometry.Point3D(.15, .30, hip_z),
        "right_hip": geometry.Point3D(-.15, .30, hip_z),
    }


class CandidateGeometryTests(unittest.TestCase):
    def test_neutral_geometry_and_explicit_proxies(self):
        result = geometry.compute_candidate_geometry(neutral_points(), focal_length_px=800.0)
        self.assertAlmostEqual(result.features["head_lateral_tilt_deg"], 0.0)
        self.assertAlmostEqual(result.features["shoulder_tilt_deg"], 0.0)
        self.assertAlmostEqual(result.features["nose_to_shoulder_mid_dx_shoulder_width"], 0.0)
        self.assertAlmostEqual(result.features["nose_to_shoulder_mid_dy_shoulder_width"], -0.75)
        self.assertEqual(result.proxies["exploratory_upper_chest_proxy"], geometry.Point(100, 100, .8))
        self.assertEqual(result.proxies["exploratory_neck_proxy"], geometry.Point(100, 75, .75))

    def test_forward_displacement_is_positive_toward_camera(self):
        result = geometry.compute_candidate_geometry(neutral_points(nose_depth=.68), focal_length_px=800.0)
        self.assertAlmostEqual(result.features["nose_forward_from_torso_m"], .12)
        self.assertAlmostEqual(result.features["shoulder_width_metric_proxy_m"], .08)
        self.assertAlmostEqual(result.features["nose_forward_normalized_by_shoulder_width"], 1.5)

    def test_upright_torso_geometry_and_true_shoulder_width(self):
        result = geometry.compute_candidate_geometry(
            neutral_points(), points_3d=metric_body_points()
        )
        self.assertEqual(
            result.proxies_3d["shoulder_midpoint_3d"],
            geometry.Point3D(0.0, -.30, .80),
        )
        self.assertEqual(
            result.proxies_3d["hip_midpoint_3d"],
            geometry.Point3D(0.0, .30, .80),
        )
        self.assertAlmostEqual(result.features["shoulder_width_3d_m"], .40)
        self.assertAlmostEqual(result.features["sagittal_torso_lean_deg"], 0.0)
        self.assertAlmostEqual(
            result.features["nose_forward_normalized_by_shoulder_width_3d"],
            .25,
        )

    def test_forward_and_reverse_torso_lean_have_opposite_signs(self):
        forward = geometry.compute_candidate_geometry(
            neutral_points(), points_3d=metric_body_points(shoulder_z=.65, hip_z=.80)
        )
        reverse = geometry.compute_candidate_geometry(
            neutral_points(), points_3d=metric_body_points(shoulder_z=.95, hip_z=.80)
        )
        self.assertGreater(forward.features["sagittal_torso_lean_deg"], 0)
        self.assertLess(reverse.features["sagittal_torso_lean_deg"], 0)
        self.assertAlmostEqual(
            forward.features["sagittal_torso_lean_deg"],
            -reverse.features["sagittal_torso_lean_deg"],
        )

    def test_missing_hip_or_missing_metric_hip_makes_torso_geometry_unavailable(self):
        points = neutral_points()
        points["left_hip"] = None
        metric = metric_body_points()
        metric["left_hip"] = None
        result = geometry.compute_candidate_geometry(points, points_3d=metric)
        self.assertIsNone(result.proxies["hip_midpoint"])
        self.assertIsNone(result.proxies_3d["hip_midpoint_3d"])
        self.assertIsNone(result.features["sagittal_torso_lean_deg"])
        self.assertAlmostEqual(result.features["shoulder_width_3d_m"], .40)

    def test_invalid_hip_depth_does_not_create_metric_torso_geometry(self):
        points = neutral_points()
        points["left_hip"] = geometry.Point(130, 160, None)
        metric = metric_body_points()
        metric["left_hip"] = None
        result = geometry.compute_candidate_geometry(points, points_3d=metric)
        self.assertIsNone(result.proxies["hip_midpoint"].depth_m)
        self.assertIsNone(result.proxies_3d["hip_midpoint_3d"])
        self.assertIsNone(result.features["sagittal_torso_lean_deg"])

    def test_degenerate_metric_body_geometry_is_unavailable(self):
        metric = metric_body_points()
        same = geometry.Point3D(0.0, 0.0, .80)
        for name in metric:
            metric[name] = same
        result = geometry.compute_candidate_geometry(neutral_points(), points_3d=metric)
        self.assertIsNone(result.features["shoulder_width_3d_m"])
        self.assertIsNone(result.features["sagittal_torso_lean_deg"])
        self.assertIsNone(
            result.features["nose_forward_normalized_by_shoulder_width_3d"]
        )

    def test_left_and_right_head_tilt_have_opposite_signs(self):
        left = neutral_points()
        left["left_ear"] = geometry.Point(120, 40, .7)
        left["right_ear"] = geometry.Point(80, 60, .7)
        right = neutral_points()
        right["left_ear"] = geometry.Point(120, 60, .7)
        right["right_ear"] = geometry.Point(80, 40, .7)
        left_angle = geometry.compute_candidate_geometry(left).features["head_lateral_tilt_deg"]
        right_angle = geometry.compute_candidate_geometry(right).features["head_lateral_tilt_deg"]
        self.assertLess(left_angle, 0)
        self.assertGreater(right_angle, 0)
        self.assertAlmostEqual(abs(left_angle), abs(right_angle))

    def test_relative_head_tilt_subtracts_shoulder_tilt(self):
        points = neutral_points()
        points["left_ear"] = geometry.Point(120, 40, .7)
        points["right_ear"] = geometry.Point(80, 60, .7)
        points["left_shoulder"] = geometry.Point(140, 90, .8)
        points["right_shoulder"] = geometry.Point(60, 110, .8)
        result = geometry.compute_candidate_geometry(points)
        self.assertAlmostEqual(
            result.features["relative_head_tilt_deg"],
            result.features["head_lateral_tilt_deg"]
            - result.features["shoulder_tilt_deg"],
        )

    def test_image_scale_normalization(self):
        base = geometry.compute_candidate_geometry(neutral_points(1.0))
        doubled = geometry.compute_candidate_geometry(neutral_points(2.0))
        for feature in (
            "nose_to_shoulder_mid_dx_shoulder_width",
            "nose_to_shoulder_mid_dy_shoulder_width",
            "left_ear_to_left_shoulder_dx_shoulder_width",
            "left_ear_to_left_shoulder_dy_shoulder_width",
            "head_to_torso_lateral_angle_deg",
        ):
            self.assertAlmostEqual(base.features[feature], doubled.features[feature])

    def test_missing_landmarks_do_not_create_measurements(self):
        points = neutral_points()
        points["nose"] = None
        points["right_ear"] = None
        result = geometry.compute_candidate_geometry(points, focal_length_px=800)
        self.assertIsNone(result.features["head_lateral_tilt_deg"])
        self.assertIsNone(result.features["nose_to_shoulder_mid_dx_shoulder_width"])
        self.assertIsNone(result.features["nose_forward_from_torso_m"])
        self.assertIsNone(result.proxies["ear_midpoint"])
        self.assertIsNone(result.proxies["exploratory_neck_proxy"])

    def test_invalid_nonfinite_depth_fails_only_depth_features(self):
        points = neutral_points()
        points["nose"] = geometry.Point(100, 40, math.nan)
        points["left_shoulder"] = geometry.Point(140, 100, math.inf)
        result = geometry.compute_candidate_geometry(points, focal_length_px=800)
        self.assertAlmostEqual(result.features["shoulder_width_px"], 80)
        self.assertIsNone(result.features["torso_depth_proxy_m"])
        self.assertIsNone(result.features["nose_forward_from_torso_m"])
        self.assertIsNone(result.features["nose_forward_normalized_by_shoulder_width"])

    def test_zero_or_near_zero_body_scale_fails_normalized_features(self):
        for delta in (0.0, 1e-8):
            points = neutral_points()
            points["left_shoulder"] = geometry.Point(100 + delta, 100, .8)
            points["right_shoulder"] = geometry.Point(100, 100, .8)
            result = geometry.compute_candidate_geometry(points, focal_length_px=800)
            self.assertIsNone(result.features["nose_to_shoulder_mid_dx_shoulder_width"])
            self.assertIsNone(result.features["shoulder_width_metric_proxy_m"])
            self.assertIsNone(result.features["nose_forward_normalized_by_shoulder_width"])

    def test_pose_adapter_uses_named_indices_and_aligned_depth(self):
        landmarks = [types.SimpleNamespace(x=.5, y=.5) for _ in range(33)]
        landmarks[0] = types.SimpleNamespace(x=.5, y=.25)
        landmarks[7] = types.SimpleNamespace(x=.6, y=.3)
        landmarks[8] = types.SimpleNamespace(x=.4, y=.3)
        landmarks[11] = types.SimpleNamespace(x=.7, y=.6)
        landmarks[12] = types.SimpleNamespace(x=.3, y=.6)
        landmarks[13] = types.SimpleNamespace(x=.8, y=.7)
        landmarks[14] = types.SimpleNamespace(x=.2, y=.7)
        landmarks[15] = types.SimpleNamespace(x=.9, y=.8)
        landmarks[16] = types.SimpleNamespace(x=.1, y=.8)
        landmarks[23] = types.SimpleNamespace(x=.65, y=.9)
        landmarks[24] = types.SimpleNamespace(x=.35, y=.9)
        depth = np.full((100, 200), 750, dtype=np.uint16)
        points = geometry.points_from_pose_landmarks(
            landmarks, 200, 100, aligned_depth=depth, depth_scale_m=.001
        )
        self.assertEqual(points["nose"], geometry.Point(100, 25, .75))
        self.assertEqual(points["left_ear"], geometry.Point(120, 30, .75))
        self.assertEqual(points["right_shoulder"], geometry.Point(60, 60, .75))
        self.assertEqual(points["left_elbow"], geometry.Point(160, 70, .75))
        self.assertEqual(points["right_elbow"], geometry.Point(40, 70, .75))
        self.assertEqual(points["left_wrist"], geometry.Point(180, 80, .75))
        self.assertEqual(points["right_wrist"], geometry.Point(20, 80, .75))
        self.assertEqual(points["left_hip"], geometry.Point(130, 90, .75))
        self.assertEqual(points["right_hip"], geometry.Point(70, 90, .75))

    def test_missing_arm_landmarks_do_not_invalidate_head_or_torso_geometry(self):
        points = neutral_points()
        baseline = geometry.compute_candidate_geometry(points, points_3d=metric_body_points())
        result = geometry.compute_candidate_geometry(points, points_3d=metric_body_points())
        for name in ("left_elbow", "right_elbow", "left_wrist", "right_wrist"):
            self.assertIsNone(result.points[name])
            self.assertIsNone(result.points_3d[name])
        self.assertEqual(result.features, baseline.features)
        self.assertEqual(result.proxies["ear_midpoint"], baseline.proxies["ear_midpoint"])
        self.assertEqual(
            result.proxies_3d["shoulder_midpoint_3d"],
            baseline.proxies_3d["shoulder_midpoint_3d"],
        )

    def test_pose_adapter_rejects_missing_out_of_frame_and_invalid_depth(self):
        landmarks = [types.SimpleNamespace(x=.5, y=.5) for _ in range(12)]
        landmarks[7] = types.SimpleNamespace(x=1.1, y=.5)
        depth = np.zeros((20, 20), dtype=np.uint16)
        points = geometry.points_from_pose_landmarks(
            landmarks, 20, 20, aligned_depth=depth, depth_scale_m=.001
        )
        self.assertIsNone(points["left_ear"])
        self.assertIsNone(points["right_shoulder"])
        self.assertEqual(points["nose"], geometry.Point(10, 10, None))

    def test_overlay_draws_without_mutating_input(self):
        image = np.zeros((180, 220, 3), dtype=np.uint8)
        result = geometry.compute_candidate_geometry(neutral_points(), focal_length_px=800)
        overlay = geometry.draw_geometry_overlay(image, result)
        self.assertEqual(overlay.shape, image.shape)
        self.assertFalse(np.array_equal(overlay, image))
        self.assertFalse(image.any())

    def test_drop_in_pose_frame_overlay_keeps_output_exploratory(self):
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        landmarks = [types.SimpleNamespace(x=.5, y=.5) for _ in range(33)]
        overlay, result = geometry.overlay_pose_frame(image, landmarks, focal_length_px=800)
        self.assertEqual(overlay.shape, image.shape)
        self.assertEqual(result.as_debug_dict()["kind"], "exploratory-posture-geometry")
        self.assertNotIn("frame_schema_version", result.as_debug_dict())


if __name__ == "__main__":
    unittest.main()
