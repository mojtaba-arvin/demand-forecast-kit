# ADR 0018: Executable single-host recovery validation

- Status: Accepted
- Date: 2026-11-26
- Scope: Alpha single-host operations

## Context

The deployment profile had backup/restore scripts and an operator runbook, but
CI checked only shell syntax. The worker also relied on Python's default signal
behavior, which does not execute its shutdown cleanup on SIGTERM.

## Decision

- Handle SIGTERM and SIGINT as graceful worker shutdown requests. Stop the
  heartbeat thread and persist the worker's stopped status in a finally block.
- Give the Compose worker a 60-second stop grace period so an in-flight job can
  finish before forced termination; scheduler leases remain the crash-recovery
  mechanism.
- Restart API and worker immediately after a successful Restic snapshot upload,
  before potentially lengthy retention pruning.
- Exercise the actual Restic CLI and repository format in CI using a local
  encrypted repository and a mocked Docker Compose control plane. Verify full
  state round-trip, SQLite integrity, preserved pre-restore state, and service
  restart after backup failure.
- Provide an authenticated post-restore smoke script that checks API readiness
  and at least one healthy worker heartbeat.

## Consequences and limits

- CI proves the backup/restore scripts against local Restic storage, not remote
  object-store IAM, network reliability, systemd timer installation, host
  filesystem behavior, or real container startup.
- An independent-host restore drill remains mandatory before closing Issue #74.
- Forced termination still relies on expiring scheduler leases and fencing;
  do not manually clear leases.
