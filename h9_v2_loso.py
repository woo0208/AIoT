"""Development LOSO evaluator for unchanged M0/M1/M2 and M3-G on H9-v2.

Input is the existing labelled engineering probe CSV, NOT a new formal data
schema. Primary five-class evaluation excludes P5 from fitting and metrics.
Auxiliary six-class evaluation requires a caller-supplied approval reference;
that reference is recorded, not independently authenticated or an IRB approval.
No capture, tuning, model export, selection-policy or canonical schema change.

Example (only after the relevant data/experiment approvals):
  python h9_v2_loso.py --probe-csv new_subject_a.csv new_subject_b.csv
  python h9_v2_loso.py --probe-csv new_subject_a.csv new_subject_b.csv \
      --scope auxiliary6 --six-class-approval APPROVAL_REFERENCE --output new.json
Output files are created exclusively; existing files are never overwritten.
"""

import argparse
import csv
import json
import os
from pathlib import Path
import platform

import numpy as np

import f1_sample_aggregator as aggregation
import h6_offline as h6
import h9_v2 as v2
import m3_g as m3
import rf_experiment as rf


FEATURE_ORDER = tuple(v2.H9_V2_FEATURE_NAMES)
SEEDS = (0, 1, 2, 3, 4)
TREE_COUNT = 500
MAX_FEATURES = 2
M2_LAMBDA = 0.5
MODEL_NAMES = ("M0", "M1", "M2", "M3-G")


def _class_contract(scope, approval):
    if scope not in ("primary5", "auxiliary6"):
        raise ValueError("scope must be primary5 or auxiliary6")
    if scope == "auxiliary6":
        if not isinstance(approval, str) or not approval.strip():
            raise ValueError("auxiliary6 requires a non-empty six-class approval reference")
        return tuple(h6.LAB6)
    if approval is not None:
        raise ValueError("six-class approval belongs only to auxiliary6")
    return tuple(rf.LAB5)


def _check_feature_order():
    if (len(FEATURE_ORDER) != 9 or tuple(v2.H9_V2_FEATURE_NAMES) != FEATURE_ORDER
            or tuple(m3.FEATURE_NAMES) != FEATURE_ORDER):
        raise ValueError("H9-v2/M3-G feature order mismatch")


def _probe_sources(paths):
    """Pin exact input bytes and bind adapter row numbers to recording/segment."""
    sources, seen_paths, seen_recordings = [], set(), set()
    for path in paths:
        source = rf.file_identity(path)
        path_key = os.path.normcase(source["path"])
        if path_key in seen_paths:
            raise ValueError("duplicate input path")
        seen_paths.add(path_key)
        identity, segments, row_count = None, {}, 0
        with open(source["path"], encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"artifact_kind", *h6.PROBE_IDENTITY_FIELDS, *FEATURE_ORDER}
            if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                    or not required.issubset(reader.fieldnames)):
                raise ValueError("missing or duplicate labelled H9-v2 probe columns")
            for row_count, row in enumerate(reader, 1):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("malformed probe source row")
                fields = {name: row[name].strip() for name in h6.PROBE_IDENTITY_FIELDS}
                current = (fields["recording_id"], fields["subject"])
                if (not all(fields.values()) or row["artifact_kind"] != h6.EXPLORATORY_ARTIFACT_KIND
                        or (identity is not None and current != identity)):
                    raise ValueError("invalid or conflicting probe source identity")
                identity = current
                if fields["label"] in h6.NON_EVALUATION_LABELS:
                    continue
                label = h6.analysis_label(fields["label"])
                segment = segments.setdefault(fields["segment_id"],
                    dict(label=label, frame_indices=[], original_labels=set()))
                if segment["label"] != label:
                    raise ValueError("conflicting segment label")
                segment["frame_indices"].append(row_count)
                segment["original_labels"].add(fields["label"])
        if identity is None or identity[0] in seen_recordings:
            raise ValueError("empty source or duplicate recording_id")
        seen_recordings.add(identity[0])
        source.update(recording_id=identity[0], subject=identity[1], row_count=row_count,
                      segments=segments)
        sources.append(source)
    if not sources:
        raise ValueError("at least one probe CSV is required")
    return sources


def _verify_files(identities):
    for item in identities:
        rf.verify_file(item["path"], item["sha256"])


def _prepare_samples(samples, sources, classes):
    """Validate loader provenance before any fit; preserve excluded sample audit."""
    source_map = {source["recording_id"]: i for i, source in enumerate(sources)}
    audit, evaluated, seen, seen_frames = [], [], set(), set()
    for sample in samples:
        if not isinstance(sample, v2.H9V2SampleResult):
            raise ValueError("expected H9V2SampleResult, not legacy H9")
        if (sample.aggregation_spec != v2.H9_V2_AGGREGATION_SPEC_ID
                or tuple(sample.feature_names) != FEATURE_ORDER
                or set(sample.features) != set(FEATURE_ORDER)):
            raise ValueError("H9-v2 aggregation or feature order mismatch")
        key = sample.sample_key
        if key in seen:
            raise ValueError("duplicate sample key")
        seen.add(key)
        if len(key) != 3 or key[1] not in source_map:
            raise ValueError("unbound sample provenance")
        source_index = source_map[key[1]]
        source = sources[source_index]
        segment = source["segments"].get(key[2])
        if (key[0] != f"probe-csv:{key[1]}" or sample.subject != source["subject"]
                or sample.round is not None or segment is None
                or h6.analysis_label(sample.label) != segment["label"]
                or tuple(sample.input_frame_indices) != tuple(segment["frame_indices"])):
            raise ValueError("sample/source recording, participant, label or frame binding mismatch")
        frames = tuple(sample.input_frame_indices)
        valid = tuple(sample.common_valid_frame_indices)
        if (sample.n_frames != len(frames) or sample.common_valid_count != len(valid)
                or len(set(valid)) != len(valid) or not set(valid).issubset(frames)
                or not frames or not np.isclose(sample.common_coverage, len(valid) / len(frames),
                                                rtol=0, atol=1e-12)
                or set(sample.missing_counts) != set(FEATURE_ORDER)):
            raise ValueError("inconsistent H9-v2 support provenance")
        for frame in frames:
            frame_key = (key[1], frame)
            if frame_key in seen_frames:
                raise ValueError("frame reused by multiple samples")
            seen_frames.add(frame_key)
        label = segment["label"]
        in_scope = label in classes
        if not in_scope:
            status = "outside_primary_class_set"
        elif not sample.eligible:
            status = "ineligible"
        else:
            if (sample.eligibility_reasons or len(valid) < aggregation.H_MIN_VALID_FRAMES
                    or sample.common_coverage < aggregation.H_MIN_COVERAGE):
                raise ValueError("eligible sample has inconsistent support/reasons")
            values = sample.ordered_values()
            if len(values) != 9 or not np.isfinite(values).all():
                raise ValueError("non-finite H9-v2 model input")
            status = "evaluated"
            evaluated.append(sample)
        audit.append(dict(sample_key=key, subject=sample.subject, label=label,
                          original_labels=sorted(segment["original_labels"]),
                          source_index=source_index, eligible=sample.eligible,
                          eligibility_reasons=sample.eligibility_reasons, status=status,
                          input_frame_indices=frames, common_valid_frame_indices=valid,
                          frame_count=sample.n_frames, common_valid_count=len(valid),
                          common_coverage=sample.common_coverage,
                          missing_counts=dict(sample.missing_counts)))
    expected = {(f"probe-csv:{source['recording_id']}", source["recording_id"], step)
                for source in sources for step in source["segments"]}
    if seen != expected:
        raise ValueError("loader sample/source coverage mismatch")
    if not evaluated:
        raise ValueError("no eligible in-scope H9-v2 samples")
    return evaluated, audit


def _metrics(y, prediction, classes):
    """Preserve RF Macro-F1; recall/rates with no true support are null."""
    K = len(classes)
    cm = np.zeros((K, K), dtype=int)
    np.add.at(cm, (y, prediction), 1)
    class_metrics = []
    for k, label in enumerate(classes):
        support, predicted = int(cm[k].sum()), int(cm[:, k].sum())
        tp = int(cm[k, k])
        class_metrics.append(dict(posture_id=f"P{k}", label=label, support=support,
                                  predicted_support=predicted,
                                  precision=tp / predicted if predicted else 0.0,
                                  recall=tp / support if support else None))
    p1_support = int(cm[1].sum())
    errors = {}
    for destination in ((0, 5) if K == 6 else (0,)):
        count = int(cm[1, destination])
        errors[f"P1_to_P{destination}"] = dict(
            count=count, support=p1_support, rate=count / p1_support if p1_support else None)
    return dict(accuracy=float(np.mean(prediction == y)),
                macro_f1=rf.macro_f1(y, prediction, K),
                complete_class_support=all(row["support"] for row in class_metrics),
                classes=class_metrics, confusion_matrix=cm.tolist(), errors=errors)


def _summary(rows):
    return {key + suffix: float(fn([row[key] for row in rows]))
            for key in ("accuracy", "macro_f1")
            for suffix, fn in (("_mean", np.mean), ("_seed_sd", np.std))}


def _fold_binding(train, test, participants, source_indices, sources, held_out):
    _check_feature_order()
    train_subjects, test_subjects = set(participants[train]), set(participants[test])
    if (not len(train) or not len(test) or train_subjects & test_subjects
            or test_subjects != {held_out}
            or train_subjects != set(participants) - {held_out}
            or set(train) & set(test) or len(train) + len(test) != len(participants)):
        raise ValueError("participant LOSO train/test separation failed")
    for i in (*train, *test):
        if sources[source_indices[i]]["subject"] != participants[i]:
            raise ValueError("fold source/participant provenance mismatch")
    return dict(train_indices=train.tolist(), test_indices=test.tolist(),
                train_participants=sorted(train_subjects), test_participants=sorted(test_subjects),
                train_source_indices=sorted({source_indices[i] for i in train}),
                test_source_indices=sorted({source_indices[i] for i in test}),
                feature_order=FEATURE_ORDER, provenance_checked=True)


def evaluate_probe_csvs(paths, *, scope="primary5", six_class_approval=None):
    """Evaluate pinned engineering CSVs; no public hyperparameter overrides.

    Synthetic tests may patch TREE_COUNT to reduce computation. This output
    layout is a development diagnostic, not a frozen formal provenance schema.
    """
    classes = _class_contract(scope, six_class_approval)
    _check_feature_order()
    code = [rf.file_identity(path) for path in (
        __file__, h6.__file__, rf.__file__, v2.__file__, m3.__file__, aggregation.__file__)]
    sources = _probe_sources(paths)
    samples = h6.load_labeled_probe_h9_v2_samples([item["path"] for item in sources])
    selected, audit = _prepare_samples(samples, sources, classes)
    _verify_files([*sources, *code])
    X = np.array([sample.ordered_values() for sample in selected], dtype=float)
    y = np.array([classes.index(h6.analysis_label(sample.label)) for sample in selected])
    participants = np.array([sample.subject for sample in selected])
    source_map = {item["recording_id"]: i for i, item in enumerate(sources)}
    source_indices = [source_map[sample.sample_key[1]] for sample in selected]
    subjects = sorted(set(participants))
    if len(subjects) < 2:
        raise ValueError("participant LOSO requires at least two eligible participants")
    plans = []
    for held_out in subjects:
        test = np.flatnonzero(participants == held_out)
        train = np.flatnonzero(participants != held_out)
        binding = _fold_binding(train, test, participants, source_indices, sources, held_out)
        if set(y[train]) != set(range(len(classes))):
            raise ValueError(f"training fold lacks required classes: held_out={held_out}")
        plans.append((held_out, train, test, binding))

    folds = []
    predictions = {name: [] for name in MODEL_NAMES}
    for seed in SEEDS:
        current = {name: np.full(len(y), -1, dtype=int) for name in MODEL_NAMES}
        assigned = np.zeros(len(y), dtype=int)
        for held_out, train, test, _ in plans:
            binding = _fold_binding(train, test, participants, source_indices, sources, held_out)
            X_train, y_train, X_test = X[train], y[train], X[test]
            legacy, weights = rf.fit_models(X_train, y_train, len(classes), TREE_COUNT,
                                            seed, [M2_LAMBDA])
            candidate = m3.M3GForest(len(classes), n_trees=TREE_COUNT, seed=seed).fit(X_train, y_train)
            models = {"M0": legacy["M0"], "M1": legacy["M1"],
                      "M2": legacy[f"M2(λ={M2_LAMBDA:g})"], "M3-G": candidate.predict}
            forests = [legacy[name].forest for name in ("M0", "M1", f"M2(λ={M2_LAMBDA:g})")]
            if any((forest.T, forest.mf, forest.seed) != (TREE_COUNT, MAX_FEATURES, seed)
                   for forest in [*forests, candidate]):
                raise ValueError("model budget/seed mismatch")
            if (not np.all(weights > 0)
                    or not np.array_equal(weights, rf.rank_weights(forests[0].mdi))):
                raise ValueError("M2 training-fold rank weights mismatch")
            for name, predict in models.items():
                result = np.asarray(predict(X_test))
                if (result.shape != (len(test),) or result.dtype.kind not in "iu"
                        or np.any(result < 0) or np.any(result >= len(classes))):
                    raise ValueError("invalid model prediction")
                current[name][test] = result
            assigned[test] += 1
            folds.append(dict(seed=seed, held_out_participant=held_out, **binding,
                              training_m0_mdi=forests[0].mdi.tolist(),
                              rank_weights=weights.tolist(),
                              m0_m1_predictions_equal=bool(np.array_equal(
                                  current["M0"][test], current["M1"][test]))))
        if not np.all(assigned == 1):
            raise ValueError("each sample must have exactly one OOF prediction per seed")
        for name in MODEL_NAMES:
            predictions[name].append(current[name])

    metrics = {}
    for name in MODEL_NAMES:
        pooled, by_subject = [], {}
        for seed, prediction in zip(SEEDS, predictions[name]):
            pooled.append(dict(seed=seed, **_metrics(y, prediction, classes)))
        for subject in subjects:
            mask = participants == subject
            rows = [dict(seed=seed, **_metrics(y[mask], prediction[mask], classes))
                    for seed, prediction in zip(SEEDS, predictions[name])]
            by_subject[subject] = dict(**_summary(rows), per_seed=rows)
        complete = all(row["complete_class_support"] for item in by_subject.values()
                       for row in item["per_seed"])
        participant_f1 = float(np.mean([item["macro_f1_mean"] for item in by_subject.values()]))
        metrics[name] = dict(**_summary(pooled), per_seed=pooled, participants=by_subject,
                             participant_macro_f1_mean=participant_f1,
                             complete_participant_class_support=complete,
                             complete_class_participant_macro_f1=participant_f1 if complete else None)
    _verify_files([*sources, *code])
    return dict(kind="h9-v2-engineering-loso-development-output", scope=scope,
                six_class_approval_reference=six_class_approval,
                approval_reference_authenticated=False, formal_schema_status="UNRESOLVED",
                unresolved_formal_connections=[
                    "IRB/experiment authorization and participant identity mapping",
                    "formal inclusion/selection manifest and dataset-role binding",
                    "engineering H9-v2 adapter to canonical raw/analysis/model-lock lineage",
                    "formal protocol, feature/evaluation freeze and external-data separation"],
                inputs=[{k: value for k, value in item.items() if k != "segments"} for item in sources],
                code=code, environment=dict(python=platform.python_version(), numpy=np.__version__),
                feature_set=v2.H9_V2_FEATURE_SET, feature_order=FEATURE_ORDER,
                aggregation_spec=v2.H9_V2_AGGREGATION_SPEC_ID, class_order=classes,
                posture_ids=[f"P{k}" for k in range(len(classes))],
                trees=TREE_COUNT, max_features=MAX_FEATURES, seeds=SEEDS, m2_lambda=M2_LAMBDA,
                m3_variant="M3-G", sample_count=len(selected), samples=audit,
                evaluated_sample_keys=[sample.sample_key for sample in selected],
                feature_matrix=X.tolist(), true_labels=y.tolist(), participants=participants.tolist(),
                folds=folds, metrics=metrics,
                predictions={name: [values.tolist() for values in predictions[name]] for name in MODEL_NAMES},
                metric_notes=dict(confusion_axes="rows=actual, columns=predicted; integer counts per seed",
                                  macro_f1="unchanged rf.macro_f1; absent true classes are skipped",
                                  zero_predicted_support_precision=0.0,
                                  zero_true_support_recall_and_error_rate=None,
                                  seed_sd="population SD (ddof=0); seeds are not independent participants",
                                  adapter_analysis_run_id="probe-csv:<recording_id> is not a canonical analysis run"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-csv", nargs="+", required=True)
    parser.add_argument("--scope", choices=("primary5", "auxiliary6"), default="primary5")
    parser.add_argument("--six-class-approval")
    parser.add_argument("--output", help="new JSON file only; default is stdout")
    args = parser.parse_args(argv)
    _class_contract(args.scope, args.six_class_approval)
    if args.output and Path(args.output).exists():
        raise FileExistsError(f"refusing to overwrite output: {args.output}")
    result = evaluate_probe_csvs(args.probe_csv, scope=args.scope,
                                six_class_approval=args.six_class_approval)
    serialized = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
    if args.output:
        with open(args.output, "x", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
