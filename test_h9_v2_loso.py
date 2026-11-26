"""Synthetic-only integration checks; no repository participant CSV is opened.

All CSVs are made in TemporaryDirectory. TREE_COUNT=2 is a test-only reduction;
the evaluator's public/default contract remains 500 trees and seeds 0..4.
"""

import csv
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import numpy as np

import h6_offline as h6
import h9_v2 as v2
import h9_v2_loso as evaluation
import m3_g as m3
import rf_experiment as rf


class IntegratedLOSOTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def csv(self, subject, *, name=None, labels=range(6), offset=0, extra_short=False):
        recording = subject + ("-" + name if name else "-recording")
        path = self.root / (recording + ".csv")
        # Reverse the physical feature header: matrix order must follow named fields.
        fields = ("artifact_kind", *h6.PROBE_IDENTITY_FIELDS, *reversed(v2.H9_V2_FEATURE_NAMES))
        with path.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            def write_segment(step, label, count):
                for _ in range(count):
                    features = {feature: offset + label * 10 + j * 0.01
                                for j, feature in enumerate(v2.H9_V2_FEATURE_NAMES)}
                    writer.writerow(dict(features, artifact_kind=h6.EXPLORATORY_ARTIFACT_KIND,
                                         subject=subject, recording_id=recording, segment_id=str(step),
                                         label=h6.LAB6[label]))
            for label in labels:
                write_segment(label, label, 30)
            if extra_short:
                write_segment("short", 0, 29)
        return path

    def pair(self):
        return [self.csv("synthetic-A"), self.csv("synthetic-B", offset=0.1)]

    def evaluate(self, paths, **kwargs):
        with patch.object(evaluation, "TREE_COUNT", 2):
            return evaluation.evaluate_probe_csvs(paths, **kwargs)

    def no_fit(self):
        return patch.object(rf, "fit_models", side_effect=AssertionError("fit before validation"))

    def test_primary_shared_matrix_folds_models_and_fixed_contract(self):
        self.assertEqual((evaluation.TREE_COUNT, evaluation.MAX_FEATURES, evaluation.M2_LAMBDA),
                         (500, 2, 0.5))
        self.assertEqual(evaluation.SEEDS, (0, 1, 2, 3, 4))
        paths = self.pair()
        originals = [path.read_bytes() for path in paths]
        m3_inputs = []
        original_class = m3.M3GForest
        class RecordedM3(original_class):
            def fit(self, X, y):
                m3_inputs.append((X.copy(), y.copy(), self.T, self.mf, self.seed))
                return super().fit(X, y)
        with patch.object(rf, "fit_models", wraps=rf.fit_models) as fit:
            with patch.object(m3, "M3GForest", RecordedM3):
                result = self.evaluate(paths)
        self.assertEqual(result["scope"], "primary5")
        self.assertEqual(result["class_order"], tuple(rf.LAB5))
        self.assertEqual(result["sample_count"], 10)
        self.assertEqual(len(result["folds"]), 10)
        self.assertEqual(set(result["metrics"]), set(evaluation.MODEL_NAMES))
        self.assertEqual(result["feature_order"], v2.H9_V2_FEATURE_NAMES)
        matrix, y = np.array(result["feature_matrix"]), np.array(result["true_labels"])
        participants = np.array(result["participants"])
        for fold, call, candidate in zip(result["folds"], fit.call_args_list, m3_inputs):
            train, test = fold["train_indices"], fold["test_indices"]
            self.assertFalse(set(fold["train_participants"]) & set(fold["test_participants"]))
            self.assertEqual(set(participants[test]), {fold["held_out_participant"]})
            self.assertTrue(all(value != fold["held_out_participant"] for value in participants[train]))
            self.assertEqual(fold["feature_order"], result["feature_order"])
            self.assertTrue(fold["provenance_checked"])
            np.testing.assert_array_equal(call.args[0], matrix[train])
            np.testing.assert_array_equal(call.args[1], y[train])
            self.assertEqual(call.args[2:], (5, 2, fold["seed"], [0.5]))
            np.testing.assert_array_equal(candidate[0], matrix[train])
            np.testing.assert_array_equal(candidate[1], y[train])
            self.assertEqual(candidate[2:], (2, 2, fold["seed"]))
            self.assertTrue(fold["m0_m1_predictions_equal"])
        for sample, row in zip([s for s in result["samples"] if s["status"] == "evaluated"], matrix):
            offset = 0.1 if sample["subject"] == "synthetic-B" else 0
            expected = int(sample["sample_key"][2]) * 10 + offset + np.arange(9) * 0.01
            np.testing.assert_allclose(row, expected, rtol=0, atol=1e-12)
        for name in evaluation.MODEL_NAMES:
            self.assertEqual(len(result["predictions"][name]), 5)
            for row in result["metrics"][name]["per_seed"]:
                self.assertEqual(np.asarray(row["confusion_matrix"]).shape, (5, 5))
                self.assertEqual(np.sum(row["confusion_matrix"]), 10)
                self.assertEqual(set(row["errors"]), {"P1_to_P0"})
            for participant in result["metrics"][name]["participants"].values():
                self.assertIn("accuracy_mean", participant)
                self.assertIn("macro_f1_seed_sd", participant)
                self.assertEqual(len(participant["per_seed"][0]["classes"]), 5)
        self.assertEqual([p.read_bytes() for p in paths], originals)

    def test_auxiliary_requires_approval_and_trains_separate_six_class_models(self):
        with self.no_fit():
            for approval in (None, "", "   ", True):
                with self.assertRaisesRegex(ValueError, "approval"):
                    evaluation.evaluate_probe_csvs([], scope="auxiliary6", six_class_approval=approval)
            with self.assertRaises(ValueError):
                evaluation.evaluate_probe_csvs([], six_class_approval="synthetic-approval")
            with self.assertRaises(ValueError):
                evaluation.evaluate_probe_csvs([], scope="unknown")
        with patch.object(rf, "fit_models", wraps=rf.fit_models) as fit:
            result = self.evaluate(self.pair(), scope="auxiliary6",
                                   six_class_approval="synthetic-approval-reference")
        self.assertTrue(all(call.args[2] == 6 for call in fit.call_args_list))
        self.assertEqual(result["sample_count"], 12)
        self.assertEqual(result["class_order"], h6.LAB6)
        self.assertFalse(result["approval_reference_authenticated"])
        self.assertEqual(result["six_class_approval_reference"], "synthetic-approval-reference")
        for row in result["metrics"]["M3-G"]["per_seed"]:
            self.assertEqual(np.asarray(row["confusion_matrix"]).shape, (6, 6))
            self.assertEqual(set(row["errors"]), {"P1_to_P0", "P1_to_P5"})

    def test_metrics_counts_rates_precision_recall_and_undefined_support(self):
        y = np.array([1, 1, 1, 0, 2, 3, 4, 5])
        p = np.array([0, 1, 5, 0, 1, 3, 4, 5])
        row = evaluation._metrics(y, p, h6.LAB6)
        self.assertEqual(row["accuracy"], 5 / 8)
        self.assertEqual(row["macro_f1"], rf.macro_f1(y, p, 6))
        self.assertEqual(row["classes"][1]["precision"], 0.5)
        self.assertEqual(row["classes"][1]["recall"], 1 / 3)
        for name in ("P1_to_P0", "P1_to_P5"):
            self.assertEqual(row["errors"][name], dict(count=1, support=3, rate=1 / 3))
        empty_support = evaluation._metrics(np.array([0]), np.array([0]), tuple(rf.LAB5))
        self.assertIsNone(empty_support["classes"][1]["recall"])
        self.assertEqual(empty_support["classes"][1]["precision"], 0.0)
        self.assertIsNone(empty_support["errors"]["P1_to_P0"]["rate"])
        self.assertFalse(empty_support["complete_class_support"])

    def test_input_hashes_row_bindings_exclusions_and_json_serialization(self):
        paths = [self.csv("synthetic-A", extra_short=True), self.csv("synthetic-B")]
        result = self.evaluate(paths)
        self.assertEqual(result["formal_schema_status"], "UNRESOLVED")
        self.assertTrue(result["unresolved_formal_connections"])
        self.assertEqual(sum(s["status"] == "ineligible" for s in result["samples"]), 1)
        self.assertEqual(sum(s["status"] == "outside_primary_class_set" for s in result["samples"]), 2)
        for source, path in zip(result["inputs"], paths):
            self.assertEqual(source["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        for sample in result["samples"]:
            source = result["inputs"][sample["source_index"]]
            self.assertEqual(sample["subject"], source["subject"])
            self.assertEqual(sample["sample_key"][1], source["recording_id"])
            self.assertEqual(len(sample["input_frame_indices"]), sample["frame_count"])
            self.assertEqual(len(sample["common_valid_frame_indices"]), sample["common_valid_count"])
        json.dumps(result, allow_nan=False)

    def test_multiple_recordings_of_one_participant_stay_in_one_fold(self):
        paths = [self.csv(subject, name=name, labels=labels)
                 for subject in ("synthetic-A", "synthetic-B")
                 for name, labels in (("first", range(3)), ("second", range(3, 6)))]
        result = self.evaluate(paths)
        self.assertEqual(len(result["folds"]), 10)
        for fold in result["folds"]:
            self.assertEqual(len(fold["test_source_indices"]), 2)
            self.assertEqual(len(fold["train_source_indices"]), 2)
            self.assertFalse(set(fold["train_source_indices"]) & set(fold["test_source_indices"]))

    def test_validation_rejects_duplicate_input_order_drift_and_missing_training_class(self):
        paths = self.pair()
        incomplete = self.csv("synthetic-C", labels=range(4))
        with self.no_fit():
            for inputs, message in (([paths[0], paths[0], paths[1]], "duplicate"),
                                    ([paths[0]], "two eligible"),
                                    ([paths[0], incomplete], "training fold")):
                with self.assertRaisesRegex(ValueError, message):
                    self.evaluate(inputs)
            with patch.object(m3, "FEATURE_NAMES", tuple(reversed(m3.FEATURE_NAMES))):
                with self.assertRaisesRegex(ValueError, "feature order"):
                    self.evaluate(paths)

    def test_loader_provenance_corruption_fails_before_fitting(self):
        paths = self.pair()
        samples = h6.load_labeled_probe_h9_v2_samples(paths)
        first = samples[0]
        corrupted = [
            replace(first, sample_key=("unbound-run", *first.sample_key[1:])),
            replace(first, subject="different-participant"),
            replace(first, input_frame_indices=(999,) + first.input_frame_indices[1:]),
            replace(first, common_valid_frame_indices=(999,) + first.common_valid_frame_indices[1:]),
            replace(first, aggregation_spec="legacy-H9"),
        ]
        with self.no_fit():
            for sample in corrupted:
                with patch.object(h6, "load_labeled_probe_h9_v2_samples", return_value=(sample, *samples[1:])):
                    with self.assertRaises(ValueError):
                        self.evaluate(paths)
            for output in ((*samples, samples[0]), samples[1:]):
                with patch.object(h6, "load_labeled_probe_h9_v2_samples", return_value=output):
                    with self.assertRaises(ValueError):
                        self.evaluate(paths)

    def test_input_mutation_after_loading_fails_before_fitting(self):
        paths = self.pair()
        loader = h6.load_labeled_probe_h9_v2_samples
        def changed(inputs):
            samples = loader(inputs)
            # Deliberate corruption of a temporary synthetic file only.
            with paths[0].open("a", encoding="utf-8") as stream:
                stream.write("\n")
            return samples
        with self.no_fit(), patch.object(h6, "load_labeled_probe_h9_v2_samples", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.evaluate(paths)

    def test_held_out_feature_change_cannot_change_that_folds_training_weights(self):
        paths = self.pair()
        baseline = self.evaluate(paths)
        changed_path = self.csv("synthetic-A", name="shifted", offset=100)
        # Its sample keys differ, but the participant and unchanged training B remain fixed.
        changed = self.evaluate([changed_path, paths[1]])
        for result in (baseline, changed):
            self.assertEqual(len(result["folds"]), 10)
        before = [f for f in baseline["folds"] if f["held_out_participant"] == "synthetic-A"]
        after = [f for f in changed["folds"] if f["held_out_participant"] == "synthetic-A"]
        self.assertEqual([f["rank_weights"] for f in before], [f["rank_weights"] for f in after])
        self.assertEqual([f["training_m0_mdi"] for f in before], [f["training_m0_mdi"] for f in after])

    def test_repeatability_and_complete_class_support_reporting(self):
        paths = self.pair()
        left, right = self.evaluate(paths), self.evaluate(paths)
        self.assertEqual(left["predictions"], right["predictions"])
        self.assertEqual(left["metrics"], right["metrics"])
        self.assertEqual(left["folds"], right["folds"])
        partial = self.csv("synthetic-C", labels=range(4))
        result = self.evaluate([*paths, partial])
        self.assertEqual(len(result["folds"]), 15)
        for model in result["metrics"].values():
            self.assertFalse(model["complete_participant_class_support"])
            self.assertIsNone(model["complete_class_participant_macro_f1"])
            self.assertIsNone(model["participants"]["synthetic-C"]["per_seed"][0]["classes"][4]["recall"])

    def test_cli_never_overwrites_existing_output_and_defaults_to_primary(self):
        output = self.root / "synthetic-result.json"
        with patch.object(evaluation, "evaluate_probe_csvs", return_value={"synthetic": True}) as run:
            evaluation.main(["--probe-csv", "synthetic.csv", "--output", str(output)])
            self.assertEqual(json.loads(output.read_text()), {"synthetic": True})
            self.assertEqual(run.call_args.kwargs, dict(scope="primary5", six_class_approval=None))
            with self.assertRaises(FileExistsError):
                evaluation.main(["--probe-csv", "synthetic.csv", "--output", str(output)])
            self.assertEqual(run.call_count, 1)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                evaluation.main(["--probe-csv", "synthetic.csv"])
            self.assertEqual(json.loads(buffer.getvalue()), {"synthetic": True})


if __name__ == "__main__":
    unittest.main()
