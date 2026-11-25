# Operational planning API and worker

This layer adds tenant-scoped operational inputs around the forecasting library:
warehouses, stock snapshots, purchase orders, receipts, demand observations,
model-quality telemetry, retraining requests, and durable scheduled jobs.

The operational store is SQLite-backed and single-machine. It is suitable for
a local installation or a single-host service with durable storage. It is not
a distributed database, multi-host lock service, or high-availability SaaS
control plane.

## Start the API

Install the API extra and run the existing FastAPI factory:

```bash
python -m pip install -e ".[api]"
uvicorn demand_forecast_kit.api:create_app --factory
```

Operational routes live under `/v1/ops`. In development, when no API keys are
configured, requests use the isolated `local` tenant. Production mode fails
closed if keys are missing:

```bash
export DEMAND_FORECAST_ENV=production
export DEMAND_FORECAST_API_KEYS='[
  {
    "key_id": "warehouse-operator",
    "token_sha256": "<64-character-lowercase-sha256>",
    "tenant_id": "acme",
    "scopes": ["ops:read", "ops:write"]
  },
  {
    "key_id": "planning-admin",
    "token_sha256": "<64-character-lowercase-sha256>",
    "tenant_id": "acme",
    "scopes": ["ops:read", "ops:write", "ops:admin"]
  }
]'
```

Generate a token digest without storing the raw token in the configuration:

```bash
python -c 'import hashlib; print(hashlib.sha256(b"replace-with-a-long-random-token").hexdigest())'
```

Send the raw token as `Authorization: Bearer <token>`. The server stores only
the SHA-256 digest in its configuration. Supported scopes:

- `ops:read`: read tenant warehouses, stock, purchase orders, demand, schedules,
  model health, and model-selection results.
- `ops:write`: create warehouses, record stock/demand, receive purchase orders,
  and submit forecast outcomes.
- `ops:admin`: configure schedules and baselines, trigger ERPNext sync, and
  manage retraining queue state.

The older `/v1/forecasts`, `/v1/backtests`, `/v1/runs`, and
`/v1/artifacts` endpoints still use the shared local run registry. When API
keys are enabled, they additionally require the explicit `runs:shared` scope.
Do not grant that scope to tenant-isolated operational API keys unless shared
run visibility is intentional.

## Daily operational data

Create a warehouse:

```http
POST /v1/ops/warehouses
Authorization: Bearer <token>
Content-Type: application/json

{"warehouse_id":"WH-01","name":"Main warehouse","location_code":"main"}
```

Record an inventory snapshot:

```http
POST /v1/ops/inventory/snapshots

{
  "warehouse_id": "WH-01",
  "sku_id": "SKU-100",
  "quantity": 120,
  "reserved": 8,
  "backorders": 3,
  "source": "erp-import"
}
```

The operational inventory position is calculated as:

`on_hand - reserved + confirmed_open_purchase_order_inbound - backorders`.

Create purchase orders with one or more SKU lines at
`POST /v1/ops/purchase-orders`. Record partial or complete receipts at
`POST /v1/ops/purchase-orders/{order_id}/receipts`. Receipts move units from
confirmed inbound into on-hand stock in one SQLite transaction, so the
inventory position does not jump merely because a delivery was received.

Demand history is written to `POST /v1/ops/demand/observations` and retrieved
from `GET /v1/ops/demand/history/{warehouse_id}/{sku_id}`. Repeated imports for
the same tenant, warehouse, SKU, and observation timestamp use last-write-wins
semantics; this makes daily ERP imports retryable.

## ERPNext connector

ERPNext is the first supported ERP connector. Configure credentials only on
the API/worker host:

```bash
DEMAND_FORECAST_ERPNEXT_URL=https://erp.example.com
DEMAND_FORECAST_ERPNEXT_API_KEY=...
DEMAND_FORECAST_ERPNEXT_API_SECRET=...
```

Create the matching local warehouse, then call
`POST /v1/ops/erpnext/sync/{warehouse_id}` with an `ops:admin` key. The
connector reads ERPNext Warehouse/Bin, Sales Invoice/Sales Invoice Item, and
Purchase Order/Purchase Order Item records. It imports stock and reservations,
daily SKU demand (including zero-demand days between invoice dates), and open
or partially received purchase orders.

Operational sync uses independent tenant/warehouse watermarks for Bin, Sales
Invoice, and Purchase Order. Each query replays a bounded five-minute overlap
by default, and writes are idempotent. Watermarks advance only after the
corresponding resource batch has been applied successfully. Run one sync at a
time per tenant/warehouse: the SQLite watermarks are not a distributed lock. Edited invoices
replace their prior per-invoice contribution; cancelled invoices remove that
contribution and recompute affected SKU/day totals. Cancelled purchase orders
are removed from confirmed inbound inventory. Source-modified timestamps fence
out stale invoice and purchase-order updates that arrive after newer changes.

Demand rows already owned by another source are not silently overwritten. A
source conflict fails the invoice batch and leaves its watermark unchanged so
an operator can reconcile the source-of-truth conflict. Incremental sync
detects ERPNext cancellations and edits, but cannot detect hard-deleted source
documents that no longer appear in modified-time queries; an operator-led full
reconciliation outside this incremental path is required after source-system
hard deletes.

### Operator-triggered full reconciliation

Incremental sync deliberately does not interpret an empty delta as a deletion.
After ERPNext hard deletes or a suspected source/local divergence, run the
explicit full-snapshot command from the host that owns the SQLite database.
The tenant and warehouse must already be configured in that same local store:

```bash
export DEMAND_FORECAST_ERPNEXT_URL="https://erp.example.com"
export DEMAND_FORECAST_ERPNEXT_API_KEY="..."
export DEMAND_FORECAST_ERPNEXT_API_SECRET="..."

demand-forecast-erpnext-reconcile \
  --database ./state/operations.sqlite \
  --tenant-id acme \
  --warehouse-id WH-01 \
  --confirm-full-snapshot
```

The ERPNext integration user must have complete list/read access to Bin,
Sales Invoice, Sales Invoice Item, Purchase Order, and Purchase Order Item for
the intended site. If a resource returns empty while local imports exist, the
command aborts rather than interpreting a permission-filtered result as mass
deletion. Only after independently verifying permissions and confirming that
the resource is genuinely empty should an operator add
`--allow-empty-snapshot`.

The command reads Bin, Sales Invoice, and Purchase Order resources twice,
including all pages. It aborts before local writes if the two snapshots differ
or a remote request fails. Run it during a quiet ERPNext window: Frappe offset
pagination is not a transactionally consistent database snapshot, and a
two-pass match is a practical consistency check rather than a source lock.

After a verified snapshot:
- Missing invoice IDs have their per-invoice demand contributions removed,
  affected SKU/day totals recomputed, and a source-time tombstone is recorded just beyond the last observed Modified
  timestamp. Stale incremental events cannot resurrect those contributions.
- Missing imported purchase orders are cancelled, removing their remaining
  confirmed inbound quantity and fencing stale updates.
- Missing Bin records receive zero-quantity deletion snapshots only when the latest
  local inventory source is still `erpnext:Bin`. A newer manual inventory
  snapshot is preserved. Incremental and full imports also leave a latest
  manual/other-source inventory snapshot untouched rather than silently
  replacing its source-of-truth value.
- Per-resource watermarks advance only after the corresponding reconciliation
  work completes.

The operation changes only local SQLite state; the ERPNext connector remains
read-only. It is idempotent and can be rerun after an interrupted local apply.
The command is intentionally explicit because a full snapshot can remove local
records that no longer exist upstream. Do not use it while the source is being
bulk-edited or while another sync is running for the same tenant/warehouse.

The connector is read-only: it does not create purchase orders, alter stock
ledgers, or submit ERPNext documents. It uses the Frappe token header and does
not log credentials. Resource pages use stable ordering. Transient connection
failures, HTTP 429, and selected 5xx responses are retried with bounded
exponential backoff; a numeric `Retry-After` header is honored. Client errors
such as HTTP 400/401 are not retried. Configure `max_retries`,
`retry_backoff_seconds`, and `sync_overlap_seconds` on `ERPNextClient`
when embedding the connector.

## SQLite backup and restore

SQLite is a single-host operational store. Back it up with the online backup API;
do not copy only the main database file while the API or worker is writing, because
committed data may still reside in the WAL.

Create and verify an atomic backup:

```bash
demand-forecast-db backup \
  ./state/operations.sqlite \
  ./backups/operations-$(date -u +%Y%m%dT%H%M%SZ).sqlite

demand-forecast-db verify ./backups/operations-YYYYMMDDTHHMMSSZ.sqlite
```

The command reports a SHA-256 digest, SQLite integrity result, and foreign-key
check. Store backups encrypted, off-host, and under a documented retention
policy. A backup on the same host is not disaster recovery.

Restore only in a maintenance window after stopping every API and worker process
that can open the target database:

```bash
demand-forecast-db verify ./backups/operations-YYYYMMDDTHHMMSSZ.sqlite

demand-forecast-db restore \
  ./backups/operations-YYYYMMDDTHHMMSSZ.sqlite \
  ./state/operations.sqlite \
  --confirm-services-stopped

demand-forecast-db verify ./state/operations.sqlite
```

Restore verifies the backup, stages a temporary database, checks its integrity
and foreign keys, then atomically replaces the target and removes stale WAL/SHM/journal sidecars. The explicit confirmation
is required because replacing an open SQLite database is unsafe. Keep the old
database and backup until the restored API/worker pass a smoke check. This tool
does not schedule backups or upload them to remote storage; configure those
controls in the deployment environment.

## Scheduled work

Create schedules with `POST /v1/ops/schedules`. Supported types:

- `forecast_refresh`: payload includes `warehouse_id`, `sku_id`, and optional
  `horizon`, `season_length`, and `quantiles`.
- `replenishment_review`: payload includes `warehouse_id`, `sku_id`,
  `lead_time_demand_quantiles`, `underage_cost`, `overage_cost`, and
  optional `pack_size`.
- `model_health`: payload includes warehouse/SKU/model/version and optional
  monitoring window, minimum sample count, and degradation ratio.

A replenishment review requires a calibrated cumulative lead-time demand
quantile curve. Do not sum marginal daily forecast quantiles to manufacture
that curve.

Run the worker continuously on the same durable state directory:

```bash
demand-forecast-worker --tenant-id acme --poll-seconds 15
```

Use `--once` for a single poll. Jobs are claimed with expiring leases and
unique ownership tokens. Completion and retry release require the token returned
by the claim, so a worker resuming after lease expiry cannot complete or release
a newer worker's claim. The API's `POST /v1/ops/schedules/claim-due` response
includes the token; pass it as JSON `{"lease_token":"..." }` to
`POST /v1/ops/schedules/{job_id}/complete`. Schedule listings do not expose
active lease tokens.

Failed jobs release their lease and are eligible for retry. If a worker has
already lost ownership, it records the stale-lease failure without releasing
the current owner's lease. The worker currently uses the deterministic
Seasonal Naive adapter for scheduled forecast refreshes. Model-specific routing
can be extended without changing the schedule store.

## Model lifecycle

Submit realized forecast outcomes to `POST /v1/ops/monitoring/outcomes`. A
baseline MAE must be registered from an out-of-sample validation set at
`POST /v1/ops/monitoring/baselines`. The health endpoint compares the recent
rolling MAE with that frozen baseline. It emits a degradation alert only after
the configured minimum number of outcomes and queues a deduplicated retraining
request.

`POST /v1/ops/monitoring/model-selection` ranks models by recent out-of-sample
MAE for one SKU/location. If evidence is insufficient, it returns the declared
fallback rather than selecting a model from too little data.

The `ModelLifecycle` coordinator accepts model-specific trainer callbacks.
A trainer receives the request and the SKU's demand history, then returns a
new model version and a validation MAE/sample count. The coordinator persists
the new baseline only after the trainer succeeds. `OperationalWorker` can
process queued requests automatically after a trainer is registered with
`worker.register_trainer(model_id, trainer)`. No generic trainer is silently
assumed: adapters in this package have different fitting semantics. The
standalone CLI has no built-in trainer registrations yet, so model-specific
fitting must be supplied by the embedding worker process.

Retraining claims are recovered after one hour without an update. This covers a
worker crash between claiming a request and recording its result; the next
worker cycle returns the abandoned request to the queue. Keep individual
training runs below this recovery window, or extend the recovery timeout in
the embedding worker before running long jobs. Trainers should be idempotent:
a process can stop after writing a validated baseline but before marking the
request complete, causing the request to be retried after recovery.

Each claim also receives a unique ownership token. Recovery invalidates the old
token, and completion requires the current token. A worker that resumes after
its claim expired therefore cannot complete a newer worker's request. Baseline
persistence and successful completion are committed in one SQLite transaction,
so a stale worker cannot publish a model baseline after losing ownership. API
clients must pass the token returned by the claim endpoint when finishing a
request. This fencing protects retraining claims; the SQLite scheduler remains
a single-host mechanism, not a distributed multi-host lease service.

Submit realized replenishment outcomes to
`POST /v1/ops/monitoring/policy-outcomes`. The store calculates realized
holding/shortage cost, fill rate, and cycle service level. The
`/v1/ops/monitoring/policy-selection` endpoint and `policy_review` schedule
rank policy versions by observed mean cost, subject to a minimum evidence
count. This selects among policy versions that were explicitly recorded; it
does not silently rewrite cost assumptions or activate a new policy. Automatic
parameter tuning and policy activation remain outside this release.

## Operational boundaries

- SQLite is a single-host store; do not mount it as a multi-writer network DB.
- API keys are tenant-scoped for `/v1/ops`; shared legacy run endpoints require
  a separate `runs:shared` scope.
- The ERPNext connector is read-only.
- The scheduler is durable but must be run by the operator as a worker process.
- Forecast outcomes must be matched to the exact forecast origin, target time,
  model ID, and model version.
- A model-health alert is a monitoring signal, not proof of business impact.
