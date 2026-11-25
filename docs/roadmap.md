# Project roadmap and milestone status

**Status date:** 2026-11-25  
**Status baseline:** main after PR #54, commit \`ac32fc4e0d56689fa2b87d33c16094f9302ccf86\`

This document records implementation boundaries and the next engineering priorities.
A feature is not considered production-ready merely because its unit tests pass.

## Milestone status

| Area | Status | Verified scope and remaining boundary |
| --- | --- | --- |
| Forecasting and rolling-origin evaluation | Implemented | Quantile contracts, baseline/statistical/optional ML adapters, chronological evaluation, leakage-aware model routing, deterministic evaluation artifacts. No universal accuracy claim. |
| Lead-time calibration and inventory evaluation | Implemented, empirical limits remain | Same-series/model residual-path calibration, prequential diagnostics, inventory cost/fill-rate evaluation, and public UCI transaction benchmarks. Dense/intermittent UCI cohorts showed undercoverage; no correction is enabled by default. |
| Model selection and version routing | Implemented | Per-SKU out-of-sample ranking, minimum evidence, strict forecast-origin checks, exact (model_id, model_version) adapter resolution, and explicit fallback. |
| Operational API and local persistence | Alpha / single-host | Tenant-scoped API, SQLite operational store, durable scheduler, lease fencing, model-health monitoring, and retraining queue. SQLite is not a multi-host database or SaaS control plane. |
| ERPNext integration | Partial | Read-only Frappe connector with pagination and bounded retries for transient failures. Sync is still a full scan; per-resource watermarks, incremental import, cancellation/correction reconciliation, and deletion handling are not implemented. |
| Model lifecycle and artifact persistence | Partial | Monitoring, retraining queue, stale-claim fencing, atomic baseline completion, and a content-addressed persistent ModelArtifactRegistry with explicit activation/rollback are implemented. The registry is not yet wired into OperationalWorker adapter loading. No built-in model-specific trainer is assumed. |
| Replenishment policy lifecycle | Partial | Realized policy outcomes and evidence-based ranking exist. Persisted policy definitions/versions, active-policy state, explicit activation, and rollback are not implemented. |
| Performance regression calibration | Blocked on reference hardware | Benchmark harness and environment-aware comparator exist. Issue #31 still requires at least 10 independent full-profile runs on one fixed Linux x64 self-hosted reference runner before a regression gate can be enabled. |

## Non-negotiable correctness boundaries

1. Never sum marginal daily forecast quantiles to create cumulative lead-time demand quantiles. Inventory decisions require a separately validated cumulative lead-time distribution.
2. A successful training callback or lower validation MAE does not activate a model. Candidate registration, evaluation evidence, explicit activation, and rollback are separate steps.
3. Model artifacts are opaque bytes. The registry does not unpickle, import, or execute them. A deployment must supply a reviewed loader for its artifact media type.
4. The artifact registry and operational SQLite stores are single-host components. Do not describe them as distributed coordination or multi-host SaaS infrastructure.
5. ERPNext remains read-only. Pagination and retries do not imply incremental synchronization or complete correction/deletion reconciliation.
6. Synthetic smoke reports prove implementation plumbing, not forecast quality, customer savings, or business impact.
7. Do not tune calibration parameters on the same chronological holdout used to report their performance.

## Next engineering priorities

1. **Connect model artifacts to runtime loading.** Add explicit media-type loader registration, load only the activated exact model version, preserve the current fallback when loading fails, and test restart/reload/rollback behavior. Do not activate newly trained candidates automatically.
2. **Version replenishment policies.** Persist immutable policy definitions and versions, validate cost/pack constraints, require compare-and-swap activation, and provide explicit rollback. Keep automatic policy tuning/activation disabled until independent outcome evidence supports it.
3. **Implement ERPNext incremental synchronization.** Use per-tenant/warehouse/resource watermarks with an overlap window; replay changed invoices and purchase orders idempotently; recompute affected SKU/day demand when old documents are edited or cancelled; advance watermarks only after successful application. Preserve read-only credentials and behavior.
4. **Close Issue #31 with real reference hardware.** Collect 10 independent full-profile workflow artifacts on the same fixed runner, characterize variance, then enable only a justified environment-matched regression gate. Do not substitute GitHub-hosted runners or one multi-repeat workflow for the required independent runs.
5. **Continue empirical calibration research.** Use purged chronological holdouts and report per-SKU coverage/bias. Do not enable a global correction based on the current UCI sample.

## Recent verified delivery

- PR #49: retraining claim fencing and atomic baseline completion.
- PR #50: ERPNext warehouse/Bin pagination.
- PR #51: exact model-version adapter routing.
- PR #52: scheduled-job lease fencing.
- PR #53: bounded ERPNext retries.
- PR #54: persistent model artifacts, evaluation digests, explicit activation/rollback, and immutable activation history.

PR #54 merged as \`ac32fc4e0d56689fa2b87d33c16094f9302ccf86\`. Its PR CI and Release Candidate passed, including 398 tests, 92.18% coverage, strict Pyright, Python 3.13/3.14 compatibility, dependency audit, REUSE, wheel build/install, and source-distribution build/install.

## External runner prerequisite for Issue #31

The GitHub connection used during this work could not read the repository's Actions runner inventory because that endpoint requires additional administration access. Therefore this document does not claim that a suitable runner is absent or present. Inspect it with:

\`\`\`bash
gh api repos/mojtaba-arvin/demand-forecast-kit/actions/runners \\
  --jq '.runners[] | [.name, .status, ([.labels[].name] | join(","))] | @tsv'
\`\`\`

If no dedicated runner with labels \`self-hosted,linux,x64,demand-forecast-reference\` is available, register one on a stable Linux x64 host. See the [reference benchmark runner runbook](benchmark-reference-runner.md) for registration, immutable revision tagging, ten independent dispatches, and closure criteria. Do not fabricate benchmark artifacts or enable the gate before calibration.
