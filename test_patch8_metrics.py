"""CAP-005 §55–§81 metric tests on synthetic rows (structural only; not D455 evidence)."""
import math
import statistics
import types
import unittest

import patch8_metrics as metrics
import patch8_protocol as p8
from patch8_test_fixtures import INTRINSICS, forward_rows, frame_row, gate_entry, pinhole, static_rows
from test_capture_protocol import load_capture


PASSED_CALIBRATION = dict(passed=True, failures=[])
# Sample SD (ddof=1) of these 30 values × 1000 is exactly 10.0 in IEEE-754 (asserted below).
EXACT_10MM = [0.53, 0.47, 0.52, 0.48, 0.51, 0.49, 0.505, 0.4950000000000005, 0.505, 0.495] + [0.5] * 20


def take(rows=None, **kwargs):
    return metrics.evaluate_static_take(static_rows() if rows is None else rows, deproject=kwargs.get(
        "deproject", pinhole), calibration=kwargs.get("calibration", PASSED_CALIBRATION))


def series_rows(field, values, **changes):
    rows = static_rows(len(values), jitter_m=0.0, **changes)
    for row, value in zip(rows, values):
        row[field] = value
    return rows


class WindowCoverageAvailabilityTests(unittest.TestCase):
    def test_static_window_bounds_and_coverage_boundary(self):
        rows = [frame_row(t) for t in (0.999, 1.0, 9.499, 9.5, 9.6)]
        self.assertEqual([r["t"] for r in metrics.static_window(rows)], [1.0, 9.499])
        self.assertTrue(take(static_rows(109))["checks"]["frame_coverage"])
        self.assertFalse(take(static_rows(108))["checks"]["frame_coverage"])
        self.assertEqual(p8.MIN_WINDOW_ROWS, 109)
        self.assertAlmostEqual(take(static_rows(109))["coverage"]["ratio"], 109 / 127.5)

    def test_rows_outside_window_never_count(self):
        inside = static_rows(109)
        outside = [frame_row(t, face_detected=False, z_face_m=3.0) for t in (0.2, 0.5, 9.5, 9.9)]
        result = take(outside + inside)
        self.assertEqual(result["coverage"]["n"], 109)
        self.assertTrue(result["take_passed"], result["checks"])

    def test_landmark_rate_boundary_and_denominators(self):
        rows = static_rows(120)
        for row in rows[:6]:
            row["face_detected"] = False                  # 114/120 = 0.95
        result = take(rows)
        self.assertEqual(result["rates"]["face_detection_rate"], 0.95)
        self.assertTrue(result["checks"]["landmark_acquisition"])
        self.assertEqual(result["rates"]["head_depth_valid_rate"], 1.0)   # denominator = face_detected
        rows[6]["face_detected"] = False
        self.assertFalse(take(rows)["checks"]["landmark_acquisition"])

    def test_head_depth_requires_bbox_roi_and_point_denominators(self):
        rows = static_rows(100)
        for row in rows[:6]:
            row["face_depth_source"] = "oval_center_roi"
        rates = take(rows)["rates"]
        self.assertEqual(rates["head_depth_valid_rate"], 0.94)
        self.assertFalse(take(rows)["checks"]["conditional_depth"])
        rows = static_rows(100)
        for row in rows[:10]:
            row.update(lsh_valid=False, lsh_depth_valid=False)            # not in denominator
        for row in rows[10:13]:
            row["lsh_depth_valid"] = False
        self.assertEqual(take(rows)["rates"]["lsh_depth_valid_rate"], 87 / 90)

    def test_zero_denominators_are_not_evaluable_not_errors(self):
        rows = static_rows(120, face_detected=False, lsh_valid=False, rsh_valid=False)
        rates = take(rows)["rates"]
        self.assertIsNone(rates["head_depth_valid_rate"])
        self.assertIsNone(rates["lsh_depth_valid_rate"])
        self.assertFalse(take(rows)["checks"]["conditional_depth"])
        empty = take([])
        self.assertIsNone(empty["rates"]["face_detection_rate"])
        self.assertFalse(empty["take_passed"])

    def test_complete_rgbd_boundary(self):
        rows = static_rows(120)
        for row in rows[:12]:
            row["face_mesh_detected"] = False                            # complete = 108/120 = 0.90
        result = take(rows)
        self.assertEqual(result["rates"]["complete_rgbd_rate"], 0.90)
        self.assertTrue(result["checks"]["complete_rgbd"])
        rows[12]["right_hip_depth_valid"] = False
        self.assertFalse(take(rows)["checks"]["complete_rgbd"])

    def test_structure_requires_single_upright_hold(self):
        rows = static_rows()
        rows[0]["label"] = "forward_head"
        self.assertFalse(take(rows)["checks"]["structure"])
        self.assertFalse(take(rows)["take_passed"])


class DepthSeriesTests(unittest.TestCase):
    def test_exact_five_series_and_all_pass(self):
        result = take(static_rows(30))
        self.assertEqual(tuple(result["depth_series"]), p8.DEPTH_SERIES)
        self.assertEqual(p8.DEPTH_SERIES, ("z_face_m", "z_lsh_m", "z_rsh_m", "left_hip_depth_m", "right_hip_depth_m"))
        for field, series in result["depth_series"].items():
            self.assertEqual(series["n"], 30)
            self.assertLess(series["temporal_depth_sd_mm"], 10.0)
        self.assertTrue(result["checks"]["depth_temporal_sd"])

    def test_one_series_n29_fails_take(self):
        rows = static_rows(128)
        for row in rows[29:]:
            row["left_hip_depth_valid"] = False
        result = take(rows)
        self.assertEqual(result["depth_series"]["left_hip_depth_m"]["n"], 29)
        self.assertFalse(result["depth_series"]["left_hip_depth_m"]["evaluable"])
        self.assertIsNone(result["depth_series"]["left_hip_depth_m"]["temporal_depth_sd_mm"])
        self.assertFalse(result["checks"]["depth_temporal_sd"])
        self.assertFalse(result["take_passed"])

    def test_exactly_10mm_passes_and_above_fails(self):
        self.assertEqual(statistics.stdev(EXACT_10MM) * 1000, 10.0)
        series = take(series_rows("z_rsh_m", EXACT_10MM))["depth_series"]["z_rsh_m"]
        self.assertEqual(series["temporal_depth_sd_mm"], 10.0)
        self.assertTrue(series["passed"])
        wider = EXACT_10MM[:-1] + [math.nextafter(0.5, 1.0) + 1e-6]
        self.assertGreater(statistics.stdev(wider) * 1000, 10.0)
        self.assertFalse(take(series_rows("z_rsh_m", wider))["depth_series"]["z_rsh_m"]["passed"])

    def test_one_series_over_threshold_is_take_fail_four_of_five_not_enough(self):
        rows = static_rows(128)
        for i, row in enumerate(rows):
            row["right_hip_depth_m"] = 0.9 + (0.02 if i % 2 else -0.02)
        result = take(rows)
        passed = [k for k, v in result["depth_series"].items() if v["passed"]]
        self.assertEqual(len(passed), 4)
        self.assertFalse(result["checks"]["depth_temporal_sd"])
        self.assertFalse(result["take_passed"])

    def test_series_masks_exclude_exactly_the_specified_rows(self):
        rows = static_rows(40)
        rows[0].update(face_depth_source="oval_center_roi", z_face_m=3.0)    # oval fallback excluded
        rows[1].update(lsh_valid=False, z_lsh_m=3.0)                        # depth present, landmark invalid
        rows[2].update(left_hip_depth_valid=False, left_hip_depth_m=3.0)
        rows[3].update(z_rsh_m=float("nan"))
        rows[4].update(right_hip_depth_m=0.0)
        rows[5].update(z_face_m=-0.5)
        rows[6].update(z_lsh_m=None)
        window = metrics.static_window(rows)
        self.assertEqual(len(metrics.depth_series_values(window, "z_face_m")), 38)
        self.assertEqual(len(metrics.depth_series_values(window, "z_lsh_m")), 38)
        self.assertEqual(len(metrics.depth_series_values(window, "z_rsh_m")), 39)
        self.assertEqual(len(metrics.depth_series_values(window, "left_hip_depth_m")), 39)
        self.assertEqual(len(metrics.depth_series_values(window, "right_hip_depth_m")), 39)
        self.assertTrue(take(rows)["checks"]["depth_temporal_sd"])
        outside = [frame_row(9.6, z_face_m=5.0)] + rows
        self.assertEqual(take(outside)["depth_series"]["z_face_m"]["n"], 38)

    def test_no_outlier_removal_or_extra_filtering(self):
        rows = static_rows(60)
        rows[10]["z_face_m"] = 0.95                     # one valid in-window spike is kept
        series = take(rows)["depth_series"]["z_face_m"]
        values = [r["z_face_m"] for r in rows]
        self.assertEqual(series["n"], 60)
        self.assertAlmostEqual(series["temporal_depth_sd_mm"], statistics.stdev(values) * 1000)
        self.assertFalse(series["passed"])

    def test_two_of_three_takes_passing_depth_fails_distance_point(self):
        bad = static_rows(128)
        for i, row in enumerate(bad):
            row["z_face_m"] = 0.8 + (0.03 if i % 2 else -0.03)
        takes = {r: take() for r in p8.STATIC_ROUNDS}
        takes["8"] = take(bad)                          # 0.80 m repetition 2
        grid = metrics.evaluate_static_grid(takes)
        self.assertFalse(grid["points"][0.80]["passed"])
        self.assertFalse(grid["points"][0.80]["checks"]["every_take_passed"])
        self.assertTrue(grid["points"][0.70]["passed"])


class IpdAndGeometryTests(unittest.TestCase):
    def test_ipd_evaluability_boundary_and_mask(self):
        rows = static_rows(128)
        for row in rows[29:]:
            row["ipd_cm"] = None
        self.assertFalse(take(rows)["ipd"]["evaluable"])
        self.assertFalse(take(rows)["checks"]["ipd_evaluable"])
        rows[29]["ipd_cm"] = 6.3
        result = take(rows)["ipd"]
        self.assertEqual((result["n"], result["evaluable"]), (30, True))
        self.assertIsNotNone(result["median"])
        masked = static_rows(40)
        for row in masked[:5]:
            row["face_depth_source"] = "oval_center_roi"
        masked[5]["face_depth_valid"] = False
        self.assertEqual(take(masked)["ipd"]["n"], 34)

    def test_ipd_is_not_subject_to_within_take_cv(self):
        rows = static_rows(128)
        for i, row in enumerate(rows):
            row["ipd_cm"] = 6.0 if i % 2 else 7.0       # CV ≈ 8%
        result = take(rows)
        self.assertTrue(result["take_passed"], result["checks"])
        self.assertEqual(tuple(result["geometry"]), p8.WITHIN_TAKE_CV_QUANTITIES)
        self.assertNotIn("ipd_cm", result["geometry"])

    def test_3d_geometry_from_deprojection(self):
        geometry = metrics.row_geometry(frame_row(2.0), pinhole)
        self.assertAlmostEqual(geometry["shoulder_width_3d"], 400 / 640 * 0.85)
        self.assertAlmostEqual(geometry["hip_width_3d"], 320 / 640 * 0.90)
        mid_sh = (0.0, (420 - 360) / 640 * 0.85, 0.85)
        mid_hip = (0.0, (700 - 360) / 640 * 0.90, 0.90)
        self.assertAlmostEqual(geometry["trunk_length_3d"], math.dist(mid_sh, mid_hip))
        partial = metrics.row_geometry(frame_row(2.0, lsh_depth_valid=False), pinhole)
        self.assertEqual(set(partial), {"hip_width_3d"})

    def test_3d_scalar_n29_fails_and_cv_applies_exactly_to_three(self):
        rows = static_rows(128)
        for row in rows[29:]:
            row["rsh_depth_valid"] = False
        result = take(rows)
        self.assertEqual(result["geometry"]["shoulder_width_3d"]["n"], 29)
        self.assertFalse(result["geometry"]["shoulder_width_3d"]["within_take_cv_passed"])
        self.assertTrue(result["geometry"]["hip_width_3d"]["within_take_cv_passed"])
        self.assertFalse(result["checks"]["within_take_cv"])
        wobbly = static_rows(128)
        for i, row in enumerate(wobbly):
            row["right_hip_x_px"] = 480.0 + (25.0 if i % 2 else -25.0)   # hip width CV ≈ 7.8%
        result = take(wobbly)
        self.assertGreater(result["geometry"]["hip_width_3d"]["within_take_cv"], 0.03)
        self.assertFalse(result["checks"]["within_take_cv"])
        self.assertEqual(p8.WITHIN_TAKE_CV_QUANTITIES, ("shoulder_width_3d", "hip_width_3d", "trunk_length_3d"))
        self.assertEqual(p8.BETWEEN_TAKE_SPREAD_QUANTITIES, p8.WITHIN_TAKE_CV_QUANTITIES)
        self.assertEqual(p8.DISTANCE_STABILITY_QUANTITIES,
                         ("ipd_cm", "shoulder_width_3d", "hip_width_3d", "trunk_length_3d"))

    def test_failed_calibration_makes_geometry_not_evaluable(self):
        result = take(calibration=dict(passed=False, failures=["x"]))
        self.assertFalse(result["checks"]["calibration"])
        self.assertFalse(result["checks"]["within_take_cv"])
        self.assertEqual(result["geometry"]["trunk_length_3d"]["n"], 0)


class CalibrationTests(unittest.TestCase):
    def fake_rs(self):
        class Member:
            def __init__(self, name):
                self.name = name

            def __str__(self):
                return "distortion." + self.name
        distortion = types.SimpleNamespace(**{n: Member(n) for n in ("none", "brown_conrady", "inverse_brown_conrady",
                                                                     "modified_brown_conrady", "ftheta",
                                                                     "kannala_brandt4")})
        calls = []

        def deproject(intrinsics, pixel, depth):
            calls.append((vars(intrinsics).copy(), pixel, depth))
            return [1.0, 2.0, 3.0]
        return types.SimpleNamespace(distortion=distortion, intrinsics=types.SimpleNamespace,
                                     rs2_deproject_pixel_to_point=deproject), calls

    def test_distortion_enum_round_trip_is_exact(self):
        rs, _ = self.fake_rs()
        self.assertIs(metrics.distortion_model("distortion.inverse_brown_conrady", rs),
                      rs.distortion.inverse_brown_conrady)
        for bad in ("inverse_brown_conrady", "distortion.unknown", "Distortion.ftheta", None, 3):
            with self.subTest(bad=bad), self.assertRaises(metrics.CalibrationError):
                metrics.distortion_model(bad, rs)

    def test_sdk_deprojector_uses_color_intrinsics_pixel_and_depth(self):
        rs, calls = self.fake_rs()
        deproject = metrics.sdk_deprojector(INTRINSICS, rs)
        self.assertEqual(deproject(840, 420, 0.85), (1.0, 2.0, 3.0))
        intrinsics, pixel, depth = calls[0]
        self.assertEqual((pixel, depth), ([840.0, 420.0], 0.85))
        self.assertEqual((intrinsics["width"], intrinsics["height"], intrinsics["fx"], intrinsics["ppy"]),
                         (1280, 720, 640.0, 360.0))
        self.assertIs(intrinsics["model"], rs.distortion.inverse_brown_conrady)

    def test_calibration_check(self):
        capture = dict(color_intrinsics=dict(INTRINSICS), depth_scale_m=0.001)
        playback = dict(color_intrinsics=dict(INTRINSICS), depth_scale_m=0.001)
        self.assertTrue(metrics.calibration_check(playback, capture)["passed"])
        cases = (
            (dict(playback, color_intrinsics=dict(INTRINSICS, width=848, height=480)), capture),
            (playback, dict(capture, color_intrinsics=dict(INTRINSICS, fx=641.0))),
            (playback, dict(capture, depth_scale_m=0.0001)),
            (dict(playback, color_intrinsics=dict(INTRINSICS, coeffs=[0.0] * 4)), capture),
            (dict(playback, color_intrinsics=dict(INTRINSICS, fy=float("nan"))), capture),
            (None, capture), (playback, None),
        )
        for play, cap in cases:
            with self.subTest(play=play, cap=cap):
                self.assertFalse(metrics.calibration_check(play, cap)["passed"])


def synthetic_take(passed=True, medians=None, canonical=True, evaluated=True, reason=None):
    values = dict(ipd_cm=6.3, shoulder_width_3d=0.40, hip_width_3d=0.33, trunk_length_3d=0.45)
    values.update(medians or {})
    return dict(canonical=canonical, evaluated=evaluated, fail_reason=reason, take_passed=passed,
                checks={}, take_medians=values)


class StaticGridTests(unittest.TestCase):
    def grid(self, **overrides):
        takes = {r: synthetic_take() for r in p8.STATIC_ROUNDS}
        takes.update(overrides)
        return metrics.evaluate_static_grid(takes)

    def rounds(self, distance):
        return p8.static_rounds_at(distance)

    def test_round_mapping_follows_frozen_order(self):
        self.assertEqual([p8.SLOTS[str(r)].nominal_distance_m for r in range(1, 16)], list(p8.STATIC_GRID_M) * 3)
        self.assertEqual([p8.SLOTS[str(r)].repetition_index for r in range(1, 16)], [1] * 5 + [2] * 5 + [3] * 5)
        self.assertEqual(p8.SLOTS["1"].protocol_version, "patch8-d455-static-validation-v1.0.0")

    def test_all_pass_gives_full_envelope(self):
        grid = self.grid()
        self.assertTrue(grid["range_validation_passed"])
        self.assertEqual(grid["envelope_m"], (0.60, 1.00))
        self.assertTrue(grid["all_points_executed"])

    def test_anchor_failure_gives_no_envelope(self):
        for anchor in (0.70, 0.80):
            with self.subTest(anchor=anchor):
                grid = self.grid(**{self.rounds(anchor)[1]: synthetic_take(passed=False)})
                self.assertFalse(grid["points"][anchor]["passed"])
                self.assertIsNone(grid["envelope_m"])
                self.assertFalse(grid["range_validation_passed"])

    def test_envelope_is_maximal_contiguous_interval_containing_anchors(self):
        grid = self.grid(**{self.rounds(0.60)[0]: synthetic_take(passed=False)})
        self.assertEqual(grid["envelope_m"], (0.70, 1.00))
        self.assertTrue(grid["points"][0.70]["passed"])                # outer failure ≠ anchor failure
        grid = self.grid(**{self.rounds(0.90)[2]: synthetic_take(passed=False)})
        self.assertEqual(grid["envelope_m"], (0.60, 0.80))             # 1.00 PASS is not contiguous
        self.assertTrue(grid["points"][1.00]["passed"])
        self.assertEqual(metrics.static_envelope({0.6: False, 0.7: True, 0.8: True, 0.9: False, 1.0: True}),
                         ((0.7, 0.8), True))

    def test_all_three_repetitions_required(self):
        grid = self.grid(**{self.rounds(1.00)[2]: metrics.unevaluated_take("NOT_EXECUTED")})
        self.assertFalse(grid["points"][1.00]["checks"]["three_canonical_takes"])
        self.assertFalse(grid["all_points_executed"])
        grid = self.grid(**{self.rounds(0.90)[0]: metrics.unevaluated_take(p8.MANUAL_ABORT, canonical=True)})
        self.assertTrue(grid["points"][0.90]["checks"]["three_canonical_takes"])
        self.assertFalse(grid["points"][0.90]["checks"]["every_take_passed"])
        self.assertTrue(grid["all_points_executed"])

    def test_between_take_spread_applies_only_to_three_geometry_quantities(self):
        r = self.rounds(0.90)
        grid = self.grid(**{r[0]: synthetic_take(medians=dict(ipd_cm=6.0)), r[2]: synthetic_take(
            medians=dict(ipd_cm=6.6))})
        point = grid["points"][0.90]
        self.assertEqual(tuple(point["between_take_spread"]), p8.BETWEEN_TAKE_SPREAD_QUANTITIES)
        self.assertTrue(point["passed"], point["checks"])               # 9.5 % IPD spread is not blocking
        grid = self.grid(**{r[0]: synthetic_take(medians=dict(hip_width_3d=0.32)),
                            r[2]: synthetic_take(medians=dict(hip_width_3d=0.34))})
        spread = grid["points"][0.90]["between_take_spread"]["hip_width_3d"]
        self.assertAlmostEqual(spread["value"], 0.02 / 0.33)
        self.assertFalse(spread["passed"])

    def test_distance_stability_exact_quantities_anchor_and_threshold(self):
        r = self.rounds(1.00)
        grid = self.grid(**{x: synthetic_take(medians=dict(ipd_cm=6.3 * 1.05)) for x in r})
        stability = grid["points"][1.00]["distance_stability"]
        self.assertEqual(tuple(stability), p8.DISTANCE_STABILITY_QUANTITIES)
        self.assertEqual(stability["ipd_cm"]["anchor"], 6.3)
        self.assertLessEqual(stability["ipd_cm"]["value"], 0.05 + 1e-12)
        grid = self.grid(**{x: synthetic_take(medians=dict(trunk_length_3d=0.45 * 1.06)) for x in r})
        self.assertFalse(grid["points"][1.00]["distance_stability"]["trunk_length_3d"]["passed"])
        self.assertFalse(grid["points"][1.00]["passed"])
        self.assertTrue(grid["range_validation_passed"])

    def test_anchor_is_median_of_six_take_medians(self):
        overrides = {}
        for i, rnd in enumerate(self.rounds(0.70) + self.rounds(0.80)):
            overrides[rnd] = synthetic_take(medians=dict(shoulder_width_3d=0.40 + 0.01 * i))
        grid = self.grid(**overrides)
        self.assertAlmostEqual(grid["anchors"]["shoulder_width_3d"], statistics.median(
            [0.40 + 0.01 * i for i in range(6)]))

    def test_missing_anchor_median_fails_stability_everywhere(self):
        grid = self.grid(**{self.rounds(0.80)[0]: synthetic_take(passed=False, medians=dict(ipd_cm=None))})
        self.assertIsNone(grid["anchors"]["ipd_cm"])
        for distance in p8.STATIC_GRID_M:
            self.assertFalse(grid["points"][distance]["distance_stability"]["ipd_cm"]["passed"])


def exact(c):
    """(ref, cur) with ref - cur == c exactly (Sterbenz)."""
    return 2 * c, c


class ForwardTests(unittest.TestCase):
    def test_forward_population_is_exact(self):
        self.assertEqual(p8.FORWARD_AVAILABILITY_POPULATION, {
            "101": ("forward_head",), "102": ("forward_head",), "103": ("forward_head",),
            "111": ("body_forward",), "112": ("body_forward",), "113": ("body_forward",),
            "131": ("forward_head", "body_forward")})
        self.assertNotIn("121", p8.FORWARD_AVAILABILITY_POPULATION)
        for rnd, phases in p8.FORWARD_AVAILABILITY_POPULATION.items():
            self.assertEqual(p8.SLOTS[rnd].designated_phases, phases)

    def test_designated_phase_only_and_no_pooling(self):
        good = forward_rows("forward_head", "2", 127)
        bad = forward_rows("body_forward", "4", 127, face_detected=False)
        rows = good + bad
        self.assertTrue(metrics.evaluate_forward_availability(rows, "forward_head", 10.0)["passed"])
        self.assertFalse(metrics.evaluate_forward_availability(rows, "body_forward", 10.0)["passed"])
        result = metrics.slot131_predicate(
            canonical_exists=True, quality=dict(verdict="ok", forward_gate_evidence=[
                gate_entry("forward_head", ref=0.75, cur=0.65), gate_entry("body_forward", ref=0.75, cur=0.65)]),
            availability={"forward_head": metrics.evaluate_forward_availability(rows, "forward_head", 10.0),
                          "body_forward": metrics.evaluate_forward_availability(rows, "body_forward", 10.0)},
            analysis=dict(passed=True), lineage=dict(passed=True), recording_reconciled=True,
            analysis_reconciled=True)
        self.assertFalse(result["passed"])
        self.assertFalse(result["components"]["body_forward_availability"])

    def test_forward_window_is_strict_and_coverage(self):
        rows = [frame_row(t, label="forward_head", step="2") for t in (1.0, 1.001, 9.499, 9.5)]
        self.assertEqual([r["t"] for r in metrics.forward_window(rows, "forward_head", 10.0)], [1.001, 9.499])
        self.assertTrue(metrics.evaluate_forward_availability(forward_rows("forward_head", "2", 109),
                                                              "forward_head", 10.0)["checks"]["coverage"])
        self.assertFalse(metrics.evaluate_forward_availability(forward_rows("forward_head", "2", 108),
                                                               "forward_head", 10.0)["checks"]["coverage"])
        self.assertFalse(metrics.evaluate_forward_availability(forward_rows("forward_head", "2"),
                                                               "forward_head", 5.0)["passed"])

    def test_forward_blocking_rates_exact(self):
        rows = forward_rows("body_forward", "4", 120)
        for row in rows[:12]:
            row.update(left_hip_valid=False, left_hip_depth_valid=False)   # hip in-frame 0.90: not blocking here
        result = metrics.evaluate_forward_availability(rows, "body_forward", 10.0)
        self.assertTrue(result["passed"], result["checks"])
        self.assertEqual(set(result["checks"]), {
            "structure", "coverage", "face_detection_rate", "face_mesh_rate", "pose_detection_rate",
            "head_depth_valid_rate", "lsh_depth_valid_rate", "rsh_depth_valid_rate", "left_hip_depth_valid_rate",
            "right_hip_depth_valid_rate", "complete_rgbd"})
        rows[12]["face_mesh_detected"] = False
        self.assertFalse(metrics.evaluate_forward_availability(rows, "body_forward", 10.0)["checks"]["complete_rgbd"])

    def outcome(self, rnd, entry, lock_reason=None, capture=None, quality="default"):
        quality = dict(verdict="ok", forward_gate_evidence=[entry]) if quality == "default" else quality
        return metrics.forward_attempt_outcome(lock_reason, capture or {}, quality, p8.SLOTS[rnd])

    def test_band_boundaries_are_inclusive_and_exact(self):
        for rnd, (low, high) in (("101", (0.05, 0.07)), ("102", (0.09, 0.11)), ("103", (0.13, 0.15)),
                                 ("111", (0.05, 0.07)), ("112", (0.09, 0.11)), ("113", (0.13, 0.15))):
            label = p8.SLOTS[rnd].designated_phases[0]
            for value in (low, high):
                with self.subTest(rnd=rnd, value=value):
                    ref, cur = exact(value)
                    result = self.outcome(rnd, gate_entry(label, ref=ref, cur=cur))
                    self.assertEqual((result["outcome"], result["reason_code"]), (p8.CANONICAL, None))
                    self.assertTrue(result["evidence"]["class_gate_passed"])
            for value in (math.nextafter(low, 0), math.nextafter(high, 1)):
                with self.subTest(rnd=rnd, outside=value):
                    ref, cur = exact(value)
                    result = self.outcome(rnd, gate_entry(label, ref=ref, cur=cur))
                    self.assertEqual((result["outcome"], result["reason_code"]), (p8.TARGET_MISS, p8.TARGET_MISS))

    def test_realistic_in_band_and_target_miss(self):
        self.assertEqual(self.outcome("102", gate_entry("forward_head", ref=0.75, cur=0.65))["outcome"], p8.CANONICAL)
        miss = self.outcome("102", gate_entry("forward_head", ref=0.75, cur=0.63))     # gate PASS, out of band
        self.assertEqual(miss["outcome"], p8.TARGET_MISS)
        below = self.outcome("101", gate_entry("forward_head", ref=0.5, cur=0.43))      # exact 0.07
        self.assertEqual((below["outcome"], below["evidence"]["forward_gate_reasons"]), (p8.CANONICAL, ["below_target"]))

    def test_null_inconsistent_absent_and_lock_failures(self):
        label = "forward_head"
        cases = {
            "CLOSER_NULL": gate_entry(label, ref=0.75, cur=None),
            "EVIDENCE_INCONSISTENT": gate_entry(label, ref=0.75, cur=0.65, closer=0.06),
        }
        cases["EVIDENCE_INCONSISTENT"]["forward_gate_result"] = "pass"
        wrong_result = gate_entry(label, ref=0.75, cur=0.65)
        wrong_result["forward_gate_result"] = "fail"
        wrong_source = gate_entry(label, ref=0.75, cur=0.65)
        wrong_source["forward_validation_source"] = "body"
        wrong_reasons = gate_entry(label, ref=0.5, cur=0.43)
        wrong_reasons["forward_gate_reasons"] = ["above_target"]
        for reason, entry in list(cases.items()) + [("EVIDENCE_INCONSISTENT", wrong_result),
                                                     ("EVIDENCE_INCONSISTENT", wrong_source),
                                                     ("EVIDENCE_INCONSISTENT", wrong_reasons)]:
            with self.subTest(reason=reason, entry=entry):
                result = self.outcome("102" if entry is not wrong_reasons else "101", entry)
                self.assertEqual((result["outcome"], result["reason_code"]), (p8.CANONICAL, reason))
        self.assertEqual(self.outcome("102", None, quality=None)["reason_code"], "NO_QUALITY_EVIDENCE")
        self.assertEqual(self.outcome("102", None, quality=dict(forward_gate_evidence=[
            gate_entry("body_forward", ref=0.75, cur=0.65)]))["reason_code"], "NO_GATE_EVIDENCE")
        for reason in (p8.MANUAL_ABORT, p8.GUIDE_NOT_SATISFIED, p8.UNCLASSIFIED_TERMINATION):
            result = self.outcome("102", gate_entry(label, ref=0.75, cur=0.65), lock_reason=reason)
            self.assertEqual((result["outcome"], result["reason_code"]), (p8.CANONICAL, reason))
        skipped = self.outcome("102", gate_entry(label, ref=0.75, cur=0.65),
                               capture=dict(start_distance=dict(distance_m=0.75, mode="face_skipped")))
        self.assertEqual(skipped["reason_code"], p8.GUIDE_NOT_SATISFIED)

    def test_gate_mirror_matches_production_capture_code(self):
        capture = load_capture()
        values = [0.0, 0.05, 0.079, 0.08, 0.08 - 1e-13, 0.08 - 1e-11, 0.1, 0.12, 0.12 + 1e-13, 0.12 + 1e-11, 0.2]
        values += [exact(v)[0] - exact(v)[1] for v in (0.07, 0.09, 0.11, 0.13)]
        for value in values:
            self.assertEqual(metrics.production_gate_status(value), capture.evaluate_forward_distance(value), value)
        self.assertEqual((p8.FORWARD_GATE_MIN_M, p8.FORWARD_GATE_MAX_M, p8.FORWARD_VALIDATION_SOURCE,
                          p8.PRODUCTION_PROTOCOL_VERSION),
                         (capture.FWD_TARGET_MIN_M, capture.FWD_TARGET_MAX_M, capture.FWD_VALIDATION_SOURCE,
                          capture.PROTOCOL_VERSION))
        self.assertEqual(p8.PRODUCTION_SEQUENCES["core"], tuple(capture.SEQ_CORE))
        self.assertEqual(p8.PRODUCTION_SEQUENCES["full"], tuple(capture.SEQ_FULL))


def body_sample(t, mode="body", distance="0.71", phase_idx=7, label="body_forward"):
    return dict(phase_idx=str(phase_idx), step="4", phase="hold", label=label, t=str(t), distance_m=distance,
                mode=mode, recording_id="V01_r121_x")


class BodyOnlyTests(unittest.TestCase):
    def entry(self, **changes):
        value = gate_entry("body_forward", ref=0.75, cur=None, phase_idx=7, reference_phase_idx=5)
        value.update(changes)
        return value

    def run_case(self, entry="default", samples=None, quality="default", lock=None, capture=None, duration=10.0):
        entry = self.entry() if entry == "default" else entry
        quality = dict(verdict="retake", forward_gate_evidence=[entry] if entry else []) \
            if quality == "default" else quality
        samples = [body_sample(5.0)] if samples is None else samples
        return metrics.body_only_attempt_outcome(lock, capture or {}, quality, samples, duration)

    def test_exact_target_condition_passes(self):
        result = self.run_case()
        self.assertEqual((result["outcome"], result["reason_code"]), (p8.CANONICAL, None))
        self.assertEqual(self.entry()["forward_gate_reasons"], ["insufficient_current_face_samples"])
        self.assertIsNone(self.entry()["closer_m"])

    def test_dispositions(self):
        cases = {
            "reference insufficient → FAIL": (dict(entry=self.entry(reference_face_median_m=None, forward_gate_reasons=[
                "insufficient_reference_face_samples", "insufficient_current_face_samples"])),
                (p8.CANONICAL, "REFERENCE_FACE_INSUFFICIENT")),
            "current face sufficient → TARGET_MISS": (dict(entry=gate_entry("body_forward", ref=0.75, cur=0.65,
                                                                            phase_idx=7)),
                                                      (p8.TARGET_MISS, p8.TARGET_MISS)),
            "no body sample → TARGET_MISS": (dict(samples=[body_sample(5.0, mode="face"),
                                                           body_sample(5.0, distance=""),
                                                           body_sample(1.0), body_sample(9.5),
                                                           body_sample(5.0, phase_idx=3)]),
                                             (p8.TARGET_MISS, p8.TARGET_MISS)),
            "quality absent → FAIL": (dict(quality=None), (p8.CANONICAL, "NO_QUALITY_EVIDENCE")),
            "gate evidence absent → FAIL": (dict(entry=None), (p8.CANONICAL, "NO_GATE_EVIDENCE")),
            "target achieved but gate PASS → FAIL": (dict(entry=self.entry(forward_gate_result="pass",
                                                                            forward_gate_reasons=[])),
                                                     (p8.CANONICAL, "GATE_PASSED_ON_BODY_ONLY_TARGET")),
            "extra reasons → FAIL": (dict(entry=self.entry(forward_gate_reasons=[
                "insufficient_current_face_samples", "missing_reference"])), (p8.CANONICAL, "EVIDENCE_INCONSISTENT")),
            "manual abort → FAIL": (dict(lock=p8.MANUAL_ABORT), (p8.CANONICAL, p8.MANUAL_ABORT)),
            "guide skip → FAIL": (dict(capture=dict(start_distance=dict(mode="body_skipped"))),
                                  (p8.CANONICAL, p8.GUIDE_NOT_SATISFIED)),
            "wrong phase duration → FAIL": (dict(duration=5.0), (p8.CANONICAL, "EVIDENCE_INCONSISTENT")),
        }
        for name, (kwargs, expected) in cases.items():
            with self.subTest(name):
                result = self.run_case(**kwargs)
                self.assertEqual((result["outcome"], result["reason_code"]), expected)


class Slot131Tests(unittest.TestCase):
    def components(self, **changes):
        rows = forward_rows("forward_head", "2") + forward_rows("body_forward", "4")
        value = dict(
            canonical_exists=True,
            quality=dict(verdict="ok", forward_gate_evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                              gate_entry("body_forward", ref=0.75, cur=0.65)]),
            availability={label: metrics.evaluate_forward_availability(rows, label, 10.0)
                          for label in ("forward_head", "body_forward")},
            analysis=dict(passed=True), lineage=dict(passed=True), recording_reconciled=True,
            analysis_reconciled=True)
        value.update(changes)
        return value

    def test_exact_predicate(self):
        self.assertTrue(metrics.slot131_predicate(**self.components())["passed"])
        for verdict in ("ok_with_warnings", "retake", "fail", "aborted", None):
            quality = dict(self.components()["quality"], verdict=verdict)
            with self.subTest(verdict=verdict):
                result = metrics.slot131_predicate(**self.components(quality=quality))
                self.assertFalse(result["passed"])
                self.assertFalse(result["components"]["capture_verdict_ok"])
        for name in ("canonical_exists", "recording_reconciled", "analysis_reconciled"):
            with self.subTest(name=name):
                self.assertFalse(metrics.slot131_predicate(**self.components(**{name: False}))["passed"])
        for name in ("analysis", "lineage"):
            with self.subTest(name=name):
                self.assertFalse(metrics.slot131_predicate(**self.components(**{name: dict(passed=False)}))["passed"])
        self.assertFalse(metrics.slot131_predicate(**self.components(quality=None))["passed"])

    def test_both_production_gates_required(self):
        quality = dict(verdict="ok", forward_gate_evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                            gate_entry("body_forward", ref=0.75, cur=0.70)])
        result = metrics.slot131_predicate(**self.components(quality=quality))
        self.assertFalse(result["components"]["body_forward_production_gate"])
        self.assertTrue(result["components"]["forward_head_production_gate"])
        mixed = gate_entry("body_forward", ref=0.75, cur=0.65)
        mixed["forward_validation_source"] = "mixed"
        quality["forward_gate_evidence"][1] = mixed
        self.assertFalse(metrics.slot131_predicate(**self.components(quality=quality))["passed"])

    def test_canonical_analysis_predicate_exact(self):
        manifest = dict(analysis_run_id="ar_1", analysis_mode="extract_raw", status="completed",
                        options=dict(step_effective=1))
        batch = dict(analysis_run_ids=["ar_1"], run_manifests=["m"])
        self.assertTrue(metrics.canonical_analysis_predicate(manifest, batch)["passed"])
        for change in (dict(analysis_mode="summarize_existing_frames"), dict(status="failed"),
                       dict(options=dict(step_effective=2))):
            with self.subTest(change=change):
                self.assertFalse(metrics.canonical_analysis_predicate(dict(manifest, **change), batch)["passed"])
        self.assertFalse(metrics.canonical_analysis_predicate(manifest, dict(batch, analysis_run_ids=["ar_1", "ar_2"],
                                                                             run_manifests=["m", "n"]))["passed"])
        self.assertFalse(metrics.canonical_analysis_predicate(None, batch)["passed"])


if __name__ == "__main__":
    unittest.main()
