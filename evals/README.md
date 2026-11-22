# Evaluation

Evaluation is separate from unit tests and model training. The initial repository contains no third-party datasets and performs no network dataset or model-weight download in CI.

## Rolling-origin evaluation

Run the deterministic synthetic smoke evaluation locally with:

\`\`\`bash
python evals/run_synthetic_smoke.py
\`\`\`

The command creates artifacts/synthetic-baseline-evaluation.json. GitHub Actions uploads the same generated report as the synthetic-evaluation-report artifact. It is a pipeline smoke artifact, not a benchmark result or a claim of forecasting quality.

Use demand_forecast_kit.backtesting.run_backtest for user datasets and compare models only with matching dataset fingerprints, split settings, quantile levels, and seeds.

## Metrics and interpretation

- MASE is the median-forecast MAE divided by the in-sample seasonal-naive scale. A zero or unavailable scale is undefined (null).
- WQL is twice the sum of pinball losses across the requested quantiles and observations divided by total absolute actual demand. A zero denominator is undefined (null).
- Pinball loss is reported per quantile.
- Central interval coverage is reported for symmetric quantile pairs (default 80% and 90%).
- Model summaries macro-average series/folds; they are not volume-weighted pooled metrics.

Future evaluations should report these metrics by dataset, horizon, and series segment, plus inventory decision cost under documented lead-time and cost assumptions. Record data provenance in datasets/DATASETS.lock. Do not compare results across different splits, frequencies, quantile sets, or leakage policies as if they were equivalent.

## Dataset leakage

Do not bundle external evaluation or training datasets until source terms, content hash, retrieval date, and intended use have been verified and locked. Report cold-start/post-release datasets separately when foundation-model pretraining overlap is plausible.
