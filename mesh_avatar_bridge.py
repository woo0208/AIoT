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
POSE_SCHEMA = "mesh-avatar-pose/2"  # /2: optional "head" axes


def result_to_pose_payload(
    result: Any,
    *,
    frame_id: int = 0,
    face_matrix_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialise usable 3D joints of a GeometryResult (missing joints -> null)."""

    import posture_3d_viewer as viewer  # imported lazily: --synthetic needs no research code

    joints: dict[str, list[float] | None] = {}
    for name, point in viewer.joint_positions_3d(result).items():
        joints[name] = None if point is None else [float(point.x_m), float(point.y_m), float(point.z_m)]
    return make_payload(joints, frame_id=frame_id, head=head_axes_from_face_matrix(face_matrix_values))


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
    return {
        "schema": POSE_SCHEMA,
        "frame_id": int(frame_id),
        "t_unix": time.time(),
        "synthetic": bool(synthetic),
        "joints": clean,
        "head": _clean_head(head),
    }


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

    def log_message(self, *_args: Any) -> None:  # keep the console quiet
        return


def start_server(store: PoseStore, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Serve the viewer page and /pose on a daemon thread; returns the server."""

    handler = partial(_Handler, directory=str(WEB_DIR), store=store)
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
