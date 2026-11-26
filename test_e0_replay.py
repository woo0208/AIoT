"""Synthetic replay contracts and software-device SDK only; never opens a camera."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout, redirect_stderr

import numpy as np

from e0_fs3 import E0Session
from e0_replay import ReplayInput, SoftwareFrames, FrameView, clock_record, stats
from frame_provenance import snapshot
from raw_rgbd_replay import RawPacket
from raw_rgbd_recording import RawRecordingControl
from test_e0_fs3 import estimators
from test_frame_provenance import pair, child
from test_h9_probe_integration import SyntheticProbe
import posture_geometry_probe as probe
import run_research_b


def camera():
    intr = dict(fx=100.,fy=100.,ppx=1.,ppy=1.,model='distortion.none',coeffs=[0.]*5)
    return dict(streams={n:dict(width=2,height=2,fps=15,format='format.'+fmt,intrinsics=intr)
        for n,fmt in (('color','bgr8'),('depth','z16'))},depth_scale_m=.001,
        depth_to_color_extrinsics=dict(rotation=[1.,0.,0.,0.,1.,0.,0.,0.,1.],translation=[0.,0.,0.]))


def packet(index,stamp,*,domain='timestamp_domain.hardware_clock',color=True,depth=True):
    c=child(index,stamp,domain=domain) if color else None
    d=child(index,stamp,stream='depth',uid=2,domain=domain) if depth else None
    f=pair(c,d)
    f.get_timestamp=lambda:stamp
    f.get_frame_number=lambda:index
    f.get_frame_timestamp_domain=lambda:domain
    return RawPacket(c.get_data() if c else None,d.get_data() if d else None,
        dict(frame_index=index,frameset_timestamp_ms=stamp,frameset_number=index,
            frameset_timestamp_domain=domain,sensors=dict(color=snapshot(c),depth=snapshot(d))),camera(),f)


class ReplayContracts(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source=self.root/'source.db3';self.source.write_bytes(b'file-only synthetic')
        self.enterContext(redirect_stdout(io.StringIO()));self.enterContext(redirect_stderr(io.StringIO()))

    def replay(self,packets,**kw):
        self.enterContext(patch('e0_replay.db3_packets',return_value=(p for p in packets)))
        r=ReplayInput(self.source,**kw);r.start(None);r.begin_stream();return r

    def validate(self,r):
        session=NS(cancel_segment=Mock(),arm_segment=Mock())
        ready,f=r.read();self.assertTrue(ready)
        row={};valid=r.validate(session,row)
        return valid,session,row

    def test_same_input_identity_excludes_only_runtime_uid(self):
        p=packet(1,100.);q=packet(1,100.)
        q.record['sensors']['color']['profile_uid']=99
        self.assertEqual(clock_record(p),clock_record(q))
        q.record['sensors']['color']['number']=2
        self.assertNotEqual(clock_record(p),clock_record(q))

    def test_readonly_pin_and_unknown_format_rejected(self):
        with self.assertRaisesRegex(ValueError,'SHA'):ReplayInput(self.source,expected_sha256='0'*64)
        path=self.root/'input.csv';path.write_text('numbers')
        with self.assertRaisesRegex(ValueError,'DB3'):ReplayInput(path)

    def test_no_silent_VIDEO_timestamp_repair_and_next_frame_recovers(self):
        r=self.replay([packet(1,100.),packet(2,100.),packet(3,99.),packet(4,101.)])
        self.assertTrue(self.validate(r)[0]);self.assertFalse(self.validate(r)[0])
        self.assertFalse(self.validate(r)[0]);self.assertTrue(self.validate(r)[0])
        self.assertEqual([x['source']['frameset_timestamp_ms'] for x in r.rows],[100.,100.,99.,101.])
        self.assertEqual(len(r.errors),2)
        self.assertEqual(r.trace.counts['color.timestamp_regression_count'],1)

    def test_submillisecond_collision_not_clamped(self):
        r=self.replay([packet(1,100.1),packet(2,100.9)])
        self.assertTrue(self.validate(r)[0]);self.assertFalse(self.validate(r)[0]);self.assertEqual(r.last_mp,100)

    def test_domain_boundary_rejected(self):
        r=self.replay([packet(1,100.),packet(2,101.,domain='timestamp_domain.system_time')])
        self.validate(r);ok,s,_=self.validate(r)
        self.assertFalse(ok);s.cancel_segment.assert_called_once_with('source_invalid')
        self.assertEqual(r.errors[-1]['cause'],'timestamp_domain_changed')

    def test_missing_pair_does_not_arm_or_reuse_features(self):
        r=self.replay([packet(1,100.,color=False)],arm_at_first_frame=True)
        ok,s,_=self.validate(r);self.assertFalse(ok);s.arm_segment.assert_not_called()
        self.assertEqual(r.errors[-1]['cause'],'missing_rgb_depth')

    def test_frame_number_gap_recorded_without_artificial_DROP(self):
        r=self.replay([packet(1,100.),packet(4,300.)]);self.validate(r);self.validate(r)
        self.assertEqual(r.trace.counts['color.missing_number_estimate'],2)
        self.assertEqual(r.errors,[])

    def test_pacing_sleeps_separately_no_drop(self):
        r=self.replay([packet(1,100.)],pacing='realtime15')
        r._stream_start+=1_000_000_000
        with patch('e0_replay.time.sleep') as sleep:
            self.validate(r);self.assertTrue(sleep.called)
        self.assertEqual(len(r.rows),1)
        self.assertIsNotNone(r.rows[0]['schedule_lateness_ms'])

    def test_throughput_does_not_sleep(self):
        r=self.replay([packet(1,100.)])
        with patch('e0_replay.time.sleep') as sleep:self.validate(r);sleep.assert_not_called()

    def test_empty_source_and_pacing_error(self):
        with self.assertRaises(ValueError):ReplayInput(self.source,pacing='bad')
        with self.assertRaisesRegex(ValueError,'Empty'):self.replay([])

    def test_no_model_download_fallback(self):
        analyze=NS(MODEL_DIR=str(self.root),load_model_lock=lambda:{'pose':{'filename':'missing'}},
            verify_model_artifact=Mock(),ensure_models=Mock())
        with self.assertRaises(FileNotFoundError):ReplayInput.locked_models(analyze)
        analyze.ensure_models.assert_not_called()

    def test_npz_corruption_stops_before_inference(self):
        root=self.root/'saved';root.mkdir()
        c=RawRecordingControl(root/'raw_rgbd',initial='on',scope='SYNTHETIC_STRUCTURAL_TEST_ONLY')
        c.bind(camera);c.capture(packet(1,100.).native_frames,dict(receive_index=1,receive_end_ns=1),armed=False,active_segment=None);c.finish()
        clip=root/'raw_rgbd/clip_0001'
        r=ReplayInput(clip)
        next((clip/'frames').glob('*.npz')).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):r.start(None)

    def test_percentiles_include_p99(self):
        s=stats([1.,2.,3.]);self.assertEqual(s['p50'],2.);self.assertGreater(s['p99'],s['p95'])

    def test_cli_rejects_B1_and_live_recording_before_camera(self):
        for extra in (['--variant','B1'],['--save-raw','on'],['--participant-id','P03']):
            with self.subTest(extra=extra),self.assertRaises(SystemExit):
                run_research_b.main(['--replay',str(self.source),*extra])

    def test_no_replay_options_on_live(self):
        with self.assertRaises(SystemExit):run_research_b.main(['--check-only','--pacing','realtime15'])

    def integrate(self,stamps,*,arm=False,fail=False):
        fake=SyntheticProbe(self,stamps)
        packets=[packet(i,t) for i,t in enumerate(stamps,1)]
        # Mock SDK source only: original Align/inference/geometry/accept loop runs.
        self.enterContext(patch('e0_replay.db3_packets',return_value=(p for p in packets)))
        r=ReplayInput(self.source,arm_at_first_frame=arm)
        self.enterContext(patch.object(r,'locked_models',return_value=dict(pose='fake',mesh='fake')))
        self.enterContext(patch.object(r,'color_intrinsics',return_value=NS(fx=100.)))
        session=E0Session(self.root/'run',*estimators(),clock_ns=fake.clock,input_scope='raw_replay',synthetic=True)
        if fail:fake.pose.detect_for_video.side_effect=RuntimeError('synthetic inference error')
        return fake,r,session

    def test_shared_pipeline_and_original_SVM_close_on_10s_source_boundary(self):
        fake,r,s=self.integrate(list(range(0,10100,100)),arm=True)
        predict=self.enterContext(patch.object(s.model,'predict',return_value=np.asarray([0])))
        probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        self.assertEqual(fake.pose.detect_for_video.call_count,101)
        self.assertEqual(fake.face.detect_for_video.call_count,101)
        self.assertEqual(fake.calculate.call_count,101)
        self.assertEqual(s.result_summary['svm_attempts'],1)
        self.assertTrue(s.segments[0]['prediction_success'])
        predict.assert_called_once()
        self.assertFalse(s.result_summary['timing_valid_for_live_performance'])
        self.assertEqual(s.result_summary['input_scope'],'raw_replay')
        sys.modules['pyrealsense2'].pipeline.assert_not_called()
        fake.cv.imshow.assert_not_called();fake.cv.waitKey.assert_not_called()

    def test_short_source_stays_incomplete_no_SVM(self):
        fake,r,s=self.integrate([0,100,200],arm=True)
        probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        self.assertEqual(s.result_summary['svm_attempts'],0)
        self.assertEqual(s.segments[0]['status'],'INCOMPLETE')
        self.assertEqual(len(r.rows),3);self.assertTrue(r.eof)
        self.assertEqual(s.result_summary['received_frames'],3)

    def test_rejected_frame_does_not_call_pose_and_can_resume(self):
        fake,r,s=self.integrate([0,0,100])
        probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        self.assertEqual(fake.pose.detect_for_video.call_count,2)
        self.assertEqual(s.result_summary['received_frames'],3)
        self.assertEqual(s.result_summary['completed_frames'],2)
        self.assertEqual([x['status'] for x in r.rows],['completed','rejected','completed'])

    def test_inference_error_closes_models_and_source_preserves_input(self):
        fake,r,s=self.integrate([0,100],fail=True)
        stop=self.enterContext(patch.object(r,'stop',wraps=r.stop))
        before=self.source.read_bytes()
        with self.assertRaises(RuntimeError):probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        stop.assert_called_once();fake.pose.close.assert_called_once();fake.face.close.assert_called_once()
        self.assertEqual(s.result_summary['status'],'FAILED');self.assertEqual(self.source.read_bytes(),before)

    def test_report_has_actual_calls_boundaries_and_original_identity(self):
        fake,r,s=self.integrate([0,100,200])
        probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        with patch('e0_replay._stored_image_counts',return_value=None):
            report=r.report(s)
        self.assertEqual(report['actual_calls'],dict(align=3,pose=3,face=3,depth=3,svm=0))
        self.assertEqual(report['input_frames'],3);self.assertEqual(report['processed_frames'],3)
        self.assertTrue(report['source_unchanged']);self.assertEqual(report['inference_kernel_ms']['count'],3)
        self.assertEqual(report['accuracy'],'NOT_MEASURED');self.assertIn('read_decode',report['measurement_boundaries'])
        self.assertIsNotNone(report['process_cpu_ms_per_input'])
        self.assertEqual(len({r['feature_vector_sha256'] for r in report['frames']}),1)

    def test_changed_source_is_never_reported_completed(self):
        fake,r,s=self.integrate([0,100])
        probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        self.source.write_bytes(b'changed synthetic file')
        with patch('e0_replay._stored_image_counts',return_value=None):report=r.report(s)
        self.assertEqual(report['status'],'FAILED');self.assertFalse(report['source_unchanged'])


class SoftwareSDKTests(unittest.TestCase):
    def test_tiny_SDK_profiles_rejected_before_native_allocation(self):
        import pyrealsense2 as rs
        with self.assertRaisesRegex(ValueError,'width >=64'):
            SoftwareFrames(rs,camera())

    def test_injected_profiles_clocks_and_native_align_without_camera(self):
        import pyrealsense2 as rs
        p=packet(9,123.25);p.native_frames=None
        for profile in p.camera['streams'].values():profile.update(width=64,height=48)
        p.color_bgr=np.zeros((48,64,3),dtype=np.uint8)
        p.depth_z16=np.full((48,64),1000,dtype=np.uint16)
        sw=SoftwareFrames(rs,p.camera)
        try:
            frames=sw.compose(p)
            self.assertEqual(snapshot(frames.get_color_frame())['timestamp_ms'],123.25)
            self.assertEqual(frames.get_depth_frame().get_frame_number(),9)
            aligned=rs.align(rs.stream.color).process(frames)
            self.assertEqual(np.asanyarray(aligned.get_depth_frame().get_data()).shape,(48,64))
            self.assertEqual(frames.get_color_frame().profile.as_video_stream_profile().get_intrinsics().fx,100.)
        finally:sw.close()


if __name__=='__main__':unittest.main()
