# End-to-end smoke

Run the deterministic offline pipeline with:

```bash
python evals/run_end_to_end_smoke.py
```

The runner creates a synthetic daily SKU history, executes a rolling-origin
backtest, produces a forecast, calibrates cumulative lead-time demand only from
completed non-overlapping folds before the forecast origin, compares two
inventory policies on the same realized scenario, and simulates delayed
replenishment with backorders. It then stores the evaluation JSON through
`FileArtifactStore`, completes an idempotent `SQLiteRunRegistry` run, and
records an immutable inventory decision.

The generated `artifacts/synthetic-end-to-end-decision.json` is uploaded by
the regular quality workflow. This verifies integration and serialization
plumbing only. It is not a real-data benchmark, forecast-quality result,
inventory-savings claim, or production-readiness certification.
