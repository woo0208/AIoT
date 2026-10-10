import math
import unittest

import numpy as np

import posture_3d_viewer as viewer
import posture_geometry as geometry


def upper_body_result(*, missing_3d=()):
    points = {
        "nose": geometry.Point(100, 35, .68),
        "left_ear": geometry.Point(115, 45, .70),
        "right_ear": geometry.Point(85, 45, .70),
        "left_shoulder": geometry.Point(140, 90, .80),
        "right_shoulder": geometry.Point(60, 90, .80),
        "left_elbow": geometry.Point(155, 120, .82),
        "right_elbow": geometry.Point(45, 120, .82),
        "left_wrist": geometry.Point(165, 150, .84),
        "right_wrist": geometry.Point(35, 150, .84),
        "left_hip": geometry.Point(130, 160, .82),
        "right_hip": geometry.Point(70, 160, .82),
    }
    points_3d = {
        "nose": geometry.Point3D(0.0, -.55, .68),
        "left_ear": geometry.Point3D(.10, -.48, .70),
        "right_ear": geometry.Point3D(-.10, -.48, .70),
        "left_shoulder": geometry.Point3D(.22, -.30, .80),
        "right_shoulder": geometry.Point3D(-.22, -.30, .80),
        "left_elbow": geometry.Point3D(.35, -.05, .82),
        "right_elbow": geometry.Point3D(-.35, -.05, .82),
        "left_wrist": geometry.Point3D(.40, .15, .84),
        "right_wrist": geometry.Point3D(-.40, .15, .84),
        "left_hip": geometry.Point3D(.16, .25, .82),
        "right_hip": geometry.Point3D(-.16, .25, .82),
    }
    for name in missing_3d:
        points_3d[name] = None
    return geometry.compute_candidate_geometry(points, points_3d=points_3d)


def pitched_head_result(pitch_deg):
    base = upper_body_result()
    points = dict(base.points)
    points["chin"] = geometry.Point(100, 62, .58)
    points_3d = dict(base.points_3d)
    ear_y, ear_z = -.48, .70
    angle = math.radians(pitch_deg)
    cosine, sine = math.cos(angle), math.sin(angle)

    def rotate(down, away):
        return geometry.Point3D(
            0.0,
            ear_y + down * cosine + away * sine,
            ear_z - down * sine + away * cosine,
        )

    points_3d["nose"] = rotate(-.07, -.12)
    points_3d["chin"] = rotate(.07, -.12)
    return geometry.compute_candidate_geometry(points, points_3d=points_3d)


class ViewerHelperTests(unittest.TestCase):
    def test_measured_lower_face_pitch_orients_head_without_changing_torso(self):
        neutral = viewer.build_avatar_primitives(pitched_head_result(0.0))
        chin_up = viewer.build_avatar_primitives(pitched_head_result(20.0))
        chin_down = viewer.build_avatar_primitives(pitched_head_result(-20.0))
        self.assertAlmostEqual(neutral.head.forward_axis[1], 0.0, places=7)
        self.assertLess(chin_up.head.forward_axis[1], 0.0)
        self.assertGreater(chin_down.head.forward_axis[1], 0.0)
        self.assertEqual(neutral.torso, chin_up.torso)
        self.assertEqual(neutral.torso, chin_down.torso)
        up_image = viewer.render_side_avatar_view(
            pitched_head_result(20.0), size=(520, 480)
        )
        down_image = viewer.render_side_avatar_view(
            pitched_head_result(-20.0), size=(520, 480)
        )
        self.assertFalse(np.array_equal(up_image, down_image))

    def test_avatar_falls_back_to_previous_orientation_without_chin_xyz(self):
        baseline_result = upper_body_result()
        points = dict(baseline_result.points)
        points["chin"] = geometry.Point(100, 62, None)
        points_3d = dict(baseline_result.points_3d)
        points_3d["chin"] = None
        missing_pitch = geometry.compute_candidate_geometry(
            points, points_3d=points_3d
        )
        baseline = viewer.build_avatar_primitives(baseline_result)
        fallback = viewer.build_avatar_primitives(missing_pitch)
        self.assertIsNone(
            missing_pitch.features["exploratory_head_pitch_deg"]
        )
        self.assertEqual(fallback.head, baseline.head)
        self.assertEqual(fallback.torso, baseline.torso)

    def test_avatar_primitives_follow_valid_measured_joints(self):
        result = upper_body_result()
        before = result.as_debug_dict()
        avatar = viewer.build_avatar_primitives(result)

        self.assertIsNotNone(avatar.head)
        self.assertIsNotNone(avatar.neck)
        self.assertIsNotNone(avatar.torso)
        self.assertIsNotNone(avatar.pelvis)
        self.assertEqual(len(avatar.arm_segments), 4)
        self.assertEqual(len(avatar.joints), len(geometry.UPPER_BODY_3D_POINT_NAMES))
        self.assertEqual(
            avatar.head.center,
            geometry.Point3D(0.0, -.515, .69),
        )
        self.assertAlmostEqual(avatar.torso.shoulder_width_m, .44)
        self.assertAlmostEqual(avatar.torso.hip_width_m, .32)
        self.assertEqual(len(avatar.torso.vertices), 8)
        self.assertEqual(result.as_debug_dict(), before)

    def test_arm_capsules_use_correct_shoulder_elbow_wrist_associations(self):
        avatar = viewer.build_avatar_primitives(upper_body_result())
        associations = {
            capsule.name: (capsule.start_name, capsule.end_name)
            for capsule in avatar.arm_segments
        }
        self.assertEqual(associations, {
            "left_upper_arm": ("left_shoulder", "left_elbow"),
            "left_forearm": ("left_elbow", "left_wrist"),
            "right_upper_arm": ("right_shoulder", "right_elbow"),
            "right_forearm": ("right_elbow", "right_wrist"),
        })
        by_name = {capsule.name: capsule for capsule in avatar.arm_segments}
        self.assertEqual(
            by_name["left_upper_arm"].start,
            geometry.Point3D(.22, -.30, .80),
        )
        self.assertEqual(
            by_name["right_forearm"].end,
            geometry.Point3D(-.40, .15, .84),
        )

    def test_torso_orientation_comes_from_shoulder_and_hip_geometry(self):
        torso = viewer.build_avatar_primitives(upper_body_result()).torso
        self.assertIsNotNone(torso)
        expected = np.asarray((0.0, -.55, -.02))
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(torso.longitudinal_axis, expected)
        self.assertAlmostEqual(
            float(np.dot(torso.longitudinal_axis, torso.lateral_axis)),
            0.0,
        )
        self.assertAlmostEqual(
            float(np.dot(torso.longitudinal_axis, torso.depth_axis)),
            0.0,
        )
        self.assertEqual(
            torso.shoulder_midpoint,
            geometry.Point3D(0.0, -.30, .80),
        )
        self.assertEqual(
            torso.hip_midpoint,
            geometry.Point3D(0.0, .25, .82),
        )

    def test_avatar_missing_joints_degrade_without_substitution(self):
        missing_wrist = viewer.build_avatar_primitives(
            upper_body_result(missing_3d=("left_wrist",))
        )
        self.assertEqual(
            {capsule.name for capsule in missing_wrist.arm_segments},
            {"left_upper_arm", "right_upper_arm", "right_forearm"},
        )

        missing_elbow = viewer.build_avatar_primitives(
            upper_body_result(missing_3d=("left_elbow",))
        )
        self.assertEqual(
            {capsule.name for capsule in missing_elbow.arm_segments},
            {"right_upper_arm", "right_forearm"},
        )

        missing_hip = viewer.build_avatar_primitives(
            upper_body_result(missing_3d=("left_hip",))
        )
        self.assertIsNone(missing_hip.torso)
        self.assertIsNone(missing_hip.pelvis)
        self.assertIsNotNone(missing_hip.head)
        self.assertIsNotNone(missing_hip.neck)

    def test_side_view_coordinate_conversion_uses_forward_minus_z_and_up_minus_y(self):
        point = geometry.Point3D(.25, -.30, .80)
        self.assertEqual(
            viewer.depth_vertical_to_sagittal(point),
            viewer.SagittalPoint(camera_forward_m=-.80, vertical_up_m=.30),
        )
        side = viewer.sagittal_points(upper_body_result())
        self.assertEqual(side["nose"], viewer.SagittalPoint(-.68, .55))
        self.assertEqual(side["ear_midpoint"], viewer.SagittalPoint(-.70, .48))
        self.assertEqual(side["shoulder_midpoint"], viewer.SagittalPoint(-.80, .30))
        self.assertEqual(side["hip_midpoint"], viewer.SagittalPoint(-.82, -.25))

    def test_missing_arm_joints_skip_only_dependent_skeleton_segments(self):
        result = upper_body_result(missing_3d=("left_elbow", "left_wrist"))
        names = {(segment.start_name, segment.end_name)
                 for segment in viewer.available_skeleton_segments(result)}
        self.assertNotIn(("left_shoulder", "left_elbow"), names)
        self.assertNotIn(("left_elbow", "left_wrist"), names)
        self.assertIn(("right_shoulder", "right_elbow"), names)
        self.assertIn(("right_elbow", "right_wrist"), names)
        self.assertIn(("left_shoulder", "right_shoulder"), names)
        self.assertIsNotNone(result.features["sagittal_torso_lean_deg"])
        self.assertIsNotNone(viewer.sagittal_points(result)["hip_midpoint"])

    def test_joint_mapping_is_reusable_and_returns_all_named_slots(self):
        joints = viewer.joint_positions_3d(upper_body_result())
        self.assertEqual(tuple(joints), geometry.UPPER_BODY_3D_POINT_NAMES)
        self.assertEqual(joints["left_elbow"], geometry.Point3D(.35, -.05, .82))
        self.assertEqual(joints["right_wrist"], geometry.Point3D(-.40, .15, .84))
        segments = viewer.available_skeleton_segments(upper_body_result())
        self.assertEqual(len(segments), len(viewer.SKELETON_SEGMENTS))

    def test_projection_helper_rejects_missing_and_preserves_metric_point(self):
        point = geometry.Point3D(.20, -.30, .80)
        before = point
        projected = viewer.axonometric_project(point)
        self.assertAlmostEqual(projected[0], -.08)
        self.assertAlmostEqual(projected[1], .156)
        self.assertEqual(point, before)
        self.assertIsNone(viewer.axonometric_project(None))

    def test_fixed_side_view_projects_depth_right_and_height_up(self):
        near = geometry.Point3D(.25, -.30, .70)
        far = geometry.Point3D(-.40, -.30, .90)
        near_before, far_before = near, far
        self.assertEqual(viewer.side_view_project(near), (.70, .30))
        self.assertEqual(viewer.side_view_project(far), (.90, .30))
        self.assertLess(
            viewer.side_view_project(near)[0],
            viewer.side_view_project(far)[0],
        )
        self.assertEqual(viewer.SIDE_CAMERA_LABEL, "<- toward camera")
        self.assertEqual((near, far), (near_before, far_before))

    def test_side_projection_consumes_existing_full_xyz_avatar_primitives(self):
        result = upper_body_result()
        before = result.as_debug_dict()
        primitives = viewer.build_avatar_primitives(result)
        projected = viewer._avatar_projection_points(
            primitives, viewer.side_view_project
        )
        self.assertEqual(
            projected["capsule:left_upper_arm:start"],
            (.80, .30),
        )
        self.assertEqual(
            primitives.arm_segments[0].start,
            geometry.Point3D(.22, -.30, .80),
        )
        self.assertIn("head:forward:positive", projected)
        self.assertEqual(result.as_debug_dict(), before)

    def test_renderers_work_without_hardware_and_do_not_mutate_geometry(self):
        result = upper_body_result()
        before = result.as_debug_dict()
        skeleton = viewer.render_upper_body_skeleton(result, size=(420, 480))
        sagittal = viewer.render_sagittal_view(result, size=(420, 480))
        avatar = viewer.render_avatar_view(result, size=(420, 480))
        side = viewer.render_side_avatar_view(result, size=(520, 480))
        combined = viewer.render_views(result, panel_size=(420, 480))
        self.assertEqual(skeleton.shape, (480, 420, 3))
        self.assertEqual(sagittal.shape, (480, 420, 3))
        self.assertEqual(avatar.shape, (480, 420, 3))
        self.assertEqual(side.shape, (480, 520, 3))
        self.assertEqual(combined.shape, (480, 840, 3))
        self.assertTrue(skeleton.any())
        self.assertTrue(sagittal.any())
        self.assertTrue(avatar.any())
        self.assertTrue(side.any())
        self.assertEqual(result.as_debug_dict(), before)

    def test_primary_side_view_and_debug_views_are_available(self):
        result = upper_body_result()
        panel_size = (360, 400)
        original = viewer.render_views(result, panel_size=panel_size)
        expected = np.hstack((
            viewer.render_upper_body_skeleton(result, size=panel_size),
            viewer.render_sagittal_view(result, size=panel_size),
        ))
        self.assertTrue(np.array_equal(original, expected))
        self.assertTrue(np.array_equal(
            viewer.render_selected_views(result, "skeleton", panel_size=panel_size),
            original,
        ))
        self.assertEqual(
            viewer.render_selected_views(result, "side", panel_size=panel_size).shape,
            (400, 360, 3),
        )
        self.assertEqual(
            viewer.render_selected_views(result, "avatar", panel_size=panel_size).shape,
            (400, 720, 3),
        )
        self.assertEqual(
            viewer.render_selected_views(result, "all", panel_size=panel_size).shape,
            (400, 1080, 3),
        )
        self.assertTrue(np.array_equal(
            viewer.render_selected_views(result, "debug", panel_size=panel_size),
            viewer.render_selected_views(result, "all", panel_size=panel_size),
        ))
        with self.assertRaises(ValueError):
            viewer.render_selected_views(result, "unknown", panel_size=panel_size)

    def test_renderer_handles_no_available_3d_points(self):
        missing = tuple(geometry.UPPER_BODY_3D_POINT_NAMES)
        result = upper_body_result(missing_3d=missing)
        self.assertEqual(viewer.available_skeleton_segments(result), ())
        self.assertTrue(all(value is None for value in viewer.sagittal_points(result).values()))
        image = viewer.render_views(result, panel_size=(360, 400))
        self.assertEqual(image.shape, (400, 720, 3))
        avatar = viewer.build_avatar_primitives(result)
        self.assertIsNone(avatar.head)
        self.assertIsNone(avatar.neck)
        self.assertIsNone(avatar.torso)
        self.assertIsNone(avatar.pelvis)
        self.assertEqual(avatar.arm_segments, ())
        self.assertEqual(avatar.joints, ())
        self.assertEqual(
            viewer.render_avatar_view(result, size=(360, 400)).shape,
            (400, 360, 3),
        )
        self.assertEqual(
            viewer.render_side_avatar_view(result, size=(500, 400)).shape,
            (400, 500, 3),
        )


if __name__ == "__main__":
    unittest.main()

