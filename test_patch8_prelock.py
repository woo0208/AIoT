"""CAP-005 §39, §41, §44–§48 closed pre-lock classification tests; fake evidence only."""
import ast
import builtins
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import signal
import tempfile
import types
import unittest
from unittest.mock import patch

import patch8_ledger as ledger
import patch8_prelock as prelock
import patch8_protocol as p8


def production(**changes):
    value = dict(slot_kind=p8.E2E, stage="post_reservation", bound_recording_ids=("V01_r131_x",), exit_code=0,
                 operator_declaration="not_operator_initiated", raw_exists=True,
                 raw_probe=dict(exists=True, openable=True, color_frame=True, depth_frame=True))
    value.update(changes)
    return prelock.PrelockEvidence(**value)


def static(**changes):
    return production(slot_kind=p8.STATIC, **changes)


SERIAL_ABSENT = {"probe_ok": True, "pinned_serial_present": False}
SERIAL_PRESENT = {"probe_ok": True, "pinned_serial_present": True}
POWER = {"kind": "host_power_event", "path": "evidence/power.txt", "sha256": "0" * 64,
         "event_time_utc": "2026-10-07T00:00:00Z"}


class ClassifierTests(unittest.TestCase):
    def assert_class(self, evidence, reason, valid, retry, rule=None):
        result = prelock.classify(evidence)
        self.assertEqual((result.reason_code, result.acquisition_valid, result.retry_allowed),
                         (reason, valid, retry), result)
        if rule:
            self.assertEqual(result.rule_id, rule)
        self.assertEqual(result.stage, evidence.stage)
        self.assertTrue(result.evidence_used)
        return result

    def test_guide_q_before_reservation_is_guide_not_satisfied_not_raw_missing(self):
        for declaration in ("not_operator_initiated", "operator_initiated", "unknown"):
            with self.subTest(declaration=declaration):
                evidence = production(slot_kind=p8.FORWARD, stage="pre_reservation", bound_recording_ids=(),
                                      raw_exists=None, raw_probe=None, operator_declaration=declaration)
                self.assert_class(evidence, p8.GUIDE_NOT_SATISFIED, True, False, "R06_GUIDE_Q_PRE_RESERVATION")

    def test_guide_timeout_kill_is_not_machine_evidence(self):
        evidence = production(slot_kind=p8.BODY_ONLY_NEGATIVE, stage="pre_reservation", bound_recording_ids=(),
                              exit_code=None, signal=int(signal.SIGTERM), orchestrator_timeout_kill=True,
                              exception_class="RuntimeError", enumeration=SERIAL_ABSENT, raw_exists=None,
                              raw_probe=None)
        self.assert_class(evidence, p8.GUIDE_NOT_SATISFIED, True, False, "R02_GUIDE_TIMEOUT")

    def test_operator_terminations_are_manual_abort_without_retry(self):
        cases = {
            "operator SIGINT observed": dict(operator_signal_observed="SIGINT", exit_code=None, signal=2),
            "operator SIGTERM observed": dict(operator_signal_observed="SIGTERM", exit_code=None, signal=15),
            "child KeyboardInterrupt": dict(exit_code=1, exception_class="KeyboardInterrupt"),
            "child SIGINT returncode": dict(exit_code=None, signal=int(signal.SIGINT)),
            "operator kill declared": dict(exit_code=None, signal=9, operator_declaration="operator_initiated"),
            "operator window closure declared": dict(exit_code=None, signal=1, operator_declaration="operator_initiated"),
            "operator cable pull declared": dict(exit_code=1, exception_class="RuntimeError", enumeration=SERIAL_ABSENT,
                                                 operator_declaration="operator_initiated"),
            "operator power removal declared": dict(exit_code=1, exception_class="RuntimeError",
                                                    power_evidence=POWER, operator_declaration="operator_initiated"),
            "q during recording declared": dict(exit_code=0, operator_declaration="operator_initiated"),
        }
        for name, changes in cases.items():
            for make in (production, static):
                with self.subTest(name, kind=make.__name__):
                    self.assert_class(make(**changes), p8.MANUAL_ABORT, True, False)

    def test_nonzero_exit_or_signal_alone_is_not_machine_evidence(self):
        for changes in (dict(exit_code=1), dict(exit_code=None, signal=9), dict(exit_code=None, signal=15),
                        dict(exit_code=None), dict(exit_code=1, exception_class="UNLISTED", enumeration=SERIAL_PRESENT),
                        dict(exit_code=None, signal=9, enumeration={"probe_ok": False})):
            with self.subTest(changes=changes):
                self.assert_class(production(**changes), p8.UNCLASSIFIED_TERMINATION, True, False,
                                  "R15_UNCLASSIFIED_ABNORMAL_TERMINATION")

    def test_unknown_operator_causality_fails_closed(self):
        evidence = production(exit_code=1, exception_class="RuntimeError", enumeration=SERIAL_ABSENT,
                              raw_exists=False, raw_probe=None, operator_declaration="unknown",
                              power_evidence=POWER)
        self.assert_class(evidence, p8.UNCLASSIFIED_TERMINATION, True, False)

    def test_raw_file_not_created_requires_post_reservation_and_machine_evidence(self):
        base = dict(raw_exists=False, raw_probe=None, exit_code=1)
        self.assert_class(production(**base, exception_class="RuntimeError"), p8.RAW_FILE_NOT_CREATED, False, True,
                          "R10_RAW_FILE_NOT_CREATED")
        self.assert_class(production(**base, enumeration=SERIAL_ABSENT), p8.RAW_FILE_NOT_CREATED, False, True)
        self.assert_class(production(**base), p8.UNCLASSIFIED_TERMINATION, True, False)
        zero = production(stage="pre_reservation", bound_recording_ids=(), raw_exists=None, raw_probe=None,
                          exit_code=1, exception_class="RuntimeError")
        self.assertNotEqual(prelock.classify(zero).reason_code, p8.RAW_FILE_NOT_CREATED)
        normal = production(raw_exists=False, raw_probe=None, exit_code=0)
        self.assert_class(normal, p8.UNCLASSIFIED_TERMINATION, True, False, "R16_NO_RAW_AFTER_NORMAL_EXIT")

    def test_raw_unreadable_uses_only_probe_booleans(self):
        for missing in ("openable", "color_frame", "depth_frame"):
            probe = dict(dict(exists=True, openable=True, color_frame=True, depth_frame=True), **{missing: False})
            with self.subTest(missing=missing):
                self.assert_class(production(raw_probe=probe), p8.RAW_FILE_UNREADABLE_OR_CORRUPT, False, True,
                                  "R11_RAW_FILE_UNREADABLE_OR_CORRUPT")
        malformed = dict(exists=True, openable=False, color_frame=True, depth_frame=True, frame_count=3)
        self.assert_class(production(raw_probe=malformed), None, True, False, "R17_ACQUISITION_COMPLETED")

    def test_camera_disconnect_and_usb_stream_failure(self):
        self.assert_class(production(exit_code=1, enumeration=SERIAL_ABSENT), p8.CAMERA_DISCONNECT, False, True,
                          "R12_CAMERA_DISCONNECT")
        self.assert_class(production(exit_code=1, exception_class="RuntimeError", enumeration=SERIAL_PRESENT),
                          p8.USB_STREAM_FAILURE, False, True, "R13_USB_STREAM_FAILURE")
        self.assert_class(production(exit_code=1, exception_class="RuntimeError", enumeration=None),
                          p8.UNCLASSIFIED_TERMINATION, True, False)

    def test_power_failure_requires_independent_evidence(self):
        self.assert_class(production(exit_code=None, signal=9), p8.UNCLASSIFIED_TERMINATION, True, False)
        self.assert_class(production(exit_code=None, power_evidence=POWER), p8.POWER_FAILURE, False, True,
                          "R09_POWER_FAILURE")

    def test_static_only_reasons_and_structured_exit_status(self):
        self.assert_class(static(exit_code=10, static_exit_status="operator_abort"), p8.MANUAL_ABORT, True, False,
                          "R05_STATIC_Q_ABORT")
        interrupted = (p8.EXTERNAL_PHYSICAL_INTERRUPTION,)
        self.assert_class(static(observations=interrupted), p8.EXTERNAL_PHYSICAL_INTERRUPTION, False, True,
                          "R14_STATIC_EXTERNAL_INTERRUPTION")
        self.assert_class(static(observations=interrupted, exit_code=1), p8.UNCLASSIFIED_TERMINATION, True, False)
        self.assert_class(production(observations=interrupted), None, True, False, "R17_ACQUISITION_COMPLETED")
        disturbed = (p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED,)
        self.assert_class(static(observations=disturbed), p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED, False, True)
        self.assert_class(static(observations=disturbed, canonical_static_take_exists=True),
                          p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED, False, False)
        self.assert_class(production(observations=disturbed), None, True, False)
        self.assert_class(static(exit_code=11, static_exit_status="record_start_failed", raw_exists=False,
                                 raw_probe=None), p8.RAW_FILE_NOT_CREATED, False, True)
        self.assert_class(static(exit_code=12, static_exit_status="stream_failure", enumeration=SERIAL_PRESENT),
                          p8.USB_STREAM_FAILURE, False, True)

    def test_ambiguous_binding_fails_closed(self):
        self.assert_class(production(bound_recording_ids=("a", "b"), raw_exists=None, raw_probe=None),
                          p8.UNCLASSIFIED_TERMINATION, True, False, "R01_AMBIGUOUS_BINDING")

    def test_retry_budget_and_execution_failure(self):
        evidence = production(exit_code=1, enumeration=SERIAL_ABSENT)
        self.assertTrue(prelock.classify(replace(evidence, attempt_index=2)).retry_allowed)
        self.assertFalse(prelock.classify(replace(evidence, attempt_index=3)).retry_allowed)
        self.assertFalse(prelock.classify(replace(evidence, execution_failed=True)).retry_allowed)

    def test_normal_completion_is_acquisition_valid(self):
        self.assert_class(production(), None, True, False, "R17_ACQUISITION_COMPLETED")

    def test_rule_table_is_closed_and_consistent_with_ledger(self):
        ids = [rule[0] for rule in prelock.CLASSIFIER_RULES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[-1], "R17_ACQUISITION_COMPLETED")
        reasons = {rule[1] for rule in prelock.CLASSIFIER_RULES}
        self.assertEqual(reasons - {None}, set(p8.MACHINE_INVALID_REASONS + p8.VALID_FAIL_REASONS +
                                               p8.STATIC_OPERATOR_INVALID_REASONS))
        for kind in (p8.STATIC, p8.FORWARD, p8.BODY_ONLY_NEGATIVE, p8.E2E):
            for reason in p8.VALID_FAIL_REASONS + (None,):
                self.assertFalse(ledger.lock_retry_allowed(kind, reason, 1, False, False))
                self.assertTrue(ledger.acquisition_valid_for(reason))
        with self.assertRaises(ValueError):
            prelock.classify(production(operator_declaration="maybe"))


class FakeFrames:
    def __init__(self, color, depth):
        self.color, self.depth = color, depth

    def get_color_frame(self):
        return object() if self.color else None

    def get_depth_frame(self):
        return object() if self.depth else None


def fake_rs(frames, start_error=None):
    calls = types.SimpleNamespace(waits=0, stopped=False, file=None)

    class Config:
        def enable_device_from_file(self, path, repeat_playback):
            calls.file = (path, repeat_playback)

    class Pipeline:
        def start(self, config):
            if start_error:
                raise start_error
            playback = types.SimpleNamespace(set_real_time=lambda value: None)
            device = types.SimpleNamespace(as_playback=lambda: playback)
            return types.SimpleNamespace(get_device=lambda: device)

        def try_wait_for_frames(self, timeout):
            calls.waits += 1
            return (True, frames.pop(0)) if frames else (False, None)

        def stop(self):
            calls.stopped = True
    return types.SimpleNamespace(pipeline=Pipeline, config=Config), calls


class RawProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name) / "V01_r1_x.db3"
        self.raw.write_bytes(b"synthetic raw")

    def test_probe_returns_only_four_booleans_and_stops_at_first_color_and_depth(self):
        frames = [FakeFrames(True, False), FakeFrames(False, True)] + [FakeFrames(True, True) for _ in range(500)]
        rs, calls = fake_rs(frames)
        result = prelock.probe_raw_readability(self.raw, rs)
        self.assertEqual(result, dict(exists=True, openable=True, color_frame=True, depth_frame=True))
        self.assertEqual(calls.waits, 2)                       # no frame counting / completeness scan
        self.assertEqual(calls.file, (str(self.raw), False))
        self.assertTrue(calls.stopped)

    def test_missing_unopenable_and_frameless_raw(self):
        rs, _ = fake_rs([])
        self.assertEqual(prelock.probe_raw_readability(Path(self.temp.name) / "absent.db3", rs),
                         dict.fromkeys(prelock.RAW_PROBE_FIELDS, False))
        rs, _ = fake_rs([], start_error=RuntimeError("cannot open"))
        self.assertEqual(prelock.probe_raw_readability(self.raw, rs),
                         dict(exists=True, openable=False, color_frame=False, depth_frame=False))
        rs, _ = fake_rs([FakeFrames(True, False)])
        self.assertEqual(prelock.probe_raw_readability(self.raw, rs),
                         dict(exists=True, openable=True, color_frame=True, depth_frame=False))

    def test_probe_source_has_no_counters_or_quality_analysis(self):
        tree = ast.parse(inspect.getsource(prelock.probe_raw_readability))
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.AugAssign)])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("len", "count", "ratio", "get_timestamp", "get_frame_number", "landmark", "quality"):
            self.assertNotIn(forbidden, names)


class EvidenceAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()

    def test_inventory_uses_names_only_and_binding_diff(self):
        before = prelock.recording_inventory(self.data)
        for name in ("V01_r1_a_camera.json", "V01_r1_a.db3", "V01_r1_a_markers.csv", "notes.txt", "V01_r2_b.bag"):
            (self.data / name).write_bytes(b"{}")
        with patch.object(builtins, "open", side_effect=AssertionError("inventory must not open files")):
            after = prelock.recording_inventory(self.data)
        self.assertEqual(after, ["V01_r1_a", "V01_r2_b"])
        self.assertEqual(prelock.new_recordings(before, after), ["V01_r1_a", "V01_r2_b"])
        self.assertEqual(prelock.recording_inventory(self.data / "absent"), [])

    def test_reservation_reader_exposes_only_two_keys(self):
        camera = self.data / "V01_r131_x_camera.json"
        camera.write_text(json.dumps(dict(recording_id="V01_r131_x", record_file="V01_r131_x.db3",
                                          start_distance={"distance_m": 0.75, "mode": "face"}, serial="S")))
        self.assertEqual(prelock.read_reservation_keys(camera),
                         {"recording_id": "V01_r131_x", "record_file": "V01_r131_x.db3"})
        self.assertTrue(prelock.valid_reservation(self.data, "V01_r131_x", "V01", "131"))
        self.assertFalse(prelock.valid_reservation(self.data, "V01_r131_x", "V01", "121"))
        camera.write_text('{"recording_id": "V01_r131_x", "record_')
        self.assertIsNone(prelock.read_reservation_keys(camera))
        self.assertFalse(prelock.valid_reservation(self.data, "V01_r131_x", "V01", "131"))

    def test_raw_path_is_structural(self):
        (self.data / "V01_r1_x_camera.json").write_text(json.dumps(dict(recording_id="V01_r1_x", record_file=None)))
        self.assertIsNone(prelock.raw_path(self.data, "V01_r1_x"))
        (self.data / "V01_r1_x.bag").write_bytes(b"raw")
        self.assertEqual(prelock.raw_path(self.data, "V01_r1_x").name, "V01_r1_x.bag")

    def test_exception_class_extractor_never_returns_message_text(self):
        log = self.data / "x.stderr.log"
        cases = {
            "[경고] provenance\nTraceback (most recent call last):\n  File \"c.py\", line 1\n    x()\n"
            "RuntimeError: Frame didn't arrive within 5000\n": "RuntimeError",
            "Traceback (most recent call last):\n  File \"c.py\"\nKeyboardInterrupt\n": "KeyboardInterrupt",
            "Traceback (most recent call last):\n  File \"c.py\"\nValueError: RuntimeError\nRuntimeError\n": "UNLISTED",
            "Traceback (most recent call last):\n  File \"a\"\nKeyError: 1\n\nDuring handling of the above exception, "
            "another exception occurred:\n\nTraceback (most recent call last):\n  File \"b\"\n"
            "pyrealsense2.RuntimeError: device disconnected\n": "RuntimeError",
            "no traceback here\n": None,
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                log.write_text(text, encoding="utf-8")
                result = prelock.extract_exception_class(log)
                self.assertEqual(result, expected)
                self.assertIn(result, prelock.WHITELISTED_EXCEPTION_CLASSES + (prelock.UNLISTED_EXCEPTION, None))
        self.assertIsNone(prelock.extract_exception_class(self.data / "absent.log"))

    def test_power_evidence_validation(self):
        root = Path(self.temp.name)
        evidence = root / "evidence" / "power.txt"
        evidence.parent.mkdir()
        evidence.write_bytes(b"host power event log export")
        record = dict(kind="host_power_event", path="evidence/power.txt",
                      sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(), event_time_utc="2026-10-07T00:00:01Z")
        window = ("2026-10-07T00:00:00.000000Z", "2026-10-07T00:00:05.000000Z")
        self.assertEqual(prelock.validate_power_evidence(record, root, *window), record)
        for change in (dict(kind="operator_note"), dict(path="../outside.txt"), dict(sha256="1" * 64),
                       dict(event_time_utc="2026-10-07T00:00:06Z"), dict(event_time_utc="2026-10-07T00:00:01")):
            with self.subTest(change=change):
                self.assertIsNone(prelock.validate_power_evidence(dict(record, **change), root, *window))

    def test_enumeration_with_fake_sdk(self):
        devices = [types.SimpleNamespace(info={"name": "Intel RealSense D455", "serial": "B", "fw": "5", "usb": "3.2"}),
                   types.SimpleNamespace(info={"name": "Other", "serial": "A", "fw": "1", "usb": "2.1"})]
        for device in devices:
            device.supports = lambda key: True
            device.get_info = (lambda d: lambda key: d.info[key])(device)
        rs = types.SimpleNamespace(camera_info=types.SimpleNamespace(name="name", serial_number="serial",
                                                                     firmware_version="fw", usb_type_descriptor="usb"),
                                   context=lambda: types.SimpleNamespace(query_devices=lambda: devices))
        result = prelock.enumerate_devices(rs)
        self.assertTrue(result["probe_ok"])
        self.assertEqual([d["serial"] for d in result["devices"]], ["A", "B"])

    def test_realsense_sdk_identity_is_explicit_and_never_package_fallback(self):
        self.assertEqual(prelock.realsense_sdk_version(types.SimpleNamespace(__version__="2.55.1")), "2.55.1")
        self.assertEqual(prelock.realsense_sdk_version(types.SimpleNamespace(get_api_version=lambda: 205501)),
                         "205501")
        self.assertIsNone(prelock.realsense_sdk_version(types.SimpleNamespace()))
        self.assertIsNone(prelock.realsense_sdk_version(types.SimpleNamespace(
            get_api_version=lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))))

    def test_prelock_module_never_opens_result_bearing_sidecars(self):
        source = Path(prelock.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for sealed in ("_quality.json", "_samples.csv", "_markers.csv"):
            self.assertEqual(literals.count(sealed), 1, sealed)    # only in CAPTURE_SUFFIXES (names, not content)
        for forbidden in ("forward_gate_evidence", "verdict", "closer_m", "person_ratio", "face_ratio",
                          "st_size", "st_mtime", "getsize", "getmtime"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
