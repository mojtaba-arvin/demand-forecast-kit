# SPEC 0003: Leakage-aware per-series model routing

- Status: implemented on `work/per-series-model-routing`; CI verification pending.
- Scope: deterministic selection of a registered forecast adapter for one demand series using only historical out-of-sample evidence.
- Non-goals: online learning, automatic model fitting, hyperparameter search, dynamic ensemble weights, cross-series transfer learning, and production accuracy claims.

## Inputs and evidence

1. The selector consumes a `BacktestReport` produced by the existing rolling-origin engine and an explicit forecast origin.
2. The report records each series' observed start and end timestamps. The target series' complete observed history must end strictly before the forecast origin.
3. Only evaluations for the requested series are considered. Folds must end before the forecast origin and cannot exceed the report's declared history end.
4. Evidence is grouped by model ID and must refer to exactly one model version matching the currently registered adapter. Stale or mixed-version evidence is an error.
5. `wql` is the default routing metric. `mase` and mean per-fold pinball loss are supported as explicit alternatives.
6. Undefined metric values are excluded. A model must have at least `min_folds` defined historical scores.
7. Candidate fold scores are macro-averaged for the requested series. There is no cross-SKU pooling or transaction-volume weighting.
8. Ties within a configurable absolute tolerance prefer the configured fallback baseline; remaining ties use lexicographic model ID ordering.
9. If no candidate has enough valid evidence, return the configured fallback adapter with an explicit `used_fallback` flag and a null score.

## Output and auditability

A routing decision records series ID, forecast origin, history end, dataset fingerprint, metric, selected model ID/version, score, evidence fold count, fallback use, and sorted candidate scores. The routing artifact is canonical JSON and is written atomically with a SHA-256 digest.

## Safety against temporal leakage

A report whose target series history ends at or after the forecast origin is rejected. This check is performed before model ranking and is independent of the fold-level end timestamps. Callers must provide forecast history values only through the selected origin when they subsequently invoke the chosen adapter.

The selector does not treat model summaries as routing evidence because those summaries aggregate folds and series without retaining the cutoff context required for a causal decision.

## Acceptance criteria

- Backtest artifacts preserve the observed timestamp range for every series.
- Tests prove independent per-series decisions, metric-based ranking, fallback behavior, deterministic tie-breaking, stale-version rejection, undefined-metric handling, cutoff enforcement, and atomic deterministic artifact output.
- Base CI runs the router tests without installing optional statistical dependencies and uploads a synthetic routing artifact.
- Synthetic decisions validate the selection pipeline only and must not be represented as forecasting benchmark results.
