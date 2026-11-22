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
