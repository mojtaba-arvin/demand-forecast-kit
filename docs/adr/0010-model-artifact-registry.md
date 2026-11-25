# ADR 0010: Persistent model artifacts with explicit activation

- Status: accepted.
- Date: 2026-11-25

## Context

The operational lifecycle can queue and coordinate model-specific training,
and the run artifact store already provides content-addressed local bytes.
However, the project has no durable model-version catalog, no persistent
active-version pointer, and no explicit rollback history. A training callback
returning a version string and validation metrics is not proof that a loadable
model artifact exists.

## Decision

- Add a SQLite-backed, single-host model artifact registry.
- Store opaque model bytes and out-of-sample evaluation reports separately in
  the existing SHA-256 content-addressed artifact store.
- Bind each immutable (model_id, model_version) to artifact/evaluation
  digests, media type, validation MAE, sample count, and finite JSON metadata.
- Require an explicit compare-and-swap expected active version for activation.
- Require rollback callers to name the target version and expected current
  version; never infer a rollback target.
- Append immutable activation/rollback events.
- Never deserialize or execute stored bytes in the registry. Model-specific
  loaders remain an application responsibility.
- Do not automatically activate a trained candidate.
- The operational worker may opt into the artifact registry and must resolve
  non-baseline candidates against the exact active version.
- Applications explicitly register reviewed loaders by media type; artifact
  metadata never selects or imports executable code.
- A missing active version, missing loader, digest/read failure, loader error, or
  adapter identity mismatch falls back to seasonal-naive rather than serving an
  unactivated or mismatched candidate.
- Cache loaded adapters by immutable artifact digest; active-pointer changes
  naturally select a different cache key for activation and rollback.

## Consequences

The registry can recover model bytes, evidence, active version, and history
after process restart on one host. The worker integration remains opt-in and\nrequires deployment code to construct the registry and register each reviewed\nmedia-type loader; the CLI does not dynamically import plugins. File writes may leave unreferenced blobs if
a later database operation fails; such blobs are safe and can be garbage
collected by a future explicit maintenance tool. This does not provide
distributed serving, multi-host activation, automatic canary rollout, or
statistical validation of caller-supplied evidence.
