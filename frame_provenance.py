"""Opt-in engineering frame metadata observer. Never retains frames or pixels.

Single receive-loop writer; buffered until finalization to avoid per-frame I/O.
This does not filter, change timestamps, or decide scientific input eligibility.
"""
from functools import wraps
from importlib import metadata
import math
from pathlib import Path
import time

import engineering_exports as out
import performance_output as perf
from probe_timing import _stats


def measured(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        start = self.clock_ns()
        try:
            return method(self, *args, **kwargs)
        finally:
            self.cost_ns.append(self.clock_ns() - start)
    return call


def snapshot(frame):
    """Use only SDK accessors; unavailable fields remain explicitly unmeasured."""
    if not frame:
        return dict(status='NOT_MEASURED', reason='frame_unavailable')
    result = {}
    for name, getter in (
        ('number', lambda: frame.get_frame_number()),
        ('timestamp_ms', lambda: float(frame.get_timestamp())),
        ('timestamp_domain', lambda: str(frame.get_frame_timestamp_domain())),
        ('profile_uid', lambda: frame.get_profile().unique_id()),
        ('stream_type', lambda: str(frame.get_profile().stream_type())),
        ('stream_index', lambda: frame.get_profile().stream_index()),
    ):
        try:
            value = getter()
            if (value is None or (name == 'number' and (type(value) is not int or value < 0))
                    or (name == 'timestamp_ms' and not math.isfinite(value))
                    or (name == 'timestamp_domain' and value.lower() in ('', 'none', 'unknown'))):
                raise ValueError('invalid SDK metadata')
            result[name] = value
        except Exception as exc:
            result[name] = None
            result.setdefault('unavailable', {})[name] = str(exc)
    core = ('number', 'timestamp_ms', 'timestamp_domain', 'profile_uid', 'stream_type', 'stream_index')
    result['status'] = 'MEASURED' if all(result.get(n) is not None for n in core) else 'NOT_MEASURED'
    return result


def compare(previous, current, *, across_align=False):
    if not previous or previous.get('status') != 'MEASURED' or current.get('status') != 'MEASURED':
        return dict(status='NOT_MEASURED')
    fields = ('number', 'timestamp_ms', 'timestamp_domain', 'stream_type', 'stream_index')
    # Align can produce a cloned profile. Keep that difference visible separately.
    if not across_align:
        fields += ('profile_uid',)
    changes = {n + '_changed': previous[n] != current[n] for n in fields}
    boundary = (previous['timestamp_domain'] != current['timestamp_domain']
                or previous['stream_type'] != current['stream_type']
                or previous['stream_index'] != current['stream_index']
                or (not across_align and previous['profile_uid'] != current['profile_uid'])
                or current['number'] < previous['number']
                or current['timestamp_ms'] < previous['timestamp_ms'])
    result = dict(status='MEASURED', **changes,
        same_identity=all(not v for v in changes.values()),
        boundary=boundary,
        source_gap=None if boundary or across_align else max(0, current['number'] - previous['number'] - 1),
        timestamp_interval_ms=None if boundary or across_align else current['timestamp_ms'] - previous['timestamp_ms'])
    result['profile_uid_changed'] = previous['profile_uid'] != current['profile_uid']
    return result


class FrameProvenance:
    def __init__(self, directory, *, headless=False, clock_ns=time.perf_counter_ns):
        self.directory = out.reserve(directory)
        self.clock_ns = clock_ns
        self.cost_ns = []
        self.rows = []
        self.previous = {'raw': {}, 'aligned': {}}
        self.finished = False
        self.device = dict(status='NOT_MEASURED')
        self.identity = dict(kind='engineering-frame-provenance/1', scope='NON_FORMAL_ENGINEERING',
            headless=headless, clock='time.perf_counter_ns',
            clock_info=vars(time.get_clock_info('perf_counter')),
            sdk_distribution=metadata.version('pyrealsense2'),
            source_sha256={n: perf.sha256(Path(__file__).with_name(n)) for n in
                           ('frame_provenance.py', 'posture_geometry_probe.py')},
            limitations=['Metadata identity is not pixel equality or actual sensor production count.',
                'Run device identity is not a per-frame physical-sensor or reconnection proof.',
                'Buffered numeric metadata only; kill/power loss may leave manifest only.',
                'Observer cost covers accessor/bookkeeping calls, excludes outer branch/clock-call overhead.',
                'QPC boundaries are host API observations, never device-clock subtraction.'])
        perf._write_json(self.directory/'manifest.json', dict(self.identity, status='RUNNING'))

    def device_environment(self, profile, rs):
        observed = {}
        for name in ('name', 'serial_number', 'firmware_version', 'usb_type_descriptor'):
            try:
                observed[name] = profile.get_device().get_info(getattr(rs.camera_info, name))
            except Exception as exc:
                observed[name] = dict(status='NOT_MEASURED', reason=str(exc))
        self.device = observed

    def begin_receive(self):
        row = dict(receive_index=len(self.rows)+1, status='waiting', receive_call_start_qpc_ns=self.clock_ns())
        self.rows.append(row)
        return row

    def _children(self, row, boundary, children):
        row[boundary] = {name: snapshot(frame) for name, frame in children.items()}
        row[boundary+'_vs_previous'] = {name: compare(self.previous[boundary].get(name), value)
                                      for name, value in row[boundary].items()}
        self.previous[boundary] = row[boundary]

    @measured
    def received(self, row, ready, frames, end_ns, token):
        row.update(receive_call_end_qpc_ns=end_ns, token=token, status='received' if ready else 'timeout')
        if ready:
            children = {}
            for name, getter in (('rgb','get_color_frame'), ('depth','get_depth_frame')):
                try:
                    children[name] = getattr(frames, getter)()
                except Exception:
                    children[name] = None
            self._children(row, 'raw', children)

    @measured
    def aligned(self, row, color, depth):
        row['align_return_observed_qpc_ns'] = self.clock_ns()
        self._children(row, 'aligned', dict(rgb=color, depth=depth))
        row['raw_vs_aligned'] = {n: compare(row['raw'][n], row['aligned'][n], across_align=True)
                                 for n in ('rgb','depth')}

    @measured
    def processing_started(self, row, frame_id):
        row.update(status='processing', frame_id=frame_id, processing_start_qpc_ns=self.clock_ns())

    @measured
    def processing_completed(self, row):
        row.update(status='completed', processing_end_qpc_ns=self.clock_ns())

    def finish(self, *, status, error=None, cleanup_errors=()):
        if self.finished:
            return
        start = self.clock_ns()
        with (self.directory/'frames.jsonl').open('x', encoding='utf-8', newline='\n') as stream:
            for row in self.rows:
                stream.write(perf.canonical(row)+'\n')
        publication_ns = self.clock_ns()-start
        perf._write_json(self.directory/'summary.json', dict(self.identity, device=self.device,
            status=status, error=str(error) if error is not None else None,
            cleanup_errors=[str(e) for e in cleanup_errors], receive_calls=len(self.rows),
            journal_sha256=perf.sha256(self.directory/'frames.jsonl'),
            observer_call_cost_ms=_stats([n/1e6 for n in self.cost_ns]),
            observer_call_cost_total_ns=sum(self.cost_ns),
            journal_publication_ns=publication_ns,
            publication_note='Shutdown only; summary/hash/setup I/O cost not included in observer call cost.',
            sensor_missing_rate='NOT_MEASURED'))
        self.finished = True
