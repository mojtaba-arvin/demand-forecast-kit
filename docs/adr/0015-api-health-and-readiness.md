# ADR 0015: API liveness and dependency readiness probes

- Status: Accepted
- Date: 2026-11-25
- Scope: Single-host operational API

## Context

The existing `/health` endpoint reports only that the FastAPI process can
answer an HTTP request. A load balancer also needs to know whether the local
persistence and artifact dependencies required to serve requests are usable.
Conflating process liveness with dependency readiness can route traffic to an
API instance whose state directory is missing or damaged.

## Decision

Preserve `/health` as a backward-compatible liveness endpoint and add:

- `/health/live`: process liveness only.
- `/health/ready`: verify the run-registry SQLite database, operational
  SQLite database, and artifact directory. Return HTTP 200 only when all local
  dependencies pass; otherwise return HTTP 503 with dependency-level status.

Keep health probes unauthenticated so load balancers and orchestrators can
inspect them without application credentials. Do not include paths, secrets,
or tenant data in responses.

## Consequences and limits

- Liveness and readiness have distinct meanings and can be configured
  independently by an orchestrator.
- Readiness checks only local dependencies. It does not assert worker
  liveness, scheduler progress, ERPNext connectivity, backup freshness,
  off-host recoverability, or multi-host availability.
- Monitor worker heartbeat, backup age, and external connector status
  independently. SQLite remains a single-host store.
