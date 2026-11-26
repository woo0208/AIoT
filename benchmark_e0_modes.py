"""E0-P2 synthetic observation overhead, never real RGB-D/model performance.

Fresh processes, fixed identical metadata/geometry, original H9 aggregation,
fitted-state structural estimator fixture and CPU prediction stub. No fit.
All modes share the same external frame timer and CPU/RAM monitor. Worker
telemetry is temporary; only aggregate comparison and private evidence remain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import numpy as np

import e0_fs3 as e0
from e0_resources import ResourceMonitor
import performance_output as output
from probe_timing import _stats
from test_e0_fs3 import estimators, result
from test_frame_provenance import child, pair


MODES=('off','summary','detailed')
CPU_ITERATIONS=8192  # Same deterministic CPU work in all modes; no actual inference.
SOURCE_FILES=('benchmark_e0_modes.py','e0_fs3.py','e0_resources.py','probe_diagnostics.py',
              'posture_geometry_probe.py','f1_sample_aggregator.py','test_e0_fs3.py','test_frame_provenance.py')


def worker(mode, segments):
    model,scaler=estimators()
    # This is a structural fixture, not a fitted research-data classifier.
    model.predict=lambda x:np.array([int(np.sum(x))%6])
    external=ResourceMonitor(gpu_reader=lambda:dict(status='NOT_MEASURED',devices=[]))
    durations=[]
    with tempfile.TemporaryDirectory() as folder, \
         patch.object(type(model),'fit',side_effect=AssertionError('no training')), \
         patch.object(type(scaler),'fit',side_effect=AssertionError('no training')):
        session=e0.E0Session(Path(folder)/'e0',model,scaler,mode=mode,synthetic=True)
        session.backends['svm']=dict(actual='SYNTHETIC_CPU_STUB',status='SYNTHETIC_STRUCTURAL_TEST_ONLY')
        good,bad=result(),result(missing=(8,))
        inputs=hashlib.sha256()
        session.begin_stream();external.start()
        start=time.perf_counter_ns()
        try:
            index=0
            for segment in range(segments):
                session.arm_segment()
                for frame in range(151):
                    index+=1;stamp=segment*11000+frame*10000/150
                    missing=frame%17==0
                    inputs.update(f'{index},{stamp!r},{missing}\n'.encode('ascii'))
                    began=time.perf_counter_ns()
                    sum(k*k for k in range(CPU_ITERATIONS))
                    row=session.begin_receive()
                    color,depth=child(index,stamp),child(index,stamp,uid=2,stream='depth')
                    session.received(row,True,pair(color,depth),session.clock_ns())
                    session.aligned(row,color,depth)
                    session.processing_started(row,index)
                    session.accept(row,bad if missing else good,index,stamp,
                                   pose_detected=True,face_detected=True)
                    session.frame_completed(row)
                    durations.append(time.perf_counter_ns()-began)
            elapsed=time.perf_counter_ns()-start
        finally:
            external.stop()
            session.end_stream()
            publication_start=time.perf_counter_ns()
            session.finish(error=sys.exc_info()[1])
            publication_ns=time.perf_counter_ns()-publication_start
        signature=[{k:s[k] for k in ('input_frames','valid_frames','coverage','eligible','prediction')}
                   for s in session.segments]
        assert len(signature)==segments and all(s['input_frames']==150 and s['valid_frames']==141 for s in signature)
        stats=_stats([x/1e6 for x in durations]);stats['p99']=float(np.percentile(durations,99)/1e6)
        return dict(scope='SYNTHETIC_STRUCTURAL_TEST_ONLY',mode=mode,segments=segments,
            frames=len(durations),input_sha256=inputs.hexdigest(),
            result_sha256=hashlib.sha256(output.canonical(signature).encode('utf-8')).hexdigest(),
            loop_seconds=elapsed/1e9,throughput_fps=len(durations)/(elapsed/1e9),
            frame_milliseconds=stats,frame_duration_ns=durations,
            shutdown_publication_ms=publication_ns/1e6,
            external_resource_summary=external.summary(),external_resources=external.samples,
            internal_resource_summary=session.result_summary['resources'],
            internal_gpu_samples=session.resources.gpu_samples if session.resources is not None else [],
            observer_bytes=sum(p.stat().st_size for p in Path(folder).rglob('*') if p.is_file()))


def summarize(rows):
    stats={}
    for mode in MODES:
        runs=[r for r in rows if r['mode']==mode]
        def median(field):return statistics.median(r[field] for r in runs)
        def resource(name,stat):
            values=[r['external_resource_summary']['statistics'][name][stat] for r in runs]
            values=[x for x in values if x is not None]
            return statistics.median(values) if values else None
        stats[mode]=dict(frame_p95_ms=statistics.median(r['frame_milliseconds']['p95'] for r in runs),
            throughput_fps=median('throughput_fps'),cpu_one_core_p50=resource('process_cpu_one_core_percent','p50'),
            system_cpu_p50=resource('system_cpu_percent','p50'),rss_peak_mib=resource('rss_bytes','maximum')/2**20,
            private_peak_mib=resource('private_bytes','maximum')/2**20,
            shutdown_publication_ms=median('shutdown_publication_ms'),observer_bytes=median('observer_bytes'))
    return stats


def verify_saved(folder):
    saved=json.loads((folder/'local_private/results.json').read_text(encoding='utf-8'))
    assert saved['scope']=='SYNTHETIC_STRUCTURAL_TEST_ONLY'
    assert {r['mode'] for r in saved['runs']}==set(MODES)
    assert len({r['input_sha256'] for r in saved['runs']})==1
    assert len({r['result_sha256'] for r in saved['runs']})==1
    for row in saved['runs']:
        assert row['frames']==row['segments']*151
        assert row['observer_bytes']==0 if row['mode']=='off' else row['observer_bytes']>0
        expected=_stats([x/1e6 for x in row['frame_duration_ns']])
        for key,value in expected.items():assert row['frame_milliseconds'][key]==value
        assert row['frame_milliseconds']['p99']==float(np.percentile(row['frame_duration_ns'],99)/1e6)
        assert row['throughput_fps']==row['frames']/row['loop_seconds']
    assert saved['summary']==summarize(saved['runs'])
    for name,digest in saved['source_sha256'].items():assert output.sha256(Path(__file__).with_name(name))==digest
    report=(folder/'REPORT.md').read_text(encoding='utf-8')
    assert report==report_text(saved)
    print('PASS: same synthetic input/output, all raw timing summaries, resource table and source hashes; no rerun')


def report_text(saved):
    lines=['# E0-P2 synthetic instrumentation overhead','',
        'SYNTHETIC_STRUCTURAL_TEST_ONLY. No camera, footage, training, real MediaPipe/Depth inference or E1 optimization.',
        'Fixed cached geometry/metadata + original H9 aggregation + prediction stub; accelerated input, not real 15FPS.',
        f'Identical deterministic CPU load: sum(k*k for k in range({CPU_ITERATIONS})) per observation; synthetic compute only.',
        f"{saved['repetitions']} fresh processes per mode, {saved['segments']} segments x 151 observations per process. Order rotates.",
        'External frame timer and CPU/RAM observer are identical for OFF/summary/detailed. No warmup exclusion.',
        'Table: median of per-process metrics; p95 is not a pooled or sensor-to-decision p95.', '',
        '|mode|frame p95 ms|throughput frames/s|process CPU p50 % (one core=100)|system CPU p50 %|RSS observed peak MiB|Private observed peak MiB|shutdown publication ms|observer bytes|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for mode,s in saved['summary'].items():
        cell=lambda x:'NOT_MEASURED' if x is None else f'{x:.4f}'
        lines.append('|'+mode+'|'+'|'.join(cell(s[k]) for k in ('frame_p95_ms','throughput_fps','cpu_one_core_p50',
            'system_cpu_p50','rss_peak_mib','private_peak_mib','shutdown_publication_ms','observer_bytes'))+'|')
    lines+=['','All input hashes and functional result hashes agree across modes and repetitions.',
        'Numeric records use bounded checkpoints; processing-loop checkpoint I/O is included in observed timing. No intentional frame skip, queue or backend change.',
        'OFF keeps the same FS3 lifecycle/validation, with timing/metadata/resources/export disabled. Shared harness still has overhead.',
        'CPU deltas and RAM are observed process resources; short runs, OS scheduling, background system load and timer granularity limit interpretation.',
        'Sampled RAM peaks can miss transients; Private is not resident RAM. OS peak is process-lifetime cumulative, hence fresh worker isolation.',
        'Resource boundary samples include observer start/stop. Loop throughput excludes observer join and file publication, reported separately.',
        'GPU inventory/utilization is device-wide when supported. Actual MediaPipe backend, process GPU attribution, SDK queue/drop count and sensor missing rate remain NOT_MEASURED.',
        'This measures synthetic observer cost only; it is not deployed FS3 latency/FPS, a D455 result or evidence of classification improvement.',
        'Evidence: local_private/results.json. No raw images/features/identities or trained models exported. No commit/push.', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',choices=MODES)
    parser.add_argument('--worker-output',type=Path)
    parser.add_argument('--segments',type=int,default=20)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.segments<1 or args.repetitions<1:parser.error('positive counts required')
    if args.worker:
        output._write_json(args.worker_output,worker(args.worker,args.segments));return
    if args.output_dir is None:parser.error('--output-dir required')
    if args.verify:verify_saved(args.output_dir);return
    if args.output_dir.exists():raise FileExistsError(args.output_dir)
    rows=[]
    with tempfile.TemporaryDirectory() as temp:
        for repetition in range(args.repetitions):
            for mode in MODES[repetition%3:]+MODES[:repetition%3]:
                path=Path(temp)/f'{repetition}-{mode}.json'
                subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),
                    '--worker',mode,'--segments',str(args.segments),'--worker-output',str(path)],check=True)
                row=json.loads(path.read_text(encoding='utf-8'));row['repetition']=repetition;rows.append(row)
                print(f'completed synthetic repetition {repetition+1} mode {mode}',flush=True)
    assert len({r['result_sha256'] for r in rows})==1 and len({r['input_sha256'] for r in rows})==1
    saved=dict(scope='SYNTHETIC_STRUCTURAL_TEST_ONLY',segments=args.segments,repetitions=args.repetitions,
        cpu_iterations=CPU_ITERATIONS,
        runs=rows,summary=summarize(rows),source_sha256={name:output.sha256(Path(__file__).with_name(name)) for name in SOURCE_FILES})
    (args.output_dir/'local_private').mkdir(parents=True)
    output._write_json(args.output_dir/'local_private/results.json',saved)
    (args.output_dir/'REPORT.md').write_text(report_text(saved),encoding='utf-8')
    verify_saved(args.output_dir)


if __name__=='__main__':main()
