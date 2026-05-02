import argparse
import json
import tempfile
import unittest
from pathlib import Path

from src.display_report_card import (
    REFERENCE_GAMUTS,
    ThermalLuminanceProfile,
    ThermalLuminanceSample,
    comparison_status_rows,
    format_fpga_label,
    gamut_temperature_annotation_parts,
    load_run_folder,
    render_report_card,
    series_labels,
    thermal_duration_minutes,
    thermal_final_d65_tolerance_multiple,
    thermal_tolerance_exit,
)


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

        self.assertEqual(run.header.run_id, "run-20260427-140033")
        self.assertEqual(run.header.display_size, '12.3"')
        self.assertEqual(run.header.display_resolution, "1920x720")
        self.assertEqual(len(run.status_rows), 22)
        self.assertEqual(run.brightness.source, "artifacts/brightness-calibration-81step.json")
        self.assertEqual(len(run.brightness.brightness_percent), 81)
        self.assertEqual(run.brightness.sample_count, 81)
        self.assertTrue(run.brightness.complete)
        self.assertFalse(run.brightness.from_cache)
        self.assertIsNotNone(run.gamma)
        self.assertAlmostEqual(run.gamma.gamma, 2.1824458280662506)
        self.assertEqual(len(run.gamma.code), 33)
        self.assertEqual(run.contrast.result, "PASS")
        self.assertEqual(len(run.contrast.brightness), 5)
        self.assertEqual(run.gamut.reference_name, "NTSC 1953")
        self.assertEqual(run.gamut.reference_white_name, "D65")
        self.assertAlmostEqual(run.gamut.coverage_percent, 78.85033441772023)
        self.assertFalse(run.gamut.white_within_tolerance)
        self.assertIsNotNone(run.local_dimming_apl)
        self.assertEqual(run.local_dimming_apl.source, "artifacts/local-dimming-apl-sweep.json")
        self.assertTrue(run.local_dimming_apl.complete)
        self.assertEqual(run.local_dimming_apl.samples_attempted, 14)
        self.assertEqual(run.local_dimming_apl.samples_collected, 10)
        self.assertEqual(run.local_dimming_apl.samples_skipped, 4)
        measured = [sample for sample in run.local_dimming_apl.samples if sample.fits_screen]
        skipped = [sample.apl_percent for sample in run.local_dimming_apl.samples if not sample.fits_screen]
        peak = max(measured, key=lambda sample: sample.luminance or 0)
        self.assertEqual(len(measured), 10)
        self.assertEqual(skipped, [1.0, 40.0, 45.0, 50.0])
        self.assertEqual(peak.apl_percent, 35.0)
        self.assertAlmostEqual(peak.luminance, 871.972473)

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

    def test_gamut_temperature_metadata_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            raw_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "gamut-temp"})
            write_json(
                raw_dir / "test-color-gamut.json",
                {
                    "test_info": {"name": "test-color-gamut", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {
                        "backlight_temp_c_start": 40.6,
                        "backlight_temp_c_end": 43.5,
                        "backlight_temp_c_avg": 42.05,
                        "backlight_temp_source": "disptool-bltemp",
                        "gamut_data": [
                            {"color": "W", "Y_luminance": 1000, "x_chromaticity": 0.3127, "y_chromaticity": 0.3290, "backlight_temp_c": 40.6},
                            {"color": "R", "x_chromaticity": 0.68, "y_chromaticity": 0.32, "backlight_temp_c": 41.1},
                            {"color": "G", "x_chromaticity": 0.23, "y_chromaticity": 0.71, "backlight_temp_c": 42.0},
                            {"color": "B", "x_chromaticity": 0.14, "y_chromaticity": 0.08, "backlight_temp_c": 43.5},
                        ],
                    },
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertIsNotNone(run.gamut)
        self.assertAlmostEqual(run.gamut.backlight_temp_c_start, 40.6)
        self.assertAlmostEqual(run.gamut.backlight_temp_c_end, 43.5)
        self.assertAlmostEqual(run.gamut.backlight_temp_c_avg, 42.05)
        self.assertEqual(run.gamut.backlight_temp_source, "disptool-bltemp")
        self.assertEqual(run.gamut.color_backlight_temps["B"], 43.5)
        self.assertEqual(gamut_temperature_annotation_parts(run.gamut), ["temp 40.6->43.5C", "avg 42.1C"])

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

    def test_brightness_nits_verify_note_uses_artifact_peak_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            artifact_dir = run_dir / "artifacts"
            raw_dir.mkdir()
            artifact_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "nits-verify"})
            write_json(
                raw_dir / "test-brightness-nits-verify.json",
                {
                    "test_info": {"name": "test-brightness-nits-verify", "category": "validation"},
                    "execution": {"result": "FAIL"},
                    "data": {
                        "nits_verify_json": "artifacts/brightness-nits-verify.json",
                        "samples_compared": 3,
                        "samples_failed": 2,
                    },
                },
            )
            write_json(
                artifact_dir / "brightness-nits-verify.json",
                {
                    "schema_version": "1.0",
                    "samples_compared": 3,
                    "samples_failed": 2,
                    "samples": [
                        {"brightness_percent": 0, "delta_pct": None, "comparison": "skipped_below_floor"},
                        {"brightness_percent": 10, "delta_pct": 3.330, "comparison": "fail"},
                        {"brightness_percent": 20, "delta_pct": 3.177, "comparison": "fail"},
                        {"brightness_percent": 30, "delta_pct": 1.115, "comparison": "pass"},
                    ],
                },
            )

            run = load_run_folder(run_dir, loader_args())

        nits_row = next(row for row in run.status_rows if row.name == "test-brightness-nits-verify")
        self.assertEqual(nits_row.result, "FAIL")
        self.assertEqual(nits_row.note, "max 3.33%@10%,2/3")

    def test_brightness_nits_verify_note_falls_back_to_log_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            raw_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "nits-verify-log"})
            write_json(
                raw_dir / "test-brightness-nits-verify.json",
                {
                    "test_info": {"name": "test-brightness-nits-verify", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {},
                },
            )
            (raw_dir / "test-brightness-nits-verify.log").write_text(
                "\n".join(
                    [
                        "[11:40:28] [2/11] Brightness 10%...",
                        "[11:40:29]   PASS: nits_als=105.0, Y_meas=108.6, delta=3.330% (<= 4.0%)",
                        "[11:40:29] [3/11] Brightness 20%...",
                        "[11:40:31]   PASS: nits_als=213.8, Y_meas=220.8, delta=3.177% (<= 4.0%)",
                    ]
                ),
                encoding="utf-8",
            )

            run = load_run_folder(run_dir, loader_args())

        nits_row = next(row for row in run.status_rows if row.name == "test-brightness-nits-verify")
        self.assertEqual(nits_row.result, "PASS")
        self.assertEqual(nits_row.note, "max 3.33%@10%")

    def test_local_dimming_apl_artifact_preserves_skipped_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            artifact_dir = run_dir / "artifacts"
            raw_dir.mkdir()
            artifact_dir.mkdir()
            write_json(run_dir / "summary.json", {"run_id": "local-dimming-apl"})
            write_json(
                raw_dir / "test-local-dimming-apl.json",
                {
                    "test_info": {"name": "test-local-dimming-apl", "category": "validation"},
                    "execution": {"result": "PASS"},
                    "data": {
                        "apl_json": "artifacts/local-dimming-apl-sweep.json",
                        "samples_attempted": 3,
                        "samples_collected": 2,
                        "samples_skipped": 1,
                    },
                },
            )
            write_json(
                artifact_dir / "local-dimming-apl-sweep.json",
                {
                    "schema_version": "1.0",
                    "display_model": "fixture-display",
                    "test_id": "test-local-dimming-apl",
                    "run_id": "local-dimming-apl",
                    "complete": True,
                    "artifact_generated_timestamp": "2026-04-27T12:29:28Z",
                    "backlight_percent": 100,
                    "samples_attempted": 3,
                    "samples_collected": 2,
                    "samples_skipped": 1,
                    "samples": [
                        apl_sample(1, 1.0, None, False, "box side 10mm smaller than i1 sensor minimum 25mm"),
                        apl_sample(2, 2.0, 100.0, True, ""),
                        apl_sample(3, 5.0, 250.0, True, ""),
                    ],
                },
            )

            run = load_run_folder(run_dir, loader_args())

        self.assertEqual(run.local_dimming_apl.source, "artifacts/local-dimming-apl-sweep.json")
        self.assertEqual(run.local_dimming_apl.samples_attempted, 3)
        self.assertEqual(run.local_dimming_apl.samples_collected, 2)
        self.assertEqual(run.local_dimming_apl.samples_skipped, 1)
        self.assertEqual([sample.apl_percent for sample in run.local_dimming_apl.samples], [1.0, 2.0, 5.0])
        self.assertEqual([sample.luminance for sample in run.local_dimming_apl.samples], [None, 100.0, 250.0])
        self.assertFalse(run.local_dimming_apl.samples[0].fits_screen)
        apl_row = next(row for row in run.status_rows if row.name == "test-local-dimming-apl")
        self.assertEqual(apl_row.note, "2/3 APL, 1 skip")

    def test_thermal_profile_csv_is_loaded_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            raw_dir = run_dir / "raw"
            raw_dir.mkdir(parents=True)
            write_json(run_dir / "summary.json", {"run_id": "thermal-profile"})
            (raw_dir / "thermal-luminance-profile.csv").write_text(
                "\n".join(
                    [
                        "# live display measurement log",
                        "# record_interval_seconds=30.0",
                        "sample_index,timestamp,elapsed_seconds,X,Y,Z,x,y,backlight_temp_c",
                        "1,2026-04-30T17:36:28+02:00,4.0,1,1175.5,1,0.3101,0.3089,37.8",
                        "2,2026-04-30T18:40:59+02:00,3849.2,1,1122.5,1,0.3045,0.3020,55.3",
                    ]
                ),
                encoding="utf-8",
            )

            run = load_run_folder(run_dir, loader_args())
            output = Path(temp_dir) / "thermal.png"
            render_report_card(run, output, "Display Test Report Card", 72, "ntsc", "basic")

            self.assertIsNotNone(run.thermal_profile)
            self.assertEqual(run.thermal_profile.source, "raw/thermal-luminance-profile.csv")
            self.assertEqual(run.thermal_profile.metadata["record_interval_seconds"], "30.0")
            self.assertEqual(len(run.thermal_profile.samples), 2)
            self.assertAlmostEqual(run.thermal_profile.samples[-1].backlight_temp_c, 55.3)
            self.assertAlmostEqual(thermal_duration_minutes(run.thermal_profile), 64.08666666666667)
            self.assertTrue(output.exists())

    def test_thermal_final_d65_tolerance_multiple_uses_endpoint(self) -> None:
        reference_white = REFERENCE_GAMUTS["ntsc"]["w"]
        profile = ThermalLuminanceProfile(
            source="raw/thermal-luminance-profile.csv",
            metadata={},
            samples=[
                ThermalLuminanceSample(1, "", 0.0, 100.0, reference_white[0], reference_white[1], 30.0),
                ThermalLuminanceSample(2, "", 60.0, 90.0, reference_white[0] + 0.025, reference_white[1], 55.0),
            ],
        )

        self.assertAlmostEqual(thermal_final_d65_tolerance_multiple(profile, reference_white), 2.5)

    def test_thermal_tolerance_exit_interpolates_first_boundary_crossing(self) -> None:
        reference_white = REFERENCE_GAMUTS["ntsc"]["w"]
        profile = ThermalLuminanceProfile(
            source="raw/thermal-luminance-profile.csv",
            metadata={},
            samples=[
                ThermalLuminanceSample(1, "", 0.0, 100.0, reference_white[0], reference_white[1], 30.0),
                ThermalLuminanceSample(2, "", 60.0, 90.0, reference_white[0] + 0.020, reference_white[1], 60.0),
            ],
        )

        tolerance_exit = thermal_tolerance_exit(profile, reference_white)

        self.assertIsNotNone(tolerance_exit)
        assert tolerance_exit is not None
        self.assertAlmostEqual(tolerance_exit.x_chromaticity, reference_white[0] + 0.010)
        self.assertAlmostEqual(tolerance_exit.y_chromaticity, reference_white[1])
        self.assertAlmostEqual(tolerance_exit.backlight_temp_c, 45.0)
        self.assertAlmostEqual(tolerance_exit.elapsed_seconds, 30.0)

    def test_thermal_tolerance_exit_ignores_runs_starting_outside_tolerance(self) -> None:
        reference_white = REFERENCE_GAMUTS["ntsc"]["w"]
        profile = ThermalLuminanceProfile(
            source="raw/thermal-luminance-profile.csv",
            metadata={},
            samples=[
                ThermalLuminanceSample(1, "", 0.0, 100.0, reference_white[0] + 0.020, reference_white[1], 30.0),
                ThermalLuminanceSample(2, "", 60.0, 90.0, reference_white[0] + 0.030, reference_white[1], 60.0),
            ],
        )

        self.assertIsNone(thermal_tolerance_exit(profile, reference_white))

    def test_comparison_mode_highlights_result_changes_and_renders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_dir = root / "base"
            run_dir = root / "run"
            write_minimal_run(base_dir, "base-run", "v02", "April 9", "ERROR")
            write_minimal_run(run_dir, "run-run", "v03", "April 29", "PASS")

            base = load_run_folder(base_dir, loader_args())
            run = load_run_folder(run_dir, loader_args())
            rows = comparison_status_rows(run, base)
            changed = next(row for row in rows if row.name == "test-ioc-i2c-flood")
            output = root / "compare.png"
            render_report_card(run, output, "Display Test Report Card", 72, "ntsc", "basic", base)

            self.assertEqual(format_fpga_label(base), "v02 Apr 9")
            self.assertEqual(format_fpga_label(run), "v03 Apr 29")
            self.assertEqual(series_labels(run, base, "v03", "v02").run, "v03")
            self.assertEqual(series_labels(run, base, "v03", "v02").base, "v02")
            self.assertEqual(changed.note, "was ERROR; 150/150 ops ok")
            self.assertTrue(output.exists())

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


def write_minimal_run(path: Path, run_id: str, fpga_version: str, fpga_date: str, ioc_flood_result: str) -> None:
    raw_dir = path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        path / "summary.json",
        {
            "run_id": run_id,
            "timestamp": "2026-04-29T07:00:00Z",
            "display_model": "12.3-nq1-lattice-ecp5",
            "total_tests": 2,
            "passed": 2 if ioc_flood_result == "PASS" else 1,
            "failed": 0,
            "errors": 0 if ioc_flood_result == "PASS" else 1,
            "skipped": 0,
        },
    )
    write_json(
        raw_dir / "test-version-read.json",
        {
            "test_info": {"name": "test-version-read", "category": "unit"},
            "execution": {"result": "PASS"},
            "data": {"version": fpga_version, "date": fpga_date},
        },
    )
    write_json(
        raw_dir / "test-ioc-i2c-flood.json",
        {
            "test_info": {"name": "test-ioc-i2c-flood", "category": "integration"},
            "execution": {"result": ioc_flood_result},
            "data": {"total_operations": 150, "failed_operations": 0},
        },
    )


def brightness_sample(index: int, brightness_percent: float, luminance: float) -> dict:
    return {
        "index": index,
        "brightness_percent": brightness_percent,
        "Y_luminance": luminance,
        "x_chromaticity": 0.3127,
        "y_chromaticity": 0.3290,
        "timestamp": "2026-04-26T13:20:00Z",
    }


def apl_sample(index: int, apl_percent: float, luminance: float | None, fits_screen: bool, skip_reason: str) -> dict:
    return {
        "index": index,
        "apl_percent": apl_percent,
        "box_side_mm": 30.0,
        "fits_screen": fits_screen,
        "Y_luminance": luminance,
        "x_chromaticity": 0.3127 if fits_screen else None,
        "y_chromaticity": 0.3290 if fits_screen else None,
        "skip_reason": skip_reason or None,
        "timestamp": "2026-04-27T12:29:28Z",
    }


if __name__ == "__main__":
    unittest.main()
