# FastAPI and persisted runs

Install the optional HTTP dependencies and start the factory-created app:

```bash
python -m pip install -e ".[api]"
uvicorn demand_forecast_kit.api:create_app --factory
```

The `/v1/forecasts` and `/v1/backtests` routes return their normal result
plus a `run` object containing the SQLite run ID, completion status, and
SHA-256 artifact reference. Run identity is deterministic over the canonical
input fingerprint, model/version, and configuration; retrying the same request
is idempotent.

A replenishment request can include both `run_id` and `decision_key` to
persist the recommendation as an immutable inventory decision linked to that
run. Supplying only one of these fields is rejected. The SQLite schema uses
triggers to reject direct updates and deletes of inventory-decision rows.

By default, API and CLI processes share the `.demand-forecast-kit/` state
directory in the current working directory. Set
`DEMAND_FORECAST_STATE_DIR` for the API process and pass the same path with
`--state-dir` to either CLI to share the registry and content-addressed
artifact objects. Keep this directory on durable, backed-up storage; it is a
single-machine SQLite/file-store design, not a multi-host transaction service.

The shared `RunService` emits structured JSON log records and maintains
thread-safe process-local metrics. The app exposes the service at
`app.state.run_service`; an embedding application may expose
`metrics_snapshot()` through its own authenticated monitoring route. The
library deliberately does not expose an unauthenticated metrics endpoint.
