"""Minimal, fail-closed posture prediction boundary.

This module defines transport and execution contracts only. It does not define
F1/F2 features, load a production model artifact, or connect prediction to the
D455 capture path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from numbers import Real
from typing import Mapping, Optional, Protocol, Tuple, runtime_checkable


# Keep this independent constant explicit so changing rf_experiment.py cannot
# silently change the inference boundary's class order.
LAB5_LABELS: Tuple[str, ...] = (
    "upright",
    "forward_head",
    "lean_back",
    "lean_left",
    "lean_right",
)


class PredictionClass(str, Enum):
    """Coarse result exposed to a future application boundary."""

    NORMAL = "NORMAL"
    POOR = "POOR"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class PredictionReason(str, Enum):
    """Stable machine-readable reasons; no scientific thresholds are implied."""

    MODEL_PREDICTION = "MODEL_PREDICTION"
    MODEL_ABSTAINED = "MODEL_ABSTAINED"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    FEATURE_VECTOR_INVALID = "FEATURE_VECTOR_INVALID"
    FEATURE_CONTRACT_MISMATCH = "FEATURE_CONTRACT_MISMATCH"
    BINARY_MAPPING_NOT_CONFIGURED = "BINARY_MAPPING_NOT_CONFIGURED"
    MODEL_ARTIFACT_UNAVAILABLE = "MODEL_ARTIFACT_UNAVAILABLE"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    MODEL_INTEGRITY_VALIDATION_FAILED = (
        "MODEL_INTEGRITY_VALIDATION_FAILED"
    )
    MODEL_EXECUTION_FAILED = "MODEL_EXECUTION_FAILED"


_UNKNOWN_REASONS = frozenset(
    {
        PredictionReason.MODEL_ABSTAINED,
        PredictionReason.MODEL_OUTPUT_INVALID,
        PredictionReason.FEATURE_VECTOR_INVALID,
        PredictionReason.FEATURE_CONTRACT_MISMATCH,
        PredictionReason.BINARY_MAPPING_NOT_CONFIGURED,
    }
)
_UNAVAILABLE_REASONS = frozenset(
    {
        PredictionReason.MODEL_ARTIFACT_UNAVAILABLE,
        PredictionReason.MODEL_LOAD_FAILED,
        PredictionReason.MODEL_INTEGRITY_VALIDATION_FAILED,
        PredictionReason.MODEL_EXECUTION_FAILED,
    }
)


@dataclass(frozen=True)
class PredictionResult:
    """One prediction with invariants tying class, LAB5 label, and reason."""

    prediction: PredictionClass
    reason: PredictionReason
    label: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.prediction, PredictionClass):
            raise ValueError("prediction must be a PredictionClass")
        if not isinstance(self.reason, PredictionReason):
            raise ValueError("reason must be a PredictionReason")

        if self.prediction in (
            PredictionClass.NORMAL,
            PredictionClass.POOR,
        ):
            valid = (
                self.label in LAB5_LABELS
                and self.reason is PredictionReason.MODEL_PREDICTION
            )
        elif self.prediction is PredictionClass.UNKNOWN:
            valid = self.label is None and self.reason in _UNKNOWN_REASONS
        else:
            valid = self.label is None and self.reason in _UNAVAILABLE_REASONS
        if not valid:
            raise ValueError("inconsistent prediction, label, and reason")

    @classmethod
    def classified(
        cls, label: str, prediction: PredictionClass
    ) -> "PredictionResult":
        """Build an explicitly mapped binary result.

        This constructor checks result consistency only. It is not model or
        mapping authorization; that trust boundary belongs to an executor.
        """

        if label not in LAB5_LABELS:
            raise ValueError("classified result requires a LAB5 label")
        if prediction not in (
            PredictionClass.NORMAL,
            PredictionClass.POOR,
        ):
            raise ValueError("classified result requires a binary class")
        return cls(prediction, PredictionReason.MODEL_PREDICTION, label)

    @classmethod
    def unknown(cls, reason: PredictionReason) -> "PredictionResult":
        return cls(PredictionClass.UNKNOWN, reason)

    @classmethod
    def unavailable(cls, reason: PredictionReason) -> "PredictionResult":
        return cls(PredictionClass.UNAVAILABLE, reason)


class FeatureValidationError(ValueError):
    """Raised when a feature vector is internally malformed."""


class FeatureContractMismatch(ValueError):
    """Raised when a vector does not match the model's declared contract."""


class ModelIntegrityValidationError(RuntimeError):
    """Raised when explicit model artifact integrity validation fails."""


def _validate_identifier(value: object, field: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a non-empty, trimmed string")


def _validate_feature_names(names: Tuple[str, ...]) -> None:
    if not names:
        raise ValueError("feature_names must not be empty")
    for name in names:
        _validate_identifier(name, "feature name")
    if len(set(names)) != len(names):
        raise ValueError("feature_names must be unique")


def _validate_feature_units(
    units: Tuple[str, ...], expected_count: int
) -> None:
    if len(units) != expected_count:
        raise ValueError("feature unit count does not match ordered names")
    for unit in units:
        _validate_identifier(unit, "feature unit")


@dataclass(frozen=True)
class FeatureContract:
    """Exact ordered input binding supplied by a future approved model."""

    contract_id: str
    feature_names: Tuple[str, ...]
    feature_units: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_names", tuple(self.feature_names))
        object.__setattr__(self, "feature_units", tuple(self.feature_units))
        _validate_identifier(self.contract_id, "contract_id")
        _validate_feature_names(self.feature_names)
        _validate_feature_units(self.feature_units, len(self.feature_names))

    def validate(self, vector: "FeatureVector") -> None:
        if not isinstance(vector, FeatureVector):
            raise FeatureValidationError("features must be a FeatureVector")
        vector.validate()
        if (
            vector.contract_id != self.contract_id
            or vector.feature_names != self.feature_names
            or vector.feature_units != self.feature_units
        ):
            raise FeatureContractMismatch(
                "feature contract id, ordered names, or ordered units do not match"
            )


@dataclass(frozen=True)
class FeatureVector:
    """Ordered numeric inputs carrying their exact feature-contract identity."""

    contract_id: str
    feature_names: Tuple[str, ...]
    values: Tuple[Real, ...]
    feature_units: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_names", tuple(self.feature_names))
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "feature_units", tuple(self.feature_units))

    @classmethod
    def from_contract(
        cls, contract: FeatureContract, values: Tuple[Real, ...]
    ) -> "FeatureVector":
        if not isinstance(contract, FeatureContract):
            raise FeatureValidationError("contract must be a FeatureContract")
        return cls(
            contract_id=contract.contract_id,
            feature_names=contract.feature_names,
            values=tuple(values),
            feature_units=contract.feature_units,
        )

    def validate(self) -> None:
        try:
            _validate_identifier(self.contract_id, "contract_id")
            _validate_feature_names(self.feature_names)
            _validate_feature_units(
                self.feature_units, len(self.feature_names)
            )
        except ValueError as exc:
            raise FeatureValidationError(str(exc)) from exc
        if len(self.values) != len(self.feature_names):
            raise FeatureValidationError(
                "feature value count does not match ordered names"
            )
        for value in self.values:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise FeatureValidationError(
                    "feature values must be real numbers, not booleans"
                )
            if not math.isfinite(float(value)):
                raise FeatureValidationError("feature values must be finite")


@runtime_checkable
class PredictionModel(Protocol):
    """Interface implemented by a future loaded model adapter."""

    @property
    def feature_contract(self) -> FeatureContract:
        ...

    def predict_label(self, features: FeatureVector) -> Optional[str]:
        """Return one LAB5 label, or None to abstain."""
        ...


@runtime_checkable
class ModelLoader(Protocol):
    """Interface for a future verified production artifact loader."""

    def load(self) -> PredictionModel:
        ...


@runtime_checkable
class PredictionExecutor(Protocol):
    """Application-facing execution interface."""

    def predict(self, features: FeatureVector) -> PredictionResult:
        ...


class UnavailablePredictor:
    """Default production-safe executor when no usable model exists."""

    def __init__(
        self,
        reason: PredictionReason = PredictionReason.MODEL_ARTIFACT_UNAVAILABLE,
    ) -> None:
        if reason not in _UNAVAILABLE_REASONS:
            raise ValueError(
                "UnavailablePredictor requires an unavailable reason"
            )
        self._result = PredictionResult.unavailable(reason)

    def predict(self, features: FeatureVector) -> PredictionResult:
        return self._result


class TestOnlyModelPredictionRunner:
    """Test-only structural runner; never a production authorization path."""

    def __init__(
        self,
        model: PredictionModel,
        binary_mapping: Optional[Mapping[str, PredictionClass]],
    ) -> None:
        contract = getattr(model, "feature_contract", None)
        if (
            not isinstance(contract, FeatureContract)
            or not callable(getattr(model, "predict_label", None))
        ):
            raise TypeError("loaded model does not satisfy PredictionModel")
        self._model = model
        self._contract = contract
        self._binary_mapping = _validate_binary_mapping(binary_mapping)

    def predict(self, features: FeatureVector) -> PredictionResult:
        try:
            self._contract.validate(features)
        except FeatureContractMismatch:
            return PredictionResult.unknown(
                PredictionReason.FEATURE_CONTRACT_MISMATCH
            )
        except Exception:
            return PredictionResult.unknown(
                PredictionReason.FEATURE_VECTOR_INVALID
            )

        try:
            label = self._model.predict_label(features)
        except Exception:
            return PredictionResult.unavailable(
                PredictionReason.MODEL_EXECUTION_FAILED
            )

        if label is None:
            return PredictionResult.unknown(PredictionReason.MODEL_ABSTAINED)
        if not isinstance(label, str) or label not in LAB5_LABELS:
            return PredictionResult.unknown(
                PredictionReason.MODEL_OUTPUT_INVALID
            )
        if (
            self._binary_mapping is None
            or label not in self._binary_mapping
        ):
            return PredictionResult.unknown(
                PredictionReason.BINARY_MAPPING_NOT_CONFIGURED
            )
        return PredictionResult.classified(
            label, self._binary_mapping[label]
        )


def _validate_binary_mapping(
    mapping: Optional[Mapping[str, PredictionClass]],
) -> Optional[dict[str, PredictionClass]]:
    if mapping is None:
        return None
    if not isinstance(mapping, Mapping):
        raise TypeError("binary_mapping must be a mapping or None")
    validated = dict(mapping)
    for label, prediction_class in validated.items():
        if label not in LAB5_LABELS:
            raise ValueError("binary_mapping keys must be LAB5 labels")
        if not isinstance(
            prediction_class, PredictionClass
        ) or prediction_class not in (
            PredictionClass.NORMAL,
            PredictionClass.POOR,
        ):
            raise ValueError(
                "binary_mapping values must be NORMAL or POOR"
            )
    return validated


def build_prediction_executor(
    loader: Optional[ModelLoader] = None,
) -> PredictionExecutor:
    """Build the fail-closed Prediction V0 production executor.

    Prediction V0 has no approved prediction-model artifact verification or
    binary mapping contract. The legacy ``loader`` parameter is accepted only
    for call compatibility and is deliberately never inspected or executed.
    No injected object, self-declared flag, or SHA string can authorize a
    production classification.
    """

    return UnavailablePredictor()


def build_test_prediction_executor(
    model: PredictionModel,
    binary_mapping: Optional[Mapping[str, PredictionClass]],
) -> PredictionExecutor:
    """Build an explicitly test-only executor around a synthetic model."""

    return TestOnlyModelPredictionRunner(model, binary_mapping)


def build_test_prediction_executor_from_loader(
    loader: ModelLoader,
    binary_mapping: Optional[Mapping[str, PredictionClass]],
) -> PredictionExecutor:
    """Exercise loader/error contracts in structural tests only."""

    validated_mapping = _validate_binary_mapping(binary_mapping)
    if not callable(getattr(loader, "load", None)):
        return UnavailablePredictor(PredictionReason.MODEL_LOAD_FAILED)
    try:
        model = loader.load()
        return TestOnlyModelPredictionRunner(model, validated_mapping)
    except FileNotFoundError:
        return UnavailablePredictor(
            PredictionReason.MODEL_ARTIFACT_UNAVAILABLE
        )
    except ModelIntegrityValidationError:
        return UnavailablePredictor(
            PredictionReason.MODEL_INTEGRITY_VALIDATION_FAILED
        )
    except Exception:
        return UnavailablePredictor(PredictionReason.MODEL_LOAD_FAILED)


__all__ = [
    "FeatureContract",
    "FeatureContractMismatch",
    "FeatureValidationError",
    "FeatureVector",
    "LAB5_LABELS",
    "ModelLoader",
    "ModelIntegrityValidationError",
    "PredictionClass",
    "PredictionExecutor",
    "PredictionModel",
    "PredictionReason",
    "PredictionResult",
    "TestOnlyModelPredictionRunner",
    "UnavailablePredictor",
    "build_prediction_executor",
    "build_test_prediction_executor",
    "build_test_prediction_executor_from_loader",
]
