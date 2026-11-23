"""Synthetic coverage for the experimental schedule, injection and delay scoring."""

from types import SimpleNamespace
import unittest

import numpy as np

from adaptive_v2_replay import AdaptiveV2Gate, HoldProgress
from research_b_motion_delay import ANNOTATION_FORMAT, DETECTOR_FORMAT, evaluate_delays
from research_b_robustness_replay import DepthFaultInjection, Uniform85Gate, loss_schedules


RGB = np.zeros((48, 64, 3), dtype=np.uint8)


class UniformScheduleTests(unittest.TestCase):
    def test_exactly_85_time_slots_at_15_fps_independent_of_rgb_and_validity(self):
        gate = Uniform85Gate()
        valid = Uniform85Gate()
        calls = []
        for i in range(150):
            now = 67.0*i
            a = gate.select(RGB, now, i+1, HoldProgress(10000., i, 0))
            b = valid.select(np.full_like(RGB, (i%2)*255), now, i+1, HoldProgress(10000., i, i))
            self.assertEqual(a['full'], b['full'])
            if a['full']:
                calls.append(a['uniform_slot'])
                gate.completed(now, i+1, False)
                valid.completed(now, i+1, True)
        self.assertEqual(calls, list(range(85)))

    def test_no_backfill_and_new_hold_restarts_slot_zero(self):
        gate = Uniform85Gate()
        hold = HoldProgress(10000., 0, 0)
        self.assertTrue(gate.select(RGB, 0., 1, hold)['full'])
        self.assertTrue(gate.select(RGB, 800., 2, hold)['full'])
        self.assertFalse(gate.select(RGB, 810., 3, hold)['full'])
        next_hold = HoldProgress(21000., 0, 0)
        self.assertEqual(gate.select(RGB, 11000., 4, next_hold)['uniform_slot'], 0)

    def test_idle_uses_original_v2_rule_when_input_history_is_same(self):
        a, b = Uniform85Gate(), AdaptiveV2Gate()
        for i, stamp in enumerate((0., 200., 500., 700., 1000.), 1):
            aa, bb = a.select(RGB, stamp, i), b.select(RGB, stamp, i)
            self.assertEqual((aa['full'], aa['reason']), (bb['full'], bb['reason']))
            if aa['full']:
                a.completed(stamp, i, True)
                b.completed(stamp, i, True)


class SyntheticDepthTests(unittest.TestCase):
    def test_seeded_masks_only_use_original_hold_frames_and_burst_is_consecutive(self):
        stamps = [67.0*i for i in range(350)]
        starts = [stamps[4], stamps[160]]
        masks = loss_schedules(stamps, starts)
        self.assertEqual(masks, loss_schedules(stamps, starts))
        self.assertEqual(masks['none'], [])
        for start in starts:
            random = [t for t in masks['random'] if start <= t < start+10000]
            burst = [t for t in masks['burst'] if start <= t < start+10000]
            self.assertEqual(len(set(random)), 8)
            self.assertEqual(len(burst), 24)
            self.assertTrue(all(b-a==67 for a,b in zip(burst, burst[1:])))
        self.assertTrue(set(masks['random']+masks['burst']).issubset(stamps))

    def test_injection_affects_real_depth_consumers_and_preserves_original_buffer(self):
        injection = DepthFaultInjection([100.0, 200.0])
        depth = np.ones((4,4), dtype=np.uint16)

        def landmarks(*args, aligned_depth=None):
            return aligned_depth

        def chest(left, right, aligned_depth, scale):
            return aligned_depth

        fake = SimpleNamespace(points_from_pose_landmarks=landmarks,
                               points_from_face_landmarks=landmarks, sample_hipless_chest_roi=chest)
        scheduled_only, applied, good = {}, {}, {}
        with injection.hook(fake):
            injection.begin_input(scheduled_only, 100.)
            self.assertTrue(scheduled_only['synthetic_depth_fault_scheduled'])
            self.assertFalse(scheduled_only['synthetic_depth_fault_applied'])
            injection.begin_input(applied, 200.)
            blank = fake.points_from_pose_landmarks([], aligned_depth=depth)
            self.assertIs(blank, fake.points_from_face_landmarks([], aligned_depth=depth))
            self.assertIs(blank, fake.sample_hipless_chest_roi(None, None, depth, .001))
            self.assertFalse(blank.any())
            self.assertFalse(blank.flags.writeable)
            self.assertTrue(applied['synthetic_depth_fault_applied'])
            injection.begin_input(good, 300.)
            self.assertIs(fake.points_from_pose_landmarks([], aligned_depth=depth), depth)
        self.assertTrue(depth.all())
        self.assertIs(fake.sample_hipless_chest_roi, chest)


class MotionDelayTests(unittest.TestCase):
    def setUp(self):
        self.index = {i: dict(sha256=str(i), frameset_timestamp_ms=100.*i) for i in range(1,7)}
        self.annotation = dict(format=ANNOTATION_FORMAT, source_index_sha256='index',
            transitions=[dict(id='motion', status='MANUAL_REVIEW_CONFIRMED', reviewer='reviewer',
                              reviewed_at='2026-11-19', start=self.ref(2), search_end=self.ref(5))])

    def ref(self, i):
        return dict(frame_index=i, timestamp_ms=100.*i, frame_sha256=str(i))

    def detector(self, method, frames):
        return dict(format=DETECTOR_FORMAT, source_index_sha256='index', detector_id='same:1',
                    method=method, events=[self.ref(i) for i in frames])

    def evaluate(self, documents):
        return evaluate_delays(self.annotation, documents, source_index_sha256='index', index=self.index)

    def test_scores_first_causal_report_retains_misses_and_unmatched_events(self):
        result = self.evaluate([self.detector('fixed', [1,3,4]), self.detector('v2', [5])])
        self.assertEqual(result['methods']['fixed']['transitions'][0]['delay_ms'], 100.)
        self.assertEqual(result['methods']['fixed']['unmatched_event_frames'], [1,4])
        self.assertEqual(result['methods']['v2']['transitions'][0]['status'], 'MISSED')
        self.assertIsNone(result['methods']['v2']['median_detected_only_ms'])

    def test_refuses_unverified_annotations_or_different_detector_or_source_time(self):
        outputs = [self.detector('fixed', [3]), self.detector('v2', [4])]
        self.annotation['transitions'][0]['status'] = 'UNVERIFIED'
        with self.assertRaisesRegex(ValueError, 'human approval'):
            self.evaluate(outputs)
        self.annotation['transitions'][0]['status'] = 'MANUAL_REVIEW_CONFIRMED'
        outputs[1]['detector_id'] = 'different:2'
        with self.assertRaisesRegex(ValueError, 'Incompatible detector'):
            self.evaluate(outputs)
        outputs[1]['detector_id'] = 'same:1'
        outputs[1]['events'][0]['timestamp_ms'] += 1
        with self.assertRaisesRegex(ValueError, 'original frame'):
            self.evaluate(outputs)
