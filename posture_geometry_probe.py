"""Live, non-formal D455 probe for exploratory posture geometry.

This tool is intentionally outside the production posture-decision path and the
canonical frames schema.  Hip-independent F1-extension/F2 values are explicitly
unapproved exploratory candidates.  By default it performs no posture
classification.  The
opt-in ``--rf-demo-model`` mode shows the separate, unvalidated three-class
F1-5 engineering RF demo (``f1_demo_rf``); it is not the LAB5 or an approved
M0/M1/M2 research classifier and is display only.  Optional CSV output is
explicitly exploratory engineering output and is disabled by default.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
from numbers import Real
import os
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
import uuid
import warnings

import numpy as np

import f1_demo_rf
import f1_features
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
F1_PANEL_HEIGHT = 184

# Pose eyes (2/5), not the FaceLandmarker iris centres used by geometry.
UPPER13_LANDMARK_INDICES = dict(sorted(
    {**geometry.POSE_LANDMARK_INDICES, "left_eye": 2, "right_eye": 5}.items(),
    key=lambda item: item[1],
))
UPPER13_CSV_FIELDS = (
    "frame_index", "device_timestamp_ms", "mediapipe_timestamp_ms",
    "landmark_name", "landmark_index", "x_px", "y_px",
    "visibility", "presence", "coordinate_valid", "depth_m", "depth_valid",
)
UPPER13_SESSION_METADATA_SCHEMA = "upper13-session-metadata/1.0.0"
SESSION_TIMEZONE = timezone(timedelta(hours=9), "Asia/Seoul")
AUTOMATIC_DEVICE_SOURCE = "automatic_device_query"
AUTOMATIC_PROFILE_SOURCE = "automatic_active_profile"
MANUAL_SOURCE = "manual_cli"
UNKNOWN_SOURCE = "unknown"

# Opt-in live F1-5 (FEAT-009) display.  Display only: never written to CSV.
F1_LIVE_TITLE = "F1-5 LIVE — FEAT-009"
F1_LIVE_BANNERS = (
    "CALIBRATION-FREE F1-5 — ENGINEERING ONLY",
    "NO POSTURE CLASSIFICATION",
)
F1_LIVE_RF_DEMO_BANNERS = (
    F1_LIVE_BANNERS[0],
    "F1-5 FEEDS UNVALIDATED RF DEMO BELOW",
)
F1_HIP_DIAGNOSTIC_NOTE = "Hip vis/pres: display only, not validity thresholds"

# Opt-in three-class F1-5 engineering RF demo (f1_demo_rf).  Display only:
# never written to any file, never smoothed, never carried across frames.
RF_DEMO_PANEL_HEIGHT = 112
RF_DEMO_TITLE = "RF POSTURE DEMO — UNVALIDATED"
RF_DEMO_BANNERS = (
    "ENGINEERING RF DEMO — ACCURACY NOT VALIDATED",
    "Not a medical or research-validated posture diagnosis",
)
RF_MODEL_LOADED = "LOADED"
RF_MODEL_NOT_LOADED = "NOT LOADED"
RF_MODEL_INVALID = "INVALID"
RF_PREDICTION_UNAVAILABLE = "PREDICTION UNAVAILABLE"
# Display text for the model-returned label; not a decision rule.
RF_DISPLAY_LABELS = MappingProxyType({
    "upright": "UPRIGHT",
    "forward_head": "FORWARD HEAD",
    "body_forward": "BODY FORWARD",
})
RF_AVAILABLE_REASON = "current-frame F1-5 -> RF model output"
RF_REASON_MAX_CHARS = 120
# Exactly the frames-schema/1.0.0 fields read by f1_features.compute_f1_5_frame.
F1_INPUT_FIELDS = (
    "face_detected",
    "face_x",
    "face_y",
    "lsh_valid",
    "rsh_valid",
    "lsh_x",
    "lsh_y",
    "rsh_x",
    "rsh_y",
    "left_hip_valid",
    "right_hip_valid",
    "left_hip_x_px",
    "left_hip_y_px",
    "right_hip_x_px",
    "right_hip_y_px",
)

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
    *geometry.HIPLESS_F1_CANDIDATE_FEATURE_NAMES,
    *geometry.HIPLESS_F2_CANDIDATE_FEATURE_NAMES,
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
    ("left_eye_3d", "points_3d", "left_eye"),
    ("right_eye_3d", "points_3d", "right_eye"),
    ("left_ear_3d", "points_3d", "left_ear"),
    ("right_ear_3d", "points_3d", "right_ear"),
    ("left_elbow_3d", "points_3d", "left_elbow"),
    ("right_elbow_3d", "points_3d", "right_elbow"),
    ("left_wrist_3d", "points_3d", "left_wrist"),
    ("right_wrist_3d", "points_3d", "right_wrist"),
    ("ear_midpoint_3d", "proxies_3d", "ear_midpoint_3d"),
    ("chin_3d", "points_3d", "chin"),
    (
        "hipless_chest_roi_center_3d",
        "proxies_3d",
        "hipless_chest_roi_center_3d",
    ),
)
POINT_3D_FIELDS = tuple(
    f"{output_name}_{axis}_m"
    for output_name, _, _ in POINT_3D_SOURCES
    for axis in ("x", "y", "z")
)

POINT_2D_SOURCES = (
    ("nose_2d", "points", "nose"),
    ("left_eye_2d", "points", "left_eye"),
    ("right_eye_2d", "points", "right_eye"),
    ("left_ear_2d", "points", "left_ear"),
    ("right_ear_2d", "points", "right_ear"),
    ("chin_2d", "points", "chin"),
    ("ear_midpoint_2d", "proxies", "ear_midpoint"),
    ("eye_midpoint_2d", "proxies", "eye_midpoint"),
    ("hipless_f1_head_center_2d", "proxies", "hipless_f1_head_center"),
    (
        "hipless_chest_roi_center_2d",
        "proxies",
        "hipless_chest_roi_center",
    ),
    ("shoulder_midpoint_2d", "proxies", "shoulder_midpoint"),
    ("hip_midpoint_2d", "proxies", "hip_midpoint"),
    ("exploratory_neck_proxy_2d", "proxies", "exploratory_neck_proxy"),
    (
        "exploratory_upper_chest_proxy_2d",
        "proxies",
        "exploratory_upper_chest_proxy",
    ),
)
POINT_2D_FIELDS = tuple(
    f"{output_name}_{axis}_px"
    for output_name, _, _ in POINT_2D_SOURCES
    for axis in ("x", "y")
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
    ("HIPLESS F1 head center dx / shoulder", "hipless_f1_candidate_head_center_dx_sw", ""),
    ("HIPLESS F1 head center dy / shoulder", "hipless_f1_candidate_head_center_dy_sw", ""),
    ("HIPLESS F1 face axis tilt", "hipless_f1_candidate_face_axis_tilt_deg", " deg"),
    ("HIPLESS F1 ear-eye dy / shoulder", "hipless_f1_candidate_ear_eye_dy_sw", ""),
    ("HIPLESS F1 nose-chin / shoulder", "hipless_f1_candidate_nose_chin_distance_sw", ""),
    ("HIPLESS F2 chest ROI depth", "hipless_f2_candidate_chest_depth_m", " m"),
    ("HIPLESS F2 chest forward / shoulders", "hipless_f2_candidate_chest_forward_from_shoulders_m", " m"),
    ("HIPLESS F2 nose forward / chest", "hipless_f2_candidate_nose_forward_from_chest_m", " m"),
    ("HIPLESS F2 nose forward / chest / shoulder3d", "hipless_f2_candidate_nose_forward_from_chest_sw3d", ""),
)

CSV_FIELDS = (
    "artifact_kind",
    "timestamp_utc",
    "device_timestamp_ms",
    "label",
    "subject",
    "recording_id",
    "segment_id",
    "pose_detected",
    *(f"{name}_landmark_valid" for name in POINT_NAMES),
    *(f"{name}_depth_valid" for name in POINT_NAMES),
    "normalized_nose_available",
    "normalized_ear_midpoint_available",
    "shoulder_width_3d_available",
    "sagittal_torso_lean_available",
    "hipless_chest_roi_defined",
    "hipless_chest_roi_depth_available",
    *POINT_3D_FIELDS,
    *FEATURE_FIELDS,
    *FACE_MATRIX_FIELDS,
    *POINT_2D_FIELDS,
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
        "--subject",
        default=None,
        help="subject identifier written to every --csv frame",
    )
    parser.add_argument(
        "--recording-id",
        default=None,
        help="recording identifier written to every --csv frame",
    )
    parser.add_argument(
        "--upper13-csv",
        metavar="PATH",
        default=None,
        help="write 13 Pose observations per frame to a new exploratory CSV",
    )
    parser.add_argument(
        "--session-meta-json",
        metavar="PATH",
        default=None,
        help=("write a new upper13 session metadata JSON sidecar; requires "
              "--upper13-csv"),
    )
    parser.add_argument(
        "--camera-height-m", type=float, default=None,
        help="manually measured camera height in metres; default: unknown",
    )
    parser.add_argument(
        "--chair-distance-m", type=float, default=None,
        help="manually measured camera-to-chair distance in metres; default: unknown",
    )
    parser.add_argument(
        "--installation-angle-deg", type=float, default=None,
        help="manually measured camera installation angle in degrees; default: unknown",
    )
    parser.add_argument(
        "--lighting", default=None,
        help="manual lighting description; default: unknown",
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
        choices=("none", "side", "debug", "skeleton", "avatar", "all"),
        default=None,
        help=("show exploratory 3D views: 'none' disables only the OpenCV 3D "
              "viewer; bare --views (or 'side') shows the "
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
    parser.add_argument(
        "--f1-live",
        action="store_true",
        help=("also compute and display calibration-free F1-5 (FEAT-009) "
              "from each live frame using the canonical FaceDetector bbox "
              "centre and the same PoseLandmarker result; engineering display "
              "only, no posture classification, no file output"),
    )
    parser.add_argument(
        "--rf-demo-model",
        metavar="PATH",
        default=None,
        help=("also show the UNVALIDATED three-class F1-5 engineering RF demo "
              "prediction from this explicit f1_demo_rf JSON artifact, loaded "
              "and verified once at startup; requires --f1-live; display only, "
              "no file output, not a research or medical classifier"),
    )
    args = parser.parse_args(argv)
    if args.pyvista_anchor != pyvista_viewer.VIEW_ANCHOR_SHOULDER and not args.pyvista:
        parser.error("--pyvista-anchor requires --pyvista")
    if args.rf_demo_model is not None and not args.f1_live:
        parser.error("--rf-demo-model requires --f1-live")
    if args.session_meta_json is not None and args.upper13_csv is None:
        parser.error("--session-meta-json requires --upper13-csv")
    if args.csv is not None:
        if not args.subject or not args.subject.strip():
            parser.error("--csv requires a non-empty --subject")
        if not args.recording_id or not args.recording_id.strip():
            parser.error("--csv requires a non-empty --recording-id")
        args.subject = args.subject.strip()
        args.recording_id = args.recording_id.strip()
    elif args.subject is not None or args.recording_id is not None:
        parser.error("--subject and --recording-id require --csv")
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
    chest = result.proxies.get("hipless_chest_roi_center")
    diagnostics["hipless_chest_roi_defined"] = chest is not None
    diagnostics["hipless_chest_roi_depth_available"] = (
        chest is not None and chest.depth_m is not None
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


def deproject_geometry_point(
    point: geometry.Point | None, color_intrinsics: Any, rs_module: Any
) -> geometry.Point3D | None:
    """Deproject one already-observed aligned-depth point; missing stays missing."""

    if point is None or point.depth_m is None:
        return None
    try:
        xyz = rs_module.rs2_deproject_pixel_to_point(
            color_intrinsics,
            [float(point.x_px), float(point.y_px)],
            float(point.depth_m),
        )
        if len(xyz) != 3:
            return None
        x_m, y_m, z_m = (float(value) for value in xyz)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x_m, y_m, z_m)) or z_m <= 0:
        return None
    return geometry.Point3D(x_m, y_m, z_m)


def _point_3d_csv_values(result: geometry.GeometryResult) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for output_name, collection_name, source_name in POINT_3D_SOURCES:
        collection = getattr(result, collection_name)
        point = collection.get(source_name)
        values[f"{output_name}_x_m"] = point.x_m if point is not None else None
        values[f"{output_name}_y_m"] = point.y_m if point is not None else None
        values[f"{output_name}_z_m"] = point.z_m if point is not None else None
    return values


def _point_2d_csv_values(result: geometry.GeometryResult) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for output_name, collection_name, source_name in POINT_2D_SOURCES:
        collection = getattr(result, collection_name)
        point = collection.get(source_name)
        values[f"{output_name}_x_px"] = point.x_px if point is not None else None
        values[f"{output_name}_y_px"] = point.y_px if point is not None else None
    return values


def exploratory_csv_row(
    result: geometry.GeometryResult,
    *,
    pose_detected: bool,
    device_timestamp_ms: float,
    timestamp_utc: str,
    label: str,
    subject: str,
    recording_id: str,
    segment_id: int,
    face_matrix: Any = None,
) -> dict[str, Any]:
    """Build one explicitly non-canonical engineering row; ``None`` stays blank in CSV."""

    row: dict[str, Any] = {
        "artifact_kind": EXPLORATORY_ARTIFACT_KIND,
        "timestamp_utc": timestamp_utc,
        "device_timestamp_ms": device_timestamp_ms,
        "label": label,
        "subject": subject,
        "recording_id": recording_id,
        "segment_id": segment_id,
    }
    row.update(diagnostics_for(result, pose_detected))
    row.update(_point_3d_csv_values(result))
    row.update({name: result.features.get(name) for name in FEATURE_FIELDS})
    row.update(_face_matrix_csv_values(face_matrix))
    row.update(_point_2d_csv_values(result))
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
        "hipless_chest_roi_defined: "
        + _yes_no(availability["hipless_chest_roi_defined"]),
        "hipless_chest_roi_depth_available: "
        + _yes_no(availability["hipless_chest_roi_depth_available"]),
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


def largest_face_detection(face_detector_result: Any) -> Any | None:
    """Select the FaceDetector detection exactly as analyze_d455 does.

    The largest bounding-box area wins; ``max`` keeps the first on ties.
    """

    detections = getattr(face_detector_result, "detections", None)
    if not detections:
        return None
    return max(
        detections,
        key=lambda detection: (
            detection.bounding_box.width * detection.bounding_box.height
        ),
    )


def _first_pose_landmarks(pose_result: Any) -> Any | None:
    poses = getattr(pose_result, "pose_landmarks", None)
    return poses[0] if poses else None


def _pose_landmark(landmarks: Any, index: int) -> Any | None:
    if landmarks is None or len(landmarks) <= index:
        return None
    return landmarks[index]


def f1_frame_input(
    face_detector_result: Any,
    pose_result: Any,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Build the canonical-compatible F1-5 input fields for one live frame.

    Mirrors analyze_d455 frames-schema/1.0.0 semantics on the original
    (non-mirrored) color image: F is the largest FaceDetector bbox centre in
    pixels; shoulders are Pose 11/12 whose pixel values are kept whenever a
    pose exists while validity comes only from ``landmark_in_frame``; hips are
    Pose 23/24 with pixel values only when in frame.  Unavailable values stay
    ``None``.  No depth, visibility, presence or previous frame is used.
    """

    import analyze_d455 as canonical

    row: dict[str, Any] = dict.fromkeys(F1_INPUT_FIELDS)
    row["face_detected"] = bool(
        getattr(face_detector_result, "detections", None)
    )
    detection = largest_face_detection(face_detector_result)
    if detection is not None:
        box = detection.bounding_box
        row["face_x"] = box.origin_x + box.width / 2
        row["face_y"] = box.origin_y + box.height / 2

    landmarks = _first_pose_landmarks(pose_result)
    for prefix, index in (
        ("lsh", canonical.SHOULDER_L),
        ("rsh", canonical.SHOULDER_R),
    ):
        landmark = _pose_landmark(landmarks, index)
        row[f"{prefix}_valid"] = canonical.landmark_in_frame(landmark)
        if landmark is not None:
            row[f"{prefix}_x"] = landmark.x * image_width
            row[f"{prefix}_y"] = landmark.y * image_height
    for side, index in (("left", canonical.HIP_L), ("right", canonical.HIP_R)):
        landmark = _pose_landmark(landmarks, index)
        valid = canonical.landmark_in_frame(landmark)
        row[f"{side}_hip_valid"] = valid
        if valid:
            row[f"{side}_hip_x_px"] = landmark.x * image_width
            row[f"{side}_hip_y_px"] = landmark.y * image_height
    return row


def hip_display_diagnostics(pose_result: Any) -> dict[str, dict[str, Any]]:
    """Hip visibility/presence for display only; never a validity threshold."""

    import analyze_d455 as canonical

    landmarks = _first_pose_landmarks(pose_result)
    output: dict[str, dict[str, Any]] = {}
    for side, index in (("left", canonical.HIP_L), ("right", canonical.HIP_R)):
        landmark = _pose_landmark(landmarks, index)
        output[side] = {
            "landmark_present": landmark is not None,
            "visibility": _finite_float(getattr(landmark, "visibility", None)),
            "presence": _finite_float(getattr(landmark, "presence", None)),
        }
    return output


@dataclass(frozen=True)
class LiveF1Frame:
    """One live frame's F1-5 input, FEAT-009 result and hip display values."""

    frame: Mapping[str, Any]
    result: f1_features.F1FrameResult
    hip_diagnostics: Mapping[str, Mapping[str, Any]]


def compute_live_f1(
    face_detector_result: Any,
    pose_result: Any,
    image_width: int,
    image_height: int,
) -> LiveF1Frame:
    """Compute F1-5 from the current frame only (no baseline or history)."""

    frame = f1_frame_input(
        face_detector_result, pose_result, image_width, image_height
    )
    return LiveF1Frame(
        frame=MappingProxyType(frame),
        result=f1_features.compute_f1_5_frame(frame),
        hip_diagnostics=MappingProxyType(hip_display_diagnostics(pose_result)),
    )


def _f1_value_text(value: Any) -> str:
    finite = _finite_float(value)
    return "N/A" if finite is None else f"{finite:+.3f}"


def _f1_family_status_text(result: f1_features.F1FrameResult, family: str) -> str:
    if result.family_available.get(family) is True:
        return f"{family} status: AVAILABLE"
    reasons = result.family_reasons.get(family) or ()
    if not reasons:
        return f"{family} status: N/A"
    return f"{family} status: N/A — {', '.join(reasons)}"


def _f1_hip_status_text(live_f1: LiveF1Frame, side: str) -> str:
    diagnostics = live_f1.hip_diagnostics[side]
    if live_f1.frame[f"{side}_hip_valid"] is True:
        state = "IN"
    elif diagnostics["landmark_present"]:
        state = "OUT"
    else:
        state = "OUT (no landmark)"

    def score(value: Any) -> str:
        return "N/A" if value is None else f"{value:.2f}"

    return (
        f"{side.capitalize()} Hip: {state} | "
        f"vis {score(diagnostics['visibility'])} | "
        f"pres {score(diagnostics['presence'])}"
    )


def f1_panel_layout_items(
    live_f1: LiveF1Frame, width: int, *, rf_demo_enabled: bool = False
) -> tuple[tuple[str, int, int, str, tuple[int, int, int], str], ...]:
    """Text items for the F1-5 strip: (text, x, y, font, BGR, anchor).

    ``rf_demo_enabled`` only swaps the second banner so the strip does not
    claim "no classification" above the RF demo strip.
    """

    banners = F1_LIVE_RF_DEMO_BANNERS if rf_demo_enabled else F1_LIVE_BANNERS
    text = (235, 235, 235)
    muted = (170, 170, 170)
    accent = (0, 210, 255)
    good = (100, 220, 100)
    caution = (0, 190, 255)
    result = live_f1.result
    right = width - 16
    y0, step = 64, 23
    items = [
        (F1_LIVE_TITLE, 16, 10, "section", accent, "lt"),
        (banners[0], right, 10, "body", caution, "rt"),
        (banners[1], right, 34, "body", caution, "rt"),
    ]
    for row, name in enumerate(f1_features.F1_5_FEATURE_NAMES):
        unit = f1_features.F1_5_FEATURE_UNITS[name]
        label = f"{name} ({unit})" if unit == "rad" else name
        value = result.features.get(name)
        items.append((
            f"{label}: {_f1_value_text(value)}",
            16, y0 + row * step, "body",
            caution if _finite_float(value) is None else text, "lt",
        ))
    for row, family in enumerate(f1_features.F1_FAMILIES):
        available = result.family_available.get(family) is True
        items.append((
            _f1_family_status_text(result, family),
            260, y0 + row * step, "body",
            good if available else caution, "lt",
        ))
    for row, side in enumerate(("left", "right")):
        inside = live_f1.frame[f"{side}_hip_valid"] is True
        items.append((
            _f1_hip_status_text(live_f1, side),
            right, y0 + row * step, "body",
            good if inside else caution, "rt",
        ))
    items.append((
        F1_HIP_DIAGNOSTIC_NOTE, right, y0 + 2 * step + 4, "small", muted, "rt"
    ))
    return tuple(items)


def draw_f1_live_panel(
    live_f1: LiveF1Frame, width: int, *, rf_demo_enabled: bool = False
) -> np.ndarray:
    """Render the opt-in F1-5 strip shown below the existing display."""

    return _draw_text_strip(
        f1_panel_layout_items(live_f1, width, rf_demo_enabled=rf_demo_enabled),
        F1_PANEL_HEIGHT,
        width,
    )


def _draw_text_strip(
    items: Sequence[tuple[str, int, int, str, tuple[int, int, int], str]],
    height: int,
    width: int,
) -> np.ndarray:
    panel = np.full((height, width, 3), 18, dtype=np.uint8)
    panel[:2, :] = 70
    fonts = _load_korean_fonts()
    if fonts is not None:
        from PIL import Image, ImageDraw

        canvas = Image.fromarray(panel[:, :, ::-1])
        draw = ImageDraw.Draw(canvas)
        for text, x, y, font_key, bgr, anchor in items:
            draw.text(
                (x, y), text, font=fonts[font_key],
                fill=tuple(reversed(bgr)), anchor=anchor,
            )
        return np.asarray(canvas)[:, :, ::-1].copy()

    import cv2

    _warn_font_fallback_once()
    scales = {"section": .50, "body": .43, "small": .31}
    for text, x, y, font_key, color, anchor in items:
        # Hershey fonts are ASCII-only.
        text = text.replace("—", "-")
        scale = scales[font_key]
        (text_width, height), _ = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1
        )
        origin_x = x - text_width if anchor == "rt" else x
        cv2.putText(
            panel, text, (origin_x, y + height), cv2.FONT_HERSHEY_SIMPLEX,
            scale, color, 1, cv2.LINE_AA,
        )
    return panel


@dataclass(frozen=True)
class RFDemoModelState:
    """RF demo artifact state, resolved once at startup.

    ``model`` is the validated ``f1_demo_rf.F1DemoRFModel`` only when
    ``status`` is LOADED; otherwise it is ``None`` and nothing is predicted.
    """

    status: str
    model: Any | None
    artifact_name: str
    detail: str


def load_rf_demo_model(path: str | os.PathLike) -> RFDemoModelState:
    """Load and fully verify the explicit artifact once; fail closed."""

    name = os.path.basename(os.fspath(path)) or os.fspath(path)
    try:
        model = f1_demo_rf.load_f1_demo_model(path)
    except FileNotFoundError:
        return RFDemoModelState(
            RF_MODEL_NOT_LOADED, None, name, f"artifact not found: {name}"
        )
    except f1_demo_rf.ArtifactValidationError as exc:
        return RFDemoModelState(
            RF_MODEL_INVALID, None, name, f"artifact rejected: {exc}"
        )
    except Exception as exc:
        return RFDemoModelState(
            RF_MODEL_INVALID, None, name, f"artifact load failed: {exc}"
        )
    return RFDemoModelState(RF_MODEL_LOADED, model, name, "verified at startup")


@dataclass(frozen=True)
class RFDemoFrame:
    """One frame's RF demo display state; never reused for another frame."""

    model_status: str
    artifact_name: str
    prediction: str
    label: str | None
    reason: str


@dataclass(frozen=True)
class ProbeFrame:
    """One completed probe frame, handed to an optional display callback.

    Every field comes from the same RGB/depth frame: ``rf_demo`` is the
    prediction already shown in the RF strip for this frame (``None`` when the
    RF demo is not enabled), never a previous frame's.  Display only.
    """

    frame_index: int
    device_timestamp_ms: float
    mediapipe_timestamp_ms: int
    result: geometry.GeometryResult
    face_matrix_values: Mapping[str, Any]
    live_f1: LiveF1Frame | None
    rf_demo: RFDemoFrame | None


def _short_reason(reason: str, limit: int = RF_REASON_MAX_CHARS) -> str:
    reason = " ".join(str(reason).split())
    if len(reason) <= limit:
        return reason
    return reason[:limit - 3] + "..."


def _rf_missing_feature_reason(result: f1_features.F1FrameResult) -> str | None:
    missing = [
        name for name in f1_features.F1_5_FEATURE_NAMES
        if _finite_float(result.features.get(name)) is None
    ]
    if not missing:
        return None
    causes = sorted({
        reason
        for family in f1_features.F1_FAMILIES
        for reason in result.family_reasons.get(family, ())
    })
    suffix = f" ({'; '.join(causes)})" if causes else ""
    return f"missing {', '.join(missing)}{suffix}"


def rf_demo_frame(
    state: RFDemoModelState, live_f1: LiveF1Frame
) -> RFDemoFrame:
    """Predict from the current frame's F1-5 only.

    No smoothing, voting, last-valid substitution, imputation or baseline:
    an incomplete frame or unusable model is shown as unavailable.
    """

    def unavailable(reason: str) -> RFDemoFrame:
        return RFDemoFrame(
            state.status, state.artifact_name, RF_PREDICTION_UNAVAILABLE,
            None, _short_reason(reason),
        )

    if state.status != RF_MODEL_LOADED or state.model is None:
        return unavailable(f"MODEL {state.status}: {state.detail}")
    try:
        prediction = state.model.predict(live_f1.result)
    except Exception as exc:
        return unavailable(f"model execution failed: {exc}")
    if prediction.status != f1_demo_rf.PREDICTION_AVAILABLE:
        return unavailable(
            _rf_missing_feature_reason(live_f1.result) or prediction.reason
        )
    display = RF_DISPLAY_LABELS.get(prediction.label)
    if display is None:
        return unavailable(f"unsupported model label: {prediction.label!r}")
    return RFDemoFrame(
        state.status, state.artifact_name, display, prediction.label,
        RF_AVAILABLE_REASON,
    )


def rf_demo_panel_layout_items(
    rf_demo: RFDemoFrame, width: int
) -> tuple[tuple[str, int, int, str, tuple[int, int, int], str], ...]:
    """Text items for the RF demo strip: (text, x, y, font, BGR, anchor)."""

    muted = (170, 170, 170)
    accent = (0, 210, 255)
    good = (100, 220, 100)
    caution = (0, 190, 255)
    bad = (80, 100, 255)
    right = width - 16
    model_color = {
        RF_MODEL_LOADED: good,
        RF_MODEL_NOT_LOADED: caution,
        RF_MODEL_INVALID: bad,
    }.get(rf_demo.model_status, bad)
    available = rf_demo.label is not None
    return (
        (RF_DEMO_TITLE, 16, 10, "section", accent, "lt"),
        (RF_DEMO_BANNERS[0], right, 10, "body", caution, "rt"),
        (RF_DEMO_BANNERS[1], right, 36, "small", muted, "rt"),
        (
            f"Model: {rf_demo.model_status} | {_short_reason(rf_demo.artifact_name, 48)}",
            16, 38, "body", model_color, "lt",
        ),
        (
            f"Prediction: {rf_demo.prediction}",
            16, 62, "section", good if available else caution, "lt",
        ),
        (f"Reason: {rf_demo.reason}", 16, 88, "body", muted, "lt"),
    )


def draw_rf_demo_panel(rf_demo: RFDemoFrame, width: int) -> np.ndarray:
    """Render the opt-in RF demo strip shown below the F1-5 strip."""

    return _draw_text_strip(
        rf_demo_panel_layout_items(rf_demo, width), RF_DEMO_PANEL_HEIGHT, width
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
    live_f1: LiveF1Frame | None = None,
    rf_demo: RFDemoFrame | None = None,
) -> Any:
    """Add the summary or paged debug panel to an annotated BGR frame.

    With ``live_f1`` the opt-in F1-5 strip is appended below, and with
    ``rf_demo`` the opt-in RF demo strip below that; otherwise the display is
    unchanged.
    """

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
    display = np.hstack((view, panel))
    if live_f1 is not None:
        display = np.vstack((
            display,
            draw_f1_live_panel(
                live_f1, display.shape[1], rf_demo_enabled=rf_demo is not None
            ),
        ))
    if rf_demo is not None:
        display = np.vstack((
            display, draw_rf_demo_panel(rf_demo, display.shape[1])
        ))
    return display


def upper13_csv_rows(
    landmarks: Any, image_width: int, image_height: int, *,
    aligned_depth: np.ndarray | None, depth_scale_m: float | None,
    frame_index: int, device_timestamp_ms: float, mediapipe_timestamp_ms: int,
) -> list[dict[str, Any]]:
    """Separate exploratory Pose observations; blanks mean missing, never zero.

    Finite out-of-frame coordinates are retained with coordinate_valid=false.
    Confidence scores are observations, not coordinate/depth thresholds.
    """
    rows = []
    for name, index in UPPER13_LANDMARK_INDICES.items():
        landmark = _pose_landmark(landmarks, index)
        x = _finite_float(getattr(landmark, "x", None))
        y = _finite_float(getattr(landmark, "y", None))
        valid = (image_width > 0 and image_height > 0
                 and x is not None and y is not None
                 and 0 <= x < 1 and 0 <= y < 1)
        x_px = x * image_width if x is not None and image_width > 0 else None
        y_px = y * image_height if y is not None and image_height > 0 else None
        depth = (geometry.sample_aligned_depth_m(
            aligned_depth, x_px, y_px, depth_scale_m
        ) if valid else None)
        rows.append({
            "frame_index": frame_index,
            "device_timestamp_ms": device_timestamp_ms,
            "mediapipe_timestamp_ms": mediapipe_timestamp_ms,
            "landmark_name": name, "landmark_index": index,
            "x_px": x_px, "y_px": y_px,
            "visibility": _finite_float(getattr(landmark, "visibility", None)),
            "presence": _finite_float(getattr(landmark, "presence", None)),
            "coordinate_valid": "true" if valid else "false",
            "depth_m": depth, "depth_valid": "true" if depth is not None else "false",
        })
    return rows


def _open_upper13_csv(path: str | None) -> tuple[Any | None, csv.DictWriter | None]:
    if path is None:
        return None, None
    handle = open(os.path.abspath(path), "x", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=UPPER13_CSV_FIELDS, extrasaction="raise")
    writer.writeheader()
    handle.flush()
    return handle, writer


def _sourced(value: Any, source: str) -> dict[str, Any]:
    return {"value": value, "source": source}


def _manual_session_value(value: Any) -> dict[str, Any]:
    return _sourced(value, MANUAL_SOURCE if value is not None else UNKNOWN_SOURCE)


def _session_id(started_at: datetime) -> str:
    return (f"upper13_{started_at.strftime('%Y%m%d_%H%M%S_%f')}_"
            f"{uuid.uuid4().hex}")


def _profile_details(stream_profile: Any) -> dict[str, Any]:
    video = stream_profile.as_video_stream_profile()
    return {
        "resolution": {"width": int(video.width()), "height": int(video.height())},
        "fps": int(video.fps()),
        "source": AUTOMATIC_PROFILE_SOURCE,
    }


def _intrinsics_details(stream_profile: Any) -> dict[str, Any]:
    intrinsics = stream_profile.as_video_stream_profile().get_intrinsics()
    return _sourced({
        "width": int(intrinsics.width), "height": int(intrinsics.height),
        "fx": float(intrinsics.fx), "fy": float(intrinsics.fy),
        "ppx": float(intrinsics.ppx), "ppy": float(intrinsics.ppy),
        "model": str(intrinsics.model),
        "coeffs": [float(value) for value in intrinsics.coeffs],
    }, AUTOMATIC_PROFILE_SOURCE)


def _device_info(device: Any, key: Any, field: str,
                 unknown_reasons: dict[str, str]) -> dict[str, Any]:
    try:
        if hasattr(device, "supports") and not device.supports(key):
            raise RuntimeError("device information is not supported")
        return _sourced(device.get_info(key), AUTOMATIC_DEVICE_SOURCE)
    except Exception as error:
        unknown_reasons[field] = str(error)
        return _sourced(None, UNKNOWN_SOURCE)


def _sensor_option(sensor: Any, option: Any, field: str,
                   unknown_reasons: dict[str, str]) -> dict[str, Any]:
    try:
        if hasattr(sensor, "supports") and not sensor.supports(option):
            raise RuntimeError("sensor option is not supported")
        return _sourced(float(sensor.get_option(option)), AUTOMATIC_DEVICE_SOURCE)
    except Exception as error:
        unknown_reasons[field] = str(error)
        return _sourced(None, UNKNOWN_SOURCE)


def _depth_scale(sensor: Any, unknown_reasons: dict[str, str]) -> dict[str, Any]:
    try:
        return _sourced(float(sensor.get_depth_scale()), AUTOMATIC_DEVICE_SOURCE)
    except Exception as error:
        unknown_reasons["depth_scale_m"] = str(error)
        return _sourced(None, UNKNOWN_SOURCE)


def build_upper13_session_metadata(
    profile: Any,
    rs_module: Any,
    upper13_csv_path: str,
    *,
    camera_height_m: float | None = None,
    chair_distance_m: float | None = None,
    installation_angle_deg: float | None = None,
    lighting: str | None = None,
    started_at: datetime | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build one non-canonical upper13 session sidecar from the active profile."""

    started_at = started_at or datetime.now(SESSION_TIMEZONE)
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must include a UTC offset")
    started_at = started_at.astimezone(SESSION_TIMEZONE)
    session_id = session_id or _session_id(started_at)
    device = profile.get_device()
    color_profile = profile.get_stream(rs_module.stream.color)
    depth_profile = profile.get_stream(rs_module.stream.depth)
    unknown_reasons: dict[str, str] = {}

    try:
        color_sensor = device.first_color_sensor()
    except Exception as error:
        color_sensor = None
        unknown_reasons["camera_controls.color"] = str(error)
    try:
        depth_sensor = device.first_depth_sensor()
    except Exception as error:
        depth_sensor = None
        unknown_reasons["camera_controls.depth"] = str(error)

    def control(sensor: Any, option: Any, field: str) -> dict[str, Any]:
        if sensor is None:
            unknown_reasons.setdefault(field, "sensor is unavailable")
            return _sourced(None, UNKNOWN_SOURCE)
        return _sensor_option(sensor, option, field, unknown_reasons)

    manual_values = {
        "camera_height_m": camera_height_m,
        "chair_distance_m": chair_distance_m,
        "installation_angle_deg": installation_angle_deg,
        "lighting": lighting,
    }
    for field, value in manual_values.items():
        if value is None:
            unknown_reasons[f"installation.{field}"] = "not provided"

    return {
        "schema_version": UPPER13_SESSION_METADATA_SCHEMA,
        "artifact_kind": "exploratory-upper13-session-metadata",
        "session_id": session_id,
        "session_id_source": "automatic_generated",
        "session_started_at": started_at.isoformat(timespec="microseconds"),
        "session_started_at_source": "automatic_system_clock",
        "metadata_recorded_at": datetime.now(SESSION_TIMEZONE).isoformat(
            timespec="microseconds"
        ),
        "metadata_recorded_at_source": "automatic_system_clock",
        "upper13_csv": {
            "path": os.path.abspath(upper13_csv_path),
            "session_id": session_id,
            "source": "cli_linkage",
        },
        "camera": {
            "model": _device_info(
                device, rs_module.camera_info.name, "camera.model", unknown_reasons
            ),
            "serial": _device_info(
                device, rs_module.camera_info.serial_number, "camera.serial",
                unknown_reasons,
            ),
            "firmware": _device_info(
                device, rs_module.camera_info.firmware_version, "camera.firmware",
                unknown_reasons,
            ),
        },
        "streams": {
            "color": _profile_details(color_profile),
            "depth": _profile_details(depth_profile),
        },
        "intrinsics": {
            "color": _intrinsics_details(color_profile),
            "depth": _intrinsics_details(depth_profile),
        },
        "depth_alignment": {
            "target": "color",
            "source": "automatic_configuration",
        },
        "depth_scale_m": (
            _depth_scale(depth_sensor, unknown_reasons)
            if depth_sensor is not None else _sourced(None, UNKNOWN_SOURCE)
        ),
        "camera_controls": {
            "color": {
                "exposure": control(
                    color_sensor, rs_module.option.exposure,
                    "camera_controls.color.exposure",
                ),
                "gain": control(
                    color_sensor, rs_module.option.gain,
                    "camera_controls.color.gain",
                ),
            },
            "depth": {
                "exposure": control(
                    depth_sensor, rs_module.option.exposure,
                    "camera_controls.depth.exposure",
                ),
                "gain": control(
                    depth_sensor, rs_module.option.gain,
                    "camera_controls.depth.gain",
                ),
            },
        },
        "installation": {
            field: _manual_session_value(value)
            for field, value in manual_values.items()
        },
        "provenance_unknown_reasons": unknown_reasons,
    }


def write_upper13_session_metadata(path: str, metadata: Mapping[str, Any]) -> None:
    """Write a new session sidecar without replacing any existing path."""

    with open(os.path.abspath(path), "x", encoding="utf-8", newline="\n") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


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


CAPTURE_LABEL_KEYS = MappingProxyType({
    ord("1"): "upright",
    ord("2"): "forward_head",
    ord("3"): "lean_back",
    ord("4"): "lean_left",
    ord("5"): "lean_right",
    ord("6"): "lean_forward",
    ord("t"): "TRANSITION",
})


@dataclass(frozen=True)
class CaptureSegment:
    label: str = "PREP"
    segment_id: int = 0


def handle_capture_label_key(key: int, segment: CaptureSegment) -> CaptureSegment:
    """Apply a non-conflicting posture/transition key for subsequent frames."""

    label = CAPTURE_LABEL_KEYS.get(key & 0xFF)
    if label is None or label == segment.label:
        return segment
    return CaptureSegment(label=label, segment_id=segment.segment_id + 1)


def run_probe(
    csv_path: str | None = None,
    *,
    subject: str | None = None,
    recording_id: str | None = None,
    face_diag_csv_path: str | None = None,
    upper13_csv_path: str | None = None,
    session_meta_json_path: str | None = None,
    camera_height_m: float | None = None,
    chair_distance_m: float | None = None,
    installation_angle_deg: float | None = None,
    lighting: str | None = None,
    show_3d_views: bool | str = False,
    panel_mode: str = "summary",
    pyvista_view: bool = False,
    pyvista_anchor: str = pyvista_viewer.VIEW_ANCHOR_SHOULDER,
    f1_live: bool = False,
    rf_demo_model_path: str | None = None,
    frame_callback: Callable[[ProbeFrame], None] | None = None,
) -> None:
    """Run the live D455/MediaPipe loop.  Hardware dependencies load only here.

    ``frame_callback``, when given, receives each completed ``ProbeFrame``
    after the existing windows are drawn (e.g. the browser mesh avatar).
    """

    if rf_demo_model_path is not None and not f1_live:
        raise ValueError("rf_demo_model_path requires f1_live")
    if session_meta_json_path is not None and upper13_csv_path is None:
        raise ValueError("session_meta_json_path requires upper13_csv_path")
    if csv_path is not None and (not subject or not recording_id):
        raise ValueError("csv_path requires subject and recording_id")
    for output_path in (upper13_csv_path, session_meta_json_path):
        if output_path is not None and os.path.lexists(os.path.abspath(output_path)):
            raise FileExistsError(os.path.abspath(output_path))

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

    rf_demo_state = None
    if rf_demo_model_path is not None:
        # Verified once; every frame reuses this same in-memory model.
        rf_demo_state = load_rf_demo_model(rf_demo_model_path)
        print(f"[probe] RF demo model {rf_demo_state.status}: "
              f"{rf_demo_state.artifact_name} ({rf_demo_state.detail})")

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
    face_detector_options = None
    if f1_live:
        # Same locked model and options as analyze_d455 (default IMAGE mode).
        face_detector_options = vision.FaceDetectorOptions(
            base_options=mpt.BaseOptions(model_asset_path=model_paths["face"]),
            min_detection_confidence=analyze_d455.FACE_MIN_DETECTION_CONFIDENCE,
        )

    csv_handle = csv_writer = None
    face_diag_handle = face_diag_writer = None
    upper13_handle = upper13_writer = None
    pipeline = rs.pipeline()
    profile = None
    pose_landmarker = None
    face_landmarker = None
    face_detector = None
    pyvista_window = None
    try:
        csv_handle, csv_writer = _open_csv(csv_path)
        upper13_handle, upper13_writer = _open_upper13_csv(upper13_csv_path)
        face_diag_handle, face_diag_writer = _open_face_diagnostic_csv(
            face_diag_csv_path
        )
        profile = pipeline.start(capture_d455.make_config())
        align = rs.align(rs.stream.color)
        depth_scale_m = profile.get_device().first_depth_sensor().get_depth_scale()
        color_intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        if session_meta_json_path is not None:
            write_upper13_session_metadata(
                session_meta_json_path,
                build_upper13_session_metadata(
                    profile,
                    rs,
                    upper13_csv_path,
                    camera_height_m=camera_height_m,
                    chair_distance_m=chair_distance_m,
                    installation_angle_deg=installation_angle_deg,
                    lighting=lighting,
                ),
            )
        pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        face_landmarker = vision.FaceLandmarker.create_from_options(face_options)
        if face_detector_options is not None:
            face_detector = vision.FaceDetector.create_from_options(
                face_detector_options
            )
        if pyvista_view:
            pyvista_window = pyvista_viewer.PyVistaPostureViewer(
                anchor_mode=pyvista_anchor
            )
        last_mediapipe_timestamp_ms = -1
        frame_index = 0
        debug_page = 0
        capture_segment = CaptureSegment()
        print("[probe] live RGB + aligned depth started; press q in the window to quit")
        if csv_writer is not None:
            print("[probe] labels: 1=upright, 2=forward_head, 3=lean_back, "
                  "4=lean_left, 5=lean_right, 6=lean_forward, t=TRANSITION; "
                  "initial=PREP")
        if rf_demo_state is None:
            print("[probe] diagnostic-only: no posture classification and no production gate changes")
        else:
            print("[probe] ENGINEERING RF DEMO - ACCURACY NOT VALIDATED: "
                  "display only, not written to any file; no production gate changes")
        if face_detector is not None:
            print("[probe] F1-5 live (FEAT-009): calibration-free engineering "
                  "display only; not written to any file")
        print("[probe] HIPLESS F1-extension/F2 candidates: UNAPPROVED EXPLORATORY; "
              "debug display and optional engineering CSV only")

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
            if upper13_writer is not None:
                upper13_writer.writerows(upper13_csv_rows(
                    landmarks, bgr.shape[1], bgr.shape[0],
                    aligned_depth=aligned_depth, depth_scale_m=depth_scale_m,
                    frame_index=frame_index, device_timestamp_ms=device_timestamp_ms,
                    mediapipe_timestamp_ms=timestamp_ms,
                ))
                upper13_handle.flush()
            face_landmarks = (
                face_result.face_landmarks[0] if face_result.face_landmarks else None
            )
            face_matrix = first_face_transformation_matrix(face_result)
            face_matrix_values = _face_matrix_csv_values(face_matrix)
            live_f1 = None
            rf_demo = None
            if face_detector is not None:
                # IMAGE-mode FaceDetector on the same RGB image; the Pose
                # result above is reused rather than inferred again.
                live_f1 = compute_live_f1(
                    face_detector.detect(mp_image),
                    pose_result,
                    bgr.shape[1],
                    bgr.shape[0],
                )
                if rf_demo_state is not None:
                    # Same F1-5 result as the F1 strip; no extra inference.
                    rf_demo = rf_demo_frame(rf_demo_state, live_f1)
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
            chest_roi_point = geometry.sample_hipless_chest_roi(
                points.get("left_shoulder"),
                points.get("right_shoulder"),
                aligned_depth,
                depth_scale_m,
            )
            points_3d = deproject_body_points(points, color_intrinsics, rs)
            chest_roi_point_3d = deproject_geometry_point(
                chest_roi_point, color_intrinsics, rs
            )
            result = geometry.compute_candidate_geometry(
                points,
                focal_length_px=color_intrinsics.fx,
                points_3d=points_3d,
                chest_roi_point=chest_roi_point,
                chest_roi_point_3d=chest_roi_point_3d,
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
                live_f1=live_f1,
                rf_demo=rf_demo,
            )
            cv2.imshow(WINDOW_NAME, display)
            if show_3d_views and show_3d_views != "none":
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
            if frame_callback is not None:
                frame_callback(ProbeFrame(
                    frame_index=frame_index,
                    device_timestamp_ms=device_timestamp_ms,
                    mediapipe_timestamp_ms=timestamp_ms,
                    result=result,
                    face_matrix_values=MappingProxyType(dict(face_matrix_values)),
                    live_f1=live_f1,
                    rf_demo=rf_demo,
                ))

            if csv_writer is not None:
                csv_writer.writerow(exploratory_csv_row(
                    result,
                    pose_detected=pose_detected,
                    device_timestamp_ms=device_timestamp_ms,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    label=capture_segment.label,
                    subject=subject,
                    recording_id=recording_id,
                    segment_id=capture_segment.segment_id,
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

            key = cv2.waitKey(1)
            next_segment = handle_capture_label_key(key, capture_segment)
            if next_segment != capture_segment:
                capture_segment = next_segment
                print(f"[probe] segment {capture_segment.segment_id}: "
                      f"{capture_segment.label}")
            should_quit, debug_page = handle_panel_key(key, panel_mode, debug_page)
            if should_quit:
                break
    finally:
        if pose_landmarker is not None:
            pose_landmarker.close()
        if face_landmarker is not None:
            face_landmarker.close()
        if face_detector is not None:
            face_detector.close()
        if profile is not None:
            pipeline.stop()
        if csv_handle is not None:
            csv_handle.close()
        if face_diag_handle is not None:
            face_diag_handle.close()
        if upper13_handle is not None:
            upper13_handle.close()
        if pyvista_window is not None:
            pyvista_window.close()
        cv2.destroyAllWindows()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_probe(
        args.csv,
        subject=args.subject,
        recording_id=args.recording_id,
        face_diag_csv_path=args.face_diag_csv,
        upper13_csv_path=args.upper13_csv,
        session_meta_json_path=args.session_meta_json,
        camera_height_m=args.camera_height_m,
        chair_distance_m=args.chair_distance_m,
        installation_angle_deg=args.installation_angle_deg,
        lighting=args.lighting,
        show_3d_views=args.views,
        panel_mode=args.panel_mode,
        pyvista_view=args.pyvista,
        pyvista_anchor=args.pyvista_anchor,
        f1_live=args.f1_live,
        rf_demo_model_path=args.rf_demo_model,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
