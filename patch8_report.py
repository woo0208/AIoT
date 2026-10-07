"""Patch 8 post-execution evaluation, reconciliation and reports (CAP-005 §52–§53, §71–§87).

Read-only over data/, analysis/ and the verified ledger. Result-bearing capture evidence
is read only through an UnsealToken issued by the ledger after validity_locked +
attempt_end. Canonical analysis is the ledger's first completed run (§53); no later
"better" run is ever selected, and no broad glob chooses canonical results. Reports are
operational validation artifacts, not frames/summary schema replacements.
"""
from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path

import patch8_ledger as ledger
import patch8_metrics as metrics
import patch8_prelock as prelock
import patch8_protocol as p8


REPORT_FILES = {"metrics": "patch8_metrics_report.json",
                "reconciliation": "patch8_reconciliation_report.json",
                "execution": "patch8_execution_report.json"}
EXTERNAL_CONDITIONS = ("A_cap005_committed", "B_implementation_completed", "C_implementation_audit",
                       "D_execution_pre_registered", "E_clean_execution_workspace",
                       "Y_ledger_report_hashes_recorded")


# ---------------------------------------------------------------- sealed evidence access (§40, §41.1)
def _paths(root, recording_id):
    data = Path(root) / "data"
    return {kind: data / f"{recording_id}_{kind}.{ext}" for kind, ext in
            (("camera", "json"), ("markers", "csv"), ("samples", "csv"), ("quality", "json"))}


def _check_token(token, recording_id=None):
    if not isinstance(token, ledger.UnsealToken):
        raise ledger.SealedResultError("result-bearing evidence requires a ledger UnsealToken")
    if recording_id is not None and token.recording_id != recording_id:
        raise ledger.SealedResultError("UnsealToken belongs to another recording")
    return token.recording_id


def json_file(path):
    try:
        value = json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _csv_file(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def read_capture(root, token):
    return json_file(_paths(root, _check_token(token))["camera"])


def read_quality(root, token):
    return json_file(_paths(root, _check_token(token))["quality"])


def read_samples(root, token):
    return _csv_file(_paths(root, _check_token(token))["samples"])


def read_markers(root, token):
    return _csv_file(_paths(root, _check_token(token))["markers"])


def phase_duration(markers, label):
    """Planned duration of the single designated hold phase recorded in the markers sidecar."""
    rows = [m for m in markers or [] if m.get("phase") == "hold" and m.get("label") == label]
    if len(rows) != 1:
        return None
    try:
        return float(rows[0].get("planned_sec"))
    except (TypeError, ValueError):
        return None


def attempt_outcome_from_evidence(root, state, attempt):
    """Deterministic §79/§80/§81 post-lock outcome; used live and re-verified at evaluation."""
    token = state.unseal(attempt.round, attempt.attempt_index) if attempt.recording_id else None
    lock_reason = attempt.locked["reason_code"]
    slot = attempt.slot
    if slot.kind == p8.E2E or token is None:
        return metrics._outcome(p8.CANONICAL, lock_reason if lock_reason is not None else
                                (None if token is not None else p8.UNCLASSIFIED_TERMINATION))
    capture, quality = read_capture(root, token), read_quality(root, token)
    if slot.kind == p8.FORWARD:
        return metrics.forward_attempt_outcome(lock_reason, capture, quality, slot)
    duration = phase_duration(read_markers(root, token), "body_forward")
    return metrics.body_only_attempt_outcome(lock_reason, capture, quality, read_samples(root, token), duration)


# ---------------------------------------------------------------- canonical analysis (§52, §53)
def canonical_analysis(root, state, recording_id):
    record = state.analyses.get(recording_id) or {}
    run = record.get("canonical")
    if run is None:
        return None
    directory = Path(root) / "analysis" / recording_id / run
    manifest = json_file(directory / "analysis_manifest.json")
    if manifest is None:
        return dict(run=run, manifest=None, batch=None, frames_path=None, predicate=dict(passed=False, checks={}))
    batch = json_file(Path(root) / "analysis" / "batches" / str(manifest.get("analysis_batch_id")) /
                       "analysis_batch.json")
    frames = [o for o in manifest.get("outputs", []) if isinstance(o, dict) and o.get("kind") == "frames"]
    frames_path = Path(frames[0]["path"]) if len(frames) == 1 and isinstance(frames[0].get("path"), str) else None
    return dict(run=run, manifest=manifest, batch=batch, frames_path=frames_path,
                predicate=metrics.canonical_analysis_predicate(manifest, batch))


def load_canonical_rows(root, analysis):
    """Frames rows via the Patch 5 canonical-input validator and the Patch 4 reader."""
    import analyze_d455
    import rf_experiment as rf
    if analysis is None or analysis["frames_path"] is None:
        return None
    try:
        entry = rf.canonical_input(analysis["frames_path"], Path(root) / "analysis")
        if entry["analysis_run_id"] != analysis["run"]:
            return None
        with redirect_stdout(io.StringIO()):
            return analyze_d455.load_frames_csv([], paths=[entry["frames_path"]])
    except (OSError, ValueError):
        return None


def deprojection(analysis, capture, factory=None):
    playback = (analysis or {}).get("manifest", {}) or {}
    calibration = metrics.calibration_check(playback.get("playback_calibration"), capture)
    if not calibration["passed"]:
        return calibration, None
    factory = factory or metrics.sdk_deprojector
    try:
        return calibration, factory(playback["playback_calibration"]["color_intrinsics"])
    except (metrics.CalibrationError, ImportError) as error:
        return dict(passed=False, failures=[f"deprojection unavailable: {type(error).__name__}: {error}"]), None


# ---------------------------------------------------------------- slot evaluation
def evaluate_static_takes(root, state, deprojector_factory=None):
    takes = {}
    for rnd in p8.STATIC_ROUNDS:
        attempts = state.slot_attempts(rnd)
        attempt = state.canonical_attempt(rnd)
        if not attempts:
            takes[rnd] = metrics.unevaluated_take("NOT_EXECUTED")
        elif attempt is None:
            takes[rnd] = metrics.unevaluated_take("NO_CANONICAL_TAKE")
        elif attempt.locked["reason_code"] in p8.VALID_FAIL_REASONS:
            takes[rnd] = metrics.unevaluated_take(attempt.locked["reason_code"], canonical=True)
        else:
            analysis = canonical_analysis(root, state, attempt.recording_id)
            rows = load_canonical_rows(root, analysis) if analysis and analysis["predicate"]["passed"] else None
            if rows is None:
                reason = "NO_CANONICAL_ANALYSIS" if analysis is None else "CANONICAL_ANALYSIS_NOT_CONFORMING"
                takes[rnd] = metrics.unevaluated_take(reason, canonical=True)
                continue
            capture = read_capture(root, state.unseal(rnd, attempt.attempt_index))
            calibration, deproject = deprojection(analysis, capture, deprojector_factory)
            takes[rnd] = metrics.evaluate_static_take(rows, deproject=deproject, calibration=calibration)
        takes[rnd].update(round=rnd, attempt_index=attempt.attempt_index if attempt else None,
                          recording_id=attempt.recording_id if attempt else None,
                          nominal_distance_m=p8.SLOTS[rnd].nominal_distance_m,
                          repetition_index=p8.SLOTS[rnd].repetition_index)
    return takes


def _availability(root, state, attempt, analysis, labels):
    rows = load_canonical_rows(root, analysis) if analysis and analysis["predicate"]["passed"] else None
    markers = read_markers(root, state.unseal(attempt.round, attempt.attempt_index))
    result = {}
    for label in labels:
        duration = phase_duration(markers, label)
        result[label] = (metrics.evaluate_forward_availability(rows, label, duration) if rows is not None
                         else dict(label=label, passed=False, checks=dict(canonical_frames=False)))
    return result


def evaluate_production_slot(root, state, rnd):
    slot = p8.slot(rnd)
    if slot.kind not in (p8.FORWARD, p8.BODY_ONLY_NEGATIVE):
        raise ValueError("forward / body-only slots only; slot 131 uses evaluate_slot131")
    attempts = state.slot_attempts(rnd)
    attempt = state.canonical_attempt(rnd)
    base = dict(round=rnd, kind=slot.kind, attempts=len(attempts), passed=False)
    if not attempts:
        return dict(base, fail_reason="NOT_EXECUTED")
    if attempt is None:
        return dict(base, fail_reason="NO_CANONICAL_ATTEMPT")
    outcome = attempt.outcome
    base.update(canonical_attempt_index=attempt.attempt_index, recording_id=attempt.recording_id,
                outcome_reason=outcome["reason_code"])
    analysis = canonical_analysis(root, state, attempt.recording_id) if attempt.recording_id else None
    if slot.kind == p8.BODY_ONLY_NEGATIVE:
        return dict(base, passed=outcome["reason_code"] is None, fail_reason=outcome["reason_code"])
    if outcome["reason_code"] is not None or attempt.recording_id is None:
        return dict(base, fail_reason=outcome["reason_code"] or "NO_RECORDING")
    availability = _availability(root, state, attempt, analysis, slot.designated_phases)
    class_gate = bool(outcome["evidence"].get("class_gate_passed"))
    passed = class_gate and all(a["passed"] for a in availability.values())
    return dict(base, availability=availability, class_gate_passed=class_gate, passed=passed,
                fail_reason=None if passed else "AVAILABILITY_OR_CLASS_GATE")


def evaluate_slot131(root, state, recording_reconciliation, analysis_reconciliation):
    attempt = state.canonical_attempt("131")
    quality = availability = analysis = lineage = None
    if attempt is not None and attempt.recording_id is not None and attempt.locked["reason_code"] is None:
        token = state.unseal("131", attempt.attempt_index)
        quality = read_quality(root, token)
        analysis = canonical_analysis(root, state, attempt.recording_id)
        availability = _availability(root, state, attempt, analysis, p8.SLOTS["131"].designated_phases)
        lineage = artifact_lineage(root, state, attempt, analysis)
    rec_ok = not any(f.get("round") == "131" for f in recording_reconciliation["failures"])
    ana_ok = not any(f.get("round") == "131" for f in analysis_reconciliation["failures"])
    result = metrics.slot131_predicate(
        canonical_exists=attempt is not None and attempt.recording_id is not None and
        attempt.locked["reason_code"] is None,
        quality=quality, availability=availability or {}, analysis=analysis and analysis["predicate"],
        lineage=lineage, recording_reconciled=rec_ok and recording_reconciliation["executed"],
        analysis_reconciled=ana_ok)
    result.update(round="131", attempts=len(state.slot_attempts("131")), availability=availability,
                  lineage=lineage, recording_id=attempt.recording_id if attempt else None)
    return result


# ---------------------------------------------------------------- §81.5 artifact / lineage
def artifact_lineage(root, state, attempt, analysis):
    import analyze_d455
    import rf_experiment as rf
    root = Path(root)
    rid, slot = attempt.recording_id, attempt.slot
    paths = _paths(root, rid)
    checks = {}
    token = state.unseal(attempt.round, attempt.attempt_index)
    capture = read_capture(root, token)
    sidecars = {kind: f"{rid}_{kind}.{ext}" for kind, ext in
                (("camera", "json"), ("markers", "csv"), ("samples", "csv"), ("quality", "json"))}
    checks["capture_provenance"] = isinstance(capture, dict) and all((
        capture.get("schema_version") == p8.CAPTURE_PROVENANCE_SCHEMA, capture.get("recording_id") == rid,
        capture.get("subject") == state.subject, capture.get("round") == slot.round,
        capture.get("dataset_role") == p8.DATASET_ROLE, capture.get("protocol_version") == slot.protocol_version,
        capture.get("sidecar_files") == sidecars,
        [tuple(s) for s in capture.get("sequence") or []] == list(p8.PRODUCTION_SEQUENCES[slot.sequence_mode])))
    raw = root / "data" / str((capture or {}).get("record_file"))
    checks["raw_recording"] = isinstance(capture, dict) and capture.get("record_file") in (rid + ".db3", rid + ".bag") \
        and raw.is_file()
    for kind, reader in (("markers", read_markers), ("samples", read_samples)):
        rows = reader(root, token)
        checks[f"{kind}_sidecar"] = bool(rows) and all(r.get("recording_id") == rid for r in rows)
    quality = read_quality(root, token)
    checks["quality_sidecar"] = isinstance(quality, dict) and quality.get("recording_id") == rid
    manifest = (analysis or {}).get("manifest") or {}
    checks["analysis_manifest"] = bool(manifest) and manifest.get("recording_id") == rid and \
        manifest.get("analysis_run_id") == (analysis or {}).get("run") and manifest.get("status") == "completed"

    def identity(path):
        try:
            return rf.file_identity(path)["sha256"]
        except (OSError, ValueError):
            return None
    inputs = manifest.get("inputs") or {}
    checks["input_hashes"] = bool(inputs) and all(
        isinstance(inputs.get(k), dict) and inputs[k].get("sha256") is not None and
        inputs[k]["sha256"] == identity(target) for k, target in
        (("recording", raw), ("capture_metadata", paths["camera"]), ("markers", paths["markers"]),
         ("quality", paths["quality"])))
    try:
        entry = rf.canonical_input((analysis or {}).get("frames_path"), root / "analysis")
        checks["canonical_frames"] = (entry["recording_id"], entry["analysis_run_id"], entry["subject"],
                                      entry["round"]) == (rid, analysis["run"], state.subject, slot.round)
    except (OSError, TypeError, ValueError):
        checks["canonical_frames"] = False
    outputs = [o for o in manifest.get("outputs") or [] if isinstance(o, dict)]
    checks["output_hashes"] = bool(outputs) and all(o.get("sha256") is not None and
                                                    identity(o.get("path", "")) == o["sha256"] for o in outputs)
    batch = (analysis or {}).get("batch") or {}
    batch_dir = root / "analysis" / "batches" / str(manifest.get("analysis_batch_id"))
    checks["analysis_batch"] = bool(batch) and batch.get("analysis_batch_id") == manifest.get("analysis_batch_id") \
        and analysis["run"] in (batch.get("analysis_run_ids") or [])
    summary = [o for o in batch.get("outputs") or [] if isinstance(o, dict) and
               Path(o.get("path", "")).name == "summary_steps.csv"]
    summary_ok = (len(summary) == 1 and summary[0].get("schema_version") == analyze_d455.SUMMARY_SCHEMA_VERSION and
                  Path(summary[0]["path"]).resolve() == (batch_dir / "summary_steps.csv").resolve() and
                  identity(summary[0]["path"]) == summary[0].get("sha256"))
    rows = _csv_file(batch_dir / "summary_steps.csv") if summary_ok else None
    checks["canonical_summary"] = bool(rows) and all(
        r.get("recording_id") == rid and r.get("analysis_run_id") == analysis["run"] and
        r.get("summary_schema_version") == analyze_d455.SUMMARY_SCHEMA_VERSION for r in rows)
    try:
        lock = analyze_d455.load_model_lock(str(root / "mediapipe_model_lock.json"))
        models = {m.get("role"): m for m in manifest.get("models") or [] if isinstance(m, dict)}
        checks["model_lock_identity"] = manifest.get("inference_performed") is True and set(models) == set(lock) and \
            all(models[r].get("sha256") == lock[r]["sha256"] and models[r].get("used_in_this_run") is True for r in lock)
    except (OSError, ValueError):
        checks["model_lock_identity"] = False
    return dict(passed=all(checks.values()), checks=checks)


# ---------------------------------------------------------------- §82 / §83 reconciliation
def reconcile_recordings(root, state):
    failures = []
    first = next((s for s in state.sessions.values()), None)
    if first is None:
        return dict(passed=False, executed=False, failures=[dict(code="NO_SESSION")], created=[])
    current = prelock.recording_inventory(Path(root) / "data")
    created = sorted(set(current) - set(first["inventory"]))
    bindings = {}
    for attempt in state.attempts.values():
        for rid in (attempt.finished or {}).get("bound_recording_ids", []):
            bindings.setdefault(rid, []).append(attempt)
    for rid in created:
        bound = bindings.get(rid, [])
        if len(bound) != 1:
            failures.append(dict(recording_id=rid, round=None, code="NOT_EXACTLY_ONE_ATTEMPT_BINDING",
                                 bindings=len(bound)))
            continue
        attempt = bound[0]
        try:
            capture = read_capture(root, state.unseal_binding(attempt.round, attempt.attempt_index, rid))
        except ledger.SealedResultError:
            capture = None
        expected = (state.subject, attempt.round, rid, attempt.slot.protocol_version)
        observed = tuple((capture or {}).get(k) for k in ("subject", "round", "recording_id", "protocol_version"))
        if not rid.startswith(f"{state.subject}_r{attempt.round}_") or observed != expected:
            failures.append(dict(recording_id=rid, round=attempt.round, code="IDENTITY_MISMATCH"))
    for rid, attempts in sorted(bindings.items()):
        if rid not in created:
            failures.append(dict(recording_id=rid, round=attempts[0].round, code="BOUND_RECORDING_NOT_EXECUTION_CREATED"))
    return dict(passed=not failures, executed=True, failures=failures, created=created)


def reconcile_analyses(root, state, created):
    failures = []
    logged = {}
    for rid, record in state.analyses.items():
        for invocation in record["invocations"]:
            for run in invocation["analysis_runs"]:
                logged[(rid, run["analysis_run_id"])] = run
    canonical = state.canonical_recordings()
    for rid, attempt in sorted(canonical.items()):
        run = (state.analyses.get(rid) or {}).get("canonical")
        if run is None:
            failures.append(dict(recording_id=rid, round=attempt.round, code="NO_CANONICAL_ANALYSIS_RUN"))
            continue
        path = Path(root) / "analysis" / rid / run / "analysis_manifest.json"
        manifest = json_file(path)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = None
        if manifest is None or manifest.get("status") != "completed" or manifest.get("recording_id") != rid or \
                digest != logged[(rid, run)]["manifest_sha256"]:
            failures.append(dict(recording_id=rid, round=attempt.round, code="CANONICAL_RUN_CHANGED_OR_MISSING"))
    rounds = {a.recording_id: a.round for a in state.attempts.values() if a.recording_id}
    for rid in created:
        for path in sorted((Path(root) / "analysis" / rid).glob("ar_*/analysis_manifest.json")):
            manifest = json_file(path) or {}
            key = (rid, path.parent.name)
            if key not in logged:
                if manifest.get("status") == "completed":
                    failures.append(dict(recording_id=rid, round=rounds.get(rid), code="UNLOGGED_COMPLETED_RUN",
                                         analysis_run_id=path.parent.name))
            elif manifest.get("status") != logged[key]["status"]:
                failures.append(dict(recording_id=rid, round=rounds.get(rid), code="RUN_STATUS_CHANGED_AFTER_BINDING",
                                     analysis_run_id=path.parent.name))
    return dict(passed=not failures, failures=failures)


# ---------------------------------------------------------------- report
def attempt_rows(state):
    rows = []
    for key in sorted(state.attempts, key=lambda k: (int(k[0]), k[1])):
        a = state.attempts[key]
        lock = a.locked or {}
        rows.append(dict(round=a.round, attempt_index=a.attempt_index, slot_kind=a.slot.kind,
                         recording_id=a.recording_id, stage=lock.get("stage"), reason_code=lock.get("reason_code"),
                         acquisition_valid=lock.get("acquisition_valid"), retry_allowed=lock.get("retry_allowed"),
                         rule_id=lock.get("rule_id"), operator_declaration=lock.get("operator_declaration"),
                         ended=a.ended is not None, outcome=(a.outcome or {}).get("outcome"),
                         outcome_reason=(a.outcome or {}).get("reason_code"), canonical=a.canonical()))
    return rows


def outcome_consistency(root, state):
    """Re-derive every recorded production outcome from evidence; any mismatch is FAIL."""
    mismatches = []
    for attempt in state.attempts.values():
        if attempt.outcome is None:
            continue
        derived = attempt_outcome_from_evidence(root, state, attempt)
        if (derived["outcome"], derived["reason_code"]) != (attempt.outcome["outcome"], attempt.outcome["reason_code"]):
            mismatches.append(dict(round=attempt.round, attempt_index=attempt.attempt_index,
                                   recorded=attempt.outcome["outcome"], derived=derived["outcome"]))
    return dict(passed=not mismatches, mismatches=mismatches)


def evaluate_execution(root, ledger_path, deprojector_factory=None):
    root = Path(root)
    events, state = ledger.verify_ledger(ledger_path)
    open_attempt = state.open_attempt()
    takes = evaluate_static_takes(root, state, deprojector_factory)
    grid = metrics.evaluate_static_grid(takes)
    forward = {r: evaluate_production_slot(root, state, r) for r in ("101", "102", "103", "111", "112", "113")}
    body_only = evaluate_production_slot(root, state, "121")
    recordings = reconcile_recordings(root, state)
    analyses = reconcile_analyses(root, state, recordings["created"])
    e2e = evaluate_slot131(root, state, recordings, analyses)
    consistency = outcome_consistency(root, state)
    static_sessions = [s for s in state.sessions.values() if s["kind"] == p8.SESSION_KINDS[p8.STATIC]
                       and s["setup_pose"] is not None]
    conditions = dict(
        ledger_verified=True, no_open_attempt=open_attempt is None,
        execution_not_failed=state.execution_failure is None,
        model_identity=state.model_verified, pre_hardware_integrity=state.pre_hardware_integrity,
        camera_pose_recheck=bool(static_sessions) and all(s["recheck"] and not s.get("material_change")
                                                          for s in static_sessions),
        J_all_static_points_executed=grid["all_points_executed"],
        K_three_canonical_takes_per_point=all(p["checks"]["three_canonical_takes"] for p in grid["points"].values()),
        L_anchor_0_70=grid["points"][0.70]["passed"], M_anchor_0_80=grid["points"][0.80]["passed"],
        N_static_envelope_derived=grid["envelope_m"] is not None,
        P_forward_slots_101_103=all(forward[r]["passed"] for r in ("101", "102", "103")),
        Q_forward_slots_111_113=all(forward[r]["passed"] for r in ("111", "112", "113")),
        R_body_only_121=body_only["passed"], S_slot_131=e2e["passed"],
        U_recording_reconciliation=recordings["passed"], V_analysis_reconciliation=analyses["passed"],
        X_closure_integrity=state.closure_integrity is True,
        outcome_consistency=consistency["passed"],
    )
    passed = all(conditions.values())
    metrics_report = dict(execution_id=state.execution_id, static_takes=takes, static_grid=grid,
                          forward_slots=forward, body_only_negative=body_only, slot_131=e2e)
    reconciliation_report = dict(execution_id=state.execution_id, recording=recordings, analysis=analyses,
                                 outcome_consistency=consistency)
    execution_report = dict(
        execution_id=state.execution_id, ledger_format_version=p8.LEDGER_FORMAT_VERSION,
        ledger=dict(event_count=len(events), last_event_sha256=events[-1]["event_sha256"] if events else None,
                    sha256=hashlib.sha256(Path(ledger_path).read_bytes()).hexdigest()),
        attempts=attempt_rows(state), static_envelope_m=grid["envelope_m"],
        range_validation_passed=grid["range_validation_passed"],
        formal_initial_seating_range_m=list(p8.FORMAL_INITIAL_SEATING_RANGE_M) if passed else None,
        computed_conditions=conditions, external_conditions={k: "EXTERNAL_RECORD_REQUIRED" for k in EXTERNAL_CONDITIONS},
        computed_result="PASS" if passed else "FAIL",
        execution_failure=state.execution_failure)
    return dict(metrics=metrics_report, reconciliation=reconciliation_report, execution=execution_report)


def report_bytes(value):
    return (json.dumps(ledger.json_safe(_keys_to_text(value)), sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def _keys_to_text(value):
    if isinstance(value, dict):
        return {(f"{k:.2f}" if isinstance(k, float) else str(k)): _keys_to_text(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_keys_to_text(v) for v in value]
    return value
