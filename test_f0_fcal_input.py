"""Only temporary synthetic CSV/markers/manifests. No device or model fitting."""

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from analyze_d455 import FRAME_FIELDS, FRAME_SCHEMA_VERSION, write_frames_csv
from f0_fcal_input import INTERFACE, load_evaluation_input
from f1_csv_adapter import read_canonical_frame_rows


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value), encoding="utf-8")


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "session_reference.json"
        self.entries = []
        for i, (label, session) in enumerate((("upright", "S1"), ("body_forward", "S1"), ("lean_left", "S2"))):
            rid, run = f"synthetic_r{i}", f"ar_synthetic_{i}"
            directory = self.root / "analysis" / rid / run
            directory.mkdir(parents=True)
            raw = self.root / (rid + ".bag")
            raw.write_bytes(b"synthetic identity bytes; not an SDK recording")
            markers = self.root / (rid + "_markers.csv")
            with markers.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("recording_id", "frame_timestamp_ms", "phase", "step", "label"))
                writer.writeheader()
                writer.writerows([
                    dict(recording_id=rid, frame_timestamp_ms=10000, phase="hold", step=1, label=label),
                    dict(recording_id=rid, frame_timestamp_ms=20000, phase="end", step=1, label="end")])
            camera = self.root / (rid + "_camera.json")
            dump(camera, dict(recording_id=rid, subject="SYN01", round=str(i+1)))
            frames = directory / "synthetic_frames.csv"
            rows = []
            inventory = []
            for n in range(61):
                ts = 10000 + n * 10000 / 60
                row = dict.fromkeys(FRAME_FIELDS)
                row.update(frame_schema_version=FRAME_SCHEMA_VERSION, subject="SYN01", round=str(i+1),
                           recording_id=rid, analysis_run_id=run, step="1", label=label,
                           frame_index=n+1, ts_ms=ts, t=(ts-10000)/1000,
                           face_x=100+i*30, face_y=100, face_w_px=20, face_h_px=20,
                           face_area_px=400, lsh_x=50, lsh_y=200, rsh_x=200, rsh_y=200,
                           face_detected=True, lsh_valid=True, rsh_valid=True,
                           face_depth_source="missing", shoulder_depth_source="missing")
                rows.append(row)
                inventory.append(dict(frame_index=n+1, ts_ms=ts))
            write_frames_csv(frames, rows)
            clock = self.root / (rid + "_clock.json")
            dump(clock, dict(recording_id=rid, raw_sha256=digest(raw), markers_sha256=digest(markers),
                             frame_field="ts_ms", marker_field="frame_timestamp_ms", unit="ms",
                             same_clock=True, domain="synthetic_device_clock"))
            index = self.root / (rid + "_inventory.json")
            dump(index, dict(recording_id=rid, raw_sha256=digest(raw), clock_domain="synthetic_device_clock",
                             scope="all_delivered_frames", interval_ms=[10000, 20000], frames=inventory))
            owner = directory / "analysis_manifest.json"
            dump(owner, dict(status="completed", analysis_mode="extract_raw", recording_id=rid,
                             analysis_run_id=run, processing_settings=dict(raw_extraction_applied=True,
                                                                         trim_start_s=0, trim_end_s=0),
                             options=dict(step_effective=1),
                             inputs={name: dict(path=str(path), sha256=digest(path)) for name, path in
                                     (("recording", raw), ("markers", markers), ("capture_metadata", camera))},
                             outputs=[dict(kind="frames", path=str(frames), sha256=digest(frames))]))
            sources = {name: dict(path=str(path.relative_to(self.root)), sha256=digest(path)) for name, path in
                       (("raw", raw), ("markers", markers), ("capture", camera), ("frames", frames),
                        ("analysis", owner), ("clock_evidence", clock), ("input_inventory", index))}
            self.entries.append(dict(subject="SYN01", recording_id=rid, analysis_run_id=run, round=str(i+1),
                                     step=1, order=i, label=label, session=session,
                                     hold_start_marker_index=0, hold_end_marker_index=1, sources=sources))
        self.data = dict(interface=INTERFACE, segments=self.entries,
                         reference_keys={"SYN01": [self.entries[0]["analysis_run_id"], self.entries[0]["recording_id"], 1]},
                         participant_splits={"SYN01": "train"})

    def change_json(self, index, kind, modify):
        spec = self.entries[index]["sources"][kind]
        path = self.root / spec["path"]
        value = json.loads(path.read_text(encoding="utf-8"))
        modify(value)
        dump(path, value)
        spec["sha256"] = digest(path)

    def load(self):
        dump(self.path, self.data)
        return load_evaluation_input(self.path, manifest_sha256=digest(self.path))


class InputLoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = Fixture(self.tmp.name)

    def test_pinned_sources_boundary_keys_s2_reference_and_adapter(self):
        f = self.fixture
        f.data["segments"] = list(reversed(f.entries))
        result = f.load()
        self.assertEqual(result.status, "prepared")
        self.assertFalse(result.issues)
        by_order = {s.sample_key[0]: s for s in result.samples}
        target = by_order["ar_synthetic_2"]
        self.assertEqual(target.reference_key, tuple(f.data["reference_keys"]["SYN01"]))
        self.assertEqual(target.f_cal[0], 60)
        self.assertEqual(target.label, "lean_left")
        self.assertEqual(len(target.input_indices), 60)
        self.assertIn(1, target.input_indices)
        self.assertNotIn(61, target.input_indices)
        self.assertEqual(result.evaluation["matrices"]["F0"].shape, (3, 6))
        self.assertEqual(tuple(result.evaluation["y"]), (0, 5, 3))
        self.assertEqual(int(result.evaluation["common_mask"].sum()), 2)
        self.assertTrue(result.evaluation["reference_mask"][0])
        self.assertFalse(result.evaluation["train_mask"][0])
        self.assertTrue(result.source_artifacts)

    def test_trim_and_stride_are_never_full_input(self):
        for field in ("trim", "stride"):
            with self.subTest(field=field):
                f = Fixture(Path(self.tmp.name) / field)
                if field == "trim":
                    f.change_json(1, "analysis", lambda a: a["processing_settings"].update(trim_end_s=0.5))
                else:
                    f.change_json(1, "analysis", lambda a: a["options"].update(step_effective=2))
                result = f.load()
                self.assertEqual(result.samples[1].status, "unprocessed")
                self.assertFalse(result.samples[1].eligible)
                self.assertIn("not_full_denominator", result.issues[0]["reason"])

    def test_csv_cannot_stand_in_for_delivered_inventory(self):
        f = self.fixture
        f.change_json(1, "input_inventory", lambda inv: inv["frames"].pop(5))
        result = f.load()
        self.assertEqual(result.samples[1].status, "unprocessed")
        self.assertIn("inventory_mismatch", result.issues[0]["reason"])
        self.assertTrue(result.samples[2].eligible)

    def test_invalid_observations_remain_in_actual_input_denominator(self):
        f = self.fixture
        spec = f.entries[1]["sources"]["frames"]
        path = f.root / spec["path"]
        rows = read_canonical_frame_rows(str(path))
        rows = [dict(row, lsh_valid=False) if i >= 29 else row for i, row in enumerate(rows)]
        # The existing writer creates a fresh output path; the fixture alone
        # replaces its temporary synthetic source for this missingness case.
        replacement = path.with_name("replacement_frames.csv")
        write_frames_csv(replacement, rows)
        spec.update(path=str(replacement.relative_to(f.root)), sha256=digest(replacement))
        f.change_json(1, "analysis", lambda a: a["outputs"][0].update(
            path=str(replacement), sha256=spec["sha256"]))
        result = f.load()
        self.assertEqual(len(result.samples[1].input_indices), 60)
        self.assertEqual(len(result.samples[1].support_indices), 29)
        self.assertAlmostEqual(result.samples[1].coverage, 29/60)
        self.assertEqual(result.samples[1].status, "ineligible")

    def test_missing_clock_session_or_reference_is_unprocessed(self):
        f = self.fixture
        del f.entries[1]["sources"]["clock_evidence"]
        del f.entries[2]["session"]
        result = f.load()
        self.assertTrue(all(s.status == "unprocessed" for s in result.samples[1:]))
        f.data["reference_keys"] = {}
        result = f.load()
        self.assertTrue(all(s.status == "unprocessed" for s in result.samples))
        self.assertTrue(all(s.reference_key is None for s in result.samples))

    def test_missing_end_timestamp_blocks_reference_and_no_replacement(self):
        f = self.fixture
        spec = f.entries[0]["sources"]["markers"]
        path = f.root / spec["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("20000,end", ",end"), encoding="utf-8")
        spec["sha256"] = digest(path)
        f.change_json(0, "analysis", lambda a: a["inputs"]["markers"].update(sha256=spec["sha256"]))
        result = f.load()
        self.assertIn("hold_marker_device_timestamp_missing", result.issues[0]["reason"])
        self.assertTrue(all(s.status == "unprocessed" for s in result.samples))
        self.assertTrue(all(not s.eligible for s in result.samples))
        self.assertTrue(all(s.reference_key == tuple(f.data["reference_keys"]["SYN01"]) for s in result.samples))

    def test_manifest_hash_and_source_hash_are_pinned(self):
        f = self.fixture
        dump(f.path, f.data)
        result = load_evaluation_input(f.path)
        self.assertIsNone(result.evaluation)
        self.assertIn("manifest_hash_missing", result.issues[0]["reason"])
        path = f.root / f.entries[1]["sources"]["frames"]["path"]
        with path.open("a", encoding="utf-8") as stream:
            stream.write("tampered")
        result = f.load()
        self.assertEqual(result.samples[1].status, "unprocessed")
        self.assertIn("SHA-256 mismatch", result.issues[0]["reason"])

    def test_later_p0_cannot_be_substituted(self):
        f = self.fixture
        # Wrong reference is rejected before any evaluation/model operation.
        f.data["reference_keys"]["SYN01"] = [f.entries[2]["analysis_run_id"], f.entries[2]["recording_id"], 1]
        result = f.load()
        self.assertEqual(result.status, "unprocessed")
        self.assertIsNone(result.evaluation)
        self.assertIn("first P0", result.issues[-1]["reason"])


if __name__ == "__main__":
    unittest.main()
