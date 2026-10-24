"""Synthetic structural tests for the H5/H9/B5 evaluation path.

No exploratory or captured CSV is used here, and no accuracy value from these
tests is research evidence.
"""

import math
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

import f1_features
import f1_sample_aggregator as agg
import rf_experiment as rf
from test_f1_features import frame_row


def h_features(index=0, *, angle=10.0, missing=()):
    values = {
        name: float(index + position + 1) / 10.0
        for position, name in enumerate(agg.H9_FEATURE_NAMES)
    }
    values[agg.H_FACE_AXIS_FEATURE] = float(angle)
    for name in missing:
        values[name] = None
    return values


def h_record(index, *, subject="P01", step="1", label="upright", features=None):
    return agg.HFrameRecord(
        analysis_run_id=f"run-{subject}",
        recording_id=f"rec-{subject}",
        frame_index=index,
        subject=subject,
        round="1",
        step=step,
        label=label,
        features=h_features(index) if features is None else features,
    )


class HAggregationTests(unittest.TestCase):
    def test_exact_threshold_and_shared_nine_feature_support(self):
        records = []
        for index in range(1, 61):
            missing = () if index <= 30 else (agg.H9_RGBD_FEATURE_NAMES[0],)
            features = h_features(index, angle=179.0 if index % 2 else -179.0,
                                  missing=missing)
            if index > 30:
                features[agg.H5_FEATURE_NAMES[0]] = 10000.0
            records.append(h_record(index, features=features))
        result = agg.aggregate_h5_h9_sample(records)

        self.assertTrue(result.eligible)
        self.assertEqual(result.common_valid_count, 30)
        self.assertEqual(result.common_coverage, 0.5)
        self.assertEqual(result.common_valid_frame_indices, tuple(range(1, 31)))
        self.assertEqual(len(result.ordered_values("H5")), 5)
        self.assertEqual(len(result.ordered_values("H9")), 9)
        self.assertAlmostEqual(result.features[agg.H5_FEATURE_NAMES[0]], 1.65)
        self.assertAlmostEqual(abs(result.features[agg.H_FACE_AXIS_FEATURE]), 180.0)

    def test_minimum_frames_and_coverage_fail_closed(self):
        too_few = agg.aggregate_h5_h9_sample(
            [h_record(index) for index in range(1, 30)]
        )
        self.assertFalse(too_few.eligible)
        self.assertIn("common_valid_frames<30", too_few.eligibility_reasons)
        with self.assertRaisesRegex(ValueError, "ineligible H sample"):
            too_few.ordered_values("H5")

        records = [h_record(index) for index in range(1, 31)]
        records += [
            h_record(index, features=h_features(
                index, missing=(agg.H9_RGBD_FEATURE_NAMES[0],)
            ))
            for index in range(31, 62)
        ]
        low_coverage = agg.aggregate_h5_h9_sample(records)
        self.assertEqual(low_coverage.common_valid_count, 30)
        self.assertLess(low_coverage.common_coverage, 0.5)
        self.assertFalse(low_coverage.eligible)
        self.assertIn("common_coverage<0.5", low_coverage.eligibility_reasons)

    def test_circular_mean_is_not_scalar_median(self):
        angles = [170.0] * 10 + [-170.0] * 20
        result = agg.aggregate_h5_h9_sample([
            h_record(index, features=h_features(index, angle=angle))
            for index, angle in enumerate(angles, 1)
        ])
        self.assertTrue(result.eligible)
        circular = result.features[agg.H_FACE_AXIS_FEATURE]
        self.assertGreater(abs(circular), 170.0)
        self.assertNotEqual(circular, -170.0)

    def test_one_missing_h9_value_excludes_frame_from_h5_too(self):
        records = [h_record(index) for index in range(1, 31)]
        excluded = h_features(31, missing=(agg.H9_RGBD_FEATURE_NAMES[-1],))
        excluded[agg.H5_FEATURE_NAMES[0]] = -9999.0
        records.append(h_record(31, features=excluded))
        result = agg.aggregate_h5_h9_sample(records)
        self.assertEqual(result.common_valid_count, 30)
        self.assertEqual(result.features[agg.H5_FEATURE_NAMES[0]], 1.65)
        self.assertNotIn(31, result.common_valid_frame_indices)


class HEvaluationTests(unittest.TestCase):
    @staticmethod
    def synthetic_matrices():
        X_h9, X_b5, y, participants = [], [], [], []
        for participant_index, participant in enumerate(("P01", "P02", "P03")):
            for label in range(5):
                for repeat in range(2):
                    base = label * 2.0 + participant_index * 0.1 + repeat * 0.01
                    X_h9.append([base + column * 0.07 for column in range(9)])
                    X_b5.append([base + column * 0.11 for column in range(5)])
                    y.append(label)
                    participants.append(participant)
        return np.array(X_h9), np.array(X_b5), np.array(y), np.array(participants)

    def test_fixed_loso_pairing_models_and_lambda_zero_equivalence(self):
        inputs = self.synthetic_matrices()
        with patch.object(rf, "H_EVAL_TREES", 4):
            result = rf.evaluate_h5_h9_b5_loso(*inputs)

        self.assertEqual(result["seeds"], (0, 1, 2, 3, 4))
        self.assertEqual(result["max_features"], 2)
        self.assertEqual(result["m2_lambda"], 0.5)
        self.assertEqual(len(result["folds"]), 15)
        for fold in result["folds"]:
            self.assertFalse(set(fold["train_indices"]) & set(fold["test_indices"]))
            self.assertEqual(set(fold["lambda_zero_equivalent"]), {"H5", "H9"})
            self.assertTrue(all(fold["lambda_zero_equivalent"].values()))
            self.assertTrue(all(value > 0 for values in fold["weights"].values()
                                for value in values))
        models = {(row["feature_set"], row["model"]) for row in result["metrics"]}
        self.assertEqual(models, {
            ("H5", "M0"), ("H5", "M1"), ("H5", "M2(λ=0.5)"),
            ("H9", "M0"), ("H9", "M1"), ("H9", "M2(λ=0.5)"),
            ("B5", "M0"), ("B5", "M1"), ("B5", "M2(λ=0.5)"),
        })
        self.assertEqual(result["blocked"], ())
        self.assertEqual(result["b5_availability"]["comparison_status"], "completed")
        self.assertEqual(result["b5_availability"]["eligible_common_sample_count"], 30)
        self.assertEqual(len(result["b5_folds"]), 15)
        self.assertTrue(all(fold["lambda_zero_equivalent"]
                            for fold in result["b5_folds"]))

    def test_p_le_6_preserved_and_p9_policy_b_weights(self):
        for p in range(1, 7):
            mdi = np.arange(p, dtype=float)
            legacy_rank = np.asarray(rf.PAPER_RANK_W[:p], dtype=float)
            if p < 6:
                legacy_rank /= legacy_rank.sum()
            expected = np.zeros(p)
            for rank, column in enumerate(np.argsort(-mdi)):
                expected[column] = legacy_rank[rank]
            np.testing.assert_array_equal(rf.rank_weights(mdi), expected)

        raw_p9 = np.array([.30, .20, .15, .15, .15, .05, .05, .05, .05])
        mdi = np.arange(9, dtype=float)[::-1]
        np.testing.assert_allclose(rf.rank_weights(mdi), raw_p9 / raw_p9.sum())
        self.assertAlmostEqual(float(rf.rank_weights(mdi).sum()), 1.0)

        for p in (7, 8, 10):
            with self.assertRaisesRegex(ValueError, "only for p<=6 or p=9"):
                rf.rank_weights(np.arange(p, dtype=float))

    def test_mdi_ties_use_ascending_feature_column_index(self):
        raw_p9 = np.array([.30, .20, .15, .15, .15, .05, .05, .05, .05])
        expected = raw_p9 / raw_p9.sum()
        for _ in range(5):
            np.testing.assert_array_equal(rf.rank_weights(np.ones(9)), expected)

    def test_held_out_features_cannot_change_training_fold_weights(self):
        X_h9, X_b5, y, participants = self.synthetic_matrices()
        changed_h9, changed_b5 = X_h9.copy(), X_b5.copy()
        held_out = participants == "P01"
        changed_h9[held_out] += 10000.0
        changed_b5[held_out] -= 10000.0
        with patch.object(rf, "H_EVAL_TREES", 3):
            original = rf.evaluate_h5_h9_b5_loso(X_h9, X_b5, y, participants)
            changed = rf.evaluate_h5_h9_b5_loso(
                changed_h9, changed_b5, y, participants
            )
        original_folds = [
            fold for fold in original["folds"]
            if fold["held_out_participant"] == "P01"
        ]
        changed_folds = [
            fold for fold in changed["folds"]
            if fold["held_out_participant"] == "P01"
        ]
        self.assertEqual(
            [fold["weights"] for fold in original_folds],
            [fold["weights"] for fold in changed_folds],
        )

    def test_b5_missingness_does_not_block_or_shrink_primary_h_evaluation(self):
        X_h9, X_b5, y, participants = self.synthetic_matrices()
        unavailable_b5 = X_b5.copy()
        unavailable_b5[participants == "P01"] = np.nan
        with patch.object(rf, "H_EVAL_TREES", 3):
            complete = rf.evaluate_h5_h9_b5_loso(X_h9, X_b5, y, participants)
            partial = rf.evaluate_h5_h9_b5_loso(
                X_h9, unavailable_b5, y, participants
            )
            absent = rf.evaluate_h5_h9_b5_loso(
                X_h9, y=y, participants=participants
            )

        primary = lambda result: [
            row for row in result["metrics"]
            if row["evaluation_scope"] == "primary"
        ]
        self.assertEqual(primary(partial), primary(complete))
        self.assertEqual(primary(absent), primary(complete))
        self.assertEqual(partial["sample_count"], 30)
        self.assertEqual(absent["sample_count"], 30)
        self.assertEqual(partial["b5_availability"]["eligible_common_sample_count"], 20)
        self.assertEqual(partial["b5_availability"]["comparison_status"], "completed")
        self.assertEqual(absent["b5_availability"]["comparison_status"], "not_run")
        self.assertEqual(absent["b5_folds"], [])

    def test_aggregate_adapter_requires_exact_same_samples(self):
        h_samples, b5_samples = [], []
        for participant in ("P01", "P02"):
            for step, label in enumerate(rf.LAB5, 1):
                h_samples.append(agg.aggregate_h5_h9_sample([
                    h_record(index, subject=participant, step=str(step), label=label)
                    for index in range(1, 31)
                ]))
                f1_result = f1_features.compute_f1_5_frame(frame_row())
                b5_samples.append(agg.aggregate_f1_sample([
                    agg.F1FrameRecord(
                        analysis_run_id=f"run-{participant}",
                        recording_id=f"rec-{participant}",
                        frame_index=1,
                        subject=participant,
                        round="1",
                        step=str(step),
                        label=label,
                        result=f1_result,
                    )
                ], support="joint"))

        with patch.object(rf, "evaluate_h5_h9_b5_loso", return_value="called") as evaluate:
            self.assertEqual(rf.evaluate_h5_h9_b5_samples(h_samples, b5_samples), "called")
        X_h9, X_b5, labels, participants = evaluate.call_args.args
        self.assertEqual(np.asarray(X_h9).shape, (10, 9))
        self.assertEqual(np.asarray(X_b5).shape, (10, 5))
        self.assertEqual(set(labels), set(range(5)))
        self.assertEqual(set(participants), {"P01", "P02"})

        with patch.object(rf, "evaluate_h5_h9_b5_loso", return_value="called") as evaluate:
            self.assertEqual(
                rf.evaluate_h5_h9_b5_samples(h_samples, b5_samples[:-1]),
                "called",
            )
        X_h9, X_b5, labels, participants = evaluate.call_args.args
        self.assertEqual(np.asarray(X_h9).shape, (10, 9))
        self.assertEqual(np.asarray(X_b5).shape, (10, 5))
        self.assertEqual(np.isnan(np.asarray(X_b5)).all(axis=1).sum(), 1)

        hip_missing_features = dict(b5_samples[0].features)
        hip_missing_features["sh_x"] = None
        hip_missing_features["sh_y"] = None
        hip_missing_b5 = [
            replace(b5_samples[0], features=hip_missing_features),
            *b5_samples[1:],
        ]
        with patch.object(rf, "evaluate_h5_h9_b5_loso", return_value="called") as evaluate:
            self.assertEqual(
                rf.evaluate_h5_h9_b5_samples(h_samples, hip_missing_b5),
                "called",
            )
        self.assertTrue(np.isnan(np.asarray(evaluate.call_args.args[1])[0]).all())

        with patch.object(rf, "evaluate_h5_h9_b5_loso", return_value="called") as evaluate:
            self.assertEqual(rf.evaluate_h5_h9_b5_samples(h_samples), "called")
        self.assertIsNone(evaluate.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
