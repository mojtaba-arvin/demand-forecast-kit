from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

from demand_forecast_kit.api import create_app
from demand_forecast_kit.run_service import RunService

testclient = pytest.importorskip("fastapi.testclient")
TestClient = testclient.TestClient


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(RunService(tmp_path / "api-state")))


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"



def test_liveness_and_readiness_report_operational_dependencies(client: TestClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "dependencies": {
            "run_registry": True,
            "operational_store": True,
            "artifact_store": True,
        },
    }


def test_readiness_fails_closed_when_operational_database_is_missing(
    client: TestClient,
) -> None:
    service = client.app.state.run_service
    (service.state_dir / "operations.sqlite").unlink()

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "dependencies": {
            "run_registry": True,
            "operational_store": False,
            "artifact_store": True,
        },
    }


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
    assert first.json()["run"]["status"] == "completed"
    assert len(first.json()["run"]["artifact_sha256"]) == 64
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
    assert response.json()["run"]["status"] == "completed"


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


def test_replenishment_endpoint_records_immutable_decision(client: TestClient) -> None:
    forecast = client.post(
        "/v1/forecasts",
        json={"series_id": "sku-decision", "history": [1, 2, 3, 4, 5, 6, 7]},
    )
    run_id = forecast.json()["run"]["run_id"]
    response = client.post(
        "/v1/replenishment/recommendations",
        json={
            "lead_time_demand_quantiles": {"0.1": 10, "0.5": 20, "0.9": 40},
            "underage_cost": 9,
            "overage_cost": 1,
            "inventory_position": 12,
            "run_id": run_id,
            "decision_key": "sku-decision:2026-01-01",
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"]["run_id"] == run_id
    assert response.json()["decision"]["decision_id"] > 0

    retrieved = client.get(f"/v1/runs/{run_id}/decisions")
    assert retrieved.status_code == 200
    assert retrieved.json()["run_id"] == run_id
    assert retrieved.json()["decisions"] == [
        {
            "decision_id": response.json()["decision"]["decision_id"],
            "run_id": run_id,
            "decision_key": "sku-decision:2026-01-01",
            "created_at": retrieved.json()["decisions"][0]["created_at"],
            "decision": {
                "quantity": 28,
                "target_stock_level": 40.0,
                "inventory_position": 12.0,
                "target_service_level": 0.9,
                "unrounded_quantity": 28.0,
            },
        }
    ]


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


def test_forecast_endpoint_handles_independent_concurrent_requests(tmp_path) -> None:
    payload = {
        "series_id": "sku-concurrent",
        "history": [float(index % 7) for index in range(28)],
        "horizon": 4,
        "season_length": 7,
    }

    service = RunService(tmp_path / "concurrent-api-state")

    def send_request(_: int) -> dict[str, object]:
        with TestClient(create_app(service)) as concurrent_client:
            response = concurrent_client.post("/v1/forecasts", json=payload)
            assert response.status_code == 200
            return response.json()

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(send_request, range(8)))

    assert all(response == responses[0] for response in responses)


def test_persisted_run_and_artifact_can_be_retrieved(client: TestClient) -> None:
    forecast = client.post(
        "/v1/forecasts",
        json={
            "series_id": "sku-retrieval",
            "history": [1, 2, 3, 4, 5, 6, 7],
            "horizon": 2,
        },
    )
    assert forecast.status_code == 200
    run_ref = forecast.json()["run"]

    run_response = client.get(f"/v1/runs/{run_ref['run_id']}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["run_id"] == run_ref["run_id"]
    assert run["status"] == "completed"
    assert run["model_id"] == "seasonal-naive"
    assert run["result"]["artifact_sha256"] == run_ref["artifact_sha256"]

    artifact_response = client.get(f"/v1/artifacts/{run_ref['artifact_sha256']}")
    assert artifact_response.status_code == 200
    assert artifact_response.headers["content-type"].startswith("application/json")
    assert artifact_response.headers["etag"] == f'"{run_ref["artifact_sha256"]}"'
    assert artifact_response.headers["cache-control"] == "private, immutable"
    assert artifact_response.content == (
        client.app.state.run_service.artifacts.get(run_ref["artifact_sha256"])
    )


def test_run_and_artifact_retrieval_return_not_found_without_leaking_paths(
    client: TestClient,
) -> None:
    missing_run = client.get("/v1/runs/999999")
    assert missing_run.status_code == 404
    assert missing_run.json() == {"detail": "run not found"}

    missing_artifact = client.get("/v1/artifacts/" + "0" * 64)
    assert missing_artifact.status_code == 404
    assert missing_artifact.json() == {"detail": "artifact not found"}

    malformed_artifact = client.get("/v1/artifacts/not-a-digest")
    assert malformed_artifact.status_code == 404
    assert malformed_artifact.json() == {"detail": "artifact not found"}


def test_run_decision_retrieval_returns_empty_list_and_unknown_run_404(
    client: TestClient,
) -> None:
    forecast = client.post(
        "/v1/forecasts",
        json={"series_id": "sku-no-decisions", "history": [1, 2, 3, 4, 5, 6, 7]},
    )
    run_id = forecast.json()["run"]["run_id"]

    empty = client.get(f"/v1/runs/{run_id}/decisions")
    assert empty.status_code == 200
    assert empty.json() == {"run_id": run_id, "decisions": []}

    missing = client.get("/v1/runs/999999/decisions")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "run not found"}
