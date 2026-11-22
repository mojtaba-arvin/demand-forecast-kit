from datetime import date, timedelta

import pytest

testclient = pytest.importorskip("fastapi.testclient")
TestClient = testclient.TestClient

from demand_forecast_kit.api import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_forecast_endpoint_returns_deterministic_quantile_contract(client: TestClient) -> None:
    payload = {
        "series_id": "sku-1",
        "history": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
        "horizon": 3,
        "season_length": 7,
        "quantiles": [0.9, 0.1, 0.5],
    }
    first = client.post("/v1/forecasts", json=payload)
    second = client.post("/v1/forecasts", json=payload)

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["horizon"] == 3
    assert list(first.json()["quantiles"]) == ["0.1", "0.5", "0.9"]


def test_forecast_endpoint_rejects_invalid_history_and_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/v1/forecasts",
        json={"series_id": "sku-1", "history": [-1, 2, 3], "unexpected": True},
    )
    assert response.status_code == 422


def test_backtest_endpoint_returns_auditable_report(client: TestClient) -> None:
    observations = [
        {"timestamp": (date(2024, 1, 1) + timedelta(days=index)).isoformat(), "demand": index % 7}
        for index in range(50)
    ]
    response = client.post(
        "/v1/backtests",
        json={
            "series_id": "sku-1",
            "observations": observations,
            "initial_train_size": 30,
            "horizon": 7,
            "step": 7,
            "season_length": 7,
            "quantiles": [0.1, 0.5, 0.9],
        },
    )
    assert response.status_code == 200
    assert response.json()["schema_version"] == 2
    assert response.json()["evaluations"]


def test_backtest_endpoint_rejects_non_chronological_observations(client: TestClient) -> None:
    response = client.post(
        "/v1/backtests",
        json={
            "series_id": "sku-1",
            "observations": [
                {"timestamp": "2024-01-02", "demand": 2},
                {"timestamp": "2024-01-01", "demand": 1},
                {"timestamp": "2024-01-03", "demand": 3},
            ],
            "initial_train_size": 2,
            "horizon": 1,
        },
    )
    assert response.status_code == 422


def test_replenishment_endpoint_uses_cumulative_quantiles(client: TestClient) -> None:
    response = client.post(
        "/v1/replenishment/recommendations",
        json={
            "lead_time_demand_quantiles": {"0.1": 10, "0.5": 20, "0.9": 40},
            "underage_cost": 9,
            "overage_cost": 1,
            "inventory_position": 12,
            "pack_size": 6,
        },
    )
    assert response.status_code == 200
    assert response.json()["target_service_level"] == 0.9
    assert response.json()["quantity"] == 30


def test_replenishment_endpoint_rejects_unbracketed_service_level(client: TestClient) -> None:
    response = client.post(
        "/v1/replenishment/recommendations",
        json={
            "lead_time_demand_quantiles": {"0.1": 10, "0.5": 20},
            "underage_cost": 9,
            "overage_cost": 1,
            "inventory_position": 0,
        },
    )
    assert response.status_code == 422
