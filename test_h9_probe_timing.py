"""Prediction provenance/first-output/warmup tests with virtual inputs; no SDK."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h9_async_runtime as host
import h9_m0 as m0
import h9_probe_session as session
import probe_timing
import rf_experiment as rf
from test_h9_async_runtime import result
from test_h9_time_window import leaf_fixture_document


class H9ProbeTimingTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clock=host.VirtualMonotonicClock()
        self.metrics=probe_timing.ProbeMetrics(self.root/'timing.json',warmup_frames=10000,
            clock_ns=self.clock,cpu_clock_ns=lambda:0,memory_reader=lambda:{})
        self.path=self.root/'fixture.json'
        m0._write_new(self.path,leaf_fixture_document())
        self.enterContext(patch.object(rf.Forest,'fit',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(rf,'fit_models',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(m0.offline,'evaluate_samples',side_effect=AssertionError('no accuracy')))
        self.s=session.H9ProbeSession(self.path,metrics=self.metrics)
        self.metrics.begin_stream()

    def feed(self,*,missing_last=False):
        for i in range(81):
            self.clock.set_ms(i*50)
            self.s.accept(result((m0.FEATURE_ORDER[0],) if missing_last and i==80 else ()),
                frame_index=i+1,device_timestamp_ms=str(900000+i*50))

    def test_latest_used_common_valid_time_is_frozen_through_holding(self):
        self.feed(missing_last=True)
        prediction=self.s.snapshot()['display_prediction']
        self.assertEqual(prediction['source_last_input_host_ms'],'3950')
        self.assertEqual(prediction['source_last_input_frame_index'],80)
        self.assertEqual(self.s.runtime.engine._last_input.time,4000)
        self.clock.set_ms(5000);self.s.runtime.tick()
        held=self.s.snapshot()
        self.assertEqual(held['published_status'],'HOLDING')
        self.assertEqual(held['display_prediction'],prediction)
        self.clock.set_ms(5500)
        self.s.mark_displayed(self.s.snapshot())
        self.s.mark_displayed(self.s.snapshot())
        self.assertEqual(self.s.runtime.engine.rf_calls,1)
        report=self.metrics.finish()
        self.assertEqual(report['stage_milliseconds']['h9.latest_window_input_to_ui_submit']['p50'],1550.)
        self.assertEqual(report['stage_milliseconds']['h9.latest_window_input_to_ui_submit']['count'],1)
        self.assertEqual(report['h9_first_prediction']['collection_start_to_ready_ms'],4000.)
        self.assertEqual(report['h9_first_ui_submission']['collection_start_to_ui_ms'],5500.)
        self.assertEqual(report['h9_first_ui_submission']['source_last_input_host_ms'],'3950')

    def test_later_arrival_does_not_change_old_prediction_latency_origin(self):
        self.feed(missing_last=True)
        prediction=self.s.snapshot()['display_prediction']
        self.clock.set_ms(4100)
        self.s.accept(result(),frame_index=82,device_timestamp_ms='1')
        self.clock.set_ms(4500)
        snapshot=self.s.snapshot()
        self.assertEqual(snapshot['display_prediction'],prediction)
        self.s.mark_displayed(snapshot)
        self.s.runtime.manual_reset()
        self.assertIsNone(self.s.snapshot()['display_prediction'])
        report=self.metrics.finish()
        self.assertEqual(report['stage_milliseconds']['h9.latest_window_input_to_ui_submit']['p50'],550.)
        self.assertEqual(report['h9_first_ui_submission']['collection_start_to_ui_ms'],4500.)

    def test_first_output_retained_while_actual_inferences_warm_then_steady(self):
        self.feed()
        self.s.mark_displayed(self.s.snapshot())
        first_id=self.s.snapshot()['display_prediction']['prediction_id']
        for i in range(81,101):
            self.clock.set_ms(i*50)
            self.s.accept(result(),frame_index=i+1,device_timestamp_ms=str(i*50))
        self.s.mark_displayed(self.s.snapshot())
        report=self.metrics.finish()
        for stage in ('h9.aggregate','h9.m0_infer'):
            self.assertEqual(report['warmup_stage_milliseconds'][stage]['count'],1)
            self.assertEqual(report['stage_milliseconds'][stage]['count'],1)
        self.assertEqual(report['collection_stage_milliseconds']['h9.aggregate']['count'],4)
        self.assertEqual(report['h9_first_prediction']['prediction_id'],first_id)
        self.assertEqual(report['h9_first_ui_submission']['prediction_id'],first_id)
        self.assertEqual(report['h9_first_ui_submission']['collection_start_to_ui_ms'],4000.)
        self.assertEqual(self.s.runtime.engine.rf_calls,2)

    def test_first_ready_and_first_displayed_predictions_can_have_different_ids(self):
        self.feed()
        first_id=self.s.snapshot()['display_prediction']['prediction_id']
        for i in range(81,101):
            self.clock.set_ms(i*50)
            self.s.accept(result(),frame_index=i+1,device_timestamp_ms=str(i*50))
        displayed_id=self.s.snapshot()['display_prediction']['prediction_id']
        self.s.mark_displayed(self.s.snapshot())
        report=self.metrics.finish()
        self.assertNotEqual(first_id,displayed_id)
        self.assertEqual(report['h9_first_prediction']['prediction_id'],first_id)
        self.assertEqual(report['h9_first_prediction']['collection_start_to_ready_ms'],4000.)
        self.assertEqual(report['h9_first_ui_submission']['prediction_id'],displayed_id)
        self.assertEqual(report['h9_first_ui_submission']['stream_start_to_ui_ms'],5000.)


if __name__=='__main__':unittest.main()
