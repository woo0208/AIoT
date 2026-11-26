"""Numeric attribution tests only; no native windows or input injection."""
import unittest
from probe_ui_interaction import analyze,overlap,EventLog


class InteractionTests(unittest.TestCase):
    def test_overlap_and_long_call_attribution(self):
        self.assertEqual(overlap(0,5,5,10),0)
        rows=[dict(frame_id=1,key_start_ns=0,key_end_ns=600_000_000,key_cpu_ns=1_000_000,
                   tk_start_ns=0,tk_end_ns=1_000_000)]
        events=[dict(kind='action',action='cv_move',edge='start',perf_ns=50_000_000),
                dict(kind='action',action='cv_move',edge='end',perf_ns=700_000_000)]
        a=analyze(rows,events)
        self.assertEqual(a['long_calls'],[dict(frame_id=1,call='key',wall_ms=600,
                                             actions=['cv_move'],thread_cpu_ms=1)])
        self.assertEqual(a['action_summary']['cv_move']['max_key_ms'],600)

    def test_unmatched_marker_and_tk_delay_are_not_misattributed(self):
        rows=[dict(frame_id=1,key_start_ns=300_000_000,key_end_ns=301_000_000,key_cpu_ns=0,
                   tk_start_ns=0,tk_end_ns=200_000_000)]
        a=analyze(rows,[dict(kind='action',action='cv_move',edge='start',perf_ns=0)])
        self.assertEqual(a['marked_actions'],[])
        self.assertEqual(a['long_calls'][0]['call'],'tk')
        self.assertEqual(a['long_calls'][0]['actions'],[])

    def test_events_have_a_hard_bound(self):
        events=EventLog(limit=1,clock_ns=lambda:42)
        self.assertEqual(events.add('test')['perf_ns'],42)
        with self.assertRaises(RuntimeError):events.add('test')


if __name__=='__main__':unittest.main()
