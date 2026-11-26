"""In-memory six-posture guide for E0; no participant or posture labels exported."""
from e0_panel import OperatorControl, OperatorPanel


NAMES = ('정상', '거북목', '상체 후방', '상체 좌측', '상체 우측', '상체 전방')
KEY_TEXT = ('Space', 'H', '↓', '←', '→', '↑')
KEYS = {'space': 0, 'h': 1, 'Down': 2, 'Left': 3, 'Right': 4, 'Up': 5}


class GuidedControl(OperatorControl):
    def __init__(self, session, *, single_round=False):
        super().__init__(session)
        self.single_round = single_round
        self.holds_per_posture = 1 if single_round else 5
        self.target_holds = len(NAMES) * self.holds_per_posture
        self.completed = 0
        self._counted = len(session.segments)
        self._time_issue_seen = False
        self.normal_ready = False
        self.selected = None
        self.message = ('미리보기를 확인한 뒤 원본 녹화 시작을 누르세요.' if single_round
                        else '정상으로 복귀한 뒤 Space를 누르세요.')
        self.progress = dict(protocol='research-b-guided-six/1' if single_round else 'e0-six-blocks-five-holds/1',
                             target_holds=self.target_holds,
                             completed_holds=0, eligible_holds=0)
        session.environment_metadata['guided_operation'] = self.progress
        self.instruction_target = None

    @property
    def recording_ready(self):
        return not self.single_round or self.session.raw_recording.requested

    @property
    def expected(self):
        return self.completed // self.holds_per_posture if self.completed < self.target_holds else None

    def record_target(self):
        if (self.single_round and self.running and self.recording_ready and
                self.expected is not None and self.expected != self.instruction_target):
            self.session.raw_recording.instruction(f'P{self.expected}', source='guided_target_display')
            if self.instruction_target is None and self.selected is None:
                self.message = '정상으로 복귀한 뒤 Space를 누르세요.'
            self.instruction_target = self.expected

    def choose(self, posture):
        # Tk can deliver a key before its next poll sees a just-completed hold.
        if self.single_round:
            self.poll()
        if not self.running or self.expected is None or not self.recording_ready:
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
        if self.single_round:
            self.poll()
        if not self.running or not self.recording_ready or self.session.active is not None or self.session.armed:
            return False
        if not self.normal_ready or self.selected != self.expected:
            self.message = '정상 복귀 Space → 목표 자세 키 → Enter 순서로 진행하세요.'
            return False
        self.record_target()
        started = super().start()
        if started:
            self._time_issue_seen = False
            self.message = ('첫 측정 프레임 대기 중. 중단은 T / 취소.' if self.single_round
                            else '10초 유지 중. 자세 변경·중단은 T / 취소.')
        return started

    def cancel(self):
        if self.single_round and not self.recording_ready:
            return
        super().cancel()
        self.normal_ready = False
        self.selected = None
        self.message = '취소됨. 같은 회차를 정상 복귀 Space부터 다시 준비하세요.'

    def poll(self):
        if self.single_round and not self.running:
            return False
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
        if self.completed == self.target_holds:
            self.state = 'DONE'
            self.running = False
            if self.single_round:
                self.message = '여섯 자세 측정 완료. 원본 저장 종료 및 검증 중입니다.'
        return self.running


class GuidedPanel(OperatorPanel):
    def __init__(self, session, *, subject, tk_module=None, single_round=False):
        raw=getattr(session,'raw_recording',None)
        if subject is None and single_round and raw is not None and raw.events is not None and all(
                raw.events.context[key] is None for key in ('participant_id', 'session_label', 'repetition')):
            display_subject = '엔지니어링 시험 (참가자 미등록)'
        elif subject in ('P01', 'P02'):
            display_subject = subject
        else:
            raise ValueError('Use P01 or P02, or an unregistered single-round engineering session')
        if raw is not None and raw.events is not None and raw.events.context['participant_id'] not in (None,subject):
            raise ValueError('Guided display and private participant identity must match')
        if tk_module is None:
            import tkinter as tk_module
        self.control = GuidedControl(session, single_round=single_round)
        self._close_reason = 'panel_closed'
        self.root = tk_module.Tk()
        self.root.title(f'{display_subject} — P0~P5 안내 촬영' if single_round
                        else f'{subject} — E0 실행 성능 측정 / 6자세 × 5회')
        self.root.geometry('820x540')
        self.root.minsize(760, 500)
        self.target = tk_module.StringVar()
        self.status = tk_module.StringVar(value='PREVIEW') if single_round else tk_module.StringVar()
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
                             ('구간 취소 (T)', self.control.cancel), ('종료 (Q)', self._abort)):
            button = tk_module.Button(self.root, text=text, command=action, font=('Malgun Gothic', 13))
            if single_round:
                # A widget binding runs before Tk's Button class schedules an invoke.
                button.bind('<KeyPress-space>', self._key)
            button.pack(pady=4)
        self._add_raw_controls(tk_module)
        self._raw_instruction_key=None
        if self.raw_recording is not None:
            if single_round:
                self.raw_button.bind('<KeyPress-space>', self._key)
            self.root.geometry('820x660')
            self.root.minsize(760, 640)
        self.pressed = set()
        self.root.bind('<KeyPress>', self._key)
        self.root.bind('<KeyRelease>', lambda event: self.pressed.discard(event.keysym))
        self.root.bind('<FocusOut>', self._focus_out)
        self.root.protocol('WM_DELETE_WINDOW', self.control.close)

    def _abort(self):
        self._close_reason = 'user_aborted'
        self.control.close()

    def stop_reason(self):
        return 'guided_completed' if self.control.state == 'DONE' else self._close_reason

    def _focus_out(self, event):
        self.pressed.clear()
        if self.control.session.active is not None or self.control.session.armed:
            self.control.cancel()

    def _key(self, event):
        key = event.keysym
        if key.lower() == 'q':
            self._close_reason = 'user_aborted'
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
        if self.control.single_round:
            self.control.record_target()
            target = ('6구간 완료' if expected is None else
                      f'P{expected} {NAMES[expected]} [{KEY_TEXT[expected]}]' if self.control.recording_ready else '미리보기 / 촬영 준비')
            self.target.set(target)
        else:
            self.target.set('30구간 완료' if expected is None else
                            f'P{expected} {NAMES[expected]} [{KEY_TEXT[expected]}] — {self.control.completed % 5 + 1}/5회')
        token=(expected,self.control.completed)
        if not self.control.single_round and self.raw_recording is not None and expected is not None and token!=self._raw_instruction_key:
            self.raw_recording.instruction(f'P{expected}',source='guided_target_display',
                                           repetition=self.control.completed%5+1)
            self._raw_instruction_key=token
        active = self.control.session.active
        stage = self.control.state
        if self.control.single_round and self.control.running:
            if not self.control.recording_ready:
                stage = 'READY' if self.raw_recording.exchange.preview_pairs else 'PREVIEW'
            elif active is not None:
                stage = 'POSTURE_MEASURING'
            elif self.control.session.armed:
                stage = 'RECORDING / 측정 시작 대기'
            else:
                stage = 'POSTURE_TRANSITION' if self.control.completed else 'RECORDING'
        elif self.control.single_round and stage == 'DONE':
            stage = 'GUIDED_COMPLETED / FINALIZING'
        self.status.set(f'{stage} | 완료 {self.control.completed}/{self.control.target_holds}')
        elapsed = (active['last_device_ms'] - active['first_device_ms']) / 1000 if active else None
        message = ('10초 유지 중. 자세 변경·중단은 T / 취소.' if self.control.single_round and active is not None
                   else self.control.message)
        self.detail.set(message + (f'\n측정 {elapsed:.1f}/10.0초' if elapsed is not None else ''))
        self._update_raw_controls()
        if self.control.single_round and self.control.state == 'DONE':
            self.root.update_idletasks()
        return running
