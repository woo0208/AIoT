"""SYNTHETIC ONLY: planned two-person 3+2 capture -> native -> formal6 input.

H values are arbitrary finite fixtures, not native geometry extraction evidence.
No real participant, camera, protected model, fit or held-out data is used.
"""

import csv
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import numpy as np

import capture_d455
import formal6_evaluation as ev
from f0_fcal_native import generate_evaluation_input
from f0_fcal_input import _Sources, InsufficientInput
from research_recording import RGBDPacket
from rf_experiment import file_identity
from stage5e_readiness import CAPTURE_LABELS, development_plan, native_request
from stage5e_native_h import GeometryObserver, extract_h
import stage5e_native_h as native_h
import f0_fcal_native as native
from test_f0_fcal_native import synthetic_observer


class PlanPackets:
    kind = "SYNTHETIC_5E3_NOT_NATIVE_RECORDING"

    def __init__(self, path):
        self.completed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        # 6 x (4 s prep + 11 s hold), plus the terminal marker packet.
        for n in range(721):
            ts = n * 125
            def desc(number, stamp, fmt):
                return dict(frame_number=number, timestamp_ms=stamp,
                    timestamp_domain="synthetic", height=4, width=6, format=fmt)
            color = np.zeros((4, 6, 3), np.uint8) if n % 20 != 1 else None
            yield RGBDPacket(color, np.zeros((4, 6), np.uint16), dict(
                color=desc(n//2+1, (n//2)*250, "bgr8") if color is not None else None,
                depth=desc(n+1, ts, "z16"), frameset_timestamp_ms=ts,
                frameset_timestamp_domain="synthetic", mediapipe_ts_ms=(n//2)*250 if color is not None else None,
                host_monotonic_ns=n, host_utc="synthetic"))
        self.completed = True


class SyntheticHObserver:
    kind = "SYNTHETIC_H_VALUES_NOT_GEOMETRY_EXTRACTION"
    model_artifacts = {}

    def __init__(self, reader, model_dir):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def observe(self, packet):
        return {name: float(j+1) if packet.color_bgr is not None else None
                for j, name in enumerate(ev.H9_FEATURE_NAMES)}


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.subjects = ("SYN-DEV01", "SYN-DEV02")
        self.plan = development_plan(self.subjects, (11,) * 6)

    def captures(self):
        result = {}
        for take in self.plan:
            rid = take["subject"] + "_r" + take["round"]
            raw = self.root / (rid + ".bag")
            raw.write_bytes(b"SYNTHETIC ONLY; NOT AN SDK RECORDING")
            camera = self.root / (rid + "_camera.json")
            camera.write_text(json.dumps(dict(recording_id=rid, subject=take["subject"],
                round=take["round"], dataset_role="formal", record_file=raw.name, sequence=take["sequence"],
                prep_sec=capture_d455.PREP_SEC,
                capture_script_sha256=file_identity(capture_d455.__file__)["sha256"])), encoding="utf-8")
            markers = self.root / (rid + "_markers.csv")
            with markers.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("recording_id", "frame_timestamp_ms",
                    "color_frame_number", "phase", "step", "label"))
                writer.writeheader()
                for i, label in enumerate(CAPTURE_LABELS):
                    for ts, phase, name in ((i*15000, "prep", "transition"),
                                            (i*15000+4000, "hold", label)):
                        writer.writerow(dict(recording_id=rid, frame_timestamp_ms=ts,
                            color_frame_number=ts//250+1, phase=phase, step=i+1, label=name))
                writer.writerow(dict(recording_id=rid, frame_timestamp_ms=90000,
                    color_frame_number=361, phase="end", step=6, label="end"))
            result[take["subject"], take["round"]] = dict(raw=raw, capture=camera, markers=markers,
                                                                        analysis_run_id="ar_" + rid)
        return result

    def test_plan_exact_class_order_sessions_repetitions_and_no_legacy_mutation(self):
        self.assertEqual(len(self.plan), 10)
        for subject in self.subjects:
            takes = [t for t in self.plan if t["subject"] == subject]
            self.assertEqual([t["session"] for t in takes], ["S1"]*3 + ["S2"]*2)
            self.assertEqual([o for t in takes for o in t["orders"]], list(range(30)))
            self.assertTrue(all(tuple(k for k, _ in t["sequence"]) == CAPTURE_LABELS for t in takes))
        self.assertEqual(capture_d455.SEQ_CORE[2], ("upright", 5))
        self.assertEqual(ev.h6.LAB6[-1], "lean_forward")

    def test_missing_duration_incomplete_plan_and_extra_capture_rejected(self):
        for durations in ((9,)*6, (float("nan"),)*6, (True,)*6, (11,)*5):
            with self.assertRaises(ValueError):
                development_plan(self.subjects, durations)
        captures = self.captures()
        with self.assertRaises(ValueError):
            native_request(self.plan[:-1], captures)
        captures["EXTERNAL-NOT-READ", "1"] = {}
        with self.assertRaises(ValueError):
            native_request(self.plan, captures)

    def test_changed_label_or_aborted_marker_not_promoted(self):
        captures = self.captures()
        path = captures[self.subjects[0], "1"]["markers"]
        original = path.read_text(encoding="utf-8")
        for text in (original.replace("forward_head", "body_forward"),
                     original.replace(",end,6,end", ",end,6,aborted")):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                native_request(self.plan, captures)

    def test_pilot_recording_cannot_be_promoted_into_formal_plan(self):
        captures = self.captures()
        path = captures[self.subjects[0], "1"]["capture"]
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["dataset_role"] = "pilot"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from plan"):
            native_request(self.plan, captures)

    def test_reused_rgb_recomputes_geometry_on_each_new_depth(self):
        packet = list(PlanPackets("synthetic"))[2]
        observer = GeometryObserver.__new__(GeometryObserver)
        observer.previous_color = native._stream_evidence(packet, "color")
        observer.landmarks = (None, None)
        observer.scale, observer.rs = .001, Mock()
        color_frame = Mock()
        color_frame.profile.as_video_stream_profile.return_value.get_intrinsics.return_value = NS(fx=500)
        observer.reader = NS(current_frames=NS(get_color_frame=lambda: color_frame))
        observer.align = Mock()
        depth_frames = []
        for value in (1, 2):
            depth = NS(get_data=lambda v=value: np.full((4, 6), v, np.uint16))
            depth_frames.append(NS(get_depth_frame=lambda d=depth: d))
        observer.align.process.side_effect = depth_frames
        outputs = [NS(features={name: float(n) for name in ev.H9_FEATURE_NAMES}) for n in (1, 2)]
        with patch.object(native_h.probe, "run_frame_inference", side_effect=AssertionError("reused RGB inferred")), \
             patch.object(native_h.geometry, "compute_candidate_geometry", side_effect=outputs) as compute:
            first = observer.observe(packet)
            second = observer.observe(packet)
        self.assertEqual(compute.call_count, 2)
        self.assertNotEqual(first, second)
        self.assertEqual(observer.align.process.call_count, 2)

    def test_complete_native_f0_and_synthetic_h_to_formal6_58_common_inputs(self):
        request = native_request(self.plan, self.captures())
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = generate_evaluation_input(request_path,
            request_sha256=file_identity(request_path)["sha256"], output_root=self.root / "generated",
            packet_factory=PlanPackets, observer_factory=synthetic_observer)
        self.assertEqual(result.status, "prepared", result.reasons)
        loaded = result.loaded
        self.assertEqual(len(loaded.samples), 60)
        self.assertEqual(sum(s.eligible for s in loaded.samples), 58)
        refs = {s: tuple(k) for s, k in request["reference_keys"].items()}
        windows, review, h_samples, key_map = {}, {}, [], {}
        for recording in request["recordings"]:
            directory = self.root / "generated/analysis" / recording["recording_id"] / recording["analysis_run_id"]
            inventory = json.loads((directory / "input_inventory.json").read_text())["frames"]
            h = extract_h(recording, _Sources(self.root), inventory, "unused",
                          packet_factory=PlanPackets, observer_factory=SyntheticHObserver)
            self.assertEqual(h["framesets"], 721)
            h_samples.extend(h["samples"])
            windows.update(h["windows"])
            key_map.update(h["key_map"])
        corrupted = [dict(r) for r in inventory]
        corrupted[0]["ts_ms"] += 1
        with self.assertRaisesRegex(InsufficientInput, "h_f0_native_inventory_mismatch"):
            extract_h(recording, _Sources(self.root), corrupted, "unused",
                      packet_factory=PlanPackets, observer_factory=SyntheticHObserver)
        for item, sample in zip(loaded.timed_segments, loaded.samples):
            key = sample.sample_key
            self.assertEqual(sample.reference_key, refs[sample.subject])  # S2 reuses S1.
            self.assertEqual(len(sample.input_indices), 80)  # Delivered framesets, not unique RGB.
            self.assertEqual(len(sample.support_indices), 76)
            self.assertEqual(sample.coverage, 76/80)
            if item.session == "S2":
                self.assertEqual(sample.reference_key[1].split("_r")[-1], "1")
            self.assertEqual(windows[key], ((item.time_basis, item.hold_end_s-10, item.hold_end_s), item.session))
            review[key] = "confirmed"  # Synthetic designation only.
            h = next(h for h in h_samples if key_map[h.sample_key] == key)
            self.assertEqual(h.n_frames, 80)
            self.assertEqual(h.common_valid_count, 76)
        families = ev.rows_from_f0(loaded.samples, loaded.timed_segments, review, self.subjects)
        families.update(ev.rows_from_h(h_samples, windows, review, self.subjects, key_map=key_map))
        aligned = ev.align_development(families, self.subjects, refs, feature_sets=tuple(ev.FEATURES))
        self.assertEqual(len(aligned["sample_keys"]), 58)
        for name, width in (("F0", 6), ("F_cal", 6), ("H5", 5), ("H9", 9), ("H9-F9", 8)):
            self.assertEqual(aligned["X"][name].shape, (58, width))
        for subject in self.subjects:
            self.assertEqual(np.bincount(aligned["y"][aligned["participants"] == subject], minlength=6).tolist(),
                             [4, 5, 5, 5, 5, 5])
        # Independent review remains a gate; the plan's labels do not certify execution.
        unreviewed = ev.rows_from_f0(loaded.samples, loaded.timed_segments, {}, self.subjects)
        with_review_missing = {**families, **unreviewed}
        blocked = ev.align_development(with_review_missing, self.subjects, refs, feature_sets=tuple(ev.FEATURES))
        self.assertEqual(len(blocked["sample_keys"]), 0)


if __name__ == "__main__":
    unittest.main()
