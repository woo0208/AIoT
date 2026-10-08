"""patch8-validation-control/1.0.0 operational governance ledger (CAP-005 §35–§40, §48–§54).

This is an append-only JSONL ledger, not a scientific schema and not Patch 6 selection.
Every append replays and validates the whole existing chain plus the new event with the
same rules `verify_ledger` uses, so an invalid lifecycle transition can neither be
written nor survive verification. Acquisition validity is immutable once
`validity_locked` is recorded; result-bearing evidence is only unsealed after
`attempt_end` (CAP-005 §40).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid

import patch8_protocol as p8


class LedgerError(ValueError):
    pass


class SealedResultError(PermissionError):
    """Raised when result-bearing evidence is requested before lock + attempt_end."""


COMMON_FIELDS = frozenset(("ledger_format_version", "execution_id", "session_id", "event_id",
                           "event_timestamp_utc", "event_type", "previous_event_sha256", "event_sha256"))
ATTEMPT_FIELDS = frozenset(("subject", "round", "attempt_index", "validation_protocol_version",
                            "recording_id", "status", "reason_code"))
STATIC_ATTEMPT_FIELDS = frozenset(("nominal_distance", "repetition_index"))
ATTEMPT_EVENT_STATUS = {
    "attempt_start": "started", "operator_observation": "observed", "capture_finished": "finished",
    "validity_locked": "locked", "attempt_end": "ended", "attempt_outcome": "outcome_recorded",
}
PAYLOAD_FIELDS = {
    "session_start": frozenset(("session_kind", "subject", "environment", "code_state", "recording_inventory")),
    "session_end": frozenset(("session_kind", "status")),
    "warmup_completed": frozenset(("duration_s", "exit_code", "logs")),
    "model_verification": frozenset(("status", "lock_sha256", "artifacts")),
    "integrity_check": frozenset(("phase", "exit_code", "summary", "counts")),
    "setup_verified": frozenset(("purpose", "camera_pose")),
    "camera_pose_recheck": frozenset(("camera_pose", "material_change", "differences")),
    "attempt_start": ATTEMPT_FIELDS | {"slot_kind", "sequence_mode", "setup_checks", "settling_s",
                                       "pre_launch_inventory", "code_state"},
    "operator_observation": ATTEMPT_FIELDS | {"observation", "retry_eligible"},
    "capture_finished": ATTEMPT_FIELDS | {"stage", "bound_recording_ids", "termination", "logs"},
    "validity_locked": ATTEMPT_FIELDS | {"stage", "acquisition_valid", "retry_allowed", "machine_evidence_ref",
                                         "evidence_used", "operator_declaration", "rule_id"},
    "attempt_end": ATTEMPT_FIELDS,
    "attempt_outcome": ATTEMPT_FIELDS | {"outcome", "evidence"},
    "analysis_invocation": frozenset(("subject", "round", "attempt_index", "recording_id", "invocation_index",
                                      "exit_code", "analysis_runs", "canonical_analysis_run_id", "logs")),
    "analysis_infrastructure_failure": frozenset(("subject", "round", "attempt_index", "recording_id",
                                                  "analysis_run_id", "evidence_ref", "evidence_sha256")),
    "execution_failed": frozenset(("reason_code", "detail")),
    "report_published": frozenset(("report_path", "report_sha256", "ledger_sha256_before")),
}
ATTEMPT_EVENTS = frozenset(ATTEMPT_EVENT_STATUS)
SETUP_CHECKS = ("hips_visually_unobstructed", "hands_forearms_clear_of_hips", "external_occluder_absent")
POSE_NUMERIC = ("reference_height_mm", "pitch_deg", "yaw_deg", "roll_deg")
POSE_TEXT = ("mount_identity", "camera_position", "witness_marks")
STAGES = ("pre_reservation", "post_reservation")
DECLARATIONS = ("operator_initiated", "not_operator_initiated", "unknown")
TERMINATION_FIELDS = frozenset(("exit_code", "signal", "orchestrator_timeout_kill", "operator_signal_observed",
                                "static_exit_status", "recovered", "reservation_observed_s"))
PINNED_ENVIRONMENT_KEYS = ("capture_host", "analysis_host", "os", "python", "packages",
                           "realsense_sdk_version", "d455_serial", "d455_firmware", "usb_type",
                           "depth_scale_m", "stream_profiles", "device_options")
REQUIRED_PACKAGE_KEYS = ("mediapipe", "pyrealsense2", "opencv-python", "numpy")
# After execution_failed no attempt may start; the in-flight attempt may still be closed
# (and locked without retry authority) and preserved evidence may still be analyzed.
AFTER_EXECUTION_FAILURE = frozenset(("session_end", "report_published", "integrity_check", "execution_failed",
                                     "analysis_invocation", "analysis_infrastructure_failure",
                                     "camera_pose_recheck", "model_verification", "operator_observation",
                                     "capture_finished", "validity_locked", "attempt_end", "attempt_outcome"))
ID_PATTERN = r"_[0-9]{8}T[0-9]{12}Z_[0-9a-f]{32}"
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
HEX64 = re.compile(r"[0-9a-f]{64}")


# ---------------------------------------------------------------- identifiers / serialization
def _new_id(prefix, now=None):
    now = now or datetime.now(timezone.utc)
    return f"{prefix}_{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}"


def new_execution_id(now=None):
    """Format only. A formal execution_id must come from the execution registry (§15)."""
    return _new_id("p8x", now)


def new_session_id(now=None):
    return _new_id("p8s", now)


def valid_id(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + ID_PATTERN, value) is not None


def utc_timestamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def json_safe(value):
    """Replace non-finite floats with null so canonical serialization never needs NaN."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def canonical_bytes(value):
    """CAP-005 §37: UTF-8, sort_keys, (",", ":"), ensure_ascii=False, no NaN/whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def event_hash(event):
    return hashlib.sha256(canonical_bytes({k: v for k, v in event.items() if k != "event_sha256"})).hexdigest()


def event_line(event):
    return canonical_bytes(event) + b"\n"


def _strict_json(line):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise LedgerError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise LedgerError(f"invalid JSON constant: {value}")

    try:
        return json.loads(line.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LedgerError(f"torn or invalid ledger line: {error}") from error


# ---------------------------------------------------------------- state
@dataclass
class Attempt:
    round: str
    attempt_index: int
    start: dict
    observations: list = field(default_factory=list)
    finished: dict = None
    locked: dict = None
    ended: dict = None
    outcome: dict = None

    @property
    def slot(self):
        return p8.slot(self.round)

    @property
    def recording_id(self):
        return (self.finished or {}).get("recording_id")

    def canonical(self):
        """§49 / §79 / §81: canonical status derived only from lock and post-lock outcome."""
        if self.ended is None or not self.locked["acquisition_valid"]:
            return False
        if self.slot.kind == p8.STATIC:
            return True
        return self.outcome is not None and self.outcome["outcome"] == p8.CANONICAL


@dataclass(frozen=True)
class UnsealToken:
    execution_id: str
    round: str
    attempt_index: int
    recording_id: str


class LedgerState:
    def __init__(self):
        self.events = []
        self.execution_id = None
        self.subject = None
        self.sessions = {}
        self.open_session = None
        self.baseline_environment = None
        self.baseline_code = None
        self.attempts = {}
        self.execution_failure = None
        self.model_verified = False
        self.pre_hardware_integrity = False
        self.closure_integrity = None
        self.analyses = {}
        self.reports = []

    # ------------------------------------------------------------ queries
    def slot_attempts(self, rnd):
        return [self.attempts[k] for k in sorted(self.attempts) if k[0] == rnd]

    def canonical_attempt(self, rnd):
        found = [a for a in self.slot_attempts(rnd) if a.canonical()]
        return found[0] if found else None

    def canonical_static_take_exists(self):
        return any(a.slot.kind == p8.STATIC and a.locked is not None and a.locked["acquisition_valid"]
                   for a in self.attempts.values())

    def open_attempt(self):
        return next((a for a in self.attempts.values() if a.ended is None), None)

    def retry_authority(self, attempt):
        """Whether `attempt` (ended) authorizes another attempt at the same slot."""
        if attempt.ended is None:
            return False
        if not attempt.locked["acquisition_valid"]:
            return bool(attempt.locked["retry_allowed"])
        kind = attempt.slot.kind
        return (kind in (p8.FORWARD, p8.BODY_ONLY_NEGATIVE) and attempt.outcome is not None and
                attempt.outcome["outcome"] == p8.TARGET_MISS_OUTCOME and attempt.attempt_index < p8.MAX_ATTEMPTS)

    def slot_resolved(self, rnd):
        attempts = self.slot_attempts(rnd)
        if self.canonical_attempt(rnd) is not None:
            return True
        return bool(attempts) and attempts[-1].ended is not None and not self.retry_authority(attempts[-1])

    def next_attempt_index(self, rnd):
        attempts = self.slot_attempts(rnd)
        if not attempts:
            return 1
        last = attempts[-1]
        if self.canonical_attempt(rnd) is not None or not self.retry_authority(last):
            return None
        return last.attempt_index + 1

    def unseal(self, rnd, attempt_index):
        attempt = self.attempts.get((rnd, attempt_index))
        if attempt is None or attempt.locked is None or attempt.ended is None:
            raise SealedResultError("result-bearing evidence is sealed until validity_locked and attempt_end")
        if attempt.recording_id is None:
            raise SealedResultError("attempt has no bound recording to unseal")
        return UnsealToken(self.execution_id, rnd, attempt_index, attempt.recording_id)

    def unseal_binding(self, rnd, attempt_index, recording_id):
        """Post-lock access to one recording bound by an ended attempt (reconciliation)."""
        attempt = self.attempts.get((rnd, attempt_index))
        if attempt is None or attempt.ended is None or \
                recording_id not in attempt.finished["bound_recording_ids"]:
            raise SealedResultError("recording is not bound by an ended attempt")
        return UnsealToken(self.execution_id, rnd, attempt_index, recording_id)

    def analysis_invocation_allowed(self, recording_id):
        """§52–§54: first invocation for a canonical recording; re-analysis only after a logged
        infrastructure failure and while no completed run exists."""
        if recording_id not in self.canonical_recordings():
            return False
        record = self.analyses.get(recording_id)
        if record is None or not record["invocations"]:
            return True
        last = self.events.index(record["invocations"][-1])
        return record["canonical"] is None and any(self.events.index(f) > last for f in record["failures"])

    def canonical_recordings(self):
        result = {}
        for rnd in p8.SLOTS:
            attempt = self.canonical_attempt(rnd)
            if attempt is not None and attempt.recording_id is not None:
                result[attempt.recording_id] = attempt
        return result


# ---------------------------------------------------------------- validation helpers
def _require(condition, message):
    if not condition:
        raise LedgerError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _strings(value, *, sorted_unique=True):
    return (isinstance(value, list) and all(isinstance(v, str) for v in value) and
            (not sorted_unique or value == sorted(set(value))))


def _artifact_ref(value):
    return (isinstance(value, dict) and set(value) == {"path", "sha256"} and _text(value["path"]) and
            isinstance(value["sha256"], str) and HEX64.fullmatch(value["sha256"]) is not None)


def _environment(value):
    """CAP-005 §9 explicit environment identities and equality-bearing fields."""
    if not isinstance(value, dict) or not all(k in value for k in PINNED_ENVIRONMENT_KEYS):
        return False
    packages = value["packages"]
    return (all(_text(value[k]) for k in ("capture_host", "analysis_host", "os", "python",
                                           "realsense_sdk_version", "d455_serial", "d455_firmware", "usb_type")) and
            _finite(value["depth_scale_m"]) and value["depth_scale_m"] > 0 and
            isinstance(packages, dict) and all(_text(packages.get(k)) for k in REQUIRED_PACKAGE_KEYS) and
            isinstance(value["stream_profiles"], dict) and bool(value["stream_profiles"]) and
            isinstance(value["device_options"], dict) and bool(value["device_options"]) and
            "error" not in value["device_options"])


def _logs(value, *, nullable=False):
    if value is None:
        return nullable
    return isinstance(value, dict) and set(value) == {"stdout", "stderr"} and all(map(_artifact_ref, value.values()))


def _pose(value, *, recheck):
    keys = set(POSE_NUMERIC) | set(POSE_TEXT) | ({"witness_mark_displaced"} if recheck else set())
    return (isinstance(value, dict) and set(value) == keys and all(_finite(value[k]) for k in POSE_NUMERIC) and
            all(_text(value[k]) for k in POSE_TEXT) and
            (not recheck or isinstance(value["witness_mark_displaced"], bool)))


def pose_differences(initial, recheck):
    """§7.4 exact material-change rule."""
    differences = {k: abs(recheck[k] - initial[k]) for k in POSE_NUMERIC}
    material = (differences["reference_height_mm"] > p8.POSE_HEIGHT_TOLERANCE_MM or
                any(differences[k] > p8.POSE_ANGLE_TOLERANCE_DEG for k in ("pitch_deg", "yaw_deg", "roll_deg")) or
                recheck["witness_mark_displaced"])
    return differences, material


def lock_retry_allowed(slot_kind, reason, attempt_index, canonical_static_take_exists, execution_failed):
    """§43, §44, §49, §79, §81: retry authority granted by a pre-result validity lock."""
    if execution_failed or attempt_index >= p8.MAX_ATTEMPTS:
        return False
    if reason in p8.MACHINE_INVALID_REASONS:
        return True
    if slot_kind == p8.STATIC and reason == p8.EXTERNAL_PHYSICAL_INTERRUPTION:
        return True
    if slot_kind == p8.STATIC and reason == p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED:
        return not canonical_static_take_exists
    return False


def acquisition_valid_for(reason):
    return reason not in p8.MACHINE_INVALID_REASONS + p8.STATIC_OPERATOR_INVALID_REASONS


def allowed_lock_reasons(slot_kind):
    reasons = (None,) + p8.MACHINE_INVALID_REASONS + (p8.MANUAL_ABORT, p8.UNCLASSIFIED_TERMINATION)
    if slot_kind == p8.STATIC:
        return reasons + p8.STATIC_OPERATOR_INVALID_REASONS
    return reasons + (p8.GUIDE_NOT_SATISFIED,)


def observation_retry_eligible(slot_kind, observation, canonical_static_take_exists):
    if slot_kind != p8.STATIC:
        return False   # §42: production live feedback exists; never retry-eligible
    if observation == p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED:
        return not canonical_static_take_exists
    return True


# ---------------------------------------------------------------- replay
def _common(state, event):
    _require(isinstance(event, dict), "ledger event must be an object")
    kind = event.get("event_type")
    _require(kind in PAYLOAD_FIELDS, f"unsupported event_type: {kind!r}")
    expected = COMMON_FIELDS | PAYLOAD_FIELDS[kind]
    if kind in ATTEMPT_EVENTS and p8.SLOTS.get(event.get("round")) is not None and \
            p8.SLOTS[event["round"]].kind == p8.STATIC:
        expected = expected | STATIC_ATTEMPT_FIELDS
    _require(set(event) == expected, f"{kind}: exact field set mismatch {sorted(set(event) ^ expected)}")
    _require(event["ledger_format_version"] == p8.LEDGER_FORMAT_VERSION, "unsupported ledger_format_version")
    _require(valid_id(event["execution_id"], "p8x"), "invalid execution_id")
    _require(valid_id(event["session_id"], "p8s"), "invalid session_id")
    _require(valid_id(event["event_id"], "p8e"), "invalid event_id")
    _require(isinstance(event["event_timestamp_utc"], str) and TIMESTAMP.fullmatch(event["event_timestamp_utc"]),
             "event_timestamp_utc must be UTC microsecond ISO-8601 with Z")
    if state.execution_id is None:
        state.execution_id = event["execution_id"]
    _require(event["execution_id"] == state.execution_id, "execution_id changed within ledger")
    _require(all(e["event_id"] != event["event_id"] for e in state.events), "duplicate event_id")
    if state.events:
        _require(event["event_timestamp_utc"] >= state.events[-1]["event_timestamp_utc"],
                 "event timestamps must be non-decreasing")
    previous = state.events[-1]["event_sha256"] if state.events else None
    _require(event["previous_event_sha256"] == previous, "hash chain previous_event_sha256 mismatch")
    _require(event["event_sha256"] == event_hash(event), "event_sha256 mismatch")
    if state.execution_failure is not None:
        _require(kind in AFTER_EXECUTION_FAILURE, f"{kind} not permitted after execution_failed")
    if kind != "session_start":
        if kind in ("execution_failed", "report_published", "analysis_invocation",
                    "analysis_infrastructure_failure", "integrity_check", "model_verification"):
            _require(event["session_id"] in state.sessions, f"{kind} references unknown session")
        else:
            _require(event["session_id"] == state.open_session, f"{kind} requires its session to be open")
    return kind


def _attempt_identity(state, event, kind):
    slot = p8.SLOTS.get(event["round"])
    _require(slot is not None, f"round {event['round']!r} is not a Patch 8 slot")
    _require(event["subject"] == state.subject, "attempt subject differs from execution subject")
    _require(type(event["attempt_index"]) is int and 1 <= event["attempt_index"] <= p8.MAX_ATTEMPTS,
             "attempt_index must be 1..3")
    _require(event["validation_protocol_version"] == slot.protocol_version, "validation_protocol_version mismatch")
    _require(event["status"] == ATTEMPT_EVENT_STATUS[kind], f"{kind} status must be {ATTEMPT_EVENT_STATUS[kind]}")
    if slot.kind == p8.STATIC:
        _require(event["nominal_distance"] == slot.nominal_distance_m and
                 event["repetition_index"] == slot.repetition_index, "static nominal_distance/repetition mismatch")
    return slot


def _apply_session(state, event, kind):
    if kind == "session_start":
        _require(state.open_session is None, "another session is still open")
        _require(state.execution_failure is None, "session_start after execution_failed")
        _require(event["session_id"] not in state.sessions, "session_id reused")
        _require(event["session_kind"] in p8.SESSION_KINDS.values(), "invalid session_kind")
        _require(_text(event["subject"]) and re.fullmatch(r"[A-Za-z0-9-]+", event["subject"]),
                 "invalid reserved validation subject")
        if state.subject is None:
            state.subject = event["subject"]
        _require(event["subject"] == state.subject, "reserved validation subject changed")
        _require(_environment(event["environment"]), "environment snapshot missing/invalid pinned fields")
        code = event["code_state"]
        _require(isinstance(code, dict) and set(code) == {"git_commit", "git_clean"}, "invalid code_state")
        _require(_strings(event["recording_inventory"]), "recording_inventory must be sorted unique strings")
        if state.baseline_environment is None:
            state.baseline_environment = {k: event["environment"][k] for k in PINNED_ENVIRONMENT_KEYS}
            state.baseline_code = dict(code)
        state.sessions[event["session_id"]] = dict(
            kind=event["session_kind"], warmup=False, setup_pose=None, recheck=False, static_attempts=False,
            environment_matches={k: event["environment"][k] for k in PINNED_ENVIRONMENT_KEYS} ==
            state.baseline_environment, inventory=list(event["recording_inventory"]))
        state.open_session = event["session_id"]
    elif kind == "session_end":
        session = state.sessions[state.open_session]
        _require(event["session_kind"] == session["kind"], "session_end kind mismatch")
        _require(event["status"] in ("completed", "aborted"), "invalid session_end status")
        _require(state.open_attempt() is None, "session_end with an open attempt")
        if session["kind"] == p8.SESSION_KINDS[p8.STATIC] and session["setup_pose"] is not None:
            _require(session["recheck"], "static session_end requires camera_pose_recheck (§7.4)")
        state.open_session = None
    elif kind == "warmup_completed":
        _require(event["duration_s"] == p8.INITIAL_WARMUP_S, "warm-up must be exactly 60 s (§11)")
        _require(event["exit_code"] == 0 and _logs(event["logs"]), "warm-up must complete with sealed logs")
        state.sessions[state.open_session]["warmup"] = True
    elif kind == "setup_verified":
        session = state.sessions[state.open_session]
        _require(session["kind"] == p8.SESSION_KINDS[p8.STATIC], "setup_verified only in static-grid session")
        _require(event["purpose"] in ("initial", "reset") and _pose(event["camera_pose"], recheck=False),
                 "invalid setup_verified payload")
        _require(not state.canonical_static_take_exists(),
                 "camera re-setup after the first canonical static take is forbidden (§7.3)")
        session["setup_pose"] = dict(event["camera_pose"])
    elif kind == "camera_pose_recheck":
        session = state.sessions[state.open_session]
        _require(session["setup_pose"] is not None, "camera_pose_recheck without setup_verified")
        _require(_pose(event["camera_pose"], recheck=True), "invalid recheck camera_pose")
        differences, material = pose_differences(session["setup_pose"], event["camera_pose"])
        _require(event["differences"] == differences and event["material_change"] is material,
                 "camera_pose_recheck differences/material_change must equal §7.4 computation")
        session["recheck"] = True
        session["material_change"] = material
    elif kind == "model_verification":
        _require(event["status"] in ("PASS", "FAIL") and isinstance(event["artifacts"], list) and
                 isinstance(event["lock_sha256"], str) and HEX64.fullmatch(event["lock_sha256"]),
                 "invalid model_verification payload")
        state.model_verified = event["status"] == "PASS"
    elif kind == "integrity_check":
        counts = event["counts"]
        _require(event["phase"] in ("pre_hardware", "closure") and type(event["exit_code"]) is int and
                 event["summary"] in ("PASS", "FAIL") and isinstance(counts, dict) and
                 set(counts) == {"ERROR", "WARNING", "INFO"} and all(type(v) is int for v in counts.values()),
                 "invalid integrity_check payload")
        passed = event["exit_code"] == 0 and event["summary"] == "PASS" and counts["ERROR"] == 0
        if event["phase"] == "pre_hardware":
            _require(not state.attempts, "pre-hardware integrity must precede the first attempt (§84)")
            state.pre_hardware_integrity = passed
        else:
            state.closure_integrity = passed
    elif kind == "execution_failed":
        _require(event["reason_code"] in p8.EXECUTION_FAILURE_REASONS, "unsupported execution failure reason")
        _require(event["detail"] is None or isinstance(event["detail"], str), "detail must be string or null")
        if state.execution_failure is None:
            state.execution_failure = event["reason_code"]
    elif kind == "report_published":
        _require(_text(event["report_path"]) and HEX64.fullmatch(event["report_sha256"] or "") and
                 HEX64.fullmatch(event["ledger_sha256_before"] or ""), "invalid report_published payload")
        state.reports.append(event)


def _apply_attempt_start(state, event):
    slot = _attempt_identity(state, event, "attempt_start")
    session = state.sessions[state.open_session]
    _require(session["kind"] == slot.session_kind, "attempt slot does not belong to the open session kind")
    _require(state.model_verified, "model verification PASS required before hardware execution (§10)")
    _require(state.pre_hardware_integrity, "pre-hardware integrity PASS required (§84)")
    _require(session["warmup"], "60 s warm-up required in the session before attempts (§11)")
    _require(session["environment_matches"], "environment differs from execution baseline (§9)")
    _require(event["code_state"] == state.baseline_code and event["code_state"]["git_clean"] is True,
             "code state changed or dirty (§20, §22)")
    _require(not session.get("material_change"), "camera pose material change recorded (§7.4)")
    _require(event["slot_kind"] == slot.kind, "slot_kind mismatch")
    if slot.kind == p8.STATIC:
        _require(event["sequence_mode"] is None, "static attempts do not use SEQ_CORE/SEQ_FULL (§24)")
        _require(session["setup_pose"] is not None, "static attempts require setup_verified (§7.2)")
    else:
        _require(slot.sequence_mode in p8.PRODUCTION_SEQUENCES,
                 "slot sequence is not supported by CAP-005/CAP-006")
        _require(event["sequence_mode"] == slot.sequence_mode, "sequence_mode mismatch")
    _require(event["setup_checks"] == {k: True for k in SETUP_CHECKS}, "pre-attempt setup checks must all pass (§7.6)")
    _require(event["settling_s"] == p8.SETTLING_S, "settling must be exactly 10 s (§11, §29)")
    _require(_strings(event["pre_launch_inventory"]), "pre_launch_inventory must be sorted unique strings")
    _require(event["recording_id"] is None and event["reason_code"] is None, "attempt_start has no recording/reason")
    _require(state.open_attempt() is None, "another attempt is still open")
    expected = state.next_attempt_index(event["round"])
    _require(expected is not None and event["attempt_index"] == expected,
             "attempt not authorized: index/retry authority mismatch (§49, §79, §81)")
    if slot.kind == p8.STATIC and event["attempt_index"] == 1:
        position = p8.STATIC_ROUNDS.index(event["round"])
        _require(position == 0 or state.slot_resolved(p8.STATIC_ROUNDS[position - 1]),
                 "static slots follow the frozen acquisition order (§32)")
    if slot.kind == p8.STATIC:
        disturbed = [a for a in state.attempts.values() if a.locked is not None and
                     a.locked["reason_code"] == p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED]
        if disturbed:
            last = max(disturbed, key=lambda a: state.events.index(a.locked))
            resets = [e for e in state.events[state.events.index(last.locked):]
                      if e["event_type"] == "setup_verified" and e["purpose"] == "reset"]
            _require(resets, "camera disturbance requires setup reset before retry (§7.3)")
    if slot.kind == p8.STATIC:
        session["static_attempts"] = True
        session["recheck"] = False   # §7.4 re-check must follow the last static attempt
    state.attempts[(event["round"], event["attempt_index"])] = Attempt(event["round"], event["attempt_index"], event)


def _apply_attempt_event(state, event, kind):
    slot = _attempt_identity(state, event, kind)
    attempt = state.attempts.get((event["round"], event["attempt_index"]))
    _require(attempt is not None, f"{kind} without attempt_start")
    if kind == "operator_observation":
        _require(attempt.finished is None, "operator_observation only while acquisition is running (§43)")
        _require(event["observation"] in p8.OPERATOR_OBSERVATIONS, "unsupported observation")
        _require(event["retry_eligible"] is observation_retry_eligible(
            slot.kind, event["observation"], state.canonical_static_take_exists()), "retry_eligible mismatch")
        _require(event["recording_id"] is None and event["reason_code"] is None, "observation carries no outcome")
        attempt.observations.append(event)
    elif kind == "capture_finished":
        _require(attempt.finished is None, "duplicate capture_finished")
        _require(event["stage"] in STAGES, "invalid stage")
        ids = event["bound_recording_ids"]
        _require(_strings(ids), "bound_recording_ids must be sorted unique strings")
        _require(event["recording_id"] == (ids[0] if len(ids) == 1 else None), "recording_id/binding mismatch")
        _require(event["reason_code"] is None, "capture_finished carries no reason")
        termination = event["termination"]
        _require(isinstance(termination, dict) and set(termination) == TERMINATION_FIELDS, "invalid termination")
        _require(_logs(event["logs"], nullable=termination["recovered"] is True), "invalid sealed log references")
        attempt.finished = event
    elif kind == "validity_locked":
        _require(attempt.finished is not None, "validity_locked before capture_finished")
        _require(attempt.locked is None, "validity is immutable: duplicate validity_locked rejected (§38, §48)")
        _require(event["stage"] == attempt.finished["stage"], "lock stage differs from capture_finished")
        _require(event["recording_id"] == attempt.finished["recording_id"], "lock recording_id mismatch")
        reason = event["reason_code"]
        _require(reason in allowed_lock_reasons(slot.kind), f"reason {reason!r} not permitted for {slot.kind}")
        _require(event["acquisition_valid"] is acquisition_valid_for(reason), "acquisition_valid inconsistent")
        expected_retry = lock_retry_allowed(slot.kind, reason, attempt.attempt_index,
                                            state.canonical_static_take_exists(), state.execution_failure is not None)
        _require(event["retry_allowed"] is expected_retry, "retry_allowed inconsistent with closed retry rules")
        _require(event["operator_declaration"] in DECLARATIONS and _text(event["rule_id"]) and
                 _strings(event["evidence_used"], sorted_unique=False), "invalid lock evidence fields")
        if reason in p8.MACHINE_INVALID_REASONS:
            _require(_artifact_ref(event["machine_evidence_ref"]), "machine reason requires machine_evidence_ref")
        else:
            _require(event["machine_evidence_ref"] is None, "machine_evidence_ref only for machine reasons")
        attempt.locked = event
    elif kind == "attempt_end":
        _require(attempt.locked is not None and attempt.ended is None, "attempt_end requires validity_locked")
        _require(event["reason_code"] == attempt.locked["reason_code"] and
                 event["recording_id"] == attempt.locked["recording_id"], "attempt_end must restate lock")
        attempt.ended = event
    elif kind == "attempt_outcome":
        _require(attempt.ended is not None, "attempt_outcome only after attempt_end (§40)")
        _require(slot.kind != p8.STATIC, "static canonical status follows the lock alone (§49)")
        _require(attempt.locked["acquisition_valid"], "invalid attempts have no outcome")
        _require(attempt.outcome is None, "outcome is immutable once recorded (§38)")
        outcome, reason = event["outcome"], event["reason_code"]
        _require(outcome in (p8.CANONICAL, p8.TARGET_MISS_OUTCOME), "invalid outcome")
        if outcome == p8.TARGET_MISS_OUTCOME:
            _require(slot.kind in (p8.FORWARD, p8.BODY_ONLY_NEGATIVE) and attempt.locked["reason_code"] is None and
                     reason == p8.TARGET_MISS, "TARGET_MISS only for forward/body-only normal acquisitions")
        else:
            _require(reason is None or reason in p8.POST_LOCK_FAIL_REASONS, "invalid canonical outcome reason")
            if attempt.locked["reason_code"] is not None:
                _require(reason == attempt.locked["reason_code"], "locked FAIL reason must carry into outcome")
        _require(event["recording_id"] == attempt.recording_id and isinstance(event["evidence"], dict),
                 "invalid attempt_outcome evidence")
        attempt.outcome = event


def _apply_analysis(state, event, kind):
    canonical = state.canonical_recordings()
    attempt = canonical.get(event["recording_id"])
    _require(attempt is not None and (attempt.round, attempt.attempt_index) ==
             (event["round"], event["attempt_index"]) and event["subject"] == state.subject,
             "analysis only for a ledger-canonical recording (§52)")
    record = state.analyses.setdefault(event["recording_id"], dict(invocations=[], canonical=None, failures=[]))
    if kind == "analysis_invocation":
        _require(event["invocation_index"] == len(record["invocations"]) + 1, "invocation_index mismatch")
        _require(state.analysis_invocation_allowed(event["recording_id"]),
                 "re-analysis only after logged infrastructure failure and before completion (§54)")
        runs = event["analysis_runs"]
        _require(isinstance(runs, list) and all(
            isinstance(r, dict) and set(r) == {"analysis_run_id", "status", "manifest_sha256"} and
            _text(r["analysis_run_id"]) and r["status"] in ("running", "failed", "completed") and
            (r["manifest_sha256"] is None or HEX64.fullmatch(str(r["manifest_sha256"]))) and
            (r["status"] != "completed" or r["manifest_sha256"] is not None) for r in runs), "invalid analysis_runs")
        completed = [r["analysis_run_id"] for r in runs if r["status"] == "completed"]
        expected = completed[0] if completed and record["canonical"] is None else None
        _require(event["canonical_analysis_run_id"] == expected, "canonical analysis = first completed run (§53)")
        _require(event["exit_code"] is None or type(event["exit_code"]) is int, "invalid exit_code")
        _require(_logs(event["logs"]), "analysis invocation requires sealed logs")
        record["invocations"].append(event)
        if expected is not None:
            record["canonical"] = expected
    else:
        _require(record["canonical"] is None and record["invocations"], "infrastructure failure after completion")
        invocation = record["invocations"][-1]
        failed = {r["analysis_run_id"]: r for r in invocation["analysis_runs"] if r["status"] == "failed"}
        run_id = event["analysis_run_id"]
        _require(_text(run_id) and run_id in failed, "infrastructure evidence must name a failed logged run (§54)")
        expected_ref = f"analysis/{event['recording_id']}/{run_id}/analysis_manifest.json"
        _require(event["evidence_ref"] == expected_ref and failed[run_id]["manifest_sha256"] is not None and
                 event["evidence_sha256"] == failed[run_id]["manifest_sha256"],
                 "analysis infrastructure evidence must be the logged failed-run manifest (§54)")
        _require(type(invocation["exit_code"]) is int and invocation["exit_code"] != 0,
                 "analysis infrastructure failure requires a nonzero failed invocation (§54)")
        record["failures"].append(event)


def apply_event(state, event):
    kind = _common(state, event)
    if kind == "attempt_start":
        _apply_attempt_start(state, event)
    elif kind in ATTEMPT_EVENTS:
        _apply_attempt_event(state, event, kind)
    elif kind in ("analysis_invocation", "analysis_infrastructure_failure"):
        _apply_analysis(state, event, kind)
    else:
        _apply_session(state, event, kind)
    state.events.append(event)
    return state


def replay(events):
    state = LedgerState()
    for event in events:
        apply_event(state, event)
    return state


def parse_ledger_bytes(data):
    """Return (events, state). Every line must be the exact canonical serialization."""
    _require(data == b"" or data.endswith(b"\n"), "torn ledger tail")
    events, state, offset = [], LedgerState(), 0
    for line in data.splitlines(keepends=True):
        event = _strict_json(line[:-1])
        _require(line == event_line(event), "ledger line is not canonical serialization")
        if isinstance(event, dict) and event.get("event_type") == "report_published":
            _require(event.get("ledger_sha256_before") == hashlib.sha256(data[:offset]).hexdigest(),
                     "report_published ledger_sha256_before mismatch")
        apply_event(state, event)
        events.append(event)
        offset += len(line)
    return events, state


def verify_ledger(path):
    path = Path(path)
    return parse_ledger_bytes(path.read_bytes())


class Ledger:
    """Single-writer append-only ledger at validation/patch8/<execution_id>/."""

    def __init__(self, path, execution_id):
        self.path = Path(path)
        _require(valid_id(execution_id, "p8x"), "invalid execution_id")
        _require(self.path.name == p8.LEDGER_FILENAME and self.path.parent.name == execution_id,
                 "ledger path must be validation/patch8/<execution_id>/patch8_validation_ledger.jsonl")
        self.execution_id = execution_id

    def read(self):
        if not self.path.exists():
            return [], LedgerState()
        events, state = verify_ledger(self.path)
        _require(state.execution_id in (None, self.execution_id), "ledger belongs to another execution")
        return events, state

    def build(self, state, event_type, session_id, payload, now=None):
        event = dict(payload, ledger_format_version=p8.LEDGER_FORMAT_VERSION, execution_id=self.execution_id,
                     session_id=session_id, event_id=_new_id("p8e", now), event_timestamp_utc=utc_timestamp(now),
                     event_type=event_type,
                     previous_event_sha256=state.events[-1]["event_sha256"] if state.events else None)
        event["event_sha256"] = event_hash(event)
        return event

    def append(self, event_type, session_id, payload, now=None):
        data = self.path.read_bytes() if self.path.exists() else b""
        events, state = parse_ledger_bytes(data)
        if event_type == "report_published":
            payload = dict(payload, ledger_sha256_before=hashlib.sha256(data).hexdigest())
        event = self.build(state, event_type, session_id, payload, now)
        apply_event(state, event)   # validate before any byte is written
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab" if self.path.exists() else "xb") as stream:
            _require(stream.tell() == len(data), "ledger changed concurrently; refusing append")
            stream.write(event_line(event))
            stream.flush()
            os.fsync(stream.fileno())
        return event, state
