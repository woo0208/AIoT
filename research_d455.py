"""Calibration-free research entry point (engineering implementation, NOT formal).

    python -B research_d455.py preview
    python -B research_d455.py preview --serial SERIAL --model-dir models
    python -B research_d455.py analyze --input TAKE_DIR --output NEW_ANALYSIS_DIR

Record is deliberately opt-in, one operator-supplied label per take. Only after
separate nonformal execution approval (this implementation task is NOT that):

    python -B research_d455.py record --output NEW_TAKE_DIR --subject P01 \
        --round 1 --label forward_head --duration 10 \
        --authorize-recording NONFORMAL_RECORDING_APPROVED \
        --authorization-ref ACTUAL_APPROVAL_REFERENCE

Output parents must already exist. Existing take/analysis paths are refused.
Duration expiry completes a take; q/Esc/window-close/Ctrl-C marks it interrupted.
Preview writes nothing. No mode launches the legacy capture executable, asks
for an upright reference, creates a Patch 8 registry, or runs classification.

Record format: research-rgbd-npz/0.1, protocol research-d455-engineering/0.1-unapproved.
Raw NPZs preserve delivered BGR8 and native Z16, separate sensor timestamps,
clock domains and frame numbers; camera.json preserves factory intrinsics,
extrinsics and depth scale (NOT individual posture calibration). No alignment
or synchronization-quality threshold is invented. SDK-delivered frames only:
the synchronous disk/inference loop may drop frames; number deltas expose gaps.

Analysis replays ALL indexed raw frames through the same locked face/pose
detectors, timestamps, f1_frame_input and unchanged FEAT-009 calculator. It
creates independent output with source hashes and new analysis identity.
--allow-incomplete explicitly permits failed/interrupted/unfinalized inputs;
corruption/truncated indexes still fail. Absence of end.json means unfinalized.

The f1_input object uses the canonical field names, coordinates and validity
semantics. This is NOT a canonical 60-field frames CSV: no legacy trimming,
step, depth ROI or mesh values are manufactured. Existing f1_csv_adapter and
the 3-class RF demo consume canonical CSVs, not this unapproved format. Their
aggregation/training policies are not imported here. F2 exposes inputs only;
OPEN-002/003/004/005, CAP-007/009 and formal 5-class model approval stay pending.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import math
from pathlib import Path
import sys
import time
import uuid

import numpy as np

import f1_features
import live_f1_d455 as live
import research_recording as storage


WINDOW = "D455 research | F1-5 geometry | NONFORMAL"


@dataclass(frozen=True)
class F2Input:
    """Future F2 boundary: native RGB-D + clock/calibration + 2D observations.

    Depth is NOT color-aligned. Consumers must explicitly design/approve the
    alignment, deprojection, validity and feature contracts before using it.
    This interface intentionally supplies no F2 formula or feature values.
    """

    packet: storage.RGBDPacket
    camera: dict
    f1_input: dict


class PacketSource:
    def __init__(self):
        self.last_mp_timestamp = -1
        self.previous_numbers = {}

    def receive(self, frames):
        host_ns, host_utc = time.monotonic_ns(), storage.utc_now()
        arrays, descriptors = {}, {}
        for name, frame in (("color", frames.get_color_frame()),
                            ("depth", frames.get_depth_frame())):
            if not frame:
                arrays[name], descriptors[name] = None, None
                continue
            arrays[name] = np.asanyarray(frame.get_data()).copy()
            number = frame.get_frame_number()
            previous = self.previous_numbers.get(name)
            descriptors[name] = {
                "frame_number": number, "timestamp_ms": frame.get_timestamp(),
                "timestamp_domain": str(frame.get_frame_timestamp_domain()),
                "height": arrays[name].shape[0], "width": arrays[name].shape[1],
                "format": "bgr8" if name == "color" else "z16",
                "number_delta": None if previous is None else number - previous,
            }
            self.previous_numbers[name] = number
        color, depth = descriptors["color"], descriptors["depth"]
        ts = None
        if color:
            ts = max(0, int(color["timestamp_ms"]), self.last_mp_timestamp + 1)
            self.last_mp_timestamp = ts
        comparable = bool(color and depth and color["timestamp_domain"] == depth["timestamp_domain"])
        timing = {**descriptors, "host_monotonic_ns": host_ns, "host_utc": host_utc,
                  "frameset_timestamp_ms": frames.get_timestamp(),
                  "frameset_timestamp_domain": str(frames.get_frame_timestamp_domain()),
                  "mediapipe_ts_ms": ts,
                  "color_minus_depth_ms": color["timestamp_ms"] - depth["timestamp_ms"] if comparable else None,
                  "clock_comparison": "same_domain" if comparable else "unavailable_or_different_domains"}
        packet = storage.RGBDPacket(arrays["color"], arrays["depth"], timing)
        packet.validate()
        return packet


class Observer:
    """Shared live/replay observation pipeline; no labels or baseline as input."""

    def __init__(self, face_detector, pose_detector):
        self.face_detector, self.pose_detector = face_detector, pose_detector
        self.last_timestamp = -1

    def observe(self, packet):
        packet.validate()
        face = pose = None
        width = height = 0
        if packet.color_bgr is not None:
            import cv2
            import mediapipe as mp

            timestamp = packet.timing["mediapipe_ts_ms"]
            if timestamp <= self.last_timestamp:
                raise ValueError("nonmonotonic observation timestamp")
            self.last_timestamp = timestamp
            height, width = packet.color_bgr.shape[:2]
            rgb = cv2.cvtColor(packet.color_bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            face = self.face_detector.detect(image)
            pose = self.pose_detector.detect_for_video(image, timestamp)
        row = live.f1_frame_input(face, pose, width, height)
        result = f1_features.compute_f1_5_frame(row)
        # FEAT-009 evaluates nonfinite observations BEFORE serialization. JSON
        # uses null with explicit diagnostics, never NaN or invented sentinels.
        nonfinite = [key for key, value in row.items()
                     if isinstance(value, float) and not math.isfinite(value)]
        clean_row = {key: None if key in nonfinite else value for key, value in row.items()}
        return {
            "f1_input": clean_row, "nonfinite_input_fields": nonfinite,
            "features": dict(result.features), "family_available": dict(result.family_available),
            "family_reasons": {key: list(value) for key, value in result.family_reasons.items()},
            "missing_streams": [name for name in ("color", "depth") if packet.timing[name] is None],
            "feature_contract": "FEAT-009/F1-5", "f2_status": "NOT_IMPLEMENTED_UNAPPROVED",
            "classifier_status": "NO_FORMAL_MODEL",
        }


@contextmanager
def open_observer(paths):
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    import analyze_d455 as canonical

    with ExitStack() as stack:
        face = stack.enter_context(vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(base_options=mpt.BaseOptions(model_asset_path=paths["face"]),
                                       min_detection_confidence=canonical.FACE_MIN_DETECTION_CONFIDENCE)))
        pose = stack.enter_context(vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=paths["pose"]),
                                         running_mode=getattr(vision.RunningMode, canonical.LANDMARK_RUNNING_MODE),
                                         num_poses=canonical.POSE_NUM_POSES)))
        yield Observer(face, pose)


def camera_metadata(profile, rs):
    device = profile.get_device()
    color = profile.get_stream(rs.stream.color).as_video_stream_profile()
    depth = profile.get_stream(rs.stream.depth).as_video_stream_profile()

    def stream_info(stream):
        intrinsics = stream.get_intrinsics()
        return {"intrinsics": {**{key: getattr(intrinsics, key)
                                  for key in ("width", "height", "fx", "fy", "ppx", "ppy")},
                               "model": str(intrinsics.model), "coeffs": list(intrinsics.coeffs)},
                "fps": stream.fps(), "format": str(stream.format())}

    extrinsics = depth.get_extrinsics_to(color)
    return {"name": device.get_info(rs.camera_info.name),
            "serial": device.get_info(rs.camera_info.serial_number),
            "firmware": device.get_info(rs.camera_info.firmware_version),
            "depth_scale_m": device.first_depth_sensor().get_depth_scale(),
            "color": stream_info(color), "depth": stream_info(depth),
            "depth_to_color": {"rotation": list(extrinsics.rotation), "translation_m": list(extrinsics.translation)},
            "depth_alignment": "none_native_depth", "color_coordinates": "original_unmirrored"}


@contextmanager
def open_camera(serial=None):
    import pyrealsense2 as rs

    context = rs.context()
    devices = [device for device in context.query_devices()
               if "D455" in device.get_info(rs.camera_info.name)
               and (serial is None or device.get_info(rs.camera_info.serial_number) == serial)]
    if len(devices) != 1:
        raise RuntimeError("Expected one D455; connect it or select --serial, and close other camera apps")
    config = rs.config()
    config.enable_device(devices[0].get_info(rs.camera_info.serial_number))
    config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
    config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
    pipeline = rs.pipeline()
    profile = pipeline.start(config)
    try:
        yield pipeline, camera_metadata(profile, rs)
    finally:
        pipeline.stop()


def provenance(paths):
    import analyze_d455 as canonical

    reasons = {}
    root = Path(__file__).resolve().parent
    files = ("research_d455.py", "research_recording.py", "live_f1_d455.py",
             "f1_features.py", "analyze_d455.py", "mediapipe_model_lock.json")
    return {"environment": canonical.analysis_environment(reasons),
            "code": canonical.analysis_code(reasons),
            "source_sha256": {name: storage.sha256(root / name) for name in files},
            "models": {role: {"filename": Path(path).name, "sha256": storage.sha256(path)}
                       for role, path in paths.items()},
            "detector_options": {"face_min_detection_confidence": canonical.FACE_MIN_DETECTION_CONFIDENCE,
                                 "pose_num_poses": canonical.POSE_NUM_POSES,
                                 "pose_running_mode": canonical.LANDMARK_RUNNING_MODE},
            "unknown_reasons": reasons}


def draw(packet, observation, recording=False):
    import cv2

    bgr = packet.color_bgr
    canvas = np.zeros((720, 1900, 3), np.uint8)
    if bgr is not None:
        # Display resizing only; inference and storage always use original arrays.
        height, width = bgr.shape[:2]
        picture = bgr.copy()
        for _, state, x_key, y_key in live.POINT_FIELDS:
            row = observation["f1_input"]
            x, y = row[x_key], row[y_key]
            if row[state] is True and x is not None and y is not None and 0 <= x < width and 0 <= y < height:
                cv2.circle(picture, (min(width - 1, round(x)), min(height - 1, round(y))), 6, (0, 230, 255), -1)
        canvas[:, :1280] = cv2.resize(picture, (1280, 720))
    lines = ["RECORDING | UNAPPROVED NONFORMAL" if recording else "PREVIEW | NO RECORDING",
             "FEAT-009 / current frame / no baseline"]
    for name, value in observation["features"].items():
        unit = " rad" if name == "so_beta" else ""
        lines.append(f"{name}: " + ("N/A" if value is None else f"{value:+.4f}{unit}"))
    for family, reasons in observation["family_reasons"].items():
        lines.append(f"{family}: " + (", ".join(reasons) if reasons else "AVAILABLE"))
    lines.extend(["Missing streams: " + (", ".join(observation["missing_streams"]) or "none"),
                  f"RGB-depth dt (ms): {packet.timing['color_minus_depth_ms']}",
                  "Native depth below (display only; no alignment)",
                  "No F2 / no formal classifier", "q / Esc / close: stop"])
    for index, line in enumerate(lines):
        cv2.putText(canvas, line, (1290, 25 + index * 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, (240, 240, 240), 1, cv2.LINE_AA)
    if packet.depth_z16 is not None:
        # Colorization has no measurement/acceptance meaning and is never stored.
        visual = cv2.normalize(packet.depth_z16, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        visual = cv2.applyColorMap(visual, cv2.COLORMAP_TURBO)
        canvas[460:700, 1290:1890] = cv2.resize(visual, (600, 240))
    return canvas


def live_loop(pipeline, observer, *, writer=None, duration=None):
    import cv2

    source, started = PacketSource(), time.monotonic()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    try:
        cv2.resizeWindow(WINDOW, 1500, 720)
        while duration is None or time.monotonic() - started < duration:
            packet = source.receive(pipeline.wait_for_frames(timeout_ms=5000))
            index = writer.append_raw(packet) if writer else None
            observation = observer.observe(packet)
            if writer:
                writer.append_observation(index, observation)
            cv2.imshow(WINDOW, draw(packet, observation, recording=writer is not None))
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return "interrupted", "operator stopped preview/take"
        return "completed", "requested duration elapsed"
    finally:
        cv2.destroyWindow(WINDOW)


def run_live(args):
    recording = args.mode == "record"
    if recording:
        storage.authorize_recording(args.authorize_recording, args.authorization_ref)
        if not math.isfinite(args.duration) or args.duration <= 0:
            raise ValueError("duration must be positive and finite")
    paths = live.verified_model_paths(args.model_dir)
    writer = None
    if recording:
        writer = storage.RecordingWriter(args.output, subject=args.subject, round=args.round,
                                         label=args.label, authorization=args.authorize_recording,
                                         authorization_ref=args.authorization_ref, provenance=provenance(paths))
    status, reason = "failed", "runtime initialization failed"
    try:
        with open_observer(paths) as observer, open_camera(args.serial) as (pipeline, camera):
            if writer:
                writer.set_camera(camera)
            print("NONFORMAL recording" if writer else "Preview only: no files, no calibration, no classifier")
            status, reason = live_loop(pipeline, observer, writer=writer,
                                       duration=args.duration if recording else None)
    except KeyboardInterrupt:
        status, reason = "interrupted", "KeyboardInterrupt"
        raise
    except Exception as error:
        status, reason = "failed", f"{type(error).__name__}: {error}"
        raise
    finally:
        if writer:
            writer.finish(status, reason)


def analyze_recording(reader, output, observer, analysis_provenance):
    output = Path(output).resolve()
    if output == reader.directory or reader.directory in output.parents:
        raise ValueError("analysis destination must be outside the immutable source take")
    identity = {"analysis_run_id": "research_analysis_" + uuid.uuid4().hex,
                "recording_id": reader.identity["recording_id"],
                "protocol_version": storage.PROTOCOL_VERSION,
                "observation_version": storage.OBSERVATION_VERSION,
                "source_identity": reader.identity, "source_status": reader.status,
                "source_sha256": reader.source_hashes, "provenance": analysis_provenance,
                "created_at_utc": storage.utc_now()}
    output.mkdir()
    storage.write_json(output / "analysis.json", identity)
    status, reason, count = "failed", "analysis initialization failed", 0
    try:
        with (output / "observations.jsonl").open("x", encoding="utf-8") as stream:
            for index, packet in reader.packets():
                observation = observer.observe(packet)
                entry = {"analysis_run_id": identity["analysis_run_id"],
                         "recording_id": reader.identity["recording_id"], "frame_index": index,
                         "timing": packet.timing, **observation}
                stream.write(storage.json_text(entry) + "\n")
                stream.flush()
                count += 1
        status, reason = "completed", "all indexed raw frames replayed; no sample eligibility implied"
    except KeyboardInterrupt:
        status, reason = "interrupted", "KeyboardInterrupt"
        raise
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
        raise
    finally:
        storage.write_json(output / "end.json", {
            "analysis_run_id": identity["analysis_run_id"], "status": status, "reason": reason,
            "observation_count": count, "ended_at_utc": storage.utc_now(),
            "sha256": {name: storage.sha256(output / name) for name in ("analysis.json", "observations.jsonl")
                       if (output / name).is_file()},
        })


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in ("preview", "record", "analyze"):
        sub = modes.add_parser(name)
        sub.add_argument("--model-dir", type=Path, default=Path(__file__).resolve().parent / "models")
        if name != "analyze":
            sub.add_argument("--serial")
        if name == "record":
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--subject", required=True)
            sub.add_argument("--round", required=True)
            sub.add_argument("--label", required=True, help="Operator label; no classifier or sequence mapping")
            sub.add_argument("--duration", type=float, required=True)
            sub.add_argument("--authorize-recording", help="Explicit nonformal recording approval acknowledgment")
            sub.add_argument("--authorization-ref", help="Reference to separately obtained execution approval")
        if name == "analyze":
            sub.add_argument("--input", type=Path, required=True)
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--allow-incomplete", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "analyze":
            reader = storage.RecordingReader(args.input, allow_incomplete=args.allow_incomplete)
            paths = live.verified_model_paths(args.model_dir)
            with open_observer(paths) as observer:
                analyze_recording(reader, args.output, observer, provenance(paths))
        else:
            run_live(args)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"Research D455 stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
