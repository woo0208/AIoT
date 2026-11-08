"""Manual NON-FORMAL six-posture pilot: 10 holds per posture, 10 seconds each.

python -X utf8 -B capture_six_pilot.py --subject P01 --repeats 10 --hold-seconds 10
P01 P5-only supplement: add --p5-supplement (7 holds, linked to the reviewed failures).
No production capture gate, canonical schema, model or formal protocol is changed.
The camera keeps running while paused; only completed holds enter features.csv.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid

LABELS = ("upright", "forward_head", "lean_back", "lean_left", "lean_right", "lean_forward")
NAMES = ("정상", "거북목", "상체 후방", "상체 좌측", "상체 우측", "상체 전방")
KEYS = {"space": LABELS[0], "h": LABELS[1], "Down": LABELS[2],
        "Left": LABELS[3], "Right": LABELS[4], "Up": LABELS[5]}
KEY_TEXT = ("Space", "H", "↓", "←", "→", "↑")


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def load_p5_supplement_binding(review_path=None, root=None):
    """Bind the requested seven holds to reviewed technical failures, not predictions."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    review_path = Path(review_path) if review_path is not None else root / "analysis/PILOT_SIX_CAPTURE_REVIEW_20261106/local_private/results.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    missing = [s for s in review["samples"] if s["subject"] == "P01"
               and s["label"] == "lean_forward" and not s["eligible"]]
    if len(missing) != 7 or len({s["sample_key"][1] for s in missing}) != 1:
        raise ValueError("Expected exactly seven reviewed P01 P5 failures in one source recording")
    segment_ids = sorted((int(s["sample_key"][2]) for s in missing))
    if len(set(segment_ids)) != 7:
        raise ValueError("Duplicate original segment identities")
    recording_id = missing[0]["sample_key"][1]
    source_dir = root / "captures" / recording_id
    # Identity comes from the saved review, never newest/mtime or prediction scores.
    if source_dir.resolve().parent != (root / "captures").resolve():
        raise ValueError("Original recording outside captures")
    summary_path = source_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (summary["scope"] != "EXPLORATORY_PILOT_ONLY" or summary["subject"] != "P01"
            or summary["recording_id"] != recording_id or summary["status"] != "COMPLETED"
            or summary["completed_segments"] != 60):
        raise ValueError("Original complete pilot identity mismatch")
    for path in (summary_path, source_dir / "features.csv"):
        expected = review["inputs"][str(path.relative_to(root))]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Original capture differs from reviewed bytes")
    return dict(original_recording_id=recording_id, original_segment_ids=segment_ids,
                original_features_sha256=summary["features_sha256"],
                review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
                reason="operator_reported_excessive_head_flexion_and_face_not_visible",
                reason_source="user report; technical landmark missingness separately verified",
                selection="prospective seven technical supplements; no automatic merging or model-based selection")


class PilotCapture:
    """Pure file/state controller; no camera, GUI, model inference or quality gate."""

    def __init__(self, directory, subject, recording_id, fields, *, repeats=10, hold_seconds=10,
                 operator_metadata=None, supplement_for=None):
        if repeats != 10 or hold_seconds != 10:
            raise ValueError("This exploratory request is fixed at 6 postures x 10 x 10 seconds")
        if supplement_for is not None:
            ids = supplement_for.get("original_segment_ids", [])
            if subject != "P01" or len(ids) != 7 or len(set(ids)) != 7:
                raise ValueError("P5 supplement requires P01 and seven distinct original segments")
        self.supplement_for = supplement_for
        self.sequence = (LABELS[-1],) * 7 if supplement_for is not None else LABELS * repeats
        self.target_counts = Counter(self.sequence)
        self.target_segments = len(self.sequence)
        self.directory, self.subject, self.recording_id = Path(directory), subject, recording_id
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / "attempts").mkdir()
        self.fields, self.repeats, self.hold_ms = tuple(fields), repeats, hold_seconds * 1000
        self.handle = (self.directory / "features.csv").open("x", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=self.fields)
        self.writer.writeheader()
        self.handle.flush()
        self.completed, self.attempts = [], []
        self.normal_ready, self.selected, self.active = False, None, None
        self.buffer, self.attempt_handle, self.attempt_writer = [], None, None
        self.closed = False
        self.message = "정상으로 복귀 후 Space → 목표 자세 선택 → 자세 안정 후 Enter"
        write_json(self.directory / "plan.json", dict(
            scope="EXPLORATORY_PILOT_ONLY", recording_id=recording_id, subject=subject,
            protocol="manual-six-posture-pilot/0.1-unapproved", posture_order=list(dict.fromkeys(self.sequence)),
            repeats=7 if supplement_for is not None else repeats, hold_seconds=hold_seconds,
            target_segments=self.target_segments, supplement_for=supplement_for,
            transition_frames_in_features=False, upright_resets_are_samples=False,
            model_prediction_used_for_capture=False, raw_rgb_depth_saved=False,
            clock="delivered frameset device_timestamp_ms", window="[first_frame, first_frame+10000ms)",
            operator_metadata=operator_metadata or {},
            source_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                           for name in ("capture_six_pilot.py", "posture_geometry_probe.py",
                                        "posture_geometry.py", "mediapipe_model_lock.json")},
            created_utc=datetime.now(timezone.utc).isoformat()))

    @property
    def done(self):
        return len(self.completed) == self.target_segments

    @property
    def expected(self):
        return None if self.done else self.sequence[len(self.completed)]

    def choose(self, label):
        if self.closed or self.done:
            return
        if self.active is not None:
            self.pause("posture_key_during_hold")
        if label == "upright":
            self.normal_ready = True
        if label != self.expected:
            if label == "upright":
                self.message = "정상 복귀 확인. 다음 목표 자세 키를 누르세요. 정상 복귀는 저장되지 않습니다."
            else:
                self.message = "화면에 표시된 다음 목표 자세만 선택할 수 있습니다."
            self.selected = None
            return
        if not self.normal_ready:
            self.message = "먼저 정상으로 복귀하고 Space를 누르세요. 이 준비 구간은 저장되지 않습니다."
            return
        self.selected = label
        self.message = "목표 자세를 충분히 안정시킨 뒤 Enter로 10초 측정 시작"

    def start(self):
        if self.closed or self.done:
            return False
        if self.active is not None:
            self.pause("manual_stop")
            return False
        if self.selected != self.expected or not self.normal_ready:
            self.message = "정상 복귀 확인 → 목표 자세 선택을 먼저 진행하세요."
            return False
        attempt_id = len(self.attempts) + 1
        self.active = dict(attempt_id=attempt_id, label=self.selected, status="ARMED",
                           intended_segment=len(self.completed)+1, first_device_ms=None,
                           last_device_ms=None, frames=0)
        if self.supplement_for is not None:
            self.active["supplement_for"] = dict(recording_id=self.supplement_for["original_recording_id"],
                segment_id=self.supplement_for["original_segment_ids"][len(self.completed)])
        self.attempts.append(self.active)
        self.attempt_handle = (self.directory / "attempts" / f"attempt_{attempt_id:03d}.csv").open(
            "x", encoding="utf-8", newline="")
        self.attempt_writer = csv.DictWriter(self.attempt_handle, fieldnames=self.fields)
        self.attempt_writer.writeheader()
        self.buffer = []
        self.message = "측정 중 — 자세 유지. 10초 뒤 자동 정지. 중단은 T 또는 Enter."
        return True

    def _close_attempt(self):
        if self.attempt_handle is not None:
            self.attempt_handle.close()
            self.attempt_handle = self.attempt_writer = None

    def _persist_attempt(self):
        attempt = self.active
        write_json(self.directory / "attempts" / f"attempt_{attempt['attempt_id']:03d}.json", attempt)

    def pause(self, reason="manual_pause"):
        if self.active is not None:
            self.active.update(status="ABORTED", reason=reason)
            self._close_attempt()
            self._persist_attempt()
        self.active, self.selected, self.normal_ready, self.buffer = None, None, False, []
        self.message = "일시정지 — 이동/휴식은 저장되지 않습니다. 다음 측정은 정상 복귀 후 준비하세요."

    def accept(self, row, frame_index):
        if self.active is None:
            return False
        stamp = float(row["device_timestamp_ms"])
        if not math.isfinite(stamp):
            self.pause("nonfinite_device_timestamp")
            raise ValueError("Nonfinite device timestamp; unfinished hold was preserved as ABORTED")
        a = self.active
        if a["first_device_ms"] is None:
            a.update(first_device_ms=stamp, first_frame_index=frame_index, status="MEASURING")
        elif stamp <= a["last_device_ms"]:
            self.pause("nonmonotonic_device_timestamp")
            raise ValueError("Duplicate/reset device timestamp; no interpolation or completed sample")
        if stamp >= a["first_device_ms"] + self.hold_ms:
            a.update(status="COMPLETED", observed_end_device_ms=stamp,
                     window_end_device_ms=a["first_device_ms"]+self.hold_ms,
                     end_boundary_frame_index=frame_index)
            self._close_attempt()
            self._persist_attempt()
            # Only a full, operator-confirmed hold reaches the analysis CSV.
            self.writer.writerows(self.buffer)
            self.handle.flush()
            self.completed.append(dict(a))
            self.active, self.selected, self.normal_ready, self.buffer = None, None, False, []
            self.message = f"{self.target_segments}구간 완료 — 측정을 종료합니다." if self.done else "10초 완료. 저장 정지. 정상으로 복귀 후 Space."
            return False
        saved = dict(row, subject=self.subject, recording_id=self.recording_id,
                     label=a["label"], segment_id=a["intended_segment"])
        self.attempt_writer.writerow(saved)
        self.attempt_handle.flush()
        self.buffer.append(saved)
        a.update(last_device_ms=stamp, last_frame_index=frame_index, frames=len(self.buffer))
        return True

    def finish(self, error=None):
        if self.closed:
            return
        if self.active is not None:
            self.pause("error" if error else "quit_before_hold_end")
        self.handle.close()
        self.closed = True
        counts = Counter(s["label"] for s in self.completed)
        summary = dict(scope="EXPLORATORY_PILOT_ONLY", subject=self.subject, recording_id=self.recording_id,
            status="FAILED" if error else "COMPLETED" if self.done else "INTERRUPTED",
            error=str(error) if error else None, completed_segments=len(self.completed),
            counts={label: counts[label] for label in LABELS}, segments=self.completed, attempts=self.attempts,
            technical_eligibility="NOT_EVALUATED: completed hold is not a guaranteed valid H9/LR sample",
            face_distance_gate="NOT_APPLIED: this is the separate exploratory probe, not production capture",
            features_sha256=hashlib.sha256((self.directory / "features.csv").read_bytes()).hexdigest())
        if self.supplement_for is not None:
            summary["supplement_for"] = self.supplement_for
        write_json(self.directory / "run_summary.json", summary)


def accept_probe_frame(capture, frame):
    """Reuse the real same-frame geometry/flags; paused frames never reach files."""
    if capture.active is None:
        return False
    if frame.pose_detected is None:
        raise ValueError("The same-frame pose_detected callback observation is required")
    import posture_geometry_probe as probe
    row = probe.exploratory_csv_row(frame.result, pose_detected=frame.pose_detected,
        device_timestamp_ms=frame.device_timestamp_ms,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        subject=capture.subject, recording_id=capture.recording_id, label=capture.active["label"],
        segment_id=capture.active["intended_segment"])
    row.update(frame.face_matrix_values)
    capture.accept(row, frame.frame_index)
    return capture.active is None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True, choices=("P01", "P02"))
    parser.add_argument("--repeats", type=int, choices=(10,), default=10)
    parser.add_argument("--hold-seconds", type=int, choices=(10,), default=10)
    parser.add_argument("--p5-supplement", action="store_true",
                        help="P01 P5 only: seven 10-second holds bound to the saved capture review")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--camera-height-m", type=float)
    parser.add_argument("--chair-distance-m", type=float)
    parser.add_argument("--installation-angle-deg", type=float)
    parser.add_argument("--lighting")
    args = parser.parse_args(argv)
    supplement = None
    if args.p5_supplement:
        if args.subject != "P01":
            parser.error("--p5-supplement is authorized only for the seven P01 P5 failures")
        try:
            supplement = load_p5_supplement_binding()
        except (OSError, ValueError, KeyError) as exc:
            parser.error(f"Cannot bind the P01 P5 supplement: {exc}")
    # All camera / GUI dependencies are loaded only for the actual live command.
    import tkinter as tk
    import posture_geometry_probe as probe
    mode = "p5supp" if supplement is not None else "pilot6"
    recording_id = f"{args.subject}_{mode}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
    directory = args.output_dir or Path(__file__).resolve().parent / "captures" / recording_id
    capture = PilotCapture(directory, args.subject, recording_id, probe.CSV_FIELDS,
                           repeats=args.repeats, hold_seconds=args.hold_seconds,
                           supplement_for=supplement,
                           operator_metadata={key: getattr(args, key) for key in (
                               "camera_height_m", "chair_distance_m", "installation_angle_deg", "lighting")})
    window = None
    error = None
    try:
        window = tk.Tk()
        window.title(f"{args.subject} 탐색 촬영 — 방향키는 이 창에서 누르세요")
        window.geometry("760x460")
        window.attributes("-topmost", True)
        title, status, counts = tk.StringVar(), tk.StringVar(), tk.StringVar()
        tk.Label(window, textvariable=title, font=("Malgun Gothic", 21), wraplength=730).pack(pady=12)
        tk.Label(window, textvariable=status, font=("Malgun Gothic", 13), wraplength=720).pack(pady=10)
        tk.Label(window, textvariable=counts, font=("Malgun Gothic", 12)).pack(pady=8)
        tk.Label(window, text="Space 정상 / H 거북목 / ↓ 후방 / ← 좌측 / → 우측 / ↑ 전방\n"
                 "정상 복귀 Space → 목표 자세 키 → 자세 안정 → Enter 시작\n"
                 "10초 후 자동 정지 / T 또는 Enter 중단 / Q 종료\n"
                 "카메라 영상은 계속 표시되며 준비·전환·휴식은 분석 CSV에 저장되지 않습니다.",
                 font=("Malgun Gothic", 12), justify="left").pack(pady=8)
        running = [True]
        pressed = set()

        def quit_capture(event=None):
            running[0] = False

        def handle(event):
            key = event.keysym
            if key in pressed:
                return "break"
            pressed.add(key)
            if key in KEYS:
                capture.choose(KEYS[key])
            elif key.lower() == "h":
                capture.choose(LABELS[1])
            elif key == "Return":
                capture.start()
            elif key.lower() == "t":
                capture.pause()
            elif key.lower() == "q" or key == "Escape":
                quit_capture()
            return "break"

        window.bind("<KeyPress>", handle)
        window.bind("<KeyRelease>", lambda event: pressed.discard(event.keysym))
        window.bind("<FocusOut>", lambda event: pressed.clear())
        window.protocol("WM_DELETE_WINDOW", quit_capture)

        def poll():
            if not running[0] or capture.done:
                return False
            target = LABELS.index(capture.expected)
            progress = (f"P5 보완 {len(capture.completed)+1}/7구간" if capture.supplement_for is not None
                        else f"{len(capture.completed)//6+1}/10회차")
            title.set(f"{args.subject}: {progress} — P{target} {NAMES[target]} [{KEY_TEXT[target]}]")
            text = capture.message
            if capture.active and capture.active["first_device_ms"] is not None:
                elapsed = capture.active["last_device_ms"]-capture.active["first_device_ms"]
                text += f"\n측정 {elapsed/1000:.1f}/10.0초"
            status.set(text)
            completed = Counter(s["label"] for s in capture.completed)
            counts.set(" / ".join(f"P{i}: {completed[label]}/{capture.target_counts[label]}"
                                  for i,label in enumerate(LABELS) if capture.target_counts[label]))
            window.update_idletasks()
            window.update()
            return running[0] and not capture.done

        def frame_callback(frame):
            if accept_probe_frame(capture, frame):
                window.bell()

        print(f"Exploratory only; output: {directory.resolve()}", flush=True)
        print("Select the controller window for arrow/Enter keys. No model predictions guide capture.", flush=True)
        probe.run_probe(frame_callback=frame_callback, ui_poll=poll, show_3d_views="none")
    except BaseException as exc:
        error = exc
        raise
    finally:
        capture.finish(error)
        if window is not None:
            window.destroy()
        print(f"Saved {len(capture.completed)}/{capture.target_segments} completed holds: {directory.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
