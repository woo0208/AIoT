"""Patch 6 synthetic contract tests; no research results or hardware evidence."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

import numpy as np
import openpyxl

import rf_experiment as rf
import selection_manifest as selection
from patch5_test_fixtures import make_frames, analysis


EVENT_KEYS = set("schema_version selection_event_id event_type created_at dataset_role subject round "
                 "recording_id selection_policy_version decided_by supersedes_selection_event_id "
                 "recapture decision evidence".split())
MANIFEST_KEYS = set("schema_version dataset_manifest_id created_at created_by dataset_role "
                    "selection_policy_version selection_events_path entries".split())
ENTRY_KEYS = set("dataset_role subject round recording_id selection_event_id selection_event_sha256 "
                "analysis_run_id frames_schema_version frames_path frames_sha256 "
                "analysis_manifest_path analysis_manifest_sha256".split())


class Patch6Tests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.out = self.root / "analysis"
        self.out.mkdir()
        self.ledger = self.root / "manifests/selection_events.jsonl"
        self.results = self.root / "results"
        self.stack.enter_context(patch.object(rf, "OUT_DIR", str(self.out)))
        self.stack.enter_context(patch.object(rf, "RESULTS_DIR", str(self.results)))
        self.stack.enter_context(patch.object(rf, "REPO_ROOT", self.root))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))

    def json_file(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
        return path

    def evidence(self, path, kind, rid):
        return dict(recording_id=rid, kind=kind, path=path.relative_to(self.root).as_posix(),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def source(self, rid="P01_r1_original", subject="P01", rnd="1", role="pilot", run="ar_one",
               include=True, quality=False, protocol="synthetic-protocol", verdict="ok", rows=None):
        capture = self.root / "data" / (rid + "_camera.json")
        self.json_file(capture, dict(schema_version="capture-provenance/1.0.0", recording_id=rid,
                                    subject=subject, round=rnd, dataset_role=role, protocol_version=protocol))
        evidence = [self.evidence(capture, "capture_provenance", rid)]
        selected = None
        if include:
            if rows is None:
                rows = [dict(subject=subject, round=rnd, step=i, label=label)
                        for i, label in enumerate(rf.LAB5, 1)]
            frames = make_frames(self.out, rid=rid, run=run, rows=rows)
            owner = frames.parent / "analysis_manifest.json"
            value = json.loads(owner.read_text(encoding="utf-8"))
            value.update(schema_version="analysis-provenance/1.0.0", dataset_role=role, protocol_version=protocol)
            self.json_file(owner, value)
            # Recreate the compatibility sidecar after adding source metadata.
            sidecar = Path(str(self.out / frames.name) + ".provenance.json")
            link = json.loads(sidecar.read_text(encoding="utf-8"))
            link["analysis_manifest_sha256"] = hashlib.sha256(owner.read_bytes()).hexdigest()
            self.json_file(sidecar, link)
            evidence += [self.evidence(owner, "analysis_manifest", rid), self.evidence(frames, "canonical_frames", rid)]
            selected = dict(analysis_run_id=run, frames_schema_version="frames-schema/1.0.0",
                            frames_path=evidence[2]["path"], frames_sha256=evidence[2]["sha256"],
                            analysis_manifest_path=evidence[1]["path"], analysis_manifest_sha256=evidence[1]["sha256"])
        if quality:
            quality_path = self.json_file(self.root / "data" / (rid + "_quality.json"),
                                          dict(recording_id=rid, verdict=verdict, fails=[], warnings=[],
                                               forward_gate_evidence={"synthetic": True}))
            evidence.append(self.evidence(quality_path, "quality", rid))
        return dict(schema_version="selection-event/1.0.0", selection_event_id=selection.new_event_id(),
                    event_type="selection_decision", created_at=datetime.now(timezone.utc).isoformat(),
                    dataset_role=role, subject=subject, round=rnd, recording_id=rid,
                    selection_policy_version="synthetic-policy/1" if role == "formal" else None,
                    decided_by="synthetic-test-authority", supersedes_selection_event_id=None, recapture=None,
                    decision=dict(disposition="include" if include else "exclude", reason_code="test-only",
                                  reason_text=None, analysis_selection=selected), evidence=evidence)

    def relation(self, child, parent):
        event = deepcopy(child)
        event.update(selection_event_id=selection.new_event_id(), event_type="recapture_relation",
                     selection_policy_version=None, decision=None, supersedes_selection_event_id=None,
                     recapture=dict(recapture_of_recording_id=parent["recording_id"]),
                     evidence=[deepcopy(child["evidence"][0]), deepcopy(parent["evidence"][0])])
        return event

    def append(self, event):
        return selection.append_event(event, self.root)

    def build(self, *events, role="pilot", policy=None):
        return selection.build_dataset_manifest([e["selection_event_id"] for e in events],
                                                dataset_role=role, created_by="synthetic-test-authority",
                                                selection_policy_version=policy, repo_root=self.root)

    def resolve(self, path, expected_sha256=None):
        return selection.resolve_dataset_manifest(path, self.root, expected_sha256)

    def repin(self, event, kind, updates):
        item = next(e for e in event["evidence"] if e["kind"] == kind)
        path = self.root / item["path"]
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(updates)
        self.json_file(path, value)
        item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if kind == "analysis_manifest":
            event["decision"]["analysis_selection"]["analysis_manifest_sha256"] = item["sha256"]

    def mutate_manifest(self, path, mutate):
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))

    def test_event_exact_keys_and_nullable_keys_required(self):
        event = self.source(include=False)
        self.assertEqual(set(event), EVENT_KEYS)
        for field in EVENT_KEYS:
            changed = deepcopy(event)
            del changed[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.append(changed)
        changed = dict(event, attempt_number=2)
        with self.assertRaisesRegex(ValueError, "exact selection event"):
            self.append(changed)
        self.assertFalse(self.ledger.exists())

    def test_event_field_types_and_enums_rejected(self):
        event = self.source(include=False)
        invalid = dict(schema_version=[None, "selection-event/2.0.0"], selection_event_id=[1, "se_bad"],
                       event_type=[None, "include", {}], created_at=[1, "2026-10-05", "2026-10-05T10:00:00+09:00"],
                       dataset_role=["external", None, 1], subject=[None, "", []], recording_id=[None, 1, ""],
                       selection_policy_version=[False, 12, []], decided_by=[None, "", "  ", 1],
                       supersedes_selection_event_id=[1, "missing"], recapture=[{}], decision=[None, []],
                       evidence=[None, {}, ""])
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.append(dict(event, **{field: value}))

    def test_event_ids_require_real_utc_timestamp_and_uuid4(self):
        event = self.source(include=False)
        for event_id in ("se_20261305T100000000000Z_" + uuid.uuid4().hex,
                         "se_20261005T100000000000Z_" + uuid.uuid1().hex):
            with self.subTest(event_id=event_id), self.assertRaises(ValueError):
                self.append(dict(event, selection_event_id=event_id))
        self.assertRegex(selection.new_event_id(), r"^se_[0-9]{8}T[0-9]{12}Z_[0-9a-f]{32}$")

    def test_round_positive_decimal_string_only(self):
        event = self.source(include=False)
        for rnd in (1, True, 1.5, None, "0", "00", "01", "001", "-1", "+1", "1.0", " 1", "1 ", "1\n", "１", ""):
            with self.subTest(round=rnd), self.assertRaisesRegex(ValueError, "round"):
                self.append(dict(event, round=rnd))
        leading_zero = self.source(rid="leading_zero", rnd="01", include=False)
        capture_path = self.root / leading_zero["evidence"][0]["path"]
        before = capture_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "round"):
            self.append(leading_zero)
        self.assertEqual(capture_path.read_bytes(), before)  # Reject; never normalize historical provenance.
        self.assertFalse(self.ledger.exists())

    def test_canonical_round_strings_pass_without_normalization(self):
        for rnd in ("1", "2", "9", "10", "100"):
            self.append(self.source(rid="round_" + rnd, rnd=rnd, include=False))
        self.assertEqual([e["round"] for e in selection.read_selection_events(self.root)],
                         ["1", "2", "9", "10", "100"])

    def test_noncanonical_round_rejected_by_ledger_and_manifest_readers(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original_manifest = path.read_bytes()
        for rnd in ("01", "001", "0", "00", "+1", "-1", "1.0", " 1", "1 "):
            path.write_bytes(original_manifest)
            self.mutate_manifest(path, lambda m: m["entries"][0].update(round=rnd))
            with self.subTest(round=rnd), self.assertRaisesRegex(ValueError, "round"):
                self.resolve(path)
        path.write_bytes(original_manifest)
        leading_zero = self.source(rid="historical_leading_zero", rnd="01")
        self.ledger.write_bytes(selection.event_bytes(leading_zero))
        with self.assertRaisesRegex(ValueError, "round"):
            selection.read_selection_events(self.root)
        with self.assertRaisesRegex(ValueError, "round"):
            self.build(leading_zero)
        with self.assertRaisesRegex(ValueError, "round"):
            self.resolve(path)

    def test_decision_exact_keys_types_and_exclude_null_analysis(self):
        event = self.source(include=False)
        for key in event["decision"]:
            changed = deepcopy(event)
            del changed["decision"][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.append(changed)
        for update in (dict(extra=True), dict(disposition="auto"), dict(reason_code=" "),
                       dict(reason_code=1), dict(reason_text=False), dict(analysis_selection={})):
            changed = deepcopy(event)
            changed["decision"].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.append(changed)

    def test_evidence_exact_shape_kind_and_hash(self):
        event = self.source(include=False)
        for update in (dict(extra=1), dict(recording_id=None), dict(kind="raw"), dict(kind=[]),
                       dict(sha256="A" * 64), dict(sha256="0" * 63), dict(sha256=None), dict(path=1)):
            changed = deepcopy(event)
            changed["evidence"][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.append(changed)
        for field in ("recording_id", "kind", "path", "sha256"):
            changed = deepcopy(event)
            del changed["evidence"][0][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.append(changed)

    def test_append_only_canonical_utf8_lf_bytes_and_line_hash(self):
        event = self.source(include=False)
        event["decision"]["reason_text"] = "합성 데이터 — 테스트\n두 번째 줄"
        expected = (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        digest = self.append(event)
        self.assertEqual(self.ledger.read_bytes(), expected)
        self.assertEqual(digest, hashlib.sha256(expected).hexdigest())
        self.assertNotEqual(digest, hashlib.sha256(expected[:-1]).hexdigest())
        second = deepcopy(event)
        second.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=event["selection_event_id"])
        self.append(second)
        data = self.ledger.read_bytes()
        self.assertEqual(data[:len(expected)], expected)
        self.assertEqual(data.count(b"\n"), 2)
        self.assertNotIn(b"\r", data)
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(selection.read_selection_events(self.root), [event, second])

    def test_duplicate_event_id_rejected_without_rewriting(self):
        event = self.source(include=False)
        self.append(event)
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "duplicate selection_event_id"):
            self.append(event)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_invalid_new_event_leaves_existing_ledger_unchanged(self):
        event = self.source(include=False)
        self.append(event)
        before = self.ledger.read_bytes()
        changed = deepcopy(event)
        changed["evidence"][0]["sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.append(changed)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_reader_and_writer_reject_malformed_and_noncanonical_ledger(self):
        event = self.source(include=False)
        self.append(event)
        good = self.ledger.read_bytes()
        corruptions = (b"{broken}\n", good + good, good[:-1], good.replace(b"\n", b"\r\n"),
                       b"\xef\xbb\xbf" + good, good + b"\n", b"[]\n", b"null\n",
                       good.replace(b'"decision":', b'"extra":NaN,"decision":'),
                       good.replace(b'"decision":', b'"extra":1,"extra":2,"decision":'),
                       (json.dumps(event) + "\n").encode("utf-8"),
                       good.replace(b"selection-event/1.0.0", b"selection-event/9.0.0"))
        new = dict(event, selection_event_id=selection.new_event_id())
        for data in corruptions:
            self.ledger.write_bytes(data)
            with self.subTest(data=data[:50]):
                with self.assertRaises(ValueError):
                    selection.read_selection_events(self.root)
                with self.assertRaises(ValueError):
                    self.append(new)
                self.assertEqual(self.ledger.read_bytes(), data)

    def test_busy_ledger_blocks_other_process_and_manifest_builder(self):
        event = self.source()
        self.append(event)
        before = self.ledger.read_bytes()
        script = ("import sys; from pathlib import Path; from selection_manifest import _locked_ledger; "
                  "\ntry:\n with _locked_ledger(Path(sys.argv[1])): pass"
                  "\nexcept ValueError as e:\n print(e); sys.exit(7)")
        with selection._locked_ledger(self.ledger):
            completed = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(self.ledger)],
                                       cwd=Path(__file__).parent, capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 7, completed.stderr)
            self.assertIn("busy", completed.stdout)
            with self.assertRaisesRegex(ValueError, "busy"):
                self.build(event)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.build(event)

    def test_every_decision_requires_exactly_one_own_capture(self):
        for include in (False, True):
            event = self.source(rid="capture_test_" + str(include), include=include)
            for replacement in ([], [dict(event["evidence"][0], recording_id="another")],
                                [event["evidence"][0], event["evidence"][0]]):
                changed = deepcopy(event)
                changed["evidence"] = replacement + event["evidence"][1:]
                with self.subTest(include=include, evidence=replacement), self.assertRaises(ValueError):
                    self.append(changed)

    def test_capture_identity_is_exact_including_round_type(self):
        event = self.source(include=False)
        path = self.root / event["evidence"][0]["path"]
        original = path.read_bytes()
        for field, value in (("recording_id", "other"), ("subject", "P99"), ("round", "2"),
                             ("round", 1), ("dataset_role", "formal")):
            path.write_bytes(original)
            changed = deepcopy(event)
            self.repin(changed, "capture_provenance", {field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.append(changed)

    def test_pilot_include_minimum_and_analysis_evidence_binding(self):
        event = self.source()
        for kind in ("analysis_manifest", "canonical_frames"):
            changed = deepcopy(event)
            changed["evidence"] = [e for e in changed["evidence"] if e["kind"] != kind]
            with self.subTest(missing=kind), self.assertRaises(ValueError):
                self.append(changed)
            changed = deepcopy(event)
            next(e for e in changed["evidence"] if e["kind"] == kind)["sha256"] = "a" * 64
            with self.subTest(mismatch=kind), self.assertRaises(ValueError):
                self.append(changed)
        self.append(event)
        self.resolve(self.build(event))

    def test_formal_include_requires_each_minimum_evidence_exactly_once(self):
        event = self.source(role="formal", quality=True)
        for kind in ("capture_provenance", "quality", "analysis_manifest", "canonical_frames"):
            changed = deepcopy(event)
            changed["evidence"] = [e for e in changed["evidence"] if e["kind"] != kind]
            with self.subTest(missing=kind), self.assertRaises(ValueError):
                self.append(changed)
            changed = deepcopy(event)
            changed["evidence"].append(next(e for e in changed["evidence"] if e["kind"] == kind))
            with self.subTest(duplicate=kind), self.assertRaises(ValueError):
                self.append(changed)
        self.append(event)
        self.resolve(self.build(event, role="formal", policy="synthetic-policy/1"))

    def test_formal_include_and_exclude_require_policy(self):
        for include in (False, True):
            event = self.source(rid="formal_" + str(include), role="formal", include=include, quality=include)
            for policy in (None, "", "  "):
                with self.subTest(include=include, policy=policy), self.assertRaisesRegex(ValueError, "policy"):
                    self.append(dict(event, selection_policy_version=policy))

    def test_quality_verdict_never_selects_or_excludes(self):
        for verdict in ("ok", "ok_with_warnings", "retake"):
            event = self.source(rid="formal_" + verdict, subject=verdict, role="formal", quality=True, verdict=verdict)
            if verdict == "ok":
                self.assertFalse(self.ledger.exists())
            self.append(event)
            self.resolve(self.build(event, role="formal", policy="synthetic-policy/1"))
        self.assertEqual(len(selection.read_selection_events(self.root)), 3)

    def test_quality_recording_identity_and_hash_required(self):
        event = self.source(role="formal", quality=True)
        self.repin(event, "quality", {"recording_id": "different"})
        with self.assertRaisesRegex(ValueError, "recording_id mismatch"):
            self.append(event)

    def test_exclude_without_any_analysis_run(self):
        event = self.source(include=False)
        self.append(event)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(selection.read_selection_events(self.root), [event])
        with self.assertRaisesRegex(ValueError, "include"):
            self.build(event)

    def test_exclude_can_pin_existing_analysis_and_quality(self):
        event = self.source(quality=True)
        event["decision"].update(disposition="exclude", analysis_selection=None)
        self.append(event)
        self.assertEqual(selection.read_selection_events(self.root), [event])

    def test_recapture_pins_both_provenances_and_does_not_select(self):
        parent = self.source()
        child = self.source(rid="P01_r1_recapture")
        self.append(parent)
        relation = self.relation(child, parent)
        self.append(relation)
        self.resolve(self.build(parent))  # Relationship does not replace/exclude parent.
        with self.assertRaisesRegex(ValueError, "include"):
            self.build(relation)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.build(child)  # Child has no decision until explicitly appended.
        self.assertEqual(relation["round"], parent["round"])
        self.assertNotEqual(child["recording_id"], parent["recording_id"])
        self.assertEqual(len(selection.read_selection_events(self.root)), 2)
        child["supersedes_selection_event_id"] = parent["selection_event_id"]
        self.append(child)
        self.resolve(self.build(child))

    def test_recapture_missing_or_duplicate_parent_child_evidence_rejected(self):
        parent = self.source(include=False)
        child = self.source(rid="child", include=False)
        relation = self.relation(child, parent)
        for index in (0, 1):
            for duplicate in (False, True):
                changed = deepcopy(relation)
                if duplicate:
                    changed["evidence"].append(deepcopy(changed["evidence"][index]))
                else:
                    del changed["evidence"][index]
                with self.subTest(index=index, duplicate=duplicate), self.assertRaises(ValueError):
                    self.append(changed)

    def test_recapture_parent_capture_slot_role_and_hash_validation(self):
        child = self.source(rid="child", include=False)
        for index, kwargs in enumerate((dict(subject="P02"), dict(rnd="2"), dict(role="formal"))):
            parent = self.source(rid="parent" + str(index), include=False, **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "slot/role"):
                self.append(self.relation(child, parent))
        parent = self.source(rid="parent_tampered", include=False)
        relation = self.relation(child, parent)
        (self.root / parent["evidence"][0]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.append(relation)

    def test_recapture_self_link_rejected(self):
        event = self.source(include=False)
        relation = self.relation(event, event)
        relation["evidence"] = relation["evidence"][:1]
        with self.assertRaisesRegex(ValueError, "self-link"):
            self.append(relation)

    def test_recapture_cycle_rejected(self):
        a, b, c = [self.source(rid=rid, include=False) for rid in ("a", "b", "c")]
        self.append(self.relation(b, a))
        self.append(self.relation(c, b))
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.append(self.relation(a, c))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_recapture_multiple_direct_parents_rejected(self):
        a, b, c = [self.source(rid=rid, include=False) for rid in ("a", "b", "c")]
        self.append(self.relation(c, a))
        with self.assertRaisesRegex(ValueError, "multiple direct"):
            self.append(self.relation(c, b))

    def test_recapture_exact_shape_and_no_supersession_or_decision(self):
        parent = self.source(include=False)
        child = self.source(rid="child", include=False, role="formal")
        relation = self.relation(child, parent)
        for update in (dict(recapture=None), dict(recapture={}), dict(recapture={"recapture_of_recording_id": "p", "extra": 1}),
                       dict(decision=parent["decision"]), dict(supersedes_selection_event_id=parent["selection_event_id"])):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.append(dict(relation, **update))

    def test_formal_pure_recapture_allows_null_policy(self):
        parent = self.source(role="formal", include=False)
        child = self.source(rid="child", role="formal", include=False)
        event = self.relation(child, parent)
        self.append(event)
        self.assertIsNone(selection.read_selection_events(self.root)[0]["selection_policy_version"])

    def test_selected_analysis_exact_shape(self):
        event = self.source()
        for field in list(event["decision"]["analysis_selection"]) + ["extra"]:
            changed = deepcopy(event)
            if field == "extra":
                changed["decision"]["analysis_selection"][field] = 1
            else:
                del changed["decision"]["analysis_selection"][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.append(changed)
        changed = deepcopy(event)
        changed["decision"]["analysis_selection"] = None
        with self.assertRaises(ValueError):
            self.append(changed)

    def test_selected_owner_status_identity_output_path_and_hash(self):
        event = self.source()
        owner_path = self.root / event["decision"]["analysis_selection"]["analysis_manifest_path"]
        original = owner_path.read_bytes()
        owner = json.loads(original)
        updates = [dict(status="running"), dict(status="failed"), dict(recording_id="different"),
                   dict(analysis_run_id="ar_different"), dict(outputs=[]),
                   dict(outputs=[dict(owner["outputs"][0], sha256="a" * 64)]),
                   dict(outputs=[dict(owner["outputs"][0], path=str(self.root / "other_frames.csv"))]),
                   dict(outputs=owner["outputs"] * 2)]
        for update in updates:
            owner_path.write_bytes(original)
            changed = deepcopy(event)
            self.repin(changed, "analysis_manifest", update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.append(changed)

    def test_selected_binding_requires_exact_run_schema_and_owner_path(self):
        event = self.source()
        for update in (dict(analysis_run_id="ar_other"), dict(frames_schema_version="frames-schema/2.0.0"),
                       dict(frames_sha256="b" * 64), dict(analysis_manifest_sha256="b" * 64)):
            changed = deepcopy(event)
            changed["decision"]["analysis_selection"].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.append(changed)
        owner_item = next(e for e in event["evidence"] if e["kind"] == "analysis_manifest")
        copied = self.root / "copied_owner.json"
        copied.write_bytes((self.root / owner_item["path"]).read_bytes())
        owner_item["path"] = "copied_owner.json"
        event["decision"]["analysis_selection"]["analysis_manifest_path"] = "copied_owner.json"
        with self.assertRaisesRegex(ValueError, "selected source"):
            self.append(event)

    def test_capture_analysis_role_and_protocol_mismatch(self):
        event = self.source()
        path = self.root / event["decision"]["analysis_selection"]["analysis_manifest_path"]
        original = path.read_bytes()
        for update in (dict(dataset_role="formal"), dict(dataset_role="external"), dict(protocol_version="other")):
            path.write_bytes(original)
            changed = deepcopy(event)
            self.repin(changed, "analysis_manifest", update)
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, "role|protocol"):
                self.append(changed)

    def test_protocol_equality_does_not_hardcode_a_scientific_version(self):
        event = self.source(protocol="explicit-synthetic-version/987")
        self.append(event)
        self.resolve(self.build(event))

    def test_frame_exact_60_fields_no_role_or_protocol_columns(self):
        event = self.source()
        frames = self.root / event["decision"]["analysis_selection"]["frames_path"]
        with frames.open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
        self.assertEqual(len(header), 60)
        self.assertEqual(tuple(header), analysis.FRAME_FIELDS)
        self.assertNotIn("dataset_role", header)
        self.assertNotIn("protocol_version", header)
        self.append(event)
        self.resolve(self.build(event))

    def test_bad_frame_header_identity_and_schema_use_patch5_validation(self):
        for index, update in enumerate((dict(subject="P99"), dict(round="2"), dict(recording_id="other"),
                                       dict(analysis_run_id="ar_other"), dict(frame_schema_version="frames-schema/9.0.0"))):
            event = self.source(rid="bad_frame_" + str(index), rows=[dict(update, step=1, label="upright")])
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.append(event)
        event = self.source()
        frames_item = next(e for e in event["evidence"] if e["kind"] == "canonical_frames")
        frames = self.root / frames_item["path"]
        frames.write_bytes(b"subject,round,dataset_role,protocol_version\nP01,1,pilot,test\n")
        digest = hashlib.sha256(frames.read_bytes()).hexdigest()
        frames_item["sha256"] = event["decision"]["analysis_selection"]["frames_sha256"] = digest
        owner = json.loads((frames.parent / "analysis_manifest.json").read_text(encoding="utf-8"))
        owner["outputs"][0]["sha256"] = digest
        self.repin(event, "analysis_manifest", {"outputs": owner["outputs"]})
        with self.assertRaisesRegex(ValueError, "60-field"):
            self.append(event)

    def test_artifact_paths_reject_absolute_traversal_and_non_normalized(self):
        event = self.source(include=False)
        paths = ("/tmp/a", "C:/temp/a", "C:relative.json", "\\\\server\\share\\a", "../a", "data/../a",
                 "data/./a", "./data/a", "data//a", "data\\a", "data/a/", "data/a:stream", "data/\x00a",
                 "data/a.", "data/a ", "data/.. /a", "data/NUL", "data/CON.txt")
        for path in paths:
            changed = deepcopy(event)
            changed["evidence"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.append(changed)

    def test_resolved_link_escape_is_rejected(self):
        # Model a resolved symlink/junction without requiring Windows symlink privileges.
        original = Path.resolve
        link = self.root / "escape" / "capture.json"
        def resolved(path, *args, **kwargs):
            return self.root.parent / "outside.json" if path == link else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolved), self.assertRaisesRegex(ValueError, "outside repository"):
            selection.resolve_artifact(self.root, "escape/capture.json")

    def test_selected_artifact_path_checks_apply_to_frames_and_owner(self):
        event = self.source()
        for field in ("frames_path", "analysis_manifest_path"):
            for value in ("../outside", str(self.root / "absolute")):
                changed = deepcopy(event)
                changed["decision"]["analysis_selection"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.append(changed)

    def test_all_evidence_bytes_are_pinned_including_other(self):
        event = self.source(quality=True)
        other = self.root / "note.txt"
        other.write_bytes(b"synthetic decision evidence")
        event["evidence"].append(self.evidence(other, "other", event["recording_id"]))
        for item in event["evidence"]:
            path = self.root / item["path"]
            before = path.read_bytes()
            path.write_bytes(before + b"tamper")
            with self.subTest(kind=item["kind"]), self.assertRaisesRegex(ValueError, "SHA-256"):
                self.append(event)
            path.write_bytes(before)
        self.append(event)

    def test_same_slot_unlinked_second_decision_rejected_for_same_or_different_recording(self):
        first = self.source()
        self.append(first)
        other = self.source(rid="another_recording")
        before = self.ledger.read_bytes()
        for source in (first, other):
            for disposition in ("include", "exclude"):
                new = deepcopy(source)
                new["selection_event_id"] = selection.new_event_id()
                new["decision"]["disposition"] = disposition
                if disposition == "exclude":
                    new["decision"]["analysis_selection"] = None
                    new["evidence"] = new["evidence"][:1]
                with self.subTest(recording=new["recording_id"], disposition=disposition):
                    with self.assertRaisesRegex(ValueError, "unlinked.*terminal"):
                        self.append(new)
                    self.assertEqual(self.ledger.read_bytes(), before)

    def test_branching_supersession_rejected_without_appending(self):
        a = self.source(include=False)
        self.append(a)
        b = deepcopy(a)
        b.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=a["selection_event_id"])
        self.append(b)
        before = self.ledger.read_bytes()
        for source in (a, self.source(rid="different_recording", include=False)):
            c = deepcopy(source)
            c.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=a["selection_event_id"])
            with self.subTest(recording=c["recording_id"]), self.assertRaisesRegex(ValueError, "branching.*terminal"):
                self.append(c)
            self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(selection.read_selection_events(self.root), [a, b])

    def test_invalid_unlinked_or_branching_ledger_rejected_by_all_consumers(self):
        a = self.source()
        self.append(a)
        path = self.build(a)
        b = dict(a, selection_event_id=selection.new_event_id())
        linked_b = dict(b, supersedes_selection_event_id=a["selection_event_id"])
        c = dict(a, selection_event_id=selection.new_event_id(), supersedes_selection_event_id=a["selection_event_id"])
        for events, message in (([a, b], "unlinked"), ([a, linked_b, c], "branching")):
            data = b"".join(selection.event_bytes(e) for e in events)
            self.ledger.write_bytes(data)
            new = dict(a, selection_event_id=selection.new_event_id(), supersedes_selection_event_id=events[-1]["selection_event_id"])
            with self.subTest(history=message):
                for consume in (lambda: selection.read_selection_events(self.root), lambda: self.append(new),
                                lambda: self.build(events[-1]), lambda: self.resolve(path)):
                    with self.assertRaisesRegex(ValueError, message):
                        consume()
                self.assertEqual(self.ledger.read_bytes(), data)

    def test_cross_recording_same_slot_linear_chain_and_historical_snapshot(self):
        a = self.source(rid="R1", role="formal", include=False)
        b = self.source(rid="R2", role="formal", quality=True)
        c = self.source(rid="R3", role="formal", quality=True)
        self.append(a)
        b["supersedes_selection_event_id"] = a["selection_event_id"]
        self.append(b)
        old_path = self.build(b, role="formal", policy="synthetic-policy/1")
        old_bytes = old_path.read_bytes()
        old_inputs, old_reference = self.resolve(old_path)
        c["supersedes_selection_event_id"] = b["selection_event_id"]
        self.append(c)
        self.assertEqual(selection.read_selection_events(self.root), [a, b, c])
        with self.assertRaisesRegex(ValueError, "superseded"):
            self.build(b, role="formal", policy="synthetic-policy/1")
        new_path = self.build(c, role="formal", policy="synthetic-policy/1")
        self.assertEqual(self.resolve(new_path)[0][0]["recording_id"], "R3")
        self.assertEqual(self.resolve(old_path, old_reference["sha256"]), (old_inputs, old_reference))
        self.assertEqual(old_inputs[0]["recording_id"], "R2")
        self.assertEqual(old_path.read_bytes(), old_bytes)

    def test_terminal_decisions_are_independent_for_different_logical_slots(self):
        a = self.source(include=False)
        self.append(a)
        for rid, kwargs in (("different_role", dict(role="formal")),
                            ("different_subject", dict(subject="P02")), ("different_round", dict(rnd="2"))):
            first = self.source(rid=rid, include=False, **kwargs)
            self.append(first)  # A decision in another slot requires no supersession.
            second = dict(first, selection_event_id=selection.new_event_id(),
                          supersedes_selection_event_id=first["selection_event_id"])
            self.append(second)
        next_a = dict(a, selection_event_id=selection.new_event_id(), supersedes_selection_event_id=a["selection_event_id"])
        self.append(next_a)
        self.assertEqual(len(selection.read_selection_events(self.root)), 8)

    def test_supersession_chain_and_new_manifest_rejects_superseded(self):
        a = self.source()
        self.append(a)
        b = deepcopy(a)
        b.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=a["selection_event_id"])
        self.append(b)
        c = deepcopy(b)
        c.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=b["selection_event_id"])
        self.append(c)
        for old in (a, b):
            with self.subTest(old=old["selection_event_id"]), self.assertRaisesRegex(ValueError, "superseded"):
                self.build(old)
        self.resolve(self.build(c))

    def test_old_immutable_manifest_remains_valid_after_later_exclusion(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        before = path.read_bytes()
        inputs, reference = self.resolve(path)
        exclusion = deepcopy(event)
        exclusion.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=event["selection_event_id"])
        exclusion["decision"].update(disposition="exclude", analysis_selection=None)
        exclusion["evidence"] = exclusion["evidence"][:1]
        self.append(exclusion)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.resolve(path, reference["sha256"]), (inputs, reference))
        with self.assertRaisesRegex(ValueError, "superseded"):
            self.build(event)

    def test_old_and_new_manifest_pin_different_explicit_recaptures(self):
        original = self.source()
        self.append(original)
        first = self.build(original)
        recapture = self.source(rid="recapture")
        recapture["supersedes_selection_event_id"] = original["selection_event_id"]
        self.append(recapture)
        second = self.build(recapture)
        self.assertNotEqual(first, second)
        self.assertEqual(self.resolve(first)[0][0]["recording_id"], original["recording_id"])
        self.assertEqual(self.resolve(second)[0][0]["recording_id"], recapture["recording_id"])

    def test_supersedes_missing_self_forward_recapture_and_slot_mismatch(self):
        event = self.source(include=False)
        for target in (event["selection_event_id"], selection.new_event_id()):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "supersedes"):
                self.append(dict(event, supersedes_selection_event_id=target))
        self.append(event)
        for index, kwargs in enumerate((dict(subject="P02"), dict(rnd="2"), dict(role="formal"))):
            other = self.source(rid="other" + str(index), include=False, **kwargs)
            other["supersedes_selection_event_id"] = event["selection_event_id"]
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "supersedes"):
                self.append(other)
        child = self.source(rid="child", include=False)
        relation = self.relation(child, event)
        self.append(relation)
        child["supersedes_selection_event_id"] = relation["selection_event_id"]
        with self.assertRaisesRegex(ValueError, "supersedes"):
            self.append(child)

    def test_reader_rejects_broken_history_in_canonical_bytes(self):
        a, b, c = [self.source(rid=rid, include=False) for rid in ("a", "b", "c")]
        self.append(a)
        cases = ([self.relation(a, b), self.relation(b, a)],
                 [self.relation(c, a), self.relation(c, b)],
                 [dict(a, supersedes_selection_event_id=b["selection_event_id"]), b])
        for events in cases:
            self.ledger.write_bytes(b"".join(selection.event_bytes(event) for event in events))
            with self.subTest(events=events), self.assertRaises(ValueError):
                selection.read_selection_events(self.root)

    def test_dataset_manifest_exact_fields_and_canonical_bytes(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        data = path.read_bytes()
        manifest = json.loads(data)
        self.assertEqual(set(manifest), MANIFEST_KEYS)
        self.assertEqual(set(manifest["entries"][0]), ENTRY_KEYS)
        self.assertEqual(manifest["schema_version"], "dataset-selection-manifest/1.0.0")
        self.assertEqual(manifest["selection_events_path"], "manifests/selection_events.jsonl")
        self.assertEqual(path.name, manifest["dataset_manifest_id"] + ".json")
        self.assertEqual(data, (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        self.assertNotIn(b"\r", data)
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn("sha256", manifest)
        self.assertEqual(self.resolve(path)[1]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest["entries"][0]["selection_event_sha256"], hashlib.sha256(self.ledger.read_bytes()).hexdigest())

    def test_manifest_exact_top_and_entry_schema_negative(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = path.read_bytes()
        for level, fields in (("top", MANIFEST_KEYS), ("entry", ENTRY_KEYS)):
            for field in sorted(fields | {"extra"}):
                path.write_bytes(original)
                def mutate(value):
                    target = value if level == "top" else value["entries"][0]
                    target.update(extra=True) if field == "extra" else target.pop(field)
                self.mutate_manifest(path, mutate)
                with self.subTest(level=level, field=field), self.assertRaises(ValueError):
                    self.resolve(path)

    def test_manifest_bad_field_types_and_enum_values(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = path.read_bytes()
        for update in (dict(schema_version="other"), dict(dataset_manifest_id="dm_bad"), dict(created_at=None),
                       dict(created_by=" "), dict(dataset_role="external"), dict(selection_policy_version=1),
                       dict(selection_events_path="../selection_events.jsonl"), dict(entries={}), dict(entries=[None])):
            path.write_bytes(original)
            self.mutate_manifest(path, lambda m: m.update(update))
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.resolve(path)

    def test_manifest_bad_entry_identity_hash_role_round_and_paths(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = path.read_bytes()
        for update in (dict(round=1), dict(round="0"), dict(subject="other"), dict(dataset_role="formal"),
                       dict(recording_id="other"), dict(analysis_run_id="ar_other"), dict(frames_sha256="a" * 64),
                       dict(frames_schema_version="frames-schema/2.0.0"), dict(selection_event_sha256="b" * 64),
                       dict(selection_event_id=selection.new_event_id()), dict(frames_path="../frames.csv"),
                       dict(analysis_manifest_path=str(self.root / "analysis.json"))):
            path.write_bytes(original)
            self.mutate_manifest(path, lambda m: m["entries"][0].update(update))
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.resolve(path)

    def test_manifest_no_overwrite_even_existing_partial_file(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        before = path.read_bytes()
        with patch.object(selection, "new_dataset_manifest_id", return_value=path.stem):
            with self.assertRaises(FileExistsError):
                self.build(event)
        self.assertEqual(path.read_bytes(), before)
        path.write_bytes(b"partial")
        with patch.object(selection, "new_dataset_manifest_id", return_value=path.stem):
            with self.assertRaises(FileExistsError):
                self.build(event)
        self.assertEqual(path.read_bytes(), b"partial")

    def test_unique_logical_slot_duplicate_source_and_duplicate_id_rejected(self):
        a, b = self.source(), self.source(rid="recapture")
        self.append(a)
        path = self.build(a)
        b["supersedes_selection_event_id"] = a["selection_event_id"]
        self.append(b)
        with self.assertRaisesRegex(ValueError, "logical slot"):
            self.build(b, b)
        current = json.loads(self.build(b).read_bytes())["entries"][0]
        original = path.read_bytes()
        for entry in (json.loads(original)["entries"][0], current):
            path.write_bytes(original)
            self.mutate_manifest(path, lambda m: m["entries"].append(deepcopy(entry)))
            with self.subTest(recording=entry["recording_id"]), self.assertRaisesRegex(ValueError, "logical slot"):
                self.resolve(path)

    def test_manifest_creation_never_redirects_an_occupied_id_to_alias_target(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        before = path.read_bytes()
        alias_target = path.with_name("unoccupied_alias_target.json")
        original = Path.resolve
        def resolved(candidate, *args, **kwargs):
            return alias_target if candidate == path else original(candidate, *args, **kwargs)
        # Model a final symlink resolution without Windows symlink privileges.
        with patch.object(Path, "resolve", resolved), \
                patch.object(selection, "new_dataset_manifest_id", return_value=path.stem):
            with self.assertRaises(FileExistsError):
                self.build(event)
        self.assertFalse(alias_target.exists())
        self.assertEqual(path.read_bytes(), before)

    def test_manifest_deterministic_subject_and_numeric_round_order(self):
        events = [self.source(rid=f"{sub}_{rnd}", subject=sub, rnd=rnd)
                  for sub, rnd in (("P02", "1"), ("P01", "10"), ("P01", "2"), ("P01", "1"))]
        for event in events:
            self.append(event)
        path = self.build(*events)
        manifest = json.loads(path.read_bytes())
        self.assertEqual([(e["subject"], e["round"]) for e in manifest["entries"]],
                         [("P01", "1"), ("P01", "2"), ("P01", "10"), ("P02", "1")])
        self.resolve(path)
        self.mutate_manifest(path, lambda m: m["entries"].reverse())
        with self.assertRaisesRegex(ValueError, "ordered"):
            self.resolve(path)

    def test_manifest_formal_policy_and_exact_event_policy_match(self):
        event = self.source(role="formal", quality=True)
        self.append(event)
        for policy in (None, "", "  ", "different-policy"):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, "policy"):
                self.build(event, role="formal", policy=policy)
        path = self.build(event, role="formal", policy="synthetic-policy/1")
        self.mutate_manifest(path, lambda m: m.update(selection_policy_version=None))
        with self.assertRaisesRegex(ValueError, "policy"):
            self.resolve(path)

    def test_pilot_manifest_policy_matches_included_event(self):
        event = self.source()
        event["selection_policy_version"] = "synthetic-pilot-policy"
        self.append(event)
        with self.assertRaisesRegex(ValueError, "policy"):
            self.build(event)
        self.resolve(self.build(event, policy="synthetic-pilot-policy"))

    def test_pilot_formal_promotion_mixing_and_external_role_rejected(self):
        pilot = self.source()
        formal = self.source(rid="formal", subject="P02", role="formal", quality=True)
        self.append(pilot)
        self.append(formal)
        for events, role, policy in (((pilot,), "formal", "synthetic-policy/1"), ((formal,), "pilot", None),
                                     ((pilot, formal), "pilot", None), ((pilot,), "external", None)):
            with self.subTest(role=role, events=events), self.assertRaises(ValueError):
                self.build(*events, role=role, policy=policy)

    def test_selected_event_line_tamper_and_removal_rejected(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        changed = deepcopy(event)
        changed["decision"]["reason_text"] = "tampered reason"
        self.ledger.write_bytes(selection.event_bytes(changed))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.resolve(path)
        self.ledger.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.resolve(path)

    def test_snapshot_revalidation_checks_selected_evidence_bytes(self):
        event = self.source(quality=True)
        self.append(event)
        path = self.build(event)
        for evidence in event["evidence"]:
            source = self.root / evidence["path"]
            original = source.read_bytes()
            source.write_bytes(original + b"\n")
            with self.subTest(kind=evidence["kind"]), self.assertRaisesRegex(ValueError, "SHA-256"):
                self.resolve(path)
            source.write_bytes(original)

    def test_historical_snapshot_does_not_depend_on_unselected_source_bytes(self):
        first = self.source()
        self.append(first)
        path = self.build(first)
        later = self.source(rid="later", include=False)
        later["supersedes_selection_event_id"] = first["selection_event_id"]
        self.append(later)
        (self.root / later["evidence"][0]["path"]).unlink()
        self.resolve(path)
        with self.assertRaises(ValueError):
            selection.read_selection_events(self.root)

    def test_manifest_hash_path_and_lf_tamper_rejected(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.resolve(path, "a" * 64)
        copy_path = path.with_name(selection.new_dataset_manifest_id() + ".json")
        copy_path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "ID/path"):
            self.resolve(copy_path)
        for data in (original[:-1], original.replace(b"\n", b"\r\n"), b"\xef\xbb\xbf" + original):
            path.write_bytes(data)
            with self.subTest(data=data[:25]), self.assertRaises(ValueError):
                self.resolve(path)

    def test_manifest_resolves_via_existing_patch5_validator_and_ambiguity_guard(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        frames = self.root / event["decision"]["analysis_selection"]["frames_path"]
        with patch.object(rf, "canonical_input", wraps=rf.canonical_input) as canonical, \
                patch.object(rf, "reject_input_ambiguity", wraps=rf.reject_input_ambiguity) as ambiguity:
            inputs, reference = self.resolve(path)
        canonical.assert_called_once_with(frames, self.out)
        ambiguity.assert_called_once_with(inputs)
        self.assertEqual(inputs, rf.resolve_ours_inputs(paths=[frames]))
        self.assertEqual(reference["path"], str(path))
        self.assertFalse(Path(event["decision"]["analysis_selection"]["frames_path"]).is_absolute())
        self.assertTrue(Path(inputs[0]["frames_path"]).is_absolute())

    def test_multiple_available_runs_require_explicit_choice_and_manual_guards_remain(self):
        one = self.source()
        two = self.source(run="ar_two")
        self.append(one)
        old_path = self.build(one)
        old_bytes = old_path.read_bytes()
        two["supersedes_selection_event_id"] = one["selection_event_id"]
        self.append(two)
        first = self.root / one["decision"]["analysis_selection"]["frames_path"]
        second = self.root / two["decision"]["analysis_selection"]["frames_path"]
        with self.assertRaisesRegex(ValueError, "multiple completed"):
            rf.resolve_ours_inputs(["P01"])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            rf.resolve_ours_inputs(paths=[first, second])
        with self.assertRaisesRegex(ValueError, "superseded"):
            self.build(one)
        self.assertEqual(self.resolve(old_path)[0][0]["analysis_run_id"], "ar_one")
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual(self.resolve(self.build(two))[0][0]["analysis_run_id"], "ar_two")

    def test_gitattributes_protect_only_selection_artifacts(self):
        result = subprocess.run(["git", "check-attr", "text", "eol", "--", "manifests/selection_events.jsonl",
                                 "manifests/datasets/dm_test.json", "manifests/recordings.jsonl"],
                                cwd=Path(__file__).parent, capture_output=True, text=True, check=True)
        self.assertIn("manifests/selection_events.jsonl: eol: lf", result.stdout)
        self.assertIn("manifests/datasets/dm_test.json: eol: lf", result.stdout)
        self.assertIn("manifests/recordings.jsonl: eol: unspecified", result.stdout)
        self.assertFalse((self.root / "manifests/recordings.jsonl").exists())

    def paper(self):
        path = self.root / "synthetic.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["header"] * 23)
        for subject in ("S1", "S2"):
            for label in range(1, 6):
                row = [None] * 23
                row[0], row[1] = "sample_" + subject, label
                row[5], row[6], row[15], row[16], row[10], row[11] = 300 + label, 150 + label, 220, 300, 420, 300
                row[22] = 1 + label / 10
                sheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    def run_rf(self, manifest_path=None, frames_path=None):
        argv = ["rf_experiment.py", "--paper", str(self.paper()), "--trees", "2", "--seeds", "1",
                "--lams", "0", "--features", "all", "invariant", "relative"]
        if manifest_path is not None:
            argv += ["--dataset-manifest", str(manifest_path)]
        if frames_path is not None:
            argv += ["--ours-frames", str(frames_path)]
        with patch("sys.argv", argv), patch.object(rf, "plot"):
            directory = rf.main()
        return directory, json.loads((directory / "experiment_manifest.json").read_bytes())

    def test_cli_dataset_manifest_and_ours_mutually_exclusive_including_empty_ours(self):
        for args in (("--ours", "P01"), ("--ours",)):
            with patch("sys.argv", ["rf_experiment.py", "--dataset-manifest", "some.json", *args]):
                with self.assertRaises(SystemExit) as error:
                    rf.main()
                self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.results.exists())

    def test_cli_dataset_manifest_and_ours_frames_mutually_exclusive(self):
        with patch("sys.argv", ["rf_experiment.py", "--ours-frames", "some.csv", "--dataset-manifest", "some.json"]):
            with self.assertRaises(SystemExit) as error:
                rf.main()
            self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.results.exists())

    def test_rf_manifest_binding_exact_inputs_result_hash_and_sample_schema(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        inputs, reference = self.resolve(path)
        directory, manifest = self.run_rf(path)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["dataset_manifest"], reference)
        self.assertEqual(manifest["inputs"]["ours"], inputs)
        self.assertEqual(manifest["options"]["dataset_manifest"], str(path))
        self.assertEqual(manifest["schema_version"], "rf-experiment-provenance/1.0.0")
        with (directory / "rf_results.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(rows)
        self.assertTrue(all(r["dataset_manifest_sha256"] == reference["sha256"] for r in rows))
        lineage = [json.loads(line) for line in (directory / "sample_lineage.jsonl").read_bytes().splitlines()]
        self.assertEqual(len(lineage), 45)
        self.assertTrue(all(set(r) == set(rf.LINEAGE_FIELDS) and r["schema_version"] == "rf-sample-lineage/1.0.0" for r in lineage))
        ours = [r for r in lineage if r["source_kind"] == "canonical_frames"]
        self.assertEqual(len(ours), 15)
        self.assertTrue(all(r["frames_sha256"] == inputs[0]["frames_sha256"] for r in ours))

    def test_manifest_and_manual_numeric_results_and_references_identical(self):
        event = self.source(rows=[dict(step=3, label="lean_left", oval_area_px=120, face_x=670),
                                  dict(step=1, label="upright", face_x=""), dict(step=2, label="upright", face_x=640),
                                  dict(step=4, label="body_forward", oval_area_px=200, face_x=700)])
        self.append(event)
        path = self.build(event)
        frames = self.root / event["decision"]["analysis_selection"]["frames_path"]
        observed = []
        original = rf.external
        def observe(Xtr, ytr, Xte, yte, meta, *args, **kwargs):
            observed.append((kwargs["feature_set"], Xte.copy(), yte.copy(), list(meta), kwargs["ref_mask"]))
            return original(Xtr, ytr, Xte, yte, meta, *args, **kwargs)
        with patch.object(rf, "external", side_effect=observe):
            manual_dir, manual = self.run_rf(frames_path=frames)
            selected_dir, _ = self.run_rf(manifest_path=path)
        self.assertEqual(manual["dataset_manifest"], dict(dataset_manifest_id=None, path=None, sha256=None))
        self.assertEqual(len(observed), 6)
        for first, second in zip(observed[:3], observed[3:]):
            self.assertEqual(first[0], second[0])
            np.testing.assert_array_equal(first[1], second[1])
            np.testing.assert_array_equal(first[2], second[2])
            self.assertEqual(first[3], second[3])
            np.testing.assert_array_equal(first[4], second[4])
        np.testing.assert_array_equal(observed[-1][4], [True, False, False])
        results = []
        for directory in (manual_dir, selected_dir):
            with (directory / "rf_results.csv").open(encoding="utf-8-sig", newline="") as stream:
                results.append([{k: v for k, v in row.items() if k not in rf.RESULT_LINEAGE_FIELDS}
                                for row in csv.DictReader(stream)])
        self.assertEqual(*results)

    def test_rf_rejects_manifest_or_capture_mutation_before_completion(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = rf.execute_experiment
        targets = (path, self.root / event["evidence"][0]["path"])
        for target in targets:
            before = target.read_bytes()
            def mutate(*args):
                original(*args)
                target.write_bytes(before + b"\n")
            with self.subTest(target=target), patch.object(rf, "execute_experiment", side_effect=mutate):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    self.run_rf(path)
            target.write_bytes(before)
        manifests = [json.loads(p.read_bytes()) for p in self.results.glob("*/experiment_manifest.json")]
        self.assertEqual(len(manifests), 2)
        self.assertTrue(all(m["status"] == "failed" for m in manifests))
        self.assertFalse((self.out / "rf_results.csv").exists())

    def test_rf_old_manifest_remains_usable_after_supersession_during_run(self):
        event = self.source()
        self.append(event)
        path = self.build(event)
        original = rf.execute_experiment
        def supersede(*args):
            original(*args)
            changed = deepcopy(event)
            changed.update(selection_event_id=selection.new_event_id(), supersedes_selection_event_id=event["selection_event_id"])
            changed["decision"].update(disposition="exclude", analysis_selection=None)
            changed["evidence"] = changed["evidence"][:1]
            self.append(changed)
        with patch.object(rf, "execute_experiment", side_effect=supersede):
            _, manifest = self.run_rf(path)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["dataset_manifest"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
