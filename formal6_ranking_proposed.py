"""B6 proposal only: synthetic review, PENDING_USER_APPROVAL.

Not imported by the official evaluator. Full ranking repeatedly selects a winner
from the remaining candidates; each selection restarts at Macro-F1. Only the
first selection uses all five candidates. No pairwise epsilon sorting is used.
"""

from collections.abc import Mapping
import math

from formal6_evaluation import CANDIDATES, FEATURES, TIE_TOLERANCE


def rank_candidates_proposed(scores):
    """Review-only score mapping -> status/reasons/ranking/recommendation.

    Keep the original six-recall shape and COMPLETE/finite ranking-score guards.
    Malformed containers/nonnumeric ranking scores fail closed instead of raising
    the original incidental TypeError/AttributeError. A mapping cannot represent
    duplicate IDs; sequence inputs are rejected, never coerced to a dict.
    """
    def blocked(reason):
        return dict(status="BLOCKED", reasons=(reason,), ranking=(), recommendation=None)

    ids = tuple(c[0] for c in CANDIDATES)
    if not isinstance(scores, Mapping) or set(scores) != set(ids):
        return blocked("all_five_approved_candidates_required")
    values = {}
    for name in ids:
        score = scores[name]
        if not isinstance(score, Mapping):
            return blocked("incomplete_candidate_scores:" + name)
        recall = score.get("mean_recall", ())
        if not isinstance(recall, (list, tuple)) or len(recall) != 6:
            return blocked("six_class_recall_required:" + name)
        row = (score.get("mean_macro_f1"), *(recall[k] for k in (0, 1, 5)), score.get("mean_accuracy"))
        try:
            finite = all(v is not None and math.isfinite(v) for v in row)
        except (TypeError, ValueError, OverflowError):
            finite = False
        if score.get("status") != "COMPLETE" or not finite:
            return blocked("incomplete_candidate_scores:" + name)
        values[name] = row

    feature_counts = {name: len(FEATURES[feature]) for name, feature, _ in CANDIDATES}
    remaining, ranking = list(ids), []
    while remaining:
        survivors = list(remaining)
        for column in range(5):
            best = max(values[name][column] for name in survivors)
            survivors = [name for name in survivors
                         if abs(best - values[name][column]) <= TIE_TOLERANCE]
            if len(survivors) == 1:
                break
        fewest = min(feature_counts[name] for name in survivors)
        # survivors retains the frozen ID order, independently of mapping order.
        winner = next(name for name in survivors if feature_counts[name] == fewest)
        ranking.append(winner)
        remaining.remove(winner)
    return dict(status="PROPOSED_REVIEW_ONLY", ranking=tuple(ranking),
                recommendation=ranking[0], reasons=())
