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

## Planned CLI

```bash
python3 src/display_report_card.py \
  --input test-data/12-3-nq1v1 \
  --output out/run-20260426-085300-report-card.png
```

## Development Notes

- Use Python standard library plus `numpy` and `matplotlib`.
- Use the `matplotlib` Agg backend for headless Raspberry Pi execution.
- Treat input result folders as read-only.
- Keep implementation commits scoped to the phases in `PLAN.md`.
