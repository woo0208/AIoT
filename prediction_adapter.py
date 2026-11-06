"""Model-independent presentation of explicit prediction events; never predicts.

H9-shaped snapshots are accepted only with the producer's explicit class order.
No primary5/three-class to formal6 conversion is performed.
"""

from dataclasses import asdict, dataclass
import math


FORMAL6 = ('upright', 'forward_head', 'lean_back', 'lean_left', 'lean_right', 'lean_forward')
KOREAN6 = ('정상', '거북목', '상체 후방', '좌측', '우측', '상체 전방')
STATES = ('NEW', 'HOLDING', 'STALE', 'INSUFFICIENT_DATA', 'MODEL_UNAVAILABLE')


@dataclass(frozen=True)
class PredictionView:
    status: str
    class_id: str | None
    posture_name: str | None
    age_ms: float | None
    prediction_id: str | None
    banner: str

    def lines(self):
        age = '--' if self.age_ms is None else f'{self.age_ms:.1f}'
        return [self.banner, f'{self.class_id or "--"}  {self.posture_name or "--"}',
                f'상태: {self.status}', f'예측 나이: {age} ms']


class PredictionAdapter:
    def __init__(self, class_order, *, synthetic=False):
        self.class_order = tuple(class_order)
        if len(self.class_order) not in (3, 5, 6) or len(set(self.class_order)) != len(self.class_order):
            raise ValueError('explicit unique three/five/six-class order required')
        self.synthetic = synthetic
        self._shown = None

    def adapt(self, snapshot=None, *, model_available=True):
        banner = 'SYNTHETIC DEMO / 실제 판정 아님' if self.synthetic else 'DEVELOPMENT ONLY / NOT VALIDATED'
        status = (snapshot or {}).get('status', 'INSUFFICIENT_DATA')
        if not model_available:
            status = 'MODEL_UNAVAILABLE'
        status = {'PREDICTED': 'NEW', 'COLLECTING': 'INSUFFICIENT_DATA'}.get(status, status)
        if status not in STATES:
            raise ValueError('unsupported prediction state')
        display = (snapshot or {}).get('display_prediction')
        if status not in ('NEW', 'HOLDING') or display is None:
            if status in ('NEW', 'HOLDING'):
                status = 'INSUFFICIENT_DATA'
            self._shown = None
            return PredictionView(status, None, None, None, None, banner)
        index = display['prediction_index']
        if type(index) is not int or not 0 <= index < len(self.class_order):
            raise ValueError('class index outside declared producer order')
        if display['prediction_label'] != self.class_order[index]:
            raise ValueError('class label/order mismatch; no label conversion allowed')
        age = float(snapshot['last_prediction_age_ms'])
        if not math.isfinite(age) or age < 0:
            raise ValueError('finite nonnegative prediction age required')
        identity = str(display['prediction_id'])
        if status == 'NEW' and identity == self._shown:
            status = 'HOLDING'
        self._shown = identity
        formal = self.class_order == FORMAL6
        return PredictionView(status, f'P{index}' if formal else str(index),
                              KOREAN6[index] if formal else self.class_order[index], age, identity, banner)


def synthetic_events():
    """H9 snapshot envelope only, with explicit synthetic six-class identities."""
    yield dict(status='MODEL_UNAVAILABLE')
    yield dict(status='COLLECTING')
    for index, label in enumerate(FORMAL6):
        display = dict(prediction_index=index, prediction_label=label, prediction_id=f'synthetic-{index}')
        yield dict(status='PREDICTED', display_prediction=display, last_prediction_age_ms=0)
        yield dict(status='HOLDING', display_prediction=display, last_prediction_age_ms=1000)
        yield dict(status='STALE')
        yield dict(status='INSUFFICIENT_DATA')


def demo_views():
    adapter = PredictionAdapter(FORMAL6, synthetic=True)
    return [asdict(adapter.adapt(event)) for event in synthetic_events()]


def run_synthetic_demo():
    """Opt-in standalone panel. Native Tk text renders Korean without cv2 glyph loss.

    Uses the existing async H9 snapshot envelope; no camera/model/feature code runs.
    """
    import tkinter as tk
    root = tk.Tk()
    root.title('6-class SYNTHETIC DEMO')
    labels = [tk.Label(root, font=('Malgun Gothic', 20), padx=30, pady=8) for _ in range(4)]
    for label in labels:
        label.pack()
    tk.Label(root, text='합성 상태 반복 재생 | Esc: 종료', font=('Malgun Gothic', 12)).pack()
    root.bind('<Escape>', lambda _: root.destroy())
    adapter = PredictionAdapter(FORMAL6, synthetic=True)
    events = list(synthetic_events())
    def update(index=0):
        view = adapter.adapt(events[index % len(events)])
        for widget, line in zip(labels, view.lines()):
            widget.config(text=line)
        root.after(1000, update, index + 1)
    update()
    root.mainloop()


class DemoPredictionPanel:
    """The existing Tk six-class presentation, supplied with real demo events."""

    def __init__(self, mode):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.title('AIoT LR B0 | DEMO_ONLY | ' + mode)
        self.adapter = PredictionAdapter(FORMAL6)
        self.closed = False
        self.labels = [tk.Label(self.root, font=('Malgun Gothic', 19), padx=24, pady=7)
                       for _ in range(7)]
        for label in self.labels:
            label.pack()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda _: self.close())

    def render(self, snapshot, *, fps=0.0, context='', error=''):
        if self.closed:
            return
        view = self.adapter.adapt(snapshot, model_available=not error)
        state = {'NEW': '정상', 'HOLDING': '정상 (HOLDING)',
                 'STALE': '입력 부족 (STALE)', 'INSUFFICIENT_DATA': '입력 부족',
                 'MODEL_UNAVAILABLE': '모델 오류'}[view.status]
        if (snapshot or {}).get('status') == 'COLLECTING':
            state = '분석 중'
        probability = (snapshot or {}).get('probability') if view.class_id else None
        lines = ['DEMO_ONLY · 파일럿 학습 모델 · 연구 성능 검증 아님',
                 f"현재 자세: {view.class_id or '--'}  {view.posture_name or '--'}",
                 f'모델 예측 확률: {probability * 100:.1f}%' if probability is not None else '모델 예측 확률: --',
                 f'현재 처리 FPS: {fps:.1f}', f'상태: {state}',
                 f"예측 경과: {view.age_ms:.0f} ms" if view.age_ms is not None else '예측 경과: --',
                 error or context or 'Esc / 창 닫기: 종료']
        for widget, line in zip(self.labels, lines):
            widget.config(text=line)

    def pump(self):
        if not self.closed:
            self.root.update_idletasks()
            self.root.update()
        return not self.closed

    def close(self):
        if not self.closed:
            self.closed = True
            self.root.destroy()
