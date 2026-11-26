"""5-D-4 six-column preparation path; no training, metrics, camera or file I/O.

Keeps the formal evaluator's fixed eight-column synthetic path untouched.
Uses h6_offline class encoding and f0_fcal_features calculations directly.
Input times must already share an explicitly named seconds-based clock.
"""

from dataclasses import dataclass, replace
import math
from typing import Mapping

import numpy as np

import f0_fcal_features as core
from h6_offline import LAB6, analysis_label


@dataclass(frozen=True)
class TimedSegment:
    segment: core.Segment
    session: str | None
    hold_start_s: float | None
    hold_end_s: float | None
    time_basis: str | None
    # Each frame requires frame_index, time_s and phase ('hold'/'transition'/'prep').


@dataclass(frozen=True)
class Window:
    segment: core.Segment
    input_indices: tuple
    support_indices: tuple
    coverage: float | None
    reasons: tuple
    unprocessed: bool


@dataclass(frozen=True)
class Sample:
    sample_key: tuple
    subject: str
    original_label: str
    label: str
    class_index: int
    session: str | None
    reference_key: tuple | None
    f0: tuple
    f_cal: tuple
    missing_f0: tuple
    missing_f_cal: tuple
    is_reference: bool
    eligible: bool
    status: str
    reasons: tuple
    calibration_reasons: tuple
    input_indices: tuple
    support_indices: tuple
    coverage: float | None
    frame_loss_rate: None = None  # Policy/denominator not frozen; never estimated.


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _window(item):
    s = item.segment
    def pending(reason):
        return Window(replace(s, frames=()), (), (), None, (reason,), True)

    if item.session not in ("S1", "S2"):
        return pending("session_metadata_missing_or_invalid")
    if not isinstance(item.time_basis, str) or not item.time_basis:
        return pending("time_basis_missing")
    if not all(_finite(v) for v in (item.hold_start_s, item.hold_end_s)):
        return pending("hold_timing_missing_or_invalid")
    if item.hold_end_s - item.hold_start_s < 10:
        return pending("short_hold_policy_unresolved")
    indices = set()
    rows, input_ids, support_ids = [], [], []
    for row in s.frames:
        idx = row.get("frame_index")
        if type(idx) is not int or idx < 0:
            return pending("frame_identity_missing_or_invalid")
        if idx in indices:
            return pending("duplicate_frame_identity")
        indices.add(idx)
        t = row.get("time_s")
        if not _finite(t):
            return pending("frame_timing_missing_or_invalid")
        if row.get("phase") not in ("hold", "transition", "prep"):
            return pending("frame_phase_missing_or_invalid")
        if not (item.hold_end_s - 10 <= t < item.hold_end_s) or row["phase"] != "hold":
            continue
        input_ids.append(idx)
        # Unit reference area only tests per-frame observation validity; never
        # estimates participant calibration from evaluation measurements.
        probe = core.Calibration(s.subject, s.key, (0,) * 5, 1.0)
        f0, _ = core.frame_features(row, probe)
        if all(v is not None and math.isfinite(v) for v in f0):
            rows.append(row)
            support_ids.append(idx)
    n, j = len(input_ids), len(rows)
    coverage = j / n if n else None
    reasons = []
    if j < 30:
        reasons.append("common_valid_frames<30")
    if coverage is None or coverage < 0.5:
        reasons.append("common_coverage<0.5_or_undefined")
    return Window(replace(s, frames=tuple(rows)), tuple(input_ids),
                  tuple(support_ids), coverage, tuple(reasons), False)


def prepare_samples(items, reference_keys):
    """Prepare every sample, retaining missing and exclusion states.

    reference_keys must be fixed before evaluation, cover every participant and
    identify their first upright in S1. Session/order are supplied provenance,
    never inferred from filenames, steps, feature quality or predictions.
    Missing designations return unprocessed samples, never an inferred reference.
    """
    items = tuple(items)
    # Accept both spelling conventions, mapping back only for the core API.
    normalized = []
    for item in items:
        label = analysis_label(item.segment.label)
        core_label = "body_forward" if label == "lean_forward" else label
        frames = tuple(dict(r, label=core_label) if "label" in r and
                       analysis_label(r["label"]) == label else dict(r)
                       for r in item.segment.frames)
        normalized.append(replace(item, segment=replace(item.segment, label=core_label, frames=frames)))
    segments = tuple(i.segment for i in normalized)
    core._validate(segments)
    expected = {}
    for s in sorted(segments, key=lambda s: s.order):
        if s.label == "upright":
            expected.setdefault(s.subject, s.key)
    for subject, key in reference_keys.items():
        if subject not in expected or expected[subject] != key:
            raise ValueError("explicit references must be each participant's first P0")
    by_key = {i.segment.key: i for i in normalized}
    windows = {i.segment.key: _window(i) for i in normalized}
    calibrations = {}
    cal_reasons, cal_pending = {}, {}
    for subject in {s.subject for s in segments}:
        if subject not in reference_keys:
            calibrations[subject] = core.Calibration(subject, None, (None,) * 5, None)
            cal_reasons[subject] = ("designated_S1_P0_reference_missing",)
            cal_pending[subject] = True
    for subject, key in reference_keys.items():
        calibrations.update(core.fit_calibrations(
            [windows[s.key].segment for s in segments if s.subject == subject], {subject: key}))
        w, c = windows[key], calibrations[subject]
        reasons = list(w.reasons)
        if by_key[key].session != "S1":
            reasons.append("reference_must_be_S1")
        if c.area_px is None or not _finite(c.area_px) or c.area_px <= 0:
            reasons.append("reference_area_invalid")
        if len(c.baseline) != 5 or any(not _finite(v) for v in c.baseline):
            reasons.append("reference_baseline_invalid")
        cal_reasons[subject] = tuple(reasons)
        cal_pending[subject] = w.unprocessed or by_key[key].session not in ("S1", "S2")
    result = []
    for original, item in zip(items, normalized):
        s, w = item.segment, windows[item.segment.key]
        values = core.segment_features([w.segment], calibrations)[0]
        label = analysis_label(s.label)
        reasons = list(w.reasons)
        if cal_reasons[s.subject]:
            reasons.append("participant_calibration_failed")
        if any(v is None or not math.isfinite(v) for v in values.f0 + values.f_cal):
            reasons.append("aggregate_features_missing")
        if values.is_reference:
            reasons.append("calibration_reference_excluded_from_train_and_evaluation")
        pending = w.unprocessed or cal_pending[s.subject]
        eligible = not reasons
        result.append(Sample(s.key, s.subject, original.segment.label, label,
                             LAB6.index(label), item.session, values.reference_key,
                             values.f0, values.f_cal,
                             tuple(v is None for v in values.f0),
                             tuple(v is None for v in values.f_cal),
                             values.is_reference, eligible,
                             "unprocessed" if pending else "eligible" if eligible else "ineligible",
                             tuple(reasons), cal_reasons[s.subject],
                             w.input_indices, w.support_indices, w.coverage))
    return tuple(result)


@dataclass(frozen=True)
class ComparableSample:
    """A different feature family's existing aggregate, without recomputation."""
    sample_key: tuple
    subject: str
    label: str
    values: tuple
    eligible: bool
    reasons: tuple = ()


def evaluation_input(samples, *, other_families: Mapping | None = None,
                     participant_splits: Mapping | None = None):
    """Separate six-column evaluator input; never calls fit/predict/metrics.

    Produces aligned X/y/participant arrays plus all-sample audit/masks. Optional
    families are joined by exact key and checked for subject/label agreement.
    Only segment intersection is applied, never a cross-family frame mask.
    Split roles must be provided explicitly; no default role or participant fit.
    """
    samples = tuple(samples)
    by_key = {}
    for s in samples:
        if s.sample_key in by_key:
            raise ValueError("duplicate F0/F_cal sample key")
        by_key[s.sample_key] = s
    keys = tuple(sorted(by_key))
    rows = tuple(by_key[k] for k in keys)
    reasons = {k: list(by_key[k].reasons) for k in keys}
    matrices = {"F0": [s.f0 for s in rows], "F_cal": [s.f_cal for s in rows]}
    family_audit = {}
    for name, family in (other_families or {}).items():
        if name in matrices:
            raise ValueError("duplicate feature family name")
        lookup = {}
        width = None
        for row in family:
            if row.sample_key in lookup:
                raise ValueError("duplicate comparison sample key")
            lookup[row.sample_key] = row
            if width is None:
                width = len(row.values)
            if not width or len(row.values) != width:
                raise ValueError("inconsistent comparison feature width")
        if width is None:
            raise ValueError("comparison family width unavailable; supply existing aggregates")
        values = []
        audit = {}
        for k in keys:
            row = lookup.get(k)
            if row is None:
                audit[k] = ("sample_missing",)
                values.append((None,) * width)
            else:
                s = by_key[k]
                if (row.subject, analysis_label(row.label)) != (s.subject, s.label):
                    raise ValueError("comparison sample identity mismatch")
                valid = all(_finite(v) for v in row.values)
                audit[k] = tuple(row.reasons) + (() if row.eligible and valid else ("ineligible",))
                values.append(row.values)
            if audit[k]:
                reasons[k].append(name + ":" + ";".join(audit[k]))
        matrices[name] = values
        family_audit[name] = dict(reasons=audit, extra_keys=tuple(sorted(set(lookup) - set(keys))))
    mask = np.array([s.eligible and not reasons[s.sample_key] for s in rows], dtype=bool)
    arrays = {name: np.asarray(values, dtype=float).reshape(len(rows),
              6 if name in ("F0", "F_cal") else (len(values[0]) if values else 0))
              for name, values in matrices.items()}
    # None becomes NaN for array transport only; never zero-filled or model-fit.
    splits = participant_splits or {}
    roles = tuple(splits.get(s.subject) for s in rows)
    blockers = ["seed_metric_and_incomplete_class_policy_not_applied",
                "real_capture_loader_not_connected", "frame_loss_rate_policy_unresolved"]
    if any(role not in ("train", "heldout") for role in roles):
        blockers.append("participant_splits_missing_or_invalid")
    else:
        train = {s.subject for s, role in zip(rows, roles) if role == "train"}
        heldout = {s.subject for s, role in zip(rows, roles) if role == "heldout"}
        if len(train) != 2 or len(heldout) != 4:
            blockers.append("requires_two_development_and_four_heldout_participants")
    return dict(class_order=LAB6, feature_order={"F0": core.FEATURE_NAMES, "F_cal": core.FEATURE_NAMES},
                sample_keys=keys, participants=tuple(s.subject for s in rows),
                labels=tuple(s.label for s in rows), y=np.array([s.class_index for s in rows], dtype=int),
                matrices=arrays, missing_masks={name: np.isnan(a) for name, a in arrays.items()},
                reference_mask=np.array([s.is_reference for s in rows], dtype=bool),
                eligible_mask=np.array([s.eligible for s in rows], dtype=bool),
                common_mask=mask, common_sample_keys=tuple(k for k, keep in zip(keys, mask) if keep),
                common_matrices={name: a[mask] for name, a in arrays.items()},
                common_y=np.array([s.class_index for s in rows], dtype=int)[mask],
                common_participants=tuple(s.subject for s, keep in zip(rows, mask) if keep),
                train_mask=mask & np.array([r == "train" for r in roles], dtype=bool),
                heldout_mask=mask & np.array([r == "heldout" for r in roles], dtype=bool),
                exclusion_reasons={k: tuple(v) for k, v in reasons.items()},
                samples=rows, comparison_audit=family_audit, execution_blockers=tuple(blockers))
