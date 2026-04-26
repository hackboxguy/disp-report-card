import argparse
import json
import tempfile
import unittest
from pathlib import Path

from src.display_report_card import load_run_folder


REPO_ROOT = Path(__file__).resolve().parents[1]


def loader_args() -> argparse.Namespace:
    return argparse.Namespace(
        reference_gamut="ntsc",
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
        self.assertEqual(run.gamut.reference_name, "NTSC 1953")
        self.assertEqual(run.gamut.reference_white_name, "D65")
        self.assertAlmostEqual(run.gamut.coverage_percent, 79.2037177619253)
        self.assertFalse(run.gamut.white_within_tolerance)

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
        self.assertAlmostEqual(run.gamut.coverage_percent, 97.14563621344901)
        self.assertGreater(run.gamut.relative_area_percent, 100.0)
        self.assertTrue(run.gamut.white_within_tolerance)

    def test_missing_summary_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                load_run_folder(Path(temp_dir), loader_args())

    def test_report_metadata_overrides_header_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            write_json(
                run_dir / "summary.json",
                {
                    "run_id": "summary-run",
                    "timestamp": "2026-04-26T10:00:00Z",
                    "display_model": "fallback-model",
                },
            )
            write_json(
                run_dir / "report-metadata.json",
                {
                    "run_id": "metadata-run",
                    "test_timestamp": "2026-04-26T11:00:00Z",
                    "display_model": "15.6-0od-lattice-ecp5",
                    "display_size": '15.6"',
                    "display_resolution": "2560x1440",
                    "display_serial_number": "SERIAL-123",
                    "fpga_sw_version": "v99",
                    "mcu_sw_version": "v88",
                    "tester_version": "display-test-framework test",
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertEqual(run.header.run_id, "metadata-run")
        self.assertEqual(run.header.timestamp, "2026-04-26T11:00:00Z")
        self.assertEqual(run.header.display_model, "15.6-0od-lattice-ecp5")
        self.assertEqual(run.header.display_size, '15.6"')
        self.assertEqual(run.header.display_resolution, "2560x1440")
        self.assertEqual(run.header.display_serial_number, "SERIAL-123")
        self.assertEqual(run.header.fpga_sw_version, "v99")
        self.assertEqual(run.header.mcu_sw_version, "v88")
        self.assertEqual(run.header.tester_version, "display-test-framework test")

    def test_missing_gamma_artifact_warns_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            raw_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "missing-gamma-artifact"})
            write_json(
                raw_dir / "test-gamma-curve.json",
                {
                    "test_info": {"name": "test-gamma-curve", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {"csv_path": "/tmp/missing/gamma_curve_test-gamma-curve.csv"},
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertIsNone(run.gamma)
        self.assertTrue(any("artifact not found" in warning for warning in run.warnings))
        self.assertEqual(len(run.status_rows), 1)

    def test_brightness_calibration_artifact_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            artifact_dir = run_dir / "artifacts"
            raw_dir.mkdir()
            artifact_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "brightness-artifact"})
            write_json(
                raw_dir / "test-brightness-calibration.json",
                {
                    "test_info": {"name": "test-brightness-calibration", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {
                        "calibration_json": "artifacts/brightness-calibration-81step.json",
                        "total_samples": 3,
                        "samples_collected": 3,
                        "from_cache": False,
                    },
                },
            )
            write_json(
                raw_dir / "test-brightness-linearity.json",
                {
                    "test_info": {"name": "test-brightness-linearity", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {
                        "measured_data": [
                            {"brightness_percent": 0, "luminance": 0.0, "expected_luminance": 0.0},
                            {"brightness_percent": 100, "luminance": 999.0, "expected_luminance": 999.0},
                        ]
                    },
                },
            )
            write_json(
                artifact_dir / "brightness-calibration-81step.json",
                {
                    "schema_version": "1.0",
                    "total_samples": 3,
                    "samples_collected": 3,
                    "complete": True,
                    "from_cache": False,
                    "samples": [
                        brightness_sample(1, 0.0, 0.0),
                        brightness_sample(2, 1.25, 8.8),
                        brightness_sample(3, 2.5, 29.7),
                    ],
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertEqual(run.brightness.source, "artifacts/brightness-calibration-81step.json")
        self.assertEqual(run.brightness.brightness_percent, [0.0, 1.25, 2.5])
        self.assertEqual(run.brightness.luminance, [0.0, 8.8, 29.7])
        self.assertEqual(run.brightness.sample_count, 3)
        self.assertTrue(run.brightness.complete)
        self.assertFalse(run.brightness.from_cache)
        self.assertEqual(run.brightness.expected_luminance, [])
        calibration_row = next(row for row in run.status_rows if row.name == "test-brightness-calibration")
        self.assertEqual(calibration_row.note, "3/3 samples")

    def test_missing_brightness_calibration_artifact_falls_back_to_linearity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            raw_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "brightness-fallback"})
            write_json(
                raw_dir / "test-brightness-calibration.json",
                {
                    "test_info": {"name": "test-brightness-calibration", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {
                        "calibration_json": "artifacts/missing-brightness-calibration.json",
                        "total_samples": 81,
                    },
                },
            )
            write_json(
                raw_dir / "test-brightness-linearity.json",
                {
                    "test_info": {"name": "test-brightness-linearity", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {
                        "measured_data": [
                            {"brightness_percent": 0, "luminance": 0.0, "expected_luminance": 0.0},
                            {"brightness_percent": 100, "luminance": 900.0, "expected_luminance": 900.0},
                        ]
                    },
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertEqual(run.brightness.source, "test-brightness-linearity")
        self.assertEqual(run.brightness.brightness_percent, [0.0, 100.0])
        self.assertEqual(run.brightness.expected_luminance, [0.0, 900.0])
        self.assertTrue(any("artifact not found" in warning for warning in run.warnings))

    def test_malformed_optional_raw_json_is_skipped_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            raw_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "bad-raw"})
            (raw_dir / "broken.json").write_text("{not-json", encoding="utf-8")
            write_json(
                raw_dir / "test-version-read.json",
                {
                    "test_info": {"name": "test-version-read", "category": "unit"},
                    "execution": {"result": "PASS"},
                    "data": {"version": "v01", "date": "2026-04-26"},
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertEqual(set(run.tests), {"test-version-read"})
        self.assertTrue(any("skipping unreadable raw test JSON broken.json" in warning for warning in run.warnings))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def brightness_sample(index: int, brightness_percent: float, luminance: float) -> dict:
    return {
        "index": index,
        "brightness_percent": brightness_percent,
        "Y_luminance": luminance,
        "x_chromaticity": 0.3127,
        "y_chromaticity": 0.3290,
        "timestamp": "2026-04-26T13:20:00Z",
    }


if __name__ == "__main__":
    unittest.main()
