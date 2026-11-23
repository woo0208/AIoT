"""Read-only NPZ/RealSense file verification. No camera discovery or inference.

Uses the existing project's SDK file-playback pattern (enable_device_from_file,
repeat_playback=False, set_real_time(False)); never falls back to a live device.
"""
import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np

from e0_storage import write_json
from frame_provenance import snapshot
from research_recording import read_json
from raw_rgbd_recording import FORMAT, SensorTrace, _sha, camera_metadata, load_raw_frame, pairing_info


@dataclass
class RawPacket:
    color_bgr: object
    depth_z16: object
    record: dict
    camera: dict
    native_frames: object = None  # optional SDK handle; readers' array/clock contract is unchanged


def _inside(root,relative):
    path=(root/relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('Recording path escapes source root')
    return path


class RawClipReader:
    def __init__(self,directory,*,allow_incomplete=False):
        self.directory=Path(directory).resolve(strict=True)
        self.identity=read_json(self.directory/'recording.json')
        if self.identity.get('format')!=FORMAT:raise ValueError('Unknown raw clip format')
        self.camera=self.identity['camera']
        end=self.directory/'end.json'
        self.end=read_json(end) if end.exists() else None
        if (self.end is None or self.end.get('status')!='COMPLETED') and not allow_incomplete:
            raise ValueError('Incomplete/failed clip requires --allow-incomplete')
        self.hashes={n:_sha(self.directory/n) for n in ('recording.json','frames.jsonl')}
        if self.end:
            if self.end.get('format')!=FORMAT or any(self.end.get(key)!=self.hashes[name]
                    for key,name in (('recording_sha256','recording.json'),('frames_index_sha256','frames.jsonl'))):
                raise ValueError('Clip metadata/index hash mismatch')
            self.hashes['end.json']=_sha(end)

    def packets(self):
        count=0;source_hashes={}
        with (self.directory/'frames.jsonl').open(encoding='utf-8') as stream:
            for index,line in enumerate(stream,1):
                record=json.loads(line)
                if record.get('frame_index')!=index:raise ValueError('Raw frame index/order mismatch')
                if record.get('session_id')!=self.identity.get('session_id'):
                    raise ValueError('Raw frame session mismatch')
                path=_inside(self.directory,record['file'])
                arrays=load_raw_frame(self.directory,record)
                for name,key in (('color','color_bgr'),('depth','depth_z16')):
                    if key in arrays:
                        info=self.camera['streams'][name]
                        if arrays[key].shape[:2]!=(info['height'],info['width']):
                            raise ValueError('Raw profile/shape mismatch')
                if record.get('pairing') is not None and record['pairing']!=pairing_info(record['sensors'],arrays):
                    raise ValueError('RGB/Depth correspondence mismatch')
                source_hashes[path]=record['sha256'];count=index
                yield RawPacket(arrays.get('color_bgr'),arrays.get('depth_z16'),record,self.camera)
        if self.end and self.end['frames']!=count:raise ValueError('Raw frame count mismatch')
        actual={p.resolve() for p in (self.directory/'frames').iterdir()}
        if actual!=set(source_hashes):raise ValueError('Unindexed or missing raw frame files')
        for path,digest in source_hashes.items():
            if _sha(path)!=digest:raise ValueError('Source pixels changed during replay')
        for name,digest in self.hashes.items():
            if _sha(self.directory/name)!=digest:raise ValueError('Source metadata changed during replay')


class RawSessionReader:
    def __init__(self,directory,*,allow_incomplete=False):
        self.directory=Path(directory).resolve(strict=True)
        self.path=self.directory/'recording_metadata/session_manifest.json'
        self.identity=read_json(self.path)
        if self.identity.get('format')!='research-b-raw-session/1':raise ValueError('Unknown raw session format')
        if self.identity['status']!='COMPLETED' and not allow_incomplete:
            raise ValueError('Failed session requires --allow-incomplete')
        self.manifest_sha256=_sha(self.path)
        self.hashes=self.identity['files']
        self._verify_inventory()
        self.clips=sorted({str(Path(n).parent).replace('\\','/') for n in self.hashes if n.startswith('raw_rgbd/')},
                          key=lambda p:int(Path(p).name.removeprefix('clip_')))
        existing={str(p.relative_to(self.directory)).replace('\\','/')
                  for p in (self.directory/'raw_rgbd').glob('clip_*')}
        if existing!=set(self.clips):raise ValueError('Session clip inventory mismatch')
        self.allow_incomplete=allow_incomplete

    def _verify_inventory(self):
        for name,digest in self.hashes.items():
            if _sha(_inside(self.directory,name))!=digest:raise ValueError('Session source hash mismatch')
        events_path=self.directory/'recording_metadata/events.jsonl'
        count=0
        first_event=last_event=None
        from raw_rgbd_events import EVENTS
        for count,line in enumerate(events_path.read_text(encoding='utf-8').splitlines(),1):
            record=json.loads(line)
            if record['session_id']!=self.identity['session_id'] or record['event_index']!=count:
                raise ValueError('Session event identity/order mismatch')
            if record['event'] not in EVENTS:raise ValueError('Unknown session event')
            if first_event is None:first_event=record['event']
            last_event=record['event']
        if count!=self.identity['event_count']:raise ValueError('Session event count mismatch')
        if first_event!='SESSION_START' or last_event!='SESSION_END':
            raise ValueError('Session terminal event missing')

    def packets(self):
        count=0
        for clip in self.clips:
            reader=RawClipReader(self.directory/clip,allow_incomplete=self.allow_incomplete)
            if reader.identity.get('session_id')!=self.identity['session_id']:
                raise ValueError('Clip/session identity mismatch')
            for packet in reader.packets():
                packet.record={**packet.record,'clip':clip};count+=1
                if (packet.record.get('preceding_event_index') is None or
                    not 1<=packet.record['preceding_event_index']<=self.identity['event_count']):
                    raise ValueError('Frame event link is outside the session')
                yield packet
        if count!=self.identity['recording']['frames']:raise ValueError('Session saved/replayed count mismatch')
        self._verify_inventory()
        if _sha(self.path)!=self.manifest_sha256:raise ValueError('Manifest changed during replay')


def db3_packets(path):
    """Use a file-only SDK source as in capture_d455.count_frames/analyze_d455."""
    import pyrealsense2 as rs
    path=Path(path).resolve(strict=True)
    if not path.is_file():raise ValueError('Playback requires a local recording file')
    pipe,cfg=rs.pipeline(),rs.config()
    cfg.enable_device_from_file(str(path),repeat_playback=False)
    started=False
    try:
        profile=pipe.start(cfg);started=True
        playback=profile.get_device().as_playback();playback.set_real_time(False)
        camera=camera_metadata(profile,rs,source_kind='file_playback')
        for key in ('color','depth'):
            if key not in camera['streams']:raise ValueError('Playback lacks RGB/Depth profile')
        index=0
        while True:
            ready,frames=pipe.try_wait_for_frames(2000)
            if not ready:
                if playback.current_status()!=rs.playback_status.stopped:
                    raise RuntimeError('File playback timeout before confirmed EOF')
                break
            arrays={};sensors={}
            for name,key,getter in (('color','color_bgr','get_color_frame'),('depth','depth_z16','get_depth_frame')):
                frame=getattr(frames,getter)()
                sensors[name]=snapshot(frame);sensors[name].pop('unavailable',None)
                if frame:arrays[key]=np.asanyarray(frame.get_data()).copy()
            index+=1
            record=dict(frame_index=index,frameset_timestamp_ms=frames.get_timestamp(),
                frameset_timestamp_domain=str(frames.get_frame_timestamp_domain()),
                frameset_number=frames.get_frame_number(),sensors=sensors,pairing=pairing_info(sensors,arrays))
            yield RawPacket(arrays.get('color_bgr'),arrays.get('depth_z16'),record,camera,frames)
    finally:
        if started:pipe.stop()


def _stored_image_counts(path):
    if Path(path).suffix.lower()!='.db3':return None
    connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        return dict(connection.execute('SELECT t.name,count(*) FROM messages m JOIN topics t ON m.topic_id=t.id '
                    'WHERE t.name LIKE ? GROUP BY t.id',('%/image/data',)).fetchall())
    finally:
        connection.close()


def verify_replay(source,*,allow_incomplete=False,expected_sha256=None):
    source=Path(source).resolve(strict=True)
    file_source=source.is_file()
    initial=_sha(source) if file_source else None
    if expected_sha256 is not None and initial!=expected_sha256:raise ValueError('Unexpected original file SHA-256')
    if file_source:
        packets=db3_packets(source);identity=initial;kind='REALSENSE_FILE'
        completion='UNKNOWN_LEGACY_CAPTURE_STATUS'
    elif (source/'recording_metadata/session_manifest.json').exists():
        reader=RawSessionReader(source,allow_incomplete=allow_incomplete)
        packets=reader.packets();identity=reader.manifest_sha256;kind='NPZ_SESSION'
        completion=reader.identity['status']
    else:
        reader=RawClipReader(source,allow_incomplete=allow_incomplete)
        packets=reader.packets();identity=reader.hashes['recording.json'];kind='NPZ_CLIP'
        completion=reader.end['status'] if reader.end else 'UNFINALIZED'
    counts=Counter();trace=SensorTrace();digest=hashlib.sha256();camera=None
    first=last=None;previous_clip=None
    for packet in packets:
        clip=packet.record.get('clip')
        if clip is not None and clip!=previous_clip:
            trace.previous={};previous_clip=clip  # OFF intervals are not sensor drop evidence.
        count=packet.record['frame_index']
        camera=packet.camera
        counts['replayable_frames']+=1
        arrays={'color_bgr':packet.color_bgr,'depth_z16':packet.depth_z16}
        pair=True
        for name,array in arrays.items():
            if array is None:counts['missing_'+name]+=1;pair=False
            else:
                if array.dtype!=(np.uint8 if name=='color_bgr' else np.uint16):raise ValueError('Decoded dtype mismatch')
                shape=tuple(array.shape)
                stream='color' if name=='color_bgr' else 'depth'
                profile=camera['streams'][stream]
                if shape[:2]!=(profile['height'],profile['width']):raise ValueError('Decoded profile mismatch')
                digest.update(name.encode());digest.update(str(shape).encode());digest.update(array.tobytes())
        counts['paired_frames']+=pair
        trace.observe(packet.record['sensors'])
        clock={k:packet.record[k] for k in ('frame_index','frameset_timestamp_ms','frameset_timestamp_domain','frameset_number','sensors')}
        stable_clock={**clock,'sensors':{n:{k:v for k,v in s.items() if k!='profile_uid'}
                                        for n,s in clock['sensors'].items()}}
        digest.update(json.dumps(stable_clock,sort_keys=True,allow_nan=False).encode())
        if first is None:first=clock
        last=clock
    if file_source and _sha(source)!=initial:raise ValueError('Original recording was modified')
    return dict(status='VERIFIED_READ_ONLY',kind=kind,source_identity_sha256=identity,
        source_completion_status=completion,
        decoded={name:counts[name] for name in ('replayable_frames','paired_frames','missing_color_bgr','missing_depth_z16')},
        sensor_diagnostics=dict(trace.counts),camera=camera,
        first=first,last=last,array_and_clock_sequence_sha256=digest.hexdigest(),
        sequence_hash_note='Pixels and original clocks/numbers/domains; runtime SDK profile_uid is excluded',
        native_stored_image_counts=_stored_image_counts(source) if file_source else None,
        hardware_capture='NOT_TESTED_HARDWARE',live_performance='NOT_MEASURED_OFFLINE_REPLAY',
        source_modified=False,classification='NOT_RUN')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,help='new report file outside the immutable source')
    parser.add_argument('--allow-incomplete',action='store_true')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--validate-annotations',type=Path)
    parser.add_argument('--make-annotation-copy',type=Path)
    args=parser.parse_args(argv)
    source=args.input.resolve(strict=True)
    for output in (args.output,args.make_annotation_copy):
        if output and (output.exists() or output.resolve()==source or
                       (source.is_dir() and output.resolve().is_relative_to(source))):
            raise ValueError('Output must be a NEW file outside the original source')
    if args.make_annotation_copy:
        document=read_json(source/'recording_metadata/annotations_template.json')
        document['source_manifest_sha256']=_sha(source/'recording_metadata/session_manifest.json')
        write_json(args.make_annotation_copy,document)
    if args.validate_annotations:
        from raw_rgbd_events import validate_annotations
        result=validate_annotations(source,args.validate_annotations,allow_incomplete=args.allow_incomplete)
    else:
        result=verify_replay(source,allow_incomplete=args.allow_incomplete,expected_sha256=args.expected_sha256)
    if args.output:write_json(args.output,result)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
