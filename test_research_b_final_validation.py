"""Structural checks for final intake and scoring. No participant media is used."""

from copy import deepcopy
from unittest.mock import patch

import pytest

import research_b_final_validation as final


BINDING = {'artifact_sha256': 'a' * 64}
ROSTER = dict(format='research-b-model-roster/1', status='VERIFIED_COMPLETE', namespace='study-b',
              artifact_sha256='a' * 64, reference='fit-ledger', development_reference='development-ledger',
              training_person_ids=['person-1'], development_person_ids=['person-2'])


def intake(cohort='INDEPENDENT'):
    return dict(format='research-b-final-intake/1', origin='EXTERNAL', cohort=cohort,
                approval=dict(status='APPROVED', scope=cohort, reference='use-ledger'),
                source_basename='fixture.db3',
                source_kind='REALSENSE_FILE', source_hashes={'file_sha256': 'b' * 64},
                session_id='session-01', clip_id='clip-01', clock_domain='timestamp_domain.hardware_clock',
                pairing_and_calibration_review=dict(status='VERIFIED', reference='camera-review'),
                participant=dict(status='VERIFIED', canonical_id='person-3', namespace='study-b', reference='alias-ledger'),
                windows=[dict(id='window-1', start_ms=10, end_ms=10010, closing_input_ms=10043,
                    start_event=dict(kind='RECORDED_OPERATOR_START', reference='operator-log'),
                    label='P0', label_status='VERIFIED', label_review_reference='review-ledger')])


def test_source_access_blocked_until_use_and_identity_are_allowed(tmp_path):
    manifest, protocol, roster = (tmp_path / name for name in ('intake.json', 'protocol.json', 'roster.json'))
    data = intake()
    data['approval']['status'] = 'PENDING'
    final.save(manifest, data)
    final.save(protocol, dict(format='research-b-final-protocol/1', methods=final.METHODS,
                              binding=BINDING, implementation_sha256={}))
    final.save(roster, ROSTER)
    with patch.object(final, 'approved_source') as source, patch.object(final, 'verify_protocol'):
        with pytest.raises(ValueError, match='use approval'):
            final.main(['inspect', '--intake', str(manifest), '--protocol', str(protocol), '--roster', str(roster),
                        '--source', 'never-open.db3'])
        source.assert_not_called()


@pytest.mark.parametrize('person,cohort', [('person-1', 'INDEPENDENT'), ('person-2', 'INDEPENDENT'),
                                         ('person-3', 'REPEAT')])
def test_roster_checks_actual_people_and_development(person, cohort):
    data = intake(cohort)
    data['participant']['canonical_id'] = person
    with pytest.raises(ValueError, match='overlap or incorrect'):
        final.validate_intake(data, BINDING, ROSTER)
    final.validate_intake(data, BINDING, ROSTER, for_replay=False)


def test_unknown_and_wrong_roster_cannot_be_independent():
    data = intake()
    assert final.validate_intake(data, BINDING, ROSTER) is data
    with pytest.raises(ValueError, match='this model'):
        final.validate_intake(data, BINDING, dict(ROSTER, artifact_sha256='c' * 64))
    data['participant'] = dict(status='UNKNOWN', canonical_id=None)
    with pytest.raises(ValueError, match='Verified identity'):
        final.validate_intake(data, BINDING, ROSTER)


def test_windows_require_real_operator_provenance_and_human_review():
    data = intake()
    data['windows'][0]['start_event']['kind'] = 'PRESPECIFIED_ENGINEERING_START'
    with pytest.raises(ValueError, match='recorded operator'):
        final.validate_intake(data, BINDING, ROSTER)
    data['windows'][0]['start_event']['kind'] = 'RECORDED_OPERATOR_START'
    data['windows'][0]['label_review_reference'] = None
    with pytest.raises(ValueError, match='human review reference'):
        final.validate_intake(data, BINDING, ROSTER)


def test_approved_inspect_can_precede_window_annotations():
    data = dict(intake(), windows=[], source_basename='recording 1.db3')
    assert final.validate_intake(data, BINDING, for_replay=False) is data
    with pytest.raises(ValueError, match='measurement window'):
        final.validate_intake(data, BINDING, ROSTER)


def test_preflight_paired_gap_can_be_reviewed_but_missing_pair_cannot():
    checks = dict(packet_counts=dict(packets=12, paired=12), input_checks='REVIEW_REQUIRED',
                  continuity_and_pairing_flags={'depth.GAP': 1})
    data = intake()
    with pytest.raises(ValueError, match='Continuity flags'):
        final.admit_preflight(checks, data)
    data['continuity_review'] = dict(status='VERIFIED', reference='review-ledger', flags={'depth.GAP': 1})
    final.admit_preflight(checks, data)
    with pytest.raises(ValueError, match='missing RGB-D'):
        final.admit_preflight(dict(checks, packet_counts=dict(packets=12, paired=11)), data)
    with pytest.raises(ValueError, match='VIDEO timestamps'):
        final.admit_preflight(dict(checks, continuity_and_pairing_flags={'frameset_domain_changed': 1}), data)


def test_approved_source_refuses_wrong_file_before_decoder(tmp_path):
    source = tmp_path / 'fixture.db3'
    source.write_bytes(b'structural fixture')
    data = intake()
    with pytest.raises(ValueError, match='basename'):
        final.approved_source(tmp_path / 'unauthorized.db3', data)
    with pytest.raises(ValueError, match='approval hash'):
        final.approved_source(source, data)
    data['source_hashes']['file_sha256'] = final.digest(source)
    assert final.approved_source(source, data) == source.resolve()


def complete_labels():
    predictions = ('P0', 'P0', None, 'P3', 'P4', 'P5')
    return [dict(label_status='VERIFIED', label=label, prediction=prediction, input_frames=150, start_ms=0, end_ms=10000,
                 valid_frames=75 if prediction else 74, h9_pass=prediction is not None)
            for label, prediction in zip(final.LABELS, predictions)]


def test_score_counts_h9_abstention_separately_and_keeps_six_classes():
    windows = complete_labels()
    result = final.score(windows, allow_final=True)
    assert (result['correct'], result['wrong'], result['no_prediction']) == (4, 1, 1)
    assert result['accuracy'] == pytest.approx(4 / 6)
    assert result['macro_f1'] == pytest.approx((2 / 3 + 3) / 6)
    assert result['recall']['P2'] == 0
    missing = final.score(windows[:-1], allow_final=True)
    assert (missing['status'], missing['macro_f1'], missing['recall']['P5']) == ('INCOMPLETE', None, None)
    windows[-1]['label_status'] = 'UNVERIFIED'
    mixed = final.score(windows, allow_final=True)
    assert (mixed['verified'], mixed['support']['P5'], mixed['accuracy']) == (5, 0, None)
    assert final.score(windows, allow_final=False)['accuracy'] is None


def test_loss_episode_never_reports_recovery_on_skipped_frame():
    def row(index, value):
        return dict(input_index=index, source=dict(frameset_timestamp_ms=index * 10),
                    natural_observation={} if value is None else dict(depth_all=value))

    episodes = final.loss_episodes([row(1, False), row(2, None), row(3, False), row(4, False), row(5, True)],
                                   'depth_all')
    assert (episodes[0]['inputs'], episodes[0]['recovery_ms']) == (1, None)
    assert (episodes[1]['inputs'], episodes[1]['onset_to_recovery_ms']) == (2, 20)


def test_window_binds_actual_close_and_preserves_failed_denominator():
    window = intake()['windows'][0]
    frames = [dict(source=dict(frameset_timestamp_ms=stamp), full_inference=full)
              for stamp, full in [(10, True), (104, False), (10043, True)]]
    segment = dict(first_device_ms=10, end_boundary_frame_id=3, window_end_device_ms=10010,
                   prediction_label=None, prediction_success=False, input_frames=2, valid_frames=1,
                   coverage=.5, eligible=False, status='INELIGIBLE', eligibility_reasons=['insufficient_valid'])
    doc = dict(frames=frames, segments=[segment])
    arms = [dict(source_ms=10, input_index=1)]
    result, = final.bind_windows(doc, [window], arms)
    assert (result['input_frames'], result['full_calls'], result['prediction_outcome']) == (2, 1, 'NO_PREDICTION')
    with pytest.raises(ValueError, match='bounds differ'):
        final.bind_windows(doc, [dict(window, closing_input_ms=10044)], arms)


def completed_result():
    runs = [dict(observation_loss=dict(episodes=dict(pose_detected=[], depth_all=[])))]
    return dict(format='research-b-final-result/1', cohort='INDEPENDENT', protocol_sha256='protocol',
                roster_sha256='roster', pc_id='PC01', pacing='throughput', repeats=3, fault_mode='NO_INJECTION',
                participant=dict(status='VERIFIED', namespace='study-b', canonical_id='person-3'),
                session_id='session-01', clip_id='clip-01', sequence='seq-A',
                methods={method: dict(repeat_windows_agree=True, windows=complete_labels(), runs=deepcopy(runs))
                         for method in final.METHODS})


def test_aggregate_deduplicates_people_and_keeps_observation_strata_separate():
    baseline = completed_result()
    second = dict(deepcopy(baseline), sequence='seq-B', session_id='session-02')
    output = final.aggregate([baseline, second])
    assert (output['participants'], output['sessions'], output['clips']) == (1, 2, 2)
    assert output['methods']['E0']['h9_pass_rate'] == pytest.approx(5 / 6)
    with pytest.raises(ValueError, match='Duplicate decoded'):
        final.aggregate([baseline, baseline])
    second['methods']['E0']['runs'][0]['observation_loss']['episodes']['depth_all'].append(
        {'inputs': 2, 'start_ms': 100, 'last_failed_ms': 140})
    assert final.observation_stratum(second) == 'E0_OBSERVATION_LOSS_IN_H9'
    with pytest.raises(ValueError, match='separately'):
        final.aggregate([baseline, second])
    with pytest.raises(ValueError, match='Engineering'):
        final.aggregate([dict(baseline, cohort='ENGINEERING')])


def test_repeat_order_rotates_and_uses_every_policy():
    order = final.order_for(4)
    assert len({block[0] for block in order}) == 4
    assert all(set(block) == set(final.METHODS) for block in order)


def test_protocol_refuses_changed_model_or_incomplete_implementation_map():
    protocol = dict(format='research-b-final-protocol/1', methods=final.METHODS, binding=BINDING,
                    implementation_sha256={})
    with pytest.raises(ValueError, match='binding mismatch'):
        final.verify_protocol(protocol)
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        final.verify_protocol(dict(protocol, binding=final.FROZEN_BINDING))
