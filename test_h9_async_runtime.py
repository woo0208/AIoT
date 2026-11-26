"""No camera/training: synthetic geometry, host clocks, callbacks and timer thread."""

import csv
from dataclasses import replace
from decimal import Decimal
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import h9_async_runtime as host
import h9_m0 as m0
import h9_time_window as window
import rf_experiment as rf
import posture_geometry as geometry
from test_h9_csv_replay import FIELDS, frame, csv_row
from test_h9_time_window import leaf_fixture_document


def result(missing=()):
    values={name: None if name in missing else j/10 for j,name in enumerate(m0.FEATURE_ORDER)}
    values[m0.FEATURE_ORDER[2]]=0.0
    return geometry.GeometryResult({}, {}, values)


class H9AsyncRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document=leaf_fixture_document()

    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(rf.Forest,'fit',side_effect=AssertionError('no fit')))
        self.enterContext(patch.object(rf,'fit_models',side_effect=AssertionError('no fit')))
        self.enterContext(patch.object(m0.offline,'evaluate_samples',side_effect=AssertionError('no accuracy')))
        self.model=m0.model_from_document(self.document)
        self.clock=host.VirtualMonotonicClock()
        self.outputs=[]
        self.runtime=host.H9AsyncRuntime(self.model,clock_ns=self.clock,sink=self.outputs.append)

    def observe(self,index,t,*,device=None,segment=None,label=None,missing=()):
        self.clock.set_ms(t)
        return self.runtime.observe_geometry(result(missing),frame_index=index,
                  recording_id='synthetic-recording',subject='synthetic-subject',
                  device_timestamp_ms=str(device if device is not None else Decimal('900000000000')+Decimal(str(t))),
                  timestamp_utc='unknown',segment_id=segment,source_label=label)

    def feed(self,count=41):
        for i in range(count):self.observe(i+1,i*100)

    def test_geometry_callback_selects_existing_features_without_recomputation(self):
        callback=self.runtime.probe_callback(recording_id='synthetic-recording',subject='synthetic-subject')
        g=result((m0.FEATURE_ORDER[-1],))
        completed=SimpleNamespace(result=g,frame_index=1,device_timestamp_ms=123.5,rf_demo='ignored',live_f1='ignored')
        with patch.object(geometry,'compute_candidate_geometry',side_effect=AssertionError('no recalculation')):
            with patch('posture_geometry_probe.run_frame_inference',side_effect=AssertionError('no detector')):
                callback(completed)
        packet=self.runtime.engine._last_input
        self.assertEqual(dict(packet.features),{name:g.features[name] for name in m0.FEATURE_ORDER})
        self.assertEqual(packet.device_timestamp_ms,'123.5')
        self.assertEqual(packet.timestamp_utc,'unknown')
        self.assertIsNone(packet.source_label)
        self.assertIsNone(packet.segment_id)
        self.assertEqual(self.runtime.engine.rf_calls,0)
        with self.assertRaisesRegex(ValueError,'required H9'):
            host.geometry_to_host_input(geometry.GeometryResult({}, {}, {}),frame_index=2,
                recording_id='r',subject='s',device_timestamp_ms='1',host_monotonic_ms='1')

    def test_host_window_accepts_device_reset_equal_times_and_keeps_original_tokens(self):
        for i in range(41):
            device='1' if i>=20 else '900000000000.1234'
            self.observe(i+1,i*100,device=device)
        row=self.outputs[-1]
        self.assertEqual(row['status'],'PREDICTED')
        self.assertEqual(row['window_end_ms'],'4000')
        self.assertEqual(row['input_host_monotonic_range'],['100','4000'])
        self.assertEqual(row['input_device_timestamp_range'],['900000000000.1234','1'])
        self.assertEqual(row['last_input_age_ms'],'0')
        self.assertEqual(self.runtime.engine.device_clock_regressions,1)
        self.assertEqual(self.runtime.engine.equal_device_times,39)

    def test_no_new_frame_holds_same_id_without_rf_or_new_prediction(self):
        self.feed()
        prediction=self.outputs[-1]
        self.assertEqual(self.runtime.engine.rf_calls,1)
        self.clock.set_ms(5000)
        with patch.object(self.model,'predict',side_effect=AssertionError('no repeat RF')):
            holding=self.runtime.tick()[0]
            self.assertEqual(self.runtime.tick(),[])
            self.clock.set_ms(5500)
            snapshot=self.runtime.snapshot()
        self.assertEqual(holding['status'],'HOLDING')
        self.assertFalse(holding['new_prediction'])
        self.assertIsNone(holding['prediction_label'])
        self.assertEqual(holding['held_prediction_id'],prediction['prediction_id'])
        self.assertEqual(holding['last_prediction_age_ms'],'1000')
        self.assertEqual(snapshot['last_prediction_age_ms'],'1500')
        self.assertEqual(snapshot['display_prediction']['prediction_id'],prediction['prediction_id'])
        self.assertFalse(snapshot['new_prediction'])
        self.assertEqual(self.runtime.engine.rf_calls,1)

    def test_snapshot_never_republishes_prediction_and_hides_it_when_timer_is_late(self):
        self.feed()
        before=self.runtime.publications
        self.clock.set_ms(4500)
        snapshot=self.runtime.snapshot()
        self.assertEqual(snapshot['status'],'HOLDING')
        self.assertEqual(snapshot['last_prediction_age_ms'],'500')
        self.assertFalse(snapshot['new_prediction'])
        self.clock.set_ms(6500)
        snapshot=self.runtime.snapshot()
        self.assertEqual(snapshot['status'],'STALE')
        self.assertIsNone(snapshot['display_prediction'])
        self.assertIsNone(snapshot['prediction_label'])
        self.assertEqual(self.runtime.publications,before)
        self.assertEqual(self.runtime.engine.rf_calls,1)

    def test_delayed_timer_emits_once_counts_missed_deadlines_and_clears_stale(self):
        self.feed()
        self.clock.set_ms(30000)
        with patch.object(self.model,'predict',side_effect=AssertionError('no old tick inference')):
            outputs=self.runtime.tick()
        self.assertEqual(len(outputs),1)
        row=outputs[0]
        self.assertEqual(row['status'],'STALE')
        self.assertEqual(row['due_periods_this_dispatch'],26)
        self.assertEqual(row['missed_periods_this_dispatch'],25)
        self.assertEqual(self.runtime.engine.missed_periods_total,25)
        self.assertEqual(row['emitted_host_monotonic_ms'],'30000')
        self.assertIsNone(row['display_prediction'])
        self.clock.set_ms(30010)
        self.assertEqual(self.runtime.tick(),[])
        recovered=self.observe(42,30100)[-1]
        self.assertEqual(recovered['status'],'COLLECTING')
        self.assertEqual(recovered['input_frame_indices'],[42])

    def test_gap_frame_coalesces_old_ticks_before_new_collection(self):
        self.feed()
        outputs=self.observe(42,30000)
        self.assertEqual([r['status'] for r in outputs],['STALE','COLLECTING'])
        self.assertEqual(outputs[0]['missed_periods_this_dispatch'],25)
        self.assertTrue(all(r['display_prediction'] is None for r in outputs))
        self.assertEqual(self.runtime.engine.rf_calls,1)

    def test_manual_reset_removes_previous_display_and_restarts_same_unlabelled_input(self):
        self.feed()
        old_id=self.outputs[-1]['prediction_id']
        self.clock.set_ms(4050)
        reset=self.runtime.manual_reset()[0]
        self.assertEqual(reset['status'],'COLLECTING')
        self.assertIsNone(reset['display_prediction'])
        self.assertIsNone(reset['held_prediction_id'])
        for i in range(41):self.observe(42+i,4100+i*100)
        self.assertEqual(self.outputs[-1]['status'],'PREDICTED')
        self.assertNotEqual(self.outputs[-1]['prediction_id'],old_id)
        self.assertEqual(self.outputs[-1]['input_frame_range'],[43,82])

    def test_insufficient_and_explicit_csv_exclusions_clear_old_prediction(self):
        self.feed()
        for i in range(1,41):self.observe(41+i,4000+i*100,missing=m0.FEATURE_ORDER)
        insufficient=self.outputs[-1]
        self.assertEqual(insufficient['status'],'INSUFFICIENT_DATA')
        self.assertIsNone(insufficient['display_prediction'])
        before=self.runtime.engine.rf_calls
        self.clock.set_ms(9000)
        self.runtime.tick()
        self.assertEqual(self.runtime.engine.rf_calls,before)
        for i,label in enumerate(('TRANSITION','body_forward'),82):
            out=self.observe(i,9100+(i-82)*100,segment=str(i),label=label)[-1]
            self.assertEqual(out['status'],'INSUFFICIENT_DATA')
            self.assertIsNone(out['display_prediction'])
        self.assertEqual(self.runtime.engine.rf_calls,before)

    def test_timer_thread_observes_stale_without_new_frame_callbacks(self):
        self.feed()
        stale=threading.Event()
        self.runtime._sink=lambda row: stale.set() if row['status']=='STALE' else None
        runner=host.H9TimerRunner(self.runtime,poll_seconds=.01).start()
        try:
            self.clock.set_ms(6000)
            self.assertTrue(stale.wait(1.0),'timer did not run independently')
            with self.assertRaisesRegex(RuntimeError,'already started'):runner.start()
        finally:
            runner.stop()
        self.assertIsNone(runner.error)
        self.assertEqual(self.runtime.engine.rf_calls,1)

    def test_concurrent_frame_timer_reset_calls_publish_in_serial_order(self):
        class Clock:
            ns=0
            def __call__(self):self.ns+=10_000_000;return self.ns
        outputs=[];errors=[]
        runtime=host.H9AsyncRuntime(self.model,clock_ns=Clock(),sink=outputs.append)
        def produce():
            try:
                for i in range(1,61):
                    runtime.observe_geometry(result(),frame_index=i,recording_id='r',subject='s',device_timestamp_ms=str(i))
            except Exception as e:errors.append(e)
        def timers():
            try:
                for _ in range(60):runtime.tick()
            except Exception as e:errors.append(e)
        def resets():
            try:
                for _ in range(5):runtime.manual_reset()
            except Exception as e:errors.append(e)
        threads=[threading.Thread(target=f) for f in (produce,timers,resets)]
        for t in threads:t.start()
        for t in threads:t.join(1.0)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(errors,[])
        self.assertEqual([r['publication_sequence'] for r in outputs],list(range(1,len(outputs)+1)))

    def test_order_guards_preserve_state_and_raw_device_reordering_is_not_host_reordering(self):
        self.observe(1,100)
        with self.assertRaises(ValueError):self.observe(1,200)
        self.observe(2,200,device='0')
        self.assertEqual(self.runtime.engine._input_version,2)
        with self.assertRaises(ValueError):self.clock.set_ms(199)
        with self.assertRaises(ValueError):self.runtime.engine.push(window.H9WindowInput.from_replay(frame(3)))

    def test_csv_runtime_keeps_source_bytes_and_applies_explicit_reset(self):
        frames=[]
        for first,count,segment,label in ((1,51,'1','upright'),(52,41,'3','body_forward'),(93,51,'5','lean_back')):
            frames.extend(frame(i,segment=segment,label=label,timestamp=str((i-1)*100)) for i in range(first,first+count))
        source=self.root/'synthetic.csv'
        with source.open('x',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(csv_row(x) for x in frames)
        artifact=self.root/'model.json';m0._write_new(artifact,self.document)
        before_source,before_model=source.read_bytes(),artifact.read_bytes()
        report=host.run_csv_runtime([source],artifact,reset_at_rows=[('synthetic-recording',45)])
        self.assertEqual(report['manual_resets'],[dict(recording_id='synthetic-recording',frame_index=45)])
        self.assertEqual(report['rf_calls'],report['status_counts']['PREDICTED'])
        self.assertGreater(report['status_counts']['HOLDING'],0)
        self.assertGreater(report['status_counts']['STALE'],0)
        self.assertEqual(report['missed_periods'],3)
        self.assertEqual(source.read_bytes(),before_source)
        self.assertEqual(artifact.read_bytes(),before_model)
        self.assertTrue(all(not r['new_prediction'] for r in report['results'] if r['status']=='HOLDING'))

    def test_cli_output_guard_prevents_loading_and_replay(self):
        output=self.root/'keep.json';output.write_text('keep',encoding='utf-8')
        with patch.object(host,'run_csv_runtime',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(FileExistsError,'overwrite'),redirect_stdout(io.StringIO()):
                host.main(['--probe-csv','unused.csv','--model','unused.json','--output',str(output)])
        self.assertEqual(output.read_text(encoding='utf-8'),'keep')


if __name__ == '__main__':unittest.main()
