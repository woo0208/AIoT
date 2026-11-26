from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import numpy as np

def read_json(path):
    def invalid(value):
        raise ValueError(f"non-finite JSON: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)

FORMAT = 'e0-raw-rgbd-npz/1'

EXCHANGE_VALIDATION_FORMAT = 'research-b-exchange-clip-validation/1'

EXCHANGE_VALIDATION_FILE = 'exchange_validation.json'

def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None

def pairing_info(sensors, arrays, source='SDK_DELIVERED_FRAMESET'):
    color,depth=sensors.get('color',{}),sensors.get('depth',{})
    comparable=(color.get('timestamp_domain') is not None
        and color.get('timestamp_domain')==depth.get('timestamp_domain')
        and _number(color.get('timestamp_ms')) is not None and _number(depth.get('timestamp_ms')) is not None)
    return dict(source=source,color_present='color_bgr' in arrays,
        depth_present='depth_z16' in arrays,same_timestamp_domain=bool(comparable),
        color_minus_depth_ms=color['timestamp_ms']-depth['timestamp_ms'] if comparable else None,
        synchronization_quality='NOT_ASSESSED')

def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def load_raw_frame(clip, record):
    """Load one indexed NPZ with hash/order/type checks; never repairs source time."""
    clip = Path(clip)
    if type(record.get('frame_index')) is not int or record['frame_index'] < 1:
        raise ValueError('Invalid raw frame index')
    expected = f"frames/{record['frame_index']:08d}.npz"
    if record['file'] != expected or _sha(clip/expected) != record['sha256']:
        raise ValueError('Raw frame path/hash mismatch')
    with np.load(clip/expected, allow_pickle=False) as saved:
        if not set(saved.files).issubset({'color_bgr', 'depth_z16'}):
            raise ValueError('Unexpected raw array key')
        result = {name: saved[name].copy() for name in saved.files}
    for name, dtype, ndim in (('color_bgr', np.uint8, 3), ('depth_z16', np.uint16, 2)):
        if name in result and (result[name].dtype != dtype or result[name].ndim != ndim
                               or (name == 'color_bgr' and result[name].shape[2] != 3)):
            raise ValueError('Invalid raw array')
    return result

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
        if 'exchange_validation' in self.identity and not allow_incomplete:
            self._require_exchange_validation()

    def _require_exchange_validation(self):
        proof = self.directory/EXCHANGE_VALIDATION_FILE
        if not proof.is_file():
            raise ValueError('Final exchange validation is missing')
        validation = read_json(proof)
        if (self.identity['exchange_validation'] != EXCHANGE_VALIDATION_FORMAT
                or validation.get('format') != EXCHANGE_VALIDATION_FORMAT
                or validation.get('session_id') != self.identity.get('session_id')
                or validation.get('write_status') != self.end['status']
                or validation.get('session_status') != 'COMPLETED'
                or validation.get('status') not in ('PASS', 'WARNING')
                or validation.get('file_integrity') != 'PASS'
                or validation.get('clip_sha256') != self.hashes):
            raise ValueError('Final exchange validation did not authorize this clip')
        self.hashes[proof.name] = _sha(proof)

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
                source = record.get('pairing_source', 'SDK_DELIVERED_FRAMESET')
                if source not in ('SDK_DELIVERED_FRAMESET', 'NATIVE_ONE_USE_TIMESTAMP_PAIR'):
                    raise ValueError('Unknown RGB/Depth pairing source')
                if record.get('pairing') is not None and record['pairing']!=pairing_info(record['sensors'],arrays,source):
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

def snapshot(frame):
    """Use only SDK accessors; unavailable fields remain explicitly unmeasured."""
    if not frame:
        return dict(status='NOT_MEASURED', reason='frame_unavailable')
    result = {}
    for name, getter in (
        ('number', lambda: frame.get_frame_number()),
        ('timestamp_ms', lambda: float(frame.get_timestamp())),
        ('timestamp_domain', lambda: str(frame.get_frame_timestamp_domain())),
        ('profile_uid', lambda: frame.get_profile().unique_id()),
        ('stream_type', lambda: str(frame.get_profile().stream_type())),
        ('stream_index', lambda: frame.get_profile().stream_index()),
    ):
        try:
            value = getter()
            if (value is None or (name == 'number' and (type(value) is not int or value < 0))
                    or (name == 'timestamp_ms' and not math.isfinite(value))
                    or (name == 'timestamp_domain' and value.lower() in ('', 'none', 'unknown'))):
                raise ValueError('invalid SDK metadata')
            result[name] = value
        except Exception as exc:
            result[name] = None
            result.setdefault('unavailable', {})[name] = str(exc)
    core = ('number', 'timestamp_ms', 'timestamp_domain', 'profile_uid', 'stream_type', 'stream_index')
    result['status'] = 'MEASURED' if all(result.get(n) is not None for n in core) else 'NOT_MEASURED'
    return result

def intrinsics(rs, camera, name):
    info = camera['streams'][name]
    intr = rs.intrinsics()
    intr.width, intr.height = info['width'], info['height']
    for key in ('fx', 'fy', 'ppx', 'ppy', 'coeffs'):
        setattr(intr, key, info['intrinsics'][key])
    intr.model = getattr(rs.distortion, info['intrinsics']['model'].split('.')[-1])
    return intr

class SoftwareFrames:
    """Reconstruct SDK frames with stored calibration; no physical sensor exists.

    Build a composite explicitly: a syncer could pair/drop different inputs when
    clocks regress or differ. Each original reader packet remains one composite.
    """
    def __init__(self, rs, camera):
        self.rs, self.camera = rs, camera
        for info in camera['streams'].values():
            # Librealsense Align is unsafe for toy 2x2 profiles on this SDK.
            if (type(info['width']) is not int or type(info['height']) is not int
                    or info['width'] < 64 or info['height'] < 48 or info['width'] % 4):
                raise ValueError('SDK replay requires video width >=64 divisible by 4 and height >=48')
            intr = info['intrinsics']
            values = [intr[k] for k in ('fx','fy','ppx','ppy')] + list(intr['coeffs'])
            if not all(math.isfinite(v) for v in values) or intr['fx'] <= 0 or intr['fy'] <= 0:
                raise ValueError('Invalid saved intrinsics')
        self.device = rs.software_device()
        self.sensor = self.device.add_sensor('RGB-D file source')
        self.sensor.add_read_only_option(rs.option.depth_units, camera['depth_scale_m'])
        self.profiles = {}
        for uid, name in enumerate(('depth', 'color'), 1):
            info = camera['streams'][name]
            expected = 'format.z16' if name == 'depth' else 'format.bgr8'
            if info['format'] != expected:
                raise ValueError('Replay requires native Z16/BGR8')
            stream = rs.video_stream()
            stream.type, stream.index, stream.uid = getattr(rs.stream, name), 0, uid
            stream.width, stream.height, stream.fps = info['width'], info['height'], info['fps']
            stream.bpp, stream.fmt = (2, rs.format.z16) if name == 'depth' else (3, rs.format.bgr8)
            stream.intrinsics = intrinsics(rs, camera, name)
            self.profiles[name] = self.sensor.add_video_stream(stream).as_video_stream_profile()
        extr = rs.extrinsics()
        for key in ('rotation', 'translation'):
            setattr(extr, key, camera['depth_to_color_extrinsics'][key])
        self.profiles['depth'].register_extrinsics_to(self.profiles['color'], extr)
        self.queue = rs.frame_queue(4, keep_frames=True)
        self.sensor.open(list(self.profiles.values()))
        self.sensor.start(self.queue)
        self.output = rs.frame_queue(1, keep_frames=True)
        self.children = []
        self.composer = rs.processing_block(lambda frame, source:
            source.frame_ready(source.allocate_composite_frame(self.children)))
        self.composer.start(self.output.enqueue)

    def compose(self, packet):
        rs = self.rs
        self.children = []
        self.arrays = []  # hold injected pixel buffers until processing is complete
        for name, array in (('depth', packet.depth_z16), ('color', packet.color_bgr)):
            if array is None:
                continue
            info = self.camera['streams'][name]
            expected_shape = (info['height'],info['width']) + ((3,) if name=='color' else ())
            if array.shape != expected_shape or array.dtype != (np.uint8 if name=='color' else np.uint16):
                raise ValueError('Original pixels/profile mismatch')
            array = np.ascontiguousarray(array)
            self.arrays.append(array)
            meta = packet.record['sensors'][name]
            f = rs.software_video_frame()
            f.pixels, f.stride, f.bpp = array, array.strides[0], array.itemsize * (3 if name == 'color' else 1)
            f.timestamp, f.frame_number = meta['timestamp_ms'], meta['number']
            f.domain = getattr(rs.timestamp_domain, meta['timestamp_domain'].split('.')[-1])
            f.profile, f.depth_units = self.profiles[name], self.camera['depth_scale_m']
            self.sensor.on_video_frame(f)
            child = self.queue.wait_for_frame(1000)
            # SDK reconstruction must never silently alter sensor clocks/numbers.
            observed = snapshot(child)
            if any(observed[k] != meta[k] for k in ('number', 'timestamp_ms', 'timestamp_domain')):
                raise ValueError('SDK reconstruction changed original sensor clock')
            self.children.append(child)
        if not self.children:
            raise ValueError('Packet contains neither RGB nor Depth')
        self.composer.invoke(self.children[-1])
        return self.output.wait_for_frame(1000).as_frameset()

    def close(self):
        try:
            self.sensor.stop()
        finally:
            self.sensor.close()
