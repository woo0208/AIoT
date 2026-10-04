"""Patch 4.5 structural tests: synthetic bytes, temporary files, no live network/hardware."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from test_analysis_provenance import load_analyzer
from test_frame_schema import canonical_row, FROZEN_FRAME_FIELDS


analysis = load_analyzer()
CANONICAL_LOCK_PATH = Path(__file__).with_name("mediapipe_model_lock.json")


class ModelArtifactLockTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.models, self.out = self.root / "models", self.root / "analysis"
        self.models.mkdir()
        self.lock_path = self.root / "mediapipe_model_lock.json"
        self.canonical = json.loads(CANONICAL_LOCK_PATH.read_text(encoding="utf-8"))
        self.lock = copy.deepcopy(self.canonical)
        self.bytes = {entry["role"]: b"synthetic Patch 4.5 " + entry["role"].encode()
                      for entry in self.lock["artifacts"]}
        for entry in self.lock["artifacts"]:
            entry["sha256"] = hashlib.sha256(self.bytes[entry["role"]]).hexdigest()
        self.write_lock(self.lock)
        for name, value in (("MODEL_DIR", self.models), ("OUT_DIR", self.out), ("MODEL_LOCK_PATH", self.lock_path)):
            self.stack.enter_context(patch.object(analysis, name, str(value)))
        self.stack.enter_context(patch.object(analysis, "analysis_environment", return_value={}))
        self.stack.enter_context(patch.object(analysis, "analysis_code", return_value={}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        # A test must opt into a local stub; accidental network is always a failure.
        self.download = self.stack.enter_context(patch.object(
            analysis.urllib.request, "urlretrieve", side_effect=AssertionError("live network forbidden")))
        self.args = types.SimpleNamespace(subjects=["P03"], step=1, from_csv=False, legacy_pilot=False)

    def write_lock(self, value):
        self.lock_path.write_text(json.dumps(value), encoding="utf-8")

    def entry(self, role="face"):
        return next(entry for entry in self.lock["artifacts"] if entry["role"] == role)

    def path(self, role="face"):
        return self.models / self.entry(role)["filename"]

    def install_existing(self):
        for role, data in self.bytes.items():
            self.path(role).write_bytes(data)

    def stub_download(self, url, destination):
        entry = next(entry for entry in self.lock["artifacts"] if entry["source_url"] == url)
        self.assertNotEqual(Path(destination), self.path(entry["role"]))
        self.assertEqual(Path(destination).parent, self.models)
        Path(destination).write_bytes(self.bytes[entry["role"]])
        return destination, None

    def assert_no_temporaries(self):
        self.assertEqual(list(self.models.glob(".model-*.tmp")), [])

    def assert_invalid(self, value, message):
        self.write_lock(value)
        with self.assertRaisesRegex(ValueError, message):
            analysis.ensure_models()
        self.download.assert_not_called()
        self.assertEqual(list(self.models.iterdir()), [])

    def raw_recording(self):
        identity = "P03_r1_20261004_120000_123456_" + "a" * 32
        raw = self.root / (identity + ".bag")
        raw.write_bytes(b"synthetic raw fixture")
        base = raw.with_suffix("")
        analysis.write_json(str(base) + "_camera.json", {
            "recording_id": identity, "record_file": raw.name, "dataset_role": "formal",
            "protocol_version": "capture-forward-face-v2.0.0",
        })
        Path(str(base) + "_markers.csv").write_text(
            "frame_timestamp_ms,phase,label,step\n0,hold,upright,1\n10000,end,end,\n", encoding="utf-8")
        return raw

    def fake_process(self, path, models, step, provenance=None, output_dir=None):
        for role in models:
            analysis.mark_model_used(provenance, role)
        row = canonical_row(recording_id=provenance["recording_id"], analysis_run_id=provenance["analysis_run_id"])
        analysis.write_frames_csv(Path(output_dir) / (Path(path).stem + "_frames.csv"), [row])
        return [row]

    def run_raw(self):
        raw = self.raw_recording()
        with patch.object(analysis, "process_recording", side_effect=self.fake_process), \
                patch.object(analysis, "plot_all", return_value=None):
            analysis.run_analysis([str(raw)], self.args)
        frame = self.out / (raw.stem + "_frames.csv")
        link = analysis.read_json(str(frame) + ".provenance.json")
        parent_path = frame.parent / link["analysis_manifest"]
        return frame, link, parent_path

    def test_tracked_manifest_exact_frozen_artifacts(self):
        expected = {
            "face": ("blaze_face_short_range.tflite",
                     "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
                     "1", "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f"),
            "mesh": ("face_landmarker.task",
                     "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
                     "1", "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
            "pose": ("pose_landmarker_full.task",
                     "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task?generation=1682642787774579",
                     "gcs-generation:1682642787774579", "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad"),
        }
        self.assertEqual(self.canonical["lock_schema_version"], "mediapipe-model-lock/1.0.0")
        self.assertEqual(len(self.canonical["artifacts"]), 3)
        self.assertEqual({entry["role"]: tuple(entry[key] for key in (
            "filename", "source_url", "version_identifier", "sha256")) for entry in self.canonical["artifacts"]}, expected)

    def test_existing_matching_artifacts_no_network(self):
        self.install_existing()
        paths = analysis.ensure_models()
        self.assertEqual(paths, {role: str(self.path(role)) for role in self.bytes})
        self.download.assert_not_called()
        self.assert_no_temporaries()

    def test_existing_mismatch_preserved_with_full_diagnostic(self):
        self.install_existing()
        self.path().write_bytes(b"changed artifact")
        before = {path.name: path.read_bytes() for path in self.models.iterdir()}
        with self.assertRaises(ValueError) as failure:
            analysis.ensure_models()
        for value in (str(self.path()), self.entry()["sha256"], hashlib.sha256(b"changed artifact").hexdigest()):
            self.assertIn(value, str(failure.exception))
        self.download.assert_not_called()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.models.iterdir()})

    def test_cached_mismatch_checked_before_missing_download(self):
        self.path("pose").write_bytes(b"bad pose")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            analysis.ensure_models()
        self.download.assert_not_called()

    def test_complete_file_hash_includes_bytes_beyond_first_chunk(self):
        self.install_existing()
        data = b"a" * (1024 * 1024) + b"locked tail"
        self.path().write_bytes(data)
        self.entry()["sha256"] = hashlib.sha256(data).hexdigest()
        self.write_lock(self.lock)
        analysis.ensure_models()
        self.path().write_bytes(data[:-1] + b"X")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            analysis.ensure_models()
        self.download.assert_not_called()

    def test_missing_artifacts_exact_source_verified_atomic_install(self):
        self.download.side_effect = self.stub_download
        original_link = os.link
        def verified_link(source, destination):
            role = next(role for role in self.bytes if self.path(role) == Path(destination))
            self.assertEqual(hashlib.sha256(Path(source).read_bytes()).hexdigest(), self.entry(role)["sha256"])
            self.assertFalse(Path(destination).exists())
            return original_link(source, destination)
        with patch.object(analysis.os, "link", side_effect=verified_link) as finalize:
            analysis.ensure_models()
        self.assertEqual([call.args[0] for call in self.download.call_args_list],
                         [entry["source_url"] for entry in self.lock["artifacts"]])
        self.assertEqual(finalize.call_count, 3)
        for role, data in self.bytes.items():
            self.assertEqual(self.path(role).read_bytes(), data)
        self.assert_no_temporaries()

    def test_downloaded_mismatch_not_installed_and_temp_cleaned(self):
        self.download.side_effect = lambda url, destination: Path(destination).write_bytes(b"wrong download")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            analysis.ensure_models()
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(list(self.models.iterdir()), [])

    def test_network_failure_leaves_no_incomplete_artifact(self):
        def fail(url, destination):
            Path(destination).write_bytes(b"partial")
            raise OSError("network interrupted")
        self.download.side_effect = fail
        with self.assertRaisesRegex(OSError, "network interrupted"):
            analysis.ensure_models()
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(list(self.models.iterdir()), [])

    def test_install_failure_leaves_no_final_or_temporary(self):
        self.download.side_effect = self.stub_download
        with patch.object(analysis.os, "link", side_effect=OSError("install failed")):
            with self.assertRaisesRegex(OSError, "install failed"):
                analysis.ensure_models()
        self.assertEqual(list(self.models.iterdir()), [])

    def test_destination_appearing_during_download_matching_preserved(self):
        self.install_existing()
        self.path().unlink()
        def download(url, destination):
            self.stub_download(url, destination)
            self.path().write_bytes(self.bytes["face"])
            os.utime(self.path(), ns=(123456700, 123456700))
        self.download.side_effect = download
        analysis.ensure_models()
        self.assertEqual(self.path().stat().st_mtime_ns, 123456700)
        self.assertEqual(self.path().read_bytes(), self.bytes["face"])
        self.assert_no_temporaries()

    def test_destination_appearing_during_download_mismatch_preserved(self):
        def download(url, destination):
            self.stub_download(url, destination)
            self.path().write_bytes(b"concurrent artifact")
        self.download.side_effect = download
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            analysis.ensure_models()
        self.assertEqual(self.path().read_bytes(), b"concurrent artifact")
        self.assertEqual(self.download.call_count, 1)
        self.assert_no_temporaries()

    def test_unreadable_existing_artifact_fails_without_download(self):
        self.path().mkdir()
        with self.assertRaisesRegex(OSError, "cannot completely hash"):
            analysis.ensure_models()
        self.download.assert_not_called()
        self.assertTrue(self.path().is_dir())

    def test_missing_manifest_raw_fails_before_provisioning_or_inference(self):
        self.lock_path.unlink()
        with patch.object(analysis, "ensure_models") as provision, \
                patch.object(analysis, "process_recording") as infer:
            with self.assertRaisesRegex(ValueError, "cannot load model lock"):
                analysis.run_analysis([str(self.raw_recording())], self.args)
        provision.assert_not_called()
        infer.assert_not_called()
        self.download.assert_not_called()
        manifest = analysis.read_json(next(self.out.glob("*/ar_*/analysis_manifest.json")))
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(manifest["inference_performed"])

    def test_malformed_json(self):
        for text in ("{", "", "{\"artifacts\": NaN}"):
            with self.subTest(text=text):
                self.lock_path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    analysis.ensure_models()
        self.download.assert_not_called()

    def test_duplicate_json_key_rejected(self):
        self.lock_path.write_text('{"lock_schema_version":"mediapipe-model-lock/1.0.0",'
                                  '"artifacts":[],"artifacts":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate model lock JSON key"):
            analysis.load_model_lock()

    def test_unsupported_schema_version(self):
        for version in ("mediapipe-model-lock/2.0.0", None, 1):
            with self.subTest(version=version):
                self.assert_invalid(dict(self.lock, lock_schema_version=version), "unsupported")

    def test_invalid_top_level_structure(self):
        for value in ([], None, "lock", {}, {"artifacts": []}, dict(self.lock, extra=True)):
            with self.subTest(value=value):
                self.assert_invalid(value, "top-level")

    def test_malformed_artifacts_collection(self):
        for value in ({}, None, "face", [None], ["face"]):
            with self.subTest(value=value):
                self.assert_invalid(dict(self.lock, artifacts=value), "artifacts collection|artifact fields")

    def test_missing_role(self):
        for index in range(3):
            value = copy.deepcopy(self.lock)
            value["artifacts"].pop(index)
            self.assert_invalid(value, "missing model lock roles")

    def test_duplicate_role(self):
        value = copy.deepcopy(self.lock)
        value["artifacts"].append(copy.deepcopy(value["artifacts"][0]))
        self.assert_invalid(value, "duplicate model lock role")

    def test_unknown_role(self):
        value = copy.deepcopy(self.lock)
        value["artifacts"][0]["role"] = "hands"
        self.assert_invalid(value, "unknown model lock role")

    def test_required_fields_missing_or_invalid_types(self):
        for field in self.entry():
            for replacement in ("missing", None, 1, [], ""):
                with self.subTest(field=field, replacement=replacement):
                    value = copy.deepcopy(self.lock)
                    if replacement == "missing":
                        del value["artifacts"][0][field]
                    else:
                        value["artifacts"][0][field] = replacement
                    self.assert_invalid(value, "artifact fields")

    def test_invalid_filename_contract(self):
        for filename in ("pose_landmarker_full.task", "../blaze_face_short_range.tflite", "other.tflite"):
            with self.subTest(filename=filename):
                value = copy.deepcopy(self.lock)
                value["artifacts"][0]["filename"] = filename
                self.assert_invalid(value, "filename")

    def test_invalid_sha256_representation(self):
        for digest in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n", "0x" + "a" * 64):
            with self.subTest(digest=digest):
                value = copy.deepcopy(self.lock)
                value["artifacts"][0]["sha256"] = digest
                self.assert_invalid(value, "canonical SHA-256")

    def test_invalid_source_url(self):
        source = self.entry()["source_url"]
        for url in ("not a URL", source.replace("https:", "http:"), source.replace("storage.googleapis.com", "mirror.example"),
                    source.replace("float16", "float32"), source.replace("blaze_face_short_range/", "other/"),
                    source + "#fragment", source + "?fallback=1", source.replace("/1/", "/../1/"),
                    " " + source, source + "\n", source.replace("https:", "HTTPS:"), source + "?", source + "#"):
            with self.subTest(url=url):
                value = copy.deepcopy(self.lock)
                value["artifacts"][0]["source_url"] = url
                self.assert_invalid(value, "source")

    def test_invalid_version_identifier(self):
        for index, versions in ((0, ("2", "01", "unknown", "gcs-generation:1")),
                                (2, ("1", "unknown", "gcs-generation:1682642787774580"))):
            for version in versions:
                with self.subTest(index=index, version=version):
                    value = copy.deepcopy(self.lock)
                    value["artifacts"][index]["version_identifier"] = version
                    self.assert_invalid(value, "source/version")

    def test_unqualified_latest_rejected_for_every_role(self):
        for index in range(3):
            value = copy.deepcopy(self.lock)
            entry = value["artifacts"][index]
            entry["source_url"] = entry["source_url"].replace("/1/", "/latest/").split("?")[0]
            self.assert_invalid(value, "source/version")

    def test_invalid_generation_query_rejected(self):
        for query in ("generation=", "generation=-1", "generation=01", "generation=1&generation=2",
                      "generation=1682642787774579&other=1", "Generation=1682642787774579"):
            with self.subTest(query=query):
                value = copy.deepcopy(self.lock)
                value["artifacts"][2]["source_url"] = self.entry("pose")["source_url"].split("?")[0] + "?" + query
                self.assert_invalid(value, "source/version")

    def test_frozen_generation_qualified_pose_accepted(self):
        self.write_lock(self.canonical)
        loaded = analysis.load_model_lock()
        self.assertEqual(loaded["pose"], self.canonical["artifacts"][2])
        self.download.assert_not_called()

    def test_raw_completed_provenance_actual_equals_lock_hash_and_source_version(self):
        self.download.side_effect = self.stub_download
        _, _, parent_path = self.run_raw()
        info = analysis.read_json(parent_path)
        self.assertEqual(info["status"], "completed")
        self.assertEqual(info["schema_version"], "analysis-provenance/1.0.0")
        self.assertTrue(info["inference_performed"])
        for model in info["models"]:
            entry = self.entry(model["role"])
            self.assertTrue(model["used_in_this_run"])
            self.assertEqual(model["sha256"], hashlib.sha256(Path(model["path"]).read_bytes()).hexdigest())
            self.assertEqual(model["sha256"], entry["sha256"])
            self.assertEqual(model["source_url"], entry["source_url"])
            self.assertEqual(model["version_identifier"], entry["version_identifier"])
            self.assertEqual(model["source_url_kind"], "configured_download_url")
            self.assertEqual(model["hash_status"], "complete")
            self.assertNotIn("expected_sha256", model)

    def test_provenance_rechecks_artifact_changed_after_provisioning(self):
        self.install_existing()
        paths = analysis.ensure_models()
        self.path().write_bytes(b"changed after provisioning")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            analysis.record_model_artifacts({"models": []}, paths)
        self.download.assert_not_called()

    def test_from_csv_missing_current_lock_models_preserves_historical_provenance(self):
        self.install_existing()
        frame, link, parent_path = self.run_raw()
        parent = analysis.read_json(parent_path)
        for model in parent["models"]:
            model["source_url"] = model["source_url"].replace("/1/", "/latest/").split("?")[0]
            model["version_identifier"] = None
            model["sha256"] = None
            model["hash_status"] = "unavailable"
        analysis.write_json(parent_path, parent)
        historical_bytes = parent_path.read_bytes()
        link["analysis_manifest_sha256"] = hashlib.sha256(historical_bytes).hexdigest()
        analysis.write_json(str(frame) + ".provenance.json", link)
        for path in self.models.iterdir():
            path.unlink()
        self.lock_path.unlink()
        self.args.from_csv = True
        with patch.object(analysis, "load_model_lock", side_effect=AssertionError("CSV lock forbidden")), \
                patch.object(analysis, "ensure_models", side_effect=AssertionError("CSV provisioning forbidden")), \
                patch.object(analysis, "verify_model_artifact", side_effect=AssertionError("CSV verification forbidden")), \
                patch.object(analysis, "process_recording", side_effect=AssertionError("CSV inference forbidden")), \
                patch.object(analysis, "plot_all", return_value=None):
            analysis.run_analysis([str(frame)], self.args)
        manifests = [analysis.read_json(path) for path in self.out.glob("*/ar_*/analysis_manifest.json")]
        info = next(item for item in manifests if item["analysis_mode"] == "summarize_existing_frames")
        self.assertEqual(info["status"], "completed")
        self.assertFalse(info["inference_performed"])
        self.assertEqual(info["parent_analysis_run_id"], parent["analysis_run_id"])
        self.assertEqual(info["models"], [dict(model, used_in_this_run=False,
                                             source_analysis_run_id=parent["analysis_run_id"]) for model in parent["models"]])
        self.assertEqual(parent_path.read_bytes(), historical_bytes)
        self.download.assert_not_called()

    def test_patch4_exact_schema_regression_guard(self):
        self.assertEqual(analysis.FRAME_SCHEMA_VERSION, "frames-schema/1.0.0")
        self.assertEqual(len(analysis.FRAME_FIELDS), 60)
        self.assertEqual(analysis.FRAME_FIELDS, FROZEN_FRAME_FIELDS)


if __name__ == "__main__":
    unittest.main()
