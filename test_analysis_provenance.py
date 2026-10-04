"""Analysis lineage tests with temporary artifacts; no camera, models, or network required."""
import builtins
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np


SCRIPT = Path(__file__).with_name("analyze_d455.py")


def load_analyzer():
    spec = importlib.util.spec_from_file_location("analysis_provenance_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    real_import = builtins.__import__
    cv2 = types.SimpleNamespace(COLOR_BGR2RGB=1, cvtColor=lambda image, code: image)
    def without_cv2(name, *args, **kwargs):
        return cv2 if name == "cv2" else real_import(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=without_cv2):
        spec.loader.exec_module(module)
    return module


analysis = load_analyzer()


class AnalysisProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.out, self.data, self.models = [self.root / name for name in ("analysis", "data", "models")]
        for directory in (self.out, self.data, self.models):
            directory.mkdir()
        for name, path in (("OUT_DIR", self.out), ("DATA_DIR", self.data), ("MODEL_DIR", self.models)):
            self.stack.enter_context(patch.object(analysis, name, str(path)))
        # Synthetic bytes exercise provenance structure, never research model results.
        self.lock = analysis.read_json(analysis.MODEL_LOCK_PATH)
        for entry in self.lock["artifacts"]:
            entry["sha256"] = hashlib.sha256(b"synthetic model " + entry["role"].encode()).hexdigest()
        lock_path = self.root / "mediapipe_model_lock.json"
        analysis.write_json(lock_path, self.lock)
        self.stack.enter_context(patch.object(analysis, "MODEL_LOCK_PATH", str(lock_path)))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stderr = self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.versions = self.stack.enter_context(patch.object(analysis.importlib.metadata, "version",
                                                            side_effect=lambda name: "test-" + name))
        self.stack.enter_context(patch.object(analysis.platform, "platform", return_value="test OS"))
        self.git = self.stack.enter_context(patch.object(analysis.subprocess, "run", side_effect=lambda cmd, **kw:
            subprocess.CompletedProcess(cmd, 0, "a" * 40 if "rev-parse" in cmd else " M analyze_d455.py", "")))
        self.args = types.SimpleNamespace(subjects=["P03"], step=2, from_csv=False, legacy_pilot=False)

    def recording(self, identity="P03_r1_20261001_143025_123456_" + "a" * 32, legacy=False):
        path = self.data / (identity + ".bag")
        path.write_bytes(b"synthetic raw fixture")
        base = path.with_suffix("")
        if not legacy:
            analysis.write_json(str(base) + "_camera.json", {
                "recording_id": identity, "record_file": path.name, "dataset_role": "formal",
                "protocol_version": "capture-forward-face-v2.0.0",
            })
        Path(str(base) + "_markers.csv").write_text(
            "frame_timestamp_ms,phase,label,step\n0,hold,upright,1\n10000,hold,forward_head,2\n20000,end,end,\n")
        return str(path)

    def model_paths(self):
        paths = {}
        for role, filename in analysis.MODEL_FILENAMES.items():
            path = self.models / filename
            path.write_bytes(b"synthetic model " + role.encode())
            paths[role] = str(path)
        return paths

    def rows(self, subject="P03", rnd="1"):
        return [dict(subject=subject, round=rnd, step=str(step), label=label, t=2.0, ts_ms=ts,
                     face_area_px=area, oval_area_px=area / 2, face_w_px=100, z_face_m=zf, z_sh_m=zs)
                for step, label, ts, area, zf, zs in (
                    (1, "upright", 2000., 100., .75, .8),
                    (2, "forward_head", 12000., 125., .65, .79))]

    def fake_process(self, path, models, step, provenance=None, output_dir=None):
        for role in models:
            analysis.mark_model_used(provenance, role)
        subject, rnd = analysis.parse_name(path)
        rows = self.rows(subject, rnd)
        analysis.write_csv(os.path.join(output_dir or analysis.OUT_DIR, Path(path).stem + "_frames.csv"), rows)
        return rows

    def fake_plot(self, rows, summary):
        Path(analysis.OUT_DIR, "fig2_fh_vs_bf.png").write_bytes(b"synthetic plot fixture")

    def run_raw(self, path):
        models = self.model_paths()
        with patch.object(analysis, "ensure_models", return_value=models), \
                patch.object(analysis, "process_recording", side_effect=self.fake_process), \
                patch.object(analysis, "plot_all", side_effect=self.fake_plot):
            analysis.run_analysis([path], self.args)
        return self.out / (Path(path).stem + "_frames.csv")

    def manifests(self):
        return [analysis.read_json(str(p)) for p in self.out.glob("*/ar_*/analysis_manifest.json")]

    def test_same_recording_new_run_ids_and_capture_identity(self):
        path = self.recording()
        with patch.object(analysis, "utc_now", return_value=datetime(2026, 10, 1, tzinfo=timezone.utc)):
            first_dir, first = analysis.start_analysis_run(path, self.args, "batch")
            second_dir, second = analysis.start_analysis_run(path, self.args, "batch")
        self.assertNotEqual(first_dir, second_dir)
        self.assertNotEqual(first["analysis_run_id"], second["analysis_run_id"])
        self.assertEqual(first["recording_id"], second["recording_id"])
        self.assertEqual(first["recording_id"], Path(path).stem)
        self.assertNotEqual(first["recording_id"], first["analysis_run_id"])
        self.assertRegex(first["analysis_run_id"], r"^ar_20261001T000000000000Z_[a-f0-9]{32}$")
        self.assertEqual(first["dataset_role"], "formal")
        self.assertEqual(first["inputs"]["recording"]["sha256"], hashlib.sha256(Path(path).read_bytes()).hexdigest())
        self.assertEqual(first["inputs"]["capture_metadata"]["filename"], Path(path).stem + "_camera.json")

    def test_legacy_raw_has_hash_identity_and_remains_pilot(self):
        path = self.recording("P01_r1_20260901_120000", legacy=True)
        self.args.legacy_pilot = True
        _, info = analysis.start_analysis_run(path, self.args, "batch")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(info["recording_id"], "legacy_" + Path(path).stem + "_" + digest[:16])
        self.assertEqual(info["dataset_role"], "pilot")
        self.assertEqual(info["protocol_version"], "unknown_legacy")
        self.assertEqual(info["inputs"]["capture_metadata"]["hash_status"], "unavailable")

    def test_legacy_raw_requires_explicit_opt_in(self):
        path = self.recording("P01_r1_old", legacy=True)
        for metadata in (None, {"subject": "P01", "round": 1, "start_time": "20260901_120000"}):
            with self.subTest(metadata=metadata):
                if metadata is not None:
                    analysis.write_json(str(Path(path).with_suffix("")) + "_camera.json", metadata)
                with self.assertRaisesRegex(ValueError, "requires explicit --legacy-pilot"):
                    analysis.start_analysis_run(path, self.args, "batch")
        self.assertEqual(self.manifests(), [])

    def test_legacy_csv_requires_explicit_opt_in(self):
        frame = self.out / "P01_r1_old_frames.csv"
        analysis.write_csv(str(frame), self.rows("P01"))
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "requires explicit --legacy-pilot"):
            analysis.start_analysis_run(str(frame), self.args, "batch")
        self.assertEqual(self.manifests(), [])

    def test_legacy_opt_in_records_reason_identity_basis_and_unknown_history(self):
        self.args.legacy_pilot = True
        raw = self.recording("P01_r1_old", legacy=True)
        # 실제 legacy metadata도 허용하며, 이 값을 현대 provenance로 채워 넣지 않는다.
        analysis.write_json(str(Path(raw).with_suffix("")) + "_camera.json", {"subject": "P01", "round": 1})
        frame = self.out / "P01_r1_old_frames.csv"
        analysis.write_csv(str(frame), self.rows("P01"))
        for from_csv, path, source in ((False, raw, "recording"), (True, str(frame), "frames")):
            with self.subTest(from_csv=from_csv):
                self.args.from_csv = from_csv
                directory, info = analysis.start_analysis_run(path, self.args, "batch")
                self.assertEqual(info, analysis.read_json(str(Path(directory) / "analysis_manifest.json")))
                self.assertIs(info["options"]["legacy_pilot"], True)
                self.assertEqual(info["dataset_role"], "pilot")
                self.assertEqual(info["protocol_version"], "unknown_legacy")
                evidence = info["legacy_input"]
                self.assertTrue(evidence["reason"])
                self.assertIsNone(evidence["original_recording_id"])
                self.assertEqual(evidence["historical_provenance"], "unknown")
                self.assertEqual(evidence["identity_source_input"], source)
                self.assertIn("SHA-256", evidence["id_generation"])
                self.assertTrue(info["recording_id"].endswith(info["inputs"][source]["sha256"][:16]))
                self.assertIsNone(info["parent_analysis_run_id"])
                self.assertEqual(info["models"], [])

    def test_legacy_flag_cannot_bypass_missing_modern_capture(self):
        path = self.recording(legacy=True)
        self.args.legacy_pilot = True
        with self.assertRaisesRegex(ValueError, "legacy downgrade forbidden"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_legacy_flag_cannot_bypass_modern_metadata_or_id_column(self):
        path = self.recording("P03_r1_old", legacy=True)
        self.args.legacy_pilot = True
        camera = str(Path(path).with_suffix("")) + "_camera.json"
        for metadata in ({"recording_id": None}, {"schema_version": "capture-provenance/1.0.0"},
                         {"protocol_version": "capture-forward-face-v2.0.0"},
                         {"dataset_role": "formal"}, {"dataset_role": "external"}):
            with self.subTest(metadata=metadata):
                analysis.write_json(camera, metadata)
                with self.assertRaisesRegex(ValueError, "legacy downgrade forbidden"):
                    analysis.start_analysis_run(path, self.args, "batch")
        Path(camera).unlink()
        self.markers_with_ids(path, [""])
        with self.assertRaisesRegex(ValueError, "legacy downgrade forbidden"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_legacy_flag_cannot_bypass_missing_csv_parent(self):
        frame = self.run_raw(self.recording())
        link = analysis.read_json(str(frame) + ".provenance.json")
        (self.out / link["analysis_manifest"]).unlink()
        self.args.from_csv = self.args.legacy_pilot = True
        with self.assertRaisesRegex(ValueError, "parent manifest hash mismatch"):
            analysis.start_analysis_run(str(frame), self.args, "batch")
        Path(str(frame) + ".provenance.json").unlink()
        with self.assertRaisesRegex(ValueError, "verified provenance sidecar"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_legacy_flag_cannot_bypass_csv_identity_columns(self):
        self.args.from_csv = self.args.legacy_pilot = True
        frame = self.out / "P01_r1_old_frames.csv"
        for field in ("recording_id", "analysis_run_id"):
            for value in ("", "modern_identity"):
                with self.subTest(field=field, value=value):
                    analysis.write_csv(str(frame), [dict(row, **{field: value}) for row in self.rows("P01")])
                    with self.assertRaisesRegex(ValueError, "verified provenance sidecar"):
                        analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_formal_external_roles_conflict_with_legacy_flag(self):
        path = self.recording()
        camera = str(Path(path).with_suffix("")) + "_camera.json"
        meta = analysis.read_json(camera)
        for role in ("formal", "external"):
            with self.subTest(role=role):
                meta["dataset_role"] = role
                analysis.write_json(camera, meta)
                self.args.legacy_pilot = False
                _, modern = analysis.start_analysis_run(path, self.args, "batch")
                self.assertEqual(modern["dataset_role"], role)
                self.assertIsNone(modern["legacy_input"])
                self.args.legacy_pilot = True
                with self.assertRaisesRegex(ValueError, "conflicts with formal/external"):
                    analysis.start_analysis_run(path, self.args, "batch")

    def test_linked_formal_parent_conflicts_with_legacy_flag(self):
        frame = self.run_raw(self.recording())
        self.args.from_csv = self.args.legacy_pilot = True
        with self.assertRaisesRegex(ValueError, "conflicts with formal/external"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_cli_legacy_raw_opt_in_and_default(self):
        path = self.recording("P01_r1_old", legacy=True)
        with patch.object(analysis, "find_recordings", return_value=[path]), \
                patch.object(analysis, "ensure_models", return_value=self.model_paths()), \
                patch.object(analysis, "process_recording", side_effect=self.fake_process), \
                patch.object(analysis, "plot_all", side_effect=self.fake_plot):
            with patch.object(analysis.sys, "argv", ["analyze_d455.py", "P01"]):
                with self.assertRaisesRegex(ValueError, "requires explicit --legacy-pilot"):
                    analysis.main()
            with patch.object(analysis.sys, "argv", ["analyze_d455.py", "P01", "--legacy-pilot"]):
                analysis.main()
        info = self.manifests()[0]
        self.assertEqual(info["status"], "completed")
        self.assertEqual(info["dataset_role"], "pilot")
        self.assertIs(info["options"]["legacy_pilot"], True)

    def test_capture_mismatch_rejected_instead_of_guessing(self):
        path = self.recording()
        meta_path = str(Path(path).with_suffix("")) + "_camera.json"
        meta = analysis.read_json(meta_path)
        meta["record_file"] = "another.bag"
        analysis.write_json(meta_path, meta)
        with self.assertRaisesRegex(ValueError, "record_file mismatch"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_raw_content_cannot_change_under_same_recording_id(self):
        path = self.recording()
        analysis.start_analysis_run(path, self.args, "batch")
        Path(path).write_bytes(b"different raw content")
        with self.assertRaisesRegex(ValueError, "different raw content"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_script_git_environment_and_options(self):
        self.args.step = 0
        with patch.object(analysis.sys, "argv", ["analyze_d455.py", "P03", "--step", "0"]):
            _, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
        self.assertEqual(info["code"]["analyze_script_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        self.assertEqual(info["code"]["git_commit"], "a" * 40)
        self.assertIs(info["code"]["git_dirty"], True)
        self.assertEqual(self.git.call_args_list[0].kwargs["cwd"], str(SCRIPT.parent))
        self.assertEqual(info["environment"]["python"], platform.python_version())
        self.assertEqual(info["environment"]["mediapipe"], "test-mediapipe")
        self.assertEqual(info["options"], dict(argv=["P03", "--step", "0"], subjects=["P03"],
                                              from_csv=False, legacy_pilot=False, step_requested=0, step_effective=1))
        self.assertEqual(info["analysis_mode"], "extract_raw")

    def test_git_failure_is_nonfatal_and_explained(self):
        for failure in (FileNotFoundError("git missing"), subprocess.CalledProcessError(128, "git"),
                        subprocess.TimeoutExpired("git", 3)):
            self.git.side_effect = failure
            _, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
            self.assertIsNone(info["code"]["git_commit"])
            self.assertIsNone(info["code"]["git_dirty"])
            self.assertIn("code.git_commit", info["provenance_unknown_reasons"])
            self.assertIsNotNone(info["code"]["analyze_script_sha256"])

    def test_package_and_script_hash_failure_are_nonfatal(self):
        self.versions.side_effect = analysis.importlib.metadata.PackageNotFoundError("not installed")
        with patch.object(analysis, "__file__", str(self.root / "missing_script.py")):
            _, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
        self.assertIsNone(info["code"]["analyze_script_sha256"])
        self.assertIsNone(info["environment"]["mediapipe"])
        self.assertIn("environment.mediapipe", info["provenance_unknown_reasons"])
        self.assertIn("[경고]", self.stderr.getvalue())

    def test_model_content_hash_and_used_flags(self):
        paths = self.model_paths()
        _, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
        analysis.record_model_artifacts(info, paths)
        self.assertEqual(len(info["models"]), 3)
        for entry in info["models"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest())
            self.assertEqual(entry["filename"], Path(paths[entry["role"]]).name)
            locked = next(item for item in self.lock["artifacts"] if item["role"] == entry["role"])
            self.assertEqual(entry["source_url"], locked["source_url"])
            self.assertEqual(entry["version_identifier"], locked["version_identifier"])
            self.assertIs(entry["used_in_this_run"], False)
        first = info["models"][0]["sha256"]
        Path(paths["face"]).write_bytes(b"changed same filename")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            analysis.record_model_artifacts(info, paths)
        self.assertEqual(first, info["models"][0]["sha256"])
        analysis.mark_model_used(info, "face")
        self.assertEqual([m["used_in_this_run"] for m in info["models"]], [True, False, False])

    def test_existing_models_not_downloaded_or_overwritten(self):
        paths = self.model_paths()
        before = {k: Path(p).read_bytes() for k, p in paths.items()}
        with patch.object(analysis.urllib.request, "urlretrieve", side_effect=AssertionError("network forbidden")) as download:
            self.assertEqual(analysis.ensure_models(), paths)
        download.assert_not_called()
        self.assertEqual(before, {k: Path(p).read_bytes() for k, p in paths.items()})

    def test_raw_reruns_preserve_archive_and_csv_parent(self):
        path = self.recording()
        frame = self.run_raw(path)
        first = self.manifests()[0]
        archived = Path(next(o["path"] for o in first["outputs"] if o["kind"] == "frames"))
        frame_bytes = archived.read_bytes()
        first_manifest = self.out / first["recording_id"] / first["analysis_run_id"] / "analysis_manifest.json"
        manifest_bytes = first_manifest.read_bytes()
        self.run_raw(path)
        self.assertEqual(len(self.manifests()), 2)
        self.assertEqual(first_manifest.read_bytes(), manifest_bytes)
        self.assertEqual(archived.read_bytes(), frame_bytes)
        link = analysis.read_json(str(frame) + ".provenance.json")
        self.assertNotEqual(link["analysis_run_id"], first["analysis_run_id"])
        self.args.from_csv = True
        with patch.object(analysis, "ensure_models", side_effect=AssertionError("no models on csv path")), \
                patch.object(analysis, "process_recording", side_effect=AssertionError("no inference")), \
                patch.object(analysis, "plot_all", side_effect=self.fake_plot):
            analysis.run_analysis([str(frame)], self.args)
        csv_run = next(m for m in self.manifests() if m["analysis_mode"] == "summarize_existing_frames")
        self.assertEqual(csv_run["recording_id"], first["recording_id"])
        self.assertEqual(csv_run["parent_analysis_run_id"], link["analysis_run_id"])
        self.assertEqual(csv_run["inputs"]["frames"]["analysis_run_id"], link["analysis_run_id"])
        self.assertIs(csv_run["inference_performed"], False)
        self.assertTrue(all(not m["used_in_this_run"] for m in csv_run["models"]))
        self.assertIsNone(csv_run["options"]["step_effective"])
        self.assertEqual(frame.read_bytes(), frame_bytes)
        self.assertEqual(analysis.read_json(str(frame) + ".provenance.json"), link)

    def test_legacy_csv_does_not_claim_models_or_raw_identity(self):
        frame = self.out / "P01_r1_old_frames.csv"
        analysis.write_csv(str(frame), self.rows("P01"))
        self.args.from_csv = True
        self.args.legacy_pilot = True
        with patch.object(analysis, "ensure_models", side_effect=AssertionError("no model acquisition")), \
                patch.object(analysis, "plot_all", side_effect=self.fake_plot):
            analysis.run_analysis([str(frame)], self.args)
        info = self.manifests()[0]
        self.assertEqual(info["recording_id"], "legacy_csv_" + frame.stem + "_" + hashlib.sha256(frame.read_bytes()).hexdigest()[:16])
        self.assertEqual(info["dataset_role"], "pilot")
        self.assertEqual(info["identity_status"], "unresolved_raw")
        self.assertEqual(info["models"], [])
        self.assertIsNone(info["parent_analysis_run_id"])

    def test_tampered_csv_link_rejected(self):
        frame = self.run_raw(self.recording())
        frame.write_bytes(frame.read_bytes() + b"\n")
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "frames provenance hash mismatch"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_tampered_parent_manifest_rejected(self):
        frame = self.run_raw(self.recording())
        link = analysis.read_json(str(frame) + ".provenance.json")
        parent = self.out / link["analysis_manifest"]
        parent.write_bytes(parent.read_bytes() + b"\n")
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "parent manifest hash mismatch"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_legacy_raw_can_be_reanalyzed_after_csv_run(self):
        path = self.recording("P01_r1_old", legacy=True)
        self.args.legacy_pilot = True
        frame = self.run_raw(path)
        self.args.from_csv = True
        with patch.object(analysis, "plot_all", side_effect=self.fake_plot):
            analysis.run_analysis([str(frame)], self.args)
        self.args.from_csv = False
        self.run_raw(path)
        self.assertEqual(len(self.manifests()), 3)
        self.assertEqual(len({m["recording_id"] for m in self.manifests()}), 1)

    def test_failure_manifest_and_output_directory_restore(self):
        path = self.recording()
        with patch.object(analysis, "ensure_models", return_value=self.model_paths()), \
                patch.object(analysis, "process_recording", side_effect=self.fake_process), \
                patch.object(analysis, "plot_all", side_effect=RuntimeError("plot failed")):
            with self.assertRaisesRegex(RuntimeError, "plot failed"):
                analysis.run_analysis([path], self.args)
        self.assertEqual(analysis.OUT_DIR, str(self.out))
        manifest = self.manifests()[0]
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["errors"], ["plot failed"])
        self.assertIsNotNone(manifest["ended_at"])

    def test_shared_outputs_list_all_contributing_runs(self):
        paths = [self.recording(), self.recording("P03_r2_20261001_143026_123456_" + "b" * 32)]
        Path(paths[1]).write_bytes(b"distinct synthetic second recording")
        with patch.object(analysis, "ensure_models", return_value=self.model_paths()), \
                patch.object(analysis, "process_recording", side_effect=self.fake_process), \
                patch.object(analysis, "plot_all", side_effect=self.fake_plot):
            analysis.run_analysis(paths, self.args)
        infos = self.manifests()
        ids = {m["analysis_run_id"] for m in infos}
        self.assertEqual(len(ids), 2)
        self.assertEqual(len({m["analysis_batch_id"] for m in infos}), 1)
        for info in infos:
            self.assertEqual(info["status"], "completed")
            for output in info["outputs"]:
                path = Path(output["path"])
                self.assertEqual(output["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                if output["kind"] == "batch_output":
                    self.assertEqual(set(output["analysis_run_ids"]), ids)
                    self.assertEqual(path.read_bytes(), (self.out / path.name).read_bytes())

    def test_csv_numerical_reading_and_summary_golden_values(self):
        frame = self.out / "P03_r1_old_frames.csv"
        rows = self.rows()
        analysis.write_csv(str(frame), rows)
        read = analysis.load_frames_csv(["P03"])
        self.assertEqual(read, rows)
        before = frame.read_bytes()
        summary = analysis.summarize([dict(r, recording_id="legacy_test", analysis_run_id=None) for r in read])
        self.assertEqual(summary[0]["A_ratio"], 1.0)
        self.assertEqual(summary[1]["ref_step"], 1)
        self.assertEqual(summary[1]["A_ratio"], 1.25)
        self.assertAlmostEqual(summary[1]["dZ_face_cm"], 10.)
        self.assertAlmostEqual(summary[1]["dZ_sh_cm"], 1.)
        self.assertAlmostEqual(summary[1]["D_head_cm"], 9.)
        self.assertAlmostEqual(summary[1]["sh_face_ratio"], .1)
        self.assertEqual(frame.read_bytes(), before)

    def test_existing_cli_from_csv_options_are_recorded(self):
        frame = self.out / "P03_r1_old_frames.csv"
        analysis.write_csv(str(frame), self.rows())
        with patch.object(analysis.sys, "argv", ["analyze_d455.py", "P03", "--from-csv", "--step", "4", "--legacy-pilot"]), \
                patch.object(analysis, "plot_all", side_effect=self.fake_plot), \
                patch.object(analysis, "ensure_models", side_effect=AssertionError("no download")):
            analysis.main()
        info = self.manifests()[0]
        self.assertEqual(info["options"]["step_requested"], 4)
        self.assertIsNone(info["options"]["step_effective"])
        self.assertEqual(info["analysis_mode"], "summarize_existing_frames")
        self.assertIs(info["options"]["legacy_pilot"], True)

    def test_run_directory_collision_does_not_overwrite(self):
        path = self.recording()
        first_dir, first = analysis.start_analysis_run(path, self.args, "batch")
        saved = Path(first_dir, "analysis_manifest.json").read_bytes()
        new_id = analysis.new_analysis_id()
        with patch.object(analysis, "new_analysis_id", side_effect=[first["analysis_run_id"], new_id]):
            second_dir, second = analysis.start_analysis_run(path, self.args, "batch")
        self.assertEqual(second["analysis_run_id"], new_id)
        self.assertNotEqual(first_dir, second_dir)
        self.assertEqual(Path(first_dir, "analysis_manifest.json").read_bytes(), saved)

    def test_os_version_failure_is_nonfatal(self):
        with patch.object(analysis.platform, "platform", side_effect=OSError("OS unavailable")):
            _, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
        self.assertIsNone(info["environment"]["os"])
        self.assertIn("environment.os", info["provenance_unknown_reasons"])

    def test_source_failed_run_cannot_be_csv_parent(self):
        frame = self.run_raw(self.recording())
        link_path = str(frame) + ".provenance.json"
        link = analysis.read_json(link_path)
        parent = self.out / link["analysis_manifest"]
        info = analysis.read_json(str(parent))
        info["status"] = "failed"
        analysis.write_json(str(parent), info)
        link["analysis_manifest_sha256"] = hashlib.sha256(parent.read_bytes()).hexdigest()
        analysis.write_json(link_path, link)
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "not completed"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_source_csv_without_rows_marks_failed_run(self):
        frame = self.out / "P03_r1_empty_frames.csv"
        frame.write_text("subject,round,step,label\n")
        self.args.from_csv = True
        self.args.legacy_pilot = True
        with self.assertRaisesRegex(RuntimeError, "프레임"):
            analysis.run_analysis([str(frame)], self.args)
        self.assertEqual(self.manifests()[0]["status"], "failed")

    def markers_with_ids(self, path, ids):
        analysis.write_csv(str(Path(path).with_suffix("")) + "_markers.csv", [
            dict(frame_timestamp_ms=i * 10000, phase="hold", label="upright", step=i + 1,
                 recording_id=identity) for i, identity in enumerate(ids)])

    def test_markers_id_mismatch_rejected(self):
        path = self.recording()
        self.markers_with_ids(path, ["different_recording"])
        with self.assertRaisesRegex(ValueError, "recording_id mismatch"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_markers_inconsistent_nonempty_ids_rejected(self):
        path = self.recording()
        self.markers_with_ids(path, [Path(path).stem, "", "different_recording"])
        with self.assertRaisesRegex(ValueError, "inconsistent recording_id"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_markers_and_quality_record_observed_ids_only(self):
        path = self.recording()
        identity = Path(path).stem
        self.markers_with_ids(path, [identity, "", identity])
        quality = str(Path(path).with_suffix("")) + "_quality.json"
        analysis.write_json(quality, {"recording_id": identity})
        _, info = analysis.start_analysis_run(path, self.args, "batch")
        for key in ("markers", "quality"):
            self.assertEqual(info["inputs"][key]["recording_id"], identity)
            self.assertEqual(info["inputs"][key]["identity_status"], "verified")

    def test_legacy_sidecar_identity_not_filled_from_capture(self):
        path = self.recording()
        _, info = analysis.start_analysis_run(path, self.args, "batch")
        self.assertIsNone(info["inputs"]["markers"]["recording_id"])
        self.assertEqual(info["inputs"]["markers"]["identity_status"], "legacy_no_id_column")
        self.assertIsNone(info["inputs"]["quality"]["recording_id"])
        self.assertEqual(info["inputs"]["quality"]["identity_status"], "missing_file")
        analysis.write_json(str(Path(path).with_suffix("")) + "_quality.json", {"pass": True})
        _, info = analysis.start_analysis_run(path, self.args, "batch")
        self.assertIsNone(info["inputs"]["quality"]["recording_id"])
        self.assertEqual(info["inputs"]["quality"]["identity_status"], "legacy_no_id_field")

    def test_quality_id_mismatch_rejected(self):
        path = self.recording()
        self.markers_with_ids(path, [Path(path).stem])
        analysis.write_json(str(Path(path).with_suffix("")) + "_quality.json", {"recording_id": "wrong"})
        with self.assertRaisesRegex(ValueError, "recording_id mismatch"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_new_raw_missing_capture_cannot_downgrade(self):
        path = self.recording(legacy=True)  # new-format filename, even without any sidecar ID
        with self.assertRaisesRegex(ValueError, "legacy downgrade forbidden"):
            analysis.start_analysis_run(path, self.args, "batch")
        self.assertEqual(self.manifests(), [])

    def test_renamed_raw_with_sidecar_id_requires_capture(self):
        path = self.recording("P03_r1_old", legacy=True)
        self.markers_with_ids(path, ["managed_recording"])
        with self.assertRaisesRegex(ValueError, "legacy downgrade forbidden"):
            analysis.start_analysis_run(path, self.args, "batch")

    def test_new_frames_without_link_cannot_downgrade(self):
        frame = self.out / (Path(self.recording()).stem + "_frames.csv")
        analysis.write_csv(str(frame), self.rows())
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "verified provenance sidecar"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_legacy_named_managed_output_without_link_cannot_downgrade(self):
        self.args.legacy_pilot = True
        frame = self.run_raw(self.recording("P01_r1_old", legacy=True))
        Path(str(frame) + ".provenance.json").unlink()
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "verified provenance sidecar"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def rewrite_parent_link(self, frame, mutate):
        link_path = str(frame) + ".provenance.json"
        link = analysis.read_json(link_path)
        parent_path = self.out / link["analysis_manifest"]
        parent = analysis.read_json(str(parent_path))
        mutate(parent, link)
        analysis.write_json(str(parent_path), parent)
        link["analysis_manifest_sha256"] = hashlib.sha256(parent_path.read_bytes()).hexdigest()
        analysis.write_json(link_path, link)

    def test_frames_must_be_listed_in_parent_outputs(self):
        frame = self.run_raw(self.recording())
        self.rewrite_parent_link(frame, lambda parent, link: parent.update(outputs=[]))
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "not listed in parent outputs"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_identical_bytes_under_another_filename_not_parent_output(self):
        frame = self.run_raw(self.recording())
        other = self.out / "P04_r1_other_frames.csv"
        other.write_bytes(frame.read_bytes())
        Path(str(other) + ".provenance.json").write_bytes(Path(str(frame) + ".provenance.json").read_bytes())
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "not listed in parent outputs"):
            analysis.start_analysis_run(str(other), self.args, "batch")

    def test_parent_link_recording_mismatch_rejected(self):
        frame = self.run_raw(self.recording())
        self.rewrite_parent_link(frame, lambda parent, link: link.update(recording_id="wrong"))
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_frames_row_identity_cannot_disagree_with_parent(self):
        frame = self.run_raw(self.recording())
        analysis.write_csv(str(frame), [dict(row, recording_id="wrong") for row in self.rows()])
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        def update_hash(parent, link):
            link["frames_sha256"] = digest
            for output in parent["outputs"]:
                if output["kind"] == "frames":
                    output["sha256"] = digest
        self.rewrite_parent_link(frame, update_hash)
        self.args.from_csv = True
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            analysis.start_analysis_run(str(frame), self.args, "batch")

    def test_flat_publish_failure_never_records_completed(self):
        statuses = []
        original_write, original_copy = analysis.write_json, analysis.shutil.copyfile
        def watch(path, value):
            if str(path).endswith("analysis_manifest.json"):
                statuses.append(value["status"])
            original_write(path, value)
        def fail_frame(source, target):
            if str(target).endswith("_frames.csv"):
                raise OSError("flat frame publish failed")
            return original_copy(source, target)
        with patch.object(analysis, "write_json", side_effect=watch), \
                patch.object(analysis.shutil, "copyfile", side_effect=fail_frame):
            with self.assertRaisesRegex(OSError, "flat frame publish"):
                self.run_raw(self.recording())
        self.assertEqual(statuses, ["running", "failed"])
        self.assertEqual(self.manifests()[0]["status"], "failed")

    def test_sidecar_publish_failure_prevents_completed(self):
        original = analysis.write_json
        def fail_sidecar(path, value):
            if str(path).endswith(".provenance.json"):
                raise OSError("sidecar publish failed")
            return original(path, value)
        with patch.object(analysis, "write_json", side_effect=fail_sidecar):
            with self.assertRaisesRegex(OSError, "sidecar publish"):
                self.run_raw(self.recording())
        self.assertEqual(self.manifests()[0]["status"], "failed")

    def test_completed_is_terminal(self):
        directory, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
        analysis.finish_analysis_run(directory, info)
        before = Path(directory, "analysis_manifest.json").read_bytes()
        analysis.finish_analysis_run(directory, info, OSError("later failure"))
        self.assertEqual(Path(directory, "analysis_manifest.json").read_bytes(), before)
        self.assertEqual(info["status"], "completed")

    def test_atomic_manifest_replace_failure_preserves_valid_json(self):
        directory, info = analysis.start_analysis_run(self.recording(), self.args, "batch")
        path = Path(directory, "analysis_manifest.json")
        before = path.read_bytes()
        with patch.object(analysis.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                analysis.finish_analysis_run(directory, info)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(analysis.read_json(str(path))["status"], "running")
        self.assertEqual(info["status"], "running")
        self.assertEqual(list(Path(directory).glob(".manifest-*.tmp")), [])

    def test_atomic_serialization_failure_preserves_valid_json(self):
        path = self.out / "manifest.json"
        analysis.write_json(str(path), {"status": "running"})
        before = path.read_bytes()
        with self.assertRaises(TypeError):
            analysis.write_json(str(path), {"partial": 1, "invalid": object()})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.out.glob(".manifest-*.tmp")), [])

    def test_processing_depth_settings_match_runtime_threshold(self):
        settings = analysis.processing_settings(False)
        self.assertEqual(settings["shoulder_indices"], [11, 12])
        self.assertEqual(settings["depth_roi"]["face_bbox_fraction"], [.25, .75])
        self.assertEqual(settings["depth_roi"]["oval_center_half_width_px"], 15)
        self.assertEqual(settings["depth_roi"]["shoulder_half_width_px"], 6)
        self.assertEqual(settings["depth_roi"]["min_valid_pixels"], 10)
        depth = np.ones((1, 10)) * 750
        self.assertIsNone(analysis.median_depth(depth, 0, 0, 9, 1, .001))
        self.assertEqual(analysis.median_depth(depth, 0, 0, 10, 1, .001), .75)

    def test_real_extraction_loop_keeps_feature_values_and_schema(self):
        path = self.recording()
        paths = self.model_paths()
        ns = types.SimpleNamespace
        landmarks = [ns(x=.25, y=.25) for _ in range(474)]
        for index, (x, y) in zip(analysis.FACE_OVAL[:4], ((.25, .25), (.75, .25), (.75, .75), (.25, .75))):
            landmarks[index] = ns(x=x, y=y)
        landmarks[analysis.IRIS_L], landmarks[analysis.IRIS_R] = ns(x=.4, y=.5), ns(x=.6, y=.5)
        pose = [ns(x=0, y=0, visibility=1.) for _ in range(33)]
        pose[11], pose[12] = ns(x=.25, y=.8, visibility=.9), ns(x=.75, y=.8, visibility=.8)
        face, mesh, body = Mock(), Mock(), Mock()
        face.detect.return_value = ns(detections=[ns(bounding_box=ns(origin_x=4, origin_y=2, width=8, height=8),
                                                   categories=[ns(score=.95)])])
        mesh.detect_for_video.return_value = ns(face_landmarks=[landmarks])
        body.detect_for_video.return_value = ns(pose_landmarks=[pose])
        option = lambda **kwargs: ns(**kwargs)
        vision = ns(FaceDetector=ns(create_from_options=Mock(return_value=face)),
                    FaceDetectorOptions=lambda **kw: ns(running_mode="IMAGE", min_suppression_threshold=.3, **kw),
                    FaceLandmarker=ns(create_from_options=Mock(return_value=mesh)), FaceLandmarkerOptions=option,
                    PoseLandmarker=ns(create_from_options=Mock(return_value=body)), PoseLandmarkerOptions=option,
                    RunningMode=ns(VIDEO="VIDEO"))
        mpt = ns(BaseOptions=option)
        intr = ns(width=20, height=20, fx=100., fy=100., ppx=10., ppy=10., model="test", coeffs=[0.] * 5)
        profile, pipe, rs = Mock(), Mock(), Mock()
        profile.get_device.return_value.first_depth_sensor.return_value.get_depth_scale.return_value = .001
        profile.get_device.return_value.as_playback.return_value.get_duration.return_value.total_seconds.return_value = 20.
        profile.get_stream.return_value.as_video_stream_profile.return_value.get_intrinsics.return_value = intr
        pipe.start.return_value = profile
        rs.pipeline.return_value = pipe
        rs.align.return_value.process.side_effect = lambda frames: frames
        def frame(ts, color_number, depth_number):
            fr = Mock()
            fr.get_timestamp.return_value = ts
            fr.get_color_frame.return_value.get_frame_number.return_value = color_number
            fr.get_depth_frame.return_value.get_frame_number.return_value = depth_number
            fr.get_color_frame.return_value.get_data.return_value = np.zeros((20, 20, 3), dtype=np.uint8)
            fr.get_depth_frame.return_value.get_data.return_value = np.full((20, 20), 1000, dtype=np.uint16)
            return fr
        def execute(provenance):
            pipe.try_wait_for_frames.side_effect = [
                (True, frame(2000., 101, 201)), (True, frame(12000., 102, 202)), (False, None)]
            real_import = builtins.__import__
            modules = {"mediapipe": ns(Image=option, ImageFormat=ns(SRGB="SRGB")),
                       "pyrealsense2": rs, "mediapipe.tasks": ns(python=mpt),
                       "mediapipe.tasks.python": ns(vision=vision)}
            def fake_import(name, *args, **kwargs):
                return modules[name] if name in modules else real_import(name, *args, **kwargs)
            with patch("builtins.__import__", side_effect=fake_import):
                return analysis.process_recording(path, paths, 1, provenance=provenance)
        with self.assertRaisesRegex(ValueError, "requires analysis provenance"):
            execute(None)
        _, info = analysis.start_analysis_run(path, self.args, "batch")
        analysis.record_model_artifacts(info, paths)
        first = execute(info)
        _, info2 = analysis.start_analysis_run(path, self.args, "batch")
        analysis.record_model_artifacts(info2, paths)
        second = execute(info2)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(first[0]), 60)
        for left, right in zip(first, second):
            self.assertNotEqual(left["analysis_run_id"], right["analysis_run_id"])
            left_without_run = dict(left); left_without_run.pop("analysis_run_id")
            right_without_run = dict(right); right_without_run.pop("analysis_run_id")
            self.assertEqual(left_without_run, right_without_run)
        with open(Path(analysis.OUT_DIR) / (Path(path).stem + "_frames.csv"), encoding="utf-8-sig") as f:
            self.assertEqual(tuple(csv.DictReader(f).fieldnames), analysis.FRAME_FIELDS)
        row = first[0]
        for field, expected in {"face_x": 8, "face_y": 6, "face_area_px": 64, "face_score": .95,
                                "z_face_m": 1., "face_size_cm2": 64., "oval_area_px": 100.,
                                "oval_size_cm2": 100., "ipd_px": 4., "ipd_cm": 4., "box_to_oval": .64,
                                "lsh_x": 5., "rsh_x": 15., "lsh_y": 16., "rsh_y": 16.,
                                "z_lsh_m": 1., "z_rsh_m": 1., "z_sh_m": 1.}.items():
            self.assertAlmostEqual(row[field], expected, msg=field)
        self.assertAlmostEqual(row["theta2_deg"], math.degrees(math.atan2(7, 10)))
        self.assertAlmostEqual(row["theta3_deg"], math.degrees(math.atan2(3, 10)))
        self.assertAlmostEqual(row["theta1_deg"], row["theta2_deg"] + row["theta3_deg"])
        self.assertEqual(row["frame_schema_version"], "frames-schema/1.0.0")
        self.assertEqual(row["recording_id"], info["recording_id"])
        self.assertEqual(row["analysis_run_id"], info["analysis_run_id"])
        self.assertEqual((row["frame_index"], row["color_frame_number"], row["depth_frame_number"]), (1, 101, 201))
        self.assertEqual(row["mediapipe_ts_ms"], 2000)
        self.assertIs(info["inference_performed"], True)
        self.assertTrue(all(m["used_in_this_run"] for m in info["models"]))
        self.assertEqual(info["playback_calibration"]["depth_scale_m"], .001)
        settings = info["processing_settings"]["tasks"]
        for role, detector in (("face", vision.FaceDetector), ("mesh", vision.FaceLandmarker),
                               ("pose", vision.PoseLandmarker)):
            actual = vars(detector.create_from_options.call_args.args[0])
            for key, value in actual.items():
                if key != "base_options":
                    self.assertEqual(settings[role][key], value)
        self.assertEqual(settings["face"]["min_detection_confidence"], .5)
        self.assertEqual(settings["face"]["running_mode"], "IMAGE")
        self.assertEqual(settings["mesh"]["running_mode"], "VIDEO")
        self.assertEqual(settings["mesh"]["num_faces"], 1)
        self.assertEqual(settings["pose"]["num_poses"], 1)


if __name__ == "__main__":
    unittest.main()
