from datetime import UTC, datetime, timedelta

import pytest

from demand_forecast_kit.lifecycle import ModelLifecycle, TrainingResult
from demand_forecast_kit.operations import OperationalStore


@pytest.fixture
def store(tmp_path) -> OperationalStore:
    return OperationalStore(tmp_path / "operations.sqlite")


def create_warehouse(store: OperationalStore, tenant: str = "tenant-a") -> None:
    store.create_warehouse(tenant, "WH-1", "Main warehouse", "main")


def test_warehouse_and_inventory_are_tenant_scoped(store: OperationalStore) -> None:
    create_warehouse(store)
    store.record_inventory("tenant-a", "WH-1", "SKU-1", 30, reserved=5, backorders=2)

    position = store.inventory_position("tenant-a", "WH-1", "SKU-1")
    assert position["inventory_position"] == 23
    assert position["on_hand"] == 30
    assert position["reserved"] == 5
    assert position["backorders"] == 2
    assert store.list_warehouses("tenant-a")[0]["warehouse_id"] == "WH-1"
    assert store.list_warehouses("tenant-b") == []
    with pytest.raises(KeyError, match="warehouse not found"):
        store.inventory_position("tenant-b", "WH-1", "SKU-1")


def test_purchase_order_receipts_move_inbound_into_on_hand_without_changing_position(
    store: OperationalStore,
) -> None:
    create_warehouse(store)
    store.record_inventory("tenant-a", "WH-1", "SKU-1", 10, reserved=2)
    store.create_purchase_order(
        "tenant-a", order_id="PO-1", supplier_id="SUP-1", warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 12, "unit_cost": 3.5}],
    )
    before = store.inventory_position("tenant-a", "WH-1", "SKU-1")
    assert before["inventory_position"] == 20
    assert before["confirmed_inbound"] == 12

    partial = store.receive_purchase_order(
        "tenant-a", "PO-1", [{"sku_id": "SKU-1", "quantity": 5}]
    )
    assert partial["status"] == "partially_received"
    after_partial = store.inventory_position("tenant-a", "WH-1", "SKU-1")
    assert after_partial["on_hand"] == 15
    assert after_partial["confirmed_inbound"] == 7
    assert after_partial["inventory_position"] == 20

    completed = store.receive_purchase_order(
        "tenant-a", "PO-1", [{"sku_id": "SKU-1", "quantity": 7}]
    )
    assert completed["status"] == "received"
    after = store.inventory_position("tenant-a", "WH-1", "SKU-1")
    assert after["on_hand"] == 22
    assert after["confirmed_inbound"] == 0
    assert after["inventory_position"] == 20


def test_purchase_order_rejects_over_receipt_and_rolls_back(store: OperationalStore) -> None:
    create_warehouse(store)
    store.create_purchase_order(
        "tenant-a", order_id="PO-2", supplier_id="SUP-1", warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 4}],
    )
    with pytest.raises(ValueError, match="exceeds ordered"):
        store.receive_purchase_order(
            "tenant-a", "PO-2", [{"sku_id": "SKU-1", "quantity": 5}]
        )
    assert store.get_purchase_order("tenant-a", "PO-2")["lines"][0]["received"] == 0


def test_purchase_orders_are_not_visible_across_tenants(store: OperationalStore) -> None:
    create_warehouse(store)
    store.create_purchase_order(
        "tenant-a", order_id="PO-3", supplier_id="SUP-1", warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 4}],
    )
    with pytest.raises(KeyError, match="purchase order"):
        store.get_purchase_order("tenant-b", "PO-3")


def test_demand_history_is_idempotent_and_chronological(store: OperationalStore) -> None:
    create_warehouse(store)
    first = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_demand("tenant-a", "WH-1", "SKU-1", 2, observed_at=first)
    store.record_demand("tenant-a", "WH-1", "SKU-1", 5, observed_at=first)
    store.record_demand("tenant-a", "WH-1", "SKU-1", 7, observed_at=first + timedelta(days=1))

    history = store.demand_history("tenant-a", "WH-1", "SKU-1")
    assert [item["demand"] for item in history] == [5, 7]
    assert len(history) == 2
    assert store.demand_history("tenant-b", "WH-1", "SKU-1") == []


def test_model_health_alerts_and_retraining_request_is_deduplicated(
    store: OperationalStore,
) -> None:
    create_warehouse(store)
    store.set_model_baseline(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", baseline_mae=1, sample_count=30,
    )
    origin = datetime(2026, 2, 1, tzinfo=UTC)
    for index in range(10):
        store.record_outcome(
            "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
            model_id="model-a", model_version="v1",
            forecast_origin=origin + timedelta(days=index),
            target_at=origin + timedelta(days=index + 1),
            predicted=20, actual=10,
        )
    lifecycle = ModelLifecycle(store)
    health = lifecycle.assess(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1",
        window=10, min_samples=10, degradation_ratio=1.5,
    )
    assert health["alert"] is True
    assert health["rolling_mae"] == 10
    first = health["retraining_request"]
    second = store.queue_retraining(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", reason="duplicate-alert",
    )
    assert first["request_id"] == second["request_id"]
    assert second["status"] == "queued"


def test_model_selection_uses_recent_out_of_sample_mae(store: OperationalStore) -> None:
    create_warehouse(store)
    origin = datetime(2026, 3, 1, tzinfo=UTC)
    for model_id, prediction in (("better", 10.5), ("worse", 30.0)):
        for index in range(6):
            store.record_outcome(
                "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
                model_id=model_id, model_version="1",
                forecast_origin=origin + timedelta(days=index),
                target_at=origin + timedelta(days=index + 1),
                predicted=prediction, actual=10,
            )
    selected = ModelLifecycle(store).select(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1", min_samples=5
    )
    assert selected["selected"]["model_id"] == "better"
    assert selected["used_fallback"] is False


def test_model_selection_falls_back_without_enough_evidence(store: OperationalStore) -> None:
    selected = ModelLifecycle(store).select(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        min_samples=5, fallback_model_id="seasonal-naive",
    )
    assert selected["used_fallback"] is True
    assert selected["selected"]["model_id"] == "seasonal-naive"


def test_retraining_worker_registers_new_version_and_baseline(store: OperationalStore) -> None:
    create_warehouse(store)
    now = datetime(2026, 4, 1, tzinfo=UTC)
    for index in range(30):
        store.record_demand(
            "tenant-a", "WH-1", "SKU-1", float(index % 5),
            observed_at=now + timedelta(days=index),
        )
    request = store.queue_retraining(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", reason="drift",
    )
    lifecycle = ModelLifecycle(store)
    unavailable = lifecycle.process_retraining_request("tenant-a", request["request_id"])
    assert unavailable["status"] == "trainer_unavailable"

    lifecycle.register_trainer(
        "model-a",
        lambda _request, history: TrainingResult("v2", 0.75, len(history)),
    )
    result = lifecycle.process_retraining_request("tenant-a", request["request_id"])
    assert result["status"] == "completed"
    assert result["new_model_version"] == "v2"
    health = store.model_health(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v2", min_samples=1,
    )
    assert health["status"] == "insufficient_samples"
    assert health["baseline_mae"] == 0.75


def test_retraining_request_state_transitions_are_guarded(store: OperationalStore) -> None:
    create_warehouse(store)
    request = store.queue_retraining(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", reason="drift",
    )
    claimed = store.claim_retraining("tenant-a", request["request_id"])
    assert claimed["status"] == "claimed"
    with pytest.raises(ValueError, match="already claimed"):
        store.claim_retraining("tenant-a", request["request_id"])
    finished = store.finish_retraining("tenant-a", request["request_id"], success=False)
    assert finished["status"] == "failed"


def test_schedules_claim_complete_and_retry(store: OperationalStore) -> None:
    create_warehouse(store)
    start = datetime(2026, 5, 1, tzinfo=UTC)
    job = store.create_schedule(
        "tenant-a", job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1"},
        interval_seconds=300, first_run_at=start,
    )
    claimed = store.claim_due_schedules("tenant-a", now=start, lease_seconds=30)
    assert [item["job_id"] for item in claimed] == [job["job_id"]]
    assert store.claim_due_schedules("tenant-a", now=start) == []
    released = store.release_schedule("tenant-a", job["job_id"], retry_after_seconds=60)
    assert released["lease_until"] is None
    retry_time = datetime.fromisoformat(released["next_run_at"])
    claimed_again = store.claim_due_schedules("tenant-a", now=retry_time)
    assert len(claimed_again) == 1
    completed = store.complete_schedule("tenant-a", job["job_id"], completed_at=retry_time)
    assert completed["last_run_at"] == retry_time.isoformat()
    assert store.claim_due_schedules("tenant-a", now=retry_time) == []


def test_schedule_rejects_short_intervals_and_unknown_types(store: OperationalStore) -> None:
    with pytest.raises(ValueError, match="at least 60"):
        store.create_schedule(
            "tenant-a", job_type="forecast_refresh", payload={}, interval_seconds=1
        )
    with pytest.raises(ValueError, match="unsupported"):
        store.create_schedule("tenant-a", job_type="unknown", payload={}, interval_seconds=60)


def test_invalid_inventory_and_demand_are_rejected(store: OperationalStore) -> None:
    create_warehouse(store)
    with pytest.raises(ValueError, match="reserved cannot exceed"):
        store.record_inventory("tenant-a", "WH-1", "SKU-1", 2, reserved=3)
    with pytest.raises(ValueError, match="finite and non-negative"):
        store.record_demand(
            "tenant-a", "WH-1", "SKU-1", float("nan"),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="timezone"):
        store.record_demand(
            "tenant-a", "WH-1", "SKU-1", 1,
            observed_at=datetime(2026, 1, 1),
        )


def test_retraining_can_be_queued_again_after_a_completed_cycle(store: OperationalStore) -> None:
    create_warehouse(store)
    first = store.queue_retraining(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", reason="first-drift",
    )
    store.claim_retraining("tenant-a", first["request_id"])
    store.finish_retraining("tenant-a", first["request_id"], success=True)

    second = store.queue_retraining(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", reason="second-drift",
    )
    store.claim_retraining("tenant-a", second["request_id"])
    finished = store.finish_retraining("tenant-a", second["request_id"], success=True)
    assert finished["status"] == "completed"
    assert len(store.list_retraining_requests("tenant-a")) == 2


def test_purchase_order_is_visible_in_inventory_position_without_a_stock_snapshot(
    store: OperationalStore,
) -> None:
    create_warehouse(store)
    store.create_purchase_order(
        "tenant-a", order_id="PO-INBOUND", supplier_id="SUP-1", warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-NEW", "quantity": 9}],
    )
    position = store.inventory_position("tenant-a", "WH-1", "SKU-NEW")
    assert position["on_hand"] == 0
    assert position["confirmed_inbound"] == 9
    assert position["inventory_position"] == 9
    assert position["as_of"] is None


def test_forecast_outcome_ingestion_is_idempotent_but_rejects_conflicts(
    store: OperationalStore,
) -> None:
    create_warehouse(store)
    origin = datetime(2026, 7, 1, tzinfo=UTC)
    arguments = {
        "warehouse_id": "WH-1", "sku_id": "SKU-1", "model_id": "model-a",
        "model_version": "v1", "forecast_origin": origin,
        "target_at": origin + timedelta(days=1), "predicted": 12, "actual": 10,
    }
    first = store.record_outcome("tenant-a", **arguments)
    retry = store.record_outcome("tenant-a", **arguments)
    assert first["outcome_id"] == retry["outcome_id"]
    with pytest.raises(ValueError, match="already bound"):
        store.record_outcome("tenant-a", **{**arguments, "actual": 11})


def test_policy_feedback_ranks_versions_by_realized_cost(store: OperationalStore) -> None:
    create_warehouse(store)
    for index in range(5):
        for policy_id, ordered in (("lean", 10), ("excess-stock", 20)):
            store.record_policy_outcome(
                "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
                policy_id=policy_id, decision_key=f"origin-{index}",
                inventory_position=0, ordered_quantity=ordered,
                realized_demand=8, holding_cost_per_unit=1,
                shortage_cost_per_unit=10,
            )
    ranked = store.rank_policies(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1", min_samples=5
    )
    assert [item["policy_id"] for item in ranked] == ["lean", "excess-stock"]
    assert ranked[0]["mean_cost"] == 2
    assert ranked[1]["mean_cost"] == 12
    assert ranked[0]["fill_rate"] == 1
    assert ranked[0]["cycle_service_level"] == 1


def test_policy_outcomes_are_idempotent_and_conflicts_are_rejected(
    store: OperationalStore,
) -> None:
    create_warehouse(store)
    args = {
        "warehouse_id": "WH-1", "sku_id": "SKU-1", "policy_id": "policy-v1",
        "decision_key": "decision-1", "inventory_position": 0,
        "ordered_quantity": 4, "realized_demand": 6,
        "holding_cost_per_unit": 1, "shortage_cost_per_unit": 5,
    }
    first = store.record_policy_outcome("tenant-a", **args)
    retry = store.record_policy_outcome("tenant-a", **args)
    assert first["outcome_id"] == retry["outcome_id"]
    assert first["shortage_units"] == 2
    assert first["total_cost"] == 10
    with pytest.raises(ValueError, match="already bound"):
        store.record_policy_outcome(
            "tenant-a", **{**args, "ordered_quantity": 5}
        )


def test_policy_ranking_falls_back_without_minimum_evidence(store: OperationalStore) -> None:
    assert store.rank_policies(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1", min_samples=3
    ) == []


def test_model_health_requires_sufficient_baseline_evidence(store: OperationalStore) -> None:
    create_warehouse(store)
    store.set_model_baseline(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", baseline_mae=1, sample_count=2,
    )
    health = store.model_health(
        "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
        model_id="model-a", model_version="v1", min_samples=5,
    )
    assert health["status"] == "baseline_insufficient"
    assert health["alert"] is False
