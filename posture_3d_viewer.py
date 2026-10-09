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
from typing import Mapping, Sequence

import numpy as np

import posture_geometry as geometry


WINDOW_NAME = "Exploratory upper-body 3D views"

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


def render_views(
    result: geometry.GeometryResult, *, panel_size: tuple[int, int] = (560, 640)
) -> np.ndarray:
    """Render the 3D skeleton and sagittal view side by side."""

    return np.hstack((
        render_upper_body_skeleton(result, size=panel_size),
        render_sagittal_view(result, size=panel_size),
    ))

