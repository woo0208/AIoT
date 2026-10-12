"""Hardware-free structural tests for debug_pose_landmark_viewer.

Synthetic landmarks only: these verify code behaviour, not D455 behaviour or
any research claim.
"""

import math
import os
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

import debug_pose_landmark_viewer as v

W, H, PAD = 1280, 720, 160


def lm(x, y, vis=0.9, pres=0.95):
    return SimpleNamespace(x=x, y=y, z=0.0, visibility=vis, presence=pres)


def pose(overrides=None):
    landmarks = [lm(0.5, 0.5) for _ in range(33)]
    base = {11: lm(0.6, 0.3), 12: lm(0.4, 0.3), 23: lm(0.58, 0.8), 24: lm(0.42, 0.8)}
    base.update(overrides or {})
    for i, item in base.items():
        landmarks[i] = item
    return landmarks


def rec(landmarks, index):
    name = {i: n for i, n, _ in v.DEBUG_LANDMARKS}[index]
    return v.landmark_record(landmarks, index, name, W, H)


class IndexMapping(unittest.TestCase):
    def test_indices_and_names(self):
        self.assertEqual(
            [(i, n) for i, n, _ in v.DEBUG_LANDMARKS],
            [(11, "left_shoulder"), (12, "right_shoulder"),
             (23, "left_hip"), (24, "right_hip")])

    def test_records_read_the_right_index(self):
        records = v.extract_debug_landmarks(pose(), W, H)
        self.assertEqual([r["index"] for r in records], [11, 12, 23, 24])
        self.assertAlmostEqual(records[0]["x"], 0.6)
        self.assertAlmostEqual(records[1]["x"], 0.4)
        self.assertAlmostEqual(records[2]["y"], 0.8)
        self.assertAlmostEqual(records[3]["x"], 0.42)


class InFrameAndRaw(unittest.TestCase):
    def test_in_frame(self):
        r = rec(pose(), 23)
        self.assertEqual(r["status"], v.STATUS_OK)
        self.assertTrue(r["in_frame"])
        self.assertAlmostEqual(r["margin_bottom"], 0.2)
        self.assertAlmostEqual(r["margin_left"], 0.58)
        self.assertAlmostEqual(r["x_px"], 0.58 * W)

    def test_out_of_frame_values_preserved_not_clipped(self):
        cases = {"x<0": (-0.2, 0.5), "x>=1": (1.0, 0.5),
                 "y<0": (0.5, -0.1), "y>=1": (0.5, 1.15), "x>1": (1.3, 0.5)}
        for label, (x, y) in cases.items():
            with self.subTest(label):
                r = rec(pose({23: lm(x, y)}), 23)
                self.assertEqual(r["status"], v.STATUS_OK)
                self.assertFalse(r["in_frame"])
                self.assertEqual(r["x"], x)
                self.assertEqual(r["y"], y)

    def test_boundaries(self):
        self.assertTrue(rec(pose({23: lm(0.0, 0.0)}), 23)["in_frame"])
        self.assertFalse(rec(pose({23: lm(1.0, 0.5)}), 23)["in_frame"])
        self.assertFalse(rec(pose({23: lm(0.5, 1.0)}), 23)["in_frame"])

    def test_negative_margin_when_outside(self):
        r = rec(pose({23: lm(0.5, 1.15)}), 23)
        self.assertAlmostEqual(r["margin_bottom"], -0.15)

    def test_low_visibility_not_dropped(self):
        r = rec(pose({23: lm(0.5, 1.2, vis=0.01, pres=0.0)}), 23)
        self.assertEqual(r["status"], v.STATUS_OK)
        self.assertEqual(r["y"], 1.2)
        self.assertEqual(r["visibility"], 0.01)
        self.assertEqual(r["presence"], 0.0)

    def test_visibility_presence_in_panel(self):
        records = v.extract_debug_landmarks(pose({23: lm(0.5, 0.8, 0.31, 0.77)}), W, H)
        text = "\n".join(v.panel_lines(records, W, H, PAD, True))
        self.assertIn("vis=0.31", text)
        self.assertIn("pres=0.77", text)
        self.assertIn(v.BANNER, text)
        self.assertIn("NOT measured anatomical", text)

    def test_missing_visibility_attr_is_na(self):
        r = rec(pose({23: SimpleNamespace(x=0.5, y=0.5)}), 23)
        self.assertEqual(r["status"], v.STATUS_OK)
        self.assertIsNone(r["visibility"])
        self.assertIsNone(r["presence"])


class MissingAndNonfinite(unittest.TestCase):
    def test_nonfinite(self):
        for bad in (float("nan"), float("inf"), -math.inf):
            with self.subTest(bad):
                r = rec(pose({23: lm(bad, 0.5)}), 23)
                self.assertEqual(r["status"], v.STATUS_NONFINITE)
                self.assertIsNone(r["x"])
                self.assertIsNone(r["in_frame"])

    def test_non_numeric(self):
        self.assertEqual(rec(pose({23: lm(None, 0.5)}), 23)["status"], v.STATUS_NONFINITE)
        self.assertEqual(rec(pose({23: lm(True, 0.5)}), 23)["status"], v.STATUS_NONFINITE)

    def test_missing_landmark(self):
        self.assertEqual(rec(None, 23)["status"], v.STATUS_MISSING)
        self.assertEqual(rec([], 23)["status"], v.STATUS_MISSING)
        self.assertEqual(rec(pose()[:20], 23)["status"], v.STATUS_MISSING)
        self.assertEqual(rec(pose({23: None}), 23)["status"], v.STATUS_MISSING)

    def test_missing_shown_in_panel(self):
        records = v.extract_debug_landmarks(None, W, H)
        text = "\n".join(v.panel_lines(records, W, H, PAD, False))
        self.assertIn("POSE NOT DETECTED", text)
        self.assertIn("MISSING", text)


class CanvasTransform(unittest.TestCase):
    def test_origin_and_far_corner(self):
        self.assertEqual(v.normalized_to_canvas(0, 0, W, H, PAD), (PAD, PAD))
        self.assertEqual(v.normalized_to_canvas(1, 1, W, H, PAD), (PAD + W, PAD + H))

    def test_outside_maps_into_padding(self):
        cx, cy = v.normalized_to_canvas(0.5, 1.1, W, H, PAD)
        self.assertAlmostEqual(cy, PAD + 1.1 * H)
        p = v.canvas_placement(0.5, 1.1, W, H, PAD)
        self.assertEqual((p["zone"], p["direction"]), ("padding", "B"))

    def test_in_frame_zone(self):
        p = v.canvas_placement(0.5, 0.5, W, H, PAD)
        self.assertEqual((p["zone"], p["direction"]), ("in_frame", ""))

    def test_beyond_padding_keeps_raw_and_clamps_draw_only(self):
        p = v.canvas_placement(0.5, 1.6, W, H, PAD)
        self.assertEqual((p["zone"], p["direction"]), ("beyond_padding", "B"))
        self.assertGreater(p["canvas"][1], H + 2 * PAD)  # unclipped value kept
        self.assertLessEqual(p["draw"][1], H + 2 * PAD - 1)
        p = v.canvas_placement(-0.5, -0.5, W, H, PAD)
        self.assertEqual((p["zone"], p["direction"]), ("beyond_padding", "LT"))

    def test_raw_record_unchanged_by_placement(self):
        r = rec(pose({23: lm(0.5, 1.6)}), 23)
        v.canvas_placement(r["x"], r["y"], W, H, PAD)
        self.assertEqual(r["y"], 1.6)

    def test_panel_marks_beyond_padding(self):
        records = v.extract_debug_landmarks(pose({23: lm(0.5, 1.6)}), W, H)
        text = "\n".join(v.panel_lines(records, W, H, PAD, True))
        self.assertIn("OUT(B) >PAD", text)
        self.assertIn("y=+1.6000", text)


class MidpointDiagnostic(unittest.TestCase):
    def test_distance(self):
        records = v.extract_debug_landmarks(pose(), W, H)
        mid = v.midpoint_diagnostic(records, W, H)
        self.assertAlmostEqual(mid["distance_px"], 0.5 * H)
        self.assertAlmostEqual(mid["distance_image_heights"], 0.5)

    def test_unavailable_when_any_missing(self):
        records = v.extract_debug_landmarks(pose({24: lm(float("nan"), 0.8)}), W, H)
        self.assertIsNone(v.midpoint_diagnostic(records, W, H))

    def test_uses_out_of_frame_raw_values(self):
        records = v.extract_debug_landmarks(
            pose({23: lm(0.58, 1.3), 24: lm(0.42, 1.3)}), W, H)
        mid = v.midpoint_diagnostic(records, W, H)
        self.assertAlmostEqual(mid["distance_image_heights"], 1.0)


class Rendering(unittest.TestCase):
    def setUp(self):
        self.bgr = np.zeros((H, W, 3), dtype=np.uint8)

    def test_shape_and_input_untouched(self):
        records = v.extract_debug_landmarks(pose({23: lm(0.5, 1.1)}), W, H)
        out = v.render_debug_image(self.bgr, records, PAD)
        self.assertEqual(out.shape, (H + 2 * PAD, W + 2 * PAD + v.PANEL_WIDTH, 3))
        self.assertEqual(int(self.bgr.sum()), 0)
        self.assertGreater(int(out.sum()), 0)

    def test_all_states_render_without_error(self):
        weird = pose({23: lm(float("nan"), 0.5), 24: lm(2.0, -3.0)})
        for lms in (weird, None, pose()):
            records = v.extract_debug_landmarks(lms, W, H)
            v.render_debug_image(self.bgr, records, PAD, lms is not None)

    def test_zero_pad(self):
        records = v.extract_debug_landmarks(pose(), W, H)
        out = v.render_debug_image(self.bgr, records, 0)
        self.assertEqual(out.shape, (H, W + v.PANEL_WIDTH, 3))

    def test_negative_pad_rejected(self):
        with self.assertRaises(ValueError):
            v.render_debug_image(self.bgr, [], -1)


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.img = np.zeros((20, 20, 3), dtype=np.uint8)

    def test_no_dir_saves_nothing(self):
        self.assertIsNone(v.save_snapshot(self.img, None))
        self.assertIsNone(v.save_snapshot(self.img, ""))

    def test_missing_dir_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "nope")
            self.assertIsNone(v.save_snapshot(self.img, target))
            self.assertFalse(os.path.exists(target))

    def test_saves_png_in_given_dir_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = v.save_snapshot(self.img, tmp, 3)
            self.assertIsNotNone(path)
            self.assertEqual(os.path.dirname(path), tmp)
            self.assertTrue(path.endswith(".png"))
            self.assertEqual(len(os.listdir(tmp)), 1)

    def test_render_itself_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                v.render_debug_image(np.zeros((H, W, 3), np.uint8),
                                     v.extract_debug_landmarks(pose(), W, H), PAD)
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(cwd)


class Args(unittest.TestCase):
    def test_default_has_no_snapshot_dir(self):
        args = v.parse_args([])
        self.assertIsNone(args.snapshot_dir)
        self.assertEqual(args.pad, 160)

    def test_bad_pad(self):
        with self.assertRaises(SystemExit):
            v.parse_args(["--pad", "-1"])


def recs(landmarks):
    return v.extract_debug_landmarks(landmarks, W, H)


def collect(collector, frames):
    for f in frames:
        collector.update(recs(f))


BASE = {"S0": (0.5, 0.3), "H0": (0.5, 0.8), "frames": 15}


class BaselineCollection(unittest.TestCase):
    def test_not_started_automatically(self):
        c = v.BaselineCollector()
        collect(c, [pose()] * 20)
        self.assertEqual(c.state, "idle")
        self.assertIsNone(c.baseline)

    def test_median_of_15_frames(self):
        c = v.BaselineCollector()
        self.assertTrue(c.start())
        frames = [pose({24: lm(0.42 + 0.001 * i, 0.8)}) for i in range(14)]
        frames.append(pose({24: lm(0.9, 0.8)}))  # outlier: median unaffected
        collect(c, frames[:14])
        self.assertTrue(c.collecting)
        self.assertIn("14/15", c.status_text())
        collect(c, frames[14:])
        self.assertTrue(c.ready)
        # right hip x: sorted 0.420..0.433, 0.9 -> 8th value = 0.427
        self.assertAlmostEqual(c.baseline["H0"][0], (0.58 + 0.427) / 2)
        self.assertAlmostEqual(c.baseline["H0"][1], 0.8)
        self.assertAlmostEqual(c.baseline["S0"][0], 0.5)
        self.assertAlmostEqual(c.baseline["S0"][1], 0.3)
        self.assertEqual(c.baseline["frames"], 15)
        self.assertIn("READY", c.status_text())

    def test_invalid_frame_aborts_never_accepts_fewer(self):
        bad_cases = {"nan": lm(float("nan"), 0.8), "out_of_frame": lm(0.42, 1.2),
                     "missing": None}
        for label, bad in bad_cases.items():
            with self.subTest(label):
                c = v.BaselineCollector()
                c.start()
                collect(c, [pose()] * 5 + [pose({24: bad})])
                self.assertEqual(c.state, "idle")
                self.assertIsNone(c.baseline)
                self.assertIn("ABORTED", c.status_text())
                collect(c, [pose()] * 20)  # not collecting anymore
                self.assertIsNone(c.baseline)
                self.assertTrue(c.start())  # retry restarts from 0
                collect(c, [pose()] * 15)
                self.assertTrue(c.ready)

    def test_pose_not_detected_frame_is_invalid(self):
        c = v.BaselineCollector()
        c.start()
        collect(c, [pose()] * 3 + [None])
        self.assertEqual(c.state, "idle")

    def test_no_visibility_threshold(self):
        c = v.BaselineCollector()
        c.start()
        collect(c, [pose({23: lm(0.58, 0.8, vis=0.0, pres=0.0)})] * 15)
        self.assertTrue(c.ready)

    def test_reset_and_recapture(self):
        c = v.BaselineCollector()
        c.start()
        collect(c, [pose()] * 15)
        self.assertFalse(c.start())  # ready: must reset first
        c.reset()
        self.assertEqual(c.state, "idle")
        self.assertIsNone(c.baseline)
        self.assertTrue(c.start())
        collect(c, [pose({23: lm(0.58, 0.7), 24: lm(0.42, 0.7)})] * 15)
        self.assertAlmostEqual(c.baseline["H0"][1], 0.7)

    def test_reset_mid_collection(self):
        c = v.BaselineCollector()
        c.start()
        collect(c, [pose()] * 4)
        c.reset()
        collect(c, [pose()] * 20)
        self.assertEqual(c.state, "idle")


class FixedHipDiagnostics(unittest.TestCase):
    def test_dynamic_and_fixed(self):
        # shoulders at x=0.6/0.4 -> D_sh = 0.2; current hips moved with trunk
        d = v.fixed_hip_diagnostics(
            recs(pose({23: lm(0.58, 0.7), 24: lm(0.42, 0.7)})), BASE)
        self.assertAlmostEqual(d["D_sh"], 0.2)
        self.assertAlmostEqual(d["SH_dynamic"][0], 0.0)
        self.assertAlmostEqual(d["SH_dynamic"][1], (0.3 - 0.7) / 0.2)
        self.assertAlmostEqual(d["SH_fixed"][0], 0.0)
        self.assertAlmostEqual(d["SH_fixed"][1], (0.3 - 0.8) / 0.2)
        self.assertAlmostEqual(d["dH"][1], -0.1)
        self.assertAlmostEqual(d["dS"][1], 0.0)

    def test_shoulders_move_changes_dS_and_fixed(self):
        d = v.fixed_hip_diagnostics(
            recs(pose({11: lm(0.6, 0.4), 12: lm(0.4, 0.4)})), BASE)
        self.assertAlmostEqual(d["dS"][1], 0.1)
        self.assertAlmostEqual(d["SH_fixed"][1], (0.4 - 0.8) / 0.2)

    def test_no_baseline(self):
        d = v.fixed_hip_diagnostics(recs(pose()), None)
        self.assertIsNone(d["H0"])
        self.assertIsNone(d["SH_fixed"])
        self.assertIsNone(d["dH"])
        self.assertIsNone(d["dS"])
        self.assertIsNotNone(d["SH_dynamic"])

    def test_missing_current_hip(self):
        d = v.fixed_hip_diagnostics(recs(pose({23: None})), BASE)
        self.assertIsNone(d["H_t"])
        self.assertIsNone(d["SH_dynamic"])
        self.assertIsNone(d["dH"])
        self.assertIsNotNone(d["SH_fixed"])

    def test_missing_current_shoulders(self):
        for bad in (None, lm(float("nan"), 0.3)):
            with self.subTest(bad):
                d = v.fixed_hip_diagnostics(recs(pose({11: bad})), BASE)
                self.assertIsNone(d["S_t"])
                self.assertIsNone(d["D_sh"])
                self.assertIsNone(d["SH_dynamic"])
                self.assertIsNone(d["SH_fixed"])
                self.assertIsNone(d["dS"])
                self.assertIsNotNone(d["H_t"])

    def test_zero_shoulder_width(self):
        d = v.fixed_hip_diagnostics(
            recs(pose({11: lm(0.5, 0.3), 12: lm(0.5, 0.3)})), BASE)
        self.assertIsNone(d["D_sh"])
        self.assertIsNone(d["SH_dynamic"])
        self.assertIsNone(d["SH_fixed"])

    def test_normalized_coordinates_not_pixels(self):
        # Vertical-only shoulder offset of 0.2 in normalized units: D_sh and the
        # numerator share the same normalized x/y units (no pixel scaling).
        d = v.fixed_hip_diagnostics(
            recs(pose({11: lm(0.5, 0.2), 12: lm(0.5, 0.4)})), BASE)
        self.assertAlmostEqual(d["D_sh"], 0.2)
        self.assertAlmostEqual(d["SH_fixed"][1], (0.3 - 0.8) / 0.2)

    def test_out_of_frame_current_values_not_clamped(self):
        d = v.fixed_hip_diagnostics(
            recs(pose({23: lm(0.58, 1.3), 24: lm(0.42, 1.3)})), BASE)
        self.assertAlmostEqual(d["H_t"][1], 1.3)
        self.assertAlmostEqual(d["SH_dynamic"][1], (0.3 - 1.3) / 0.2)

    def test_na_displayed_not_zero(self):
        c = v.BaselineCollector()
        d = v.fixed_hip_diagnostics(recs(None), None)
        text = "\n".join(v.fixed_hip_lines(c, d))
        self.assertIn("SH_dynamic(x,y)=N/A", text)
        self.assertIn("SH_fixed  (x,y)=N/A", text)
        self.assertIn("H0    =N/A", text)
        self.assertIn("D_sh=N/A", text)
        self.assertNotIn("0.000", text)


class FixedHipDisplay(unittest.TestCase):
    def test_label_and_lines_in_panel(self):
        c = v.BaselineCollector()
        d = v.fixed_hip_diagnostics(recs(pose()), None)
        text = "\n".join(v.panel_lines(recs(pose()), W, H, PAD, True, (c, d)))
        self.assertIn("FIXED-HIP ENGINEERING CANDIDATE — NOT F1", text)
        for token in ("S(t)", "H(t)", "H0", "S(t)-S0", "H(t)-H0",
                      "SH_dynamic", "SH_fixed"):
            self.assertIn(token, text)

    def test_panel_unchanged_without_fixed_hip(self):
        plain = v.panel_lines(recs(pose()), W, H, PAD, True)
        self.assertNotIn(v.FIXED_HIP_LABEL, "\n".join(plain))

    def test_lines_fit_panel_width(self):
        c = v.BaselineCollector()
        d = v.fixed_hip_diagnostics(recs(pose()), BASE)
        for line in v.fixed_hip_lines(c, d):
            self.assertLessEqual(len(line), 50, line)

    def test_render_with_and_without_baseline(self):
        bgr = np.zeros((H, W, 3), dtype=np.uint8)
        c = v.BaselineCollector()
        for lms in (pose(), None, pose({23: lm(0.5, 1.6)})):
            for base in (None, BASE):
                d = v.fixed_hip_diagnostics(recs(lms), base)
                out = v.render_debug_image(bgr, recs(lms), PAD, lms is not None,
                                           (c, d))
                self.assertEqual(
                    out.shape, (H + 2 * PAD, W + 2 * PAD + v.PANEL_WIDTH, 3))

    def test_no_files_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                c = v.BaselineCollector()
                c.start()
                collect(c, [pose()] * 15)
                d = v.fixed_hip_diagnostics(recs(pose()), c.baseline)
                v.render_debug_image(np.zeros((H, W, 3), np.uint8), recs(pose()),
                                     PAD, True, (c, d))
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(cwd)

    def test_snapshot_still_opt_in_and_args_unchanged(self):
        self.assertIsNone(v.parse_args([]).snapshot_dir)
        self.assertIsNone(v.save_snapshot(np.zeros((5, 5, 3), np.uint8), None))


class ExistingValidityContractUnchanged(unittest.TestCase):
    def test_diagnostic_does_not_mutate_records(self):
        before = recs(pose({23: lm(0.5, 1.2, vis=0.01)}))
        v.fixed_hip_diagnostics(before, BASE)
        self.assertEqual(before, recs(pose({23: lm(0.5, 1.2, vis=0.01)})))

    def test_out_of_frame_still_ok_status_for_live_viewing(self):
        r = rec(pose({23: lm(0.5, 1.2)}), 23)
        self.assertEqual(r["status"], v.STATUS_OK)
        self.assertFalse(r["in_frame"])

    def test_baseline_validity_requires_finite_and_in_frame_only(self):
        self.assertTrue(v.baseline_frame_valid(recs(pose({23: lm(0.5, 0.8, 0.0, 0.0)}))))
        self.assertFalse(v.baseline_frame_valid(recs(pose({23: lm(0.5, 1.0)}))))
        self.assertFalse(v.baseline_frame_valid(recs(pose({23: lm(1.0, 0.5)}))))
        self.assertTrue(v.baseline_frame_valid(recs(pose({23: lm(0.0, 0.0)}))))


if __name__ == "__main__":
    unittest.main()
