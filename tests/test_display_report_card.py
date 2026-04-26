import argparse
import unittest
from pathlib import Path

from src.display_report_card import load_run_folder


REPO_ROOT = Path(__file__).resolve().parents[1]


def loader_args() -> argparse.Namespace:
    return argparse.Namespace(
        reference_gamut="srgb",
        serial_number=None,
        tester_version=None,
    )


class DisplayReportCardExtractionTest(unittest.TestCase):
    def test_loads_12_3_fixture(self) -> None:
        run = load_run_folder(REPO_ROOT / "test-data" / "12-3-nq1v1", loader_args())

        self.assertEqual(run.header.run_id, "run-20260426-085300")
        self.assertEqual(run.header.display_size, '12.3"')
        self.assertEqual(run.header.display_resolution, "1920x720")
        self.assertEqual(len(run.status_rows), 20)
        self.assertIsNotNone(run.gamma)
        self.assertAlmostEqual(run.gamma.gamma, 2.186854778899406)
        self.assertEqual(len(run.gamma.code), 33)
        self.assertEqual(run.contrast.result, "PASS")
        self.assertEqual(len(run.contrast.brightness), 5)

    def test_loads_15_6_fixture_with_partial_contrast(self) -> None:
        run = load_run_folder(REPO_ROOT / "test-data" / "15-6-0od", loader_args())

        self.assertEqual(run.header.run_id, "run-20260426-080625")
        self.assertEqual(run.header.display_size, '15.6"')
        self.assertEqual(run.header.display_resolution, "2560x1440")
        self.assertEqual(len(run.status_rows), 20)
        self.assertIsNotNone(run.gamma)
        self.assertAlmostEqual(run.gamma.gamma, 2.5371418606498857)
        self.assertEqual(run.gamma.source, "artifacts/gamma_curve_test-gamma-curve.csv")
        self.assertLess(run.gamma.endpoint_drift_percent, -2.0)
        self.assertEqual(run.contrast.result, "ERROR")
        self.assertEqual(len(run.contrast.brightness), 4)
        self.assertEqual(set(run.contrast.expected_levels) - set(run.contrast.brightness), {25.0})


if __name__ == "__main__":
    unittest.main()
