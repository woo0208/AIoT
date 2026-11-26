"""Core structural tests for unapproved hip-independent F1/F2 candidates.

Synthetic pixels/depth only: these tests are not D455 measurement evidence and
do not validate posture classification or resolve OPEN-002/OPEN-003.
"""

import unittest

import numpy as np

import f1_features
import posture_geometry as geometry
import posture_geometry_probe as probe
from test_f1_features import frame_row


def hipless_points():
    return {
        "left_eye": geometry.Point(40.0, 20.0),
        "right_eye": geometry.Point(60.0, 20.0),
        "left_ear": geometry.Point(35.0, 30.0),
        "right_ear": geometry.Point(65.0, 30.0),
        "nose": geometry.Point(50.0, 35.0, 0.70),
        "chin": geometry.Point(50.0, 50.0),
        "left_shoulder": geometry.Point(80.0, 100.0, 0.90),
        "right_shoulder": geometry.Point(20.0, 100.0, 0.90),
        "left_hip": None,
        "right_hip": None,
    }


class HiplessCandidateTests(unittest.TestCase):
    def test_f1_5_contract_output_is_unchanged(self):
        result = f1_features.compute_f1_5_frame(frame_row())
        self.assertEqual(f1_features.F1_5_FEATURE_NAMES,
                         ("fs_x", "fs_y", "sh_x", "sh_y", "so_beta"))
        self.assertEqual(result.ordered_values(), (0.0, -1.0, 0.0, -1.5, 0.0))

    def test_f1_extension_uses_face_and_shoulders_without_hips(self):
        result = geometry.compute_candidate_geometry(hipless_points())
        values = result.features
        self.assertAlmostEqual(values["hipless_f1_candidate_head_center_dx_sw"], 0.0)
        self.assertAlmostEqual(
            values["hipless_f1_candidate_head_center_dy_sw"],
            ((20 + 20 + 30 + 30 + 35 + 50) / 6 - 100) / 60,
        )
        self.assertAlmostEqual(values["hipless_f1_candidate_face_axis_tilt_deg"], 0.0)
        self.assertAlmostEqual(values["hipless_f1_candidate_ear_eye_dy_sw"], 10 / 60)
        self.assertAlmostEqual(values["hipless_f1_candidate_nose_chin_distance_sw"], 15 / 60)
        self.assertIsNone(values["sagittal_torso_lean_deg"])

    def test_shoulder_defined_chest_roi_samples_actual_depth_without_hips(self):
        depth = np.zeros((140, 120), dtype=np.uint16)
        # Horizontal 60 px shoulders at y=40 define centre (50, 61), with the
        # oriented ROI spanning x=35..65 and y=52..70 for this synthetic case.
        depth[52:71, 35:66] = 800
        left = geometry.Point(80.0, 40.0, 0.90)
        right = geometry.Point(20.0, 40.0, 0.90)
        chest = geometry.sample_hipless_chest_roi(left, right, depth, 0.001)
        self.assertIsNotNone(chest)
        self.assertAlmostEqual(chest.x_px, 50.0)
        self.assertAlmostEqual(chest.y_px, 61.0)
        self.assertAlmostEqual(chest.depth_m, 0.8)

        points = dict(hipless_points(), left_shoulder=left, right_shoulder=right)
        points_3d = {
            "left_shoulder": geometry.Point3D(-0.3, 0.0, 0.9),
            "right_shoulder": geometry.Point3D(0.3, 0.0, 0.9),
            "nose": geometry.Point3D(0.0, -0.2, 0.7),
        }
        result = geometry.compute_candidate_geometry(
            points,
            points_3d=points_3d,
            chest_roi_point=chest,
            chest_roi_point_3d=geometry.Point3D(0.0, 0.2, 0.8),
        )
        values = result.features
        self.assertAlmostEqual(values["hipless_f2_candidate_chest_depth_m"], 0.8)
        self.assertAlmostEqual(values["hipless_f2_candidate_chest_forward_from_shoulders_m"], 0.1)
        self.assertAlmostEqual(values["hipless_f2_candidate_nose_forward_from_chest_m"], 0.1)
        self.assertAlmostEqual(values["hipless_f2_candidate_nose_forward_from_chest_sw3d"], 1 / 6)

        with_hips = dict(
            points,
            left_hip=geometry.Point(70.0, 125.0, 1.1),
            right_hip=geometry.Point(30.0, 125.0, 1.1),
        )
        comparison = geometry.compute_candidate_geometry(
            with_hips,
            points_3d=dict(
                points_3d,
                left_hip=geometry.Point3D(-0.2, 0.5, 1.1),
                right_hip=geometry.Point3D(0.2, 0.5, 1.1),
            ),
            chest_roi_point=chest,
            chest_roi_point_3d=geometry.Point3D(0.0, 0.2, 0.8),
        )
        for name in geometry.HIPLESS_F2_CANDIDATE_FEATURE_NAMES:
            self.assertEqual(comparison.features[name], values[name])
        self.assertIsNotNone(comparison.features["sagittal_torso_lean_deg"])

    def test_missing_depth_stays_missing_while_2d_candidates_remain(self):
        points = hipless_points()
        chest = geometry.sample_hipless_chest_roi(
            points["left_shoulder"], points["right_shoulder"],
            np.zeros((140, 120), dtype=np.uint16), 0.001,
        )
        self.assertIsNotNone(chest)
        self.assertIsNone(chest.depth_m)
        result = geometry.compute_candidate_geometry(points, chest_roi_point=chest)
        self.assertIsNotNone(result.features["hipless_f1_candidate_head_center_dy_sw"])
        for name in geometry.HIPLESS_F2_CANDIDATE_FEATURE_NAMES:
            self.assertIsNone(result.features[name])

    def test_engineering_csv_and_live_debug_expose_separate_candidate_names(self):
        points = hipless_points()
        chest = geometry.Point(50.0, 121.0, 0.8)
        result = geometry.compute_candidate_geometry(
            points,
            points_3d={
                "left_shoulder": geometry.Point3D(-0.3, 0.0, 0.9),
                "right_shoulder": geometry.Point3D(0.3, 0.0, 0.9),
                "nose": geometry.Point3D(0.0, -0.2, 0.7),
            },
            chest_roi_point=chest,
            chest_roi_point_3d=geometry.Point3D(0.0, 0.2, 0.8),
        )
        row = probe.exploratory_csv_row(
            result,
            pose_detected=True,
            device_timestamp_ms=1.0,
            timestamp_utc="synthetic",
        )
        for name in (*geometry.HIPLESS_F1_CANDIDATE_FEATURE_NAMES,
                     *geometry.HIPLESS_F2_CANDIDATE_FEATURE_NAMES):
            self.assertIn(name, probe.CSV_FIELDS)
            self.assertEqual(row[name], result.features[name])
        self.assertTrue(row["hipless_chest_roi_defined"])
        self.assertTrue(row["hipless_chest_roi_depth_available"])
        values = probe.panel_measurement_values(
            result, face_detected=True, face_matrix=None
        )
        text = "\n".join(
            line for _, lines in probe.debug_panel_pages(result, True, values)
            for line in lines
        )
        for name in (*geometry.HIPLESS_F1_CANDIDATE_FEATURE_NAMES,
                     *geometry.HIPLESS_F2_CANDIDATE_FEATURE_NAMES):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
