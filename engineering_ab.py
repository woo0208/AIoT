"""Read-only timing-only / Performance A/B projection. Never starts a device.

Identity sidecars attest run conditions and bind the original JSON SHA-256.
They must be recorded for BOTH runs; an old timing JSON alone is insufficient.
"""
import argparse
import json
import math
from pathlib import Path

import engineering_exports as out
import performance_output as perf


CONDITIONS = ('device', 'input', 'config', 'environment', 'models', 'source_sha256', 'measurement')
FIELDS = ('metric', 'phase', 'statistic', 'unit', 'measurement_status', 'reason',
          'timing_only', 'performance', 'absolute_difference', 'relative_change_percent')


def _known(value):
    if value is None or (isinstance(value, str) and value in ('', 'NOT_MEASURED', 'UNKNOWN')):
        return False
    if isinstance(value, dict):
        return bool(value) and value.get('status') != 'NOT_MEASURED' and all(_known(v) for v in value.values())
    if isinstance(value, (tuple, list)):
        return bool(value) and all(_known(v) for v in value)
    return True


def _values(report):
    values = {}
    for name, key in (('frameset_fps', 'delivered_input_fps'), ('processed_fps', 'processed_fps')):
        values[name, 'stream', 'value', '1/s'] = report.get(key)
    for phase, key in (('steady', 'stage_milliseconds'), ('warmup', 'warmup_stage_milliseconds'),
                       ('collection', 'collection_stage_milliseconds')):
        for name, stats in report.get(key, {}).items():
            for stat in ('p50', 'p95'):
                values[name, phase, stat, 'ms'] = stats.get(stat) if stats.get('count') else None
    for phase, metrics in report.get('process_resource_summary', {}).items():
        for name in ('cpu_one_core_percent', 'rss_bytes', 'private_bytes'):
            stats = metrics.get(name, {})
            for stat in ('p50', 'p95'):
                values[name, phase, stat, 'percent_one_core' if name.startswith('cpu') else 'bytes'] = (
                    stats.get(stat) if stats.get('count') else None)
    return values


def compare(timing, performance, identities):
    reasons = []
    scope = identities.get('scope', 'NON_FORMAL_ENGINEERING')
    if scope not in (out.SYNTHETIC, 'NON_FORMAL_ENGINEERING'):
        reasons.append('engineering_scope_required')
    synthetic = 'SYNTHETIC' in str(performance.get('data_id', ''))
    if synthetic != (scope == out.SYNTHETIC):
        reasons.append('synthetic_scope_mismatch')
    reports = (timing, performance.get('timing', {}))
    if timing.get('kind') != 'engineering-probe-host-timing' or performance.get('schema') != perf.SCHEMA:
        reasons.append('unsupported_input_kind')
    if performance.get('run_status') != 'COMPLETED' or performance.get('timing_publication_error'):
        reasons.append('performance_run_not_completed')
    records = [identities.get(mode, {}) for mode in ('timing_only', 'performance')]
    for mode, record, report in zip(('timing_only', 'performance'), records, reports):
        conditions = record.get('conditions', {})
        if not record.get('json_sha256'):
            reasons.append(mode + ':unbound_json')
        for key in CONDITIONS:
            # Empty model inventory explicitly means no model; never an unknown model.
            if key not in conditions or (key != 'models' and not _known(conditions[key])):
                reasons.append(mode + ':missing_condition:' + key)
        for group, fields in (('device', ('name', 'serial_number', 'firmware_version', 'usb_type_descriptor', 'rgb', 'depth')),
                              ('input', ('id', 'sha256')),
                              ('environment', ('python', 'platform', 'logical_cpus')),
                              ('measurement', ('resource_sampler', 'stage_clock'))):
            if any(not _known(conditions.get(group, {}).get(field)) for field in fields):
                reasons.append(mode + ':incomplete_condition:' + group)
        measurement = conditions.get('measurement', {})
        for key, actual in (('warmup_frames', report.get('warmup_processed_frames')),
                            ('h9_warmup_calls', report.get('h9_warmup_calls_per_stage')),
                            ('requested_duration_seconds', report.get('termination', {}).get('requested_duration_seconds'))):
            if measurement.get(key) != actual or actual is None:
                reasons.append(mode + ':measurement_mismatch:' + key)
        for key, value in report.get('environment', {}).items():
            if conditions.get('environment', {}).get(key) != value:
                reasons.append(mode + ':observed_environment_mismatch:' + key)
        if (report.get('error') or report.get('cleanup_errors') or report.get('unfinished_processing_frames')
                or report.get('termination', {}).get('reason') not in ('completed', 'duration_elapsed')):
            reasons.append(mode + ':incomplete_run')
    a, b = [r.get('conditions', {}) for r in records]
    for key in CONDITIONS:
        if a.get(key) != b.get(key):
            reasons.append('different_condition:' + key)
    for key in ('config', 'models', 'source_sha256'):
        if b.get(key) != performance.get(key):
            reasons.append('performance_identity_mismatch:' + key)
    observed_environment = dict(performance.get('environment', {}))
    observed_device = observed_environment.pop('device', None)
    if (observed_device != b.get('device') or not observed_environment
            or any(b.get('environment', {}).get(k) != v for k, v in observed_environment.items())):
        reasons.append('performance_device_or_environment_mismatch')
    left, right = [_values(r) for r in reports]
    rows = []
    for key in sorted(set(left) | set(right)):
        x, y = left.get(key), right.get(key)
        valid = all(type(v) in (int, float) and math.isfinite(v) for v in (x, y))
        rows.append(dict(zip(FIELDS[:4], key), measurement_status='MEASURED' if valid else 'NOT_MEASURED',
                         reason='' if valid else 'metric_not_observed_in_both_runs', timing_only=x, performance=y,
                         absolute_difference=y-x if valid else None,
                         relative_change_percent=(y-x)/x*100 if valid and x else None))
        if valid and not x:
            rows[-1]['reason'] = 'relative_change_undefined_zero_baseline'
    required = {('frameset_fps', 'value'), ('processed_fps', 'value')}
    required.update((name, stat) for name in ('cpu_one_core_percent', 'rss_bytes', 'private_bytes') for stat in ('p50', 'p95'))
    measured = {(r['metric'], r['statistic']) for r in rows if r['phase'] == 'stream' and r['measurement_status'] == 'MEASURED'}
    stages = {r['metric'] for r in rows if r['phase'] == 'steady' and r['unit'] == 'ms'
              and r['measurement_status'] == 'MEASURED'}
    complete_stages = {name for name in stages if all(any(r['metric'] == name and r['phase'] == 'steady'
        and r['statistic'] == stat and r['measurement_status'] == 'MEASURED' for r in rows) for stat in ('p50', 'p95'))}
    if not required <= measured or not complete_stages:
        reasons.append('required_metrics_not_measured_in_both_runs')
    return dict(scope=identities.get('scope', 'NON_FORMAL_ENGINEERING'),
                status='BLOCKED' if reasons else 'COMPARABLE', reasons=sorted(set(reasons)),
                interpretation='Descriptive B-A only; no statistical significance or improvement claim.',
                condition_evidence='SHA-bound operator run-condition sidecars; no independent device attestation',
                metrics=[] if reasons else rows)


def export(timing_path, performance_path, identity_path, directory):
    paths = [Path(p) for p in (timing_path, performance_path, identity_path)]
    raw = [p.read_bytes() for p in paths]
    documents = [json.loads(b) for b in raw]
    timing, performance, identities = documents
    for mode, path in zip(('timing_only', 'performance'), paths):
        if identities.get(mode, {}).get('json_sha256') != perf.sha256(path):
            raise ValueError(mode + ': JSON SHA-256 mismatch')
    result = compare(timing, performance, identities)
    root = out.reserve(directory, paths)
    names = ('timing_only.original.json', 'performance.original.json', 'conditions.original.json')
    for name, data in zip(names, raw):
        with (root / name).open('xb') as stream:
            stream.write(data)
    result['sources'] = [dict(path=str(p.resolve()), sha256=perf.sha256(p), copy=n) for p, n in zip(paths, names)]
    perf._write_json(root / 'ab_comparison.json', result)
    out.csv_write(root / 'ab_comparison.csv', FIELDS, result['metrics'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('timing_json', 'performance_json', 'conditions_json', 'new_directory'):
        parser.add_argument(name)
    args = parser.parse_args(argv)
    result = export(args.timing_json, args.performance_json, args.conditions_json, args.new_directory)
    print(result['status'])
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
