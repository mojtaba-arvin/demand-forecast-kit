# Phase 7: UCI Online Retail empirical calibration benchmark

## Purpose

This is an opt-in empirical benchmark for the Phase 6 lead-time residual-path
calibrator. It evaluates dense, intermittent, and very-intermittent SKU cohorts
on a real transaction dataset and compares Seasonal Naive, Croston SBA, and TSB.

## Dataset and attribution

- Dataset: [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online-retail)
- Creator: Daqing Chen
- Citation: Chen, D. (2015). *Online Retail*. UCI Machine Learning Repository.
- DOI: https://doi.org/10.24432/C5BW33
- License: CC BY 4.0
- Original workbook: `Online Retail.xlsx`

The raw workbook is not committed and CI does not download it. Download the
workbook from UCI, then install the optional benchmark dependencies:

```bash
python -m pip install -e ".[benchmark,dev]"
```

Run the benchmark:

```bash
python evals/run_uci_online_retail_benchmark.py /path/to/Online\\ Retail.xlsx
```

For a smaller development run, use `--max-skus-per-cohort 3`. The default is
10 SKUs per cohort.

## Preprocessing contract

- Exclude cancellation invoices (InvoiceNo beginning with `C`, case-insensitive).
- Exclude non-positive quantities, including returns. This is intentional:
  the target is gross outbound unit demand, not net accounting movement.
- Aggregate positive quantities by StockCode and calendar day.
- Fill days without a sale with zero after constructing a complete daily calendar.
- Require at least eight active sales days before cohort assignment.
- Dense: activity on at least 50% of calendar days.
- Intermittent: activity on 5% to less than 50% of calendar days.
- Very intermittent: activity on less than 5% of calendar days.
- Select up to 10 SKUs per cohort by stable SHA-256 ordering of StockCode.
  This is deterministic, not a volume-weighted or random sample.

## Evaluation design

- 180-day expanding training window.
- 14-day forecast horizon, 7-day origin step.
- Lead times: 7 and 14 days.
- Quantiles: P10, P50, P90.
- Models: Seasonal Naive, Croston SBA, and TSB.
- Residual-path calibration: 250 bootstrap draws, at least five strictly earlier
  non-overlapping calibration paths, with Phase 6's model-version and leakage guards.
- Prequential evaluation reports per-SKU cumulative quantile coverage, P80
  interval coverage, and pinball loss. Cohort summaries are unweighted
  macro-averages across SKUs.

## Interpretation limits

This is a single retailer's 2010–2011 history, not a representative global
benchmark. Removing returns defines a gross-demand target and can change the
interpretation relative to net sales. The deterministic cohort sample is
small by design. Results must not be presented as universal forecast accuracy,
inventory savings, or causal business impact. Compare models only on identical
SKUs, origins, lead times, and preprocessing. No benchmark result is valid until
the script has actually been run against the downloaded source workbook.
