"""Live, non-formal D455 probe for exploratory posture geometry.

This tool is intentionally outside the production posture-decision path and the
canonical frames schema.  It performs no posture classification.  Optional CSV
output is explicitly exploratory engineering output and is disabled by default.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from functools import lru_cache
import math
from numbers import Real
import os
from typing import Any, Mapping, Sequence
import warnings

import numpy as np

import posture_geometry as geometry
import posture_3d_viewer as viewer
import posture_pyvista_viewer as pyvista_viewer


WINDOW_NAME = "Exploratory D455 posture geometry probe"
EXPLORATORY_ARTIFACT_KIND = "exploratory-posture-geometry-engineering-measurement"
FACE_DIAGNOSTIC_ARTIFACT_KIND = (
    "exploratory-face-pipeline-engineering-diagnostic"
)
PANEL_HEIGHT = 760
PANEL_WIDTH = 560
DEBUG_PAGE_COUNT = 5

SUMMARY_LABELS_KO = {
    "title": "D455 자세 측정 — 개발용",
    "subtitle": "비정식 탐색 측정 | 자세 정상/비정상 판정 아님",
    "camera_section": "카메라 및 검출 상태",
    "nose_depth": "코 깊이(Z축)",
    "face_detection": "얼굴 검출",
    "matrix_status": "얼굴 방향 계산",
    "head_section": "머리 방향 측정",
    "chin_pitch": "기존 턱 기반 상하 회전",
    "matrix_pitch": "신규 Matrix 상하 회전",
    "matrix_yaw": "신규 Matrix 좌우 회전",
    "matrix_roll": "신규 Matrix 좌우 기울기",
    "head_note": "카메라 기준 탐색 각도이며 해부학적 중립각이 아님",
    "body_section": "상체 측정",
    "torso_lean": "상체 앞뒤 기울기",
    "shoulder_tilt": "양쪽 어깨 기울기",
    "shoulder_width": "3D 어깨 너비",
    "head_forward": "머리 전방 위치(상대값)",
    "head_forward_hint": (
        "기술값: nose_forward_normalized_by_shoulder_width_3d"
    ),
    "status_section": "상태 안내",
    "engineering_only": "개발용 실시간 표시 | 자세 판정 없음",
    "quit": "q 키: 종료",
    "unavailable": "측정 불가",
    "detected": "검출됨",
    "no_face": "미검출",
    "valid": "유효",
    "missing": "누락",
    "invalid": "무효",
}

SUMMARY_LABELS_EN = {
    "title": "D455 POSTURE MEASUREMENT - ENGINEERING",
    "subtitle": "Non-formal exploratory measurement | No posture decision",
    "camera_section": "CAMERA AND DETECTION",
    "nose_depth": "Nose depth (Z axis)",
    "face_detection": "Face detection",
    "matrix_status": "Face orientation",
    "head_section": "HEAD ORIENTATION",
    "chin_pitch": "Legacy chin-based pitch",
    "matrix_pitch": "Matrix pitch",
    "matrix_yaw": "Matrix yaw",
    "matrix_roll": "Matrix roll",
    "head_note": "Camera-relative exploratory angles; not anatomical neutral",
    "body_section": "UPPER BODY",
    "torso_lean": "Sagittal torso lean",
    "shoulder_tilt": "Shoulder tilt",
    "shoulder_width": "3D shoulder width",
    "head_forward": "Relative head-forward position",
    "head_forward_hint": (
        "source: nose_forward_normalized_by_shoulder_width_3d"
    ),
    "status_section": "STATUS",
    "engineering_only": "Engineering display | No posture decision",
    "quit": "q: quit",
    "unavailable": "unavailable",
    "detected": "DETECTED",
    "no_face": "NO_FACE",
    "valid": "VALID",
    "missing": "MISSING",
    "invalid": "INVALID",
}

POINT_NAMES = geometry.EXPLORATORY_POINT_NAMES
FEATURE_FIELDS = (
    "head_lateral_tilt_deg",
    "shoulder_tilt_deg",
    "relative_head_tilt_deg",
    "shoulder_width_px",
    "nose_to_shoulder_mid_dx_shoulder_width",
    "nose_to_shoulder_mid_dy_shoulder_width",
    "left_ear_to_left_shoulder_dx_shoulder_width",
    "left_ear_to_left_shoulder_dy_shoulder_width",
    "right_ear_to_right_shoulder_dx_shoulder_width",
    "right_ear_to_right_shoulder_dy_shoulder_width",
    "head_to_torso_lateral_angle_deg",
    "torso_depth_proxy_m",
    "nose_forward_from_torso_m",
    "left_ear_forward_from_torso_m",
    "right_ear_forward_from_torso_m",
    "ear_midpoint_forward_from_torso_m",
    "shoulder_width_metric_proxy_m",
    "nose_forward_normalized_by_shoulder_width",
    "ear_midpoint_forward_normalized_by_shoulder_width",
    "shoulder_width_3d_m",
    "sagittal_torso_lean_deg",
    "exploratory_head_pitch_deg",
    "nose_forward_normalized_by_shoulder_width_3d",
    "ear_midpoint_forward_normalized_by_shoulder_width_3d",
)

FACE_MATRIX_FIELDS = (
    "face_matrix_valid",
    "face_matrix_pitch_deg",
    "face_matrix_yaw_deg",
    "face_matrix_roll_deg",
)

FACE_DIAGNOSTIC_FIELDS = (
    "artifact_kind",
    "frame_index",
    "device_timestamp_ms",
    "mediapipe_timestamp_ms",
    "rgb_width",
    "rgb_height",
    "pose_detected",
    "face_count",
    "first_face_landmark_count",
    "chin_normalized_x",
    "chin_normalized_y",
    "chin_coordinate_in_bounds",
    "face_matrix_count",
    "face_matrix_selected",
    "face_matrix_valid",
    "face_pipeline_status",
)

POINT_3D_SOURCES = (
    ("left_shoulder_3d", "points_3d", "left_shoulder"),
    ("right_shoulder_3d", "points_3d", "right_shoulder"),
    ("left_hip_3d", "points_3d", "left_hip"),
    ("right_hip_3d", "points_3d", "right_hip"),
    ("shoulder_midpoint_3d", "proxies_3d", "shoulder_midpoint_3d"),
    ("hip_midpoint_3d", "proxies_3d", "hip_midpoint_3d"),
    ("nose_3d", "points_3d", "nose"),
    ("left_ear_3d", "points_3d", "left_ear"),
    ("right_ear_3d", "points_3d", "right_ear"),
    ("left_elbow_3d", "points_3d", "left_elbow"),
    ("right_elbow_3d", "points_3d", "right_elbow"),
    ("left_wrist_3d", "points_3d", "left_wrist"),
    ("right_wrist_3d", "points_3d", "right_wrist"),
    ("ear_midpoint_3d", "proxies_3d", "ear_midpoint_3d"),
    ("chin_3d", "points_3d", "chin"),
)
POINT_3D_FIELDS = tuple(
    f"{output_name}_{axis}_m"
    for output_name, _, _ in POINT_3D_SOURCES
    for axis in ("x", "y", "z")
)

FEATURE_DISPLAY = (
    ("head tilt", "head_lateral_tilt_deg", " deg"),
    ("shoulder tilt", "shoulder_tilt_deg", " deg"),
    ("relative head tilt", "relative_head_tilt_deg", " deg"),
    ("shoulder width", "shoulder_width_px", " px"),
    ("nose dx / shoulder", "nose_to_shoulder_mid_dx_shoulder_width", ""),
    ("nose dy / shoulder", "nose_to_shoulder_mid_dy_shoulder_width", ""),
    ("left ear dx / shoulder", "left_ear_to_left_shoulder_dx_shoulder_width", ""),
    ("left ear dy / shoulder", "left_ear_to_left_shoulder_dy_shoulder_width", ""),
    ("right ear dx / shoulder", "right_ear_to_right_shoulder_dx_shoulder_width", ""),
    ("right ear dy / shoulder", "right_ear_to_right_shoulder_dy_shoulder_width", ""),
    ("head-to-torso lateral", "head_to_torso_lateral_angle_deg", " deg"),
    ("torso depth proxy", "torso_depth_proxy_m", " m"),
    ("nose forward", "nose_forward_from_torso_m", " m"),
    ("left ear forward", "left_ear_forward_from_torso_m", " m"),
    ("right ear forward", "right_ear_forward_from_torso_m", " m"),
    ("ear midpoint forward", "ear_midpoint_forward_from_torso_m", " m"),
    ("approx shoulder scale", "shoulder_width_metric_proxy_m", " m"),
    ("nose forward / shoulder", "nose_forward_normalized_by_shoulder_width", ""),
    ("ear-mid forward / shoulder", "ear_midpoint_forward_normalized_by_shoulder_width", ""),
    ("3D shoulder width", "shoulder_width_3d_m", " m"),
    ("sagittal torso lean (+camera)", "sagittal_torso_lean_deg", " deg"),
    ("exploratory head pitch (+up)", "exploratory_head_pitch_deg", " deg"),
    ("nose forward / 3D shoulder", "nose_forward_normalized_by_shoulder_width_3d", ""),
    ("ear-mid forward / 3D shoulder", "ear_midpoint_forward_normalized_by_shoulder_width_3d", ""),
)

CSV_FIELDS = (
    "artifact_kind",
    "timestamp_utc",
    "device_timestamp_ms",
    "pose_detected",
    *(f"{name}_landmark_valid" for name in POINT_NAMES),
    *(f"{name}_depth_valid" for name in POINT_NAMES),
    "normalized_nose_available",
    "normalized_ear_midpoint_available",
    "shoulder_width_3d_available",
    "sagittal_torso_lean_available",
    *POINT_3D_FIELDS,
    *FEATURE_FIELDS,
    *FACE_MATRIX_FIELDS,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live NON-FORMAL D455 exploratory posture-geometry probe."
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        default=None,
        help=("write exploratory engineering measurements to a new CSV file; "
              "default: no file output"),
    )
    parser.add_argument(
        "--face-diag-csv",
        metavar="PATH",
        default=None,
        help=("write per-frame FaceLandmarker engineering diagnostics to a new "
              "CSV file; default: no diagnostic file output"),
    )
    parser.add_argument(
        "--panel-mode",
        choices=("summary", "debug"),
        default="summary",
        help=("engineering panel content; default: Korean summary, while "
              "debug provides paged detailed values"),
    )
    parser.add_argument(
        "--views",
        nargs="?",
        const="side",
        choices=("side", "debug", "skeleton", "avatar", "all"),
        default=None,
        help=("show exploratory 3D views: bare --views (or 'side') shows the "
              "primary side-oriented avatar; 'debug' shows the legacy skeleton, "
              "axonometric avatar, and sagittal panels; legacy individual modes "
              "and 'all' remain available"),
    )
    parser.add_argument(
        "--pyvista",
        action="store_true",
        help=("also show the optional PyVista front/side 3D avatar window; "
              f"requires: {pyvista_viewer.INSTALL_HINT}"),
    )
    parser.add_argument(
        "--pyvista-anchor",
        choices=pyvista_viewer.VIEW_ANCHOR_MODES,
        default=pyvista_viewer.VIEW_ANCHOR_SHOULDER,
        help=("PyVista view centre: 'shoulder' (default) follows the measured "
              "shoulder midpoint; 'camera' locks it once and keeps it fixed in "
              "camera coordinates; display only, requires --pyvista"),
    )
    args = parser.parse_args(argv)
    if args.pyvista_anchor != pyvista_viewer.VIEW_ANCHOR_SHOULDER and not args.pyvista:
        parser.error("--pyvista-anchor requires --pyvista")
    return args


def format_feature(value: Any, unit: str = "") -> str:
    """Format a live value without converting missing/invalid data into a number."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return "unavailable"
    value = float(value)
    if not math.isfinite(value):
        return "unavailable"
    return f"{value:+.3f}{unit}"


def extract_face_matrix_orientation(
    matrix: Any,
) -> tuple[float, float, float] | None:
    """Return exploratory camera-relative (pitch, yaw, roll) in degrees.

    MediaPipe's 4x4 matrix maps canonical-face column vectors into its runtime
    metric face space.  That space is right-handed: +X is image-right, +Y is
    image-up, and the camera looks along -Z (so canonical face-forward is +Z
    at the identity pose).  It is not the RealSense +X-right, +Y-down,
    +Z-away coordinate system used by posture_geometry.

    After removing MediaPipe's uniform scale with the closest proper rotation,
    the convention is the active composition
    R = Rz(roll) @ Ry(yaw) @ Rx(-pitch).  Thus positive pitch moves face
    forward toward image-up, positive yaw moves it toward image-right, and
    positive roll moves +X toward +Y (counter-clockwise in the unmirrored
    image).  These are exploratory camera-relative pose angles, not cervical
    anatomical angles.

    Gimbal lock is represented deterministically with roll set to zero.  A
    malformed homogeneous matrix, reflection, degenerate block, or appreciable
    non-uniform scale/shear is unsupported and returns None.
    """

    if matrix is None:
        return None
    try:
        transform = np.asarray(matrix, dtype=float)
    except (TypeError, ValueError):
        return None
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        return None
    if not np.allclose(transform[3], (0.0, 0.0, 0.0, 1.0), atol=1e-6, rtol=0.0):
        return None

    linear = transform[:3, :3]
    try:
        left, singular_values, right_t = np.linalg.svd(linear)
    except np.linalg.LinAlgError:
        return None
    scale = float(np.mean(singular_values))
    if not math.isfinite(scale) or scale <= 1e-8:
        return None
    # MediaPipe specifies one uniform scale.  This also rejects shear because
    # shear produces unequal singular values even when column norms look close.
    # The official MediaPipe Python reference output itself has about 0.5%
    # singular-value spread, so allow up to 1% numerical fit deviation.
    if float(np.max(np.abs(singular_values - scale))) > 1e-2 * scale:
        return None
    if float(np.linalg.det(linear)) <= 0.0:
        return None

    rotation = left @ right_t
    if not np.all(np.isfinite(rotation)) or not np.allclose(
        rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0.0
    ):
        return None
    if not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=1e-6):
        return None

    yaw = math.asin(float(np.clip(-rotation[2, 0], -1.0, 1.0)))
    if abs(math.cos(yaw)) > 1e-7:
        pitch_rh = math.atan2(rotation[2, 1], rotation[2, 2])
        roll = math.atan2(rotation[1, 0], rotation[0, 0])
    else:
        # At yaw +/-90 degrees, pitch and roll are not separately observable.
        # Choose roll=0 to keep the result deterministic.
        yaw_sign = 1.0 if yaw >= 0.0 else -1.0
        pitch_rh = math.atan2(
            yaw_sign * rotation[0, 1], yaw_sign * rotation[0, 2]
        )
        roll = 0.0

    return tuple(
        math.degrees(value) for value in (-pitch_rh, yaw, roll)
    )


def first_face_transformation_matrix(face_result: Any) -> Any | None:
    """Select the first face's matrix only when that same face was detected."""

    if face_result is None or not getattr(face_result, "face_landmarks", None):
        return None
    matrices = getattr(face_result, "facial_transformation_matrixes", None)
    if matrices is None or len(matrices) == 0:
        return None
    return matrices[0]


def run_frame_inference(
    pose_landmarker: Any,
    face_landmarker: Any,
    image: Any,
    mediapipe_timestamp_ms: int,
) -> tuple[Any, Any]:
    """Run each landmarker exactly once for one shared RGB frame/timestamp."""

    pose_result = pose_landmarker.detect_for_video(image, mediapipe_timestamp_ms)
    face_result = face_landmarker.detect_for_video(image, mediapipe_timestamp_ms)
    return pose_result, face_result


def _sequence_length(value: Any) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def face_pipeline_diagnostic_row(
    face_result: Any,
    *,
    frame_index: int,
    device_timestamp_ms: float,
    mediapipe_timestamp_ms: int,
    rgb_width: int,
    rgb_height: int,
    pose_detected: bool,
) -> dict[str, Any]:
    """Describe FaceLandmarker stages without inferring depth or confidence.

    Status precedence is face presence, chin presence, chin image bounds, matrix
    presence, then matrix mathematical validity.  The independent matrix fields
    remain populated even when an earlier chin status takes precedence.
    """

    faces = getattr(face_result, "face_landmarks", None)
    face_count = _sequence_length(faces)
    first_face = faces[0] if face_count else None
    first_face_landmark_count = _sequence_length(first_face)

    chin_x = chin_y = None
    chin_in_bounds = None
    chin_index = geometry.FACE_LANDMARK_INDICES["chin"]
    if first_face_landmark_count > chin_index:
        try:
            chin = first_face[chin_index]
            chin_x = _finite_float(chin.x)
            chin_y = _finite_float(chin.y)
        except (IndexError, KeyError, TypeError, AttributeError):
            chin_x = chin_y = None
        if chin_x is not None and chin_y is not None:
            chin_in_bounds = 0 <= chin_x < 1 and 0 <= chin_y < 1

    matrices = getattr(face_result, "facial_transformation_matrixes", None)
    face_matrix_count = _sequence_length(matrices)
    selected_matrix = first_face_transformation_matrix(face_result)
    face_matrix_selected = selected_matrix is not None
    face_matrix_valid = (
        extract_face_matrix_orientation(selected_matrix) is not None
        if face_matrix_selected
        else None
    )

    if face_count == 0:
        status = "NO_FACE"
    elif chin_x is None or chin_y is None:
        status = "FACE_WITHOUT_CHIN"
    elif not chin_in_bounds:
        status = "CHIN_OUT_OF_BOUNDS"
    elif not face_matrix_selected:
        status = "MATRIX_MISSING"
    elif not face_matrix_valid:
        status = "MATRIX_INVALID"
    else:
        status = "MATRIX_VALID"

    return {
        "artifact_kind": FACE_DIAGNOSTIC_ARTIFACT_KIND,
        "frame_index": frame_index,
        "device_timestamp_ms": device_timestamp_ms,
        "mediapipe_timestamp_ms": mediapipe_timestamp_ms,
        "rgb_width": rgb_width,
        "rgb_height": rgb_height,
        "pose_detected": bool(pose_detected),
        "face_count": face_count,
        "first_face_landmark_count": first_face_landmark_count,
        "chin_normalized_x": chin_x,
        "chin_normalized_y": chin_y,
        "chin_coordinate_in_bounds": chin_in_bounds,
        "face_matrix_count": face_matrix_count,
        "face_matrix_selected": face_matrix_selected,
        "face_matrix_valid": face_matrix_valid,
        "face_pipeline_status": status,
    }


def _face_matrix_csv_values(matrix: Any) -> dict[str, bool | float | None]:
    orientation = extract_face_matrix_orientation(matrix)
    if orientation is None:
        return {
            "face_matrix_valid": False,
            "face_matrix_pitch_deg": None,
            "face_matrix_yaw_deg": None,
            "face_matrix_roll_deg": None,
        }
    pitch, yaw, roll = orientation
    return {
        "face_matrix_valid": True,
        "face_matrix_pitch_deg": pitch,
        "face_matrix_yaw_deg": yaw,
        "face_matrix_roll_deg": roll,
    }


def diagnostics_for(result: geometry.GeometryResult, pose_detected: bool) -> dict[str, bool]:
    diagnostics: dict[str, bool] = {"pose_detected": bool(pose_detected)}
    for name in POINT_NAMES:
        point = result.points.get(name)
        diagnostics[f"{name}_landmark_valid"] = point is not None
        diagnostics[f"{name}_depth_valid"] = point is not None and point.depth_m is not None
    diagnostics["normalized_nose_available"] = (
        result.features.get("nose_forward_normalized_by_shoulder_width") is not None
    )
    diagnostics["normalized_ear_midpoint_available"] = (
        result.features.get("ear_midpoint_forward_normalized_by_shoulder_width") is not None
    )
    diagnostics["shoulder_width_3d_available"] = (
        result.features.get("shoulder_width_3d_m") is not None
    )
    diagnostics["sagittal_torso_lean_available"] = (
        result.features.get("sagittal_torso_lean_deg") is not None
    )
    return diagnostics


def deproject_body_points(
    points: dict[str, geometry.Point | None], color_intrinsics: Any, rs_module: Any
) -> dict[str, geometry.Point3D | None]:
    """Use the RealSense SDK to deproject valid aligned-depth exploratory points.

    This is the thin hardware adapter.  The pure geometry module receives only
    the resulting metric XYZ values and never imports ``pyrealsense2``.
    """

    output: dict[str, geometry.Point3D | None] = {
        name: None for name in geometry.EXPLORATORY_POINT_NAMES
    }
    for name in geometry.EXPLORATORY_POINT_NAMES:
        point = points.get(name)
        if point is None or point.depth_m is None:
            continue
        try:
            xyz = rs_module.rs2_deproject_pixel_to_point(
                color_intrinsics,
                [float(point.x_px), float(point.y_px)],
                float(point.depth_m),
            )
            if len(xyz) != 3:
                continue
            x_m, y_m, z_m = (float(value) for value in xyz)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in (x_m, y_m, z_m)) and z_m > 0:
            output[name] = geometry.Point3D(x_m, y_m, z_m)
    return output


def _point_3d_csv_values(result: geometry.GeometryResult) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for output_name, collection_name, source_name in POINT_3D_SOURCES:
        collection = getattr(result, collection_name)
        point = collection.get(source_name)
        values[f"{output_name}_x_m"] = point.x_m if point is not None else None
        values[f"{output_name}_y_m"] = point.y_m if point is not None else None
        values[f"{output_name}_z_m"] = point.z_m if point is not None else None
    return values


def exploratory_csv_row(
    result: geometry.GeometryResult,
    *,
    pose_detected: bool,
    device_timestamp_ms: float,
    timestamp_utc: str,
    face_matrix: Any = None,
) -> dict[str, Any]:
    """Build one explicitly non-canonical engineering row; ``None`` stays blank in CSV."""

    row: dict[str, Any] = {
        "artifact_kind": EXPLORATORY_ARTIFACT_KIND,
        "timestamp_utc": timestamp_utc,
        "device_timestamp_ms": device_timestamp_ms,
    }
    row.update(diagnostics_for(result, pose_detected))
    row.update(_point_3d_csv_values(result))
    row.update({name: result.features.get(name) for name in FEATURE_FIELDS})
    row.update(_face_matrix_csv_values(face_matrix))
    return row


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


@lru_cache(maxsize=1)
def _find_korean_font_files() -> tuple[str, str] | None:
    windows_dir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = (
        (
            os.path.join(windows_dir, "Fonts", "malgun.ttf"),
            os.path.join(windows_dir, "Fonts", "malgunbd.ttf"),
        ),
        (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ),
        (
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        ),
        (
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        ),
    )
    for regular, bold in candidates:
        if os.path.isfile(regular):
            return regular, bold if os.path.isfile(bold) else regular
    return None


@lru_cache(maxsize=1)
def _load_korean_fonts() -> Mapping[str, Any] | None:
    try:
        from PIL import ImageFont
    except ImportError:
        return None

    paths = _find_korean_font_files()
    if paths is None:
        return None
    regular, bold = paths
    try:
        return {
            "title": ImageFont.truetype(bold, 25),
            "subtitle": ImageFont.truetype(regular, 14),
            "section": ImageFont.truetype(bold, 18),
            "body": ImageFont.truetype(regular, 16),
            "small": ImageFont.truetype(regular, 11),
        }
    except OSError:
        return None


_FONT_WARNING_EMITTED = False


def _warn_font_fallback_once() -> None:
    global _FONT_WARNING_EMITTED
    if _FONT_WARNING_EMITTED:
        return
    warnings.warn(
        "Korean UI font/Pillow unavailable; using legible English fallback.",
        RuntimeWarning,
        stacklevel=2,
    )
    _FONT_WARNING_EMITTED = True


def panel_measurement_values(
    result: geometry.GeometryResult,
    *,
    face_detected: bool,
    face_matrix: Any,
    face_matrix_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect display-only values without changing or resampling measurements."""

    matrix_values = (
        dict(face_matrix_values)
        if face_matrix_values is not None
        else _face_matrix_csv_values(face_matrix)
    )
    nose = result.points_3d.get("nose")
    matrix_valid = bool(matrix_values.get("face_matrix_valid"))
    if face_matrix is None:
        matrix_status = "MISSING"
    elif matrix_valid:
        matrix_status = "VALID"
    else:
        matrix_status = "INVALID"
    return {
        "nose_z_m": _finite_float(getattr(nose, "z_m", None)),
        "face_status": "DETECTED" if face_detected else "NO_FACE",
        "matrix_status": matrix_status,
        "chin_pitch_deg": _finite_float(
            result.features.get("exploratory_head_pitch_deg")
        ),
        "matrix_pitch_deg": (
            _finite_float(matrix_values.get("face_matrix_pitch_deg"))
            if matrix_valid else None
        ),
        "matrix_yaw_deg": (
            _finite_float(matrix_values.get("face_matrix_yaw_deg"))
            if matrix_valid else None
        ),
        "matrix_roll_deg": (
            _finite_float(matrix_values.get("face_matrix_roll_deg"))
            if matrix_valid else None
        ),
        "torso_lean_deg": _finite_float(
            result.features.get("sagittal_torso_lean_deg")
        ),
        "shoulder_tilt_deg": _finite_float(
            result.features.get("shoulder_tilt_deg")
        ),
        "shoulder_width_3d_m": _finite_float(
            result.features.get("shoulder_width_3d_m")
        ),
        "head_forward_relative": _finite_float(
            result.features.get(
                "nose_forward_normalized_by_shoulder_width_3d"
            )
        ),
    }


def _summary_number(
    value: Any,
    unit: str,
    unavailable: str,
    *,
    signed: bool = True,
) -> str:
    finite = _finite_float(value)
    if finite is None:
        return unavailable
    sign = "+" if signed else ""
    return f"{finite:{sign}.2f}{unit}"


def _summary_layout_items(
    values: Mapping[str, Any], *, korean: bool
) -> tuple[tuple[str, int, int, str, tuple[int, int, int], str], ...]:
    labels = SUMMARY_LABELS_KO if korean else SUMMARY_LABELS_EN
    unavailable = labels["unavailable"]
    face_value = (
        labels["detected"]
        if values["face_status"] == "DETECTED"
        else labels["no_face"]
    )
    matrix_value = labels[values["matrix_status"].lower()]
    text = (235, 235, 235)
    muted = (170, 170, 170)
    accent = (0, 210, 255)
    section = (100, 220, 100)
    good = (100, 220, 100)
    caution = (0, 190, 255)
    bad = (80, 100, 255)
    face_color = good if values["face_status"] == "DETECTED" else caution
    matrix_color = {
        "VALID": good,
        "MISSING": caution,
        "INVALID": bad,
    }[values["matrix_status"]]

    def row(
        label_key: str, value: str, y: int, color: tuple[int, int, int] = text
    ) -> tuple[tuple[str, int, int, str, tuple[int, int, int], str], ...]:
        return (
            (labels[label_key], 24, y, "body", text, "lt"),
            (value, PANEL_WIDTH - 24, y, "body", color, "rt"),
        )

    items = [
        (labels["title"], 20, 12, "title", accent, "lt"),
        (labels["subtitle"], 20, 50, "subtitle", muted, "lt"),
        (labels["camera_section"], 20, 91, "section", section, "lt"),
        *row(
            "nose_depth",
            _summary_number(
                values["nose_z_m"], " m", unavailable, signed=False
            ),
            125,
        ),
        *row("face_detection", face_value, 155, face_color),
        *row("matrix_status", matrix_value, 185, matrix_color),
        (labels["head_section"], 20, 225, "section", section, "lt"),
        *row(
            "chin_pitch",
            _summary_number(values["chin_pitch_deg"], "°", unavailable),
            259,
        ),
        *row(
            "matrix_pitch",
            _summary_number(values["matrix_pitch_deg"], "°", unavailable),
            289,
        ),
        *row(
            "matrix_yaw",
            _summary_number(values["matrix_yaw_deg"], "°", unavailable),
            319,
        ),
        *row(
            "matrix_roll",
            _summary_number(values["matrix_roll_deg"], "°", unavailable),
            349,
        ),
        (labels["head_note"], 24, 379, "small", muted, "lt"),
        (labels["body_section"], 20, 419, "section", section, "lt"),
        *row(
            "torso_lean",
            _summary_number(values["torso_lean_deg"], "°", unavailable),
            453,
        ),
        *row(
            "shoulder_tilt",
            _summary_number(values["shoulder_tilt_deg"], "°", unavailable),
            483,
        ),
        *row(
            "shoulder_width",
            _summary_number(
                values["shoulder_width_3d_m"], " m", unavailable, signed=False
            ),
            513,
        ),
        *row(
            "head_forward",
            _summary_number(values["head_forward_relative"], "", unavailable),
            543,
        ),
        (labels["head_forward_hint"], 24, 572, "small", muted, "lt"),
        (labels["status_section"], 20, 615, "section", section, "lt"),
        (labels["engineering_only"], 24, 651, "body", muted, "lt"),
        (labels["quit"], 24, 684, "body", accent, "lt"),
    ]
    return tuple(items)


def _draw_summary_panel_with_pillow(
    panel: np.ndarray,
    values: Mapping[str, Any],
    fonts: Mapping[str, Any],
) -> np.ndarray:
    from PIL import Image, ImageDraw

    canvas = Image.fromarray(panel[:, :, ::-1])
    draw = ImageDraw.Draw(canvas)
    draw.line((20, 77, PANEL_WIDTH - 20, 77), fill=(70, 70, 70), width=1)
    for text, x, y, font_key, bgr, anchor in _summary_layout_items(
        values, korean=True
    ):
        draw.text(
            (x, y),
            text,
            font=fonts[font_key],
            fill=tuple(reversed(bgr)),
            anchor=anchor,
        )
    return np.asarray(canvas)[:, :, ::-1].copy()


def _draw_summary_panel_fallback(
    panel: np.ndarray, values: Mapping[str, Any]
) -> np.ndarray:
    import cv2

    scales = {
        "title": .58,
        "subtitle": .39,
        "section": .50,
        "body": .43,
        "small": .31,
    }
    cv2.line(panel, (20, 77), (PANEL_WIDTH - 20, 77), (70, 70, 70), 1)
    for text, x, y, font_key, color, anchor in _summary_layout_items(
        values, korean=False
    ):
        scale = scales[font_key]
        (width, height), _ = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1
        )
        origin_x = x - width if anchor == "rt" else x
        cv2.putText(
            panel,
            text,
            (origin_x, y + height),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            1,
            cv2.LINE_AA,
        )
    return panel


def _draw_summary_panel(
    panel: np.ndarray, values: Mapping[str, Any]
) -> np.ndarray:
    fonts = _load_korean_fonts()
    if fonts is None:
        _warn_font_fallback_once()
        return _draw_summary_panel_fallback(panel, values)
    return _draw_summary_panel_with_pillow(panel, values, fonts)


def _debug_point_2d(name: str, point: Any) -> str:
    if point is None:
        return f"{name}: unavailable"
    depth = format_feature(getattr(point, "depth_m", None), " m")
    return f"{name}: x={point.x_px:.1f} px y={point.y_px:.1f} px d={depth}"


def _debug_point_3d(name: str, point: Any) -> str:
    if point is None:
        return f"{name}: unavailable"
    return (
        f"{name}: x={point.x_m:+.3f} y={point.y_m:+.3f} "
        f"z={point.z_m:+.3f} m"
    )


def debug_panel_pages(
    result: geometry.GeometryResult,
    pose_detected: bool,
    values: Mapping[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    feature_lines = tuple(
        f"{key}: {format_feature(result.features.get(key), unit)}"
        for _, key, unit in FEATURE_DISPLAY
    )
    matrix_lines = (
        f"nose_3d_z_m: {_summary_number(values['nose_z_m'], ' m', 'unavailable', signed=False)}",
        f"face_detection: {values['face_status']}",
        f"face_matrix_status: {values['matrix_status']}",
        f"face_matrix_pitch_deg: {format_feature(values['matrix_pitch_deg'], ' deg')}",
        f"face_matrix_yaw_deg: {format_feature(values['matrix_yaw_deg'], ' deg')}",
        f"face_matrix_roll_deg: {format_feature(values['matrix_roll_deg'], ' deg')}",
    )
    availability = diagnostics_for(result, pose_detected)
    availability_lines = tuple(
        f"{name}: landmark={_yes_no(availability[f'{name}_landmark_valid'])} "
        f"depth={_yes_no(availability[f'{name}_depth_valid'])}"
        for name in POINT_NAMES
    ) + (
        "normalized_nose_available: "
        + _yes_no(availability["normalized_nose_available"]),
        "normalized_ear_midpoint_available: "
        + _yes_no(availability["normalized_ear_midpoint_available"]),
        "shoulder_width_3d_available: "
        + _yes_no(availability["shoulder_width_3d_available"]),
        "sagittal_torso_lean_available: "
        + _yes_no(availability["sagittal_torso_lean_available"]),
        f"pose_detected: {_yes_no(pose_detected)}",
        f"face_detection: {values['face_status']}",
        f"face_matrix_status: {values['matrix_status']}",
    )
    point_2d_lines = tuple(
        _debug_point_2d(name, result.points.get(name)) for name in POINT_NAMES
    ) + tuple(
        _debug_point_2d(name, point) for name, point in result.proxies.items()
    )
    point_3d_lines = tuple(
        _debug_point_3d(name, result.points_3d.get(name)) for name in POINT_NAMES
    ) + tuple(
        _debug_point_3d(name, point) for name, point in result.proxies_3d.items()
    )
    pages = (
        ("FEATURE VALUES 1", matrix_lines + feature_lines[:12]),
        ("FEATURE VALUES 2", feature_lines[12:]),
        ("2D SOURCE COORDINATES", point_2d_lines),
        ("3D SOURCE COORDINATES", point_3d_lines),
        ("LANDMARK / DEPTH VALIDITY", availability_lines),
    )
    if len(pages) != DEBUG_PAGE_COUNT:
        raise AssertionError("debug page count constant is out of sync")
    return pages


def _draw_debug_panel(
    panel: np.ndarray,
    result: geometry.GeometryResult,
    pose_detected: bool,
    values: Mapping[str, Any],
    debug_page: int,
) -> np.ndarray:
    import cv2

    pages = debug_panel_pages(result, pose_detected, values)
    page_index = debug_page % len(pages)
    title, lines = pages[page_index]

    def put(
        text: str,
        y: int,
        color: tuple[int, int, int] = (235, 235, 235),
        scale: float = .40,
    ) -> None:
        while scale > .25:
            width = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1
            )[0][0]
            if width <= PANEL_WIDTH - 24:
                break
            scale -= .02
        cv2.putText(
            panel, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
            scale, color, 1, cv2.LINE_AA,
        )

    put("NON-FORMAL / EXPLORATORY ENGINEERING DEBUG", 24, (0, 210, 255), .50)
    put(title, 50, (100, 220, 100), .48)
    y = 80
    for line in lines:
        put(line, y)
        y += 29
    put(
        f"DEBUG {page_index + 1}/{len(pages)} | [ previous | ] next | q quit",
        PANEL_HEIGHT - 12,
        (0, 210, 255),
        .42,
    )
    return panel


def engineering_panel_diagnostic_lines(
    result: geometry.GeometryResult,
    *,
    face_detected: bool,
    face_matrix: Any,
    face_matrix_values: Mapping[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Format same-frame D455/FaceLandmarker values for the live panel."""

    values = panel_measurement_values(
        result,
        face_detected=face_detected,
        face_matrix=face_matrix,
        face_matrix_values=face_matrix_values,
    )
    nose_depth = _summary_number(
        values["nose_z_m"], " m", "unavailable", signed=False
    )
    return (
        f"Nose Z Depth: {nose_depth}",
        f"FaceLandmarker: {values['face_status']}",
        f"Face Matrix: {values['matrix_status']}",
    )


def draw_engineering_panel(
    image: Any,
    result: geometry.GeometryResult,
    pose_detected: bool,
    *,
    face_detected: bool | None = None,
    face_matrix: Any = None,
    face_matrix_values: Mapping[str, Any] | None = None,
    panel_mode: str = "summary",
    debug_page: int = 0,
) -> Any:
    """Add the summary or paged debug panel to an annotated BGR frame."""

    import cv2

    view_width = round(image.shape[1] * PANEL_HEIGHT / image.shape[0])
    view = cv2.resize(
        image, (view_width, PANEL_HEIGHT), interpolation=cv2.INTER_AREA
    )
    panel = np.full((PANEL_HEIGHT, PANEL_WIDTH, 3), 28, dtype=np.uint8)
    values = panel_measurement_values(
        result,
        face_detected=bool(face_detected),
        face_matrix=face_matrix,
        face_matrix_values=face_matrix_values,
    )
    if panel_mode == "summary":
        panel = _draw_summary_panel(panel, values)
    elif panel_mode == "debug":
        panel = _draw_debug_panel(
            panel, result, pose_detected, values, debug_page
        )
    else:
        raise ValueError(f"unsupported panel mode: {panel_mode!r}")
    return np.hstack((view, panel))


def _open_csv(path: str | None) -> tuple[Any | None, csv.DictWriter | None]:
    if path is None:
        return None, None
    absolute = os.path.abspath(path)
    handle = open(absolute, "x", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="raise")
    writer.writeheader()
    handle.flush()
    print(f"[exploratory CSV] writing non-canonical engineering measurements: {absolute}")
    return handle, writer


def _open_face_diagnostic_csv(
    path: str | None,
) -> tuple[Any | None, csv.DictWriter | None]:
    if path is None:
        return None, None
    absolute = os.path.abspath(path)
    handle = open(absolute, "x", encoding="utf-8", newline="")
    writer = csv.DictWriter(
        handle, fieldnames=FACE_DIAGNOSTIC_FIELDS, extrasaction="raise"
    )
    writer.writeheader()
    handle.flush()
    print(f"[face diagnostic CSV] writing engineering diagnostics: {absolute}")
    return handle, writer


def handle_panel_key(
    key: int, panel_mode: str, debug_page: int
) -> tuple[bool, int]:
    """Return quit state and next debug page without changing other controls."""

    key &= 0xFF
    if key == ord("q"):
        return True, debug_page
    if panel_mode == "debug":
        if key == ord("]"):
            debug_page = (debug_page + 1) % DEBUG_PAGE_COUNT
        elif key == ord("["):
            debug_page = (debug_page - 1) % DEBUG_PAGE_COUNT
    return False, debug_page


def run_probe(
    csv_path: str | None = None,
    *,
    face_diag_csv_path: str | None = None,
    show_3d_views: bool | str = False,
    panel_mode: str = "summary",
    pyvista_view: bool = False,
    pyvista_anchor: str = pyvista_viewer.VIEW_ANCHOR_SHOULDER,
) -> None:
    """Run the live D455/MediaPipe loop.  Hardware dependencies load only here."""

    import cv2
    import mediapipe as mp
    import numpy as np
    import pyrealsense2 as rs
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    import analyze_d455
    import capture_d455

    if pyvista_view:
        # Fail before opening the camera when the optional viewer is absent.
        pyvista_viewer.require_pyvista()

    model_paths = analyze_d455.ensure_models()
    pose_options = vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=model_paths["pose"]),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=analyze_d455.POSE_NUM_POSES,
    )
    face_options = vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=model_paths["mesh"]),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=analyze_d455.FACE_NUM_FACES,
        output_facial_transformation_matrixes=True,
    )

    csv_handle = csv_writer = None
    face_diag_handle = face_diag_writer = None
    pipeline = rs.pipeline()
    profile = None
    pose_landmarker = None
    face_landmarker = None
    pyvista_window = None
    try:
        csv_handle, csv_writer = _open_csv(csv_path)
        face_diag_handle, face_diag_writer = _open_face_diagnostic_csv(
            face_diag_csv_path
        )
        profile = pipeline.start(capture_d455.make_config())
        align = rs.align(rs.stream.color)
        depth_scale_m = profile.get_device().first_depth_sensor().get_depth_scale()
        color_intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        face_landmarker = vision.FaceLandmarker.create_from_options(face_options)
        if pyvista_view:
            pyvista_window = pyvista_viewer.PyVistaPostureViewer(
                anchor_mode=pyvista_anchor
            )
        last_mediapipe_timestamp_ms = -1
        frame_index = 0
        debug_page = 0
        print("[probe] live RGB + aligned depth started; press q in the window to quit")
        print("[probe] diagnostic-only: no posture classification and no production gate changes")

        while True:
            frames = pipeline.wait_for_frames()
            device_timestamp_ms = float(frames.get_timestamp())
            aligned = align.process(frames)
            color_frame = aligned.get_color_frame()
            depth_frame = aligned.get_depth_frame()
            if not color_frame or not depth_frame:
                continue

            bgr = np.asanyarray(color_frame.get_data())
            aligned_depth = np.asanyarray(depth_frame.get_data())
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int(device_timestamp_ms)
            if timestamp_ms <= last_mediapipe_timestamp_ms:
                timestamp_ms = last_mediapipe_timestamp_ms + 1
            last_mediapipe_timestamp_ms = timestamp_ms
            frame_index += 1

            # Both Tasks consume the exact same RGB image and MediaPipe timestamp.
            pose_result, face_result = run_frame_inference(
                pose_landmarker, face_landmarker, mp_image, timestamp_ms
            )
            pose_detected = bool(pose_result.pose_landmarks)
            landmarks = pose_result.pose_landmarks[0] if pose_detected else None
            face_landmarks = (
                face_result.face_landmarks[0] if face_result.face_landmarks else None
            )
            face_matrix = first_face_transformation_matrix(face_result)
            face_matrix_values = _face_matrix_csv_values(face_matrix)
            points = geometry.points_from_pose_landmarks(
                landmarks,
                bgr.shape[1],
                bgr.shape[0],
                aligned_depth=aligned_depth,
                depth_scale_m=depth_scale_m,
            )
            points.update(geometry.points_from_face_landmarks(
                face_landmarks,
                bgr.shape[1],
                bgr.shape[0],
                aligned_depth=aligned_depth,
                depth_scale_m=depth_scale_m,
            ))
            points_3d = deproject_body_points(points, color_intrinsics, rs)
            result = geometry.compute_candidate_geometry(
                points,
                focal_length_px=color_intrinsics.fx,
                points_3d=points_3d,
            )
            overlay = geometry.draw_geometry_overlay(bgr, result)
            display = draw_engineering_panel(
                overlay,
                result,
                pose_detected,
                face_detected=bool(face_result.face_landmarks),
                face_matrix=face_matrix,
                face_matrix_values=face_matrix_values,
                panel_mode=panel_mode,
                debug_page=debug_page,
            )
            cv2.imshow(WINDOW_NAME, display)
            if show_3d_views:
                view_mode = (
                    "side" if show_3d_views is True else str(show_3d_views)
                )
                cv2.imshow(
                    viewer.WINDOW_NAME,
                    viewer.render_selected_views(result, view_mode),
                )
            if pyvista_window is not None and not pyvista_window.update(
                result, face_matrix_values
            ):
                pyvista_window = None
                print("[probe] PyVista window closed; measurement loop continues")

            if csv_writer is not None:
                csv_writer.writerow(exploratory_csv_row(
                    result,
                    pose_detected=pose_detected,
                    device_timestamp_ms=device_timestamp_ms,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    face_matrix=face_matrix,
                ))
                csv_handle.flush()

            if face_diag_writer is not None:
                face_diag_writer.writerow(face_pipeline_diagnostic_row(
                    face_result,
                    frame_index=frame_index,
                    device_timestamp_ms=device_timestamp_ms,
                    mediapipe_timestamp_ms=timestamp_ms,
                    rgb_width=bgr.shape[1],
                    rgb_height=bgr.shape[0],
                    pose_detected=pose_detected,
                ))
                face_diag_handle.flush()

            should_quit, debug_page = handle_panel_key(
                cv2.waitKey(1), panel_mode, debug_page
            )
            if should_quit:
                break
    finally:
        if pose_landmarker is not None:
            pose_landmarker.close()
        if face_landmarker is not None:
            face_landmarker.close()
        if profile is not None:
            pipeline.stop()
        if csv_handle is not None:
            csv_handle.close()
        if face_diag_handle is not None:
            face_diag_handle.close()
        if pyvista_window is not None:
            pyvista_window.close()
        cv2.destroyAllWindows()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_probe(
        args.csv,
        face_diag_csv_path=args.face_diag_csv,
        show_3d_views=args.views,
        panel_mode=args.panel_mode,
        pyvista_view=args.pyvista,
        pyvista_anchor=args.pyvista_anchor,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
