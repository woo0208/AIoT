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
