"""Structural tests for the FEAT-009 F1-5 frame calculation (synthetic only)."""

import math
import unittest

import f1_features as f1


def frame_row(**overrides):
    """Synthetic frames-schema/1.0.0 subset; not participant data."""

    row = {
        "face_detected": True, "face_x": 640.0, "face_y": 200.0,
        # subject-left shoulder appears on image right (non-mirrored image)
        "lsh_valid": True, "lsh_x": 740.0, "lsh_y": 400.0,
        "rsh_valid": True, "rsh_x": 540.0, "rsh_y": 400.0,
        "left_hip_valid": True, "left_hip_x_px": 710.0, "left_hip_y_px": 700.0,
        "right_hip_valid": True, "right_hip_x_px": 570.0, "right_hip_y_px": 700.0,
    }
    row.update(overrides)
    return row


def transformed(row, scale=1.0, dx=0.0, dy=0.0):
    out = dict(row)
    for x_field, y_field in (("face_x", "face_y"), ("lsh_x", "lsh_y"), ("rsh_x", "rsh_y"),
                             ("left_hip_x_px", "left_hip_y_px"),
                             ("right_hip_x_px", "right_hip_y_px")):
        out[x_field] = row[x_field] * scale + dx
        out[y_field] = row[y_field] * scale + dy
    return out


class WrapPiTests(unittest.TestCase):
    def test_range_and_period_pi(self):
        for theta in (-math.pi, -3.0, -math.pi / 2, -1.0, 0.0, 1.0, math.pi / 2, 3.0, math.pi,
                      7.5, -7.5):
            with self.subTest(theta=theta):
                wrapped = f1.wrap_pi(theta)
                self.assertGreaterEqual(wrapped, -math.pi / 2)
                self.assertLess(wrapped, math.pi / 2)
                self.assertAlmostEqual(math.sin(2 * wrapped), math.sin(2 * theta), places=12)
                self.assertAlmostEqual(math.cos(2 * wrapped), math.cos(2 * theta), places=12)

    def test_half_open_boundary(self):
        self.assertEqual(f1.wrap_pi(math.pi / 2), -math.pi / 2)
        self.assertEqual(f1.wrap_pi(-math.pi / 2), -math.pi / 2)
        self.assertEqual(f1.wrap_pi(math.pi), 0.0)
        self.assertEqual(f1.wrap_pi(-math.pi), 0.0)
        for theta in (math.nextafter(math.pi / 2, 0.0), math.nextafter(-math.pi / 2, 0.0),
                      math.nextafter(-math.pi / 2, -math.inf), math.nextafter(math.pi / 2, math.inf)):
            with self.subTest(theta=theta):
                wrapped = f1.wrap_pi(theta)
                self.assertGreaterEqual(wrapped, -math.pi / 2)
                self.assertLess(wrapped, math.pi / 2)

    def test_matches_contract_formula_away_from_rounding_boundary(self):
        for theta in (-2.9, -1.2, -0.4, 0.3, 1.1, 2.2, 3.1):
            with self.subTest(theta=theta):
                expected = theta - math.pi * math.floor((theta + math.pi / 2) / math.pi)
                self.assertEqual(f1.wrap_pi(theta), expected)

    def test_rejects_non_finite_angle(self):
        for theta in (math.nan, math.inf, -math.inf):
            with self.subTest(theta=theta):
                with self.assertRaises(ValueError):
                    f1.wrap_pi(theta)


class F1FormulaTests(unittest.TestCase):
    def test_output_names_order_units_and_families(self):
        self.assertEqual(f1.F1_5_FEATURE_NAMES, ("fs_x", "fs_y", "sh_x", "sh_y", "so_beta"))
        self.assertEqual(dict(f1.F1_5_FEATURE_UNITS), {
            "fs_x": "dimensionless", "fs_y": "dimensionless",
            "sh_x": "dimensionless", "sh_y": "dimensionless", "so_beta": "rad",
        })
        self.assertEqual(dict(f1.F1_5_FEATURE_FAMILIES), {
            "fs_x": "FS", "fs_y": "FS", "sh_x": "SH", "sh_y": "SH", "so_beta": "SO",
        })
        result = f1.compute_f1_5_frame(frame_row())
        self.assertEqual(tuple(result.features), f1.F1_5_FEATURE_NAMES)
        self.assertEqual(result.ordered_values(),
                         tuple(result.features[name] for name in f1.F1_5_FEATURE_NAMES))
        self.assertEqual(tuple(result.family_available), ("FS", "SH", "SO"))

    def test_hand_computed_values(self):
        # S = (640, 400), H = (640, 700), W = (-200, 0), D_sh = 200
        result = f1.compute_f1_5_frame(frame_row())
        self.assertEqual(result.ordered_values(), (0.0, -1.0, 0.0, -1.5, 0.0))
        self.assertTrue(all(result.family_available.values()))
        self.assertEqual(dict(result.family_reasons), {"FS": (), "SH": (), "SO": ()})

    def test_general_formula_with_tilted_shoulders(self):
        row = frame_row(face_x=610.0, face_y=180.0, lsh_x=700.0, lsh_y=380.0,
                        rsh_x=520.0, rsh_y=440.0, left_hip_x_px=690.0, left_hip_y_px=760.0,
                        right_hip_x_px=560.0, right_hip_y_px=740.0)
        s = (610.0, 410.0)
        h = (625.0, 750.0)
        w = (-180.0, 60.0)
        d_sh = math.hypot(*w)
        beta = math.atan2(w[1], w[0])
        beta -= math.pi * math.floor((beta + math.pi / 2) / math.pi)
        expected = ((610.0 - s[0]) / d_sh, (180.0 - s[1]) / d_sh,
                    (s[0] - h[0]) / d_sh, (s[1] - h[1]) / d_sh, beta)
        for got, want in zip(f1.compute_f1_5_frame(row).ordered_values(), expected):
            self.assertAlmostEqual(got, want, places=12)

    def test_horizontal_shoulders_beta_zero(self):
        for lsh_x, rsh_x in ((740.0, 540.0), (540.0, 740.0)):
            with self.subTest(lsh_x=lsh_x):
                result = f1.compute_f1_5_frame(frame_row(lsh_x=lsh_x, rsh_x=rsh_x))
                self.assertEqual(result.features["so_beta"], 0.0)
                self.assertEqual(math.copysign(1.0, result.features["so_beta"]), 1.0)

    def test_shoulder_tilt_sign_follows_image_coordinates(self):
        # Facing camera: subject-left shoulder at image right. W = R - L points image-left.
        # Image-right shoulder (L) higher on screen (smaller y) -> W_y > 0 with W_x < 0.
        right_side_high = f1.compute_f1_5_frame(frame_row(lsh_y=380.0, rsh_y=420.0))
        left_side_high = f1.compute_f1_5_frame(frame_row(lsh_y=420.0, rsh_y=380.0))
        expected = math.atan(-40.0 / 200.0)
        self.assertAlmostEqual(right_side_high.features["so_beta"], expected, places=12)
        self.assertLess(right_side_high.features["so_beta"], 0.0)
        self.assertGreater(left_side_high.features["so_beta"], 0.0)
        self.assertAlmostEqual(left_side_high.features["so_beta"],
                               -right_side_high.features["so_beta"], places=12)

    def test_w_and_minus_w_give_same_beta(self):
        base = dict(lsh_x=700.0, lsh_y=380.0, rsh_x=520.0, rsh_y=440.0)
        swapped = dict(lsh_x=520.0, lsh_y=440.0, rsh_x=700.0, rsh_y=380.0)
        a = f1.compute_f1_5_frame(frame_row(**base)).features["so_beta"]
        b = f1.compute_f1_5_frame(frame_row(**swapped)).features["so_beta"]
        self.assertAlmostEqual(a, b, places=12)

    def test_beta_wrap_at_vertical_shoulder_line(self):
        # W = (0, +d) gives atan2 = +pi/2 and W = (0, -d) gives -pi/2; both map to -pi/2.
        down = f1.compute_f1_5_frame(frame_row(lsh_x=640.0, lsh_y=300.0, rsh_x=640.0, rsh_y=500.0))
        up = f1.compute_f1_5_frame(frame_row(lsh_x=640.0, lsh_y=500.0, rsh_x=640.0, rsh_y=300.0))
        self.assertEqual(down.features["so_beta"], -math.pi / 2)
        self.assertEqual(up.features["so_beta"], -math.pi / 2)
        # atan2 just below +pi/2 stays just below +pi/2 (half-open upper end)
        below = f1.compute_f1_5_frame(frame_row(lsh_x=640.0, lsh_y=300.0, rsh_x=640.001, rsh_y=500.0))
        self.assertLess(below.features["so_beta"], math.pi / 2)
        self.assertGreater(below.features["so_beta"], math.pi / 2 - 1e-3)
        # atan2 just above +pi/2 wraps to just above -pi/2
        above = f1.compute_f1_5_frame(frame_row(lsh_x=640.0, lsh_y=300.0, rsh_x=639.999, rsh_y=500.0))
        self.assertGreater(above.features["so_beta"], -math.pi / 2)
        self.assertLess(above.features["so_beta"], -math.pi / 2 + 1e-3)

    def test_translation_invariance(self):
        base = frame_row(lsh_y=380.0, rsh_y=430.0, face_x=600.0)
        expected = f1.compute_f1_5_frame(base).ordered_values()
        for dx, dy in ((37.5, -12.25), (-500.0, 300.0)):
            with self.subTest(dx=dx, dy=dy):
                got = f1.compute_f1_5_frame(transformed(base, dx=dx, dy=dy)).ordered_values()
                for g, e in zip(got, expected):
                    self.assertAlmostEqual(g, e, places=12)

    def test_uniform_scale_invariance(self):
        base = frame_row(lsh_y=380.0, rsh_y=430.0, face_x=600.0)
        expected = f1.compute_f1_5_frame(base).ordered_values()
        for scale in (0.5, 1.5, 3.0):
            with self.subTest(scale=scale):
                got = f1.compute_f1_5_frame(transformed(base, scale=scale)).ordered_values()
                for g, e in zip(got, expected):
                    self.assertAlmostEqual(g, e, places=12)

    def test_inputs_outside_contract_are_ignored(self):
        base = f1.compute_f1_5_frame(frame_row()).ordered_values()
        extra = frame_row(z_face_m=0.6, z_sh_m=0.7, left_hip_depth_m=0.8, lsh_vis=0.01,
                          rsh_vis=0.01, left_hip_visibility=0.0, face_score=0.01, label="forward")
        self.assertEqual(f1.compute_f1_5_frame(extra).ordered_values(), base)


class F1ValidityTests(unittest.TestCase):
    def assert_family(self, result, fs, sh, so):
        self.assertEqual(dict(result.family_available), {"FS": fs, "SH": sh, "SO": so})
        self.assertEqual(result.features["fs_x"] is not None, fs)
        self.assertEqual(result.features["fs_y"] is not None, fs)
        self.assertEqual(result.features["sh_x"] is not None, sh)
        self.assertEqual(result.features["sh_y"] is not None, sh)
        self.assertEqual(result.features["so_beta"] is not None, so)
        for family, available in result.family_available.items():
            self.assertEqual(result.family_reasons[family] == (), available)

    def test_zero_shoulder_width_makes_all_features_unavailable(self):
        result = f1.compute_f1_5_frame(frame_row(rsh_x=740.0, rsh_y=400.0))
        self.assert_family(result, False, False, False)
        for family in f1.F1_FAMILIES:
            self.assertIn("d_sh:zero", result.family_reasons[family])

    def test_invalid_shoulder_with_legacy_numeric_coordinate(self):
        # Schema D02: legacy lsh_x/lsh_y can remain numeric while lsh_valid is false.
        for state, reason in ((False, "lsh_valid:false"), (None, "lsh_valid:unknown"),
                              ("false", "lsh_valid:false"), ("", "lsh_valid:unknown")):
            with self.subTest(state=state):
                result = f1.compute_f1_5_frame(frame_row(lsh_valid=state))
                self.assert_family(result, False, False, False)
                for family in f1.F1_FAMILIES:
                    self.assertIn(reason, result.family_reasons[family])
        result = f1.compute_f1_5_frame(frame_row(rsh_valid=False))
        self.assert_family(result, False, False, False)

    def test_invalid_face(self):
        for overrides, reason in (
            ({"face_detected": False}, "face_detected:false"),
            ({"face_detected": None}, "face_detected:unknown"),
            ({"face_detected": True, "face_x": None}, "face_xy:missing"),
            ({"face_detected": "true", "face_y": ""}, "face_xy:missing"),
        ):
            with self.subTest(overrides=overrides):
                result = f1.compute_f1_5_frame(frame_row(**overrides))
                self.assert_family(result, False, True, True)
                self.assertEqual(result.family_reasons["FS"], (reason,))

    def test_invalid_hip(self):
        for overrides, reason in (
            ({"left_hip_valid": False, "left_hip_x_px": None, "left_hip_y_px": None},
             "left_hip_valid:false"),
            ({"right_hip_valid": None}, "right_hip_valid:unknown"),
            ({"right_hip_valid": True, "right_hip_y_px": None}, "right_hip_xy:missing"),
            # numbers present but state false must not be treated as valid
            ({"left_hip_valid": False}, "left_hip_valid:false"),
        ):
            with self.subTest(overrides=overrides):
                result = f1.compute_f1_5_frame(frame_row(**overrides))
                self.assert_family(result, True, False, True)
                self.assertEqual(result.family_reasons["SH"], (reason,))

    def test_family_availability_is_independent(self):
        cases = (
            ({}, (True, True, True)),
            ({"face_detected": False}, (False, True, True)),
            ({"left_hip_valid": False}, (True, False, True)),
            ({"face_detected": False, "right_hip_valid": False}, (False, False, True)),
            ({"lsh_valid": False}, (False, False, False)),
        )
        full = f1.compute_f1_5_frame(frame_row()).features
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                result = f1.compute_f1_5_frame(frame_row(**overrides))
                self.assert_family(result, *expected)
                for name, value in result.features.items():
                    if value is not None:
                        self.assertEqual(value, full[name])

    def test_missing_fields_are_unknown_not_false_or_valid(self):
        row = frame_row()
        for field in ("left_hip_valid", "right_hip_valid", "left_hip_x_px", "right_hip_y_px"):
            row.pop(field)
        result = f1.compute_f1_5_frame(row)
        self.assert_family(result, True, False, True)
        self.assertIn("left_hip_valid:unknown", result.family_reasons["SH"])
        self.assert_family(f1.compute_f1_5_frame({}), False, False, False)

    def test_non_finite_coordinates_are_unavailable_not_values(self):
        for value in (math.nan, math.inf, -math.inf, "nan", "inf", "-Infinity"):
            with self.subTest(value=value):
                face = f1.compute_f1_5_frame(frame_row(face_x=value))
                self.assert_family(face, False, True, True)
                self.assertEqual(face.family_reasons["FS"], ("face_xy:nonfinite",))
                hip = f1.compute_f1_5_frame(frame_row(right_hip_y_px=value))
                self.assert_family(hip, True, False, True)
                shoulder = f1.compute_f1_5_frame(frame_row(rsh_x=value))
                self.assert_family(shoulder, False, False, False)
                self.assertIn("rsh_xy:nonfinite", shoulder.family_reasons["SO"])

    def test_overflowing_intermediate_geometry_is_unavailable(self):
        result = f1.compute_f1_5_frame(frame_row(lsh_x=1e308, rsh_x=-1e308))
        self.assert_family(result, False, False, False)
        self.assertIn("shoulder_geometry:nonfinite", result.family_reasons["SO"])

    def test_outputs_are_always_finite_or_none(self):
        rows = (frame_row(), frame_row(face_x=math.inf), frame_row(rsh_x=740.0, rsh_y=400.0),
                frame_row(lsh_x=1e308, rsh_x=-1e308), frame_row(left_hip_x_px=-1e308,
                                                                 right_hip_x_px=-1e308))
        for row in rows:
            for value in f1.compute_f1_5_frame(row).ordered_values():
                self.assertTrue(value is None or math.isfinite(value))

    def test_csv_string_cells_follow_schema_serialization(self):
        strings = {key: ("true" if value is True else str(value)) for key, value in frame_row().items()}
        self.assertEqual(f1.compute_f1_5_frame(strings).ordered_values(),
                         f1.compute_f1_5_frame(frame_row()).ordered_values())
        result = f1.compute_f1_5_frame(dict(strings, face_detected="false"))
        self.assert_family(result, False, True, True)

    def test_malformed_encodings_are_rejected(self):
        for field, value in (("face_detected", "TRUE"), ("lsh_valid", 1), ("rsh_valid", 0),
                             ("left_hip_valid", "1"), ("right_hip_valid", "False"),
                             ("face_x", "abc"), ("lsh_y", True), ("rsh_x", [1.0])):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    f1.compute_f1_5_frame(frame_row(**{field: value}))

    def test_geometry_uses_only_the_given_frame(self):
        # Frame A lacks a face, frame B lacks hips; neither borrows from the other.
        frame_a = frame_row(face_detected=False, face_x=None, face_y=None)
        frame_b = frame_row(left_hip_valid=False, left_hip_x_px=None, left_hip_y_px=None,
                            lsh_y=380.0)
        result_a = f1.compute_f1_5_frame(frame_a)
        result_b = f1.compute_f1_5_frame(frame_b)
        self.assert_family(result_a, False, True, True)
        self.assert_family(result_b, True, False, True)
        self.assertEqual(result_a.ordered_values(),
                         (None, None, 0.0, -1.5, 0.0))
        self.assertNotEqual(result_b.features["so_beta"], result_a.features["so_beta"])
        self.assertEqual(f1.compute_f1_5_frame(frame_a).ordered_values(), result_a.ordered_values())

    def test_result_is_immutable(self):
        result = f1.compute_f1_5_frame(frame_row())
        with self.assertRaises(TypeError):
            result.features["fs_x"] = 0.0
        with self.assertRaises(AttributeError):
            result.features = {}


if __name__ == "__main__":
    unittest.main()
