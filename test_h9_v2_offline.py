"""Synthetic labelled CSV input tests only: no capture, training or evaluation."""

import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import f1_sample_aggregator as legacy
import h6_offline as h6
import h9_v2 as v2


FIELDS = ("artifact_kind", *h6.PROBE_IDENTITY_FIELDS,
          *legacy.H9_FEATURE_NAMES, v2.H9_V2_C3_FEATURE)


def row(segment="1", label="upright", index=1):
    values = dict.fromkeys(legacy.H9_FEATURE_NAMES, float(index))
    values[legacy.H_FACE_AXIS_FEATURE] = 10.0
    values[v2.H9_V2_C3_FEATURE] = -20.0
    return dict(values, artifact_kind=h6.EXPLORATORY_ARTIFACT_KIND,
                subject="synthetic-subject", recording_id="synthetic-recording",
                segment_id=segment, label=label)


class H9V2OfflineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(h6, "evaluate_samples", side_effect=AssertionError("no evaluation")))
        self.enterContext(patch.object(h6.rf, "fit_models", side_effect=AssertionError("no training")))

    def write_csv(self, rows, *, fields=FIELDS, name="synthetic.csv"):
        path = self.root / name
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_v2_only_columns_segments_labels_and_original_frame_indices(self):
        rows = [row("0", "PREP"), row("0", "TRANSITION")]
        # Non-posture feature cells are not parsed or included in coverage.
        rows[0][v2.H9_V2_C3_FEATURE] = "not-a-number"
        rows += [row("1", index=i) for i in range(1, 31)]
        rows += [row("3", "body_forward", i) for i in range(1, 31)]
        fields = tuple(name for name in FIELDS if name != legacy.H9_FEATURE_NAMES[-1])
        path = self.write_csv(rows, fields=fields)
        before = path.read_bytes()
        samples = h6.load_labeled_probe_h9_v2_samples([path])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(samples), 2)
        for sample, segment, label, indices in zip(
            samples, ("1", "3"), ("upright", "lean_forward"),
            (tuple(range(3, 33)), tuple(range(33, 63))),
        ):
            self.assertIsInstance(sample, v2.H9V2SampleResult)
            self.assertNotIsInstance(sample, legacy.HSampleResult)
            self.assertEqual(sample.sample_key,
                             ("probe-csv:synthetic-recording", "synthetic-recording", segment))
            self.assertEqual((sample.subject, sample.round, sample.label),
                             ("synthetic-subject", None, label))
            self.assertEqual(sample.input_frame_indices, indices)
            self.assertEqual(sample.common_valid_frame_indices, indices)
            self.assertEqual((sample.n_frames, sample.common_valid_count, sample.common_coverage),
                             (30, 30, 1.0))
            self.assertTrue(sample.eligible)
            self.assertEqual(sample.ordered_values()[0], 15.5)
            self.assertEqual(sample.ordered_values()[-1], -20.0)
        with self.assertRaisesRegex(ValueError, "missing or duplicate"):
            h6.load_labeled_probe_h_samples([path])

    def test_common_eligible_keys_preserve_each_candidates_own_support(self):
        rows = []
        for segment, count in (("1", 60), ("2", 30), ("3", 30), ("4", 29)):
            for i in range(1, count + 1):
                value = row(segment, index=i)
                if (segment == "1" and i <= 30) or (segment == "3" and i == 30):
                    value[legacy.H9_FEATURE_NAMES[-1]] = ""
                if (segment == "1" and i > 30) or (segment == "2" and i == 30):
                    value[v2.H9_V2_C3_FEATURE] = "  "
                rows.append(value)
        path = self.write_csv(rows)
        old = h6.load_labeled_probe_h_samples([path])
        new = h6.load_labeled_probe_h9_v2_samples([path])
        self.assertEqual([s.sample_key for s in old], [s.sample_key for s in new])
        self.assertEqual([s.input_frame_indices for s in old], [s.input_frame_indices for s in new])
        old_keys = {s.sample_key for s in old if s.eligible}
        new_keys = {s.sample_key for s in new if s.eligible}
        self.assertEqual({key[-1] for key in old_keys}, {"1", "2"})
        self.assertEqual({key[-1] for key in new_keys}, {"1", "3"})
        self.assertEqual(old_keys & new_keys, {new[0].sample_key})
        self.assertEqual(old[0].common_valid_frame_indices, tuple(range(31, 61)))
        self.assertEqual(new[0].common_valid_frame_indices, tuple(range(1, 31)))
        self.assertEqual(new[0].common_coverage, 0.5)
        self.assertEqual(new[0].missing_counts[v2.H9_V2_C3_FEATURE], 30)
        self.assertEqual(old[0].missing_counts[legacy.H9_FEATURE_NAMES[-1]], 30)
        self.assertEqual(new[0].ordered_values()[0], 15.5)
        self.assertEqual(old[0].ordered_values("H9")[0], 45.5)
        self.assertEqual(old[0].ordered_values("H5"), old[0].ordered_values("H9")[:5])
        self.assertIn("common_valid_frames<30", new[1].eligibility_reasons)
        self.assertEqual(len(new), 4)  # Ineligible segments remain available for audit.

    def test_repeated_postures_and_recordings_remain_separate(self):
        first = self.write_csv([row(segment) for segment in ("1", "3") for _ in range(30)])
        rows = [row() for _ in range(30)]
        for value in rows:
            value["recording_id"] = "second-recording"
        second = self.write_csv(rows, name="second.csv")
        samples = h6.load_labeled_probe_h9_v2_samples([second, first])
        self.assertEqual(len(samples), 3)
        self.assertEqual(len({s.sample_key for s in samples}), 3)
        self.assertEqual([s.sample_key for s in samples], sorted(s.sample_key for s in samples))
        self.assertTrue(all(s.eligible for s in samples))

    def test_duplicate_recording_and_identity_conflicts_rejected(self):
        path = self.write_csv([row()])
        with self.assertRaisesRegex(ValueError, "duplicate probe recording_id"):
            h6.load_labeled_probe_h9_v2_samples([path, path])
        for changes, error in (({"subject": "different"}, "multiple recording identities"),
                               ({"recording_id": "different"}, "multiple recording identities"),
                               ({"label": h6.LAB6[1]}, "conflicting labelled probe segment"),
                               ({"segment_id": ""}, "empty labelled probe identity"),
                               ({"label": "unknown"}, "not a six-posture label")):
            with self.subTest(changes=changes):
                other = row()
                other.update(changes)
                path = self.write_csv([row(), other])
                with self.assertRaisesRegex(ValueError, error):
                    h6.load_labeled_probe_h9_v2_samples([path])

    def test_missing_columns_bad_headers_values_and_artifact_kind_rejected(self):
        bad_fields = (FIELDS[:-1], (*FIELDS, FIELDS[-1]),
                      tuple(name for name in FIELDS if name != legacy.H5_FEATURE_NAMES[0]))
        for fields in bad_fields:
            with self.subTest(fields=fields):
                path = self.write_csv([row()], fields=fields)
                with self.assertRaisesRegex(ValueError, "missing or duplicate"):
                    h6.load_labeled_probe_h9_v2_samples([path])
        for bad in ("nan", "inf", "not-a-number"):
            with self.subTest(bad=bad):
                value = row()
                value[v2.H9_V2_C3_FEATURE] = bad
                path = self.write_csv([value])
                with self.assertRaises(ValueError):
                    h6.load_labeled_probe_h9_v2_samples([path])
        value = row()
        value["artifact_kind"] = "wrong-kind"
        path = self.write_csv([value])
        with self.assertRaisesRegex(ValueError, "unexpected probe artifact kind"):
            h6.load_labeled_probe_h9_v2_samples([path])

    def test_empty_and_malformed_rows_rejected(self):
        for rows in ([], [row("0", "PREP"), row("0", "TRANSITION")]):
            path = self.write_csv(rows)
            with self.assertRaisesRegex(ValueError, "no six-posture frames"):
                h6.load_labeled_probe_h9_v2_samples([path])
        for cells in (("short-row",), (*row().values(), "extra-cell")):
            path = self.root / "malformed.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(FIELDS)
                writer.writerow(cells)
            with self.assertRaisesRegex(ValueError, "malformed probe CSV row"):
                h6.load_labeled_probe_h9_v2_samples([path])


if __name__ == "__main__":
    unittest.main()
