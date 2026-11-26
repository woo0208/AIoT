"""Causal scheduling and original H9 integration tests with synthetic inputs."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import e0_replay
import posture_geometry_probe as probe
from adaptive_v2_replay import AdaptiveV2Gate, HoldProgress, adaptive_v2_hook
from test_e0_replay import packet
from test_e0_fs3 import estimators, result
from test_h9_probe_integration import SyntheticProbe
from e0_fs3 import E0Session


RGB = np.zeros((48, 64, 3), dtype=np.uint8)


class AdaptiveV2GateTests(unittest.TestCase):
    def test_targets_allocate_full_calls_across_a_stable_hold(self):
        for target in (75, 85, 90):
            with self.subTest(target=target):
                gate = AdaptiveV2Gate(target)
                valid = 0
                gate.select(RGB, 0.0, 1)
                gate.completed(0.0, 1, True)
                for seen in range(150):
                    stamp = (seen + 1) * 67.0
                    decision = gate.select(RGB, stamp, seen + 2, HoldProgress(10067.0, seen, valid))
                    if decision['full']:
                        gate.completed(stamp, seen + 2, True)
                        valid += 1
                self.assertEqual(valid, target)
                self.assertEqual(gate.counts['HELD'] + gate.counts['STALE'], 150 - target)

    def test_missing_valid_support_and_deadline_force_actual_full_calls(self):
        gate = AdaptiveV2Gate()
        gate.select(RGB, 0., 1)
        gate.completed(0., 1, False)
        failed = gate.select(RGB, 67., 2, HoldProgress(10000., 1, 0))
        self.assertEqual(failed['reason'], 'HOLD_PRIOR_INVALID')
        self.assertEqual(failed['hold_budget']['valid_before'], 0)
        gate.completed(67., 2, True)
        late = gate.select(RGB, 9950., 3, HoldProgress(10000., 149, 70))
        self.assertEqual(late['reason'], 'HOLD_DEADLINE')

    def test_coverage_forecast_scales_with_observed_source_rate(self):
        gate = AdaptiveV2Gate(75)
        for index in range(1, 18):
            stamp = (index - 1) * 40.0
            gate.select(RGB, stamp, index)
            gate.completed(stamp, index, True)
        start = 17 * 40.0
        decision = gate.select(RGB, start, 18, HoldProgress(start + 10000, 0, 0))
        self.assertEqual(decision['hold_budget']['estimated_remaining_including_current'], 250)
        self.assertEqual(decision['hold_budget']['schedule_goal'], 125)

    def test_met_goal_saves_full_work_but_rgb_change_still_has_priority(self):
        gate = AdaptiveV2Gate(75)
        gate.select(RGB, 0., 1)
        gate.completed(0., 1, True)
        met = HoldProgress(10000., 149, 75)
        self.assertEqual(gate.select(RGB, 9933., 2, met)['reason'], 'HOLD_GOAL_MET')
        moved = gate.select(np.full_like(RGB, 255), 9966., 3, met)
        self.assertEqual((moved['full'], moved['reason']), (True, 'RGB_CHANGE'))

    def test_outside_hold_uses_bounded_heartbeat_and_can_reset_clock(self):
        gate = AdaptiveV2Gate()
        gate.select(RGB, 0., 1)
        gate.completed(0., 1, True)
        self.assertFalse(gate.select(RGB, 200., 2)['full'])
        self.assertEqual(gate.select(RGB, 500., 3)['reason'], 'IDLE_MAX_SOURCE_INTERVAL')
        gate.invalidate()
        self.assertEqual(gate.select(RGB, 1., 4)['reason'], 'FIRST_OR_RESET')


class AdaptiveV2IntegrationTests(unittest.TestCase):
    def test_original_h9_counts_only_real_full_observations_and_requires_coverage(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                root = Path(directory)
                source = root / 'synthetic.bag'
                source.write_bytes(b'synthetic')
                stamps = list(range(0, 10100, 100))
                fake = SyntheticProbe(self, stamps)
                if invalid:
                    fake.calculate.return_value = result(missing=(0,))
                session = E0Session(root/'run', *estimators(), clock_ns=fake.clock,
                                    input_scope='raw_replay', synthetic=True)
                with adaptive_v2_hook(target_valid=60, continuous_face=False), \
                        patch('e0_replay.db3_packets',
                              return_value=(packet(i, s) for i, s in enumerate(stamps, 1))), \
                        patch.object(session.model, 'predict', return_value=np.asarray([0])) as predict:
                    replay = e0_replay.ReplayInput(source, method='Adaptive', arm_at_first_frame=True)
                    with patch.object(replay, 'locked_models', return_value=dict(pose='fake', mesh='fake')), \
                            patch.object(replay, 'color_intrinsics', return_value=SimpleNamespace(fx=100.)):
                        probe.run_probe(e0_session=session, replay_input=replay, headless=True, show_3d_views='none')
                segment, = session.segments
                self.assertEqual(segment['input_frames'], 100)
                self.assertEqual(segment['end_boundary_frame_id'], 101)
                self.assertIsNone(replay.rows[-1]['gate']['hold_budget'])
                self.assertEqual(segment['valid_frames'], 0 if invalid else 60)
                self.assertEqual(predict.call_count, int(not invalid))
                self.assertTrue(all(not r.get('h9_common_success') for r in replay.rows if not r['full_inference']))
                self.assertIs(e0_replay.ReplayInput, self.original_input)

    def setUp(self):
        self.original_input = e0_replay.ReplayInput
