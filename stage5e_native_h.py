"""Offline native H5/H9 adapter using unchanged probe geometry/aggregation.

No camera capture, downloads, fitting, label certification or formal execution.
Requires the complete F0 native inventory for exact cross-path frame binding.
"""

from contextlib import ExitStack
from pathlib import Path

import numpy as np

import analyze_d455 as canonical
import f0_fcal_native as native
from f0_fcal_input import _ReplayClock, _require
from f1_sample_aggregator import H9_FEATURE_NAMES, HFrameRecord, aggregate_h5_h9_sample
from h6_offline import analysis_label
import posture_geometry as geometry
import posture_geometry_probe as probe
from rf_experiment import file_identity


class GeometryObserver:
    """Reuse RGB landmark results; recompute geometry for each delivered depth."""
    kind = "locked-probe-geometry-native-offline"

    def __init__(self, reader, model_dir):
        self.reader, self.model_dir = reader, model_dir
        self.previous_color = self.previous_timestamp = self.landmarks = None

    def __enter__(self):
        import pyrealsense2 as rs
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        self.rs, self.stack = rs, ExitStack()
        try:
            lock = canonical.load_model_lock()
            paths = {role: str(Path(self.model_dir) / lock[role]["filename"]) for role in ("pose", "mesh")}
            for role, path in paths.items():
                canonical.verify_model_artifact(path, lock[role])
            self.model_artifacts = {role: file_identity(path) for role, path in paths.items()}
            self.pose = self.stack.enter_context(vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=paths["pose"]),
                    running_mode=vision.RunningMode.VIDEO, num_poses=canonical.POSE_NUM_POSES)))
            self.mesh = self.stack.enter_context(vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=paths["mesh"]),
                    running_mode=vision.RunningMode.VIDEO, num_faces=canonical.FACE_NUM_FACES,
                    output_facial_transformation_matrixes=True)))
            self.align = rs.align(rs.stream.color)
            self.scale = self.reader.pipe.get_active_profile().get_device().first_depth_sensor().get_depth_scale()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        self.stack.close()

    def observe(self, packet):
        if packet.color_bgr is None:
            return dict.fromkeys(H9_FEATURE_NAMES)
        color = native._stream_evidence(packet, "color")
        if self.previous_color is not None and color["frame_number"] == self.previous_color["frame_number"]:
            _require(color == self.previous_color, "h_native_color_reuse_mismatch")
        else:
            import cv2
            import mediapipe as mp
            timestamp = packet.timing["mediapipe_ts_ms"]
            _require(timestamp == int(color["timestamp_ms"]) and
                     (self.previous_timestamp is None or timestamp > self.previous_timestamp),
                     "h_native_model_time_invalid")
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(packet.color_bgr, cv2.COLOR_BGR2RGB))
            pose, face = probe.run_frame_inference(self.pose, self.mesh, image, timestamp)
            self.landmarks = (pose.pose_landmarks[0] if pose.pose_landmarks else None,
                              face.face_landmarks[0] if face.face_landmarks else None)
            self.previous_color, self.previous_timestamp = color, timestamp
        # A reused RGB child may accompany NEW depth: never cache H9 geometry.
        frames = self.reader.current_frames
        aligned_depth = None
        if packet.depth_z16 is not None:
            depth_frame = self.align.process(frames).get_depth_frame()
            if depth_frame:
                aligned_depth = np.asanyarray(depth_frame.get_data())
        intrinsics = frames.get_color_frame().profile.as_video_stream_profile().get_intrinsics()
        height, width = packet.color_bgr.shape[:2]
        pose_lm, face_lm = self.landmarks
        points = geometry.points_from_pose_landmarks(pose_lm, width, height,
            aligned_depth=aligned_depth, depth_scale_m=self.scale)
        points.update(geometry.points_from_face_landmarks(face_lm, width, height,
            aligned_depth=aligned_depth, depth_scale_m=self.scale))
        chest = geometry.sample_hipless_chest_roi(points.get("left_shoulder"),
            points.get("right_shoulder"), aligned_depth, self.scale)
        result = geometry.compute_candidate_geometry(points, focal_length_px=intrinsics.fx,
            points_3d=probe.deproject_body_points(points, intrinsics, self.rs), chest_roi_point=chest,
            chest_roi_point_3d=probe.deproject_geometry_point(chest, intrinsics, self.rs))
        return {name: result.features[name] for name in H9_FEATURE_NAMES}


def extract_h(recording, sources, native_inventory, model_dir, *,
              packet_factory=native.NativePackets, observer_factory=GeometryObserver):
    """Return H samples/windows/audit only after exact inventory/EOF validation.

    recording and native_inventory must be from the same pinned native F0 run.
    Ineligible samples remain present; this function never assigns confirmed.
    Synthetic injection is test-only and explicitly identified in backend audit.
    """
    raw, _, _, _, _, _, intervals = native._markers(recording, sources)
    groups = {s["step"]: [] for _, _, s in intervals}
    clock, observed = _ReplayClock(), []
    with packet_factory(raw) as reader, observer_factory(reader, model_dir) as observer:
        for index, packet in enumerate(reader, 1):
            packet.validate()
            ts = packet.timing["frameset_timestamp_ms"]
            streams = {name: native._stream_evidence(packet, name) for name in ("color", "depth")}
            clock.accept(ts, packet.timing["frameset_timestamp_domain"], streams)
            evidence = dict(frame_index=index, ts_ms=ts,
                color_frame_number=(packet.timing.get("color") or {}).get("frame_number"),
                depth_frame_number=(packet.timing.get("depth") or {}).get("frame_number"),
                mediapipe_ts_ms=packet.timing.get("mediapipe_ts_ms"), native_streams=streams)
            _require(index <= len(native_inventory) and evidence == native_inventory[index-1],
                     "h_f0_native_inventory_mismatch")
            observed.append(evidence)
            features = observer.observe(packet)
            for start, end, s in intervals:
                if end-10000 <= ts < end:
                    groups[s["step"]].append(HFrameRecord(recording["analysis_run_id"],
                        recording["recording_id"], index, recording["subject"], recording["round"],
                        str(s["step"]), analysis_label(s["label"]), features))
        _require(reader.completed and len(observed) == len(native_inventory), "h_native_EOF_or_count_mismatch")
        models = observer.model_artifacts
        for spec in models.values():
            sources.path(spec)
        backend = dict(reader=reader.kind, observer=observer.kind, models=models)
    sources.recheck()
    _require(all(groups.values()), "h_analysis_window_empty")
    samples = tuple(aggregate_h5_h9_sample(groups[s["step"]]) for _, _, s in intervals)
    windows, key_map = {}, {}
    for sample, (_, end, segment) in zip(samples, intervals):
        key = (*sample.sample_key[:2], segment["step"])
        key_map[sample.sample_key] = key
        # Same seconds conversion/order as the existing F0 TimedSegment bridge.
        end_s = end/1000
        windows[key] = ((clock.domain, end_s-10, end_s), segment.get("session"))
    return dict(samples=samples, windows=windows, key_map=key_map, backend=backend,
                framesets=len(observed), source_artifacts=dict(sources.artifacts),
                code={"adapter": file_identity(__file__),
                      **{name: file_identity(module.__file__) for name, module in
                         (("geometry", geometry), ("probe", probe), ("native", native))}})
