"""Exploratory posture geometry derived from one MediaPipe Pose/Face frame.

This module is deliberately separate from the production capture gate and the
canonical ``frames-schema/1.0.0`` writer.  Its values are engineering candidates,
not frozen F1/F2 features or posture decisions.

The Pose indices used here are the named BlazePose landmarks already returned by
the repository's PoseLandmarker: nose 0, ears 7/8, shoulders 11/12, elbows
13/14, wrists 15/16, and hips 23/24.  The FaceLandmarker lower-chin point is
index 152: it is the bottom-centre vertex in MediaPipe's canonical face model,
the repository's ordered ``FACE_OVAL``, and MediaPipe's official face-oval
connections (377 -> 152 -> 148).  Metric depth is sampled from the aligned D455
depth image; MediaPipe's relative landmark ``z`` is not treated as sensor depth.

RealSense deprojection is deliberately performed by the hardware-facing caller.
This module accepts ordinary metric XYZ points and has no ``pyrealsense2``
dependency.  RealSense camera coordinates are assumed: +X image-right, +Y
image-down, and +Z away from the camera.  The exploratory sagittal torso angle
uses the hip-midpoint -> shoulder-midpoint axis, is zero when its YZ projection
is vertically upward, positive when the shoulders lean toward the camera, and
negative when they lean away from the camera.
"""

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np


POSE_LANDMARK_INDICES = {
    "nose": 0,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
}

FACE_LANDMARK_INDICES = {
    "chin": 152,
}

# Every direct landmark is eligible for the same aligned-depth + RealSense SDK
# deprojection path.  Keep the older name as an alias for callers that already
# use it; this is exploratory API compatibility, not a formal schema contract.
UPPER_BODY_3D_POINT_NAMES = tuple(POSE_LANDMARK_INDICES)
BODY_3D_POINT_NAMES = UPPER_BODY_3D_POINT_NAMES
EXPLORATORY_POINT_NAMES = (
    *UPPER_BODY_3D_POINT_NAMES,
    *FACE_LANDMARK_INDICES,
)


@dataclass(frozen=True)
class Point:
    """Image point plus optional aligned sensor depth in metres."""

    x_px: float
    y_px: float
    depth_m: float | None = None


@dataclass(frozen=True)
class Point3D:
    """Metric camera-coordinate point produced by the caller's deprojector."""

    x_m: float
    y_m: float
    z_m: float


@dataclass(frozen=True)
class GeometryResult:
    """One-frame exploratory result; absent quantities are explicitly ``None``."""

    points: Mapping[str, Point | None]
    proxies: Mapping[str, Point | None]
    features: Mapping[str, float | None]
    points_3d: Mapping[str, Point3D | None] = field(default_factory=dict)
    proxies_3d: Mapping[str, Point3D | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze owned mapping snapshots as well as the dataclass fields."""

        for name in ("points", "proxies", "features", "points_3d", "proxies_3d"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_debug_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly debug object, not a canonical research schema."""

        def point_dict(point: Point | None) -> dict[str, float | None] | None:
            if point is None:
                return None
            return {"x_px": point.x_px, "y_px": point.y_px, "depth_m": point.depth_m}

        def point_3d_dict(point: Point3D | None) -> dict[str, float] | None:
            if point is None:
                return None
            return {"x_m": point.x_m, "y_m": point.y_m, "z_m": point.z_m}

        return {
            "kind": "exploratory-posture-geometry",
            "points": {name: point_dict(point) for name, point in self.points.items()},
            "proxies": {name: point_dict(point) for name, point in self.proxies.items()},
            "points_3d": {name: point_3d_dict(point) for name, point in self.points_3d.items()},
            "proxies_3d": {name: point_3d_dict(point) for name, point in self.proxies_3d.items()},
            "features": dict(self.features),
        }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _valid_point(point: Point | None) -> Point | None:
    if point is None:
        return None
    x, y = _finite_number(point.x_px), _finite_number(point.y_px)
    if x is None or y is None:
        return None
    depth = _finite_number(point.depth_m)
    if depth is None or depth <= 0:
        depth = None
    return Point(x, y, depth)


def _valid_point_3d(point: Point3D | None) -> Point3D | None:
    if point is None:
        return None
    x = _finite_number(point.x_m)
    y = _finite_number(point.y_m)
    z = _finite_number(point.z_m)
    if x is None or y is None or z is None or z <= 0:
        return None
    return Point3D(x, y, z)


def _midpoint(a: Point | None, b: Point | None) -> Point | None:
    a, b = _valid_point(a), _valid_point(b)
    if a is None or b is None:
        return None
    depth = (a.depth_m + b.depth_m) / 2 if a.depth_m is not None and b.depth_m is not None else None
    return Point((a.x_px + b.x_px) / 2, (a.y_px + b.y_px) / 2, depth)


def _midpoint_3d(a: Point3D | None, b: Point3D | None) -> Point3D | None:
    a, b = _valid_point_3d(a), _valid_point_3d(b)
    if a is None or b is None:
        return None
    return Point3D(
        (a.x_m + b.x_m) / 2,
        (a.y_m + b.y_m) / 2,
        (a.z_m + b.z_m) / 2,
    )


def _distance_2d(a: Point | None, b: Point | None) -> float | None:
    a, b = _valid_point(a), _valid_point(b)
    return math.hypot(b.x_px - a.x_px, b.y_px - a.y_px) if a is not None and b is not None else None


def _distance_3d(a: Point3D | None, b: Point3D | None) -> float | None:
    a, b = _valid_point_3d(a), _valid_point_3d(b)
    if a is None or b is None:
        return None
    distance = math.sqrt(
        (b.x_m - a.x_m) ** 2
        + (b.y_m - a.y_m) ** 2
        + (b.z_m - a.z_m) ** 2
    )
    return distance if math.isfinite(distance) and distance > 1e-6 else None


def _undirected_line_angle_deg(a: Point | None, b: Point | None) -> float | None:
    """Signed image-plane line angle in [-90, 90), independent of 180-degree reversal."""

    a, b = _valid_point(a), _valid_point(b)
    if a is None or b is None:
        return None
    dx, dy = b.x_px - a.x_px, b.y_px - a.y_px
    if dx == 0 and dy == 0:
        return None
    angle = math.degrees(math.atan2(dy, dx))
    while angle >= 90:
        angle -= 180
    while angle < -90:
        angle += 180
    return angle


def _relative(source: Point | None, target: Point | None, scale: float | None) -> tuple[float | None, float | None]:
    source, target = _valid_point(source), _valid_point(target)
    if source is None or target is None or scale is None or not math.isfinite(scale) or scale <= 1e-6:
        return None, None
    return ((source.x_px - target.x_px) / scale, (source.y_px - target.y_px) / scale)


def _forward_offset(torso_depth_m: float | None, point: Point | None) -> float | None:
    point = _valid_point(point)
    if torso_depth_m is None or point is None or point.depth_m is None:
        return None
    # D455 depth increases away from the camera, so positive means the point is
    # closer to the camera than the shoulder-based torso proxy.
    return torso_depth_m - point.depth_m


def _sagittal_torso_lean_deg(
    hip_midpoint: Point3D | None, shoulder_midpoint: Point3D | None
) -> float | None:
    """Return signed torso lean in the camera YZ plane.

    The directed axis is hip midpoint -> shoulder midpoint.  Because RealSense
    +Y points down and +Z points away from the camera, its upward component is
    ``hip_y - shoulder_y`` and its camera-forward component is
    ``hip_z - shoulder_z``.  ``atan2(camera_forward, upward)`` therefore yields
    positive angles for shoulders closer to the camera than the hips.
    """

    hip_midpoint = _valid_point_3d(hip_midpoint)
    shoulder_midpoint = _valid_point_3d(shoulder_midpoint)
    if hip_midpoint is None or shoulder_midpoint is None:
        return None
    upward_m = hip_midpoint.y_m - shoulder_midpoint.y_m
    camera_forward_m = hip_midpoint.z_m - shoulder_midpoint.z_m
    if math.hypot(upward_m, camera_forward_m) <= 1e-6:
        return None
    return math.degrees(math.atan2(camera_forward_m, upward_m))


def _exploratory_head_pitch_deg(
    ear_midpoint: Point3D | None,
    nose: Point3D | None,
    chin: Point3D | None,
) -> float | None:
    """Return sparse, translation-invariant head pitch in the camera YZ plane.

    The ear midpoint is the origin for two rays, ``ear -> nose`` and
    ``ear -> chin``.  Each ray is projected onto the RealSense YZ plane and
    normalized; their normalized sum is the sparse face-forward bisector.
    The returned angle is ``atan2(vertical-up, camera-forward)`` where
    ``vertical-up = -Y`` and ``camera-forward = -Z``.  Positive means the
    face-forward bisector is rotated toward vertical-up, corresponding to chin
    up / head backward; negative corresponds to chin down / head forward.
    Common XYZ translation cancels before projection, so head-forward
    translation alone does not create pitch.

    This is an exploratory camera-relative orientation, not an anatomical
    cervical angle and not a frozen research feature.
    """

    ear_midpoint = _valid_point_3d(ear_midpoint)
    nose = _valid_point_3d(nose)
    chin = _valid_point_3d(chin)
    if ear_midpoint is None or nose is None or chin is None:
        return None

    def yz_unit(target: Point3D) -> tuple[float, float] | None:
        down = target.y_m - ear_midpoint.y_m
        away = target.z_m - ear_midpoint.z_m
        length = math.hypot(down, away)
        if not math.isfinite(length) or length <= 1e-6:
            return None
        return down / length, away / length

    nose_ray = yz_unit(nose)
    chin_ray = yz_unit(chin)
    if nose_ray is None or chin_ray is None:
        return None
    bisector_down = nose_ray[0] + chin_ray[0]
    bisector_away = nose_ray[1] + chin_ray[1]
    if math.hypot(bisector_down, bisector_away) <= 1e-6:
        return None
    return math.degrees(math.atan2(-bisector_down, -bisector_away))


def compute_candidate_geometry(
    points: Mapping[str, Point | None], *,
    focal_length_px: float | None = None,
    points_3d: Mapping[str, Point3D | None] | None = None,
) -> GeometryResult:
    """Compute threshold-free, one-frame candidate geometry.

    ``focal_length_px`` enables an approximate metric shoulder-width scale:
    ``shoulder_width_px * torso_depth_m / focal_length_px``.  It is a debug
    normalization candidate, not a substitute for SDK deprojection or D455
    engineering validation.  ``points_3d`` must contain caller-deprojected
    metric RealSense camera coordinates; this pure module never invokes the SDK.
    """

    clean = {name: _valid_point(points.get(name)) for name in EXPLORATORY_POINT_NAMES}
    nose = clean["nose"]
    left_ear, right_ear = clean["left_ear"], clean["right_ear"]
    left_shoulder, right_shoulder = clean["left_shoulder"], clean["right_shoulder"]
    left_hip, right_hip = clean["left_hip"], clean["right_hip"]

    shoulder_midpoint = _midpoint(left_shoulder, right_shoulder)
    hip_midpoint = _midpoint(left_hip, right_hip)
    ear_midpoint = _midpoint(left_ear, right_ear)

    # These names intentionally say "exploratory" and "proxy": neither is a
    # directly observed anatomical neck or clavicle/chest landmark.
    exploratory_upper_chest_proxy = shoulder_midpoint
    exploratory_neck_proxy = _midpoint(ear_midpoint, shoulder_midpoint)
    proxies = {
        "shoulder_midpoint": shoulder_midpoint,
        "hip_midpoint": hip_midpoint,
        "ear_midpoint": ear_midpoint,
        "exploratory_neck_proxy": exploratory_neck_proxy,
        "exploratory_upper_chest_proxy": exploratory_upper_chest_proxy,
    }

    provided_3d = points_3d or {}
    clean_3d = {
        name: _valid_point_3d(provided_3d.get(name))
        for name in EXPLORATORY_POINT_NAMES
    }
    shoulder_midpoint_3d = _midpoint_3d(
        clean_3d["left_shoulder"], clean_3d["right_shoulder"]
    )
    hip_midpoint_3d = _midpoint_3d(clean_3d["left_hip"], clean_3d["right_hip"])
    ear_midpoint_3d = _midpoint_3d(clean_3d["left_ear"], clean_3d["right_ear"])
    proxies_3d = {
        "shoulder_midpoint_3d": shoulder_midpoint_3d,
        "hip_midpoint_3d": hip_midpoint_3d,
        "ear_midpoint_3d": ear_midpoint_3d,
    }

    shoulder_width_px = _distance_2d(left_shoulder, right_shoulder)
    usable_scale_px = shoulder_width_px if shoulder_width_px is not None and shoulder_width_px > 1e-6 else None
    nose_dx, nose_dy = _relative(nose, shoulder_midpoint, usable_scale_px)
    left_ear_dx, left_ear_dy = _relative(left_ear, left_shoulder, usable_scale_px)
    right_ear_dx, right_ear_dy = _relative(right_ear, right_shoulder, usable_scale_px)

    head_to_torso_angle = None
    if nose is not None and shoulder_midpoint is not None:
        dx = nose.x_px - shoulder_midpoint.x_px
        up = shoulder_midpoint.y_px - nose.y_px
        if abs(dx) > 1e-6 or abs(up) > 1e-6:
            head_to_torso_angle = math.degrees(math.atan2(dx, up))

    torso_depth = shoulder_midpoint.depth_m if shoulder_midpoint is not None else None
    nose_forward = _forward_offset(torso_depth, nose)
    left_ear_forward = _forward_offset(torso_depth, left_ear)
    right_ear_forward = _forward_offset(torso_depth, right_ear)
    ear_mid_forward = _forward_offset(torso_depth, ear_midpoint)

    focal = _finite_number(focal_length_px)
    body_scale_m = None
    if usable_scale_px is not None and torso_depth is not None and focal is not None and focal > 1e-6:
        body_scale_m = usable_scale_px * torso_depth / focal
        if not math.isfinite(body_scale_m) or body_scale_m <= 1e-6:
            body_scale_m = None

    shoulder_width_3d_m = _distance_3d(
        clean_3d["left_shoulder"], clean_3d["right_shoulder"]
    )

    head_tilt = _undirected_line_angle_deg(left_ear, right_ear)
    shoulder_tilt = _undirected_line_angle_deg(left_shoulder, right_shoulder)
    relative_head_tilt = (
        head_tilt - shoulder_tilt
        if head_tilt is not None and shoulder_tilt is not None
        else None
    )

    def normalized_depth(offset: float | None) -> float | None:
        return offset / body_scale_m if offset is not None and body_scale_m is not None else None

    def normalized_depth_3d(offset: float | None) -> float | None:
        return (
            offset / shoulder_width_3d_m
            if offset is not None and shoulder_width_3d_m is not None
            else None
        )

    features = {
        "head_lateral_tilt_deg": head_tilt,
        "shoulder_tilt_deg": shoulder_tilt,
        "relative_head_tilt_deg": relative_head_tilt,
        "shoulder_width_px": shoulder_width_px,
        "nose_to_shoulder_mid_dx_shoulder_width": nose_dx,
        "nose_to_shoulder_mid_dy_shoulder_width": nose_dy,
        "left_ear_to_left_shoulder_dx_shoulder_width": left_ear_dx,
        "left_ear_to_left_shoulder_dy_shoulder_width": left_ear_dy,
        "right_ear_to_right_shoulder_dx_shoulder_width": right_ear_dx,
        "right_ear_to_right_shoulder_dy_shoulder_width": right_ear_dy,
        "head_to_torso_lateral_angle_deg": head_to_torso_angle,
        "torso_depth_proxy_m": torso_depth,
        "nose_forward_from_torso_m": nose_forward,
        "left_ear_forward_from_torso_m": left_ear_forward,
        "right_ear_forward_from_torso_m": right_ear_forward,
        "ear_midpoint_forward_from_torso_m": ear_mid_forward,
        "shoulder_width_metric_proxy_m": body_scale_m,
        "nose_forward_normalized_by_shoulder_width": normalized_depth(nose_forward),
        "ear_midpoint_forward_normalized_by_shoulder_width": normalized_depth(ear_mid_forward),
        "shoulder_width_3d_m": shoulder_width_3d_m,
        "sagittal_torso_lean_deg": _sagittal_torso_lean_deg(
            hip_midpoint_3d, shoulder_midpoint_3d
        ),
        "exploratory_head_pitch_deg": _exploratory_head_pitch_deg(
            ear_midpoint_3d,
            clean_3d["nose"],
            clean_3d["chin"],
        ),
        "nose_forward_normalized_by_shoulder_width_3d": normalized_depth_3d(nose_forward),
        "ear_midpoint_forward_normalized_by_shoulder_width_3d": normalized_depth_3d(
            ear_mid_forward
        ),
    }
    return GeometryResult(
        points=clean,
        proxies=proxies,
        features=features,
        points_3d=clean_3d,
        proxies_3d=proxies_3d,
    )


def sample_aligned_depth_m(
    depth_image: np.ndarray | None,
    x_px: float,
    y_px: float,
    depth_scale_m: float | None,
    *,
    half_width_px: int = 6,
    minimum_valid_pixels: int = 10,
) -> float | None:
    """Median positive depth around an in-frame color-aligned pixel."""

    scale = _finite_number(depth_scale_m)
    if depth_image is None or getattr(depth_image, "ndim", None) != 2 or scale is None or scale <= 0:
        return None
    x, y = _finite_number(x_px), _finite_number(y_px)
    if x is None or y is None:
        return None
    height, width = depth_image.shape
    x0, x1 = max(0, int(x) - half_width_px), min(width, int(x) + half_width_px)
    y0, y1 = max(0, int(y) - half_width_px), min(height, int(y) + half_width_px)
    if x1 <= x0 or y1 <= y0:
        return None
    values = np.asarray(depth_image[y0:y1, x0:x1])
    valid = values[np.isfinite(values) & (values > 0)]
    if valid.size < minimum_valid_pixels:
        return None
    depth_m = float(np.median(valid)) * scale
    return depth_m if math.isfinite(depth_m) and depth_m > 0 else None


def points_from_pose_landmarks(
    pose_landmarks: Any,
    image_width: int,
    image_height: int,
    *,
    aligned_depth: np.ndarray | None = None,
    depth_scale_m: float | None = None,
) -> dict[str, Point | None]:
    """Extract verified Pose upper-body points from one result list."""

    output: dict[str, Point | None] = {name: None for name in POSE_LANDMARK_INDICES}
    if pose_landmarks is None or image_width <= 0 or image_height <= 0:
        return output
    for name, index in POSE_LANDMARK_INDICES.items():
        try:
            landmark = pose_landmarks[index]
            x_norm, y_norm = _finite_number(landmark.x), _finite_number(landmark.y)
        except (IndexError, KeyError, TypeError, AttributeError):
            continue
        if x_norm is None or y_norm is None or not (0 <= x_norm < 1 and 0 <= y_norm < 1):
            continue
        x_px, y_px = x_norm * image_width, y_norm * image_height
        depth_m = sample_aligned_depth_m(aligned_depth, x_px, y_px, depth_scale_m)
        output[name] = Point(x_px, y_px, depth_m)
    return output


def points_from_face_landmarks(
    face_landmarks: Any,
    image_width: int,
    image_height: int,
    *,
    aligned_depth: np.ndarray | None = None,
    depth_scale_m: float | None = None,
) -> dict[str, Point | None]:
    """Extract the verified FaceLandmarker lower-chin point from one RGB frame."""

    output: dict[str, Point | None] = {name: None for name in FACE_LANDMARK_INDICES}
    if face_landmarks is None or image_width <= 0 or image_height <= 0:
        return output
    for name, index in FACE_LANDMARK_INDICES.items():
        try:
            landmark = face_landmarks[index]
            x_norm, y_norm = _finite_number(landmark.x), _finite_number(landmark.y)
        except (IndexError, KeyError, TypeError, AttributeError):
            continue
        if x_norm is None or y_norm is None or not (0 <= x_norm < 1 and 0 <= y_norm < 1):
            continue
        x_px, y_px = x_norm * image_width, y_norm * image_height
        depth_m = sample_aligned_depth_m(aligned_depth, x_px, y_px, depth_scale_m)
        output[name] = Point(x_px, y_px, depth_m)
    return output


def draw_geometry_overlay(image: np.ndarray, result: GeometryResult) -> np.ndarray:
    """Draw direct points, exploratory proxies, reference lines, and values on BGR image."""

    import cv2

    canvas = image.copy()
    direct_colors = {
        "nose": (0, 255, 255),
        "left_ear": (255, 160, 0),
        "right_ear": (255, 160, 0),
        "left_shoulder": (0, 220, 0),
        "right_shoulder": (0, 220, 0),
        "left_elbow": (0, 180, 255),
        "right_elbow": (0, 180, 255),
        "left_wrist": (0, 120, 255),
        "right_wrist": (0, 120, 255),
        "left_hip": (255, 100, 255),
        "right_hip": (255, 100, 255),
        "chin": (60, 220, 255),
    }

    def pixel(point: Point | None) -> tuple[int, int] | None:
        point = _valid_point(point)
        return (int(round(point.x_px)), int(round(point.y_px))) if point is not None else None

    def line(a: Point | None, b: Point | None, color: tuple[int, int, int], thickness: int = 2) -> None:
        pa, pb = pixel(a), pixel(b)
        if pa is not None and pb is not None:
            cv2.line(canvas, pa, pb, color, thickness, cv2.LINE_AA)

    line(result.points.get("left_ear"), result.points.get("right_ear"), (255, 160, 0))
    line(result.points.get("left_shoulder"), result.points.get("right_shoulder"), (0, 220, 0))
    line(result.points.get("left_shoulder"), result.points.get("left_elbow"), (0, 180, 255))
    line(result.points.get("left_elbow"), result.points.get("left_wrist"), (0, 120, 255))
    line(result.points.get("right_shoulder"), result.points.get("right_elbow"), (0, 180, 255))
    line(result.points.get("right_elbow"), result.points.get("right_wrist"), (0, 120, 255))
    line(result.points.get("left_hip"), result.points.get("right_hip"), (255, 100, 255))
    line(result.proxies.get("hip_midpoint"), result.proxies.get("shoulder_midpoint"), (0, 140, 255), 3)
    line(result.points.get("nose"), result.proxies.get("shoulder_midpoint"), (0, 255, 255))
    line(result.points.get("nose"), result.points.get("chin"), (60, 220, 255))
    line(result.points.get("left_ear"), result.points.get("left_shoulder"), (180, 100, 255), 1)
    line(result.points.get("right_ear"), result.points.get("right_shoulder"), (180, 100, 255), 1)
    line(result.proxies.get("exploratory_neck_proxy"),
         result.proxies.get("exploratory_upper_chest_proxy"), (255, 0, 255), 1)

    for name, point in result.points.items():
        p = pixel(point)
        if p is not None:
            cv2.circle(canvas, p, 5, direct_colors[name], -1, cv2.LINE_AA)
            cv2.putText(canvas, name.replace("_", " "), (p[0] + 7, p[1] - 7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, direct_colors[name], 1, cv2.LINE_AA)

    for name, color in (("exploratory_neck_proxy", (255, 0, 255)),
                        ("exploratory_upper_chest_proxy", (0, 140, 255)),
                        ("shoulder_midpoint", (0, 220, 0)),
                        ("hip_midpoint", (255, 100, 255))):
        p = pixel(result.proxies.get(name))
        if p is not None:
            cv2.drawMarker(canvas, p, color, cv2.MARKER_DIAMOND, 14, 2, cv2.LINE_AA)
            cv2.putText(canvas, name.replace("exploratory_", "").replace("_", " "),
                        (p[0] + 7, p[1] + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

    labels = (
        ("head tilt", "head_lateral_tilt_deg", "deg"),
        ("shoulder tilt", "shoulder_tilt_deg", "deg"),
        ("relative head tilt", "relative_head_tilt_deg", "deg"),
        ("nose dx / shoulder", "nose_to_shoulder_mid_dx_shoulder_width", ""),
        ("nose dy / shoulder", "nose_to_shoulder_mid_dy_shoulder_width", ""),
        ("nose forward", "nose_forward_from_torso_m", "m"),
        ("nose forward / shoulder", "nose_forward_normalized_by_shoulder_width", ""),
        ("torso lean (+camera)", "sagittal_torso_lean_deg", "deg"),
        ("3D shoulder width", "shoulder_width_3d_m", "m"),
        ("exploratory head pitch", "exploratory_head_pitch_deg", "deg"),
    )
    y = 22
    for label, key, unit in labels:
        value = result.features.get(key)
        if value is None:
            continue
        text = f"{label}: {value:+.3f}{unit}"
        cv2.putText(canvas, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (245, 245, 245), 2, cv2.LINE_AA)
        cv2.putText(canvas, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1, cv2.LINE_AA)
        y += 20
    return canvas


def overlay_pose_frame(
    bgr_image: np.ndarray,
    pose_landmarks: Any,
    *,
    aligned_depth: np.ndarray | None = None,
    depth_scale_m: float | None = None,
    focal_length_px: float | None = None,
    points_3d: Mapping[str, Point3D | None] | None = None,
    face_landmarks: Any = None,
) -> tuple[np.ndarray, GeometryResult]:
    """Drop-in exploratory overlay for an existing aligned BGR/depth frame.

    This helper performs no display, file write, canonical-row mutation, or
    posture classification.  A debug caller can pass the same frame and Pose
    result already present in ``analyze_d455.py`` and decide how to show/save it.
    """

    if getattr(bgr_image, "ndim", None) != 3 or bgr_image.shape[2] != 3:
        raise ValueError("bgr_image must have shape (height, width, 3)")
    height, width = bgr_image.shape[:2]
    points = points_from_pose_landmarks(
        pose_landmarks,
        width,
        height,
        aligned_depth=aligned_depth,
        depth_scale_m=depth_scale_m,
    )
    points.update(points_from_face_landmarks(
        face_landmarks,
        width,
        height,
        aligned_depth=aligned_depth,
        depth_scale_m=depth_scale_m,
    ))
    result = compute_candidate_geometry(
        points,
        focal_length_px=focal_length_px,
        points_3d=points_3d,
    )
    return draw_geometry_overlay(bgr_image, result), result
