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


def live_display_state(label, closer, reference=0.75, sample_count=10):
    # Execute the actual UI decision block, without the surrounding camera loop.
    record = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "record_phase")
    loop = next(node for node in ast.walk(record) if isinstance(node, ast.While))
    start = next(i for i, node in enumerate(loop.body)
                 if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "(name, how, name_en)")
    end = next(i for i, node in enumerate(loop.body)
               if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "dtxt")
    code = compile(ast.Module(body=loop.body[start:end], type_ignores=[]), str(SOURCE_PATH), "exec")
    distance = 0.75 - closer
    namespace = dict(vars(capture), ph={"key": label, "kind": "hold", "dur": 10},
                     ph_i=1, t_in=4, dist=distance, ref_up={"dist": reference, "cx": 0.5},
                     samples=[dict(phase_idx=1, t=2 + i / 10, distance_m=distance, face_cx=0.5)
                              for i in range(sample_count)])
    exec(code, namespace)
    return namespace


def final_quality(label, closer):
    phases = [dict(step=1, kind="hold", key="upright", dur=10),
              dict(step=2, kind="hold", key=label, dur=10)]
    samples = [dict(phase_idx=i, t=t, distance_m=distance, face_cx=0.5,
                    mode="face", face_area_px=100, face_size_cm2=100)
               for i, distance in enumerate((0.75, 0.75 - closer)) for t in (2, 3, 4, 5, 6)]
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


if __name__ == "__main__":
    unittest.main()
