"""Synthetic structural tests; no human data, camera, display or model runs."""
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import posture_geometry_probe as probe
from capture_six_pilot import PilotCapture, LABELS, accept_probe_frame, load_p5_supplement_binding
from f1_sample_aggregator import H9_FEATURE_NAMES
from h6_offline import load_labeled_probe_h_samples


def row(stamp):
    value = dict.fromkeys(probe.CSV_FIELDS)
    value.update(artifact_kind=probe.EXPLORATORY_ARTIFACT_KIND,
                 device_timestamp_ms=stamp, timestamp_utc="SYNTHETIC_TEST")
    value.update({name: 1.0 for name in H9_FEATURE_NAMES})
    return value


class PilotCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp) / "new_run"
        self.capture = PilotCapture(self.root, "P01", "SYNTHETIC_CAPTURE", probe.CSV_FIELDS)
        self.addCleanup(self.capture.finish)

    def select(self, label):
        self.capture.choose("upright")
        if label != "upright":
            self.capture.choose(label)
        self.assertTrue(self.capture.start())

    def read_rows(self, path=None):
        with (path or self.root / "features.csv").open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_paused_and_normal_reset_frames_are_never_saved(self):
        self.assertFalse(self.capture.accept(row(0), 1))
        self.assertFalse(self.capture.start())
        self.capture.choose("forward_head")  # wrong order does not choose a label
        self.assertFalse(self.capture.start())
        self.assertEqual(self.read_rows(), [])

    def test_half_open_ten_second_hold_commits_only_at_boundary(self):
        self.select("upright")
        self.assertTrue(self.capture.accept(row(100), 1))
        self.assertTrue(self.capture.accept(row(10099), 2))
        self.assertEqual(self.read_rows(), [])
        self.assertFalse(self.capture.accept(row(10100), 3))
        rows = self.read_rows()
        self.assertEqual([r["device_timestamp_ms"] for r in rows], ["100", "10099"])
        self.assertEqual({r["label"] for r in rows}, {"upright"})
        self.assertEqual(self.capture.expected, "forward_head")
        self.capture.choose("forward_head")
        self.assertFalse(self.capture.start())  # explicit unrecorded normal reset required

    def test_interrupted_attempt_is_preserved_but_not_an_analysis_sample(self):
        self.select("upright")
        self.capture.accept(row(0), 1)
        self.capture.pause()
        self.assertEqual(self.read_rows(), [])
        self.assertEqual(len(self.read_rows(self.root / "attempts/attempt_001.csv")), 1)
        self.assertEqual(json.loads((self.root / "attempts/attempt_001.json").read_text())["status"], "ABORTED")
        self.assertEqual(len(self.capture.completed), 0)
        self.select("upright")
        self.capture.accept(row(10000), 2)
        self.capture.accept(row(20000), 3)
        self.assertEqual(len(self.capture.completed), 1)

    def test_complete_ten_rounds_join_existing_loader_as_sixty_unique_segments(self):
        index = 0
        for step in range(60):
            label = LABELS[step % 6]
            self.select(label)
            for offset in range(0, 10001, 250):
                index += 1
                self.capture.accept(row(step * 20000 + offset), index)
            self.capture.accept(row(step * 20000 + 12000), index + 1)  # paused transition
        self.assertTrue(self.capture.done)
        self.assertFalse(self.capture.start())
        self.capture.finish()
        summary = json.loads((self.root / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "COMPLETED")
        self.assertEqual(set(summary["counts"].values()), {10})
        rows = self.read_rows()
        self.assertEqual(len(rows), 60 * 40)
        self.assertTrue(all(r["label"] in LABELS for r in rows))
        samples = load_labeled_probe_h_samples([self.root / "features.csv"])
        self.assertEqual(len(samples), 60)
        self.assertEqual(len({s.sample_key for s in samples}), 60)
        self.assertTrue(all(s.eligible and s.common_valid_count == 40 for s in samples))

    def test_timestamp_reset_or_duplicate_aborts_without_filling(self):
        self.select("upright")
        self.capture.accept(row(100), 1)
        with self.assertRaisesRegex(ValueError, "Duplicate/reset"):
            self.capture.accept(row(100), 2)
        self.assertEqual(self.read_rows(), [])
        self.assertIsNone(self.capture.active)

    def test_real_callback_flag_is_used_without_inference_and_frame_fields_unchanged(self):
        frame = SimpleNamespace(result=object(), pose_detected=False, device_timestamp_ms=100,
                                face_matrix_values={}, frame_index=1)
        # Paused frames do not even build an experimental row.
        with patch.object(probe, "exploratory_csv_row", return_value=row(100)) as builder:
            self.assertFalse(accept_probe_frame(self.capture, frame))
            builder.assert_not_called()
            self.select("upright")
            accept_probe_frame(self.capture, frame)
            self.assertIs(builder.call_args.kwargs["pose_detected"], False)
        frame.pose_detected = None
        with self.assertRaisesRegex(ValueError, "same-frame"):
            accept_probe_frame(self.capture, frame)

    def test_existing_outputs_are_never_overwritten(self):
        before = (self.root / "features.csv").read_bytes()
        with self.assertRaises(FileExistsError):
            PilotCapture(self.root, "P01", "SYNTHETIC_CAPTURE", probe.CSV_FIELDS)
        self.assertEqual((self.root / "features.csv").read_bytes(), before)

    def test_p5_supplement_stops_after_seven_and_preserves_original_links(self):
        binding = dict(original_recording_id="SYNTHETIC_ORIGINAL", original_segment_ids=[12,18,24,36,48,54,60])
        target = Path(self.temp) / "p5_supplement"
        capture = PilotCapture(target, "P01", "SYNTHETIC_SUPPLEMENT", probe.CSV_FIELDS, supplement_for=binding)
        self.addCleanup(capture.finish)
        self.assertEqual(capture.target_segments, 7)
        self.assertEqual(capture.expected, "lean_forward")
        capture.choose("lean_forward")
        self.assertFalse(capture.start())
        for i in range(7):
            capture.choose("upright")  # unrecorded reset, never a P0 sample
            self.assertFalse(capture.start())
            capture.choose("lean_forward")
            self.assertTrue(capture.start())
            for j, offset in enumerate(range(0,10001,250)):
                capture.accept(row(i*20000+offset), i*100+j)
        self.assertTrue(capture.done)
        self.assertFalse(capture.start())
        capture.finish()
        summary = json.loads((target / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["completed_segments"], 7)
        self.assertEqual(summary["counts"]["lean_forward"], 7)
        self.assertEqual(summary["counts"]["upright"], 0)
        self.assertEqual([s["supplement_for"]["segment_id"] for s in summary["segments"]], binding["original_segment_ids"])
        samples = load_labeled_probe_h_samples([target / "features.csv"])
        self.assertEqual(len(samples), 7)
        self.assertTrue(all(s.label == "lean_forward" and s.eligible for s in samples))

    def test_p5_supplement_rejects_wrong_subject_and_duplicate_original_ids(self):
        binding = dict(original_recording_id="SYNTHETIC_ORIGINAL", original_segment_ids=list(range(7)))
        with self.assertRaisesRegex(ValueError, "P01"):
            PilotCapture(Path(self.temp)/"wrong_person", "P02", "SYNTHETIC", probe.CSV_FIELDS, supplement_for=binding)
        binding["original_segment_ids"] = [12]*7
        with self.assertRaisesRegex(ValueError, "distinct"):
            PilotCapture(Path(self.temp)/"bad_ids", "P01", "SYNTHETIC", probe.CSV_FIELDS, supplement_for=binding)
        self.assertFalse((Path(self.temp)/"wrong_person").exists())
        self.assertFalse((Path(self.temp)/"bad_ids").exists())

    def test_supplement_binding_verifies_original_bytes_without_newest_selection(self):
        import hashlib
        original = Path(self.temp) / "captures/SYNTHETIC_ORIGINAL"
        original.mkdir(parents=True)
        features = original / "features.csv"
        features.write_text("synthetic original bytes", encoding="utf-8")
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        summary = dict(scope="EXPLORATORY_PILOT_ONLY", subject="P01", recording_id=original.name,
                       status="COMPLETED", completed_segments=60, features_sha256=sha(features))
        summary_path = original / "run_summary.json"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        review = dict(samples=[dict(subject="P01",label="lean_forward",eligible=False,
                                   sample_key=["synthetic",original.name,str(i)]) for i in range(1,8)],
                      inputs={str(p.relative_to(self.temp)):sha(p) for p in (features, summary_path)})
        review_path = Path(self.temp) / "synthetic_review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        binding = load_p5_supplement_binding(review_path, self.temp)
        self.assertEqual(binding["original_segment_ids"], list(range(1,8)))
        features.write_text("changed original bytes", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"reviewed bytes"):
            load_p5_supplement_binding(review_path, self.temp)


if __name__ == "__main__":
    unittest.main()
