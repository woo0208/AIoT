"""Development host-clock runner around the existing H9TimeWindow.

Features are selected from an already computed GeometryResult. Windows and
timeout use host monotonic admission time; device/UTC tokens remain separate.
No model fit, detector/geometry recomputation, camera or performance tuning.
Legacy h9_time_window CSV replay keeps its original event-time behavior.

New runtime timer dispatches coalesce missed 1s deadlines into one current
update. With no unconsumed input, HOLDING refers to the existing prediction
ID/age, not a new RF call or prediction event. Reset/insufficient/stale clear
the displayed prediction. All 4s/1s/2s settings remain development-only.
"""

import argparse
from collections import Counter
import copy
from dataclasses import dataclass, field, fields
from decimal import Decimal
from pathlib import Path
import threading
import time

import h9_csv_replay as replay
import h9_m0 as m0
import h9_time_window as window
from posture_geometry import GeometryResult


@dataclass(frozen=True)
class H9HostInput(window.H9WindowInput):
    host_monotonic_ms: str = field(kw_only=True)

    def __post_init__(self):
        super().__post_init__()
        window._time(self.host_monotonic_ms)

    @property
    def time(self):
        return window._time(self.host_monotonic_ms)

    @classmethod
    def from_window_input(cls, frame, host_monotonic_ms):
        return cls(**{f.name: getattr(frame, f.name) for f in fields(window.H9WindowInput)},
                   host_monotonic_ms=str(host_monotonic_ms))


def geometry_to_host_input(result, *, frame_index, recording_id, subject,
                           device_timestamp_ms, host_monotonic_ms, timestamp_utc='unknown',
                           segment_id=None, source_label=None):
    """Select same-frame stored H9 features only; never invoke any calculator."""
    if not isinstance(result, GeometryResult):
        raise ValueError('expected an already computed GeometryResult')
    if not set(m0.FEATURE_ORDER).issubset(result.features):
        raise ValueError('GeometryResult is missing required H9 feature keys')
    values = (None if source_label in replay.offline.NON_EVALUATION_LABELS
              else {name: result.features[name] for name in m0.FEATURE_ORDER})
    return H9HostInput(frame_index, recording_id, subject, str(device_timestamp_ms),
                       timestamp_utc, values, segment_id, source_label,
                       host_monotonic_ms=str(host_monotonic_ms))


class H9HostTimeWindow(window.H9TimeWindow):
    """Host-time scheduling policy; original aggregation and RF path are reused."""

    def __init__(self, model):
        super().__init__(model)
        self._input_version = 0
        self._evaluated_version = None
        self._display = None
        self.rf_calls = 0
        self.missed_periods_total = 0
        self.device_clock_regressions = 0
        self.equal_device_times = 0

    def _clear(self):
        super()._clear()
        self._evaluated_version = None
        self._display = None

    def _predict_sample(self, sample):
        if self._evaluated_version == self._input_version:
            return None
        result = super()._predict_sample(sample)
        self.rf_calls += 1
        return result

    def _emit(self, end, event, **kwargs):
        result = super()._emit(end, event, **kwargs)
        if result['status'] == 'PREDICTED':
            # H9 aggregates the existing common-valid support, not later arrivals
            # or incomplete frames. Freeze this provenance with the prediction.
            last_used_index = result['common_valid_frame_indices'][-1]
            last_used = next(f for f in reversed(self._frames) if f.frame_index == last_used_index)
            self._display = dict(prediction_id=result['window_id'],
                                 generated_host_ms=str(end), prediction_index=result['prediction_index'],
                                 prediction_label=result['prediction_label'],
                                 model_sha256=result['model_sha256'],
                                 source_last_input_host_ms=str(last_used.time),
                                 source_last_input_frame_index=last_used_index,
                                 accumulation_start_host_ms=result['accumulation_start_ms'],
                                 source_input_frame_range=result['input_frame_range'])
        elif result['status'] != 'HOLDING':
            self._display = None
        if result['status'] == 'HOLDING' and self._display is None:
            result['status'] = 'INSUFFICIENT_DATA'
        if (self._start is not None and end-self._start >= window.WINDOW_MS
                and result['status'] in ('PREDICTED', 'HOLDING', 'INSUFFICIENT_DATA')):
            self._evaluated_version = self._input_version
        result.update(clock_domain='host monotonic admission clock', observed_at_ms=str(end),
                      emitted_host_monotonic_ms=str(end),
                      input_host_monotonic_range=[str(self._frames[0].time), str(self._frames[-1].time)] if self._frames else None,
                      last_observation_host_monotonic_ms=str(self._last_input.time) if self._last_input else None,
                      new_prediction=result['status'] == 'PREDICTED',
                      prediction_id=result['window_id'] if result['status'] == 'PREDICTED' else None,
                      held_prediction_id=self._display['prediction_id'] if result['status'] == 'HOLDING' else None,
                      display_prediction=copy.deepcopy(self._display),
                      last_prediction_age_ms=str(end-Decimal(self._display['generated_host_ms'])) if self._display else None,
                      rf_calls_total=self.rf_calls, missed_periods_this_dispatch=0,
                      missed_periods_total=self.missed_periods_total)
        return result

    def _advance(self, now, inclusive):
        self._clock = now
        if self._next_due is None or now < self._next_due or (not inclusive and now == self._next_due):
            return []
        count = int((now-self._next_due)//window.UPDATE_MS)+1
        if not inclusive and self._next_due+(count-1)*window.UPDATE_MS == now:
            count -= 1
        if count <= 0:
            return []
        latest_due = self._next_due+(count-1)*window.UPDATE_MS
        self.missed_periods_total += count-1
        stale = self._last_input is not None and now-self._last_input.time >= window.STALE_AFTER_MS
        result = self._emit(now, 'timer_tick', forced_state='STALE' if stale else None)
        result.update(scheduled_host_monotonic_ms=str(latest_due),
                      deadline_lag_ms=str(now-latest_due),
                      due_periods_this_dispatch=count, missed_periods_this_dispatch=count-1)
        self._next_due += count*window.UPDATE_MS
        if stale and not self._stale:
            self._clear()
            self._stale = True
        return [result]

    def _before_push(self, now):
        # A resumed frame must not silently bridge an outage if the timer was delayed.
        outputs = (self._advance(now, inclusive=True) if self._last_input is not None
                   and now-self._last_input.time >= window.STALE_AFTER_MS else [])
        self._clock = now
        return outputs

    def push(self, frame):
        if not isinstance(frame, H9HostInput):
            raise ValueError('host runtime requires separate host/device timestamp fields')
        previous = self._last_input
        self._input_version += 1
        try:
            outputs = super().push(frame)
        except Exception:
            self._input_version -= 1
            raise
        if previous is not None:
            device = window._time(frame.device_timestamp_ms)
            before = window._time(previous.device_timestamp_ms)
            self.device_clock_regressions += int(device < before)
            self.equal_device_times += int(device == before)
        return outputs


class H9AsyncRuntime:
    """Serialize frame/timer/reset calls, timestamping live inputs inside the lock.

    sink is an optional local presentation callback. It is called in publication
    order under the lock and must be short and must not mutate the runtime.
    No communication, camera start or inference calculator is hidden here.
    """

    def __init__(self, model, *, clock_ns=time.monotonic_ns, sink=None, engine_factory=H9HostTimeWindow):
        self.engine = engine_factory(model)
        self._clock_ns = clock_ns
        self._sink = sink
        self._lock = threading.RLock()
        self._last_output = None
        self.publications = 0

    def _now(self):
        value = self._clock_ns()
        if type(value) is not int:
            raise ValueError('monotonic clock must return integer nanoseconds')
        return Decimal(value)/Decimal(1_000_000)

    def _publish(self, results):
        for result in results:
            self.publications += 1
            result['publication_sequence'] = self.publications
            result['device_clock_regressions'] = self.engine.device_clock_regressions
            self._last_output = copy.deepcopy(result)
            if self._sink is not None:
                self._sink(copy.deepcopy(result))
        return results

    def observe_geometry(self, result, *, frame_index, recording_id, subject,
                         device_timestamp_ms, timestamp_utc='unknown',
                         segment_id=None, source_label=None):
        with self._lock:
            frame = geometry_to_host_input(
                result, frame_index=frame_index, recording_id=recording_id, subject=subject,
                device_timestamp_ms=device_timestamp_ms, host_monotonic_ms=self._now(),
                timestamp_utc=timestamp_utc, segment_id=segment_id, source_label=source_label)
            return self._publish(self.engine.push(frame))

    def observe_replay_frame(self, frame):
        with self._lock:
            packet = H9HostInput.from_window_input(window.H9WindowInput.from_replay(frame), self._now())
            return self._publish(self.engine.push(packet))

    def tick(self):
        with self._lock:
            return self._publish(self.engine.tick(self._now()))

    def manual_reset(self):
        with self._lock:
            return self._publish([self.engine.reset(self._now())])

    def snapshot(self):
        """Read the last published state and current ages; does not infer or tick."""
        with self._lock:
            if self._last_output is None:
                return None
            result = copy.deepcopy(self._last_output)
            now = self._now()
            if now < Decimal(result['emitted_host_monotonic_ms']):
                raise ValueError('monotonic clock moved backwards')
            result['snapshot_only'] = True
            result['published_status'] = result['status']
            result['new_prediction'] = False
            result['snapshot_host_monotonic_ms'] = str(now)
            result['output_age_ms'] = str(now-Decimal(result['emitted_host_monotonic_ms']))
            if result['last_observation_host_monotonic_ms'] is not None:
                result['last_input_age_ms'] = str(now-Decimal(result['last_observation_host_monotonic_ms']))
            if result['display_prediction'] is not None:
                result['last_prediction_age_ms'] = str(now-Decimal(result['display_prediction']['generated_host_ms']))
                if Decimal(result['last_input_age_ms']) >= window.STALE_AFTER_MS:
                    result.update(status='STALE', reasons=['input_timeout_timer_dispatch_pending'],
                                  display_prediction=None, last_prediction_age_ms=None,
                                  prediction_id=None, held_prediction_id=None,
                                  prediction_index=None, prediction_label=None, features=None)
                elif result['status'] == 'PREDICTED':
                    result.update(status='HOLDING', reasons=['snapshot_of_existing_prediction'],
                                  held_prediction_id=result['display_prediction']['prediction_id'],
                                  prediction_id=None, prediction_index=None, prediction_label=None, features=None)
            return result

    def probe_callback(self, *, recording_id, subject):
        """Compatible with run_probe(frame_callback=...); unknown live labels stay unknown."""
        def accept(completed_frame):
            return self.observe_geometry(
                completed_frame.result, frame_index=completed_frame.frame_index,
                recording_id=recording_id, subject=subject,
                device_timestamp_ms=completed_frame.device_timestamp_ms,
                timestamp_utc=getattr(completed_frame, 'timestamp_utc', 'unknown'))
        return accept


class H9TimerRunner:
    """Independent host timer thread; external producer calls runtime.observe_*()."""

    def __init__(self, runtime, *, poll_seconds=1.0):
        if not 0 < poll_seconds <= 1:
            raise ValueError('timer poll interval must be in (0, 1] seconds')
        self.runtime, self.poll_seconds = runtime, poll_seconds
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError('timer runner already started')
        self.runtime.tick()
        self._thread = threading.Thread(target=self._run, name='h9-development-timer', daemon=True)
        self._thread.start()
        return self

    def _run(self):
        try:
            while not self._stop.wait(self.poll_seconds):
                self.runtime.tick()
        except Exception as exc:
            self.error = exc
            self._stop.set()

    def stop(self, timeout=2.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise RuntimeError('timer thread did not stop')
        if self.error is not None:
            raise RuntimeError('timer thread failed') from self.error


class VirtualMonotonicClock:
    """Explicit development clock for deterministic CSV/timer tests, no sleeping."""

    def __init__(self):
        self.ns = 0

    def set_ms(self, value):
        ns = window._time(value)*Decimal(1_000_000)
        if ns != ns.to_integral_value() or ns < self.ns:
            raise ValueError('virtual host clock must advance in integer nanoseconds')
        self.ns = int(ns)

    def __call__(self):
        return self.ns


def run_csv_runtime(paths, model_path, *, reset_at_rows=()):
    artifact = replay._identity(model_path)
    model = m0.load_model(model_path)
    comparison = replay.validate_replay(paths)
    if comparison['status'] != 'PASS':
        raise ValueError('whole-segment CSV adapter validation failed')
    inputs = [{k: s[k] for k in ('path', 'sha256', 'size_bytes')} for s in comparison['sources']]
    code = [replay._identity(__file__), replay._identity(window.__file__), *m0._code_identities()]
    requested = set(reset_at_rows)
    applied = set()
    sources, results = [], []
    for source in inputs:
        clock = VirtualMonotonicClock()
        outputs = []
        runtime = H9AsyncRuntime(model, clock_ns=clock, sink=outputs.append)
        origin, last = None, None
        for frame in replay.iter_probe_frames(source['path']):
            if origin is None:
                origin = frame.device_time
            last = Decimal(1000)+frame.device_time-origin
            clock.set_ms(last)
            key = (frame.recording_id, frame.frame_index)
            if key in requested:
                runtime.manual_reset()
                applied.add(key)
            runtime.observe_replay_frame(frame)
        # 1s no-input update, then delayed timer; no RF replay of old deadlines.
        clock.set_ms(last+1000);runtime.tick()
        clock.set_ms(last+5000);runtime.tick()
        sources.append(dict(**source, status_counts=dict(Counter(r['status'] for r in outputs)),
                            rf_calls=runtime.engine.rf_calls,
                            missed_periods=runtime.engine.missed_periods_total,
                            device_clock_regressions=runtime.engine.device_clock_regressions,
                            equal_device_times=runtime.engine.equal_device_times))
        results.extend(outputs)
    if applied != requested:
        raise ValueError('manual reset refers to an unknown recording/frame')
    replay._verify_files([artifact, *inputs, *code])
    return dict(kind='h9-development-host-clock-runtime-csv-check',
                protocol_status='PROVISIONAL DEVELOPMENT; no accuracy or runtime performance claim',
                clock_mode='virtual host monotonic: 1000ms + recorded device-time delta; original device tokens retained',
                artifact=artifact, model_sha256=model.metadata['model_sha256'], code=code,
                feature_order=m0.FEATURE_ORDER, class_order=m0.CLASS_ORDER,
                sources=sources, results=results,
                status_counts=dict(Counter(r['status'] for r in results)),
                rf_calls=sum(s['rf_calls'] for s in sources),
                missed_periods=sum(s['missed_periods'] for s in sources),
                manual_resets=[dict(recording_id=r, frame_index=i) for r,i in sorted(applied)],
                notes=['No camera/feature recomputation/training; existing H9 aggregation and M0 only.',
                       'Host admission time is not sensor exposure time or sensor-to-screen latency.',
                       'CSV labels provide boundaries/P5 exclusion; probe callback defaults to unknown labels.',
                       'HOLDING has no new prediction; display_prediction references the old prediction ID.',
                       'Legacy CSV replay remains device-event-time based and retains its original output policy.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-csv', nargs='+', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--reset-at-row', action='append', default=[], metavar='RECORDING:ROW')
    args = parser.parse_args(argv)
    m0._new_paths(args.output)
    resets = []
    for value in args.reset_at_row:
        recording, index = value.rsplit(':',1)
        if not recording or int(index) < 1:
            raise ValueError('invalid manual reset row')
        resets.append((recording,int(index)))
    result = run_csv_runtime(args.probe_csv, args.model, reset_at_rows=resets)
    m0._write_new(args.output,result)
    print('HOST RUNTIME:',result['status_counts'],'RF calls=',result['rf_calls'],
          'missed periods=',result['missed_periods'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
