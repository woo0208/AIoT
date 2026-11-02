"""Synthetic structural tests only; no participant CSV or accuracy calculation.

One fixed existing M0 forest is fitted to synthetic inputs for serialization
tests. Production training is separately restricted to the authorized hashes.
"""

import copy
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np

import f1_sample_aggregator as aggregation
import h9_m0 as m0
import h9_csv_replay as replay
import rf_experiment as rf
from test_h9_csv_replay import FIELDS, csv_row, frame


def resign(document, *, update_model=False):
    if update_model:
        document['payload']['metadata']['model_sha256'] = m0._digest(document['payload']['model'])
    signed = {k: document[k] for k in ('artifact_format', 'payload')}
    document['integrity']['sha256'] = m0._digest(signed)
    return document


class H9M0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(12345)
        cls.X = rng.normal(size=(20, 9))
        cls.y = np.arange(20) % 5
        cls.native = rf.Forest(5, 500, 2, None, 0).fit(cls.X, cls.y)
        data = dict(matrix=cls.X.tolist(), labels=cls.y.tolist(),
                    note='synthetic structural inputs only')
        cls.template = m0._signed_document(cls.native, dict(
            dataset_role='synthetic-structural', data=data,
            input_matrix_sha256=m0._digest(data), sample_count=20))

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.document = copy.deepcopy(self.template)
        self.enterContext(patch.object(rf, 'fit_models', side_effect=AssertionError('no weighted models/LOSO')))
        self.enterContext(patch.object(m0.offline, 'evaluate_samples', side_effect=AssertionError('no accuracy evaluation')))

    def artifact(self):
        path = self.root/'model.json'
        m0._write_new(path, self.document)
        return path

    def test_serialized_file_uses_native_rf_prediction_with_exact_probabilities(self):
        path = self.artifact()
        before = path.read_bytes()
        with patch.object(rf.Forest, 'fit', side_effect=AssertionError('load must not fit')):
            loaded = m0.load_model(path)
        probes = np.vstack([self.X, np.zeros((1,9)), np.full((1,9),100), np.full((1,9),-100)])
        self.assertIs(type(loaded.forest), rf.Forest)
        self.assertTrue(all(type(tree) is rf.Tree for tree in loaded.forest.trees))
        np.testing.assert_array_equal(loaded.predict(probes), self.native.predict(probes))
        np.testing.assert_array_equal(rf._forest_probabilities(loaded.forest, probes), rf._forest_probabilities(self.native, probes))
        self.assertEqual((loaded.forest.K, loaded.forest.T, loaded.forest.mf, loaded.forest.seed), (5,500,2,0))
        self.assertEqual(path.read_bytes(), before)

    def test_integrity_and_model_hash_tampering_rejected(self):
        self.document['payload']['model']['trees'][0]['threshold'][0] += .1
        with self.assertRaisesRegex(m0.ArtifactError, 'integrity'):
            m0.model_from_document(self.document)
        resign(self.document)
        with self.assertRaisesRegex(m0.ArtifactError, 'model/feature hash'):
            m0.model_from_document(self.document)

    def test_feature_class_units_aggregation_and_purpose_cannot_change(self):
        changes = [('feature_order', list(reversed(m0.FEATURE_ORDER))),
                   ('class_order', list(reversed(m0.CLASS_ORDER))),
                   ('feature_units', ['m']*9), ('aggregation_spec','other'),
                   ('purpose','formal performance model'), ('scope','auxiliary6')]
        for key,value in changes:
            doc = copy.deepcopy(self.template)
            doc['payload']['metadata'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(m0.ArtifactError, 'contract mismatch'):
                m0.model_from_document(resign(doc))

    def test_fixed_budget_seed_and_unweighted_configuration_enforced(self):
        for key,value in [('trees',499),('max_features',3),('seed',1),('seed',False),
                          ('trees',500.0),('bootstrap',1),('implementation','weighted')]:
            doc = copy.deepcopy(self.template)
            doc['payload']['metadata']['configuration'][key] = value
            with self.subTest(key=key,value=value), self.assertRaisesRegex(m0.ArtifactError, 'configuration'):
                m0.model_from_document(resign(doc))

    def test_bad_tree_topology_indices_and_probabilities_rejected(self):
        for variant in ('feature','cycle','shared','width','negative','unreachable'):
            doc = copy.deepcopy(self.template)
            tree = doc['payload']['model']['trees'][0]
            if variant == 'feature':tree['feature'][0] = 9
            elif variant == 'cycle':tree['left'][0] = 0
            elif variant == 'shared':tree['right'][0] = tree['left'][0]
            elif variant == 'width':tree['probability'][0] = [1.0,0,0]
            elif variant == 'negative':tree['probability'][0] = [-1.0,2.0,0,0,0]
            else:
                for key,value in [('feature',-1),('threshold',-1),('left',-1),('right',-1),('probability',[1,0,0,0,0])]:
                    tree[key].append(value)
            with self.subTest(variant=variant), self.assertRaises(m0.ArtifactError):
                m0.model_from_document(resign(doc, update_model=True))

    def test_duplicate_json_nonfinite_and_f1_artifact_format_rejected(self):
        path = self.root/'duplicate.json'
        with path.open('x',encoding='utf-8') as f:f.write('{"artifact_format":1,"artifact_format":2}')
        with self.assertRaisesRegex(m0.ArtifactError, 'duplicate JSON'):
            m0.load_model(path)
        doc = copy.deepcopy(self.template)
        doc['payload']['model']['trees'][0]['threshold'][0] = float('nan')
        with self.assertRaises(m0.ArtifactError):m0.model_from_document(doc)
        doc = copy.deepcopy(self.template)
        doc['artifact_format'] = m0.artifact_helpers.ARTIFACT_FORMAT
        with self.assertRaisesRegex(m0.ArtifactError, 'format'):
            m0.model_from_document(resign(doc))

    def test_rf_hash_and_development_input_provenance_enforced(self):
        doc = copy.deepcopy(self.template)
        doc['payload']['metadata']['code'] = []
        with self.assertRaisesRegex(m0.ArtifactError, 'implementation hash'):
            m0.model_from_document(resign(doc))
        for change in ('role','data'):
            doc = copy.deepcopy(self.template)
            training = doc['payload']['metadata']['training']
            if change == 'role':training['dataset_role'] = 'formal'
            else:training['data']['matrix'][0][0] += 1
            with self.subTest(change=change), self.assertRaisesRegex(m0.ArtifactError, 'provenance'):
                m0.model_from_document(resign(doc))

    def test_prediction_requires_exact_order_numeric_finite_nine_columns(self):
        model = m0.model_from_document(self.document)
        for X in (np.ones((2,8)),np.ones(9),np.full((1,9),np.nan),np.full((1,9),np.inf),
                  np.ones((1,9),dtype=bool),[['1']*9]):
            with self.subTest(shape=np.shape(X)), self.assertRaises(ValueError):model.predict(X)
        with self.assertRaisesRegex(ValueError, 'order'):
            model.predict(self.X, feature_order=tuple(reversed(m0.FEATURE_ORDER)))

    def test_sample_gate_rejects_p5_and_ineligible_before_forest_prediction(self):
        model = m0.model_from_document(self.document)
        primary = aggregation.aggregate_h5_h9_sample(frame(i).record for i in range(1,31))
        p5 = aggregation.aggregate_h5_h9_sample(frame(i,label='body_forward').record for i in range(1,31))
        invalid = replace(primary, eligible=False, eligibility_reasons=('synthetic missing support',))
        with patch.object(model.forest, 'predict', side_effect=AssertionError('must not infer')):
            with self.assertRaisesRegex(ValueError, 'outside primary5'):model.predict_sample(p5)
            with self.assertRaisesRegex(ValueError, 'ineligible'):model.predict_sample(invalid)
        with self.assertRaisesRegex(ValueError, 'aggregation'):
            model.predict_sample(replace(primary,aggregation_spec='other'))

    def test_replay_only_eligible_primary5_and_preserves_artifact_and_csv(self):
        model_path = self.artifact()
        frames = [frame(i,segment=segment,label=label)
                  for start,count,segment,label in ((1,30,'1','upright'),(31,30,'3','body_forward'),
                                                   (61,29,'5','forward_head'),(90,30,'7','lean_back'))
                  for i in range(start,start+count)]
        csv_path = self.root/'synthetic.csv'
        with csv_path.open('x',encoding='utf-8',newline='') as f:
            writer = csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(csv_row(x) for x in frames)
        before_model,before_csv = model_path.read_bytes(),csv_path.read_bytes()
        original = m0.H9M0Model.predict_sample
        with patch.object(rf.Forest,'fit',side_effect=AssertionError('inference must not fit')):
            with patch.object(m0.H9M0Model,'predict_sample',autospec=True,side_effect=original) as predict:
                result = m0.replay_inference([csv_path],model_path)
        self.assertEqual(predict.call_count,2)
        self.assertEqual([c.args[1].label for c in predict.call_args_list],['upright','lean_back'])
        self.assertEqual(result['status_counts'],dict(predicted=2,outside_primary5=1,ineligible=1))
        self.assertIsNone(result['segments'][1]['prediction_index'])
        self.assertIsNone(result['segments'][2]['prediction_index'])
        self.assertEqual(result['training_dataset_role'],'synthetic-structural')
        self.assertEqual(model_path.read_bytes(),before_model)
        self.assertEqual(csv_path.read_bytes(),before_csv)
        self.assertNotIn('accuracy',result)

    def test_build_scope_and_output_guard_fail_before_fit(self):
        csv_path = self.root/'unapproved.csv'
        csv_path.write_text('synthetic; not an authorized pilot',encoding='utf-8')
        model,report = self.root/'model.json',self.root/'report.json'
        with patch.object(rf.Forest,'fit',side_effect=AssertionError('must not fit')):
            with self.assertRaisesRegex(ValueError, 'authorized'):
                m0.build_development_model([csv_path,csv_path],model,report)
            model.write_text('keep existing artifact',encoding='utf-8')
            with self.assertRaisesRegex(FileExistsError, 'overwrite'):
                m0.build_development_model([csv_path],model,report)
        self.assertEqual(model.read_text(encoding='utf-8'),'keep existing artifact')
        self.assertFalse(report.exists())

    def test_cli_output_exists_prevents_loading_or_inference(self):
        output = self.root/'keep.json';output.write_text('keep',encoding='utf-8')
        with patch.object(m0,'replay_inference',side_effect=AssertionError('must not replay')):
            with self.assertRaisesRegex(FileExistsError,'overwrite'), redirect_stdout(io.StringIO()):
                m0.main(['replay','--probe-csv','unused.csv','--model','unused.json','--output',str(output)])
        self.assertEqual(output.read_text(encoding='utf-8'),'keep')


if __name__ == '__main__':unittest.main()
