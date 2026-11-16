"""Structural harness tests only; actual native GUI benchmark is separate."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import benchmark_ui_native as bench
from probe_diagnostics import ProbeDiagnostics
from test_e0_fs3 import Clock


class NativeBenchmarkTests(unittest.TestCase):
    def test_real_clock_boundaries_are_injectable_without_opening_gui(self):
        for variant,event_ms in [('E0',13),('E1',3)]:
            with tempfile.TemporaryDirectory() as folder:
                clock=Clock()
                diag=ProbeDiagnostics(Path(folder)/'timing',clock_ns=clock,retain_raw=False)
                session=bench.UIOnlySession(diag)
                panel=NS(control=NS(session=session),poll=lambda:(clock.add_ms(5) or True))
                cv=NS(imshow=Mock(side_effect=lambda *args:clock.add_ms(2)),
                      waitKey=Mock(side_effect=lambda delay:(clock.add_ms(13) or -1)),
                      pollKey=Mock(side_effect=lambda:(clock.add_ms(3) or -1)))
                row=bench.frame_step(diag,panel,cv,variant,None,1,20_000_000,
                    clock_ns=clock,sleep=lambda seconds:clock.add_ms(seconds*1000))
                self.assertEqual(row['tk_poll_ns'],5_000_000)
                self.assertEqual(row['synthetic_ready_ns'],20_000_000)
                self.assertEqual(row['key_wait_ns'],event_ms*1_000_000)
                self.assertEqual(row['loop_ns'],(22+event_ms)*1_000_000)
                if variant=='E1':cv.waitKey.assert_not_called()
                else:cv.pollKey.assert_not_called()
                diag.finish(status='COMPLETED')

    def test_interference_interrupts_without_saving_key_values(self):
        with tempfile.TemporaryDirectory() as folder:
            diag=ProbeDiagnostics(Path(folder)/'timing',retain_raw=False)
            session=bench.UIOnlySession(diag)
            panel=NS(control=NS(session=session),poll=lambda:True)
            cv=NS(imshow=Mock(),pollKey=Mock(return_value=ord('x')))
            with self.assertRaises(InterruptedError):
                bench.frame_step(diag,panel,cv,'E1',None,1,0)
            session.interference=True
            cv.imshow.reset_mock()
            with self.assertRaises(InterruptedError):
                bench.frame_step(diag,panel,cv,'E1',None,2,0)
            cv.imshow.assert_not_called()
            diag.finish(status='INTERRUPTED')

    def test_median_trial_percentiles_and_worst_case_are_distinct(self):
        runs=[]
        for variant,values in [('E0',[1,3,100]),('E1',[.1,.2,.3])]:
            for value in values:
                stats=dict(p50=value,p95=value,p99=value,maximum=value+1)
                runs.append(dict(variant=variant,stages={n:stats for n in
                    ['ui.key_wait','ui.tk_poll','latency.synthetic_ready_to_complete',
                     'latency.loop_start_to_frame_complete']},submitted_fps=15,
                    resources=dict(statistics=dict(process_cpu_one_core_percent=dict(p95=1),
                                   rss_bytes=dict(maximum=10*2**20)))))
        summary=bench.summarize(runs)
        self.assertEqual(summary['E0']['key_p95_ms'],3)
        self.assertEqual(summary['E0']['key_worst_ms'],101)
        self.assertEqual(summary['E1']['key_p95_ms'],.2)
        text=bench.report_text(dict(frames=225,fps=15,summary=summary))
        self.assertIn('not maximum throughput or D455',text)
        self.assertIn('No camera',text)
        self.assertEqual(text,bench.report_text(json.loads(json.dumps(
            dict(frames=225,fps=15,summary=summary),sort_keys=True))))
        self.assertTrue(next(line for line in text.splitlines() if line.startswith('|E0|')).startswith('|E0|3.0000|3.0000|3.0000|101.0000|'))

    def test_invalid_parameters_never_launch_worker(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(bench,'worker') as worker:
            for extra in [['--frames','0'],['--fps','0'],['--fps','nan'],['--fps','inf']]:
                with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    bench.main(['--worker','E0','--output-dir',folder]+extra)
            worker.assert_not_called()

    def test_existing_output_is_not_overwritten_or_retried(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(bench.subprocess,'run') as run:
            with self.assertRaises(FileExistsError):bench.main(['--output-dir',folder])
            run.assert_not_called()


if __name__=='__main__':unittest.main()
