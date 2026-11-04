"""5-D-6 pinned canonical/marker/session loader. No extraction, fitting or writes.

The separate manifest is an engineering input interface, not a frozen schema.
See F0_FCAL_5D6_INPUT.md for its evidence contract and unprocessed conditions.
"""

import csv
from dataclasses import dataclass, replace
import math
from pathlib import Path

from analyze_d455 import load_markers
from f1_csv_adapter import read_canonical_frame_rows
from rf_experiment import canonical_input, read_pinned_json, verify_file
from f0_fcal_features import Segment
from f0_fcal_evaluation import TimedSegment, analysis_label, prepare_samples, evaluation_input


INTERFACE = "f0-fcal-session-input-engineering-v1"


class InsufficientInput(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise InsufficientInput(reason)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class _ReplayClock:
    """Validate composite time without mistaking a reused child for a duplicate set.

    Legacy inventories without sensor evidence still require strictly increasing
    time. Equal composite time needs an unchanged child and a different advancing
    child, with original sensor identities and payload hashes preserved.
    """

    def __init__(self):
        self.previous = None
        self.domain = None
        self.streams = {}

    def accept(self, ts, domain, streams=None):
        _require(streams is None or isinstance(streams, dict), "native_sensor_evidence_invalid")
        _require(_finite(ts) and (self.previous is None or ts >= self.previous),
                 "replay_timestamp_invalid_or_nonmonotonic")
        _require(isinstance(domain, str) and bool(domain), "replay_clock_domain_missing")
        self.domain = self.domain or domain
        _require(domain == self.domain, "replay_clock_domain_changed")
        equal = self.previous is not None and ts == self.previous
        advanced, repeated_clock_child, clock_child, present = False, False, False, False
        for name in ("color", "depth"):
            current = (streams or {}).get(name)
            if current is None:
                continue
            _require(isinstance(current, dict), "native_sensor_evidence_invalid")
            present = True
            number, stamp = current.get("frame_number"), current.get("timestamp_ms")
            child_domain, digest = current.get("timestamp_domain"), current.get("payload_sha256")
            _require(type(number) is int and number >= 0 and _finite(stamp) and
                     isinstance(child_domain, str) and bool(child_domain) and
                     isinstance(digest, str) and len(digest) == 64 and
                     all(c in "0123456789abcdef" for c in digest), "native_sensor_evidence_invalid")
            old = self.streams.get(name)
            clock_match = stamp == ts and child_domain == domain
            clock_child |= clock_match
            if old is not None:
                _require(child_domain == old["timestamp_domain"], "native_sensor_clock_domain_changed")
                _require(number >= old["frame_number"], "native_sensor_number_reversed")
                if number == old["frame_number"]:
                    _require(current == old, "native_sensor_reuse_identity_or_payload_mismatch")
                    repeated_clock_child |= clock_match
                else:
                    _require(stamp > old["timestamp_ms"], "native_sensor_time_not_increasing")
                    advanced = True
            else:
                advanced = True
            self.streams[name] = dict(current)
        _require(not present or clock_child, "frameset_clock_not_bound_to_sensor")
        _require(not equal or (advanced and repeated_clock_child),
                 "replay_timestamp_equal_without_verified_sensor_progress")
        self.previous = ts


@dataclass(frozen=True)
class LoadedInput:
    status: str
    timed_segments: tuple
    samples: tuple
    evaluation: dict | None
    issues: tuple
    source_artifacts: tuple


class _Sources:
    def __init__(self, root):
        self.root = root
        self.artifacts = {}

    def path(self, spec):
        _require(isinstance(spec, dict) and isinstance(spec.get("path"), str)
                 and isinstance(spec.get("sha256"), str), "source_path_or_hash_missing")
        path = Path(spec["path"])
        path = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        verify_file(path, spec["sha256"])
        _require(str(path) not in self.artifacts or self.artifacts[str(path)] == spec["sha256"],
                 "conflicting_source_hash")
        self.artifacts[str(path)] = spec["sha256"]
        return path

    def json(self, spec):
        path = self.path(spec)
        value, identity = read_pinned_json(path)
        _require(identity["sha256"] == spec["sha256"], "source_changed_during_read")
        _require(isinstance(value, dict), "source_json_object_required")
        return value

    def recheck(self):
        for path, digest in self.artifacts.items():
            verify_file(path, digest)


def _identity(entry):
    _require(isinstance(entry, dict), "segment_manifest_object_required")
    for key in ("subject", "recording_id", "analysis_run_id", "round", "label"):
        _require(isinstance(entry.get(key), str) and bool(entry[key]), "segment_identity_missing:" + key)
    _require(type(entry.get("step")) is int and entry["step"] >= 0, "step_missing_or_invalid")
    _require(type(entry.get("order")) is int and entry["order"] >= 0, "acquisition_order_missing_or_invalid")
    analysis_label(entry["label"])
    return (entry["analysis_run_id"], entry["recording_id"], entry["step"])


def _load_segment(entry, sources):
    key = _identity(entry)
    _require(entry.get("session") in ("S1", "S2"), "session_missing_or_invalid")
    src = entry.get("sources", {})
    paths = {name: sources.path(src.get(name))
             for name in ("frames", "analysis", "markers", "capture", "raw")}
    _require(paths["analysis"] == paths["frames"].parent / "analysis_manifest.json",
             "analysis_owner_path_mismatch")
    resolved = canonical_input(paths["frames"], paths["frames"].parent.parent.parent)
    _require(tuple(resolved[k] for k in ("analysis_run_id", "recording_id", "subject", "round")) ==
             (entry["analysis_run_id"], entry["recording_id"], entry["subject"], entry["round"]),
             "canonical_segment_identity_mismatch")
    owner = sources.json(src["analysis"])
    settings, options = owner.get("processing_settings", {}), owner.get("options", {})
    _require(owner.get("analysis_mode") == "extract_raw" and settings.get("raw_extraction_applied") is True,
             "raw_extraction_provenance_missing")
    _require(settings.get("trim_start_s") == 0 and settings.get("trim_end_s") == 0,
             "trimmed_or_unknown_trim_input_not_full_denominator")
    _require(type(options.get("step_effective")) is int and options["step_effective"] == 1,
             "strided_or_unknown_stride_input_not_full_denominator")
    for owner_key, source_key in (("recording", "raw"), ("markers", "markers"), ("capture_metadata", "capture")):
        _require(owner.get("inputs", {}).get(owner_key, {}).get("sha256") == src[source_key]["sha256"],
                 "analysis_input_hash_mismatch:" + source_key)
    camera = sources.json(src["capture"])
    _require(all(str(camera.get(k)) == entry[k] for k in ("recording_id", "subject", "round")),
             "capture_identity_mismatch")

    # Existing load_markers skips null timestamps and may synthesize old steps.
    # Validate the selected raw records first so neither fallback is accepted.
    _require(paths["markers"] == paths["raw"].with_name(paths["raw"].stem + "_markers.csv"),
             "markers_not_raw_sidecar")
    with paths["markers"].open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        _require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)),
                 "marker_header_invalid")
        markers = list(reader)
    a, b = entry.get("hold_start_marker_index"), entry.get("hold_end_marker_index")
    _require(type(a) is int and type(b) is int and 0 <= a < b < len(markers) and b == a + 1,
             "explicit_adjacent_hold_markers_missing")
    start, end = markers[a], markers[b]
    _require(start.get("recording_id") == entry["recording_id"] and
             end.get("recording_id") == entry["recording_id"], "marker_recording_identity_missing_or_mismatch")
    _require(start.get("phase") == "hold" and start.get("step") == str(entry["step"])
             and analysis_label(start.get("label")) == analysis_label(entry["label"]),
             "hold_start_marker_mismatch")
    _require(end.get("phase") in ("prep", "transition", "end") and end.get("label") != "aborted",
             "hold_end_marker_missing_or_aborted")
    try:
        start_ms, end_ms = float(start["frame_timestamp_ms"]), float(end["frame_timestamp_ms"])
    except (TypeError, ValueError, KeyError):
        raise InsufficientInput("hold_marker_device_timestamp_missing") from None
    _require(_finite(start_ms) and _finite(end_ms) and end_ms > start_ms,
             "hold_marker_timing_invalid")
    _require(end_ms - start_ms >= 10000, "short_hold_policy_unresolved")
    parsed_markers = load_markers(paths["raw"])
    for m, ts in ((start, start_ms), (end, end_ms)):
        _require(any(p["ts"] == ts and p["phase"] == m["phase"] and p["label"] == m["label"]
                     and p["step"] == (m.get("step") or "") for p in parsed_markers),
                 "marker_reader_identity_mismatch")

    clock = sources.json(src.get("clock_evidence"))
    _require(clock.get("recording_id") == entry["recording_id"] and
             clock.get("raw_sha256") == src["raw"]["sha256"] and
             clock.get("markers_sha256") == src["markers"]["sha256"] and
             clock.get("frame_field") == "ts_ms" and clock.get("marker_field") == "frame_timestamp_ms" and
             clock.get("unit") == "ms" and clock.get("same_clock") is True and
             isinstance(clock.get("domain"), str) and bool(clock["domain"]),
             "same_clock_evidence_missing_or_mismatch")
    inventory = sources.json(src.get("input_inventory"))
    _require(inventory.get("recording_id") == entry["recording_id"] and
             inventory.get("raw_sha256") == src["raw"]["sha256"] and
             inventory.get("clock_domain") == clock["domain"] and
             inventory.get("scope") == "all_delivered_frames",
             "complete_delivered_frame_inventory_missing")
    interval = inventory.get("interval_ms")
    _require(isinstance(interval, list) and len(interval) == 2 and all(_finite(t) for t in interval)
             and interval[0] <= start_ms and interval[1] >= end_ms,
             "inventory_does_not_cover_hold")
    delivered = inventory.get("frames")
    _require(isinstance(delivered, list), "delivered_frame_list_missing")
    indexed, replay_clock = {}, _ReplayClock()
    for frame in delivered:
        _require(isinstance(frame, dict) and type(frame.get("frame_index")) is int and
                 frame["frame_index"] >= 1 and _finite(frame.get("ts_ms")), "inventory_frame_invalid")
        idx, ts = frame["frame_index"], frame["ts_ms"]
        _require(idx not in indexed, "duplicate_or_nonmonotonic_inventory")
        replay_clock.accept(ts, inventory["clock_domain"], frame.get("native_streams"))
        indexed[idx] = ts

    rows = read_canonical_frame_rows(str(paths["frames"]))
    frame_ids = set()
    for row in rows:
        idx = row["frame_index"]
        _require(idx not in frame_ids, "duplicate_canonical_frame_identity")
        frame_ids.add(idx)
        _require((row["analysis_run_id"], row["recording_id"], row["subject"], row["round"]) ==
                 (entry["analysis_run_id"], entry["recording_id"], entry["subject"], entry["round"]),
                 "canonical_row_identity_mismatch")
    selected = [r for r in rows if r["step"] == str(entry["step"])]
    _require(all(analysis_label(r["label"]) == analysis_label(entry["label"]) for r in selected),
             "canonical_label_mismatch")
    # Compare actual identities/times, not len(CSV), FPS or maximum frame_index.
    expected = {idx: ts for idx, ts in indexed.items() if end_ms - 10000 <= ts < end_ms}
    observed = {r["frame_index"]: r["ts_ms"] for r in selected
                if _finite(r.get("ts_ms")) and end_ms - 10000 <= r["ts_ms"] < end_ms}
    _require(observed == expected, "analysis_window_inventory_mismatch")
    for r in selected:
        _require(_finite(r.get("ts_ms")) and indexed.get(r["frame_index"]) == r["ts_ms"],
                 "canonical_frame_not_bound_to_inventory")
    # Only the evidenced last-ten-second input list is delivered to the adapter.
    selected = [dict(r, time_s=r["ts_ms"] / 1000, phase="hold") for r in selected
                if r["frame_index"] in expected]
    sources.recheck()
    segment = Segment(entry["subject"], entry["recording_id"], entry["analysis_run_id"],
                      entry["step"], entry["order"], entry["label"], tuple(selected))
    return TimedSegment(segment, entry["session"], start_ms / 1000, end_ms / 1000, clock["domain"])


def load_evaluation_input(manifest_path, *, manifest_sha256=None, other_families=None):
    """Read pinned sources, return loader audit + existing six-column adapter output.

    Missing/contradictory provenance is unprocessed; no alternative P0/source is
    selected. A malformed manifest without usable identity is reported globally.
    No dataset-role promotion, source rewriting or capture/analysis invocation.
    """
    issues, items, keys = [], [], set()
    source = _Sources(Path(manifest_path).resolve().parent)
    try:
        manifest, identity = read_pinned_json(manifest_path)
        source.artifacts[identity["path"]] = identity["sha256"]
        _require(isinstance(manifest_sha256, str) and manifest_sha256 == identity["sha256"],
                 "session_reference_manifest_hash_missing_or_mismatch")
        _require(isinstance(manifest, dict), "session_reference_manifest_object_required")
        _require(manifest.get("interface") == INTERFACE, "unknown_loader_interface")
        entries = manifest.get("segments")
        _require(isinstance(entries, list) and bool(entries), "segment_manifest_missing")
        refs = manifest.get("reference_keys")
        _require(isinstance(refs, dict), "reference_manifest_missing")
        refs = {subject: tuple(key) for subject, key in refs.items()}
        for entry in entries:
            key = _identity(entry)
            _require(key not in keys, "duplicate_manifest_sample_key")
            keys.add(key)
            try:
                item = _load_segment(entry, source)
            except (OSError, ValueError, KeyError, TypeError) as error:
                issues.append(dict(sample_key=key, status="unprocessed", reason=str(error)))
                placeholder = Segment(entry["subject"], entry["recording_id"], entry["analysis_run_id"],
                                      entry["step"], entry["order"], entry["label"], ())
                item = TimedSegment(placeholder, entry.get("session"), None, None, None)
            items.append(item)
        samples = prepare_samples(items, refs)
        issue_map = {i["sample_key"]: i["reason"] for i in issues}
        samples = tuple(replace(s, reasons=s.reasons + ("loader:" + issue_map[s.sample_key],))
                        if s.sample_key in issue_map else s for s in samples)
        output = evaluation_input(samples, other_families=other_families,
                                  participant_splits=manifest.get("participant_splits"))
        output["execution_blockers"] = tuple(b for b in output["execution_blockers"]
                                              if b != "real_capture_loader_not_connected") + (
                                                  "actual_capture_path_not_validated",)
        source.recheck()
        status = "unprocessed" if any(s.status == "unprocessed" for s in samples) else "prepared"
        return LoadedInput(status, tuple(items), samples, output, tuple(issues),
                           tuple(dict(path=p, sha256=h) for p, h in source.artifacts.items()))
    except (OSError, ValueError, KeyError, TypeError) as error:
        issues.append(dict(sample_key=None, status="unprocessed", reason=str(error)))
        return LoadedInput("unprocessed", tuple(items), (), None, tuple(issues),
                           tuple(dict(path=p, sha256=h) for p, h in source.artifacts.items()))
