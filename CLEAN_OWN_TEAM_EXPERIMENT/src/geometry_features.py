from __future__ import annotations
import math
from typing import Any
import posture_geometry as geometry

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

def frame_geometry(landmarks, face_landmarks, bgr, aligned_depth, depth_scale_m, color_intrinsics, rs):
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
    return result
