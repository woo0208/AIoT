"""Small synthetic structural checks only; scores are not research results."""

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

import h6_offline as h6
import posture_geometry_probe as probe
import rf_experiment as rf
from f1_sample_aggregator import H9_FEATURE_NAMES, aggregate_h5_h9_sample
from test_h5_h9_evaluation import h_record, h_features


def synthetic_samples():
    samples = []
    for subject in ("S1", "S2", "S3"):
        for k, label in enumerate((*rf.LAB5, "body_forward")):
            samples.append(aggregate_h5_h9_sample([
                h_record(k * 30 + i, subject=subject, step=str(k), label=label,
                         features=h_features(k * 10 + i))
                for i in range(1, 31)
            ]))
    return samples


class SixPostureTests(unittest.TestCase):
    def evaluate(self, samples):
        with patch.object(rf, "H_EVAL_TREES", 2):
            return h6.evaluate_samples(samples)

    def test_six_models_metrics_joint_eligibility_and_original_labels(self):
        samples = synthetic_samples()
        excluded = replace(samples[0], sample_key=("other", "other", "0"),
                           eligible=False, eligibility_reasons=("common_valid_frames<30",))
        result = self.evaluate([*samples, excluded])
        self.assertEqual(result["sample_count"], 18)
        self.assertEqual(result["eligible_class_counts"], dict.fromkeys(h6.LAB6, 3))
        self.assertEqual(len(result["metrics"]), 6)
        self.assertEqual(result["seeds"], (0, 1, 2, 3, 4))
        self.assertEqual(result["tree_count"], 2)
        self.assertEqual(len(result["folds"]), 15)
        for row in result["metrics"]:
            self.assertTrue(0 <= row["accuracy"] <= 1)
            self.assertTrue(0 <= row["macro_f1"] <= 1)
            self.assertEqual(len(row["confusion_matrices"]), 5)
            for cm in row["confusion_matrices"]:
                self.assertEqual(np.asarray(cm).shape, (6, 6))
                np.testing.assert_array_equal(np.sum(cm, axis=1), [3] * 6)
        p5 = [s for s in result["samples"] if s["posture_id"] == "P5"]
        self.assertEqual(len(p5), 3)
        self.assertTrue(all(s["original_label"] == "body_forward" and
                            s["analysis_label"] == "lean_forward" for s in p5))
        self.assertEqual(samples[-1].label, "body_forward")
        json.dumps(result, allow_nan=False)

    def test_training_only_weights_and_shared_participant_folds(self):
        samples = synthetic_samples()
        original_fit = rf.fit_models
        with patch.object(rf, "fit_models", wraps=original_fit) as fit:
            result = self.evaluate(samples)
        self.assertEqual(len(fit.call_args_list), 30)
        for fold, calls in zip(result["folds"], zip(fit.call_args_list[::2], fit.call_args_list[1::2])):
            train, test = fold["train_indices"], fold["test_indices"]
            self.assertFalse(set(train) & set(test))
            self.assertTrue(all(samples[i].subject == fold["held_out_participant"] for i in test))
            self.assertTrue(all(samples[i].subject != fold["held_out_participant"] for i in train))
            for call, fs in zip(calls, ("H5", "H9")):
                expected = [samples[i].ordered_values(fs) for i in train]
                np.testing.assert_array_equal(call.args[0], expected)
                self.assertEqual(call.args[2], 6)
                self.assertEqual(call.args[5], [0.5])
        changed = [replace(s, features={k: v + 10000 for k, v in s.features.items()})
                   if s.subject == "S1" else s for s in samples]
        changed_result = self.evaluate(changed)
        weights = lambda r: [f["weights"] for f in r["folds"] if f["held_out_participant"] == "S1"]
        self.assertEqual(weights(result), weights(changed_result))

    def test_fail_closed_labels_duplicates_and_missing_training_class(self):
        samples = synthetic_samples()
        for invalid, message in (
            ([*samples, samples[0]], "duplicate"),
            ([replace(samples[0], label="unknown"), *samples[1:]], "six-posture label"),
            ([s for s in samples if s.label != "body_forward"], "all six postures"),
            ([s for s in samples if s.label != "body_forward" or s.subject == "S1"], "training fold"),
            (samples[:6], "two participants"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.evaluate(invalid)
        self.assertEqual(h6.analysis_label("lean_forward"), "lean_forward")
        self.assertEqual(rf.LAB5, list(h6.LAB6[:5]))

    def test_probe_csv_metadata_adapter_aggregation_and_cli_json(self):
        metadata_fields = list(h6.PROBE_METADATA_FIELDS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_path = root / "captures.csv"
            metadata_rows = []
            for subject in ("S1", "S2"):
                for k, label in enumerate((*rf.LAB5, "body_forward")):
                    path = root / f"{subject}-{k}.csv"
                    metadata_rows.append(dict(
                        csv_path=path.name, subject=subject,
                        recording_id=f"rec-{subject}-{k}", round="1",
                        step=str(k), label=label,
                    ))
                    with path.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(
                            stream,
                            fieldnames=["artifact_kind", *H9_FEATURE_NAMES],
                        )
                        writer.writeheader()
                        for i in range(1, 32):
                            features = h_features(
                                i, missing=H9_FEATURE_NAMES[-1:] if i == 31 else ()
                            )
                            writer.writerow(dict(
                                artifact_kind=h6.EXPLORATORY_ARTIFACT_KIND,
                                **features,
                            ))

            excluded_path = root / "excluded.csv"
            metadata_rows.append(dict(
                csv_path=excluded_path.name, subject="S1",
                recording_id="rec-excluded", round="1", step="extra",
                label="upright",
            ))
            with excluded_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=["artifact_kind", *H9_FEATURE_NAMES]
                )
                writer.writeheader()
                for i in range(1, 32):
                    features = h_features(
                        i, missing=H9_FEATURE_NAMES[-1:] if i >= 30 else ()
                    )
                    writer.writerow(dict(
                        artifact_kind=h6.EXPLORATORY_ARTIFACT_KIND, **features
                    ))

            with metadata_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=metadata_fields)
                writer.writeheader()
                writer.writerows(metadata_rows)

            before = {path: path.read_bytes() for path in root.iterdir()}
            samples = h6.load_probe_h_samples([metadata_path])
            self.assertEqual(len(samples), 13)
            self.assertEqual(sum(sample.eligible for sample in samples), 12)
            self.assertTrue(all(sample.common_valid_count == 30
                                for sample in samples[:-1]))
            output = io.StringIO()
            with patch("sys.argv", ["h6_offline.py", "--probe-metadata",
                                    str(metadata_path)]), \
                    patch.object(rf, "H_EVAL_TREES", 2), redirect_stdout(output):
                h6.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["sample_count"], 12)
            self.assertEqual(result["aggregation_audit"]["input_sample_count"], 13)
            self.assertEqual(result["aggregation_audit"]["excluded_sample_count"], 1)
            self.assertEqual(result["aggregation_audit"]["excluded_frame_count"], 14)
            self.assertEqual(
                result["aggregation_audit"]["feature_missing_cell_counts"]
                      [H9_FEATURE_NAMES[-1]],
                14,
            )
            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, before)
            with self.assertRaisesRegex(ValueError, "duplicate probe recording_id"):
                h6.load_probe_h_samples([metadata_path, metadata_path])

    def test_continuous_probe_segments_exclude_prep_and_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for subject in ("S1", "S2"):
                path = root / f"{subject}.csv"
                paths.append(path)
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(
                        stream,
                        fieldnames=["artifact_kind", *h6.PROBE_IDENTITY_FIELDS,
                                    *H9_FEATURE_NAMES],
                    )
                    writer.writeheader()
                    for label, segment_id, count in (("PREP", "0", 2),
                                                     ("TRANSITION", "1", 2)):
                        for i in range(count):
                            writer.writerow(dict(
                                artifact_kind=h6.EXPLORATORY_ARTIFACT_KIND,
                                subject=subject, recording_id=f"rec-{subject}",
                                segment_id=segment_id, label=label,
                                **h_features(i),
                            ))
                    for k, label in enumerate(h6.LAB6, 2):
                        for i in range(30):
                            writer.writerow(dict(
                                artifact_kind=h6.EXPLORATORY_ARTIFACT_KIND,
                                subject=subject, recording_id=f"rec-{subject}",
                                segment_id=str(k), label=label,
                                **h_features(k * 100 + i),
                            ))

            samples = h6.load_labeled_probe_h_samples(paths)
            self.assertEqual(len(samples), 12)
            self.assertTrue(all(sample.n_frames == 30 for sample in samples))
            self.assertEqual({sample.label for sample in samples}, set(h6.LAB6))
            result = self.evaluate(samples)
            self.assertEqual(result["sample_count"], 12)
            self.assertEqual(result["eligible_class_counts"], dict.fromkeys(h6.LAB6, 2))
            output = io.StringIO()
            with patch("sys.argv", ["h6_offline.py", "--probe-csv",
                                    *(str(path) for path in paths)]), \
                    patch.object(rf, "H_EVAL_TREES", 2), redirect_stdout(output):
                h6.main()
            self.assertEqual(json.loads(output.getvalue())["sample_count"], 12)

    def test_capture_label_keys_start_prep_and_increment_on_changes(self):
        segment = probe.CaptureSegment()
        self.assertEqual((segment.label, segment.segment_id), ("PREP", 0))
        for key, label in ((ord("t"), "TRANSITION"), (ord("1"), "upright"),
                           (ord("6"), "lean_forward")):
            segment = probe.handle_capture_label_key(key, segment)
            self.assertEqual(segment.label, label)
        self.assertEqual(segment.segment_id, 3)
        self.assertIs(probe.handle_capture_label_key(ord("6"), segment), segment)
        self.assertIs(probe.handle_capture_label_key(ord("q"), segment), segment)

    def test_evaluator_ignores_prep_and_transition_samples(self):
        samples = synthetic_samples()
        auxiliary = [
            replace(samples[0], sample_key=("aux", "prep", "0"), label="PREP"),
            replace(samples[0], sample_key=("aux", "transition", "1"),
                    label="TRANSITION"),
        ]
        result = self.evaluate([*samples, *auxiliary])
        self.assertEqual(result["sample_count"], len(samples))
        self.assertEqual(result["aggregation_audit"]["input_sample_count"], len(samples))


if __name__ == "__main__":
    unittest.main()
