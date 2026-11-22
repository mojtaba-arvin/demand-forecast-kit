import pytest

from demand_forecast_kit.registry import SQLiteRunRegistry


def test_registry_create_is_idempotent_and_round_trips(tmp_path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "runs.sqlite")
    first = registry.create_run(
        idempotency_key="forecast:dataset-a:sku-1:2026-01-01",
        dataset_fingerprint="sha256:abc",
        model_id="seasonal-naive",
        model_version="0.1.0",
        config={"horizon": 14, "quantiles": [0.1, 0.5, 0.9]},
    )
    retry = registry.create_run(
        idempotency_key="forecast:dataset-a:sku-1:2026-01-01",
        dataset_fingerprint="sha256:changed",
        model_id="other-model",
        model_version="9.9",
        config={"horizon": 99},
    )

    assert retry == first
    completed = registry.complete_run(first.run_id, {"p50": [1.0, 2.0]})
    assert completed.status == "completed"
    assert registry.get_run(first.run_id) == completed


def test_registry_completion_is_idempotent_but_immutable(tmp_path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "runs.sqlite")
    run = registry.create_run(
        idempotency_key="key",
        dataset_fingerprint="fingerprint",
        model_id="model",
        model_version="1",
        config={},
    )
    registry.complete_run(run.run_id, {"value": 1})
    assert registry.complete_run(run.run_id, {"value": 1}).status == "completed"
    with pytest.raises(ValueError, match="current state"):
        registry.complete_run(run.run_id, {"value": 2})


def test_registry_rejects_non_json_payload(tmp_path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "runs.sqlite")
    with pytest.raises(ValueError, match="finite JSON"):
        registry.create_run(
            idempotency_key="key",
            dataset_fingerprint="fingerprint",
            model_id="model",
            model_version="1",
            config={"bad": float("nan")},
        )


def test_registry_unknown_run_raises_key_error(tmp_path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "runs.sqlite")
    with pytest.raises(KeyError, match="unknown"):
        registry.get_run(404)


def test_idempotency_key_cannot_be_reused_for_different_run_inputs(tmp_path: Path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "runs.sqlite")
    original = registry.create_run(
        idempotency_key="stable-key",
        dataset_fingerprint="dataset-a",
        model_id="seasonal-naive",
        model_version="1",
        config={"horizon": 7},
    )
    retry = registry.create_run(
        idempotency_key="stable-key",
        dataset_fingerprint="dataset-a",
        model_id="seasonal-naive",
        model_version="1",
        config={"horizon": 7},
    )

    assert retry.run_id == original.run_id
    with pytest.raises(ValueError, match="different dataset, model, or config"):
        registry.create_run(
            idempotency_key="stable-key",
            dataset_fingerprint="dataset-b",
            model_id="seasonal-naive",
            model_version="1",
            config={"horizon": 7},
        )
    with pytest.raises(ValueError, match="different dataset, model, or config"):
        registry.create_run(
            idempotency_key="stable-key",
            dataset_fingerprint="dataset-a",
            model_id="seasonal-naive",
            model_version="1",
            config={"horizon": 14},
        )
