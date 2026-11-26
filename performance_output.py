"""Opt-in, non-formal engineering evidence and reproducible CSV projections.

No camera, model execution, accuracy evaluation, or research schema changes.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import threading
import uuid


SCHEMA = 'engineering-performance/1.0.0'
COMMON = ('run_id', 'data_id', 'model_id', 'config_id', 'config_sha256',
          'git_commit', 'git_dirty', 'environment_json', 'run_status', 'evidence')
RUN_FIELDS = COMMON + ('metric', 'phase', 'unit', 'measurement_status', 'reason',
                       'count', 'value', 'p50', 'p95', 'maximum')
SAMPLE_FIELDS = COMMON + ('sample_index', 'kind', 'phase', 'name', 'frame_id',
                          'token', 'host_monotonic_ns', 'duration_ns', 'value',
                          'unit', 'measurement_status', 'source_frameset_number',
                          'source_frame_number', 'device_timestamp_ms', 'timestamp_domain',
                          'process_cpu_ns', 'cpu_one_core_percent', 'rss_bytes',
                          'private_bytes', 'os_peak_rss_bytes', 'details_json')
BENCHMARK_FIELDS = COMMON + ('measurement_status', 'reason', 'model_sha256',
                             'input_id', 'calls', 'unit', 'p50', 'p95')
COMPARISON_FIELDS = COMMON + ('measurement_status', 'reason', 'comparison_id',
                              'dataset_sha256', 'evaluation_rule_id', 'support',
                              'accuracy', 'macro_f1')
CSV_FIELDS = {'performance_runs.csv': RUN_FIELDS,
              'performance_samples.csv': SAMPLE_FIELDS,
              'model_benchmarks.csv': BENCHMARK_FIELDS,
              'experiment_comparisons.csv': COMPARISON_FIELDS}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def git_identity():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=Path(__file__).parent,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    try:
        return dict(commit=git('rev-parse', 'HEAD'),
                    dirty=bool(git('status', '--porcelain', '--untracked-files=normal')),
                    status='RECORDED')
    except (OSError, subprocess.CalledProcessError) as exc:
        return dict(commit=None, dirty=None, status='NOT_MEASURED', reason=str(exc))


def environment():
    packages = {}
    for name in ('numpy', 'mediapipe', 'pyrealsense2', 'opencv-python', 'opencv-contrib-python'):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return dict(python=platform.python_version(), platform=platform.platform(),
                machine=platform.machine(), processor=platform.processor(), packages=packages)


def validate_paths(directory, timing_path, other_paths=()):
    """Resolve aliases before any output opens; directory creation is exclusive."""
    root = Path(directory).resolve()
    if Path(directory).exists() or Path(directory).is_symlink():
        raise FileExistsError(f'performance directory must be new: {directory}')
    if not root.parent.is_dir():
        raise FileNotFoundError(root.parent)
    paths = [Path(p).resolve() for p in (timing_path, *other_paths) if p is not None]
    if len(paths) != len(set(paths)):
        raise ValueError('performance output/input path collision')
    for path in paths:
        if path == root or path in root.parents or root in path.parents:
            raise ValueError(f'performance directory overlaps another path: {path}')
    if timing_path is not None:
        path = Path(timing_path)
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        if not path.parent.is_dir():
            raise FileNotFoundError(path.parent)


def _write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


class PerformanceRecorder:
    def __init__(self, directory, *, config, data_id='live-unlabelled-engineering',
                 timing_path=None, other_paths=()):
        validate_paths(directory, timing_path, other_paths)
        self.directory = Path(directory).resolve()
        config_hash = hashlib.sha256(canonical(config).encode('utf-8')).hexdigest()
        self.identity = dict(schema=SCHEMA, scope='NON_FORMAL_ENGINEERING',
                             run_id='perf_' + uuid.uuid4().hex, data_id=data_id,
                             config_id='probe-options/1', config=config,
                             config_sha256=config_hash, git=git_identity(),
                             environment=environment(), models={},
                             source_sha256={name: sha256(Path(__file__).with_name(name)) for name in
                                            ('performance_output.py', 'probe_timing.py', 'posture_geometry_probe.py')},
                             started_utc=datetime.now(timezone.utc).isoformat(),
                             initial_status='RUNNING')
        self.events = []
        self._lock = threading.RLock()
        self.directory.mkdir()  # atomic reservation; never reuse an existing directory
        _write_json(self.directory / 'manifest.json', self.identity)
        self._journal = (self.directory / 'events.jsonl').open('x', encoding='utf-8')
        self.finished = False

    def event(self, kind, **values):
        with self._lock:
            row = dict(sample_index=len(self.events) + 1, kind=kind, **values)
            self._journal.write(canonical(row) + '\n')
            self._journal.flush()
            self.events.append(row)

    def pin_models(self, paths):
        for name, path in paths.items():
            if path is not None:
                pin = dict(path=str(Path(path).resolve()), sha256=sha256(path))
                self.identity['models'][name] = pin
                self.event('model_identity', name=name, **pin)

    def device_environment(self, profile, rs):
        """Best-effort observed device/profile metadata, separate from configuration."""
        observed = {}
        for name in ('name', 'serial_number', 'firmware_version', 'usb_type_descriptor'):
            try:
                observed[name] = profile.get_device().get_info(getattr(rs.camera_info, name))
            except Exception as exc:
                observed[name] = dict(status='NOT_MEASURED', reason=str(exc))
        for name, stream in (('rgb', 'color'), ('depth', 'depth')):
            try:
                video = profile.get_stream(getattr(rs.stream, stream)).as_video_stream_profile()
                observed[name] = dict(width=video.width(), height=video.height(),
                                      fps=video.fps(), format=str(video.format()))
            except Exception as exc:
                observed[name] = dict(status='NOT_MEASURED', reason=str(exc))
        self.identity['environment']['device'] = observed
        self.event('device_environment', observed=observed)

    def fail_setup(self, error):
        """Preserve a reservation failure before a metrics object could be created."""
        self._journal.close()
        _write_json(self.directory / 'setup_failure.json',
                    dict(**self.identity, run_status='FAILED', error=str(error)))
        self.finished = True

    def sensor_frames(self, token, frames):
        """Read original SDK child IDs before alignment; never modify inputs."""
        for sensor, getter in (('rgb', 'get_color_frame'), ('depth', 'get_depth_frame')):
            try:
                child = getattr(frames, getter)()
                if not child:
                    raise ValueError('sensor child unavailable')
                number = child.get_frame_number()
                timestamp = float(child.get_timestamp())
                domain = child.get_frame_timestamp_domain()
                if (type(number) is not int or number < 0 or not math.isfinite(timestamp)
                        or domain is None or str(domain).lower() in ('', 'none', 'unknown')):
                    raise ValueError('sensor identity unavailable')
                self.event('sensor', token=token, name=sensor, source_frame_number=number,
                           device_timestamp_ms=timestamp, timestamp_domain=str(domain),
                           measurement_status='MEASURED')
            except Exception as exc:
                self.event('sensor', token=token, name=sensor,
                           measurement_status='NOT_MEASURED', reason=str(exc))

    def finish(self, report, *, timing_error=None):
        with self._lock:
            if self.finished:
                return
            self._journal.close()
            reason = report['termination']['reason']
            status = ('INTERRUPTED' if reason == 'keyboard_interrupt' or
                      report['termination'].get('requested_stop_reason') == 'keyboard_interrupt' else
                      'FAILED' if report['error'] is not None or report['cleanup_errors']
                      or timing_error is not None else
                      'INTERRUPTED' if reason in ('q', 'keyboard_interrupt') else
                      'COMPLETED' if reason in ('completed', 'duration_elapsed') else 'INCOMPLETE')
            document = dict(**self.identity, run_status=status, timing=report,
                            timing_publication_error=str(timing_error) if timing_error is not None else None,
                            events=self.events, journal_sha256=sha256(self.directory / 'events.jsonl'))
            # Preserve evidence before CSV publication. Failed exports can be regenerated.
            _write_json(self.directory / 'performance.json', document)
            try:
                export_csv(document, self.directory)
            except Exception as exc:
                _write_json(self.directory / 'export_failure.json', dict(status='FAILED', error=str(exc)))
                raise
            finally:
                self.finished = True
            return document


def csv_rows(document):
    """Pure projection: this function never measures or infers research results."""
    if document['schema'] != SCHEMA:
        raise ValueError('unsupported engineering performance schema')
    report = document['timing']
    common = dict(run_id=document['run_id'], data_id=document['data_id'],
                  model_id=canonical({k: v['sha256'] for k, v in document['models'].items()}), config_id=document['config_id'],
                  config_sha256=document['config_sha256'], git_commit=document['git']['commit'],
                  git_dirty=document['git']['dirty'], environment_json=canonical(document['environment']),
                  run_status=document['run_status'], evidence='performance.json')
    runs, samples = [], []

    def metric(name, unit, value=None, *, phase='stream', status=None, reason='', **stats):
        runs.append(dict(common, metric=name, phase=phase, unit=unit, value=value,
                         measurement_status=status or ('MEASURED' if value is not None or stats.get('count', 0) else 'NOT_MEASURED'),
                         reason=reason, **stats))

    metric('stream_seconds', 's', report['stream_seconds'])
    for name, key in (('frameset_fps', 'delivered_input_fps'), ('processed_fps', 'processed_fps')):
        metric(name, '1/s', report[key])
    for name, value in sorted(report['counts'].items()):
        metric(name, 'count', value)
    metric('unfinished_processing_frames', 'count', report['unfinished_processing_frames'])
    for name, value in report['h9_inferences'].items():
        metric('h9_inferences.' + name, 'count', value)
    for prefix, key in (('h9_first_prediction.', 'h9_first_prediction'),
                        ('h9_first_ui_submission.', 'h9_first_ui_submission')):
        for name in (('collection_start_to_ready_ms', 'stream_start_to_ready_ms')
                     if key == 'h9_first_prediction' else
                     ('collection_start_to_ui_ms', 'stream_start_to_ui_ms')):
            metric(prefix + name, 'ms', (report[key] or {}).get(name),
                   reason='' if report[key] else 'no_observed_event')
    for phase, key in (('steady', 'stage_milliseconds'), ('warmup', 'warmup_stage_milliseconds'),
                       ('collection', 'collection_stage_milliseconds')):
        for name, stats in report[key].items():
            metric(name, 'ms', phase=phase, **stats)
    for phase, values in report['process_resource_summary'].items():
        for name, stats in values.items():
            metric(name, 'percent_one_core' if name == 'cpu_one_core_percent' else 'bytes', phase=phase, **stats)

    for sensor in ('rgb', 'depth'):
        rows = [e for e in document['events'] if e['kind'] == 'sensor' and e['name'] == sensor]
        reliable = bool(rows) and all(e['measurement_status'] == 'MEASURED' for e in rows)
        domains = {e.get('timestamp_domain') for e in rows}
        previous = previous_timestamp = None
        identities = {}
        for row in rows:
            number, stamp = row.get('source_frame_number'), row.get('device_timestamp_ms')
            if number is not None:
                if previous is not None and number < previous:
                    reliable = False
                if previous_timestamp is not None and stamp < previous_timestamp:
                    reliable = False
                if number in identities and identities[number] != stamp:
                    reliable = False
                identities[number] = stamp
                previous = number
                previous_timestamp = stamp
        reliable = reliable and len(domains) == 1
        count = len(identities) if reliable else None
        why = '' if reliable else 'missing_or_inconsistent_original_sensor_identity'
        metric(sensor + '_unique_frames', 'count', count, reason=why)
        metric(sensor + '_reused_deliveries', 'count', len(rows) - count if reliable else None, reason=why)
        metric(sensor + '_unique_fps', '1/s', count / report['stream_seconds']
               if reliable and report['stream_seconds'] > 0 else None,
               reason=why or ('nonpositive_stream_duration' if report['stream_seconds'] <= 0 else ''))
        metric(sensor + '_missing_rate', 'ratio', status='NOT_MEASURED',
               reason='sensor_continuity_and_missing_rate_contract_not_verified')

    for row in document['events']:
        known = {k: row[k] for k in ('sample_index', 'kind', 'phase', 'name', 'frame_id', 'token',
                                    'host_monotonic_ns', 'duration_ns', 'source_frameset_number',
                                    'source_frame_number', 'device_timestamp_ms', 'timestamp_domain',
                                    'process_cpu_ns', 'cpu_one_core_percent', 'rss_bytes',
                                    'private_bytes', 'os_peak_rss_bytes') if k in row}
        samples.append(dict(common, **known, value=row.get('duration_ns'),
                            unit='ns' if 'duration_ns' in row else '',
                            measurement_status=row.get('measurement_status', 'MEASURED'),
                            details_json=canonical(row)))
    return {'performance_runs.csv': runs, 'performance_samples.csv': samples,
            'model_benchmarks.csv': [dict(common, measurement_status='NOT_MEASURED',
                reason='no_isolated_model_benchmark; H9 host stage samples are pipeline observations')],
            'experiment_comparisons.csv': [dict(common, measurement_status='NOT_MEASURED',
                reason='no_accuracy_evaluation_or_common_sample_comparison_performed')]}


def export_csv(document, directory):
    directory = Path(directory)
    rows = csv_rows(document)
    for name in CSV_FIELDS:
        path = directory / name
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    for name, fields in CSV_FIELDS.items():
        with (directory / name).open('x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows[name])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Regenerate engineering CSV from performance JSON; no measurements')
    parser.add_argument('performance_json')
    parser.add_argument('new_directory')
    args = parser.parse_args(argv)
    document = json.loads(Path(args.performance_json).read_text(encoding='utf-8'))
    target = Path(args.new_directory)
    target.mkdir()  # exclusive, including empty existing directories
    _write_json(target / 'performance.json', document)
    export_csv(document, target)


if __name__ == '__main__':
    main()
