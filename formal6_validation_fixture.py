"""Synthetic-only 2-person train / 4-person held-out evaluation rehearsal.

No real-data loader, camera operation, approval override, or primary5 change.
"""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import warnings

# Imports of existing reference code must never create files beside that code.
sys.dont_write_bytecode = True
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'analysis/formal6_synthetic_validation'
REFERENCE = ROOT / 'formal6_reference.py'
spec = importlib.util.spec_from_file_location('formal6_reference_baseline', REFERENCE)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

SEEDS = ev.SEEDS
FEATURES = tuple(ev.agg.H9_FEATURE_NAMES[:8])  # Existing B0 = feature comparison B.
CLASSES = tuple(ev.h6.LAB6)
SUBJECTS = tuple(f'SYN-F{i:02d}' for i in range(1, 7))
KIND = 'SYNTHETIC_STRUCTURAL_ONLY_NOT_RESEARCH_PERFORMANCE'
GENERATOR = 'formal6-fixed-fixture-v1'
GENERATOR_SEED = 20261030
STEPS = (1, 2, 6, 7, 8, 4)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def synthetic_fixture():
    """Arbitrary aggregated eight-column values, not simulated human geometry.

    Five full-series repeats per person; S1 rounds 1..3, S2 rounds 4..5.
    Source intervals are artificial identity tokens, not captured raw frames.
    """
    rng = np.random.default_rng(GENERATOR_SEED)
    centers = rng.normal(0, 1, (6, 8))
    people, rows = [], []
    for i, subject in enumerate(SUBJECTS):
        split = 'train' if i < 2 else 'heldout'
        people.append(dict(subject=subject, person_id=f'synthetic-person-{i+1}', split=split))
        offset = rng.normal(0, .25, 8)
        for repeat in range(1, 6):
            session = 'S1' if repeat <= 3 else 'S2'
            # Retain target order of SEQ_FULL without auxiliary return upright.
            for k in (0, 1, 5, 2, 3, 4):
                rows.append(dict(subject=subject, session=session, round=str(repeat),
                    label=CLASSES[k], segment_id=f'{subject}-R{repeat}-P{k}',
                    source_id=f'synthetic-source-{subject}-R{repeat}',
                    frame_start=STEPS[k]*100, frame_stop=STEPS[k]*100+49,
                    values=(centers[k]+offset+rng.normal(0, .75, 8)).tolist()))
    return dict(kind=KIND, generator=GENERATOR, generator_seed=GENERATOR_SEED,
                class_order=list(CLASSES), feature_order=list(FEATURES),
                train_subjects=list(SUBJECTS[:2]), heldout_subjects=list(SUBJECTS[2:]),
                participants=people, segments=rows)


def validate(data):
    """Complete-fixture structural contract only; no formal missing-data policy."""
    required = set(synthetic_fixture())
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError('missing or unexpected input fields')
    if (data['kind'], data['generator'], data['generator_seed']) != (KIND, GENERATOR, GENERATOR_SEED):
        raise ValueError('only the fixed synthetic generator is allowed')
    if data['class_order'] != list(CLASSES) or data['feature_order'] != list(FEATURES):
        raise ValueError('class/feature order mismatch')
    train, heldout = data['train_subjects'], data['heldout_subjects']
    if (not isinstance(train, list) or not isinstance(heldout, list)
            or any(not isinstance(s, str) or not s.strip() for s in train+heldout)):
        raise ValueError('missing participant split')
    if len(train) != len(set(train)) or len(heldout) != len(set(heldout)):
        raise ValueError('duplicate participant in split')
    if set(train) & set(heldout):
        raise ValueError('train/heldout participant leakage')
    if len(train) != 2 or len(heldout) != 4:
        raise ValueError('expected two train and four heldout participants')
    people, identities = {}, set()
    if not isinstance(data['participants'], list):
        raise ValueError('missing participants')
    for person in data['participants']:
        if not isinstance(person, dict) or set(person) != {'subject', 'person_id', 'split'}:
            raise ValueError('missing participant identity fields')
        s, identity, split = person['subject'], person['person_id'], person['split']
        if any(not isinstance(v, str) or not v.strip() for v in (s, identity, split)):
            raise ValueError('missing participant identity')
        if s in people or identity in identities:
            raise ValueError('duplicate participant or same-person alias')
        expected = 'train' if s in train else 'heldout' if s in heldout else None
        if split != expected:
            raise ValueError('participant split mismatch')
        people[s] = person
        identities.add(identity)
    if set(people) != set(train+heldout):
        raise ValueError('missing participant registration')
    if not isinstance(data['segments'], list):
        raise ValueError('missing segments')
    slots, segments, sources = set(), set(), {}
    fields = {'subject', 'session', 'round', 'label', 'segment_id', 'source_id',
              'frame_start', 'frame_stop', 'values'}
    for row in data['segments']:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError('missing or unexpected segment fields')
        if any(not isinstance(row[k], str) or not row[k].strip()
               for k in ('subject', 'session', 'round', 'label', 'segment_id', 'source_id')):
            raise ValueError('missing segment identity')
        s, repeat, label = row['subject'], row['round'], row['label']
        if s not in people or repeat not in ('1', '2', '3', '4', '5') or label not in CLASSES:
            raise ValueError('unregistered subject, round or class')
        if row['session'] != ('S1' if int(repeat) <= 3 else 'S2'):
            raise ValueError('session must follow rounds 1..3 + 4..5')
        slot = (s, repeat, label)
        if row['segment_id'] in segments or slot in slots:
            raise ValueError('duplicate segment or participant/round/class slot')
        segments.add(row['segment_id'])
        slots.add(slot)
        start, stop = row['frame_start'], row['frame_stop']
        if type(start) is not int or type(stop) is not int or start < 0 or stop < start:
            raise ValueError('invalid source frame interval')
        owner = (people[s]['person_id'], row['session'], repeat)
        source = sources.setdefault(row['source_id'], dict(owner=owner, intervals=[]))
        if source['owner'] != owner:
            raise ValueError('source reused across participants/rounds: input leakage')
        if any(start <= b and a <= stop for a, b in source['intervals']):
            raise ValueError('overlapping source frames / duplicate segment')
        source['intervals'].append((start, stop))
        values = row['values']
        if (not isinstance(values, list) or len(values) != len(FEATURES)
                or any(type(v) not in (int, float) for v in values)
                or not np.isfinite(values).all()):
            raise ValueError('missing, malformed or non-finite feature input; no imputation')
    expected_slots = {(s, str(r), label) for s in people for r in range(1, 6) for label in CLASSES}
    if slots != expected_slots:
        raise ValueError('missing target segments: expected six postures x five repeats per person')
    counts = Counter('train' if row['subject'] in train else 'heldout' for row in data['segments'])
    if counts != {'train': 60, 'heldout': 120}:
        raise ValueError('expected 60 train / 120 heldout segments')
    return dict(status='PASS', train_segments=60, heldout_segments=120,
                participant_count=6, independent_heldout_participants=4,
                duplicate_participants=0, duplicate_segments=0, input_leakage=0,
                missing_inputs=0, complete_class_support=True)


def _fit_predict(x_train, y_train, x_heldout, seed):
    # Same StandardScaler class and unchanged B0 model factory as the reference.
    scaler = ev.StandardScaler().fit(x_train)
    model = ev.make_model('Logistic-Regression', seed)
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        model.fit(scaler.transform(x_train), y_train)
    prediction = model.predict(scaler.transform(x_heldout))
    if int(scaler.n_samples_seen_) != len(x_train):
        raise RuntimeError('scaler training support mismatch')
    np.testing.assert_allclose(scaler.mean_, x_train.mean(0), rtol=0, atol=1e-15)
    return prediction, dict(n_samples_seen=int(scaler.n_samples_seen_),
        mean=scaler.mean_.tolist(), var=scaler.var_.tolist(), scale=scaler.scale_.tolist()), model


def evaluate(data, mode='synthetic'):
    # Check before validation or model fitting. No flag can authorize formal use.
    if mode != 'synthetic':
        raise ValueError('real/formal data execution is blocked pending freeze and approval')
    checks = validate(data)
    # A "synthetic" marker alone cannot admit external observations through this API.
    if data != synthetic_fixture():
        raise ValueError('only the internally generated fixed synthetic fixture may be evaluated')
    rows = data['segments']
    x = np.asarray([r['values'] for r in rows], dtype=float)
    y = np.asarray([CLASSES.index(r['label']) for r in rows])
    train = np.array([r['subject'] in data['train_subjects'] for r in rows])
    test = ~train
    test_rows = [r for r, keep in zip(rows, test) if keep]
    truth = y[test]
    predictions, fits = [], []
    with threadpool_limits(limits=1):
        for seed in SEEDS:
            pred, scaler, model = _fit_predict(x[train], y[train], x[test], seed)
            predictions.append(pred)
            fits.append(dict(seed=seed, scaler=scaler, model_parameters=model.get_params(),
                             n_iter=model.n_iter_.tolist()))
    predictions = np.asarray(predictions)
    subjects = np.asarray([r['subject'] for r in test_rows])
    sessions = np.asarray([r['session'] for r in test_rows])
    masks = {'pooled': np.ones(len(truth), dtype=bool)}
    masks.update({s: subjects == s for s in data['heldout_subjects']})
    masks.update({s: sessions == s for s in ('S1', 'S2')})
    masks.update({f'{s}/{t}': (subjects == s) & (sessions == t)
                  for s in data['heldout_subjects'] for t in ('S1', 'S2')})
    scopes = {scope: ev.summary(truth, predictions, mask) for scope, mask in masks.items()}
    participant_f1 = [float(np.mean([scopes[s]['per_seed'][i]['macro_f1']
                      for s in data['heldout_subjects']])) for i in range(len(SEEDS))]
    return dict(measurement_status=KIND, class_role='six-class candidate; primary5 unchanged',
        configuration_id='B0-synthetic-2to4', class_order=list(CLASSES), feature_order=list(FEATURES),
        seeds=list(SEEDS), generator_seed=GENERATOR_SEED, checks=checks, fit_count=len(SEEDS),
        train_subjects=data['train_subjects'], heldout_subjects=data['heldout_subjects'],
        train_indices=np.flatnonzero(train).tolist(), heldout_indices=np.flatnonzero(test).tolist(),
        evaluated_segment_ids=[r['segment_id'] for r in test_rows], truth=truth.tolist(),
        predictions_by_seed=predictions.tolist(), fits=fits, scopes=scopes,
        participant_mean_macro_f1=dict(per_seed=participant_f1, mean=float(np.mean(participant_f1)),
                                      sd_ddof0=float(np.std(participant_f1))),
        real_data_execution='BLOCKED', actual_research_performance=None,
        actual_four_participant_data_used=False, d455_used=False)


def tables(result, fixture):
    """Existing long-table conventions, with synthetic status on every row."""
    output = {n: [] for n in ('performance', 'class_metrics', 'confusion_matrices',
                              'seed_confusion_matrices', 'major_errors', 'predictions')}
    for scope, summary in result['scopes'].items():
        selected = [fixture['segments'][i] for i in result['heldout_indices']]
        if scope != 'pooled':
            parts = scope.split('/')
            selected = [r for r in selected if all(p in (r['subject'], r['session']) for p in parts)]
        common = dict(experiment_id=OUT.name, configuration_id=result['configuration_id'],
            scope=scope, class_set='P0,P1,P2,P3,P4,P5', feature_set='H9 F1..F8 (B0)', K=6,
            participant_count=len({r['subject'] for r in selected}), sample_count=summary['sample_count'],
            measurement_status=KIND, source_sha256=object_sha(fixture))
        output['performance'].append(dict(**common, seed='mean', **summary['mean'],
            accuracy_seed_sd=summary['sd_ddof0']['accuracy'], macro_f1_seed_sd=summary['sd_ddof0']['macro_f1']))
        for row in summary['per_seed']:
            output['performance'].append(dict(**common, seed=row['seed'], accuracy=row['accuracy'],
                macro_f1=row['macro_f1'], accuracy_seed_sd=None, macro_f1_seed_sd=None))
        for k, c in enumerate(summary['mean_per_class']):
            output['class_metrics'].append(dict(**common, seed='mean', **c,
                predicted_support=float(np.sum(summary['mean_confusion_matrix'], axis=0)[k])))
        for i in range(6):
            for j in range(6):
                counts = [r['confusion_matrix'][i][j] for r in summary['per_seed']]
                output['confusion_matrices'].append(dict(**common, seed='mean', actual=f'P{i}',
                    predicted=f'P{j}', mean_count=float(np.mean(counts)), seed_sd_count=float(np.std(counts))))
                for row, count in zip(summary['per_seed'], counts):
                    output['seed_confusion_matrices'].append(dict(**common, seed=row['seed'],
                        actual=f'P{i}', predicted=f'P{j}', count=count))
                if i in (0, 1, 5) and i != j:
                    support = summary['mean_per_class'][i]['support']
                    for row, count in zip(summary['per_seed'], counts):
                        output['major_errors'].append(dict(**common, seed=row['seed'], actual=f'P{i}',
                            predicted=f'P{j}', count=count, support=support, rate=count/support))
    for seed, prediction in zip(SEEDS, result['predictions_by_seed']):
        for index, actual, predicted in zip(result['heldout_indices'], result['truth'], prediction):
            row = fixture['segments'][index]
            output['predictions'].append(dict(measurement_status=KIND, seed=seed,
                segment_id=row['segment_id'], subject=row['subject'], session=row['session'],
                round=row['round'], actual=f'P{actual}', predicted=f'P{predicted}'))
    return output


def run(destination, mode='synthetic'):
    if mode != 'synthetic':
        raise ValueError('real/formal data execution is blocked pending freeze and approval')
    destination = Path(destination).resolve()
    if not destination.is_relative_to(OUT) or destination == OUT:
        raise ValueError('output must be a new subdirectory of this evaluator directory')
    if destination.exists():
        raise ValueError('output already exists; select a new name (no overwrite)')
    fixture = synthetic_fixture()
    result = evaluate(fixture, mode)
    result['reused_code'] = [dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in
        (REFERENCE, Path(ev.rf.__file__), Path(ev.agg.__file__), Path(ev.h6.__file__))]
    result['runner_sha256'] = sha(__file__)
    result['environment'] = ev.environment()
    result['input_sha256'] = object_sha(fixture)
    destination.mkdir()
    for name, value in (('synthetic_input.json', fixture), ('results.json', result)):
        with (destination/name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    for name, rows in tables(result, fixture).items():
        with (destination/(name+'.csv')).open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('synthetic', 'formal'), default='synthetic')
    parser.add_argument('--output', type=Path, default=OUT/'synthetic_run')
    args = parser.parse_args(argv)
    try:
        result = run(args.output, args.mode)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(dict(status=KIND, checks=result['checks'],
                         synthetic_pooled=result['scopes']['pooled']['mean']), indent=2))


if __name__ == '__main__':
    main()
