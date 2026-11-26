"""Patch 8 deterministic validation metrics (CAP-005 §55–§81); pure functions only.

Inputs are canonical `frames-schema/1.0.0` rows as parsed by analyze_d455.load_frames_csv
(booleans as True/False/None, numbers as float/None) and post-lock production evidence.
Quantity lists, masks, windows and thresholds come from patch8_protocol and are applied
exactly: no pooling across series, takes, phases, recordings or distances; no outlier
removal; no additional filtering. The 3D quantities are Patch 8 validation-only and do
not define F2 / OPEN-003 (§65, §88).
"""
import math
import statistics

import patch8_protocol as p8


class CalibrationError(ValueError):
    pass


# ---------------------------------------------------------------- primitives
def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def positive(value):
    value = number(value)
    return value is not None and value > 0


def rate(count, denominator):
    return None if denominator == 0 else count / denominator


def at_least(value, minimum):
    return value is not None and value >= minimum


def _true(row, *fields):
    return all(row.get(field) is True for field in fields)


def head_depth_valid(row):
    """§58 / §60 / §62 / §63 face depth validity (bbox ROI only; oval fallback excluded)."""
    return _true(row, "face_detected", "face_depth_valid") and row.get("face_depth_source") == p8.FACE_DEPTH_SOURCE_REQUIRED


POINTS = (("lsh", "lsh_valid", "lsh_depth_valid"), ("rsh", "rsh_valid", "rsh_depth_valid"),
          ("left_hip", "left_hip_valid", "left_hip_depth_valid"),
          ("right_hip", "right_hip_valid", "right_hip_depth_valid"))


def complete_rgbd(row):
    """§60 complete RGB-D geometry mask."""
    return (_true(row, "face_detected", "face_mesh_detected", "pose_detected") and head_depth_valid(row) and
            all(_true(row, valid, depth) for _, valid, depth in POINTS))


# §62 exact series validity masks (value finiteness/positivity applied in depth_series_values).
DEPTH_SERIES_MASKS = {
    "z_face_m": head_depth_valid,
    "z_lsh_m": lambda r: _true(r, "lsh_valid", "lsh_depth_valid"),
    "z_rsh_m": lambda r: _true(r, "rsh_valid", "rsh_depth_valid"),
    "left_hip_depth_m": lambda r: _true(r, "left_hip_valid", "left_hip_depth_valid"),
    "right_hip_depth_m": lambda r: _true(r, "right_hip_valid", "right_hip_depth_valid"),
}
assert tuple(DEPTH_SERIES_MASKS) == p8.DEPTH_SERIES


# ---------------------------------------------------------------- windows (§55, §75.1)
def static_window(rows):
    return [r for r in rows if number(r.get("t")) is not None and
            p8.STATIC_WINDOW_START_S <= r["t"] < p8.STATIC_WINDOW_END_S]


def forward_window(rows, label, phase_duration_s):
    return [r for r in rows if r.get("label") == label and number(r.get("t")) is not None and
            p8.FORWARD_TRIM_START_S < r["t"] < phase_duration_s - p8.FORWARD_TRIM_END_S]


def coverage(n):
    value = n / p8.EXPECTED_FRAME_DENOMINATOR
    return dict(n=n, ratio=value, passed=value >= p8.FRAME_COVERAGE_MIN)


def availability_rates(rows):
    """§57–§60 / §75.3 rates over one window; zero denominators yield None (not evaluable)."""
    n = len(rows)
    face = sum(_true(r, "face_detected") for r in rows)
    rates = dict(
        face_detection_rate=rate(face, n),
        face_mesh_rate=rate(sum(_true(r, "face_mesh_detected") for r in rows), n),
        pose_detection_rate=rate(sum(_true(r, "pose_detected") for r in rows), n),
        bilateral_shoulder_inframe_rate=rate(sum(_true(r, "lsh_valid", "rsh_valid") for r in rows), n),
        bilateral_hip_inframe_rate=rate(sum(_true(r, "left_hip_valid", "right_hip_valid") for r in rows), n),
        head_depth_valid_rate=rate(sum(head_depth_valid(r) for r in rows), face),
        complete_rgbd_rate=rate(sum(complete_rgbd(r) for r in rows), n),
    )
    for name, valid, depth in POINTS:
        rates[f"{name}_depth_valid_rate"] = rate(sum(_true(r, valid, depth) for r in rows),
                                                 sum(_true(r, valid) for r in rows))
    return rates


STATIC_LANDMARK_RATES = ("face_detection_rate", "face_mesh_rate", "pose_detection_rate",
                         "bilateral_shoulder_inframe_rate", "bilateral_hip_inframe_rate")
CONDITIONAL_DEPTH_RATES = ("head_depth_valid_rate", "lsh_depth_valid_rate", "rsh_depth_valid_rate",
                           "left_hip_depth_valid_rate", "right_hip_depth_valid_rate")
FORWARD_LANDMARK_RATES = ("face_detection_rate", "face_mesh_rate", "pose_detection_rate")


# ---------------------------------------------------------------- §62 depth temporal SD
def depth_series_values(rows, field):
    """Frozen-window rows INTERSECT the exact series mask; nothing else is filtered."""
    mask = DEPTH_SERIES_MASKS[field]
    return [r[field] for r in rows if mask(r) and positive(r.get(field))]


def depth_temporal_sd(rows):
    result = {}
    for field in p8.DEPTH_SERIES:
        values = depth_series_values(rows, field)
        evaluable = len(values) >= p8.MIN_VALID_N
        sd_mm = statistics.stdev(values) * 1000 if evaluable else None   # ddof = 1
        result[field] = dict(n=len(values), evaluable=evaluable, temporal_depth_sd_mm=sd_mm,
                             passed=evaluable and sd_mm <= p8.DEPTH_TEMPORAL_SD_MAX_MM)
    return result


# ---------------------------------------------------------------- §63 IPD
def ipd_values(rows):
    return [r["ipd_cm"] for r in rows if positive(r.get("ipd_cm")) and head_depth_valid(r)]


def ipd_metric(rows):
    values = ipd_values(rows)
    evaluable = len(values) >= p8.MIN_VALID_N
    return dict(n=len(values), evaluable=evaluable, median=statistics.median(values) if evaluable else None)


# ---------------------------------------------------------------- §64 SDK deprojection / calibration
CALIBRATION_KEYS = ("width", "height", "fx", "fy", "ppx", "ppy", "model", "coeffs")


def distortion_model(text, rs):
    """Exact `distortion.<member>` round trip to the SDK enum; anything else fails closed."""
    if not isinstance(text, str) or not text.startswith("distortion."):
        raise CalibrationError(f"unrecognized distortion model: {text!r}")
    member = getattr(rs.distortion, text[len("distortion."):], None)
    if member is None or str(member) != text:
        raise CalibrationError(f"distortion model does not round-trip to the SDK enum: {text!r}")
    return member


def calibration_check(playback, capture):
    """Color intrinsics used for deprojection must be complete, 1280x720 (§8), and identical
    between analysis playback calibration and capture metadata; depth scale likewise."""
    failures = []
    intrinsics = (playback or {}).get("color_intrinsics") if isinstance(playback, dict) else None
    if not isinstance(intrinsics, dict) or set(intrinsics) != set(CALIBRATION_KEYS):
        return dict(passed=False, failures=["playback color intrinsics missing or incomplete"])
    if (intrinsics["width"], intrinsics["height"]) != (1280, 720):
        failures.append("color intrinsics resolution is not 1280x720")
    if not all(positive(intrinsics[k]) for k in ("fx", "fy")) or not all(
            number(intrinsics[k]) is not None for k in ("ppx", "ppy")):
        failures.append("non-finite or non-positive focal/principal values")
    coeffs = intrinsics["coeffs"]
    if not isinstance(coeffs, list) or len(coeffs) != 5 or not all(number(c) is not None for c in coeffs):
        failures.append("distortion coefficients must be five finite numbers")
    captured = (capture or {}).get("color_intrinsics") if isinstance(capture, dict) else None
    if not isinstance(captured, dict) or any(captured.get(k) != intrinsics[k] for k in CALIBRATION_KEYS):
        failures.append("capture and playback color intrinsics differ")
    if not positive(playback.get("depth_scale_m")) or (capture or {}).get("depth_scale_m") != playback.get("depth_scale_m"):
        failures.append("capture and playback depth scale differ or are invalid")
    return dict(passed=not failures, failures=failures)


def sdk_deprojector(color_intrinsics, rs=None):
    """P = SDK deproject(color intrinsics, pixel, aligned depth) (§64)."""
    if rs is None:
        import pyrealsense2 as rs
    intrinsics = rs.intrinsics()
    for key in ("width", "height"):
        setattr(intrinsics, key, int(color_intrinsics[key]))
    for key in ("fx", "fy", "ppx", "ppy"):
        setattr(intrinsics, key, float(color_intrinsics[key]))
    intrinsics.model = distortion_model(color_intrinsics["model"], rs)
    intrinsics.coeffs = [float(c) for c in color_intrinsics["coeffs"]]
    return lambda x, y, depth: tuple(rs.rs2_deproject_pixel_to_point(intrinsics, [float(x), float(y)], float(depth)))


# ---------------------------------------------------------------- §65–§67 validation-only 3D geometry
def _point(row, prefix, deproject):
    x, y, z = (row.get(prefix + "_x"), row.get(prefix + "_y"), row.get("z_" + prefix + "_m")) if prefix in ("lsh", "rsh") \
        else (row.get(prefix + "_x_px"), row.get(prefix + "_y_px"), row.get(prefix + "_depth_m"))
    if number(x) is None or number(y) is None or not positive(z):
        return None
    point = deproject(x, y, z)
    return point if len(point) == 3 and all(number(c) is not None for c in point) else None


def _distance(a, b):
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


def row_geometry(row, deproject):
    points = {}
    for name, valid, depth in POINTS:   # §64 eligibility: *_valid && *_depth_valid
        if _true(row, valid, depth):
            points[name] = _point(row, name, deproject)
    out = {}
    if points.get("lsh") and points.get("rsh"):
        out["shoulder_width_3d"] = _distance(points["lsh"], points["rsh"])
    if points.get("left_hip") and points.get("right_hip"):
        out["hip_width_3d"] = _distance(points["left_hip"], points["right_hip"])
    if "shoulder_width_3d" in out and "hip_width_3d" in out:
        mid_sh = [(a + b) / 2 for a, b in zip(points["lsh"], points["rsh"])]
        mid_hip = [(a + b) / 2 for a, b in zip(points["left_hip"], points["right_hip"])]
        out["trunk_length_3d"] = _distance(mid_sh, mid_hip)
    return out


def geometry_metrics(rows, deproject):
    samples = {q: [] for q in p8.WITHIN_TAKE_CV_QUANTITIES}
    if deproject is not None:
        for row in rows:
            for quantity, value in row_geometry(row, deproject).items():
                if positive(value):   # §66 finite && > 0
                    samples[quantity].append(value)
    result = {}
    for quantity in p8.WITHIN_TAKE_CV_QUANTITIES:
        values = samples[quantity]
        evaluable = len(values) >= p8.MIN_VALID_N
        median = statistics.median(values) if evaluable else None
        cv = statistics.stdev(values) / median if evaluable and median > 0 else None
        result[quantity] = dict(n=len(values), evaluable=evaluable, median=median, within_take_cv=cv,
                                within_take_cv_passed=cv is not None and cv <= p8.WITHIN_TAKE_CV_MAX)
    return result


# ---------------------------------------------------------------- static take (§55–§67)
def evaluate_static_take(rows, *, deproject, calibration):
    labels = {r.get("label") for r in rows}
    steps = {r.get("step") for r in rows}
    structure = labels == {p8.STATIC_MARKER_LABEL} and len(steps) == 1
    window = static_window(rows) if structure else []
    rates = availability_rates(window)
    cover = coverage(len(window))
    depth = depth_temporal_sd(window)
    ipd = ipd_metric(window)
    geometry = geometry_metrics(window, deproject if calibration.get("passed") else None)
    checks = dict(
        structure=structure,
        frame_coverage=cover["passed"],
        landmark_acquisition=all(at_least(rates[k], p8.LANDMARK_RATE_MIN) for k in STATIC_LANDMARK_RATES),
        conditional_depth=all(at_least(rates[k], p8.CONDITIONAL_DEPTH_RATE_MIN) for k in CONDITIONAL_DEPTH_RATES),
        complete_rgbd=at_least(rates["complete_rgbd_rate"], p8.COMPLETE_RGBD_RATE_MIN),
        depth_temporal_sd=all(depth[k]["passed"] for k in p8.DEPTH_SERIES),
        ipd_evaluable=ipd["evaluable"],
        calibration=bool(calibration.get("passed")),
        within_take_cv=all(geometry[q]["within_take_cv_passed"] for q in p8.WITHIN_TAKE_CV_QUANTITIES),
    )
    medians = dict(ipd_cm=ipd["median"], **{q: geometry[q]["median"] for q in p8.WITHIN_TAKE_CV_QUANTITIES})
    return dict(canonical=True, evaluated=True, fail_reason=None, coverage=cover, rates=rates, depth_series=depth, ipd=ipd,
                geometry=geometry, calibration=calibration, checks=checks, take_medians=medians,
                take_passed=all(checks.values()))


def unevaluated_take(reason, *, canonical=False):
    """A slot with no canonical take (canonical=False) or a canonical take that is FAIL evidence
    without metrics (e.g. MANUAL_ABORT, missing/non-conforming canonical analysis)."""
    return dict(canonical=canonical, evaluated=False, fail_reason=reason, take_passed=False, checks={},
                take_medians={q: None for q in p8.DISTANCE_STABILITY_QUANTITIES})


# ---------------------------------------------------------------- §68–§73 static point / envelope
def between_take_spread(medians):
    if len(medians) != p8.STATIC_REPETITIONS or not all(positive(m) for m in medians):
        return None
    return (max(medians) - min(medians)) / statistics.median(medians)


def evaluate_static_grid(takes):
    """`takes` maps every static round to a take result (or unevaluated_take)."""
    by_distance = {d: [takes.get(r) or unevaluated_take("NOT_EXECUTED") for r in p8.static_rounds_at(d)]
                   for d in p8.STATIC_GRID_M}
    anchor_takes = [t for d in p8.MANDATORY_ANCHORS_M for t in by_distance[d]]
    anchors = {}
    for quantity in p8.DISTANCE_STABILITY_QUANTITIES:
        values = [t["take_medians"].get(quantity) for t in anchor_takes]
        anchor = statistics.median(values) if len(values) == 6 and all(positive(v) for v in values) else None
        anchors[quantity] = anchor if positive(anchor) else None
    points = {}
    for distance, point_takes in by_distance.items():
        spreads, stability = {}, {}
        for quantity in p8.BETWEEN_TAKE_SPREAD_QUANTITIES:
            spread = between_take_spread([t["take_medians"].get(quantity) for t in point_takes])
            spreads[quantity] = dict(value=spread, passed=spread is not None and spread <= p8.BETWEEN_TAKE_SPREAD_MAX)
        for quantity in p8.DISTANCE_STABILITY_QUANTITIES:
            medians = [t["take_medians"].get(quantity) for t in point_takes]
            distance_median = statistics.median(medians) if all(positive(m) for m in medians) else None
            anchor = anchors[quantity]
            value = abs(distance_median - anchor) / anchor if distance_median is not None and anchor is not None else None
            stability[quantity] = dict(distance_median=distance_median, anchor=anchor, value=value,
                                       passed=value is not None and value <= p8.DISTANCE_STABILITY_MAX)
        executed = all(t["fail_reason"] != "NOT_EXECUTED" for t in point_takes)
        checks = dict(three_canonical_takes=all(t["canonical"] for t in point_takes),
                      every_take_passed=all(t["take_passed"] for t in point_takes),
                      between_take_spread=all(s["passed"] for s in spreads.values()),
                      distance_stability=all(s["passed"] for s in stability.values()))
        points[distance] = dict(executed=executed, checks=checks, between_take_spread=spreads,
                                distance_stability=stability, passed=all(checks.values()))
    passed = {d: points[d]["passed"] for d in p8.STATIC_GRID_M}
    envelope, range_valid = static_envelope(passed)
    return dict(points=points, anchors=anchors, envelope_m=envelope, range_validation_passed=range_valid,
                all_points_executed=all(points[d]["executed"] for d in p8.STATIC_GRID_M))


def static_envelope(point_passed):
    """§72/§73: both anchors PASS → maximal contiguous PASS interval containing both; else NONE."""
    if not all(point_passed.get(a) is True for a in p8.MANDATORY_ANCHORS_M):
        return None, False
    grid = list(p8.STATIC_GRID_M)
    low, high = grid.index(p8.MANDATORY_ANCHORS_M[0]), grid.index(p8.MANDATORY_ANCHORS_M[-1])
    if not all(point_passed.get(d) is True for d in grid[low:high + 1]):
        return None, False
    while low > 0 and point_passed.get(grid[low - 1]) is True:
        low -= 1
    while high < len(grid) - 1 and point_passed.get(grid[high + 1]) is True:
        high += 1
    return (grid[low], grid[high]), True


# ---------------------------------------------------------------- §75 forward availability
def evaluate_forward_availability(rows, label, phase_duration_s):
    steps = {r.get("step") for r in rows if r.get("label") == label}
    structure = len(steps) == 1 and phase_duration_s == p8.FORWARD_PHASE_DURATION_S
    window = forward_window(rows, label, phase_duration_s) if structure else []
    rates = availability_rates(window)
    cover = coverage(len(window))
    checks = dict(structure=structure, coverage=cover["passed"],
                  **{k: at_least(rates[k], p8.LANDMARK_RATE_MIN) for k in FORWARD_LANDMARK_RATES},
                  **{k: at_least(rates[k], p8.CONDITIONAL_DEPTH_RATE_MIN) for k in CONDITIONAL_DEPTH_RATES},
                  complete_rgbd=at_least(rates["complete_rgbd_rate"], p8.COMPLETE_RGBD_RATE_MIN))
    return dict(label=label, phase_duration_s=phase_duration_s, coverage=cover, rates=rates, checks=checks,
                passed=all(checks.values()))


# ---------------------------------------------------------------- §76–§79 production gate evidence
def production_gate_status(closer):
    """Read-only mirror of capture_d455.evaluate_forward_distance (tested for equality)."""
    if closer < p8.FORWARD_GATE_MIN_M and not math.isclose(closer, p8.FORWARD_GATE_MIN_M, rel_tol=0,
                                                            abs_tol=p8.FORWARD_GATE_ABS_TOL):
        return "too_little"
    if closer > p8.FORWARD_GATE_MAX_M and not math.isclose(closer, p8.FORWARD_GATE_MAX_M, rel_tol=0,
                                                            abs_tol=p8.FORWARD_GATE_ABS_TOL):
        return "too_much"
    return "ok"


GATE_EVIDENCE_KEYS = ("label", "phase_idx", "reference_phase_idx", "reference_face_median_m",
                      "current_face_median_m", "closer_m", "forward_target_min_m", "forward_target_max_m",
                      "forward_validation_source", "forward_gate_result", "forward_gate_reasons")


def gate_evidence_consistent(entry):
    """The recorded result must be exactly what the face-only production gate yields."""
    if not isinstance(entry, dict) or not all(k in entry for k in GATE_EVIDENCE_KEYS):
        return False
    if (entry["forward_validation_source"] != p8.FORWARD_VALIDATION_SOURCE or
            entry["forward_target_min_m"] != p8.FORWARD_GATE_MIN_M or
            entry["forward_target_max_m"] != p8.FORWARD_GATE_MAX_M):
        return False
    ref, cur, closer = entry["reference_face_median_m"], entry["current_face_median_m"], entry["closer_m"]
    if closer is None:
        expected = []
        if ref is None:
            expected.append("insufficient_reference_face_samples" if entry["reference_phase_idx"] is not None
                            else "missing_reference")
        if cur is None:
            expected.append("insufficient_current_face_samples")
        return bool(expected) and entry["forward_gate_result"] == "fail" and entry["forward_gate_reasons"] == expected
    if number(ref) is None or number(cur) is None or number(closer) is None or closer != ref - cur:
        return False
    status = production_gate_status(closer)
    expected = {"ok": [], "too_little": ["below_target"], "too_much": ["above_target"]}[status]
    return (entry["forward_gate_result"] == ("pass" if status == "ok" else "fail") and
            entry["forward_gate_reasons"] == expected)


def guide_skipped(capture):
    start = (capture or {}).get("start_distance") if isinstance(capture, dict) else None
    return isinstance(start, dict) and str(start.get("mode", "")).endswith("_skipped")


def _outcome(outcome, reason, **evidence):
    return dict(outcome=outcome, reason_code=reason, evidence=evidence)


def _designated_entry(quality, label):
    entries = [e for e in (quality or {}).get("forward_gate_evidence") or [] if isinstance(e, dict)
               and e.get("label") == label]
    return entries[0] if len(entries) == 1 else None


def forward_attempt_outcome(lock_reason, capture, quality, slot):
    """§79 post-lock disposition of one acquisition-valid forward-slot attempt."""
    label = slot.designated_phases[0]
    if lock_reason is not None:
        return _outcome(p8.CANONICAL, lock_reason)
    if guide_skipped(capture):
        return _outcome(p8.CANONICAL, p8.GUIDE_NOT_SATISFIED)
    if not isinstance(quality, dict):
        return _outcome(p8.CANONICAL, "NO_QUALITY_EVIDENCE")
    entry = _designated_entry(quality, label)
    if entry is None:
        return _outcome(p8.CANONICAL, "NO_GATE_EVIDENCE")
    if entry.get("closer_m") is None:
        return _outcome(p8.CANONICAL, "CLOSER_NULL")
    if not gate_evidence_consistent(entry):
        return _outcome(p8.CANONICAL, "EVIDENCE_INCONSISTENT")
    low, high = p8.FORWARD_BANDS_M[slot.band]
    closer = entry["closer_m"]
    details = dict(label=label, band=slot.band, closer_m=closer, forward_gate_result=entry["forward_gate_result"],
                   forward_gate_reasons=entry["forward_gate_reasons"])
    if low <= closer <= high:
        expected = p8.FORWARD_GATE_REASON_BY_BAND[slot.band]
        class_gate = (entry["forward_gate_result"] == ("pass" if not expected else "fail") and
                      entry["forward_gate_reasons"] == expected)
        return _outcome(p8.CANONICAL, None if class_gate else "EVIDENCE_INCONSISTENT", in_band=True,
                        class_gate_passed=class_gate, **details)
    return _outcome(p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS, in_band=False, **details)


# ---------------------------------------------------------------- §80 body-only negative
def body_samples(samples, entry, phase_duration_s):
    """samples.csv rows: mode == body, distance_m non-null, inside the frozen phase window."""
    found = []
    for row in samples or []:
        try:
            same_phase = (int(row.get("phase_idx")) == entry["phase_idx"] and row.get("phase") == "hold" and
                          row.get("label") == "body_forward")
            t = float(row.get("t"))
            distance = row.get("distance_m")
            value = float(distance) if distance not in (None, "", "None") else None
        except (TypeError, ValueError):
            continue
        if (same_phase and row.get("mode") == "body" and number(value) is not None and
                p8.FORWARD_TRIM_START_S < t < phase_duration_s - p8.FORWARD_TRIM_END_S):
            found.append(row)
    return found


def body_only_attempt_outcome(lock_reason, capture, quality, samples, phase_duration_s):
    if lock_reason is not None:
        return _outcome(p8.CANONICAL, lock_reason)
    if guide_skipped(capture):
        return _outcome(p8.CANONICAL, p8.GUIDE_NOT_SATISFIED)
    if not isinstance(quality, dict):
        return _outcome(p8.CANONICAL, "NO_QUALITY_EVIDENCE")
    entry = _designated_entry(quality, "body_forward")
    if entry is None or not all(k in entry for k in GATE_EVIDENCE_KEYS):
        return _outcome(p8.CANONICAL, "NO_GATE_EVIDENCE")
    if phase_duration_s != p8.FORWARD_PHASE_DURATION_S:
        return _outcome(p8.CANONICAL, "EVIDENCE_INCONSISTENT", phase_duration_s=phase_duration_s)
    if entry["reference_face_median_m"] is None:
        return _outcome(p8.CANONICAL, "REFERENCE_FACE_INSUFFICIENT")
    if entry["current_face_median_m"] is not None:
        return _outcome(p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS, current_face_sufficient=True)
    bodies = body_samples(samples, entry, phase_duration_s)
    if not bodies:
        return _outcome(p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS, current_face_sufficient=False, body_samples=0)
    details = dict(body_samples=len(bodies), closer_m=entry["closer_m"],
                   forward_gate_result=entry["forward_gate_result"], forward_gate_reasons=entry["forward_gate_reasons"])
    if entry["forward_gate_result"] == "pass":
        return _outcome(p8.CANONICAL, "GATE_PASSED_ON_BODY_ONLY_TARGET", **details)
    if (entry["closer_m"] is not None or entry["forward_gate_reasons"] != p8.BODY_ONLY_REQUIRED_REASONS or
            not gate_evidence_consistent(entry)):
        return _outcome(p8.CANONICAL, "EVIDENCE_INCONSISTENT", **details)
    return _outcome(p8.CANONICAL, None, target_achieved=True, **details)


# ---------------------------------------------------------------- §81 slot 131 / analysis predicate
def canonical_analysis_predicate(manifest, batch):
    """§52/§53/§81.4 exact predicate on the first completed (canonical) analysis run."""
    if not isinstance(manifest, dict) or not isinstance(batch, dict):
        return dict(passed=False, checks=dict(present=False))
    run = manifest.get("analysis_run_id")
    checks = dict(
        analysis_mode=manifest.get("analysis_mode") == "extract_raw",
        status=manifest.get("status") == "completed",
        step_effective=(manifest.get("options") or {}).get("step_effective") == 1,
        one_recording_per_invocation=(batch.get("analysis_run_ids") == [run] and
                                      isinstance(batch.get("run_manifests"), list) and
                                      len(batch["run_manifests"]) == 1),
    )
    return dict(passed=all(checks.values()), checks=checks)


def e2e_gate_pass(quality, label):
    entry = _designated_entry(quality, label)
    return (entry is not None and gate_evidence_consistent(entry) and entry["forward_gate_result"] == "pass" and
            entry["forward_validation_source"] == p8.FORWARD_VALIDATION_SOURCE)


def slot131_predicate(*, canonical_exists, quality, availability, analysis, lineage, recording_reconciled,
                      analysis_reconciled):
    """§81.8 exact conjunction; any false component is slot-131 FAIL."""
    components = dict(
        canonical_acquisition_valid_recording=bool(canonical_exists),
        capture_verdict_ok=isinstance(quality, dict) and quality.get("verdict") == "ok",
        forward_head_availability=bool((availability.get("forward_head") or {}).get("passed")),
        body_forward_availability=bool((availability.get("body_forward") or {}).get("passed")),
        forward_head_production_gate=isinstance(quality, dict) and e2e_gate_pass(quality, "forward_head"),
        body_forward_production_gate=isinstance(quality, dict) and e2e_gate_pass(quality, "body_forward"),
        canonical_analysis=bool((analysis or {}).get("passed")),
        artifact_lineage=bool((lineage or {}).get("passed")),
        recording_reconciliation=bool(recording_reconciled),
        analysis_reconciliation=bool(analysis_reconciled),
    )
    return dict(passed=all(components.values()), components=components)
