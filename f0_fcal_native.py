"""5-D-7 offline native recording -> independent F0 input artifacts.

No camera capture, downloads, fitting or metric calculation. Native playback
uses the existing SDK reader pattern and research_d455.PacketSource; observation
coordinates reuse live_f1_d455.f1_frame_input. Synthetic injection is test-only
and is marked in every generated provenance artifact.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path

import analyze_d455 as canonical
import capture_d455
import f0_fcal_input as input_validation
import live_f1_d455 as live
from research_d455 import PacketSource, open_observer
from rf_experiment import file_identity, read_pinned_json, verify_file
from f0_fcal_features import Segment, first_upright_references
from f0_fcal_input import INTERFACE, InsufficientInput, _Sources, _ReplayClock, _require, load_evaluation_input


REQUEST_INTERFACE = "f0-fcal-native-request-engineering-v1"


class NativePackets:
    """Existing native SDK replay primitive; stopped EOF is distinct from timeout."""
    kind = "native-sdk-offline"

    def __init__(self, path):
        self.path, self.completed = str(path), False

    def __enter__(self):
        import pyrealsense2 as rs
        self.rs, self.pipe = rs, rs.pipeline()
        cfg = rs.config()
        cfg.enable_device_from_file(self.path, repeat_playback=False)
        try:
            self.playback = self.pipe.start(cfg).get_device().as_playback()
            self.playback.set_real_time(False)
        except BaseException:
            try:
                self.pipe.stop()
            except RuntimeError:
                pass
            raise
        return self

    def __iter__(self):
        source = PacketSource()
        while True:
            ok, frames = self.pipe.try_wait_for_frames(5000)
            if not ok:
                _require(self.playback.current_status() == self.rs.playback_status.stopped,
                         "native_timeout_not_verified_EOF")
                self.completed = True
                return
            packet = source.receive(frames)
            # MediaPipe accepts integer milliseconds, not an invented +1 time
            # when the SDK reuses a color child in a new depth frameset.
            color = packet.timing["color"]
            packet.timing["mediapipe_ts_ms"] = int(color["timestamp_ms"]) if color else None
            packet.validate()
            yield packet

    def __exit__(self, *args):
        self.pipe.stop()


def observation_from_results(face, pose, width, height):
    """Reuse existing bbox-centre/shoulder semantics; add true bbox dimensions."""
    row = live.f1_frame_input(face, pose, width, height)
    row["pose_detected"] = bool(getattr(pose, "pose_landmarks", None))
    detection = live.largest_face_detection(face)
    if detection is not None:
        box = detection.bounding_box
        row.update(face_w_px=box.width, face_h_px=box.height, face_area_px=box.width * box.height)
    return row


def _stream_evidence(packet, name):
    descriptor = packet.timing.get(name)
    if descriptor is None:
        return None
    array = packet.color_bgr if name == "color" else packet.depth_z16
    return {**{key: descriptor[key] for key in
               ("frame_number", "timestamp_ms", "timestamp_domain", "height", "width", "format")},
            "payload_sha256": hashlib.sha256(array.tobytes()).hexdigest()}


@contextmanager
def native_observer(model_dir):
    paths = live.verified_model_paths(model_dir)  # Existing locks; never downloads.
    with open_observer(paths) as observer:
        class F0Observer:
            kind = "locked-mediapipe-face-pose"
            model_artifacts = {name: file_identity(path) for name, path in paths.items()}
            previous_color = None
            previous_observation = None
            previous_mp_timestamp = None

            def observe(self, packet):
                if packet.color_bgr is None:
                    return observation_from_results(None, None, 0, 0)
                color = _stream_evidence(packet, "color")
                if self.previous_color is not None:
                    if color["frame_number"] == self.previous_color["frame_number"]:
                        _require(color == self.previous_color, "native_color_reuse_mismatch")
                        return dict(self.previous_observation)
                    _require(color["timestamp_domain"] == self.previous_color["timestamp_domain"] and
                             color["frame_number"] > self.previous_color["frame_number"] and
                             color["timestamp_ms"] > self.previous_color["timestamp_ms"],
                             "native_color_clock_invalid")
                timestamp = packet.timing["mediapipe_ts_ms"]
                _require(timestamp == int(color["timestamp_ms"]) and
                         (self.previous_mp_timestamp is None or timestamp > self.previous_mp_timestamp),
                         "native_mediapipe_time_not_original_or_nonmonotonic")
                import cv2
                import mediapipe as mp
                height, width = packet.color_bgr.shape[:2]
                rgb = cv2.cvtColor(packet.color_bgr, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                face = observer.face_detector.detect(image)
                pose = observer.pose_detector.detect_for_video(image, timestamp)
                obs = observation_from_results(face, pose, width, height)
                self.previous_color, self.previous_observation = color, dict(obs)
                self.previous_mp_timestamp = timestamp
                return obs
        yield F0Observer()


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def _pin(path):
    return {k: v for k, v in file_identity(path).items() if k in ("path", "sha256")}


@dataclass(frozen=True)
class Generation:
    status: str
    reasons: tuple
    manifest_path: str | None = None
    manifest_sha256: str | None = None
    loaded: object = None


def _markers(recording, sources):
    raw = sources.path(recording["sources"]["raw"])
    marker_path = sources.path(recording["sources"]["markers"])
    camera = sources.json(recording["sources"]["capture"])
    _require(marker_path == raw.with_name(raw.stem + "_markers.csv"), "marker_sidecar_path_mismatch")
    _require(all(str(camera.get(k)) == recording[k] for k in ("recording_id", "subject", "round")),
             "capture_identity_mismatch")
    _require(camera.get("record_file") == raw.name, "capture_raw_file_mismatch")
    # This known producer writes frame_timestamp_ms from frames.get_timestamp().
    # Unknown/older producers are not certified from numeric timestamp overlap.
    producer = file_identity(capture_d455.__file__)
    _require(camera.get("capture_script_sha256") == producer["sha256"],
             "marker_clock_producer_not_verified")
    sources.path(producer)
    with marker_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        _require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)),
                 "marker_header_invalid")
        marks = list(reader)
    times, previous = [], None
    for mark in marks:
        _require(mark.get("recording_id") == recording["recording_id"], "marker_recording_mismatch")
        try:
            ts = float(mark["frame_timestamp_ms"])
        except (KeyError, ValueError, TypeError):
            # An unrelated, unselected end may lack a timestamp. It is never
            # used to bound a selected hold or to invent a frame time.
            times.append(None)
            continue
        _require(math.isfinite(ts) and (previous is None or ts > previous), "marker_timing_invalid")
        times.append(ts)
        previous = ts
    _require(bool(marks), "markers_missing")
    parsed = canonical.load_markers(raw)
    _require(len(parsed) == sum(t is not None for t in times), "marker_reader_fallback_not_allowed")
    intervals = []
    for s in recording["segments"]:
        a, b = s.get("hold_start_marker_index"), s.get("hold_end_marker_index")
        _require(type(a) is int and type(b) is int and 0 <= a < b < len(marks) and b == a + 1,
                 "explicit_hold_boundary_missing")
        _require(times[a] is not None and times[b] is not None,
                 "marker_device_timestamp_missing_capture_change_needed")
        _require(marks[a].get("phase") == "hold" and marks[a].get("step") == str(s["step"])
                 and marks[a].get("label") == s["label"], "hold_marker_identity_mismatch")
        _require(marks[b].get("phase") in ("prep", "transition", "end")
                 and marks[b].get("label") != "aborted", "hold_end_invalid")
        _require(times[b] - times[a] >= 10000, "short_hold_policy_unresolved")
        intervals.append((times[a], times[b], s))
    _require(all(b <= c or d <= a for i, (a, b, _) in enumerate(intervals)
                 for c, d, _ in intervals[i+1:]), "overlapping_hold_intervals")
    return raw, marker_path, camera, producer, marks, times, intervals


def _extract(recording, sources, model_dir, packet_factory, observer_factory):
    raw, marker_path, camera, producer, marks, times, intervals = _markers(recording, sources)
    observations, inventory, rows, domain = [], [], [], None
    replay_clock = _ReplayClock()
    with packet_factory(raw) as reader, observer_factory(model_dir) as observer:
        for index, packet in enumerate(reader, 1):
            packet.validate()
            ts = packet.timing.get("frameset_timestamp_ms")
            current_domain = packet.timing.get("frameset_timestamp_domain")
            streams = {name: _stream_evidence(packet, name) for name in ("color", "depth")}
            replay_clock.accept(ts, current_domain, streams)
            domain = replay_clock.domain
            obs = observer.observe(packet)
            # Sensor/model absence remains a row, not a frame drop.
            canonical._validate_frame_row(dict(obs, frame_schema_version=canonical.FRAME_SCHEMA_VERSION,
                recording_id=recording["recording_id"],
                analysis_run_id=recording["analysis_run_id"], face_depth_source="missing",
                shoulder_depth_source="missing"))
            metadata = {"frame_index": index, "ts_ms": ts,
                        "color_frame_number": (packet.timing.get("color") or {}).get("frame_number"),
                        "depth_frame_number": (packet.timing.get("depth") or {}).get("frame_number"),
                        "mediapipe_ts_ms": packet.timing.get("mediapipe_ts_ms")}
            inventory.append(dict(metadata, native_streams=streams))
            observations.append(dict(recording_id=recording["recording_id"],
                                     analysis_run_id=recording["analysis_run_id"],
                                     **metadata, timing=packet.timing, observations=obs))
            for start, end, s in intervals:
                if start <= ts < end:
                    row = dict.fromkeys(canonical.FRAME_FIELDS)
                    row.update({k: v for k, v in obs.items() if k in row})
                    row.update(metadata, frame_schema_version=canonical.FRAME_SCHEMA_VERSION,
                        subject=recording["subject"], round=recording["round"], step=str(s["step"]),
                        label=s["label"], t=(ts-start)/1000, recording_id=recording["recording_id"],
                        analysis_run_id=recording["analysis_run_id"], face_depth_source="missing",
                        shoulder_depth_source="missing")
                    rows.append(row)
        _require(getattr(reader, "completed", False) is True, "replay_completion_not_verified")
        backend = dict(reader=reader.kind, observer=observer.kind, models=observer.model_artifacts)
        for artifact in observer.model_artifacts.values():
            sources.path(artifact)
    _require(bool(inventory), "no_delivered_frames")
    by_ts = {}
    for row in inventory:
        by_ts.setdefault(row["ts_ms"], []).append(row)
    selected_boundaries = {s[k] for s in recording["segments"]
                           for k in ("hold_start_marker_index", "hold_end_marker_index")}
    bindings = []
    for i in sorted(selected_boundaries):
        mark, ts = marks[i], times[i]
        _require(ts in by_ts, "marker_not_bound_to_native_frame")
        candidates = by_ts[ts]
        number = mark.get("color_frame_number")
        if number not in (None, "", "None"):
            candidates = [r for r in candidates if float(number) == r["color_frame_number"]]
            _require(bool(candidates), "marker_color_frame_number_mismatch")
        _require(len(candidates) == 1, "marker_native_frame_binding_ambiguous")
        bound = candidates[0]
        bindings.append(dict(marker_index=i, ts_ms=ts, frame_index=bound["frame_index"],
                             color_frame_number=bound["color_frame_number"]))
    sources.recheck()
    return dict(recording=recording, raw=raw, markers=marker_path, camera=camera,
                producer=producer, observations=observations, inventory=inventory,
                rows=rows, domain=domain, backend=backend, marker_bindings=bindings)


def generate_evaluation_input(request_path, *, request_sha256, output_root, model_dir=None,
                              packet_factory=NativePackets, observer_factory=native_observer):
    """Explicit offline API. Tests inject synthetic readers/observers; no CLI auto-run.

    output_root must be new. Missing evidence returns unprocessed without
    producing consumable artifacts. The frozen reference key is never replaced.
    """
    try:
        request_path, root = Path(request_path).resolve(), Path(output_root).resolve()
        _require(not root.exists() and root.parent.is_dir(), "new_output_root_required")
        source = _Sources(request_path.parent)
        request = source.json(dict(path=str(request_path), sha256=request_sha256))
        _require(request.get("interface") == REQUEST_INTERFACE, "request_interface_invalid")
        recordings, segments, seen_runs = request.get("recordings"), [], set()
        _require(isinstance(recordings, list) and bool(recordings), "recording_list_missing")
        for r in recordings:
            for k in ("subject", "round", "recording_id", "analysis_run_id"):
                _require(isinstance(r.get(k), str) and bool(r[k]), "recording_identity_missing:" + k)
            _require(r["analysis_run_id"].startswith("ar_") and r["recording_id"] not in seen_runs,
                     "recording_run_duplicate_or_invalid")
            _require(all(Path(r[k]).name == r[k] and r[k] not in (".", "..")
                         for k in ("recording_id", "analysis_run_id")), "unsafe_output_identity")
            seen_runs.add(r["recording_id"])
            _require(isinstance(r.get("segments"), list) and bool(r["segments"]), "segment_list_missing")
            for s in r["segments"]:
                _require(s.get("session") in ("S1", "S2"), "session_missing_or_invalid")
                segments.append(Segment(r["subject"], r["recording_id"], r["analysis_run_id"],
                                        s["step"], s["order"], s["label"], ()))
        refs = {subject: tuple(key) for subject, key in request.get("reference_keys", {}).items()}
        _require(first_upright_references(segments) == refs, "fixed_first_P0_reference_missing_or_mismatch")
        for r in recordings:
            for s in r["segments"]:
                if (r["analysis_run_id"], r["recording_id"], s["step"]) == refs[r["subject"]]:
                    _require(s["session"] == "S1", "reference_must_be_S1")
        extracted = [_extract(r, source, model_dir, packet_factory, observer_factory) for r in recordings]
        source.recheck()
        root.mkdir()  # No artifacts before all evidence/EOF/clock checks succeed.
        output_segments = []
        for data in extracted:
            r, src = data["recording"], data["recording"]["sources"]
            directory = root / "analysis" / r["recording_id"] / r["analysis_run_id"]
            directory.mkdir(parents=True)
            settings = dict(raw_extraction_applied=True, trim_start_s=0, trim_end_s=0,
                            depth_alignment_target=None, f0_observations_only=True,
                            full_observations_preserved=True, canonical_projection="explicit_hold_intervals",
                            native_clock_validation="sensor-identity-and-payload-progress-v1")
            proof = dict(request=_pin(request_path), capture_producer=data["producer"],
                         generator=file_identity(__file__), backend=data["backend"],
                         marker_bindings=data["marker_bindings"],
                         dependencies={name: file_identity(module.__file__) for name, module in
                                       (("canonical", canonical), ("live_observation", live),
                                        ("input_validation", input_validation))})
            observations = directory / "all_observations.jsonl"
            with observations.open("x", encoding="utf-8") as stream:
                for obs in data["observations"]:
                    stream.write(json.dumps(obs, allow_nan=False) + "\n")
            frames = directory / "f0_frames.csv"
            canonical.write_frames_csv(frames, data["rows"])
            _require(frames.exists(), "no_hold_frames_exported")
            inventory = directory / "input_inventory.json"
            _write(inventory, dict(recording_id=r["recording_id"], raw_sha256=src["raw"]["sha256"],
                clock_domain=data["domain"], scope="all_delivered_frames",
                interval_ms=[data["inventory"][0]["ts_ms"], data["inventory"][-1]["ts_ms"]],
                frames=data["inventory"], extraction_settings=settings, provenance=proof))
            clock = directory / "clock_evidence.json"
            _write(clock, dict(recording_id=r["recording_id"], raw_sha256=src["raw"]["sha256"],
                markers_sha256=src["markers"]["sha256"], frame_field="ts_ms",
                marker_field="frame_timestamp_ms", unit="ms", same_clock=True, domain=data["domain"],
                evidence="known hash-pinned capture producer + exact native frame/marker binding",
                provenance=proof))
            owner = directory / "analysis_manifest.json"
            _write(owner, dict(interface="f0-native-generator-engineering-v1", status="completed",
                analysis_mode="extract_raw", analysis_run_id=r["analysis_run_id"], recording_id=r["recording_id"],
                subject=r["subject"], round=r["round"], options=dict(step_effective=1),
                dataset_role=data["camera"].get("dataset_role"),
                processing_settings=settings, provenance=proof,
                inputs={name: _pin(source.path(src[key])) for name, key in
                        (("recording", "raw"), ("markers", "markers"), ("capture_metadata", "capture"))},
                outputs=[dict(kind=kind, **_pin(path)) for kind, path in
                         (("frames", frames), ("all_observations", observations),
                          ("input_inventory", inventory), ("clock_evidence", clock))]))
            pins = dict(frames=_pin(frames), analysis=_pin(owner), markers=_pin(data["markers"]),
                        raw=_pin(data["raw"]), capture=_pin(source.path(src["capture"])),
                        clock_evidence=_pin(clock), input_inventory=_pin(inventory))
            for s in r["segments"]:
                output_segments.append(dict(subject=r["subject"], round=r["round"], recording_id=r["recording_id"],
                    analysis_run_id=r["analysis_run_id"], **s, sources=pins))
        source.recheck()
        session = root / "session_reference.json"
        _write(session, dict(interface=INTERFACE, segments=output_segments,
            reference_keys=request["reference_keys"], participant_splits=request.get("participant_splits", {}),
            request_manifest=_pin(request_path)))
        pin = _pin(session)
        loaded = load_evaluation_input(session, manifest_sha256=pin["sha256"])
        return Generation(loaded.status, tuple(i["reason"] for i in loaded.issues),
                          str(session), pin["sha256"], loaded)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, ImportError) as error:
        return Generation("unprocessed", (str(error),))
