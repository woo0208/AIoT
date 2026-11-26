"""F1-5 frame-level core calculation (FEAT-009 engineering prototype).

Implements only the researcher-approved core calculation recorded in
``docs/research/F1_FEATURE_CORE_CALCULATION_CONTRACT.md`` (``FEAT-009``):

    S    = (L + R) / 2
    H    = (Lh + Rh) / 2
    W    = R - L
    D_sh = norm(W)

    fs_x    = (F_x - S_x) / D_sh
    fs_y    = (F_y - S_y) / D_sh
    sh_x    = (S_x - H_x) / D_sh
    sh_y    = (S_y - H_y) / D_sh
    so_beta = wrap_pi(atan2(W_y, W_x))      # rad, period pi, [-pi/2, pi/2)

Inputs are the ``frames-schema/1.0.0`` field names of ONE canonical frame row:
original (non-mirrored) color-image pixel coordinates, +x image-right, +y
image-down, left/right relative to the subject.  Depth, MediaPipe relative z,
upright references and labels are not inputs.

Validity follows the existing Schema section F state fields only
(``face_detected``, ``lsh_valid`` / ``rsh_valid``, ``left_hip_valid`` /
``right_hip_valid``): an observation is used only when its state is explicit
``True`` and its x/y are finite.  ``D_sh > 0`` is a mathematical definition
condition, not a quality threshold.  No epsilon, visibility cutoff, frame
aggregation, sample eligibility, imputation or model-input policy is defined
here; unavailable features are ``None`` and must not be replaced by sentinels.
F1-6 (``sin 2beta``, ``cos 2beta``) remains a separate comparison candidate and
is not implemented.
"""

from dataclasses import dataclass
import math
import numbers
from types import MappingProxyType
from typing import Any, Mapping


F1_CORE_DECISION = "FEAT-009"
F1_5_FEATURE_NAMES = ("fs_x", "fs_y", "sh_x", "sh_y", "so_beta")
F1_5_FEATURE_UNITS = MappingProxyType({
    "fs_x": "dimensionless",
    "fs_y": "dimensionless",
    "sh_x": "dimensionless",
    "sh_y": "dimensionless",
    "so_beta": "rad",
})
F1_5_FEATURE_FAMILIES = MappingProxyType({
    "fs_x": "FS",
    "fs_y": "FS",
    "sh_x": "SH",
    "sh_y": "SH",
    "so_beta": "SO",
})
F1_FAMILIES = ("FS", "SH", "SO")

# observation -> (state field, x field, y field) in frames-schema/1.0.0
_OBSERVATIONS = {
    "face": ("face_detected", "face_x", "face_y"),
    "lsh": ("lsh_valid", "lsh_x", "lsh_y"),
    "rsh": ("rsh_valid", "rsh_x", "rsh_y"),
    "left_hip": ("left_hip_valid", "left_hip_x_px", "left_hip_y_px"),
    "right_hip": ("right_hip_valid", "right_hip_x_px", "right_hip_y_px"),
}
_FAMILY_OBSERVATIONS = {
    "FS": ("face", "lsh", "rsh"),
    "SH": ("lsh", "rsh", "left_hip", "right_hip"),
    "SO": ("lsh", "rsh"),
}


@dataclass(frozen=True)
class F1FrameResult:
    """F1-5 values of one frame; unavailable features are explicitly ``None``.

    ``family_reasons`` lists why a family is unavailable (empty when
    available).  It is a diagnostic, not a sample-eligibility decision.
    """

    features: Mapping[str, float | None]
    family_available: Mapping[str, bool]
    family_reasons: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        for name in ("features", "family_available", "family_reasons"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def ordered_values(self) -> tuple[float | None, ...]:
        """Return the values in the frozen F1-5 output order."""

        return tuple(self.features[name] for name in F1_5_FEATURE_NAMES)


def wrap_pi(theta: float) -> float:
    """Map a period-pi angle (rad) to ``[-pi/2, pi/2)``.

    Uses the contract definition ``theta - pi * floor((theta + pi/2) / pi)``;
    the final checks only undo floating-point rounding at the half-open
    boundary so the returned value always lies in the contract range.
    """

    theta = float(theta)
    if not math.isfinite(theta):
        raise ValueError(f"non-finite angle: {theta!r}")
    wrapped = theta - math.pi * math.floor((theta + math.pi / 2) / math.pi)
    if wrapped < -math.pi / 2:
        wrapped += math.pi
    elif wrapped >= math.pi / 2:
        wrapped -= math.pi
    return wrapped + 0.0  # normalise -0.0 to 0.0


def _canonical_bool(field: str, value: Any) -> bool | None:
    """Python or frames-schema CSV boolean -> True / False / None (unknown)."""

    if value is None or value is True or value is False:
        return value
    if isinstance(value, str):
        if value == "true":
            return True
        if value == "false":
            return False
        if value == "":
            return None
    raise ValueError(f"invalid canonical boolean {field}: {value!r}")


def _coordinate(field: str, value: Any) -> float | None:
    """Python number or frames-schema CSV numeric cell -> float / None."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"invalid canonical numeric {field}: {value!r}")
    if isinstance(value, numbers.Real):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    raise ValueError(f"invalid canonical numeric {field}: {value!r}")


def _observation(row: Mapping[str, Any], name: str) -> tuple[tuple[float, float] | None, str | None]:
    """Return ``(point, None)`` when usable, otherwise ``(None, reason)``."""

    state_field, x_field, y_field = _OBSERVATIONS[name]
    state = _canonical_bool(state_field, row.get(state_field))
    x = _coordinate(x_field, row.get(x_field))
    y = _coordinate(y_field, row.get(y_field))
    if state is None:
        return None, f"{state_field}:unknown"
    if state is False:
        return None, f"{state_field}:false"
    if x is None or y is None:
        return None, f"{name}_xy:missing"
    if not (math.isfinite(x) and math.isfinite(y)):
        return None, f"{name}_xy:nonfinite"
    return (x, y), None


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def compute_f1_5_frame(row: Mapping[str, Any]) -> F1FrameResult:
    """Compute F1-5 from one ``frames-schema/1.0.0`` frame row.

    Each family (FS, SH, SO) is evaluated independently from the same row.
    Malformed encodings (e.g. boolean ``"TRUE"`` / ``1`` or a non-numeric
    coordinate string) raise ``ValueError`` as in the canonical reader.
    """

    points: dict[str, tuple[float, float]] = {}
    issues: dict[str, str] = {}
    for name in _OBSERVATIONS:
        point, reason = _observation(row, name)
        if point is None:
            issues[name] = reason
        else:
            points[name] = point

    features: dict[str, float | None] = dict.fromkeys(F1_5_FEATURE_NAMES)
    reasons: dict[str, list[str]] = {
        family: [issues[obs] for obs in observations if obs in issues]
        for family, observations in _FAMILY_OBSERVATIONS.items()
    }

    if "lsh" in points and "rsh" in points:
        left, right = points["lsh"], points["rsh"]
        s = _midpoint(left, right)
        w = (right[0] - left[0], right[1] - left[1])
        d_sh = math.hypot(w[0], w[1])
        shoulder_issue = None
        if not all(math.isfinite(v) for v in (*s, *w, d_sh)):
            shoulder_issue = "shoulder_geometry:nonfinite"
        elif not d_sh > 0:
            shoulder_issue = "d_sh:zero"
        if shoulder_issue is not None:
            for family in F1_FAMILIES:
                reasons[family].append(shoulder_issue)
        else:
            candidates: dict[str, dict[str, float]] = {
                "SO": {"so_beta": wrap_pi(math.atan2(w[1], w[0]))},
            }
            if not reasons["FS"]:
                face = points["face"]
                candidates["FS"] = {
                    "fs_x": (face[0] - s[0]) / d_sh,
                    "fs_y": (face[1] - s[1]) / d_sh,
                }
            if not reasons["SH"]:
                h = _midpoint(points["left_hip"], points["right_hip"])
                candidates["SH"] = {
                    "sh_x": (s[0] - h[0]) / d_sh,
                    "sh_y": (s[1] - h[1]) / d_sh,
                }
            for family, values in candidates.items():
                if all(math.isfinite(v) for v in values.values()):
                    features.update(values)
                else:
                    reasons[family].append(f"{family.lower()}_result:nonfinite")

    return F1FrameResult(
        features=features,
        family_available={family: not reasons[family] for family in F1_FAMILIES},
        family_reasons={family: tuple(reasons[family]) for family in F1_FAMILIES},
    )
