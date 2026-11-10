"""Synthetic SDK/clocks/estimators only. No camera, raw data, fit, or evaluation."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

import e0_fs3 as e0
import posture_geometry as geometry
import posture_geometry_probe as probe
from test_frame_provenance import child, pair
from test_h9_probe_integration import SyntheticProbe


class Clock:
    def __init__(self): self.ns = 0
    def __call__(self): return self.ns
    def add_ms(self, ms): self.ns += int(ms*1e6)


def estimators():
    # Structural fitted-state fixture only; no training and no real learned model.
    model = SVC(C=1., gamma=1./9, probability=False, random_state=0)
    model.classes_, model.n_features_in_ = np.arange(6), 7
    model.support_vectors_ = np.zeros((6,7))
    model._gamma = 1./9
    scaler = StandardScaler()
    scaler.n_features_in_, scaler.n_samples_seen_ = 7, 60
    scaler.mean_, scaler.var_, scaler.scale_ = np.arange(7,dtype=float), np.ones(7), np.ones(7)
    return model, scaler


def result(missing=(), angle=10.):
    values = {n:float(i+1) for i,n in enumerate(e0.H9_FEATURE_NAMES)}
    values[e0.H9_FEATURE_NAMES[2]] = angle
    values.update({e0.H9_FEATURE_NAMES[i]:None for i in missing})
    return geometry.GeometryResult({}, {}, values)


class E0Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clock = Clock()
        self.model, self.scaler = estimators()
        self.enterContext(patch.object(SVC,'fit',side_effect=AssertionError('no fit')))
        self.enterContext(patch.object(StandardScaler,'fit',side_effect=AssertionError('no fit')))

    def session(self, name='e0'):
        return e0.E0Session(self.root/name, self.model, self.scaler, clock_ns=self.clock)

    def observe(self, session, index, stamp, value=None, *, face=True):
        row = session.begin_receive()
        self.clock.add_ms(1)
        session.received(row,True,pair(child(index,stamp),child(index,stamp,stream='depth',uid=2)),self.clock())
        session.aligned(row,child(index,stamp),child(index,stamp,stream='depth',uid=20))
        session.accept(row,value or result(),index,stamp,pose_detected=True,face_detected=face)
        session.frame_completed(row)
        return row

    def read(self, s, name='summary.json'):
        return json.loads((s.directory/name).read_text(encoding='utf-8'))

    def test_model_settings_scaler_and_class_order_are_checked_without_fit(self):
        for change in [dict(gamma=1/7),dict(C=2),dict(class_weight={1:1.5}),dict(probability=True)]:
            self.model.set_params(**change)
            with self.assertRaises(ValueError):self.session()
            self.model,self.scaler = estimators()
        self.model.classes_ = np.arange(5)
        with self.assertRaises(ValueError):self.session()
        self.model,self.scaler = estimators();self.scaler.scale_[0] = 0
        with self.assertRaises(ValueError):self.session()
        self.model,self.scaler = estimators();self.scaler.mean_[0] = np.nan
        with self.assertRaises(ValueError):self.session()

    def test_original_aggregation_support_circular_mean_and_order_are_preserved(self):
        s=self.session();s.begin_stream();s.arm_segment()
        for i in range(40):
            self.observe(s,i+1,i*200,result(missing=(8,) if i<5 else (),angle=179. if i%2 else -179.))
        reference=e0.aggregate_h5_h9_sample(s.records)
        expected=np.array([[reference.features[e0.H9_FEATURE_NAMES[i]] for i in e0.COLUMNS]])
        with patch.object(self.model,'predict',return_value=np.array([1])) as predict:
            self.observe(s,41,10000)
        np.testing.assert_array_equal(predict.call_args.args[0],self.scaler.transform(expected))
        s.end_stream();s.finish()
        segment=s.segments[0]
        self.assertEqual((segment['input_frames'],segment['valid_frames'],segment['coverage']),(40,35,.875))
        self.assertEqual(segment['prediction_label'],'P1')
        self.assertEqual(self.read(s)['prediction_success_percent'],100)
        self.assertEqual(self.read(s)['scope'],'SYNTHETIC_STRUCTURAL_TEST_ONLY')
        self.assertEqual(len(s.records),0)
        self.assertNotIn('segment_index',s.frames[-1])

    def test_exact_half_open_ten_second_boundary_prep_pause_and_incomplete(self):
        s=self.session();s.begin_stream()
        self.observe(s,1,0)  # Preparation is not a sample.
        s.arm_segment()
        for i in range(30):self.observe(s,i+2,100+i*330)
        with patch.object(self.model,'predict',return_value=np.array([0])) as predict:
            self.observe(s,32,10100);self.observe(s,33,10200)
        self.assertEqual(predict.call_count,1)
        self.assertEqual(s.segments[0]['input_frames'],30)
        s.arm_segment();self.observe(s,34,10300);s.cancel_segment()
        self.assertEqual(s.segments[1]['status'],'INCOMPLETE')
        s.arm_segment();self.observe(s,35,10400);s.finish()
        self.assertEqual(s.segments[2]['reason'],'stream_end')
        self.assertFalse(s.segments[2]['eligible'])

    def test_eligibility_thresholds_not_weakened_or_changed_to_seven_column_support(self):
        for name,n,missing in [('few',29,()),('low_coverage',60,(8,))]:
            s=self.session(name);s.begin_stream();s.arm_segment()
            for i in range(n):self.observe(s,i+1,i*100,result(missing=missing if i<31 else ()))
            with patch.object(self.model,'predict',side_effect=AssertionError('ineligible must not predict')):
                self.observe(s,n+1,10000)
            s.finish();self.assertEqual(s.segments[0]['status'],'INELIGIBLE')
            self.assertIsNone(self.read(s)['prediction_success_percent'])
        s=self.session('exact');s.arm_segment()
        for i in range(60):self.observe(s,i+1,i*100,result(missing=(8,) if i<30 else ()))
        with patch.object(self.model,'predict',return_value=np.array([5])):self.observe(s,61,10000)
        self.assertEqual(s.segments[0]['coverage'],.5)
        self.assertTrue(s.segments[0]['prediction_success'])

    def test_clock_reset_and_duplicate_stop_hold_without_imputation(self):
        for name,stamp in [('reset',99),('duplicate',100)]:
            s=self.session(name);s.arm_segment();self.observe(s,1,100)
            row=self.observe(s,2,stamp)
            self.assertEqual(s.segments[0]['reason'],'timestamp_invalid')
            self.assertEqual(row['segment_time_failure'],
                'duplicate_timestamp' if name=='duplicate' else 'timestamp_regression')
            self.assertEqual(s.last_segment_issue,'TIMESTAMP_INVALID')
            self.assertFalse(s.records)
            self.assertFalse(s.armed)
            self.assertFalse(s.segments[0]['prediction_attempted'])
            self.observe(s,3,200)  # No implicit restart after rejection.
            self.assertIsNone(s.active)
            s.arm_segment()
            for i in range(30):self.observe(s,i+4,300+i*300)
            with patch.object(self.model,'predict',return_value=np.array([0])) as predict:
                self.observe(s,34,10300)
            self.assertEqual(predict.call_count,1)
            self.assertEqual(s.segments[1]['input_frames'],30)
            self.assertEqual(s.segments[1]['status'],'PREDICTED')
            s.finish()
            self.assertEqual(self.read(s)['status'],'COMPLETED')
            self.assertEqual(sum(self.read(s)['segment_time_failures'].values()),1)

    def test_invalid_initial_timestamp_is_visible_without_starting_a_hold(self):
        for name,stamp,issue in [('nan',float('nan'),'non_finite'),
                                 ('infinity',float('inf'),'non_finite'),
                                 ('text','invalid','not_numeric')]:
            s=self.session(name);s.arm_segment()
            row=self.observe(s,1,stamp)
            self.assertEqual(row['segment_time_failure'],issue)
            self.assertEqual(s.last_segment_issue,'TIMESTAMP_INVALID')
            self.assertIsNone(s.active)
            self.assertFalse(s.armed)
            self.assertFalse(s.records)
            s.finish()
            self.assertEqual(self.read(s)['segment_time_failures'],{issue:1})

    def test_feature_failures_and_zero_denominators(self):
        s=self.session();s.begin_stream()
        self.observe(s,1,0,result(missing=(0,2,3,4)),face=False)
        s.finish();summary=self.read(s)
        self.assertEqual(summary['feature_success_percent'],0)
        self.assertIn('missing_F1',summary['failure_reasons'])
        self.assertIn('face_not_detected',summary['failure_reasons'])
        self.assertIsNone(summary['prediction_success_percent'])
        s=self.session('empty');s.finish()
        self.assertIsNone(self.read(s)['feature_success_percent'])

    def test_nonfinite_observation_is_logged_and_cannot_enter_aggregation(self):
        s=self.session();s.arm_segment();bad=dict(result().features);bad[e0.H9_FEATURE_NAMES[0]]=np.nan
        with self.assertRaises(ValueError):self.observe(s,1,0,geometry.GeometryResult({}, {}, bad))
        self.assertIn('invalid_F1',s.frames[0]['feature_failure_reasons'])
        self.assertFalse(s.records)

    def test_sensor_duplicates_child_reuse_gaps_and_boundaries_are_separate(self):
        s=self.session()
        sequence=[(1,1,0,'hardware_clock'),(1,2,10,'hardware_clock'),(4,2,20,'hardware_clock'),
                  (4,2,20,'hardware_clock'),(1,1,1,'hardware_clock'),(2,2,2,'system_time')]
        for rgb,depth,stamp,domain in sequence:
            row=s.begin_receive()
            # Reused child retains its timestamp even when the other advances.
            rgb_stamp=0 if rgb==1 and depth==2 else stamp
            depth_stamp=10 if depth==2 and rgb==4 else stamp
            s.received(row,True,pair(child(rgb,rgb_stamp,domain=domain),
                child(depth,depth_stamp,domain=domain,uid=2,stream='depth')),self.clock())
        self.assertTrue(s.frames[1]['raw_relations']['rgb']['child_reused_while_other_advanced'])
        self.assertEqual(s.frames[2]['raw_relations']['rgb']['source_gap'],2)
        self.assertEqual(s.frames[3]['raw_relations']['rgb']['classification'],'DUPLICATE_IDENTITY')
        self.assertEqual(s.frames[4]['raw_relations']['rgb']['classification'],'COUNTER_RESET_OR_WRAP')
        self.assertEqual(s.frames[5]['raw_relations']['rgb']['classification'],'STREAM_BOUNDARY')
        row=s.begin_receive();s.received(row,True,pair(None,None),self.clock())
        self.assertEqual(row['raw_relations']['rgb']['classification'],'NOT_MEASURED')
        s.finish();self.assertEqual(self.read(s)['sensor_missing_rate'],'NOT_MEASURED')

    def test_high_resolution_stage_percentiles_and_prediction_endpoints(self):
        s=self.session();s.begin_stream();s.arm_segment()
        for i in range(30):self.observe(s,i+1,i*100)
        original=e0.aggregate_h5_h9_sample
        def aggregate(records):self.clock.add_ms(2);return original(records)
        transform=self.scaler.transform
        def scale(x):self.clock.add_ms(3);return transform(x)
        def predict(x):self.clock.add_ms(5);return np.array([2])
        with patch.object(e0,'aggregate_h5_h9_sample',side_effect=aggregate), \
             patch.object(self.scaler,'transform',side_effect=scale), \
             patch.object(self.model,'predict',side_effect=predict):self.observe(s,31,10000)
        s.finish();stats={x['name']:x for x in self.read(s,'timing/diagnostics.json')['stage_milliseconds']}
        for name,ms in [('fs3.aggregate',2),('fs3.scale',3),('fs3.svm',5)]:
            for percentile in ['p50','p95','p99']:self.assertEqual(stats[name][percentile],ms)
        self.assertEqual(s.segments[0]['aggregation_ns'],2_000_000)
        self.assertEqual(s.segments[0]['scale_svm_ns'],8_000_000)
        self.assertEqual(s.segments[0]['boundary_input_to_prediction_ns'],10_000_000)
        self.assertGreater(s.segments[0]['first_input_to_prediction_ns'],10_000_000)

    def test_prediction_failure_and_privacy_safe_partial_publication(self):
        s=self.session();s.arm_segment()
        for i in range(30):self.observe(s,i+1,i*100)
        with patch.object(self.model,'predict',side_effect=RuntimeError('PRIVATE person/path/token')):
            with self.assertRaises(RuntimeError):self.observe(s,31,10000)
        s.finish(error=RuntimeError('PRIVATE name'))
        self.assertEqual(self.read(s)['prediction_success_percent'],0)
        self.assertEqual(s.segments[0]['error_type'],'RuntimeError')
        text=''.join(p.read_text(encoding='utf-8') for p in s.directory.rglob('*') if p.is_file())
        for sensitive in ['PRIVATE','support_vectors_', 'timestamp_utc','serial_number','anonymous']:
            self.assertNotIn(sensitive,text)
        with self.assertRaises(ValueError):s.arm_segment()
        with self.assertRaises(FileExistsError):self.session()

    def test_probe_connects_real_boundaries_with_synthetic_sdk_and_no_legacy_logs(self):
        s=self.session();s.arm_segment()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()));stack.enter_context(redirect_stderr(io.StringIO()))
            fake=SyntheticProbe(NS(enterContext=stack.enter_context),list(range(0,10400,200)),keys=[-1]*52)
            def receive(_):
                i=receive.index;receive.index+=1;fake.clock.set_ms(i*200);self.clock.ns=i*200_000_000
                return True,pair(child(i+1,i*200),child(i+1,i*200,stream='depth',uid=2))
            receive.index=0;fake.pipeline.try_wait_for_frames.side_effect=receive
            stack.enter_context(patch.object(self.model,'predict',return_value=np.array([1])))
            run_control=probe.probe_timing.ProbeRunControl
            stack.enter_context(patch.object(probe.probe_timing,'ProbeRunControl',
                side_effect=lambda duration,**kwargs:run_control(duration,clock_ns=fake.clock)))
            probe.run_probe(e0_session=s,headless=True,duration_seconds=10.1,show_3d_views='none',
                frame_callback=fake.callbacks.append)
        self.assertEqual(len(fake.callbacks),51)
        self.assertEqual(s.segments[0]['input_frames'],50)
        self.assertEqual(s.segments[0]['status'],'PREDICTED')
        summary=self.read(s)
        self.assertEqual(summary['received_frames'],52)
        self.assertEqual(s.frames[-1]['status'],'deadline_skip')
        self.assertEqual(summary['completed_frames'],51)
        names={x['name'] for x in self.read(s,'timing/diagnostics.json')['stage_milliseconds']}
        self.assertTrue({'receive.wait','receive.align','mediapipe.pose','mediapipe.face','depth_geometry',
            'fs3.feature_select','fs3.aggregate','fs3.scale','fs3.svm',
            'latency.first_input_to_prediction','latency.receive_to_frame_complete'}<=names)
        self.assertEqual(self.read(s,'timing/diagnostics.json')['ui_latency_status'],'NOT_MEASURED')
        fake.pipeline.stop.assert_called_once();fake.face.close.assert_called_once()

    def test_e0_does_not_enable_mixed_identifying_writers_or_legacy_rf(self):
        s=self.session()
        for option in [dict(csv_path='private.csv'),dict(performance_output_dir='private'),
                       dict(h9_model_path='old.json'),dict(timing_output_path='old.json')]:
            with self.assertRaises(ValueError):probe.run_probe(e0_session=s,**option)

    def test_duplicate_device_time_does_not_terminate_probe_in_any_mode(self):
        outputs=[]
        for mode in ('off','summary','detailed'):
            s=e0.E0Session(self.root/mode,self.model,self.scaler,clock_ns=self.clock,mode=mode)
            s.arm_segment()
            with ExitStack() as stack:
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(redirect_stderr(io.StringIO()))
                fake=SyntheticProbe(NS(enterContext=stack.enter_context),[0,100,100,200])
                stack.enter_context(patch.object(self.model,'predict',side_effect=AssertionError('rejected hold')))
                probe.run_probe(e0_session=s,frame_callback=fake.callbacks.append)
            self.assertEqual(len(fake.callbacks),4)
            self.assertEqual(s.segments[0]['status'],'INCOMPLETE')
            self.assertEqual(s.segments[0]['input_frames'],2)
            self.assertEqual(s.segments[0]['timestamp_failure'],'duplicate_timestamp')
            self.assertEqual(s.result_summary['segment_time_failures'],{'duplicate_timestamp':1})
            self.assertEqual(s.result_summary['status'],'COMPLETED')
            self.assertEqual(s.result_summary['prediction_attempts'],0)
            fake.pipeline.stop.assert_called_once()
            outputs.append([dict(f.result.features) for f in fake.callbacks])
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(outputs[1],outputs[2])

    def test_p99_submillisecond_precision_and_legacy_diagnostics_default(self):
        s=self.session()
        for ns in [100000,200000,300000,400000,500000]:s.timing.record_ns('tiny',ns)
        s.finish()
        stat=self.read(s,'timing/diagnostics.json')['stage_milliseconds'][0]
        self.assertAlmostEqual(stat['p50'],.3)
        self.assertAlmostEqual(stat['p95'],.48)
        self.assertAlmostEqual(stat['p99'],.496)
        legacy=e0.ProbeDiagnostics(self.root/'legacy',clock_ns=self.clock)
        legacy.record_ns('tiny',100000);legacy.finish(status='COMPLETED')
        data=json.loads((legacy.directory/'diagnostics.json').read_text())
        self.assertNotIn('p99',data['stage_milliseconds'][0])

    def test_bad_scaled_input_never_reaches_predict_and_no_result_is_reused(self):
        s=self.session();s.arm_segment()
        for i in range(30):self.observe(s,i+1,i*100)
        with patch.object(self.scaler,'transform',return_value=np.full((1,7),np.nan)), \
             patch.object(self.model,'predict',side_effect=AssertionError('invalid scaling')) as predict:
            with self.assertRaises(ValueError):self.observe(s,31,10000)
        predict.assert_not_called()
        self.assertFalse(s.segments[0]['prediction_success'])
        self.assertNotIn('prediction',s.segments[0])
        s.finish()
        self.assertEqual(self.read(s)['svm_attempts'],0)
        self.assertIsNone(self.read(s)['svm_success_percent'])

    def test_probe_error_publishes_partial_safe_logs_and_closes_sdk(self):
        s=self.session();s.arm_segment()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()));stack.enter_context(redirect_stderr(io.StringIO()))
            fake=SyntheticProbe(NS(enterContext=stack.enter_context),[0,100],keys=[-1,-1])
            fake.calculate.side_effect=RuntimeError('PRIVATE patient/source/path')
            with self.assertRaises(RuntimeError):probe.run_probe(e0_session=s,ui_poll=lambda:True)
        fake.pipeline.stop.assert_called_once();fake.face.close.assert_called_once()
        self.assertEqual(self.read(s)['status'],'FAILED')
        self.assertEqual(self.read(s)['frame_status_counts'],{'INCOMPLETE':1})
        self.assertNotIn('PRIVATE',(s.directory/'timing/diagnostics.json').read_text())

    def test_e0_is_observer_only_for_geometry_and_callbacks(self):
        outputs=[]
        for enabled in [False,True]:
            with ExitStack() as stack:
                stack.enter_context(redirect_stdout(io.StringIO()));stack.enter_context(redirect_stderr(io.StringIO()))
                fake=SyntheticProbe(NS(enterContext=stack.enter_context),[0,100,200])
                s=self.session('observer') if enabled else None
                probe.run_probe(frame_callback=fake.callbacks.append,e0_session=s)
                outputs.append([dict(f.result.features) for f in fake.callbacks])
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(self.read(s)['prediction_attempts'],0)

    def test_undefined_original_circular_mean_remains_ineligible(self):
        s=self.session();s.arm_segment()
        for i in range(30):self.observe(s,i+1,i*100,result(angle=90 if i%2 else -90))
        with patch.object(self.model,'predict',side_effect=AssertionError('undefined angle')):
            self.observe(s,31,10000)
        self.assertIn('face_axis_circular_mean_undefined',s.segments[0]['eligibility_reasons'])
        self.assertFalse(s.segments[0]['prediction_attempted'])

    def test_number_reused_with_new_timestamp_is_not_identical_child_reuse(self):
        s=self.session()
        for stamp in [1,2]:
            row=s.begin_receive();s.received(row,True,pair(child(1,stamp),child(1,stamp,stream='depth')),self.clock())
        self.assertEqual(row['raw_relations']['rgb']['classification'],'NUMBER_REUSED_DIFFERENT_TIMESTAMP')
        self.assertFalse(row['raw_relations']['rgb']['child_reused_while_other_advanced'])


if __name__ == '__main__':unittest.main()
