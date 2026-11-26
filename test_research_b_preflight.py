"""Synthetic input contracts for the read-only Research B preflight."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from raw_rgbd_recording import RawRecordingControl, _sha, pairing_info
from research_b_preflight import inspect_source, main
from test_e0_replay import camera, packet


def fixture_camera():
    metadata = camera()
    for stream in ('color', 'depth'):
        metadata['streams'][stream].update(width=64, height=48)
    return metadata


def fixture_packet(number, stamp, *, depth=True):
    sample = packet(number, stamp, depth=depth)
    color = np.zeros((48, 64, 3), dtype=np.uint8)
    depth_array = np.ones((48, 64), dtype=np.uint16) if depth else None
    sample.native_frames.get_color_frame().get_data = lambda: color
    if depth:
        sample.native_frames.get_depth_frame().get_data = lambda: depth_array
    sample.color_bgr, sample.depth_z16, sample.camera = color, depth_array, fixture_camera()
    return sample


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def save(self, packets, *, calibration=fixture_camera, termination=None):
        capture = RawRecordingControl(self.root / 'raw_rgbd', initial='on',
            scope='SYNTHETIC_STRUCTURAL_TEST_ONLY',
            session_context={'participant_id': 'P90', 'session_label': 'S1', 'repetition': 1})
        capture.bind(calibration)
        capture.begin_session()
        for index, sample in enumerate(packets, 1):
            row = {'receive_index': index, 'receive_end_ns': index}
            capture.observe_input(sample.native_frames, row)
            capture.capture(sample.native_frames, row, armed=False, active_segment=None)
        capture.finish(termination=termination)
        return self.root / 'raw_rgbd/clip_0001'

    def test_session_and_clip_use_the_same_read_only_packet_checks(self):
        clip = self.save([fixture_packet(1, 100.0), fixture_packet(2, 200.0)])
        before = {path: _sha(path) for path in self.root.rglob('*') if path.is_file()}
        session = inspect_source(self.root)
        standalone = inspect_source(clip)
        self.assertEqual(session['packet_counts'], standalone['packet_counts'])
        self.assertEqual(session['packet_counts']['paired'], 2)
        self.assertEqual(session['input_checks'], 'PASS')
        self.assertEqual(session['status'], 'CONDITIONAL')
        self.assertEqual(session['participant_code'], 'RECORDED_UNCONFIRMED')
        self.assertEqual(standalone['participant_code'], 'UNKNOWN')
        self.assertEqual(session['ground_truth'], 'HUMAN_REVIEW_REQUIRED')
        self.assertEqual(before, {path: _sha(path) for path in self.root.rglob('*') if path.is_file()})

    def test_flags_missing_stream_gap_and_regressing_or_colliding_time(self):
        clip = self.save([fixture_packet(1, 100.1), fixture_packet(4, 100.9),
                          fixture_packet(5, 99.0), fixture_packet(6, 200.0, depth=False)])
        report = inspect_source(clip)
        self.assertEqual(report['input_checks'], 'REVIEW_REQUIRED')
        flags = report['continuity_and_pairing_flags']
        self.assertEqual(flags['missing_depth'], 1)
        self.assertEqual(flags['color.missing_number_estimate'], 2)
        self.assertEqual(flags['color.timestamp_regression_count'], 1)
        self.assertEqual(flags['non_increasing_video_timestamp'], 2)

    def test_incomplete_session_requires_explicit_diagnostic_mode(self):
        self.save([fixture_packet(1, 100.0)], termination='panel_closed')
        with self.assertRaisesRegex(ValueError, 'allow-incomplete'):
            inspect_source(self.root)
        report = inspect_source(self.root, allow_incomplete=True)
        self.assertEqual(report['input_checks'], 'REVIEW_REQUIRED')
        self.assertEqual(report['source_completion_status'], 'INTERRUPTED')

    def test_invalid_depth_scale_fails_before_replay(self):
        clip = self.save([fixture_packet(1, 100.0)], calibration=lambda: {**fixture_camera(), 'depth_scale_m': 0})
        with self.assertRaisesRegex(ValueError, 'depth scale'):
            inspect_source(clip)

    def test_payload_tampering_returns_cli_failure(self):
        clip = self.save([fixture_packet(1, 100.0)])
        (clip / 'frames/00000001.npz').write_bytes(b'tampered')
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(['--input', str(clip)]), 1)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'FAIL')

    def test_source_with_no_pairs_fails(self):
        clip = self.save([fixture_packet(1, 100.0, depth=False)])
        with self.assertRaisesRegex(ValueError, 'No paired'):
            inspect_source(clip)

    def test_native_file_dispatch_and_hash_pin_use_a_mocked_sdk_reader(self):
        source = self.root / 'sample.bag'
        source.write_bytes(b'synthetic marker')
        sample = fixture_packet(1, 100.0)
        sample.record['pairing'] = pairing_info(sample.record['sensors'], {'color_bgr': 1, 'depth_z16': 1})
        with patch('research_b_preflight.db3_packets', return_value=(p for p in [sample])) as reader:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                inspect_source(source, expected_sha256='0' * 64)
            reader.assert_not_called()
            report = inspect_source(source, expected_sha256=_sha(source))
            reader.assert_called_once_with(source.resolve())
        self.assertEqual(report['kind'], 'REALSENSE_FILE')
        self.assertEqual(report['inference_replay'], 'NOT_TESTED')

    def test_container_with_unsupported_extension_fails(self):
        source = self.root / 'sample.mcap'
        source.touch()
        with self.assertRaisesRegex(ValueError, 'DB3/BAG'):
            inspect_source(source)
