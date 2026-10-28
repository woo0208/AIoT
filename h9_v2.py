"""H9-v2 candidate calculation/aggregation only: F1..F8 + C3.

Implements the 2026-10-27 minimal implementation request, following
``analysis/h9/pilot_20261026/H9_v2_candidate_validity_20261027.md``.
F1..F8 and C3 are selected from an existing, same-frame GeometryResult;
C3 is exactly ``sagittal_torso_lean_deg``, without recomputation or calibration.
It depends on shoulder/hip metric depth, unlike the hipless legacy H9.

All nine inputs share this candidate's OWN complete-frame support. F3 uses
the existing directed circular mean; every other column, including C3, uses
the scalar median. Eligibility is unchanged: >=30 complete frames and >=50%
of all frames supplied for the sample. Missing observations stay None.

This in-memory API does not read/write CSVs, fit/evaluate models, authorize
capture, or freeze a scientific schema/resolve OPEN-002/003/005. The caller
must supply only one posture segment, excluding PREP/TRANSITION, with the
same frame/sample identity as the geometry. No legacy H5 projection is exposed.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from f1_sample_aggregator import (
    H9_FEATURE_NAMES,
    _aggregate_h_sample,
    _validate_h_frame_record,
)
from posture_geometry import GeometryResult


H9_V2_FEATURE_SET = "H9-v2"
H9_V2_C3_FEATURE = "sagittal_torso_lean_deg"
H9_V2_FEATURE_NAMES = H9_FEATURE_NAMES[:8] + (H9_V2_C3_FEATURE,)
# Candidate implementation identifier, not a frozen scientific schema version.
H9_V2_AGGREGATION_SPEC_ID = "h9-v2-candidate-common-9-feature-aggregation/1.0.0"


@dataclass(frozen=True)
class H9V2FrameRecord:
    """Distinct from HFrameRecord; exact F1..F8+C3 keys, finite values or None."""

    analysis_run_id: str
    recording_id: str
    frame_index: int
    subject: str
    round: str | None
    step: str
    label: str
    features: Mapping[str, float | None]

    def __post_init__(self) -> None:
        _validate_h_frame_record(self, H9_V2_FEATURE_NAMES, H9_V2_FEATURE_SET)

    @property
    def frame_key(self) -> tuple[str, str, int]:
        return (self.analysis_run_id, self.recording_id, self.frame_index)


@dataclass(frozen=True)
class H9V2SampleResult:
    """Candidate-specific values/support; cannot enter legacy HSampleResult APIs."""

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
        for name in ("features", "missing_counts"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    @property
    def feature_set(self) -> str:
        return H9_V2_FEATURE_SET

    @property
    def feature_names(self) -> tuple[str, ...]:
        return H9_V2_FEATURE_NAMES

    def ordered_values(self, feature_set: str = H9_V2_FEATURE_SET) -> tuple[float, ...]:
        """Return only H9-v2 order, failing closed for legacy names/ineligibility."""

        if feature_set != H9_V2_FEATURE_SET:
            raise ValueError(f"unsupported H9-v2 feature set: {feature_set!r}")
        if not self.eligible:
            raise ValueError("ineligible H9-v2 sample: " + "; ".join(self.eligibility_reasons))
        values = tuple(self.features[name] for name in H9_V2_FEATURE_NAMES)
        if any(value is None for value in values):
            raise ValueError("eligible H9-v2 sample contains an undefined aggregate")
        return tuple(float(value) for value in values)


def h9_v2_frame_from_geometry(
    result: GeometryResult, *, analysis_run_id: str, recording_id: str,
    frame_index: int, subject: str, round: str | None, step: str, label: str,
) -> H9V2FrameRecord:
    """Select same-frame existing values; geometry owns observation validity.

    No XYZ or torso angle is recalculated. Unavailable geometry outputs must
    already be None, as produced by compute_candidate_geometry. Structurally
    missing keys or malformed numeric values fail closed, never become zero.
    """

    if not isinstance(result, GeometryResult):
        raise ValueError(f"not a GeometryResult: {type(result).__name__}")
    return H9V2FrameRecord(
        analysis_run_id=analysis_run_id, recording_id=recording_id,
        frame_index=frame_index, subject=subject, round=round, step=step, label=label,
        features={name: result.features[name] for name in H9_V2_FEATURE_NAMES},
    )


def aggregate_h9_v2_sample(records: Iterable[H9V2FrameRecord]) -> H9V2SampleResult:
    """Aggregate one segment on F1..F8+C3 support, independently of legacy F9."""

    return _aggregate_h_sample(
        records, record_type=H9V2FrameRecord, feature_names=H9_V2_FEATURE_NAMES,
        aggregation_spec=H9_V2_AGGREGATION_SPEC_ID, result_type=H9V2SampleResult,
    )
