"""Focused read-only tests for the F0 paper asset renderer."""

import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

import render_f0_paper_assets as render


RUN_ID = "er_20261015T031706845312Z_7f5dd19f54414813ab4c3d7c25e5a08e"
RUN_DIR = Path(__file__).resolve().parent / "results" / RUN_ID


def hashes(directory):
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in render.REQUIRED_FILES}


class F0PaperAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = render.analyze(RUN_DIR)

    def test_run_scope_counts_hashes_and_prediction_uniqueness(self):
        analysis = self.analysis
        self.assertEqual(analysis["manifest"]["status"], "completed")
        self.assertEqual(analysis["manifest"]["experiment_run_id"], RUN_ID)
        self.assertEqual(len(analysis["lineage"]), 100)
        self.assertEqual(len(analysis["subjects"]), 20)
        self.assertEqual(len(analysis["predictions"]), 1200)
        self.assertEqual(len({(row["sample_index"], row["seed"], row["model"])
                              for row in analysis["predictions"]}), 1200)
        self.assertEqual(analysis["supports"], {0: 20, 1: 20, 2: 20, 3: 20, 4: 20})
        self.assertTrue(analysis["predictions_identical"])
        for name, identity in analysis["identities"].items():
            self.assertEqual(identity["sha256"], hashlib.sha256((RUN_DIR / name).read_bytes()).hexdigest())

    def test_metrics_are_independently_recalculated_per_seed(self):
        for model in render.ordered_models(self.analysis):
            metric = self.analysis["metrics"][model]
            self.assertEqual(metric["per_seed_accuracy"], [0.96, 0.96, 0.96])
            self.assertEqual(metric["per_seed_macro_f1"], [render.REFERENCE_MACRO_F1] * 3)
            self.assertEqual(metric["accuracy_sd"], 0.0)
            self.assertEqual(metric["macro_f1_sd"], 0.0)

    def test_confusion_orientation_and_per_class_metrics_use_unique_samples(self):
        rows = [row for row in self.analysis["predictions"] if row["model"] == "M0" and row["seed"] == 0]
        expected = render.confusion_from_predictions(rows)
        archived = self.analysis["confusions"][("M0", 0)]
        self.assertEqual(archived, expected)
        self.assertEqual(sum(map(sum, archived)), 100)
        self.assertEqual([sum(row) for row in archived], [20] * 5)  # true-label rows
        self.assertEqual(sum(archived[i][i] for i in range(5)), 96)
        metrics = render.per_class_metrics(rows)
        self.assertEqual([row["support"] for row in metrics], [20] * 5)
        self.assertEqual(sum(row["support"] for row in metrics), 100)

    def test_root_denominators_are_actual_splitting_roots(self):
        for model in render.ordered_models(self.analysis):
            roots = self.analysis["roots"][model]
            self.assertEqual(roots["total_trees"], 20 * 3 * 500)
            self.assertEqual(roots["split_roots"], sum(roots["counts"].values()))
            self.assertEqual(roots["split_roots"], 30000)
            self.assertEqual(roots["leaf_only_trees"], 0)
            self.assertAlmostEqual(sum(roots["percentages"].values()), 100.0)
        self.assertEqual(self.analysis["roots"]["M0"]["counts"],
                         self.analysis["roots"]["M1"]["counts"])
        self.assertNotEqual(self.analysis["roots"]["M0"]["counts"],
                            self.analysis["roots"]["M2(λ=0.5)"]["counts"])


class F0PaperRenderingTests(unittest.TestCase):
    def test_renderer_outputs_assets_without_mutating_sources_or_pooling_seeds(self):
        try:
            import matplotlib.image as mpimg
        except ImportError as error:
            self.skipTest(f"Matplotlib unavailable: {error}")
        before = hashes(RUN_DIR)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / RUN_ID
            analysis = render.render_all(RUN_DIR, output)
            expected = {
                "table_1_settings.md", "table_2_performance.csv", "table_3_per_class.csv",
                "figure_1_confusion_matrix.png", "figure_1_confusion_matrix.svg",
                "figure_2_root_feature_distribution.png", "figure_2_root_feature_distribution.svg",
                "F0_preliminary_results.md",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected)
            for name in ("figure_1_confusion_matrix.png", "figure_2_root_feature_distribution.png"):
                image = mpimg.imread(output / name)
                self.assertGreater(image.shape[0], 1200)
                self.assertGreater(image.shape[1], 1600)
            with (output / "table_3_per_class.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 4 * 5)
            self.assertEqual({row["seed"] for row in rows}, {"0"})
            self.assertEqual({row["aggregation_method"] for row in rows},
                             {"single recorded seed; no seed pooling"})
            for model in {row["model"] for row in rows}:
                self.assertEqual(sum(int(row["support"]) for row in rows if row["model"] == model), 100)
            self.assertEqual(len(analysis["predictions"]), 1200)
        self.assertEqual(hashes(RUN_DIR), before)


if __name__ == "__main__":
    unittest.main()
