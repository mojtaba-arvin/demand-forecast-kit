import sys
import threading
from datetime import UTC, datetime, timedelta

import pytest

from demand_forecast_kit.operations import OperationalStore
from demand_forecast_kit.operations_worker import OperationalWorker
from demand_forecast_kit.run_service import RunService


def _new_service_store(tmp_path):
    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    return service, store


def test_worker_model_health_job_queues_retraining_and_leaves_unconfigured_trainer_queued(
    tmp_path,
) -> None:
    service, store = _new_service_store(tmp_path)
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    store.set_model_baseline(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        baseline_mae=1,
        sample_count=20,
    )
    for index in range(10):
        store.record_outcome(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="model-a",
            model_version="v1",
            forecast_origin=origin + timedelta(days=index),
            target_at=origin + timedelta(days=index + 1),
            predicted=20,
            actual=10,
        )
    store.create_schedule(
        "tenant-a",
        job_type="model_health",
        payload={
            "warehouse_id": "WH-1",
            "sku_id": "SKU-1",
            "model_id": "model-a",
            "model_version": "v1",
            "window": 10,
            "min_samples": 10,
        },
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    report = OperationalWorker(service, store).run_once("tenant-a")
    assert report["completed"][0]["result"]["alert"] is True
    assert report["retraining"] == []
    assert store.list_retraining_requests("tenant-a")[0]["status"] == "queued"


def test_worker_catches_registered_trainer_failure(tmp_path) -> None:
    service, store = _new_service_store(tmp_path)
    store.record_demand(
        "tenant-a", "WH-1", "SKU-1", 3, observed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    request = store.queue_retraining(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        reason="drift",
    )
    worker = OperationalWorker(service, store)

    def fail(_request, _history):
        raise RuntimeError("trainer unavailable at runtime")

    worker.register_trainer("model-a", fail)
    report = worker.run_once("tenant-a")
    assert report["retraining"] == []
    assert report["failed"][0]["job_id"] == request["request_id"]
    assert store.list_retraining_requests("tenant-a")[0]["status"] == "failed"


def test_worker_reports_lost_scheduler_lease_without_aborting_poll(tmp_path, monkeypatch) -> None:
    service, store = _new_service_store(tmp_path)
    store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    def stale_release(*_args, **_kwargs):
        raise ValueError("scheduled job lease is stale")

    monkeypatch.setattr(store, "release_schedule", stale_release)
    report = OperationalWorker(service, store).run_once("tenant-a")

    assert len(report["failed"]) == 1
    assert "lease release failed: ValueError" in report["failed"][0]["error"]


def test_worker_falls_back_when_selected_adapter_is_not_registered(tmp_path) -> None:
    service, store = _new_service_store(tmp_path)
    start = datetime(2026, 2, 1, tzinfo=UTC)
    for index in range(21):
        store.record_demand(
            "tenant-a",
            "WH-1",
            "SKU-1",
            float(index % 7),
            observed_at=start + timedelta(days=index),
        )
    for index in range(5):
        store.record_outcome(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="missing-adapter",
            model_version="v1",
            forecast_origin=start + timedelta(days=index),
            target_at=start + timedelta(days=index + 1),
            predicted=10,
            actual=10,
        )
    store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "horizon": 2},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    result = OperationalWorker(service, store).run_once("tenant-a")["completed"][0]["result"]
    selection = result["forecast"]["model_selection"]
    assert selection["used_fallback"] is False
    assert selection["adapter_fallback_reason"].startswith("selected_adapter")
    assert result["forecast"]["model_id"] == "seasonal-naive"


def test_worker_policy_review_uses_fallback_without_observed_policy_results(tmp_path) -> None:
    service, store = _new_service_store(tmp_path)
    store.create_schedule(
        "tenant-a",
        job_type="policy_review",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "fallback_policy_id": "safe-default"},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    report = OperationalWorker(service, store).run_once("tenant-a")
    result = report["completed"][0]["result"]
    assert result["used_fallback"] is True
    assert result["selected"]["policy_id"] == "safe-default"


def test_worker_rejects_unknown_job_type(tmp_path) -> None:
    service, store = _new_service_store(tmp_path)
    worker = OperationalWorker(service, store)
    with pytest.raises(ValueError, match="unsupported"):
        worker._execute("tenant-a", {"job_type": "unknown", "payload": {}})


def test_worker_cli_once_and_invalid_arguments(tmp_path, monkeypatch) -> None:
    from demand_forecast_kit import operations_worker

    service = RunService(tmp_path / "cli-state")

    class FakeRunService:
        @classmethod
        def from_environment(cls):
            return service

    monkeypatch.setattr(operations_worker, "RunService", FakeRunService)
    monkeypatch.setattr(sys, "argv", ["worker", "--once", "--tenant-id", "tenant-a"])
    operations_worker.main()

    monkeypatch.setattr(sys, "argv", ["worker", "--once", "--poll-seconds", "0"])
    with pytest.raises(SystemExit):
        operations_worker.main()


def test_worker_cli_poll_loop_sleeps_between_polls(tmp_path, monkeypatch) -> None:
    from demand_forecast_kit import operations_worker

    service = RunService(tmp_path / "cli-loop-state")

    class FakeRunService:
        @classmethod
        def from_environment(cls):
            return service

    class StopPolling(Exception):
        pass

    monkeypatch.setattr(operations_worker, "RunService", FakeRunService)
    monkeypatch.setattr(sys, "argv", ["worker", "--tenant-id", "tenant-a"])

    original_wait = threading.Event.wait

    def stop_polling(_event, timeout=None):
        if threading.current_thread() is threading.main_thread() and timeout == 15:
            raise StopPolling
        return original_wait(_event, timeout)

    monkeypatch.setattr(threading.Event, "wait", stop_polling)
    with pytest.raises(StopPolling):
        operations_worker.main()
