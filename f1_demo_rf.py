"""Fail-closed F1-5 Random Forest inference for an engineering demo.

This module is deliberately separate from ``posture_prediction.py`` and its
LAB5 research boundary.  Artifacts are non-executable JSON and describe a
three-class engineering model, not an approved research M0/M1/M2 model.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from numbers import Real
from pathlib import Path
from typing import Sequence

from f1_features import F1_5_FEATURE_NAMES, F1_5_FEATURE_UNITS, F1FrameResult


ARTIFACT_FORMAT = "aiot-f1-demo-rf/1.0.0"
MODEL_FORMAT = "aiot-f1-demo-rf-tree-json/1.0.0"
FEATURE_CONTRACT = "FEAT-009/F1-5"
CLASS_LABELS = ("upright", "forward_head", "body_forward")
FEATURE_NAMES = tuple(F1_5_FEATURE_NAMES)
FEATURE_UNITS = tuple(F1_5_FEATURE_UNITS[name] for name in FEATURE_NAMES)
PREDICTION_AVAILABLE = "PREDICTION_AVAILABLE"
PREDICTION_UNAVAILABLE = "PREDICTION_UNAVAILABLE"


class ArtifactValidationError(ValueError):
    """The supplied artifact is malformed, incompatible, or not intact."""


@dataclass(frozen=True)
class F1DemoFeatureVector:
    """An explicitly ordered vector with its exact F1-5 contract identity."""

    values: tuple[Real, ...]
    feature_names: tuple[str, ...] = FEATURE_NAMES
    feature_units: tuple[str, ...] = FEATURE_UNITS

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "feature_names", tuple(self.feature_names))
        object.__setattr__(self, "feature_units", tuple(self.feature_units))


@dataclass(frozen=True)
class F1DemoPrediction:
    status: str
    label: str | None
    reason: str

    @classmethod
    def unavailable(cls, reason: str) -> "F1DemoPrediction":
        return cls(PREDICTION_UNAVAILABLE, None, reason)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError(f"artifact is not canonical JSON data: {exc}") from exc


def artifact_integrity_sha256(artifact_without_integrity: dict) -> str:
    """Return the artifact digest; exposed for deterministic artifact writers/tests."""

    return hashlib.sha256(_canonical_bytes(artifact_without_integrity)).hexdigest()


def _exact_sequence(value: object, expected: tuple[str, ...], field: str) -> None:
    if not isinstance(value, list) or tuple(value) != expected:
        raise ArtifactValidationError(f"{field} must exactly equal {list(expected)!r}")


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ArtifactValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ArtifactValidationError(f"{field} must be a finite real number")
    return float(value)


def _validate_tree(tree: object, tree_index: int) -> dict:
    if not isinstance(tree, dict):
        raise ArtifactValidationError(f"model.trees[{tree_index}] must be an object")
    required = {"feature", "threshold", "left", "right", "probability"}
    if set(tree) != required or not all(isinstance(tree[k], list) for k in required):
        raise ArtifactValidationError(f"model.trees[{tree_index}] has an invalid structure")
    n = len(tree["feature"])
    if n == 0 or any(len(tree[k]) != n for k in required):
        raise ArtifactValidationError(f"model.trees[{tree_index}] node arrays do not align")

    for node in range(n):
        feature = tree["feature"][node]
        left, right = tree["left"][node], tree["right"][node]
        if type(feature) is not int or type(left) is not int or type(right) is not int:
            raise ArtifactValidationError(f"tree {tree_index} node {node} indices must be integers")
        _finite(tree["threshold"][node], f"tree {tree_index} node {node} threshold")
        probabilities = tree["probability"][node]
        if not isinstance(probabilities, list) or len(probabilities) != len(CLASS_LABELS):
            raise ArtifactValidationError(f"tree {tree_index} node {node} probability width mismatch")
        values = [_finite(v, f"tree {tree_index} node {node} probability") for v in probabilities]
        if any(v < 0 for v in values) or math.fsum(values) <= 0:
            raise ArtifactValidationError(f"tree {tree_index} node {node} probabilities are invalid")
        if feature == -1:
            if left != -1 or right != -1:
                raise ArtifactValidationError(f"tree {tree_index} leaf {node} has children")
        elif not (0 <= feature < len(FEATURE_NAMES) and 0 <= left < n and 0 <= right < n):
            raise ArtifactValidationError(f"tree {tree_index} node {node} has an invalid split")

    visiting: set[int] = set()
    visited: set[int] = set()

    def walk(node: int) -> None:
        if node in visiting:
            raise ArtifactValidationError(f"tree {tree_index} contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        if tree["feature"][node] != -1:
            walk(tree["left"][node])
            walk(tree["right"][node])
        visiting.remove(node)
        visited.add(node)

    walk(0)
    if len(visited) != n:
        raise ArtifactValidationError(f"tree {tree_index} contains unreachable nodes")
    return tree


def _validate_artifact(document: object) -> dict:
    if not isinstance(document, dict) or set(document) != {"artifact_format", "payload", "integrity"}:
        raise ArtifactValidationError("artifact must contain only artifact_format, payload, and integrity")
    integrity = document["integrity"]
    if not isinstance(integrity, dict) or set(integrity) != {"algorithm", "sha256"}:
        raise ArtifactValidationError("invalid artifact integrity record")
    if integrity.get("algorithm") != "sha256" or not isinstance(integrity.get("sha256"), str):
        raise ArtifactValidationError("unsupported artifact integrity algorithm")
    signed = {"artifact_format": document["artifact_format"], "payload": document["payload"]}
    actual = artifact_integrity_sha256(signed)
    if not hmac.compare_digest(integrity["sha256"], actual):
        raise ArtifactValidationError("artifact SHA-256 integrity check failed")
    if document["artifact_format"] != ARTIFACT_FORMAT:
        raise ArtifactValidationError(f"unsupported artifact format: {document['artifact_format']!r}")

    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ArtifactValidationError("artifact payload must be an object")
    metadata, model = payload.get("metadata"), payload.get("model")
    if not isinstance(metadata, dict) or not isinstance(model, dict):
        raise ArtifactValidationError("artifact metadata and model must be objects")
    if metadata.get("model_format") != MODEL_FORMAT:
        raise ArtifactValidationError(f"unsupported model format: {metadata.get('model_format')!r}")
    if metadata.get("feature_contract") != FEATURE_CONTRACT:
        raise ArtifactValidationError("feature contract identifier mismatch")
    _exact_sequence(metadata.get("feature_names"), FEATURE_NAMES, "metadata.feature_names")
    _exact_sequence(metadata.get("feature_units"), FEATURE_UNITS, "metadata.feature_units")
    _exact_sequence(metadata.get("class_labels"), CLASS_LABELS, "metadata.class_labels")

    config = metadata.get("model_configuration")
    if not isinstance(config, dict) or config.get("implementation") != "rf_experiment.Forest/unweighted":
        raise ArtifactValidationError("unsupported Random Forest implementation")
    n_trees = _integer(config.get("n_estimators"), "n_estimators", minimum=1)
    _integer(config.get("max_features"), "max_features", minimum=1)
    _integer(config.get("random_seed"), "random_seed", minimum=0)
    if config["max_features"] > len(FEATURE_NAMES):
        raise ArtifactValidationError("max_features exceeds the F1-5 width")
    if set(model) != {"trees"} or not isinstance(model["trees"], list) or len(model["trees"]) != n_trees:
        raise ArtifactValidationError("model tree count does not match metadata")
    for index, tree in enumerate(model["trees"]):
        _validate_tree(tree, index)
    return payload


class F1DemoRFModel:
    """Validated in-memory model; it never loads executable pickle data."""

    def __init__(self, payload: dict):
        self.metadata = payload["metadata"]
        self._trees = payload["model"]["trees"]

    def predict(self, features: F1FrameResult | F1DemoFeatureVector | Sequence[Real]) -> F1DemoPrediction:
        vector, reason = _coerce_features(features)
        if vector is None:
            return F1DemoPrediction.unavailable(reason)
        totals = [0.0] * len(CLASS_LABELS)
        try:
            for tree in self._trees:
                node = 0
                while tree["feature"][node] != -1:
                    feature = tree["feature"][node]
                    node = tree["left"][node] if vector[feature] <= tree["threshold"][node] else tree["right"][node]
                probabilities = tree["probability"][node]
                for index, value in enumerate(probabilities):
                    totals[index] += value
        except Exception as exc:
            return F1DemoPrediction.unavailable(f"model execution failed: {exc}")
        label = CLASS_LABELS[max(range(len(totals)), key=totals.__getitem__)]
        return F1DemoPrediction(PREDICTION_AVAILABLE, label, "model prediction")


def _coerce_features(
    features: F1FrameResult | F1DemoFeatureVector | Sequence[Real],
) -> tuple[tuple[float, ...] | None, str]:
    if isinstance(features, F1FrameResult):
        values = features.ordered_values()
        missing = [name for name, value in zip(FEATURE_NAMES, values) if value is None]
        if missing:
            details = sorted({reason for reasons in features.family_reasons.values() for reason in reasons})
            return None, f"required F1-5 features unavailable: {missing}; reasons: {details}"
    elif isinstance(features, F1DemoFeatureVector):
        if features.feature_names != FEATURE_NAMES or features.feature_units != FEATURE_UNITS:
            return None, "feature contract mismatch: exact F1-5 names, order, and units are required"
        values = features.values
    elif isinstance(features, Sequence) and not isinstance(features, (str, bytes, bytearray)):
        values = tuple(features)
    else:
        return None, "features must be an F1FrameResult or explicitly ordered feature vector"
    if len(values) != len(FEATURE_NAMES):
        return None, f"feature vector has {len(values)} values; expected {len(FEATURE_NAMES)}"
    converted = []
    for name, value in zip(FEATURE_NAMES, values):
        if value is None:
            return None, f"required feature {name} is unavailable"
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
            return None, f"required feature {name} must be a finite real number"
        converted.append(float(value))
    return tuple(converted), ""


def load_f1_demo_model(path: str | Path) -> F1DemoRFModel:
    artifact_path = Path(path)
    try:
        with artifact_path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f"could not read model artifact: {exc}") from exc
    return F1DemoRFModel(_validate_artifact(document))


def predict_f1_demo(
    artifact_path: str | Path,
    features: F1FrameResult | F1DemoFeatureVector | Sequence[Real],
) -> F1DemoPrediction:
    """Load the explicitly supplied artifact and make one fail-closed prediction."""

    try:
        model = load_f1_demo_model(artifact_path)
    except FileNotFoundError:
        return F1DemoPrediction.unavailable(f"model artifact not found: {Path(artifact_path)}")
    except ArtifactValidationError as exc:
        return F1DemoPrediction.unavailable(f"model artifact rejected: {exc}")
    except Exception as exc:
        return F1DemoPrediction.unavailable(f"model artifact load failed: {exc}")
    return model.predict(features)


__all__ = [
    "ARTIFACT_FORMAT", "ArtifactValidationError", "CLASS_LABELS", "FEATURE_CONTRACT",
    "FEATURE_NAMES", "FEATURE_UNITS", "F1DemoFeatureVector", "F1DemoPrediction",
    "F1DemoRFModel", "MODEL_FORMAT", "PREDICTION_AVAILABLE", "PREDICTION_UNAVAILABLE",
    "artifact_integrity_sha256", "load_f1_demo_model", "predict_f1_demo",
]
