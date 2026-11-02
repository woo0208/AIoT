"""5-D-9 development-only six-class evaluation and frozen held-out access gate.

Reuses existing RF, LR B0 and complete-class metrics. No data loader, capture,
artifact writes, final refit or automatic held-out evaluation is invoked here.
"""

from dataclasses import dataclass
from functools import cmp_to_key, lru_cache
import importlib.util
import math
from pathlib import Path
import sys
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning

import rf_experiment as rf
import h6_offline as h6
from f1_sample_aggregator import H5_FEATURE_NAMES, H9_FEATURE_NAMES
import f0_fcal_features as f0


SEEDS = (0, 1, 2)
TREE_COUNT = 500  # Only tests patch this constant; no public tuning parameter.
TIE_TOLERANCE = 1e-12
FEATURES = {"F0": f0.FEATURE_NAMES, "F_cal": f0.FEATURE_NAMES,
            "H5": H5_FEATURE_NAMES, "H9": H9_FEATURE_NAMES, "H9-F9": H9_FEATURE_NAMES[:8]}
CANDIDATES = (("RF_M0_H9", "H9", "M0"), ("RF_M1_H9", "H9", "M1"),
              ("RF_M2_H9", "H9", "M2"), ("RF_M0_H9-F9", "H9-F9", "M0"),
              ("LR_B0_H9-F9", "H9-F9", "LR_B0"))
BASELINES = (("RF_M0_F0", "F0", "M0"), ("RF_M0_F_cal", "F_cal", "M0"),
             ("RF_M0_H5", "H5", "M0"))
REFERENCE_LR = Path(__file__).parent / "analysis/lr_feature_comparison_20261029_1a6c42/baseline.py"


def _finite_feature(value):
    return (not isinstance(value, (bool, np.bool_))
            and isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value))


@lru_cache(maxsize=1)
def _reference():
    # Match the existing formal8 reference import; don't retain its sys.path edit.
    previous = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("formal6_existing_lr_reference", REFERENCE_LR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous


@dataclass(frozen=True)
class Row:
    sample_key: tuple
    subject: str
    label: str
    session: str
    window: tuple | None  # (verified time_basis, start_s, end_s), exactly ten seconds.
    values: tuple
    eligible: bool
    review: str = "not_reviewable"
    reasons: tuple = ()
    support: tuple = ()


def _roster(subjects):
    subjects = tuple(subjects)
    if len(subjects) != 2 or len(set(subjects)) != 2 or any(not isinstance(s, str) or not s for s in subjects):
        raise ValueError("development requires exactly two explicit participant IDs")
    return subjects


def _check_development_only(rows, subjects):
    # Check participant metadata BEFORE accessing numerical values.
    if any(r.subject not in subjects for r in rows):
        raise ValueError("non-development participant input blocked before feature access")


def rows_from_f0(samples, timed_segments, review_states, development_subjects):
    """Bridge existing 5-D-4/6/7 results; retain source eligibility and support."""
    return _rows_from_f0(samples, timed_segments, review_states, _roster(development_subjects))


def _rows_from_f0(samples, timed_segments, review_states, subjects):
    """Shared bridge; held-out callers must enter through the frozen gate."""
    samples, timed_segments = tuple(samples), tuple(timed_segments)
    _check_development_only(samples, subjects)
    if any(t.segment.subject not in subjects for t in timed_segments):
        raise ValueError("held-out TimedSegment blocked")
    timing = {t.segment.key: t for t in timed_segments}
    if len(timing) != len(timed_segments):
        raise ValueError("duplicate timing key")
    result = {"F0": [], "F_cal": []}
    for s in samples:
        t = timing.get(s.sample_key)
        window = None
        if t is not None and t.time_basis and type(t.hold_end_s) in (int, float) and math.isfinite(t.hold_end_s):
            window = (t.time_basis, t.hold_end_s - 10, t.hold_end_s)
        for name, values in (("F0", s.f0), ("F_cal", s.f_cal)):
            result[name].append(Row(s.sample_key, s.subject, s.label, s.session, window, values,
                s.eligible, review_states.get(s.sample_key, "not_reviewable"), s.reasons, s.support_indices))
    return {k: tuple(v) for k, v in result.items()}


def rows_from_h(samples, windows, review_states, development_subjects, *, key_map=None):
    """Project existing H aggregates, never recalculate geometry/support.

    An explicit key_map may bind canonical string step to the same integer step;
    it may not silently relabel a recording/run or infer probe lineage.
    """
    return _rows_from_h(samples, windows, review_states, _roster(development_subjects), key_map=key_map)


def _rows_from_h(samples, windows, review_states, subjects, *, key_map=None):
    samples = tuple(samples)
    _check_development_only(samples, subjects)
    result = {name: [] for name in ("H5", "H9", "H9-F9")}
    for s in samples:
        key = (key_map or {}).get(s.sample_key, s.sample_key)
        if key[:2] != s.sample_key[:2] or str(key[2]) != str(s.sample_key[2]):
            raise ValueError("H key mapping requires exact recording/run/step binding")
        window, session = windows.get(key, (None, None))
        for name in result:
            result[name].append(Row(key, s.subject, s.label, session, window,
                tuple(s.features[k] for k in FEATURES[name]), s.eligible,
                review_states.get(key, "not_reviewable"), tuple(s.eligibility_reasons),
                tuple(s.common_valid_frame_indices)))
    return {k: tuple(v) for k, v in result.items()}


def align_development(families, development_subjects, reference_keys, *, feature_sets):
    """Exact segment intersection with full exclusion audit; no frame intersection."""
    subjects = _roster(development_subjects)
    result = _align_rows(families, subjects, reference_keys, feature_sets=feature_sets)
    result["development_subjects"] = subjects
    return result


def _align_rows(families, subjects, reference_keys, *, feature_sets):
    """Common numeric alignment, also used AFTER the four-person freeze gate."""
    if set(reference_keys) != set(subjects) or any(not isinstance(k, tuple) or len(k) != 3 for k in reference_keys.values()):
        raise ValueError("fixed first-P0 key required for each participant")
    names = tuple(feature_sets)
    if not names or len(set(names)) != len(names) or any(n not in FEATURES for n in names):
        raise ValueError("unknown or duplicate feature set")
    lookup, universe = {}, {}
    for name in names:
        rows = tuple(families.get(name, ()))
        _check_development_only(rows, subjects)
        lookup[name] = {}
        for r in rows:
            if r.sample_key in lookup[name]:
                raise ValueError("duplicate sample key in feature family")
            if not isinstance(r.sample_key, tuple) or len(r.sample_key) != 3:
                raise ValueError("exact three-part sample key required")
            label = h6.analysis_label(r.label)
            identity = (r.subject, label, r.session, r.window)
            if r.sample_key in universe and universe[r.sample_key] != identity:
                raise ValueError("cross-family participant/label/session/window mismatch")
            if r.sample_key == reference_keys[r.subject] and label != "upright":
                raise ValueError("reference key does not identify P0")
            universe[r.sample_key] = identity
            if len(r.values) != len(FEATURES[name]):
                raise ValueError(f"{name} requires exactly {len(FEATURES[name])} columns")
            lookup[name][r.sample_key] = r
    audit, accepted = [], []
    for key in sorted(universe):
        subject, label, session, window = universe[key]
        reasons = []
        if key == reference_keys[subject]:
            reasons.append("first_P0_reference_excluded_from_train_and_evaluation")
        if session not in ("S1", "S2"):
            reasons.append("session_unprocessed")
        if (not isinstance(window, tuple) or len(window) != 3 or not isinstance(window[0], str) or not window[0]
                or any(type(t) not in (int, float) or not math.isfinite(t) for t in window[1:])
                or window[2] - window[1] != 10):
            reasons.append("verified_ten_second_window_missing")
        family_audit = {}
        for name in names:
            r = lookup[name].get(key)
            if r is None:
                reasons.append(name + ":sample_missing")
                family_audit[name] = dict(status="missing")
                continue
            valid = all(_finite_feature(v) for v in r.values)
            if not r.eligible or r.reasons:
                reasons.append(name + ":technical_ineligible")
            if r.review != "confirmed":
                reasons.append(name + ":label_" + r.review)
            if not valid:
                reasons.append(name + ":missing_or_nonfinite_features")
            family_audit[name] = dict(eligible=r.eligible, review=r.review, reasons=r.reasons,
                missing_mask=tuple(not _finite_feature(v) for v in r.values), support=r.support)
        if not reasons:
            accepted.append(key)
        audit.append(dict(sample_key=key, subject=subject, label=label, session=session,
                          eligible=not reasons, reasons=tuple(reasons), families=family_audit))
    return dict(class_order=h6.LAB6, feature_order={n: FEATURES[n] for n in names},
                participant_roster=subjects, sample_keys=tuple(accepted), audit=tuple(audit),
                X={n: np.asarray([lookup[n][k].values for k in accepted], dtype=float).reshape(-1, len(FEATURES[n]))
                   for n in names},
                y=np.asarray([h6.LAB6.index(universe[k][1]) for k in accepted], dtype=int),
                participants=np.asarray([universe[k][0] for k in accepted]),
                sessions=np.asarray([universe[k][2] for k in accepted]))


def metrics6(y, prediction):
    """EXP-006: fixed-six diagnostic vs official metric; absent recall is None/N/A."""
    y, prediction = np.asarray(y), np.asarray(prediction)
    if (y.shape != prediction.shape or y.ndim != 1
            or any(a.dtype.kind not in "iu" or np.any((a < 0) | (a > 5)) for a in (y, prediction))):
        raise ValueError("sample-aligned six-class integer labels required")
    ref = _reference()
    if len(y):
        cm = ref.confusion_matrix(y, prediction, labels=range(6))
        pr, recall, f1, support = ref.precision_recall_fscore_support(y, prediction, labels=range(6), zero_division=0)
    else:
        cm = np.zeros((6, 6), dtype=int)
        pr, recall, f1, support = (np.zeros(6) for _ in range(4))
    complete = bool(np.all(support > 0))
    original = ref.metrics(y, prediction) if complete else None
    return dict(status="COMPLETE" if complete else "INCOMPLETE", sample_count=len(y),
        accuracy=original["accuracy"] if complete else float(np.trace(cm)/len(y)) if len(y) else None,
        macro_f1=original["macro_f1"] if complete else None,
        diagnostic_macro_f1_zero_division_0=float(np.mean(f1)), confusion_matrix=cm.tolist(),
        per_class=[dict(posture=f"P{k}", label=h6.LAB6[k], support=int(support[k]),
            predicted_support=int(cm[:, k].sum()), precision=float(pr[k]),
            recall=float(recall[k]) if support[k] else None,
            f1=float(f1[k]) if support[k] else None, diagnostic_f1_zero_division_0=float(f1[k])) for k in range(6)],
        p0_p1_p5_errors={f"P{i}_to_P{j}": dict(count=int(cm[i,j]), support=int(support[i]),
            rate=float(cm[i,j]/support[i]) if support[i] else None)
            for i in (0,1,5) for j in range(6) if j != i})


def _summary(y, predictions, seeds):
    rows = [dict(seed=seed, **metrics6(y, p)) for seed, p in zip(seeds, predictions)]
    complete = bool(rows) and all(r["status"] == "COMPLETE" for r in rows)
    return dict(status="COMPLETE" if complete else "INCOMPLETE", per_seed=rows,
                mean_macro_f1=float(np.mean([r["macro_f1"] for r in rows])) if complete else None,
                mean_accuracy=float(np.mean([r["accuracy"] for r in rows])) if len(y) and rows else None,
                mean_recall=tuple(float(np.mean([r["per_class"][k]["recall"] for r in rows]))
                    if rows and all(r["per_class"][k]["recall"] is not None for r in rows) else None for k in range(6)))


def rank_candidates(scores):
    """Return a development recommendation only; never creates a final artifact."""
    ids = tuple(c[0] for c in CANDIDATES)
    if set(scores) != set(ids):
        return dict(status="BLOCKED", reasons=("all_five_approved_candidates_required",), ranking=(), recommendation=None)
    for name in ids:
        s = scores[name]
        recall = s.get("mean_recall", ())
        if not isinstance(recall, (list, tuple)) or len(recall) != 6:
            return dict(status="BLOCKED", reasons=("six_class_recall_required:" + name,), ranking=(), recommendation=None)
        values = (s.get("mean_macro_f1"), s.get("mean_accuracy"), *(recall[k] for k in (0,1,5)))
        if s.get("status") != "COMPLETE" or any(v is None or not math.isfinite(v) for v in values):
            return dict(status="BLOCKED", reasons=("incomplete_candidate_scores:" + name,), ranking=(), recommendation=None)
    def compare(a, b):
        for va, vb in zip((scores[a]["mean_macro_f1"], *(scores[a]["mean_recall"][k] for k in (0,1,5)), scores[a]["mean_accuracy"]),
                          (scores[b]["mean_macro_f1"], *(scores[b]["mean_recall"][k] for k in (0,1,5)), scores[b]["mean_accuracy"])):
            if abs(va-vb) > TIE_TOLERANCE:
                return -1 if va > vb else 1
        pa, pb = len(FEATURES[CANDIDATES[ids.index(a)][1]]), len(FEATURES[CANDIDATES[ids.index(b)][1]])
        return (pa > pb) - (pa < pb) if pa != pb else ids.index(a) - ids.index(b)
    ranking = tuple(sorted(ids, key=cmp_to_key(compare)))
    return dict(status="DEVELOPMENT_RECOMMENDATION_ONLY", ranking=ranking, recommendation=ranking[0], reasons=())


def _prediction_report(aligned, values, seeds, feature_set, model):
    y, people = aligned["y"], aligned["participants"]
    return dict(feature_set=feature_set, model=model,
        predictions=tuple(p.tolist() for p in values), pooled=_summary(y, values, seeds),
        participants={s: _summary(y[people == s], [p[people == s] for p in values], seeds)
                      for s in aligned["development_subjects"]},
        sessions={s: _summary(y[aligned["sessions"] == s], [p[aligned["sessions"] == s] for p in values], seeds)
                  for s in ("S1", "S2")})


def _evaluate_candidates(families, development_subjects, reference_keys, *, rank=True):
    """Five approved candidates, two-person LOSO; cannot accept held-out rows."""
    # Even unused baseline families must not smuggle held-out observations here.
    families = {name: tuple(rows) for name, rows in families.items()}
    subjects = _roster(development_subjects)
    for rows in families.values():
        _check_development_only(rows, subjects)
    aligned = align_development(families, subjects, reference_keys, feature_sets=("H9", "H9-F9"))
    y, people = aligned["y"], aligned["participants"]
    support = {s: np.bincount(y[people == s], minlength=6).tolist() for s in subjects}
    blocked = tuple("required_classes_missing:" + s for s in subjects if any(n == 0 for n in support[s]))
    result = dict(aligned=aligned, support_by_participant=support,
        baseline_model_status={feature: "REGISTERED_COMPARISON_ONLY" for _, feature, _ in BASELINES},
        settings=dict(rf_seeds=SEEDS, rf_trees=TREE_COUNT, max_features=2, m2_lambda=0.5,
                      lr_runs=1, lr_seed=0, structural_test_settings=TREE_COUNT != 500),
        status="BLOCKED" if blocked else "DEVELOPMENT_COMPLETE", reasons=blocked,
        candidates={}, folds=[], selection=dict(status="BLOCKED", recommendation=None, ranking=(), reasons=blocked))
    if blocked:
        return result  # No fit and no discarded incomplete fold.
    ref = _reference()
    predictions = {c[0]: [] for c in CANDIDATES}
    try:
        for seed in SEEDS:
            current = {name: np.empty(len(y), dtype=int) for name in predictions if not name.startswith("LR_")}
            for heldout in subjects:
                test = people == heldout
                train = ~test
                X9, X8 = aligned["X"]["H9"], aligned["X"]["H9-F9"]
                models, weights = rf.fit_models(X9[train], y[train], 6, TREE_COUNT, seed, [0.5])
                for key, model in (("RF_M0_H9", "M0"), ("RF_M1_H9", "M1"), ("RF_M2_H9", "M2(λ=0.5)")):
                    current[key][test] = models[model](X9[test])
                forest = rf.Forest(6, TREE_COUNT, 2, None, seed).fit(X8[train], y[train])
                current["RF_M0_H9-F9"][test] = forest.predict(X8[test])
                result["folds"].append(dict(model="RF", seed=seed, heldout=heldout,
                    train_keys=tuple(k for k, keep in zip(aligned["sample_keys"], train) if keep),
                    test_keys=tuple(k for k, keep in zip(aligned["sample_keys"], test) if keep),
                    weights=weights.tolist(), preprocessing="raw; train-fold MDI/weights only"))
            for name, p in current.items():
                predictions[name].append(p)
        lr_prediction = np.empty(len(y), dtype=int)
        for heldout in subjects:
            test, train = people == heldout, people != heldout
            X = aligned["X"]["H9-F9"]
            scaler = ref.StandardScaler().fit(X[train])
            model = ref.make_model("Logistic-Regression", 0)
            with warnings.catch_warnings():
                warnings.simplefilter("error", ConvergenceWarning)
                model.fit(scaler.transform(X[train]), y[train])
            lr_prediction[test] = model.predict(scaler.transform(X[test]))
            result["folds"].append(dict(model="LR_B0", seed=0, heldout=heldout,
                scaler_n_samples_seen=int(scaler.n_samples_seen_), scaler_mean=scaler.mean_.tolist(),
                scaler_scale=scaler.scale_.tolist(), train_participants=tuple(s for s in subjects if s != heldout)))
        predictions["LR_B0_H9-F9"] = [lr_prediction]
    except (ValueError, RuntimeError, ConvergenceWarning) as error:
        result.update(status="BLOCKED", reasons=("model_fit_failed:" + str(error),))
        result["selection"]["reasons"] = result["reasons"]
        return result
    for name, feature_set, model in CANDIDATES:
        seeds = (0,) if model == "LR_B0" else SEEDS
        values = predictions[name]
        result["candidates"][name] = _prediction_report(aligned, values, seeds, feature_set, model)
    result["selection"] = (rank_candidates({name: c["pooled"] for name, c in result["candidates"].items()})
                           if rank else dict(status="COMPARISON_ONLY", recommendation=None, ranking=(), reasons=()))
    return result


def _baseline_comparison(families, development_subjects, reference_keys, primary=None):
    """Eight comparisons on ONE five-family segment intersection; no selection."""
    subjects = _roster(development_subjects)
    result = dict(status="NOT_PROVIDED", evaluation_status="NOT_EVALUATED", reasons=(),
                  models={}, folds=[], selection=None,
                  baseline_ids=tuple(b[0] for b in BASELINES), candidate_scope_reused=False,
                  settings=dict(rf_seeds=SEEDS, rf_trees=TREE_COUNT, max_features=2,
                                baseline_preprocessing="raw", structural_test_settings=TREE_COUNT != 500))
    missing = tuple(name for name in FEATURES if name not in families)
    if missing:
        result["reasons"] = tuple("feature_family_not_provided:" + n for n in missing)
        return result
    aligned = align_development(families, subjects, reference_keys, feature_sets=tuple(FEATURES))
    y, people = aligned["y"], aligned["participants"]
    support = {s: np.bincount(y[people == s], minlength=6).tolist() for s in subjects}
    blocked = tuple("required_classes_missing:" + s for s in subjects if any(n == 0 for n in support[s]))
    result.update(aligned=aligned, support_by_participant=support, sample_keys=aligned["sample_keys"],
                  status="BLOCKED" if blocked else "COMPARISON_COMPLETE", reasons=blocked,
                  evaluation_status="INCOMPLETE" if blocked else "COMPLETE")
    if blocked:
        return result
    # Primary ranking always keeps its original H9/H9-F9 scope. If that scope
    # differs, evaluate comparison copies of the five models on the common
    # five-family scope; never mix scores from different segment populations.
    if primary is not None and primary["status"] == "BLOCKED":
        result.update(status="BLOCKED", reasons=primary["reasons"])
        return result
    if primary is not None and primary["aligned"]["sample_keys"] == aligned["sample_keys"]:
        compared_candidates = primary
        result["candidate_scope_reused"] = True
    else:
        accepted = set(aligned["sample_keys"])
        filtered = {name: tuple(r for r in rows if r.sample_key in accepted) for name, rows in families.items()}
        compared_candidates = _evaluate_candidates(filtered, subjects, reference_keys, rank=False)
    if compared_candidates["status"] == "BLOCKED":
        result.update(status="BLOCKED", reasons=compared_candidates["reasons"])
        return result
    result["models"].update(compared_candidates["candidates"])
    result["folds"].extend(compared_candidates["folds"])
    predictions = {name: [] for name, _, _ in BASELINES}
    try:
        for seed in SEEDS:
            current = {name: np.empty(len(y), dtype=int) for name in predictions}
            for heldout in subjects:
                test, train = people == heldout, people != heldout
                for name, feature, _ in BASELINES:
                    X = aligned["X"][feature]
                    forest = rf.Forest(6, TREE_COUNT, 2, None, seed).fit(X[train], y[train])
                    current[name][test] = forest.predict(X[test])
                    result["folds"].append(dict(model=name, feature_set=feature, seed=seed, heldout=heldout,
                        train_keys=tuple(k for k, keep in zip(aligned["sample_keys"], train) if keep),
                        test_keys=tuple(k for k, keep in zip(aligned["sample_keys"], test) if keep),
                        preprocessing="raw; unchanged RF M0", feature_count=X.shape[1]))
            for name, p in current.items():
                predictions[name].append(p)
    except (ValueError, RuntimeError) as error:
        result.update(status="BLOCKED", reasons=("baseline_fit_failed:" + str(error),), models={})
        return result
    for name, feature, model in BASELINES:
        result["models"][name] = _prediction_report(aligned, predictions[name], SEEDS, feature, model)
    return result


def evaluate_baseline_comparison(families, development_subjects, reference_keys):
    """Registered baselines + existing candidates, exact common rows, no ranking."""
    subjects = _roster(development_subjects)
    families = {name: tuple(rows) for name, rows in families.items()}
    for rows in families.values():
        _check_development_only(rows, subjects)
    return _baseline_comparison(families, subjects, reference_keys)


def evaluate_development(families, development_subjects, reference_keys):
    """Unchanged five-candidate selection plus a separate baseline comparison."""
    families = {name: tuple(rows) for name, rows in families.items()}
    primary = _evaluate_candidates(families, development_subjects, reference_keys)
    comparison = _baseline_comparison(families, development_subjects, reference_keys, primary)
    primary["baseline_comparison"] = comparison
    primary["baseline_model_status"] = {feature: comparison["status"] for _, feature, _ in BASELINES}
    return primary


def code_hashes():
    """Expected code pin set for the access boundary; reads source only."""
    from rf_experiment import file_identity
    paths = (Path(__file__), Path(rf.__file__), Path(h6.__file__), REFERENCE_LR,
             Path(f0.__file__), Path(__file__).with_name("f0_fcal_evaluation.py"),
             Path(__file__).with_name("f0_fcal_input.py"), Path(__file__).with_name("f0_fcal_native.py"),
             *(Path(__file__).with_name(name) for name in ("f1_sample_aggregator.py", "f1_csv_adapter.py",
               "analyze_d455.py", "capture_d455.py", "live_f1_d455.py", "research_d455.py",
               "research_recording.py", "posture_geometry.py")))
    return {str(p.resolve()): file_identity(p)["sha256"] for p in paths}


def frozen_settings(candidate):
    """Exact declaration required by the held-out access gate; no fitting."""
    options = {c[0]: c for c in CANDIDATES}
    if candidate not in options:
        raise ValueError("unapproved frozen candidate")
    _, feature, model = options[candidate]
    return dict(feature_order=list(FEATURES[feature]), seeds=list((0,) if model == "LR_B0" else SEEDS),
                preprocessing="train-only StandardScaler" if model == "LR_B0" else "raw",
                n_classes=6, n_trees=None if model == "LR_B0" else 500,
                max_features=None if model == "LR_B0" else 2,
                m2_lambda=0.5 if model == "M2" else None,
                rank_weight_policy=rf.RANK_WEIGHT_POLICY if model in ("M1", "M2") else None,
                lr_parameters=_reference().make_model("Logistic-Regression", 0).get_params(deep=False)
                              if model == "LR_B0" else None)


def load_frozen_heldout(freeze_path, *, freeze_sha256, loader):
    """Lazy access only after explicit final artifact/settings/code hash checks.

    Does not create a freeze, deserialize classifiers, refit or evaluate heldout.
    Callable receives exactly the four frozen subject IDs after all checks pass.
    """
    from rf_experiment import read_pinned_json, verify_file
    manifest, pin = read_pinned_json(freeze_path)
    if pin["sha256"] != freeze_sha256 or manifest.get("status") != "FROZEN":
        raise ValueError("final freeze hash/status not verified; heldout access blocked")
    candidates = {c[0]: c for c in CANDIDATES}
    if manifest.get("candidate") not in candidates or manifest.get("class_order") != list(h6.LAB6):
        raise ValueError("unapproved frozen candidate/classes")
    expected = frozen_settings(manifest["candidate"])
    if manifest.get("settings") != expected or manifest.get("code_hashes") != code_hashes():
        raise ValueError("final settings/code freeze mismatch")
    dev = _roster(manifest.get("development_subjects", ()))
    heldout = manifest.get("heldout_subjects", ())
    if (not isinstance(heldout, (list, tuple)) or len(heldout) != 4 or len(set(heldout)) != 4 or set(dev) & set(heldout)
            or any(not isinstance(s, str) or not s for s in heldout)):
        raise ValueError("independent four-person frozen roster required")
    models = manifest.get("model_artifacts", [])
    if [m.get("seed") for m in models] != expected["seeds"]:
        raise ValueError("final model artifacts for every frozen seed required")
    root = Path(freeze_path).resolve().parent
    for m in models:
        path = Path(m["path"])
        verify_file(path if path.is_absolute() else root / path, m["sha256"])
    verify_file(freeze_path, freeze_sha256)
    return loader(tuple(heldout))
