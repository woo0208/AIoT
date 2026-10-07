"""Patch 8 orchestration CLI (CAP-005 §11–§23, §35–§54, §82–§85); see `--help`.

Formal commands refuse to run unless the execution registry (§15, created only after the
audited implementation and explicit authorization) names the execution_id and a registered
commit whose non-documentation tree equals the clean HEAD. Read-only commands (`show-protocol`, `verify-ledger`, `evaluate`
without `--publish`) create no evidence. Hardware is touched only by child processes:
capture_d455.py (production slots, unchanged), patch8_static_capture.py (static slots),
and patch8_prelock.py probes. Child stdout/stderr are sealed under
validation/patch8/<execution_id>/logs/ and never live-forwarded (§41).

Attempt lifecycle (§40): attempt_start → child → capture_finished → stage classification
→ structural probes → validity_locked → attempt_end → only then unseal/outcome/analysis.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import types

import patch8_ledger as ledger
import patch8_prelock as prelock
import patch8_protocol as p8
import patch8_report as report


ROOT = Path(__file__).resolve().parent
ENUMERATION_TIMEOUT_S, RAW_PROBE_TIMEOUT_S, ENVIRONMENT_TIMEOUT_S = 30, 120, 60
TERMINATE_GRACE_S, OPERATOR_SIGNAL_GRACE_S, POLL_S = 5.0, 10.0, 0.1
OBSERVATION_KEYS = {"i": p8.EXTERNAL_PHYSICAL_INTERRUPTION, "m": p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED}


class ExecutionNotAuthorized(RuntimeError):
    pass


class DesignAuthorityGap(RuntimeError):
    pass


class FirewallViolation(RuntimeError):
    pass


# ---------------------------------------------------------------- runtime (injectable for tests)
class OperatorConsole:
    """§25 static firewall: while sealed only phase identity, elapsed timer, recording state
    and operator prompts can be written. Any other output raises before reaching the screen."""

    def __init__(self, write=print, read=input):
        self.write, self.read, self.sealed = write, read, False

    def seal(self):
        self.sealed = True

    def unseal(self):
        self.sealed = False

    def phase(self, name):
        self.write(f"[PATCH 8] PHASE {name}")

    def timer(self, elapsed_s, total_s):
        self.write(f"[PATCH 8] ELAPSED {elapsed_s:4.1f} / {total_s:.1f} s")

    def recording_state(self, state):
        self.write(f"[PATCH 8] RECORDING {state}")

    def prompt(self, text):
        return self.read(f"[PATCH 8] {text} ")

    def info(self, text):
        if self.sealed:
            raise FirewallViolation("result-bearing or diagnostic output is sealed before validity_locked")
        self.write(f"[PATCH 8] {text}")


class KeyboardObservations:
    """Non-blocking operator observation keys typed in the orchestrator terminal during
    acquisition: `i` + Enter = external physical interruption, `m` + Enter = camera mount
    disturbed (§43). Logged to the ledger immediately."""

    def __init__(self):
        self.buffer = ""

    def poll(self):
        lines = []
        try:
            if os.name == "nt":
                import msvcrt
                while msvcrt.kbhit():
                    char = msvcrt.getwch()
                    if char in "\r\n":
                        lines.append(self.buffer)
                        self.buffer = ""
                    else:
                        self.buffer += char
            else:
                import select
                while select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    lines.append(line)
        except (OSError, ValueError):
            return []
        return [OBSERVATION_KEYS[t] for t in (line.strip().lower() for line in lines) if t in OBSERVATION_KEYS]


@contextmanager
def operator_signals():
    """Record operator SIGINT/SIGTERM delivered to the orchestrator (§46) instead of dying."""
    captured = types.SimpleNamespace(name=None)
    previous = {}

    def handler(number, frame):
        captured.name = captured.name or signal.Signals(number).name
    for name in ("SIGINT", "SIGTERM"):
        number = getattr(signal, name, None)
        if number is not None:
            try:
                previous[number] = signal.signal(number, handler)
            except (ValueError, OSError):
                pass
    try:
        yield captured
    finally:
        for number, old in previous.items():
            signal.signal(number, old)


@dataclass
class Runtime:
    root: Path = ROOT
    popen: object = subprocess.Popen
    run: object = subprocess.run
    clock: object = time.monotonic
    sleep: object = time.sleep
    now: object = lambda: datetime.now(timezone.utc)
    console: OperatorConsole = field(default_factory=OperatorConsole)
    observations: object = field(default_factory=KeyboardObservations)
    signals: object = operator_signals
    python: str = sys.executable


# ---------------------------------------------------------------- paths / authorization
def execution_dir(root, execution_id):
    if not ledger.valid_id(execution_id, "p8x"):
        raise ValueError("invalid execution_id")
    return Path(root) / p8.VALIDATION_ROOT / execution_id


def open_ledger(root, execution_id):
    return ledger.Ledger(execution_dir(root, execution_id) / p8.LEDGER_FILENAME, execution_id)


def code_state(rt):
    def git(*args):
        return rt.run(["git", *args], cwd=rt.root, capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    try:
        return {"git_commit": git("rev-parse", "HEAD"), "git_clean": git("status", "--porcelain",
                                                                         "--untracked-files=normal") == ""}
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_clean": False}


def authorization_gate(rt, execution_id):
    """§15/§20/§22: formal commands need the execution registry to name the execution_id and
    a commit that is an ancestor of HEAD whose non-documentation tree equals HEAD (the
    audited implementation; only documentation such as the registration may follow), plus
    a clean workspace. The registry format is not assumed beyond these tokens, and the
    registry is never created by this tool."""
    registry = Path(rt.root) / p8.EXECUTION_REGISTRY_PATH
    if not registry.is_file():
        raise ExecutionNotAuthorized(f"{p8.EXECUTION_REGISTRY_PATH} absent: formal Patch 8 execution is not authorized")
    text = registry.read_text(encoding="utf-8")
    if execution_id not in text:
        raise ExecutionNotAuthorized("execution_id is not registered")
    code = code_state(rt)
    if not code["git_commit"] or not code["git_clean"]:
        raise ExecutionNotAuthorized("execution workspace is not a clean Git checkout (§22)")

    def git_ok(*args):
        try:
            return rt.run(["git", *args], cwd=rt.root, capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    for commit in sorted(set(re.findall(r"\b[0-9a-f]{40}\b", text))):
        if git_ok("merge-base", "--is-ancestor", commit, "HEAD") and git_ok(
                "diff", "--quiet", commit, "HEAD", "--", ".", ":(exclude)docs", ":(exclude,glob)*.md"):
            return dict(code, audited_implementation_commit=commit)
    raise ExecutionNotAuthorized("no registered commit matches HEAD's non-documentation tree (§20)")


def _sealed_files(directory, stem):
    logs = directory / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / f"{stem}.stdout.log", logs / f"{stem}.stderr.log"


def _artifact(directory, path):
    return {"path": Path(path).relative_to(directory).as_posix(),
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def _decode_returncode(code):
    if code is None:
        return None, None
    return (None, -code) if code < 0 else (code, None)


def launch_sealed(rt, command, stdout_path, stderr_path):
    """One child launch with stdout/stderr redirected to exclusive sealed files (§41)."""
    stdout, stderr = open(stdout_path, "xb"), open(stderr_path, "xb")
    try:
        process = rt.popen(command, cwd=str(rt.root), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
    except BaseException:
        stdout.close()
        stderr.close()
        raise
    return process, (stdout, stderr)


def _stop(rt, process):
    process.terminate()
    deadline = rt.clock() + TERMINATE_GRACE_S
    while process.poll() is None and rt.clock() < deadline:
        rt.sleep(POLL_S)
    if process.poll() is None:
        process.kill()
    return process.wait()


def supervise(rt, process, *, guide_timeout_s, reservation_seen, on_poll, on_tick=None):
    """Wait for exactly this child; enforce the §47.1 guide reservation clock if given."""
    started = rt.clock()
    reserved_at, timeout_kill, signal_at = None, False, None
    with rt.signals() as captured:
        while process.poll() is None:
            elapsed = rt.clock() - started
            if guide_timeout_s is not None and reserved_at is None:
                if reservation_seen():
                    reserved_at = elapsed
                elif elapsed >= guide_timeout_s:
                    timeout_kill = True
                    _stop(rt, process)
                    break
            if captured.name is not None:
                signal_at = signal_at if signal_at is not None else rt.clock()
                if rt.clock() - signal_at >= OPERATOR_SIGNAL_GRACE_S:
                    _stop(rt, process)
                    break
            on_poll()
            if on_tick is not None:
                on_tick(elapsed)
            rt.sleep(POLL_S)
        operator_signal = captured.name
    exit_code, signal_number = _decode_returncode(process.wait())
    return dict(exit_code=exit_code, signal=signal_number, orchestrator_timeout_kill=timeout_kill,
                operator_signal_observed=operator_signal, reservation_observed_s=reserved_at)


# ---------------------------------------------------------------- session-level commands
def open_session(rt, execution_id, session_kind, subject):
    if session_kind not in p8.SESSION_KINDS.values():
        raise ValueError("invalid session kind")
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    environment = prelock.run_probe(["environment"], runner=rt.run, timeout=ENVIRONMENT_TIMEOUT_S)
    if environment is None or not environment.get("d455_serial"):
        raise RuntimeError("environment snapshot unavailable or no single D455 enumerated (§9)")
    code = code_state(rt)
    session_id = ledger.new_session_id(rt.now())
    payload = dict(session_kind=session_kind, subject=subject, environment=ledger.json_safe(environment),
                   code_state=code, recording_inventory=prelock.recording_inventory(Path(rt.root) / "data"))
    _, state = led.append("session_start", session_id, payload, rt.now())
    if not state.sessions[session_id]["environment_matches"]:
        led.append("execution_failed", session_id, dict(reason_code="ENVIRONMENT_CHANGED",
                                                        detail="pinned environment differs (§9)"), rt.now())
    elif code != state.baseline_code or not code["git_clean"]:
        led.append("execution_failed", session_id, dict(reason_code="CODE_CHANGED",
                                                        detail="code state differs (§20)"), rt.now())
    return session_id


def _open_session_id(state):
    if state.open_session is None:
        raise RuntimeError("no open Patch 8 session")
    return state.open_session


def close_session(rt, execution_id, status):
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    session = state.sessions[_open_session_id(state)]
    led.append("session_end", state.open_session, dict(session_kind=session["kind"], status=status), rt.now())


def verify_models(rt, execution_id):
    """§10: compare local models with mediapipe_model_lock.json; never downloads."""
    import analyze_d455
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    lock_path = Path(rt.root) / "mediapipe_model_lock.json"
    artifacts, status = [], "PASS"
    try:
        lock = analyze_d455.load_model_lock(str(lock_path))
        for role, entry in lock.items():
            path = Path(rt.root) / analyze_d455.MODEL_DIR / entry["filename"]
            try:
                info = analyze_d455.verify_model_artifact(str(path), entry)
                artifacts.append(dict(role=role, filename=entry["filename"], sha256=info["sha256"], verified=True))
            except (OSError, ValueError):
                artifacts.append(dict(role=role, filename=entry["filename"], sha256=None, verified=False))
                status = "FAIL"
    except ValueError:
        status = "FAIL"
    led.append("model_verification", _any_session(state), dict(
        status=status, lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(), artifacts=artifacts), rt.now())
    return status


def _any_session(state):
    if not state.sessions:
        raise RuntimeError("open a session first")
    return state.open_session or list(state.sessions)[-1]


def record_integrity(rt, execution_id, phase):
    """§84/§85: whole-repository integrity_check.py; exit 0 + PASS + ERROR 0 required."""
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    completed = rt.run([rt.python, str(Path(rt.root) / "integrity_check.py"), "--repo-root", str(rt.root)],
                       cwd=str(rt.root), capture_output=True, text=True, timeout=3600)
    last = (completed.stdout.strip().splitlines() or [""])[-1].split()
    counts = {}
    for item in last[:-1]:
        name, _, value = item.partition("=")
        if name in ("ERROR", "WARNING", "INFO") and value.isdigit():
            counts[name] = int(value)
    summary = last[-1] if last and last[-1] in ("PASS", "FAIL") and set(counts) == {"ERROR", "WARNING", "INFO"} else "FAIL"
    counts = counts if set(counts) == {"ERROR", "WARNING", "INFO"} else {"ERROR": -1, "WARNING": -1, "INFO": -1}
    led.append("integrity_check", _any_session(state), dict(phase=phase, exit_code=completed.returncode,
                                                           summary=summary, counts=counts), rt.now())
    return completed.returncode == 0 and summary == "PASS" and counts["ERROR"] == 0


def warmup(rt, execution_id):
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    session_id = _open_session_id(state)
    directory = execution_dir(rt.root, execution_id)
    out, err = _sealed_files(directory, f"warmup_{session_id}_{rt.now().strftime('%Y%m%dT%H%M%S%fZ')}")
    rt.console.seal()
    rt.console.phase("WARM-UP")
    process, files = launch_sealed(rt, [rt.python, str(Path(rt.root) / "patch8_static_capture.py"),
                                        "--warmup-seconds", str(p8.INITIAL_WARMUP_S)], out, err)
    try:
        result = supervise(rt, process, guide_timeout_s=None, reservation_seen=lambda: False, on_poll=lambda: None)
    finally:
        for stream in files:
            stream.close()
        rt.console.unseal()
    if result["exit_code"] != 0:
        rt.console.info("warm-up did not complete; run warm-up again")
        return False
    led.append("warmup_completed", session_id, dict(duration_s=p8.INITIAL_WARMUP_S, exit_code=0, logs=dict(
        stdout=_artifact(directory, out), stderr=_artifact(directory, err))), rt.now())
    return True


def setup_verified(rt, execution_id, pose, purpose):
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    led.append("setup_verified", _open_session_id(state), dict(purpose=purpose, camera_pose=pose), rt.now())


def pose_recheck(rt, execution_id, pose):
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    session_id = _open_session_id(state)
    initial = state.sessions[session_id]["setup_pose"]
    if initial is None:
        raise RuntimeError("no setup_verified pose in this session")
    differences, material = ledger.pose_differences(initial, pose)
    led.append("camera_pose_recheck", session_id, dict(camera_pose=pose, material_change=material,
                                                       differences=differences), rt.now())
    if material:
        led.append("execution_failed", session_id, dict(reason_code="CAMERA_POSE_MATERIAL_CHANGE",
                                                        detail="§7.4 re-check"), rt.now())
    return material


# ---------------------------------------------------------------- attempts
def attempt_identity(state, slot, attempt_index):
    value = dict(subject=state.subject, round=slot.round, attempt_index=attempt_index,
                 validation_protocol_version=slot.protocol_version)
    if slot.kind == p8.STATIC:
        value.update(nominal_distance=slot.nominal_distance_m, repetition_index=slot.repetition_index)
    return value


def child_command(rt, slot, subject):
    if slot.kind == p8.STATIC:
        return [rt.python, str(Path(rt.root) / "patch8_static_capture.py"), subject, slot.round,
                "--dataset-role", p8.DATASET_ROLE, "--data-dir", "data"]
    if slot.sequence_mode not in p8.PRODUCTION_SEQUENCES:
        raise DesignAuthorityGap(
            f"slot {slot.round}: sequence_mode {slot.sequence_mode!r} is not supported by CAP-005/CAP-006. "
            "An explicit authority entry is required before this sequence can be launched.")
    return [rt.python, str(Path(rt.root) / "capture_d455.py"), subject, slot.round,
            *(["core"] if slot.sequence_mode == "core" else []), "--dataset-role", p8.DATASET_ROLE]


def settle(rt, label):
    """§11/§29: 10 s settling; firewall output only (phase identity + timer)."""
    rt.console.phase(label)
    started = rt.clock()
    while rt.clock() - started < p8.SETTLING_S:
        rt.console.timer(rt.clock() - started, p8.SETTLING_S)
        rt.sleep(1.0)


def operator_declaration(rt):
    answer = rt.console.prompt("Did the operator end this attempt (q during recording, Ctrl-C, kill, "
                               "window/terminal closure, camera cable or power removal)? Type YES or NO:")
    answer = (answer or "").strip().upper()
    return {"YES": "operator_initiated", "NO": "not_operator_initiated"}.get(answer, "unknown")


def _record_observations(rt, led, session_id, slot, identity):
    for observation in rt.observations.poll():
        _, state = led.read()
        canonical_exists = state.canonical_static_take_exists()
        led.append("operator_observation", session_id, dict(
            identity, recording_id=None, status="observed", reason_code=None, observation=observation,
            retry_eligible=ledger.observation_retry_eligible(slot.kind, observation, canonical_exists)), rt.now())
        if slot.kind == p8.STATIC and observation == p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED and canonical_exists:
            led.append("execution_failed", session_id, dict(
                reason_code="CAMERA_DISTURBED_AFTER_FIRST_CANONICAL_STATIC_TAKE", detail="§7.3"), rt.now())


def prelock_evidence(rt, state, attempt, finished, declaration, power_evidence=None):
    """Gather only CAP-005-permitted pre-lock evidence and classify (§39, §47)."""
    data = Path(rt.root) / "data"
    slot = attempt.slot
    termination = finished["termination"]
    bound = finished["bound_recording_ids"]
    normal = (termination["exit_code"] == 0 and termination["signal"] is None and
              not termination["orchestrator_timeout_kill"] and termination["operator_signal_observed"] is None)
    raw = prelock.raw_path(data, bound[0]) if len(bound) == 1 else None
    raw_exists = (raw is not None) if finished["stage"] == "post_reservation" else None
    raw_probe = prelock.run_probe(["raw-probe", str(raw)], runner=rt.run, timeout=RAW_PROBE_TIMEOUT_S) \
        if raw is not None and declaration == "not_operator_initiated" else None
    if raw_probe is not None and set(raw_probe) != set(prelock.RAW_PROBE_FIELDS):
        raw_probe = None
    enumeration = None
    if not normal and declaration == "not_operator_initiated":
        found = prelock.run_probe(["enumerate"], runner=rt.run, timeout=ENUMERATION_TIMEOUT_S)
        pinned = state.baseline_environment.get("d455_serial")
        enumeration = {"probe_ok": False} if found is None else {
            "probe_ok": True, "pinned_serial_present": any(d.get("serial") == pinned for d in found.get("devices", []))}
    stderr = execution_dir(rt.root, state.execution_id) / finished["logs"]["stderr"]["path"] \
        if finished.get("logs") else None
    evidence = prelock.PrelockEvidence(
        slot_kind=slot.kind, stage=finished["stage"], bound_recording_ids=tuple(bound),
        exit_code=termination["exit_code"], signal=termination["signal"],
        orchestrator_timeout_kill=termination["orchestrator_timeout_kill"],
        operator_signal_observed=termination["operator_signal_observed"], operator_declaration=declaration,
        exception_class=prelock.extract_exception_class(stderr) if stderr is not None and not normal else None,
        static_exit_status=termination["static_exit_status"], raw_exists=raw_exists, raw_probe=raw_probe,
        enumeration=enumeration, power_evidence=power_evidence,
        observations=tuple(o["observation"] for o in attempt.observations), attempt_index=attempt.attempt_index,
        canonical_static_take_exists=state.canonical_static_take_exists(),
        execution_failed=state.execution_failure is not None)
    return evidence, prelock.classify(evidence)


def lock_attempt(rt, led, session_id, key, declaration, power_evidence=None):
    """capture_finished must exist; writes validity_locked then attempt_end (§40, §48)."""
    _, state = led.read()
    attempt = state.attempts[key]
    evidence, result = prelock_evidence(rt, state, attempt, attempt.finished, declaration, power_evidence)
    directory = execution_dir(rt.root, state.execution_id)
    stem = f"{state.subject}_r{attempt.round}_a{attempt.attempt_index}"
    record = directory / "state" / f"{stem}.prelock_evidence.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    with open(record, "xb") as stream:
        stream.write(ledger.canonical_bytes(ledger.json_safe(prelock.evidence_record(evidence, result))) + b"\n")
    identity = attempt_identity(state, attempt.slot, attempt.attempt_index)
    common = dict(identity, recording_id=attempt.finished["recording_id"], reason_code=result.reason_code)
    led.append("validity_locked", session_id, dict(
        common, status="locked", stage=result.stage, acquisition_valid=result.acquisition_valid,
        retry_allowed=result.retry_allowed, rule_id=result.rule_id, evidence_used=list(result.evidence_used),
        operator_declaration=declaration,
        machine_evidence_ref=_artifact(directory, record) if result.reason_code in p8.MACHINE_INVALID_REASONS else None),
        rt.now())
    led.append("attempt_end", session_id, dict(common, status="ended"), rt.now())
    return result


def record_outcome(rt, led, session_id, key):
    """Post-lock production disposition (§79–§81); recorded once, never revised (§38)."""
    _, state = led.read()
    attempt = state.attempts[key]
    if attempt.slot.kind == p8.STATIC or not attempt.locked["acquisition_valid"]:
        return None
    outcome = report.attempt_outcome_from_evidence(rt.root, state, attempt)
    led.append("attempt_outcome", session_id, dict(
        attempt_identity(state, attempt.slot, attempt.attempt_index), recording_id=attempt.recording_id,
        status="outcome_recorded", reason_code=outcome["reason_code"], outcome=outcome["outcome"],
        evidence=ledger.json_safe(outcome["evidence"])), rt.now())
    return outcome


def run_attempt(rt, execution_id, rnd, setup_checks):
    slot = p8.slot(rnd)
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    session_id = _open_session_id(state)
    command = child_command(rt, slot, state.subject)          # fails closed on design gap
    attempt_index = state.next_attempt_index(rnd)
    if attempt_index is None:
        raise RuntimeError(f"slot {rnd}: no further attempt is authorized")
    if setup_checks != {k: True for k in ledger.SETUP_CHECKS}:
        raise RuntimeError("pre-attempt setup checks failed: attempt not started, no recording_id (§7.6)")
    identity = attempt_identity(state, slot, attempt_index)
    static = slot.kind == p8.STATIC
    if static:
        rt.console.seal()                                      # §25 firewall from settling start
    settle(rt, "SETTLING")
    data = Path(rt.root) / "data"
    before = prelock.recording_inventory(data)
    led.append("attempt_start", session_id, dict(
        identity, recording_id=None, status="started", reason_code=None, slot_kind=slot.kind,
        sequence_mode=None if static else slot.sequence_mode, setup_checks=dict(setup_checks),
        settling_s=p8.SETTLING_S, pre_launch_inventory=before, code_state=code_state(rt)), rt.now())
    directory = execution_dir(rt.root, execution_id)
    out, err = _sealed_files(directory, f"{state.subject}_r{rnd}_a{attempt_index}")
    rt.console.phase("STATIC HOLD (upright)" if static else f"PRODUCTION SLOT {rnd}")
    rt.console.recording_state("CHILD RUNNING")

    def reservation_seen():
        return any(prelock.valid_reservation(data, i, state.subject, rnd)
                   for i in prelock.new_recordings(before, prelock.recording_inventory(data)))
    shown = set()

    def tick(elapsed):
        if int(elapsed) not in shown:
            shown.add(int(elapsed))
            rt.console.timer(elapsed, p8.STATIC_HOLD_S)
    process, files = launch_sealed(rt, command, out, err)      # §50 exactly one launch
    try:
        termination = supervise(rt, process, guide_timeout_s=None if static else p8.GUIDE_RESERVATION_TIMEOUT_S,
                                reservation_seen=reservation_seen,
                                on_poll=lambda: _record_observations(rt, led, session_id, slot, identity),
                                on_tick=tick if static else None)
    finally:
        for stream in files:
            stream.close()
    _record_observations(rt, led, session_id, slot, identity)
    rt.console.recording_state("STOPPED")
    bound = prelock.new_recordings(before, prelock.recording_inventory(data))
    stage = "post_reservation" if any((data / (i + "_camera.json")).exists() for i in bound) else "pre_reservation"
    termination["static_exit_status"] = prelock.STATIC_EXIT_STATUS.get(termination["exit_code"]) if static else None
    termination["recovered"] = False
    led.append("capture_finished", session_id, dict(
        identity, recording_id=bound[0] if len(bound) == 1 else None, status="finished", reason_code=None,
        stage=stage, bound_recording_ids=bound, termination=termination,
        logs=dict(stdout=_artifact(directory, out), stderr=_artifact(directory, err))), rt.now())
    declaration = operator_declaration(rt)
    result = lock_attempt(rt, led, session_id, (rnd, attempt_index), declaration)
    rt.console.unseal()                                        # validity_locked + attempt_end recorded
    rt.console.info(f"slot {rnd} attempt {attempt_index} locked: acquisition_valid={result.acquisition_valid} "
                    f"reason={result.reason_code} retry_allowed={result.retry_allowed}")
    outcome = record_outcome(rt, led, session_id, (rnd, attempt_index))
    if outcome is not None:
        rt.console.info(f"slot {rnd} attempt {attempt_index} outcome: {outcome['outcome']} {outcome['reason_code']}")
    return result, outcome


def recover_attempt(rt, execution_id, declaration, power_evidence=None):
    """Close an attempt left open by an orchestrator/host interruption (fail-closed, §45)."""
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    attempt = state.open_attempt()
    if attempt is None:
        raise RuntimeError("no open attempt to recover")
    session_id = attempt.start["session_id"]
    if state.open_session != session_id:
        raise RuntimeError("the attempt's session is not open")
    identity = attempt_identity(state, attempt.slot, attempt.attempt_index)
    if power_evidence is not None:   # the lock is immutable: refuse rather than lock without the evidence
        end = attempt.finished["event_timestamp_utc"] if attempt.finished else ledger.utc_timestamp(rt.now())
        power_evidence = prelock.validate_power_evidence(power_evidence, execution_dir(rt.root, execution_id),
                                                         attempt.start["event_timestamp_utc"], end)
        if power_evidence is None:
            raise RuntimeError("power-loss evidence rejected (§47.4); attempt left unlocked for correction")
    if attempt.finished is None:
        data = Path(rt.root) / "data"
        bound = prelock.new_recordings(attempt.start["pre_launch_inventory"], prelock.recording_inventory(data))
        stage = "post_reservation" if any((data / (i + "_camera.json")).exists() for i in bound) else "pre_reservation"
        termination = dict(exit_code=None, signal=None, orchestrator_timeout_kill=False, operator_signal_observed=None,
                           static_exit_status=None, recovered=True, reservation_observed_s=None)
        led.append("capture_finished", session_id, dict(
            identity, recording_id=bound[0] if len(bound) == 1 else None, status="finished", reason_code=None,
            stage=stage, bound_recording_ids=bound, termination=termination, logs=None), rt.now())
    result = lock_attempt(rt, led, session_id, (attempt.round, attempt.attempt_index), declaration, power_evidence)
    record_outcome(rt, led, session_id, (attempt.round, attempt.attempt_index))
    return result


# ---------------------------------------------------------------- analysis (§52–§54)
def analyze(rt, execution_id, rnd):
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    attempt = state.canonical_attempt(rnd)
    if attempt is None or attempt.recording_id is None:
        raise RuntimeError(f"slot {rnd} has no ledger-canonical recording")
    rid = attempt.recording_id
    if not state.analysis_invocation_allowed(rid):
        raise RuntimeError("analysis not authorized: first completed run is canonical; re-analysis needs a "
                           "logged infrastructure failure (§53, §54)")
    capture = report.read_capture(rt.root, state.unseal(rnd, attempt.attempt_index)) or {}
    raw = Path(rt.root) / "data" / str(capture.get("record_file"))
    if capture.get("record_file") not in (rid + ".db3", rid + ".bag") or not raw.is_file():
        raise RuntimeError("canonical raw recording missing")
    runs_dir = Path(rt.root) / "analysis" / rid
    before = {p.name for p in runs_dir.glob("ar_*")}
    index = len((state.analyses.get(rid) or {"invocations": []})["invocations"]) + 1
    directory = execution_dir(rt.root, execution_id)
    out, err = _sealed_files(directory, f"analysis_{rid}_{index}")
    process, files = launch_sealed(rt, [rt.python, str(Path(rt.root) / "patch8_validation.py"), "_analyze-one",
                                        str(raw)], out, err)
    try:
        code = process.wait()
    finally:
        for stream in files:
            stream.close()
    runs = []
    for name in sorted({p.name for p in runs_dir.glob("ar_*")} - before):
        path = runs_dir / name / "analysis_manifest.json"
        manifest = report.json_file(path) or {}
        runs.append(dict(analysis_run_id=name, status=manifest.get("status") if manifest.get("status") in
                         ("running", "failed", "completed") else "failed",
                         manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
    record = state.analyses.get(rid) or {}
    completed = [r["analysis_run_id"] for r in runs if r["status"] == "completed"]
    canonical = completed[0] if completed and record.get("canonical") is None else None
    led.append("analysis_invocation", _any_session(state), dict(
        subject=state.subject, round=rnd, attempt_index=attempt.attempt_index, recording_id=rid,
        invocation_index=index, exit_code=code if isinstance(code, int) else None, analysis_runs=runs,
        canonical_analysis_run_id=canonical, logs=dict(stdout=_artifact(directory, out),
                                                       stderr=_artifact(directory, err))), rt.now())
    return canonical


def analysis_infrastructure_failure(rt, execution_id, rnd, evidence_path, analysis_run_id=None):
    led = open_ledger(rt.root, execution_id)
    _, state = led.read()
    attempt = state.canonical_attempt(rnd)
    if attempt is None:
        raise RuntimeError("no canonical attempt")
    directory = execution_dir(rt.root, execution_id)
    path = Path(evidence_path).resolve()
    if not path.is_file() or not path.is_relative_to(directory.resolve()):
        raise RuntimeError("infrastructure-failure evidence must be a file under the execution directory (§54)")
    reference = _artifact(directory.resolve(), path)
    led.append("analysis_infrastructure_failure", _any_session(state), dict(
        subject=state.subject, round=rnd, attempt_index=attempt.attempt_index, recording_id=attempt.recording_id,
        analysis_run_id=analysis_run_id, evidence_ref=reference["path"], evidence_sha256=reference["sha256"]), rt.now())


def analyze_one(path):
    """Internal child entry: exactly one explicit recording per invocation, step = 1 (§52)."""
    import analyze_d455
    subject, _ = analyze_d455.parse_name(path)
    analyze_d455.run_analysis([path], argparse.Namespace(subjects=[subject], step=1, from_csv=False,
                                                         legacy_pilot=False))


# ---------------------------------------------------------------- evaluation / reports
def evaluate(rt, execution_id, publish=False):
    path = execution_dir(rt.root, execution_id) / p8.LEDGER_FILENAME
    reports = report.evaluate_execution(rt.root, path)
    if publish:
        led = open_ledger(rt.root, execution_id)
        _, state = led.read()
        directory = execution_dir(rt.root, execution_id)
        for kind, name in report.REPORT_FILES.items():
            with open(directory / name, "xb") as stream:
                stream.write(report.report_bytes(reports[kind]))
        final = directory / report.REPORT_FILES["execution"]
        led.append("report_published", _any_session(state), dict(
            report_path=final.relative_to(directory).as_posix(),
            report_sha256=hashlib.sha256(final.read_bytes()).hexdigest()), rt.now())
    return reports


def show_protocol():
    return dict(
        ledger_format_version=p8.LEDGER_FORMAT_VERSION, static_protocol_version=p8.STATIC_PROTOCOL_VERSION,
        production_protocol_version=p8.PRODUCTION_PROTOCOL_VERSION, static_grid_m=p8.STATIC_GRID_M,
        mandatory_anchors_m=p8.MANDATORY_ANCHORS_M, static_repetitions=p8.STATIC_REPETITIONS,
        static_hold_s=p8.STATIC_HOLD_S, static_window_s=[p8.STATIC_WINDOW_START_S, p8.STATIC_WINDOW_END_S],
        expected_frame_denominator=p8.EXPECTED_FRAME_DENOMINATOR, min_window_rows=p8.MIN_WINDOW_ROWS,
        thresholds=dict(frame_coverage=p8.FRAME_COVERAGE_MIN, landmark=p8.LANDMARK_RATE_MIN,
                        conditional_depth=p8.CONDITIONAL_DEPTH_RATE_MIN, complete_rgbd=p8.COMPLETE_RGBD_RATE_MIN,
                        min_valid_n=p8.MIN_VALID_N, depth_sd_mm=p8.DEPTH_TEMPORAL_SD_MAX_MM,
                        within_take_cv=p8.WITHIN_TAKE_CV_MAX, between_take_spread=p8.BETWEEN_TAKE_SPREAD_MAX,
                        distance_stability=p8.DISTANCE_STABILITY_MAX),
        forward_bands_m=p8.FORWARD_BANDS_M,
        slots={r: dict(kind=s.kind, protocol_version=s.protocol_version, nominal_distance_m=s.nominal_distance_m,
                       repetition_index=s.repetition_index, designated_phases=list(s.designated_phases),
                       band=s.band, sequence_mode=s.sequence_mode) for r, s in p8.SLOTS.items()})


# ---------------------------------------------------------------- CLI
def _pose(args, recheck):
    pose = dict(reference_height_mm=args.reference_height_mm, pitch_deg=args.pitch_deg, yaw_deg=args.yaw_deg,
                roll_deg=args.roll_deg, mount_identity=args.mount_identity, camera_position=args.camera_position,
                witness_marks=args.witness_marks)
    if recheck:
        pose["witness_mark_displaced"] = args.witness_mark_displaced == "yes"
    return pose


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show-protocol", help="print frozen CAP-005 values (read-only)")
    for name in ("verify-ledger", "evaluate", "open-session", "close-session", "verify-models", "integrity",
                 "warmup", "setup", "pose-recheck", "attempt", "recover-attempt", "analyze",
                 "analysis-infrastructure-failure", "terminate-execution"):
        command = sub.add_parser(name)
        command.add_argument("--execution-id", required=True)
        if name == "evaluate":
            command.add_argument("--publish", action="store_true", help="write reports (formal; gated)")
        if name == "open-session":
            command.add_argument("--session-kind", required=True, choices=sorted(p8.SESSION_KINDS.values()))
            command.add_argument("--subject", required=True)
        if name == "close-session":
            command.add_argument("--status", required=True, choices=("completed", "aborted"))
        if name == "integrity":
            command.add_argument("--phase", required=True, choices=("pre_hardware", "closure"))
        if name in ("setup", "pose-recheck"):
            for option in ("reference-height-mm", "pitch-deg", "yaw-deg", "roll-deg"):
                command.add_argument("--" + option, type=float, required=True)
            for option in ("mount-identity", "camera-position", "witness-marks"):
                command.add_argument("--" + option, required=True)
            if name == "setup":
                command.add_argument("--purpose", required=True, choices=("initial", "reset"))
            else:
                command.add_argument("--witness-mark-displaced", required=True, choices=("yes", "no"))
        if name == "attempt":
            command.add_argument("--round", required=True, choices=list(p8.SLOTS))
            for check in ledger.SETUP_CHECKS:
                command.add_argument("--" + check.replace("_", "-"), action="store_true")
        if name == "recover-attempt":
            command.add_argument("--declaration", required=True, choices=("operator_initiated",
                                                                         "not_operator_initiated", "unknown"))
            command.add_argument("--power-evidence-kind", choices=prelock.POWER_EVIDENCE_KINDS)
            command.add_argument("--power-evidence-path")
            command.add_argument("--power-event-time-utc")
        if name in ("analyze", "analysis-infrastructure-failure"):
            command.add_argument("--round", required=True, choices=list(p8.SLOTS))
        if name == "analysis-infrastructure-failure":
            command.add_argument("--evidence-path", required=True)
            command.add_argument("--analysis-run-id")
    internal = sub.add_parser("_analyze-one", help=argparse.SUPPRESS)
    internal.add_argument("path")
    return parser


def main(argv=None, rt=None):
    args = build_parser().parse_args(argv)
    rt = rt or Runtime(root=args.root.resolve())
    try:
        if args.command == "show-protocol":
            print(json.dumps(show_protocol(), indent=2, sort_keys=True))
            return 0
        if args.command == "_analyze-one":
            analyze_one(args.path)
            return 0
        if args.command == "verify-ledger":
            events, state = ledger.verify_ledger(execution_dir(rt.root, args.execution_id) / p8.LEDGER_FILENAME)
            print(f"LEDGER PASS events={len(events)} last_event_sha256={events[-1]['event_sha256'] if events else None}")
            return 0
        if args.command == "evaluate" and not args.publish:
            result = evaluate(rt, args.execution_id)["execution"]
            print(json.dumps(ledger.json_safe(report._keys_to_text(result)), indent=2, sort_keys=True))
            return 0
        authorization_gate(rt, args.execution_id)
        if args.command == "evaluate":
            evaluate(rt, args.execution_id, publish=True)
        elif args.command == "open-session":
            print(open_session(rt, args.execution_id, args.session_kind, args.subject))
        elif args.command == "close-session":
            close_session(rt, args.execution_id, args.status)
        elif args.command == "verify-models":
            return 0 if verify_models(rt, args.execution_id) == "PASS" else 1
        elif args.command == "integrity":
            return 0 if record_integrity(rt, args.execution_id, args.phase) else 1
        elif args.command == "warmup":
            return 0 if warmup(rt, args.execution_id) else 1
        elif args.command == "setup":
            setup_verified(rt, args.execution_id, _pose(args, False), args.purpose)
        elif args.command == "pose-recheck":
            return 1 if pose_recheck(rt, args.execution_id, _pose(args, True)) else 0
        elif args.command == "attempt":
            checks = {k: bool(getattr(args, k)) for k in ledger.SETUP_CHECKS}
            run_attempt(rt, args.execution_id, args.round, checks)
        elif args.command == "recover-attempt":
            power = None
            if args.power_evidence_path:
                directory = execution_dir(rt.root, args.execution_id)
                path = (directory / args.power_evidence_path).resolve()
                power = dict(kind=args.power_evidence_kind, path=args.power_evidence_path,
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             event_time_utc=args.power_event_time_utc)
            recover_attempt(rt, args.execution_id, args.declaration, power)
        elif args.command == "analyze":
            analyze(rt, args.execution_id, args.round)
        elif args.command == "analysis-infrastructure-failure":
            analysis_infrastructure_failure(rt, args.execution_id, args.round, args.evidence_path, args.analysis_run_id)
        elif args.command == "terminate-execution":
            led = open_ledger(rt.root, args.execution_id)
            _, state = led.read()
            led.append("execution_failed", _any_session(state), dict(reason_code="OPERATOR_TERMINATED_EXECUTION",
                                                                     detail=None), rt.now())
        return 0
    except (ExecutionNotAuthorized, DesignAuthorityGap, ledger.LedgerError, ledger.SealedResultError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 3
    except RuntimeError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
