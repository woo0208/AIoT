"""Opt-in, causal H9 scheduling for the offline Research B Replay."""

from contextlib import contextmanager
from dataclasses import dataclass
from collections import deque
import math
from statistics import median
import time
from unittest.mock import patch

import numpy as np

import e0_replay
from e0_fs3 import WINDOW_MS
from f1_sample_aggregator import H_MIN_COVERAGE, H_MIN_VALID_FRAMES
from face_recovery_replay import face_recovery_hook
from replay_policy import ReplayGate, counter_delta, cpu_counters


@dataclass(frozen=True)
class HoldProgress:
    end_ms: float
    observed: int
    valid: int


class AdaptiveV2Gate(ReplayGate):
    """Schedule actual full measurements using the current hold and past clocks."""

    def __init__(self, target_valid=85, *, continuous_face=True):
        super().__init__('Adaptive')
        if type(target_valid) is not int or target_valid < H_MIN_VALID_FRAMES:
            raise ValueError('Expected an integer scheduling target at least as large as the H9 minimum')
        self.target_valid = target_valid
        self.continuous_face = continuous_face
        self.idle_max_ms = 500.0
        self.intervals = deque(maxlen=15)
        self.previous_stamp = None

    def config(self):
        return dict(super().config(), policy='Adaptive-V2', target_valid=self.target_valid,
                    continuous_face=self.continuous_face, idle_max_source_interval_ms=self.idle_max_ms,
                    cadence='median of last 15 delivered source intervals',
                    hold_goal='max(scheduling target, H9 count minimum, ceil(H9 coverage * forecast inputs))',
                    hold_inputs='actual accepted input count; skipped rows remain in the denominator')

    def invalidate(self):
        super().invalidate()
        self.intervals.clear()
        self.previous_stamp = None

    def _budget(self, stamp, hold):
        if hold is None:
            return None
        remaining_ms = hold.end_ms - stamp
        period = median(self.intervals) if self.intervals else None
        # Forecast only. The original aggregation uses the actual input count.
        remaining = max(1, math.ceil(remaining_ms / period)) if period else 1
        expected = hold.observed + remaining
        goal = max(self.target_valid, H_MIN_VALID_FRAMES, math.ceil(H_MIN_COVERAGE * expected))
        due = math.ceil(goal * (hold.observed + 1) / expected)
        return dict(remaining_ms=remaining_ms, estimated_remaining_including_current=remaining,
                    observed_before=hold.observed, valid_before=hold.valid, schedule_goal=goal,
                    due_after_current=due, deficit=goal - hold.valid, period_ms=period)

    def _decision(self, change, age, budget):
        if self.last_full_ms is None:
            return True, 'FIRST_OR_RESET'
        if change is None:
            return True, 'RGB_REFERENCE_UNAVAILABLE'
        if change >= self.threshold:
            return True, 'RGB_CHANGE'
        if budget is None:
            return ((True, 'IDLE_MAX_SOURCE_INTERVAL') if age >= self.idle_max_ms
                    else (False, 'IDLE_LOW_CHANGE'))
        if budget['deficit'] <= 0:
            return False, 'HOLD_GOAL_MET'
        if self.valid is False:
            return True, 'HOLD_PRIOR_INVALID'
        if budget['deficit'] >= budget['estimated_remaining_including_current']:
            return True, 'HOLD_DEADLINE'
        if budget['valid_before'] < budget['due_after_current']:
            return True, 'HOLD_BEHIND_PACE'
        if age >= self.max_ms:
            return True, 'HOLD_MAX_SOURCE_INTERVAL'
        return False, 'HOLD_ON_PACE'

    def select(self, rgb, stamp, index, hold=None):
        start, before = time.perf_counter_ns(), cpu_counters()
        if self.previous_stamp is not None:
            if stamp <= self.previous_stamp:
                raise ValueError('Adaptive-V2 source timestamp must increase')
            self.intervals.append(stamp - self.previous_stamp)
        self.previous_stamp = stamp
        h, w = rgb.shape[:2]
        self.sample = rgb[::max(1, math.ceil(h / 36)), ::max(1, math.ceil(w / 64))].astype(np.float32)
        change = (float(np.mean(np.abs(self.sample - self.reference))) / 255.
                  if self.reference is not None and self.reference.shape == self.sample.shape else None)
        age = stamp - self.last_full_ms if self.last_full_ms is not None else None
        budget = self._budget(stamp, hold)
        full, reason = self._decision(change, age, budget)
        status = 'FULL' if full else 'HELD' if self.valid is True and age <= self.stale_ms else 'STALE'
        self.counts[status] += 1
        delta = counter_delta(before, cpu_counters())
        return dict(full=full, reason=reason, measurement_status=status, rgb_change=change,
            age_since_full_ms=age, last_full_input_index=self.last_full_index,
            gate_wall_ns=time.perf_counter_ns() - start, gate_cpu=delta, hold_budget=budget)


@contextmanager
def adaptive_v2_hook(*, target_valid=85, continuous_face=True):
    """Reuse the Step 2 Face adapter and connect the scheduler to original H9 holds."""
    mode = 'continuous_face' if continuous_face else 'baseline'
    with face_recovery_hook(mode):
        base_input = e0_replay.ReplayInput

        class AdaptiveV2Input(base_input):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if self.gate.method != 'Adaptive':
                    raise ValueError('Use method=Adaptive for the Adaptive-V2 experiment')
                self.gate = AdaptiveV2Gate(target_valid, continuous_face=continuous_face)
                self.hold_start = None
                self.hold_valid = 0

            def validate(self, session, row):
                self.hold_session = session
                return super().validate(session, row)

            def select_full(self):
                session = self.hold_session
                stamp = self.frames.get_timestamp()
                start = end = None
                if session.armed:
                    start, end = stamp, stamp + WINDOW_MS
                elif session.active is not None and stamp < session.active['window_end_device_ms']:
                    start = session.active['first_device_ms']
                    end = session.active['window_end_device_ms']
                if start != self.hold_start:
                    self.hold_start, self.hold_valid = start, 0
                hold = HoldProgress(end, len(session.records), self.hold_valid) if end is not None else None
                self.current['gate'] = self.gate.select(self.rgb, stamp, self.current['input_index'], hold)
                return self.current['gate']['full']

            def completed(self, row, *, full=True):
                super().completed(row, full=full)
                if (self.hold_start is not None and full and row.get('segment_index') is not None
                        and row.get('h9_common_success')):
                    self.hold_valid += 1

        with patch.object(e0_replay, 'ReplayInput', AdaptiveV2Input):
            yield
