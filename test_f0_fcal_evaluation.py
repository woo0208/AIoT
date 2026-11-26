"""Synthetic preparation/transport tests; no fitting or research-data access."""

from dataclasses import replace
import unittest

import numpy as np

from f0_fcal_features import Segment
from f0_fcal_evaluation import (
    TimedSegment, ComparableSample, prepare_samples, evaluation_input, LAB6,
)


def item(order=0, subject="SYN01", label="upright", n=60, valid=60, x=100, session="S1"):
    frames = tuple(dict(frame_index=i, time_s=10 + i * 9 / n, phase="hold",
                        face_x=x, face_y=100, lsh_x=50, lsh_y=200,
                        rsh_x=200, rsh_y=200, face_area_px=400,
                        lsh_valid=i < valid) for i in range(n))
    return TimedSegment(Segment(subject, "r" + subject, "a" + subject,
                                order, order, label, frames), session, 5, 20, "synthetic_seconds")


def prepare(items):
    refs = {i.segment.subject: i.segment.key for i in items
            if i.segment.order == 0 and i.segment.label == "upright"}
    return prepare_samples(items, refs)


class AdapterTests(unittest.TestCase):
    def test_six_columns_class_order_and_reference_masks(self):
        items = [item()]
        for i, label in enumerate(LAB6, 1):
            items.append(item(i, label=label))
        samples = prepare(items)
        result = evaluation_input(samples)
        self.assertEqual(result["matrices"]["F0"].shape, (7, 6))
        self.assertEqual(result["matrices"]["F_cal"].shape, (7, 6))
        self.assertEqual(tuple(s.class_index for s in samples[1:]), tuple(range(6)))
        self.assertEqual(samples[-1].label, "lean_forward")
        self.assertTrue(samples[0].is_reference)
        self.assertFalse(samples[0].eligible)
        self.assertFalse(result["common_mask"][0])
        self.assertFalse(result["train_mask"][0])
        self.assertFalse(result["heldout_mask"][0])
        self.assertEqual(prepare([item(), item(1, label="body_forward")])[1].class_index, 5)

    def test_joint_support_coverage_and_primitive_median(self):
        ref = item()
        good = item(1, n=60, valid=30, x=130)
        rows = tuple(dict(r, face_x=9999) if i >= 30 else r
                     for i, r in enumerate(good.segment.frames))
        good = replace(good, segment=replace(good.segment, frames=rows))
        bad = item(2, n=61, valid=30)
        too_few = item(3, n=29, valid=29)
        a, b, c, d = prepare([ref, good, bad, too_few])
        self.assertEqual(b.coverage, 0.5)
        self.assertEqual(len(b.support_indices), 30)
        self.assertEqual(b.f0[0], 130)
        self.assertTrue(b.eligible)
        self.assertFalse(c.eligible)
        self.assertFalse(d.eligible)

    def test_half_open_window_and_transition_exclusion(self):
        target = item(1, n=30, valid=30)
        extra = tuple(dict(target.segment.frames[0], frame_index=100+i, time_s=t, phase=p)
                      for i, (t, p) in enumerate([(9.99, "hold"), (20, "hold"), (15, "transition")]))
        target = replace(target, segment=replace(target.segment, frames=target.segment.frames + extra))
        result = prepare([item(), target])[1]
        self.assertEqual(len(result.input_indices), 30)
        self.assertIn(0, result.input_indices)  # t=10 included
        self.assertTrue(result.eligible)

    def test_reference_is_fixed_and_participants_are_isolated(self):
        a, b = item(), item(subject="SYN02", x=300)
        target = item(2, subject="SYN02", x=350, label="lean_left", session="S2")
        later = item(1, subject="SYN02", x=10000, session="S2")
        samples = prepare([target, a, later, b])
        self.assertEqual(samples[0].f_cal[0], 50)
        changed = replace(target, segment=replace(target.segment, frames=tuple(
            dict(r, face_x=90000, prediction="upright") for r in target.segment.frames)))
        again = prepare([changed, a, later, b])
        self.assertEqual(samples[1].f_cal, again[1].f_cal)
        self.assertEqual(samples[3].f_cal, again[3].f_cal)
        with self.assertRaises(ValueError):
            prepare_samples([b, later], {"SYN02": later.segment.key})

    def test_reference_failure_blocks_only_that_participant(self):
        badref = item(n=60, valid=29)
        goodref = item(subject="SYN02")
        samples = prepare([badref, item(1), goodref, item(1, subject="SYN02")])
        self.assertFalse(samples[1].eligible)
        self.assertIn("participant_calibration_failed", samples[1].reasons)
        self.assertTrue(samples[3].eligible)
        self.assertEqual(samples[1].reference_key, badref.segment.key)
        self.assertTrue(samples[1].calibration_reasons)
        # Frame-wise defined angles can still yield undefined median geometry.
        ref = item(n=30, valid=30)
        frames = tuple(dict(r, lsh_y=90 if i < 15 else 110)
                       for i, r in enumerate(ref.segment.frames))
        ref = replace(ref, segment=replace(ref.segment, frames=frames))
        failed = prepare([ref, item(1)])[1]
        self.assertIn("reference_baseline_invalid", failed.calibration_reasons)
        self.assertFalse(failed.eligible)

    def test_missing_time_short_hold_reference_and_duplicate_are_unprocessed(self):
        target = item(1)
        variants = [replace(target, hold_end_s=None), replace(target, hold_start_s=15),
                    replace(target, time_basis=None), replace(target, session=None),
                    replace(target, segment=replace(target.segment, frames=target.segment.frames +
                                                   (target.segment.frames[0],)))]
        for candidate in variants:
            with self.subTest(candidate=candidate):
                sample = prepare([item(), candidate])[1]
                self.assertEqual(sample.status, "unprocessed")
                self.assertEqual(sample.f0, (None,) * 6)
                self.assertTrue(all(sample.missing_f0))
        no_ref = prepare_samples([target], {})[0]
        self.assertEqual(no_ref.status, "unprocessed")
        self.assertIsNone(no_ref.reference_key)

    def test_common_sample_alignment_and_identity_audit(self):
        samples = prepare([item(), item(2), item(1)])
        family = [ComparableSample(s.sample_key, s.subject, s.label, (9,) * 8,
                                   s.sample_key[-1] != 2) for s in reversed(samples)]
        result = evaluation_input(samples, other_families={"H9-F9": family},
                                  participant_splits={"SYN01": "train"})
        self.assertEqual(result["common_sample_keys"], (samples[2].sample_key,))
        self.assertEqual(result["common_matrices"]["F0"].shape, (1, 6))
        self.assertEqual(result["common_matrices"]["H9-F9"].shape, (1, 8))
        self.assertFalse(result["reference_mask"][result["common_mask"]].any())
        np.testing.assert_array_equal(result["y"], [0, 0, 0])
        wrong = replace(family[0], subject="other")
        with self.assertRaises(ValueError):
            evaluation_input(samples, other_families={"H9": [wrong]})
        with self.assertRaises(ValueError):
            evaluation_input(samples, other_families={"H9": [family[0], family[0]]})

    def test_missing_features_are_not_zero_filled(self):
        bad = item(1, valid=0)
        samples = prepare([item(), bad])
        result = evaluation_input(samples)
        self.assertTrue(result["missing_masks"]["F0"][1].all())
        self.assertTrue(np.isnan(result["matrices"]["F0"][1]).all())
        self.assertFalse(result["eligible_mask"][1])
        self.assertIsNone(samples[1].frame_loss_rate)

    def test_explicit_two_four_split_keeps_reference_out_of_both_masks(self):
        items, roles = [], {}
        for i in range(6):
            subject = f"SYN{i}"
            items.extend([item(subject=subject), item(1, subject=subject, label="forward_head")])
            roles[subject] = "train" if i < 2 else "heldout"
        result = evaluation_input(prepare(items), participant_splits=roles)
        self.assertEqual(int(result["train_mask"].sum()), 2)
        self.assertEqual(int(result["heldout_mask"].sum()), 4)
        self.assertFalse((result["reference_mask"] & result["train_mask"]).any())
        self.assertFalse((result["reference_mask"] & result["heldout_mask"]).any())
        self.assertEqual(len(result["common_y"]), 6)
        self.assertEqual(len(result["common_participants"]), 6)


if __name__ == "__main__":
    unittest.main()
