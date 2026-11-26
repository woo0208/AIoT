"""Optional run_probe H9 session; separate from the three-class F1-5 display."""

from collections import Counter
from contextlib import nullcontext

import numpy as np

import h9_async_runtime as host
import h9_m0 as m0


WINDOW_NAME = 'H9 + M0 DEVELOPMENT (not validated)'
FRAME_WAIT_TIMEOUT_MS = 250  # UI/health polling only; not a feature/window threshold


class TimedHostWindow(host.H9HostTimeWindow):
    def __init__(self,model,metrics):
        super().__init__(model)
        self.metrics = metrics

    def _sample(self,end):
        collecting = self._start is None or end-self._start < host.window.WINDOW_MS
        with self.metrics.h9_stage('h9.aggregate',collecting=collecting):
            return super()._sample(end)

    def _predict_sample(self,sample):
        if self._evaluated_version == self._input_version:
            return None
        with self.metrics.h9_stage('h9.m0_infer'):
            return super()._predict_sample(sample)


class H9ProbeSession:
    """Load once, start timer explicitly, consume completed geometry exactly once."""

    def __init__(self,model_path,*,recording_id='h9-probe-development',subject='unknown',metrics=None):
        if not recording_id or not subject:
            raise ValueError('H9 recording_id and subject must be nonempty')
        self.metrics = metrics
        self._displayed_prediction = None
        self.recording_id,self.subject = recording_id,subject
        self.events = Counter()
        self._stopped = False
        with metrics.stage('h9.model_load') if metrics is not None else nullcontext():
            self.model = m0.load_model(model_path)
        self.artifact = host.replay._identity(model_path)
        factory = (lambda model: TimedHostWindow(model,metrics)) if metrics is not None else host.H9HostTimeWindow
        clock = metrics.clock_ns if metrics is not None else host.time.monotonic_ns
        self.runtime = host.H9AsyncRuntime(self.model,clock_ns=clock,sink=self._event,engine_factory=factory)
        self.runner = host.H9TimerRunner(self.runtime)
        if metrics is not None:
            metrics.metadata['h9_model'] = dict(artifact=self.artifact,model_sha256=self.model.metadata['model_sha256'],
                                                 window_ms=4000,update_ms=1000,stale_after_ms=2000)

    def _event(self,row):
        self.events[row['status']] += 1
        if self.metrics is not None and row['status'] == 'PREDICTED':
            self.metrics.h9_prediction_ready(row)

    def start(self):
        try:
            self.runner.start()
        except Exception:
            try:
                self.runner.stop()
            except Exception:
                pass
            raise

    def check_health(self):
        if self.runner.error is not None:
            raise RuntimeError('H9 independent timer failed') from self.runner.error
        if self._stopped:
            raise RuntimeError('H9 session is closed')

    def accept(self,result,*,frame_index,device_timestamp_ms,timestamp_utc='unknown',
               segment_id=None,source_label=None):
        self.check_health()
        return self.runtime.observe_geometry(result,frame_index=frame_index,
                    recording_id=self.recording_id,subject=self.subject,
                    device_timestamp_ms=device_timestamp_ms,timestamp_utc=timestamp_utc,
                    segment_id=segment_id,source_label=source_label)

    def handle_key(self,key):
        if key & 0xff == ord('r'):
            self.check_health()
            self.runtime.manual_reset()
            return True
        return False

    def snapshot(self):
        self.check_health()
        return self.runtime.snapshot()

    def mark_displayed(self,snapshot):
        """One submission-age sample per prediction; redraws never count as new output."""
        prediction = (snapshot or {}).get('display_prediction')
        if prediction is not None and self.metrics is not None:
            identity = prediction['prediction_id']
            if identity != self._displayed_prediction:
                self._displayed_prediction = identity
                generated_ns = int(host.Decimal(prediction['generated_host_ms'])*1_000_000)
                now = self.metrics.clock_ns()
                self.metrics.record_ns('h9.prediction_tick_to_ui_submit',now-generated_ns)
                observed_ns = int(host.Decimal(prediction['source_last_input_host_ms'])*1_000_000)
                self.metrics.record_ns('h9.latest_window_input_to_ui_submit',now-observed_ns)
                self.metrics.h9_ui_submitted(prediction,now)

    def stop(self):
        if not self._stopped:
            self._stopped = True
            self.runner.stop()

    def statistics(self):
        return dict(status_events=dict(self.events),rf_calls=self.runtime.engine.rf_calls,
                    missed_periods=self.runtime.engine.missed_periods_total,
                    timer_error=str(self.runner.error) if self.runner.error else None)


def panel_lines(snapshot):
    state = snapshot or dict(status='COLLECTING',published_status='COLLECTING',reasons=['waiting_for_input'])
    display = state.get('display_prediction')
    return [
        'H9 + M0: DEVELOPMENT ONLY / NOT VALIDATED',
        f"State: {state['status']}   last event: {state.get('published_status',state['status'])}",
        f"Prediction: {display['prediction_label'] if display else '--'}   age ms: {state.get('last_prediction_age_ms') or '--'}",
        'Reason: '+', '.join(state.get('reasons',[]))[:100],
        'r: reset H9 | unknown input: no automatic transition/P5 detection',
    ]


def draw_panel(snapshot,width=800):
    import cv2
    image = np.zeros((165,width,3),dtype=np.uint8)
    for i,line in enumerate(panel_lines(snapshot)):
        cv2.putText(image,line,(12,25+i*29),cv2.FONT_HERSHEY_SIMPLEX,.50,(235,235,235),1,cv2.LINE_AA)
    return image
