from collections import Counter
from dataclasses import dataclass
import math
import statistics
import sys
from types import MappingProxyType
from typing import Iterable, Mapping

AXIAL_CANCELLATION_GUARD = 16 * sys.float_info.epsilon

H5_FEATURE_NAMES = (
    "hipless_f1_candidate_head_center_dx_sw",
    "hipless_f1_candidate_head_center_dy_sw",
    "hipless_f1_candidate_face_axis_tilt_deg",
    "hipless_f1_candidate_ear_eye_dy_sw",
    "hipless_f1_candidate_nose_chin_distance_sw",
)

H9_RGBD_FEATURE_NAMES = (
    "hipless_f2_candidate_chest_depth_m",
    "hipless_f2_candidate_chest_forward_from_shoulders_m",
    "hipless_f2_candidate_nose_forward_from_chest_m",
    "hipless_f2_candidate_nose_forward_from_chest_sw3d",
)

H9_FEATURE_NAMES = H5_FEATURE_NAMES + H9_RGBD_FEATURE_NAMES

H_FACE_AXIS_FEATURE = "hipless_f1_candidate_face_axis_tilt_deg"

H_MIN_VALID_FRAMES = 30

H_MIN_COVERAGE = 0.50

H_AGGREGATION_SPEC_ID = "h5-h9-common-9-feature-aggregation/1.0.0"

_IDENTITY_FIELDS = ("analysis_run_id", "recording_id", "step", "subject", "round", "label")

def _require_text(field: str, value: object) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"invalid {field}: {value!r}")

def _validate_h_frame_record(record, feature_names, feature_set) -> None:
    """Shared identity/missing-value validation for distinct H frame types."""

    for name in ("analysis_run_id", "recording_id", "subject", "step", "label"):
        _require_text(name, getattr(record, name))
    if record.round is not None:
        _require_text("round", record.round)
    if type(record.frame_index) is not int or record.frame_index < 1:
        raise ValueError(f"invalid frame_index: {record.frame_index!r}")
    if set(record.features) != set(feature_names):
        raise ValueError(f"H frame features must contain the exact {feature_set} feature set")
    clean: dict[str, float | None] = {}
    for name in feature_names:
        value = record.features[name]
        if value is None:
            clean[name] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"invalid H feature {name}: {value!r}")
        elif not math.isfinite(float(value)):
            raise ValueError(f"non-finite H feature {name}: {value!r}")
        else:
            clean[name] = float(value)
    object.__setattr__(record, "features", MappingProxyType(clean))

@dataclass(frozen=True)
class HFrameRecord:
    """One frame of the shared H5/H9 candidate feature table.

    All nine keys are required.  A missing observation is represented only by
    ``None``; finite numeric values are normalised to ``float``.  The record is
    deliberately independent of the frozen canonical frame schema.
    """

    analysis_run_id: str
    recording_id: str
    frame_index: int
    subject: str
    round: str | None
    step: str
    label: str
    features: Mapping[str, float | None]

    def __post_init__(self) -> None:
        _validate_h_frame_record(self, H9_FEATURE_NAMES, "H9")

    @property
    def frame_key(self) -> tuple[str, str, int]:
        return (self.analysis_run_id, self.recording_id, self.frame_index)

@dataclass(frozen=True)
class HSampleResult:
    """H5 and H9 values aggregated from one shared nine-feature frame set."""

    aggregation_spec: str
    sample_key: tuple[str, str, str]
    subject: str
    round: str | None
    label: str
    n_frames: int
    common_valid_count: int
    common_coverage: float
    input_frame_indices: tuple[int, ...]
    common_valid_frame_indices: tuple[int, ...]
    features: Mapping[str, float | None]
    missing_counts: Mapping[str, int]
    face_axis_resultant: float | None
    eligible: bool
    eligibility_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))
        object.__setattr__(self, "missing_counts", MappingProxyType(dict(self.missing_counts)))

    def ordered_values(self, feature_set: str) -> tuple[float, ...]:
        """Return model-ready H5/H9 values, failing closed when ineligible."""

        if feature_set == "H5":
            names = H5_FEATURE_NAMES
        elif feature_set == "H9":
            names = H9_FEATURE_NAMES
        else:
            raise ValueError(f"unsupported H feature set: {feature_set!r}")
        if not self.eligible:
            raise ValueError(
                "ineligible H sample: " + "; ".join(self.eligibility_reasons)
            )
        values = tuple(self.features[name] for name in names)
        if any(value is None for value in values):
            raise ValueError("eligible H sample contains an undefined aggregate")
        return tuple(float(value) for value in values)

def _circular_mean_degrees(values: Iterable[float]) -> tuple[float | None, float]:
    """Directed circular mean in degrees, returned in ``[-180, 180)``."""

    values = tuple(values)
    c = math.fsum(math.cos(math.radians(value)) for value in values) / len(values)
    s = math.fsum(math.sin(math.radians(value)) for value in values) / len(values)
    resultant = math.hypot(c, s)
    if resultant <= AXIAL_CANCELLATION_GUARD:
        return None, resultant
    angle = math.degrees(math.atan2(s, c))
    if angle >= 180.0:
        angle -= 360.0
    elif angle < -180.0:
        angle += 360.0
    return angle + 0.0, resultant

def aggregate_h5_h9_sample(records: Iterable[HFrameRecord]) -> HSampleResult:
    """Aggregate one sample using frames where all nine H features are valid.

    H5 is the first five columns of the same aggregated H9 frame support.  A
    sample is model-eligible only when the shared support has at least 30
    frames and covers at least 50% of all input frames.  Eight scalar features
    use the median; the directed face-axis angle uses a circular mean.
    """

    return _aggregate_h_sample(
        records, record_type=HFrameRecord, feature_names=H9_FEATURE_NAMES,
        aggregation_spec=H_AGGREGATION_SPEC_ID, result_type=HSampleResult,
    )

def _aggregate_h_sample(records, *, record_type, feature_names, aggregation_spec, result_type):
    """Common H aggregation; callers supply distinct record/result types and order."""

    frames = tuple(records)
    if not frames:
        raise ValueError("empty input: sample identity cannot be established")
    for record in frames:
        if not isinstance(record, record_type):
            raise ValueError(f"not an {record_type.__name__}: {type(record).__name__}")
    for field in _IDENTITY_FIELDS:
        values = {getattr(record, field) for record in frames}
        if len(values) > 1:
            raise ValueError(f"conflicting sample identity {field}: {sorted(map(repr, values))}")
    keys = Counter(record.frame_key for record in frames)
    duplicates = sorted(key for key, count in keys.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate frame keys: {duplicates}")

    frames = tuple(sorted(frames, key=lambda record: record.frame_index))
    valid = tuple(
        record for record in frames
        if all(record.features[name] is not None for name in feature_names)
    )
    n_frames = len(frames)
    valid_count = len(valid)
    coverage = valid_count / n_frames
    reasons = []
    if valid_count < H_MIN_VALID_FRAMES:
        reasons.append(f"common_valid_frames<{H_MIN_VALID_FRAMES}")
    if coverage < H_MIN_COVERAGE:
        reasons.append(f"common_coverage<{H_MIN_COVERAGE:g}")

    features: dict[str, float | None] = dict.fromkeys(feature_names)
    resultant = None
    if valid:
        for name in feature_names:
            values = tuple(record.features[name] for record in valid)
            if name == H_FACE_AXIS_FEATURE:
                features[name], resultant = _circular_mean_degrees(values)
                if features[name] is None:
                    reasons.append("face_axis_circular_mean_undefined")
            else:
                features[name] = float(statistics.median(values))

    first = frames[0]
    return result_type(
        aggregation_spec=aggregation_spec,
        sample_key=(first.analysis_run_id, first.recording_id, first.step),
        subject=first.subject,
        round=first.round,
        label=first.label,
        n_frames=n_frames,
        common_valid_count=valid_count,
        common_coverage=coverage,
        input_frame_indices=tuple(record.frame_index for record in frames),
        common_valid_frame_indices=tuple(record.frame_index for record in valid),
        features=features,
        missing_counts={
            name: sum(record.features[name] is None for record in frames)
            for name in feature_names
        },
        face_axis_resultant=resultant,
        eligible=not reasons,
        eligibility_reasons=tuple(reasons),
    )
