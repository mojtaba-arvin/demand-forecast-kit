# Command-line interface

Install the package with its CLI entry points, then run a forecast from CSV or Parquet history:

```bash
demand-forecast history.csv --horizon 14 --format json --output forecast.json
demand-forecast history.csv --horizon 14 --format csv --output forecast.csv
demand-forecast history.parquet --horizon 14 --format parquet --output forecast.parquet
```

CSV and Parquet outputs are long-form tables with one row per series, horizon step, and quantile. JSON preserves the nested forecast response contract. Tabular formats require an output path.

Run a reproducible rolling-origin evaluation with:

```bash
demand-forecast-evaluate history.csv --initial-train-size 90 --horizon 14 --step 7 --output evaluation.json
```

The evaluation command uses the seasonal-naive baseline and the same canonical history schema. The report includes the dataset fingerprint, split configuration, per-fold forecasts, and aggregate metrics. It does not tune models or calibration on the final holdout.


Both Forecast CLI and Rolling-origin Evaluation CLI persist completed runs by
default under `.demand-forecast-kit/` (SQLite registry plus SHA-256 artifact
objects). Override this location with `--state-dir PATH`. JSON output includes
the run ID and artifact digest; CSV/Parquet forecast rows include the same
provenance fields. Repeating an identical input/configuration is idempotent.
