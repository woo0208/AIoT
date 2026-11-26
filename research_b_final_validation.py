"""Permission-gated Research B final evaluation. Existing policies are called unchanged."""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time
from unittest.mock import patch


METHODS = ('E0', 'Fixed_2_matched', 'Uniform_85', 'V2_85')
LABELS = tuple(f'P{i}' for i in range(6))
FROZEN_BINDING = {
    'artifact_sha256': 'e9da4811e6549b474219637e77879433829d7e9a1ecdba54ca1ac34dbaafa249',
    'model_sha256': '913bbf2446a770054de8ca6058eb2ca52db7779e0c9342e3719c093e59d4315b',
    'scaler_sha256': '41c051ec8e2293f81aa752562fcc9f81cdc6396a0027ba8bb461cb2617594113',
    'feature_ids': ['F1', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8'],
}
LOCKED_FILES = frozenset(('mediapipe_model_lock.json', 'analyze_d455.py', 'raw_rgbd_recording.py',
    'raw_rgbd_replay.py', 'research_b_preflight.py', 'face_recovery_replay.py', 'adaptive_v2_replay.py',
    'replay_policy.py', 'research_b_fair_replay.py', 'research_b_robustness_replay.py', 'e0_replay.py',
    'e0_fs3.py', 'e0_panel.py', 'e0_model.py', 'e0_resources.py', 'e0_storage.py', 'probe_diagnostics.py',
    'f1_sample_aggregator.py', 'posture_geometry_probe.py', 'posture_geometry.py'))
SOURCE_FILES = {
    'NPZ_CLIP': {'recording.json': 'recording.json', 'frames.jsonl': 'frames.jsonl', 'end.json': 'end.json'},
    'NPZ_SESSION': {'session_manifest_sha256': 'recording_metadata/session_manifest.json'},
    'REALSENSE_FILE': {'file_sha256': None},
}
ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def present(value):
    return isinstance(value, str) and bool(value.strip()) and value not in ('UNKNOWN', 'NOT_TESTED')


def pseudonym(value):
    return present(value) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value) is not None


def validate_intake(intake, binding, roster=None, *, for_replay=True):
    """Validate declarations before resolving, hashing or opening any RGB-D path."""
    from e0_fs3 import WINDOW_MS

    require(intake.get('format') == 'research-b-final-intake/1', 'Unsupported intake format')
    cohort, origin = intake.get('cohort'), intake.get('origin')
    require(cohort in ('ENGINEERING', 'REPEAT', 'INDEPENDENT'), 'Invalid evaluation cohort')
    require(origin in ('LOCAL', 'EXTERNAL'), 'Invalid source origin')
    approval = intake.get('approval', {})
    require(approval.get('status') == 'APPROVED' and approval.get('scope') == cohort
            and present(approval.get('reference')), 'Source-specific human use approval required before reading RGB-D')
    if origin == 'EXTERNAL':
        basename = intake.get('source_basename')
        require(present(basename) and basename not in ('.', '..') and not any(char in basename for char in '/\\:\0'),
                'Approved external source basename required')
    kind = intake.get('source_kind')
    hashes = intake.get('source_hashes', {})
    require(kind in SOURCE_FILES and hashes.keys() == SOURCE_FILES[kind].keys()
            and all(sha(value) for value in hashes.values()), 'Exact approved source hashes required')
    sequence = intake.get('array_and_clock_sequence_sha256')
    require(sequence is None or sha(sequence), 'Invalid approved array-and-clock sequence hash')
    require(all(pseudonym(intake.get(key)) for key in ('session_id', 'clip_id')), 'Session and clip IDs required')
    require(intake.get('clock_domain') in ('timestamp_domain.hardware_clock', 'timestamp_domain.system_time',
            'timestamp_domain.global_time'), 'Source clock domain required')
    if for_replay and (cohort != 'ENGINEERING' or origin == 'EXTERNAL'):
        review = intake.get('pairing_and_calibration_review', {})
        require(review.get('status') == 'VERIFIED' and present(review.get('reference')),
                'Human pairing and calibration review required')
    person = intake.get('participant', {})
    if person.get('status') == 'VERIFIED':
        require(pseudonym(person.get('canonical_id')) and pseudonym(person.get('namespace'))
                and present(person.get('reference')), 'Verified canonical person ID, namespace and reference required')
    else:
        require(person.get('status') == 'UNKNOWN' and person.get('canonical_id') is None,
                'Unknown identity must have no canonical person ID')
    if for_replay and cohort != 'ENGINEERING':
        require(person.get('status') == 'VERIFIED', 'Verified identity required for participant evaluation')
        require(roster is not None and roster.get('format') == 'research-b-model-roster/1'
                and roster.get('status') == 'VERIFIED_COMPLETE' and present(roster.get('reference'))
                and roster.get('artifact_sha256') == binding['artifact_sha256']
                and roster.get('namespace') == person['namespace'], 'Complete human-verified roster for this model and namespace required')
        training = roster.get('training_person_ids')
        development = roster.get('development_person_ids')
        require(isinstance(training, list) and training and isinstance(development, list)
                and all(pseudonym(value) for value in training + development)
                and len(set(training)) == len(training) and len(set(development)) == len(development)
                and present(roster.get('development_reference')), 'Complete fit and development person rosters required')
        seen = person['canonical_id'] in set(training + development)
        require(seen == (cohort == 'REPEAT'), 'Training overlap or incorrect repeat cohort')

    windows = intake.get('windows', [])
    if not windows and not for_replay:
        return intake
    require(isinstance(windows, list) and windows, 'At least one declared measurement window required')
    ids, previous_close = set(), -1
    for window in windows:
        key = window.get('id')
        start, end, close = (window.get(field) for field in ('start_ms', 'end_ms', 'closing_input_ms'))
        require(pseudonym(key) and key not in ids, 'Unique window IDs required')
        require(all(type(value) in (int, float) and math.isfinite(value) and 0 <= value < 2**63 / 1000
                    for value in (start, end, close)) and end == start + WINDOW_MS
                and close >= end and start > previous_close, 'H9 windows require ordered, nonoverlapping source-clock start/end/closing input')
        signal = window.get('start_event', {})
        require(signal.get('kind') in ('RECORDED_OPERATOR_START', 'PRESPECIFIED_ENGINEERING_START')
                and present(signal.get('reference')), 'Operator Start provenance required')
        require(cohort == 'ENGINEERING' or signal['kind'] == 'RECORDED_OPERATOR_START',
                'Participant evaluation requires a recorded operator Start')
        status, label = window.get('label_status'), window.get('label')
        require(status in ('VERIFIED', 'UNVERIFIED') and (label is None or label in LABELS), 'Invalid label or review status')
        if status == 'VERIFIED':
            require(label in LABELS and present(window.get('label_review_reference')),
                    'Verified label needs a human review reference for the exact H9 interval')
        ids.add(key)
        previous_close = close
    return intake


def approved_source(path, intake):
    """Pin the authorized source headers or native file before the full reader runs."""
    path = Path(path)
    name = intake.get('source_basename')
    require(name is None or path.name == name, 'Path basename differs from external approval')
    path = path.resolve(strict=True)
    require(name is None or path.name == name, 'Resolved source differs from external approval')
    for key, name in SOURCE_FILES[intake['source_kind']].items():
        file = path if name is None else (path / name).resolve(strict=True)
        require(name is None or file.is_relative_to(path), 'Source metadata must be within the approved directory')
        require(digest(file) == intake['source_hashes'][key], 'Source does not match approval hash')
    return path


def source_preflight(path, intake):
    from research_b_preflight import inspect_source

    checks = inspect_source(path, expected_sha256=intake['source_hashes'].get('file_sha256'))
    require(checks['kind'] == intake['source_kind'] and checks['source_hashes'] == intake['source_hashes'],
            'Reader found a different source identity')
    return checks


def admit_preflight(checks, intake):
    counts = checks['packet_counts']
    require(counts['packets'] == counts['paired'], 'Existing Replay cannot score missing RGB-D pairs')
    flags = checks['continuity_and_pairing_flags']
    rejects = {'invalid_frameset_clock', 'frameset_domain_changed', 'non_increasing_video_timestamp'}
    require(not rejects.intersection(flags), 'Existing Replay cannot score rejected VIDEO timestamps')
    if checks['input_checks'] != 'PASS':
        review = intake.get('continuity_review', {})
        require(review.get('status') == 'VERIFIED' and present(review.get('reference'))
                and review.get('flags') == flags, 'Continuity flags require source-specific human review')


def score(windows, *, allow_final):
    verified = [row for row in windows if row['label_status'] == 'VERIFIED']
    confusion = {label: dict.fromkeys((*LABELS, 'NO_PREDICTION'), 0) for label in LABELS}
    for row in verified:
        confusion[row['label']][row['prediction'] or 'NO_PREDICTION'] += 1
    support = {label: sum(row.values()) for label, row in confusion.items()}
    correct = sum(confusion[label][label] for label in LABELS)
    absent = sum(row['NO_PREDICTION'] for row in confusion.values())
    totals = dict(windows=len(windows), verified=len(verified), correct=correct,
                  wrong=len(verified) - correct - absent, no_prediction=absent)
    complete_review = bool(windows) and len(verified) == len(windows)
    if allow_final and complete_review:
        recall = {label: confusion[label][label] / support[label] if support[label] else None for label in LABELS}
        f1 = [2 * confusion[label][label] / (support[label] + sum(row[label] for row in confusion.values()))
              for label in LABELS if support[label]]
        metrics = dict(status='COMPUTED' if all(support.values()) else 'INCOMPLETE', accuracy=correct / len(verified),
                       macro_f1=statistics.mean(f1) if all(support.values()) else None, recall=recall)
    else:
        metrics = dict(status='NOT_TESTED' if not verified else 'INCOMPLETE', accuracy=None,
                       macro_f1=None, recall=dict.fromkeys(LABELS))
    return dict(**totals, support=support, confusion=confusion, **metrics)


def condition(method):
    from adaptive_v2_replay import adaptive_v2_hook
    from face_recovery_replay import face_recovery_hook
    from research_b_fair_replay import matched_idle_fixed2_hook
    from research_b_robustness_replay import uniform85_hook

    if method == 'E0':
        return face_recovery_hook('baseline'), 'E0'
    if method == 'Fixed_2_matched':
        return matched_idle_fixed2_hook(), 'Adaptive'
    if method == 'Uniform_85':
        return uniform85_hook(), 'Adaptive'
    require(method == 'V2_85', 'Unknown policy')
    return adaptive_v2_hook(target_valid=85, continuous_face=True), 'Adaptive'


def loss_episodes(frames, field):
    episodes, current = [], []
    for frame in frames:
        if frame.get('natural_observation', {}).get(field) is False:
            current.append(frame)
        elif current:
            episodes.append(episode(current, frame if frame.get('natural_observation', {}).get(field) is True else None))
            current = []
    if current:
        episodes.append(episode(current, None))
    return episodes


def episode(frames, recovered):
    first, last = frames[0], frames[-1]
    start, end = (row['source']['frameset_timestamp_ms'] for row in (first, last))
    recovery_ms = recovered['source']['frameset_timestamp_ms'] if recovered else None
    return dict(first_input=first['input_index'], last_input=last['input_index'], inputs=len(frames),
                start_ms=start, last_failed_ms=end, span_ms=end - start, recovery_ms=recovery_ms,
                onset_to_recovery_ms=recovery_ms - start if recovery_ms is not None else None)


def bind_windows(doc, windows, arms):
    require(len(arms) == len(windows) == len(doc['segments']), 'Source did not deliver all declared Start and close events')
    rows = []
    for window, arm, segment in zip(windows, arms, doc['segments']):
        closure = doc['frames'][segment['end_boundary_frame_id'] - 1]
        require(arm['source_ms'] == window['start_ms'] == segment['first_device_ms']
                and segment['window_end_device_ms'] == window['end_ms']
                and closure['source']['frameset_timestamp_ms'] == window['closing_input_ms'],
                'Measurement bounds differ from declared source-clock events')
        prediction = segment['prediction_label'] if segment['prediction_success'] else None
        require(prediction is None or prediction in LABELS, 'Unexpected prediction label')
        observed = doc['frames'][arm['input_index'] - 1: segment['end_boundary_frame_id'] - 1]
        require(len(observed) == segment['input_frames'], 'H9 input denominator mismatch')
        rows.append(dict(id=window['id'], label_status=window['label_status'],
                         label=window.get('label') if window['label_status'] == 'VERIFIED' else None,
                         start_ms=window['start_ms'], end_ms=window['end_ms'], input_frames=segment['input_frames'],
                         valid_frames=segment['valid_frames'], coverage=segment['coverage'], h9_pass=segment['eligible'],
                         prediction=prediction, prediction_outcome='GENERATED' if prediction else 'NO_PREDICTION',
                         replay_status=segment['status'], reasons=segment['eligibility_reasons'],
                         full_calls=sum(row['full_inference'] for row in observed)))
    return rows


def thread_count():
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes

            class ThreadEntry(ctypes.Structure):
                _fields_ = [(name, wintypes.DWORD) for name in
                            ('size', 'usage', 'thread', 'owner', 'base', 'delta', 'flags')]

            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            snapshot = kernel.CreateToolhelp32Snapshot
            snapshot.argtypes, snapshot.restype = [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE
            handle = snapshot(4, 0)
            if handle == ctypes.c_void_p(-1).value:
                return None
            entry = ThreadEntry(ctypes.sizeof(ThreadEntry))
            try:
                first, next_entry = kernel.Thread32First, kernel.Thread32Next
                for query in (first, next_entry):
                    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
                if not first(handle, ctypes.byref(entry)):
                    return None
                count = int(entry.owner == os.getpid())
                while next_entry(handle, ctypes.byref(entry)):
                    count += entry.owner == os.getpid()
                return count
            finally:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(handle)
        with open('/proc/self/status', encoding='utf-8') as stream:
            return next(int(line.split()[1]) for line in stream if line.startswith('Threads:'))
    except (OSError, StopIteration):
        return None


def worker(plan, target, method):
    from e0_panel import OperatorControl
    import e0_replay
    from f1_sample_aggregator import H9_RGBD_FEATURE_NAMES
    from research_b_fair_replay import InputPhaseMeter, measurement_phase

    intake, protocol = plan['intake'], plan['protocol']
    validate_intake(intake, protocol['binding'], plan['roster'])
    source = approved_source(plan['source'], intake)
    starts = {window['start_ms'] for window in intake['windows']}
    hook, variant = condition(method)
    meter, arms, instances = InputPhaseMeter(), [], []
    control, thread_sample = None, None
    with hook:
        base = e0_replay.ReplayInput

        class ValidationInput(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.previous = None
                instances.append(self)

            def read(self):
                meter.mark_read(time.process_time_ns(), self.previous)
                ready, frame = super().read()
                self.previous = self.current if ready else None
                return ready, frame

            def validate(self, session, row):
                nonlocal control, thread_sample
                if not super().validate(session, row):
                    meter.mark_frame(self.current, 'rejected')
                    return False
                stamp = self.frames.get_timestamp()
                require(str(self.frames.get_frame_timestamp_domain()) == intake['clock_domain'], 'Declared clock domain differs from input')
                if control is None:
                    control = OperatorControl(session)
                    thread_sample = thread_count()
                if stamp in starts:
                    require(control.start(), 'Recorded Start overlaps an active H9 window')
                    arms.append(dict(source_ms=stamp, input_index=self.current['input_index']))
                meter.mark_frame(self.current, measurement_phase(session, stamp))
                return True

            def observe_features(self, result):
                super().observe_features(result)
                pose = self.current['e0_row']['pose_detected']
                self.current['natural_observation'] = dict(pose_detected=bool(pose),
                    depth_all=all(result.features.get(name) is not None for name in H9_RGBD_FEATURE_NAMES))

        with patch.object(e0_replay, 'ReplayInput', ValidationInput):
            doc = e0_replay.run_replay(source, protocol['binding'], plan['artifact'], target, pacing=plan['pacing'],
                                       expected_sha256=intake['source_hashes'].get('file_sha256'),
                                       pc_id=plan['pc_id'], method=variant)

    replay, = instances
    phases = meter.summary(replay._cpu_start, replay._cpu_end)
    save(target / 'phase_cpu.json', dict(**phases, operator_start_events=arms))
    require(doc['status'] == 'COMPLETED' and doc['eof_confirmed'] and doc['source_unchanged']
            and not doc['dropped_or_rejected_frames'] and not doc['errors']
            and doc['input_frames'] == doc['handled_frames'] == plan['preflight']['packet_counts']['packets'],
            'Incomplete or changed input. Inspect retained logs.')
    sequence = doc['array_and_clock_sequence_sha256']
    require(intake.get('array_and_clock_sequence_sha256') in (None, sequence), 'Approved sequence mismatch')
    rows = bind_windows(doc, intake['windows'], arms)
    timings = read(target / 'replay_invocation.json')
    latency = doc['all_input_latency_ms']
    natural = {field: loss_episodes(doc['frames'], field) for field in ('pose_detected', 'depth_all')}
    save(target / 'final_metrics.json', dict(method=method, sequence=sequence, windows=rows, total_inputs=doc['input_frames'],
         h9_pass=sum(row['h9_pass'] for row in rows), predictions=sum(row['prediction'] is not None for row in rows),
         valid_frames=sum(row['valid_frames'] for row in rows), h9_inputs=sum(row['input_frames'] for row in rows),
         face_failures=sum(frame['face_experiment']['detected'] is False for frame in doc['frames']),
         calls=doc['actual_calls'], full_active=sum(row['full_calls'] for row in rows),
         full_total=sum(frame['full_inference'] for frame in doc['frames']),
         process_cpu_s=doc['process_cpu_seconds'], wall_s=doc['stream_wall_seconds'], invocation=timings,
         p50_ms=latency['read_to_complete_ms']['p50'], p95_ms=latency['read_to_complete_ms']['p95'],
         service_p95_ms=latency['service_excluding_pacing_ms']['p95'], rss=doc['rss'], process_threads_at_first_input=thread_sample,
         observation_loss=dict(status='OBSERVED' if method == 'E0' else 'SELECTED_FRAMES_ONLY', episodes=natural)))


def repeat_stats(values):
    return dict(n=len(values), median=statistics.median(values), minimum=min(values), maximum=max(values),
                sample_sd=statistics.stdev(values) if len(values) > 1 else None)


def build_result(plan, runs):
    sequences = {run['sequence'] for items in runs.values() for run in items}
    require(len(sequences) == 1, 'Policies did not receive the same decoded array-and-clock sequence')
    methods = {}
    for method, items in runs.items():
        first = items[0]
        stable = all(item['windows'] == first['windows'] for item in items)
        methods[method] = dict(repeat_windows_agree=stable, windows=first['windows'] if stable else [],
                               runs=items, stats={key: repeat_stats([item[key] for item in items])
                                                  for key in ('process_cpu_s', 'wall_s', 'p50_ms', 'p95_ms', 'service_p95_ms')},
                               score=score(first['windows'] if stable else [], allow_final=plan['intake']['cohort'] != 'ENGINEERING'))
    paired = {other: [{key: v2[key] - base[key] for key in ('full_active', 'full_total', 'process_cpu_s', 'wall_s')}
                     for v2, base in zip(runs['V2_85'], runs[other])] for other in METHODS[:-1]}
    return dict(format='research-b-final-result/1', cohort=plan['intake']['cohort'], sequence=sequences.pop(),
                participant=plan['intake']['participant'], session_id=plan['intake']['session_id'],
                clip_id=plan['intake']['clip_id'], protocol_sha256=plan['protocol_sha256'],
                roster_sha256=plan['roster_sha256'], pc_id=plan['pc_id'], pacing=plan['pacing'],
                repeats=plan['repeats'], fault_mode='NO_INJECTION', methods=methods, v2_minus_other_paired=paired)


def observation_stratum(result):
    e0 = result['methods']['E0']
    signatures = [run['observation_loss']['episodes'] for run in e0['runs']]
    require(all(episodes == signatures[0] for episodes in signatures), 'E0 natural-loss inventory differs across repeats')
    episodes = [episode for records in signatures[0].values() for episode in records]
    if not episodes:
        return 'NO_E0_OBSERVATION_LOSS'
    inside = any(episode['start_ms'] < window['end_ms'] and episode['last_failed_ms'] >= window['start_ms']
                 for episode in episodes for window in e0['windows'])
    return 'E0_OBSERVATION_LOSS_IN_H9' if inside else 'E0_OBSERVATION_LOSS_OUTSIDE_H9'


def aggregate(results):
    first = results[0]
    cohort = first['cohort']
    require(cohort in ('REPEAT', 'INDEPENDENT'), 'Engineering runs cannot enter participant metrics')
    keys = ('format', 'cohort', 'protocol_sha256', 'roster_sha256', 'pc_id', 'pacing', 'repeats', 'fault_mode')
    require(all(all(run[key] == first[key] for key in keys) for run in results)
            and first['format'] == 'research-b-final-result/1' and first['fault_mode'] == 'NO_INJECTION',
            'Aggregate one cohort, frozen protocol/roster, hardware, repeat condition and original fault mode')
    require(len({run['sequence'] for run in results}) == len(results), 'Duplicate decoded sequence')
    strata = {observation_stratum(result) for result in results}
    require(len(strata) == 1, 'Aggregate observed natural-loss strata separately')
    identities = {(run['participant']['namespace'], run['participant']['canonical_id']) for run in results}
    require(all(run['participant']['status'] == 'VERIFIED' for run in results), 'Unverified identity in participant result')
    clips = {(run['participant']['canonical_id'], run['session_id'], run['clip_id']) for run in results}
    require(len(clips) == len(results), 'Duplicate participant/session/clip')
    methods = {}
    for method in METHODS:
        entries = [run['methods'][method] for run in results]
        require(all(entry['repeat_windows_agree'] for entry in entries), 'Repeat disagreement. Inspect runs before aggregating.')
        windows = [window for entry in entries for window in entry['windows']]
        attempts = len(windows)
        h9 = sum(window['h9_pass'] for window in windows)
        generated = sum(window['prediction'] is not None for window in windows)
        valid = sum(window['valid_frames'] for window in windows)
        inputs = sum(window['input_frames'] for window in windows)
        methods[method] = dict(**score(windows, allow_final=True), h9_pass=h9, h9_pass_rate=h9 / attempts,
                               predictions=generated, prediction_rate=generated / attempts,
                               valid_frames=valid, h9_inputs=inputs, coverage=valid / inputs)
    return dict(cohort=cohort, participants=len(identities), sessions=len({clip[:2] for clip in clips}),
                clips=len(clips), observation_stratum=strata.pop(), methods=methods)


def verify_protocol(protocol):
    require(protocol['format'] == 'research-b-final-protocol/1' and tuple(protocol['methods']) == METHODS,
            'Unexpected locked protocol')
    require(protocol.get('binding') == FROZEN_BINDING, 'Frozen SVM and FS3 binding mismatch')
    sources = protocol['implementation_sha256']
    require(sources.keys() == LOCKED_FILES and all(digest(ROOT / name) == value for name, value in sources.items()),
            'Frozen policy or runtime source fingerprint mismatch')


def environment(pc_id, hardware):
    from e0_model import environment_record

    record = environment_record(pc_id)
    require(present(hardware.get('cpu_model')) and type(hardware.get('physical_cores')) is int
            and 0 < hardware['physical_cores'] <= record['logical_cpus'], 'Record actual CPU model and physical core count')
    return dict(**record, cpu_brand=hardware['cpu_model'], physical_cores=hardware['physical_cores'],
                hardware_note=hardware.get('note'), configured_threads={key: os.environ.get(key) for key in
                    ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')},
                real_sense_runtime='pyrealsense2 bundled SDK runtime; package version recorded; camera firmware outside offline Replay',
                thread_measurement='OS process thread count sampled at first validated frame; SDK per-task concurrency unavailable')


def order_for(repeats):
    order = list(METHODS)
    random.Random(20261119).shuffle(order)
    return [order[repeat % len(order):] + order[:repeat % len(order)] for repeat in range(repeats)]


def launch(plan_path, output, plan):
    runs = {method: [] for method in METHODS}
    for block, methods in enumerate([['E0']] * plan['warmups'] + plan['order']):
        warmup = block < plan['warmups']
        parent = output / ('warmup' if warmup else f'repeat_{block - plan["warmups"] + 1:02}')
        parent.mkdir()
        for method in methods:
            target = parent / method
            command = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), 'worker',
                       str(plan_path), str(target), method]
            start = time.perf_counter()
            with (parent / f'{method}.log').open('x', encoding='utf-8') as stream:
                result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
            save(parent / f'{method}_launch.json', dict(exit_code=result.returncode, elapsed_s=time.perf_counter() - start))
            print(parent.name, method, result.returncode, flush=True)
            require(result.returncode == 0, f'{parent.name}/{method} failed. Inspect retained run log.')
            if not warmup:
                runs[method].append(read(target / 'final_metrics.json'))
    save(output / 'result.json', build_result(plan, runs))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'run'):
        command = commands.add_parser(name)
        for flag in ('protocol', 'intake', 'source'):
            command.add_argument(f'--{flag}', required=True)
        command.add_argument('--roster')
    run = commands.choices['run']
    for flag in ('artifact', 'hardware', 'pc-id', 'output'):
        run.add_argument(f'--{flag}', required=True)
    run.add_argument('--repeats', type=int, default=3)
    run.add_argument('--pacing', choices=('throughput', 'realtime15'), default='throughput')
    run.add_argument('--engineering-smoke', action='store_true')
    group = commands.add_parser('aggregate')
    group.add_argument('--output', required=True)
    group.add_argument('results', nargs='+')
    job = commands.add_parser('worker')
    job.add_argument('plan')
    job.add_argument('output')
    job.add_argument('method', choices=METHODS)
    args = parser.parse_args(argv)
    if args.command == 'worker':
        plan = read(args.plan)
        verify_protocol(plan['protocol'])
        worker(plan, Path(args.output), args.method)
        return
    if args.command == 'aggregate':
        save(args.output, aggregate([read(path) for path in args.results]))
        return
    protocol, intake = read(args.protocol), read(args.intake)
    roster = read(args.roster) if args.roster else None
    verify_protocol(protocol)
    validate_intake(intake, protocol['binding'], roster, for_replay=args.command == 'run')
    source = approved_source(args.source, intake)
    checks = source_preflight(source, intake)
    if args.command == 'inspect':
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return
    admit_preflight(checks, intake)
    smoke = args.engineering_smoke
    require((smoke and intake['cohort'] == 'ENGINEERING' and args.repeats == 1)
            or (not smoke and args.repeats >= 3), 'Require three repeats or an explicitly labelled one-repeat engineering smoke')
    artifact = Path(args.artifact).resolve(strict=True)
    require(digest(artifact) == protocol['binding']['artifact_sha256'], 'Trusted SVM artifact hash mismatch')
    output = Path(args.output).resolve()
    require(output != source and not output.is_relative_to(source), 'Output must be outside raw source')
    machine = environment(args.pc_id, read(args.hardware))
    output.mkdir(parents=True, exist_ok=False)
    plan = dict(protocol=protocol, protocol_sha256=digest(args.protocol), intake=intake, roster=roster,
                roster_sha256=digest(args.roster) if args.roster else None, source=str(source), artifact=str(artifact),
                preflight=checks, pc_id=args.pc_id, pacing=args.pacing, repeats=args.repeats, warmups=0 if smoke else 1,
                order=order_for(args.repeats), mode='ENGINEERING_SMOKE' if smoke else 'STANDARD_REPEATED', environment=machine,
                runner_sha256=digest(__file__))
    plan_path = output / 'plan.json'
    save(plan_path, plan)
    launch(plan_path, output, plan)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
