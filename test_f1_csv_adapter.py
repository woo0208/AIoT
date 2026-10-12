"""Structural tests for the Gate 1.9 canonical CSV adapter and coverage audit (synthetic only).

Every CSV here is synthetic and written to a temporary directory.  Passing these
tests is software verification of parsing, conversion, counting and integrity
checks, not evidence about real D455 coverage or posture separability.
"""

import contextlib
import csv
import io
import math
import os
import tempfile
import unittest

import analyze_d455
import f1_csv_adapter as adapter
import f1_features as f1
import f1_preflight_coverage as cov


RUN, REC = "ar_synthetic_run", "SYN_r1_synthetic_recording"


def canonical_row(index, /, step="1", label="upright", **overrides):
    """One synthetic frames-schema/1.0.0 row as CSV text cells (all 60 fields)."""

    frame_index = index
    row = dict.fromkeys(analyze_d455.FRAME_FIELDS, "")
    row.update({
        "subject": "SYN", "round": "1", "step": step, "label": label,
        "t": "0.000", "ts_ms": str(1000 + frame_index),
        "frame_schema_version": "frames-schema/1.0.0", "recording_id": REC, "analysis_run_id": RUN,
        "frame_index": str(frame_index), "color_frame_number": str(frame_index),
        "depth_frame_number": str(frame_index), "mediapipe_ts_ms": str(1000 + frame_index),
        "face_depth_source": "bbox_roi", "shoulder_depth_source": "both",
        "face_detected": "true", "face_mesh_detected": "true", "pose_detected": "true",
        "face_depth_valid": "true",
        "face_x": "640.0", "face_y": "200.0",
        # subject-left shoulder appears on image right (non-mirrored image)
        "lsh_valid": "true", "lsh_x": "740.0", "lsh_y": "400.0", "lsh_depth_valid": "true",
        "rsh_valid": "true", "rsh_x": "540.0", "rsh_y": "400.0", "rsh_depth_valid": "true",
        "left_hip_valid": "true", "left_hip_x_px": "710.0", "left_hip_y_px": "700.0",
        "left_hip_visibility": "0.9", "left_hip_depth_valid": "false",
        "right_hip_valid": "true", "right_hip_x_px": "570.0", "right_hip_y_px": "700.0",
        "right_hip_visibility": "0.9", "right_hip_depth_valid": "false",
    })
    row.update(overrides)
    return row


NO_LEFT_HIP = dict(left_hip_valid="false", left_hip_x_px="", left_hip_y_px="", left_hip_depth_valid="false")
NO_RIGHT_HIP = dict(right_hip_valid="false", right_hip_x_px="", right_hip_y_px="", right_hip_depth_valid="false")
NO_HIPS = {**NO_LEFT_HIP, **NO_RIGHT_HIP}


class CsvCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, rows, header=None, name="frames.csv", raw_lines=None):
        path = os.path.join(self._tmp.name, name)
        header = list(analyze_d455.FRAME_FIELDS) if header is None else header
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows:
                writer.writerow([row.get(h, "") for h in header])
            for line in raw_lines or ():
                f.write(line)
        return path

    def load(self, rows, **kwargs):
        return adapter.load_f1_frame_records(self.write(rows, **kwargs))


class ConversionTests(CsvCase):
    def test_correct_row_conversion_matches_direct_feat009(self):
        rows, records = self.load([canonical_row(3, step="2", label="forward_head")])
        rec = records[0]
        self.assertEqual((rec.analysis_run_id, rec.recording_id, rec.frame_index), (RUN, REC, 3))
        self.assertEqual((rec.subject, rec.round, rec.step, rec.label), ("SYN", "1", "2", "forward_head"))
        # same FEAT-009 values as the unchanged calculator on the same typed row
        self.assertEqual(rec.result, f1.compute_f1_5_frame(rows[0]))
        self.assertAlmostEqual(rec.result.features["fs_x"], (640 - 640) / 200)
        self.assertAlmostEqual(rec.result.features["fs_y"], (200 - 400) / 200)
        self.assertAlmostEqual(rec.result.features["sh_y"], (400 - 700) / 200)
        self.assertEqual(rec.result.features["so_beta"], 0.0)   # wrap_pi(atan2(0, -200))
        self.assertTrue(all(rec.result.family_available.values()))

    def test_explicit_boolean_parsing(self):
        rows, records = self.load([canonical_row(1), canonical_row(2, face_detected="false"),
                                   canonical_row(3, face_detected="")])
        self.assertEqual([r["face_detected"] for r in rows], [True, False, None])
        self.assertEqual([r.result.family_available["FS"] for r in records], [True, False, False])
        self.assertEqual(records[1].result.family_reasons["FS"], ("face_detected:false",))
        self.assertEqual(records[2].result.family_reasons["FS"], ("face_detected:unknown",))

    def test_noncanonical_boolean_spellings_fail_closed(self):
        for bad in ("TRUE", "True", "1", "0", "yes"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "invalid canonical boolean"):
                self.load([canonical_row(1, left_hip_valid=bad)])

    def test_missing_hip_coordinates_is_a_diagnostic_not_an_error(self):
        _, records = self.load([canonical_row(1, **NO_LEFT_HIP)])
        res = records[0].result
        self.assertFalse(res.family_available["SH"])
        self.assertEqual(res.family_reasons["SH"], ("left_hip_valid:false",))
        self.assertIsNone(res.features["sh_x"])
        self.assertIsNone(res.features["sh_y"])
        self.assertTrue(res.family_available["FS"] and res.family_available["SO"])

    def test_valid_hip_flag_without_coordinates_is_missing_not_imputed(self):
        _, records = self.load([canonical_row(1, left_hip_x_px="", left_hip_y_px="")])
        self.assertEqual(records[0].result.family_reasons["SH"], ("left_hip_xy:missing",))
        self.assertIsNone(records[0].result.features["sh_x"])

    def test_invalid_shoulder_flag_ignores_numeric_coordinates(self):
        _, records = self.load([canonical_row(1, lsh_valid="false")])   # lsh_x/lsh_y still numeric
        res = records[0].result
        self.assertFalse(any(res.family_available.values()))
        self.assertEqual(res.ordered_values(), (None,) * 5)
        for family in f1.F1_FAMILIES:
            self.assertIn("lsh_valid:false", res.family_reasons[family])

    def test_missing_face(self):
        _, records = self.load([canonical_row(1, face_detected="false", face_x="", face_y="")])
        res = records[0].result
        self.assertEqual((res.features["fs_x"], res.features["fs_y"]), (None, None))
        self.assertTrue(res.family_available["SH"] and res.family_available["SO"])

    def test_nonfinite_coordinates_fail_closed(self):
        for bad in ("nan", "inf", "-inf", "NaN", "Infinity"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "non-finite"):
                self.load([canonical_row(1, left_hip_x_px=bad)])

    def test_non_numeric_coordinate_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid canonical numeric"):
            self.load([canonical_row(1, face_x="abc")])

    def test_round_empty_is_unknown_not_guessed(self):
        _, records = self.load([canonical_row(1, round="")])
        self.assertIsNone(records[0].round)


class MalformedInputTests(CsvCase):
    def test_header_missing_field(self):
        header = [h for h in analyze_d455.FRAME_FIELDS if h != "left_hip_valid"]
        with self.assertRaisesRegex(ValueError, r"missing=\['left_hip_valid'\]"):
            self.load([canonical_row(1)], header=header)

    def test_header_reordered(self):
        header = list(analyze_d455.FRAME_FIELDS)
        header[0], header[1] = header[1], header[0]
        with self.assertRaisesRegex(ValueError, "field order differs"):
            self.load([canonical_row(1)], header=header)

    def test_legacy_unversioned_header_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a frames-schema/1.0.0 header"):
            self.load([canonical_row(1)], header=list(analyze_d455.LEGACY_FRAME_FIELDS))

    def test_unsupported_schema_version(self):
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.load([canonical_row(1, frame_schema_version="frames-schema/2.0.0")])

    def test_ragged_row(self):
        path = self.write([canonical_row(1)], raw_lines=["SYN,1,1,upright\r\n"])
        with self.assertRaisesRegex(ValueError, "malformed CSV record"):
            adapter.load_f1_frame_records(path)

    def test_empty_file_and_header_only(self):
        empty = os.path.join(self._tmp.name, "empty.csv")
        open(empty, "w").close()
        with self.assertRaisesRegex(ValueError, "no header"):
            adapter.load_f1_frame_records(empty)
        with self.assertRaisesRegex(ValueError, "header-only"):
            self.load([])

    def test_missing_frame_index(self):
        with self.assertRaisesRegex(ValueError, "missing canonical frame_index"):
            self.load([canonical_row(1, frame_index="")])

    def test_invalid_frame_index(self):
        for bad in ("0", "-1", "1.5", "x"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "frame_index"):
                self.load([canonical_row(1, frame_index=bad)])

    def test_duplicate_frame_key(self):
        with self.assertRaisesRegex(ValueError, "duplicate canonical frame key"):
            self.load([canonical_row(1), canonical_row(1, step="2")])

    def test_mixed_recording_or_run(self):
        for field in ("recording_id", "analysis_run_id"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "inconsistent canonical frame identity"):
                self.load([canonical_row(1), canonical_row(2, **{field: "other"})])

    def test_conflicting_subject_or_round_within_recording(self):
        for field in ("subject", "round"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"conflicting {field}"):
                self.load([canonical_row(1), canonical_row(2, step="2", **{field: "2"})])

    def test_conflicting_label_within_step(self):
        with self.assertRaisesRegex(ValueError, "conflicting label within step"):
            self.load([canonical_row(1), canonical_row(2, label="forward_head")])

    def test_missing_identity_text(self):
        for field in ("subject", "step", "label"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"missing canonical {field}"):
                self.load([canonical_row(1, **{field: ""})])

    def test_invalid_enum(self):
        with self.assertRaisesRegex(ValueError, "face_depth_source"):
            self.load([canonical_row(1, face_depth_source="other")])


def three_step_rows():
    """Synthetic 3-step recording: upright(4), forward_head(3), upright(2)."""

    return [
        canonical_row(1, step="1"),
        canonical_row(2, step="1", **NO_LEFT_HIP),
        canonical_row(3, step="1", face_detected="false", face_x="", face_y=""),
        canonical_row(5, step="1"),                                # non-contiguous index is legal
        canonical_row(6, step="2", label="forward_head", **NO_HIPS),
        canonical_row(7, step="2", label="forward_head", **NO_HIPS),
        canonical_row(8, step="2", label="forward_head", lsh_valid="false", **NO_RIGHT_HIP),
        canonical_row(9, step="3"),
        canonical_row(10, step="3", rsh_valid="false"),
    ]


class GroupingAndCoverageTests(CsvCase):
    def setUp(self):
        super().setUp()
        self.path = self.write(three_step_rows())
        self.rows, self.records = adapter.load_f1_frame_records(self.path)

    def test_exact_grouping_by_step_and_label(self):
        groups = adapter.group_by_sample(self.records)
        self.assertEqual(list(groups), [(RUN, REC, "1"), (RUN, REC, "2"), (RUN, REC, "3")])
        self.assertEqual([[r.frame_index for r in g] for g in groups.values()], [[1, 2, 3, 5], [6, 7, 8], [9, 10]])
        self.assertEqual([{r.label for r in g} for g in groups.values()],
                         [{"upright"}, {"forward_head"}, {"upright"}])

    def test_coverage_numerators_and_denominators(self):
        whole = cov.coverage_counts(self.records)
        # FS: 1,2,5,6,7,9 ; SH: 1,3,5,9 ; SO: all but 8,10 ; joint: 1,5,9
        self.assertEqual(whole, {"n_frames": 9, "FS": 6, "SH": 4, "SO": 7, "joint": 3})
        self.assertAlmostEqual(cov.percent(whole["SH"], whole["n_frames"]), 100 * 4 / 9)
        steps = cov.step_coverage(adapter.group_by_sample(self.records))
        self.assertEqual([s["counts"] for s in steps], [
            {"n_frames": 4, "FS": 3, "SH": 3, "SO": 4, "joint": 2},
            {"n_frames": 3, "FS": 2, "SH": 0, "SO": 2, "joint": 0},
            {"n_frames": 2, "FS": 1, "SH": 1, "SO": 1, "joint": 1},
        ])
        with self.assertRaises(ValueError):
            cov.percent(0, 0)

    def test_label_pooling_uses_frame_counts_not_mean_of_percentages(self):
        labels = cov.label_coverage(cov.step_coverage(adapter.group_by_sample(self.records)))
        upright = labels[0]
        self.assertEqual((upright["label"], upright["steps"]), ("upright", ["1", "3"]))
        self.assertEqual(upright["counts"], {"n_frames": 6, "FS": 4, "SH": 4, "SO": 5, "joint": 3})
        pooled = cov.percent(upright["counts"]["SH"], upright["counts"]["n_frames"])
        self.assertAlmostEqual(pooled, 100 * 4 / 6)
        self.assertNotAlmostEqual(pooled, (75.0 + 50.0) / 2)   # naive mean of step 1 / step 3 SH %

    def test_invalid_reason_distribution(self):
        reasons = cov.reason_distribution(self.records)
        self.assertEqual(reasons["SH"], {"left_hip_valid:false": 3, "lsh_valid:false": 1,
                                         "right_hip_valid:false": 3, "rsh_valid:false": 1})
        self.assertEqual(reasons["FS"], {"face_detected:false": 1, "lsh_valid:false": 1, "rsh_valid:false": 1})

    def test_hip_diagnostics(self):
        d = cov.hip_diagnostics(self.rows, self.records)
        self.assertEqual(d["left_hip_valid"], {"true": 6, "false": 3})
        self.assertEqual(d["right_hip_valid"], {"true": 6, "false": 3})
        self.assertEqual(d["both_hips_valid"], 5)
        self.assertEqual(d["both_shoulders_valid"], 7)
        self.assertEqual((d["SH_available"], d["SH_fail_hip_only"], d["SH_fail_shoulder_or_other_only"],
                          d["SH_fail_hip_and_other"]), (4, 3, 1, 1))
        with self.assertRaisesRegex(ValueError, "aligned"):
            cov.hip_diagnostics(self.rows, tuple(reversed(self.records)))

    def test_joint_vs_family_aggregation(self):
        samples = cov.aggregate_samples(adapter.group_by_sample(self.records))
        step2 = samples[1]
        self.assertEqual(step2["joint"]["defined"], [])
        self.assertEqual(set(step2["joint"]["undefined"].values()), {"no_supported_frames:joint"})
        self.assertEqual(step2["family"]["defined"], ["fs_x", "fs_y", "so_beta"])
        self.assertEqual(step2["family"]["undefined"], {"sh_x": "no_supported_frames:SH",
                                                         "sh_y": "no_supported_frames:SH"})
        self.assertEqual(step2["defined_only_under_family"], ["fs_x", "fs_y", "so_beta"])
        step1 = samples[0]
        self.assertTrue(step1["joint"]["all_five_defined"])
        self.assertEqual(step1["joint"]["feature_n_used"], dict.fromkeys(f1.F1_5_FEATURE_NAMES, 2))
        self.assertEqual(step1["family"]["feature_n_used"],
                         {"fs_x": 3, "fs_y": 3, "sh_x": 3, "sh_y": 3, "so_beta": 4})
        self.assertFalse(step1["family"]["defined_features_same_frames"])
        for s in samples:   # never 0 / sentinel for undefined values
            for policy in ("joint", "family"):
                for name in s[policy]["undefined"]:
                    self.assertIsNone(s[policy]["features"][name])

    def test_no_imputation(self):
        for rec in self.records:
            for name, value in rec.result.features.items():
                family = f1.F1_5_FEATURE_FAMILIES[name]
                self.assertEqual(value is None, not rec.result.family_available[family])
                if value is not None:
                    self.assertTrue(math.isfinite(value))
        self.assertIsNone(self.rows[1]["left_hip_x_px"])   # still empty after conversion

    def test_run_audit_invariants_pass_and_account_for_every_frame(self):
        audit = cov.run_audit(self.path)
        self.assertEqual([c for c in audit["invariants"] if not c[1]], [])
        self.assertEqual(audit["whole"]["n_frames"], 9)
        self.assertEqual(sum(s["counts"]["n_frames"] for s in audit["steps"]), 9)
        self.assertEqual(audit["identity"]["steps"], [("1", "upright"), ("2", "forward_head"), ("3", "upright")])

    def test_invariant_checker_detects_inconsistency(self):
        groups = adapter.group_by_sample(self.records)
        audit = cov.run_audit(self.path)
        broken_whole = dict(audit["whole"], joint=audit["whole"]["SH"] + 1)
        checks = cov.check_invariants(self.records, groups, broken_whole, audit["steps"], audit["labels"],
                                      audit["hips"], audit["samples"])
        failed = {name for name, ok, _ in checks if not ok}
        self.assertIn("recording: 0 <= joint <= min(FS, SH, SO)", failed)
        self.assertIn("per-step joint totals reconcile with recording", failed)
        dropped = dict(groups)
        dropped[(RUN, REC, "3")] = dropped[(RUN, REC, "3")][:1]
        checks = cov.check_invariants(self.records, dropped, audit["whole"], audit["steps"], audit["labels"],
                                      audit["hips"], audit["samples"])
        self.assertIn("every source frame in exactly one sample group", {n for n, ok, _ in checks if not ok})


class CliAndSourceTests(CsvCase):
    def test_source_csv_unchanged_and_cli_report(self):
        path = self.write(three_step_rows())
        with open(path, "rb") as f:
            before_bytes = f.read()
        before = cov.sha256_file(path)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cov.main([path, "--expected-sha256", before])
        self.assertEqual(code, 0)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before_bytes)
        report = stdout.getvalue()
        self.assertIn(cov.AUDIT_STATUS, report)
        self.assertIn(f"sha256 before: {before}", report)
        self.assertIn(f"sha256 after:  {before}", report)
        self.assertIn("GAP: no .provenance.json sidecar", report)
        self.assertIn("integrity invariants: ", report)
        self.assertEqual(sorted(os.listdir(self._tmp.name)), ["frames.csv"])   # nothing written

    def test_cli_rejects_unexpected_sha(self):
        path = self.write(three_step_rows())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cov.main([path, "--expected-sha256", "0" * 64]), 2)

    def test_cli_json_output(self):
        import json
        path = self.write(three_step_rows())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(cov.main([path, "--json"]), 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["status"], cov.AUDIT_STATUS)
        self.assertEqual(data["whole"]["joint"], 3)
        self.assertTrue(all(c["ok"] for c in data["invariants"]))

    def test_sidecar_provenance_mismatch_is_reported(self):
        import json
        path = self.write(three_step_rows())
        manifest = os.path.join(self._tmp.name, "analysis_manifest.json")
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "recording_id": REC, "analysis_run_id": RUN,
                       "dataset_role": "pilot", "outputs": []}, f)
        with open(path + ".provenance.json", "w", encoding="utf-8") as f:
            json.dump({"recording_id": REC, "analysis_run_id": RUN, "frames_sha256": "0" * 64,
                       "analysis_manifest": "analysis_manifest.json",
                       "analysis_manifest_sha256": cov.sha256_file(manifest)}, f)
        status = cov.sidecar_provenance(path, cov.sha256_file(path))
        self.assertEqual(status["dataset_role"], "pilot")
        self.assertIn("MISMATCH: sidecar frames_sha256 differs from source SHA-256", status["findings"])
        self.assertIn("MISMATCH: CSV not listed (name + SHA-256) in manifest frames outputs", status["findings"])


if __name__ == "__main__":
    unittest.main()
