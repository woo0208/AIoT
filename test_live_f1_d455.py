"""Synthetic structural tests only; no camera, recordings or research results."""

import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

import f1_features
import live_f1_d455 as live


def detection(x=600, y=160, width=80, height=80):
    return NS(bounding_box=NS(origin_x=x, origin_y=y, width=width, height=height))


def observations():
    landmarks = [None] * 25
    for index, x, y in ((11, 740, 400), (12, 540, 400),
                        (23, 710, 650), (24, 570, 650)):
        landmarks[index] = NS(x=x / 1280, y=y / 720, visibility=0.0, presence=0.0)
    return NS(detections=[detection()]), NS(pose_landmarks=[landmarks])


class LiveInputTests(unittest.TestCase):
    def test_existing_core_receives_original_pixels_and_subject_sides(self):
        face, pose = observations()
        row = live.f1_frame_input(face, pose, 1280, 720)
        self.assertEqual((row['lsh_x'], row['rsh_x']), (740, 540))
        result = f1_features.compute_f1_5_frame(row)
        self.assertEqual(result.ordered_values(), (0.0, -1.0, 0.0, -1.25, 0.0))
        # Zero visibility/presence must not become new rejection thresholds.
        self.assertTrue(all(result.family_available.values()))

    def test_largest_bbox_ties_keep_first_and_face_has_no_bounds_gate(self):
        face, pose = observations()
        outside = detection(x=-200, y=100, width=100, height=100)
        face.detections.extend([outside, detection(x=900, width=100, height=100)])
        row = live.f1_frame_input(face, pose, 1280, 720)
        self.assertEqual(row['face_x'], -150)
        result = f1_features.compute_f1_5_frame(row)
        self.assertTrue(result.family_available['FS'])
        image = live.draw_preview(np.zeros((720, 1280, 3), np.uint8), row, result)
        self.assertEqual(image.shape[1], 1900)

    def test_missing_face_does_not_disable_other_families(self):
        _, pose = observations()
        result = f1_features.compute_f1_5_frame(live.f1_frame_input(None, pose, 1280, 720))
        self.assertEqual(dict(result.family_available), {'FS': False, 'SH': True, 'SO': True})
        self.assertIn('N/A', live.feature_lines(result)[0])

    def test_invalid_hip_is_empty_without_disabling_fs_so(self):
        for bad in (-0.01, 1.0, math.nan, math.inf):
            with self.subTest(x=bad):
                face, pose = observations()
                pose.pose_landmarks[0][23].x = bad
                row = live.f1_frame_input(face, pose, 1280, 720)
                self.assertFalse(row['left_hip_valid'])
                self.assertIsNone(row['left_hip_x_px'])
                result = f1_features.compute_f1_5_frame(row)
                self.assertEqual(dict(result.family_available), {'FS': True, 'SH': False, 'SO': True})
                self.assertIn('  left_hip_valid:false', live.diagnostic_lines(row, result))

    def test_invalid_shoulder_numeric_is_retained_but_never_used(self):
        for bad in (-0.01, 1.0, math.nan, math.inf):
            with self.subTest(x=bad):
                face, pose = observations()
                pose.pose_landmarks[0][11].x = bad
                row = live.f1_frame_input(face, pose, 1280, 720)
                self.assertFalse(row['lsh_valid'])
                self.assertIsNotNone(row['lsh_x'])
                result = f1_features.compute_f1_5_frame(row)
                self.assertEqual(result.ordered_values(), (None,) * 5)
                live.draw_preview(np.zeros((720, 1280, 3), np.uint8), row, result)

    def test_missing_and_truncated_pose_and_zero_shoulder_width(self):
        face, pose = observations()
        for missing in (None, NS(pose_landmarks=[]), NS(pose_landmarks=[[None]])):
            row = live.f1_frame_input(face, missing, 1280, 720)
            self.assertEqual(f1_features.compute_f1_5_frame(row).ordered_values(), (None,) * 5)
        pose.pose_landmarks[0][12] = pose.pose_landmarks[0][11]
        result = f1_features.compute_f1_5_frame(live.f1_frame_input(face, pose, 1280, 720))
        self.assertEqual(result.ordered_values(), (None,) * 5)
        self.assertIn('d_sh:zero', result.family_reasons['SO'])

    def test_current_frame_3d_tilts_and_side_view_remain_non_f2(self):
        import posture_3d_viewer

        _, pose = observations()

        class FakeRS:
            @staticmethod
            def rs2_deproject_pixel_to_point(_intrinsics, pixel, depth):
                return [pixel[0] / 1000, pixel[1] / 1000, depth]

        geometry = live.current_geometry(
            pose,
            np.zeros((720, 1280, 3), np.uint8),
            np.full((720, 1280), 1000, np.uint16),
            .001,
            NS(fx=1000.),
            FakeRS,
        )
        self.assertEqual(geometry.features['sagittal_torso_lean_deg'], 0.)
        self.assertEqual(geometry.features['shoulder_tilt_deg'], 0.)
        lines = live.geometry_lines(geometry)
        self.assertIn('NOT APPROVED F2', lines[0])
        self.assertIn('no personal calibration', lines[-1])
        self.assertEqual(
            posture_3d_viewer.render_side_avatar_view(geometry).shape,
            (760, 900, 3),
        )


class LiveRuntimeTests(unittest.TestCase):
    def test_model_loading_verifies_only_existing_face_pose(self):
        import analyze_d455 as canonical
        with patch.object(canonical, 'verify_model_artifact') as verify, \
                patch.object(canonical, 'ensure_models') as provision:
            paths = live.verified_model_paths(Path('models'))
        self.assertEqual(set(paths), {'face', 'pose'})
        self.assertEqual(verify.call_count, 2)
        provision.assert_not_called()

    def test_missing_model_fails_without_provisioning(self):
        import analyze_d455 as canonical
        with patch.object(canonical, 'verify_model_artifact', side_effect=OSError('missing')), \
                patch.object(canonical, 'ensure_models') as provision:
            with self.assertRaises(OSError):
                live.verified_model_paths(Path('missing-model-dir'))
        provision.assert_not_called()

    def test_same_image_monotonic_time_and_no_stale_values_after_missing_frame(self):
        import cv2
        face, pose = observations()
        camera = MagicMock()
        color = NS(get_data=lambda: np.zeros((720, 1280, 3), np.uint8))
        camera.wait_for_frames.side_effect = [NS(get_color_frame=lambda: color),
                                              NS(get_color_frame=lambda: color),
                                              NS(get_color_frame=lambda: None)]
        face_detector = MagicMock()
        face_detector.detect.return_value = face
        pose_detector = MagicMock()
        pose_detector.detect_for_video.return_value = pose
        with patch.object(cv2, 'imshow'), patch.object(cv2, 'waitKey', side_effect=[-1, -1, ord('q')]), \
                patch.object(cv2, 'getWindowProperty', return_value=1), \
                patch.object(live.time, 'monotonic_ns', return_value=1000000), \
                patch.object(live, 'draw_preview', return_value=np.zeros((1, 1, 3), np.uint8)) as draw:
            live.preview_loop(camera, face_detector, pose_detector)
        self.assertEqual(face_detector.detect.call_count, 2)
        for face_call, pose_call in zip(face_detector.detect.call_args_list,
                                        pose_detector.detect_for_video.call_args_list):
            self.assertIs(face_call.args[0], pose_call.args[0])
        self.assertEqual([call.args[1] for call in pose_detector.detect_for_video.call_args_list], [1, 2])
        self.assertEqual(draw.call_args.args[2].ordered_values(), (None,) * 5)
        self.assertTrue(draw.call_args.kwargs['color_missing'])

    def test_camera_and_detectors_released_on_inference_failure(self):
        import cv2
        import pyrealsense2 as rs
        from mediapipe.tasks.python import vision
        device = NS(get_info=lambda key: 'Intel RealSense D455' if key == rs.camera_info.name else 'test')
        context = NS(query_devices=lambda: [device])
        pipeline, config = MagicMock(), MagicMock()
        with patch.object(live, 'verified_model_paths', return_value={'face': 'face', 'pose': 'pose'}), \
                patch.object(rs, 'context', return_value=context), \
                patch.object(rs, 'pipeline', return_value=pipeline), \
                patch.object(rs, 'config', return_value=config), \
                patch.object(vision.FaceDetector, 'create_from_options') as face, \
                patch.object(vision.PoseLandmarker, 'create_from_options') as pose, \
                patch.object(cv2, 'namedWindow'), patch.object(cv2, 'resizeWindow'), \
                patch.object(cv2, 'destroyWindow') as close, \
                patch.object(live, 'preview_loop', side_effect=RuntimeError('inference failed')):
            with self.assertRaisesRegex(RuntimeError, 'inference failed'):
                live.run_preview(Path('models'))
        pipeline.stop.assert_called_once()
        face.return_value.__exit__.assert_called_once()
        pose.return_value.__exit__.assert_called_once()
        self.assertCountEqual(
            [call.args for call in close.call_args_list],
            [(live.WINDOW,), (live.SIDE_WINDOW,)],
        )
        self.assertEqual(
            [call.args for call in config.enable_stream.call_args_list],
            [
                (rs.stream.depth, 848, 480, rs.format.z16, 30),
                (rs.stream.color, 1280, 720, rs.format.bgr8, 30),
            ],
        )
        config.enable_record_to_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
