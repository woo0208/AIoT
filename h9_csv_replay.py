"""Sequential engineering CSV adapter; unchanged whole-segment H9 aggregation.

No camera, RF inference/training, accuracy evaluation or sliding windows.
CSV data-row numbers are adapter frame identities, not hardware frame numbers.
Device timestamp and UTC tokens are preserved verbatim; equal device times
with distinct frame indices are retained. Duplicate/decreasing indices,
decreasing device time, conflicting identities and reopened segments fail
closed before changing buffer state. Index gaps are reported, never filled.
The existing coverage denominator remains the number of supplied records.

Run: python -B h9_csv_replay.py --probe-csv P01.csv P02.csv --output NEW.json
This compares aggregation only, including retained P5 segments; it does not
authorize or run a six-class evaluation. Existing output files are refused.
"""

import argparse
import csv
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from collections.abc import Mapping

import f1_sample_aggregator as aggregation
import h6_offline as offline


FEATURE_ORDER = aggregation.H9_FEATURE_NAMES


@dataclass(frozen=True)
class H9ReplayFrame:
    """One observed input, including PREP/TRANSITION with no H9 record."""

    frame_index: int
    recording_id: str
    subject: str
    segment_id: str
    original_label: str
    device_timestamp_ms: str
    timestamp_utc: str
    record: aggregation.HFrameRecord | None

    def __post_init__(self):
        if type(self.frame_index) is not int or self.frame_index < 1:
            raise ValueError('frame_index must be a positive integer')
        for name in ('recording_id', 'subject', 'segment_id', 'original_label',
                     'device_timestamp_ms', 'timestamp_utc'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'missing replay {name}')
        if not self.device_time.is_finite():
            raise ValueError('non-finite device timestamp')
        if self.original_label in offline.NON_EVALUATION_LABELS:
            if self.record is not None:
                raise ValueError('PREP/TRANSITION must not enter H9 aggregation')
        else:
            label = offline.analysis_label(self.original_label)
            r = self.record
            if (not isinstance(r, aggregation.HFrameRecord)
                    or (r.frame_index, r.recording_id, r.subject, r.step, r.label,
                        r.analysis_run_id, r.round) !=
                    (self.frame_index, self.recording_id, self.subject, self.segment_id,
                     label, 'probe-csv:'+self.recording_id, None)):
                raise ValueError('replay/H9 record identity mismatch')

    @property
    def device_time(self):
        try:
            return Decimal(self.device_timestamp_ms.strip())
        except InvalidOperation as exc:
            raise ValueError('invalid device timestamp') from exc

    @property
    def label(self):
        return self.record.label if self.record is not None else self.original_label


@dataclass(frozen=True)
class H9ReplaySegment:
    sample: aggregation.HSampleResult
    frames: tuple[H9ReplayFrame, ...]
    emitted_on: str


class H9SequentialBuffer:
    """One recording, one active segment; push returns its completed predecessor.

    PREP/TRANSITION terminate the preceding posture and remain order-checked.
    finish() emits the final posture exactly once. Repeated posture labels with
    different segment IDs remain separate. No timing-based segmentation occurs.
    """

    def __init__(self):
        self._last = None
        self._active = []
        self._closed_segments = set()
        self._finished = False
        self.frame_count = 0
        self.excluded_frame_count = 0
        self.equal_timestamp_count = 0
        self.frame_index_gap_count = 0

    def _complete(self, emitted_on):
        if not self._active or self._active[0].record is None:
            return None
        frames = tuple(self._active)
        sample = aggregation.aggregate_h5_h9_sample(f.record for f in frames)
        return H9ReplaySegment(sample, frames, emitted_on)

    def push(self, frame):
        if self._finished:
            raise ValueError('buffer already finished')
        if not isinstance(frame, H9ReplayFrame):
            raise ValueError('expected H9ReplayFrame')
        previous = self._last
        changing = previous is not None and previous.segment_id != frame.segment_id
        if previous is not None:
            if (previous.recording_id, previous.subject) != (frame.recording_id, frame.subject):
                raise ValueError('recording/subject changed; use a new buffer')
            if frame.frame_index <= previous.frame_index:
                raise ValueError('duplicate or out-of-order frame index')
            if frame.device_time < previous.device_time:
                raise ValueError('out-of-order device timestamp')
            if not changing and frame.label != previous.label:
                raise ValueError('conflicting label within segment')
            if changing and frame.segment_id in self._closed_segments:
                raise ValueError('closed segment cannot be reopened')
        # Finish/validation before mutation keeps a rejected push from consuming input.
        completed = self._complete('segment_transition') if changing else None
        if changing:
            self._closed_segments.add(previous.segment_id)
            self._active = []
        if previous is not None:
            self.equal_timestamp_count += int(frame.device_time == previous.device_time)
            self.frame_index_gap_count += frame.frame_index-previous.frame_index-1
        self._active.append(frame)
        self._last = frame
        self.frame_count += 1
        self.excluded_frame_count += int(frame.record is None)
        return completed

    def finish(self):
        if self._finished:
            return None
        completed = self._complete('end_of_stream')
        self._active = []
        self._finished = True
        return completed


def iter_probe_frames(path):
    """Read CSV in physical order; reuse HFrameRecord validation and label mapping."""
    required = {'artifact_kind', *offline.PROBE_IDENTITY_FIELDS, *FEATURE_ORDER,
                'device_timestamp_ms', 'timestamp_utc'}
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                or not required.issubset(reader.fieldnames)):
            raise ValueError('missing or duplicate replay CSV columns')
        count = 0
        for count, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'malformed replay CSV row {count}')
            if row['artifact_kind'] != offline.EXPLORATORY_ARTIFACT_KIND:
                raise ValueError(f'unexpected probe artifact kind at row {count}')
            identity = {name: row[name].strip() for name in offline.PROBE_IDENTITY_FIELDS}
            if not all(identity.values()):
                raise ValueError(f'empty replay identity at row {count}')
            record = None
            if identity['label'] not in offline.NON_EVALUATION_LABELS:
                record = aggregation.HFrameRecord(
                    analysis_run_id='probe-csv:'+identity['recording_id'],
                    recording_id=identity['recording_id'], frame_index=count,
                    subject=identity['subject'], round=None, step=identity['segment_id'],
                    label=offline.analysis_label(identity['label']),
                    features={name: float(row[name]) if row[name].strip() else None
                              for name in FEATURE_ORDER})
            yield H9ReplayFrame(
                frame_index=count, recording_id=identity['recording_id'],
                subject=identity['subject'], segment_id=identity['segment_id'],
                original_label=identity['label'], device_timestamp_ms=row['device_timestamp_ms'],
                timestamp_utc=row['timestamp_utc'], record=record)
        if not count:
            raise ValueError('empty replay CSV')


def _identity(path):
    path = Path(path).resolve(strict=True)
    return dict(path=str(path), size_bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _verify_files(identities):
    for item in identities:
        if _identity(item['path']) != item:
            raise ValueError(f"file changed during replay: {item['path']}")


def _sample_document(sample):
    return {f.name: dict(value) if isinstance(value, Mapping) else value
            for f in fields(sample) for value in (getattr(sample, f.name),)}


def validate_replay(paths):
    """Compare every whole posture segment with the unchanged offline loader.

    Equality includes feature floats, circular resultant, support indices,
    missing counts, eligibility/reasons and identity. No tolerance is applied.
    """
    sources = [_identity(p) for p in paths]
    if not sources or len({Path(s['path']) for s in sources}) != len(sources):
        raise ValueError('missing or duplicate input path')
    code = [_identity(p) for p in (__file__, aggregation.__file__, offline.__file__)]
    expected = {s.sample_key: s for s in offline.load_labeled_probe_h_samples(
        [s['path'] for s in sources])}
    comparisons, source_rows, seen = [], [], set()
    max_delta = dict.fromkeys(FEATURE_ORDER, 0.0)
    for source in sources:
        buffer = H9SequentialBuffer()
        trace, emitted = [], []
        for frame in iter_probe_frames(source['path']):
            completed = buffer.push(frame)
            if completed is not None:
                emitted.append(completed)
            trace.append([frame.frame_index, frame.device_timestamp_ms, frame.timestamp_utc,
                          frame.segment_id, frame.original_label])
        completed = buffer.finish()
        if completed is not None:
            emitted.append(completed)
        for completed in emitted:
            actual = completed.sample
            key = actual.sample_key
            if key in seen or key not in expected:
                raise ValueError(f'duplicate or unbound replay sample: {key}')
            seen.add(key)
            reference = expected[key]
            mismatches = [f.name for f in fields(actual)
                          if getattr(actual, f.name) != getattr(reference, f.name)]
            if tuple(actual.features) != FEATURE_ORDER:
                mismatches.append('feature_order')
            deltas = {}
            for name in FEATURE_ORDER:
                a, b = actual.features[name], reference.features[name]
                deltas[name] = a-b if a is not None and b is not None else None
                if deltas[name] is not None:
                    max_delta[name] = max(max_delta[name], abs(deltas[name]))
            comparisons.append(dict(sample=_sample_document(actual),
                                    emitted_on=completed.emitted_on,
                                    original_labels=sorted({f.original_label for f in completed.frames}),
                                    matches_offline=not mismatches, mismatched_fields=mismatches,
                                    feature_deltas=deltas,
                                    offline_sample=_sample_document(reference) if mismatches else None))
        source_rows.append(dict(**source, frame_count=buffer.frame_count,
                                excluded_prep_transition_frames=buffer.excluded_frame_count,
                                equal_timestamp_count=buffer.equal_timestamp_count,
                                frame_index_gap_count=buffer.frame_index_gap_count,
                                posture_segment_count=len(emitted),
                                trace_columns=['csv_data_row', 'device_timestamp_ms_original',
                                               'timestamp_utc_original', 'segment_id', 'original_label'],
                                frame_trace=trace))
    if seen != set(expected):
        raise ValueError('replay/offline sample coverage mismatch')
    _verify_files([*sources, *code])
    mismatched = sum(not row['matches_offline'] for row in comparisons)
    return dict(kind='h9-sequential-csv-whole-segment-aggregation-check',
                status='PASS' if mismatched == 0 else 'FAIL', feature_order=FEATURE_ORDER,
                aggregation_spec=aggregation.H_AGGREGATION_SPEC_ID, sources=source_rows, code=code,
                segment_count=len(comparisons), mismatched_segment_count=mismatched,
                max_absolute_feature_difference=max_delta, segments=comparisons,
                notes=['Engineering probe CSV adapter, not a frozen scientific schema.',
                       'All original posture segments retained, including P5; no class evaluation or RF.',
                       'CSV data-row identity is not a hardware frame number.',
                       'No synthetic replacement for missing observations or index gaps.',
                       'Exact offline aggregation comparison; no real-time speed or latency claim.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-csv', nargs='+', required=True)
    parser.add_argument('--output', help='new JSON file only; omit to print to stdout')
    args = parser.parse_args(argv)
    if args.output and Path(args.output).exists():
        raise FileExistsError(f'refusing to overwrite output: {args.output}')
    result = validate_replay(args.probe_csv)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)+'\n'
    if args.output:
        with Path(args.output).open('x', encoding='utf-8') as stream:
            stream.write(encoded)
        print(f"{result['status']}: {result['segment_count']} segments; "
              f"mismatches={result['mismatched_segment_count']}; output={args.output}")
    else:
        print(encoded, end='')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
