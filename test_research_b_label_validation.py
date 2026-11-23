"""Approval and scoring contract tests with synthetic metadata only."""

from copy import deepcopy

import pytest

from research_b_final_validation import FROZEN_BINDING, LABELS, save, validate_intake
from research_b_label_validation import archived_windows, approval_schedule, make_intake, person_audit, score_schedule, source_bounds


@pytest.fixture
def review():
    times = [i * 5000 for i in range(25)]
    candidates, approvals = [], []
    for i, label in enumerate(LABELS):
        start = i * 4 + 1
        bounds = source_bounds(times, start, start + 2)
        candidates.append(dict(window_id=label, posture_code=label, start_frame=str(start), end_frame=str(start + 2),
                               start_time_ms=str(bounds.start_ms), end_time_ms=str(bounds.closing_ms)))
        approvals.append(dict(window_id=label, candidate_posture=label, confirmed_posture='', posture_status='NOT_VERIFIED',
                              stability_status='NOT_VERIFIED', boundary_status='NOT_VERIFIED', approval_status='NOT_VERIFIED',
                              approved_start_frame='', approved_closing_frame='', posture_review_reference='',
                              interval_review_reference='', reason=''))
    return times, candidates, approvals


def approve(candidate, row):
    row.update(confirmed_posture=candidate['posture_code'], posture_status='VERIFIED', stability_status='VERIFIED',
               boundary_status='VERIFIED', approval_status='VERIFIED', approved_start_frame=candidate['start_frame'],
               approved_closing_frame=candidate['end_frame'], posture_review_reference='User review',
               interval_review_reference='Precise window review')


def stored(schedule):
    return {row['bounds']: dict(prediction=prediction, h9_pass=prediction is not None, valid_frames=0, input_frames=2,
                               coverage=0) for row, prediction in zip(schedule, ('P0', 'P0', None, 'P3', 'P4', 'P5'))}


def test_confirmed_direction_without_stability_never_becomes_ground_truth(review):
    times, candidates, approvals = review
    approvals[3].update(confirmed_posture='P3', posture_status='VERIFIED', posture_review_reference='User direction')
    schedule = approval_schedule(candidates, approvals, times)
    assert schedule[3]['posture_status'] == 'VERIFIED'
    assert schedule[3]['posture'] is None
    result = score_schedule(schedule, stored(schedule))
    assert result['status'] == 'NOT_TESTED'
    assert result['approved_windows'] == result['scored_windows'] == 0
    assert result['full_six'] is result['partial_diagnostic'] is None


def test_overall_approval_requires_all_states_and_exact_closing_input(review):
    times, candidates, approvals = review
    approve(candidates[0], approvals[0])
    approvals[0]['stability_status'] = 'NOT_VERIFIED'
    with pytest.raises(ValueError, match='all three'):
        approval_schedule(candidates, approvals, times)
    approve(candidates[0], approvals[0])
    approvals[0]['approved_closing_frame'] = '4'
    with pytest.raises(ValueError, match='first input'):
        approval_schedule(candidates, approvals, times)
    approve(candidates[0], approvals[0])
    approvals[0]['interval_review_reference'] = ''
    with pytest.raises(ValueError, match='human reference'):
        approval_schedule(candidates, approvals, times)


def test_changed_approved_window_invalidates_cached_schedule(review):
    times, candidates, approvals = review
    approve(candidates[1], approvals[1])
    before = approval_schedule(candidates, approvals, times)
    cache = stored(before)
    approve(candidates[0], approvals[0])
    approvals[0].update(approved_start_frame='2', approved_closing_frame='4', reason='Boundary moved after blind review')
    revised = approval_schedule(candidates, approvals, times)
    result = score_schedule(revised, cache)
    assert result['exact_window_matches'] == 5
    assert result['status'] == 'REPLAY_REQUIRED'
    assert result['partial_diagnostic'] is None


def test_partial_and_full_scoring_preserve_wrong_and_no_prediction(review):
    times, candidates, approvals = review
    for i in (0, 1, 2):
        approve(candidates[i], approvals[i])
    schedule = approval_schedule(candidates, approvals, times)
    partial = score_schedule(schedule, stored(schedule))
    assert partial['full_six'] is None
    assert partial['partial_diagnostic']['wrong'] == partial['partial_diagnostic']['no_prediction'] == 1
    assert partial['partial_diagnostic']['macro_f1'] is None
    for row, candidate in zip(approvals, candidates):
        approve(candidate, row)
    schedule = approval_schedule(candidates, approvals, times)
    full = score_schedule(schedule, stored(schedule))['full_six']
    assert full['accuracy'] == pytest.approx(4 / 6)
    assert full['h9_pass_rate'] == pytest.approx(5 / 6)
    assert full['non_generation_rate'] == pytest.approx(1 / 6)
    assert full['confusion']['P2']['NO_PREDICTION'] == full['confusion']['P1']['P0'] == 1
    approvals[-1]['confirmed_posture'] = 'P4'
    schedule = approval_schedule(candidates, approvals, times)
    repeated_class = score_schedule(schedule, stored(schedule))
    assert repeated_class['status'] == 'DEVELOPMENT_SIX_INCOMPLETE_CLASS_SUPPORT'
    assert repeated_class['full_six']['accuracy'] == pytest.approx(3 / 6)
    assert repeated_class['full_six']['macro_f1'] is None


def test_same_person_aliases_block_new_participant_interpretation():
    rows = [dict(source_code=key, namespace='', canonical_person_id='', identity_reference='', identity_status='UNKNOWN')
            for key in ('P01', 'P02', 'P03', 'P04', 'Clip2')]
    assert person_audit(rows)['exact_fit_clip2_overlap'] == 'UNKNOWN'
    for row in (rows[1], rows[-1]):
        row.update(identity_status='VERIFIED', canonical_person_id='person-01', identity_reference='private log', namespace='study')
    result = person_audit(rows)
    assert result['exact_fit_clip2_overlap'] == 'SAME_PERSON'
    assert result['distinct_confirmed_people'] == 1
    assert result['total_unique_people'] == 'UNKNOWN'
    assert result['independent_clip2'] == 'INELIGIBLE_DEVELOPMENT_SOURCE'


def test_generated_intake_reuses_step5a_guard_and_keeps_pending_rows_unverified(review):
    times, candidates, approvals = review
    approve(candidates[1], approvals[1])
    schedule = approval_schedule(candidates, approvals, times)
    base = dict(format='research-b-final-intake/1', origin='LOCAL', cohort='ENGINEERING',
                approval=dict(status='APPROVED', scope='ENGINEERING', reference='Local'), source_kind='NPZ_CLIP',
                source_hashes={key: 'a' * 64 for key in ('recording.json', 'frames.jsonl', 'end.json')},
                session_id='test-session', clip_id='test-clip', clock_domain='timestamp_domain.system_time',
                participant=dict(status='UNKNOWN', canonical_id=None))
    before = deepcopy(base)
    intake = make_intake(base, schedule)
    assert base == before
    assert [row['label'] for row in validate_intake(intake, {})['windows']] == [None, 'P1', None, None, None, None]


def test_incomplete_archived_window_is_separate_from_closed_non_prediction(tmp_path):
    times = [0, 5000]
    save(tmp_path / 'summary.json', {'model_binding': FROZEN_BINDING})
    save(tmp_path / 'replay.json', dict(status='COMPLETED', source_unchanged=True, eof_confirmed=True, errors=[],
         dropped_or_rejected_frames=0, array_and_clock_sequence_sha256='test-sequence', input_frames=2, handled_frames=2,
         replay_gate=dict(method='E0', interval=1), actual_calls=dict(face=2),
         frames=[dict(input_index=i, source=dict(frameset_timestamp_ms=stamp)) for i, stamp in enumerate(times, 1)],
         segments=[dict(status='INCOMPLETE', first_device_ms=0)]))
    windows, summary = archived_windows(tmp_path, 'E0', times, 'test-sequence')
    assert not windows
    assert (summary['windows'], summary['incomplete_windows'], summary['generated']) == (0, 1, 0)
