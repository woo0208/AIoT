"""P3 synthetic model/UI/storage integration. No camera, training or E1."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace as NS

import numpy as np
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler

from e0_fs3 import E0Session,FEATURE_IDS
from e0_model import load_fs3,ModelNotReady,environment_record
from e0_panel import OperatorControl,OperatorPanel,run_bound_probe
from e0_resources import ResourceMonitor
from e0_storage import CheckpointList,LogStorageError,exact_stats,write_json
from test_e0_fs3 import Clock,estimators,result


class P3Tests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clock=Clock()
        self.model,self.scaler=estimators()
        self.enterContext(patch.object(SVC,'fit',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(StandardScaler,'fit',side_effect=AssertionError('no training')))

    def session(self,mode='detailed',limit=4):
        return E0Session(self.root/mode,self.model,self.scaler,clock_ns=self.clock,mode=mode,log_buffer_limit=limit)

    def observation(self,s,i,stamp):
        row=s.begin_receive();self.clock.add_ms(1)
        s.received(row,True,None,s.clock_ns())
        s.accept(row,result(),i,stamp,pose_detected=None,face_detected=None)
        s.frame_completed(row)

    def fixture_model(self):
        path=self.root/'synthetic.pkl'
        path.write_bytes(pickle.dumps((self.model,self.scaler),protocol=5))
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        return path,sha

    def test_exact_disk_percentiles_match_numpy_without_sampling(self):
        rng=np.random.default_rng(1203)
        for n in (0,1,2,7,256,4097):
            values=rng.random(n)*1000
            found=exact_stats(iter(values),disk=True,include_p99=True)
            self.assertEqual(found['count'],n)
            for p in (50,95,99):
                self.assertEqual(found[f'p{p}'],float(np.percentile(values,p)) if n else None)

    def test_checkpoint_bound_order_random_access_and_flush_tail(self):
        rows=CheckpointList(self.root/'bounded',7)
        for i in range(1025):rows.append(dict(index=i,ns=i*100))
        self.assertLessEqual(len(rows.buffer),7)
        self.assertEqual(rows.status()['peak_buffered_records'],7)
        self.assertEqual(rows[-1]['index'],1024)
        self.assertEqual(rows[:3],[dict(index=i,ns=i*100) for i in range(3)])
        rows.flush()
        self.assertEqual([r['index'] for r in rows],list(range(1025)))
        self.assertEqual(rows.status()['buffered_records'],0)

    def test_disk_failure_preserves_committed_prefix_and_never_overwrites(self):
        rows=CheckpointList(self.root/'failure',1)
        rows.append(dict(index=0));rows.append(dict(index=1))
        first=rows.directory/'00000000.jsonl';before=first.read_bytes()
        with patch('e0_storage.os.rename',side_effect=OSError('PRIVATE disk path')):
            with self.assertRaises(LogStorageError) as error:rows.append(dict(index=2))
        self.assertNotIn('PRIVATE',str(error.exception))
        self.assertEqual(first.read_bytes(),before)
        self.assertEqual(list(rows),[dict(index=0),dict(index=1)])
        self.assertTrue((rows.directory/'00000001.jsonl.partial').exists())

    def test_log_capacity_fails_explicitly_instead_of_sampling_or_eviction(self):
        rows=CheckpointList(self.root/'capacity',1,max_bytes=1)
        rows.append(dict(index=0))
        with self.assertRaisesRegex(LogStorageError,'LOG_CAPACITY_EXCEEDED'):rows.append(dict(index=1))
        self.assertEqual(list(rows),[dict(index=0)])

    def test_atomic_stream_publication_keeps_old_json_fields(self):
        rows=CheckpointList(self.root/'rows',3)
        for i in range(10):rows.append(dict(frame_id=i))
        path=self.root/'output.json';write_json(path,dict(kind='old-format',raw=rows),arrays=('raw',))
        self.assertEqual(json.loads(path.read_text())['raw'],[dict(frame_id=i) for i in range(10)])
        before=path.read_bytes()
        with self.assertRaises(FileExistsError):write_json(path,dict(changed=True))
        self.assertEqual(path.read_bytes(),before)

    def test_session_bounded_logs_equal_full_order_and_exact_predict(self):
        s=self.session();s.begin_stream();s.arm_segment()
        with patch.object(self.model,'predict',return_value=np.array([1])):
            for i in range(40):self.observation(s,i+1,i*200)
            with self.assertRaises(ValueError):s.complete_segment(9000,40,self.clock())
            s.complete_segment(10000,40,self.clock())
        s.finish()
        raw=[json.loads(line) for line in (s.directory/'frames.jsonl').read_text().splitlines()]
        self.assertEqual([r['frame_id'] for r in raw],list(range(1,41)))
        self.assertTrue(all(r['face_detected'] is None for r in raw))
        self.assertEqual(s.segments[0]['prediction'],1)
        self.assertLessEqual(s.result_summary['buffering']['frames']['peak_buffered_records'],4)
        timing=json.loads((s.directory/'timing/diagnostics.json').read_text())
        self.assertTrue(all(b['peak_buffered_records']<=4 for b in timing['buffering']['durations']))
        self.assertEqual(len(timing['raw']),sum(r['count'] for r in timing['stage_milliseconds']))

    def test_partial_last_frame_is_finalized_before_checkpoint(self):
        s=self.session(limit=1);s.begin_stream()
        self.observation(s,1,0)
        row=s.begin_receive();s.received(row,True,None,s.clock_ns())
        s.finish(error=RuntimeError('PRIVATE failure'))
        lines=[json.loads(line) for line in (s.directory/'frames.jsonl').read_text().splitlines()]
        self.assertEqual([r['status'] for r in lines],['completed','INCOMPLETE'])
        self.assertNotIn('PRIVATE',(s.directory/'summary.json').read_text())

    def test_checkpoint_latency_is_not_counted_as_sensor_wait(self):
        s=self.session(limit=1);s.begin_stream();self.observation(s,1,0)
        flush=s.frames.flush
        def delayed_flush():flush();self.clock.add_ms(7)
        with patch.object(s.frames,'flush',side_effect=delayed_flush):row=s.begin_receive()
        began=row['receive_start_ns'];self.clock.add_ms(3)
        s.received(row,False,None,self.clock())
        self.assertEqual(self.clock()-began,3_000_000)
        self.assertEqual(s.timing._durations[('receive.wait','steady')][-1],3)
        s.finish()

    def test_ui_start_cancel_completion_and_ineligible(self):
        s=self.session();control=OperatorControl(s)
        self.assertTrue(control.start());self.assertFalse(control.start())
        self.assertEqual(control.state,'ARMED')
        self.observation(s,1,0);control.poll();self.assertEqual(control.state,'COLLECTING')
        control.cancel();self.assertEqual(control.state,'CANCELLED')
        self.assertEqual(s.segments[0]['input_frames'],1)
        control.start()
        with patch.object(self.model,'predict',return_value=np.array([0])):
            for i in range(30):self.observation(s,i+2,i*300)
            s.complete_segment(10000,31,self.clock())
        control.poll();self.assertEqual(control.state,'COMPLETED')
        control.start();self.observation(s,32,0);s.complete_segment(10000,32,self.clock())
        control.poll();self.assertEqual(control.state,'INELIGIBLE')
        control.close();self.assertFalse(control.poll())

    def test_tk_buttons_key_repeat_focus_cancel_and_close_are_wired(self):
        s=self.session();root=Mock();var=Mock();buttons=[]
        def button(*args,**kwargs):buttons.append(kwargs);return Mock()
        tk=NS(Tk=lambda:root,StringVar=lambda **kwargs:var,Label=lambda *args,**kwargs:Mock(),Button=button)
        panel=OperatorPanel(s,tk_module=tk)
        panel._key(NS(keysym='Return'));panel._key(NS(keysym='Return'))
        self.assertTrue(s.armed)
        bindings={call.args[0]:call.args[1] for call in root.bind.call_args_list}
        bindings['<FocusOut>'](NS());self.assertFalse(s.armed)
        buttons[0]['command']();self.assertTrue(s.armed)
        buttons[1]['command']();self.assertFalse(s.armed)
        buttons[2]['command']();self.assertFalse(panel.poll())
        panel.close();root.destroy.assert_called_once()

    def test_ui_timestamp_failure_keeps_running_and_requires_explicit_restart(self):
        s=self.session();control=OperatorControl(s)
        control.start();self.observation(s,1,100);control.poll()
        self.observation(s,2,100)
        self.assertTrue(control.poll())
        self.assertEqual(control.state,'TIMESTAMP_INVALID')
        self.assertTrue(control.start())
        self.assertEqual(control.state,'ARMED')
        self.observation(s,3,200);self.assertTrue(control.poll())
        self.assertEqual(control.state,'COLLECTING')

    def test_verified_loader_binds_archive_components_order_and_settings(self):
        path,sha=self.fixture_model()
        model,scaler,binding=load_fs3(path,sha,FEATURE_IDS)
        self.assertEqual(binding['artifact_sha256'],sha)
        self.assertEqual(binding['training_samples'],60)
        self.assertEqual(binding['model_sha256'],hashlib.sha256(pickle.dumps(model,protocol=5)).hexdigest())
        loaded=load_fs3(path,sha,FEATURE_IDS,expected_model_sha256=binding['model_sha256'],expected_scaler_sha256=binding['scaler_sha256'])
        self.assertEqual(loaded[2],binding)
        with self.assertRaises(ModelNotReady):load_fs3(path,sha,FEATURE_IDS,expected_scaler_sha256='0'*64)
        self.model.set_params(gamma=1/7)
        path.write_bytes(pickle.dumps((self.model,self.scaler),protocol=5));bad_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ModelNotReady):load_fs3(path,bad_sha,FEATURE_IDS)

    def test_missing_or_changed_model_is_not_ready_before_deserialization(self):
        path,sha=self.fixture_model()
        with patch('e0_model.pickle.loads',side_effect=AssertionError('must not load')):
            for bad_path,bad_sha,order in [(self.root/'missing',sha,FEATURE_IDS),(path,'0'*64,FEATURE_IDS),(path,sha,FEATURE_IDS[::-1])]:
                with self.assertRaises(ModelNotReady):load_fs3(bad_path,bad_sha,order)

    def test_frozen_probability_false_does_not_follow_changed_library_default(self):
        path,sha=self.fixture_model()
        model,_,_=load_fs3(path,sha,FEATURE_IDS)
        self.assertIs(model.probability,False)
        self.model.probability='deprecated'
        path.write_bytes(pickle.dumps((self.model,self.scaler),protocol=5))
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ModelNotReady):load_fs3(path,sha,FEATURE_IDS)

    def test_bound_ui_to_probe_adapter_uses_verified_objects_and_requires_authorization(self):
        path,sha=self.fixture_model();binding=load_fs3(path,sha,FEATURE_IDS)[2]
        runner=Mock()
        with self.assertRaises(PermissionError):run_bound_probe(path,binding,self.root/'unauthorized',probe_runner=runner)
        runner.assert_not_called()
        panels=[]
        def panel_factory(session):
            control=OperatorControl(session);control.start()
            panel=NS(poll=control.poll,close=Mock(side_effect=control.close));panels.append(panel);return panel
        def run(**kwargs):
            session=kwargs['e0_session'];session.begin_stream()
            self.assertTrue(kwargs['ui_poll']())
            with patch.object(session.model,'predict',return_value=np.array([1])):
                for i in range(30):self.observation(session,i+1,i*300)
                session.complete_segment(10000,30,self.clock())
            session.finish()
        factory=lambda *args,**kwargs:E0Session(*args,**kwargs,clock_ns=self.clock)
        with patch('e0_panel.E0Session',side_effect=factory):
            s=run_bound_probe(path,binding,self.root/'bound',execution_authorized=True,
                panel_factory=panel_factory,probe_runner=run)
        self.assertEqual(s.model_binding,binding)
        self.assertEqual(s.segments[0]['prediction'],1)
        panels[0].close.assert_called_once()

    def test_resource_writer_failure_is_reported_to_frame_loop(self):
        r=ResourceMonitor(clock_ns=self.clock,reader=lambda:{},interval_seconds=.001,
            gpu_reader=lambda:dict(status='NOT_MEASURED',devices=[]))
        r.enable_checkpoints(self.root/'resources',1);r.samples.max_bytes=1
        r.start();self.assertTrue(r._stop.wait(1))
        with self.assertRaises(LogStorageError):r.check_health()
        with self.assertRaises(LogStorageError):r.stop()
        self.assertFalse(r._thread.is_alive())

    def test_environment_record_has_anonymous_pc_and_no_machine_identity(self):
        env=environment_record('PC01')
        self.assertEqual(env['pc_id'],'PC01')
        self.assertTrue(env['packages']['numpy'])
        for key in ('hostname','username','serial','uuid','path'):self.assertNotIn(key,env)
        with self.assertRaises(ValueError):environment_record('PRIVATE user name')


if __name__=='__main__':unittest.main()
