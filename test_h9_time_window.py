"""Synthetic window-state tests with a hand-constructed RF leaf fixture; no fit."""

from dataclasses import replace
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np

import f1_sample_aggregator as aggregation
import h9_m0 as m0
import h9_time_window as window
import rf_experiment as rf
from test_h9_csv_replay import frame


def leaf_fixture_document():
    forest = rf.Forest(5,500,2,None,0)
    forest.trees = []
    for _ in range(500):
        tree = rf.Tree(5,2,np.ones(9),None)
        tree.feat = np.array([-1]);tree.thr = np.array([-1.0])
        tree.left = np.array([-1]);tree.right = np.array([-1])
        tree.value = np.array([[.4,.3,.2,.05,.05]])
        forest.trees.append(tree)
    data = dict(note='synthetic constant-leaf structural fixture; never trained')
    return m0._signed_document(forest,dict(dataset_role='synthetic-structural',data=data,
                                         input_matrix_sha256=m0._digest(data)))


def observation(index, time, *, segment='1', label='upright', missing=(), unlabelled=False):
    f = window.H9WindowInput.from_replay(frame(index,segment=segment,label=label,
                                              timestamp=str(time),missing=missing))
    return replace(f,segment_id=None,source_label=None) if unlabelled else f


class H9TimeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = leaf_fixture_document()

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(rf.Forest,'fit',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(rf,'fit_models',side_effect=AssertionError('no training')))
        self.enterContext(patch.object(m0.offline,'evaluate_samples',side_effect=AssertionError('no scores')))
        self.model = m0.model_from_document(self.document)
        self.engine = window.H9TimeWindow(self.model)

    def feed(self, count=41, *, start=0, interval=100, index=1, **kwargs):
        outputs=[]
        for j in range(count):
            outputs.extend(self.engine.push(observation(index+j,start+j*interval,**kwargs)))
        return outputs

    def test_collecting_until_four_seconds_and_exact_one_second_ticks(self):
        with patch.object(self.model,'predict',wraps=self.model.predict) as predict:
            outputs = self.feed()
        self.assertEqual([r['observed_at_ms'] for r in outputs],['0','1000','2000','3000','4000'])
        self.assertEqual([r['status'] for r in outputs],['COLLECTING']*4+['PREDICTED'])
        self.assertEqual(predict.call_count,1)
        self.assertTrue(all(r['prediction_index'] is None for r in outputs[:-1]))
        self.assertEqual(outputs[-1]['prediction_label'],'upright')
        self.assertEqual(outputs[-1]['model_sha256'],self.model.metadata['model_sha256'])

    def test_left_open_right_closed_window_and_original_aggregate(self):
        inputs=[observation(i+1,i*100) for i in range(41)]
        outputs=[]
        for f in inputs:outputs.extend(self.engine.push(f))
        result=outputs[-1]
        self.assertEqual(result['input_frame_indices'],list(range(2,42)))
        self.assertEqual(result['input_frame_range'],[2,41])
        self.assertEqual((result['window_start_ms'],result['window_end_ms']),('0','4000'))
        # Relabel only sample identity, then use the original aggregation implementation.
        records=[aggregation.HFrameRecord('synthetic','synthetic-recording',f.frame_index,
                    'synthetic-subject',None,'window','upright',f.features) for f in inputs[1:]]
        expected=aggregation.aggregate_h5_h9_sample(records)
        self.assertEqual(result['features'],list(expected.ordered_values('H9')))
        self.assertEqual(result['common_valid_frame_indices'],list(expected.common_valid_frame_indices))
        self.assertEqual(result['missing_counts'],dict(expected.missing_counts))

    def test_window_slides_without_frame_count_approximation_or_future_leakage(self):
        outputs=self.feed(51)
        predictions=[r for r in outputs if r['status']=='PREDICTED']
        self.assertEqual([r['input_frame_range'] for r in predictions],[[2,41],[12,51]])
        engine=window.H9TimeWindow(self.model)
        outputs=[]
        for i,t in enumerate(range(0,4000,100),1):outputs.extend(engine.push(observation(i,t)))
        # Frame at 4050 must not enter the scheduled snapshot at 4000.
        outputs.extend(engine.push(observation(41,4050)))
        at_four=next(r for r in outputs if r['window_end_ms']=='4000')
        self.assertEqual(at_four['input_frame_range'],[2,40])
        self.assertNotIn(41,at_four['input_frame_indices'])

    def test_insufficient_data_keeps_original_missing_support_and_denominator(self):
        name=m0.FEATURE_ORDER[-1]
        for i in range(61):
            self.engine.push(observation(i+1,i*50,missing=(name,) if i>30 else ()))
        result=self.engine.tick(4000)[-1]
        self.assertEqual(result['status'],'PREDICTED')
        self.assertEqual((result['frame_count'],result['common_valid_count'],result['common_coverage']),(60,30,.5))
        self.engine=window.H9TimeWindow(self.model)
        for i in range(61):
            self.engine.push(observation(i+1,i*50,missing=(name,) if i>=30 else ()))
        with patch.object(self.model,'predict',side_effect=AssertionError('no inference')):
            result=self.engine.tick(4000)[-1]
        self.assertEqual(result['status'],'INSUFFICIENT_DATA')
        self.assertIn('common_valid_frames<30',result['reasons'])
        self.assertIn('common_coverage<0.5',result['reasons'])
        self.assertIsNone(result['prediction_label'])

    def test_circular_mean_undefined_is_still_ineligible_with_sufficient_frames(self):
        for i in range(41):
            f=observation(i+1,i*100)
            values=dict(f.features);values[aggregation.H_FACE_AXIS_FEATURE]=90 if i%2 else -90
            outputs=self.engine.push(replace(f,features=values))
        result=outputs[-1]
        self.assertEqual(result['common_valid_count'],40)
        self.assertEqual(result['status'],'INSUFFICIENT_DATA')
        self.assertIn('face_axis_circular_mean_undefined',result['reasons'])

    def test_stale_timer_suppresses_previous_prediction_and_recovery_recollects(self):
        self.feed()
        self.assertNotEqual(self.engine.tick(5000)[-1]['status'],'STALE')
        with patch.object(self.model,'predict',side_effect=AssertionError('no stale inference')):
            outputs=self.engine.tick(7000)
        self.assertEqual([r['status'] for r in outputs[-2:]],['STALE','STALE'])
        self.assertTrue(all(r['prediction_label'] is None for r in outputs if r['status']=='STALE'))
        self.assertEqual(outputs[-1]['frame_count'],0)
        recovered=self.engine.push(observation(42,7100))
        self.assertEqual(recovered[-1]['status'],'COLLECTING')
        self.assertEqual(recovered[-1]['input_frame_range'],[42,42])
        self.assertEqual(recovered[-1]['accumulation_start_ms'],'7100')
        for j in range(1,41):recovered=self.engine.push(observation(42+j,7100+j*100))
        self.assertEqual(recovered[-1]['status'],'PREDICTED')
        self.assertEqual(recovered[-1]['input_frame_range'],[43,82])

    def test_pause_before_window_full_becomes_stale_and_timer_cannot_reverse(self):
        self.engine.push(observation(1,0))
        outputs=self.engine.tick(2000)
        self.assertEqual([r['status'] for r in outputs],['COLLECTING','STALE'])
        with self.assertRaisesRegex(ValueError,'out-of-order'):self.engine.tick(1999)
        with self.assertRaisesRegex(ValueError,'late/out-of-order'):self.engine.push(observation(2,1999))

    def test_before_first_input_is_collecting_and_gap_push_cannot_reuse_old_window(self):
        self.assertEqual(self.engine.tick(0)[0]['status'],'COLLECTING')
        self.assertEqual(self.engine.tick(3000)[-1]['status'],'COLLECTING')
        self.engine=window.H9TimeWindow(self.model)
        self.feed()
        outputs=self.engine.push(observation(42,8000))
        self.assertIn('STALE',[r['status'] for r in outputs])
        self.assertEqual(outputs[-1]['status'],'COLLECTING')
        self.assertEqual(outputs[-1]['input_frame_indices'],[42])

    def test_csv_segment_or_label_change_and_manual_reset_clear_window(self):
        self.feed()
        changed=self.engine.push(observation(42,4100,segment='3',label='forward_head'))[-1]
        self.assertEqual(changed['event'],'context_reset')
        self.assertEqual(changed['status'],'COLLECTING')
        self.assertEqual(changed['input_frame_indices'],[42])
        changed=self.engine.push(observation(43,4200,segment='3',label='lean_back'))[-1]
        self.assertEqual(changed['status'],'COLLECTING')
        self.assertEqual(changed['input_frame_indices'],[43])
        reset=self.engine.reset(4250)
        self.assertEqual(reset['event'],'manual_reset')
        self.assertIsNone(reset['prediction_label'])
        self.assertEqual(reset['frame_count'],0)
        resumed=self.engine.push(observation(44,4300,segment='3',label='lean_back'))[-1]
        self.assertEqual(resumed['accumulation_start_ms'],'4300')
        self.assertEqual(resumed['input_frame_indices'],[44])

    def test_csv_prep_transition_and_p5_block_inference(self):
        for label in ('PREP','TRANSITION','body_forward'):
            self.engine=window.H9TimeWindow(self.model)
            with patch.object(self.model,'predict',side_effect=AssertionError('excluded labels cannot infer')):
                outputs=self.feed(label=label)
            self.assertTrue(all(r['status']=='INSUFFICIENT_DATA' for r in outputs))
            self.assertTrue(all(r['prediction_index'] is None for r in outputs))
            self.assertTrue(all(r['scope_basis']=='csv_label' for r in outputs))

    def test_unlabelled_input_never_uses_geometry_to_detect_transition_or_p5(self):
        outputs=[]
        for i in range(51):
            f=observation(i+1,i*100,unlabelled=True)
            if i>=35:
                f=replace(f,features={k:(v+1000 if k!=aggregation.H_FACE_AXIS_FEATURE else v)
                                      for k,v in f.features.items()})
            outputs.extend(self.engine.push(f))
        predictions=[r for r in outputs if r['status']=='PREDICTED']
        self.assertEqual(len(predictions),2)
        self.assertEqual(len({r['generation'] for r in outputs}),1)
        self.assertTrue(all(r['source_label'] is None for r in outputs))
        self.assertTrue(all('no_automatic' in r['scope_basis'] for r in outputs))
        reset=self.engine.reset(5050)
        self.assertEqual(reset['status'],'COLLECTING')
        self.assertEqual(reset['frame_count'],0)

    def test_duplicate_order_recording_and_invalid_context_fail_before_consumption(self):
        self.engine.push(observation(1,0))
        self.engine.push(observation(2,100))
        for f in (observation(2,100),observation(1,200),observation(3,50),
                  replace(observation(3,200),recording_id='other')):
            with self.assertRaises(ValueError):self.engine.push(f)
        self.engine.push(observation(3,200))
        self.assertEqual(self.engine._last_input.frame_index,3)
        for fields in (dict(segment_id=None),dict(features=None),dict(source_label='bad-label')):
            with self.assertRaises(ValueError):replace(observation(4,300),**fields)

    def test_same_device_times_are_not_deduplicated_and_output_ids_are_unique(self):
        outputs=self.engine.push(observation(1,'0.000'))
        outputs+=self.engine.push(observation(2,'0.000'))
        for i in range(3,43):outputs+=self.engine.push(observation(i,(i-2)*100))
        ids=[r['window_id'] for r in outputs]
        self.assertEqual(len(ids),len(set(ids)))
        first=self.engine._last_input
        self.assertEqual(first.frame_index,42)
        # Both equal-time inputs are retained before they reach the open left boundary.
        e=window.H9TimeWindow(self.model);e.push(observation(1,'1000.000'));e.push(observation(2,'1000.000'))
        out=e.tick(2000)[-1]
        self.assertEqual(out['input_frame_indices'],[1,2])
        self.assertEqual(out['input_device_timestamp_range'],['1000.000','1000.000'])

    def test_cli_exclusive_output_guard_prevents_any_replay(self):
        output=self.root/'keep.json';output.write_text('keep',encoding='utf-8')
        with patch.object(window,'run_csv_windows',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(FileExistsError,'overwrite'),redirect_stdout(io.StringIO()):
                window.main(['--probe-csv','unused.csv','--model','unused.json','--output',str(output)])
        self.assertEqual(output.read_text(encoding='utf-8'),'keep')


if __name__ == '__main__':unittest.main()
