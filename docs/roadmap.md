# Project roadmap and milestone status

**Status date:** 2026-11-25  
**Status baseline:** main at the start of this work; see the merged PR history for the exact revision.

This document records implementation boundaries and the next engineering priorities.
A feature is not considered production-ready merely because its unit tests pass.

## Milestone status

| Area | Status | Verified scope and remaining boundary |
| --- | --- | --- |
| Forecasting and rolling-origin evaluation | Implemented | Quantile contracts, baseline/statistical/optional ML adapters, chronological evaluation, leakage-aware model routing, deterministic evaluation artifacts. No universal accuracy claim. |
| Lead-time calibration and inventory evaluation | Implemented, empirical limits remain | Same-series/model residual-path calibration, prequential diagnostics, inventory cost/fill-rate evaluation, and UCI real-data plus purged temporal holdout experiments. Latest retail rerun (20 slices, 10 SKUs/cohort, 16 origins/series) has mean P80 coverage 64.81% (46.88%–81.88%); dense/intermittent cohorts remain under-covered. Cross-domain electricity evidence is being expanded separately and cannot substitute for retail calibration. No global correction is enabled. |
| Model selection and version routing | Implemented | Per-SKU out-of-sample ranking, minimum evidence, strict forecast-origin checks, exact (model_id, model_version) adapter resolution, and explicit fallback. |
| Operational API and local persistence | Alpha / single-host | Tenant-scoped API, SQLite operational store, durable scheduler, lease fencing, model-health monitoring, retraining queue, and online backup/integrity/controlled-restore CLI. Encrypted off-host retention, scheduled backups, restore drills, and a multi-host database boundary remain deployment work. |
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

1. **Extend independent empirical evidence (Issue #75).** Run the complete UCI Electricity 370-series benchmark with immutable data/runtime provenance; inspect per-series dispersion and failure modes rather than only a macro score. Keep the retail-specific calibration gate disabled until larger retail cohorts or another independent retail dataset replicate the result.
2. **Validate ERPNext full reconciliation in a representative deployment (Issue #73).** The explicit double-snapshot operator command is implemented; exercise it against a real ERPNext test site, confirm pagination/permissions, and retain the read-only boundary.
3. **Advance operational readiness (Issue #74).** Online SQLite backup, integrity verification, controlled restore (PR #72), and API liveness/readiness probes (PR #76) are implemented. Add encrypted off-host retention, scheduled backup policy, periodic restore drills, tenant-isolation tests, worker heartbeat/scheduler recovery, and a supported deployment boundary before claiming production deployment.
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
- PR #77: explicit API liveness and dependency readiness probes.

## Issue #31 deferral decision

The reference-runner calibration task is deliberately deferred, not treated as a release blocker. Continue feature development, dataset evaluation, and correctness work on GitHub-hosted CI. The performance comparator stays informational and no machine-specific regression gate is enabled. When a stable Linux x64 host becomes available, resume the issue's original acceptance criteria without substituting mismatched hosted-runner measurements.

