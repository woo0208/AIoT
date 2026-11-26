"""SYNTHETIC STRUCTURAL ONLY: no training, prediction, or research-data access."""

import copy
from functools import cmp_to_key
import itertools
import math
import random
import unittest
from unittest.mock import patch

import numpy as np
import formal6_evaluation as ev
from formal6_ranking_proposed import rank_candidates_proposed as proposed

IDS = tuple(c[0] for c in ev.CANDIDATES)
A, B, C, D, E = IDS


def scores_equal(value=0.5):
    return {name: dict(status="COMPLETE", mean_macro_f1=value,
                      mean_recall=(value,) * 6, mean_accuracy=value) for name in IDS}


def set_metric(scores, name, column, value):
    if column == 0:
        scores[name]["mean_macro_f1"] = value
    elif column == 4:
        scores[name]["mean_accuracy"] = value
    else:
        recall = list(scores[name]["mean_recall"])
        recall[(0, 1, 5)[column - 1]] = value
        scores[name]["mean_recall"] = tuple(recall)


def two_candidates():
    scores = scores_equal(0.1)
    for name in (A, B):
        scores[name] = copy.deepcopy(scores_equal()[name])
    return scores


def chain_scores():
    scores = scores_equal(0.1)
    for name, delta, recall in ((A, 0.0, 0.9), (B, 0.75e-12, 0.8), (C, 1.5e-12, 0.7)):
        scores[name].update(mean_macro_f1=0.5 + delta, mean_recall=(recall,) * 6)
    return scores


def original_comparator(scores):
    """Capture the actual original closure, rather than reimplementing it."""
    captured = []
    def capture(compare):
        captured.append(compare)
        return cmp_to_key(compare)
    with patch.object(ev, "cmp_to_key", side_effect=capture):
        result = ev.rank_candidates(scores)
    return captured[0], result


class ProposedRankingTests(unittest.TestCase):
    def winner(self, scores):
        result = proposed(scores)
        self.assertEqual(result["status"], "PROPOSED_REVIEW_ONLY")
        self.assertEqual(set(result["ranking"]), set(IDS))
        self.assertEqual(len(result["ranking"]), 5)
        self.assertEqual(result["recommendation"], result["ranking"][0])
        return result["recommendation"]

    def test_T01_clear_macro_winner(self):
        scores = scores_equal()
        scores[C]["mean_macro_f1"] = 0.8
        self.assertEqual(self.winner(scores), C)

    def test_T02_exact_macro_tie(self):
        scores = two_candidates()
        set_metric(scores, B, 1, 0.8)
        self.assertEqual(self.winner(scores), B)

    def test_T03_difference_below_epsilon(self):
        scores = two_candidates()
        set_metric(scores, B, 0, 0.5 + 0.75e-12)
        set_metric(scores, A, 1, 0.9)
        self.assertLess(scores[B]["mean_macro_f1"] - 0.5, ev.TIE_TOLERANCE)
        self.assertEqual(self.winner(scores), A)

    def test_T04_difference_above_epsilon(self):
        scores = two_candidates()
        set_metric(scores, B, 0, 0.5 + 1.5e-12)
        set_metric(scores, A, 1, 0.9)
        self.assertEqual(self.winner(scores), B)

    def test_T05_actual_binary_boundaries_all_metrics(self):
        below = 0.5 + ev.TIE_TOLERANCE
        above = math.nextafter(below, math.inf)
        self.assertLess(below - 0.5, ev.TIE_TOLERANCE)
        self.assertGreater(above - 0.5, ev.TIE_TOLERANCE)
        for column in range(5):
            for high, expected in ((math.nextafter(below, -math.inf), A), (below, A), (above, B)):
                with self.subTest(column=column, high=high.hex()):
                    scores = two_candidates()
                    set_metric(scores, B, column, high)
                    self.assertEqual(self.winner(scores), expected)
        # Exact binary-float equality to the epsilon value, inclusive <= boundary.
        for high, expected in ((ev.TIE_TOLERANCE, A), (math.nextafter(ev.TIE_TOLERANCE, math.inf), B)):
            scores = two_candidates()
            set_metric(scores, A, 0, 0.0)
            set_metric(scores, B, 0, high)
            for name in (C, D, E):
                set_metric(scores, name, 0, 0.0)
                set_metric(scores, name, 1, 0.0)
            self.assertEqual(self.winner(scores), expected)

    def test_T06_chain_discards_A_before_recalls(self):
        scores = chain_scores()
        self.assertEqual(ev.rank_candidates(scores)["recommendation"], A)
        self.assertEqual(self.winner(scores), B)
        self.assertEqual(proposed(scores)["ranking"][:3], (B, C, A))

    def test_T07_all_120_five_candidate_permutations(self):
        scores = chain_scores()
        results = [proposed({name: scores[name] for name in order}) for order in itertools.permutations(IDS)]
        self.assertEqual(len(results), 120)
        self.assertEqual({r["recommendation"] for r in results}, {B})
        self.assertEqual({r["ranking"] for r in results}, {(B, C, A, D, E)})

    def test_T08_permutations_for_each_metric_and_final_ties(self):
        for column in range(5):
            scores = scores_equal()
            set_metric(scores, C, column, 0.9)
            for order in itertools.permutations(IDS):
                self.assertEqual(self.winner({name: scores[name] for name in order}), C)
        scores = scores_equal()
        for order in itertools.permutations(IDS):
            self.assertEqual(self.winner({name: scores[name] for name in order}), D)

    def metric_winner(self, column):
        scores = two_candidates()
        set_metric(scores, B, column, 0.8)
        # Later metrics must not bring the eliminated A back into consideration.
        for later in range(column + 1, 5):
            set_metric(scores, A, later, 1.0)
        self.assertEqual(self.winner(scores), B)

    def test_T09_p0_recall(self):
        self.metric_winner(1)

    def test_T10_p1_recall(self):
        self.metric_winner(2)

    def test_T11_p5_recall(self):
        self.metric_winner(3)

    def test_T12_accuracy(self):
        self.metric_winner(4)

    def test_T13_fewer_features(self):
        self.assertEqual(self.winner(scores_equal()), D)

    def test_T14_frozen_order_for_equal_dimensions(self):
        scores = scores_equal()
        for name in (D, E):
            scores[name]["mean_macro_f1"] = 0.1
        self.assertEqual(self.winner(scores), A)
        self.assertEqual(IDS, ("RF_M0_H9", "RF_M1_H9", "RF_M2_H9", "RF_M0_H9-F9", "LR_B0_H9-F9"))

    def test_T15_invalid_scores_fail_closed(self):
        for column in range(5):
            for value in (None, "N/A", float("nan"), float("inf"), -float("inf")):
                with self.subTest(column=column, value=value):
                    scores = scores_equal()
                    set_metric(scores, A, column, value)
                    self.assertEqual(proposed(scores)["status"], "BLOCKED")
                    self.assertIsNone(proposed(scores)["recommendation"])
        for recall in (None, "N/A", (), (0.5,) * 5, (0.5,) * 7):
            scores = scores_equal()
            scores[A]["mean_recall"] = recall
            self.assertEqual(proposed(scores)["status"], "BLOCKED")
        for malformed in (None, "N/A", {}):
            scores = scores_equal()
            scores[A] = malformed
            self.assertEqual(proposed(scores)["status"], "BLOCKED")
        scores = scores_equal()
        scores[A]["status"] = "INCOMPLETE"
        self.assertEqual(proposed(scores)["status"], "BLOCKED")

    def test_T16_missing_duplicate_unknown_ids(self):
        scores = scores_equal()
        missing = dict(scores); missing.pop(A)
        unknown = dict(scores); unknown["UNKNOWN"] = unknown.pop(A)
        extra = dict(scores); extra["RF_M0_F0"] = scores[A]
        duplicate_pairs = list(scores.items()) + [(A, scores[A])]
        for invalid in (None, missing, unknown, extra, duplicate_pairs):
            result = proposed(invalid)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["ranking"], ())

    def test_T17_seed_summary_and_score_contract_no_fit(self):
        # Already-constructed synthetic labels, NOT outputs of model inference.
        y = np.tile(np.arange(6), 3)
        predictions = [y.copy(), np.roll(y, 1), np.where(y == 0, 1, y)]
        rf_summary = ev._summary(y, predictions, ev.SEEDS)
        self.assertEqual(ev.SEEDS, (0, 1, 2))
        self.assertEqual([r["seed"] for r in rf_summary["per_seed"]], [0, 1, 2])
        for key, mean_key in (("macro_f1", "mean_macro_f1"), ("accuracy", "mean_accuracy")):
            self.assertAlmostEqual(rf_summary[mean_key], sum(r[key] for r in rf_summary["per_seed"]) / 3)
        for k in range(6):
            self.assertAlmostEqual(rf_summary["mean_recall"][k],
                sum(r["per_class"][k]["recall"] for r in rf_summary["per_seed"]) / 3)
        for p, row in zip(predictions, rf_summary["per_seed"]):
            self.assertEqual(row["sample_count"], 18)
            self.assertEqual(row["macro_f1"], ev.metrics6(y, p)["macro_f1"])
        lr_summary = ev._summary(y, [predictions[2]], (0,))
        self.assertEqual(len(lr_summary["per_seed"]), 1)
        self.assertEqual(lr_summary["per_seed"][0]["seed"], 0)
        # Unequal synthetic fold sizes: pooled OOF metric is not fold-metric mean.
        pooled_prediction = np.concatenate((np.roll(y[:6], 1), y[6:]))
        pooled = ev._summary(y, [pooled_prediction], (0,))
        fold_mean = (ev.metrics6(y[:6], pooled_prediction[:6])["macro_f1"]
                     + ev.metrics6(y[6:], pooled_prediction[6:])["macro_f1"]) / 2
        self.assertNotAlmostEqual(pooled["mean_macro_f1"], fold_mean)
        aligned = dict(y=y, participants=np.array(["SYN-A"] * 6 + ["SYN-B"] * 12),
                       development_subjects=("SYN-A", "SYN-B"),
                       sessions=np.array(["S1"] * 6 + ["S2"] * 12))
        for name, feature, model in ev.CANDIDATES:
            seeds = (0,) if model == "LR_B0" else ev.SEEDS
            values = [pooled_prediction] if model == "LR_B0" else predictions
            report = ev._prediction_report(aligned, values, seeds, feature, model)
            self.assertEqual(len(report["predictions"]), 1 if model == "LR_B0" else 3)
            self.assertEqual([r["seed"] for r in report["pooled"]["per_seed"]], list(seeds))
            self.assertEqual(ev.frozen_settings(name)["seeds"], list(seeds))
        scores = {name: copy.deepcopy(lr_summary if name == E else rf_summary) for name in IDS}
        self.winner(scores)
        incomplete = ev._summary(np.array([0, 1]), [np.array([0, 0])], (0,))
        self.assertIsNone(incomplete["mean_macro_f1"])
        scores[A] = incomplete
        self.assertEqual(proposed(scores)["status"], "BLOCKED")

    def test_T18_original_normal_cases_equivalent(self):
        cases = [scores_equal(), two_candidates()]
        for column in range(5):
            scores = two_candidates()
            set_metric(scores, B, column, 0.8)
            cases.append(scores)
        near = two_candidates()
        set_metric(near, A, 0, 0.5 + 0.5e-12)
        set_metric(near, A, 1, 0.6)
        cases.append(near)
        rng = random.Random(20261105)  # Local structural fixture, no research seed changes.
        for _ in range(100):
            scores = scores_equal()
            for name, value in zip(IDS, rng.sample(range(1, 1000), 5)):
                scores[name]["mean_macro_f1"] = value / 1000
            cases.append(scores)
        for scores in cases:
            self.assertEqual(proposed(scores)["ranking"], ev.rank_candidates(scores)["ranking"])

    def test_T19_input_objects_unchanged(self):
        scores = chain_scores()
        before = copy.deepcopy(scores)
        objects = tuple(id(scores[name]) for name in IDS)
        proposed(scores)
        self.assertEqual(scores, before)
        self.assertEqual(tuple(id(scores[name]) for name in IDS), objects)

    def test_T20_repeated_calls_deterministic(self):
        scores = chain_scores()
        expected = proposed(scores)
        for _ in range(100):
            self.assertEqual(proposed(scores), expected)


class OriginalReproductionTests(unittest.TestCase):
    def test_actual_pairwise_cycle(self):
        compare, result = original_comparator(chain_scores())
        self.assertEqual(result["recommendation"], A)
        self.assertLess(compare(A, B), 0)
        self.assertLess(compare(B, C), 0)
        self.assertLess(compare(C, A), 0)
        for left, right in itertools.combinations(IDS, 2):
            self.assertEqual(compare(left, right), -compare(right, left))

    def test_actual_mapping_order_is_fixed_but_comparator_sort_is_unstable(self):
        scores = chain_scores()
        compare, result = original_comparator(scores)
        actual, diagnostic = set(), set()
        for order in itertools.permutations(IDS):
            actual.add(ev.rank_candidates({name: scores[name] for name in order})["ranking"])
            diagnostic.add(tuple(sorted(order, key=cmp_to_key(compare))))
        self.assertEqual(actual, {result["ranking"]})
        self.assertGreater(len({r[0] for r in diagnostic}), 1)

    def test_original_repeated_calls_deterministic(self):
        scores = chain_scores()
        expected = ev.rank_candidates(scores)
        for _ in range(100):
            self.assertEqual(ev.rank_candidates(scores), expected)


if __name__ == "__main__":
    unittest.main()
