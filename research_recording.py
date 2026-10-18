"""Separate, non-formal RGB-D engineering storage for research_d455.

This is NOT frames-schema/1.0.0, a Patch 8 artifact, a dataset manifest, or
an approved collection protocol. Each NPZ contains the original delivered
BGR8 / native Z16 arrays, without alignment, resizing or lossy compression.
Missing streams are absent arrays, never fabricated images. frames.jsonl
binds each frameset's arrays, independent sensor clocks and host receipt time.
recording.json is immutable; end.json is written once on orderly termination.
Absent end.json means unfinalized, never successful. Files are exclusive-create.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid

import numpy as np


PROTOCOL_VERSION = "research-d455-engineering/0.1-unapproved"
STORAGE_VERSION = "research-rgbd-npz/0.1"
OBSERVATION_VERSION = "research-f1-observations/0.1"
AUTHORIZATION_ACK = "NONFORMAL_RECORDING_APPROVED"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def write_json(path, value):
    text = json_text(value)
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(text + "\n")


def read_json(path):
    def invalid(value):
        raise ValueError(f"non-finite JSON: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def authorize_recording(ack, reference):
    """Explicit operator attestation, NOT formal protocol/ethics authorization."""
    if ack != AUTHORIZATION_ACK:
        raise PermissionError(f"record requires --authorize-recording {AUTHORIZATION_ACK}")
    require_text(reference, "authorization reference")


@dataclass(frozen=True)
class RGBDPacket:
    """One delivered SDK frameset; color and depth have separate clock metadata."""

    color_bgr: np.ndarray | None
    depth_z16: np.ndarray | None
    timing: dict

    def validate(self):
        for name, array, dtype, dimensions in (
            ("color", self.color_bgr, np.uint8, 3),
            ("depth", self.depth_z16, np.uint16, 2),
        ):
            descriptor = self.timing.get(name)
            if array is None:
                if descriptor is not None:
                    raise ValueError(f"{name} metadata without array")
                continue
            if (array.dtype != dtype or array.ndim != dimensions
                    or (name == "color" and array.shape[2] != 3)
                    or min(array.shape) < 1):
                raise ValueError(f"invalid {name} raw array")
            if not isinstance(descriptor, dict):
                raise ValueError(f"missing {name} metadata")
            if [descriptor.get("height"), descriptor.get("width")] != list(array.shape[:2]):
                raise ValueError(f"{name} dimensions mismatch")
            if descriptor.get("format") != ("bgr8" if name == "color" else "z16"):
                raise ValueError(f"invalid {name} format")
            number = descriptor.get("frame_number")
            if type(number) is not int or number < 0:
                raise ValueError(f"invalid {name} frame number")
            timestamp = descriptor.get("timestamp_ms")
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError(f"invalid {name} timestamp")
            require_text(descriptor.get("timestamp_domain"), f"{name} clock domain")
        ts = self.timing.get("mediapipe_ts_ms")
        if self.color_bgr is None:
            if ts is not None:
                raise ValueError("MediaPipe timestamp without color")
        elif type(ts) is not int or ts < 0:
            raise ValueError("invalid MediaPipe timestamp")
        host = self.timing.get("host_monotonic_ns")
        if type(host) is not int or host < 0:
            raise ValueError("invalid host receipt time")
        require_text(self.timing.get("host_utc"), "host UTC")
        json_text(self.timing)


class RecordingWriter:
    """One label per explicitly approved take; upright is just another label.

    Raw is saved before inference, so detector failures cannot discard an
    already delivered frame. A crash may leave an unindexed NPZ: readers fail
    closed on that condition; they never silently call a partial take complete.
    """

    def __init__(self, directory, *, subject, round, label, authorization,
                 authorization_ref, provenance):
        authorize_recording(authorization, authorization_ref)
        for name, value in (("subject", subject), ("round", round), ("label", label)):
            require_text(value, name)
        self.directory = Path(directory)
        self.identity = {
            "recording_id": "research_" + uuid.uuid4().hex,
            "subject": subject, "round": round, "label": label,
            "protocol_version": PROTOCOL_VERSION, "storage_version": STORAGE_VERSION,
            "dataset_role": "engineering", "protocol_status": "UNAPPROVED_NONFORMAL",
            "created_at_utc": utc_now(),
            "authorization": {"ack": authorization, "reference": authorization_ref,
                              "scope": "operator-attested nonformal take only"},
            "provenance": provenance,
        }
        json_text(self.identity)  # Validate before reserving any output.
        self.directory.mkdir()  # Parent must exist; existing destinations refused.
        write_json(self.directory / "recording.json", self.identity)
        (self.directory / "raw").mkdir()
        self.frames = (self.directory / "frames.jsonl").open("x", encoding="utf-8")
        try:
            self.observations = (self.directory / "observations.jsonl").open("x", encoding="utf-8")
        except BaseException:
            self.frames.close()
            raise
        self.frame_count = self.observation_count = 0
        self.closed = False
        self.last_mp_timestamp = -1

    def set_camera(self, metadata):
        write_json(self.directory / "camera.json", metadata)

    def append_raw(self, packet):
        if self.closed:
            raise ValueError("recording closed")
        packet.validate()
        ts = packet.timing["mediapipe_ts_ms"]
        if ts is not None and ts <= self.last_mp_timestamp:
            raise ValueError("MediaPipe timestamps must strictly increase")
        index = self.frame_count + 1
        relative = f"raw/{index:08d}.npz"
        arrays = {name: array for name, array in
                  (("color_bgr", packet.color_bgr), ("depth_z16", packet.depth_z16))
                  if array is not None}
        with (self.directory / relative).open("xb") as stream:
            np.savez(stream, **arrays)
        entry = {"recording_id": self.identity["recording_id"], "frame_index": index,
                 "raw_path": relative, "sha256": sha256(self.directory / relative),
                 "timing": packet.timing}
        self.frames.write(json_text(entry) + "\n")
        self.frames.flush()
        self.frame_count = index
        if ts is not None:
            self.last_mp_timestamp = ts
        return index

    def append_observation(self, index, observation):
        if self.closed or index != self.observation_count + 1 or index != self.frame_count:
            raise ValueError("observation must match the latest raw frame in order")
        entry = {"recording_id": self.identity["recording_id"], "frame_index": index,
                 "observation_version": OBSERVATION_VERSION, **observation}
        self.observations.write(json_text(entry) + "\n")
        self.observations.flush()
        self.observation_count += 1

    def finish(self, status, reason):
        if self.closed:
            return
        if status not in ("completed", "interrupted", "failed"):
            raise ValueError("invalid termination status")
        if status == "completed" and (not self.frame_count or self.frame_count != self.observation_count):
            status, reason = "failed", "empty take or incomplete observations: " + reason
        self.frames.close()
        self.observations.close()
        self.closed = True
        files = ("recording.json", "frames.jsonl", "observations.jsonl", "camera.json")
        write_json(self.directory / "end.json", {
            "recording_id": self.identity["recording_id"], "status": status,
            "reason": reason, "ended_at_utc": utc_now(), "frame_count": self.frame_count,
            "observation_count": self.observation_count,
            "sha256": {name: sha256(self.directory / name) for name in files
                       if (self.directory / name).is_file()},
        })


class RecordingReader:
    """Validate hashes, identity, sequence and timing before replaying raw arrays."""

    def __init__(self, directory, *, allow_incomplete=False):
        self.directory = Path(directory).resolve(strict=True)
        self.identity = read_json(self.directory / "recording.json")
        if (self.identity.get("protocol_version") != PROTOCOL_VERSION
                or self.identity.get("storage_version") != STORAGE_VERSION
                or self.identity.get("dataset_role") != "engineering"
                or self.identity.get("protocol_status") != "UNAPPROVED_NONFORMAL"):
            raise ValueError("unsupported research recording contract")
        for field in ("recording_id", "subject", "round", "label"):
            require_text(self.identity.get(field), field)
        end_path = self.directory / "end.json"
        self.end = read_json(end_path) if end_path.exists() else None
        self.status = self.end["status"] if self.end else "unfinalized"
        if self.status not in ("completed", "interrupted", "failed", "unfinalized"):
            raise ValueError("unknown recording status")
        if self.status != "completed" and not allow_incomplete:
            raise ValueError(f"recording {self.status}; explicit --allow-incomplete required")
        if self.end:
            if self.end["recording_id"] != self.identity["recording_id"]:
                raise ValueError("terminal recording identity mismatch")
            required = {"recording.json", "frames.jsonl", "observations.jsonl"}
            if self.status == "completed":
                required.add("camera.json")
            hashes = self.end["sha256"]
            if not required <= hashes.keys() or set(hashes) - (required | {"camera.json"}):
                raise ValueError("terminal file inventory mismatch")
            for name, digest in hashes.items():
                if sha256(self.directory / name) != digest:
                    raise ValueError(f"recording hash mismatch: {name}")
        self.camera = read_json(self.directory / "camera.json")
        self.source_hashes = {name: sha256(self.directory / name)
                              for name in ("recording.json", "camera.json", "frames.jsonl")}
        if self.end:
            self.source_hashes["end.json"] = sha256(end_path)

    def packets(self):
        last_ts, count = -1, 0
        with (self.directory / "frames.jsonl").open(encoding="utf-8") as stream:
            for index, line in enumerate(stream, 1):
                entry = json.loads(line)
                expected_path = f"raw/{index:08d}.npz"
                if (entry.get("recording_id") != self.identity["recording_id"]
                        or entry.get("frame_index") != index or entry.get("raw_path") != expected_path):
                    raise ValueError("raw identity, sequence or path mismatch")
                path = self.directory / expected_path
                if path.resolve().parent != (self.directory / "raw").resolve():
                    raise ValueError("raw path escapes recording")
                if sha256(path) != entry["sha256"]:
                    raise ValueError(f"raw hash mismatch: {expected_path}")
                with np.load(path, allow_pickle=False) as raw:
                    if set(raw.files) - {"color_bgr", "depth_z16"}:
                        raise ValueError("unexpected raw arrays")
                    packet = RGBDPacket(raw["color_bgr"] if "color_bgr" in raw else None,
                                        raw["depth_z16"] if "depth_z16" in raw else None,
                                        entry["timing"])
                packet.validate()
                ts = packet.timing["mediapipe_ts_ms"]
                if ts is not None:
                    if ts <= last_ts:
                        raise ValueError("nonmonotonic MediaPipe replay time")
                    last_ts = ts
                count = index
                yield index, packet
        if self.end and count != self.end["frame_count"]:
            raise ValueError("terminal raw frame count mismatch")
        if len(list((self.directory / "raw").iterdir())) != count:
            raise ValueError("unindexed raw files; interrupted write requires explicit recovery")
        for name, digest in self.source_hashes.items():
            if sha256(self.directory / name) != digest:
                raise ValueError(f"source changed during replay: {name}")
