# Implementation Plan

## Current Status

- Done: created the implementation repo.
- Done: copied PRDs into `prd/`.
- Done: copied latest 12.3" and 15.6" run fixtures into `test-data/`.
- Next: implement the data loading and extraction layer in `src/`.

## Phase 1: Loader And Metadata

- Create a lightweight Python entry point.
- Load one run folder from `--input`.
- Require `summary.json` and fail clearly if it is missing.
- Discover `raw/*.json` tests.
- Resolve header metadata from `report-metadata.json` when present, then from raw test files, then placeholders.
- Implement portable artifact path resolution:
  - run-folder relative path
  - raw-test-folder relative path
  - existing absolute path
  - `artifacts/<basename>` fallback

## Phase 2: Structured Data Extraction

- Extract test status rows for the matrix.
- Extract brightness curve from `test-brightness-linearity.json`.
- Add future-ready hook for structured 81-step brightness calibration artifacts.
- Extract gamma curve from `test-gamma-curve.json` and the current CSV artifact.
- Extract contrast measurements, including partial data from `ERROR` tests.
- Extract gamut and white-point metrics.

## Phase 3: Report Rendering

- Render one A4 landscape PNG using `matplotlib` Agg.
- Add header band with display and software identity fields.
- Add summary KPI band with executed pass rate.
- Add full test matrix.
- Add four chart panels:
  - brightness
  - gamma
  - contrast
  - gamut / white point
- Add footer observations when soak data is unavailable.

## Phase 4: Verification

- Generate a report for `test-data/12-3-nq1v1`.
- Generate a report for `test-data/15-6-0od`.
- Verify the gamma path fallback works despite Pi-side absolute paths in JSON.
- Verify the 15.6" contrast panel renders partial data while the matrix shows `ERROR`.
- Keep fixtures read-only during report generation.

## Phase 5: Packaging And Documentation

- Document CLI usage in `README.md`.
- Document Python dependencies.
- Add focused tests for parsing and path resolution if the implementation grows beyond a single script.
- Keep commits scoped to one implementation milestone at a time.

## Open Implementation Notes

- `matplotlib` and `numpy` are acceptable dependencies for v1.
- Reuse the parsing and fitting approach from `gamma-tools/visualize-gamma.py`, but render only a compact report-card gamma panel.
- Do not parse logs except as an explicit backward-compatibility fallback for brightness calibration.
- Do not mutate input run folders.
