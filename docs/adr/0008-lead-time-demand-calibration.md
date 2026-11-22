# ADR 0008: Calibrate lead-time demand with out-of-sample residual paths

- Status: accepted.
- Date: 2026-11-22

## Context

The forecast contract contains marginal daily quantiles and does not encode cross-period dependence. Inventory decisions require a distribution for the cumulative lead-time total. Summing daily quantiles, independently resampling daily residuals, or pooling different SKUs would invent dependence or erase relevant structure.

## Decision

- Use rolling-origin out-of-sample median forecast residuals from the same series and model; allow callers to pin the expected model version and enforce exact version matching in prequential diagnostics.
- Admit only folds whose full test window ends strictly before the target forecast origin.
- Greedily retain non-overlapping forecast windows to avoid counting repeated actual observations as independent paths.
- Resample complete residual trajectories with a seeded bootstrap, add them to the caller's median baseline path, clip daily demand at zero, then sum over lead time.
- Require a configurable minimum number of calibration paths and limit lead time to the backtest horizon.
- Provide a prequential backtest that evaluates later folds using only earlier completed residual paths.
- Provide an explicit adapter to the inventory scenario contract.

## Consequences

- Temporal residual dependence within each forecast horizon is retained.
- Calibration is same-series and same-model by default; no cross-series pooling is performed.
- The method assumes historical non-overlapping residual paths are representative of the target period. Distribution shift, sparse history, and conditional residual dynamics remain limitations.
- Coverage metrics are diagnostics, not guarantees. Real operational use requires sufficient historical origins and evaluation on the target SKU population.
