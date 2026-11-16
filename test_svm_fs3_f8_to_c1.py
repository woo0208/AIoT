"""Synthetic structural checks only; no research data, fitting, or camera."""
import math
import unittest

import numpy as np

from compare_svm_fs3_f8_to_c1 import c1_value, frame_c1, replacement


class C1Case(unittest.TestCase):
    def test_physical_sign_axis_and_earz_limit(self):
        s, h, e = np.array([0., 0., 1.]), np.array([0., .5, 1.]), np.array([0., -.2, .9])
        self.assertAlmostEqual(c1_value(s, h, e, .4), .25)
        self.assertAlmostEqual(c1_value(s, h, e, .4), (s[2] - e[2]) / .4)
        self.assertAlmostEqual(c1_value(s, h, [0., -.2, 1.1], .4), -.25)
        np.testing.assert_allclose(c1_value(s, h, s + 2 * (s - h), .4), 0.)
        self.assertIsNone(c1_value(s, s, e, .4))
        self.assertIsNone(c1_value(s, h, e, 0.))
        self.assertIsNone(c1_value(s, h, e, float('nan')))
        self.assertIsNone(c1_value(h, s, e, .4))

    def test_translation_scale_and_yz_rotation_invariance(self):
        s, h, e = np.array([.1, 0., 1.]), np.array([.1, .5, 1.2]), np.array([.1, -.2, .9])
        expected = c1_value(s, h, e, .4)
        shift = np.array([3., 2., 4.])
        self.assertAlmostEqual(c1_value(s + shift, h + shift, e + shift, .4), expected)
        self.assertAlmostEqual(c1_value(3 * s, 3 * h, 3 * e, 1.2), expected)
        angle = .3
        r = np.array([[1., 0., 0.], [0., math.cos(angle), -math.sin(angle)],
                      [0., math.sin(angle), math.cos(angle)]])
        self.assertAlmostEqual(c1_value(r @ s, r @ h, r @ e, .4), expected)

    def test_missing_flags_and_invalid_depth_are_not_imputed(self):
        row = {}
        for group, yz in (("ear", (-.2, .9)), ("shoulder", (0., 1.)), ("hip", (.5, 1.))):
            for side, x in (("left", -.2), ("right", .2)):
                name = f"{side}_{group}"
                row.update({f"{name}_3d_{a}_m": str(v) for a, v in zip("xyz", (x, *yz))})
                row[f"{name}_landmark_valid"] = row[f"{name}_depth_valid"] = "True"
        self.assertAlmostEqual(frame_c1(row)[0], .25)
        for changed in ({"left_hip_depth_valid": "False"}, {"right_ear_3d_z_m": "0"},
                        {"right_shoulder_3d_y_m": "nan"}, {"left_ear_3d_x_m": ""}):
            value, reasons = frame_c1(dict(row, **changed))
            self.assertIsNone(value)
            self.assertTrue(reasons)

    def test_replacement_preserves_other_columns_and_input(self):
        x = np.arange(21, dtype=float).reshape(3, 7)
        before = x.copy()
        changed = replacement(x, [9., 8., 7.])
        np.testing.assert_array_equal(x, before)
        np.testing.assert_array_equal(changed[:, :6], before[:, :6])
        np.testing.assert_array_equal(changed[:, 6], [9., 8., 7.])
        with self.assertRaises(ValueError):
            replacement(x, [1., 2.])
        with self.assertRaises(ValueError):
            replacement(x, [1., float('nan'), 3.])


if __name__ == "__main__":
    unittest.main()
