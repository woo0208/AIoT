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
