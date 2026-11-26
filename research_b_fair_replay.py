"""Measurement-demand drivers and a matched-idle Fixed 2 Replay control."""

from contextlib import contextmanager
import math
import time
from unittest.mock import patch

import numpy as np

import e0_replay
from adaptive_v2_replay import AdaptiveV2Gate, adaptive_v2_hook
from e0_fs3 import WINDOW_MS
from replay_policy import counter_delta, cpu_counters


class MeasurementDemand:
    """Release unlabeled Start signals at the current input; closure belongs to E0."""

    def __init__(self, mode, *, recorded_after_ms=None):
        if mode not in ('recorded_low', 'periodic_six', 'continuous'):
            raise ValueError('Unknown measurement demand')
        if mode == 'recorded_low' and recorded_after_ms is None:
            raise ValueError('Recorded demand requires its preceding receive anchor')
        self.mode = mode
        self.recorded_after_ms = recorded_after_ms
        self.first_ms = None
        self.starts = 0

    def offer(self, control, stamp):
        if self.first_ms is None:
            self.first_ms = stamp
        if control.session.armed or control.session.active is not None:
            return False
        if self.mode == 'recorded_low':
            requested = self.starts == 0 and stamp > self.recorded_after_ms
        elif self.mode == 'periodic_six':
            requested = self.starts < 6 and stamp - self.first_ms >= WINDOW_MS / 2 + 2 * WINDOW_MS * self.starts
        else:
            requested = True
        if requested and control.start():
            self.starts += 1
            return True
        return False


def measurement_phase(session, stamp):
    if session.armed:
        return 'active'
    if session.active is None:
        return 'idle'
    return 'active' if stamp < session.active['window_end_device_ms'] else 'closing'


class MatchedIdleFixed2Gate(AdaptiveV2Gate):
    """Use the original Fixed 2 input parity in holds and V2's exact idle code otherwise."""

    def config(self):
        cfg = super().config()
        for key in ('target_valid', 'hold_goal', 'hold_inputs'):
            cfg.pop(key)
        return dict(cfg, method='Fixed', interval=2, policy='Fixed 2 + matched V2 idle',
                    hold_schedule='original stream parity; no motion or budget override in hold')

    def select(self, rgb, stamp, index, hold=None):
        if hold is None:
            return super().select(rgb, stamp, index)
        start, before = time.perf_counter_ns(), cpu_counters()
        full = (index - 1) % 2 == 0
        age = stamp - self.last_full_ms if self.last_full_ms is not None else None
        self.previous_stamp = stamp
        if full:
            # Resume the idle RGB comparison from the last completed full input.
            h, w = rgb.shape[:2]
            self.sample = rgb[::max(1, math.ceil(h / 36)), ::max(1, math.ceil(w / 64))].astype(np.float32)
        status = ('FULL' if full else 'HELD' if self.valid is True and age is not None
                  and age <= self.stale_ms else 'STALE')
        self.counts[status] += 1
        delta = counter_delta(before, cpu_counters())
        return dict(full=full, reason='FIXED_PERIOD', measurement_status=status, rgb_change=None,
                    age_since_full_ms=age, last_full_input_index=self.last_full_index,
                    gate_wall_ns=time.perf_counter_ns()-start, gate_cpu=delta, hold_budget=None)


@contextmanager
def matched_idle_fixed2_hook():
    with adaptive_v2_hook(continuous_face=True):
        base_input = e0_replay.ReplayInput

        class MatchedIdleInput(base_input):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.gate = MatchedIdleFixed2Gate()

        with patch.object(e0_replay, 'ReplayInput', MatchedIdleInput):
            yield


class InputPhaseMeter:
    """Allocate process CPU across half-open read-entry intervals, including adapter and loop work."""

    def __init__(self):
        self.first_ns = None
        self.last_ns = None
        self.last_row = None

    def mark_read(self, now_ns, previous_row):
        if self.first_ns is None:
            self.first_ns = now_ns
        if self.last_row is not None and self.last_row is not previous_row:
            raise ValueError('Unexpected Replay row changed since the last read')
        if previous_row is not None:
            if self.last_ns is None or now_ns < self.last_ns:
                raise ValueError('Process CPU clock reversed')
            previous_row['phase_process_cpu_ns'] = now_ns - self.last_ns
        self.last_ns = now_ns
        self.last_row = None

    def mark_frame(self, row, phase):
        row['measurement_phase'] = phase
        self.last_row = row

    def summary(self, start_ns, end_ns):
        if not start_ns <= self.first_ns <= self.last_ns <= end_ns:
            raise ValueError('Invalid process CPU accounting boundaries')
        return dict(stream_process_cpu_ns=end_ns-start_ns,
                    before_first_read_ns=self.first_ns-start_ns, eof_and_finish_ns=end_ns-self.last_ns)
