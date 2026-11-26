"""Regression coverage for native acquisition and write-once NPZ checksums."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from exchange_native import (MAX_CONSECUTIVE_UNPAIRED, NativePairer, NativeRGBDSource, RECENT_FRAME_LIMIT,
                             SDK_METADATA_FIELDS)
from raw_rgbd_recording import HashingNPZOutput, native_packet
from test_frame_provenance import child


def send(pairer, name, number, stamp, domain='system_time'):
    frame = child(number, stamp, stream=name, uid=1 if name=='color' else 2, domain=domain)
    return pairer.push(name, frame, int(stamp*1e6))


class TimedInput:
    def __init__(self):
        self.now = 10_000_000_000
        self.origin = self.now
        self.pairer = NativePairer(15, clock_ns=lambda: self.now)
        self.pairer.activate()
        self.frames = {}

    def send(self, name, number, stamp, callback_ms, *, domain='system_time', uid=None):
        at = self.origin + round(callback_ms * 1e6)
        assert at >= self.now
        self.now = at
        default_uid = 1 if name == 'color' else 2
        sample = child(number, stamp, stream=name, uid=uid if uid is not None else default_uid, domain=domain)
        self.frames[name, number] = sample
        return self.pairer.push(name, sample, at)


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

    def test_incompatible_clocks_are_never_paired(self):
        p = NativePairer(15)
        p.activate()
        send(p, 'depth', 1, 100)
        with self.assertRaisesRegex(RuntimeError, 'incomparable_clocks'):
            send(p, 'color', 1, 100, 'hardware_clock')
        diagnostic = p.failure['diagnostics']
        self.assertEqual(diagnostic['color_minus_depth_ms'], 'NOT_RECORDED')
        self.assertEqual(diagnostic['abs_skew_excess_ms'], 'NOT_RECORDED')
        self.assertEqual(diagnostic['compared_candidates']['color']['timestamp_domain'], 'hardware_clock')

    def test_observed_p04_and_hw5_order_recovers_exact_original_frames(self):
        # Independent SDK and callback clocks are rebased. Preserve the recorded callback order.
        for depths, colors, stamps, callbacks in (
            ((963, 964, 965), (967, 968),
             (0, 0.479248, 66.358398, 132.874023, 138.771240), (0, 1.0757, 66.3246, 132.8225, 139.3559)),
            ((1440, 1441, 1442), (1444, 1445),
             (0, 0.444092, 66.575684, 133.080078, 139.158203), (0, 1.1178, 66.5835, 133.0853, 139.8282)),
        ):
            with self.subTest(depths=depths):
                feed = TimedInput()
                order = [('depth', depths[0]), ('color', colors[0]), ('depth', depths[1]),
                         ('depth', depths[2]), ('color', colors[1])]
                outputs = [feed.send(name, number, 1000 + stamp, at)
                           for (name, number), stamp, at in zip(order, stamps, callbacks)]
                self.assertEqual([i for i, output in enumerate(outputs) if output], [1])
                first = outputs[1]
                # A synthetic following pair advances both streams past the recorded candidate's window.
                self.assertIsNone(feed.send('depth', depths[2]+1, 1000 + stamps[3] + 66.67, callbacks[3]+66.67))
                resumed = feed.send('color', colors[1]+1, 1000 + stamps[4] + 66.67, callbacks[4]+66.67)
                self.assertIs(first.depth, feed.frames['depth', depths[0]])
                self.assertIs(first.color, feed.frames['color', colors[0]])
                self.assertIs(resumed.depth, feed.frames['depth', depths[2]])
                self.assertIs(resumed.color, feed.frames['color', colors[1]])
                self.assertEqual(resumed.depth.get_timestamp(), 1000 + stamps[3])
                self.assertEqual(resumed.color.get_timestamp(), 1000 + stamps[4])
                self.assertAlmostEqual(resumed.color.get_timestamp() - resumed.depth.get_timestamp(),
                                       stamps[4] - stamps[3])
                discarded, = resumed.recovery['excluded']
                self.assertEqual((discarded['stream'], discarded['sensor']['number']), ('depth', depths[1]))
                self.assertEqual(discarded['sensor']['timestamp_ms'], 1000 + stamps[2])
                self.assertEqual(resumed.recovery['status'], 'RECOVERED')
                self.assertIsNone(feed.pairer.failure)
                following = feed.pairer.poll()
                self.assertIs(following.depth, feed.frames['depth', depths[2]+1])
                self.assertIs(following.color, feed.frames['color', colors[1]+1])
                self.assertIsNone(following.recovery)
                self.assertIsNone(feed.pairer.poll())

    def retry_prefix(self):
        # P04 retry callback order and rebased timestamp differences up to the exception.
        feed = TimedInput()
        self.assertIsNone(feed.send('color', 158, 1000 - 3.3994, 0))
        self.assertIsNotNone(feed.send('depth', 154, 1000, 2.7277))
        self.assertIsNone(feed.send('depth', 155, 1066.6802, 69.4174))
        self.assertIsNone(feed.send('color', 159, 1128.0313, 131.3812))
        return feed

    def test_following_candidate_can_arrive_later(self):
        feed = self.retry_prefix()
        self.assertEqual(feed.pairer.recoveries[0]['status'], 'PENDING')
        # A synthetic continuation, since the recording stops before this callback.
        self.assertIsNone(feed.send('depth', 156, 1133.36, 136.2))
        self.assertIsNone(feed.send('color', 160, 1194.70, 198.05))
        pair = feed.send('depth', 157, 1200.03, 202.87)
        self.assertEqual((pair.color.get_frame_number(), pair.depth.get_frame_number()), (159, 156))
        self.assertEqual(pair.recovery['excluded'][0]['sensor']['number'], 155)

    def p05_gapped_prefix(self, *, mirror=False):
        feed = TimedInput()
        slow, steady = ('depth', 'color') if mirror else ('color', 'depth')
        # Recorded P05 S1 18:02 shape, rebased to distinct SDK and host clocks.
        # The displayed SDK frame numbers advance by one, including the slow stream.
        feed.send(steady, 69, 1000, 0)
        self.assertIsNotNone(feed.send(slow, 70, 994.8, 0.9))
        feed.send(steady, 70, 1064.754, 64.775)
        self.assertIsNone(feed.send(slow, 71, 1128.516, 134.5837))
        self.assertEqual(feed.pairer.recovery_deadline_ns-feed.now, 233_333_334)
        first, = feed.pairer.recoveries
        self.assertEqual(first['excluded'][0]['stream'], steady)
        return feed, slow, steady

    def test_p05_timing_without_confirmation_still_aborts(self):
        for mirror in (False, True):
            with self.subTest(mirror=mirror):
                feed, slow, steady = self.p05_gapped_prefix(mirror=mirror)
                # Only the prefix was observed. A plausible first candidate
                # alone cannot establish that its two timestamp windows closed.
                feed.send(steady, 71, 1131.421, 135)
                feed.now = feed.pairer.recovery_deadline_ns
                with self.assertRaisesRegex(RuntimeError, 'unmatched_timestamp_timeout'):
                    feed.pairer.poll()

    def test_timely_p05_confirmation_survives_delayed_queue_processing(self):
        for mirror in (False, True):
            for late in (False, True):
                with self.subTest(mirror=mirror, late=late):
                    feed, slow, steady = self.p05_gapped_prefix(mirror=mirror)
                    source = NativeRGBDSource(None, SimpleNamespace(processing_block=Mock()), 15)
                    source.pairer = feed.pairer
                    deadline = feed.pairer.recovery_deadline_ns
                    # Synthetic continuation. The producer reaches the queue
                    # before the processing thread resumes after the deadline.
                    frames = []
                    for name, num, stamp, at in (
                        (steady, 71, 1131.421, deadline - 120_000_000),
                        (slow, 72, 1195.183, deadline - 60_000_000),
                        (steady, 72, 1198.088, deadline if late else deadline - 1),
                    ):
                        sample = child(num, stamp, stream=name, uid=1 if name == 'color' else 2,
                                       domain='system_time')
                        frames.append(sample)
                        source.input.put_nowait((name, sample, at))
                    feed.now = deadline + 5_000_000
                    with patch('exchange_native.time.perf_counter_ns', return_value=feed.now):
                        if late:
                            with self.assertRaisesRegex(RuntimeError, 'unmatched_timestamp_timeout'):
                                source.try_wait_for_frames(250)
                            self.assertEqual(feed.pairer.recoveries[0]['status'], 'FAILED')
                            continue
                        ready, recovered = source.try_wait_for_frames(250)
                        self.assertTrue(ready)
                        self.assertIs(getattr(recovered, slow), feed.frames[slow, 71])
                        self.assertIs(getattr(recovered, steady), frames[0])
                        self.assertEqual(recovered.recovery['status'], 'RECOVERED')
                        self.assertEqual(len(recovered.recovery['excluded']), 1)
                        self.assertLess(recovered.recovery['confirmation_latest_callback_ns'], deadline)
                        self.assertGreater(recovered.recovery['ended_host_ns'], deadline)
                        ready, following = source.try_wait_for_frames(250)
                        self.assertTrue(ready)
                        self.assertIs(getattr(following, slow), frames[1])
                        self.assertIs(getattr(following, steady), frames[2])
                        self.assertIsNone(following.recovery)
                        self.assertIsNone(source.pairer.poll())

    def test_no_following_candidate_fails_at_deadline_and_stays_failed(self):
        feed = self.retry_prefix()
        p = feed.pairer
        deadline = p.recovery_deadline_ns
        self.assertEqual(deadline - feed.now, 233_333_334)
        p.expire_recovery(deadline - 1)
        feed.now = deadline
        with self.assertRaisesRegex(RuntimeError, 'unmatched_timestamp_timeout'):
            p.expire_recovery(feed.now)
        with self.assertRaisesRegex(RuntimeError, 'unmatched_timestamp_timeout'):
            feed.send('depth', 156, 1133.36, 365)
        incident, = p.recoveries
        self.assertEqual(incident['status'], 'FAILED')
        self.assertEqual([item['sensor']['number'] for item in incident['excluded']], [155])

    def test_ambiguous_recovery_fails_with_buffered_or_late_second_candidate(self):
        for buffered in (True, False):
            with self.subTest(buffered=buffered):
                feed = TimedInput()
                feed.send('depth', 1, 1000, 0)
                first = feed.send('color', 1, 1006, 6)
                self.assertEqual(first.depth.get_frame_number(), 1)
                feed.send('depth', 2, 1066, 66)
                feed.send('depth', 3, 1124, 124)
                if buffered:
                    feed.send('depth', 4, 1152, 152)
                    with self.assertRaisesRegex(RuntimeError, 'ambiguous_timestamp_recovery'):
                        feed.send('color', 2, 1156, 156)
                else:
                    self.assertIsNone(feed.send('color', 2, 1156, 156))
                    with self.assertRaisesRegex(RuntimeError, 'ambiguous_timestamp_recovery'):
                        feed.send('depth', 4, 1152, 160)
                incident, = feed.pairer.recoveries
                self.assertEqual([item['sensor']['number'] for item in incident['excluded']], [2])
                self.assertEqual(incident['status'], 'FAILED')
                self.assertEqual([item[1]['number'] for item in feed.pairer.pending['depth']], [3, 4])
                with self.assertRaisesRegex(RuntimeError, 'ambiguous_timestamp_recovery'):
                    feed.pairer.poll()

    def test_incomplete_candidate_window_fails_even_with_one_eligible_pair(self):
        feed = self.retry_prefix()
        self.assertIsNone(feed.send('depth', 156, 1133.36, 136.2))
        self.assertIsNone(feed.send('color', 160, 1194.70, 198.05))
        feed.now = feed.pairer.recovery_deadline_ns
        with self.assertRaisesRegex(RuntimeError, 'unmatched_timestamp_timeout'):
            feed.pairer.poll()
        self.assertEqual(feed.pairer.recoveries[0]['status'], 'FAILED')

    def test_domain_or_profile_change_during_recovery_remains_terminal(self):
        for change in (dict(domain='hardware_clock'), dict(uid=9)):
            with self.subTest(change=change):
                feed = self.retry_prefix()
                with self.assertRaisesRegex(RuntimeError, 'stream_boundary'):
                    feed.send('depth', 156, 1133.36, 136.2, **change)
                self.assertEqual(feed.pairer.recoveries[0]['status'], 'FAILED')
                self.assertNotIn('resumed_sensors', feed.pairer.recoveries[0])

    def test_consecutive_unpaired_frames_at_and_beyond_limit(self):
        for exceeds_limit in (False, True):
            with self.subTest(exceeds_limit=exceeds_limit):
                feed = TimedInput()
                feed.send('depth', 1, 1000, 0)
                feed.send('color', 1, 1006, 6)
                for number in range(2, 5):
                    ms = (number-1)*67
                    feed.send('depth', number, 1000+ms, ms)
                if exceeds_limit:
                    with self.assertRaisesRegex(RuntimeError, 'unmatched_timestamp_skip_limit'):
                        feed.send('color', 2, 1274, 274)
                else:
                    self.assertIsNone(feed.send('color', 2, 1207, 207))
                    self.assertIsNone(feed.send('depth', 5, 1268, 268))
                    resumed = feed.send('color', 3, 1274, 274)
                    self.assertEqual((resumed.color.get_frame_number(), resumed.depth.get_frame_number()), (2, 4))
                incident, = feed.pairer.recoveries
                self.assertEqual([item['sensor']['number'] for item in incident['excluded']], [2, 3])
                self.assertEqual(incident['status'], 'FAILED' if exceeds_limit else 'RECOVERED')
                self.assertEqual(incident['excluded'][-1]['reason'], 'no_partner_in_timestamp_window')
                if exceeds_limit:
                    self.assertEqual(incident['blocked_candidate']['reason'], 'recovery_skip_limit')
                    self.assertEqual(incident['blocked_candidate']['sensor']['number'], 4)
                    self.assertEqual(feed.pairer.pending['depth'][0][1]['number'], 4)

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
        send(p, 'depth', 14, 950)
        now += 10_000_000
        rgb = child(13, 898, domain='system_time')
        rgb.supports_frame_metadata = lambda key: key != 2
        rgb.get_frame_metadata = Mock(side_effect=[123456, RuntimeError('SDK metadata unavailable')])
        self.assertIsNone(p.push('color', rgb, None))
        compared_at = now
        now = p.recovery_deadline_ns
        with self.assertRaisesRegex(RuntimeError, r'unmatched_timestamp_timeout \(depth, frame 13\)'):
            p.expire_recovery(now)
        diagnostic = p.failure['diagnostics']
        color = diagnostic['compared_candidates']['color']
        depth = diagnostic['compared_candidates']['depth']
        self.assertEqual((color['number'], depth['number']), (13, 13))
        self.assertEqual((color['timestamp_ms'], depth['timestamp_ms']), (898, 858))
        self.assertEqual(diagnostic['color_minus_depth_ms'], 40)
        self.assertAlmostEqual(diagnostic['abs_skew_excess_ms'], 40 - 500/15)
        self.assertEqual(diagnostic['comparison_host_ns'], compared_at)
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

    def test_complete_rgb_or_depth_number_loss_still_aborts(self):
        for stream in ('color', 'depth'):
            with self.subTest(stream=stream):
                feed = TimedInput()
                feed.send('depth', 1, 1000, 0)
                feed.send('color', 1, 1006, 6)
                with self.assertRaisesRegex(RuntimeError, 'sensor_number_or_time_gap'):
                    feed.send(stream, 3, 1133, 139)
                self.assertEqual(feed.pairer.failure['stream'], stream)
                self.assertEqual(feed.pairer.failure['sensor']['number'], 3)

    def test_native_stop_releases_both_sensors_when_one_reports_an_error(self):
        source = NativeRGBDSource(None, SimpleNamespace(processing_block=Mock()), 15)
        rgb, depth = Mock(), Mock()
        rgb.stop.side_effect = RuntimeError('synthetic sensor stop failure')
        source.opened.extend([('color', rgb), ('depth', depth)])
        source.started.extend([rgb, depth])
        with self.assertRaisesRegex(RuntimeError, 'synthetic sensor stop failure'):
            source.stop()
        for sensor in (rgb, depth):
            sensor.stop.assert_called_once()
            sensor.close.assert_called_once()
        self.assertFalse(source.accepting)
        self.assertFalse(source.started)
        self.assertFalse(source.opened)


PERIOD_MS = 1000 / 15
# Windows D455 runs without UVC metadata: system_time stamps are host arrival
# times and frame numbers are host counters. RGB arrived ~6 ms after Depth in
# P04, P05 and C3 recordings.
COLOR_AFTER_DEPTH_MS = 6.0
CALLBACK_AFTER_STAMP_MS = 0.25


def grid_feed(slots, *, absent=None, shift=None):
    """Deliver a synthetic 15 FPS RGB-D grid in callback order.

    An absent slot is never delivered and leaves the host frame numbers
    contiguous. A shift moves one delivery, including its arrival timestamp.
    Returns the feed, emitted pairs, the terminal error and the true capture
    slot of every delivered frame.
    """
    absent, shift = absent or {}, shift or {}
    events, truth = [], {}
    for name, offset in (('depth', 0.0), ('color', COLOR_AFTER_DEPTH_MS)):
        number = 0
        for slot in range(slots):
            if slot in absent.get(name, ()):
                continue
            number += 1
            stamp = 1000 + slot * PERIOD_MS + offset + shift.get(name, {}).get(slot, 0.0)
            truth[name, number] = slot
            events.append((stamp + CALLBACK_AFTER_STAMP_MS, name, number, stamp))
    events.sort()
    feed = TimedInput()
    pairs, error = [], None
    try:
        for callback_ms, name, number, stamp in events:
            pair = feed.send(name, number, stamp, callback_ms)
            # NativeRGBDSource drains ready pairs only outside a pending recovery.
            while pair is not None:
                pairs.append(pair)
                pair = feed.pairer.poll() if feed.pairer.recovery_deadline_ns is None else None
    except RuntimeError as exc:
        error = exc
    return feed, pairs, error, truth


class UpstreamSlotLossTest(unittest.TestCase):
    """Timing shapes observed in P04, P05 and C3 at 15 FPS."""

    def assert_true_one_use_pairs(self, pairs, truth):
        used, last = set(), None
        for pair in pairs:
            numbers = pair.color.get_frame_number(), pair.depth.get_frame_number()
            # A pair may only join frames from the same capture slot.
            self.assertEqual(truth['color', numbers[0]], truth['depth', numbers[1]])
            self.assertLessEqual(abs(pair.color.get_timestamp() - pair.depth.get_timestamp()), 500 / 15)
            for key in zip(('color', 'depth'), numbers):
                self.assertNotIn(key, used)
                used.add(key)
            if last is not None:
                self.assertTrue(numbers[0] > last[0] and numbers[1] > last[1])
            last = numbers

    def excluded(self, feed, truth):
        return [(item['stream'], truth[item['stream'], item['sensor']['number']])
                for incident in feed.pairer.recoveries for item in incident['excluded']]

    def test_normal_grid_with_observed_delivery_jitter_pairs_every_slot(self):
        # SDK-only probe 18:17: late deliveries up to 26.1 ms, followed by early ones.
        feed, pairs, error, truth = grid_feed(300, shift={'color': {50: 26.1, 120: -10.9},
                                                          'depth': {80: 16.5, 81: -8.2}})
        self.assertIsNone(error)
        self.assertEqual(len(pairs), 300)
        self.assertEqual(feed.pairer.recoveries, [])
        self.assert_true_one_use_pairs(pairs, truth)

    def test_one_absent_slot_excludes_only_the_orphan_of_the_other_stream(self):
        for stream, other in (('color', 'depth'), ('depth', 'color')):
            with self.subTest(stream=stream):
                # P05_B 18:08 recovered six times with this shape: an early frame, then one absent slot.
                feed, pairs, error, truth = grid_feed(100, absent={stream: {40}}, shift={stream: {39: -10.9}})
                self.assertIsNone(error)
                self.assertEqual(self.excluded(feed, truth), [(other, 40)])
                self.assertEqual([incident['status'] for incident in feed.pairer.recoveries], ['RECOVERED'])
                self.assertEqual(len(pairs), 99)
                self.assert_true_one_use_pairs(pairs, truth)

    def test_recorded_p05b_terminal_state_is_reproduced_with_the_previous_wait(self):
        for previous_wait in (True, False):
            with self.subTest(previous_wait=previous_wait):
                # P05_S1_r1_20261126_180803_613, rebased: SDK ms to Depth 149 (+1000),
                # callbacks to the Depth 149 callback (26677225217300 ns).
                feed = TimedInput()
                if previous_wait:
                    feed.pairer.recovery_wait_ns = (2 * 1_000_000_000 + 14) // 15
                self.assertIsNone(feed.send('depth', 149, 1000.0, 0.0))
                self.assertIsNotNone(feed.send('color', 144, 1000.5226, 1.138))
                self.assertIsNone(feed.send('depth', 150, 1066.9486, 66.926))
                # RGB 145 arrives 130.34 ms after RGB 144 (backend delta 133 ms).
                self.assertIsNone(feed.send('color', 145, 1130.8610, 131.4452))
                incident, = feed.pairer.recoveries
                self.assertEqual([(i['stream'], i['sensor']['number']) for i in incident['excluded']],
                                 [('depth', 150)])
                # Recorded at the abort: Depth 151 and 152 had been processed, RGB 146 had not,
                # and the SDK input queue was empty. Their stamps were not recorded; grid values.
                self.assertIsNone(feed.send('depth', 151, 1133.6153, 133.626))
                self.assertIsNone(feed.send('depth', 152, 1200.2820, 200.326))
                # The recorded abort: 267.142 ms, still without another RGB callback.
                feed.now = feed.origin + 267_141_700
                pending = lambda: {name: [item[1]['number'] for item in entries]
                                   for name, entries in feed.pairer.pending.items()}
                if previous_wait:
                    with self.assertRaisesRegex(RuntimeError, r'unmatched_timestamp_timeout \(depth, frame 150\)'):
                        feed.pairer.poll()
                    self.assertEqual(incident['status'], 'FAILED')
                    # The recorded pending_at_stop was 3 with an empty SDK input queue.
                    self.assertEqual(pending(), {'color': [145], 'depth': [151, 152]})
                    continue
                self.assertIsNone(feed.pairer.poll())
                self.assertEqual(pending(), {'color': [145], 'depth': [151, 152]})
                # Synthetic continuation: the next RGB frame follows one more absent slot.
                # Single-slot RGB intervals in the same session were 139.8-144.6 ms.
                self.assertIsNone(feed.send('depth', 153, 1266.9487, 267.5))
                resumed = feed.send('color', 146, 1272.8610, 273.4452)
                self.assertEqual((resumed.color.get_frame_number(), resumed.depth.get_frame_number()), (145, 151))
                self.assertEqual(resumed.recovery['status'], 'RECOVERED')
                self.assertGreater(resumed.recovery['confirmation_latest_callback_ns'] - incident['started_host_ns'],
                                   (2 * 1_000_000_000 + 14) // 15)
                self.assertIsNone(feed.send('depth', 154, 1333.6153, 333.9))
                second = feed.send('color', 147, 1339.5000, 340.1)
                self.assertEqual((second.color.get_frame_number(), second.depth.get_frame_number()), (146, 153))
                self.assertEqual([(i['stream'], i['sensor']['number']) for i in second.recovery['excluded']],
                                 [('depth', 152)])
                following = feed.pairer.poll()
                self.assertEqual((following.color.get_frame_number(), following.depth.get_frame_number()), (147, 154))
                self.assertIsNone(following.recovery)
                self.assertIsNone(feed.pairer.failure)

    def test_recorded_1919_late_rgb_delivery_aborts_as_ambiguous_with_either_wait(self):
        for previous_wait in (True, False):
            with self.subTest(previous_wait=previous_wait):
                # user_check/ENGINEERING_TEST_300s_20261126_191928, rebased: SDK ms to
                # 1795688394000, callbacks to the Depth 363 callback + 200 ms. MF backend
                # receipt (ms): Depth 362 318, RGB 366 324, Depth 363 385, RGB 367 391,
                # Depth 364 452, RGB 368 457. RGB 367 reached librealsense 96 ms after its
                # backend receipt (others 67-68 ms), so its arrival stamp is 29 ms late.
                feed = TimedInput()
                if previous_wait:
                    feed.pairer.recovery_wait_ns = (2 * 1_000_000_000 + 14) // 15
                pairs = [feed.send('depth', 361, 1319.1997, 66.8946), feed.send('color', 365, 1324.8657, 73.1785),
                         feed.send('depth', 362, 1385.6389, 133.3206), feed.send('color', 366, 1391.5972, 139.9475)]
                self.assertEqual([(p.color.get_frame_number(), p.depth.get_frame_number()) for p in pairs if p],
                                 [(365, 361), (366, 362)])
                self.assertIsNone(feed.send('depth', 363, 1452.3208, 200.0))
                # RGB 367 - Depth 363 = 35.05 ms > 33.333 ms: Depth 363 has no partner in this clock.
                self.assertIsNone(feed.send('color', 367, 1487.3684, 236.0215))
                incident, = feed.pairer.recoveries
                self.assertEqual([(i['stream'], i['sensor']['number']) for i in incident['excluded']],
                                 [('depth', 363)])
                # Depth 364 is within the window of RGB 367 (-31.76 ms) ...
                self.assertIsNone(feed.send('depth', 364, 1519.1323, 266.8942))
                # ... and of RGB 368 (+6.27 ms). Two candidates: no unique pair can be proven.
                with self.assertRaisesRegex(RuntimeError, r'ambiguous_timestamp_recovery \(color, frame 368\)'):
                    feed.send('color', 368, 1525.4036, 273.7228)
                self.assertEqual(incident['status'], 'FAILED')
                self.assertEqual({name: [item[1]['number'] for item in entries]
                                  for name, entries in feed.pairer.pending.items()},
                                 {'color': [367, 368], 'depth': [364]})
                # Recorded: aborted 37.7 ms after the recovery started, far inside either wait.
                self.assertAlmostEqual((incident['ended_host_ns'] - incident['started_host_ns']) / 1e6, 37.7013,
                                       places=3)
                self.assertLess(incident['ended_host_ns'], incident['recovery_deadline_host_ns'])

    def test_absent_slots_after_the_trigger_frame_up_to_the_skip_limit(self):
        for stream, other in (('color', 'depth'), ('depth', 'color')):
            for extra in range(1, MAX_CONSECUTIVE_UNPAIRED + 2):
                with self.subTest(stream=stream, extra=extra):
                    later = set(range(42, 42 + extra))
                    feed, pairs, error, truth = grid_feed(100, absent={stream: {40} | later})
                    self.assert_true_one_use_pairs(pairs, truth)
                    if extra > MAX_CONSECUTIVE_UNPAIRED:
                        self.assertRegex(str(error), 'unmatched_timestamp_timeout')
                        self.assertEqual(feed.pairer.recoveries[-1]['status'], 'FAILED')
                        continue
                    self.assertIsNone(error)
                    self.assertEqual(self.excluded(feed, truth), [(other, slot) for slot in sorted({40} | later)])
                    self.assertTrue(all(i['status'] == 'RECOVERED' for i in feed.pairer.recoveries))
                    self.assertEqual(len(pairs), 100 - 1 - extra)

    def test_sustained_half_rate_stream_records_one_orphan_per_absent_slot(self):
        for stream, other in (('color', 'depth'), ('depth', 'color')):
            with self.subTest(stream=stream):
                absent = set(range(21, 81, 2))
                feed, pairs, error, truth = grid_feed(100, absent={stream: absent})
                self.assertIsNone(error)
                self.assertEqual(self.excluded(feed, truth), [(other, slot) for slot in sorted(absent)])
                self.assertEqual(len(feed.pairer.recoveries), len(absent))
                self.assertEqual(len(pairs), 100 - len(absent))
                self.assert_true_one_use_pairs(pairs, truth)

    def test_delivery_delay_beyond_the_window_aborts_without_a_wrong_pair(self):
        for stream in ('color', 'depth'):
            for delay in (45.0, 60.0):
                with self.subTest(stream=stream, delay=delay):
                    # Arrival-time stamps move with the delivery. The late frame
                    # matches its neighbour's slot, so uniqueness must fail.
                    feed, pairs, error, truth = grid_feed(100, shift={stream: {40: delay}})
                    self.assertRegex(str(error), 'ambiguous_timestamp_recovery')
                    self.assert_true_one_use_pairs(pairs, truth)
                    self.assertEqual(len(pairs), 40)

    def test_timestamp_window_keeps_its_inclusive_boundary(self):
        feed = TimedInput()
        self.assertEqual(feed.pairer.max_skew_ms, 500 / 15)
        feed.send('depth', 1, 1000, 0)
        self.assertIsNotNone(feed.send('color', 1, 1000 + 500 / 15, 34))
        feed.send('depth', 2, 1066.667, 67)
        self.assertIsNone(feed.send('color', 2, 1066.667 + 33.34, 101))
        incident, = feed.pairer.recoveries
        self.assertEqual([(i['stream'], i['sensor']['number']) for i in incident['excluded']], [('depth', 2)])

    def test_recovery_wait_covers_the_skip_limit_and_half_a_period(self):
        for fps, expected in ((15, 233_333_334), (30, 116_666_667)):
            with self.subTest(fps=fps):
                half_periods = 2 * (MAX_CONSECUTIVE_UNPAIRED + 1) + 1
                self.assertEqual(NativePairer(fps).recovery_wait_ns, expected)
                self.assertEqual(expected, -(-half_periods * 1_000_000_000 // (2 * fps)))


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
