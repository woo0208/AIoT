"""File-only adapter into run_probe; no alternative inference/feature/classifier path."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np

from e0_storage import write_json
from frame_provenance import snapshot
from probe_timing import process_memory
from raw_rgbd_recording import SensorTrace, _sha
from raw_rgbd_replay import RawClipReader, RawSessionReader, db3_packets, _stored_image_counts
from replay_policy import ReplayGate, cpu_counters, counter_delta
from f1_sample_aggregator import H9_FEATURE_NAMES, H_MIN_VALID_FRAMES, H_MIN_COVERAGE


def intrinsics(rs, camera, name):
    info = camera['streams'][name]
    intr = rs.intrinsics()
    intr.width, intr.height = info['width'], info['height']
    for key in ('fx', 'fy', 'ppx', 'ppy', 'coeffs'):
        setattr(intr, key, info['intrinsics'][key])
    intr.model = getattr(rs.distortion, info['intrinsics']['model'].split('.')[-1])
    return intr


class SoftwareFrames:
    """Reconstruct SDK frames with stored calibration; no physical sensor exists.

    Build a composite explicitly: a syncer could pair/drop different inputs when
    clocks regress or differ. Each original reader packet remains one composite.
    """
    def __init__(self, rs, camera):
        self.rs, self.camera = rs, camera
        for info in camera['streams'].values():
            # Librealsense Align is unsafe for toy 2x2 profiles on this SDK.
            if (type(info['width']) is not int or type(info['height']) is not int
                    or info['width'] < 64 or info['height'] < 48 or info['width'] % 4):
                raise ValueError('SDK replay requires video width >=64 divisible by 4 and height >=48')
            intr = info['intrinsics']
            values = [intr[k] for k in ('fx','fy','ppx','ppy')] + list(intr['coeffs'])
            if not all(math.isfinite(v) for v in values) or intr['fx'] <= 0 or intr['fy'] <= 0:
                raise ValueError('Invalid saved intrinsics')
        self.device = rs.software_device()
        self.sensor = self.device.add_sensor('RGB-D file source')
        self.sensor.add_read_only_option(rs.option.depth_units, camera['depth_scale_m'])
        self.profiles = {}
        for uid, name in enumerate(('depth', 'color'), 1):
            info = camera['streams'][name]
            expected = 'format.z16' if name == 'depth' else 'format.bgr8'
            if info['format'] != expected:
                raise ValueError('Replay requires native Z16/BGR8')
            stream = rs.video_stream()
            stream.type, stream.index, stream.uid = getattr(rs.stream, name), 0, uid
            stream.width, stream.height, stream.fps = info['width'], info['height'], info['fps']
            stream.bpp, stream.fmt = (2, rs.format.z16) if name == 'depth' else (3, rs.format.bgr8)
            stream.intrinsics = intrinsics(rs, camera, name)
            self.profiles[name] = self.sensor.add_video_stream(stream).as_video_stream_profile()
        extr = rs.extrinsics()
        for key in ('rotation', 'translation'):
            setattr(extr, key, camera['depth_to_color_extrinsics'][key])
        self.profiles['depth'].register_extrinsics_to(self.profiles['color'], extr)
        self.queue = rs.frame_queue(4, keep_frames=True)
        self.sensor.open(list(self.profiles.values()))
        self.sensor.start(self.queue)
        self.output = rs.frame_queue(1, keep_frames=True)
        self.children = []
        self.composer = rs.processing_block(lambda frame, source:
            source.frame_ready(source.allocate_composite_frame(self.children)))
        self.composer.start(self.output.enqueue)

    def compose(self, packet):
        rs = self.rs
        self.children = []
        self.arrays = []  # hold injected pixel buffers until processing is complete
        for name, array in (('depth', packet.depth_z16), ('color', packet.color_bgr)):
            if array is None:
                continue
            info = self.camera['streams'][name]
            expected_shape = (info['height'],info['width']) + ((3,) if name=='color' else ())
            if array.shape != expected_shape or array.dtype != (np.uint8 if name=='color' else np.uint16):
                raise ValueError('Original pixels/profile mismatch')
            array = np.ascontiguousarray(array)
            self.arrays.append(array)
            meta = packet.record['sensors'][name]
            f = rs.software_video_frame()
            f.pixels, f.stride, f.bpp = array, array.strides[0], array.itemsize * (3 if name == 'color' else 1)
            f.timestamp, f.frame_number = meta['timestamp_ms'], meta['number']
            f.domain = getattr(rs.timestamp_domain, meta['timestamp_domain'].split('.')[-1])
            f.profile, f.depth_units = self.profiles[name], self.camera['depth_scale_m']
            self.sensor.on_video_frame(f)
            child = self.queue.wait_for_frame(1000)
            # SDK reconstruction must never silently alter sensor clocks/numbers.
            observed = snapshot(child)
            if any(observed[k] != meta[k] for k in ('number', 'timestamp_ms', 'timestamp_domain')):
                raise ValueError('SDK reconstruction changed original sensor clock')
            self.children.append(child)
        if not self.children:
            raise ValueError('Packet contains neither RGB nor Depth')
        self.composer.invoke(self.children[-1])
        return self.output.wait_for_frame(1000).as_frameset()

    def close(self):
        try:
            self.sensor.stop()
        finally:
            self.sensor.close()


class FrameView:
    def __init__(self, sdk_frames, record):
        self.sdk_frames, self.record = sdk_frames, record
    def get_timestamp(self):return self.record['frameset_timestamp_ms']
    def get_frame_number(self):return self.record['frameset_number']
    def get_frame_timestamp_domain(self):return self.record['frameset_timestamp_domain']
    def get_color_frame(self):return self.sdk_frames.get_color_frame()
    def get_depth_frame(self):return self.sdk_frames.get_depth_frame()


def stats(values):
    return dict(count=len(values), mean=float(np.mean(values)) if values else None,
        total=float(sum(values)), **{name:float(np.percentile(values, q)) if values else None
        for name, q in (('p50',50), ('p95',95), ('p99',99))})


def clock_record(packet):
    r = packet.record
    return {**{k:r[k] for k in ('frame_index','frameset_timestamp_ms','frameset_timestamp_domain','frameset_number')},
        'sensors':{n:{k:v for k,v in s.items() if k != 'profile_uid'} for n,s in r['sensors'].items()}}


class ReplayInput:
    def __init__(self, source, *, pacing='throughput', allow_incomplete=False,
                 expected_sha256=None, arm_at_first_frame=False, method='E0', interval=1):
        if pacing not in ('throughput', 'realtime15'):
            raise ValueError('Unknown pacing')
        self.source = Path(source).resolve(strict=True)
        self.pacing, self.arm = pacing, arm_at_first_frame
        self.gate = ReplayGate(method,interval=interval)
        self.initial_sha = _sha(self.source) if self.source.is_file() else None
        if expected_sha256 is not None and self.initial_sha != expected_sha256:
            raise ValueError('Unexpected original SHA-256')
        if self.source.is_file():
            if self.source.suffix.lower() not in ('.db3','.bag'):
                raise ValueError('Expected DB3/BAG or raw NPZ session/clip directory')
            self.kind, self.reader = 'REALSENSE_FILE', None
            self.identity = self.initial_sha
        elif (self.source/'recording_metadata/session_manifest.json').exists():
            self.kind = 'NPZ_SESSION'
            self.reader = RawSessionReader(self.source, allow_incomplete=allow_incomplete)
            self.identity = self.reader.manifest_sha256
        else:
            self.kind = 'NPZ_CLIP'
            self.reader = RawClipReader(self.source, allow_incomplete=allow_incomplete)
            # Include the immutable frame index/end linkage, not camera-only metadata.
            self.identity = hashlib.sha256(json.dumps(self.reader.hashes,sort_keys=True).encode()).hexdigest()
        self.trace, self.rows = SensorTrace(), []
        self.sequence = hashlib.sha256()
        self.pixels = hashlib.sha256()
        self.last_mp = -1
        self.last_domain = None
        self.previous_clip = None
        self.frames = None
        self.iterator = None
        self.prefetched = None
        self.software = None
        self._stream_start = self._stream_end = None
        self._cpu_start = self._cpu_end = None
        self.eof = False
        self.eof_read_ms = 0.
        self.errors = []
        self.cpu_first_full = None

    @staticmethod
    def locked_models(analyze):
        lock = analyze.load_model_lock()
        paths = {role:str(Path(analyze.MODEL_DIR)/entry['filename']) for role,entry in lock.items()}
        for role, path in paths.items():
            if not Path(path).is_file():raise FileNotFoundError('Cached locked model missing: '+role)
            analyze.verify_model_artifact(path, lock[role])
        return paths

    def start(self, rs):
        self.rs = rs
        self.iterator = iter(db3_packets(self.source) if self.reader is None else self.reader.packets())
        start = time.perf_counter_ns()
        try:
            self.prefetched = next(self.iterator)
        except StopIteration:
            raise ValueError('Empty RGB-D source') from None
        self.prefetch_ms = (time.perf_counter_ns()-start)/1e6
        self.camera = self.prefetched.camera
        if self.prefetched.native_frames is None:
            self.software = SoftwareFrames(rs, self.camera)
        return self  # run_probe only uses the metadata below for replay

    def color_intrinsics(self, rs):return intrinsics(rs, self.camera, 'color')

    def begin_stream(self):
        self._stream_start, self._cpu_start = time.perf_counter_ns(), time.process_time_ns()
        self.cpu_begin = cpu_counters()

    def end_stream(self):
        if self._stream_end is None:
            self._stream_end, self._cpu_end = time.perf_counter_ns(), time.process_time_ns()
            self.cpu_end = cpu_counters()

    def read(self):
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            if self.prefetched is not None:
                packet, self.prefetched = self.prefetched, None
                prefetched = True
            else:
                packet = next(self.iterator)
                prefetched = False
        except StopIteration:
            self.eof = True
            self.eof_read_ms = (time.perf_counter_ns()-start)/1e6
            return False, None
        decode_end, decode_cpu = time.perf_counter_ns(), time.process_time_ns()
        if any(packet.camera[key] != self.camera[key] for key in
               ('streams','depth_scale_m','depth_to_color_extrinsics')):
            raise ValueError('Replay calibration/profile changed within source')
        if self.previous_clip != packet.record.get('clip'):
            self.trace.previous = {}
            self.previous_clip = packet.record.get('clip')
        row = dict(input_index=len(self.rows)+1, source=clock_record(packet),
            clip=packet.record.get('clip'), pairing=packet.record.get('pairing'),
            sensor_relations=self.trace.observe(packet.record['sensors']),
            read_decode_ms=(decode_end-start)/1e6, read_decode_cpu_ms=(decode_cpu-cpu)/1e6,
            prefetched_during_setup=prefetched, status='received',
            missing_rgb=packet.color_bgr is None,missing_depth=packet.depth_z16 is None)
        self.rows.append(row)
        clock = clock_record(packet)
        self.sequence.update(json.dumps(clock,sort_keys=True,allow_nan=False).encode())
        # Reuse the prior verifier's canonical pixel + original clock identity.
        for name, array in (('color_bgr',packet.color_bgr),('depth_z16',packet.depth_z16)):
            if array is not None:
                self.pixels.update(name.encode());self.pixels.update(str(array.shape).encode());self.pixels.update(array.tobytes())
        self.pixels.update(json.dumps(clock,sort_keys=True,allow_nan=False).encode())
        adapter_start = time.perf_counter_ns()
        sdk = packet.native_frames if packet.native_frames is not None else self.software.compose(packet)
        row['adapter_and_identity_ms'] = (time.perf_counter_ns()-decode_end)/1e6
        row['sdk_reconstruction_ms'] = (time.perf_counter_ns()-adapter_start)/1e6
        pace_start = time.perf_counter_ns()
        target = self._stream_start + (len(self.rows)-1)*1_000_000_000/15
        if self.pacing == 'realtime15':
            remaining = (target-time.perf_counter_ns())/1e9
            if remaining > 0:time.sleep(remaining)
        row['pacing_wait_ms'] = (time.perf_counter_ns()-pace_start)/1e6
        row['schedule_lateness_ms'] = max(0,(time.perf_counter_ns()-target)/1e6) if self.pacing == 'realtime15' else None
        row['_start_ns'], row['_cpu_ns'] = start, cpu
        row['_ready_ns'], row['_ready_cpu_ns'] = time.perf_counter_ns(), time.process_time_ns()
        self.frames = FrameView(sdk, packet.record)
        self.rgb = packet.color_bgr
        self.current = row
        return True, self.frames

    def validate(self, session, e0_row):
        row = self.current
        row['e0_row'] = e0_row
        stamp = self.frames.get_timestamp()
        domain = self.frames.get_frame_timestamp_domain()
        problem = None
        if row['missing_rgb'] or row['missing_depth']:problem = 'missing_rgb_depth'
        elif isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp):problem = 'non_finite_timestamp'
        elif stamp < 0 or stamp >= 2**63/1000:problem = 'timestamp_out_of_range'
        elif self.last_domain is not None and domain != self.last_domain:problem = 'timestamp_domain_changed'
        elif int(stamp) <= self.last_mp:problem = 'duplicate_or_regressing_VIDEO_timestamp'
        row['mediapipe_timestamp_ms'] = int(stamp) if isinstance(stamp,(int,float)) and math.isfinite(stamp) else None
        if problem:
            row['status'], row['skip_reason'] = 'rejected', problem
            e0_row['status'] = 'replay_rejected'
            session.cancel_segment('source_invalid')
            self.gate.invalidate()
            self.errors.append(dict(input_index=row['input_index'], cause=problem, recovery='SKIP_INPUT_NO_CACHED_FEATURES'))
            return False
        self.last_mp, self.last_domain = int(stamp), domain
        row['status'] = 'processing'
        if self.arm and len(self.rows) == 1:
            session.arm_segment()
        return True

    def select_full(self):
        self.current['gate'] = self.gate.select(self.rgb,self.frames.get_timestamp(),len(self.rows))
        return self.current['gate']['full']

    def skipped(self,session,row,frame_index,stamp):
        # Explicit missing observations retain the original denominator. No
        # held vector/prediction is supplied to H9; its 30/50 rules are unchanged.
        session.processing_started(row,frame_index)
        session.accept(row,SimpleNamespace(features={n:None for n in H9_FEATURE_NAMES}),
            frame_index,stamp,pose_detected=None,face_detected=None)
        session.frame_completed(row)
        row['status']='replay_'+self.current['gate']['measurement_status'].lower()
        row['measurement_available']=False
        self.completed(row,full=False)

    def completed(self, e0_row, *, full=True):
        row = self.current
        row.update(status='completed' if full else row['gate']['measurement_status'].lower(),
            full_inference=full, feature_success=e0_row.get('feature_success'),
            h9_common_success=e0_row.get('h9_common_success'),
            processing_ms=(time.perf_counter_ns()-row['_ready_ns'])/1e6,
            processing_cpu_ms=(time.process_time_ns()-row['_ready_cpu_ns'])/1e6,
            read_to_complete_ms=(time.perf_counter_ns()-row['_start_ns'])/1e6)
        row['service_excluding_pacing_ms'] = row['read_to_complete_ms']-row['pacing_wait_ms']
        if full:
            self.gate.completed(self.frames.get_timestamp(),row['input_index'],bool(row.get('h9_common_success')))
            if self.cpu_first_full is None:self.cpu_first_full=cpu_counters()
        try:row['rss_bytes'] = process_memory()['rss_bytes']
        except Exception:row['rss_bytes'] = None

    def observe_features(self, result):
        # Numeric identity only; no alternate feature formula or classification.
        self.current['feature_vector_sha256'] = hashlib.sha256(json.dumps(
            dict(result.features),sort_keys=True,allow_nan=False).encode()).hexdigest()

    def stop(self):
        try:
            if self.iterator is not None:self.iterator.close()
        finally:
            if self.software is not None:self.software.close()

    def report(self, session, *, error=None):
        source_unchanged = _sha(self.source) == self.initial_sha if self.source.is_file() else (True if self.eof else None)
        timing = json.loads((session.directory/'timing/diagnostics.json').read_text(encoding='utf8'))
        stages = {s['name']:s for s in timing['stage_milliseconds'] if s['phase']=='steady'}
        kernels = ('receive.align','input.convert','mediapipe.pose','mediapipe.face','depth_geometry',
                   'fs3.feature_select','fs3.aggregate','fs3.scale','fs3.svm')
        kernel_samples = Counter()
        for sample in timing.get('raw',[]):
            if sample['name'] in kernels:
                kernel_samples[sample.get('frame_id')] += sample['duration_ns']/1e6
        for name, stage in stages.items():
            samples=[r['duration_ns']/1e6 for r in timing.get('raw',[]) if r['name']==name and r['phase']=='steady']
            stage.update(total_ms=sum(samples),mean_ms=float(np.mean(samples)) if samples else None)
        for row in self.rows:
            if row['status'] in ('received','processing'):
                row['status'] = 'failed' if error else row.get('e0_row',{}).get('status','INCOMPLETE')
        completed = [r for r in self.rows if r['status']=='completed']
        handled = [r for r in self.rows if r['status'] in ('completed','held','stale')]
        seconds = (self._stream_end-self._stream_start)/1e9 if self._stream_start is not None else None
        cpu = (self._cpu_end-self._cpu_start)/1e9 if self._cpu_start is not None else None
        rss = [r['rss_bytes'] for r in handled if r.get('rss_bytes') is not None]
        summary = session.result_summary
        source_stamps=[r['source']['frameset_timestamp_ms'] for r in self.rows]
        regular_clock=(len(source_stamps)>1 and all(b>a for a,b in zip(source_stamps,source_stamps[1:]))
            and len({r['source']['frameset_timestamp_domain'] for r in self.rows})==1)
        clean = lambda r:{k:v for k,v in r.items() if not k.startswith('_') and k!='e0_row'}
        document = dict(format='research-b-e0-raw-replay/1',scope='NON_FORMAL_OFFLINE_ENGINEERING',
            status='FAILED' if error is not None or not self.eof or source_unchanged is not True else 'COMPLETED',
            error_type=type(error).__name__ if error else None, variant=self.gate.method, source_kind=self.kind,
            replay_gate=self.gate.config(),gate_states=dict(self.gate.counts),
            source_identity_sha256=self.identity, source_unchanged=source_unchanged,
            sequence_sha256=self.sequence.hexdigest(),array_and_clock_sequence_sha256=self.pixels.hexdigest(),
            camera=self.camera, pacing=self.pacing, target_fps=15 if self.pacing=='realtime15' else None,
            prefetch_setup_ms=self.prefetch_ms, eof_confirmed=self.eof,
            terminal_read_eof_ms=self.eof_read_ms,
            input_frames=len(self.rows), processed_frames=len(completed),
            handled_frames=len(handled),skipped_frames=len(handled)-len(completed),
            native_stored_image_counts=_stored_image_counts(self.source) if self.source.is_file() else None,
            source_timeline_fps=(len(source_stamps)-1)*1000/(source_stamps[-1]-source_stamps[0]) if regular_clock else None,
            hold_control='EXPLICIT_UNLABELLED_ARM_AT_FIRST_INPUT' if self.arm else 'UNARMED_FULL_INFERENCE',
            dropped_or_rejected_frames=len(self.rows)-len(handled),
            missing_rgb=sum(r['missing_rgb'] for r in self.rows),missing_depth=sum(r['missing_depth'] for r in self.rows),
            sensor_diagnostics=dict(self.trace.counts),sensor_missing_rate='NOT_MEASURED',
            stages=stages, actual_calls={name:stages.get(key,{}).get('count',0) for name,key in
                (('align','receive.align'),('pose','mediapipe.pose'),('face','mediapipe.face'),('depth','depth_geometry'),('svm','fs3.svm'))},
            stream_wall_seconds=seconds, process_cpu_seconds=cpu,
            process_cpu_ms_per_input=cpu*1000/len(self.rows) if self.rows and cpu is not None else None,
            cpu_check=dict(clock=vars(time.get_clock_info('process_time')),
                stream_counters=counter_delta(self.cpu_begin,self.cpu_end),
                first_full_counters=counter_delta(self.cpu_begin,self.cpu_first_full) if self.cpu_first_full else None,
                after_first_full_counters=counter_delta(self.cpu_first_full,self.cpu_end) if self.cpu_first_full else None,
                backend=session.backends,initialization_in_stream=False,first_inference_in_stream=True,
                cycles_note='QueryProcessCycleTime/QueryThreadCycleTime; raw cycles, not converted using assumed frequency'),
            gate_cost=dict(wall_ms=stats([r['gate']['gate_wall_ns']/1e6 for r in handled]),
                cpu_counters={k:sum(r['gate']['gate_cpu'].get(k,0) for r in handled)
                    for k in ('process_ns','thread_ns','process_cycles','thread_cycles')},
                note='process CPU includes concurrent workers; main-thread cycles include counter reads; coarse CPU ticks may be zero'),
            process_cpu_percent_one_core=cpu/seconds*100 if seconds else None,
            input_fps=len(self.rows)/seconds if seconds else None,
            processed_fps=len(completed)/seconds if seconds else None,
            processed_fps_excluding_terminal_read=len(completed)/(seconds-self.eof_read_ms/1000)
                if seconds and seconds>self.eof_read_ms/1000 else None,
            latency_ms={key:stats([r[key] for r in completed]) for key in
                ('read_decode_ms','adapter_and_identity_ms','pacing_wait_ms','processing_ms','processing_cpu_ms',
                 'read_to_complete_ms','service_excluding_pacing_ms')},
            all_input_latency_ms={key:stats([r[key] for r in handled]) for key in
                ('processing_ms','read_to_complete_ms','service_excluding_pacing_ms')},
            rss=dict(sample_count=len(rss),mean_bytes=float(np.mean(rss)) if rss else None,
                peak_bytes=max(rss) if rss else None,method='GetProcessMemoryInfo/proc per-completed-frame samples; frame-weighted mean'),
            resource_monitor=summary['resources'], feature_success_frames=summary['feature_success_frames'],
            inference_kernel_ms=stats([v for k,v in kernel_samples.items() if k is not None]),
            inference_kernel_definition=list(kernels),
            inference_kernel_total_ms=sum(kernel_samples.values()),
            unframed_kernel_total_ms=kernel_samples.get(None,0),
            pure_inference_cpu='NOT_ISOLATED_SDK_DECODER_AND_OBSERVER_THREADS_SHARE_PROCESS',
            cpu_clock_resolution_seconds=time.get_clock_info('process_time').resolution,
            common_valid_frames=sum(bool(r.get('h9_common_success')) for r in completed),
            h9_support=dict(input_frames=len(self.rows),valid_frames=sum(bool(r.get('h9_common_success')) for r in completed),
                coverage=sum(bool(r.get('h9_common_success')) for r in completed)/len(self.rows) if self.rows else None,
                minimum_valid=H_MIN_VALID_FRAMES,minimum_coverage=H_MIN_COVERAGE,
                denominator='all delivered inputs, including skipped observations; whole-clip diagnostic only',
                reasons=([f'valid_frames<{H_MIN_VALID_FRAMES}'] if sum(bool(r.get('h9_common_success')) for r in completed)<H_MIN_VALID_FRAMES else [])+
                    ([f'coverage<{H_MIN_COVERAGE}'] if not self.rows or sum(bool(r.get('h9_common_success')) for r in completed)/len(self.rows)<H_MIN_COVERAGE else []),
                completed_eligible_holds=sum(bool(s.get('eligible')) and s.get('status')=='PREDICTED' for s in session.segments)),
            segments=list(session.segments),prediction_attempts=summary['prediction_attempts'],
            prediction_successes=summary['prediction_successes'],errors=self.errors,recovery_policy='skip invalid source clock; abort I/O/inference/corruption; no retry',
            accuracy='NOT_MEASURED',macro_f1='NOT_MEASURED',p0_recall='NOT_MEASURED',p1_recall='NOT_MEASURED',
            transition_delay='NOT_MEASURED',ground_truth='UNANNOTATED',hardware='NOT_TESTED_HARDWARE',
            measurement_boundaries=dict(
                stream='after model/source initialization -> EOF/exception before model/source close; process CPU includes all process threads/observer',
                read_decode='synchronous reader next() incl NPZ hash and decoded array copy; SDK asynchronous work may overlap inference',
                eof='stream FPS/CPU includes separately reported terminal next(): EOF wait, final reader verification and SDK close; excluding-terminal FPS also provided',
                prefetch='first packet read during setup; first frame decode reported separately, not included again in stream',
                processing='reader+adapter+pacing return -> original E0 frame_completed; includes Align/convert/Pose/Face/Depth/features/hold/SVM if eligible',
                read_to_complete='next() entry -> E0 complete, includes decode/adapter/identity/pacing',
                service='read_to_complete minus measured pacing wait; excludes model init/final report and separately noted prefetch',
                kernel_stages='per-frame sum of tagged original stages; FS3 hold aggregate/scale/SVM have no frame tag and are separately unframed; total includes both; no decode/observer/pacing or physical sensor/display latency',
                rss='per-frame samples during stream; mean frame-weighted, peak sampled; OS lifetime peak in separate monitor'),
            frames=[clean(r) for r in self.rows])
        write_json(session.directory/'replay.json', document)
        return document


def run_replay(source, binding, artifact, directory, *, pacing='throughput',
               allow_incomplete=False, expected_sha256=None, arm_at_first_frame=False, pc_id='PC01',
               method='E0',interval=1):
    from e0_fs3 import E0Session
    from e0_model import load_fs3, environment_record
    from posture_geometry_probe import run_probe
    source = Path(source).resolve(strict=True)
    directory = Path(directory).resolve()
    if directory.exists() or directory == source or source.is_dir() and directory.is_relative_to(source):
        raise ValueError('Replay output must be new and outside source')
    replay = ReplayInput(source,pacing=pacing,allow_incomplete=allow_incomplete,
        expected_sha256=expected_sha256,arm_at_first_frame=arm_at_first_frame,method=method,interval=interval)
    model,scaler,verified = load_fs3(artifact,binding['artifact_sha256'],binding['feature_ids'],
        expected_model_sha256=binding['model_sha256'],expected_scaler_sha256=binding['scaler_sha256'])
    session = E0Session(directory,model,scaler,input_scope='raw_replay',model_binding=verified)
    session.environment_metadata = environment_record(pc_id)
    total_start, total_cpu = time.perf_counter_ns(), time.process_time_ns()
    error = None
    try:
        run_probe(e0_session=session,replay_input=replay,headless=True,show_3d_views='none')
    except BaseException as exc:
        error = exc
        replay.errors.append(dict(input_index=len(replay.rows),cause=type(exc).__name__,
                                  recovery='ABORT_NO_RETRY'))
        write_json(directory/'replay_failure.json',dict(status='FAILED',error_type=type(exc).__name__,
            input_index=len(replay.rows),source_identity_sha256=replay.identity,
            source_kind=replay.kind,recovery='ABORT_NO_RETRY',hardware='NOT_TESTED_HARDWARE'))
        raise
    finally:
        # run_probe owns normal and exceptional source/model/resource cleanup.
        if session._finished and replay._stream_start is not None:
            try:
                document = replay.report(session,error=error)
            except Exception as report_error:
                if error is None:raise
                # Keep the original inference/I/O error as the raised exception.
                write_json(directory/'replay_report_failure.json',dict(status='FAILED',
                    primary_error_type=type(error).__name__,report_error_type=type(report_error).__name__))
            write_json(directory/'replay_invocation.json',dict(
                wall_seconds=(time.perf_counter_ns()-total_start)/1e9,
                process_cpu_seconds=(time.process_time_ns()-total_cpu)/1e9,
                boundary='run_probe entry through session/report publication; excludes preflight SHA/model binding validation',
                source_sha256={n:_sha(Path(__file__).with_name(n)) for n in
                    ('e0_replay.py','replay_policy.py','raw_rgbd_replay.py','posture_geometry_probe.py','e0_fs3.py','posture_geometry.py')}))
    return document
