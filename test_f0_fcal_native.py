"""Synthetic packet replay only. Never opens an SDK recording or model."""

from contextlib import contextmanager
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

import numpy as np

import capture_d455
from f1_csv_adapter import read_canonical_frame_rows
from f0_fcal_native import (
    REQUEST_INTERFACE, generate_evaluation_input, observation_from_results,
)
from research_recording import RGBDPacket
from rf_experiment import file_identity


def pin(path):
    return {k: v for k, v in file_identity(path).items() if k in ("path", "sha256")}


def write_json(path, value):
    Path(path).write_text(json.dumps(value), encoding="utf-8")


class SyntheticPackets:
    kind = "SYNTHETIC_STRUCTURAL_NOT_NATIVE_RECORDING"
    change_domain = False
    duplicate_time = False
    finish = True

    def __init__(self, path):
        self.completed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        for n in range(89):
            ts = n * 250
            if self.duplicate_time and n == 50:
                ts -= 250
            domain = "synthetic_other" if self.change_domain and n == 50 else "synthetic_clock"
            color = None if n == 48 else np.zeros((4, 6, 3), dtype=np.uint8)
            depth = np.zeros((4, 6), dtype=np.uint16) if n % 2 else None
            desc = lambda fmt: dict(frame_number=n+1, timestamp_ms=ts, timestamp_domain=domain,
                                    height=4, width=6, format=fmt)
            yield RGBDPacket(color, depth, dict(
                color=desc("bgr8") if color is not None else None,
                depth=desc("z16") if depth is not None else None,
                frameset_timestamp_ms=ts, frameset_timestamp_domain=domain,
                mediapipe_ts_ms=ts if color is not None else None,
                host_monotonic_ns=n, host_utc="synthetic-host-time"))
        self.completed = self.finish


@contextmanager
def synthetic_observer(model_dir):
    class Observer:
        kind = "SYNTHETIC_DETECTIONS_NO_MODEL"
        model_artifacts = {}

        def observe(self, packet):
            if packet.color_bgr is None:
                return observation_from_results(None, None, 0, 0)
            box = NS(origin_x=2, origin_y=0, width=2, height=1)
            face = NS(detections=[NS(bounding_box=box)])
            lm = [NS(x=0.2, y=0.75) for _ in range(25)]
            lm[12] = NS(x=0.8, y=0.75)
            return observation_from_results(face, NS(pose_landmarks=[lm]), 6, 4)
    yield Observer()


class NativeGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "SYN01.bag"
        self.raw.write_bytes(b"synthetic only; not a RealSense native file")
        self.markers = self.root / "SYN01_markers.csv"
        self.marks = [
            dict(recording_id="SYN01", frame_timestamp_ms=0, color_frame_number=1, phase="hold", step=1, label="upright"),
            dict(recording_id="SYN01", frame_timestamp_ms=10000, color_frame_number=41, phase="prep", step=2, label="transition"),
            dict(recording_id="SYN01", frame_timestamp_ms=11000, color_frame_number=45, phase="hold", step=2, label="body_forward"),
            dict(recording_id="SYN01", frame_timestamp_ms=21000, color_frame_number=85, phase="end", step=2, label="end")]
        self.camera = self.root / "SYN01_camera.json"
        self.cam = dict(recording_id="SYN01", subject="SYN-P01", round="1", record_file=self.raw.name,
                        capture_script_sha256=pin(capture_d455.__file__)["sha256"])
        self.request_path = self.root / "request.json"
        self.recording = dict(subject="SYN-P01", round="1", recording_id="SYN01",
            analysis_run_id="ar_SYN01", segments=[
                dict(session="S1", order=0, step=1, label="upright", hold_start_marker_index=0, hold_end_marker_index=1),
                dict(session="S1", order=1, step=2, label="body_forward", hold_start_marker_index=2, hold_end_marker_index=3)])
        self.request = dict(interface=REQUEST_INTERFACE, recordings=[self.recording],
            reference_keys={"SYN-P01": ["ar_SYN01", "SYN01", 1]}, participant_splits={"SYN-P01": "train"})

    def save(self):
        with self.markers.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.marks[0]))
            writer.writeheader()
            writer.writerows(self.marks)
        write_json(self.camera, self.cam)
        self.recording["sources"] = dict(raw=pin(self.raw), markers=pin(self.markers), capture=pin(self.camera))
        write_json(self.request_path, self.request)

    def run_generation(self, packet_factory=SyntheticPackets, suffix="output"):
        self.save()
        return generate_evaluation_input(self.request_path, request_sha256=pin(self.request_path)["sha256"],
            output_root=self.root / suffix, packet_factory=packet_factory, observer_factory=synthetic_observer)

    def test_all_packets_and_missing_streams_preserved_then_loader_connected(self):
        result = self.run_generation()
        self.assertEqual(result.status, "prepared", result.reasons)
        directory = self.root / "output/analysis/SYN01/ar_SYN01"
        inventory = json.loads((directory / "input_inventory.json").read_text(encoding="utf-8"))
        observations = [json.loads(line) for line in (directory / "all_observations.jsonl").read_text().splitlines()]
        self.assertEqual(len(inventory["frames"]), 89)
        self.assertEqual(len(observations), 89)
        self.assertEqual([r["frame_index"] for r in observations], list(range(1, 90)))
        self.assertIsNone(observations[48]["timing"]["color"])
        self.assertIsNone(observations[0]["timing"]["depth"])
        rows = read_canonical_frame_rows(str(directory / "f0_frames.csv"))
        self.assertEqual(len(rows), 80)  # Full holds, prep/trailing rows remain in JSONL.
        missing = next(r for r in rows if r["frame_index"] == 49)
        self.assertFalse(missing["face_detected"])
        self.assertIsNone(missing["face_area_px"])
        sample = result.loaded.samples[1]
        self.assertEqual(len(sample.input_indices), 40)
        self.assertEqual(len(sample.support_indices), 39)
        self.assertEqual(sample.label, "lean_forward")
        self.assertEqual(sample.reference_key, ("ar_SYN01", "SYN01", 1))
        self.assertTrue(sample.eligible)
        self.assertFalse(result.loaded.samples[0].eligible)
        self.assertEqual(result.loaded.evaluation["matrices"]["F0"].shape, (2, 6))
        self.assertEqual(pin(self.raw), self.recording["sources"]["raw"])

    def test_provenance_and_exact_clock_binding(self):
        result = self.run_generation()
        self.assertEqual(result.status, "prepared", result.reasons)
        directory = self.root / "output/analysis/SYN01/ar_SYN01"
        owner = json.loads((directory / "analysis_manifest.json").read_text())
        clock = json.loads((directory / "clock_evidence.json").read_text())
        self.assertEqual(owner["processing_settings"]["trim_end_s"], 0)
        self.assertEqual(owner["options"]["step_effective"], 1)
        self.assertEqual(owner["inputs"]["recording"]["sha256"], pin(self.raw)["sha256"])
        self.assertEqual(clock["domain"], "synthetic_clock")
        self.assertTrue(clock["same_clock"])
        self.assertIn("SYNTHETIC", clock["provenance"]["backend"]["reader"])
        self.assertEqual(clock["provenance"]["request"]["sha256"], pin(self.request_path)["sha256"])
        self.assertEqual(owner["outputs"][0]["sha256"], pin(directory / "f0_frames.csv")["sha256"])

    def test_missing_end_timestamp_does_not_open_reader_or_write(self):
        self.marks[-1]["frame_timestamp_ms"] = None
        def forbidden(path):
            self.fail("reader must not open without hold end timestamp")
        result = self.run_generation(forbidden)
        self.assertEqual(result.status, "unprocessed")
        self.assertIn("marker_device_timestamp_missing", result.reasons[0])
        self.assertFalse((self.root / "output").exists())

    def test_unknown_capture_clock_producer_is_not_inferred_from_timestamps(self):
        self.cam["capture_script_sha256"] = "0" * 64
        result = self.run_generation()
        self.assertEqual(result.status, "unprocessed")
        self.assertIn("marker_clock_producer_not_verified", result.reasons[0])
        self.assertFalse((self.root / "output").exists())

    def test_unmatched_marker_domain_change_nonmonotonic_and_incomplete_replay_block(self):
        classes = [type("ChangedDomain", (SyntheticPackets,), dict(change_domain=True)),
                   type("DuplicateTime", (SyntheticPackets,), dict(duplicate_time=True)),
                   type("Incomplete", (SyntheticPackets,), dict(finish=False))]
        for i, factory in enumerate(classes):
            with self.subTest(factory=factory):
                result = self.run_generation(factory, suffix=f"blocked{i}")
                self.assertEqual(result.status, "unprocessed")
                self.assertFalse((self.root / f"blocked{i}").exists())
        self.marks[-1]["frame_timestamp_ms"] = 21001
        result = self.run_generation(suffix="unmatched")
        self.assertIn("marker_not_bound_to_native_frame", result.reasons[0])
        self.assertFalse((self.root / "unmatched").exists())

    def test_hash_tamper_and_fixed_reference_do_not_fall_back(self):
        self.save()
        old_hash = pin(self.request_path)["sha256"]
        self.request_path.write_text(self.request_path.read_text() + " ")
        result = generate_evaluation_input(self.request_path, request_sha256=old_hash,
                                           output_root=self.root / "bad_hash")
        self.assertEqual(result.status, "unprocessed")
        self.assertFalse((self.root / "bad_hash").exists())
        self.request["reference_keys"]["SYN-P01"] = ["ar_SYN01", "SYN01", 2]
        result = self.run_generation()
        self.assertIn("fixed_first_P0_reference", result.reasons[0])
        self.assertFalse((self.root / "output").exists())


if __name__ == "__main__":
    unittest.main()
