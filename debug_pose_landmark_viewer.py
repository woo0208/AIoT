"""NON-FORMAL ENGINEERING DEBUG: raw MediaPipe shoulder/hip landmark viewer.

Shows the raw normalized PoseLandmarker output for indices 11/12/23/24 on the
live D455 RGB image, including values outside the image (x<0, x>=1, y<0,
y>=1).  Nothing is clipped, filtered by visibility, or corrected.

Out-of-frame values are MediaPipe model extrapolations, NOT measured anatomical
pelvis positions.  This tool does no classification, no feature computation
(F1/F2), no aggregation, and writes no files unless ``--snapshot-dir`` is given
and ``s`` is pressed.  It is not formal evidence and not hardware validation.

Engineering diagnostic add-on (NOT F1, NOT research evidence): press ``b`` while
sitting upright to capture a fixed baseline (median of 15 consecutive valid
frames) and compare the live MediaPipe hip midpoint against that fixed hip.
The fixed reference is valid only for the current camera, chair and subject
setup; it is not claimed to be anatomically accurate and cannot separate real
3D pelvic motion from camera projection or model estimation error.

Run (D455 attached):
    python debug_pose_landmark_viewer.py [--snapshot-dir DIR] [--pad 160]
Keys: b = capture baseline, r = reset baseline,
      s = save PNG snapshot (needs --snapshot-dir), q = quit.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import math
import os
from typing import Any, Mapping, Sequence

import numpy as np

WINDOW_NAME = "NON-FORMAL pose landmark debug viewer"
BANNER = "NON-FORMAL ENGINEERING DEBUG"
DISCLAIMER = ("Out-of-frame values = MediaPipe model extrapolation, "
              "NOT measured anatomical pelvis position")

# (mediapipe pose index, name, BGR colour)
DEBUG_LANDMARKS: tuple[tuple[int, str, tuple[int, int, int]], ...] = (
    (11, "left_shoulder", (0, 220, 0)),
    (12, "right_shoulder", (0, 160, 60)),
    (23, "left_hip", (255, 100, 255)),
    (24, "right_hip", (255, 180, 60)),
)

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_NONFINITE = "nonfinite"

PANEL_WIDTH = 560

FIXED_HIP_LABEL = "FIXED-HIP ENGINEERING CANDIDATE \u2014 NOT F1"
FIXED_HIP_NOTE = "valid only for this camera/chair/subject setup"
BASELINE_FRAMES = 15
_BASELINE_NAMES = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
HIP_CURRENT_COLOR = (255, 0, 255)   # BGR magenta: current MediaPipe hip midpoint
HIP_FIXED_COLOR = (0, 140, 255)     # BGR orange: fixed baseline hip midpoint


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_score(landmark: Any, attr: str) -> float | None:
    """visibility/presence: None when absent or nonfinite (never dropped)."""
    return _finite(getattr(landmark, attr, None))


def landmark_record(
    pose_landmarks: Any,
    index: int,
    name: str,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Raw record for one landmark.  x/y are the unmodified MediaPipe values."""

    record: dict[str, Any] = {
        "index": index, "name": name, "status": STATUS_MISSING,
        "x": None, "y": None, "visibility": None, "presence": None,
        "in_frame": None,
        "margin_left": None, "margin_right": None,
        "margin_top": None, "margin_bottom": None,
        "x_px": None, "y_px": None,
    }
    try:
        landmark = pose_landmarks[index]
    except (IndexError, KeyError, TypeError):
        return record
    if landmark is None:
        return record
    x = _finite(getattr(landmark, "x", None))
    y = _finite(getattr(landmark, "y", None))
    record["visibility"] = _optional_score(landmark, "visibility")
    record["presence"] = _optional_score(landmark, "presence")
    if x is None or y is None:
        record["status"] = STATUS_NONFINITE
        return record
    record.update(
        status=STATUS_OK, x=x, y=y,
        x_px=x * image_width, y_px=y * image_height,
        # Same geometric rule as the production extractor: 0 <= v < 1.
        in_frame=bool(0.0 <= x < 1.0 and 0.0 <= y < 1.0),
        # Signed distance to each image border (normalized); negative = outside.
        margin_left=x, margin_right=1.0 - x,
        margin_top=y, margin_bottom=1.0 - y,
    )
    return record


def extract_debug_landmarks(
    pose_landmarks: Any, image_width: int, image_height: int
) -> list[dict[str, Any]]:
    return [
        landmark_record(pose_landmarks, idx, name, image_width, image_height)
        for idx, name, _ in DEBUG_LANDMARKS
    ]


def normalized_to_canvas(
    x: float, y: float, image_width: int, image_height: int, pad: int
) -> tuple[float, float]:
    """Normalized image coords -> padded-canvas pixel coords (unclipped)."""
    return pad + x * image_width, pad + y * image_height


def canvas_placement(
    x: float, y: float, image_width: int, image_height: int, pad: int
) -> dict[str, Any]:
    """Where a point lands on the padded canvas.

    zone: 'in_frame' | 'padding' | 'beyond_padding'.  ``direction`` lists the
    sides (L/R/T/B) the point lies beyond.  ``draw`` is the canvas position to
    draw at (clamped to the canvas edge only for beyond_padding; the raw
    numbers are always kept separately).
    """
    cx, cy = normalized_to_canvas(x, y, image_width, image_height, pad)
    canvas_w, canvas_h = image_width + 2 * pad, image_height + 2 * pad
    direction = ""
    if x < 0:
        direction += "L"
    if x >= 1:
        direction += "R"
    if y < 0:
        direction += "T"
    if y >= 1:
        direction += "B"
    if not direction:
        zone = "in_frame"
    elif 0 <= cx < canvas_w and 0 <= cy < canvas_h:
        zone = "padding"
    else:
        zone = "beyond_padding"
    draw = (min(max(cx, 0.0), canvas_w - 1.0), min(max(cy, 0.0), canvas_h - 1.0))
    return {"zone": zone, "direction": direction, "canvas": (cx, cy), "draw": draw}


def midpoint_diagnostic(
    records: Sequence[Mapping[str, Any]], image_width: int, image_height: int
) -> dict[str, Any] | None:
    """2D shoulder-mid -> hip-mid projected distance (diagnostic only)."""
    by_name = {r["name"]: r for r in records}
    names = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    if any(by_name.get(n, {}).get("status") != STATUS_OK for n in names):
        return None
    sx = (by_name["left_shoulder"]["x"] + by_name["right_shoulder"]["x"]) / 2
    sy = (by_name["left_shoulder"]["y"] + by_name["right_shoulder"]["y"]) / 2
    hx = (by_name["left_hip"]["x"] + by_name["right_hip"]["x"]) / 2
    hy = (by_name["left_hip"]["y"] + by_name["right_hip"]["y"]) / 2
    dist_px = math.hypot((hx - sx) * image_width, (hy - sy) * image_height)
    return {
        "shoulder_mid": (sx, sy), "hip_mid": (hx, hy),
        "distance_px": dist_px, "distance_image_heights": dist_px / image_height,
    }


# ---------------------------------------------------------------------------
# Fixed-hip engineering diagnostic (NOT F1)
# ---------------------------------------------------------------------------

Point = tuple[float, float]


def _by_name(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {r["name"]: r for r in records}


def _pair_midpoint(records: Sequence[Mapping[str, Any]],
                   left: str, right: str) -> Point | None:
    """Midpoint of two finite landmarks (raw values, no in-frame requirement)."""
    by_name = _by_name(records)
    a, b = by_name.get(left), by_name.get(right)
    if a is None or b is None:
        return None
    if a.get("status") != STATUS_OK or b.get("status") != STATUS_OK:
        return None
    return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2


def baseline_frame_valid(records: Sequence[Mapping[str, Any]]) -> bool:
    """Baseline-frame validity: 11/12/23/24 finite AND inside the image frame.

    No visibility/presence threshold is applied (engineering diagnostic).
    """
    by_name = _by_name(records)
    for name in _BASELINE_NAMES:
        r = by_name.get(name)
        if r is None or r.get("status") != STATUS_OK or r.get("in_frame") is not True:
            return False
    return True


class BaselineCollector:
    """Manual baseline capture: 15 consecutive valid frames -> coordinate median.

    States: idle -> collecting -> ready.  An invalid frame during collection
    aborts the capture (back to idle); fewer than ``required`` frames are never
    accepted.  ``reset()`` clears everything.  Nothing starts automatically.
    """

    def __init__(self, required: int = BASELINE_FRAMES) -> None:
        if required < 1:
            raise ValueError("required must be >= 1")
        self.required = required
        self.state = "idle"
        self.message = ""
        self._frames: list[list[Point]] = []
        self.baseline: dict[str, Any] | None = None

    @property
    def collecting(self) -> bool:
        return self.state == "collecting"

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def start(self) -> bool:
        """Begin a capture (the 'b' key).  Refused while collecting or ready."""
        if self.state == "collecting":
            self.message = "capture already in progress"
            return False
        if self.state == "ready":
            self.message = "baseline already set; press r to reset first"
            return False
        self._frames = []
        self.state = "collecting"
        self.message = ""
        return True

    def reset(self) -> None:
        """Clear baseline / any partial capture (the 'r' key)."""
        self.state = "idle"
        self._frames = []
        self.baseline = None
        self.message = "baseline cleared"

    def update(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Feed one live frame; only meaningful while collecting."""
        if self.state != "collecting":
            return
        if not baseline_frame_valid(records):
            got = len(self._frames)
            self._frames = []
            self.state = "idle"
            self.message = (f"capture ABORTED: invalid frame after {got}/"
                            f"{self.required}; press b to retry")
            return
        by_name = _by_name(records)
        self._frames.append([(by_name[n]["x"], by_name[n]["y"])
                             for n in _BASELINE_NAMES])
        if len(self._frames) < self.required:
            return
        med = np.median(np.asarray(self._frames, dtype=float), axis=0)
        ls, rs, lh, rh = (tuple(float(c) for c in row) for row in med)
        self.baseline = {
            "S0": ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2),
            "H0": ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2),
            "frames": len(self._frames),
        }
        self._frames = []
        self.state = "ready"
        self.message = "baseline ready"

    def status_text(self) -> str:
        if self.state == "collecting":
            text = f"baseline: COLLECTING {len(self._frames)}/{self.required}"
        elif self.state == "ready":
            text = f"baseline: READY ({self.baseline['frames']} frames, median)"
        else:
            text = "baseline: NOT SET (sit upright, press b)"
        if self.message and self.state != "ready":
            text += f" | {self.message}"
        return text


def _sub(a: Point | None, b: Point | None) -> Point | None:
    if a is None or b is None:
        return None
    return a[0] - b[0], a[1] - b[1]


def fixed_hip_diagnostics(
    records: Sequence[Mapping[str, Any]], baseline: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Dynamic vs fixed shoulder-hip vectors in image-normalized x/y.

    SH_dynamic = (S(t) - H(t)) / D_sh(t);  SH_fixed = (S(t) - H0) / D_sh(t),
    D_sh = Euclidean distance between the current shoulders in the same
    normalized (x, y) units.  Unavailable values are None (never 0/imputed).
    """
    s_t = _pair_midpoint(records, "left_shoulder", "right_shoulder")
    h_t = _pair_midpoint(records, "left_hip", "right_hip")
    s0 = baseline["S0"] if baseline else None
    h0 = baseline["H0"] if baseline else None

    d_sh: float | None = None
    by_name = _by_name(records)
    ls, rs = by_name.get("left_shoulder"), by_name.get("right_shoulder")
    if s_t is not None and ls is not None and rs is not None:
        d = math.hypot(ls["x"] - rs["x"], ls["y"] - rs["y"])
        if math.isfinite(d) and d > 0.0:
            d_sh = d

    def ratio(hip: Point | None) -> Point | None:
        if s_t is None or hip is None or d_sh is None:
            return None
        return (s_t[0] - hip[0]) / d_sh, (s_t[1] - hip[1]) / d_sh

    return {
        "S_t": s_t, "H_t": h_t, "H0": h0, "S0": s0, "D_sh": d_sh,
        "dS": _sub(s_t, s0), "dH": _sub(h_t, h0),
        "SH_dynamic": ratio(h_t), "SH_fixed": ratio(h0),
    }


def _pt(p: Point | None) -> str:
    return "N/A" if p is None else f"({p[0]:+.3f},{p[1]:+.3f})"


def fixed_hip_lines(collector: BaselineCollector,
                    diag: Mapping[str, Any]) -> list[str]:
    d_sh = diag["D_sh"]
    d_txt = "N/A" if d_sh is None else f"{d_sh:.3f}"
    return [
        FIXED_HIP_LABEL,
        "  " + FIXED_HIP_NOTE,
        collector.status_text(),
        f"S(t)  ={_pt(diag['S_t'])}  D_sh={d_txt}",
        f"H(t)  ={_pt(diag['H_t'])}  (MediaPipe)",
        f"H0    ={_pt(diag['H0'])}  (fixed)",
        f"S(t)-S0={_pt(diag['dS'])}",
        f"H(t)-H0={_pt(diag['dH'])}",
        f"SH_dynamic(x,y)={_pt(diag['SH_dynamic'])}",
        f"SH_fixed  (x,y)={_pt(diag['SH_fixed'])}",
        "norm. image x/y; not 3D, not anatomical",
    ]


def _fmt(value: float | None, spec: str = "+.3f") -> str:
    return "n/a" if value is None else format(value, spec)


def panel_lines(
    records: Sequence[Mapping[str, Any]],
    image_width: int,
    image_height: int,
    pad: int,
    pose_detected: bool,
    fixed_hip: tuple[BaselineCollector, Mapping[str, Any]] | None = None,
) -> list[str]:
    lines = [BANNER, "diagnostic only: no F1/F2, no classification"]
    if not pose_detected:
        lines.append("POSE NOT DETECTED (no landmarks this frame)")
    for r in records:
        head = f"[{r['index']}] {r['name']}"
        if r["status"] != STATUS_OK:
            lines.append(f"{head}: {r['status'].upper()}"
                         f"  vis={_fmt(r['visibility'], '.2f')}"
                         f" pres={_fmt(r['presence'], '.2f')}")
            continue
        place = canvas_placement(r["x"], r["y"], image_width, image_height, pad)
        state = "IN" if r["in_frame"] else f"OUT({place['direction']})"
        if place["zone"] == "beyond_padding":
            state += " >PAD"
        lines.append(f"{head}: {state}")
        lines.append(f"   x={r['x']:+.4f} y={r['y']:+.4f}"
                     f"  vis={_fmt(r['visibility'], '.2f')}"
                     f" pres={_fmt(r['presence'], '.2f')}")
        lines.append(f"   margin L={r['margin_left']:+.3f} R={r['margin_right']:+.3f}"
                     f" T={r['margin_top']:+.3f} B={r['margin_bottom']:+.3f}")
    mid = midpoint_diagnostic(records, image_width, image_height)
    if mid is None:
        lines.append("shoulder-mid -> hip-mid 2D: n/a (needs all 4 finite)")
    else:
        lines.append(f"shoulder-mid -> hip-mid 2D: {mid['distance_px']:.0f}px"
                     f" = {mid['distance_image_heights']:.2f} img-heights")
        lines.append("   (projected, diagnostic only; not a feature)")
    lines.append(DISCLAIMER)
    if fixed_hip is not None:
        lines.extend(fixed_hip_lines(*fixed_hip))
    return lines


def _draw_hip_markers(canvas: np.ndarray, diag: Mapping[str, Any],
                      w: int, h: int, pad: int) -> None:
    """Current MediaPipe hip midpoint (magenta ring) and fixed H0 (orange cross)."""

    import cv2

    canvas_h, canvas_w = canvas.shape[:2]
    pts = {}
    for key, color, label in (("H_t", HIP_CURRENT_COLOR, "H(t) MediaPipe hip"),
                              ("H0", HIP_FIXED_COLOR, "H0 fixed hip")):
        p = diag.get(key)
        if p is None:
            continue
        place = canvas_placement(p[0], p[1], w, h, pad)
        px, py = int(round(place["draw"][0])), int(round(place["draw"][1]))
        pts[key] = (px, py)
        if key == "H_t":
            cv2.circle(canvas, (px, py), 9, color, 3, cv2.LINE_AA)
        else:
            cv2.drawMarker(canvas, (px, py), color, cv2.MARKER_CROSS, 24, 3)
        tx = min(px + 12, canvas_w - 200)
        ty = min(max(py + (22 if key == "H0" else -12), 14), canvas_h - 6)
        cv2.putText(canvas, label, (max(tx, 2), ty), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 1, cv2.LINE_AA)
    if len(pts) == 2:
        cv2.line(canvas, pts["H_t"], pts["H0"], (255, 255, 255), 1, cv2.LINE_AA)


def render_debug_image(
    bgr: np.ndarray,
    records: Sequence[Mapping[str, Any]],
    pad: int,
    pose_detected: bool = True,
    fixed_hip: tuple[BaselineCollector, Mapping[str, Any]] | None = None,
) -> np.ndarray:
    """Padded RGB canvas with markers + status panel on the right (new array)."""

    import cv2

    if pad < 0:
        raise ValueError("pad must be >= 0")
    h, w = bgr.shape[:2]
    canvas_w, canvas_h = w + 2 * pad, h + 2 * pad
    canvas = np.full((canvas_h, canvas_w, 3), 40, dtype=np.uint8)
    canvas[pad:pad + h, pad:pad + w] = bgr
    cv2.rectangle(canvas, (pad, pad), (pad + w - 1, pad + h - 1), (0, 255, 255), 2)
    cv2.putText(canvas, "image boundary", (pad + 6, pad + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

    colors = {idx: color for idx, _, color in DEBUG_LANDMARKS}
    for r in records:
        if r["status"] != STATUS_OK:
            continue
        color = colors[r["index"]]
        place = canvas_placement(r["x"], r["y"], w, h, pad)
        px, py = int(round(place["draw"][0])), int(round(place["draw"][1]))
        label = f"{r['index']} {r['name']}"
        if place["zone"] == "beyond_padding":
            cv2.drawMarker(canvas, (px, py), color, cv2.MARKER_TRIANGLE_UP, 16, 2)
            label += f" OUT({place['direction']}) beyond pad"
        elif place["zone"] == "padding":
            cv2.circle(canvas, (px, py), 7, color, 2, cv2.LINE_AA)
            label += f" OUT({place['direction']})"
        else:
            cv2.circle(canvas, (px, py), 6, color, -1, cv2.LINE_AA)
        tx = min(px + 9, canvas_w - 260)
        ty = min(max(py - 9, 14), canvas_h - 6)
        cv2.putText(canvas, label, (max(tx, 2), ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if fixed_hip is not None:
        _draw_hip_markers(canvas, fixed_hip[1], w, h, pad)
    cv2.putText(canvas, BANNER, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 210, 255), 2, cv2.LINE_AA)

    panel = np.full((canvas_h, PANEL_WIDTH, 3), 24, dtype=np.uint8)
    y = 24
    for i, text in enumerate(
            panel_lines(records, w, h, pad, pose_detected, fixed_hip)):
        color = (0, 210, 255) if i == 0 else (235, 235, 235)
        if text == DISCLAIMER:
            color = (120, 180, 255)
        elif text == FIXED_HIP_LABEL:
            color = (0, 200, 255)
        elif text.startswith(("H(t)", "SH_dynamic")):
            color = HIP_CURRENT_COLOR
        elif text.startswith(("H0", "SH_fixed")):
            color = HIP_FIXED_COLOR
        text = text.replace("\u2014", "-")  # Hershey font has no em dash
        cv2.putText(panel, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                    color, 1, cv2.LINE_AA)
        y += 20
        if y > canvas_h - 6:
            break
    return np.hstack([canvas, panel])


def save_snapshot(image: np.ndarray, snapshot_dir: str | None,
                  counter: int = 0) -> str | None:
    """Opt-in PNG save.  Returns the path, or None when saving is not enabled."""

    import cv2

    if not snapshot_dir:
        print("[viewer] snapshot not saved: pass --snapshot-dir DIR to enable")
        return None
    if not os.path.isdir(snapshot_dir):
        print(f"[viewer] snapshot not saved: directory does not exist: {snapshot_dir}")
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(snapshot_dir, f"pose_debug_{stamp}_{counter:03d}.png")
    if os.path.exists(path):  # never overwrite
        print(f"[viewer] snapshot not saved: already exists: {path}")
        return None
    if not cv2.imwrite(path, image):
        print(f"[viewer] snapshot write failed: {path}")
        return None
    print(f"[viewer] snapshot saved: {path}")
    return path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NON-FORMAL raw shoulder/hip PoseLandmarker debug viewer.")
    parser.add_argument("--snapshot-dir", metavar="DIR", default=None,
                        help="existing local directory enabling the 's' PNG snapshot; "
                             "default: nothing is written")
    parser.add_argument("--pad", type=int, default=160,
                        help="padding (px) around the RGB image for out-of-frame "
                             "points; default 160")
    parser.add_argument("--display-scale", type=float, default=0.6,
                        help="window scale only (snapshots are full resolution)")
    args = parser.parse_args(argv)
    if args.pad < 0:
        parser.error("--pad must be >= 0")
    if not (0 < args.display_scale <= 2):
        parser.error("--display-scale must be in (0, 2]")
    return args


def run_viewer(snapshot_dir: str | None, pad: int, display_scale: float) -> None:
    """Live loop.  Hardware/MediaPipe dependencies load only here."""

    import cv2
    import mediapipe as mp
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
    pipeline = rs.pipeline()
    profile = None
    pose_landmarker = None
    try:
        profile = pipeline.start(capture_d455.make_config())
        align = rs.align(rs.stream.color)
        pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        last_ts = -1
        saved = 0
        collector = BaselineCollector()
        print("[viewer] NON-FORMAL ENGINEERING DEBUG; b = capture baseline, "
              "r = reset baseline, s = snapshot, q = quit")
        if not snapshot_dir:
            print("[viewer] no --snapshot-dir: 's' will not save anything")
        while True:
            frames = pipeline.wait_for_frames()
            ts = int(float(frames.get_timestamp()))
            color_frame = align.process(frames).get_color_frame()
            if not color_frame:
                continue
            bgr = np.asanyarray(color_frame.get_data())
            if ts <= last_ts:
                ts = last_ts + 1
            last_ts = ts
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            result = pose_landmarker.detect_for_video(mp_image, ts)
            detected = bool(result.pose_landmarks)
            landmarks = result.pose_landmarks[0] if detected else None
            h, w = bgr.shape[:2]
            records = extract_debug_landmarks(landmarks, w, h)
            collector.update(records)
            diag = fixed_hip_diagnostics(records, collector.baseline)
            full = render_debug_image(bgr, records, pad, detected,
                                      (collector, diag))
            shown = full if display_scale == 1 else cv2.resize(
                full, None, fx=display_scale, fy=display_scale,
                interpolation=cv2.INTER_AREA)
            cv2.imshow(WINDOW_NAME, shown)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("b"):
                collector.start()
            elif key == ord("r"):
                collector.reset()
            elif key == ord("s"):
                if save_snapshot(full, snapshot_dir, saved) is not None:
                    saved += 1
    finally:
        if pose_landmarker is not None:
            pose_landmarker.close()
        if profile is not None:
            pipeline.stop()
        cv2.destroyAllWindows()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_viewer(args.snapshot_dir, args.pad, args.display_scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
