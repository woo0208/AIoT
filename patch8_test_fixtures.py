"""Synthetic Patch 8 fixtures for structural tests only (no hardware, no research results)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import analyze_d455
import patch8_ledger as ledger
import patch8_protocol as p8


EXECUTION_ID = "p8x_20261007T000000000000Z_" + "a" * 32
SUBJECT = "V01"
SERIAL = "SYNTHETIC-SERIAL"
HEX = "0" * 64
LOGS = {"stdout": {"path": "logs/x.stdout.log", "sha256": HEX}, "stderr": {"path": "logs/x.stderr.log", "sha256": HEX}}
SETUP_CHECKS = {k: True for k in ledger.SETUP_CHECKS}
CODE = {"git_commit": "c" * 40, "git_clean": True}
POSE = dict(reference_height_mm=1000.0, pitch_deg=0.0, yaw_deg=0.0, roll_deg=0.0, mount_identity="mount A",
            camera_position="desk center", witness_marks="tape marks")
TERMINATION = dict(exit_code=0, signal=None, orchestrator_timeout_kill=False, operator_signal_observed=None,
                   static_exit_status=None, recovered=False, reservation_observed_s=None)
INTRINSICS = dict(width=1280, height=720, fx=640.0, fy=640.0, ppx=640.0, ppy=360.0,
                  model="distortion.inverse_brown_conrady", coeffs=[0.0, 0.0, 0.0, 0.0, 0.0])


def environment(serial=SERIAL, **changes):
    value = dict(capture_host="synthetic-host", os="synthetic-os", python="3.12", packages={"numpy": "x"},
                 d455_serial=serial, d455_firmware="5.0", usb_type="3.2", depth_scale_m=0.001,
                 realsense_devices=[], device_options={}, stream_profiles={})
    value.update(changes)
    return value


def pinhole(x, y, z):
    """Synthetic stand-in for SDK deprojection in structural tests (distortion-free model)."""
    return ((x - INTRINSICS["ppx"]) / INTRINSICS["fx"] * z, (y - INTRINSICS["ppy"]) / INTRINSICS["fy"] * z, z)


def pinhole_factory(intrinsics):
    return pinhole


class LedgerHarness:
    def __init__(self, root, execution_id=EXECUTION_ID):
        self.root = Path(root)
        self.directory = self.root / p8.VALIDATION_ROOT / execution_id
        self.path = self.directory / p8.LEDGER_FILENAME
        self.ledger = ledger.Ledger(self.path, execution_id)
        self.time = datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.session = None

    def now(self):
        self.time += timedelta(milliseconds=1)
        return self.time

    def append(self, kind, payload, session=None):
        return self.ledger.append(kind, session or self.session, payload, self.now())

    def state(self):
        return self.ledger.read()[1]

    def start_session(self, kind="static-grid", env=None, code=None, inventory=()):
        self.session = ledger.new_session_id(self.now())
        self.append("session_start", dict(session_kind=kind, subject=SUBJECT, environment=env or environment(),
                                          code_state=dict(code or CODE), recording_inventory=sorted(inventory)))
        return self.session

    def prepare(self, kind="static-grid", inventory=(), models=True, integrity=True, warm=True, setup=True):
        self.start_session(kind, inventory=inventory)
        if models:
            self.append("model_verification", dict(status="PASS", lock_sha256=HEX, artifacts=[]))
        if integrity and not self.state().pre_hardware_integrity:
            self.append("integrity_check", dict(phase="pre_hardware", exit_code=0, summary="PASS",
                                                counts=dict(ERROR=0, WARNING=0, INFO=3)))
        if warm:
            self.append("warmup_completed", dict(duration_s=60.0, exit_code=0, logs=LOGS))
        if setup and kind == "static-grid":
            self.append("setup_verified", dict(purpose="initial", camera_pose=dict(POSE)))
        return self.session

    def identity(self, rnd, index):
        slot = p8.slot(rnd)
        value = dict(subject=SUBJECT, round=rnd, attempt_index=index, validation_protocol_version=slot.protocol_version)
        if slot.kind == p8.STATIC:
            value.update(nominal_distance=slot.nominal_distance_m, repetition_index=slot.repetition_index)
        return value

    def start(self, rnd, index=1, **overrides):
        slot = p8.slot(rnd)
        payload = dict(self.identity(rnd, index), recording_id=None, status="started", reason_code=None,
                       slot_kind=slot.kind, sequence_mode=None if slot.kind == p8.STATIC else slot.sequence_mode,
                       setup_checks=dict(SETUP_CHECKS), settling_s=10.0, pre_launch_inventory=[],
                       code_state=dict(CODE))
        payload.update(overrides)
        return self.append("attempt_start", payload)

    def finish(self, rnd, index=1, recording_ids=None, stage="post_reservation", **termination):
        ids = sorted(recording_ids if recording_ids is not None else [f"{SUBJECT}_r{rnd}_a{index}"])
        return self.append("capture_finished", dict(
            self.identity(rnd, index), recording_id=ids[0] if len(ids) == 1 else None, status="finished",
            reason_code=None, stage=stage, bound_recording_ids=ids, termination=dict(TERMINATION, **termination),
            logs=LOGS))

    def lock(self, rnd, index=1, reason=None, **overrides):
        state = self.state()
        attempt = state.attempts[(rnd, index)]
        slot = p8.slot(rnd)
        payload = dict(self.identity(rnd, index), recording_id=attempt.finished["recording_id"], status="locked",
                       reason_code=reason, stage=attempt.finished["stage"],
                       acquisition_valid=ledger.acquisition_valid_for(reason),
                       retry_allowed=ledger.lock_retry_allowed(slot.kind, reason, index,
                                                               state.canonical_static_take_exists(),
                                                               state.execution_failure is not None),
                       machine_evidence_ref={"path": "state/x.json", "sha256": HEX}
                       if reason in p8.MACHINE_INVALID_REASONS else None,
                       evidence_used=["exit_code"], operator_declaration="not_operator_initiated", rule_id="R17")
        payload.update(overrides)
        return self.append("validity_locked", payload)

    def end(self, rnd, index=1):
        attempt = self.state().attempts[(rnd, index)]
        return self.append("attempt_end", dict(self.identity(rnd, index), recording_id=attempt.locked["recording_id"],
                                               status="ended", reason_code=attempt.locked["reason_code"]))

    def outcome(self, rnd, index=1, outcome=p8.CANONICAL, reason=None, evidence=None):
        attempt = self.state().attempts[(rnd, index)]
        return self.append("attempt_outcome", dict(self.identity(rnd, index), recording_id=attempt.recording_id,
                                                   status="outcome_recorded", reason_code=reason, outcome=outcome,
                                                   evidence=evidence or {}))

    def attempt(self, rnd, index=1, reason=None, recording_ids=None, stage="post_reservation", **termination):
        self.start(rnd, index)
        self.finish(rnd, index, recording_ids, stage, **termination)
        self.lock(rnd, index, reason)
        self.end(rnd, index)


# ---------------------------------------------------------------- canonical frame rows
def frame_row(t, index=1, *, label="upright", step="1", rid=SUBJECT + "_r1_x", run="ar_x", jitter=0.0, **changes):
    row = {field: None for field in analyze_d455.FRAME_FIELDS}
    row.update(subject=SUBJECT, round="1", step=step, label=label, t=t, ts_ms=1000.0 + 1000.0 * t,
               frame_schema_version=analyze_d455.FRAME_SCHEMA_VERSION, recording_id=rid, analysis_run_id=run,
               frame_index=index, face_detected=True, face_mesh_detected=True, pose_detected=True,
               face_depth_valid=True, face_depth_source="bbox_roi", z_face_m=0.80 + jitter, ipd_cm=6.3 + jitter,
               face_x=640.0, face_y=300.0, face_area_px=10000.0, face_w_px=100.0,
               lsh_valid=True, rsh_valid=True, lsh_depth_valid=True, rsh_depth_valid=True,
               shoulder_depth_source="both", lsh_x=840.0, lsh_y=420.0, rsh_x=440.0, rsh_y=420.0,
               z_lsh_m=0.85 + jitter, z_rsh_m=0.85 + jitter, z_sh_m=0.85 + jitter,
               left_hip_x_px=800.0, left_hip_y_px=700.0, right_hip_x_px=480.0, right_hip_y_px=700.0,
               left_hip_depth_m=0.90 + jitter, right_hip_depth_m=0.90 + jitter, left_hip_visibility=0.9,
               right_hip_visibility=0.9, left_hip_valid=True, right_hip_valid=True, left_hip_depth_valid=True,
               right_hip_depth_valid=True)
    row.update(changes)
    return row


def window_times(n=128, start=1.0):
    return [start + i / 15 for i in range(n)]


def static_rows(n=128, jitter_m=0.001, **changes):
    """n rows inside 1.0 <= t < 9.5 with alternating ±jitter (synthetic micro-motion)."""
    return [frame_row(t, i + 1, jitter=jitter_m if i % 2 else -jitter_m, **changes)
            for i, t in enumerate(window_times(n))]


def forward_rows(label, step, n=127, **changes):
    """Rows inside 1.0 < t < 9.5 for one forward phase (strict lower bound)."""
    return [frame_row(1.0 + (i + 1) / 15, i + 1, label=label, step=step, **changes) for i in range(n)]


def gate_entry(label, *, ref=0.75, cur=None, closer="auto", phase_idx=3, reference_phase_idx=1, result=None,
               reasons=None):
    if closer == "auto":
        closer = None if ref is None or cur is None else ref - cur
    if result is None:
        if closer is None:
            reasons = reasons if reasons is not None else (
                (["insufficient_reference_face_samples"] if ref is None else []) +
                (["insufficient_current_face_samples"] if cur is None else []))
            result = "fail"
        else:
            status = ("too_little" if closer < 0.08 - 1e-12 else "too_much" if closer > 0.12 + 1e-12 else "ok")
            result = "pass" if status == "ok" else "fail"
            reasons = reasons if reasons is not None else {"ok": [], "too_little": ["below_target"],
                                                           "too_much": ["above_target"]}[status]
    return dict(step=2, phase_idx=phase_idx, label=label, reference_step=1, reference_phase_idx=reference_phase_idx,
                reference_label="upright", reference_face_median_m=ref, current_face_median_m=cur, closer_m=closer,
                forward_target_min_m=0.08, forward_target_max_m=0.12, forward_validation_source="face_only",
                forward_gate_result=result, forward_gate_reasons=reasons or [], reference_total_samples=40,
                reference_valid_face_samples=40, reference_valid_face_fraction=1.0, current_total_samples=40,
                current_valid_face_samples=0 if cur is None else 40,
                current_valid_face_fraction=0.0 if cur is None else 1.0)
