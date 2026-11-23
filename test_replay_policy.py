"""Structural gates/H9 denominator/CPU telemetry tests; no camera or fitting."""
import unittest
from unittest.mock import patch
import numpy as np
from replay_policy import ReplayGate, cpu_counters, counter_delta
import test_e0_replay as fixtures
import posture_geometry_probe as probe


class GateTests(unittest.TestCase):
    def test_fixed_N1_2_3_5_exact_schedule(self):
        rgb=np.zeros((36,64,3),dtype=np.uint8)
        for n in (1,2,3,5):
            gate=ReplayGate('Fixed',interval=n);selected=[]
            for i in range(1,16):
                decision=gate.select(rgb,float(i*66),i)
                if decision['full']:selected.append(i);gate.completed(float(i*66),i,True)
            self.assertEqual(selected,list(range(1,16,n)))

    def test_adaptive_no_SVM_confidence_has_bounded_refresh(self):
        rgb=np.zeros((36,64,3),dtype=np.uint8);g=ReplayGate('Adaptive')
        self.assertTrue(g.select(rgb,0.,1)['full']);g.completed(0.,1,None)
        self.assertFalse(g.select(rgb,66.,2)['full'])
        self.assertEqual(g.select(rgb,201.,4)['reason'],'MAX_SOURCE_INTERVAL')

    def test_motion_triggers_before_expensive_processing(self):
        g=ReplayGate('Adaptive');zero=np.zeros((36,64,3),dtype=np.uint8)
        g.select(zero,0.,1);g.completed(0.,1,True)
        self.assertEqual(g.select(np.full_like(zero,255),66.,2)['reason'],'RGB_CHANGE')

    def test_cumulative_RGB_reference_is_last_full_not_previous_skip(self):
        g=ReplayGate('Adaptive',change_threshold=.02);a=np.zeros((36,64,3),dtype=np.uint8)
        g.select(a,0.,1);g.completed(0.,1,True)
        self.assertFalse(g.select(a+3,50.,2)['full'])
        self.assertTrue(g.select(a+6,100.,3)['full'])

    def test_low_quality_forces_reacquisition(self):
        g=ReplayGate('Adaptive');a=np.zeros((36,64,3),dtype=np.uint8)
        g.select(a,0.,1);g.completed(0.,1,False)
        d=g.select(a,66.,2);self.assertTrue(d['full']);self.assertEqual(d['reason'],'PRIOR_OBSERVATION_INVALID')

    def test_fixed_held_then_stale_never_claim_new_measurement(self):
        g=ReplayGate('Fixed',interval=5);a=np.zeros((36,64,3),dtype=np.uint8)
        g.select(a,0.,1);g.completed(0.,1,True)
        self.assertEqual(g.select(a,66.,2)['measurement_status'],'HELD')
        self.assertEqual(g.select(a,267.,5)['measurement_status'],'STALE')

    def test_invalid_previous_observation_is_stale(self):
        g=ReplayGate('Fixed',interval=3);a=np.zeros((36,64,3),dtype=np.uint8)
        g.select(a,0.,1);g.completed(0.,1,False)
        self.assertEqual(g.select(a,66.,2)['measurement_status'],'STALE')

    def test_reset_demands_full_even_off_fixed_schedule(self):
        g=ReplayGate('Fixed',interval=5);a=np.zeros((36,64,3),dtype=np.uint8)
        g.select(a,0.,1);g.completed(0.,1,True);g.invalidate()
        self.assertTrue(g.select(a,66.,2)['full'])

    def test_RGB_shape_change_full_and_new_reference(self):
        g=ReplayGate('Adaptive');a=np.zeros((36,64,3),dtype=np.uint8)
        g.select(a,0.,1);g.completed(0.,1,True)
        self.assertEqual(g.select(a[:10],66.,2)['reason'],'RGB_REFERENCE_UNAVAILABLE')

    def test_parameters_validated_not_tuned(self):
        for kw in (dict(method='bad'),dict(interval=4),dict(change_threshold=float('nan')),dict(max_interval_ms=0)):
            with self.subTest(kw=kw),self.assertRaises(ValueError):ReplayGate(**kw)

    def test_CPU_counters_monotonic_raw_cycles_and_gate_cost(self):
        a=cpu_counters();b=cpu_counters();delta=counter_delta(a,b)
        self.assertTrue(all(v>=0 for v in delta.values()))
        g=ReplayGate('Adaptive');d=g.select(np.zeros((36,64,3),dtype=np.uint8),0.,1)
        self.assertGreater(d['gate_wall_ns'],0);self.assertIn('process_ns',d['gate_cpu'])


class GateIntegration(unittest.TestCase):
    setUp=fixtures.ReplayContracts.setUp
    integrate=fixtures.ReplayContracts.integrate

    def run_gate(self,n,stamps,method='Fixed'):
        fake,r,s=self.integrate(stamps,arm=True);r.gate=ReplayGate(method,interval=n)
        predict=self.enterContext(patch.object(s.model,'predict',return_value=np.asarray([0])))
        probe.run_probe(e0_session=s,replay_input=r,headless=True,show_3d_views='none')
        return fake,r,s,predict

    def test_fixed2_preserves_50percent_boundary_and_original_SVM(self):
        fake,r,s,predict=self.run_gate(2,list(range(0,10100,100)))
        segment=s.segments[0]
        self.assertEqual(segment['input_frames'],100);self.assertEqual(segment['valid_frames'],50)
        self.assertEqual(segment['coverage'],.5);self.assertTrue(segment['prediction_success'])
        predict.assert_called_once();self.assertEqual(fake.pose.detect_for_video.call_count,51)
        self.assertEqual(sum(x['status']!='completed' for x in r.rows),50)
        for row in r.rows:
            if not row['full_inference']:
                self.assertFalse(row['h9_common_success']);self.assertNotIn('feature_vector_sha256',row)

    def test_fixed3_coverage_denominator_contains_skipped_inputs(self):
        fake,r,s,predict=self.run_gate(3,list(range(0,10100,100)))
        segment=s.segments[0]
        self.assertEqual(segment['input_frames'],100);self.assertEqual(segment['valid_frames'],34)
        self.assertAlmostEqual(segment['coverage'],.34);self.assertFalse(segment['eligible'])
        self.assertIn('common_coverage<0.5',segment['eligibility_reasons']);predict.assert_not_called()

    def test_fixed5_both_original_support_rules_fail(self):
        fake,r,s,predict=self.run_gate(5,list(range(0,10100,100)))
        segment=s.segments[0]
        self.assertEqual(segment['input_frames'],100);self.assertEqual(segment['valid_frames'],20)
        self.assertIn('common_valid_frames<30',segment['eligibility_reasons'])
        self.assertIn('common_coverage<0.5',segment['eligibility_reasons']);predict.assert_not_called()

    def test_adaptive_static_input_skips_and_reaches_bounded_refresh(self):
        fake,r,s,predict=self.run_gate(1,[0,66,132,201,267],method='Adaptive')
        self.assertEqual(fake.pose.detect_for_video.call_count,2)
        self.assertEqual(fake.face.detect_for_video.call_count,2)
        self.assertEqual(fake.calculate.call_count,2)
        self.assertEqual(s.segments[0]['input_frames'],5)
        self.assertEqual(s.segments[0]['valid_frames'],2)
        self.assertEqual(r.rows[3]['gate']['reason'],'MAX_SOURCE_INTERVAL')
        self.assertEqual(s.result_summary['completed_frames'],2)

    def test_report_separates_deliberate_skips_from_drops_and_valid_support(self):
        fake,r,s,predict=self.run_gate(1,[0,66,132,201,267],method='Adaptive')
        with patch('e0_replay._stored_image_counts',return_value=None):report=r.report(s)
        self.assertEqual(report['input_frames'],5);self.assertEqual(report['handled_frames'],5)
        self.assertEqual(report['processed_frames'],2);self.assertEqual(report['skipped_frames'],3)
        self.assertEqual(report['dropped_or_rejected_frames'],0)
        self.assertEqual(report['h9_support']['valid_frames'],2)
        self.assertEqual(report['h9_support']['coverage'],.4)
        self.assertEqual(report['rss']['sample_count'],5)
        self.assertEqual(report['all_input_latency_ms']['processing_ms']['count'],5)
        self.assertEqual(report['latency_ms']['processing_ms']['count'],2)
        self.assertEqual(report['gate_cost']['wall_ms']['count'],5)
        self.assertIn('process_cycles',report['cpu_check']['stream_counters'])


if __name__=='__main__':unittest.main()
