"""Virtual-clock A/B fixtures, never D455 or performance evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import engineering_ab as ab
import engineering_exports as out
import performance_output as perf


def fixture():
    stats = dict(count=2, p50=10., p95=19., maximum=20.)
    timing = dict(kind='engineering-probe-host-timing', error=None, cleanup_errors=[],
        unfinished_processing_frames=0, environment=dict(python='SYNTHETIC', platform='SYNTHETIC', logical_cpus=4),
        termination=dict(reason='duration_elapsed', requested_duration_seconds=90),
        warmup_processed_frames=150, h9_warmup_calls_per_stage=5,
        delivered_input_fps=30., processed_fps=20., stage_milliseconds={'pose': stats},
        warmup_stage_milliseconds={}, collection_stage_milliseconds={},
        process_resource_summary={'stream': {n: dict(stats) for n in
                                  ('cpu_one_core_percent', 'rss_bytes', 'private_bytes')}})
    conditions = dict(device=dict(name='SYNTHETIC', serial_number='SYNTHETIC', firmware_version='SYNTHETIC',
                                  usb_type_descriptor='SYNTHETIC', rgb={'profile': 'SYNTHETIC'}, depth={'profile': 'SYNTHETIC'}),
        input=dict(id='SYNTHETIC', sha256='a'*64), config=dict(views='none'), environment=timing['environment'],
        models={}, source_sha256={'fixture.py': 'b'*64},
        measurement=dict(warmup_frames=150, h9_warmup_calls=5, requested_duration_seconds=90,
                         resource_sampler='SYNTHETIC_1_HZ', stage_clock='SYNTHETIC_NS'))
    performance = dict(schema=perf.SCHEMA, data_id=out.SYNTHETIC, run_status='COMPLETED', timing=copy.deepcopy(timing),
        config=conditions['config'], models={}, source_sha256=conditions['source_sha256'],
        environment=dict(conditions['environment'], device=conditions['device']))
    performance['timing']['processed_fps'] = 18.
    performance['timing']['stage_milliseconds']['pose']['p50'] = 11.
    identities = dict(scope=out.SYNTHETIC, **{mode: dict(json_sha256='placeholder', conditions=copy.deepcopy(conditions))
                                          for mode in ('timing_only', 'performance')})
    return timing, performance, identities


class ABTests(unittest.TestCase):
    def test_units_absolute_relative_and_no_mutation(self):
        a, b, identity = fixture()
        original = copy.deepcopy((a, b, identity))
        result = ab.compare(a, b, identity)
        self.assertEqual(result['status'], 'COMPARABLE')
        rows = {(r['metric'], r['statistic']): r for r in result['metrics']}
        self.assertEqual(rows['processed_fps', 'value']['absolute_difference'], -2)
        self.assertEqual(rows['processed_fps', 'value']['relative_change_percent'], -10)
        self.assertEqual(rows['pose', 'p50']['absolute_difference'], 1)
        self.assertEqual(rows['pose', 'p50']['unit'], 'ms')
        self.assertEqual(rows['rss_bytes', 'p95']['unit'], 'bytes')
        self.assertEqual((a, b, identity), original)

    def test_every_condition_missing_or_different_is_blocked(self):
        for condition in ab.CONDITIONS:
            for change in ('missing', 'different'):
                a, b, identity = fixture()
                if change == 'missing':
                    del identity['timing_only']['conditions'][condition]
                else:
                    identity['timing_only']['conditions'][condition] = {'other': 'SYNTHETIC'}
                result = ab.compare(a, b, identity)
                self.assertEqual(result['status'], 'BLOCKED', (condition, change))
                self.assertEqual(result['metrics'], [])

    def test_failure_warmup_and_observed_environment_block(self):
        for key, value in (('error', 'failed'), ('warmup_processed_frames', 0),
                           ('environment', {'python': 'other'}), ('unfinished_processing_frames', 1)):
            a, b, identity = fixture()
            a[key] = value
            self.assertEqual(ab.compare(a, b, identity)['status'], 'BLOCKED')

    def test_zero_baseline_relative_null_and_unsupported_private_blocks(self):
        a, b, identity = fixture()
        a['processed_fps'] = 0
        row = next(r for r in ab.compare(a, b, identity)['metrics'] if r['metric'] == 'processed_fps')
        self.assertIsNone(row['relative_change_percent'])
        a['process_resource_summary']['stream']['private_bytes'] = dict(count=0, p50=None, p95=None)
        self.assertEqual(ab.compare(a, b, identity)['status'], 'BLOCKED')

    def test_synthetic_cannot_be_relabelled_formal_or_engineering(self):
        for scope in ('FORMAL', 'NON_FORMAL_ENGINEERING'):
            a, b, identity = fixture()
            identity['scope'] = scope
            self.assertEqual(ab.compare(a, b, identity)['status'], 'BLOCKED')

    def test_raw_preservation_collision_hash_and_blocked_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b, identity = fixture()
            paths = [root / n for n in ('a.json', 'b.json', 'identity.json')]
            for path, value in zip(paths, (a, b)):
                perf._write_json(path, value)
            for mode, path in zip(('timing_only', 'performance'), paths):
                identity[mode]['json_sha256'] = perf.sha256(path)
            perf._write_json(paths[2], identity)
            result = ab.export(*paths, root / 'new')
            self.assertEqual(result['status'], 'COMPARABLE')
            for path, name in zip(paths, ('timing_only.original.json', 'performance.original.json', 'conditions.original.json')):
                self.assertEqual(path.read_bytes(), (root / 'new' / name).read_bytes())
            with self.assertRaises(FileExistsError):
                ab.export(*paths, root / 'new')
            paths[0].write_text('{}')  # synthetic fixture tamper only
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                ab.export(*paths, root / 'tampered')
            self.assertFalse((root / 'tampered').exists())
