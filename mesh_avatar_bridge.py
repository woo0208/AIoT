"""Display-only bridge: GeometryResult joints -> browser mesh avatar.

This module only *forwards already-computed* exploratory 3D joint positions to a
local web page that draws a rigged human mesh.  It does not sample depth, compute
posture features, classify posture, or write research artifacts.  The mesh is an
illustration of measured joint directions, not a measurement.

Coordinates are forwarded unchanged in RealSense camera frame (metres):
+X image-right, +Y image-down, +Z away from the camera.  The browser converts them.

Optional ``head`` (stage 2): unit head axes in the same RealSense frame, derived
from the probe's already-computed face-matrix angles with the PyVista viewer's
``face_matrix_head_axes`` (no new sign convention).  ``None`` when no valid
face matrix exists; the page then falls back to ear/nose joints.

``prediction`` (/3): the engineering RF demo output computed by the probe for
the *same* frame (``probe.ProbeFrame.rf_demo``), forwarded as-is or marked
unavailable with a reason.  The page only displays it; it never classifies.

``exploratory_geometry`` is a backward-compatible optional /3 field containing
only already-computed values from that same ``ProbeFrame``.  It is explicitly
tagged as engineering geometry, not a posture classification.  No threshold or
new formula is applied here.
"""

from __future__ import annotations

import json
import math
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

WEB_DIR = Path(__file__).resolve().parent / "mesh_avatar" / "web"
MODELS_DIR = WEB_DIR / "models"
DEFAULT_MODEL_FILE = "X_Bot.fbx"
POSE_SCHEMA = "mesh-avatar-pose/3"  # /2: optional "head" axes; /3: frame identity + same-frame RF prediction

RF_DEMO_BANNER = "ENGINEERING RF DEMO — ACCURACY NOT VALIDATED"
GEOMETRY_BANNER = "EXPLORATORY GEOMETRY — NOT A POSTURE CLASSIFICATION"
GEOMETRY_KIND = "exploratory-current-frame-geometry/1"
PREDICTION_UNAVAILABLE = "PREDICTION UNAVAILABLE"
# The only texts the page may show as an available prediction (probe.RF_DISPLAY_LABELS values).
PREDICTION_DISPLAYS = ("UPRIGHT", "FORWARD HEAD", "BODY FORWARD")
REASON_RF_NOT_ENABLED = "RF demo not enabled (start with --f1-live --rf-demo-model PATH)"
REASON_SYNTHETIC = "synthetic mode: no camera frame, no RF prediction"


def result_to_pose_payload(
    result: Any,
    *,
    frame_id: int = 0,
    face_matrix_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialise usable 3D joints of a GeometryResult (missing joints -> null)."""

    return make_payload(
        _joints_from_result(result),
        frame_id=frame_id,
        head=head_axes_from_face_matrix(face_matrix_values),
        exploratory_geometry=exploratory_geometry_from_result(
            result, frame_id=frame_id, face_matrix_values=face_matrix_values
        ),
    )


def probe_frame_to_payload(frame: Any) -> dict[str, Any]:
    """Payload for one completed ``probe.ProbeFrame``: joints, head and RF prediction of that frame only."""

    return make_payload(
        _joints_from_result(frame.result),
        frame_id=frame.frame_index,
        head=head_axes_from_face_matrix(frame.face_matrix_values),
        device_timestamp_ms=frame.device_timestamp_ms,
        mediapipe_timestamp_ms=frame.mediapipe_timestamp_ms,
        prediction=prediction_from_rf_demo(frame.rf_demo, frame_id=frame.frame_index),
        exploratory_geometry=exploratory_geometry_from_result(
            frame.result,
            frame_id=frame.frame_index,
            face_matrix_values=frame.face_matrix_values,
        ),
    )


def _joints_from_result(result: Any) -> dict[str, list[float] | None]:
    import posture_3d_viewer as viewer  # imported lazily: --synthetic needs no research code

    joints: dict[str, list[float] | None] = {}
    for name, point in viewer.joint_positions_3d(result).items():
        joints[name] = None if point is None else [float(point.x_m), float(point.y_m), float(point.z_m)]
    return joints


def unavailable_prediction(reason: str, *, frame_id: int | None, model_status: str | None = None) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "display": PREDICTION_UNAVAILABLE,
        "label": None,
        "reason": str(reason),
        "model_status": model_status,
        "frame_id": frame_id,
        "banner": RF_DEMO_BANNER,
    }


def prediction_from_rf_demo(rf_demo: Any, *, frame_id: int) -> dict[str, Any]:
    """Forward the probe's RFDemoFrame unchanged; anything else is UNAVAILABLE (no substitution)."""

    if rf_demo is None:
        return unavailable_prediction(REASON_RF_NOT_ENABLED, frame_id=frame_id)
    label = getattr(rf_demo, "label", None)
    display = getattr(rf_demo, "prediction", None)
    status = getattr(rf_demo, "model_status", None)
    reason = str(getattr(rf_demo, "reason", ""))
    if label is None:
        return unavailable_prediction(reason or "prediction unavailable", frame_id=frame_id, model_status=status)
    if display not in PREDICTION_DISPLAYS:
        return unavailable_prediction(
            f"unsupported prediction display: {display!r}", frame_id=frame_id, model_status=status
        )
    return {
        "status": "available",
        "display": display,
        "label": str(label),
        "reason": reason,
        "model_status": status,
        "frame_id": frame_id,
        "banner": RF_DEMO_BANNER,
    }


def exploratory_geometry_from_result(
    result: Any,
    *,
    frame_id: int,
    face_matrix_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Forward existing current-frame geometry without classifying it.

    The feature names and calculations come from ``posture_geometry``.  This
    bridge only filters non-finite values and adds same-frame identity.  The
    mixed sources are kept explicit so 2D/Face-Matrix diagnostics cannot be
    mistaken for metric 3D measurements.
    """

    features = getattr(result, "features", {})
    if not isinstance(features, Mapping):
        features = {}
    values = {
        "sagittal_torso_lean_deg": _finite_or_none(
            features.get("sagittal_torso_lean_deg")
        ),
        "exploratory_head_pitch_deg": _finite_or_none(
            features.get("exploratory_head_pitch_deg")
        ),
        "nose_forward_normalized_by_shoulder_width_3d": _finite_or_none(
            features.get("nose_forward_normalized_by_shoulder_width_3d")
        ),
        "shoulder_width_3d_m": _finite_or_none(
            features.get("shoulder_width_3d_m")
        ),
        "head_to_torso_lateral_angle_deg": _finite_or_none(
            features.get("head_to_torso_lateral_angle_deg")
        ),
        "shoulder_tilt_deg": _finite_or_none(features.get("shoulder_tilt_deg")),
        "face_matrix_yaw_deg": None,
    }
    if face_matrix_values and face_matrix_values.get("face_matrix_valid") is True:
        values["face_matrix_yaw_deg"] = _finite_or_none(
            face_matrix_values.get("face_matrix_yaw_deg")
        )
    return {
        "kind": GEOMETRY_KIND,
        "role": "exploratory_geometry_not_classification",
        "frame_id": int(frame_id),
        "banner": GEOMETRY_BANNER,
        "values": values,
    }


def model_asset_diagnostic(model_file: str = DEFAULT_MODEL_FILE) -> str | None:
    """None when the avatar model file is present; otherwise a human-readable reason (no download)."""

    path = MODELS_DIR / model_file
    if path.is_file():
        return None
    return (
        f"avatar model not found: {path}\n"
        f"  The FBX is not in Git and is never downloaded automatically (Adobe Mixamo terms unverified).\n"
        f"  Obtain '{model_file}' yourself and place it there; see mesh_avatar/README.md.\n"
        f"  The page still shows the connection status and the RF prediction panel without it."
    )


def head_axes_from_face_matrix(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Face-matrix head axes (lateral->left ear, vertical->head top, forward->out of face) or None."""

    import posture_pyvista_viewer as pv  # lazily; imports without PyVista installed

    orientation = pv.face_matrix_orientation(values)
    if orientation is None:
        return None
    lateral, vertical, forward = pv.face_matrix_head_axes(orientation)
    return {
        "source": "face_matrix",
        "lateral": list(lateral),
        "vertical": list(vertical),
        "forward": list(forward),
    }


def make_payload(
    joints: Mapping[str, Any],
    *,
    frame_id: int = 0,
    synthetic: bool = False,
    head: Mapping[str, Any] | None = None,
    device_timestamp_ms: float | None = None,
    mediapipe_timestamp_ms: int | None = None,
    prediction: Mapping[str, Any] | None = None,
    exploratory_geometry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    clean: dict[str, list[float] | None] = {}
    for name, value in joints.items():
        if value is None:
            clean[name] = None
            continue
        try:
            xyz = [float(value[0]), float(value[1]), float(value[2])]
        except (TypeError, ValueError, IndexError):
            clean[name] = None
            continue
        clean[name] = xyz if all(math.isfinite(v) for v in xyz) else None
    if prediction is None or synthetic:  # synthetic poses never carry a prediction
        prediction = unavailable_prediction(
            REASON_SYNTHETIC if synthetic else REASON_RF_NOT_ENABLED, frame_id=int(frame_id)
        )
    if synthetic:
        exploratory_geometry = None
    return {
        "schema": POSE_SCHEMA,
        "frame_id": int(frame_id),
        "device_timestamp_ms": _finite_or_none(device_timestamp_ms),
        "mediapipe_timestamp_ms": None if mediapipe_timestamp_ms is None else int(mediapipe_timestamp_ms),
        "t_unix": time.time(),
        "synthetic": bool(synthetic),
        "joints": clean,
        "head": _clean_head(head),
        "prediction": dict(prediction),
        "exploratory_geometry": (
            None if exploratory_geometry is None else dict(exploratory_geometry)
        ),
    }


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_head(head: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not head:
        return None
    out: dict[str, Any] = {"source": str(head.get("source", "unknown"))}
    for axis in ("lateral", "vertical", "forward"):
        try:
            xyz = [float(v) for v in head[axis]]
        except (KeyError, TypeError, ValueError):
            return None
        if len(xyz) != 3 or not all(math.isfinite(v) for v in xyz):
            return None
        out[axis] = xyz
    return out


class PoseStore:
    """Thread-safe latest-pose holder."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None

    def publish(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._payload = payload

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._payload


class _Handler(SimpleHTTPRequestHandler):
    store: PoseStore

    def __init__(self, *args: Any, store: PoseStore, **kwargs: Any) -> None:
        self.store = store
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if self.path.split("?")[0] == "/pose":
            payload = self.store.latest()
            body = json.dumps(payload if payload is not None else {"schema": POSE_SCHEMA, "joints": None}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self) -> None:
        # page files (index.html, app.js): revalidate every load so an edited app.js is never served stale
        if self.path.split("?")[0] != "/pose":
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *_args: Any) -> None:  # keep the console quiet
        return


def start_server(store: PoseStore, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Serve the viewer page and /pose on a daemon thread; returns the server."""

    handler = partial(_Handler, directory=str(WEB_DIR), store=store)
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
