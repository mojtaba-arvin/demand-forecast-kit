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


def test_run_service_uses_environment_state_directory(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "environment-state"
    monkeypatch.setenv("DEMAND_FORECAST_STATE_DIR", str(state_dir))

    service = RunService.from_environment()

    assert service.state_dir == state_dir
    assert (state_dir / "runs.sqlite").is_file()


def test_run_service_marks_failed_runs_when_artifact_storage_fails(tmp_path, monkeypatch) -> None:
    import sqlite3

    import pytest

    service = RunService(tmp_path / "failed-state")

    def fail_put(_: bytes):
        raise OSError("simulated artifact storage failure")

    monkeypatch.setattr(service.artifacts, "put", fail_put)
    with pytest.raises(OSError, match="simulated artifact storage failure"):
        service.record_run(
            idempotency_key="failed-run",
            dataset_fingerprint="dataset",
            model_id="model",
            model_version="1",
            config={},
            result={"forecast": [1]},
            artifact_payload=b'{"forecast":[1]}',
        )

    with sqlite3.connect(service.state_dir / "runs.sqlite") as connection:
        status = connection.execute(
            "SELECT status FROM forecast_runs WHERE idempotency_key = ?",
            ("failed-run",),
        ).fetchone()[0]
    assert status == "failed"
    assert service.metrics_snapshot()["counters"]["runs.failed"] == 1
