import csv
import hashlib
import io
import math
import os
from pathlib import Path
import tempfile
import types
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import numpy as np

import analyze_d455 as analysis


FROZEN_LEGACY_FIELDS = (
    "subject", "round", "step", "label", "t", "ts_ms",
    "face_x", "face_y", "face_w_px", "face_h_px", "face_area_px", "face_score",
    "z_face_m", "face_size_cm2", "oval_area_px", "oval_size_cm2", "ipd_px", "ipd_cm",
    "box_to_oval", "lsh_x", "lsh_y", "rsh_x", "rsh_y", "lsh_vis", "rsh_vis",
    "z_lsh_m", "z_rsh_m", "z_sh_m", "theta1_deg", "theta2_deg", "theta3_deg",
)
FROZEN_EXTENSION_FIELDS = (
    "frame_schema_version", "recording_id", "analysis_run_id", "frame_index",
    "color_frame_number", "depth_frame_number", "mediapipe_ts_ms", "face_depth_source",
    "face_detected", "face_mesh_detected", "pose_detected", "face_depth_valid",
    "lsh_valid", "rsh_valid", "lsh_depth_valid", "rsh_depth_valid", "shoulder_depth_source",
    "left_hip_x_px", "left_hip_y_px", "left_hip_depth_m", "left_hip_visibility",
    "left_hip_valid", "left_hip_depth_valid", "right_hip_x_px", "right_hip_y_px",
    "right_hip_depth_m", "right_hip_visibility", "right_hip_valid", "right_hip_depth_valid",
)
FROZEN_FRAME_FIELDS = FROZEN_LEGACY_FIELDS + FROZEN_EXTENSION_FIELDS
FROZEN_BOOL_FIELDS = (
    "face_detected", "face_mesh_detected", "pose_detected", "face_depth_valid",
    "lsh_valid", "rsh_valid", "lsh_depth_valid", "rsh_depth_valid",
    "left_hip_valid", "left_hip_depth_valid", "right_hip_valid", "right_hip_depth_valid",
)


def canonical_row(frame_index=1, **overrides):
    row = {
        "subject": "P03", "round": "1", "step": 1, "label": "upright", "t": 2.0, "ts_ms": 2000.0,
        "frame_schema_version": "frames-schema/1.0.0", "recording_id": "recording_test",
        "analysis_run_id": "ar_test", "frame_index": frame_index, "color_frame_number": 101,
        "depth_frame_number": 201, "mediapipe_ts_ms": 2000, "face_depth_source": "missing",
        "shoulder_depth_source": "missing",
    }
    row.update({field: False for field in FROZEN_BOOL_FIELDS})
    row.update(overrides)
    return row


class FrameSchemaTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.out = self.root / "analysis"
        self.data = self.root / "data"
        self.out.mkdir(); self.data.mkdir()
        self.stack.enter_context(patch.object(analysis, "OUT_DIR", str(self.out)))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))

    def _csv_path(self, name="frames.csv"):
        return self.root / name

    def _read_raw(self, path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return tuple(reader.fieldnames or ()), list(reader)

    def _write_raw(self, path, header, rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

    def _recording(self):
        path = self.data / "P03_r1_test.bag"
        path.write_bytes(b"synthetic")
        Path(str(path.with_suffix("")) + "_markers.csv").write_text(
            "frame_timestamp_ms,phase,label,step\n"
            "0,hold,upright,1\n"
            "30000,end,end,\n", encoding="utf-8")
        return str(path)

    def _provenance(self, recording_id="recording_test", analysis_run_id="ar_test"):
        return {
            "recording_id": recording_id,
            "analysis_run_id": analysis_run_id,
            "processing_settings": analysis.processing_settings(False),
            "models": [{"role": role, "used_in_this_run": False} for role in ("face", "mesh", "pose")],
            "inference_performed": False,
            "playback_calibration": None,
        }

    def _extract(self, frame_specs, pose=None, face=False, mesh=False, step=1, depth=None,
                 recording_id="recording_test", analysis_run_id="ar_test", image_shape=(20, 20)):
        ns = types.SimpleNamespace
        image_height, image_width = image_shape
        path = self._recording()
        models = {role: role + ".model" for role in ("face", "mesh", "pose")}
        face_det, mesh_det, pose_det = Mock(), Mock(), Mock()
        if face:
            face_det.detect.return_value = ns(detections=[ns(
                bounding_box=ns(origin_x=4, origin_y=2, width=8, height=8), categories=[ns(score=.95)])])
        else:
            face_det.detect.return_value = ns(detections=[])
        if mesh:
            landmarks = [ns(x=.5, y=.5) for _ in range(474)]
            for index, (x, y) in zip(analysis.FACE_OVAL[:4], ((.25, .25), (.75, .25), (.75, .75), (.25, .75))):
                landmarks[index] = ns(x=x, y=y)
            landmarks[analysis.IRIS_L], landmarks[analysis.IRIS_R] = ns(x=.4, y=.5), ns(x=.6, y=.5)
            mesh_det.detect_for_video.return_value = ns(face_landmarks=[landmarks])
        else:
            mesh_det.detect_for_video.return_value = ns(face_landmarks=[])
        pose_det.detect_for_video.return_value = ns(pose_landmarks=[] if pose is None else [pose])

        option = lambda **kwargs: ns(**kwargs)
        vision = ns(
            FaceDetector=ns(create_from_options=Mock(return_value=face_det)),
            FaceDetectorOptions=lambda **kw: ns(running_mode="IMAGE", min_suppression_threshold=.3, **kw),
            FaceLandmarker=ns(create_from_options=Mock(return_value=mesh_det)), FaceLandmarkerOptions=option,
            PoseLandmarker=ns(create_from_options=Mock(return_value=pose_det)), PoseLandmarkerOptions=option,
            RunningMode=ns(VIDEO="VIDEO"),
        )
        mpt = ns(BaseOptions=option)
        intr = ns(width=image_width, height=image_height, fx=100., fy=100.,
                  ppx=image_width / 2, ppy=image_height / 2, model="test", coeffs=[0.] * 5)
        profile, pipe, rs = Mock(), Mock(), Mock()
        profile.get_device.return_value.first_depth_sensor.return_value.get_depth_scale.return_value = .001
        profile.get_device.return_value.as_playback.return_value.get_duration.return_value.total_seconds.return_value = 30.
        profile.get_stream.return_value.as_video_stream_profile.return_value.get_intrinsics.return_value = intr
        pipe.start.return_value = profile
        rs.pipeline.return_value = pipe
        rs.config.return_value = Mock()
        rs.stream = ns(color="color")
        def aligned_frames(frames):
            aligned = Mock()
            aligned.get_color_frame.return_value.get_data.return_value = frames.get_color_frame().get_data()
            aligned.get_depth_frame.return_value.get_data.return_value = frames.get_depth_frame().get_data()
            aligned.get_color_frame.return_value.get_frame_number.return_value = 900001
            aligned.get_depth_frame.return_value.get_frame_number.return_value = 900002
            return aligned
        rs.align.return_value.process.side_effect = aligned_frames
        depth_image = np.full(image_shape, 1000, dtype=np.uint16) if depth is None else depth

        def make_frame(ts, color_number, depth_number):
            frame = Mock()
            frame.get_timestamp.return_value = ts
            frame.get_color_frame.return_value.get_frame_number.return_value = color_number
            frame.get_depth_frame.return_value.get_frame_number.return_value = depth_number
            frame.get_color_frame.return_value.get_data.return_value = np.zeros(
                (image_height, image_width, 3), dtype=np.uint8)
            frame.get_depth_frame.return_value.get_data.return_value = depth_image
            return frame

        pipe.try_wait_for_frames.side_effect = [
            (True, make_frame(ts, cn, dn)) for ts, cn, dn in frame_specs
        ] + [(False, None)]
        modules = {
            "mediapipe": ns(Image=option, ImageFormat=ns(SRGB="SRGB")),
            "pyrealsense2": rs,
            "mediapipe.tasks": ns(python=mpt),
            "mediapipe.tasks.python": ns(vision=vision),
        }
        real_import = __import__
        def fake_import(name, *args, **kwargs):
            return modules[name] if name in modules else real_import(name, *args, **kwargs)
        provenance = self._provenance(recording_id, analysis_run_id)
        with patch("builtins.__import__", side_effect=fake_import):
            rows = analysis.process_recording(path, models, step, provenance=provenance)
        return rows, provenance, (face_det, mesh_det, pose_det)

    def test_exact_frozen_60_field_header_and_order(self):
        self.assertEqual(len(FROZEN_FRAME_FIELDS), 60)
        self.assertEqual(analysis.FRAME_FIELDS, FROZEN_FRAME_FIELDS)
        path = self._csv_path()
        analysis.write_frames_csv(path, [canonical_row()])
        header, _ = self._read_raw(path)
        self.assertEqual(header, FROZEN_FRAME_FIELDS)

    def test_fields_are_unique_legacy_prefix_exact_and_no_arm_columns(self):
        self.assertEqual(len(set(FROZEN_FRAME_FIELDS)), 60)
        self.assertEqual(analysis.FRAME_FIELDS[:31], FROZEN_LEGACY_FIELDS)
        self.assertFalse(any("elbow" in field or "wrist" in field for field in analysis.FRAME_FIELDS))

    def test_writer_boolean_missing_enum_and_unknown_field_contract(self):
        path = self._csv_path()
        row = canonical_row(face_detected=True, face_depth_valid=True, face_depth_source="bbox_roi",
                            left_hip_x_px=None, left_hip_depth_m=None)
        analysis.write_frames_csv(path, [row])
        _, rows = self._read_raw(path)
        raw = rows[0]
        self.assertEqual(raw["face_detected"], "true")
        self.assertEqual(raw["pose_detected"], "false")
        self.assertEqual(raw["face_x"], "")
        self.assertEqual(raw["left_hip_x_px"], "")
        self.assertEqual(raw["left_hip_depth_m"], "")
        self.assertNotIn(raw["left_hip_x_px"], ("None", "nan", "0", "-1"))
        with self.assertRaisesRegex(ValueError, "invalid canonical face_depth_source"):
            analysis.write_frames_csv(path, [canonical_row(face_depth_source="unknown_legacy")])
        with self.assertRaisesRegex(ValueError, "invalid canonical shoulder_depth_source"):
            analysis.write_frames_csv(path, [canonical_row(shoulder_depth_source="arbitrary")])
        with self.assertRaisesRegex(ValueError, "unexpected canonical frame fields"):
            analysis.write_frames_csv(path, [dict(canonical_row(), left_elbow_x_px=1)])
        with self.assertRaisesRegex(ValueError, "invalid canonical boolean"):
            analysis.write_frames_csv(path, [canonical_row(face_detected=1)])

    def test_nullable_canonical_booleans_round_trip_without_becoming_false(self):
        path = self._csv_path()
        row = canonical_row(face_detected=True, face_mesh_detected=False, pose_detected=None,
                            left_hip_valid=None)
        analysis.write_frames_csv(path, [row])
        _, raw_rows = self._read_raw(path)
        self.assertEqual(raw_rows[0]["face_detected"], "true")
        self.assertEqual(raw_rows[0]["face_mesh_detected"], "false")
        self.assertEqual(raw_rows[0]["pose_detected"], "")
        self.assertEqual(raw_rows[0]["left_hip_valid"], "")
        loaded = analysis.load_frames_csv([], paths=[str(path)])[0]
        self.assertIs(loaded["face_detected"], True)
        self.assertIs(loaded["face_mesh_detected"], False)
        self.assertIsNone(loaded["pose_detected"])
        self.assertIsNone(loaded["left_hip_valid"])

    def test_writer_rejects_bad_identity_frame_index_duplicate_and_nonfinite(self):
        path = self._csv_path()
        for row, message in (
            (canonical_row(recording_id=""), "recording_id"),
            (canonical_row(analysis_run_id=""), "analysis_run_id"),
            (canonical_row(frame_schema_version="frames-schema/9.9.9"), "schema version"),
            (canonical_row(frame_index=0), "frame_index"),
            (canonical_row(left_hip_visibility=float("nan")), "non-finite"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    analysis.write_frames_csv(path, [row])
        with self.assertRaisesRegex(ValueError, "duplicate canonical frame key"):
            analysis.write_frames_csv(path, [canonical_row(), canonical_row()])
        with self.assertRaisesRegex(ValueError, "inconsistent canonical frame identity"):
            analysis.write_frames_csv(path, [canonical_row(1), canonical_row(2, analysis_run_id="ar_other")])

    def test_canonical_reader_strict_boolean_header_enum_numeric_and_roundtrip(self):
        path = self._csv_path()
        row = canonical_row(face_detected=True, left_hip_valid=True, left_hip_x_px=0.0,
                            face_depth_source="bbox_roi", shoulder_depth_source="left_only")
        analysis.write_frames_csv(path, [row])
        loaded = analysis.load_frames_csv([], paths=[str(path)])[0]
        self.assertIs(loaded["face_detected"], True)
        self.assertIs(loaded["pose_detected"], False)
        self.assertEqual(loaded["left_hip_x_px"], 0.0)
        self.assertEqual(loaded["frame_schema_version"], "frames-schema/1.0.0")
        header, raw_rows = self._read_raw(path)
        for field, value, message in (
            ("face_detected", "TRUE", "boolean"),
            ("face_depth_source", "unknown_legacy", "face_depth_source"),
            ("left_hip_x_px", "nan", "non-finite"),
        ):
            with self.subTest(field=field):
                raw_rows[0][field] = value
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=header); writer.writeheader(); writer.writerows(raw_rows)
                with self.assertRaisesRegex(ValueError, message):
                    analysis.load_frames_csv([], paths=[str(path)])
                analysis.write_frames_csv(path, [row])
                header, raw_rows = self._read_raw(path)
        bad_header = list(header); bad_header[-1], bad_header[-2] = bad_header[-2], bad_header[-1]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=bad_header); writer.writeheader()
        with self.assertRaisesRegex(ValueError, "header mismatch"):
            analysis.load_frames_csv([], paths=[str(path)])

    def test_canonical_frame_index_writer_reader_writer_round_trip(self):
        first_path = self._csv_path("first.csv")
        second_path = self._csv_path("second.csv")
        analysis.write_frames_csv(first_path, [canonical_row(frame_index=7)])
        loaded = analysis.load_frames_csv([], paths=[str(first_path)])[0]
        self.assertIs(type(loaded["frame_index"]), int)
        self.assertEqual(loaded["frame_index"], 7)
        analysis.write_frames_csv(second_path, [loaded])
        loaded_again = analysis.load_frames_csv([], paths=[str(second_path)])[0]
        self.assertEqual(loaded_again, loaded)

    def test_canonical_reader_rejects_invalid_frame_index_values(self):
        path = self._csv_path()
        analysis.write_frames_csv(path, [canonical_row()])
        header, raw_rows = self._read_raw(path)
        for value, message in (
            ("", "missing canonical frame_index"),
            ("0", "invalid canonical frame_index"),
            ("-1", "invalid canonical frame_index"),
            ("1.5", "invalid canonical frame_index"),
            ("not-a-number", "invalid canonical frame_index"),
            ("nan", "non-finite canonical value frame_index"),
            ("inf", "non-finite canonical value frame_index"),
        ):
            with self.subTest(value=value):
                raw_rows[0]["frame_index"] = value
                self._write_raw(path, header, raw_rows)
                with self.assertRaisesRegex(ValueError, message):
                    analysis.load_frames_csv([], paths=[str(path)])

    def test_canonical_reader_rejects_wrong_schema_empty_ids_and_non_numeric(self):
        path = self._csv_path()
        analysis.write_frames_csv(path, [canonical_row()])
        header, original_rows = self._read_raw(path)
        for field, value, message in (
            ("frame_schema_version", "frames-schema/9.9.9", "schema version"),
            ("recording_id", "", "recording_id"),
            ("analysis_run_id", "", "analysis_run_id"),
            ("left_hip_x_px", "not-a-number", "invalid canonical numeric left_hip_x_px"),
        ):
            with self.subTest(field=field):
                rows = [dict(original_rows[0])]
                rows[0][field] = value
                self._write_raw(path, header, rows)
                with self.assertRaisesRegex(ValueError, message):
                    analysis.load_frames_csv([], paths=[str(path)])

    def test_canonical_reader_rejects_mixed_recording_and_analysis_run_ids(self):
        path = self._csv_path()
        analysis.write_frames_csv(path, [canonical_row(1), canonical_row(2)])
        header, original_rows = self._read_raw(path)
        for field, value in (("recording_id", "recording_other"),
                             ("analysis_run_id", "ar_other")):
            with self.subTest(field=field):
                rows = [dict(row) for row in original_rows]
                rows[1][field] = value
                self._write_raw(path, header, rows)
                with self.assertRaisesRegex(ValueError, "inconsistent canonical frame identity"):
                    analysis.load_frames_csv([], paths=[str(path)])

    def test_legacy_reader_regression_remains_name_based_and_permissive(self):
        path = self._csv_path("legacy.csv")
        analysis.write_csv(path, [{"subject": "P01", "round": "1", "step": "2", "label": "upright",
                                   "face_area_px": "100", "custom_legacy": "value", "z_face_m": ""}])
        loaded = analysis.load_frames_csv([], paths=[str(path)])[0]
        self.assertEqual(loaded["subject"], "P01")
        self.assertEqual(loaded["step"], "2")
        self.assertEqual(loaded["face_area_px"], 100.0)
        self.assertEqual(loaded["custom_legacy"], "value")
        self.assertIsNone(loaded["z_face_m"])

    def test_normal_bilateral_hip_raw_observation(self):
        ns = types.SimpleNamespace
        pose = [ns(x=.5, y=.5, visibility=.5) for _ in range(33)]
        pose[11], pose[12] = ns(x=.25, y=.8, visibility=.9), ns(x=.75, y=.8, visibility=.8)
        pose[23], pose[24] = ns(x=.2, y=.3, visibility=.7), ns(x=.8, y=.7, visibility=.6)
        rows, _, _ = self._extract([(2000., 101, 201)], pose=pose)
        row = rows[0]
        self.assertNotIn("theta1_deg", row)
        self.assertEqual((row["left_hip_x_px"], row["left_hip_y_px"]), (4., 6.))
        self.assertEqual((row["right_hip_x_px"], row["right_hip_y_px"]), (16., 14.))
        self.assertEqual((row["left_hip_depth_m"], row["right_hip_depth_m"]), (1., 1.))
        self.assertEqual((row["left_hip_visibility"], row["right_hip_visibility"]), (.7, .6))
        self.assertIs(row["left_hip_valid"], True); self.assertIs(row["right_hip_valid"], True)
        self.assertIs(row["left_hip_depth_valid"], True); self.assertIs(row["right_hip_depth_valid"], True)

    def test_hip_geometry_and_depth_use_non_square_dimensions_and_shared_six_pixel_roi(self):
        ns = types.SimpleNamespace
        image_shape = (32, 48)
        pose = [ns(x=.5, y=.5, visibility=.5) for _ in range(33)]
        pose[11], pose[12] = ns(x=.3, y=.3, visibility=.9), ns(x=.7, y=.3, visibility=.8)
        pose[23], pose[24] = ns(x=.25, y=.375, visibility=.7), ns(x=.75, y=.6875, visibility=.6)
        depth = np.random.default_rng(42).integers(1, 5000, size=image_shape, dtype=np.uint16)
        expected_left = float(np.median(depth[6:18, 6:18])) * .001
        expected_right = float(np.median(depth[16:28, 30:42])) * .001
        self.assertNotEqual(expected_left, expected_right)
        with patch.object(analysis, "median_depth", wraps=analysis.median_depth) as median:
            rows, _, _ = self._extract([(2000., 101, 201)], pose=pose, depth=depth,
                                       image_shape=image_shape)
        row = rows[0]
        self.assertEqual((row["left_hip_x_px"], row["left_hip_y_px"]), (12., 12.))
        self.assertEqual((row["right_hip_x_px"], row["right_hip_y_px"]), (36., 22.))
        self.assertEqual(row["left_hip_depth_m"], expected_left)
        self.assertEqual(row["right_hip_depth_m"], expected_right)
        self.assertEqual(median.call_args_list[-2].args, (depth, 6., 6., 18., 18., .001))
        self.assertEqual(median.call_args_list[-1].args, (depth, 30., 16., 42., 28., .001))

    def test_hip_in_frame_boundaries_and_invalid_cases_skip_depth(self):
        ns = types.SimpleNamespace
        depth = np.full((20, 20), 1000, dtype=np.uint16)
        invalid = [(-.01, .5), (1., .5), (.5, 1.), (float("nan"), .5)]
        with patch.object(analysis, "median_depth", wraps=analysis.median_depth) as median:
            for x, y in invalid:
                with self.subTest(x=x, y=y):
                    result = analysis.hip_observation(ns(x=x, y=y, visibility=.4), 20, 20, depth, .001)
                    self.assertEqual(result[:3], (None, None, None))
                    self.assertEqual(result[3:], (.4, False, False))
            self.assertEqual(median.call_count, 0)
            result = analysis.hip_observation(ns(x=0., y=.5, visibility=.9), 20, 20, depth, .001)
            self.assertEqual(result[:2], (0., 10.))
            self.assertEqual(result[2], 1.)
            self.assertEqual(result[3:], (.9, True, True))
            self.assertEqual(median.call_count, 1)

    def test_pose_missing_sets_canonical_false_and_missing_states(self):
        rows, _, _ = self._extract([(2000., 101, 201)], pose=None)
        row = rows[0]
        self.assertIs(row["pose_detected"], False)
        for field in ("lsh_valid", "rsh_valid", "lsh_depth_valid", "rsh_depth_valid",
                      "left_hip_valid", "right_hip_valid", "left_hip_depth_valid", "right_hip_depth_valid"):
            self.assertIs(row[field], False, field)
        self.assertEqual(row["shoulder_depth_source"], "missing")
        for field in ("lsh_x", "lsh_y", "rsh_x", "rsh_y", "z_lsh_m", "z_rsh_m", "z_sh_m",
                      "left_hip_x_px", "left_hip_y_px", "left_hip_depth_m", "left_hip_visibility",
                      "right_hip_x_px", "right_hip_y_px", "right_hip_depth_m", "right_hip_visibility"):
            self.assertIsNone(row.get(field), field)

    def test_valid_hip_with_unavailable_depth_keeps_xy_visibility(self):
        ns = types.SimpleNamespace
        depth = np.zeros((20, 20), dtype=np.uint16)
        result = analysis.hip_observation(ns(x=.25, y=.75, visibility=.33), 20, 20, depth, .001)
        self.assertEqual(result[:2], (5., 15.))
        self.assertIsNone(result[2])
        self.assertEqual(result[3:], (.33, True, False))

    def test_out_of_frame_shoulder_preserves_legacy_depth_but_invalidates_canonical_depth(self):
        ns = types.SimpleNamespace
        pose = [ns(x=.5, y=.5, visibility=.5) for _ in range(33)]
        pose[11] = ns(x=.25, y=.8, visibility=.9)
        pose[12] = ns(x=-.1, y=.8, visibility=.8)  # -2 px: clipped legacy ROI still has enough depth pixels
        rows, _, _ = self._extract([(2000., 101, 201)], pose=pose)
        row = rows[0]
        self.assertEqual(row["rsh_x"], -2.)
        self.assertEqual(row["z_rsh_m"], 1.)
        self.assertEqual(row["z_sh_m"], 1.)
        self.assertIs(row["lsh_valid"], True)
        self.assertIs(row["rsh_valid"], False)
        self.assertIs(row["lsh_depth_valid"], True)
        self.assertIs(row["rsh_depth_valid"], False)
        self.assertEqual(row["shoulder_depth_source"], "left_only")

    def test_left_out_of_frame_shoulder_preserves_legacy_depth_and_uses_right_canonically(self):
        ns = types.SimpleNamespace
        pose = [ns(x=.5, y=.5, visibility=.5) for _ in range(33)]
        pose[11] = ns(x=1.1, y=.8, visibility=.9)  # 22 px: clipped legacy ROI still has depth
        pose[12] = ns(x=.75, y=.8, visibility=.8)
        rows, _, _ = self._extract([(2000., 101, 201)], pose=pose)
        row = rows[0]
        self.assertEqual(row["lsh_x"], 22.)
        self.assertEqual(row["z_lsh_m"], 1.)
        self.assertEqual(row["z_sh_m"], 1.)
        self.assertIs(row["lsh_valid"], False)
        self.assertIs(row["rsh_valid"], True)
        self.assertIs(row["lsh_depth_valid"], False)
        self.assertIs(row["rsh_depth_valid"], True)
        self.assertEqual(row["shoulder_depth_source"], "right_only")

    def test_frame_index_uses_pre_filter_traversal_count_and_can_gap(self):
        ns = types.SimpleNamespace
        pose = [ns(x=.5, y=.5, visibility=.5) for _ in range(33)]
        specs = [(2000., 101, 201), (3000., 102, 202), (4000., 103, 203), (5000., 104, 204)]
        rows, _, _ = self._extract(specs, pose=pose, step=2)
        self.assertEqual([row["frame_index"] for row in rows], [2, 4])
        self.assertEqual([row["color_frame_number"] for row in rows], [102, 104])
        self.assertEqual([row["depth_frame_number"] for row in rows], [202, 204])

    def test_mediapipe_timestamp_is_monotonic_corrected_value_and_ids_are_constant(self):
        ns = types.SimpleNamespace
        pose = [ns(x=.5, y=.5, visibility=.5) for _ in range(33)]
        rows, provenance, detectors = self._extract(
            [(2000.9, 11, 21), (2000.9, 12, 22)], pose=pose, recording_id="rec_A", analysis_run_id="ar_A")
        self.assertEqual([row["mediapipe_ts_ms"] for row in rows], [2000, 2001])
        self.assertEqual([call.args[1] for call in detectors[1].detect_for_video.call_args_list], [2000, 2001])
        self.assertEqual([call.args[1] for call in detectors[2].detect_for_video.call_args_list], [2000, 2001])
        self.assertEqual({row["recording_id"] for row in rows}, {"rec_A"})
        self.assertEqual({row["analysis_run_id"] for row in rows}, {"ar_A"})
        self.assertEqual({row["frame_schema_version"] for row in rows}, {"frames-schema/1.0.0"})
        self.assertEqual(provenance["playback_calibration"]["depth_scale_m"], .001)

    def test_face_depth_source_bbox_oval_and_missing_are_reachable(self):
        bbox, _, _ = self._extract([(2000., 1, 1)], face=True, mesh=True)
        oval, _, _ = self._extract([(2000., 1, 1)], face=False, mesh=True)
        missing, _, _ = self._extract([(2000., 1, 1)], face=False, mesh=False)
        self.assertEqual(bbox[0]["face_depth_source"], "bbox_roi")
        self.assertEqual(oval[0]["face_depth_source"], "oval_center_roi")
        self.assertEqual(missing[0]["face_depth_source"], "missing")
        self.assertIs(bbox[0]["face_depth_valid"], True)
        self.assertIs(oval[0]["face_depth_valid"], True)
        self.assertIs(missing[0]["face_depth_valid"], False)

    def test_face_bbox_depth_failure_falls_back_to_oval_center_depth(self):
        depth = np.full((20, 20), 1000, dtype=np.uint16)
        depth[4:8, 6:10] = 0
        rows, _, _ = self._extract([(2000., 1, 1)], face=True, mesh=True, depth=depth)
        row = rows[0]
        self.assertIs(row["face_detected"], True)
        self.assertIs(row["face_mesh_detected"], True)
        self.assertEqual(row["z_face_m"], 1.)
        self.assertIs(row["face_depth_valid"], True)
        self.assertEqual(row["face_depth_source"], "oval_center_roi")

    def test_shoulder_depth_source_all_states_are_reachable(self):
        path = self._csv_path()
        rows = [
            canonical_row(1, shoulder_depth_source="both"), canonical_row(2, shoulder_depth_source="left_only"),
            canonical_row(3, shoulder_depth_source="right_only"), canonical_row(4, shoulder_depth_source="missing"),
        ]
        analysis.write_frames_csv(path, rows)
        _, raw = self._read_raw(path)
        self.assertEqual([r["shoulder_depth_source"] for r in raw], ["both", "left_only", "right_only", "missing"])

    def test_raw_run_records_frames_artifact_schema_version(self):
        identity = "P03_r1_20261001_143025_123456_" + "a" * 32
        raw = self.data / (identity + ".bag")
        raw.write_bytes(b"synthetic raw fixture")
        base = raw.with_suffix("")
        analysis.write_json(str(base) + "_camera.json", {
            "recording_id": identity, "record_file": raw.name, "dataset_role": "formal",
            "protocol_version": "capture-forward-face-v2.0.0",
        })
        Path(str(base) + "_markers.csv").write_text(
            "frame_timestamp_ms,phase,label,step\n0,hold,upright,1\n10000,end,end,\n", encoding="utf-8")
        model_paths = {}
        for role, (filename, _) in analysis.MODELS.items():
            path = self.root / filename
            path.write_bytes(("model-" + role).encode())
            model_paths[role] = str(path)
        args = types.SimpleNamespace(subjects=["P03"], step=1, from_csv=False, legacy_pilot=False)

        def fake_process(path, models, step, provenance=None, output_dir=None):
            for role in models:
                analysis.mark_model_used(provenance, role)
            row = canonical_row(recording_id=provenance["recording_id"],
                                analysis_run_id=provenance["analysis_run_id"])
            destination = Path(output_dir) / (Path(path).stem + "_frames.csv")
            analysis.write_frames_csv(destination, [row])
            return [row]

        with patch.object(analysis, "ensure_models", return_value=model_paths), \
                patch.object(analysis, "process_recording", side_effect=fake_process), \
                patch.object(analysis, "analysis_code", return_value={}), \
                patch.object(analysis, "analysis_environment", return_value={}), \
                patch.object(analysis, "plot_all", return_value=None):
            analysis.run_analysis([str(raw)], args)
        manifests = [analysis.read_json(path) for path in self.out.glob(f"{identity}/ar_*/analysis_manifest.json")]
        self.assertEqual(len(manifests), 1)
        frame_output = next(item for item in manifests[0]["outputs"] if item["kind"] == "frames")
        self.assertEqual(frame_output["schema_version"], "frames-schema/1.0.0")

    def _linked_parent(self, frame, row):
        analysis.write_frames_csv(frame, [row])
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        parent_dir = self.root / "parent"
        parent_dir.mkdir(exist_ok=True)
        parent_path = parent_dir / "analysis_manifest.json"
        parent = {
            "status": "completed", "recording_id": row["recording_id"], "analysis_run_id": row["analysis_run_id"],
            "dataset_role": "formal", "protocol_version": "capture-forward-face-v2.0.0", "models": [],
            "outputs": [{"kind": "frames", "sha256": digest, "filename": frame.name}],
        }
        analysis.write_json(parent_path, parent)
        link = {
            "recording_id": row["recording_id"], "analysis_run_id": row["analysis_run_id"],
            "frames_sha256": digest, "analysis_manifest": os.path.relpath(parent_path, frame.parent),
            "analysis_manifest_sha256": hashlib.sha256(parent_path.read_bytes()).hexdigest(),
        }
        analysis.write_json(str(frame) + ".provenance.json", link)
        return parent_path

    def test_canonical_from_csv_linkage_passes_and_id_mismatch_is_rejected(self):
        frame = self.root / "source_frames.csv"
        row = canonical_row(recording_id="rec_parent", analysis_run_id="ar_parent")
        self._linked_parent(frame, row)
        args = types.SimpleNamespace(subjects=["P03"], step=1, from_csv=True, legacy_pilot=False)
        with patch.object(analysis, "analysis_code", return_value={}), \
                patch.object(analysis, "analysis_environment", return_value={}), \
                patch.object(analysis, "plot_all", return_value=None):
            analysis.run_analysis([str(frame)], args)
        manifests = [analysis.read_json(path) for path in self.out.glob("rec_parent/ar_*/analysis_manifest.json")]
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0]["status"], "completed")
        self.assertEqual(manifests[0]["recording_id"], "rec_parent")
        self.assertEqual(manifests[0]["parent_analysis_run_id"], "ar_parent")
        self.assertEqual(manifests[0]["input_frame_rows"], 1)

        bad = canonical_row(recording_id="rec_parent", analysis_run_id="ar_wrong")
        analysis.write_frames_csv(frame, [bad])
        link = analysis.read_json(str(frame) + ".provenance.json")
        link["frames_sha256"] = hashlib.sha256(frame.read_bytes()).hexdigest()
        analysis.write_json(str(frame) + ".provenance.json", link)
        with patch.object(analysis, "analysis_code", return_value={}), \
                patch.object(analysis, "analysis_environment", return_value={}):
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                analysis.start_analysis_run(str(frame), args, "batch")


if __name__ == "__main__":
    unittest.main()
