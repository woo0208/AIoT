"""E0/E1 common timing and key-path contracts; synthetic SDK/GUI only."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler

from e0_fs3 import E0Session
from e0_panel import OperatorPanel
from test_e0_fs3 import Clock, estimators
from test_h9_probe_integration import SyntheticProbe
import posture_geometry_probe as probe


class E0E1Tests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(SVC,'fit',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(StandardScaler,'fit',side_effect=AssertionError('no training')))

    def run_fake(self,variant,*,mode='summary',events=None,arm=False,backend='WIN32',
                 poll_supported=True,fail_inference=False,stop_via_tk=False,invalid_pair=False,
                 receive_deadline=False):
        events=[0,100,200] if events is None else events
        clock=Clock();model,scaler=estimators()
        s=E0Session(self.root/f'{variant}_{mode}_{len(list(self.root.iterdir()))}',
                    model,scaler,clock_ns=clock,mode=mode)
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            fake=SyntheticProbe(NS(enterContext=stack.enter_context),events)
            fake.cv.currentUIFramework=Mock(return_value=backend)
            def key():
                clock.add_ms(13 if variant=='E0' else 3)
                return -1 if stop_via_tk else next(fake.keys)
            fake.cv.waitKey.side_effect=lambda delay:key()
            if poll_supported:fake.cv.pollKey=Mock(side_effect=key)
            root=Mock()
            root.update_idletasks.side_effect=lambda:clock.add_ms(2)
            root.update.side_effect=lambda:clock.add_ms(3)
            tk=NS(Tk=lambda:root,StringVar=lambda **kwargs:Mock(),
                  Label=lambda *args,**kwargs:Mock(),Button=lambda *args,**kwargs:Mock())
            panel=OperatorPanel(s,tk_module=tk)
            if arm:panel.control.start()
            calls=[0]
            def ui_poll():
                calls[0]+=1
                if stop_via_tk and calls[0]>len(events):panel.control.close()
                return panel.poll()
            if invalid_pair:
                fake.pipeline.try_wait_for_frames.side_effect=lambda timeout:(True,NS(
                    get_timestamp=lambda:100.,get_color_frame=lambda:None,get_depth_frame=lambda:None))
            if fail_inference:fake.pose.detect_for_video.side_effect=RuntimeError('PRIVATE failure')
            if receive_deadline:
                receive=fake.pipeline.try_wait_for_frames.side_effect
                def delayed_receive(timeout):
                    value=receive(timeout);clock.add_ms(10);return value
                fake.pipeline.try_wait_for_frames.side_effect=delayed_receive
                real_control=probe.probe_timing.ProbeRunControl
                stack.enter_context(patch.object(probe.probe_timing,'ProbeRunControl',
                    side_effect=lambda duration,**kwargs:real_control(.01,clock_ns=clock)))
            predict=stack.enter_context(patch.object(model,'predict',return_value=np.array([2])))
            expected_error=variant=='E1' and (backend!='WIN32' or not poll_supported)
            if expected_error or fail_inference:
                with self.assertRaises(RuntimeError):
                    probe.run_probe(e0_session=s,e0_ui_variant=variant,ui_poll=ui_poll)
            else:
                probe.run_probe(e0_session=s,e0_ui_variant=variant,ui_poll=ui_poll,
                                frame_callback=fake.callbacks.append)
            calls_predict=predict.call_args_list
        stats={} if mode=='off' else {x['name']:x for x in json.loads(
            (s.directory/'timing/diagnostics.json').read_text(encoding='utf-8'))['stage_milliseconds']}
        return s,stats,fake,calls_predict

    def test_tk_time_in_both_new_boundaries_and_old_receive_span_unchanged(self):
        for variant,key_ms in [('E0',13),('E1',3)]:
            s,stats,fake,_=self.run_fake(variant)
            for n,ms in [('ui.tk_idle',2),('ui.tk_update',3),('ui.tk_poll',5),
                         ('ui.key_wait',key_ms),('latency.receive_to_frame_complete',key_ms),
                         ('latency.receive_wait_start_to_frame_complete',key_ms),
                         ('latency.loop_start_to_frame_complete',5+key_ms),('loop.total',5+key_ms)]:
                self.assertEqual(stats[n]['count'],3,n)
                for q in (50,95,99):self.assertEqual(stats[n][f'p{q}'],ms,n)
            self.assertEqual(s.result_summary['loop_status_counts'],{'completed':3})
            self.assertAlmostEqual(s.result_summary['stream_seconds'],3*(5+key_ms)/1000)
            if variant=='E1':fake.cv.waitKey.assert_not_called()
            self.assertEqual(len(fake.callbacks),3)
            fake.pipeline.stop.assert_called_once()

    def test_same_features_scaler_inputs_predictions_and_modes(self):
        outputs=[]
        for mode in ('off','summary','detailed'):
            for variant in ('E0','E1'):
                s,stats,fake,pred=self.run_fake(variant,mode=mode,
                    events=list(range(0,10000,300))+[10000],arm=True)
                self.assertEqual(s.segments[0]['input_frames'],34)
                self.assertEqual(s.segments[0]['status'],'PREDICTED')
                self.assertEqual(s.segments[0]['prediction'],2)
                self.assertEqual(len(pred),1)
                outputs.append((pred[0].args[0], [dict(f.result.features) for f in fake.callbacks]))
                if mode=='off':self.assertFalse(s.directory)
                else:
                    saved=json.loads((s.directory/'summary.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['timing_contract'],'e0-e1-loop-timing/1')
                    self.assertEqual(saved['environment']['execution_variant'],variant)
        for x,features in outputs[1:]:
            np.testing.assert_array_equal(x,outputs[0][0])
            self.assertEqual(features,outputs[0][1])

    def test_timeout_is_counted_in_loop_and_separate_idle_key_stage(self):
        for variant in ('E0','E1'):
            s,stats,fake,_=self.run_fake(variant,events=[0,None,3000])
            self.assertEqual(s.result_summary['loop_status_counts'],{'completed':2,'timeout':1})
            self.assertEqual(stats['loop.total']['count'],3)
            self.assertEqual(stats['latency.loop_start_to_frame_complete']['count'],2)
            self.assertEqual(stats['ui.key_wait']['count'],2)
            self.assertEqual(stats['ui.idle_key_wait']['count'],1)
            if variant=='E1':fake.cv.waitKey.assert_not_called()

    def test_tk_close_and_invalid_pair_remain_in_total_loop(self):
        for variant in ('E0','E1'):
            s,stats,_,_=self.run_fake(variant,events=[0],stop_via_tk=True,invalid_pair=True)
            self.assertEqual(s.result_summary['loop_status_counts'],{'invalid_pair':1,'control_only':1})
            self.assertEqual(stats['loop.total']['count'],2)
            self.assertEqual(stats['ui.tk_poll']['count'],2)
            self.assertNotIn('latency.loop_start_to_frame_complete',stats)

    def test_receive_deadline_skip_is_not_removed_from_total_loop(self):
        for variant in ('E0','E1'):
            s,stats,fake,_=self.run_fake(variant,events=[0],receive_deadline=True)
            self.assertEqual(s.result_summary['loop_status_counts'],{'deadline_skip':1})
            self.assertEqual(stats['loop.total']['count'],1)
            self.assertEqual(stats['loop.total']['p95'],15)
            self.assertNotIn('latency.loop_start_to_frame_complete',stats)
            fake.cv.waitKey.assert_not_called()

    def test_exception_finalizes_partial_loop_and_privacy_safe_logs(self):
        for variant in ('E0','E1'):
            s,stats,fake,_=self.run_fake(variant,events=[0],fail_inference=True)
            self.assertEqual(s.result_summary['loop_status_counts'],{'INCOMPLETE':1})
            self.assertEqual(stats['loop.total']['count'],1)
            self.assertEqual(s.result_summary['status'],'FAILED')
            text=''.join(p.read_text(encoding='utf-8') for p in s.directory.rglob('*') if p.is_file())
            self.assertNotIn('PRIVATE',text)
            fake.pipeline.stop.assert_called_once()

    def test_unsupported_e1_refuses_before_camera_and_never_falls_back(self):
        for backend,supported in [('QT',True),('NOT_MEASURED',True),('WIN32',False)]:
            s,_,fake,_=self.run_fake('E1',backend=backend,poll_supported=supported)
            fake.pipeline.start.assert_not_called()
            fake.cv.waitKey.assert_not_called()
            self.assertEqual(s.result_summary['status'],'FAILED')

    def test_e1_requires_engineering_session_and_visible_path(self):
        with self.assertRaises(ValueError):probe.run_probe(e0_ui_variant='E1')
        model,scaler=estimators()
        s=E0Session(self.root/'headless',model,scaler,clock_ns=Clock())
        with self.assertRaises(ValueError):probe.run_probe(e0_session=s,e0_ui_variant='E1',headless=True)

    def test_poll_key_codes_match_legacy_low_byte_handlers(self):
        cv=NS(pollKey=Mock(side_effect=[-1,ord('q')|0x10000]),waitKey=Mock())
        self.assertEqual(probe._e0_ui_key(cv,'E1'),-1)
        key=probe._e0_ui_key(cv,'E1')
        self.assertEqual(key,ord('q'))
        self.assertTrue(probe.handle_panel_key(key,'summary',0)[0])
        cv.waitKey.assert_not_called()


if __name__=='__main__':unittest.main()
