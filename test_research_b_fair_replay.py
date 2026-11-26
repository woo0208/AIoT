"""Synthetic contracts for operator demand, matched scheduling and CPU partition."""

from types import SimpleNamespace
import unittest

import numpy as np

from adaptive_v2_replay import AdaptiveV2Gate, HoldProgress
from e0_panel import OperatorControl
from research_b_fair_replay import InputPhaseMeter, MatchedIdleFixed2Gate, MeasurementDemand, measurement_phase


def operator():
    session = SimpleNamespace(armed=False, active=None)

    def arm():
        session.armed = True

    session.arm_segment = arm
    return OperatorControl(session)


class MeasurementDemandTests(unittest.TestCase):
    def test_releases_recorded_request_after_captured_preceding_anchor(self):
        demand = MeasurementDemand('recorded_low', recorded_after_ms=1500)
        control = operator()
        self.assertFalse(demand.offer(control, 1500))
        self.assertTrue(demand.offer(control, 1510))
        self.assertEqual(measurement_phase(control.session, 1510), 'active')
        control.session.armed = False
        self.assertFalse(demand.offer(control, 30000))

    def test_periodic_driver_uses_elapsed_time_and_limits_to_six_busy_safe_requests(self):
        control = operator()
        demand = MeasurementDemand('periodic_six')
        self.assertFalse(demand.offer(control, 2000))
        self.assertFalse(demand.offer(control, 6999))
        for n in range(6):
            stamp = 7000 + 20000*n
            self.assertTrue(demand.offer(control, stamp))
            self.assertFalse(demand.offer(control, stamp+1))
            control.session.armed = False
        self.assertFalse(demand.offer(control, 200000))

    def test_continuous_driver_never_rearms_the_closing_input(self):
        control = operator()
        demand = MeasurementDemand('continuous')
        self.assertTrue(demand.offer(control, 100))
        control.session.armed = False
        control.session.active = {'window_end_device_ms': 10100}
        self.assertEqual(measurement_phase(control.session, 10099), 'active')
        self.assertFalse(demand.offer(control, 10100))
        self.assertEqual(measurement_phase(control.session, 10100), 'closing')
        control.session.active = None
        self.assertEqual(measurement_phase(control.session, 10101), 'idle')
        self.assertTrue(demand.offer(control, 10101))


class MatchedIdleTests(unittest.TestCase):
    def test_idle_matches_original_v2_when_history_is_the_same(self):
        fixed, adaptive = MatchedIdleFixed2Gate(), AdaptiveV2Gate()
        rgb = np.zeros((48, 64, 3), dtype=np.uint8)
        changed = np.full_like(rgb, 255)
        for index, (stamp, image) in enumerate(((0, rgb), (67, rgb), (134, changed),
                                                     (500, changed), (650, changed)), 1):
            a, b = fixed.select(image, stamp, index), adaptive.select(image, stamp, index)
            for key in ('reason', 'full', 'measurement_status', 'rgb_change'):
                self.assertEqual(a[key], b[key])
            if a['full']:
                fixed.completed(stamp, index, True)
                adaptive.completed(stamp, index, True)

    def test_hold_keeps_original_parity_even_on_motion_and_carries_reference_into_idle(self):
        gate = MatchedIdleFixed2Gate()
        rgb = np.zeros((48, 64, 3), dtype=np.uint8)
        moved = np.full_like(rgb, 255)
        self.assertTrue(gate.select(rgb, 0, 1)['full'])
        gate.completed(0, 1, True)
        hold = HoldProgress(10090, 0, 0)
        self.assertFalse(gate.select(moved, 70, 2, hold)['full'])
        self.assertTrue(gate.select(moved, 140, 3, hold)['full'])
        gate.completed(140, 3, True)
        self.assertEqual(gate.select(moved, 210, 4)['reason'], 'IDLE_LOW_CHANGE')
        self.assertEqual(gate.select(rgb, 280, 5)['reason'], 'RGB_CHANGE')


class PhaseMeterTests(unittest.TestCase):
    def test_input_slots_and_residual_sum_to_stream_cpu(self):
        meter = InputPhaseMeter()
        a, b, closing = {}, {}, {}
        meter.mark_read(10, None)
        meter.mark_frame(a, 'active')
        meter.mark_read(30, a)
        meter.mark_frame(b, 'idle')
        meter.mark_read(35, b)
        meter.mark_frame(closing, 'closing')
        meter.mark_read(45, closing)
        outcome = meter.summary(8, 50)
        self.assertEqual([row['phase_process_cpu_ns'] for row in (a, b, closing)], [20, 5, 10])
        self.assertEqual(outcome, dict(stream_process_cpu_ns=42, before_first_read_ns=2, eof_and_finish_ns=5))

    def test_cpu_clock_regression_is_reported(self):
        meter = InputPhaseMeter()
        row = {}
        meter.mark_read(10, None)
        meter.mark_frame(row, 'idle')
        with self.assertRaisesRegex(ValueError, 'reversed'):
            meter.mark_read(9, row)
