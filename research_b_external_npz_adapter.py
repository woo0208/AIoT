"""Pack confirmed external JPEG/Z16 pairs for NPZ Reader inspection only."""

import argparse
import csv
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import cv2
import numpy as np
import pyrealsense2 as rs

from raw_rgbd_recording import FORMAT, _sha, pairing_info
from raw_rgbd_replay import RawClipReader
from research_b_preflight import _check_geometry, inspect_source


CONFIRMATION_FORMAT = 'research-b-external-inspect-confirmation/1'
SELECTION_MODE = 'FIRST_ELIGIBLE_15FPS'
SENSOR_CLOCKS = {'color_hw_timestamp_ms': 'color', 'depth_hw_timestamp_ms': 'depth'}
CLOCK_DOMAINS = {str(domain) for domain in rs.timestamp_domain.__members__.values()}
CLOCK_COLUMNS = ('mono_time', 'sys_time', 'color_hw_timestamp_ms', 'depth_hw_timestamp_ms',
                 'color_ts_domain', 'depth_ts_domain')
PNG_GRAY16 = b'\x10\x00'


def _confirmation(document, session, start, count, *, select_15fps):
    if document['format'] != CONFIRMATION_FORMAT or document['session_id'] != session:
        raise ValueError('Confirmation format or source session mismatch')
    if not re.fullmatch(r'[a-f0-9]{64}', document['provider_manifest_sha256']):
        raise ValueError('Confirmation must bind the audited provider manifest SHA-256')
    permission, clock = document['permission'], document['clock']
    depth, alignment = document['depth'], document['alignment']
    for section in (permission, clock, depth, alignment):
        if (section.get('status') != 'CONFIRMED' or not isinstance(section.get('evidence_ref'), str)
                or not section['evidence_ref'].strip()):
            raise ValueError('Local conversion, clock, depth and alignment need confirmed evidence')
    if permission.get('local_conversion_and_inspection') is not True:
        raise ValueError('Local conversion and inspection are not approved')
    if (permission['source_start'] != start or permission['source_count'] != count
            or type(permission['source_start']) is not int or type(permission['source_count']) is not int):
        raise ValueError('Selected source range differs from the confirmed inspection scope')
    if clock['pair_timestamp_column'] not in SENSOR_CLOCKS.keys() | {'sys_time'}:
        raise ValueError('Unsupported pair clock mapping; no automatic relabeling or rebasing')
    if clock['first_pair'] not in ('INCLUDE', 'EXCLUDE') or (start == 0 and clock['first_pair'] != 'INCLUDE'):
        raise ValueError('First-pair disposition is unresolved or disallows this range')
    if select_15fps and (permission.get('selection_mode') != SELECTION_MODE
                         or start != int(clock['first_pair'] == 'EXCLUDE')):
        raise ValueError('15 FPS needs explicit selection approval and a prefix anchored at the first source pair')
    if not select_15fps and permission.get('selection_mode') is not None:
        raise ValueError('Selection-scoped confirmation requires --select-15fps')
    maximum = clock['max_abs_sensor_offset_ms']
    if type(maximum) not in (float, int) or not math.isfinite(maximum) or maximum < 0:
        raise ValueError('Confirmed sensor offset bound required')
    invalid = depth['invalid_codes']
    if (not isinstance(invalid, list) or 0 not in invalid
            or any(type(code) is not int or not 0 <= code <= 65535 for code in invalid)
            or len(set(invalid)) != len(invalid)):
        raise ValueError('Confirmed Z16 invalid codes must include 0')
    if depth['code_65535'] not in ('VALID', 'INVALID') or (65535 in invalid) != (depth['code_65535'] == 'INVALID'):
        raise ValueError('Confirmed and consistent classification for Depth code 65535 required')
    if (alignment['representation'] != 'ALREADY_COLOR_ALIGNED'
            or alignment['z_reference'] != 'COLOR_CAMERA_Z'
            or alignment['uses_stored_color_intrinsics'] is not True):
        raise ValueError('Unsupported Depth representation or unconfirmed RGB geometry')


def _source_file(path, root, hashes):
    relative = path.relative_to(root).as_posix()
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError(f'Expected regular source path: {relative}')
    digest = hashes.get(relative.casefold())
    if digest is None:
        raise ValueError(f'Source SHA-256 missing or mismatched: {relative}')
    return dict(path=relative, sha256=digest)


def _verified_bytes(path, root, hashes):
    reference = _source_file(path, root, hashes)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != reference['sha256']:
        raise ValueError(f"Source SHA-256 missing or mismatched: {reference['path']}")
    return payload, reference


def _manifest(path, root):
    hashes = {}
    if path.resolve(strict=True) != path:
        raise ValueError('Checksum manifest must be inside the original package')
    payload = path.read_bytes()
    for line in payload.decode('utf-8-sig').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *](.+)', line)
        if not match:
            raise ValueError('Malformed provider SHA-256 manifest')
        digest, relative = match.groups()
        parts = relative.split('/')
        if (len(parts) < 2 or set(parts) & {'', '.', '..'} or '\\' in relative
                or ':' in relative or relative.casefold() in hashes):
            raise ValueError('Unsafe or duplicate provider SHA-256 manifest path')
        hashes[relative.casefold()] = digest.lower()
    return hashes, dict(path=path.relative_to(root).as_posix(), sha256=hashlib.sha256(payload).hexdigest())


def _camera(device, depth):
    scale = depth['scale_m_per_unit']
    if (type(scale) not in (int, float) or not math.isfinite(scale)
            or scale <= 0 or scale != device['depth_scale_m']):
        raise ValueError('Confirmed Depth scale differs from source meta.json')
    streams = {name: dict(device['streams'][name]) for name in ('color', 'depth')}
    calibration = device['color_intrinsics']
    for profile in streams.values():
        if any(profile[key] != calibration[key] for key in ('width', 'height')):
            raise ValueError('Color and aligned Depth must share the calibrated pixel grid')
        profile['intrinsics'] = {key: calibration[key] for key in ('fx', 'fy', 'ppx', 'ppy', 'model', 'coeffs')}
    camera = dict(streams=streams, depth_scale_m=scale,
                  source_kind='EXTERNAL_PREALIGNED_INSPECTION_ONLY',
                  depth_to_color_extrinsics=dict(rotation=[1, 0, 0, 0, 1, 0, 0, 0, 1], translation=[0, 0, 0]),
                  geometry_note='Virtual same-grid declaration for inspection; not measured native extrinsics')
    _check_geometry(rs, camera, native_file=False)
    return camera


def _clock_row(row, clock, previous):
    sensors = {}
    for uid, name in enumerate(('depth', 'color'), 1):
        domain = row[f'{name}_ts_domain']
        stamp, number = float(row[f'{name}_hw_timestamp_ms']), int(row[f'{name}_frame_number'])
        if domain not in CLOCK_DOMAINS or not 0 <= stamp < 2**63 / 1000 or number < 0:
            raise ValueError('Invalid source sensor clock')
        if previous is not None:
            prior = previous['sensors'][name]
            if domain != prior['timestamp_domain'] or stamp <= prior['timestamp_ms'] or number <= prior['number']:
                raise ValueError('Source sensor clock is not increasing in a single domain')
        sensors[name] = dict(status='MEASURED', timestamp_ms=stamp, number=number,
                             timestamp_domain=domain, profile_uid=uid, stream_type=f'stream.{name}', stream_index=0)
    color, depth = sensors['color'], sensors['depth']
    if (color['timestamp_domain'] != depth['timestamp_domain']
            or abs(color['timestamp_ms'] - depth['timestamp_ms']) > clock['max_abs_sensor_offset_ms']):
        raise ValueError('Pair offset or domain is outside the confirmed pairing rule')
    mono, system = (Decimal(row[key]) for key in ('mono_time', 'sys_time'))
    if not all(value.is_finite() and value >= 0 for value in (mono, system)):
        raise ValueError('Invalid source host timestamp')
    column = clock['pair_timestamp_column']
    if column == 'sys_time':
        domain, stamp, number = 'timestamp_domain.system_time', float(system * 1000), None
    else:
        source = sensors[SENSOR_CLOCKS[column]]
        domain, stamp, number = source['timestamp_domain'], source['timestamp_ms'], source['number']
    if not 0 <= stamp < 2**63 / 1000 or (previous is not None and (
            domain != previous['frameset_timestamp_domain'] or int(stamp) <= int(previous['frameset_timestamp_ms']))):
        raise ValueError('Representative clock collides or regresses in VIDEO milliseconds')
    return dict(sensors=sensors, frameset_timestamp_ms=stamp, frameset_timestamp_domain=domain, frameset_number=number,
                external_clock={key: row[key] for key in CLOCK_COLUMNS})


def _pair_paths(source, index):
    directory = source / 'frames'
    return directory / f'{index:06d}_color.jpg', directory / f'{index:06d}_depth.png'


def _select_15fps(rows, *, start, source, hashes, document):
    """Choose a source-ordered prefix on the session grid; no pixel-based selection."""
    clock_rules = document['clock']
    column = clock_rules['pair_timestamp_column']
    approved_exclusions = document['permission'].get('excluded_pairs', {})
    if (not isinstance(approved_exclusions, dict)
            or set(approved_exclusions) - {row['frame_index'] for row in rows[start:]}
            or any(not isinstance(reason, str) or not reason.strip() for reason in approved_exclusions.values())):
        raise ValueError('Excluded pairs must name original indices within the approved prefix and give reasons')
    if not start and rows[0]['frame_index'] in approved_exclusions:
        raise ValueError('Use the confirmed EXCLUDE first-pair disposition for an ineligible first pair')

    selected, decisions = [], []
    previous = anchor = last_bin = None
    for position, row in enumerate(rows):
        index = int(row['frame_index'])
        decision = dict(source_frame_index=index, source_csv_row=position,
                        source_clock={key: row.get(key) for key in CLOCK_COLUMNS},
                        source_sensor_numbers={name: row.get(f'{name}_frame_number') for name in ('color', 'depth')})
        decisions.append(decision)
        if position < start or row['frame_index'] in approved_exclusions:
            reason = 'CONFIRMED_FIRST_PAIR_EXCLUSION' if position < start else approved_exclusions[row['frame_index']]
            decision.update(reason='APPROVED_EXCLUSION', exclusion_detail=reason)
            continue
        # An unexpected missing member is a data fault, even in an already occupied bin.
        color_path, depth_path = _pair_paths(source, index)
        decision.update(source_rgb=_source_file(color_path, source.parent, hashes),
                        source_depth=_source_file(depth_path, source.parent, hashes))
        clock = _clock_row(row, clock_rules, previous)
        previous = clock
        stamp = Fraction(row[column]) * (1000 if column == 'sys_time' else 1)
        if anchor is None:
            anchor = stamp
        bin_index = (stamp - anchor) * 3 // 200
        decision['bin'] = bin_index
        if bin_index == last_bin:
            decision['reason'] = 'BIN_ALREADY_OCCUPIED'
            continue
        last_bin = bin_index
        decision.update(reason=SELECTION_MODE, reader_frame_index=len(selected) + 1)
        selected.append((row, clock, dict(bin=bin_index, reason=SELECTION_MODE)))
    if not selected:
        raise ValueError('15 FPS selection found no eligible source pairs')
    missing_indices = sum(b['source_frame_index'] - a['source_frame_index'] - 1
                          for a, b in zip(decisions, decisions[1:]))
    return selected, dict(mode=SELECTION_MODE, anchor_timestamp_ms_exact=str(anchor),
                          representative_clock_column=column, clock_domain=previous['frameset_timestamp_domain'],
                          slot_period_ms='200/3', empty_bins=last_bin + 1 - len(selected),
                          unindexed_source_positions=missing_indices, selected_pairs=len(selected),
                          approved_exclusions=sum(d['reason'] == 'APPROVED_EXCLUSION' for d in decisions),
                          thinned_pairs=sum(d['reason'] == 'BIN_ALREADY_OCCUPIED' for d in decisions), decisions=decisions)


def _decode(color_bytes, depth_bytes, camera, invalid_codes):
    if not color_bytes.startswith(b'\xff\xd8\xff'):
        raise ValueError('Expected a JPEG color file')
    if (not depth_bytes.startswith(b'\x89PNG\r\n\x1a\n')
            or depth_bytes[12:16] != b'IHDR' or depth_bytes[24:26] != PNG_GRAY16):
        raise ValueError('Expected a 16-bit grayscale Depth PNG')
    color = cv2.imdecode(np.frombuffer(color_bytes, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    depth = cv2.imdecode(np.frombuffer(depth_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    profile = camera['streams']['color']
    height, width = profile['height'], profile['width']
    if color is None or color.dtype != np.uint8 or color.shape != (height, width, 3):
        raise ValueError('Unexpected decoded color shape or dtype')
    if depth is None or depth.dtype != np.uint16 or depth.shape != (height, width):
        raise ValueError('Unexpected decoded Depth shape or dtype')
    if any(code and np.any(depth == code) for code in invalid_codes):
        raise ValueError('Nonzero invalid Depth code present; unchanged sampler treats it as positive')
    return dict(color_bgr=color, depth_z16=depth)


def _json(path, content):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(content, stream, ensure_ascii=False, allow_nan=False, indent=2)


def convert_subset(source, output, confirmation, *, start, count, select_15fps=False, authorization=None, actor=None):
    if (type(start) is not int or start < 0 or type(count) is not int or count < 1
            or (not select_15fps and count > 20)):
        if select_15fps:
            raise ValueError('Use a nonnegative source start and a positive source count')
        raise ValueError('Use a nonnegative source start and 1–20 consecutive RGB-D pairs')
    source, output, confirmation = Path(source), Path(output), Path(confirmation)
    session = source.name
    project = Path(__file__).resolve().parent
    gate_root = project / 'analysis/RESEARCH_B/EXTERNAL_TEAM_VALIDATION'
    if source.resolve().is_relative_to(project / 'another_team'):
        import sys
        sys.path.insert(0, str(gate_root))
        from external_authorization import REPLAY, authorization_for, require_grant
        grant = authorization_for(authorization, REPLAY, actor=actor)
    else:
        grant = None
    document_bytes = confirmation.read_bytes()
    document = json.loads(document_bytes.decode('utf-8-sig'))
    _confirmation(document, session, start, count, select_15fps=select_15fps)
    source = source.resolve(strict=True)
    if source.name != session or not source.is_dir():
        raise ValueError('Source must be a session directory')
    root = source.parent
    output = output.resolve()
    if output.is_relative_to(root) or output.exists() or not output.parent.is_dir():
        raise ValueError('Use a new output directory under an existing parent outside the source package')

    hashes, manifest = _manifest(root / 'FILES_SHA256.txt', root)
    if manifest['sha256'] != document['provider_manifest_sha256']:
        raise ValueError('Source manifest differs from the one bound in confirmation')
    if grant is not None:
        require_grant(grant, REPLAY, actor=actor, session=session, manifest=manifest['sha256'])
    meta_bytes, meta_ref = _verified_bytes(source / 'meta.json', root, hashes)
    meta = json.loads(meta_bytes.decode('utf-8-sig'))
    if meta['session_id'] != session:
        raise ValueError('Source meta.json session mismatch')
    camera = _camera(meta['device'], document['depth'])
    csv_bytes, csv_ref = _verified_bytes(source / 'frames.csv', root, hashes)
    rows, previous_index = [], -1
    first_row = 0 if select_15fps else start
    with io.StringIO(csv_bytes.decode('utf-8-sig'), newline='') as stream:
        for position, row in enumerate(csv.DictReader(stream)):
            index = int(row['frame_index'])
            if index <= previous_index or (not select_15fps and index != position):
                if select_15fps:
                    raise ValueError('Source frame indices must be nonnegative, unique and increasing in file order')
                raise ValueError('Source frame indices must be unique, contiguous and in file order')
            previous_index = index
            if first_row <= position < start + count:
                rows.append(row)
    if len(rows) != start + count - first_row:
        raise ValueError('Requested subset extends beyond the source indices')
    selection = None
    if select_15fps:
        selected, selection = _select_15fps(rows, start=start, source=source, hashes=hashes, document=document)
    else:
        selected = [(row, None, None) for row in rows]

    with TemporaryDirectory(prefix='.external-rgbd-', dir=output.parent) as staging:
        clip = Path(staging) / 'clip'
        (clip / 'frames').mkdir(parents=True)
        identity = dict(format=FORMAT, session_id=session, camera=camera,
                        scope='EXTERNAL_PREALIGNED_INSPECTION_ONLY', source_start=start, source_count=count,
                        confirmation_sha256=hashlib.sha256(document_bytes).hexdigest(),
                        sources=dict(manifest=manifest, metadata=meta_ref, frame_index=csv_ref),
                        decoder=f'OpenCV {cv2.__version__}',
                        pair_clock_column=document['clock']['pair_timestamp_column'],
                        invalid_depth_codes=document['depth']['invalid_codes'])
        if selection is not None:
            selection_path = clip / 'selection.json'
            _json(selection_path, dict(**selection, session_id=session, source_start=start, source_count=count,
                                       sources=identity['sources'], confirmation_sha256=identity['confirmation_sha256']))
            identity['selection_index'] = dict(file=selection_path.name, sha256=_sha(selection_path))
        _json(clip / 'recording.json', identity)
        previous, expected_pixel_hashes, expected_clocks = None, [], []
        with (clip / 'frames.jsonl').open('x', encoding='utf-8', newline='\n') as stream:
            for frame_index, (row, clock, decision) in enumerate(selected, 1):
                source_index = int(row['frame_index'])
                clock = clock if clock is not None else _clock_row(row, document['clock'], previous)
                color_path, depth_path = _pair_paths(source, source_index)
                color, color_ref = _verified_bytes(color_path, root, hashes)
                depth, depth_ref = _verified_bytes(depth_path, root, hashes)
                arrays = _decode(color, depth, camera, document['depth']['invalid_codes'])
                expected_pixel_hashes.append(tuple(hashlib.sha256(array.tobytes()).hexdigest() for array in arrays.values()))
                expected_clocks.append(clock)
                relative = f'frames/{frame_index:08d}.npz'
                np.savez(clip / relative, **arrays)
                record = dict(**clock, session_id=session, frame_index=frame_index, file=relative,
                              sha256=_sha(clip / relative), pairing=pairing_info(clock['sensors'], arrays),
                              source_frame_index=source_index, source_rgb=color_ref, source_depth=depth_ref,
                              source_pairing='PROVIDER_INDEXED_PAIR', preceding_event_index=None)
                if decision is not None:
                    record['selection'] = decision
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
                previous = clock
        _json(clip / 'end.json', dict(format=FORMAT, status='COMPLETED', reason='inspection_subset_packaged',
              frames=len(selected), recording_sha256=_sha(clip / 'recording.json'), frames_index_sha256=_sha(clip / 'frames.jsonl')))
        # Exhaust the current Reader, including its end-of-stream inventory/hash checks.
        inspected = inspect_source(clip)
        if inspected['packet_counts']['paired'] != len(selected):
            raise ValueError('Existing Reader did not recover all packaged pairs')
        for index, packet in enumerate(RawClipReader(clip).packets()):
            decoded_hashes = tuple(hashlib.sha256(array.tobytes()).hexdigest()
                                   for array in (packet.color_bgr, packet.depth_z16))
            if (decoded_hashes != expected_pixel_hashes[index]
                    or any(packet.record[key] != value for key, value in expected_clocks[index].items())
                    or packet.record['source_frame_index'] != int(selected[index][0]['frame_index'])
                    or packet.record.get('selection') != selected[index][2]):
                raise ValueError('Reader round-trip changed source pixels, clocks or order')
        if output.exists():
            raise ValueError('Output already exists')
        clip.rename(output)
    return inspected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Single source session directory')
    parser.add_argument('--output', type=Path, required=True, help='New inspection-only clip directory')
    parser.add_argument('--confirmation', type=Path, required=True, help='Reviewed local evidence JSON')
    parser.add_argument('--start', type=int, required=True, help='Original zero-based CSV row')
    parser.add_argument('--count', type=int, required=True, help='Approved source rows (maximum 20 in contiguous mode)')
    parser.add_argument('--select-15fps', action='store_true', help='Select first eligible pairs in session-time bins')
    parser.add_argument('--authorization', type=Path, help='Registered authorization for the external team data')
    parser.add_argument('--actor')
    args = parser.parse_args()
    try:
        inspected = convert_subset(args.source, args.output, args.confirmation, start=args.start, count=args.count,
                                   select_15fps=args.select_15fps, authorization=args.authorization, actor=args.actor)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, InvalidOperation, OverflowError,
            cv2.error, RuntimeError) as exc:
        parser.exit(1, f'Inspection conversion refused: {exc}\n')
    print(json.dumps(dict(status='PACKAGED_FOR_INSPECTION_ONLY', inspection=inspected), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
