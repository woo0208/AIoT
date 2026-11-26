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
            children = [('color', sample.get_color_frame()), ('depth', sample.get_depth_frame())]
            for name, child_frame in sorted(children, key=lambda item: item[1].get_timestamp()):
                callbacks[name](child_frame)
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
        self.assertEqual((result['unqueued'], result['unwritten'], result['total_unstored']), (1, 0, 1))
        overflow = result['raw_queue_overflow']
        self.assertEqual(overflow['rejected_pair']['receive_index'], 3)
        self.assertEqual(overflow['rejected_pair']['sensors']['depth']['number'], 3)
        self.assertEqual(overflow['active']['receive_index'], 1)

    def test_15fps_queue_recovers_after_io_stall_exceeding_hardware_delay(self):
        self.start()
        until(lambda: self.raw.total_frames == 1)
        entered, release = threading.Event(), threading.Event()
        store = self.raw.store_packet

        def stall_second(*args):
            if args[1]['receive_index'] == 2:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('test did not release blocked write')
            return store(*args)

        with patch.object(self.raw, 'store_packet', side_effect=stall_second):
            self.source.frames.put(frame(2))
            self.assertTrue(entered.wait(1))
            try:
                for n in range(3, 14):
                    time.sleep(1/15)
                    self.source.frames.put(frame(n))
                until(lambda: self.x.enqueued == 13)
                self.assertEqual(self.raw.total_frames, 1)
            finally:
                release.set()
            until(lambda: self.raw.total_frames == 13)
            self.assertTrue(self.x.pending.empty())
            self.source.frames.put(frame(14))
            until(lambda: self.x.enqueued == 14)
            report = self.finish()
        self.assertEqual((report['acquired'], report['queued'], report['written']), (14, 14, 14))
        self.assertEqual((report['queue_overflows'], report['total_unstored']), (0, 0))
        self.assertEqual(report['raw_queue']['peak'], 11)
        stages = report['writer_stage_ms']['writer_total']
        self.assertGreaterEqual(stages['max'], 451.6)
        self.assertTrue(0 < stages['p50'] <= stages['p95'] <= stages['p99'] <= stages['max'])
        self.assertEqual(report['writer_timing']['longest_slow_streak'], 1)
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        packets = list(RawSessionReader(self.root).packets())
        self.assertEqual([p.record['sensors']['depth']['number'] for p in packets], list(range(1, 15)))
        np.testing.assert_array_equal(packets[-1].depth_z16, [[0, 65535], [1, 1024]])
        self.assertEqual(packets[-1].record['sha256'], _sha(self.raw.last_clip/'frames/00000014.npz'))

    def test_consecutive_slower_writes_drain_with_full_counts(self):
        self.start()
        until(lambda: self.raw.total_frames == 1)
        store = self.raw.store_packet

        def three_slow(*args):
            if 2 <= args[1]['receive_index'] <= 4:
                time.sleep(.20)
            return store(*args)

        with patch.object(self.raw, 'store_packet', side_effect=three_slow):
            for number in range(2, 12):
                self.source.frames.put(frame(number))
                time.sleep(1/15)
            until(lambda: self.x.enqueued == 11)
            report = self.finish()
        self.assertEqual((report['written'], report['queued'], report['total_unstored']), (11, 11, 0))
        self.assertEqual(report['writer_timing']['longest_slow_streak'], 3)
        self.assertLessEqual(report['raw_queue']['peak'], 16)
        self.assertFalse(self.x.writer.is_alive())

    def test_sustained_bottleneck_hits_real_capacity_and_explicitly_fails(self):
        self.start()
        until(lambda: self.raw.total_frames == 1)
        entered, release = threading.Event(), threading.Event()
        store = self.raw.store_packet

        def blocked(*args):
            if args[1]['receive_index'] == 2:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('test writer timed out')
            return store(*args)

        with patch.object(self.raw, 'store_packet', side_effect=blocked):
            self.source.frames.put(frame(2))
            self.assertTrue(entered.wait(1))
            try:
                for number in range(3, 20):
                    time.sleep(1/15)
                    self.source.frames.put(frame(number))
                until(lambda: bool(self.x.errors))
                self.assertEqual(self.x.pending.qsize(), 16)
                self.assertTrue(self.x.stop_request.is_set())
            finally:
                release.set()
            report = self.finish()
        self.assertEqual((report['status'], report['acquired'], report['queued'], report['written']),
                         ('FAIL', 19, 18, 18))
        self.assertEqual(report['total_unstored'], 1)
        self.assertEqual(report['raw_queue']['peak'], 16)
        self.assertEqual(report['raw_queue_overflow']['rejected_pair']['receive_index'], 19)
        self.assertFalse(self.x.writer.is_alive())

    def test_drain_deadline_keeps_stuck_clip_unfinalized(self):
        self.start()
        until(lambda: self.raw.total_frames == 1)
        entered, release = threading.Event(), threading.Event()

        def blocked(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test writer timed out')

        with patch.object(self.raw, 'store_packet', side_effect=blocked):
            self.source.frames.put(frame(2))
            self.assertTrue(entered.wait(1))
            self.source.frames.put(frame(3))
            until(lambda: self.x.enqueued == 3)
            try:
                with patch('exchange_capture.WRITER_DRAIN_TIMEOUT_S', .05):
                    report = self.finish()
                self.assertEqual((report['status'], report['written'], report['unwritten']), ('FAIL', 1, 2))
                self.assertEqual(report['writer_stall']['active']['receive_index'], 2)
                self.assertEqual(report['checks']['file_integrity'], 'FAIL')
                self.assertFalse((self.raw.current/'end.json').exists())
                self.assertFalse((self.root/'recording_metadata/session_manifest.json').exists())
                self.assertFalse((self.raw.current/'exchange_validation.json').exists())
            finally:
                release.set()
                self.x.writer.join(1)
                self.raw._index.close()
        self.assertFalse(self.x.writer.is_alive())

    def test_capture_only_measurement_uses_native_time_and_original_event_links(self):
        from exchange_capture_only import CaptureOnlySession
        self.x.capture_only = True
        measurement = CaptureOnlySession(self.raw)
        self.x.record_measurement = measurement.observe_pair
        self.start()
        self.raw.instruction('P0')
        measurement.arm_segment()
        for number in range(2, 153):
            self.source.frames.put(frame(number))
            until(lambda: self.raw.total_frames == number)
        report = self.finish()
        self.assertEqual((report['capture_mode'], report['written'], report['mediapipe_completed']),
                         ('capture_only', 152, 0))
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        hold, = report['verification']['observed_holds']
        self.assertEqual((hold['first_frame'], hold['last_frame']), (2, 151))
        events = [json.loads(line) for line in
                  (self.root/'recording_metadata/events.jsonl').read_text(encoding='utf-8').splitlines()]
        request, = [e for e in events if e['event'] == 'MEASUREMENT_START']
        start, = [e for e in events if e['event'] == 'POSTURE_HOLD_START']
        end, = [e for e in events if e['event'] == 'POSTURE_HOLD_END']
        self.assertEqual(request['details']['source'], 'capture-only operator state')
        self.assertEqual(end['details']['status'], 'RECORDED_UNASSESSED')
        self.assertEqual(start['details']['start_frame_reference']['receive_index'], 2)
        self.assertEqual(end['details']['end_frame_reference']['receive_index'], 152)
        self.assertAlmostEqual(end['details']['end_device_ms'] - start['details']['first_device_ms'], 10_000)

    def test_capture_only_interruption_keeps_latest_recorded_measurement_anchor(self):
        from exchange_capture_only import CaptureOnlySession
        self.x.capture_only = True
        measurement = CaptureOnlySession(self.raw)
        self.x.record_measurement = measurement.observe_pair
        self.start()
        self.raw.instruction('P0')
        measurement.arm_segment()
        for number in (2, 3, 4):
            self.source.frames.put(frame(number))
            until(lambda: self.raw.total_frames == number)
        report = self.finish('panel_closed')
        self.assertEqual(report['session_status'], 'INTERRUPTED')
        events = [json.loads(line) for line in
                  (self.root/'recording_metadata/events.jsonl').read_text(encoding='utf-8').splitlines()]
        end, = [e['details'] for e in events if e['event'] == 'POSTURE_HOLD_END']
        self.assertEqual(end['status'], 'INTERRUPTED')
        self.assertEqual(end['end_frame_reference']['receive_index'], 4)

    def test_rgb_preview_uses_latest_and_keeps_native_npz_and_measurement(self):
        from concurrent.futures import ThreadPoolExecutor
        from exchange_capture_only import CaptureOnlyPanel, CaptureOnlySession, RGB_PREVIEW_INTERVAL_NS
        self.x = ExchangeCapture(self.raw, environment=read_environment(None), duration=3,
                                 record_imu=False, capture_only=True, rgb_preview=True)
        self.raw.exchange = self.x
        session = CaptureOnlySession(self.raw)
        self.x.record_measurement = session.observe_pair
        callbacks = self.start_native()
        tk = NS(Tk=Mock(), StringVar=Mock(), Label=Mock(), Button=Mock(), Frame=Mock(),
                PhotoImage=Mock(), TclError=RuntimeError)
        panel = CaptureOnlyPanel(session, tk_module=tk)
        self.addCleanup(panel.destroy)
        panel._raw_instruction('P0')
        self.assertTrue(panel.control.start())

        entered, release = threading.Event(), threading.Event()
        first_photo, next_photo = Mock(), Mock()

        def slow_first_photo(**kwargs):
            if tk.PhotoImage.call_count == 1:
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Preview did not get released')
                return first_photo
            return next_photo

        tk.PhotoImage.side_effect = slow_first_photo
        colors = [frame(4).get_color_frame().get_data()]
        with ThreadPoolExecutor(max_workers=1) as ui:
            draw = ui.submit(panel._update_rgb_preview, 0)
            try:
                self.assertTrue(entered.wait(1))
                for number in (5, 6, 7):
                    sample = frame(number)
                    bgr = np.broadcast_to(np.array([number, number+1, number+2], dtype=np.uint8),
                                          (2, 2, 3)).copy()
                    colors.append(bgr)
                    sample.get_color_frame().get_data = lambda bgr=bgr: bgr
                    callbacks['depth'](sample.get_depth_frame())
                    callbacks['color'](sample.get_color_frame())
                until(lambda: self.raw.total_frames == 4)
                self.assertFalse(draw.done())
            finally:
                release.set()
            draw.result(timeout=1)

        panel._update_rgb_preview(RGB_PREVIEW_INTERVAL_NS - 1)
        self.assertEqual(tk.PhotoImage.call_count, 1)
        panel._update_rgb_preview(RGB_PREVIEW_INTERVAL_NS)
        self.assertEqual(tk.PhotoImage.call_count, 2)
        self.assertEqual(tk.PhotoImage.call_args.kwargs['data'], b'P6\n1 1\n255\n' + bytes((9, 8, 7)))
        self.assertIs(panel._preview_image, next_photo)
        self.assertIsNone(self.x.take_rgb_preview())

        report = self.finish()
        self.assertFalse(self.x.rgb_preview_enabled)
        self.assertEqual((report['acquired'], report['queued'], report['written']), (4, 4, 4))
        self.assertEqual((report['total_unstored'], report['queue_overflows'], report['mediapipe_completed']),
                         (0, 0, 0))
        packets = list(RawSessionReader(self.root).packets())
        for index, (packet, original_rgb) in enumerate(zip(packets, colors, strict=True), 1):
            np.testing.assert_array_equal(packet.color_bgr, original_rgb)
            native_depth = frame(index+3).get_depth_frame().get_data()
            np.testing.assert_array_equal(packet.depth_z16, native_depth)
            self.assertEqual(packet.record['sensors']['color']['number'], index+3)
            self.assertEqual(packet.record['sensors']['depth']['number'], index+3)
            expected = io.BytesIO()
            np.savez(HashingNPZOutput(expected), color_bgr=original_rgb, depth_z16=native_depth)
            path = self.raw.last_clip/f'frames/{index:08d}.npz'
            self.assertEqual(path.read_bytes(), expected.getvalue())
            self.assertEqual(packet.record['sha256'], _sha(path))
        hold, = report['verification']['observed_holds']
        self.assertEqual((hold['instruction'], hold['first_frame'], hold['last_frame']), ('P0', 2, 4))

    def test_rgb_preview_tk_error_disables_display_without_stopping_recording(self):
        from exchange_capture_only import CaptureOnlyPanel, CaptureOnlySession
        self.x = ExchangeCapture(self.raw, environment=read_environment(None), duration=3,
                                 record_imu=False, capture_only=True, rgb_preview=True)
        self.raw.exchange = self.x
        tk = NS(Tk=Mock(), StringVar=Mock(), Label=Mock(), Button=Mock(), Frame=Mock(),
                PhotoImage=Mock(side_effect=RuntimeError('mock display error')), TclError=RuntimeError)
        panel = CaptureOnlyPanel(CaptureOnlySession(self.raw), tk_module=tk)
        self.addCleanup(panel.destroy)
        self.start()
        until(lambda: self.raw.total_frames == 1)
        until(lambda: bool(self.x._rgb_preview))
        preview = self.x.take_rgb_preview()
        self.assertFalse(preview.flags.writeable)
        self.source.frames.put(frame(2))
        until(lambda: bool(self.x._rgb_preview))
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertTrue(panel.poll())
        self.assertIn('RGB preview disabled', stderr.getvalue())
        self.assertFalse(self.x.rgb_preview_enabled)
        self.assertIsNone(panel._preview_label)
        self.source.frames.put(frame(3))
        until(lambda: self.raw.total_frames == 3)
        report = self.finish()
        self.assertEqual((report['session_status'], report['written']), ('COMPLETED', 3))
        self.assertEqual(report['checks']['file_integrity'], 'PASS')

    def test_capture_only_preview_off_skips_tk_image_and_accepts_only_explicit_flag(self):
        import run_research_b
        from exchange_capture_only import CaptureOnlyPanel, CaptureOnlySession
        self.x.capture_only = True
        tk = NS(Tk=Mock(), StringVar=Mock(), Label=Mock(), Button=Mock(), Frame=Mock(),
                PhotoImage=Mock(), TclError=RuntimeError)
        panel = CaptureOnlyPanel(CaptureOnlySession(self.raw), tk_module=tk)
        self.addCleanup(panel.destroy)
        self.start()
        self.assertTrue(panel.poll())
        self.assertIsNone(self.x.take_rgb_preview())
        tk.PhotoImage.assert_not_called()
        self.assertEqual(self.finish()['written'], 1)
        with patch.object(run_research_b, 'ROOT', self.root):
            target = str(self.root/'preview')
            with patch('exchange_capture_only.run_capture_only') as run:
                self.assertEqual(run_research_b.main(['--live', '--capture-only', '--rgb-preview',
                    '--exchange-capture', '--participant-unregistered', '--output-dir', target]), 0)
                self.assertTrue(run.call_args.kwargs['rgb_preview'])
            with self.assertRaises(SystemExit):
                run_research_b.main(['--check-only', '--rgb-preview', '--output-dir', target])

    def test_capture_only_cli_skips_model_and_probe_initialization(self):
        import run_research_b
        target = self.root/'capture-only'
        source = Input()
        forbidden = AssertionError('live analysis must not run in capture-only')
        panel = Mock()
        panel.poll.return_value = True
        with (patch.object(run_research_b, 'ROOT', self.root),
              patch.object(run_research_b, 'load_fs3', side_effect=forbidden),
              patch.object(run_research_b, 'run_bound_probe', side_effect=forbidden),
              patch.object(run_research_b, 'run_probe', side_effect=forbidden),
              patch('pyrealsense2.pipeline', return_value=source),
              patch.object(ExchangeCapture, 'start_pipeline', return_value=None),
              patch('exchange_capture_only.camera_metadata', side_effect=lambda *_: camera()),
              patch('exchange_capture_only.CaptureOnlyPanel', return_value=panel)):
            self.assertEqual(run_research_b.main([
                '--live', '--capture-only', '--exchange-capture', '--participant-unregistered',
                '--duration-seconds', '.20', '--output-dir', str(target)]), 0)
        report = json.loads((target/'exchange_verification.json').read_text(encoding='utf-8'))
        self.assertEqual((report['session_status'], report['written'], report['mediapipe_completed']),
                         ('COMPLETED', 1, 0))
        self.assertEqual(report['capture_mode'], 'capture_only')
        self.assertEqual(report['live_measurement_assessment'], 'NOT_ASSESSED')
        self.assertEqual(len(list(RawSessionReader(target).packets())), 1)

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

    def test_hw5_timestamp_gap_recovers_and_preserves_saved_identity_and_measurement(self):
        self._check_hw5_timestamp_gap('P0')

    def test_recovery_is_reported_in_each_posture_with_preview_on_and_off(self):
        for rgb_preview in (False, True):
            for posture in ('P0', 'P1', 'P2', 'P3', 'P4', 'P5'):
                with self.subTest(rgb_preview=rgb_preview, posture=posture):
                    self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
                    self.raw = RawRecordingControl(self.root/'raw_rgbd', initial='on',
                                                   session_context={'participant_id':'P02','session_label':'S1'})
                    self.raw.bind(camera)
                    self.x = ExchangeCapture(self.raw, environment=read_environment(None), duration=3,
                                             record_imu=False, capture_only=True, rgb_preview=rgb_preview)
                    self.raw.exchange = self.x
                    self.source = Input()
                    try:
                        self._check_hw5_timestamp_gap(posture)
                    finally:
                        self.cleanup()

    def _check_hw5_timestamp_gap(self, posture):
        def part(stream, number, stamp):
            sample = frame(number)
            result = sample.get_color_frame() if stream == 'color' else sample.get_depth_frame()
            result.get_timestamp = lambda: stamp
            result.get_frame_timestamp_domain = lambda: 'system_time'
            if stream == 'depth':
                result.get_data = lambda: np.array([[0, 65535], [number, 1024]], dtype=np.uint16)
            else:
                result.get_data = lambda: np.full((2, 2, 3), number % 256, dtype=np.uint8)
            return result

        # Rebase the hardware observations. The callbacks retain the recorded Depth/Depth/RGB order.
        samples = [pair(part('color', 1441+i, c), part('depth', 1437+i, d))
                   for i, (c, d) in enumerate(((-53.0547, -58.8845), (13.648, 7.578),
                                              (80.312, 74.4143), (141.7344, 141.2903)))]
        callbacks = self.start_native(samples=samples)
        self.raw.instruction(posture)
        self.raw.observe_measurement(NS(armed=False, active=dict(segment_index=0, first_device_ms=141.2903),
                                        segments=[]))
        callbacks['depth'](part('depth', 1441, 207.866))
        callbacks['depth'](part('depth', 1442, 274.3704))
        callbacks['color'](part('color', 1445, 280.4485))
        until(lambda: bool(self.x.native_source.pairer.recoveries))
        self.assertEqual(self.raw.total_frames, 1)
        # The synthetic next pair closes both comparison windows and then reaches disk itself.
        callbacks['depth'](part('depth', 1443, 341.04))
        callbacks['color'](part('color', 1446, 347.12))
        until(lambda: self.raw.total_frames == 3)
        report = self.finish()

        self.assertEqual((report['status'], report['session_status'], report['written']),
                         ('RECOVERED_WITH_GAPS', 'COMPLETED', 3))
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        self.assertEqual(report['checks']['continuity'], 'WARNING')
        self.assertEqual(report['checks']['timing'], 'WARNING')
        self.assertEqual(report['checks']['receive_gap'], 'PASS')
        self.assertEqual(report['unwritten'], 0)
        self.assertEqual(report['verification']['issues']['depth.NUMBER_GAP'], 1)
        self.assertEqual(report['verification']['pairing_recovery']['documented_issues']['depth.NUMBER_GAP'], 1)
        self.assertIsNone(report['native_source']['pairing_failure'])
        recovery, = report['native_source']['pairing_recoveries']
        excluded, = recovery['excluded']
        self.assertEqual((excluded['stream'], excluded['sensor']['number'], excluded['sensor']['timestamp_ms']),
                         ('depth', 1441, 207.866))
        self.assertEqual((recovery['status'], recovery['scope'], recovery['resumed_receive_index']),
                         ('RECOVERED', 'RECORDING', 2))
        window, = recovery['affected_measurement_windows']
        self.assertEqual((window['posture_id'], window['e0_segment_index']), (posture, 0))
        self.assertLess(recovery['confirmation_latest_callback_ns'], recovery['recovery_deadline_host_ns'])
        self.assertTrue(window['segment_id'].endswith('/measurement_0001'))
        with self.assertRaisesRegex(ValueError, 'recovered with pairing gaps'):
            RawSessionReader(self.root)
        with self.assertRaisesRegex(ValueError, 'exchange validation'):
            RawClipReader(self.raw.last_clip)
        packets = list(RawSessionReader(self.root, allow_incomplete=True).packets())
        self.assertEqual([(packet.record['sensors']['color']['number'], packet.record['sensors']['depth']['number'])
                          for packet in packets], [(1444, 1440), (1445, 1442), (1446, 1443)])
        resumed = packets[1]
        from exchange_verification import _matches_recovery
        delayed = dict(recovery, ended_host_ns=recovery['recovery_deadline_host_ns'] + 1)
        self.assertTrue(_matches_recovery(delayed, resumed.record, {}, 500/15))
        late = dict(recovery, confirmation_latest_callback_ns=recovery['recovery_deadline_host_ns'])
        self.assertFalse(_matches_recovery(late, resumed.record, {}, 500/15))
        self.assertEqual(resumed.record['sensors']['depth']['timestamp_ms'], 274.3704)
        self.assertEqual(resumed.record['sensors']['color']['timestamp_ms'], 280.4485)
        np.testing.assert_array_equal(resumed.depth_z16, [[0, 65535], [1442, 1024]])
        np.testing.assert_array_equal(resumed.color_bgr, np.full((2, 2, 3), 1445 % 256, dtype=np.uint8))
        inventory = json.loads((self.root/'exchange_files.json').read_text())
        self.assertEqual(inventory['sha256']['exchange_verification.json'], _sha(self.root/'exchange_verification.json'))

    def test_p05_absent_present_absent_rgb_records_two_gaps_in_each_posture_with_preview_on_and_off(self):
        for rgb_preview in (False, True):
            for posture in ('P0', 'P1', 'P2', 'P3', 'P4', 'P5'):
                with self.subTest(rgb_preview=rgb_preview, posture=posture):
                    self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
                    self.raw = RawRecordingControl(self.root/'raw_rgbd', initial='on',
                                                   session_context={'participant_id':'P02','session_label':'S1'})
                    self.raw.bind(camera)
                    self.x = ExchangeCapture(self.raw, environment=read_environment(None), duration=3,
                                             record_imu=False, capture_only=True, rgb_preview=rgb_preview)
                    self.raw.exchange = self.x
                    self.source = Input()
                    try:
                        self._check_p05_absent_present_absent(posture)
                    finally:
                        self.cleanup()

    def _check_p05_absent_present_absent(self, posture):
        period = 1000 / 15

        def part(stream, number, slot):
            sample = frame(number)
            result = sample.get_color_frame() if stream == 'color' else sample.get_depth_frame()
            stamp = slot * period + (6.0 if stream == 'color' else 0.0)
            result.get_timestamp = lambda: stamp
            result.get_frame_timestamp_domain = lambda: 'system_time'
            if stream == 'depth':
                result.get_data = lambda: np.array([[0, 65535], [number, 1024]], dtype=np.uint16)
            else:
                result.get_data = lambda: np.full((2, 2, 3), number % 256, dtype=np.uint8)
            return result

        callbacks = self.start_native(samples=[pair(part('color', k, k), part('depth', k, k)) for k in range(1, 5)])
        self.raw.instruction(posture)
        self.raw.observe_measurement(NS(armed=False, active=dict(segment_index=0, first_device_ms=4 * period),
                                        segments=[]))
        # RGB slot 5 is absent upstream; host RGB numbers stay contiguous.
        callbacks['depth'](part('depth', 5, 5))
        callbacks['depth'](part('depth', 6, 6))
        callbacks['color'](part('color', 5, 6))
        until(lambda: len(self.x.native_source.pairer.recoveries) == 1)
        # RGB slot 7 is absent too (P05_B 18:08). The confirming RGB frame
        # arrives after the previous 133.3 ms wait but inside 233.3 ms.
        callbacks['depth'](part('depth', 7, 7))
        time.sleep(0.17)
        callbacks['depth'](part('depth', 8, 8))
        callbacks['color'](part('color', 6, 8))
        callbacks['depth'](part('depth', 9, 9))
        callbacks['color'](part('color', 7, 9))
        until(lambda: self.raw.total_frames == 4)
        report = self.finish()

        self.assertEqual((report['status'], report['session_status'], report['written']),
                         ('RECOVERED_WITH_GAPS', 'COMPLETED', 4))
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        self.assertEqual(report['checks']['receive_gap'], 'PASS')
        self.assertEqual(report['checks']['pairing_recovery'], 'WARNING')
        self.assertEqual(report['unwritten'], 0)
        self.assertIsNone(report['native_source']['pairing_failure'])
        self.assertEqual(report['verification']['pairing_recovery']['verified_resumptions'], 2)
        self.assertEqual(report['verification']['issues']['depth.NUMBER_GAP'], 2)
        first, second = report['native_source']['pairing_recoveries']
        self.assertEqual([(i['stream'], i['sensor']['number']) for i in first['excluded']], [('depth', 5)])
        self.assertEqual([(i['stream'], i['sensor']['number']) for i in second['excluded']], [('depth', 7)])
        for incident in (first, second):
            self.assertEqual((incident['status'], incident['scope']), ('RECOVERED', 'RECORDING'))
            window, = incident['affected_measurement_windows']
            self.assertEqual((window['posture_id'], window['e0_segment_index']), (posture, 0))
            self.assertLess(incident['confirmation_latest_callback_ns'], incident['recovery_deadline_host_ns'])
        self.assertGreater(first['confirmation_latest_callback_ns'] - first['started_host_ns'], 133_333_334)
        packets = list(RawSessionReader(self.root, allow_incomplete=True).packets())
        self.assertEqual([(packet.record['sensors']['color']['number'], packet.record['sensors']['depth']['number'])
                          for packet in packets], [(4, 4), (5, 6), (6, 8), (7, 9)])
        for packet in packets:
            depth_number = packet.record['sensors']['depth']['number']
            color_number = packet.record['sensors']['color']['number']
            np.testing.assert_array_equal(packet.depth_z16, [[0, 65535], [depth_number, 1024]])
            np.testing.assert_array_equal(packet.color_bgr, np.full((2, 2, 3), color_number % 256, dtype=np.uint8))
            self.assertLessEqual(abs(packet.record['pairing']['color_minus_depth_ms']), 500 / 15)

    def test_recovery_report_cannot_excuse_an_unverified_number_gap(self):
        callbacks = self.start_native()
        callbacks['depth'](frame(5).get_depth_frame())
        callbacks['depth'](frame(6).get_depth_frame())
        color = frame(5).get_color_frame()
        color.get_timestamp = lambda: 406.0
        callbacks['color'](color)
        callbacks['depth'](frame(7).get_depth_frame())
        next_color = frame(6).get_color_frame()
        next_color.get_timestamp = lambda: 472.67
        callbacks['color'](next_color)
        until(lambda: self.raw.total_frames == 3)
        incident, = self.x.native_source.pairer.recoveries
        incident['excluded'][0]['sensor']['number'] = 999  # Simulate an incorrect gap record.
        with self.assertRaisesRegex(RuntimeError, 'verification'):
            self.finish()
        report = json.loads((self.root/'exchange_verification.json').read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['checks']['file_integrity'], 'PASS')
        self.assertEqual(report['checks']['continuity'], 'FAIL')
        self.assertEqual(report['checks']['pairing_recovery'], 'FAIL')
        self.assertEqual(report['verification']['issues']['unverified_pairing_recovery'], 1)

    def test_operator_interruption_preserves_pending_unpaired_record(self):
        callbacks = self.start_native()
        sample = frame(5)
        callbacks['depth'](sample.get_depth_frame())
        color = sample.get_color_frame()
        color.get_timestamp = lambda: 398.0
        callbacks['color'](color)
        until(lambda: bool(self.x.native_source.pairer.recoveries))
        report = self.finish('panel_closed')
        self.assertEqual((report['status'], report['session_status']), ('WARNING', 'INTERRUPTED'))
        incident, = report['native_source']['pairing_recoveries']
        self.assertEqual((incident['status'], incident['scope']), ('INTERRUPTED', 'RECORDING'))
        self.assertEqual([item['sensor']['number'] for item in incident['excluded']], [5])
        self.assertNotIn('resumed_receive_index', incident)
        self.assertEqual(report['written'], 1)

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
        sample = frame(5)
        depth_callback(sample.get_depth_frame())
        color = sample.get_color_frame()
        color.get_timestamp = lambda: 398.0
        color_callback(color)
        until(lambda: bool(self.x.errors))
        with self.assertRaisesRegex(RuntimeError, r'unmatched_timestamp_timeout \(depth, frame 5\)'):
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
        self.assertEqual(diagnostic['pairing_queue_depth'], {'color': 1, 'depth': 1})
        self.assertEqual(diagnostic['sdk_input_queue_depth_after_failure'], 0)
        self.assertEqual(diagnostic['terminal_pairing_snapshot']['pairing_queue_depth'], {'color': 1, 'depth': 0})
        self.assertGreaterEqual(diagnostic['deadline_trigger_host_ns'], diagnostic['recovery_deadline_host_ns'])
        self.assertEqual(diagnostic['next_candidates']['depth'], 'NOT_RECORDED')
        self.assertAlmostEqual(diagnostic['color_minus_depth_ms'], 398 - 5000/15)
        recovery, = report['native_source']['pairing_recoveries']
        self.assertEqual((recovery['status'], recovery['failure_reason']), ('FAILED', 'unmatched_timestamp_timeout'))
        self.assertEqual(recovery['excluded'][0]['sensor']['number'], 5)
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
