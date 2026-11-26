"""Real Win32/Tk UI timings on a synthetic screen; no camera, models or training.

Fixed 225 submissions at 15 Hz in each fresh process, three crossed pairs.
This isolates passive UI refresh; it does not benchmark the RGB-D pipeline.
"""
import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from e0_panel import OperatorPanel
from e0_resources import ResourceMonitor
from e0_storage import CheckpointList, write_json, write_rows
from posture_geometry_probe import e0_ui_backend, _e0_ui_key
from probe_diagnostics import ProbeDiagnostics


ORDER = ('E0', 'E1', 'E1', 'E0', 'E0', 'E1')
SOURCES = ('benchmark_ui_native.py', 'e0_panel.py', 'e0_resources.py',
           'e0_storage.py', 'probe_diagnostics.py', 'posture_geometry_probe.py')
SCOPE = 'REAL_UI_SYNTHETIC_SCREEN_ENGINEERING_ONLY'
WINDOW = 'Synthetic screen UI benchmark - no camera'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class UIOnlySession:
    """Controller shim only; any operator interaction interrupts the trial."""
    def __init__(self, timing):
        self.timing = timing
        self.active = None
        self.armed = False
        self.segments = []
        self.last_segment_issue = None
        self.interference = False

    def arm_segment(self):
        self.interference = True
        self.armed = True

    def cancel_segment(self):
        self.interference = True
        self.armed = False


def frame_step(diag, panel, cv, variant, image, index, target_ns, *,
               clock_ns=time.perf_counter_ns, sleep=time.sleep):
    begin = clock_ns()
    with diag.stage('ui.tk_poll', index):
        running = panel.poll()
    after_tk = clock_ns()
    if not running or panel.control.session.interference:
        raise InterruptedError('UI interaction')
    with diag.stage('input.synthetic_wait', index):
        remaining = target_ns-clock_ns()
        if remaining > 0:
            sleep(remaining/1e9)
    ready = clock_ns()
    with diag.stage('ui.render_submit', index):
        cv.imshow(WINDOW, image)
    key_start = clock_ns()
    key = _e0_ui_key(cv, variant)
    key_end = clock_ns()
    diag.record_ns('ui.key_wait', key_end-key_start, index)
    end = clock_ns()
    diag.record_ns('latency.synthetic_ready_to_complete', end-ready, index)
    diag.record_ns('latency.loop_start_to_frame_complete', end-begin, index)
    diag.record_ns('ui.work_sum', after_tk-begin+end-ready, index)
    if key >= 0:
        raise InterruptedError('Key input')  # Never retain actual key values/text.
    return dict(frame_id=index, key_wait_ns=key_end-key_start, tk_poll_ns=after_tk-begin,
                synthetic_ready_ns=ready, target_ns=target_ns, end_ns=end,
                loop_ns=end-begin, late_more_than_period=False)


def worker(directory, variant, frames, fps):
    import cv2 as cv
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    diag = ProbeDiagnostics(directory/'timing', include_p99=True, redact_errors=True,
                            retain_raw=False, buffer_limit=256)
    resources = ResourceMonitor(gpu_reader=lambda:dict(status='NOT_MEASURED', devices=[]))
    resources.enable_checkpoints(directory/'buffers'/'resources', 256)
    rows = CheckpointList(directory/'buffers'/'frames', 256)
    panel = None
    started = None
    error = None
    cleanup = []
    result = dict(scope=SCOPE, variant=variant, requested_frames=frames, input_fps=fps,
                  clock='time.perf_counter_ns', interaction='PASSIVE_REFRESH',
                  no_camera=True, no_inference=True, physical_display_latency='NOT_MEASURED',
                  gpu_usage='NOT_MEASURED', imports_excluded_from_setup_time=True)
    setup = time.perf_counter_ns()
    try:
        result['highgui_backend'] = e0_ui_backend(cv, variant)
        if result['highgui_backend'] != 'WIN32':
            raise RuntimeError('This comparison requires WIN32 for both variants')
        session = UIOnlySession(diag)
        panel = OperatorPanel(session)
        panel.root.title('Synthetic UI benchmark - no camera/model - do not interact')
        screen_w, screen_h = panel.root.winfo_screenwidth(), panel.root.winfo_screenheight()
        width, height = min(960, screen_w-60), min(540, screen_h-320)
        if width < 640 or height < 360:
            raise RuntimeError('Insufficient visible desktop area')
        panel_x = width+40 if screen_w >= width+640 else 20
        panel_y = 20 if panel_x != 20 else height+60
        panel.root.geometry(f'580x230+{panel_x}+{panel_y}')
        def interaction(event):
            session.interference = True
            return panel._key(event)
        panel.root.bind('<KeyPress>', interaction)
        panel.root.bind('<ButtonPress>', lambda event:setattr(session, 'interference', True))
        cv.namedWindow(WINDOW, cv.WINDOW_NORMAL)
        cv.resizeWindow(WINDOW, width, height)
        cv.moveWindow(WINDOW, 20, 20)
        image = np.full((720,1280,3), 24, dtype=np.uint8)
        for y in range(0,720,80):
            for x in range(0,1280,80):
                image[y:y+40,x:x+40] = (60,100,150)
        cv.putText(image, 'SYNTHETIC UI ONLY - NO CAMERA / NO MODEL', (40,360),
                   cv.FONT_HERSHEY_SIMPLEX, 1.1, (240,240,240), 2)
        result.update(frame_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                      image_shape=list(image.shape), window_size=[width,height],
                      screen_size=[screen_w,screen_h], tkinter_version=str(panel.root.tk.call('info','patchlevel')),
                      opencv_version=cv.__version__, setup_ns=time.perf_counter_ns()-setup)
        resources.start()
        started = time.perf_counter_ns()
        for i in range(frames):
            row = frame_step(diag, panel, cv, variant, image, i+1,
                             started+round((i+1)*1e9/fps))
            row['late_more_than_period'] = row['synthetic_ready_ns']-row['target_ns'] > 1e9/fps
            rows.append(row)
            resources.check_health()
            if i == 0:
                result['api_windows_visible'] = bool(panel.root.winfo_viewable() and
                    cv.getWindowProperty(WINDOW, cv.WND_PROP_VISIBLE) >= 1)
                if not result['api_windows_visible']:
                    raise RuntimeError('Native windows not visible')
        result['duration_ns'] = time.perf_counter_ns()-started
    except Exception as exc:
        error = exc
        if started is not None:result['duration_ns'] = time.perf_counter_ns()-started
    finally:
        for action in ([resources.stop] if started is not None else []) + (
                [panel.close] if panel is not None else []) + [cv.destroyAllWindows]:
            try:action()
            except Exception as exc:cleanup.append(type(exc).__name__)
        rows.flush()
        result.update(status='COMPLETED' if error is None and not cleanup else 'INTERRUPTED' if
                      isinstance(error,InterruptedError) else 'FAILED',
                      error_type=type(error).__name__ if error else None, cleanup_errors=cleanup,
                      submitted_frames=len(rows),
                      late_more_than_period=sum(r['late_more_than_period'] for r in rows),
                      resources=resources.summary())
        if result.get('duration_ns',0)>0:
            result['submitted_fps']=len(rows)/(result['duration_ns']/1e9)
        diag.finish(status=result['status'],error=error)
        write_rows(directory/'frames.jsonl',rows)
        write_rows(directory/'resources.jsonl',resources.samples)
        write_json(directory/'result.json',result)
    if error is not None or cleanup:
        raise RuntimeError('UI trial incomplete; numeric diagnostics preserved') from None


def summarize(runs):
    table = {}
    for variant in ('E0','E1'):
        selected = [r for r in runs if r['variant']==variant]
        def median_stage(name, stat):
            return statistics.median(r['stages'][name][stat] for r in selected)
        table[variant] = dict(key_p50_ms=median_stage('ui.key_wait','p50'),
            key_p95_ms=median_stage('ui.key_wait','p95'), key_p99_ms=median_stage('ui.key_wait','p99'),
            key_worst_ms=max(r['stages']['ui.key_wait']['maximum'] for r in selected),
            tk_p95_ms=median_stage('ui.tk_poll','p95'),
            render_to_complete_p95_ms=median_stage('latency.synthetic_ready_to_complete','p95'),
            loop_p95_ms=median_stage('latency.loop_start_to_frame_complete','p95'),
            submitted_fps=statistics.median(r['submitted_fps'] for r in selected),
            cpu_one_core_p95=statistics.median(r['resources']['statistics']['process_cpu_one_core_percent']['p95'] for r in selected),
            rss_worst_mib=max(r['resources']['statistics']['rss_bytes']['maximum'] for r in selected)/2**20)
    return table


def report_text(saved):
    lines=['# Actual native UI benchmark with synthetic screen','',
        '**REAL_UI_SYNTHETIC_SCREEN_ENGINEERING_ONLY**. Actual perf_counter_ns timings; real Tk/Win32 windows.',
        'No camera, RGB-D replay, MediaPipe, model load/fit/prediction, participant data or raw image export.',
        'Three crossed pairs: E0/E1, E1/E0, E0/E1. Fresh process per trial; passive refresh, no scripted drag/key injection.',
        f"Each trial: {saved['frames']} identical 1280x720 synthetic image submissions paced at {saved['fps']} Hz; no frame skipping.",
        'Initialization precedes the timed loop and is recorded separately; every timed frame including the first is retained.',
        'UI uses existing OperatorPanel, common Tk stages, and the same E0/E1 key helper. GPU query disabled equally.',
        'Rows below are medians of three per-trial percentiles, not pooled percentiles. Worst values are maxima across trials.', '',
        '|variant|key p50 ms|key p95 ms|key p99 ms|worst key ms|Tk poll p95 ms|render-to-complete p95 ms|paced loop p95 ms|submitted FPS|CPU p95 one-core %|worst sampled RSS MiB|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    columns=('key_p50_ms','key_p95_ms','key_p99_ms','key_worst_ms','tk_p95_ms',
             'render_to_complete_p95_ms','loop_p95_ms','submitted_fps','cpu_one_core_p95','rss_worst_mib')
    for variant in ('E0','E1'):
        row=saved['summary'][variant]
        lines.append('|'+variant+'|'+'|'.join(f'{row[key]:.4f}' for key in columns)+'|')
    lines += ['', 'Submitted FPS is capped by 15 Hz input pacing; this is not maximum throughput or D455 processing FPS.',
        'Tk poll includes nested idle/update stages; do not add their percentiles. Loop latency includes synthetic input waiting.',
        'CPU/RAM describe this UI-only process. GPU utilization, sensor loss, features and SVM success are NOT_MEASURED.',
        'This tests passive event-pump overhead, not the earlier rare window-interaction stalls or physical display latency.',
        'It cannot establish full RGB-D pipeline speedup, posture accuracy/recall, or generalization to other machines.',
        'Numeric per-trial evidence and source hashes: local_private/results.json and trial subfolders.',
        'No original research data changed. No commit/push performed by this benchmark.', '']
    delta=saved['summary']['E1']['key_p95_ms']-saved['summary']['E0']['key_p95_ms']
    change=100*delta/saved['summary']['E0']['key_p95_ms']
    lines += ['## 해석', '',
        f'UI 키/이벤트 호출 p95의 E1−E0 관측 차이는 {delta:+.4f}ms ({change:+.2f}%)다.',
        '이 수치는 세 실행별 p95의 중앙값 차이이며 통계적 유의성이나 다른 장치로의 일반화를 주장하지 않는다.',
        '15FPS 입력 제한에서 FPS가 비슷하다는 것만으로 처리 여유나 최대 처리량이 같다고 결론내리지 않는다.',
        'Tk poll·화면 제출을 함께 보고, CPU/RAM의 작은 차이로 전체 RGB-D 개선을 주장하지 않는다.',
        '이번 수동 조작 없는 합성 화면 조건은 과거 준비 중 발생한 0.5~1초 UI 정지를 재현한 시험이 아니다.', '']
    return '\n'.join(lines)


def verify(directory):
    directory=Path(directory)
    saved=read(directory/'local_private/results.json')
    assert [r['variant'] for r in saved['runs']]==list(ORDER)
    assert len({r['frame_sha256'] for r in saved['runs']})==1
    assert len({tuple(r['window_size']) for r in saved['runs']})==1
    for index,run in enumerate(saved['runs'],1):
        assert run['status']=='COMPLETED' and run['api_windows_visible']
        assert run['submitted_frames']==saved['frames']
        folder=directory/'local_private'/f'{index}_{run["variant"]}'
        raw=[json.loads(line) for line in (folder/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len(raw)==saved['frames'] and [r['frame_id'] for r in raw]==list(range(1,len(raw)+1))
        assert math.isclose(run['submitted_fps'],len(raw)/(run['duration_ns']/1e9))
        key=np.array([r['key_wait_ns']/1e6 for r in raw])
        for p in (50,95,99):assert math.isclose(run['stages']['ui.key_wait'][f'p{p}'],float(np.percentile(key,p)),rel_tol=1e-12)
        assert run['late_more_than_period']==sum(r['late_more_than_period'] for r in raw)
    assert saved['summary']==summarize(saved['runs'])
    assert (directory/'REPORT.md').read_text(encoding='utf-8')==report_text(saved)
    for n,digest in saved['source_sha256'].items():
        current=Path(__file__).with_name(n)
        if hashlib.sha256(current.read_bytes()).hexdigest()!=digest:
            # Historical measurement source must be pinned, never relabel results
            # with the hash of a later report/verification-only correction.
            archived=directory/'local_private'/'measurement_sources'/n
            assert hashlib.sha256(archived.read_bytes()).hexdigest()==digest
    print('PASS: actual UI frame counts, raw key percentiles, input identity, summary/report and source hashes')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--worker',choices=('E0','E1'))
    parser.add_argument('--frames',type=int,default=225)
    parser.add_argument('--fps',type=float,default=15.)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args(argv)
    if args.frames<1 or not math.isfinite(args.fps) or args.fps<=0:
        parser.error('positive frame count and finite positive fps required')
    if args.verify:verify(args.output_dir);return
    if args.worker:worker(args.output_dir,args.worker,args.frames,args.fps);return
    args.output_dir.mkdir(parents=True,exist_ok=False)
    private=args.output_dir/'local_private';private.mkdir()
    saved=dict(scope=SCOPE,frames=args.frames,fps=args.fps,order=list(ORDER),
        rest_between_processes_seconds=1,source_sha256={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in SOURCES},runs=[])
    write_json(private/'plan.json',saved)
    for index,variant in enumerate(ORDER,1):
        folder=private/f'{index}_{variant}'
        result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),
            '--worker',variant,'--frames',str(args.frames),'--fps',str(args.fps),'--output-dir',str(folder)],
            capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
            timeout=max(60,args.frames/args.fps*4+30))
        if result.returncode:
            print(f'TRIAL_FAILED: {index} {variant}; evidence retained at {folder}',flush=True)
            raise RuntimeError('Native UI trial failed; no automatic retry')
        row=read(folder/'result.json')
        row['stages']={x['name']:x for x in read(folder/'timing/diagnostics.json')['stage_milliseconds']}
        saved['runs'].append(row)
        print(f'Completed {index}/6: {variant}, frames={row["submitted_frames"]}, key p95={row["stages"]["ui.key_wait"]["p95"]:.4f} ms',flush=True)
        if index<len(ORDER):time.sleep(1)
    saved['summary']=summarize(saved['runs'])
    write_json(private/'results.json',saved)
    (args.output_dir/'REPORT.md').write_text(report_text(saved),encoding='utf-8')
    verify(args.output_dir)


if __name__=='__main__':main()
