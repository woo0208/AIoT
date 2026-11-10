"""Manual stable-hold UI: no posture labels, calibration or automatic capture."""
from e0_fs3 import E0Session
from e0_model import load_fs3, environment_record


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
        return True

    def cancel(self):
        if self.session.active is not None or self.session.armed:
            self.session.cancel_segment()
            self._seen=len(self.session.segments)
            self.state='CANCELLED'

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
            self.state={'PREDICTED':'COMPLETED','INELIGIBLE':'INELIGIBLE','INCOMPLETE':'CANCELLED'}.get(status,'ERROR')
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

    def poll(self):
        with self.control.session.timing.stage('ui.tk_idle'):
            self.root.update_idletasks()
        with self.control.session.timing.stage('ui.tk_update'):
            self.root.update()
        running=self.control.poll()
        self.status.set(self.control.state)
        return running

    def close(self):
        self.control.close();self.root.destroy()


def run_bound_probe(path,binding,directory,*,execution_authorized=False,pc_id='PC_UNSPECIFIED',mode='summary',
                    panel_factory=OperatorPanel,probe_runner=None):
    """Future explicit engineering invocation; no CLI or implicit authorization."""
    if not execution_authorized:raise PermissionError('E0 execution not authorized')
    model,scaler,verified=load_fs3(path,binding['artifact_sha256'],binding['feature_ids'],
        expected_model_sha256=binding['model_sha256'],expected_scaler_sha256=binding['scaler_sha256'])
    session=E0Session(directory,model,scaler,mode=mode,model_binding=verified)
    session.environment_metadata=environment_record(pc_id)
    panel=panel_factory(session)
    if probe_runner is None:
        from posture_geometry_probe import run_probe
        probe_runner=run_probe
    try:
        probe_runner(e0_session=session,ui_poll=panel.poll,show_3d_views='none')
    finally:
        panel.close()
    return session
