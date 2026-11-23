"""Read-only E0-P2 telemetry. No model/delegate settings, images or identities.

CPU/RAM accessors reuse probe_timing. GPU polling is device-wide, read-only and
never runs on the frame loop. Unsupported observations remain NOT_MEASURED.
"""
import csv
import ctypes
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from probe_timing import process_memory, _stats
from e0_storage import CheckpointList, exact_stats, LogStorageError


def system_cpu_times():
    """Return cumulative busy/total ticks, not an unprimed percentage."""
    if os.name == 'nt':
        if (os.cpu_count() or 0) > 64:
            raise OSError('multiple_processor_groups_not_supported')
        from ctypes import wintypes
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        function = ctypes.WinDLL('kernel32',use_last_error=True).GetSystemTimes
        function.argtypes = [ctypes.POINTER(wintypes.FILETIME)]*3
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = lambda t: (t.dwHighDateTime << 32) + t.dwLowDateTime
        total = ticks(kernel)+ticks(user)  # kernel includes idle on Windows.
        return total-ticks(idle), total
    line = Path('/proc/stat').read_text().splitlines()[0].split()
    values = [int(x) for x in line[1:9]]  # exclude duplicated guest/guest_nice.
    total = sum(values)
    return total-values[3]-values[4], total


def read_cpu_memory():
    values = dict(process_cpu_ns=time.process_time_ns(), logical_cpus=os.cpu_count())
    try:
        values.update(process_memory())
    except Exception as exc:
        values.update(rss_bytes=None,private_bytes=None,os_peak_rss_bytes=None,memory_error_type=type(exc).__name__)
    try:
        values['system_busy_ticks'], values['system_total_ticks'] = system_cpu_times()
    except Exception as exc:
        values.update(system_busy_ticks=None,system_total_ticks=None,system_error_type=type(exc).__name__)
    return values


class NvidiaTelemetry:
    """Optional NVIDIA provider; absent tools/driver/permissions are not zeros."""
    def __init__(self):
        self.executable = shutil.which('nvidia-smi')

    def __call__(self):
        if self.executable is None:
            return dict(status='NOT_MEASURED',reason='NVIDIA_SMI_UNAVAILABLE',devices=[])
        try:
            result = subprocess.run([self.executable,
                '--query-gpu=index,name,utilization.gpu,memory.used,memory.total',
                '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=1,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                return dict(status='NOT_MEASURED',reason='GPU_QUERY_FAILED',devices=[])
            devices = []
            def number(token, factor=1):
                try:
                    value=float(token)
                    return value*factor if math.isfinite(value) and value>=0 else None
                except ValueError:
                    return None
            for row in csv.reader(result.stdout.splitlines()):
                if len(row)!=5:
                    raise ValueError('invalid_gpu_row')
                index,name,util,used,total=(s.strip() for s in row)
                utilization=number(util)
                if utilization is not None and utilization>100:
                    utilization=None
                memory_used,memory_total=number(used,2**20),number(total,2**20)
                devices.append(dict(index=int(index),model=name[:128],
                    utilization_percent=utilization,vram_used_bytes=memory_used,vram_total_bytes=memory_total,
                    utilization_status='MEASURED' if utilization is not None else 'NOT_MEASURED',
                    vram_status='MEASURED' if None not in (memory_used,memory_total) else 'NOT_MEASURED'))
            return dict(status='MEASURED' if devices else 'NOT_MEASURED',devices=devices,
                        scope='DEVICE_WIDE; process attribution and inference association NOT_MEASURED')
        except Exception as exc:
            return dict(status='NOT_MEASURED',reason='GPU_QUERY_UNAVAILABLE',error_type=type(exc).__name__,devices=[])


class ResourceMonitor:
    """One-second background observations; no frame producer/consumer queue."""
    def __init__(self, *, clock_ns=time.perf_counter_ns, reader=read_cpu_memory,
                 gpu_reader=None, interval_seconds=1.):
        self.clock_ns, self.reader = clock_ns, reader
        self.gpu_reader = gpu_reader if gpu_reader is not None else NvidiaTelemetry()
        if not math.isfinite(interval_seconds) or interval_seconds<=0:
            raise ValueError('invalid resource sample interval')
        self.interval_seconds = interval_seconds
        self.samples = []
        self.gpu_samples = []
        self._previous = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self.error_type = None

    def enable_checkpoints(self, directory, limit=256):
        if self._thread is not None or self.samples or self.gpu_samples:
            raise ValueError('Resource checkpoints must be configured before sampling')
        self.samples=CheckpointList(Path(directory)/'cpu_ram',limit,clock_ns=self.clock_ns)
        self.gpu_samples=CheckpointList(Path(directory)/'gpu',limit,clock_ns=self.clock_ns)

    def sample(self, phase='stream'):
        with self._lock:
            now = self.clock_ns()
            try:
                values = self.reader()
            except Exception as exc:
                values = dict(error_type=type(exc).__name__)
            allowed = ('process_cpu_ns','logical_cpus','rss_bytes','private_bytes','os_peak_rss_bytes',
                       'system_busy_ticks','system_total_ticks','memory_error_type','system_error_type','error_type')
            row = dict(host_perf_counter_ns=now,phase=phase,**{k:values.get(k) for k in allowed})
            for key in ('process_cpu_ns','logical_cpus','rss_bytes','private_bytes','os_peak_rss_bytes',
                        'system_busy_ticks','system_total_ticks'):
                value=row[key]
                if not isinstance(value,(float,int)) or not math.isfinite(value) or value<0:
                    row[key]=None
            row.update(process_cpu_one_core_percent=None,process_cpu_percent=None,system_cpu_percent=None)
            old = self._previous
            if old is not None and now>old['host_perf_counter_ns']:
                cpu, before = row['process_cpu_ns'], old['process_cpu_ns']
                if cpu is not None and before is not None and cpu>=before:
                    row['process_cpu_one_core_percent']=100*(cpu-before)/(now-old['host_perf_counter_ns'])
                    if row['logical_cpus']:
                        row['process_cpu_percent']=row['process_cpu_one_core_percent']/row['logical_cpus']
                busy,total = row['system_busy_ticks'],row['system_total_ticks']
                prev_busy,prev_total = old['system_busy_ticks'],old['system_total_ticks']
                if None not in (busy,total,prev_busy,prev_total) and total>prev_total and 0<=busy-prev_busy<=total-prev_total:
                    row['system_cpu_percent']=100*(busy-prev_busy)/(total-prev_total)
            self._previous = row
            row['sample_duration_ns'] = self.clock_ns()-now
            self.samples.append(row)
            return row

    def poll_gpu(self):
        start=self.clock_ns()
        try:
            value=self.gpu_reader()
        except Exception as exc:
            value=dict(status='NOT_MEASURED',error_type=type(exc).__name__,devices=[])
        # Only the explicit provider's hardware fields, never arbitrary provider text.
        clean=dict(status='MEASURED' if value.get('status')=='MEASURED' else 'NOT_MEASURED',
                   devices=[],reason=value.get('reason') if value.get('reason') in
                   ('NVIDIA_SMI_UNAVAILABLE','GPU_QUERY_FAILED','GPU_QUERY_UNAVAILABLE') else None)
        for device in value.get('devices',[]):
            clean['devices'].append({k:device.get(k) for k in
                ('index','model','utilization_percent','vram_used_bytes','vram_total_bytes',
                 'utilization_status','vram_status')})
        clean.update(host_perf_counter_ns=start,poll_duration_ns=self.clock_ns()-start,
                     scope='DEVICE_WIDE; inference association NOT_MEASURED')
        self.gpu_samples.append(clean)
        return clean

    def _monitor(self):
        # GPU commands stay on this observer thread, including the first poll.
        try:
            self.poll_gpu()
            while not self._stop.wait(self.interval_seconds):
                self.sample()
                self.poll_gpu()
        except Exception as exc:
            self.error_type=type(exc).__name__
            self._stop.set()

    def check_health(self):
        if self.error_type is not None:raise LogStorageError('RESOURCE_LOGGER_FAILED')

    def start(self):
        self.sample()
        self._thread=threading.Thread(target=self._monitor,name='e0-resources',daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self.sample('final')
        finally:
            if self._thread is not None:self._thread.join()
        self.check_health()

    def summary(self):
        fields=('process_cpu_percent','process_cpu_one_core_percent','system_cpu_percent',
                'rss_bytes','private_bytes','os_peak_rss_bytes')
        statistics={}
        for name in fields:
            values=(r[name] for r in self.samples if r.get(name) is not None)
            stats=exact_stats(values,disk=isinstance(self.samples,CheckpointList))
            first=next((r[name] for r in self.samples if r.get(name) is not None),None)
            last=None
            for row in self.samples:
                if row.get(name) is not None:last=row[name]
            statistics[name]=dict(status='MEASURED' if stats['count'] else 'NOT_MEASURED',**stats,
                first=first,last=last,change=last-first if first is not None else None)
        return dict(clock='time.perf_counter_ns' if self.clock_ns is time.perf_counter_ns else 'injected_test_clock',
            sample_interval_seconds=self.interval_seconds,
            logical_cpus=self.samples[-1].get('logical_cpus') if self.samples else None,
            statistics=statistics,
            gpu_status='MEASURED' if any(r['status']=='MEASURED' for r in self.gpu_samples) else 'NOT_MEASURED',
            gpu_samples=len(self.gpu_samples),
            gpu_devices=self.gpu_samples[-1]['devices'] if self.gpu_samples else [],
            buffering={name:rows.status() for name,rows in [('cpu_ram',self.samples),('gpu',self.gpu_samples)]
                       if isinstance(rows,CheckpointList)},
            notes=['Process CPU percent is machine-normalized; one_core uses one core=100%',
                'First CPU sample has no delta; missing/unsupported is not zero',
                'RSS/Private observation peaks are sampled; OS peak is process-lifetime cumulative',
                'Final resource sample precedes monitor join; stream FPS excludes join/publication'])
