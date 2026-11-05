"""Synthetic EXISTING-result fixtures only. No fit/evaluation runner is invoked."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engineering_exports as out
import evaluation_csv_adapter as adapter
import formal6_evaluation as ev
import performance_output as perf
from test_formal6_evaluation import fixture as families_fixture, SUBJECTS, REFS
from test_model_benchmark import identity


def jsonable(value):
    if hasattr(value, 'tolist'):
        return value.tolist()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    return value


def fixture(*, incomplete=False):
    families = families_fixture()
    if incomplete:
        families = {name: tuple(r for r in rows if r.label != 'lean_forward') for name, rows in families.items()}
    aligned = ev.align_development(families, SUBJECTS, REFS, feature_sets=tuple(ev.FEATURES))
    y = aligned['y']
    # Deliberate P1->P0 error: test scores differ from a perfect fixture.
    prediction = y.copy()
    prediction[prediction == 1] = 0
    folds = []
    for model in ('RF', 'LR_B0', *(b[0] for b in ev.BASELINES)):
        for seed in ((0,) if model == 'LR_B0' else ev.SEEDS):
            for heldout in SUBJECTS:
                folds.append(dict(model=model, seed=seed, heldout=heldout,
                    train_participants=[s for s in SUBJECTS if s != heldout],
                    train_keys=[k for k, s in zip(aligned['sample_keys'], aligned['participants']) if s != heldout],
                    test_keys=[k for k, s in zip(aligned['sample_keys'], aligned['participants']) if s == heldout]))
    models = {}
    for name, (feature, model) in adapter.APPROVED.items():
        seeds = (0,) if model == 'LR_B0' else ev.SEEDS
        models[name] = ev._prediction_report(aligned, [prediction]*len(seeds), seeds, feature, model)
    report = jsonable(dict(baseline_comparison=dict(status='COMPARISON_COMPLETE', aligned=aligned, models=models,
        folds=folds, settings=dict(rf_seeds=ev.SEEDS, rf_trees=500, max_features=2, structural_test_settings=False))))
    metadata = dict(identity=dict(identity(), run_status='COMPLETED'), evaluation_rule_id=adapter.RULE_ID,
        evaluation_rule_sha256=perf.sha256(adapter.FREEZE),
        dataset_sha256=adapter.dataset_digest(report['baseline_comparison']['aligned']),
        reference_keys=jsonable(REFS), windows=[dict(sample_key=list(r.sample_key), window=list(r.window))
                                               for r in families['H9']])
    return report, metadata


class EvaluationCSVTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.complete = fixture()
        cls.incomplete = fixture(incomplete=True)

    def test_eight_comparisons_accuracy_recall_macro_and_roles(self):
        report, metadata = copy.deepcopy(self.complete)
        with patch.object(ev, 'evaluate_development', side_effect=AssertionError('no evaluation')):
            result = adapter.project(report, metadata)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(len(result['comparison_rows']), 8)
        for row in result['comparison_rows']:
            self.assertAlmostEqual(row['accuracy'], 5/6)
            self.assertAlmostEqual(row['macro_f1'], (2/3 + 0 + 4)/6)
            self.assertEqual(row['support'], 12)
        rows = [r for r in result['class_rows'] if r['scope'] == 'pooled' and r['posture'] == 'P1']
        self.assertTrue(all(r['recall'] == 0 and r['support'] == 2 for r in rows))
        self.assertEqual(result['combinations']['RF_M0_F0']['role'], 'COMPARISON_BASELINE')
        self.assertIn('COPY', result['combinations']['RF_M0_H9']['role'])
        self.assertEqual(report, self.complete[0])

    def test_na_incomplete_not_measured_are_separate(self):
        result = adapter.project(*copy.deepcopy(self.incomplete))
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertTrue(all(r['macro_f1'] is None and r['measurement_status'] == 'INCOMPLETE'
                            for r in result['comparison_rows']))
        absent = [r for r in result['class_rows'] if r['posture'] == 'P5']
        self.assertTrue(all(r['recall'] is None and r['f1'] is None and r['metric_status'] == 'N/A' for r in absent))
        report, metadata = copy.deepcopy(self.complete)
        report['baseline_comparison']['models'] = {}
        result = adapter.project(report, metadata)
        self.assertTrue(all(r['measurement_status'] == 'NOT_MEASURED' for r in result['comparison_rows']))
        result = adapter.project(dict(status='NOT_PROVIDED'), metadata)
        self.assertEqual(result['status'], 'NOT_MEASURED')

    def test_rules_seeds_common_samples_reference_loso_and_auxiliary_rejected(self):
        edits = [lambda r, m: m.update(evaluation_rule_id='changed'),
            lambda r, m: m.update(dataset_sha256='x'*64),
            lambda r, m: m['windows'][1].update(window=['SYNTHETIC', 0, 9]),
            lambda r, m: r['baseline_comparison']['settings'].update(rf_seeds=[42]),
            lambda r, m: r['baseline_comparison']['folds'].pop(),
            lambda r, m: r['baseline_comparison']['models'].update(AUXILIARY={}),
            lambda r, m: r['baseline_comparison']['models']['RF_M0_H9']['pooled'].update(mean_accuracy=.99),
            lambda r, m: r['baseline_comparison']['models']['RF_M0_H9']['predictions'][0].__setitem__(0, 5)]
        for edit in edits:
            r, m = copy.deepcopy(self.complete)
            edit(r, m)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                adapter.project(r, m)

    def test_reference_inclusion_rejected_even_if_digest_rebound(self):
        report, metadata = copy.deepcopy(self.complete)
        aligned = report['baseline_comparison']['aligned']
        aligned['sample_keys'][0] = list(REFS[SUBJECTS[0]])
        metadata['dataset_sha256'] = adapter.dataset_digest(aligned)
        with self.assertRaisesRegex(ValueError, 'reference P0'):
            adapter.project(report, metadata)
        report, metadata = copy.deepcopy(self.complete)
        a, b = SUBJECTS
        metadata['reference_keys'][a], metadata['reference_keys'][b] = metadata['reference_keys'][b], metadata['reference_keys'][a]
        with self.assertRaisesRegex(ValueError, 'P0 exclusion audit'):
            adapter.project(report, metadata)

    def test_synthetic_scope_cannot_be_relabelled_formal(self):
        for scope in ('FORMAL', 'NON_FORMAL_ENGINEERING'):
            report, metadata = copy.deepcopy(self.complete)
            metadata['identity']['scope'] = scope
            with self.assertRaisesRegex(ValueError, 'scope'):
                adapter.project(report, metadata)

    def test_json_preserved_csv_schema_and_blank_na(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, metadata = copy.deepcopy(self.incomplete)
            source, meta = root / 'synthetic.json', root / 'metadata.json'
            perf._write_json(source, report)
            metadata['result_sha256'] = perf.sha256(source)
            perf._write_json(meta, metadata)
            adapter.export(source, meta, root / 'new')
            self.assertEqual(source.read_bytes(), (root / 'new/evaluation.original.json').read_bytes())
            with (root / 'new/experiment_comparisons.csv').open() as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, list(perf.COMPARISON_FIELDS))
                self.assertTrue(all(r['macro_f1'] == '' for r in reader))
            with (root / 'new/class_metrics.csv').open() as stream:
                self.assertTrue(all(r['recall'] == '' for r in csv.DictReader(stream) if r['metric_status'] == 'N/A'))
            with self.assertRaises(FileExistsError):
                adapter.export(source, meta, root / 'new')
            source.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                adapter.export(source, meta, root / 'tampered')
