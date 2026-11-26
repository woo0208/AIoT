"""Finalize an exchange recording once acquisition, analysis and writer have stopped."""
from collections import Counter
import json
import math

from e0_fs3 import WINDOW_MS
from e0_storage import write_json
from exchange_capture import RECEIVE_GAP_MS
from raw_rgbd_recording import EXCHANGE_VALIDATION_FILE, EXCHANGE_VALIDATION_FORMAT, _sha
from raw_rgbd_replay import RawSessionReader


def rate(intervals, begin_ns, end_ns):
    if intervals > 0 and begin_ns is not None and end_ns is not None and end_ns > begin_ns:
        return intervals * 1e9 / (end_ns - begin_ns)
    return None


def frame_boundary(record):
    return dict(frame=record['frame_index'], receive_index=record['receive_index'],
                host_ns=record['host_receive_end_ns'],
                sensors={name: {key: sensor.get(key) for key in ('number', 'timestamp_ms', 'timestamp_domain')}
                         for name, sensor in record['sensors'].items()})


def _guided_intervals(events, saved, context, recording_event_index, recording_start_ns):
    identity = {key: context[key] for key in ('participant_id', 'session_label', 'repetition')}
    expected_order = [f'P{i}' for i in range(6)]
    instructions = {}
    measurements = {}
    completed, faults = [], []
    recording = [event for event in events if event['event'] == 'RECORDING_START']
    if (len(recording) != 1 or recording[0]['event_index'] != recording_event_index or
            recording[0]['details'].get('source') != 'operator_start' or
            recording[0]['details'].get('activated_host_ns') != recording_start_ns):
        faults.append('recording_start_mismatch')
    for event in events:
        kind, label, segment = event['event'], event['posture_code'], event['segment_id']
        if any(event[key] != value for key, value in identity.items()):
            faults.append('event_identity_mismatch')
        if kind == 'POSTURE_INSTRUCTION':
            if label in instructions or event['event_index'] <= (recording_event_index or 0):
                faults.append('unexpected_posture_instruction')
            instructions[label] = event
        if kind in ('MEASUREMENT_START', 'POSTURE_HOLD_START', 'POSTURE_HOLD_END', 'MEASUREMENT_END'):
            boundaries = measurements.setdefault(segment, {})
            if segment is None or kind in boundaries:
                faults.append('duplicate_or_unidentified_measurement_event')
            boundaries[kind] = event
    last_end = 0
    for boundaries in measurements.values():
        end = boundaries.get('POSTURE_HOLD_END')
        if end is None or end['details']['status'] not in ('PREDICTED', 'INELIGIBLE'):
            continue
        start = boundaries.get('POSTURE_HOLD_START')
        request, finish = boundaries.get('MEASUREMENT_START'), boundaries.get('MEASUREMENT_END')
        label = end['posture_code']
        instruction = instructions.get(label)
        if (not all((instruction, request, start, finish)) or
                any(event['posture_code'] != label for event in boundaries.values()) or
                finish['details']['status'] != end['details']['status'] or
                not ((recording_event_index or 0) < instruction['event_index'] < request['event_index']
                     < start['event_index'] < end['event_index'] < finish['event_index'])):
            faults.append('missing_or_unordered_measurement_events')
            continue
        first_ref = start['details'].get('start_frame_reference')
        last_ref = end['details'].get('end_frame_reference')
        if (not first_ref or not last_ref or saved.get(first_ref['receive_index']) != first_ref or
                saved.get(last_ref['receive_index']) != last_ref or first_ref['clip'] != last_ref['clip'] or
                not last_end < first_ref['receive_index'] < last_ref['receive_index']):
            faults.append('unresolved_or_overlapping_frame_references')
            continue
        first_ms = start['details']['first_device_ms']
        last_ms = end['details'].get('end_device_ms')
        same_sensor_clock = any(
            first['timestamp_ms'] == first_ms and last_ref['sensors'][name]['timestamp_ms'] == last_ms and
            first['timestamp_domain'] == last_ref['sensors'][name]['timestamp_domain']
            for name, first in first_ref['sensors'].items())
        if (type(first_ms) not in (int, float) or type(last_ms) not in (int, float) or
                not math.isfinite(first_ms) or not math.isfinite(last_ms) or
                first_ms + WINDOW_MS > last_ms or not same_sensor_clock):
            faults.append('invalid_measurement_duration_or_clock')
            continue
        last_end = last_ref['receive_index']
        completed.append(dict(**identity, posture_id=label,
                              posture_instruction_host_ns=instruction['host_perf_counter_ns'],
                              measurement_start_host_ns=start['host_perf_counter_ns'],
                              measurement_end_host_ns=end['host_perf_counter_ns'],
                              measurement_status=end['details']['status'], duration_ms=last_ms-first_ms,
                              start_frame_reference=first_ref, end_frame_reference=last_ref))
    if list(instructions) != expected_order or [hold['posture_id'] for hold in completed] != expected_order:
        faults.append('expected_exactly_one_completed_hold_per_posture')
    return dict(completed_intervals=completed, issues=sorted(set(faults)))


def verify_files(root, expected_count, *, guided_capture=None):
    """Re-open indexed files using the existing reader, including its terminal checks."""
    reader = RawSessionReader(root, allow_incomplete=True)
    events = [json.loads(line) for line in (root/'recording_metadata/events.jsonl').read_text(
        encoding='utf-8').splitlines()]
    metadata = json.loads((root/'exchange_metadata.json').read_text(encoding='utf-8'))
    if metadata['session_id'] != reader.identity['session_id']:
        raise ValueError('Exchange session identity mismatch')
    required = ['recording_metadata/events.jsonl','recording_metadata/annotations_template.json']
    for clip in reader.clips:
        required.extend(clip+'/'+name for name in ('end.json','recording.json','frames.jsonl'))
    if not reader.clips or not set(required).issubset(reader.hashes):
        raise ValueError('Session inventory lacks required clip or event metadata')
    template=json.loads((root/'stable_intervals_template.json').read_text(encoding='utf-8'))
    if template['session_id'] != reader.identity['session_id'] or template['status'] != 'PENDING_HUMAN_REVIEW':
        raise ValueError('Invalid stable interval template')
    files = dict(reader.identity['files'])
    issues = Counter()
    ranges = []
    range_key = None
    event_index = instruction_index = 0
    hold = None
    counts = Counter()
    previous = {}
    unique = {name: set() for name in ('color', 'depth')}
    paired_once = {name: set() for name in unique}
    first = last = None
    saved_guided = {}
    guided_refs = set()
    first_guided_frame = None
    if guided_capture is not None:
        if reader.identity['context'] != guided_capture.raw.events.context or metadata['participant'] != reader.identity['context']:
            raise ValueError('Guided participant, session or repetition mismatch')
        for event in events:
            for key in ('start_frame_reference', 'end_frame_reference'):
                reference = event['details'].get(key)
                if reference is not None:
                    guided_refs.add(reference['receive_index'])
    for packet in reader.packets():
        rec = packet.record
        counts['frames'] += 1
        if rec['receive_index'] != counts['frames']:
            raise ValueError('Acquisition and saved indices disagree')
        counts['color'] += packet.color_bgr is not None
        counts['depth'] += packet.depth_z16 is not None
        if packet.color_bgr is None or packet.depth_z16 is None:
            issues['missing_required_array'] += 1
        else:
            counts['pairs'] += 1
        files[rec['clip']+'/'+rec['file']] = rec['sha256']
        ns = rec['host_receive_end_ns']
        if last is not None and ns <= last:
            issues['host_time_regression'] += 1
        first = ns if first is None else first
        last = ns
        for name in ('color', 'depth'):
            sensor = rec['sensors'][name]
            relation = rec['sensor_relations'][name]['classification']
            if relation not in ('FIRST', 'ADVANCED'):
                issues[name+'.'+relation] += 1
            key = rec['clip'], name
            prior = previous.get(key)
            period = 1000 / packet.camera['streams'][name]['fps']
            if prior and sensor['status'] == prior['status'] == 'MEASURED':
                if all(sensor[k] == prior[k] for k in ('timestamp_domain', 'profile_uid', 'stream_type', 'stream_index')):
                    dt = sensor['timestamp_ms'] - prior['timestamp_ms']
                    if dt <= 0 or dt > 1.5 * period:
                        issues[name+'.unusual_interval'] += 1
                    if dt >= RECEIVE_GAP_MS:
                        issues[name+'.sensor_gap'] += 1
            previous[key] = sensor
        identities = {name: tuple(rec['sensors'][name][key] for key in
                      ('profile_uid', 'stream_type', 'stream_index', 'timestamp_domain', 'number', 'timestamp_ms'))
                      for name in unique if rec['sensors'][name]['status']=='MEASURED'}
        for name, identity in identities.items():
            unique[name].add(identity)
        skew = rec['pairing']['color_minus_depth_ms']
        if (len(identities)==2 and packet.color_bgr is not None and packet.depth_z16 is not None
                and skew is not None and abs(skew) <= 500 / packet.camera['streams']['color']['fps']
                and all(identity not in paired_once[name] for name,identity in identities.items())):
            for name, identity in identities.items():
                paired_once[name].add(identity)
        if rec['pairing']['color_minus_depth_ms'] is None:
            issues['skew_unknown'] += 1
        elif abs(rec['pairing']['color_minus_depth_ms']) > 500 / packet.camera['streams']['color']['fps']:
            issues['large_pair_skew'] += 1
        index = rec['preceding_event_index']
        if index < event_index:
            raise ValueError('Frame event index regressed')
        for new_event in events[event_index:index]:
            if new_event['event'] == 'POSTURE_INSTRUCTION':
                instruction_index = new_event['event_index']
            elif new_event['event'] == 'POSTURE_HOLD_START':
                hold = new_event
        event_index = index
        event = events[index-1]
        label = event['posture_code']
        if label is None:
            phase = 'UNLABELLED'
        elif (hold and hold['event_index'] > instruction_index and hold['segment_id'] == event['segment_id']
              and rec['active_segment_index'] is not None):
            phase = 'MEASUREMENT'
        else:
            phase = 'TRANSITION'
        key = rec['clip'], event['segment_id'], instruction_index, phase
        boundary = frame_boundary(rec)
        if guided_capture is not None and counts['frames'] == 1:
            first_guided_frame = dict(boundary, clip=rec['clip'], preceding_event_index=index)
        if boundary['receive_index'] in guided_refs and packet.color_bgr is not None and packet.depth_z16 is not None:
            saved_guided[boundary['receive_index']] = dict(boundary, clip=rec['clip'])
        if key != range_key:
            ranges.append(dict(clip=rec['clip'], segment_id=event['segment_id'],
                instruction=label, instruction_event_index=instruction_index or None,
                phase=phase, first_frame=rec['frame_index'], start=boundary))
            range_key = key
        ranges[-1].update(last_frame=rec['frame_index'], end=boundary)
    if not counts['frames']:
        raise ValueError('No stored RGB-D frames')
    if counts['frames'] != expected_count:
        issues['acquired_saved_count_mismatch'] = abs(expected_count-counts['frames'])
    counts.update(unique_color=len(unique['color']), unique_depth=len(unique['depth']),
                  one_use_pairs=len(paired_once['color']))
    stats = dict(counts=dict(counts), issues=dict(issues), saved_fps=rate(counts['frames']-1,first,last),
                 one_use_pair_fps=rate(counts['one_use_pairs']-1,first,last),
                 posture_ranges=ranges, observed_holds=[r for r in ranges if r['phase']=='MEASUREMENT'])
    if guided_capture is not None:
        stats['guided_protocol'] = _guided_intervals(events, saved_guided, reader.identity['context'],
                                                     guided_capture.recording_start_event, guided_capture.active_since_ns)
        stats['guided_protocol']['first_saved_pair'] = first_guided_frame
    return stats, files


def publish_result(capture, error):
    root = capture.root
    raw = capture.raw
    manifest = root/'recording_metadata/session_manifest.json'
    checks = dict(preflight=capture.preflight_status, file_integrity='NOT_TESTED',
                  continuity='NOT_TESTED', timing='NOT_TESTED', six_instructed_holds='NOT_TESTED',
                  receive_gap=('FAIL' if capture.receive_gap_failed else
                               'PASS' if capture.first_ns is not None else 'NOT_TESTED'),
                  physical_losslessness='NOT_TESTED', stable_ground_truth='NOT_TESTED',
                  external_reader='NOT_TESTED', hardware_qualification='NOT_TESTED')
    errors = list(capture.errors)
    if error and not isinstance(error, KeyboardInterrupt):
        errors.append(dict(stage='execution', type=type(error).__name__, detail=str(error)))
    if raw.error_type and not errors:
        errors.append(dict(stage='recording', type=raw.error_type))
    stats, files = {}, {}
    if manifest.is_file() and raw.clip_count:
        try:
            stats, files = verify_files(root, capture.acquired, **({'guided_capture': capture} if capture.guided else {}))
            issues = stats['issues']
            checks['file_integrity'] = ('FAIL' if issues.get('missing_required_array')
                                        or issues.get('acquired_saved_count_mismatch') else 'PASS')
            uncertain = any(k.endswith('NOT_MEASURED') for k in issues)
            discontinuity = any(k == 'missing_required_array' or k.endswith(
                ('NUMBER_GAP','NUMBER_REUSED','DUPLICATE_IDENTITY','COUNTER_REGRESSION','STREAM_BOUNDARY'))
                for k in issues)
            checks['continuity'] = ('FAIL' if discontinuity else 'WARNING' if uncertain else
                                    'NOT_TESTED' if stats['counts']['frames'] < 2 else 'PASS')
            timing_issue = any(any(token in k.lower() for token in ('time','interval','skew','not_measured')) for k in issues)
            checks['timing'] = ('FAIL' if any(k.endswith('.sensor_gap') for k in issues) else
                                'NOT_TESTED' if stats['counts']['frames'] < 2 else
                                'WARNING' if timing_issue else 'PASS')
            labels = {h['instruction'] for h in stats['observed_holds']}
            checks['six_instructed_holds'] = 'PASS' if labels == {f'P{i}' for i in range(6)} else 'WARNING'
        except Exception as exc:
            checks['file_integrity'] = 'FAIL'
            errors.append(dict(stage='verification', type=type(exc).__name__, detail=str(exc)))
    if capture.imu_status.get('saved',0) and not (root/'imu.jsonl').is_file():
        checks['imu_file'] = 'WARNING'
    if not manifest.is_file():
        errors.append(dict(stage='finalization', detail='Session manifest unavailable'))
    guided_interrupted = capture.guided and raw.termination_reason in ('user_aborted', 'panel_closed', 'duration_expired')
    if (not raw.total_frames and not guided_interrupted) or capture.enqueued != raw.total_frames:
        errors.append(dict(stage='storage', detail='No frames or unfinished writes'))
    interrupted = (guided_interrupted or raw.termination_reason in ('q','panel_closed','keyboard_interrupt')
                   or isinstance(error, KeyboardInterrupt))
    if capture.guided:
        protocol = stats.get('guided_protocol', dict(completed_intervals=[], issues=['no_verified_guided_recording']))
        first_saved = protocol.get('first_saved_pair')
        if raw.termination_reason == 'guided_completed':
            if any(checks[key] != 'PASS' for key in ('continuity', 'timing', 'file_integrity', 'receive_gap')):
                protocol['issues'].append('capture_integrity_not_passed')
            if (first_saved is None or capture.active_since_ns is None or capture.recording_start_event is None or
                    capture.first_recorded_callback_ns is None or
                    not capture.active_since_ns <= capture.first_recorded_callback_ns <= first_saved['host_ns'] or
                    first_saved['preceding_event_index'] < capture.recording_start_event):
                protocol['issues'].append('unverified_recording_start_boundary')
            checks['guided_protocol'] = 'FAIL' if protocol['issues'] else 'PASS'
        else:
            checks['guided_protocol'] = 'WARNING' if guided_interrupted else 'FAIL'
    fail = bool(errors or 'FAIL' in checks.values())
    incomplete = interrupted or 'WARNING' in checks.values() or capture.imu_status['status']=='WARNING' or checks['timing']=='NOT_TESTED'
    result = 'FAIL' if fail else 'WARNING' if incomplete else 'PASS'
    state = 'FAILED' if fail else 'INTERRUPTED' if interrupted else 'COMPLETED'
    report = dict(format='research-b-exchange-verification/1', status=result, session_status=state,
        session_id=raw.events.session_id, termination=raw.termination_reason, errors=errors, checks=checks,
        start_utc=capture.start_utc, end_utc=capture.end_utc, acquired=capture.acquired,
        queued=capture.enqueued, written=raw.total_frames, unwritten=capture.enqueued-raw.total_frames,
        queue_overflows=capture.overflows, receiver_timeouts=capture.timeouts, analysis_replaced=capture.analysis_replaced,
        requested_fps=capture.fps, active_start_host_ns=capture.active_since_ns, active_end_host_ns=capture.end_ns,
        receive_gap_limit_ms=RECEIVE_GAP_MS, max_receive_gap_ms=capture.max_receive_gap_ns / 1e6,
        terminal_receive_gap_ms=capture.tail_gap_ns / 1e6 if capture.tail_gap_ns is not None else None,
        max_consecutive_timeouts=capture.max_consecutive_timeouts,
        raw_queue_peak_sample=capture.queue_peak_sample,
        writer_stage_ms={name: dict(mean=ns/capture.writer_samples/1e6, max=capture.storage_max_ns[name]/1e6)
                         for name,ns in capture.storage_ns.items()},
        native_source=capture.native_source.diagnostics() if capture.native_source is not None else None,
        acquisition_fps=rate(capture.acquired-1,capture.first_ns,capture.last_ns),
        writer_fps=rate(raw.total_frames-1,capture.first_write_ns,capture.last_write_ns),
        mediapipe_completed=capture.analysis_completed,
        mediapipe_fps=rate(capture.analysis_completed,capture.first_ns,capture.end_ns)
                      if capture.analysis_completed else (0 if capture.first_ns is not None else None),
        imu=capture.imu_status, verification=stats)
    if capture.receive_gap_diagnostics is not None:
        report['receive_gap'] = dict(diagnostics=capture.receive_gap_diagnostics)
    if capture.guided:
        report['guided_capture'] = dict(recording_start_event_index=capture.recording_start_event,
            recording_start_host_ns=capture.active_since_ns,
            first_saved_pair_host_ns=first_saved['host_ns'] if first_saved else None,
            first_saved_pair_earliest_callback_host_ns=capture.first_recorded_callback_ns if first_saved else None,
            preview_pairs_not_recorded=capture.preview_pairs, **protocol)
    report_path = root/'exchange_verification.json'
    clip_proof = raw.last_clip/EXCHANGE_VALIDATION_FILE if raw.last_clip else None
    if manifest.is_file():
        pending_report = root/'exchange_verification.pending.json'
        final = manifest.with_suffix('.final')
        pending_proof = clip_proof.with_suffix('.pending') if clip_proof else None
        manifest_replaced = False
        try:
            original = json.loads(manifest.read_text(encoding='utf-8'))
            doc = dict(original, files=dict(original['files']))
            doc['status'] = state
            doc['exchange_verification'] = dict(status=result, path=report_path.name)
            doc['privacy'] = 'External sharing and publication authorization UNKNOWN'
            if clip_proof:
                write_json(pending_proof, clip_validation(raw, report))
                key = clip_proof.relative_to(root).as_posix()
                doc['files'][key] = files[key] = _sha(pending_proof)
            write_json(final, doc)
            write_json(pending_report, report)
            for name in ('exchange_metadata.json','stable_intervals_template.json','imu.jsonl'):
                if (root/name).is_file():
                    files[name] = _sha(root/name)
            files[report_path.name] = _sha(pending_report)
            files['recording_metadata/session_manifest.json'] = _sha(final)
            write_json(root/'exchange_files.json', dict(format='research-b-exchange-sha256/1',
                scope='verified exchange inputs and report; inventory excludes itself',
                status=result, sha256=files))
            pending_report.replace(report_path)
            final.replace(manifest)
            manifest_replaced = True
            if clip_proof:
                pending_proof.replace(clip_proof)
        except Exception as exc:
            report.update(status='FAIL', session_status='FAILED')
            if capture.guided:
                report['termination'] = 'write_failed'
            errors.append(dict(stage='publication', detail=str(exc)))
            failure = root/'exchange_publication_failure.json'
            # The proof is the last publication step. Strict readers reject its absence
            # even if rebuilding the failure metadata below is also blocked by I/O.
            try:
                if manifest_replaced:
                    failed = manifest.with_suffix('.failed')
                    write_json(failed, dict(original, status='FAILED',
                        exchange_verification=dict(status='FAIL', path=failure.name)))
                    failed.replace(manifest)
            finally:
                try:
                    write_json(failure, report)
                finally:
                    if clip_proof and not clip_proof.exists():
                        write_json(clip_proof, clip_validation(raw, report))
            raise
    else:
        if clip_proof:
            write_json(clip_proof, clip_validation(raw, report))
        write_json(report_path, report)
    print(f'Exchange verification {result}: {root / "exchange_verification.json"}')
    if fail and error is None:
        raise RuntimeError('Exchange capture failed: see exchange_verification.json')
    return report


def clip_validation(raw, report):
    clip = raw.last_clip
    hashes = {name: _sha(clip/name) for name in ('recording.json', 'frames.jsonl', 'end.json')
              if (clip/name).is_file()}
    end = json.loads((clip/'end.json').read_text(encoding='utf-8')) if 'end.json' in hashes else {}
    return dict(format=EXCHANGE_VALIDATION_FORMAT, session_id=raw.events.session_id, clip=clip.name,
                write_status=end.get('status', 'INCOMPLETE'), session_status=report['session_status'],
                status=report['status'], file_integrity=report['checks']['file_integrity'], clip_sha256=hashes)
