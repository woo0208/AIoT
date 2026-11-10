"""Opt-in E0 engineering observer; no camera, fit, artifact selection or raw images.

Arm each stable hold explicitly. The next completed geometry frame starts the
unchanged device-time [first, first+10000ms) interval. Its first end-boundary
arrival closes the hold; preparation/transitions never enter the aggregate.
Caller supplies an already fitted, explicitly selected FS3 T0 model/scaler.
"""
from collections import Counter
import math
from pathlib import Path
import time

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.utils.validation import check_is_fitted

import engineering_exports as exports
import frame_provenance as provenance
from f1_sample_aggregator import H9_FEATURE_NAMES, HFrameRecord, aggregate_h5_h9_sample
import performance_output as output
from probe_diagnostics import ProbeDiagnostics, DisabledDiagnostics
from e0_resources import ResourceMonitor
from e0_storage import CheckpointList, write_json, write_rows


COLUMNS = (0, 2, 3, 4, 5, 6, 7)
FEATURE_IDS = tuple(f'F{i+1}' for i in COLUMNS)
WINDOW_MS = 10000


def validate_model(model, scaler):
    """Check only; never fit, choose a fold, or modify estimator state."""
    if not isinstance(model, SVC) or not isinstance(scaler, StandardScaler):
        raise ValueError('E0 requires fitted SVC and StandardScaler')
    expected = SVC(C=1., kernel='rbf', gamma=1./9, shrinking=True,probability=False,
        tol=1e-3,cache_size=200,class_weight=None,max_iter=-1,
        decision_function_shape='ovr',break_ties=False,random_state=0).get_params()
    if model.get_params() != expected or scaler.get_params() != StandardScaler().get_params():
        raise ValueError('Not FS3-V0-T0 settings')
    check_is_fitted(model, ['classes_', 'support_vectors_', 'n_features_in_', '_gamma'])
    check_is_fitted(scaler, ['mean_', 'var_', 'scale_', 'n_features_in_'])
    if (model.n_features_in_ != 7 or scaler.n_features_in_ != 7
            or not np.array_equal(model.classes_, np.arange(6))):
        raise ValueError('Expected seven inputs and classes 0..5')
    if model._gamma != 1./9:
        raise ValueError('Fitted SVM gamma differs from T0')
    if any(np.asarray(getattr(scaler, name)).shape != (7,)
           or not np.isfinite(getattr(scaler, name)).all() for name in ('mean_', 'var_', 'scale_')):
        raise ValueError('Invalid fitted scaler')
    if np.any(scaler.scale_ <= 0):
        raise ValueError('Invalid scaler scale')


class E0Session:
    def __init__(self, directory, model, scaler, *, clock_ns=time.perf_counter_ns,
                 mode='detailed', resource_monitor=None, synthetic=False,
                 log_buffer_limit=256, input_scope='live', model_binding=None):
        validate_model(model, scaler)
        if type(log_buffer_limit) is not int or log_buffer_limit<1 or input_scope not in ('live','stored_features'):
            raise ValueError('invalid E0 buffer/input scope')
        if mode not in ('off','summary','detailed'):
            raise ValueError('E0 mode must be off, summary or detailed')
        self.mode = mode
        self.directory = exports.reserve(directory) if mode!='off' else None
        self.clock_ns = clock_ns if mode!='off' else lambda:0
        self.scope = ('NON_FORMAL_ENGINEERING' if clock_ns is time.perf_counter_ns and not synthetic
                      else 'SYNTHETIC_STRUCTURAL_TEST_ONLY')
        if input_scope=='stored_features':self.scope='NON_FORMAL_ENGINEERING'
        self.input_scope=input_scope
        self.model_binding=model_binding or dict(status='UNPINNED_IN_MEMORY')
        self.environment_metadata=dict(status='NOT_RECORDED')
        self.model, self.scaler = model, scaler
        self.timing = (ProbeDiagnostics(self.directory/'timing', clock_ns=clock_ns,
            include_p99=True, redact_errors=True,retain_raw=mode=='detailed',buffer_limit=log_buffer_limit)
            if mode!='off' else DisabledDiagnostics())
        self.timing.identity['scope'] = self.scope
        # Real resource counters cannot be interpreted against a virtual clock.
        self.resources = (None if mode=='off' else resource_monitor if resource_monitor is not None else
            ResourceMonitor(clock_ns=clock_ns) if clock_ns is time.perf_counter_ns else None)
        if self.resources is not None and self.resources.clock_ns is not clock_ns:
            raise ValueError('Resource/frame observations require the same clock')
        if self.resources is not None:
            self.resources.enable_checkpoints(self.directory/'buffers'/'resources',log_buffer_limit)
        self.frames = (CheckpointList(self.directory/'buffers'/'frames',log_buffer_limit,clock_ns=self.clock_ns)
                       if mode=='detailed' else [])
        self.segments = (CheckpointList(self.directory/'buffers'/'segments',log_buffer_limit,clock_ns=self.clock_ns)
                         if mode!='off' else [])
        self._pending_row = None
        self._receive_index = 0
        self._counts, self._statuses, self._failures = Counter(), Counter(), Counter()
        self._sensor_events = {name:Counter() for name in ('rgb','depth')}
        self.backends = dict(svm=dict(actual='sklearn.SVC/libsvm CPU',status='IMPLEMENTATION_CONFIRMED'),
            pose=dict(actual='NOT_MEASURED'),face=dict(actual='NOT_MEASURED'))
        self.previous = {'raw': {}, 'aligned': {}}
        self.armed = False
        self.active = None
        self.last_segment_issue = None
        self._segment_time_failures = Counter()
        self.records = []
        self._last_index = 0
        self._finished = False
        self._start_ns = self._end_ns = None
        self._loop = None
        self._loop_index = 0
        self._loop_statuses = Counter()

    def begin_loop(self):
        boundary = self.clock_ns()
        self.end_loop(end_ns=boundary)
        # Closing the previous sample is observer work in this new loop.
        self._loop_index += 1
        self._loop = dict(index=self._loop_index, start_ns=boundary, row=None)

    def end_loop(self, *, end_ns=None):
        loop = self._loop
        if loop is None:
            return
        self._loop = None
        end = self.clock_ns() if end_ns is None else end_ns
        row = loop['row']
        status = row['status'] if row is not None else 'control_only'
        if status in ('waiting', 'received', 'processing'):
            status = 'INCOMPLETE'
        self._loop_statuses[status] += 1
        if row is not None:
            row.update(loop_end_ns=end, loop_total_ns=end-loop['start_ns'])
        self.timing.record_ns('loop.total', end-loop['start_ns'],
                              row.get('frame_id') if row is not None else None)

    def begin_stream(self):
        self._start_ns = self.clock_ns()
        if self.resources is not None:
            self.resources.start()

    def end_stream(self):
        if self._end_ns is None:
            self._end_ns = self.clock_ns()
            if self.resources is not None:
                self.resources.stop()

    def observe_backends(self, pose_options, face_options):
        for name,options in [('pose',pose_options),('face',face_options)]:
            base=options.get('base_options') if isinstance(options,dict) else getattr(options,'base_options',None)
            delegate=base.get('delegate') if isinstance(base,dict) else getattr(base,'delegate',None)
            configured=getattr(delegate,'name',None)
            self.backends[name]=dict(actual='NOT_MEASURED',
                configured_delegate=configured if configured in ('CPU','GPU') else 'DEFAULT_OR_UNKNOWN',
                reason='Task options are not runtime backend attestation')

    def _flush_row(self):
        row=self._pending_row
        if row is None:
            return
        self._pending_row=None
        if self.mode=='off':
            return
        self._statuses[row['status']]+=1
        self._counts['received']+=bool(row.get('received'))
        self._counts['completed']+=row['status']=='completed'
        if 'feature_success' in row:
            self._counts['evaluated']+=1
            self._counts['feature_success']+=row['feature_success']
            self._failures.update(row['feature_failure_reasons'])
        if 'raw_relations' in row:
            for name in ('rgb','depth'):
                self._sensor_events[name][row['raw_relations'][name]['classification']]+=1

    def arm_segment(self):
        if self._finished or self.armed or self.active is not None:
            raise ValueError('E0 segment already active or session closed')
        self.armed = True
        self.last_segment_issue = None

    def _reject_segment_time(self, row, issue):
        # Reject the entire hold, never repair timestamps or reuse a prediction.
        # A source-time anomaly is recoverable at the operator/session boundary.
        row['segment_time_failure'] = issue
        self._segment_time_failures[issue] += 1
        if self.active is not None:
            self.active['timestamp_failure'] = issue
        self.cancel_segment('timestamp_invalid')
        self.last_segment_issue = 'TIMESTAMP_INVALID'

    def cancel_segment(self, reason='operator_cancel'):
        if reason not in ('operator_cancel', 'stream_end', 'timestamp_invalid', 'source_invalid'):
            raise ValueError('Unsupported cancellation reason')
        if self.active is not None:
            valid = sum(all(r.features[n] is not None for n in H9_FEATURE_NAMES) for r in self.records)
            self.active.update(status='INCOMPLETE', reason=reason, input_frames=len(self.records),
                valid_frames=valid, coverage=valid/len(self.records) if self.records else None,
                eligible=False, prediction_attempted=False)
        self.records = []
        self.active = None
        self.armed = False

    def begin_receive(self):
        if self.resources is not None:self.resources.check_health()
        self._flush_row()
        # Checkpoint I/O precedes the SDK-wait timestamp, never masquerades as sensor wait.
        if isinstance(self.frames,CheckpointList) and len(self.frames.buffer)>=self.frames.limit:
            self.frames.flush()
        self._receive_index+=1
        row = dict(receive_index=self._receive_index, status='waiting',
                   receive_start_ns=self.clock_ns())
        if self._loop is not None:
            self._loop['row'] = row
            row.update(loop_index=self._loop['index'], loop_start_ns=self._loop['start_ns'])
        if self.mode=='detailed':
            self.frames.append(row)
        self._pending_row=row
        return row

    def _snapshot(self, frame):
        # Existing accessor semantics; exception text/path and device serial never escape.
        value = provenance.snapshot(frame)
        value.pop('unavailable', None)
        return value

    def _children(self, row, boundary, children):
        values = {name: self._snapshot(frame) for name, frame in children.items()}
        relations = {name: provenance.compare(self.previous[boundary].get(name), value)
                     for name, value in values.items()}
        for name, relation in relations.items():
            if relation['status'] != 'MEASURED':
                relation['classification'] = 'NOT_MEASURED'
                continue
            previous = self.previous[boundary][name]
            relation['counter_regression'] = values[name]['number'] < previous['number']
            relation['timestamp_regression'] = values[name]['timestamp_ms'] < previous['timestamp_ms']
            if relation['counter_regression']:
                relation['classification'] = 'COUNTER_RESET_OR_WRAP'
            elif relation['timestamp_regression']:
                relation['classification'] = 'TIMESTAMP_REGRESSION'
            elif relation['boundary']:
                relation['classification'] = 'STREAM_BOUNDARY'
            elif relation['same_identity']:
                relation['classification'] = 'DUPLICATE_IDENTITY'
            elif not relation['number_changed']:
                relation['classification'] = 'NUMBER_REUSED_DIFFERENT_TIMESTAMP'
            elif relation['source_gap']:
                relation['classification'] = 'ADVANCED_WITH_NUMBER_GAP'
            else:
                relation['classification'] = 'ADVANCED'
        for name, relation in relations.items():
            other = relations['depth' if name == 'rgb' else 'rgb']
            relation['child_reused_while_other_advanced'] = (
                relation['classification'] == 'DUPLICATE_IDENTITY'
                and other['classification'].startswith('ADVANCED'))
        row[boundary], row[boundary+'_relations'] = values, relations
        self.previous[boundary] = values

    def received(self, row, ready, frames, end_ns):
        end_ns=end_ns if self.mode!='off' else 0
        row.update(receive_end_ns=end_ns, received=bool(ready), status='received' if ready else 'timeout')
        self.timing.record_ns('receive.wait', end_ns-row['receive_start_ns'])
        if ready and self.mode!='off':
            children = {}
            for name, getter in (('rgb', 'get_color_frame'), ('depth', 'get_depth_frame')):
                try:
                    children[name] = getattr(frames, getter)()
                except Exception:
                    children[name] = None
            self._children(row, 'raw', children)

    def aligned(self, row, color, depth):
        if self.mode=='off':
            return
        row['align_observed_ns'] = self.clock_ns()
        self._children(row, 'aligned', dict(rgb=color, depth=depth))
        row['raw_vs_aligned'] = {name: provenance.compare(row['raw'][name], row['aligned'][name],
            across_align=True) for name in ('rgb', 'depth')}

    def processing_started(self, row, frame_index):
        row.update(status='processing', frame_id=frame_index, processing_start_ns=self.clock_ns())

    def accept(self, row, result, frame_index, device_timestamp_ms, *, pose_detected, face_detected):
        if self._finished or type(frame_index) is not int or frame_index <= self._last_index:
            raise ValueError('E0 input ordering/session error')
        self._last_index = frame_index
        row.update(frame_id=frame_index, pose_detected=None if pose_detected is None else bool(pose_detected),
                   face_detected=None if face_detected is None else bool(face_detected))
        with self.timing.stage('fs3.feature_select', frame_index):
            values = {name: result.features.get(name) for name in H9_FEATURE_NAMES}
            missing = [f'F{i+1}' for i, name in enumerate(H9_FEATURE_NAMES) if values[name] is None]
            invalid = [f'F{i+1}' for i, name in enumerate(H9_FEATURE_NAMES) if values[name] is not None
                       and (isinstance(values[name], bool) or not isinstance(values[name], (int, float))
                            or not math.isfinite(values[name]))]
            row['feature_success'] = not any(f in missing+invalid for f in FEATURE_IDS)
            row['h9_common_success'] = not missing and not invalid
            row['feature_failure_reasons'] = [f'missing_{f}' for f in missing if f in FEATURE_IDS]
            row['feature_failure_reasons'] += [f'invalid_{f}' for f in invalid if f in FEATURE_IDS]
            if not row['feature_success'] and pose_detected is False:
                row['feature_failure_reasons'].append('pose_not_detected')
            if not row['feature_success'] and face_detected is False:
                row['feature_failure_reasons'].append('face_not_detected')
        row['feature_ready_ns'] = self.clock_ns()
        self.timing.record_ns('latency.receive_to_features',
                              row['feature_ready_ns']-row['receive_end_ns'], frame_index)
        if not self.armed and self.active is None:
            return
        if invalid or not set(H9_FEATURE_NAMES).issubset(result.features):
            self.cancel_segment('source_invalid')
            raise ValueError('Invalid original H9 observation')
        try:
            stamp = float(device_timestamp_ms)
        except (TypeError, ValueError):
            self._reject_segment_time(row, 'not_numeric')
            return
        if not math.isfinite(stamp):
            self._reject_segment_time(row, 'non_finite')
            return
        if self.active is not None and stamp <= self.active['last_device_ms']:
            self._reject_segment_time(row,
                'duplicate_timestamp' if stamp == self.active['last_device_ms'] else 'timestamp_regression')
            return
        if self.active is None:
            self.active = dict(segment_index=len(self.segments)+1, status='COLLECTING',
                first_device_ms=stamp, window_end_device_ms=stamp+WINDOW_MS, last_device_ms=stamp,
                first_receive_ns=row['receive_end_ns'], last_receive_ns=row['receive_end_ns'])
            self.segments.append(self.active)
            self.armed = False
        elif stamp >= self.active['first_device_ms']+WINDOW_MS:
            self.complete_segment(stamp,frame_index,row['receive_end_ns'])
            return  # End-boundary observation is not part of the preceding hold.
        self.records.append(HFrameRecord('E0', 'E0', frame_index, 'anonymous', None,
            str(self.active['segment_index']), 'unlabelled', values))
        self.active.update(last_device_ms=stamp, last_receive_ns=row['receive_end_ns'])
        row['segment_index'] = self.active['segment_index']

    def complete_segment(self, device_timestamp_ms, frame_id, receive_end_ns):
        stamp=float(device_timestamp_ms)
        if self.active is None or not math.isfinite(stamp) or stamp<self.active['window_end_device_ms']:
            raise ValueError('10-second source interval not complete')
        self._close(dict(frame_id=frame_id,receive_end_ns=receive_end_ns if self.mode!='off' else 0))

    def _close(self, boundary):
        segment = self.active
        segment['end_boundary_frame_id'] = boundary['frame_id']
        segment['status'] = 'AGGREGATING'
        started = self.clock_ns()
        try:
            with self.timing.stage('fs3.aggregate'):
                sample = aggregate_h5_h9_sample(self.records)
            segment.update(input_frames=sample.n_frames, valid_frames=sample.common_valid_count,
                coverage=sample.common_coverage, eligible=sample.eligible,
                eligibility_reasons=list(sample.eligibility_reasons),
                aggregation_ns=self.clock_ns()-started, prediction_attempted=False)
            if not sample.eligible:
                segment['status'] = 'INELIGIBLE'
                return
            x = np.asarray([[sample.features[H9_FEATURE_NAMES[i]] for i in COLUMNS]], dtype=float)
            segment['prediction_attempted'] = True
            segment.update(scale_success=False, svm_attempted=False)
            infer_start = self.clock_ns()
            try:
                scale_start = self.clock_ns()
                try:
                    with self.timing.stage('fs3.scale'):
                        scaled = self.scaler.transform(x)
                finally:
                    segment['scale_ns'] = self.clock_ns()-scale_start
                if np.asarray(scaled).shape != (1, 7) or not np.isfinite(scaled).all():
                    raise ValueError('Invalid scaled FS3 input')
                segment.update(scale_success=True, svm_attempted=True, svm_success=False)
                svm_start = self.clock_ns()
                try:
                    with self.timing.stage('fs3.svm'):
                        prediction = self.model.predict(scaled)
                finally:
                    segment['svm_ns'] = self.clock_ns()-svm_start
                if np.asarray(prediction).shape != (1,) or prediction[0] not in range(6):
                    raise ValueError('Invalid FS3 prediction')
                end = self.clock_ns()
                segment.update(status='PREDICTED', prediction=int(prediction[0]),
                    prediction_label=f'P{int(prediction[0])}', prediction_success=True,
                    svm_success=True, scale_svm_ns=end-infer_start)
                for name, begin in [('first_input', segment['first_receive_ns']),
                                    ('last_input', segment['last_receive_ns']),
                                    ('boundary_input', boundary['receive_end_ns'])]:
                    elapsed = end-begin
                    segment[name+'_to_prediction_ns'] = elapsed
                    self.timing.record_ns('latency.'+name+'_to_prediction', elapsed)
            except Exception as exc:
                segment.update(status='PREDICTION_FAILED', prediction_success=False,
                               error_type=type(exc).__name__, scale_svm_ns=self.clock_ns()-infer_start)
                raise
        finally:
            if segment['status'] == 'AGGREGATING':
                segment['status'] = 'AGGREGATION_FAILED'
            self.records = []
            self.active = None

    def frame_completed(self, row):
        row.update(status='completed', processing_end_ns=self.clock_ns())
        if 'loop_start_ns' in row:
            self.timing.record_ns('latency.loop_start_to_frame_complete',
                                 row['processing_end_ns']-row['loop_start_ns'], row['frame_id'])
        for name, begin in [('receive_to_frame_complete', row['receive_end_ns']),
                            ('receive_wait_start_to_frame_complete', row['receive_start_ns'])]:
            self.timing.record_ns('latency.'+name, row['processing_end_ns']-begin, row.get('frame_id'))

    def finish(self, *, error=None, cleanup_errors=()):
        if self._finished:
            return
        self.end_loop()
        self.end_stream()
        self.cancel_segment('stream_end')
        if self._pending_row is not None and self._pending_row['status'] in ('received','waiting','processing'):
            self._pending_row['status']='INCOMPLETE'
        self._flush_row()
        for rows in (self.frames,self.segments):
            if isinstance(rows,CheckpointList):rows.flush()
        if self.resources is not None:
            for rows in (self.resources.samples,self.resources.gpu_samples):
                if isinstance(rows,CheckpointList):rows.flush()
        self.timing.finish(status='FAILED' if error is not None or cleanup_errors else 'COMPLETED',
                           error=error, cleanup_errors=cleanup_errors)
        received, evaluated = self._counts['received'], self._counts['evaluated']
        attempts = [s for s in self.segments if s.get('prediction_attempted')]
        svm_attempts = [s for s in self.segments if s.get('svm_attempted')]
        seconds = (self._end_ns-self._start_ns)/1e9 if self._start_ns is not None else None
        ratio = lambda n, d: 100*n/d if d else None
        summary = dict(scope=self.scope, model='SVM-FS3-V0-T0',
            feature_ids=list(FEATURE_IDS), window_ms=WINDOW_MS,
            model_validation='settings and fitted shape checked; artifact/training lineage supplied by caller',
            model_binding=self.model_binding, environment=self.environment_metadata,
            input_scope=self.input_scope,
            timing_valid_for_live_performance=self.input_scope=='live' and self.scope=='NON_FORMAL_ENGINEERING',
            support='original H9 joint support; >=30 frames and coverage>=0.5',
            status='FAILED' if error is not None or cleanup_errors else 'COMPLETED',
            error_type=type(error).__name__ if error is not None else None,
            stream_seconds=seconds, received_frames=received, evaluated_frames=evaluated,
            unevaluated_received_frames=received-evaluated,
            frame_status_counts=dict(self._statuses),
            completed_frames=self._counts['completed'],
            feature_success_frames=self._counts['feature_success'],
            feature_success_percent=ratio(self._counts['feature_success'],received),
            failure_reasons=dict(self._failures),
            sensor_events={name:dict(counts) for name,counts in self._sensor_events.items()},
            segment_time_failures=dict(self._segment_time_failures),
            loop_count=sum(self._loop_statuses.values()), loop_status_counts=dict(self._loop_statuses),
            timing_contract='e0-e1-loop-timing/1',
            timing_boundaries=dict(
                legacy_frame='SDK receive end -> frame_completed; unchanged',
                legacy_wait_frame='SDK wait start -> frame_completed; unchanged',
                loop_frame='before Tk poll -> frame_completed; successful frames only',
                loop_total='before Tk poll -> next loop start or cleanup entry; all loop outcomes'),
            prediction_attempts=len(attempts), prediction_successes=sum(s.get('prediction_success',False) for s in attempts),
            prediction_success_percent=ratio(sum(s.get('prediction_success',False) for s in attempts),len(attempts)),
            svm_attempts=len(svm_attempts), svm_successes=sum(s.get('svm_success',False) for s in svm_attempts),
            svm_success_percent=ratio(sum(s.get('svm_success',False) for s in svm_attempts),len(svm_attempts)),
            sensor_missing_rate='NOT_MEASURED', gpu_usage='NOT_MEASURED',
            measurement_mode=self.mode, measurement_status='DISABLED' if self.mode=='off' else 'ENABLED',
            inference_backends=self.backends,
            queue=dict(application_queue='NOT_APPLICABLE',length='NOT_APPLICABLE',
                wait='NOT_APPLICABLE',drops='NOT_APPLICABLE',
                sdk_internal_queue='NOT_MEASURED',sensor_wait_stage='receive.wait'),
            resources=self.resources.summary() if self.resources is not None else dict(status='NOT_MEASURED'),
            limitations=['Host API endpoints, not sensor exposure or physical screen latency',
                'First-input latency includes 10-second accumulation; do not sum stage percentiles',
                'Metadata reuse is not pixel comparison or proof of sensor production/drop count',
                'Bounded record checkpoints add I/O overhead; stream FPS includes it; publication is separate',
                'No raw RGB/Depth, landmarks, features, ground-truth labels, subject or device identity logged'])
        if seconds is not None and seconds > 0:
            summary['processed_fps'] = summary['completed_frames']/seconds
            summary['valid_feature_fps'] = summary['feature_success_frames']/seconds
        if self.input_scope=='stored_features':
            summary.update(processed_fps=None,valid_feature_fps=None,fps_status='NOT_MEASURED_STORED_INPUT_REPLAY')
        self.result_summary=summary
        if self.resources is not None and any(device.get('utilization_percent') is not None
                for sample in self.resources.gpu_samples for device in sample.get('devices',[])):
            summary['gpu_usage']='MEASURED_DEVICE_WIDE'
        if self.mode=='off':
            self._finished=True
            return
        if self.resources is not None:
            def resources():
                for kind,rows in [('cpu_ram',self.resources.samples),('gpu',self.resources.gpu_samples)]:
                    for row in rows:
                        yield dict(kind=kind,**row)
            write_rows(self.directory/'resources.jsonl',resources())
        tables=[('segments',self.segments)]
        if self.mode=='detailed':
            tables.insert(0,('frames',self.frames))
        for name, rows in tables:
            write_rows(self.directory/(name+'.jsonl'),rows)
        summary['buffering']={name:rows.status() for name,rows in tables if isinstance(rows,CheckpointList)}
        write_json(self.directory/'summary.json',summary)
        self._finished = True
