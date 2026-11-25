# ADR 0017: Single-host Compose and encrypted off-host recovery

- Status: Accepted
- Date: 2026-11-25
- Scope: Alpha single-host operational deployment

## Context

SQLite and the operational worker are single-host components. The project had
online SQLite backup and controlled restore commands, but no supported service
layout, scheduled off-host retention, or complete-state backup procedure.
Copying only operations.sqlite would omit run registries and immutable
artifacts; copying live SQLite files with ordinary file tools is unsafe.

## Decision

Provide a Docker Compose profile with one API and one tenant-configured worker
sharing a local bind-mounted state directory. Containers run as UID 10001 with
read-only root filesystems, dropped Linux capabilities, and a loopback-only API
port. Multi-host sharing of the state directory is unsupported.

Use Restic for encrypted remote snapshots. The backup script requires both
services to be running, stops them to obtain a quiescent snapshot of the entire
state directory, uploads the archive, applies a 7-daily/5-weekly/12-monthly
retention policy, and restarts services through an EXIT trap. A systemd timer
runs this daily. The restore script requires an explicit confirmation argument
and stopped services, preserves the previous state, restores the complete
archive, and checks SQLite integrity and foreign keys before leaving services
stopped for application smoke checks.

## Consequences and limits

- Backup causes a short service interruption; no online full-state snapshot is
  claimed.
- Restic encrypts data before remote upload. Repository credentials and
  password files remain host-managed and must not enter Git.
- A successful upload and SQLite integrity checks do not prove recovery until
  an independent restore drill validates API and worker behavior.
- SQLite remains local, single-host storage. No distributed locks, failover,
  or HA claims are introduced.
