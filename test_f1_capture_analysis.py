"""Synthetic/mocked integration only: no device access or research results."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import analyze_d455 as analysis
import f1_csv_adapter as adapter
import f1_features
import train_f1_demo_rf as trainer
from test_capture_protocol import load_capture
from test_f1_features import frame_row
from test_frame_schema import canonical_row
import test_frame_schema
import test_analysis_provenance


def row(index=1, **changes):
    result = canonical_row(index, **frame_row())
    result.update(step="1", label="forward_head")
    result.update(changes)
    return result


class CaptureRoutingTests(unittest.TestCase):
    def setUp(self):
        self.capture = load_capture()

    def test_default_and_explicit_preview_never_record_or_run_legacy(self):
        with patch("live_f1_d455.run_preview") as preview, \
                patch.object(self.capture, "legacy_main") as legacy, \
                patch.object(self.capture, "record_f1") as record, \
                patch.object(self.capture, "reserve_capture") as reserve:
            self.capture.main([])
            self.capture.main(["preview"])
        self.assertEqual(preview.call_count, 2)
        legacy.assert_not_called()
        record.assert_not_called()
        reserve.assert_not_called()

    def test_patch8_positional_and_explicit_legacy_routing(self):
        argv = ["P03", "101", "core", "--dataset-role", "formal"]
        with patch.object(self.capture, "legacy_main") as legacy, \
                patch.object(self.capture, "record_f1") as record:
            self.capture.main(argv)
            legacy.assert_called_with(argv)
            self.capture.main(["legacy", *argv])
            legacy.assert_called_with(argv)
        record.assert_not_called()

    def test_record_is_explicit_and_accepts_non_upright(self):
        with patch.object(self.capture, "record_f1") as record, \
                patch.object(self.capture, "legacy_main") as legacy:
            self.capture.main(["record", "P03", "1", "--label", "lean_left", "--duration", "10"])
        self.assertEqual(record.call_args.args[0].label, "lean_left")
        legacy.assert_not_called()

    def test_record_rejects_invalid_duration_or_formal_role_before_hardware(self):
        import contextlib
        for extra in (["--duration", "nan"], ["--duration", "0"], ["--duration", "-2"],
                      ["--duration", "10", "--dataset-role", "formal"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(self.capture, "record_f1") as record, self.assertRaises(SystemExit):
                self.capture.main(["record", "P03", "1", "--label", "forward_head", *extra])
            record.assert_not_called()

    def run_record(self, *, interrupt=False, fail=False, stop_fail=False):
        capture = self.capture
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            sdk, gui = Mock(), Mock()
            sdk.camera_info = NS(name="name", serial_number="serial")
            device = Mock()
            device.get_info.side_effect = lambda name: "Intel RealSense D455" if name == "name" else "TEST"
            sdk.context.return_value.query_devices.return_value = [device]
            pipe = sdk.pipeline.return_value
            profile = pipe.start.return_value
            profile.get_device.return_value = device
            device.first_depth_sensor.return_value.get_depth_scale.return_value = .001
            stream = profile.get_stream.return_value.as_video_stream_profile.return_value
            stream.get_extrinsics_to.return_value = NS(rotation=[0.] * 9, translation=[0.] * 3)
            stream.get_intrinsics.return_value = NS(width=1280, height=720, fx=1., fy=1., ppx=0., ppy=0.,
                                                   model="synthetic", coeffs=[0.] * 5)
            frames = Mock()
            frames.get_timestamp.side_effect = [1000., 12000.]
            frames.get_color_frame.return_value = None
            pipe.wait_for_frames.return_value = frames
            if fail:
                pipe.wait_for_frames.side_effect = RuntimeError("synthetic camera failure")
            if stop_fail:
                pipe.stop.side_effect = RuntimeError("synthetic stop failure")
            gui.waitKey.return_value = ord("q") if interrupt else -1
            gui.getWindowProperty.return_value = 1
            stack.enter_context(patch.object(capture, "rs", sdk))
            stack.enter_context(patch.object(capture, "cv2", gui))
            stack.enter_context(patch.object(capture, "make_config", return_value=Mock()))
            stack.enter_context(patch.object(capture.time, "monotonic", side_effect=[0., 1., 11.]))
            stack.enter_context(patch.object(capture, "guide_phase", side_effect=AssertionError("legacy guide")))
            stack.enter_context(patch.object(capture, "quality_check", side_effect=AssertionError("legacy gate")))
            args = capture.parse_f1_capture_args(["record", "P03", "1", "--label", "forward_head",
                                                 "--duration", "10", "--output-dir", directory])
            if fail or stop_fail:
                with self.assertRaises(RuntimeError):
                    capture.record_f1(args)
            else:
                capture.record_f1(args)
            pipe.stop.assert_called_once()
            camera = next(Path(directory).glob("*_camera.json"))
            metadata = json.loads(camera.read_text(encoding="utf-8"))
            marks = analysis.load_markers(str(camera).replace("_camera.json", ".db3"))
            self.assertIs(metadata["personal_calibration"], False)
            self.assertIsNone(metadata["forward_target_min_m"])
            self.assertEqual(metadata["dataset_role"], "pilot")
            self.assertEqual(metadata["quality_assessment"], "NOT_ASSESSED")
            self.assertNotEqual(metadata["protocol_version"], capture.PROTOCOL_VERSION)
            self.assertEqual(set(metadata["sidecar_files"]), {"camera", "markers"})
            self.assertFalse(list(Path(directory).glob("*_quality.json")))
            return metadata, marks

    def test_record_native_markers_without_upright_or_gate(self):
        metadata, marks = self.run_record()
        self.assertEqual(metadata["capture_status"], "completed")
        self.assertEqual([m["label"] for m in marks], ["forward_head", "end"])

    def test_interrupted_record_not_complete(self):
        metadata, marks = self.run_record(interrupt=True)
        self.assertEqual(metadata["capture_status"], "interrupted")
        self.assertEqual(marks[-1]["phase"], "aborted")

    def test_camera_failure_preserves_failed_metadata(self):
        metadata, marks = self.run_record(fail=True)
        self.assertEqual(metadata["capture_status"], "failed")
        self.assertEqual(marks, [])

    def test_recorder_stop_failure_is_not_completed(self):
        metadata, _ = self.run_record(stop_fail=True)
        self.assertEqual(metadata["capture_status"], "failed")


class F1AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_saved_canonical_csv_to_five_features_no_upright(self):
        path = self.root / "frames.csv"
        analysis.write_frames_csv(path, [row()])
        typed, records = adapter.load_f1_frame_records(str(path))
        result = analysis.write_f1_analysis(typed, self.root)
        self.assertEqual(result["frames"][0]["features"], dict(f1_features.compute_f1_5_frame(row()).features))
        self.assertEqual(records[0].result.ordered_values(), (0., -1., 0., -1.5, 0.))
        self.assertIsNone(result["samples"])
        self.assertIsNone(result["evaluation"])
        self.assertFalse(list(self.root.glob("*summary*")))
        with self.assertRaises(FileExistsError):
            analysis.write_f1_analysis(typed, self.root)

    def test_missing_hip_retained_and_explicit_aggregation_only(self):
        result = analysis.write_f1_analysis([row(left_hip_valid=False)], self.root, support="family")
        self.assertIsNone(result["frames"][0]["features"]["sh_y"])
        self.assertEqual(result["aggregation_status"], "ENGINEERING_UNAPPROVED")
        self.assertIsNone(result["samples"][0]["features"]["sh_y"])

    def test_native_extractor_no_upright_to_adapter(self):
        fixture = test_frame_schema.FrameSchemaTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = fixture._recording
        def recording():
            path = original()
            marker = Path(path).with_suffix("")
            Path(str(marker) + "_markers.csv").write_text(
                "frame_timestamp_ms,phase,label,step\n0,hold,lean_left,1\n30000,end,end,1\n", encoding="utf-8")
            return path
        pose = [NS(x=.5, y=.5, visibility=.9) for _ in range(33)]
        pose[11], pose[12] = NS(x=.7, y=.4), NS(x=.3, y=.4)
        pose[23], pose[24] = NS(x=.7, y=.8), NS(x=.3, y=.8)
        with patch.object(fixture, "_recording", side_effect=recording):
            rows, _, _ = fixture._extract([(2000., 1, 1)], pose=pose, face=True)
        self.assertEqual(rows[0]["label"], "lean_left")
        _, records = adapter.load_f1_frame_records(str(next(fixture.out.glob("*_frames.csv"))))
        self.assertTrue(all(v is not None for v in records[0].result.ordered_values()))

    def test_f1_raw_and_csv_pipeline_skip_legacy_summary_preserve_lineage(self):
        binding = patch.object(test_analysis_provenance, "analysis", analysis)
        binding.start()
        self.addCleanup(binding.stop)
        fixture = test_analysis_provenance.AnalysisProvenanceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = fixture.recording()
        camera = str(Path(raw).with_suffix("")) + "_camera.json"
        info = analysis.read_json(camera)
        info.update(protocol_version="capture-f1-engineering/0.1-unapproved", dataset_role="pilot",
                    capture_status="completed")
        analysis.write_json(camera, info)
        args = NS(subjects=[], from_csv=False, legacy_pilot=False, step=1, f1=True, support=None, model=None)
        def extract(path, models, step, provenance, output_dir):
            rows = [row(recording_id=provenance["recording_id"], analysis_run_id=provenance["analysis_run_id"])]
            analysis.write_frames_csv(Path(output_dir) / (Path(path).stem + "_frames.csv"), rows)
            return rows
        with patch.object(analysis, "ensure_models", return_value=fixture.model_paths()), \
                patch.object(analysis, "process_recording", side_effect=extract), \
                patch.object(analysis, "summarize", side_effect=AssertionError("legacy summary")), \
                patch.object(analysis, "plot_all", side_effect=AssertionError("legacy plot")):
            analysis.run_analysis([raw], args)
            csv = next(fixture.out.glob("*_frames.csv"))
            args.from_csv = True
            analysis.run_analysis([str(csv)], args)
        self.assertEqual(len(list(fixture.out.glob("batches/*/f1_analysis.json"))), 2)
        self.assertEqual({m["status"] for m in fixture.manifests()}, {"completed"})
        self.assertFalse(list(fixture.out.rglob("summary_steps.csv")))
        args.from_csv = False
        for status in ("interrupted", "failed", "recording", "reserved"):
            info["capture_status"] = status
            analysis.write_json(camera, info)
            with self.assertRaisesRegex(ValueError, "not completed"):
                analysis.start_analysis_run(raw, args, "synthetic")

    def test_existing_rf_train_predict_and_evaluate_without_reference(self):
        rows = [row(i + 1, step=str(i + 1), label=label, face_x=640. + i * 100)
                for i, label in enumerate(("upright", "forward_head", "body_forward"))]
        path, model = self.root / "train.csv", self.root / "rf.json"
        analysis.write_frames_csv(path, rows)
        trainer.train_f1_demo_rf([path], model, n_estimators=3)
        heldout = [row(recording_id="heldout", label="forward_head"),
                   row(2, recording_id="heldout", left_hip_valid=False),
                   row(3, step="2", recording_id="heldout", label="lean_left")]
        payload = analysis.write_f1_analysis(heldout, self.root, model_path=str(model))
        stats = payload["evaluation"]
        self.assertEqual(stats["evaluated_frames"], 1)
        self.assertEqual(stats["unavailable_frames"], 1)
        self.assertEqual(stats["unsupported_label_frames"], 1)
        self.assertEqual(sum(map(sum, stats["confusion_matrix_true_by_predicted"])), 1)
        with self.assertRaisesRegex(ValueError, "overlap"):
            analysis.write_f1_analysis(rows, self.root, model_path=str(model))


if __name__ == "__main__":
    unittest.main()
