"""HW7 guide with synthetic sensor callbacks, the existing E0 window and real NPZ I/O."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from e0_fs3 import E0Session
from e0_guided_panel import GuidedControl, GuidedPanel
from exchange_capture import ExchangeCapture, read_environment
from exchange_native import NativeRGBDSource
from exchange_verification import _guided_intervals
from raw_rgbd_recording import RawRecordingControl, RawRecordingError, _sha
from raw_rgbd_replay import RawClipReader, RawSessionReader
from test_e0_fs3 import estimators, result
from test_exchange_capture import camera, frame, until


class GuidedCaptureTests(TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        model, scaler = estimators()
        self.enterContext(patch.object(model, 'predict', return_value=np.array([5])))
        self.session = E0Session(root/'run', model, scaler, mode='summary')
        self.root = self.session.directory
        self.context = dict(participant_id='P02', session_label='S2', repetition=5)
        self.raw = RawRecordingControl(self.root/'raw_rgbd', initial='off', session_context=self.context)
        self.capture = ExchangeCapture(self.raw, environment=read_environment(None),
                                       record_imu=False, duration=120, guided=True)
        self.session.raw_recording = self.raw
        self.raw.exchange = self.capture
        self.raw.bind(camera)
        self.source = NativeRGBDSource(None, NS(processing_block=Mock()), 15)
        self.source.to_analysis_frames = lambda pair: pair
        self.capture.native_source = self.source
        self.color = self.source._callback('color')
        self.depth = self.source._callback('depth')
        self.number = 0
        for _ in range(4):
            self.send()
        self.addCleanup(self.cleanup)
        with patch.object(self.source, 'start'):
            self.capture.start(None, None, None)
        self.guide = GuidedControl(self.session, single_round=True)

    def cleanup(self):
        if self.capture.writer is not None:
            try:
                self.capture.stop()
            except RuntimeError:
                pass
        if not self.raw._finished:
            self.raw.finish(termination='q')

    def send(self):
        self.number += 1
        sample = frame(self.number)
        self.color(sample.get_color_frame())
        self.depth(sample.get_depth_frame())

    def observe(self):
        self.send()
        ready, pair = self.capture.analysis_frame()
        self.assertTrue(ready)
        self.assertEqual(pair.get_frame_number(), self.number)
        row = self.session.begin_receive()
        self.session.received(row, True, pair, self.session.clock_ns())
        stamp = pair.get_timestamp()
        self.session.accept(row, result(), self.number, stamp, pose_detected=True, face_detected=True)
        self.raw.observe_measurement(self.session, device_timestamp_ms=stamp)
        self.session.frame_completed(row)
        until(lambda: self.raw.total_frames == self.capture.enqueued)

    def finish(self, reason):
        error = None
        try:
            self.capture.stop()
        except RuntimeError as exc:
            error = exc
        self.raw.finish(termination=reason, error=error)
        return self.capture.publish(error)

    def read(self, relative):
        return json.loads((self.root/relative).read_text(encoding='utf-8'))

    def events(self):
        return [json.loads(line) for line in (self.root/'recording_metadata/events.jsonl').read_text(
            encoding='utf-8').splitlines()]

    def start_hold(self, posture):
        self.assertEqual(self.guide.expected, posture)
        self.guide.choose(0)
        if posture:
            self.assertFalse(self.guide.start())
            self.guide.choose(posture)
        self.assertTrue(self.guide.start())

    def test_preview_writes_nothing_and_pair_crossing_operator_start_is_excluded(self):
        self.assertFalse(self.raw.requested)
        self.assertFalse(self.guide.start())
        self.assertFalse(self.raw.directory.exists())
        self.assertTrue(self.capture.analysis_frame()[0])
        self.assertIsNone(self.capture.analysis_reference)
        sample = frame(5)
        self.color(sample.get_color_frame())
        until(lambda: self.source.pairer.observed['color'] == 2)
        self.raw.set_enabled(True)
        self.depth(sample.get_depth_frame())
        until(lambda: self.capture.preview_pairs == 2)
        self.assertFalse(self.raw.directory.exists())
        self.assertEqual(self.capture.acquired, 0)
        self.number = 5
        self.observe()
        self.assertEqual(self.capture.analysis_reference['sensors']['color']['number'], 6)
        with self.assertRaises(RawRecordingError):
            self.raw.set_enabled(False)
        report = self.finish('q')
        guided = report['guided_capture']
        self.assertEqual((report['session_status'], report['termination'], report['written']),
                         ('INTERRUPTED', 'user_aborted', 1))
        self.assertEqual(guided['preview_pairs_not_recorded'], 2)
        self.assertGreaterEqual(guided['first_saved_pair_earliest_callback_host_ns'], guided['recording_start_host_ns'])
        self.assertEqual(self.events()[guided['recording_start_event_index']-1]['details']['activated_host_ns'],
                         guided['recording_start_host_ns'])
        with self.assertRaises(ValueError):
            RawSessionReader(self.root)

    def test_single_round_cancellation_transition_exact_frame_links_and_normal_finalize(self):
        root = Mock()
        tk = NS(Tk=lambda: root, StringVar=Mock(), Label=Mock(), Button=Mock())
        panel = GuidedPanel(self.session, subject='P02', single_round=True, tk_module=tk)
        self.guide = panel.control
        self.assertTrue(panel.poll())
        panel._toggle_raw()
        self.assertTrue(self.raw.requested)
        panel.raw_button.configure.assert_called_with(text='원본 녹화 중', state='disabled')
        self.start_hold(0)
        self.observe()
        self.guide.cancel()
        self.assertTrue(panel.poll())
        self.assertEqual(self.guide.expected, 0)
        self.observe()  # Still saved during the cancelled hold's transition.
        for posture in range(6):
            self.start_hold(posture)
            for _ in range(152):
                self.observe()
                if self.session.active is None:
                    break
            self.assertEqual(panel.poll(), posture < 5)
            self.assertEqual(self.guide.completed, posture+1)
            if posture < 5:
                self.observe()  # Existing source keeps saving between holds.
        self.assertEqual(self.guide.state, 'DONE')
        self.assertEqual(panel.stop_reason(), 'guided_completed')
        report = self.finish(panel.stop_reason())
        self.assertEqual((report['status'], report['session_status'], report['termination']),
                         ('PASS', 'COMPLETED', 'guided_completed'))
        self.assertEqual((report['acquired'], report['queued'], report['written']),
                         (self.number-4,)*3)
        self.assertEqual(report['checks']['six_instructed_holds'], 'PASS')
        self.assertEqual(report['checks']['guided_protocol'], 'PASS')
        intervals = report['guided_capture']['completed_intervals']
        self.assertEqual([hold['posture_id'] for hold in intervals], [f'P{i}' for i in range(6)])
        self.assertEqual([hold['repetition'] for hold in intervals], [5]*6)
        self.assertTrue(all(10000 <= hold['duration_ms'] < 10100 for hold in intervals))
        self.assertTrue(all(a['end_frame_reference']['frame'] + 1 < b['start_frame_reference']['frame']
                            for a, b in zip(intervals, intervals[1:])))
        events = self.events()
        self.assertEqual(events[-1]['details']['status'], 'PENDING_VERIFICATION')
        self.assertEqual(len([e for e in events if e['event'] == 'POSTURE_HOLD_START']), 7)
        self.assertEqual(len([e for e in events if e['event'] == 'POSTURE_HOLD_END' and
                              e['details']['status'] == 'INCOMPLETE']), 1)
        for event in events:
            self.assertEqual({k: event[k] for k in self.context}, self.context)
        session = RawSessionReader(self.root)
        self.assertEqual({k: session.identity['context'][k] for k in self.context}, self.context)
        packet = next(session.packets())
        np.testing.assert_array_equal(packet.depth_z16, [[0, 65535], [1, 1024]])
        self.assertEqual(packet.depth_z16.dtype, np.uint16)
        inventory = self.read('exchange_files.json')['sha256']
        for filename in ('exchange_verification.json', 'raw_rgbd/clip_0001/frames/00000001.npz'):
            self.assertEqual(inventory[filename], _sha(self.root/filename))
        self.assertEqual(RawClipReader(self.raw.last_clip).end['status'], 'COMPLETED')
        saved = {ref['receive_index']: ref for hold in intervals for ref in
                 (hold['start_frame_reference'], hold['end_frame_reference'])}
        partial = _guided_intervals([event for event in events if event['posture_code'] != 'P5'], saved,
                                    session.identity['context'], report['guided_capture']['recording_start_event_index'],
                                    report['active_start_host_ns'])
        self.assertEqual(len(partial['completed_intervals']), 5)
        self.assertIn('expected_exactly_one_completed_hold_per_posture', partial['issues'])

    def test_space_and_enter_queued_after_p0_do_not_rearm_the_old_target(self):
        root = Mock()
        tk = NS(Tk=lambda: root, StringVar=Mock(), Label=Mock(), Button=Mock())
        panel = GuidedPanel(self.session, subject='P02', single_round=True, tk_module=tk)
        panel._toggle_raw()
        panel.poll()

        def press(key):
            panel._key(NS(keysym=key))
            panel.pressed.discard(key)

        press('space')
        press('Return')
        self.assertTrue(self.session.armed)
        self.session.armed = False
        self.session.segments.append(dict(status='PREDICTED', eligible=True, segment_index=1))
        self.raw.observe_measurement(self.session)

        def queued_keys():
            press('space')
            press('Return')

        root.update.side_effect = queued_keys
        self.assertTrue(panel.poll())
        self.assertEqual(panel.control.expected, 1)
        self.assertTrue(panel.control.normal_ready)
        self.assertFalse(self.session.armed)
        press('H')
        press('Return')
        self.assertTrue(self.session.armed)
        requests = [event['posture_code'] for event in self.events() if event['event'] == 'MEASUREMENT_START']
        self.assertEqual(requests, ['P0', 'P1'])

    def test_focused_buttons_consume_space_before_the_tk_button_class(self):
        root = Mock()
        buttons = []

        def button(_, **kwargs):
            widget = Mock()
            buttons.append((kwargs['text'], widget))
            return widget

        tk = NS(Tk=lambda: root, StringVar=Mock(), Label=Mock(), Button=button)
        panel = GuidedPanel(self.session, subject='P02', single_round=True, tk_module=tk)
        panel._toggle_raw()
        self.assertEqual(len(buttons), 4)
        for label, widget in buttons:
            with self.subTest(button=label):
                sequence, handler = widget.bind.call_args.args
                self.assertEqual(sequence, '<KeyPress-space>')
                self.assertEqual(handler(NS(keysym='space')), 'break')
                self.assertTrue(panel.control.normal_ready)
                self.assertFalse(self.session.armed)
                self.assertTrue(panel.control.running)
                panel.pressed.discard('space')

    def test_claimed_guided_completion_without_six_holds_fails_closed(self):
        self.raw.set_enabled(True)
        self.observe()
        with self.assertRaisesRegex(RuntimeError, 'verification'):
            self.finish('guided_completed')
        report = self.read('exchange_verification.json')
        self.assertEqual(report['session_status'], 'FAILED')
        self.assertEqual(report['checks']['guided_protocol'], 'FAIL')
        self.assertIn('expected_exactly_one_completed_hold_per_posture', report['guided_capture']['issues'])
        with self.assertRaises(ValueError):
            RawClipReader(self.raw.last_clip)

    def test_deadline_during_preview_is_interrupted_without_a_clip(self):
        report = self.finish('duration_elapsed')
        self.assertEqual((report['session_status'], report['termination']), ('INTERRUPTED', 'duration_expired'))
        self.assertEqual(report['written'], 0)
        self.assertFalse(self.raw.directory.exists())

    def test_window_close_is_distinct_from_q_and_completed_guide(self):
        for use_key, expected in ((False, 'panel_closed'), (True, 'user_aborted')):
            with self.subTest(use_key=use_key), patch.object(self.session, 'segments', []):
                root = Mock()
                tk = NS(Tk=lambda: root, StringVar=Mock(), Label=Mock(), Button=Mock())
                panel = GuidedPanel(self.session, subject='P02', single_round=True, tk_module=tk)
                panel.poll()
                if use_key:
                    panel._key(NS(keysym='q'))
                else:
                    root.protocol.call_args.args[1]()
                # An operator close wins even if a last time window was just processed.
                panel.control.completed = 5
                self.session.segments.append(dict(status='PREDICTED', eligible=True))
                self.assertFalse(panel.poll())
                self.assertEqual(panel.stop_reason(), expected)
        report = self.finish('panel_closed')
        self.assertEqual((report['session_status'], report['termination']), ('INTERRUPTED', 'panel_closed'))

    def test_native_acquisition_error_overrides_guided_completion(self):
        self.raw.set_enabled(True)
        self.observe()
        self.number += 2
        self.color(frame(self.number).get_color_frame())
        until(lambda: bool(self.capture.errors))
        report = self.finish('guided_completed')
        self.assertEqual((report['session_status'], report['termination']), ('FAILED', 'acquisition_failed'))

    def test_raw_write_error_overrides_guided_completion(self):
        self.raw.set_enabled(True)
        self.observe()
        with patch.object(self.raw, 'store_packet', side_effect=OSError('synthetic store failure')):
            self.send()
            until(lambda: bool(self.capture.errors))
        report = self.finish('guided_completed')
        self.assertEqual((report['session_status'], report['termination']), ('FAILED', 'write_failed'))
        self.assertEqual(report['unwritten'], 1)


class GuidedLauncherTests(TestCase):
    def test_guided_completion_at_or_after_deadline_is_expiration_in_probe(self):
        import posture_geometry_probe as probe
        from probe_timing import ProbeRunControl
        from test_h9_probe_integration import SyntheticProbe

        for finished_ns, expected in ((299_999_999_999, 'guided_completed'),
                                       (300_000_000_000, 'duration_elapsed'),
                                       (301_000_000_000, 'duration_elapsed')):
            with self.subTest(ns=finished_ns):
                fake = SyntheticProbe(self, [0])
                controller = ProbeRunControl(300, clock_ns=fake.clock)

                def finish_panel():
                    fake.clock.ns = finished_ns
                    return False

                with patch.object(probe.probe_timing, 'ProbeRunControl', return_value=controller):
                    probe.run_probe(duration_seconds=300, ui_poll=finish_panel,
                                    ui_stop_reason=lambda: 'guided_completed')
                self.assertEqual(controller.reason, expected)
                self.assertEqual(controller.stop_ns, finished_ns)
                fake.pipeline.try_wait_for_frames.assert_not_called()

    def test_guided_cli_help_supports_windows_cp949(self):
        import run_research_b as launcher
        with io.TextIOWrapper(io.BytesIO(), encoding='cp949') as stdout:
            with redirect_stdout(stdout), self.assertRaises(SystemExit) as stopped:
                launcher.main(['--help'])
            self.assertEqual(stopped.exception.code, 0)
            stdout.flush()
            self.assertIn(b'--guided-six', stdout.buffer.getvalue())

    def test_bound_probe_passes_guided_stop_reason_to_probe_without_running_camera(self):
        import e0_panel
        with tempfile.TemporaryDirectory() as directory:
            model, scaler = estimators()
            panel = Mock()
            panel.stop_reason.return_value = 'guided_completed'
            fake_capture = Mock(guided=True, errors=[])
            binding = dict(artifact_sha256='a', feature_ids=[], model_sha256='m', scaler_sha256='s')
            with (patch.object(e0_panel, 'load_fs3', return_value=(model, scaler, {})),
                  patch.object(e0_panel, 'environment_record', return_value={}),
                  patch('exchange_capture.ExchangeCapture', return_value=fake_capture)):
                runner = Mock()
                e0_panel.run_bound_probe('artifact', binding, Path(directory)/'run', execution_authorized=True,
                    panel_factory=lambda session: panel, probe_runner=runner, save_raw='off',
                    recording_context=dict(participant_id='P01', session_label='S1', repetition=1),
                    exchange_options=dict(guided=True))
            self.assertEqual(runner.call_args.kwargs['ui_stop_reason'](), 'guided_completed')
            self.assertIs(runner.call_args.kwargs['ui_poll'], panel.poll)
            panel.close.assert_called_once()
            fake_capture.publish.assert_called_once_with(None)

    def test_cli_forwards_single_round_with_exact_session_context_and_technical_stays_on(self):
        import run_research_b as launcher
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = root/'binding.json'
            binding.write_text(json.dumps(dict(path='artifact', artifact_sha256='a', feature_ids=[],
                                              model_sha256='m', scaler_sha256='s')), encoding='utf-8')
            with (patch.object(launcher, 'ROOT', root), patch.object(launcher, 'environment_record'),
                  patch.object(launcher, 'load_fs3', return_value=(None, None, {'artifact_sha256': 'a'})),
                  patch.object(launcher, 'run_bound_probe') as bound):
                args = ['--live', '--exchange-capture', '--binding', str(binding)]
                for subject in ('P01', 'P02'):
                    for repeat in range(1, 6):
                        with self.subTest(subject=subject, repeat=repeat):
                            label = 'S1' if repeat <= 3 else 'S2'
                            self.assertEqual(launcher.main(args+['--guided-six', '--participant-id', subject,
                                '--session-label', label, '--repetition', str(repeat)]), 0)
                            kwargs = bound.call_args.kwargs
                            self.assertEqual(kwargs['save_raw'], 'off')
                            self.assertTrue(kwargs['exchange_options']['guided'])
                            self.assertEqual(kwargs['exchange_options']['duration'], 300)
                            self.assertEqual(kwargs['panel_factory'].keywords, dict(subject=subject, single_round=True))
                            self.assertEqual(kwargs['recording_context'], dict(participant_id=subject,
                                session_label=label, repetition=repeat, identity_status='ASSIGNED'))
                self.assertEqual(launcher.main(args+['--participant-unregistered']), 0)
                kwargs = bound.call_args.kwargs
                self.assertEqual(kwargs['save_raw'], 'on')
                self.assertNotIn('guided', kwargs['exchange_options'])
                self.assertNotIn('panel_factory', kwargs)

    def test_guided_cli_rejects_incompatible_recording_and_repeat_options(self):
        import run_research_b as launcher
        for options in (['--guided-six'],
                        ['--guided-six', '--live', '--exchange-capture', '--participant-unregistered',
                         '--session-label', 'S1'],
                        ['--guided-six', '--live', '--exchange-capture', '--participant-id', 'P01',
                         '--session-label', 'S2', '--repetition', '1'],
                        ['--guided-six', '--live', '--exchange-capture', '--participant-id', 'P02',
                         '--session-label', 'S1', '--repetition', '1', '--save-raw', 'on']):
            with self.subTest(options=options), self.assertRaises(SystemExit):
                launcher.main(options)

    def test_unregistered_guide_uses_a_reserved_output_area_and_no_subject_metadata(self):
        import run_research_b as launcher
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = root/'binding.json'
            binding.write_text(json.dumps(dict(path='artifact', artifact_sha256='a', feature_ids=[],
                                              model_sha256='m', scaler_sha256='s')), encoding='utf-8')
            engineering = root/'analysis/RESEARCH_B/local_private/guided_engineering'
            base = ['--live', '--exchange-capture', '--guided-six', '--binding', str(binding)]
            with (patch.object(launcher, 'ROOT', root), patch.object(launcher, 'environment_record'),
                  patch.object(launcher, 'load_fs3', return_value=(None, None, {'artifact_sha256': 'a'})),
                  patch.object(launcher, 'run_bound_probe') as bound):
                self.assertEqual(launcher.main(base+['--participant-unregistered']), 0)
                self.assertEqual(bound.call_args.args[2].parent, engineering)
                kwargs = bound.call_args.kwargs
                self.assertTrue(kwargs['engineering_test'])
                self.assertEqual(kwargs['save_raw'], 'off')
                self.assertEqual(kwargs['panel_factory'].keywords, dict(subject=None, single_round=True))
                self.assertEqual(kwargs['recording_context'], dict(participant_id=None, session_label=None,
                                                                  repetition=None, identity_status='UNASSIGNED'))
                with self.assertRaises(SystemExit):
                    launcher.main(base+['--participant-unregistered', '--output-dir', str(root/'ordinary')])
                with self.assertRaises(SystemExit):
                    launcher.main(base+['--participant-id', 'P01', '--session-label', 'S1', '--repetition', '1',
                                       '--output-dir', str(engineering/'formal')])
                with self.assertRaises(SystemExit):
                    launcher.main(['--live', '--exchange-capture', '--participant-unregistered',
                                   '--output-dir', str(engineering/'technical')])

    def test_engineering_manifest_and_events_have_explicit_scope_and_unassigned_identity(self):
        import e0_panel
        from raw_rgbd_events import validate_context

        with tempfile.TemporaryDirectory() as directory:
            model, scaler = estimators()
            root = Path(directory)/'run'
            binding = dict(artifact_sha256='a', feature_ids=[], model_sha256='m', scaler_sha256='s')
            context = validate_context()
            window = Mock()
            tk = NS(Tk=lambda: window, StringVar=Mock(), Label=Mock(), Button=Mock())

            def simulate(**kwargs):
                raw = kwargs['raw_recording']
                raw.begin_session()
                raw.finish(termination='panel_closed')

            with (patch.object(e0_panel, 'load_fs3', return_value=(model, scaler, {})),
                  patch.object(e0_panel, 'environment_record', return_value={})):
                session = e0_panel.run_bound_probe('artifact', binding, root, execution_authorized=True,
                    panel_factory=lambda session: GuidedPanel(session, subject=None, tk_module=tk, single_round=True),
                    probe_runner=simulate, save_raw='off', recording_context=context, engineering_test=True,
                    exchange_options=dict(guided=True, environment={}, record_imu=False, duration=300))
            self.assertTrue(session.environment_metadata['guided_engineering_test'])
            self.assertIn('참가자 미등록', window.title.call_args.args[0])
            manifest = json.loads((root/'recording_metadata/session_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['context'], context)
            self.assertEqual(manifest['scope'], 'NON_FORMAL_GUIDED_ENGINEERING_TEST')
            events = (root/'recording_metadata/events.jsonl').read_text(encoding='utf-8').splitlines()
            for event in map(json.loads, events):
                self.assertEqual({k: event[k] for k in context}, context)
                self.assertEqual(event['scope'], manifest['scope'])
