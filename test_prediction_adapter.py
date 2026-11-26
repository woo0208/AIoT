"""Synthetic presentation tests only; no camera or model inference."""
import copy
import unittest
from unittest.mock import patch

import prediction_adapter as ui


class PredictionAdapterTests(unittest.TestCase):
    def test_all_six_labels_and_states(self):
        views = ui.demo_views()
        new = [v for v in views if v['status'] == 'NEW']
        self.assertEqual([v['class_id'] for v in new], [f'P{i}' for i in range(6)])
        self.assertEqual([v['posture_name'] for v in new], list(ui.KOREAN6))
        self.assertEqual({v['status'] for v in views}, set(ui.STATES))
        self.assertTrue(all('SYNTHETIC DEMO' in v['banner'] for v in views))

    def test_all_state_to_state_transitions_and_input_unchanged(self):
        events = {e['status']: e for e in ui.synthetic_events()}
        events['NEW'] = events['PREDICTED']
        for before in ui.STATES:
            for after in ui.STATES:
                with self.subTest(before=before, after=after):
                    adapter = ui.PredictionAdapter(ui.FORMAL6, synthetic=True)
                    adapter.adapt(events[before])
                    event = copy.deepcopy(events[after])
                    original = copy.deepcopy(event)
                    view = adapter.adapt(event)
                    expected = 'HOLDING' if before in ('NEW', 'HOLDING') and after == 'NEW' else after
                    self.assertEqual(view.status, expected)
                    self.assertEqual(event, original)

    def test_age_zero_repeat_and_hidden_stale(self):
        adapter = ui.PredictionAdapter(ui.FORMAL6)
        event = next(e for e in ui.synthetic_events() if e['status'] == 'PREDICTED')
        self.assertIn('0.0 ms', adapter.adapt(event).lines()[-1])
        self.assertEqual(adapter.adapt(event).status, 'HOLDING')
        self.assertIsNone(adapter.adapt(dict(event, status='STALE')).class_id)
        self.assertEqual(adapter.adapt(event, model_available=False).status, 'MODEL_UNAVAILABLE')

    def test_three_five_class_stay_in_declared_label_space(self):
        for order in (('normal', 'neck', 'back'), ui.FORMAL6[:5]):
            event = dict(status='PREDICTED', last_prediction_age_ms=0,
                         display_prediction=dict(prediction_id='1', prediction_index=0, prediction_label=order[0]))
            self.assertEqual(ui.PredictionAdapter(order).adapt(event).posture_name, order[0])
            self.assertEqual(ui.PredictionAdapter(order).adapt(event).class_id, '0')

    def test_no_primary5_conversion_or_invalid_age(self):
        event = next(e for e in ui.synthetic_events() if e['status'] == 'PREDICTED')
        with self.assertRaises(ValueError):
            ui.PredictionAdapter(('other', *ui.FORMAL6[1:])).adapt(event)
        for age in (-1, float('nan')):
            with self.assertRaises(ValueError):
                ui.PredictionAdapter(ui.FORMAL6).adapt(dict(event, last_prediction_age_ms=age))

    def test_probe_opt_in_bypasses_hardware(self):
        import posture_geometry_probe as probe
        with patch.object(probe, 'run_probe') as hardware, patch.object(ui, 'run_synthetic_demo') as demo:
            self.assertEqual(probe.main(['--six-class-synthetic-demo']), 0)
        hardware.assert_not_called()
        demo.assert_called_once()

    def test_existing_three_class_display_unchanged(self):
        from types import SimpleNamespace as NS
        import posture_geometry_probe as probe
        import f1_demo_rf
        live = NS(result=object())
        for label in f1_demo_rf.CLASS_LABELS:
            model = NS(predict=lambda value: NS(status=f1_demo_rf.PREDICTION_AVAILABLE, label=label))
            state = probe.RFDemoModelState(probe.RF_MODEL_LOADED, model, 'SYNTHETIC', 'fixture')
            view = probe.rf_demo_frame(state, live)
            self.assertEqual(view.label, label)
            self.assertEqual(view.prediction, probe.RF_DISPLAY_LABELS[label])

    def test_existing_async_five_class_snapshot_never_mutated_or_promoted(self):
        import h9_async_runtime as host
        import h9_m0 as m0
        from test_h9_time_window import leaf_fixture_document
        from test_h9_async_runtime import result
        clock = host.VirtualMonotonicClock()
        runtime = host.H9AsyncRuntime(m0.model_from_document(leaf_fixture_document()), clock_ns=clock)
        for i in range(41):
            clock.set_ms(i * 100)
            runtime.observe_geometry(result(), frame_index=i+1, recording_id='SYNTHETIC', subject='SYNTHETIC',
                                     device_timestamp_ms=i*100)
        snapshot = runtime.snapshot()
        original = copy.deepcopy(snapshot)
        calls = runtime.engine.rf_calls
        view = ui.PredictionAdapter(m0.CLASS_ORDER).adapt(snapshot)
        self.assertEqual(view.posture_name, m0.CLASS_ORDER[0])
        self.assertEqual(snapshot, original)
        self.assertEqual(runtime.engine.rf_calls, calls)
        self.assertNotEqual(view.class_id, 'P0')
