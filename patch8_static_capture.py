"""Patch 8 dedicated static acquisition child (CAP-005 §24–§31); launched by patch8_validation.py.

One recording = one 10.0 s `upright` hold with protocol_version
`patch8-d455-static-validation-v1.0.0`, written with the existing capture-provenance/1.0.0
structure (recording_id, record_file, dataset_role, sidecar_files, protocol_version).
Static slots never use SEQ_CORE/SEQ_FULL, the production distance guide, or production
forward constants; `target_range_m` and `start_distance` are omitted (§28). Nominal
distance / repetition / attempt / execution identity live only in the Patch 8 ledger.

Static operator feedback firewall (§25): the window shows only phase identity, elapsed
timer, recording state and a plain mirrored RGB preview. This module never aligns depth,
measures distance, detects faces or landmarks, evaluates quality, or prints results; its
stdout/stderr are sealed by the orchestrator anyway. `capture_script_sha256` records the
byte hash of this executed capture script. No `_samples.csv` / `_quality.json` is written;
the sidecar naming map is kept because capture-provenance/1.0.0 requires it.

Exit status (structured, permitted pre-lock evidence §47.5): see patch8_prelock.STATIC_EXIT_STATUS.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid

import patch8_prelock as prelock
import patch8_protocol as p8


WINDOW = "patch8 static"
DISPLAY_W, DISPLAY_H, BAND_H = 960, 540, 84
STATIC_PHASE = "STATIC HOLD (upright)"
WARMUP_PHASE = "WARM-UP"
ALLOWED_PHASES = (STATIC_PHASE, WARMUP_PHASE)
MARKER_FIELDS = ("wall_time", "frame_timestamp_ms", "color_frame_number", "step", "phase", "label",
                 "planned_sec", "recording_id")
SIDECARS = (("camera", "json"), ("markers", "csv"), ("samples", "csv"), ("quality", "json"))
SCRIPT = os.path.abspath(__file__)


# ---------------------------------------------------------------- identity / provenance (§26, §28)
def validate_identity(subject, rnd, dataset_role):
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9-]+", subject):
        raise ValueError("subject must use letters, digits and hyphens only")
    if rnd not in p8.STATIC_ROUNDS:
        raise ValueError("static acquisition is only for Patch 8 static rounds 1-15")
    if dataset_role != p8.DATASET_ROLE:
        raise ValueError("Patch 8 static validation dataset_role must be pilot (§7.1)")


def _git(args):
    return subprocess.run(["git", *args], cwd=os.path.dirname(SCRIPT), capture_output=True, text=True,
                          check=True, timeout=3).stdout.strip()


def static_capture_provenance(subject, rnd, dataset_role, now=None, git=_git):
    validate_identity(subject, rnd, dataset_role)
    started = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=9), "Asia/Seoul"))
    stamp = started.strftime("%Y%m%d_%H%M%S")
    iso = started.isoformat(timespec="microseconds")
    info = {
        "schema_version": p8.CAPTURE_PROVENANCE_SCHEMA,
        "recording_id": f"{subject}_r{rnd}_{stamp}_{started.microsecond:06d}_{uuid.uuid4().hex}",
        "subject": subject, "round": rnd, "start_time": stamp,
        "dataset_role": dataset_role, "protocol_version": p8.STATIC_PROTOCOL_VERSION,
        "capture_start_time": iso, "capture_start_time_iso": iso, "capture_timezone": "Asia/Seoul",
        "git_commit": None, "git_dirty": None, "capture_script_sha256": None,
        "provenance_unknown_reasons": {},
    }
    for field, args in (("git_commit", ["rev-parse", "HEAD"]),
                        ("git_dirty", ["status", "--porcelain", "--untracked-files=normal"])):
        try:
            value = git(args)
            if field == "git_commit" and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
                raise ValueError("Git HEAD commit hash unavailable")
            info[field] = bool(value) if field == "git_dirty" else value
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            info["provenance_unknown_reasons"][field] = str(error)
    try:
        with open(SCRIPT, "rb") as stream:
            info["capture_script_sha256"] = hashlib.sha256(stream.read()).hexdigest()
    except OSError as error:
        info["provenance_unknown_reasons"]["capture_script_sha256"] = str(error)
    return info


def reserve_static_capture(subject, rnd, dataset_role, directory="data", **kwargs):
    """Exclusive camera-sidecar reservation with the same collision rule as production."""
    info = static_capture_provenance(subject, rnd, dataset_role, **kwargs)
    os.makedirs(directory, exist_ok=True)
    while True:
        base = os.path.join(directory, info["recording_id"])
        if not any(os.path.lexists(base + suffix) for suffix in prelock.CAPTURE_SUFFIXES):
            try:
                with open(base + "_camera.json", "x", encoding="utf-8") as stream:
                    info["record_file"] = None
                    info["sidecar_files"] = {name: os.path.basename(base + f"_{name}.{ext}") for name, ext in SIDECARS}
                    json.dump(info, stream, indent=2, ensure_ascii=False)
                return base, info
            except FileExistsError:
                pass
        info["recording_id"] = info["recording_id"].rsplit("_", 1)[0] + "_" + uuid.uuid4().hex


# ---------------------------------------------------------------- operator-visible firewall (§25)
def overlay_lines(phase, elapsed_s, total_s, recording):
    """The ONLY text the static utility may show: phase identity, elapsed timer, recording state."""
    if phase not in ALLOWED_PHASES:
        raise ValueError("phase identity outside the static firewall")
    return [f"PATCH 8 {phase}", f"ELAPSED {max(0.0, float(elapsed_s)):4.1f} / {float(total_s):.1f} s",
            "REC" if recording else "NOT RECORDING"]


def render(cv2, np, image, lines):
    """Plain RGB preview (mirrored like production) with the firewall text band only."""
    video = cv2.flip(cv2.resize(image, (DISPLAY_W, DISPLAY_H)), 1)
    canvas = np.full((BAND_H + DISPLAY_H, DISPLAY_W, 3), 32, np.uint8)
    canvas[BAND_H:] = video
    for index, line in enumerate(lines):
        cv2.putText(canvas, line, (14, 26 + 24 * index), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return canvas


# ---------------------------------------------------------------- acquisition
def _write_markers(base, markers):
    with open(base + "_markers.csv", "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=MARKER_FIELDS)
        writer.writeheader()
        writer.writerows(markers)


def record_static(subject, rnd, dataset_role, directory, *, rs, cv2, np, production, clock=time.time, **kwargs):
    base, provenance = reserve_static_capture(subject, rnd, dataset_role, directory, **kwargs)
    rid = provenance["recording_id"]
    profile = pipe = record = None
    for ext in (".db3", ".bag"):
        pipe = rs.pipeline()
        try:
            profile = pipe.start(production.make_config(base + ext))
            record = base + ext
            break
        except RuntimeError:
            continue
    if profile is None:
        return prelock.STATIC_EXIT_CODES["record_start_failed"]   # reservation preserved, record_file null

    device = profile.get_device()
    sensor = device.first_depth_sensor()
    color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
    depth_stream = profile.get_stream(rs.stream.depth).as_video_stream_profile()
    extrinsics = depth_stream.get_extrinsics_to(color_stream)
    info = {
        "subject": subject, "round": rnd, "start_time": provenance["start_time"],
        "record_file": os.path.basename(record), "fps": production.FPS,
        "sequence": [[p8.STATIC_MARKER_LABEL, p8.STATIC_HOLD_S]],
        "device": device.get_info(rs.camera_info.name),
        "serial": device.get_info(rs.camera_info.serial_number),
        "firmware": device.get_info(rs.camera_info.firmware_version),
        "usb": device.get_info(rs.camera_info.usb_type_descriptor)
        if device.supports(rs.camera_info.usb_type_descriptor) else "unknown",
        "depth_scale_m": sensor.get_depth_scale(),
        "color_intrinsics": production.intr_to_dict(color_stream.get_intrinsics()),
        "depth_intrinsics": production.intr_to_dict(depth_stream.get_intrinsics()),
        "depth_to_color_extrinsics": {"rotation": list(extrinsics.rotation),
                                      "translation": list(extrinsics.translation)},
    }
    try:
        info["stereo_baseline_mm"] = sensor.get_option(rs.option.stereo_baseline)
    except Exception:
        info["stereo_baseline_mm"] = None
    provenance["record_file"] = os.path.basename(record)
    info.update(provenance)
    with open(base + "_camera.json", "w", encoding="utf-8") as stream:
        json.dump(info, stream, indent=2, ensure_ascii=False)

    markers, started, aborted, failed = [], None, False, False
    try:
        while True:
            frames = pipe.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                continue
            now = clock()
            if started is None:
                started = now
                markers.append(dict(wall_time=now, frame_timestamp_ms=frames.get_timestamp(),
                                    color_frame_number=color.get_frame_number(), step=1, phase="hold",
                                    label=p8.STATIC_MARKER_LABEL, planned_sec=p8.STATIC_HOLD_S, recording_id=rid))
            elapsed = now - started
            if elapsed >= p8.STATIC_HOLD_S:
                break
            cv2.imshow(WINDOW, render(cv2, np, np.asanyarray(color.get_data()),
                                      overlay_lines(STATIC_PHASE, elapsed, p8.STATIC_HOLD_S, True)))
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                aborted = True
                break
    except RuntimeError:
        failed = True
    finally:
        try:
            pipe.stop()
        except Exception:
            failed = True
        markers.append(dict(wall_time=clock(), frame_timestamp_ms=None, color_frame_number=None, step=None,
                            phase="end", label="aborted" if aborted or failed else "end", planned_sec=None,
                            recording_id=rid))
        _write_markers(base, markers)
    if failed:
        return prelock.STATIC_EXIT_CODES["stream_failure"]
    return prelock.STATIC_EXIT_CODES["operator_abort" if aborted else "completed"]


def warm_up(seconds, *, rs, cv2, np, production, clock=time.time):
    """§11 initial warm-up: stream without recording; firewall display only."""
    pipe = rs.pipeline()
    try:
        pipe.start(production.make_config())
    except RuntimeError:
        return prelock.STATIC_EXIT_CODES["record_start_failed"]
    started, status = clock(), "completed"
    try:
        while clock() - started < seconds:
            frames = pipe.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                continue
            cv2.imshow(WINDOW, render(cv2, np, np.asanyarray(color.get_data()),
                                      overlay_lines(WARMUP_PHASE, clock() - started, seconds, False)))
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                status = "operator_abort"
                break
    except RuntimeError:
        status = "stream_failure"
    finally:
        try:
            pipe.stop()
        except Exception:
            status = "stream_failure"
    return prelock.STATIC_EXIT_CODES[status]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Patch 8 static acquisition child (launched by patch8_validation.py)")
    parser.add_argument("subject", nargs="?")
    parser.add_argument("round", nargs="?")
    parser.add_argument("--dataset-role", default=p8.DATASET_ROLE)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--warmup-seconds", type=float)
    args = parser.parse_args(argv)
    if args.warmup_seconds is None:
        try:
            validate_identity(args.subject, args.round, args.dataset_role)
        except ValueError as error:
            parser.error(str(error))
    elif args.warmup_seconds != p8.INITIAL_WARMUP_S or args.subject is not None:
        parser.error("warm-up runs alone for exactly 60 s (§11)")
    import cv2
    import numpy as np
    import pyrealsense2 as rs
    import capture_d455 as production
    try:
        if args.warmup_seconds is not None:
            return warm_up(args.warmup_seconds, rs=rs, cv2=cv2, np=np, production=production)
        return record_static(args.subject, args.round, args.dataset_role, args.data_dir,
                             rs=rs, cv2=cv2, np=np, production=production)
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
