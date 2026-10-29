"""Optional host-monotonic engineering timing; no camera or research evaluation."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from decimal import Decimal
import ctypes
import json
import math
import os
from pathlib import Path
import platform
import threading
import time

import numpy as np


def process_memory():
    """Current process memory, never system-wide RAM or Python allocations only."""
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                        *[(n,ctypes.c_size_t) for n in (
                            'PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage',
                            'QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage',
                            'PagefileUsage','PeakPagefileUsage','PrivateUsage')]]
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi',use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters();counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return dict(rss_bytes=counters.WorkingSetSize,private_bytes=counters.PrivateUsage,
                    os_peak_rss_bytes=counters.PeakWorkingSetSize,method='Windows GetProcessMemoryInfo')
    statm = Path('/proc/self/statm')
    if statm.is_file():
        rss = int(statm.read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        return dict(rss_bytes=rss,private_bytes=None,os_peak_rss_bytes=None,method='Linux /proc/self/statm')
    return dict(rss_bytes=None,private_bytes=None,os_peak_rss_bytes=None,method='unavailable on this platform')


def _stats(values):
    if not values:
        return dict(count=0,p50=None,p95=None,maximum=None)
    values = np.asarray(values,dtype=float)
    return dict(count=len(values),p50=float(np.percentile(values,50)),
                p95=float(np.percentile(values,95)),maximum=float(values.max()))


class ProbeRunControl:
    """Optional cooperative deadline; finish the current call and clean up normally."""

    def __init__(self,duration_seconds=None,*,clock_ns=time.monotonic_ns):
        if duration_seconds is not None and (isinstance(duration_seconds,bool)
                or not isinstance(duration_seconds,(int,float))
                or not math.isfinite(duration_seconds) or duration_seconds <= 0):
            raise ValueError('duration_seconds must be finite and positive')
        self.duration_seconds=duration_seconds
        self.duration_ns=int(Decimal(str(duration_seconds))*1_000_000_000) if duration_seconds is not None else None
        if self.duration_ns is not None and self.duration_ns < 1:
            raise ValueError('duration must be at least one nanosecond')
        self.clock_ns=clock_ns
        self.start_ns=self.stop_ns=self.reason=None

    def start(self,start_ns=None):
        self.start_ns=self.clock_ns() if start_ns is None else start_ns

    def stop(self,reason):
        if self.reason is None:
            self.reason=reason
            self.stop_ns=self.clock_ns()

    def deadline_reached(self):
        if self.start_ns is not None and self.duration_ns is not None and self.clock_ns()-self.start_ns >= self.duration_ns:
            self.stop('duration_elapsed')
            return True
        return False

    def summary(self):
        return dict(reason=self.reason or 'not_started',requested_duration_seconds=self.duration_seconds,
                    stream_start_host_monotonic_ns=self.start_ns,stop_requested_host_monotonic_ns=self.stop_ns,
                    deadline_overrun_seconds=max(0,(self.stop_ns-self.start_ns-self.duration_ns)/1e9)
                    if self.stop_ns is not None and self.start_ns is not None and self.duration_ns is not None else None)


class ProbeMetrics:
    """Thread-safe timing samples and a 1Hz process resource monitor.

    Nested stages overlap and must not be summed. FPS counts delivered SDK
    framesets/finished processing, not the camera setting or UI refresh rate.
    UI latency ends at application submission, not physical presentation.
    """

    def __init__(self, output_path, *, warmup_frames=0, h9_warmup_calls=1, clock_ns=time.monotonic_ns,
                 cpu_clock_ns=time.process_time_ns, memory_reader=process_memory, metadata=None):
        self.output_path = Path(output_path)
        if self.output_path.exists() or self.output_path.is_symlink():
            raise FileExistsError(f'refusing to overwrite timing output: {self.output_path}')
        if not self.output_path.parent.is_dir():
            raise FileNotFoundError(self.output_path.parent)
        if type(warmup_frames) is not int or warmup_frames < 0:
            raise ValueError('warmup_frames must be a nonnegative integer')
        if type(h9_warmup_calls) is not int or h9_warmup_calls < 0:
            raise ValueError('h9_warmup_calls must be a nonnegative integer')
        self.warmup_frames = warmup_frames
        self.h9_warmup_calls = h9_warmup_calls
        self.clock_ns,self.cpu_clock_ns,self.memory_reader = clock_ns,cpu_clock_ns,memory_reader
        self.metadata = dict(metadata or {})
        self._lock = threading.RLock()
        self._stages = defaultdict(list)
        self._warmup = defaultdict(list)
        self._collection = defaultdict(list)
        self._h9_calls = Counter()
        self._first_h9_prediction = self._first_h9_ui = None
        self._successful_h9_inferences = 0
        self._counts = Counter()
        self._pending = {}
        self._source_ids = set()
        self._source_unknown = False
        self._last_source_id = None
        self._resources = []
        self._last_resource = None
        self._stream_start = self._stream_end = None
        self._stop = threading.Event()
        self._thread = None
        self._finished = False

    def record_ns(self,name,duration_ns,frame_id=None,*,phase=None):
        if duration_ns < 0:
            raise ValueError('monotonic duration cannot be negative')
        if phase not in (None,'collection','warmup','steady'):
            raise ValueError('unknown timing phase')
        with self._lock:
            if phase is None:
                phase = 'warmup' if frame_id is not None and frame_id <= self.warmup_frames else 'steady'
            bucket = {'collection':self._collection,'warmup':self._warmup,'steady':self._stages}[phase]
            bucket[name].append(duration_ns/1_000_000)

    @contextmanager
    def h9_stage(self,name,*,collecting=False):
        """Partial aggregation is separate; each full stage warms independently.

        Counters are per process run, not restarted by manual window reset.
        M0 counts only real inference calls; HOLDING never consumes its warmup.
        """
        with self._lock:
            if collecting:
                phase = 'collection'
            else:
                self._h9_calls[name] += 1
                phase = 'warmup' if self._h9_calls[name] <= self.h9_warmup_calls else 'steady'
        start = self.clock_ns()
        try:
            yield
        finally:
            self.record_ns(name,self.clock_ns()-start,phase=phase)

    def h9_prediction_ready(self,row):
        """Retain first prediction availability even when its stages are warmup."""
        with self._lock:
            # Only a completed PREDICTED event counts, never a stage attempt,
            # HOLDING snapshot, UI redraw or failed RF call.
            if row['status'] != 'PREDICTED':
                raise ValueError('expected a completed H9 prediction')
            self._successful_h9_inferences += 1
            if self._first_h9_prediction is None:
                prediction = row['display_prediction']
                now = self.clock_ns()
                origin = int(Decimal(prediction['accumulation_start_host_ms'])*1_000_000)
                self._first_h9_prediction = dict(prediction_id=prediction['prediction_id'],
                    ready_host_monotonic_ns=now,source_last_input_host_ms=prediction['source_last_input_host_ms'],
                    collection_start_host_ms=prediction['accumulation_start_host_ms'],
                    collection_start_to_ready_ms=(now-origin)/1_000_000,
                    stream_start_to_ready_ms=(now-self._stream_start)/1_000_000 if self._stream_start is not None else None)

    def h9_ui_submitted(self,prediction,now):
        """First displayed prediction may differ from the first generated one."""
        with self._lock:
            if self._first_h9_ui is None:
                origin = int(Decimal(prediction['accumulation_start_host_ms'])*1_000_000)
                self._first_h9_ui = dict(prediction_id=prediction['prediction_id'],
                    submitted_host_monotonic_ns=now,source_last_input_host_ms=prediction['source_last_input_host_ms'],
                    collection_start_host_ms=prediction['accumulation_start_host_ms'],
                    collection_start_to_ui_ms=(now-origin)/1_000_000,
                    stream_start_to_ui_ms=(now-self._stream_start)/1_000_000 if self._stream_start is not None else None)

    @contextmanager
    def stage(self,name,frame_id=None):
        start = self.clock_ns()
        try:
            yield
        finally:
            self.record_ns(name,self.clock_ns()-start,frame_id)

    def start(self):
        if self._thread is not None:
            raise RuntimeError('resource monitor already started')
        self.sample_resources()
        self._thread = threading.Thread(target=self._monitor,name='probe-process-metrics',daemon=True)
        self._thread.start()

    def _monitor(self):
        while not self._stop.wait(1.0):
            self.sample_resources()

    def sample_resources(self):
        with self._lock:
            now,cpu = self.clock_ns(),self.cpu_clock_ns()
            try:
                memory = self.memory_reader()
            except Exception as exc:
                memory = dict(rss_bytes=None,private_bytes=None,os_peak_rss_bytes=None,memory_error=str(exc))
            phase = 'startup' if self._stream_start is None else ('stream' if self._stream_end is None else 'shutdown')
            row = dict(host_monotonic_ns=now,process_cpu_ns=cpu,phase=phase,**memory)
            if self._last_resource is not None and self._last_resource[2] == phase:
                wall = now-self._last_resource[0]
                row['cpu_one_core_percent'] = 100*(cpu-self._last_resource[1])/wall if wall > 0 else None
            else:
                row['cpu_one_core_percent'] = None
            self._last_resource = now,cpu,phase
            self._resources.append(row)

    def begin_stream(self):
        self._stream_start = self.clock_ns()
        self.sample_resources()
        return self._stream_start

    def end_stream(self):
        if self._stream_start is not None and self._stream_end is None:
            self.sample_resources()
            self._stream_end = self.clock_ns()

    def input_received(self,source_id=None):
        with self._lock:
            self._counts['input_framesets'] += 1
            token = self._counts['input_framesets']
            self._pending[token] = self.clock_ns()
            if type(source_id) is int:
                self._counts['source_duplicate_ids'] += int(source_id in self._source_ids)
                if self._last_source_id is not None:
                    self._counts['source_frame_gaps'] += max(0,source_id-self._last_source_id-1)
                    self._counts['source_counter_regressions'] += int(source_id < self._last_source_id)
                self._source_ids.add(source_id)
                self._last_source_id = source_id
            else:
                self._source_unknown = True
            return token

    def receive_timeout(self):
        with self._lock:self._counts['receive_timeouts'] += 1

    def invalid_pair(self,token):
        with self._lock:
            self._counts['missing_color_or_depth'] += 1
            self._pending.pop(token,None)

    def skip_at_deadline(self,token):
        with self._lock:
            self._counts['duration_boundary_frames_skipped'] += 1
            self._pending.pop(token,None)

    def ui_submitted(self,token,frame_id):
        with self._lock:
            self.record_ns('latency.host_receive_to_ui_submit',self.clock_ns()-self._pending[token],frame_id)

    def frame_completed(self,token,frame_id):
        with self._lock:
            self.record_ns('frame.processing',self.clock_ns()-self._pending.pop(token),frame_id)
            self._counts['processed_frames'] += 1

    def finish(self,*,error=None,cleanup_errors=(),termination=None):
        if self._finished:
            return
        self.end_stream()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2.0)
            if self._thread.is_alive():
                raise RuntimeError('resource monitor did not stop')
        self.sample_resources()
        with self._lock:
            elapsed = ((self._stream_end-self._stream_start)/1e9 if self._stream_start is not None else 0)
            stop=dict(termination or dict(reason='completed',requested_duration_seconds=None))
            stop['actual_run_seconds']=elapsed
            if error is not None or cleanup_errors:
                stop['requested_stop_reason']=stop['reason']
                stop['reason']='error' if error is not None else 'cleanup_error'
            inference_counts=dict(total_successful=self._successful_h9_inferences,
                warmup_excluded=min(self.h9_warmup_calls,self._successful_h9_inferences),
                post_warmup=max(0,self._successful_h9_inferences-self.h9_warmup_calls))
            reasons=[]
            if inference_counts['post_warmup'] < 60:reasons.append('insufficient_post_warmup_m0_inferences')
            if 'h9_model' not in self.metadata:reasons.append('h9_model_not_connected')
            if stop['reason'] != 'duration_elapsed':reasons.append('run_did_not_finish_by_duration')
            if stop.get('requested_duration_seconds') != 90 or elapsed < 90:reasons.append('fixed_90_second_run_not_completed')
            if self.warmup_frames != 150 or self.h9_warmup_calls != 5:reasons.append('fixed_warmup_settings_not_used')
            if error is not None:reasons.append('runtime_error')
            if cleanup_errors:reasons.append('cleanup_error')
            for flag in ('f1_live','f1_demo_enabled','pyvista','csv_enabled','face_diag_enabled','upper13_enabled','callback_enabled'):
                if self.metadata.get(flag):reasons.append('extra_pipeline_option_enabled:'+flag)
            if self.metadata.get('views') not in (None,False,'none'):reasons.append('extra_3d_view_enabled')
            baseline=dict(eligible=not reasons,status='ELIGIBLE' if not reasons else 'BLOCKED',
                minimum_post_warmup_m0_inferences=60,post_warmup_m0_inferences=inference_counts['post_warmup'],
                reasons=reasons,scope='One development timing run only; all three fixed runs must qualify separately. Not execution approval or an accuracy/Patch 8 result.')
            resource_summary = {}
            for phase in ('startup','stream','shutdown'):
                rows = [r for r in self._resources if r['phase']==phase]
                resource_summary[phase] = {key:_stats([r[key] for r in rows if r.get(key) is not None])
                                           for key in ('cpu_one_core_percent','rss_bytes','private_bytes','os_peak_rss_bytes')}
            report = dict(kind='engineering-probe-host-timing',metadata=self.metadata,
                          clock='host time.monotonic_ns; process time.process_time_ns',
                          environment=dict(python=platform.python_version(),platform=platform.platform(),logical_cpus=os.cpu_count()),
                          error=str(error) if error is not None else None,
                          cleanup_errors=[str(e) for e in cleanup_errors],
                          termination=stop,h9_inferences=inference_counts,baseline_interpretation=baseline,
                          baseline_stage_milliseconds={name:_stats(values) for name,values in sorted(self._stages.items())} if not reasons else None,
                          stage_milliseconds={name:_stats(values) for name,values in sorted(self._stages.items())},
                          warmup_stage_milliseconds={name:_stats(values) for name,values in sorted(self._warmup.items())},
                          collection_stage_milliseconds={name:_stats(values) for name,values in sorted(self._collection.items())},
                          h9_warmup_calls_per_stage=self.h9_warmup_calls,h9_full_window_stage_calls=dict(self._h9_calls),
                          h9_first_prediction=self._first_h9_prediction,h9_first_ui_submission=self._first_h9_ui,
                          warmup_processed_frames=self.warmup_frames,counts=dict(self._counts),
                          unfinished_processing_frames=len(self._pending),stream_seconds=elapsed,
                          delivered_input_fps=self._counts['input_framesets']/elapsed if elapsed else None,
                          processed_fps=self._counts['processed_frames']/elapsed if elapsed else None,
                          unique_source_frames=None if self._source_unknown else len(self._source_ids),
                          process_resource_samples=self._resources,process_resource_summary=resource_summary,
                          notes=['Nested stages overlap; do not sum stage p95 values.',
                                 'Duration is cooperative: a running receive/feature/inference call may finish; actual duration and stop-request overrun are recorded.',
                                 'FPS covers the entire stream, including warmup; stage warmup is reported separately.',
                                 'H9 partial collection is separate; first N full-window aggregate calls and first N actual M0 calls are warmup independently.',
                                 'H9 counters span this run, including resets; steady means after prescribed warmup, not proven convergence.',
                                 'Raw stage/resource statistics are retained even when baseline_interpretation is BLOCKED.',
                                 'Other stages use processed-frame warmup only when frame IDs are supplied; receive and H9 UI ages cover the entire run.',
                                 'CPU uses one-core=100%; divide by logical_cpus for machine-normalized percent.',
                                 'RAM is this process working set/private memory; external browser/GPU memory is excluded.',
                                 'UI endpoint is application submission, not physical display or sensor-to-screen latency.'])
            with self.output_path.open('x',encoding='utf-8') as stream:
                json.dump(report,stream,ensure_ascii=False,allow_nan=False,indent=2);stream.write('\n')
            self._finished = True
        return report
