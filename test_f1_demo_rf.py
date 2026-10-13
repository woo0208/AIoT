"""Synthetic structural tests for the F1-5 engineering-demo classifier.

These fixtures verify software behavior only.  They are not real posture data
and provide no evidence of classification accuracy or generalization.
"""

import csv
import json
import os
from pathlib import Path
import tempfile
import unittest

import analyze_d455
import f1_demo_rf as demo
import f1_features
import posture_prediction
import rf_experiment
from test_f1_csv_adapter import canonical_row
import train_f1_demo_rf as trainer


def synthetic_rows(include_body_forward=True):
    rows = []
    index = 1
    definitions = [
        ("1", "upright", {}),
        ("2", "forward_head", {"face_x": "840.0", "face_y": "400.0"}),
    ]
    if include_body_forward:
        definitions.append(("3", "body_forward", {
            "left_hip_x_px": "910.0", "right_hip_x_px": "770.0",
            "left_hip_y_px": "500.0", "right_hip_y_px": "500.0",
        }))
    for step, label, geometry in definitions:
        for _ in range(12):
            rows.append(canonical_row(index, step=step, label=label, **geometry))
            index += 1
    return rows


def write_canonical_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=analyze_d455.FRAME_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def feature_values(row):
    typed = dict(row)
    for name in analyze_d455.FRAME_BOOL_FIELDS:
        typed[name] = {"true": True, "false": False, "": None}[typed[name]]
    for name in set(analyze_d455.FRAME_FIELDS) - analyze_d455.FRAME_TEXT_FIELDS - analyze_d455.FRAME_BOOL_FIELDS:
        value = typed[name]
        if value == "":
            typed[name] = None
        elif name in {"frame_index", "color_frame_number", "depth_frame_number", "mediapipe_ts_ms"}:
            typed[name] = int(value)
        else:
            typed[name] = float(value)
    return f1_features.compute_f1_5_frame(typed)


class DemoRFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.csv_path = cls.root / "synthetic_frames.csv"
        cls.model_path = cls.root / "synthetic_model.json"
        cls.rows = synthetic_rows()
        write_canonical_csv(cls.csv_path, cls.rows)
        cls.document = trainer.train_f1_demo_rf(
            [cls.csv_path], cls.model_path,
            n_estimators=31, max_features=5, random_seed=7,
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_correct_three_class_labels(self):
        self.assertEqual(demo.CLASS_LABELS, ("upright", "forward_head", "body_forward"))
        self.assertEqual(
            tuple(self.document["payload"]["metadata"]["class_labels"]),
            demo.CLASS_LABELS,
        )

    def test_correct_f1_feature_order(self):
        self.assertEqual(demo.FEATURE_NAMES, ("fs_x", "fs_y", "sh_x", "sh_y", "so_beta"))
        self.assertEqual(demo.FEATURE_NAMES, f1_features.F1_5_FEATURE_NAMES)
        self.assertEqual(demo.FEATURE_UNITS, ("dimensionless",) * 4 + ("rad",))

    def test_successful_training_on_synthetic_fixtures(self):
        metadata = self.document["payload"]["metadata"]
        self.assertTrue(self.model_path.is_file())
        self.assertEqual(metadata["training"]["label_counts"], {
            "upright": 12, "forward_head": 12, "body_forward": 12,
        })
        self.assertEqual(metadata["training"]["valid_frame_count"], 36)
        self.assertEqual(metadata["training"]["rejected_frame_count"], 0)
        source = metadata["training"]["input_csvs"][0]
        self.assertEqual(source["recording_id"], "SYN_r1_synthetic_recording")
        self.assertEqual(source["analysis_run_id"], "ar_synthetic_run")
        self.assertEqual(len(source["sha256"]), 64)
        self.assertIsNone(metadata["training"]["validation"])

    def test_successful_inference_using_test_trained_model(self):
        representatives = (self.rows[0], self.rows[12], self.rows[24])
        for expected, row in zip(demo.CLASS_LABELS, representatives):
            with self.subTest(expected=expected):
                result = demo.predict_f1_demo(self.model_path, feature_values(row))
                self.assertEqual(result.status, demo.PREDICTION_AVAILABLE)
                self.assertEqual(result.label, expected)

    def test_missing_feature_is_unavailable(self):
        row = canonical_row(
            100, face_detected="false", face_x="", face_y="",
        )
        result = demo.predict_f1_demo(self.model_path, feature_values(row))
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIsNone(result.label)
        self.assertIn("fs_x", result.reason)
        self.assertIn("face_detected:false", result.reason)

    def test_missing_model_is_unavailable(self):
        result = demo.predict_f1_demo(self.root / "absent.json", (0, -1, 0, -1.5, 0))
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIn("not found", result.reason)

    def test_feature_contract_mismatch_is_unavailable(self):
        vector = demo.F1DemoFeatureVector(
            values=(0, -1, 0, -1.5, 0),
            feature_names=("fs_y", "fs_x", "sh_x", "sh_y", "so_beta"),
        )
        result = demo.predict_f1_demo(self.model_path, vector)
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIn("feature contract mismatch", result.reason)

        changed = json.loads(json.dumps(self.document))
        changed["payload"]["metadata"]["feature_names"][0:2] = ["fs_y", "fs_x"]
        signed = {"artifact_format": changed["artifact_format"], "payload": changed["payload"]}
        changed["integrity"]["sha256"] = demo.artifact_integrity_sha256(signed)
        path = self.root / "wrong_contract.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        result = demo.predict_f1_demo(path, (0, -1, 0, -1.5, 0))
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIn("feature_names", result.reason)

    def test_no_baseline_calibration_or_prior_frame_state(self):
        metadata_text = json.dumps(self.document["payload"]["metadata"]).lower()
        self.assertNotIn("calibration", metadata_text)
        self.assertNotIn("baseline", metadata_text)
        model = demo.load_f1_demo_model(self.model_path)
        target = demo.F1DemoFeatureVector((0, -1, 0, -1.5, 0))
        first = model.predict(target)
        model.predict((1, 0, 0, -1.5, 0))
        self.assertEqual(model.predict(target), first)

    def test_model_save_load_round_trip(self):
        loaded = demo.load_f1_demo_model(self.model_path)
        self.assertEqual(loaded.metadata, self.document["payload"]["metadata"])
        expected = demo.predict_f1_demo(self.model_path, (0, -1, 0, -1.5, 0))
        self.assertEqual(loaded.predict((0, -1, 0, -1.5, 0)), expected)

    def test_corrupted_model_or_metadata_rejected(self):
        corrupt = self.root / "corrupt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        result = demo.predict_f1_demo(corrupt, (0, -1, 0, -1.5, 0))
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIn("rejected", result.reason)

        invalid_tree = json.loads(json.dumps(self.document))
        invalid_tree["payload"]["model"]["trees"][0]["feature"][0] = 99
        signed = {
            "artifact_format": invalid_tree["artifact_format"],
            "payload": invalid_tree["payload"],
        }
        invalid_tree["integrity"]["sha256"] = demo.artifact_integrity_sha256(signed)
        invalid_tree_path = self.root / "invalid_tree.json"
        invalid_tree_path.write_text(json.dumps(invalid_tree), encoding="utf-8")
        result = demo.predict_f1_demo(invalid_tree_path, (0, -1, 0, -1.5, 0))
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIn("invalid split", result.reason)

        changed = json.loads(json.dumps(self.document))
        changed["payload"]["metadata"]["class_labels"][0] = "other"
        tampered = self.root / "tampered.json"
        tampered.write_text(json.dumps(changed), encoding="utf-8")
        result = demo.predict_f1_demo(tampered, (0, -1, 0, -1.5, 0))
        self.assertEqual(result.status, demo.PREDICTION_UNAVAILABLE)
        self.assertIn("integrity", result.reason)

    def test_missing_class_in_training_data_rejected(self):
        path = self.root / "two_class.csv"
        write_canonical_csv(path, synthetic_rows(include_body_forward=False))
        with self.assertRaisesRegex(ValueError, "body_forward"):
            trainer.train_f1_demo_rf(
                [path], self.root / "must_not_exist.json",
                n_estimators=3, max_features=5,
            )
        self.assertFalse((self.root / "must_not_exist.json").exists())

    def test_invalid_label_and_overwrite_are_rejected(self):
        path = self.root / "invalid_label.csv"
        rows = synthetic_rows()
        rows[-1]["label"] = "lean_left"
        rows[-1]["step"] = "4"
        write_canonical_csv(path, rows)
        with self.assertRaisesRegex(ValueError, "invalid training label"):
            trainer.train_f1_demo_rf([path], self.root / "invalid.json", n_estimators=3)
        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
            trainer.train_f1_demo_rf([self.csv_path], self.model_path, n_estimators=3)

    def test_existing_research_code_remains_unaffected(self):
        self.assertEqual(posture_prediction.LAB5_LABELS, (
            "upright", "forward_head", "lean_back", "lean_left", "lean_right",
        ))
        self.assertEqual(rf_experiment.LAB5, [
            "upright", "forward_head", "lean_back", "lean_left", "lean_right",
        ])
        executor = posture_prediction.build_prediction_executor()
        self.assertEqual(
            executor.predict(None).prediction,
            posture_prediction.PredictionClass.UNAVAILABLE,
        )


if __name__ == "__main__":
    unittest.main()
