"""Synthetic structural checks, never research-data performance tests."""
import copy
import unittest

import numpy as np
from measure import relative, references


def fixture():
    data = dict(sample_keys=[["probe-csv:r", "r", str(i)] for i in (1, 3, 13)],
                subjects=["A"]*3, labels=[0, 1, 0])
    segments = [dict(subject="A", recording_id="r", segment_id=str(i), posture_id=p,
                     common_frame_indices=list(range(lo, lo+3)))
                for i, p, lo in ((1, "P0", 10), (3, "P1", 20), (13, "P0", 30))]
    return data, segments


class CalibrationChecks(unittest.TestCase):
    def test_circular_boundary_and_preserved_units(self):
        values = np.array([[2., 3., -179., 5., 6., 7., 8., 9.],
                           [2., 3., 179., 5., 6., 7., 8., 9.]])
        baseline = np.array([[1., 1., 179., 1., 1., 1., 1., 1.],
                             [1., 1., -179., 1., 1., 1., 1., 1.]])
        before = values.copy()
        result = relative(values, baseline)
        np.testing.assert_array_equal(result[:, 2], [2., -2.])
        np.testing.assert_array_equal(result[:, 0], [1., 1.])
        np.testing.assert_array_equal(values, before)

    def test_chronology_beats_lexical_or_input_order(self):
        data, seg = fixture()
        order = [2, 0, 1]
        data = {k: [v[i] for i in order] for k,v in data.items()}
        refs, _ = references(data, list(reversed(seg)))
        self.assertEqual(data["sample_keys"][refs["A"]][2], "1")

    def test_missing_order_is_blocked(self):
        data, seg = fixture()
        seg[0]["common_frame_indices"] = []
        with self.assertRaisesRegex(ValueError, "BLOCKED"):
            references(data, seg)

    def test_overlap_is_blocked(self):
        data, seg = fixture()
        seg[1]["common_frame_indices"] = [11, 12, 13]
        with self.assertRaisesRegex(ValueError, "BLOCKED"):
            references(data, seg)

    def test_unordered_recordings_are_blocked(self):
        data, seg = fixture()
        data["sample_keys"][2] = ["probe-csv:other", "other", "13"]
        seg[2]["recording_id"] = "other"
        with self.assertRaisesRegex(ValueError, "BLOCKED"):
            references(data, seg)

    def test_label_identity_mismatch_is_blocked(self):
        data, seg = fixture()
        seg[0]["posture_id"] = "P1"
        with self.assertRaisesRegex(ValueError, "BLOCKED"):
            references(data, seg)

    def test_evaluated_values_cannot_update_reference(self):
        values = np.arange(24, dtype=float).reshape(3, 8)
        baseline = values[0].copy()
        first = relative(values[1:2], baseline)
        changed = copy.deepcopy(values)
        changed[2] = 1e6  # Another evaluation sample, including a later P0.
        np.testing.assert_array_equal(relative(changed[1:2], baseline), first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
