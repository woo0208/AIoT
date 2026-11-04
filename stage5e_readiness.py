"""Offline 5-E-3 plan/metadata adapter. Never opens a camera or participant data.

Hold durations are explicit operator inputs, not a new research default. The
P0..P5 cycle order implements this task's requested order; execution still needs
the approved SOP/IRB. Existing capture.record_phase accepts each returned seq.
"""

import csv
from pathlib import Path

import capture_d455 as capture
from f0_fcal_native import REQUEST_INTERFACE
from rf_experiment import file_identity, read_pinned_json


CAPTURE_LABELS = ("upright", "forward_head", "lean_back", "lean_left", "lean_right", "body_forward")


def development_plan(subjects, hold_seconds):
    """Five full cycles/person, S1=1..3 and S2=4..5; no implicit hold duration."""
    import math
    subjects, durations = tuple(subjects), tuple(hold_seconds)
    if len(subjects) != 2 or len(set(subjects)) != 2:
        raise ValueError("exactly two distinct development subjects required")
    if len(durations) != 6 or any(isinstance(t, bool) or not isinstance(t, (int, float))
                                or not math.isfinite(t) or t < 10 for t in durations):
        raise ValueError("six explicit finite hold durations >=10 seconds required")
    takes = []
    for subject in subjects:
        capture.validate_capture_identity(subject, "1", "formal")
        for repeat in range(1, 6):
            takes.append(dict(subject=subject, round=str(repeat),
                session="S1" if repeat <= 3 else "S2", repeat=repeat,
                sequence=list(zip(CAPTURE_LABELS, durations)),
                orders=list(range((repeat-1)*6, repeat*6))))
    return tuple(takes)


def native_request(plan, captures):
    """Bind explicit capture files to a reviewed plan, without replay or writes.

    captures is a (subject, round) -> {raw, capture, markers, analysis_run_id}
    map. Only those paths are read. No directory scan or held-out loader exists.
    The existing native generator subsequently verifies hashes, marker clocks,
    native EOF and frame bindings. This is not a collection authorization.
    """
    plan = tuple(plan)
    subjects = tuple(dict.fromkeys(t["subject"] for t in plan))
    # Reconstruct to reject missing/reordered/altered cycles or reference order.
    if not plan or plan != development_plan(subjects, [v for _, v in plan[0]["sequence"]]):
        raise ValueError("plan must contain the complete ordered development schedule")
    expected = {(t["subject"], t["round"]) for t in plan}
    if set(captures) != expected:
        raise ValueError("capture map must match only the two-person planned takes")
    recordings, refs, used_runs, used_recordings = [], {}, set(), set()
    for take in plan:
        spec = captures[take["subject"], take["round"]]
        paths = {k: Path(spec[k]).resolve() for k in ("raw", "capture", "markers")}
        camera, identity = read_pinned_json(paths["capture"])
        rid, run = camera.get("recording_id"), spec["analysis_run_id"]
        if (rid in used_recordings or run in used_runs or not isinstance(run, str)
                or not run.startswith("ar_")):
            raise ValueError("duplicate recording/run or invalid analysis run")
        used_recordings.add(rid)
        used_runs.add(run)
        if (camera.get("subject") != take["subject"] or str(camera.get("round")) != take["round"]
                or camera.get("dataset_role") != "formal"
                or paths["raw"].stem != rid or camera.get("record_file") != paths["raw"].name
                or paths["capture"] != paths["raw"].with_name(rid + "_camera.json")
                or paths["markers"] != paths["raw"].with_name(rid + "_markers.csv")
                or camera.get("capture_script_sha256") != file_identity(capture.__file__)["sha256"]
                or camera.get("sequence") != [list(p) for p in take["sequence"]]
                or camera.get("prep_sec") != capture.PREP_SEC):
            raise ValueError("capture identity/producer/sequence differs from plan")
        with paths["markers"].open(encoding="utf-8-sig", newline="") as stream:
            marks = list(csv.DictReader(stream))
        # record_phase writes prep,hold pairs and a final normal end marker.
        if len(marks) != 13 or any(m.get("recording_id") != rid for m in marks):
            raise ValueError("complete six-hold marker sequence required")
        segments = []
        for i, (label, _) in enumerate(take["sequence"]):
            prep, hold = marks[2*i:2*i+2]
            if (prep.get("phase"), prep.get("label"), prep.get("step"),
                hold.get("phase"), hold.get("label"), hold.get("step")) != (
                    "prep", "transition", str(i+1), "hold", label, str(i+1)):
                raise ValueError("marker order/label differs from plan")
            segments.append(dict(session=take["session"], order=take["orders"][i],
                step=i+1, label=label, hold_start_marker_index=2*i+1,
                hold_end_marker_index=2*i+2))
        if marks[-1].get("phase") != "end" or marks[-1].get("label") != "end":
            raise ValueError("normal end required; interrupted takes remain excluded")
        if take["repeat"] == 1:
            refs[take["subject"]] = [run, rid, 1]
        recordings.append(dict(subject=take["subject"], round=take["round"], recording_id=rid,
            analysis_run_id=run, segments=segments,
            sources={**{k: file_identity(v) for k, v in paths.items()}, "capture": identity}))
    return dict(interface=REQUEST_INTERFACE, recordings=recordings, reference_keys=refs,
                participant_splits={s: "train" for s in subjects})
