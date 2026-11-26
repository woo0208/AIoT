"""Small in-memory SDK source; no camera, model fit, field data or network."""
import io
import json
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import numpy as np

from exchange_capture import ExchangeCapture, preflight, read_environment
from exchange_imu import MotionLog
from exchange_native import NativeRGBDSource
from raw_rgbd_recording import HashingNPZOutput, RawRecordingControl, _sha
from raw_rgbd_replay import RawClipReader, RawSessionReader
from test_frame_provenance import child, pair
from test_raw_rgbd_recording import metadata


def camera():
    data = metadata()
    for name, stream in data['streams'].items():
        stream.update(fps=15, format='bgr8' if name=='color' else 'z16',
                      intrinsics=dict(fx=10,fy=10,ppx=1,ppy=1,model='none',coeffs=[0]*5))
    data['device'] = dict(name=dict(status='MEASURED',value='synthetic'), serial_number='private')
    return data


def frame(i, skew=0, *, fps=15):
    depth = child(i, i*1000/fps+skew, stream='depth',uid=2)
    depth.get_data = lambda: np.array([[0,65535],[1,1024]], dtype=np.uint16)
    rgb = child(i,i*1000/fps)
    rgb.get_data = lambda: np.arange(12,dtype=np.uint8).reshape(2,2,3)
    return pair(rgb, depth)


class Input:
    def __init__(self):
        self.frames = queue.Queue()
        self.frames.put(frame(0))  # initialization only
        self.frames.put(frame(1))

    def try_wait_for_frames(self, timeout):
        try:
            return True,self.frames.get(timeout=0.02)
        except queue.Empty:
            return False,None


def until(condition):
    deadline = time.monotonic()+4
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out waiting for synthetic worker')
        time.sleep(0.002)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.raw = RawRecordingControl(self.root/'raw_rgbd',initial='on',
                                       session_context={'participant_id':'P02','session_label':'S1'})
        self.raw.bind(camera)
        self.x = ExchangeCapture(self.raw,environment=read_environment(None),duration=3,record_imu=False)
        self.raw.exchange = self.x
        self.source = Input()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.x.writer and self.x.writer.is_alive():
            try:self.x.stop()
            except RuntimeError:pass
        if self.raw.events.started and not self.raw._finished:
            self.raw.finish(termination='panel_closed')

    def start(self):
        self.x.start(self.source,None,None)

    def start_native(self, samples=None, sdk_metadata=None):
        sdk = NS(processing_block=Mock(), frame_metadata_value=sdk_metadata)
        source = NativeRGBDSource(None, sdk, 15)
        self.x.native_source = source
        callbacks = {name: source._callback(name) for name in ('color', 'depth')}
        if samples is None:
            samples = (frame(number) for number in range(1, 5))
        for sample in samples:
            callbacks['color'](sample.get_color_frame())
            callbacks['depth'](sample.get_depth_frame())
        with patch.object(source, 'start'):
            self.start()
        until(lambda: self.raw.total_frames == 1)
        return callbacks

    def finish(self, reason='duration_elapsed', error=None):
        try:self.x.stop()
        except RuntimeError as exc:error=exc
        self.raw.finish(termination=reason,error=error)
        return self.x.publish(error)

    def test_native_arrays_clocks_and_reader(self):
        self.start()
        self.source.frames.put(frame(2))
        until(lambda:self.x.enqueued==2)
        report=self.finish()
        self.assertEqual(report['checks']['file_integrity'],'PASS')
        packets=list(RawSessionReader(self.root).packets())
        self.assertEqual(len(packets),2)
        packet=packets[-1]
        np.testing.assert_array_equal(packet.color_bgr,np.arange(12,dtype=np.uint8).reshape(2,2,3))
        np.testing.assert_array_equal(packet.depth_z16,[[0,65535],[1,1024]])
        self.assertEqual(packet.depth_z16.dtype,np.uint16)
        self.assertEqual(packet.camera['depth_scale_m'],.001)
        self.assertEqual(packet.camera['depth_to_color_extrinsics']['translation'],[.05,0.,0.])
        self.assertEqual(packet.camera['coordinates']['extrinsics'],'depth to color; translation in meters')
        self.assertNotIn('serial_number',packet.camera['device'])
        self.assertEqual(packet.record['sensors']['depth']['number'],2)
        index=json.loads((self.root/'exchange_files.json').read_text())
        for name,digest in index['sha256'].items():
            self.assertEqual(_sha(self.root/name),digest)
        self.assertEqual(report['requested_fps'], 15)
        self.assertEqual(report['checks']['hardware_qualification'], 'NOT_TESTED')
        standalone = self.root/'detached'
        shutil.copytree(self.raw.last_clip, standalone)
        self.assertEqual(len(list(RawClipReader(standalone).packets())), 2)
        (standalone/'exchange_validation.json').unlink()
        with self.assertRaisesRegex(ValueError, 'exchange validation'):
            RawClipReader(standalone)
        self.assertEqual(len(list(RawClipReader(standalone,allow_incomplete=True).packets())), 2)

    def test_slow_analysis_does_not_delay_recording(self):
        self.start()
        self.assertTrue(self.x.analysis_frame()[0])
        # Consumer holds its frame and never polls while all eight inputs are saved.
        for i in range(2,10):
            self.source.frames.put(frame(i))
            until(lambda:self.raw.total_frames==i)
        self.assertEqual(self.x.analysis_frame()[1].get_frame_number(),9)
        report=self.finish()
        self.assertGreater(report['analysis_replaced'],0)
        self.assertEqual(report['verification']['counts']['pairs'],9)
        self.assertGreater(report['verification']['saved_fps'],0)
        self.assertEqual(report['mediapipe_fps'],0)

    def test_gap_and_duplicate(self):
        self.start()
        for i in (3,3):self.source.frames.put(frame(i))
        until(lambda:self.raw.total_frames==3)
        with self.assertRaisesRegex(RuntimeError,'verification'):
            self.finish()
        r=json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(r['checks']['continuity'],'FAIL')
        self.assertEqual(r['verification']['issues']['color.NUMBER_GAP'],1)
        self.assertEqual(r['verification']['issues']['depth.DUPLICATE_IDENTITY'],1)
        with self.assertRaises(ValueError):RawSessionReader(self.root)
        with self.assertRaisesRegex(ValueError, 'exchange validation'):
            RawClipReader(self.raw.last_clip)
        proof = json.loads((self.raw.last_clip/'exchange_validation.json').read_text())
        self.assertEqual((proof['write_status'], proof['session_status'], proof['status']),
                         ('COMPLETED', 'FAILED', 'FAIL'))
        self.assertEqual(len(list(RawClipReader(self.raw.last_clip,allow_incomplete=True).packets())),3)

    def test_active_tail_gap_is_not_success(self):
        self.start()
        session = NS(armed=False, active=None, segments=[])
        for i in range(6):
            self.raw.instruction(f'P{i}')
            session.active = dict(segment_index=i, first_device_ms=10*i)
            self.raw.observe_measurement(session)
            self.source.frames.put(frame(i+2))
            until(lambda: self.raw.total_frames == i+2)
            session.active = None
            self.raw.observe_measurement(session)
        time.sleep(0.75)
        try:
            self.finish()
        except RuntimeError:
            pass
        report = json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['checks']['receive_gap'], 'FAIL')
        self.assertGreaterEqual(report['terminal_receive_gap_ms'], report['receive_gap_limit_ms'])
        self.assertGreater(report['receiver_timeouts'], 0)

    def test_shutdown_wait_after_stop_is_not_an_active_gap(self):
        self.start()
        waiting = threading.Event()
        def late_sdk_return(timeout):
            waiting.set()
            self.x.stop_request.wait(timeout=1)
            time.sleep(0.55)
            return False, None
        self.source.try_wait_for_frames = late_sdk_return
        self.assertTrue(waiting.wait(timeout=1))
        report = self.finish('panel_closed')
        self.assertEqual(report['session_status'], 'INTERRUPTED')
        self.assertEqual(report['checks']['receive_gap'], 'PASS')
        self.assertLess(report['terminal_receive_gap_ms'], report['receive_gap_limit_ms'])

    def test_sensor_gap_fails_with_consecutive_ids_and_regular_host_receive(self):
        self.start()
        self.source.frames.put(frame(2, 600))
        until(lambda: self.raw.total_frames==2)
        with self.assertRaisesRegex(RuntimeError, 'verification'):
            self.finish()
        report = json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(report['checks']['timing'], 'FAIL')
        self.assertEqual(report['checks']['continuity'], 'PASS')
        self.assertEqual(report['verification']['issues']['depth.sensor_gap'], 1)

    def test_repeated_instruction_never_spans_other_postures(self):
        self.start()
        session = NS(armed=False, active=dict(segment_index=0, first_device_ms=0), segments=[])
        for i, label in enumerate(('P0', 'P1', 'P0'), 2):
            self.raw.instruction(label)
            self.raw.observe_measurement(session)
            self.source.frames.put(frame(i))
            until(lambda: self.raw.total_frames == i)
        report = self.finish()
        ranges = [r for r in report['verification']['posture_ranges'] if r['instruction'] is not None]
        self.assertEqual([(r['instruction'], r['first_frame'], r['last_frame']) for r in ranges],
                         [('P0', 2, 2), ('P1', 3, 3), ('P0', 4, 4)])
        self.assertEqual([r['phase'] for r in ranges], ['MEASUREMENT', 'TRANSITION', 'TRANSITION'])
        self.assertEqual([r['instruction'] for r in report['verification']['observed_holds']], ['P0'])
        self.assertTrue(all(a['end']['host_ns'] < b['start']['host_ns'] for a,b in zip(ranges,ranges[1:])))
        self.assertEqual(ranges[-1]['end']['sensors']['depth']['number'], 4)

    def test_pair_skew_and_timestamp_interval(self):
        self.start()
        self.source.frames.put(frame(2,90))
        until(lambda:self.x.enqueued==2)
        r=self.finish()
        self.assertEqual(r['checks']['timing'],'WARNING')
        self.assertEqual(r['verification']['issues']['large_pair_skew'],1)
        self.assertEqual(r['verification']['issues']['depth.unusual_interval'],1)

    def test_missing_depth_fails_final_verification(self):
        self.start()
        self.source.frames.put(pair(child(2,133),None))
        until(lambda:self.x.enqueued==2)
        with self.assertRaises(RuntimeError):self.finish()
        self.assertEqual(json.loads((self.root/'exchange_verification.json').read_text())['status'],'FAIL')

    def test_overflow_keeps_prior_items_and_fails(self):
        self.x.pending=queue.Queue(1)
        entered,release=threading.Event(),threading.Event()
        store=self.raw.store_packet
        def slow(*args):
            entered.set()
            if not release.wait(3):raise RuntimeError('test barrier timeout')
            return store(*args)
        with patch.object(self.raw,'store_packet',side_effect=slow):
            self.start()
            self.assertTrue(entered.wait(1))
            self.source.frames.put(frame(2))
            self.source.frames.put(frame(3))
            until(lambda:bool(self.x.errors))
            release.set()
            result=self.finish()
        self.assertEqual((result['status'],result['queue_overflows'],result['written']),('FAIL',1,2))

    def test_disk_write_failure(self):
        with patch('raw_rgbd_recording.np.savez',side_effect=OSError('disk I/O')):
            try:
                self.start()
            except RuntimeError as exc:
                self.assertIn('disk I/O',str(exc))  # writer may fail before start returns
            until(lambda:bool(self.x.errors))
            r=self.finish()
        self.assertEqual(r['session_status'],'FAILED')
        self.assertEqual(r['errors'][0]['stage'],'storage')
        self.assertEqual(r['unwritten'],1)
        proof = json.loads((self.raw.last_clip/'exchange_validation.json').read_text())
        self.assertEqual(proof['status'], 'FAIL')
        with self.assertRaises(ValueError):
            RawClipReader(self.raw.last_clip)

    def test_hw5_timestamp_gap_keeps_failed_status_and_exports_both_predecessors(self):
        def observed(stream, number, timestamp, counter, backend, arrival):
            sample = frame(0)
            result = sample.get_color_frame() if stream == 'color' else sample.get_depth_frame()
            result.get_frame_number = lambda: number
            result.get_timestamp = lambda: timestamp
            result.get_frame_timestamp_domain = lambda: 'system_time'
            values = dict(frame_counter=counter, backend_timestamp=backend, time_of_arrival=arrival)
            result.supports_frame_metadata = lambda key: key in values
            result.get_frame_metadata = values.__getitem__
            return result

        # Rebase the HW5 SDK times. Hardware counters and prior raw metadata here are synthetic.
        samples = [pair(observed('color', 1441+i, c, 5100+i, round(c)-67, round(c)),
                        observed('depth', 1437+i, d, 6100+i, round(d)-67, round(d)))
                   for i, (c, d) in enumerate(((-53.0547, -58.8845), (13.648, 7.578),
                                              (80.312, 74.4143), (141.7344, 141.2903)))]
        sdk = NS(frame_counter='frame_counter', sensor_timestamp='sensor_timestamp',
                 backend_timestamp='backend_timestamp', time_of_arrival='time_of_arrival')
        callbacks = self.start_native(samples=samples, sdk_metadata=sdk)
        callbacks['depth'](observed('depth', 1441, 207.866, 6104, 140, 207))
        callbacks['depth'](observed('depth', 1442, 274.3704, 6105, 207, 274))
        callbacks['color'](observed('color', 1445, 280.4485, 5105, 213, 280))
        until(lambda: bool(self.x.errors))
        self.finish(reason='error')

        report = json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual((report['status'], report['session_status'], report['written']), ('FAIL', 'FAILED', 1))
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        self.assertEqual(report['checks']['receive_gap'], 'PASS')
        failure = report['native_source']['pairing_failure']
        self.assertEqual((failure['reason'], failure['sensor']['number']), ('unmatched_timestamp', 1441))
        diagnostic = failure['diagnostics']
        self.assertAlmostEqual(diagnostic['color_minus_depth_ms'], 72.5825)
        self.assertAlmostEqual(diagnostic['allowed_abs_skew_ms'], 500/15)
        self.assertEqual(diagnostic['next_candidates']['depth']['number'], 1442)
        self.assertEqual(diagnostic['previous_candidates']['depth']['number'], 1440)
        self.assertEqual(diagnostic['previous_candidates']['color']['number'], 1444)
        color_interval = diagnostic['candidate_intervals']['color']['previous_to_compared']
        self.assertAlmostEqual(color_interval['sdk_timestamp_delta_ms'], 138.7141)
        self.assertEqual(color_interval['frame_number_delta'], 1)
        self.assertEqual(color_interval['sdk_metadata_raw_deltas']['frame_counter'], 2)
        self.assertEqual(color_interval['sdk_metadata_raw_deltas']['backend_timestamp'], 138)
        self.assertEqual(color_interval['sdk_metadata_raw_deltas']['time_of_arrival'], 138)
        self.assertGreater(color_interval['host_callback_interval_ns'], 0)
        depth_interval = diagnostic['candidate_intervals']['depth']
        self.assertAlmostEqual(depth_interval['previous_to_compared']['sdk_timestamp_delta_ms'], 66.5757)
        self.assertAlmostEqual(depth_interval['compared_to_next']['sdk_timestamp_delta_ms'], 66.5044)
        self.assertEqual(diagnostic['previous_candidates']['depth']['sdk_metadata']['frame_counter'],
                         dict(status='MEASURED', raw_value=6103))
        self.assertEqual(diagnostic['previous_candidates']['color']['sdk_metadata']['sensor_timestamp'],
                         dict(status='NOT_SUPPORTED'))
        with self.assertRaises(ValueError):
            RawSessionReader(self.root)

    def test_interruption_is_distinct_and_drains(self):
        self.start()
        for n in range(2,6):self.source.frames.put(frame(n))
        until(lambda:self.x.enqueued==5)
        r=self.finish('panel_closed')
        self.assertEqual(r['session_status'],'INTERRUPTED')
        self.assertEqual(r['unwritten'],0)
        self.assertFalse(self.x.writer.is_alive())
        self.assertFalse(self.x.producer.is_alive())
        self.assertEqual(len(list(RawSessionReader(self.root,allow_incomplete=True).packets())),5)

    def test_corruption_before_publish(self):
        self.start()
        self.x.stop()
        self.raw.finish()
        folder=self.raw.last_clip
        (folder/'frames/00000001.npz').write_bytes(b'broken synthetic')
        with self.assertRaises(RuntimeError):self.x.publish()
        doc=json.loads((self.root/'recording_metadata/session_manifest.json').read_text())
        self.assertEqual(doc['status'],'FAILED')
        result=json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(result['checks']['file_integrity'],'FAIL')
        with self.assertRaisesRegex(ValueError, 'exchange validation'):
            RawClipReader(self.raw.last_clip)

    def test_legacy_clip2_reader_keeps_backward_compatibility(self):
        path = (Path(__file__).resolve().parent/'analysis/RESEARCH_B/local_private'
                /'b_pilot_20261117_141409/raw_rgbd/clip_0002')
        if not (path/'recording.json').is_file():
            self.skipTest('Historical pilot is available only in the local research workspace')
        by_clip = RawClipReader(path)
        self.assertNotIn('exchange_validation', by_clip.identity)
        frames = by_clip.packets()
        try:
            sample = next(frames)
            self.assertEqual(sample.record['frame_index'], 1)
            self.assertEqual(sample.color_bgr.dtype, np.uint8)
            self.assertEqual(sample.depth_z16.dtype, np.uint16)
        finally:
            frames.close()

    def test_preflight_blocks_no_space_and_permission(self):
        with patch('exchange_capture.shutil.disk_usage',return_value=NS(free=0)):
            with self.assertRaisesRegex(OSError,'space'):self.start()
        with patch('exchange_capture.tempfile.TemporaryFile',side_effect=PermissionError('write denied')):
            with self.assertRaises(PermissionError):self.start()
        self.assertFalse(self.raw.events.started)
        self.assertFalse(self.raw.directory.exists())

    def test_preflight_bad_camera_scale_and_missing_stream(self):
        for mutation in (lambda c:c['device']['name'].update(status='NOT_MEASURED'),
                         lambda c:c.update(depth_scale_m=0),
                         lambda c:c['streams']['color']['intrinsics'].update(coeffs=[])):
            info=camera();mutation(info)
            with self.assertRaises(ValueError):preflight(self.raw,info,1)
        self.source.frames.get_nowait()
        self.source.frames.get_nowait()
        self.source.frames.put(pair(child(),None))
        with self.assertRaisesRegex(ValueError,'depth'):self.start()
        self.assertFalse(self.raw.events.started)

    def test_sdk_rejects_unsupported_exchange_profile_before_start(self):
        self.x.fps = 30
        config = Mock()
        config.resolve.side_effect = RuntimeError('Unsupported combination')
        pipeline = Mock()
        with self.assertRaisesRegex(RuntimeError, '1280x720.*848x480.*30 FPS'):
            self.x.start_pipeline(pipeline, Mock(return_value=config), NS(pipeline_wrapper=lambda p:p))
        pipeline.start.assert_not_called()
        self.assertEqual(self.x.preflight_status, 'FAIL')

    def test_active_profile_must_match_request(self):
        self.x.start_pipeline(Mock(), Mock(), NS(pipeline_wrapper=lambda p:p, processing_block=Mock()))
        with self.assertRaisesRegex(ValueError, 'profile.*does not match'):
            self.start()  # Fixture offers a different resolution.
        self.assertFalse(self.raw.events.started)

    def test_legacy_config_requests_15_fps_by_default(self):
        import capture_d455
        config = Mock()
        sdk = NS(config=lambda:config, stream=NS(color=1,depth=2), format=NS(bgr8=3,z16=4))
        with patch.object(capture_d455,'rs',sdk):
            self.assertIs(capture_d455.make_config(), config)
        self.assertEqual([c.args[-1] for c in config.enable_stream.call_args_list], [15,15])

    def test_six_event_ranges_require_separate_review(self):
        self.start()
        session=NS(armed=False,active=None,segments=[])
        for i in range(6):
            self.raw.instruction(f'P{i}')
            session.active=dict(segment_index=i,first_device_ms=10*i)
            self.raw.observe_measurement(session)
            self.source.frames.put(frame(2+i))
            until(lambda:self.raw.total_frames==2+i)
            session.active=None
            self.raw.observe_measurement(session)
        r=self.finish()
        self.assertEqual(r['checks']['six_instructed_holds'],'PASS')
        self.assertEqual(r['checks']['stable_ground_truth'],'NOT_TESTED')
        self.assertEqual(r['status'],'PASS')
        for hold in r['verification']['observed_holds']:
            self.assertEqual(hold['first_frame'],hold['last_frame'])

    def test_environment_validation_and_cli_conflicts(self):
        import run_research_b
        for args in (['--exchange-capture'],['--exchange-capture','--participant-unregistered','--save-raw','off'],
                     ['--record-imu'], ['--exchange-fps','30'],
                     ['--exchange-capture','--participant-unregistered','--exchange-fps','60']):
            with self.assertRaises(SystemExit):run_research_b.main(args)
        path=self.root/'input.json'
        path.write_text('{"height_m":0.8,"setup":"desk"}')
        env=read_environment(path)
        self.assertEqual(env['yaw_deg'],'NOT_RECORDED')
        path.write_text('{"height_m":-1}')
        with self.assertRaises(ValueError):read_environment(path)

    def test_imu_unsupported_is_optional(self):
        self.x.record_imu=True
        self.x.start(self.source,NS(get_device=lambda:NS(query_sensors=lambda:[])),None)
        result=self.finish()
        self.assertEqual(result['imu']['status'],'WARNING')
        self.assertEqual(result['checks']['file_integrity'],'PASS')

    def test_motion_sdk_callback_drained(self):
        rs=NS(stream=NS(accel=1,gyro=2),format=NS(motion_xyz32f=3))
        sensor=Mock()
        sensor.get_stream_profiles.return_value=[NS(stream_type=lambda:1,format=lambda:3,fps=lambda:100)]
        motion=MotionLog(self.root/'motion.jsonl')
        motion.start(NS(query_sensors=lambda:[sensor]),rs)
        cb=sensor.start.call_args.args[0]
        sample=Mock()
        sample.as_motion_frame.return_value.get_motion_data.return_value=NS(x=1,y=2,z=3)
        sample.get_frame_number.return_value=8
        sample.get_timestamp.return_value=99.5
        cb(sample)
        self.assertEqual(motion.close()['saved'],1)
        sensor.stop.assert_called_once()
        self.assertEqual(json.loads(motion.path.read_text())['xyz'],[1,2,3])

    def test_launcher_to_verification_while_mediapipe_is_busy(self):
        import e0_panel
        import run_research_b
        from test_e0_fs3 import estimators, result
        from test_h9_probe_integration import SyntheticProbe
        fake = SyntheticProbe(self, [0,1,2,3])
        config = Mock()
        config.resolve.return_value = fake.pipeline.start.return_value
        make_config = Mock(return_value=config)
        sys.modules['capture_d455'].make_config = make_config
        sys.modules['pyrealsense2'].pipeline_wrapper = lambda p: p
        profile = camera()
        widths = {'color': (1280,720), 'depth': (848,480)}
        for name, stream in profile['streams'].items():
            w,h = widths[name]
            stream.update(width=w,height=h,fps=30)
        def full_frame(i):
            f = frame(i, fps=30)
            f.get_color_frame().get_data = lambda:np.zeros((720,1280,3),np.uint8)
            f.get_depth_frame().get_data = lambda:np.ones((480,848),np.uint16)
            return f
        self.source.frames = queue.Queue()
        self.source.frames.put(full_frame(0))
        self.source.frames.put(full_frame(1))
        native = Mock()
        native.warm_up.side_effect = lambda:self.source.frames.get_nowait()
        native.try_wait_for_frames.side_effect = self.source.try_wait_for_frames
        native.to_analysis_frames.side_effect = lambda f:f
        native.diagnostics.return_value = {}
        self.enterContext(patch('exchange_capture.NativeRGBDSource',return_value=native))
        fake.pipeline.try_wait_for_frames.side_effect = self.source.try_wait_for_frames
        fake.calculate.return_value = result()
        fake.cv.waitKey.side_effect = None
        fake.cv.waitKey.return_value = -1
        fake.cv.putText = Mock()
        fake.cv.FONT_HERSHEY_SIMPLEX = 0
        output = self.root/'exchange'
        model, scaler = estimators()
        verified = dict(artifact_sha256='test', model_sha256='test', scaler_sha256='test')
        binding = self.root/'binding.json'
        binding.write_text(json.dumps(dict(path='sample',feature_ids=[],**verified)))
        def blocked_pose(*args):
            for i in range(2,6):
                self.source.frames.put(full_frame(i))
            # Assert that the independent writer finished while inference has not returned.
            until(lambda:(output/'raw_rgbd/clip_0001/frames/00000005.npz').is_file())
            return NS(pose_landmarks=[])
        fake.pose.detect_for_video.side_effect = blocked_pose
        def panel(session):
            return NS(poll=lambda:fake.pose.detect_for_video.call_count==0, close=lambda:None)
        def bound(*args,**kwargs):
            return e0_panel.run_bound_probe(*args,panel_factory=panel,**kwargs)
        self.enterContext(patch('raw_rgbd_recording.camera_metadata',return_value=profile))
        for module in (e0_panel, run_research_b):
            self.enterContext(patch.object(module,'load_fs3',return_value=(model,scaler,verified)))
            self.enterContext(patch.object(module,'environment_record',return_value={}))
        self.enterContext(patch.object(run_research_b,'run_bound_probe',side_effect=bound))
        self.enterContext(patch.object(run_research_b,'ROOT',self.root))
        code=run_research_b.main(['--live','--exchange-capture','--participant-id','P02',
            '--session-label','S1','--duration-seconds','3','--binding',str(binding),'--output-dir',str(output),
            '--exchange-fps','30'])
        self.assertEqual(code,0)
        r=json.loads((output/'exchange_verification.json').read_text())
        self.assertEqual((r['written'],r['mediapipe_completed']),(5,1))
        self.assertEqual(r['session_status'],'INTERRUPTED')
        fake.pipeline.stop.assert_not_called()
        native.stop.assert_called_once()
        self.assertEqual(r['checks']['file_integrity'],'PASS')
        self.assertEqual(r['requested_fps'], 30)
        self.assertEqual(r['checks']['hardware_qualification'], 'NOT_TESTED')
        make_config.assert_called_once_with(fps=30)
        config.resolve.assert_called_once_with(fake.pipeline)
        fake.pipeline.start.assert_not_called()

    def test_user_interrupt_keeps_integrity_and_session_status(self):
        self.start()
        self.x.stop()
        interrupted=KeyboardInterrupt()
        self.raw.finish(error=interrupted)
        report=self.x.publish(interrupted)
        self.assertEqual(report['session_status'],'INTERRUPTED')
        self.assertEqual(report['checks']['file_integrity'],'PASS')

    def test_source_exception_is_persisted(self):
        self.start()
        self.source.try_wait_for_frames=Mock(side_effect=RuntimeError('SDK disconnected'))
        until(lambda:bool(self.x.errors))
        r=self.finish()
        self.assertEqual(r['session_status'],'FAILED')
        self.assertEqual(r['errors'][0]['stage'],'acquisition')

    def test_native_timestamp_failure_diagnostics_are_published_without_accepting_the_clip(self):
        callbacks = self.start_native()
        color_callback, depth_callback = callbacks['color'], callbacks['depth']
        sample = frame(5, skew=-40)
        depth_callback(sample.get_depth_frame())
        depth_callback(frame(6).get_depth_frame())
        color_callback(sample.get_color_frame())
        until(lambda: bool(self.x.errors))
        with self.assertRaisesRegex(RuntimeError, r'unmatched_timestamp \(depth, frame 5\)'):
            self.x.analysis_frame()
        self.finish(reason='error')

        report_path = self.root/'exchange_verification.json'
        report = json.loads(report_path.read_text())
        self.assertEqual((report['status'], report['session_status']), ('FAIL', 'FAILED'))
        self.assertNotIn('receive_gap', report)
        self.assertEqual((report['written'], report['unwritten']), (1, 0))
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        inventory = json.loads((self.root/'exchange_files.json').read_text())
        self.assertEqual(inventory['sha256'][report_path.name], _sha(report_path))
        diagnostic = report['native_source']['pairing_failure']['diagnostics']
        self.assertEqual(diagnostic['pairing_queue_depth'], {'color': 1, 'depth': 2})
        self.assertEqual(diagnostic['sdk_input_queue_depth_after_failure'], 0)
        self.assertAlmostEqual(diagnostic['color_minus_depth_ms'], 40)
        self.assertAlmostEqual(diagnostic['allowed_abs_skew_ms'], 500/15)
        values = diagnostic['compared_candidates']
        self.assertGreater(values['color']['host_callback_ns'], values['depth']['host_callback_ns'])
        self.assertGreaterEqual(values['depth']['pairing_queue_wait_ns'], 0)
        self.assertGreaterEqual(values['color']['callback_to_pairing_queue_ns'], 0)
        self.assertEqual(set(values['color']['sdk_metadata_raw'].values()), {'NOT_RECORDED'})
        with self.assertRaises(ValueError):
            RawSessionReader(self.root)
        with self.assertRaises(ValueError):
            RawClipReader(self.raw.last_clip)

    def test_native_gap_telemetry_keeps_success_output_and_npz_bytes(self):
        self.start_native()
        pair_info = self.x.last_accepted_pair
        self.assertLess(pair_info['latest_callback_host_ns'], pair_info['created_host_ns'])
        self.assertLessEqual(pair_info['created_host_ns'], pair_info['accepted_host_ns'])
        self.assertEqual(pair_info['sensors']['color']['number'], 4)
        report = self.finish()
        self.assertNotIn('receive_gap', report)
        self.assertEqual(report['session_status'], 'COMPLETED')
        packet = next(RawSessionReader(self.root).packets())
        expected = io.BytesIO()
        sample = frame(4)
        np.savez(HashingNPZOutput(expected), color_bgr=sample.get_color_frame().get_data(),
                 depth_z16=sample.get_depth_frame().get_data())
        path = self.raw.last_clip/'frames/00000001.npz'
        self.assertEqual(path.read_bytes(), expected.getvalue())
        self.assertEqual(packet.record['sha256'], _sha(path))

    def assert_one_sided_receive_gap(self, available, missing):
        callbacks = self.start_native()
        last_accepted = self.x.last_ns
        stream_frame = {"color": lambda f: f.get_color_frame(), "depth": lambda f: f.get_depth_frame()}[available]
        for number in range(5, 9):
            callbacks[available](stream_frame(frame(number)))
        until(lambda: self.x.timeouts >= 1)
        for number in range(9, 12):
            callbacks[available](stream_frame(frame(number)))
        until(lambda: self.x.receive_gap_failed)
        report = self.finish(reason='error')
        diagnostic = report['receive_gap']['diagnostics']
        native = diagnostic['native_input']
        streams = native['streams']
        self.assertEqual((report['status'], report['session_status']), ('FAIL', 'FAILED'))
        self.assertEqual((report['acquired'], report['written'], report['unwritten']), (1, 1, 0))
        self.assertEqual(report['checks']['receive_gap'], 'FAIL')
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        self.assertEqual(diagnostic['last_accepted_pair']['accepted_host_ns'], last_accepted)
        self.assertEqual(diagnostic['reference'], 'last_accepted_pair')
        self.assertGreaterEqual(diagnostic['observed_gap_ms'], 500)
        self.assertEqual(diagnostic['queues_at_failure']['sdk_input_depth'], 0)
        self.assertEqual(diagnostic['queues_at_failure']['pairing_depth'], {available: 7, missing: 0})
        self.assertEqual(streams[available]['callback_count'], 11)
        self.assertEqual(streams[missing]['callback_count'], 4)
        self.assertEqual(streams[available]['pairer_input_count'], 11)
        self.assertEqual(streams[available]['active_pairer_input_count'], 8)
        self.assertEqual(streams[missing]['active_pairer_input_count'], 1)
        self.assertGreater(streams[available]['last_callback_host_ns'], last_accepted)
        self.assertLess(streams[missing]['last_callback_host_ns'], last_accepted)
        self.assertGreater(streams[missing]['elapsed_since_last_callback_ms'],
                           streams[available]['elapsed_since_last_callback_ms'])
        self.assertEqual(streams[missing]['last_processed']['number'], 4)
        self.assertEqual(streams[missing]['last_processed']['sdk_metadata_raw']['time_of_arrival'], 'NOT_RECORDED')
        candidates = native['pending_candidates'][available]
        self.assertEqual([item['number'] for item in candidates], list(range(5, 12)))
        self.assertEqual(native['pending_candidates'][missing], [])
        self.assertEqual(candidates[-1]['timestamp_ms'], 11*1000/15)
        self.assertEqual(candidates[-1]['timestamp_domain'], 'hardware_clock')
        for item in candidates:
            self.assertGreaterEqual(item['host_pairer_processed_ns'], item['host_callback_ns'])
            self.assertEqual(item['pairing_queue_wait_ns'],
                             native['sampled_host_ns'] - item['host_pairing_queue_enter_ns'])
        self.assertLessEqual(len(native['recent_frame_metadata']), native['recent_frame_limit'])
        on_disk = json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(on_disk['receive_gap']['diagnostics'], diagnostic)
        with self.assertRaises(ValueError):
            RawSessionReader(self.root)
        with self.assertRaises(ValueError):
            RawClipReader(self.raw.last_clip)

    def test_rgb_only_receive_gap_exports_seven_pending_frames(self):
        self.assert_one_sided_receive_gap('color', 'depth')

    def test_depth_only_receive_gap_exports_seven_pending_frames(self):
        self.assert_one_sided_receive_gap('depth', 'color')

    def test_pair_received_before_deadline_refreshes_gap_reference(self):
        callbacks = self.start_native()
        before = self.x.last_ns
        until(lambda: self.x.timeouts == 1)
        sample = frame(5)
        callbacks['depth'](sample.get_depth_frame())
        callbacks['color'](sample.get_color_frame())
        until(lambda: self.raw.total_frames == 2)
        self.assertGreater(self.x.last_ns, before)
        self.assertLess(self.x.last_ns-before, 500_000_000)
        self.assertEqual(self.x.consecutive_timeouts, 0)
        report = self.finish()
        self.assertEqual(report['checks']['receive_gap'], 'PASS')
        self.assertEqual(report['session_status'], 'COMPLETED')
        self.assertNotIn('receive_gap', report)

    def test_two_timeout_timeline_survives_additional_cleanup_exception(self):
        callbacks = self.start_native()
        accepted = self.x.last_ns
        until(lambda: self.x.receive_gap_failed)
        # A late pair cannot restore the failed capture or change the frozen snapshot.
        sample = frame(5)
        callbacks['color'](sample.get_color_frame())
        callbacks['depth'](sample.get_depth_frame())
        self.x.motion = Mock(**{'close.side_effect': RuntimeError('additional cleanup error')})
        with self.assertRaisesRegex(RuntimeError, 'additional cleanup error') as cleanup:
            self.x.stop()
        self.raw.finish(termination='error', error=cleanup.exception)
        self.x.publish(cleanup.exception)
        report = json.loads((self.root/'exchange_verification.json').read_text())
        diagnostic = report['receive_gap']['diagnostics']
        waits = diagnostic['timeout_history']
        self.assertEqual(report['session_status'], 'FAILED')
        self.assertEqual([err['stage'] for err in report['errors']], ['receive_gap', 'execution'])
        self.assertEqual(report['errors'][1]['detail'], 'additional cleanup error')
        self.assertEqual(report['written'], 1)
        self.assertEqual(report['receiver_timeouts'], 2)
        self.assertEqual(diagnostic['consecutive_timeouts'], 2)
        self.assertEqual(diagnostic['reference_host_ns'], accepted)
        self.assertEqual(diagnostic['sdk_wait_budget_ms'], 250)
        self.assertEqual(diagnostic['gap_limit_ms'], 500)
        self.assertEqual(len(waits), 2)
        self.assertEqual(diagnostic['last_completed_wait'], waits[-1])
        self.assertEqual(diagnostic['last_wait_started_host_ns'], waits[-1]['started_host_ns'])
        self.assertLessEqual(waits[0]['returned_host_ns'], waits[1]['started_host_ns'])
        self.assertLessEqual(waits[-1]['returned_host_ns'], diagnostic['detected_host_ns'])
        for wait in waits:
            self.assertEqual(wait['outcome'], 'timeout')
            self.assertEqual(wait['elapsed_ms'], (wait['returned_host_ns']-wait['started_host_ns'])/1e6)
            self.assertGreaterEqual(wait['elapsed_ms'], 245)
        self.assertEqual(diagnostic['observed_gap_ms'], (diagnostic['detected_host_ns']-accepted)/1e6)
        self.assertGreaterEqual(diagnostic['observed_gap_ms'], 500)
        self.assertEqual(diagnostic['native_input']['streams']['color']['callback_count'], 4)
        self.assertEqual(diagnostic['native_input']['streams']['depth']['callback_count'], 4)

    def test_post_close_failure_to_publish_cannot_leave_completed_manifest(self):
        self.start()
        self.x.stop()
        self.raw.finish()
        from e0_storage import write_json
        def fail_inventory(path, doc):
            if path.name == 'exchange_files.json':
                raise OSError('inventory cannot be written')
            write_json(path, doc)
        with patch('exchange_verification.write_json',side_effect=fail_inventory):
            with self.assertRaises(OSError): self.x.publish()
        manifest=json.loads((self.root/'recording_metadata/session_manifest.json').read_text())
        self.assertEqual(manifest['status'],'PENDING_VERIFICATION')
        self.assertEqual(json.loads((self.root/'exchange_publication_failure.json').read_text())['status'],'FAIL')
        with self.assertRaises(ValueError): RawSessionReader(self.root)
        with self.assertRaisesRegex(ValueError, 'exchange validation'): RawClipReader(self.raw.last_clip)

    def test_missing_review_template_blocks_package(self):
        self.start()
        self.x.stop()
        self.raw.finish()
        (self.root/'stable_intervals_template.json').unlink()
        with self.assertRaises(RuntimeError):self.x.publish()
        report=json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(report['checks']['file_integrity'],'FAIL')

    def test_failed_proof_publication_never_admits_clip_or_session(self):
        self.start()
        self.x.stop()
        self.raw.finish()
        replace = Path.replace
        def fail_final_proof(path, target):
            if target.name == 'exchange_validation.json':
                raise PermissionError('simulated failure at final validation rename')
            return replace(path, target)
        with patch.object(Path, 'replace', fail_final_proof):
            with self.assertRaises(PermissionError):
                self.x.publish()
        manifest = json.loads((self.root/'recording_metadata/session_manifest.json').read_text())
        proof = json.loads((self.raw.last_clip/'exchange_validation.json').read_text())
        self.assertEqual(manifest['status'], 'FAILED')
        self.assertEqual(proof['session_status'], 'FAILED')
        with self.assertRaises(ValueError):
            RawSessionReader(self.root)
        with self.assertRaisesRegex(ValueError, 'exchange validation'):
            RawClipReader(self.raw.last_clip)

    def test_new_npz_is_readable_by_existing_sdk_software_replay(self):
        import pyrealsense2 as rs
        from e0_replay import ReplayInput
        from test_e0_replay import camera as sdk_camera, packet
        profile=camera()
        profile['streams']=sdk_camera()['streams']
        for stream in profile['streams'].values():stream.update(width=64,height=48)
        self.raw._metadata=lambda:profile
        self.source.frames=queue.Queue()
        for i in (1,2):
            f=packet(i,i*67).native_frames
            f.get_color_frame().get_data=lambda:np.full((48,64,3),17,np.uint8)
            f.get_depth_frame().get_data=lambda:np.full((48,64),1234,np.uint16)
            self.source.frames.put(f)
        self.start()
        self.finish()
        replay=ReplayInput(self.root)
        replay.start(rs)
        try:
            replay.begin_stream()
            ready, restored=replay.read()
            self.assertTrue(ready)
            self.assertEqual(restored.get_frame_number(),2)
            self.assertEqual(restored.get_timestamp(),134)
            self.assertEqual(np.asanyarray(restored.get_depth_frame().get_data())[0,0],1234)
            self.assertFalse(replay.read()[0])
        finally:
            replay.stop()
