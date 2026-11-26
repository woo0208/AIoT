"""PROV-008 synthetic integrity tests; no research results, hardware or network."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import integrity_check as checker
import rf_experiment as rf
import selection_manifest as selection
import test_patch6_selection as fixtures


class Patch7Tests(unittest.TestCase):
    # Reuse Patch 6's synthetic source/event factories and Patch 5's frames
    # helper transitively. Extend only the fields those consumer-only fixtures
    # intentionally omit but a whole-repository audit must inspect.
    json_file = fixtures.Patch6Tests.json_file
    evidence = fixtures.Patch6Tests.evidence
    relation = fixtures.Patch6Tests.relation
    build = fixtures.Patch6Tests.build

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.out = self.root / "analysis"
        self.ledger = self.root / selection.LEDGER_PATH
        self.lock = self.root / "mediapipe_model_lock.json"
        shutil.copyfile(Path(__file__).with_name("mediapipe_model_lock.json"), self.lock)

    def source(self, rid="P01_r1_original", **kwargs):
        event = fixtures.Patch6Tests.source(self, rid=rid, **kwargs)
        camera = self.root / event["evidence"][0]["path"]
        value = json.loads(camera.read_bytes())
        raw = camera.parent / (rid + ".bag")
        raw.write_bytes(b"synthetic raw " + rid.encode())
        markers = camera.parent / (rid + "_markers.csv")
        markers.write_text("recording_id,step\n" + rid + ",1\n", encoding="utf-8")
        value.update(record_file=raw.name, sidecar_files={k: f"{rid}_{k}.{ext}" for k, ext in
                     (("camera", "json"), ("markers", "csv"), ("samples", "csv"), ("quality", "json"))})
        self.json_file(camera, value)
        selected = event["decision"]["analysis_selection"]
        if selected:
            owner = self.root / selected["analysis_manifest_path"]
            manifest = json.loads(owner.read_bytes())
            batch_id = "ar_batch_" + rid + "_" + manifest["analysis_run_id"]
            manifest.update(analysis_batch_id=batch_id, parent_analysis_run_id=None,
                            inputs={"recording": rf.file_identity(raw), "capture_metadata": rf.file_identity(camera),
                                    "markers": rf.file_identity(markers)})
            self.json_file(owner, manifest)
            self.json_file(self.out / "batches" / batch_id / "analysis_batch.json",
                           dict(analysis_batch_id=batch_id, analysis_run_ids=[manifest["analysis_run_id"]],
                                outputs=[], run_manifests=[str(owner)]))
            flat_link = Path(str(self.out / (rid + "_frames.csv")) + ".provenance.json")
            link = json.loads(flat_link.read_bytes())
            link["analysis_manifest_sha256"] = rf.file_identity(owner)["sha256"]
            self.json_file(flat_link, link)
            selected["analysis_manifest_sha256"] = link["analysis_manifest_sha256"]
        for item in event["evidence"]:
            item["sha256"] = rf.file_identity(self.root / item["path"])["sha256"]
        return event

    def append(self, event):
        selection.append_event(event, self.root)

    def owner(self, event):
        return self.root / event["decision"]["analysis_selection"]["analysis_manifest_path"]

    def frames(self, event):
        return self.root / event["decision"]["analysis_selection"]["frames_path"]

    def mutate(self, path, change):
        value = json.loads(path.read_bytes())
        change(value)
        self.json_file(path, value)
        return value

    def refresh_owner_link(self, event):
        owner = self.owner(event)
        link = Path(str(self.out / self.frames(event).name) + ".provenance.json")
        self.mutate(link, lambda d: d.update(analysis_manifest_sha256=rf.file_identity(owner)["sha256"]))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def audit(self):
        return checker.audit_repository(self.root)

    def assert_clean(self):
        result = self.audit()
        self.assertEqual(result.counts["ERROR"], 0, result.findings)
        self.assertEqual(result.exit_code, 0)
        return result

    def assert_error(self, code=None):
        result = self.audit()
        errors = [f for f in result.findings if f.severity == "ERROR"]
        self.assertTrue(errors, result.findings)
        if code:
            self.assertIn(code, [f.code for f in errors], result.findings)
        self.assertEqual(result.exit_code, 1)
        return result

    def rf_run(self, event=None, dataset=None, status="completed", external=None):
        directory = self.root / "results/er_synthetic"
        directory.mkdir(parents=True)
        manifest = dict(schema_version="rf-experiment-provenance/1.0.0", experiment_run_id=directory.name,
                        status=status, inputs=dict(paper=None, multiposture=None, ours=[]),
                        dataset_manifest=dict(dataset_manifest_id=None, path=None, sha256=None),
                        sample_lineage=dict(schema_version=rf.LINEAGE_SCHEMA, path="sample_lineage.jsonl",
                                            sha256=None, row_count=0), outputs=[])
        rows = []
        if event is not None:
            entry = rf.canonical_input(self.frames(event), self.out)
            manifest["inputs"]["ours"] = [entry]
            source = dict(source_kind="canonical_frames", step=1, label="upright", calibration_reference_step=1,
                          **{k: entry[k] for k in ("recording_id", "analysis_run_id", "subject", "round",
                                                  "frames_path", "frames_sha256")})
            rows += rf.lineage_rows([source], directory.name, "ours_external", "all")
        if external is not None:
            artifact = dict(source_dataset_id="paper_dataset", **rf.file_identity(external))
            manifest["inputs"]["paper"] = artifact
            rows += rf.lineage_rows([rf.external_source(artifact, 2, "synthetic", 0)], directory.name, "paper_loso", "all")
        if dataset is not None:
            manifest["inputs"]["ours"], manifest["dataset_manifest"] = selection.resolve_dataset_manifest(dataset, self.root)
        if status == "completed":
            manifest["sample_lineage"] = rf.write_sample_lineage(directory, rows)
            with (directory / "rf_results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rf.RESULT_LINEAGE_FIELDS)
                writer.writeheader()
                writer.writerow(dict(zip(rf.RESULT_LINEAGE_FIELDS, (directory.name,
                    manifest["dataset_manifest"]["sha256"], "sample_lineage.jsonl", manifest["sample_lineage"]["sha256"]))))
            (directory / "rf_results.txt").write_bytes(b"synthetic structural result; no metrics")
            manifest["outputs"] = [dict(kind=n, **rf.file_identity(directory / n)) for n in ("rf_results.csv", "rf_results.txt")]
        path = self.json_file(directory / "experiment_manifest.json", manifest)
        return path

    def mutate_lineage(self, manifest_path, change):
        path = manifest_path.parent / "sample_lineage.jsonl"
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        change(rows)
        path.write_bytes(b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
                                 for r in rows))
        self.mutate(manifest_path, lambda m: m["sample_lineage"].update(sha256=rf.file_identity(path)["sha256"], row_count=len(rows)))

    def test_empty_generated_namespaces_and_missing_model_cache(self):
        result = self.assert_clean()
        self.assertEqual(result.counts, dict(ERROR=0, WARNING=0, INFO=3))

    def test_valid_capture_unselected_no_samples(self):
        self.source(include=False, quality=True)
        self.assert_clean()

    def test_failed_reserved_capture_optional_companions(self):
        event = self.source(include=False)
        camera = self.root / event["evidence"][0]["path"]
        self.mutate(camera, lambda m: m.update(record_file=None))
        (camera.parent / (event["recording_id"] + ".bag")).unlink()
        (camera.parent / (event["recording_id"] + "_markers.csv")).unlink()
        self.assertGreater(self.assert_clean().counts["WARNING"], 0)

    def test_valid_analysis_batch_unselected_and_unused_frames(self):
        self.source()
        self.assert_clean()

    def test_valid_selection_dataset_and_completed_rf(self):
        event = self.source(quality=True)
        self.append(event)
        self.rf_run(event, self.build(event))
        self.assert_clean()

    def test_historical_manifest_after_supersession(self):
        event = self.source()
        self.append(event)
        dataset = self.build(event)
        newer = deepcopy(event)
        newer.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=event["selection_event_id"])
        self.append(newer)
        self.rf_run(event, dataset)
        self.assert_clean()

    def test_failed_and_running_analysis_without_future_outputs(self):
        for status in ("failed", "running"):
            event = self.source(rid="P01_r1_" + status, run="ar_" + status)
            frames = self.frames(event)
            self.mutate(self.owner(event), lambda m: m.update(status=status, outputs=[]))
            frames.unlink()
            (self.out / frames.name).unlink()
            Path(str(self.out / frames.name) + ".provenance.json").unlink()
        self.assert_clean()

    def test_failed_and_running_rf_without_future_outputs(self):
        path = self.rf_run(status="failed")
        self.assert_clean()
        self.mutate(path, lambda m: m.update(status="running"))
        self.assert_clean()

    def test_absent_compatibility_copies_not_required(self):
        event = self.source()
        (self.out / self.frames(event).name).unlink()
        Path(str(self.out / self.frames(event).name) + ".provenance.json").unlink()
        self.assert_clean()

    def test_legacy_capture_companion_warns_without_identity_inference(self):
        self.json_file(self.root / "data/old_camera.json", dict(subject="P01", round=1))
        (self.root / "data/old.bag").write_bytes(b"synthetic legacy raw")
        self.assert_clean()

    def test_analysis_input_hash_mismatch(self):
        event = self.source()
        (self.root / "data" / (event["recording_id"] + ".bag")).write_bytes(b"changed")
        self.assert_error("HASH_MISMATCH")

    def test_analysis_output_hash_mismatch(self):
        event = self.source()
        with self.frames(event).open("ab") as stream:
            stream.write(b"\n")
        self.assert_error("HASH_MISMATCH")

    def test_analysis_recorded_output_missing(self):
        event = self.source()
        self.frames(event).unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_capture_declared_raw_missing(self):
        event = self.source(include=False)
        (self.root / "data" / (event["recording_id"] + ".bag")).unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_capture_sidecar_identity_mismatch(self):
        event = self.source(include=False, quality=True)
        self.mutate(self.root / "data" / (event["recording_id"] + "_quality.json"), lambda m: m.update(recording_id="other"))
        self.assert_error("IDENTITY_MISMATCH")

    def test_capture_csv_every_row_identity(self):
        event = self.source(include=False)
        path = self.root / "data" / (event["recording_id"] + "_samples.csv")
        path.write_text("recording_id\n" + event["recording_id"] + "\nother\n", encoding="utf-8")
        self.assert_error("IDENTITY_MISMATCH")

    def test_capture_semantic_fields(self):
        event = self.source(include=False)
        path = self.root / event["evidence"][0]["path"]
        original = path.read_bytes()
        for field, value in (("schema_version", "wrong"), ("subject", "unsafe/name"), ("round", "01"),
                             ("dataset_role", "unknown"), ("protocol_version", None), ("sidecar_files", {}),
                             ("record_file", "other.bag"), ("recording_id", "other")):
            with self.subTest(field=field):
                path.write_bytes(original)
                self.mutate(path, lambda m: m.update({field: value}))
                self.assert_error()

    def test_malformed_capture_json(self):
        event = self.source(include=False)
        (self.root / event["evidence"][0]["path"]).write_bytes(b'{"recording_id":')
        self.assert_error("TORN_AUTHORITY")

    def test_analysis_directory_identity_mismatch(self):
        event = self.source()
        for field in ("recording_id", "analysis_run_id"):
            with self.subTest(field=field):
                path = self.owner(event)
                original = path.read_bytes()
                self.mutate(path, lambda m: m.update({field: "wrong"}))
                self.assert_error("IDENTITY_MISMATCH")
                path.write_bytes(original)

    def test_analysis_schema_and_status(self):
        event = self.source()
        path = self.owner(event)
        original = path.read_bytes()
        for field, value in (("schema_version", "wrong"), ("status", "stale"), ("analysis_mode", "guess"),
                             ("inputs", []), ("outputs", {}), ("analysis_batch_id", None)):
            with self.subTest(field=field):
                path.write_bytes(original)
                self.mutate(path, lambda m: m.update({field: value}))
                self.assert_error("SCHEMA_INVALID")

    def test_complete_analysis_hash_missing(self):
        event = self.source()
        self.mutate(self.owner(event), lambda m: m["inputs"]["recording"].update(hash_status="complete", sha256=None))
        self.assert_error("SCHEMA_INVALID")

    def test_canonical_frames_header_corruption_with_rehashed_owner(self):
        event = self.source()
        path = self.frames(event)
        path.write_bytes(path.read_bytes().replace(b"face_x", b"wrong_x", 1))
        self.mutate(self.owner(event), lambda m: m["outputs"][0].update(**rf.file_identity(path)))
        self.assert_error("SCHEMA_INVALID")

    def test_frames_row_owner_mismatch_with_rehashed_owner(self):
        event = self.source()
        path = self.frames(event)
        path.write_bytes(path.read_bytes().replace(b"ar_one", b"ar_other"))
        self.mutate(self.owner(event), lambda m: m["outputs"][0].update(**rf.file_identity(path)))
        self.assert_error("IDENTITY_MISMATCH")

    def test_frames_field_serialization_reuses_patch4_reader(self):
        event = self.source()
        path = self.frames(event)
        path.write_bytes(path.read_bytes().replace(b"bbox_roi", b"invented"))
        self.mutate(self.owner(event), lambda m: m["outputs"][0].update(**rf.file_identity(path)))
        self.assert_error("SCHEMA_INVALID")

    def test_raw_identity_fork(self):
        a, b = self.source(), self.source(rid="P01_r1_second")
        source = json.loads(self.owner(a).read_bytes())["inputs"]["recording"]
        self.mutate(self.owner(b), lambda m: m["inputs"].update(recording=source))
        self.assert_error("IDENTITY_MISMATCH")

    def test_same_recording_identity_different_raw_bytes(self):
        event = self.source()
        other = self.source(run="ar_second")
        raw = self.root / "data/alternate.bag"
        raw.write_bytes(b"different synthetic recording")
        self.mutate(self.owner(other), lambda m: m["inputs"].update(recording=rf.file_identity(raw)))
        self.assert_error("IDENTITY_MISMATCH")

    def test_batch_run_ownership_mismatch(self):
        event = self.source()
        self.mutate(self.owner(event), lambda m: m.update(analysis_batch_id="ar_other"))
        self.assert_error("OWNER_MISMATCH")

    def test_batch_contributors_mismatch(self):
        self.source()
        path = next((self.out / "batches").glob("*/analysis_batch.json"))
        self.mutate(path, lambda m: m.update(analysis_run_ids=["ar_other"]))
        self.assert_error("OWNER_MISMATCH")

    def test_false_flat_provenance_owner(self):
        event = self.source()
        path = Path(str(self.out / self.frames(event).name) + ".provenance.json")
        self.mutate(path, lambda m: m.update(analysis_run_id="ar_false"))
        self.assert_error("OWNER_MISMATCH")

    def test_torn_selection_tail_read_only(self):
        self.append(self.source())
        with self.ledger.open("ab") as stream:
            stream.write(b'{"torn":')
        before = self.snapshot()
        self.assert_error("TORN_AUTHORITY")
        self.assertEqual(before, self.snapshot())

    def test_selection_serialization_violation(self):
        event = self.source()
        self.append(event)
        self.ledger.write_bytes(selection.event_bytes(event).replace(b"\n", b"\r\n"))
        self.assert_error("SERIALIZATION_INVALID")

    def test_selection_graph_unlinked_second_decision(self):
        event = self.source()
        self.append(event)
        second = dict(event, selection_event_id=selection.new_event_id())
        with self.ledger.open("ab") as stream:
            stream.write(selection.event_bytes(second))
        self.assert_error("GRAPH_INVALID")

    def test_recapture_cycle(self):
        a, b = self.source(include=False), self.source(rid="P01_r1_retake", include=False)
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_bytes(selection.event_bytes(self.relation(a, b)) + selection.event_bytes(self.relation(b, a)))
        self.assert_error("GRAPH_INVALID")

    def test_evidence_pinned_hash_mismatch(self):
        event = self.source(include=False, quality=True)
        self.append(event)
        self.mutate(self.root / event["evidence"][-1]["path"], lambda m: m.update(verdict="retake"))
        self.assert_error("HASH_MISMATCH")

    def test_evidence_quality_identity_and_object_minimum(self):
        event = self.source(include=False, quality=True)
        item = event["evidence"][-1]
        path = self.root / item["path"]
        for value in ({"verdict": "ok"}, {"recording_id": "wrong"}, []):
            with self.subTest(value=value):
                self.json_file(path, value)
                item["sha256"] = rf.file_identity(path)["sha256"]
                self.ledger.parent.mkdir(parents=True, exist_ok=True)
                self.ledger.write_bytes(selection.event_bytes(event))
                self.assert_error()

    def test_deep_capture_evidence_schema_even_when_patch6_accepts(self):
        event = self.source(include=False)
        camera = self.root / event["evidence"][0]["path"]
        self.mutate(camera, lambda m: m.update(schema_version="wrong"))
        event["evidence"][0]["sha256"] = rf.file_identity(camera)["sha256"]
        self.append(event)  # Patch 6 M-2 gap: pinned identity alone accepts this.
        self.assert_error("SCHEMA_INVALID")

    def test_quality_verdict_and_other_evidence_not_scientific_policy(self):
        event = self.source(include=False, quality=True, verdict="arbitrary-future-verdict")
        path = self.root / "data/arbitrary.bin"
        path.write_bytes(b"not JSON; no semantic contract for other")
        event["evidence"].append(self.evidence(path, "other", event["recording_id"]))
        self.append(event)
        self.assert_clean()

    def test_other_evidence_escape_rejected(self):
        event = self.source(include=False)
        event["evidence"].append(dict(kind="other", recording_id=event["recording_id"], path="../outside", sha256="a" * 64))
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_bytes(selection.event_bytes(event))
        self.assert_error()

    def test_partial_dataset_manifest_final_filename(self):
        path = self.root / "manifests/datasets/dm_partial.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{"schema_version":')
        before = self.snapshot()
        self.assert_error("TORN_AUTHORITY")
        self.assertEqual(before, self.snapshot())

    def test_dataset_path_identity_and_event_sha(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = path.read_bytes()
        for change in (lambda m: m.update(dataset_manifest_id=selection.new_dataset_manifest_id()),
                       lambda m: m["entries"][0].update(selection_event_sha256="a" * 64),
                       lambda m: m["entries"][0].update(selection_event_id=selection.new_event_id())):
            with self.subTest(change=change):
                value = json.loads(original)
                change(value)
                path.write_bytes(selection.manifest_bytes(value))
                self.assert_error()

    def test_dataset_selected_analysis_missing(self):
        event = self.source()
        self.append(event)
        self.build(event)
        self.owner(event).unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_dataset_without_selection_ledger(self):
        event = self.source()
        self.append(event)
        self.build(event)
        self.ledger.unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_rf_directory_manifest_identity(self):
        path = self.rf_run()
        self.mutate(path, lambda m: m.update(experiment_run_id="er_wrong"))
        self.assert_error("IDENTITY_MISMATCH")

    def test_rf_canonical_input_hash_mismatch(self):
        path = self.rf_run(self.source())
        self.mutate(path, lambda m: m["inputs"]["ours"][0].update(frames_sha256="a" * 64))
        self.assert_error("HASH_MISMATCH")

    def test_sample_lineage_hash_mismatch(self):
        path = self.rf_run(self.source())
        with (path.parent / "sample_lineage.jsonl").open("ab") as stream:
            stream.write(b"\n")
        self.assert_error("HASH_MISMATCH")

    def test_sample_lineage_semantic_mutations_with_rehashed_reference(self):
        path = self.rf_run(self.source())
        lineage = path.parent / "sample_lineage.jsonl"
        original = lineage.read_bytes()
        for key, value in (("experiment_run_id", "er_other"), ("recording_id", "other"),
                           ("analysis_run_id", "ar_other"), ("frames_sha256", "a" * 64),
                           ("sample_index", 3), ("dataset_track", "paper_loso"),
                           ("feature_mode", "invented"), ("source_kind", "other"),
                           ("reference_recording_id", "wrong"), ("calibration_reference_step", 999),
                           ("source_file_path", "/wrong"), ("step", 999)):
            with self.subTest(key=key):
                lineage.write_bytes(original)
                self.mutate_lineage(path, lambda rows: rows[0].update({key: value}))
                self.assert_error()

    def test_sample_lineage_duplicate_sample_and_source_keys(self):
        path = self.rf_run(self.source())
        self.mutate_lineage(path, lambda rows: rows.append(dict(rows[0], sample_index=1)))
        self.assert_error("GRAPH_INVALID")

    def test_sample_lineage_noncanonical_serialization(self):
        path = self.rf_run(self.source())
        lineage = path.parent / "sample_lineage.jsonl"
        lineage.write_bytes(lineage.read_bytes().replace(b"\n", b"\r\n"))
        self.mutate(path, lambda m: m["sample_lineage"].update(sha256=rf.file_identity(lineage)["sha256"]))
        self.assert_error("SERIALIZATION_INVALID")

    def test_completed_rf_required_output_missing(self):
        path = self.rf_run()
        for name in ("sample_lineage.jsonl", "rf_results.csv", "rf_results.txt"):
            with self.subTest(name=name):
                target = path.parent / name
                original = target.read_bytes()
                target.unlink()
                self.assert_error("MISSING_ARTIFACT")
                target.write_bytes(original)

    def test_completed_rf_output_hash_mismatch(self):
        path = self.rf_run()
        (path.parent / "rf_results.txt").write_bytes(b"changed")
        self.assert_error("HASH_MISMATCH")

    def test_rf_output_size_mismatch(self):
        path = self.rf_run()
        self.mutate(path, lambda m: m["outputs"][0].update(size_bytes=0))
        self.assert_error("SCHEMA_INVALID")

    def test_rf_result_lineage_fields(self):
        path = self.rf_run()
        result = path.parent / "rf_results.csv"
        result.write_bytes(result.read_bytes().replace(b"er_synthetic", b"er_other"))
        self.mutate(path, lambda m: m["outputs"][0].update(**rf.file_identity(result)))
        self.assert_error("IDENTITY_MISMATCH")

    def test_manifest_driven_rf_source_mismatch(self):
        event = self.source()
        self.append(event)
        dataset = self.build(event)
        path = self.rf_run(event, dataset)
        other = self.source(rid="P01_r1_other")
        self.mutate(path, lambda m: m["inputs"].update(ours=[rf.canonical_input(self.frames(other), self.out)]))
        self.assert_error("OWNER_MISMATCH")

    def test_structural_orphan_analysis_frames(self):
        event = self.source()
        self.owner(event).unlink()
        self.assert_error("STRUCTURAL_ORPHAN")

    def test_frames_without_owner_output_binding(self):
        event = self.source()
        self.mutate(self.owner(event), lambda m: m.update(outputs=[]))
        self.assert_error("STRUCTURAL_ORPHAN")

    def test_structural_orphan_rf_lineage(self):
        path = self.rf_run()
        path.unlink()
        self.assert_error("STRUCTURAL_ORPHAN")

    def test_empty_and_temporary_only_run_directories(self):
        for name in ("analysis/rid/ar_empty", "analysis/batches/ar_empty", "results/er_empty"):
            directory = self.root / name
            directory.mkdir(parents=True)
            (directory / ".manifest-test.tmp").write_bytes(b"unfinished")
        result = self.assert_clean()
        self.assertEqual(result.counts["WARNING"], 6)

    def test_recognized_temp_residue_arbitrary_tmp_ignored(self):
        directory = self.root / "models"
        directory.mkdir()
        (directory / ".model-test.tmp").write_bytes(b"partial")
        (self.root / "user.tmp").write_bytes(b"unrelated")
        result = self.assert_clean()
        self.assertEqual([f.code for f in result.findings if f.severity == "WARNING"], ["TEMP_RESIDUE"])

    def test_external_accessible_hash_checked_then_inaccessible_warns(self):
        with tempfile.TemporaryDirectory() as outside:
            source = Path(outside) / "synthetic.xlsx"
            source.write_bytes(b"synthetic external bytes")
            self.rf_run(external=source)
            self.assert_clean()
            source.write_bytes(b"tampered")
            self.assert_error("HASH_MISMATCH")
            source.unlink()
            result = self.assert_clean()
            self.assertIn("EXTERNAL_UNVERIFIABLE", [f.code for f in result.findings])

    def test_repository_owned_absolute_missing_is_error(self):
        source = self.root / "synthetic.xlsx"
        source.write_bytes(b"synthetic repository-owned input")
        self.rf_run(external=source)
        source.unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_external_lineage_source_mismatch(self):
        source = self.root / "synthetic.xlsx"
        source.write_bytes(b"synthetic external input")
        path = self.rf_run(external=source)
        self.mutate_lineage(path, lambda rows: rows[0].update(source_file_sha256="a" * 64))
        self.assert_error("OWNER_MISMATCH")

    def test_local_model_wrong_hash_no_download(self):
        entry = json.loads(self.lock.read_bytes())["artifacts"][0]
        path = self.root / "models" / entry["filename"]
        path.parent.mkdir()
        path.write_bytes(b"synthetic wrong model")
        with patch.object(checker.analysis, "provision_model_artifact", side_effect=AssertionError("must not provision")):
            self.assert_error("HASH_MISMATCH")

    def test_model_lock_invalid(self):
        self.mutate(self.lock, lambda m: m.update(lock_schema_version="wrong"))
        self.assert_error("SCHEMA_INVALID")

    def test_deterministic_order_and_counts(self):
        self.source(include=False)
        path = self.rf_run(status="failed")
        self.mutate(path, lambda m: m.update(experiment_run_id="wrong"))
        first, second = self.audit(), self.audit()
        self.assertEqual(first, second)
        self.assertEqual(sum(first.counts.values()), len(first.findings))
        self.assertEqual(list(first.findings), sorted(first.findings, key=lambda f:
                         (checker.SEVERITIES.index(f.severity), f.code, f.artifact, f.reason)))

    def test_read_only_full_authority_graph_no_network_or_hardware(self):
        event = self.source(quality=True)
        self.append(event)
        self.rf_run(event, self.build(event))
        before = self.snapshot()
        with patch.object(checker.analysis, "ensure_models", side_effect=AssertionError("no provisioning")), \
                patch.object(checker.analysis.urllib.request, "urlopen", side_effect=AssertionError("no network")), \
                patch.object(checker.analysis.urllib.request, "urlretrieve", side_effect=AssertionError("no network")), \
                patch.object(rf, "execute_experiment", side_effect=AssertionError("no experiment")), \
                patch.object(selection, "append_event", side_effect=AssertionError("no selection")):
            self.assert_clean()
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("pyrealsense2", sys.modules)

    def test_managed_path_set_change(self):
        original = checker.managed_inventory
        count = 0
        def inventory(root):
            nonlocal count
            count += 1
            if count == 2:
                (root / "results").mkdir()
                (root / "results/new.txt").write_bytes(b"concurrent synthetic writer")
            return original(root)
        with patch.object(checker, "managed_inventory", side_effect=inventory):
            self.assert_error("REPOSITORY_CHANGED_DURING_CHECK")

    def test_cli_exit_zero_one_two_and_internal_failure(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(checker.main(["--repo-root", str(self.root)]), 0)
            self.lock.write_bytes(b"{")
            self.assertEqual(checker.main(["--repo-root", str(self.root)]), 1)
            self.assertEqual(checker.main(["--repo-root", str(self.root / "missing")]), 2)
            with patch.object(checker, "audit_repository", side_effect=RuntimeError("checker bug")):
                self.assertEqual(checker.main(["--repo-root", str(self.root)]), 2)
        self.assertIn("ERROR=0 WARNING=0 INFO=3 PASS", out.getvalue())
        self.assertIn("CHECKER_FAILURE", err.getvalue())

    def test_cli_warning_only_no_git_or_hardware(self):
        self.source(include=False)
        directory = self.root / "results/er_empty"
        directory.mkdir(parents=True)
        result = subprocess.run([sys.executable, "-B", str(Path(checker.__file__)), "--repo-root", str(self.root)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PASS", result.stdout)
        self.assertIn("WARNING=1", result.stdout)

    @contextmanager
    def actual_analysis_producer(self, *, legacy=False):
        """Real producer lifecycle with synthetic extraction and local model bytes."""
        if legacy:
            raw = self.root / "data/P01_r1_20260901_120000.bag"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"synthetic legacy raw")
            self.json_file(raw.with_name(raw.stem + "_camera.json"), dict(subject="P01", round=1))
            raw.with_name(raw.stem + "_markers.csv").write_text(
                "frame_timestamp_ms,phase,label,step\n0,hold,upright,1\n", encoding="utf-8")
        else:
            event = self.source(include=False)
            raw = self.root / "data" / (event["recording_id"] + ".bag")
        module = checker.analysis
        args = types.SimpleNamespace(from_csv=False, legacy_pilot=legacy, subjects=["P01"], step=1)
        lock = json.loads(self.lock.read_bytes())
        models = {}
        for entry in lock["artifacts"]:
            path = self.root / "models" / entry["filename"]
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"synthetic model " + entry["role"].encode())
            entry["sha256"] = rf.file_identity(path)["sha256"]
            models[entry["role"]] = str(path)
        self.json_file(self.lock, lock)
        def extract(path, models, step, provenance, output_dir):
            row = dict(subject="P01", round="1", step=1, label="upright", frame_index=1,
                       recording_id=provenance["recording_id"], analysis_run_id=provenance["analysis_run_id"],
                       frame_schema_version=module.FRAME_SCHEMA_VERSION,
                       face_depth_source="missing", shoulder_depth_source="missing")
            module.write_frames_csv(Path(output_dir) / (Path(path).stem + "_frames.csv"), [row])
            return [row]
        with patch.object(module, "OUT_DIR", str(self.out)), patch.object(module, "MODEL_LOCK_PATH", str(self.lock)), \
                patch.object(module, "ensure_models", return_value=models), \
                patch.object(module, "process_recording", side_effect=extract), \
                patch.object(module, "analysis_code", return_value={}), \
                patch.object(module, "analysis_environment", return_value={}), \
                patch.object(module, "plot_all", return_value=None), redirect_stdout(io.StringIO()):
            yield module, raw, args

    def test_actual_analysis_producer_and_linked_csv_run(self):
        with self.actual_analysis_producer() as (module, raw, args):
            module.run_analysis([str(raw)], args)
            self.assert_clean()
            args.from_csv = True
            module.run_analysis([str(self.out / (raw.stem + "_frames.csv"))], args)
            self.assert_clean()

    def failed_analysis_with_frames(self):
        with self.actual_analysis_producer() as (module, raw, args):
            # Failure after frames are recorded, before any shared output exists.
            with patch.object(module, "summarize", side_effect=RuntimeError("synthetic summary failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic summary failure"):
                    module.run_analysis([str(raw)], args)
        owner = next(self.out.glob("*/ar_*/analysis_manifest.json"))
        value = json.loads(owner.read_bytes())
        self.assertEqual(value["status"], "failed")
        frames = next(o for o in value["outputs"] if o["kind"] == "frames")
        self.assertEqual(frames["sha256"], rf.file_identity(frames["path"])["sha256"])
        return owner, Path(frames["path"])

    def test_failed_analysis_valid_recorded_frames(self):
        owner, _ = self.failed_analysis_with_frames()
        self.assertGreater(self.assert_clean().counts["WARNING"], 0)
        self.mutate(owner, lambda m: m.update(status="running"))
        self.assert_clean()

    def test_failed_analysis_recorded_frames_hash_mismatch(self):
        _, frames = self.failed_analysis_with_frames()
        frames.write_bytes(frames.read_bytes() + b"\n")
        self.assert_error("HASH_MISMATCH")

    def test_failed_analysis_rehashed_frames_schema_and_identity(self):
        owner, frames = self.failed_analysis_with_frames()
        original = frames.read_bytes()
        run = json.loads(owner.read_bytes())["analysis_run_id"].encode()
        for before, after, code in ((b"face_x", b"wrong_x", "SCHEMA_INVALID"),
                                    (run, b"ar_wrong", "IDENTITY_MISMATCH")):
            with self.subTest(code=code):
                frames.write_bytes(original.replace(before, after))
                self.mutate(owner, lambda m: m["outputs"][0].update(**rf.file_identity(frames)))
                self.assert_error(code)

    def replacement_lifecycle(self, *, legacy=False):
        with self.actual_analysis_producer(legacy=legacy) as (module, raw, args):
            module.run_analysis([str(raw)], args)  # A
            flat = self.out / (raw.stem + "_frames.csv")
            args.from_csv = True
            module.run_analysis([str(flat)], args)  # B
            self.assert_clean()
            owners = list(self.out.glob("*/ar_*/analysis_manifest.json"))
            csv_owner = next(p for p in owners if json.loads(p.read_bytes())["analysis_mode"] ==
                             "summarize_existing_frames")
            historical = csv_owner.read_bytes()
            value = json.loads(historical)
            archive = Path(next(o["path"] for o in value["outputs"] if o["kind"] == "source_frames"))
            archived_bytes = archive.read_bytes()
            args.from_csv = False
            module.run_analysis([str(raw)], args)  # C republishes both flat files.
            self.assertNotEqual(value["inputs"]["frames"]["sha256"], rf.file_identity(flat)["sha256"])
            self.assertNotEqual(value["inputs"]["frames_provenance"]["sha256"],
                                rf.file_identity(str(flat) + ".provenance.json")["sha256"])
            self.assertEqual(csv_owner.read_bytes(), historical)
            self.assertEqual(archive.read_bytes(), archived_bytes)
            self.assert_clean()
        return csv_owner, archive, Path(value["inputs"]["parent_manifest"]["path"])

    def test_legacy_csv_history_survives_explicit_compatibility_replacement(self):
        owner, archive, parent = self.replacement_lifecycle(legacy=True)
        value = json.loads(owner.read_bytes())
        previous = json.loads(parent.read_bytes())
        output = next(o for o in previous["outputs"] if o["kind"] == "frames")
        self.assertEqual(previous["identity_status"], "legacy_raw")
        self.assertEqual(previous["dataset_role"], "pilot")
        self.assertEqual(previous["protocol_version"], "unknown_legacy")
        self.assertNotEqual(Path(output["compatibility_path"]).name, value["recording_id"] + "_frames.csv")
        self.assertEqual(output["compatibility_path"], value["inputs"]["frames"]["path"])
        self.assertEqual(archive.read_bytes(), Path(output["path"]).read_bytes())
        before = self.snapshot()
        self.assert_clean()
        self.assertEqual(before, self.snapshot())

    def test_legacy_csv_archived_source_corruption(self):
        owner, archive, _ = self.replacement_lifecycle(legacy=True)
        archive.write_bytes(archive.read_bytes() + b"\n")
        self.assert_error("HASH_MISMATCH")
        # Even repinning the archive cannot sever its equality to the input/parent.
        self.mutate(owner, lambda m: next(o for o in m["outputs"] if o["kind"] == "source_frames").update(
            **rf.file_identity(archive)))
        self.assert_error("HASH_MISMATCH")

    def test_legacy_csv_archived_source_missing_or_stored_hash_mismatch(self):
        owner, archive, _ = self.replacement_lifecycle(legacy=True)
        original = archive.read_bytes()
        archive.unlink()
        self.assert_error("MISSING_ARTIFACT")
        archive.write_bytes(original)
        self.mutate(owner, lambda m: next(o for o in m["outputs"] if o["kind"] == "source_frames").update(sha256="a" * 64))
        self.assert_error("HASH_MISMATCH")

    def test_legacy_csv_parent_authority_loss_or_byte_corruption(self):
        _, _, parent = self.replacement_lifecycle(legacy=True)
        frames = Path(next(o["path"] for o in json.loads(parent.read_bytes())["outputs"] if o["kind"] == "frames"))
        for path in (parent, frames):
            original = path.read_bytes()
            for missing in (True, False):
                with self.subTest(path=path.name, missing=missing):
                    if missing:
                        path.unlink()
                    else:
                        path.write_bytes(original + b"\n")
                    self.assert_error("MISSING_ARTIFACT" if missing else "HASH_MISMATCH")
                    path.write_bytes(original)

    def test_legacy_csv_parent_identity_ownership_and_hash(self):
        owner, _, parent = self.replacement_lifecycle(legacy=True)
        original_parent, original_owner = parent.read_bytes(), owner.read_bytes()
        for field, replacement in (("recording_id", "other"), ("analysis_run_id", "ar_wrong"),
                                   ("status", "failed"), ("path", str(self.out / "other/ar_wrong/a_frames.csv")),
                                   ("sha256", "a" * 64)):
            with self.subTest(field=field):
                parent.write_bytes(original_parent)
                owner.write_bytes(original_owner)
                def change(m):
                    target = next(o for o in m["outputs"] if o["kind"] == "frames") if field in ("path", "sha256") else m
                    target[field] = replacement
                self.mutate(parent, change)
                self.mutate(owner, lambda m: m["inputs"]["parent_manifest"].update(**rf.file_identity(parent)))
                auditor = checker.Auditor(self.root)
                auditor.check(owner, lambda: auditor.analysis_run(owner))
                self.assertTrue(any(f.severity == "ERROR" for f in auditor.findings), auditor.findings)

    def test_legacy_csv_rehashed_archive_schema_and_row_identity(self):
        owner, archive, parent = self.replacement_lifecycle(legacy=True)
        original_owner, original_parent, original_archive = owner.read_bytes(), parent.read_bytes(), archive.read_bytes()
        value = json.loads(original_parent)
        frames = Path(next(o["path"] for o in value["outputs"] if o["kind"] == "frames"))
        for old, new, code in ((b"face_x", b"wrong_x", "SCHEMA_INVALID"),
                              (value["recording_id"].encode(), b"other", "IDENTITY_MISMATCH"),
                              (value["analysis_run_id"].encode(), b"ar_wrong", "IDENTITY_MISMATCH")):
            with self.subTest(code=code, old=old):
                owner.write_bytes(original_owner)
                parent.write_bytes(original_parent)
                archive.write_bytes(original_archive.replace(old, new))
                frames.write_bytes(archive.read_bytes())
                self.mutate(parent, lambda m: next(o for o in m["outputs"] if o["kind"] == "frames").update(
                    **rf.file_identity(frames)))
                def repin(m):
                    m["inputs"]["parent_manifest"].update(**rf.file_identity(parent))
                    m["inputs"]["frames"].update(sha256=rf.file_identity(archive)["sha256"], size_bytes=archive.stat().st_size)
                    next(o for o in m["outputs"] if o["kind"] == "source_frames").update(**rf.file_identity(archive))
                self.mutate(owner, repin)
                auditor = checker.Auditor(self.root)
                auditor.check(owner, lambda: auditor.analysis_run(owner))
                self.assertIn(code, [f.code for f in auditor.findings if f.severity == "ERROR"])

    def test_legacy_csv_false_current_compatibility_claim(self):
        owner, _, _ = self.replacement_lifecycle(legacy=True)
        link = Path(json.loads(owner.read_bytes())["inputs"]["frames_provenance"]["path"])
        self.mutate(link, lambda m: m.update(analysis_run_id="ar_false_current_owner"))
        self.assert_error("OWNER_MISMATCH")

    def test_csv_unrelated_frames_like_input_remains_pinned(self):
        with self.actual_analysis_producer(legacy=True) as (module, raw, args):
            module.run_analysis([str(raw)], args)
            flat = self.out / (raw.stem + "_frames.csv")
            # A separately pinned copy is legal producer input, but the parent's
            # compatibility_path identifies only the flat publication above.
            unrelated = self.root / "data" / flat.name
            unrelated.write_bytes(flat.read_bytes())
            link = json.loads(Path(str(flat) + ".provenance.json").read_bytes())
            link["analysis_manifest"] = str(self.out / link["analysis_manifest"])
            sidecar = self.json_file(Path(str(unrelated) + ".provenance.json"), link)
            args.from_csv = True
            module.run_analysis([str(unrelated)], args)
            args.from_csv = False
            module.run_analysis([str(raw)], args)
            self.assert_clean()
        for path in (unrelated, sidecar):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                result = self.assert_error("HASH_MISMATCH")
                self.assertTrue(any(str(path) in f.reason for f in result.findings if f.code == "HASH_MISMATCH"))
                path.write_bytes(original)

    def test_csv_modern_spelling_without_parent_compatibility_relation_stays_pinned(self):
        owner, _, parent = self.replacement_lifecycle()
        self.mutate(parent, lambda m: next(o for o in m["outputs"] if o["kind"] == "frames").pop("compatibility_path"))
        self.mutate(owner, lambda m: m["inputs"]["parent_manifest"].update(**rf.file_identity(parent)))
        result = self.assert_error("HASH_MISMATCH")
        flat = json.loads(owner.read_bytes())["inputs"]["frames"]["path"]
        self.assertTrue(any(flat in f.reason for f in result.findings if f.code == "HASH_MISMATCH"))

    def failed_exclude_evidence(self, *, status="failed", kinds=("analysis_manifest",)):
        owner, frames = self.failed_analysis_with_frames()
        if status != "failed":
            self.mutate(owner, lambda m: m.update(status=status))
        value = json.loads(owner.read_bytes())
        camera = Path(value["inputs"]["capture_metadata"]["path"])
        event = dict(schema_version=selection.EVENT_SCHEMA, selection_event_id=selection.new_event_id(),
                     event_type="selection_decision", created_at=checker.analysis.utc_now().isoformat(),
                     dataset_role=value["dataset_role"], subject="P01", round="1", recording_id=value["recording_id"],
                     selection_policy_version=None, decided_by="synthetic-test-authority",
                     supersedes_selection_event_id=None, recapture=None,
                     decision=dict(disposition="exclude", reason_code="test-only", reason_text=None,
                                   analysis_selection=None),
                     evidence=[self.evidence(camera, "capture_provenance", value["recording_id"])])
        for kind in kinds:
            event["evidence"].append(self.evidence(owner if kind == "analysis_manifest" else frames, kind, value["recording_id"]))
        return event, owner, frames

    def test_failed_exclude_analysis_manifest_evidence(self):
        event, _, _ = self.failed_exclude_evidence()
        self.append(event)
        self.assertEqual(selection.read_selection_events(self.root), [event])
        before = self.snapshot()
        self.assert_clean()
        self.assertEqual(before, self.snapshot())

    def test_running_exclude_manifest_and_frames_evidence(self):
        event, _, _ = self.failed_exclude_evidence(status="running", kinds=("analysis_manifest", "canonical_frames"))
        self.append(event)
        self.assertEqual(selection.read_selection_events(self.root), [event])
        self.assert_clean()

    def test_failed_exclude_canonical_frames_only_evidence(self):
        event, _, _ = self.failed_exclude_evidence(kinds=("canonical_frames",))
        self.append(event)
        self.assert_clean()

    def test_failed_exclude_recorded_output_hash_corruption(self):
        event, _, frames = self.failed_exclude_evidence()
        self.append(event)
        frames.write_bytes(frames.read_bytes() + b"\n")
        # The pinned manifest is intact; deep output validation must still fail.
        self.assertEqual(selection.read_selection_events(self.root), [event])
        self.assert_error("HASH_MISMATCH")

    def test_failed_exclude_rehashed_schema_and_identity_corruption(self):
        event, owner, frames = self.failed_exclude_evidence(kinds=("analysis_manifest", "canonical_frames"))
        original_owner, original_frames = owner.read_bytes(), frames.read_bytes()
        value = json.loads(original_owner)
        for old, new, code in ((b"face_x", b"wrong_x", "SCHEMA_INVALID"),
                              (value["recording_id"].encode(), b"other", "IDENTITY_MISMATCH"),
                              (value["analysis_run_id"].encode(), b"ar_wrong", "IDENTITY_MISMATCH")):
            with self.subTest(code=code, old=old):
                owner.write_bytes(original_owner)
                frames.write_bytes(original_frames.replace(old, new))
                self.mutate(owner, lambda m: m["outputs"][0].update(**rf.file_identity(frames)))
                for item in event["evidence"]:
                    item["sha256"] = rf.file_identity(self.root / item["path"])["sha256"]
                self.ledger.parent.mkdir(exist_ok=True)
                self.ledger.write_bytes(selection.event_bytes(event))
                self.assertEqual(selection.read_selection_events(self.root), [event])
                result = self.assert_error(code)
                self.assertFalse(any("must be completed" in f.reason for f in result.findings))
                for item in event["evidence"][1:]:
                    auditor = checker.Auditor(self.root)
                    auditor.check(self.root / item["path"], lambda: auditor.evidence(item, event))
                    self.assertIn(code, [f.code for f in auditor.findings if f.severity == "ERROR"])

    def test_include_noncompleted_selected_source_rejected(self):
        event, owner, frames = self.failed_exclude_evidence(kinds=("analysis_manifest", "canonical_frames"))
        entry = rf.validate_frames_output(frames, self.out, require_completed=False)
        selected = {k: entry[k] for k in selection.ANALYSIS_FIELDS}
        selected.update(frames_path=frames.relative_to(self.root).as_posix(),
                        analysis_manifest_path=owner.relative_to(self.root).as_posix())
        event["decision"].update(disposition="include", analysis_selection=selected)
        with self.assertRaisesRegex(ValueError, "must be completed"):
            self.append(event)
        self.ledger.parent.mkdir(exist_ok=True)
        self.ledger.write_bytes(selection.event_bytes(event))
        result = self.assert_error("OWNER_MISMATCH")
        self.assertTrue(any("must be completed" in f.reason for f in result.findings))

    def historical_role_event(self, action, *, status="failed"):
        historical, owner, frames = self.failed_exclude_evidence(
            status=status, kinds=("analysis_manifest", "canonical_frames"))
        # Patch 6 binds same-recording include evidence to analysis_selection.
        # Use a separate recording for legal auxiliary historical evidence.
        child = self.source(rid="P01_r1_recaptured", include=action == "include")
        event = self.relation(child, historical) if action == "recapture" else child
        event["evidence"].extend(deepcopy(historical["evidence"][1:]))
        return event, owner, frames

    def assert_historical_role_clean(self, action, status):
        event, owner, _ = self.historical_role_event(action, status=status)
        self.append(event)  # Real Patch 6 writer validates these references.
        self.assertEqual(selection.read_selection_events(self.root), [event])
        if action == "include":
            self.assertNotEqual(self.owner(event), owner)
            self.assertEqual(json.loads(self.owner(event).read_bytes())["status"], "completed")
            self.build(event)
            self.rf_run(event)
        before = self.snapshot()
        self.assertGreater(self.assert_clean().counts["WARNING"], 0)
        self.assertEqual(before, self.snapshot())
        # Exercise each evidence kind independently as well as orchestration.
        for item in event["evidence"][-2:]:
            with self.subTest(kind=item["kind"]):
                auditor = checker.Auditor(self.root)
                auditor.check(self.root / item["path"], lambda: auditor.evidence(item, event))
                self.assertFalse(any(f.severity == "ERROR" for f in auditor.findings), auditor.findings)

    def test_failed_recapture_historical_evidence(self):
        self.assert_historical_role_clean("recapture", "failed")

    def test_running_recapture_historical_evidence(self):
        self.assert_historical_role_clean("recapture", "running")

    def test_include_completed_source_with_failed_auxiliary_evidence(self):
        self.assert_historical_role_clean("include", "failed")

    def test_include_completed_source_with_running_auxiliary_evidence(self):
        self.assert_historical_role_clean("include", "running")

    def assert_historical_role_hash_corruption(self, action):
        event, owner, frames = self.historical_role_event(action)
        self.append(event)
        self.assert_clean()
        original = deepcopy(event)
        for item in original["evidence"][-2:]:
            path = self.root / item["path"]
            data = path.read_bytes()
            for mutation in ("stored evidence SHA", "actual bytes", "missing"):
                with self.subTest(kind=item["kind"], mutation=mutation):
                    changed = deepcopy(original)
                    if mutation == "stored evidence SHA":
                        next(e for e in changed["evidence"] if e["path"] == item["path"])["sha256"] = "a" * 64
                    elif mutation == "actual bytes":
                        path.write_bytes(data + b"\n")
                    else:
                        path.unlink()
                    self.ledger.write_bytes(selection.event_bytes(changed))
                    self.assert_error("MISSING_ARTIFACT" if mutation == "missing" else "HASH_MISMATCH")
                    path.write_bytes(data)
        self.ledger.write_bytes(selection.event_bytes(original))
        # Re-pin the evidence manifest so its stored output SHA is checked too.
        self.mutate(owner, lambda m: m["outputs"][0].update(sha256="a" * 64))
        self.repin_historical_role(event, owner, frames)
        self.assert_error("HASH_MISMATCH")

    def repin_historical_role(self, event, owner, frames):
        for item in event["evidence"]:
            if self.root / item["path"] in (owner, frames):
                item["sha256"] = rf.file_identity(self.root / item["path"])["sha256"]
        self.ledger.write_bytes(selection.event_bytes(event))

    def test_recapture_historical_evidence_hash_corruption(self):
        self.assert_historical_role_hash_corruption("recapture")

    def test_include_auxiliary_evidence_hash_corruption(self):
        self.assert_historical_role_hash_corruption("include")

    def assert_historical_role_structural_corruption(self, action):
        event, owner, frames = self.historical_role_event(action)
        self.append(event)
        self.assert_clean()
        original_owner, original_frames = owner.read_bytes(), frames.read_bytes()
        value = json.loads(original_owner)
        for old, new, code in ((b"face_x", b"wrong_x", "SCHEMA_INVALID"),
                              (value["recording_id"].encode(), b"other", "IDENTITY_MISMATCH"),
                              (value["analysis_run_id"].encode(), b"ar_wrong", "IDENTITY_MISMATCH")):
            with self.subTest(row_mutation=old):
                owner.write_bytes(original_owner)
                frames.write_bytes(original_frames.replace(old, new))
                self.mutate(owner, lambda m: m["outputs"][0].update(**rf.file_identity(frames)))
                self.repin_historical_role(event, owner, frames)
                # Frozen Patch 6 accepts the evidence; Patch 7 must go deeper.
                self.assertEqual(selection.read_selection_events(self.root), [event])
                result = self.assert_error(code)
                self.assertFalse(any("must be completed" in f.reason for f in result.findings))
                for item in event["evidence"][-2:]:
                    with self.subTest(kind=item["kind"]):
                        auditor = checker.Auditor(self.root)
                        auditor.check(self.root / item["path"], lambda: auditor.evidence(item, event))
                        self.assertIn(code, [f.code for f in auditor.findings if f.severity == "ERROR"])
        frames.write_bytes(original_frames)
        for field, replacement in (("recording_id", "other"), ("analysis_run_id", "ar_wrong"),
                                   ("outputs", [])):
            with self.subTest(owner_mutation=field):
                owner.write_bytes(original_owner)
                self.mutate(owner, lambda m: m.update({field: replacement}))
                self.repin_historical_role(event, owner, frames)
                self.assert_error()
        owner.write_bytes(b'{"recording_id":')
        self.repin_historical_role(event, owner, frames)
        self.assert_error()
        owner.write_bytes(original_owner)
        for kind in ("analysis_manifest", "canonical_frames"):
            with self.subTest(contradictory_reference=kind):
                changed = deepcopy(event)
                next(e for e in changed["evidence"][-2:] if e["kind"] == kind)["recording_id"] = "other"
                self.repin_historical_role(changed, owner, frames)
                self.assert_error("IDENTITY_MISMATCH")

    def test_recapture_historical_evidence_schema_and_identity_corruption(self):
        self.assert_historical_role_structural_corruption("recapture")

    def test_include_auxiliary_evidence_schema_and_identity_corruption(self):
        self.assert_historical_role_structural_corruption("include")

    def test_same_noncompleted_analysis_evidence_and_selected_source(self):
        event, owner, frames = self.failed_exclude_evidence(kinds=("analysis_manifest", "canonical_frames"))
        for status in ("failed", "running"):
            with self.subTest(status=status):
                self.mutate(owner, lambda m: m.update(status=status))
                entry = rf.validate_frames_output(frames, self.out, require_completed=False)
                selected = {k: entry[k] for k in selection.ANALYSIS_FIELDS}
                selected.update(frames_path=frames.relative_to(self.root).as_posix(),
                                analysis_manifest_path=owner.relative_to(self.root).as_posix())
                event["decision"].update(disposition="include", analysis_selection=selected)
                self.ledger.parent.mkdir(exist_ok=True)
                self.repin_historical_role(event, owner, frames)
                # Validate evidence FIRST on the same auditor: no cached evidence
                # success may exempt the selected-source edge from completion.
                auditor = checker.Auditor(self.root)
                for item in event["evidence"][1:]:
                    auditor.check(self.root / item["path"], lambda: auditor.evidence(item, event))
                self.assertFalse(any(f.severity == "ERROR" for f in auditor.findings), auditor.findings)
                auditor.selections()
                self.assertTrue(any(f.severity == "ERROR" and "must be completed" in f.reason
                                    for f in auditor.findings), auditor.findings)
                with self.assertRaisesRegex(ValueError, "must be completed"):
                    self.append(event)
                self.assert_error("OWNER_MISMATCH")

    def test_recapture_evidence_does_not_exempt_rf_consumer(self):
        event, _, frames = self.historical_role_event("recapture")
        self.append(event)
        self.assert_clean()
        experiment = self.rf_run(status="running")
        entry = rf.validate_frames_output(frames, self.out, require_completed=False)
        self.mutate(experiment, lambda m: m["inputs"].update(ours=[entry]))
        result = self.assert_error("OWNER_MISMATCH")
        self.assertTrue(any(f.artifact == experiment.relative_to(self.root).as_posix() and
                            "must be completed" in f.reason for f in result.findings), result.findings)

    def test_unsupported_historical_evidence_kind_rejected(self):
        event, _, _ = self.historical_role_event("recapture")
        self.append(event)
        self.assert_clean()
        event["evidence"][-1]["kind"] = "historical_frames"
        self.ledger.write_bytes(selection.event_bytes(event))
        result = self.assert_error()
        self.assertTrue(any("unsupported evidence kind" in f.reason for f in result.findings))

    def test_csv_history_survives_flat_replacement(self):
        self.replacement_lifecycle()
        before = self.snapshot()
        self.assert_clean()
        self.assertEqual(before, self.snapshot())

    def test_csv_replacement_archived_source_corruption(self):
        _, archive, _ = self.replacement_lifecycle()
        archive.write_bytes(archive.read_bytes() + b"\n")
        self.assert_error("HASH_MISMATCH")

    def test_csv_replacement_parent_authority_loss(self):
        _, _, parent = self.replacement_lifecycle()
        frames = Path(next(o["path"] for o in json.loads(parent.read_bytes())["outputs"] if o["kind"] == "frames"))
        for path in (frames, parent):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.unlink()
                self.assert_error("MISSING_ARTIFACT")
                path.write_bytes(original)

    def test_csv_replacement_archived_source_missing_or_undeclared(self):
        owner, archive, _ = self.replacement_lifecycle()
        original = archive.read_bytes()
        archive.unlink()
        self.assert_error("MISSING_ARTIFACT")
        archive.write_bytes(original)
        self.mutate(owner, lambda m: m.update(outputs=[o for o in m["outputs"] if o["kind"] != "source_frames"]))
        self.assert_error("MISSING_ARTIFACT")

    def test_csv_replacement_parent_identity_ownership_and_hash(self):
        owner, _, parent = self.replacement_lifecycle()
        original_parent, original_owner = parent.read_bytes(), owner.read_bytes()
        changes = (
            ("recording", lambda m: m.update(recording_id="other")),
            ("run", lambda m: m.update(analysis_run_id="ar_nonexistent")),
            ("status", lambda m: m.update(status="failed")),
            ("output owner", lambda m: next(o for o in m["outputs"] if o["kind"] == "frames").update(
                path=str(self.out / "other/ar_missing/other_frames.csv"))),
            ("output hash", lambda m: next(o for o in m["outputs"] if o["kind"] == "frames").update(sha256="a" * 64)),
        )
        for name, change in changes:
            with self.subTest(mutation=name):
                parent.write_bytes(original_parent)
                owner.write_bytes(original_owner)
                self.mutate(parent, change)
                # Repin the manifest so the test proves lineage checking, not
                # merely detection of an out-of-date parent-manifest digest.
                self.mutate(owner, lambda m: m["inputs"]["parent_manifest"].update(**rf.file_identity(parent)))
                auditor = checker.Auditor(self.root)
                auditor.check(owner, lambda: auditor.analysis_run(owner))
                self.assertTrue(any(f.severity == "ERROR" for f in auditor.findings), auditor.findings)

    def test_csv_replacement_current_false_compatibility_claim(self):
        owner, _, _ = self.replacement_lifecycle()
        value = json.loads(owner.read_bytes())
        link = Path(value["inputs"]["frames_provenance"]["path"])
        self.mutate(link, lambda m: m.update(analysis_run_id="ar_false_current_owner"))
        self.assert_error("OWNER_MISMATCH")

    def test_csv_noncompatibility_input_hash_remains_pinned(self):
        owner, archive, _ = self.replacement_lifecycle()
        # A run-scoped source path never receives the two flat-path exceptions.
        self.mutate(owner, lambda m: m["inputs"]["frames"].update(path=str(archive), sha256="a" * 64))
        self.assert_error("HASH_MISMATCH")

    def test_noncompleted_canonical_consumers_still_require_completion(self):
        event = self.source()
        self.append(event)
        dataset = self.build(event)
        experiment = self.rf_run(event)
        owner = self.owner(event)
        self.mutate(owner, lambda m: m.update(status="failed"))
        sha = rf.file_identity(owner)["sha256"]
        self.refresh_owner_link(event)
        selected = event["decision"]["analysis_selection"]
        selected["analysis_manifest_sha256"] = sha
        next(e for e in event["evidence"] if e["kind"] == "analysis_manifest")["sha256"] = sha
        self.ledger.write_bytes(selection.event_bytes(event))
        value = json.loads(dataset.read_bytes())
        value["entries"][0].update(analysis_manifest_sha256=sha,
                                   selection_event_sha256=hashlib.sha256(selection.event_bytes(event)).hexdigest())
        dataset.write_bytes(selection.manifest_bytes(value))
        self.mutate(experiment, lambda m: m["inputs"]["ours"][0].update(analysis_manifest_sha256=sha))
        for consume in (lambda: rf.canonical_input(self.frames(event), self.out),
                        lambda: selection.read_selection_events(self.root),
                        lambda: selection.resolve_dataset_manifest(dataset, self.root)):
            with self.subTest(consumer=consume), self.assertRaisesRegex(ValueError, "must be completed"):
                consume()
        result = self.assert_error("OWNER_MISMATCH")
        for path in (experiment, Path(str(self.out / self.frames(event).name) + ".provenance.json")):
            self.assertTrue(any(f.severity == "ERROR" and f.artifact == path.relative_to(self.root).as_posix()
                                and "must be completed" in f.reason for f in result.findings), result.findings)

    def test_optional_rf_plot_missing_only_after_declaration_is_error(self):
        owner = self.rf_run()
        plot = owner.parent / "fig5_rf_compare.png"
        self.assertFalse(plot.exists())
        self.assert_clean()
        plot.write_bytes(b"synthetic optional plot")
        self.mutate(owner, lambda m: m["outputs"].append(dict(kind=plot.name, **rf.file_identity(plot))))
        self.assert_clean()
        plot.unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_multiple_direct_recapture_parents_orchestration(self):
        a, b, c = [self.source(rid=rid, include=False) for rid in ("parent_a", "parent_b", "child")]
        self.append(self.relation(c, a))
        with self.ledger.open("ab") as stream:
            stream.write(selection.event_bytes(self.relation(c, b)))
        result = self.assert_error("GRAPH_INVALID")
        self.assertTrue(any("multiple direct recapture parents" in f.reason for f in result.findings))

    def test_reused_validator_programming_failures_exit_two(self):
        self.source()
        for name in ("file_identity", "validate_frames_output"):
            for exception in (TypeError, KeyError, AttributeError):
                with self.subTest(validator=name, exception=exception):
                    out, err = io.StringIO(), io.StringIO()
                    with patch.object(rf, name, side_effect=exception("synthetic checker bug")), \
                            redirect_stdout(out), redirect_stderr(err):
                        self.assertEqual(checker.main(["--repo-root", str(self.root)]), 2)
                    self.assertIn("CHECKER_FAILURE: " + exception.__name__, err.getvalue())
                    self.assertEqual(out.getvalue(), "")

    def test_reused_validator_expected_rejection_remains_exit_one(self):
        event = self.source(include=False)
        event["schema_version"] = "invalid"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_bytes(selection.event_bytes(event))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(checker.main(["--repo-root", str(self.root)]), 1)
        self.assertIn("unsupported selection event schema", out.getvalue())
        self.assertNotIn("CHECKER_FAILURE", err.getvalue())

    def test_legacy_raw_analysis_unknown_metadata_is_supported(self):
        event = self.source()
        path = self.owner(event)
        camera = self.root / event["evidence"][0]["path"]
        camera.unlink()
        def legacy(value):
            value.update(identity_status="legacy_raw", protocol_version="unknown_legacy",
                         legacy_input=dict(reason="explicit legacy pilot", historical_provenance="unknown"))
            value["inputs"]["capture_metadata"] = dict(path=str(camera), sha256=None, hash_status="unavailable")
        self.mutate(path, legacy)
        self.refresh_owner_link(event)
        self.assert_clean()

    def test_absent_batch_legal_before_nonterminal_publication(self):
        event = self.source()
        path = self.owner(event)
        value = self.mutate(path, lambda m: m.update(status="running", outputs=[]))
        self.frames(event).unlink()
        (self.out / self.frames(event).name).unlink()
        Path(str(self.out / self.frames(event).name) + ".provenance.json").unlink()
        (self.out / "batches" / value["analysis_batch_id"] / "analysis_batch.json").unlink()
        self.assert_clean()

    def test_failed_rf_recorded_outputs_still_enforced(self):
        path = self.rf_run(self.source())
        self.mutate(path, lambda m: m.update(status="failed"))
        self.assert_clean()
        (path.parent / "rf_results.txt").unlink()
        self.assert_error("MISSING_ARTIFACT")

    def test_deep_unselected_canonical_frames_evidence(self):
        source = self.source()
        event = self.source(rid="P01_r1_excluded", include=False)
        item = self.evidence(self.frames(source), "canonical_frames", "incorrect-identity")
        event["evidence"].append(item)
        self.append(event)  # Exclude does not otherwise consume canonical evidence.
        self.assert_error("IDENTITY_MISMATCH")

    def test_selection_branching_duplicate_and_recapture_self_parent(self):
        event = self.source(include=False)
        self.append(event)
        first = selection.event_bytes(event)
        second = dict(event, selection_event_id=selection.new_event_id(),
                      supersedes_selection_event_id=event["selection_event_id"])
        third = dict(second, selection_event_id=selection.new_event_id())
        for data in (first + first, first + selection.event_bytes(second) + selection.event_bytes(third),
                     selection.event_bytes(self.relation(event, event))):
            with self.subTest(data=data):
                self.ledger.write_bytes(data)
                self.assert_error("GRAPH_INVALID")

    def test_selected_frames_owner_status_mismatch(self):
        event = self.source()
        self.append(event)
        owner = self.owner(event)
        self.mutate(owner, lambda m: m.update(status="failed"))
        sha = rf.file_identity(owner)["sha256"]
        event["decision"]["analysis_selection"]["analysis_manifest_sha256"] = sha
        next(e for e in event["evidence"] if e["kind"] == "analysis_manifest")["sha256"] = sha
        self.ledger.write_bytes(selection.event_bytes(event))
        self.assert_error("OWNER_MISMATCH")

    def test_malformed_authorities_are_findings_not_internal_failures(self):
        event = self.source()
        rf_path = self.rf_run()
        for path in (self.owner(event), rf_path):
            original = path.read_bytes()
            for value in (b'{"unfinished":', b'[]', b'{"status":"running","status":"failed"}'):
                with self.subTest(path=path, value=value):
                    path.write_bytes(value)
                    self.assert_error()
                    path.write_bytes(original)

    def test_malformed_nested_records_are_schema_findings(self):
        event = self.source()
        rf_path = self.rf_run()
        for path, field, invalid in ((self.owner(event), "inputs", {"recording": None}),
                                     (self.owner(event), "outputs", [None]),
                                     (self.owner(event), "outputs", [{"path": "../escape", "kind": "frames"}]),
                                     (self.owner(event), "inputs", {"recording": {"path": str(self.root), "sha256": "a" * 64}}),
                                     (rf_path, "outputs", [None])):
            with self.subTest(field=field, invalid=invalid):
                original = path.read_bytes()
                self.mutate(path, lambda m: m.update({field: invalid}))
                self.assert_error("SCHEMA_INVALID")
                path.write_bytes(original)

    def test_lineage_row_count_exact_fields_and_duplicate_index(self):
        path = self.rf_run(self.source())
        lineage = path.parent / "sample_lineage.jsonl"
        original = lineage.read_bytes()
        for change in (lambda rows: rows[0].pop("subject"), lambda rows: rows.append(dict(rows[0])),
                       lambda rows: rows[0].update(unfrozen_field=True)):
            with self.subTest(change=change):
                lineage.write_bytes(original)
                self.mutate_lineage(path, change)
                self.assert_error()
        lineage.write_bytes(original)
        self.mutate(path, lambda m: m["sample_lineage"].update(sha256=rf.file_identity(lineage)["sha256"], row_count=99))
        self.assert_error("SCHEMA_INVALID")

    def test_dataset_serialization_and_rf_manifest_pin(self):
        event = self.source()
        self.append(event)
        dataset = self.build(event)
        self.rf_run(event, dataset)
        dataset.write_bytes(dataset.read_bytes() + b"\n")
        result = self.assert_error("SERIALIZATION_INVALID")
        self.assertIn("HASH_MISMATCH", [f.code for f in result.findings])

    def test_mutation_during_hash_fails_closed(self):
        original = rf.file_identity
        def hashing(path):
            if Path(path) == self.lock:
                raise ValueError("file changed while hashing: synthetic lock")
            return original(path)
        with patch.object(rf, "file_identity", side_effect=hashing):
            self.assert_error("REPOSITORY_CHANGED_DURING_CHECK")

    def test_foreign_absolute_external_input_warning_on_posix(self):
        if sys.platform == "win32":
            self.skipTest("Windows absolute paths are native on Windows")
        path = self.rf_run(status="failed")
        self.mutate(path, lambda m: m["inputs"].update(paper=dict(path="C:\\historical\\Dataset.xlsx",
                    sha256="a" * 64, size_bytes=100, source_dataset_id="paper_dataset")))
        result = self.assert_clean()
        self.assertIn("EXTERNAL_UNVERIFIABLE", [f.code for f in result.findings])

    def test_cli_unknown_argument_exit_two(self):
        result = subprocess.run([sys.executable, "-B", str(Path(checker.__file__)), "--repair"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("PASS", result.stdout)

    def test_cli_missing_runtime_dependency_exit_two(self):
        code = """
import builtins, runpy, sys
original = builtins.__import__
def importing(name, *args, **kwargs):
    if name == 'cv2':
        raise ModuleNotFoundError('synthetic missing runtime dependency')
    return original(name, *args, **kwargs)
builtins.__import__ = importing
runpy.run_path(sys.argv[1], run_name='__main__')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code, str(Path(checker.__file__))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("CHECKER_FAILURE", result.stderr)
        self.assertNotIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
