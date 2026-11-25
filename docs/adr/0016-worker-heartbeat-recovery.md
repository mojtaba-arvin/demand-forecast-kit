# ADR 0016: Tenant-scoped worker liveness and restart recovery

- Status: Accepted
- Date: 2026-11-25
- Scope: Single-host operational worker

## Context

API readiness verifies local databases and artifact storage, but it does not
prove that the background worker is polling or that scheduled work can resume
after a process failure. Operators need an independent, tenant-scoped signal.

## Decision

Persist worker identity, hostname, PID, start time, last heartbeat, and
graceful-stop status in the operational SQLite store. The CLI refreshes its
heartbeat independently of scheduled-job execution (at most every 30 seconds)
and marks the worker stopped during graceful shutdown. The authenticated
/v1/ops/worker/status endpoint exposes only records belonging to the caller's
tenant and classifies old heartbeats as stale using a caller-selected threshold
bounded from 5 to 3600 seconds.

A crash cannot record a graceful stop; its last heartbeat becomes stale. Job
recovery remains lease-based: a later worker can reclaim a due job after the
prior lease expires. Never clear another worker's lease manually.

## Consequences and limits

- Heartbeat status is a process-liveness signal, not proof of successful job
  throughput or ERPNext connectivity.
- The heartbeat endpoint is not folded into API readiness; the API can serve
  status while a worker is down.
- SQLite and scheduler leases remain single-host mechanisms.
- Deployment documentation must monitor heartbeat freshness and validate
  worker restart behavior separately from API liveness.
