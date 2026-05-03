# disp-report-card

Display test result analyzer and report-card generator.

## Goal

Generate one lightweight A4 landscape PNG report card from an automated display test result folder,
with optional baseline/run overlay comparison.

Dashboards, PDF output, trend-history storage, and heavy runtime dependencies are out of scope for
the current tool.

## Repository Layout

- `prd/` - historical product requirements and tester-extension notes.
- `src/` - report-card implementation.
- `test-data/12-3-nq1v1/` - latest 12.3" display fixture run.
- `test-data/15-6-0od/` - latest 15.6" display fixture run.
- `PLAN.md` - implementation phases and progress notes.

## Current Fixture Runs

- `test-data/12-3-nq1v1`: 22 tests, 17 pass, 0 failed, 2 errors, 3 skipped.
- `test-data/15-6-0od`: 23 tests, 19 pass, 0 failed, 1 error, 3 skipped.

Both fixtures include the current gamma extension:

- `raw/test-gamma-curve.json`
- `artifacts/gamma_curve_test-gamma-curve.csv`
- `artifacts/gamma_curve_test-gamma-curve_inverse_lut.csv`

Both fixtures include a structured 81-step brightness calibration artifact. When present, the report
uses the structured calibration artifact before falling back to the older brightness-linearity data:

- `raw/test-brightness-calibration.json`
- `artifacts/brightness-calibration-81step.json`
- `artifacts/brightness-calibration-81step.csv`

Both fixtures include the local-dimming APL extension:

- `raw/test-local-dimming-apl.json`
- `artifacts/local-dimming-apl-sweep.json`
- `artifacts/local-dimming-apl-sweep.csv`

The 15.6" fixture is the current v5 sample run. It also includes:

- `raw/test-brightness-nits-verify.json`
- `artifacts/brightness-nits-verify.json`
- `raw/thermal-luminance-profile.csv`
- gamut backlight temperature metadata in `raw/test-color-gamut.json`

## Usage

```bash
python3 src/display_report_card.py \
  --input test-data/12-3-nq1v1 \
  --output out/12-3-report-card.png
```

For repeated use on a development host, install the local console command inside a virtualenv:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .

.venv/bin/display-report-card \
  --input test-data/12-3-nq1v1 \
  --output out/12-3-report-card.png
```

On Raspberry Pi targets, the direct script path remains the simplest basic-mode invocation when
dependencies are provided by apt packages.

Options:

- `--input` - required result folder.
- `--base-input` - optional baseline result folder; when provided, report charts overlay baseline and run curves.
- `--base-label` / `--run-label` - optional chart legend labels for comparison mode.
- `--output` - output PNG path. Defaults to `<run_id>-report-card.png`.
- `--reference-gamut` - one of `srgb`, `rec709`, `dcip3`, `ntsc`, or `rec2020`; default is `ntsc`.
- `--render` - `basic` by default, or `advanced` for an optional CIE chromaticity background when `colour-science` is installed.
- `--dpi` - output DPI, default `200`.
- `--serial-number` - temporary header override.
- `--tester-version` - temporary header override.

The default gamut panel uses NTSC 1953 primaries with D65 white. It reports reference coverage,
relative measured area, measured white-point offset, and distance against the default D65 tolerance
ellipse of `0.010`. If gamut backlight temperature metadata is present, the panel also reports the
temperature range and average during the gamut sweep.

When `raw/thermal-luminance-profile.csv` is present, the bottom chart row splits to add a
`Thermal White-Point Drift` panel. That panel shows the display white-point path during warm-up in
a zoomed CIE xy view with D65 tolerance, start/end temperature and luminance labels, runtime,
final D65 tolerance multiple, luminance drop summary, and the interpolated tolerance-exit
temperature when the run starts inside tolerance and later exits.

When `test-brightness-nits-verify` is present, the test matrix reports its pass/fail state and the
peak nits delta, for example `max 3.44%@20%`.

### Comparison Mode

Comparison mode overlays a baseline run and the current run on shared chart scales. FPGA labels
come from `raw/test-version-read.json`. Use two different run folders for a real firmware or panel
comparison; the example below uses the tracked 15.6" fixture as both inputs as a copy-paste smoke
test.

```bash
python3 src/display_report_card.py \
  --base-input test-data/15-6-0od \
  --input test-data/15-6-0od \
  --output out/15-6-self-compare.png

make compare BASE=test-data/15-6-0od RUN=test-data/15-6-0od \
  OUT=out/15-6-self-compare.png

make compare BASE=test-data/15-6-0od RUN=test-data/15-6-0od \
  BASE_LABEL=baseline RUN_LABEL=current OUT=out/15-6-self-compare.png
```

The test matrix remains run-focused and highlights result changes from the baseline. If labels are
not supplied, comparison charts use FPGA labels derived from `test-version-read`.

## Verification

```bash
make test

make test-data/12-3-nq1v1
make report-samples
make compare BASE=test-data/15-6-0od RUN=test-data/15-6-0od
make report-samples-advanced PYTHON=.venv/bin/python
make clean
```

The `test-data/<fixture>` make target writes `out/<fixture>-report-card.png`.

Expected output size at the default DPI is `2338 x 1654` pixels.

### Advanced Rendering On Debian/Ubuntu Hosts

Debian/Ubuntu may reject `pip install --user` with an externally managed environment error.
Use a repo-local virtualenv instead:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-deps 'colour-science==0.4.6'

.venv/bin/python src/display_report_card.py \
  --input test-data/15-6-0od \
  --output out/15-6-report-card-advanced.png \
  --render advanced

make report-samples-advanced PYTHON=.venv/bin/python
```

`python3-colour` is a different package and does not provide `colour.plotting`. Version
`0.4.6` avoids pulling NumPy 2 into a virtualenv that reuses apt-built Matplotlib/Shapely.

## Development Notes

- Use Python standard library plus `numpy` and `matplotlib`.
- Use the `matplotlib` Agg backend for headless Raspberry Pi execution.
- Keep `basic` rendering free of heavy scientific/reporting dependencies.
- Treat `advanced` rendering dependencies as optional host-PC enhancements; missing optional modules should warn and still produce a report.
- Treat input result folders as read-only.
- Keep implementation commits scoped to the phases in `PLAN.md`.
