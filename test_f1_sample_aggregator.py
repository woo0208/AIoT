"""Structural tests for the Gate 1.8 F1 sample aggregator (synthetic only).

All fixtures are synthetic.  Passing these tests is software verification of
the prototype mathematics and diagnostics, not evidence about real coverage,
posture separability or classification performance.
"""

from dataclasses import FrozenInstanceError
import math
import random
import statistics
import unittest

import f1_features as f1
import f1_sample_aggregator as agg
from test_f1_features import frame_row


RUN, REC = "run-synthetic-A", "rec-synthetic-A"


def record(result, frame_index, **overrides):
    fields = dict(analysis_run_id=RUN, recording_id=REC, frame_index=frame_index,
                  subject="S-synthetic", round="1", step="3", label="upright", result=result)
    fields.update(overrides)
    return agg.F1FrameRecord(**fields)


def row_records(rows, start=1, **overrides):
    """Records from synthetic frames-schema rows via the unchanged FEAT-009 calculation."""

    return [record(f1.compute_f1_5_frame(row), start + i, **overrides) for i, row in enumerate(rows)]


def manual_result(fs=None, sh=None, so=None):
    """Hand-built consistent F1FrameResult (for values compute_f1_5_frame cannot isolate)."""

    features = dict.fromkeys(f1.F1_5_FEATURE_NAMES)
    available, reasons = {}, {}
    for family, values, names in (("FS", fs, ("fs_x", "fs_y")), ("SH", sh, ("sh_x", "sh_y")),
                                  ("SO", (so,) if so is not None else None, ("so_beta",))):
        available[family] = values is not None
        reasons[family] = () if values is not None else (f"synthetic_{family.lower()}:missing",)
        if values is not None:
            features.update(zip(names, (float(v) for v in values)))
    return f1.F1FrameResult(features=features, family_available=available, family_reasons=reasons)


def beta_records(betas):
    return [record(manual_result(fs=(0.0, -1.0), sh=(0.0, -1.5), so=b), i + 1)
            for i, b in enumerate(betas)]


def axial_distance(a, b):
    return abs(f1.wrap_pi(a - b))


NO_HIP = dict(left_hip_valid=False, left_hip_x_px=None, left_hip_y_px=None)


class JointSupportTests(unittest.TestCase):
    def test_all_families_valid(self):
        rows = [frame_row(face_x=640.0 + 10 * i, lsh_y=400.0 + i) for i in range(5)]
        records = row_records(rows)
        result = agg.aggregate_f1_sample(records, support="joint")
        frame_values = [r.result.features for r in records]
        self.assertEqual(result.support_policy, "joint")
        self.assertEqual(result.n_frames, 5)
        self.assertEqual(dict(result.family_valid_counts), {"FS": 5, "SH": 5, "SO": 5})
        self.assertEqual(result.joint_valid_count, 5)
        self.assertEqual(dict(result.coverage), {"FS": 1.0, "SH": 1.0, "SO": 1.0, "joint": 1.0})
        for name in ("fs_x", "fs_y", "sh_x", "sh_y"):
            self.assertEqual(result.features[name], statistics.median(v[name] for v in frame_values))
        self.assertTrue(all(v is not None for v in result.ordered_values()))
        self.assertEqual(set(result.feature_support.values()), {"joint"})
        self.assertEqual(dict(result.undefined_reasons), dict.fromkeys(f1.F1_5_FEATURE_NAMES))
        self.assertTrue(result.defined_features_same_frames)

    def test_joint_uses_one_frame_set_for_all_features(self):
        rows = [frame_row(),                                   # 1: joint
                frame_row(face_detected=False, lsh_y=380.0),   # 2: SH, SO
                frame_row(lsh_y=420.0, **NO_HIP),              # 3: FS, SO
                frame_row(face_x=700.0, lsh_y=410.0)]          # 4: joint
        result = agg.aggregate_f1_sample(row_records(rows), support="joint")
        self.assertEqual(result.valid_frame_indices["joint"], (1, 4))
        self.assertEqual(dict(result.selected_frame_indices), {"FS": (1, 4), "SH": (1, 4), "SO": (1, 4)})
        self.assertEqual(set(result.feature_n_used.values()), {2})

    def test_empty_joint_support_is_undefined_not_zero(self):
        rows = [frame_row(face_detected=False), frame_row(**NO_HIP), frame_row(**NO_HIP)]
        result = agg.aggregate_f1_sample(row_records(rows), support="joint")
        self.assertEqual(result.joint_valid_count, 0)
        self.assertEqual(result.coverage["joint"], 0.0)
        self.assertEqual(result.ordered_values(), (None,) * 5)
        self.assertEqual(set(result.undefined_reasons.values()), {"no_supported_frames:joint"})
        self.assertIsNone(result.so_beta_resultant)
        self.assertEqual(dict(result.family_valid_counts), {"FS": 2, "SH": 1, "SO": 3})
        self.assertEqual(set(result.feature_n_used.values()), {0})
        self.assertFalse(hasattr(result, "eligible"))


class FamilySupportTests(unittest.TestCase):
    def test_family_specific_support(self):
        rows = [frame_row(),
                frame_row(face_detected=False, lsh_y=380.0),
                frame_row(lsh_y=420.0, **NO_HIP),
                frame_row(face_x=700.0, lsh_y=410.0)]
        records = row_records(rows)
        result = agg.aggregate_f1_sample(records, support="family")
        self.assertEqual(dict(result.selected_frame_indices),
                         {"FS": (1, 3, 4), "SH": (1, 2, 4), "SO": (1, 2, 3, 4)})
        self.assertEqual(dict(result.feature_support),
                         {"fs_x": "FS", "fs_y": "FS", "sh_x": "SH", "sh_y": "SH", "so_beta": "SO"})
        self.assertEqual(dict(result.feature_n_used),
                         {"fs_x": 3, "fs_y": 3, "sh_x": 3, "sh_y": 3, "so_beta": 4})
        by_index = {r.frame_index: r.result.features for r in records}
        self.assertEqual(result.features["fs_y"], statistics.median(by_index[i]["fs_y"] for i in (1, 3, 4)))
        self.assertEqual(result.features["sh_y"], statistics.median(by_index[i]["sh_y"] for i in (1, 2, 4)))
        # explicitly reported: features of this sample summarise different frame subsets
        self.assertFalse(result.defined_features_same_frames)

    def test_joint_vs_family_differ_on_same_input(self):
        rows = [frame_row(),
                frame_row(face_detected=False, lsh_y=380.0),
                frame_row(lsh_y=420.0, face_x=600.0, **NO_HIP),
                frame_row(face_x=700.0, lsh_y=410.0)]
        joint = agg.aggregate_f1_sample(row_records(rows), support="joint")
        family = agg.aggregate_f1_sample(row_records(rows), support="family")
        # diagnostics independent of the policy are identical
        for field in ("n_frames", "family_valid_counts", "joint_valid_count", "coverage",
                      "valid_frame_indices", "invalid_reason_counts"):
            self.assertEqual(getattr(joint, field), getattr(family, field))
        self.assertNotEqual(joint.features["fs_x"], family.features["fs_x"])
        self.assertNotEqual(joint.features["so_beta"], family.features["so_beta"])
        self.assertLess(joint.feature_n_used["so_beta"], family.feature_n_used["so_beta"])
        self.assertTrue(joint.defined_features_same_frames)
        self.assertFalse(family.defined_features_same_frames)
        self.assertLessEqual(joint.joint_valid_count, min(joint.family_valid_counts.values()))

    def test_missing_hip_keeps_fs_and_so(self):
        rows = [frame_row(lsh_y=400.0 + i, **NO_HIP) for i in range(3)]
        rows.append(frame_row(right_hip_valid=None))
        family = agg.aggregate_f1_sample(row_records(rows), support="family")
        self.assertIsNone(family.features["sh_x"])
        self.assertIsNone(family.features["sh_y"])
        self.assertEqual(family.undefined_reasons["sh_x"], "no_supported_frames:SH")
        for name in ("fs_x", "fs_y", "so_beta"):
            self.assertIsNotNone(family.features[name])
            self.assertIsNone(family.undefined_reasons[name])
        self.assertEqual(family.family_valid_counts["SH"], 0)
        self.assertEqual(dict(family.invalid_reason_counts["SH"]),
                         {"left_hip_valid:false": 3, "right_hip_valid:unknown": 1})
        self.assertEqual(dict(family.invalid_reason_counts["FS"]), {})
        # same input under joint: SH is the limiting family, nothing is defined
        joint = agg.aggregate_f1_sample(row_records(rows), support="joint")
        self.assertEqual(joint.ordered_values(), (None,) * 5)
        self.assertEqual(dict(joint.family_valid_counts), {"FS": 4, "SH": 0, "SO": 4})


class MedianTests(unittest.TestCase):
    def test_component_wise_median_odd_even_and_outlier(self):
        odd = [(0.1, -1.0), (0.3, -0.9), (5.0, -50.0)]        # outlier frame 3
        result = agg.aggregate_f1_sample(
            [record(manual_result(fs=v, sh=v, so=0.0), i + 1) for i, v in enumerate(odd)],
            support="family")
        self.assertEqual((result.features["fs_x"], result.features["fs_y"]), (0.3, -1.0))
        even = odd + [(0.2, -0.95)]
        result = agg.aggregate_f1_sample(
            [record(manual_result(fs=v, sh=v, so=0.0), i + 1) for i, v in enumerate(even)],
            support="family")
        self.assertAlmostEqual(result.features["fs_x"], 0.25, places=15)
        self.assertAlmostEqual(result.features["fs_y"], -0.975, places=15)
        # component-wise: the median vector need not be any single frame's vector
        self.assertNotIn((result.features["sh_x"], result.features["sh_y"]), even)

    def test_geometry_before_aggregation(self):
        # Shoulder width varies per frame: median of per-frame ratios differs from
        # the ratio computed after averaging landmarks first (AC-4).
        rows = [frame_row(lsh_x=740.0, rsh_x=540.0, face_y=200.0),
                frame_row(lsh_x=840.0, rsh_x=440.0, face_y=200.0),
                frame_row(lsh_x=700.0, rsh_x=580.0, face_y=300.0)]
        records = row_records(rows)
        result = agg.aggregate_f1_sample(records, support="joint")
        per_frame = statistics.median(f1.compute_f1_5_frame(r).features["fs_y"] for r in rows)
        self.assertEqual(result.features["fs_y"], per_frame)
        averaged = {k: statistics.fmean(r[k] for r in rows) for k in rows[0]
                    if isinstance(rows[0][k], float)}
        landmarks_first = f1.compute_f1_5_frame(frame_row(**averaged)).features["fs_y"]
        self.assertGreater(abs(result.features["fs_y"] - landmarks_first), 1e-3)

    def test_single_frame_aggregates_no_hidden_n_min(self):
        records = row_records([frame_row()])
        result = agg.aggregate_f1_sample(records, support="joint")
        self.assertEqual(result.ordered_values(), records[0].result.ordered_values())
        self.assertAlmostEqual(result.so_beta_resultant, 1.0, places=15)


class AxialMeanTests(unittest.TestCase):
    def test_constant_angle(self):
        result = agg.aggregate_f1_sample(beta_records([0.3] * 4), support="family")
        self.assertAlmostEqual(result.features["so_beta"], 0.3, places=14)
        self.assertAlmostEqual(result.so_beta_resultant, 1.0, places=14)

    def test_period_pi_axial_mean(self):
        betas = [0.1, 0.2, 0.3]
        c = statistics.fmean(math.cos(2 * b) for b in betas)
        s = statistics.fmean(math.sin(2 * b) for b in betas)
        result = agg.aggregate_f1_sample(beta_records(betas), support="family")
        self.assertAlmostEqual(result.features["so_beta"], 0.5 * math.atan2(s, c), places=14)
        self.assertAlmostEqual(result.so_beta_resultant, math.hypot(c, s), places=14)
        self.assertLess(result.so_beta_resultant, 1.0)

    def test_wrap_boundary(self):
        eps = 0.01
        betas = [-math.pi / 2 + eps, math.pi / 2 - eps]
        result = agg.aggregate_f1_sample(beta_records(betas), support="family")
        beta = result.features["so_beta"]
        self.assertGreaterEqual(beta, -math.pi / 2)
        self.assertLess(beta, math.pi / 2)
        self.assertLess(axial_distance(beta, -math.pi / 2), 1e-12)     # vertical axis
        self.assertAlmostEqual(statistics.fmean(betas), 0.0, places=15)  # arithmetic mean fails
        self.assertGreater(axial_distance(beta, 0.0), 1.5)
        self.assertAlmostEqual(result.so_beta_resultant, math.cos(2 * eps), places=14)

    def test_axially_equivalent_inputs_give_same_mean(self):
        a = agg.aggregate_f1_sample(beta_records([-math.pi / 2, -math.pi / 2 + 0.2]), support="family")
        b = agg.aggregate_f1_sample(beta_records([math.pi / 2 - 0.2, -math.pi / 2 + 0.4]), support="family")
        self.assertLess(axial_distance(a.features["so_beta"], -math.pi / 2 + 0.1), 1e-12)
        self.assertLess(axial_distance(b.features["so_beta"], -math.pi / 2 + 0.1), 1e-12)

    def test_opposing_orientations_are_undefined(self):
        # beta = 0 and pi/2 (stored as -pi/2) cancel; float64 leaves R ~ 6e-17, not 0.
        for betas in ([0.0, -math.pi / 2], [0.0, -math.pi / 2, math.pi / 4, -math.pi / 4],
                      [0.25, 0.25 - math.pi / 2]):
            with self.subTest(betas=betas):
                result = agg.aggregate_f1_sample(beta_records(betas), support="family")
                self.assertIsNone(result.features["so_beta"])
                self.assertEqual(result.undefined_reasons["so_beta"],
                                 "axial_resultant_numerical_cancellation")
                self.assertGreater(result.so_beta_resultant, 0.0)
                self.assertLessEqual(result.so_beta_resultant, agg.AXIAL_CANCELLATION_GUARD)
                self.assertEqual(result.feature_n_used["so_beta"], len(betas))
                # other families still aggregate
                self.assertEqual(result.features["fs_y"], -1.0)

    def test_exact_zero_resultant_is_undefined(self):
        self.assertEqual(agg._axial_from_components(0.0, 0.0), (None, 0.0, "axial_resultant_zero"))
        self.assertEqual(agg._axial_from_components(-0.0, 0.0)[2], "axial_resultant_zero")

    def test_guard_is_numerical_not_a_research_r_min(self):
        self.assertLess(agg.AXIAL_CANCELLATION_GUARD, 1e-14)
        # small but numerically resolved dispersion stays defined (no hidden R_min)
        result = agg.aggregate_f1_sample(beta_records([0.0, -math.pi / 2 + 1e-6]), support="family")
        self.assertIsNotNone(result.features["so_beta"])
        self.assertLess(result.so_beta_resultant, 1e-5)
        self.assertGreater(result.so_beta_resultant, agg.AXIAL_CANCELLATION_GUARD)
        beta, r, reason = agg._axial_from_components(2 * agg.AXIAL_CANCELLATION_GUARD, 0.0)
        self.assertEqual((beta, reason), (0.0, None))


class ValidationTests(unittest.TestCase):
    def test_support_policy_is_required_and_checked(self):
        records = row_records([frame_row()])
        with self.assertRaises(TypeError):
            agg.aggregate_f1_sample(records)                       # no default policy
        for bad in ("hybrid", "Joint", "", None, ["joint"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    agg.aggregate_f1_sample(records, support=bad)
        with self.assertRaises(TypeError):
            agg.aggregate_f1_sample(records, "joint")              # keyword-only

    def test_empty_input(self):
        for support in agg.SUPPORT_POLICIES:
            with self.assertRaisesRegex(ValueError, "empty input"):
                agg.aggregate_f1_sample([], support=support)

    def test_mixed_sample_identity(self):
        for field, other in (("analysis_run_id", "run-B"), ("recording_id", "rec-B"),
                             ("step", "4"), ("subject", "S-other"), ("round", "2"),
                             ("round", None), ("label", "forward_head")):
            with self.subTest(field=field, other=other):
                records = row_records([frame_row()] * 2)
                records.append(record(records[0].result, 3, **{field: other}))
                with self.assertRaisesRegex(ValueError, f"conflicting sample identity {field}"):
                    agg.aggregate_f1_sample(records, support="family")

    def test_unknown_round_is_kept_unknown(self):
        result = agg.aggregate_f1_sample(row_records([frame_row()] * 2, round=None), support="family")
        self.assertIsNone(result.round)

    def test_duplicate_frame_keys(self):
        records = row_records([frame_row(), frame_row(lsh_y=380.0)])
        records.append(record(records[0].result, 2))
        with self.assertRaisesRegex(ValueError, "duplicate frame keys"):
            agg.aggregate_f1_sample(records, support="joint")

    def test_invalid_record_metadata(self):
        result = f1.compute_f1_5_frame(frame_row())
        for overrides in ({"frame_index": 0}, {"frame_index": True}, {"frame_index": 1.0},
                          {"frame_index": "1"}, {"recording_id": ""}, {"analysis_run_id": None},
                          {"step": 3}, {"subject": ""}, {"label": None}, {"round": 1},
                          {"round": ""}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    record(result, overrides.pop("frame_index", 1), **overrides)

    def test_non_record_items_rejected(self):
        with self.assertRaises(ValueError):
            agg.aggregate_f1_sample([f1.compute_f1_5_frame(frame_row())], support="joint")
        with self.assertRaises(ValueError):
            agg.aggregate_f1_sample(row_records([frame_row()]) + [frame_row()], support="joint")

    def test_malformed_frame_results(self):
        good = f1.compute_f1_5_frame(frame_row())
        no_hip = f1.compute_f1_5_frame(frame_row(**NO_HIP))

        def variant(base, features=None, available=None, reasons=None):
            return f1.F1FrameResult(
                features=dict(base.features, **(features or {})),
                family_available=dict(base.family_available, **(available or {})),
                family_reasons=dict(base.family_reasons, **(reasons or {})))

        cases = {
            "available feature is None": variant(good, features={"fs_x": None}),
            "available feature is NaN": variant(good, features={"sh_y": math.nan}),
            "available feature is inf": variant(good, features={"fs_y": math.inf}),
            "available feature not float": variant(good, features={"fs_x": "0.0"}),
            "available feature is int": variant(good, features={"fs_x": 0}),
            "unavailable feature has value": variant(no_hip, features={"sh_x": 0.0}),
            "unavailable feature has zero": variant(no_hip, features={"sh_x": 0.0, "sh_y": 0.0}),
            "flag not bool": variant(good, available={"FS": 1}),
            "available with reasons": variant(good, reasons={"FS": ("x",)}),
            "unavailable without reasons": variant(no_hip, reasons={"SH": ()}),
            "reasons not tuple": variant(no_hip, reasons={"SH": ["left_hip_valid:false"]}),
            "so_beta out of range": variant(good, features={"so_beta": math.pi / 2}),
            "missing feature key": f1.F1FrameResult(
                features={k: v for k, v in good.features.items() if k != "so_beta"},
                family_available=good.family_available, family_reasons=good.family_reasons),
            "extra family key": variant(good, available={"XX": True}),
            "not a frame result": {"features": dict(good.features)},
        }
        for name, bad in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    record(bad, 1)

    def test_missing_observation_is_not_malformed(self):
        rows = [frame_row(**NO_HIP), frame_row(face_detected=None), frame_row(rsh_x=740.0)]
        result = agg.aggregate_f1_sample(row_records(rows), support="family")
        self.assertEqual(dict(result.family_valid_counts), {"FS": 1, "SH": 1, "SO": 2})
        self.assertEqual(result.invalid_reason_counts["SO"]["d_sh:zero"], 1)
        self.assertEqual(result.invalid_reason_counts["FS"]["face_detected:unknown"], 1)


class ResultContractTests(unittest.TestCase):
    def test_provenance_preserved(self):
        rows = [frame_row(), frame_row(lsh_y=380.0)]
        records = [record(f1.compute_f1_5_frame(r), idx, analysis_run_id="run-X", recording_id="rec-Y",
                          subject="P07-synthetic", round="2", step="11", label="body_forward")
                   for r, idx in zip(rows, (42, 17))]
        result = agg.aggregate_f1_sample(records, support="joint")
        self.assertEqual(result.sample_key, ("run-X", "rec-Y", "11"))
        self.assertEqual((result.subject, result.round, result.label), ("P07-synthetic", "2", "body_forward"))
        self.assertEqual(result.input_frame_indices, (17, 42))
        self.assertEqual(result.valid_frame_indices["joint"], (17, 42))
        self.assertEqual(result.aggregation_spec, agg.F1_AGGREGATION_SPEC_ID)
        self.assertEqual(result.source_decision, "FEAT-009")

    def test_labels_do_not_enter_calculation(self):
        rows = [frame_row(lsh_y=380.0 + 7 * i, face_x=600.0 + 13 * i) for i in range(3)]
        a = agg.aggregate_f1_sample(row_records(rows, label="upright"), support="family")
        b = agg.aggregate_f1_sample(row_records(rows, label="body_forward"), support="family")
        self.assertEqual(a.ordered_values(), b.ordered_values())
        self.assertEqual(a.so_beta_resultant, b.so_beta_resultant)

    def test_undefined_reason_reporting(self):
        rows = [frame_row(face_detected=False, **NO_HIP)]
        family = agg.aggregate_f1_sample(row_records(rows), support="family")
        self.assertEqual(dict(family.undefined_reasons), {
            "fs_x": "no_supported_frames:FS", "fs_y": "no_supported_frames:FS",
            "sh_x": "no_supported_frames:SH", "sh_y": "no_supported_frames:SH", "so_beta": None})
        for name, value in family.features.items():
            self.assertEqual(value is None, family.undefined_reasons[name] is not None)

    def test_no_imputation_or_zero_replacement(self):
        rows = [frame_row(face_detected=False, **NO_HIP), frame_row(rsh_x=740.0)]
        for support in agg.SUPPORT_POLICIES:
            with self.subTest(support=support):
                result = agg.aggregate_f1_sample(row_records(rows), support=support)
                for name in ("fs_x", "fs_y", "sh_x", "sh_y"):
                    self.assertIsNone(result.features[name])
                    self.assertNotEqual(result.features[name], 0.0)
                    self.assertEqual(result.feature_n_used[name], 0)
                for value in result.ordered_values():
                    self.assertTrue(value is None or math.isfinite(value))
        # a valid frame with genuine 0.0 values stays 0.0 and is not confused with missing
        zero = agg.aggregate_f1_sample(row_records([frame_row()]), support="family")
        self.assertEqual(zero.features["fs_x"], 0.0)
        self.assertIsNone(zero.undefined_reasons["fs_x"])

    def test_order_invariance_and_inputs_unchanged(self):
        rows = [frame_row(face_x=600.0 + 9 * i, lsh_y=370.0 + 11 * i,
                          **(NO_HIP if i % 3 == 0 else {})) for i in range(9)]
        records = row_records(rows)
        snapshot = [(r.frame_key, r.result.ordered_values()) for r in records]
        expected = agg.aggregate_f1_sample(records, support="family")
        shuffled = list(records)
        random.Random(1234).shuffle(shuffled)
        self.assertEqual(agg.aggregate_f1_sample(shuffled, support="family"), expected)
        self.assertEqual([(r.frame_key, r.result.ordered_values()) for r in records], snapshot)
        # generators are accepted
        self.assertEqual(agg.aggregate_f1_sample(iter(records), support="family"), expected)

    def test_result_is_immutable(self):
        result = agg.aggregate_f1_sample(row_records([frame_row(**NO_HIP)]), support="family")
        with self.assertRaises(FrozenInstanceError):
            result.support_policy = "joint"
        with self.assertRaises(TypeError):
            result.features["sh_x"] = 0.0
        with self.assertRaises(TypeError):
            result.invalid_reason_counts["SH"]["left_hip_valid:false"] = 0
        self.assertNotIn("eligible", {f for f in vars(result)})

    def test_synthetic_forward_like_partial_hip_loss(self):
        # SYNTHETIC illustration only: hips invalid in half of the frames.
        rows = [frame_row(lsh_y=420.0, rsh_y=420.0, face_y=260.0,
                          **(NO_HIP if i % 2 else {})) for i in range(6)]
        family = agg.aggregate_f1_sample(row_records(rows), support="family")
        joint = agg.aggregate_f1_sample(row_records(rows), support="joint")
        self.assertEqual(family.coverage["SH"], 0.5)
        self.assertEqual(family.coverage["FS"], 1.0)
        self.assertEqual(joint.coverage["joint"], 0.5)
        self.assertEqual(family.feature_n_used["so_beta"], 6)
        self.assertEqual(joint.feature_n_used["so_beta"], 3)


if __name__ == "__main__":
    unittest.main()
