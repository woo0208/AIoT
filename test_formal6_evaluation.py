"""Small synthetic structural checks only; no research data or final artifact."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np

import formal6_evaluation as ev
from rf_experiment import file_identity


SUBJECTS = ("SYN-D1", "SYN-D2")
REFS = {s: ("ar_" + s, "r_" + s, 0) for s in SUBJECTS}


def fixture():
    families = {n: [] for n in ev.FEATURES}
    for person, subject in enumerate(SUBJECTS):
        # Reference plus one non-reference sample of every class.
        for step, k in enumerate((0, 0, 1, 2, 3, 4, 5)):
            key = ("ar_" + subject, "r_" + subject, step)
            for name, columns in ev.FEATURES.items():
                values = tuple(person * 100 + k * 2 + j / 10 for j in range(len(columns)))
                families[name].append(ev.Row(key, subject, ev.h6.LAB6[k], "S1" if step < 4 else "S2",
                    ("synthetic_seconds", step * 20, step * 20 + 10), values, True, "confirmed",
                    support=tuple(range(30)) if name == "H9" else tuple(range(10, 40))))
    return {k: tuple(reversed(v)) for k, v in families.items()}


class FormalEvaluationTests(unittest.TestCase):
    def test_dimensions_common_keys_reference_exclusion_and_supports(self):
        aligned = ev.align_development(fixture(), SUBJECTS, REFS, feature_sets=tuple(ev.FEATURES))
        self.assertEqual(len(aligned["sample_keys"]), 12)
        for name, width in (("F0", 6), ("F_cal", 6), ("H5", 5), ("H9-F9", 8), ("H9", 9)):
            self.assertEqual(aligned["X"][name].shape, (12, width))
        self.assertEqual(aligned["sample_keys"], tuple(sorted(aligned["sample_keys"])))
        self.assertFalse(set(REFS.values()) & set(aligned["sample_keys"]))
        self.assertEqual(len(aligned["audit"]), 14)
        row = next(r for r in aligned["audit"] if r["eligible"])
        self.assertNotEqual(row["families"]["H9"]["support"], row["families"]["H9-F9"]["support"])

    def test_technical_missing_labels_and_conflicting_identity(self):
        families = fixture()
        rows = list(families["H9-F9"])
        target = next(i for i, r in enumerate(rows) if r.sample_key[2] == 6)
        rows[target] = replace(rows[target], values=(None,) * 8, review="ambiguous")
        families["H9-F9"] = tuple(rows)
        aligned = ev.align_development(families, SUBJECTS, REFS, feature_sets=("H9", "H9-F9"))
        audit = next(r for r in aligned["audit"] if r["sample_key"] == rows[target].sample_key)
        self.assertFalse(audit["eligible"])
        self.assertIn("H9-F9:label_ambiguous", audit["reasons"])
        self.assertTrue(all(audit["families"]["H9-F9"]["missing_mask"]))
        rows[target] = replace(rows[target], label="lean_back")
        families["H9-F9"] = tuple(rows)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            ev.align_development(families, SUBJECTS, REFS, feature_sets=("H9", "H9-F9"))

    def test_existing_adapter_and_h_sample_bridges(self):
        from test_f0_fcal_evaluation import item, prepare
        items = [item(subject=s) for s in SUBJECTS] + [item(1, subject=s, label="body_forward") for s in SUBJECTS]
        f0_samples = prepare(items)
        reviews = {s.sample_key: "confirmed" for s in f0_samples}
        converted = ev.rows_from_f0(f0_samples, items, reviews, SUBJECTS)
        self.assertEqual(len(converted["F0"][0].values), 6)
        self.assertEqual(converted["F0"][-1].label, "lean_forward")
        key = ("ar_h", "r_h", "1")
        new_key = ("ar_h", "r_h", 1)
        sample = NS(sample_key=key, subject=SUBJECTS[0], label="body_forward",
                    features={n: i for i, n in enumerate(ev.H9_FEATURE_NAMES)}, eligible=True,
                    eligibility_reasons=(), common_valid_frame_indices=tuple(range(30)))
        converted_h = ev.rows_from_h([sample], {new_key: (("clock", 0, 10), "S1")},
                                    {new_key: "confirmed"}, SUBJECTS, key_map={key: new_key})
        self.assertEqual(converted_h["H9-F9"][0].sample_key, new_key)
        self.assertEqual(len(converted_h["H5"][0].values), 5)
        self.assertEqual(converted_h["H9-F9"][0].values, tuple(range(8)))

    def test_small_synthetic_loso_fixed_combinations_and_train_only_scaler(self):
        with patch.object(ev, "TREE_COUNT", 2), patch.object(ev.rf, "fit_models", wraps=ev.rf.fit_models) as fit:
            report = ev.evaluate_development(fixture(), SUBJECTS, REFS)
        self.assertEqual(report["status"], "DEVELOPMENT_COMPLETE")
        self.assertEqual(set(report["candidates"]), {c[0] for c in ev.CANDIDATES})
        self.assertEqual(fit.call_count, 6)
        self.assertEqual({call.args[4] for call in fit.call_args_list}, {0, 1, 2})
        self.assertTrue(all(call.args[0].shape == (6, 9) and call.args[5] == [0.5] for call in fit.call_args_list))
        aligned = report["aligned"]
        for fold in report["folds"]:
            if fold["model"] == "LR_B0":
                train = aligned["participants"] != fold["heldout"]
                self.assertEqual(fold["scaler_n_samples_seen"], 6)
                np.testing.assert_allclose(fold["scaler_mean"], aligned["X"]["H9-F9"][train].mean(0))
            else:
                self.assertFalse(set(fold["train_keys"]) & set(fold["test_keys"]))
                self.assertFalse(set(REFS.values()) & (set(fold["train_keys"]) | set(fold["test_keys"])))
        self.assertEqual(len(report["candidates"]["LR_B0_H9-F9"]["predictions"]), 1)
        self.assertTrue(report["settings"]["structural_test_settings"])
        self.assertTrue(all(s == "COMPARISON_COMPLETE" for s in report["baseline_model_status"].values()))
        self.assertTrue(report["baseline_comparison"]["candidate_scope_reused"])

    def test_missing_class_blocks_before_any_fit(self):
        families = {n: tuple(r for r in rows if not (r.subject == SUBJECTS[0] and r.label == "lean_forward"))
                    for n, rows in fixture().items()}
        with patch.object(ev.rf, "fit_models") as fit, patch.object(ev.rf.Forest, "fit") as forest_fit:
            report = ev.evaluate_development(families, SUBJECTS, REFS)
        fit.assert_not_called()
        forest_fit.assert_not_called()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIsNone(report["selection"]["recommendation"])
        self.assertEqual(set(report["support_by_participant"]), set(SUBJECTS))
        self.assertEqual(report["support_by_participant"][SUBJECTS[0]][5], 0)

    def test_non_development_data_blocked_before_values(self):
        class SealedHeldout:
            subject = "SYN-H1"
            @property
            def values(self):
                self.fail("held-out values accessed")
        families = fixture()
        families["F0"] = (SealedHeldout(),)
        for evaluate in (ev.evaluate_development, ev.evaluate_baseline_comparison):
            with patch.object(ev.rf, "fit_models") as fit, self.assertRaisesRegex(ValueError, "before feature access"):
                evaluate(families, SUBJECTS, REFS)
            fit.assert_not_called()

    def test_registered_baselines_reuse_f0_bridge_and_execute_without_padding(self):
        from test_f0_fcal_evaluation import item, prepare
        items = []
        for subject in SUBJECTS:
            items.append(item(subject=subject, n=30, valid=30))
            items.extend(item(i, subject=subject, label=label, n=30, valid=30)
                         for i, label in enumerate(ev.h6.LAB6, 1))
        samples = prepare(items)
        refs = {s.subject: s.sample_key for s in samples if s.is_reference}
        reviews = {s.sample_key: "confirmed" for s in samples}
        families = ev.rows_from_f0(samples, items, reviews, SUBJECTS)
        h_samples = [NS(sample_key=s.sample_key, subject=s.subject, label=s.label,
                        features={name: s.class_index * 2 + j/10 for j, name in enumerate(ev.H9_FEATURE_NAMES)},
                        eligible=True, eligibility_reasons=(), common_valid_frame_indices=tuple(range(30)))
                     for s in samples]
        windows = {s.sample_key: (("synthetic_seconds", 10, 20), "S1") for s in samples}
        families.update(ev.rows_from_h(h_samples, windows, reviews, SUBJECTS))
        dimensions = []
        original_fit = ev.rf.Forest.fit
        def record_fit(model, X, y):
            dimensions.append(X.shape[1])
            return original_fit(model, X, y)
        with patch.object(ev, "TREE_COUNT", 2), patch.object(ev.rf.Forest, "fit", autospec=True, side_effect=record_fit):
            comparison = ev.evaluate_baseline_comparison(families, SUBJECTS, refs)
        self.assertEqual(comparison["status"], "COMPARISON_COMPLETE")
        self.assertIsNone(comparison["selection"])
        self.assertEqual(set(comparison["models"]), {c[0] for c in ev.CANDIDATES + ev.BASELINES})
        self.assertEqual(set(dimensions), {5, 6, 8, 9})
        self.assertEqual(len(comparison["sample_keys"]), 12)
        self.assertFalse(set(refs.values()) & set(comparison["sample_keys"]))
        for name, feature, model in ev.BASELINES:
            self.assertEqual(model, "M0")
            self.assertEqual(comparison["aligned"]["X"][feature].shape[1], 5 if feature == "H5" else 6)
            self.assertEqual(len(comparison["models"][name]["predictions"]), 3)
            self.assertTrue(all(len(p) == 12 for p in comparison["models"][name]["predictions"]))

    def test_comparison_uses_common_rows_without_changing_candidate_selection_scope(self):
        families = fixture()
        for name, rows in families.items():
            original = next(r for r in rows if r.subject == SUBJECTS[0] and r.sample_key[2] == 1)
            extra = replace(original, sample_key=(*original.sample_key[:2], 7),
                            window=("synthetic_seconds", 200, 210),
                            review="ambiguous" if name == "H5" else "confirmed")
            families[name] = rows + (extra,)
        with patch.object(ev, "TREE_COUNT", 2):
            result = ev.evaluate_development(families, SUBJECTS, REFS)
        comparison = result["baseline_comparison"]
        self.assertEqual(len(result["aligned"]["sample_keys"]), 13)
        self.assertEqual(len(comparison["sample_keys"]), 12)
        self.assertFalse(comparison["candidate_scope_reused"])
        self.assertEqual(comparison["status"], "COMPARISON_COMPLETE")
        self.assertEqual(set(result["selection"]["ranking"]), {c[0] for c in ev.CANDIDATES})
        self.assertFalse(set(comparison["baseline_ids"]) & set(result["selection"]["ranking"]))
        self.assertTrue(all(len(p) == 12 for m in comparison["models"].values() for p in m["predictions"]))

    def test_calibration_failure_blocks_comparison_but_not_h_candidate_evaluation(self):
        families = fixture()
        for name in ("F0", "F_cal"):
            families[name] = tuple(replace(r, eligible=False, reasons=("participant_calibration_failed",))
                                   if r.subject == SUBJECTS[0] else r for r in families[name])
        with patch.object(ev, "TREE_COUNT", 2):
            result = ev.evaluate_development(families, SUBJECTS, REFS)
        self.assertEqual(result["status"], "DEVELOPMENT_COMPLETE")
        self.assertEqual(len(result["candidates"]), 5)
        self.assertEqual(result["baseline_comparison"]["status"], "BLOCKED")
        self.assertEqual(result["baseline_comparison"]["evaluation_status"], "INCOMPLETE")
        self.assertFalse(result["baseline_comparison"]["models"])
        self.assertEqual(result["baseline_comparison"]["support_by_participant"][SUBJECTS[0]], [0]*6)
        self.assertIn("required_classes_missing:" + SUBJECTS[0], result["baseline_comparison"]["reasons"])

    def test_metrics_incomplete_and_tie_priority(self):
        metrics = ev.metrics6(np.array([0, 1]), np.array([0, 0]))
        self.assertEqual(metrics["status"], "INCOMPLETE")
        self.assertIsNone(metrics["macro_f1"])
        self.assertIsNone(metrics["per_class"][5]["recall"])
        self.assertEqual(len(metrics["per_class"]), 6)
        self.assertIsNotNone(metrics["diagnostic_macro_f1_zero_division_0"])
        empty = ev.metrics6(np.array([], dtype=int), np.array([], dtype=int))
        self.assertIsNone(empty["accuracy"])
        self.assertIsNone(empty["macro_f1"])
        with self.assertRaises(ValueError):
            ev.metrics6([0.5], [0])
        scores = {name: dict(status="COMPLETE", mean_macro_f1=0.5, mean_accuracy=0.5, mean_recall=(0.5,)*6)
                  for name, _, _ in ev.CANDIDATES}
        self.assertEqual(ev.rank_candidates(scores)["recommendation"], "RF_M0_H9-F9")  # fewer features, fixed order
        scores["RF_M0_H9"]["mean_macro_f1"] += 0.5e-12
        scores["RF_M0_H9"]["mean_recall"] = (0.6,) + (0.5,)*5
        self.assertEqual(ev.rank_candidates(scores)["recommendation"], "RF_M0_H9")
        scores["LR_B0_H9-F9"]["mean_macro_f1"] += 3e-12
        self.assertEqual(ev.rank_candidates(scores)["recommendation"], "LR_B0_H9-F9")
        scores["LR_B0_H9-F9"]["status"] = "INCOMPLETE"
        self.assertEqual(ev.rank_candidates(scores)["status"], "BLOCKED")

    def test_freeze_gate_never_calls_loader_until_hashes_settings_and_models_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, artifact = root / "freeze.json", root / "synthetic-model.bin"
            artifact.write_bytes(b"synthetic test bytes; not a classifier or final model")
            candidate = "LR_B0_H9-F9"
            manifest = dict(status="DRAFT", candidate=candidate, class_order=list(ev.h6.LAB6),
                settings=ev.frozen_settings(candidate), code_hashes=ev.code_hashes(),
                development_subjects=list(SUBJECTS), heldout_subjects=[f"SYN-H{i}" for i in range(4)],
                model_artifacts=[dict(seed=0, path=artifact.name, sha256=file_identity(artifact)["sha256"])])
            loader = Mock(return_value="synthetic sealed payload")
            def save():
                path.write_text(json.dumps(manifest), encoding="utf-8")
                return file_identity(path)["sha256"]
            with self.assertRaises(ValueError):
                ev.load_frozen_heldout(path, freeze_sha256=save(), loader=loader)
            loader.assert_not_called()
            manifest["status"] = "FROZEN"
            manifest["settings"]["preprocessing"] = "heldout-fit"
            with self.assertRaises(ValueError):
                ev.load_frozen_heldout(path, freeze_sha256=save(), loader=loader)
            loader.assert_not_called()
            manifest["settings"] = ev.frozen_settings(candidate)
            self.assertEqual(ev.load_frozen_heldout(path, freeze_sha256=save(), loader=loader), "synthetic sealed payload")
            loader.assert_called_once_with(tuple(manifest["heldout_subjects"]))
            loader.reset_mock()
            artifact.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                ev.load_frozen_heldout(path, freeze_sha256=file_identity(path)["sha256"], loader=loader)
            loader.assert_not_called()

    def test_original_eight_column_synthetic_validation_path_unchanged(self):
        path = Path(ev.__file__).parent / "analysis/formal6_evaluator_20261030_93bd72/run.py"
        before = file_identity(path)["sha256"]
        previous = list(sys.path)
        try:
            spec = importlib.util.spec_from_file_location("formal8_preservation_check", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            data = module.synthetic_fixture()
            self.assertEqual(len(data["feature_order"]), 8)
            module.validate(data)  # no evaluate/fit
            data["feature_order"] = data["feature_order"][:6]
            with self.assertRaises(ValueError):
                module.validate(data)
        finally:
            sys.path[:] = previous
        self.assertEqual(file_identity(path)["sha256"], before)


if __name__ == "__main__":
    unittest.main()
