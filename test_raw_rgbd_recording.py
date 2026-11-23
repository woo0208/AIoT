"""Synthetic arrays/SDK/Tk only. Never starts a camera or participant evaluation."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler

from e0_fs3 import E0Session
from e0_panel import OperatorPanel, run_bound_probe
from e0_guided_panel import GuidedPanel
from research_b import DemandPolicy
from research_b_report import report
import raw_rgbd_recording as raw
import posture_geometry_probe as probe
from test_e0_fs3 import Clock, estimators, result
from test_frame_provenance import child, pair
from test_h9_probe_integration import SyntheticProbe


def metadata():
    return dict(streams=dict(color=dict(width=2,height=2),depth=dict(width=2,height=2)),
        depth_scale_m=.001, depth_to_color_extrinsics=dict(rotation=[1.,0.,0.,0.,1.,0.,0.,0.,1.],
        translation=[.05,0.,0.]), alignment='NONE_NATIVE_STREAMS')


def rows(clip):
    return [json.loads(line) for line in (clip/'frames.jsonl').read_text(encoding='utf-8').splitlines()]


class RawStorageTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.control=raw.RawRecordingControl(self.root/'raw_rgbd',scope='SYNTHETIC_STRUCTURAL_TEST_ONLY')
        self.provider=Mock(side_effect=metadata)
        self.control.bind(self.provider)

    def capture(self,index=1,stamp=100.,*,color=True,depth=True):
        return self.control.capture(pair(child(index,stamp) if color else None,
            child(index,stamp,stream='depth',uid=2) if depth else None),
            dict(receive_index=index,receive_end_ns=1000*index),armed=True,active_segment=2)

    def test_off_and_on_without_input_never_read_arrays_or_create_files(self):
        self.assertFalse(self.control.capture(Mock(),{}))
        self.control.set_enabled(True)
        self.assertFalse(self.root.joinpath('raw_rgbd').exists())
        self.control.set_enabled(False)
        self.provider.assert_not_called()
        self.control.finish()
        self.assertFalse(self.root.joinpath('raw_rgbd').exists())

    def test_on_off_on_creates_distinct_clips_and_lossless_arrays_clocks(self):
        self.control.set_enabled(True);self.capture()
        first=self.control.current
        self.control.set_enabled(False)
        saved=rows(first)[0]
        arrays=raw.load_raw_frame(first,saved)
        np.testing.assert_array_equal(arrays['color_bgr'],np.zeros((2,2,3),dtype=np.uint8))
        np.testing.assert_array_equal(arrays['depth_z16'],np.ones((2,2),dtype=np.uint16))
        self.assertEqual(saved['sensors']['color']['timestamp_ms'],100.)
        self.assertEqual(saved['sensors']['depth']['number'],1)
        self.assertEqual(saved['host_receive_end_ns'],1000)
        self.assertEqual(saved['active_segment_index'],2)
        self.assertEqual(json.loads((first/'end.json').read_text())['status'],'COMPLETED')
        before={p.name:p.read_bytes() for p in first.iterdir() if p.is_file()}
        self.assertFalse(self.capture(2))
        self.control.set_enabled(True);self.capture(3,300.)
        second=self.control.current
        self.control.finish()
        self.assertNotEqual(first,second)
        self.assertEqual(rows(second)[0]['receive_index'],3)
        self.assertEqual(rows(second)[0]['frame_index'],1)
        self.assertEqual(before,{p.name:p.read_bytes() for p in first.iterdir() if p.is_file()})
        self.assertEqual(self.control.summary()['frames'],2)

    def test_missing_streams_are_absent_and_previous_pixels_never_reused(self):
        self.control.set_enabled(True)
        self.capture(1)
        self.capture(2,color=False)
        self.capture(3,depth=False)
        clip=self.control.current;self.control.finish()
        records=rows(clip)
        self.assertEqual(set(raw.load_raw_frame(clip,records[1])),{'depth_z16'})
        self.assertEqual(set(raw.load_raw_frame(clip,records[2])),{'color_bgr'})
        self.assertEqual(records[1]['sensors']['color']['status'],'NOT_MEASURED')

    def test_source_duplicate_and_regressing_timestamps_are_preserved(self):
        self.control.set_enabled(True)
        for i,stamp in enumerate((100.,100.,90.),1):self.capture(i,stamp)
        clip=self.control.current;self.control.finish()
        self.assertEqual([r['frameset_timestamp_ms'] for r in rows(clip)],[100.,100.,90.])

    def test_invalid_native_dtype_fails_without_inventing_a_frame(self):
        self.control.set_enabled(True)
        color=child();color.get_data=lambda:np.zeros((2,2,3),dtype=np.uint16)
        with self.assertRaises(raw.RawRecordingError):
            self.control.capture(pair(color,child(stream='depth')),dict(receive_index=1,receive_end_ns=0))
        self.assertEqual(self.control.total_frames,0)
        self.assertEqual(self.control.summary()['status'],'FAILED')

    def test_existing_clip_is_never_overwritten_or_finalized(self):
        existing=self.root/'raw_rgbd/clip_0001';existing.mkdir(parents=True)
        (existing/'sentinel').write_bytes(b'PRESERVE')
        self.control.set_enabled(True)
        with self.assertRaises(raw.RawRecordingError):self.capture()
        self.assertEqual([p.name for p in existing.iterdir()],['sentinel'])
        self.assertEqual((existing/'sentinel').read_bytes(),b'PRESERVE')
        self.assertEqual(self.control.clip_count,0)

    def test_disk_reserve_error_stops_recording_before_writing(self):
        self.control.set_enabled(True)
        with patch.object(raw.shutil,'disk_usage',return_value=NS(free=0)):
            with self.assertRaises(raw.RawRecordingError):self.capture()
        self.assertFalse(self.control.requested)
        self.assertFalse(self.root.joinpath('raw_rgbd').exists())
        with self.assertRaises(raw.RawRecordingError):self.control.set_enabled(True)

    def test_partial_write_is_failed_and_prior_indexed_frames_remain_readable(self):
        self.control.set_enabled(True);self.capture()
        clip=self.control.current
        with patch.object(raw.np,'savez',side_effect=OSError('PRIVATE details')):
            with self.assertRaises(raw.RawRecordingError):self.capture(2)
        end=json.loads((clip/'end.json').read_text())
        self.assertEqual(end['status'],'FAILED');self.assertEqual(end['frames'],1)
        self.assertEqual(len(rows(clip)),1)
        self.assertEqual(raw.load_raw_frame(clip,rows(clip)[0])['depth_z16'].dtype,np.uint16)
        self.assertNotIn('PRIVATE',json.dumps(self.control.summary()))

    def test_off_finalization_failure_is_not_reported_as_success(self):
        self.control.set_enabled(True);self.capture();clip=self.control.current
        with patch.object(raw,'write_json',side_effect=OSError('PRIVATE')):
            with self.assertRaises(raw.RawRecordingError):self.control.set_enabled(False)
        self.assertFalse((clip/'end.json').exists())
        self.assertEqual(self.control.summary()['status'],'FAILED')
        self.control.finish()

    def test_stream_error_marks_current_clip_failed_and_finish_is_idempotent(self):
        self.control.set_enabled(True);self.capture();clip=self.control.current
        self.control.finish(error=RuntimeError('PRIVATE'))
        self.control.finish()
        self.assertEqual(json.loads((clip/'end.json').read_text())['status'],'FAILED')
        self.assertEqual(self.control.summary()['status'],'FAILED')
        self.assertFalse(self.control.requested)

    def test_reader_rejects_tampering_and_path_substitution(self):
        self.control.set_enabled(True);self.capture();clip=self.control.current;self.control.finish()
        record=rows(clip)[0]
        bad=dict(record,file='../other.npz')
        with self.assertRaises(ValueError):raw.load_raw_frame(clip,bad)
        with self.assertRaises(ValueError):raw.load_raw_frame(clip,dict(record,frame_index=-1))
        (clip/record['file']).write_bytes(b'CORRUPT')
        with self.assertRaises(ValueError):raw.load_raw_frame(clip,record)

    def test_camera_metadata_keeps_geometry_and_marks_unavailable_private_identity(self):
        intr=NS(width=1280,height=720,fx=600.,fy=601.,ppx=640.,ppy=360.,model='distortion.none',coeffs=[0.]*5)
        color=NS(get_intrinsics=lambda:intr,fps=lambda:15,format=lambda:'bgr8')
        depth=NS(get_intrinsics=lambda:NS(**{**vars(intr),'width':848,'height':480}),
            fps=lambda:15,format=lambda:'z16',get_extrinsics_to=lambda c:NS(rotation=list(range(9)),translation=[.05,0.,0.]))
        profile=NS(get_stream=lambda stream: NS(as_video_stream_profile=lambda:color if stream==1 else depth),
            get_device=lambda:NS(first_depth_sensor=lambda:NS(get_depth_scale=lambda:.001)))
        actual=raw.camera_metadata(profile,NS(stream=NS(color=1,depth=2)))
        self.assertEqual(actual['streams']['depth']['width'],848)
        self.assertEqual(actual['streams']['color']['intrinsics']['fx'],600.)
        self.assertEqual(actual['depth_to_color_extrinsics']['translation'],[.05,0.,0.])
        self.assertEqual(actual['device']['serial_number']['status'],'NOT_MEASURED')
        self.assertIsNone(actual['device']['serial_number']['value'])


class RawProbeTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(SVC,'fit',side_effect=AssertionError('no fit')))
        self.enterContext(patch.object(StandardScaler,'fit',side_effect=AssertionError('no fit')))

    def run_fake(self,variant='B1',*,initial='off',events=None,actions=None,arm_at=None,fail=None,
                 deadline=False,mutate_align=False,session_context=None):
        events=[0,100,200,300,400] if events is None else events
        model,scaler=estimators();clock=Clock()
        session=E0Session(self.root/str(len(list(self.root.iterdir()))),model,scaler,clock_ns=clock)
        control=raw.RawRecordingControl(session.directory/'raw_rgbd',initial=initial,scope=session.scope,
            session_context=session_context,clock_ns=clock)
        session.raw_recording=control
        fake=SyntheticProbe(self,events)
        fake.calculate.return_value=result()
        fake.cv.putText=Mock();fake.cv.FONT_HERSHEY_SIMPLEX=0
        fake.raw_metadata=self.enterContext(patch.object(raw,'camera_metadata',side_effect=lambda p,rs:metadata()))
        if mutate_align:
            def align(frames):
                frames.get_depth_frame().get_data=lambda:np.full((2,2),99,dtype=np.uint16)
                return frames
            self.enterContext(patch.object(sys.modules['pyrealsense2'],'align',
                                          return_value=NS(process=align)))
        seen=[0];actions=actions or {}
        def poll():
            seen[0]+=1;clock.add_ms(1)
            if seen[0] in actions:control.set_enabled(actions[seen[0]])
            if seen[0]==arm_at:session.arm_segment()
            return seen[0]<=len(events)
        if fail=='inference':fake.pose.detect_for_video.side_effect=RuntimeError('PRIVATE')
        if fail=='write':self.enterContext(patch.object(raw.np,'savez',side_effect=OSError('PRIVATE')))
        if deadline:
            receive=fake.pipeline.try_wait_for_frames.side_effect
            def delayed(timeout):
                value=receive(timeout);clock.add_ms(20);return value
            fake.pipeline.try_wait_for_frames.side_effect=delayed
            real=probe.probe_timing.ProbeRunControl
            self.enterContext(patch.object(probe.probe_timing,'ProbeRunControl',
                side_effect=lambda duration,**kwargs:real(.01,clock_ns=clock)))
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()), \
                patch.object(model,'predict',return_value=np.array([2])) as predict, \
                patch.object(scaler,'transform',wraps=scaler.transform) as transform:
            kwargs=dict(e0_session=session,ui_poll=poll,rgbd_policy=DemandPolicy(variant),raw_recording=control)
            if fail:
                with self.assertRaises((RuntimeError,raw.RawRecordingError)):probe.run_probe(**kwargs)
            else:probe.run_probe(**kwargs)
            inputs=[c.args[0].copy() for c in transform.call_args_list]
            predictions=predict.call_count
        fake.pipeline.start.assert_called_once();fake.pipeline.stop.assert_called_once()
        fake.pose.close.assert_called_once();fake.face.close.assert_called_once()
        fake.cv.destroyAllWindows.assert_called_once()
        return session,control,fake,inputs,predictions

    def test_e0_and_b1_toggle_save_same_native_inputs_including_idle(self):
        for variant in ('E0','B1'):
            s,c,fake,_,_=self.run_fake(variant,actions={2:True,3:False,4:True})
            clips=sorted(c.directory.glob('clip_*'))
            self.assertEqual(len(clips),2)
            records=[r for clip in clips for r in rows(clip)]
            self.assertEqual([r['receive_index'] for r in records],[2,4,5])
            self.assertEqual([r['frameset_timestamp_ms'] for r in records],[900100.,900300.,900400.])
            self.assertEqual(c.total_frames,3)
            self.assertEqual(fake.pose.detect_for_video.call_count,5 if variant=='E0' else 0)
            self.assertEqual(s.result_summary['environment']['raw_recording']['frames'],3)
            self.assertIn('stored separately in raw_rgbd/',s.result_summary['limitations'][-1])
            self.assertEqual(report(s.directory)['stages_ms']['io.raw_rgbd']['count'],3)
            self.assertEqual(json.loads((clips[0]/'recording.json').read_text())['camera'],metadata())
            for clip in clips:
                for r in rows(clip):self.assertIn('depth_z16',raw.load_raw_frame(clip,r))

    def test_raw_off_makes_no_files_and_does_not_query_calibration(self):
        s,c,fake,_,_=self.run_fake()
        fake.raw_metadata.assert_not_called()
        self.assertFalse(c.directory.exists());self.assertEqual(c.total_frames,0)
        self.assertEqual(s.result_summary['environment']['raw_recording']['initial'],'off')

    def test_raw_is_native_before_alignment_mutates_the_depth_input(self):
        s,c,_,_,_=self.run_fake('E0',initial='on',events=[0],mutate_align=True)
        saved=raw.load_raw_frame(c.last_clip,rows(c.last_clip)[0])
        np.testing.assert_array_equal(saved['depth_z16'],np.ones((2,2),dtype=np.uint16))
        aligned=probe.geometry.points_from_pose_landmarks.call_args.kwargs['aligned_depth']
        np.testing.assert_array_equal(aligned,np.full((2,2),99,dtype=np.uint16))

    def test_initial_on_and_mid_hold_toggle_preserve_original_scaler_input_and_prediction(self):
        collected=[]
        for variant in ('E0','B1'):
            for initial,actions in (('off',{}),('on',{15:False,20:True})):
                s,c,fake,inputs,predictions=self.run_fake(variant,initial=initial,actions=actions,
                    events=list(range(0,11400,300)),arm_at=2)
                self.assertEqual(predictions,1)
                self.assertEqual(s.segments[0]['prediction'],2)
                self.assertEqual(s.segments[0]['input_frames'],34)
                self.assertEqual(s.segments[0]['valid_frames'],34)
                collected.append(inputs[0])
                if initial=='off':self.assertFalse(c.directory.exists())
        for item in collected[1:]:np.testing.assert_array_equal(item,collected[0])

    def test_input_saved_before_inference_failure_and_failed_clip_preserved(self):
        s,c,_,_,_=self.run_fake('E0',initial='on',fail='inference')
        clip=c.last_clip
        self.assertEqual(c.total_frames,1)
        self.assertEqual(json.loads((clip/'end.json').read_text())['status'],'FAILED')
        self.assertIn('color_bgr',raw.load_raw_frame(clip,rows(clip)[0]))
        self.assertEqual(s.result_summary['status'],'FAILED')
        self.assertEqual(s.result_summary['environment']['raw_recording']['status'],'FAILED')

    def test_raw_write_failure_fails_run_and_still_cleans_all_sdk_objects(self):
        s,c,_,_,_=self.run_fake('E0',initial='on',fail='write')
        self.assertEqual(s.result_summary['status'],'FAILED')
        self.assertEqual(c.summary()['status'],'FAILED')
        self.assertFalse(c.requested)

    def test_received_deadline_input_saved_even_when_processing_is_skipped(self):
        s,c,fake,_,_=self.run_fake(initial='on',deadline=True)
        self.assertEqual(c.total_frames,1)
        fake.pose.detect_for_video.assert_not_called()
        self.assertEqual(s.result_summary['frame_status_counts']['deadline_skip'],1)


class FakeVar:
    def __init__(self,value=''):self.value=value
    def set(self,value):self.value=value
    def get(self):return self.value


class RawUiTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        model,scaler=estimators()
        self.s=E0Session(self.root/'session',model,scaler,clock_ns=Clock())
        self.c=raw.RawRecordingControl(self.s.directory/'raw_rgbd',scope=self.s.scope)
        self.s.raw_recording=self.c
        self.window=Mock();self.buttons=[]
        def button(*args,**kwargs):self.buttons.append(kwargs);return Mock()
        self.tk=NS(Tk=lambda:self.window,StringVar=FakeVar,Label=lambda *a,**kw:Mock(),Button=button)

    def tearDown(self):
        self.c.finish();self.s.finish()

    def test_button_toggles_raw_only_and_status_shows_path_frames(self):
        panel=OperatorPanel(self.s,tk_module=self.tk)
        panel.control.start()
        button=next(b for b in self.buttons if b['text']=='원본 저장 ON/OFF')
        button['command']();self.assertTrue(self.c.requested)
        self.assertTrue(self.s.armed)
        self.assertIn('원본 저장 ON',panel.raw_status.get())
        self.assertIn('raw_rgbd',panel.raw_status.get())
        button['command']();self.assertFalse(self.c.requested)
        self.assertTrue(self.s.armed)
        self.assertIn('원본 저장 OFF',panel.raw_status.get())
        self.assertFalse(self.c.directory.exists())
        panel.close()

    def test_guided_panel_has_same_control_and_extra_room_without_exporting_subject(self):
        panel=GuidedPanel(self.s,subject='P01',tk_module=self.tk)
        self.assertTrue(any(b['text']=='원본 저장 ON/OFF' for b in self.buttons))
        panel._toggle_raw();self.assertTrue(self.c.requested)
        self.window.geometry.assert_any_call('820x660')
        self.assertTrue(panel.poll())
        self.assertNotIn('P01',json.dumps(self.c.summary()))
        panel.close()

    def test_tk_callback_error_is_visible_and_poll_propagates_failure(self):
        panel=OperatorPanel(self.s,tk_module=self.tk)
        self.c.error_type='OSError'
        panel._toggle_raw()
        self.assertIn('ERROR',panel.raw_status.get())
        with self.assertRaises(raw.RawRecordingError):panel.poll()
        panel.close()


class RawLauncherTests(unittest.TestCase):
    def test_both_launchers_check_only_is_no_creation_and_live_forwards_initial_state(self):
        import run_e0_check
        import run_research_b
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);binding=root/'binding.json'
            binding.write_text(json.dumps(dict(path='artifact.pkl',artifact_sha256='a'*64,
                feature_ids=['F1','F3','F4','F5','F6','F7','F8'],model_sha256='b'*64,scaler_sha256='c'*64)))
            for cli in (run_e0_check,run_research_b):
                with patch.object(cli,'ROOT',root),patch.object(cli,'environment_record'), \
                        patch.object(cli,'load_fs3',return_value=(None,None,dict(training_samples=60,artifact_sha256='a'*64))), \
                        patch.object(cli,'run_bound_probe') as bound,patch.object(cli,'run_probe') as camera, \
                        redirect_stdout(io.StringIO()):
                    for state in ('on','off'):
                        args=['--binding',str(binding),'--save-raw',state,'--output-dir',str(root/'new'/'run')]
                        cli.main(['--check-only',*args])
                        self.assertFalse((root/'new').exists())
                        bound.assert_not_called();camera.assert_not_called()
                    for state in ('on','off'):
                        cli.main(['--live','--binding',str(binding),'--save-raw',state,
                                  '--output-dir',str(root/'run')])
                        self.assertEqual(bound.call_args.kwargs['save_raw'],state)
                        session=NS(environment_metadata={});marker=object()
                        bound.call_args.kwargs['probe_runner'](e0_session=session,raw_recording=marker)
                        self.assertIs(camera.call_args.kwargs['raw_recording'],marker)

    def test_bound_session_attaches_control_before_panel_and_closes_it(self):
        import e0_panel
        with tempfile.TemporaryDirectory() as temp:
            model,scaler=estimators();clock=Clock()
            panels=[]
            def panel_factory(session):
                self.assertTrue(session.raw_recording.requested)
                panel=NS(poll=lambda:True,close=Mock());panels.append(panel)
                return panel
            fake=SyntheticProbe(self,[0,100,200])
            fake.calculate.return_value=result()
            factory=lambda *a,**kw:E0Session(*a,**kw,clock_ns=clock)
            with patch.object(e0_panel,'load_fs3',return_value=(model,scaler,{})), \
                    patch.object(e0_panel,'environment_record',return_value={}), \
                    patch.object(e0_panel,'E0Session',side_effect=factory), \
                    patch.object(raw,'camera_metadata',return_value=metadata()), \
                    redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                s=run_bound_probe('unused',dict(artifact_sha256='a'*64,feature_ids=[],
                    model_sha256='b'*64,scaler_sha256='c'*64),Path(temp)/'run',execution_authorized=True,
                    save_raw='on',panel_factory=panel_factory)
            self.assertTrue(s.raw_recording._finished)
            self.assertEqual(s.raw_recording.total_frames,3)
            panels[0].close.assert_called_once()
            fake.pipeline.stop.assert_called_once()


if __name__=='__main__':unittest.main()
