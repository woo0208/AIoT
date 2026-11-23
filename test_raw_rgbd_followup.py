"""Research B event/integrity/replay tests: synthetic sources, no physical camera."""
import copy
from contextlib import redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

import numpy as np
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler

from e0_fs3 import E0Session
from e0_panel import OperatorPanel,OperatorControl
from e0_guided_panel import GuidedPanel
import raw_rgbd_recording as raw
import raw_rgbd_replay as replay
from raw_rgbd_events import validate_context,validate_annotations
from test_e0_fs3 import Clock,estimators
from test_frame_provenance import child,pair
import test_raw_rgbd_recording as helpers


CONTEXT=dict(participant_id='P03',session_label='S1',repetition=2)


def events_at(session):
    return [json.loads(line) for line in (session/'recording_metadata/events.jsonl').read_text(encoding='utf-8').splitlines()]


class EventRecordingTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.session=self.root/'session';self.session.mkdir()
        self.clock=Clock()
        self.c=raw.RawRecordingControl(self.session/'raw_rgbd',initial='off',
            scope='SYNTHETIC_STRUCTURAL_TEST_ONLY',session_context=CONTEXT,clock_ns=self.clock)
        self.c.bind(helpers.metadata);self.c.begin_session()

    def tearDown(self):
        self.c.finish()

    def capture(self,index,stamp,*,number=None,missing=None):
        number=index if number is None else number
        frames=pair(None if missing=='color' else child(number,stamp),
                    None if missing=='depth' else child(number,stamp,stream='depth',uid=2))
        row=dict(receive_index=index,receive_end_ns=self.clock(),raw={
            'rgb':raw.snapshot(frames.get_color_frame()),'depth':raw.snapshot(frames.get_depth_frame())})
        self.c.observe_input(frames,row)
        self.c.capture(frames,row)

    def complete(self):
        self.c.set_enabled(True);self.c.instruction('P0');self.capture(1,100.)
        self.clock.add_ms(10);self.c.instruction('P1');self.capture(2,200.)
        self.c.set_enabled(False);self.c.finish()

    def test_off_records_session_idle_events_without_creating_raw_arrays(self):
        self.c.finish()
        records=events_at(self.session)
        self.assertEqual([r['event'] for r in records],['SESSION_START','IDLE_START','IDLE_END','SESSION_END'])
        self.assertFalse((self.session/'raw_rgbd').exists())
        verified=replay.verify_replay(self.session)
        self.assertEqual(verified['decoded']['replayable_frames'],0)
        self.assertTrue(all(r['participant_id']=='P03' and r['session_label']=='S1' for r in records))

    def test_recording_off_is_independent_of_measurement_and_hold_boundaries(self):
        s=NS(armed=True,active=None,segments=[])
        self.c.observe_measurement(s)
        self.c.set_enabled(True);self.capture(1,100.)
        s.active=dict(segment_index=1,first_device_ms=100.,status='COLLECTING');s.armed=False
        s.segments.append(s.active);self.c.observe_measurement(s)
        self.c.set_enabled(False)
        self.assertIsNotNone(s.active)
        before=events_at(self.session)
        self.assertNotIn('MEASUREMENT_END',[r['event'] for r in before])
        s.active['status']='PREDICTED';s.active=None
        self.c.observe_measurement(s);self.c.finish()
        records=events_at(self.session);types=[r['event'] for r in records]
        self.assertLess(types.index('RECORDING_STOP'),types.index('POSTURE_HOLD_END'))
        self.assertIn('MEASUREMENT_START',types);self.assertIn('MEASUREMENT_END',types)
        self.assertEqual(next(r for r in records if r['event']=='POSTURE_HOLD_START')['details']['first_device_ms'],100.)
        frames=list(replay.RawSessionReader(self.session).packets())
        self.assertEqual(frames[0].record['receive_index'],1)
        self.assertGreater(frames[0].record['preceding_event_index'],1)

    def test_instruction_motion_times_stay_unannotated_and_source_anchors_are_explicit(self):
        self.complete()
        template=json.loads((self.session/'recording_metadata/annotations_template.json').read_text())
        self.assertEqual(len(template['transitions']),2)
        self.assertEqual(template['transitions'][1]['from_posture'],'P0')
        for transition in template['transitions']:
            self.assertEqual(transition['movement_start'],dict(status='UNANNOTATED',frame_reference=None))
            self.assertEqual(transition['target_reached'],dict(status='UNANNOTATED',frame_reference=None))
        cue=[e for e in events_at(self.session) if e['event']=='POSTURE_INSTRUCTION'][1]
        self.assertEqual(cue['source_anchor']['receive_index'],1)
        self.assertIn('not the physical motion time',cue['anchor_meaning'])

    def test_gap_duplicate_regression_and_missing_are_detected_without_repair(self):
        self.c.set_enabled(True)
        for index,number,stamp in ((1,1,100.),(2,4,200.),(3,4,200.),(4,5,150.)):
            self.capture(index,stamp,number=number)
        self.capture(5,300.,missing='depth')
        self.capture(6,50.,number=0)
        clip=self.c.current;self.c.finish()
        end=json.loads((clip/'end.json').read_text())
        self.assertEqual(end['sensor_diagnostics']['color.NUMBER_GAP'],1)
        self.assertEqual(end['sensor_diagnostics']['color.missing_number_estimate'],2)
        self.assertEqual(end['sensor_diagnostics']['color.DUPLICATE_IDENTITY'],1)
        self.assertEqual(end['sensor_diagnostics']['color.TIMESTAMP_REGRESSION'],1)
        self.assertEqual(end['sensor_diagnostics']['color.number_regression_count'],1)
        self.assertEqual(end['sensor_diagnostics']['color.timestamp_regression_count'],2)
        self.assertEqual(end['availability']['missing_depth'],1)
        read=list(replay.RawSessionReader(self.session).packets())
        self.assertEqual([p.record['sensors']['color']['number'] for p in read],[1,4,4,5,5,0])
        self.assertEqual(read[3].record['sensors']['color']['timestamp_ms'],150.)

    def test_interrupted_session_is_preserved_and_requires_explicit_incomplete_replay(self):
        self.c.set_enabled(True);self.capture(1,100.)
        self.c.finish(termination='q')
        self.assertEqual(json.loads((self.session/'recording_metadata/session_manifest.json').read_text())['status'],'INTERRUPTED')
        with self.assertRaises(ValueError):replay.RawSessionReader(self.session)
        result=replay.verify_replay(self.session,allow_incomplete=True)
        self.assertEqual(result['decoded']['replayable_frames'],1)

    def test_session_copy_keeps_original_identity_pixels_and_clocks(self):
        self.complete()
        moved=self.root/'another_pc';shutil.copytree(self.session,moved)
        original=replay.verify_replay(self.session);copy_result=replay.verify_replay(moved)
        self.assertEqual(original['source_identity_sha256'],copy_result['source_identity_sha256'])
        self.assertEqual(original['array_and_clock_sequence_sha256'],copy_result['array_and_clock_sequence_sha256'])
        self.assertEqual(original['decoded']['paired_frames'],2)

    def test_pixel_tampering_missing_frames_and_unindexed_files_fail(self):
        self.complete()
        for kind in ('tamper','missing','extra'):
            target=self.root/kind;shutil.copytree(self.session,target)
            image=target/'raw_rgbd/clip_0001/frames/00000001.npz'
            if kind=='tamper':image.write_bytes(b'CORRUPT')
            elif kind=='missing':image.unlink()  # Synthetic test fixture only.
            else:(image.parent/'99999999.npz').write_bytes(b'UNINDEXED')
            with self.assertRaises((ValueError,FileNotFoundError)):
                replay.verify_replay(target,allow_incomplete=True)

    def test_manifest_and_event_tampering_fail_before_replay(self):
        self.complete()
        journal=self.session/'recording_metadata/events.jsonl'
        journal.write_text(journal.read_text().replace('P03','P99'))
        with self.assertRaises(ValueError):replay.RawSessionReader(self.session)

    def test_incomplete_or_partial_write_never_becomes_a_successful_session(self):
        self.c.set_enabled(True);self.capture(1,100.)
        with patch.object(raw.np,'savez',side_effect=OSError('PRIVATE')):
            with self.assertRaises(raw.RawRecordingError):self.capture(2,200.)
        self.c.finish()
        types=[r['event'] for r in events_at(self.session)]
        self.assertIn('RECORDING_ERROR',types);self.assertIn('RECORDING_STOP',types)
        manifest=json.loads((self.session/'recording_metadata/session_manifest.json').read_text())
        self.assertEqual(manifest['status'],'FAILED')
        self.assertEqual(manifest['recording']['errors'][0]['path'],'clip_0001/frames/00000002.npz')
        with self.assertRaises(ValueError):replay.verify_replay(self.session,allow_incomplete=True)

    def test_annotation_copy_binds_to_original_and_does_not_invent_ground_truth(self):
        self.complete()
        path=self.root/'manual_review.json'
        with redirect_stdout(io.StringIO()):
            replay.main(['--input',str(self.session),'--make-annotation-copy',str(path)])
        result=validate_annotations(self.session,path)
        self.assertEqual(result['status'],'LINKAGE_VALIDATED')
        doc=json.loads(path.read_text())
        packet=next(replay.RawSessionReader(self.session).packets())
        ref={k:packet.record[k] for k in ('clip','frame_index','sha256')}
        sensor=packet.record['sensors']['color']
        ref.update(stream='color',timestamp_ms=sensor['timestamp_ms'],
                   timestamp_domain=sensor['timestamp_domain'],frame_number=sensor['number'])
        doc['transitions'][0]['movement_start']=dict(status='MANUAL_REVIEW_CONFIRMED',frame_reference=ref)
        path.write_text(json.dumps(doc))
        self.assertEqual(validate_annotations(self.session,path)['status'],'LINKAGE_VALIDATED')
        doc['transitions'][0]['movement_start']['frame_reference']['timestamp_ms']+=1.
        path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):validate_annotations(self.session,path)
        doc['transitions'][0]['movement_start']['frame_reference']['timestamp_ms']-=1.
        doc['source_manifest_sha256']='0'*64;path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):validate_annotations(self.session,path)

    def test_interrupted_annotation_review_requires_and_honors_explicit_flag(self):
        self.c.set_enabled(True);self.c.instruction('P1');self.capture(1,100.)
        self.c.finish(termination='q')
        path=self.root/'interrupted_review.json'
        with redirect_stdout(io.StringIO()):
            replay.main(['--input',str(self.session),'--allow-incomplete','--make-annotation-copy',str(path)])
        with self.assertRaises(ValueError):validate_annotations(self.session,path)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(replay.main(['--input',str(self.session),'--allow-incomplete',
                                        '--validate-annotations',str(path)]),0)

    def test_replay_cli_refuses_overwrite_and_writing_under_source(self):
        self.complete()
        existing=self.root/'existing.json';existing.write_text('PRESERVE')
        for output in (existing,self.session/'new_report.json'):
            with self.assertRaises(ValueError):replay.main(['--input',str(self.session),'--output',str(output)])
        self.assertEqual(existing.read_text(),'PRESERVE')

    def test_identity_values_are_operator_supplied_or_explicitly_unassigned(self):
        self.assertEqual(validate_context()['identity_status'],'UNASSIGNED')
        for args in (dict(participant_id='a name'),dict(session_label='S3'),dict(repetition=0)):
            with self.assertRaises(ValueError):validate_context(**args)

    def test_event_write_failure_is_visible_and_never_becomes_a_completed_recording(self):
        with patch.object(self.c.events.stream,'write',side_effect=OSError('PRIVATE')):
            with self.assertRaises(raw.RawRecordingError):self.c.instruction('P1')
        self.c.finish()
        self.assertEqual(self.c.summary()['status'],'FAILED')
        self.assertEqual(json.loads((self.session/'recording_metadata/session_manifest.json').read_text())['status'],'FAILED')
        with self.assertRaises(ValueError):replay.verify_replay(self.session,allow_incomplete=True)

    def test_persistent_event_disk_failure_still_closes_the_journal(self):
        with patch.object(self.c.events.stream,'write',side_effect=OSError('PRIVATE')):
            with self.assertRaises(raw.RawRecordingError):self.c.instruction('P1')
            with self.assertRaises(raw.RawRecordingError):self.c.finish()
        self.assertTrue(self.c.events.stream.closed)
        self.assertFalse((self.session/'recording_metadata/session_manifest.json').exists())

    def test_recording_stop_event_failure_also_closes_open_raw_and_event_files(self):
        self.c.set_enabled(True);self.capture(1,100.)
        with patch.object(self.c.events.stream,'write',side_effect=OSError('PRIVATE')):
            with self.assertRaises(raw.RawRecordingError):self.c.finish()
        self.assertTrue(self.c.events.stream.closed)
        self.assertTrue(self.c._finished)
        self.assertEqual(self.c.summary()['termination_status'],'FAILED')
        self.assertIsNone(self.c.current)

    def test_unfinalized_clip_can_only_be_read_with_explicit_flag_and_remains_unfinalized(self):
        self.complete()
        target=self.root/'unfinalized';shutil.copytree(self.session/'raw_rgbd/clip_0001',target)
        (target/'end.json').unlink()  # Only this synthetic copy.
        with self.assertRaises(ValueError):replay.verify_replay(target)
        self.assertEqual(replay.verify_replay(target,allow_incomplete=True)['source_completion_status'],'UNFINALIZED')


class FollowupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(SVC,'fit',side_effect=AssertionError('no fit')))
        self.enterContext(patch.object(StandardScaler,'fit',side_effect=AssertionError('no fit')))

    def test_e0_b1_saved_or_unsaved_keep_same_measurement_and_event_boundaries(self):
        values=[]
        for variant in ('E0','B1'):
            for initial in ('off','on'):
                s,c,_,inputs,predictions=helpers.RawProbeTests.run_fake(self,variant,initial=initial,
                    events=list(range(0,11400,300)),arm_at=2,session_context=CONTEXT)
                self.assertEqual(predictions,1);self.assertEqual(s.segments[0]['input_frames'],34)
                values.append(inputs[0])
                types=[r['event'] for r in events_at(s.directory)]
                for event in ('SESSION_START','MEASUREMENT_START','POSTURE_HOLD_START','POSTURE_HOLD_END','MEASUREMENT_END','SESSION_END'):
                    self.assertIn(event,types)
                verified=replay.verify_replay(s.directory,allow_incomplete=True)
                self.assertEqual(verified['decoded']['replayable_frames'],38 if initial=='on' else 0)
        for value in values[1:]:np.testing.assert_array_equal(value,values[0])

    def test_inference_failure_keeps_raw_frame_and_session_failure_evidence(self):
        s,c,_,_,_=helpers.RawProbeTests.run_fake(self,'E0',initial='on',fail='inference',session_context=CONTEXT)
        manifest=json.loads((s.directory/'recording_metadata/session_manifest.json').read_text())
        self.assertEqual(manifest['status'],'FAILED')
        self.assertEqual(replay.verify_replay(s.directory,allow_incomplete=True)['decoded']['replayable_frames'],1)

    def test_operator_posture_buttons_and_guided_instructions_are_separate_from_movement(self):
        for guided in (False,True):
            model,scaler=estimators();clock=Clock()
            s=E0Session(self.root/str(guided),model,scaler,clock_ns=clock)
            c=raw.RawRecordingControl(s.directory/'raw_rgbd',
                session_context={**CONTEXT,'participant_id':'P01'} if guided else CONTEXT,
                clock_ns=clock,scope=s.scope)
            s.raw_recording=c;c.begin_session()
            buttons=[]
            def button(*a,**kw):buttons.append(kw);return Mock()
            tk=NS(Tk=lambda:Mock(),StringVar=helpers.FakeVar,Label=lambda *a,**kw:Mock(),
                  Frame=lambda *a,**kw:Mock(),Button=button)
            panel=GuidedPanel(s,subject='P01',tk_module=tk) if guided else OperatorPanel(s,tk_module=tk)
            if guided:panel.poll()
            else:
                next(b for b in buttons if b['text'].startswith('P1 '))['command']();panel.poll()
            c.finish();panel.close();s.finish()
            cue=next(r for r in events_at(s.directory) if r['event']=='POSTURE_INSTRUCTION')
            self.assertEqual(cue['posture_code'],'P0' if guided else 'P1')
            self.assertEqual(cue['details']['actual_movement_start'],'UNANNOTATED')

    def test_start_then_cancel_in_one_ui_poll_records_both_requests_without_fabricating_hold(self):
        model,scaler=estimators();clock=Clock()
        s=E0Session(self.root/'fast',model,scaler,clock_ns=clock)
        c=raw.RawRecordingControl(s.directory/'raw_rgbd',session_context=CONTEXT,clock_ns=clock,scope=s.scope)
        s.raw_recording=c;c.begin_session()
        operator=OperatorControl(s);operator.start();operator.cancel()
        c.finish();s.finish()
        kinds=[r['event'] for r in events_at(s.directory)]
        self.assertIn('MEASUREMENT_START',kinds);self.assertIn('MEASUREMENT_END',kinds)
        self.assertNotIn('POSTURE_HOLD_START',kinds)
        self.assertEqual(c.total_frames,0)

    def test_guided_cli_rejects_conflicting_manual_repeat_before_camera_or_model_loading(self):
        import run_e0_check
        with patch.object(run_e0_check,'load_fs3') as model,patch.object(run_e0_check,'run_probe') as camera, \
                redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_e0_check.main(['--check-only','--guided-six','--subject','P01','--repetition','2'])
        model.assert_not_called();camera.assert_not_called()


class NativeReplayStructureTests(unittest.TestCase):
    def setUp(self):self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))

    def fake_db(self):
        path=self.root/'source.db3';c=sqlite3.connect(path)
        c.execute('CREATE TABLE topics(id INTEGER,name TEXT)')
        c.execute('CREATE TABLE messages(topic_id INTEGER)');c.commit();c.close()
        return path

    def packet(self,uid=1,stamp=100.):
        sensors={n:raw.snapshot(child(1,stamp,uid=uid,stream=n)) for n in ('color','depth')}
        arrays=dict(color_bgr=np.zeros((2,2,3),dtype=np.uint8),depth_z16=np.ones((2,2),dtype=np.uint16))
        record=dict(frame_index=1,frameset_number=1,frameset_timestamp_ms=stamp,
            frameset_timestamp_domain='hardware_clock',sensors=sensors,pairing=raw.pairing_info(sensors,arrays))
        return replay.RawPacket(arrays['color_bgr'],arrays['depth_z16'],record,helpers.metadata())

    def test_runtime_profile_uid_does_not_change_pixel_clock_identity_but_timestamps_do(self):
        source=self.fake_db();outputs=[]
        for uid,stamp in ((1,100.),(99,100.),(99,101.)):
            with patch.object(replay,'db3_packets',return_value=iter([self.packet(uid,stamp)])):
                outputs.append(replay.verify_replay(source))
        self.assertEqual(outputs[0]['array_and_clock_sequence_sha256'],outputs[1]['array_and_clock_sequence_sha256'])
        self.assertNotEqual(outputs[1]['array_and_clock_sequence_sha256'],outputs[2]['array_and_clock_sequence_sha256'])
        # sqlite3 context managers do not close connections; the helper must do so.
        source.unlink()  # Only this synthetic DB, also verifies Windows handle release.
        self.assertFalse(source.exists())

    def test_file_reader_uses_only_explicit_file_source_and_confirms_eof(self):
        path=self.fake_db();camera=helpers.metadata()
        playback=NS(set_real_time=Mock(),current_status=lambda:'STOPPED')
        device=NS(as_playback=lambda:playback)
        frames=pair(child(),child(stream='depth',uid=2))
        frames.get_frame_timestamp_domain=lambda:'hardware_clock'
        pipe=NS(start=Mock(return_value=NS(get_device=lambda:device)),stop=Mock(),
                try_wait_for_frames=Mock(side_effect=[(True,frames),(False,None)]))
        config=NS(enable_device_from_file=Mock())
        rs=NS(pipeline=lambda:pipe,config=lambda:config,playback_status=NS(stopped='STOPPED'),
              context=Mock(side_effect=AssertionError('no live discovery')))
        with patch.dict(sys.modules,{'pyrealsense2':rs}),patch.object(replay,'camera_metadata',return_value=camera):
            packets=list(replay.db3_packets(path))
        self.assertEqual(len(packets),1)
        config.enable_device_from_file.assert_called_once_with(str(path.resolve()),repeat_playback=False)
        playback.set_real_time.assert_called_once_with(False);pipe.stop.assert_called_once();rs.context.assert_not_called()

    def test_camera_identity_firmware_sdk_and_options_are_read_only_and_restorable(self):
        intr=NS(width=2,height=2,fx=3.,fy=4.,ppx=1.,ppy=1.,model='none',coeffs=[0.]*5)
        color=NS(get_intrinsics=lambda:intr,fps=lambda:15,format=lambda:'bgr8')
        depth=NS(get_intrinsics=lambda:intr,fps=lambda:15,format=lambda:'z16',
            get_extrinsics_to=lambda _:NS(rotation=[1.,0.,0.,0.,1.,0.,0.,0.,1.],translation=[.05,0.,0.]))
        sensor=NS(get_depth_scale=lambda:.001,get_option=Mock(return_value=12.),
                  set_option=Mock(side_effect=AssertionError('no setting mutation')))
        values=dict(name='SYNTHETIC_D455',serial_number='SYNTHETIC_SERIAL',firmware_version='TEST_FW',product_id='TEST',usb_type_descriptor='3')
        device=NS(get_info=lambda key:values[key],first_depth_sensor=lambda:sensor,first_color_sensor=lambda:sensor)
        profile=NS(get_device=lambda:device,get_stream=lambda stream:NS(as_video_stream_profile=lambda:color if stream==1 else depth))
        options=('exposure','gain','enable_auto_exposure','white_balance','enable_auto_white_balance','laser_power',
                 'emitter_enabled','visual_preset','frames_queue_size','depth_units','global_time_enabled')
        rs=NS(stream=NS(color=1,depth=2),camera_info=NS(**{key:key for key in values}),
              option=NS(**{key:key for key in options}))
        with patch.object(raw.package_metadata,'version',return_value='TEST_SDK'):
            record=raw.camera_metadata(profile,rs)
        self.assertEqual(record['device']['firmware_version']['value'],'TEST_FW')
        self.assertEqual(record['device']['serial_number']['value'],'SYNTHETIC_SERIAL')
        self.assertEqual(record['sdk']['value'],'TEST_SDK')
        self.assertEqual(record['sensor_options']['depth']['laser_power']['value'],12.)
        sensor.set_option.assert_not_called()


if __name__=='__main__':unittest.main()
