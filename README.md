# disp-report-card

Display test result analyzer and report-card generator.

## Goal

Generate one lightweight A4 landscape PNG report card from one automated display test result folder.

The first implementation is per-run only. Cross-run comparison, dashboards, PDF output, and heavy report dependencies are out of scope for v1.

## Repository Layout

- `prd/` - product requirements and tester-extension notes.
- `src/` - report-card implementation.
- `test-data/12-3-nq1v1/` - latest 12.3" display fixture run.
- `test-data/15-6-0od/` - latest 15.6" display fixture run.
- `PLAN.md` - implementation phases and progress notes.

## Current Fixture Runs

- `test-data/12-3-nq1v1`: 20 tests, 17 pass, 2 skip, 1 error.
- `test-data/15-6-0od`: 20 tests, 16 pass, 2 skip, 2 errors.

Both fixtures include the current gamma extension:

- `raw/test-gamma-curve.json`
- `artifacts/gamma_curve_test-gamma-curve.csv`
- `artifacts/gamma_curve_test-gamma-curve_inverse_lut.csv`

## Usage

```bash
python3 src/display_report_card.py \
  --input test-data/12-3-nq1v1 \
  --output out/run-20260426-085300-report-card.png
```

Options:

- `--input` - required result folder.
- `--output` - output PNG path. Defaults to `<run_id>-report-card.png`.
- `--reference-gamut` - one of `srgb`, `rec709`, `dcip3`, `ntsc`, or `rec2020`; default is `ntsc`.
- `--render` - `basic` by default, or `advanced` for an optional CIE chromaticity background when `colour-science` is installed.
- `--dpi` - output DPI, default `200`.
- `--serial-number` - temporary header override.
- `--tester-version` - temporary header override.

The default gamut panel uses NTSC 1953 primaries with D65 white. It reports reference coverage,
relative measured area, measured white-point offset, and distance against the default D65 tolerance
ellipse of `0.010`.

## Verification

```bash
python3 -m py_compile src/display_report_card.py
python3 -m unittest discover -s tests

python3 src/display_report_card.py \
  --input test-data/12-3-nq1v1 \
  --output out/12-3-report-card.png

python3 src/display_report_card.py \
  --input test-data/15-6-0od \
  --output out/15-6-report-card.png

python3 src/display_report_card.py \
  --input test-data/15-6-0od \
  --output out/15-6-report-card-advanced.png \
  --render advanced
```

Expected output size at the default DPI is `2338 x 1654` pixels.

## Development Notes

- Use Python standard library plus `numpy` and `matplotlib`.
- Use the `matplotlib` Agg backend for headless Raspberry Pi execution.
- Keep `basic` rendering free of heavy scientific/reporting dependencies.
- Treat `advanced` rendering dependencies as optional host-PC enhancements; missing optional modules should warn and still produce a report.
- Treat input result folders as read-only.
- Keep implementation commits scoped to the phases in `PLAN.md`.
