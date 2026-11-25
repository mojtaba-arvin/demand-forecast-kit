import json

import pytest

from demand_forecast_kit import erpnext_cli


def test_erpnext_reconcile_cli_requires_explicit_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "demand-forecast-erpnext-reconcile",
            "--database",
            "state.sqlite",
            "--tenant-id",
            "tenant-a",
            "--warehouse-id",
            "WH-1",
        ],
    )
    with pytest.raises(SystemExit) as error:
        erpnext_cli.main()
    assert error.value.code == 2


def test_erpnext_reconcile_cli_uses_environment_credentials_and_reports_result(
    monkeypatch, capsys
) -> None:
    calls: dict[str, object] = {}

    class FakeClient:
        def __init__(self, base_url, api_key, api_secret, *, timeout, page_size):
            calls["client"] = (base_url, api_key, api_secret, timeout, page_size)

        def reconcile_warehouse(self, store, tenant_id, warehouse_id, *, allow_empty_snapshot):
            calls["reconcile"] = (store, tenant_id, warehouse_id, allow_empty_snapshot)
            return {"snapshot_verified": True, "deleted_sales_invoices": 2}

    marker_store = object()
    monkeypatch.setattr(erpnext_cli, "ERPNextClient", FakeClient)
    monkeypatch.setattr(erpnext_cli, "OperationalStore", lambda path: (path, marker_store))
    monkeypatch.setenv("DEMAND_FORECAST_ERPNEXT_URL", "https://erp.example")
    monkeypatch.setenv("DEMAND_FORECAST_ERPNEXT_API_KEY", "api-key")
    monkeypatch.setenv("DEMAND_FORECAST_ERPNEXT_API_SECRET", "api-secret")
    monkeypatch.setattr(
        "sys.argv",
        [
            "demand-forecast-erpnext-reconcile",
            "--database",
            "state.sqlite",
            "--tenant-id",
            "tenant-a",
            "--warehouse-id",
            "WH-1",
            "--timeout",
            "9",
            "--page-size",
            "100",
            "--confirm-full-snapshot",
        ],
    )

    erpnext_cli.main()

    assert calls["client"] == (
        "https://erp.example",
        "api-key",
        "api-secret",
        9.0,
        100,
    )
    assert calls["reconcile"] == (("state.sqlite", marker_store), "tenant-a", "WH-1", False)
    assert json.loads(capsys.readouterr().out) == {
        "snapshot_verified": True,
        "deleted_sales_invoices": 2,
    }


def test_erpnext_reconcile_cli_requires_credentials(monkeypatch) -> None:
    monkeypatch.delenv("DEMAND_FORECAST_ERPNEXT_URL", raising=False)
    monkeypatch.delenv("DEMAND_FORECAST_ERPNEXT_API_KEY", raising=False)
    monkeypatch.delenv("DEMAND_FORECAST_ERPNEXT_API_SECRET", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "demand-forecast-erpnext-reconcile",
            "--database",
            "state.sqlite",
            "--tenant-id",
            "tenant-a",
            "--warehouse-id",
            "WH-1",
            "--confirm-full-snapshot",
        ],
    )

    with pytest.raises(SystemExit) as error:
        erpnext_cli.main()
    assert error.value.code == 2
