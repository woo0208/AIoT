"""CAP-005 §35–§54 / CAP-006 ledger tests on synthetic events; no hardware or research data."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import patch8_ledger as ledger
import patch8_protocol as p8
from patch8_test_fixtures import (CODE, EXECUTION_ID, HEX, LOGS, POSE, SUBJECT, LedgerHarness,
                                  analysis_environment, environment)


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = LedgerHarness(self.temp.name)

    def lines(self):
        return self.h.path.read_bytes().splitlines(keepends=True)

    def write_lines(self, lines):
        self.h.path.write_bytes(b"".join(lines))

    def assert_rejected(self, function, *args, message=None, **kwargs):
        before = self.h.path.read_bytes() if self.h.path.exists() else None
        with self.assertRaises(ledger.LedgerError) as caught:
            function(*args, **kwargs)
        if message:
            self.assertIn(message, str(caught.exception))
        self.assertEqual(before, self.h.path.read_bytes() if self.h.path.exists() else None,
                         "a rejected append must not write any byte")


class SerializationAndChainTests(LedgerTestCase):
    def test_first_event_previous_hash_null_and_line_is_canonical(self):
        self.h.start_session(env=environment(capture_host="검증-호스트"))
        line = self.lines()[0]
        event = json.loads(line)
        self.assertIsNone(event["previous_event_sha256"])
        self.assertEqual(line, json.dumps(event, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False).encode("utf-8") + b"\n")
        self.assertIn("검증-호스트".encode("utf-8"), line)          # ensure_ascii = false
        self.assertNotIn(b", ", line)
        self.assertNotIn(b": ", line)
        for field in ("ledger_format_version", "execution_id", "session_id", "event_id",
                      "event_timestamp_utc", "event_type"):
            self.assertIn(field, event)
        self.assertEqual(event["ledger_format_version"], "patch8-validation-control/1.0.0")

    def test_event_hash_excludes_itself_and_second_event_chains(self):
        self.h.prepare()
        events = [json.loads(line) for line in self.lines()]
        for previous, event in zip([None] + events, events):
            body = {k: v for k, v in event.items() if k != "event_sha256"}
            expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=False).encode("utf-8")).hexdigest()
            self.assertEqual(event["event_sha256"], expected)
            self.assertEqual(event["previous_event_sha256"], previous and previous["event_sha256"])

    def test_canonical_serialization_is_deterministic(self):
        a = {"b": 1, "a": {"y": [1, 2], "x": "é"}}
        b = {"a": {"x": "é", "y": [1, 2]}, "b": 1}
        self.assertEqual(ledger.canonical_bytes(a), ledger.canonical_bytes(b))
        self.assertEqual(ledger.canonical_bytes(a), '{"a":{"x":"é","y":[1,2]},"b":1}'.encode("utf-8"))
        with self.assertRaises(ValueError):
            ledger.canonical_bytes({"x": float("nan")})

    def test_altered_event_breaks_verification(self):
        self.h.prepare()
        lines = self.lines()
        event = json.loads(lines[1])
        event["status"] = "FAIL"                                   # silent edit, stale hash
        self.write_lines([lines[0], ledger.event_line(event), *lines[2:]])
        with self.assertRaisesRegex(ledger.LedgerError, "event_sha256 mismatch"):
            ledger.verify_ledger(self.h.path)
        event["event_sha256"] = ledger.event_hash(event)          # rehashed edit breaks the chain
        self.write_lines([lines[0], ledger.event_line(event), *lines[2:]])
        with self.assertRaisesRegex(ledger.LedgerError, "previous_event_sha256 mismatch"):
            ledger.verify_ledger(self.h.path)

    def test_reordered_or_deleted_event_breaks_verification(self):
        self.h.prepare()
        lines = self.lines()
        self.write_lines([lines[0], lines[2], lines[1], *lines[3:]])
        with self.assertRaisesRegex(ledger.LedgerError, "previous_event_sha256"):
            ledger.verify_ledger(self.h.path)
        self.write_lines([lines[0], *lines[2:]])
        with self.assertRaisesRegex(ledger.LedgerError, "previous_event_sha256"):
            ledger.verify_ledger(self.h.path)

    def test_noncanonical_torn_duplicate_and_nan_lines_rejected(self):
        self.h.start_session()
        line = self.lines()[0]
        event = json.loads(line)
        variants = {
            "not canonical": json.dumps(event, sort_keys=True, indent=1).replace("\n", "").encode() + b"\n",
            "torn ledger tail": line[:-1],
            "duplicate JSON key": line[:-2] + b',"event_type":"session_start"}\n',
            "invalid JSON constant": line[:-2] + b',"x":NaN}\n',
        }
        for message, data in variants.items():
            with self.subTest(message):
                self.h.path.write_bytes(data)
                with self.assertRaisesRegex(ledger.LedgerError, message):
                    ledger.verify_ledger(self.h.path)

    def test_append_only_writer_preserves_prefix_and_refuses_tampered_file(self):
        self.h.prepare()
        prefix = self.h.path.read_bytes()
        self.h.start("1")
        self.assertTrue(self.h.path.read_bytes().startswith(prefix))
        lines = self.lines()
        event = json.loads(lines[0])
        event["subject"] = "OTHER"
        self.write_lines([ledger.event_line(event), *lines[1:]])
        tampered = self.h.path.read_bytes()
        with self.assertRaises(ledger.LedgerError):
            self.h.finish("1")
        self.assertEqual(self.h.path.read_bytes(), tampered)

    def test_unsupported_type_extra_field_and_execution_identity_rejected(self):
        self.h.start_session()
        state = self.h.state()
        for kind, payload, message in (
                ("rewrite_validity", {}, "unsupported event_type"),
                ("session_end", dict(session_kind="static-grid", status="completed", extra=1), "exact field set"),
        ):
            event = self.h.ledger.build(state, kind, self.h.session, payload, self.h.now())
            with self.subTest(kind), self.assertRaisesRegex(ledger.LedgerError, message):
                ledger.apply_event(ledger.replay(list(state.events)), event)
        with self.assertRaises(ledger.LedgerError):
            ledger.Ledger(Path(self.temp.name) / "elsewhere" / p8.LEDGER_FILENAME, EXECUTION_ID)
        other = ledger.Ledger(self.h.path.parent.parent / ("p8x_20261007T000000000000Z_" + "b" * 32) /
                              p8.LEDGER_FILENAME, "p8x_20261007T000000000000Z_" + "b" * 32)
        other.path.parent.mkdir(parents=True)
        other.path.write_bytes(self.h.path.read_bytes())
        with self.assertRaisesRegex(ledger.LedgerError, "another execution"):
            other.read()

    def test_report_published_binds_previous_ledger_bytes(self):
        self.h.start_session()
        before = self.h.path.read_bytes()
        event, _ = self.h.append("report_published", dict(report_path="r.json", report_sha256=HEX))
        self.assertEqual(event["ledger_sha256_before"], hashlib.sha256(before).hexdigest())
        ledger.verify_ledger(self.h.path)


class LifecycleTests(LedgerTestCase):
    def test_lifecycle_order_is_enforced(self):
        self.h.prepare()
        self.assert_rejected(self.h.finish, "1", message="without attempt_start")
        self.h.start("1")
        self.assert_rejected(self.h.append, "validity_locked", dict(
            self.h.identity("1", 1), recording_id=None, status="locked", reason_code=None, stage="post_reservation",
            acquisition_valid=True, retry_allowed=False, machine_evidence_ref=None, evidence_used=[],
            operator_declaration="unknown", rule_id="R17"), message="before capture_finished")
        self.h.finish("1")
        self.assert_rejected(self.h.append, "attempt_end", dict(self.h.identity("1", 1), recording_id="V01_r1_a1",
                                                                status="ended", reason_code=None),
                             message="requires validity_locked")
        self.h.lock("1")
        self.h.end("1")
        self.assertTrue(self.h.state().attempts[("1", 1)].canonical())

    def test_validity_lock_is_immutable_and_must_match_closed_rules(self):
        self.h.prepare()
        self.h.start("1")
        self.h.finish("1")
        self.assert_rejected(self.h.lock, "1", reason=p8.MANUAL_ABORT, acquisition_valid=False,
                             message="acquisition_valid inconsistent")
        self.assert_rejected(self.h.lock, "1", reason=p8.MANUAL_ABORT, retry_allowed=True,
                             message="retry_allowed inconsistent")
        self.assert_rejected(self.h.lock, "1", reason=p8.GUIDE_NOT_SATISFIED, message="not permitted for static")
        self.assert_rejected(self.h.lock, "1", reason=p8.CAMERA_DISCONNECT, machine_evidence_ref=None,
                             message="machine_evidence_ref")
        self.h.lock("1", reason=None)
        for reason in (None, p8.CAMERA_DISCONNECT):
            with self.subTest(reason=reason):
                self.assert_rejected(self.h.lock, "1", reason=reason, message="validity is immutable")
        self.h.end("1")
        self.assert_rejected(self.h.lock, "1", reason=p8.USB_STREAM_FAILURE, message="validity is immutable")
        self.assertTrue(self.h.state().attempts[("1", 1)].locked["acquisition_valid"])

    def test_attempt_end_must_restate_lock(self):
        self.h.prepare()
        self.h.start("1")
        self.h.finish("1")
        self.h.lock("1", reason=p8.MANUAL_ABORT)
        self.assert_rejected(self.h.append, "attempt_end", dict(self.h.identity("1", 1), recording_id="V01_r1_a1",
                                                                status="ended", reason_code=None),
                             message="restate lock")

    def test_unseal_requires_lock_and_attempt_end(self):
        self.h.prepare()
        self.h.start("1")
        with self.assertRaises(ledger.SealedResultError):
            self.h.state().unseal("1", 1)
        self.h.finish("1")
        self.h.lock("1")
        with self.assertRaises(ledger.SealedResultError):
            self.h.state().unseal("1", 1)
        self.h.end("1")
        token = self.h.state().unseal("1", 1)
        self.assertEqual((token.round, token.attempt_index, token.recording_id), ("1", 1, "V01_r1_a1"))

    def test_attempt_prerequisites(self):
        cases = (
            (dict(models=False), "model verification"),
            (dict(integrity=False), "pre-hardware integrity"),
            (dict(warm=False), "warm-up"),
            (dict(setup=False), "setup_verified"),
        )
        for kwargs, message in cases:
            with self.subTest(message), tempfile.TemporaryDirectory() as directory:
                self.h = LedgerHarness(directory)
                self.h.prepare(**kwargs)
                self.assert_rejected(self.h.start, "1", message=message)

    def test_attempt_start_payload_rules(self):
        self.h.prepare()
        for overrides, message in (
                (dict(setup_checks=dict(hips_visually_unobstructed=False, hands_forearms_clear_of_hips=True,
                                        external_occluder_absent=True)), "setup checks"),
                (dict(settling_s=5.0), "settling"),
                (dict(code_state=dict(CODE, git_clean=False)), "code state"),
                (dict(code_state=dict(CODE, git_commit="d" * 40)), "code state"),
                (dict(sequence_mode="core"), "SEQ_CORE/SEQ_FULL"),
                (dict(nominal_distance=0.7), "nominal_distance"),
                (dict(validation_protocol_version=p8.PRODUCTION_PROTOCOL_VERSION), "protocol_version"),
                (dict(subject="OTHER"), "subject"),
        ):
            with self.subTest(message=message, overrides=overrides):
                self.assert_rejected(self.h.start, "1", message=message, **overrides)
        self.assert_rejected(self.h.start, "131", message="session kind")

    def test_environment_change_blocks_attempts(self):
        self.h.prepare()
        self.h.attempt("1")
        self.h.append("camera_pose_recheck", dict(camera_pose=dict(POSE, witness_mark_displaced=False),
                                                  material_change=False, differences=dict(
                                                      reference_height_mm=0.0, pitch_deg=0.0, yaw_deg=0.0,
                                                      roll_deg=0.0)))
        self.h.append("session_end", dict(session_kind="static-grid", status="completed"))
        self.h.start_session("E2E", env=environment(usb_type="2.1"))
        self.h.append("warmup_completed", dict(duration_s=60.0, exit_code=0, logs=LOGS))
        self.assert_rejected(self.h.start, "131", message="environment differs")

    def test_valid_environment_identity_changes_each_block_attempts(self):
        options = environment()["device_options"]
        changes = (
            dict(device_options=dict(options, **{"depth.visual_preset": 2.0})),
            dict(capture_host="other-capture-host"),
            dict(realsense_sdk_version="different-sdk"),
        )
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                harness = LedgerHarness(directory)
                harness.prepare()
                harness.attempt("1")
                harness.append("camera_pose_recheck", dict(camera_pose=dict(POSE, witness_mark_displaced=False),
                                                            material_change=False, differences=dict(
                                                                reference_height_mm=0.0, pitch_deg=0.0,
                                                                yaw_deg=0.0, roll_deg=0.0)))
                harness.append("session_end", dict(session_kind="static-grid", status="completed"))
                harness.start_session("E2E", env=environment(**change))
                harness.append("warmup_completed", dict(duration_s=60.0, exit_code=0, logs=LOGS))
                before = harness.path.read_bytes()
                with self.assertRaisesRegex(ledger.LedgerError, "environment differs"):
                    harness.start("131")
                self.assertEqual(harness.path.read_bytes(), before)

    def test_capture_environment_rejects_incomplete_profiles_options_and_sdk(self):
        valid = environment()
        cases = {
            "missing color profile content": dict(stream_profiles={
                "color": {"height": 720, "format": "bgr8", "fps": 15},
                "depth": valid["stream_profiles"]["depth"], "align_to": "color"}),
            "missing depth profile content": dict(stream_profiles={
                "color": valid["stream_profiles"]["color"],
                "depth": {"width": 848, "height": 480, "fps": 15}, "align_to": "color"}),
            "missing alignment": dict(stream_profiles={
                "color": valid["stream_profiles"]["color"], "depth": valid["stream_profiles"]["depth"]}),
            "incomplete device options": dict(device_options={"depth.visual_preset": 1.0}),
            "unrelated device options": dict(device_options={"unrelated": 0.0}),
            "missing SDK": dict(realsense_sdk_version=None),
            "error-only SDK": dict(realsense_sdk_version="error"),
        }
        for name, change in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                harness = LedgerHarness(directory)
                before = harness.path.read_bytes() if harness.path.exists() else None
                with self.assertRaisesRegex(ledger.LedgerError, "capture environment"):
                    harness.start_session(env=environment(**change))
                self.assertEqual(before, harness.path.read_bytes() if harness.path.exists() else None)

    def test_valid_canonical_capture_environment_passes(self):
        self.h.start_session(env=environment())
        self.assertEqual(self.h.state().baseline_environment, ledger.capture_environment_identity(environment()))


class RetryAuthorityTests(LedgerTestCase):
    def test_static_retry_only_after_objective_invalid_lock(self):
        self.h.prepare()
        self.h.attempt("1", 1, reason=p8.USB_STREAM_FAILURE)
        self.h.attempt("1", 2, reason=p8.EXTERNAL_PHYSICAL_INTERRUPTION)
        self.h.attempt("1", 3, reason=p8.RAW_FILE_UNREADABLE_OR_CORRUPT)
        state = self.h.state()
        self.assertFalse(state.attempts[("1", 3)].locked["retry_allowed"])   # budget exhausted
        self.assertIsNone(state.next_attempt_index("1"))
        self.assertIsNone(state.canonical_attempt("1"))
        self.assertTrue(state.slot_resolved("1"))
        self.assert_rejected(self.h.start, "1", 4, message="attempt_index")

    def test_first_non_invalid_static_attempt_is_canonical_and_ends_slot(self):
        self.h.prepare()
        self.h.attempt("1", 1, reason=p8.CAMERA_DISCONNECT)
        self.h.attempt("1", 2, reason=None)
        self.assertEqual(self.h.state().canonical_attempt("1").attempt_index, 2)
        self.assert_rejected(self.h.start, "1", 3, message="not authorized")

    def test_valid_fail_reasons_never_grant_retry(self):
        for reason in (p8.MANUAL_ABORT, p8.UNCLASSIFIED_TERMINATION):
            with self.subTest(reason), tempfile.TemporaryDirectory() as directory:
                self.h = LedgerHarness(directory)
                self.h.prepare()
                self.h.attempt("1", 1, reason=reason)
                self.assert_rejected(self.h.start, "1", 2, message="not authorized")

    def test_static_acquisition_order(self):
        self.h.prepare()
        self.assert_rejected(self.h.start, "2", message="acquisition order")
        self.h.attempt("1")
        self.h.start("2")

    def test_camera_disturbance_before_and_after_first_canonical_take(self):
        self.h.prepare()
        self.h.start("1")
        event, _ = self.h.append("operator_observation", dict(
            self.h.identity("1", 1), recording_id=None, status="observed", reason_code=None,
            observation=p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED, retry_eligible=True))
        self.h.finish("1")
        self.h.lock("1", reason=p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED)
        self.h.end("1")
        self.assert_rejected(self.h.start, "1", 2, message="setup reset")
        self.h.append("setup_verified", dict(purpose="reset", camera_pose=dict(POSE)))
        self.h.attempt("1", 2)                                        # first canonical take
        self.assert_rejected(self.h.append, "setup_verified", dict(purpose="reset", camera_pose=dict(POSE)),
                             message="first canonical static take")
        self.h.start("2")
        self.assert_rejected(self.h.append, "operator_observation", dict(
            self.h.identity("2", 1), recording_id=None, status="observed", reason_code=None,
            observation=p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED, retry_eligible=True), message="retry_eligible")
        self.h.append("operator_observation", dict(
            self.h.identity("2", 1), recording_id=None, status="observed", reason_code=None,
            observation=p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED, retry_eligible=False))
        self.h.append("execution_failed", dict(reason_code="CAMERA_DISTURBED_AFTER_FIRST_CANONICAL_STATIC_TAKE",
                                               detail=None))
        self.h.finish("2")
        self.h.lock("2", reason=p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED)
        self.h.end("2")
        state = self.h.state()
        self.assertFalse(state.attempts[("2", 1)].locked["retry_allowed"])
        self.assertEqual(state.execution_failure, "CAMERA_DISTURBED_AFTER_FIRST_CANONICAL_STATIC_TAKE")
        self.assert_rejected(self.h.start, "2", 2, message="after execution_failed")

    def test_forward_target_miss_bounded_retry_and_canonical_closure(self):
        self.h.prepare("forward-gate")
        self.h.attempt("101", 1)
        self.assert_rejected(self.h.start, "101", 2, message="not authorized")   # outcome not yet recorded
        self.h.outcome("101", 1, p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS)
        self.assert_rejected(self.h.outcome, "101", 1, p8.CANONICAL, None, message="immutable")
        self.h.attempt("101", 2)
        self.h.outcome("101", 2, p8.CANONICAL, None)
        state = self.h.state()
        self.assertEqual(state.canonical_attempt("101").attempt_index, 2)
        self.assertIsNone(state.next_attempt_index("101"))
        self.assert_rejected(self.h.start, "101", 3, message="not authorized")

    def test_forward_three_target_misses_exhaust_slot(self):
        self.h.prepare("forward-gate")
        for index in (1, 2, 3):
            self.h.attempt("113", index)
            self.h.outcome("113", index, p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS)
        state = self.h.state()
        self.assertIsNone(state.canonical_attempt("113"))
        self.assertIsNone(state.next_attempt_index("113"))

    def test_outcome_rules(self):
        self.h.prepare("forward-gate")
        self.h.attempt("101", 1, reason=p8.MANUAL_ABORT)
        self.assert_rejected(self.h.outcome, "101", 1, p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS,
                             message="TARGET_MISS only")
        self.assert_rejected(self.h.outcome, "101", 1, p8.CANONICAL, None, message="carry into outcome")
        self.h.outcome("101", 1, p8.CANONICAL, p8.MANUAL_ABORT)
        self.setUp()
        self.h.prepare()
        self.h.attempt("1")
        self.assert_rejected(self.h.outcome, "1", 1, message="static canonical status")

    def test_e2e_retry_only_after_machine_invalid_and_no_target_miss(self):
        self.h.prepare("E2E")
        self.h.attempt("131", 1, reason=p8.POWER_FAILURE)
        self.h.attempt("131", 2)
        self.assert_rejected(self.h.outcome, "131", 2, p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS,
                             message="TARGET_MISS only")
        self.h.outcome("131", 2, p8.CANONICAL, None)
        self.assert_rejected(self.h.start, "131", 3, message="not authorized")

    def test_body_only_target_miss_retry(self):
        self.h.prepare("body-only-negative")
        self.h.attempt("121", 1)
        self.h.outcome("121", 1, p8.TARGET_MISS_OUTCOME, p8.TARGET_MISS)
        self.h.attempt("121", 2)
        self.assertEqual(self.h.state().slot_attempts("121")[-1].attempt_index, 2)

    def test_cap006_production_sequences_can_start(self):
        for rnd, mode in (("101", "core"), ("102", "core"), ("103", "core"),
                          ("111", "core"), ("112", "core"), ("113", "core"),
                          ("121", "core"), ("131", "full")):
            with self.subTest(rnd=rnd, mode=mode):
                self.setUp()
                slot = p8.SLOTS[rnd]
                self.assertEqual(slot.sequence_mode, mode)
                self.h.prepare(slot.session_kind)
                self.assert_rejected(self.h.start, rnd, sequence_mode="full" if mode == "core" else "core",
                                     message="sequence_mode mismatch")
                self.h.start(rnd)
                self.assertEqual(self.h.state().open_attempt().round, rnd)

    def test_unsupported_production_sequences_cannot_start(self):
        for rnd in ("101", "102", "103", "111", "112", "113", "121", "131"):
            for mode in (None, "unknown"):
                with self.subTest(rnd=rnd, mode=mode):
                    self.setUp()
                    slot = p8.SLOTS[rnd]
                    self.h.prepare(slot.session_kind)
                    with patch.dict(p8.SLOTS, {rnd: replace(slot, sequence_mode=mode)}):
                        self.assert_rejected(self.h.start, rnd, message="not supported by CAP-005/CAP-006")

    def test_production_observations_are_never_retry_eligible(self):
        self.h.prepare("E2E")
        self.h.start("131")
        for eligible in (True,):
            self.assert_rejected(self.h.append, "operator_observation", dict(
                self.h.identity("131", 1), recording_id=None, status="observed", reason_code=None,
                observation=p8.EXTERNAL_PHYSICAL_INTERRUPTION, retry_eligible=eligible), message="retry_eligible")
        self.h.append("operator_observation", dict(
            self.h.identity("131", 1), recording_id=None, status="observed", reason_code=None,
            observation=p8.EXTERNAL_PHYSICAL_INTERRUPTION, retry_eligible=False))
        self.h.finish("131")
        self.assert_rejected(self.h.lock, "131", reason=p8.EXTERNAL_PHYSICAL_INTERRUPTION, message="not permitted")


class SessionAndAnalysisTests(LedgerTestCase):
    def test_static_session_end_requires_recheck_after_last_attempt_and_material_rule(self):
        self.h.prepare()
        self.h.attempt("1")
        self.assert_rejected(self.h.append, "session_end", dict(session_kind="static-grid", status="completed"),
                             message="camera_pose_recheck")
        moved = dict(POSE, reference_height_mm=1006.0, witness_mark_displaced=False)
        differences = dict(reference_height_mm=6.0, pitch_deg=0.0, yaw_deg=0.0, roll_deg=0.0)
        self.assert_rejected(self.h.append, "camera_pose_recheck", dict(camera_pose=moved, material_change=False,
                                                                        differences=differences),
                             message="§7.4")
        self.h.append("camera_pose_recheck", dict(camera_pose=moved, material_change=True, differences=differences))
        self.assert_rejected(self.h.start, "2", message="material change")
        self.h.append("session_end", dict(session_kind="static-grid", status="completed"))

    def test_pose_material_change_thresholds(self):
        base = dict(POSE)
        for change, material in ((dict(reference_height_mm=1005.0), False), (dict(reference_height_mm=1005.1), True),
                                 (dict(pitch_deg=1.0), False), (dict(yaw_deg=-1.01), True),
                                 (dict(roll_deg=1.5), True)):
            with self.subTest(change=change):
                _, result = ledger.pose_differences(base, dict(base, witness_mark_displaced=False, **change))
                self.assertIs(result, material)
        self.assertTrue(ledger.pose_differences(base, dict(base, witness_mark_displaced=True))[1])

    def analysis(self, index, runs, canonical, exit_code=0, env=None):
        return self.h.append("analysis_invocation", dict(
            subject=SUBJECT, round="1", attempt_index=1, recording_id="V01_r1_a1", invocation_index=index,
            exit_code=exit_code, analysis_runs=runs, canonical_analysis_run_id=canonical, logs=LOGS,
            environment=env or analysis_environment()))

    def test_analysis_environment_is_measured_pinned_and_cross_host_realsense_matched(self):
        self.h.prepare()
        self.h.attempt("1")
        runs = [dict(analysis_run_id="ar_1", status="failed", manifest_sha256=HEX)]
        same_host_bad = analysis_environment(
            packages=dict(analysis_environment()["packages"], numpy="different"))
        self.assert_rejected(self.analysis, 1, runs, None, exit_code=1, env=same_host_bad,
                             message="same-host analysis environment")
        remote = analysis_environment(analysis_host="analysis-host", os="analysis-os", python="3.13",
                                      packages=dict(analysis_environment()["packages"], mediapipe="remote"))
        self.analysis(1, runs, None, exit_code=1, env=remote)
        self.assertEqual(self.h.state().baseline_analysis_environment,
                         ledger.analysis_environment_identity(remote))
        self.h.append("analysis_infrastructure_failure", dict(
            subject=SUBJECT, round="1", attempt_index=1, recording_id="V01_r1_a1", analysis_run_id="ar_1",
            evidence_ref="analysis/V01_r1_a1/ar_1/analysis_manifest.json", evidence_sha256=HEX))
        changed_host = analysis_environment(**dict(remote, analysis_host="other-analysis-host"))
        self.assert_rejected(self.analysis, 2, runs, None, exit_code=1, env=changed_host,
                             message="analysis environment differs")

    def test_analysis_environment_rejects_missing_and_mismatched_sdk_identity(self):
        self.h.prepare()
        self.h.attempt("1")
        runs = [dict(analysis_run_id="ar_1", status="failed", manifest_sha256=HEX)]
        for name, env, message in (
                ("missing", analysis_environment(realsense_sdk_version=None), "missing/invalid"),
                ("error", analysis_environment(realsense_sdk_version="error"), "missing/invalid"),
                ("sdk mismatch", analysis_environment(analysis_host="remote", realsense_sdk_version="different"),
                 "differs from capture"),
                ("binding mismatch", analysis_environment(
                    analysis_host="remote", packages=dict(analysis_environment()["packages"],
                                                          pyrealsense2="different")), "differs from capture")):
            with self.subTest(name=name):
                self.assert_rejected(self.analysis, 1, runs, None, exit_code=1, env=env, message=message)

    def test_first_completed_analysis_run_is_canonical_and_reanalysis_needs_evidence(self):
        self.h.prepare()
        self.assert_rejected(self.analysis, 1, [], None, message="ledger-canonical recording")
        self.h.attempt("1")
        failed = [dict(analysis_run_id="ar_1", status="failed", manifest_sha256=HEX)]
        self.analysis(1, failed, None, exit_code=1)
        completed = [dict(analysis_run_id="ar_2", status="completed", manifest_sha256=HEX)]
        self.assert_rejected(self.analysis, 2, completed, "ar_2", message="infrastructure failure")
        base = dict(subject=SUBJECT, round="1", attempt_index=1, recording_id="V01_r1_a1",
                    analysis_run_id="ar_1", evidence_ref="analysis/V01_r1_a1/ar_1/analysis_manifest.json",
                    evidence_sha256=HEX)
        self.assert_rejected(self.h.append, "analysis_infrastructure_failure",
                             dict(base, analysis_run_id="ar_unknown"), message="failed logged run")
        self.assert_rejected(self.h.append, "analysis_infrastructure_failure",
                             dict(base, evidence_ref="evidence/disk.txt"), message="failed-run manifest")
        self.assert_rejected(self.h.append, "analysis_infrastructure_failure",
                             dict(base, evidence_sha256="1" * 64), message="failed-run manifest")
        self.h.append("analysis_infrastructure_failure", dict(
            subject=SUBJECT, round="1", attempt_index=1, recording_id="V01_r1_a1", analysis_run_id="ar_1",
            evidence_ref="analysis/V01_r1_a1/ar_1/analysis_manifest.json", evidence_sha256=HEX))
        self.assert_rejected(self.analysis, 2, completed, None, message="first completed run")
        self.analysis(2, completed, "ar_2")
        self.assertEqual(self.h.state().analyses["V01_r1_a1"]["canonical"], "ar_2")
        self.assertFalse(self.h.state().analysis_invocation_allowed("V01_r1_a1"))
        self.assert_rejected(self.h.append, "analysis_infrastructure_failure", dict(
            subject=SUBJECT, round="1", attempt_index=1, recording_id="V01_r1_a1", analysis_run_id="ar_2",
            evidence_ref="evidence/x.txt", evidence_sha256=HEX), message="after completion")

    def test_integrity_and_model_events(self):
        self.h.start_session()
        self.h.append("integrity_check", dict(phase="pre_hardware", exit_code=0, summary="PASS",
                                              counts=dict(ERROR=1, WARNING=0, INFO=0)))
        self.assertFalse(self.h.state().pre_hardware_integrity)           # ERROR count must be 0
        self.h.append("model_verification", dict(status="FAIL", lock_sha256=HEX, artifacts=[]))
        self.assertFalse(self.h.state().model_verified)


if __name__ == "__main__":
    unittest.main()
