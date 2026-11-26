"""Patch 5 synthetic schema/lineage tests. No research or hardware evidence."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import openpyxl

import rf_experiment as rf
from patch5_test_fixtures import make_frames, analysis


class Patch5Tests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.out = self.root / "analysis"
        self.out.mkdir()
        self.results = self.root / "results"
        self.stack.enter_context(patch.object(analysis, "OUT_DIR", str(self.out)))
        self.stack.enter_context(patch.object(rf, "OUT_DIR", str(self.out)))
        self.stack.enter_context(patch.object(rf, "RESULTS_DIR", str(self.results)))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))

    def evidence(self, rid, sha, status="completed", mode="extract_raw"):
        path = self.out / rid / ("ar_" + status) / "analysis_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(recording_id=rid, status=status, analysis_mode=mode,
                                       inputs=dict(recording=dict(sha256=sha)))), encoding="utf-8")
        return path

    def summary_rows(self, rid="take1", run="ar_one"):
        return [dict(subject="P01", round="1", step=i, label=lab, recording_id=rid,
                     analysis_run_id=run, dataset_role="pilot", protocol_version="synthetic",
                     face_area_px=area, face_w_px=100, z_face_m=z, z_sh_m=.8)
                for i, lab, area, z in ((1, "upright", 100, .75), (2, "forward_head", 125, .65),
                                        (3, "upright", 110, .73), (4, "lean_left", 132, .70))]

    def frames(self, **kwargs):
        return make_frames(self.out, **kwargs)

    def owner(self, path, **updates):
        owner = path.parent / "analysis_manifest.json"
        value = json.loads(owner.read_text(encoding="utf-8"))
        value.update(updates)
        owner.write_text(json.dumps(value), encoding="utf-8")

    def paper(self):
        path = self.root / "paper.xlsx"
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(["header"] * 23)
        for sub in ("S1", "S2"):
            for label in range(1, 6):
                r = [None] * 23
                r[0], r[1] = "sample_" + sub, label
                r[5], r[6] = 300 + label, 150 + label
                r[15], r[16], r[10], r[11] = 220, 300, 420, 300
                r[22] = 1 + label / 10
                ws.append(r)
            ws.append([None] * 23)
        book.save(path)
        book.close()
        return path

    def multi(self):
        path = self.root / "multi.csv"
        rows = []
        for i in range(6):
            for sub in ("S1", "S2"):
                row = dict(subject=sub, upperbody_label="TUP" if i == 0 else "TLB")
                for j, point in enumerate(("left_ear", "right_ear", "nose", "left_eye", "right_eye",
                                           "mouth_left", "mouth_right", "right_shoulder", "left_shoulder")):
                    row[point + "_x"], row[point + "_y"] = 100 + j * 10 + i, 200 + j * 5
                rows.append(row)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def run_rf(self, frames=None, extra=(), plot_error=False):
        paper = self.paper()
        argv = ["rf_experiment.py", "--paper", str(paper), "--trees", "2", "--seeds", "1",
                "--lams", "0", "--features", "all", "invariant", "relative"]
        if frames is not None:
            argv += ["--ours-frames", str(frames)]
        argv += list(extra)
        def plot(rows):
            (Path(rf.OUT_DIR) / "fig5_rf_compare.png").write_bytes(b"synthetic plot")
            if plot_error:
                raise RuntimeError("synthetic optional plot failure")
        with patch("sys.argv", argv), patch.object(rf, "plot", side_effect=plot):
            directory = rf.main()
        return directory, json.loads((directory / "experiment_manifest.json").read_text(encoding="utf-8"))

    def test_raw_modern_and_legacy_alias_rejected_before_run_creation(self):
        raw = self.root / "P01_r1_alias.bag"
        raw.write_bytes(b"same raw bytes")
        self.evidence("modern_id", hashlib.sha256(raw.read_bytes()).hexdigest())
        before = set(self.out.rglob("*"))
        args = types.SimpleNamespace(from_csv=False, legacy_pilot=True, subjects=["P01"], step=1)
        with patch.object(analysis, "new_analysis_id", side_effect=AssertionError("must not create run")):
            with self.assertRaisesRegex(ValueError, "raw identity conflict"):
                analysis.start_analysis_run(str(raw), args, "batch")
        self.assertEqual(set(self.out.rglob("*")), before)

    def test_raw_same_hash_same_id_allowed_in_all_statuses(self):
        for status in ("running", "completed", "failed"):
            self.evidence("same_id", "a" * 64, status)
        analysis.validate_raw_identity("a" * 64, "same_id")

    def test_raw_existing_repository_conflict_rejected_even_for_unrelated_input(self):
        self.evidence("id_a", "a" * 64)
        self.evidence("id_b", "A" * 64, "failed")
        with self.assertRaisesRegex(ValueError, "repository raw identity conflict"):
            analysis.validate_raw_identity("b" * 64, "new_id")

    def test_raw_only_frozen_identity_evidence_participates(self):
        self.evidence("id_a", "bad hash")
        self.evidence("id_b", "a" * 64, mode="summarize_existing_frames")
        analysis.validate_raw_identity("a" * 64, "new_id")

    def test_raw_failed_and_running_evidence_reject_alias(self):
        for status in ("running", "failed"):
            with self.subTest(status=status):
                self.evidence("owner", "b" * 64, status)
                with self.assertRaisesRegex(ValueError, "raw identity conflict"):
                    analysis.validate_raw_identity("b" * 64, "alias")

    def test_summary_exact_52_field_order(self):
        analysis.summarize(self.summary_rows())
        expected = ("subject round step label n_frames face_detect_ratio pose_detect_ratio "
                    "face_area_px face_area_px_sd face_w_px face_w_px_sd face_x face_x_sd face_y face_y_sd "
                    "theta1_deg theta1_deg_sd theta2_deg theta2_deg_sd theta3_deg theta3_deg_sd "
                    "z_face_m z_face_m_sd z_sh_m z_sh_m_sd face_size_cm2 face_size_cm2_sd "
                    "oval_area_px oval_area_px_sd oval_size_cm2 oval_size_cm2_sd ipd_cm ipd_cm_sd "
                    "box_to_oval box_to_oval_sd ref_step A_ratio A_ratio_oval dZ_face_cm dZ_sh_cm "
                    "D_head_cm sh_face_ratio area_err_est_pct area_cv_pct summary_schema_version "
                    "recording_id analysis_run_id source_frames_analysis_run_id dataset_role protocol_version "
                    "reference_recording_id reference_analysis_run_id").split()
        with (self.out / "summary_steps.csv").open(encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, expected)
            self.assertEqual(len(reader.fieldnames), 52)
            self.assertTrue(all(r["summary_schema_version"] == "summary-schema/1.0.0" for r in reader))

    def test_summary_different_recordings_never_aggregate(self):
        rows = self.summary_rows() + self.summary_rows("take2", "ar_two")
        summary = analysis.summarize(rows)
        self.assertEqual(len(summary), 8)
        self.assertTrue(all(s["n_frames"] == 1 for s in summary))
        self.assertTrue(all(s["analysis_run_id"] == s["source_frames_analysis_run_id"] for s in summary))

    def test_summary_multiple_source_runs_rejected(self):
        with self.assertRaisesRegex(ValueError, "multiple source frame runs"):
            analysis.summarize(self.summary_rows() + self.summary_rows(run="ar_two"))

    def test_summary_conflicting_metadata_rejected(self):
        for field in ("subject", "round", "label", "dataset_role", "protocol_version"):
            rows = self.summary_rows()[:1]
            rows.append(dict(rows[0], **{field: "conflict"}))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "conflicting summary"):
                analysis.summarize(rows)

    def test_summary_reference_isolated_and_previous_upright_preserved(self):
        rows = self.summary_rows() + self.summary_rows("take2", "ar_two")[1:2]
        summary = analysis.summarize(rows)
        self.assertEqual(summary[3]["ref_step"], 3)
        self.assertEqual(summary[3]["A_ratio"], 1.2)
        other = summary[-1]
        self.assertIsNone(other["ref_step"])
        self.assertIsNone(other["reference_recording_id"])
        self.assertIsNone(other["reference_analysis_run_id"])
        self.assertEqual(summary[1]["reference_analysis_run_id"], "ar_one")

    def test_summary_missing_numeric_still_writes_fixed_header(self):
        rows = self.summary_rows()[:1]
        rows[0]["face_w_px"] = None
        analysis.summarize(rows)
        with (self.out / "summary_steps.csv").open(encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["area_err_est_pct"], "")
        self.assertEqual(len(row), 52)

    def test_from_csv_current_vs_source_run_without_model_provisioning(self):
        path = self.frames()
        before = path.read_bytes()
        args = types.SimpleNamespace(from_csv=True, legacy_pilot=False, subjects=["P01"], step=1)
        with patch.object(analysis, "ensure_models", side_effect=AssertionError("no provisioning")), \
                patch.object(analysis, "load_model_lock", side_effect=AssertionError("no current lock")), \
                patch.object(analysis, "report"), patch.object(analysis, "plot_all"):
            analysis.run_analysis([str(self.out / path.name)], args)
        with (self.out / "summary_steps.csv").open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(all(r["source_frames_analysis_run_id"] == "ar_source" for r in rows))
        self.assertTrue(all(r["analysis_run_id"] != "ar_source" for r in rows))
        self.assertEqual(path.read_bytes(), before)

    def test_explicit_canonical_accepts_exact_owner_hash(self):
        path = self.frames()
        entry = rf.resolve_ours_inputs(paths=[path])[0]
        self.assertEqual(set(entry), set("recording_id analysis_run_id subject round frames_schema_version "
                                        "frames_path frames_sha256 analysis_manifest_path analysis_manifest_sha256".split()))
        self.assertEqual(entry["frames_path"], str(path.resolve()))
        self.assertEqual(entry["frames_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_explicit_flat_rejected(self):
        path = self.frames()
        with self.assertRaisesRegex(ValueError, "immutable"):
            rf.resolve_ours_inputs(paths=[self.out / path.name])

    def test_explicit_noncompleted_owner_rejected(self):
        path = self.frames()
        for status in ("running", "failed"):
            self.owner(path, status=status)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "completed"):
                rf.resolve_ours_inputs(paths=[path])

    def test_explicit_owner_identity_and_output_hash_rejected(self):
        path = self.frames()
        self.owner(path, recording_id="other")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            rf.resolve_ours_inputs(paths=[path])
        self.owner(path, recording_id="P01_r1_take", outputs=[])
        with self.assertRaisesRegex(ValueError, "output SHA-256"):
            rf.resolve_ours_inputs(paths=[path])

    def test_explicit_incorrect_header_rejected(self):
        path = self.frames()
        path.write_text("subject,round\nP01,1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "60-field"):
            rf.resolve_ours_inputs(paths=[path])

    def test_explicit_multiple_ids_and_conflicting_step_labels_rejected(self):
        for field in ("recording_id", "analysis_run_id", "subject", "round", "label"):
            path = self.frames(rid="P01_r1_" + field, rows=[dict(step=1), dict(step=1, **{field: "other"})])
            with self.subTest(field=field), self.assertRaises(ValueError):
                rf.resolve_ours_inputs(paths=[path])

    def test_compatibility_resolves_immutable_archive(self):
        path = self.frames()
        self.assertEqual(rf.resolve_ours_inputs(["P01"]), rf.resolve_ours_inputs(paths=[path]))

    def test_compatibility_multiple_completed_runs_rejected(self):
        self.frames()
        explicit = self.frames(run="ar_second")
        with self.assertRaisesRegex(ValueError, "use exact --ours-frames"):
            rf.resolve_ours_inputs(["P01"])
        self.assertEqual(rf.resolve_ours_inputs(paths=[explicit])[0]["analysis_run_id"], "ar_second")

    def test_compatibility_failed_or_summary_only_runs_not_ambiguous(self):
        self.frames()
        path = self.frames(run="ar_second", flat=False)
        self.owner(path, status="failed")
        self.assertEqual(len(rf.resolve_ours_inputs(["P01"])), 1)
        self.owner(path, status="completed", outputs=[dict(kind="source_frames")])
        self.assertEqual(len(rf.resolve_ours_inputs(["P01"])), 1)

    def test_compatibility_sidecar_flat_and_manifest_tampering_rejected(self):
        path = self.frames()
        flat = self.out / path.name
        original = flat.read_bytes()
        flat.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            rf.resolve_ours_inputs(["P01"])
        flat.write_bytes(original)
        self.owner(path, extra="tamper")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            rf.resolve_ours_inputs(["P01"])

    def test_same_subject_round_different_recordings_rejected_before_loader(self):
        a = self.frames()
        b = self.frames(rid="P01_r1_retake")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            rf.resolve_ours_inputs(paths=[a, b])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            rf.load_ours(["P01"])

    def test_explicit_same_recording_two_runs_rejected(self):
        a = self.frames()
        b = self.frames(run="ar_second")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            rf.resolve_ours_inputs(paths=[a, b])

    def test_duplicate_explicit_inputs_rejected(self):
        path = self.frames()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            rf.resolve_ours_inputs(paths=[path, path])

    def test_modified_frames_after_pinning_rejected(self):
        path = self.frames()
        entries = rf.resolve_ours_inputs(paths=[path])
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            rf.load_ours(inputs=entries)

    def test_paper_lineage_original_physical_rows_after_drop(self):
        path, sources = self.paper(), []
        X, y, groups = rf.load_paper(path, lineage=sources)
        self.assertEqual(len(X), len(sources))
        self.assertEqual([r["source_row_number"] for r in sources], [2, 3, 4, 5, 6, 8, 9, 10, 11, 12])
        self.assertEqual([r["subject"] for r in sources], list(groups))
        self.assertEqual([r["label"] for r in sources], list(y))
        self.assertTrue(all(r["source_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() for r in sources))

    def test_multiposture_stride_keeps_original_physical_rows(self):
        sources = []
        X, y, groups = rf.load_multiposture(self.multi(), 2, lineage=sources)
        self.assertEqual([r["source_row_number"] for r in sources], [2, 6, 10, 3, 7, 11])
        self.assertEqual([r["subject"] for r in sources], list(groups))
        self.assertEqual([r["label"] for r in sources], list(y))
        self.assertEqual(len(X), len(sources))

    def test_ours_lineage_matches_dropped_and_sorted_model_samples(self):
        path = self.frames(rows=[dict(step=3, label="lean_left"), dict(step=1, label="upright", face_x=""),
                                dict(step=2, label="upright"), dict(step=4, label="body_forward")])
        sources = []
        X, y, meta = rf.load_ours(inputs=rf.resolve_ours_inputs(paths=[path]), lineage=sources)
        self.assertEqual([r["step"] for r in sources], [2, 3, 4])
        self.assertEqual([m[2] for m in meta], [2, 3, 4])
        self.assertEqual(list(y), [0, 3, -1])
        self.assertEqual(len(X), len(sources))
        self.assertTrue(all(r["calibration_reference_step"] == 1 for r in sources))
        rows = rf.lineage_rows(sources, "er_test", "ours_external", "relative", {("P01_r1_take", "ar_source"): 2})
        self.assertTrue(all(r["relative_reference_step"] == 2 for r in rows))
        self.assertTrue(all(r["reference_recording_id"] == r["recording_id"] and
                            r["reference_analysis_run_id"] == r["analysis_run_id"] for r in rows))

    def test_cross_recording_reference_is_hard_error(self):
        source = dict(source_kind="canonical_frames", recording_id="a", analysis_run_id="ar_a",
                      reference_recording_id="b", calibration_reference_step=1)
        with self.assertRaisesRegex(ValueError, "cross-recording"):
            rf.lineage_rows([source], "er_test", "ours_external", "relative")

    def test_canonical_jsonl_serialization_hash_and_tamper_detection(self):
        artifact = dict(source_dataset_id="paper_dataset", **rf.file_identity(self.paper()))
        rows = rf.lineage_rows([rf.external_source(artifact, 2, "합성", 0)], "er_test", "paper_loso", "all")
        a, b = self.root / "a", self.root / "b"
        a.mkdir()
        b.mkdir()
        first = rf.write_sample_lineage(a, rows)
        second = rf.write_sample_lineage(b, rows)
        expected = (json.dumps(rows[0], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.assertEqual((a / first["path"]).read_bytes(), expected)
        self.assertEqual(first, second)
        self.assertEqual(first["sha256"], hashlib.sha256(expected).hexdigest())
        (a / first["path"]).write_bytes(expected + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            rf.verify_file(a / first["path"], first["sha256"])

    def test_full_run_manifest_result_columns_and_every_model_sample(self):
        path = self.frames()
        directory, manifest = self.run_rf(path, extra=("--multiposture", str(self.multi()), "--stride", "2"))
        self.assertEqual(manifest["status"], "completed")
        self.assertRegex(directory.name, r"^er_\d{8}T\d{12}Z_[0-9a-f]{32}$")
        self.assertEqual(set(manifest), set("schema_version experiment_run_id started_at ended_at status "
                                          "dataset_manifest inputs code environment options sample_lineage outputs "
                                          "errors provenance_unknown_reasons".split()))
        self.assertEqual(manifest["schema_version"], "rf-experiment-provenance/1.0.0")
        self.assertEqual(manifest["dataset_manifest"], dict(dataset_manifest_id=None, path=None, sha256=None))
        self.assertEqual(set(manifest["code"]), {"git_commit", "git_dirty", "rf_script_sha256", "path"})
        self.assertEqual(manifest["code"]["rf_script_sha256"], hashlib.sha256(Path(rf.__file__).read_bytes()).hexdigest())
        self.assertEqual(set(manifest["options"]), set("argv paper multiposture ours ours_frames dataset_manifest trees seeds stride lams skip_paper_loso features".split()))
        self.assertTrue(set("python os architecture numpy matplotlib openpyxl".split()) <= set(manifest["environment"]))
        self.assertEqual(set(manifest["inputs"]), {"paper", "multiposture", "ours"})
        lineage = [json.loads(line) for line in (directory / "sample_lineage.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lineage), 3 * (10 + 5) + 6)
        self.assertEqual(manifest["sample_lineage"]["row_count"], len(lineage))
        for track, count, modes in (("paper_loso", 10, ("all", "invariant", "relative")),
                                    ("ours_external", 5, ("all", "invariant", "relative")),
                                    ("multiposture_loso", 6, ("all",))):
            for mode in modes:
                selected = [r for r in lineage if r["dataset_track"] == track and r["feature_mode"] == mode]
                self.assertEqual([r["sample_index"] for r in selected], list(range(count)))
                self.assertTrue(all(set(r) == set(rf.LINEAGE_FIELDS) for r in selected))
                if track == "ours_external":
                    self.assertEqual([r["label"] for r in selected], rf.LAB5)
                    self.assertTrue(all(r["frames_path"] == str(path) and r["frames_sha256"] ==
                                        hashlib.sha256(path.read_bytes()).hexdigest() for r in selected))
        with (directory / "rf_results.csv").open(encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames[-4:], list(rf.RESULT_LINEAGE_FIELDS))
            for row in reader:
                self.assertEqual(row["experiment_run_id"], directory.name)
                self.assertEqual(row["dataset_manifest_sha256"], "")
                self.assertEqual(row["lineage_manifest_path"], "sample_lineage.jsonl")
                self.assertEqual(row["lineage_manifest_sha256"], manifest["sample_lineage"]["sha256"])
                self.assertIn("root_provenance", row)
        self.assertEqual(len(manifest["outputs"]), 3)
        for output in manifest["outputs"]:
            self.assertEqual(output["sha256"], hashlib.sha256(Path(output["path"]).read_bytes()).hexdigest())
            self.assertEqual(Path(output["path"]).read_bytes(), (self.out / output["kind"]).read_bytes())

    def test_second_execution_unique_and_previous_run_unchanged(self):
        directory, _ = self.run_rf()
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        second, _ = self.run_rf()
        self.assertNotEqual(directory, second)
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_completed_run_and_colliding_directory_cannot_be_overwritten(self):
        directory, manifest = self.run_rf()
        before = (directory / "experiment_manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "terminal"):
            rf.write_experiment_manifest(directory, manifest)
        with patch.object(rf, "new_experiment_id", return_value=directory.name):
            with self.assertRaises(FileExistsError):
                rf.start_experiment(types.SimpleNamespace())
        self.assertEqual(before, (directory / "experiment_manifest.json").read_bytes())

    def test_optional_plot_failure_preserves_numeric_completion(self):
        directory, manifest = self.run_rf(plot_error=True)
        self.assertEqual(manifest["status"], "completed")
        self.assertTrue(any("optional plot failure" in e for e in manifest["errors"]))
        self.assertFalse((directory / "fig5_rf_compare.png").exists())
        self.assertEqual({o["kind"] for o in manifest["outputs"]}, {"rf_results.csv", "rf_results.txt"})

    def test_failed_run_keeps_manifest_and_does_not_publish(self):
        with patch.object(rf, "load_paper", side_effect=RuntimeError("synthetic load failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic load failure"):
                self.run_rf()
        manifest_path = next(self.results.glob("*/experiment_manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("synthetic load failure", manifest["errors"])
        self.assertIsNotNone(manifest["inputs"]["paper"]["sha256"])
        self.assertFalse((self.out / "rf_results.csv").exists())

    def test_mutation_during_execution_fails_without_flat_publication(self):
        path = self.frames()
        original = rf.execute_experiment
        def mutate(*args):
            original(*args)
            path.write_bytes(path.read_bytes() + b"\n")
        with patch.object(rf, "execute_experiment", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.run_rf(path)
        manifest = json.loads(next(self.results.glob("*/experiment_manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse((self.out / "rf_results.csv").exists())

    def test_cli_ours_modes_are_mutually_exclusive(self):
        with patch("sys.argv", ["rf_experiment.py", "--ours", "P01", "--ours-frames", "any"]):
            with self.assertRaises(SystemExit):
                rf.main()
        self.assertFalse(self.results.exists())

    def test_failed_fitting_retains_persistent_lineage(self):
        with patch.object(rf, "fit_models", side_effect=RuntimeError("synthetic fit failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic fit failure"):
                self.run_rf(self.frames())
        manifest_path = next(self.results.glob("*/experiment_manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        lineage = manifest_path.parent / manifest["sample_lineage"]["path"]
        self.assertEqual(manifest["sample_lineage"]["row_count"], 45)
        self.assertEqual(manifest["sample_lineage"]["sha256"], hashlib.sha256(lineage.read_bytes()).hexdigest())
        self.assertFalse((self.out / "rf_results.csv").exists())

    def test_model_array_order_and_actual_relative_reference_match_jsonl(self):
        path = self.frames(rows=[dict(step=3, label="lean_left", oval_area_px=120, face_x=670),
                                dict(step=1, label="upright", face_x=""),
                                dict(step=2, label="upright", face_x=640),
                                dict(step=4, label="body_forward", oval_area_px=200, face_x=700)])
        original, seen = rf.external, []
        def observe(Xtr, ytr, Xte, yte, meta, *args, **kwargs):
            mode = kwargs["feature_set"]
            seen.append(mode)
            rows = [json.loads(line) for line in (Path(rf.OUT_DIR) / "sample_lineage.jsonl").read_text(encoding="utf-8").splitlines()]
            rows = [r for r in rows if r["dataset_track"] == "ours_external" and r["feature_mode"] == mode]
            self.assertEqual([r["step"] for r in rows], [2, 3, 4])
            self.assertEqual([m[2] for m in meta], [2, 3, 4])
            self.assertEqual(list(yte), [0, 3, -1])
            np.testing.assert_allclose(Xte[:, 0], [1, 1.2, 2])
            self.assertTrue(all(r["calibration_reference_step"] == 1 for r in rows))
            if mode == "relative":
                np.testing.assert_allclose(Xte[:, 1], [0, 20, 40])
                np.testing.assert_array_equal(kwargs["ref_mask"], [True, False, False])
                self.assertTrue(all(r["relative_reference_step"] == 2 for r in rows))
            else:
                self.assertTrue(all(r["relative_reference_step"] is None for r in rows))
            return original(Xtr, ytr, Xte, yte, meta, *args, **kwargs)
        with patch.object(rf, "external", side_effect=observe):
            self.run_rf(path)
        self.assertEqual(seen, ["all", "invariant", "relative"])

    def test_multiline_and_blank_csv_physical_rows_preserved(self):
        path = self.multi()
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        # A blank physical row precedes the first data row; subject is a quoted multiline value.
        lines[1] = lines[1].replace("S1,", '"S\n1",', 1)
        path.write_text(lines[0] + "\n" + "".join(lines[1:]), encoding="utf-8")
        sources = []
        rf.load_multiposture(path, 1, lineage=sources)
        self.assertEqual(sources[0]["source_row_number"], 3)
        self.assertEqual(sources[0]["subject"], "S\n1")
        self.assertEqual(sources[1]["source_row_number"], 5)

    def test_streaming_hash_rejects_mutation(self):
        path = self.root / "changing.bin"
        path.write_bytes(b"before")
        real_sha = hashlib.sha256
        class MutatingDigest:
            def __init__(self):
                self.inner = real_sha()
                self.changed = False
            def update(self, chunk):
                self.inner.update(chunk)
                if not self.changed:
                    self.changed = True
                    with path.open("ab") as stream:
                        stream.write(b"after")
            def hexdigest(self):
                return self.inner.hexdigest()
        with patch.object(rf.hashlib, "sha256", side_effect=MutatingDigest):
            with self.assertRaisesRegex(ValueError, "changed while hashing"):
                rf.file_identity(path)

    def test_result_hash_detects_tampering(self):
        directory, manifest = self.run_rf()
        output = next(o for o in manifest["outputs"] if o["kind"] == "rf_results.csv")
        path = Path(output["path"])
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            rf.verify_file(path, output["sha256"])

    def test_lineage_tampering_before_completion_fails(self):
        original = rf.execute_experiment
        def mutate(a, directory, manifest):
            original(a, directory, manifest)
            path = directory / "sample_lineage.jsonl"
            path.write_bytes(path.read_bytes() + b"\n")
        with patch.object(rf, "execute_experiment", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.run_rf()
        manifest = json.loads(next(self.results.glob("*/experiment_manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse((self.out / "rf_results.csv").exists())

    def test_repeated_from_csv_input_is_rejected_without_silent_run_selection(self):
        path = self.frames()
        args = types.SimpleNamespace(from_csv=True, legacy_pilot=False, subjects=["P01"], step=1)
        flat = str(self.out / path.name)
        with self.assertRaisesRegex(ValueError, "multiple analysis runs"):
            analysis.run_analysis([flat, flat], args)

    def test_missing_external_input_leaves_failed_run_with_options(self):
        with patch("sys.argv", ["rf_experiment.py", "--paper", str(self.root / "absent.xlsx")]):
            with self.assertRaises(FileNotFoundError):
                rf.main()
        manifest = json.loads(next(self.results.glob("*/experiment_manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(manifest["errors"])
        self.assertEqual(manifest["options"]["argv"], ["--paper", str(self.root / "absent.xlsx")])

    def test_required_output_hash_failure_prevents_completion_and_publication(self):
        original = rf.file_identity
        def fail(path):
            if Path(path).name == "rf_results.txt":
                raise OSError("synthetic required output hash failure")
            return original(path)
        with patch.object(rf, "file_identity", side_effect=fail):
            with self.assertRaisesRegex(OSError, "required output hash failure"):
                self.run_rf()
        manifest = json.loads(next(self.results.glob("*/experiment_manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse((self.out / "rf_results.csv").exists())

    def test_terminal_manifest_write_failure_preserves_failed_state(self):
        original = rf.os.replace
        def fail_once(source, destination):
            value = json.loads(Path(source).read_text(encoding="utf-8"))
            if value["status"] == "completed":
                raise OSError("synthetic completion write failure")
            return original(source, destination)
        with patch.object(rf.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "completion write failure"):
                self.run_rf()
        manifest = json.loads(next(self.results.glob("*/experiment_manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse((self.out / "rf_results.csv").exists())
        self.assertFalse(list(self.results.glob("*/.experiment_manifest.tmp")))


if __name__ == "__main__":
    unittest.main()
