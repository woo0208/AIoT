"""Synthetic structure/SDK tests only: no D455, participant data or training."""
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
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from e0_fs3 import E0Session, H9_FEATURE_NAMES
from e0_panel import OperatorControl
from research_b import DemandPolicy
from research_b_report import classification, report, sha256
from test_e0_fs3 import Clock, estimators, result
from test_frame_provenance import child, pair
from test_h9_probe_integration import SyntheticProbe
import posture_geometry_probe as probe
import run_research_b as launcher


class ResearchBTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(SVC, 'fit', side_effect=AssertionError('no training')))
        self.enterContext(patch.object(StandardScaler, 'fit', side_effect=AssertionError('no training')))

    def run_fake(self, variant='B1', *, events=None, operations=None, mode='detailed',
                 missing=(), fail=None, stamps=None, invalid_at=(), no_policy=False, results=None):
        events = [0, 100, 200] if events is None else events
        operations = operations or {}
        clock = Clock()
        model, scaler = estimators()
        session = E0Session(self.root / str(len(list(self.root.iterdir()))), model, scaler,
                            mode=mode, clock_ns=clock, log_buffer_limit=4)
        policy = DemandPolicy(variant)
        control = OperatorControl(session)
        fake = SyntheticProbe(self, events)
        fake.calculate.return_value = result(missing=missing)
        if results is not None:
            fake.calculate.side_effect = results
        fake.cv.putText = Mock()
        fake.cv.FONT_HERSHEY_SIMPLEX = 0
        align = Mock(side_effect=lambda frames: frames)
        self.enterContext(patch.object(sys.modules['pyrealsense2'], 'align',
                                      return_value=NS(process=align)))
        calls = [0]
        original = fake.try_wait
        def receive(timeout):
            ready, frame = original(timeout)
            if ready and stamps is not None:
                stamp = stamps[calls[0]-1]
                frame.get_timestamp = lambda: stamp
            if ready and calls[0] in invalid_at:
                frame.get_depth_frame = lambda: None
            return ready, frame
        fake.pipeline.try_wait_for_frames.side_effect = receive
        def poll():
            calls[0] += 1
            clock.add_ms(1)
            if calls[0] > len(events):
                control.close()
            if calls[0] in operations:
                getattr(control, operations[calls[0]])()
            return control.poll()
        def key(delay):
            clock.add_ms(2)
            return next(fake.keys)
        fake.cv.waitKey.side_effect = key
        if fail == 'pose':
            fake.pose.detect_for_video.side_effect = RuntimeError('PRIVATE details')
        elif fail == 'face':
            fake.face.detect_for_video.side_effect = RuntimeError('PRIVATE details')
        elif fail == 'align':
            align.side_effect = RuntimeError('PRIVATE details')
        elif fail == 'preview':
            fake.cv.putText.side_effect = RuntimeError('PRIVATE details')
        with patch.object(model, 'predict', return_value=np.array([2])) as predict, \
                patch.object(scaler, 'transform', wraps=scaler.transform) as transform, \
                patch.object(session, 'accept', wraps=session.accept) as accept, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            if fail:
                with self.assertRaises(RuntimeError):
                    probe.run_probe(e0_session=session, ui_poll=poll, rgbd_policy=policy)
            else:
                probe.run_probe(e0_session=session, ui_poll=poll,
                                rgbd_policy=None if no_policy else policy)
            saved_calls = dict(predict=predict.call_args_list, transform=transform.call_args_list,
                               accept=accept.call_args_list)
        fake.pose.close.assert_called_once()
        fake.face.close.assert_called_once()
        fake.pipeline.stop.assert_called_once()
        fake.cv.destroyAllWindows.assert_called_once()
        return session, policy, fake, align, saved_calls

    def test_idle_skips_actual_align_pose_face_geometry_not_just_svm(self):
        session, policy, fake, align, calls = self.run_fake()
        align.assert_not_called()
        fake.pose.detect_for_video.assert_not_called()
        fake.face.detect_for_video.assert_not_called()
        fake.calculate.assert_not_called()
        self.assertFalse(calls['accept'] or calls['predict'])
        self.assertEqual(policy.counts['idle_skips'], 3)
        self.assertEqual(fake.cv.putText.call_count, 3)
        self.assertEqual(session.records, [])
        self.assertEqual(session.result_summary['evaluated_frames'], 0)
        rows = [json.loads(x) for x in (session.directory/'frames.jsonl').read_text().splitlines()]
        self.assertEqual([r['frame_id'] for r in rows], [1, 2, 3])
        self.assertTrue(all(r['status'] == 'b1_idle_skipped' and not r['measurement_available'] for r in rows))
        self.assertTrue(all('feature_success' not in r and 'aligned' not in r for r in rows))

    def test_start_immediately_restores_full_processing_cancel_returns_to_idle(self):
        s, p, fake, align, calls = self.run_fake(events=[0, 100, 200, 300, 400],
                                                operations={2: 'start', 4: 'cancel', 5: 'start'})
        self.assertEqual(align.call_count, 3)
        self.assertEqual(fake.pose.detect_for_video.call_count, 3)
        self.assertEqual(fake.face.detect_for_video.call_count, 3)
        self.assertEqual(fake.calculate.call_count, 3)
        self.assertEqual([c.args[2] for c in calls['accept']], [2, 3, 5])
        self.assertEqual([c.args[3] for c in calls['accept']], [900100., 900200., 900400.])
        self.assertEqual(p.transitions['IDLE->FULL'], 2)
        self.assertEqual(p.transitions['FULL->IDLE'], 1)
        self.assertTrue(all(x['status'] == 'INCOMPLETE' for x in s.segments))

    def test_full_ten_second_window_same_scaler_input_prediction_and_end_boundary(self):
        events = list(range(0, 10700, 100))
        values = []
        for mode in ('summary', 'detailed'):
            for variant in ('E0', 'B1'):
                s, p, fake, align, calls = self.run_fake(variant, events=events,
                    operations={3: 'start'}, mode=mode)
                self.assertEqual(s.segments[0]['input_frames'], 100)
                self.assertEqual(s.segments[0]['valid_frames'], 100)
                self.assertEqual(s.segments[0]['prediction'], 2)
                self.assertEqual(s.segments[0]['first_device_ms'], 900200.)
                self.assertEqual(len(calls['predict']), 1)
                values.append(calls['transform'][0].args[0])
                expected = len(events) if variant == 'E0' else 101
                self.assertEqual(align.call_count, expected)
                self.assertEqual(fake.pose.detect_for_video.call_count, expected)
                self.assertEqual(p.counts['demand_inputs'], 101)
                if variant == 'B1':
                    self.assertEqual(p.counts['idle_skips'], len(events)-101)
                    self.assertEqual(calls['accept'][-1].args[3], 910200.)
        for x in values[1:]:
            np.testing.assert_array_equal(x, values[0])

    def test_default_e0_and_observed_e0_both_process_every_idle_frame(self):
        for absent in (False, True):
            s, _, fake, align, calls = self.run_fake('E0', no_policy=absent)
            self.assertEqual(align.call_count, 3)
            self.assertEqual(fake.pose.detect_for_video.call_count, 3)
            self.assertEqual(fake.face.detect_for_video.call_count, 3)
            self.assertEqual(len(calls['accept']), 3)
            self.assertEqual(s.result_summary['completed_frames'], 3)

    def test_missing_current_features_are_not_filled_or_predicted(self):
        s, _, _, _, calls = self.run_fake(events=list(range(0, 10300, 100)),
            operations={2:'start'}, missing=(0,))
        self.assertEqual(s.segments[0]['status'], 'INELIGIBLE')
        self.assertEqual(s.segments[0]['valid_frames'], 0)
        self.assertEqual(s.segments[0]['input_frames'], 100)
        self.assertFalse(calls['predict'])
        self.assertTrue(all(c.args[1].features[H9_FEATURE_NAMES[0]] is None for c in calls['accept']))

    def test_valid_to_idle_to_missing_does_not_reuse_a_previous_feature(self):
        s, _, fake, _, calls = self.run_fake(events=[0,100,200,300],
            operations={1:'start',3:'cancel',4:'start'},
            results=[result(),result(),result(missing=(0,))])
        self.assertEqual(len(calls['accept']),3)
        self.assertIsNone(calls['accept'][-1].args[1].features[H9_FEATURE_NAMES[0]])
        self.assertEqual(fake.cv.putText.call_count,1)
        self.assertFalse(calls['predict'])
        self.assertEqual(s.records,[])
        rows=[json.loads(x) for x in (s.directory/'frames.jsonl').read_text().splitlines()]
        self.assertFalse(rows[-1]['measurement_available'])

    def test_duplicate_device_time_cancels_then_manual_restart_uses_fresh_window(self):
        s, p, fake, _, calls = self.run_fake(events=[0,100,200,300,400],
            operations={1:'start',4:'start'}, stamps=[100.,100.,200.,300.,400.])
        self.assertEqual(s.segments[0]['reason'], 'timestamp_invalid')
        self.assertEqual(s.segments[1]['first_device_ms'], 300.)
        self.assertEqual(p.counts['idle_skips'], 1)
        self.assertFalse(calls['predict'])
        times = [c.args[1] for c in fake.pose.detect_for_video.call_args_list]
        self.assertEqual(times, [100,101,300,400])

    def test_invalid_pair_is_not_replaced_by_prior_geometry(self):
        s, p, fake, align, calls = self.run_fake(operations={1:'start'}, invalid_at=(2,))
        self.assertEqual(align.call_count, 3)
        self.assertEqual(fake.calculate.call_count, 2)
        self.assertEqual(len(calls['accept']), 2)
        self.assertEqual(s.result_summary['frame_status_counts']['invalid_pair'], 1)
        self.assertEqual(p.counts['full_completed'], 2)

    def test_timeout_does_not_make_an_idle_or_full_measurement(self):
        s, p, fake, align, _ = self.run_fake(events=[0,None,3000], operations={1:'start'})
        self.assertEqual(align.call_count, 2)
        self.assertEqual(p.counts['selected'], 2)
        self.assertEqual(s.result_summary['frame_status_counts']['timeout'], 1)

    def test_stage_and_preview_errors_fail_safely_and_clean_sdk(self):
        for fail in ('pose', 'face', 'align', 'preview'):
            s, _, _, _, calls = self.run_fake(fail=fail,
                operations={} if fail == 'preview' else {1:'start'})
            self.assertEqual(s.result_summary['status'], 'FAILED')
            self.assertFalse(calls['predict'])
            self.assertEqual(s.records, [])
            self.assertNotIn('PRIVATE', (s.directory/'summary.json').read_text())

    def test_report_separates_preview_throughput_and_full_work_and_keeps_percentiles(self):
        s, _, _, _, _ = self.run_fake(operations={2:'start'})
        r = report(s.directory)
        self.assertEqual(r['stages_ms']['mediapipe.pose']['count'], 2)
        self.assertEqual(r['stages_ms']['receive.align']['count'], 2)
        self.assertEqual(r['counts']['idle_completed'], 1)
        self.assertGreater(r['completed_delivery_fps'], r['fully_processed_fps'])
        self.assertEqual(r['stages_ms']['research_b.idle.receive_to_complete']['p99'], 2.)
        self.assertEqual(r['classification']['status'], 'NOT_MEASURED')
        self.assertEqual(r['performance_improvement'], 'UNVERIFIED')
        self.assertEqual(r['host_observed_number_gaps']['rgb']['status'], 'NOT_MEASURED')

    def test_unsafe_extra_consumers_and_unmeasured_mode_rejected_before_hardware(self):
        model, scaler = estimators()
        s = E0Session(None, model, scaler, mode='off')
        with self.assertRaises(ValueError):
            probe.run_probe(e0_session=s, rgbd_policy=DemandPolicy('B1'))
        s = E0Session(self.root/'guard', model, scaler, clock_ns=Clock())
        for options in (dict(frame_callback=Mock()), dict(pyvista_view=True),
                        dict(show_3d_views='side'), dict(e0_ui_variant='E1'), dict(f1_live=True)):
            with self.assertRaises(ValueError):
                probe.run_probe(e0_session=s, rgbd_policy=DemandPolicy('B1'), **options)
        used=DemandPolicy('B1');used.counts['selected']=1
        with self.assertRaises(ValueError):
            probe.run_probe(e0_session=s,rgbd_policy=used)
        for invalid in (None, object()):
            with self.assertRaises(ValueError):
                probe.run_probe(e0_session=invalid,rgbd_policy=DemandPolicy('B1'))
        stored=E0Session(self.root/'stored',model,scaler,clock_ns=Clock(),input_scope='stored_features')
        with self.assertRaises(ValueError):
            probe.run_probe(e0_session=stored,rgbd_policy=DemandPolicy('B1'))

    def test_gap_counts_exclude_intentional_skips_and_uncertain_edges_invalidate_rate(self):
        model, scaler = estimators()
        for anomaly in (None, 'duplicate', 'reset', 'domain', 'missing'):
            s = E0Session(self.root/('gaps_'+str(anomaly)), model, scaler, clock_ns=Clock())
            p = DemandPolicy('B1')
            for i, number in enumerate((10,11,15)):
                if i == 2:
                    number = 11 if anomaly == 'duplicate' else 1 if anomaly == 'reset' else number
                stamp = 100+i*100
                domain = 'system_time' if i == 2 and anomaly == 'domain' else 'hardware_clock'
                color = None if i == 2 and anomaly == 'missing' else child(number,stamp,domain=domain)
                row=s.begin_receive()
                s.received(row,True,pair(color,child(number,stamp,stream='depth',uid=2)),s.clock_ns())
                self.assertFalse(p.select(s,row))
            stats=p.summary()['raw_frame_number_gaps']['rgb']
            if anomaly is None:
                self.assertEqual(stats['gaps'], 3)
                self.assertEqual(stats['observed_number_gap_fraction'], 3/5)
                self.assertEqual(stats['sensor_missing_rate'], 'NOT_MEASURED')
            else:
                self.assertEqual(stats['status'], 'NOT_MEASURED')
                self.assertIsNone(stats['observed_number_gap_fraction'])
            s.finish()


class ResearchBReportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root/'summary.json').write_text('{}')

    def fixture(self, predictions, labels):
        rows = [dict(segment_index=i+1, prediction=p, prediction_success=p is not None)
                for i,p in enumerate(predictions)]
        (self.root/'segments.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
        document=dict(summary_sha256=sha256(self.root/'summary.json'), source='independent_observation',
            segments=[dict(segment_index=i+1,label=y,confirmed=True) for i,y in enumerate(labels)])
        path=self.root/'labels.json'
        path.write_text(json.dumps(document))
        return path, document

    def test_complete_fixed_six_metrics_and_unscored_coverage(self):
        path, _ = self.fixture(list(range(6))+[None], list(range(6))+[0])
        actual=classification(self.root,path)
        for name in ('accuracy','macro_f1','p0_recall','p1_recall'):
            self.assertEqual(actual[name],100.)
        self.assertEqual(actual['prediction_coverage'],6/7)
        self.assertEqual(actual['unscored_segments'],1)

    def test_missing_class_and_empty_predictions_not_fabricated_as_complete(self):
        for predictions,labels in (([0,0],[0,1]), ([None],[0]), ([],[])):
            path,_=self.fixture(predictions,labels)
            actual=classification(self.root,path)
            self.assertEqual(actual['status'],'INCOMPLETE')
            self.assertIsNone(actual['macro_f1'])
            if not predictions or predictions==[None]:
                self.assertIsNone(actual['accuracy'])
            else:
                self.assertEqual(actual['accuracy'],50.)
                self.assertEqual(actual['p1_recall'],0.)

    def test_no_labels_no_accuracy_and_wrong_bindings_or_unconfirmed_labels_rejected(self):
        self.assertEqual(classification(self.root)['status'],'NOT_MEASURED')
        for key,value in (('summary_sha256','0'*64),('source','schedule')):
            path,document=self.fixture([0],[0]);document[key]=value
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):classification(self.root,path)
        for change in ('unconfirmed','duplicate','missing','bad_label'):
            path,document=self.fixture([0],[0])
            if change=='unconfirmed':document['segments'][0]['confirmed']=False
            elif change=='duplicate':document['segments']*=2
            elif change=='missing':document['segments']=[]
            else:document['segments'][0]['label']=6
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):classification(self.root,path)


class ResearchBLauncherTests(unittest.TestCase):
    def test_check_only_both_variants_never_create_output_or_open_camera(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);binding=root/'binding.json'
            binding.write_text(json.dumps(dict(path='artifact.pkl', artifact_sha256='a'*64,
                feature_ids=['F1','F3','F4','F5','F6','F7','F8'],model_sha256='b'*64,scaler_sha256='c'*64)))
            with patch.object(launcher,'ROOT',root), patch.object(launcher,'load_fs3',return_value=(None,None,dict(artifact_sha256='a'*64))), \
                    patch.object(launcher,'environment_record'), patch.object(launcher,'run_probe') as live, \
                    patch.object(launcher,'run_bound_probe') as bound, redirect_stdout(io.StringIO()):
                for variant in ('E0','B1'):
                    self.assertEqual(launcher.main(['--check-only','--binding',str(binding),
                        '--variant',variant]),0)
                self.assertEqual(list(root.iterdir()),[binding])
                live.assert_not_called();bound.assert_not_called()


if __name__ == '__main__':
    unittest.main()
