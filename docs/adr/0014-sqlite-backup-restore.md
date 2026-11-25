# ADR 0014: SQLite online backup and controlled restore

- Status: Accepted
- Date: 2026-11-25
- Scope: Single-host operational persistence

## Context

The operational API and worker persist tenant data in SQLite. Copying only the
main database file while processes are active can omit committed WAL contents.
A production deployment needs a repeatable backup, integrity check, and restore
procedure before it can be considered operationally recoverable.

## Decision

Provide a small dependency-free CLI, demand-forecast-db, with three operations:

- backup: use sqlite3.Connection.backup to create a consistent temporary copy,
  verify integrity and foreign keys, calculate SHA-256, then atomically publish
  the backup. Existing destinations are protected unless --overwrite is set.
- verify: run PRAGMA integrity_check and PRAGMA foreign_key_check and report a
  SHA-256 digest.
- restore: require --confirm-services-stopped, verify the source backup, stage
  and verify a temporary copy, then atomically replace the destination and
  remove stale WAL/SHM sidecars. If replacement fails, parked sidecars are
  restored.

The CLI does not schedule backups, encrypt artifacts, or transfer them to
remote storage. Those responsibilities belong to deployment infrastructure.

## Consequences

- Online backup is consistent with active SQLite WAL writes.
- Restore is deliberately offline and requires the operator to stop every
  process using the target database.
- Backups must be encrypted, stored off-host, and governed by retention policy.
- A successful integrity check is necessary but not sufficient for disaster
  recovery; deployments must periodically test restores and run application
  smoke checks afterward.
- SQLite remains single-host. Backup support does not add multi-writer,
  multi-host, or SaaS deployment guarantees.
