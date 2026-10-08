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
        depth = np.full((100, 200), 750, dtype=np.uint16)
        points = geometry.points_from_pose_landmarks(
            landmarks, 200, 100, aligned_depth=depth, depth_scale_m=.001
        )
        self.assertEqual(points["nose"], geometry.Point(100, 25, .75))
        self.assertEqual(points["left_ear"], geometry.Point(120, 30, .75))
        self.assertEqual(points["right_shoulder"], geometry.Point(60, 60, .75))

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
