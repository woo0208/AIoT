"""Read-only visualizations for exploratory upper-body 3D geometry.

This module consumes :class:`posture_geometry.GeometryResult` values that were
already computed by the MediaPipe/aligned-depth/RealSense adapter.  It does not
sample depth, deproject pixels, calculate posture features, classify posture, or
write canonical artifacts.

RealSense camera coordinates are used throughout: +X image-right, +Y image-down,
and +Z away from the camera.  The sagittal view displays camera-forward as -Z
and vertical-up as -Y.  It is a depth-derived projection, not a reconstructed
side-camera image.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Mapping, Sequence

import numpy as np

import posture_geometry as geometry


WINDOW_NAME = "Exploratory upper-body 3D views"
DEFAULT_PANEL_SIZE = (560, 640)
DEFAULT_SIDE_VIEW_SIZE = (900, 760)
SIDE_CAMERA_LABEL = "<- toward camera"

JOINT_NAMES = geometry.UPPER_BODY_3D_POINT_NAMES

# A stable joint graph that a later primitive avatar or parametric-mesh adapter
# can consume without changing D455 acquisition or candidate feature logic.
SKELETON_SEGMENTS = (
    ("nose", "left_ear"),
    ("nose", "right_ear"),
    ("left_ear", "left_shoulder"),
    ("right_ear", "right_shoulder"),
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
)

SAGITTAL_POINT_SOURCES = {
    "nose": ("points_3d", "nose"),
    "ear_midpoint": ("proxies_3d", "ear_midpoint_3d"),
    "shoulder_midpoint": ("proxies_3d", "shoulder_midpoint_3d"),
    "hip_midpoint": ("proxies_3d", "hip_midpoint_3d"),
}

SAGITTAL_SEGMENTS = (
    ("nose", "ear_midpoint"),
    ("ear_midpoint", "shoulder_midpoint"),
    ("shoulder_midpoint", "hip_midpoint"),
)


@dataclass(frozen=True)
class SagittalPoint:
    """Metric side-view coordinate: camera-forward (-Z), vertical-up (-Y)."""

    camera_forward_m: float
    vertical_up_m: float


@dataclass(frozen=True)
class SkeletonSegment:
    """One available named 3D segment, suitable for later model adapters."""

    start_name: str
    end_name: str
    start: geometry.Point3D
    end: geometry.Point3D


Vector3D = tuple[float, float, float]


@dataclass(frozen=True)
class AvatarCapsule:
    """Joint-to-joint display capsule; dimensions remain metric."""

    name: str
    start_name: str
    end_name: str
    start: geometry.Point3D
    end: geometry.Point3D
    radius_m: float


@dataclass(frozen=True)
class AvatarEllipsoid:
    """Measured-geometry head approximation, not an anatomical reconstruction."""

    name: str
    center: geometry.Point3D
    lateral_axis: Vector3D
    vertical_axis: Vector3D
    forward_axis: Vector3D
    radii_m: tuple[float, float, float]


@dataclass(frozen=True)
class AvatarTorso:
    """Tapered shoulder-to-hip display volume in a measured 3D frame."""

    shoulder_midpoint: geometry.Point3D
    hip_midpoint: geometry.Point3D
    longitudinal_axis: Vector3D
    lateral_axis: Vector3D
    depth_axis: Vector3D
    shoulder_width_m: float
    hip_width_m: float
    half_depth_m: float
    vertices: tuple[geometry.Point3D, ...]


@dataclass(frozen=True)
class AvatarSphere:
    """Small joint marker centered on one direct measured joint."""

    joint_name: str
    center: geometry.Point3D
    radius_m: float


@dataclass(frozen=True)
class AvatarPrimitives:
    """Immutable visualization primitives derived from one GeometryResult."""

    head: AvatarEllipsoid | None
    neck: AvatarCapsule | None
    torso: AvatarTorso | None
    pelvis: AvatarCapsule | None
    arm_segments: tuple[AvatarCapsule, ...]
    joints: tuple[AvatarSphere, ...]


def _vector(a: geometry.Point3D, b: geometry.Point3D) -> Vector3D:
    """Return the directed vector a -> b."""

    return (
        float(b.x_m) - float(a.x_m),
        float(b.y_m) - float(a.y_m),
        float(b.z_m) - float(a.z_m),
    )


def _dot(a: Vector3D, b: Vector3D) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a: Vector3D, b: Vector3D) -> Vector3D:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit(vector: Vector3D) -> Vector3D | None:
    length = math.sqrt(_dot(vector, vector))
    if not math.isfinite(length) or length <= 1e-9:
        return None
    return tuple(value / length for value in vector)  # type: ignore[return-value]


def _distance(a: geometry.Point3D, b: geometry.Point3D) -> float | None:
    vector = _vector(a, b)
    length = math.sqrt(_dot(vector, vector))
    return length if math.isfinite(length) and length > 1e-9 else None


def _midpoint(a: geometry.Point3D, b: geometry.Point3D) -> geometry.Point3D:
    return geometry.Point3D(
        (float(a.x_m) + float(b.x_m)) / 2,
        (float(a.y_m) + float(b.y_m)) / 2,
        (float(a.z_m) + float(b.z_m)) / 2,
    )


def _offset(point: geometry.Point3D, axis: Vector3D, distance_m: float) -> geometry.Point3D:
    return geometry.Point3D(
        float(point.x_m) + axis[0] * distance_m,
        float(point.y_m) + axis[1] * distance_m,
        float(point.z_m) + axis[2] * distance_m,
    )


def _lower_face_forward_axis(
    ear_midpoint: geometry.Point3D,
    nose: geometry.Point3D,
    chin: geometry.Point3D | None,
    lateral: Vector3D,
) -> Vector3D | None:
    """Return the measured ear/nose/chin face bisector orthogonal to lateral."""

    if chin is None:
        return None
    nose_ray = _unit(_vector(ear_midpoint, nose))
    chin_ray = _unit(_vector(ear_midpoint, chin))
    if nose_ray is None or chin_ray is None:
        return None
    candidate = tuple(
        nose_ray[index] + chin_ray[index] for index in range(3)
    )
    lateral_component = _dot(candidate, lateral)
    return _unit(tuple(
        candidate[index] - lateral_component * lateral[index]
        for index in range(3)
    ))


def _torso_from_joints(
    left_shoulder: geometry.Point3D | None,
    right_shoulder: geometry.Point3D | None,
    left_hip: geometry.Point3D | None,
    right_hip: geometry.Point3D | None,
) -> AvatarTorso | None:
    if any(point is None for point in (
        left_shoulder, right_shoulder, left_hip, right_hip
    )):
        return None
    assert left_shoulder is not None and right_shoulder is not None
    assert left_hip is not None and right_hip is not None
    shoulder_width = _distance(right_shoulder, left_shoulder)
    hip_width = _distance(right_hip, left_hip)
    if shoulder_width is None or hip_width is None:
        return None

    shoulder_midpoint = _midpoint(left_shoulder, right_shoulder)
    hip_midpoint = _midpoint(left_hip, right_hip)
    longitudinal = _unit(_vector(hip_midpoint, shoulder_midpoint))
    shoulder_lateral = _unit(_vector(right_shoulder, left_shoulder))
    hip_lateral = _unit(_vector(right_hip, left_hip))
    if longitudinal is None or shoulder_lateral is None or hip_lateral is None:
        return None

    lateral_candidate = tuple(
        shoulder_lateral[index] + hip_lateral[index] for index in range(3)
    )
    along_longitudinal = _dot(lateral_candidate, longitudinal)
    lateral = _unit(tuple(
        lateral_candidate[index] - along_longitudinal * longitudinal[index]
        for index in range(3)
    ))
    if lateral is None:
        return None
    depth_axis = _unit(_cross(lateral, longitudinal))
    if depth_axis is None:
        return None

    # The only unmeasured dimension is a deliberately generic display
    # thickness. It is scaled from measured widths and is not body-shape fit.
    half_depth = .18 * ((shoulder_width + hip_width) / 2)
    front = tuple(
        _offset(point, depth_axis, half_depth)
        for point in (left_shoulder, right_shoulder, right_hip, left_hip)
    )
    back = tuple(
        _offset(point, depth_axis, -half_depth)
        for point in (left_shoulder, right_shoulder, right_hip, left_hip)
    )
    return AvatarTorso(
        shoulder_midpoint=shoulder_midpoint,
        hip_midpoint=hip_midpoint,
        longitudinal_axis=longitudinal,
        lateral_axis=lateral,
        depth_axis=depth_axis,
        shoulder_width_m=shoulder_width,
        hip_width_m=hip_width,
        half_depth_m=half_depth,
        vertices=front + back,
    )


def build_avatar_primitives(result: geometry.GeometryResult) -> AvatarPrimitives:
    """Build display-only primitives from available measured 3D joints.

    No smoothing, filtering, landmark substitution, pose optimization, or body
    fitting is performed. A primitive is omitted when its required joints are
    unavailable.
    """

    joints = joint_positions_3d(result)
    left_shoulder = joints["left_shoulder"]
    right_shoulder = joints["right_shoulder"]
    left_hip = joints["left_hip"]
    right_hip = joints["right_hip"]
    shoulder_width = (
        _distance(left_shoulder, right_shoulder)
        if left_shoulder is not None and right_shoulder is not None else None
    )
    hip_width = (
        _distance(left_hip, right_hip)
        if left_hip is not None and right_hip is not None else None
    )

    arm_segments = []
    for side in ("left", "right"):
        for role, start_name, end_name in (
            ("upper_arm", f"{side}_shoulder", f"{side}_elbow"),
            ("forearm", f"{side}_elbow", f"{side}_wrist"),
        ):
            start, end = joints[start_name], joints[end_name]
            if start is None or end is None:
                continue
            segment_length = _distance(start, end)
            if segment_length is None:
                continue
            reference = shoulder_width if shoulder_width is not None else segment_length
            arm_segments.append(AvatarCapsule(
                name=f"{side}_{role}",
                start_name=start_name,
                end_name=end_name,
                start=start,
                end=end,
                radius_m=.075 * reference,
            ))

    torso = _torso_from_joints(
        left_shoulder, right_shoulder, left_hip, right_hip
    )
    pelvis = None
    if left_hip is not None and right_hip is not None and hip_width is not None:
        pelvis = AvatarCapsule(
            name="pelvis",
            start_name="left_hip",
            end_name="right_hip",
            start=left_hip,
            end=right_hip,
            radius_m=.18 * hip_width,
        )

    head = None
    neck = None
    nose = joints["nose"]
    left_ear, right_ear = joints["left_ear"], joints["right_ear"]
    chin = _usable_point_3d(result.points_3d.get("chin"))
    if (nose is not None and left_ear is not None and right_ear is not None
            and left_shoulder is not None and right_shoulder is not None):
        ear_width = _distance(left_ear, right_ear)
        ear_midpoint = _midpoint(left_ear, right_ear)
        shoulder_midpoint = _midpoint(left_shoulder, right_shoulder)
        lateral = _unit(_vector(right_ear, left_ear))
        vertical_candidate = _unit(_vector(shoulder_midpoint, ear_midpoint))
        if ear_width is not None and lateral is not None:
            # Prefer the measured lower-face direction.  If chin XYZ is absent,
            # preserve the previous shoulder/ear-derived head orientation.
            forward = _lower_face_forward_axis(ear_midpoint, nose, chin, lateral)
            vertical = _unit(_cross(forward, lateral)) if forward is not None else None
            if forward is None and vertical_candidate is not None:
                lateral_component = _dot(vertical_candidate, lateral)
                vertical = _unit(tuple(
                    vertical_candidate[index] - lateral_component * lateral[index]
                    for index in range(3)
                ))
                forward = _unit(_cross(lateral, vertical)) if vertical is not None else None
                if forward is not None and _dot(forward, _vector(ear_midpoint, nose)) < 0:
                    forward = tuple(-value for value in forward)  # type: ignore[assignment]
            if vertical is not None and forward is not None:
                head = AvatarEllipsoid(
                    name="head",
                    center=_midpoint(nose, ear_midpoint),
                    lateral_axis=lateral,
                    vertical_axis=vertical,
                    forward_axis=forward,
                    radii_m=(.65 * ear_width, .85 * ear_width, .55 * ear_width),
                )
                neck_reference = min(ear_width, shoulder_width or ear_width)
                neck = AvatarCapsule(
                    name="neck",
                    start_name="ear_midpoint",
                    end_name="shoulder_midpoint",
                    start=ear_midpoint,
                    end=shoulder_midpoint,
                    radius_m=.22 * neck_reference,
                )

    scale_candidates = [value for value in (shoulder_width, hip_width) if value is not None]
    if left_ear is not None and right_ear is not None:
        ear_width = _distance(left_ear, right_ear)
        if ear_width is not None:
            scale_candidates.append(ear_width)
    display_scale = max(scale_candidates) if scale_candidates else None
    joint_spheres = tuple(
        AvatarSphere(name, point, .035 * display_scale)
        for name, point in joints.items()
        if point is not None and display_scale is not None
    )

    return AvatarPrimitives(
        head=head,
        neck=neck,
        torso=torso,
        pelvis=pelvis,
        arm_segments=tuple(arm_segments),
        joints=joint_spheres,
    )


def _usable_point_3d(point: object) -> geometry.Point3D | None:
    if not isinstance(point, geometry.Point3D):
        return None
    values = (point.x_m, point.y_m, point.z_m)
    if not all(isinstance(value, (int, float, np.number)) and not isinstance(value, bool)
               and math.isfinite(float(value)) for value in values):
        return None
    if float(point.z_m) <= 0:
        return None
    return point


def joint_positions_3d(result: geometry.GeometryResult) -> dict[str, geometry.Point3D | None]:
    """Return the reusable direct-joint mapping without altering the result."""

    return {name: _usable_point_3d(result.points_3d.get(name)) for name in JOINT_NAMES}


def available_skeleton_segments(result: geometry.GeometryResult) -> tuple[SkeletonSegment, ...]:
    """Return only anatomical segments whose two endpoint joints are available."""

    joints = joint_positions_3d(result)
    segments = []
    for start_name, end_name in SKELETON_SEGMENTS:
        start, end = joints[start_name], joints[end_name]
        if start is not None and end is not None:
            segments.append(SkeletonSegment(start_name, end_name, start, end))
    return tuple(segments)


def depth_vertical_to_sagittal(point: geometry.Point3D | None) -> SagittalPoint | None:
    """Convert RealSense XYZ to the metric depth-derived sagittal plane.

    Camera lateral X is intentionally discarded.  No perspective synthesis or
    side-camera reconstruction is attempted.
    """

    point = _usable_point_3d(point)
    if point is None:
        return None
    return SagittalPoint(camera_forward_m=-float(point.z_m), vertical_up_m=-float(point.y_m))


def sagittal_points(result: geometry.GeometryResult) -> dict[str, SagittalPoint | None]:
    """Project already-computed nose and midpoint geometry into the sagittal plane."""

    projected: dict[str, SagittalPoint | None] = {}
    for output_name, (collection_name, source_name) in SAGITTAL_POINT_SOURCES.items():
        collection = getattr(result, collection_name)
        projected[output_name] = depth_vertical_to_sagittal(collection.get(source_name))
    return projected


def axonometric_project(point: geometry.Point3D | None) -> tuple[float, float] | None:
    """Project metric XYZ to a fixed axonometric display plane.

    This changes display coordinates only.  The underlying metric joints remain
    untouched and are available from :func:`joint_positions_3d`.
    """

    point = _usable_point_3d(point)
    if point is None:
        return None
    camera_forward = -float(point.z_m)
    return (
        float(point.x_m) + 0.35 * camera_forward,
        -float(point.y_m) + 0.18 * camera_forward,
    )



def side_view_project(point: geometry.Point3D | None) -> tuple[float, float] | None:
    """Project metric XYZ onto a fixed side-oriented Y-Z display plane.

    The display looks along the camera X axis.  Screen-right is RealSense +Z
    (farther from the physical camera) and screen-up is -Y (body height), so
    the physical camera is consistently to the left.  X is omitted only by
    this display transform; avatar primitives retain their original XYZ data.
    """

    point = _usable_point_3d(point)
    if point is None:
        return None
    return (float(point.z_m), -float(point.y_m))

def _fit_points(
    points: Mapping[str, tuple[float, float] | SagittalPoint | None],
    width: int,
    height: int,
    *,
    margins: tuple[int, int, int, int] = (45, 80, 35, 55),
) -> dict[str, tuple[int, int] | None]:
    """Fit finite 2D metric coordinates into a canvas with equal axis scale."""

    left, top, right, bottom = margins
    if width <= left + right or height <= top + bottom:
        raise ValueError("canvas is too small for the requested margins")

    numeric: dict[str, tuple[float, float]] = {}
    for name, point in points.items():
        if point is None:
            continue
        if isinstance(point, SagittalPoint):
            x, y = point.camera_forward_m, point.vertical_up_m
        else:
            x, y = point
        if math.isfinite(float(x)) and math.isfinite(float(y)):
            numeric[name] = (float(x), float(y))

    output: dict[str, tuple[int, int] | None] = {name: None for name in points}
    if not numeric:
        return output

    xs = [point[0] for point in numeric.values()]
    ys = [point[1] for point in numeric.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x, span_y = max_x - min_x, max_y - min_y
    usable_width = width - left - right
    usable_height = height - top - bottom
    scale = min(
        usable_width / span_x if span_x > 1e-9 else math.inf,
        usable_height / span_y if span_y > 1e-9 else math.inf,
    )
    if not math.isfinite(scale):
        scale = min(usable_width, usable_height) / 2
    scale *= 0.9
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    canvas_center_x = left + usable_width / 2
    canvas_center_y = top + usable_height / 2
    for name, (x, y) in numeric.items():
        output[name] = (
            int(round(canvas_center_x + (x - center_x) * scale)),
            int(round(canvas_center_y - (y - center_y) * scale)),
        )
    return output


def _canvas(size: tuple[int, int]) -> np.ndarray:
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("size must contain positive width and height")
    return np.full((height, width, 3), 24, dtype=np.uint8)


def _put(cv2: object, image: np.ndarray, text: str, at: tuple[int, int],
         color: tuple[int, int, int] = (230, 230, 230), scale: float = .42) -> None:
    cv2.putText(image, text, at, cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, 1, cv2.LINE_AA)


def render_upper_body_skeleton(
    result: geometry.GeometryResult, *, size: tuple[int, int] = (560, 640)
) -> np.ndarray:
    """Render a testable axonometric 3D skeleton from direct metric joints."""

    import cv2

    canvas = _canvas(size)
    width, height = size
    joints = joint_positions_3d(result)
    projected = {name: axonometric_project(point) for name, point in joints.items()}
    pixels = _fit_points(projected, width, height)

    _put(cv2, canvas, "3D upper-body skeleton", (14, 24), (100, 220, 100), .55)
    _put(cv2, canvas, "metric XYZ / fixed axonometric display", (14, 46), (170, 170, 170))
    _put(cv2, canvas, "+X right, +Y down, +Z away from camera", (14, 65), (170, 170, 170), .36)

    for start_name, end_name in SKELETON_SEGMENTS:
        start, end = pixels[start_name], pixels[end_name]
        if start is not None and end is not None:
            cv2.line(canvas, start, end, (185, 185, 185), 3, cv2.LINE_AA)

    for name in JOINT_NAMES:
        pixel = pixels[name]
        if pixel is None:
            continue
        color = (0, 190, 255) if "left_" in name else (255, 170, 50)
        if name == "nose":
            color = (0, 255, 255)
        cv2.circle(canvas, pixel, 6, color, -1, cv2.LINE_AA)
        _put(cv2, canvas, name.replace("_", " "), (pixel[0] + 7, pixel[1] - 7), color, .34)

    available = sum(point is not None for point in joints.values())
    _put(cv2, canvas, f"available joints: {available}/{len(JOINT_NAMES)}",
         (14, height - 14), (0, 210, 255), .43)
    return canvas


def render_sagittal_view(
    result: geometry.GeometryResult, *, size: tuple[int, int] = (560, 640)
) -> np.ndarray:
    """Render the explicitly labelled depth-derived sagittal projection."""

    import cv2

    canvas = _canvas(size)
    width, height = size
    points = sagittal_points(result)
    pixels = _fit_points(points, width, height)

    _put(cv2, canvas, "Depth-derived sagittal visualization", (14, 24),
         (100, 220, 100), .52)
    _put(cv2, canvas, "NOT a reconstructed side-camera image", (14, 47),
         (0, 190, 255), .42)
    _put(cv2, canvas, "horizontal: camera-forward (-Z); vertical: up (-Y)",
         (14, 67), (170, 170, 170), .34)

    for start_name, end_name in SAGITTAL_SEGMENTS:
        start, end = pixels[start_name], pixels[end_name]
        if start is None or end is None:
            continue
        color = (0, 140, 255) if (start_name, end_name) == (
            "shoulder_midpoint", "hip_midpoint"
        ) else (190, 190, 190)
        thickness = 4 if color == (0, 140, 255) else 2
        cv2.line(canvas, start, end, color, thickness, cv2.LINE_AA)

    colors = {
        "nose": (0, 255, 255),
        "ear_midpoint": (255, 160, 0),
        "shoulder_midpoint": (0, 220, 0),
        "hip_midpoint": (255, 100, 255),
    }
    for name, pixel in pixels.items():
        if pixel is None:
            continue
        cv2.circle(canvas, pixel, 6, colors[name], -1, cv2.LINE_AA)
        _put(cv2, canvas, name.replace("_", " "), (pixel[0] + 7, pixel[1] - 7),
             colors[name], .36)

    _put(cv2, canvas, "orange segment = torso axis", (14, height - 14),
         (0, 140, 255), .43)
    return canvas


def _avatar_projection_points(
    primitives: AvatarPrimitives,
    projector: Callable[[geometry.Point3D | None], tuple[float, float] | None],
) -> dict[str, tuple[float, float] | None]:
    points: dict[str, geometry.Point3D] = {}
    capsules = (
        *((primitives.neck,) if primitives.neck is not None else ()),
        *((primitives.pelvis,) if primitives.pelvis is not None else ()),
        *primitives.arm_segments,
    )
    for capsule in capsules:
        points[f"capsule:{capsule.name}:start"] = capsule.start
        points[f"capsule:{capsule.name}:end"] = capsule.end
    if primitives.torso is not None:
        for index, point in enumerate(primitives.torso.vertices):
            points[f"torso:{index}"] = point
    if primitives.head is not None:
        head = primitives.head
        points["head:center"] = head.center
        for label, axis, radius in (
            ("lateral", head.lateral_axis, head.radii_m[0]),
            ("vertical", head.vertical_axis, head.radii_m[1]),
            ("forward", head.forward_axis, head.radii_m[2]),
        ):
            points[f"head:{label}:positive"] = _offset(head.center, axis, radius)
            points[f"head:{label}:negative"] = _offset(head.center, axis, -radius)
    for sphere in primitives.joints:
        points[f"joint:{sphere.joint_name}"] = sphere.center
    return {name: projector(point) for name, point in points.items()}

def _display_scale(
    points: Mapping[str, tuple[float, float] | None],
    width: int,
    height: int,
    *,
    margins: tuple[int, int, int, int] = (45, 80, 35, 55),
) -> float:
    numeric = [point for point in points.values() if point is not None]
    if not numeric:
        return 1.0
    left, top, right, bottom = margins
    xs = [float(point[0]) for point in numeric]
    ys = [float(point[1]) for point in numeric]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    usable_width = width - left - right
    usable_height = height - top - bottom
    scale = min(
        usable_width / span_x if span_x > 1e-9 else math.inf,
        usable_height / span_y if span_y > 1e-9 else math.inf,
    )
    if not math.isfinite(scale):
        scale = min(usable_width, usable_height) / 2
    return .9 * scale


def _render_avatar_view(
    result: geometry.GeometryResult,
    *,
    size: tuple[int, int],
    projector: Callable[[geometry.Point3D | None], tuple[float, float] | None],
    title: str,
    coordinate_text: str,
    head_horizontal_axis: str,
    direction_label: str | None = None,
) -> np.ndarray:
    """Render shared measured avatar primitives through one display transform."""

    import cv2

    canvas = _canvas(size)
    width, height = size
    primitives = build_avatar_primitives(result)
    projected = _avatar_projection_points(primitives, projector)
    margins = (55, 110 if direction_label else 80, 45, 55)
    pixels = _fit_points(projected, width, height, margins=margins)
    scale = _display_scale(projected, width, height, margins=margins)

    _put(cv2, canvas, title, (14, 24), (100, 220, 100), .54)
    _put(cv2, canvas, "visual approximation / NOT anatomical reconstruction",
         (14, 47), (0, 190, 255), .39)
    _put(cv2, canvas, coordinate_text, (14, 67), (170, 170, 170), .36)
    if direction_label is not None:
        _put(cv2, canvas, direction_label, (14, 91), (0, 210, 255), .46)

    if primitives.torso is not None:
        torso_pixels = [pixels[f"torso:{index}"] for index in range(8)]
        if all(point is not None for point in torso_pixels):
            vertices = [point for point in torso_pixels if point is not None]
            overlay = canvas.copy()
            for face, color in (
                ((4, 5, 6, 7), (80, 105, 125)),
                ((0, 4, 7, 3), (95, 130, 150)),
                ((1, 5, 6, 2), (85, 120, 145)),
                ((0, 1, 2, 3), (105, 150, 175)),
            ):
                polygon = np.asarray([vertices[index] for index in face], dtype=np.int32)
                cv2.fillConvexPoly(overlay, polygon, color, cv2.LINE_AA)
                cv2.polylines(overlay, [polygon], True, (180, 205, 215), 1, cv2.LINE_AA)
            cv2.addWeighted(overlay, .72, canvas, .28, 0, canvas)

    capsules = (
        *primitives.arm_segments,
        *((primitives.neck,) if primitives.neck is not None else ()),
        *((primitives.pelvis,) if primitives.pelvis is not None else ()),
    )
    capsule_colors = {
        "left_upper_arm": (60, 150, 225),
        "left_forearm": (70, 175, 240),
        "right_upper_arm": (225, 145, 70),
        "right_forearm": (240, 165, 80),
        "neck": (170, 190, 205),
        "pelvis": (155, 95, 190),
    }
    for capsule in capsules:
        start = pixels[f"capsule:{capsule.name}:start"]
        end = pixels[f"capsule:{capsule.name}:end"]
        if start is None or end is None:
            continue
        radius_px = max(2, int(round(capsule.radius_m * scale)))
        color = capsule_colors[capsule.name]
        cv2.line(canvas, start, end, color, 2 * radius_px, cv2.LINE_AA)
        cv2.circle(canvas, start, radius_px, color, -1, cv2.LINE_AA)
        cv2.circle(canvas, end, radius_px, color, -1, cv2.LINE_AA)

    if primitives.head is not None:
        center = pixels["head:center"]
        horizontal = pixels[f"head:{head_horizontal_axis}:positive"]
        vertical = pixels["head:vertical:positive"]
        if center is not None and horizontal is not None and vertical is not None:
            horizontal_px = max(2, int(round(math.hypot(
                horizontal[0] - center[0], horizontal[1] - center[1]
            ))))
            vertical_px = max(2, int(round(math.hypot(
                vertical[0] - center[0], vertical[1] - center[1]
            ))))
            angle = math.degrees(math.atan2(
                horizontal[1] - center[1], horizontal[0] - center[0]
            ))
            cv2.ellipse(canvas, center, (horizontal_px, vertical_px), angle,
                        0, 360, (115, 180, 215), -1, cv2.LINE_AA)
            cv2.ellipse(canvas, center, (horizontal_px, vertical_px), angle,
                        0, 360, (205, 225, 235), 2, cv2.LINE_AA)

    for sphere in primitives.joints:
        center = pixels[f"joint:{sphere.joint_name}"]
        if center is None:
            continue
        radius_px = max(2, int(round(sphere.radius_m * scale)))
        color = (0, 190, 255) if sphere.joint_name.startswith("left_") else (255, 170, 50)
        if sphere.joint_name == "nose":
            color = (0, 255, 255)
        cv2.circle(canvas, center, radius_px, color, -1, cv2.LINE_AA)

    primitive_count = (
        len(primitives.arm_segments)
        + len(primitives.joints)
        + sum(value is not None for value in (
            primitives.head, primitives.neck, primitives.torso, primitives.pelvis
        ))
    )
    _put(cv2, canvas, f"available avatar primitives: {primitive_count}",
         (14, height - 14), (0, 210, 255), .43)
    return canvas


def render_avatar_view(
    result: geometry.GeometryResult, *, size: tuple[int, int] = DEFAULT_PANEL_SIZE
) -> np.ndarray:
    """Render the legacy joint-driven avatar in its axonometric debug plane."""

    return _render_avatar_view(
        result,
        size=size,
        projector=axonometric_project,
        title="Exploratory joint-driven avatar",
        coordinate_text="metric joints / fixed axonometric display",
        head_horizontal_axis="lateral",
    )


def render_side_avatar_view(
    result: geometry.GeometryResult, *, size: tuple[int, int] = DEFAULT_SIDE_VIEW_SIZE
) -> np.ndarray:
    """Render the primary ergonomic avatar in a fixed orthographic side view."""

    return _render_avatar_view(
        result,
        size=size,
        projector=side_view_project,
        title="Side-oriented 3D ergonomic avatar",
        coordinate_text="horizontal: depth (+Z away); vertical: height (-Y)",
        head_horizontal_axis="forward",
        direction_label=SIDE_CAMERA_LABEL,
    )

def render_views(
    result: geometry.GeometryResult, *, panel_size: tuple[int, int] = (560, 640)
) -> np.ndarray:
    """Render the 3D skeleton and sagittal view side by side."""

    return np.hstack((
        render_upper_body_skeleton(result, size=panel_size),
        render_sagittal_view(result, size=panel_size),
    ))


def render_selected_views(
    result: geometry.GeometryResult,
    mode: str,
    *,
    panel_size: tuple[int, int] | None = None,
) -> np.ndarray:
    """Render the primary side avatar or explicitly requested debug panels."""

    if mode == "side":
        return render_side_avatar_view(
            result, size=panel_size or DEFAULT_SIDE_VIEW_SIZE
        )

    debug_size = panel_size or DEFAULT_PANEL_SIZE
    if mode == "skeleton":
        return render_views(result, panel_size=debug_size)
    if mode == "avatar":
        return np.hstack((
            render_avatar_view(result, size=debug_size),
            render_sagittal_view(result, size=debug_size),
        ))
    if mode in ("debug", "all"):
        return np.hstack((
            render_upper_body_skeleton(result, size=debug_size),
            render_avatar_view(result, size=debug_size),
            render_sagittal_view(result, size=debug_size),
        ))
    raise ValueError("mode must be one of: side, debug, skeleton, avatar, all")
