"""Integration tests: probe frame callback -> mesh-avatar payload -> browser RF display.

Fake RealSense/MediaPipe and a tiny synthetic RF artifact only; no hardware,
no FBX asset, and nothing here is evidence of real-world performance.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import mesh_avatar_bridge as bridge
import posture_geometry_probe as probe
import run_mesh_avatar
from test_f1_demo_rf import feature_values, synthetic_rows, write_canonical_csv
from test_posture_geometry_probe import (
    FakeLiveLoop,
    RFDemoArtifactCase,
    SequencePoseTask,
    live_pose_result,
    pose_landmark,
)

WEB_DIR = Path(bridge.WEB_DIR)


def rf_frame(prediction, label, reason="r", status=probe.RF_MODEL_LOADED):
    return probe.RFDemoFrame(status, "m.json", prediction, label, reason)


class ProbeCallbackSynchronizationTests(RFDemoArtifactCase):
    def run_loop(self, loop, **kwargs):
        frames = []
        kwargs.setdefault("f1_live", True)
        kwargs.setdefault("rf_demo_model_path", str(self.model_path))
        with mock.patch.object(
            probe, "draw_engineering_panel", wraps=probe.draw_engineering_panel
        ) as draw, mock.patch.object(
            probe.viewer, "render_selected_views", wraps=probe.viewer.render_selected_views
        ) as render:
            loop.run(frame_callback=frames.append, show_3d_views="side", **kwargs)
        drawn = [call.kwargs["rf_demo"] for call in draw.call_args_list]
        rendered = [call.args[0] for call in render.call_args_list]
        return frames, drawn, rendered

    def test_callback_receives_each_completed_frame_with_its_own_prediction(self):
        loop = FakeLiveLoop(frame_count=3)
        frames, drawn, rendered = self.run_loop(loop)
        self.assertEqual([f.frame_index for f in frames], [1, 2, 3])
        stamps = [f.mediapipe_timestamp_ms for f in frames]
        self.assertEqual(stamps, sorted(set(stamps)))
        self.assertEqual(stamps, [call[1] for call in loop.pose.video_calls])
        for frame, rf_demo, result, live in zip(frames, drawn, rendered, loop.live_results):
            # the very objects the OpenCV strip and the side view used for this frame
            self.assertIs(frame.rf_demo, rf_demo)
            self.assertIs(frame.result, result)
            self.assertIs(frame.live_f1, live)
            self.assertIsNotNone(frame.rf_demo.label)
            self.assertTrue(frame.face_matrix_values["face_matrix_valid"])
            payload = bridge.probe_frame_to_payload(frame)
            json.dumps(payload)  # serialisable for /pose
            self.assertEqual(payload["schema"], "mesh-avatar-pose/3")
            self.assertEqual(payload["frame_id"], frame.frame_index)
            self.assertEqual(payload["prediction"]["frame_id"], frame.frame_index)
            self.assertEqual(payload["mediapipe_timestamp_ms"], frame.mediapipe_timestamp_ms)
            self.assertEqual(payload["device_timestamp_ms"], frame.device_timestamp_ms)
            self.assertEqual(payload["prediction"]["status"], "available")
            self.assertEqual(payload["prediction"]["display"], rf_demo.prediction)
            self.assertEqual(payload["prediction"]["label"], rf_demo.label)
            self.assertEqual(payload["prediction"]["banner"], bridge.RF_DEMO_BANNER)
            self.assertEqual(payload["exploratory_geometry"]["frame_id"], frame.frame_index)
            self.assertEqual(payload["exploratory_geometry"]["kind"], bridge.GEOMETRY_KIND)
            self.assertEqual(
                payload["exploratory_geometry"]["values"]["sagittal_torso_lean_deg"],
                frame.result.features["sagittal_torso_lean_deg"],
            )
            self.assertIsNotNone(payload["head"])
            self.assertFalse(payload["synthetic"])

    def test_unavailable_frames_are_published_unavailable_not_substituted(self):
        loop = FakeLiveLoop(frame_count=4)
        loop.pose = SequencePoseTask([
            live_pose_result(),
            live_pose_result(i24=pose_landmark(0.44, 1.02)),
            types.SimpleNamespace(pose_landmarks=[]),
            live_pose_result(),
        ])
        frames, drawn, _ = self.run_loop(loop)
        payloads = [bridge.probe_frame_to_payload(f) for f in frames]
        statuses = [p["prediction"]["status"] for p in payloads]
        self.assertEqual(statuses, ["available", "unavailable", "unavailable", "available"])
        for payload, rf_demo in zip(payloads[1:3], drawn[1:3]):
            self.assertEqual(payload["prediction"]["display"], bridge.PREDICTION_UNAVAILABLE)
            self.assertIsNone(payload["prediction"]["label"])
            self.assertEqual(payload["prediction"]["reason"], rf_demo.reason)
        self.assertEqual(payloads[1]["prediction"]["reason"], "missing sh_x, sh_y (right_hip_valid:false)")

    def test_missing_artifact_publishes_model_status_and_reason(self):
        frames, _, _ = self.run_loop(
            FakeLiveLoop(frame_count=2), rf_demo_model_path=str(self.root / "absent.json")
        )
        for frame in frames:
            prediction = bridge.probe_frame_to_payload(frame)["prediction"]
            self.assertEqual(prediction["status"], "unavailable")
            self.assertEqual(prediction["model_status"], probe.RF_MODEL_NOT_LOADED)
            self.assertIn("absent.json", prediction["reason"])

    def test_rf_demo_off_publishes_not_enabled(self):
        for kwargs in ({"f1_live": True, "rf_demo_model_path": None}, {"f1_live": False, "rf_demo_model_path": None}):
            with self.subTest(**kwargs):
                frames, _, _ = self.run_loop(FakeLiveLoop(frame_count=1), **kwargs)
                self.assertIsNone(frames[0].rf_demo)
                prediction = bridge.probe_frame_to_payload(frames[0])["prediction"]
                self.assertEqual(prediction["status"], "unavailable")
                self.assertEqual(prediction["reason"], bridge.REASON_RF_NOT_ENABLED)

    def test_existing_windows_unchanged_by_callback(self):
        def run(callback):
            window = mock.Mock()
            window.update.return_value = True
            loop = FakeLiveLoop(frame_count=2)
            with mock.patch.object(probe.pyvista_viewer, "require_pyvista"), \
                    mock.patch.object(probe.pyvista_viewer, "PyVistaPostureViewer", return_value=window):
                kwargs = dict(show_3d_views="side", pyvista_view=True, f1_live=True,
                              rf_demo_model_path=str(self.model_path))
                if callback is not None:
                    kwargs["frame_callback"] = callback
                loop.run(**kwargs)
            return loop, window

        base, base_window = run(None)
        frames = []
        hooked, hooked_window = run(frames.append)
        self.assertEqual(hooked.shown, base.shown)  # RGB+F1+RF window and side view, same shapes and order
        self.assertEqual(
            {name for name, _ in hooked.shown}, {probe.WINDOW_NAME, probe.viewer.WINDOW_NAME}
        )
        self.assertEqual(hooked_window.update.call_count, base_window.update.call_count)
        for frame, call in zip(frames, hooked_window.update.call_args_list):
            self.assertIs(frame.result, call.args[0])
            self.assertEqual(dict(frame.face_matrix_values), call.args[1])
        self.assertEqual(hooked.created_files, [])


class PayloadPredictionTests(unittest.TestCase):
    def test_available_prediction_forwarded_unchanged(self):
        for display, label in (("UPRIGHT", "upright"), ("FORWARD HEAD", "forward_head"),
                               ("BODY FORWARD", "body_forward")):
            p = bridge.prediction_from_rf_demo(rf_frame(display, label), frame_id=5)
            self.assertEqual((p["status"], p["display"], p["label"], p["frame_id"]),
                             ("available", display, label, 5))

    def test_unknown_display_is_unavailable(self):
        p = bridge.prediction_from_rf_demo(rf_frame("SLOUCH", "slouch"), frame_id=1)
        self.assertEqual(p["status"], "unavailable")
        self.assertEqual(p["display"], bridge.PREDICTION_UNAVAILABLE)
        self.assertIsNone(p["label"])

    def test_bridge_displays_match_probe_labels(self):
        self.assertEqual(set(bridge.PREDICTION_DISPLAYS), set(probe.RF_DISPLAY_LABELS.values()))
        self.assertEqual(bridge.PREDICTION_UNAVAILABLE, probe.RF_PREDICTION_UNAVAILABLE)
        self.assertEqual(bridge.RF_DEMO_BANNER, probe.RF_DEMO_BANNERS[0])

    def test_synthetic_payload_never_carries_prediction(self):
        available = bridge.prediction_from_rf_demo(rf_frame("UPRIGHT", "upright"), frame_id=0)
        payload = bridge.make_payload({}, synthetic=True, prediction=available)
        self.assertEqual(payload["prediction"]["status"], "unavailable")
        self.assertEqual(payload["prediction"]["reason"], bridge.REASON_SYNTHETIC)
        self.assertTrue(payload["synthetic"])

    def test_legacy_result_payload_has_unavailable_prediction(self):
        payload = bridge.result_to_pose_payload(
            probe.geometry.GeometryResult(points={}, proxies={}, features={}, points_3d={}), frame_id=2
        )
        self.assertEqual(payload["prediction"]["status"], "unavailable")
        self.assertEqual(payload["prediction"]["frame_id"], 2)


class LauncherTests(unittest.TestCase):
    def run_main(self, argv, models_dir):
        with mock.patch.object(bridge, "MODELS_DIR", models_dir), \
                mock.patch.object(bridge, "start_server") as start, \
                mock.patch.object(run_mesh_avatar.webbrowser, "open"), \
                mock.patch.object(probe, "run_probe") as run_probe, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run_mesh_avatar.main(argv), 0)
        return run_probe, start, out.getvalue()

    def test_uses_explicit_callback_and_forwards_probe_options(self):
        before = (probe.viewer.render_selected_views, probe._face_matrix_csv_values)
        with tempfile.TemporaryDirectory() as d:
            run_probe, start, _ = self.run_main(
                ["--no-browser", "--f1-live", "--rf-demo-model", "m.json", "--pyvista"], Path(d)
            )
        # no monkey-patching of private probe/viewer functions
        self.assertEqual((probe.viewer.render_selected_views, probe._face_matrix_csv_values), before)
        kwargs = run_probe.call_args.kwargs
        self.assertEqual(kwargs["show_3d_views"], "side")
        self.assertTrue(kwargs["f1_live"])
        self.assertEqual(kwargs["rf_demo_model_path"], "m.json")
        self.assertTrue(kwargs["pyvista_view"])
        store = start.call_args.args[0]
        frame = probe.ProbeFrame(
            7, 1234.5, 1234,
            probe.geometry.GeometryResult(points={}, proxies={}, features={}, points_3d={}),
            {}, None, rf_frame("BODY FORWARD", "body_forward"),
        )
        kwargs["frame_callback"](frame)
        published = store.latest()
        self.assertEqual(published["frame_id"], 7)
        self.assertEqual(published["prediction"]["display"], "BODY FORWARD")
        self.assertEqual(published["prediction"]["frame_id"], 7)

    def test_views_option_still_forwarded(self):
        with tempfile.TemporaryDirectory() as d:
            run_probe, _, _ = self.run_main(["--no-browser", "--views", "debug"], Path(d))
        self.assertEqual(run_probe.call_args.kwargs["show_3d_views"], "debug")
        self.assertIsNone(run_probe.call_args.kwargs["rf_demo_model_path"])

    def test_missing_fbx_gives_diagnostic_and_no_download(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("download")):
            _, _, out = self.run_main(["--no-browser"], Path(d))
            self.assertIn("avatar model not found", out)
            self.assertIn("never downloaded", out)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_present_fbx_no_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / bridge.DEFAULT_MODEL_FILE).write_bytes(b"x")
            with mock.patch.object(bridge, "MODELS_DIR", Path(d)):
                self.assertIsNone(bridge.model_asset_diagnostic())

    def test_synthetic_rejects_probe_options(self):
        with self.assertRaises(SystemExit):
            run_mesh_avatar.main(["--synthetic", "--no-browser", "--f1-live"])


class BrowserNoHeuristicJudgementTests(unittest.TestCase):
    def read(self, name):
        return (WEB_DIR / name).read_text(encoding="utf-8")

    def test_temporary_indicator_panel_not_imported(self):
        self.assertFalse((WEB_DIR / "indicators.js").exists())
        page = self.read("index.html") + self.read("app.js") + self.read("prediction.js")
        for token in ("indicators", "computeIndicators", "renderPanel", "DEMO_RULES", "임시 데모 규칙", 'id="ind"'):
            self.assertNotIn(token, page)

    def test_only_prediction_module_names_classes_and_it_reads_no_joints(self):
        app = self.read("app.js")
        for text in ("UPRIGHT", "FORWARD HEAD", "BODY FORWARD", "forward_head", "body_forward"):
            self.assertNotIn(text, app)
        pred = self.read("prediction.js")
        # pure display of the supplied prediction: no joint access, geometry or remembered predictions
        for token in ("joints[", "joints.", "shoulder", "nose", "left_", "right_", "atan", "acos", "hypot", "head",
                      "let ", "var ", "localStorage"):
            self.assertNotIn(token, pred)

    def test_page_has_banner_and_unavailable_default(self):
        page = self.read("index.html")
        self.assertIn("ENGINEERING RF DEMO — ACCURACY NOT VALIDATED", page)
        self.assertIn('<div id="predText" class="pred-na">PREDICTION UNAVAILABLE</div>', page)
        self.assertIn("EXPLORATORY GEOMETRY — NOT A POSTURE CLASSIFICATION", page)
        self.assertIn("현재 프레임 탐색용 기하 · 판정 아님", page)
        for element_id in ("gTorso", "gHeadPitch", "gHeadForward", "gShoulderWidth", "gHeadLateral", "gFaceYaw"):
            self.assertIn(f'id="{element_id}">N/A', page)

    def test_dashboard_layout_and_synthetic_labels(self):
        page = self.read("index.html")
        for token in ("AIoT Posture Monitor", "ENGINEERING DEMO", 'id="viewFront"', 'id="viewSide"', 'id="modeChip"',
                      'id="notice"', 'href="./style.css"'):
            self.assertIn(token, page)
        self.assertTrue((WEB_DIR / "style.css").exists())
        app = self.read("app.js")
        self.assertIn("'SYNTHETIC'", app)
        self.assertIn("FBX 로드 실패", app)
        # display-only layout: diagnostics fall back to N/A, never to invented values
        self.assertIn("'N/A'", app)

    def test_server_serves_stylesheet(self):
        server = bridge.start_server(bridge.PoseStore(), port=0)
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(base + "/style.css") as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"predText", response.read())
        finally:
            server.shutdown()
            server.server_close()

    def test_server_serves_prediction_module(self):
        server = bridge.start_server(bridge.PoseStore(), port=0)
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(base + "/prediction.js") as response:
                self.assertEqual(response.headers.get_all("Cache-Control"), ["no-cache"])
                self.assertIn(b"predictionView", response.read())
        finally:
            server.shutdown()
            server.server_close()

    def test_server_serves_geometry_module(self):
        server = bridge.start_server(bridge.PoseStore(), port=0)
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(base + "/geometry.js") as response:
                self.assertEqual(response.headers.get_all("Cache-Control"), ["no-cache"])
                body = response.read()
                self.assertIn(b"geometryView", body)
                self.assertIn(b"NOT A POSTURE CLASSIFICATION", body)
        finally:
            server.shutdown()
            server.server_close()


@unittest.skipUnless(shutil.which("node"), "node not installed: browser display logic not executed")
class BrowserPredictionViewTests(unittest.TestCase):
    """Executes mesh_avatar/web/prediction.js with Node (pure function, no DOM)."""

    def view(self, payload, age_ms):
        script = textwrap.dedent(f"""
            import {{ predictionView }} from {json.dumps((WEB_DIR / 'prediction.js').as_uri())};
            const age = {json.dumps(age_ms)};
            console.log(JSON.stringify(predictionView({json.dumps(payload)}, age === null ? Infinity : age)));
        """)
        out = subprocess.run(
            ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True, timeout=30
        )
        return json.loads(out.stdout)

    def payload(self, prediction, frame_id=4, **extra):
        base = {"frame_id": frame_id, "joints": {}, "synthetic": False, "prediction": prediction}
        base.update(extra)
        return base

    def test_shows_supplied_prediction_only(self):
        for display in ("UPRIGHT", "FORWARD HEAD", "BODY FORWARD"):
            p = bridge.prediction_from_rf_demo(rf_frame(display, "x"), frame_id=4)
            v = self.view(self.payload(p), 10)
            self.assertEqual((v["text"], v["frameId"]), (display, 4))

    def test_unavailable_cases(self):
        good = bridge.prediction_from_rf_demo(rf_frame("UPRIGHT", "upright"), frame_id=4)
        cases = {
            "no payload": (None, 0),
            "no joints": ({"schema": bridge.POSE_SCHEMA, "joints": None}, 0),
            "stale": (self.payload(good), 1500),
            "never arrived": (self.payload(good), None),
            "other frame": (self.payload(dict(good, frame_id=3)), 10),
            "missing prediction": (self.payload(None), 10),
            "unavailable": (self.payload(bridge.unavailable_prediction("missing sh_x", frame_id=4)), 10),
            "unknown display": (self.payload(dict(good, display="SLOUCH")), 10),
            "synthetic": (self.payload(good, synthetic=True), 10),
        }
        for name, (payload, age) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.view(payload, age)["text"], "PREDICTION UNAVAILABLE")
        self.assertEqual(
            self.view(self.payload(bridge.unavailable_prediction("missing sh_x", frame_id=4)), 10)["reason"],
            "missing sh_x",
        )

    def test_offline_rf_end_to_end_smoke(self):
        """Synthetic engineering data only; labels are not real posture evidence."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = synthetic_rows()
            csv_path = root / "synthetic_engineering_frames.csv"
            model_path = root / "synthetic_engineering_model.json"
            write_canonical_csv(csv_path, rows)

            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("train_f1_demo_rf.py")),
                    "--input", str(csv_path),
                    "--output", str(model_path),
                    "--trees", "31",
                    "--max-features", "5",
                    "--seed", "7",
                ],
                capture_output=True, text=True, check=True, timeout=60,
            )
            state = probe.load_rf_demo_model(model_path)
            self.assertEqual(state.status, probe.RF_MODEL_LOADED)

            cases = [
                ("upright", rows[0]),
                ("forward_head", rows[12]),
                ("body_forward", rows[24]),
                (None, dict(rows[0], face_detected="false", face_x="", face_y="")),
            ]
            empty_geometry = probe.geometry.GeometryResult(
                points={}, proxies={}, features={}, points_3d={}
            )
            for frame_id, (synthetic_expected_label, row) in enumerate(cases, 1):
                with self.subTest(synthetic_engineering_label=synthetic_expected_label):
                    live = types.SimpleNamespace(result=feature_values(row))
                    rf_demo = probe.rf_demo_frame(state, live)
                    frame = probe.ProbeFrame(
                        frame_id, float(frame_id), frame_id, empty_geometry, {}, live, rf_demo
                    )
                    payload = bridge.probe_frame_to_payload(frame)
                    view = self.view(payload, 10)

                    if synthetic_expected_label is None:
                        self.assertEqual(rf_demo.prediction, probe.RF_PREDICTION_UNAVAILABLE)
                        self.assertIsNone(rf_demo.label)
                        self.assertEqual(payload["prediction"]["status"], "unavailable")
                        self.assertEqual(view["text"], "PREDICTION UNAVAILABLE")
                    else:
                        expected_display = probe.RF_DISPLAY_LABELS[synthetic_expected_label]
                        self.assertEqual(rf_demo.label, synthetic_expected_label)
                        self.assertEqual(payload["prediction"]["label"], synthetic_expected_label)
                        self.assertEqual(payload["prediction"]["display"], expected_display)
                        self.assertEqual(view["text"], expected_display)


@unittest.skipUnless(shutil.which("node"), "node not installed: browser geometry display logic not executed")
class BrowserGeometryViewTests(unittest.TestCase):
    """Executes the display-only same-frame geometry adapter with Node."""

    def view(self, payload, age_ms):
        script = textwrap.dedent(f"""
            import {{ geometryView }} from {json.dumps((WEB_DIR / 'geometry.js').as_uri())};
            const age = {json.dumps(age_ms)};
            console.log(JSON.stringify(geometryView({json.dumps(payload)}, age === null ? Infinity : age)));
        """)
        out = subprocess.run(
            ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True, timeout=30
        )
        return json.loads(out.stdout)

    def payload(self, frame_id=4, **geometry_changes):
        geometry_payload = {
            "kind": bridge.GEOMETRY_KIND,
            "role": "exploratory_geometry_not_classification",
            "frame_id": frame_id,
            "values": {
                "sagittal_torso_lean_deg": 7.25,
                "exploratory_head_pitch_deg": None,
                "nose_forward_normalized_by_shoulder_width_3d": 0.12,
                "shoulder_width_3d_m": 0.4,
                "head_to_torso_lateral_angle_deg": -3.5,
                "face_matrix_yaw_deg": 2.0,
            },
        }
        geometry_payload.update(geometry_changes)
        return {
            "frame_id": frame_id,
            "joints": {},
            "synthetic": False,
            "exploratory_geometry": geometry_payload,
        }

    def test_shows_only_supplied_same_frame_finite_values(self):
        view = self.view(self.payload(), 10)
        self.assertEqual(view["frameId"], 4)
        self.assertEqual(view["values"]["sagittal_torso_lean_deg"], 7.25)
        self.assertEqual(view["values"]["head_to_torso_lateral_angle_deg"], -3.5)
        self.assertIsNone(view["values"]["exploratory_head_pitch_deg"])

    def test_missing_stale_synthetic_or_other_frame_never_reuses_values(self):
        other_frame = self.payload()
        other_frame["exploratory_geometry"]["frame_id"] = 3
        cases = {
            "no payload": (None, 0),
            "stale": (self.payload(), 1500),
            "never arrived": (self.payload(), None),
            "other frame": (other_frame, 10),
            "missing geometry": ({"frame_id": 4, "joints": {}, "synthetic": False}, 10),
            "synthetic": (dict(self.payload(), synthetic=True), 10),
        }
        for name, (payload, age) in cases.items():
            with self.subTest(name):
                view = self.view(payload, age)
                self.assertTrue(all(value is None for value in view["values"].values()))


if __name__ == "__main__":
    unittest.main()
