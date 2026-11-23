"""Private engineering events; instruction/hold intent never becomes motion truth."""
import copy
import json
from pathlib import Path
import re
import uuid
import time

from capture_six_pilot import LABELS  # Existing research A P0..P5 order, unchanged.
from e0_storage import write_json


EVENT_FORMAT = 'research-b-recording-events/1'
EVENTS = frozenset(('SESSION_START','SESSION_END','RECORDING_START','RECORDING_STOP',
    'IDLE_START','IDLE_END','MEASUREMENT_START','MEASUREMENT_END',
    'POSTURE_INSTRUCTION','POSTURE_HOLD_START','POSTURE_HOLD_END','RECORDING_ERROR'))


def validate_context(participant_id=None, session_label=None, repetition=None):
    if participant_id is not None and not re.fullmatch(r'P[0-9]{2,3}', participant_id):
        raise ValueError('participant-id must be an anonymous Pxx/Pxxx code')
    if session_label not in (None,'S1','S2'):
        raise ValueError('session-label must be S1 or S2')
    if repetition is not None and (type(repetition) is not int or repetition < 1):
        raise ValueError('repetition must be a positive integer')
    return dict(participant_id=participant_id, session_label=session_label, repetition=repetition,
                identity_status='ASSIGNED' if participant_id and session_label else 'UNASSIGNED')


def add_context_arguments(parser):
    parser.add_argument('--participant-id', help='anonymous Pxx/Pxxx code, private sidecar only')
    parser.add_argument('--session-label', choices=('S1','S2'))
    parser.add_argument('--repetition', type=int, help='operator-supplied repeat index')


class SessionEvents:
    def __init__(self, directory, *, context, clock_ns, scope):
        self.directory=Path(directory)
        self.context=validate_context(context.get('participant_id'),context.get('session_label'),context.get('repetition'))
        self.clock_ns=clock_ns;self.scope=scope
        self.session_id='rb_raw_'+uuid.uuid4().hex
        self.started=self.finished=False
        self.stream=None;self.count=0;self.anchor=None
        self.posture=None;self.repetition=self.context['repetition']
        self.transitions=[];self.measurement=None;self.measurements=0
        self.idle=False

    def begin(self):
        if self.started:return
        self.directory.mkdir()  # Exclusive; never appends to an old session.
        self.stream=(self.directory/'events.jsonl').open('x',encoding='utf-8',newline='\n')
        self.started=True
        self.emit('SESSION_START')
        self.emit('IDLE_START');self.idle=True

    def emit(self, kind, **details):
        if kind not in EVENTS or not self.started or self.finished:
            raise ValueError('Invalid event lifecycle/type')
        self.count+=1
        record=dict(format=EVENT_FORMAT,session_id=self.session_id,event_index=self.count,
            event=kind,host_perf_counter_ns=self.clock_ns(),scope=self.scope,
            **{**self.context,'repetition':self.repetition},posture_code=self.posture,
            posture_label=LABELS[int(self.posture[1:])] if self.posture else None,
            segment_id=self.measurement['segment_id'] if self.measurement else None,
            source_anchor=copy.deepcopy(self.anchor),
            anchor_meaning='most recently received input; not the physical motion time',details=details)
        self.stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n');self.stream.flush()
        return record

    def observe_input(self, row, timestamp):
        self.anchor=dict(receive_index=row['receive_index'],host_receive_end_ns=row['receive_end_ns'],
            frameset_timestamp_ms=timestamp,sensors=copy.deepcopy(row.get('raw',{})))

    def instruction(self, code, *, source='operator_instruction_button', repetition=None):
        if code not in tuple(f'P{i}' for i in range(6)):
            raise ValueError('Expected P0..P5')
        if repetition is not None:
            validate_context(repetition=repetition)
            self.repetition=repetition
        previous=self.posture;self.posture=code
        if not self.started:return
        event=self.emit('POSTURE_INSTRUCTION',source=source,
                        instruction_boundary='program instruction variable updated',
                        physical_display_time='NOT_MEASURED',actual_movement_start='UNANNOTATED',
                        target_reached='UNANNOTATED')
        self.transitions.append(dict(transition_id=f'{self.session_id}/instruction_{event["event_index"]}',
            instruction_event_index=event['event_index'],instruction_host_perf_counter_ns=event['host_perf_counter_ns'],
            from_posture=previous,to_posture=code,
            movement_start=dict(status='UNANNOTATED',frame_reference=None),
            target_reached=dict(status='UNANNOTATED',frame_reference=None)))

    def watch_measurement(self, session):
        if not self.started or self.finished:return
        if self.measurement is None and (session.armed or session.active is not None):
            if self.idle:self.emit('IDLE_END');self.idle=False
            self.measurements+=1
            self.measurement=dict(segment_id=f'{self.session_id}/measurement_{self.measurements:04d}',
                                  held=False,e0_segment_index=None)
            self.emit('MEASUREMENT_START',source='E0 armed/active state',status='REQUESTED')
        if self.measurement is None:return
        if session.active is not None and not self.measurement['held']:
            self.measurement.update(held=True,e0_segment_index=session.active['segment_index'])
            self.emit('POSTURE_HOLD_START',e0_segment_index=session.active['segment_index'],
                first_device_ms=session.active['first_device_ms'],
                meaning='measurement window start; not actual movement completion')
        if session.active is None and not session.armed:
            index=self.measurement['e0_segment_index']
            segment=next((s for s in reversed(session.segments) if s['segment_index']==index),{})
            self._end_measurement(segment.get('status','CANCELLED_BEFORE_INPUT'),segment.get('reason'),
                                  resume_idle=True)

    def _end_measurement(self,status,reason,*,resume_idle):
        if self.measurement is None:return
        if self.measurement['held']:
            self.emit('POSTURE_HOLD_END',status=status,reason=reason,
                      e0_segment_index=self.measurement['e0_segment_index'])
        self.emit('MEASUREMENT_END',status=status,reason=reason,
                  e0_segment_index=self.measurement['e0_segment_index'])
        self.measurement=None
        if resume_idle:self.emit('IDLE_START');self.idle=True

    def finish(self, *, status, reason, raw_summary, files):
        if not self.started or self.finished:return
        try:
            if self.measurement:self._end_measurement('INTERRUPTED',reason,resume_idle=False)
            if self.idle:self.emit('IDLE_END');self.idle=False
            self.emit('SESSION_END',status=status,reason=reason)
        finally:
            self.stream.close()
        template=dict(format='research-b-motion-annotation/1',session_id=self.session_id,
            annotation_status='UNANNOTATED',source_event_file='events.jsonl',
            notes=['Instruction time and measurement/hold boundaries are not motion truth.',
                   'Write reviewed annotations to a NEW file; preserve this template.'],
            transitions=self.transitions)
        write_json(self.directory/'annotations_template.json',template)
        from raw_rgbd_recording import _sha
        inventory=dict(files)
        inventory['recording_metadata/events.jsonl']=_sha(self.directory/'events.jsonl')
        inventory['recording_metadata/annotations_template.json']=_sha(self.directory/'annotations_template.json')
        document=dict(format='research-b-raw-session/1',session_id=self.session_id,scope=self.scope,
            context=self.context,status=status,reason=reason,event_count=self.count,
            configuration=dict(raw_format=raw_summary['format'],initial_recording=raw_summary['initial'],
                               event_format=EVENT_FORMAT),
            host_clock=dict(api='time.perf_counter_ns' if self.clock_ns is time.perf_counter_ns else 'injected_test_clock',
                            relation='Host API observations; never equate directly with sensor clock domains'),
            recording=raw_summary,files=inventory,
            replay=dict(status='NOT_CHECKED_AT_CAPTURE',replayable_frames=None),
            privacy='Private device/participant metadata; never commit or push',
            source_sha256={name:_sha(Path(__file__).with_name(name)) for name in
                ('raw_rgbd_events.py','raw_rgbd_recording.py','raw_rgbd_replay.py',
                 'posture_geometry_probe.py','e0_panel.py','e0_guided_panel.py')},
            hardware_validation='NOT_TESTED_HARDWARE')
        write_json(self.directory/'session_manifest.json',document)
        self.finished=True


def validate_annotations(session_directory, annotation_path, *, allow_incomplete=False):
    """Read-only linkage check for future manually reviewed motion annotations."""
    from raw_rgbd_recording import _sha
    root=Path(session_directory)
    manifest=root/'recording_metadata/session_manifest.json'
    source=json.loads(manifest.read_text(encoding='utf-8'))
    data=json.loads(Path(annotation_path).read_text(encoding='utf-8'))
    if (data.get('session_id')!=source['session_id']
            or data.get('source_manifest_sha256')!=_sha(manifest)
            or data.get('format')!='research-b-motion-annotation/1'):
        raise ValueError('Annotation session/hash/format mismatch')
    template=json.loads((root/'recording_metadata/annotations_template.json').read_text(encoding='utf-8'))
    expected={t['transition_id']:t for t in template['transitions']}
    if len(data['transitions'])!=len(expected) or {t['transition_id'] for t in data['transitions']}!=set(expected):
        raise ValueError('Annotation transition inventory mismatch')
    from raw_rgbd_replay import RawSessionReader
    reader=RawSessionReader(root,allow_incomplete=allow_incomplete)
    refs={(p.record['clip'],p.record['frame_index']):p.record for p in reader.packets()}
    for transition in data['transitions']:
        original=expected[transition['transition_id']]
        for key in ('instruction_event_index','instruction_host_perf_counter_ns','from_posture','to_posture'):
            if transition.get(key)!=original[key]:raise ValueError('Instruction history was changed')
        positions={}
        for key in ('movement_start','target_reached'):
            value=transition[key]
            if value['status']=='UNANNOTATED':
                if value.get('frame_reference') is not None:raise ValueError('Unannotated frame must be null')
            elif value['status']=='MANUAL_REVIEW_CONFIRMED':
                ref=value['frame_reference']
                record=refs.get((ref.get('clip'),ref.get('frame_index')))
                if record is None or ref.get('sha256')!=record['sha256']:
                    raise ValueError('Annotation must reference the original frame/hash')
                sensor=record['sensors'].get(ref.get('stream'))
                if sensor is None or sensor.get('status')!='MEASURED':
                    raise ValueError('Annotation needs a measured color/depth source clock')
                for field,source_field in (('timestamp_ms','timestamp_ms'),('timestamp_domain','timestamp_domain'),('frame_number','number')):
                    if ref.get(field)!=sensor.get(source_field):
                        raise ValueError('Annotation clock/frame number differs from original')
                positions[key]=record['receive_index']
            else:raise ValueError('Unsupported movement annotation status')
        if len(positions)==2 and positions['target_reached']<positions['movement_start']:
            raise ValueError('Target reached precedes movement start')
    return dict(status='LINKAGE_VALIDATED',transitions=len(expected),
                time_resolution='Reviewed source frame boundary; no sub-frame accuracy asserted',
                motion_accuracy='NOT_EVALUATED; annotation truth requires manual review')
