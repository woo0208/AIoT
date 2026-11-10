"""Read-only stored-feature integration, existing pinned LOSO artifacts only.

No RGB-D replay, camera, training, model selection, accuracy search or E1.
Uses virtual replay time; no runtime/FPS conclusions from saved features.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from unittest.mock import patch

from e0_fs3 import E0Session,COLUMNS,FEATURE_IDS,H9_FEATURE_NAMES
from e0_model import load_fs3,ModelNotReady,environment_record
from e0_storage import write_json
from posture_geometry import GeometryResult


ROOT=Path(__file__).resolve().parent
OLD=ROOT/'analysis/PILOT120_SEVEN_CANDIDATE_REVIEW_20261108/local_private/results.json'
SOURCE=ROOT/'analysis/LR6_LR9_POST_SUPPLEMENT_20261108/local_private/results.json'
BUNDLE=SOURCE.parent/'dataset120/bundle_info.json'
CODE=('e0_fs3.py','e0_resources.py','e0_storage.py','probe_diagnostics.py','e0_model.py',
      'e0_panel.py','e0_p3_verify.py','posture_geometry_probe.py','f1_sample_aggregator.py')


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class ReplayClock:
    def __init__(self):self.ns=0
    def __call__(self):return self.ns


def run(folder):
    if folder.exists():raise FileExistsError(folder)
    private=folder/'local_private';private.mkdir(parents=True)
    audit=dict(kind='STORED_INPUT_INTEGRATION_ONLY',scope='NON_FORMAL_ENGINEERING',
        no_training=True,no_camera=True,model_status='MODEL_NOT_READY',models=[],modes=[],
        source_sha256={name:digest(ROOT/name) for name in CODE},
        environment=environment_record(),
        known_input_sha256={str(p.relative_to(ROOT)):digest(p) for p in (OLD,SOURCE,BUNDLE)})
    old=read(OLD);source=read(SOURCE);bundle=read(BUNDLE)
    assert old['features']==list(FEATURE_IDS)
    # Only the two already existing repetition-0 LOSO models are replayed.
    # No fold is promoted into a live/deployment model.
    records=[r for r in old['records'] if r['model']=='SVM-RBF' and r['repetition']==0]
    records.sort(key=lambda r:r['fold']);assert [r['fold'] for r in records]==[0,1]
    for record in records:
        try:
            model,scaler,binding=load_fs3(ROOT/record['model_path'],record['model_sha256'],old['features'])
            assert binding['training_samples']==len(record['train'])==60
            again=load_fs3(ROOT/record['model_path'],record['model_sha256'],old['features'])
            assert again[2]==binding
            audit['models'].append(dict(fold=record['fold'],path=record['model_path'],binding=binding))
            write_json(private/f"model_fold{record['fold']}.json",dict(path=record['model_path'],**binding))
        except (ModelNotReady,AssertionError):
            write_json(private/'verification.json',audit)
            (folder/'REPORT.md').write_text('# E0-P3\n\nMODEL_NOT_READY. No training attempted.\n',encoding='utf-8')
            print('MODEL_NOT_READY; no training attempted');return
    audit['model_status']='MODEL_READY_FOR_EXISTING_LOSO_REPLAY; LIVE_ARTIFACT_NOT_SELECTED'
    groups=defaultdict(list)
    source_hashes=[]
    for path,expected in bundle['source_csv_sha256'].items():
        p=ROOT/path;assert digest(p)==expected;source_hashes.append(expected)
        with p.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):groups[(row['recording_id'],str(row['segment_id']))].append(row)
    audit['feature_csv_sha256']=sorted(source_hashes)
    matrix=np.asarray(source['matrix'])
    for record,model_record in zip(records,audit['models']):
        model,scaler,binding=load_fs3(ROOT/record['model_path'],record['model_sha256'],old['features'],
            expected_model_sha256=model_record['binding']['model_sha256'],
            expected_scaler_sha256=model_record['binding']['scaler_sha256'])
        train=record['train']
        training=matrix[:,COLUMNS][train]
        np.testing.assert_allclose(scaler.mean_,np.mean(training,axis=0),rtol=1e-14,atol=1e-14)
        np.testing.assert_allclose(scaler.var_,np.var(training,axis=0),rtol=1e-14,atol=1e-14)
        signatures=[]
        for mode in ('off','summary','detailed'):
            clock=ReplayClock()
            session=E0Session(private/f"fold{record['fold']}_{mode}",model,scaler,clock_ns=clock,
                mode=mode,input_scope='stored_features',model_binding=binding)
            session.begin_stream();index=0;out=[]
            try:
                with patch.object(SVC,'fit',side_effect=AssertionError('no fit')), \
                     patch.object(StandardScaler,'fit',side_effect=AssertionError('no fit')):
                    for sample_index in record['test']:
                        key=source['sample_keys'][sample_index]
                        rows=groups[(key[1],str(key[2]))];assert len(rows)==150
                        first=float(rows[0]['device_timestamp_ms'])
                        session.arm_segment()
                        for raw in rows:
                            values={name:float(raw[name]) if raw[name].strip() else None for name in H9_FEATURE_NAMES}
                            index+=1;clock.ns+=1_000_000
                            row=session.begin_receive()
                            session.received(row,True,None,clock())  # sensor metadata NOT_MEASURED
                            relative_ms=float(raw['device_timestamp_ms'])-first
                            assert 0<=relative_ms<10000
                            session.accept(row,GeometryResult({}, {}, values),index,
                                relative_ms,pose_detected=str(raw.get('pose_detected','')).lower()=='true'
                                if 'pose_detected' in raw else None,face_detected=None)
                            session.frame_completed(row)
                        # A time-boundary notification, not a fabricated RGB/Depth frame.
                        sample=session.records
                        from f1_sample_aggregator import aggregate_h5_h9_sample
                        reference=aggregate_h5_h9_sample(sample)
                        actual=np.array([reference.features[H9_FEATURE_NAMES[i]] for i in COLUMNS])
                        np.testing.assert_array_equal(actual,matrix[sample_index,list(COLUMNS)])
                        clock.ns+=1_000_000
                        session.complete_segment(10000,index,clock())
                        segment=session.segments[-1]
                        out.append(dict(n=segment['input_frames'],valid=segment['valid_frames'],
                            coverage=segment['coverage'],prediction=segment['prediction']))
                assert [r['prediction'] for r in out]==record['predictions']
            finally:
                session.end_stream();session.finish(error=__import__('sys').exc_info()[1])
            fingerprint=hashlib.sha256(json.dumps(out,sort_keys=True).encode()).hexdigest();signatures.append(fingerprint)
            audit['modes'].append(dict(fold=record['fold'],mode=mode,samples=len(out),
                result_sha256=fingerprint,exact_batch_match=True,predictions_match_existing=True,
                buffer_peaks=session.result_summary.get('buffering',{})))
        assert len(set(signatures))==1
    audit['stored_samples']=120
    audit['mode_comparisons']=360
    audit['result']='PASS'
    audit['limitations']=['Stored post-geometry features only; no sensor pipeline latency/FPS',
        'No participant identities/feature vectors/ground truth copied into new logs',
        'Original device intervals preserved; replay timestamps translated to segment-relative time',
        'Existing two LOSO artifacts each trained on 60; live artifact selection remains explicit']
    assert all(digest(ROOT/p)==h for p,h in audit['known_input_sha256'].items())
    assert all(digest(ROOT/p)==h for p,h in bundle['source_csv_sha256'].items())
    assert all(digest(ROOT/r['model_path'])==r['model_sha256'] for r in records)
    write_json(private/'verification.json',audit)
    text=['# E0-P3 integration verification','',audit['result'],audit['model_status'],
        '120 stored eligible segments x OFF/summary/detailed = 360 segment comparisons.',
        'Two existing 60-training-sample LOSO artifact pairs; no selection/refit.',
        '7-feature order, archive SHA-256, component serialization hashes, T0 settings and train-only scaler statistics verified.',
        'Original H9 support/aggregate equals saved matrix; predictions equal existing held-out outputs in every mode.',
        'Replay is post-geometry with virtual/relative time, not a D455 latency/FPS benchmark.',
        'Bounded checkpoint buffers retain every record and exact disk-backed percentiles. No log sampling.',
        'UI and buffer-failure/percentile/memory tests are reported in E0_INSTRUMENTATION.md.',
        'Live measurement remains gated by explicit artifact choice, approvals, operator and device checks.',
        'Private evidence: local_private/verification.json and model_fold0.json/model_fold1.json.',
        'No camera, training, E1 optimization, commit or push.','']
    (folder/'REPORT.md').write_text('\n'.join(text),encoding='utf-8')
    print('PASS: 120 stored samples, 360 exact aggregate/prediction checks, two existing pinned models; no fit/camera')


def verify(folder):
    audit=read(folder/'local_private/verification.json')
    if audit['model_status']=='MODEL_NOT_READY':print('MODEL_NOT_READY');return
    assert audit['result']=='PASS' and audit['mode_comparisons']==360
    assert all(digest(ROOT/name)==h for name,h in audit['source_sha256'].items())
    assert all(digest(ROOT/name)==h for name,h in audit['known_input_sha256'].items())
    assert sorted(read(BUNDLE)['source_csv_sha256'].values())==audit['feature_csv_sha256']
    for item in audit['models']:
        binding=item['binding']
        load_fs3(ROOT/item['path'],binding['artifact_sha256'],binding['feature_ids'],
            expected_model_sha256=binding['model_sha256'],expected_scaler_sha256=binding['scaler_sha256'])
    for fold in (0,1):assert len({r['result_sha256'] for r in audit['modes'] if r['fold']==fold})==1
    print('PASS: saved integration evidence/source/model hashes; no replay, fit or camera')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    (verify if args.verify else run)(args.output_dir)
