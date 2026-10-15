"""Patch 8 OpenCV distribution identity contract tests (synthetic; no hardware)."""
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

import analyze_d455
import patch8_ledger as ledger
import patch8_prelock as prelock
from patch8_test_fixtures import analysis_environment, environment


def packages(opencv_python=None, opencv_contrib=None, **changes):
    value = {"mediapipe": "1.0.1", "pyrealsense2": "2.58.4.10922", "numpy": "2.5.3",
             "opencv-python": opencv_python, "opencv-contrib-python": opencv_contrib}
    value.update(changes)
    return value


class OpenCVIdentityContractTests(unittest.TestCase):
    def test_opencv_python_only_passes_and_normalizes_absent_alternative(self):
        identity = ledger.capture_environment_identity(
            environment(packages=packages(opencv_python="4.14.0.94")))
        self.assertIsNotNone(identity)
        self.assertEqual(identity["packages"]["opencv-python"], "4.14.0.94")
        self.assertIsNone(identity["packages"]["opencv-contrib-python"])

    def test_opencv_contrib_only_passes_and_normalizes_absent_alternative(self):
        identity = ledger.capture_environment_identity(
            environment(packages=packages(opencv_contrib="5.0.0.93")))
        self.assertIsNotNone(identity)
        self.assertIsNone(identity["packages"]["opencv-python"])
        self.assertEqual(identity["packages"]["opencv-contrib-python"], "5.0.0.93")

    def test_neither_opencv_distribution_fails(self):
        self.assertIsNone(ledger.capture_environment_identity(environment(packages=packages())))
        self.assertIsNone(ledger.analysis_environment_identity(analysis_environment(packages=packages())))

    def test_both_opencv_distributions_fail(self):
        both = packages(opencv_python="4.14.0.94", opencv_contrib="5.0.0.93")
        self.assertIsNone(ledger.capture_environment_identity(environment(packages=both)))
        self.assertIsNone(ledger.analysis_environment_identity(analysis_environment(packages=both)))

    def test_same_host_capture_and_analysis_match_passes(self):
        installed = packages(opencv_contrib="5.0.0.93")
        capture = ledger.capture_environment_identity(environment(packages=installed))
        state = SimpleNamespace(baseline_environment=capture, baseline_analysis_environment=None)
        self.assertIsNone(ledger.analysis_environment_error(
            state, analysis_environment(packages=installed)))

    def test_same_host_distribution_mismatch_fails(self):
        capture = ledger.capture_environment_identity(
            environment(packages=packages(opencv_python="4.14.0.94")))
        state = SimpleNamespace(baseline_environment=capture, baseline_analysis_environment=None)
        error = ledger.analysis_environment_error(
            state, analysis_environment(packages=packages(opencv_contrib="5.0.0.93")))
        self.assertIn("same-host analysis environment differs", error)

    def test_same_host_version_mismatch_fails(self):
        capture = ledger.capture_environment_identity(
            environment(packages=packages(opencv_contrib="5.0.0.93")))
        state = SimpleNamespace(baseline_environment=capture, baseline_analysis_environment=None)
        error = ledger.analysis_environment_error(
            state, analysis_environment(packages=packages(opencv_contrib="5.0.0.94")))
        self.assertIn("same-host analysis environment differs", error)

    def test_incomplete_mandatory_package_information_fails(self):
        for package in ledger.REQUIRED_PACKAGE_KEYS:
            with self.subTest(package=package):
                incomplete = packages(opencv_contrib="5.0.0.93", **{package: None})
                self.assertIsNone(ledger.capture_environment_identity(environment(packages=incomplete)))
                self.assertIsNone(ledger.analysis_environment_identity(
                    analysis_environment(packages=incomplete)))

    def test_windows_package_collector_preserves_distribution_names_and_versions(self):
        installed = {"pyrealsense2": "2.58.4.10922", "opencv-contrib-python": "5.0.0.93",
                     "numpy": "2.5.3", "mediapipe": "1.0.1", "pillow": "12.3.0"}

        def version(name):
            if name == "opencv-python":
                raise prelock.importlib.metadata.PackageNotFoundError(name)
            return installed[name]

        with patch.object(prelock.importlib.metadata, "version", side_effect=version) as mocked:
            collected = prelock.package_versions()
        self.assertEqual(collected, dict(installed, **{"opencv-python": None}))
        self.assertEqual(mocked.call_args_list, [call(name) for name in prelock.ENVIRONMENT_PACKAGES])

    def test_analysis_provenance_does_not_flag_expected_opencv_absence(self):
        installed = {"mediapipe": "1.0.1", "pyrealsense2": "2.58.4.10922",
                     "opencv-contrib-python": "5.0.0.93", "numpy": "2.5.3", "matplotlib": "3.10.7"}

        def version(name):
            if name == "opencv-python":
                raise analyze_d455.importlib.metadata.PackageNotFoundError(name)
            return installed[name]

        reasons = {}
        with patch.object(analyze_d455.importlib.metadata, "version", side_effect=version):
            identity = analyze_d455.analysis_environment(reasons)
        self.assertIsNone(identity["opencv-python"])
        self.assertEqual(identity["opencv-contrib-python"], "5.0.0.93")
        self.assertNotIn("environment.opencv-python", reasons)


if __name__ == "__main__":
    unittest.main()
