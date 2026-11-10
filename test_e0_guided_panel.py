"""Synthetic guide/state/widget tests; no camera, Tk window or training."""
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
from e0_guided_panel import GuidedControl, GuidedPanel
from test_e0_fs3 import Clock, estimators, result


class GuidedTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clock = Clock()
        model, scaler = estimators()
        self.enterContext(patch.object(SVC, 'fit', side_effect=AssertionError('no training')))
        self.enterContext(patch.object(StandardScaler, 'fit', side_effect=AssertionError('no training')))
        self.predict = self.enterContext(patch.object(model, 'predict', return_value=np.array([5])))
        self.s = E0Session(self.root/'run', model, scaler, clock_ns=self.clock, mode='summary')
        self.control = GuidedControl(self.s)
        self.index = 0

    def observe(self, stamp):
        self.index += 1
        row = self.s.begin_receive()
        self.clock.add_ms(1)
        self.s.received(row, True, None, self.clock())
        self.s.accept(row, result(), self.index, stamp, pose_detected=True, face_detected=True)
        self.s.frame_completed(row)

    def hold(self, base, count=30):
        for i in range(count):
            self.observe(base+i*300)
        self.observe(base+10000)
        return self.control.poll()

    def test_all_thirty_holds_block_order_reset_and_auto_finish(self):
        order = []
        for n in range(30):
            self.assertEqual(self.control.expected, n//5)
            self.assertFalse(self.control.start())
            self.control.choose(0)
            if n//5:
                self.assertFalse(self.control.start())
                self.control.choose(n//5)
            self.assertTrue(self.control.start())
            self.assertFalse(self.control.start())
            order.append(self.control.expected)
            self.assertEqual(self.hold(n*20000), n<29)
            self.assertEqual(self.control.completed, n+1)
            self.assertFalse(self.control.normal_ready)
        self.assertEqual(order, [p for p in range(6) for _ in range(5)])
        self.assertEqual(self.control.state, 'DONE')
        self.assertEqual(self.predict.call_count, 30)  # P5 outputs never control progress.
        self.s.finish()
        summary=json.loads((self.s.directory/'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['environment']['guided_operation']['completed_holds'],30)
        self.assertEqual(summary['prediction_successes'],30)

    def test_cancel_and_bad_time_do_not_advance_and_require_manual_restart(self):
        self.control.choose(0);self.control.start();self.observe(100)
        self.control.cancel();self.control.poll()
        self.assertEqual(self.control.completed,0)
        self.assertFalse(self.control.start())
        self.control.choose(0);self.control.start();self.observe(200);self.observe(200)
        self.assertTrue(self.control.poll())
        self.assertEqual(self.control.state,'TIMESTAMP_INVALID')
        self.assertEqual(self.control.completed,0)
        self.assertFalse(self.control.start())
        self.control.choose(0);self.control.poll()
        self.assertTrue(self.control.start())
        self.hold(500)
        self.assertEqual(self.control.completed,1)
        self.assertEqual([s['status'] for s in self.s.segments],['INCOMPLETE','INCOMPLETE','PREDICTED'])

    def test_ineligible_full_window_counts_without_resampling_or_prediction(self):
        self.control.choose(0);self.control.start();self.hold(0,count=1)
        self.assertEqual(self.control.completed,1)
        self.assertEqual(self.control.progress['eligible_holds'],0)
        self.predict.assert_not_called()

    def test_preparation_and_wrong_target_never_start_aggregation(self):
        self.control.choose(1)
        self.assertFalse(self.control.start())
        self.observe(0)
        self.assertFalse(self.s.segments)
        self.assertFalse(self.s.records)
        self.control.choose(0);self.control.choose(2)
        self.assertFalse(self.control.start())
        self.control.choose(0)
        self.assertTrue(self.control.start())

    def test_panel_keys_fonts_subject_display_only_focus_and_close(self):
        root=Mock()
        tk=NS(Tk=lambda:root,StringVar=lambda **kwargs:Mock(),Label=Mock(return_value=Mock()),
              Button=Mock(return_value=Mock()))
        panel=GuidedPanel(self.s,subject='P02',tk_module=tk)
        self.control=panel.control
        root.geometry.assert_called_once_with('820x540')
        panel._key(NS(keysym='space'));panel._key(NS(keysym='Return'))
        self.assertTrue(self.s.armed)
        panel._key(NS(keysym='Return'))
        self.observe(0);panel.poll()
        self.assertEqual(self.control.state,'COLLECTING')
        panel._focus_out(NS())
        self.assertFalse(self.s.armed)
        self.assertIsNone(self.s.active)
        self.assertFalse(panel.pressed)
        panel._key(NS(keysym='q'));self.assertFalse(panel.poll())
        panel.close();root.destroy.assert_called_once()
        self.s.finish()
        text=''.join(p.read_text(encoding='utf-8') for p in self.s.directory.rglob('*') if p.is_file())
        self.assertNotIn('P02',text)
        self.assertNotIn('selected',text)


if __name__=='__main__':unittest.main()
