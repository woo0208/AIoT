"""Offline join of reviewed motion starts and causal detector outputs on one Clip clock."""

import argparse
import json
from pathlib import Path
from statistics import median

from raw_rgbd_replay import RawClipReader


ANNOTATION_FORMAT = 'research-b-reviewed-motion/1'
DETECTOR_FORMAT = 'research-b-motion-detector-events/1'


def _reference(reference, index):
    frame = reference.get('frame_index')
    row = index.get(frame) if type(frame) is int else None
    if (row is None or reference.get('frame_sha256') != row['sha256']
            or reference.get('timestamp_ms') != row['frameset_timestamp_ms']):
        raise ValueError('Motion reference does not match the original frame/hash/clock')
    return frame, row['frameset_timestamp_ms']


def evaluate_delays(annotations, detector_documents, *, source_index_sha256, index):
    """Use a confirmed start and a reviewed exclusive search end for every event."""
    if (annotations.get('format') != ANNOTATION_FORMAT
            or annotations.get('source_index_sha256') != source_index_sha256):
        raise ValueError('Motion annotation format/source index mismatch')
    transitions = []
    previous_end = None
    ids = set()
    for item in annotations['transitions']:
        if (item.get('status') != 'MANUAL_REVIEW_CONFIRMED'
                or not item.get('reviewer') or not item.get('reviewed_at')):
            raise ValueError('Motion onset requires a documented human approval')
        transition_id = item['id']
        if not transition_id or transition_id in ids:
            raise ValueError('Motion transition IDs must be unique')
        ids.add(transition_id)
        start, onset_ms = _reference(item['start'], index)
        end, end_ms = _reference(item['search_end'], index)
        if end <= start or end_ms <= onset_ms or (previous_end is not None and start < previous_end):
            raise ValueError('Motion search intervals must be ordered and disjoint')
        previous_end = end
        transitions.append((transition_id, start, end, onset_ms))
    if not transitions or len(detector_documents) < 2:
        raise ValueError('Expected verified transitions and at least two method outputs')
    detector_id = detector_documents[0].get('detector_id')
    if not detector_id:
        raise ValueError('Specify the same versioned detector for all methods')
    methods = {}
    for document in detector_documents:
        method = document.get('method')
        if (document.get('format') != DETECTOR_FORMAT or document.get('detector_id') != detector_id
                or document.get('source_index_sha256') != source_index_sha256 or not method
                or method in methods):
            raise ValueError('Incompatible detector, method identity or source clock')
        events = [_reference(event, index) for event in document['events']]
        if any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(events, events[1:])):
            raise ValueError('Detector outputs must be strictly ordered causal reporting inputs')
        matched = set()
        delays = []
        for transition_id, start, end, onset_ms in transitions:
            first = next(((frame, stamp) for frame, stamp in events if start <= frame < end), None)
            if first is None:
                delays.append(dict(transition=transition_id, status='MISSED', delay_ms=None))
                continue
            frame, timestamp = first
            matched.add(frame)
            delays.append(dict(transition=transition_id, status='DETECTED', detection_frame=frame,
                               delay_frames=frame-start, delay_ms=timestamp-onset_ms))
        numeric = [d['delay_ms'] for d in delays if d['delay_ms'] is not None]
        methods[method] = dict(transitions=delays, detected=len(numeric), expected=len(transitions),
            median_detected_only_ms=median(numeric) if numeric else None,
            unmatched_event_frames=[frame for frame, _ in events if frame not in matched])
    return dict(detector_id=detector_id, source_index_sha256=source_index_sha256,
                clock='original frameset_timestamp_ms; event time is when the detector could report',
                methods=methods)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--annotations', required=True, type=Path)
    parser.add_argument('--detections', required=True, nargs='+', type=Path)
    args = parser.parse_args(argv)
    reader = RawClipReader(args.source)
    with (reader.directory/'frames.jsonl').open(encoding='utf-8') as stream:
        index = {row['frame_index']: row for row in map(json.loads, stream)}
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    result = evaluate_delays(read(args.annotations), [read(p) for p in args.detections],
                              source_index_sha256=reader.hashes['frames.jsonl'], index=index)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
