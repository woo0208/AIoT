"""Synthetic callbacks and virtual clock only. No research model training."""
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

import engineering_exports as out
import model_benchmark as bench
import performance_output as perf


def identity():
    return dict(scope=out.SYNTHETIC, run_id='SYNTHETIC_BENCHMARK', data_id=out.SYNTHETIC,
        model_id='SYNTHETIC_CALLBACK', config_id='synthetic-benchmark/1', config_sha256=out.digest({'fixture': 1}),
        git=dict(commit=None, dirty=None), environment=perf.environment())


def synthetic_benchmark(root):
    root = Path(root)
    artifact = root / 'SYNTHETIC_MODEL.json'
    perf._write_json(artifact, {'synthetic_model': True, 'constant': 0})
    clock = NS(ns=0)
    durations = iter((500, 10, 20, 40))  # first inference warmup is excluded
    def train():
        clock.ns += 2_000_000_000
        return 'SYNTHETIC_MODEL'
    def predict(model, value):
        clock.ns += next(durations) * 1_000_000
        return 0
    return bench.run_benchmark(root / 'benchmark', identity=identity(), input_value=[1, 2],
        input_id=out.SYNTHETIC, input_sha256=out.digest([1, 2]), feature_order=['SYNTHETIC_X'], seed=0,
        train=train, predict=predict, model_path=artifact, calls=3, warmup_calls=1,
        clock_ns=lambda: clock.ns, memory_reader=lambda: dict(rss_bytes=1024, private_bytes=512, method='SYNTHETIC'))


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_percentiles_training_seconds_file_size_memory_and_schema(self):
        result = synthetic_benchmark(self.root)
        metrics = {m['metric']: m for m in result['metrics']}
        self.assertEqual(metrics['training_time']['value'], 2.)
        self.assertEqual(metrics['inference_time']['p50'], 20.)
        self.assertEqual(metrics['inference_time']['p95'], 38.)
        self.assertEqual(result['raw_inference_ns'], [10_000_000, 20_000_000, 40_000_000])
        self.assertEqual(metrics['model_file_size']['value'], (self.root / 'SYNTHETIC_MODEL.json').stat().st_size)
        self.assertEqual(metrics['train.before.rss_bytes']['value'], 1024)
        self.assertEqual(metrics['train.operation_peak_memory']['measurement_status'], 'NOT_MEASURED')
        import csv
        with (self.root / 'benchmark/model_benchmarks.csv').open() as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, list(perf.BENCHMARK_FIELDS))
            self.assertEqual(next(reader)['p95'], '38.0')

    def test_unexecuted_operations_are_not_measured(self):
        result = bench.run_benchmark(self.root / 'empty', identity=dict(identity(), run_status='COMPLETED'), input_value=[], input_id='synthetic',
            input_sha256=out.digest([]), feature_order=['x'], seed=0)
        metrics = {m['metric']: m for m in result['metrics']}
        for name in ('training_time', 'inference_time', 'model_file_size'):
            self.assertEqual(metrics[name]['measurement_status'], 'NOT_MEASURED')
            self.assertIsNone(metrics[name]['value'])
        self.assertEqual(len(result['measurement_conditions_sha256']), 64)

    def test_input_identity_and_collision_checked_before_callbacks(self):
        from unittest.mock import Mock
        train = Mock()
        args = dict(identity=identity(), input_value=[], input_id='SYNTHETIC', input_sha256=out.digest([]),
                    feature_order=['x'], seed=0, train=train)
        with self.assertRaises(FileExistsError):
            bench.run_benchmark(self.root, **args)
        with self.assertRaises(ValueError):
            bench.run_benchmark(self.root / 'bad', **dict(args, input_sha256=''))
        train.assert_not_called()

    def test_inference_only_and_unsupported_memory(self):
        result = bench.run_benchmark(self.root / 'inference', identity=identity(), input_value=[], input_id='SYNTHETIC',
            input_sha256=out.digest([]), feature_order=['x'], seed=0, model='synthetic',
            predict=lambda m, x: 0, calls=2, memory_reader=lambda: dict(rss_bytes=None, private_bytes=None))
        metrics = {m['metric']: m for m in result['metrics']}
        self.assertEqual(metrics['training_time']['measurement_status'], 'NOT_MEASURED')
        self.assertEqual(metrics['inference_time']['count'], 2)
        self.assertEqual(metrics['inference.before.private_bytes']['measurement_status'], 'NOT_MEASURED')

    def test_failed_callback_evidence_preserved(self):
        def fail():
            raise RuntimeError('synthetic failure')
        with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
            bench.run_benchmark(self.root / 'failed', identity=identity(), input_value=[], input_id='SYNTHETIC',
                input_sha256=out.digest([]), feature_order=['x'], seed=0, train=fail)
        import json
        self.assertEqual(json.loads((self.root / 'failed/benchmark.json').read_text())['run_status'], 'FAILED')

    def test_synthetic_scope_cannot_be_relabelled(self):
        for scope in ('FORMAL', 'NON_FORMAL_ENGINEERING'):
            with self.assertRaisesRegex(ValueError, 'scope'):
                bench.run_benchmark(self.root / scope, identity=dict(identity(), scope=scope), input_value=[],
                    input_id='SYNTHETIC', input_sha256=out.digest([]), feature_order=['x'], seed=0)
