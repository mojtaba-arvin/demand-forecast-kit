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

## Real-demand UCI run

The dedicated real-data workflow also runs:

```bash
python evals/run_uci_online_retail_e2e.py \
  "data/raw/Online Retail.xlsx" \
  --origin-offset-days 300
```

This variant uses an actual SKU demand history and an untouched seven-day
holdout from UCI Online Retail. It performs rolling-origin evaluation and
lead-time calibration strictly before the forecast origin, compares two
inventory policies on the same actual-demand scenario, simulates supplier
delay/backorders, and writes the inventory decision to SQLite. The workflow
uploads the resulting report and SHA-256 provenance.

The public dataset has no stock-on-hand, supplier, or cost fields. Inventory
position, supplier delay, and cost rates are explicit scenario assumptions;
the output is a reproducible technical evaluation, not observed retailer
inventory performance or a savings claim.
