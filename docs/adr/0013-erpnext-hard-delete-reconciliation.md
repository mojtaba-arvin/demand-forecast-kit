# ADR 0013: Explicit ERPNext full reconciliation for hard deletes

- Status: Accepted
- Date: 2026-11-25
- Scope: Read-only ERPNext synchronization into the local operational store

## Context

The incremental connector uses independent Modified-time watermarks and a
bounded overlap for Bin, Sales Invoice, and Purchase Order resources. ERPNext
hard deletes do not produce a surviving record with a newer Modified value.
An empty incremental page therefore cannot distinguish "nothing changed" from
"a previously imported source record was deleted".

Inferring deletion from incremental absence would be unsafe: the query may be
partial, a page may fail, or a source-side edit may move records between pages.

## Decision

Keep incremental sync strictly non-destructive. Add a separate operator-triggered
full reconciliation for one tenant/warehouse:

1. Fetch all Bin, Sales Invoice, and Purchase Order pages twice.
2. Compare complete ordered snapshots; abort before local writes if any resource
   differs or any request fails.
3. Apply current source records, then reconcile locally imported IDs absent from
   the verified snapshot.
4. Advance resource watermarks only after the reconciliation work succeeds.

The double read is a consistency check, not a transaction lock. Operators must
run reconciliation during a quiet ERPNext window and must not overlap it with
another sync for the same tenant/warehouse.

### Deletion behavior

- Sales Invoice: remove the deleted invoice's contribution, recompute affected
  SKU/day totals, and retain a source-deleted tombstone with a local timestamp.
  Incremental events older than that tombstone cannot resurrect the invoice.
  A later verified full snapshot can restore it if the ID is present again.
- Purchase Order: cancel the missing imported order and advance its source
  modification fence so stale updates cannot restore inbound stock.
- Bin: write a zero-quantity snapshot only if the latest local inventory source
  remains erpnext:Bin. A newer manual inventory source is authoritative and
  must not be overwritten by a missing ERPNext Bin.

The command is exposed as demand-forecast-erpnext-reconcile and requires the
explicit --confirm-full-snapshot flag. It also refuses an empty resource snapshot
when local records exist unless the operator explicitly opts in after verifying
complete ERPNext list/read permissions. Credentials are read only from environment
variables. The operation mutates local SQLite data only; it never writes to
ERPNext. Incremental and full Bin imports preserve the latest manual/other-source
inventory snapshot instead of silently replacing its source-of-truth value.

## Consequences

- Incremental sync remains fast and safe for routine operation.
- Hard deletes become recoverable through an explicit, auditable operator action.
- Full reconciliation is more expensive than incremental sync and must be run
  deliberately, especially for large warehouses.
- Frappe does not provide a cross-resource snapshot transaction; two matching
  reads reduce pagination-race risk but cannot prove source immutability.
- SQLite remains single-host. This feature does not add distributed locking,
  multi-host coordination, or automatic scheduled deletion inference.
- If local application fails after some resource batches were applied, watermarks
  remain unchanged and the idempotent reconciliation can be safely rerun.
