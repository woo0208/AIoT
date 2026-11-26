"""Full fixed-settings six-person synthetic rehearsal, never participant data."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import formal6_evaluation as ev
import formal6_synthetic as syn
from rf_experiment import file_identity


class SyntheticPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.result = syn.run_synthetic_pipeline(Path(cls.tmp.name) / "SYNTHETIC_ONLY")
        cls.path = Path(cls.result["freeze_path"])
        cls.sha = cls.result["freeze_sha256"]
        cls.freeze = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_development_eight_combinations_freeze_then_four_person_inference(self):
        result = self.result
        self.assertEqual(result["kind"], syn.KIND)
        self.assertFalse(result["formal_model_frozen"])
        self.assertFalse(result["research_performance_result"])
        development, heldout = result["development"], result["heldout"]
        self.assertEqual(development["settings"]["rf_trees"], 500)
        self.assertEqual(development["settings"]["rf_seeds"], (0, 1, 2))
        self.assertEqual(len(development["baseline_comparison"]["models"]), 8)
        self.assertEqual(len(development["selection"]["ranking"]), 5)
        self.assertEqual(development["selection"]["recommendation"], self.freeze["candidate"])
        self.assertEqual(len(development["aligned"]["sample_keys"]), 12)
        self.assertEqual(len(heldout["aligned"]["sample_keys"]), 24)
        self.assertEqual(heldout["aligned"]["sample_keys"], heldout["comparison_alignment"]["sample_keys"])
        self.assertFalse(set(development["aligned"]["sample_keys"]) & set(heldout["aligned"]["sample_keys"]))
        self.assertTrue(all(k[2] != 1 for k in development["aligned"]["sample_keys"] + heldout["aligned"]["sample_keys"]))
        self.assertTrue(any(k[2] == 2 for k in heldout["aligned"]["sample_keys"]))  # Separate evaluation P0.
        self.assertTrue(all(k[1].endswith("_S1") for k in heldout["reference_keys"].values()))
        self.assertTrue(any(k[1].endswith("_S2") for k in heldout["aligned"]["sample_keys"]))
        self.assertEqual(set(heldout["participants"]), set(syn.HELDOUT))
        self.assertEqual(heldout["pooled"]["status"], "COMPLETE")
        for metrics in heldout["pooled"]["per_seed"]:
            self.assertEqual(metrics["sample_count"], 24)
            self.assertEqual([p["support"] for p in metrics["per_class"]], [4]*6)
            self.assertIsNotNone(metrics["macro_f1"])
            self.assertIsNotNone(metrics["accuracy"])
        for audit in self.freeze["fit_audits"]:
            self.assertEqual(audit["train_subjects"], list(syn.DEVELOPMENT))
            self.assertEqual(audit["n_train"], 12)
            self.assertTrue(all(key[2] != 1 for key in audit["train_keys"]))
            if audit["scaler_n_samples_seen"] is not None:
                self.assertEqual(audit["scaler_n_samples_seen"], 12)
        events = result["events"]
        self.assertLess(events.index("synthetic_freeze_written"), events.index("heldout_fixture_generated_after_freeze"))
        self.assertLess(events.index("freeze_verified_before_heldout_access"), events.index("heldout_fixture_generated_after_freeze"))
        self.assertEqual(self.freeze["freeze_scope"], "SYNTHETIC_TEST_ONLY")

    def test_heldout_inference_cannot_fit_scaler_model_or_reselect(self):
        ref = ev._reference()
        before = file_identity(self.path)["sha256"]
        with patch.object(ev.rf.Forest, "fit", side_effect=AssertionError("heldout RF fit")), \
             patch.object(ref.StandardScaler, "fit", side_effect=AssertionError("heldout scaler fit")), \
             patch.object(ref.LogisticRegression, "fit", side_effect=AssertionError("heldout LR fit")), \
             patch.object(ev, "rank_candidates", side_effect=AssertionError("heldout reselection")):
            result = syn.infer_synthetic_frozen(self.path, freeze_sha256=self.sha, fixture=syn.SyntheticFixture())
        self.assertEqual(result["heldout_fit_count"], 0)
        self.assertEqual(result["heldout_scaler_fit_count"], 0)
        self.assertEqual(result["heldout_selection_count"], 0)
        self.assertEqual(result["candidate"], self.freeze["candidate"])
        self.assertEqual(file_identity(self.path)["sha256"], before)

    def test_missing_class_is_incomplete_not_an_official_macro_score(self):
        with patch.object(ev.rf.Forest, "fit", side_effect=AssertionError("no refit")):
            result = syn.infer_synthetic_frozen(self.path, freeze_sha256=self.sha,
                                              fixture=syn.SyntheticFixture(missing_heldout_class=5))
        self.assertEqual(len(result["aligned"]["sample_keys"]), 20)
        self.assertEqual(result["pooled"]["status"], "INCOMPLETE")
        self.assertIsNone(result["pooled"]["mean_macro_f1"])
        self.assertEqual(set(result["participants"]), set(syn.HELDOUT))
        for metrics in result["pooled"]["per_seed"]:
            self.assertIsNone(metrics["macro_f1"])
            self.assertEqual(len(metrics["per_class"]), 6)
            self.assertIsNone(metrics["per_class"][5]["recall"])
            self.assertIsNotNone(metrics["diagnostic_macro_f1_zero_division_0"])

    def test_early_access_and_freeze_mismatches_are_blocked_before_payload_access(self):
        fixture = syn.SyntheticFixture()
        with self.assertRaises(ValueError):
            fixture.heldout(syn.HELDOUT)
        with self.assertRaises(ValueError):
            syn.infer_synthetic_frozen(self.path, freeze_sha256="0"*64, fixture=fixture)
        variants = []
        draft = copy.deepcopy(self.freeze)
        draft["status"] = "DRAFT"
        variants.append(draft)
        code = copy.deepcopy(self.freeze)
        code["code_hashes"][next(iter(code["code_hashes"]))] = "0"*64
        variants.append(code)
        model = copy.deepcopy(self.freeze)
        model["model_artifacts"][0]["sha256"] = "0"*64
        variants.append(model)
        settings = copy.deepcopy(self.freeze)
        settings["settings"]["preprocessing"] = "heldout-fit-forbidden"
        variants.append(settings)
        for i, value in enumerate(variants):
            path = self.path.parent / f"SYNTHETIC_ONLY_invalid_freeze_{i}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(i=i), self.assertRaises(ValueError):
                syn.infer_synthetic_frozen(path, freeze_sha256=file_identity(path)["sha256"], fixture=fixture)
        self.assertFalse(fixture.events)


if __name__ == "__main__":
    unittest.main()
