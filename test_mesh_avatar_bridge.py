"""Structural tests for the display-only mesh-avatar bridge (no hardware, synthetic values)."""

import json
import math
import unittest
import urllib.request

import mesh_avatar_bridge as bridge
import posture_geometry as geometry


class MeshAvatarBridgeTests(unittest.TestCase):
    def test_make_payload_drops_non_finite_and_malformed(self):
        payload = bridge.make_payload(
            {"nose": [0.0, 0.1, 0.8], "left_ear": [math.nan, 0, 1], "right_ear": None, "bad": "xyz"},
            frame_id=3,
            synthetic=True,
        )
        self.assertEqual(payload["schema"], bridge.POSE_SCHEMA)
        self.assertEqual(payload["frame_id"], 3)
        self.assertTrue(payload["synthetic"])
        self.assertEqual(payload["joints"]["nose"], [0.0, 0.1, 0.8])
        self.assertIsNone(payload["joints"]["left_ear"])
        self.assertIsNone(payload["joints"]["right_ear"])
        self.assertIsNone(payload["joints"]["bad"])

    def test_result_to_pose_payload_forwards_usable_joints_only(self):
        result = geometry.GeometryResult(
            points={}, proxies={}, features={},
            points_3d={
                "nose": geometry.Point3D(0.0, -0.2, 0.8),
                "left_shoulder": geometry.Point3D(0.2, 0.0, 0.8),
                "right_shoulder": geometry.Point3D(-0.2, 0.0, 0.0),  # z<=0 is unusable
            },
        )
        payload = bridge.result_to_pose_payload(result, frame_id=1)
        self.assertEqual(payload["joints"]["nose"], [0.0, -0.2, 0.8])
        self.assertEqual(payload["joints"]["left_shoulder"], [0.2, 0.0, 0.8])
        self.assertIsNone(payload["joints"]["right_shoulder"])
        self.assertFalse(payload["synthetic"])

    def test_head_axes_from_valid_face_matrix_use_viewer_convention(self):
        head = bridge.head_axes_from_face_matrix({
            "face_matrix_valid": True,
            "face_matrix_pitch_deg": 0.0,
            "face_matrix_yaw_deg": 0.0,
            "face_matrix_roll_deg": 0.0,
        })
        self.assertEqual(head["source"], "face_matrix")
        # neutral face toward the camera: left ear image-right, head top image-up, face toward camera
        for axis, expected in (("lateral", (1, 0, 0)), ("vertical", (0, -1, 0)), ("forward", (0, 0, -1))):
            for got, want in zip(head[axis], expected):
                self.assertAlmostEqual(got, want, places=9)

    def test_head_axes_pitch_down_points_forward_axis_image_down(self):
        head = bridge.head_axes_from_face_matrix({
            "face_matrix_valid": True,
            "face_matrix_pitch_deg": -20.0,
            "face_matrix_yaw_deg": 0.0,
            "face_matrix_roll_deg": 0.0,
        })
        self.assertGreater(head["forward"][1], 0.3)  # +Y = image-down
        for axis in ("lateral", "vertical", "forward"):
            self.assertAlmostEqual(math.hypot(*head[axis]), 1.0, places=9)

    def test_head_axes_absent_without_valid_face_matrix(self):
        self.assertIsNone(bridge.head_axes_from_face_matrix(None))
        self.assertIsNone(bridge.head_axes_from_face_matrix({"face_matrix_valid": False}))
        self.assertIsNone(bridge.head_axes_from_face_matrix({
            "face_matrix_valid": True,
            "face_matrix_pitch_deg": math.nan,
            "face_matrix_yaw_deg": 0.0,
            "face_matrix_roll_deg": 0.0,
        }))

    def test_payload_head_is_forwarded_or_null(self):
        result = geometry.GeometryResult(points={}, proxies={}, features={}, points_3d={})
        with_face = bridge.result_to_pose_payload(result, face_matrix_values={
            "face_matrix_valid": True,
            "face_matrix_pitch_deg": 5.0,
            "face_matrix_yaw_deg": -3.0,
            "face_matrix_roll_deg": 1.0,
        })
        self.assertEqual(with_face["head"]["source"], "face_matrix")
        self.assertEqual(len(with_face["head"]["forward"]), 3)
        self.assertIsNone(bridge.result_to_pose_payload(result)["head"])
        bad = bridge.make_payload({}, head={"source": "x", "lateral": [1, 0], "vertical": [0, 1, 0], "forward": [0, 0, 1]})
        self.assertIsNone(bad["head"])

    def test_server_serves_latest_pose(self):
        store = bridge.PoseStore()
        server = bridge.start_server(store, port=0)
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/pose"
            empty = json.load(urllib.request.urlopen(url))
            self.assertIsNone(empty["joints"])
            store.publish(bridge.make_payload({"nose": [0, 0, 1]}, frame_id=7))
            got = json.load(urllib.request.urlopen(url))
            self.assertEqual(got["frame_id"], 7)
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read()
            self.assertIn(b"Posture Mesh Avatar", page)
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
