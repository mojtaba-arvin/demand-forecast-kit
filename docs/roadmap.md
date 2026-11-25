# Project roadmap and milestone status

**Status date:** 2026-11-25  
**Status baseline:** main after PRs #72, #77, and #78; latest delivery is recorded below.

This document records implementation boundaries and the next engineering priorities.
A feature is not considered production-ready merely because its unit tests pass.

## Milestone status

| Area | Status | Verified scope and remaining boundary |
| --- | --- | --- |
| Forecasting and rolling-origin evaluation | Implemented | Quantile contracts, baseline/statistical/optional ML adapters, chronological evaluation, leakage-aware model routing, deterministic evaluation artifacts. No universal accuracy claim. |
| Lead-time calibration and inventory evaluation | Implemented, independent-retailer evidence in progress | Same-series/model residual-path calibration, prequential diagnostics, inventory cost/fill-rate evaluation, and chronological holdout experiments. UCI Online Retail II adds 60 SKUs and 68 prequential origins per series, but is the same retailer as the original UCI dataset. An opt-in local M5/Walmart adapter validates source hashes and deterministically selects item/store cohorts from the first 180 days; no M5 benchmark results are claimed yet. No global correction is enabled. |
| Model selection and version routing | Implemented | Per-SKU out-of-sample ranking, minimum evidence, strict forecast-origin checks, exact (model_id, model_version) adapter resolution, and explicit fallback. |
| Operational API and local persistence | Alpha / supported single-host deployment in progress | Tenant-scoped API, SQLite operational store, durable scheduler, lease fencing, model-health monitoring, retraining queue, local online backup/restore CLI, API readiness probes, tenant-scoped worker heartbeat/status, Docker Compose API/worker profile, encrypted Restic off-host backup/retention scripts, daily systemd timer, and Compose configuration validation in CI. A real off-host restore drill and host-specific smoke validation remain external acceptance work. |
| ERPNext integration | Implemented, read-only incremental + explicit full reconciliation | Independent tenant/warehouse/resource watermarks, bounded overlap, idempotent Bin/Invoice/Purchase Order replay, invoice edit/cancellation reconciliation, stale-source fencing, and operator-triggered double-snapshot reconciliation for hard deletes. Full reconciliation preserves newer manual stock and tombstones deleted invoice/PO state; live ERPNext validation remains deployment-specific. |
| Model lifecycle and artifact persistence | Partial | Monitoring, retraining queue, stale-claim fencing, atomic baseline completion, and a content-addressed persistent ModelArtifactRegistry with explicit activation/rollback are implemented. OperationalWorker supports opt-in exact-active-version resolution through explicitly registered media-type loaders; the CLI does not dynamically import plugins. No built-in model-specific trainer is assumed. |
| Replenishment policy lifecycle | Implemented, opt-in single-host control plane | Tenant-scoped immutable Newsvendor definitions, SHA-256 identity, CAS activation, explicit rollback, append-only history, and worker enforcement/audit are implemented. Policy ranking remains advisory; no automatic promotion. SQLite is single-host. |
| Performance regression calibration | Deferred | Issue #31 remains open. The fixed Linux x64 self-hosted runner is not a prerequisite for feature development or empirical forecast evaluation; defer the hardware-specific variance study and regression gate until a suitable external host is available. Do not infer performance targets from GitHub-hosted runner timings. |

## Non-negotiable correctness boundaries

1. Never sum marginal daily forecast quantiles to create cumulative lead-time demand quantiles. Inventory decisions require a separately validated cumulative lead-time distribution.
2. A successful training callback or lower validation MAE does not activate a model. Candidate registration, evaluation evidence, explicit activation, and rollback are separate steps.
3. Model artifacts are opaque bytes. The registry does not unpickle, import, or execute them. A deployment must supply a reviewed loader for its artifact media type.
4. The artifact registry and operational SQLite stores are single-host components. Do not describe them as distributed coordination or multi-host SaaS infrastructure.
5. ERPNext remains read-only. Incremental sync cannot detect hard deletes; the explicit operator-triggered full-snapshot reconciliation handles that case. SQLite watermarks are not distributed locks.
6. Synthetic smoke reports prove implementation plumbing, not forecast quality, customer savings, or business impact.
7. Do not tune calibration parameters on the same chronological holdout used to report their performance.
8. Cross-domain electricity results are forecasting evidence only; never use them as retail SKU, inventory-cost, or replenishment-service evidence.

## Next engineering priorities

1. **Extend independent retail evidence (Issue #75).** The opt-in M5/Walmart local-file adapter is implemented, but the authorized Kaggle files and empirical run are still external. Next, run the prequential 7/14-day calibration only on the pre-holdout history and reserve the final 28 labeled days as an untouched inventory-policy holdout. Keep global correction disabled until coverage and service/cost outcomes replicate.
2. **Validate ERPNext full reconciliation in a representative deployment (Issue #73).** The explicit double-snapshot operator command is implemented; exercise it against a real ERPNext test site, confirm pagination/permissions, and retain the read-only boundary.
3. **Advance operational readiness (Issue #74).** PR #72/#77 provide local SQLite backup/restore and API probes. PR #80 adds a constrained Compose profile, encrypted Restic off-host snapshots, retention, and daily systemd scheduling. PR #79 adds worker heartbeat and tenant isolation. A real restore drill on an independent host, with API/worker smoke checks, remains required before claiming operational readiness.
4. **Resume Issue #31 after external host provisioning.** Collect 10 independent full-profile artifacts on one fixed Linux x64 runner, characterize variance, and enable only an environment-matched threshold justified by the measured distribution.

See [versioned replenishment policies](policy-lifecycle.md) for validation, activation, rollback, and worker enforcement. See the [UCI retail benchmark](benchmarks/uci-online-retail.md) and [independent electricity benchmark](benchmarks/uci-electricity-load.md) for dataset-specific protocols and evidence.

## Recent verified delivery

- PR #49: retraining claim fencing and atomic baseline completion.
- PR #50: ERPNext warehouse/Bin pagination.
- PR #51: exact model-version adapter routing.
- PR #52: scheduled-job lease fencing.
- PR #53: bounded ERPNext retries.
- PR #54: persistent model artifacts, evaluation digests, explicit activation/rollback, and immutable activation history.
- PR #62: active model artifact resolution in the operational worker and tenant-scoped versioned replenishment policy lifecycle.
- PR #67: incremental ERPNext sync with per-resource watermarks, overlap replay, invoice correction/cancellation reconciliation, and purchase-order cancellation.
- PR #70: independent UCI Electricity benchmark provenance and Issue #31 deferral decision.
- PR #71: operator-triggered ERPNext full reconciliation for hard-deleted Bin, Sales Invoice, and Purchase Order records (ADR 0013).
- PR #72: SQLite online backup, integrity verification, and controlled restore CLI (ADR 0014).
- PR #77: explicit API liveness and dependency readiness probes (ADR 0015).
- PR #78: UCI Online Retail II prequential 7/14-day lead-time calibration diagnostics; real-data benchmark run #45633743983 completed successfully.
- PR #80: single-host Compose deployment, encrypted Restic full-state backup/restore scripts, retention, and systemd daily backup timer (ADR 0017).
- PR #81: deterministic M5/Walmart local-file preprocessing adapter with source SHA-256 provenance and frozen item/store cohorts; no raw Kaggle data is stored in the repository.
- PR #79: tenant-scoped worker heartbeat/status, stale-heartbeat detection, graceful shutdown, and expanded tenant-isolation regression tests (ADR 0016).
- PR #82: CI validation of compose.yaml against .env.example when Docker Compose is available.
- PR #83/#84: change-aware UCI Online Retail benchmark gating, including merge-base detection for work branches.
- PR #85: merge-base-aware gating for the independent UCI Online Retail II benchmark.

## Issue #31 deferral decision

The reference-runner calibration task is deliberately deferred, not treated as a release blocker. Continue feature development, dataset evaluation, and correctness work on GitHub-hosted CI. The performance comparator stays informational and no machine-specific regression gate is enabled. When a stable Linux x64 host becomes available, resume the issue's original acceptance criteria without substituting mismatched hosted-runner measurements.

