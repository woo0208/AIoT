"""Synthetic SDK integration only. All camera/MediaPipe/UI entry points are fakes."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np

import h9_async_runtime as host
import h9_m0 as m0
import h9_probe_session as session
import posture_geometry as geometry
import posture_geometry_probe as probe
import probe_timing
import rf_experiment as rf
from test_h9_async_runtime import result
from test_h9_time_window import leaf_fixture_document


def module(name, **values):
    obj=ModuleType(name);obj.__dict__.update(values);return obj


class SyntheticProbe:
    """A virtual host clock and completed RGB-D frames, never an SDK device."""
    def __init__(self,case,events,keys=None,*,f1=False):
        self.clock=host.VirtualMonotonicClock()
        self.events=iter(events);self.sessions=[];self.panels=[];self.callbacks=[]
        self.keys=iter(keys or [-1]*(len(events)-1)+[ord('q')])
        self.pose=NS(detect_for_video=Mock(return_value=NS(pose_landmarks=[])),close=Mock())
        self.face=NS(detect_for_video=Mock(return_value=NS(face_landmarks=[])),close=Mock())
        self.detector=NS(detect=Mock(return_value='face bbox'),close=Mock())
        self.geometry=result();self.f1=object();self.f1_prediction=object()
        self.pipeline=NS(start=Mock(return_value=NS(
            get_device=lambda:NS(first_depth_sensor=lambda:NS(get_depth_scale=lambda:.001)),
            get_stream=lambda _:NS(as_video_stream_profile=lambda:NS(get_intrinsics=lambda:NS(fx=500))))),
            stop=Mock(),wait_for_frames=Mock(side_effect=self.wait),try_wait_for_frames=Mock(side_effect=self.try_wait))
        cv=module('cv2',COLOR_BGR2RGB=1,cvtColor=lambda image,_:image,imshow=Mock(),
                  waitKey=Mock(side_effect=lambda _:next(self.keys)),destroyAllWindows=Mock())
        self.cv=cv
        vision=module('mediapipe.tasks.python.vision',RunningMode=NS(VIDEO='VIDEO'),
            PoseLandmarkerOptions=lambda **k:k,FaceLandmarkerOptions=lambda **k:k,FaceDetectorOptions=lambda **k:k,
            PoseLandmarker=NS(create_from_options=Mock(return_value=self.pose)),
            FaceLandmarker=NS(create_from_options=Mock(return_value=self.face)),
            FaceDetector=NS(create_from_options=Mock(return_value=self.detector)))
        mpt=module('mediapipe.tasks.python',BaseOptions=lambda **k:k,vision=vision)
        tasks=module('mediapipe.tasks',python=mpt)
        modules={'cv2':cv,'mediapipe':module('mediapipe',tasks=tasks,Image=lambda **k:k,ImageFormat=NS(SRGB=1)),
            'mediapipe.tasks':tasks,'mediapipe.tasks.python':mpt,'mediapipe.tasks.python.vision':vision,
            'pyrealsense2':module('pyrealsense2',pipeline=Mock(return_value=self.pipeline),stream=NS(color=1),
                                 align=lambda _:NS(process=lambda frames:frames)),
            'capture_d455':module('capture_d455',make_config=lambda:'synthetic config'),
            'analyze_d455':module('analyze_d455',ensure_models=lambda:dict(pose='fake',mesh='fake',face='fake'),
                POSE_NUM_POSES=1,FACE_NUM_FACES=1,FACE_MIN_DETECTION_CONFIDENCE=.5)}
        case.enterContext(patch.dict(sys.modules,modules))
        for obj,name,value in (
            (geometry,'points_from_pose_landmarks',{}),(geometry,'points_from_face_landmarks',{}),
            (geometry,'sample_hipless_chest_roi',None),(probe,'deproject_body_points',{}),
            (probe,'deproject_geometry_point',None),(probe,'first_face_transformation_matrix',None),
            (probe,'_face_matrix_csv_values',{}),(geometry,'compute_candidate_geometry',self.geometry),
            (geometry,'draw_geometry_overlay',np.zeros((2,2,3))),
            (probe,'draw_engineering_panel',np.zeros((2,2,3))),
            (probe,'compute_live_f1',self.f1),(probe,'rf_demo_frame',self.f1_prediction),
            (probe,'load_rf_demo_model',NS(status='VALID',artifact_name='fake-f1',detail='synthetic'))):
            mocked=case.enterContext(patch.object(obj,name,return_value=value))
            if name=='compute_candidate_geometry':self.calculate=mocked
        def panel(snapshot):
            self.panels.append(snapshot)
            return np.zeros((2,2,3))
        case.enterContext(patch.object(session,'draw_panel',side_effect=panel))
        real_session=session.H9ProbeSession
        def make_session(*args,**kw):
            created=real_session(*args,**kw);self.sessions.append(created);return created
        case.enterContext(patch.object(session,'H9ProbeSession',side_effect=make_session))
        real_metrics=probe_timing.ProbeMetrics
        def make_metrics(*args,**kw):
            return real_metrics(*args,**kw,clock_ns=self.clock,cpu_clock_ns=lambda:0,
                    memory_reader=lambda:dict(rss_bytes=1024,private_bytes=512,os_peak_rss_bytes=1024))
        case.enterContext(patch.object(probe_timing,'ProbeMetrics',side_effect=make_metrics))

    def next_event(self):
        event=next(self.events)
        if event is None:
            self.clock.set_ms(self.clock.ns//1_000_000+2500)
        else:
            self.clock.set_ms(event)
        # Deterministic dispatch of the independent timer on the virtual clock.
        # The real runner is also started/stopped; no wall-clock perf is inferred.
        if self.sessions:self.sessions[0].runtime.tick()
        if event is None:return None
        color=NS(get_data=lambda:np.zeros((2,2,3),dtype=np.uint8))
        depth=NS(get_data=lambda:np.ones((2,2),dtype=np.uint16))
        return NS(get_timestamp=lambda:900000.+event,get_frame_number=lambda:event//100+1,
                  get_color_frame=lambda:color,get_depth_frame=lambda:depth)

    def wait(self):
        frame=self.next_event()
        assert frame is not None
        return frame

    def try_wait(self,timeout):
        assert timeout==250
        frame=self.next_event();return frame is not None,frame


class H9ProbeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.document=leaf_fixture_document()

    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.model_path=self.root/'synthetic_model.json'
        m0._write_new(self.model_path,self.document)
        self.output=self.root/'timing.json'
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(redirect_stderr(io.StringIO()))
        self.enterContext(patch.object(rf.Forest,'fit',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(rf,'fit_models',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(m0.offline,'evaluate_samples',side_effect=AssertionError('no accuracy')))

    def run_synthetic(self,fake,**kwargs):
        probe.run_probe(h9_model_path=str(self.model_path),timing_output_path=str(self.output),
                        frame_callback=fake.callbacks.append,**kwargs)
        return json.loads(self.output.read_text(encoding='utf-8'))

    def assert_closed(self,fake):
        fake.pose.close.assert_called_once();fake.face.close.assert_called_once()
        fake.pipeline.stop.assert_called_once();fake.cv.destroyAllWindows.assert_called_once()
        for s in fake.sessions:
            if s.runner._thread is not None:self.assertFalse(s.runner._thread.is_alive())
            if s.metrics is not None:self.assertFalse(s.metrics._thread.is_alive())

    def test_geometry_reused_f1_separated_all_stages_and_stale_on_no_input(self):
        events=list(range(0,4100,100))+[None]
        fake=SyntheticProbe(self,events)
        report=self.run_synthetic(fake,f1_live=True,rf_demo_model_path='synthetic-f1')
        self.assert_closed(fake)
        self.assertEqual(fake.pose.detect_for_video.call_count,41)
        self.assertEqual(fake.face.detect_for_video.call_count,41)
        self.assertEqual(fake.detector.detect.call_count,41)
        self.assertEqual(fake.calculate.call_count,41)
        self.assertTrue(all(f.result is fake.geometry and f.rf_demo is fake.f1_prediction for f in fake.callbacks))
        states={p['status'] for p in fake.panels}
        self.assertTrue({'COLLECTING','HOLDING','STALE'}<=states)
        self.assertEqual(report['metadata']['h9_runtime']['status_events']['PREDICTED'],1)
        self.assertEqual(report['metadata']['h9_runtime']['rf_calls'],1)
        self.assertIsNone(fake.panels[-1]['display_prediction'])
        stages=report['stage_milliseconds']
        for stage in ('receive.wait','receive.align','input.convert','mediapipe.pose','mediapipe.face',
                      'depth_geometry','h9.dispatch','ui.render_submit',
                      'io.callback','ui.key_wait','f1.face_detector','f1.compute','f1_demo.rf',
                      'frame.processing','latency.host_receive_to_ui_submit',
                      'h9.prediction_tick_to_ui_submit','h9.latest_window_input_to_ui_submit'):
            self.assertGreater(stages[stage]['count'],0,stage)
        self.assertEqual(report['warmup_stage_milliseconds']['h9.m0_infer']['count'],1)
        self.assertGreater(report['collection_stage_milliseconds']['h9.aggregate']['count'],0)
        self.assertGreater(report['warmup_stage_milliseconds']['h9.aggregate']['count'],0)
        self.assertNotIn('h9.m0_infer',stages)
        self.assertEqual(stages['h9.prediction_tick_to_ui_submit']['count'],1)
        self.assertIsNotNone(report['h9_first_prediction'])
        self.assertIsNotNone(report['h9_first_ui_submission'])
        self.assertEqual(report['counts']['input_framesets'],41)
        self.assertEqual(report['counts']['processed_frames'],41)
        self.assertEqual(report['counts']['receive_timeouts'],1)
        self.assertEqual({c.args[0] for c in fake.cv.imshow.call_args_list},{probe.WINDOW_NAME,session.WINDOW_NAME})
        fake.pipeline.wait_for_frames.assert_not_called()

    def test_manual_reset_clears_prediction_and_recollects(self):
        events=list(range(0,4100,100))+[4100]
        fake=SyntheticProbe(self,events,keys=[-1]*40+[ord('r'),ord('q')])
        report=self.run_synthetic(fake)
        self.assertEqual(fake.panels[-1]['status'],'COLLECTING')
        self.assertIsNone(fake.panels[-1]['display_prediction'])
        self.assertEqual(report['metadata']['h9_runtime']['rf_calls'],1)
        self.assert_closed(fake)

    def test_insufficient_data_never_calls_rf(self):
        fake=SyntheticProbe(self,list(range(0,4100,100)))
        fake.geometry=result((m0.FEATURE_ORDER[0],))
        fake.calculate.return_value=fake.geometry
        report=self.run_synthetic(fake)
        self.assertEqual(fake.panels[-1]['status'],'INSUFFICIENT_DATA')
        self.assertNotIn('h9.m0_infer',report['stage_milliseconds'])
        self.assertEqual(report['metadata']['h9_runtime']['rf_calls'],0)
        self.assert_closed(fake)

    def test_default_probe_uses_legacy_wait_and_only_existing_window(self):
        fake=SyntheticProbe(self,[0])
        probe.run_probe(frame_callback=fake.callbacks.append)
        fake.pipeline.wait_for_frames.assert_called_once()
        fake.pipeline.try_wait_for_frames.assert_not_called()
        self.assertEqual(len(fake.sessions),0)
        self.assertEqual([c.args[0] for c in fake.cv.imshow.call_args_list],[probe.WINDOW_NAME])
        self.assertFalse(self.output.exists())
        self.assert_closed(fake)

    def test_h9_without_metrics_and_metrics_without_h9_are_independent(self):
        fake=SyntheticProbe(self,[0])
        probe.run_probe(h9_model_path=str(self.model_path))
        self.assertIsNone(fake.sessions[0].metrics)
        self.assertFalse(self.output.exists())
        self.assert_closed(fake)

    def test_metrics_only_preserves_legacy_wait(self):
        fake=SyntheticProbe(self,[0])
        probe.run_probe(timing_output_path=str(self.output))
        report=json.loads(self.output.read_text())
        self.assertFalse(report['metadata']['h9_enabled'])
        self.assertEqual(report['counts']['processed_frames'],1)
        fake.pipeline.try_wait_for_frames.assert_not_called()
        self.assert_closed(fake)

    def test_missing_rgbd_pairs_keep_stale_ui_and_quit_responsive(self):
        fake=SyntheticProbe(self,[0,100,3000])
        original=fake.try_wait
        def invalid(timeout):
            ready,frames=original(timeout)
            if fake.clock.ns>0:frames.get_depth_frame=lambda:None
            return ready,frames
        fake.pipeline.try_wait_for_frames.side_effect=invalid
        report=self.run_synthetic(fake)
        self.assertEqual(fake.panels[-1]['status'],'STALE')
        self.assertEqual(report['counts']['missing_color_or_depth'],2)
        self.assertEqual(report['counts']['processed_frames'],1)
        self.assertEqual(report['unfinished_processing_frames'],0)
        self.assert_closed(fake)

    def test_optional_io_timing_and_explicit_csv_label_boundaries(self):
        fake=SyntheticProbe(self,[0,100,200],keys=[ord('1'),ord('t'),ord('q')])
        handles=[Mock(),Mock(),Mock()]
        writers=[Mock(),Mock(),Mock()]
        for name,handle,writer in zip(('_open_csv','_open_upper13_csv','_open_face_diagnostic_csv'),handles,writers):
            self.enterContext(patch.object(probe,name,return_value=(handle,writer)))
        for name,value in (('upper13_csv_rows',[]),('exploratory_csv_row',{}),('face_pipeline_diagnostic_row',{})):
            self.enterContext(patch.object(probe,name,return_value=value))
        report=self.run_synthetic(fake,csv_path=str(self.root/'new.csv'),subject='synthetic',recording_id='dev',
            upper13_csv_path=str(self.root/'new-upper.csv'),face_diag_csv_path=str(self.root/'new-face.csv'))
        self.assertEqual(fake.sessions[0].runtime.engine._last_input.source_label,'TRANSITION')
        self.assertIsNone(fake.sessions[0].runtime.engine._last_input.features)
        self.assertEqual(fake.sessions[0].runtime.engine.rf_calls,0)
        for name in ('io.csv','io.face_diag','io.upper13'):
            self.assertEqual(report['stage_milliseconds'][name]['count'],3)
        for handle in handles:handle.close.assert_called_once()
        self.assert_closed(fake)

    def test_callback_failure_keeps_original_error_and_closes_everything(self):
        fake=SyntheticProbe(self,[0])
        fake.callbacks=NS(append=Mock(side_effect=ValueError('synthetic callback failure')))
        fake.pose.close.side_effect=OSError('synthetic close failure')
        with self.assertRaisesRegex(ValueError,'synthetic callback failure'):self.run_synthetic(fake)
        self.assert_closed(fake)
        report=json.loads(self.output.read_text())
        self.assertEqual(report['error'],'synthetic callback failure')
        self.assertEqual(report['cleanup_errors'],['synthetic close failure'])
        self.assertEqual(report['termination']['reason'],'error')
        self.assertFalse(report['baseline_interpretation']['eligible'])

    def test_timer_worker_failure_is_propagated_and_closed(self):
        fake=SyntheticProbe(self,[0])
        original=fake.try_wait
        def broken(timeout):
            answer=original(timeout)
            fake.sessions[0].runner.error=RuntimeError('synthetic timer worker failure')
            return answer
        fake.pipeline.try_wait_for_frames.side_effect=broken
        with self.assertRaisesRegex(RuntimeError,'independent timer failed'):self.run_synthetic(fake)
        self.assert_closed(fake)
        report=json.loads(self.output.read_text())
        self.assertIn('synthetic timer worker failure',report['metadata']['h9_runtime']['timer_error'])
        self.assertIn('timer thread failed',report['cleanup_errors'])

    def test_timer_start_failure_and_stop_failure_cannot_skip_sdk_cleanup(self):
        fake=SyntheticProbe(self,[0])
        with patch.object(host.H9TimerRunner,'start',side_effect=RuntimeError('synthetic start failure')):
            with self.assertRaisesRegex(RuntimeError,'synthetic start failure'):self.run_synthetic(fake)
        self.assert_closed(fake)

    def test_stop_failure_reported_after_other_cleanup(self):
        fake=SyntheticProbe(self,[0])
        real_stop=host.H9TimerRunner.stop
        def fail_after_stop(runner):
            real_stop(runner);raise OSError('synthetic timer stop failure')
        with patch.object(host.H9TimerRunner,'stop',fail_after_stop):
            with self.assertRaisesRegex(RuntimeError,'probe cleanup failed'):self.run_synthetic(fake)
        self.assert_closed(fake)
        self.assertEqual(json.loads(self.output.read_text())['cleanup_errors'],['synthetic timer stop failure'])

    def test_actual_timer_thread_exception_stops_worker_and_reaches_health_check(self):
        s=session.H9ProbeSession(self.model_path)
        s.runner=host.H9TimerRunner(s.runtime,poll_seconds=.005)
        original=s.runtime.tick
        count=0
        def failing_tick():
            nonlocal count
            count+=1
            if count>1:raise ValueError('synthetic asynchronous tick exception')
            return original()
        with patch.object(s.runtime,'tick',side_effect=failing_tick):
            try:
                s.start()
                s.runner._thread.join(1.)
                self.assertFalse(s.runner._thread.is_alive())
                with self.assertRaisesRegex(RuntimeError,'independent timer failed'):s.check_health()
                with self.assertRaisesRegex(RuntimeError,'timer thread failed'):s.stop()
                self.assertEqual(str(s.runner.error),'synthetic asynchronous tick exception')
            finally:
                if s.runner._thread is not None and s.runner._thread.is_alive():
                    s.runner._stop.set();s.runner._thread.join(1.)

    def test_cli_forwarding_and_fail_before_hardware(self):
        with patch.object(probe,'run_probe') as run:
            self.assertEqual(probe.main(['--h9-model','dev.json','--h9-recording-id','dev',
                '--h9-subject','unknown','--timing-output','new.json','--timing-warmup-frames','30',
                '--timing-h9-warmup-calls','5','--duration-seconds','90']),0)
            self.assertEqual(run.call_args.kwargs['h9_model_path'],'dev.json')
            self.assertEqual(run.call_args.kwargs['timing_warmup_frames'],30)
            self.assertEqual(run.call_args.kwargs['timing_h9_warmup_calls'],5)
            self.assertEqual(run.call_args.kwargs['duration_seconds'],90.)
        for args in (['--h9-subject','x'],['--timing-warmup-frames','1'],
                     ['--timing-h9-warmup-calls','2'],['--timing-output','new.json','--timing-h9-warmup-calls','-1'],
                     ['--duration-seconds','0'],['--duration-seconds','nan'],['--duration-seconds','inf']):
            with self.assertRaises(SystemExit):probe.parse_args(args)
        self.output.write_text('original')
        with self.assertRaises(FileExistsError):
            probe.run_probe(h9_model_path='missing',timing_output_path=str(self.output))
        self.assertEqual(self.output.read_text(),'original')
        with self.assertRaises(FileNotFoundError):probe.run_probe(h9_model_path='does-not-exist.json')

    def test_panel_includes_all_runtime_states_without_new_predictions(self):
        for state in ('COLLECTING','PREDICTED','HOLDING','INSUFFICIENT_DATA','STALE'):
            lines=session.panel_lines(dict(status=state,reasons=['synthetic'],display_prediction=None))
            self.assertIn(state,lines[1]);self.assertIn('DEVELOPMENT',lines[0])

    def timed_baseline(self,fake):
        # Actual predictions use the unchanged synthetic 500-leaf RF fixture.
        # No frame_callback: the fixed baseline excludes external I/O paths.
        probe.run_probe(h9_model_path=str(self.model_path),timing_output_path=str(self.output),
            duration_seconds=90,timing_warmup_frames=150,timing_h9_warmup_calls=5)
        return json.loads(self.output.read_text())

    def test_90_second_virtual_deadline_exits_normally_with_real_fixture_inferences(self):
        fake=SyntheticProbe(self,list(range(0,90100,100)))
        report=self.timed_baseline(fake)
        self.assert_closed(fake)
        self.assertEqual(report['termination']['reason'],'duration_elapsed')
        self.assertEqual(report['termination']['actual_run_seconds'],90.)
        self.assertEqual(report['termination']['requested_duration_seconds'],90)
        self.assertGreaterEqual(report['h9_inferences']['post_warmup'],60)
        self.assertEqual(report['h9_inferences']['total_successful'],report['metadata']['h9_runtime']['rf_calls'])
        self.assertTrue(report['baseline_interpretation']['eligible'])
        self.assertEqual(report['counts']['duration_boundary_frames_skipped'],1)
        self.assertEqual(report['unfinished_processing_frames'],0)
        self.assertIsNotNone(report['baseline_stage_milliseconds'])

    def test_90_second_run_with_insufficient_data_preserves_raw_metrics(self):
        fake=SyntheticProbe(self,list(range(0,90100,100)))
        fake.calculate.return_value=result((m0.FEATURE_ORDER[0],))
        report=self.timed_baseline(fake)
        self.assert_closed(fake)
        self.assertEqual(report['termination']['reason'],'duration_elapsed')
        self.assertEqual(report['h9_inferences']['post_warmup'],0)
        self.assertFalse(report['baseline_interpretation']['eligible'])
        self.assertIn('insufficient_post_warmup_m0_inferences',report['baseline_interpretation']['reasons'])
        self.assertIsNone(report['baseline_stage_milliseconds'])
        self.assertGreater(report['stage_milliseconds']['depth_geometry']['count'],0)

    def test_q_early_exit_blocks_even_after_60_real_fixture_inferences(self):
        fake=SyntheticProbe(self,list(range(0,70100,100)))
        report=self.timed_baseline(fake)
        self.assert_closed(fake)
        self.assertEqual(report['termination']['reason'],'q')
        self.assertEqual(report['termination']['actual_run_seconds'],70.)
        self.assertGreaterEqual(report['h9_inferences']['post_warmup'],60)
        self.assertFalse(report['baseline_interpretation']['eligible'])

    def test_no_input_deadline_does_not_wait_forever(self):
        # Each timeout advances the virtual host by 2.5s; no RGB-D input exists.
        fake=SyntheticProbe(self,[None]*36,keys=[-1]*36)
        report=self.timed_baseline(fake)
        self.assert_closed(fake)
        self.assertEqual(report['termination']['reason'],'duration_elapsed')
        self.assertEqual(report['termination']['actual_run_seconds'],90.)
        self.assertEqual(report['h9_inferences']['total_successful'],0)
        fake.calculate.assert_not_called()

    def test_optional_duration_without_h9_keeps_normal_cleanup(self):
        fake=SyntheticProbe(self,[0,100,200])
        probe.run_probe(timing_output_path=str(self.output),duration_seconds=.2)
        report=json.loads(self.output.read_text())
        self.assert_closed(fake)
        self.assertEqual(report['termination']['reason'],'duration_elapsed')
        self.assertEqual(report['termination']['actual_run_seconds'],.2)
        self.assertEqual(report['counts']['processed_frames'],2)
        self.assertFalse(report['baseline_interpretation']['eligible'])


if __name__=='__main__':unittest.main()
