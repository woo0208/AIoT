"""Explicit QPC/perf-counter sidecar; legacy monotonic timing stays unchanged."""
from contextlib import contextmanager
from collections import defaultdict
from pathlib import Path
import threading
import time
import numpy as np

import engineering_exports as out
import performance_output as perf
from probe_timing import _stats
from e0_storage import CheckpointList, exact_stats, write_json


class ProbeDiagnostics:
    def __init__(self, directory, *, inputs=(), headless=False, clock_ns=time.perf_counter_ns,
                 include_p99=False, redact_errors=False, retain_raw=True, buffer_limit=None):
        self.directory = out.reserve(directory, inputs)
        self.clock_ns = clock_ns
        self.headless = headless
        self.include_p99 = include_p99
        self.redact_errors = redact_errors
        self.retain_raw = retain_raw
        self.buffer_limit = buffer_limit
        self._durations = defaultdict(lambda: CheckpointList(self.directory/'buffers'/f'duration_{len(self._durations)}',
            buffer_limit,clock_ns=clock_ns)) if buffer_limit is not None else defaultdict(list)
        self.rows = CheckpointList(self.directory/'buffers'/'raw',buffer_limit,clock_ns=clock_ns) if buffer_limit is not None else []
        self._inputs = {}
        self._lock = threading.RLock()
        self._finished = False
        self.identity = dict(kind='engineering-probe-diagnostics/1', scope='NON_FORMAL_ENGINEERING',
            headless=headless, clock='time.perf_counter_ns' if clock_ns is time.perf_counter_ns else 'injected_test_clock',
            source_sha256={n:perf.sha256(Path(__file__).with_name(n)) for n in
                           ('probe_diagnostics.py','probe_timing.py','posture_geometry_probe.py')},
            clock_info={n:vars(time.get_clock_info(n)) for n in ('monotonic','perf_counter','process_time')})
        perf._write_json(self.directory/'manifest.json', dict(self.identity, status='RUNNING'))

    def record_ns(self, name, duration_ns, frame_id=None, phase='steady'):
        if duration_ns < 0:
            raise ValueError('diagnostic clock moved backwards')
        with self._lock:
            if self.retain_raw:
                self.rows.append(dict(name=name, duration_ns=duration_ns, frame_id=frame_id, phase=phase))
            if not self.retain_raw or self.buffer_limit is not None:
                self._durations[(name,phase)].append(duration_ns/1e6)

    @contextmanager
    def stage(self, name, frame_id=None, phase='steady'):
        start = self.clock_ns()
        try:
            yield
        finally:
            self.record_ns(name, self.clock_ns()-start, frame_id, phase)

    def input_received(self, token):
        with self._lock:
            self._inputs[token] = self.clock_ns()

    def discard(self, token):
        with self._lock:
            self._inputs.pop(token, None)

    def endpoint(self, token, name, frame_id, phase='steady', *, complete=False):
        with self._lock:
            start = self._inputs[token]
            self.record_ns(name, self.clock_ns()-start, frame_id, phase)
            if complete:
                self._inputs.pop(token)

    def finish(self, *, status, error=None, cleanup_errors=()):
        with self._lock:
            if self._finished:
                return
            durations = self._durations
            if self.retain_raw and self.buffer_limit is None:
                durations = defaultdict(list)
                for row in self.rows:
                    durations[(row['name'],row['phase'])].append(row['duration_ns']/1e6)
            summary = [dict(name=name, phase=phase, unit='ms', **exact_stats(values,
                include_p99=self.include_p99,disk=self.buffer_limit is not None))
                       for (name,phase),values in sorted(durations.items())]
            error_text = lambda exc: type(exc).__name__ if self.redact_errors else str(exc)
            document = dict(self.identity, status=status, error=error_text(error) if error else None,
                cleanup_errors=[error_text(e) for e in cleanup_errors], raw=self.rows, stage_milliseconds=summary,
                pending_inputs=len(self._inputs),
                ui_latency_status='NOT_MEASURED' if self.headless else 'OBSERVED_IF_SUBMITTED',
                notes=['Independent clock domain; never subtract QPC from legacy monotonic or device clocks.',
                       'Parallel observer adds overhead; tiny interval differences include observer/clock-call cost.',
                       'Raw rows are memory-resident until normal/exception finalization; kill/power loss may leave manifest only.',
                       'No physical display/GPU-completion/sensor-to-screen latency measurement.'])
            if not self.retain_raw:
                document['raw_status'] = 'NOT_RETAINED_SUMMARY'
            if self.buffer_limit is not None:
                document['notes']=[note for note in document['notes'] if not note.startswith('Raw rows are memory-resident')]
                document['notes'].append('Bounded checkpoints retain every row; checkpoint I/O adds observer overhead.')
                self.rows.flush()
                for values in self._durations.values():values.flush()
                document['buffering']=dict(raw=self.rows.status(),
                    durations=[values.status() for values in self._durations.values()])
                write_json(self.directory/'diagnostics.json',document,arrays=('raw',))
            else:
                perf._write_json(self.directory/'diagnostics.json', document)
            self._finished = True


class DisabledDiagnostics:
    """No clock reads, buffers or files; retains the stage-call interface."""
    def __init__(self):
        self.headless = False
        self.identity = {}

    def stage(self, *args, **kwargs):
        from contextlib import nullcontext
        return nullcontext()

    def record_ns(self, *args, **kwargs):
        pass

    def finish(self, **kwargs):
        pass
