"""E0-P2 synthetic contracts; no camera, fit, GPU execution or optimization."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np

from e0_fs3 import E0Session
from e0_resources import ResourceMonitor, NvidiaTelemetry
from test_e0_fs3 import Clock, estimators, result
from test_frame_provenance import child, pair
from test_h9_probe_integration import SyntheticProbe
import posture_geometry_probe as probe


class P2Tests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clock=Clock()

    def test_cpu_normalization_system_deltas_ram_peaks_and_same_clock(self):
        samples=iter([dict(process_cpu_ns=1_000_000_000,logical_cpus=4,rss_bytes=100,private_bytes=150,
            system_busy_ticks=10,system_total_ticks=100),
            dict(process_cpu_ns=1_500_000_000,logical_cpus=4,rss_bytes=200,private_bytes=180,
            system_busy_ticks=60,system_total_ticks=200)])
        r=ResourceMonitor(clock_ns=self.clock,reader=lambda:next(samples))
        first=r.sample();self.clock.add_ms(1000);last=r.sample()
        self.assertIsNone(first['process_cpu_percent']);self.assertIsNone(first['system_cpu_percent'])
        self.assertEqual(last['host_perf_counter_ns'],1_000_000_000)
        self.assertEqual(last['process_cpu_one_core_percent'],50)
        self.assertEqual(last['process_cpu_percent'],12.5)
        self.assertEqual(last['system_cpu_percent'],50)
        stats=r.summary()['statistics']
        self.assertEqual(stats['rss_bytes']['maximum'],200)
        self.assertEqual(stats['private_bytes']['change'],30)
        self.assertEqual(stats['os_peak_rss_bytes']['status'],'NOT_MEASURED')

    def test_missing_reset_and_invalid_counters_are_not_zeros(self):
        values=iter([dict(process_cpu_ns=10,logical_cpus=4,system_busy_ticks=10,system_total_ticks=20),
                     dict(process_cpu_ns=1,logical_cpus=4,system_busy_ticks=1,system_total_ticks=2),
                     dict(process_cpu_ns=np.nan,logical_cpus=None,rss_bytes=np.inf)])
        r=ResourceMonitor(clock_ns=self.clock,reader=lambda:next(values))
        for _ in range(3):r.sample();self.clock.add_ms(1000)
        self.assertTrue(all(row['process_cpu_percent'] is None for row in r.samples))
        self.assertTrue(all(row['system_cpu_percent'] is None for row in r.samples))
        self.assertEqual(r.summary()['statistics']['rss_bytes']['status'],'NOT_MEASURED')

    def test_reader_failure_records_only_type(self):
        def bad():raise OSError('PRIVATE user path')
        r=ResourceMonitor(clock_ns=self.clock,reader=bad);r.sample()
        self.assertNotIn('PRIVATE',json.dumps(r.samples))
        self.assertEqual(r.summary()['statistics']['private_bytes']['status'],'NOT_MEASURED')

    def test_nvidia_provider_parsing_unsupported_fields_timeout_and_no_tool(self):
        with patch('e0_resources.shutil.which',return_value=None):
            p=NvidiaTelemetry()
        self.assertEqual(p()['status'],'NOT_MEASURED')
        p.executable='synthetic-nvidia-smi'
        with patch('e0_resources.subprocess.run',return_value=NS(returncode=0,
                stdout='0, Test GPU, 35, 100, 1000\n1, Other GPU, N/A, N/A, N/A\n')) as command:
            observed=p()
        self.assertEqual(observed['devices'][0]['utilization_percent'],35)
        self.assertEqual(observed['devices'][0]['vram_used_bytes'],100*2**20)
        self.assertEqual(observed['devices'][1]['utilization_status'],'NOT_MEASURED')
        self.assertIsNone(observed['devices'][1]['vram_used_bytes'])
        args=command.call_args.args[0]
        self.assertTrue(any(x.startswith('--query-gpu=') for x in args))
        self.assertNotIn('--compute-mode',args)
        self.assertEqual(command.call_args.kwargs['timeout'],1)
        with patch('e0_resources.subprocess.run',side_effect=OSError('PRIVATE token')):
            self.assertNotIn('PRIVATE',json.dumps(p()))
            self.assertEqual(p()['status'],'NOT_MEASURED')

    def test_gpu_poll_never_blocks_frame_thread_and_resource_worker_stops(self):
        entered,released=threading.Event(),threading.Event();threads=[]
        def gpu():
            threads.append(threading.current_thread().name);entered.set()
            if not released.wait(2):raise TimeoutError('test GPU wait')
            return dict(status='NOT_MEASURED',devices=[])
        r=ResourceMonitor(clock_ns=self.clock,reader=lambda:{},gpu_reader=gpu)
        try:
            r.start();self.assertTrue(entered.wait(1))
            # A synchronous frame loop has no monitor lock to acquire.
            self.clock.add_ms(1)
            self.assertEqual(self.clock(),1_000_000)
        finally:
            released.set();r.stop()
        self.assertEqual(threads,['e0-resources'])
        self.assertFalse(r._thread.is_alive())

    def run_segment(self,mode):
        model,scaler=estimators();s=E0Session(self.root/mode,model,scaler,clock_ns=self.clock,mode=mode)
        s.begin_stream();s.arm_segment()
        with patch.object(model,'predict',return_value=np.array([1])) as predict:
            for i in range(151):
                row=s.begin_receive();self.clock.add_ms(1)
                stamp=i*10000/150
                s.received(row,True,pair(child(i+1,stamp),child(i+1,stamp,stream='depth')),s.clock_ns())
                s.aligned(row,child(i+1,stamp),child(i+1,stamp,stream='depth'))
                s.accept(row,result(missing=(8,) if i%17==0 else ()),i+1,stamp,pose_detected=True,face_detected=True)
                s.frame_completed(row)
        s.finish()
        return s,predict.call_args.args[0]

    def test_modes_preserve_exact_model_input_support_prediction_and_no_fake_queue(self):
        sessions=[];inputs=[]
        for mode in ['off','summary','detailed']:
            s,x=self.run_segment(mode);sessions.append(s);inputs.append(x)
        for x in inputs[1:]:np.testing.assert_array_equal(x,inputs[0])
        for s in sessions:
            segment=s.segments[0]
            self.assertEqual((segment['input_frames'],segment['valid_frames'],segment['prediction']),(150,141,1))
            self.assertEqual(s.result_summary['queue']['application_queue'],'NOT_APPLICABLE')
            self.assertEqual(s.result_summary['queue']['sdk_internal_queue'],'NOT_MEASURED')
        self.assertFalse((self.root/'off').exists())
        self.assertFalse(sessions[0].frames)
        self.assertFalse((self.root/'summary/frames.jsonl').exists())
        self.assertFalse(sessions[1].frames)
        summary=json.loads((self.root/'summary/timing/diagnostics.json').read_text())
        self.assertEqual(summary['raw'],[])
        self.assertEqual(summary['raw_status'],'NOT_RETAINED_SUMMARY')
        self.assertTrue((self.root/'detailed/frames.jsonl').exists())
        for key in ['received_frames','completed_frames','feature_success_frames','sensor_events','svm_successes']:
            self.assertEqual(sessions[1].result_summary[key],sessions[2].result_summary[key])

    def test_backend_observation_is_config_not_attestation_and_never_mutates_delegate(self):
        model,scaler=estimators();s=E0Session(self.root/'backend',model,scaler,clock_ns=self.clock)
        delegate=NS(name='GPU');base=NS(delegate=delegate);options=NS(base_options=base)
        s.observe_backends(options,options)
        self.assertIs(base.delegate,delegate)
        self.assertEqual(s.backends['pose']['configured_delegate'],'GPU')
        self.assertEqual(s.backends['pose']['actual'],'NOT_MEASURED')
        self.assertEqual(s.backends['svm']['actual'],'sklearn.SVC/libsvm CPU')

    def test_injected_resource_clock_must_match_frame_clock(self):
        model,scaler=estimators();r=ResourceMonitor(clock_ns=Clock())
        with self.assertRaises(ValueError):
            E0Session(self.root/'badclock',model,scaler,clock_ns=self.clock,resource_monitor=r)

    def test_actual_probe_hooks_preserve_callbacks_and_predictions_in_all_modes(self):
        outputs=[]
        for mode in ['off','summary','detailed']:
            self.clock=Clock()
            model,scaler=estimators();s=E0Session(self.root/('probe-'+mode),model,scaler,clock_ns=self.clock,mode=mode)
            s.arm_segment()
            with ExitStack() as stack:
                stack.enter_context(redirect_stdout(io.StringIO()));stack.enter_context(redirect_stderr(io.StringIO()))
                fake=SyntheticProbe(NS(enterContext=stack.enter_context),list(range(52)),keys=[-1]*52)
                def receive(_):
                    i=receive.index;receive.index+=1;fake.clock.set_ms(i*200);self.clock.ns=i*200_000_000
                    return True,pair(child(i+1,i*200),child(i+1,i*200,stream='depth'))
                receive.index=0;fake.pipeline.try_wait_for_frames.side_effect=receive
                stack.enter_context(patch.object(model,'predict',return_value=np.array([2])))
                control=probe.probe_timing.ProbeRunControl
                stack.enter_context(patch.object(probe.probe_timing,'ProbeRunControl',
                    side_effect=lambda duration,**kwargs:control(duration,clock_ns=fake.clock)))
                probe.run_probe(e0_session=s,headless=True,duration_seconds=10.1,show_3d_views='none',
                    frame_callback=fake.callbacks.append)
            outputs.append(([dict(f.result.features) for f in fake.callbacks],
                            s.segments[0]['prediction'],s.segments[0]['coverage']))
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual(outputs[1],outputs[2])

    def test_periodic_resource_sampling_and_gpu_field_statuses(self):
        sampled=threading.Event();calls=[]
        def read():
            calls.append(1);self.clock.add_ms(1000)
            if len(calls)>=3:sampled.set()
            return dict(process_cpu_ns=self.clock()//2,logical_cpus=4,
                        rss_bytes=100+len(calls),private_bytes=200+len(calls))
        r=ResourceMonitor(clock_ns=self.clock,reader=read,interval_seconds=.005,
            gpu_reader=lambda:dict(status='MEASURED',devices=[dict(index=0,model='Test GPU',
                utilization_percent=0,vram_used_bytes=None,vram_total_bytes=None,
                utilization_status='MEASURED',vram_status='NOT_MEASURED')]))
        try:
            r.start();self.assertTrue(sampled.wait(1))
        finally:
            r.stop()
        self.assertGreaterEqual(len(r.samples),3)
        self.assertEqual(r.summary()['gpu_devices'][0]['utilization_percent'],0)
        self.assertEqual(r.summary()['gpu_devices'][0]['vram_status'],'NOT_MEASURED')
        self.assertGreater(r.summary()['statistics']['rss_bytes']['change'],0)

    def test_e0_resource_timeline_persistence_and_off_disables_monitor(self):
        model,scaler=estimators()
        monitor=ResourceMonitor(clock_ns=self.clock,reader=lambda:dict(
            process_cpu_ns=self.clock()//2,logical_cpus=4,rss_bytes=1024,private_bytes=2048))
        # Deterministic periodic-reader fixture: no real resource thread needed.
        monitor.start=lambda:monitor.sample()
        s=E0Session(self.root/'resources',model,scaler,clock_ns=self.clock,mode='summary',resource_monitor=monitor)
        s.begin_stream();self.clock.add_ms(1000);s.finish()
        rows=[json.loads(line) for line in (s.directory/'resources.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['host_perf_counter_ns'],1_000_000_000)
        self.assertEqual(s.result_summary['resources']['statistics']['process_cpu_percent']['p50'],12.5)
        with patch.object(monitor,'start',side_effect=AssertionError('OFF monitor')):
            off=E0Session(self.root/'off',model,scaler,mode='off',resource_monitor=monitor)
            off.begin_stream();off.finish()
        self.assertIsNone(off.resources)
        self.assertFalse((self.root/'off').exists())


if __name__=='__main__':unittest.main()
