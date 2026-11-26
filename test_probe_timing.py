"""Deterministic host instrumentation checks; no SDK/camera/model fitting."""

import json
from pathlib import Path
import tempfile
import unittest

import probe_timing as timing


class ProbeMetricsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.ns = self.cpu = 0
        self.metrics = timing.ProbeMetrics(self.root/'timing.json',warmup_frames=1,
            clock_ns=lambda:self.ns,cpu_clock_ns=lambda:self.cpu,
            memory_reader=lambda:dict(rss_bytes=1234,private_bytes=567,os_peak_rss_bytes=1500))

    def test_stage_percentiles_warmup_fps_cpu_and_memory(self):
        m = self.metrics
        m.start();m.begin_stream()
        first = m.input_received(1)
        with m.stage('pose',1):self.ns += 10_000_000
        m.ui_submitted(first,1);m.frame_completed(first,1)
        for i,ms in enumerate((20,40),2):
            token = m.input_received(i)
            with m.stage('pose',i):self.ns += ms*1_000_000
            m.ui_submitted(token,i);m.frame_completed(token,i)
        m.receive_timeout()
        token=m.input_received(5);m.invalid_pair(token)
        self.ns=1_000_000_000;self.cpu=500_000_000
        report=m.finish()
        self.assertFalse(m._thread.is_alive())
        self.assertEqual(report['stage_milliseconds']['pose'],dict(count=2,p50=30.,p95=39.,maximum=40.))
        self.assertEqual(report['warmup_stage_milliseconds']['pose']['count'],1)
        self.assertEqual(report['delivered_input_fps'],4.)
        self.assertEqual(report['processed_fps'],3.)
        self.assertEqual(report['unique_source_frames'],4)
        self.assertEqual(report['counts']['source_frame_gaps'],1)
        self.assertEqual(report['counts']['receive_timeouts'],1)
        self.assertEqual(report['counts']['missing_color_or_depth'],1)
        self.assertEqual(report['unfinished_processing_frames'],0)
        summary=report['process_resource_summary']['stream']
        self.assertEqual(summary['cpu_one_core_percent']['maximum'],50.)
        self.assertEqual(summary['rss_bytes']['p50'],1234.)
        self.assertEqual(json.loads(m.output_path.read_text())['kind'],'engineering-probe-host-timing')
        self.assertIsNone(m.finish())

    def test_no_overwrite_including_race_at_publication(self):
        self.metrics.output_path.write_text('original')
        with self.assertRaises(FileExistsError):
            timing.ProbeMetrics(self.metrics.output_path)
        with self.assertRaises(FileExistsError):self.metrics.finish()
        self.assertEqual(self.metrics.output_path.read_text(),'original')

    def test_unknown_duplicate_regressed_source_and_partial_failure_are_explicit(self):
        m=self.metrics;m.begin_stream()
        for source in (5,5,2,None):
            token=m.input_received(source)
            if source is not None:m.frame_completed(token,1)
        self.ns=1_000_000
        report=m.finish(error=ValueError('synthetic downstream'),cleanup_errors=[RuntimeError('timer stop')])
        self.assertIsNone(report['unique_source_frames'])
        self.assertEqual(report['counts']['source_duplicate_ids'],1)
        self.assertEqual(report['counts']['source_counter_regressions'],1)
        self.assertEqual(report['unfinished_processing_frames'],1)
        self.assertEqual(report['error'],'synthetic downstream')
        self.assertEqual(report['cleanup_errors'],['timer stop'])

    def test_memory_failure_is_reported_and_native_reader_is_process_memory(self):
        def fail():raise OSError('synthetic memory failure')
        self.metrics.memory_reader=fail
        report=self.metrics.finish()
        self.assertIn('memory_error',report['process_resource_samples'][0])
        self.assertEqual(report['process_resource_summary']['shutdown']['rss_bytes']['count'],0)
        native=timing.process_memory()
        self.assertGreater(native['rss_bytes'],0)

    def test_h9_collection_warmup_and_steady_are_independent_of_frame_warmup(self):
        m=self.metrics
        with m.h9_stage('h9.aggregate',collecting=True):self.ns+=2_000_000
        with m.h9_stage('h9.aggregate'):self.ns+=10_000_000
        # A full aggregation can occur without an eligible inference.
        with m.h9_stage('h9.aggregate'):self.ns+=30_000_000
        with m.h9_stage('h9.m0_infer'):self.ns+=20_000_000
        with m.h9_stage('h9.m0_infer'):self.ns+=40_000_000
        report=m.finish()
        self.assertEqual(report['collection_stage_milliseconds']['h9.aggregate']['p50'],2.)
        self.assertEqual(report['warmup_stage_milliseconds']['h9.aggregate']['p50'],10.)
        self.assertEqual(report['warmup_stage_milliseconds']['h9.m0_infer']['p50'],20.)
        self.assertEqual(report['stage_milliseconds']['h9.aggregate']['p50'],30.)
        self.assertEqual(report['stage_milliseconds']['h9.m0_infer']['p50'],40.)
        self.assertEqual(report['h9_full_window_stage_calls'],{'h9.aggregate':2,'h9.m0_infer':2})
        self.assertEqual(report['h9_warmup_calls_per_stage'],1)
        self.assertIsNone(report['h9_first_prediction'])
        self.assertIsNone(report['h9_first_ui_submission'])

    def test_zero_h9_warmup_and_invalid_policy(self):
        for value in (-1,True,1.5):
            with self.assertRaises(ValueError):timing.ProbeMetrics(self.root/'invalid.json',h9_warmup_calls=value)
        m=timing.ProbeMetrics(self.root/'zero.json',h9_warmup_calls=0,
            clock_ns=lambda:self.ns,cpu_clock_ns=lambda:0,memory_reader=lambda:{})
        with m.h9_stage('h9.m0_infer'):self.ns+=1_000_000
        report=m.finish()
        self.assertEqual(report['stage_milliseconds']['h9.m0_infer']['count'],1)
        self.assertNotIn('h9.m0_infer',report['warmup_stage_milliseconds'])

    def test_deadline_is_optional_monotonic_and_validated(self):
        for value in (0,-1,float('inf'),float('nan'),True):
            with self.assertRaises(ValueError):timing.ProbeRunControl(value)
        optional=timing.ProbeRunControl(clock_ns=lambda:self.ns)
        optional.start();self.ns=1_000_000_000_000
        self.assertFalse(optional.deadline_reached())
        self.ns=0
        control=timing.ProbeRunControl(90,clock_ns=lambda:self.ns)
        control.start()
        self.ns=89_999_999_999;self.assertFalse(control.deadline_reached())
        self.ns=90_000_000_000;self.assertTrue(control.deadline_reached())
        control.stop('q')
        self.assertEqual(control.summary()['reason'],'duration_elapsed')
        self.assertEqual(control.summary()['deadline_overrun_seconds'],0.)

    def baseline_fixture(self,total,*,reason='duration_elapsed',error=None,attempts=None):
        self.ns=0
        m=timing.ProbeMetrics(self.root/f'baseline_{total}_{reason}_{error}.json',warmup_frames=150,h9_warmup_calls=5,
            clock_ns=lambda:self.ns,cpu_clock_ns=lambda:0,memory_reader=lambda:{},
            metadata=dict(h9_model={'fixture':'synthetic structural counter test'}))
        m.begin_stream()
        for i in range(attempts if attempts is not None else total):
            with m.h9_stage('h9.m0_infer'):self.ns+=1_000_000
            if i<total:
                m.h9_prediction_ready(dict(status='PREDICTED',display_prediction=dict(prediction_id=str(i),
                    source_last_input_host_ms='0',accumulation_start_host_ms='0')))
        self.ns=90_000_000_000
        return m.finish(error=error,termination=dict(reason=reason,requested_duration_seconds=90))

    def test_59_predictions_block_60_allow_and_raw_statistics_survive(self):
        blocked=self.baseline_fixture(64)
        self.assertEqual(blocked['h9_inferences'],dict(total_successful=64,warmup_excluded=5,post_warmup=59))
        self.assertFalse(blocked['baseline_interpretation']['eligible'])
        self.assertIn('insufficient_post_warmup_m0_inferences',blocked['baseline_interpretation']['reasons'])
        self.assertIsNone(blocked['baseline_stage_milliseconds'])
        self.assertEqual(blocked['stage_milliseconds']['h9.m0_infer']['count'],59)
        allowed=self.baseline_fixture(65)
        self.assertTrue(allowed['baseline_interpretation']['eligible'])
        self.assertEqual(allowed['baseline_stage_milliseconds']['h9.m0_infer']['count'],60)
        attempts=self.baseline_fixture(0,attempts=65)
        self.assertEqual(attempts['h9_inferences']['total_successful'],0)
        self.assertFalse(attempts['baseline_interpretation']['eligible'])

    def test_early_exit_or_error_blocks_even_with_enough_predictions(self):
        early=self.baseline_fixture(65,reason='q')
        self.assertFalse(early['baseline_interpretation']['eligible'])
        self.assertEqual(early['termination']['reason'],'q')
        error=self.baseline_fixture(65,error=ValueError('synthetic'))
        self.assertEqual(error['termination']['reason'],'error')
        self.assertIn('runtime_error',error['baseline_interpretation']['reasons'])
        self.assertIsNotNone(error['stage_milliseconds']['h9.m0_infer']['p95'])


if __name__=='__main__':unittest.main()
