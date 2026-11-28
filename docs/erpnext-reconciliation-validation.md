# ERPNext live full-reconciliation validation (Issue #73)

**Status: BLOCKED — disposable ERPNext site and owner-issued credentials were not available to this run.**  
This document is the executable operator procedure and evidence template. It is not a claim that a live ERPNext validation passed.

## Scope and safety

Validate the operator-triggered `demand-forecast-erpnext-reconcile` command from PR #71 against a disposable, isolated ERPNext site. The connector must issue **GET requests only**. The only writes in this exercise are deliberate fixture setup/cleanup by the disposable-site owner and local SQLite reconciliation by the command.

Never point this procedure at production. Never use an Administrator token or a human user's API key. Never put API keys, API secrets, customer names, invoice numbers, item codes, supplier names, raw payloads, or database contents in this repository or the report.

The command reads Bin, Sales Invoice, and Purchase Order twice (all pages); the incremental sales-demand path also reads Sales Invoice Item and Purchase Order Item. Frappe offset pagination is not a transactionally consistent snapshot. Run in a quiet source window with no concurrent import/reconciliation for the same tenant/warehouse.

## Prerequisites and owner-only actions

The disposable-site owner must provide:

1. An isolated disposable site with no customer/production data and permission to create, cancel, edit, and hard-delete test fixtures.
2. Exact site URL through the approved secret channel, plus the exact ERPNext and Frappe versions/build identifiers.
3. A dedicated enabled **System User** named for this integration (not Administrator), with a unique API key/secret issued for this test and a documented expiry/revocation plan.
4. A least-privilege role assignment that grants read/list access only to the five required DocTypes. No create, write, submit, cancel, delete, import, export, report, or broad administrative permissions. Review all roles and User Permissions attached to the user; Frappe role grants are not a per-token DocType allow-list.
5. Confirmation that the integration user can list and read records in the intended warehouse/company scope for:
   - `Bin`
   - `Sales Invoice`
   - `Sales Invoice Item`
   - `Purchase Order`
   - `Purchase Order Item`
6. A disposable test company, warehouse, at least three SKUs, a supplier, and fixture documents with synthetic data only. Arrange at least five records in each listable resource so a page size of two necessarily exercises multiple pages. Include records both inside and outside the intended warehouse/company scope.
7. A named owner/operator available to make controlled source-side changes and restore/clean fixtures. The integration user must not be used for fixture setup or cleanup.

**Do not ask the owner to send credentials in chat or commit them.** Enter them only into the protected environment of the host running the test.

### Version and identity capture

On the disposable ERPNext bench host, the owner captures and supplies the output of:

```bash
bench version
```

Record the exact ERPNext and Frappe versions, app revisions if available, site timezone, and test timestamp. With the dedicated token, verify identity without printing the token:

```bash
curl --fail --silent --show-error \
  -H "Authorization: token ${DEMAND_FORECAST_ERPNEXT_API_KEY}:${DEMAND_FORECAST_ERPNEXT_API_SECRET}" \
  "${DEMAND_FORECAST_ERPNEXT_URL%/}/api/method/frappe.auth.get_logged_user"
```

The response must identify the dedicated Integration User. Do not retain raw command traces containing headers or environment values.

## Permission and read-only preflight

For each of the five DocTypes, use the authenticated integration identity to:

1. List all pages with an explicit small page size (2), stable ordering, and only the `name` field. Continue until a short page is returned.
2. Record page count, total record count, and whether the resource is intentionally scoped/filtered. Compare against an independently obtained count from the site owner under the same company/warehouse and filters.
3. GET an individual document by name for at least one permitted record, including a child row from each child DocType. A successful list alone does not establish single-document read access.
4. Verify that inaccessible records are excluded and that an explicit single-record GET for a deliberately out-of-scope record is denied/not found according to the site's permission model.
5. Verify the integration user's effective role permissions do not include any write/create/submit/cancel/delete action on these DocTypes.

Example read-only list request (repeat for each DocType; URL-encode the JSON query parameters):

```bash
curl --fail --silent --show-error -G \
  -H "Authorization: token ${DEMAND_FORECAST_ERPNEXT_API_KEY}:${DEMAND_FORECAST_ERPNEXT_API_SECRET}" \
  "${DEMAND_FORECAST_ERPNEXT_URL%/}/api/resource/Bin" \
  --data-urlencode 'fields=["name"]' \
  --data-urlencode 'limit_start=0' \
  --data-urlencode 'limit_page_length=2' \
  --data-urlencode 'order_by=modified asc, name asc'
```

Use the same parameters for subsequent offsets (2, 4, ...). For child DocTypes, apply a parent/warehouse filter appropriate to the test fixture, and separately verify that the role can list/read child records in that scope. Do not use `frappe.get_all` as proof: it bypasses user permissions. Use the REST resource API or `frappe.get_list` semantics under the Integration User.

Before any reconciliation, capture the disposable site's source-side record counts and a redacted inventory of fixture IDs (stable synthetic aliases only).

## Controlled test matrix

Run the following cases sequentially. Use a fresh local SQLite database and a dedicated test tenant/warehouse for each full scenario, or take a verified local backup before each destructive phase.

| Case | Source-side setup/change by owner | Expected observation |
| --- | --- | --- |
| Pagination | At least 5 Bin, Sales Invoice, Sales Invoice Item, Purchase Order, and Purchase Order Item rows; command page size 2 | Every page is consumed; totals equal independently verified in-scope counts; no duplicate or skipped names |
| Repeatability | No source changes between two complete reconciliations | Both passes have identical ordered snapshots; second local application is idempotent |
| Hard-deleted Bin | Import a Bin, then owner hard-deletes that disposable Bin after baseline | Local ERPNext-owned quantity becomes zero with a deletion fence/tombstone; a newer manual inventory snapshot remains authoritative |
| Hard-deleted invoice | Import a submitted synthetic invoice and its lines, then owner hard-deletes it | Its contribution is removed, affected SKU/day totals recomputed, and source-inactive tombstone prevents stale incremental replay |
| Cancelled invoice | Import a submitted invoice, then owner cancels it | Demand contribution is removed and cancellation is reflected; no source write is made by connector |
| Edited invoice | Change quantities/date/warehouse on a synthetic invoice between incremental imports | Prior contribution is replaced, not double-counted; edits outside the target warehouse remove the old warehouse contribution |
| Hard-deleted PO | Import an open/partially received PO, then owner hard-deletes it | Local order is cancelled; remaining inbound quantity is removed; stale incremental event cannot resurrect it |
| Permission-filtered resource | Remove the Integration User's list/read permission or add a restrictive User Permission so a resource is filtered/empty while local imported records exist | Reconciliation fails closed before applying deletion for an incomplete/permission-limited snapshot |
| Genuine empty resource | Owner verifies complete list/read permission and confirms a resource is truly empty | Default invocation refuses unexpected empty snapshot when local records exist; `--allow-empty-snapshot` is used only after this independent verification |
| Source changes between passes | Owner changes a fixture during the controlled double-read window | Snapshot mismatch aborts before local deletion/reconciliation writes |
| Manual inventory ownership | Record a manual local inventory snapshot newer than the imported Bin | Full reconciliation and subsequent incremental import preserve manual quantity/source |
| Stale replay | Replay an event older than the deletion/cancellation fence | Deleted/cancelled invoice contribution and PO/Bin state are not resurrected |

The permission-filtered case must not be “fixed” by routinely passing `--allow-empty-snapshot`. That flag is an exceptional operator acknowledgement for a genuinely empty resource after independent permission verification, not a bypass for incomplete reads.

## Execute the reconciliation

Run this on the host that owns the test SQLite database, after confirming no sync or reconciliation is active for this tenant/warehouse. Use the isolated site URL and dedicated read-only credentials in the protected environment only:

```bash
export DEMAND_FORECAST_ERPNEXT_URL='https://<disposable-site>'
# Populate the next two variables from the approved secret store; never echo them.
export DEMAND_FORECAST_ERPNEXT_API_KEY='...'
export DEMAND_FORECAST_ERPNEXT_API_SECRET='...'

demand-forecast-erpnext-reconcile \
  --database ./state/erpnext-issue-73.sqlite \
  --tenant-id erpnext-issue-73 \
  --warehouse-id <synthetic-warehouse-id> \
  --page-size 2 \
  --confirm-full-snapshot
```

Do not use `--allow-empty-snapshot` in the initial run. Capture stdout (the JSON result) only after confirming it contains no source/customer identifiers. Capture process exit status and sanitized stderr. Keep the local database private; inspect it with application store APIs or a local test script and report only aggregate counts and pass/fail.

For each destructive source-side case, repeat the preflight, incremental import as applicable, full reconciliation, local-state assertions, and stale-event replay assertion. Keep the source quiet during both full-snapshot passes.

## Local assertions and acceptance

Verify using the local store and targeted test fixtures:

- Invoice demand contributions, per-SKU/day totals, and invoice-ID membership match the current permitted source snapshot.
- Cancelled, hard-deleted, or no-longer-in-scope invoice contributions are absent; tombstone/source-inactive state exists and rejects events at or before its source-time fence.
- Missing purchase orders are cancelled and no longer contribute confirmed inbound quantity; an older source modification cannot restore them.
- Missing Bin records are zeroed/tombstoned only when ERPNext still owns the latest local inventory snapshot. Manual/other-source ownership is preserved.
- Resource watermarks advance only after successful application.
- An HTTP/auth/permission error, malformed response, incomplete page, or mismatch between full reads aborts before deletion reconciliation. No empty or partial page is treated as proof of absence.
- Repeating the same verified snapshot does not change effective local state or create duplicate demand/inbound records.
- The integration user's audit trail shows only GET requests from the connector. Confirm there were no POST, PUT, PATCH, or DELETE requests attributable to the integration user.
- The connector makes no ERPNext document, stock ledger, or accounting changes. Local SQLite mutations are expected and are the only mutations performed by the command.

A two-pass match reduces but does not eliminate source races; it is not a transactional source snapshot. Acceptance requires a quiet source window and owner-confirmed fixture change log.

## Redacted report template

Copy this template into the issue/PR validation evidence after execution. Replace every placeholder. Do not include names, URLs, credentials, raw API payloads, invoice numbers, SKU/item codes, supplier names, or customer data.

```text
Issue: #73
Validation status: NOT RUN / PASS / FAIL
Run timestamp (UTC):
Disposable site alias:
ERPNext exact version/build:
Frappe exact version/build:
Site timezone:
Connector commit:
Integration identity: dedicated read-only user (alias only)
Effective roles reviewed: yes/no
Write permissions absent on all five DocTypes: yes/no
Connector HTTP methods observed: GET only / unexpected methods

Resource                  Pages (page size 2)   Listed count   Single GET   Owner count match
Bin                       ...                   ...            pass/fail    pass/fail
Sales Invoice             ...                   ...            pass/fail    pass/fail
Sales Invoice Item        ...                   ...            pass/fail    pass/fail
Purchase Order            ...                   ...            pass/fail    pass/fail
Purchase Order Item       ...                   ...            pass/fail    pass/fail

Scenario                                  Result   Redacted evidence/reference
Pagination and complete counts           ...
Two identical snapshots                  ...
Hard-deleted Bin + tombstone              ...
Hard-deleted invoice + tombstone          ...
Cancelled invoice                         ...
Edited invoice                            ...
Hard-deleted PO + stale replay            ...
Permission-filtered read fails closed     ...
Genuine empty-resource acknowledgement    ...
Between-pass source mutation abort        ...
Manual inventory ownership preserved      ...
No ERPNext writes/ledger changes          ...

Command exit status:
Sanitized reconciliation result counts:
Local assertions:
Unresolved compatibility gaps:
Owner/operator confirmation:
Credential revoked/rotation confirmed:
```

Report counts separately for the five remote resources and the command's local reconciliation counters. Do not imply that the command output itself reports Sales Invoice Item or Purchase Order Item counts unless instrumentation explicitly supplies those counts.

## Owner handoff checklist

- [ ] Disposable site and isolated synthetic fixture data are ready.
- [ ] Owner has recorded exact ERPNext/Frappe versions and site timezone.
- [ ] Dedicated Integration User and read-only API key are created; no Administrator/human token is used.
- [ ] Owner has independently verified complete list/read permissions for all five DocTypes and scoped child-row visibility.
- [ ] Page-size-two fixture data exists in every resource.
- [ ] Owner has scheduled a quiet source window and is available for controlled source-side edits/cancellations/hard deletes.
- [ ] Test host has the package, isolated SQLite path, and protected environment variables configured.
- [ ] Redacted evidence is recorded and credentials are revoked/rotated after validation.

## References

- Repository operator runbook: [docs/operations.md](operations.md#operator-triggered-full-reconciliation)
- Design decision: [ADR 0013](adr/0013-erpnext-hard-delete-reconciliation.md)
- Frappe REST API: https://docs.frappe.io/framework/user/en/api/rest
- Frappe REST integration guide: https://docs.frappe.io/framework/user/en/guides/integration/rest_api
- Frappe database API: https://docs.frappe.io/framework/user/en/api/database

The root `AGENTS.md` path was not present on the inspected repository default branch at the time this procedure was prepared. Re-check repository guidance before execution if an `AGENTS.md` is added.
