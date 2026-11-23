"""Research B Clip 2 approval audit and offline scoring of stored full-clip predictions."""

import argparse
from bisect import bisect_left
from collections import Counter
import csv
from dataclasses import dataclass
from itertools import combinations
import json
from pathlib import Path

from e0_fs3 import WINDOW_MS
from research_b_final_validation import FROZEN_BINDING, LABELS, METHODS, digest, read, require, save, score


@dataclass(frozen=True)
class Bounds:
    start_frame: int
    closing_frame: int
    start_ms: float
    end_ms: float
    closing_ms: float


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def read_clock(index):
    with index.open(encoding='utf-8') as stream:
        frames = [json.loads(line) for line in stream]
    require(all(row['frame_index'] == number for number, row in enumerate(frames, 1)), 'Unexpected raw frame index')
    times = [row['frameset_timestamp_ms'] for row in frames]
    require(all(right > left for left, right in zip(times, times[1:])), 'Unordered source timestamps')
    require(len({row['frameset_timestamp_domain'] for row in frames}) == 1, 'Unexpected source clock domain')
    return times


def source_bounds(times, first, close):
    require(1 <= first < close <= len(times), 'Window frame bounds outside original input')
    start = times[first - 1]
    end = start + WINDOW_MS
    require(close == bisect_left(times, end) + 1, 'Closing frame must be the first input at or after 10 seconds')
    return Bounds(first, close, start, end, times[close - 1])


def approval_schedule(candidates, approvals, times):
    require(len(candidates) == len(approvals) == len(LABELS), 'All six prespecified windows must be accounted for')
    by_id = {row['window_id']: row for row in approvals}
    require(len(by_id) == len(approvals) and set(by_id) == {row['window_id'] for row in candidates},
            'Approval rows must uniquely identify the original candidates')
    schedule = []
    for original in candidates:
        key = original['window_id']
        row = by_id[key]
        require(row['candidate_posture'] == original['posture_code'], 'Approval sheet candidate differs from correction record')
        begin, close = (int(original[field]) for field in ('start_frame', 'end_frame'))
        candidate = source_bounds(times, begin, close)
        require(candidate.start_ms == float(original['start_time_ms']) and candidate.closing_ms == float(original['end_time_ms']),
                'Candidate source timestamps disagree with the frame index')
        states = (row['posture_status'], row['stability_status'], row['boundary_status'])
        for state in (*states, row['approval_status']):
            require(state in ('VERIFIED', 'NOT_VERIFIED', 'REJECTED'), 'Unrecognized human review status')
        posture, label_reference = row['confirmed_posture'], row['posture_review_reference'].strip()
        require(states[0] != 'VERIFIED' or posture in LABELS and label_reference, 'Verified posture needs a class and human reference')
        verified = row['approval_status'] == 'VERIFIED'
        require(all(state == 'VERIFIED' for state in states) == verified, 'Overall approval must agree with all three human decisions')
        if verified:
            require(row['interval_review_reference'].strip(), 'Verified stability and bounds need a human reference')
            begin, close = (int(row[field]) for field in ('approved_start_frame', 'approved_closing_frame'))
            candidate = source_bounds(times, begin, close)
            if candidate.start_frame != int(original['start_frame']) or candidate.closing_frame != int(original['end_frame']):
                require(row['reason'].strip(), 'Edited bounds need a reason')
        schedule.append(dict(id=key, bounds=candidate, verified=verified,
                             posture=posture if verified else None, posture_status=states[0],
                             review_reference=f"{label_reference} | {row['interval_review_reference']}" if verified else None))
    require(all(left['bounds'].closing_frame < right['bounds'].start_frame for left, right in zip(schedule, schedule[1:])),
            'Windows must stay in source order without overlap or a shared closing input')
    return schedule


def person_audit(rows):
    ids = [row['source_code'] for row in rows]
    require(len(ids) == len(set(ids)) and set(ids) == {'P01', 'P02', 'P03', 'P04', 'Clip2'}, 'Expected five provenance codes')
    people = {}
    for row in rows:
        identity = (row['namespace'].strip(), row['canonical_person_id'].strip())
        status = row['identity_status']
        if status == 'VERIFIED':
            require(all(value and value != 'UNKNOWN' for value in identity) and row['identity_reference'].strip(),
                    'Verified identity needs two namespace/ID fields and a human reference')
            people[row['source_code']] = identity
        else:
            require(status == 'UNKNOWN' and not any(identity), 'Unknown identity cannot have a canonical ID')
    require(len({value[0] for value in people.values()}) <= 1, 'Use the same canonical ID namespace for every source')
    relations = {f'{a}/{b}': ('SAME_PERSON' if people[a] == people[b] else 'DIFFERENT_PEOPLE')
                 if a in people and b in people else 'UNKNOWN' for a, b in combinations(ids, 2)}
    overlap = relations.get('P02/Clip2', relations.get('Clip2/P02'))
    return dict(records=len(ids), verified_mappings=len(people), distinct_confirmed_people=len(set(people.values())),
                total_unique_people=len(set(people.values())) if len(people) == len(ids) else 'UNKNOWN',
                relations=relations, exact_fit_clip2_overlap=overlap,
                independent_clip2='INELIGIBLE_DEVELOPMENT_SOURCE', independent_participant_evaluation='NOT_TESTED')


def archived_windows(directory, method, times, sequence):
    path = directory / 'replay.json'
    doc, summary = read(path), read(directory / 'summary.json')
    require(all(summary['model_binding'].get(key) == value for key, value in FROZEN_BINDING.items()), 'Stored SVM binding mismatch')
    expected_gate = {
        'E0': {'method': 'E0', 'interval': 1},
        'Fixed_2_matched': {'policy': 'Fixed 2 + matched V2 idle', 'interval': 2, 'continuous_face': True},
        'Uniform_85': {'policy': 'Uniform-85', 'continuous_face': True},
        'V2_85': {'policy': 'Adaptive-V2', 'target_valid': 85, 'continuous_face': True},
    }[method]
    require(all(doc['replay_gate'].get(key) == value for key, value in expected_gate.items()), 'Stored policy configuration mismatch')
    require(doc['status'] == 'COMPLETED' and doc['source_unchanged'] and doc['eof_confirmed'] and not doc['errors']
            and not doc['dropped_or_rejected_frames'] and doc['array_and_clock_sequence_sha256'] == sequence
            and doc['input_frames'] == doc['handled_frames'] == len(doc['frames']) == len(times)
            and doc['actual_calls']['face'] == len(times), 'Incomplete or mismatched stored Replay')
    require(all(frame['input_index'] == index and frame['source']['frameset_timestamp_ms'] == stamp
                for index, (frame, stamp) in enumerate(zip(doc['frames'], times), 1)), 'Stored input clock mismatch')
    windows = {}
    incomplete = 0
    for segment in doc['segments']:
        first = bisect_left(times, segment['first_device_ms']) + 1
        close = segment.get('end_boundary_frame_id')
        if close is None:
            require(segment['status'] == 'INCOMPLETE' and not segment.get('prediction_success'),
                    'Stored output lacks a closing input')
            incomplete += 1
            continue
        bounds = source_bounds(times, first, close)
        require(segment['first_device_ms'] == bounds.start_ms and segment['window_end_device_ms'] == bounds.end_ms
                and segment['input_frames'] == close - first and bounds not in windows, 'Stored H9 window boundary mismatch')
        predicted = segment['prediction_label'] if segment['prediction_success'] else None
        require(predicted is None or predicted in LABELS and segment['eligible'], 'Invalid stored prediction')
        windows[bounds] = dict(prediction=predicted, h9_pass=segment['eligible'], input_frames=segment['input_frames'],
                               valid_frames=segment['valid_frames'], coverage=segment['coverage'])
    technical = dict(windows=len(windows), incomplete_windows=incomplete, h9_pass=sum(row['h9_pass'] for row in windows.values()),
                     generated=sum(row['prediction'] is not None for row in windows.values()))
    return windows, dict(replay=str(path), sha256=digest(path), **technical)


def score_schedule(schedule, stored):
    approved = [row for row in schedule if row['verified']]
    exact = list(stored) == [row['bounds'] for row in schedule]
    result = dict(schedule_exact=exact, exact_window_matches=sum(row['bounds'] in stored for row in schedule),
                  approved_windows=len(approved), scored_windows=0, partial_diagnostic=None, full_six=None)
    if not approved or not exact:
        return dict(**result, status='NOT_TESTED' if not approved else 'REPLAY_REQUIRED')
    rows = [dict(**stored[row['bounds']], label=row['posture'], label_status='VERIFIED') for row in approved]
    metrics = score(rows, allow_final=True)
    h9 = sum(row['h9_pass'] for row in rows)
    metrics.update(h9_pass=h9, h9_pass_rate=h9 / len(rows), non_generation_rate=metrics['no_prediction'] / len(rows))
    full = len(rows) == len(LABELS)
    status = 'DEVELOPMENT_PARTIAL' if not full else (
        'DEVELOPMENT_SIX_COMPUTED' if metrics['status'] == 'COMPUTED' else 'DEVELOPMENT_SIX_INCOMPLETE_CLASS_SUPPORT')
    result.update(status=status, scored_windows=len(rows))
    result['full_six' if full else 'partial_diagnostic'] = metrics
    return result


def make_intake(base, schedule):
    require(base['cohort'] == 'ENGINEERING' and base['origin'] == 'LOCAL', 'Only local development intake can be prepared here')
    return dict(base, windows=[dict(id=row['id'], start_ms=row['bounds'].start_ms, end_ms=row['bounds'].end_ms,
        closing_input_ms=row['bounds'].closing_ms, label=row['posture'], label_status='VERIFIED' if row['verified'] else 'UNVERIFIED',
        label_review_reference=row['review_reference'], start_event=dict(kind='PRESPECIFIED_ENGINEERING_START',
            reference='STEP 5B frozen candidate or human-approved development schedule')) for row in schedule])


def audit(archive, base, schedule, times, methods=METHODS):
    entries = {}
    for method in methods:
        directories = [Path(row[method]) for row in archive]
        reports = [archived_windows(directory, method, times, base['array_and_clock_sequence_sha256']) for directory in directories]
        first = reports[0][0]
        require(all(list(first.items()) == list(windows.items()) for windows, _ in reports), 'Stored repeat windows or outcomes disagree')
        entries[method] = dict(repeats=len(reports), source_runs=[report for _, report in reports], **score_schedule(schedule, first))
    return entries


def archive_runs(path):
    dirs = sorted(path.glob('repeat_*'))
    require(bool(dirs), 'No saved repeat directories')
    return [{method: repeat / method for method in METHODS} for repeat in dirs]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('study', 'index', 'intake', 'archive', 'output'):
        parser.add_argument(f'--{name}', type=Path, required=True)
    parser.add_argument('--approvals', type=Path)
    parser.add_argument('--participants', type=Path)
    parser.add_argument('--step3', type=Path)
    parser.add_argument('--replay-intake', type=Path)
    args = parser.parse_args(argv)
    base = read(args.intake)
    require(base['cohort'] == 'ENGINEERING' and base['origin'] == 'LOCAL', 'Expected the authorized local engineering intake')
    require(digest(args.index) == base['source_hashes']['frames.jsonl'], 'Raw index differs from the pinned Clip 2 input')
    times = read_clock(args.index)
    schedule = approval_schedule(csv_rows(args.study / 'manual_labels.corrected_candidate.csv'),
                                 csv_rows(args.approvals or args.study / 'human_approval.csv'), times)
    people = person_audit(csv_rows(args.participants or args.study / 'participant_crosswalk.csv'))
    archive_plan = read(args.archive / 'plan.json')
    require(archive_plan['intake']['source_hashes'] == base['source_hashes']
            and archive_plan['intake']['cohort'] == 'ENGINEERING' and archive_plan['protocol']['binding'] == FROZEN_BINDING,
            'Saved four-policy run does not belong to the locked development input')
    runs = archive_runs(args.archive)
    require(len(runs) == archive_plan['repeats'], 'Saved batch repeat count mismatch')
    main_results = audit(runs, base, schedule, times)
    old_results = None
    if args.step3:
        old = [{name: repeat / source for name, source in (('E0', 'E0'), ('V2_85', 'V2_85_face'))}
               for repeat in sorted((args.step3 / 'runs').glob('repeat_*'))]
        old_results = audit(old, base, schedule, times, methods=('E0', 'V2_85'))
    result = dict(scope='DEVELOPMENT_CLIP2', candidate_windows=len(schedule),
                  posture_verified=sum(row['posture_status'] == 'VERIFIED' for row in schedule),
                  fully_approved=sum(row['verified'] for row in schedule), participants=people,
                  approved_metrics_status='NOT_TESTED' if not any(row['verified'] for row in schedule) else 'SEE_METHODS',
                  four_policy_archive=main_results, step3_two_policy_archive_diagnostic=old_results)
    save(args.output, result)
    if args.replay_intake:
        save(args.replay_intake, make_intake(base, schedule))


if __name__ == '__main__':
    main()
