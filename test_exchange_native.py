"""Regression coverage for native acquisition and write-once NPZ checksums."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from exchange_native import NativePairer, NativeRGBDSource, RECENT_FRAME_LIMIT, SDK_METADATA_FIELDS
from raw_rgbd_recording import HashingNPZOutput, native_packet
from test_frame_provenance import child


def send(pairer, name, number, stamp, domain='system_time'):
    frame = child(number, stamp, stream=name, uid=1 if name=='color' else 2, domain=domain)
    return pairer.push(name, frame, int(stamp*1e6))


class PairerTest(unittest.TestCase):
    def test_reads_all_supported_sdk_metadata_without_normalizing_raw_values(self):
        keys = SimpleNamespace(**{name: index for index, name in enumerate(SDK_METADATA_FIELDS)})
        p = NativePairer(15, sdk_metadata=keys)
        sample = child()
        sample.supports_frame_metadata = Mock(return_value=True)
        sample.get_frame_metadata = Mock(side_effect=lambda key: key*1000)
        self.assertEqual(p._read_sdk_metadata(sample), {name: key*1000 for name, key in vars(keys).items()})
        self.assertEqual(sample.supports_frame_metadata.call_count, 5)
        self.assertEqual(sample.get_frame_metadata.call_count, 5)

    def test_partial_sdk_support_skips_missing_enum_and_unsupported_frame_field(self):
        keys = SimpleNamespace(frame_counter=0, sensor_timestamp=1)
        p = NativePairer(15, sdk_metadata=keys)
        sample = child()
        sample.supports_frame_metadata = Mock(side_effect=lambda key: key == 0)
        sample.get_frame_metadata = Mock(return_value=42)
        observed = p._read_sdk_metadata(sample)
        self.assertEqual(observed['frame_counter'], 42)
        self.assertEqual(observed['sensor_timestamp'], 'NOT_SUPPORTED')
        self.assertEqual(observed['time_of_arrival'], 'NOT_SUPPORTED')
        self.assertEqual(sample.supports_frame_metadata.call_count, 2)
        sample.get_frame_metadata.assert_called_once_with(0)

    def test_sdk_metadata_query_errors_do_not_interrupt_normal_pairing(self):
        keys = SimpleNamespace(frame_counter=0, sensor_timestamp=1, backend_timestamp=2, time_of_arrival=3)
        p = NativePairer(15, sdk_metadata=keys)
        p.activate()
        color = child(1, 66, domain='system_time')
        color.supports_frame_metadata = Mock(side_effect=[RuntimeError('support check'), True, True, True])
        # The declared enum order is sensor, backend, arrival, counter.
        color.get_frame_metadata = Mock(side_effect=[RuntimeError('value read'), 'invalid', 5])
        self.assertIsNone(p.push('color', color, 66_000_000))
        self.assertIsNotNone(send(p, 'depth', 1, 67))
        sdk_values = p.last_processed['color'][-1]
        self.assertEqual(sdk_values, dict(sensor_timestamp='READ_ERROR', backend_timestamp='READ_ERROR',
                         time_of_arrival='READ_ERROR', frame_counter=5, frame_timestamp='NOT_SUPPORTED'))
        self.assertIsNone(p.failure)

    def test_startup_depth_interruption_requires_new_stable_pairs(self):
        p = NativePairer(15)
        send(p,'depth',1,100)
        send(p,'color',1,370)
        send(p,'color',2,437)
        send(p,'depth',2,705)
        self.assertEqual(p.streak,0)
        for i in range(3,6):
            send(p,'depth',i,705+(i-2)*67)
            pair=send(p,'color',i,711+(i-2)*67)
        self.assertEqual(p.streak,3)
        self.assertEqual(p.warmup['sensor_number_or_time_gap'],1)
        self.assertEqual(native_packet(pair)[2]['pairing_source'],'NATIVE_ONE_USE_TIMESTAMP_PAIR')
        p.activate()
        send(p,'color',6,979)
        self.assertIsNotNone(send(p,'depth',6,973))
        self.assertEqual(dict(p.observed),{'color':1,'depth':1})

    def test_no_old_child_substitution_when_one_stream_arrives_twice(self):
        p=NativePairer(15)
        p.activate()
        send(p,'color',1,100)
        send(p,'depth',1,101)
        self.assertIsNone(send(p,'color',2,166))
        self.assertIsNone(send(p,'color',3,233))
        pair=send(p,'depth',2,167)
        self.assertEqual((pair.color.get_frame_number(),pair.depth.get_frame_number()),(2,2))
        pair=send(p,'depth',3,234)
        self.assertEqual((pair.color.get_frame_number(),pair.depth.get_frame_number()),(3,3))

    def test_duplicate_gap_and_sensor_time_gap_are_terminal(self):
        for number,stamp,reason in [(1,160,'duplicate_or_regression'),(3,168,'sensor_number_or_time_gap'),
                                    (2,600,'sensor_number_or_time_gap')]:
            with self.subTest(number=number,stamp=stamp):
                p=NativePairer(15)
                p.activate()
                send(p,'depth',1,100)
                with self.assertRaisesRegex(RuntimeError,reason):
                    send(p,'depth',number,stamp)
                self.assertEqual(p.failure['sensor']['number'],number)

    def test_incompatible_clocks_and_skew_are_never_paired(self):
        for other,stamp,reason in [('hardware_clock',100,'incomparable_clocks'),
                                   ('system_time',135,'unmatched_timestamp')]:
            with self.subTest(domain=other):
                p=NativePairer(15)
                p.activate()
                send(p,'depth',1,100)
                with self.assertRaisesRegex(RuntimeError,reason):
                    send(p,'color',1,stamp,other)
                if reason == 'incomparable_clocks':
                    diagnostic = p.failure['diagnostics']
                    self.assertEqual(diagnostic['color_minus_depth_ms'], 'NOT_RECORDED')
                    self.assertEqual(diagnostic['abs_skew_excess_ms'], 'NOT_RECORDED')
                    self.assertEqual(diagnostic['compared_candidates']['color']['timestamp_domain'], other)

    def test_mismatch_freezes_bounded_metadata_and_preserves_optional_sdk_values(self):
        fields = SimpleNamespace(sensor_timestamp=0, backend_timestamp=1, time_of_arrival=2)
        now = 1_000_000_000
        p = NativePairer(15, sdk_metadata=fields, clock_ns=lambda: now)
        p.activate()
        rgb = child(1, 66, domain='system_time')
        rgb.supports_frame_metadata = Mock(return_value=True)
        p.push('color', rgb, 66_000_000)
        self.assertIsNotNone(send(p, 'depth', 1, 66))
        rgb.supports_frame_metadata.assert_not_called()
        for number in range(2, 13):
            send(p, 'color', number, number*66)
            self.assertIsNotNone(send(p, 'depth', number, number*66))
        send(p, 'depth', 13, 858)
        now += 5_000_000
        send(p, 'depth', 14, 924)
        now += 10_000_000
        rgb = child(13, 898, domain='system_time')
        rgb.supports_frame_metadata = lambda key: key != 2
        rgb.get_frame_metadata = Mock(side_effect=[123456, RuntimeError('SDK metadata unavailable')])
        with self.assertRaisesRegex(RuntimeError, r'unmatched_timestamp \(depth, frame 13\)'):
            p.push('color', rgb, None)
        diagnostic = p.failure['diagnostics']
        color = diagnostic['compared_candidates']['color']
        depth = diagnostic['compared_candidates']['depth']
        self.assertEqual((color['number'], depth['number']), (13, 13))
        self.assertEqual((color['timestamp_ms'], depth['timestamp_ms']), (898, 858))
        self.assertEqual(diagnostic['color_minus_depth_ms'], 40)
        self.assertAlmostEqual(diagnostic['abs_skew_excess_ms'], 40 - 500/15)
        self.assertEqual(diagnostic['comparison_host_ns'], now)
        self.assertEqual(depth['host_callback_ns'], 858_000_000)
        self.assertEqual(depth['pairing_queue_wait_ns'], 15_000_000)
        self.assertEqual(color['host_callback_ns'], 'NOT_RECORDED')
        self.assertEqual(color['callback_to_pairing_queue_ns'], 'NOT_RECORDED')
        self.assertEqual(color['sdk_metadata_raw'], dict(sensor_timestamp=123456, frame_timestamp='NOT_RECORDED',
                         backend_timestamp='NOT_RECORDED', time_of_arrival='NOT_RECORDED'))
        self.assertEqual(diagnostic['next_candidates']['color'], 'NOT_RECORDED')
        self.assertEqual(diagnostic['next_candidates']['depth']['number'], 14)
        self.assertEqual(diagnostic['pairing_queue_depth'], {'color': 1, 'depth': 2})
        self.assertEqual(len(diagnostic['recent_frames']), RECENT_FRAME_LIMIT)
        self.assertEqual(len(diagnostic['recent_frame_metadata']), RECENT_FRAME_LIMIT)
        self.assertEqual(diagnostic['recent_frame_metadata'][0]['number'], 6)
        self.assertEqual(diagnostic['recent_frame_metadata'][-1]['sdk_metadata']['backend_timestamp']['status'], 'READ_ERROR')
        self.assertEqual(diagnostic['recent_frames'][0]['number'], 6)
        self.assertEqual(diagnostic['recent_frames'][-1]['number'], 13)
        self.assertEqual({tuple(item) for item in diagnostic['recent_frames']},
                         {('stream', 'number', 'timestamp_ms', 'timestamp_domain', 'host_callback_ns')})

    def test_gap_snapshot_distinguishes_enqueued_callback_from_processed_input(self):
        rs = SimpleNamespace(processing_block=Mock(), frame_metadata_value=SimpleNamespace(backend_timestamp=0))
        source = NativeRGBDSource(None, rs, 15)
        source.pairer.activate()
        color = source._callback('color')
        depth = source._callback('depth')
        first = child(1, 66, domain='system_time')
        first.supports_frame_metadata = Mock(return_value=True)
        color(first)
        depth(child(1, 67, stream='depth', uid=2, domain='system_time'))
        ready, accepted = source.try_wait_for_frames(250)
        self.assertTrue(ready)
        self.assertGreaterEqual(accepted.created_host_ns, accepted.host_ns)
        first.supports_frame_metadata.assert_not_called()

        rgb = child(2, 132, domain='system_time')
        rgb.supports_frame_metadata = Mock(return_value=True)
        rgb.get_frame_metadata = Mock(return_value=12345)
        color(rgb)
        self.assertEqual(source.try_wait_for_frames(25), (False, None))
        rgb.get_frame_metadata.assert_called_once_with(0)
        depth(child(2, 133, stream='depth', uid=2, domain='system_time'))
        source.end_input()
        diagnostic = source.receive_gap_snapshot()
        self.assertEqual(diagnostic['sdk_input_queue_depth'], 1)
        self.assertEqual(diagnostic['pairing_queue_depth'], {'color': 1, 'depth': 0})
        last_depth = diagnostic['streams']['depth']
        self.assertEqual((last_depth['callback_count'], last_depth['pairer_input_count']), (2, 1))
        self.assertGreater(last_depth['last_callback_host_ns'], last_depth['last_processed']['host_callback_ns'])
        self.assertEqual(last_depth['last_processed']['number'], 1)
        self.assertEqual(last_depth['last_processed']['timestamp_ms'], 67)
        self.assertEqual(last_depth['last_processed']['sdk_metadata_raw']['backend_timestamp'], 'NOT_RECORDED')
        last_color = diagnostic['streams']['color']['last_processed']
        self.assertEqual(last_color['sdk_metadata_raw']['backend_timestamp'], 12345)
        self.assertEqual(last_color['sdk_metadata_raw']['time_of_arrival'], 'NOT_RECORDED')
        self.assertEqual(last_color['sdk_metadata']['backend_timestamp'], dict(status='MEASURED', raw_value=12345))
        self.assertEqual(last_color['sdk_metadata']['time_of_arrival'], dict(status='NOT_SUPPORTED'))
        self.assertEqual(len(diagnostic['recent_frame_metadata']), 3)
        rgb.get_frame_metadata.assert_called_once_with(0)

    def test_measured_gaps_between_pairs_are_not_hidden_by_restart(self):
        p=NativePairer(30)
        for i in range(1,4):
            send(p,'depth',i,i*33)
            send(p,'color',i,i*33+6)
        p.activate()
        with self.assertRaisesRegex(RuntimeError,'sensor_number_or_time_gap'):
            send(p,'depth',5,166)


class HashingWriterTest(unittest.TestCase):
    def test_uncompressed_npz_digest_and_values(self):
        rgb=np.arange(12,dtype=np.uint8).reshape(2,2,3)
        depth=np.array([[0,1],[1024,65535]],dtype=np.uint16)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'test.npz'
            with path.open('xb') as stream:
                out=HashingNPZOutput(stream)
                np.savez(out,color_bgr=rgb,depth_z16=depth)
                out.flush()
            self.assertEqual(out.digest.hexdigest(),hashlib.sha256(path.read_bytes()).hexdigest())
            with np.load(path,allow_pickle=False) as payload:
                np.testing.assert_array_equal(payload['color_bgr'],rgb)
                np.testing.assert_array_equal(payload['depth_z16'],depth)

    def test_short_write_fails_before_accepting_digest(self):
        from unittest.mock import Mock
        out=HashingNPZOutput(Mock(**{'write.return_value':2}))
        with self.assertRaisesRegex(OSError,'Short NPZ write'):
            out.write(b'test')
