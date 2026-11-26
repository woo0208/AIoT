"""Synthetic metadata/SDK tests only; no device, footage, fit, or evaluation."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np
import frame_provenance as fp
import performance_output as perf
import posture_geometry_probe as probe
from test_h9_probe_integration import SyntheticProbe
from test_h9_time_window import leaf_fixture_document


def child(number=1, timestamp=100., *, domain='hardware_clock', uid=1, stream='color', index=0):
    return NS(get_frame_number=lambda:number, get_timestamp=lambda:timestamp,
        get_frame_timestamp_domain=lambda:domain,
        get_profile=lambda:NS(unique_id=lambda:uid, stream_type=lambda:stream, stream_index=lambda:index),
        get_data=lambda:np.zeros((2,2,3),dtype=np.uint8) if stream=='color' else np.ones((2,2),dtype=np.uint16))


def pair(rgb, depth):
    return NS(get_color_frame=lambda:rgb, get_depth_frame=lambda:depth,
              get_frame_number=lambda:(depth or rgb).get_frame_number(), get_timestamp=lambda:(depth or rgb).get_timestamp())


class FrameProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_individual_fields_define_identity_not_number_alone(self):
        first=fp.snapshot(child())
        self.assertTrue(fp.compare(first,fp.snapshot(child()))['same_identity'])
        for other, number_changed, stamp_changed in ((child(timestamp=101),False,True),
                (child(number=2),True,False),(child(number=2,timestamp=101),True,True)):
            result=fp.compare(first,fp.snapshot(other))
            self.assertFalse(result['same_identity'])
            self.assertEqual(result['number_changed'],number_changed)
            self.assertEqual(result['timestamp_ms_changed'],stamp_changed)

    def test_gap_reset_wraparound_domain_and_profile_boundaries(self):
        first=fp.snapshot(child(10,100))
        self.assertEqual(fp.compare(first,fp.snapshot(child(14,200)))['source_gap'],3)
        for a,b in ((child(10,100),child(1,1)),(child(2**32-1,100),child(0,101)),
                    (child(),child(domain='system_time')),(child(),child(uid=2)),
                    (child(1,100),child(2,99)),(child(),child(stream='depth'))):
            comparison=fp.compare(fp.snapshot(a),fp.snapshot(b))
            self.assertTrue(comparison['boundary']); self.assertIsNone(comparison['source_gap'])
        self.assertEqual(fp.compare(first,fp.snapshot(child(14,200)))['timestamp_interval_ms'],100)

    def test_unavailable_or_invalid_sdk_fields_never_fabricated(self):
        for frame in (None,NS(),child(-1),child(timestamp=float('nan')),child(domain='unknown')):
            observed=fp.snapshot(frame)
            self.assertEqual(observed['status'],'NOT_MEASURED')
            self.assertEqual(fp.compare(fp.snapshot(child()),observed),dict(status='NOT_MEASURED'))

    def test_raw_rgb_only_depth_only_both_reused_and_align_selection_changes(self):
        diag=fp.FrameProvenance(self.root/'provenance')
        sequence=[(child(),child(stream='depth',uid=2)),
            (child(),child(2,200,stream='depth',uid=2)),
            (child(2,200),child(2,200,stream='depth',uid=2)),
            (child(2,200),child(2,200,stream='depth',uid=2))]
        for i,(rgb,depth) in enumerate(sequence):
            row=diag.begin_receive(); diag.received(row,True,pair(rgb,depth),diag.clock_ns(),i+1)
            diag.aligned(row,rgb,depth); diag.processing_started(row,i+1); diag.processing_completed(row)
        flags=[tuple(r['raw_vs_previous'][n]['same_identity'] for n in ('rgb','depth')) for r in diag.rows[1:]]
        self.assertEqual(flags,[(True,False),(False,True),(True,True)])
        row=diag.begin_receive(); diag.received(row,True,pair(child(3,300),child(3,300,stream='depth',uid=2)),diag.clock_ns(),5)
        diag.aligned(row,child(2,200),child(3,300,stream='depth',uid=99))
        self.assertFalse(row['raw_vs_aligned']['rgb']['same_identity'])
        self.assertTrue(row['raw_vs_aligned']['depth']['same_identity'])
        self.assertTrue(row['raw_vs_aligned']['depth']['profile_uid_changed'])
        diag.finish(status='FAILED',error=ValueError('synthetic'))
        lines=[json.loads(s) for s in (diag.directory/'frames.jsonl').read_text().splitlines()]
        self.assertEqual(len(lines),5)
        summary=json.loads((diag.directory/'summary.json').read_text())
        self.assertEqual(summary['status'],'FAILED')
        self.assertGreater(summary['observer_call_cost_total_ns'],0)
        self.assertEqual(summary['journal_sha256'],perf.sha256(diag.directory/'frames.jsonl'))
        self.assertNotIn('get_data',json.dumps(lines))

    def run_probe(self,name,enabled,*,headless=True,error=None,invalid=False,timeout=False,h9=False,repeat=False):
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO())); stack.enter_context(redirect_stderr(io.StringIO()))
            fake=SyntheticProbe(NS(enterContext=stack.enter_context),[0,100,200,300],keys=[-1]*4)
            pin=self.root/'SYNTHETIC-pin.bin'
            if not pin.exists():pin.write_bytes(b'SYNTHETIC_NOT_A_REAL_MODEL')
            sys.modules['analyze_d455'].ensure_models=lambda:dict(pose=pin,mesh=pin,face=pin)
            # Accessors only: distinguish the SDK receive pair from aligned output.
            def receive(_):
                index=receive.index; receive.index+=1; fake.clock.set_ms(index*100)
                if fake.sessions:fake.sessions[0].runtime.tick()
                if error=='receive' and index==1:raise RuntimeError('synthetic receive error')
                if timeout:return False,None
                number,stamp=(1,100) if repeat else (index+1,100+index)
                return True,pair(child(number,stamp),None if invalid else child(number,stamp,uid=2,stream='depth'))
            receive.index=0
            fake.pipeline.try_wait_for_frames.side_effect=receive
            def align(frames):
                if invalid:return frames
                color=frames.get_color_frame(); depth=frames.get_depth_frame()
                return pair(child(color.get_frame_number(),color.get_timestamp()),
                    child(depth.get_frame_number(),depth.get_timestamp(),uid=20,stream='depth'))
            sys.modules['pyrealsense2'].align=lambda _:NS(process=align)
            if isinstance(error,BaseException):fake.calculate.side_effect=error
            model=None
            if h9:
                model=self.root/'SYNTHETIC-h9.json'
                if not model.exists():perf._write_json(model,leaf_fixture_document())
            kwargs=dict(headless=headless,duration_seconds=4.1 if h9 else .3,show_3d_views='none',
                performance_output_dir=str(self.root/(name+'-performance')),frame_callback=fake.callbacks.append,
                h9_model_path=str(model) if model else None)
            if enabled:kwargs['frame_provenance_dir']=str(self.root/(name+'-provenance'))
            if error:
                with self.assertRaises(RuntimeError if error=='receive' else type(error)):probe.run_probe(**kwargs)
            else:probe.run_probe(**kwargs)
            doc=json.loads((self.root/(name+'-performance')/'performance.json').read_text())
            side=None
            if enabled:
                directory=self.root/(name+'-provenance')
                side=dict(summary=json.loads((directory/'summary.json').read_text()),
                    rows=[json.loads(r) for r in (directory/'frames.jsonl').read_text().splitlines()])
            return doc,side,fake

    def test_actual_probe_receive_align_processing_boundaries_and_deadline(self):
        document,side,fake=self.run_probe('path',True)
        self.assertEqual(len(side['rows']),4)
        self.assertEqual([r['status'] for r in side['rows']],['completed']*3+['deadline_skip'])
        self.assertEqual([r['token'] for r in side['rows']],[1,2,3,4])
        self.assertEqual(fake.calculate.call_count,3)
        for r in side['rows'][:3]:
            self.assertLessEqual(r['receive_call_start_qpc_ns'],r['receive_call_end_qpc_ns'])
            self.assertLessEqual(r['receive_call_end_qpc_ns'],r['align_return_observed_qpc_ns'])
            self.assertLessEqual(r['align_return_observed_qpc_ns'],r['processing_start_qpc_ns'])
            self.assertLessEqual(r['processing_start_qpc_ns'],r['processing_end_qpc_ns'])
            self.assertTrue(r['raw_vs_aligned']['depth']['same_identity'])
            self.assertTrue(r['raw_vs_aligned']['depth']['profile_uid_changed'])
        self.assertEqual(document['run_status'],'COMPLETED')

    def test_same_pair_returned_by_sdk_is_observed_without_filtering(self):
        doc,side,fake=self.run_probe('repeated',True,repeat=True)
        self.assertEqual(fake.calculate.call_count,3)
        self.assertEqual(doc['timing']['counts']['processed_frames'],3)
        for row in side['rows'][1:]:
            self.assertTrue(all(row['raw_vs_previous'][n]['same_identity'] for n in ('rgb','depth')))

    def test_opt_in_off_preserves_timing_events_csv_schema_and_h9_calls(self):
        results=[]
        for enabled in (False,True):
            document,side,fake=self.run_probe('equiv'+str(enabled),enabled,h9=True)
            results.append((document,fake))
            if not enabled:self.assertFalse((self.root/'equivFalse-provenance').exists())
        a,b=(r[0] for r in results)
        self.assertEqual(a['timing'],b['timing'])
        self.assertEqual(a['events'],b['events'])
        for fake in (r[1] for r in results):
            self.assertEqual(fake.pose.detect_for_video.call_count,41)
            self.assertEqual(fake.face.detect_for_video.call_count,41)
            self.assertEqual(fake.calculate.call_count,41)
            self.assertEqual(fake.sessions[0].runtime.engine.rf_calls,1)
        for name,fields in perf.CSV_FIELDS.items():
            for enabled in (False,True):
                import csv
                with (self.root/('equiv'+str(enabled)+'-performance')/name).open(encoding='utf-8',newline='') as stream:
                    self.assertEqual(next(csv.reader(stream)),list(fields))
        self.assertEqual(set(a['timing']),set(b['timing']))
        self.assertEqual(results[0][1].sessions[0].events,results[1][1].sessions[0].events)

    def test_timeout_and_invalid_pair_duration_exit(self):
        for kind in ('timeout','invalid'):
            doc,side,fake=self.run_probe(kind,True,timeout=kind=='timeout',invalid=kind=='invalid')
            self.assertEqual(doc['timing']['termination']['reason'],'duration_elapsed')
            self.assertEqual(side['summary']['status'],'COMPLETED')
            self.assertEqual(fake.calculate.call_count,0)
            self.assertEqual(side['rows'][0]['status'],'timeout' if kind=='timeout' else 'invalid_pair')

    def test_exception_interrupt_and_receive_exception_preserve_pending_evidence(self):
        for index,error in enumerate((RuntimeError('synthetic geometry'),KeyboardInterrupt(),'receive')):
            doc,side,fake=self.run_probe('error'+str(index),True,error=error)
            self.assertEqual(side['summary']['status'],'INTERRUPTED' if isinstance(error,KeyboardInterrupt) else 'FAILED')
            self.assertEqual(side['rows'][-1]['status'],'waiting' if error=='receive' else 'processing')
            fake.pipeline.stop.assert_called_once()

    def test_ui_path_preserved_and_no_pixels_saved(self):
        _,side,fake=self.run_probe('ui',True,headless=False)
        self.assertEqual(fake.cv.imshow.call_count,3)
        self.assertEqual(fake.cv.waitKey.call_count,3)
        self.assertEqual({p.name for p in (self.root/'ui-provenance').iterdir()},
            {'manifest.json','frames.jsonl','summary.json'})
        self.assertNotIn('pixels',json.dumps(side))

    def test_cli_guard_paths_and_exclusive_output(self):
        with self.assertRaises(SystemExit):probe.parse_args(['--frame-provenance-dir','unused'])
        with self.assertRaises(ValueError):probe.run_probe(frame_provenance_dir='unused')
        fp.FrameProvenance(self.root/'reserved')
        with self.assertRaises(FileExistsError):fp.FrameProvenance(self.root/'reserved')
        with self.assertRaises(ValueError):
            probe.run_probe(frame_provenance_dir=str(self.root/'nested'),duration_seconds=1,
                performance_output_dir=str(self.root/'nested/performance'))


if __name__=='__main__':unittest.main()
