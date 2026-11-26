"""Targeted synthetic candidate safety tests; no device/model fitting."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np

import adaptive_guarded_replay as candidate
from replay_policy import ReplayGate
import test_e0_replay as fixtures
from test_h9_probe_integration import SyntheticProbe
from test_e0_fs3 import estimators
from e0_fs3 import E0Session
import posture_geometry_probe as probe


class BudgetTests(unittest.TestCase):
    def test_stable_budget_has_margin_in_every_150_input_window(self):
        gate = candidate.GuardedAdaptiveGate()
        rgb = np.zeros((36, 64, 3), np.uint8)
        calls = []
        for i in range(1, 401):
            d = gate.select(rgb, i * 66.7, i)
            calls.append(d['full'])
            if d['full']:
                gate.completed(i * 66.7, i, True)
                gate.face_valid = True
        self.assertEqual(sum(calls), 300)
        self.assertGreaterEqual(min(sum(calls[i:i+150]) for i in range(251)), 112)
        self.assertEqual(gate.counts['FULL'], 300)
        self.assertEqual(gate.counts['HELD'], 100)

    def test_motion_and_invalid_observation_override_skip_slot(self):
        rgb = np.zeros((36, 64, 3), np.uint8)
        for failure in ('motion', 'h9', 'face'):
            with self.subTest(failure=failure):
                g = candidate.GuardedAdaptiveGate()
                g.select(rgb, 0., 3); g.completed(0., 3, failure != 'h9')
                g.face_valid = failure != 'face'
                d = g.select(rgb + (255 if failure == 'motion' else 0), 66., 4)
                self.assertTrue(d['full'])
                self.assertIn(d['reason'], ('RGB_CHANGE', 'PRIOR_OBSERVATION_INVALID', 'FACE_RECOVERY_FULL'))

    def test_reset_and_missing_confidence_safe(self):
        g = candidate.GuardedAdaptiveGate(); rgb = np.zeros((36, 64, 3), np.uint8)
        g.select(rgb, 0., 1);g.completed(0., 1, True);g.face_valid = False
        g.invalidate()
        self.assertTrue(g.select(rgb, 66., 4)['full'])
        self.assertIsNone(g.face_valid)
        self.assertEqual(g.config()['svm_confidence'], 'NOT_AVAILABLE_probability_false')

    def test_original_adaptive_schedule_unchanged(self):
        g = ReplayGate('Adaptive'); rgb = np.zeros((36, 64, 3), np.uint8)
        g.select(rgb, 0., 1);g.completed(0., 1, True)
        self.assertFalse(g.select(rgb, 66., 2)['full'])


class GuardedIntegration(unittest.TestCase):
    setUp = fixtures.ReplayContracts.setUp

    def run_candidate(self, *, fail_on_skip=False):
        stamps = list(range(0, 10100, 100))
        fake = SyntheticProbe(self, stamps)
        fake.face.detect_for_video.return_value = NS(face_landmarks=[[]])
        self.enterContext(patch('e0_replay.db3_packets', return_value=(
            fixtures.packet(i, t) for i,t in enumerate(stamps, 1))))
        r = candidate.GuardedReplayInput(self.source, arm_at_first_frame=True)
        self.enterContext(patch.object(r, 'locked_models', return_value=dict(pose='fake',mesh='fake')))
        self.enterContext(patch.object(r, 'color_intrinsics', return_value=NS(fx=100.)))
        session = E0Session(self.root/'run', *estimators(), clock_ns=fake.clock,
                            input_scope='raw_replay', synthetic=True)
        self.enterContext(patch.object(session.model, 'predict', return_value=np.asarray([0])))
        original = probe.run_frame_inference
        self.enterContext(patch.object(probe, 'run_frame_inference',
                                      candidate.inference_bridge(r, original)))
        if fail_on_skip:
            def infer(image, stamp):
                if stamp == 300:
                    raise RuntimeError('tracking-only failure')
                return NS(face_landmarks=[[]])
            fake.face.detect_for_video.side_effect = infer
        return fake, r, session

    def test_face_every_input_skip_is_not_a_fresh_H9_feature(self):
        fake,r,s = self.run_candidate()
        probe.run_probe(e0_session=s, replay_input=r, headless=True, show_3d_views='none')
        self.assertEqual(fake.face.detect_for_video.call_count, 101)
        self.assertEqual(fake.pose.detect_for_video.call_count, 76)
        self.assertEqual([c.args[1] for c in fake.face.detect_for_video.call_args_list], list(range(0,10100,100)))
        self.assertEqual(s.segments[0]['valid_frames'], 75)
        self.assertEqual(s.segments[0]['coverage'], .75)
        self.assertTrue(s.segments[0]['prediction_success'])
        for row in r.rows:
            if not row['full_inference']:
                self.assertFalse(row['h9_common_success'])
                self.assertNotIn('feature_vector_sha256', row)
                self.assertEqual(row['face_tracking']['role'], 'TRACKING_ONLY')
        fake.face.close.assert_called_once()

    def test_face_only_error_aborts_and_closes_original_tasks(self):
        fake,r,s = self.run_candidate(fail_on_skip=True)
        with self.assertRaisesRegex(RuntimeError, 'tracking-only failure'):
            probe.run_probe(e0_session=s, replay_input=r, headless=True, show_3d_views='none')
        fake.face.close.assert_called_once();fake.pose.close.assert_called_once()
        self.assertEqual(len(r.rows), 4)
        self.assertNotIn('feature_vector_sha256', r.rows[-1])

    def test_duplicate_timestamp_and_task_replacement_rejected(self):
        fake,r,s = self.run_candidate()
        r.check_face_input(fake.face, 1);r.last_face_stamp = 1
        with self.assertRaises(ValueError):r.check_face_input(fake.face, 1)
        with self.assertRaises(RuntimeError):r.check_face_input(object(), 2)


if __name__ == '__main__':
    unittest.main()
