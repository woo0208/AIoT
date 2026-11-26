"""Research B exchange mode. One SDK consumer, bounded raw FIFO, latest-only AI input."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import os
import queue
import shutil
import tempfile
import threading
import time
from collections import Counter, defaultdict, deque

import numpy as np

from e0_storage import write_json
from exchange_native import NOT_RECORDED, NativeRGBDSource
from raw_rgbd_recording import RESERVE_BYTES, RawRecordingError, native_packet

SDK_WAIT_MS = 250
RECEIVE_GAP_MS = 2 * SDK_WAIT_MS
TIMEOUT_HISTORY_LIMIT = 16
RAW_QUEUE_CAPACITY_15FPS = 16
WRITER_DRAIN_TIMEOUT_S = 30
WRITER_TRACE_LIMIT = 64
WRITER_PERCENTILE_LIMIT = 16_384


class RawPairQueue(queue.Queue):
    """Record enqueue depth while Queue still holds its mutex."""
    def __init__(self, capacity):
        super().__init__(capacity)
        self.peak = 0
        self.recent_enqueues = deque(maxlen=WRITER_TRACE_LIMIT)

    def _put(self, item):
        super()._put(item)
        depth = self._qsize()
        self.peak = max(self.peak, depth)
        row = item[1]
        self.recent_enqueues.append(dict(receive_index=row['receive_index'],
            received_host_ns=row['receive_end_ns'], enqueued_host_ns=time.perf_counter_ns(), depth=depth))

    def telemetry(self):
        with self.mutex:
            return dict(peak=self.peak, recent_enqueues=list(self.recent_enqueues))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _wait_diagnostic(wait):
    if wait is None:
        return NOT_RECORDED
    start_ns, returned_ns, outcome = wait
    return dict(started_host_ns=start_ns, returned_host_ns=returned_ns, outcome=outcome,
                elapsed_ms=(returned_ns-start_ns)/1e6)


def read_environment(path):
    fields = ('session_alias', 'height_m', 'subject_distance_m', 'yaw_deg', 'pitch_deg', 'setup')
    supplied = json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else {}
    if not isinstance(supplied, dict) or set(supplied).difference(fields):
        raise ValueError('Unknown capture environment field')
    for key, value in supplied.items():
        if key in ('session_alias', 'setup'):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{key} must be nonempty text')
        elif type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        elif key in ('height_m', 'subject_distance_m') and value <= 0:
            raise ValueError(f'{key} must be positive')
    return {key: supplied.get(key, 'NOT_RECORDED') for key in fields}


def preflight(raw, camera, duration):
    if (not raw.requested and not getattr(raw.exchange, 'guided', False)) or not raw.events or not raw.events.session_id:
        raise ValueError('Exchange requires raw ON and a session ID')
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Expected positive capture duration')
    model = camera['device']['name']
    if model['status'] != 'MEASURED' or not model['value']:
        raise ValueError('Camera model unavailable')
    rate = 0
    for name, fmt, channels in [('color', 'bgr8', 3), ('depth', 'z16', 2)]:
        s = camera['streams'][name]
        intr = s['intrinsics']
        if (any(type(s[k]) is not int or s[k] <= 0 for k in ('width', 'height', 'fps'))
                or str(s['format']).lower().split('.')[-1] != fmt
                or min(intr['fx'], intr['fy']) <= 0 or not intr['model']
                or len(intr['coeffs']) != 5):
            raise ValueError(f'Invalid {name} stream or intrinsics')
        rate += s['width'] * s['height'] * s['fps'] * channels
    extr = camera['depth_to_color_extrinsics']
    if (camera['depth_scale_m'] <= 0 or len(extr['rotation']) != 9 or len(extr['translation']) != 3
            or camera['alignment'] != 'NONE_NATIVE_STREAMS'):
        raise ValueError('Invalid native depth calibration')
    rotation = np.asarray(extr['rotation'], dtype=float).reshape(3, 3)
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-4) or not np.isclose(np.linalg.det(rotation), 1, atol=1e-4):
        raise ValueError('Invalid depth-to-color rotation matrix')
    for stream in camera['streams'].values():
        intr = stream['intrinsics']
        if not all(math.isfinite(x) for x in (intr['fx'], intr['fy'], intr['ppx'], intr['ppy'], *intr['coeffs'])):
            raise ValueError('Non-finite intrinsics')
    if not all(math.isfinite(x) for x in (*extr['rotation'], *extr['translation'], camera['depth_scale_m'])):
        raise ValueError('Non-finite extrinsics/depth scale')
    required = math.ceil(rate * duration * 1.05) + RESERVE_BYTES
    with tempfile.TemporaryFile(dir=raw.directory.parent) as probe:
        probe.write(b'write check')
        probe.flush()
        os.fsync(probe.fileno())
    if shutil.disk_usage(raw.directory.parent).free < required:
        raise OSError(f'Insufficient disk space: require {required} free bytes')
    return required


class ExchangeCapture:
    def __init__(self, raw, *, environment, record_imu, duration, fps=15, capacity=None, guided=False,
                 capture_only=False, rgb_preview=False):
        if capacity is None:
            capacity = RAW_QUEUE_CAPACITY_15FPS if fps == 15 else 8
        if capacity < 1:
            raise ValueError('Positive raw queue capacity required')
        if fps not in (15, 30):
            raise ValueError('Exchange RGB-D FPS must be 15 or 30')
        self.raw = raw
        self.root = raw.directory.parent
        self.environment = environment
        self.record_imu = record_imu
        self.duration = duration
        self.fps = fps
        self.guided = guided
        if guided and capture_only:
            raise ValueError('Capture-only and guided capture are mutually exclusive')
        if rgb_preview and not capture_only:
            raise ValueError('RGB preview requires capture-only')
        self.capture_only = capture_only
        self._rgb_preview = deque(maxlen=1) if rgb_preview else None
        self.record_measurement = None
        self.preview_pairs = 0
        self.recording_start_event = None
        self.first_recorded_callback_ns = None
        self.latest_reference = self.analysis_reference = None
        self.requested_profiles = None
        self.pending = RawPairQueue(capacity)
        self.stop_request = threading.Event()
        self.source_done = threading.Event()
        self.available = threading.Condition()
        self.event_lock = threading.RLock()
        self.latest = None
        self.measurement_armed = False
        self.producer = self.writer = self.motion = None
        self.errors = []
        self.acquired = self.enqueued = self.overflows = self.analysis_completed = 0
        self.analysis_replaced = self.timeouts = 0
        self.consecutive_timeouts = self.max_consecutive_timeouts = 0
        self.active_since_ns = None
        self.max_receive_gap_ns = 0
        self.tail_gap_ns = None
        self.receive_gap_failed = False
        self.receive_gap_diagnostics = None
        self.last_accepted_pair = None
        self.wait_started_ns = None
        self.last_wait = None
        self.timeout_history = deque(maxlen=TIMEOUT_HISTORY_LIMIT)
        self.failure_stop_ns = None
        self.native_source = None
        self.storage_ns = Counter()
        self.storage_max_ns = Counter()
        self.storage_percentiles = defaultdict(lambda: deque(maxlen=WRITER_PERCENTILE_LIMIT))
        self.packet_copy_ns = deque(maxlen=WRITER_PERCENTILE_LIMIT)
        self.writer_samples = 0
        self.writer_slow_streak = self.writer_slow_longest = self.writer_slow_count = 0
        self.writer_trace = deque(maxlen=WRITER_TRACE_LIMIT)
        self.writer_state = threading.Lock()
        self.writer_active = None
        self.queue_overflow = None
        self.writer_failure = None
        self.writer_stall = None
        self.queue_peak_sample = 0
        self.first_ns = self.last_ns = self.end_ns = None
        self.first_write_ns = self.last_write_ns = None
        self.start_utc = self.end_utc = None
        self.preflight_status = 'NOT_TESTED'
        self.imu_status = {'status': 'NOT_RECORDED'}

    def start_pipeline(self, pipeline, make_config, rs):
        self.requested_profiles = {'color': (1280, 720, self.fps), 'depth': (848, 480, self.fps)}
        config = make_config(fps=self.fps)
        try:
            profile = config.resolve(rs.pipeline_wrapper(pipeline))
        except RuntimeError as exc:
            self.preflight_status = 'FAIL'
            raise RuntimeError(
                f'SDK cannot resolve exchange RGB 1280x720 BGR8 + Depth 848x480 Z16 at {self.fps} FPS: {exc}'
            ) from exc
        self.native_source = NativeRGBDSource(profile, rs, self.fps)
        return profile

    def start(self, pipeline, profile, rs):
        self.preflight_status = 'FAIL'
        if self.guided and (self.native_source is None or self.raw.requested):
            raise ValueError('Guided capture requires native preview with recording initially OFF')
        camera = self.raw._metadata()
        for name in ('color', 'depth'):
            stream = camera['streams'][name]
            actual = (stream['width'], stream['height'], stream['fps'])
            if stream['fps'] != self.fps or (self.requested_profiles and actual != self.requested_profiles[name]):
                raise ValueError(f'Active SDK {name} profile {actual} does not match the exchange request at {self.fps} FPS')
        required = preflight(self.raw, camera, self.duration)
        camera['device'].pop('serial_number', None)
        camera.update(depth_spec=dict(unit='m', encoding='Z16', invalid_zero=True,
            value_65535='NO_SPECIAL_RULE_CONFIRMED', validated_range_m='UNKNOWN',
            source='https://github.com/realsenseai/librealsense/wiki/Projection-in-RealSense-SDK-2.0'),
            coordinates=dict(native='each optical sensor: X right, Y down, Z forward',
                             extrinsics='depth to color; translation in meters'))
        if camera['device']['name']['value'] in ('Intel RealSense D455', 'RealSense D455'):
            camera['depth_spec'].update(manufacturer_ideal_range_m=[0.6, 6.0],
                range_source='https://www.realsenseai.com/products/450-series/')
        self.raw._metadata = lambda: camera
        # Legacy/mock callers supply a frameset source. The exchange launcher uses
        # the two live SDK sensors, opened only after startup output I/O below.
        if self.native_source is None:
            ready, first = pipeline.try_wait_for_frames(2000)
            if not ready:
                raise RuntimeError('RGB-D initialization timed out')
            self._validate_first_pair(first, camera)
        self.raw.begin_session()
        if not self.guided:
            self.raw._open()
        write_json(self.root/'exchange_metadata.json', dict(format='research-b-exchange/1',
            session_id=self.raw.events.session_id, participant=self.raw.events.context,
            environment=self.environment, required_free_bytes=required, raw_queue_capacity=self.pending.maxsize,
            capture_mode='capture_only' if self.capture_only else 'live_analysis', requested_fps=self.fps, hardware_qualification='NOT_TESTED',
            acquisition_source=('native_sensor_callbacks' if self.native_source else 'pipeline_framesets'),
            manual_labels='P3 left / P4 right from participant perspective',
            external_use='UNKNOWN', paper_use='UNKNOWN', stable_intervals='PENDING_HUMAN_REVIEW',
            raw_format='e0-raw-rgbd-npz/1', depth_grid='native depth optical coordinates',
            timing_heuristics='WARNING if sensor interval >1.5 nominal periods or same-domain pair skew >0.5 color period',
            receive_gap_policy=dict(fail_at_ms=RECEIVE_GAP_MS, sdk_wait_ms=SDK_WAIT_MS,
                scope='capture activation to stop request; includes first, between-frame and terminal gaps',
                rationale='Two SDK wait budgets; independent of sensor frame numbers and post-stop cleanup',
                sensor_scope='Consecutive frames from the same stream and timestamp domain'),
            verification_file='exchange_verification.json', checksum_inventory='exchange_files.json',
            annotation_template='stable_intervals_template.json', recipient_npz_support='UNKNOWN',
            layout='raw_rgbd/clip_####/frames/*.npz: color_bgr uint8 HWC, depth_z16 uint16 HW; '
                   'recording.json calibration; frames.jsonl sensor clocks and SHA-256; '
                   'exchange_validation.json final clip status; recording_metadata/events.jsonl instructions and measurements'))
        write_json(self.root/'stable_intervals_template.json', dict(session_id=self.raw.events.session_id,
            status='PENDING_HUMAN_REVIEW', write_review_to='a new file', bounds='inclusive clip frame_index',
            intervals=[dict(posture=f'P{i}',clip=None,start_frame=None,end_frame=None,
                            review_status='UNREVIEWED') for i in range(6)]))
        if self.native_source is not None:
            self.native_source.start()
        if self.record_imu:
            from exchange_imu import MotionLog
            self.motion = MotionLog(self.root/'imu.jsonl')
            self.motion.start(profile.get_device(), rs)
        else:
            from exchange_imu import available_profiles
            try:
                _, profiles = available_profiles(profile.get_device(), rs)
                self.imu_status['support'] = 'SUPPORTED' if profiles else 'UNSUPPORTED'
            except Exception:
                self.imu_status['support'] = 'UNKNOWN'
        if self.native_source is not None:
            self._validate_first_pair(self.native_source.warm_up(), camera)
        self.preflight_status = 'PASS'
        if not self.guided:
            self.start_utc = utc_now()
        self.writer = threading.Thread(target=self._write, name='exchange-raw-writer', daemon=True)
        source = self.native_source if self.native_source is not None else pipeline
        self.producer = threading.Thread(target=self._receive, args=(source,), name='exchange-sdk-receiver')
        self.writer.start()
        if not self.guided:
            self.active_since_ns = time.perf_counter_ns()
        self.producer.start()
        # Prevent operator measurements before the first accepted source frameset.
        with self.available:
            self.available.wait_for(lambda: self.enqueued or self.preview_pairs or self.errors, timeout=3)
            if not (self.enqueued or self.preview_pairs) or self.errors:
                raise RuntimeError(self.errors[0]['detail'] if self.errors else 'No initial recording input')

    def begin_recording(self):
        with self.event_lock:
            if not self.guided or not self.preview_pairs or self.stop_request.is_set():
                raise RawRecordingError('Guided recording requires a healthy preview')
            if self.active_since_ns is not None:
                return
            activated_ns = time.perf_counter_ns()
            try:
                event = self.raw.events.emit('RECORDING_START', source='operator_start',
                                            activated_host_ns=activated_ns, clip=None)
            except Exception as exc:
                self._error('event_log', exc)
                raise RawRecordingError('Exchange event recording failed') from exc
            with self.available:
                self.latest = self.latest_reference = self.analysis_reference = None
            self.recording_start_event = event['event_index']
            self.active_since_ns = activated_ns
            self.start_utc = utc_now()
            self.raw.requested = True
            self.raw.toggle_count += 1

    @staticmethod
    def _validate_first_pair(first, camera):
        arrays, clocks, _ = native_packet(first)
        for name, key in [('color', 'color_bgr'), ('depth', 'depth_z16')]:
            stream = camera['streams'][name]
            if clocks[name]['status'] != 'MEASURED':
                raise ValueError(f'Initial {name} frame identity or clock unavailable')
            if key not in arrays or arrays[key].shape[:2] != (stream['height'], stream['width']):
                raise ValueError(f'Initial {name} frame absent or incompatible')

    def _error(self, stage, exc):
        with self.available:
            self.errors.append(dict(stage=stage, type=type(exc).__name__, detail=str(exc)))
            if not self.stop_request.is_set():
                self.failure_stop_ns = time.perf_counter_ns()
            self.stop_request.set()
            if self.native_source is not None:
                self.native_source.end_input()
            self.available.notify_all()

    def _accept(self, frames, ns):
        self.acquired += 1
        if self.first_ns is None:
            self.first_ns = ns
            if self.guided:
                self.first_recorded_callback_ns = frames.first_callback_host_ns
        self.last_ns = ns
        before_copy = time.perf_counter_ns()
        packet = native_packet(frames)
        self.packet_copy_ns.append(time.perf_counter_ns() - before_copy)
        pair = dict(
            receive_index=self.acquired, accepted_host_ns=ns,
            created_host_ns=getattr(frames, 'created_host_ns', NOT_RECORDED),
            latest_callback_host_ns=getattr(frames, 'host_ns', NOT_RECORDED), sensors=packet[1],
        )
        row = dict(receive_index=self.acquired, receive_end_ns=ns,
                   raw=dict(rgb=packet[1]['color'], depth=packet[1]['depth']))
        events = self.raw.events
        events.observe_input(row, packet[2]['frameset_timestamp_ms'])
        if self.record_measurement is not None:
            self.record_measurement(row, packet[2]['frameset_timestamp_ms'])
        measure = events.measurement or {}
        item = packet, row, self.measurement_armed, measure.get('e0_segment_index'), events.count
        try:
            self.pending.put_nowait(item)
        except queue.Full as exc:
            self.overflows += 1
            self.queue_peak_sample = self.pending.maxsize
            self.queue_overflow = dict(rejected_pair=pair, depth_at_rejection=self.pending.maxsize,
                                       **self._writer_snapshot())
            raise RuntimeError('Raw queue overflow') from exc
        self.last_accepted_pair = pair
        self.enqueued += 1
        recovery = getattr(frames, 'recovery', None)
        if recovery is not None:
            recovery.update(resumed_receive_index=self.acquired, resumed_accepted_host_ns=ns)
        self.queue_peak_sample = max(self.queue_peak_sample, self.pending.qsize())
        if self.capture_only:
            preview = self._rgb_preview
            if preview is not None and (color := packet[0].get('color_bgr')) is not None:
                # The packet already owns its native array. Publication only retains a reference.
                preview.append(color)
            with self.available:
                self.available.notify_all()  # Initial recording readiness has no analysis consumer.
            return
        reference = None
        if self.guided:
            reference = dict(clip='raw_rgbd/clip_0001', frame=self.acquired, receive_index=self.acquired,
                             host_ns=ns, sensors={name: {key: sensor[key] for key in
                                 ('number', 'timestamp_ms', 'timestamp_domain')} for name, sensor in packet[1].items()})
        self._offer_analysis(frames, reference)

    @property
    def rgb_preview_enabled(self):
        return self._rgb_preview is not None

    def take_rgb_preview(self):
        preview = self._rgb_preview
        if preview is None:
            return None
        try:
            color = preview.popleft().view()
        except IndexError:
            return None
        color.flags.writeable = False
        return color

    def disable_rgb_preview(self):
        self._rgb_preview = None

    def _offer_analysis(self, frames, reference=None):
        with self.available:
            if self.latest is not None:
                if not self.guided or reference is not None:
                    self.analysis_replaced += 1
            self.latest = frames
            self.latest_reference = reference
            self.available.notify()

    def _observe_gap(self, ns):
        previous = self.last_ns if self.last_ns is not None else self.active_since_ns
        elapsed = ns - previous
        self.max_receive_gap_ns = max(self.max_receive_gap_ns, elapsed)
        if elapsed >= RECEIVE_GAP_MS * 1_000_000 and not self.receive_gap_failed:
            self.receive_gap_failed = True
            self._error('receive_gap', TimeoutError(
                f'No new RGB-D input for {elapsed / 1e6:.1f} ms during active capture (limit {RECEIVE_GAP_MS} ms)'))
            self._snapshot_receive_gap(ns, previous, elapsed)
        return elapsed

    def _snapshot_receive_gap(self, ns, previous, elapsed):
        storage_depth = self.pending.qsize()
        storage_sampled_ns = time.perf_counter_ns()
        diagnostic = dict(
            error_type='TimeoutError', host_clock='time.perf_counter_ns',
            detected_host_ns=ns, reference_host_ns=previous, gap_limit_ms=RECEIVE_GAP_MS,
            reference=('last_accepted_pair' if self.last_ns is not None else 'capture_activated'),
            observed_gap_ms=elapsed/1e6, sdk_wait_budget_ms=SDK_WAIT_MS,
            last_accepted_pair=self.last_accepted_pair or NOT_RECORDED,
            last_wait_started_host_ns=(self.wait_started_ns if self.wait_started_ns is not None else NOT_RECORDED),
            last_completed_wait=_wait_diagnostic(self.last_wait),
            consecutive_timeouts=self.consecutive_timeouts, timeout_history_limit=TIMEOUT_HISTORY_LIMIT,
            timeout_history=[_wait_diagnostic(wait) for wait in self.timeout_history],
            queues_at_failure=dict(storage_depth=storage_depth, storage_sampled_host_ns=storage_sampled_ns,
                                   sdk_input_depth=NOT_RECORDED, pairing_depth=NOT_RECORDED),
            native_input=NOT_RECORDED,
        )
        self.receive_gap_diagnostics = diagnostic
        if self.native_source is not None:
            try:
                native = self.native_source.receive_gap_snapshot()
            except Exception as exc:
                diagnostic['native_snapshot_error'] = type(exc).__name__
                return
            diagnostic['queues_at_failure'].update(sdk_input_depth=native.pop('sdk_input_queue_depth'),
                                                   pairing_depth=native.pop('pairing_queue_depth'))
            diagnostic['native_input'] = native

    def _receive(self, pipeline):
        try:
            while not self.stop_request.is_set():
                self.wait_started_ns = time.perf_counter_ns()
                try:
                    ready, frames = pipeline.try_wait_for_frames(SDK_WAIT_MS)
                except Exception:
                    self.last_wait = (self.wait_started_ns, time.perf_counter_ns(), 'exception')
                    raise
                returned_ns = time.perf_counter_ns()
                with self.event_lock:
                    if self.stop_request.is_set():
                        break
                    ns = time.perf_counter_ns()
                    if self.guided and self.active_since_ns is None:
                        if ready:
                            self.preview_pairs += 1
                            self._offer_analysis(frames)
                        continue
                    self.last_wait = (self.wait_started_ns, returned_ns, 'pair' if ready else 'timeout')
                    if not ready:
                        self.timeout_history.append(self.last_wait)
                        self.timeouts += 1
                        self.consecutive_timeouts += 1
                        self.max_consecutive_timeouts = max(self.max_consecutive_timeouts, self.consecutive_timeouts)
                    self._observe_gap(ns)
                    if ready:
                        self.consecutive_timeouts = 0
                        if self.guided and frames.first_callback_host_ns < self.active_since_ns:
                            self.preview_pairs += 1
                            continue
                        self._accept(frames, ns)
        except Exception as exc:
            self._error('acquisition', exc)
        finally:
            self.source_done.set()

    def _writer_snapshot(self):
        with self.writer_state:
            return dict(host_ns=time.perf_counter_ns(), queue_capacity=self.pending.maxsize,
                        queue_depth_sample=self.pending.qsize(), acquired=self.acquired,
                        queued=self.enqueued, written=self.writer_samples, active=self.writer_active,
                        recent_writes=list(self.writer_trace))

    def _write(self):
        try:
            while self.writer_stall is None and (not self.source_done.is_set() or not self.pending.empty()):
                try:
                    item = self.pending.get(timeout=0.05)
                except queue.Empty:
                    continue
                start = time.perf_counter_ns()
                row = item[1]
                active = dict(receive_index=row['receive_index'], sensors=item[0][1],
                              received_host_ns=row['receive_end_ns'], writer_start_host_ns=start,
                              queue_depth_sample=self.pending.qsize())
                with self.writer_state:
                    if self.writer_stall is not None:
                        return
                    self.writer_active = active
                self.raw.store_packet(*item)
                end = time.perf_counter_ns()
                timings = dict(self.raw.last_storage_timings, writer_total=end-start,
                               receive_to_write_start=start-row['receive_end_ns'])
                with self.writer_state:
                    if self.writer_stall is not None:
                        return
                    self.last_write_ns = end
                    self.writer_samples += 1
                    self.storage_ns.update(timings)
                    for name, ns in timings.items():
                        self.storage_max_ns[name] = max(self.storage_max_ns[name], ns)
                        self.storage_percentiles[name].append(ns)
                    if self.first_write_ns is None:
                        self.first_write_ns = end
                    slow = timings['writer_total'] * self.fps >= 1_000_000_000
                    self.writer_slow_streak = self.writer_slow_streak + 1 if slow else 0
                    self.writer_slow_longest = max(self.writer_slow_longest, self.writer_slow_streak)
                    self.writer_slow_count += int(slow)
                    self.writer_trace.append(dict(active, writer_end_host_ns=end,
                                                  stages_ns=timings, written=self.writer_samples))
                    self.writer_active = None
        except Exception as exc:
            if self.writer_stall is None:
                self.writer_failure = self._writer_snapshot()
                self._error('storage', exc)

    def analysis_frame(self):
        with self.available:
            self.available.wait_for(lambda: self.latest is not None or self.errors, timeout=0.25)
            if self.errors:
                raise RuntimeError(self.errors[0]['detail'])
            frames, self.latest = self.latest, None
            self.analysis_reference, self.latest_reference = self.latest_reference, None
        if frames is not None and self.native_source is not None:
            frames = self.native_source.to_analysis_frames(frames)
        return frames is not None, frames

    def stop(self):
        with self.event_lock:
            if self.end_ns is None:
                self.end_ns = self.failure_stop_ns or time.perf_counter_ns()
                self.end_utc = utc_now()
                if self.active_since_ns is not None:
                    if self.errors:
                        last = self.last_ns if self.last_ns is not None else self.active_since_ns
                        self.tail_gap_ns = max(0, self.end_ns - last)
                    else:
                        self.tail_gap_ns = self._observe_gap(self.end_ns)
            self.stop_request.set()
            if self.native_source is not None:
                self.native_source.end_input()
        if self.producer is not None and self.producer.ident is not None:
            self.producer.join()
        self.source_done.set()
        if self.writer is not None and self.writer.ident is not None and self.writer_stall is None:
            self.writer.join(timeout=WRITER_DRAIN_TIMEOUT_S)
            if self.writer.is_alive():
                with self.writer_state:
                    self.writer_stall = dict(written=self.writer_samples, active=self.writer_active,
                                             drain_timeout_s=WRITER_DRAIN_TIMEOUT_S)
                self._error('storage', TimeoutError('Raw writer drain deadline expired'))
        if self.motion is not None:
            self.imu_status = self.motion.close()
        self.latest = None
        self.disable_rgb_preview()
        if self.errors:
            raise RuntimeError(self.errors[0]['detail'])

    def publish(self, error=None):
        from exchange_verification import publish_result
        return publish_result(self, error)
