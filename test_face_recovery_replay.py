"""Synthetic states for the opt-in offline Face recovery hooks."""

from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

import e0_replay
from face_recovery_replay import FaceRecovery, face_recovery_hook
import posture_geometry_probe as probe


def face_result(detected):
    return SimpleNamespace(face_landmarks=[[object()]] if detected else [])


def task(detected):
    return Mock(detect_for_video=Mock(return_value=face_result(detected)), close=Mock())


class FaceRecoveryTests(unittest.TestCase):
    def test_baseline_returns_primary_and_preserves_the_original(self):
        original = task(True)
        recovery = FaceRecovery('baseline')
        recovery.bind(original)
        primary = face_result(False)
        for stamp in (100, 200, 800):
            result, trace = recovery.observe(object(), stamp, primary, role='FULL')
            self.assertIs(result, primary)
            self.assertFalse(trace['recovery_attempt'])
            self.assertEqual(trace['operations'], [])
        recovery.close()
        original.close.assert_not_called()

    def test_reset_retries_current_frame_and_keeps_new_graph_even_if_empty(self):
        original, first, second = task(False), task(False), task(True)
        factory = Mock(side_effect=[first, second])
        recovery = FaceRecovery('reset', factory)
        recovery.bind(original)
        image, miss = object(), face_result(False)
        _, trace = recovery.observe(image, 100, miss, role='FULL')
        self.assertFalse(trace['recovery_attempt'])
        result, trace = recovery.observe(image, 200, miss, role='FULL')
        self.assertFalse(trace['detected'])
        self.assertFalse(trace['retry_detected'])
        first.detect_for_video.assert_called_once_with(image, 200)
        self.assertIs(recovery.task, first)
        _, trace = recovery.observe(image, 699, miss, role='FULL')
        self.assertFalse(trace['recovery_attempt'])
        result, trace = recovery.observe(image, 700, miss, role='FULL')
        self.assertTrue(result.face_landmarks)
        self.assertEqual(trace['primary_generation'], 1)
        self.assertEqual(trace['active_generation'], 2)
        first.close.assert_called_once()
        recovery.close()
        second.close.assert_called_once()
        original.close.assert_not_called()

    def test_blaze_detection_gate_and_failed_retry_do_not_claim_recovery(self):
        original, trial, success = task(False), task(False), task(True)
        detector = Mock(detect=Mock(side_effect=[SimpleNamespace(detections=[]),
            SimpleNamespace(detections=[object()]), SimpleNamespace(detections=[object()])]))
        factory = Mock(side_effect=[trial, success])
        recovery = FaceRecovery('redetect', factory, detector)
        recovery.bind(original)
        image, miss = object(), face_result(False)
        recovery.observe(image, 10, miss, role='FULL')
        _, trace = recovery.observe(image, 100, miss, role='FULL')
        self.assertFalse(trace['independent_detected'])
        self.assertIsNone(trace['retry_detected'])
        factory.assert_not_called()
        _, trace = recovery.observe(image, 600, miss, role='FULL')
        self.assertTrue(trace['independent_detected'])
        self.assertFalse(trace['detected'])
        self.assertIs(recovery.task, original)
        trial.close.assert_called_once()
        _, trace = recovery.observe(image, 1100, miss, role='FULL')
        self.assertTrue(trace['retry_detected'])
        self.assertIs(recovery.task, success)
        self.assertEqual(recovery.misses, 0)
        recovery.close()
        success.close.assert_called_once()

    def test_positive_primary_breaks_the_miss_streak(self):
        factory = Mock()
        recovery = FaceRecovery('reset', factory)
        for stamp, detected in ((1, False), (2, True), (3, False)):
            recovery.observe(object(), stamp, face_result(detected), role='FULL')
        factory.assert_not_called()

    def test_failed_operation_closes_trial_and_propagates_error(self):
        trial = task(False)
        trial.detect_for_video.side_effect = RuntimeError('SDK failure')
        recovery = FaceRecovery('reset', Mock(return_value=trial))
        recovery.observe(object(), 100, face_result(False), role='FULL')
        with self.assertRaisesRegex(RuntimeError, 'SDK failure'):
            recovery.observe(object(), 200, face_result(False), role='FULL')
        trial.close.assert_called_once()

    def test_non_increasing_timestamps_and_unexpected_task_change_are_rejected(self):
        recovery = FaceRecovery('continuous_face')
        recovery.bind(task(True))
        recovery.observe(object(), 100, face_result(True), role='FULL')
        with self.assertRaisesRegex(ValueError, 'increase'):
            recovery.observe(object(), 100, face_result(False), role='FACE_ONLY')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            recovery.bind(task(True))

    def test_face_only_advances_same_task_and_preserves_original_skip(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic.bag'
            path.write_bytes(b'dispatch marker')
            original_input, original_infer = e0_replay.ReplayInput, probe.run_frame_inference
            face, pose = task(True), Mock(detect_for_video=Mock(return_value=object()))
            session = SimpleNamespace(timing=SimpleNamespace(stage=lambda *_: nullcontext()))
            with patch.object(original_input, 'skipped', autospec=True) as skipped:
                with face_recovery_hook('continuous_face'):
                    replay = e0_replay.ReplayInput(path, method='Fixed', interval=2)
                    self.assertEqual(replay.gate.interval, 2)
                    replay.rgb = np.zeros((48, 64, 3), dtype=np.uint8)
                    replay.current = {}
                    probe.run_frame_inference(pose, face, object(), 100)
                    self.assertEqual(replay.current['face_experiment']['role'], 'FULL')
                    replay.current = {}
                    replay.skipped(session, {}, 2, 167.8)
                    self.assertEqual(replay.current['face_experiment']['role'], 'FACE_ONLY')
                    self.assertEqual(replay.current['face_experiment']['timestamp_ms'], 167)
                    skipped.assert_called_once_with(replay, session, {}, 2, 167.8)
                    self.assertEqual(face.detect_for_video.call_count, 2)
                    self.assertEqual(pose.detect_for_video.call_count, 1)
            self.assertIs(e0_replay.ReplayInput, original_input)
            self.assertIs(probe.run_frame_inference, original_infer)
