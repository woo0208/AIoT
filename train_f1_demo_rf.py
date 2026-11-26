"""Train the three-class F1-5 engineering-demo Random Forest.

Training uses individual complete canonical frames.  It intentionally reports
no frame-random validation score: frames from one recording are correlated.
Synthetic inputs are appropriate for software tests only, never as research
evidence or a claim of posture-classification accuracy.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys

import numpy as np

import f1_csv_adapter
from f1_demo_rf import (
    ARTIFACT_FORMAT,
    CLASS_LABELS,
    FEATURE_CONTRACT,
    FEATURE_NAMES,
    FEATURE_UNITS,
    MODEL_FORMAT,
    artifact_integrity_sha256,
)
from rf_experiment import Forest


TRAINER_VERSION = "aiot-f1-demo-rf-trainer/1.0.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _serialize_forest(forest: Forest) -> dict:
    trees = []
    for tree in forest.trees:
        trees.append({
            "feature": [int(v) for v in tree.feat],
            "threshold": [float(v) for v in tree.thr],
            "left": [int(v) for v in tree.left],
            "right": [int(v) for v in tree.right],
            "probability": [[float(v) for v in row] for row in tree.value],
        })
    return {"trees": trees}


def _software_versions() -> dict:
    root = Path(__file__).resolve().parent
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "trainer_version": TRAINER_VERSION,
        "trainer_sha256": _sha256(Path(__file__).resolve()),
        "inference_sha256": _sha256(root / "f1_demo_rf.py"),
        "forest_implementation_sha256": _sha256(root / "rf_experiment.py"),
        "f1_calculator_sha256": _sha256(root / "f1_features.py"),
        "csv_adapter_sha256": _sha256(root / "f1_csv_adapter.py"),
    }


def train_f1_demo_rf(
    csv_paths: list[str | Path] | tuple[str | Path, ...],
    output_path: str | Path,
    *,
    n_estimators: int = 100,
    max_features: int = 2,
    random_seed: int = 0,
) -> dict:
    """Train and exclusively create one integrity-protected JSON artifact."""

    if not csv_paths:
        raise ValueError("at least one explicit canonical CSV path is required")
    if type(n_estimators) is not int or n_estimators < 1:
        raise ValueError("n_estimators must be a positive integer")
    if type(max_features) is not int or not 1 <= max_features <= len(FEATURE_NAMES):
        raise ValueError(f"max_features must be between 1 and {len(FEATURE_NAMES)}")
    if type(random_seed) is not int or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer")

    destination = Path(output_path).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {destination.parent}")

    resolved_inputs = [Path(path).expanduser().resolve(strict=True) for path in csv_paths]
    if len(set(resolved_inputs)) != len(resolved_inputs):
        raise ValueError("duplicate canonical CSV path")

    vectors: list[tuple[float, ...]] = []
    labels: list[str] = []
    label_counts = Counter()
    rejected_by_label = Counter()
    rejected_reasons = Counter()
    inputs = []
    identities: set[tuple[str, str]] = set()

    for path in resolved_inputs:
        before_hash = _sha256(path)
        _, records = f1_csv_adapter.load_f1_frame_records(str(path))
        after_hash = _sha256(path)
        if before_hash != after_hash:
            raise ValueError(f"input CSV changed while being read: {path}")
        identity = (records[0].recording_id, records[0].analysis_run_id)
        if identity in identities:
            raise ValueError(f"duplicate recording/run identity across inputs: {identity}")
        identities.add(identity)

        input_valid = 0
        input_rejected = 0
        for record in records:
            if record.label not in CLASS_LABELS:
                raise ValueError(
                    f"invalid training label {record.label!r} at "
                    f"{path}:{record.frame_index}; expected one of {CLASS_LABELS}"
                )
            values = record.result.ordered_values()
            if any(value is None for value in values):
                input_rejected += 1
                rejected_by_label[record.label] += 1
                reasons = {
                    reason
                    for family_reasons in record.result.family_reasons.values()
                    for reason in family_reasons
                }
                for reason in reasons or {"feature_unavailable"}:
                    rejected_reasons[reason] += 1
                continue
            vector = tuple(float(value) for value in values)
            if not all(math.isfinite(value) for value in vector):
                input_rejected += 1
                rejected_by_label[record.label] += 1
                rejected_reasons["feature_nonfinite"] += 1
                continue
            vectors.append(vector)
            labels.append(record.label)
            label_counts[record.label] += 1
            input_valid += 1
        inputs.append({
            "path": str(path),
            "sha256": before_hash,
            "recording_id": identity[0],
            "analysis_run_id": identity[1],
            "frame_count": len(records),
            "valid_frame_count": input_valid,
            "rejected_frame_count": input_rejected,
        })

    missing_classes = [label for label in CLASS_LABELS if label_counts[label] == 0]
    if missing_classes:
        raise ValueError(
            "training requires at least one usable complete F1-5 frame for every class; "
            f"missing usable classes: {missing_classes}; usable counts: {dict(label_counts)}"
        )

    x = np.asarray(vectors, dtype=float)
    y = np.asarray([CLASS_LABELS.index(label) for label in labels], dtype=int)
    forest = Forest(
        len(CLASS_LABELS), n_trees=n_estimators, max_features=max_features,
        split_w=None, seed=random_seed,
    ).fit(x, y)

    metadata = {
        "model_format": MODEL_FORMAT,
        "feature_contract": FEATURE_CONTRACT,
        "feature_names": list(FEATURE_NAMES),
        "feature_units": list(FEATURE_UNITS),
        "class_labels": list(CLASS_LABELS),
        "model_configuration": {
            "implementation": "rf_experiment.Forest/unweighted",
            "n_estimators": n_estimators,
            "max_features": max_features,
            "random_seed": random_seed,
            "criterion": "gini",
            "bootstrap": True,
        },
        "training": {
            "purpose": "engineering three-class posture demo; not approved research M0/M1/M2",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_csvs": inputs,
            "label_counts": {label: label_counts[label] for label in CLASS_LABELS},
            "valid_frame_count": len(vectors),
            "rejected_frame_count": sum(rejected_by_label.values()),
            "rejected_frame_counts_by_label": {
                label: rejected_by_label[label] for label in CLASS_LABELS
            },
            "rejection_reason_counts": dict(sorted(rejected_reasons.items())),
            "unit_of_training": "individual canonical frame",
            "validation": None,
            "validation_note": (
                "No frame-random validation is reported; repeated frames within a recording are correlated."
            ),
        },
        "software": _software_versions(),
    }
    signed = {
        "artifact_format": ARTIFACT_FORMAT,
        "payload": {"metadata": metadata, "model": _serialize_forest(forest)},
    }
    document = {
        **signed,
        "integrity": {"algorithm": "sha256", "sha256": artifact_integrity_sha256(signed)},
    }
    encoded = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite existing artifact: {destination}") from None
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the F1-5 three-class engineering-demo Random Forest."
    )
    parser.add_argument("--input", nargs="+", required=True, metavar="FRAMES_CSV",
                        help="explicit canonical frames-schema/1.0.0 CSV path(s)")
    parser.add_argument("--output", required=True, metavar="MODEL_JSON",
                        help="new artifact path; an existing file is never overwritten")
    parser.add_argument("--trees", type=int, default=100)
    parser.add_argument("--max-features", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        document = train_f1_demo_rf(
            args.input, args.output, n_estimators=args.trees,
            max_features=args.max_features, random_seed=args.seed,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    training = document["payload"]["metadata"]["training"]
    print(f"saved: {Path(args.output).resolve()}")
    print(f"usable frames: {training['valid_frame_count']}")
    print(f"rejected frames: {training['rejected_frame_count']}")
    print(f"class counts: {training['label_counts']}")
    print(training["validation_note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
