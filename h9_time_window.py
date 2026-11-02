"""Provisional development H9 window: (end-4000ms, end], updates every 1000ms.

Reuses the CSV adapter, original H9 aggregator and loaded development M0.
No fit, feature/filter change, camera or accuracy evaluation. Source label/ID
changes and explicit manual reset clear the window; geometry never detects a
transition or P5. Unlabelled inputs have neither source label nor segment ID.

The reference clock must be monotonic and in the same domain as device times.
CSV replay advances this clock virtually, without sleeping or measuring speed.
STALE is a provisional 2000ms input timeout, observed on the next 1s tick.
STALE clears accumulated data and predictions; recovery collects 4s anew.
Immediate first-input/reset/recovery events supplement periodic 1s updates.
Actual hardware clock mapping and UI/timer integration are outside this step.
"""

import argparse
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import f1_sample_aggregator as aggregation
import h9_csv_replay as replay
import h9_m0 as m0


WINDOW_MS = Decimal(4000)
UPDATE_MS = Decimal(1000)
STALE_AFTER_MS = Decimal(2000)
STATES = ('COLLECTING', 'INSUFFICIENT_DATA', 'STALE', 'PREDICTED')


def _time(value):
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('invalid reference timestamp') from exc
    if not result.is_finite():
        raise ValueError('non-finite reference timestamp')
    return result


@dataclass(frozen=True)
class H9WindowInput:
    """Preserved feature observation, with optional externally supplied context."""

    frame_index: int
    recording_id: str
    subject: str
    device_timestamp_ms: str
    timestamp_utc: str
    features: Mapping[str, float | None] | None
    segment_id: str | None = None
    source_label: str | None = None

    def __post_init__(self):
        if type(self.frame_index) is not int or self.frame_index < 1:
            raise ValueError('frame index must be a positive integer')
        for name in ('recording_id', 'subject', 'device_timestamp_ms', 'timestamp_utc'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'missing window input {name}')
        _time(self.device_timestamp_ms)
        if (self.segment_id is None) != (self.source_label is None):
            raise ValueError('source label and segment ID must both be known or unknown')
        if self.source_label is not None and (not isinstance(self.source_label, str) or not self.source_label.strip()):
            raise ValueError('invalid source label')
        if self.segment_id is not None and (not isinstance(self.segment_id, str) or not self.segment_id.strip()):
            raise ValueError('empty source segment ID')
        if self.source_label in replay.offline.NON_EVALUATION_LABELS:
            if self.features is not None:
                raise ValueError('PREP/TRANSITION do not supply H9 observations')
        else:
            if not isinstance(self.features, Mapping):
                raise ValueError('H9 observations require the exact feature mapping, including None values')
            label = self.label if self.source_label is not None else 'unlabelled'
            record = aggregation.HFrameRecord(
                analysis_run_id='window-input:'+self.recording_id, recording_id=self.recording_id,
                frame_index=self.frame_index, subject=self.subject, round=None,
                step=self.segment_id or 'unlabelled', label=label, features=self.features)
            object.__setattr__(self, 'features', record.features)

    @property
    def time(self):
        return _time(self.device_timestamp_ms)

    @property
    def label(self):
        if self.source_label is None or self.source_label in replay.offline.NON_EVALUATION_LABELS:
            return self.source_label
        return replay.offline.analysis_label(self.source_label)

    @classmethod
    def from_replay(cls, frame):
        if not isinstance(frame, replay.H9ReplayFrame):
            raise ValueError('expected the existing CSV adapter frame')
        return cls(frame.frame_index, frame.recording_id, frame.subject,
                   frame.device_timestamp_ms, frame.timestamp_utc,
                   frame.record.features if frame.record is not None else None,
                   frame.segment_id, frame.original_label)


class H9TimeWindow:
    """One recording, causal pushes plus explicit timer ticks. No automatic labels."""

    def __init__(self, model):
        if not isinstance(model, m0.H9M0Model):
            raise ValueError('expected the validated existing H9 development model')
        self.model = model
        self._frames = deque()
        self._last_input = None
        self._clock = None
        self._start = None
        self._next_due = None
        self._stale = False
        self._generation = 0
        self._sequence = 0
        self._context = None
        self._context_known = False

    def _clear(self):
        self._frames.clear()
        self._start = None
        self._generation += 1

    def _sample(self, end):
        while self._frames and self._frames[0].time <= end-WINDOW_MS:
            self._frames.popleft()
        if not self._frames:
            return None
        label = self._context[1] if self._context[1] is not None else 'unlabelled'
        step = f'window:g{self._generation}:end{end}'
        records = [aggregation.HFrameRecord(
            analysis_run_id='h9-window-development:'+f.recording_id,
            recording_id=f.recording_id, frame_index=f.frame_index, subject=f.subject,
            round=None, step=step, label=label, features=f.features) for f in self._frames]
        return aggregation.aggregate_h5_h9_sample(records)

    def _predict_sample(self, sample):
        """Default replay inference; host runtime may suppress an unchanged input."""
        return int(self.model.predict([sample.ordered_values('H9')], feature_order=m0.FEATURE_ORDER)[0])

    def _before_push(self, now):
        """Preserve event-time replay's processing of deadlines before a frame."""
        return self._advance(now, inclusive=False)

    def _emit(self, end, event, *, forced_state=None, extra_reason=None):
        sample = self._sample(end)
        frames = tuple(self._frames)
        last = self._last_input
        label = self._context[1] if self._context is not None else None
        reasons = []
        if forced_state == 'STALE':
            state, reasons = 'STALE', ['no_input_for_at_least_2000ms']
        elif label in replay.offline.NON_EVALUATION_LABELS:
            state, reasons = 'INSUFFICIENT_DATA', ['csv_label_excluded_non_posture']
        elif label is not None and label not in m0.CLASS_ORDER:
            state, reasons = 'INSUFFICIENT_DATA', ['csv_label_outside_primary5']
        elif self._start is None or end-self._start < WINDOW_MS:
            state, reasons = 'COLLECTING', ['full_4s_window_not_yet_accumulated']
        elif sample is None or not sample.eligible:
            state = 'INSUFFICIENT_DATA'
            reasons = list(sample.eligibility_reasons) if sample is not None else ['no_observed_H9_frames']
        else:
            state = 'PREDICTED'
        if extra_reason:
            reasons.append(extra_reason)
        prediction = None
        if state == 'PREDICTED':
            # Unknown source label is metadata, not a sixth class or an inference input.
            prediction = self._predict_sample(sample)
            if prediction is None:
                state, reasons = 'HOLDING', ['no_new_input_since_last_window_update']
        self._sequence += 1
        return dict(window_id=f'h9dev:{last.recording_id if last else "no-input"}:g{self._generation}:u{self._sequence}',
                    generation=self._generation, event=event, status=state, reasons=reasons,
                    clock_domain='CSV/synthetic device-time replay reference, not host wall time',
                    observed_at_ms=str(end), window_start_ms=str(end-WINDOW_MS), window_end_ms=str(end),
                    accumulation_start_ms=str(self._start) if self._start is not None else None,
                    provisional_window_ms=int(WINDOW_MS), provisional_update_ms=int(UPDATE_MS),
                    provisional_stale_after_ms=int(STALE_AFTER_MS),
                    recording_id=last.recording_id if last else None,
                    source_segment_id=self._context[0] if self._context else None, source_label=label,
                    scope_basis='csv_label' if label is not None else 'unlabelled_no_automatic_transition_or_P5_detection',
                    input_frame_range=[frames[0].frame_index, frames[-1].frame_index] if frames else None,
                    input_frame_indices=[f.frame_index for f in frames],
                    input_device_timestamp_range=[frames[0].device_timestamp_ms, frames[-1].device_timestamp_ms] if frames else None,
                    input_utc_range=[frames[0].timestamp_utc, frames[-1].timestamp_utc] if frames else None,
                    last_observation_device_timestamp_ms=last.device_timestamp_ms if last else None,
                    last_observation_utc=last.timestamp_utc if last else None,
                    last_input_age_ms=str(end-last.time) if last else None,
                    frame_count=sample.n_frames if sample else 0,
                    common_valid_count=sample.common_valid_count if sample else 0,
                    common_coverage=sample.common_coverage if sample else 0.0,
                    common_valid_frame_indices=list(sample.common_valid_frame_indices) if sample else [],
                    missing_counts=dict(sample.missing_counts) if sample else dict.fromkeys(m0.FEATURE_ORDER, 0),
                    features=list(sample.ordered_values('H9')) if state == 'PREDICTED' else None,
                    model_sha256=self.model.metadata['model_sha256'],
                    prediction_index=prediction,
                    prediction_label=m0.CLASS_ORDER[prediction] if prediction is not None else None)

    def _advance(self, now, inclusive):
        outputs = []
        while self._next_due is not None and (self._next_due <= now if inclusive else self._next_due < now):
            end = self._next_due
            stale = self._last_input is not None and end-self._last_input.time >= STALE_AFTER_MS
            outputs.append(self._emit(end, 'timer_tick', forced_state='STALE' if stale else None))
            if stale and not self._stale:
                self._clear()
                self._stale = True
            self._next_due += UPDATE_MS
        self._clock = now
        return outputs

    def push(self, frame):
        if not isinstance(frame, H9WindowInput):
            raise ValueError('expected H9WindowInput')
        now = frame.time
        previous = self._last_input
        if self._clock is not None and now < self._clock:
            raise ValueError('late/out-of-order frame relative to replay clock')
        if previous is not None:
            if (frame.recording_id, frame.subject) != (previous.recording_id, previous.subject):
                raise ValueError('recording/subject changed; use a new window engine')
            if frame.frame_index <= previous.frame_index:
                raise ValueError('duplicate or out-of-order frame index')
            if now < previous.time:
                raise ValueError('out-of-order device timestamp')
        outputs = self._before_push(now)
        context = (frame.segment_id, frame.label)
        changed = self._context_known and context != self._context
        restarting = previous is None or changed or self._stale or self._start is None
        if changed or self._stale:
            self._clear()
        self._context = context
        self._context_known = True
        self._last_input = frame
        self._stale = False
        if self._start is None:
            self._start = now
        if frame.features is not None:
            self._frames.append(frame)
        if restarting:
            self._next_due = now+UPDATE_MS
            outputs.append(self._emit(now, 'context_reset' if changed else 'collection_start'))
        else:
            outputs.extend(self._advance(now, inclusive=True))
        return outputs

    def tick(self, now_ms):
        """Timer input independent of frame arrival; same reference clock domain."""
        now = _time(now_ms)
        if self._clock is not None and now < self._clock:
            raise ValueError('out-of-order timer timestamp')
        if self._next_due is None:
            self._clock = now
            self._next_due = now+UPDATE_MS
            return [self._emit(now, 'waiting_for_first_input')]
        return self._advance(now, inclusive=True)

    def reset(self, now_ms):
        """Explicit manual signal; retain order checks, clear data and predictions."""
        now = _time(now_ms)
        if self._clock is not None and now < self._clock:
            raise ValueError('out-of-order reset timestamp')
        self._clear()
        self._stale = False
        self._clock = now
        self._next_due = now+UPDATE_MS
        return self._emit(now, 'manual_reset', extra_reason='explicit_manual_reset')


def run_csv_windows(paths, model_path):
    artifact = replay._identity(model_path)
    model = m0.load_model(model_path)
    comparison = replay.validate_replay(paths)
    if comparison['status'] != 'PASS':
        raise ValueError('whole-segment replay validation failed')
    inputs = [{k: s[k] for k in ('path', 'size_bytes', 'sha256')} for s in comparison['sources']]
    code = [replay._identity(__file__), *m0._code_identities()]
    results, sources = [], []
    for source in inputs:
        engine = H9TimeWindow(model)
        outputs, count, last = [], 0, None
        for frame in replay.iter_probe_frames(source['path']):
            last = H9WindowInput.from_replay(frame)
            outputs.extend(engine.push(last))
            count += 1
        # Deterministic end-of-file outage simulation, not measured real-time latency.
        outputs.extend(engine.tick(last.time+STALE_AFTER_MS+UPDATE_MS))
        results.extend(outputs)
        sources.append(dict(**source, input_frames=count, output_events=len(outputs),
                            status_counts=dict(Counter(r['status'] for r in outputs)),
                            eof_clock_advanced_ms=int(STALE_AFTER_MS+UPDATE_MS)))
    replay._verify_files([artifact, *inputs, *code])
    return dict(kind='provisional-h9-4s-1s-development-window-replay',
                protocol_status='DEVELOPMENT PROVISIONAL; not a frozen scientific contract',
                artifact=artifact, model_sha256=model.metadata['model_sha256'],
                feature_order=m0.FEATURE_ORDER, class_order=m0.CLASS_ORDER,
                window_ms=int(WINDOW_MS), update_ms=int(UPDATE_MS), stale_after_ms=int(STALE_AFTER_MS),
                interval='(window_end_ms - 4000, window_end_ms]',
                coverage_denominator='observed supplied H9 records; no inferred frames or changed eligibility',
                transition_policy='CSV segment/label changes or explicit manual reset only',
                stale_policy='first 1s timer tick with input age >=2000ms; clear data, collect 4s again on recovery',
                sources=sources, code=code, results=results,
                status_counts=dict(Counter(r['status'] for r in results)),
                whole_segment_aggregation_check=dict(segments=comparison['segment_count'], mismatches=0),
                notes=['Loaded model only; no training, tuning or accuracy evaluation.',
                       'Input and model are development data; window predictions are not whole-segment LOSO results.',
                       'CSV labels supply transitions/P5 exclusion; unknown inputs cannot automatically detect either.',
                       'Virtual timer clock only; no camera, host performance or sensor-to-screen measurement.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-csv', nargs='+', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    m0._new_paths(args.output)
    result = run_csv_windows(args.probe_csv, args.model)
    m0._write_new(args.output, result)
    print('WINDOW REPLAY:', result['status_counts'], '; development only, no accuracy claims')
    print('MODEL_SHA256', result['model_sha256'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
