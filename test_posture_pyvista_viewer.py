import math
import os
import subprocess
import sys
import unittest
from unittest import mock

import numpy as np

import posture_3d_viewer as viewer
import posture_geometry as geometry
import posture_geometry_probe as probe
import posture_pyvista_viewer as pv_viewer

try:
    import pyvista  # noqa: F401
except ImportError:
    PYVISTA_AVAILABLE = False
else:
    PYVISTA_AVAILABLE = True


REPOSITORY = os.path.dirname(os.path.abspath(__file__))
FOCAL_PX = 600.0
HIP_MIDPOINT = (0.0, .25, .85)
NEUTRAL_3D = {
    "nose": (0.0, -.55, .76),
    "chin": (0.0, -.47, .78),
    "left_ear": (.08, -.56, .85),
    "right_ear": (-.08, -.56, .85),
    "left_shoulder": (.20, -.30, .85),
    "right_shoulder": (-.20, -.30, .85),
    "left_elbow": (.27, -.04, .82),
    "right_elbow": (-.27, -.04, .82),
    "left_wrist": (.25, .16, .70),
    "right_wrist": (-.25, .16, .70),
    "left_hip": (.15, .25, .85),
    "right_hip": (-.15, .25, .85),
}
HEAD_NAMES = ("nose", "chin", "left_ear", "right_ear")
SHOULDER_NAMES = ("left_shoulder", "right_shoulder")
HIP_NAMES = ("left_hip", "right_hip")


def posture_result(
    *,
    sagittal_lean_deg=0.0,
    lateral_lean_deg=0.0,
    head_shift_m=(0.0, 0.0, 0.0),
    shoulder_shift_m=(0.0, 0.0, 0.0),
    missing=(),
):
    """Synthetic RealSense-frame posture; structural test data only.

    Positive sagittal lean rotates everything above the hips toward the
    camera (-Z); positive lateral lean rotates it toward image-right (+X).
    """

    hip_x, hip_y, hip_z = HIP_MIDPOINT
    sagittal = math.radians(sagittal_lean_deg)
    lateral = math.radians(lateral_lean_deg)
    xyz = {}
    for name, (x, y, z) in NEUTRAL_3D.items():
        for names, shift_m in ((HEAD_NAMES, head_shift_m), (SHOULDER_NAMES, shoulder_shift_m)):
            if name in names:
                x, y, z = (
                    value + shift for value, shift in zip((x, y, z), shift_m)
                )
        if name not in HIP_NAMES:
            right, up, forward = x - hip_x, hip_y - y, hip_z - z
            forward, up = (
                forward * math.cos(sagittal) + up * math.sin(sagittal),
                -forward * math.sin(sagittal) + up * math.cos(sagittal),
            )
            right, up = (
                right * math.cos(lateral) + up * math.sin(lateral),
                -right * math.sin(lateral) + up * math.cos(lateral),
            )
            x, y, z = hip_x + right, hip_y - up, hip_z - forward
        xyz[name] = (x, y, z)
    points = {
        name: geometry.Point(640 + FOCAL_PX * x / z, 360 + FOCAL_PX * y / z, z)
        for name, (x, y, z) in xyz.items()
    }
    points_3d = {name: geometry.Point3D(*value) for name, value in xyz.items()}
    for name in missing:
        points_3d[name] = None
    return geometry.compute_candidate_geometry(
        points, focal_length_px=FOCAL_PX, points_3d=points_3d
    )


def matrix_values(pitch=0.0, yaw=0.0, roll=0.0):
    return {
        "face_matrix_valid": True,
        "face_matrix_pitch_deg": pitch,
        "face_matrix_yaw_deg": yaw,
        "face_matrix_roll_deg": roll,
    }


def mediapipe_rotation(axis, angle_deg):
    """Right-handed axis-angle rotation in MediaPipe face space."""

    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    skew = np.array(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))
    angle = math.radians(angle_deg)
    return np.eye(3) + math.sin(angle) * skew + (1 - math.cos(angle)) * skew @ skew


def screen(camera, vector):
    """Project a world vector onto (screen-right, screen-up)."""

    right, up = camera.screen_axes()
    vector = np.asarray(vector, dtype=float)
    return float(np.dot(vector, right)), float(np.dot(vector, up))


def offset(a, b):
    """Return b - a for two Point3D values."""

    return (b.x_m - a.x_m, b.y_m - a.y_m, b.z_m - a.z_m)


def press_key(window, key):
    """Send one real VTK key stroke (KeyPress then Char) to the viewer window."""

    interactor = window.plotter.iren.interactor
    interactor.SetKeyCode(key)
    interactor.SetKeySym(key)
    interactor.KeyPressEvent()
    interactor.CharEvent()
    interactor.KeyReleaseEvent()


class SceneTests(unittest.TestCase):
    def assert_point(self, point, expected):
        self.assertIsNotNone(point)
        np.testing.assert_allclose(
            (point.x_m, point.y_m, point.z_m), expected, atol=1e-12
        )

    def test_module_imports_without_pyvista(self):
        code = (
            "import sys; sys.modules['pyvista'] = None; "
            "import posture_pyvista_viewer as m; "
            "import posture_geometry_probe as p; "
            "print(m.build_scene(m.geometry.compute_candidate_geometry({})).head_source)"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=REPOSITORY, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), pv_viewer.HEAD_SOURCE_UNAVAILABLE)

    def test_missing_pyvista_raises_install_hint_only_when_window_is_requested(self):
        with mock.patch.dict(sys.modules, {"pyvista": None}):
            with self.assertRaisesRegex(RuntimeError, "requirements-viewer.txt"):
                pv_viewer.require_pyvista()
            with self.assertRaisesRegex(RuntimeError, "requirements-viewer.txt"):
                pv_viewer.PyVistaPostureViewer(off_screen=True)
            scene = pv_viewer.build_scene(posture_result(), matrix_values())
        self.assertIsNotNone(scene.primitives.torso)

    def test_view_cameras_match_unmirrored_front_and_existing_side_convention(self):
        anchor = geometry.Point3D(.1, -.3, .85)
        front = pv_viewer.front_camera(anchor)
        side = pv_viewer.side_camera(anchor)
        np.testing.assert_allclose(front.screen_axes(), ((1, 0, 0), (0, -1, 0)), atol=1e-12)
        np.testing.assert_allclose(side.screen_axes(), ((0, 0, 1), (0, -1, 0)), atol=1e-12)
        self.assertEqual(front.focal_point, (.1, -.3, .85))
        self.assertLess(front.position[2], anchor.z_m)
        # Same horizontal convention as the OpenCV side avatar: camera at left.
        near, far = geometry.Point3D(0, 0, .7), geometry.Point3D(0, 0, .9)
        self.assertLess(
            viewer.side_view_project(near)[0], viewer.side_view_project(far)[0]
        )
        self.assertLess(screen(side, offset(far, near))[0], 0.0)

    def test_neutral_front_scene_faces_camera_with_vertical_torso(self):
        result = posture_result()
        scene = pv_viewer.build_scene(result, matrix_values())
        self.assertEqual(scene.head_source, pv_viewer.HEAD_SOURCE_FACE_MATRIX)
        head = scene.primitives.head
        np.testing.assert_allclose(head.lateral_axis, (1, 0, 0), atol=1e-12)
        np.testing.assert_allclose(head.vertical_axis, (0, -1, 0), atol=1e-12)
        np.testing.assert_allclose(head.forward_axis, (0, 0, -1), atol=1e-12)
        front = pv_viewer.front_camera(scene.anchor)
        np.testing.assert_allclose(screen(front, head.forward_axis), (0, 0), atol=1e-12)
        torso = scene.primitives.torso
        torso_axis = offset(torso.hip_midpoint, torso.shoulder_midpoint)
        for camera in (front, pv_viewer.side_camera(scene.anchor)):
            horizontal, vertical = screen(camera, torso_axis)
            self.assertAlmostEqual(horizontal, 0.0, places=12)
            self.assertGreater(vertical, 0.0)
        self.assert_point(scene.anchor, (0.0, -.30, .85))
        self.assertAlmostEqual(result.features["sagittal_torso_lean_deg"], 0.0)

    def test_torso_forward_and_backward_lean_follow_feature_sign_in_side_view(self):
        for lean in (15.0, -15.0):
            with self.subTest(lean=lean):
                result = posture_result(sagittal_lean_deg=lean)
                feature = result.features["sagittal_torso_lean_deg"]
                self.assertAlmostEqual(feature, lean)
                scene = pv_viewer.build_scene(result, matrix_values())
                torso = scene.primitives.torso
                torso_axis = offset(torso.hip_midpoint, torso.shoulder_midpoint)
                side_x, side_y = screen(pv_viewer.side_camera(scene.anchor), torso_axis)
                # Toward the camera is screen-left in the side view.
                self.assertEqual(np.sign(-side_x), np.sign(feature))
                self.assertAlmostEqual(
                    math.degrees(math.atan2(-side_x, side_y)), feature
                )
                front_x, _ = screen(pv_viewer.front_camera(scene.anchor), torso_axis)
                self.assertAlmostEqual(front_x, 0.0, places=12)
                guide = {line.name: line for line in scene.guides}["torso_vertical"]
                self.assertEqual(guide.start, torso.hip_midpoint)
                self.assertEqual(guide.end.z_m, torso.hip_midpoint.z_m)
                self.assertAlmostEqual(guide.end.y_m, torso.shoulder_midpoint.y_m)

    def test_torso_left_and_right_lean_is_shown_in_front_view_only(self):
        for lean in (12.0, -12.0):
            with self.subTest(lean=lean):
                result = posture_result(lateral_lean_deg=lean)
                scene = pv_viewer.build_scene(result, matrix_values())
                torso = scene.primitives.torso
                torso_axis = offset(torso.hip_midpoint, torso.shoulder_midpoint)
                front_x, front_y = screen(
                    pv_viewer.front_camera(scene.anchor), torso_axis
                )
                self.assertEqual(np.sign(front_x), np.sign(lean))
                self.assertAlmostEqual(
                    math.degrees(math.atan2(front_x, front_y)), lean
                )
                side_x, _ = screen(pv_viewer.side_camera(scene.anchor), torso_axis)
                self.assertAlmostEqual(side_x, 0.0, places=12)
                self.assertAlmostEqual(
                    result.features["sagittal_torso_lean_deg"], 0.0
                )

    def test_matrix_yaw_turns_head_arrow_horizontally_in_front_view(self):
        result = posture_result()
        neutral = pv_viewer.build_scene(result, matrix_values())
        for yaw in (30.0, -30.0):
            with self.subTest(yaw=yaw):
                scene = pv_viewer.build_scene(result, matrix_values(yaw=yaw))
                head = scene.primitives.head
                front_x, front_y = screen(
                    pv_viewer.front_camera(scene.anchor), head.forward_axis
                )
                self.assertEqual(np.sign(front_x), np.sign(yaw))
                self.assertAlmostEqual(front_x, math.sin(math.radians(yaw)))
                self.assertAlmostEqual(front_y, 0.0, places=12)
                self.assertEqual(head.center, neutral.primitives.head.center)
                self.assertEqual(head.radii_m, neutral.primitives.head.radii_m)
                self.assertEqual(scene.primitives.torso, neutral.primitives.torso)
                self.assertIn(f"yaw {yaw:+.1f}", "\n".join(scene.front_lines))

    def test_matrix_pitch_tilts_head_arrow_vertically_in_both_views(self):
        result = posture_result()
        for pitch in (20.0, -20.0):
            with self.subTest(pitch=pitch):
                scene = pv_viewer.build_scene(result, matrix_values(pitch=pitch))
                forward = scene.primitives.head.forward_axis
                front_x, front_y = screen(pv_viewer.front_camera(scene.anchor), forward)
                side_x, side_y = screen(pv_viewer.side_camera(scene.anchor), forward)
                self.assertAlmostEqual(front_x, 0.0, places=12)
                self.assertEqual(np.sign(front_y), np.sign(pitch))
                self.assertEqual(np.sign(side_y), np.sign(pitch))
                self.assertLess(side_x, 0.0)  # still facing the camera
                self.assertAlmostEqual(
                    math.degrees(math.atan2(side_y, -side_x)), pitch
                )

    def test_matrix_roll_rotates_head_counter_clockwise_in_front_view(self):
        result = posture_result()
        for roll in (15.0, -15.0):
            with self.subTest(roll=roll):
                scene = pv_viewer.build_scene(result, matrix_values(roll=roll))
                head = scene.primitives.head
                camera = pv_viewer.front_camera(scene.anchor)
                lateral_x, lateral_y = screen(camera, head.lateral_axis)
                self.assertGreater(lateral_x, 0.0)
                self.assertEqual(np.sign(lateral_y), np.sign(roll))
                np.testing.assert_allclose(
                    screen(camera, head.forward_axis), (0, 0), atol=1e-12
                )

    def test_head_axes_reproduce_probe_matrix_orientation(self):
        rotations = {
            "positive yaw": mediapipe_rotation((0, 1, 0), 30.0),
            "negative yaw": mediapipe_rotation((0, 1, 0), -30.0),
            "positive pitch": mediapipe_rotation((1, 0, 0), -20.0),
            "negative pitch": mediapipe_rotation((1, 0, 0), 20.0),
            "positive roll": mediapipe_rotation((0, 0, 1), 15.0),
            "combined": mediapipe_rotation((.3, .8, .5), 37.0),
        }
        expected_signs = {
            "positive yaw": ("face_matrix_yaw_deg", 1.0),
            "negative yaw": ("face_matrix_yaw_deg", -1.0),
            "positive pitch": ("face_matrix_pitch_deg", 1.0),
            "negative pitch": ("face_matrix_pitch_deg", -1.0),
            "positive roll": ("face_matrix_roll_deg", 1.0),
        }
        to_realsense = np.diag((1.0, -1.0, -1.0))
        for name, rotation in rotations.items():
            with self.subTest(name=name):
                transform = np.eye(4)
                transform[:3, :3] = 1.4 * rotation
                transform[:3, 3] = (3.0, -2.0, -55.0)
                pitch, yaw, roll = probe.extract_face_matrix_orientation(transform)
                values = matrix_values(pitch=pitch, yaw=yaw, roll=roll)
                if name in expected_signs:
                    field, sign = expected_signs[name]
                    self.assertEqual(np.sign(values[field]), sign)
                axes = pv_viewer.face_matrix_head_axes(
                    pv_viewer.face_matrix_orientation(values)
                )
                np.testing.assert_allclose(
                    np.column_stack(axes), to_realsense @ rotation, atol=1e-9
                )

    def test_head_forward_translation_moves_head_toward_camera_only(self):
        neutral_result = posture_result()
        forward_result = posture_result(head_shift_m=(0.0, 0.0, -.05))
        self.assertGreater(
            forward_result.features["nose_forward_normalized_by_shoulder_width_3d"],
            neutral_result.features["nose_forward_normalized_by_shoulder_width_3d"],
        )
        for values in (matrix_values(pitch=-8.0, yaw=2.0), None):
            with self.subTest(matrix=values is not None):
                neutral = pv_viewer.build_scene(neutral_result, values)
                moved = pv_viewer.build_scene(forward_result, values)
                self.assertEqual(neutral.anchor, moved.anchor)
                self.assertEqual(neutral.primitives.torso, moved.primitives.torso)
                side = pv_viewer.side_camera(moved.anchor)
                shift = offset(neutral.primitives.head.center, moved.primitives.head.center)
                side_x, side_y = screen(side, shift)
                self.assertAlmostEqual(side_x, -.05)
                self.assertAlmostEqual(side_y, 0.0, places=12)
                for axis in ("lateral_axis", "vertical_axis", "forward_axis"):
                    np.testing.assert_allclose(
                        getattr(neutral.primitives.head, axis),
                        getattr(moved.primitives.head, axis),
                        atol=1e-12,
                    )
                guide = {line.name: line for line in moved.guides}["head_vertical"]
                head_from_guide = screen(
                    side, offset(guide.start, moved.primitives.head.center)
                )[0]
                self.assertLess(head_from_guide, 0.0)
        text = "\n".join(pv_viewer.build_scene(forward_result).side_lines)
        value = forward_result.features["nose_forward_normalized_by_shoulder_width_3d"]
        self.assertIn(f"head forward / 3D shoulder: {value:+.3f}", text)

    def test_head_is_centred_on_measured_ear_midpoint_at_neck_top(self):
        for name, result, values in (
            ("matrix neutral", posture_result(), matrix_values()),
            ("matrix pitch+", posture_result(), matrix_values(pitch=20.0)),
            ("matrix pitch-", posture_result(), matrix_values(pitch=-20.0)),
            ("matrix yaw", posture_result(), matrix_values(yaw=-30.0, roll=10.0)),
            ("landmarks", posture_result(), None),
            ("landmarks, no chin", posture_result(missing=("chin",)), None),
        ):
            with self.subTest(name=name):
                joints = viewer.joint_positions_3d(result)
                ear_midpoint = pv_viewer._midpoint(joints["left_ear"], joints["right_ear"])
                scene = pv_viewer.build_scene(result, values)
                head, neck = scene.primitives.head, scene.primitives.neck
                self.assertEqual(head.center, ear_midpoint)
                self.assertEqual(neck.start, ear_midpoint)
                self.assertEqual(neck.end, pv_viewer._midpoint(
                    joints["left_shoulder"], joints["right_shoulder"]
                ))
                # The measured nose stays ahead of the centre along the face
                # direction, and the joint markers stay on measured points.
                self.assertGreater(
                    float(np.dot(offset(head.center, joints["nose"]), head.forward_axis)),
                    0.0,
                )
                markers = {sphere.joint_name: sphere.center
                           for sphere in scene.primitives.joints}
                for joint in ("nose", "left_ear", "right_ear"):
                    self.assertEqual(markers[joint], joints[joint])
                if "matrix" in name:
                    expected = pv_viewer.face_matrix_head_axes(scene.face_orientation)
                    np.testing.assert_allclose(
                        (head.lateral_axis, head.vertical_axis, head.forward_axis),
                        expected, atol=1e-12,
                    )
        # Synthetic neutral ears are level with the shoulders in camera Z, so
        # the head is not drawn ahead of the shoulder vertical by the nose.
        scene = pv_viewer.build_scene(posture_result(), matrix_values())
        guide = {line.name: line for line in scene.guides}["head_vertical"]
        side_x, _ = screen(
            pv_viewer.side_camera(scene.anchor),
            offset(guide.start, scene.primitives.head.center),
        )
        self.assertAlmostEqual(side_x, 0.0, places=12)

    def test_head_and_neck_top_follow_forward_and_backward_translation(self):
        neutral_result = posture_result()
        neutral_value = neutral_result.features[
            "nose_forward_normalized_by_shoulder_width_3d"
        ]
        for shift in (-.05, .05):
            moved_result = posture_result(head_shift_m=(0.0, 0.0, shift))
            moved_value = moved_result.features[
                "nose_forward_normalized_by_shoulder_width_3d"
            ]
            # -Z shift is toward the camera: the measured value rises.
            self.assertEqual(np.sign(moved_value - neutral_value), -np.sign(shift))
            for values in (matrix_values(pitch=-8.0, yaw=2.0), None):
                with self.subTest(shift=shift, matrix=values is not None):
                    neutral = pv_viewer.build_scene(neutral_result, values)
                    moved = pv_viewer.build_scene(moved_result, values)
                    side = pv_viewer.side_camera(moved.anchor)
                    for before, after in (
                        (neutral.primitives.head.center, moved.primitives.head.center),
                        (neutral.primitives.neck.start, moved.primitives.neck.start),
                    ):
                        side_x, side_y = screen(side, offset(before, after))
                        self.assertAlmostEqual(side_x, shift)
                        self.assertAlmostEqual(side_y, 0.0, places=12)
                    self.assertEqual(neutral.primitives.neck.end, moved.primitives.neck.end)
                    self.assertEqual(neutral.primitives.torso, moved.primitives.torso)

    def test_view_anchor_follows_shoulders_or_stays_fixed_in_camera_space(self):
        shoulder, camera = pv_viewer.VIEW_ANCHOR_SHOULDER, pv_viewer.VIEW_ANCHOR_CAMERA
        first = geometry.Point3D(0.0, -.30, .85)
        second = geometry.Point3D(.02, -.29, .82)
        for measured in (first, second, None):
            self.assertEqual(
                pv_viewer.view_anchor(shoulder, measured, None), (measured, None)
            )
        # Camera mode never locks by itself: unlocked it follows the anchor ...
        for measured in (first, second, None):
            self.assertEqual(
                pv_viewer.view_anchor(camera, measured, None), (measured, None)
            )
        # ... and once locked (by the user) the lock never moves.
        for measured in (first, second, None):
            self.assertEqual(
                pv_viewer.view_anchor(camera, measured, first), (first, first)
            )
        with self.assertRaises(ValueError):
            pv_viewer.view_anchor("hips", first, None)
        # Rejected before PyVista is imported, so this holds without PyVista.
        with self.assertRaises(ValueError):
            pv_viewer.PyVistaPostureViewer(off_screen=True, anchor_mode="hips")
        self.assertEqual(set(pv_viewer.VIEW_ANCHOR_LINES), set(pv_viewer.VIEW_ANCHOR_MODES))

    def test_camera_lock_point_is_measured_shoulder_midpoint_without_fallback(self):
        result = posture_result(shoulder_shift_m=(.01, .02, -.03))
        self.assert_point(pv_viewer.camera_lock_point(result), (.01, -.30 + .02, .85 - .03))
        self.assertEqual(pv_viewer.camera_lock_point(result), pv_viewer.scene_anchor(result))
        for missing in (("left_shoulder",), ("right_shoulder",), SHOULDER_NAMES):
            with self.subTest(missing=missing):
                partial = posture_result(missing=missing)
                # The view anchor falls back to the hips; a lock never does.
                self.assertIsNotNone(pv_viewer.scene_anchor(partial))
                self.assertIsNone(pv_viewer.camera_lock_point(partial))

    def test_anchor_status_line_names_each_view_centre_state(self):
        shoulder, camera = pv_viewer.VIEW_ANCHOR_SHOULDER, pv_viewer.VIEW_ANCHOR_CAMERA
        point = geometry.Point3D(0.0, -.30, .85)
        for locked in (None, point):
            for pending in (False, True):
                self.assertEqual(
                    pv_viewer.anchor_status_line(shoulder, locked, pending),
                    pv_viewer.VIEW_ANCHOR_LINES[shoulder],
                )
        self.assertEqual(pv_viewer.anchor_status_line(camera, None, False),
                         pv_viewer.CAMERA_UNLOCKED_LINE)
        self.assertEqual(pv_viewer.anchor_status_line(camera, point, False),
                         pv_viewer.CAMERA_LOCKED_LINE)
        for locked in (None, point):
            self.assertEqual(pv_viewer.anchor_status_line(camera, locked, True),
                             pv_viewer.CAMERA_LOCK_WAITING_LINE)
        self.assertIn("NOT LOCKED", pv_viewer.CAMERA_UNLOCKED_LINE)
        self.assertTrue(pv_viewer.CAMERA_LOCKED_LINE.startswith("LOCKED"))
        self.assertIn(pv_viewer.VIEW_ANCHOR_LINES[camera], pv_viewer.CAMERA_LOCKED_LINE)
        with self.assertRaises(ValueError):
            pv_viewer.anchor_status_line("hips", None, False)
        # VTK text treats '|' as a column separator.
        for line in (pv_viewer.CAMERA_UNLOCKED_LINE, pv_viewer.CAMERA_LOCKED_LINE,
                     pv_viewer.CAMERA_LOCK_WAITING_LINE, *pv_viewer.NECK_STATUS_LINES.values()):
            self.assertNotIn("|", line)

    def test_screen_motion_separates_head_and_shoulder_movement(self):
        neutral = posture_result()
        cases = {
            "head only": ((0.0, 0.0, -.03), (0.0, 0.0, 0.0)),
            "shoulders only": ((0.0, 0.0, 0.0), (0.0, .01, -.03)),
            "head and shoulders": ((0.0, 0.0, -.03), (0.0, .01, -.02)),
        }
        for name, (head_shift, shoulder_shift) in cases.items():
            moved = posture_result(head_shift_m=head_shift, shoulder_shift_m=shoulder_shift)
            scenes = [pv_viewer.build_scene(r, matrix_values()) for r in (neutral, moved)]
            for mode, head_expected, hip_expected in (
                # Following the shoulders shows motion relative to them ...
                (pv_viewer.VIEW_ANCHOR_SHOULDER,
                 np.subtract(head_shift, shoulder_shift), np.negative(shoulder_shift)),
                # ... a camera-fixed view shows the measured camera-space motion.
                (pv_viewer.VIEW_ANCHOR_CAMERA, np.asarray(head_shift), np.zeros(3)),
            ):
                with self.subTest(case=name, mode=mode):
                    # Camera mode: the user locked the view on the first frame.
                    locked = scenes[0].anchor if mode == pv_viewer.VIEW_ANCHOR_CAMERA else None
                    positions = []
                    for scene in scenes:
                        focal, locked = pv_viewer.view_anchor(mode, scene.anchor, locked)
                        side = pv_viewer.side_camera(focal)
                        positions.append([
                            screen(side, offset(focal, point))
                            for point in (scene.primitives.head.center,
                                          scene.primitives.torso.hip_midpoint)
                        ])
                    head_move, hip_move = np.subtract(positions[1], positions[0])
                    np.testing.assert_allclose(head_move, screen(side, head_expected), atol=1e-12)
                    np.testing.assert_allclose(hip_move, screen(side, hip_expected), atol=1e-12)
                    # The drawn neck is the measured shoulder->ear line either way.
                    neck = scenes[1].primitives.neck
                    self.assertEqual(neck.end, scenes[1].anchor)
            # Head-forward text still reports the measured value, view-independent.
            value = moved.features["nose_forward_normalized_by_shoulder_width_3d"]
            self.assertIn(f"{value:+.3f}", "\n".join(scenes[1].side_lines))

    def head_local(self, head, point):
        """Point in the drawn head's axes, as fractions of its radii."""

        vector = offset(head.center, point)
        return np.asarray([
            float(np.dot(vector, axis)) / radius
            for axis, radius in zip(
                (head.lateral_axis, head.vertical_axis, head.forward_axis), head.radii_m
            )
        ])

    def test_display_neck_joins_torso_top_to_inside_lower_back_of_head(self):
        for name, result, values in (
            ("matrix neutral", posture_result(), matrix_values()),
            ("matrix pitch+", posture_result(), matrix_values(pitch=20.0)),
            ("matrix pitch-", posture_result(), matrix_values(pitch=-20.0)),
            ("matrix yaw/roll", posture_result(), matrix_values(yaw=-30.0, roll=10.0)),
            ("no hips", posture_result(missing=HIP_NAMES), matrix_values()),
        ):
            with self.subTest(name=name):
                scene = pv_viewer.build_scene(result, values)
                head, measured, neck = (
                    scene.primitives.head, scene.primitives.neck, scene.display_neck
                )
                # Measured relation untouched; it is what the cyan line draws.
                expected = pv_viewer.orient_head(
                    viewer.build_avatar_primitives(result),
                    pv_viewer.face_matrix_orientation(values),
                )[0]
                self.assertEqual(scene.primitives, expected)
                self.assertEqual(measured.start, head.center)
                # Bottom: the measured shoulder midpoint (= torso top centre).
                self.assertEqual(neck.base, measured.end)
                if scene.primitives.torso is not None:
                    self.assertEqual(neck.base, scene.primitives.torso.shoulder_midpoint)
                    self.assertLessEqual(neck.base_radius_m, scene.primitives.torso.half_depth_m)
                # Top: the same place inside the head in the head's own axes,
                # so it turns with yaw/pitch/roll and is hidden by the head.
                np.testing.assert_allclose(
                    self.head_local(head, neck.top),
                    (0.0, -pv_viewer.NECK_TOP_DOWN_FACTOR, -pv_viewer.NECK_TOP_BACK_FACTOR),
                    atol=1e-12,
                )
                self.assertLess(float(np.sum(self.head_local(head, neck.top) ** 2)), 1.0)
                self.assertLessEqual(neck.top_radius_m, neck.base_radius_m)
                self.assertIn(pv_viewer.MESH_NOTE, scene.front_lines)
                self.assertIn(pv_viewer.MESH_NOTE, scene.side_lines)

    def test_display_neck_follows_measured_head_and_shoulder_motion(self):
        neutral = pv_viewer.build_scene(posture_result(), matrix_values(pitch=-8.0))
        for head_shift, shoulder_shift in (
            ((0.0, 0.0, -.05), (0.0, 0.0, 0.0)),   # head forward
            ((0.0, 0.0, .05), (0.0, 0.0, 0.0)),    # head backward
            ((0.0, 0.0, 0.0), (0.0, .01, -.03)),   # shoulders only (arms on desk)
        ):
            with self.subTest(head=head_shift, shoulders=shoulder_shift):
                moved = pv_viewer.build_scene(
                    posture_result(head_shift_m=head_shift, shoulder_shift_m=shoulder_shift),
                    matrix_values(pitch=-8.0),
                )
                np.testing.assert_allclose(
                    offset(neutral.display_neck.top, moved.display_neck.top), head_shift, atol=1e-12
                )
                np.testing.assert_allclose(
                    offset(neutral.display_neck.base, moved.display_neck.base),
                    shoulder_shift, atol=1e-12,
                )
                # The measured line moves exactly like its measured endpoints.
                np.testing.assert_allclose(
                    offset(neutral.primitives.neck.start, moved.primitives.neck.start),
                    head_shift, atol=1e-12,
                )
        # Nothing is drawn without a measured head.
        scene = pv_viewer.build_scene(posture_result(missing=("nose",)), matrix_values())
        self.assertIsNone(scene.display_neck)
        self.assertIsNone(scene.primitives.neck)
        self.assertIn(
            pv_viewer.NECK_STATUS_LINES[pv_viewer.HEAD_SOURCE_UNAVAILABLE], scene.side_lines
        )

    def test_display_neck_is_hidden_while_face_matrix_is_missing(self):
        result = posture_result(head_shift_m=(0.0, 0.0, -.04))
        measured = viewer.build_avatar_primitives(result)
        invalid = {**matrix_values(5.0, 5.0, 5.0), "face_matrix_valid": False}
        scenes = [
            pv_viewer.build_scene(result, values)
            for values in (matrix_values(pitch=-8.0), None, invalid, matrix_values(pitch=-8.0))
        ]
        self.assertEqual(
            [scene.head_source for scene in scenes],
            [pv_viewer.HEAD_SOURCE_FACE_MATRIX, pv_viewer.HEAD_SOURCE_LANDMARKS,
             pv_viewer.HEAD_SOURCE_LANDMARKS, pv_viewer.HEAD_SOURCE_FACE_MATRIX],
        )
        self.assertEqual(
            [scene.display_neck is not None for scene in scenes], [True, False, False, True]
        )
        # Re-shown in the same place: the top is still fixed in the matrix head axes.
        self.assertEqual(scenes[0].display_neck, scenes[3].display_neck)
        self.assertEqual(
            scenes[0].display_neck,
            pv_viewer.display_neck(pv_viewer.orient_head(
                measured, pv_viewer.face_matrix_orientation(matrix_values(pitch=-8.0))
            )[0]),
        )
        head_forward = result.features["nose_forward_normalized_by_shoulder_width_3d"]
        for scene in scenes:
            # The measured shoulder->ear line and head position never change.
            self.assertEqual(scene.primitives.neck, measured.neck)
            self.assertEqual(scene.primitives.head.center, measured.head.center)
            self.assertEqual(scene.primitives.torso, measured.torso)
            self.assertIn(f"{head_forward:+.3f}", "\n".join(scene.side_lines))
            self.assertIn(pv_viewer.NECK_STATUS_LINES[scene.head_source], scene.side_lines)
        self.assertIn("face matrix unavailable", "\n".join(scenes[1].front_lines))

    def test_unavailable_or_invalid_matrix_keeps_landmark_head_axes(self):
        result = posture_result()
        baseline = viewer.build_avatar_primitives(result)
        invalid_values = {
            "none": None,
            "empty": {},
            "not a mapping": [True, 1.0, 2.0, 3.0],
            "invalid flag": {**matrix_values(1.0, 2.0, 3.0), "face_matrix_valid": False},
            "string flag": {**matrix_values(), "face_matrix_valid": "True"},
            "integer flag": {**matrix_values(), "face_matrix_valid": 1},
            "missing angle": {"face_matrix_valid": True, "face_matrix_pitch_deg": 1.0,
                              "face_matrix_yaw_deg": 2.0},
            "nan pitch": matrix_values(pitch=math.nan),
            "infinite yaw": matrix_values(yaw=math.inf),
            "none roll": matrix_values(roll=None),
            "bool roll": matrix_values(roll=True),
            "string yaw": matrix_values(yaw="12"),
        }
        for name, values in invalid_values.items():
            with self.subTest(name=name):
                scene = pv_viewer.build_scene(result, values)
                self.assertIsNone(scene.face_orientation)
                self.assertEqual(scene.head_source, pv_viewer.HEAD_SOURCE_LANDMARKS)
                self.assertEqual(scene.primitives, baseline)
                text = "\n".join(scene.front_lines)
                self.assertIn("face matrix unavailable", text)
                self.assertNotIn("nan", text.lower())
                self.assertNotIn("inf", text.lower())

    def test_valid_matrix_without_measured_head_position_draws_no_head(self):
        for missing in (("nose",), ("left_ear",), ("left_shoulder",)):
            with self.subTest(missing=missing):
                scene = pv_viewer.build_scene(
                    posture_result(missing=missing), matrix_values(yaw=25.0)
                )
                self.assertIsNone(scene.primitives.head)
                self.assertEqual(scene.head_source, pv_viewer.HEAD_SOURCE_UNAVAILABLE)
                self.assertEqual(scene.face_orientation.yaw_deg, 25.0)
                text = "\n".join(scene.front_lines)
                self.assertIn("head: unavailable", text)
                self.assertIn("yaw +25.0", text)

    def test_anchor_falls_back_without_inventing_missing_joints(self):
        self.assert_point(
            pv_viewer.scene_anchor(posture_result(missing=("left_shoulder",))),
            (0.0, .25, .85),
        )
        self.assert_point(
            pv_viewer.scene_anchor(posture_result(
                missing=("left_shoulder", "right_hip")
            )),
            (0.0, -.55, .76),
        )
        empty = posture_result(missing=tuple(NEUTRAL_3D))
        scene = pv_viewer.build_scene(empty, matrix_values())
        self.assertIsNone(scene.anchor)
        self.assertEqual(scene.guides, ())
        self.assertIsNone(scene.primitives.torso)
        self.assertEqual(scene.primitives.joints, ())

    def test_nonfinite_geometry_never_creates_primitives_or_numbers(self):
        bad = geometry.GeometryResult(
            points={},
            proxies={},
            features={
                "sagittal_torso_lean_deg": math.nan,
                "nose_forward_normalized_by_shoulder_width_3d": math.inf,
            },
            points_3d={
                "nose": geometry.Point3D(math.nan, -.5, .8),
                "left_ear": geometry.Point3D(.08, -.5, math.inf),
                "right_ear": geometry.Point3D(-.08, -.5, .8),
                "left_shoulder": geometry.Point3D(.2, -.3, -.8),
                "right_shoulder": geometry.Point3D(-.2, -.3, .8),
                "left_hip": geometry.Point3D(.15, .25, 0.0),
                "right_hip": geometry.Point3D("x", .25, .8),
            },
            proxies_3d={
                "shoulder_midpoint_3d": geometry.Point3D(math.nan, 0, 1),
            },
        )
        before = bad.as_debug_dict()
        scene = pv_viewer.build_scene(bad, matrix_values())
        self.assertIsNone(scene.anchor)
        self.assertEqual(scene.guides, ())
        self.assertIsNone(scene.primitives.head)
        self.assertIsNone(scene.primitives.torso)
        self.assertIsNone(scene.primitives.neck)
        # Unpaired joints give no measured display scale, so no spheres.
        self.assertEqual(scene.primitives.joints, ())
        text = "\n".join(scene.side_lines)
        self.assertIn("torso lean (+toward camera): unavailable", text)
        self.assertIn("head forward / 3D shoulder: unavailable", text)
        self.assertNotIn("nan", text.lower())
        self.assertEqual(bad.as_debug_dict(), before)

    def test_scene_does_not_mutate_geometry_or_matrix_values(self):
        result = posture_result(sagittal_lean_deg=7.0)
        values = matrix_values(pitch=-6.0, yaw=12.0, roll=2.0)
        result_before, values_before = result.as_debug_dict(), dict(values)
        pv_viewer.build_scene(result, values)
        self.assertEqual(result.as_debug_dict(), result_before)
        self.assertEqual(values, values_before)


@unittest.skipUnless(PYVISTA_AVAILABLE, "optional PyVista viewer dependency not installed")
class PyVistaWindowTests(unittest.TestCase):
    def make_viewer(self, anchor_mode=pv_viewer.VIEW_ANCHOR_SHOULDER):
        window = pv_viewer.PyVistaPostureViewer(
            off_screen=True, window_size=(800, 400), anchor_mode=anchor_mode
        )
        self.addCleanup(window.close)
        return window

    def arrow_centroid(self, image, column):
        half = image.shape[1] // 2
        view = image[:, column * half:(column + 1) * half].astype(int)
        red, green, blue = view[..., 0], view[..., 1], view[..., 2]
        mask = (green > 120) & (green > red + 60) & (green > blue + 40)
        self.assertGreater(int(mask.sum()), 0)
        rows, columns = np.nonzero(mask)
        return float(columns.mean()), float(rows.mean())

    def test_offscreen_update_reuses_actors_and_hides_missing_primitives(self):
        window = self.make_viewer()
        self.assertTrue(window.update(posture_result(), matrix_values()))
        image = window.screenshot()
        self.assertEqual(image.shape, (400, 800, 3))
        self.assertTrue(image.any())
        front, side = window.plotter.renderers[0], window.plotter.renderers[1]
        for renderer in (front, side):
            for name in ("torso", "pelvis", "neck", "head",
                         "head_forward:face_matrix", "guide:torso_vertical"):
                self.assertTrue(renderer.actors[name].GetVisibility(), name)
        torso_actor = front.actors["torso"]
        anchor = pv_viewer.scene_anchor(posture_result())
        camera = pv_viewer.front_camera(anchor)
        np.testing.assert_allclose(front.camera.focal_point, camera.focal_point)
        self.assertTrue(front.camera.parallel_projection)

        self.assertTrue(window.update(posture_result(missing=HIP_NAMES), None))
        window.screenshot()
        self.assertIs(front.actors["torso"], torso_actor)
        for renderer in (front, side):
            # Without a face matrix the display neck is hidden as well.
            for name in ("torso", "pelvis", "guide:torso_vertical",
                         "head_forward:face_matrix", "neck"):
                self.assertFalse(renderer.actors[name].GetVisibility(), name)
            for name in ("head", "measured:shoulder_ear", "head_forward:landmarks"):
                self.assertTrue(renderer.actors[name].GetVisibility(), name)

        window.close()
        window.close()
        self.assertTrue(window.closed)
        self.assertFalse(window.update(posture_result(), matrix_values()))

    def test_rendered_head_arrow_follows_yaw_and_pitch_signs(self):
        for mode in pv_viewer.VIEW_ANCHOR_MODES:
            with self.subTest(anchor_mode=mode):
                window = self.make_viewer(mode)
                result = posture_result()
                if mode == pv_viewer.VIEW_ANCHOR_CAMERA:
                    # Render the locked camera state.
                    window.update(result, matrix_values())
                    press_key(window, "l")
                    window.update(result, matrix_values())
                    self.assertEqual(
                        window.plotter.renderers[1].actors["status"].GetText(2).splitlines()[-1],
                        pv_viewer.CAMERA_LOCKED_LINE,
                    )
                centroids = {}
                for name, values in (
                    ("yaw+", matrix_values(yaw=30.0)),
                    ("yaw-", matrix_values(yaw=-30.0)),
                    ("pitch+", matrix_values(pitch=20.0)),
                    ("pitch-", matrix_values(pitch=-20.0)),
                ):
                    window.update(result, values)
                    image = window.screenshot()
                    centroids[name] = (
                        self.arrow_centroid(image, 0), self.arrow_centroid(image, 1)
                    )
                # Front view: +yaw arrow toward screen-right (+X image-right).
                self.assertGreater(centroids["yaw+"][0][0], centroids["yaw-"][0][0])
                # Image rows grow downward: +pitch arrow is higher in both views.
                self.assertLess(centroids["pitch+"][0][1], centroids["pitch-"][0][1])
                self.assertLess(centroids["pitch+"][1][1], centroids["pitch-"][1][1])

    def test_neck_mesh_is_tapered_display_tube_beside_measured_line(self):
        import pyvista

        def xyz(point):
            return (point.x_m, point.y_m, point.z_m)

        scene = pv_viewer.build_scene(posture_result(), matrix_values())
        meshes = pv_viewer.scene_meshes(scene, pyvista)
        line, _ = meshes["measured:shoulder_ear"]
        measured = scene.primitives.neck
        np.testing.assert_allclose(line.points, (xyz(measured.end), xyz(measured.start)))
        tube, _ = meshes["neck"]
        neck = scene.display_neck
        base, top = np.asarray(xyz(neck.base)), np.asarray(xyz(neck.top))
        axis = (top - base) / np.linalg.norm(top - base)
        along = (tube.points - base) @ axis / np.linalg.norm(top - base)
        radial = np.linalg.norm((tube.points - base) - np.outer(along * np.linalg.norm(top - base), axis), axis=1)
        for end, radius in ((0.0, neck.base_radius_m), (1.0, neck.top_radius_m)):
            ring = np.isclose(along, end, atol=1e-4)  # VTK points are float32
            self.assertGreater(int(ring.sum()), 0)
            self.assertAlmostEqual(float(radial[ring].max()), radius, places=5)
        # Actor reuse copies new geometry in place: topology must not change.
        other = pv_viewer.scene_meshes(pv_viewer.build_scene(
            posture_result(head_shift_m=(0.0, 0.0, -.05), shoulder_shift_m=(0.0, .01, -.03)),
            matrix_values(pitch=20.0, yaw=-30.0),
        ), pyvista)["neck"][0]
        self.assertEqual((other.n_points, other.n_cells), (tube.n_points, tube.n_cells))
        window = self.make_viewer()
        window.update(posture_result(), matrix_values())
        for renderer in window.plotter.renderers:
            for name in ("neck", "measured:shoulder_ear", "head"):
                self.assertTrue(renderer.actors[name].GetVisibility(), name)

    def test_camera_anchor_fixes_rendered_view_while_shoulder_anchor_follows(self):
        neutral = posture_result()
        shoulders_forward = posture_result(shoulder_shift_m=(0.0, 0.0, -.03))
        head = pv_viewer.build_scene(neutral).primitives.head.center  # head never moves
        px_per_m = 400 / (2 * pv_viewer.VIEW_HALF_HEIGHT_M)
        for mode, focal_shift_z, head_shift_px in (
            # Screen-right is +Z: following shoulders that came toward the
            # camera pushes a still head to the right on screen.
            (pv_viewer.VIEW_ANCHOR_SHOULDER, -.03, .03 * px_per_m),
            (pv_viewer.VIEW_ANCHOR_CAMERA, 0.0, 0.0),
        ):
            with self.subTest(anchor_mode=mode):
                window = self.make_viewer(mode)
                side = window.plotter.renderers[1]

                def head_pixel():
                    side.SetWorldPoint(head.x_m, head.y_m, head.z_m, 1.0)
                    side.WorldToDisplay()
                    return np.asarray(side.GetDisplayPoint()[:2])

                window.update(neutral, matrix_values())
                if mode == pv_viewer.VIEW_ANCHOR_CAMERA:
                    press_key(window, "l")  # the user locks once settled
                    window.update(neutral, matrix_values())
                focal_before, head_before = np.asarray(side.camera.focal_point), head_pixel()
                # Second frame also drops the face matrix (landmark head axes).
                window.update(shoulders_forward, None)
                focal_after, head_after = np.asarray(side.camera.focal_point), head_pixel()
                np.testing.assert_allclose(
                    focal_after - focal_before, (0.0, 0.0, focal_shift_z), atol=1e-9
                )
                np.testing.assert_allclose(
                    head_after - head_before, (head_shift_px, 0.0), atol=1e-6
                )
                self.assertTrue(side.actors["head_forward:landmarks"].GetVisibility())
                self.assertFalse(side.actors["head_forward:face_matrix"].GetVisibility())
                self.assertIn(
                    pv_viewer.VIEW_ANCHOR_LINES[mode], side.actors["status"].GetText(2)
                )

    def focal_and_status(self, window):
        """Both views' focal points (must agree) and the side status line."""

        front, side = window.plotter.renderers
        np.testing.assert_allclose(front.camera.focal_point, side.camera.focal_point)
        return (np.asarray(side.camera.focal_point),
                side.actors["status"].GetText(2).splitlines()[-1])

    def test_camera_view_never_locks_on_start_frame_and_locks_only_on_key(self):
        # SYNTHETIC: a start-up frame whose shoulder depth is 12 cm off.
        start = posture_result(shoulder_shift_m=(0.0, -.04, .12))
        neutral = posture_result()
        moved = posture_result(shoulder_shift_m=(0.0, .01, -.03))
        no_shoulder = posture_result(missing=("left_shoulder",))

        def xyz(point):
            return np.asarray((point.x_m, point.y_m, point.z_m))

        window = self.make_viewer(pv_viewer.VIEW_ANCHOR_CAMERA)
        window.update(start, matrix_values())
        focal, status = self.focal_and_status(window)
        np.testing.assert_allclose(focal, xyz(pv_viewer.scene_anchor(start)))
        self.assertEqual(status, pv_viewer.CAMERA_UNLOCKED_LINE)
        # Unlocked: the next frame is followed, the start frame is not kept.
        window.update(neutral, matrix_values())
        focal, status = self.focal_and_status(window)
        np.testing.assert_allclose(focal, xyz(pv_viewer.scene_anchor(neutral)))
        self.assertEqual(status, pv_viewer.CAMERA_UNLOCKED_LINE)

        # L locks at the next frame's measured shoulder midpoint ...
        press_key(window, "l")
        window.update(neutral, matrix_values())
        locked = xyz(pv_viewer.camera_lock_point(neutral))
        focal, status = self.focal_and_status(window)
        np.testing.assert_allclose(focal, locked)
        self.assertEqual(status, pv_viewer.CAMERA_LOCKED_LINE)
        # ... which then stays fixed while the shoulders move.
        window.update(moved, None)
        focal, status = self.focal_and_status(window)
        np.testing.assert_allclose(focal, locked)
        self.assertEqual(status, pv_viewer.CAMERA_LOCKED_LINE)

        # Re-lock without both shoulders waits and keeps the old lock ...
        press_key(window, "L")
        window.update(no_shoulder, matrix_values())
        focal, status = self.focal_and_status(window)
        np.testing.assert_allclose(focal, locked)
        self.assertEqual(status, pv_viewer.CAMERA_LOCK_WAITING_LINE)
        # ... until both shoulders are measured again.
        window.update(moved, matrix_values())
        focal, status = self.focal_and_status(window)
        np.testing.assert_allclose(focal, xyz(pv_viewer.camera_lock_point(moved)))
        self.assertEqual(status, pv_viewer.CAMERA_LOCKED_LINE)

        # A first lock request without shoulders keeps following the fallback.
        # (The window exists, and so takes keys, from its first update.)
        fresh = self.make_viewer(pv_viewer.VIEW_ANCHOR_CAMERA)
        fresh.update(start, matrix_values())
        press_key(fresh, "l")
        fresh.update(no_shoulder, matrix_values())
        focal, status = self.focal_and_status(fresh)
        np.testing.assert_allclose(focal, xyz(pv_viewer.scene_anchor(no_shoulder)))
        self.assertEqual(status, pv_viewer.CAMERA_LOCK_WAITING_LINE)
        fresh.update(neutral, matrix_values())
        focal, status = self.focal_and_status(fresh)
        np.testing.assert_allclose(focal, locked)
        self.assertEqual(status, pv_viewer.CAMERA_LOCKED_LINE)

    def test_lock_key_leaves_shoulder_mode_unchanged(self):
        window = self.make_viewer(pv_viewer.VIEW_ANCHOR_SHOULDER)
        window.update(posture_result(), matrix_values())
        for key in pv_viewer.CAMERA_LOCK_KEYS:
            press_key(window, key)
        # Every later frame is still followed (no lock taken on any of them).
        for shift in ((0.0, .01, -.03), (.02, -.01, .04)):
            moved = posture_result(shoulder_shift_m=shift)
            window.update(moved, matrix_values())
            focal, status = self.focal_and_status(window)
            anchor = pv_viewer.scene_anchor(moved)
            np.testing.assert_allclose(focal, (anchor.x_m, anchor.y_m, anchor.z_m))
            self.assertEqual(status, pv_viewer.VIEW_ANCHOR_LINES[pv_viewer.VIEW_ANCHOR_SHOULDER])

    def test_neck_actor_hides_and_returns_with_face_matrix_while_measured_line_stays(self):
        result = posture_result()
        measured = viewer.build_avatar_primitives(result).neck

        def xyz(point):
            return (point.x_m, point.y_m, point.z_m)

        window = self.make_viewer()
        neck_actors = None
        for values, neck_visible in (
            (matrix_values(), True), (None, False), (matrix_values(), True)
        ):
            window.update(result, values)
            for renderer in window.plotter.renderers:
                self.assertEqual(bool(renderer.actors["neck"].GetVisibility()), neck_visible)
                self.assertTrue(renderer.actors["measured:shoulder_ear"].GetVisibility())
                self.assertIn(
                    pv_viewer.NECK_STATUS_LINES[
                        pv_viewer.HEAD_SOURCE_FACE_MATRIX if neck_visible
                        else pv_viewer.HEAD_SOURCE_LANDMARKS
                    ],
                    window.plotter.renderers[1].actors["status"].GetText(2),
                )
            line = window.plotter.renderers[0].actors["measured:shoulder_ear"].mapper.dataset
            np.testing.assert_allclose(line.points, (xyz(measured.end), xyz(measured.start)),
                                       atol=1e-6)  # VTK points are float32
            actors = [renderer.actors["neck"] for renderer in window.plotter.renderers]
            if neck_actors is None:
                neck_actors = actors
            for actor, first in zip(actors, neck_actors):
                self.assertIs(actor, first)


if __name__ == "__main__":
    unittest.main()
