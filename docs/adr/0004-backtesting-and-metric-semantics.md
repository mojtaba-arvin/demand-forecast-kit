# ADR 0004: Backtesting and metric semantics

- Status: accepted for the initial evaluation engine.
- Date: 2026-11-22

## Context

Model selection requires reproducible out-of-sample comparisons. Forecasting metrics have implementation variants, especially normalized weighted quantile loss and undefined seasonal scales.

## Decision

- Evaluate each series independently with chronological rolling origins.
- Use expanding training windows by default; an optional maximum training size enables sliding windows.
- Use the median quantile for point-error MASE.
- Define WQL as twice the sum of pinball losses across requested quantiles and observations divided by the sum of absolute actual demand.
- Represent MASE and WQL as null when their denominator/scale is undefined; never substitute zero or an epsilon.
- Report central interval coverage for symmetric quantile pairs. Default pairs are P10-P90 and P05-P95 (nominal 80% and 90%).
- Macro-average fold metrics in model summaries. This avoids implicitly weighting high-volume series more heavily; pooled/weighted summaries may be added later with an explicit contract.
- Serialize deterministic JSON with a dataset content fingerprint, adapter versions, config, seed, forecasts, and fold metrics. Do not embed a generation timestamp.
- CI produces a small synthetic smoke artifact to verify the full report-writing path; the synthetic output is not an accuracy benchmark.

## Consequences

Metrics from different WQL definitions or quantile sets are not directly comparable. A zero-scale MASE and all-zero-denominator WQL are explicitly undefined. The evaluation engine provides evidence for later routing but does not automatically select a model.
