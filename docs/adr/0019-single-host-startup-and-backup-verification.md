# ADR 0019: Single-host startup ordering and backup verification

- Status: Accepted
- Date: 2026-11-28
- Scope: Alpha single-host operational deployment

## Context

The Compose deployment shares one durable SQLite state directory between the
API and one tenant-configured worker. The worker process owns the scheduler
poll loop; a separate scheduler container would introduce another process
against the same state without adding supported availability. Startup ordering
must ensure the API's local dependencies are ready before the worker begins
polling. Backup acceptance also needs an explicit repository verification step
rather than treating a successful upload as proof of repository integrity.

## Decision

- Compose starts the API first and waits for its dependency-aware readiness
  healthcheck before starting the worker. Reverse dependency ordering stops the
  worker before the API.
- The worker remains the sole scheduler poller for its configured tenant.
  Restarted or interrupted work is recovered by expiring leases and fencing;
  operators must not clear lease tokens manually.
- After the Restic snapshot upload, the backup script restarts API and worker
  before running `restic check` and retention pruning. A verification failure
  is reported as a failed backup run without extending the service outage.
- Restore runs `restic check` before materializing the selected snapshot into a
  temporary directory, then extracts into a clean state directory while
  preserving the prior state. SQLite integrity and foreign-key checks run
  before services may be restarted.
- `restic check --read-data` is an explicit, potentially I/O-intensive
  full-repository scrub for a separately scheduled maintenance window.

## Consequences and limits

- This remains one host, one local POSIX filesystem, one API, and one worker
  process per tenant. It is not a multi-host SQLite, shared-filesystem,
  distributed-locking, failover, or HA design.
- The encrypted local-repository CI round-trip validates the Restic commands,
  backup/restore scripts, and database checks. It does not prove remote
  object-store IAM/network access, host-installed timer execution, or
  independent-host recovery.
- Issue #74 remains open until an operator provisions real off-host credentials,
  enables the systemd timer on the target host, and records a successful
  restore onto a separate clean host with API readiness and tenant-scoped
  worker smoke checks.
