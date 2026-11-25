# UCI Online Retail II benchmark

## Provenance

- Creator: Daqing Chen
- Citation: Chen, D. (2012). *Online Retail II*. UCI Machine Learning Repository.
- DOI: https://doi.org/10.24432/C5CG6D
- Source: https://archive.ics.uci.edu/dataset/502/online+retail+ii
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Size: 1,067,371 transaction rows across two historical worksheets.
- Coverage: 1 December 2009 to 9 December 2011.

## Why this dataset

Online Retail II adds an expanded two-year transaction history and more
intermittent product histories than the original Online Retail release. It is
used to evaluate SKU-frequency cohorts and model comparisons on a larger retail
history. It is a second UCI release from the same retailer and creator, not an
independent retailer or independent commercial environment.

The separate UCI Electricity Load Diagrams benchmark provides cross-domain
dense multi-series evidence. Its results must not be described as retail
forecast validation.

## Preprocessing

The runner combines both workbook sheets, excludes cancellation invoices and
non-positive quantities, drops rows with missing/blank StockCode or invalid
quantity/date, aggregates positive unit quantities by StockCode/day, and fills
no-sale calendar days with zero. This measures gross outbound unit demand,
not net accounting movement or return-adjusted demand.

Cohorts are frozen from the initial 180-day training window. The runner compares
Seasonal Naive, Croston SBA, and TSB on identical rolling-origin folds and
reports MASE, WQL, per-quantile pinball loss, central interval coverage, model
versions, dataset fingerprints, and per-series fold summaries.

## Prequential cumulative lead-time calibration

The benchmark report now includes a separate `lead_time_calibration` section.
It evaluates 7- and 14-day cumulative demand quantiles using the same
prequential residual-path calibrator as the original Online Retail experiment:

- 180-day initial training window, 14-day forecast horizon, and 7-day origin step.
- 250 bootstrap draws per eligible forecast origin.
- At least five strictly earlier, non-overlapping residual paths before a
  target origin can be calibrated.
- P10/P50/P90 cumulative lead-time quantile coverage, P80 interval coverage,
  pinball loss, per-SKU results, and cohort/model/lead-time macro summaries.
- Failed eligibility is recorded in `lead_time_calibration.skipped`; it is
  never silently counted as a successful evaluation.

This is a prequential evaluation, not a tuned correction experiment. No global
scale or bias parameter is fitted from these outcomes. Forecast origins overlap
in calendar time and must not be treated as independent samples for confidence
intervals or significance tests. The 2010–2011 Online Retail II data comes from
the same retailer as the original UCI Online Retail release; it expands the SKU
and time sample but does not establish cross-retailer generalization.

Never sum marginal daily forecast quantiles to create cumulative lead-time
demand quantiles. The report uses the dedicated residual-path calibration
method for cumulative demand.

## Reproduce

Download the official UCI workbook and run:

```bash
python evals/run_uci_online_retail_ii_benchmark.py online_retail_II.xlsx \
  --max-skus-per-cohort 20 \
  --output artifacts/uci-online-retail-ii-benchmark.json
```

The raw workbook is not committed. The report records the source-file SHA-256,
worksheet names, attribution, license, and preprocessing contract.

## Interpretation limits

- Both UCI retail datasets originate from the same retailer; they do not
  establish cross-retailer generalization.
- Removing returns and cancellations estimates gross outbound unit demand.
- Zero-filled no-sale days assume a product was available for sale; stockout
  censoring is not observed and may bias demand downward.
- Macro metrics weight SKUs equally. Volume-weighted results should be reported
  separately if needed.
- Synthetic CI tests validate code paths, not the real-data benchmark results.


## Verified run — 22 November 2026

The real-data run completed successfully on the same preprocessing and model contract:

- Workflow run: [45069409648](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45069409648)
- Report artifact: `uci-online-retail-ii-benchmark`, artifact ID `14772627774`
- Source workbook SHA-256: `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`
- 739 calendar days, 60 selected SKUs (20 per cohort), 78 rolling origins per SKU.
- 14,040 per-SKU/model/fold records; zero skipped evaluations.

| Cohort | Model | MASE | WQL | Mean pinball | Central 80% coverage |
|---|---|---:|---:|---:|---:|
| Dense | Seasonal Naive | 1.105 | 5.500 | 9.535 | 82.6% |
| Dense | Croston SBA | 0.995 | 5.514 | 8.074 | 63.9% |
| Dense | TSB | **0.930** | **4.283** | **8.052** | 63.9% |
| Intermittent | Seasonal Naive | 0.859 | 8.721 | 3.216 | 87.5% |
| Intermittent | Croston SBA | 1.086 | 10.745 | 2.781 | 79.9% |
| Intermittent | TSB | **0.752** | **7.842** | **2.584** | 77.8% |
| Very-intermittent | Seasonal Naive | 1.587 | 23.437 | 0.765 | 92.3% |
| Very-intermittent | Croston SBA | 2.986 | **8.539** | 0.645 | 83.7% |
| Very-intermittent | TSB | **1.488** | 12.313 | **0.605** | 79.7% |

TSB has the lowest MASE and mean pinball loss in every cohort; Croston SBA has the lowest WQL for very-intermittent demand. Dense Croston SBA/TSB central-80% coverage is only 63.9%, so those uncalibrated intervals are not suitable as inventory protection bounds. This expanded dataset is from the same retailer, not independent-retailer evidence.
