"""Opt-in E0/B1 raw recording, independently controlled from measurement.

Lossless, native (pre-align) BGR8/Z16 NPZs plus source clocks/calibration.
This engineering sidecar is not a scientific schema or a labelled dataset.
OFF creates no files; every ON interval gets a new exclusive clip directory.
"""
from contextlib import nullcontext
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
from collections import Counter
from importlib import metadata as package_metadata
import time

import numpy as np

from e0_storage import write_json
from frame_provenance import snapshot, compare


FORMAT = 'e0-raw-rgbd-npz/1'
EXCHANGE_VALIDATION_FORMAT = 'research-b-exchange-clip-validation/1'
EXCHANGE_VALIDATION_FILE = 'exchange_validation.json'
RESERVE_BYTES = 256 * 2**20


class RawRecordingError(RuntimeError):
    pass


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def camera_metadata(profile, rs, *, source_kind='live_profile'):
    """Private camera identity/geometry/settings; getters only, never sets options."""
    streams, handles = {}, {}
    for name, stream in (('color', rs.stream.color), ('depth', rs.stream.depth)):
        handle = profile.get_stream(stream).as_video_stream_profile()
        intr = handle.get_intrinsics()
        handles[name] = handle
        streams[name] = dict(width=intr.width, height=intr.height, fps=handle.fps(),
            format=str(handle.format()), intrinsics={
                **{n: getattr(intr, n) for n in ('fx', 'fy', 'ppx', 'ppy')},
                'model': str(intr.model), 'coeffs': list(intr.coeffs)})
    extr = handles['depth'].get_extrinsics_to(handles['color'])
    scale = float(profile.get_device().first_depth_sensor().get_depth_scale())
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid depth scale')
    device=profile.get_device()
    def observed(getter):
        try:
            value=getter()
            json.dumps(value,allow_nan=False)
            if value is None:raise ValueError('unavailable')
            return dict(status='MEASURED',value=value)
        except Exception as exc:
            return dict(status='NOT_MEASURED',value=None,reason_type=type(exc).__name__)
    info={name:observed(lambda name=name:device.get_info(getattr(rs.camera_info,name)))
          for name in ('name','serial_number','firmware_version','product_id','usb_type_descriptor')}
    settings={}
    for name,getter in (('color','first_color_sensor'),('depth','first_depth_sensor')):
        settings[name]={key:observed(lambda key=key,getter=getter:
            float(getattr(device,getter)().get_option(getattr(rs.option,key)))) for key in
            (('exposure','gain','enable_auto_exposure','white_balance','enable_auto_white_balance') if name=='color'
             else ('exposure','gain','enable_auto_exposure','laser_power','emitter_enabled',
                   'visual_preset','frames_queue_size','depth_units','global_time_enabled'))}
    sdk=observed(lambda:package_metadata.version('pyrealsense2'))
    sdk['role']='PLAYBACK_RUNTIME' if source_kind=='file_playback' else 'RECORDING_RUNTIME'
    return dict(streams=streams, depth_scale_m=scale, device=info, sensor_options=settings,
        sdk=sdk,metadata_source=source_kind,
        original_capture_sdk=(dict(status='NOT_MEASURED',value=None) if source_kind=='file_playback' else sdk),
        depth_to_color_extrinsics=dict(rotation=list(extr.rotation), translation=list(extr.translation)),
        alignment='NONE_NATIVE_STREAMS',processing_alignment=dict(target='color',saved_arrays_aligned=False),
        storage=dict(color='BGR8 uint8', depth='Z16 uint16'))


class SensorTrace:
    """Diagnostic continuity only. Never filters, repairs or sets eligibility."""
    def __init__(self):
        self.previous={};self.counts=Counter()

    def observe(self,sensors,*,commit=True):
        output={}
        for name,current in sensors.items():
            previous=self.previous.get(name)
            relation=compare(previous,current)
            kind='NOT_MEASURED'
            if current.get('status')=='MEASURED':
                if not previous:kind='FIRST'
                elif relation['status']=='MEASURED':
                    if current['number']<previous['number']:kind='COUNTER_REGRESSION'
                    elif current['timestamp_ms']<previous['timestamp_ms']:kind='TIMESTAMP_REGRESSION'
                    elif relation['boundary']:kind='STREAM_BOUNDARY'
                    elif relation['same_identity']:kind='DUPLICATE_IDENTITY'
                    elif not relation['number_changed']:kind='NUMBER_REUSED'
                    elif relation['source_gap']:kind='NUMBER_GAP'
                    elif not relation['timestamp_ms_changed']:kind='DUPLICATE_TIMESTAMP'
                    else:kind='ADVANCED'
            comparable=(previous is not None and previous.get('status')=='MEASURED'
                and current.get('status')=='MEASURED' and all(previous.get(key)==current.get(key)
                for key in ('timestamp_domain','profile_uid','stream_type','stream_index')))
            flags=dict(number_regression=current['number']<previous['number'] if comparable else None,
                timestamp_regression=current['timestamp_ms']<previous['timestamp_ms'] if comparable else None,
                timestamp_duplicate=current['timestamp_ms']==previous['timestamp_ms'] if comparable else None)
            output[name]=dict(relation,classification=kind,**flags)
            if commit:
                self.counts[name+'.'+kind]+=1
                for flag,value in flags.items():
                    if value:self.counts[name+'.'+flag+'_count']+=1
                if kind=='NUMBER_GAP':self.counts[name+'.missing_number_estimate']+=relation['source_gap']
                self.previous[name]=current
        return output


def pairing_info(sensors, arrays, source='SDK_DELIVERED_FRAMESET'):
    color,depth=sensors.get('color',{}),sensors.get('depth',{})
    comparable=(color.get('timestamp_domain') is not None
        and color.get('timestamp_domain')==depth.get('timestamp_domain')
        and _number(color.get('timestamp_ms')) is not None and _number(depth.get('timestamp_ms')) is not None)
    return dict(source=source,color_present='color_bgr' in arrays,
        depth_present='depth_z16' in arrays,same_timestamp_domain=bool(comparable),
        color_minus_depth_ms=color['timestamp_ms']-depth['timestamp_ms'] if comparable else None,
        synchronization_quality='NOT_ASSESSED')


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def native_packet(frames):
    arrays, clocks = {}, {}
    for name, getter, key, dtype, ndim in (
            ('color', 'get_color_frame', 'color_bgr', np.uint8, 3),
            ('depth', 'get_depth_frame', 'depth_z16', np.uint16, 2)):
        frame = getattr(frames, getter)()
        clocks[name] = snapshot(frame)
        clocks[name].pop('unavailable', None)
        if frame:
            array = np.asanyarray(frame.get_data())
            if array.dtype != dtype or array.ndim != ndim or (name == 'color' and array.shape[2] != 3):
                raise ValueError('Unexpected native stream array')
            arrays[key] = array.copy()
    def accessor(name):
        try:
            value = getattr(frames, name)()
            return (str(value) if value is not None else None) if name.endswith('domain') else _number(value)
        except Exception:
            return None
    identity = dict(frameset_timestamp_ms=accessor('get_timestamp'),
        frameset_timestamp_domain=accessor('get_frame_timestamp_domain'),
        frameset_number=accessor('get_frame_number'))
    if getattr(frames, 'native_timestamp_pair', False) is True:
        identity['pairing_source'] = 'NATIVE_ONE_USE_TIMESTAMP_PAIR'
    return arrays, clocks, identity


class HashingNPZOutput:
    """Forward-only ZIP output so the digest covers exactly the bytes written."""
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.timings = Counter()

    def write(self, data):
        start = time.perf_counter_ns()
        written = self.stream.write(data)
        mid = time.perf_counter_ns()
        if written != len(data):
            raise OSError('Short NPZ write')
        self.digest.update(data)
        self.timings['npz_write'] += mid-start
        self.timings['npz_hash'] += time.perf_counter_ns()-mid
        return written

    def flush(self):
        start = time.perf_counter_ns()
        self.stream.flush()
        self.timings['npz_flush'] += time.perf_counter_ns()-start

    def read(self, size=-1):
        # NumPy recognizes a file-like ZIP destination by this method.
        raise io.UnsupportedOperation('NPZ output is write-only')


class RawRecordingControl:
    def __init__(self, directory, *, initial='off', scope='NON_FORMAL_ENGINEERING', model_binding=None,
                 session_context=None, clock_ns=time.perf_counter_ns):
        if initial not in ('on', 'off'):
            raise ValueError('save_raw must be on or off')
        self.directory = Path(directory)
        if self.directory.exists():
            raise FileExistsError(self.directory)
        self.requested = initial == 'on'
        self.exchange = None
        self.initial = initial
        self.scope = scope
        self.model_binding = model_binding or {}
        self.total_frames = self.clip_count = 0
        self.current = self.last_clip = None
        self.current_frames = 0
        self._index = None
        self.last_storage_timings = {}
        self._metadata = None
        self._finished = False
        self.error_type = None
        self.toggle_count = 0
        self.events=None
        if session_context is not None:
            from raw_rgbd_events import SessionEvents
            self.events=SessionEvents(self.directory.parent/'recording_metadata',context=session_context,
                                      clock_ns=clock_ns,scope=scope)
        self.availability=Counter(missing_color=0,missing_depth=0,paired_frames=0)
        self.sensor_counts=Counter();self.trace=SensorTrace()
        self.clip_availability=Counter();self.errors=[];self._io_target=None
        self.termination_status=None;self.termination_reason=None

    def begin_session(self):
        if self.events is not None and not self.events.started:
            self.events.begin()
            if self.requested:self.events.emit('RECORDING_START',source='initial_option',clip=None)

    def observe_input(self,frames,row):
        if self.events is not None:
            try:timestamp=_number(frames.get_timestamp())
            except Exception:timestamp=None
            self.events.observe_input(row,timestamp)

    def observe_measurement(self,session, *, device_timestamp_ms=None):
        if self.events is not None:
            self._io_target='recording_metadata/events.jsonl'
            try:
                with self.exchange.event_lock if self.exchange else nullcontext():
                    guided_frame = None
                    if device_timestamp_ms is not None and getattr(self.exchange, 'guided', False):
                        reference = self.exchange.analysis_reference
                        if reference is not None:
                            guided_frame = dict(reference=reference, device_ms=device_timestamp_ms)
                    self.events.watch_measurement(session, guided_frame=guided_frame)
                    if self.exchange:
                        self.exchange.measurement_armed = bool(session.armed)
            except Exception as exc:self._fail(exc)

    def instruction(self,code,*,source='operator_instruction_button',repetition=None):
        if self.events is not None:
            self._io_target='recording_metadata/events.jsonl'
            try:
                with self.exchange.event_lock if self.exchange else nullcontext():
                    self.events.instruction(code,source=source,repetition=repetition)
            except Exception as exc:self._fail(exc)

    def bind(self, provider):
        if self._metadata is not None or self._finished:
            raise ValueError('Raw recording source cannot be reused')
        self._metadata = provider  # SDK metadata reads deferred until first ON frame.

    def check_health(self):
        if self.error_type:
            raise RawRecordingError('RAW_RECORDING_FAILED: '+self.error_type)

    def set_enabled(self, enabled):
        if type(enabled) is not bool or self._finished:
            raise ValueError('Invalid raw recording state')
        self.check_health()
        if self.exchange is not None and not enabled:
            raise RawRecordingError('Exchange capture requires raw recording ON')
        if enabled == self.requested:
            return
        if getattr(self.exchange, 'guided', False):
            self.exchange.begin_recording()
            return
        self.toggle_count += 1
        self.requested = enabled
        try:
            if self.events is not None and self.events.started:
                self._io_target='recording_metadata/events.jsonl'
                self.events.emit('RECORDING_START' if enabled else 'RECORDING_STOP',source='operator_toggle',
                                 clip=self.current.name if self.current else None)
            if not enabled:
                self._close('COMPLETED', 'operator_off')
        except Exception as exc:
            self._fail(exc)

    def _open(self):
        if self._metadata is None:
            raise ValueError('Raw camera metadata not bound')
        metadata = self._metadata()
        # Validate all numeric metadata before creating a clip.
        json.dumps(metadata, allow_nan=False)
        self.directory.mkdir(exist_ok=True)
        candidate = self.directory/f'clip_{self.clip_count+1:04d}'
        candidate.mkdir()  # Exclusive; an existing clip is never reused.
        self.clip_count += 1
        self.current = candidate
        self._io_target=f'{candidate.name}/recording.json'
        self.current_frames = 0
        self.trace=SensorTrace();self.clip_availability=Counter()
        (self.current/'frames').mkdir()
        write_json(self.current/'recording.json', dict(format=FORMAT, scope=self.scope,
            **({'exchange_validation': EXCHANGE_VALIDATION_FORMAT} if self.exchange else {}),
            label_status='UNLABELLED; operator intent is not ground truth',
            parent_session='../..', model_binding=self.model_binding, camera=metadata,
            session_id=self.events.session_id if self.events else None,
            source_sha256={n: _sha(Path(__file__).with_name(n)) for n in
                           ('raw_rgbd_recording.py', 'posture_geometry_probe.py', 'e0_panel.py')},
            notes=['Native arrays before Align/inference; missing streams stay missing.',
                   'Source timestamps and duplicates are preserved without repair.',
                   'No end.json means unfinalized. OFF intervals have no saved frames.']))
        self._index = (self.current/'frames.jsonl').open('x', encoding='utf-8', newline='\n')

    def capture(self, frames, row, *, armed=False, active_segment=None):
        self.check_health()
        if self._finished:
            raise ValueError('Raw recording already finalized')
        if not self.requested:
            return False
        try:
            return self.store_packet(native_packet(frames), row, armed, active_segment,
                                     self.events.count if self.events else None)
        except Exception as exc:
            self._fail(exc)

    def store_packet(self, packet, row, armed, active_segment, event_index):
        """Single writer. Pixels were copied from the native frameset at receipt."""
        arrays, clocks, frame_identity = packet
        start = time.perf_counter_ns()
        if shutil.disk_usage(self.directory.parent).free < RESERVE_BYTES:
            raise OSError('Raw recording disk reserve reached')
        if self.current is None:
            self._open()
        # No previous image is substituted when one/both streams are absent.
        count = self.current_frames+1
        relative = f'frames/{count:08d}.npz'
        path = self.current/relative
        self._io_target=f'{self.current.name}/{relative}'
        before_npz = time.perf_counter_ns()
        with path.open('xb') as output:
            if self.exchange is not None:
                writer = HashingNPZOutput(output)
                np.savez(writer, **arrays)
                writer.flush()
            else:
                np.savez(output, **arrays)
        after_npz = time.perf_counter_ns()
        digest = writer.digest.hexdigest() if self.exchange is not None else _sha(path)
        record = dict(frame_index=count, file=relative, sha256=digest,
            receive_index=row['receive_index'], host_receive_end_ns=row['receive_end_ns'],
            **frame_identity, sensors=clocks,
            measurement_armed=bool(armed), active_segment_index=active_segment,
            session_id=self.events.session_id if self.events else None,
            preceding_event_index=event_index,
            sensor_relations=self.trace.observe(clocks,commit=False),
            pairing=pairing_info(clocks, arrays, frame_identity.get('pairing_source', 'SDK_DELIVERED_FRAMESET')))
        self._io_target=f'{self.current.name}/frames.jsonl'
        self._index.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')
        self._index.flush()
        if self.exchange is not None:
            self.last_storage_timings = dict(writer.timings, npz_total=after_npz-before_npz,
                npz_framework=after_npz-before_npz-sum(writer.timings.values()),
                index_and_metadata=time.perf_counter_ns()-after_npz, prepare=before_npz-start)
        self.current_frames += 1
        self.total_frames += 1
        self.trace.observe(clocks)
        for key,present in (('missing_color','color_bgr' in arrays),('missing_depth','depth_z16' in arrays)):
            self.availability[key]+=not present;self.clip_availability[key]+=not present
        self.availability['paired_frames']+=len(arrays)==2
        self.clip_availability['paired_frames']+=len(arrays)==2
        return True

    def _close(self, status, reason):
        if self.current is None:
            return
        clip = self.current
        try:
            self._io_target=f'{clip.name}/end.json'
            if self._index is not None:
                self._index.close()
            write_json(clip/'end.json', dict(format=FORMAT, status=status, reason=reason,
                frames=self.current_frames, error_type=self.error_type,
                frames_index_sha256=_sha(clip/'frames.jsonl'),
                recording_sha256=_sha(clip/'recording.json'),availability=dict(self.clip_availability),
                sensor_diagnostics=dict(self.trace.counts)))
        finally:
            self.sensor_counts.update(self.trace.counts)
            self.last_clip = clip
            self.current = self._index = None

    def _fail(self, exc):
        if self.exchange is not None and self.exchange.writer is not None and self.exchange.writer.is_alive():
            # UI/event errors must not close a file owned by the active writer.
            self.exchange._error('event_log', exc)
            raise RawRecordingError('Exchange event recording failed') from exc
        self.error_type = type(exc).__name__
        self.termination_status='FAILED'
        if getattr(self.exchange, 'guided', False):
            self.termination_reason = 'write_failed'
        was_requested=self.requested
        self.requested = False
        self.errors.append(dict(error_type=self.error_type,
            clip=self.current.name if self.current else None,next_frame=self.current_frames+1,path=self._io_target))
        try:
            self._close('FAILED', 'recording_error')
        except Exception:
            pass  # Missing finalization remains visibly incomplete, never success.
        if self.events is not None and self.events.started and not self.events.finished:
            try:
                self.events.emit('RECORDING_ERROR',error_type=self.error_type,record=self.errors[-1])
                if was_requested:self.events.emit('RECORDING_STOP',source='recording_error',error_type=self.error_type)
            except Exception:pass
        raise RawRecordingError('RAW_RECORDING_FAILED: '+self.error_type) from None

    def finish(self, *, error=None, termination=None):
        if self._finished:
            return
        if self.exchange is not None and isinstance(error, KeyboardInterrupt):
            termination, error = 'keyboard_interrupt', None
        if error is not None and self.error_type is None:
            self.error_type = type(error).__name__
        guided = getattr(self.exchange, 'guided', False)
        if guided:
            if self.exchange.errors:
                first = self.exchange.errors[0]
                self.error_type = self.error_type or first['type']
                termination = ('write_failed' if first['stage'] in ('storage', 'event_log')
                               else 'acquisition_failed')
            else:
                termination = {'q': 'user_aborted', 'keyboard_interrupt': 'user_aborted',
                               'duration_elapsed': 'duration_expired'}.get(termination, termination)
        self.termination_reason=termination or ('stream_error' if self.error_type else 'stream_end')
        self.termination_status=('FAILED' if self.error_type else
            'INTERRUPTED' if guided and termination != 'guided_completed' else
            'INTERRUPTED' if termination in ('q','panel_closed','keyboard_interrupt') else 'COMPLETED')
        try:
            if self.events is not None and self.events.started and self.requested:
                self._io_target='recording_metadata/events.jsonl'
                self.events.emit('RECORDING_STOP',source='stream_end',error_type=self.error_type)
            self._close(self.termination_status,self.termination_reason)
            if self.events is not None and self.events.started:
                files={str(p.relative_to(self.directory.parent)).replace('\\','/'):_sha(p)
                       for p in self.directory.glob('clip_*/*') if p.is_file()}
                event_status = ('PENDING_VERIFICATION' if guided and self.termination_status == 'COMPLETED'
                                else self.termination_status)
                self.events.finish(status=event_status,reason=self.termination_reason,
                    verification_pending=self.exchange is not None,
                    raw_summary={**self.summary(),'requested':False,'status':'FAILED' if self.error_type else 'CLOSED'},
                    files=files)
        except Exception as exc:
            self._fail(exc)
        finally:
            try:
                if self.events is not None and self.events.stream is not None and not self.events.stream.closed:
                    self.events.stream.close()
            finally:
                self.requested = False
                self._finished = True

    def summary(self):
        return dict(format=FORMAT, initial=self.initial, requested=self.requested,
            status='FAILED' if self.error_type else 'CLOSED' if self._finished else 'ON' if self.requested else 'OFF',
            clips=self.clip_count, frames=self.total_frames, toggles=self.toggle_count,
            error_type=self.error_type, directory='raw_rgbd', scope=self.scope,
            termination_status=self.termination_status,termination_reason=self.termination_reason,
            session_id=self.events.session_id if self.events else None,
            events='recording_metadata/events.jsonl' if self.events else None,
            session_manifest='recording_metadata/session_manifest.json' if self.events else None,
            availability=dict(self.availability),sensor_diagnostics=dict(self.sensor_counts),errors=self.errors,
            performance_note=('Independent native acquisition and writer; see exchange_verification.json' if self.exchange
                              else 'Recording I/O is included in loop latency/CPU; match recording settings.'))

    def display(self):
        status = 'ERROR: '+self.error_type if self.error_type else 'ON' if self.requested else 'OFF'
        clip = self.current or self.last_clip
        text=f'원본 저장 {status} | {self.total_frames} 프레임\n{clip or self.directory}'
        if self.exchange is not None:
            if self.exchange.errors:
                text += '\nERROR: '+self.exchange.errors[0]['detail']
            else:
                text += f'\nRGB gaps {self.trace.counts["color.missing_number_estimate"]} / Depth gaps {self.trace.counts["depth.missing_number_estimate"]}'
        if self.events is not None and self.events.posture is not None:
            text+=f'\n자세 안내 {self.events.posture} (실제 움직임 UNANNOTATED)'
        return text


def load_raw_frame(clip, record):
    """Load one indexed NPZ with hash/order/type checks; never repairs source time."""
    clip = Path(clip)
    if type(record.get('frame_index')) is not int or record['frame_index'] < 1:
        raise ValueError('Invalid raw frame index')
    expected = f"frames/{record['frame_index']:08d}.npz"
    if record['file'] != expected or _sha(clip/expected) != record['sha256']:
        raise ValueError('Raw frame path/hash mismatch')
    with np.load(clip/expected, allow_pickle=False) as saved:
        if not set(saved.files).issubset({'color_bgr', 'depth_z16'}):
            raise ValueError('Unexpected raw array key')
        result = {name: saved[name].copy() for name in saved.files}
    for name, dtype, ndim in (('color_bgr', np.uint8, 3), ('depth_z16', np.uint16, 2)):
        if name in result and (result[name].dtype != dtype or result[name].ndim != ndim
                               or (name == 'color_bgr' and result[name].shape[2] != 3)):
            raise ValueError('Invalid raw array')
    return result
