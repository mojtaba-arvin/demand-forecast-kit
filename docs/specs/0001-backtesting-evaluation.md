# SPEC 0001: Rolling-origin backtesting and evaluation

- Status: implemented on work/backtesting-evaluation; CI verification pending.
- Scope: deterministic chronological evaluation of one or more quantile forecast adapters on canonical demand history.
- Non-goals: automatic model selection/routing, hyperparameter tuning, conformal calibration, hierarchical reconciliation, external dataset downloads, benchmark claims, and GPU execution.

## Contracts

1. Input contains canonical series_id, timestamp, and non-negative finite demand; duplicate series/timestamp keys and null required values are errors.
2. Each series is sorted chronologically and evaluated independently. A split trains only on rows strictly earlier than its test window.
3. Rolling splits use an initial training size, fixed forecast horizon, and configurable origin step. Optional maximum training size switches to sliding windows.
4. Every adapter receives the same split, requested quantile levels, and explicit seed. Returned series ID, horizon, and quantile levels must match.
5. MASE uses the in-sample seasonal-naive scale from training rows and the median forecast. It is null when scale is zero or cannot be computed.
6. WQL is 2 * sum(pinball losses across quantiles and observations) / sum(abs(actual demand)); it is null when the actual-demand denominator is zero.
7. Pinball loss is reported per quantile. Interval coverage is reported for symmetric central intervals (default 80% and 90%) whose lower and upper quantiles must be requested.
8. Short series are explicitly listed as skipped. No result is silently omitted.
9. The report contains model ID/version, split boundaries, seed, dataset SHA-256 fingerprint, predictions, and metrics. JSON serialization is canonical and contains no wall-clock timestamp.

## Acceptance criteria

- Unit tests cover split chronology, expanding/sliding windows, metric formulae, undefined denominators, adapter conformance, multiple models, multiple series, skipped series, invalid input, reproducible serialization, and artifact SHA-256.
- CI runs tests without downloading datasets or model weights.
- Ruff, strict Pyright, pytest with at least 90% branch-aware core coverage, pip-audit, and REUSE lint pass.
- A synthetic evaluation smoke run produces a downloadable CI artifact; it is not a benchmark accuracy claim.
- No benchmark accuracy claim is added to README. A future model router must consume these artifacts and cannot choose a model from an unverified local score.

## Interpretation constraints

Fold summaries are macro-averages across evaluated series/folds, not pooled estimates weighted by transaction volume. Compare models only when dataset fingerprint, split config, quantile levels, and seed match. WQL values are comparable only with the same quantile set and evaluation window.
