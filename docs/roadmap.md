# Project roadmap and milestone status

**Status date:** 2026-11-25  
**Status baseline:** main after PR #67, commit \`9cc351bdd4c93bf153387cfb276df95911315c57\`

This document records implementation boundaries and the next engineering priorities.
A feature is not considered production-ready merely because its unit tests pass.

## Milestone status

| Area | Status | Verified scope and remaining boundary |
| --- | --- | --- |
| Forecasting and rolling-origin evaluation | Implemented | Quantile contracts, baseline/statistical/optional ML adapters, chronological evaluation, leakage-aware model routing, deterministic evaluation artifacts. No universal accuracy claim. |
| Lead-time calibration and inventory evaluation | Implemented, empirical limits remain | Same-series/model residual-path calibration, prequential diagnostics, inventory cost/fill-rate evaluation, and UCI real-data plus purged temporal holdout experiments. Width/bias adjustments expose a coverage–sharpness trade-off; no global correction is enabled. Intermittent-specific results remain too small to promote. |
| Model selection and version routing | Implemented | Per-SKU out-of-sample ranking, minimum evidence, strict forecast-origin checks, exact (model_id, model_version) adapter resolution, and explicit fallback. |
| Operational API and local persistence | Alpha / single-host | Tenant-scoped API, SQLite operational store, durable scheduler, lease fencing, model-health monitoring, and retraining queue. SQLite is not a multi-host database or SaaS control plane. |
| ERPNext integration | Implemented, read-only incremental sync | Independent tenant/warehouse/resource watermarks, bounded overlap, idempotent Bin/Invoice/Purchase Order replay, invoice edit/cancellation reconciliation, PO cancellation, and stale-source fencing. Hard-deleted source documents still require operator-led full reconciliation; source conflicts fail closed. |
| Model lifecycle and artifact persistence | Partial | Monitoring, retraining queue, stale-claim fencing, atomic baseline completion, and a content-addressed persistent ModelArtifactRegistry with explicit activation/rollback are implemented. OperationalWorker supports opt-in exact-active-version resolution through explicitly registered media-type loaders; the CLI does not dynamically import plugins. No built-in model-specific trainer is assumed. |
| Replenishment policy lifecycle | Implemented, opt-in single-host control plane | Tenant-scoped immutable Newsvendor definitions, SHA-256 identity, CAS activation, explicit rollback, append-only history, and worker enforcement/audit are implemented. Policy ranking remains advisory; no automatic promotion. SQLite is single-host. |
| Performance regression calibration | Blocked on reference hardware | Benchmark harness and environment-aware comparator exist. Issue #31 still requires at least 10 independent full-profile runs on one fixed Linux x64 self-hosted reference runner before a regression gate can be enabled. |

## Non-negotiable correctness boundaries

1. Never sum marginal daily forecast quantiles to create cumulative lead-time demand quantiles. Inventory decisions require a separately validated cumulative lead-time distribution.
2. A successful training callback or lower validation MAE does not activate a model. Candidate registration, evaluation evidence, explicit activation, and rollback are separate steps.
3. Model artifacts are opaque bytes. The registry does not unpickle, import, or execute them. A deployment must supply a reviewed loader for its artifact media type.
4. The artifact registry and operational SQLite stores are single-host components. Do not describe them as distributed coordination or multi-host SaaS infrastructure.
5. ERPNext remains read-only. Incremental sync handles supported edits/cancellations but cannot detect hard deletes; SQLite watermarks are not distributed locks.
6. Synthetic smoke reports prove implementation plumbing, not forecast quality, customer savings, or business impact.
7. Do not tune calibration parameters on the same chronological holdout used to report their performance.

## Next engineering priorities

1. **Close Issue #31 with real reference hardware.** Collect 10 independent full-profile workflow artifacts on the same fixed runner, characterize variance, then enable only a justified environment-matched regression gate. Do not substitute GitHub-hosted runners or one multi-repeat workflow for the required independent runs.
2. **Extend empirical calibration evidence.** The UCI purged holdout already exists; next use a larger cohort or independent dataset and more non-overlapping origins, report per-SKU coverage/bias and inventory cost, and keep corrections disabled until the result replicates.

See [versioned replenishment policies](policy-lifecycle.md) for validation, activation, rollback, and worker enforcement. See the [UCI benchmark and purged holdout report](benchmarks/uci-online-retail.md) for cohort-level coverage, SKU dispersion, baseline bias, and the width/bias adjustment trade-off.

## Recent verified delivery

- PR #49: retraining claim fencing and atomic baseline completion.
- PR #50: ERPNext warehouse/Bin pagination.
- PR #51: exact model-version adapter routing.
- PR #52: scheduled-job lease fencing.
- PR #53: bounded ERPNext retries.
- PR #54: persistent model artifacts, evaluation digests, explicit activation/rollback, and immutable activation history.
- PR #62: active model artifact resolution in the operational worker and tenant-scoped versioned replenishment policy lifecycle.
- PR #67: incremental ERPNext sync with per-resource watermarks, overlap replay, invoice correction/cancellation reconciliation, and purchase-order cancellation.

PR #54 merged as \`ac32fc4e0d56689fa2b87d33c16094f9302ccf86\`. Its PR CI and Release Candidate passed, including 398 tests, 92.18% coverage, strict Pyright, Python 3.13/3.14 compatibility, dependency audit, REUSE, wheel build/install, and source-distribution build/install.

## External runner prerequisite for Issue #31

The GitHub connection used during this work could not read the repository's Actions runner inventory because that endpoint requires additional administration access. Therefore this document does not claim that a suitable runner is absent or present. Inspect it with:

\`\`\`bash
gh api repos/mojtaba-arvin/demand-forecast-kit/actions/runners \\
  --jq '.runners[] | [.name, .status, ([.labels[].name] | join(","))] | @tsv'
\`\`\`

If no dedicated runner with labels \`self-hosted,linux,x64,demand-forecast-reference\` is available, register one on a stable Linux x64 host. See the [reference benchmark runner runbook](benchmark-reference-runner.md) for registration, immutable revision tagging, ten independent dispatches, and closure criteria. Do not fabricate benchmark artifacts or enable the gate before calibration.
