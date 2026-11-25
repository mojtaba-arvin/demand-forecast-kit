import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from demand_forecast_kit.api import create_app
from demand_forecast_kit.run_service import RunService

testclient = pytest.importorskip("fastapi.testclient")
TestClient = testclient.TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("DEMAND_FORECAST_API_KEYS", raising=False)
    monkeypatch.setenv("DEMAND_FORECAST_ENV", "development")
    return TestClient(create_app(RunService(tmp_path / "ops-api-state")))



def test_retraining_api_requires_current_claim_token_to_finish(client: TestClient) -> None:
    assert client.post(
        "/v1/ops/warehouses",
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main"},
    ).status_code == 201
    assert client.post(
        "/v1/ops/monitoring/baselines",
        json={
            "warehouse_id": "WH-1",
            "sku_id": "SKU-1",
            "model_id": "model-a",
            "model_version": "v1",
            "baseline_mae": 1,
            "sample_count": 20,
        },
    ).status_code == 201
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(10):
        response = client.post(
            "/v1/ops/monitoring/outcomes",
            json={
                "warehouse_id": "WH-1",
                "sku_id": "SKU-1",
                "model_id": "model-a",
                "model_version": "v1",
                "forecast_origin": (origin + timedelta(days=index)).isoformat(),
                "target_at": (origin + timedelta(days=index + 1)).isoformat(),
                "predicted": 20,
                "actual": 10,
            },
        )
        assert response.status_code == 201

    health = client.post(
        "/v1/ops/monitoring/health",
        json={
            "warehouse_id": "WH-1",
            "sku_id": "SKU-1",
            "model_id": "model-a",
            "model_version": "v1",
            "window": 10,
            "min_samples": 10,
        },
    )
    assert health.json()["alert"] is True
    request_id = health.json()["retraining_request"]["request_id"]

    claim = client.post(f"/v1/ops/retraining-requests/{request_id}/claim")
    assert claim.status_code == 200
    token = claim.json()["claim_token"]

    missing_token = client.post(
        f"/v1/ops/retraining-requests/{request_id}/finish",
        json={"success": True},
    )
    assert missing_token.status_code == 422

    finished = client.post(
        f"/v1/ops/retraining-requests/{request_id}/finish",
        json={"success": True, "claim_token": token},
    )
    assert finished.status_code == 200
    assert finished.json()["status"] == "completed"

def test_warehouse_inventory_and_purchase_order_api(client: TestClient) -> None:
    warehouse = client.post(
        "/v1/ops/warehouses",
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main"},
    )
    assert warehouse.status_code == 201

    stock = client.post(
        "/v1/ops/inventory/snapshots",
        json={"warehouse_id": "WH-1", "sku_id": "SKU-1", "quantity": 10, "reserved": 2},
    )
    assert stock.status_code == 201
    assert stock.json()["inventory_position"] == 8

    order = client.post(
        "/v1/ops/purchase-orders",
        json={
            "order_id": "PO-1",
            "supplier_id": "SUP-1",
            "warehouse_id": "WH-1",
            "lines": [{"sku_id": "SKU-1", "quantity": 12, "unit_cost": 2.5}],
        },
    )
    assert order.status_code == 201
    assert client.get("/v1/ops/inventory/WH-1/SKU-1").json()["inventory_position"] == 20

    receipt = client.post(
        "/v1/ops/purchase-orders/PO-1/receipts",
        json={"lines": [{"sku_id": "SKU-1", "quantity": 5}]},
    )
    assert receipt.status_code == 200
    position = client.get("/v1/ops/inventory/WH-1/SKU-1").json()
    assert position["on_hand"] == 15
    assert position["confirmed_inbound"] == 7
    assert position["inventory_position"] == 20


def test_api_rejects_unknown_fields_and_invalid_inventory(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/warehouses",
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main", "admin": True},
    )
    assert response.status_code == 422
    missing_warehouse = client.post(
        "/v1/ops/inventory/snapshots",
        json={"warehouse_id": "missing", "sku_id": "SKU-1", "quantity": 1},
    )
    assert missing_warehouse.status_code == 404


def test_demand_monitoring_and_model_selection_api(client: TestClient) -> None:
    client.post(
        "/v1/ops/warehouses",
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main"},
    )
    start = datetime(2026, 6, 1, tzinfo=UTC)
    for index in range(10):
        response = client.post(
            "/v1/ops/demand/observations",
            json={
                "warehouse_id": "WH-1",
                "sku_id": "SKU-1",
                "observed_at": (start + timedelta(days=index)).isoformat(),
                "demand": index + 1,
            },
        )
        assert response.status_code == 201

    baseline = client.post(
        "/v1/ops/monitoring/baselines",
        json={
            "warehouse_id": "WH-1",
            "sku_id": "SKU-1",
            "model_id": "model-a",
            "model_version": "v1",
            "baseline_mae": 1,
            "sample_count": 20,
        },
    )
    assert baseline.status_code == 201
    for index in range(10):
        response = client.post(
            "/v1/ops/monitoring/outcomes",
            json={
                "warehouse_id": "WH-1",
                "sku_id": "SKU-1",
                "model_id": "model-a",
                "model_version": "v1",
                "forecast_origin": (start + timedelta(days=index)).isoformat(),
                "target_at": (start + timedelta(days=index + 1)).isoformat(),
                "predicted": 20,
                "actual": 10,
            },
        )
        assert response.status_code == 201

    health = client.post(
        "/v1/ops/monitoring/health",
        json={
            "warehouse_id": "WH-1",
            "sku_id": "SKU-1",
            "model_id": "model-a",
            "model_version": "v1",
            "window": 10,
            "min_samples": 10,
        },
    )
    assert health.status_code == 200
    assert health.json()["alert"] is True
    assert health.json()["retraining_request"]["status"] == "queued"

    selection = client.post(
        "/v1/ops/monitoring/model-selection",
        json={"warehouse_id": "WH-1", "sku_id": "SKU-1", "min_samples": 5},
    )
    assert selection.status_code == 200
    assert selection.json()["used_fallback"] is False
    assert selection.json()["selected"]["model_id"] == "model-a"


def test_schedule_api_creates_and_claims_jobs(client: TestClient) -> None:
    created = client.post(
        "/v1/ops/schedules",
        json={
            "job_type": "forecast_refresh",
            "interval_seconds": 300,
            "payload": {"warehouse_id": "WH-1", "sku_id": "SKU-1"},
        },
    )
    assert created.status_code == 201
    assert created.json()["job_type"] == "forecast_refresh"
    claimed = client.post("/v1/ops/schedules/claim-due")
    assert claimed.status_code == 200
    assert len(claimed.json()["jobs"]) == 1


def test_api_keys_enforce_scopes_and_tenant_isolation(tmp_path, monkeypatch) -> None:
    read_token = "tenant-a-read-secret"
    write_token = "tenant-a-write-secret"
    tenant_b_token = "tenant-b-read-secret"

    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    monkeypatch.setenv("DEMAND_FORECAST_ENV", "production")
    monkeypatch.setenv(
        "DEMAND_FORECAST_API_KEYS",
        json.dumps(
            [
                {
                    "key_id": "a-read",
                    "token_sha256": digest(read_token),
                    "tenant_id": "tenant-a",
                    "scopes": ["ops:read"],
                },
                {
                    "key_id": "a-write",
                    "token_sha256": digest(write_token),
                    "tenant_id": "tenant-a",
                    "scopes": ["ops:read", "ops:write", "ops:admin"],
                },
                {
                    "key_id": "b-read",
                    "token_sha256": digest(tenant_b_token),
                    "tenant_id": "tenant-b",
                    "scopes": ["ops:read"],
                },
            ]
        ),
    )
    client = TestClient(create_app(RunService(tmp_path / "secure-api-state")))

    unauthorized = client.get("/v1/ops/warehouses")
    assert unauthorized.status_code == 401

    denied_write = client.post(
        "/v1/ops/warehouses",
        headers={"Authorization": f"Bearer {read_token}"},
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main"},
    )
    assert denied_write.status_code == 403

    created = client.post(
        "/v1/ops/warehouses",
        headers={"Authorization": f"Bearer {write_token}"},
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main"},
    )
    assert created.status_code == 201

    tenant_b = client.get(
        "/v1/ops/warehouses", headers={"Authorization": f"Bearer {tenant_b_token}"}
    )
    assert tenant_b.status_code == 200
    assert tenant_b.json()["warehouses"] == []

    shared_legacy = client.get("/v1/runs/1", headers={"Authorization": f"Bearer {read_token}"})
    assert shared_legacy.status_code == 403


def test_production_mode_fails_closed_without_api_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMAND_FORECAST_ENV", "production")
    monkeypatch.delenv("DEMAND_FORECAST_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="must be configured"):
        create_app(RunService(tmp_path / "no-keys"))


def test_policy_feedback_api_selects_lowest_observed_cost(client: TestClient) -> None:
    client.post(
        "/v1/ops/warehouses",
        json={"warehouse_id": "WH-1", "name": "Main", "location_code": "main"},
    )
    for index in range(5):
        for policy_id, ordered in (("lean", 10), ("excess-stock", 20)):
            response = client.post(
                "/v1/ops/monitoring/policy-outcomes",
                json={
                    "warehouse_id": "WH-1",
                    "sku_id": "SKU-1",
                    "policy_id": policy_id,
                    "decision_key": f"origin-{index}",
                    "inventory_position": 0,
                    "ordered_quantity": ordered,
                    "realized_demand": 8,
                    "holding_cost_per_unit": 1,
                    "shortage_cost_per_unit": 10,
                },
            )
            assert response.status_code == 201
    selected = client.post(
        "/v1/ops/monitoring/policy-selection",
        json={"warehouse_id": "WH-1", "sku_id": "SKU-1", "min_samples": 5},
    )
    assert selected.status_code == 200
    assert selected.json()["selected"]["policy_id"] == "lean"
    assert selected.json()["used_fallback"] is False
