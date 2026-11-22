# SPEC 0006: Real-data lead-time calibration benchmark

- Status: implemented as an opt-in benchmark runner; empirical results pending a local UCI workbook run.
- Scope: compare Phase 6 residual-path calibration on deterministic dense, intermittent, and very-intermittent SKU cohorts from UCI Online Retail.
- Non-goals: ship raw transaction data, download datasets in CI, claim generalization beyond one retailer, or claim inventory savings.

## Data contract

1. The source is UCI Online Retail (Daqing Chen, 2015), DOI 10.24432/C5BW33, CC BY 4.0.
2. Raw workbook bytes are hashed and the SHA-256 is recorded in the output.
3. Cancellation invoices and non-positive quantities are excluded. The resulting target is gross outbound demand, not net accounting movement.
4. Positive quantities are summed by StockCode and calendar day; no-sale days are explicitly filled with zero.
5. SKUs with fewer than eight active days are excluded.
6. Dense, intermittent, and very-intermittent activity cohorts use thresholds 50%, 5%-50%, and below 5%, respectively.
7. At most the configured number of SKUs per cohort are selected by stable SHA-256 ordering of StockCode.

## Evaluation

1. Use an expanding 180-day training window, 14-day forecast horizon, and 7-day origin step.
2. Compare Seasonal Naive, Croston SBA, and TSB on the same cohort series and chronological folds.
3. Calibrate cumulative lead-time demand for 7- and 14-day lead times from same-series, same-model completed residual paths.
4. Use 250 bootstrap draws, a minimum of five non-overlapping historical paths, and a fixed seed.
5. Report per-series cumulative quantile coverage, P80 interval coverage, and pinball loss.
6. Aggregate cohort summaries as equal-weight macro averages across SKUs; retain per-series results and skipped-evaluation reasons.

## Acceptance

- Offline tests cover cancellation/return filtering, daily aggregation, zero filling, deterministic cohort assignment, and invalid sample size.
- The runner requires explicit local access to the UCI workbook and never downloads it.
- The output includes source attribution, license, source-file hash, preprocessing, model/split configuration, per-SKU results, and macro cohort summaries.
- CI runs only offline unit tests; it does not download or redistribute the dataset.
- No accuracy or inventory-savings claim is made until the benchmark has been run and independently reviewed.
