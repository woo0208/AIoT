"""F1-5 frame-to-sample aggregation (Gate 1.8 engineering prototype, NOT APPROVED).

Consumes frame-level ``f1_features.F1FrameResult`` values (``FEAT-009``,
unchanged) of ONE sample and returns aggregated values plus structural
diagnostics.  Implements the PROPOSED candidates of
``docs/research/F1_FRAME_TO_SAMPLE_AGGREGATION_REVIEW_2026-10-12.md``:

    fs_x, fs_y, sh_x, sh_y : component-wise median of the frame-level values
    so_beta                : period-pi axial mean
        C = mean(cos 2b_i),  S = mean(sin 2b_i),  R = hypot(C, S)
        so_beta = wrap_pi(0.5 * atan2(S, C))

Sample identity is the proposed key ``(analysis_run_id, recording_id, step)``
(``summary-schema/1.0.0`` grouping precedent); ``subject``, ``round`` and
``label`` must be constant within it.  Frame identity is the canonical
``(analysis_run_id, recording_id, frame_index)`` (Schema section F.3).  The
caller must choose ``support`` explicitly:

    "joint"  : all five features use J = frames where FS, SH and SO are all available
    "family" : each feature uses its own family's available frames, so the
               features of one sample may summarise DIFFERENT frame subsets

Neither support policy, the median nor the axial mean is an approved research
decision (contract section 6; ``OPEN-002`` stays DEFERRED).  The result is a
diagnostic engineering output, not a model-ready sample: there is no
eligibility flag, no N_min, no R_min, no D_sh / visibility / presence
threshold, no imputation, and an undefined value is ``None``, never 0.  Labels
are carried as provenance only and never enter a calculation.  Nothing is read
from or written to disk.
"""

from collections import Counter
from dataclasses import dataclass
import math
import statistics
import sys
from types import MappingProxyType
from typing import Iterable, Mapping

from f1_features import (
    F1_5_FEATURE_FAMILIES,
    F1_5_FEATURE_NAMES,
    F1_CORE_DECISION,
    F1_FAMILIES,
    F1FrameResult,
    wrap_pi,
)


# Non-frozen prototype label; not a schema or contract version.
F1_AGGREGATION_SPEC_ID = "f1-sample-aggregation-prototype-gate1.8-unapproved"
SUPPORT_POLICIES = ("joint", "family")
JOINT = "joint"

# Floating-point cancellation guard for the axial resultant.  NOT a research R_min.
# An angle stored as float64 is only resolved to about one epsilon after doubling
# (e.g. sin(2 * fl(pi/2)) = 1.2e-16 rather than 0) and libm cos/sin add about one
# epsilon; math.fsum adds no accumulation error, so the error of C and S does
# not grow with the frame count.  A resultant at this scale is indistinguishable
# from exact cancellation, so the mean axis is reported undefined instead of an
# arbitrary atan2 direction.  The margin is purely numerical: any R above it is
# reported as defined, however small, because a scientific dispersion threshold
# (R_min) is not approved.
AXIAL_CANCELLATION_GUARD = 16 * sys.float_info.epsilon

# H5/H9 evaluation contract supplied for the 2026-10-22 research task.  These
# names intentionally reuse the already implemented hip-independent geometry
# outputs without changing frames-schema/1.0.0 or the existing F1-5 contract.
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


def _validate_frame_result(result: object) -> None:
    """Reject structurally malformed results; legitimate unavailability is not an error."""

    if not isinstance(result, F1FrameResult):
        raise ValueError(f"result is not an F1FrameResult: {type(result).__name__}")
    if set(result.features) != set(F1_5_FEATURE_NAMES):
        raise ValueError(f"F1FrameResult features keys: {sorted(result.features)!r}")
    for name in ("family_available", "family_reasons"):
        if set(getattr(result, name)) != set(F1_FAMILIES):
            raise ValueError(f"F1FrameResult {name} keys: {sorted(getattr(result, name))!r}")
    for family in F1_FAMILIES:
        available = result.family_available[family]
        reasons = result.family_reasons[family]
        if available is not True and available is not False:
            raise ValueError(f"family_available[{family}] is not a bool: {available!r}")
        if not isinstance(reasons, tuple) or not all(isinstance(r, str) and r for r in reasons):
            raise ValueError(f"family_reasons[{family}] is not a tuple of reasons: {reasons!r}")
        if available == bool(reasons):
            raise ValueError(f"family_available[{family}] inconsistent with family_reasons")
    for name in F1_5_FEATURE_NAMES:
        value = result.features[name]
        if result.family_available[F1_5_FEATURE_FAMILIES[name]]:
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError(f"available feature {name} is not a finite float: {value!r}")
        elif value is not None:
            raise ValueError(f"unavailable feature {name} has a value: {value!r}")
    beta = result.features["so_beta"]
    if beta is not None and not -math.pi / 2 <= beta < math.pi / 2:
        raise ValueError(f"so_beta outside [-pi/2, pi/2): {beta!r}")


@dataclass(frozen=True)
class F1FrameRecord:
    """One frame's ``F1FrameResult`` with its canonical frame key and sample identity.

    ``subject`` / ``round`` / ``step`` / ``label`` are the canonical
    ``frames-schema/1.0.0`` text fields of the same row.  ``round`` may be
    ``None`` when unknown; it is then never filled in or guessed.
    """

    analysis_run_id: str
    recording_id: str
    frame_index: int
    subject: str
    round: str | None
    step: str
    label: str
    result: F1FrameResult

    def __post_init__(self) -> None:
        for name in ("analysis_run_id", "recording_id", "subject", "step", "label"):
            _require_text(name, getattr(self, name))
        if self.round is not None:
            _require_text("round", self.round)
        if type(self.frame_index) is not int or self.frame_index < 1:
            raise ValueError(f"invalid frame_index: {self.frame_index!r}")
        _validate_frame_result(self.result)

    @property
    def frame_key(self) -> tuple[str, str, int]:
        return (self.analysis_run_id, self.recording_id, self.frame_index)


@dataclass(frozen=True)
class F1SampleResult:
    """Diagnostic aggregation of one sample; NOT a model-ready or eligible sample.

    Support names are ``"FS"``, ``"SH"``, ``"SO"`` and ``"joint"``.  Frame
    references are ``frame_index`` values within ``sample_key``'s run/recording.
    """

    aggregation_spec: str
    source_decision: str
    support_policy: str
    sample_key: tuple[str, str, str]           # (analysis_run_id, recording_id, step)
    subject: str
    round: str | None
    label: str
    n_frames: int
    input_frame_indices: tuple[int, ...]
    family_valid_counts: Mapping[str, int]     # FS, SH, SO
    joint_valid_count: int
    coverage: Mapping[str, float]              # FS, SH, SO, joint -> count / n_frames
    valid_frame_indices: Mapping[str, tuple[int, ...]]     # FS, SH, SO, joint
    selected_frame_indices: Mapping[str, tuple[int, ...]]  # FS, SH, SO under the policy
    feature_support: Mapping[str, str]         # feature -> support name actually used
    features: Mapping[str, float | None]
    feature_n_used: Mapping[str, int]
    undefined_reasons: Mapping[str, str | None]
    so_beta_resultant: float | None            # axial R on the selected SO support
    defined_features_same_frames: bool
    invalid_reason_counts: Mapping[str, Mapping[str, int]]

    def __post_init__(self) -> None:
        for name in ("family_valid_counts", "coverage", "valid_frame_indices",
                     "selected_frame_indices", "feature_support", "features",
                     "feature_n_used", "undefined_reasons"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        object.__setattr__(self, "invalid_reason_counts", MappingProxyType({
            family: MappingProxyType(dict(counts))
            for family, counts in self.invalid_reason_counts.items()
        }))

    def ordered_values(self) -> tuple[float | None, ...]:
        """Return the aggregated values in the frozen F1-5 output order."""

        return tuple(self.features[name] for name in F1_5_FEATURE_NAMES)


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
        for name in ("analysis_run_id", "recording_id", "subject", "step", "label"):
            _require_text(name, getattr(self, name))
        if self.round is not None:
            _require_text("round", self.round)
        if type(self.frame_index) is not int or self.frame_index < 1:
            raise ValueError(f"invalid frame_index: {self.frame_index!r}")
        if set(self.features) != set(H9_FEATURE_NAMES):
            raise ValueError("H frame features must contain the exact H9 feature set")
        clean: dict[str, float | None] = {}
        for name in H9_FEATURE_NAMES:
            value = self.features[name]
            if value is None:
                clean[name] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"invalid H feature {name}: {value!r}")
            elif not math.isfinite(float(value)):
                raise ValueError(f"non-finite H feature {name}: {value!r}")
            else:
                clean[name] = float(value)
        object.__setattr__(self, "features", MappingProxyType(clean))

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


def _axial_components(betas: Iterable[float]) -> tuple[float, float]:
    """Mean doubled-angle components ``(C, S)`` with exactly rounded summation."""

    betas = tuple(betas)
    n = len(betas)
    return (math.fsum(math.cos(2 * b) for b in betas) / n,
            math.fsum(math.sin(2 * b) for b in betas) / n)


def _axial_from_components(c: float, s: float) -> tuple[float | None, float, str | None]:
    """``(beta, R, undefined_reason)`` from mean doubled-angle components."""

    r = math.hypot(c, s)
    if r == 0.0:
        return None, r, "axial_resultant_zero"
    if r <= AXIAL_CANCELLATION_GUARD:
        return None, r, "axial_resultant_numerical_cancellation"
    return wrap_pi(0.5 * math.atan2(s, c)), r, None


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


def _in_support(record: F1FrameRecord, support_name: str) -> bool:
    available = record.result.family_available
    if support_name == JOINT:
        return all(available[family] for family in F1_FAMILIES)
    return available[support_name]


def aggregate_f1_sample(records: Iterable[F1FrameRecord], *, support: str) -> F1SampleResult:
    """Aggregate the F1-5 frame results of ONE sample under an explicit support policy.

    Raises ``ValueError`` (fail closed) for an unsupported policy, empty input,
    non-record items, mixed sample keys, conflicting ``subject`` / ``round`` /
    ``label`` and duplicate frame keys; malformed ``F1FrameResult`` values are
    already rejected by ``F1FrameRecord``.  Frames whose families are
    legitimately unavailable are counted, never an error.
    """

    if not isinstance(support, str) or support not in SUPPORT_POLICIES:
        raise ValueError(f"unsupported support policy: {support!r} (choose one of {SUPPORT_POLICIES})")
    frames = tuple(records)
    if not frames:
        raise ValueError("empty input: sample identity cannot be established")
    for record in frames:
        if not isinstance(record, F1FrameRecord):
            raise ValueError(f"not an F1FrameRecord: {type(record).__name__}")
    for field in _IDENTITY_FIELDS:
        values = {getattr(record, field) for record in frames}
        if len(values) > 1:
            raise ValueError(f"conflicting sample identity {field}: {sorted(map(repr, values))}")
    keys = Counter(record.frame_key for record in frames)
    duplicates = sorted(key for key, count in keys.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate frame keys: {duplicates}")

    frames = tuple(sorted(frames, key=lambda record: record.frame_index))
    n_frames = len(frames)
    support_names = (*F1_FAMILIES, JOINT)
    valid = {name: tuple(r.frame_index for r in frames if _in_support(r, name))
             for name in support_names}
    family_support = {family: JOINT if support == JOINT else family for family in F1_FAMILIES}
    feature_support = {name: family_support[F1_5_FEATURE_FAMILIES[name]]
                       for name in F1_5_FEATURE_NAMES}

    features: dict[str, float | None] = dict.fromkeys(F1_5_FEATURE_NAMES)
    undefined: dict[str, str | None] = dict.fromkeys(F1_5_FEATURE_NAMES)
    n_used: dict[str, int] = {}
    resultant = None
    for name in F1_5_FEATURE_NAMES:
        values = [r.result.features[name] for r in frames if _in_support(r, feature_support[name])]
        n_used[name] = len(values)
        if not values:
            undefined[name] = f"no_supported_frames:{feature_support[name]}"
        elif name == "so_beta":
            features[name], resultant, undefined[name] = _axial_from_components(
                *_axial_components(values))
        else:
            value = statistics.median(values)
            if math.isfinite(value):
                features[name] = value
            else:
                undefined[name] = "median_nonfinite"

    used_frame_sets = {valid[feature_support[name]] for name in F1_5_FEATURE_NAMES
                       if features[name] is not None}
    reason_counts = {
        family: dict(sorted(Counter(reason for r in frames
                                    for reason in r.result.family_reasons[family]).items()))
        for family in F1_FAMILIES
    }
    first = frames[0]
    return F1SampleResult(
        aggregation_spec=F1_AGGREGATION_SPEC_ID,
        source_decision=F1_CORE_DECISION,
        support_policy=support,
        sample_key=(first.analysis_run_id, first.recording_id, first.step),
        subject=first.subject,
        round=first.round,
        label=first.label,
        n_frames=n_frames,
        input_frame_indices=tuple(r.frame_index for r in frames),
        family_valid_counts={family: len(valid[family]) for family in F1_FAMILIES},
        joint_valid_count=len(valid[JOINT]),
        coverage={name: len(valid[name]) / n_frames for name in support_names},
        valid_frame_indices=valid,
        selected_frame_indices={family: valid[family_support[family]] for family in F1_FAMILIES},
        feature_support=feature_support,
        features=features,
        feature_n_used=n_used,
        undefined_reasons=undefined,
        so_beta_resultant=resultant,
        defined_features_same_frames=len(used_frame_sets) <= 1,
        invalid_reason_counts=reason_counts,
    )


def aggregate_h5_h9_sample(records: Iterable[HFrameRecord]) -> HSampleResult:
    """Aggregate one sample using frames where all nine H features are valid.

    H5 is the first five columns of the same aggregated H9 frame support.  A
    sample is model-eligible only when the shared support has at least 30
    frames and covers at least 50% of all input frames.  Eight scalar features
    use the median; the directed face-axis angle uses a circular mean.
    """

    frames = tuple(records)
    if not frames:
        raise ValueError("empty input: sample identity cannot be established")
    for record in frames:
        if not isinstance(record, HFrameRecord):
            raise ValueError(f"not an HFrameRecord: {type(record).__name__}")
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
        if all(record.features[name] is not None for name in H9_FEATURE_NAMES)
    )
    n_frames = len(frames)
    valid_count = len(valid)
    coverage = valid_count / n_frames
    reasons = []
    if valid_count < H_MIN_VALID_FRAMES:
        reasons.append(f"common_valid_frames<{H_MIN_VALID_FRAMES}")
    if coverage < H_MIN_COVERAGE:
        reasons.append(f"common_coverage<{H_MIN_COVERAGE:g}")

    features: dict[str, float | None] = dict.fromkeys(H9_FEATURE_NAMES)
    resultant = None
    if valid:
        for name in H9_FEATURE_NAMES:
            values = tuple(record.features[name] for record in valid)
            if name == H_FACE_AXIS_FEATURE:
                features[name], resultant = _circular_mean_degrees(values)
                if features[name] is None:
                    reasons.append("face_axis_circular_mean_undefined")
            else:
                features[name] = float(statistics.median(values))

    first = frames[0]
    return HSampleResult(
        aggregation_spec=H_AGGREGATION_SPEC_ID,
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
            for name in H9_FEATURE_NAMES
        },
        face_axis_resultant=resultant,
        eligible=not reasons,
        eligibility_reasons=tuple(reasons),
    )
