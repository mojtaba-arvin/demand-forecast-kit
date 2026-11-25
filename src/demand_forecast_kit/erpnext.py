"""ERPNext/Frappe REST integration for warehouse, stock, and sales history ingestion."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from demand_forecast_kit.operations import OperationalStore

Transport = Callable[[str, str, dict[str, str], bytes | None, float], bytes]


class ERPNextRequestError(RuntimeError):
    """Sanitized transport failure with retry metadata."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def _http_transport(
    url: str, method: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> bytes:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        # Do not include request headers or credentials in raised messages.
        retry_after = None
        try:
            raw_retry_after = exc.headers.get("Retry-After")
        except AttributeError:
            raw_retry_after = None
        if raw_retry_after is not None:
            try:
                retry_after = float(raw_retry_after)
            except ValueError:
                retry_after = None
        raise ERPNextRequestError(
            f"ERPNext returned HTTP {exc.code}",
            status_code=exc.code,
            retry_after_seconds=retry_after,
        ) from exc
    except URLError as exc:
        raise ERPNextRequestError("ERPNext connection failed") from exc


class ERPNextClient:
    """Small, read-oriented Frappe API client.

    Credentials are supplied by the caller and never persisted or logged. The
    connector imports source records; it does not create or submit ERP documents.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        timeout: float = 20.0,
        transport: Transport = _http_transport,
        page_size: int = 500,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.25,
        sync_overlap_seconds: int = 300,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("ERPNext API key and secret are required")
        if (
            timeout <= 0
            or not 1 <= page_size <= 5000
            or type(max_retries) is not int
            or not 0 <= max_retries <= 10
            or not math.isfinite(retry_backoff_seconds)
            or retry_backoff_seconds < 0
            or type(sync_overlap_seconds) is not int
            or not 0 <= sync_overlap_seconds <= 86_400
        ):
            raise ValueError("timeout, page_size, or retry configuration is out of range")
        self.base_url = base_url.rstrip("/") + "/"
        self._authorization = f"token {api_key}:{api_secret}"
        self.timeout = timeout
        self.transport = transport
        self.page_size = page_size
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sync_overlap_seconds = sync_overlap_seconds
        self._sleep = sleep

    def _request(self, url: str, headers: dict[str, str]) -> bytes:
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(self.max_retries + 1):
            try:
                return self.transport(url, "GET", headers, None, self.timeout)
            except ERPNextRequestError as exc:
                retryable = exc.status_code is None or exc.status_code in retryable_statuses
                if not retryable or attempt >= self.max_retries:
                    raise
                delay = exc.retry_after_seconds
                if delay is None or delay <= 0:
                    delay = self.retry_backoff_seconds * (2**attempt)
                self._sleep(min(delay, 30.0))
        raise RuntimeError("ERPNext retry loop exhausted unexpectedly")

    def _resource(
        self,
        doctype: str,
        *,
        fields: list[str],
        filters: list[list[Any]] | None = None,
        limit_start: int = 0,
    ) -> list[dict[str, Any]]:
        query = {
            "fields": json.dumps(fields, separators=(",", ":")),
            "filters": json.dumps(filters or [], separators=(",", ":")),
            "limit_start": str(limit_start),
            "limit_page_length": str(self.page_size),
            "order_by": "modified asc, name asc",
        }
        url = urljoin(self.base_url, f"api/resource/{doctype}") + "?" + urlencode(query)
        headers = {
            "Authorization": self._authorization,
            "Accept": "application/json",
            "User-Agent": "demand-forecast-kit/0.2",
        }
        raw = self._request(url, headers)
        try:
            payload_raw: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ERPNext returned invalid JSON") from exc
        if not isinstance(payload_raw, dict):
            raise RuntimeError("ERPNext response must be a JSON object")
        payload = cast(dict[str, Any], payload_raw)
        data: Any = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("ERPNext response does not contain a valid data list")
        data_items = cast(list[Any], data)
        if any(not isinstance(item, dict) for item in data_items):
            raise RuntimeError("ERPNext response does not contain a valid data list")
        return cast(list[dict[str, Any]], data_items)

    def _all_resources(
        self,
        doctype: str,
        *,
        fields: list[str],
        filters: list[list[Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch every page using the configured bounded page size."""
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._resource(doctype, fields=fields, filters=filters, limit_start=offset)
            records.extend(page)
            if len(page) < self.page_size:
                return records
            offset += len(page)

    def list_warehouses(self) -> list[dict[str, Any]]:
        return self._all_resources(
            "Warehouse",
            fields=["name", "warehouse_name", "parent_warehouse", "is_group", "disabled"],
            filters=[["disabled", "=", 0], ["is_group", "=", 0]],
        )

    def fetch_bin_balances(self, warehouse: str) -> list[dict[str, Any]]:
        if not warehouse.strip():
            raise ValueError("warehouse must not be blank")
        return self._all_resources(
            "Bin",
            fields=["item_code", "warehouse", "actual_qty", "reserved_qty", "modified"],
            filters=[["warehouse", "=", warehouse]],
        )

    def fetch_sales_demand(self, warehouse: str) -> list[dict[str, Any]]:
        """Return submitted invoice-item demand, grouped by item and posting date."""
        invoices: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._resource(
                "Sales Invoice",
                fields=["name", "posting_date", "docstatus"],
                filters=[["docstatus", "=", 1]],
                limit_start=offset,
            )
            invoices.extend(page)
            if len(page) < self.page_size:
                break
            offset += len(page)
        dates = {
            str(invoice["name"]): str(invoice["posting_date"])
            for invoice in invoices
            if invoice.get("name") and invoice.get("posting_date")
        }
        if not dates:
            return []
        names = sorted(dates)
        totals: dict[tuple[str, str], float] = {}
        for start in range(0, len(names), 100):
            batch = names[start : start + 100]
            offset = 0
            while True:
                items = self._resource(
                    "Sales Invoice Item",
                    fields=["item_code", "qty", "parent", "warehouse"],
                    filters=[["parent", "in", batch], ["warehouse", "=", warehouse]],
                    limit_start=offset,
                )
                for item in items:
                    item_code = str(item.get("item_code", "")).strip()
                    invoice = str(item.get("parent", ""))
                    if item_code and invoice in dates:
                        quantity = float(item.get("qty", 0))
                        if quantity > 0:
                            key = (item_code, dates[invoice])
                            totals[key] = totals.get(key, 0.0) + quantity
                if len(items) < self.page_size:
                    break
                offset += len(items)
        if not totals:
            return []
        active_skus = sorted({sku for sku, _day in totals})
        first_day = min(date.fromisoformat(day) for _sku, day in totals)
        last_day = max(date.fromisoformat(day) for _sku, day in totals)
        dense_rows: list[dict[str, Any]] = []
        for sku in active_skus:
            current = first_day
            while current <= last_day:
                day = current.isoformat()
                dense_rows.append(
                    {
                        "sku_id": sku,
                        "observed_at": day,
                        "demand": totals.get((sku, day), 0.0),
                    }
                )
                current += timedelta(days=1)
        return dense_rows

    @staticmethod
    def _modified_timestamp(value: Any) -> str:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
        except ValueError as exc:
            raise RuntimeError("ERPNext returned an invalid modified timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()

    def _overlap_start(self, watermark: str | None) -> str | None:
        if watermark is None:
            return None
        parsed = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        start = parsed.astimezone(UTC) - timedelta(seconds=self.sync_overlap_seconds)
        return start.strftime("%Y-%m-%d %H:%M:%S")

    def _latest_modified(self, records: list[dict[str, Any]]) -> str | None:
        values = [
            self._modified_timestamp(record["modified"])
            for record in records
            if record.get("modified")
        ]
        return max(values) if values else None

    def fetch_bin_changes(
        self, warehouse: str, *, modified_since: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch only Bin records changed since an optional overlap boundary."""
        if not warehouse.strip():
            raise ValueError("warehouse must not be blank")
        filters: list[list[Any]] = [["warehouse", "=", warehouse]]
        if modified_since is not None:
            filters.append(["modified", ">=", modified_since])
        return self._all_resources(
            "Bin",
            fields=["item_code", "warehouse", "actual_qty", "reserved_qty", "modified"],
            filters=filters,
        )

    def fetch_sales_invoice_changes(
        self, warehouse: str, *, modified_since: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch changed submitted/cancelled invoices with their current warehouse lines."""
        if not warehouse.strip():
            raise ValueError("warehouse must not be blank")
        filters: list[list[Any]] = [["docstatus", "in", [1, 2]]]
        if modified_since is not None:
            filters.append(["modified", ">=", modified_since])
        headers = self._all_resources(
            "Sales Invoice",
            fields=["name", "posting_date", "docstatus", "modified"],
            filters=filters,
        )
        for header in headers:
            if (
                not header.get("name")
                or not header.get("posting_date")
                or not header.get("modified")
            ):
                raise RuntimeError(
                    "ERPNext invoice header is missing name, posting_date, or modified"
                )
        submitted = [
            str(header["name"]) for header in headers if int(header.get("docstatus", 0)) == 1
        ]
        grouped: dict[str, dict[str, float]] = {}
        for start in range(0, len(submitted), 100):
            batch = submitted[start : start + 100]
            items = self._all_resources(
                "Sales Invoice Item",
                fields=["item_code", "qty", "parent", "warehouse"],
                filters=[["parent", "in", batch], ["warehouse", "=", warehouse]],
            )
            for item in items:
                invoice_id = str(item.get("parent", ""))
                sku = str(item.get("item_code", "")).strip()
                quantity = float(item.get("qty", 0))
                if invoice_id in batch and sku and math.isfinite(quantity) and quantity > 0:
                    invoice_lines = grouped.setdefault(invoice_id, {})
                    invoice_lines[sku] = invoice_lines.get(sku, 0.0) + quantity
        return [
            {
                "invoice_id": str(header["name"]),
                "posting_date": str(header["posting_date"]),
                "docstatus": int(header.get("docstatus", 0)),
                "modified": self._modified_timestamp(header["modified"]),
                "lines": [
                    {"sku_id": sku, "quantity": quantity}
                    for sku, quantity in sorted(grouped.get(str(header["name"]), {}).items())
                ],
            }
            for header in headers
        ]

    def fetch_purchase_order_changes(
        self, warehouse: str, *, modified_since: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch changed submitted/cancelled purchase orders and current warehouse lines."""
        if not warehouse.strip():
            raise ValueError("warehouse must not be blank")
        filters: list[list[Any]] = [["docstatus", "in", [1, 2]]]
        if modified_since is not None:
            filters.append(["modified", ">=", modified_since])
        headers = self._all_resources(
            "Purchase Order",
            fields=["name", "supplier", "schedule_date", "docstatus", "modified"],
            filters=filters,
        )
        for header in headers:
            if not header.get("name") or not header.get("modified"):
                raise RuntimeError("ERPNext purchase order is missing name or modified")
            if not header.get("supplier"):
                raise RuntimeError("ERPNext purchase order is missing supplier")
        submitted = [
            str(header["name"]) for header in headers if int(header.get("docstatus", 0)) == 1
        ]
        grouped: dict[str, dict[str, dict[str, Any]]] = {}
        for start in range(0, len(submitted), 100):
            batch = submitted[start : start + 100]
            items = self._all_resources(
                "Purchase Order Item",
                fields=["item_code", "qty", "received_qty", "rate", "parent", "warehouse"],
                filters=[["parent", "in", batch], ["warehouse", "=", warehouse]],
            )
            for item in items:
                order_id = str(item.get("parent", ""))
                sku = str(item.get("item_code", "")).strip()
                quantity = float(item.get("qty", 0))
                received = float(item.get("received_qty", 0))
                if order_id not in batch or not sku or quantity <= 0:
                    continue
                if not math.isfinite(quantity) or not math.isfinite(received):
                    raise RuntimeError("ERPNext purchase order line contains a non-finite quantity")
                cost = None if item.get("rate") is None else float(item["rate"])
                order_lines = grouped.setdefault(order_id, {})
                aggregate = order_lines.get(sku)
                if aggregate is None:
                    order_lines[sku] = {
                        "sku_id": sku,
                        "quantity": quantity,
                        "received_quantity": received,
                        "unit_cost": cost,
                    }
                else:
                    previous_quantity = float(aggregate["quantity"])
                    previous_cost = aggregate["unit_cost"]
                    aggregate["quantity"] = previous_quantity + quantity
                    aggregate["received_quantity"] = (
                        float(aggregate["received_quantity"]) + received
                    )
                    if cost is not None:
                        aggregate["unit_cost"] = (
                            cost
                            if previous_cost is None
                            else (float(previous_cost) * previous_quantity + cost * quantity)
                            / (previous_quantity + quantity)
                        )
        result: list[dict[str, Any]] = []
        for header in headers:
            order_id = str(header["name"])
            schedule_date = header.get("schedule_date")
            expected_at = None
            if schedule_date:
                date_text = str(schedule_date)
                expected_at = f"{date_text}T00:00:00+00:00" if len(date_text) == 10 else date_text
            result.append(
                {
                    "order_id": order_id,
                    "supplier_id": str(header.get("supplier") or ""),
                    "expected_at": expected_at,
                    "docstatus": int(header.get("docstatus", 0)),
                    "modified": self._modified_timestamp(header["modified"]),
                    "lines": [
                        grouped.get(order_id, {})[sku] for sku in sorted(grouped.get(order_id, {}))
                    ],
                }
            )
        return result

    def fetch_purchase_orders(self, warehouse: str) -> list[dict[str, Any]]:
        """Read submitted purchase-order lines for one warehouse, including receipts."""
        if not warehouse.strip():
            raise ValueError("warehouse must not be blank")
        orders: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._resource(
                "Purchase Order",
                fields=["name", "supplier", "schedule_date", "docstatus"],
                filters=[["docstatus", "=", 1]],
                limit_start=offset,
            )
            orders.extend(page)
            if len(page) < self.page_size:
                break
            offset += len(page)
        headers = {
            str(item["name"]): item for item in orders if item.get("name") and item.get("supplier")
        }
        if not headers:
            return []
        grouped: dict[str, dict[str, dict[str, Any]]] = {}
        names = sorted(headers)
        for start in range(0, len(names), 100):
            batch = names[start : start + 100]
            offset = 0
            while True:
                items = self._resource(
                    "Purchase Order Item",
                    fields=["item_code", "qty", "received_qty", "rate", "parent", "warehouse"],
                    filters=[["parent", "in", batch], ["warehouse", "=", warehouse]],
                    limit_start=offset,
                )
                for item in items:
                    order_name = str(item.get("parent", ""))
                    sku = str(item.get("item_code", "")).strip()
                    if order_name not in headers or not sku:
                        continue
                    quantity = float(item.get("qty", 0))
                    received = float(item.get("received_qty", 0))
                    if quantity <= 0:
                        continue
                    unit_cost = None if item.get("rate") is None else float(item["rate"])
                    order_group = grouped.setdefault(order_name, {})
                    aggregate = order_group.get(sku)
                    if aggregate is None:
                        order_group[sku] = {
                            "sku_id": sku,
                            "quantity": quantity,
                            "received_quantity": received,
                            "unit_cost": unit_cost,
                        }
                    else:
                        previous_quantity = float(aggregate["quantity"])
                        previous_cost = aggregate["unit_cost"]
                        aggregate["quantity"] = previous_quantity + quantity
                        aggregate["received_quantity"] = (
                            float(aggregate["received_quantity"]) + received
                        )
                        if unit_cost is not None:
                            aggregate["unit_cost"] = (
                                unit_cost
                                if previous_cost is None
                                else (
                                    float(previous_cost) * previous_quantity + unit_cost * quantity
                                )
                                / (previous_quantity + quantity)
                            )
                if len(items) < self.page_size:
                    break
                offset += len(items)
        result: list[dict[str, Any]] = []
        for order_name, sku_lines in sorted(grouped.items()):
            header = headers[order_name]
            lines = [sku_lines[sku] for sku in sorted(sku_lines)]
            schedule_date = header.get("schedule_date")
            expected_at = None
            if schedule_date:
                date_text = str(schedule_date)
                expected_at = f"{date_text}T00:00:00+00:00" if len(date_text) == 10 else date_text
            result.append(
                {
                    "order_id": order_name,
                    "supplier_id": str(header["supplier"]),
                    "expected_at": expected_at,
                    "lines": lines,
                }
            )
        return result

    @staticmethod
    def _snapshot_signature(records: list[dict[str, Any]]) -> str:
        return json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _assert_unique_snapshot_keys(
        records: list[dict[str, Any]], key: str, resource: str
    ) -> None:
        values = [str(record.get(key, "")).strip() for record in records]
        if any(not value for value in values) or len(values) != len(set(values)):
            raise RuntimeError(\n                f"ERPNext {resource} full snapshot contains missing or duplicate keys"\n            )

    def reconcile_warehouse(
        self,
        store: OperationalStore,
        tenant_id: str,
        warehouse_id: str,
        *,
        allow_empty_snapshot: bool = False,
    ) -> dict[str, int | bool]:
        """Operator-triggered full snapshot reconciliation, including hard deletes.

        All three remote snapshots are fetched twice and must match before local
        state is changed. Run this during a quiet source-system window; Frappe's
        offset pagination does not provide a transactionally consistent snapshot.
        """
        if not warehouse_id.strip():
            raise ValueError("warehouse_id must not be blank")

        first_bins = self.fetch_bin_changes(warehouse_id)
        first_invoices = self.fetch_sales_invoice_changes(warehouse_id)
        first_orders = self.fetch_purchase_order_changes(warehouse_id)
        bins = self.fetch_bin_changes(warehouse_id)
        invoices = self.fetch_sales_invoice_changes(warehouse_id)
        purchase_orders = self.fetch_purchase_order_changes(warehouse_id)

        snapshots = (
            (first_bins, bins, "Bin"),
            (first_invoices, invoices, "Sales Invoice"),
            (first_orders, purchase_orders, "Purchase Order"),
        )
        for first, second, resource in snapshots:
            if self._snapshot_signature(first) != self._snapshot_signature(second):
                raise RuntimeError(
                    f"ERPNext {resource} changed during full reconciliation; "
                    "retry during a quiet window"
                )

        self._assert_unique_snapshot_keys(bins, "item_code", "Bin")
        self._assert_unique_snapshot_keys(invoices, "invoice_id", "Sales Invoice")
        self._assert_unique_snapshot_keys(purchase_orders, "order_id", "Purchase Order")

        local_counts = store.get_erpnext_snapshot_counts(tenant_id, warehouse_id)
        remote_counts = {
            "Bin": len(bins),
            "Sales Invoice": len(invoices),
            "Purchase Order": len(purchase_orders),
        }
        unexpectedly_empty = [
            resource
            for resource, remote_count in remote_counts.items()
            if remote_count == 0 and local_counts[resource] > 0
        ]
        if unexpectedly_empty and not allow_empty_snapshot:
            resources = ", ".join(unexpectedly_empty)
            raise RuntimeError(
                "ERPNext returned an empty full snapshot for locally populated resources "
                f"({resources}); verify API read permissions or explicitly allow an empty snapshot"
            )

        known_invoice_ids = store.list_erpnext_sales_invoice_ids(tenant_id, warehouse_id)
        present_invoice_ids = {str(invoice["invoice_id"]) for invoice in invoices}
        deleted_invoice_count = len(known_invoice_ids - present_invoice_ids)
        imported_stock = 0
        imported_orders = 0
        affected_skus: set[str] = set()

        # Apply current records only after every remote resource has been fetched
        # and the two complete snapshots agree.
        for item in bins:
            sku = str(item["item_code"]).strip()
            if not sku:
                raise RuntimeError("ERPNext Bin record is missing item_code")
            effective_as_of = self._modified_timestamp(item["modified"])
            if store.record_erpnext_inventory_snapshot(
                tenant_id,
                warehouse_id,
                sku,
                float(item.get("actual_qty", 0)),
                reserved=float(item.get("reserved_qty", 0)),
                as_of=effective_as_of,
            ):
                imported_stock += 1

        for invoice in invoices:
            effective_modified = str(invoice["modified"])
            affected_skus.update(
                store.apply_erpnext_sales_invoice(
                    tenant_id,
                    warehouse_id,
                    str(invoice["invoice_id"]),
                    posting_date=str(invoice["posting_date"]),
                    docstatus=int(invoice["docstatus"]),
                    modified_at=effective_modified,
                    lines=invoice["lines"],
                )
            )
        affected_skus.update(
            store.reconcile_erpnext_missing_sales_invoices(
                tenant_id,
                warehouse_id,
                {str(invoice["invoice_id"]) for invoice in invoices},
            )
        )
        imported_demand = (
            store.fill_erpnext_demand_gaps(tenant_id, warehouse_id, affected_skus)
            if affected_skus
            else 0
        )

        for order in purchase_orders:
            order_id = f"erpnext:{order['order_id']}"
            effective_modified = str(order["modified"])
            if int(order["docstatus"]) == 2 or not order["lines"]:
                store.cancel_purchase_order(
                    tenant_id,
                    order_id,
                    supplier_id=str(order["supplier_id"]),
                    warehouse_id=warehouse_id,
                    expected_at=order["expected_at"],
                    source_modified_at=effective_modified,
                )
            else:
                store.sync_purchase_order(
                    tenant_id,
                    order_id=order_id,
                    supplier_id=str(order["supplier_id"]),
                    warehouse_id=warehouse_id,
                    expected_at=order["expected_at"],
                    lines=order["lines"],
                    source_modified_at=effective_modified,
                )
            imported_orders += 1

        deleted_orders = store.reconcile_erpnext_missing_purchase_orders(
            tenant_id,
            warehouse_id,
            {f"erpnext:{order['order_id']}" for order in purchase_orders},
        )
        deleted_bins = store.reconcile_erpnext_missing_bins(
            tenant_id,
            warehouse_id,
            {str(item["item_code"]).strip() for item in bins},
        )

        for resource, records in (
            ("Bin", bins),
            ("Sales Invoice", invoices),
            ("Purchase Order", purchase_orders),
        ):
            latest = self._latest_modified(records)
            if latest is not None:
                store.advance_erpnext_watermark(tenant_id, warehouse_id, resource, latest)

        return {
            "inventory_items": imported_stock,
            "daily_demand_rows": imported_demand,
            "purchase_orders": imported_orders,
            "deleted_inventory_items": deleted_bins,
            "deleted_sales_invoices": deleted_invoice_count,
            "deleted_purchase_orders": deleted_orders,
            "snapshot_verified": True,
        }

    def sync_warehouse(
        self,
        store: OperationalStore,
        tenant_id: str,
        warehouse_id: str,
        *,
        warehouse_name: str | None = None,
    ) -> dict[str, int]:
        """Incrementally import ERPNext changes using per-resource overlap watermarks."""
        imported_stock = 0
        imported_demand = 0
        imported_orders = 0

        bin_watermark = store.get_erpnext_watermark(tenant_id, warehouse_id, "Bin")
        balances = self.fetch_bin_changes(
            warehouse_id, modified_since=self._overlap_start(bin_watermark)
        )
        for item in balances:
            sku = str(item.get("item_code", "")).strip()
            if not sku:
                continue
            modified = self._modified_timestamp(item.get("modified"))
            if store.record_erpnext_inventory_snapshot(
                tenant_id,
                warehouse_id,
                sku,
                float(item.get("actual_qty", 0)),
                reserved=float(item.get("reserved_qty", 0)),
                as_of=modified,
            ):
                imported_stock += 1
        latest_bin = self._latest_modified(balances)
        if latest_bin is not None:
            store.advance_erpnext_watermark(tenant_id, warehouse_id, "Bin", latest_bin)

        invoice_watermark = store.get_erpnext_watermark(tenant_id, warehouse_id, "Sales Invoice")
        invoices = self.fetch_sales_invoice_changes(
            warehouse_id, modified_since=self._overlap_start(invoice_watermark)
        )
        affected_skus: set[str] = set()
        for invoice in invoices:
            affected_skus.update(
                store.apply_erpnext_sales_invoice(
                    tenant_id,
                    warehouse_id,
                    invoice["invoice_id"],
                    posting_date=invoice["posting_date"],
                    docstatus=invoice["docstatus"],
                    modified_at=invoice["modified"],
                    lines=invoice["lines"],
                )
            )
        if affected_skus:
            imported_demand = store.fill_erpnext_demand_gaps(tenant_id, warehouse_id, affected_skus)
        latest_invoice = self._latest_modified(invoices)
        if latest_invoice is not None:
            store.advance_erpnext_watermark(
                tenant_id, warehouse_id, "Sales Invoice", latest_invoice
            )

        order_watermark = store.get_erpnext_watermark(tenant_id, warehouse_id, "Purchase Order")
        purchase_orders = self.fetch_purchase_order_changes(
            warehouse_id, modified_since=self._overlap_start(order_watermark)
        )
        for order in purchase_orders:
            order_id = f"erpnext:{order['order_id']}"
            if order["docstatus"] == 2 or not order["lines"]:
                store.cancel_purchase_order(
                    tenant_id,
                    order_id,
                    supplier_id=order["supplier_id"],
                    warehouse_id=warehouse_id,
                    expected_at=order["expected_at"],
                    source_modified_at=order["modified"],
                )
            else:
                store.sync_purchase_order(
                    tenant_id,
                    order_id=order_id,
                    supplier_id=order["supplier_id"],
                    warehouse_id=warehouse_id,
                    expected_at=order["expected_at"],
                    lines=order["lines"],
                    source_modified_at=order["modified"],
                )
            imported_orders += 1
        latest_order = self._latest_modified(purchase_orders)
        if latest_order is not None:
            store.advance_erpnext_watermark(tenant_id, warehouse_id, "Purchase Order", latest_order)

        return {
            "inventory_items": imported_stock,
            "daily_demand_rows": imported_demand,
            "purchase_orders": imported_orders,
        }
