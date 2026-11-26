"""D455 F1-5 plus exploratory 3D live preview; no recording or file output.

Reuse source: feat/rf-loso-prediction-audit at 6fd01b2. f1_features.py and
its tests are unchanged; the input adapter below is copied verbatim from
posture_geometry_probe.py. FEAT-009 authority on that same source branch:
docs/research/F1_FEATURE_CORE_CALCULATION_CONTRACT.md and Decision Log.
The depth-derived geometry remains an engineering display and is not an
approved F2 feature set.  No aggregation, imputation, personal baseline,
classifier or Patch 8 execution is performed.

Run: python -B live_f1_d455.py
Quit: q / Esc / close window. Existing locked face/pose models are required.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import math
from pathlib import Path
import sys
import time
from typing import Any

import f1_features
import posture_3d_viewer
import posture_geometry


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


WINDOW = "D455 F1-5 | LIVE PREVIEW | NO RECORDING"
SIDE_WINDOW = posture_3d_viewer.WINDOW_NAME
POINT_FIELDS = (
    ("F (bbox)", "face_detected", "face_x", "face_y"),
    ("L shoulder", "lsh_valid", "lsh_x", "lsh_y"),
    ("R shoulder", "rsh_valid", "rsh_x", "rsh_y"),
    ("L hip", "left_hip_valid", "left_hip_x_px", "left_hip_y_px"),
    ("R hip", "right_hip_valid", "right_hip_x_px", "right_hip_y_px"),
)


def verified_model_paths(model_dir):
    """Read and verify existing models only; never provision/download files."""
    import analyze_d455 as canonical

    lock = canonical.load_model_lock()
    paths = {}
    for role in ("face", "pose"):
        path = Path(model_dir) / lock[role]["filename"]
        canonical.verify_model_artifact(str(path), lock[role])
        paths[role] = str(path)
    return paths


def feature_lines(result):
    lines = []
    for name in f1_features.F1_5_FEATURE_NAMES:
        value = result.features[name]
        number = "N/A" if value is None else f"{value:+.4f}"
        unit = " rad" if name == "so_beta" else ""
        lines.append(f"{name}: {number}{unit}")
    return lines


def _display_number(value, *, unit=""):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "N/A"
    value = float(value)
    return f"{value:+.2f}{unit}" if math.isfinite(value) else "N/A"


def geometry_lines(result):
    """Format existing exploratory tilt values without making a posture decision."""

    if result is None:
        front_back = lateral = "N/A"
    else:
        front_back = _display_number(
            result.features.get("sagittal_torso_lean_deg"), unit=" deg"
        )
        lateral = _display_number(
            result.features.get("shoulder_tilt_deg"), unit=" deg"
        )
    return [
        "3D GEOMETRY | EXPLORATORY / NOT APPROVED F2",
        f"Front/back torso tilt (+toward camera): {front_back}",
        f"Left/right shoulder tilt (signed image-plane): {lateral}",
        "Current frame only; no personal calibration.",
    ]


def diagnostic_lines(row, result, geometry_result=None):
    lines = ["FEAT-009 | current-frame 2D geometry", "NO RECORDING / NO AGGREGATION",
             "Original RGB; L/R = subject left/right", ""]
    for label, state, x_field, y_field in POINT_FIELDS:
        x, y = row.get(x_field), row.get(y_field)
        if row.get(state) is not True:
            status = "INVALID / MISSING"
        elif x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
            status = "MISSING / NONFINITE"
        else:
            status = "AVAILABLE"
        lines.append(f"{label}: {status}")
    for family in f1_features.F1_FAMILIES:
        lines.append("")
        if result.family_available[family]:
            lines.append(f"{family}: AVAILABLE")
        else:
            lines.append(f"{family}: N/A")
            lines.extend(f"  {reason}" for reason in result.family_reasons[family])
    lines.extend(["", *geometry_lines(geometry_result), "",
                  "Visibility is not an acceptance threshold.",
                  "Preview only; not validated posture classification.", "q / Esc / close window: quit"])
    return lines


def draw_preview(bgr, row, result, *, geometry_result=None, color_missing=False):
    import cv2
    import numpy as np

    height, width = bgr.shape[:2]
    canvas = bgr.copy()
    points = []
    for label, state, x_field, y_field in POINT_FIELDS:
        x, y = row.get(x_field), row.get(y_field)
        drawable = (row.get(state) is True and x is not None and y is not None
                    and math.isfinite(x) and math.isfinite(y)
                    and 0 <= x < width and 0 <= y < height)
        # This is a rendering boundary only, NOT an extra face-validity rule.
        point = (min(width - 1, round(x)), min(height - 1, round(y))) if drawable else None
        points.append(point)
        if point is not None:
            cv2.circle(canvas, point, 6, (0, 230, 255), -1)
            cv2.putText(canvas, label, (point[0] + 8, point[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 230, 255), 1, cv2.LINE_AA)
    for first, second in ((1, 2), (3, 4), (1, 3), (2, 4)):
        if points[first] is not None and points[second] is not None:
            cv2.line(canvas, points[first], points[second], (80, 200, 80), 2)
    # Values are overlaid directly on the RGB image, with reasons beside it.
    for index, line in enumerate(feature_lines(result)):
        position = (12, 28 + index * 27)
        cv2.putText(canvas, line, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(canvas, line, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (255, 255, 255), 1, cv2.LINE_AA)
    lines = diagnostic_lines(row, result, geometry_result)
    if color_missing:
        lines.insert(0, "COLOR FRAME MISSING - no previous values reused")
    panel_height = max(height, len(lines) * 24 + 20)
    output = np.zeros((panel_height, width + 620, 3), dtype=np.uint8)
    output[:height, :width] = canvas
    for index, line in enumerate(lines):
        cv2.putText(output, line, (width + 15, 26 + index * 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)
    return output


def deproject_body_points(points, color_intrinsics, rs_module):
    """Reuse the probe's thin RealSense adapter for current-frame metric XYZ."""

    output = {name: None for name in posture_geometry.EXPLORATORY_POINT_NAMES}
    for name in posture_geometry.EXPLORATORY_POINT_NAMES:
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
            output[name] = posture_geometry.Point3D(x_m, y_m, z_m)
    return output


def current_geometry(
    pose_result,
    bgr,
    aligned_depth,
    depth_scale_m,
    color_intrinsics,
    rs_module,
):
    """Compute the existing threshold-free candidate geometry for one frame."""

    landmarks = _first_pose_landmarks(pose_result)
    points = posture_geometry.points_from_pose_landmarks(
        landmarks,
        bgr.shape[1],
        bgr.shape[0],
        aligned_depth=aligned_depth,
        depth_scale_m=depth_scale_m,
    )
    points_3d = deproject_body_points(points, color_intrinsics, rs_module)
    return posture_geometry.compute_candidate_geometry(
        points,
        focal_length_px=getattr(color_intrinsics, "fx", None),
        points_3d=points_3d,
    )


def preview_loop(
    pipeline,
    face_detector,
    pose_detector,
    *,
    align=None,
    color_intrinsics=None,
    depth_scale_m=None,
    rs_module=None,
):
    """All calculations consume one current unmirrored RGB-D frame; no history."""
    import cv2
    import mediapipe as mp
    import numpy as np

    last_timestamp = -1
    while True:
        frames = pipeline.wait_for_frames(timeout_ms=5000)
        if align is not None:
            frames = align.process(frames)
        color = frames.get_color_frame()
        depth = frames.get_depth_frame() if align is not None else None
        geometry_result = None
        if color:
            bgr = np.asanyarray(color.get_data())
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp = max(time.monotonic_ns() // 1_000_000, last_timestamp + 1)
            last_timestamp = timestamp
            face = face_detector.detect(mp_image)
            pose = pose_detector.detect_for_video(mp_image, timestamp)
            row = f1_frame_input(face, pose, bgr.shape[1], bgr.shape[0])
            if (depth is not None and color_intrinsics is not None
                    and depth_scale_m is not None and rs_module is not None):
                geometry_result = current_geometry(
                    pose,
                    bgr,
                    np.asanyarray(depth.get_data()),
                    depth_scale_m,
                    color_intrinsics,
                    rs_module,
                )
        else:
            bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
            row = f1_frame_input(None, None, 1280, 720)
        result = f1_features.compute_f1_5_frame(row)
        cv2.imshow(WINDOW, draw_preview(
            bgr,
            row,
            result,
            geometry_result=geometry_result,
            color_missing=not bool(color),
        ))
        if geometry_result is not None:
            cv2.imshow(
                SIDE_WINDOW,
                posture_3d_viewer.render_side_avatar_view(geometry_result),
            )
        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
            break
        if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        if (geometry_result is not None
                and cv2.getWindowProperty(SIDE_WINDOW, cv2.WND_PROP_VISIBLE) < 1):
            break


def run_preview(model_dir, serial=None):
    import cv2
    import pyrealsense2 as rs
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    import analyze_d455 as canonical

    paths = verified_model_paths(model_dir)
    devices = [device for device in rs.context().query_devices()
               if "D455" in device.get_info(rs.camera_info.name)
               and (serial is None or device.get_info(rs.camera_info.serial_number) == serial)]
    if len(devices) != 1:
        raise RuntimeError("Expected one D455; connect it, close other camera apps, "
                           "or use --serial to select among multiple D455 devices.")
    config = rs.config()
    config.enable_device(devices[0].get_info(rs.camera_info.serial_number))
    # F1 still uses only color pixels. Depth is consumed only by the separate,
    # explicitly non-F2 exploratory geometry display.
    config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
    face_options = vision.FaceDetectorOptions(
        base_options=mpt.BaseOptions(model_asset_path=paths["face"]),
        min_detection_confidence=canonical.FACE_MIN_DETECTION_CONFIDENCE)
    pose_options = vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=paths["pose"]),
        running_mode=getattr(vision.RunningMode, canonical.LANDMARK_RUNNING_MODE),
        num_poses=canonical.POSE_NUM_POSES)
    with ExitStack() as stack:
        face = stack.enter_context(vision.FaceDetector.create_from_options(face_options))
        pose = stack.enter_context(vision.PoseLandmarker.create_from_options(pose_options))
        pipeline = rs.pipeline()
        profile = pipeline.start(config)
        stack.callback(pipeline.stop)
        align = rs.align(rs.stream.color)
        depth_scale_m = profile.get_device().first_depth_sensor().get_depth_scale()
        color_intrinsics = (
            profile.get_stream(rs.stream.color)
            .as_video_stream_profile()
            .get_intrinsics()
        )
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        stack.callback(cv2.destroyWindow, WINDOW)
        cv2.namedWindow(SIDE_WINDOW, cv2.WINDOW_NORMAL)
        stack.callback(cv2.destroyWindow, SIDE_WINDOW)
        cv2.resizeWindow(WINDOW, 1400, 720)
        cv2.resizeWindow(SIDE_WINDOW, *posture_3d_viewer.DEFAULT_SIDE_VIEW_SIZE)
        print("F1-5 + exploratory 3D preview started. No recording, personal "
              "calibration, or file output. q / Esc to quit.")
        preview_loop(
            pipeline,
            face,
            pose,
            align=align,
            color_intrinsics=color_intrinsics,
            depth_scale_m=depth_scale_m,
            rs_module=rs,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path,
                        default=Path(__file__).resolve().parent / "models",
                        help="Existing locked model directory (read-only; no downloads)")
    parser.add_argument("--serial", help="Select a D455 by serial number")
    args = parser.parse_args(argv)
    try:
        run_preview(args.model_dir, args.serial)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"F1 preview stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
