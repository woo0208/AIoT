"""Standalone F0/F_cal engineering implementation; no evaluation or file I/O.

See F0_FCAL_IMPLEMENTATION.md for explicit paper ambiguities and conventions.
Inputs reuse analyze_d455's bbox/shoulder columns, never its approximate angles
or oval area. Segment aggregation reuses its median primitive. This module does
not change any frozen schema, feature set, model, or evaluation runner.
"""

from dataclasses import dataclass
import math
from typing import Mapping

from analyze_d455 import med


FEATURE_NAMES = ("xc", "yc", "theta1_deg", "theta2_deg", "theta3_deg", "A")
LABELS = ("upright", "forward_head", "body_forward", "lean_back", "lean_left", "lean_right")
INPUT_NAMES = ("face_x", "face_y", "lsh_x", "lsh_y", "rsh_x", "rsh_y", "face_area_px")


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _angle(xc, yc, x, y):
    if None in (xc, yc, x, y) or yc == y:
        return None
    return math.degrees(math.atan((xc - x) / (yc - y)))


def _observations(row):
    values = {k: _number(row.get(k)) for k in INPUT_NAMES}
    for flag, fields in (("face_detected", ("face_x", "face_y", "face_area_px")),
                         ("lsh_valid", ("lsh_x", "lsh_y")),
                         ("rsh_valid", ("rsh_x", "rsh_y"))):
        if row.get(flag) is False or row.get(flag) == "false":
            for k in fields:
                values[k] = None
    if values["face_area_px"] is not None and values["face_area_px"] <= 0:
        values["face_area_px"] = None
    return values


def _basic(row):
    values = _observations(row)
    xc, yc, lx, ly, rx, ry, area = (values[k] for k in INPUT_NAMES)
    if area is None or area <= 0:
        area = None
    t2, t3 = _angle(xc, yc, lx, ly), _angle(xc, yc, rx, ry)
    t1 = t2 + t3 if t2 is not None and t3 is not None else None
    return (xc, yc, t1, t2, t3), area


@dataclass(frozen=True)
class Segment:
    """One preselected recording/run/step; order is planned acquisition order.

    All coordinates are same-resolution pixels, +y downward, shoulders are
    participant-anatomical left/right. Frames must already be the intended
    stable interval; this module neither trims nor invents acceptance gates.
    """

    subject: str
    recording_id: str
    analysis_run_id: str
    step: int
    order: int
    label: str
    frames: tuple[Mapping, ...]

    @property
    def key(self):
        return (self.analysis_run_id, self.recording_id, self.step)


@dataclass(frozen=True)
class Calibration:
    subject: str
    reference_key: tuple
    baseline: tuple
    area_px: float | None


@dataclass(frozen=True)
class Features:
    subject: str
    sample_key: tuple
    label: str
    reference_key: tuple
    f0: tuple
    f_cal: tuple
    is_reference: bool
    excluded_from_evaluation: bool

    def missing(self, mode="F0"):
        if mode not in ("F0", "F_cal"):
            raise ValueError("mode must be F0 or F_cal")
        values = self.f0 if mode == "F0" else self.f_cal
        return tuple(k for k, v in zip(FEATURE_NAMES, values) if v is None)


def _validate(segments):
    keys, orders = set(), set()
    for s in segments:
        if not isinstance(s, Segment):
            raise ValueError("expected Segment")
        if any(not isinstance(v, str) or not v for v in
               (s.subject, s.recording_id, s.analysis_run_id)):
            raise ValueError("segment identity must be nonempty")
        if any(type(v) is not int or v < 0 for v in (s.step, s.order)):
            raise ValueError("step/order must be nonnegative integers")
        if s.label not in LABELS:
            raise ValueError("unknown six-class label")
        if s.key in keys or (s.subject, s.order) in orders:
            raise ValueError("duplicate sample key or participant acquisition order")
        keys.add(s.key)
        orders.add((s.subject, s.order))
        for row in s.frames:
            if not isinstance(row, Mapping):
                raise ValueError("frame must be a mapping")
            for k in ("subject", "recording_id", "analysis_run_id", "step", "label"):
                if k in row and str(row[k]) != str(getattr(s, k)):
                    raise ValueError(f"frame/segment identity mismatch: {k}")


def _aggregate(segment):
    # Same component-wise primitive median as legacy load_ours/summarize.
    # Reject non-finite observations before using the existing median helper.
    row = {}
    observations = [_observations(r) for r in segment.frames]
    for k in INPUT_NAMES:
        row[k] = med([r[k] for r in observations])
    return _basic(row)


def first_upright_references(segments):
    """Build a metadata-only designation to review/fix BEFORE feature evaluation.

    The supplied order must come from the acquisition plan, not prediction,
    quality, or feature values. Never chooses the first *valid* upright.
    """
    segments = tuple(segments)
    _validate(segments)
    refs = {}
    for s in sorted(segments, key=lambda s: s.order):
        if s.label == "upright":
            refs.setdefault(s.subject, s.key)
    if set(refs) != {s.subject for s in segments}:
        raise ValueError("participant has no designated upright reference")
    return refs


def fit_calibrations(segments, reference_keys):
    """Read measurements ONLY from explicitly designated first upright segments.

    No learning, label inference, replacement reference, or later-round update.
    Missing baseline components stay None, including for a held-out subject.
    """
    segments = tuple(segments)
    expected = first_upright_references(segments)
    if dict(reference_keys) != expected:
        raise ValueError("references must designate each participant's first upright")
    by_key = {s.key: s for s in segments}
    result = {}
    for subject, key in reference_keys.items():
        baseline, area = _aggregate(by_key[key])
        result[subject] = Calibration(subject, key, baseline, area)
    return result


def frame_features(row, calibration):
    """Return (F0, F_cal) in FEATURE_NAMES order; undefined values are None.

    A is bbox area / reference bbox area for BOTH modes, never A - 1.
    Callers using frames directly must supply the matching subject calibration.
    """
    if "subject" in row and row["subject"] != calibration.subject:
        raise ValueError("frame/calibration participant mismatch")
    basic, area = _basic(row)
    return _relative(basic, area, calibration)


def _relative(basic, area, calibration):
    try:
        baseline_length = len(calibration.baseline)
    except TypeError:
        raise ValueError("calibration baseline must contain exactly 5 values") from None
    if baseline_length != 5:
        raise ValueError("calibration baseline must contain exactly 5 values")
    ref_area = _number(calibration.area_px)
    ratio = area / ref_area if area is not None and ref_area is not None and ref_area > 0 else None
    ratio = _number(ratio)
    relative = tuple(_number(v - b) if v is not None and b is not None else None
                     for v, b in zip(basic, calibration.baseline))
    return basic + (ratio,), relative + (ratio,)


def segment_features(segments, calibrations, *, exclude_references=True):
    """Preserve every sample and its missing/exclusion state; never silently drop.

    Reference exclusions apply identically to F0 and F_cal. A later runner must
    honor excluded_from_evaluation and choose/report a missing-data policy.
    """
    segments = tuple(segments)
    _validate(segments)
    results = []
    for s in segments:
        c = calibrations.get(s.subject)
        if c is None or c.subject != s.subject:
            raise ValueError("missing or mismatched participant calibration")
        basic, area = _aggregate(s)
        f0, fcal = _relative(basic, area, c)
        is_ref = s.key == c.reference_key
        results.append(Features(s.subject, s.key, s.label, c.reference_key,
                                f0, fcal, is_ref, bool(exclude_references and is_ref)))
    return tuple(results)
