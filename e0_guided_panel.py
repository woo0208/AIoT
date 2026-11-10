"""In-memory six-posture guide for E0; no participant or posture labels exported."""
from e0_panel import OperatorControl, OperatorPanel


NAMES = ('정상', '거북목', '상체 후방', '상체 좌측', '상체 우측', '상체 전방')
KEY_TEXT = ('Space', 'H', '↓', '←', '→', '↑')
KEYS = {'space': 0, 'h': 1, 'Down': 2, 'Left': 3, 'Right': 4, 'Up': 5}


class GuidedControl(OperatorControl):
    def __init__(self, session):
        super().__init__(session)
        self.completed = 0
        self._counted = len(session.segments)
        self._time_issue_seen = False
        self.normal_ready = False
        self.selected = None
        self.message = '정상으로 복귀한 뒤 Space를 누르세요.'
        self.progress = dict(protocol='e0-six-blocks-five-holds/1', target_holds=30,
                             completed_holds=0, eligible_holds=0)
        session.environment_metadata['guided_operation'] = self.progress

    @property
    def expected(self):
        return self.completed // 5 if self.completed < 30 else None

    def choose(self, posture):
        if not self.running or self.expected is None:
            return
        if self.session.active is not None or self.session.armed:
            self.cancel()
        if posture == 0:
            self.normal_ready = True
        self.selected = None
        if not self.normal_ready:
            self.message = '먼저 정상으로 복귀한 뒤 Space를 누르세요.'
        elif posture != self.expected:
            self.message = '정상 복귀 확인. 화면의 목표 자세 키를 누르세요.'
        else:
            self.selected = posture
            self.message = '목표 자세를 안정시킨 뒤 Enter / 시작을 누르세요.'

    def start(self):
        # Repeated Enter during a hold never cancels or advances the schedule.
        if self.session.active is not None or self.session.armed:
            return False
        if not self.normal_ready or self.selected != self.expected:
            self.message = '정상 복귀 Space → 목표 자세 키 → Enter 순서로 진행하세요.'
            return False
        started = super().start()
        if started:
            self._time_issue_seen = False
            self.message = '10초 유지 중. 자세 변경·중단은 T / 취소.'
        return started

    def cancel(self):
        super().cancel()
        self.normal_ready = False
        self.selected = None
        self.message = '취소됨. 같은 회차를 정상 복귀 Space부터 다시 준비하세요.'

    def poll(self):
        super().poll()
        while self._counted < len(self.session.segments):
            segment = self.session.segments[self._counted]
            if segment['status'] in ('COLLECTING', 'AGGREGATING'):
                break
            self._counted += 1
            if segment['status'] in ('PREDICTED', 'INELIGIBLE'):
                # Advance by completed time window, never by prediction correctness.
                self.completed += 1
                self.progress['completed_holds'] = self.completed
                self.progress['eligible_holds'] += bool(segment.get('eligible'))
                self.normal_ready = False
                self.selected = None
                self.message = '10초 완료. 정상으로 복귀한 뒤 Space를 누르세요.'
            elif segment['status'] == 'INCOMPLETE':
                self.normal_ready = False
                self.selected = None
        if self.session.last_segment_issue and not self._time_issue_seen:
            self._time_issue_seen = True
            self.normal_ready = False
            self.selected = None
            self.message = '장치 시간 이상으로 구간 취소. 정상 복귀 Space부터 다시 시작하세요.'
        if self.completed == 30:
            self.state = 'DONE'
            self.running = False
        return self.running


class GuidedPanel(OperatorPanel):
    def __init__(self, session, *, subject, tk_module=None):
        if subject not in ('P01', 'P02'):
            raise ValueError('Use an anonymous operator label P01 or P02')
        if tk_module is None:
            import tkinter as tk_module
        self.control = GuidedControl(session)
        self.root = tk_module.Tk()
        self.root.title(f'{subject} — E0 실행 성능 측정 / 6자세 × 5회')
        self.root.geometry('820x540')
        self.root.minsize(760, 500)
        self.target = tk_module.StringVar()
        self.status = tk_module.StringVar()
        self.detail = tk_module.StringVar()
        for variable, size in ((self.target, 22), (self.status, 15), (self.detail, 13)):
            tk_module.Label(self.root, textvariable=variable, font=('Malgun Gothic', size),
                            wraplength=780).pack(pady=10)
        tk_module.Label(self.root, text='Space 정상 / H 거북목 / ↓ 후방 / ← 좌측 / → 우측 / ↑ 전방\n'
                        '매 구간: 정상 복귀 Space → 목표 자세 선택 → 안정 후 Enter\n'
                        '10초 자동 완료 / T·Esc 취소 / Q 종료\n'
                        '전환 중 구간 집계는 정지하며 전체 성능 계측은 계속됩니다.',
                        font=('Malgun Gothic', 12), justify='left').pack(pady=10)
        for text, action in (('시작 10초 (Enter)', self.control.start),
                             ('구간 취소 (T)', self.control.cancel), ('종료 (Q)', self.control.close)):
            tk_module.Button(self.root, text=text, command=action,
                             font=('Malgun Gothic', 13)).pack(pady=4)
        self.pressed = set()
        self.root.bind('<KeyPress>', self._key)
        self.root.bind('<KeyRelease>', lambda event: self.pressed.discard(event.keysym))
        self.root.bind('<FocusOut>', self._focus_out)
        self.root.protocol('WM_DELETE_WINDOW', self.control.close)

    def _focus_out(self, event):
        self.pressed.clear()
        if self.control.session.active is not None or self.control.session.armed:
            self.control.cancel()

    def _key(self, event):
        key = event.keysym
        posture = KEYS.get(key, KEYS.get(key.lower()))
        if posture is not None:
            if key not in self.pressed:
                self.pressed.add(key)
                self.control.choose(posture)
            return 'break'
        return super()._key(event)

    def poll(self):
        with self.control.session.timing.stage('ui.tk_idle'):
            self.root.update_idletasks()
        with self.control.session.timing.stage('ui.tk_update'):
            self.root.update()
        running = self.control.poll()
        expected = self.control.expected
        self.target.set('30구간 완료' if expected is None else
                        f'P{expected} {NAMES[expected]} [{KEY_TEXT[expected]}] — {self.control.completed % 5 + 1}/5회')
        self.status.set(f'{self.control.state} | 완료 {self.control.completed}/30')
        active = self.control.session.active
        elapsed = (active['last_device_ms'] - active['first_device_ms']) / 1000 if active else None
        self.detail.set(self.control.message + (f'\n측정 {elapsed:.1f}/10.0초' if elapsed is not None else ''))
        return running
