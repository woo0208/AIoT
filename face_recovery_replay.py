"""Opt-in FaceLandmarker experiments for offline RGB-D Replay."""

from contextlib import contextmanager
import time
from unittest.mock import patch

import e0_replay


MODES = ('baseline', 'reset', 'redetect', 'continuous_face')
MISS_LIMIT = 2
RETRY_INTERVAL_MS = 500


class FaceRecovery:
    """Use only current and past Face calls. The original Task belongs to the probe."""

    def __init__(self, mode, create_task=None, detector=None):
        if mode not in MODES or (mode in ('reset', 'redetect') and create_task is None):
            raise ValueError('Invalid Face recovery configuration')
        if mode == 'redetect' and detector is None:
            raise ValueError('Redetection requires an independent FaceDetector')
        self.mode = mode
        self.create_task = create_task
        self.detector = detector
        self.original = None
        self.replacement = None
        self.last_stamp = None
        self.last_attempt_stamp = None
        self.misses = 0
        self.generation = 0

    @property
    def task(self):
        return self.original if self.replacement is None else self.replacement

    def bind(self, original):
        if self.original is not None and self.original is not original:
            raise RuntimeError('Original Face Task changed during Replay')
        self.original = original

    @staticmethod
    def _measure(events, stage, fn, *args):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = fn(*args)
        events.append(dict(stage=stage, wall_ns=time.perf_counter_ns() - wall,
                           process_cpu_ns=time.process_time_ns() - cpu))
        return result

    def _replace(self, trial, events):
        retired, self.replacement = self.replacement, trial
        self.generation += 1
        if retired is not None:
            self._measure(events, 'close', retired.close)

    def observe(self, image, stamp, primary, *, role, events=None):
        if self.last_stamp is not None and stamp <= self.last_stamp:
            raise ValueError('Face VIDEO timestamp must increase')
        self.last_stamp = stamp
        events = [] if events is None else events
        primary_detected = bool(primary.face_landmarks)
        self.misses = 0 if primary_detected else self.misses + 1
        attempt = (self.mode in ('reset', 'redetect') and self.misses >= MISS_LIMIT
                   and (self.last_attempt_stamp is None
                        or stamp - self.last_attempt_stamp >= RETRY_INTERVAL_MS))
        initial_generation = self.generation
        independent_detected = retry_detected = None
        result = primary
        if attempt:
            self.last_attempt_stamp = stamp
            if self.mode == 'redetect':
                detection = self._measure(events, 'detector', self.detector.detect, image)
                independent_detected = bool(detection.detections)
            if independent_detected is not False:
                trial = self._measure(events, 'create', self.create_task)
                try:
                    retry = self._measure(events, 'retry', trial.detect_for_video, image, stamp)
                    retry_detected = bool(retry.face_landmarks)
                    if self.mode == 'reset' or retry_detected:
                        promoted, trial = trial, None
                        self._replace(promoted, events)
                    if retry_detected:
                        result, self.misses = retry, 0
                finally:
                    if trial is not None:
                        self._measure(events, 'close', trial.close)
        return result, dict(timestamp_ms=stamp, role=role, primary_detected=primary_detected,
            detected=bool(result.face_landmarks), recovery_attempt=attempt,
            independent_detected=independent_detected, retry_detected=retry_detected,
            primary_generation=initial_generation, active_generation=self.generation, operations=events)

    def close(self):
        if self.replacement is not None:
            task, self.replacement = self.replacement, None
            task.close()


@contextmanager
def face_recovery_hook(mode):
    """Install the experiment in one offline worker process for one Replay run."""
    from contextlib import ExitStack
    from functools import partial
    import cv2
    import mediapipe as mp
    import analyze_d455
    import posture_geometry_probe as probe

    if mode not in MODES:
        raise ValueError('Unknown Face experiment')
    base_input = e0_replay.ReplayInput
    original_infer = probe.run_frame_inference
    inputs = []
    with ExitStack() as stack:
        create_task = detector = None
        if mode in ('reset', 'redetect'):
            paths = base_input.locked_models(analyze_d455)
            tasks, vision = mp.tasks, mp.tasks.vision
            face_options = vision.FaceLandmarkerOptions(
                base_options=tasks.BaseOptions(model_asset_path=paths['mesh']),
                running_mode=vision.RunningMode.VIDEO, num_faces=analyze_d455.FACE_NUM_FACES,
                output_facial_transformation_matrixes=True)
            create_task = partial(vision.FaceLandmarker.create_from_options, face_options)
            if mode == 'redetect':
                detector_options = vision.FaceDetectorOptions(
                    base_options=tasks.BaseOptions(model_asset_path=paths['face']),
                    running_mode=vision.RunningMode.IMAGE,
                    min_detection_confidence=analyze_d455.FACE_MIN_DETECTION_CONFIDENCE)
                detector = stack.enter_context(vision.FaceDetector.create_from_options(detector_options))
        recovery = FaceRecovery(mode, create_task, detector)
        stack.callback(recovery.close)

        class ExperimentInput(base_input):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                inputs.append(self)

            def skipped(self, session, row, frame_index, stamp):
                if mode == 'continuous_face':
                    events = []
                    with session.timing.stage('input.convert', frame_index):
                        rgb = recovery._measure(events, 'face_only_convert', cv2.cvtColor,
                                                self.rgb, cv2.COLOR_BGR2RGB)
                        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    with session.timing.stage('mediapipe.face', frame_index):
                        face = recovery._measure(events, 'face_only', recovery.task.detect_for_video,
                                                 image, int(stamp))
                    _, self.current['face_experiment'] = recovery.observe(
                        image, int(stamp), face, role='FACE_ONLY', events=events)
                super().skipped(session, row, frame_index, stamp)

        def infer(pose, face, image, stamp, **kwargs):
            recovery.bind(face)
            pose_result, primary = original_infer(pose, recovery.task, image, stamp, **kwargs)
            result, trace = recovery.observe(image, stamp, primary, role='FULL')
            inputs[0].current['face_experiment'] = trace
            return pose_result, result

        stack.enter_context(patch.object(e0_replay, 'ReplayInput', ExperimentInput))
        stack.enter_context(patch.object(probe, 'run_frame_inference', infer))
        yield
