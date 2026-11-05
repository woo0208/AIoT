"""Engineering-only Bundle C evidence analysis and deterministic microbenchmarks.

No camera streaming, dataset loading, model fit, or formal evaluation. Paths
must be explicit. Live B repetitions are never promoted to strict A/B pairs.
"""
import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path
import statistics
import time

import engineering_exports as out
import performance_output as perf
from probe_timing import ProbeMetrics, _stats, process_memory


def differences(a, b):
    return dict(before=a, after=b, absolute_difference=b-a,
                relative_change_percent=(b-a)/a*100 if a else None)


def analyze_run(directory):
    directory = Path(directory)
    document = json.loads((directory / 'performance.json').read_text(encoding='utf-8'))
    timing = json.loads((directory / 'host_timing.json').read_text(encoding='utf-8'))
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    journal = [json.loads(line) for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    checks = dict(timing_equals_embedded=timing == document['timing'], journal_equals_events=journal == document['events'],
        journal_hash=perf.sha256(directory / 'events.jsonl') == document['journal_sha256'],
        manifest_identity=all(manifest[k] == document[k] for k in ('run_id', 'config', 'config_sha256', 'source_sha256')),
        config_hash=out.digest(document['config']) == document['config_sha256'],
        processed_fps=timing['counts']['processed_frames']/timing['stream_seconds'] == timing['processed_fps'],
        delivered_fps=timing['counts']['input_framesets']/timing['stream_seconds'] == timing['delivered_input_fps'])
    checks['event_sequence'] = [r['sample_index'] for r in journal] == list(range(1,len(journal)+1))
    checks['raw_event_counts'] = all(timing['counts'].get(key,0) == sum(r['kind']==kind for r in journal)
        for key,kind in (('input_framesets','input'),('processed_frames','frame_completed'),
                         ('receive_timeouts','receive_timeout'),('duration_boundary_frames_skipped','deadline_skip'),
                         ('missing_color_or_depth','invalid_pair')))
    checks['raw_resource_statistics'] = all(stats == _stats([r[name] for r in journal if r['kind']=='resource'
        and r['phase']==phase and r.get(name) is not None])
        for phase,values in timing['process_resource_summary'].items() for name,stats in values.items())
    projected = perf.csv_rows(document)
    for name, fields in perf.CSV_FIELDS.items():
        with (directory / name).open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            actual, header = list(reader), reader.fieldnames
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fields, lineterminator='\n')
        writer.writeheader(); writer.writerows(projected[name]); buffer.seek(0)
        checks[name] = header == list(fields) and actual == list(csv.DictReader(buffer))
    stage_rows = [r for r in journal if r['kind'] == 'stage']
    for phase, key in (('steady', 'stage_milliseconds'), ('warmup', 'warmup_stage_milliseconds'),
                       ('collection', 'collection_stage_milliseconds')):
        checks[key] = all(_stats([r['duration_ns']/1e6 for r in stage_rows if r['name'] == name and r['phase'] == phase]) == stats
                          for name, stats in timing[key].items())
    quantization = {}
    for name in sorted({r['name'] for r in stage_rows}):
        raw = [r['duration_ns'] for r in stage_rows if r['name'] == name]
        quantization[name] = dict(samples=len(raw), zero_count=raw.count(0),
            all_integer_milliseconds=all(n % 1_000_000 == 0 for n in raw),
            most_common_ns=Counter(raw).most_common(10))
    host_stamps = sorted({r['host_monotonic_ns'] for r in journal if 'host_monotonic_ns' in r})
    deltas = [b-a for a, b in zip(host_stamps, host_stamps[1:])]
    sensors = {name: {r['metric']: dict(value=r.get('value'), status=r['measurement_status']) for r in projected['performance_runs.csv']
                      if r['metric'] in {name+suffix for suffix in ('unique_frames','reused_deliveries','unique_fps','missing_rate')}}
               for name in ('rgb_', 'depth_')}
    return dict(path=str(directory), run_id=document['run_id'], run_status=document['run_status'], checks=checks,
        source_sha256=document['source_sha256'], config=document['config'], environment=document['environment'],
        processed_fps=timing['processed_fps'], delivered_fps=timing['delivered_input_fps'],
        seconds=timing['stream_seconds'], counts=timing['counts'], error=timing['error'], cleanup_errors=timing['cleanup_errors'],
        stages=timing['stage_milliseconds'], resources=timing['process_resource_summary']['stream'],
        sensor_metrics=sensors, quantization=quantization, unique_host_stamp_step_ns=Counter(deltas).most_common(8),
        events=len(journal), event_bytes=(directory / 'events.jsonl').stat().st_size,
        attribution='NONHUMAN_LIVE_OBSERVATION; no classification accuracy evidence')


def analyze_baselines(root):
    runs = [analyze_run(Path(root) / f'BASELINE_{i:02}') for i in (1, 2, 3)]
    fps = [r['processed_fps'] for r in runs]
    return dict(kind='bundle-c-b-baseline-analysis/1', runs=runs,
        all_checks_passed=all(all(r['checks'].values()) for r in runs),
        processed_total=sum(r['counts']['processed_frames'] for r in runs),
        delivered_total=sum(r['counts']['input_framesets'] for r in runs),
        processed_fps_mean=statistics.mean(fps), processed_fps_sample_sd=statistics.stdev(fps),
        processed_fps_range=[min(fps), max(fps)],
        strict_timing_performance_ab=dict(status='BLOCKED', reason='B contains only performance runs; no identical-input timing-only pair'),
        after_live=dict(status='NOT_MEASURED', reason='No new live acquisition; identical scene replay not available'))


def clock_diagnostic(samples=2000):
    raw = []
    for delay_ns in (0, 100_000, 500_000, 2_000_000):
        for _ in range(100):
            a, x = time.monotonic_ns(), time.perf_counter_ns()
            while time.perf_counter_ns() - x < delay_ns:
                pass
            y, b = time.perf_counter_ns(), time.monotonic_ns()
            raw.append(dict(requested_busy_ns=delay_ns, monotonic_ns=b-a, perf_counter_ns=y-x))
    steps = {}
    for name, clock in (('monotonic', time.monotonic_ns), ('perf_counter', time.perf_counter_ns)):
        values = [clock() for _ in range(samples)]
        deltas = [b-a for a, b in zip(values, values[1:])]
        steps[name] = dict(zero_steps=deltas.count(0), total_steps=len(deltas),
                           positive_min_ns=min((d for d in deltas if d), default=None))
    sleeps = []
    for _ in range(30):
        start = time.perf_counter_ns(); time.sleep(.001)
        sleeps.append(time.perf_counter_ns() - start)
    return dict(scope='CONTROLLED_CLOCK_DIAGNOSTIC_NOT_D455', clock_info={name:vars(time.get_clock_info(name))
        for name in ('monotonic', 'perf_counter', 'process_time')}, consecutive_steps=steps, raw=raw,
        sleep_requested_ns=1_000_000, sleep_observed_ns=sleeps,
        note='sleep test is not a waitKey benchmark or scheduler-only attribution')


def recorder_microbenchmark(root, *, calls=3000, repeats=3):
    root = Path(root)
    input_sha = out.digest(dict(name='synthetic.work', duration_ns=123456, frame_ids=list(range(1, calls+1))))
    runs = []
    for repeat in range(repeats):
        # Alternate order; each has the exact same event payload sequence.
        for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
            directory = out.reserve(root / f'recorder_{repeat}_{int(enabled)}')
            recorder = perf.PerformanceRecorder(directory / 'performance', config=dict(source='SYNTHETIC_DETERMINISTIC'),
                data_id=out.SYNTHETIC) if enabled else None
            metrics = ProbeMetrics(directory / 'timing.json', performance=recorder,
                memory_reader=lambda:dict(rss_bytes=None, private_bytes=None, os_peak_rss_bytes=None))
            durations = []
            memory_before = process_memory()
            cpu = time.process_time_ns(); start = time.perf_counter_ns()
            for index in range(1, calls+1):
                mark = time.perf_counter_ns()
                metrics.record_ns('synthetic.work', 123456, index)
                durations.append(time.perf_counter_ns()-mark)
            elapsed, used_cpu = time.perf_counter_ns()-start, time.process_time_ns()-cpu
            memory_after = process_memory()
            mark = time.perf_counter_ns(); metrics.finish(); finish = time.perf_counter_ns()-mark
            preserved = True
            if recorder:
                doc = json.loads((recorder.directory/'performance.json').read_text(encoding='utf-8'))
                journal = [json.loads(l) for l in (recorder.directory/'events.jsonl').read_text(encoding='utf-8').splitlines()]
                preserved = doc['events'] == journal and len([e for e in journal if e['kind']=='stage']) == calls
            runs.append(dict(repeat=repeat, mode='performance' if enabled else 'timing_only', input_sha256=input_sha,
                calls=calls, raw_call_ns=durations, call_ms=_stats([n/1e6 for n in durations]), elapsed_ms=elapsed/1e6,
                cpu_one_core_percent=used_cpu/elapsed*100, memory_before=memory_before, memory_after=memory_after,
                finish_ms=finish/1e6, journal_preserved=preserved))
    component = {name:[] for name in ('serialize', 'write', 'flush', 'resource_sample', 'statistics')}
    with (root/'component_journal.jsonl').open('x', encoding='utf-8') as stream:
        for index in range(calls):
            row = dict(kind='stage', sample_index=index+1, name='synthetic.work', frame_id=index+1,
                       phase='steady', duration_ns=123456, host_monotonic_ns=index*1_000_000)
            start=time.perf_counter_ns(); payload=perf.canonical(row)+'\n'
            component['serialize'].append(time.perf_counter_ns()-start)
            start=time.perf_counter_ns(); stream.write(payload)
            component['write'].append(time.perf_counter_ns()-start)
            start=time.perf_counter_ns(); stream.flush()
            component['flush'].append(time.perf_counter_ns()-start)
    for _ in range(30):
        start=time.perf_counter_ns(); process_memory(); time.process_time_ns()
        component['resource_sample'].append(time.perf_counter_ns()-start)
        start=time.perf_counter_ns(); _stats([.123456]*calls)
        component['statistics'].append(time.perf_counter_ns()-start)
    pairs=[]
    for i in range(repeats):
        a,b=[next(r for r in runs if r['repeat']==i and r['mode']==mode) for mode in ('timing_only','performance')]
        pairs.append(dict(repeat=i, call_p50_ms=differences(a['call_ms']['p50'], b['call_ms']['p50']),
                          call_p95_ms=differences(a['call_ms']['p95'], b['call_ms']['p95']),
                          finish_ms=differences(a['finish_ms'], b['finish_ms'])))
    return dict(scope='DETERMINISTIC_RECORDER_MICROBENCHMARK_NOT_D455', runs=runs, pairs=pairs,
        components={k:dict(raw_ns=v, milliseconds=_stats([n/1e6 for n in v])) for k,v in component.items()},
        note='Instrumented call/component costs; no pipeline FPS or statistical significance claim')


def render_microbenchmark(calls=120, repeats=3):
    import numpy as np
    import posture_geometry as geometry
    import posture_geometry_probe as probe
    image=np.zeros((720,1280,3), dtype=np.uint8)
    result=geometry.GeometryResult({}, {}, {})
    def build():
        overlay=geometry.draw_geometry_overlay(image, result)
        return probe.draw_engineering_panel(overlay,result,False,face_detected=False)
    # Warm caches before either condition. No imshow/waitKey/native window.
    for _ in range(5): build()
    raw=[]
    for repeat in range(repeats):
        for render in ((True,False) if repeat%2==0 else (False,True)):
            samples=[]; start=time.perf_counter_ns(); cpu=time.process_time_ns()
            for _ in range(calls):
                mark=time.perf_counter_ns()
                if render: build()
                samples.append(time.perf_counter_ns()-mark)
            elapsed=time.perf_counter_ns()-start
            raw.append(dict(repeat=repeat, render=render, calls=calls, raw_ns=samples,
                milliseconds=_stats([n/1e6 for n in samples]), elapsed_ms=elapsed/1e6,
                cpu_one_core_percent=(time.process_time_ns()-cpu)/elapsed*100))
    return dict(scope='SYNTHETIC_IMAGE_BUILD_MICROBENCHMARK_NOT_D455', input_sha256=out.digest(
        dict(shape=[720,1280,3],pixels='all_zero_uint8',geometry='empty_nonhuman')), runs=raw,
        imshow='NOT_MEASURED', waitKey='NOT_MEASURED', actual_classification='NOT_RUN')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_b'); parser.add_argument('new_directory')
    args=parser.parse_args(argv)
    root=out.reserve(args.new_directory, (args.bundle_b,))
    results=dict(baseline=analyze_baselines(args.bundle_b), clock=clock_diagnostic(),
                 recorder=recorder_microbenchmark(root), render=render_microbenchmark())
    for name,value in results.items(): perf._write_json(root/(name+'.json'), value)
    print(json.dumps(dict(baseline_checks=results['baseline']['all_checks_passed'],
        processed_total=results['baseline']['processed_total'], fps_mean=results['baseline']['processed_fps_mean'],
        recorder_call_p95=[r['call_ms']['p95'] for r in results['recorder']['runs']],
        render_p50=[r['milliseconds']['p50'] for r in results['render']['runs']]),indent=2))


if __name__=='__main__': main()
