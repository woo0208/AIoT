"""Launcher: live D455 probe + browser mesh avatar (display only).

Usage:
    python run_mesh_avatar.py            # live D455 -> http://127.0.0.1:8765
    python run_mesh_avatar.py --synthetic     # no camera; synthetic poses (NOT data)
    python run_mesh_avatar.py --cam-pitch 15  # camera mounted looking 15 deg downward

It leaves posture_geometry_probe.py / posture_3d_viewer.py untouched: it wraps the
probe's 3D-view hook so every frame's GeometryResult is also published to the page,
and taps (read-only) the probe's per-frame face-matrix values for the head axes.
"""

from __future__ import annotations

import argparse
import math
import time
import webbrowser

import mesh_avatar_bridge as bridge


def _synthetic_loop(store: bridge.PoseStore) -> None:
    """Structural demo only: a slowly leaning synthetic upper body."""

    frame = 0
    while True:
        t = frame / 15.0
        lean = 0.12 * (1 + math.sin(t * 0.6))  # forward shift (m)
        z = 0.80
        joints = {
            "left_shoulder": [0.19, -0.0, z - lean * 0.4], "right_shoulder": [-0.19, -0.0, z - lean * 0.4],
            "left_hip": [0.10, 0.50, z], "right_hip": [-0.10, 0.50, z],
            "left_ear": [0.08, -0.22, z - lean], "right_ear": [-0.08, -0.22, z - lean],
            "nose": [0.0, -0.20, z - lean - 0.09],
            "left_elbow": [0.24, 0.25, z - 0.05], "right_elbow": [-0.24, 0.25, z - 0.05],
            "left_wrist": [0.15, 0.40, z - 0.30], "right_wrist": [-0.15, 0.40, z - 0.30],
        }
        store.publish(bridge.make_payload(joints, frame_id=frame, synthetic=True))
        frame += 1
        time.sleep(1 / 15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="no camera: structural demo with synthetic joints")
    parser.add_argument(
        "--cam-pitch", type=float, default=0.0,
        help="display only: D455 downward pitch in degrees (+ = looking down) to level the avatar",
    )
    parser.add_argument(
        "--smooth", type=float, default=None,
        help="display only, off by default: joint smoothing weight of the newest sample (e.g. 0.45)",
    )
    parser.add_argument(
        "--nose-down", type=float, default=None,
        help="display only, off by default: assumed nose-below-ear head pitch offset in degrees (e.g. 10)",
    )
    args = parser.parse_args()

    store = bridge.PoseStore()
    bridge.start_server(store, args.port)
    url = f"http://127.0.0.1:{args.port}/?cam_pitch={args.cam_pitch:g}"
    if args.smooth is not None:
        url += f"&smooth={args.smooth:g}"
    if args.nose_down is not None:
        url += f"&nose_down={args.nose_down:g}"
    print(f"[mesh-avatar] viewer: {url}  (display only; not a measurement)")
    if not args.no_browser:
        webbrowser.open(url)

    if args.synthetic:
        print("[mesh-avatar] SYNTHETIC mode: poses are generated, not measured. Ctrl+C to stop.")
        try:
            _synthetic_loop(store)
        except KeyboardInterrupt:
            return 0

    import posture_geometry_probe as probe

    original = probe.viewer.render_selected_views
    original_face_values = probe._face_matrix_csv_values
    counter = {"n": 0}
    latest_face = {"values": None}

    # Read-only tap: the probe computes face-matrix values each frame before it
    # renders the 3D views; remember them and return them unchanged.
    def tapped_face_values(matrix):
        values = original_face_values(matrix)
        latest_face["values"] = values
        return values

    def hooked(result, view_mode):
        counter["n"] += 1
        face_values, latest_face["values"] = latest_face["values"], None  # this frame only
        store.publish(bridge.result_to_pose_payload(
            result, frame_id=counter["n"], face_matrix_values=face_values
        ))
        return original(result, view_mode)

    probe._face_matrix_csv_values = tapped_face_values
    probe.viewer.render_selected_views = hooked
    # The probe only calls render_selected_views when views are enabled; the
    # OpenCV window it opens is harmless, and can be closed independently.
    probe.run_probe(show_3d_views="side")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
