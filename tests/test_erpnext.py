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
            data = [
                {
                    "item_code": "SKU-1",
                    "warehouse": "WH-1",
                    "actual_qty": 20,
                    "reserved_qty": 3,
                    "modified": "2026-11-24 10:00:00",
                }
            ]
        elif doctype == "Sales Invoice":
            data = [
                {
                    "name": "SINV-1",
                    "posting_date": "2026-11-23",
                    "docstatus": 1,
                    "modified": "2026-11-25 10:00:00",
                },
                {
                    "name": "SINV-2",
                    "posting_date": "2026-11-25",
                    "docstatus": 1,
                    "modified": "2026-11-25 11:00:00",
                },
            ]
        elif doctype == "Sales Invoice Item":
            data = [
                {"item_code": "SKU-1", "qty": 2, "parent": "SINV-1", "warehouse": "WH-1"},
                {"item_code": "SKU-1", "qty": 3, "parent": "SINV-1", "warehouse": "WH-1"},
                {"item_code": "SKU-1", "qty": 4, "parent": "SINV-2", "warehouse": "WH-1"},
            ]
        elif doctype == "Purchase Order":
            data = [
                {
                    "name": "PO-1",
                    "supplier": "SUP-1",
                    "schedule_date": "2026-11-30",
                    "docstatus": 1,
                    "modified": "2026-11-25 12:00:00",
                }
            ]
        elif doctype == "Purchase Order Item":
            data = [
                {
                    "item_code": "SKU-1",
                    "qty": 12,
                    "received_qty": 2,
                    "rate": 4,
                    "parent": "PO-1",
                    "warehouse": "WH-1",
                }
            ]
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
        "Bin",
        "Sales Invoice",
        "Sales Invoice Item",
        "Purchase Order",
        "Purchase Order Item",
    ]
    assert calls == expected_calls * 2


def test_erpnext_client_validates_configuration_and_response() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        ERPNextClient("ftp://erp.example", "key", "secret")
    with pytest.raises(ValueError, match="required"):
        ERPNextClient("https://erp.example", "", "secret")

    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=lambda *_args: b"not-json",
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        client.list_warehouses()


def test_erpnext_client_rejects_invalid_data_shape() -> None:
    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=lambda *_args: json.dumps({"data": {}}).encode(),
    )
    with pytest.raises(RuntimeError, match="data list"):
        client.list_warehouses()


def test_erpnext_incremental_sync_reconciles_invoice_edits_and_cancellations(tmp_path) -> None:
    invoices = [
        {
            "name": "SINV-1",
            "posting_date": "2026-11-23",
            "docstatus": 1,
            "modified": "2026-11-25 10:00:00",
        },
        {
            "name": "SINV-2",
            "posting_date": "2026-11-25",
            "docstatus": 1,
            "modified": "2026-11-25 11:00:00",
        },
    ]
    invoice_items = {
        "SINV-1": [{"item_code": "SKU-1", "qty": 5, "parent": "SINV-1", "warehouse": "WH-1"}],
        "SINV-2": [{"item_code": "SKU-1", "qty": 4, "parent": "SINV-2", "warehouse": "WH-1"}],
    }
    bins = [
        {
            "item_code": "SKU-1",
            "warehouse": "WH-1",
            "actual_qty": 20,
            "reserved_qty": 3,
            "modified": "2026-11-25 09:00:00",
        }
    ]
    orders = [
        {
            "name": "PO-1",
            "supplier": "SUP-1",
            "schedule_date": "2026-11-30",
            "docstatus": 1,
            "modified": "2026-11-25 12:00:00",
        }
    ]
    purchase_items = [
        {
            "item_code": "SKU-1",
            "qty": 12,
            "received_qty": 2,
            "rate": 4,
            "parent": "PO-1",
            "warehouse": "WH-1",
        }
    ]

    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        if doctype == "Bin":
            data = bins
        elif doctype == "Sales Invoice":
            data = invoices
        elif doctype == "Sales Invoice Item":
            data = [item for invoice_lines in invoice_items.values() for item in invoice_lines]
        elif doctype == "Purchase Order":
            data = orders
        elif doctype == "Purchase Order Item":
            data = purchase_items if orders and orders[0]["docstatus"] == 1 else []
        else:
            raise AssertionError(doctype)
        return json.dumps({"data": data}).encode()

    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)
    store = OperationalStore(tmp_path / "incremental.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")

    first = client.sync_warehouse(store, "tenant-a", "WH-1")
    assert first["daily_demand_rows"] == 3
    assert [row["demand"] for row in store.demand_history("tenant-a", "WH-1", "SKU-1")] == [
        5.0,
        0.0,
        4.0,
    ]
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["confirmed_inbound"] == 10

    invoices[0] = {
        "name": "SINV-1",
        "posting_date": "2026-11-24",
        "docstatus": 1,
        "modified": "2026-11-26 10:00:00",
    }
    invoice_items["SINV-1"] = [
        {"item_code": "SKU-1", "qty": 7, "parent": "SINV-1", "warehouse": "WH-1"}
    ]
    bins[0] = {**bins[0], "actual_qty": 30, "modified": "2026-11-26 09:00:00"}
    second = client.sync_warehouse(store, "tenant-a", "WH-1")
    assert second["daily_demand_rows"] == 3
    assert [row["demand"] for row in store.demand_history("tenant-a", "WH-1", "SKU-1")] == [
        0.0,
        7.0,
        4.0,
    ]
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["on_hand"] == 30

    invoices[1] = {
        "name": "SINV-2",
        "posting_date": "2026-11-25",
        "docstatus": 2,
        "modified": "2026-11-27 11:00:00",
    }
    orders[0] = {**orders[0], "docstatus": 2, "modified": "2026-11-27 12:00:00"}
    third = client.sync_warehouse(store, "tenant-a", "WH-1")
    assert third["daily_demand_rows"] == 3
    assert [row["demand"] for row in store.demand_history("tenant-a", "WH-1", "SKU-1")] == [
        0.0,
        7.0,
        0.0,
    ]
    assert store.get_purchase_order("tenant-a", "erpnext:PO-1")["status"] == "cancelled"
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["confirmed_inbound"] == 0
    assert store.get_erpnext_watermark("tenant-a", "WH-1", "Sales Invoice") == (
        "2026-11-27T11:00:00+00:00"
    )
    assert store.get_erpnext_watermark("tenant-a", "WH-1", "Purchase Order") == (
        "2026-11-27T12:00:00+00:00"
    )


def test_erpnext_incremental_sync_does_not_advance_failed_resource_watermark(tmp_path) -> None:
    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        if doctype == "Sales Invoice":
            data = [
                {
                    "name": "SINV-BAD",
                    "posting_date": "not-a-date",
                    "docstatus": 1,
                    "modified": "2026-11-25 10:00:00",
                }
            ]
        else:
            data = []
        return json.dumps({"data": data}).encode()

    store = OperationalStore(tmp_path / "failed-sync.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)

    with pytest.raises(ValueError):
        client.sync_warehouse(store, "tenant-a", "WH-1")

    assert store.get_erpnext_watermark("tenant-a", "WH-1", "Sales Invoice") is None


def test_erpnext_watermarks_are_tenant_warehouse_and_resource_scoped(tmp_path) -> None:
    store = OperationalStore(tmp_path / "watermarks.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.create_warehouse("tenant-a", "WH-2", "Secondary", "secondary")
    store.create_warehouse("tenant-b", "WH-1", "Main", "main")

    store.advance_erpnext_watermark(
        "tenant-a", "WH-1", "Sales Invoice", "2026-11-25T10:00:00+00:00"
    )

    assert store.get_erpnext_watermark("tenant-a", "WH-1", "Sales Invoice") == (
        "2026-11-25T10:00:00+00:00"
    )
    assert store.get_erpnext_watermark("tenant-a", "WH-1", "Bin") is None
    assert store.get_erpnext_watermark("tenant-a", "WH-2", "Sales Invoice") is None
    assert store.get_erpnext_watermark("tenant-b", "WH-1", "Sales Invoice") is None
    assert (
        store.advance_erpnext_watermark(
            "tenant-a", "WH-1", "Sales Invoice", "2026-11-25T09:00:00+00:00"
        )
        == "2026-11-25T10:00:00+00:00"
    )


def test_erpnext_invoice_replay_does_not_regress_newer_source_state(tmp_path) -> None:
    store = OperationalStore(tmp_path / "invoice-state.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")

    store.apply_erpnext_sales_invoice(
        "tenant-a",
        "WH-1",
        "SINV-1",
        posting_date="2026-11-25",
        docstatus=1,
        modified_at="2026-11-26T10:00:00+00:00",
        lines=[{"sku_id": "SKU-1", "quantity": 9}],
    )
    stale = store.apply_erpnext_sales_invoice(
        "tenant-a",
        "WH-1",
        "SINV-1",
        posting_date="2026-11-24",
        docstatus=1,
        modified_at="2026-11-25T10:00:00+00:00",
        lines=[{"sku_id": "SKU-1", "quantity": 2}],
    )

    assert stale == set()
    history = store.demand_history("tenant-a", "WH-1", "SKU-1")
    assert [(row["observed_at"], row["demand"]) for row in history] == [
        ("2026-11-25T00:00:00+00:00", 9.0)
    ]


def test_erpnext_sync_does_not_overwrite_manual_demand_or_advance_watermark(tmp_path) -> None:
    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        if doctype == "Sales Invoice":
            data = [
                {
                    "name": "SINV-1",
                    "posting_date": "2026-11-25",
                    "docstatus": 1,
                    "modified": "2026-11-26 10:00:00",
                }
            ]
        elif doctype == "Sales Invoice Item":
            data = [{"item_code": "SKU-1", "qty": 5, "parent": "SINV-1", "warehouse": "WH-1"}]
        else:
            data = []
        return json.dumps({"data": data}).encode()

    store = OperationalStore(tmp_path / "manual-conflict.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.record_demand(
        "tenant-a",
        "WH-1",
        "SKU-1",
        2,
        observed_at="2026-11-25T00:00:00+00:00",
        source="manual",
    )
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)

    with pytest.raises(ValueError, match="conflicts with a non-ERPNext observation"):
        client.sync_warehouse(store, "tenant-a", "WH-1")

    history = store.demand_history("tenant-a", "WH-1", "SKU-1")
    assert history[0]["demand"] == 2
    assert history[0]["source"] == "manual"
    assert store.get_erpnext_watermark("tenant-a", "WH-1", "Sales Invoice") is None


def test_erpnext_purchase_order_source_timestamps_fence_stale_updates(tmp_path) -> None:
    store = OperationalStore(tmp_path / "purchase-order-state.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.sync_purchase_order(
        "tenant-a",
        order_id="erpnext:PO-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 0}],
        source_modified_at="2026-11-26T10:00:00+00:00",
    )
    stale = store.sync_purchase_order(
        "tenant-a",
        order_id="erpnext:PO-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 5, "received_quantity": 0}],
        source_modified_at="2026-11-25T10:00:00+00:00",
    )

    assert stale["lines"][0]["ordered"] == 10
    assert (
        store.cancel_purchase_order(
            "tenant-a", "erpnext:PO-1", source_modified_at="2026-11-25T11:00:00+00:00"
        )
        is False
    )
    assert store.get_purchase_order("tenant-a", "erpnext:PO-1")["status"] == "submitted"
    assert (
        store.cancel_purchase_order(
            "tenant-a", "erpnext:PO-1", source_modified_at="2026-11-27T10:00:00+00:00"
        )
        is True
    )
    stale_replay = store.sync_purchase_order(
        "tenant-a",
        order_id="erpnext:PO-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 0}],
        source_modified_at="2026-11-26T10:00:00+00:00",
    )
    assert stale_replay["status"] == "cancelled"


def test_erpnext_full_reconciliation_removes_hard_deleted_source_records(tmp_path) -> None:
    resources = {
        "Bin": [
            {
                "item_code": "SKU-1",
                "warehouse": "WH-1",
                "actual_qty": 20,
                "reserved_qty": 2,
                "modified": "2026-11-25 09:00:00",
            },
            {
                "item_code": "SKU-2",
                "warehouse": "WH-1",
                "actual_qty": 8,
                "reserved_qty": 0,
                "modified": "2026-11-25 09:01:00",
            },
        ],
        "Sales Invoice": [
            {
                "name": "SINV-1",
                "posting_date": "2026-11-24",
                "docstatus": 1,
                "modified": "2026-11-25 10:00:00",
            }
        ],
        "Sales Invoice Item": [
            {"item_code": "SKU-1", "qty": 5, "parent": "SINV-1", "warehouse": "WH-1"}
        ],
        "Purchase Order": [
            {
                "name": "PO-1",
                "supplier": "SUP-1",
                "schedule_date": "2026-11-30",
                "docstatus": 1,
                "modified": "2026-11-25 11:00:00",
            }
        ],
        "Purchase Order Item": [
            {
                "item_code": "SKU-1",
                "qty": 10,
                "received_qty": 0,
                "rate": 4,
                "parent": "PO-1",
                "warehouse": "WH-1",
            }
        ],
    }

    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        return json.dumps({"data": resources[doctype]}).encode()

    store = OperationalStore(tmp_path / "hard-delete.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)
    client.sync_warehouse(store, "tenant-a", "WH-1")
    store.record_inventory("tenant-a", "WH-1", "SKU-1", 99, source="manual")

    # An empty incremental delta is not proof of deletion and must not remove state.
    for resource in resources:
        resources[resource] = []
    client.sync_warehouse(store, "tenant-a", "WH-1")
    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 5
    assert store.get_purchase_order("tenant-a", "erpnext:PO-1")["status"] == "submitted"
    assert store.inventory_position("tenant-a", "WH-1", "SKU-2")["on_hand"] == 8

    result = client.reconcile_warehouse(store, "tenant-a", "WH-1", allow_empty_snapshot=True)

    assert result == {
        "inventory_items": 0,
        "daily_demand_rows": 0,
        "purchase_orders": 0,
        "deleted_inventory_items": 1,
        "deleted_sales_invoices": 1,
        "deleted_purchase_orders": 1,
        "snapshot_verified": True,
    }
    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 0
    assert store.list_erpnext_sales_invoice_ids("tenant-a", "WH-1") == set()
    assert store.get_purchase_order("tenant-a", "erpnext:PO-1")["status"] == "cancelled"
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["on_hand"] == 99
    assert store.inventory_position("tenant-a", "WH-1", "SKU-2")["on_hand"] == 0
    assert not store.record_erpnext_inventory_snapshot(
        "tenant-a",
        "WH-1",
        "SKU-2",
        8,
        as_of="2026-11-25T09:01:00+00:00",
    )
    assert store.record_erpnext_inventory_snapshot(
        "tenant-a",
        "WH-1",
        "SKU-2",
        6,
        as_of="2026-11-25T09:02:00+00:00",
    )
    assert store.inventory_position("tenant-a", "WH-1", "SKU-2")["on_hand"] == 6

    # Delayed pre-delete events cannot resurrect invoice demand or purchase orders.
    assert (
        store.apply_erpnext_sales_invoice(
            "tenant-a",
            "WH-1",
            "SINV-1",
            posting_date="2026-11-24",
            docstatus=1,
            modified_at="2026-11-25T10:00:00+00:00",
            lines=[{"sku_id": "SKU-1", "quantity": 5}],
        )
        == set()
    )
    stale_order = store.sync_purchase_order(
        "tenant-a",
        order_id="erpnext:PO-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 0}],
        source_modified_at="2026-11-25T11:00:00+00:00",
    )
    assert stale_order["status"] == "cancelled"
    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 0


def test_erpnext_full_reconciliation_fetch_failure_does_not_apply_deletions(tmp_path) -> None:
    resources = {
        "Bin": [
            {
                "item_code": "SKU-1",
                "warehouse": "WH-1",
                "actual_qty": 20,
                "reserved_qty": 0,
                "modified": "2026-11-25 09:00:00",
            }
        ],
        "Sales Invoice": [
            {
                "name": "SINV-1",
                "posting_date": "2026-11-24",
                "docstatus": 1,
                "modified": "2026-11-25 10:00:00",
            }
        ],
        "Sales Invoice Item": [
            {"item_code": "SKU-1", "qty": 5, "parent": "SINV-1", "warehouse": "WH-1"}
        ],
        "Purchase Order": [
            {
                "name": "PO-1",
                "supplier": "SUP-1",
                "schedule_date": "2026-11-30",
                "docstatus": 1,
                "modified": "2026-11-25 11:00:00",
            }
        ],
        "Purchase Order Item": [
            {
                "item_code": "SKU-1",
                "qty": 10,
                "received_qty": 0,
                "rate": 4,
                "parent": "PO-1",
                "warehouse": "WH-1",
            }
        ],
    }

    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        if doctype == "Purchase Order":
            raise RuntimeError("simulated incomplete ERPNext snapshot")
        return json.dumps({"data": resources[doctype]}).encode()

    store = OperationalStore(tmp_path / "incomplete-snapshot.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)

    # Seed the local state with a complete initial import using a transport without failures.
    def seed_transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        return json.dumps({"data": resources[doctype]}).encode()

    ERPNextClient("https://erp.example", "key", "secret", transport=seed_transport).sync_warehouse(
        store, "tenant-a", "WH-1"
    )
    resources["Bin"] = []
    resources["Sales Invoice"] = []
    resources["Sales Invoice Item"] = []
    resources["Purchase Order"] = []
    resources["Purchase Order Item"] = []

    with pytest.raises(RuntimeError, match="incomplete ERPNext snapshot"):
        client.reconcile_warehouse(store, "tenant-a", "WH-1")

    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 5
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["on_hand"] == 20
    assert store.get_purchase_order("tenant-a", "erpnext:PO-1")["status"] == "submitted"


def test_erpnext_full_reconciliation_rejects_unexpected_empty_snapshot(tmp_path) -> None:
    resources = {
        "Bin": [
            {
                "item_code": "SKU-1",
                "warehouse": "WH-1",
                "actual_qty": 20,
                "reserved_qty": 0,
                "modified": "2026-11-25 09:00:00",
            }
        ],
        "Sales Invoice": [
            {
                "name": "SINV-1",
                "posting_date": "2026-11-24",
                "docstatus": 1,
                "modified": "2026-11-25 10:00:00",
            }
        ],
        "Sales Invoice Item": [
            {"item_code": "SKU-1", "qty": 5, "parent": "SINV-1", "warehouse": "WH-1"}
        ],
        "Purchase Order": [],
        "Purchase Order Item": [],
    }

    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        return json.dumps({"data": resources[doctype]}).encode()

    store = OperationalStore(tmp_path / "empty-snapshot.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)
    client.sync_warehouse(store, "tenant-a", "WH-1")
    resources["Bin"] = []
    resources["Sales Invoice"] = []
    resources["Sales Invoice Item"] = []

    with pytest.raises(RuntimeError, match="unexpectedly empty"):
        client.reconcile_warehouse(store, "tenant-a", "WH-1")

    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 5
    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["on_hand"] == 20

def test_erpnext_full_reconciliation_aborts_if_snapshot_changes_between_reads(
    tmp_path,
) -> None:
    resources = {
        "Bin": [
            {
                "item_code": "SKU-1",
                "warehouse": "WH-1",
                "actual_qty": 20,
                "reserved_qty": 0,
                "modified": "2026-11-25 09:00:00",
            }
        ],
        "Sales Invoice": [],
        "Sales Invoice Item": [],
        "Purchase Order": [],
        "Purchase Order Item": [],
    }
    bin_calls = 0

    def transport(url, method, headers, body, timeout):
        nonlocal bin_calls
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        if doctype == "Bin":
            bin_calls += 1
            if bin_calls == 3:
                return json.dumps({"data": []}).encode()
        return json.dumps({"data": resources[doctype]}).encode()

    store = OperationalStore(tmp_path / "changing-snapshot.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)
    client.sync_warehouse(store, "tenant-a", "WH-1")

    with pytest.raises(RuntimeError, match="changed during full reconciliation"):
        client.reconcile_warehouse(store, "tenant-a", "WH-1")

    assert store.inventory_position("tenant-a", "WH-1", "SKU-1")["on_hand"] == 20


def test_erpnext_full_reconciliation_allows_empty_new_warehouse(tmp_path) -> None:
    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=lambda *_args: json.dumps({"data": []}).encode(),
    )
    store = OperationalStore(tmp_path / "empty-new-warehouse.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")

    result = client.reconcile_warehouse(store, "tenant-a", "WH-1")

    assert result == {
        "inventory_items": 0,
        "daily_demand_rows": 0,
        "purchase_orders": 0,
        "deleted_inventory_items": 0,
        "deleted_sales_invoices": 0,
        "deleted_purchase_orders": 0,
        "snapshot_verified": True,
    }


def test_empty_invoice_warehouse_contribution_tombstones_stale_line_replays(tmp_path) -> None:
    store = OperationalStore(tmp_path / "empty-invoice-contribution.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.apply_erpnext_sales_invoice(
        "tenant-a",
        "WH-1",
        "SINV-1",
        posting_date="2026-11-24",
        docstatus=1,
        modified_at="2026-11-25T10:00:00+00:00",
        lines=[{"sku_id": "SKU-1", "quantity": 5}],
    )

    store.apply_erpnext_sales_invoice(
        "tenant-a",
        "WH-1",
        "SINV-1",
        posting_date="2026-11-24",
        docstatus=1,
        modified_at="2026-11-25T10:00:00+00:00",
        lines=[],
    )
    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 0
    assert store.list_erpnext_sales_invoice_ids("tenant-a", "WH-1") == set()

    assert (
        store.apply_erpnext_sales_invoice(
            "tenant-a",
            "WH-1",
            "SINV-1",
            posting_date="2026-11-24",
            docstatus=1,
            modified_at="2026-11-25T10:00:00+00:00",
            lines=[{"sku_id": "SKU-1", "quantity": 5}],
        )
        == set()
    )
    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 0

    store.apply_erpnext_sales_invoice(
        "tenant-a",
        "WH-1",
        "SINV-1",
        posting_date="2026-11-24",
        docstatus=1,
        modified_at="2026-11-25T10:01:00+00:00",
        lines=[{"sku_id": "SKU-1", "quantity": 7}],
    )
    assert store.demand_history("tenant-a", "WH-1", "SKU-1")[0]["demand"] == 7
    assert store.list_erpnext_sales_invoice_ids("tenant-a", "WH-1") == {"SINV-1"}
