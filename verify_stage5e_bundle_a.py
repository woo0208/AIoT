"""Reproducible synthetic Bundle A artifacts + one related regression run.

Only explicit synthetic fixtures, hand-built leaves, virtual SDKs and metrics
are used. No real model training, D455, research dataset or held-out data access.
Outputs require a new directory. Run with the existing project venv.
"""
import argparse
import json
from pathlib import Path
import unittest

import engineering_ab as ab
import engineering_exports as out
import evaluation_csv_adapter as evaluation
import performance_output as perf
import prediction_adapter as ui
from test_engineering_ab import fixture as ab_fixture
from test_evaluation_csv_adapter import fixture as evaluation_fixture
from test_model_benchmark import synthetic_benchmark
from test_performance_output import synthetic_example


MODULES = ['test_prediction_adapter', 'test_engineering_ab', 'test_model_benchmark',
    'test_evaluation_csv_adapter', 'test_performance_output', 'test_probe_timing',
    'test_h9_probe_timing', 'test_h9_probe_integration', 'test_h9_async_runtime',
    'test_h9_time_window', 'test_h9_csv_replay', 'test_stage5e_readiness',
    'test_live_f1_d455', 'test_capture_end_timing']
FORMAL_TESTS = ['test_dimensions_common_keys_reference_exclusion_and_supports',
    'test_technical_missing_labels_and_conflicting_identity', 'test_existing_adapter_and_h_sample_bridges',
    'test_missing_class_blocks_before_any_fit', 'test_non_development_data_blocked_before_values',
    'test_metrics_incomplete_and_tie_priority', 'test_freeze_gate_never_calls_loader_until_hashes_settings_and_models_match']
PIN_FILES = ['formal6_evaluation.py', 'rf_experiment.py', 'h9_m0.py', 'h9_async_runtime.py',
    'h9_time_window.py', 'f1_features.py', 'f1_demo_rf.py', 'f1_sample_aggregator.py',
    'posture_geometry.py', 'performance_output.py', 'probe_timing.py',
    'docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md', 'RESEARCH_DATA_SCHEMA.md']


def generate(root):
    perf._write_json(root / 'prediction_demo.json', dict(scope=out.SYNTHETIC, views=ui.demo_views()))
    a, b, identities = ab_fixture()
    for name, value in (('timing_only.synthetic.json', a), ('performance.synthetic.json', b)):
        perf._write_json(root / name, value)
    for mode, name in (('timing_only', 'timing_only.synthetic.json'), ('performance', 'performance.synthetic.json')):
        identities[mode]['json_sha256'] = perf.sha256(root / name)
    perf._write_json(root / 'ab_conditions.synthetic.json', identities)
    result = ab.export(root / 'timing_only.synthetic.json', root / 'performance.synthetic.json',
                       root / 'ab_conditions.synthetic.json', root / 'ab_comparable')
    assert result['status'] == 'COMPARABLE'
    del identities['timing_only']['conditions']['device']
    perf._write_json(root / 'ab_conditions_missing.synthetic.json', identities)
    blocked = ab.export(root / 'timing_only.synthetic.json', root / 'performance.synthetic.json',
                       root / 'ab_conditions_missing.synthetic.json', root / 'ab_blocked')
    assert blocked['status'] == 'BLOCKED'
    benchmark = synthetic_benchmark(root)
    for incomplete in (False, True):
        report, metadata = evaluation_fixture(incomplete=incomplete)
        prefix = 'incomplete' if incomplete else 'complete'
        source, meta = root / f'{prefix}.evaluation.synthetic.json', root / f'{prefix}.metadata.synthetic.json'
        perf._write_json(source, report)
        metadata['result_sha256'] = perf.sha256(source)
        perf._write_json(meta, metadata)
        converted = evaluation.export(source, meta, root / f'evaluation_{prefix}')
        assert converted['status'] == ('INCOMPLETE' if incomplete else 'COMPLETE')
    report, document = synthetic_example(root / 'legacy_performance')
    assert document['timing'] == report
    perf.main([str(root / 'legacy_performance/performance.json'), str(root / 'legacy_regenerated')])
    byte_identical = {}
    for name in ('performance.json', *perf.CSV_FIELDS):
        assert (root / 'legacy_performance' / name).read_bytes() == (root / 'legacy_regenerated' / name).read_bytes()
        byte_identical[name] = perf.sha256(root / 'legacy_performance' / name)
    return dict(ab_status=result['status'], insufficient_ab_status=blocked['status'],
        benchmark_status=benchmark['run_status'], legacy_byte_identical=byte_identical)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('new_directory')
    parser.add_argument('--artifacts-only', action='store_true', help='generate synthetic outputs without rerunning tests')
    args = parser.parse_args(argv)
    root = out.reserve(args.new_directory)
    before = {name: perf.sha256(name) for name in PIN_FILES}
    generated = generate(root)
    if args.artifacts_only:
        perf._write_json(root / 'artifacts.json', dict(scope=out.SYNTHETIC, **generated, tests_run=0))
        print('Synthetic artifacts generated; tests were not rerun.')
        return 0
    names = MODULES + ['test_formal6_evaluation.FormalEvaluationTests.' + name for name in FORMAL_TESTS]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    with (root / 'integrated_tests.log').open('x', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    after = {name: perf.sha256(name) for name in PIN_FILES}
    summary = dict(scope=out.SYNTHETIC, tests_run=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped),
        passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        success=result.wasSuccessful(), modules=names, artifacts=generated,
        source_pins_before=before, source_pins_after=after, sources_preserved=before == after,
        hardware_execution='NOT_RUN', research_data_access='NOT_RUN',
        research_model_training='NOT_RUN', formal_evaluation='NOT_RUN',
        formal_execution_authorization='UNCHANGED_DEFERRED')
    perf._write_json(root / 'verification.json', summary)
    print(json.dumps({k: summary[k] for k in ('tests_run', 'passed', 'failures', 'errors', 'skipped', 'success', 'sources_preserved')}, indent=2))
    return 0 if result.wasSuccessful() and before == after else 1


if __name__ == '__main__':
    raise SystemExit(main())
