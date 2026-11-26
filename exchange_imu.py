"""Optional separate RealSense motion sensor; never feeds the posture model."""
import json
import queue
import threading
import time


def available_profiles(device, rs):
    for sensor in device.query_sensors():
        # Pick one profile per stream from a dedicated motion sensor.
        choices = {}
        for profile in sensor.get_stream_profiles():
            kind = profile.stream_type()
            if kind in (rs.stream.accel, rs.stream.gyro) and profile.format() == rs.format.motion_xyz32f:
                if kind not in choices or profile.fps() < choices[kind].fps():
                    choices[kind] = profile
        if choices:
            return sensor, list(choices.values())
    return None, []


class MotionLog:
    def __init__(self, path):
        self.path = path
        self.queue = queue.Queue(512)
        self.done = threading.Event()
        self.sensor = self.worker = self.stream = None
        self.opened = self.started = False
        self.reason = None
        self.saved = self.dropped = 0
        self.profiles = []
        self.capability = 'UNKNOWN'

    def start(self, device, rs):
        try:
            self.sensor, selected = available_profiles(device, rs)
            self.capability = 'SUPPORTED' if selected else 'UNSUPPORTED'
            if self.sensor is None:
                self.reason = 'No supported motion profile'
                return
            self.profiles = [dict(stream=str(p.stream_type()), fps=p.fps()) for p in selected]
            self.sensor.open(selected)
            self.opened = True
            self.stream = self.path.open('x', encoding='utf-8')
            self.worker = threading.Thread(target=self._write, name='exchange-motion-writer')
            self.worker.start()
            self.sensor.start(self._observe)
            self.started = True
        except Exception as exc:
            self.reason = str(exc)

    def _observe(self, frame):
        try:
            vector = frame.as_motion_frame().get_motion_data()
            self.queue.put_nowait(dict(stream=str(frame.get_profile().stream_type()),
                frame_number=frame.get_frame_number(), timestamp_ms=frame.get_timestamp(),
                domain=str(frame.get_frame_timestamp_domain()), host_ns=time.perf_counter_ns(),
                xyz=[vector.x, vector.y, vector.z]))
        except queue.Full:
            self.dropped += 1
        except Exception as exc:
            self.reason = str(exc)

    def _write(self):
        try:
            while not self.done.is_set() or not self.queue.empty():
                try:
                    sample = self.queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                self.stream.write(json.dumps(sample, allow_nan=False)+'\n')
                self.saved += 1
        except Exception as exc:
            self.reason = str(exc)

    def close(self):
        for enabled, method in [(self.started, 'stop'), (self.opened, 'close')]:
            if enabled:
                try:
                    getattr(self.sensor, method)()
                except Exception as exc:
                    self.reason = str(exc)
        self.done.set()
        if self.worker and self.worker.ident is not None:
            self.worker.join()
        if self.stream:
            try:
                self.stream.close()
            except OSError as exc:
                self.reason = str(exc)
        return dict(status='RECORDED' if self.saved and not self.reason and not self.dropped else 'WARNING',
                    support=self.capability, saved=self.saved, overflow=self.dropped, profiles=self.profiles, reason=self.reason,
                    accel_units='m/s^2', gyro_units='rad/s')
