"""Manual stable-hold UI: no posture labels, calibration or automatic capture."""
from e0_fs3 import E0Session
from e0_model import load_fs3, environment_record
import sys


class OperatorControl:
    def __init__(self,session):
        self.session=session
        self.running=True
        self.state='READY'
        self._seen=0

    def start(self):
        if not self.running or self.session.active is not None or self.session.armed:return False
        self.session.arm_segment()
        self.state='ARMED'
        raw=getattr(self.session,'raw_recording',None)
        if raw is not None:raw.observe_measurement(self.session)
        return True

    def cancel(self):
        if self.session.active is not None or self.session.armed:
            self.session.cancel_segment()
            self._seen=len(self.session.segments)
            self.state='CANCELLED'
            raw=getattr(self.session,'raw_recording',None)
            if raw is not None:raw.observe_measurement(self.session)

    def close(self):
        self.cancel()
        self.running=False
        self.state='CLOSED'

    def poll(self):
        if self.session.active is not None:self.state='COLLECTING'
        elif self.session.last_segment_issue is not None:
            self._seen=len(self.session.segments)
            self.state=self.session.last_segment_issue
        elif len(self.session.segments)>self._seen:
            self._seen=len(self.session.segments)
            status=self.session.segments[-1]['status']
            self.state={'PREDICTED':'COMPLETED','RECORDED_UNASSESSED':'RECORDED_UNASSESSED',
                        'INELIGIBLE':'INELIGIBLE','INCOMPLETE':'CANCELLED'}.get(status,'ERROR')
        return self.running


class OperatorPanel:
    def __init__(self,session,*,tk_module=None):
        if tk_module is None:import tkinter as tk_module
        self.control=OperatorControl(session)
        self.root=tk_module.Tk()
        self.root.title('E0 FS3: stable 10-second hold / engineering only')
        self.status=tk_module.StringVar(value='READY')
        tk_module.Label(self.root,textvariable=self.status).pack()
        tk_module.Label(self.root,text='Stable posture: Enter/Start. Transition/stop: T/Cancel. Q: close.').pack()
        tk_module.Button(self.root,text='Start 10s',command=self.control.start).pack()
        tk_module.Button(self.root,text='Cancel',command=self.control.cancel).pack()
        tk_module.Button(self.root,text='Close',command=self.control.close).pack()
        self._add_raw_controls(tk_module)
        self.pressed=set()
        self.root.bind('<KeyPress>',self._key)
        self.root.bind('<KeyRelease>',lambda event:self.pressed.discard(event.keysym))
        self.root.bind('<FocusOut>',lambda event:self.control.cancel())
        self.root.protocol('WM_DELETE_WINDOW',self.control.close)

    def _key(self,event):
        key=event.keysym
        if key in self.pressed:return 'break'
        self.pressed.add(key)
        if key=='Return':self.control.start()
        elif key.lower()=='t' or key=='Escape':self.control.cancel()
        elif key.lower()=='q':self.control.close()
        return 'break'

    def _add_raw_controls(self, tk_module):
        self.raw_recording = getattr(self.control.session, 'raw_recording', None)
        if self.raw_recording is None:
            return
        self.raw_status = tk_module.StringVar(value=self.raw_recording.display())
        tk_module.Label(self.root, textvariable=self.raw_status, wraplength=760).pack()
        self.raw_button = tk_module.Button(self.root, text='원본 저장 ON/OFF', command=self._toggle_raw,
                                          takefocus=False)
        exchange = getattr(self.raw_recording, 'exchange', None)
        if exchange is not None:
            if exchange.guided:
                self.raw_button.configure(text='원본 녹화 시작')
            else:
                self.raw_button.configure(text='교환용 원본 저장 ON', state='disabled')
        self.raw_button.pack()
        if self.raw_recording.events is not None:
            identity=self.raw_recording.events.context
            tk_module.Label(self.root,text=f"참가자 {identity['participant_id'] or 'UNASSIGNED'} / "
                f"{identity['session_label'] or 'UNASSIGNED'} — 실제 움직임 시각 UNANNOTATED").pack()
            if not hasattr(self.control,'expected'):
                from capture_six_pilot import NAMES
                bar=tk_module.Frame(self.root);bar.pack()
                for index,name in enumerate(NAMES):
                    tk_module.Button(bar,text=f'P{index} {name}',takefocus=False,
                        command=lambda index=index:self._raw_instruction(f'P{index}')).pack(side='left')

    def _raw_instruction(self,code):
        self.raw_status.set(f'자세 안내 {code} (실제 움직임 UNANNOTATED)')
        self.raw_recording.instruction(code)
        self.raw_status.set(self.raw_recording.display())

    def _toggle_raw(self):
        from raw_rgbd_recording import RawRecordingError
        try:
            self.raw_recording.set_enabled(not self.raw_recording.requested)
        except RawRecordingError:
            pass  # Tk swallows callback exceptions; poll propagates logger health.
        self.raw_status.set(self.raw_recording.display())
        if getattr(getattr(self.raw_recording, 'exchange', None), 'guided', False) and self.raw_recording.requested:
            self.raw_button.configure(text='원본 녹화 중', state='disabled')

    def _update_raw_controls(self):
        if self.raw_recording is not None:
            self.raw_status.set(self.raw_recording.display())
            self.raw_recording.check_health()

    def poll(self):
        with self.control.session.timing.stage('ui.tk_idle'):
            self.root.update_idletasks()
        with self.control.session.timing.stage('ui.tk_update'):
            self.root.update()
        running=self.control.poll()
        self.status.set(self.control.state)
        self._update_raw_controls()
        return running

    def close(self):
        self.control.close();self.root.destroy()


def run_bound_probe(path,binding,directory,*,execution_authorized=False,pc_id='PC_UNSPECIFIED',mode='summary',
                    panel_factory=OperatorPanel,probe_runner=None,save_raw=None,recording_context=None,
                    exchange_options=None,engineering_test=False):
    """Future explicit engineering invocation; no CLI or implicit authorization."""
    if not execution_authorized:raise PermissionError('E0 execution not authorized')
    guided_exchange = exchange_options is not None and exchange_options.get('guided', False)
    if exchange_options is not None and (save_raw != ('off' if guided_exchange else 'on') or recording_context is None):
        raise ValueError('Exchange capture requires the mode-specific raw state and explicit participant context')
    if engineering_test and (not guided_exchange or any(
            recording_context.get(key) is not None for key in ('participant_id', 'session_label', 'repetition'))):
        raise ValueError('Guided engineering requires unregistered guided exchange capture')
    if save_raw not in (None, 'on', 'off') or (save_raw is not None and mode == 'off'):
        raise ValueError('Raw recording controls require measured session and on/off state')
    model,scaler,verified=load_fs3(path,binding['artifact_sha256'],binding['feature_ids'],
        expected_model_sha256=binding['model_sha256'],expected_scaler_sha256=binding['scaler_sha256'])
    session=E0Session(directory,model,scaler,mode=mode,model_binding=verified)
    session.environment_metadata=environment_record(pc_id)
    if engineering_test:
        session.environment_metadata['guided_engineering_test'] = True
    raw_recording = None
    if save_raw is not None:
        from raw_rgbd_recording import RawRecordingControl
        raw_recording = RawRecordingControl(session.directory/'raw_rgbd', initial=save_raw,
            scope='NON_FORMAL_GUIDED_ENGINEERING_TEST' if engineering_test else session.scope,
            model_binding=verified,session_context=recording_context,
            clock_ns=session.clock_ns)
        if exchange_options is not None:
            from exchange_capture import ExchangeCapture
            raw_recording.exchange = ExchangeCapture(raw_recording, **exchange_options)
        session.raw_recording = raw_recording
    panel=None
    if probe_runner is None:
        from posture_geometry_probe import run_probe
        probe_runner=run_probe
    try:
        panel=panel_factory(session)
        options = dict(e0_session=session,ui_poll=panel.poll,show_3d_views='none')
        if guided_exchange:
            options['ui_stop_reason'] = panel.stop_reason
        if raw_recording is not None:
            options['raw_recording'] = raw_recording
        probe_runner(**options)
    finally:
        try:
            if raw_recording is not None:
                raw_recording.finish(error=sys.exc_info()[1])
        finally:
            try:
                if panel is not None:
                    panel.close()
            finally:
                if raw_recording is not None and raw_recording.exchange is not None:
                    raw_recording.exchange.publish(sys.exc_info()[1])
    return session
