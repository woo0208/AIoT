"""Causal Uniform-85 control and temporary aligned-depth fault injection."""

from contextlib import ExitStack, contextmanager, wraps
import math
import random
import time
from unittest.mock import patch

import numpy as np

import e0_replay
from adaptive_v2_replay import adaptive_v2_hook
from e0_fs3 import WINDOW_MS
from replay_policy import counter_delta, cpu_counters
from research_b_fair_replay import MatchedIdleFixed2Gate


UNIFORM_TARGET = 85
FAULTS = ('none', 'random', 'burst')
RANDOM_FRAMES = 8
BURST_FRAMES = 24
LOSS_SEEDS = {'random': 20261119, 'burst': 20261120}


class Uniform85Gate(MatchedIdleFixed2Gate):
    """Process the first available input in each of 85 source-time slots."""

    def __init__(self):
        super().__init__()
        self.hold_end = None
        self.last_slot = -1

    def config(self):
        return dict(super().config(), method='Uniform', interval=None, policy='Uniform-85',
                    hold_schedule='first available input in each of 85 equal half-open time slots')

    def invalidate(self):
        super().invalidate()
        self.hold_end = None
        self.last_slot = -1

    def select(self, rgb, stamp, index, hold=None):
        if hold is None:
            return super().select(rgb, stamp, index)
        start, cpu = time.perf_counter_ns(), cpu_counters()
        if hold.end_ms != self.hold_end:
            self.hold_end, self.last_slot = hold.end_ms, -1
        elapsed = stamp - (hold.end_ms - WINDOW_MS)
        if not 0 <= elapsed < WINDOW_MS:
            raise ValueError('Uniform schedule received an input outside its current hold')
        slot = math.floor(elapsed * UNIFORM_TARGET / WINDOW_MS)
        full = slot > self.last_slot
        self.last_slot = slot
        self.previous_stamp = stamp
        age = stamp - self.last_full_ms if self.last_full_ms is not None else None
        if full:
            # Preserve the inherited idle RGB reference on actual full inputs.
            h, w = rgb.shape[:2]
            self.sample = rgb[::max(1, math.ceil(h / 36)), ::max(1, math.ceil(w / 64))].astype(np.float32)
        status = ('FULL' if full else 'HELD' if self.valid is True and age is not None
                  and age <= self.stale_ms else 'STALE')
        self.counts[status] += 1
        return dict(full=full, reason='UNIFORM_SLOT' if full else 'WAIT_UNIFORM_SLOT',
                    measurement_status=status, rgb_change=None, age_since_full_ms=age,
                    last_full_input_index=self.last_full_index, uniform_slot=slot,
                    gate_wall_ns=time.perf_counter_ns()-start, gate_cpu=counter_delta(cpu, cpu_counters()))


@contextmanager
def uniform85_hook():
    with adaptive_v2_hook(continuous_face=True):
        base = e0_replay.ReplayInput

        class UniformInput(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.gate = Uniform85Gate()

        with patch.object(e0_replay, 'ReplayInput', UniformInput):
            yield


def loss_schedules(stamps, starts):
    """Build masks once from the original time axis and policy-independent Starts."""
    output = {name: [] for name in FAULTS}
    rng = {name: random.Random(seed) for name, seed in LOSS_SEEDS.items()}
    for start in starts:
        inputs = [stamp for stamp in stamps if start <= stamp < start + WINDOW_MS]
        if len(inputs) < BURST_FRAMES:
            raise ValueError('Insufficient inputs for the predeclared fault workload')
        output['random'].extend(sorted(rng['random'].sample(inputs, RANDOM_FRAMES)))
        i = rng['burst'].randrange(len(inputs) - BURST_FRAMES + 1)
        output['burst'].extend(inputs[i:i+BURST_FRAMES])
    return output


class DepthFaultInjection:
    """Feed an all-zero aligned depth view to original depth sampling on marked inputs."""

    def __init__(self, stamps):
        self.stamps = frozenset(stamps)
        self.current = None
        self.blank = None

    def begin_input(self, row, stamp):
        self.current = row
        row.update(synthetic_depth_fault_scheduled=stamp in self.stamps, synthetic_depth_fault_applied=False)

    def substitute(self, depth):
        if (self.current is None or not self.current['synthetic_depth_fault_scheduled'] or depth is None):
            return depth
        if self.blank is None or self.blank.shape != depth.shape or self.blank.dtype != depth.dtype:
            self.blank = np.zeros_like(depth)
            self.blank.flags.writeable = False
        self.current['synthetic_depth_fault_applied'] = True
        return self.blank

    @contextmanager
    def hook(self, geometry):
        def landmark_sampler(original):
            @wraps(original)
            def call(*args, aligned_depth=None, **kwargs):
                return original(*args, aligned_depth=self.substitute(aligned_depth), **kwargs)
            return call

        chest = geometry.sample_hipless_chest_roi

        @wraps(chest)
        def chest_sampler(left, right, depth, scale):
            return chest(left, right, self.substitute(depth), scale)

        with ExitStack() as stack:
            for name in ('points_from_pose_landmarks', 'points_from_face_landmarks'):
                stack.enter_context(patch.object(geometry, name, landmark_sampler(getattr(geometry, name))))
            stack.enter_context(patch.object(geometry, 'sample_hipless_chest_roi', chest_sampler))
            yield
