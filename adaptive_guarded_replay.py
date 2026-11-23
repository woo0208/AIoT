"""Opt-in offline AdaptiveGuardedV1 candidate; existing E0/Adaptive unchanged.

Preserve Face VIDEO history on every input, skip only Align/Pose/Depth/H9,
and reserve at least three full observations per four delivered inputs.
No labels, measurement boundaries, SVM predictions or probabilities gate work.
The temporary adapter bindings are process-local: do not run concurrently with
another probe in the same Python process. Live camera controls are not exposed.
"""
import hashlib
from pathlib import Path
import time
from unittest.mock import patch

import e0_replay
from replay_policy import ReplayGate, cpu_counters, counter_delta


CANDIDATE = 'AdaptiveGuardedV1'


class GuardedAdaptiveGate(ReplayGate):
    def __init__(self):
        super().__init__('Adaptive')
        self.face_valid = None

    def config(self):
        return dict(super().config(), candidate=CANDIDATE,
                    full_budget='at least 3 of every 4 input indices; no label/window access',
                    face_policy='same VIDEO Task on every RGB; no cached result used as H9',
                    support_note='75% full schedule headroom above unchanged 50% H9; validity not guaranteed')

    def invalidate(self):
        super().invalidate()
        self.face_valid = None

    def select(self, rgb, stamp, index):
        begin = time.perf_counter_ns()
        cpu_begin = cpu_counters()
        decision = super().select(rgb, stamp, index)
        reason = ('FACE_RECOVERY_FULL' if self.face_valid is False else
                  'H9_SUPPORT_BUDGET' if index % 4 != 0 else None)
        if not decision['full'] and reason:
            self.counts[decision['measurement_status']] -= 1
            decision.update(full=True, reason=reason, measurement_status='FULL')
            self.counts['FULL'] += 1
        decision['candidate'] = CANDIDATE
        decision['gate_cpu'] = counter_delta(cpu_begin, cpu_counters())
        decision['gate_wall_ns'] = time.perf_counter_ns() - begin
        return decision


class GuardedReplayInput(e0_replay.ReplayInput):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = GuardedAdaptiveGate()
        self.face_task = None
        self.last_face_stamp = -1
        self.on_validated = None
        self.on_features = None

    def validate(self, session, row):
        valid = super().validate(session, row)
        if valid and self.on_validated is not None:
            self.on_validated(self, session, row)
        return valid

    def observe_features(self, result):
        super().observe_features(result)
        if self.on_features is not None:
            self.on_features(self, result)

    def check_face_input(self, task, stamp):
        if self.face_task is not None and self.face_task is not task:
            raise RuntimeError('Face Task changed within continuous replay')
        if stamp <= self.last_face_stamp:
            raise ValueError('Face VIDEO timestamp duplicate/regression')
        self.face_task = task

    def face_observed(self, result, stamp, role):
        self.last_face_stamp = stamp
        detected = bool(result.face_landmarks)
        self.gate.face_valid = detected
        self.current['face_tracking'] = dict(timestamp_ms=stamp, detected=detected, role=role)
        if not detected and role == 'TRACKING_ONLY':
            # No fresh joint measurement exists on this input, even if the
            # previous full observation was valid.
            decision = self.current['gate']
            self.gate.counts[decision['measurement_status']] -= 1
            decision['measurement_status'] = 'STALE'
            self.gate.counts['STALE'] += 1

    def skipped(self, session, row, frame_index, stamp):
        import cv2
        import mediapipe as mp
        if self.face_task is None:
            raise RuntimeError('Tracking-only input before first full Face call')
        self.check_face_input(self.face_task, int(stamp))
        with session.timing.stage('input.convert', frame_index):
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(self.rgb, cv2.COLOR_BGR2RGB))
        with session.timing.stage('mediapipe.face', frame_index):
            face = self.face_task.detect_for_video(image, int(stamp))
        self.face_observed(face, int(stamp), 'TRACKING_ONLY')
        # Original skipped path supplies nine None values and keeps the input
        # in H9's denominator. Face-only results are never feature observations.
        super().skipped(session, row, frame_index, stamp)


def inference_bridge(replay, original):
    """Bind the original Task without re-running a full-frame Face inference."""
    def infer(pose, face, image, stamp, **kwargs):
        replay.check_face_input(face, stamp)
        result = original(pose, face, image, stamp, **kwargs)
        replay.face_observed(result[1], stamp, 'FULL')
        return result
    return infer


def run_guarded_replay(source, binding, artifact, directory, *, configure=None, **kwargs):
    """Original file-only run_replay with an isolated, opt-in input subclass."""
    import posture_geometry_probe as probe
    if 'method' in kwargs or 'interval' in kwargs:
        raise ValueError('Candidate selects its own gate; no E0/Fixed override')
    replay_holder = []

    class ConfiguredInput(GuardedReplayInput):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            replay_holder.append(self)
            if configure is not None:
                configure(self)

    original = probe.run_frame_inference

    def infer(*args, **kw):
        return inference_bridge(replay_holder[0], original)(*args, **kw)

    with patch.object(e0_replay, 'ReplayInput', ConfiguredInput), \
            patch.object(probe, 'run_frame_inference', infer):
        document = e0_replay.run_replay(source, binding, artifact, directory,
                                      method='Adaptive', **kwargs)
    from e0_storage import write_json
    write_json(Path(directory) / 'candidate.json', dict(
        candidate=CANDIDATE, config=replay_holder[0].gate.config(),
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        face_task_lifetime='created/closed by original run_probe; no boundary resets',
        measurement='existing service/CPU includes tracking-only Face work',
        baseline_preservation='no original source or policy rewritten'))
    return document
