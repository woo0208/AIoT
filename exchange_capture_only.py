"""Native Exchange collection with operator events and no live analysis."""
import sys
import time

from e0_fs3 import WINDOW_MS
from e0_panel import OperatorPanel
from exchange_capture import ExchangeCapture
from raw_rgbd_recording import RawRecordingControl, camera_metadata


RGB_PREVIEW_INTERVAL_NS = 100_000_000  # At most ten Tk image updates per second.


class CaptureOnlySession:
    """Track operator-selected windows on the original Depth timestamp."""
    def __init__(self, raw):
        self.raw_recording = raw
        self.armed = False
        self.active = None
        self.segments = []
        self.last_segment_issue = None

    def arm_segment(self):
        with self.raw_recording.exchange.event_lock:
            self.armed = True
            self.raw_recording.observe_measurement(self)

    def cancel_segment(self):
        with self.raw_recording.exchange.event_lock:
            if self.active is not None:
                self.active.update(status='INCOMPLETE', reason='operator_cancel')
            self.armed = False
            self.active = None
            self.raw_recording.observe_measurement(self)

    def observe_pair(self, row, timestamp_ms):
        # Called within the receiver's event lock, so frame and event indices agree.
        if self.armed:
            self.active = dict(segment_index=len(self.segments)+1,
                               first_device_ms=timestamp_ms, status='RECORDING')
            self.segments.append(self.active)
            self.armed = False
        elif self.active is None:
            return
        elif timestamp_ms >= self.active['first_device_ms'] + WINDOW_MS:
            self.active['status'] = 'RECORDED_UNASSESSED'
            self.active = None
        index = row['receive_index']
        reference = dict(clip='raw_rgbd/clip_0001', frame=index, receive_index=index,
                         host_ns=row['receive_end_ns'], sensors={
                             name: {field: row['raw'][key][field]
                                    for field in ('number', 'timestamp_ms', 'timestamp_domain')}
                             for name, key in (('color', 'rgb'), ('depth', 'depth'))})
        self.raw_recording.observe_measurement(self, device_timestamp_ms=timestamp_ms,
                                               frame_reference=reference)


class CaptureOnlyPanel(OperatorPanel):
    def __init__(self, session, *, tk_module=None):
        if tk_module is None:
            import tkinter as tk_module
        super().__init__(session, tk_module=tk_module)
        self.root.title('Research B capture-only / offline analysis')
        self._tk = tk_module
        self._preview_label = self._preview_image = None
        self._next_preview_ns = 0
        if self.raw_recording.exchange.rgb_preview_enabled:
            self._preview_label = tk_module.Label(self.root, text='Waiting for RGB preview')
            self._preview_label.pack()

    def _update_rgb_preview(self, now_ns):
        if self._preview_label is None or now_ns < self._next_preview_ns:
            return
        capture = self.raw_recording.exchange
        bgr = capture.take_rgb_preview()
        if bgr is None:
            return
        self._next_preview_ns = now_ns + RGB_PREVIEW_INTERVAL_NS
        # Tk consumes RGB. Subsampling and byte conversion affect only this display buffer.
        rgb = bgr[::2, ::2, ::-1]
        height, width = rgb.shape[:2]
        ppm = f'P6\n{width} {height}\n255\n'.encode('ascii') + rgb.tobytes()
        try:
            image = self._tk.PhotoImage(master=self.root, data=ppm, format='PPM')
            self._preview_label.configure(image=image, text='')
        except self._tk.TclError as exc:
            print(f'RGB preview disabled: {exc}', file=sys.stderr, flush=True)
            capture.disable_rgb_preview()
            try:
                self._preview_label.destroy()
            except self._tk.TclError:
                pass
            self._preview_label = self._preview_image = None
        else:
            self._preview_image = image  # Keep Tk's photo alive until the next refresh.

    def _raw_instruction(self, code):
        with self.raw_recording.exchange.event_lock:
            if code != self.raw_recording.events.posture:
                self.control.cancel()
            super()._raw_instruction(code)

    def poll(self):
        self.root.update_idletasks()
        self.root.update()
        running = self.control.poll()
        self.status.set(self.control.state)
        self._update_raw_controls()
        if running:
            self._update_rgb_preview(time.perf_counter_ns())
        return running

    def destroy(self):
        self._preview_image = None
        self.root.destroy()


def run_capture_only(root, *, context, environment, record_imu, duration, fps, rgb_preview=False):
    import pyrealsense2 as rs
    from capture_d455 import make_config

    root.mkdir(parents=True)
    raw = RawRecordingControl(root/'raw_rgbd', initial='on', session_context=context)
    capture = ExchangeCapture(raw, environment=environment, record_imu=record_imu,
                              duration=duration, fps=fps, capture_only=True, rgb_preview=rgb_preview)
    raw.exchange = capture
    session = CaptureOnlySession(raw)
    capture.record_measurement = session.observe_pair
    panel = None
    error = None
    termination = 'duration_elapsed'
    try:
        panel = CaptureOnlyPanel(session)
        pipe = rs.pipeline()
        profile = capture.start_pipeline(pipe, make_config, rs)
        raw.bind(lambda: camera_metadata(profile, rs))
        capture.start(pipe, profile, rs)
        print('Capture-only: native RGB-D recording ON. P0-P5, Start 10s, T/Cancel, Q/Close.', flush=True)
        deadline = capture.active_since_ns + int(duration * 1e9)
        while not capture.stop_request.is_set():
            if time.perf_counter_ns() >= deadline:
                break
            if not panel.poll():
                termination = 'panel_closed'
                break
            remaining = (deadline-time.perf_counter_ns()) / 1e9
            capture.stop_request.wait(max(0, min(.05, remaining)))
    except KeyboardInterrupt as exc:
        error, termination = exc, 'keyboard_interrupt'
    except Exception as exc:
        error, termination = exc, 'error'
    actions = [capture.stop]
    if capture.native_source is not None:
        actions.append(capture.native_source.stop)
    if panel is not None:
        actions.append(panel.destroy)
    for action in actions:
        try:
            action()
        except Exception as exc:
            if error is None or isinstance(error, KeyboardInterrupt):
                error, termination = exc, 'error'
    try:
        raw.finish(error=error, termination=termination)
    finally:
        capture.publish(error)
    if error is not None and not isinstance(error, KeyboardInterrupt):
        raise error
