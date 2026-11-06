"""DEMO_ONLY LR B0 UI. Default replay uses only the authorized 24 aggregates.

Live geometry comes from run_probe; no recording, evaluation or model selection.
The existing H9 joint support and 4s/1s/2s engineering timing are retained.
"""

import argparse
import ast
from collections import deque
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from f1_sample_aggregator import H9_FEATURE_NAMES, HFrameRecord, aggregate_h5_h9_sample
from h9_time_window import WINDOW_MS, UPDATE_MS, STALE_AFTER_MS
from prediction_adapter import FORMAL6, DemoPredictionPanel


ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'analysis/research_h9_algorithms_20261029_7c3e91/samples.json'
FACTORY = DATA.parent / 'compare_fixed.py'
MODEL = ROOT / 'models/lr_b0_demo_only.pkl'
DATA_SHA256 = '69d64dca60a1f70ff60cd9663febc52b19d0e26540ffc97508ff3178a01deb20'
FEATURE_ORDER = H9_FEATURE_NAMES[:8]
FEATURE_UNITS = ('1', '1', 'deg', '1', '1', 'm', 'm', 'm')
WINDOW_S, UPDATE_S, STALE_S = (float(v) / 1000 for v in (WINDOW_MS, UPDATE_MS, STALE_AFTER_MS))


def pilot_data():
    raw = DATA.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise ValueError('Authorized pilot aggregate hash mismatch')
    data = json.loads(raw.decode('utf-8-sig'))
    if (tuple(data['feature_order']) != H9_FEATURE_NAMES or tuple(data['class_order']) != FORMAL6
            or len(data['sample_keys']) != 24 or set(data['subjects']) != {'P01', 'P02'}):
        raise ValueError('Expected original 24-segment, six-class H9 pilot')
    matrix = np.asarray(data['matrix'], dtype=float)
    if matrix.shape != (24, 9) or not np.isfinite(matrix).all():
        raise ValueError('Invalid aggregate features; no imputation')
    for person in ('P01', 'P02'):
        labels = [y for y, p in zip(data['labels'], data['subjects']) if p == person]
        if np.bincount(labels, minlength=6).tolist() != [2] * 6:
            raise ValueError('Missing pilot classes')
    return data, matrix[:, :8], np.asarray(data['labels'])


def fixed_lr():
    # Reuse the exact existing constructor without executing its experiment CLI.
    node = next(n for n in ast.parse(FACTORY.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'make_model')
    namespace = {'LogisticRegression': LogisticRegression}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(FACTORY), 'exec'), namespace)
    return namespace['make_model']('Logistic-Regression', 0)


def load_or_build_model():
    if not MODEL.exists():
        _, matrix, labels = pilot_data()
        scaler = StandardScaler().fit(matrix)
        model = fixed_lr().fit(scaler.transform(matrix), labels)
        payload = dict(scope='DEMO_ONLY', format='lr-b0-demo/1', model=model, scaler=scaler,
                       feature_order=FEATURE_ORDER, feature_units=FEATURE_UNITS,
                       class_order=FORMAL6, training_samples=24, source_sha256=DATA_SHA256)
        with MODEL.open('xb') as stream:
            pickle.dump(payload, stream, protocol=5)
        print('Saved DEMO_ONLY LR B0: 24 pilot aggregates; no accuracy evaluation.', flush=True)
    # Local, application-created pickle only; never accepts a downloaded model path.
    with MODEL.open('rb') as stream:
        payload = pickle.load(stream)
    if (payload.get('scope') != 'DEMO_ONLY' or payload.get('format') != 'lr-b0-demo/1'
            or tuple(payload.get('feature_order', ())) != FEATURE_ORDER
            or tuple(payload.get('feature_units', ())) != FEATURE_UNITS
            or tuple(payload.get('class_order', ())) != FORMAL6
            or payload.get('source_sha256') != DATA_SHA256 or payload.get('training_samples') != 24):
        raise ValueError('Wrong demo model identity/order/units')
    model, scaler = payload['model'], payload['scaler']
    if (not isinstance(model, LogisticRegression) or not isinstance(scaler, StandardScaler)
            or model.n_features_in_ != 8 or scaler.n_features_in_ != 8
            or model.classes_.tolist() != list(range(6)) or int(scaler.n_samples_seen_) != 24
            or model.get_params() != fixed_lr().get_params()):
        raise ValueError('Wrong LR B0 preprocessing or classes')
    return model, scaler


class DemoInference:
    """One shared LR/scaler and explicit freshness state for replay/live."""

    def __init__(self, model, scaler, *, clock=time.monotonic):
        self.model, self.scaler, self.clock = model, scaler, clock
        self.current = dict(status='COLLECTING')
        self.generated = None
        self.sequence = 0
        self.error = ''
        self.processed = deque()

    def clear(self, state):
        self.current = dict(status=state)
        self.generated = None

    def mark_input(self, now):
        self.processed.append(now)
        while len(self.processed) > 2 and self.processed[1] < now - 1:
            self.processed.popleft()

    def fps(self):
        now = self.clock()
        if not self.processed or now - self.processed[-1] >= STALE_S:
            return 0.0
        span = now - self.processed[0]
        return (len(self.processed) - 1) / span if span > 0 else 0.0

    def predict(self, values):
        vector = np.asarray(values, dtype=float)
        if vector.shape != (8,) or not np.isfinite(vector).all():
            self.clear('INSUFFICIENT_DATA')
            return
        try:
            probs = self.model.predict_proba(self.scaler.transform(vector.reshape(1, 8)))[0]
            if probs.shape != (6,) or not np.isfinite(probs).all():
                raise ValueError('Invalid model probabilities')
            index = int(self.model.classes_[int(np.argmax(probs))])
            self.sequence += 1
            self.generated = self.clock()
            self.current = dict(status='PREDICTED', last_prediction_age_ms=0,
                probability=float(probs[index]), display_prediction=dict(
                    prediction_id=f'lr-demo-{self.sequence}', prediction_index=index,
                    prediction_label=FORMAL6[index]))
        except Exception as exc:
            self.error = str(exc)
            self.clear('MODEL_UNAVAILABLE')

    def snapshot(self):
        if self.generated is not None:
            age = self.clock() - self.generated
            if age >= STALE_S:
                self.clear('STALE')
            else:
                self.current['last_prediction_age_ms'] = age * 1000
        return self.current


class LiveAggregates:
    """Select existing geometry; aggregate original H9 support before dropping F9."""

    def __init__(self, inference):
        self.inference = inference
        self.frames = deque()
        self.started = self.last_input = self.next_due = None
        self.version = 0
        self.evaluated = -1
        self.latest_valid = False

    def accept(self, frame):
        now = self.inference.clock()
        if self.last_input is not None and now - self.last_input >= STALE_S:
            self.frames.clear()
            self.started = None
            self.inference.clear('COLLECTING')
        if self.started is None:
            self.started, self.next_due = now, now + WINDOW_S
        # Missing observations stay None and still count in the coverage denominator.
        record = HFrameRecord(analysis_run_id='lr-demo-live', recording_id='lr-demo-live',
            frame_index=frame.frame_index, subject='unlabelled', round=None, step='live-window',
            label='unlabelled', features={n: frame.result.features[n] for n in H9_FEATURE_NAMES})
        self.frames.append((now, record))
        while self.frames and self.frames[0][0] <= now - WINDOW_S:
            self.frames.popleft()
        self.version += 1
        self.last_input = now
        self.latest_valid = all(v is not None for v in record.features.values())
        self.inference.mark_input(now)
        if not self.latest_valid:
            self.inference.clear('INSUFFICIENT_DATA')

    def poll(self):
        now = self.inference.clock()
        if self.last_input is None:
            return self.inference.snapshot()
        if now - self.last_input >= STALE_S:
            self.frames.clear()
            self.started = None
            self.inference.clear('STALE')
        elif self.latest_valid and self.started is not None and now >= self.next_due:
            self.next_due = now + UPDATE_S
            if self.evaluated == self.version:
                self.inference.clear('INSUFFICIENT_DATA')
            else:
                while self.frames and self.frames[0][0] <= now - WINDOW_S:
                    self.frames.popleft()
                sample = aggregate_h5_h9_sample(r for _, r in self.frames) if self.frames else None
                self.evaluated = self.version
                if sample is not None and sample.eligible:
                    self.inference.predict(sample.ordered_values('H9')[:8])
                else:
                    self.inference.clear('INSUFFICIENT_DATA')
        return self.inference.snapshot()


def run_replay(panel, inference):
    data, matrix, _ = pilot_data()
    order = sorted(range(24), key=lambda i: (data['subjects'][i], int(data['sample_keys'][i][2])))
    position = 0
    context = 'REPLAY_DEMO · 집계값 순차 재생 · 카메라 사용 안 함'

    def feed():
        nonlocal position, context
        if panel.closed:
            return
        i = order[position % len(order)]
        inference.mark_input(inference.clock())
        inference.predict(matrix[i])
        context = f"REPLAY_DEMO · {data['subjects'][i]} / 구간 {data['sample_keys'][i][2]} · Esc: 종료"
        print(f"REPLAY {position+1}: {context} -> {inference.current.get('display_prediction')}", flush=True)
        position += 1
        panel.root.after(1000, feed)

    def redraw():
        if not panel.closed:
            panel.render(inference.snapshot(), fps=inference.fps(), context=context, error=inference.error)
            panel.root.after(100, redraw)

    panel.root.after(500, feed)
    redraw()
    panel.root.mainloop()


def run_live(panel, inference, *, nonhuman_only):
    if not nonhuman_only:
        raise ValueError('LIVE_D455 is restricted to --nonhuman-only while IRB/operational release is on HOLD')
    import posture_geometry_probe as probe
    live = LiveAggregates(inference)

    def poll():
        panel.render(live.poll(), fps=inference.fps(), error=inference.error,
                     context='LIVE_D455 · 비인체 입력 확인 전용 · 사람 대상 시험 금지 · Esc: 종료')
        return panel.pump()

    # No CSV/video/timing output. Existing D455/MediaPipe/geometry and cleanup.
    probe.run_probe(frame_callback=live.accept, ui_poll=poll)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('REPLAY_DEMO', 'LIVE_D455'), default='REPLAY_DEMO')
    parser.add_argument('--nonhuman-only', action='store_true',
                        help='LIVE only: operator confirms nonhuman scene; does not release IRB HOLD')
    args = parser.parse_args(argv)
    if args.mode == 'LIVE_D455' and not args.nonhuman_only:
        parser.error('LIVE_D455 requires --nonhuman-only; human testing remains prohibited')
    panel = DemoPredictionPanel(args.mode)
    try:
        panel.render(dict(status='COLLECTING'), context='DEMO_ONLY 모델 준비 중')
        if not panel.pump():
            return 0
        model, scaler = load_or_build_model()
        inference = DemoInference(model, scaler)
        if args.mode == 'REPLAY_DEMO':
            run_replay(panel, inference)
        else:
            run_live(panel, inference, nonhuman_only=args.nonhuman_only)
    except Exception as exc:
        print(f'DEMO ERROR: {exc}', flush=True)
        if not panel.closed:
            panel.render(dict(status='MODEL_UNAVAILABLE'), error=str(exc))
            panel.root.mainloop()
        return 1
    finally:
        panel.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
