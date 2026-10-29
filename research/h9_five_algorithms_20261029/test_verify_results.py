"""Saved-output regression and tamper checks. No fit, camera or timing runs."""
import ast
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import unittest

import verify_results as v

ROOT = Path(__file__).resolve().parent


class SavedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = json.loads((ROOT/'aggregate_results.json').read_text(encoding='utf-8'))

    def test_all_75_cases_match_confusion_counts(self):
        self.assertEqual(v.verify(self.saved)['recomputed_seed_scope_cases'], 75)

    def test_participant_macro_mean_cannot_replace_pooled_macro(self):
        d = copy.deepcopy(self.saved)
        d['results']['M0']['scopes']['pooled']['mean']['macro_f1'] = d['participant_mean_macro_f1']['M0']
        with self.assertRaisesRegex(ValueError, 'mean macro_f1'):
            v.verify(d)

    def test_reported_class_precision_corruption_is_rejected(self):
        d = copy.deepcopy(self.saved)
        d['results']['Logistic-Regression']['scopes']['pooled']['per_seed'][0]['per_class'][2]['precision'] = 1.
        with self.assertRaisesRegex(ValueError, 'precision'):
            v.verify(d)

    def test_confusion_matrix_corruption_is_rejected(self):
        d = copy.deepcopy(self.saved)
        d['results']['M0']['scopes']['participant_A']['per_seed'][0]['confusion_matrix'][0][0] += 1
        with self.assertRaises(ValueError):
            v.verify(d)

    def test_seed_order_corruption_is_rejected(self):
        d = copy.deepcopy(self.saved)
        d['results']['KNN']['scopes']['pooled']['per_seed'][0]['seed'] = 100
        with self.assertRaisesRegex(ValueError, 'seed'):
            v.verify(d)

    def test_seed_sd_corruption_is_rejected(self):
        d = copy.deepcopy(self.saved)
        d['results']['M0']['scopes']['pooled']['sd_ddof0']['macro_f1'] = 0.
        with self.assertRaisesRegex(ValueError, 'seed SD'):
            v.verify(d)

    def test_p1_error_corruption_is_rejected(self):
        d = copy.deepcopy(self.saved)
        d['results']['Logistic-Regression']['scopes']['pooled']['mean_p1_errors']['P1_to_P5']['rate'] = .25
        with self.assertRaisesRegex(ValueError, 'P1 error'):
            v.verify(d)

    def test_sample_level_predictions_are_rejected(self):
        d = copy.deepcopy(self.saved)
        d['results']['KNN']['predictions_by_seed'] = []
        with self.assertRaisesRegex(ValueError, 'sample-level'):
            v.verify(d)

    def test_logistic_p0_p1_and_all_error_types(self):
        row = self.saved['logistic_regression_error_summary']
        self.assertEqual(row['P0_recall'], .5)
        self.assertEqual(row['P1_recall'], .75)
        self.assertEqual(row['off_diagonal_counts_per_seed'],
                         {'P0_to_P1': 1., 'P0_to_P2': 1., 'P1_to_P0': 1.})

    def test_synthetic_metrics_zero_predictions_and_absent_class_guard(self):
        cm = [[int(i==j)*2 for j in range(6)] for i in range(6)]
        cm[0][0] = 0; cm[0][1] = 2
        m = v.metrics(cm)
        self.assertEqual(m['per_class'][0]['precision'], 0.)
        self.assertEqual(m['per_class'][0]['recall'], 0.)
        self.assertAlmostEqual(m['accuracy'], 10/12)
        cm[0] = [0]*6
        with self.assertRaisesRegex(ValueError, 'actual classes'):
            v.metrics(cm)

    def test_archived_code_bytes_match_successful_evaluation_identity(self):
        for filename,key in [('compare.py','original_evaluator_sha256'),
                             ('compare_fixed.py','successful_evaluator_sha256')]:
            content = (ROOT/'experiment'/filename).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), self.saved['provenance'][key])
            ast.parse(content)

    def test_historical_fix_did_not_change_model_or_evaluation_math(self):
        functions = []
        for filename in ('compare.py','compare_fixed.py'):
            tree = ast.parse((ROOT/'experiment'/filename).read_text(encoding='utf-8'))
            functions.append({n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)})
        for name in ('make_model','model_parameters','load_samples','fold_plans','metrics','summary','benchmark'):
            self.assertEqual(functions[0][name],functions[1][name],name)

    def test_public_aggregate_excludes_private_fields(self):
        banned = {'matrix','feature_matrix','sample_keys','samples','input_frame_indices',
                  'common_valid_frame_indices','scaler','folds','predictions','predictions_by_seed',
                  'executable','filepath','original_root','benchmark_raw','p1_sample_predictions'}
        def walk(value):
            if isinstance(value,dict):
                self.assertFalse(set(value)&banned)
                for x in value.values():walk(x)
            elif isinstance(value,list):
                for x in value:walk(x)
        walk(self.saved)
        encoded=json.dumps(self.saved)
        self.assertNotIn('C:\\Users',encoded)
        self.assertNotIn('captures/',encoded)

    def test_csv_metrics_match_published_aggregate(self):
        with (ROOT/'class_metrics.csv').open(encoding='utf-8-sig',newline='') as f:
            classes=list(csv.DictReader(f))
        self.assertEqual(len(classes),90)
        for row in classes:
            expected=self.saved['results'][row['model']]['scopes'][row['scope']]['mean_per_class'][int(row['posture'][1:])]
            for field in ('support','precision','recall','f1'):
                self.assertAlmostEqual(float(row[field]),expected[field],places=12)
        with (ROOT/'performance.csv').open(encoding='utf-8-sig',newline='') as f:
            performance=list(csv.DictReader(f))
        self.assertEqual(len(performance),15)
        for row in performance:
            scope=self.saved['results'][row['model']]['scopes'][row['scope']]
            self.assertAlmostEqual(float(row['accuracy_percent']),100*scope['mean']['accuracy'],places=12)
            self.assertAlmostEqual(float(row['macro_f1_percent']),100*scope['mean']['macro_f1'],places=12)

    def test_all_15_report_matrices_match_aggregate(self):
        text=(ROOT/'README.md').read_text(encoding='utf-8')
        for name in v.MODELS:
            for scope in v.SCOPES:
                block=re.search(r'### '+re.escape(scope+' / '+name)+r'\s+```text\n(.*?)```',text,re.S)
                self.assertIsNotNone(block)
                rows=[[float(x) for x in line.split()[1:]] for line in block.group(1).splitlines()[1:]]
                self.assertEqual(rows,self.saved['results'][name]['scopes'][scope]['mean_confusion_matrix'])


if __name__ == '__main__':
    unittest.main()
