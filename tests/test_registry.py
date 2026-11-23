import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
        dataset_fingerprint="sha256:abc",
        model_id="seasonal-naive",
        model_version="0.1.0",
        config={"horizon": 14, "quantiles": [0.1, 0.5, 0.9]},
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


def test_failed_run_is_immutable_and_idempotent(tmp_path: Path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "runs.sqlite")
    created = registry.create_run(
        idempotency_key="failure-key",
        dataset_fingerprint="dataset",
        model_id="model",
        model_version="1",
        config={"seed": 1},
    )

    failed = registry.fail_run(created.run_id, "forecast adapter failed")
    retry = registry.fail_run(created.run_id, "forecast adapter failed")

    assert failed.status == "failed"
    assert failed.result == {"error": "forecast adapter failed"}
    assert retry == failed
    with pytest.raises(ValueError, match="current state"):
        registry.complete_run(created.run_id, {"forecast": []})
    with pytest.raises(ValueError, match="must not be blank"):
        registry.fail_run(created.run_id, " ")


def test_concurrent_idempotent_creates_return_one_run(tmp_path: Path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "concurrent.sqlite")

    def create() -> int:
        return registry.create_run(
            idempotency_key="concurrent-key",
            dataset_fingerprint="dataset",
            model_id="model",
            model_version="1",
            config={"horizon": 7},
        ).run_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        identifiers = list(executor.map(lambda _: create(), range(16)))

    assert len(set(identifiers)) == 1
    assert registry.get_run(identifiers[0]).status == "created"


def test_inventory_decisions_are_idempotent_and_immutable(tmp_path: Path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "decisions.sqlite")
    run = registry.create_run(
        idempotency_key="decision-run",
        dataset_fingerprint="dataset",
        model_id="seasonal-naive",
        model_version="1",
        config={"horizon": 7},
    )
    decision = {"sku": "sku-1", "quantity": 12, "target_stock": 20}

    first = registry.record_inventory_decision(
        run.run_id, decision_key="sku-1:2026-01-01", decision=decision
    )
    retry = registry.record_inventory_decision(
        run.run_id, decision_key="sku-1:2026-01-01", decision=decision
    )

    assert retry == first
    assert registry.list_inventory_decisions(run.run_id) == (first,)
    with pytest.raises(ValueError, match="different inventory decision"):
        registry.record_inventory_decision(
            run.run_id,
            decision_key="sku-1:2026-01-01",
            decision={"sku": "sku-1", "quantity": 15},
        )


def test_inventory_decision_requires_existing_run(tmp_path: Path) -> None:
    registry = SQLiteRunRegistry(tmp_path / "decisions.sqlite")

    with pytest.raises(KeyError, match="unknown run_id"):
        registry.record_inventory_decision(404, decision_key="decision", decision={"quantity": 1})
    with pytest.raises(KeyError, match="unknown run_id"):
        registry.list_inventory_decisions(404)



def test_inventory_decisions_cannot_be_mutated_or_deleted_via_sql(tmp_path: Path) -> None:
    database = tmp_path / "immutable-decisions.sqlite"
    registry = SQLiteRunRegistry(database)
    run = registry.create_run(
        idempotency_key="immutable-run",
        dataset_fingerprint="dataset",
        model_id="model",
        model_version="1",
        config={},
    )
    decision = registry.record_inventory_decision(
        run.run_id,
        decision_key="sku-1:2026-01-01",
        decision={"sku": "sku-1", "quantity": 12},
    )

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="inventory decisions are immutable"):
            connection.execute(
                "UPDATE inventory_decisions SET decision_json = ? WHERE decision_id = ?",
                ('{"sku":"sku-1","quantity":99}', decision.decision_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="inventory decisions are immutable"):
            connection.execute(
                "DELETE FROM inventory_decisions WHERE decision_id = ?",
                (decision.decision_id,),
            )

    assert registry.list_inventory_decisions(run.run_id) == (decision,)
