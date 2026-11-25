import json
from urllib.error import HTTPError, URLError

import pytest

from demand_forecast_kit.erpnext import ERPNextClient, ERPNextRequestError
from demand_forecast_kit.operations import OperationalStore


def test_http_transport_sanitizes_server_and_connection_errors(monkeypatch) -> None:
    from demand_forecast_kit import erpnext

    client = ERPNextClient("https://erp.example", "key", "secret")

    def http_error(_request, timeout):
        raise HTTPError("https://erp.example/private", 500, "failed", None, None)

    monkeypatch.setattr(erpnext, "urlopen", http_error)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        client.list_warehouses()

    def connection_error(_request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(erpnext, "urlopen", connection_error)
    with pytest.raises(RuntimeError, match="connection failed"):
        client.list_warehouses()


def test_erpnext_configuration_and_empty_resource_paths() -> None:
    with pytest.raises(ValueError, match="out of range"):
        ERPNextClient("https://erp.example", "key", "secret", timeout=0)
    with pytest.raises(ValueError, match="out of range"):
        ERPNextClient("https://erp.example", "key", "secret", page_size=5001)

    def empty_transport(url, method, headers, body, timeout):
        return json.dumps({"data": []}).encode()

    client = ERPNextClient("https://erp.example", "key", "secret", transport=empty_transport)
    assert client.list_warehouses() == []
    assert client.fetch_sales_demand("WH-1") == []
    assert client.fetch_purchase_orders("WH-1") == []
    with pytest.raises(ValueError, match="warehouse"):
        client.fetch_bin_balances(" ")
    with pytest.raises(ValueError, match="warehouse"):
        client.fetch_purchase_orders(" ")


def test_erpnext_retries_transient_server_errors_with_bounded_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def transport(url, method, headers, body, timeout):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ERPNextRequestError("ERPNext returned HTTP 503", status_code=503)
        return json.dumps({"data": [{"name": "WH-1"}]}).encode()

    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=transport,
        max_retries=2,
        retry_backoff_seconds=0.1,
        sleep=delays.append,
    )

    assert client.list_warehouses() == [{"name": "WH-1"}]
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_erpnext_honors_retry_after_and_does_not_retry_client_errors() -> None:
    attempts = 0
    delays: list[float] = []

    def rate_limited(url, method, headers, body, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ERPNextRequestError(
                "ERPNext returned HTTP 429",
                status_code=429,
                retry_after_seconds=2.5,
            )
        return json.dumps({"data": []}).encode()

    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=rate_limited,
        sleep=delays.append,
    )
    assert client.list_warehouses() == []
    assert attempts == 2
    assert delays == [2.5]

    client_error_attempts = 0

    def bad_request(url, method, headers, body, timeout):
        nonlocal client_error_attempts
        client_error_attempts += 1
        raise ERPNextRequestError("ERPNext returned HTTP 400", status_code=400)

    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=bad_request,
        sleep=lambda _delay: None,
    )
    with pytest.raises(ERPNextRequestError, match="HTTP 400"):
        client.list_warehouses()
    assert client_error_attempts == 1


def test_erpnext_retry_configuration_is_bounded() -> None:
    with pytest.raises(ValueError, match="retry configuration"):
        ERPNextClient("https://erp.example", "key", "secret", max_retries=11)
    with pytest.raises(ValueError, match="retry configuration"):
        ERPNextClient("https://erp.example", "key", "secret", retry_backoff_seconds=-1)


def test_erpnext_empty_sync_is_safe_and_does_not_create_fake_rows(tmp_path) -> None:
    store = OperationalStore(tmp_path / "empty.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    client = ERPNextClient(
        "https://erp.example",
        "key",
        "secret",
        transport=lambda *_args: json.dumps({"data": []}).encode(),
    )
    assert client.sync_warehouse(store, "tenant-a", "WH-1") == {
        "inventory_items": 0,
        "daily_demand_rows": 0,
        "purchase_orders": 0,
    }
    assert store.list_warehouses("tenant-a")[0]["warehouse_id"] == "WH-1"


def test_erpnext_purchase_order_duplicate_lines_are_aggregated() -> None:
    def transport(url, method, headers, body, timeout):
        doctype = url.split("/api/resource/")[1].split("?")[0]
        if doctype == "Purchase Order":
            data = [{"name": "PO-1", "supplier": "SUP-1", "schedule_date": None}]
        elif doctype == "Purchase Order Item":
            data = [
                {
                    "item_code": "SKU-1",
                    "qty": 2,
                    "received_qty": 1,
                    "rate": 4,
                    "parent": "PO-1",
                    "warehouse": "WH-1",
                },
                {
                    "item_code": "SKU-1",
                    "qty": 3,
                    "received_qty": 2,
                    "rate": 6,
                    "parent": "PO-1",
                    "warehouse": "WH-1",
                },
                {
                    "item_code": " ",
                    "qty": 5,
                    "received_qty": 0,
                    "rate": 2,
                    "parent": "PO-1",
                    "warehouse": "WH-1",
                },
            ]
        else:
            raise AssertionError(doctype)
        return json.dumps({"data": data}).encode()

    orders = ERPNextClient(
        "https://erp.example", "key", "secret", transport=transport
    ).fetch_purchase_orders("WH-1")
    assert len(orders) == 1
    assert orders[0]["lines"] == [
        {
            "sku_id": "SKU-1",
            "quantity": 5.0,
            "received_quantity": 3.0,
            "unit_cost": 5.2,
        }
    ]


def test_erpnext_paginates_invoice_and_purchase_order_headers() -> None:
    def transport(url, method, headers, body, timeout):
        from urllib.parse import parse_qs, urlsplit

        parsed = urlsplit(url)
        doctype = parsed.path.rsplit("/", 1)[-1]
        offset = int(parse_qs(parsed.query)["limit_start"][0])
        if doctype == "Sales Invoice":
            data = [
                {"name": "SINV-1", "posting_date": "2026-01-01"},
                {"name": "SINV-2", "posting_date": "2026-01-02"},
            ][offset : offset + 1]
        elif doctype == "Sales Invoice Item":
            data = [
                {"item_code": "SKU-1", "qty": 1, "parent": "SINV-1", "warehouse": "WH-1"},
                {"item_code": "SKU-1", "qty": 2, "parent": "SINV-2", "warehouse": "WH-1"},
            ][offset : offset + 1]
        elif doctype == "Purchase Order":
            data = [
                {"name": "PO-1", "supplier": "SUP-1", "schedule_date": None},
                {"name": "PO-2", "supplier": "SUP-2", "schedule_date": None},
            ][offset : offset + 1]
        elif doctype == "Purchase Order Item":
            data = [
                {
                    "item_code": "SKU-1",
                    "qty": 1,
                    "received_qty": 0,
                    "rate": 1,
                    "parent": "PO-1",
                    "warehouse": "WH-1",
                },
                {
                    "item_code": "SKU-2",
                    "qty": 2,
                    "received_qty": 0,
                    "rate": 2,
                    "parent": "PO-2",
                    "warehouse": "WH-1",
                },
            ][offset : offset + 1]
        else:
            raise AssertionError(doctype)
        return json.dumps({"data": data}).encode()

    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport, page_size=1)
    assert len(client.fetch_sales_demand("WH-1")) == 2
    assert len(client.fetch_purchase_orders("WH-1")) == 2


def test_erpnext_paginates_warehouse_and_bin_resources() -> None:
    from urllib.parse import parse_qs, urlsplit

    resources = {
        "Warehouse": [
            {"name": "WH-1", "warehouse_name": "Main"},
            {"name": "WH-2", "warehouse_name": "Secondary"},
        ],
        "Bin": [
            {"item_code": "SKU-1", "warehouse": "WH-1", "actual_qty": 10, "reserved_qty": 1},
            {"item_code": "SKU-2", "warehouse": "WH-1", "actual_qty": 20, "reserved_qty": 2},
        ],
    }

    def transport(url, method, headers, body, timeout):
        parsed = urlsplit(url)
        doctype = parsed.path.rsplit("/", 1)[-1]
        query = parse_qs(parsed.query)
        offset = int(query["limit_start"][0])
        page_size = int(query["limit_page_length"][0])
        assert query["order_by"] == ["modified asc, name asc"]
        return json.dumps({"data": resources[doctype][offset : offset + page_size]}).encode()

    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport, page_size=1)
    assert [item["name"] for item in client.list_warehouses()] == ["WH-1", "WH-2"]
    assert [item["item_code"] for item in client.fetch_bin_balances("WH-1")] == [
        "SKU-1",
        "SKU-2",
    ]


def test_erpnext_full_snapshot_rejects_duplicate_resource_keys() -> None:
    client = ERPNextClient("https://erp.example", "key", "secret")
    with pytest.raises(RuntimeError, match="duplicate keys"):
        client._assert_unique_snapshot_keys(
            [{"item_code": "SKU-1"}, {"item_code": "SKU-1"}],
            "item_code",
            "Bin",
        )
