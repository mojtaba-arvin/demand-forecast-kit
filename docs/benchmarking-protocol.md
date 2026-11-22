# Benchmarking protocol

## Required report metadata

Every benchmark report must identify:

- dataset name, creator, source URL, DOI, license, and source-file SHA-256;
- preprocessing rules and canonical frequency;
- selected series and cohort assignment policy;
- initial training window, horizon, origin step, and any purged windows;
- model identifiers and versions, quantile levels, and random seeds;
- per-series and macro metrics, including undefined/skipped evaluations.

## Evaluation rules

1. Use chronological rolling-origin splits.
2. Fit model selection and calibration only on data available before each
   forecast origin.
3. Compare all candidate models on identical folds.
4. Report per-series outcomes and equal-series macro summaries; report
   volume-weighted summaries separately when useful.
5. Report pinball loss at each quantile, WQL, MASE, interval coverage, and
   interval width.
6. For inventory policies, report holding cost, shortage cost, unit fill rate,
   and cycle service level separately.
7. Keep a later untouched temporal holdout for any fitted adjustment.
8. Treat a benchmark from one retailer or one domain as domain-specific evidence.

## Dataset separation

UCI Online Retail measures gross outbound unit demand after excluding
cancellations and non-positive quantities. UCI Electricity Load Diagrams
measures quarter-hourly energy consumption for 370 clients. The latter is a
useful independent multi-series load benchmark but is not a retail SKU dataset.
Cross-domain results must not be presented as retail replenishment validation.
