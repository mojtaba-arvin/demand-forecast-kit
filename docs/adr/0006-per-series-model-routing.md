# ADR 0006: Leakage-aware per-series model routing

- Status: accepted for the first routing policy.
- Date: 2026-11-22

## Context

The project has several statistical and baseline adapters plus an evaluation engine. Choosing the best model from an aggregate report without a temporal cutoff can leak future validation results into an earlier forecast origin. Aggregating scores across all SKUs can also hide series-specific behavior.

## Decision

- Add an explicit observed timestamp range for each series to the versioned backtest report schema.
- Choose models per series using only that series' historical rolling-origin folds.
- Require the full observed history for the selected series to end strictly before the forecast origin.
- Default to WQL, require a configurable minimum number of defined validation folds, and support MASE or mean pinball loss only when explicitly selected.
- Require model-version equality between evidence and the currently registered adapter.
- Use Seasonal Naive as the default deterministic fallback; prefer it on metric ties within a configurable tolerance.
- Emit an auditable, deterministic routing decision artifact.

## Consequences

- Model decisions are series-specific and reproducible for a given backtest report and forecast origin.
- A new backtest is required whenever the forecast origin advances beyond the report's observed history.
- This router is a selector, not an automatic model trainer or a promise that validation rank will generalize to future demand.
- Callers remain responsible for passing only pre-origin observations to the selected adapter.
- Synthetic CI results validate plumbing and leakage guards, not model quality.
