# ADR 0009: Use a licensed public transaction dataset for empirical calibration evaluation

- Status: accepted.
- Date: 2026-11-22

## Context

Phase 6 was verified only with synthetic data. A real-data evaluation is needed to expose SKU-frequency effects and test the residual-path calibration workflow beyond synthetic plumbing. The repository must not silently download or redistribute third-party data in CI.

## Decision

- Use UCI Online Retail (Daqing Chen, 2015; DOI 10.24432/C5BW33; CC BY 4.0) as the first reproducible public transaction benchmark.
- Keep the raw workbook outside version control and require the user to download it explicitly.
- Define the target as gross outbound demand: exclude cancellation invoices and non-positive quantities, aggregate positive quantities by SKU/day, and fill no-sale days with zero.
- Evaluate deterministic dense, intermittent, and very-intermittent cohorts with a stable hash-based SKU sample.
- Compare Seasonal Naive, Croston SBA, and TSB using identical rolling-origin folds and prequential 7-/14-day lead-time calibration.
- Record source SHA-256, dataset citation, license, preprocessing, split configuration, per-SKU results, and macro cohort summaries.

## Consequences

- The benchmark is reproducible without adding a dataset download to CI or committing the raw workbook.
- Return exclusion changes the target from net movement to gross outbound demand and must remain explicit in all interpretations.
- One retailer's 2010-2011 history is not representative evidence for all industries or current demand regimes.
- Empirical results remain pending until the runner is executed against the source workbook; no forecast-quality or savings claims are implied by the implementation alone.
