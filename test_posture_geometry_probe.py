import csv
import math
import os
import tempfile
import unittest

import posture_geometry as geometry
import posture_geometry_probe as probe


def incomplete_result():
    return geometry.compute_candidate_geometry({
        "nose": geometry.Point(100, 40, None),
        "left_ear": None,
        "right_ear": geometry.Point(80, 50, .70),
        "left_shoulder": geometry.Point(140, 100, .80),
        "right_shoulder": geometry.Point(60, 100, None),
    }, focal_length_px=800)


class ProbeHelperTests(unittest.TestCase):
    def test_cli_default_has_no_output_path(self):
        args = probe.parse_args([])
        self.assertIsNone(args.csv)

    def test_feature_formatting_marks_missing_and_nonfinite_unavailable(self):
        self.assertEqual(probe.format_feature(None), "unavailable")
        self.assertEqual(probe.format_feature(math.nan), "unavailable")
        self.assertEqual(probe.format_feature(math.inf), "unavailable")
        self.assertEqual(probe.format_feature(.125, " m"), "+0.125 m")

    def test_missing_values_remain_blank_and_validity_is_explicit_in_csv(self):
        row = probe.exploratory_csv_row(
            incomplete_result(),
            pose_detected=True,
            device_timestamp_ms=123.5,
            timestamp_utc="2026-10-08T00:00:00.000+00:00",
        )
        self.assertEqual(row["artifact_kind"], probe.EXPLORATORY_ARTIFACT_KIND)
        self.assertTrue(row["nose_landmark_valid"])
        self.assertFalse(row["nose_depth_valid"])
        self.assertFalse(row["left_ear_landmark_valid"])
        self.assertFalse(row["right_shoulder_depth_valid"])
        self.assertIsNone(row["nose_forward_from_torso_m"])
        self.assertFalse(row["normalized_nose_available"])

    def test_csv_writer_is_opt_in_and_refuses_overwrite(self):
        handle, writer = probe._open_csv(None)
        self.assertIsNone(handle)
        self.assertIsNone(writer)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "exploratory.csv")
            handle, writer = probe._open_csv(path)
            try:
                writer.writerow(probe.exploratory_csv_row(
                    incomplete_result(), pose_detected=True, device_timestamp_ms=1.0,
                    timestamp_utc="2026-10-08T00:00:00.000+00:00"))
            finally:
                handle.close()
            with open(path, encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["artifact_kind"], probe.EXPLORATORY_ARTIFACT_KIND)
            self.assertEqual(rows[0]["nose_forward_from_torso_m"], "")
            with self.assertRaises(FileExistsError):
                probe._open_csv(path)


if __name__ == "__main__":
    unittest.main()
