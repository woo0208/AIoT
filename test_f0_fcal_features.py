"""Synthetic structural tests only; no recording/CSV access or model fitting."""

from dataclasses import replace
import math
import unittest

from f0_fcal_features import (
    LABELS, Segment, first_upright_references,
    fit_calibrations, frame_features, segment_features,
)


def frame(**updates):
    row = dict(face_x=100, face_y=100, lsh_x=50, lsh_y=200,
               rsh_x=200, rsh_y=200, face_area_px=400)
    row.update(updates)
    return row


def segment(order=0, subject="P01", label="upright", frames=None):
    return Segment(subject, "rec_" + subject, "run_" + subject,
                   order, order, label, tuple(frames if frames is not None else [frame()]))


class F0FcalTests(unittest.TestCase):
    def fit(self, segments):
        return fit_calibrations(segments, first_upright_references(segments))

    def test_equations_signed_angles_and_bbox_ratio(self):
        c = self.fit([segment()])["P01"]
        f0, fc = frame_features(frame(face_area_px=800, oval_area_px=99999,
                                      theta1_deg=999), c)
        self.assertEqual(f0[:2], (100, 100))
        self.assertAlmostEqual(f0[3], math.degrees(math.atan(-0.5)))
        self.assertAlmostEqual(f0[4], 45)
        self.assertAlmostEqual(f0[2], f0[3] + f0[4])
        self.assertEqual(fc[:5], (0,) * 5)
        self.assertEqual((f0[-1], fc[-1]), (2, 2))

    def test_relative_subtracts_all_five_basics(self):
        c = self.fit([segment()])["P01"]
        f0, fc = frame_features(frame(face_x=130, face_y=120), c)
        self.assertEqual(fc[:2], (30, 20))
        for i in range(5):
            self.assertAlmostEqual(fc[i], f0[i] - c.baseline[i])
        self.assertEqual(fc[-1], 1)

    def test_six_labels_and_default_reference_exclusion(self):
        segments = [segment(i, label=label) for i, label in enumerate(LABELS)]
        c = self.fit(segments)
        results = segment_features(segments, c)
        self.assertEqual(tuple(r.label for r in results), LABELS)
        self.assertEqual([r.excluded_from_evaluation for r in results], [True] + [False] * 5)
        self.assertFalse(any(r.excluded_from_evaluation for r in
                             segment_features(segments, c, exclude_references=False)))

    def test_later_upright_and_predictions_cannot_change_reference(self):
        initial = segment()
        later = segment(2, frames=[frame(face_x=900, prediction="upright")])
        test = segment(3, label="lean_left", frames=[frame(face_x=150)])
        c = self.fit([test, later, initial])
        self.assertEqual(c, self.fit([initial]))
        self.assertEqual(segment_features([test], c)[0].f_cal[0], 50)
        with self.assertRaises(ValueError):
            fit_calibrations([initial, later], {"P01": later.key})

    def test_participants_are_isolated_including_held_out_subject(self):
        a, b = segment(), segment(subject="P02", frames=[frame(face_x=300, face_area_px=800)])
        c = self.fit([a, b])
        result = segment_features([segment(1, "P02", "lean_back", [frame(face_x=350)])], c)[0]
        self.assertEqual(result.f_cal[0], 50)
        self.assertEqual(result.f0[-1], 0.5)
        with self.assertRaises(ValueError):
            frame_features(frame(subject="P01"), c["P02"])

    def test_primitive_medians_and_angles_after_aggregation(self):
        s = segment(frames=[frame(face_x=x, face_area_px=a) for x, a in
                            [(100, 100), (110, 400), (1000, 900)]])
        c = self.fit([s])
        self.assertEqual(c["P01"].area_px, 400)
        self.assertEqual(c["P01"].baseline[:2], (110, 100))
        self.assertEqual(segment_features([s], c)[0].f_cal, (0, 0, 0, 0, 0, 1))

    def test_invalid_numbers_and_zero_denominator_are_missing(self):
        c = self.fit([segment()])["P01"]
        for bad in (None, "", "nan", float("inf"), "bad", True):
            with self.subTest(bad=bad):
                f0, fc = frame_features(frame(face_x=bad), c)
                self.assertIsNone(f0[0])
                self.assertTrue(all(v is None for v in f0[2:5]))
                self.assertIsNone(fc[0])
        f0, _ = frame_features(frame(lsh_y=100), c)
        self.assertIsNone(f0[3])
        self.assertIsNone(f0[2])
        self.assertEqual(f0[4], 45)

    def test_missing_reference_never_falls_back_to_later_upright(self):
        first = segment(frames=[frame(face_x=None, face_area_px=0)])
        later = segment(1)
        c = self.fit([first, later])
        r = segment_features([later], c)[0]
        self.assertIsNone(r.f0[-1])
        self.assertIsNone(r.f_cal[0])
        self.assertIn("A", r.missing())
        self.assertIn("xc", r.missing("F_cal"))
        self.assertFalse(r.excluded_from_evaluation)

    def test_empty_segment_and_invalid_areas(self):
        s = segment(frames=[])
        c = self.fit([s])
        self.assertEqual(segment_features([s], c)[0].f0, (None,) * 6)
        good = self.fit([segment()])["P01"]
        for area in (0, -1, float("nan"), None):
            self.assertIsNone(frame_features(frame(face_area_px=area), good)[0][-1])

    def test_identity_and_reference_validation(self):
        s = segment()
        for bad in ([s, s], [replace(s, label="unknown")],
                    [replace(s, frames=(frame(subject="other"),))],
                    [replace(s, label="lean_back")]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.fit(bad)
        with self.assertRaises(ValueError):
            fit_calibrations([s], {})
        with self.assertRaises(ValueError):
            segment_features([s], {})

    def test_explicit_validity_flags_and_no_depth_requirement(self):
        c = self.fit([segment()])["P01"]
        f0, _ = frame_features(frame(lsh_valid="false", z_face_m=None), c)
        self.assertIsNone(f0[3])
        self.assertEqual(f0[-1], 1)
        s = segment(1, frames=[frame(face_detected=False)])
        self.assertEqual(segment_features([s], {"P01": c})[0].f0, (None,) * 6)

    def test_invalid_baseline_length_is_rejected(self):
        s = segment()
        c = self.fit([s])["P01"]
        for baseline in ((), (100.0,), (0,) * 4, (0,) * 6, None):
            bad = replace(c, baseline=baseline)
            with self.subTest(baseline=baseline):
                with self.assertRaisesRegex(ValueError, "baseline must contain exactly 5 values"):
                    frame_features(frame(), bad)
                with self.assertRaisesRegex(ValueError, "baseline must contain exactly 5 values"):
                    segment_features([s], {"P01": bad})

    def test_valid_baseline_preserves_six_features_and_missing_values(self):
        s = segment()
        c = self.fit([s])["P01"]
        for baseline, expected in ((c.baseline, (0, 0, 0, 0, 0, 1)),
                                   ((None,) * 5, (None,) * 5 + (1,))):
            valid = replace(c, baseline=baseline)
            with self.subTest(baseline=baseline):
                fcal = frame_features(frame(), valid)[1]
                result = segment_features([s], {"P01": valid})[0]
                self.assertEqual(len(fcal), 6)
                self.assertEqual(len(result.f_cal), 6)
                self.assertEqual(fcal, expected)
                self.assertEqual(result.f_cal, expected)


if __name__ == "__main__":
    unittest.main()
