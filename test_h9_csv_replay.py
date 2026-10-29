"""Synthetic stream/CSV tests only; participant inputs and all model fits excluded."""

import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import f1_sample_aggregator as aggregation
import h6_offline as offline
import h9_csv_replay as replay


FIELDS = ('artifact_kind', *offline.PROBE_IDENTITY_FIELDS, 'device_timestamp_ms',
          'timestamp_utc', *aggregation.H9_FEATURE_NAMES)


def frame(index, *, segment='1', label='upright', missing=(), timestamp=None,
          recording='synthetic-recording', subject='synthetic-subject'):
    record = None
    if label not in offline.NON_EVALUATION_LABELS:
        features = {name: None if name in missing else index+j/10
                    for j, name in enumerate(aggregation.H9_FEATURE_NAMES)}
        if aggregation.H_FACE_AXIS_FEATURE not in missing:
            features[aggregation.H_FACE_AXIS_FEATURE] = 179.0 if index % 2 else -179.0
        record = aggregation.HFrameRecord(
            analysis_run_id='probe-csv:'+recording, recording_id=recording,
            frame_index=index, subject=subject, round=None, step=segment,
            label=offline.analysis_label(label), features=features)
    return replay.H9ReplayFrame(index, recording, subject, segment, label,
                               timestamp if timestamp is not None else f'{index}.000',
                               f'2026-10-28T00:00:00.{index:06d}+00:00', record)


def csv_row(f):
    values = (dict(f.record.features) if f.record is not None
              else dict.fromkeys(aggregation.H9_FEATURE_NAMES, 'not-parsed'))
    return dict(values, artifact_kind=offline.EXPLORATORY_ARTIFACT_KIND,
                subject=f.subject, recording_id=f.recording_id, segment_id=f.segment_id,
                label=f.original_label, device_timestamp_ms=f.device_timestamp_ms,
                timestamp_utc=f.timestamp_utc)


class H9ReplayTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for obj, name in ((offline, 'evaluate_samples'), (offline.rf, 'fit_models'),
                          (offline.rf.Forest, 'fit'), (offline.rf.Forest, 'predict')):
            self.enterContext(patch.object(obj, name, side_effect=AssertionError('no RF/evaluation')))

    def csv(self, frames=None, *, rows=None, fields=FIELDS, name='synthetic.csv'):
        path = self.root/name
        with path.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows if rows is not None else [csv_row(f) for f in frames])
        return path

    def consume(self, frames):
        buffer = replay.H9SequentialBuffer()
        emitted = []
        for f in frames:
            result = buffer.push(f)
            if result is not None:
                emitted.append(result)
        result = buffer.finish()
        if result is not None:
            emitted.append(result)
        return buffer, emitted

    def test_exact_feature_order_scalar_median_circular_mean_and_eof(self):
        frames = [frame(i) for i in range(1, 31)]
        buffer, result = self.consume(frames)
        self.assertEqual(len(result), 1)
        segment = result[0]
        self.assertEqual(segment.frames, tuple(frames))
        self.assertEqual(segment.sample, aggregation.aggregate_h5_h9_sample(f.record for f in frames))
        self.assertEqual(tuple(segment.sample.features), aggregation.H9_FEATURE_NAMES)
        self.assertTrue(segment.sample.eligible)
        for j, name in enumerate(aggregation.H9_FEATURE_NAMES):
            if name == aggregation.H_FACE_AXIS_FEATURE:
                self.assertAlmostEqual(abs(segment.sample.features[name]), 180.0)
            else:
                self.assertAlmostEqual(segment.sample.features[name], 15.5+j/10)
        self.assertEqual(segment.emitted_on, 'end_of_stream')
        self.assertIsNone(buffer.finish())
        with self.assertRaisesRegex(ValueError, 'finished'):
            buffer.push(frame(31))

    def test_missing_observations_keep_denominator_support_and_eligibility(self):
        feature = aggregation.H9_FEATURE_NAMES[-1]
        frames = [frame(i, missing=(feature,) if i > 30 else ()) for i in range(1, 61)]
        _, result = self.consume(frames)
        sample = result[0].sample
        self.assertTrue(sample.eligible)
        self.assertEqual((sample.n_frames, sample.common_valid_count, sample.common_coverage), (60, 30, .5))
        self.assertEqual(sample.missing_counts[feature], 30)
        self.assertIsNone(result[0].frames[-1].record.features[feature])
        self.assertEqual(sample.common_valid_frame_indices, tuple(range(1, 31)))
        path = self.csv(frames)
        replayed = replay.validate_replay([path])
        self.assertEqual(replayed['status'], 'PASS')
        self.assertEqual(replayed['segments'][0]['sample']['missing_counts'][feature], 30)
        _, low_coverage = self.consume([*frames, frame(61, missing=(feature,))])
        self.assertIn('common_coverage<0.5', low_coverage[0].sample.eligibility_reasons)
        _, too_few = self.consume([frame(i, missing=(feature,) if i == 30 else ()) for i in range(1, 31)])
        self.assertIn('common_valid_frames<30', too_few[0].sample.eligibility_reasons)
        with self.assertRaisesRegex(ValueError, 'ineligible'):
            too_few[0].sample.ordered_values('H9')
        _, entirely_missing = self.consume([frame(i, missing=aggregation.H9_FEATURE_NAMES) for i in range(1, 31)])
        self.assertTrue(all(v is None for v in entirely_missing[0].sample.features.values()))

    def test_prep_transition_and_repeated_posture_are_separate_segments(self):
        frames = [frame(1, segment='0', label='PREP')]
        frames += [frame(i) for i in range(2, 32)]
        frames += [frame(32, segment='2', label='TRANSITION')]
        frames += [frame(i, segment='3') for i in range(33, 63)]
        buffer, result = self.consume(frames)
        self.assertEqual(buffer.excluded_frame_count, 2)
        self.assertEqual([r.sample.sample_key[-1] for r in result], ['1', '3'])
        self.assertEqual(result[0].sample.input_frame_indices, tuple(range(2, 32)))
        self.assertEqual(result[1].sample.input_frame_indices, tuple(range(33, 63)))
        self.assertEqual(result[0].emitted_on, 'segment_transition')
        self.assertEqual(result[1].emitted_on, 'end_of_stream')
        self.assertNotEqual(result[0].sample.features, result[1].sample.features)

    def test_direct_segment_change_emits_only_predecessor(self):
        buffer = replay.H9SequentialBuffer()
        for i in range(1, 31):
            self.assertIsNone(buffer.push(frame(i)))
        previous = buffer.push(frame(31, segment='2', label='forward_head'))
        self.assertEqual(previous.sample.n_frames, 30)
        current = buffer.finish()
        self.assertEqual(current.sample.input_frame_indices, (31,))
        self.assertFalse(current.sample.eligible)
        self.assertIsNone(replay.H9SequentialBuffer().finish())

    def test_duplicate_reverse_indices_rejected_without_consuming_input(self):
        buffer = replay.H9SequentialBuffer()
        buffer.push(frame(1))
        buffer.push(frame(2))
        for f in (frame(2), frame(1), frame(1, segment='2')):
            with self.assertRaisesRegex(ValueError, 'duplicate or out-of-order'):
                buffer.push(f)
        for i in range(3, 31):
            buffer.push(frame(i))
        self.assertEqual(buffer.frame_count, 30)
        self.assertEqual(buffer.finish().sample.n_frames, 30)

    def test_timestamp_tokens_equal_times_retained_reverse_times_rejected(self):
        buffer = replay.H9SequentialBuffer()
        a = frame(1, timestamp=' 1000.0000 ')
        b = frame(2, timestamp='1000.0000')
        buffer.push(a)
        buffer.push(b)
        with self.assertRaisesRegex(ValueError, 'device timestamp'):
            buffer.push(frame(3, timestamp='999.999'))
        buffer.push(frame(3, timestamp='1000.0001'))
        result = buffer.finish()
        self.assertEqual(buffer.equal_timestamp_count, 1)
        self.assertEqual(result.frames[0].device_timestamp_ms, ' 1000.0000 ')
        self.assertEqual(result.frames[1].timestamp_utc, b.timestamp_utc)
        for timestamp in ('', 'NaN', 'Infinity', 'bad'):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                frame(1, timestamp=timestamp)

    def test_index_gap_is_observed_not_imputed_or_added_to_coverage(self):
        buffer, result = self.consume([frame(1), frame(3)])
        self.assertEqual(buffer.frame_index_gap_count, 1)
        self.assertEqual(result[0].sample.input_frame_indices, (1, 3))
        self.assertEqual(result[0].sample.n_frames, 2)
        self.assertEqual(result[0].sample.common_coverage, 1.0)

    def test_conflicting_identity_label_and_reopened_segment_fail_before_flush(self):
        buffer = replay.H9SequentialBuffer()
        buffer.push(frame(1))
        for f, message in ((frame(2, label='lean_back'), 'conflicting label'),
                           (frame(2, recording='other'), 'recording/subject'),
                           (frame(2, subject='other'), 'recording/subject')):
            with self.assertRaisesRegex(ValueError, message):
                buffer.push(f)
        result = buffer.push(frame(2, segment='2'))
        self.assertEqual(result.sample.input_frame_indices, (1,))
        with self.assertRaisesRegex(ValueError, 'reopened'):
            buffer.push(frame(3, segment='1'))
        result = buffer.push(frame(3, segment='3'))
        self.assertEqual(result.sample.input_frame_indices, (2,))
        self.assertEqual(buffer.frame_count, 3)
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            replace(frame(4), segment_id='other')

    def test_csv_exact_offline_match_original_times_labels_and_stream_order(self):
        frames = [frame(1, segment='0', label='PREP')]
        frames += [frame(i, segment=segment, label=label)
                   for start,segment,label in ((2,'1','upright'), (32,'3','body_forward'), (62,'13','upright'))
                   for i in range(start,start+30)]
        frames[-1] = replace(frames[-1], device_timestamp_ms=frames[-2].device_timestamp_ms)
        path = self.csv(frames)
        before = path.read_bytes()
        result = replay.validate_replay([path])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['segment_count'], 3)
        self.assertEqual([s['sample']['sample_key'][-1] for s in result['segments']], ['1','3','13'])
        self.assertEqual(result['segments'][1]['sample']['label'], 'lean_forward')
        self.assertEqual(result['segments'][1]['original_labels'], ['body_forward'])
        self.assertTrue(all(d == 0.0 for d in result['max_absolute_feature_difference'].values()))
        trace = result['sources'][0]['frame_trace']
        self.assertEqual(trace, [[f.frame_index,f.device_timestamp_ms,f.timestamp_utc,f.segment_id,f.original_label] for f in frames])
        self.assertEqual(result['sources'][0]['equal_timestamp_count'], 1)
        json.dumps(result, allow_nan=False)
        with self.assertRaisesRegex(ValueError, 'duplicate input'):
            replay.validate_replay([path, path])

    def test_csv_requires_well_formed_identity_features_timestamps_and_header(self):
        good = csv_row(frame(1))
        cases = [('timestamp', {**good, 'device_timestamp_ms':''}, FIELDS),
                 ('utc', {**good, 'timestamp_utc':''}, FIELDS),
                 ('identity', {**good, 'segment_id':''}, FIELDS),
                 ('nonfinite', {**good, aggregation.H9_FEATURE_NAMES[0]:'NaN'}, FIELDS),
                 ('kind', {**good, 'artifact_kind':'wrong'}, FIELDS),
                 ('header', good, FIELDS+('segment_id',)),
                 ('missing_header', good, tuple(f for f in FIELDS if f!='timestamp_utc'))]
        for name,row,header in cases:
            path = self.csv(rows=[row], fields=header, name=name+'.csv')
            with self.subTest(name=name), self.assertRaises(ValueError):
                list(replay.iter_probe_frames(path))
        path = self.csv(rows=[], name='empty.csv')
        with self.assertRaisesRegex(ValueError, 'empty'):
            list(replay.iter_probe_frames(path))
        path = self.csv(rows=[good], name='malformed.csv')
        with path.open('a', encoding='utf-8', newline='') as stream:
            stream.write('too,few,columns\n')
        with self.assertRaisesRegex(ValueError, 'malformed'):
            list(replay.iter_probe_frames(path))

    def test_mismatch_report_identifies_feature_and_numeric_difference(self):
        path = self.csv([frame(i) for i in range(1, 31)])
        original = replay.H9SequentialBuffer._complete
        def altered(buffer, emitted_on):
            result = original(buffer, emitted_on)
            if result is None:
                return None
            features = dict(result.sample.features)
            features[aggregation.H9_FEATURE_NAMES[0]] += .25
            return replace(result, sample=replace(result.sample, features=features))
        with patch.object(replay.H9SequentialBuffer, '_complete', altered):
            result = replay.validate_replay([path])
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['mismatched_segment_count'], 1)
        self.assertEqual(result['segments'][0]['mismatched_fields'], ['features'])
        self.assertEqual(result['max_absolute_feature_difference'][aggregation.H9_FEATURE_NAMES[0]], .25)

    def test_cli_exclusive_output_and_no_replay_on_overwrite(self):
        path = self.csv([frame(i) for i in range(1, 31)])
        output = self.root/'new-result.json'
        args = ['--probe-csv', str(path), '--output', str(output)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(replay.main(args), 0)
        before = output.read_bytes()
        with patch.object(replay, 'validate_replay', side_effect=AssertionError('must not replay')):
            with self.assertRaisesRegex(FileExistsError, 'overwrite'):
                replay.main(args)
        self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
