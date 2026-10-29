"""Exploratory measurement review only: no model fitting or input edits.

Run from repository root with python -B analysis/h9/quality_review_20261028/inspect_quality.py.
Creates one new results.json exclusively. Diagnostic deletion is an in-memory
sensitivity calculation, not a replacement H9 feature/aggregation definition.

Before execution: use only the two stage6 inputs and primary5. A short isolated
depth candidate is a 1..3 sample excursion, within one label/segment, bracketed
by 3 finite samples on each side whose medians differ <=10mm. Every excursion
sample must differ from the pooled bracketing median in the same direction by
>max(20mm, 6*1.4826*MAD). Context gaps must be 0..200ms. This diagnostic rule is
not a validated sensor-error detector or an approved production threshold.
Also inspect a fixed 1s band at both ends of each labelled hold as a sensitivity
to label timing. Boundary membership is not proof of a transition or an error.
No parameter search, class performance calculation, filtering deployment,
imputation, model inference/training, six-class evaluation or capture occurs.
"""

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import f1_sample_aggregator as agg
import h6_offline as h6

OUT = Path(__file__).resolve().parent
REFERENCE = ROOT/'analysis/h9/stage6_20261028/results.json'
DEPTH = ('nose_3d_z_m', 'left_shoulder_3d_z_m', 'right_shoulder_3d_z_m',
         'hipless_f2_candidate_chest_depth_m')
XY = ('nose_2d', 'shoulder_midpoint_2d', 'hipless_chest_roi_center_2d')
PRIMARY = ('upright', 'forward_head', 'lean_back', 'lean_left', 'lean_right')


def identity(path):
    p = Path(path).resolve()
    return dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest(), size_bytes=p.stat().st_size)


def verify(items):
    for item in items:
        assert identity(item['path'])['sha256'] == item['sha256']


def number(row, name):
    return float(row[name]) if row[name].strip() else np.nan


def block_events(rows):
    z = np.array([[number(r, name) for name in DEPTH] for r in rows])
    t = np.array([number(r, 'device_timestamp_ms') for r in rows])
    events = []
    for f, name in enumerate(DEPTH):
        flagged = set()
        for start in range(3, len(rows)-3):
            for length in (1, 2, 3):
                stop = start+length
                if stop+3 > len(rows) or any(i in flagged for i in range(start, stop)):
                    continue
                context = np.r_[z[start-3:start,f], z[stop:stop+3,f]]
                window = z[start:stop,f]
                if not np.isfinite(np.r_[context,window]).all():
                    continue
                gaps = np.diff(t[start-3:stop+3])
                if np.any(gaps <= 0) or np.any(gaps > 200):
                    continue
                before, after = np.median(context[:3]), np.median(context[3:])
                if abs(before-after) > .01:
                    continue
                baseline = np.median(context)
                mad = np.median(np.abs(context-baseline))
                threshold = max(.02,6*1.4826*mad)
                residual = window-baseline
                if not (np.all(residual > threshold) or np.all(residual < -threshold)):
                    continue
                flagged.update(range(start,stop))
                xy = {}
                for point in XY:
                    a=np.array([[number(r,point+'_x_px'), number(r,point+'_y_px')] for r in rows[start-3:stop+3]])
                    reference=np.median(np.r_[a[:3],a[-3:]],axis=0)
                    widths=np.array([number(r,'shoulder_width_px') for r in rows[start:stop]])
                    xy[point]=float(np.max(np.linalg.norm(a[3:3+length]-reference,axis=1)/widths))
                other=[]
                for j, other_name in enumerate(DEPTH):
                    if j==f:
                        continue
                    b=np.median(np.r_[z[start-3:start,j],z[stop:stop+3,j]])
                    if np.any(np.abs(z[start:stop,j]-b)>.02):
                        other.append(other_name)
                validity={key:sorted(set(rows[i][key] for i in range(start,stop)))
                          for key in ('pose_detected','nose_depth_valid','left_shoulder_depth_valid',
                                      'right_shoulder_depth_valid','hipless_chest_roi_depth_available')}
                events.append(dict(channel=name, local_indices=list(range(start,stop)),
                                   csv_rows=[rows[i]['_row'] for i in range(start,stop)],
                                   before_m=float(before), after_m=float(after), excursion_m=window.tolist(),
                                   residual_mm=(1000*residual).tolist(), threshold_mm=1000*threshold,
                                   other_depth_channels_with_20mm_excursion=other,
                                   two_d_residual_in_shoulder_widths=xy, validity_flags=validity,
                                   interpretation='isolated depth excursion candidate; sensor cause unverified'))
                break
    return events


def record(row):
    return agg.HFrameRecord(analysis_run_id='probe-csv:'+row['recording_id'],
                            recording_id=row['recording_id'],frame_index=row['_row'],
                            subject=row['subject'],round=None,step=row['segment_id'],
                            label=h6.analysis_label(row['label']),
                            features={n: number(row,n) if row[n].strip() else None for n in agg.H9_FEATURE_NAMES})


def aggregate_change(records, base, removed):
    kept = [r for r in records if r.frame_index not in removed]
    assert kept
    result=agg.aggregate_h5_h9_sample(kept)
    before=np.array(base.ordered_values('H9'))
    after=np.array(result.ordered_values('H9'))
    delta=after-before
    delta[2]=(delta[2]+180)%360-180
    return dict(removed_count=len(records)-len(kept), retained_count=len(kept),
                retained_fraction_of_original=len(kept)/len(records),
                eligibility_on_retained_input=result.eligible,
                original_denominator_coverage=result.common_valid_count/len(records),
                aggregate=after.tolist(), delta=delta.tolist())


def main():
    target=OUT/'results.json'
    if target.exists():
        raise FileExistsError(target)
    prior=json.loads(REFERENCE.read_text(encoding='utf-8'))
    pinned=[*prior['inputs'],identity(REFERENCE),identity(__file__),
            identity(agg.__file__),identity(h6.__file__),identity(ROOT/'posture_geometry.py')]
    verify(pinned)
    segments, all_events, source_summaries = [], [], []
    for source in prior['inputs']:
        with open(source['path'],encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        for i,r in enumerate(rows,1):r['_row']=i
        groups=[]
        for r in rows:
            key=(r['label'],r['segment_id'])
            if not groups or groups[-1][0]!=key:groups.append((key,[]))
            groups[-1][1].append(r)
        summary=dict(subject=source['subject'],total_frames=len(rows),
                     label_counts=dict(Counter(r['label'] for r in rows)),
                     large_adjacent_depth_changes=[], isolated_events_by_label={})
        for name in DEPTH:
            changes=[]
            for a,b in zip(rows,rows[1:]):
                d=number(b,name)-number(a,name)
                if abs(d)>.02:
                    changes.append(dict(csv_row=b['_row'],previous_label=a['label'],label=b['label'],
                                        same_segment=a['segment_id']==b['segment_id'],delta_mm=1000*d))
            summary['large_adjacent_depth_changes'].append(dict(channel=name,count=len(changes),
                      counts_by_destination_label=dict(Counter(x['label'] for x in changes)),
                      largest=sorted(changes,key=lambda x:-abs(x['delta_mm']))[:10]))
        for (label,segment_id), group in groups:
            events=block_events(group)
            for e in events:e.update(subject=source['subject'],segment_id=segment_id,label=label)
            all_events.extend(events)
            summary['isolated_events_by_label'][label]=summary['isolated_events_by_label'].get(label,0)+len(events)
            if label not in PRIMARY:
                continue
            records=[record(r) for r in group]
            baseline=agg.aggregate_h5_h9_sample(records)
            key=list(baseline.sample_key)
            ix=prior['sample_keys'].index(key)
            np.testing.assert_array_equal(baseline.ordered_values('H9'),prior['matrices']['H9'][ix])
            spike=set(i for e in events for i in e['csv_rows'])
            t=np.array([number(r,'device_timestamp_ms') for r in group])
            boundary={r['_row'] for i,r in enumerate(group) if t[i]-t[0]<1000 or t[-1]-t[i]<1000}
            variations={name: aggregate_change(records,baseline,removed)
                        for name,removed in (('isolated_candidates',spike),('boundary_1s',boundary),
                                             ('union',spike|boundary))}
            a=np.array([r.features[n] for r in records for n in agg.H9_FEATURE_NAMES]).reshape(-1,9)
            feature_quantiles=np.percentile(a,[0,5,25,50,75,95,100],axis=0).tolist()
            # Descriptive variability of the middle portion: not an error estimate.
            core=np.array([r.features[n] for r in records if r.frame_index not in boundary
                           for n in agg.H9_FEATURE_NAMES]).reshape(-1,9)
            core_iqr=(np.percentile(core,75,axis=0)-np.percentile(core,25,axis=0)).tolist()
            segments.append(dict(subject=source['subject'],segment_id=segment_id,label=label,
                                 sample_key=key,frame_count=len(records),baseline=list(baseline.ordered_values('H9')),
                                 spike_rows=sorted(spike),boundary_rows=sorted(boundary),
                                 spike_and_boundary_overlap=sorted(spike&boundary),
                                 feature_quantiles_0_5_25_50_75_95_100=feature_quantiles,
                                 interior_feature_iqr=core_iqr,variations=variations))
        source_summaries.append(summary)
    aggregate_sensitivity={}
    for variant in ('isolated_candidates','boundary_1s','union'):
        d=np.array([s['variations'][variant]['delta'] for s in segments])
        aggregate_sensitivity[variant]=dict(
            affected_segments=sum(s['variations'][variant]['removed_count']>0 for s in segments),
            removed_frames=sum(s['variations'][variant]['removed_count'] for s in segments),
            total_original_frames=sum(s['frame_count'] for s in segments),
            max_abs_delta=np.max(np.abs(d),axis=0).tolist(),median_abs_delta=np.median(np.abs(d),axis=0).tolist(),
            largest_segment_by_feature=[dict(subject=segments[i]['subject'],segment_id=segments[i]['segment_id'],
                                            label=segments[i]['label'],delta=float(d[i,j]))
                                        for j,i in enumerate(np.argmax(np.abs(d),axis=0))])
    verify(pinned)
    result=dict(kind='exploratory-quality-diagnostic-no-model-training',created_utc=datetime.now(timezone.utc).isoformat(),
                pinned_inputs_and_code=pinned, scope='primary5',feature_order=agg.H9_FEATURE_NAMES,
                method=dict(short_excursion_samples=[1,2,3],bracket_samples_per_side=3,
                            bracket_median_tolerance_mm=10,minimum_excursion_mm=20,mad_multiplier=6,
                            mad_normalization=1.4826,maximum_context_gap_ms=200,boundary_band_ms=1000,
                            notes='Diagnostic choices fixed in script before execution; no threshold search. Not a validated filter.'),
                source_summaries=source_summaries,isolated_depth_candidates=all_events,
                segments=segments,aggregate_sensitivity=aggregate_sensitivity,
                verification=dict(all_20_original_h9_aggregates_exact_match_stage6=True,
                                  source_code_and_previous_results_unchanged=True,
                                  no_models_fitted_or_predictions_computed=True),
                limitations=['No RGB/video ground truth of posture transitions or depth accuracy',
                             'Stored depth/XYZ are already spatial ROI medians; raw depth pixel error cannot be quantified',
                             'Short-event rule misses persistent bias and events at label edges',
                             'Boundary deletion is sensitivity to timing, not an adjudicated error correction',
                             'Reaggregation is temporary diagnostic output, not a replacement baseline',
                             'Retained-input eligibility is not approval of a new formal denominator/selection policy'])
    with target.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,allow_nan=False,indent=2);stream.write('\n')
    for s in source_summaries:print('SOURCE',s['subject'],'frames',s['label_counts'],'isolated_events',s['isolated_events_by_label'])
    print('ISOLATED_EVENTS',all_events)
    print('SENSITIVITY',aggregate_sensitivity)
    for s in segments:
        print('SEGMENT',s['subject'],s['segment_id'],s['label'],'spikes',s['spike_rows'],
              'boundary_removed',len(s['boundary_rows']),'spike_delta',s['variations']['isolated_candidates']['delta'],
              'boundary_delta',s['variations']['boundary_1s']['delta'])


if __name__=='__main__':main()
