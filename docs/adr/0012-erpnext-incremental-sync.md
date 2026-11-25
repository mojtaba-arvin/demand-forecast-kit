# ADR 0012: Incremental ERPNext synchronization

- Status: accepted.
- Date: 2026-11-25

## Context

The original ERPNext connector paginated full resource scans. Pagination and
HTTP retries made reads bounded and repeatable, but did not detect changes to
old invoices or cancelled purchase orders, and repeated every historical read
on every sync.

## Decision

- Maintain independent watermarks for Bin, Sales Invoice, and Purchase Order,
  scoped by tenant and local warehouse.
- Query each resource from its watermark minus a configurable overlap window
  (five minutes by default); keep the watermark monotonic.
- Apply changed records idempotently and advance each resource watermark only
  after its complete batch has been applied.
- Keep an invoice contribution ledger keyed by tenant, warehouse, invoice,
  and SKU. Replacing or cancelling an invoice recomputes the affected SKU/day
  totals from all remaining submitted invoices.
- Preserve zero-demand days between the first and last imported invoice dates.
- Import cancelled purchase orders as cancelled local orders so they no longer
  contribute to confirmed inbound stock.
- Persist source-modified timestamps and ignore stale invoice/PO replays that
  arrive after newer source changes.
- Never overwrite a demand observation owned by another source. Fail the
  invoice batch and leave its watermark unchanged for operator reconciliation.
- Keep ERPNext credentials read-only; no ERP documents or stock ledgers are
  created or changed by this connector.

## Consequences and limitations

The overlap makes retries and pagination races safer but is not a distributed
lock. SQLite remains single-host. ERPNext hard deletes do not produce a
modified-time event and cannot be discovered by this incremental query; an
operator-led full reconciliation is required after source hard deletes.
Invoice return/credit-note quantities retain the existing connector behavior
and are not counted as positive demand. Source timestamp interpretation assumes
ERPNext's naive modified timestamps represent UTC.
