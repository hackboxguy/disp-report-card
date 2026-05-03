# Implementation Plan

## Current Status

- Done: created the implementation repo.
- Done: copied PRDs into `prd/`.
- Done: copied latest 12.3" and 15.6" run fixtures into `test-data/`.
- Done: implemented the initial report-card generator in `src/display_report_card.py`.
- Done: added focused extraction tests in `tests/`.
- Done: verified PNG generation for both bundled fixture runs.
- Done: refreshed the 12.3" fixture with the v6 fresh 81-step brightness calibration run.
- Done: switched the default gamut panel to NTSC 1953 primaries with D65 white reference.
- Done: added gamut coverage, relative area, D65 tolerance, and white-point distance indicators.
- Done: added `--render basic|advanced`; `basic` stays lightweight and `advanced` uses optional host-PC chromaticity rendering when available.
- Done: added packaging metadata, a console entry point, repeatable make targets, and edge-case parser tests.
- Done: consume the structured 81-step brightness calibration artifact when it is present.
- Done: consume and render the local-dimming APL sweep artifact when it is present.
- Done: add comparison mode for baseline/run overlays and changed-test highlighting.
- Done: add comparison label overrides for concise firmware labels in plots.
- Done: add optional thermal white-point drift rendering from live thermal luminance CSV.
- Done: add brightness-nits-verify pass/fail status metric with peak delta extraction.
- Done: add thermal D65 tolerance multiple and tolerance-exit marker.
- Done: add gamut backlight temperature parsing and rendering.
- Done: refresh the 15.6" sample fixture to the v5 run with current artifacts.
- Next: add future soak/stability artifact support when the tester artifact is available.

## Phase 1: Loader And Metadata

- Done: create a lightweight Python entry point.
- Done: load one run folder from `--input`.
- Done: require `summary.json` and fail clearly if it is missing.
- Done: discover `raw/*.json` tests.
- Done: resolve header metadata from `report-metadata.json` when present, then from raw test files, then placeholders.
- Done: implement portable artifact path resolution:
  - run-folder relative path
  - raw-test-folder relative path
  - existing absolute path
  - `artifacts/<basename>` fallback

## Phase 2: Structured Data Extraction

- Done: extract test status rows for the matrix.
- Done: prefer structured 81-step brightness calibration artifacts and fall back to `test-brightness-linearity.json`.
- Done: extract gamma curve from `test-gamma-curve.json` and the current CSV artifact.
- Done: extract contrast measurements, including partial data from `ERROR` tests.
- Done: extract gamut and white-point metrics, including reference coverage and D65 tolerance distance.
- Done: extract optional gamut backlight temperature metadata.
- Done: extract local-dimming APL sweep metrics, including skipped APL steps.
- Done: extract brightness-nits-verify peak delta from the structured artifact, with log fallback.
- Done: extract thermal white-point drift samples from `raw/thermal-luminance-profile.csv`.

## Phase 3: Report Rendering

- Done: render one A4 landscape PNG using `matplotlib` Agg.
- Done: add header band with display and software identity fields.
- Done: add summary KPI band with executed pass rate.
- Done: add full test matrix.
- Done: add chart panels:
  - brightness
  - gamma
  - contrast
  - gamut / white point with NTSC reference, coverage, and D65 tolerance
- Done: add local-dimming APL as a bottom-row chart panel.
- Done: add thermal white-point drift as an optional bottom-row chart panel when thermal data is present.
- Done: add D65 tolerance exit label and final tolerance multiple to the thermal drift panel.
- Done: add gamut temperature range/average to the gamut metric badge when provided by the test run.
- Done: add optional advanced gamut rendering mode for host PCs.
- Done: add footer observations when soak data is unavailable.

## Phase 4: Verification

- Done: generate a report for `test-data/12-3-nq1v1`.
- Done: generate a report for `test-data/15-6-0od`.
- Done: verify the gamma path fallback works despite Pi-side absolute paths in JSON.
- Done: verify legacy partial contrast data can render while the matrix shows `ERROR`.
- Done: verify the current 15.6" v5 fixture renders full contrast, APL, thermal drift, gamut temperature, and brightness-nits-verify data.
- Done: keep fixtures read-only during report generation.

## Phase 5: Packaging And Documentation

- Done: document CLI usage in `README.md`.
- Done: document Python dependencies and optional advanced rendering behavior.
- Done: add focused tests for fixture parsing and current gamma path fallback.
- Done: add `pyproject.toml` with `display-report-card` console entry point.
- Done: add `Makefile` targets for tests and sample report regeneration.
- Done: add tests for missing `summary.json`, `report-metadata.json` header overrides, missing gamma artifacts, and malformed optional raw JSON.
- Done: update README and plan notes for comparison mode, current fixtures, thermal drift, brightness-nits-verify, and gamut temperature support.
- Keep commits scoped to one implementation milestone at a time.

## Open Implementation Notes

- `matplotlib` and `numpy` are acceptable dependencies for v1.
- Reuse the parsing and fitting approach from `gamma-tools/visualize-gamma.py`, but render only a compact report-card gamma panel.
- Reuse the useful gamut ideas from `imagetools/scripts/analyze-2d-gamut.py`, but keep CSV parsing and polygon coverage local for the default Pi-friendly path.
- `--render advanced` may use optional host-PC packages such as `colour-science`; it must warn and fall back gracefully when they are not installed.
- Avoid log parsing except for explicit backward-compatibility fallbacks such as brightness-nits-verify when its artifact is missing.
- Do not mutate input run folders.
