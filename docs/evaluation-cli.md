# Evaluation CLI

Run rolling-origin evaluation from the canonical CSV or Parquet history contract
without importing internal Python functions:

```bash
python -m demand_forecast_kit.evaluation_cli history.csv \
  --initial-train-size 90 --horizon 14 --step 7 --season-length 7 \
  --output artifacts/evaluation.json
```

The command uses the seasonal-naive adapter as a deterministic baseline and
writes the canonical, SHA-256-fingerprint-bearing `BacktestReport` JSON. Each
fold is evaluated using only observations before its test window. The CLI does
not tune calibration or model parameters on holdout observations. Defaults are
intended for small examples; choose split sizes that match the cadence and
history length of the dataset.
