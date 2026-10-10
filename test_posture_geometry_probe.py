import csv
import io
import math
import os
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
        )

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


if __name__ == "__main__":
    unittest.main()
