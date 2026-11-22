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

The raw workbook is not committed. The dedicated GitHub Actions workflow
`.github/workflows/uci-online-retail-benchmark.yml` downloads the official UCI
archive at run time, extracts the workbook, executes this benchmark, and uploads
the JSON report as a 30-day artifact. For a local run, download the workbook
from UCI and install the optional benchmark dependencies:

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
- Freeze cohort membership using only the first 180 calendar days, matching the
  initial training window. No observations from later evaluation periods influence
  cohort assignment.
- Require at least eight active sales days within that initial window.
- Dense: activity on at least 50% of initial-window days.
- Intermittent: activity on 5% to less than 50% of initial-window days.
- Very intermittent: activity on less than 5% of initial-window days.
- Select up to 10 SKUs per cohort by stable SHA-256 ordering of StockCode.
  This is deterministic, not a volume-weighted or random sample.

## Evaluation design

- Cohort membership is frozen from the initial 180-day training window.
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

## Real-data run: 2026-11-22

The first run on commit `da76574...` used full-history cohort assignment and is
superseded. After freezing cohorts to the initial training window, the corrected
workflow completed successfully on commit
`d25e8fd680cd2df212b4678fcee350f9adcb96d6`:

- [GitHub Actions run #45038895069](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45036995061)
- [JSON artifact](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45036995061/artifacts/14759959986)
- Official UCI workbook extracted by the runner: 23,715,344 bytes.
- Source workbook SHA-256: `43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d`.
- Panel: 374 calendar days (2010-12-01 through 2011-12-09), 30 selected SKUs
  (10 per cohort), 16 rolling origins per SKU/model/lead-time evaluation.
- Evaluations: 180 (30 SKUs × 3 models × 2 lead times); none skipped.

Macro-average results (lower pinball loss is better; P80 interval coverage has
an 0.80 nominal target):

| Cohort | Lead days | Model | P50 pinball | P80 coverage | P10 pinball | P90 pinball |
|---|---:|---|---:|---:|---:|---:|
| Dense | 7 | Croston SBA | 33.612 | 0.656 | 14.869 | 26.341 |
| Dense | 7 | Seasonal Naive | 43.622 | 0.500 | 33.598 | 27.632 |
| Dense | 7 | TSB | 35.771 | 0.688 | 17.755 | 25.873 |
| Dense | 14 | Croston SBA | 57.057 | 0.625 | 25.729 | 47.891 |
| Dense | 14 | Seasonal Naive | 77.673 | 0.469 | 62.238 | 49.418 |
| Dense | 14 | TSB | 58.914 | 0.600 | 29.318 | 46.113 |
| Intermittent | 7 | Croston SBA | 37.506 | 0.669 | 14.087 | 34.261 |
| Intermittent | 7 | Seasonal Naive | 44.594 | 0.544 | 34.446 | 35.617 |
| Intermittent | 7 | TSB | 39.245 | 0.588 | 20.972 | 36.063 |
| Intermittent | 14 | Croston SBA | 70.714 | 0.631 | 25.352 | 61.296 |
| Intermittent | 14 | Seasonal Naive | 86.912 | 0.544 | 66.895 | 58.797 |
| Intermittent | 14 | TSB | 75.103 | 0.575 | 40.338 | 58.399 |
| Very intermittent | 7 | Croston SBA | 1.996 | 0.819 | 0.659 | 1.607 |
| Very intermittent | 7 | Seasonal Naive | 2.117 | 0.775 | 2.075 | 1.448 |
| Very intermittent | 7 | TSB | 1.766 | 0.725 | 1.074 | 1.383 |
| Very intermittent | 14 | Croston SBA | 3.900 | 0.775 | 1.253 | 2.115 |
| Very intermittent | 14 | Seasonal Naive | 4.967 | 0.750 | 4.178 | 2.575 |
| Very intermittent | 14 | TSB | 3.592 | 0.750 | 2.332 | 2.232 |

### Findings

- Croston SBA has the lowest P50 pinball loss in all four dense and
  intermittent cohort/lead-time slices. TSB has the lowest P50 loss in both
  very-intermittent slices; no single model wins every cohort.
- P80 interval coverage remains below its 0.80 target for dense and
  intermittent SKUs (0.469–0.688 and 0.544–0.669 respectively). These intervals
  should not be treated as calibrated inventory protection bounds.
- Very-intermittent coverage is closer to nominal: Croston SBA reaches 0.819
  at seven days and 0.775 at fourteen days. Other model/lead-time combinations
  range from 0.725 to 0.775.
- These are descriptive results for one deterministic 30-SKU sample, not proof
  of universal model superiority. Per-SKU outcomes vary; see the full artifact.

## Interpretation limits

This is a single retailer's 2010–2011 history, not a representative global
benchmark. Removing returns defines a gross-demand target and can change the
interpretation relative to net sales. The deterministic cohort sample is
small by design. Results must not be presented as universal forecast accuracy,
inventory savings, or causal business impact. Compare models only on identical
SKUs, origins, lead times, and preprocessing. The reported metrics are empirical
results from the exact source workbook identified by its SHA-256 above.
