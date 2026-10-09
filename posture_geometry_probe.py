"""Live, non-formal D455 probe for exploratory posture geometry.

This tool is intentionally outside the production posture-decision path and the
canonical frames schema.  It performs no posture classification.  Optional CSV
output is explicitly exploratory engineering output and is disabled by default.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import math
from numbers import Real
import os
from typing import Any, Sequence

import posture_geometry as geometry


WINDOW_NAME = "Exploratory D455 posture geometry probe"
EXPLORATORY_ARTIFACT_KIND = "exploratory-posture-geometry-engineering-measurement"

POINT_NAMES = tuple(geometry.POSE_LANDMARK_INDICES)
FEATURE_FIELDS = (
    "head_lateral_tilt_deg",
    "shoulder_tilt_deg",
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
)

FEATURE_DISPLAY = (
    ("head tilt", "head_lateral_tilt_deg", " deg"),
    ("shoulder tilt", "shoulder_tilt_deg", " deg"),
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
    *FEATURE_FIELDS,
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
    return parser.parse_args(argv)


def format_feature(value: Any, unit: str = "") -> str:
    """Format a live value without converting missing/invalid data into a number."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return "unavailable"
    value = float(value)
    if not math.isfinite(value):
        return "unavailable"
    return f"{value:+.3f}{unit}"


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
    return diagnostics


def exploratory_csv_row(
    result: geometry.GeometryResult,
    *,
    pose_detected: bool,
    device_timestamp_ms: float,
    timestamp_utc: str,
) -> dict[str, Any]:
    """Build one explicitly non-canonical engineering row; ``None`` stays blank in CSV."""

    row: dict[str, Any] = {
        "artifact_kind": EXPLORATORY_ARTIFACT_KIND,
        "timestamp_utc": timestamp_utc,
        "device_timestamp_ms": device_timestamp_ms,
    }
    row.update(diagnostics_for(result, pose_detected))
    row.update({name: result.features.get(name) for name in FEATURE_FIELDS})
    return row


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def draw_engineering_panel(image: Any, result: geometry.GeometryResult, pose_detected: bool) -> Any:
    """Add a compact diagnostic panel to an already annotated BGR frame."""

    import cv2
    import numpy as np

    target_height = 680
    view_width = round(image.shape[1] * target_height / image.shape[0])
    view = cv2.resize(image, (view_width, target_height), interpolation=cv2.INTER_AREA)
    panel_width = 560
    panel = np.full((target_height, panel_width, 3), 28, dtype=np.uint8)
    diagnostics = diagnostics_for(result, pose_detected)

    def put(text: str, y: int, color: tuple[int, int, int] = (235, 235, 235), scale: float = .43) -> None:
        cv2.putText(panel, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    color, 1, cv2.LINE_AA)

    put("NON-FORMAL / EXPLORATORY ENGINEERING VIEW", 22, (0, 210, 255), .48)
    put("No posture classification or canonical data", 43, (175, 175, 175), .40)
    put("Candidate features", 70, (100, 220, 100), .47)
    y = 92
    for label, key, unit in FEATURE_DISPLAY:
        put(f"{label}: {format_feature(result.features.get(key), unit)}", y)
        y += 21

    put("Diagnostics", y + 5, (100, 220, 100), .47)
    y += 28
    landmark_bits = "  ".join(
        f"{name.replace('_', ' ')}={_yes_no(diagnostics[f'{name}_landmark_valid'])}"
        for name in POINT_NAMES
    )
    depth_bits = "  ".join(
        f"{name.replace('_', ' ')}={_yes_no(diagnostics[f'{name}_depth_valid'])}"
        for name in POINT_NAMES
    )
    put(f"pose landmarks: {_yes_no(diagnostics['pose_detected'])}", y)
    put("landmarks: " + landmark_bits, y + 21, scale=.35)
    put("depths: " + depth_bits, y + 42, scale=.35)
    put("normalized nose available: " + _yes_no(diagnostics["normalized_nose_available"]), y + 63)
    put("normalized ear-mid available: " + _yes_no(diagnostics["normalized_ear_midpoint_available"]), y + 84)
    put("q = quit", target_height - 12, (0, 210, 255), .45)
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


def run_probe(csv_path: str | None = None) -> None:
    """Run the live D455/MediaPipe loop.  Hardware dependencies load only here."""

    import cv2
    import mediapipe as mp
    import numpy as np
    import pyrealsense2 as rs
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    import analyze_d455
    import capture_d455

    model_path = analyze_d455.ensure_models()["pose"]
    options = vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=analyze_d455.POSE_NUM_POSES,
    )

    csv_handle, csv_writer = _open_csv(csv_path)
    pipeline = rs.pipeline()
    profile = None
    landmarker = None
    try:
        profile = pipeline.start(capture_d455.make_config())
        align = rs.align(rs.stream.color)
        depth_scale_m = profile.get_device().first_depth_sensor().get_depth_scale()
        color_intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        landmarker = vision.PoseLandmarker.create_from_options(options)
        last_mediapipe_timestamp_ms = -1
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

            pose_result = landmarker.detect_for_video(mp_image, timestamp_ms)
            pose_detected = bool(pose_result.pose_landmarks)
            landmarks = pose_result.pose_landmarks[0] if pose_detected else None
            overlay, result = geometry.overlay_pose_frame(
                bgr,
                landmarks,
                aligned_depth=aligned_depth,
                depth_scale_m=depth_scale_m,
                focal_length_px=color_intrinsics.fx,
            )
            display = draw_engineering_panel(overlay, result, pose_detected)
            cv2.imshow(WINDOW_NAME, display)

            if csv_writer is not None:
                csv_writer.writerow(exploratory_csv_row(
                    result,
                    pose_detected=pose_detected,
                    device_timestamp_ms=device_timestamp_ms,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                ))
                csv_handle.flush()

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        if landmarker is not None:
            landmarker.close()
        if profile is not None:
            pipeline.stop()
        if csv_handle is not None:
            csv_handle.close()
        cv2.destroyAllWindows()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_probe(args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
