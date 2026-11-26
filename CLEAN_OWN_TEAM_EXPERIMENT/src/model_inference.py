from collections import Counter
import math
import time
import hashlib
from pathlib import Path
import pickle
import re
import warnings
import numpy as np
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.utils.validation import check_is_fitted
from aggregation import H9_FEATURE_NAMES, HFrameRecord, aggregate_h5_h9_sample

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

class ModelNotReady(ValueError):
    pass

def component_sha256(value):
    """Fingerprint of protocol-5 component serialization; no model bytes exported."""
    return hashlib.sha256(pickle.dumps(value,protocol=5)).hexdigest()

def load_fs3(path, expected_sha256, feature_ids, *, expected_model_sha256=None, expected_scaler_sha256=None):
    if tuple(feature_ids)!=FEATURE_IDS or not re.fullmatch('[0-9a-f]{64}',expected_sha256 or ''):
        raise ModelNotReady('MODEL_NOT_READY: binding/order')
    try:
        raw=Path(path).read_bytes()
        artifact_sha=hashlib.sha256(raw).hexdigest()
        if artifact_sha!=expected_sha256:raise ValueError('hash mismatch')
        # Only explicitly bound, known local research artifacts are accepted.
        with warnings.catch_warnings():
            warnings.simplefilter('error',InconsistentVersionWarning)
            model,scaler=pickle.loads(raw)
        validate_model(model,scaler)
        if getattr(model,'fit_status_',0)!=0:raise ValueError('fit not converged')
        model_sha,scaler_sha=component_sha256(model),component_sha256(scaler)
        if expected_model_sha256 is not None and expected_model_sha256!=model_sha:raise ValueError('component mismatch')
        if expected_scaler_sha256 is not None and expected_scaler_sha256!=scaler_sha:raise ValueError('component mismatch')
        count=int(scaler.n_samples_seen_)
    except Exception as exc:
        raise ModelNotReady('MODEL_NOT_READY: '+type(exc).__name__) from None
    return model,scaler,dict(status='MODEL_READY',artifact_sha256=artifact_sha,
        model_sha256=model_sha,scaler_sha256=scaler_sha,component_hash_method='pickle-protocol-5',
        feature_ids=list(FEATURE_IDS),training_samples=count,
        settings='SVM-FS3-V0-T0; no refit',purpose='EXISTING_ARTIFACT; live selection not implied')

class WindowInference:
    """E0 device-time segment and prediction methods with in-memory observations."""
    def __init__(self, model, scaler, timing):
        self.model, self.scaler, self.timing = model, scaler, timing
        self.clock_ns = time.perf_counter_ns
        self.mode = 'summary'
        self.segments, self.records = [], []
        self.armed = self._finished = False
        self.active = self.last_segment_issue = None
        self._last_index = 0
        self._segment_time_failures = Counter()

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
