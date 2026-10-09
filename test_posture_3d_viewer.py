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


class ViewerHelperTests(unittest.TestCase):
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

    def test_renderers_work_without_hardware_and_do_not_mutate_geometry(self):
        result = upper_body_result()
        before = result.as_debug_dict()
        skeleton = viewer.render_upper_body_skeleton(result, size=(420, 480))
        sagittal = viewer.render_sagittal_view(result, size=(420, 480))
        combined = viewer.render_views(result, panel_size=(420, 480))
        self.assertEqual(skeleton.shape, (480, 420, 3))
        self.assertEqual(sagittal.shape, (480, 420, 3))
        self.assertEqual(combined.shape, (480, 840, 3))
        self.assertTrue(skeleton.any())
        self.assertTrue(sagittal.any())
        self.assertEqual(result.as_debug_dict(), before)

    def test_renderer_handles_no_available_3d_points(self):
        missing = tuple(geometry.UPPER_BODY_3D_POINT_NAMES)
        result = upper_body_result(missing_3d=missing)
        self.assertEqual(viewer.available_skeleton_segments(result), ())
        self.assertTrue(all(value is None for value in viewer.sagittal_points(result).values()))
        image = viewer.render_views(result, panel_size=(360, 400))
        self.assertEqual(image.shape, (400, 720, 3))


if __name__ == "__main__":
    unittest.main()

