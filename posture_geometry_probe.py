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
import posture_3d_viewer as viewer


WINDOW_NAME = "Exploratory D455 posture geometry probe"
EXPLORATORY_ARTIFACT_KIND = "exploratory-posture-geometry-engineering-measurement"

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
    return row


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def draw_engineering_panel(image: Any, result: geometry.GeometryResult, pose_detected: bool) -> Any:
    """Add a compact diagnostic panel to an already annotated BGR frame."""

    import cv2
    import numpy as np

    target_height = 760
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
    put("3D shoulder width available: " + _yes_no(diagnostics["shoulder_width_3d_available"]), y + 105)
    put("sagittal torso lean available: " + _yes_no(diagnostics["sagittal_torso_lean_available"]), y + 126)
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


def run_probe(
    csv_path: str | None = None, *, show_3d_views: bool | str = False
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
    )

    csv_handle, csv_writer = _open_csv(csv_path)
    pipeline = rs.pipeline()
    profile = None
    pose_landmarker = None
    face_landmarker = None
    try:
        profile = pipeline.start(capture_d455.make_config())
        align = rs.align(rs.stream.color)
        depth_scale_m = profile.get_device().first_depth_sensor().get_depth_scale()
        color_intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        face_landmarker = vision.FaceLandmarker.create_from_options(face_options)
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

            # Both Tasks consume the exact same RGB image and MediaPipe timestamp.
            pose_result = pose_landmarker.detect_for_video(mp_image, timestamp_ms)
            face_result = face_landmarker.detect_for_video(mp_image, timestamp_ms)
            pose_detected = bool(pose_result.pose_landmarks)
            landmarks = pose_result.pose_landmarks[0] if pose_detected else None
            face_landmarks = (
                face_result.face_landmarks[0] if face_result.face_landmarks else None
            )
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
            display = draw_engineering_panel(overlay, result, pose_detected)
            cv2.imshow(WINDOW_NAME, display)
            if show_3d_views:
                view_mode = (
                    "side" if show_3d_views is True else str(show_3d_views)
                )
                cv2.imshow(
                    viewer.WINDOW_NAME,
                    viewer.render_selected_views(result, view_mode),
                )

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
        if pose_landmarker is not None:
            pose_landmarker.close()
        if face_landmarker is not None:
            face_landmarker.close()
        if profile is not None:
            pipeline.stop()
        if csv_handle is not None:
            csv_handle.close()
        cv2.destroyAllWindows()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_probe(args.csv, show_3d_views=args.views)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
