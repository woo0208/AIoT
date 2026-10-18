"""Launcher: live D455 probe + browser mesh avatar (display only).

Usage:
    python run_mesh_avatar.py            # live D455 -> http://127.0.0.1:8765
    python run_mesh_avatar.py --synthetic     # no camera; synthetic poses (NOT data)
    python run_mesh_avatar.py --cam-pitch 15  # camera mounted looking 15 deg downward
    python run_mesh_avatar.py --views none    # browser mesh without the OpenCV 3D viewer
    python run_mesh_avatar.py --f1-live --rf-demo-model f1_demo_rf.json   # + same-frame RF demo

Any other option is passed unchanged to posture_geometry_probe.py (--f1-live,
--rf-demo-model, --views, --pyvista, --pyvista-anchor, --panel-mode, ...).
The probe's OpenCV window, F1/RF strips and 3D viewers behave as when the probe
runs alone; each completed probe frame is also published to the page through
the probe's explicit ``frame_callback`` (joints, face-matrix head axes, frame
identity, that frame's RF prediction or its unavailable reason, and the
already-computed exploratory geometry values (clearly separated from the
classification).
"""

from __future__ import annotations

import argparse
import math
import time
import webbrowser
from typing import Sequence

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


def make_frame_publisher(store: bridge.PoseStore):
    """Probe frame callback: publish exactly the completed frame it is given."""

    def publish(frame) -> None:
        store.publish(bridge.probe_frame_to_payload(frame))

    return publish


def parse_args(argv: Sequence[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="no camera: structural demo with synthetic joints")
    parser.add_argument(
        "--model", default=bridge.DEFAULT_MODEL_FILE,
        help="avatar FBX file inside mesh_avatar/web/models/ (not in Git; never downloaded)",
    )
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
    return parser.parse_known_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args, probe_argv = parse_args(argv)

    probe_args = None
    if not args.synthetic:
        import posture_geometry_probe as probe

        probe_args = probe.parse_args(probe_argv)  # validates probe options before the server starts
        if probe_args.views is None:
            probe_args.views = "side"  # the side-view avatar stays on, as in the previous launcher
    elif probe_argv:
        raise SystemExit(f"--synthetic takes no probe options: {' '.join(probe_argv)}")

    diagnostic = bridge.model_asset_diagnostic(args.model)
    if diagnostic:
        print("[mesh-avatar] " + diagnostic)

    store = bridge.PoseStore()
    bridge.start_server(store, args.port)
    url = f"http://127.0.0.1:{args.port}/?cam_pitch={args.cam_pitch:g}"
    if args.model != bridge.DEFAULT_MODEL_FILE:
        url += f"&model={args.model}"
    if args.smooth is not None:
        url += f"&smooth={args.smooth:g}"
    if args.nose_down is not None:
        url += f"&nose_down={args.nose_down:g}"
    print(f"[mesh-avatar] viewer: {url}  (display only; not a measurement)")
    if not args.no_browser:
        webbrowser.open(url)

    if args.synthetic:
        print("[mesh-avatar] SYNTHETIC mode: poses are generated, not measured; no RF prediction. Ctrl+C to stop.")
        try:
            _synthetic_loop(store)
        except KeyboardInterrupt:
            return 0

    if probe_args.rf_demo_model is None:
        print("[mesh-avatar] RF demo off: the page shows PREDICTION UNAVAILABLE "
              "(add --f1-live --rf-demo-model PATH); same-frame exploratory "
              "geometry remains live and is not a posture decision")
    probe.run_probe(
        probe_args.csv,
        face_diag_csv_path=probe_args.face_diag_csv,
        show_3d_views=probe_args.views,
        panel_mode=probe_args.panel_mode,
        pyvista_view=probe_args.pyvista,
        pyvista_anchor=probe_args.pyvista_anchor,
        f1_live=probe_args.f1_live,
        rf_demo_model_path=probe_args.rf_demo_model,
        frame_callback=make_frame_publisher(store),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
