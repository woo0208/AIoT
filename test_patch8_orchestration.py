"""CAP-005 / CAP-006 orchestration / static acquisition / reconciliation / report tests.

Hardware is simulated: a fake RealSense SDK drives the real static capture code, fake child
processes stand in for capture_d455.py, and analysis runs the real analyze_d455.run_analysis
with only frame extraction replaced. Synthetic data proves software structure only; it is
not D455 measurement evidence and creates no formal Patch 8 artifact.
"""
import ast
import builtins
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import io
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

import numpy as np

import analyze_d455
import integrity_check
import patch8_ledger as ledger
import patch8_prelock as prelock
import patch8_protocol as p8
import patch8_report as report
import patch8_static_capture as static_capture
import patch8_validation as validation
from patch8_test_fixtures import (EXECUTION_ID, INTRINSICS, POSE, SERIAL, analysis_environment, environment,
                                  gate_entry, pinhole_factory)
from test_capture_protocol import load_capture


REPO = Path(__file__).resolve().parent
FORWARD_ROUNDS = ("101", "102", "103", "111", "112", "113")


# ---------------------------------------------------------------- fake RealSense SDK / OpenCV
class FakeModel:
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class FakeIntrinsics:
    def __init__(self, values):
        self.__dict__.update({k: v for k, v in values.items() if k not in ("model", "coeffs")})
        self.coeffs = list(values["coeffs"])
        self.model = FakeModel(values["model"])


class FakeRS:
    """Minimal pyrealsense2 stand-in; depth frames are never readable by the static path."""

    def __init__(self, frames=400, fail_start=False, fail_after=None):
        self.frames, self.fail_start, self.fail_after = frames, fail_start, fail_after
        self.stream = types.SimpleNamespace(depth="depth", color="color")
        self.format = types.SimpleNamespace(z16="z16", bgr8="bgr8")
        self.camera_info = types.SimpleNamespace(name="name", serial_number="serial", firmware_version="fw",
                                                 usb_type_descriptor="usb")
        self.option = types.SimpleNamespace(stereo_baseline="stereo_baseline")
        self.configs, self.served = [], 0

    def config(self):
        rs = self

        class Config:
            def __init__(self):
                self.streams, self.record = [], None
                rs.configs.append(self)

            def enable_stream(self, *args):
                self.streams.append(args)

            def enable_record_to_file(self, path):
                self.record = path
        return Config()

    def pipeline(self):
        rs = self

        class Frames:
            def __init__(self, index):
                self.index = index

            def get_color_frame(self):
                return types.SimpleNamespace(get_data=lambda: np.zeros((72, 128, 3), np.uint8),
                                             get_frame_number=lambda: self.index + 1)

            def get_depth_frame(self):
                raise AssertionError("static acquisition must not read depth frames")

            def get_timestamp(self):
                return 1000.0 + self.index * 1000.0 / 15

        class Pipeline:
            def start(self, config):
                if rs.fail_start:
                    raise RuntimeError("synthetic start failure")
                if config.record:
                    Path(config.record).write_bytes(b"synthetic raw " + Path(config.record).name.encode())
                return types.SimpleNamespace(get_device=lambda: device, get_stream=lambda kind: stream)

            def wait_for_frames(self):
                if rs.fail_after is not None and rs.served >= rs.fail_after:
                    raise RuntimeError("synthetic stream failure")
                rs.served += 1
                return Frames(rs.served - 1)

            def stop(self):
                pass
        sensor = types.SimpleNamespace(get_depth_scale=lambda: 0.001, get_option=lambda option: 95.0)
        device = types.SimpleNamespace(get_info=lambda key: {"name": "Intel RealSense D455", "serial": SERIAL,
                                                             "fw": "5.0", "usb": "3.2"}[key],
                                       supports=lambda key: True, first_depth_sensor=lambda: sensor)
        stream = types.SimpleNamespace()
        stream.as_video_stream_profile = lambda: stream
        stream.get_intrinsics = lambda: FakeIntrinsics(INTRINSICS)
        stream.get_extrinsics_to = lambda other: types.SimpleNamespace(rotation=[1.0] * 9, translation=[0.0] * 3)
        return Pipeline()


class FakeCV2:
    FONT_HERSHEY_SIMPLEX = 0

    def __init__(self, quit_at=None):
        self.quit_at, self.calls, self.texts = quit_at, 0, []

    def resize(self, image, size):
        return np.zeros((size[1], size[0], 3), np.uint8)

    def flip(self, image, code):
        return image

    def putText(self, canvas, text, *args):
        self.texts.append(text)

    def imshow(self, name, canvas):
        pass

    def waitKey(self, delay):
        self.calls += 1
        return ord("q") if self.quit_at is not None and self.calls >= self.quit_at else -1

    def destroyAllWindows(self):
        pass


def production_module(rs):
    capture = load_capture()
    capture.rs = rs
    return capture


def frame_clock(rs):
    return lambda: 100.0 + rs.served / 15


def fake_git(args):
    return "c" * 40 if args[0] == "rev-parse" else ""


# ---------------------------------------------------------------- static acquisition child
class StaticCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"

    def record(self, rnd="1", **kwargs):
        rs = FakeRS(**{k: v for k, v in kwargs.items() if k in ("frames", "fail_start", "fail_after")})
        cv2 = FakeCV2(kwargs.get("quit_at"))
        code = static_capture.record_static("V01", rnd, "pilot", str(self.data), rs=rs, cv2=cv2, np=np,
                                            production=production_module(rs), clock=frame_clock(rs), git=fake_git)
        return code, rs, cv2

    def files(self):
        camera = next(self.data.glob("*_camera.json"))
        rid = camera.name[:-len("_camera.json")]
        return rid, json.loads(camera.read_text()), self.data

    def test_static_provenance_reuses_capture_provenance_without_repurposing(self):
        code, rs, _ = self.record()
        self.assertEqual(code, 0)
        rid, camera, data = self.files()
        self.assertTrue(analyze_d455.new_recording_name(rid + ".db3"))
        self.assertEqual(camera["schema_version"], "capture-provenance/1.0.0")
        self.assertEqual(camera["protocol_version"], "patch8-d455-static-validation-v1.0.0")
        self.assertEqual((camera["recording_id"], camera["record_file"], camera["dataset_role"]),
                         (rid, rid + ".db3", "pilot"))
        self.assertEqual(camera["sidecar_files"], {k: f"{rid}_{k}.{e}" for k, e in (
            ("camera", "json"), ("markers", "csv"), ("samples", "csv"), ("quality", "json"))})
        for absent in ("target_range_m", "start_distance", "forward_target_min_m", "forward_target_max_m",
                       "forward_validation_source", "prep_sec", "nominal_distance", "repetition_index",
                       "attempt_index", "execution_id"):
            self.assertNotIn(absent, camera)
        self.assertEqual(camera["sequence"], [["upright", 10.0]])
        self.assertEqual(camera["color_intrinsics"], INTRINSICS)
        self.assertEqual(camera["capture_script_sha256"],
                         hashlib.sha256(Path(static_capture.__file__).read_bytes()).hexdigest())
        self.assertEqual(rs.configs[0].streams, [("depth", 848, 480, "z16", 15), ("color", 1280, 720, "bgr8", 15)])
        self.assertFalse((data / f"{rid}_samples.csv").exists())
        self.assertFalse((data / f"{rid}_quality.json").exists())

    def test_one_upright_hold_marker_and_ten_second_recording(self):
        self.record()
        rid, _, data = self.files()
        with open(data / f"{rid}_markers.csv", encoding="utf-8") as stream:
            markers = list(csv.DictReader(stream))
        self.assertEqual([(m["phase"], m["label"], m["step"], m["planned_sec"]) for m in markers],
                         [("hold", "upright", "1", "10.0"), ("end", "end", "", "")])
        self.assertTrue(all(m["recording_id"] == rid for m in markers))
        loaded = analyze_d455.load_markers(str(data / (rid + ".db3")))
        self.assertEqual([(m["phase"], m["label"]) for m in loaded], [("hold", "upright")])

    def test_structured_exit_status(self):
        for kwargs, status, label in ((dict(quit_at=5), "operator_abort", "aborted"),
                                      (dict(fail_after=20), "stream_failure", "aborted")):
            with self.subTest(status=status):
                shutil.rmtree(self.data, ignore_errors=True)
                code, _, _ = self.record(**kwargs)
                self.assertEqual(prelock.STATIC_EXIT_STATUS[code], status)
                rid, _, data = self.files()
                with open(data / f"{rid}_markers.csv", encoding="utf-8") as stream:
                    self.assertEqual(list(csv.DictReader(stream))[-1]["label"], label)
        shutil.rmtree(self.data)
        code, _, _ = self.record(fail_start=True)
        self.assertEqual(prelock.STATIC_EXIT_STATUS[code], "record_start_failed")
        rid, camera, _ = self.files()
        self.assertIsNone(camera["record_file"])                     # reservation preserved

    def test_operator_visible_output_is_firewalled(self):
        _, _, cv2 = self.record()
        allowed = re.compile(r"^(PATCH 8 STATIC HOLD \(upright\)|ELAPSED +[0-9]+\.[0-9] / 10\.0 s|REC)$")
        self.assertTrue(cv2.texts)
        self.assertTrue(all(allowed.match(text) for text in cv2.texts), set(cv2.texts))
        self.assertEqual(static_capture.overlay_lines("WARM-UP", 3.25, 60.0, False),
                         ["PATCH 8 WARM-UP", "ELAPSED  3.2 / 60.0 s", "NOT RECORDING"])
        with self.assertRaises(ValueError):
            static_capture.overlay_lines("DISTANCE 0.71 m", 1, 10, True)
        self.assertEqual(list(inspect.signature(static_capture.overlay_lines).parameters),
                         ["phase", "elapsed_s", "total_s", "recording"])

    def test_static_module_has_no_analysis_or_result_output_paths(self):
        tree = ast.parse(Path(static_capture.__file__).read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("align", "get_depth_frame", "measure_distance", "face_distance", "body_distance",
                          "face_cascade", "quality_check", "report", "print", "guide_phase", "SEQ_CORE", "SEQ_FULL",
                          "FWD_TARGET_MIN_M", "TARGET_MIN_M", "evaluate_forward_distance", "median_face_distance"):
            self.assertNotIn(forbidden, names)

    def test_warm_up_streams_without_recording(self):
        rs = FakeRS()
        code = static_capture.warm_up(60.0, rs=rs, cv2=FakeCV2(), np=np, production=production_module(rs),
                                      clock=frame_clock(rs))
        self.assertEqual(code, 0)
        self.assertGreaterEqual(rs.served, 900)
        self.assertIsNone(rs.configs[0].record)
        self.assertFalse(self.data.exists())

    def test_cli_identity_guards(self):
        for argv in (["V01", "101"], ["V01", "1", "--dataset-role", "formal"], ["V_01", "1"],
                     ["--warmup-seconds", "30"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                static_capture.main(argv)

    def test_static_recording_passes_patch7_integrity_and_analyzer_identity(self):
        self.record()
        rid, camera, data = self.files()
        root = Path(self.temp.name)
        shutil.copyfile(REPO / "mediapipe_model_lock.json", root / "mediapipe_model_lock.json")
        result = integrity_check.audit_repository(root)
        self.assertEqual(result.counts["ERROR"], 0, result.findings)
        out = root / "analysis"
        args = types.SimpleNamespace(subjects=["V01"], step=1, from_csv=False, legacy_pilot=False)
        with patch.object(analyze_d455, "OUT_DIR", str(out)), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()):
            _, manifest = analyze_d455.start_analysis_run(str(data / (rid + ".db3")), args, "batch")
        self.assertEqual((manifest["recording_id"], manifest["protocol_version"], manifest["dataset_role"]),
                         (rid, p8.STATIC_PROTOCOL_VERSION, "pilot"))
        self.assertEqual(len(analyze_d455.FRAME_FIELDS), 60)
        self.assertEqual(analyze_d455.FRAME_SCHEMA_VERSION, "frames-schema/1.0.0")
        self.assertEqual(analyze_d455.SUMMARY_SCHEMA_VERSION, "summary-schema/1.0.0")


# ---------------------------------------------------------------- synthetic world for orchestration
class FakeProcess:
    def __init__(self, behaviour):
        self.behaviour, self.polls, self.code = behaviour, 0, None
        self.terminated = self.killed = False

    def poll(self):
        if self.code is None:
            self.polls += 1
            self.code = self.behaviour(self.polls)
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def kill(self):
        self.killed = True
        self.code = -9

    def wait(self):
        while self.poll() is None:
            pass
        return self.code


class FakeConsole(validation.OperatorConsole):
    def __init__(self, answer="NO"):
        self.lines, self.events = [], []
        super().__init__(write=self.record, read=lambda text: self.prompted(text, answer))

    def record(self, line):
        self.lines.append((self.sealed, line))

    def prompted(self, text, answer):
        self.lines.append((self.sealed, text))
        return answer


class FakeObservations:
    def __init__(self):
        self.pending = []

    def poll(self):
        pending, self.pending = self.pending, []
        return pending


def make_runtime(root, world):
    clock = types.SimpleNamespace(t=0.0)
    times = itertools.count()

    def sleep(seconds):
        clock.t += seconds

    def now():
        return datetime(2026, 10, 7, tzinfo=timezone.utc) + timedelta(milliseconds=next(times))

    @contextmanager
    def signals():
        captured = types.SimpleNamespace(name=None)
        world.signal_box = captured
        yield captured
    return validation.Runtime(root=Path(root), popen=world.popen, run=world.run, clock=lambda: clock.t, sleep=sleep,
                              now=now, console=FakeConsole(), observations=FakeObservations(), signals=signals,
                              python="python-under-test")


class World:
    """Fake child processes and probes; every artifact is synthetic and lives in a temp root."""

    def __init__(self, root):
        self.root = Path(root)
        self.data = self.root / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.launches, self.production = [], {}
        self.static_kwargs, self.signal_box = {}, None
        self.raw_probe = dict(exists=True, openable=True, color_frame=True, depth_frame=True)
        self.enumeration = {"probe_ok": True, "devices": [{"serial": SERIAL, "name": "Intel RealSense D455"}]}
        self.capture_environment = environment()
        self.analysis_environment = analysis_environment()
        self.probes = []

    # -------------------------------------------------------- subprocess.run stand-in
    def run(self, command, **kwargs):
        def done(stdout, code=0):
            return subprocess.CompletedProcess(command, code, stdout, "")
        if command[0] == "git":
            if command[1] == "rev-parse":
                return done("c" * 40)
            return done("") if command[1] == "status" else done("", 0)
        if Path(command[1]).name == "patch8_prelock.py":
            self.probes.append(command[2])
            value = {"capture-environment": self.capture_environment,
                     "analysis-environment": self.analysis_environment,
                     "enumerate": self.enumeration}.get(command[2], self.raw_probe)
            return done(json.dumps(value).encode())
        if Path(command[1]).name == "integrity_check.py":
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = integrity_check.main(["--repo-root", str(self.root)])
            return done(buffer.getvalue(), code)
        raise AssertionError(f"unexpected command {command}")

    # -------------------------------------------------------- subprocess.Popen stand-in
    def popen(self, command, **kwargs):
        script = Path(command[1]).name
        self.launches.append(command)
        kwargs["stdout"].write(b"sealed child stdout: verdict, distance and quality text\n")
        if script == "patch8_static_capture.py" and "--warmup-seconds" in command:
            return FakeProcess(lambda polls: 0)
        if script == "patch8_static_capture.py":
            subject, rnd = command[2], command[3]
            kwargs_ = dict(self.static_kwargs)
            rs = FakeRS(**{k: v for k, v in kwargs_.items() if k in ("fail_start", "fail_after")})

            def behaviour(polls):
                return static_capture.record_static(subject, rnd, "pilot", str(self.data), rs=rs,
                                                    cv2=FakeCV2(kwargs_.get("quit_at")), np=np,
                                                    production=production_module(rs), clock=frame_clock(rs),
                                                    git=fake_git)
            return FakeProcess(behaviour)
        if script == "capture_d455.py":
            mode = "core" if "core" in command else "full"
            scenario = self.production.get(command[3], {})
            return FakeProcess(lambda polls: self.production_child(command[2], command[3], mode, scenario, polls,
                                                                   kwargs["stderr"]))
        if script == "patch8_validation.py" and command[2] == "_analyze-one":
            def behaviour(polls):
                with self.analysis_patches():
                    validation.analyze_one(command[3])
                return 0
            return FakeProcess(behaviour)
        raise AssertionError(f"unexpected child {command}")

    def production_child(self, subject, rnd, mode, scenario, polls, stderr):
        reserve_at = scenario.get("reserve_at", 3)
        if scenario.get("guide_q") and polls >= 2:
            return 0
        if scenario.get("signal") and polls >= 2:
            self.signal_box.name = scenario["signal"]
            return -2
        if reserve_at is None or polls < reserve_at:
            return None
        if polls == reserve_at:
            write_production_capture(self.data, subject, rnd, mode, scenario)
        if scenario.get("crash"):
            stderr.write(b"Traceback (most recent call last):\n  File \"capture_d455.py\"\n"
                         b"RuntimeError: Frame didn't arrive within 5000\n")
            return 1
        return 0 if polls >= reserve_at + 2 else None

    @contextmanager
    def analysis_patches(self):
        lock = json.loads((self.root / "mediapipe_model_lock.json").read_text())
        models = {e["role"]: str(self.root / "models" / e["filename"]) for e in lock["artifacts"]}
        with ExitStack() as stack:
            for name, value in (("OUT_DIR", str(self.root / "analysis")), ("DATA_DIR", str(self.data)),
                                ("MODEL_DIR", str(self.root / "models")),
                                ("MODEL_LOCK_PATH", str(self.root / "mediapipe_model_lock.json"))):
                stack.enter_context(patch.object(analyze_d455, name, value))
            stack.enter_context(patch.object(analyze_d455, "ensure_models", return_value=models))
            stack.enter_context(patch.object(analyze_d455, "process_recording", side_effect=synthetic_frames))
            stack.enter_context(patch.object(analyze_d455, "plot_all", side_effect=lambda rows, summary: Path(
                analyze_d455.OUT_DIR, "fig.png").write_bytes(b"synthetic figure")))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            yield


def write_production_capture(data, subject, rnd, mode, scenario):
    stamp = datetime(2026, 10, 7, 10, 0, 0)
    rid = f"{subject}_r{rnd}_{stamp.strftime('%Y%m%d_%H%M%S')}_000000_{uuid.uuid4().hex}"
    sequence = p8.PRODUCTION_SEQUENCES[mode]
    sidecars = {k: f"{rid}_{k}.{e}" for k, e in (("camera", "json"), ("markers", "csv"), ("samples", "csv"),
                                                   ("quality", "json"))}
    camera = dict(schema_version="capture-provenance/1.0.0", recording_id=rid, subject=subject, round=rnd,
                  start_time="20261007_100000", dataset_role="pilot", protocol_version=p8.PRODUCTION_PROTOCOL_VERSION,
                  record_file=rid + ".db3", sidecar_files=sidecars,
                  start_distance=dict(distance_m=0.75, mode="face_skipped" if scenario.get("skip") else "face"),
                  target_range_m=[0.7, 0.8], fps=15, sequence=[list(s) for s in sequence], prep_sec=4,
                  color_intrinsics=dict(INTRINSICS), depth_scale_m=0.001, forward_target_min_m=0.08,
                  forward_target_max_m=0.12, forward_validation_source="face_only", provenance_unknown_reasons={})
    (data / (rid + "_camera.json")).write_text(json.dumps(camera), encoding="utf-8")
    (data / (rid + ".db3")).write_bytes(b"synthetic production raw " + rid.encode())
    markers, ts, phase_index = [], 1000.0, {}
    for step, (label, seconds) in enumerate(sequence, 1):
        for kind, duration in (("prep", 4), ("hold", seconds)):
            phase_index[(step, kind)] = len(markers)
            markers.append(dict(wall_time=ts, frame_timestamp_ms=ts, color_frame_number=1, step=step, phase=kind,
                                label=label if kind == "hold" else "transition", planned_sec=duration,
                                distance_m=0.75, distance_mode="face", recording_id=rid))
            ts += duration * 1000
    markers.append(dict(wall_time=ts, frame_timestamp_ms=None, color_frame_number=None, step=None, phase="end",
                        label="end", planned_sec=None, distance_m=None, distance_mode="face", recording_id=rid))
    write_csv(data / sidecars["markers"], markers)
    samples = [dict(phase_idx=phase_index[(4, "hold")], step=4, phase="hold", label="body_forward", t=t,
                    distance_m=0.72, mode="body", face_cx=None, recording_id=rid) for t in (2.0, 5.0, 8.0)] \
        if scenario.get("body_samples", True) else []
    samples.append(dict(phase_idx=0, step=1, phase="prep", label="upright", t=1.0, distance_m=0.75, mode="face",
                        face_cx=0.5, recording_id=rid))
    write_csv(data / sidecars["samples"], samples)
    entries = scenario.get("evidence")
    if entries is None:
        entries = [gate_entry("forward_head", ref=0.75, cur=0.65, phase_idx=phase_index[(2, "hold")]),
                   gate_entry("body_forward", ref=0.75, cur=0.65, phase_idx=phase_index[(4, "hold")])]
    for entry in entries:
        entry["phase_idx"] = phase_index[(2 if entry["label"] == "forward_head" else 4, "hold")]
    (data / sidecars["quality"]).write_text(json.dumps(dict(
        verdict=scenario.get("verdict", "ok"), fails=[], warnings=[], frames="synthetic", total_sec=70.0,
        recording_id=rid, forward_gate_evidence=entries, steps=[])), encoding="utf-8")
    return rid


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def synthetic_frames(rec_path, models, step, provenance=None, output_dir=None):
    """Replaces only MediaPipe/RealSense extraction: canonical 60-field rows per hold phase."""
    for role in models:
        analyze_d455.mark_model_used(provenance, role)
    provenance["playback_calibration"] = dict(depth_scale_m=0.001, color_intrinsics=dict(INTRINSICS))
    subject, rnd = analyze_d455.parse_name(rec_path)
    marks = analyze_d455.load_markers(rec_path)
    rows, index = [], 0
    holds = [m for m in marks if m["phase"] == "hold"]
    for mark in holds:
        count = 128 if mark["label"] in ("upright", "forward_head", "body_forward") else 20
        for i in range(count):
            index += 1
            jitter = 0.001 if i % 2 else -0.001
            rows.append({field: None for field in analyze_d455.FRAME_FIELDS} | dict(
                subject=subject, round=rnd, step=mark["step"], label=mark["label"], t=round(1.0 + i / 15 + 0.01, 3),
                ts_ms=mark["ts"] + 1000 + i * 66.7, frame_schema_version=analyze_d455.FRAME_SCHEMA_VERSION,
                recording_id=provenance["recording_id"], analysis_run_id=provenance["analysis_run_id"],
                frame_index=index, color_frame_number=index, depth_frame_number=index, mediapipe_ts_ms=index,
                face_detected=True, face_mesh_detected=True, pose_detected=True, face_depth_valid=True,
                face_depth_source="bbox_roi", face_x=640.0, face_y=300.0, face_w_px=100.0, face_h_px=100.0,
                face_area_px=10000.0, z_face_m=0.8 + jitter, ipd_cm=6.3, lsh_valid=True, rsh_valid=True,
                lsh_depth_valid=True, rsh_depth_valid=True, shoulder_depth_source="both", lsh_x=840.0, lsh_y=420.0,
                rsh_x=440.0, rsh_y=420.0, z_lsh_m=0.85 + jitter, z_rsh_m=0.85 + jitter, z_sh_m=0.85,
                left_hip_x_px=800.0, left_hip_y_px=700.0, left_hip_depth_m=0.9 + jitter, left_hip_visibility=0.9,
                left_hip_valid=True, left_hip_depth_valid=True, right_hip_x_px=480.0, right_hip_y_px=700.0,
                right_hip_depth_m=0.9 + jitter, right_hip_visibility=0.9, right_hip_valid=True,
                right_hip_depth_valid=True))
    path = os.path.join(output_dir, Path(rec_path).stem + "_frames.csv")
    analyze_d455.write_frames_csv(path, rows)
    return rows


class OrchestrationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.world = World(self.root)
        self.rt = make_runtime(self.root, self.world)
        lock = json.loads((REPO / "mediapipe_model_lock.json").read_text())
        (self.root / "models").mkdir()
        for entry in lock["artifacts"]:
            content = b"synthetic model " + entry["role"].encode()
            (self.root / "models" / entry["filename"]).write_bytes(content)
            entry["sha256"] = hashlib.sha256(content).hexdigest()
        (self.root / "mediapipe_model_lock.json").write_text(json.dumps(lock, indent=2))
        self.ledger_path = validation.execution_dir(self.root, EXECUTION_ID) / p8.LEDGER_FILENAME
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stderr(io.StringIO()))

    def state(self):
        return ledger.verify_ledger(self.ledger_path)[1]

    def events(self, kind=None):
        events = ledger.verify_ledger(self.ledger_path)[0]
        return [e for e in events if kind is None or e["event_type"] == kind]

    def session(self, kind):
        validation.open_session(self.rt, EXECUTION_ID, kind, "V01")
        if not self.state().model_verified:
            self.assertEqual(validation.verify_models(self.rt, EXECUTION_ID), "PASS")
        if not self.state().pre_hardware_integrity:
            self.assertTrue(validation.record_integrity(self.rt, EXECUTION_ID, "pre_hardware"))
        self.assertTrue(validation.warmup(self.rt, EXECUTION_ID))
        if kind == "static-grid":
            validation.setup_verified(self.rt, EXECUTION_ID, dict(POSE), "initial")

    def close(self, kind):
        if kind == "static-grid":
            self.assertFalse(validation.pose_recheck(self.rt, EXECUTION_ID, dict(POSE, witness_mark_displaced=False)))
        validation.close_session(self.rt, EXECUTION_ID, "completed")

    def attempt(self, rnd):
        return validation.run_attempt(self.rt, EXECUTION_ID, rnd, {k: True for k in ledger.SETUP_CHECKS})


class AttemptLifecycleTests(OrchestrationCase):
    def test_static_attempt_lifecycle_sealing_and_firewall(self):
        self.session("static-grid")
        result, outcome = self.attempt("1")
        self.assertIsNone(outcome)
        self.assertEqual((result.reason_code, result.acquisition_valid, result.rule_id),
                         (None, True, "R17_ACQUISITION_COMPLETED"))
        kinds = [e["event_type"] for e in self.events()][-4:]
        self.assertEqual(kinds, ["attempt_start", "capture_finished", "validity_locked", "attempt_end"])
        start = self.events("attempt_start")[0]
        self.assertEqual((start["nominal_distance"], start["repetition_index"], start["attempt_index"],
                          start["validation_protocol_version"]), (0.6, 1, 1, p8.STATIC_PROTOCOL_VERSION))
        finished = self.events("capture_finished")[0]
        rid = finished["recording_id"]
        self.assertTrue(rid.startswith("V01_r1_"))
        directory = validation.execution_dir(self.root, EXECUTION_ID)
        stdout = directory / finished["logs"]["stdout"]["path"]
        self.assertIn(b"sealed child stdout", stdout.read_bytes())
        sealed_lines = [line for sealed, line in self.rt.console.lines if sealed]
        allowed = re.compile(r"^\[PATCH 8\] (PHASE [A-Za-z0-9 ()-]+|ELAPSED +[0-9.]+ / [0-9.]+ s|RECORDING "
                             r"(CHILD RUNNING|STOPPED)|Did the operator end this attempt.*)$")
        self.assertTrue(sealed_lines)
        self.assertTrue(all(allowed.match(line) for line in sealed_lines), sealed_lines)
        self.assertFalse(any("sealed child stdout" in line for _, line in self.rt.console.lines))
        self.assertEqual(len([c for c in self.world.launches if Path(c[1]).name == "patch8_static_capture.py"
                              and "--warmup-seconds" not in c]), 1)
        with self.assertRaises(validation.FirewallViolation):
            self.rt.console.seal()
            self.rt.console.info("distance 0.71 m")

    def guarded_attempt(self, rnd):
        """Record every read of result-bearing sidecars / sealed logs with the lifecycle state.
        Patches both builtins.open and io.open (Path.read_bytes uses io.open)."""
        opened, real_open = [], io.open
        permitted = {"_artifact", "extract_exception_class"}   # log hashing; whitelisted class token

        def guarded(path, mode="r", *args, **kwargs):
            name = str(path)
            if "r" in mode and "+" not in mode and name.endswith(
                    ("_quality.json", "_samples.csv", "_markers.csv", ".stdout.log", ".stderr.log")):
                ended = any(e["event_type"] == "attempt_end" for e in ledger.parse_ledger_bytes(
                    self.ledger_path.read_bytes())[0][-4:])
                callers = {frame.function for frame in inspect.stack()[1:8]}
                opened.append((Path(name).name, ended, bool(callers & permitted)))
            return real_open(path, mode, *args, **kwargs)
        with patch.object(builtins, "open", guarded), patch.object(io, "open", guarded):
            result, outcome = self.attempt(rnd)
        return result, outcome, opened

    def test_no_result_bearing_file_is_read_before_lock(self):
        self.world.production["121"] = dict(evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                      gate_entry("body_forward", ref=0.75, cur=None)])
        self.session("body-only-negative")
        result, outcome, opened = self.guarded_attempt("121")
        self.assertTrue(result.acquisition_valid)
        self.assertEqual(outcome["reason_code"], None)
        for sidecar in ("_quality.json", "_samples.csv", "_markers.csv"):     # positive control: reads observed
            self.assertTrue([o for o in opened if o[0].endswith(sidecar) and o[1]], sidecar)
        self.assertTrue(all(ended or permitted for _, ended, permitted in opened), opened)
        self.assertFalse([o for o in opened if not o[1] and o[0].endswith((".json", ".csv"))], opened)

    def test_crash_prelock_reads_only_permitted_stderr_class_extraction(self):
        self.world.production["131"] = dict(crash=True)
        self.session("E2E")
        result, _, opened = self.guarded_attempt("131")
        self.assertEqual(result.reason_code, p8.USB_STREAM_FAILURE)
        prelock_reads = [o for o in opened if not o[1]]
        self.assertTrue([o for o in prelock_reads if o[0].endswith(".stderr.log")])
        self.assertTrue(all(permitted for _, _, permitted in prelock_reads), prelock_reads)

    def test_production_canonical_first_attempt_and_no_result_driven_retry(self):
        self.world.production["131"] = dict(verdict="retake")
        self.session("E2E")
        result, outcome = self.attempt("131")
        self.assertEqual((outcome["outcome"], outcome["reason_code"]), (p8.CANONICAL, None))
        self.assertIsNone(self.state().next_attempt_index("131"))
        with self.assertRaisesRegex(RuntimeError, "no further attempt"):
            self.attempt("131")
        command = [c for c in self.world.launches if Path(c[1]).name == "capture_d455.py"]
        self.assertEqual(command, [["python-under-test", str(self.root / "capture_d455.py"), "V01", "131",
                                    "--dataset-role", "pilot"]])

    def test_slot131_post_reservation_guide_skip_is_canonical_fail_without_retry(self):
        self.world.production["131"] = dict(skip=True)
        self.session("E2E")
        result, outcome, opened = self.guarded_attempt("131")
        self.assertEqual((result.reason_code, result.acquisition_valid, result.retry_allowed), (None, True, False))
        self.assertEqual((outcome["outcome"], outcome["reason_code"]),
                         (p8.CANONICAL, p8.GUIDE_NOT_SATISFIED))
        self.assertIsNone(self.state().next_attempt_index("131"))
        e2e = report.evaluate_execution(self.root, self.ledger_path, pinhole_factory)["metrics"]["slot_131"]
        self.assertFalse(e2e["passed"])
        self.assertFalse(e2e["components"]["canonical_acquisition_valid_recording"])
        self.assertTrue(all(ended or permitted for _, ended, permitted in opened), opened)

    def test_slot121_runs_seq_core_and_records_target_miss_retry(self):
        self.world.production["121"] = dict(evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                      gate_entry("body_forward", ref=0.75, cur=0.65)])
        self.session("body-only-negative")
        _, outcome = self.attempt("121")
        self.assertEqual(outcome["outcome"], p8.TARGET_MISS)
        self.assertEqual(self.world.launches[-1][4], "core")
        self.world.production["121"] = dict(evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                      gate_entry("body_forward", ref=0.75, cur=None)])
        _, outcome = self.attempt("121")
        self.assertEqual((outcome["outcome"], outcome["reason_code"]), (p8.CANONICAL, None))
        self.assertEqual(self.state().canonical_attempt("121").attempt_index, 2)

    def test_guide_timeout_and_guide_q_are_guide_not_satisfied(self):
        self.world.production["121"] = dict(reserve_at=None)
        self.session("body-only-negative")
        result, outcome = self.attempt("121")
        self.assertEqual((result.reason_code, result.acquisition_valid, result.retry_allowed, result.rule_id),
                         (p8.GUIDE_NOT_SATISFIED, True, False, "R02_GUIDE_TIMEOUT"))
        finished = self.events("capture_finished")[-1]
        self.assertTrue(finished["termination"]["orchestrator_timeout_kill"])
        self.assertEqual((finished["stage"], finished["bound_recording_ids"]), ("pre_reservation", []))
        self.assertEqual((outcome["outcome"], outcome["reason_code"]), (p8.CANONICAL, p8.GUIDE_NOT_SATISFIED))
        self.assertIsNone(self.state().next_attempt_index("121"))

    def test_guide_q_and_operator_signal(self):
        self.world.production["131"] = dict(guide_q=True)
        self.session("E2E")
        result, _ = self.attempt("131")
        self.assertEqual((result.reason_code, result.rule_id), (p8.GUIDE_NOT_SATISFIED, "R06_GUIDE_Q_PRE_RESERVATION"))
        self.setUp()
        self.world.production["131"] = dict(signal="SIGINT")
        self.session("E2E")
        result, _ = self.attempt("131")
        self.assertEqual((result.reason_code, result.retry_allowed), (p8.MANUAL_ABORT, False))

    def test_machine_failure_retry_uses_only_permitted_evidence(self):
        self.world.production["131"] = dict(crash=True)
        self.world.enumeration = {"probe_ok": True, "devices": []}
        self.session("E2E")
        result, outcome = self.attempt("131")
        self.assertEqual((result.reason_code, result.acquisition_valid, result.retry_allowed),
                         (p8.CAMERA_DISCONNECT, False, True))
        self.assertIsNone(outcome)
        lock = self.events("validity_locked")[-1]
        evidence = json.loads((validation.execution_dir(self.root, EXECUTION_ID) /
                               lock["machine_evidence_ref"]["path"]).read_bytes())
        self.assertEqual(evidence["exception_class"], "RuntimeError")
        self.assertNotIn("Frame didn't arrive", json.dumps(evidence))
        self.world.production["131"] = {}
        self.world.enumeration = {"probe_ok": True, "devices": [{"serial": SERIAL}]}
        self.attempt("131")
        self.assertEqual(self.state().canonical_attempt("131").attempt_index, 2)

    def test_static_interruption_is_logged_immediately_and_grants_retry(self):
        self.session("static-grid")
        self.rt.observations.pending.append(p8.EXTERNAL_PHYSICAL_INTERRUPTION)
        result, _ = self.attempt("1")
        self.assertEqual((result.reason_code, result.retry_allowed), (p8.EXTERNAL_PHYSICAL_INTERRUPTION, True))
        kinds = [e["event_type"] for e in self.events()]
        self.assertLess(kinds.index("operator_observation"), kinds.index("capture_finished"))
        self.attempt("1")
        self.assertEqual(self.state().canonical_attempt("1").attempt_index, 2)

    def test_static_q_abort_is_manual_abort_without_retry(self):
        self.world.static_kwargs = dict(quit_at=3)
        self.session("static-grid")
        result, _ = self.attempt("1")
        self.assertEqual((result.reason_code, result.rule_id, result.retry_allowed),
                         (p8.MANUAL_ABORT, "R05_STATIC_Q_ABORT", False))

    def test_cap006_forward_slots_launch_seq_core(self):
        self.session("forward-gate")
        for rnd in FORWARD_ROUNDS:
            with self.subTest(rnd=rnd):
                self.assertEqual(p8.SLOTS[rnd].sequence_mode, "core")
                self.attempt(rnd)
                self.assertEqual(self.world.launches[-1],
                                 ["python-under-test", str(self.root / "capture_d455.py"), "V01", rnd,
                                  "core", "--dataset-role", "pilot"])
                self.assertEqual(self.events("attempt_start")[-1]["sequence_mode"], "core")

    def test_unsupported_production_sequences_fail_closed(self):
        for rnd in (*FORWARD_ROUNDS, "121", "131"):
            for mode in (None, "unknown"):
                with self.subTest(rnd=rnd, mode=mode):
                    self.setUp()
                    slot = p8.SLOTS[rnd]
                    self.session(slot.session_kind)
                    before = self.ledger_path.read_bytes()
                    launches = list(self.world.launches)
                    with patch.dict(p8.SLOTS, {rnd: replace(slot, sequence_mode=mode)}):
                        with self.assertRaisesRegex(validation.DesignAuthorityGap,
                                                    "not supported by CAP-005/CAP-006"):
                            self.attempt(rnd)
                    self.assertEqual(self.ledger_path.read_bytes(), before)
                    self.assertEqual(self.world.launches, launches)

    def test_setup_check_failure_creates_no_attempt(self):
        self.session("static-grid")
        before = self.ledger_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "setup checks"):
            validation.run_attempt(self.rt, EXECUTION_ID, "1", dict(hips_visually_unobstructed=False,
                                                                    hands_forearms_clear_of_hips=True,
                                                                    external_occluder_absent=True))
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(prelock.recording_inventory(self.root / "data"), [])

    def test_recover_open_attempt_fail_closed_and_power_evidence(self):
        self.session("E2E")
        state = self.state()
        led = validation.open_ledger(self.root, EXECUTION_ID)
        identity = validation.attempt_identity(state, p8.SLOTS["131"], 1)
        led.append("attempt_start", state.open_session, dict(
            identity, recording_id=None, status="started", reason_code=None, slot_kind="e2e", sequence_mode="full",
            setup_checks={k: True for k in ledger.SETUP_CHECKS}, settling_s=10.0, pre_launch_inventory=[],
            code_state=dict(git_commit="c" * 40, git_clean=True)), self.rt.now())
        bad = dict(kind="host_power_event", path="evidence/none.txt", sha256="0" * 64,
                   event_time_utc="2026-10-07T00:00:00Z")
        with self.assertRaisesRegex(RuntimeError, "power-loss evidence rejected"):
            validation.recover_attempt(self.rt, EXECUTION_ID, "not_operator_initiated", bad)
        self.assertIsNone(self.state().attempts[("131", 1)].locked)
        evidence = validation.execution_dir(self.root, EXECUTION_ID) / "evidence" / "power.txt"
        evidence.parent.mkdir()
        evidence.write_bytes(b"UPS event export")
        good = dict(kind="ups_power_event", path="evidence/power.txt",
                    sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    event_time_utc=self.events("attempt_start")[0]["event_timestamp_utc"])
        result = validation.recover_attempt(self.rt, EXECUTION_ID, "not_operator_initiated", good)
        self.assertEqual((result.reason_code, result.retry_allowed), (p8.POWER_FAILURE, True))
        self.assertTrue(self.events("capture_finished")[-1]["termination"]["recovered"])

    def test_analysis_is_explicit_single_recording_and_first_completed_is_canonical(self):
        self.session("static-grid")
        self.attempt("1")
        run = validation.analyze(self.rt, EXECUTION_ID, "1")
        invocation = self.events("analysis_invocation")[-1]
        self.assertIn("analysis-environment", self.world.probes)
        self.assertEqual(invocation["environment"], analysis_environment())
        self.assertEqual(invocation["canonical_analysis_run_id"], run)
        self.assertEqual(len(invocation["analysis_runs"]), 1)
        command = self.world.launches[-1]
        self.assertEqual(command[2:], ["_analyze-one", str(self.root / "data" / (
            self.state().canonical_attempt("1").recording_id + ".db3"))])
        manifest = json.loads((self.root / "analysis" / invocation["recording_id"] / run /
                               "analysis_manifest.json").read_text())
        self.assertEqual((manifest["analysis_mode"], manifest["options"]["step_effective"], manifest["status"],
                          manifest["protocol_version"]), ("extract_raw", 1, "completed", p8.STATIC_PROTOCOL_VERSION))
        with self.assertRaisesRegex(RuntimeError, "not authorized"):
            validation.analyze(self.rt, EXECUTION_ID, "1")
        with self.assertRaisesRegex(RuntimeError, "ledger-canonical"):
            validation.analyze(self.rt, EXECUTION_ID, "2")

    def test_analysis_environment_probe_is_mandatory_before_child_launch(self):
        self.session("static-grid")
        self.attempt("1")
        self.world.analysis_environment = None
        launches = list(self.world.launches)
        with self.assertRaisesRegex(RuntimeError, "analysis environment snapshot"):
            validation.analyze(self.rt, EXECUTION_ID, "1")
        self.assertIn("analysis-environment", self.world.probes)
        self.assertEqual(self.world.launches, launches)
        self.assertEqual(self.state().execution_failure, "ENVIRONMENT_CHANGED")
        self.assertFalse(self.events("analysis_invocation"))

    def test_analysis_environment_is_actual_and_pinned_without_forcing_cross_host_equality(self):
        self.world.analysis_environment = analysis_environment(
            analysis_host="remote-analysis-host", os="remote-os", python="3.13",
            packages=dict(analysis_environment()["packages"], mediapipe="remote-mediapipe"))
        self.session("static-grid")
        self.attempt("1")
        run = validation.analyze(self.rt, EXECUTION_ID, "1")
        self.assertIsNotNone(run)
        recorded = self.events("analysis_invocation")[-1]["environment"]
        self.assertEqual(recorded["analysis_host"], "remote-analysis-host")
        self.assertNotEqual(recorded["analysis_host"], self.events("session_start")[0]["environment"]["capture_host"])
        self.assertNotIn("analysis_host", self.events("session_start")[0]["environment"])
        self.attempt("2")
        self.world.analysis_environment = dict(self.world.analysis_environment,
                                               analysis_host="changed-analysis-host")
        launches = list(self.world.launches)
        with self.assertRaisesRegex(RuntimeError, "analysis environment differs"):
            validation.analyze(self.rt, EXECUTION_ID, "2")
        self.assertEqual(self.world.launches, launches)

    def test_same_host_analysis_environment_mismatch_fails_before_analysis(self):
        self.session("static-grid")
        self.attempt("1")
        self.world.analysis_environment = analysis_environment(
            packages=dict(analysis_environment()["packages"], numpy="different"))
        launches = list(self.world.launches)
        with self.assertRaisesRegex(RuntimeError, "same-host analysis environment differs"):
            validation.analyze(self.rt, EXECUTION_ID, "1")
        self.assertEqual(self.world.launches, launches)
        self.assertFalse(self.events("analysis_invocation"))

    def test_analysis_realsense_sdk_mismatch_fails_before_analysis(self):
        self.session("static-grid")
        self.attempt("1")
        self.world.analysis_environment = analysis_environment(
            analysis_host="remote-analysis-host", realsense_sdk_version="different-sdk")
        launches = list(self.world.launches)
        with self.assertRaisesRegex(RuntimeError, "RealSense SDK identity differs"):
            validation.analyze(self.rt, EXECUTION_ID, "1")
        self.assertEqual(self.world.launches, launches)
        self.assertFalse(self.events("analysis_invocation"))

    def test_analysis_retry_requires_the_logged_failed_run_manifest(self):
        self.session("static-grid")
        self.attempt("1")
        state = self.state()
        attempt = state.canonical_attempt("1")
        rid, run_id = attempt.recording_id, "ar_failed"
        manifest_path = self.root / "analysis" / rid / run_id / "analysis_manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest = dict(analysis_run_id=run_id, recording_id=rid, status="failed", errors=["synthetic failure"])
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        validation.open_ledger(self.root, EXECUTION_ID).append("analysis_invocation", state.open_session, dict(
            subject="V01", round="1", attempt_index=1, recording_id=rid, invocation_index=1, exit_code=1,
            analysis_runs=[dict(analysis_run_id=run_id, status="failed", manifest_sha256=digest)],
            canonical_analysis_run_id=None, logs={"stdout": {"path": "logs/x", "sha256": "0" * 64},
                                                  "stderr": {"path": "logs/y", "sha256": "0" * 64}},
            environment=analysis_environment()), self.rt.now())
        note = validation.execution_dir(self.root, EXECUTION_ID) / "note.txt"
        note.write_text("operator note", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "failed logged run manifest"):
            validation.analysis_infrastructure_failure(self.rt, EXECUTION_ID, "1", note, run_id)
        with self.assertRaisesRegex(RuntimeError, "not a failed run"):
            validation.analysis_infrastructure_failure(self.rt, EXECUTION_ID, "1", manifest_path, "ar_unknown")
        original = manifest_path.read_bytes()
        manifest_path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(RuntimeError, "logged hash"):
            validation.analysis_infrastructure_failure(self.rt, EXECUTION_ID, "1", manifest_path, run_id)
        manifest_path.write_bytes(original)
        validation.analysis_infrastructure_failure(self.rt, EXECUTION_ID, "1", manifest_path, run_id)
        self.assertTrue(self.state().analysis_invocation_allowed(rid))
        self.assertTrue(report.retry_evidence_integrity(self.root, self.state())["passed"])
        manifest_path.unlink()
        retained = report.retry_evidence_integrity(self.root, self.state())
        self.assertFalse(retained["passed"])
        self.assertEqual(retained["failures"][0]["code"], "ANALYSIS_RETRY_EVIDENCE_MISSING_OR_MISMATCH")


class ReconciliationAndReportTests(OrchestrationCase):
    def run_static_grid(self, failing=()):
        self.session("static-grid")
        for rnd in p8.STATIC_ROUNDS:
            self.attempt(rnd)
            validation.analyze(self.rt, EXECUTION_ID, rnd)
        self.close("static-grid")

    def run_production(self, kind, rnd):
        self.session(kind)
        self.attempt(rnd)
        validation.analyze(self.rt, EXECUTION_ID, rnd)
        self.close(kind)

    def full_execution(self):
        self.run_static_grid()
        self.world.production["121"] = dict(evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                      gate_entry("body_forward", ref=0.75, cur=None)],
                                            verdict="retake")
        self.run_production("body-only-negative", "121")
        self.run_production("E2E", "131")

    def full_passing_execution(self):
        closer = {"below": 0.06, "pass": 0.10, "above": 0.14}
        self.full_execution()
        self.session("forward-gate")
        for rnd in FORWARD_ROUNDS:
            label, band = p8.SLOTS[rnd].designated_phases[0], p8.SLOTS[rnd].band
            ref, cur = 2 * closer[band], closer[band]
            self.world.production[rnd] = dict(evidence=[gate_entry(label, ref=ref, cur=cur)], verdict="retake")
            if rnd == "102":
                self.world.production[rnd] = dict(evidence=[gate_entry(label, ref=0.75, cur=0.63)])
                _, outcome = self.attempt(rnd)
                self.assertEqual(outcome["outcome"], p8.TARGET_MISS)
                self.world.production[rnd] = dict(evidence=[gate_entry(label, ref=ref, cur=cur)])
            self.attempt(rnd)
            validation.analyze(self.rt, EXECUTION_ID, rnd)
        self.close("forward-gate")

    def evaluate(self):
        return report.evaluate_execution(self.root, self.ledger_path, pinhole_factory)

    def test_full_synthetic_execution_without_forward_slots(self):
        self.full_execution()
        self.assertTrue(validation.record_integrity(self.rt, EXECUTION_ID, "closure"))
        reports = self.evaluate()
        execution, metrics_report = reports["execution"], reports["metrics"]
        conditions = execution["computed_conditions"]
        self.assertEqual({k for k, v in conditions.items() if not v},
                         {"P_forward_slots_101_103", "Q_forward_slots_111_113"})
        self.assertEqual(execution["computed_result"], "FAIL")
        self.assertIsNone(execution["formal_initial_seating_range_m"])
        self.assertEqual(execution["static_envelope_m"], (0.6, 1.0))
        self.assertTrue(metrics_report["slot_131"]["passed"], metrics_report["slot_131"])
        self.assertTrue(metrics_report["body_only_negative"]["passed"])
        self.assertTrue(all(r["fail_reason"] == "NOT_EXECUTED" for r in metrics_report["forward_slots"].values()))
        self.assertTrue(reports["reconciliation"]["recording"]["passed"])
        self.assertTrue(reports["reconciliation"]["analysis"]["passed"])
        self.assertEqual(set(execution["external_conditions"].values()), {"EXTERNAL_RECORD_REQUIRED"})
        audit = integrity_check.audit_repository(self.root)
        self.assertEqual(audit.counts["ERROR"], 0, audit.findings)

    def test_full_synthetic_execution_with_forward_slots_exercised(self):
        self.full_passing_execution()
        self.assertTrue(validation.record_integrity(self.rt, EXECUTION_ID, "closure"))
        reports = self.evaluate()
        execution = reports["execution"]
        self.assertEqual(execution["computed_result"], "PASS", {k: v for k, v in
                                                               execution["computed_conditions"].items() if not v})
        self.assertEqual(execution["formal_initial_seating_range_m"], [0.7, 0.8])
        self.assertEqual(reports["metrics"]["forward_slots"]["102"]["canonical_attempt_index"], 2)

    def test_publish_reruns_closure_integrity_after_evidence_mutation(self):
        self.full_passing_execution()
        self.assertTrue(validation.record_integrity(self.rt, EXECUTION_ID, "closure"))
        self.assertEqual(self.evaluate()["execution"]["computed_result"], "PASS")
        rid = self.state().canonical_attempt("131").recording_id
        raw = self.root / "data" / f"{rid}.db3"
        raw.write_bytes(raw.read_bytes() + b"tampered")
        with self.assertRaisesRegex(RuntimeError, "fresh closure integrity failed"):
            validation.evaluate(self.rt, EXECUTION_ID, publish=True)
        self.assertFalse(any((validation.execution_dir(self.root, EXECUTION_ID) / name).exists()
                             for name in report.REPORT_FILES.values()))
        self.assertFalse(self.state().closure_integrity)

    def test_deleted_machine_retry_evidence_fails_patch8_report_integrity(self):
        self.world.production["131"] = dict(crash=True)
        self.world.enumeration = {"probe_ok": True, "devices": []}
        self.session("E2E")
        self.attempt("131")
        state = self.state()
        check = report.retry_evidence_integrity(self.root, state)
        self.assertTrue(check["passed"], check)
        lock = state.attempts[("131", 1)].locked
        evidence = validation.execution_dir(self.root, EXECUTION_ID) / lock["machine_evidence_ref"]["path"]
        evidence.unlink()
        reports = self.evaluate()
        retry = reports["reconciliation"]["retry_evidence_integrity"]
        self.assertFalse(retry["passed"])
        self.assertEqual(retry["failures"][0]["code"], "MACHINE_EVIDENCE_MISSING_OR_HASH_MISMATCH")
        self.assertFalse(reports["execution"]["computed_conditions"]["retry_evidence_integrity"])

    def test_slot131_verdict_not_ok_fails_e2e(self):
        self.world.production["131"] = dict(verdict="ok_with_warnings")
        self.run_production("E2E", "131")
        e2e = self.evaluate()["metrics"]["slot_131"]
        self.assertFalse(e2e["passed"])
        self.assertEqual({k for k, v in e2e["components"].items() if not v}, {"capture_verdict_ok"})

    def test_slot131_missing_artifact_and_unlogged_run_fail(self):
        self.run_production("E2E", "131")
        rid = self.state().canonical_attempt("131").recording_id
        (self.root / "data" / f"{rid}_samples.csv").unlink()
        e2e = self.evaluate()["metrics"]["slot_131"]
        self.assertFalse(e2e["lineage"]["checks"]["samples_sidecar"])
        self.assertFalse(e2e["passed"])
        self.setUp()
        self.run_production("E2E", "131")
        rid = self.state().canonical_attempt("131").recording_id
        with self.world.analysis_patches():                    # an analysis the ledger never saw
            validation.analyze_one(str(self.root / "data" / (rid + ".db3")))
        reports = self.evaluate()
        failures = reports["reconciliation"]["analysis"]["failures"]
        self.assertEqual([f["code"] for f in failures], ["UNLOGGED_COMPLETED_RUN"])
        self.assertFalse(reports["metrics"]["slot_131"]["components"]["analysis_reconciliation"])

    def test_recording_reconciliation_detects_unbound_and_mismatched_recordings(self):
        self.run_production("E2E", "131")
        (self.root / "data" / "V01_r131_stray_camera.json").write_text("{}")
        recordings = self.evaluate()["reconciliation"]["recording"]
        self.assertEqual([(f["recording_id"], f["code"]) for f in recordings["failures"]],
                         [("V01_r131_stray", "NOT_EXACTLY_ONE_ATTEMPT_BINDING")])
        (self.root / "data" / "V01_r131_stray_camera.json").unlink()
        rid = self.state().canonical_attempt("131").recording_id
        camera = self.root / "data" / f"{rid}_camera.json"
        value = json.loads(camera.read_text())
        camera.write_text(json.dumps(dict(value, protocol_version=p8.STATIC_PROTOCOL_VERSION)))
        recordings = self.evaluate()["reconciliation"]["recording"]
        self.assertEqual([f["code"] for f in recordings["failures"]], ["IDENTITY_MISMATCH"])

    def test_recorded_outcome_must_match_evidence(self):
        self.world.production["121"] = dict(evidence=[gate_entry("forward_head", ref=0.75, cur=0.65),
                                                      gate_entry("body_forward", ref=0.75, cur=None)])
        self.run_production("body-only-negative", "121")
        rid = self.state().canonical_attempt("121").recording_id
        quality = self.root / "data" / f"{rid}_quality.json"
        value = json.loads(quality.read_text())
        value["forward_gate_evidence"][1] = gate_entry("body_forward", ref=0.75, cur=0.65)
        quality.write_text(json.dumps(value))
        consistency = self.evaluate()["reconciliation"]["outcome_consistency"]
        self.assertFalse(consistency["passed"])
        self.assertEqual(consistency["mismatches"][0]["derived"], p8.TARGET_MISS)

    def test_report_serialization_is_deterministic_and_publication_is_gated(self):
        self.run_production("E2E", "131")
        first, second = (report.report_bytes(self.evaluate()["execution"]) for _ in range(2))
        self.assertEqual(first, second)
        self.assertNotIn(b"NaN", first)
        self.assertEqual(validation.main(["--root", str(self.root), "evaluate", "--execution-id", EXECUTION_ID,
                                          "--publish"], self.rt), 3)
        self.assertFalse(any((validation.execution_dir(self.root, EXECUTION_ID) / n).exists()
                             for n in report.REPORT_FILES.values()))


class CliAndRepositoryTests(OrchestrationCase):
    def test_formal_commands_refuse_without_registry_and_create_nothing(self):
        for argv in (["open-session", "--session-kind", "static-grid", "--subject", "V01"],
                     ["attempt", "--round", "1"], ["warmup"], ["integrity", "--phase", "pre_hardware"]):
            with self.subTest(argv=argv):
                code = validation.main(["--root", str(self.root), argv[0], "--execution-id", EXECUTION_ID, *argv[1:]],
                                       self.rt)
                self.assertEqual(code, 3)
        self.assertFalse((self.root / "validation").exists())
        self.assertFalse(self.world.launches)

    def test_authorization_gate_rules(self):
        registry = self.root / p8.EXECUTION_REGISTRY_PATH
        registry.parent.mkdir(parents=True)
        registry.write_text(f"execution_id: {EXECUTION_ID}\naudited_implementation_commit: {'c' * 40}\n")
        self.assertEqual(validation.authorization_gate(self.rt, EXECUTION_ID)["audited_implementation_commit"], "c" * 40)
        other = "p8x_20261007T000000000000Z_" + "b" * 32
        with self.assertRaisesRegex(validation.ExecutionNotAuthorized, "not registered"):
            validation.authorization_gate(self.rt, other)
        original = self.world.run

        def diverged(command, **kwargs):
            if command[:2] == ["git", "diff"]:
                return subprocess.CompletedProcess(command, 1, b"", b"")
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, self.dirty, "")
            return original(command, **kwargs)
        self.rt.run, self.dirty = diverged, ""
        with self.assertRaisesRegex(validation.ExecutionNotAuthorized, "non-documentation tree"):
            validation.authorization_gate(self.rt, EXECUTION_ID)
        self.dirty = " M capture_d455.py"
        with self.assertRaisesRegex(validation.ExecutionNotAuthorized, "clean"):
            validation.authorization_gate(self.rt, EXECUTION_ID)

    def test_read_only_cli(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(validation.main(["show-protocol"]), 0)
        protocol = json.loads(buffer.getvalue())
        self.assertEqual(protocol["static_protocol_version"], "patch8-d455-static-validation-v1.0.0")
        for rnd, mode in (("101", "core"), ("102", "core"), ("103", "core"),
                          ("111", "core"), ("112", "core"), ("113", "core"),
                          ("121", "core"), ("131", "full")):
            with self.subTest(rnd=rnd):
                self.assertEqual(protocol["slots"][rnd]["sequence_mode"], mode)
        self.assertEqual(protocol["thresholds"]["depth_sd_mm"], 10.0)

    def test_validation_runtime_is_git_ignored(self):
        self.assertIn("validation/", (REPO / ".gitignore").read_text().splitlines())
        result = subprocess.run(["git", "check-ignore", "-q", "validation/patch8/" + EXECUTION_ID + "/x.jsonl"],
                                cwd=REPO)
        self.assertEqual(result.returncode, 0)

    def test_no_execution_registry_or_formal_runtime_in_repository(self):
        self.assertFalse((REPO / p8.EXECUTION_REGISTRY_PATH).exists())
        self.assertFalse((REPO / "validation").exists())

    def test_production_capture_code_is_launched_unchanged(self):
        rt = make_runtime(self.root, self.world)
        capture = load_capture()
        for rnd, mode in (("101", ["core"]), ("102", ["core"]), ("103", ["core"]),
                          ("111", ["core"]), ("112", ["core"]), ("113", ["core"]),
                          ("121", ["core"]), ("131", [])):
            command = validation.child_command(rt, p8.SLOTS[rnd], "V01")
            self.assertEqual(command, ["python-under-test", str(self.root / "capture_d455.py"), "V01", rnd, *mode,
                                       "--dataset-role", "pilot"])
            # The unchanged production CLI selects SEQ_FULL when mode is omitted.
            self.assertEqual(capture.parse_capture_args(command[2:]).mode, "core" if mode else None)
        static = validation.child_command(rt, p8.SLOTS["7"], "V01")
        self.assertEqual(Path(static[1]).name, "patch8_static_capture.py")
        self.assertNotIn("core", static)


if __name__ == "__main__":
    unittest.main()
