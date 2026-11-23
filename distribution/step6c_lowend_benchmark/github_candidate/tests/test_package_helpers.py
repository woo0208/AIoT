"""Structural regression checks for the portable entrypoints."""
import csv
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark import PACKAGE, checked_path, private_output
from score_replay import baseline_predictions


class PathGuards(unittest.TestCase):
    def test_relative_file_and_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "one.txt"
            local.touch()
            self.assertEqual(checked_path(root, "one.txt"), local.resolve())
            for bad in ("../one.txt", str(local.resolve())):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    checked_path(root, bad)

    def test_output_is_private(self):
        with self.assertRaises(ValueError):
            private_output(PACKAGE / "results")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(private_output(Path(tmp)), Path(tmp).resolve())

    def test_incomplete_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "ref.csv"
            with file.open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(("method", "repeat", "window_id"))
            with self.assertRaises(ValueError):
                baseline_predictions(file, [{"id": "test"}])


if __name__ == "__main__":
    unittest.main()
