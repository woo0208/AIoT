"""Separate six-posture H5/H9 LOSO path; consumes existing H feature outputs.

Input CSVs contain HFrameRecord identity columns and H9_FEATURE_NAMES. Empty
feature cells mean missing observations. No geometry formula is recomputed.
Run: python h6_offline.py --frames h_frames.csv [more.csv] > h6_results.json

The ``--probe-csv`` adapter reads continuously labelled
``posture_geometry_probe.py --csv`` files and groups posture segments while
excluding PREP/TRANSITION frames.  The legacy ``--probe-metadata`` adapter
reads probe files whose identity is kept separately. Its metadata CSV has one
row per probe file with columns
``csv_path,subject,recording_id,round,step,label``; relative paths are resolved
from the metadata file.  The adapter adds only frame/sample identity in memory.
"""

import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np

import rf_experiment as rf
from f1_sample_aggregator import (
    H5_FEATURE_NAMES, H9_FEATURE_NAMES, HFrameRecord, HSampleResult,
    aggregate_h5_h9_sample,
)
from posture_geometry_probe import EXPLORATORY_ARTIFACT_KIND


LAB6 = tuple(rf.LAB5) + ("lean_forward",)
POSTURE_IDS = tuple(f"P{i}" for i in range(6))
PROBE_METADATA_FIELDS = ("csv_path", "subject", "recording_id", "round", "step", "label")
PROBE_IDENTITY_FIELDS = ("subject", "recording_id", "segment_id", "label")
NON_EVALUATION_LABELS = frozenset(("PREP", "TRANSITION"))


def analysis_label(label):
    label = "lean_forward" if label == "body_forward" else label
    if label not in LAB6:
        raise ValueError(f"not a six-posture label: {label!r}")
    return label


def load_h_samples(paths):
    """Read existing per-frame H outputs and reuse unchanged common aggregation."""
    groups, seen, identities = {}, set(), {}
    identity_fields = ("analysis_run_id", "recording_id", "subject", "round", "step", "label")
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = set(identity_fields + ("frame_index",) + H9_FEATURE_NAMES)
            if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                    or not required.issubset(reader.fieldnames)):
                raise ValueError(f"missing or duplicate H frame columns: {path}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"malformed H frame row: {path}:{reader.line_num}")
                record = HFrameRecord(
                    **{name: row[name] for name in identity_fields if name != "round"},
                    round=row["round"] or None,
                    frame_index=int(row["frame_index"]),
                    features={name: float(row[name]) if row[name] else None
                              for name in H9_FEATURE_NAMES},
                )
                analysis_label(record.label)
                if record.frame_key in seen:
                    raise ValueError(f"duplicate H frame key: {record.frame_key}")
                seen.add(record.frame_key)
                run = (record.analysis_run_id, record.recording_id)
                identity = (record.subject, record.round)
                if identities.setdefault(run, identity) != identity:
                    raise ValueError(f"conflicting recording identity: {run}")
                groups.setdefault((*run, record.step), []).append(record)
    return tuple(aggregate_h5_h9_sample(groups[key]) for key in sorted(groups))


def _read_probe_csv(path, metadata):
    """Convert one existing probe CSV to HFrameRecords without rewriting it."""
    records = []
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"artifact_kind", *H9_FEATURE_NAMES}
        if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                or not required.issubset(reader.fieldnames)):
            raise ValueError(f"missing or duplicate probe CSV columns: {path}")
        for frame_index, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed probe CSV row: {path}:{reader.line_num}")
            if row["artifact_kind"] != EXPLORATORY_ARTIFACT_KIND:
                raise ValueError(f"unexpected probe artifact kind: {path}:{reader.line_num}")
            records.append(HFrameRecord(
                analysis_run_id=f"probe-csv:{metadata['recording_id']}",
                recording_id=metadata["recording_id"],
                frame_index=frame_index,
                subject=metadata["subject"],
                round=metadata["round"] or None,
                step=metadata["step"],
                label=metadata["label"],
                features={
                    name: float(row[name]) if row[name].strip() else None
                    for name in H9_FEATURE_NAMES
                },
            ))
    if not records:
        raise ValueError(f"empty probe CSV: {path}")
    return records


def load_probe_h_samples(metadata_paths):
    """Join per-capture probe CSVs with separate six-field sample metadata."""
    samples, seen_recordings, seen_paths = [], set(), set()
    for metadata_path in metadata_paths:
        metadata_path = Path(metadata_path).resolve()
        with metadata_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                    or not set(PROBE_METADATA_FIELDS).issubset(reader.fieldnames)):
                raise ValueError(f"missing or duplicate probe metadata columns: {metadata_path}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"malformed probe metadata row: {metadata_path}:{reader.line_num}")
                metadata = {name: row[name].strip() for name in PROBE_METADATA_FIELDS}
                for name in ("csv_path", "subject", "recording_id", "step", "label"):
                    if not metadata[name]:
                        raise ValueError(
                            f"empty probe metadata {name}: {metadata_path}:{reader.line_num}"
                        )
                analysis_label(metadata["label"])
                if metadata["recording_id"] in seen_recordings:
                    raise ValueError(f"duplicate probe recording_id: {metadata['recording_id']}")
                source_path = Path(metadata["csv_path"])
                if not source_path.is_absolute():
                    source_path = metadata_path.parent / source_path
                source_path = source_path.resolve()
                source_key = os.path.normcase(str(source_path))
                if source_key in seen_paths:
                    raise ValueError(f"duplicate probe csv_path: {source_path}")
                seen_recordings.add(metadata["recording_id"])
                seen_paths.add(source_key)
                samples.append(aggregate_h5_h9_sample(
                    _read_probe_csv(source_path, metadata)
                ))
    if not samples:
        raise ValueError("probe metadata contains no capture rows")
    return tuple(samples)


def load_labeled_probe_h_samples(paths):
    """Read continuous probe CSVs and aggregate only labelled posture segments."""

    return _load_labeled_probe_samples(
        paths, feature_names=H9_FEATURE_NAMES, record_type=HFrameRecord,
        aggregate=aggregate_h5_h9_sample,
    )


def load_labeled_probe_h9_v2_samples(paths):
    """Load F1..F8+C3 without fitting/evaluating or rewriting input files.

    Returns H9V2SampleResults including ineligible segments. Sample keys and
    input frame indices match load_labeled_probe_h_samples on the same files;
    common_valid_frame_indices/count/coverage and missing_counts describe each
    candidate's own support. Compare eligible sample-key intersections, keeping
    those support diagnostics distinct. No legacy F9 column is required.
    """

    from h9_v2 import H9_V2_FEATURE_NAMES, H9V2FrameRecord, aggregate_h9_v2_sample

    return _load_labeled_probe_samples(
        paths, feature_names=H9_V2_FEATURE_NAMES, record_type=H9V2FrameRecord,
        aggregate=aggregate_h9_v2_sample,
    )


def _load_labeled_probe_samples(paths, *, feature_names, record_type, aggregate):
    """Shared labelled CSV parsing, segment identity and frame numbering."""

    groups, seen_recordings = {}, set()
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"artifact_kind", *PROBE_IDENTITY_FIELDS, *feature_names}
            if (reader.fieldnames is None
                    or len(set(reader.fieldnames)) != len(reader.fieldnames)
                    or not required.issubset(reader.fieldnames)):
                raise ValueError(f"missing or duplicate labelled probe columns: {path}")
            file_identity = None
            for frame_index, row in enumerate(reader, 1):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"malformed probe CSV row: {path}:{reader.line_num}")
                if row["artifact_kind"] != EXPLORATORY_ARTIFACT_KIND:
                    raise ValueError(
                        f"unexpected probe artifact kind: {path}:{reader.line_num}"
                    )
                identity = {name: row[name].strip() for name in PROBE_IDENTITY_FIELDS}
                if any(not identity[name] for name in PROBE_IDENTITY_FIELDS):
                    raise ValueError(f"empty labelled probe identity: {path}:{reader.line_num}")
                row_identity = (identity["recording_id"], identity["subject"])
                if file_identity is None:
                    file_identity = row_identity
                    if row_identity[0] in seen_recordings:
                        raise ValueError(f"duplicate probe recording_id: {row_identity[0]}")
                    seen_recordings.add(row_identity[0])
                elif row_identity != file_identity:
                    raise ValueError(f"multiple recording identities in probe CSV: {path}")
                if identity["label"] in NON_EVALUATION_LABELS:
                    continue
                label = analysis_label(identity["label"])
                segment_id = identity["segment_id"]
                key = (identity["recording_id"], segment_id)
                record = record_type(
                    analysis_run_id=f"probe-csv:{identity['recording_id']}",
                    recording_id=identity["recording_id"],
                    frame_index=frame_index,
                    subject=identity["subject"],
                    round=None,
                    step=segment_id,
                    label=label,
                    features={
                        name: float(row[name]) if row[name].strip() else None
                        for name in feature_names
                    },
                )
                previous = groups.setdefault(key, [])
                if previous and (previous[0].subject != record.subject
                                 or previous[0].label != record.label):
                    raise ValueError(f"conflicting labelled probe segment: {key}")
                previous.append(record)
    if not groups:
        raise ValueError("labelled probe CSVs contain no six-posture frames")
    return tuple(aggregate(groups[key]) for key in sorted(groups))


def aggregation_audit(samples):
    """Report H9 common-support missingness and exclusion counts."""
    samples = tuple(samples)
    return dict(
        input_sample_count=len(samples),
        eligible_sample_count=sum(sample.eligible for sample in samples),
        excluded_sample_count=sum(not sample.eligible for sample in samples),
        samples_with_missing_feature_cells=sum(
            any(sample.missing_counts.values()) for sample in samples
        ),
        input_frame_count=sum(sample.n_frames for sample in samples),
        common_valid_frame_count=sum(sample.common_valid_count for sample in samples),
        excluded_frame_count=sum(
            sample.n_frames - sample.common_valid_count for sample in samples
        ),
        feature_missing_cell_counts={
            name: sum(sample.missing_counts[name] for sample in samples)
            for name in H9_FEATURE_NAMES
        },
        excluded_sample_reasons={
            reason: sum(reason in sample.eligibility_reasons for sample in samples)
            for reason in sorted({
                reason for sample in samples for reason in sample.eligibility_reasons
            })
        },
    )


def evaluate_samples(samples):
    """Evaluate only joint H9-eligible samples; retain every original label."""
    samples = tuple(
        sample for sample in samples if sample.label not in NON_EVALUATION_LABELS
    )
    audit, eligible, seen = [], [], set()
    for sample in samples:
        if not isinstance(sample, HSampleResult):
            raise ValueError("expected HSampleResult")
        if sample.sample_key in seen:
            raise ValueError(f"duplicate H sample key: {sample.sample_key}")
        seen.add(sample.sample_key)
        label = analysis_label(sample.label)
        audit.append(dict(sample_key=sample.sample_key, subject=sample.subject,
                          original_label=sample.label, analysis_label=label,
                          posture_id=POSTURE_IDS[LAB6.index(label)], eligible=sample.eligible,
                          eligibility_reasons=sample.eligibility_reasons,
                          frame_count=sample.n_frames,
                          common_valid_frame_count=sample.common_valid_count,
                          excluded_frame_count=sample.n_frames - sample.common_valid_count,
                          missing_counts=dict(sample.missing_counts)))
        if sample.eligible:
            eligible.append(sample)
    y = np.array([LAB6.index(analysis_label(s.label)) for s in eligible], dtype=int)
    X = np.array([s.ordered_values("H9") for s in eligible], dtype=float)
    participants = np.array([s.subject for s in eligible])
    if not len(y) or X.shape != (len(y), 9) or not np.isfinite(X).all():
        raise ValueError("six-posture LOSO requires finite jointly eligible H samples")
    if set(y) != set(range(6)):
        raise ValueError("jointly eligible samples must contain all six postures")
    if any(not isinstance(s.subject, str) or not s.subject for s in eligible):
        raise ValueError("participant identifiers must be non-empty strings")
    subjects = sorted(set(participants))
    if len(subjects) < 2:
        raise ValueError("LOSO requires at least two participants")
    for subject in subjects:
        if set(y[participants != subject]) != set(range(6)):
            raise ValueError(f"training fold without all six postures: held_out={subject}")

    matrices = {"H5": X[:, :len(H5_FEATURE_NAMES)], "H9": X}
    names = ("M0", "M1", f"M2(λ={rf.H_EVAL_M2_LAMBDA:g})")
    predictions = {fs: {m: [] for m in names} for fs in matrices}
    folds = []
    for seed in rf.H_EVAL_SEEDS:
        current = {fs: {m: np.empty(len(y), dtype=int) for m in names} for fs in matrices}
        for subject in subjects:
            test = participants == subject
            train = ~test
            fold = dict(seed=seed, held_out_participant=subject,
                        train_indices=np.flatnonzero(train).tolist(),
                        test_indices=np.flatnonzero(test).tolist(), weights={})
            for fs, values in matrices.items():
                models, weights = rf.fit_models(values[train], y[train], 6,
                                               rf.H_EVAL_TREES, seed, [rf.H_EVAL_M2_LAMBDA])
                fold["weights"][fs] = weights.tolist()
                for model in names:
                    current[fs][model][test] = models[model](values[test])
            folds.append(fold)
        for fs in matrices:
            for model in names:
                predictions[fs][model].append(current[fs][model])

    metrics = []
    for fs in matrices:
        for model in names:
            values = predictions[fs][model]
            acc = [float(np.mean(p == y)) for p in values]
            f1 = [rf.macro_f1(y, p, 6) for p in values]
            cms = []
            for p in values:
                cm = np.zeros((6, 6), dtype=int)
                np.add.at(cm, (y, p), 1)
                cms.append(cm.tolist())
            metrics.append(dict(feature_set=fs, model=model, accuracy=float(np.mean(acc)),
                                accuracy_seed_sd=float(np.std(acc)), macro_f1=float(np.mean(f1)),
                                macro_f1_seed_sd=float(np.std(f1)), confusion_matrices=cms))
    return dict(evaluation="six-posture-participant-level-loso", class_order=LAB6,
                posture_ids=POSTURE_IDS, sample_count=len(y), samples=audit,
                aggregation_audit=aggregation_audit(samples),
                eligible_sample_keys=[s.sample_key for s in eligible],
                eligible_class_counts={label: int(np.sum(y == k)) for k, label in enumerate(LAB6)},
                feature_order={"H5": H5_FEATURE_NAMES, "H9": H9_FEATURE_NAMES},
                tree_count=rf.H_EVAL_TREES, max_features=rf.H_EVAL_MAX_FEATURES,
                seeds=rf.H_EVAL_SEEDS, m2_lambda=rf.H_EVAL_M2_LAMBDA,
                confusion_matrix_axes="rows=actual, columns=predicted; one matrix per seed",
                folds=folds, metrics=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--frames", nargs="+")
    inputs.add_argument("--probe-metadata", nargs="+", metavar="CSV")
    inputs.add_argument("--probe-csv", nargs="+", metavar="CSV")
    args = parser.parse_args()
    if args.probe_csv:
        samples = load_labeled_probe_h_samples(args.probe_csv)
    elif args.probe_metadata:
        samples = load_probe_h_samples(args.probe_metadata)
    else:
        samples = load_h_samples(args.frames)
    print(json.dumps(evaluate_samples(samples), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
