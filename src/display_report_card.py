#!/usr/bin/env python3
"""Generate a single-run display test report card PNG."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "disp-report-card-mpl")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, HPacker, TextArea
from matplotlib.patches import Ellipse, Rectangle
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
import numpy as np


A4_LANDSCAPE_INCHES = (11.69, 8.27)
DEFAULT_DPI = 200
DEFAULT_WHITE_TOLERANCE = 0.010
BASELINE_COLOR = "#6E7781"

STATUS_COLORS = {
    "PASS": "#1B8A5A",
    "SKIP": "#808A96",
    "ERROR": "#C9342F",
    "FAIL": "#D04A26",
    "INFO": "#5B6472",
}

REFERENCE_GAMUTS = {
    "srgb": {
        "name": "sRGB / Rec.709",
        "r": (0.640, 0.330),
        "g": (0.300, 0.600),
        "b": (0.150, 0.060),
        "w": (0.3127, 0.3290),
        "white_name": "D65",
    },
    "rec709": {
        "name": "sRGB / Rec.709",
        "r": (0.640, 0.330),
        "g": (0.300, 0.600),
        "b": (0.150, 0.060),
        "w": (0.3127, 0.3290),
        "white_name": "D65",
    },
    "dcip3": {
        "name": "DCI-P3 D65",
        "r": (0.680, 0.320),
        "g": (0.265, 0.690),
        "b": (0.150, 0.060),
        "w": (0.3127, 0.3290),
        "white_name": "D65",
    },
    "ntsc": {
        "name": "NTSC 1953",
        "r": (0.670, 0.330),
        "g": (0.210, 0.710),
        "b": (0.140, 0.080),
        "w": (0.3127, 0.3290),
        "white_name": "D65",
    },
    "rec2020": {
        "name": "Rec.2020",
        "r": (0.708, 0.292),
        "g": (0.170, 0.797),
        "b": (0.131, 0.046),
        "w": (0.3127, 0.3290),
        "white_name": "D65",
    },
}


@dataclass
class RawTest:
    name: str
    path: Path
    data: dict[str, Any]

    @property
    def result(self) -> str:
        return str(self.data.get("execution", {}).get("result", "UNKNOWN")).upper()

    @property
    def category(self) -> str:
        return str(self.data.get("test_info", {}).get("category", "unknown"))


@dataclass
class HeaderMetadata:
    run_id: str
    timestamp: str
    display_model: str
    display_size: str
    display_resolution: str
    display_serial_number: str
    fpga_sw_version: str
    fpga_companion: str
    mcu_sw_version: str
    tester_version: str


@dataclass
class StatusRow:
    name: str
    category: str
    result: str
    note: str


@dataclass
class BrightnessCurve:
    source: str
    brightness_percent: list[float]
    luminance: list[float]
    expected_luminance: list[float] = field(default_factory=list)
    sample_count: int | None = None
    complete: bool | None = None
    from_cache: bool | None = None


@dataclass
class GammaCurve:
    source: str
    code: np.ndarray
    normalized_input: np.ndarray
    luminance: np.ndarray
    normalized_luminance: np.ndarray
    y_std: np.ndarray
    x_chromaticity: np.ndarray
    y_chromaticity: np.ndarray
    gamma: float | None
    rms_gamma: float | None
    rms_srgb: float | None
    y_black: float
    y_max: float
    endpoint_drift_percent: float | None
    samples_per_patch: int | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ContrastCurve:
    source: str
    expected_levels: list[float]
    brightness: list[float]
    contrast_ratio: list[float]
    contrast_display: list[str]
    lower_bound: list[bool]
    result: str
    errors: list[str]


@dataclass
class GamutMetrics:
    source: str
    points: dict[str, tuple[float, float]]
    white_luminance: float | None
    white_point: tuple[float, float] | None
    reference_name: str
    reference_white: tuple[float, float]
    reference_white_name: str
    reference_points: dict[str, tuple[float, float]]
    measured_area: float | None
    reference_area: float | None
    overlap_area: float | None
    coverage_percent: float | None
    relative_area_percent: float | None
    white_delta: tuple[float, float] | None
    white_tolerance: float
    white_tolerance_distance: float | None
    white_within_tolerance: bool | None
    backlight_temp_c_start: float | None = None
    backlight_temp_c_end: float | None = None
    backlight_temp_c_avg: float | None = None
    backlight_temp_source: str = ""
    color_backlight_temps: dict[str, float] = field(default_factory=dict)


@dataclass
class LocalDimmingAplSample:
    index: int
    apl_percent: float
    box_side_mm: float | None
    fits_screen: bool
    luminance: float | None
    x_chromaticity: float | None
    y_chromaticity: float | None
    skip_reason: str
    timestamp: str


@dataclass
class LocalDimmingAplCurve:
    source: str
    display_model: str
    complete: bool | None
    artifact_generated_timestamp: str
    backlight_percent: float | None
    samples_attempted: int | None
    samples_collected: int | None
    samples_skipped: int | None
    samples: list[LocalDimmingAplSample]


@dataclass
class ThermalLuminanceSample:
    index: int
    timestamp: str
    elapsed_seconds: float | None
    luminance: float
    x_chromaticity: float
    y_chromaticity: float
    backlight_temp_c: float | None


@dataclass
class ThermalLuminanceProfile:
    source: str
    metadata: dict[str, str]
    samples: list[ThermalLuminanceSample]


@dataclass
class ThermalToleranceExit:
    x_chromaticity: float
    y_chromaticity: float
    backlight_temp_c: float | None
    elapsed_seconds: float | None


@dataclass
class RunData:
    run_dir: Path
    summary: dict[str, Any]
    tests: dict[str, RawTest]
    header: HeaderMetadata
    status_rows: list[StatusRow]
    brightness: BrightnessCurve | None
    gamma: GammaCurve | None
    contrast: ContrastCurve | None
    gamut: GamutMetrics | None
    local_dimming_apl: LocalDimmingAplCurve | None
    thermal_profile: ThermalLuminanceProfile | None
    warnings: list[str]


@dataclass
class SeriesLabels:
    run: str
    base: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def shorten(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "."


def format_timestamp(value: str) -> str:
    if not value or value == "TBD":
        return "TBD"
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-._" else "-" for char in value)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "report"


def derive_display_size(display_model: str) -> str:
    if not display_model:
        return "TBD"
    token = display_model.split("-", 1)[0]
    try:
        float(token)
    except ValueError:
        return "TBD"
    return f'{token}"'


def discover_tests(run_dir: Path, warnings: list[str] | None = None) -> dict[str, RawTest]:
    raw_dir = run_dir / "raw"
    tests: dict[str, RawTest] = {}
    if not raw_dir.exists():
        return tests

    for path in sorted(raw_dir.glob("*.json")):
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            if warnings is not None:
                warnings.append(f"skipping unreadable raw test JSON {path.name}: {exc}")
            continue
        name = str(get_nested(data, "test_info", "name", default=path.stem))
        tests[name] = RawTest(name=name, path=path, data=data)
    return tests


def resolve_artifact_path(
    run_dir: Path,
    raw_test_path: Path | None,
    recorded_path: str | None,
    fallback_relative: str | None = None,
) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    candidates: list[Path] = []

    if recorded_path:
        recorded = Path(recorded_path)
        if recorded.is_absolute():
            candidates.append(recorded)
            candidates.append(run_dir / "artifacts" / recorded.name)
        else:
            candidates.append(run_dir / recorded)
            if raw_test_path is not None:
                candidates.append(raw_test_path.parent / recorded)

    if fallback_relative:
        candidates.append(run_dir / fallback_relative)

    seen: set[Path] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        try:
            key = candidate.resolve(strict=False)
        except OSError:
            key = candidate
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)

    for candidate in unique_candidates:
        if candidate.exists():
            return candidate, warnings

    if recorded_path or fallback_relative:
        attempted = ", ".join(str(p) for p in unique_candidates)
        warnings.append(f"artifact not found; tried: {attempted}")
    return None, warnings


def resolve_header_metadata(
    run_dir: Path,
    summary: dict[str, Any],
    tests: dict[str, RawTest],
    overrides: argparse.Namespace,
) -> HeaderMetadata:
    metadata_path = run_dir / "report-metadata.json"
    metadata = load_json(metadata_path) if metadata_path.exists() else {}

    fpgaid = tests.get("test-fpgaid-read")
    version = tests.get("test-version-read")
    iocversion = tests.get("test-iocversion-read")
    serial = tests.get("test-display-serial-read")

    fpga_display_model = get_nested(fpgaid.data, "environment", "display_model", default="") if fpgaid else ""
    display_model = str(metadata.get("display_model") or summary.get("display_model") or fpga_display_model or "")
    display_size = str(
        metadata.get("display_size")
        or (get_nested(fpgaid.data, "data", "disp_size") if fpgaid else None)
        or derive_display_size(display_model)
        or "TBD"
    )
    display_resolution = str(
        metadata.get("display_resolution")
        or (get_nested(fpgaid.data, "data", "disp_resolution") if fpgaid else None)
        or "TBD"
    )

    display_serial_number = str(
        overrides.serial_number
        or metadata.get("display_serial_number")
        or (get_nested(serial.data, "data", "serial_number") if serial else None)
        or "DUMMY-SERIAL-NUMBER"
    )

    fpga_sw_version = str(
        metadata.get("fpga_sw_version")
        or (get_nested(version.data, "data", "version") if version else None)
        or "DUMMY-FPGA-VERSION"
    )
    fpga_companion_parts = []
    if version:
        build_date = get_nested(version.data, "data", "date")
        binary = get_nested(version.data, "data", "binary")
        if build_date:
            fpga_companion_parts.append(str(build_date))
        if binary:
            fpga_companion_parts.append(f"bin {binary}")
    fpga_companion = " / ".join(fpga_companion_parts)

    mcu_sw_version = str(
        metadata.get("mcu_sw_version")
        or (get_nested(iocversion.data, "data", "fw_version") if iocversion else None)
        or "N/A"
    )

    tester_version = (
        overrides.tester_version
        or metadata.get("tester_version")
        or summary.get("framework_version")
        or resolve_framework_version(tests)
        or "DUMMY-TESTER-VERSION"
    )

    return HeaderMetadata(
        run_id=str(metadata.get("run_id") or summary.get("run_id") or run_dir.name),
        timestamp=str(metadata.get("test_timestamp") or summary.get("timestamp") or "TBD"),
        display_model=display_model or "TBD",
        display_size=display_size,
        display_resolution=display_resolution,
        display_serial_number=display_serial_number,
        fpga_sw_version=fpga_sw_version,
        fpga_companion=fpga_companion,
        mcu_sw_version=str(non_empty_value(mcu_sw_version)),
        tester_version=str(non_empty_value(tester_version)),
    )


def non_empty_value(value: Any) -> str:
    if value is None or value == "":
        return "TBD"
    return str(value)


def resolve_framework_version(tests: dict[str, RawTest]) -> str | None:
    versions = {
        str(get_nested(test.data, "environment", "framework_version", default=""))
        for test in tests.values()
    }
    versions.discard("")
    if len(versions) == 1:
        return f"display-test-framework {next(iter(versions))}"
    if versions:
        return "mixed framework versions"
    return None


def extract_status_rows(tests: dict[str, RawTest]) -> list[StatusRow]:
    def sort_key(test: RawTest) -> tuple[int, str]:
        category_order = {"unit": 0, "integration": 1, "validation": 2}
        return (category_order.get(test.category, 9), test.name)

    return [
        StatusRow(
            name=test.name,
            category=test.category,
            result=test.result,
            note=build_status_note(test),
        )
        for test in sorted(tests.values(), key=sort_key)
    ]


def build_status_note(test: RawTest) -> str:
    errors = test.data.get("errors") or []
    data = test.data.get("data") or {}

    if test.name == "test-i2c-flood":
        total = as_int(data.get("total_operations"))
        failed = as_int(data.get("failed_operations"))
        if total is not None and failed is not None:
            if failed > 0:
                return f"{failed}/{total} failed"
            return f"{total - failed}/{total} ops ok"

    if test.name == "test-ioc-i2c-flood":
        total = as_int(data.get("total_operations"))
        failed = as_int(data.get("failed_operations"), 0)
        if total is not None:
            return f"{total - (failed or 0)}/{total} ops ok"

    if test.name == "test-brightness-linearity":
        passed = as_int(data.get("passed_points"))
        total = as_int(data.get("total_points"))
        if passed is not None and total is not None:
            return f"{passed}/{total} points"

    if test.name == "test-brightness-calibration":
        collected = as_int(data.get("samples_collected"))
        total = as_int(data.get("total_samples"))
        if collected is not None and total is not None:
            note = f"{collected}/{total} samples"
            if data.get("from_cache") is True:
                note += " cache"
            return note
        if total is not None:
            return f"{total} samples"

    if test.name == "test-brightness-nits-verify":
        note = build_brightness_nits_verify_note(test)
        if note:
            return note

    if test.name == "test-color-gamut":
        successful = as_int(data.get("successful_colors"))
        total = as_int(data.get("total_colors"))
        if successful is not None and total is not None:
            return f"{successful}/{total} colors"

    if test.name == "test-contrast-sequential":
        measurements = data.get("contrast_measurements") or []
        expected = data.get("brightness_levels") or []
        if expected:
            return f"{len(measurements)}/{len(expected)} levels"

    if test.name == "test-gamma-curve":
        gamma = as_float(data.get("gamma"))
        patches = as_int(data.get("num_patches"))
        if gamma is not None and patches is not None:
            return f"gamma {gamma:.3f}, {patches} patches"

    if test.name == "test-local-dimming-apl":
        collected = as_int(data.get("samples_collected"))
        attempted = as_int(data.get("samples_attempted"))
        skipped = as_int(data.get("samples_skipped"), 0) or 0
        if collected is not None and attempted is not None:
            note = f"{collected}/{attempted} APL"
            if skipped:
                note += f", {skipped} skip"
            return note

    if test.name == "test-fpgaid-read":
        resolution = data.get("disp_resolution")
        size = data.get("disp_size")
        if resolution or size:
            return " ".join(str(part) for part in (size, resolution) if part)

    if test.name == "test-version-read":
        version = data.get("version")
        date = data.get("date")
        if version:
            return f"{version} {date or ''}".strip()

    if test.name == "test-iocversion-read":
        version = data.get("fw_version")
        if version:
            return str(version)

    if errors:
        return shorten(str(errors[0]), 46)

    if test.result == "SKIP":
        return "skipped"
    return ""


def build_brightness_nits_verify_note(test: RawTest) -> str:
    note = brightness_nits_verify_note_from_artifact(test)
    if note:
        return note
    return brightness_nits_verify_note_from_log(test)


def brightness_nits_verify_note_from_artifact(test: RawTest) -> str:
    run_dir = test.path.parent.parent
    recorded_json = str(get_nested(test.data, "data", "nits_verify_json", default="") or "")
    artifact_path, _warnings = resolve_artifact_path(
        run_dir,
        test.path,
        recorded_json,
        "artifacts/brightness-nits-verify.json",
    )
    if artifact_path is None:
        return ""
    try:
        artifact = load_json(artifact_path)
    except (OSError, json.JSONDecodeError):
        return ""

    peak = brightness_nits_verify_peak_sample(artifact.get("samples") or [])
    if peak is None:
        return ""
    peak_delta, peak_brightness = peak
    failed = as_int(artifact.get("samples_failed"))
    compared = as_int(artifact.get("samples_compared"))
    return format_brightness_nits_verify_note(peak_delta, peak_brightness, failed, compared)


def brightness_nits_verify_peak_sample(samples: list[Any]) -> tuple[float, float | None] | None:
    peak_delta: float | None = None
    peak_brightness: float | None = None
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        delta = as_float(sample.get("delta_pct"))
        if delta is None:
            continue
        abs_delta = abs(delta)
        if peak_delta is None or abs_delta > peak_delta:
            peak_delta = abs_delta
            peak_brightness = as_float(sample.get("brightness_percent"))
    if peak_delta is None:
        return None
    return peak_delta, peak_brightness


def brightness_nits_verify_note_from_log(test: RawTest) -> str:
    log_path = test.path.with_suffix(".log")
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    current_brightness: float | None = None
    peak_delta: float | None = None
    peak_brightness: float | None = None
    compared = 0
    failed = 0
    brightness_pattern = re.compile(r"Brightness\s+([0-9.]+)%")
    delta_pattern = re.compile(r"\b(PASS|FAIL):.*?\bdelta=([0-9.]+)%")
    for line in lines:
        brightness_match = brightness_pattern.search(line)
        if brightness_match:
            current_brightness = as_float(brightness_match.group(1))
        delta_match = delta_pattern.search(line)
        if not delta_match:
            continue
        delta = as_float(delta_match.group(2))
        if delta is None:
            continue
        compared += 1
        if delta_match.group(1) == "FAIL":
            failed += 1
        if peak_delta is None or delta > peak_delta:
            peak_delta = delta
            peak_brightness = current_brightness
    if peak_delta is None:
        return ""
    return format_brightness_nits_verify_note(peak_delta, peak_brightness, failed, compared)


def format_brightness_nits_verify_note(
    peak_delta: float,
    peak_brightness: float | None,
    failed: int | None,
    compared: int | None,
) -> str:
    brightness = f"@{peak_brightness:g}%" if peak_brightness is not None else ""
    note = f"max {peak_delta:.2f}%{brightness}"
    if failed and failed > 0 and compared:
        note += f",{failed}/{compared}"
    return note


def comparison_status_rows(run: RunData, base_run: RunData | None) -> list[StatusRow]:
    if base_run is None:
        return run.status_rows
    base_rows = {row.name: row for row in base_run.status_rows}
    rows: list[StatusRow] = []
    for row in run.status_rows:
        note = row.note
        base_row = base_rows.get(row.name)
        if base_row is None:
            note = f"new; {note}" if note else "new"
        elif base_row.result != row.result:
            note = f"was {base_row.result}; {note}" if note else f"was {base_row.result}"
        rows.append(StatusRow(name=row.name, category=row.category, result=row.result, note=note))
    return rows


def extract_brightness(run_dir: Path, tests: dict[str, RawTest]) -> tuple[BrightnessCurve | None, list[str]]:
    warnings: list[str] = []
    calibration = extract_brightness_calibration(run_dir, tests, warnings)
    if calibration is not None:
        return calibration, warnings
    return extract_brightness_linearity(tests), warnings


def extract_brightness_calibration(
    run_dir: Path,
    tests: dict[str, RawTest],
    warnings: list[str],
) -> BrightnessCurve | None:
    test = tests.get("test-brightness-calibration")
    if not test:
        return None

    recorded_json = str(get_nested(test.data, "data", "calibration_json", default="") or "")
    artifact_path, path_warnings = resolve_artifact_path(
        run_dir,
        test.path,
        recorded_json,
        "artifacts/brightness-calibration-81step.json",
    )
    if recorded_json or artifact_path is not None:
        warnings.extend(path_warnings)
    if artifact_path is None:
        return None

    try:
        artifact = load_json(artifact_path)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"could not load brightness calibration artifact {artifact_path}: {exc}")
        return None

    samples = artifact.get("samples") or []
    brightness: list[float] = []
    luminance: list[float] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        x = as_float(sample.get("brightness_percent"))
        y = as_float(sample.get("Y_luminance"))
        if x is None or y is None:
            continue
        brightness.append(x)
        luminance.append(y)

    if not brightness:
        warnings.append(f"no usable brightness calibration samples in {artifact_path}")
        return None

    return BrightnessCurve(
        source=str(artifact_path.relative_to(run_dir) if artifact_path.is_relative_to(run_dir) else artifact_path),
        brightness_percent=brightness,
        luminance=luminance,
        sample_count=len(brightness),
        complete=bool(artifact.get("complete")) if "complete" in artifact else None,
        from_cache=bool(artifact.get("from_cache")) if "from_cache" in artifact else None,
    )


def extract_brightness_linearity(tests: dict[str, RawTest]) -> BrightnessCurve | None:
    test = tests.get("test-brightness-linearity")
    if not test:
        return None

    samples = get_nested(test.data, "data", "measured_data", default=[]) or []
    brightness: list[float] = []
    luminance: list[float] = []
    expected: list[float] = []
    for sample in samples:
        x = as_float(sample.get("brightness_percent"))
        y = as_float(sample.get("luminance"))
        ey = as_float(sample.get("expected_luminance"))
        if x is None or y is None:
            continue
        brightness.append(x)
        luminance.append(y)
        if ey is not None:
            expected.append(ey)

    if not brightness:
        return None
    return BrightnessCurve(
        source="test-brightness-linearity",
        brightness_percent=brightness,
        luminance=luminance,
        expected_luminance=expected if len(expected) == len(brightness) else [],
        sample_count=len(brightness),
    )


def parse_gamma_csv(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            if line.lstrip().startswith("#"):
                parse_comment_metadata(line, metadata)
            else:
                data_lines.append(line)
    reader = csv.DictReader(data_lines)
    return metadata, [row for row in reader]


def parse_comment_csv(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            if line.lstrip().startswith("#"):
                parse_comment_metadata(line, metadata)
            elif line.strip():
                data_lines.append(line)
    if not data_lines:
        return metadata, []
    reader = csv.DictReader(data_lines)
    return metadata, [row for row in reader]


def parse_comment_metadata(line: str, metadata: dict[str, str]) -> None:
    body = line.lstrip("#").strip()
    if not body:
        return
    for fragment in body.split(","):
        part = fragment.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        metadata[key.strip()] = value.strip()


def extract_gamma(run_dir: Path, tests: dict[str, RawTest]) -> tuple[GammaCurve | None, list[str]]:
    warnings: list[str] = []
    test = tests.get("test-gamma-curve") or tests.get("test-gamma-grayscale")
    if not test:
        return None, warnings

    recorded_csv = str(get_nested(test.data, "data", "csv_path", default="") or "")
    artifact_path, path_warnings = resolve_artifact_path(
        run_dir,
        test.path,
        recorded_csv,
        "artifacts/gamma_curve_test-gamma-curve.csv",
    )
    warnings.extend(path_warnings)
    if artifact_path is None:
        return None, warnings

    _metadata, rows = parse_gamma_csv(artifact_path)
    code: list[float] = []
    luminance: list[float] = []
    y_std: list[float] = []
    x_chrom: list[float] = []
    y_chrom: list[float] = []
    for row in rows:
        if row.get("status", "").strip().upper() != "OK":
            continue
        c = as_float(row.get("code"))
        y = as_float(row.get("Y_mean"))
        if c is None or y is None:
            continue
        code.append(c)
        luminance.append(y)
        y_std.append(as_float(row.get("Y_std"), 0.0) or 0.0)
        x_chrom.append(as_float(row.get("x_mean"), math.nan) or math.nan)
        y_chrom.append(as_float(row.get("y_mean"), math.nan) or math.nan)

    if len(code) < 3:
        warnings.append(f"too few gamma rows in {artifact_path}")
        return None, warnings

    code_arr = np.asarray(code, dtype=float)
    lum_arr = np.asarray(luminance, dtype=float)
    y_std_arr = np.asarray(y_std, dtype=float)
    x_arr = np.asarray(x_chrom, dtype=float)
    y_arr = np.asarray(y_chrom, dtype=float)

    y_black = as_float(get_nested(test.data, "data", "y_black_nits"), float(np.nanmin(lum_arr)))
    y_max = as_float(get_nested(test.data, "data", "y_max_nits"), float(np.nanmax(lum_arr)))
    if y_black is None:
        y_black = float(np.nanmin(lum_arr))
    if y_max is None:
        y_max = float(np.nanmax(lum_arr))
    denom = y_max - y_black
    if denom <= 0:
        warnings.append("gamma normalization denominator is not positive")
        norm_lum = np.zeros_like(lum_arr)
    else:
        norm_lum = (lum_arr - y_black) / denom

    norm_input = code_arr / 255.0
    gamma = as_float(get_nested(test.data, "data", "gamma"))
    if gamma is None:
        gamma = fit_gamma(norm_input, norm_lum)

    endpoint_drift = None
    if denom > 0:
        code_255_indexes = np.where(code_arr == 255)[0]
        if len(code_255_indexes):
            endpoint_drift = (norm_lum[code_255_indexes[-1]] - 1.0) * 100.0

    return (
        GammaCurve(
            source=str(artifact_path.relative_to(run_dir) if artifact_path.is_relative_to(run_dir) else artifact_path),
            code=code_arr,
            normalized_input=norm_input,
            luminance=lum_arr,
            normalized_luminance=norm_lum,
            y_std=y_std_arr,
            x_chromaticity=x_arr,
            y_chromaticity=y_arr,
            gamma=gamma,
            rms_gamma=as_float(get_nested(test.data, "data", "rms_residual_gamma")),
            rms_srgb=as_float(get_nested(test.data, "data", "rms_residual_srgb")),
            y_black=y_black,
            y_max=y_max,
            endpoint_drift_percent=endpoint_drift,
            samples_per_patch=as_int(get_nested(test.data, "data", "samples_per_patch")),
            warnings=warnings.copy(),
        ),
        warnings,
    )


def extract_thermal_profile(run_dir: Path) -> tuple[ThermalLuminanceProfile | None, list[str]]:
    warnings: list[str] = []
    profile_path = run_dir / "raw" / "thermal-luminance-profile.csv"
    if not profile_path.exists():
        return None, warnings

    try:
        metadata, rows = parse_comment_csv(profile_path)
    except OSError as exc:
        warnings.append(f"could not load thermal luminance profile {profile_path}: {exc}")
        return None, warnings

    samples: list[ThermalLuminanceSample] = []
    for idx, row in enumerate(rows, start=1):
        luminance = as_float(row.get("Y"))
        x_chrom = as_float(row.get("x"))
        y_chrom = as_float(row.get("y"))
        if luminance is None or x_chrom is None or y_chrom is None:
            continue
        samples.append(
            ThermalLuminanceSample(
                index=as_int(row.get("sample_index"), idx) or idx,
                timestamp=str(row.get("timestamp") or ""),
                elapsed_seconds=as_float(row.get("elapsed_seconds")),
                luminance=luminance,
                x_chromaticity=x_chrom,
                y_chromaticity=y_chrom,
                backlight_temp_c=as_float(row.get("backlight_temp_c")),
            )
        )

    if not samples:
        warnings.append(f"no usable thermal luminance samples in {profile_path}")
        return None, warnings

    return (
        ThermalLuminanceProfile(
            source=str(profile_path.relative_to(run_dir) if profile_path.is_relative_to(run_dir) else profile_path),
            metadata=metadata,
            samples=samples,
        ),
        warnings,
    )


def fit_gamma(normalized_input: np.ndarray, normalized_luminance: np.ndarray) -> float | None:
    xs: list[float] = []
    ys: list[float] = []
    for x, y in zip(normalized_input, normalized_luminance):
        if x <= 0 or y <= 0:
            continue
        xs.append(math.log(float(x)))
        ys.append(math.log(float(y)))
    if len(xs) < 3:
        return None
    slope, _intercept = np.polyfit(np.asarray(xs), np.asarray(ys), 1)
    return float(slope)


def extract_contrast(tests: dict[str, RawTest]) -> ContrastCurve | None:
    test = tests.get("test-contrast-sequential")
    if not test:
        return None
    data = test.data.get("data") or {}
    measurements = data.get("contrast_measurements") or []
    brightness: list[float] = []
    ratios: list[float] = []
    displays: list[str] = []
    lower_bounds: list[bool] = []
    for sample in measurements:
        level = as_float(sample.get("brightness"))
        ratio = as_float(sample.get("contrast_ratio"))
        if level is None or ratio is None:
            continue
        brightness.append(level)
        ratios.append(ratio)
        displays.append(str(sample.get("contrast_ratio_display") or f"{ratio:.1f}"))
        lower_bounds.append(bool(sample.get("below_detection_threshold")))
    if not brightness:
        return None
    expected = [float(v) for v in data.get("brightness_levels", []) if as_float(v) is not None]
    return ContrastCurve(
        source="test-contrast-sequential",
        expected_levels=expected,
        brightness=brightness,
        contrast_ratio=ratios,
        contrast_display=displays,
        lower_bound=lower_bounds,
        result=test.result,
        errors=[str(error) for error in (test.data.get("errors") or [])],
    )


def extract_local_dimming_apl(
    run_dir: Path,
    tests: dict[str, RawTest],
) -> tuple[LocalDimmingAplCurve | None, list[str]]:
    warnings: list[str] = []
    test = tests.get("test-local-dimming-apl")
    if not test:
        return None, warnings

    recorded_json = str(get_nested(test.data, "data", "apl_json", default="") or "")
    artifact_path, path_warnings = resolve_artifact_path(
        run_dir,
        test.path,
        recorded_json,
        "artifacts/local-dimming-apl-sweep.json",
    )
    warnings.extend(path_warnings)
    if artifact_path is None:
        return None, warnings

    try:
        artifact = load_json(artifact_path)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"could not load local dimming APL artifact {artifact_path}: {exc}")
        return None, warnings

    schema_version = str(artifact.get("schema_version") or "")
    if schema_version and schema_version != "1.0":
        warnings.append(f"unsupported local dimming APL schema {schema_version}; attempting best effort parse")

    samples: list[LocalDimmingAplSample] = []
    for idx, sample in enumerate(artifact.get("samples") or [], start=1):
        if not isinstance(sample, dict):
            continue
        apl = as_float(sample.get("apl_percent"))
        if apl is None:
            continue
        luminance = as_float(sample.get("Y_luminance"))
        fits_screen = bool(sample.get("fits_screen")) and luminance is not None
        samples.append(
            LocalDimmingAplSample(
                index=as_int(sample.get("index"), idx) or idx,
                apl_percent=apl,
                box_side_mm=as_float(sample.get("box_side_mm")),
                fits_screen=fits_screen,
                luminance=luminance if fits_screen else None,
                x_chromaticity=as_float(sample.get("x_chromaticity")),
                y_chromaticity=as_float(sample.get("y_chromaticity")),
                skip_reason=str(sample.get("skip_reason") or ""),
                timestamp=str(sample.get("timestamp") or ""),
            )
        )

    if not samples:
        warnings.append(f"no usable local dimming APL samples in {artifact_path}")
        return None, warnings

    return (
        LocalDimmingAplCurve(
            source=str(artifact_path.relative_to(run_dir) if artifact_path.is_relative_to(run_dir) else artifact_path),
            display_model=str(artifact.get("display_model") or get_nested(test.data, "environment", "display_model", default="") or ""),
            complete=bool(artifact.get("complete")) if "complete" in artifact else None,
            artifact_generated_timestamp=str(artifact.get("artifact_generated_timestamp") or ""),
            backlight_percent=as_float(artifact.get("backlight_percent")),
            samples_attempted=as_int(artifact.get("samples_attempted")),
            samples_collected=as_int(artifact.get("samples_collected")),
            samples_skipped=as_int(artifact.get("samples_skipped")),
            samples=samples,
        ),
        warnings,
    )


def polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for idx, point in enumerate(points):
        next_point = points[(idx + 1) % len(points)]
        total += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(total) * 0.5


def signed_polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for idx, point in enumerate(points):
        next_point = points[(idx + 1) % len(points)]
        total += point[0] * next_point[1] - next_point[0] * point[1]
    return total * 0.5


def clip_polygon_to_convex(
    subject: list[tuple[float, float]],
    clip: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Sutherland-Hodgman polygon clipping for convex clip polygons."""
    if len(subject) < 3 or len(clip) < 3:
        return []

    orientation = 1.0 if signed_polygon_area(clip) >= 0 else -1.0
    output = subject[:]

    def cross(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])

    def inside(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
        return orientation * cross(a, b, p) >= -1e-12

    def intersection(
        s: tuple[float, float],
        e: tuple[float, float],
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> tuple[float, float]:
        x1, y1 = s
        x2, y2 = e
        x3, y3 = a
        x4, y4 = b
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return e
        px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
        py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
        return (px, py)

    for idx, a in enumerate(clip):
        b = clip[(idx + 1) % len(clip)]
        input_list = output
        output = []
        if not input_list:
            break
        s = input_list[-1]
        for e in input_list:
            if inside(e, a, b):
                if not inside(s, a, b):
                    output.append(intersection(s, e, a, b))
                output.append(e)
            elif inside(s, a, b):
                output.append(intersection(s, e, a, b))
            s = e
    return output


def white_tolerance_distance(
    measured: tuple[float, float],
    reference: tuple[float, float],
    tolerance: float,
) -> float | None:
    if tolerance <= 0:
        return None
    dx = measured[0] - reference[0]
    dy = measured[1] - reference[1]
    minor_axis = tolerance
    major_axis = tolerance * 1.2
    return math.sqrt((dx / minor_axis) ** 2 + (dy / major_axis) ** 2)


def extract_gamut(tests: dict[str, RawTest], reference_gamut: str) -> GamutMetrics | None:
    test = tests.get("test-color-gamut")
    if not test:
        return None
    reference = REFERENCE_GAMUTS.get(reference_gamut, REFERENCE_GAMUTS["ntsc"])
    points: dict[str, tuple[float, float]] = {}
    color_backlight_temps: dict[str, float] = {}
    white_luminance: float | None = None
    white_point: tuple[float, float] | None = None
    data = get_nested(test.data, "data", default={}) or {}

    for sample in data.get("gamut_data", []) or []:
        color = str(sample.get("color", "")).upper()
        x = as_float(sample.get("x_chromaticity"))
        y = as_float(sample.get("y_chromaticity"))
        if color and x is not None and y is not None:
            points[color] = (x, y)
        temp_c = as_float(sample.get("backlight_temp_c"))
        if color and temp_c is not None:
            color_backlight_temps[color] = temp_c
        if color == "W":
            white_luminance = as_float(sample.get("Y_luminance"))
            if x is not None and y is not None:
                white_point = (x, y)

    if not points:
        return None
    reference_points = {
        "R": reference["r"],
        "G": reference["g"],
        "B": reference["b"],
    }

    measured_area: float | None = None
    reference_area: float | None = None
    overlap_area: float | None = None
    coverage_percent: float | None = None
    relative_area_percent: float | None = None
    if all(color in points for color in ("R", "G", "B")):
        measured_triangle = [points["R"], points["G"], points["B"]]
        reference_triangle = [reference_points["R"], reference_points["G"], reference_points["B"]]
        measured_area = polygon_area(measured_triangle)
        reference_area = polygon_area(reference_triangle)
        overlap = clip_polygon_to_convex(measured_triangle, reference_triangle)
        overlap_area = polygon_area(overlap)
        if reference_area > 0:
            coverage_percent = overlap_area / reference_area * 100.0
            relative_area_percent = measured_area / reference_area * 100.0

    white_delta: tuple[float, float] | None = None
    tolerance_distance: float | None = None
    within_tolerance: bool | None = None
    if white_point:
        reference_white = reference["w"]
        white_delta = (white_point[0] - reference_white[0], white_point[1] - reference_white[1])
        tolerance_distance = white_tolerance_distance(white_point, reference_white, DEFAULT_WHITE_TOLERANCE)
        if tolerance_distance is not None:
            within_tolerance = tolerance_distance <= 1.0

    return GamutMetrics(
        source="test-color-gamut",
        points=points,
        white_luminance=white_luminance,
        white_point=white_point,
        reference_name=str(reference["name"]),
        reference_white=reference["w"],
        reference_white_name=str(reference.get("white_name", "white")),
        reference_points=reference_points,
        measured_area=measured_area,
        reference_area=reference_area,
        overlap_area=overlap_area,
        coverage_percent=coverage_percent,
        relative_area_percent=relative_area_percent,
        white_delta=white_delta,
        white_tolerance=DEFAULT_WHITE_TOLERANCE,
        white_tolerance_distance=tolerance_distance,
        white_within_tolerance=within_tolerance,
        backlight_temp_c_start=as_float(data.get("backlight_temp_c_start")),
        backlight_temp_c_end=as_float(data.get("backlight_temp_c_end")),
        backlight_temp_c_avg=as_float(data.get("backlight_temp_c_avg")),
        backlight_temp_source=str(data.get("backlight_temp_source") or ""),
        color_backlight_temps=color_backlight_temps,
    )


def load_run_folder(run_dir: Path, args: argparse.Namespace) -> RunData:
    warnings: list[str] = []
    run_dir = run_dir.resolve()
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"missing required file: {summary_path}")

    summary = load_json(summary_path)
    tests = discover_tests(run_dir, warnings)
    header = resolve_header_metadata(run_dir, summary, tests, args)
    status_rows = extract_status_rows(tests)
    brightness, brightness_warnings = extract_brightness(run_dir, tests)
    warnings.extend(brightness_warnings)
    gamma, gamma_warnings = extract_gamma(run_dir, tests)
    warnings.extend(gamma_warnings)
    contrast = extract_contrast(tests)
    gamut = extract_gamut(tests, args.reference_gamut)
    local_dimming_apl, apl_warnings = extract_local_dimming_apl(run_dir, tests)
    warnings.extend(apl_warnings)
    thermal_profile, thermal_warnings = extract_thermal_profile(run_dir)
    warnings.extend(thermal_warnings)

    return RunData(
        run_dir=run_dir,
        summary=summary,
        tests=tests,
        header=header,
        status_rows=status_rows,
        brightness=brightness,
        gamma=gamma,
        contrast=contrast,
        gamut=gamut,
        local_dimming_apl=local_dimming_apl,
        thermal_profile=thermal_profile,
        warnings=warnings,
    )


def format_fpga_label(run: RunData) -> str:
    version = run.header.fpga_sw_version.strip()
    if version.startswith("DUMMY") or version == "TBD":
        version = ""
    companion = run.header.fpga_companion.split("/", 1)[0].strip()
    companion = (
        companion.replace("January", "Jan")
        .replace("February", "Feb")
        .replace("March", "Mar")
        .replace("April", "Apr")
        .replace("June", "Jun")
        .replace("July", "Jul")
        .replace("August", "Aug")
        .replace("September", "Sep")
        .replace("October", "Oct")
        .replace("November", "Nov")
        .replace("December", "Dec")
    )
    label = " ".join(part for part in (version, companion) if part)
    return label or shorten(run.header.run_id, 18)


def series_labels(
    run: RunData,
    base_run: RunData | None,
    run_label: str | None = None,
    base_label: str | None = None,
) -> SeriesLabels:
    return SeriesLabels(
        run=run_label or (f"run {format_fpga_label(run)}" if base_run else "measured"),
        base=base_label or (f"base {format_fpga_label(base_run)}" if base_run else "base"),
    )


def render_report_card(
    run: RunData,
    output: Path,
    title: str,
    dpi: int,
    reference_gamut: str,
    render_mode: str,
    base_run: RunData | None = None,
    run_label: str | None = None,
    base_label: str | None = None,
) -> None:
    fig = plt.figure(figsize=A4_LANDSCAPE_INCHES, dpi=dpi, facecolor="white")
    grid = fig.add_gridspec(
        4,
        2,
        width_ratios=[1.08, 1.42],
        height_ratios=[0.50, 0.40, 6.55, 0.20],
        left=0.035,
        right=0.985,
        top=0.985,
        bottom=0.018,
        wspace=0.13,
        hspace=0.09,
    )

    ax_header = fig.add_subplot(grid[0, :])
    ax_kpi = fig.add_subplot(grid[1, :])
    ax_matrix = fig.add_subplot(grid[2, 0])
    chart_grid = grid[2, 1].subgridspec(3, 2, height_ratios=[1.0, 1.0, 0.95], wspace=0.27, hspace=0.46)
    ax_brightness = fig.add_subplot(chart_grid[0, 0])
    ax_gamma = fig.add_subplot(chart_grid[0, 1])
    ax_contrast = fig.add_subplot(chart_grid[1, 0])
    ax_gamut = fig.add_subplot(chart_grid[1, 1])
    has_thermal_profile = run.thermal_profile is not None or (base_run is not None and base_run.thermal_profile is not None)
    ax_local_dimming_apl = fig.add_subplot(chart_grid[2, 0] if has_thermal_profile else chart_grid[2, :])
    ax_thermal = fig.add_subplot(chart_grid[2, 1]) if has_thermal_profile else None
    ax_footer = fig.add_subplot(grid[3, :])

    labels = series_labels(run, base_run, run_label, base_label)
    render_header(ax_header, run, title, base_run)
    render_kpis(ax_kpi, run)
    render_status_matrix(ax_matrix, comparison_status_rows(run, base_run))
    render_brightness(ax_brightness, run.brightness, base_run.brightness if base_run else None, labels)
    render_gamma(ax_gamma, run.gamma, base_run.gamma if base_run else None, labels)
    render_contrast(ax_contrast, run.contrast, base_run.contrast if base_run else None, labels)
    render_gamut(ax_gamut, run.gamut, reference_gamut, render_mode, run.warnings, base_run.gamut if base_run else None, labels)
    render_local_dimming_apl(
        ax_local_dimming_apl,
        run.local_dimming_apl,
        base_run.local_dimming_apl if base_run else None,
        labels,
        compact=has_thermal_profile,
    )
    if ax_thermal is not None:
        render_thermal_white_point_drift(
            ax_thermal,
            run.thermal_profile,
            base_run.thermal_profile if base_run else None,
            labels,
        )
    render_footer(ax_footer, run, base_run)

    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)
    for ax in fig.axes:
        ax.patch.set_alpha(1.0)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, facecolor="white", edgecolor="white", transparent=False)
    plt.close(fig)


def render_header(ax: plt.Axes, run: RunData, title: str, base_run: RunData | None = None) -> None:
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, color="#F2F5F8", zorder=0))
    header = run.header
    display_title = "Display Compare Report" if base_run and title == "Display Test Report Card" else title
    run_id_text = header.run_id
    if base_run:
        run_id_text = f"run {header.run_id}  |  base {base_run.header.run_id}"
    ax.text(0.014, 0.66, display_title, fontsize=13.2 if base_run else 15.5, weight="bold", color="#17202A", transform=ax.transAxes)
    ax.text(0.014, 0.24, run_id_text, fontsize=7.6 if base_run else 8.8, color="#44515F", transform=ax.transAxes)

    row1 = [
        ("Timestamp", format_timestamp(header.timestamp)),
        ("Display", f"{header.display_size}  {header.display_resolution}"),
        ("Model", header.display_model),
    ]
    row2 = [
        ("Serial", header.display_serial_number),
        ("FPGA", f"{format_fpga_label(base_run)} -> {format_fpga_label(run)}" if base_run else f"{header.fpga_sw_version} {header.fpga_companion}".strip()),
        ("MCU", header.mcu_sw_version),
        ("Tester", header.tester_version),
    ]
    for (label, value), x in zip(row1, [0.31, 0.49, 0.64]):
        ax.text(x, 0.73, label, fontsize=6.4, color="#6B7682", transform=ax.transAxes)
        ax.text(x, 0.52, shorten(value, 26), fontsize=8.0, color="#1C2733", transform=ax.transAxes)
    for (label, value), x in zip(row2, [0.31, 0.49, 0.64, 0.76]):
        if label == "Tester":
            value = value.replace("display-test-framework", "framework")
        ax.text(x, 0.31, label, fontsize=6.4, color="#6B7682", transform=ax.transAxes)
        ax.text(x, 0.11, shorten(value, 24), fontsize=8.0, color="#1C2733", transform=ax.transAxes)


def render_kpis(ax: plt.Axes, run: RunData) -> None:
    ax.axis("off")
    passed = as_int(run.summary.get("passed"), 0) or 0
    failed = as_int(run.summary.get("failed"), 0) or 0
    skipped = as_int(run.summary.get("skipped"), 0) or 0
    errors = as_int(run.summary.get("errors"), 0) or 0
    executed = passed + failed + errors
    pass_rate = passed / executed * 100.0 if executed else 0.0
    total = as_int(run.summary.get("total_tests"), len(run.status_rows)) or len(run.status_rows)
    overall = "PASS" if failed == 0 and errors == 0 else "ATTENTION"
    tiles = [
        (f"Overall ({total} tests)", overall, "#1B8A5A" if overall == "PASS" else "#C9342F"),
        ("Passed", str(passed), STATUS_COLORS["PASS"]),
        ("Failed", str(failed), STATUS_COLORS["FAIL"]),
        ("Errors", str(errors), STATUS_COLORS["ERROR"]),
        ("Skipped", str(skipped), STATUS_COLORS["SKIP"]),
        ("Executed Pass Rate", f"{pass_rate:.1f}%", "#245A92"),
    ]
    gap = 0.012
    tile_w = (1.0 - gap * (len(tiles) - 1)) / len(tiles)
    for idx, (label, value, color) in enumerate(tiles):
        x = idx * (tile_w + gap)
        ax.add_patch(
            Rectangle((x, 0.06), tile_w, 0.88, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor="#D9E0E7", linewidth=0.8)
        )
        ax.text(x + 0.02, 0.58, value, fontsize=14, weight="bold", color=color, va="center", transform=ax.transAxes)
        ax.text(x + 0.02, 0.24, label, fontsize=7.5, color="#586472", va="center", transform=ax.transAxes)


def render_status_matrix(ax: plt.Axes, rows: list[StatusRow]) -> None:
    ax.set_title("Test Matrix", loc="left", fontsize=10, weight="bold", pad=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    header_h = 0.052
    row_h = (0.97 - header_h) / max(len(rows), 1)
    columns = [
        ("Test", 0.02, 0.47),
        ("Category", 0.48, 0.16),
        ("Result", 0.65, 0.13),
        ("Note", 0.78, 0.20),
    ]
    ax.add_patch(Rectangle((0, 1 - header_h), 1, header_h, facecolor="#EDF2F6", edgecolor="#D3DCE5", linewidth=0.8))
    for label, x, _width in columns:
        ax.text(x, 1 - header_h / 2, label, va="center", fontsize=7.2, weight="bold", color="#3B4652")

    for idx, row in enumerate(rows):
        y_top = 1 - header_h - idx * row_h
        y = y_top - row_h
        changed = row.note.startswith("was ") or row.note.startswith("new")
        bg = "#FFF7E6" if changed else ("#FFFFFF" if idx % 2 == 0 else "#F8FAFC")
        ax.add_patch(Rectangle((0, y), 1, row_h, facecolor=bg, edgecolor="#E4E9EF", linewidth=0.45))
        if changed:
            ax.add_patch(Rectangle((0, y), 0.006, row_h, facecolor="#D99028", edgecolor="#D99028", linewidth=0))
        ax.text(0.02, y + row_h * 0.52, shorten(row.name.replace("test-", ""), 30), va="center", fontsize=6.45, color="#18222D")
        ax.text(0.48, y + row_h * 0.52, row.category, va="center", fontsize=6.1, color="#5C6875")

        color = STATUS_COLORS.get(row.result, "#5B6472")
        ax.add_patch(Rectangle((0.65, y + row_h * 0.22), 0.105, row_h * 0.56, facecolor=color, edgecolor=color, linewidth=0))
        ax.text(0.702, y + row_h * 0.51, row.result, ha="center", va="center", fontsize=5.6, color="white", weight="bold")
        ax.text(0.78, y + row_h * 0.52, shorten(row.note, 24), va="center", fontsize=5.6, color="#47515D", clip_on=True)


def render_brightness(
    ax: plt.Axes,
    brightness: BrightnessCurve | None,
    base_brightness: BrightnessCurve | None = None,
    labels: SeriesLabels | None = None,
) -> None:
    style_chart(ax, "Brightness")
    labels = labels or SeriesLabels(run="measured", base="base")
    if brightness is None and base_brightness is None:
        placeholder(ax, "Brightness data not available")
        return
    all_luminance: list[float] = []
    if base_brightness is not None:
        ax.plot(
            base_brightness.brightness_percent,
            base_brightness.luminance,
            "o--",
            color=BASELINE_COLOR,
            markerfacecolor="white",
            linewidth=1.1,
            markersize=2.2,
            label=labels.base,
        )
        all_luminance.extend(base_brightness.luminance)
    if brightness is not None:
        x = brightness.brightness_percent
        y = brightness.luminance
        ax.plot(x, y, "o-", color="#0072B2", linewidth=1.4, markersize=2.6, label=labels.run)
        all_luminance.extend(y)
    else:
        x = []
        y = []
    if brightness is not None and brightness.expected_luminance and base_brightness is None:
        ax.plot(x, brightness.expected_luminance, "--", color="#6B7682", linewidth=1.0, label="expected")
    ax.set_xlabel("Brightness command (%)", fontsize=7)
    ax.set_ylabel("Luminance Y (nits)", fontsize=7)
    ax.set_xlim(-2, 102)
    if all_luminance:
        ax.set_ylim(0, max(all_luminance) * 1.08)
    else:
        ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", fontsize=6, frameon=False)
    if y:
        peak_text = f"Peak {max(y):.1f} nits"
        if base_brightness and base_brightness.luminance:
            peak_text += f" ({max(y) - max(base_brightness.luminance):+.1f})"
        ax.text(
            0.98,
            0.05,
            peak_text,
            ha="right",
            transform=ax.transAxes,
            fontsize=7.2,
            color="#111111",
            weight="bold",
        )


def render_gamma(
    ax: plt.Axes,
    gamma: GammaCurve | None,
    base_gamma: GammaCurve | None = None,
    labels: SeriesLabels | None = None,
) -> None:
    style_chart(ax, "Gamma")
    labels = labels or SeriesLabels(run="measured", base="base")
    if gamma is None and base_gamma is None:
        placeholder(ax, "Gamma data not available")
        return

    ref_x = np.linspace(0, 1, 256)
    ax.plot(ref_x, ref_x**2.2, "--", color="#999999", linewidth=1.0, label="ref 2.2")
    ax.plot(ref_x, ref_x**2.4, ":", color="#666666", linewidth=1.0, label="ref 2.4")
    if base_gamma is not None:
        if base_gamma.gamma is not None:
            ax.plot(ref_x, ref_x**base_gamma.gamma, "--", color=BASELINE_COLOR, linewidth=0.95, label=f"{labels.base} fit {base_gamma.gamma:.3f}")
        ax.plot(
            base_gamma.normalized_input,
            base_gamma.normalized_luminance,
            "o",
            markerfacecolor="white",
            markeredgecolor=BASELINE_COLOR,
            markersize=2.2,
            label=labels.base,
            zorder=4,
        )
    if gamma is not None and gamma.gamma is not None:
        run_fit_label = f"{labels.run} fit {gamma.gamma:.3f}" if base_gamma is not None else f"fit {gamma.gamma:.3f}"
        ax.plot(ref_x, ref_x**gamma.gamma, "-", color="#E69F00", linewidth=1.0, label=run_fit_label)
    if gamma is not None:
        ax.plot(
            gamma.normalized_input,
            gamma.normalized_luminance,
            "o",
            color="#0072B2",
            markersize=2.4,
            label=labels.run,
            zorder=5,
        )
    ax.set_xlabel("Gray code / 255", fontsize=7)
    ax.set_ylabel("Normalized luminance", fontsize=7)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.03, 1.05)
    ax.legend(loc="upper left", fontsize=5.8, frameon=False)

    details = []
    if gamma and gamma.rms_gamma is not None:
        details.append(f"RMS {gamma.rms_gamma:.3f}")
    if gamma:
        details.append(f"Ymax {gamma.y_max:.1f}")
    if gamma and base_gamma and gamma.gamma is not None and base_gamma.gamma is not None:
        details.append(f"dG {gamma.gamma - base_gamma.gamma:+.3f}")
    if gamma and gamma.endpoint_drift_percent is not None:
        details.append(f"end {gamma.endpoint_drift_percent:+.1f}%")
    if details:
        ax.text(0.98, 0.05, " | ".join(details), ha="right", transform=ax.transAxes, fontsize=6.1, color="#4F5965")


def render_contrast(
    ax: plt.Axes,
    contrast: ContrastCurve | None,
    base_contrast: ContrastCurve | None = None,
    labels: SeriesLabels | None = None,
) -> None:
    style_chart(ax, "Contrast")
    labels = labels or SeriesLabels(run="measured", base="base")
    if contrast is None and base_contrast is None:
        placeholder(ax, "Contrast data not available")
        return
    if base_contrast is not None:
        ax.plot(
            base_contrast.brightness,
            base_contrast.contrast_ratio,
            "o--",
            color=BASELINE_COLOR,
            markerfacecolor="white",
            linewidth=1.1,
            markersize=3.1,
            label=labels.base,
        )
    if contrast is not None:
        ax.plot(contrast.brightness, contrast.contrast_ratio, "o-", color="#009E73", linewidth=1.4, markersize=3.8, label=labels.run)
    ax.set_xlabel("Brightness command (%)", fontsize=7)
    ax.set_ylabel("Contrast ratio", fontsize=7)
    ax.set_xlim(0, 105)
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(LogLocator(base=10, numticks=4))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.0f}:1"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    if contrast is not None:
        for x, y, label, lower in zip(
            contrast.brightness,
            contrast.contrast_ratio,
            contrast.contrast_display,
            contrast.lower_bound,
        ):
            text = label if lower and label.startswith(">") else f"{y:.0f}"
            ax.annotate(text, (x, y), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=5.5)
    missing = sorted(set(contrast.expected_levels) - set(contrast.brightness)) if contrast is not None else []
    note_parts = []
    if contrast is not None and any(contrast.lower_bound):
        note_parts.append("lower bounds")
    if missing:
        note_parts.append("missing " + ", ".join(f"{level:g}%" for level in missing))
    if contrast is not None and contrast.result != "PASS":
        note_parts.append(contrast.result)
    if note_parts:
        ax.text(0.02, 0.94, "; ".join(note_parts), transform=ax.transAxes, fontsize=6.1, color="#C9342F", va="top")
    if base_contrast is not None and contrast is not None:
        ax.legend(loc="lower right", fontsize=5.7, frameon=False)


def render_local_dimming_apl(
    ax: plt.Axes,
    apl: LocalDimmingAplCurve | None,
    base_apl: LocalDimmingAplCurve | None = None,
    labels: SeriesLabels | None = None,
    compact: bool = False,
) -> None:
    style_chart(ax, "Peak luminance vs window size" if compact else "Peak luminance vs window size (backlight 100%)")
    labels = labels or SeriesLabels(run="measured", base="base")
    if apl is None and base_apl is None:
        placeholder(ax, "No APL data in this run")
        return

    measured = [sample for sample in apl.samples if sample.fits_screen and sample.luminance is not None] if apl else []
    skipped = [sample for sample in apl.samples if not sample.fits_screen] if apl else []
    base_measured = [sample for sample in base_apl.samples if sample.fits_screen and sample.luminance is not None] if base_apl else []
    base_skipped = [sample for sample in base_apl.samples if not sample.fits_screen] if base_apl else []
    all_apl = sorted(
        {sample.apl_percent for sample in measured + skipped + base_measured + base_skipped}
    )

    if all_apl:
        ax.set_xlim(max(0.0, min(all_apl) - 1.0), max(all_apl) + 2.0)
        ax.set_xticks(all_apl)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g}"))

    all_measured_y = [float(sample.luminance) for sample in measured + base_measured if sample.luminance is not None]
    if not all_measured_y:
        for samples, marker, color, label in (
            (base_skipped, "^", BASELINE_COLOR, labels.base),
            (skipped, "o", "#8C96A3", "skipped"),
        ):
            if samples:
                ax.scatter(
                    [sample.apl_percent for sample in samples],
                    [0.0 for _sample in samples],
                    marker=marker,
                    facecolors="none",
                    edgecolors=color,
                    s=22,
                    linewidths=0.9,
                    label=label,
                )
        ax.set_ylim(0, 1)
        placeholder(ax, "No measurable APL samples")
        return

    y_min = min(all_measured_y)
    y_max = max(all_measured_y)
    y_span = max(y_max - y_min, 1.0)
    y_bottom = max(0.0, y_min - max(y_span * 0.12, y_max * 0.05, 1.0))
    y_top = y_max + max(y_span * 0.12, y_max * 0.04, 1.0)
    ax.set_ylim(y_bottom, y_top)

    if base_measured:
        base_measured = sorted(base_measured, key=lambda sample: sample.index)
        ax.plot(
            [sample.apl_percent for sample in base_measured],
            [float(sample.luminance) for sample in base_measured if sample.luminance is not None],
            "o--",
            color=BASELINE_COLOR,
            markerfacecolor="white",
            linewidth=1.1,
            markersize=2.8,
            label=labels.base,
        )

    if measured:
        measured = sorted(measured, key=lambda sample: sample.index)
        measured_x = [sample.apl_percent for sample in measured]
        measured_y = [float(sample.luminance) for sample in measured if sample.luminance is not None]
        ax.plot(measured_x, measured_y, "o-", color="#A23E48", linewidth=1.35, markersize=3.0, label=labels.run)
    else:
        measured_y = []

    marker_y = y_bottom + (y_top - y_bottom) * 0.055
    for samples, marker, color, label, zorder in (
        (base_skipped, "^", BASELINE_COLOR, f"{labels.base} skipped", 4),
        (skipped, "o", "#8C96A3", "skipped", 5),
    ):
        if samples:
            for sample in samples:
                ax.axvline(sample.apl_percent, color="#D0D7DF", linestyle="--", linewidth=0.65, zorder=0)
            ax.scatter(
                [sample.apl_percent for sample in samples],
                [marker_y for _sample in samples],
                marker=marker,
                facecolors="white",
                edgecolors=color,
                s=22,
                linewidths=0.9,
                label=label,
                zorder=zorder,
            )

    if measured:
        peak = max(measured, key=lambda sample: float(sample.luminance or -math.inf))
        ratio = max(measured_y) / min(measured_y) if min(measured_y) > 0 else None
        attempted = apl.samples_attempted if apl and apl.samples_attempted is not None else len(apl.samples) if apl else len(measured)
        collected = apl.samples_collected if apl and apl.samples_collected is not None else len(measured)
        if compact:
            badge_parts = [f"peak {float(peak.luminance or 0.0):.1f} @ {peak.apl_percent:g}% | {collected}/{attempted}"]
            ratio_and_delta = []
            if ratio is not None:
                ratio_and_delta.append(f"ratio {ratio:.2f}x")
            if base_measured:
                base_peak = max(base_measured, key=lambda sample: float(sample.luminance or -math.inf))
                ratio_and_delta.append(f"dPeak {float(peak.luminance or 0.0) - float(base_peak.luminance or 0.0):+.1f}")
            if ratio_and_delta:
                badge_parts.append(" | ".join(ratio_and_delta))
            badge_text = "\n".join(badge_parts)
        else:
            badge_parts = [
                f"peak {float(peak.luminance or 0.0):.1f} @ {peak.apl_percent:g}%",
                f"{collected}/{attempted} measured",
            ]
            if ratio is not None:
                badge_parts.insert(1, f"ratio {ratio:.2f}x")
            if base_measured:
                base_peak = max(base_measured, key=lambda sample: float(sample.luminance or -math.inf))
                badge_parts.append(f"dPeak {float(peak.luminance or 0.0) - float(base_peak.luminance or 0.0):+.1f}")
            if apl and apl.artifact_generated_timestamp:
                badge_parts.append(f"gen {format_timestamp(apl.artifact_generated_timestamp)[:16]}")
            badge_text = " | ".join(badge_parts)
        ax.text(
            0.985,
            0.175 if compact else 0.235,
            badge_text,
            transform=ax.transAxes,
            fontsize=5.15 if compact else 5.8,
            color="#3D4650",
            ha="right",
            va="top",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 1.3},
        )

    display_model = apl.display_model if apl and apl.display_model else base_apl.display_model if base_apl else ""
    if display_model:
        ax.text(0.015, 0.90, shorten(display_model, 34), transform=ax.transAxes, fontsize=5.8, color="#5E6874", va="top")
    skip_note = summarize_apl_skips(skipped)
    if skip_note:
        ax.text(0.015, 0.74, f"skipped: {skip_note}", transform=ax.transAxes, fontsize=5.5, color="#7A4F00", va="top")
    if not compact:
        ax.text(
            0.985,
            0.125,
            "APL = centered square area; i1DisplayPro at centre.",
            transform=ax.transAxes,
            fontsize=5.5,
            color="#596574",
            ha="right",
            va="top",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.65, "pad": 1.0},
        )
    ax.set_xlabel("APL (%)", fontsize=6.4)
    ax.set_ylabel("Peak Y (cd/m^2)", fontsize=6.4)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.56 if compact else 0.56), fontsize=5.4 if compact else 5.6, frameon=False)


def summarize_apl_skips(skipped: list[LocalDimmingAplSample]) -> str:
    if not skipped:
        return ""
    small = [sample.apl_percent for sample in skipped if "smaller than" in sample.skip_reason]
    tall = [sample.apl_percent for sample in skipped if "exceeds screen height" in sample.skip_reason]
    other = [sample for sample in skipped if sample.apl_percent not in set(small + tall)]
    parts: list[str] = []
    if small:
        parts.append("too small " + ", ".join(f"{value:g}%" for value in small))
    if tall:
        parts.append("too large " + ", ".join(f"{value:g}%" for value in tall))
    if other:
        parts.append(f"other {len(other)}")
    return "; ".join(parts)


def render_thermal_white_point_drift(
    ax: plt.Axes,
    profile: ThermalLuminanceProfile | None,
    base_profile: ThermalLuminanceProfile | None = None,
    labels: SeriesLabels | None = None,
) -> None:
    style_chart(ax, "Thermal White-Point Drift")
    labels = labels or SeriesLabels(run="measured", base="base")
    if profile is None and base_profile is None:
        placeholder(ax, "No thermal white-point data")
        return

    reference = REFERENCE_GAMUTS["ntsc"]
    reference_white = reference["w"]
    all_samples: list[ThermalLuminanceSample] = []
    if base_profile:
        all_samples.extend(base_profile.samples)
    if profile:
        all_samples.extend(profile.samples)
    all_x = [sample.x_chromaticity for sample in all_samples]
    all_y = [sample.y_chromaticity for sample in all_samples]
    x_min, x_max, y_min, y_max = thermal_zoom_limits(all_x, all_y, reference_white)

    draw_white_reference(ax, reference_white, "D65", DEFAULT_WHITE_TOLERANCE)
    if base_profile is not None:
        plot_thermal_profile(ax, base_profile, labels.base, BASELINE_COLOR, baseline=profile is not None)
    if profile is not None:
        plot_thermal_profile(ax, profile, labels.run, "#A23E48", baseline=False)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("auto", adjustable="box")
    ax.set_xlabel("CIE x", fontsize=6.4)
    ax.set_ylabel("CIE y", fontsize=6.4)
    ax.legend(loc="upper left", fontsize=5.4, frameon=False)

    summary_profile = profile or base_profile
    if profile is not None:
        add_thermal_tolerance_exit_marker(ax, profile, reference_white)
    if summary_profile is not None:
        add_thermal_runtime_badge(ax, summary_profile)
        add_thermal_summary_badge(ax, summary_profile, reference_white)


def draw_white_reference(
    ax: plt.Axes,
    reference_white: tuple[float, float],
    label: str,
    tolerance: float,
) -> None:
    ax.plot(reference_white[0], reference_white[1], "x", color="#4F5965", markersize=4.7, label=label, zorder=5)
    ax.add_patch(
        Ellipse(
            xy=reference_white,
            width=tolerance * 2,
            height=tolerance * 2.4,
            angle=-10,
            fill=False,
            edgecolor="#697684",
            linestyle=":",
            linewidth=1.0,
            label=f"D65 tol {tolerance:.3f}",
            zorder=2,
        )
    )


def thermal_zoom_limits(
    x_values: list[float],
    y_values: list[float],
    reference_white: tuple[float, float],
) -> tuple[float, float, float, float]:
    x_candidates = x_values + [reference_white[0] - DEFAULT_WHITE_TOLERANCE, reference_white[0] + DEFAULT_WHITE_TOLERANCE]
    y_candidates = y_values + [reference_white[1] - DEFAULT_WHITE_TOLERANCE * 1.2, reference_white[1] + DEFAULT_WHITE_TOLERANCE * 1.2]
    x_min = min(x_candidates)
    x_max = max(x_candidates)
    y_min = min(y_candidates)
    y_max = max(y_candidates)
    span = max(x_max - x_min, y_max - y_min, 0.020)
    pad = max(span * 0.18, 0.004)
    return x_min - pad * 1.8, x_max + pad * 0.5, y_min - pad, y_max + pad


def plot_thermal_profile(
    ax: plt.Axes,
    profile: ThermalLuminanceProfile,
    label: str,
    color: str,
    baseline: bool,
) -> None:
    samples = profile.samples
    if not samples:
        return
    x_values = [sample.x_chromaticity for sample in samples]
    y_values = [sample.y_chromaticity for sample in samples]
    if baseline:
        ax.plot(
            x_values,
            y_values,
            "o--",
            color=color,
            markerfacecolor="white",
            linewidth=0.8,
            markersize=2.2,
            label=label,
            zorder=3,
        )
    else:
        ax.plot(x_values, y_values, "-", color=color, linewidth=0.8, alpha=0.8, label=label, zorder=3)
        temps = [sample.backlight_temp_c if sample.backlight_temp_c is not None else math.nan for sample in samples]
        finite_temps = [temp for temp in temps if not math.isnan(temp)]
        if finite_temps:
            ax.scatter(
                x_values,
                y_values,
                c=temps,
                cmap="coolwarm",
                s=7,
                edgecolors="none",
                zorder=4,
            )
        else:
            ax.scatter(x_values, y_values, color=color, s=7, edgecolors="none", zorder=4)

    start = samples[0]
    end = samples[-1]
    ax.plot(start.x_chromaticity, start.y_chromaticity, "o", color=color, markerfacecolor="white" if baseline else color, markersize=3.0, zorder=6)
    ax.plot(end.x_chromaticity, end.y_chromaticity, "s", color=color, markerfacecolor="white" if baseline else color, markersize=3.0, zorder=6)
    if not baseline:
        ax.annotate(
            "",
            xy=(end.x_chromaticity, end.y_chromaticity),
            xytext=(start.x_chromaticity, start.y_chromaticity),
            arrowprops={"arrowstyle": "->", "color": color, "linewidth": 0.7, "shrinkA": 4, "shrinkB": 4},
            zorder=5,
        )
        add_thermal_point_label(ax, "start", start, xybox=(2, 2), box_alignment=(0.0, 0.0), temp_color="#0072B2")
        add_thermal_point_label(ax, "end", end, xybox=(-2, -2), box_alignment=(1.0, 1.0), temp_color="#C9342F")


def add_thermal_point_label(
    ax: plt.Axes,
    prefix: str,
    sample: ThermalLuminanceSample,
    xybox: tuple[float, float],
    box_alignment: tuple[float, float],
    temp_color: str,
) -> None:
    textprops = {"fontsize": 5.2, "color": "#3D4650"}
    parts = [TextArea(f"{prefix} ", textprops=textprops)]
    if sample.backlight_temp_c is not None:
        parts.append(TextArea(f"{sample.backlight_temp_c:.1f}C", textprops={"fontsize": 5.2, "color": temp_color}))
        parts.append(TextArea(f" {sample.luminance:.0f}Y", textprops=textprops))
    else:
        parts.append(TextArea(f"{sample.luminance:.0f}Y", textprops=textprops))
    packed = HPacker(children=parts, align="center", pad=0, sep=0)
    label = AnnotationBbox(
        packed,
        (sample.x_chromaticity, sample.y_chromaticity),
        xybox=xybox,
        xycoords="data",
        boxcoords="offset points",
        box_alignment=box_alignment,
        frameon=True,
        bboxprops={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "boxstyle": "round,pad=0.08"},
    )
    label.set_zorder(7)
    ax.add_artist(label)


def add_thermal_summary_badge(
    ax: plt.Axes,
    profile: ThermalLuminanceProfile,
    reference_white: tuple[float, float],
) -> None:
    if not profile.samples:
        return
    start = profile.samples[0]
    end = profile.samples[-1]
    temp_text = "T n/a"
    if start.backlight_temp_c is not None and end.backlight_temp_c is not None:
        temp_text = f"T {start.backlight_temp_c:.1f}->{end.backlight_temp_c:.1f}C"
    y_delta = end.luminance - start.luminance
    y_delta_percent = y_delta / start.luminance * 100.0 if start.luminance else 0.0
    d65_start = xy_distance((start.x_chromaticity, start.y_chromaticity), reference_white)
    d65_end = xy_distance((end.x_chromaticity, end.y_chromaticity), reference_white)
    drift = xy_distance((start.x_chromaticity, start.y_chromaticity), (end.x_chromaticity, end.y_chromaticity))
    tolerance_multiple = thermal_final_d65_tolerance_multiple(profile, reference_white)
    tolerance_text = f" ({tolerance_multiple:.1f}x tol)" if tolerance_multiple is not None else ""
    badge = (
        f"{temp_text} | Y {y_delta_percent:+.1f}%\n"
        f"dD65 {d65_start:.4f}->{d65_end:.4f}{tolerance_text} | drift {drift:.4f} xy"
    )
    ax.text(
        0.985,
        0.025,
        badge,
        transform=ax.transAxes,
        fontsize=5.35,
        color="#3D4650",
        ha="right",
        va="bottom",
        linespacing=1.15,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 1.1},
    )


def add_thermal_runtime_badge(ax: plt.Axes, profile: ThermalLuminanceProfile) -> None:
    minutes = thermal_duration_minutes(profile)
    if minutes is None:
        return
    ax.text(
        0.985,
        0.935,
        f"runtime {minutes:.1f} min",
        transform=ax.transAxes,
        fontsize=5.4,
        color="#4D5966",
        ha="right",
        va="top",
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.76, "pad": 1.0},
    )


def add_thermal_tolerance_exit_marker(
    ax: plt.Axes,
    profile: ThermalLuminanceProfile,
    reference_white: tuple[float, float],
) -> None:
    tolerance_exit = thermal_tolerance_exit(profile, reference_white)
    if tolerance_exit is None:
        return
    ax.plot(
        tolerance_exit.x_chromaticity,
        tolerance_exit.y_chromaticity,
        "o",
        color="#B86A00",
        markerfacecolor="white",
        markeredgewidth=0.8,
        markersize=3.8,
        zorder=8,
        label="_nolegend_",
    )
    label = "tol exit"
    if tolerance_exit.backlight_temp_c is not None:
        label += f" ~{tolerance_exit.backlight_temp_c:.1f}C"
    ax.text(
        0.035,
        0.755,
        label,
        transform=ax.transAxes,
        fontsize=5.2,
        color="#8A5200",
        ha="left",
        va="top",
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.74, "pad": 0.7},
        zorder=9,
    )


def thermal_final_d65_tolerance_multiple(
    profile: ThermalLuminanceProfile,
    reference_white: tuple[float, float],
    tolerance: float = DEFAULT_WHITE_TOLERANCE,
) -> float | None:
    if not profile.samples or tolerance <= 0:
        return None
    end = profile.samples[-1]
    return white_tolerance_distance((end.x_chromaticity, end.y_chromaticity), reference_white, tolerance)


def thermal_tolerance_exit(
    profile: ThermalLuminanceProfile,
    reference_white: tuple[float, float],
    tolerance: float = DEFAULT_WHITE_TOLERANCE,
) -> ThermalToleranceExit | None:
    if len(profile.samples) < 2 or tolerance <= 0:
        return None
    prev = profile.samples[0]
    prev_distance = white_tolerance_distance((prev.x_chromaticity, prev.y_chromaticity), reference_white, tolerance)
    if prev_distance is None or prev_distance > 1.0:
        return None
    for sample in profile.samples[1:]:
        sample_distance = white_tolerance_distance((sample.x_chromaticity, sample.y_chromaticity), reference_white, tolerance)
        if sample_distance is None:
            return None
        if prev_distance <= 1.0 < sample_distance:
            fraction = thermal_tolerance_exit_fraction(prev, sample, reference_white, tolerance)
            if fraction is None:
                fraction = (1.0 - prev_distance) / (sample_distance - prev_distance)
            return ThermalToleranceExit(
                x_chromaticity=interpolate_value(prev.x_chromaticity, sample.x_chromaticity, fraction),
                y_chromaticity=interpolate_value(prev.y_chromaticity, sample.y_chromaticity, fraction),
                backlight_temp_c=interpolate_optional(prev.backlight_temp_c, sample.backlight_temp_c, fraction),
                elapsed_seconds=interpolate_optional(prev.elapsed_seconds, sample.elapsed_seconds, fraction),
            )
        prev = sample
        prev_distance = sample_distance
    return None


def thermal_tolerance_exit_fraction(
    start: ThermalLuminanceSample,
    end: ThermalLuminanceSample,
    reference_white: tuple[float, float],
    tolerance: float,
) -> float | None:
    start_x = (start.x_chromaticity - reference_white[0]) / tolerance
    start_y = (start.y_chromaticity - reference_white[1]) / (tolerance * 1.2)
    end_x = (end.x_chromaticity - reference_white[0]) / tolerance
    end_y = (end.y_chromaticity - reference_white[1]) / (tolerance * 1.2)
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    a = delta_x * delta_x + delta_y * delta_y
    b = 2.0 * (start_x * delta_x + start_y * delta_y)
    c = start_x * start_x + start_y * start_y - 1.0
    if a <= 0:
        return None
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        return None
    root = math.sqrt(discriminant)
    candidates = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
    valid = [value for value in candidates if -1e-9 <= value <= 1.0 + 1e-9]
    if not valid:
        return None
    return min(max(value, 0.0) for value in valid)


def interpolate_value(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


def interpolate_optional(start: float | None, end: float | None, fraction: float) -> float | None:
    if start is None or end is None:
        return None
    return interpolate_value(start, end, fraction)


def thermal_duration_minutes(profile: ThermalLuminanceProfile) -> float | None:
    if len(profile.samples) < 2:
        return None
    start = profile.samples[0]
    end = profile.samples[-1]
    if start.elapsed_seconds is not None and end.elapsed_seconds is not None:
        seconds = end.elapsed_seconds - start.elapsed_seconds
        if seconds >= 0:
            return seconds / 60.0
    start_time = parse_iso_datetime(start.timestamp)
    end_time = parse_iso_datetime(end.timestamp)
    if start_time is None or end_time is None:
        return None
    try:
        seconds = (end_time - start_time).total_seconds()
    except TypeError:
        return None
    if seconds < 0:
        return None
    return seconds / 60.0


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def xy_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def render_gamut(
    ax: plt.Axes,
    gamut: GamutMetrics | None,
    reference_gamut: str,
    render_mode: str,
    warnings: list[str],
    base_gamut: GamutMetrics | None = None,
    labels: SeriesLabels | None = None,
) -> None:
    style_chart(ax, "Gamut / White Point")
    labels = labels or SeriesLabels(run="measured", base="base")
    reference = REFERENCE_GAMUTS.get(reference_gamut, REFERENCE_GAMUTS["ntsc"])
    if render_mode == "advanced":
        render_advanced_chromaticity_background(ax, warnings)

    ref_triangle = [reference["r"], reference["g"], reference["b"], reference["r"]]
    ax.plot([p[0] for p in ref_triangle], [p[1] for p in ref_triangle], "--", color="#8C96A3", linewidth=1.0, label=reference["name"])
    ax.plot(reference["w"][0], reference["w"][1], "x", color="#5B6472", markersize=5, label=reference.get("white_name", "white"))
    ax.add_patch(
        Ellipse(
            xy=reference["w"],
            width=DEFAULT_WHITE_TOLERANCE * 2,
            height=DEFAULT_WHITE_TOLERANCE * 2.4,
            angle=-10,
            fill=False,
            edgecolor="#697684",
            linestyle=":",
            linewidth=1.0,
            label=f"D65 tol {DEFAULT_WHITE_TOLERANCE:.3f}",
        )
    )

    if gamut is None and base_gamut is None:
        placeholder(ax, "Gamut data not available")
        return

    if base_gamut is not None and all(color in base_gamut.points for color in ("R", "G", "B")):
        base_measured = [base_gamut.points["R"], base_gamut.points["G"], base_gamut.points["B"], base_gamut.points["R"]]
        ax.plot(
            [p[0] for p in base_measured],
            [p[1] for p in base_measured],
            "o--",
            color=BASELINE_COLOR,
            markerfacecolor="white",
            linewidth=1.0,
            markersize=3.0,
            label=labels.base,
        )
    if base_gamut is not None and base_gamut.white_point:
        ax.plot(
            base_gamut.white_point[0],
            base_gamut.white_point[1],
            "o",
            markerfacecolor="white",
            markeredgecolor=BASELINE_COLOR,
            markersize=3.0,
            label=f"{labels.base} white",
        )

    if gamut is None:
        ax.set_xlabel("CIE x", fontsize=7)
        ax.set_ylabel("CIE y", fontsize=7)
        ax.set_xlim(0.0, 0.78)
        ax.set_ylim(0.0, 0.82)
        ax.legend(loc="upper right", fontsize=5.7, frameon=False)
        return

    if all(color in gamut.points for color in ("R", "G", "B")):
        measured = [gamut.points["R"], gamut.points["G"], gamut.points["B"], gamut.points["R"]]
        ax.plot([p[0] for p in measured], [p[1] for p in measured], "o-", color="#D55E00", linewidth=1.3, markersize=3.5, label=labels.run)
    if gamut.white_point:
        white_label = f"{labels.run} white" if base_gamut is not None else "white"
        ax.plot(gamut.white_point[0], gamut.white_point[1], "o", color="#0072B2", markersize=3.0, label=white_label)
        coverage_parts = []
        white_parts = []
        if gamut.coverage_percent is not None:
            coverage_parts.append(f"cov {gamut.coverage_percent:.1f}%")
        if gamut.relative_area_percent is not None:
            coverage_parts.append(f"area {gamut.relative_area_percent:.1f}%")
        if gamut.white_delta is not None:
            white_parts.append(f"dx {gamut.white_delta[0]:+.4f}")
            white_parts.append(f"dy {gamut.white_delta[1]:+.4f}")
        if gamut.white_tolerance_distance is not None:
            white_parts.append(f"{gamut.white_tolerance_distance:.2f}x tol")
        temp_parts = gamut_temperature_annotation_parts(gamut)
        annotation = "\n".join(" | ".join(parts) for parts in (coverage_parts, white_parts, temp_parts) if parts)
        if annotation:
            ax.text(
                0.98,
                0.055,
                annotation,
                transform=ax.transAxes,
                fontsize=5.4,
                color="#4F5965",
                ha="right",
                linespacing=1.12,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 1.2},
            )

    ax.set_xlabel("CIE x", fontsize=7)
    ax.set_ylabel("CIE y", fontsize=7)
    ax.set_xlim(0.0, 0.78)
    ax.set_ylim(0.0, 0.82)
    if render_mode == "advanced":
        ax.set_aspect("auto", adjustable="box")
    ax.legend(loc="upper right", fontsize=5.7, frameon=False)


def gamut_temperature_annotation_parts(gamut: GamutMetrics) -> list[str]:
    start = gamut.backlight_temp_c_start
    end = gamut.backlight_temp_c_end
    avg = gamut.backlight_temp_c_avg
    if avg is None and gamut.color_backlight_temps:
        temps = list(gamut.color_backlight_temps.values())
        avg = sum(temps) / len(temps)
        start = min(temps) if start is None else start
        end = max(temps) if end is None else end
    if start is None and end is None and avg is None:
        return []

    parts = []
    if start is not None and end is not None:
        if abs(start - end) < 0.05:
            parts.append(f"temp {format_temp_c(start)}C")
        else:
            parts.append(f"temp {format_temp_c(start)}->{format_temp_c(end)}C")
    elif avg is not None:
        parts.append(f"temp avg {format_temp_c(avg)}C")
    elif start is not None:
        parts.append(f"temp start {format_temp_c(start)}C")
    elif end is not None:
        parts.append(f"temp end {format_temp_c(end)}C")

    if avg is not None and (start is not None or end is not None):
        parts.append(f"avg {format_temp_c(avg)}C")
    return parts


def format_temp_c(value: float) -> str:
    if value >= 0:
        rounded = math.floor(value * 10.0 + 0.5) / 10.0
    else:
        rounded = math.ceil(value * 10.0 - 0.5) / 10.0
    return f"{rounded:.1f}"


def render_advanced_chromaticity_background(ax: plt.Axes, warnings: list[str]) -> None:
    try:
        import warnings as warnings_module

        from colour.plotting import plot_chromaticity_diagram_CIE1931
    except Exception as exc:
        message = f"advanced gamut rendering unavailable: {exc}"
        if message not in warnings:
            warnings.append(message)
        ax.text(0.02, 0.92, "advanced CIE background unavailable", transform=ax.transAxes, fontsize=5.7, color="#9A5B00")
        return

    try:
        with warnings_module.catch_warnings():
            warnings_module.filterwarnings(
                "ignore",
                message="This figure includes Axes that are not compatible with tight_layout.*",
                category=UserWarning,
            )
            plot_chromaticity_diagram_CIE1931(
                axes=ax,
                show=False,
                title=False,
                diagram_opacity=0.62,
                spectral_locus_opacity=0.55,
                spectral_locus_labels=[],
            )
    except Exception as exc:
        message = f"advanced gamut rendering failed: {exc}"
        if message not in warnings:
            warnings.append(message)
        ax.text(0.02, 0.92, "advanced CIE background failed", transform=ax.transAxes, fontsize=5.7, color="#9A5B00")


def style_chart(ax: plt.Axes, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=8.7, weight="bold", pad=4)
    ax.grid(True, linestyle=":", linewidth=0.55, color="#B9C2CC", alpha=0.9)
    ax.tick_params(axis="both", labelsize=5.8, length=2.5)
    for spine in ax.spines.values():
        spine.set_color("#CAD2DA")
        spine.set_linewidth(0.8)


def placeholder(ax: plt.Axes, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=8, color="#697684", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def render_footer(ax: plt.Axes, run: RunData, base_run: RunData | None = None) -> None:
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor="#F8FAFC", edgecolor="#D9E0E7", linewidth=0.8))
    observations = build_observations(run, base_run)
    ax.text(0.012, 0.68, "Observations", fontsize=8.2, weight="bold", color="#2D3845", transform=ax.transAxes)
    ax.text(0.012, 0.28, "  |  ".join(observations), fontsize=7.2, color="#4D5966", transform=ax.transAxes)
    if run.warnings:
        ax.text(0.988, 0.28, f"{len(run.warnings)} warning(s)", ha="right", fontsize=6.8, color="#9A5B00", transform=ax.transAxes)


def build_observations(run: RunData, base_run: RunData | None = None) -> list[str]:
    if base_run is not None:
        return build_comparison_observations(run, base_run)
    notes: list[str] = []
    failed_or_error = [row for row in run.status_rows if row.result in {"FAIL", "ERROR"}]
    skipped = [row for row in run.status_rows if row.result == "SKIP"]
    if failed_or_error:
        notes.append("; ".join(f"{row.name}: {row.note or row.result}" for row in failed_or_error[:2]))
    else:
        notes.append("No FAIL or ERROR test results")
    if skipped:
        notes.append(f"{len(skipped)} skipped model/configuration-specific test(s)")
    if run.gamma and run.gamma.gamma is not None:
        notes.append(f"Gamma {run.gamma.gamma:.3f}")
    if run.gamut and run.gamut.coverage_percent is not None:
        notes.append(f"{run.gamut.reference_name} coverage {run.gamut.coverage_percent:.1f}%")
    if run.local_dimming_apl:
        measured = [sample for sample in run.local_dimming_apl.samples if sample.fits_screen and sample.luminance is not None]
        if measured:
            peak = max(measured, key=lambda sample: float(sample.luminance or -math.inf))
            attempted = run.local_dimming_apl.samples_attempted or len(run.local_dimming_apl.samples)
            collected = run.local_dimming_apl.samples_collected or len(measured)
            notes.append(f"APL peak {float(peak.luminance or 0.0):.1f} cd/m2 @ {peak.apl_percent:g}% ({collected}/{attempted})")
    if run.contrast and run.contrast.result != "PASS":
        notes.append("Contrast chart uses partial measurement data")
    if run.header.display_serial_number.startswith("DUMMY"):
        notes.append("Display serial placeholder")
    return [shorten(note, 78) for note in notes[:5]]


def build_comparison_observations(run: RunData, base_run: RunData) -> list[str]:
    notes: list[str] = []
    changes = result_changes(run, base_run)
    if changes:
        notes.append("; ".join(changes[:2]) + (f"; +{len(changes) - 2} more" if len(changes) > 2 else ""))
    else:
        notes.append("No test result changes")

    brightness_delta = scalar_delta(max_luminance(run.brightness), max_luminance(base_run.brightness), "nits", 1)
    if brightness_delta:
        notes.append(f"Peak brightness {brightness_delta}")

    if run.gamma and base_run.gamma and run.gamma.gamma is not None and base_run.gamma.gamma is not None:
        notes.append(f"Gamma {run.gamma.gamma:.3f} ({run.gamma.gamma - base_run.gamma.gamma:+.3f})")

    gamut_delta = scalar_delta(
        run.gamut.coverage_percent if run.gamut else None,
        base_run.gamut.coverage_percent if base_run.gamut else None,
        "%",
        1,
    )
    if gamut_delta and run.gamut:
        notes.append(f"{run.gamut.reference_name} coverage {run.gamut.coverage_percent:.1f}% ({gamut_delta})")

    apl_delta = scalar_delta(apl_peak_luminance(run.local_dimming_apl), apl_peak_luminance(base_run.local_dimming_apl), "cd/m2", 1)
    if apl_delta:
        notes.append(f"APL peak {apl_peak_luminance(run.local_dimming_apl):.1f} ({apl_delta})")
    return [shorten(note, 78) for note in notes[:5]]


def result_changes(run: RunData, base_run: RunData) -> list[str]:
    base_rows = {row.name: row for row in base_run.status_rows}
    changes: list[str] = []
    for row in run.status_rows:
        base_row = base_rows.get(row.name)
        if base_row is None:
            changes.append(f"{row.name}: new {row.result}")
        elif base_row.result != row.result:
            changes.append(f"{row.name}: {base_row.result}->{row.result}")
    return changes


def max_luminance(brightness: BrightnessCurve | None) -> float | None:
    if brightness is None or not brightness.luminance:
        return None
    return max(brightness.luminance)


def apl_peak_luminance(apl: LocalDimmingAplCurve | None) -> float | None:
    if apl is None:
        return None
    measured = [sample.luminance for sample in apl.samples if sample.fits_screen and sample.luminance is not None]
    if not measured:
        return None
    return max(float(value) for value in measured)


def scalar_delta(run_value: float | None, base_value: float | None, unit: str, precision: int) -> str | None:
    if run_value is None or base_value is None:
        return None
    delta = run_value - base_value
    if unit == "%":
        return f"{delta:+.{precision}f}%"
    return f"{delta:+.{precision}f} {unit}".rstrip()


def default_output_path(run: RunData, base_run: RunData | None = None) -> Path:
    if base_run is not None:
        filename = f"{safe_filename(base_run.header.run_id)}-vs-{safe_filename(run.header.run_id)}-report-card.png"
        return Path(filename)
    filename = f"{safe_filename(run.header.run_id)}-report-card.png"
    return Path(filename)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a display test report card PNG.")
    parser.add_argument("--input", required=True, type=Path, help="Input display test result folder.")
    parser.add_argument("--base-input", type=Path, default=None, help="Optional baseline result folder for curve comparison.")
    parser.add_argument("--base-label", default=None, help="Override baseline chart label in comparison mode.")
    parser.add_argument("--run-label", default=None, help="Override current-run chart label in comparison mode.")
    parser.add_argument("--output", type=Path, default=None, help="Output PNG path.")
    parser.add_argument("--reference-gamut", choices=sorted(REFERENCE_GAMUTS), default="ntsc")
    parser.add_argument("--render", choices=["basic", "advanced"], default="basic", help="Gamut rendering mode.")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--title", default="Display Test Report Card")
    parser.add_argument("--serial-number", default=None, help="Override display serial number.")
    parser.add_argument("--tester-version", default=None, help="Override tester version.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        run = load_run_folder(args.input, args)
        base_run = load_run_folder(args.base_input, args) if args.base_input else None
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = args.output or default_output_path(run, base_run)
    render_report_card(
        run,
        output,
        args.title,
        args.dpi,
        args.reference_gamut,
        args.render,
        base_run,
        args.run_label,
        args.base_label,
    )
    if base_run:
        for warning in base_run.warnings:
            print(f"warning(base): {warning}", file=sys.stderr)
    for warning in run.warnings:
        print(f"warning(run): {warning}", file=sys.stderr)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
