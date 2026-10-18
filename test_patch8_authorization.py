"""Registry gate regressions using isolated temporary Git repositories, never hardware.

All IDs, registries, commits and runtime evidence below belong to disposable test
fixtures. No repository execution registry or formal measurement is created.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import patch8_ledger as ledger
import patch8_protocol as p8
import patch8_validation as validation


def fixture_id(letter):
    return "p8x_20261007T000000000000Z_" + letter * 32


FIRST, SECOND, THIRD = (fixture_id(letter) for letter in "abc")
HEX = "1" * 64


def fields_text(fields):
    return "".join(f"{key}: {value}\n" for key, value in fields.items())


class RegistryAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Produce official, linked result bundles using the actual synthetic pipeline once.
        import test_patch8_orchestration as orchestration
        from patch8_test_fixtures import pinhole_factory
        cls.bundles = {}
        for result in ("PASS", "FAIL"):
            case = orchestration.ReconciliationAndReportTests()
            case.setUp()
            cls.addClassCleanup(case.doCleanups)
            case.full_passing_execution()
            if result == "FAIL":
                # A fully acquired, analyzed E2E capture with a failing verdict.
                # Use a fresh fixture, so no previously published data is altered.
                case.doCleanups()
                case.setUp()
                case.world.production["131"] = dict(verdict="ok_with_warnings")
                case.full_passing_execution()
            with patch.object(validation.report.metrics, "sdk_deprojector", pinhole_factory):
                published = validation.evaluate(case.rt, orchestration.EXECUTION_ID, publish=True)
            if published["execution"]["computed_result"] != result:
                raise AssertionError(published["execution"])
            cls.bundles[result] = validation.execution_dir(case.root, orchestration.EXECUTION_ID)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="patch8-gate-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt = validation.Runtime(root=self.root)
        self.git("init", "--quiet", "--template=")
        self.git("config", "user.name", "Patch 8 Test Fixture")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "true")
        self.git("config", "commit.gpgsign", "false")
        objects = Path(subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                                               cwd=validation.ROOT, text=True).strip())
        (self.root / ".git" / "objects" / "info" / "alternates").write_bytes((objects.as_posix() + "\n").encode("utf-8"))
        (self.root / "implementation.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("validation/\ndata/\nanalysis/\nresults/\nruntime/\nmodels/\n", encoding="utf-8")
        self.git("add", ".")
        tree = self.git("write-tree")
        self.audit = self.git("commit-tree", tree, "-p", validation.DESIGN_FREEZE_COMMIT, input="synthetic fixture\n")
        self.git("update-ref", "HEAD", self.audit)
        # Unit-test process injection does not provide a production runtime-root option.
        # Separate subprocess tests below exercise the unpatched location gate.
        root_patch = patch.object(validation, "_require_runtime_root", side_effect=lambda root: Path(root).resolve())
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.evidence = Path(self.temp.name).parent / (self.root.name + "-retained")
        self.addCleanup(lambda: shutil.rmtree(self.evidence, ignore_errors=True))
        self.prior_evidence = {}
        self.registry = self.root / p8.EXECUTION_REGISTRY_PATH
        self.registry.parent.mkdir(parents=True)

    def git(self, *args, input=None):
        return subprocess.run(["git", *args], cwd=self.root, input=input, capture_output=True,
                              text=True, check=True, timeout=30).stdout.strip()

    def commit(self):
        # Commits only in this test's TemporaryDirectory; never in the working repository.
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "synthetic test fixture")
        return self.git("rev-parse", "HEAD")

    def auth_fields(self, identity=FIRST, commit=None, **updates):
        fields = dict(execution_id=identity, status="AUTHORIZED / NOT_STARTED",
                      reserved_validation_subject="V01", design_freeze_commit=validation.DESIGN_FREEZE_COMMIT,
                      audited_implementation_commit=commit or self.audit, capture_host="fixture-host",
                      analysis_host="fixture-host", planned_date_session="synthetic test only")
        fields.update(updates)
        return fields

    def auth(self, identity=FIRST, commit=None, **updates):
        return "## Authorization\n" + fields_text(self.auth_fields(identity, commit, **updates))

    def disposition(self, identity=FIRST, result="FAIL", **updates):
        # Bundles have the pipeline's own execution_id; rebind all canonical ledger events
        # and report identities, then recompute their real hashes for this isolated fixture.
        directory = self.evidence / identity
        key = (identity, result)
        if key not in self.prior_evidence:
            self._make_prior(directory, identity, result)
            self.prior_evidence[key] = dict(execution_id=identity, result=result,
                ledger_sha256=hashlib.sha256((directory / p8.LEDGER_FILENAME).read_bytes()).hexdigest(),
                report_sha256=validation._NO_FINAL_REPORT if result == "terminated" else
                    ledger.verify_ledger(directory / p8.LEDGER_FILENAME)[1].reports[0]["report_sha256"],
                evidence_directory=str(directory))
        fields = dict(self.prior_evidence[key])
        fields.update(updates)
        return fields

    def _make_prior(self, directory, identity, result):
        from patch8_test_fixtures import environment
        import patch8_report as report
        directory.mkdir(parents=True, exist_ok=True)
        if result == "terminated":
            path = directory / p8.LEDGER_FILENAME
            if path.exists():
                for child in directory.iterdir():
                    child.unlink()
            led = ledger.Ledger(path, identity)
            session = "p8s_20261007T000000000000Z_" + "d" * 32
            led.append("session_start", session, dict(session_kind="E2E", subject="V01", environment=environment(),
                       code_state=dict(git_commit=self.audit, git_clean=True), recording_inventory=[]))
            led.append("execution_failed", session, dict(reason_code="OPERATOR_TERMINATED_EXECUTION", detail=None))
            return
        source = self.bundles[result]
        events, _ = ledger.verify_ledger(source / p8.LEDGER_FILENAME)
        rebuilt = []
        for old in events[:-1]:
            event = dict(old, execution_id=identity, previous_event_sha256=rebuilt[-1]["event_sha256"] if rebuilt else None)
            if "code_state" in event:
                event["code_state"] = dict(git_commit=self.audit, git_clean=True)
            event["event_sha256"] = ledger.event_hash(event)
            rebuilt.append(event)
        prefix = b"".join(ledger.event_line(e) for e in rebuilt)
        reports = {kind: json.loads((source / name).read_bytes()) for kind, name in report.REPORT_FILES.items()}
        for value in reports.values():
            value["execution_id"] = identity
        reports["execution"]["ledger"] = dict(event_count=len(rebuilt), last_event_sha256=rebuilt[-1]["event_sha256"],
                                             sha256=hashlib.sha256(prefix).hexdigest())
        if result == "FAIL":
            reports["execution"]["code_identity"] = dict(git_commit=self.audit, git_clean=True)
            reports["execution"]["supporting_reports"] = {k: hashlib.sha256(report.report_bytes(reports[k])).hexdigest()
                                                          for k in ("metrics", "reconciliation")}
        for kind, name in report.REPORT_FILES.items():
            (directory / name).write_bytes(report.report_bytes(reports[kind]))
        event = dict(events[-1], execution_id=identity, previous_event_sha256=rebuilt[-1]["event_sha256"],
                     ledger_sha256_before=hashlib.sha256(prefix).hexdigest(),
                     report_sha256=hashlib.sha256((directory / report.REPORT_FILES["execution"]).read_bytes()).hexdigest())
        event["event_sha256"] = ledger.event_hash(event)
        (directory / p8.LEDGER_FILENAME).write_bytes(prefix + ledger.event_line(event))

    def rerun(self, *, previous=None, identity=SECOND, commit=None, changed="no", **updates):
        previous = previous if previous is not None else [self.disposition()]
        entry = self.auth(identity, commit, reason_for_reexecution="explicit synthetic rerun authorization",
                          implementation_changed=changed, **updates)
        return entry + "".join("### Prior execution\n" + fields_text(prior) for prior in previous)

    def history(self, result="FAIL", **rerun_options):
        prior = self.disposition(result=result)
        return self.auth() + "## Disposition\n" + fields_text(prior) + self.rerun(previous=[prior], **rerun_options)

    def register(self, text=None):
        parent = self.audit if self.git("ls-tree", "HEAD", "--", p8.EXECUTION_REGISTRY_PATH) else self.git("rev-parse", "HEAD")
        self.registry.write_text(self.auth() if text is None else text, encoding="utf-8", newline="\n")
        # Each malformed alternative is an independent synthetic registration, not a
        # mutation of an earlier authorization. History-specific tests use commit().
        self.git("add", ".")
        new = self.git("commit-tree", self.git("write-tree"), "-p", parent, input="independent registration fixture\n")
        self.git("update-ref", "HEAD", new)

    def gate(self, identity=FIRST, **kwargs):
        return validation.authorization_gate(self.rt, identity, **kwargs)

    def refuse(self, identity=FIRST, message=None):
        with self.assertRaisesRegex(validation.ExecutionNotAuthorized, message or "."):
            self.gate(identity)

    def test_single_authorization_and_documentation_descendant(self):
        self.register("# Patch 8 Execution Registry\n\n" + self.auth())
        registered_head = self.git("rev-parse", "HEAD")
        self.assertNotEqual(registered_head, self.audit)
        (self.root / "docs" / "note.md").write_text("documentation only", encoding="utf-8")
        self.commit()
        self.assertEqual(self.gate()["audited_implementation_commit"], self.audit)
        self.assertFalse((self.root / "validation").exists())

    def test_exact_selection_with_multiple_entries_and_no_local_history(self):
        self.register(self.history())
        self.assertFalse((self.root / "validation").exists())
        self.assertEqual(self.gate(SECOND)["audited_implementation_commit"], self.audit)
        self.refuse(FIRST, "terminal disposition")

    def test_explicit_reexecution_with_changed_audited_code(self):
        (self.root / "implementation.py").write_text("VALUE = 2\n", encoding="utf-8")
        changed = self.commit()
        self.register(self.history(commit=changed, changed="yes"))
        self.assertEqual(self.gate(SECOND)["audited_implementation_commit"], changed)

    def test_reexecution_with_document_only_audit_change(self):
        (self.root / "README.md").write_text("fixture documentation", encoding="utf-8")
        descendant = self.commit()
        self.register(self.history(commit=descendant))
        self.assertEqual(self.gate(SECOND)["audited_implementation_commit"], descendant)

    def test_missing_registry_and_missing_id(self):
        self.refuse(message="absent")
        self.register()
        self.refuse(SECOND, "not registered")

    def test_substring_id_never_authorizes(self):
        self.register()
        for identity in (FIRST[:-1], FIRST[1:], "", "../" + FIRST):
            with self.subTest(identity=identity):
                self.refuse(identity, "invalid requested")

    def test_id_in_description_is_not_an_authorization(self):
        self.register(self.auth(planned_date_session="reference only " + SECOND))
        self.refuse(SECOND, "not registered")

    def test_id_in_prior_only_and_orphan_prior_cannot_authorize(self):
        prior = self.disposition(SECOND)
        self.register(self.auth() + "### Prior execution\n" + fields_text(prior))
        self.refuse(SECOND)
        self.register(self.auth() + "## Disposition\n" + fields_text(prior))
        self.refuse(SECOND, "orphan")

    def test_other_entry_sha_does_not_authorize_nonexistent_commit(self):
        self.register(self.history(commit="f" * 40))
        self.refuse(SECOND, "Git authorization query failed")

    def test_nonancestor_commit_with_identical_tree_rejected(self):
        tree = self.git("rev-parse", self.audit + "^{tree}")
        unrelated = self.git("commit-tree", tree, input="unrelated fixture root\n")
        self.register(self.auth(commit=unrelated))
        self.refuse(message="merge-base")

    def test_tree_mismatch_cannot_use_other_entry_sha(self):
        self.register(self.history())
        (self.root / "implementation.py").write_text("VALUE = 2\n", encoding="utf-8")
        current_code = self.commit()
        # The old entry has a matching SHA, but SECOND pins a different tree.
        text = self.history().replace("audited_implementation_commit: " + self.audit,
                                      "audited_implementation_commit: " + current_code, 1)
        self.register(text)
        self.refuse(SECOND, "non-documentation tree")

    def test_many_unrelated_shas_never_substitute_for_pinned_commit(self):
        matching = self.git("rev-parse", "HEAD")
        self.register(self.auth(commit="f" * 40, planned_date_session=matching + " " + self.audit))
        self.refuse(message="Git authorization query failed")

    def test_blob_is_not_an_implementation_commit(self):
        blob = self.git("rev-parse", self.audit + ":implementation.py")
        self.register(self.auth(commit=blob))
        self.refuse(message="not a commit")

    def test_dirty_tracked_and_untracked_worktree_rejected(self):
        self.register()
        code = self.root / "implementation.py"
        original = code.read_bytes()
        code.write_bytes(original + b"# dirty\n")
        self.refuse(message="clean")
        code.write_bytes(original)
        (self.root / "untracked.py").write_text("# test", encoding="utf-8")
        self.refuse(message="clean")

    def test_ignored_untracked_registry_rejected(self):
        (self.root / ".gitignore").write_text("validation/\ndocs/\n", encoding="utf-8")
        self.commit()
        self.registry.write_text(self.auth(), encoding="utf-8")
        self.refuse(message="ls-files")

    def test_each_git_query_error_or_timeout_fails_closed(self):
        self.register()
        for command in ("rev-parse", "status", "ls-files", "ls-tree", "show", "rev-list", "cat-file", "merge-base", "diff"):
            for failure in ("returncode", "timeout", "oserror"):
                with self.subTest(command=command, failure=failure):
                    def run(args, **kwargs):
                        if args[:2] == ["git", command]:
                            if failure == "timeout":
                                raise subprocess.TimeoutExpired(args, 30)
                            if failure == "oserror":
                                raise OSError("synthetic Git query failure")
                            result = subprocess.CompletedProcess(args, 128, "", "synthetic failure")
                            if kwargs.get("check"):
                                raise subprocess.CalledProcessError(128, args)
                            return result
                        return subprocess.run(args, **kwargs)
                    self.rt.run = run
                    self.refuse()

    def test_authorization_status_is_exact_and_local_to_entry(self):
        for status in ("AUTHORIZED", "NOT_STARTED", "PENDING", "DEFERRED", "FAIL", "terminated",
                       "AUTHORIZED / STARTED", "NOT_AUTHORIZED / NOT_STARTED", "authorized / not_started"):
            with self.subTest(status=status):
                self.register(self.auth(status=status, planned_date_session="AUTHORIZED / NOT_STARTED"))
                self.refuse(message="status")

    def test_status_in_another_entry_cannot_authorize(self):
        self.register(self.history().replace("status: AUTHORIZED / NOT_STARTED", "status: DEFERRED", 1))
        self.refuse(SECOND, "status")

    def test_duplicate_authorization_and_fields_rejected(self):
        for text in (self.auth() + self.auth(), self.auth() + "status: AUTHORIZED / NOT_STARTED\n",
                     self.auth() + self.auth(status="FAIL")):
            with self.subTest(text=text):
                self.register(text)
                self.refuse(message="duplicate|status")

    def test_every_required_field_is_mandatory(self):
        for missing in self.auth_fields():
            with self.subTest(missing=missing):
                fields = self.auth_fields()
                del fields[missing]
                self.register("## Authorization\n" + fields_text(fields))
                self.refuse(message="fields")

    def test_malformed_ambiguous_and_legacy_formats_fail_closed(self):
        for text in ("", fields_text(self.auth_fields()), "```\n" + self.auth() + "```\n",
                     "\n".join("    " + line for line in self.auth().splitlines()),
                     self.auth() + "# hidden comment\n", self.auth() + "unexpected: value\n",
                     self.auth().replace("capture_host: fixture-host", "capture_host:"),
                     self.auth().replace("design_freeze_commit: " + validation.DESIGN_FREEZE_COMMIT, "design_freeze_commit: invalid"),
                     self.auth().replace("reserved_validation_subject: V01", "reserved_validation_subject: ../V01")):
            with self.subTest(text=text):
                self.register(text)
                self.refuse()

    def test_unreadable_or_invalid_utf8_registry_fails_closed(self):
        self.registry.write_bytes(b"\xff\xfe")
        self.commit()
        self.refuse(message="unreadable")
        with patch.object(Path, "read_bytes", side_effect=PermissionError("synthetic refusal")):
            self.refuse(message="unreadable")

    def test_all_known_terminal_results_forbid_reuse_in_fresh_workspace(self):
        for result in ("FAIL", "terminated", "PASS"):
            with self.subTest(result=result):
                self.register(self.history(result))
                self.refuse(FIRST, "terminal disposition")
                self.gate(SECOND)
                self.assertFalse((self.root / "validation").exists())

    def test_reexecution_requires_new_id_and_own_authorization(self):
        prior = self.disposition()
        self.register(self.auth() + "## Disposition\n" + fields_text(prior) + self.rerun(identity=FIRST))
        self.refuse(message="duplicate execution_id")
        self.register(self.auth() + "## Disposition\n" + fields_text(prior))
        self.refuse(SECOND, "not registered")

    def test_reexecution_requires_complete_consistent_prior_evidence(self):
        for field, value in (("execution_id", SECOND), ("result", "PASS"), ("ledger_sha256", "3" * 64),
                             ("report_sha256", "4" * 64), ("ledger_sha256", "invalid"),
                             ("report_sha256", validation._NO_FINAL_REPORT)):
            with self.subTest(field=field, value=value):
                prior = self.disposition(**{field: value})
                self.register(self.auth() + "## Disposition\n" + fields_text(self.disposition()) +
                              self.rerun(previous=[prior]))
                self.refuse(SECOND)
        for missing in self.disposition():
            with self.subTest(missing=missing):
                prior = self.disposition()
                del prior[missing]
                self.register(self.auth() + "## Disposition\n" + fields_text(self.disposition()) +
                              self.rerun(previous=[prior]))
                self.refuse(SECOND)

    def test_missing_reason_flag_or_prior_list_fails_closed(self):
        for text in (self.history().replace("reason_for_reexecution: explicit synthetic rerun authorization\n", ""),
                     self.history().replace("implementation_changed: no\n", ""),
                     self.history().replace("reason_for_reexecution: explicit synthetic rerun authorization", "reason_for_reexecution:"),
                     self.auth() + "## Disposition\n" + fields_text(self.disposition()) + self.rerun(previous=[])):
            with self.subTest(text=text):
                self.register(text)
                self.refuse(SECOND)

    def test_reexecution_without_prior_terminal_disposition_fails_closed(self):
        self.register(self.auth() + self.rerun())
        self.refuse(SECOND, "earlier terminal disposition")

    def test_duplicate_or_contradictory_dispositions_fail_closed(self):
        for second in (self.disposition(), self.disposition(result="PASS")):
            self.register(self.auth() + "## Disposition\n" + fields_text(self.disposition()) +
                          "## Disposition\n" + fields_text(second))
            self.refuse(message="duplicate disposition")

    def test_multiple_prior_executions_must_all_be_explicit(self):
        first, second = self.disposition(), self.disposition(SECOND, result="terminated")
        history = self.history() + "## Disposition\n" + fields_text(second)
        for priors in ([second], [first, first], [first, second]):
            with self.subTest(priors=priors):
                self.register(history + self.rerun(previous=priors, identity=THIRD))
                if priors == [first, second]:
                    self.gate(THIRD)
                else:
                    self.refuse(THIRD, "every prior execution")

    def test_implementation_changed_must_match_actual_trees(self):
        self.register(self.history(changed="yes"))
        self.refuse(SECOND, "contradicts")
        self.setUp()  # Independent alternative; never rewrite a registered history.
        (self.root / "implementation.py").write_text("VALUE = 3\n", encoding="utf-8")
        changed = self.commit()
        self.register(self.history(commit=changed, changed="no"))
        self.refuse(SECOND, "contradicts")

    def test_reexecution_git_comparison_errors_fail_closed(self):
        self.register(self.history())
        for failure in ("returncode", "timeout", "oserror"):
            with self.subTest(failure=failure):
                def run(args, **kwargs):
                    # The selected-to-HEAD comparison succeeds; the second diff checks
                    # the implementation_changed declaration against the prior audit.
                    if args[:3] == ["git", "diff", "--quiet"] and args[3:5] == [self.audit, self.audit]:
                        if failure == "timeout":
                            raise subprocess.TimeoutExpired(args, 30)
                        if failure == "oserror":
                            raise OSError("synthetic prior comparison failure")
                        return subprocess.CompletedProcess(args, 128, "", "synthetic failure")
                    return subprocess.run(args, **kwargs)
                self.rt.run = run
                self.refuse(SECOND, "comparison failed")

    def test_local_failed_execution_cannot_restart(self):
        # Actual hash-chain ledger replay, without any device use.
        from patch8_test_fixtures import environment
        self.register()
        session = "p8s_20261007T000000000000Z_" + "d" * 32
        led = validation.open_ledger(self.root, FIRST)
        led.append("session_start", session, dict(session_kind="E2E", subject="V01", environment=environment(),
                   code_state=validation.code_state(self.rt), recording_inventory=[]))
        self.gate()  # NOT_STARTED is an immutable registration snapshot, not live status.
        led.append("execution_failed", session, dict(reason_code="OPERATOR_TERMINATED_EXECUTION", detail=None))
        self.refuse(message="local execution failed")
        self.gate(finalization=True)
        self.assertEqual(ledger.verify_ledger(led.path)[1].execution_failure, "OPERATOR_TERMINATED_EXECUTION")

    def test_local_published_report_blocks_execution_and_finalization(self):
        from patch8_test_fixtures import environment
        self.register()
        session = "p8s_20261007T000000000000Z_" + "d" * 32
        led = validation.open_ledger(self.root, FIRST)
        led.append("session_start", session, dict(session_kind="E2E", subject="V01", environment=environment(),
                   code_state=validation.code_state(self.rt), recording_inventory=[]))
        led.append("report_published", session, dict(report_path="synthetic-report.json", report_sha256=HEX,
                                                     ledger_sha256_before=HEX))
        self.refuse(message="published result")
        with self.assertRaisesRegex(validation.ExecutionNotAuthorized, "published result"):
            self.gate(finalization=True)

    def test_corrupt_local_ledger_or_orphan_runtime_refused(self):
        self.register()
        directory = validation.execution_dir(self.root, FIRST)
        directory.mkdir(parents=True)
        (directory / "orphan.txt").write_text("synthetic runtime", encoding="utf-8")
        self.refuse(message="without a ledger")
        (directory / p8.LEDGER_FILENAME).write_text("broken\n", encoding="utf-8")
        self.refuse(message="invalid")

    def test_cli_refuses_wrong_subject_and_closed_hardware_commands(self):
        self.register()
        with patch.object(validation, "open_session") as launch:
            self.assertEqual(validation.main(["open-session", "--execution-id", FIRST, "--session-kind", "E2E",
                                              "--subject", "V02"], self.rt), 3)
            launch.assert_not_called()
        self.register(self.history())
        for command, extra in (("open-session", ["--session-kind", "E2E", "--subject", "V01"]),
                               ("attempt", ["--round", "131"]), ("warmup", [])):
            with self.subTest(command=command), patch.object(self.rt, "popen") as launch:
                self.assertEqual(validation.main([command, "--execution-id", FIRST, *extra], self.rt), 3)
                launch.assert_not_called()
        with patch.object(validation, "evaluate") as publish:
            self.assertEqual(validation.main(["evaluate", "--execution-id", FIRST, "--publish"], self.rt), 3)
            publish.assert_not_called()

    def test_lf_crlf_and_unicode_controls(self):
        self.register()
        self.git("config", "core.autocrlf", "true")
        original = self.registry.read_bytes()
        self.registry.write_bytes(original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.git("add", p8.EXECUTION_REGISTRY_PATH)  # Refresh Git's identical normalized blob/stat cache.
        self.gate()
        for char in ("\ufeff", "\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x00", "\t", "\r", "\u200b"):
            with self.subTest(char=repr(char)):
                self.register(self.auth(planned_date_session="synthetic" + char + "only"))
                self.refuse(message="control character/BOM/line separator")

    def test_hidden_registry_changes_are_refused(self):
        self.register()
        for flag in ("--skip-worktree", "--assume-unchanged"):
            with self.subTest(flag=flag):
                self.git("update-index", flag, p8.EXECUTION_REGISTRY_PATH)
                self.registry.write_text(self.auth(reserved_validation_subject="V02"), encoding="utf-8")
                self.assertEqual(self.git("status", "--porcelain"), "")
                self.refuse(message="HEAD blob")
                self.registry.write_text(self.auth(), encoding="utf-8")
                self.refuse(message="index flags")
                self.git("update-index", "--no-" + flag[2:], p8.EXECUTION_REGISTRY_PATH)

    def test_tracked_registry_symlink_mode_refused(self):
        self.register()
        blob = self.git("rev-parse", "HEAD:" + p8.EXECUTION_REGISTRY_PATH)
        self.git("update-index", "--cacheinfo", "120000," + blob + "," + p8.EXECUTION_REGISTRY_PATH)
        self.git("commit", "--quiet", "-m", "synthetic symlink mode")
        self.refuse(message="regular tracked blob|clean Git checkout")

    def test_append_only_history_modification_deletion_and_reregistration(self):
        self.register()
        self.registry.write_text(self.auth(capture_host="altered"), encoding="utf-8")
        self.commit()
        self.refuse(message="append-only")
        self.registry.unlink()
        self.commit()
        self.registry.write_text(self.auth(), encoding="utf-8")
        self.commit()
        self.refuse(message="append-only")

    def test_append_only_history_allows_new_authorization(self):
        self.register()
        self.registry.write_text(self.history(), encoding="utf-8")
        self.commit()
        self.gate(SECOND)
        self.refuse(FIRST, "terminal disposition")

    def test_design_freeze_identity_and_ancestry(self):
        for value in ("f" * 40, self.audit):
            self.register(self.auth(design_freeze_commit=value))
            self.refuse(message="CAP-005 freeze identity")
        unrelated = self.git("commit-tree", self.git("rev-parse", self.audit + "^{tree}"), input="unrelated root\n")
        self.register(self.auth(commit=unrelated))
        self.refuse(message="merge-base")

    def test_mixed_runtime_and_deleted_ledger_cannot_restart(self):
        self.register()
        for namespace in ("validation/patch8/" + SECOND, "data", "analysis", "results", "runtime/data"):
            with self.subTest(namespace=namespace):
                directory = self.root / namespace
                directory.mkdir(parents=True, exist_ok=True)
                artifact = directory / "prior-evidence.json"
                artifact.write_text("{}", encoding="utf-8")
                self.refuse(message="runtime artifacts")
                artifact.unlink()
        models = self.root / "models"
        models.mkdir()
        (models / "permitted-model-cache.task").write_bytes(b"synthetic model cache")
        # Model caches are independent of execution artifacts and are not banned.
        self.gate()

    def test_local_subject_mismatch_refused(self):
        from patch8_test_fixtures import environment
        self.register()
        session = "p8s_20261007T000000000000Z_" + "d" * 32
        validation.open_ledger(self.root, FIRST).append("session_start", session,
            dict(session_kind="E2E", subject="V02", environment=environment(),
                 code_state=validation.code_state(self.rt), recording_inventory=[]))
        self.refuse(message="ledger subject")

    def test_fail_disposition_matches_official_bundle_and_new_id(self):
        self.register(self.history())
        self.gate(SECOND)
        prior = self.disposition()
        execution, _ = validation.report.verify_published_bundle(prior["evidence_directory"])
        self.assertEqual(execution["computed_result"], "FAIL")
        self.assertFalse(validation.report.is_pass_result(execution))
        self.assertEqual(prior["report_sha256"], hashlib.sha256(
            (Path(prior["evidence_directory"]) / validation.report.REPORT_FILES["execution"]).read_bytes()).hexdigest())
        self.refuse(FIRST, "terminal disposition")

    def test_arbitrary_report_hash_or_result_cannot_be_disposition(self):
        for mutation in (dict(report_sha256="4" * 64), dict(result="PASS")):
            prior = dict(self.disposition(), **mutation)
            self.register(self.auth() + "## Disposition\n" + fields_text(prior) + self.rerun(previous=[prior]))
            self.refuse(SECOND, "evidence mismatch")
        prior = self.disposition()
        final = Path(prior["evidence_directory"]) / validation.report.REPORT_FILES["execution"]
        final.write_text("arbitrary text", encoding="utf-8")
        self.register(self.history())
        self.refuse(SECOND, "report SHA-256 mismatch")

    def test_unavailable_retained_evidence_refused(self):
        self.register(self.history())
        shutil.rmtree(self.evidence)
        self.refuse(SECOND, "prior evidence mismatch")


class RuntimeLocationTests(unittest.TestCase):
    def setUp(self):
        fixture = RegistryAuthorizationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        for name in ("patch8_validation", "patch8_protocol", "patch8_ledger", "patch8_prelock", "patch8_report", "patch8_metrics"):
            shutil.copyfile(validation.ROOT / (name + ".py"), fixture.root / (name + ".py"))
        fixture.audit = fixture.commit()
        fixture.register()

    def run_gate(self, root, injected=False):
        script = "from pathlib import Path; import sys; import patch8_validation as v; "
        script += ("r=v.Runtime(root=Path(sys.argv[1]),run=lambda *a,**kw: None); " if injected else
                   "r=v.Runtime(root=Path(sys.argv[1])); ")
        script += "v.authorization_gate(r,sys.argv[2]); print('AUTHORIZED')"
        return subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", script, str(root), FIRST],
                              cwd=self.fixture.root, capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_same_runtime_repository_and_windows_normalization(self):
        root = self.fixture.root
        variants = [root, root / "docs" / ".."]
        if sys.platform == "win32":
            variants.append(Path(str(root).upper()))
        for path in variants:
            with self.subTest(path=path):
                result = self.run_gate(path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("AUTHORIZED", result.stdout)

    def test_external_modified_runtime_root_refused_before_provenance(self):
        with tempfile.TemporaryDirectory(prefix="patch8-other-root-") as other:
            result = self.run_gate(other)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("runtime code repository differs", result.stderr)
            self.assertFalse((Path(other) / "validation").exists())
        # Real CLI reproduces B/code --root A with an approved clean repository A.
        with tempfile.TemporaryDirectory(prefix="patch8-code-B-") as other:
            for path in self.fixture.root.glob("patch8_*.py"):
                shutil.copyfile(path, Path(other) / path.name)
            with (Path(other) / "patch8_validation.py").open("a") as stream:
                stream.write("\n# external modified code fixture\n")
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(Path(other) / "patch8_validation.py"),
                "--root", str(self.fixture.root), "attempt", "--execution-id", FIRST, "--round", "131"],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 3)
            self.assertIn("runtime code repository differs", result.stderr)
            self.assertFalse((self.fixture.root / "validation").exists())

    def test_injected_runner_cannot_bypass_location_gate(self):
        with tempfile.TemporaryDirectory(prefix="patch8-injection-root-") as other:
            result = self.run_gate(other, injected=True)
            self.assertIn("runtime code repository differs", result.stderr)
            self.assertNotIn("AttributeError", result.stderr)

    def test_junction_or_symlink_alias_is_same_repository(self):
        import os
        alias = self.fixture.root.parent / (self.fixture.root.name + "-alias")
        if sys.platform == "win32":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(self.fixture.root)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            alias.symlink_to(self.fixture.root, target_is_directory=True)
        self.addCleanup(lambda: os.rmdir(alias) if sys.platform == "win32" else alias.unlink())
        result = self.run_gate(alias)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
