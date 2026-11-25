"""ERPNext/Frappe REST integration for warehouse, stock, and sales history ingestion."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from demand_forecast_kit.operations import OperationalStore

Transport = Callable[[str, str, dict[str, str], bytes | None, float], bytes]


def _http_transport(
    url: str, method: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> bytes:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        # Do not include request headers or credentials in raised messages.
        raise RuntimeError(f"ERPNext returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("ERPNext connection failed") from exc


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
    ) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("ERPNext API key and secret are required")
        if timeout <= 0 or not 1 <= page_size <= 5000:
            raise ValueError("timeout and page_size are out of range")
        self.base_url = base_url.rstrip("/") + "/"
        self._authorization = f"token {api_key}:{api_secret}"
        self.timeout = timeout
        self.transport = transport
        self.page_size = page_size

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
            "order_by": "modified asc",
        }
        url = urljoin(self.base_url, f"api/resource/{doctype}") + "?" + urlencode(query)
        headers = {
            "Authorization": self._authorization,
            "Accept": "application/json",
            "User-Agent": "demand-forecast-kit/0.2",
        }
        raw = self.transport(url, "GET", headers, None, self.timeout)
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ERPNext returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("ERPNext response must be a JSON object")
        data = payload.get("data")
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise RuntimeError("ERPNext response does not contain a valid data list")
        return cast(list[dict[str, Any]], data)

    def list_warehouses(self) -> list[dict[str, Any]]:
        return self._resource(
            "Warehouse",
            fields=["name", "warehouse_name", "parent_warehouse", "is_group", "disabled"],
            filters=[["disabled", "=", 0], ["is_group", "=", 0]],
        )

    def fetch_bin_balances(self, warehouse: str) -> list[dict[str, Any]]:
        if not warehouse.strip():
            raise ValueError("warehouse must not be blank")
        return self._resource(
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

    def sync_warehouse(
        self,
        store: OperationalStore,
        tenant_id: str,
        warehouse_id: str,
        *,
        warehouse_name: str | None = None,
    ) -> dict[str, int]:
        """Import current stock and daily invoiced demand into a local tenant."""
        balances = self.fetch_bin_balances(warehouse_id)
        sales = self.fetch_sales_demand(warehouse_id)
        purchase_orders = self.fetch_purchase_orders(warehouse_id)
        imported_stock = 0
        imported_demand = 0
        imported_orders = 0
        timestamp = datetime.now(UTC)
        for item in balances:
            sku = str(item.get("item_code", "")).strip()
            if not sku:
                continue
            modified = item.get("modified") or timestamp.isoformat()
            store.record_inventory(
                tenant_id,
                warehouse_id,
                sku,
                float(item.get("actual_qty", 0)),
                reserved=float(item.get("reserved_qty", 0)),
                as_of=str(modified).replace(" ", "T")
                + ("+00:00" if "Z" not in str(modified) and "+" not in str(modified) else ""),
                source="erpnext:Bin",
            )
            imported_stock += 1
        for item in sales:
            day = date.fromisoformat(str(item["observed_at"])).isoformat()
            store.record_demand(
                tenant_id,
                warehouse_id,
                str(item["sku_id"]),
                float(item["demand"]),
                observed_at=f"{day}T00:00:00+00:00",
                source="erpnext:Sales Invoice Item",
            )
            imported_demand += 1
        for order in purchase_orders:
            store.sync_purchase_order(
                tenant_id,
                order_id=f"erpnext:{order['order_id']}",
                supplier_id=order["supplier_id"],
                warehouse_id=warehouse_id,
                expected_at=order["expected_at"],
                lines=order["lines"],
            )
            imported_orders += 1
        return {
            "inventory_items": imported_stock,
            "daily_demand_rows": imported_demand,
            "purchase_orders": imported_orders,
        }
