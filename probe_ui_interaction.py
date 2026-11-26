"""Observe owned synthetic UI windows during Computer Use actions. No input injection.

The external controller writes start/end markers; an observer thread timestamps
them with the same perf_counter_ns used by the UI calls. No camera or model.
"""
import argparse
import json
from pathlib import Path
import threading
import time

import numpy as np

from benchmark_ui_native import UIOnlySession, frame_step
from e0_panel import OperatorPanel
from e0_storage import CheckpointList, write_json, write_rows
from probe_diagnostics import ProbeDiagnostics
from posture_geometry_probe import e0_ui_backend


ACTIONS = ('cv_move','cv_resize','tk_focus','tk_move','tk_resize','cv_focus')
CV_TITLE = 'UI interaction probe - OpenCV'
TK_TITLE = 'UI interaction probe - Tk'


class EventLog:
    def __init__(self, limit=4096, clock_ns=time.perf_counter_ns):
        self.rows=[];self.limit=limit;self.clock_ns=clock_ns;self.lock=threading.Lock()

    def add(self, kind, **values):
        row=dict(kind=kind,perf_ns=self.clock_ns(),**values)
        with self.lock:
            if len(self.rows)>=self.limit:raise RuntimeError('Event limit reached')
            self.rows.append(row)
        return row


class MarkerObserver:
    def __init__(self, directory, events):
        self.directory=Path(directory);self.events=events
        self.stop=threading.Event();self.error=None
        self.directory.joinpath('markers').mkdir()
        self.directory.joinpath('acks').mkdir()
        self.thread=threading.Thread(target=self.run,daemon=True)

    def run(self):
        seen=set()
        try:
            while not self.stop.wait(.01):
                for p in sorted((self.directory/'markers').glob('*.json')):
                    if p.name in seen:continue
                    value=json.loads(p.read_text(encoding='utf-8'))
                    if value['action'] not in ACTIONS or value['edge'] not in ('start','end'):
                        raise ValueError('Unsupported marker')
                    event=self.events.add('action',action=value['action'],edge=value['edge'])
                    write_json(self.directory/'acks'/p.name,event)
                    seen.add(p.name)
        except Exception as exc:self.error=type(exc).__name__


class TimedPanel:
    def __init__(self,panel):self.panel=panel;self.control=panel.control;self.span=None
    def poll(self):
        start=time.perf_counter_ns()
        try:return self.panel.poll()
        finally:self.span=(start,time.perf_counter_ns())


class TimedCV:
    def __init__(self,cv):self.cv=cv;self.span=None
    def imshow(self,*args):self.cv.imshow(*args)
    def key(self,name,*args):
        start=time.perf_counter_ns();cpu=time.thread_time_ns()
        try:return getattr(self.cv,name)(*args)
        finally:self.span=(start,time.perf_counter_ns(),time.thread_time_ns()-cpu)
    def waitKey(self,delay):return self.key('waitKey',delay)
    def pollKey(self):return self.key('pollKey')


def overlap(a,b,c,d):
    return max(0,min(b,d)-max(a,c))


def analyze(rows, events, threshold_ms=100):
    markers={}
    for e in events:
        if e['kind']=='action':markers.setdefault(e['action'],{})[e['edge']]=e['perf_ns']
    intervals={k:v for k,v in markers.items() if 'start' in v and 'end' in v}
    long=[]
    for row in rows:
        for prefix in ('key','tk'):
            a,b=row[prefix+'_start_ns'],row[prefix+'_end_ns']
            if b-a < threshold_ms*1e6:continue
            hit=[name for name,v in intervals.items() if overlap(a,b,v['start'],v['end'])>0]
            item=dict(frame_id=row['frame_id'],call=prefix,wall_ms=(b-a)/1e6,actions=hit)
            if prefix=='key':item['thread_cpu_ms']=row['key_cpu_ns']/1e6
            long.append(item)
    return dict(threshold_ms=threshold_ms,marked_actions=sorted(intervals),long_calls=long,
        action_summary={name:dict(marker_bracket_ms=(v['end']-v['start'])/1e6,
            max_key_ms=max((r['key_end_ns']-r['key_start_ns'])/1e6 for r in rows
                if overlap(r['key_start_ns'],r['key_end_ns'],v['start'],v['end'])>0)
                if any(overlap(r['key_start_ns'],r['key_end_ns'],v['start'],v['end'])>0 for r in rows) else None)
            for name,v in intervals.items()})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--variant',choices=('E0','E1'),required=True)
    parser.add_argument('--max-seconds',type=float,default=600)
    args=parser.parse_args(argv)
    if not 1<=args.max_seconds<=900:parser.error('maximum must be 1..900 seconds')
    import cv2 as cv
    import benchmark_ui_native as base
    folder=args.output_dir;folder.mkdir(parents=True,exist_ok=False)
    diag=ProbeDiagnostics(folder/'timing',include_p99=True,redact_errors=True,retain_raw=False,buffer_limit=256)
    rows=CheckpointList(folder/'buffers'/'frames',256)
    events=EventLog();observer=MarkerObserver(folder,events)
    panel=None;error=None;cleanup=[];start=None
    result=dict(scope='CONTROLLED_NATIVE_UI_INTERACTION_ONLY',variant=args.variant,
        clock='time.perf_counter_ns',threshold_ms=100,marker_poll_ms=10,
        no_camera=True,no_model=True,action_plan=list(ACTIONS),
        marker_note='Start ack precedes input API; end ack follows its return. Bracket includes automation overhead, not exact mouse-down/up duration.')
    try:
        backend=e0_ui_backend(cv,args.variant)
        if backend!='WIN32':raise RuntimeError('Win32 only')
        panel=OperatorPanel(UIOnlySession(diag));panel.root.title(TK_TITLE)
        panel.root.geometry('580x230+1020+40')
        for kind,binding in [('tk_configure','<Configure>'),('tk_focus_in','<FocusIn>'),('tk_focus_out','<FocusOut>')]:
            def callback(event,kind=kind):
                if event.widget==panel.root:
                    events.add(kind,x=panel.root.winfo_x(),y=panel.root.winfo_y(),
                               width=panel.root.winfo_width(),height=panel.root.winfo_height())
            panel.root.bind(binding,callback,add='+')
        cv.namedWindow(CV_TITLE,cv.WINDOW_NORMAL)
        cv.resizeWindow(CV_TITLE,960,540);cv.moveWindow(CV_TITLE,20,40)
        image=np.full((720,1280,3),40,dtype=np.uint8)
        cv.putText(image,'CONTROLLED WINDOW ACTIONS - NO CAMERA',(35,350),cv.FONT_HERSHEY_SIMPLEX,1.1,(220,220,220),2)
        # Reuse the measured frame helper while targeting this owned window only.
        base.WINDOW=CV_TITLE
        timed_panel=TimedPanel(panel);timed_cv=TimedCV(cv)
        observer.thread.start()
        start=time.perf_counter_ns();i=0;previous_rect=None
        write_json(folder/'ready.json',dict(scope=result['scope'],variant=args.variant,start_ns=start))
        while time.perf_counter_ns()-start<args.max_seconds*1e9:
            if (folder/'stop').exists():break
            if observer.error:raise RuntimeError('Marker observer failed')
            i+=1
            row=frame_step(diag,timed_panel,timed_cv,args.variant,image,i,start+round(i*1e9/15))
            row.update(key_start_ns=timed_cv.span[0],key_end_ns=timed_cv.span[1],key_cpu_ns=timed_cv.span[2],
                       tk_start_ns=timed_panel.span[0],tk_end_ns=timed_panel.span[1])
            rows.append(row)
            rect=list(cv.getWindowImageRect(CV_TITLE))
            if rect!=previous_rect:events.add('cv_geometry',rect=rect);previous_rect=rect
        result['stream_seconds']=(time.perf_counter_ns()-start)/1e9
        result['termination']='controller_stop' if (folder/'stop').exists() else 'safety_timeout'
    except Exception as exc:error=exc
    finally:
        observer.stop.set()
        if observer.thread.ident is not None:observer.thread.join(timeout=2)
        for action in ([panel.close] if panel else [])+[cv.destroyAllWindows]:
            try:action()
            except Exception as exc:cleanup.append(type(exc).__name__)
        rows.flush()
        result.update(status='FAILED' if error or cleanup else 'COMPLETED',
                      error_type=type(error).__name__ if error else None,cleanup_errors=cleanup,frames=len(rows),
                      observer_error=observer.error)
        result['analysis']=analyze(rows,events.rows)
        diag.finish(status=result['status'],error=error)
        write_rows(folder/'frames.jsonl',rows);write_rows(folder/'events.jsonl',events.rows)
        write_json(folder/'result.json',result)
    if error or cleanup:raise RuntimeError('Probe failed; numeric evidence preserved') from None
    print(json.dumps(dict(status=result['status'],variant=args.variant,frames=len(rows),
                         long_calls=result['analysis']['long_calls']),ensure_ascii=False))


if __name__=='__main__':main()
