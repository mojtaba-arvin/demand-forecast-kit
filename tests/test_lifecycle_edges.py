from datetime import UTC, datetime, timedelta

import pytest

from demand_forecast_kit.lifecycle import ModelLifecycle, TrainingResult
from demand_forecast_kit.operations import OperationalStore


def _store_with_warehouse(tmp_path) -> OperationalStore:
    store = OperationalStore(tmp_path / "lifecycle.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    return store


def test_lifecycle_validation_and_healthy_assessment(tmp_path) -> None:
    store = _store_with_warehouse(tmp_path)
    lifecycle = ModelLifecycle(store)
    with pytest.raises(ValueError, match="model_id"):
        lifecycle.register_trainer(" ", lambda _request, _history: TrainingResult("v2", 1, 1))
    store.set_model_baseline(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        baseline_mae=1,
        sample_count=20,
    )
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_outcome(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        forecast_origin=origin,
        target_at=origin + timedelta(days=1),
        predicted=10.5,
        actual=10,
    )
    health = lifecycle.assess(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        min_samples=1,
    )
    assert health["status"] == "healthy"
    assert "retraining_request" not in health


def test_lifecycle_retraining_missing_request_and_empty_history(tmp_path) -> None:
    store = _store_with_warehouse(tmp_path)
    lifecycle = ModelLifecycle(store)
    with pytest.raises(KeyError, match="not found"):
        lifecycle.process_retraining_request("tenant-a", "missing")
    request = store.queue_retraining(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        reason="drift",
    )
    lifecycle.register_trainer(
        "model-a", lambda _request, history: TrainingResult("v2", 1, len(history))
    )
    with pytest.raises(ValueError, match="without demand history"):
        lifecycle.process_retraining_request("tenant-a", request["request_id"])
    assert store.list_retraining_requests("tenant-a")[0]["status"] == "failed"


@pytest.mark.parametrize(
    "training_result, message",
    [
        (TrainingResult("", 1, 5), "blank model version"),
        (TrainingResult("v1", 1, 5), "new model version"),
        (TrainingResult("v2", 1, 0), "validation sample"),
        (TrainingResult("v2", float("nan"), 5), "baseline_mae"),
    ],
)
def test_lifecycle_retraining_rejects_invalid_trainer_results(
    tmp_path, training_result: TrainingResult, message: str
) -> None:
    store = _store_with_warehouse(tmp_path)
    start = datetime(2026, 2, 1, tzinfo=UTC)
    for index in range(5):
        store.record_demand(
            "tenant-a",
            "WH-1",
            "SKU-1",
            float(index),
            observed_at=start + timedelta(days=index),
        )
    request = store.queue_retraining(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        reason="drift",
    )
    lifecycle = ModelLifecycle(store)
    lifecycle.register_trainer("model-a", lambda _request, _history: training_result)
    with pytest.raises(ValueError, match=message):
        lifecycle.process_retraining_request("tenant-a", request["request_id"])
    assert store.list_retraining_requests("tenant-a")[0]["status"] == "failed"


def test_lifecycle_marks_trainer_exceptions_as_failed(tmp_path) -> None:
    store = _store_with_warehouse(tmp_path)
    start = datetime(2026, 3, 1, tzinfo=UTC)
    store.record_demand("tenant-a", "WH-1", "SKU-1", 3, observed_at=start)
    request = store.queue_retraining(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        reason="drift",
    )

    def fail(_request, _history):
        raise RuntimeError("trainer failed")

    lifecycle = ModelLifecycle(store, trainers={"model-a": fail})
    with pytest.raises(RuntimeError, match="trainer failed"):
        lifecycle.process_retraining_request("tenant-a", request["request_id"])
    assert store.list_retraining_requests("tenant-a")[0]["status"] == "failed"
