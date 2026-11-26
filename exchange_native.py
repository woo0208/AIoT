"""Native RealSense sensors with one-use timestamp pairing for exchange capture."""
from collections import Counter, deque
import queue
import threading
import time

from frame_provenance import snapshot

PENDING_PER_STREAM = 8
STARTUP_VALID_PAIRS = 3
STARTUP_TIMEOUT_S = 6
RECENT_FRAME_LIMIT = 16
NOT_RECORDED = 'NOT_RECORDED'
NOT_SUPPORTED = 'NOT_SUPPORTED'
READ_ERROR = 'READ_ERROR'
SDK_TIMESTAMP_FIELDS = ('sensor_timestamp', 'frame_timestamp', 'backend_timestamp', 'time_of_arrival')
SDK_METADATA_FIELDS = (*SDK_TIMESTAMP_FIELDS, 'frame_counter')


def _frame_diagnostic(name, stamp, received_ns):
    fields = {key: stamp.get(key) for key in ('number', 'timestamp_ms', 'timestamp_domain')}
    fields['host_callback_ns'] = received_ns
    return dict(stream=name, **{key: value if value is not None else NOT_RECORDED
                                for key, value in fields.items()})


def _observed_frame_diagnostic(name, stamp, received_ns, processed_ns, sdk_values):
    return dict(_frame_diagnostic(name, stamp, received_ns), host_pairer_processed_ns=processed_ns,
                sdk_metadata={field: (dict(status='MEASURED', raw_value=value) if type(value) is int
                                      else dict(status=value)) for field, value in sdk_values.items()})


def _frame_intervals(earlier, later):
    if earlier == NOT_RECORDED or later == NOT_RECORDED:
        return NOT_RECORDED

    def delta(first, last):
        return last - first if type(first) in (int, float) and type(last) in (int, float) else NOT_RECORDED

    same_domain = earlier['timestamp_domain'] != NOT_RECORDED and earlier['timestamp_domain'] == later['timestamp_domain']
    return dict(
        frame_number_delta=delta(earlier['number'], later['number']),
        sdk_timestamp_delta_ms=delta(earlier['timestamp_ms'], later['timestamp_ms']) if same_domain else NOT_RECORDED,
        host_callback_interval_ns=delta(earlier['host_callback_ns'], later['host_callback_ns']),
        sdk_metadata_raw_deltas={field: delta(earlier['sdk_metadata'][field].get('raw_value'),
                                             later['sdk_metadata'][field].get('raw_value'))
                                 if same_domain else NOT_RECORDED for field in SDK_METADATA_FIELDS},
    )


class NativePairer:
    """Pair ordered child frames once, without a latest-frame cache."""

    def __init__(self, fps, *, sdk_metadata=None, clock_ns=time.perf_counter_ns):
        self.max_skew_ms = 500 / fps
        self.pending = {name: deque() for name in ('color', 'depth')}
        # Keep the existing stamps and callback times without retaining SDK frames.
        self.recent = deque(maxlen=RECENT_FRAME_LIMIT)
        self.last_processed = {}
        self.clock_ns = clock_ns
        self.sdk_metadata_keys = {name: key for name in SDK_METADATA_FIELDS
                                  if (key := getattr(sdk_metadata, name, None)) is not None}
        self.previous = {}
        self.startup = True
        self.streak = 0
        self.warmup = Counter()
        self.observed = Counter()
        self.failure = None

    def _discontinuity(self, reason, name, stamp, *, skew_ms=None):
        if self.startup:
            self.streak = 0
            self.warmup[reason] += 1
            return
        self.failure = dict(reason=reason, stream=name, sensor=stamp)
        if reason in ('unmatched_timestamp', 'incomparable_clocks'):
            self.failure['diagnostics'] = self._comparison_diagnostics(skew_ms)
        raise RuntimeError(f'Native RGB-D {reason} ({name}, frame {stamp.get("number")})')

    def _read_sdk_metadata(self, frame):
        values = dict.fromkeys(SDK_METADATA_FIELDS, NOT_SUPPORTED)
        if not self.sdk_metadata_keys:
            return values
        try:
            supports = getattr(frame, 'supports_frame_metadata', None)
            read = getattr(frame, 'get_frame_metadata', None)
        except Exception:
            values.update(dict.fromkeys(self.sdk_metadata_keys, READ_ERROR))
            return values
        if supports is None or read is None:
            return values
        for field, key in self.sdk_metadata_keys.items():
            try:
                if supports(key):
                    value = read(key)
                    values[field] = value if type(value) is int else READ_ERROR
            except Exception:
                # A failed diagnostic query cannot alter frame acceptance.
                values[field] = READ_ERROR
        return values

    def _candidate_diagnostic(self, name, entry, compared_ns):
        _, stamp, received_ns, queued_ns, processed_ns, sdk_values = entry
        result = _observed_frame_diagnostic(name, stamp, received_ns, processed_ns, sdk_values)
        result['host_pairing_queue_enter_ns'] = queued_ns
        result['pairing_queue_wait_ns'] = compared_ns - queued_ns
        result['callback_to_pairing_queue_ns'] = (queued_ns - received_ns if received_ns is not None
                                                  else NOT_RECORDED)
        # Keep the legacy four-field view and its missing-value convention.
        result['sdk_metadata_raw'] = {field: sdk_values[field] if type(sdk_values[field]) is int else NOT_RECORDED
                                      for field in SDK_TIMESTAMP_FIELDS}
        return result

    def _comparison_diagnostics(self, skew_ms):
        compared_ns = self.clock_ns()
        heads = {name: self._candidate_diagnostic(name, entries[0], compared_ns)
                 for name, entries in self.pending.items()}
        following = {name: self._candidate_diagnostic(name, entries[1], compared_ns)
                     if len(entries) > 1 else NOT_RECORDED for name, entries in self.pending.items()}
        previous = dict.fromkeys(self.pending, NOT_RECORDED)
        latest = {}
        recent = []
        for item in self.recent:
            name, stamp = item[:2]
            if stamp is self.pending[name][0][1]:
                previous[name] = latest.get(name, NOT_RECORDED)
            observation = _observed_frame_diagnostic(*item)
            latest[name] = observation
            recent.append(observation)
        return dict(
            host_clock='time.perf_counter_ns', comparison_host_ns=compared_ns,
            color_minus_depth_ms=skew_ms if skew_ms is not None else NOT_RECORDED,
            allowed_abs_skew_ms=self.max_skew_ms,
            abs_skew_excess_ms=abs(skew_ms)-self.max_skew_ms if skew_ms is not None else NOT_RECORDED,
            pairing_queue_depth={name: len(entries) for name, entries in self.pending.items()},
            compared_candidates=heads, next_candidates=following, previous_candidates=previous,
            candidate_intervals={name: dict(previous_to_compared=_frame_intervals(previous[name], head),
                                            compared_to_next=_frame_intervals(head, following[name]))
                                 for name, head in heads.items()},
            recent_frame_limit=RECENT_FRAME_LIMIT,
            recent_frames=[_frame_diagnostic(*item[:3]) for item in self.recent],
            recent_frame_metadata=recent,
        )

    def push(self, name, frame, received_ns):
        if self.startup:
            self.warmup[name+'_frames'] += 1
        else:
            self.observed[name] += 1
        stamp = snapshot(frame)
        processed_ns = self.clock_ns()
        sdk_values = self._read_sdk_metadata(frame)
        metadata = name, stamp, received_ns, processed_ns, sdk_values
        self.last_processed[name] = metadata
        self.recent.append(metadata)
        if stamp['status'] != 'MEASURED':
            self._discontinuity('unmeasured_clock', name, stamp)
            return None
        prev = self.previous.get(name)
        if prev:
            identity = ('timestamp_domain', 'profile_uid', 'stream_type', 'stream_index')
            if any(stamp[k] != prev[k] for k in identity):
                self._discontinuity('stream_boundary', name, stamp)
                self.pending['color'].clear()
                self.pending['depth'].clear()
            elif stamp['number'] <= prev['number'] or stamp['timestamp_ms'] <= prev['timestamp_ms']:
                self._discontinuity('duplicate_or_regression', name, stamp)
                return None
            elif stamp['number'] != prev['number']+1 or stamp['timestamp_ms']-prev['timestamp_ms'] >= 500:
                self._discontinuity('sensor_number_or_time_gap', name, stamp)
                self.pending['color'].clear()
                self.pending['depth'].clear()
        self.previous[name] = stamp
        own = self.pending[name]
        if len(own) == PENDING_PER_STREAM:
            self._discontinuity('unmatched_buffer_full', name, stamp)
            own.popleft()
        own.append((frame, stamp, received_ns, self.clock_ns(), processed_ns, sdk_values))
        color, depth = self.pending['color'], self.pending['depth']
        while color and depth:
            c, d = color[0], depth[0]
            if c[1]['timestamp_domain'] != d[1]['timestamp_domain']:
                self._discontinuity('incomparable_clocks', name, stamp)
                color.clear()
                depth.clear()
                return None
            skew = c[1]['timestamp_ms'] - d[1]['timestamp_ms']
            if abs(skew) <= self.max_skew_ms:
                color.popleft()
                depth.popleft()
                if self.startup:
                    self.warmup['paired_frames'] += 1
                    self.streak += 1
                return NativePair(c[0], d[0], max(c[2], d[2]), self.clock_ns(), min(c[2], d[2]))
            older = 'color' if skew < 0 else 'depth'
            self._discontinuity('unmatched_timestamp', older, self.pending[older][0][1], skew_ms=skew)
            self.pending[older].popleft()
        return None

    def activate(self):
        # The first active pair is checked against the last warmup sensor observations.
        self.startup = False


class NativePair:
    native_timestamp_pair = True

    def __init__(self, color, depth, host_ns, created_host_ns, first_callback_host_ns):
        self.color = color
        self.depth = depth
        self.host_ns = host_ns
        self.created_host_ns = created_host_ns
        self.first_callback_host_ns = first_callback_host_ns

    def get_color_frame(self):
        return self.color

    def get_depth_frame(self):
        return self.depth

    def get_frame_number(self):
        return self.depth.get_frame_number()

    def get_timestamp(self):
        return self.depth.get_timestamp()

    def get_frame_timestamp_domain(self):
        return self.depth.get_frame_timestamp_domain()


class NativeRGBDSource:
    def __init__(self, profile, rs, fps):
        self.profile = profile
        self.rs = rs
        self.pairer = NativePairer(fps, sdk_metadata=getattr(rs, 'frame_metadata_value', None))
        self.input = queue.Queue(2 * PENDING_PER_STREAM)
        self.callback_lock = threading.Lock()
        self.pairer_lock = threading.Lock()
        self.callback_counts = Counter()
        self.last_callback_ns = {}
        self.opened = []
        self.started = []
        self.callback_error = None
        self.accepting = True
        self.composite = None
        self.children = None
        self.composer = rs.processing_block(
            lambda frame, source: source.frame_ready(source.allocate_composite_frame(self.children)))
        self.composer.start(self._set_composite)

    def _set_composite(self, frame):
        self.composite = frame.as_frameset()

    def to_analysis_frames(self, pair):
        # Only the analysis thread uses the composite block. Recording uses the
        # original SDK children directly and never waits for frame composition.
        self.children = [pair.depth, pair.color]
        self.composite = None
        try:
            self.composer.invoke(pair.depth)
            if self.composite is None:
                raise RuntimeError('SDK did not compose the analysis frameset')
            return self.composite
        finally:
            self.children = self.composite = None

    def _callback(self, name):
        def enqueue(frame):
            received_ns = time.perf_counter_ns()
            with self.callback_lock:
                if self.callback_error is not None or not self.accepting:
                    return
                self.callback_counts[name] += 1
                self.last_callback_ns[name] = received_ns
                try:
                    self.input.put_nowait((name, frame, received_ns))
                except queue.Full:
                    self.callback_error = f'Native SDK input queue overflow ({name}, frame {frame.get_frame_number()})'
        return enqueue

    def start(self):
        wanted = {self.profile.get_stream(getattr(self.rs.stream, name)).unique_id(): name
                  for name in ('color', 'depth')}
        try:
            for sensor in self.profile.get_device().query_sensors():
                profiles = sensor.get_stream_profiles()
                selected = []
                for uid, name in wanted.items():
                    target = self.profile.get_stream(getattr(self.rs.stream, name)).as_video_stream_profile()
                    for stream in profiles:
                        if stream.unique_id() != uid or stream.fps() != target.fps() or stream.format() != target.format():
                            continue
                        video = stream.as_video_stream_profile()
                        if (video.width(), video.height()) == (target.width(), target.height()):
                            selected.append((name, stream))
                            break
                if selected:
                    if len(selected) != 1:
                        raise RuntimeError('Expected dedicated RGB and depth SDK sensors')
                    name, stream = selected[0]
                    sensor.open(stream)
                    self.opened.append((name, sensor))
            if sorted(name for name, _ in self.opened) != ['color', 'depth']:
                raise RuntimeError('Resolved RGB and depth profiles not available on native sensors')
            for name, sensor in self.opened:
                sensor.start(self._callback(name))
                self.started.append(sensor)
        except BaseException:
            self.stop()
            raise

    def try_wait_for_frames(self, timeout_ms):
        deadline = time.perf_counter() + timeout_ms / 1000
        while True:
            if self.callback_error is not None:
                raise RuntimeError(self.callback_error)
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return False, None
            try:
                child = self.input.get(timeout=remaining)
            except queue.Empty:
                return False, None
            try:
                with self.pairer_lock:
                    pair = self.pairer.push(*child)
            except RuntimeError:
                failure = self.pairer.failure
                if failure is not None and 'diagnostics' in failure:
                    failure['diagnostics']['sdk_input_queue_depth_after_failure'] = self.input.qsize()
                raise
            if pair is not None:
                return True, pair

    def warm_up(self):
        deadline = time.perf_counter() + STARTUP_TIMEOUT_S
        while time.perf_counter() < deadline:
            ready, pair = self.try_wait_for_frames(250)
            if ready and self.pairer.streak >= STARTUP_VALID_PAIRS:
                self.pairer.activate()
                return pair
        raise RuntimeError('Native RGB-D startup did not produce three consecutive fresh timestamp pairs')

    def stop(self):
        self.end_input()
        errors = []
        for sensor in reversed(self.started):
            try:
                sensor.stop()
            except RuntimeError as exc:
                errors.append(exc)
        self.started.clear()
        for _, sensor in reversed(self.opened):
            try:
                sensor.close()
            except RuntimeError as exc:
                errors.append(exc)
        self.opened.clear()
        if errors:
            raise errors[0]

    def end_input(self):
        with self.callback_lock:
            self.accepting = False

    def receive_gap_snapshot(self):
        """Copy and format bounded metadata state after sealing callbacks."""
        pairer = self.pairer
        with self.pairer_lock:
            with self.callback_lock:
                sampled_ns = time.perf_counter_ns()
                input_depth = self.input.qsize()
                counts = dict(self.callback_counts)
                callbacks = dict(self.last_callback_ns)
            pending_entries = {name: tuple(entries) for name, entries in pairer.pending.items()}
            last_processed = dict(pairer.last_processed)
            recent = tuple(pairer.recent)
            active_counts = dict(pairer.observed)
            warmup = dict(pairer.warmup)

        pending = {name: [pairer._candidate_diagnostic(name, item, sampled_ns) for item in entries]
                   for name, entries in pending_entries.items()}
        streams = {}
        for name, entries in pending.items():
            callback_ns = callbacks.get(name)
            last = last_processed.get(name)
            processed = _observed_frame_diagnostic(*last) if last is not None else NOT_RECORDED
            if last is not None:
                # The legacy view only reported optional fields for pending frames.
                last_is_pending = entries and pending_entries[name][-1][1] is last[1]
                processed['sdk_metadata_raw'] = (entries[-1]['sdk_metadata_raw'] if last_is_pending
                                                  else dict.fromkeys(SDK_TIMESTAMP_FIELDS, NOT_RECORDED))
            streams[name] = dict(
                callback_count=counts.get(name, 0),
                last_callback_host_ns=callback_ns if callback_ns is not None else NOT_RECORDED,
                elapsed_since_last_callback_ms=((sampled_ns-callback_ns)/1e6 if callback_ns is not None
                                                else NOT_RECORDED),
                pairer_input_count=warmup.get(name+'_frames', 0) + active_counts.get(name, 0),
                active_pairer_input_count=active_counts.get(name, 0), last_processed=processed,
            )
        return dict(
            sampled_host_ns=sampled_ns, sdk_input_queue_depth=input_depth,
            pairing_queue_depth={name: len(entries) for name, entries in pending.items()},
            streams=streams, pending_candidates=pending, recent_frame_limit=RECENT_FRAME_LIMIT,
            recent_frame_metadata=[_observed_frame_diagnostic(*item) for item in recent],
        )

    def diagnostics(self):
        return dict(warmup=dict(self.pairer.warmup), observed=dict(self.pairer.observed),
                    pairing_failure=self.pairer.failure, callback_error=self.callback_error,
                    max_pair_skew_ms=self.pairer.max_skew_ms, pending_at_stop=self.input.qsize() +
                    sum(len(pending) for pending in self.pairer.pending.values()))
