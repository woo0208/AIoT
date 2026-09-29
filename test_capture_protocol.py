"""Protocol checks without a camera, GUI, or RealSense installation."""
import ast
import builtins
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
