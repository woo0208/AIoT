"""Model-independent opt-in callback benchmark; never discovers/trains models.

The caller supplies train() and predict(model, input) adapters for its existing
interface. Memory is current-process before/after observations, not operation
peak or isolated allocations. CSV columns remain the 5-E-4 columns.
"""
import time
from pathlib import Path

import engineering_exports as out
import performance_output as perf
from probe_timing import _stats, process_memory


DETAIL_FIELDS = ('metric', 'unit', 'measurement_status', 'reason', 'value', 'count', 'p50', 'p95', 'maximum')


def run_benchmark(directory, *, identity, input_value, input_id, input_sha256,
                  feature_order, seed, model=None, train=None, predict=None,
                  model_path=None, calls=20, warmup_calls=1,
                  clock_ns=time.perf_counter_ns, memory_reader=process_memory):
    """Measure only supplied operations; skipped operations remain NOT_MEASURED.

    Synthetic inputs must have scope SYNTHETIC_STRUCTURAL_TEST_ONLY. Supplying
    real callbacks is a separate explicit caller action, not done by this CLI.
    """
    if type(calls) is not int or calls < 1 or type(warmup_calls) is not int or warmup_calls < 0:
        raise ValueError('positive inference calls and nonnegative warmup required')
    if not input_id or len(input_sha256) != 64 or not feature_order or seed is None:
        raise ValueError('input identity, feature order and seed required')
    for key in ('scope', 'run_id', 'data_id', 'model_id', 'config_id', 'config_sha256', 'git', 'environment'):
        if key not in identity:
            raise ValueError('missing identity:' + key)
    out.validate_scope(identity)
    path = Path(model_path) if model_path is not None else None
    pin = dict(path=str(path.resolve()), sha256=perf.sha256(path), size_bytes=path.stat().st_size) if path else None
    root = out.reserve(directory, (path,) if path else ())
    document = dict(identity, kind='engineering-model-benchmark/1',
        run_status='RUNNING', input_id=input_id, input_sha256=input_sha256,
        feature_order=list(feature_order), seed=seed, model_artifact=pin,
        measurement_conditions=dict(clock='perf_counter_ns' if clock_ns is time.perf_counter_ns else 'injected_test_clock',
            inference_calls=calls, inference_warmup_calls=warmup_calls,
            memory='same-process before/after snapshots; no operation peak attribution'),
        raw_inference_ns=[], memory_observations={}, metrics=[], errors=[])
    document['measurement_conditions_sha256'] = out.digest(dict(
        input_id=input_id, input_sha256=input_sha256, feature_order=list(feature_order), seed=seed,
        environment=identity['environment'], measurement=document['measurement_conditions']))
    def metric(name, unit, value=None, reason='', **stats):
        measured = value is not None or bool(stats.get('count'))
        document['metrics'].append(dict(metric=name, unit=unit, value=value,
            measurement_status='MEASURED' if measured else 'NOT_MEASURED',
            reason='' if measured else reason, **stats))
    def memory(phase):
        try:
            sample = memory_reader()
        except (OSError, RuntimeError) as exc:
            sample = dict(rss_bytes=None, private_bytes=None, method=str(exc))
        document['memory_observations'][phase] = sample
        for name in ('rss_bytes', 'private_bytes'):
            metric(phase + '.' + name, 'bytes', sample.get(name), 'resource_not_supported')
    try:
        if train is not None:
            memory('train.before')
            start = clock_ns()
            model = train()
            elapsed = clock_ns() - start
            if elapsed < 0:
                raise ValueError('benchmark clock moved backwards')
            metric('training_time', 's', elapsed / 1e9)
            memory('train.after')
        else:
            metric('training_time', 's', reason='training_callback_not_run')
            for phase in ('train.before', 'train.after'):
                for name in ('rss_bytes', 'private_bytes'):
                    metric(phase + '.' + name, 'bytes', reason='training_callback_not_run')
        if predict is not None and model is not None:
            for _ in range(warmup_calls):
                predict(model, input_value)
            memory('inference.before')
            for _ in range(calls):
                start = clock_ns()
                predict(model, input_value)
                elapsed = clock_ns() - start
                if elapsed < 0:
                    raise ValueError('benchmark clock moved backwards')
                document['raw_inference_ns'].append(elapsed)
            memory('inference.after')
        else:
            for phase in ('inference.before', 'inference.after'):
                for name in ('rss_bytes', 'private_bytes'):
                    metric(phase + '.' + name, 'bytes', reason='inference_callback_or_model_not_run')
        metric('inference_time', 'ms', reason='inference_callback_or_model_not_run',
               **_stats([n / 1e6 for n in document['raw_inference_ns']]))
        if path and (perf.sha256(path) != pin['sha256'] or path.stat().st_size != pin['size_bytes']):
            raise ValueError('model artifact changed during measurement')
        metric('model_file_size', 'bytes', pin['size_bytes'] if pin else None, 'no_persisted_model_artifact')
        for phase in ('train', 'inference'):
            metric(phase + '.operation_peak_memory', 'bytes', reason='before_after_snapshots_are_not_operation_peak')
        document['run_status'] = 'COMPLETED'
    except Exception as exc:
        document.update(run_status='FAILED', errors=[str(exc)])
        perf._write_json(root / 'benchmark.json', document)
        raise
    perf._write_json(root / 'benchmark.json', document)
    inference = next(m for m in document['metrics'] if m['metric'] == 'inference_time')
    row = dict(out.common(document, 'benchmark.json'), measurement_status=inference['measurement_status'],
        reason=inference['reason'], model_sha256=pin['sha256'] if pin else None,
        input_id=input_id, calls=inference['count'], unit='ms', p50=inference['p50'], p95=inference['p95'])
    out.csv_write(root / 'model_benchmarks.csv', perf.BENCHMARK_FIELDS, [row])
    out.csv_write(root / 'model_benchmark_details.csv', DETAIL_FIELDS, document['metrics'])
    return document
