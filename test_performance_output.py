"""Synthetic clocks/SDK objects only; no participant data, hardware or training."""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import csv
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np

import performance_output as perf
import posture_geometry_probe as probe
import probe_timing
import test_h9_probe_integration as integration


def child(number, timestamp=None, domain='synthetic_clock'):
    return NS(get_frame_number=lambda: number,
              get_timestamp=lambda: number * 100 if timestamp is None else timestamp,
              get_frame_timestamp_domain=lambda: domain)


def pair(rgb, depth):
    return NS(get_color_frame=lambda: rgb, get_depth_frame=lambda: depth)


def synthetic_example(directory):
    """Explicit structural fixture; these numbers are never performance evidence."""
    directory = Path(directory)
    recorder = perf.PerformanceRecorder(directory, data_id='SYNTHETIC_STRUCTURAL_TEST_ONLY',
        config=dict(measurement_source='SYNTHETIC_VIRTUAL_CLOCK', fixture='stage5e4/1'))
    clock = NS(ns=0, cpu=0)
    metrics = probe_timing.ProbeMetrics(directory / 'host_timing.json', performance=recorder,
        warmup_frames=1, clock_ns=lambda: clock.ns, cpu_clock_ns=lambda: clock.cpu,
        memory_reader=lambda: dict(rss_bytes=1234, private_bytes=567, os_peak_rss_bytes=1500,
                                   method='SYNTHETIC_STRUCTURAL_TEST_ONLY'),
        metadata=dict(measurement_source='SYNTHETIC_VIRTUAL_CLOCK'))
    metrics.begin_stream()
    for i, (rgb, depth, duration) in enumerate(((1, 1, 10), (1, 2, 20), (2, 3, 40)), 1):
        token = metrics.input_received(i)
        recorder.sensor_frames(token, pair(child(rgb), child(depth)))
        with metrics.stage('synthetic.pose', i):
            clock.ns += duration * 1_000_000
        metrics.ui_submitted(token, i)
        metrics.frame_completed(token, i)
    metrics.receive_timeout()
    token = metrics.input_received(5)
    recorder.sensor_frames(token, pair(child(3), None))
    metrics.invalid_pair(token)
    clock.ns = 1_000_000_000
    clock.cpu = 500_000_000
    report = metrics.finish(termination=dict(reason='duration_elapsed', requested_duration_seconds=1))
    return report, json.loads((directory / 'performance.json').read_text(encoding='utf-8'))


class PerformanceOutputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def read_csv(self, path):
        with Path(path).open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            return reader.fieldnames, list(reader)

    def test_csv_fields_units_percentiles_counts_and_json_preservation(self):
        report, document = synthetic_example(self.root / 'run')
        self.assertEqual(document['timing'], report)
        self.assertEqual(json.loads((self.root / 'run/host_timing.json').read_text()), report)
        for name, fields in perf.CSV_FIELDS.items():
            actual, rows = self.read_csv(self.root / 'run' / name)
            self.assertEqual(actual, list(fields))
            self.assertTrue(rows)
            self.assertTrue(all(r['run_id'] == document['run_id'] for r in rows))
            self.assertTrue(all(r['config_sha256'] == document['config_sha256'] for r in rows))
        _, rows = self.read_csv(self.root / 'run/performance_runs.csv')
        values = {(r['metric'], r['phase']): r for r in rows}
        stage = values['synthetic.pose', 'steady']
        self.assertEqual((stage['unit'], stage['count'], stage['p50'], stage['p95']), ('ms', '2', '30.0', '39.0'))
        self.assertEqual(values['synthetic.pose', 'warmup']['count'], '1')
        self.assertEqual(values['frameset_fps', 'stream']['value'], '4.0')
        self.assertEqual(values['processed_fps', 'stream']['value'], '3.0')
        self.assertEqual(values['rgb_unique_frames', 'stream']['value'], '3')
        self.assertEqual(values['rgb_reused_deliveries', 'stream']['value'], '1')
        self.assertEqual(values['depth_unique_fps', 'stream']['measurement_status'], 'NOT_MEASURED')
        self.assertEqual(values['cpu_one_core_percent', 'stream']['maximum'], '50.0')
        for sensor in ('rgb', 'depth'):
            row = values[sensor + '_missing_rate', 'stream']
            self.assertEqual((row['measurement_status'], row['value']), ('NOT_MEASURED', ''))
        for name in ('model_benchmarks.csv', 'experiment_comparisons.csv'):
            _, rows = self.read_csv(self.root / 'run' / name)
            self.assertEqual(rows[0]['measurement_status'], 'NOT_MEASURED')
            self.assertTrue(rows[0]['reason'])

    def test_raw_stages_resources_and_counts_can_be_cross_checked(self):
        report, document = synthetic_example(self.root / 'run')
        events = document['events']
        for phase, key in (('steady', 'stage_milliseconds'), ('warmup', 'warmup_stage_milliseconds')):
            for name, stats in report[key].items():
                values = [e['duration_ns'] / 1e6 for e in events
                          if e['kind'] == 'stage' and e['phase'] == phase and e['name'] == name]
                self.assertEqual(len(values), stats['count'])
                self.assertEqual(float(np.percentile(values, 50)), stats['p50'])
                self.assertEqual(float(np.percentile(values, 95)), stats['p95'])
        self.assertEqual(sum(e['kind'] == 'input' for e in events), report['counts']['input_framesets'])
        self.assertEqual(sum(e['kind'] == 'frame_completed' for e in events), report['counts']['processed_frames'])
        self.assertEqual(sum(e['kind'] == 'invalid_pair' for e in events), report['counts']['missing_color_or_depth'])
        _, samples = self.read_csv(self.root / 'run/performance_samples.csv')
        resources = [r for r in samples if r['kind'] == 'resource']
        self.assertEqual(len(resources), len(report['process_resource_samples']))
        self.assertEqual(resources[-1]['rss_bytes'], '1234')
        journal = (self.root / 'run/events.jsonl')
        self.assertEqual([json.loads(line) for line in journal.read_text().splitlines()], events)
        self.assertEqual(perf.sha256(journal), document['journal_sha256'])

    def test_regeneration_is_byte_identical_and_refuses_overwrite(self):
        synthetic_example(self.root / 'run')
        perf.main([str(self.root / 'run/performance.json'), str(self.root / 'regenerated')])
        for name in (*perf.CSV_FIELDS, 'performance.json'):
            self.assertEqual((self.root / 'run' / name).read_bytes(), (self.root / 'regenerated' / name).read_bytes())
        with self.assertRaises(FileExistsError):
            perf.main([str(self.root / 'run/performance.json'), str(self.root / 'regenerated')])

    def test_reuse_changes_neither_frameset_count_nor_original_sensor_time(self):
        recorder = perf.PerformanceRecorder(self.root / 'run', config={})
        clock = NS(ns=0)
        metrics = probe_timing.ProbeMetrics(self.root / 'timing.json', performance=recorder,
            clock_ns=lambda: clock.ns, cpu_clock_ns=lambda: 0, memory_reader=lambda: {})
        metrics.begin_stream()
        for i, (rgb, depth) in enumerate(((1, 1), (1, 2), (2, 3)), 1):
            token = metrics.input_received(i)
            recorder.sensor_frames(token, pair(child(rgb), child(depth)))
            metrics.frame_completed(token, i)
        clock.ns = 1_000_000_000
        report = metrics.finish()
        document = json.loads((recorder.directory / 'performance.json').read_text())
        rows = perf.csv_rows(document)['performance_runs.csv']
        values = {r['metric']: r for r in rows if r['phase'] == 'stream'}
        self.assertEqual(values['rgb_unique_frames']['value'], 2)
        self.assertEqual(values['depth_unique_frames']['value'], 3)
        self.assertEqual(report['counts']['processed_frames'], 3)
        rgb = [e for e in document['events'] if e['kind'] == 'sensor' and e['name'] == 'rgb']
        self.assertEqual([r['device_timestamp_ms'] for r in rgb], [100, 100, 200])
        self.assertEqual(values['rgb_unique_fps']['value'], 2.)
        self.assertEqual(values['depth_unique_fps']['value'], 3.)
        self.assertEqual(values['frameset_fps']['value'], 3.)

    def test_unknown_regressed_changed_domain_or_reused_identity_stays_unmeasured(self):
        for index, rgb in enumerate(((child(2), child(1)), (child(1), child(1, 999)),
                                     (child(1), child(2, domain='changed')), (None, child(2)),
                                     (child(1), child(2, 50)), (child(1, domain=None), child(2)))):
            recorder = perf.PerformanceRecorder(self.root / str(index), config={})
            metrics = probe_timing.ProbeMetrics(recorder.directory / 'timing.json', performance=recorder,
                clock_ns=lambda: 0, cpu_clock_ns=lambda: 0, memory_reader=lambda: {})
            for i, color in enumerate(rgb):
                recorder.sensor_frames(i, pair(color, child(i)))
            metrics.finish()
            doc = json.loads((recorder.directory / 'performance.json').read_text())
            rows = perf.csv_rows(doc)['performance_runs.csv']
            self.assertTrue(all(r['measurement_status'] == 'NOT_MEASURED'
                                for r in rows if r['metric'] in ('rgb_unique_frames', 'rgb_missing_rate')))

    def test_paths_alias_existing_output_and_directory_overlap_are_blocked(self):
        original = self.root / 'original.json'
        original.write_text('original')
        for timing, paths in ((original, ()), (self.root / 'same', (self.root / './same',)),
                              (self.root / 'run/timing.json', ()), (None, (self.root / 'run/other.csv',))):
            with self.assertRaises((ValueError, FileExistsError)):
                perf.PerformanceRecorder(self.root / 'run', config={}, timing_path=timing, other_paths=paths)
            self.assertFalse((self.root / 'run').exists())
        self.assertEqual(original.read_text(), 'original')
        (self.root / 'run').mkdir()
        with self.assertRaises(FileExistsError):
            perf.PerformanceRecorder(self.root / 'run', config={})

    def test_config_hash_is_canonical_and_model_bytes_are_pinned(self):
        recorder = perf.PerformanceRecorder(self.root / 'run', config=dict(b=2, a=1))
        model = self.root / 'synthetic_model_bytes'
        model.write_bytes(b'SYNTHETIC; never executed')
        recorder.pin_models({'fixture': model})
        metrics = probe_timing.ProbeMetrics(self.root / 'timing.json', performance=recorder)
        metrics.finish()
        doc = json.loads((recorder.directory / 'performance.json').read_text())
        import hashlib
        self.assertEqual(doc['config_sha256'], hashlib.sha256(perf.canonical(dict(a=1, b=2)).encode()).hexdigest())
        self.assertEqual(doc['models']['fixture']['sha256'], perf.sha256(model))
        self.assertEqual(len(doc['source_sha256']), 3)
        self.assertIn('packages', doc['environment'])

    def test_runtime_cleanup_interrupt_and_pending_frame_evidence(self):
        for index, (reason, error, cleanup, status) in enumerate((
            ('error', ValueError('synthetic failure'), [], 'FAILED'),
            ('q', None, [RuntimeError('synthetic close')], 'FAILED'),
            ('keyboard_interrupt', KeyboardInterrupt(), [], 'INTERRUPTED'),
            ('q', None, [], 'INTERRUPTED'))):
            recorder = perf.PerformanceRecorder(self.root / str(index), config={})
            metrics = probe_timing.ProbeMetrics(recorder.directory / 'timing.json', performance=recorder,
                clock_ns=lambda: 0, cpu_clock_ns=lambda: 0, memory_reader=lambda: {})
            metrics.begin_stream()
            metrics.input_received(1)
            metrics.record_ns('synthetic.failed_stage', 1_000_000, 1)
            metrics.finish(error=error, cleanup_errors=cleanup, termination=dict(reason=reason))
            doc = json.loads((recorder.directory / 'performance.json').read_text())
            self.assertEqual(doc['run_status'], status)
            self.assertEqual(doc['timing']['unfinished_processing_frames'], 1)
            self.assertEqual(doc['timing']['stage_milliseconds']['synthetic.failed_stage']['p50'], 1.)

    def test_timing_publication_race_preserves_original_and_performance_failure(self):
        recorder = perf.PerformanceRecorder(self.root / 'run', config={})
        metrics = probe_timing.ProbeMetrics(self.root / 'timing.json', performance=recorder)
        metrics.output_path.write_text('racing original')
        with self.assertRaises(FileExistsError):
            metrics.finish()
        self.assertEqual(metrics.output_path.read_text(), 'racing original')
        doc = json.loads((recorder.directory / 'performance.json').read_text())
        self.assertEqual(doc['run_status'], 'FAILED')
        self.assertIsNotNone(doc['timing_publication_error'])

    def test_csv_export_failure_preserves_json_and_flushed_events(self):
        recorder = perf.PerformanceRecorder(self.root / 'run', config={})
        metrics = probe_timing.ProbeMetrics(self.root / 'timing.json', performance=recorder)
        metrics.record_ns('synthetic', 100)
        target = recorder.directory / 'performance_runs.csv'
        target.write_text('racing original')
        with self.assertRaises(FileExistsError):
            metrics.finish()
        self.assertEqual(target.read_text(), 'racing original')
        self.assertTrue((recorder.directory / 'performance.json').is_file())
        self.assertTrue((recorder.directory / 'export_failure.json').is_file())
        self.assertIn('synthetic', (recorder.directory / 'events.jsonl').read_text())

    def test_metrics_constructor_race_preserves_setup_failure_without_sdk(self):
        with patch.object(probe_timing, 'ProbeMetrics', side_effect=FileExistsError('synthetic reservation race')):
            with self.assertRaises(FileExistsError):
                probe.run_probe(performance_output_dir=str(self.root / 'run'))
        failure = json.loads((self.root / 'run/setup_failure.json').read_text())
        self.assertEqual(failure['run_status'], 'FAILED')
        self.assertIn('synthetic reservation race', failure['error'])

    def test_h9_collection_warmup_and_inference_events_are_only_pipeline_observations(self):
        recorder = perf.PerformanceRecorder(self.root / 'run', config={})
        clock = NS(ns=0)
        metrics = probe_timing.ProbeMetrics(self.root / 'timing.json', performance=recorder,
            clock_ns=lambda: clock.ns, cpu_clock_ns=lambda: 0, memory_reader=lambda: {})
        metrics.begin_stream()
        with metrics.h9_stage('h9.aggregate', collecting=True): clock.ns += 1_000_000
        for i in range(2):
            with metrics.h9_stage('h9.m0_infer'): clock.ns += 2_000_000
            prediction = dict(prediction_id=str(i), source_last_input_frame_index=i + 1,
                              accumulation_start_host_ms='0', source_last_input_host_ms='0')
            metrics.h9_prediction_ready(dict(status='PREDICTED', display_prediction=prediction))
            metrics.h9_ui_submitted(prediction, clock.ns)
        metrics.finish()
        document = json.loads((recorder.directory / 'performance.json').read_text())
        rows = perf.csv_rows(document)
        values = {(r['metric'], r['phase']): r for r in rows['performance_runs.csv']}
        self.assertEqual(values['h9.m0_infer', 'warmup']['count'], 1)
        self.assertEqual(values['h9.m0_infer', 'steady']['count'], 1)
        self.assertEqual(values['h9.aggregate', 'collection']['count'], 1)
        self.assertEqual(values['h9_inferences.total_successful', 'stream']['value'], 2)
        self.assertEqual(sum(e['kind'] == 'h9_prediction_ready' for e in document['events']), 2)
        self.assertEqual(rows['model_benchmarks.csv'][0]['measurement_status'], 'NOT_MEASURED')

    def test_zero_duration_and_unavailable_resource_fields_stay_empty(self):
        recorder = perf.PerformanceRecorder(self.root / 'run', config={})
        metrics = probe_timing.ProbeMetrics(self.root / 'timing.json', performance=recorder,
            clock_ns=lambda: 0, cpu_clock_ns=lambda: 0, memory_reader=lambda: {})
        metrics.begin_stream()
        recorder.sensor_frames(1, pair(child(1), child(1)))
        metrics.finish()
        doc = json.loads((recorder.directory / 'performance.json').read_text())
        rows = perf.csv_rows(doc)['performance_runs.csv']
        for row in rows:
            if row['metric'] in ('rss_bytes', 'rgb_unique_fps', 'depth_unique_fps'):
                self.assertEqual(row['measurement_status'], 'NOT_MEASURED')
                self.assertIsNone(row['value'])

    def run_probe(self, directory, *, enabled=True, failure=None, sensor_ids=False, **kwargs):
        with ExitStack() as stack:
            fake = integration.SyntheticProbe(NS(enterContext=stack.enter_context), [0, 100, 200])
            model = self.root / 'synthetic_model_pin.bin'
            if not model.exists():
                model.write_bytes(b'SYNTHETIC PIN; fake SDK never reads this model')
            import sys
            sys.modules['analyze_d455'].ensure_models = lambda: dict(pose=model, mesh=model, face=model)
            if sensor_ids:
                original_next = fake.next_event
                def next_with_original_children():
                    frames = original_next()
                    i = frames.get_frame_number()
                    rgb, depth = frames.get_color_frame(), frames.get_depth_frame()
                    number = 1 if i <= 2 else 2
                    for target, source in ((rgb, child(number)), (depth, child(i))):
                        target.get_frame_number = source.get_frame_number
                        target.get_timestamp = source.get_timestamp
                        target.get_frame_timestamp_domain = source.get_frame_timestamp_domain
                    return frames
                fake.next_event = next_with_original_children
                def align(frames):
                    # Alignment has different synthetic metadata; only originals are evidence.
                    color, depth = frames.get_color_frame(), frames.get_depth_frame()
                    return pair(NS(get_data=color.get_data, get_frame_number=lambda: 999),
                                NS(get_data=depth.get_data, get_frame_number=lambda: 999))
                sys.modules['pyrealsense2'].align = lambda _: NS(process=align)
            if failure is not None:
                fake.calculate.side_effect = failure
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            try:
                probe.run_probe(timing_output_path=str(directory / 'legacy.json') if not enabled else None,
                    performance_output_dir=str(directory / 'perf') if enabled else None, **kwargs)
            finally:
                fake.pipeline.stop.assert_called_once()
            return fake

    def test_opt_in_real_loop_uses_same_geometry_calls_and_preserves_legacy_json_values(self):
        baseline = self.root / 'baseline'; baseline.mkdir()
        measured = self.root / 'measured'; measured.mkdir()
        old = self.run_probe(baseline, enabled=False)
        new = self.run_probe(measured)
        self.assertEqual(old.calculate.call_count, new.calculate.call_count)
        self.assertEqual(old.pose.detect_for_video.call_count, new.pose.detect_for_video.call_count)
        legacy = json.loads((baseline / 'legacy.json').read_text())
        document = json.loads((measured / 'perf/performance.json').read_text())
        self.assertEqual(legacy, document['timing'])
        self.assertEqual(document['timing']['counts']['processed_frames'], 3)
        self.assertEqual(document['run_status'], 'INTERRUPTED')

    def test_real_loop_failure_and_setup_failure_are_recorded_without_hardware(self):
        with self.assertRaisesRegex(ValueError, 'synthetic geometry'):
            self.run_probe(self.root, failure=ValueError('synthetic geometry'))
        doc = json.loads((self.root / 'perf/performance.json').read_text())
        self.assertEqual(doc['run_status'], 'FAILED')
        self.assertEqual(doc['timing']['unfinished_processing_frames'], 1)
        with self.assertRaises(FileNotFoundError):
            probe.run_probe(h9_model_path=str(self.root / 'missing_model'),
                            performance_output_dir=str(self.root / 'setup_failure'))
        doc = json.loads((self.root / 'setup_failure/performance.json').read_text())
        self.assertEqual(doc['run_status'], 'FAILED')
        self.assertEqual(doc['timing']['termination']['reason'], 'error')

    def test_real_loop_records_original_children_before_alignment_without_deduplicating(self):
        fake = self.run_probe(self.root, sensor_ids=True)
        doc = json.loads((self.root / 'perf/performance.json').read_text())
        rgb = [e for e in doc['events'] if e['kind'] == 'sensor' and e['name'] == 'rgb']
        depth = [e for e in doc['events'] if e['kind'] == 'sensor' and e['name'] == 'depth']
        self.assertEqual([e['source_frame_number'] for e in rgb], [1, 1, 2])
        self.assertEqual([e['source_frame_number'] for e in depth], [1, 2, 3])
        self.assertEqual([e['device_timestamp_ms'] for e in rgb], [100, 100, 200])
        self.assertEqual(fake.calculate.call_count, 3)
        self.assertEqual(fake.pose.detect_for_video.call_count, 3)

    def test_cli_and_existing_csv_fail_before_any_hardware(self):
        with patch.object(probe, 'run_probe') as run:
            probe.main(['--performance-output-dir', 'new', '--performance-data-id', 'SYNTHETIC',
                        '--timing-warmup-frames', '2', '--timing-h9-warmup-calls', '5'])
            self.assertEqual(run.call_args.kwargs['performance_output_dir'], 'new')
            self.assertEqual(run.call_args.kwargs['performance_data_id'], 'SYNTHETIC')
        existing = self.root / 'existing.csv'; existing.write_text('original')
        with self.assertRaises(FileExistsError):
            probe.run_probe(face_diag_csv_path=str(existing), performance_output_dir=str(self.root / 'run'))
        self.assertFalse((self.root / 'run').exists())
        self.assertEqual(existing.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
