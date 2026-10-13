import contextlib
import csv
import io
import itertools
import math
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
import warnings

import numpy as np

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


def result_with_nose_z(z_m):
    return geometry.compute_candidate_geometry(
        {"nose": geometry.Point(100, 40, z_m)},
        points_3d={"nose": geometry.Point3D(0.01, -0.02, z_m)},
    )


def readable_summary_result():
    return geometry.GeometryResult(
        points={},
        proxies={},
        points_3d={"nose": geometry.Point3D(0.01, -0.02, 0.85)},
        features={
            "exploratory_head_pitch_deg": 12.5,
            "sagittal_torso_lean_deg": -3.25,
            "shoulder_tilt_deg": 1.5,
            "shoulder_width_3d_m": 0.42,
            "nose_forward_normalized_by_shoulder_width_3d": 0.125,
        },
    )


def valid_matrix_values(pitch=4.5, yaw=-6.25, roll=2.0):
    return {
        "face_matrix_valid": True,
        "face_matrix_pitch_deg": pitch,
        "face_matrix_yaw_deg": yaw,
        "face_matrix_roll_deg": roll,
    }


def face_transform(
    *,
    pitch_deg=0.0,
    yaw_deg=0.0,
    roll_deg=0.0,
    scale=1.0,
    translation=(0.0, 0.0, 0.0),
):
    """Build the documented MediaPipe-space active rotation convention."""

    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)
    roll = math.radians(roll_deg)
    # Positive exploratory pitch rotates face-forward +Z toward image-up +Y,
    # hence the negative right-handed X rotation.
    pitch_rotation = np.array([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(pitch), math.sin(pitch)],
        [0.0, -math.sin(pitch), math.cos(pitch)],
    ])
    yaw_rotation = np.array([
        [math.cos(yaw), 0.0, math.sin(yaw)],
        [0.0, 1.0, 0.0],
        [-math.sin(yaw), 0.0, math.cos(yaw)],
    ])
    roll_rotation = np.array([
        [math.cos(roll), -math.sin(roll), 0.0],
        [math.sin(roll), math.cos(roll), 0.0],
        [0.0, 0.0, 1.0],
    ])
    transform = np.eye(4)
    transform[:3, :3] = scale * (
        roll_rotation @ yaw_rotation @ pitch_rotation
    )
    transform[:3, 3] = translation
    return transform


def face_landmarks(count=478, *, chin=(0.5, 0.5)):
    landmarks = [
        types.SimpleNamespace(x=0.5, y=0.5)
        for _ in range(count)
    ]
    chin_index = geometry.FACE_LANDMARK_INDICES["chin"]
    if count > chin_index:
        landmarks[chin_index] = types.SimpleNamespace(
            x=chin[0], y=chin[1]
        )
    return landmarks


def face_result(faces=None, matrices=None):
    return types.SimpleNamespace(
        face_landmarks=[] if faces is None else faces,
        facial_transformation_matrixes=[] if matrices is None else matrices,
    )


def diagnostic_row(result):
    return probe.face_pipeline_diagnostic_row(
        result,
        frame_index=7,
        device_timestamp_ms=123.5,
        mediapipe_timestamp_ms=124,
        rgb_width=1280,
        rgb_height=720,
        pose_detected=True,
    )


class ProbeHelperTests(unittest.TestCase):
    def assert_orientation(self, matrix, expected, places=7):
        actual = probe.extract_face_matrix_orientation(matrix)
        self.assertIsNotNone(actual)
        for actual_angle, expected_angle in zip(actual, expected):
            self.assertAlmostEqual(actual_angle, expected_angle, places=places)

    def test_face_matrix_identity_orientation(self):
        self.assert_orientation(np.eye(4), (0.0, 0.0, 0.0))

    def test_face_matrix_pitch_axes_and_signs(self):
        forward = np.array([0.0, 0.0, 1.0])
        for pitch in (-25.0, 25.0):
            with self.subTest(pitch=pitch):
                matrix = face_transform(pitch_deg=pitch)
                moved_forward = matrix[:3, :3] @ forward
                self.assertEqual(np.sign(moved_forward[1]), np.sign(pitch))
                self.assert_orientation(matrix, (pitch, 0.0, 0.0))

    def test_face_matrix_yaw_axes_signs_and_no_pitch_crosstalk(self):
        forward = np.array([0.0, 0.0, 1.0])
        for yaw in (-35.0, 35.0):
            with self.subTest(yaw=yaw):
                matrix = face_transform(yaw_deg=yaw)
                moved_forward = matrix[:3, :3] @ forward
                self.assertEqual(np.sign(moved_forward[0]), np.sign(yaw))
                pitch, actual_yaw, roll = (
                    probe.extract_face_matrix_orientation(matrix)
                )
                self.assertAlmostEqual(pitch, 0.0, places=7)
                self.assertAlmostEqual(actual_yaw, yaw, places=7)
                self.assertAlmostEqual(roll, 0.0, places=7)

    def test_face_matrix_roll_axes_and_signs(self):
        image_right = np.array([1.0, 0.0, 0.0])
        for roll in (-18.0, 18.0):
            with self.subTest(roll=roll):
                matrix = face_transform(roll_deg=roll)
                moved_right = matrix[:3, :3] @ image_right
                self.assertEqual(np.sign(moved_right[1]), np.sign(roll))
                self.assert_orientation(matrix, (0.0, 0.0, roll))

    def test_face_matrix_combined_known_rotation(self):
        self.assert_orientation(
            face_transform(pitch_deg=17.0, yaw_deg=-23.0, roll_deg=11.0),
            (17.0, -23.0, 11.0),
        )

    def test_face_matrix_uniform_scale_and_translation_do_not_change_angles(self):
        expected = (-12.0, 28.0, -9.0)
        self.assert_orientation(
            face_transform(
                pitch_deg=expected[0],
                yaw_deg=expected[1],
                roll_deg=expected[2],
                scale=2.75,
                translation=(13.0, -4.0, -65.0),
            ),
            expected,
        )

    def test_face_matrix_small_numerical_deviation_is_tolerated(self):
        matrix = face_transform(pitch_deg=8.0, yaw_deg=-14.0, roll_deg=5.0)
        matrix[:3, :3] += np.array([
            [1e-6, -2e-6, 0.0],
            [0.0, 1e-6, 2e-6],
            [-1e-6, 0.0, -1e-6],
        ])
        self.assert_orientation(matrix, (8.0, -14.0, 5.0), places=3)

    def test_official_mediapipe_reference_matrix_is_accepted(self):
        # Row-major 4x4 expected output from MediaPipe's Python landmarker test.
        matrix = np.array([
            [0.9995292, -0.01294756, 0.038823195, -0.3691378],
            [0.0072318087, 0.9937692, -0.1101321, 22.75809],
            [-0.03715533, 0.11070588, 0.99315894, -65.765925],
            [0.0, 0.0, 0.0, 1.0],
        ])
        pitch, yaw, roll = probe.extract_face_matrix_orientation(matrix)
        self.assertTrue(all(
            math.isfinite(angle) for angle in (pitch, yaw, roll)
        ))

    def test_invalid_face_matrices_never_produce_angles(self):
        invalid = {
            "missing": None,
            "wrong dimensions": np.eye(3),
            "nan": np.where(np.eye(4) == 1.0, np.nan, 0.0),
            "infinity": np.diag([1.0, 1.0, 1.0, math.inf]),
            "degenerate": np.diag([0.0, 0.0, 0.0, 1.0]),
            "reflection": np.diag([-1.0, 1.0, 1.0, 1.0]),
            "nonuniform scale": np.diag([1.0, 1.1, 1.0, 1.0]),
            "shear": np.array([
                [1.0, .1, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]),
            "bad homogeneous row": np.array([
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, .1, 1.0],
            ]),
        }
        for name, matrix in invalid.items():
            with self.subTest(name=name):
                self.assertIsNone(
                    probe.extract_face_matrix_orientation(matrix)
                )

    def test_first_face_matrix_requires_a_detected_face(self):
        matrix = face_transform(yaw_deg=10.0)
        self.assertIsNone(probe.first_face_transformation_matrix(None))
        self.assertIsNone(probe.first_face_transformation_matrix(
            types.SimpleNamespace(
                face_landmarks=[],
                facial_transformation_matrixes=[matrix],
            )
        ))
        self.assertIsNone(probe.first_face_transformation_matrix(
            types.SimpleNamespace(
                face_landmarks=[[object()]],
                facial_transformation_matrixes=[],
            )
        ))
        selected = probe.first_face_transformation_matrix(
            types.SimpleNamespace(
                face_landmarks=[[object()], [object()]],
                facial_transformation_matrixes=[matrix, np.eye(4)],
            )
        )
        self.assertIs(selected, matrix)

    def test_cli_default_has_no_output_path(self):
        args = probe.parse_args([])
        self.assertIsNone(args.csv)
        self.assertIsNone(args.face_diag_csv)
        self.assertIsNone(args.views)
        self.assertEqual(args.panel_mode, "summary")

    def test_cli_accepts_face_diagnostic_output_path(self):
        args = probe.parse_args(["--face-diag-csv", "face-diag.csv"])
        self.assertEqual(args.face_diag_csv, "face-diag.csv")

    def test_cli_accepts_debug_panel_without_changing_existing_options(self):
        args = probe.parse_args([
            "--panel-mode", "debug",
            "--csv", "engineering.csv",
            "--face-diag-csv", "face.csv",
            "--views", "avatar",
        ])
        self.assertEqual(args.panel_mode, "debug")
        self.assertEqual(args.csv, "engineering.csv")
        self.assertEqual(args.face_diag_csv, "face.csv")
        self.assertEqual(args.views, "avatar")

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
        self.assertFalse(row["face_matrix_valid"])
        self.assertIsNone(row["face_matrix_pitch_deg"])
        self.assertIsNone(row["face_matrix_yaw_deg"])
        self.assertIsNone(row["face_matrix_roll_deg"])

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

    def test_matrix_orientation_is_recorded_without_chin_depth(self):
        result = incomplete_result()
        self.assertIsNone(result.features["exploratory_head_pitch_deg"])
        matrix = face_transform(pitch_deg=6.0, yaw_deg=31.0, roll_deg=-4.0)
        row = probe.exploratory_csv_row(
            result,
            pose_detected=True,
            device_timestamp_ms=1.0,
            timestamp_utc="2026-10-08T00:00:00.000+00:00",
            face_matrix=matrix,
        )
        self.assertTrue(row["face_matrix_valid"])
        self.assertAlmostEqual(row["face_matrix_pitch_deg"], 6.0)
        self.assertAlmostEqual(row["face_matrix_yaw_deg"], 31.0)
        self.assertAlmostEqual(row["face_matrix_roll_deg"], -4.0)
        self.assertIsNone(row["exploratory_head_pitch_deg"])
        self.assertEqual(
            probe.CSV_FIELDS[-4:],
            probe.FACE_MATRIX_FIELDS,
        )
        self.assertNotIn("frame_schema_version", probe.CSV_FIELDS)

    def test_face_diagnostic_no_face(self):
        row = diagnostic_row(face_result())
        self.assertEqual(row["face_count"], 0)
        self.assertEqual(row["first_face_landmark_count"], 0)
        self.assertIsNone(row["chin_normalized_x"])
        self.assertIsNone(row["chin_coordinate_in_bounds"])
        self.assertEqual(row["face_matrix_count"], 0)
        self.assertFalse(row["face_matrix_selected"])
        self.assertIsNone(row["face_matrix_valid"])
        self.assertEqual(row["face_pipeline_status"], "NO_FACE")

    def test_face_diagnostic_valid_landmark_list(self):
        row = diagnostic_row(face_result(faces=[face_landmarks()]))
        self.assertEqual(row["face_count"], 1)
        self.assertEqual(row["first_face_landmark_count"], 478)
        self.assertEqual(row["chin_normalized_x"], 0.5)
        self.assertEqual(row["chin_normalized_y"], 0.5)
        self.assertTrue(row["chin_coordinate_in_bounds"])

    def test_face_diagnostic_face_without_chin(self):
        row = diagnostic_row(face_result(faces=[face_landmarks(152)]))
        self.assertEqual(row["first_face_landmark_count"], 152)
        self.assertIsNone(row["chin_normalized_x"])
        self.assertIsNone(row["chin_normalized_y"])
        self.assertIsNone(row["chin_coordinate_in_bounds"])
        self.assertEqual(row["face_pipeline_status"], "FACE_WITHOUT_CHIN")

    def test_face_diagnostic_chin_out_of_bounds(self):
        row = diagnostic_row(face_result(
            faces=[face_landmarks(chin=(1.01, -0.02))],
            matrices=[np.eye(4)],
        ))
        self.assertEqual(row["chin_normalized_x"], 1.01)
        self.assertEqual(row["chin_normalized_y"], -0.02)
        self.assertFalse(row["chin_coordinate_in_bounds"])
        self.assertTrue(row["face_matrix_valid"])
        self.assertEqual(row["face_pipeline_status"], "CHIN_OUT_OF_BOUNDS")

    def test_face_diagnostic_matrix_missing(self):
        row = diagnostic_row(face_result(faces=[face_landmarks()]))
        self.assertEqual(row["face_matrix_count"], 0)
        self.assertFalse(row["face_matrix_selected"])
        self.assertIsNone(row["face_matrix_valid"])
        self.assertEqual(row["face_pipeline_status"], "MATRIX_MISSING")

    def test_face_diagnostic_matrix_invalid(self):
        row = diagnostic_row(face_result(
            faces=[face_landmarks()],
            matrices=[np.eye(3)],
        ))
        self.assertEqual(row["face_matrix_count"], 1)
        self.assertTrue(row["face_matrix_selected"])
        self.assertFalse(row["face_matrix_valid"])
        self.assertEqual(row["face_pipeline_status"], "MATRIX_INVALID")

    def test_face_diagnostic_matrix_valid(self):
        row = diagnostic_row(face_result(
            faces=[face_landmarks()],
            matrices=[face_transform(yaw_deg=9.0)],
        ))
        self.assertEqual(row["face_matrix_count"], 1)
        self.assertTrue(row["face_matrix_selected"])
        self.assertTrue(row["face_matrix_valid"])
        self.assertEqual(row["face_pipeline_status"], "MATRIX_VALID")

    def test_face_diagnostic_selects_first_face_and_matrix(self):
        row = diagnostic_row(face_result(
            faces=[
                face_landmarks(chin=(0.25, 0.4)),
                face_landmarks(chin=(0.75, 0.6)),
            ],
            matrices=[np.eye(4), np.eye(3)],
        ))
        self.assertEqual(row["face_count"], 2)
        self.assertEqual(row["face_matrix_count"], 2)
        self.assertEqual(row["chin_normalized_x"], 0.25)
        self.assertTrue(row["face_matrix_valid"])
        self.assertEqual(row["face_pipeline_status"], "MATRIX_VALID")

    def test_frame_inference_calls_each_landmarker_once(self):
        class FakeLandmarker:
            def __init__(self, result):
                self.result = result
                self.calls = []

            def detect_for_video(self, image, timestamp):
                self.calls.append((image, timestamp))
                return self.result

        image = object()
        pose = FakeLandmarker("pose result")
        face = FakeLandmarker("face result")
        results = probe.run_frame_inference(pose, face, image, 456)
        self.assertEqual(results, ("pose result", "face result"))
        self.assertEqual(pose.calls, [(image, 456)])
        self.assertEqual(face.calls, [(image, 456)])

    def test_panel_displays_valid_nose_z_in_metres(self):
        lines = probe.engineering_panel_diagnostic_lines(
            result_with_nose_z(1.024),
            face_detected=True,
            face_matrix=np.eye(4),
        )
        self.assertEqual(lines[0], "Nose Z Depth: 1.02 m")

    def test_panel_displays_unavailable_for_missing_or_nonfinite_nose_z(self):
        missing_lines = probe.engineering_panel_diagnostic_lines(
            incomplete_result(),
            face_detected=True,
            face_matrix=np.eye(4),
        )
        nonfinite_result = geometry.GeometryResult(
            points={},
            proxies={},
            features={},
            points_3d={"nose": geometry.Point3D(0.0, 0.0, math.nan)},
        )
        nonfinite_lines = probe.engineering_panel_diagnostic_lines(
            nonfinite_result,
            face_detected=True,
            face_matrix=np.eye(4),
        )
        self.assertEqual(missing_lines[0], "Nose Z Depth: unavailable")
        self.assertEqual(nonfinite_lines[0], "Nose Z Depth: unavailable")

    def test_panel_distinguishes_face_detection_status(self):
        detected = probe.engineering_panel_diagnostic_lines(
            incomplete_result(), face_detected=True, face_matrix=None
        )
        missing = probe.engineering_panel_diagnostic_lines(
            incomplete_result(), face_detected=False, face_matrix=None
        )
        self.assertEqual(detected[1], "FaceLandmarker: DETECTED")
        self.assertEqual(missing[1], "FaceLandmarker: NO_FACE")

    def test_panel_distinguishes_matrix_status(self):
        cases = (
            (np.eye(4), "Face Matrix: VALID"),
            (None, "Face Matrix: MISSING"),
            (np.eye(3), "Face Matrix: INVALID"),
        )
        for matrix, expected in cases:
            with self.subTest(expected=expected):
                lines = probe.engineering_panel_diagnostic_lines(
                    incomplete_result(),
                    face_detected=True,
                    face_matrix=matrix,
                )
                self.assertEqual(lines[2], expected)

    def test_panel_keeps_pose_nose_depth_when_face_is_not_detected(self):
        lines = probe.engineering_panel_diagnostic_lines(
            result_with_nose_z(0.765),
            face_detected=False,
            face_matrix=None,
        )
        self.assertEqual(lines, (
            "Nose Z Depth: 0.77 m",
            "FaceLandmarker: NO_FACE",
            "Face Matrix: MISSING",
        ))

    def test_panel_diagnostics_do_not_change_engineering_csv_values(self):
        result = result_with_nose_z(0.7654321)
        row = probe.exploratory_csv_row(
            result,
            pose_detected=True,
            device_timestamp_ms=123.5,
            timestamp_utc="2026-10-08T00:00:00.000+00:00",
            face_matrix=np.eye(4),
        )
        self.assertEqual(set(row), set(probe.CSV_FIELDS))
        self.assertEqual(row["nose_3d_z_m"], 0.7654321)
        self.assertTrue(row["face_matrix_valid"])
        for display_only_name in (
            "nose_z_depth",
            "face_landmarker_status",
            "face_matrix_status",
        ):
            self.assertNotIn(display_only_name, probe.CSV_FIELDS)

    def test_rendering_does_not_change_csv_bytes_or_field_semantics(self):
        result = readable_summary_result()
        matrix = face_transform(pitch_deg=4.5, yaw_deg=-6.25, roll_deg=2.0)

        def csv_text():
            row = probe.exploratory_csv_row(
                result,
                pose_detected=True,
                device_timestamp_ms=123.5,
                timestamp_utc="2026-10-08T00:00:00.000+00:00",
                face_matrix=matrix,
            )
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=probe.CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)
            return output.getvalue(), row

        before_text, before_row = csv_text()
        probe.draw_engineering_panel(
            np.zeros((720, 1280, 3), dtype=np.uint8),
            result,
            pose_detected=True,
            face_detected=True,
            face_matrix=matrix,
            face_matrix_values=probe._face_matrix_csv_values(matrix),
        )
        after_text, after_row = csv_text()
        self.assertEqual(after_text, before_text)
        self.assertEqual(after_row, before_row)
        self.assertEqual(tuple(csv.DictReader(
            io.StringIO(after_text)
        ).fieldnames), probe.CSV_FIELDS)

    def test_same_inference_result_supplies_panel_without_another_detection(self):
        class FakeLandmarker:
            def __init__(self, result):
                self.result = result
                self.call_count = 0

            def detect_for_video(self, image, timestamp):
                self.call_count += 1
                return self.result

        matrix = face_transform(yaw_deg=12.0)
        expected_face_result = face_result(
            faces=[face_landmarks()], matrices=[matrix]
        )
        pose = FakeLandmarker(types.SimpleNamespace(pose_landmarks=[]))
        face = FakeLandmarker(expected_face_result)
        _, actual_face_result = probe.run_frame_inference(
            pose, face, object(), 456
        )
        selected_matrix = probe.first_face_transformation_matrix(
            actual_face_result
        )
        lines = probe.engineering_panel_diagnostic_lines(
            result_with_nose_z(0.8),
            face_detected=bool(actual_face_result.face_landmarks),
            face_matrix=selected_matrix,
        )
        self.assertEqual(pose.call_count, 1)
        self.assertEqual(face.call_count, 1)
        self.assertIs(selected_matrix, matrix)
        self.assertEqual(lines[1:], (
            "FaceLandmarker: DETECTED",
            "Face Matrix: VALID",
        ))

    def test_existing_panel_call_remains_compatible(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        rendered = probe.draw_engineering_panel(
            image, incomplete_result(), pose_detected=True
        )
        self.assertEqual(rendered.shape, (760, 1911, 3))

    def test_korean_summary_labels_are_explicit_and_human_readable(self):
        labels = probe.SUMMARY_LABELS_KO
        self.assertEqual(labels["title"], "D455 자세 측정 — 개발용")
        self.assertEqual(
            labels["subtitle"],
            "비정식 탐색 측정 | 자세 정상/비정상 판정 아님",
        )
        for key in (
            "camera_section", "nose_depth", "face_detection",
            "matrix_status", "head_section", "chin_pitch",
            "matrix_pitch", "matrix_yaw", "matrix_roll",
            "body_section", "torso_lean", "shoulder_tilt",
            "shoulder_width", "head_forward", "status_section",
        ):
            self.assertRegex(labels[key], "[가-힣]")

    def test_summary_keeps_chin_and_matrix_orientations_distinct(self):
        values = probe.panel_measurement_values(
            readable_summary_result(),
            face_detected=True,
            face_matrix=np.eye(4),
            face_matrix_values=valid_matrix_values(),
        )
        self.assertEqual(values["chin_pitch_deg"], 12.5)
        self.assertEqual(values["matrix_pitch_deg"], 4.5)
        self.assertEqual(values["matrix_yaw_deg"], -6.25)
        self.assertEqual(values["matrix_roll_deg"], 2.0)
        texts = {
            item[0] for item in probe._summary_layout_items(
                values, korean=True
            )
        }
        self.assertIn("기존 턱 기반 상하 회전", texts)
        self.assertIn("신규 Matrix 상하 회전", texts)
        self.assertIn("신규 Matrix 좌우 회전", texts)
        self.assertIn("신규 Matrix 좌우 기울기", texts)
        self.assertIn("+12.50°", texts)
        self.assertIn("+4.50°", texts)
        self.assertIn("-6.25°", texts)
        self.assertIn("+2.00°", texts)

    def test_korean_summary_formats_depth_and_all_detection_states(self):
        cases = (
            (True, np.eye(4), valid_matrix_values(), "검출됨", "유효"),
            (
                False,
                None,
                {
                    "face_matrix_valid": False,
                    "face_matrix_pitch_deg": None,
                    "face_matrix_yaw_deg": None,
                    "face_matrix_roll_deg": None,
                },
                "미검출",
                "누락",
            ),
            (
                True,
                np.eye(3),
                {
                    "face_matrix_valid": False,
                    "face_matrix_pitch_deg": None,
                    "face_matrix_yaw_deg": None,
                    "face_matrix_roll_deg": None,
                },
                "검출됨",
                "무효",
            ),
        )
        for detected, matrix, matrix_values, face_text, matrix_text in cases:
            with self.subTest(face=face_text, matrix=matrix_text):
                values = probe.panel_measurement_values(
                    readable_summary_result(),
                    face_detected=detected,
                    face_matrix=matrix,
                    face_matrix_values=matrix_values,
                )
                texts = {
                    item[0] for item in probe._summary_layout_items(
                        values, korean=True
                    )
                }
                self.assertIn("0.85 m", texts)
                self.assertIn(face_text, texts)
                self.assertIn(matrix_text, texts)

        unavailable = probe.panel_measurement_values(
            incomplete_result(),
            face_detected=False,
            face_matrix=None,
            face_matrix_values={
                "face_matrix_valid": False,
                "face_matrix_pitch_deg": None,
                "face_matrix_yaw_deg": None,
                "face_matrix_roll_deg": None,
            },
        )
        unavailable_texts = {
            item[0] for item in probe._summary_layout_items(
                unavailable, korean=True
            )
        }
        self.assertIn("측정 불가", unavailable_texts)

    def test_invalid_matrix_never_displays_zero_orientation(self):
        invalid = {
            "face_matrix_valid": False,
            "face_matrix_pitch_deg": 0.0,
            "face_matrix_yaw_deg": 0.0,
            "face_matrix_roll_deg": 0.0,
        }
        values = probe.panel_measurement_values(
            readable_summary_result(),
            face_detected=True,
            face_matrix=np.eye(3),
            face_matrix_values=invalid,
        )
        self.assertEqual(values["matrix_status"], "INVALID")
        self.assertEqual(values["chin_pitch_deg"], 12.5)
        self.assertIsNone(values["matrix_pitch_deg"])
        self.assertIsNone(values["matrix_yaw_deg"])
        self.assertIsNone(values["matrix_roll_deg"])
        texts = [
            item[0] for item in probe._summary_layout_items(
                values, korean=True
            )
        ]
        self.assertEqual(texts.count("측정 불가"), 3)
        self.assertNotIn("+0.00°", texts)

    def test_debug_pages_retain_features_sources_and_validity(self):
        result = readable_summary_result()
        values = probe.panel_measurement_values(
            result,
            face_detected=True,
            face_matrix=np.eye(4),
            face_matrix_values=valid_matrix_values(),
        )
        pages = probe.debug_panel_pages(result, True, values)
        self.assertEqual(len(pages), probe.DEBUG_PAGE_COUNT)
        all_text = " | ".join(
            line for _, lines in pages for line in lines
        )
        for _, key, _ in probe.FEATURE_DISPLAY:
            self.assertIn(f"{key}:", all_text)
        for name in probe.POINT_NAMES:
            self.assertIn(f"{name}:", all_text)
        self.assertIn("face_matrix_pitch_deg:", all_text)
        self.assertIn("landmark=", all_text)
        self.assertIn("depth=", all_text)
        self.assertIn("nose_forward_normalized_by_shoulder_width_3d", all_text)

    def test_summary_layout_fits_korean_font_without_overlap(self):
        from PIL import Image, ImageDraw

        fonts = probe._load_korean_fonts()
        self.assertIsNotNone(fonts)
        values = probe.panel_measurement_values(
            readable_summary_result(),
            face_detected=True,
            face_matrix=np.eye(4),
            face_matrix_values=valid_matrix_values(),
        )
        draw = ImageDraw.Draw(Image.new(
            "RGB", (probe.PANEL_WIDTH, probe.PANEL_HEIGHT)
        ))
        boxes = []
        for text, x, y, font_key, _, anchor in probe._summary_layout_items(
            values, korean=True
        ):
            box = draw.textbbox(
                (x, y), text, font=fonts[font_key], anchor=anchor
            )
            self.assertGreaterEqual(box[0], 0, msg=text)
            self.assertGreaterEqual(box[1], 0, msg=text)
            self.assertLessEqual(box[2], probe.PANEL_WIDTH, msg=text)
            self.assertLessEqual(box[3], probe.PANEL_HEIGHT, msg=text)
            boxes.append((box, text))
        for index, (first, first_text) in enumerate(boxes):
            for second, second_text in boxes[index + 1:]:
                overlap = (
                    first[0] < second[2] and second[0] < first[2]
                    and first[1] < second[3] and second[1] < first[3]
                )
                self.assertFalse(
                    overlap,
                    msg=f"summary text overlaps: {first_text!r} / {second_text!r}",
                )

    def test_summary_uses_unicode_capable_pillow_path(self):
        fonts = probe._load_korean_fonts()
        self.assertIsNotNone(fonts)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with mock.patch.object(
            probe,
            "_draw_summary_panel_with_pillow",
            wraps=probe._draw_summary_panel_with_pillow,
        ) as pillow_draw:
            probe.draw_engineering_panel(
                image,
                readable_summary_result(),
                pose_detected=True,
                face_detected=True,
                face_matrix=np.eye(4),
                face_matrix_values=valid_matrix_values(),
            )
        pillow_draw.assert_called_once()

    def test_missing_korean_font_falls_back_without_crashing(self):
        import cv2

        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with mock.patch.object(probe, "_load_korean_fonts", return_value=None), \
                mock.patch.object(probe, "_FONT_WARNING_EMITTED", False), \
                mock.patch.object(cv2, "putText", wraps=cv2.putText) as put_text, \
                warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rendered = probe.draw_engineering_panel(
                image,
                readable_summary_result(),
                pose_detected=True,
                face_detected=False,
                face_matrix=None,
                face_matrix_values={
                    "face_matrix_valid": False,
                    "face_matrix_pitch_deg": None,
                    "face_matrix_yaw_deg": None,
                    "face_matrix_roll_deg": None,
                },
            )
        self.assertEqual(rendered.shape, (760, 1911, 3))
        self.assertTrue(any("English fallback" in str(w.message) for w in caught))
        self.assertTrue(any(
            call.args[1] == probe.SUMMARY_LABELS_EN["title"]
            for call in put_text.call_args_list
        ))
        self.assertFalse(any(
            any("가" <= character <= "힣" for character in call.args[1])
            for call in put_text.call_args_list
        ))

    def test_rendering_uses_precomputed_matrix_values(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with mock.patch.object(
            probe,
            "extract_face_matrix_orientation",
            side_effect=AssertionError("rendering repeated matrix extraction"),
        ):
            probe.draw_engineering_panel(
                image,
                readable_summary_result(),
                pose_detected=True,
                face_detected=True,
                face_matrix=np.eye(4),
                face_matrix_values=valid_matrix_values(),
            )

    def test_panel_keyboard_keeps_quit_and_pages_debug_only(self):
        self.assertEqual(
            probe.handle_panel_key(ord("q"), "summary", 2),
            (True, 2),
        )
        self.assertEqual(
            probe.handle_panel_key(ord("]"), "debug", 0),
            (False, 1),
        )
        self.assertEqual(
            probe.handle_panel_key(ord("["), "debug", 0),
            (False, probe.DEBUG_PAGE_COUNT - 1),
        )
        self.assertEqual(
            probe.handle_panel_key(ord("]"), "summary", 3),
            (False, 3),
        )

    def test_main_keeps_3d_view_selection_separate_from_panel_mode(self):
        with mock.patch.object(probe, "run_probe") as run_probe:
            self.assertEqual(probe.main([
                "--panel-mode", "debug", "--views", "all"
            ]), 0)
        run_probe.assert_called_once_with(
            None,
            face_diag_csv_path=None,
            show_3d_views="all",
            panel_mode="debug",
            pyvista_view=False,
            pyvista_anchor="shoulder",
            f1_live=False,
            rf_demo_model_path=None,
        )

    def test_pyvista_view_is_opt_in_and_independent_of_opencv_views(self):
        self.assertFalse(probe.parse_args([]).pyvista)
        args = probe.parse_args(["--pyvista", "--views", "side", "--csv", "e.csv"])
        self.assertTrue(args.pyvista)
        self.assertEqual(args.views, "side")
        self.assertEqual(args.csv, "e.csv")
        with mock.patch.object(probe, "run_probe") as run_probe:
            self.assertEqual(probe.main(["--pyvista"]), 0)
        run_probe.assert_called_once_with(
            None,
            face_diag_csv_path=None,
            show_3d_views=None,
            panel_mode="summary",
            pyvista_view=True,
            pyvista_anchor="shoulder",
            f1_live=False,
            rf_demo_model_path=None,
        )

    def test_pyvista_camera_anchor_is_opt_in_and_requires_pyvista(self):
        self.assertEqual(probe.parse_args(["--pyvista"]).pyvista_anchor, "shoulder")
        with mock.patch.object(probe, "run_probe") as run_probe:
            self.assertEqual(
                probe.main(["--pyvista", "--pyvista-anchor", "camera"]), 0
            )
        run_probe.assert_called_once_with(
            None,
            face_diag_csv_path=None,
            show_3d_views=None,
            panel_mode="summary",
            pyvista_view=True,
            pyvista_anchor="camera",
            f1_live=False,
            rf_demo_model_path=None,
        )
        with mock.patch("sys.stderr"):
            for argv in (["--pyvista-anchor", "camera"],
                         ["--pyvista", "--pyvista-anchor", "hips"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    probe.parse_args(argv)

    def test_debug_pages_are_visible_and_do_not_overlap_or_clip(self):
        import cv2

        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        for page in range(probe.DEBUG_PAGE_COUNT):
            with self.subTest(page=page):
                with mock.patch.object(
                    cv2, "putText", wraps=cv2.putText
                ) as put_text:
                    rendered = probe.draw_engineering_panel(
                        image,
                        readable_summary_result(),
                        pose_detected=True,
                        face_detected=True,
                        face_matrix=np.eye(4),
                        face_matrix_values=valid_matrix_values(),
                        panel_mode="debug",
                        debug_page=page,
                    )

                self.assertEqual(rendered.shape, (760, 1911, 3))
                vertical_boxes = []
                for call in put_text.call_args_list:
                    text = call.args[1]
                    x, y = call.args[2]
                    scale = call.args[4]
                    (width, height), baseline = cv2.getTextSize(
                        text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1
                    )
                    self.assertGreaterEqual(x, 0)
                    self.assertLessEqual(x + width, probe.PANEL_WIDTH)
                    self.assertGreaterEqual(y - height, 0)
                    self.assertLessEqual(y + baseline, probe.PANEL_HEIGHT)
                    vertical_boxes.append((y - height, y + baseline, text))
                vertical_boxes.sort()
                for first, second in zip(
                    vertical_boxes, vertical_boxes[1:]
                ):
                    self.assertLess(
                        first[1], second[0],
                        msg=(
                            f"panel rows overlap: {first[2]!r} / "
                            f"{second[2]!r}"
                        ),
                    )
                self.assertTrue(any(
                    f"DEBUG {page + 1}/{probe.DEBUG_PAGE_COUNT}" in call.args[1]
                    for call in put_text.call_args_list
                ))

    def test_diagnostic_csv_header_values_and_frame_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            engineering_path = os.path.join(directory, "engineering.csv")
            diagnostic_path = os.path.join(directory, "face-diagnostic.csv")
            eng_handle, eng_writer = probe._open_csv(engineering_path)
            diag_handle, diag_writer = probe._open_face_diagnostic_csv(
                diagnostic_path
            )
            try:
                eng_writer.writerow(probe.exploratory_csv_row(
                    incomplete_result(),
                    pose_detected=True,
                    device_timestamp_ms=123.5,
                    timestamp_utc="2026-10-08T00:00:00.000+00:00",
                ))
                diag_writer.writerow(diagnostic_row(face_result(
                    faces=[face_landmarks()],
                    matrices=[np.eye(4)],
                )))
                eng_handle.flush()
                diag_handle.flush()
            finally:
                eng_handle.close()
                diag_handle.close()

            with open(engineering_path, encoding="utf-8") as source:
                engineering_reader = csv.DictReader(source)
                engineering_rows = list(engineering_reader)
            with open(diagnostic_path, encoding="utf-8") as source:
                diagnostic_reader = csv.DictReader(source)
                diagnostic_rows = list(diagnostic_reader)

            self.assertEqual(
                tuple(diagnostic_reader.fieldnames),
                probe.FACE_DIAGNOSTIC_FIELDS,
            )
            self.assertEqual(len(engineering_rows), 1)
            self.assertEqual(len(diagnostic_rows), 1)
            self.assertEqual(
                engineering_rows[0]["device_timestamp_ms"],
                diagnostic_rows[0]["device_timestamp_ms"],
            )
            self.assertEqual(diagnostic_rows[0]["frame_index"], "7")
            self.assertEqual(diagnostic_rows[0]["mediapipe_timestamp_ms"], "124")
            self.assertEqual(diagnostic_rows[0]["face_pipeline_status"], "MATRIX_VALID")
            self.assertEqual(diagnostic_rows[0]["chin_coordinate_in_bounds"], "True")

    def test_diagnostic_csv_is_opt_in_and_refuses_overwrite(self):
        handle, writer = probe._open_face_diagnostic_csv(None)
        self.assertIsNone(handle)
        self.assertIsNone(writer)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "face-diagnostic.csv")
            handle, _ = probe._open_face_diagnostic_csv(path)
            handle.close()
            with self.assertRaises(FileExistsError):
                probe._open_face_diagnostic_csv(path)

    def test_diagnostic_fields_do_not_change_engineering_csv_header(self):
        for field in (
            "frame_index",
            "mediapipe_timestamp_ms",
            "rgb_width",
            "rgb_height",
            "face_count",
            "first_face_landmark_count",
            "chin_normalized_x",
            "chin_normalized_y",
            "chin_coordinate_in_bounds",
            "face_matrix_count",
            "face_matrix_selected",
            "face_pipeline_status",
        ):
            self.assertNotIn(field, probe.CSV_FIELDS)

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
            self.assertEqual(rows[0]["face_matrix_valid"], "False")
            self.assertEqual(rows[0]["face_matrix_pitch_deg"], "")
            self.assertEqual(rows[0]["face_matrix_yaw_deg"], "")
            self.assertEqual(rows[0]["face_matrix_roll_deg"], "")
            with self.assertRaises(FileExistsError):
                probe._open_csv(path)


# ---------------------------------------------------------------- live F1-5
IMAGE_W, IMAGE_H = 1280, 720


def pose_landmark(x, y, visibility=0.9, presence=0.95):
    return types.SimpleNamespace(
        x=x, y=y, visibility=visibility, presence=presence
    )


def live_pose_result(**overrides):
    """Synthetic subject facing the camera: subject-left appears image-right."""

    landmarks = [pose_landmark(0.5, 0.5) for _ in range(33)]
    landmarks[0] = pose_landmark(0.51, 0.18)    # nose
    landmarks[11] = pose_landmark(0.60, 0.40)   # subject-left shoulder
    landmarks[12] = pose_landmark(0.40, 0.40)   # subject-right shoulder
    landmarks[13] = pose_landmark(0.70, 0.55)   # decoy: left elbow
    landmarks[14] = pose_landmark(0.30, 0.55)   # decoy: right elbow
    landmarks[23] = pose_landmark(0.60, 0.80)   # subject-left hip
    landmarks[24] = pose_landmark(0.44, 0.82)   # subject-right hip
    for index, landmark in overrides.items():
        landmarks[int(index.lstrip("i"))] = landmark
    return types.SimpleNamespace(pose_landmarks=[landmarks])


def face_detection(origin_x, origin_y, width, height):
    return types.SimpleNamespace(
        bounding_box=types.SimpleNamespace(
            origin_x=origin_x, origin_y=origin_y, width=width, height=height
        ),
        categories=[],
    )


def face_detector_result(*detections):
    return types.SimpleNamespace(detections=list(detections))


DEFAULT_FACE = face_detection(610, 90, 80, 100)   # centre (650, 140) px


def live_f1(detector=None, pose=None):
    return probe.compute_live_f1(
        face_detector_result(DEFAULT_FACE) if detector is None else detector,
        live_pose_result() if pose is None else pose,
        IMAGE_W,
        IMAGE_H,
    )


def f1_panel_texts(live, width=1911):
    return [item[0] for item in probe.f1_panel_layout_items(live, width)]


class FakeTask:
    def __init__(self, result):
        self.result = result
        self.video_calls = []
        self.image_calls = []
        self.close_count = 0

    def detect_for_video(self, image, timestamp_ms):
        self.video_calls.append((image, timestamp_ms))
        return self.result

    def detect(self, image):
        self.image_calls.append(image)
        return self.result

    def close(self):
        self.close_count += 1


class FakeLiveLoop:
    """Runs run_probe with fake RealSense/MediaPipe; no hardware required."""

    def __init__(self, *, frame_count=1, loop_error=None):
        self.frame_count = frame_count
        self.loop_error = loop_error
        self.pose = FakeTask(live_pose_result())
        # FaceLandmarker landmarks sit at (640, 360) px: distinct from F.
        self.face_landmarker = FakeTask(face_result(
            faces=[face_landmarks()], matrices=[np.eye(4)]
        ))
        self.face_detector = FakeTask(face_detector_result(DEFAULT_FACE))
        self.options = []
        self.detector_create_count = 0
        self.shown = []
        self.live_results = []
        self.created_files = []

    def _options(self, kind):
        def factory(**kwargs):
            self.options.append((kind, kwargs))
            return (kind, kwargs)
        return factory

    def _create_detector(self, options):
        self.detector_create_count += 1
        return self.face_detector

    def _modules(self):
        vision = types.SimpleNamespace(
            RunningMode=types.SimpleNamespace(VIDEO="VIDEO"),
            PoseLandmarkerOptions=self._options("pose"),
            FaceLandmarkerOptions=self._options("mesh"),
            FaceDetectorOptions=self._options("face"),
            PoseLandmarker=types.SimpleNamespace(
                create_from_options=lambda options: self.pose
            ),
            FaceLandmarker=types.SimpleNamespace(
                create_from_options=lambda options: self.face_landmarker
            ),
            FaceDetector=types.SimpleNamespace(
                create_from_options=self._create_detector
            ),
        )
        mpt = types.SimpleNamespace(
            BaseOptions=lambda **kwargs: kwargs, vision=vision
        )
        mp = types.SimpleNamespace(
            Image=lambda image_format, data: types.SimpleNamespace(data=data),
            ImageFormat=types.SimpleNamespace(SRGB="SRGB"),
            tasks=types.SimpleNamespace(python=mpt),
        )
        timestamps = itertools.count(1000.0, 66.7)
        color = types.SimpleNamespace(
            get_data=lambda: np.zeros((IMAGE_H, IMAGE_W, 3), dtype=np.uint8)
        )
        depth = types.SimpleNamespace(
            get_data=lambda: np.zeros((IMAGE_H, IMAGE_W), dtype=np.uint16)
        )
        aligned = types.SimpleNamespace(
            get_color_frame=lambda: color, get_depth_frame=lambda: depth
        )
        frame_set = types.SimpleNamespace(
            get_timestamp=lambda: next(timestamps)
        )
        intrinsics = types.SimpleNamespace(fx=900.0)
        profile = types.SimpleNamespace(
            get_device=lambda: types.SimpleNamespace(
                first_depth_sensor=lambda: types.SimpleNamespace(
                    get_depth_scale=lambda: 0.001
                )
            ),
            get_stream=lambda stream: types.SimpleNamespace(
                as_video_stream_profile=lambda: types.SimpleNamespace(
                    get_intrinsics=lambda: intrinsics
                )
            ),
        )
        self.pipeline = mock.Mock()
        self.pipeline.start.return_value = profile
        self.pipeline.wait_for_frames.return_value = frame_set
        rs = types.SimpleNamespace(
            pipeline=lambda: self.pipeline,
            align=lambda stream: types.SimpleNamespace(
                process=lambda frames: aligned
            ),
            stream=types.SimpleNamespace(color="color"),
        )
        return {
            "mediapipe": mp,
            "mediapipe.tasks": mp.tasks,
            "mediapipe.tasks.python": mpt,
            "mediapipe.tasks.python.vision": vision,
            "pyrealsense2": rs,
            "capture_d455": types.SimpleNamespace(make_config=lambda: "cfg"),
        }

    def run(self, **kwargs):
        import cv2
        import analyze_d455
        # patch.dict restores sys.modules on exit, evicting modules first
        # imported inside it; import rendering dependencies beforehand.
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        probe._load_korean_fonts()

        keys = [-1] * (self.frame_count - 1) + [ord("q")]

        def wait_key(delay):
            if self.loop_error is not None:
                raise self.loop_error
            return keys.pop(0)

        def capture_live(*args):
            live = original_compute(*args)
            self.live_results.append(live)
            return live

        original_compute = probe.compute_live_f1
        models = {"face": "face-model", "mesh": "mesh-model", "pose": "pose-model"}
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                with mock.patch.dict(sys.modules, self._modules()), \
                        mock.patch.object(analyze_d455, "ensure_models", return_value=models), \
                        mock.patch.object(probe, "compute_live_f1", side_effect=capture_live), \
                        mock.patch.object(cv2, "imshow", side_effect=lambda name, image: self.shown.append((name, image.shape))), \
                        mock.patch.object(cv2, "waitKey", side_effect=wait_key), \
                        mock.patch.object(cv2, "destroyAllWindows"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    probe.run_probe(**kwargs)
            finally:
                self.created_files = sorted(os.listdir(directory))
                os.chdir(previous_cwd)
        return self

    def main_window_shapes(self):
        return [shape for name, shape in self.shown if name == probe.WINDOW_NAME]


class LiveF1InputTests(unittest.TestCase):
    def test_cli_f1_live_is_opt_in(self):
        self.assertFalse(probe.parse_args([]).f1_live)
        self.assertTrue(probe.parse_args(["--f1-live"]).f1_live)
        args = probe.parse_args(["--views", "side", "--pyvista", "--f1-live"])
        self.assertTrue(args.f1_live)
        self.assertEqual(args.views, "side")
        self.assertTrue(args.pyvista)
        with mock.patch.object(probe, "run_probe") as run_probe:
            self.assertEqual(probe.main(["--views", "side", "--f1-live"]), 0)
        run_probe.assert_called_once_with(
            None,
            face_diag_csv_path=None,
            show_3d_views="side",
            panel_mode="summary",
            pyvista_view=False,
            pyvista_anchor="shoulder",
            f1_live=True,
            rf_demo_model_path=None,
        )

    def test_existing_3d_options_are_unchanged_by_f1_live(self):
        for extra in ([], ["--f1-live"]):
            with self.subTest(extra=extra):
                self.assertEqual(probe.parse_args(["--views", *extra]).views, "side")
                for mode in ("side", "debug", "skeleton", "avatar", "all"):
                    self.assertEqual(
                        probe.parse_args(["--views", mode, *extra]).views, mode
                    )
                args = probe.parse_args(
                    ["--pyvista", "--pyvista-anchor", "camera", *extra]
                )
                self.assertEqual(args.pyvista_anchor, "camera")
                with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                    probe.parse_args(["--pyvista-anchor", "camera", *extra])

    def test_frame_input_uses_original_pixel_coordinates(self):
        frame = live_f1().frame
        self.assertEqual(tuple(frame), probe.F1_INPUT_FIELDS)
        self.assertTrue(frame["face_detected"])
        self.assertEqual((frame["face_x"], frame["face_y"]), (650.0, 140.0))
        self.assertTrue(frame["lsh_valid"])
        self.assertTrue(frame["rsh_valid"])
        self.assertAlmostEqual(frame["lsh_x"], 0.60 * IMAGE_W)
        self.assertAlmostEqual(frame["lsh_y"], 0.40 * IMAGE_H)
        self.assertAlmostEqual(frame["rsh_x"], 0.40 * IMAGE_W)
        self.assertAlmostEqual(frame["rsh_y"], 0.40 * IMAGE_H)
        self.assertTrue(frame["left_hip_valid"])
        self.assertTrue(frame["right_hip_valid"])
        self.assertAlmostEqual(frame["left_hip_x_px"], 0.60 * IMAGE_W)
        self.assertAlmostEqual(frame["left_hip_y_px"], 0.80 * IMAGE_H)
        self.assertAlmostEqual(frame["right_hip_x_px"], 0.44 * IMAGE_W)
        self.assertAlmostEqual(frame["right_hip_y_px"], 0.82 * IMAGE_H)

    def test_coordinates_are_not_mirrored(self):
        frame = live_f1().frame
        # Subject facing the camera: subject-left shoulder stays image-right.
        self.assertGreater(frame["lsh_x"], frame["rsh_x"])
        self.assertNotAlmostEqual(frame["lsh_x"], IMAGE_W - 0.60 * IMAGE_W)
        # Mirroring the input flips fs_x sign; the probe must not do that.
        result = live_f1().result
        self.assertAlmostEqual(result.features["fs_x"], (650 - 640) / 256)

    def test_subject_left_right_indices_11_12_23_24(self):
        pose = live_pose_result(
            i11=pose_landmark(0.61, 0.41),
            i12=pose_landmark(0.39, 0.43),
            i23=pose_landmark(0.57, 0.79),
            i24=pose_landmark(0.45, 0.81),
        )
        frame = live_f1(pose=pose).frame
        self.assertAlmostEqual(frame["lsh_x"], 0.61 * IMAGE_W)
        self.assertAlmostEqual(frame["rsh_y"], 0.43 * IMAGE_H)
        self.assertAlmostEqual(frame["left_hip_x_px"], 0.57 * IMAGE_W)
        self.assertAlmostEqual(frame["right_hip_y_px"], 0.81 * IMAGE_H)
        # Elbows (13/14) and nose (0) are never used as F1 inputs.
        for value in frame.values():
            self.assertNotIn(value, (0.70 * IMAGE_W, 0.30 * IMAGE_W, 0.51 * IMAGE_W))

    def test_hand_computed_f1_values(self):
        pose = live_pose_result(i12=pose_landmark(0.40, 0.42))
        result = live_f1(pose=pose).result
        sx, sy = (768 + 512) / 2, (288 + 302.4) / 2
        hx, hy = (768 + 563.2) / 2, (576 + 590.4) / 2
        d_sh = math.hypot(512 - 768, 302.4 - 288)
        self.assertAlmostEqual(result.features["fs_x"], (650 - sx) / d_sh)
        self.assertAlmostEqual(result.features["fs_y"], (140 - sy) / d_sh)
        self.assertAlmostEqual(result.features["sh_x"], (sx - hx) / d_sh)
        self.assertAlmostEqual(result.features["sh_y"], (sy - hy) / d_sh)
        self.assertAlmostEqual(
            result.features["so_beta"], math.atan2(14.4, -256) - math.pi
        )
        self.assertEqual(dict(result.family_available), {
            "FS": True, "SH": True, "SO": True,
        })

    def test_largest_face_bbox_is_selected_first_on_ties(self):
        small = face_detection(0, 0, 10, 10)
        large = face_detection(100, 50, 60, 80)
        tied = face_detection(400, 50, 80, 60)
        self.assertIs(probe.largest_face_detection(
            face_detector_result(small, large, tied)
        ), large)
        frame = live_f1(face_detector_result(small, large, tied)).frame
        self.assertEqual((frame["face_x"], frame["face_y"]), (130.0, 90.0))
        self.assertIsNone(probe.largest_face_detection(face_detector_result()))
        self.assertIsNone(probe.largest_face_detection(None))

    def test_face_is_detector_bbox_centre_not_landmarker_or_nose(self):
        frame = live_f1().frame
        nose_x = 0.51 * IMAGE_W
        landmarker_centre = (0.5 * IMAGE_W, 0.5 * IMAGE_H)
        self.assertEqual((frame["face_x"], frame["face_y"]), (650.0, 140.0))
        self.assertNotEqual(frame["face_x"], nose_x)
        self.assertNotEqual((frame["face_x"], frame["face_y"]), landmarker_centre)
        # A FaceLandmarker result cannot be passed as F: it has no detections.
        landmarker_like = face_result(faces=[face_landmarks()])
        frame = live_f1(detector=landmarker_like).frame
        self.assertFalse(frame["face_detected"])
        self.assertIsNone(frame["face_x"])

    def test_missing_face_keeps_sh_and_so(self):
        result = live_f1(detector=face_detector_result()).result
        self.assertIsNone(result.features["fs_x"])
        self.assertIsNone(result.features["fs_y"])
        self.assertEqual(result.family_reasons["FS"], ("face_detected:false",))
        self.assertTrue(result.family_available["SH"])
        self.assertTrue(result.family_available["SO"])
        self.assertIsNotNone(result.features["sh_y"])
        self.assertIsNotNone(result.features["so_beta"])

    def test_missing_hip_keeps_fs_and_so(self):
        pose = live_pose_result(i24=pose_landmark(0.44, 1.02))
        live = live_f1(pose=pose)
        self.assertFalse(live.frame["right_hip_valid"])
        self.assertIsNone(live.frame["right_hip_x_px"])
        self.assertIsNone(live.frame["right_hip_y_px"])
        self.assertIsNone(live.result.features["sh_x"])
        self.assertIsNone(live.result.features["sh_y"])
        self.assertEqual(
            live.result.family_reasons["SH"], ("right_hip_valid:false",)
        )
        self.assertTrue(live.result.family_available["FS"])
        self.assertTrue(live.result.family_available["SO"])

    def test_out_of_frame_hip_is_invalid_without_clamping(self):
        cases = {
            "x at 1.0": (1.0, 0.8, False),
            "negative y": (0.6, -0.01, False),
            "nan": (math.nan, 0.8, False),
            "infinite": (0.6, math.inf, False),
            "zero edge": (0.0, 0.0, True),
            "just inside": (0.999, 0.999, True),
        }
        for name, (x, y, valid) in cases.items():
            with self.subTest(name=name):
                frame = live_f1(
                    pose=live_pose_result(i23=pose_landmark(x, y))
                ).frame
                self.assertIs(frame["left_hip_valid"], valid)
                if valid:
                    self.assertAlmostEqual(frame["left_hip_x_px"], x * IMAGE_W)
                    self.assertAlmostEqual(frame["left_hip_y_px"], y * IMAGE_H)
                else:
                    self.assertIsNone(frame["left_hip_x_px"])
                    self.assertIsNone(frame["left_hip_y_px"])

    def test_low_visibility_hip_is_not_thresholded(self):
        pose = live_pose_result(i23=pose_landmark(0.6, 0.8, visibility=0.01, presence=0.02))
        live = live_f1(pose=pose)
        self.assertTrue(live.frame["left_hip_valid"])
        self.assertTrue(live.result.family_available["SH"])
        self.assertEqual(live.hip_diagnostics["left"]["visibility"], 0.01)
        self.assertEqual(live.hip_diagnostics["left"]["presence"], 0.02)
        self.assertNotIn("left_hip_visibility", live.frame)

    def test_invalid_shoulder_flag_wins_over_numeric_coordinates(self):
        pose = live_pose_result(i11=pose_landmark(1.05, 0.40))
        live = live_f1(pose=pose)
        self.assertFalse(live.frame["lsh_valid"])
        # Canonical legacy numeric prefix is retained, but never trusted.
        self.assertAlmostEqual(live.frame["lsh_x"], 1.05 * IMAGE_W)
        self.assertTrue(all(
            value is None for value in live.result.features.values()
        ))
        for family in ("FS", "SH", "SO"):
            self.assertFalse(live.result.family_available[family])
            self.assertIn("lsh_valid:false", live.result.family_reasons[family])

    def test_no_pose_marks_all_body_observations_invalid(self):
        live = live_f1(pose=types.SimpleNamespace(pose_landmarks=[]))
        for field in ("lsh_valid", "rsh_valid", "left_hip_valid", "right_hip_valid"):
            self.assertIs(live.frame[field], False)
        for field in ("lsh_x", "rsh_y", "left_hip_x_px", "right_hip_y_px"):
            self.assertIsNone(live.frame[field])
        self.assertTrue(all(
            value is None for value in live.result.features.values()
        ))
        self.assertFalse(live.hip_diagnostics["left"]["landmark_present"])

    def test_zero_shoulder_width_is_unavailable_not_zero(self):
        pose = live_pose_result(
            i11=pose_landmark(0.5, 0.4), i12=pose_landmark(0.5, 0.4)
        )
        result = live_f1(pose=pose).result
        self.assertTrue(all(value is None for value in result.features.values()))
        for family in ("FS", "SH", "SO"):
            self.assertIn("d_sh:zero", result.family_reasons[family])

    def test_no_baseline_each_frame_is_independent(self):
        upright = live_pose_result()
        shifted = live_pose_result(
            i11=pose_landmark(0.66, 0.45), i12=pose_landmark(0.46, 0.47)
        )
        alone = live_f1(pose=shifted).result
        live_f1(pose=upright)
        live_f1(pose=upright)
        after_history = live_f1(pose=shifted).result
        self.assertEqual(dict(after_history.features), dict(alone.features))
        self.assertEqual(
            dict(after_history.family_reasons), dict(alone.family_reasons)
        )
        # The F1 input carries only the current frame's raw observations.
        self.assertEqual(tuple(live_f1().frame), probe.F1_INPUT_FIELDS)
        # No calibration key: 'b' is not a probe control.
        self.assertEqual(probe.handle_panel_key(ord("b"), "summary", 0), (False, 0))

    def test_f1_reuses_formula_from_f1_features(self):
        sentinel = object()
        with mock.patch.object(
            probe.f1_features, "compute_f1_5_frame", return_value=sentinel
        ) as compute:
            live = live_f1()
        compute.assert_called_once()
        self.assertEqual(dict(compute.call_args.args[0]), dict(live.frame))
        self.assertIs(live.result, sentinel)


class LiveF1DisplayTests(unittest.TestCase):
    def test_panel_shows_values_banners_and_hip_state(self):
        texts = f1_panel_texts(live_f1())
        self.assertEqual(texts[0], "F1-5 LIVE — FEAT-009")
        self.assertIn("CALIBRATION-FREE F1-5 — ENGINEERING ONLY", texts)
        self.assertIn("NO POSTURE CLASSIFICATION", texts)
        for label in ("fs_x: ", "fs_y: ", "sh_x: ", "sh_y: ", "so_beta (rad): "):
            self.assertTrue(any(text.startswith(label) for text in texts), label)
        self.assertIn("fs_x: +0.039", texts)
        self.assertIn("FS status: AVAILABLE", texts)
        self.assertIn("SH status: AVAILABLE", texts)
        self.assertIn("SO status: AVAILABLE", texts)
        self.assertIn("Left Hip: IN | vis 0.90 | pres 0.95", texts)
        self.assertIn("Right Hip: IN | vis 0.90 | pres 0.95", texts)
        self.assertIn(probe.F1_HIP_DIAGNOSTIC_NOTE, texts)

    def test_missing_values_render_na_with_family_reason(self):
        pose = live_pose_result(i23=pose_landmark(0.6, 1.2))
        texts = f1_panel_texts(live_f1(face_detector_result(), pose))
        for name in ("fs_x", "fs_y", "sh_x", "sh_y"):
            self.assertIn(f"{name}: N/A", texts)
            self.assertNotIn(f"{name}: +0.000", texts)
        # Horizontal synthetic shoulders: a genuine zero is a value, not N/A.
        self.assertIn("so_beta (rad): +0.000", texts)
        self.assertIn("FS status: N/A — face_detected:false", texts)
        self.assertIn("SH status: N/A — left_hip_valid:false", texts)
        self.assertIn("SO status: AVAILABLE", texts)
        self.assertIn("Left Hip: OUT | vis 0.90 | pres 0.95", texts)

    def test_all_unavailable_still_shows_banners_and_no_zero(self):
        texts = f1_panel_texts(live_f1(
            face_detector_result(), types.SimpleNamespace(pose_landmarks=[])
        ))
        self.assertIn("CALIBRATION-FREE F1-5 — ENGINEERING ONLY", texts)
        self.assertIn("NO POSTURE CLASSIFICATION", texts)
        self.assertIn("so_beta (rad): N/A", texts)
        self.assertIn("Left Hip: OUT (no landmark) | vis N/A | pres N/A", texts)
        self.assertFalse(any("0.000" in text for text in texts))

    def test_no_posture_class_names_are_displayed(self):
        texts = " | ".join(f1_panel_texts(live_f1())).lower()
        for label in ("upright", "forward head", "body forward", "body_forward"):
            self.assertNotIn(label, texts)

    def test_f1_strip_is_appended_without_changing_existing_display(self):
        image = np.zeros((IMAGE_H, IMAGE_W, 3), dtype=np.uint8)
        kwargs = dict(
            pose_detected=True,
            face_detected=True,
            face_matrix=np.eye(4),
            face_matrix_values=valid_matrix_values(),
        )
        for mode in ("summary", "debug"):
            with self.subTest(mode=mode):
                base = probe.draw_engineering_panel(
                    image, readable_summary_result(), panel_mode=mode, **kwargs
                )
                with_f1 = probe.draw_engineering_panel(
                    image, readable_summary_result(), panel_mode=mode,
                    live_f1=live_f1(), **kwargs
                )
                self.assertEqual(base.shape, (760, 1911, 3))
                self.assertEqual(
                    with_f1.shape, (760 + probe.F1_PANEL_HEIGHT, 1911, 3)
                )
                np.testing.assert_array_equal(with_f1[:760], base)

    def test_f1_layout_fits_korean_font_without_overlap(self):
        from PIL import Image, ImageDraw

        fonts = probe._load_korean_fonts()
        self.assertIsNotNone(fonts)
        worst = live_f1(face_detector_result(), types.SimpleNamespace(pose_landmarks=[]))
        draw = ImageDraw.Draw(Image.new("RGB", (1911, probe.F1_PANEL_HEIGHT)))
        for live in (live_f1(), worst):
            boxes = []
            for text, x, y, font_key, _, anchor in probe.f1_panel_layout_items(live, 1911):
                box = draw.textbbox((x, y), text, font=fonts[font_key], anchor=anchor)
                self.assertGreaterEqual(box[0], 0, msg=text)
                self.assertGreaterEqual(box[1], 0, msg=text)
                self.assertLessEqual(box[2], 1911, msg=text)
                self.assertLessEqual(box[3], probe.F1_PANEL_HEIGHT, msg=text)
                boxes.append((box, text))
            for index, (first, first_text) in enumerate(boxes):
                for second, second_text in boxes[index + 1:]:
                    overlap = (
                        first[0] < second[2] and second[0] < first[2]
                        and first[1] < second[3] and second[1] < first[3]
                    )
                    self.assertFalse(overlap, msg=f"{first_text!r} / {second_text!r}")

    def test_f1_strip_falls_back_to_ascii_without_korean_font(self):
        import cv2

        with mock.patch.object(probe, "_load_korean_fonts", return_value=None), \
                mock.patch.object(probe, "_FONT_WARNING_EMITTED", True), \
                mock.patch.object(cv2, "putText", wraps=cv2.putText) as put_text:
            panel = probe.draw_f1_live_panel(live_f1(), 1911)
        self.assertEqual(panel.shape, (probe.F1_PANEL_HEIGHT, 1911, 3))
        drawn = [call.args[1] for call in put_text.call_args_list]
        self.assertIn("F1-5 LIVE - FEAT-009", drawn)
        self.assertTrue(all(text.isascii() for text in drawn))

    def test_f1_values_never_enter_existing_csv_headers(self):
        for name in (*probe.F1_INPUT_FIELDS, *probe.f1_features.F1_5_FEATURE_NAMES):
            self.assertNotIn(name, probe.CSV_FIELDS)
            self.assertNotIn(name, probe.FACE_DIAGNOSTIC_FIELDS)


class LiveF1LoopTests(unittest.TestCase):
    def test_default_off_creates_no_face_detector_and_keeps_display(self):
        loop = FakeLiveLoop().run()
        self.assertEqual(loop.detector_create_count, 0)
        self.assertNotIn("face", [kind for kind, _ in loop.options])
        self.assertEqual(loop.live_results, [])
        self.assertEqual(loop.main_window_shapes(), [(760, 1911, 3)])
        self.assertEqual(len(loop.pose.video_calls), 1)
        self.assertEqual(loop.created_files, [])

    def test_f1_live_reuses_pose_result_and_same_rgb_image(self):
        loop = FakeLiveLoop(frame_count=3).run(f1_live=True)
        self.assertEqual(loop.detector_create_count, 1)
        self.assertEqual(len(loop.pose.video_calls), 3)
        self.assertEqual(len(loop.face_landmarker.video_calls), 3)
        self.assertEqual(len(loop.face_detector.image_calls), 3)
        for frame in range(3):
            pose_image = loop.pose.video_calls[frame][0]
            self.assertIs(loop.face_detector.image_calls[frame], pose_image)
            self.assertIs(loop.face_landmarker.video_calls[frame][0], pose_image)
        self.assertEqual(len(loop.live_results), 3)
        frame = loop.live_results[0].frame
        self.assertEqual((frame["face_x"], frame["face_y"]), (650.0, 140.0))
        self.assertEqual(
            loop.main_window_shapes(),
            [(760 + probe.F1_PANEL_HEIGHT, 1911, 3)] * 3,
        )
        self.assertEqual(loop.created_files, [])

    def test_face_detector_uses_locked_model_and_canonical_options(self):
        import analyze_d455

        loop = FakeLiveLoop().run(f1_live=True)
        face_options = [kwargs for kind, kwargs in loop.options if kind == "face"]
        self.assertEqual(face_options, [{
            "base_options": {"model_asset_path": "face-model"},
            "min_detection_confidence": analyze_d455.FACE_MIN_DETECTION_CONFIDENCE,
        }])
        self.assertEqual(loop.face_detector.video_calls, [])

    def test_f1_live_coexists_with_3d_views_and_csv(self):
        loop = FakeLiveLoop().run(
            csv_path="engineering.csv", show_3d_views="side", f1_live=True
        )
        names = [name for name, _ in loop.shown]
        self.assertIn(probe.WINDOW_NAME, names)
        self.assertIn(probe.viewer.WINDOW_NAME, names)
        self.assertEqual(loop.created_files, ["engineering.csv"])

    def test_csv_header_is_unchanged_with_f1_live(self):
        previous_cwd = os.getcwd()
        loop = FakeLiveLoop()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "engineering.csv")
            loop.run(csv_path=path, f1_live=True)
            with open(path, encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames), probe.CSV_FIELDS)
            self.assertEqual(len(rows), 1)
        self.assertEqual(os.getcwd(), previous_cwd)

    def test_face_detector_closed_when_loop_raises(self):
        loop = FakeLiveLoop(loop_error=RuntimeError("live loop failure"))
        with self.assertRaisesRegex(RuntimeError, "live loop failure"):
            loop.run(f1_live=True)
        self.assertEqual(loop.face_detector.close_count, 1)
        self.assertEqual(loop.pose.close_count, 1)
        self.assertEqual(loop.face_landmarker.close_count, 1)
        loop.pipeline.stop.assert_called_once()

    def test_face_detector_closed_on_normal_exit(self):
        loop = FakeLiveLoop().run(f1_live=True)
        self.assertEqual(loop.face_detector.close_count, 1)


# ------------------------------------------------- live F1-5 RF engineering demo
# Synthetic artifacts/frames verify software behavior only; they are not
# evidence of posture-classification accuracy.
import json
from pathlib import Path

import f1_demo_rf
import test_f1_demo_rf as demo_fixtures
import train_f1_demo_rf


class StubDemoModel:
    """Stands in for F1DemoRFModel; records exactly what it is asked."""

    def __init__(self, label="upright", *, error=None):
        self.label = label
        self.error = error
        self.calls = []

    def predict(self, features):
        self.calls.append(features)
        if self.error is not None:
            raise self.error
        return f1_demo_rf.F1DemoPrediction(
            f1_demo_rf.PREDICTION_AVAILABLE, self.label, "model prediction"
        )


def stub_state(model):
    return probe.RFDemoModelState(
        probe.RF_MODEL_LOADED, model, "stub.json", "verified at startup"
    )


def rf_panel_texts(rf_demo, width=1911):
    return [item[0] for item in probe.rf_demo_panel_layout_items(rf_demo, width)]


class SequencePoseTask(FakeTask):
    """Returns a different synthetic Pose result for each successive frame."""

    def __init__(self, results):
        super().__init__(results[0])
        self.results = list(results)

    def detect_for_video(self, image, timestamp_ms):
        self.result = self.results[len(self.video_calls)]
        return super().detect_for_video(image, timestamp_ms)


class RFDemoArtifactCase(unittest.TestCase):
    """Trains one tiny synthetic artifact with the real demo trainer."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        csv_path = cls.root / "synthetic_frames.csv"
        demo_fixtures.write_canonical_csv(csv_path, demo_fixtures.synthetic_rows())
        cls.model_path = cls.root / "f1_demo_rf.json"
        cls.document = train_f1_demo_rf.train_f1_demo_rf(
            [csv_path], cls.model_path, n_estimators=7, max_features=5,
            random_seed=3,
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def write_document(self, name, document, *, resign=True):
        document = json.loads(json.dumps(document))
        if resign:
            signed = {
                "artifact_format": document["artifact_format"],
                "payload": document["payload"],
            }
            document["integrity"]["sha256"] = f1_demo_rf.artifact_integrity_sha256(signed)
        path = self.root / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path


class RFDemoCliTests(unittest.TestCase):
    def test_cli_default_is_unchanged(self):
        args = probe.parse_args([])
        self.assertIsNone(args.rf_demo_model)
        self.assertFalse(args.f1_live)
        with mock.patch.object(probe, "run_probe") as run_probe:
            self.assertEqual(probe.main([]), 0)
        run_probe.assert_called_once_with(
            None,
            face_diag_csv_path=None,
            show_3d_views=None,
            panel_mode="summary",
            pyvista_view=False,
            pyvista_anchor="shoulder",
            f1_live=False,
            rf_demo_model_path=None,
        )

    def test_f1_live_alone_is_unchanged(self):
        self.assertIsNone(probe.parse_args(["--f1-live"]).rf_demo_model)
        texts = f1_panel_texts(live_f1())
        self.assertEqual(texts[1:3], list(probe.F1_LIVE_BANNERS))
        self.assertIn("NO POSTURE CLASSIFICATION", texts)
        image = np.zeros((IMAGE_H, IMAGE_W, 3), dtype=np.uint8)
        display = probe.draw_engineering_panel(
            image, readable_summary_result(), True, face_detected=True,
            face_matrix=np.eye(4), face_matrix_values=valid_matrix_values(),
            live_f1=live_f1(),
        )
        self.assertEqual(display.shape, (760 + probe.F1_PANEL_HEIGHT, 1911, 3))
        with mock.patch.object(probe.f1_demo_rf, "load_f1_demo_model") as load:
            loop = FakeLiveLoop().run(f1_live=True)
        load.assert_not_called()
        self.assertEqual(
            loop.main_window_shapes(), [(760 + probe.F1_PANEL_HEIGHT, 1911, 3)]
        )

    def test_rf_demo_requires_f1_live(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            probe.parse_args(["--rf-demo-model", "model.json"])
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            probe.parse_args(["--views", "side", "--rf-demo-model", "model.json"])
        with self.assertRaisesRegex(ValueError, "requires f1_live"):
            probe.run_probe(rf_demo_model_path="model.json")

    def test_rf_demo_path_is_forwarded_with_existing_options(self):
        argv = ["--views", "side", "--f1-live", "--rf-demo-model", "m.json"]
        args = probe.parse_args(argv)
        self.assertEqual(args.rf_demo_model, "m.json")
        self.assertTrue(args.f1_live)
        self.assertEqual(args.views, "side")
        with mock.patch.object(probe, "run_probe") as run_probe:
            self.assertEqual(probe.main(argv), 0)
        run_probe.assert_called_once_with(
            None,
            face_diag_csv_path=None,
            show_3d_views="side",
            panel_mode="summary",
            pyvista_view=False,
            pyvista_anchor="shoulder",
            f1_live=True,
            rf_demo_model_path="m.json",
        )
        args = probe.parse_args(
            ["--pyvista", "--pyvista-anchor", "camera", *argv]
        )
        self.assertEqual(args.pyvista_anchor, "camera")
        self.assertEqual(args.views, "side")


class RFDemoModelTests(RFDemoArtifactCase):
    def test_valid_artifact_loads_once_into_verified_model(self):
        with mock.patch.object(
            probe.f1_demo_rf, "load_f1_demo_model",
            wraps=probe.f1_demo_rf.load_f1_demo_model,
        ) as load:
            state = probe.load_rf_demo_model(self.model_path)
        load.assert_called_once_with(self.model_path)
        self.assertEqual(state.status, probe.RF_MODEL_LOADED)
        self.assertIsInstance(state.model, f1_demo_rf.F1DemoRFModel)
        self.assertEqual(state.artifact_name, "f1_demo_rf.json")
        self.assertEqual(
            state.model.metadata, self.document["payload"]["metadata"]
        )

    def test_missing_artifact_fails_closed(self):
        state = probe.load_rf_demo_model(self.root / "absent.json")
        self.assertEqual(state.status, probe.RF_MODEL_NOT_LOADED)
        self.assertIsNone(state.model)
        frame = probe.rf_demo_frame(state, live_f1())
        self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
        self.assertIsNone(frame.label)
        self.assertTrue(frame.reason.startswith("MODEL NOT LOADED:"))
        self.assertIn("Model: NOT LOADED | absent.json", rf_panel_texts(frame))

    def test_invalid_artifacts_fail_closed(self):
        corrupt = self.root / "corrupt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        tampered = json.loads(json.dumps(self.document))
        tampered["payload"]["metadata"]["class_labels"][0] = "lean_back"
        wrong_order = json.loads(json.dumps(self.document))
        wrong_order["payload"]["metadata"]["feature_names"][0:2] = ["fs_y", "fs_x"]
        wrong_format = json.loads(json.dumps(self.document))
        wrong_format["artifact_format"] = "aiot-f1-demo-rf/9.9.9"
        cases = {
            "corrupt json": (corrupt, "could not read"),
            "integrity": (self.write_document("tampered.json", tampered, resign=False), "integrity"),
            "feature order": (self.write_document("wrong_order.json", wrong_order), "feature_names"),
            "format": (self.write_document("wrong_format.json", wrong_format), "artifact format"),
            "directory": (self.root, ""),
        }
        for name, (path, detail) in cases.items():
            with self.subTest(name=name):
                state = probe.load_rf_demo_model(path)
                self.assertEqual(state.status, probe.RF_MODEL_INVALID)
                self.assertIsNone(state.model)
                self.assertIn(detail, state.detail)
                frame = probe.rf_demo_frame(state, live_f1())
                self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
                self.assertIsNone(frame.label)
                self.assertTrue(frame.reason.startswith("MODEL INVALID:"))

    def test_displayed_label_is_the_actual_model_output(self):
        state = probe.load_rf_demo_model(self.model_path)
        live = live_f1()
        expected = state.model.predict(live.result)
        self.assertEqual(expected.status, f1_demo_rf.PREDICTION_AVAILABLE)
        frame = probe.rf_demo_frame(state, live)
        self.assertEqual(frame.label, expected.label)
        self.assertEqual(frame.prediction, probe.RF_DISPLAY_LABELS[expected.label])
        self.assertEqual(frame.model_status, probe.RF_MODEL_LOADED)

    def test_display_labels_cover_exactly_the_demo_classes(self):
        self.assertEqual(tuple(probe.RF_DISPLAY_LABELS), f1_demo_rf.CLASS_LABELS)
        self.assertEqual(
            tuple(probe.RF_DISPLAY_LABELS.values()),
            ("UPRIGHT", "FORWARD HEAD", "BODY FORWARD"),
        )

    def test_three_supported_labels_are_displayed(self):
        for label, display in probe.RF_DISPLAY_LABELS.items():
            with self.subTest(label=label):
                model = StubDemoModel(label)
                frame = probe.rf_demo_frame(stub_state(model), live_f1())
                self.assertEqual(frame.prediction, display)
                self.assertEqual(frame.label, label)
                self.assertIn(f"Prediction: {display}", rf_panel_texts(frame))

    def test_unsupported_or_failing_model_output_is_never_shown_as_label(self):
        for model in (
            StubDemoModel("lean_back"),
            StubDemoModel(None),
            StubDemoModel(error=RuntimeError("boom")),
        ):
            with self.subTest(label=model.label, error=model.error):
                frame = probe.rf_demo_frame(stub_state(model), live_f1())
                self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
                self.assertIsNone(frame.label)

    def test_missing_hip_makes_prediction_unavailable(self):
        state = probe.load_rf_demo_model(self.model_path)
        live = live_f1(pose=live_pose_result(i24=pose_landmark(0.44, 1.02)))
        frame = probe.rf_demo_frame(state, live)
        self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
        self.assertIsNone(frame.label)
        self.assertEqual(frame.reason, "missing sh_x, sh_y (right_hip_valid:false)")
        self.assertEqual(frame.model_status, probe.RF_MODEL_LOADED)

    def test_missing_face_makes_prediction_unavailable(self):
        state = probe.load_rf_demo_model(self.model_path)
        frame = probe.rf_demo_frame(state, live_f1(detector=face_detector_result()))
        self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
        self.assertIsNone(frame.label)
        self.assertEqual(frame.reason, "missing fs_x, fs_y (face_detected:false)")

    def test_no_stale_prediction_after_incomplete_frame(self):
        state = probe.load_rf_demo_model(self.model_path)
        complete = probe.rf_demo_frame(state, live_f1())
        self.assertIsNotNone(complete.label)
        for live in (
            live_f1(detector=face_detector_result()),
            live_f1(pose=types.SimpleNamespace(pose_landmarks=[])),
        ):
            frame = probe.rf_demo_frame(state, live)
            self.assertIsNone(frame.label)
            self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
            self.assertNotIn(complete.prediction, " ".join(rf_panel_texts(frame)))
        self.assertEqual(probe.rf_demo_frame(state, live_f1()), complete)

    def test_no_baseline_calibration_or_frame_history(self):
        model = StubDemoModel("forward_head")
        state = stub_state(model)
        upright = live_f1()
        shifted = live_f1(pose=live_pose_result(
            i11=pose_landmark(0.66, 0.45), i12=pose_landmark(0.46, 0.47)
        ))
        for live in (upright, shifted, upright):
            probe.rf_demo_frame(state, live)
        # Each call passes exactly that frame's own F1-5 result, nothing else.
        self.assertEqual(
            [id(call) for call in model.calls],
            [id(upright.result), id(shifted.result), id(upright.result)],
        )
        real = probe.load_rf_demo_model(self.model_path)
        alone = probe.rf_demo_frame(real, shifted)
        probe.rf_demo_frame(real, upright)
        self.assertEqual(probe.rf_demo_frame(real, shifted), alone)
        metadata = json.dumps(self.document["payload"]["metadata"]).lower()
        self.assertNotIn("baseline", metadata)
        self.assertNotIn("calibration", metadata)

    def test_rf_demo_is_separate_from_research_classifier(self):
        import posture_prediction

        self.assertNotEqual(f1_demo_rf.CLASS_LABELS, posture_prediction.LAB5_LABELS)
        self.assertIn(
            "not approved research M0/M1/M2",
            self.document["payload"]["metadata"]["training"]["purpose"],
        )


class RFDemoDisplayTests(unittest.TestCase):
    def frame(self, label="upright"):
        return probe.rf_demo_frame(stub_state(StubDemoModel(label)), live_f1())

    def test_rf_panel_shows_unvalidated_banners_state_and_prediction(self):
        texts = rf_panel_texts(self.frame("body_forward"))
        self.assertEqual(texts[0], "RF POSTURE DEMO — UNVALIDATED")
        self.assertIn("ENGINEERING RF DEMO — ACCURACY NOT VALIDATED", texts)
        self.assertIn(probe.RF_DEMO_BANNERS[1], texts)
        self.assertIn("Model: LOADED | stub.json", texts)
        self.assertIn("Prediction: BODY FORWARD", texts)
        self.assertIn(f"Reason: {probe.RF_AVAILABLE_REASON}", texts)

    def test_f1_strip_states_rf_mode_without_changing_its_values(self):
        live = live_f1()
        plain = probe.f1_panel_layout_items(live, 1911)
        rf_mode = probe.f1_panel_layout_items(live, 1911, rf_demo_enabled=True)
        self.assertEqual(len(plain), len(rf_mode))
        differing = [(a, b) for a, b in zip(plain, rf_mode) if a != b]
        self.assertEqual(len(differing), 1)
        self.assertEqual(differing[0][0][0], "NO POSTURE CLASSIFICATION")
        self.assertEqual(differing[0][1][0], probe.F1_LIVE_RF_DEMO_BANNERS[1])
        self.assertEqual(differing[0][0][1:], differing[0][1][1:])

    def test_rf_strip_is_appended_without_changing_existing_display(self):
        image = np.zeros((IMAGE_H, IMAGE_W, 3), dtype=np.uint8)
        kwargs = dict(
            pose_detected=True, face_detected=True, face_matrix=np.eye(4),
            face_matrix_values=valid_matrix_values(),
        )
        live = live_f1()
        for mode in ("summary", "debug"):
            with self.subTest(mode=mode):
                base = probe.draw_engineering_panel(
                    image, readable_summary_result(), panel_mode=mode, **kwargs
                )
                with_rf = probe.draw_engineering_panel(
                    image, readable_summary_result(), panel_mode=mode,
                    live_f1=live, rf_demo=self.frame(), **kwargs
                )
                self.assertEqual(with_rf.shape, (
                    760 + probe.F1_PANEL_HEIGHT + probe.RF_DEMO_PANEL_HEIGHT,
                    1911, 3,
                ))
                np.testing.assert_array_equal(with_rf[:760], base)
                np.testing.assert_array_equal(
                    with_rf[760:760 + probe.F1_PANEL_HEIGHT],
                    probe.draw_f1_live_panel(live, 1911, rf_demo_enabled=True),
                )

    def test_rf_layout_fits_korean_font_without_overlap(self):
        from PIL import Image, ImageDraw

        fonts = probe._load_korean_fonts()
        self.assertIsNotNone(fonts)
        long_state = probe.RFDemoModelState(
            probe.RF_MODEL_INVALID, None, "x" * 200 + ".json", "W" * 400
        )
        frames = (
            self.frame("forward_head"),
            probe.rf_demo_frame(long_state, live_f1()),
            probe.rf_demo_frame(stub_state(StubDemoModel()), live_f1(
                face_detector_result(), types.SimpleNamespace(pose_landmarks=[])
            )),
        )
        height = probe.RF_DEMO_PANEL_HEIGHT
        draw = ImageDraw.Draw(Image.new("RGB", (1911, height)))
        for frame in frames:
            boxes = []
            for text, x, y, font_key, _, anchor in probe.rf_demo_panel_layout_items(frame, 1911):
                box = draw.textbbox((x, y), text, font=fonts[font_key], anchor=anchor)
                self.assertGreaterEqual(box[0], 0, msg=text)
                self.assertGreaterEqual(box[1], 0, msg=text)
                self.assertLessEqual(box[2], 1911, msg=text)
                self.assertLessEqual(box[3], height, msg=text)
                boxes.append((box, text))
            for index, (first, first_text) in enumerate(boxes):
                for second, second_text in boxes[index + 1:]:
                    overlap = (
                        first[0] < second[2] and second[0] < first[2]
                        and first[1] < second[3] and second[1] < first[3]
                    )
                    self.assertFalse(overlap, msg=f"{first_text!r} / {second_text!r}")

    def test_rf_strip_falls_back_to_ascii_without_korean_font(self):
        import cv2

        with mock.patch.object(probe, "_load_korean_fonts", return_value=None), \
                mock.patch.object(probe, "_FONT_WARNING_EMITTED", True), \
                mock.patch.object(cv2, "putText", wraps=cv2.putText) as put_text:
            panel = probe.draw_rf_demo_panel(self.frame(), 1911)
        self.assertEqual(panel.shape, (probe.RF_DEMO_PANEL_HEIGHT, 1911, 3))
        drawn = [call.args[1] for call in put_text.call_args_list]
        self.assertIn("RF POSTURE DEMO - UNVALIDATED", drawn)
        self.assertIn("ENGINEERING RF DEMO - ACCURACY NOT VALIDATED", drawn)
        self.assertTrue(all(text.isascii() for text in drawn))

    def test_rf_values_never_enter_existing_csv_headers(self):
        for name in ("prediction", "label", "rf_demo", "model_status", *f1_demo_rf.CLASS_LABELS):
            self.assertNotIn(name, probe.CSV_FIELDS)
            self.assertNotIn(name, probe.FACE_DIAGNOSTIC_FIELDS)


class RFDemoLoopTests(RFDemoArtifactCase):
    def run_rf(self, loop=None, **kwargs):
        loop = loop or FakeLiveLoop()
        kwargs.setdefault("f1_live", True)
        kwargs.setdefault("rf_demo_model_path", str(self.model_path))
        with mock.patch.object(
            probe, "draw_engineering_panel", wraps=probe.draw_engineering_panel
        ) as draw:
            loop.run(**kwargs)
        loop.rf_frames = [call.kwargs["rf_demo"] for call in draw.call_args_list]
        return loop

    def test_model_is_loaded_once_and_reused_across_frames(self):
        original_predict = f1_demo_rf.F1DemoRFModel.predict
        with mock.patch.object(
            probe.f1_demo_rf, "load_f1_demo_model",
            wraps=probe.f1_demo_rf.load_f1_demo_model,
        ) as load, mock.patch.object(
            probe.f1_demo_rf, "predict_f1_demo",
            side_effect=AssertionError("per-frame artifact reload"),
        ), mock.patch.object(
            f1_demo_rf.F1DemoRFModel, "predict", autospec=True,
            side_effect=original_predict,
        ) as predict:
            loop = self.run_rf(FakeLiveLoop(frame_count=3))
        load.assert_called_once_with(str(self.model_path))
        self.assertEqual(predict.call_count, 3)
        models = {id(call.args[0]) for call in predict.call_args_list}
        self.assertEqual(len(models), 1)
        self.assertEqual(
            [call.args[1] for call in predict.call_args_list],
            [live.result for live in loop.live_results],
        )
        self.assertEqual(loop.main_window_shapes(), [(
            760 + probe.F1_PANEL_HEIGHT + probe.RF_DEMO_PANEL_HEIGHT, 1911, 3,
        )] * 3)
        self.assertTrue(all(frame.label is not None for frame in loop.rf_frames))
        self.assertEqual(loop.created_files, [])

    def test_no_duplicate_mediapipe_inference(self):
        loop = self.run_rf(FakeLiveLoop(frame_count=3))
        self.assertEqual(loop.detector_create_count, 1)
        self.assertEqual(len(loop.pose.video_calls), 3)
        self.assertEqual(len(loop.face_landmarker.video_calls), 3)
        self.assertEqual(len(loop.face_detector.image_calls), 3)
        self.assertEqual(loop.face_detector.video_calls, [])
        self.assertEqual(len(loop.live_results), 3)
        self.assertEqual([kind for kind, _ in loop.options], ["pose", "mesh", "face"])

    def test_missing_or_invalid_artifact_runs_without_inventing_labels(self):
        corrupt = self.root / "loop_corrupt.json"
        corrupt.write_text("{}", encoding="utf-8")
        for path, status in (
            (self.root / "absent.json", probe.RF_MODEL_NOT_LOADED),
            (corrupt, probe.RF_MODEL_INVALID),
        ):
            with self.subTest(status=status):
                loop = self.run_rf(FakeLiveLoop(frame_count=2), rf_demo_model_path=str(path))
                self.assertEqual(len(loop.rf_frames), 2)
                for frame in loop.rf_frames:
                    self.assertEqual(frame.model_status, status)
                    self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)
                    self.assertIsNone(frame.label)
                self.assertEqual(loop.created_files, [])

    def test_no_stale_predictions_across_live_frames(self):
        loop = FakeLiveLoop(frame_count=4)
        loop.pose = SequencePoseTask([
            live_pose_result(),
            live_pose_result(i24=pose_landmark(0.44, 1.02)),
            types.SimpleNamespace(pose_landmarks=[]),
            live_pose_result(),
        ])
        self.run_rf(loop)
        labels = [frame.label for frame in loop.rf_frames]
        self.assertIsNotNone(labels[0])
        self.assertIsNone(labels[1])
        self.assertIsNone(labels[2])
        self.assertEqual(labels[3], labels[0])
        self.assertEqual(loop.rf_frames[1].reason, "missing sh_x, sh_y (right_hip_valid:false)")
        for frame in loop.rf_frames[1:3]:
            self.assertEqual(frame.prediction, probe.RF_PREDICTION_UNAVAILABLE)

    def test_existing_3d_viewers_are_unaffected(self):
        def run(**extra):
            fake_window = mock.Mock()
            fake_window.update.return_value = True
            with mock.patch.object(probe.pyvista_viewer, "require_pyvista") as require, \
                    mock.patch.object(
                        probe.pyvista_viewer, "PyVistaPostureViewer",
                        return_value=fake_window,
                    ) as viewer_class, \
                    mock.patch.object(
                        probe.viewer, "render_selected_views",
                        wraps=probe.viewer.render_selected_views,
                    ) as render:
                loop = FakeLiveLoop(frame_count=2)
                if "rf_demo_model_path" in extra:
                    self.run_rf(loop, **extra)
                else:
                    loop.run(**extra)
            require.assert_called_once()
            viewer_class.assert_called_once_with(anchor_mode="camera")
            fake_window.close.assert_called_once()
            return loop, fake_window, render

        common = dict(
            show_3d_views="side", pyvista_view=True, pyvista_anchor="camera",
            f1_live=True,
        )
        base, base_window, base_render = run(**common)
        rf, rf_window, rf_render = run(
            rf_demo_model_path=str(self.model_path), **common
        )
        shapes = lambda loop: [s for n, s in loop.shown if n == probe.viewer.WINDOW_NAME]
        self.assertEqual(shapes(rf), shapes(base))
        self.assertEqual(len(shapes(rf)), 2)
        self.assertEqual(
            [call.args[1] for call in rf_render.call_args_list], ["side", "side"]
        )
        self.assertEqual(rf_window.update.call_count, base_window.update.call_count)
        for (rf_call, base_call) in zip(
            rf_window.update.call_args_list, base_window.update.call_args_list
        ):
            self.assertEqual(rf_call.args[0].features, base_call.args[0].features)
            self.assertEqual(rf_call.args[1], base_call.args[1])

    def test_existing_csv_interfaces_unchanged_with_rf_demo(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            engineering = os.path.join(directory, "engineering.csv")
            face = os.path.join(directory, "face.csv")
            loop = self.run_rf(
                FakeLiveLoop(frame_count=2), csv_path=engineering,
                face_diag_csv_path=face,
            )
            with open(engineering, encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames), probe.CSV_FIELDS)
            self.assertEqual(len(rows), 2)
            with open(face, encoding="utf-8") as source:
                reader = csv.DictReader(source)
                face_rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames), probe.FACE_DIAGNOSTIC_FIELDS)
            self.assertEqual(len(face_rows), 2)
            self.assertEqual(sorted(os.listdir(directory)), ["engineering.csv", "face.csv"])
        self.assertEqual(loop.created_files, [])
        self.assertEqual(os.getcwd(), previous_cwd)

    def test_cleanup_preserved_when_loop_raises(self):
        loop = FakeLiveLoop(loop_error=RuntimeError("live loop failure"))
        with self.assertRaisesRegex(RuntimeError, "live loop failure"):
            self.run_rf(loop)
        self.assertEqual(loop.face_detector.close_count, 1)
        self.assertEqual(loop.pose.close_count, 1)
        self.assertEqual(loop.face_landmarker.close_count, 1)
        loop.pipeline.stop.assert_called_once()

    def test_cleanup_preserved_on_normal_exit(self):
        loop = self.run_rf(FakeLiveLoop(frame_count=2))
        self.assertEqual(loop.face_detector.close_count, 1)
        self.assertEqual(loop.pose.close_count, 1)
        self.assertEqual(loop.face_landmarker.close_count, 1)
        loop.pipeline.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
