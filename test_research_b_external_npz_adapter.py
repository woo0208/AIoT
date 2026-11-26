"""Synthetic-only checks for the external inspection adapter."""

import csv
from decimal import Decimal
import json
from pathlib import Path

import cv2
import numpy as np
import pyrealsense2 as rs
import pytest

from adaptive_v2_replay import AdaptiveV2Gate, HoldProgress
from e0_fs3 import WINDOW_MS
from e0_replay import SoftwareFrames
from f1_sample_aggregator import H9_FEATURE_NAMES, HFrameRecord, aggregate_h5_h9_sample
from posture_geometry import sample_aligned_depth_m
from raw_rgbd_recording import _sha
from raw_rgbd_replay import RawClipReader
from replay_policy import ReplayGate
from research_b_external_npz_adapter import CONFIRMATION_FORMAT, SELECTION_MODE, convert_subset, main
from research_b_fair_replay import MatchedIdleFixed2Gate
from research_b_preflight import inspect_source
from research_b_robustness_replay import Uniform85Gate


def write_manifest(source, receipt):
    root = source.parent
    manifest = root / 'FILES_SHA256.txt'
    manifest.write_text(''.join(f'{_sha(path)}  {path.relative_to(root).as_posix()}\n'
                                for path in sorted(source.rglob('*')) if path.is_file()), encoding='utf-8')
    if receipt.exists():
        confirmation = json.loads(receipt.read_text(encoding='utf-8'))
        confirmation['provider_manifest_sha256'] = _sha(manifest)
        receipt.write_text(json.dumps(confirmation), encoding='utf-8')
    return _sha(manifest)


def write_rows(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / 'source' / 'fixture01'
    (source / 'frames').mkdir(parents=True)
    dimensions = dict(width=64, height=48)
    device = dict(depth_scale_m=.002,
                  streams={name: dict(**dimensions, fps=30, format=encoding) for name, encoding in
                           (('color', 'format.bgr8'), ('depth', 'format.z16'))},
                  color_intrinsics=dict(**dimensions, fx=50., fy=50., ppx=31.5, ppy=23.5,
                                        model='distortion.none', coeffs=[0.] * 5))
    (source / 'meta.json').write_text(json.dumps(dict(session_id=source.name, device=device)), encoding='utf-8')
    rows = []
    for i, stamp in enumerate(('1000.25', '1192.375', '1396.625')):
        row = dict(frame_index=str(i), mono_time=('1.0123456', '1.202341', '1.404321')[i],
                   sys_time=('1577836801.0123456', '1577836801.202341', '1577836801.404321')[i])
        for name in ('color', 'depth'):
            row[f'{name}_frame_number'] = str(101 + i * 5)
            row[f'{name}_hw_timestamp_ms'] = stamp if name == 'color' else str(float(stamp) - 6.)
            row[f'{name}_ts_domain'] = 'timestamp_domain.system_time'
        rows.append(row)
        color = np.full((48, 64, 3), [13, 101, 201 - i], dtype=np.uint8)
        depth = np.full((48, 64), 345 + i, dtype=np.uint16)
        depth[0, :3] = [0, 25000, 65534]
        assert cv2.imwrite(str(source / 'frames' / f'{i:06d}_color.jpg'), color)
        assert cv2.imwrite(str(source / 'frames' / f'{i:06d}_depth.png'), depth)
    write_rows(source / 'frames.csv', rows)
    output, receipt = tmp_path / 'inspected', tmp_path / 'receipt.json'
    evidence = dict(status='CONFIRMED', evidence_ref='Synthetic fixture evidence')
    confirmation = dict(format=CONFIRMATION_FORMAT, session_id=source.name,
                        provider_manifest_sha256=write_manifest(source, receipt),
                        permission=dict(**evidence, local_conversion_and_inspection=True, source_start=1, source_count=2),
                        clock=dict(**evidence, pair_timestamp_column='color_hw_timestamp_ms',
                                   first_pair='EXCLUDE', max_abs_sensor_offset_ms=7.),
                        depth=dict(**evidence, scale_m_per_unit=.002, invalid_codes=[0, 65535], code_65535='INVALID'),
                        alignment=dict(**evidence, representation='ALREADY_COLOR_ALIGNED',
                                       z_reference='COLOR_CAMERA_Z', uses_stored_color_intrinsics=True))
    receipt.write_text(json.dumps(confirmation), encoding='utf-8')
    return source, output, receipt, rows


def convert(fixture):
    source, output, receipt, _ = fixture
    return convert_subset(source, output, receipt, start=1, count=2)


def update(receipt, section, **values):
    confirmation = json.loads(receipt.read_text(encoding='utf-8'))
    confirmation[section].update(values)
    receipt.write_text(json.dumps(confirmation), encoding='utf-8')


def test_subset_round_trip_reader_sdk_pixels_time_and_scale(fixture):
    source, output, _, rows = fixture
    before = {path: _sha(path) for path in source.parent.rglob('*') if path.is_file()}
    inspected = convert(fixture)
    reader = RawClipReader(output)
    assert reader.identity['scope'] == 'EXTERNAL_PREALIGNED_INSPECTION_ONLY'
    assert inspected == inspect_source(output)
    assert inspected['packet_counts'] == dict(packets=2, paired=2, missing_color=0, missing_depth=0)
    assert inspected['input_checks'] == 'REVIEW_REQUIRED'  # Stored sensor number gaps are preserved.
    assert inspected['max_abs_reported_pair_offset_ms'] == 6
    assert inspected['depth_scale_m'] == .002
    assert not (output / 'recording_metadata').exists()
    software = SoftwareFrames(rs, reader.camera)
    try:
        for i, packet in enumerate(reader.packets(), 1):
            assert packet.record['frame_index'] == i and packet.record['source_frame_index'] == i
            source_row = rows[i]
            assert packet.record['frameset_timestamp_ms'] == float(source_row['color_hw_timestamp_ms'])
            assert packet.record['frameset_number'] == int(source_row['color_frame_number'])
            assert all(source_row[key] == value for key, value in packet.record['external_clock'].items())
            assert packet.record['preceding_event_index'] is None
            for file, array, flag, key in (
                    ('color.jpg', packet.color_bgr, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION, 'source_rgb'),
                    ('depth.png', packet.depth_z16, cv2.IMREAD_UNCHANGED, 'source_depth')):
                original = source / 'frames' / f'{i:06d}_{file}'
                np.testing.assert_array_equal(array, cv2.imread(str(original), flag))
                assert packet.record[key]['sha256'] == _sha(original)
            assert packet.color_bgr.dtype == np.uint8 and packet.color_bgr[0, 0, 2] > packet.color_bgr[0, 0, 0]
            assert packet.depth_z16.dtype == np.uint16 and list(packet.depth_z16[0, :3]) == [0, 25000, 65534]
            assert sample_aligned_depth_m(packet.depth_z16, 32, 24, reader.camera['depth_scale_m']) == (345 + i) * .002
            frames = software.compose(packet)
            np.testing.assert_array_equal(np.asanyarray(frames.get_depth_frame().get_data()), packet.depth_z16)
            np.testing.assert_array_equal(np.asanyarray(frames.get_color_frame().get_data()), packet.color_bgr)
            assert frames.get_depth_frame().get_distance(32, 24) == pytest.approx((345 + i) * .002)
    finally:
        software.close()
    assert before == {path: _sha(path) for path in before}
    with pytest.raises(ValueError, match='new output'):
        convert(fixture)


@pytest.mark.parametrize(('section', 'values', 'error'), [
    ('permission', dict(status='PENDING'), 'confirmed evidence'),
    ('permission', dict(local_conversion_and_inspection=False), 'not approved'),
    ('permission', dict(source_start=2), 'confirmed inspection scope'),
    ('clock', dict(pair_timestamp_column='mono_time'), 'Unsupported pair clock'),
    ('clock', dict(first_pair='UNKNOWN'), 'First-pair disposition'),
    ('clock', dict(max_abs_sensor_offset_ms=5), 'outside the confirmed pairing rule'),
    ('depth', dict(scale_m_per_unit=.001), 'Depth scale differs'),
    ('depth', dict(code_65535='UNKNOWN'), 'classification for Depth code 65535'),
    ('alignment', dict(representation='NATIVE_DEPTH'), 'Unsupported Depth representation'),
    ('alignment', dict(z_reference='UNKNOWN'), 'Unsupported Depth representation'),
    ('alignment', dict(evidence_ref=''), 'confirmed evidence'),
])
def test_confirmation_gate(fixture, section, values, error):
    _, output, receipt, _ = fixture
    update(receipt, section, **values)
    with pytest.raises(ValueError, match=error):
        convert(fixture)
    assert not output.exists()


def test_missing_pair_and_manifest_binding(fixture):
    source, output, receipt, _ = fixture
    missing = source / 'frames/000002_depth.png'
    original = missing.read_bytes()
    missing.unlink()
    with pytest.raises(FileNotFoundError):
        convert(fixture)
    assert not output.exists()
    missing.write_bytes(original + b'changed')
    with pytest.raises(ValueError, match='SHA-256 missing or mismatched'):
        convert(fixture)
    write_manifest(source, Path(source / 'nonexistent-receipt.json'))
    with pytest.raises(ValueError, match='manifest differs'):
        convert(fixture)
    assert receipt.is_file() and not output.exists()


@pytest.mark.parametrize(('mutation', 'error'), [
    ('bad_index', 'indices must be unique'),
    ('collision', 'collides or regresses'),
    ('domain', 'single domain'),
    ('depth_8bit', '16-bit grayscale'),
    ('invalid_positive', 'Nonzero invalid Depth code present'),
])
def test_rejects_input_defects(fixture, mutation, error):
    source, output, receipt, rows = fixture
    if mutation == 'bad_index':
        rows[2]['frame_index'] = '1'
    if mutation == 'collision':
        rows[2].update(color_hw_timestamp_ms='1192.875', depth_hw_timestamp_ms='1186.875')
    if mutation == 'domain':
        rows[2]['depth_ts_domain'] = 'timestamp_domain.hardware_clock'
    if mutation in ('depth_8bit', 'invalid_positive'):
        value, dtype = (10, np.uint8) if mutation == 'depth_8bit' else (65535, np.uint16)
        assert cv2.imwrite(str(source / 'frames/000002_depth.png'), np.full((48, 64), value, dtype=dtype))
    write_rows(source / 'frames.csv', rows)
    write_manifest(source, receipt)
    with pytest.raises(ValueError, match=error):
        convert(fixture)
    assert not output.exists()


def test_subset_limit_first_pair_output_location_and_host_clock(fixture):
    source, output, receipt, rows = fixture
    with pytest.raises(ValueError, match='1–20'):
        convert_subset(source, output, receipt, start=1, count=21)
    update(receipt, 'permission', source_start=0)
    with pytest.raises(ValueError, match='First-pair disposition'):
        convert_subset(source, output, receipt, start=0, count=2)
    update(receipt, 'clock', first_pair='INCLUDE', pair_timestamp_column='sys_time')
    with pytest.raises(ValueError, match='outside the source package'):
        convert_subset(source, source / 'output', receipt, start=0, count=2)
    convert_subset(source, output, receipt, start=0, count=2)
    for i, packet in enumerate(RawClipReader(output).packets()):
        assert packet.record['frameset_timestamp_ms'] == pytest.approx(float(rows[i]['sys_time']) * 1000, rel=0, abs=.001)
        assert packet.record['frameset_timestamp_domain'] == 'timestamp_domain.system_time'
        assert packet.record['frameset_number'] is None


def prepare_selection(fixture, timestamps, *, indices=None, first_pair='INCLUDE', missing_depth=()):
    source, _, receipt, template = fixture
    rows = []
    indices = range(len(timestamps)) if indices is None else indices
    for index, value in zip(indices, timestamps, strict=True):
        stamp = Decimal(value)
        row = dict(template[0], frame_index=str(index), mono_time=str(stamp / 1000), sys_time=str(stamp / 1000),
                   color_hw_timestamp_ms=str(stamp), depth_hw_timestamp_ms=str(stamp - 6),
                   color_frame_number=str(100 + index), depth_frame_number=str(300 + index))
        rows.append(row)
        path = source / 'frames' / f'{index:06d}'
        bgr = np.full((48, 64, 3), (13, 101, 201 - index % 100), dtype=np.uint8)
        depth = np.full((48, 64), 1000 + index, dtype=np.uint16)
        depth[0, :2] = 0, 65534
        assert cv2.imwrite(str(path.with_name(path.name + '_color.jpg')), bgr)
        if index in missing_depth:
            path.with_name(path.name + '_depth.png').unlink(missing_ok=True)
        else:
            assert cv2.imwrite(str(path.with_name(path.name + '_depth.png')), depth)
    write_rows(source / 'frames.csv', rows)
    write_manifest(source, receipt)
    start = int(first_pair == 'EXCLUDE')
    update(receipt, 'clock', first_pair=first_pair)
    update(receipt, 'permission', source_start=start, source_count=len(rows) - start, selection_mode=SELECTION_MODE)
    return rows


def run_selection(fixture, count, *, start=0):
    source, output, receipt, _ = fixture
    convert_subset(source, output, receipt, start=start, count=count, select_15fps=True)
    reader = RawClipReader(output)
    selection_path = output / reader.identity['selection_index']['file']
    assert reader.identity['selection_index']['sha256'] == _sha(selection_path)
    return list(reader.packets()), json.loads(selection_path.read_text(encoding='utf-8'))


def regular_times(fps, count):
    # Round upwards only when generating synthetic CSV input from the rational grid.
    return [1000 + Decimal((i * 1000000000 + fps - 1) // fps) / 1000000 for i in range(count)]


@pytest.mark.parametrize('fps', [15, 30, 60])
def test_regular_15_30_60_fps_end_to_end(fixture, fps):
    source, output, _, _ = fixture
    rows = prepare_selection(fixture, regular_times(fps, fps + 1))
    hashes_before = {path: _sha(path) for path in source.parent.rglob('*') if path.is_file()}
    packets, selection = run_selection(fixture, len(rows))
    assert selection['anchor_timestamp_ms_exact'] == '1000'
    assert selection['slot_period_ms'] == '200/3' and selection['empty_bins'] == 0
    assert selection['selected_pairs'] == 16 and selection['thinned_pairs'] == fps - 15
    assert len(packets) == 16 and len(selection['decisions']) == len(rows)
    assert [p.record['source_frame_index'] for p in packets] == list(range(0, fps + 1, fps // 15))
    assert inspect_source(output)['packet_counts']['paired'] == len(packets)
    for ordinal, packet in enumerate(packets, 1):
        i = packet.record['source_frame_index']
        assert packet.record['selection'] == {'bin': ordinal - 1, 'reason': SELECTION_MODE}
        assert packet.record['frame_index'] == ordinal
        assert packet.record['sensors']['depth']['number'] == 300 + i
        assert packet.record['external_clock']['depth_hw_timestamp_ms'] == rows[i]['depth_hw_timestamp_ms']
        assert packet.record['frameset_timestamp_ms'] == float(rows[i]['color_hw_timestamp_ms'])
        color = source / 'frames' / f'{i:06d}_color.jpg'
        np.testing.assert_array_equal(packet.color_bgr, cv2.imread(str(color)))
        assert packet.depth_z16.dtype == np.uint16 and packet.depth_z16[1, 0] == 1000 + i
        assert tuple(packet.depth_z16[0, :2]) == (0, 65534)
    assert hashes_before == {path: _sha(path) for path in hashes_before}


def test_irregular_sparse_timestamps_and_empty_slots(fixture):
    offsets = [0, 34, 67, 101, 199, 202, 230, 345]
    rows = prepare_selection(fixture, [1000 + n for n in offsets], indices=[0, 1, 2, 4, 5, 6, 7, 9])
    packets, selection = run_selection(fixture, len(rows))
    assert [p.record['source_frame_index'] for p in packets] == [0, 2, 5, 6, 9]
    assert [p.record['frameset_timestamp_ms'] for p in packets] == [1000, 1067, 1199, 1202, 1345]
    assert [p.record['selection']['bin'] for p in packets] == [0, 1, 2, 3, 5]
    assert selection['empty_bins'] == 1 and selection['unindexed_source_positions'] == 2
    assert selection['thinned_pairs'] == 3


def test_missing_pairs_require_approval_even_if_the_bin_is_full(fixture):
    _, output, receipt, _ = fixture
    rows = prepare_selection(fixture, [1000, 1034, 1067, 1101, 1202], missing_depth={1, 2})
    with pytest.raises(FileNotFoundError, match='000001_depth'):
        run_selection(fixture, len(rows))
    assert not output.exists()
    update(receipt, 'permission', excluded_pairs={'1': 'Confirmed missing Depth', '2': 'Confirmed missing Depth'})
    packets, selection = run_selection(fixture, len(rows))
    assert [p.record['source_frame_index'] for p in packets] == [0, 3, 4]
    assert selection['approved_exclusions'] == 2
    assert selection['decisions'][2]['exclusion_detail'] == 'Confirmed missing Depth'


@pytest.mark.parametrize('defect', ['duplicate_time', 'regression', 'video_collision', 'duplicate_index'])
def test_rejects_bad_clock_or_index_inside_thinned_bin(fixture, defect):
    source, output, receipt, _ = fixture
    rows = prepare_selection(fixture, [1000, 1034, 1067])
    if defect == 'duplicate_index':
        rows[1]['frame_index'] = rows[0]['frame_index']
    else:
        stamp = {'duplicate_time': '1000', 'regression': '999', 'video_collision': '1000.5'}[defect]
        rows[1].update(color_hw_timestamp_ms=stamp, depth_hw_timestamp_ms=str(Decimal(stamp) - 6))
    write_rows(source / 'frames.csv', rows)
    write_manifest(source, receipt)
    with pytest.raises(ValueError, match='clock|indices'):
        run_selection(fixture, len(rows))
    assert not output.exists()


def test_explicit_scope_and_first_pair_anchor(fixture):
    source, output, receipt, _ = fixture
    rows = prepare_selection(fixture, [1000, 1034, 1067, 1101], first_pair='EXCLUDE', missing_depth={0})
    with pytest.raises(ValueError, match='requires --select-15fps'):
        convert_subset(source, output, receipt, start=1, count=3)
    update(receipt, 'permission', selection_mode=None)
    with pytest.raises(ValueError, match='explicit selection approval'):
        run_selection(fixture, len(rows) - 1, start=1)
    update(receipt, 'permission', selection_mode=SELECTION_MODE, source_start=2, source_count=2)
    with pytest.raises(ValueError, match='prefix anchored'):
        run_selection(fixture, 2, start=2)
    assert not output.exists()
    update(receipt, 'permission', source_start=1, source_count=3)
    packets, selection = run_selection(fixture, 3, start=1)
    assert selection['anchor_timestamp_ms_exact'] == '1034'
    assert selection['decisions'][0]['exclusion_detail'] == 'CONFIRMED_FIRST_PAIR_EXCLUSION'
    assert [p.record['source_frame_index'] for p in packets] == [1, 3]
    assert source.is_dir()


def test_cli_exact_bins_with_epoch_clock(fixture, monkeypatch, capsys):
    source, output, receipt, _ = fixture
    epoch = Decimal('1794000000000')
    rows = prepare_selection(fixture, [epoch, epoch + Decimal('199.99999'), epoch + 234])
    update(receipt, 'clock', pair_timestamp_column='sys_time')
    monkeypatch.setattr('sys.argv', ['adapter', '--source', str(source), '--output', str(output),
                                    '--confirmation', str(receipt), '--start', '0', '--count', '3', '--select-15fps'])
    main()
    assert json.loads(capsys.readouterr().out)['status'] == 'PACKAGED_FOR_INSPECTION_ONLY'
    packets = list(RawClipReader(output).packets())
    assert [p.record['selection']['bin'] for p in packets] == [0, 2, 3]
    assert packets[1].record['external_clock']['sys_time'] == rows[1]['sys_time']
    assert packets[1].record['frameset_number'] is None


@pytest.mark.parametrize(('n_inputs', 'first_packet', 'min_valid', 'fixed_pass'), [
    (149, 0, 75, True), (150, 0, 75, True), (151, 1, 76, False),
])
def test_149_150_151_actual_selected_window_with_frozen_gates(fixture, n_inputs, first_packet, min_valid, fixed_pass):
    stamps = regular_times(15, 153)
    if n_inputs == 149:
        del stamps[40]
    elif n_inputs == 151:
        stamps[1] += 10  # Start late in bin 1; bin 151 still lies inside the hold.
    rows = prepare_selection(fixture, stamps)
    packets, _ = run_selection(fixture, len(rows))
    roi = packets[first_packet:]
    end = roi[0].record['frameset_timestamp_ms'] + WINDOW_MS
    window = [p for p in roi if p.record['frameset_timestamp_ms'] < end]
    assert len(window) == n_inputs and roi[n_inputs].record['frameset_timestamp_ms'] >= end
    image = np.zeros((48, 64, 3), np.uint8)  # Stable synthetic policy signal.
    for gate, expected, pass_h9 in ((ReplayGate(), n_inputs, True), (MatchedIdleFixed2Gate(), 75, fixed_pass),
                                     (Uniform85Gate(), 85, True), (AdaptiveV2Gate(), 85, True)):
        valid_count, records = 0, []
        for packet in window:
            stamp, i = packet.record['frameset_timestamp_ms'], packet.record['frame_index']
            hold = HoldProgress(end, len(records), valid_count)
            decision = gate.select(image, stamp, i) if type(gate) is ReplayGate else gate.select(image, stamp, i, hold)
            if decision['full']:
                gate.completed(stamp, i, True)
                valid_count += 1
            values = dict.fromkeys(H9_FEATURE_NAMES, 0.0 if decision['full'] else None)
            records.append(HFrameRecord('a', 'r', i, 'p', None, 's', 'unlabelled', values))
        result = aggregate_h5_h9_sample(records)
        assert result.n_frames == n_inputs and result.common_valid_count == valid_count == expected
        assert result.eligible == pass_h9 == (valid_count >= min_valid)
