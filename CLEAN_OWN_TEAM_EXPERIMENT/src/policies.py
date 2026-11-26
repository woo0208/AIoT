"""Engineering-only replay gates and read-only CPU counters; no model/feature changes."""
from collections import Counter
import ctypes
from functools import lru_cache
import math
import os
import time

import numpy as np


@lru_cache(maxsize=1)
def _windows_cpu_api():
    from ctypes import wintypes as w
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.GetCurrentProcess.restype=w.HANDLE
    api.GetCurrentThread.restype=w.HANDLE
    api.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
    api.GetProcessTimes.restype=w.BOOL
    for name in ('QueryProcessCycleTime','QueryThreadCycleTime'):
        fn=getattr(api,name);fn.argtypes=[w.HANDLE,ctypes.POINTER(ctypes.c_ulonglong)];fn.restype=w.BOOL
    return api,w


def cpu_counters():
    """Cycles are raw cycles, never converted to seconds using an assumed GHz."""
    result=dict(process_ns=time.process_time_ns(),thread_ns=time.thread_time_ns())
    if os.name!='nt':return result
    try:
        api,w=_windows_cpu_api();p=api.GetCurrentProcess()
        create,exit,kernel,user=(w.FILETIME() for _ in range(4))
        if not api.GetProcessTimes(p,ctypes.byref(create),ctypes.byref(exit),ctypes.byref(kernel),ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        ns=lambda v:((v.dwHighDateTime<<32)+v.dwLowDateTime)*100
        result.update(kernel_ns=ns(kernel),user_ns=ns(user))
        for name,handle,key in (('QueryProcessCycleTime',p,'process_cycles'),
                               ('QueryThreadCycleTime',api.GetCurrentThread(),'thread_cycles')):
            value=ctypes.c_ulonglong()
            if getattr(api,name)(handle,ctypes.byref(value)):result[key]=value.value
    except Exception as exc:result['counter_error']=type(exc).__name__
    return result


def counter_delta(before,after):
    return {key:after[key]-value for key,value in before.items()
            if type(value) is int and type(after.get(key)) is int}


class ReplayGate:
    """Defaults are untuned engineering candidates, not validated posture thresholds.

    Adaptive compares a small RGB grid to the LAST FULL observation, so slow
    cumulative changes are not erased by updating the reference on skipped input.
    No SVM probability is invented (the frozen SVC has probability=False).
    """
    def __init__(self,method='E0',*,interval=1,change_threshold=.02,max_interval_ms=200.,stale_after_ms=200.):
        if method not in ('E0','Fixed','Adaptive') or interval not in (1,2,3,5):raise ValueError('Invalid replay gate')
        for value in (change_threshold,max_interval_ms,stale_after_ms):
            if isinstance(value,bool) or not math.isfinite(value) or value<=0:raise ValueError('Invalid gate parameter')
        if change_threshold>1:raise ValueError('Normalized RGB change must be <=1')
        self.method,self.interval=method,interval
        self.threshold,self.max_ms,self.stale_ms=change_threshold,max_interval_ms,stale_after_ms
        self.last_full_ms=self.last_full_index=self.reference=self.valid=None
        self.sample=None;self.counts=Counter()

    def config(self):
        return dict(method=self.method,interval=self.interval,change_threshold=self.threshold,
            max_interval_ms=self.max_ms,stale_after_ms=self.stale_ms,rgb_grid='at most 36x64 RGB float32',
            reference='last completed full inference',quality='prior H9 joint validity only; no calibrated probability',
            svm_confidence='NOT_AVAILABLE_probability_false',status='UNTUNED_ENGINEERING_CANDIDATE')

    def invalidate(self):
        self.last_full_ms=self.last_full_index=self.reference=self.valid=None

    def select(self,rgb,stamp,index):
        start=time.perf_counter_ns();before=cpu_counters();change=None
        if self.method=='Adaptive':
            if rgb is None:raise ValueError('Adaptive gate requires current RGB')
            h,w=rgb.shape[:2]
            self.sample=rgb[::max(1,math.ceil(h/36)),::max(1,math.ceil(w/64))].astype(np.float32)
            if self.reference is not None and self.reference.shape==self.sample.shape:
                change=float(np.mean(np.abs(self.sample-self.reference)))/255.
        age=stamp-self.last_full_ms if self.last_full_ms is not None else None
        if self.last_full_ms is None:full,reason=True,'FIRST_OR_RESET'
        elif self.method=='E0':full,reason=True,'E0_FULL'
        elif self.method=='Fixed':full,reason=(index-1)%self.interval==0,'FIXED_PERIOD'
        elif self.valid is False:full,reason=True,'PRIOR_OBSERVATION_INVALID'
        elif change is None:full,reason=True,'RGB_REFERENCE_UNAVAILABLE'
        elif age>=self.max_ms:full,reason=True,'MAX_SOURCE_INTERVAL'
        elif change>=self.threshold:full,reason=True,'RGB_CHANGE'
        else:full,reason=False,'LOW_CHANGE_BOUNDED_WAIT'
        status='FULL' if full else 'HELD' if self.valid is True and age is not None and 0<=age<=self.stale_ms else 'STALE'
        delta=counter_delta(before,cpu_counters())
        result=dict(full=full,reason=reason,measurement_status=status,rgb_change=change,
            age_since_full_ms=age,last_full_input_index=self.last_full_index,
            gate_wall_ns=time.perf_counter_ns()-start,gate_cpu=delta)
        self.counts[status]+=1
        return result

    def completed(self,stamp,index,valid):
        self.last_full_ms,self.last_full_index,self.valid=stamp,index,valid
        if self.method=='Adaptive':self.reference=self.sample

from collections import deque
from dataclasses import dataclass
from statistics import median
from model_inference import WINDOW_MS
from aggregation import H_MIN_VALID_FRAMES, H_MIN_COVERAGE

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

UNIFORM_TARGET = 85

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
