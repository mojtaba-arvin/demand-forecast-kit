import json
from urllib.parse import urlsplit

import pytest

from demand_forecast_kit.erpnext import ERPNextClient
from demand_forecast_kit.operations import OperationalStore


def test_erpnext_sync_imports_bin_stock_and_daily_sales(tmp_path) -> None:
    calls: list[str] = []

    def transport(url, method, headers, body, timeout):
        assert method == "GET"
        assert body is None
        assert headers["Authorization"] == "token api-key:api-secret"
        assert timeout == 7
        parsed = urlsplit(url)
        doctype = parsed.path.rsplit("/", 1)[-1]
        calls.append(doctype)
        if doctype == "Bin":
            data = [{
                "item_code": "SKU-1", "warehouse": "WH-1",
                "actual_qty": 20, "reserved_qty": 3, "modified": "2026-11-24 10:00:00",
            }]
        elif doctype == "Sales Invoice":
            data = [
                {"name": "SINV-1", "posting_date": "2026-11-23", "docstatus": 1},
                {"name": "SINV-2", "posting_date": "2026-11-25", "docstatus": 1},
            ]
        elif doctype == "Sales Invoice Item":
            data = [
                {"item_code": "SKU-1", "qty": 2, "parent": "SINV-1", "warehouse": "WH-1"},
                {"item_code": "SKU-1", "qty": 3, "parent": "SINV-1", "warehouse": "WH-1"},
                {"item_code": "SKU-1", "qty": 4, "parent": "SINV-2", "warehouse": "WH-1"},
            ]
        elif doctype == "Purchase Order":
            data = [{
                "name": "PO-1", "supplier": "SUP-1",
                "schedule_date": "2026-11-30", "docstatus": 1,
            }]
        elif doctype == "Purchase Order Item":
            data = [{
                "item_code": "SKU-1", "qty": 12, "received_qty": 2, "rate": 4,
                "parent": "PO-1", "warehouse": "WH-1",
            }]
        else:
            raise AssertionError(f"unexpected ERPNext resource: {doctype}")
        return json.dumps({"data": data}).encode()

    client = ERPNextClient(
        "https://erp.example", "api-key", "api-secret", timeout=7, transport=transport
    )
    store = OperationalStore(tmp_path / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")

    result = client.sync_warehouse(store, "tenant-a", "WH-1")

    assert result == {"inventory_items": 1, "daily_demand_rows": 3, "purchase_orders": 1}
    position = store.inventory_position("tenant-a", "WH-1", "SKU-1")
    assert position["on_hand"] == 20
    assert position["reserved"] == 3
    assert position["confirmed_inbound"] == 10
    assert position["inventory_position"] == 27
    history = store.demand_history("tenant-a", "WH-1", "SKU-1")
    assert [row["demand"] for row in history] == [5, 0, 4]
    order = store.get_purchase_order("tenant-a", "erpnext:PO-1")
    assert order["status"] == "partially_received"
    assert order["lines"][0]["received"] == 2

    repeated = client.sync_warehouse(store, "tenant-a", "WH-1")
    assert repeated == result
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["on_hand"] == 20
    assert len(store.demand_history("tenant-a", "WH-1", "SKU-1")) == 3
    expected_calls = [
        "Bin", "Sales Invoice", "Sales Invoice Item", "Purchase Order", "Purchase Order Item"
    ]
    assert calls == expected_calls * 2


def test_erpnext_client_validates_configuration_and_response() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        ERPNextClient("ftp://erp.example", "key", "secret")
    with pytest.raises(ValueError, match="required"):
        ERPNextClient("https://erp.example", "", "secret")

    client = ERPNextClient(
        "https://erp.example", "key", "secret",
        transport=lambda *_args: b"not-json",
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        client.list_warehouses()


def test_erpnext_client_rejects_invalid_data_shape() -> None:
    client = ERPNextClient(
        "https://erp.example", "key", "secret",
        transport=lambda *_args: json.dumps({"data": {}}).encode(),
    )
    with pytest.raises(RuntimeError, match="data list"):
        client.list_warehouses()
