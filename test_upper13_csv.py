"""Synthetic CSV checks only; no D455 measurement or classification evidence."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import posture_geometry_probe as probe


class Upper13CSVTests(unittest.TestCase):
    def rows(self, landmarks, depth=None):
        return probe.upper13_csv_rows(
            landmarks, 100, 80, aligned_depth=depth, depth_scale_m=0.001,
            frame_index=7, device_timestamp_ms=12.5, mediapipe_timestamp_ms=13,
        )

    def test_pose_indices_coordinates_scores_and_existing_depth_sampler(self):
        landmarks = [SimpleNamespace(x=0.5, y=0.25, visibility=0.0, presence=0.8)
                     for _ in range(33)]
        depth = np.full((80, 100), 850, dtype=np.uint16)
        with patch.object(probe.geometry, "sample_aligned_depth_m",
                          wraps=probe.geometry.sample_aligned_depth_m) as sampler:
            rows = self.rows(landmarks, depth)
        self.assertEqual(sampler.call_count, 13)
        self.assertEqual([r["landmark_index"] for r in rows],
                         [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24])
        self.assertEqual([r["landmark_name"] for r in rows],
                         ["nose", "left_eye", "right_eye", "left_ear", "right_ear",
                          "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                          "left_wrist", "right_wrist", "left_hip", "right_hip"])
        for row in rows:
            self.assertEqual((row["x_px"], row["y_px"]), (50.0, 20.0))
            self.assertEqual((row["visibility"], row["presence"]), (0.0, 0.8))
            self.assertEqual((row["coordinate_valid"], row["depth_valid"]),
                             ("true", "true"))
            self.assertAlmostEqual(row["depth_m"], 0.85)

    def test_missing_invalid_coordinates_and_depth_are_explicit(self):
        for landmarks in (None, []):
            rows = self.rows(landmarks)
            self.assertEqual(len(rows), 13)
            for row in rows:
                for field in ("x_px", "y_px", "visibility", "presence", "depth_m"):
                    self.assertIsNone(row[field])
                self.assertEqual(row["coordinate_valid"], "false")
                self.assertEqual(row["depth_valid"], "false")
        landmarks = [SimpleNamespace(x=0.5, y=0.25) for _ in range(33)]
        landmarks[0].x = 1.0
        landmarks[2].y = float("nan")
        rows = self.rows(landmarks, np.zeros((80, 100), dtype=np.uint16))
        self.assertEqual(rows[0]["x_px"], 100.0)
        self.assertEqual(rows[0]["coordinate_valid"], "false")
        self.assertIsNone(rows[1]["y_px"])
        self.assertEqual(rows[1]["coordinate_valid"], "false")
        self.assertEqual(rows[2]["coordinate_valid"], "true")
        self.assertTrue(all(r["depth_m"] is None and r["depth_valid"] == "false"
                            for r in rows))
        self.assertIsNone(self.rows(landmarks, None)[2]["depth_m"])

    def test_new_csv_roundtrip_missing_rows_and_no_overwrite(self):
        self.assertEqual(probe._open_upper13_csv(None), (None, None))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upper13.csv"
            handle, writer = probe._open_upper13_csv(str(path))
            with handle:
                writer.writerows(self.rows(None))
            before = path.read_bytes()
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, list(probe.UPPER13_CSV_FIELDS))
                rows = list(reader)
            self.assertEqual(len(rows), 13)
            self.assertTrue(all(r["x_px"] == "" and r["depth_m"] == ""
                                and r["depth_valid"] == "false" for r in rows))
            self.assertTrue(all(r["frame_index"] == "7" for r in rows))
            with self.assertRaises(FileExistsError):
                probe._open_upper13_csv(str(path))
            self.assertEqual(path.read_bytes(), before)

    def test_cli_passes_separate_output_to_probe(self):
        self.assertIsNone(probe.parse_args([]).upper13_csv)
        with patch.object(probe, "run_probe") as run:
            probe.main([
                "--upper13-csv", "new-upper13.csv",
                "--session-meta-json", "session.json",
                "--camera-height-m", "1.25",
                "--chair-distance-m", "0.80",
                "--installation-angle-deg", "-5.0",
                "--lighting", "ceiling LED",
            ])
        self.assertEqual(run.call_args.kwargs["upper13_csv_path"], "new-upper13.csv")
        self.assertEqual(run.call_args.kwargs["session_meta_json_path"], "session.json")
        self.assertEqual(run.call_args.kwargs["camera_height_m"], 1.25)
        self.assertEqual(run.call_args.kwargs["chair_distance_m"], 0.80)
        self.assertEqual(run.call_args.kwargs["installation_angle_deg"], -5.0)
        self.assertEqual(run.call_args.kwargs["lighting"], "ceiling LED")
        self.assertIsNone(run.call_args.args[0])

    def test_session_metadata_records_automatic_manual_and_unknown_sources(self):
        intrinsics = SimpleNamespace(
            width=1280, height=720, fx=600.0, fy=601.0,
            ppx=640.0, ppy=360.0, model="brown", coeffs=[0.0] * 5,
        )

        class Stream:
            def __init__(self, width, height, fps):
                self._width, self._height, self._fps = width, height, fps

            def as_video_stream_profile(self):
                return self

            def width(self):
                return self._width

            def height(self):
                return self._height

            def fps(self):
                return self._fps

            def get_intrinsics(self):
                return intrinsics

        class Sensor:
            def __init__(self, values):
                self.values = values

            def supports(self, option):
                return option in self.values

            def get_option(self, option):
                return self.values[option]

        color_sensor = Sensor({"exposure": 156.0})
        depth_sensor = Sensor({"exposure": 8500.0, "gain": 16.0})
        device = SimpleNamespace(
            supports=lambda key: True,
            get_info=lambda key: {
                "name": "Intel RealSense D455", "serial": "D455-1",
                "firmware": "5.16.0",
            }[key],
            first_color_sensor=lambda: color_sensor,
            first_depth_sensor=lambda: depth_sensor,
        )
        streams = {
            "color": Stream(1280, 720, 15),
            "depth": Stream(848, 480, 15),
        }
        profile = SimpleNamespace(
            get_device=lambda: device,
            get_stream=lambda kind: streams[kind],
        )
        rs = SimpleNamespace(
            stream=SimpleNamespace(color="color", depth="depth"),
            camera_info=SimpleNamespace(
                name="name", serial_number="serial", firmware_version="firmware"
            ),
            option=SimpleNamespace(exposure="exposure", gain="gain"),
        )

        metadata = probe.build_upper13_session_metadata(
            profile,
            rs,
            "upper13.csv",
            camera_height_m=1.25,
            lighting="ceiling LED",
            started_at=datetime(2026, 10, 24, 14, 31, tzinfo=timezone.utc),
            session_id="upper13-session-fixed",
        )

        self.assertEqual(metadata["schema_version"],
                         "upper13-session-metadata/1.0.0")
        self.assertEqual(metadata["session_id"], "upper13-session-fixed")
        self.assertEqual(metadata["session_id_source"], "automatic_generated")
        self.assertEqual(metadata["upper13_csv"]["session_id"],
                         "upper13-session-fixed")
        self.assertEqual(metadata["camera"]["model"]["value"],
                         "Intel RealSense D455")
        self.assertEqual(metadata["streams"]["color"]["resolution"],
                         {"width": 1280, "height": 720})
        self.assertEqual(metadata["streams"]["depth"]["fps"], 15)
        self.assertEqual(metadata["intrinsics"]["color"]["value"]["fx"], 600.0)
        self.assertEqual(metadata["depth_alignment"], {
            "target": "color", "source": "automatic_configuration"
        })
        self.assertEqual(metadata["camera_controls"]["color"]["exposure"], {
            "value": 156.0, "source": "automatic_device_query"
        })
        self.assertEqual(metadata["camera_controls"]["color"]["gain"], {
            "value": None, "source": "unknown"
        })
        self.assertEqual(metadata["installation"]["camera_height_m"], {
            "value": 1.25, "source": "manual_cli"
        })
        self.assertEqual(metadata["installation"]["chair_distance_m"], {
            "value": None, "source": "unknown"
        })
        self.assertIn("installation.chair_distance_m",
                      metadata["provenance_unknown_reasons"])

    def test_session_metadata_json_roundtrip_and_no_overwrite(self):
        payload = {"session_id": {"value": "session-1", "source": "automatic_generated"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            probe.write_upper13_session_metadata(str(path), payload)
            before = path.read_bytes()
            self.assertEqual(json.loads(before), payload)
            with self.assertRaises(FileExistsError):
                probe.write_upper13_session_metadata(str(path), payload)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
