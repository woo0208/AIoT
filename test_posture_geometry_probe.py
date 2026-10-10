import csv
import math
import os
import tempfile
import types
import unittest

import posture_geometry as geometry
import posture_geometry_probe as probe


def incomplete_result():
    return geometry.compute_candidate_geometry({
        "nose": geometry.Point(100, 40, None),
        "left_ear": None,
        "right_ear": geometry.Point(80, 50, .70),
        "left_shoulder": geometry.Point(140, 100, .80),
        "right_shoulder": geometry.Point(60, 100, None),
    }, focal_length_px=800)


class ProbeHelperTests(unittest.TestCase):
    def test_cli_default_has_no_output_path(self):
        args = probe.parse_args([])
        self.assertIsNone(args.csv)
        self.assertIsNone(args.views)

    def test_cli_defaults_bare_views_to_primary_side_avatar(self):
        self.assertEqual(probe.parse_args(["--views"]).views, "side")
        self.assertEqual(probe.parse_args(["--views", "side"]).views, "side")
        self.assertEqual(probe.parse_args(["--views", "debug"]).views, "debug")
        self.assertEqual(probe.parse_args(["--views", "skeleton"]).views, "skeleton")
        self.assertEqual(probe.parse_args(["--views", "avatar"]).views, "avatar")
        self.assertEqual(probe.parse_args(["--views", "all"]).views, "all")

    def test_feature_formatting_marks_missing_and_nonfinite_unavailable(self):
        self.assertEqual(probe.format_feature(None), "unavailable")
        self.assertEqual(probe.format_feature(math.nan), "unavailable")
        self.assertEqual(probe.format_feature(math.inf), "unavailable")
        self.assertEqual(probe.format_feature(.125, " m"), "+0.125 m")

    def test_missing_values_remain_blank_and_validity_is_explicit_in_csv(self):
        row = probe.exploratory_csv_row(
            incomplete_result(),
            pose_detected=True,
            device_timestamp_ms=123.5,
            timestamp_utc="2026-10-08T00:00:00.000+00:00",
        )
        self.assertEqual(row["artifact_kind"], probe.EXPLORATORY_ARTIFACT_KIND)
        self.assertTrue(row["nose_landmark_valid"])
        self.assertFalse(row["nose_depth_valid"])
        self.assertFalse(row["left_ear_landmark_valid"])
        self.assertFalse(row["right_shoulder_depth_valid"])
        self.assertIsNone(row["nose_forward_from_torso_m"])
        self.assertFalse(row["normalized_nose_available"])
        self.assertFalse(row["shoulder_width_3d_available"])
        self.assertFalse(row["sagittal_torso_lean_available"])
        self.assertIsNone(row["left_hip_3d_x_m"])
        self.assertFalse(row["chin_landmark_valid"])
        self.assertFalse(row["chin_depth_valid"])
        self.assertIsNone(row["chin_3d_x_m"])
        self.assertIsNone(row["exploratory_head_pitch_deg"])

    def test_realsense_deprojection_adapter_passes_metric_points_to_geometry(self):
        calls = []

        def deproject(intrinsics, pixel, depth):
            calls.append((intrinsics, pixel, depth))
            return [pixel[0] / 1000, pixel[1] / 1000, depth]

        points = {
            "left_shoulder": geometry.Point(140, 100, .80),
            "right_shoulder": geometry.Point(60, 100, .80),
            "left_elbow": geometry.Point(155, 125, .78),
            "right_elbow": geometry.Point(45, 125, None),
            "left_wrist": geometry.Point(165, 150, .76),
            "right_wrist": None,
            "left_hip": geometry.Point(130, 160, .85),
            "right_hip": geometry.Point(70, 160, None),
            "chin": geometry.Point(100, 145, .74),
        }
        intrinsics = object()
        metric = probe.deproject_body_points(
            points,
            intrinsics,
            types.SimpleNamespace(rs2_deproject_pixel_to_point=deproject),
        )
        self.assertEqual(metric["left_shoulder"], geometry.Point3D(.14, .10, .80))
        self.assertEqual(metric["left_hip"], geometry.Point3D(.13, .16, .85))
        self.assertEqual(metric["left_elbow"], geometry.Point3D(.155, .125, .78))
        self.assertEqual(metric["left_wrist"], geometry.Point3D(.165, .15, .76))
        self.assertEqual(metric["chin"], geometry.Point3D(.10, .145, .74))
        self.assertIsNone(metric["right_elbow"])
        self.assertIsNone(metric["right_wrist"])
        self.assertIsNone(metric["right_hip"])
        self.assertEqual(len(calls), 6)

    def test_chin_xyz_and_pitch_are_written_only_to_exploratory_csv(self):
        points = {
            "nose": geometry.Point(100, 40, .68),
            "left_ear": geometry.Point(120, 50, .70),
            "right_ear": geometry.Point(80, 50, .70),
            "chin": geometry.Point(100, 65, .68),
        }
        points_3d = {
            "nose": geometry.Point3D(0.0, -.55, .58),
            "left_ear": geometry.Point3D(.10, -.48, .70),
            "right_ear": geometry.Point3D(-.10, -.48, .70),
            "chin": geometry.Point3D(0.0, -.41, .58),
        }
        result = geometry.compute_candidate_geometry(points, points_3d=points_3d)
        row = probe.exploratory_csv_row(
            result,
            pose_detected=True,
            device_timestamp_ms=1.0,
            timestamp_utc="2026-10-08T00:00:00.000+00:00",
        )
        self.assertTrue(row["chin_landmark_valid"])
        self.assertTrue(row["chin_depth_valid"])
        self.assertEqual(row["chin_3d_x_m"], 0.0)
        self.assertEqual(row["chin_3d_y_m"], -.41)
        self.assertEqual(row["chin_3d_z_m"], .58)
        self.assertAlmostEqual(row["exploratory_head_pitch_deg"], 0.0)
        self.assertNotIn("frame_schema_version", probe.CSV_FIELDS)

    def test_csv_writer_is_opt_in_and_refuses_overwrite(self):
        handle, writer = probe._open_csv(None)
        self.assertIsNone(handle)
        self.assertIsNone(writer)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "exploratory.csv")
            handle, writer = probe._open_csv(path)
            try:
                writer.writerow(probe.exploratory_csv_row(
                    incomplete_result(), pose_detected=True, device_timestamp_ms=1.0,
                    timestamp_utc="2026-10-08T00:00:00.000+00:00"))
            finally:
                handle.close()
            with open(path, encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["artifact_kind"], probe.EXPLORATORY_ARTIFACT_KIND)
            self.assertEqual(rows[0]["nose_forward_from_torso_m"], "")
            with self.assertRaises(FileExistsError):
                probe._open_csv(path)


if __name__ == "__main__":
    unittest.main()
