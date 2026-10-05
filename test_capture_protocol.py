"""Protocol checks without a camera, GUI, or RealSense installation."""
import ast
import builtins
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SOURCE_PATH = Path(__file__).with_name("capture_d455.py")
SOURCE = SOURCE_PATH.read_text()
TREE = ast.parse(SOURCE)


def load_capture():
    cv2 = types.ModuleType("cv2")
    cv2.data = types.SimpleNamespace(haarcascades="")
    cv2.CascadeClassifier = lambda path: None
    spec = importlib.util.spec_from_file_location("capture_protocol_under_test", SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    import_module = builtins.__import__
    hardware = {"cv2": cv2, "pyrealsense2": types.ModuleType("pyrealsense2")}

    def without_hardware(name, *args, **kwargs):
        return hardware[name] if name in hardware else import_module(name, *args, **kwargs)

    # Only replace hardware imports; preserve the shared NumPy module cache.
    with patch("builtins.__import__", side_effect=without_hardware):
        spec.loader.exec_module(module)
    return module


capture = load_capture()


def live_display_state(label, closer, reference=0.75, sample_count=10,
                       reference_mode="face", mode="face", sample_modes=None, sample_distances=None):
    # Execute the actual UI decision block, without the surrounding camera loop.
    record = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "record_phase")
    loop = next(node for node in ast.walk(record) if isinstance(node, ast.While))
    start = next(i for i, node in enumerate(loop.body)
                 if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "(name, how, name_en)")
    end = next(i for i, node in enumerate(loop.body)
               if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "dtxt")
    code = compile(ast.Module(body=loop.body[start:end], type_ignores=[]), str(SOURCE_PATH), "exec")
    distance = 0.75 - closer
    sample_modes = sample_modes if sample_modes is not None else [mode] * sample_count
    sample_distances = sample_distances if sample_distances is not None else [distance] * sample_count
    namespace = dict(vars(capture), ph={"key": label, "kind": "hold", "dur": 10},
                     ph_i=1, t_in=4, dist=distance, mode=mode,
                     ref_up={"dist": reference, "cx": 0.5,
                             "face_dist": reference if reference_mode == "face" else None},
                     samples=[dict(phase_idx=1, t=2 + i / 10, distance_m=d, face_cx=0.5, mode=m)
                              for i, (m, d) in enumerate(zip(sample_modes, sample_distances))])
    exec(code, namespace)
    return namespace


def final_quality(label, closer, reference_mode="face", current_mode="face",
                  reference_values=None, current_values=None):
    phases = [dict(step=1, kind="hold", key="upright", dur=10),
              dict(step=2, kind="hold", key=label, dur=10)]
    values = [reference_values if reference_values is not None else [(reference_mode, 0.75)] * 5,
              current_values if current_values is not None else [(current_mode, 0.75 - closer)] * 5]
    samples = [dict(phase_idx=i, t=2 + j / 10, distance_m=distance, face_cx=0.5,
                    mode=mode, face_area_px=100, face_size_cm2=100)
               for i, phase_values in enumerate(values) for j, (mode, distance) in enumerate(phase_values)]
    return capture.quality_check(phases, samples, False)


class CaptureProtocolTests(unittest.TestCase):
    def assert_distance(self, closer, expected):
        self.assertEqual(capture.evaluate_forward_distance(closer), expected)
        for label in ("forward_head", "body_forward"):
            with self.subTest(label=label, closer=closer):
                state = live_display_state(label, closer)
                fails, _, _ = final_quality(label, closer)
                self.assertEqual(state["col"], capture.C_GREEN if expected == "ok" else capture.C_RED)
                self.assertEqual(len(fails), 0 if expected == "ok" else 1)
                if expected != "ok":
                    self.assertIn(f"얼굴 전방 이동 {closer * 100:.1f}cm", fails[0])
                    self.assertIn("목표 8~12cm", fails[0])
                    self.assertIn("더 앞으로" if expected == "too_little" else "조금 뒤로", state["sub"])
                self.assertIn("8~12cm", state["msg_en"])

    def test_a_below_target(self):
        self.assert_distance(0.079, "too_little")

    def test_b_lower_boundary(self):
        self.assert_distance(0.080, "ok")

    def test_c_inside_target(self):
        self.assert_distance(0.100, "ok")

    def test_d_upper_boundary(self):
        self.assert_distance(0.120, "ok")

    def test_e_over_target(self):
        self.assert_distance(0.121, "too_much")

    def test_f_shared_constants_control_both_paths(self):
        self.assertEqual((capture.FWD_TARGET_MIN_M, capture.FWD_TARGET_MAX_M), (0.08, 0.12))
        # Changing only the constants changes both actual live and final decisions.
        with patch.object(capture, "FWD_TARGET_MIN_M", 0.09), patch.object(capture, "FWD_TARGET_MAX_M", 0.11):
            for closer in (0.08, 0.12):
                for label in ("forward_head", "body_forward"):
                    self.assertEqual(live_display_state(label, closer)["col"], capture.C_RED)
                    self.assertEqual(len(final_quality(label, closer)[0]), 1)

    def test_g_old_forward_thresholds_removed(self):
        self.assertNotIn("LIVE_FWD_M", SOURCE)
        for closer in (0.015, 0.04):
            self.assert_distance(closer, "too_little")
        for node in ast.walk(TREE):
            if isinstance(node, ast.If) and "forward_head" in ast.unparse(node.test):
                for descendant in ast.walk(node):
                    if isinstance(descendant, ast.Constant) and isinstance(descendant.value, float):
                        self.assertNotIn(descendant.value, (0.04, 0.015))

    def test_instructions_distinguish_head_and_body(self):
        head = capture.POSTURES["forward_head"][1]
        body = capture.POSTURES["body_forward"][1]
        for text in (head, body):
            self.assertIn(capture.FWD_TARGET_TEXT, text)
        self.assertNotIn("턱만 앞으로", head)
        for text in ("등·어깨 고정", "정면 시선", "고개 각도 유지", "머리 전체", "수평"):
            self.assertIn(text, head)
        self.assertIn("등·어깨 포함 상체 전체", body)
        self.assertIn("머리만 말고", body)

    def test_unmeasured_forward_distance_is_not_green(self):
        for label in ("forward_head", "body_forward"):
            self.assertEqual(live_display_state(label, 0.1, reference=None)["col"], capture.C_RED)
            self.assertEqual(live_display_state(label, 0.1, sample_count=2)["col"], capture.C_RED)

    def test_backward_warning_unchanged(self):
        fails, warns, _ = final_quality("lean_back", -0.01)
        self.assertEqual(fails, [])
        self.assertTrue(any("뒤로 거의 이동하지 않음" in warning for warning in warns))


class FaceOnlyForwardTests(unittest.TestCase):
    def test_face_10cm_passes(self):
        for label in ("forward_head", "body_forward"):
            self.assertEqual(final_quality(label, 0.10)[0], [])
            self.assertEqual(live_display_state(label, 0.10)["col"], capture.C_GREEN)

    def test_body_only_10cm_cannot_pass(self):
        for label in ("forward_head", "body_forward"):
            fails, _, _ = final_quality(label, 0.10, "body", "body")
            self.assertTrue(any("얼굴 거리 측정 샘플 부족" in message for message in fails))
            state = live_display_state(label, 0.10, reference_mode="body", mode="body")
            self.assertEqual(state["col"], capture.C_RED)
            self.assertIn("얼굴 거리 측정 필요", state["sub"])

    def test_mixed_sources_cannot_pass(self):
        for label in ("forward_head", "body_forward"):
            for reference_mode, current_mode in (("face", "body"), ("body", "face")):
                with self.subTest(label=label, reference=reference_mode, current=current_mode):
                    self.assertTrue(final_quality(label, 0.10, reference_mode, current_mode)[0])
                    state = live_display_state(label, 0.10, reference_mode=reference_mode, mode=current_mode)
                    self.assertEqual(state["col"], capture.C_RED)

    def test_face_7cm_fails(self):
        for label in ("forward_head", "body_forward"):
            self.assertIn("7.0cm", final_quality(label, 0.07)[0][0])
            self.assertIn("더 앞으로", live_display_state(label, 0.07)["sub"])

    def test_face_13cm_fails(self):
        for label in ("forward_head", "body_forward"):
            self.assertIn("13.0cm", final_quality(label, 0.13)[0][0])
            self.assertIn("조금 뒤로", live_display_state(label, 0.13)["sub"])

    def test_general_body_fallback_preserved(self):
        with patch.object(capture, "face_distance", return_value=(None, None)), \
                patch.object(capture, "body_distance", return_value=0.65) as body:
            self.assertEqual(capture.measure_distance(None, None, 0.001), (0.65, None, "body"))
            body.assert_called_once_with(None, 0.001)

    def test_existing_face_rate_threshold_reused(self):
        sparse = [("face", 0.65)] * 4 + [("body", 0.65)] * 6
        enough = [("face", 0.65)] * 5 + [("body", 0.65)] * 5
        for label in ("forward_head", "body_forward"):
            self.assertTrue(final_quality(label, 0.1, current_values=sparse)[0])
            self.assertEqual(final_quality(label, 0.1, current_values=enough)[0], [])
            self.assertTrue(final_quality(label, 0.1,
                                         reference_values=[(m, 0.75) for m, _ in sparse])[0])
            state = live_display_state(label, 0.1, sample_modes=[m for m, _ in sparse])
            self.assertEqual(state["col"], capture.C_RED)

    def test_medians_exclude_body_values(self):
        for label in ("forward_head", "body_forward"):
            # All-distance reference median is .78, but face-only reference is .75.
            ref = [("face", 0.75)] * 5 + [("body", 0.81)] * 5
            self.assertEqual(final_quality(label, 0.1, reference_values=ref)[0], [])
            # Mixed current median .66 would pass; face-only .68 must fail (7cm).
            current = [("face", 0.68)] * 5 + [("body", 0.64)] * 5
            self.assertIn("7.0cm", final_quality(label, 0.07, current_values=current)[0][0])
            state = live_display_state(label, 0.07, sample_modes=[m for m, _ in current],
                                       sample_distances=[d for _, d in current])
            self.assertIn("더 앞으로", state["sub"])

    def test_current_body_mode_cannot_use_recent_face_history(self):
        for label in ("forward_head", "body_forward"):
            state = live_display_state(label, 0.1, mode="body", sample_modes=["face"] * 9 + ["body"])
            self.assertEqual(state["col"], capture.C_RED)
            self.assertIn("얼굴 거리 측정 필요", state["sub"])

    def test_none_face_depth_and_missing_reference_fail(self):
        for label in ("forward_head", "body_forward"):
            for reference, current in (([("face", None)] * 5, [("face", 0.65)] * 5),
                                       ([("face", 0.75)] * 5, [("face", None)] * 5),
                                       ([], [("face", 0.65)] * 5)):
                fails = final_quality(label, 0.1, reference_values=reference, current_values=current)[0]
                self.assertTrue(any("얼굴 거리 측정 샘플 부족" in message for message in fails))

    def test_final_does_not_skip_invalid_latest_upright(self):
        for label in ("forward_head", "body_forward"):
            phases = [dict(step=i + 1, kind="hold", key=key, dur=10)
                      for i, key in enumerate(("upright", "upright", label))]
            samples = [dict(phase_idx=i, t=t, distance_m=d, mode=m, face_cx=0.5,
                            face_area_px=100, face_size_cm2=100)
                       for i, (m, d) in enumerate((("face", 0.75), ("body", 0.75), ("face", 0.65)))
                       for t in (2, 3, 4, 5, 6)]
            fails = capture.quality_check(phases, samples, False)[0]
            self.assertTrue(any("기준 정상 자세" in message for message in fails))

    def test_live_reference_uses_faces_and_clears_stale_value(self):
        record = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "record_phase")
        update = next(n for n in ast.walk(record) if isinstance(n, ast.Assign)
                      and ast.unparse(n.targets[0]) == "ref_up['face_dist']")
        code = compile(ast.Module(body=[update], type_ignores=[]), str(SOURCE_PATH), "exec")
        values = [("face", 0.75)] * 5 + [("body", 0.81)] * 5
        samples = [dict(phase_idx=1, t=2, distance_m=d, mode=m) for m, d in values]
        namespace = dict(vars(capture), samples=samples, ph_i=1, ref_up={"face_dist": 0.9})
        exec(code, namespace)
        self.assertEqual(namespace["ref_up"]["face_dist"], 0.75)
        namespace["samples"] = [dict(s, mode="body") for s in samples]
        exec(code, namespace)
        self.assertIsNone(namespace["ref_up"]["face_dist"])


class CaptureProvenanceTests(unittest.TestCase):
    def setUp(self):
        def git_result(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "a" * 40 if "rev-parse" in command else "", "")
        self.git = patch.object(capture.subprocess, "run", side_effect=git_result).start()
        self.addCleanup(patch.stopall)

    def test_new_attempts_have_unique_ids_even_at_same_time(self):
        with patch.object(capture, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 1, 14, 30, 25, 123456, tzinfo=timezone.utc)
            ids = [capture.capture_provenance("P03", "1", "pilot")["recording_id"] for _ in range(20)]
        self.assertEqual(len(set(ids)), 20)
        for recording_id in ids:
            self.assertRegex(recording_id, r"^P03_r1_20261001_143025_123456_[0-9a-f]{32}$")

    def test_identity_and_seoul_timestamp(self):
        info = capture.capture_provenance("P03-test", "2", "pilot")
        self.assertRegex(info["recording_id"], r"^P03-test_r2_[0-9]{8}_[0-9]{6}_[0-9]{6}_[0-9a-f]{32}$")
        started = datetime.fromisoformat(info["capture_start_time_iso"])
        self.assertEqual(started.utcoffset().total_seconds(), 9 * 3600)
        self.assertEqual(info["capture_start_time"], info["capture_start_time_iso"])
        self.assertEqual(info["capture_timezone"], "Asia/Seoul")
        self.assertEqual(info["start_time"], started.strftime("%Y%m%d_%H%M%S"))

    def test_dataset_roles_are_explicit_and_valid(self):
        for role in ("pilot", "formal", "external"):
            args = capture.parse_capture_args(["P03", "1", "core", "--dataset-role", role])
            self.assertEqual(args.dataset_role, role)
            self.assertEqual(args.mode, "core")
            self.assertEqual(capture.capture_provenance("P03", "1", role)["dataset_role"], role)
        self.assertIsNone(capture.parse_capture_args(["P03", "1", "--dataset-role", "pilot"]).mode)

    def test_missing_or_invalid_role_is_rejected(self):
        for args in (["P03", "1"], ["P03", "1", "--dataset-role", "automatic"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                capture.parse_capture_args(args)
            self.assertEqual(error.exception.code, 2)
        for role in (None, "automatic", "FORMAL", ""):
            with self.assertRaises(ValueError):
                capture.capture_provenance("P03", "1", role)

    def test_unsafe_subject_and_invalid_round_rejected(self):
        for subject, rnd in (("../P03", "1"), ("P03_test", "1"), ("P03/4", "1"),
                             ("", "1"), ("P03", "0"), ("P03", "-1"), ("P03", "1/2")):
            with self.subTest(subject=subject, rnd=rnd), self.assertRaises(ValueError):
                capture.capture_provenance(subject, rnd, "pilot")

    def test_new_capture_accepts_canonical_round_strings(self):
        for rnd in ("1", "2", "9", "10", "100"):
            with self.subTest(round=rnd):
                args = capture.parse_capture_args(["P03", rnd, "--dataset-role", "pilot"])
                info = capture.capture_provenance(args.subject, args.round, args.dataset_role)
                self.assertEqual(args.round, rnd)
                self.assertEqual(info["round"], rnd)
                self.assertTrue(info["recording_id"].startswith(f"P03_r{rnd}_"))

    def test_new_capture_rejects_noncanonical_round_before_identity_or_files(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(capture.uuid, "uuid4", side_effect=AssertionError("must not generate identity")) as new_id:
            destination = Path(directory) / "new_capture"
            for rnd in ("01", "001", "0", "00", "+1", "-1", "1.0", " 1", "1 ", "1\n", "１", "", 1, True, None):
                with self.subTest(round=rnd), self.assertRaisesRegex(ValueError, "round"):
                    capture.reserve_capture("P03", rnd, "pilot", directory=destination)
                self.assertFalse(destination.exists())
            new_id.assert_not_called()

    def test_new_capture_invocation_rejects_leading_zero_before_capture(self):
        with patch("sys.argv", ["capture_d455.py", "P03", "01", "--dataset-role", "pilot"]), \
                patch.object(capture, "capture_provenance") as provenance, \
                patch.object(capture, "guide_phase") as guide, \
                patch.object(capture, "record_phase") as record, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                capture.main()
            self.assertEqual(error.exception.code, 2)
            provenance.assert_not_called()
            guide.assert_not_called()
            record.assert_not_called()

    def test_protocol_and_gate_metadata_use_constants(self):
        info = capture.capture_provenance("P03", "1", "formal")
        self.assertEqual(info["protocol_version"], "capture-forward-face-v2.0.0")
        self.assertEqual(info["forward_validation_source"], "face_only")
        self.assertEqual(info["forward_target_min_m"], capture.FWD_TARGET_MIN_M)
        self.assertEqual(info["forward_target_max_m"], capture.FWD_TARGET_MAX_M)
        with patch.object(capture, "FWD_TARGET_MIN_M", 0.09), patch.object(capture, "FWD_TARGET_MAX_M", 0.11):
            changed = capture.capture_provenance("P03", "1", "formal")
        self.assertEqual((changed["forward_target_min_m"], changed["forward_target_max_m"]), (0.09, 0.11))

    def test_git_head_and_dirty_from_script_repository(self):
        info = capture.capture_provenance("P03", "1", "pilot")
        self.assertEqual(info["git_commit"], "a" * 40)
        self.assertIs(info["git_dirty"], False)
        self.assertEqual(info["provenance_unknown_reasons"], {})
        head_call = self.git.call_args_list[0]
        self.assertEqual(head_call.args[0], ["git", "rev-parse", "HEAD"])
        self.assertEqual(head_call.kwargs["cwd"], str(SOURCE_PATH.parent))
        self.assertGreater(head_call.kwargs["timeout"], 0)
        self.git.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "a" * 40 if "rev-parse" in command else " M capture_d455.py", "")
        self.assertIs(capture.capture_provenance("P03", "1", "pilot")["git_dirty"], True)

    def test_git_unavailable_does_not_block_metadata(self):
        for failure in (FileNotFoundError("git unavailable"), subprocess.CalledProcessError(128, "git"),
                        subprocess.TimeoutExpired("git", 3)):
            self.git.side_effect = failure
            warning = io.StringIO()
            with redirect_stderr(warning):
                info = capture.capture_provenance("P03", "1", "pilot")
            self.assertIsNone(info["git_commit"])
            self.assertIsNone(info["git_dirty"])
            self.assertIn("git_commit", info["provenance_unknown_reasons"])
            self.assertIn("[경고]", warning.getvalue())
            self.assertIsNotNone(info["capture_script_sha256"])

    def test_script_sha256_matches_binary_file(self):
        info = capture.capture_provenance("P03", "1", "pilot")
        self.assertEqual(info["capture_script_sha256"], hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest())

    def test_script_hash_failure_does_not_block_metadata(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(capture, "__file__", os.path.join(directory, "missing.py")), \
                redirect_stderr(io.StringIO()) as warning:
            info = capture.capture_provenance("P03", "1", "pilot")
        self.assertIsNone(info["capture_script_sha256"])
        self.assertIn("capture_script_sha256", info["provenance_unknown_reasons"])
        self.assertIn("[경고]", warning.getvalue())

    def test_collision_reservation_preserves_existing_artifacts(self):
        # Same candidate ID, first occupied by raw, then by a metadata reservation.
        with tempfile.TemporaryDirectory() as directory, patch.object(capture, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 1, 14, 30, 25, 123456, tzinfo=timezone.utc)
            prefix = "P03_r1_20261001_143025_123456_"
            raw = Path(directory, prefix + "a" * 32 + ".db3")
            raw.write_bytes(b"existing recording")
            with patch.object(capture.uuid, "uuid4", side_effect=[types.SimpleNamespace(hex=x * 32)
                                                                 for x in ("a", "b", "b", "c")]):
                base1, info1 = capture.reserve_capture("P03", "1", "pilot", directory)
                saved = Path(base1 + "_camera.json").read_bytes()
                base2, info2 = capture.reserve_capture("P03", "1", "pilot", directory)
            self.assertNotEqual(info1["recording_id"], info2["recording_id"])
            self.assertEqual(raw.read_bytes(), b"existing recording")
            self.assertEqual(Path(base1 + "_camera.json").read_bytes(), saved)
            self.assertEqual(json.loads(Path(base2 + "_camera.json").read_text())["recording_id"],
                             info2["recording_id"])
            self.assertIsNone(info2["record_file"])

    def test_exclusive_reservation_retries_a_concurrent_collision(self):
        real_open = builtins.open
        collisions = []
        def racing_open(path, mode="r", *args, **kwargs):
            if mode == "x" and not collisions:
                collisions.append(path)
                with real_open(path, mode, *args, **kwargs) as f:
                    f.write("other process reservation")
                raise FileExistsError(path)
            return real_open(path, mode, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch("builtins.open", side_effect=racing_open):
            base, _ = capture.reserve_capture("P03", "1", "pilot", directory)
            self.assertNotEqual(base + "_camera.json", collisions[0])
            self.assertEqual(Path(collisions[0]).read_text(), "other process reservation")

    def test_failed_start_keeps_attempt_reservation(self):
        reserve = capture.reserve_capture
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(capture, "reserve_capture", side_effect=lambda s, r, role:
                                            reserve(s, r, role, directory)))
            pipe = Mock()
            pipe.start.side_effect = RuntimeError("camera unavailable")
            stack.enter_context(patch.object(capture.rs, "pipeline", return_value=pipe, create=True))
            config = stack.enter_context(patch.object(capture, "make_config", side_effect=lambda path: path))
            stack.enter_context(redirect_stdout(io.StringIO()))
            with self.assertRaises(RuntimeError):
                capture.record_phase("P03", "1", None, capture.SEQ_CORE, "pilot")
            files = list(Path(directory).glob("*_camera.json"))
            self.assertEqual(len(files), 1)
            info = json.loads(files[0].read_text())
            self.assertIsNone(info["record_file"])
            self.assertEqual([Path(call.args[0]).stem for call in config.call_args_list],
                             [info["recording_id"]] * 2)

    def test_recording_sidecars_and_existing_reader_compatibility(self):
        # Run the real recording/writer/report paths with three fake camera frames.
        reserve = capture.reserve_capture
        intr = types.SimpleNamespace(width=1280, height=720, fx=600, fy=600,
                                     ppx=640, ppy=360, model="test", coeffs=[0] * 5)
        depth_intr = types.SimpleNamespace(**dict(vars(intr), width=848, height=480))
        cs, ds = Mock(), Mock()
        cs.as_video_stream_profile.return_value = cs
        ds.as_video_stream_profile.return_value = ds
        cs.get_intrinsics.return_value = intr
        ds.get_intrinsics.return_value = depth_intr
        ds.get_extrinsics_to.return_value = types.SimpleNamespace(rotation=[1] * 9, translation=[0] * 3)
        dev = Mock()
        dev.first_depth_sensor.return_value.get_depth_scale.return_value = 0.001
        dev.first_depth_sensor.return_value.get_option.return_value = 95
        dev.get_info.side_effect = lambda key: {"name": "D455-test", "serial_number": "test-serial",
                                               "firmware_version": "test-fw", "usb_type_descriptor": "3.2"}[key]
        profile = Mock()
        profile.get_device.return_value = dev
        profile.get_stream.side_effect = lambda key: cs if key == "color" else ds
        pipe, frames = Mock(), Mock()
        pipe.start.side_effect = [RuntimeError("db3 unsupported"), profile]
        pipe.wait_for_frames.return_value = frames
        frames.get_color_frame.return_value.get_data.return_value = capture.np.zeros((4, 4, 3), dtype="uint8")
        frames.get_color_frame.return_value.get_frame_number.return_value = 7
        frames.get_timestamp.return_value = 1234.5
        rs = Mock()
        rs.pipeline.return_value = pipe
        rs.stream = types.SimpleNamespace(color="color", depth="depth")
        rs.format = types.SimpleNamespace(bgr8="bgr8", z16="z16")
        rs.camera_info = types.SimpleNamespace(**{x: x for x in (
            "name", "serial_number", "firmware_version", "usb_type_descriptor")})
        rs.align.return_value.process.return_value.get_depth_frame.return_value.get_data.return_value = \
            capture.np.zeros((4, 4), dtype="uint16")
        start_info = {"distance_m": 0.75, "mode": "face"}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            reservation = stack.enter_context(patch.object(capture, "reserve_capture", side_effect=lambda s, r, role:
                                                          reserve(s, r, role, directory)))
            stack.enter_context(patch.object(capture, "rs", rs))
            stack.enter_context(patch.object(capture, "measure_distance", return_value=(0.75, (0, 0, 2, 2), "face")))
            stack.enter_context(patch.object(capture, "make_display"))
            stack.enter_context(patch.object(capture, "beep"))
            stack.enter_context(patch.object(capture.cv2, "imshow", create=True))
            stack.enter_context(patch.object(capture.cv2, "waitKey", side_effect=[-1, -1, ord("q")], create=True))
            stack.enter_context(redirect_stdout(io.StringIO()))
            result = capture.record_phase("P03", "1", start_info, capture.SEQ_CORE, "pilot")
            base, rec_file, phases, samples, aborted, _, provenance = result
            reservation.assert_called_once_with("P03", "1", "pilot")
            recording_id = provenance["recording_id"]
            self.assertEqual(Path(base).name, recording_id)
            self.assertEqual(Path(rec_file).suffix, ".bag")
            self.assertEqual([c.args[0] for c in rs.config.return_value.enable_record_to_file.call_args_list],
                             [base + ".db3", base + ".bag"])
            streams = [c.args for c in rs.config.return_value.enable_stream.call_args_list]
            self.assertEqual(streams, [("depth", 848, 480, "z16", 15),
                                       ("color", 1280, 720, "bgr8", 15)] * 2)
            camera = json.loads(Path(base + "_camera.json").read_text())
            expected_old = {
                "subject": "P03", "round": "1", "start_time": provenance["start_time"],
                "record_file": recording_id + ".bag", "start_distance": start_info,
                "target_range_m": [0.70, 0.80], "fps": 15,
                "sequence": [list(p) for p in capture.SEQ_CORE], "prep_sec": 4,
                "device": "D455-test", "serial": "test-serial", "firmware": "test-fw", "usb": "3.2",
                "depth_scale_m": 0.001, "color_intrinsics": capture.intr_to_dict(intr),
                "depth_intrinsics": capture.intr_to_dict(depth_intr),
                "depth_to_color_extrinsics": {"rotation": [1] * 9, "translation": [0] * 3},
                "stereo_baseline_mm": 95,
            }
            self.assertEqual({k: camera[k] for k in expected_old}, expected_old)
            self.assertEqual(camera["recording_id"], recording_id)
            self.assertEqual(camera["protocol_version"], capture.PROTOCOL_VERSION)
            for kind in ("markers", "samples"):
                with open(base + f"_{kind}.csv", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    data = list(reader)
                    self.assertEqual(reader.fieldnames[-1], "recording_id")
                    expected_columns = (
                        ["wall_time", "frame_timestamp_ms", "color_frame_number", "step", "phase", "label",
                         "planned_sec", "distance_m", "distance_mode"] if kind == "markers" else
                        ["phase_idx", "step", "phase", "label", "t", "distance_m", "mode", "face_cx",
                         "face_w_px", "face_h_px", "face_area_px", "face_size_cm2"])
                    self.assertEqual(reader.fieldnames[:-1], expected_columns)
                self.assertTrue(data)
                self.assertTrue(all(row["recording_id"] == recording_id for row in data))
            self.assertEqual(samples[0]["distance_m"], 0.75)
            self.assertEqual(samples[0]["face_area_px"], 4)
            self.assertEqual(samples[0]["face_size_cm2"], 4 * 0.75 ** 2 / 600 ** 2 * 1e4)
            stack.enter_context(patch.object(capture, "count_frames", return_value=(15, 15)))
            capture.report("P03", "1", base, rec_file, phases, samples, aborted, 1.0, provenance)
            quality = json.loads(Path(base + "_quality.json").read_text())
            self.assertEqual(quality["recording_id"], recording_id)
            self.assertEqual(quality["fails"], capture.quality_check(phases, samples, aborted)[0])
            self.assertEqual(quality["verdict"], "retake")
            for kind, filename in camera["sidecar_files"].items():
                self.assertEqual(filename, Path(base + f"_{kind}." + ("csv" if kind in ("markers", "samples") else "json")).name)
                self.assertTrue(Path(directory, filename).exists())

            # Execute unchanged reader functions without importing analysis hardware/models.
            analysis_tree = ast.parse(SOURCE_PATH.with_name("analyze_d455.py").read_text())
            functions = [n for n in analysis_tree.body if isinstance(n, ast.FunctionDef)
                         and n.name in ("parse_name", "load_markers")]
            namespace = {"os": os, "csv": csv}
            exec(compile(ast.Module(body=functions, type_ignores=[]), "analysis_readers", "exec"), namespace)
            self.assertEqual(namespace["parse_name"](rec_file), ("P03", "1"))
            self.assertEqual(namespace["load_markers"](rec_file),
                             [{"ts": 1234.5, "label": "transition", "phase": "prep", "step": "1"}])


class ForwardGateEvidenceTests(unittest.TestCase):
    def inputs(self, label="forward_head", current=0.65, reference_values=None, current_values=None):
        phases = [dict(step=1, kind="hold", key="upright", dur=10),
                  dict(step=2, kind="hold", key=label, dur=10)]
        values = [reference_values if reference_values is not None else [("face", 0.75)] * 5,
                  current_values if current_values is not None else [("face", current)] * 5]
        samples = [dict(phase_idx=i, t=2 + j / 10, distance_m=d, mode=m, face_cx=0.5,
                        face_area_px=100, face_size_cm2=100)
                   for i, items in enumerate(values) for j, (m, d) in enumerate(items)]
        return phases, samples

    def evidence(self, **kwargs):
        phases, samples = self.inputs(**kwargs)
        fails, _, _, evidence = capture.quality_check(phases, samples, False, include_evidence=True)
        self.assertEqual(len(evidence), 1)
        return fails, evidence[0]

    def test_face_10cm_pass_evidence(self):
        for label in ("forward_head", "body_forward"):
            fails, ev = self.evidence(label=label)
            self.assertEqual(fails, [])
            self.assertEqual((ev["step"], ev["label"], ev["phase_idx"]), (2, label, 1))
            self.assertEqual((ev["reference_step"], ev["reference_label"], ev["reference_phase_idx"]),
                             (1, "upright", 0))
            self.assertEqual(ev["reference_face_median_m"], 0.75)
            self.assertEqual(ev["current_face_median_m"], 0.65)
            self.assertAlmostEqual(ev["closer_m"], 0.10)
            self.assertEqual(ev["forward_target_min_m"], capture.FWD_TARGET_MIN_M)
            self.assertEqual(ev["forward_target_max_m"], capture.FWD_TARGET_MAX_M)
            self.assertEqual(ev["forward_validation_source"], "face_only")
            self.assertEqual(ev["forward_gate_result"], "pass")
            self.assertEqual(ev["forward_gate_reasons"], [])
            for prefix in ("reference", "current"):
                self.assertEqual(ev[prefix + "_total_samples"], 5)
                self.assertEqual(ev[prefix + "_valid_face_samples"], 5)
                self.assertEqual(ev[prefix + "_valid_face_fraction"], 1.0)

    def test_face_7cm_below_target_evidence(self):
        fails, ev = self.evidence(current=0.68)
        self.assertTrue(fails)
        self.assertAlmostEqual(ev["closer_m"], 0.07)
        self.assertEqual(ev["forward_gate_result"], "fail")
        self.assertEqual(ev["forward_gate_reasons"], ["below_target"])

    def test_face_13cm_above_target_evidence(self):
        fails, ev = self.evidence(current=0.62)
        self.assertTrue(fails)
        self.assertAlmostEqual(ev["closer_m"], 0.13)
        self.assertEqual(ev["forward_gate_result"], "fail")
        self.assertEqual(ev["forward_gate_reasons"], ["above_target"])

    def test_both_boundaries_still_pass(self):
        for current in (0.67, 0.63):
            fails, ev = self.evidence(current=current)
            self.assertEqual(fails, [])
            self.assertEqual(ev["forward_gate_result"], "pass")
            self.assertEqual(ev["forward_gate_reasons"], [])

    def test_body_only_cannot_supply_face_evidence(self):
        fails, ev = self.evidence(reference_values=[("body", 0.75)] * 5,
                                  current_values=[("body", 0.65)] * 5)
        self.assertTrue(fails)
        self.assertEqual(ev["forward_gate_result"], "fail")
        self.assertEqual(ev["forward_gate_reasons"],
                         ["insufficient_reference_face_samples", "insufficient_current_face_samples"])
        self.assertIsNone(ev["closer_m"])
        for prefix in ("reference", "current"):
            self.assertIsNone(ev[prefix + "_face_median_m"])
            self.assertEqual(ev[prefix + "_total_samples"], 5)
            self.assertEqual(ev[prefix + "_valid_face_samples"], 0)
            self.assertEqual(ev[prefix + "_valid_face_fraction"], 0.0)

    def test_mixed_source_fail_evidence(self):
        for prefix, distance in (("reference", 0.75), ("current", 0.65)):
            fails, ev = self.evidence(**{prefix + "_values": [("body", distance)] * 5})
            self.assertTrue(fails)
            self.assertEqual(ev["forward_gate_result"], "fail")
            self.assertEqual(ev["forward_gate_reasons"], [f"insufficient_{prefix}_face_samples"])
            self.assertIsNone(ev[prefix + "_face_median_m"])
            self.assertIsNone(ev["closer_m"])

    def test_reference_valid_ratio_shortage(self):
        fails, ev = self.evidence(reference_values=[("face", 0.75)] * 4 + [("body", 0.75)] * 6)
        self.assertTrue(fails)
        self.assertEqual(ev["reference_total_samples"], 10)
        self.assertEqual(ev["reference_valid_face_samples"], 4)
        self.assertEqual(ev["reference_valid_face_fraction"], 0.4)
        self.assertIsNone(ev["reference_face_median_m"])
        self.assertEqual(ev["current_face_median_m"], 0.65)
        self.assertEqual(ev["forward_gate_reasons"], ["insufficient_reference_face_samples"])

    def test_current_valid_ratio_shortage_including_none_depth(self):
        fails, ev = self.evidence(current_values=[("face", 0.65)] * 4 + [("face", None)] * 6)
        self.assertTrue(fails)
        self.assertEqual(ev["current_total_samples"], 10)
        self.assertEqual(ev["current_valid_face_samples"], 4)
        self.assertEqual(ev["current_valid_face_fraction"], 0.4)
        self.assertIsNone(ev["current_face_median_m"])
        self.assertEqual(ev["forward_gate_reasons"], ["insufficient_current_face_samples"])
        # Existing face_ratio counts mode only and must remain distinct from valid fraction.
        phases, samples = self.inputs(current_values=[("face", 0.65)] * 4 + [("face", None)] * 6)
        rows = capture.quality_check(phases, samples, False)[2]
        self.assertEqual(rows[1][4], 1.0)

    def test_exactly_half_valid_uses_face_medians_only(self):
        fails, ev = self.evidence(reference_values=[("face", 0.75)] * 5 + [("body", 0.81)] * 5,
                                  current_values=[("face", 0.65)] * 5 + [("body", 0.69)] * 5)
        self.assertEqual(fails, [])
        self.assertEqual(ev["reference_face_median_m"], 0.75)
        self.assertEqual(ev["current_face_median_m"], 0.65)
        self.assertEqual(ev["reference_valid_face_fraction"], 0.5)
        self.assertEqual(ev["current_valid_face_fraction"], 0.5)
        self.assertEqual(ev["forward_gate_result"], "pass")

    def test_missing_reference_has_null_identity_and_zero_counts(self):
        phases, samples = self.inputs()
        phases[0]["kind"] = "prep"  # An upright prep must not become a hold reference.
        fails, _, _, evidence = capture.quality_check(phases, samples, False, include_evidence=True)
        ev = evidence[0]
        self.assertTrue(fails)
        self.assertEqual(ev["forward_gate_reasons"], ["missing_reference"])
        for field in ("reference_step", "reference_phase_idx", "reference_label", "reference_face_median_m",
                      "reference_valid_face_fraction", "closer_m"):
            self.assertIsNone(ev[field])
        self.assertEqual(ev["reference_total_samples"], 0)
        self.assertEqual(ev["reference_valid_face_samples"], 0)

    def test_empty_or_aborted_windows_keep_evidence(self):
        phases, _ = self.inputs()
        for aborted in (False, True):
            fails, _, _, evidence = capture.quality_check(phases, [], aborted, include_evidence=True)
            self.assertTrue(fails)
            self.assertEqual(len(evidence), 1)
            ev = evidence[0]
            self.assertEqual(ev["reference_step"], 1)
            self.assertEqual(ev["forward_gate_result"], "fail")
            self.assertEqual(ev["forward_gate_reasons"],
                             ["insufficient_reference_face_samples", "insufficient_current_face_samples"])
            for prefix in ("reference", "current"):
                self.assertEqual(ev[prefix + "_total_samples"], 0)
                self.assertEqual(ev[prefix + "_valid_face_samples"], 0)
                self.assertIsNone(ev[prefix + "_valid_face_fraction"])
                self.assertIsNone(ev[prefix + "_face_median_m"])

    def test_latest_upright_reference_even_when_insufficient(self):
        phases, samples = self.inputs()
        phases.insert(1, dict(step=8, kind="hold", key="upright", dur=10))
        for row in samples:
            if row["phase_idx"] == 1:
                row["phase_idx"] = 2
        samples.append(dict(samples[0], phase_idx=1, distance_m=0.77))
        ev = capture.quality_check(phases, samples, False, include_evidence=True)[3][0]
        self.assertEqual((ev["reference_step"], ev["reference_phase_idx"]), (8, 1))
        self.assertEqual(ev["reference_face_median_m"], 0.77)
        self.assertAlmostEqual(ev["closer_m"], 0.12)
        samples[-1]["mode"] = "body"
        ev = capture.quality_check(phases, samples, False, include_evidence=True)[3][0]
        self.assertEqual(ev["reference_step"], 8)
        self.assertIsNone(ev["reference_face_median_m"])
        self.assertEqual(ev["forward_gate_reasons"], ["insufficient_reference_face_samples"])

    def test_trimming_counts_and_medians_use_identical_windows(self):
        phases, samples = self.inputs()
        for phase_idx in (0, 1):
            template = samples[phase_idx * 5]
            # Boundary and outside samples must not affect either counts or medians.
            samples.extend(dict(template, t=t, mode="body", distance_m=1.2)
                           for t in (0, 1.0, 9.5, 10))
        ev = capture.quality_check(phases, samples, False, include_evidence=True)[3][0]
        self.assertEqual(ev["reference_total_samples"], 5)
        self.assertEqual(ev["current_total_samples"], 5)
        self.assertEqual(ev["reference_face_median_m"], 0.75)
        self.assertEqual(ev["current_face_median_m"], 0.65)
        self.assertEqual(ev["forward_gate_result"], "pass")

    def test_evidence_consumes_actual_helper_results_once(self):
        phases, samples = self.inputs()
        helper = capture.median_face_distance
        def offset_result(values, **kwargs):
            return helper(values, **kwargs) + 0.01
        with patch.object(capture, "median_face_distance", side_effect=offset_result) as median, \
                patch.object(capture, "evaluate_forward_distance", wraps=capture.evaluate_forward_distance) as gate:
            ev = capture.quality_check(phases, samples, False, include_evidence=True)[3][0]
        self.assertEqual(median.call_count, 2)
        gate.assert_called_once_with(ev["closer_m"])
        self.assertEqual(ev["reference_face_median_m"], 0.76)
        self.assertEqual(ev["current_face_median_m"], 0.66)
        self.assertEqual(ev["reference_valid_face_samples"], 5)

    def test_only_forward_hold_phases_have_evidence(self):
        phases = [dict(step=i + 1, kind=kind, key=key, dur=10) for i, (kind, key) in enumerate(
            (("hold", "upright"), ("prep", "forward_head"), ("hold", "forward_head"),
             ("hold", "lean_back"), ("hold", "body_forward")))]
        evidence = capture.quality_check(phases, [], False, include_evidence=True)[3]
        self.assertEqual([(e["step"], e["label"]) for e in evidence], [(3, "forward_head"), (5, "body_forward")])

    def test_existing_result_tuple_matches_baseline_fixture(self):
        for current, expected_fail in ((0.65, []), (0.68, ["2단계 거북목: 얼굴 전방 이동 7.0cm — 목표 8~12cm"]),
                                       (0.62, ["2단계 거북목: 얼굴 전방 이동 13.0cm — 목표 8~12cm"])):
            phases, samples = self.inputs(current=current)
            expected = (expected_fail, [], [["1단계 정상 자세", 0.75, 0.0, 1.0, 1.0, 100, 1.0, 100, 0],
                                           ["2단계 거북목", current, 0.0, 1.0, 1.0, 100, 1.0, 100, 1]])
            self.assertEqual(capture.quality_check(phases, samples, False), expected)
            self.assertEqual(capture.quality_check(phases, samples, False, include_evidence=True)[:3], expected)

    def test_quality_json_preserves_fields_and_serializes_same_evidence(self):
        phases, samples = self.inputs()
        provenance = {"recording_id": "test_recording", "dataset_role": "pilot"}
        checked = capture.quality_check(phases, samples, False, include_evidence=True)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.object(capture, "count_frames", return_value=(300, 300)), \
                patch.object(capture, "quality_check", return_value=checked) as check:
            base = os.path.join(directory, "test_recording")
            capture.report("TEST", "1", base, base + ".bag", phases, samples, False, 20.0, provenance)
            saved = json.loads(Path(base + "_quality.json").read_text())
        check.assert_called_once_with(phases, samples, False, include_evidence=True)
        self.assertEqual(saved.pop("forward_gate_evidence"), checked[3])
        self.assertEqual(saved, {
            "verdict": "ok", "fails": [], "warnings": [], "recording_id": "test_recording", "total_sec": 20.0,
            "frames": "컬러 300 / 깊이 300 프레임 (예상 약 300, 100%)",
            "steps": [{"name": name, "median_m": med, "sd_m": 0.0, "person_ratio": 1.0, "face_ratio": 1.0,
                       "face_area_px": 100, "area_ratio_A": 1.0, "face_size_cm2": 100}
                      for name, med in (("1단계 정상 자세", 0.75), ("2단계 거북목", 0.65))],
        })


if __name__ == "__main__":
    unittest.main()
