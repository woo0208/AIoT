"""Read-only Research B numeric report; never estimates skipped compute from CSV.

Optional independently confirmed labels must bind to this exact summary hash.
No posture is inferred from the operator's sequence, features or predictions.
"""
import argparse
import hashlib
import json
from pathlib import Path

from sklearn.metrics import accuracy_score, precision_recall_fscore_support


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classification(run, labels_path=None):
    if labels_path is None:
        return dict(status='NOT_MEASURED', reason='independently confirmed labels unavailable',
                    accuracy=None, macro_f1=None, p0_recall=None, p1_recall=None)
    labels = json.loads(Path(labels_path).read_text(encoding='utf-8'))
    if (labels.get('summary_sha256') != sha256(run / 'summary.json')
            or labels.get('source') != 'independent_observation'):
        raise ValueError('Labels require exact run binding and independent observation')
    segments = [json.loads(line) for line in (run / 'segments.jsonl').read_text(encoding='utf-8').splitlines()]
    entries = labels['segments']
    by_index = {}
    for row in entries:
        if (type(row.get('segment_index')) is not int or type(row.get('label')) is not int
                or row['label'] not in range(6) or row.get('confirmed') is not True
                or row['segment_index'] in by_index):
            raise ValueError('Duplicate, invalid or unconfirmed label')
        by_index[row['segment_index']] = row['label']
    if set(by_index) != {s['segment_index'] for s in segments}:
        raise ValueError('Labels must cover every segment, including unsuccessful holds')
    predicted = [s for s in segments if s.get('prediction_success') is True]
    if any(type(s.get('prediction')) is not int or s['prediction'] not in range(6) for s in predicted):
        raise ValueError('Invalid saved prediction')
    support = [sum(by_index[s['segment_index']] == k for s in predicted) for k in range(6)]
    measured = None
    if predicted:
        y = [by_index[s['segment_index']] for s in predicted]
        p = [s['prediction'] for s in predicted]
        # Same fixed-six sklearn definitions/percent units as research A;
        # no fitting, model selection, fold or original evaluation changes.
        _, recall, f1, _ = precision_recall_fscore_support(y, p, labels=range(6), zero_division=0)
        measured = dict(accuracy=100*float(accuracy_score(y, p)),
                        macro_f1=100*float(f1.mean()),
                        per_class=[dict(recall=100*float(r)) for r in recall])
    return dict(status='COMPLETE' if all(support) else 'INCOMPLETE',
        scope='NON_FORMAL_ENGINEERING; no LOSO/training or formal policy change',
        labels_sha256=sha256(labels_path), total_segments=len(segments),
        scored_segments=len(predicted), unscored_segments=len(segments)-len(predicted),
        prediction_coverage=len(predicted)/len(segments) if segments else None,
        support=support, unit='percent',
        accuracy=measured['accuracy'] if measured else None,
        macro_f1=measured['macro_f1'] if all(support) else None,
        p0_recall=measured['per_class'][0]['recall'] if support[0] else None,
        p1_recall=measured['per_class'][1]['recall'] if support[1] else None,
        diagnostic_fixed6=measured)


def report(run, labels_path=None):
    run = Path(run)
    summary = json.loads((run / 'summary.json').read_text(encoding='utf-8'))
    policy = summary['environment']['research_b']
    timing = json.loads((run / 'timing/diagnostics.json').read_text(encoding='utf-8'))
    stages = {s['name']: s for s in timing['stage_milliseconds']}
    names = ('receive.wait', 'receive.align', 'input.convert', 'mediapipe.pose', 'mediapipe.face',
             'depth_geometry', 'fs3.feature_select', 'fs3.aggregate', 'fs3.scale', 'fs3.svm',
             'ui.tk_poll', 'ui.render_submit', 'ui.key_wait', 'io.raw_rgbd', 'loop.total',
             'latency.receive_to_frame_complete', 'latency.loop_start_to_frame_complete',
             'research_b.full.receive_to_complete', 'research_b.idle.receive_to_complete',
             'research_b.full.demand.receive_to_complete', 'research_b.full.idle.receive_to_complete')
    seconds = summary['stream_seconds']
    count = policy['counts']
    fps = lambda n: n/seconds if seconds and seconds > 0 else None
    return dict(scope=summary['scope'], status=summary['status'], variant=policy['variant'],
        summary_sha256=sha256(run / 'summary.json'), model_binding=summary['model_binding'],
        performance_improvement='UNVERIFIED', stream_seconds=seconds,
        received_fps=fps(summary['received_frames']),
        fully_processed_fps=fps(count.get('full_completed', 0)),
        idle_preview_fps=fps(count.get('idle_completed', 0)),
        completed_delivery_fps=fps(count.get('full_completed', 0)+count.get('idle_completed', 0)),
        counts=count, transitions=policy['transitions'],
        raw_recording=summary['environment'].get('raw_recording', dict(status='NOT_CONFIGURED')),
        frame_status_counts=summary['frame_status_counts'],
        loop_status_counts=summary['loop_status_counts'],
        sensor_missing_rate='NOT_MEASURED',
        host_observed_number_gaps=policy['raw_frame_number_gaps'],
        stages_ms={name: stages.get(name, dict(count=0, p50=None, p95=None, p99=None,
                                              status='NOT_CALLED')) for name in names},
        resources=summary['resources'], classification=classification(run, labels_path),
        notes=['Stage count includes attempted calls whose timing context exited with an exception.',
               'Idle delivery is not geometry throughput. Compare demand-only and all-loop latencies separately.',
               'Match PC/profile/model hashes/mode/UI/hold and idle schedule; use new E0 control.',
               'Do not sum percentiles, derive compute saving from FPS capped at 15, or omit failed runs.',
               'Unpaired sessions cannot establish equal accuracy or paired prediction agreement.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--labels', type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(report(args.run, args.labels), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
