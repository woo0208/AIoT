"""Read-only input preflight for Research B Replay. Emits a JSON report to stdout."""

import argparse
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
from zipfile import BadZipFile

import numpy as np

from e0_replay import intrinsics
from raw_rgbd_recording import SensorTrace, _sha
from raw_rgbd_replay import RawClipReader, RawSessionReader, _stored_image_counts, db3_packets


STREAMS = {'color': ('format.bgr8', np.uint8), 'depth': ('format.z16', np.uint16)}
GEOMETRY_FIELDS = ('streams', 'depth_scale_m', 'depth_to_color_extrinsics')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vector(values, size):
    return isinstance(values, list) and len(values) == size and all(map(_finite, values))


def _check_geometry(rs, camera, *, native_file):
    scale = camera['depth_scale_m']
    if not _finite(scale) or scale <= 0:
        raise ValueError('Missing or invalid depth scale in metres per unit')
    for stream, (pixel_format, _) in STREAMS.items():
        profile = camera['streams'][stream]
        width, height, fps = (profile[key] for key in ('width', 'height', 'fps'))
        if any(type(n) is not int or n <= 0 for n in (width, height, fps)):
            raise ValueError(f'Invalid {stream} dimensions or FPS')
        if not native_file and (width < 64 or width % 4 or height < 48):
            raise ValueError(f'{stream} dimensions are unsupported by NPZ SDK Replay')
        if profile['format'] != pixel_format:
            raise ValueError(f'Expected {stream} format {pixel_format}')
        calibration = profile['intrinsics']
        values = [calibration[k] for k in ('fx', 'fy', 'ppx', 'ppy')]
        if (not _vector(values, 4) or min(values[:2]) <= 0
                or not _vector(calibration['coeffs'], 5)):
            raise ValueError(f'Invalid {stream} intrinsics')
        intrinsics(rs, camera, stream)
    extrinsics = camera['depth_to_color_extrinsics']
    if not _vector(extrinsics['rotation'], 9) or not _vector(extrinsics['translation'], 3):
        raise ValueError('Invalid Depth-to-color extrinsics')


def inspect_source(source, *, expected_sha256=None, allow_incomplete=False):
    """Check every packet through the existing readers, without running inference."""
    import pyrealsense2 as rs

    source = Path(source).resolve(strict=True)
    native_file = source.is_file()
    completion, context = 'UNKNOWN', {}
    if native_file:
        if source.suffix.lower() not in ('.db3', '.bag'):
            raise ValueError('Expected RealSense DB3/BAG or an indexed NPZ directory')
        identity = {'file_sha256': _sha(source)}
        if expected_sha256 is not None and identity['file_sha256'] != expected_sha256:
            raise ValueError('Unexpected source SHA-256')
        packets, kind = db3_packets(source), 'REALSENSE_FILE'
    else:
        if expected_sha256 is not None:
            raise ValueError('--expected-sha256 is for DB3/BAG files')
        if (source / 'recording_metadata/session_manifest.json').is_file():
            reader = RawSessionReader(source, allow_incomplete=allow_incomplete)
            context = reader.identity.get('context', {})
            identity = {'session_manifest_sha256': reader.manifest_sha256}
            kind, completion = 'NPZ_SESSION', reader.identity['status']
        else:
            reader = RawClipReader(source, allow_incomplete=allow_incomplete)
            identity = dict(reader.hashes)
            kind, completion = 'NPZ_CLIP', reader.end['status'] if reader.end else 'UNFINALIZED'
        packets = reader.packets()

    camera = None
    counts, trace = Counter(), SensorTrace()
    previous_clip = last_domain = None
    last_video_ms = -1
    domains = {str(domain) for domain in rs.timestamp_domain.__members__.values()}
    max_pair_offset_ms = None
    with closing(packets):
        for packet in packets:
            counts['packets'] += 1
            if camera is None:
                camera = packet.camera
                _check_geometry(rs, camera, native_file=native_file)
            elif any(packet.camera[field] != camera[field] for field in GEOMETRY_FIELDS):
                raise ValueError('Replay calibration/profile changed within source')

            record = packet.record
            clip = record.get('clip')
            if clip != previous_clip:
                trace.previous.clear()
                previous_clip = clip
            trace.observe(record['sensors'])
            stamp, domain = record['frameset_timestamp_ms'], record['frameset_timestamp_domain']
            if not _finite(stamp) or not 0 <= stamp < 2**63 / 1000 or domain not in domains:
                counts['invalid_frameset_clock'] += 1
            elif last_domain is not None and domain != last_domain:
                counts['frameset_domain_changed'] += 1
            elif int(stamp) <= last_video_ms:
                counts['non_increasing_video_timestamp'] += 1
            else:
                last_domain, last_video_ms = domain, int(stamp)

            color, depth = packet.color_bgr, packet.depth_z16
            paired = color is not None and depth is not None
            counts['paired'] += paired
            for stream, array in (('color', color), ('depth', depth)):
                if array is None:
                    counts[f'missing_{stream}'] += 1
                    continue
                profile = camera['streams'][stream]
                shape = (profile['height'], profile['width']) + ((3,) if stream == 'color' else ())
                if array.dtype != STREAMS[stream][1] or array.shape != shape:
                    raise ValueError(f'Decoded {stream} pixels do not match the declared profile')
                sensor = record['sensors'][stream]
                if (sensor['status'] != 'MEASURED' or not _finite(sensor['timestamp_ms'])
                        or sensor['timestamp_domain'] not in domains
                        or type(sensor['number']) is not int or sensor['number'] < 0):
                    counts[f'unavailable_{stream}_clock'] += 1
            if paired:
                offset = (record.get('pairing') or {}).get('color_minus_depth_ms')
                if _finite(offset):
                    max_pair_offset_ms = max(max_pair_offset_ms or 0, abs(offset))
                else:
                    counts['pair_offset_unavailable'] += 1

    stored_counts = _stored_image_counts(source) if native_file else None
    if native_file and _sha(source) != identity['file_sha256']:
        raise ValueError('Source file changed during the read')
    if not counts['paired']:
        raise ValueError('No paired RGB/Depth frames')
    anomalies = {key: count for key, count in counts.items()
                 if key not in ('packets', 'paired') and count}
    anomalies.update({key: count for key, count in trace.counts.items()
                      if key.split('.')[1] not in ('FIRST', 'ADVANCED') and count})
    needs_review = anomalies or (not native_file and completion != 'COMPLETED')
    return dict(status='CONDITIONAL', input_checks='REVIEW_REQUIRED' if needs_review else 'PASS',
        kind=kind, source_completion_status=completion, source_hashes=identity,
        packet_counts={key: counts[key] for key in ('packets', 'paired', 'missing_color', 'missing_depth')},
        continuity_and_pairing_flags=anomalies,
        max_abs_reported_pair_offset_ms=max_pair_offset_ms, physical_sync='NOT_TESTED',
        stream_profiles={stream: camera['streams'][stream] for stream in STREAMS},
        depth_scale_m=camera['depth_scale_m'], extrinsics_fields='CHECKED',
        native_stored_image_counts=stored_counts,
        participant_code='RECORDED_UNCONFIRMED' if context.get('participant_id') else 'UNKNOWN',
        session_label='RECORDED_UNCONFIRMED' if context.get('session_label') else 'UNKNOWN',
        ground_truth='HUMAN_REVIEW_REQUIRED', authorization='HUMAN_REVIEW_REQUIRED',
        inference_replay='NOT_TESTED')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--expected-sha256', help='Provider SHA-256 for a DB3/BAG file')
    parser.add_argument('--allow-incomplete', action='store_true', help='Inspect a partial capture for diagnostics')
    args = parser.parse_args(argv)
    try:
        result = inspect_source(args.input, expected_sha256=args.expected_sha256,
                                allow_incomplete=args.allow_incomplete)
    except (AttributeError, BadZipFile, ImportError, KeyError, OSError, OverflowError, RuntimeError,
            TypeError, ValueError, sqlite3.Error) as exc:
        result = dict(status='FAIL', error_type=type(exc).__name__, reason=str(exc))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return int(result['status'] == 'FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
