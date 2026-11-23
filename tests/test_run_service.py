from __future__ import annotations

from demand_forecast_kit.run_service import RunService


def test_run_service_persists_idempotent_artifacts_decisions_and_metrics(tmp_path) -> None:
    service = RunService(tmp_path / "state")
    artifact_payload = b'{"forecast":[1,2,3]}'
    config = {"horizon": 3, "seed": 42}
    identity = {
        "dataset_fingerprint": service.fingerprint(b"dataset"),
        "model_id": "seasonal-naive",
        "model_version": "0.1.0",
        "config": config,
    }
    run_args = {
        **identity,
        "idempotency_key": service.idempotency_key(**identity),
        "result": {"forecast": [1, 2, 3]},
        "artifact_payload": artifact_payload,
    }

    first = service.record_run(**run_args)
    second = service.record_run(**run_args)

    assert first == second
    assert first.status == "completed"
    assert service.artifacts.get(first.artifact_sha256) == artifact_payload
    decision = service.record_inventory_decision(
        first.run_id,
        decision_key="sku-1:2026-01-01",
        decision={"sku": "sku-1", "quantity": 12},
    )
    assert decision["run_id"] == first.run_id
    assert decision["decision_id"] > 0
    snapshot = service.metrics_snapshot()
    assert snapshot["counters"]["runs.completed"] == 2
    assert snapshot["counters"]["inventory_decisions.recorded"] == 1
    assert snapshot["observations"]["run.artifact_bytes"]["count"] == 2
