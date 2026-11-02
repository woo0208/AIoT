"""Mock the real legacy record_phase loop; no device, GUI, or participant data."""

from contextlib import ExitStack
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np

import capture_d455 as capture
from analyze_d455 import load_markers


def frames(ts, number, domain="hardware_clock"):
    color = Mock()
    color.get_frame_number.return_value = number
    color.get_data.return_value = np.zeros((2, 2, 3), dtype=np.uint8)
    value = Mock()
    value.get_timestamp.return_value = ts
    value.get_frame_timestamp_domain.return_value = domain
    value.get_color_frame.return_value = color
    return value


class EndTimingTests(unittest.TestCase):
    def record(self, *, start_domain="hardware_clock", end_domain="hardware_clock", aborted=False):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            base = str(Path(tmp) / "SYN01")
            provenance = dict(start_time="synthetic", recording_id="SYN01",
                              sidecar_files={"camera": "SYN01_camera.json", "markers": "SYN01_markers.csv"},
                              capture_script_sha256="synthetic-producer-hash")
            intrinsics = NS(fx=1, fy=1)
            stream = Mock()
            stream.as_video_stream_profile.return_value = stream
            stream.get_intrinsics.return_value = intrinsics
            stream.get_extrinsics_to.return_value = NS(rotation=[0]*9, translation=[0]*3)
            device = Mock()
            device.first_depth_sensor.return_value.get_depth_scale.return_value = 0.001
            device.first_depth_sensor.return_value.get_option.return_value = 50
            device.get_info.return_value = "3-synthetic"
            device.supports.return_value = True
            profile = Mock()
            profile.get_device.return_value = device
            profile.get_stream.return_value = stream
            pipe = Mock()
            pipe.start.return_value = profile
            pipe.wait_for_frames.side_effect = [frames(1000, 1), frames(2000, 2, start_domain),
                                                frames(12000, 3, end_domain)]
            stack.enter_context(patch.object(capture, "reserve_capture", return_value=(base, provenance)))
            stack.enter_context(patch.object(capture.rs, "pipeline", return_value=pipe))
            stack.enter_context(patch.object(capture.rs, "align", return_value=Mock()))
            stack.enter_context(patch.object(capture, "make_config", return_value=Mock()))
            stack.enter_context(patch.object(capture, "intr_to_dict", return_value={"fx": 1, "fy": 1}))
            stack.enter_context(patch.object(capture, "make_display", return_value=np.zeros((2, 2, 3))))
            stack.enter_context(patch.object(capture.cv2, "imshow"))
            stack.enter_context(patch.object(capture.cv2, "waitKey", return_value=ord("q") if aborted else -1))
            stack.enter_context(patch.object(capture, "beep"))
            # Different cleanup wall time must never become a device timestamp.
            stack.enter_context(patch.object(capture.time, "time", side_effect=[0, 0, 10, 30, 99, 100]))
            capture.record_phase("SYN-P01", "1", {}, [("upright", 10)], "pilot")
            pipe.stop.assert_called_once()
            with Path(base + "_markers.csv").open(encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header, markers = reader.fieldnames, list(reader)
            timing = json.loads(Path(base + "_end_timing.json").read_text(encoding="utf-8"))
            camera = json.loads(Path(base + "_camera.json").read_text(encoding="utf-8"))
            parsed = load_markers(base + ".db3")
            return header, markers, timing, camera, parsed

    def test_normal_end_uses_actual_deadline_frameset_and_keeps_marker_header(self):
        header, markers, timing, camera, parsed = self.record()
        self.assertEqual(header, ["wall_time", "frame_timestamp_ms", "color_frame_number", "step",
                                 "phase", "label", "planned_sec", "distance_m", "distance_mode", "recording_id"])
        self.assertEqual(markers[-1]["frame_timestamp_ms"], "12000")
        self.assertEqual(markers[-1]["color_frame_number"], "3")
        self.assertEqual(float(markers[-1]["wall_time"]), 30)
        self.assertEqual(timing["status"], "recorded")
        self.assertEqual(timing["timestamp_domain"], "hardware_clock")
        self.assertEqual(timing["hold_start"]["frame_timestamp_ms"], 2000)
        self.assertEqual(timing["observed_end"]["frame_timestamp_ms"], 12000)
        self.assertEqual(timing["marker_index"], 2)
        self.assertEqual(camera["sidecar_files"]["end_timing"], "SYN01_end_timing.json")
        self.assertEqual(parsed[-1]["phase"], "end")
        self.assertEqual(parsed[-1]["ts"], 12000)

    def test_insufficient_or_changed_clock_leaves_end_unprocessed(self):
        for start, end, reason in ((None, "hardware_clock", "hold_start_clock_evidence_missing"),
                                   ("hardware_clock", None, "hold_end_clock_evidence_missing"),
                                   ("hardware_clock", "global_time", "hold_clock_domain_changed")):
            with self.subTest(start=start, end=end):
                _, markers, timing, _, parsed = self.record(start_domain=start, end_domain=end)
                self.assertEqual(timing["status"], "unprocessed")
                self.assertEqual(timing["reason"], reason)
                self.assertEqual(markers[-1]["frame_timestamp_ms"], "")
                self.assertEqual(markers[-1]["color_frame_number"], "")
                self.assertIsNone(timing["timestamp_domain"])
                self.assertFalse(any(m["phase"] == "end" for m in parsed))

    def test_operator_abort_does_not_reuse_last_frame_as_normal_end(self):
        _, markers, timing, _, _ = self.record(aborted=True)
        self.assertEqual(timing["status"], "unprocessed")
        self.assertEqual(timing["reason"], "normal_hold_end_event_not_observed")
        self.assertEqual(markers[-1]["label"], "aborted")
        self.assertEqual(markers[-1]["frame_timestamp_ms"], "")


if __name__ == "__main__":
    unittest.main()
