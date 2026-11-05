"""Explicit QPC/perf-counter sidecar; legacy monotonic timing stays unchanged."""
from contextlib import contextmanager
from pathlib import Path
import threading
import time

import engineering_exports as out
import performance_output as perf
from probe_timing import _stats


class ProbeDiagnostics:
    def __init__(self, directory, *, inputs=(), headless=False, clock_ns=time.perf_counter_ns):
        self.directory = out.reserve(directory, inputs)
        self.clock_ns = clock_ns
        self.headless = headless
        self.rows = []
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
            self.rows.append(dict(name=name, duration_ns=duration_ns, frame_id=frame_id, phase=phase))

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
            names = sorted({(r['name'],r['phase']) for r in self.rows})
            summary = [dict(name=name, phase=phase, unit='ms', **_stats([
                r['duration_ns']/1e6 for r in self.rows if (r['name'],r['phase']) == (name,phase)])) for name,phase in names]
            document = dict(self.identity, status=status, error=str(error) if error else None,
                cleanup_errors=[str(e) for e in cleanup_errors], raw=self.rows, stage_milliseconds=summary,
                pending_inputs=len(self._inputs),
                ui_latency_status='NOT_MEASURED' if self.headless else 'OBSERVED_IF_SUBMITTED',
                notes=['Independent clock domain; never subtract QPC from legacy monotonic or device clocks.',
                       'Parallel observer adds overhead; tiny interval differences include observer/clock-call cost.',
                       'Raw rows are memory-resident until normal/exception finalization; kill/power loss may leave manifest only.',
                       'No physical display/GPU-completion/sensor-to-screen latency measurement.'])
            perf._write_json(self.directory/'diagnostics.json', document)
            self._finished = True
