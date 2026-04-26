# Implementation Plan

## Current Status

- Done: created the implementation repo.
- Done: copied PRDs into `prd/`.
- Done: copied latest 12.3" and 15.6" run fixtures into `test-data/`.
- Done: implemented the initial report-card generator in `src/display_report_card.py`.
- Done: added focused extraction tests in `tests/`.
- Done: verified PNG generation for both bundled fixture runs.
- Next: refine packaging, parser tests, and future artifact support as needed.

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
- Done: extract brightness curve from `test-brightness-linearity.json`.
- Add future-ready hook for structured 81-step brightness calibration artifacts.
- Done: extract gamma curve from `test-gamma-curve.json` and the current CSV artifact.
- Done: extract contrast measurements, including partial data from `ERROR` tests.
- Done: extract gamut and white-point metrics.

## Phase 3: Report Rendering

- Done: render one A4 landscape PNG using `matplotlib` Agg.
- Done: add header band with display and software identity fields.
- Done: add summary KPI band with executed pass rate.
- Done: add full test matrix.
- Done: add four chart panels:
  - brightness
  - gamma
  - contrast
  - gamut / white point
- Done: add footer observations when soak data is unavailable.

## Phase 4: Verification

- Done: generate a report for `test-data/12-3-nq1v1`.
- Done: generate a report for `test-data/15-6-0od`.
- Done: verify the gamma path fallback works despite Pi-side absolute paths in JSON.
- Done: verify the 15.6" contrast panel renders partial data while the matrix shows `ERROR`.
- Done: keep fixtures read-only during report generation.

## Phase 5: Packaging And Documentation

- Document CLI usage in `README.md`.
- Document Python dependencies.
- Done: add focused tests for fixture parsing and current gamma path fallback.
- Keep commits scoped to one implementation milestone at a time.

## Open Implementation Notes

- `matplotlib` and `numpy` are acceptable dependencies for v1.
- Reuse the parsing and fitting approach from `gamma-tools/visualize-gamma.py`, but render only a compact report-card gamma panel.
- Do not parse logs except as an explicit backward-compatibility fallback for brightness calibration.
- Do not mutate input run folders.
