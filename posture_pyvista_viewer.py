"""Optional PyVista front/side views of the exploratory upper-body avatar.

This is a display-only layer over :mod:`posture_3d_viewer`.  It consumes a
:class:`posture_geometry.GeometryResult` and, optionally, the per-frame face
matrix values already produced by ``posture_geometry_probe`` (the same
``face_matrix_*`` values shown in the panel and written to the engineering
CSV).  It performs no depth sampling, deprojection, smoothing, calibration,
neutral-offset removal, posture classification, or file output.

PyVista (with VTK) is an optional dependency listed in
``requirements-viewer.txt``.  This module imports without it; PyVista is only
imported when a window is created.

RealSense camera coordinates are used: +X image-right, +Y image-down, +Z away
from the camera.  The front view looks from the camera along +Z with screen-up
-Y, so it matches the unmirrored D455 colour image (screen-right is +X).  The
side view looks along -X with screen-up -Y, so screen-left is toward the
camera, as in :func:`posture_3d_viewer.side_view_project`.  Both views use
parallel projection, a fixed display scale, and the measured shoulder
midpoint as focal point (else the hip midpoint, else the nose).

View anchor: by default (``shoulder``) the focal point follows that measured
anchor every frame, so on-screen motion is relative to the shoulders; a still
head appears to move when only the shoulders move.  The optional ``camera``
mode is never locked automatically (a start-up frame may carry transient
depth): it follows the same anchor until the user presses L in the PyVista
window, then locks at the next frame's measured shoulder midpoint and keeps
it fixed in RealSense camera coordinates, so on-screen motion is the measured
camera-space motion.  L again re-locks.  The status line says which state is
shown.  Either mode changes only the display camera; no primitive,
measurement, or reference value depends on it.

Neck: the measured shoulder-midpoint -> ear-midpoint relation is drawn as a
thin cyan diagnostic line, unchanged.  The shaded neck is a display-only
tapered tube from that measured shoulder midpoint to a fixed point inside the
lower back of the drawn head (in the head's own axes), so it follows head
translation and yaw/pitch/roll.  It is a visual approximation, not a measured
or estimated cervical joint, and no measured coordinate is moved.  It is drawn
only while the head axes come from a valid face matrix; with the landmark
fallback axes it is hidden (the cyan measured line remains).

Head orientation: when a valid face matrix orientation is supplied, the head
ellipsoid keeps its landmark-derived position and size and takes its axes from
the matrix angles.  The angles are recomposed with the probe's documented
convention ``R = Rz(roll) @ Ry(yaw) @ Rx(-pitch)`` in MediaPipe face space
(+X image-right, +Y image-up, +Z toward the camera) and converted to RealSense
axes with ``diag(1, -1, -1)``.  Positive yaw therefore turns the face toward
image-right, positive pitch toward image-up, and positive roll rotates the
face's +X axis counter-clockwise in the front view.  Without a valid matrix
the existing landmark-derived head axes are shown and labelled as such.  All
angles are camera-relative exploratory values, not anatomical angles.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from numbers import Real
from typing import Any, Mapping

import numpy as np

import posture_3d_viewer as viewer
import posture_geometry as geometry


WINDOW_TITLE = "Exploratory upper-body PyVista views"
DEFAULT_WINDOW_SIZE = (1280, 720)
INSTALL_HINT = "python -m pip install -r requirements-viewer.txt"

FACE_MATRIX_VALID_FIELD = "face_matrix_valid"
FACE_MATRIX_ANGLE_FIELDS = (
    "face_matrix_pitch_deg",
    "face_matrix_yaw_deg",
    "face_matrix_roll_deg",
)

HEAD_SOURCE_FACE_MATRIX = "face_matrix"
HEAD_SOURCE_LANDMARKS = "landmarks"
HEAD_SOURCE_UNAVAILABLE = "unavailable"

VIEW_ANCHOR_SHOULDER = "shoulder"  # focal point follows the measured anchor
VIEW_ANCHOR_CAMERA = "camera"      # focal point locked once, fixed in camera space
VIEW_ANCHOR_MODES = (VIEW_ANCHOR_SHOULDER, VIEW_ANCHOR_CAMERA)
VIEW_ANCHOR_LINES = {
    VIEW_ANCHOR_SHOULDER: "view centre follows shoulder midpoint: motion shown is relative to shoulders",
    VIEW_ANCHOR_CAMERA: "view centre fixed in camera coordinates: motion shown is camera-space motion",
}
# Free in PyVista's default keys, the VTK interactor style and the probe's
# OpenCV keys (q, [, ]).
CAMERA_LOCK_KEYS = ("l", "L")
CAMERA_UNLOCKED_LINE = (
    "camera view NOT LOCKED: centre follows shoulder midpoint; press L in this window to lock"
)
CAMERA_LOCK_WAITING_LINE = "camera lock requested: waiting for both measured shoulders"
CAMERA_LOCKED_LINE = f"LOCKED: {VIEW_ANCHOR_LINES[VIEW_ANCHOR_CAMERA]}; L re-locks"

# MediaPipe face space -> RealSense camera space: +Y and +Z are reversed.
MEDIAPIPE_TO_REALSENSE = np.diag((1.0, -1.0, -1.0))

FRONT_VIEW_DIRECTION = (0.0, 0.0, 1.0)   # from the D455 toward the subject
SIDE_VIEW_DIRECTION = (-1.0, 0.0, 0.0)   # from image-right toward image-left
VIEW_UP = (0.0, -1.0, 0.0)

# Display-only constants; none of them is a measurement or posture threshold.
VIEW_HALF_HEIGHT_M = .65
CAMERA_DISTANCE_M = 3.0
HEAD_ARROW_LENGTH_FACTOR = 2.0  # multiples of the head's forward radius
MESH_RESOLUTION = 12  # tube sides / sphere segments; display cost only

# Display neck shape.  The top sits inside the head ellipsoid at fixed
# fractions of the head's own radii (down along -vertical, back along
# -forward), so it moves and turns with the drawn head; the radii are
# fractions of the head's lateral radius.  Visual approximation only: no
# cervical joint is measured or estimated.
NECK_TOP_DOWN_FACTOR = .55
NECK_TOP_BACK_FACTOR = .35
NECK_TOP_RADIUS_FACTOR = .55
NECK_BASE_RADIUS_FACTOR = .70

# RGB versions of the OpenCV avatar colours in posture_3d_viewer.
BACKGROUND_COLOR = "#181818"
TEXT_COLOR = "#e6e6e6"
TORSO_COLOR = "#af9669"
TORSO_EDGE_COLOR = "#d7cdb4"
HEAD_COLOR = "#d7b473"
GUIDE_COLOR = "#8c8c8c"
CAPSULE_COLORS = {
    "left_upper_arm": "#e1963c",
    "left_forearm": "#f0af46",
    "right_upper_arm": "#4691e1",
    "right_forearm": "#50a5f0",
    "neck": "#cdbeaa",
    "pelvis": "#be5f9b",
}
MEASURED_LINE_COLOR = "#00e5ff"
MESH_NOTE = "cyan line: measured shoulder->ear midpoints; meshes are display shapes"
NECK_STATUS_LINES = {
    HEAD_SOURCE_FACE_MATRIX: "neck mesh: shown (face matrix valid)",
    HEAD_SOURCE_LANDMARKS: "neck mesh: HIDDEN (face matrix unavailable); cyan line still measured",
    HEAD_SOURCE_UNAVAILABLE: "neck mesh: hidden (no measured head)",
}
HEAD_ARROW_COLORS = {
    HEAD_SOURCE_FACE_MATRIX: "#39ff6a",
    HEAD_SOURCE_LANDMARKS: "#ff4fd8",
}

# AvatarTorso vertices: front (LS, RS, RH, LH) then back in the same order.
TORSO_FACES = (
    (0, 1, 2, 3),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (3, 2, 6, 7),
    (0, 3, 7, 4),
    (1, 2, 6, 5),
)

Vector3D = viewer.Vector3D


@dataclass(frozen=True)
class FaceMatrixOrientation:
    """Camera-relative exploratory angles from the probe's face matrix."""

    pitch_deg: float
    yaw_deg: float
    roll_deg: float


@dataclass(frozen=True)
class ViewCamera:
    """Parallel-projection camera aimed at one measured anchor point."""

    name: str
    position: Vector3D
    focal_point: Vector3D
    view_up: Vector3D

    def screen_axes(self) -> tuple[Vector3D, Vector3D]:
        """Return the world directions of screen-right and screen-up."""

        direction = np.subtract(self.focal_point, self.position).astype(float)
        direction /= np.linalg.norm(direction)
        up = np.asarray(self.view_up, dtype=float)
        right = np.cross(direction, up)
        return (
            tuple(float(value) for value in right),  # type: ignore[return-value]
            tuple(float(value) for value in up),
        )


@dataclass(frozen=True)
class GuideLine:
    """Display-only camera-vertical reference starting at a measured point."""

    name: str
    start: geometry.Point3D
    end: geometry.Point3D


@dataclass(frozen=True)
class DisplayNeck:
    """Tapered display neck from the torso top to inside the drawn head.

    ``base`` is the measured shoulder midpoint (the measured neck capsule's
    lower end).  ``top`` is a fixed point inside the head ellipsoid in the
    head's own axes.  It is a visual approximation, not a cervical joint.
    """

    base: geometry.Point3D
    top: geometry.Point3D
    base_radius_m: float
    top_radius_m: float


@dataclass(frozen=True)
class PostureScene:
    """Everything one PyVista frame draws, without any PyVista objects.

    ``primitives.neck`` keeps the measured shoulder->ear relation (drawn as a
    thin diagnostic line); ``display_neck`` is the shaded neck mesh.
    """

    primitives: viewer.AvatarPrimitives
    display_neck: DisplayNeck | None
    head_source: str
    face_orientation: FaceMatrixOrientation | None
    anchor: geometry.Point3D | None
    guides: tuple[GuideLine, ...]
    front_lines: tuple[str, ...]
    side_lines: tuple[str, ...]


def _finite_real(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def face_matrix_orientation(values: Any) -> FaceMatrixOrientation | None:
    """Accept only an explicitly valid matrix with three finite angles."""

    if not isinstance(values, Mapping) or values.get(FACE_MATRIX_VALID_FIELD) is not True:
        return None
    angles = tuple(_finite_real(values.get(name)) for name in FACE_MATRIX_ANGLE_FIELDS)
    if any(angle is None for angle in angles):
        return None
    return FaceMatrixOrientation(*angles)  # type: ignore[arg-type]


def face_matrix_head_axes(
    orientation: FaceMatrixOrientation,
) -> tuple[Vector3D, Vector3D, Vector3D]:
    """Return head (lateral, vertical, forward) unit axes in RealSense space.

    The axes are the face's +X, +Y and +Z directions, matching the
    landmark-derived ``AvatarEllipsoid`` axes: lateral points toward the left
    ear, vertical toward the top of the head, forward out of the face.
    """

    pitch, yaw, roll = (math.radians(value) for value in (
        orientation.pitch_deg, orientation.yaw_deg, orientation.roll_deg
    ))
    pitch_rotation = np.array((
        (1.0, 0.0, 0.0),
        (0.0, math.cos(pitch), math.sin(pitch)),
        (0.0, -math.sin(pitch), math.cos(pitch)),
    ))
    yaw_rotation = np.array((
        (math.cos(yaw), 0.0, math.sin(yaw)),
        (0.0, 1.0, 0.0),
        (-math.sin(yaw), 0.0, math.cos(yaw)),
    ))
    roll_rotation = np.array((
        (math.cos(roll), -math.sin(roll), 0.0),
        (math.sin(roll), math.cos(roll), 0.0),
        (0.0, 0.0, 1.0),
    ))
    rotation = MEDIAPIPE_TO_REALSENSE @ roll_rotation @ yaw_rotation @ pitch_rotation
    return tuple(  # type: ignore[return-value]
        tuple(float(value) for value in rotation[:, index]) for index in range(3)
    )


def orient_head(
    primitives: viewer.AvatarPrimitives,
    orientation: FaceMatrixOrientation | None,
) -> tuple[viewer.AvatarPrimitives, str]:
    """Replace only the head axes when a valid matrix orientation exists.

    The head position and size stay landmark-derived.  Without a measured
    head primitive nothing is drawn, even if the matrix itself is valid.
    """

    if primitives.head is None:
        return primitives, HEAD_SOURCE_UNAVAILABLE
    if orientation is None:
        return primitives, HEAD_SOURCE_LANDMARKS
    lateral, vertical, forward = face_matrix_head_axes(orientation)
    head = replace(
        primitives.head,
        lateral_axis=lateral,
        vertical_axis=vertical,
        forward_axis=forward,
    )
    return replace(primitives, head=head), HEAD_SOURCE_FACE_MATRIX


def display_neck(primitives: viewer.AvatarPrimitives) -> DisplayNeck | None:
    """Join the measured torso-top anchor to the underside of the drawn head.

    Uses the head as drawn (after any face-matrix orientation), so the neck
    top follows head translation and yaw/pitch/roll.  Nothing is drawn when
    either the head or the measured neck capsule is unavailable.
    """

    head, measured = primitives.head, primitives.neck
    if head is None or measured is None:
        return None
    lateral_radius, vertical_radius, forward_radius = head.radii_m
    down = NECK_TOP_DOWN_FACTOR * vertical_radius
    back = NECK_TOP_BACK_FACTOR * forward_radius
    top = geometry.Point3D(*(
        float(centre) - down * vertical - back * forward
        for centre, vertical, forward in zip(
            _xyz(head.center), head.vertical_axis, head.forward_axis
        )
    ))
    base_radius = NECK_BASE_RADIUS_FACTOR * lateral_radius
    if primitives.torso is not None:
        # Keep the neck root within the drawn torso's front/back faces.
        base_radius = min(base_radius, primitives.torso.half_depth_m)
    return DisplayNeck(
        base=measured.end,
        top=top,
        base_radius_m=base_radius,
        top_radius_m=min(NECK_TOP_RADIUS_FACTOR * lateral_radius, base_radius),
    )


def _midpoint(
    a: geometry.Point3D | None, b: geometry.Point3D | None
) -> geometry.Point3D | None:
    if a is None or b is None:
        return None
    return geometry.Point3D(
        (float(a.x_m) + float(b.x_m)) / 2,
        (float(a.y_m) + float(b.y_m)) / 2,
        (float(a.z_m) + float(b.z_m)) / 2,
    )


def _measured_references(
    result: geometry.GeometryResult,
) -> tuple[geometry.Point3D | None, geometry.Point3D | None, geometry.Point3D | None]:
    joints = viewer.joint_positions_3d(result)
    return (
        _midpoint(joints["left_shoulder"], joints["right_shoulder"]),
        _midpoint(joints["left_hip"], joints["right_hip"]),
        joints["nose"],
    )


def scene_anchor(result: geometry.GeometryResult) -> geometry.Point3D | None:
    """Return the views' focal point: shoulder midpoint, hip midpoint, or nose."""

    shoulder, hip, nose = _measured_references(result)
    for point in (shoulder, hip, nose):
        if point is not None:
            return point
    return None


def camera_lock_point(result: geometry.GeometryResult) -> geometry.Point3D | None:
    """Return the point a camera-view lock uses: the measured shoulder midpoint.

    Unlike :func:`scene_anchor` there is no hip or nose fallback, so a lock
    is only taken while both shoulders are measured.
    """

    return _measured_references(result)[0]


def view_anchor(
    mode: str,
    measured: geometry.Point3D | None,
    locked: geometry.Point3D | None,
) -> tuple[geometry.Point3D | None, geometry.Point3D | None]:
    """Return ``(focal point for this frame, locked point to keep)``.

    ``shoulder`` uses this frame's measured anchor.  ``camera`` uses the
    locked point once the user has locked it (see
    :class:`PyVistaPostureViewer`) and follows this frame's measured anchor
    until then; nothing is locked automatically.  Display camera only.
    """

    if mode == VIEW_ANCHOR_SHOULDER:
        return measured, locked
    if mode == VIEW_ANCHOR_CAMERA:
        return (measured if locked is None else locked), locked
    raise ValueError(f"unknown view anchor mode {mode!r}; expected one of {VIEW_ANCHOR_MODES}")


def anchor_status_line(
    mode: str, locked: geometry.Point3D | None, lock_pending: bool
) -> str:
    """Describe the view-centre state shown under both views."""

    if mode == VIEW_ANCHOR_SHOULDER:
        return VIEW_ANCHOR_LINES[mode]
    if mode != VIEW_ANCHOR_CAMERA:
        raise ValueError(f"unknown view anchor mode {mode!r}; expected one of {VIEW_ANCHOR_MODES}")
    if lock_pending:
        return CAMERA_LOCK_WAITING_LINE
    return CAMERA_UNLOCKED_LINE if locked is None else CAMERA_LOCKED_LINE


def guide_lines(result: geometry.GeometryResult) -> tuple[GuideLine, ...]:
    """Camera-vertical (-Y) references for torso lean and head position.

    ``torso_vertical`` rises from the hip midpoint to shoulder height and
    ``head_vertical`` from the shoulder midpoint to nose height.  They are the
    reference axis of ``sagittal_torso_lean_deg`` and the shoulder reference
    of the head-forward values; no angle or threshold is added.
    """

    shoulder, hip, nose = _measured_references(result)
    guides = []
    if hip is not None and shoulder is not None:
        guides.append(GuideLine(
            "torso_vertical",
            hip,
            geometry.Point3D(hip.x_m, shoulder.y_m, hip.z_m),
        ))
    if shoulder is not None and nose is not None:
        guides.append(GuideLine(
            "head_vertical",
            shoulder,
            geometry.Point3D(shoulder.x_m, nose.y_m, shoulder.z_m),
        ))
    return tuple(guides)


def _view_camera(
    name: str, anchor: geometry.Point3D, direction: Vector3D
) -> ViewCamera:
    focal = (float(anchor.x_m), float(anchor.y_m), float(anchor.z_m))
    position = tuple(
        value - axis * CAMERA_DISTANCE_M for value, axis in zip(focal, direction)
    )
    return ViewCamera(name, position, focal, VIEW_UP)  # type: ignore[arg-type]


def front_camera(anchor: geometry.Point3D) -> ViewCamera:
    """D455-side view: screen-right +X, screen-up -Y (unmirrored image)."""

    return _view_camera("front", anchor, FRONT_VIEW_DIRECTION)


def side_camera(anchor: geometry.Point3D) -> ViewCamera:
    """View from image-right: screen-right +Z (away), screen-up -Y."""

    return _view_camera("side", anchor, SIDE_VIEW_DIRECTION)


def _format(value: Any, unit: str, digits: int) -> str:
    finite = _finite_real(value)
    return "unavailable" if finite is None else f"{finite:+.{digits}f}{unit}"


def _angles_text(orientation: FaceMatrixOrientation) -> str:
    return (
        f"pitch {_format(orientation.pitch_deg, '', 1)}  "
        f"yaw {_format(orientation.yaw_deg, '', 1)}  "
        f"roll {_format(orientation.roll_deg, '', 1)} deg"
    )


def _front_lines(
    head_source: str, orientation: FaceMatrixOrientation | None
) -> tuple[str, ...]:
    lines = ["FRONT: D455 view, unmirrored; right = +X image-right, up = -Y"]
    if head_source == HEAD_SOURCE_FACE_MATRIX:
        assert orientation is not None
        lines.append(f"head axes: face matrix (green arrow); {_angles_text(orientation)}")
    elif head_source == HEAD_SOURCE_LANDMARKS:
        lines.append("head axes: 3D landmarks (pink arrow); face matrix unavailable")
    else:
        lines.append("head: unavailable (needs 3D nose, both ears, both shoulders)")
        if orientation is not None:
            lines.append(f"face matrix without head position; {_angles_text(orientation)}")
    lines.append("+yaw: face to image-right; +pitch: face up; +roll: counter-clockwise")
    lines.append("camera-relative exploratory display; NOT anatomy; no posture decision")
    lines.append(MESH_NOTE)
    return tuple(lines)


def _side_lines(result: geometry.GeometryResult, head_source: str) -> tuple[str, ...]:
    features = result.features
    return (
        "SIDE: viewed from +X; <- toward camera, up = -Y",
        "torso lean (+toward camera): "
        + _format(features.get("sagittal_torso_lean_deg"), " deg", 1),
        "head forward / 3D shoulder: "
        + _format(features.get("nose_forward_normalized_by_shoulder_width_3d"), "", 3),
        "grey lines: camera-vertical references",
        MESH_NOTE,
        NECK_STATUS_LINES[head_source],
    )


def build_scene(
    result: geometry.GeometryResult,
    face_matrix_values: Mapping[str, Any] | None = None,
) -> PostureScene:
    """Describe one frame's display from existing geometry and matrix values."""

    orientation = face_matrix_orientation(face_matrix_values)
    primitives, head_source = orient_head(
        viewer.build_avatar_primitives(result), orientation
    )
    return PostureScene(
        primitives=primitives,
        # The shaded neck top is placed in the head's axes, so it is only
        # drawn when those axes come from a valid face matrix; switching to
        # the landmark fallback axes would otherwise make it jump.
        display_neck=(
            display_neck(primitives) if head_source == HEAD_SOURCE_FACE_MATRIX else None
        ),
        head_source=head_source,
        face_orientation=orientation,
        anchor=scene_anchor(result),
        guides=guide_lines(result),
        front_lines=_front_lines(head_source, orientation),
        side_lines=_side_lines(result, head_source),
    )


def require_pyvista() -> Any:
    """Import PyVista or explain how to install the optional dependency."""

    try:
        import pyvista
    except ImportError as error:
        raise RuntimeError(
            "PyVista is not installed; install the optional viewer "
            f"dependency with: {INSTALL_HINT}"
        ) from error
    return pyvista


def _xyz(point: geometry.Point3D) -> tuple[float, float, float]:
    return (float(point.x_m), float(point.y_m), float(point.z_m))


def _capsule_mesh(pv: Any, capsule: viewer.AvatarCapsule) -> Any:
    """Draw the joint-to-joint capsule as a capped tube."""

    return pv.Tube(
        pointa=_xyz(capsule.start),
        pointb=_xyz(capsule.end),
        radius=capsule.radius_m,
        n_sides=MESH_RESOLUTION,
        capping=True,
    )


def _head_meshes(pv: Any, head: viewer.AvatarEllipsoid) -> tuple[Any, Any]:
    # A unit sphere mapped by (axis * radius) columns is the head ellipsoid.
    transform = np.eye(4)
    for column, (axis, radius) in enumerate(zip(
        (head.lateral_axis, head.vertical_axis, head.forward_axis), head.radii_m
    )):
        transform[:3, column] = np.multiply(axis, radius)
    transform[:3, 3] = _xyz(head.center)
    ellipsoid = pv.Sphere(
        radius=1.0,
        theta_resolution=2 * MESH_RESOLUTION,
        phi_resolution=2 * MESH_RESOLUTION,
    ).transform(transform, inplace=False)
    arrow = pv.Arrow(
        start=_xyz(head.center),
        direction=head.forward_axis,
        scale=HEAD_ARROW_LENGTH_FACTOR * head.radii_m[2],
    )
    return ellipsoid, arrow


def _joint_color(name: str) -> str:
    if name == "nose":
        return "#ffff00"
    return "#ffbe00" if name.startswith("left_") else "#32aaff"


def scene_meshes(scene: PostureScene, pv: Any) -> dict[str, tuple[Any, dict[str, Any]]]:
    """Convert a scene to named PyVista meshes and ``add_mesh`` styles."""

    primitives = scene.primitives
    meshes: dict[str, tuple[Any, dict[str, Any]]] = {}
    if primitives.torso is not None:
        faces = np.hstack([(4, *face) for face in TORSO_FACES])
        vertices = np.asarray([_xyz(point) for point in primitives.torso.vertices])
        meshes["torso"] = (
            pv.PolyData(vertices, faces),
            {"color": TORSO_COLOR, "opacity": .85, "show_edges": True,
             "edge_color": TORSO_EDGE_COLOR},
        )
    capsules = (
        *primitives.arm_segments,
        *((primitives.pelvis,) if primitives.pelvis is not None else ()),
    )
    for capsule in capsules:
        meshes[capsule.name] = (
            _capsule_mesh(pv, capsule),
            {"color": CAPSULE_COLORS[capsule.name]},
        )
    if scene.display_neck is not None:
        neck = scene.display_neck
        line = pv.Line(_xyz(neck.base), _xyz(neck.top))
        line.point_data["radius"] = (neck.base_radius_m, neck.top_radius_m)
        meshes["neck"] = (
            line.tube(scalars="radius", absolute=True,
                      n_sides=2 * MESH_RESOLUTION, capping=True),
            # Translucent so the measured line inside it stays visible.
            {"color": CAPSULE_COLORS["neck"], "opacity": .6},
        )
    if primitives.neck is not None:
        meshes["measured:shoulder_ear"] = (
            pv.Line(_xyz(primitives.neck.end), _xyz(primitives.neck.start)),
            {"color": MEASURED_LINE_COLOR, "line_width": 3},
        )
    if primitives.head is not None:
        ellipsoid, arrow = _head_meshes(pv, primitives.head)
        meshes["head"] = (ellipsoid, {"color": HEAD_COLOR, "opacity": .9})
        meshes[f"head_forward:{scene.head_source}"] = (
            arrow, {"color": HEAD_ARROW_COLORS[scene.head_source]}
        )
    for sphere in primitives.joints:
        meshes[f"joint:{sphere.joint_name}"] = (
            pv.Sphere(
                radius=sphere.radius_m,
                center=_xyz(sphere.center),
                theta_resolution=MESH_RESOLUTION,
                phi_resolution=MESH_RESOLUTION,
            ),
            {"color": _joint_color(sphere.joint_name)},
        )
    for guide in scene.guides:
        meshes[f"guide:{guide.name}"] = (
            pv.Line(_xyz(guide.start), _xyz(guide.end)),
            {"color": GUIDE_COLOR, "line_width": 2},
        )
    return meshes


class PyVistaPostureViewer:
    """Front/side PyVista window updated from the probe's existing loop.

    No thread or second event loop is started.  ``update`` redraws and then
    processes pending VTK window events once, the same way ``cv2.waitKey``
    services the OpenCV windows in that loop.  Closing this window (or
    pressing q/e in it) only requests closure; the next ``update`` closes it
    and returns False so the caller can continue without it.  The cameras are
    reset every frame, so mouse rotation is not retained.

    Each named mesh gets one actor per view on first use; later frames copy
    new geometry into that mesh and hide actors whose primitive is missing.
    ``anchor_mode`` selects the display focal point (see :func:`view_anchor`).
    In ``camera`` mode, pressing L in this window requests a lock (or
    re-lock); the next ``update`` with both shoulders measured locks at that
    frame's shoulder midpoint (:func:`camera_lock_point`).
    """

    def __init__(
        self,
        *,
        off_screen: bool = False,
        window_size: tuple[int, int] = DEFAULT_WINDOW_SIZE,
        anchor_mode: str = VIEW_ANCHOR_SHOULDER,
    ) -> None:
        if anchor_mode not in VIEW_ANCHOR_MODES:
            raise ValueError(
                f"unknown view anchor mode {anchor_mode!r}; expected one of {VIEW_ANCHOR_MODES}"
            )
        self._anchor_mode = anchor_mode
        self._locked_anchor: geometry.Point3D | None = None
        self._lock_requested = False
        self._pv = require_pyvista()
        self._off_screen = bool(off_screen)
        self._plotter = self._pv.Plotter(
            shape=(1, 2),
            off_screen=self._off_screen,
            window_size=list(window_size),
            title=WINDOW_TITLE,
        )
        self._meshes: dict[str, Any] = {}
        self._close_requested = False
        self._closed = False
        self._shown = False
        for column in range(2):
            self._plotter.subplot(0, column)
            self._plotter.set_background(BACKGROUND_COLOR)
            self._plotter.enable_parallel_projection()
        if self._plotter.iren is not None:
            self._plotter.iren.add_observer("ExitEvent", self._request_close)
            if anchor_mode == VIEW_ANCHOR_CAMERA:
                for key in CAMERA_LOCK_KEYS:
                    self._plotter.add_key_event(key, self._request_lock)

    @property
    def plotter(self) -> Any:
        return self._plotter

    @property
    def closed(self) -> bool:
        return self._closed

    def _request_close(self, *_: Any) -> None:
        self._close_requested = True

    def _request_lock(self) -> None:
        self._lock_requested = True

    def update(
        self,
        result: geometry.GeometryResult,
        face_matrix_values: Mapping[str, Any] | None = None,
    ) -> bool:
        """Draw one frame; return False once the window has been closed."""

        if self._closed:
            return False
        if self._close_requested:
            self.close()
            return False
        scene = build_scene(result, face_matrix_values)
        if self._lock_requested:
            lock_point = camera_lock_point(result)
            if lock_point is not None:
                self._locked_anchor = lock_point
                self._lock_requested = False
        focal, self._locked_anchor = view_anchor(
            self._anchor_mode, scene.anchor, self._locked_anchor
        )
        anchor_line = anchor_status_line(
            self._anchor_mode, self._locked_anchor, self._lock_requested
        )
        meshes = scene_meshes(scene, self._pv)
        new_names = []
        for name, (mesh, _) in meshes.items():
            if name in self._meshes:
                self._meshes[name].copy_from(mesh)
            else:
                self._meshes[name] = mesh
                new_names.append(name)
        for column, camera_for, lines in (
            (0, front_camera, scene.front_lines),
            (1, side_camera, scene.side_lines),
        ):
            self._plotter.subplot(0, column)
            for name in new_names:
                # Both views share the mesh object, so one copy updates both.
                self._plotter.add_mesh(
                    self._meshes[name], name=name, reset_camera=False,
                    render=False, **meshes[name][1],
                )
            for name, actor in self._plotter.renderer.actors.items():
                if name in self._meshes:
                    actor.SetVisibility(name in meshes)
            self._plotter.add_text(
                "\n".join((*lines, anchor_line)), position="upper_left", font_size=9,
                color=TEXT_COLOR, name="status", render=False,
            )
            if focal is not None:
                camera = camera_for(focal)
                self._plotter.camera_position = [
                    camera.position, camera.focal_point, camera.view_up
                ]
                self._plotter.camera.parallel_scale = VIEW_HALF_HEIGHT_M
                self._plotter.renderer.reset_camera_clipping_range()
        if not self._shown:
            # Non-blocking: no VTK event loop is started here.
            self._plotter.show(interactive_update=True, auto_close=False)
            self._shown = True
        else:
            self._plotter.render()
        if not self._off_screen:
            # Render first, then pump events, so a close request is handled
            # before anything draws into a window that is being destroyed.
            self._plotter.iren.process_events()
            if self._close_requested:
                self.close()
                return False
        return True

    def screenshot(self) -> np.ndarray:
        """Return the current RGB frame; intended for off-screen checks."""

        return self._plotter.screenshot(return_img=True)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._plotter.close()
