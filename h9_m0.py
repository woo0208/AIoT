"""Development-only H9 M0 artifact and whole-segment CSV replay inference.

Reuses rf_experiment.Forest/Tree without changing fitting or prediction logic,
the existing tree serializer and H9 sequential replay/aggregation. The F1-5
three-class artifact loader is not changed or used for H9 model validation.
Only the two explicitly authorized P01/P02 CSV byte identities can be trained.
All outputs are new files. No accuracy metrics, LOSO run, tuning, camera,
sliding windows or formal schema/collection authorization are added.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hmac
import json
import math
from pathlib import Path
import platform
import subprocess

import numpy as np

import f1_demo_rf as artifact_helpers
import f1_sample_aggregator as aggregation
import h6_offline as offline
import h9_csv_replay as replay
import rf_experiment as rf
import train_f1_demo_rf as serializer


ARTIFACT_FORMAT = 'h9-m0-development-json/1.0.0'  # engineering format, not a scientific schema
PURPOSE = 'development-only H9 M0 connection; no performance claim'
FEATURE_ORDER = tuple(aggregation.H9_FEATURE_NAMES)
FEATURE_UNITS = ('1', '1', 'deg', '1', '1', 'm', 'm', 'm', '1')
CLASS_ORDER = tuple(rf.LAB5)
CONFIG = dict(implementation='rf_experiment.Forest/unweighted', trees=500,
              max_features=2, seed=0, criterion='gini', bootstrap=True)
AUTHORIZED_INPUTS = {
    '1d8f0c7e40b87f750bb4a351f52ed55b083a1c37e777a2e9088f54111ded3122': 'P01',
    '6bbad505e9333e4029fe1be155e73ce745c9709077b57fda65eb49e3fc8b9f2e': 'P02',
}


class ArtifactError(ValueError):
    pass


def _digest(value):
    # The existing helper canonicalizes finite JSON and hashes its exact content.
    try:
        return artifact_helpers.artifact_integrity_sha256(value)
    except ValueError as exc:
        raise ArtifactError(str(exc)) from exc


def _write_new(path, value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(encoded)


def _new_paths(*paths):
    resolved = [Path(p).resolve() for p in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError('output paths must be distinct')
    for p in resolved:
        if p.exists() or p.is_symlink():
            raise FileExistsError(f'refusing to overwrite output: {p}')
        if not p.parent.is_dir():
            raise FileNotFoundError(f'output directory does not exist: {p.parent}')
    return resolved


def _code_identities():
    return [replay._identity(p) for p in (
        __file__, rf.__file__, aggregation.__file__, offline.__file__, replay.__file__,
        serializer.__file__, artifact_helpers.__file__)]


def _matrix(X):
    X = np.asarray(X)
    if X.ndim != 2 or X.shape[1] != 9 or X.dtype.kind not in 'fiu':
        raise ValueError('H9 input must be a numeric matrix in exact nine-feature order')
    X = X.astype(float, copy=False)
    if not np.isfinite(X).all():
        raise ValueError('H9 model input must be finite; no imputation')
    return X


def _validate_tree(tree):
    names = {'feature', 'threshold', 'left', 'right', 'probability'}
    if not isinstance(tree, dict) or set(tree) != names:
        raise ArtifactError('invalid tree fields')
    if any(not isinstance(tree[n], list) for n in names):
        raise ArtifactError('tree arrays must be lists')
    n = len(tree['feature'])
    if not n or any(len(tree[k]) != n for k in names):
        raise ArtifactError('unaligned or empty tree arrays')
    parents = [0]*n
    for node in range(n):
        f, left, right = (tree[k][node] for k in ('feature', 'left', 'right'))
        if any(type(x) is not int for x in (f, left, right)):
            raise ArtifactError('tree indices must be integers')
        threshold = tree['threshold'][node]
        probabilities = tree['probability'][node]
        if (type(threshold) not in (int, float) or not math.isfinite(threshold)
                or not isinstance(probabilities, list) or len(probabilities) != 5
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                       for v in probabilities)
                or abs(math.fsum(probabilities)-1) > 1e-12):
            raise ArtifactError('invalid finite threshold or five-class probability vector')
        if f == -1:
            if left != -1 or right != -1:
                raise ArtifactError('leaf has children')
        elif not (0 <= f < 9 and node < left < n and node < right < n and left != right):
            # The reused RF serializer emits preorder node arrays. This also excludes cycles.
            raise ArtifactError('invalid preorder tree split')
        else:
            parents[left] += 1
            parents[right] += 1
    if parents[0] != 0 or any(p != 1 for p in parents[1:]):
        raise ArtifactError('tree has shared or unreachable nodes')


def _signed_document(forest, training):
    if (forest.K, forest.T, forest.mf, forest.seed, forest.sw) != (5, 500, 2, 0, None):
        raise ValueError('expected fixed unweighted H9 M0 configuration')
    model = serializer._serialize_forest(forest)
    metadata = dict(purpose=PURPOSE, scope='primary5', feature_order=list(FEATURE_ORDER),
                    feature_units=list(FEATURE_UNITS), class_order=list(CLASS_ORDER),
                    aggregation_spec=aggregation.H_AGGREGATION_SPEC_ID,
                    configuration=dict(CONFIG), training=training, code=_code_identities(),
                    model_sha256=_digest(model), feature_order_sha256=_digest(list(FEATURE_ORDER)),
                    environment=dict(python=platform.python_version(), numpy=np.__version__))
    signed = dict(artifact_format=ARTIFACT_FORMAT, payload=dict(metadata=metadata, model=model))
    return dict(**signed, integrity=dict(algorithm='sha256', sha256=_digest(signed)))


class H9M0Model:
    """Validated arrays reconstructed into the existing RF inference implementation."""

    def __init__(self, forest, metadata, integrity_sha256):
        self.forest = forest
        self.metadata = metadata
        self.integrity_sha256 = integrity_sha256

    def predict(self, X, *, feature_order=FEATURE_ORDER):
        if tuple(feature_order) != FEATURE_ORDER:
            raise ValueError('H9 feature order mismatch')
        return self.forest.predict(_matrix(X))

    def predict_sample(self, sample):
        if not isinstance(sample, aggregation.HSampleResult):
            raise ValueError('expected original H9 HSampleResult')
        if sample.label not in CLASS_ORDER:
            raise ValueError('sample outside primary5; no inference')
        if (sample.aggregation_spec != aggregation.H_AGGREGATION_SPEC_ID
                or tuple(sample.features) != FEATURE_ORDER):
            raise ValueError('H9 aggregation or feature order mismatch')
        return int(self.predict([sample.ordered_values('H9')])[0])


def model_from_document(document):
    if not isinstance(document, dict) or set(document) != {'artifact_format', 'payload', 'integrity'}:
        raise ArtifactError('invalid artifact envelope')
    signed = {k: document[k] for k in ('artifact_format', 'payload')}
    integrity = document['integrity']
    if (not isinstance(integrity, dict) or set(integrity) != {'algorithm', 'sha256'}
            or integrity['algorithm'] != 'sha256' or not isinstance(integrity['sha256'], str)
            or not hmac.compare_digest(integrity['sha256'], _digest(signed))):
        raise ArtifactError('artifact integrity mismatch')
    if document['artifact_format'] != ARTIFACT_FORMAT:
        raise ArtifactError('unsupported H9 development artifact format')
    payload = document['payload']
    if not isinstance(payload, dict) or set(payload) != {'metadata', 'model'}:
        raise ArtifactError('invalid artifact payload')
    metadata, model = payload['metadata'], payload['model']
    if not isinstance(metadata, dict) or not isinstance(model, dict):
        raise ArtifactError('invalid metadata or model')
    expected = dict(purpose=PURPOSE, scope='primary5', feature_order=list(FEATURE_ORDER),
                    feature_units=list(FEATURE_UNITS), class_order=list(CLASS_ORDER),
                    aggregation_spec=aggregation.H_AGGREGATION_SPEC_ID)
    if any(metadata.get(k) != value for k, value in expected.items()):
        raise ArtifactError('H9 feature/class/aggregation/development contract mismatch')
    config = metadata.get('configuration')
    if (not isinstance(config, dict) or config != CONFIG
            or any(type(config.get(k)) is not int for k in ('trees', 'max_features', 'seed'))
            or config.get('bootstrap') is not True):
        raise ArtifactError('M0 configuration mismatch')
    training = metadata.get('training')
    if (not isinstance(training, dict) or training.get('dataset_role') not in ('pilot', 'synthetic-structural')
            or 'data' not in training or training.get('input_matrix_sha256') != _digest(training['data'])):
        raise ArtifactError('missing or inconsistent development input provenance')
    code = metadata.get('code')
    if (not isinstance(code, list) or not any(isinstance(c, dict)
            and Path(c.get('path', '')).name == 'rf_experiment.py'
            and c.get('sha256') == replay._identity(rf.__file__)['sha256'] for c in code)):
        raise ArtifactError('RF implementation hash mismatch')
    if (set(model) != {'trees'} or not isinstance(model['trees'], list) or len(model['trees']) != 500
            or metadata.get('model_sha256') != _digest(model)
            or metadata.get('feature_order_sha256') != _digest(list(FEATURE_ORDER))):
        raise ArtifactError('tree count or model/feature hash mismatch')
    forest = rf.Forest(5, 500, 2, None, 0)
    forest.trees = []
    for arrays in model['trees']:
        _validate_tree(arrays)
        tree = rf.Tree(5, 2, np.ones(9), None)
        tree.feat = np.asarray(arrays['feature'], dtype=int)
        tree.thr = np.asarray(arrays['threshold'], dtype=float)
        tree.left = np.asarray(arrays['left'], dtype=int)
        tree.right = np.asarray(arrays['right'], dtype=int)
        tree.value = np.asarray(arrays['probability'], dtype=float)
        forest.trees.append(tree)
    return H9M0Model(forest, metadata, integrity['sha256'])


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError('duplicate JSON key')
        result[key] = value
    return result


def load_model(path):
    with Path(path).open(encoding='utf-8') as stream:
        try:
            document = json.load(stream, object_pairs_hook=_unique_pairs)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactError('invalid model JSON') from exc
    return model_from_document(document)


def build_development_model(paths, model_output, report_output):
    """One fixed M0 fit on authorized pilot bytes; serialization checks, no scoring."""
    model_path, report_path = _new_paths(model_output, report_output)
    inputs = [replay._identity(p) for p in paths]
    if len(inputs) != 2 or {i['sha256'] for i in inputs} != set(AUTHORIZED_INPUTS):
        raise ValueError('development training restricted to the two authorized P01/P02 inputs')
    code = _code_identities()
    comparison = replay.validate_replay([i['path'] for i in inputs])
    if comparison['status'] != 'PASS':
        raise ValueError('CSV replay aggregation mismatch before training')
    samples = offline.load_labeled_probe_h_samples([i['path'] for i in inputs])
    selected = [s for s in samples if s.label in CLASS_ORDER and s.eligible]
    counts = Counter((s.subject, s.label) for s in selected)
    if (len(selected) != 20 or counts != Counter({(subject, label): 2
            for subject in ('P01', 'P02') for label in CLASS_ORDER})):
        raise ValueError('expected the same 20 eligible primary5 pilot segments')
    X = _matrix([s.ordered_values('H9') for s in selected])
    y = np.array([CLASS_ORDER.index(s.label) for s in selected])
    data = dict(feature_order=list(FEATURE_ORDER), class_order=list(CLASS_ORDER),
                sample_keys=[list(s.sample_key) for s in selected],
                participants=[s.subject for s in selected], matrix=X.tolist(), labels=y.tolist())
    training = dict(dataset_role='pilot', purpose=PURPOSE, inputs=inputs, sample_count=20,
                    unit='whole posture segment', data=data, input_matrix_sha256=_digest(data),
                    excluded=[dict(sample_key=s.sample_key, label=s.label,
                                   reason='outside_primary5' if s.label not in CLASS_ORDER else 'ineligible')
                              for s in samples if s not in selected],
                    authorization=dict(current_user_request='H9 live connection stage 2: conditional development-only M0 build',
                                       decision='DATA-002 retains pilot role; not standalone formal authorization',
                                       scope='Research Master section 9.1 code development; no formal/external evaluation'),
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    replay._verify_files([*inputs, *code])
    forest = rf.Forest(5, n_trees=500, max_features=2, split_w=None, seed=0).fit(X, y)
    document = _signed_document(forest, training)
    before = forest.predict(X)
    before_probabilities = rf._forest_probabilities(forest, X)
    in_memory = model_from_document(document)
    np.testing.assert_array_equal(in_memory.predict(X), before)
    np.testing.assert_array_equal(rf._forest_probabilities(in_memory.forest, X), before_probabilities)
    replay._verify_files([*inputs, *code])
    _write_new(model_path, document)
    model_identity = replay._identity(model_path)
    loaded = load_model(model_path)
    after = loaded.predict(X)
    after_probabilities = rf._forest_probabilities(loaded.forest, X)
    np.testing.assert_array_equal(after, before)
    np.testing.assert_array_equal(after_probabilities, before_probabilities)
    replay._verify_files([*inputs, *code, model_identity])
    report = dict(kind='h9-m0-development-build-and-serialization-check', purpose=PURPOSE,
                  artifact=model_identity, model_sha256=document['payload']['metadata']['model_sha256'],
                  artifact_integrity_sha256=document['integrity']['sha256'],
                  feature_order=FEATURE_ORDER, class_order=CLASS_ORDER, configuration=CONFIG,
                  input_matrix_sha256=training['input_matrix_sha256'], inputs=inputs, code=code,
                  selected_sample_keys=data['sample_keys'], excluded=training['excluded'],
                  serialization_check=dict(inputs=20, predictions_before=before.tolist(), predictions_after=after.tolist(),
                                           exact_predictions_equal=True, exact_probabilities_equal=True,
                                           max_absolute_probability_difference=float(np.max(np.abs(after_probabilities-before_probabilities)))),
                  aggregation_check=dict(segments=comparison['segment_count'], mismatches=0),
                  note='All 20 inputs used for development training; checks are serialization consistency, not accuracy or LOSO.')
    _write_new(report_path, report)
    return report


def replay_inference(paths, model_path):
    """Predict only eligible primary5 completions from the stage-1 stream buffer."""
    model_identity = replay._identity(model_path)
    model = load_model(model_path)
    comparison = replay.validate_replay(paths)
    if comparison['status'] != 'PASS':
        raise ValueError('CSV replay aggregation mismatch before inference')
    inputs = [{k: s[k] for k in ('path', 'sha256', 'size_bytes')} for s in comparison['sources']]
    code = _code_identities()
    results = []
    def completed(result):
        sample = result.sample
        row = dict(sample_key=sample.sample_key, source_label=sample.label,
                   emitted_on=result.emitted_on, first_frame_index=result.frames[0].frame_index,
                   last_frame_index=result.frames[-1].frame_index,
                   first_device_timestamp_ms=result.frames[0].device_timestamp_ms,
                   last_device_timestamp_ms=result.frames[-1].device_timestamp_ms,
                   frame_count=sample.n_frames, common_valid_count=sample.common_valid_count,
                   common_coverage=sample.common_coverage, prediction_index=None, prediction_label=None)
        if sample.label not in CLASS_ORDER:
            row['status'] = 'outside_primary5'
        elif not sample.eligible:
            row.update(status='ineligible', reasons=sample.eligibility_reasons)
        else:
            index = model.predict_sample(sample)
            row.update(status='predicted', prediction_index=index, prediction_label=CLASS_ORDER[index],
                       features=list(sample.ordered_values('H9')))
        results.append(row)
    for source in inputs:
        buffer = replay.H9SequentialBuffer()
        for frame in replay.iter_probe_frames(source['path']):
            result = buffer.push(frame)
            if result is not None:
                completed(result)
        result = buffer.finish()
        if result is not None:
            completed(result)
    replay._verify_files([model_identity, *inputs, *code])
    return dict(kind='h9-m0-development-whole-segment-replay-inference', purpose=PURPOSE,
                artifact=model_identity, model_sha256=model.metadata['model_sha256'],
                training_dataset_role=model.metadata['training']['dataset_role'],
                feature_order=FEATURE_ORDER, class_order=CLASS_ORDER, configuration=CONFIG,
                sources=inputs, code=code, segments=results,
                status_counts=dict(Counter(r['status'] for r in results)),
                aggregation_check=dict(segments=comparison['segment_count'], mismatches=0),
                note='Development replay may reuse training inputs. Predictions are not an accuracy/generalization result.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build', help='one authorized development M0 fit; no scores')
    build.add_argument('--probe-csv', nargs='+', required=True)
    build.add_argument('--model-output', required=True)
    build.add_argument('--report-output', required=True)
    run = sub.add_parser('replay', help='load model and infer primary5 only; no fit')
    run.add_argument('--probe-csv', nargs='+', required=True)
    run.add_argument('--model', required=True)
    run.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if args.command == 'build':
        result = build_development_model(args.probe_csv, args.model_output, args.report_output)
        print('BUILD PASS: 20 development segments; exact predictions/probabilities after reload; no accuracy scoring')
    else:
        _new_paths(args.output)
        result = replay_inference(args.probe_csv, args.model)
        _write_new(args.output, result)
        print('REPLAY:', result['status_counts'], '; no accuracy scoring')
    print('MODEL_SHA256', result['model_sha256'])
    print('ARTIFACT_FILE_SHA256', result['artifact']['sha256'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
