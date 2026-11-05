"""Synthetic SDK, clocks, geometry and hand-built RF leaves only; never D455."""
from contextlib import contextmanager, ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import performance_output as perf
import posture_geometry_probe as probe
from probe_diagnostics import ProbeDiagnostics
from probe_timing import ProbeMetrics
import stage5e_bundle_c as bundle
from test_h9_probe_integration import SyntheticProbe
from test_h9_time_window import leaf_fixture_document
from test_performance_output import synthetic_example


class BundleCTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))

    @contextmanager
    def sdk(self, events, *, keys=None):
        with ExitStack() as stack:
            fake=SyntheticProbe(NS(enterContext=stack.enter_context), events, keys=keys)
            model=self.root/'SYNTHETIC-pin.bin'
            if not model.exists(): model.write_bytes(b'SYNTHETIC_NO_MODEL')
            sys.modules['analyze_d455'].ensure_models=lambda:dict(pose=model,mesh=model,face=model)
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            yield fake

    def test_high_resolution_is_separate_and_legacy_fractional_units_preserved(self):
        clock=NS(ns=0)
        diag=ProbeDiagnostics(self.root/'diag',clock_ns=lambda:clock.ns)
        metrics=ProbeMetrics(self.root/'timing.json',clock_ns=lambda:0,diagnostics=diag)
        with metrics.stage('synthetic.tiny',1): clock.ns+=12345
        metrics.record_ns('synthetic.explicit_ns',98765,1)
        report=metrics.finish()
        diag.finish(status='COMPLETED')
        document=json.loads((self.root/'diag/diagnostics.json').read_text())
        self.assertEqual(report['stage_milliseconds']['synthetic.tiny']['p50'],0.)
        self.assertEqual(report['stage_milliseconds']['synthetic.explicit_ns']['p50'],.098765)
        self.assertEqual(document['raw'][0]['duration_ns'],12345)
        self.assertEqual(document['stage_milliseconds'][0]['p50'],.012345)
        self.assertNotIn('diagnostics',report)

    def test_diagnostic_endpoints_and_warmup_keep_clock_domains_separate(self):
        clock=NS(ns=100)
        diag=ProbeDiagnostics(self.root/'diag',clock_ns=lambda:clock.ns)
        metrics=ProbeMetrics(self.root/'timing.json',clock_ns=lambda:0,diagnostics=diag,warmup_frames=1)
        token=metrics.input_received(1)
        clock.ns+=1000; metrics.ui_submitted(token,1)
        clock.ns+=2000; metrics.frame_completed(token,1)
        skipped=metrics.input_received(2); metrics.skip_at_deadline(skipped)
        invalid=metrics.input_received(3); metrics.invalid_pair(invalid)
        metrics.finish(); diag.finish(status='COMPLETED')
        self.assertEqual([r['duration_ns'] for r in diag.rows],[1000,3000])
        self.assertTrue(all(r['phase']=='warmup' for r in diag.rows))
        self.assertEqual(diag._inputs,{})

    def test_views_none_keeps_ui_and_explicit_headless_removes_only_ui(self):
        outputs=[]
        for enabled in (False,True):
            with self.sdk([0,100,200,300],keys=[-1]*4) as fake:
                path=self.root/f'timing-{enabled}.json'
                probe.run_probe(headless=enabled,duration_seconds=.3,show_3d_views='none',
                    timing_output_path=str(path),frame_callback=fake.callbacks.append,
                    f1_live=True,rf_demo_model_path='SYNTHETIC-F1')
                report=json.loads(path.read_text())
                self.assertEqual(report['termination']['reason'],'duration_elapsed')
                self.assertEqual(fake.calculate.call_count,3)
                self.assertEqual(fake.pose.detect_for_video.call_count,3)
                self.assertEqual(fake.face.detect_for_video.call_count,3)
                self.assertTrue(all(f.result is fake.geometry and f.rf_demo is fake.f1_prediction for f in fake.callbacks))
                outputs.append(report['counts'])
                if enabled:
                    fake.cv.imshow.assert_not_called(); fake.cv.waitKey.assert_not_called()
                    fake.cv.destroyAllWindows.assert_not_called()
                    probe.draw_engineering_panel.assert_not_called()
                    probe.geometry.draw_geometry_overlay.assert_not_called()
                    self.assertNotIn('ui.key_wait',report['stage_milliseconds'])
                    self.assertNotIn('latency.host_receive_to_ui_submit',report['stage_milliseconds'])
                else:
                    self.assertEqual(fake.cv.imshow.call_count,3)
                    self.assertEqual(fake.cv.waitKey.call_count,3)
        self.assertEqual(outputs[0],outputs[1])

    def test_headless_h9_preserves_predictions_features_and_timer(self):
        model=self.root/'SYNTHETIC-h9.json'; perf._write_json(model,leaf_fixture_document())
        records=[]
        for enabled in (False,True):
            with self.sdk(list(range(0,4200,100)),keys=[-1]*42) as fake:
                probe.run_probe(headless=enabled,duration_seconds=4.1,h9_model_path=str(model),
                    timing_output_path=str(self.root/f'h9-{enabled}.json'))
                session=fake.sessions[0]
                records.append((dict(session.events),session.runtime.engine.rf_calls,
                                session.runtime.snapshot()['display_prediction']))
                self.assertFalse(session.runner._thread.is_alive())
                if enabled:
                    fake.cv.imshow.assert_not_called(); fake.cv.waitKey.assert_not_called()
        self.assertEqual(records[0],records[1])
        self.assertEqual(records[1][1],1)

    def test_ui_diagnostics_split_build_imshow_and_key_wait(self):
        with self.sdk([0,100,200],keys=[-1]*3):
            probe.run_probe(duration_seconds=.2,timing_output_path=str(self.root/'timing.json'),
                diagnostics_output_dir=str(self.root/'diag'),timing_warmup_frames=1)
        document=json.loads((self.root/'diag/diagnostics.json').read_text())
        self.assertEqual(document['status'],'COMPLETED')
        names={r['name'] for r in document['raw']}
        self.assertTrue({'ui.image_build','ui.imshow','ui.key_wait','frame.processing'}<=names)
        self.assertEqual([r['phase'] for r in document['raw'] if r['name']=='ui.image_build'],['warmup','steady'])

    def test_headless_diagnostics_do_not_fabricate_ui_latency(self):
        with self.sdk([0,100,200]):
            probe.run_probe(headless=True,duration_seconds=.2,timing_output_path=str(self.root/'timing.json'),
                diagnostics_output_dir=str(self.root/'diag'))
        document=json.loads((self.root/'diag/diagnostics.json').read_text())
        self.assertEqual(document['ui_latency_status'],'NOT_MEASURED')
        self.assertFalse(any('ui' in r['name'] for r in document['raw']))
        self.assertEqual(document['pending_inputs'],0)

    def test_headless_timeouts_and_invalid_pairs_keep_duration_exit(self):
        for invalid in (False,True):
            with self.sdk([0,None] if not invalid else [0,100,200]) as fake:
                if invalid:
                    fake.pipeline.try_wait_for_frames.side_effect=lambda _: (True,NS(get_timestamp=lambda:0,
                        get_frame_number=lambda:1,get_color_frame=lambda:None,get_depth_frame=lambda:None))
                    clock=NS(n=0)
                    def receive(_):
                        clock.n+=1; fake.clock.set_ms(clock.n*100)
                        return True,NS(get_timestamp=lambda:0,get_frame_number=lambda:clock.n,
                            get_color_frame=lambda:None,get_depth_frame=lambda:None)
                    fake.pipeline.try_wait_for_frames.side_effect=receive
                path=self.root/f'invalid-{invalid}.json'
                probe.run_probe(headless=True,duration_seconds=.2,timing_output_path=str(path))
                report=json.loads(path.read_text())
                self.assertEqual(report['termination']['reason'],'duration_elapsed')
                fake.cv.waitKey.assert_not_called()

    def test_runtime_error_and_keyboard_interrupt_keep_journal_and_status(self):
        for index, error in enumerate((RuntimeError('synthetic failure'),KeyboardInterrupt())):
            with self.sdk([0,100]) as fake:
                fake.calculate.side_effect=error
                directory=self.root/f'perf-{index}'
                with self.assertRaises(type(error)):
                    probe.run_probe(headless=True,duration_seconds=.2,performance_output_dir=str(directory),
                                    diagnostics_output_dir=str(self.root/f'diag-{index}'))
                doc=json.loads((directory/'performance.json').read_text())
                rows=[json.loads(l) for l in (directory/'events.jsonl').read_text().splitlines()]
                self.assertEqual(rows,doc['events'])
                self.assertEqual(doc['run_status'],'INTERRUPTED' if index else 'FAILED')
                diagnostic=json.loads((self.root/f'diag-{index}/diagnostics.json').read_text())
                self.assertEqual(diagnostic['status'],doc['run_status'])
                self.assertEqual(diagnostic['pending_inputs'],1)
                fake.pipeline.stop.assert_called_once()

    def test_opt_in_options_and_collisions_fail_before_hardware(self):
        with redirect_stderr(io.StringIO()):
            for args in (['--headless'],['--headless','--duration-seconds','1','--views','all'],
                         ['--engineering-diagnostics-dir','unused']):
                with self.assertRaises(SystemExit): probe.parse_args(args)
        with self.assertRaises(ValueError): probe.run_probe(headless=True)
        with self.assertRaises(FileExistsError):
            probe.run_probe(duration_seconds=1,timing_output_path=str(self.root/'timing.json'),
                            diagnostics_output_dir=str(self.root))
        with self.assertRaises(ValueError):
            probe.run_probe(duration_seconds=1,performance_output_dir=str(self.root/'same'),
                            diagnostics_output_dir=str(self.root/'same'))
        self.assertFalse((self.root/'same').exists())

    def test_default_config_and_no_diagnostic_sidecar_remain_legacy(self):
        with self.sdk([0]) as fake:
            probe.run_probe(performance_output_dir=str(self.root/'perf'))
        doc=json.loads((self.root/'perf/performance.json').read_text())
        self.assertNotIn('headless',doc['config'])
        self.assertNotIn('engineering_diagnostics_enabled',doc['config'])
        self.assertNotIn('headless',doc['timing']['metadata'])
        self.assertEqual(fake.cv.imshow.call_count,1)

    def test_raw_to_csv_baseline_validation_detects_tampering(self):
        synthetic_example(self.root/'run')
        result=bundle.analyze_run(self.root/'run')
        self.assertTrue(all(result['checks'].values()))
        path=self.root/'run/performance_runs.csv'
        path.write_text(path.read_text().replace('frameset_fps','tampered_fps'))
        self.assertFalse(bundle.analyze_run(self.root/'run')['checks']['performance_runs.csv'])

    def test_diagnostic_publication_collision_and_exception_leave_manifest(self):
        diag=ProbeDiagnostics(self.root/'diag')
        with self.assertRaisesRegex(RuntimeError,'synthetic'):
            with diag.stage('synthetic'):
                raise RuntimeError('synthetic')
        self.assertEqual(len(diag.rows),1)
        path=self.root/'diag/diagnostics.json'; path.write_text('existing')
        with self.assertRaises(FileExistsError): diag.finish(status='FAILED')
        self.assertEqual(path.read_text(),'existing')
        self.assertTrue((self.root/'diag/manifest.json').is_file())

    def test_difference_units_and_zero_baseline(self):
        self.assertEqual(bundle.differences(20.,18.),dict(before=20.,after=18.,absolute_difference=-2.,relative_change_percent=-10.))
        self.assertIsNone(bundle.differences(0.,1.)['relative_change_percent'])

    def test_performance_still_flushes_every_event_and_preserves_failure_evidence(self):
        from unittest.mock import Mock
        recorder=perf.PerformanceRecorder(self.root/'perf',config={'fixture':'SYNTHETIC'},data_id='SYNTHETIC')
        recorder._journal=Mock(wraps=recorder._journal)
        recorder.event('synthetic', index=1); recorder.event('synthetic', index=2)
        self.assertEqual(recorder._journal.flush.call_count,2)
        metrics=ProbeMetrics(self.root/'timing.json',performance=recorder)
        metrics.finish(error=RuntimeError('synthetic_failure'))
        doc=json.loads((self.root/'perf/performance.json').read_text())
        self.assertEqual(doc['run_status'],'FAILED')
        self.assertEqual(doc['events'],[json.loads(l) for l in (self.root/'perf/events.jsonl').read_text().splitlines()])

    def test_setup_and_timing_publication_errors_mark_diagnostics_failed(self):
        with patch.object(probe.probe_timing,'ProbeMetrics',side_effect=RuntimeError('synthetic_setup')):
            with self.assertRaisesRegex(RuntimeError,'synthetic_setup'):
                probe.run_probe(timing_output_path=str(self.root/'timing.json'),diagnostics_output_dir=str(self.root/'setup'))
        self.assertEqual(json.loads((self.root/'setup/diagnostics.json').read_text())['status'],'FAILED')
        with self.sdk([0,100],keys=[-1,-1]) as fake:
            path=self.root/'collided.json'
            def callback(frame): path.write_text('existing')
            with self.assertRaisesRegex(RuntimeError,'cleanup failed'):
                probe.run_probe(headless=True,duration_seconds=.1,timing_output_path=str(path),
                    diagnostics_output_dir=str(self.root/'publication'),frame_callback=callback)
            self.assertEqual(path.read_text(),'existing')
            self.assertEqual(json.loads((self.root/'publication/diagnostics.json').read_text())['status'],'FAILED')
