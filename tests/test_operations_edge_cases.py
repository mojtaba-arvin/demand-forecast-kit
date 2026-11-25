import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from demand_forecast_kit.operations import OperationalStore


def _warehouse(store: OperationalStore) -> None:
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")


def test_legacy_inventory_schema_is_migrated_with_backorders(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE inventory_snapshots (
                tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, sku_id TEXT NOT NULL,
                quantity REAL NOT NULL, reserved REAL NOT NULL, as_of TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (tenant_id, warehouse_id, sku_id, as_of)
            )"""
        )
    OperationalStore(database)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(inventory_snapshots)")}
    assert "backorders" in columns


def test_legacy_retraining_schema_is_migrated_with_claim_tokens(tmp_path) -> None:
    database = tmp_path / "legacy-retraining.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE retraining_requests (
                request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                warehouse_id TEXT NOT NULL, sku_id TEXT NOT NULL,
                model_id TEXT NOT NULL, model_version TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','claimed','completed','failed')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
    store = OperationalStore(database)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(retraining_requests)")}
    assert "claim_token" in columns

    _warehouse(store)
    request = store.queue_retraining(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        reason="migration-test",
    )
    claimed = store.claim_retraining("tenant-a", request["request_id"])
    assert claimed["claim_token"]



def test_legacy_scheduler_schema_is_migrated_with_lease_tokens(tmp_path) -> None:
    database = tmp_path / "legacy-scheduler.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE scheduled_jobs (
                tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
                next_run_at TEXT NOT NULL, last_run_at TEXT, lease_until TEXT,
                enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, job_id)
            )"""
        )
    store = OperationalStore(database)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(scheduled_jobs)")}
    assert "lease_token" in columns

    job = store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={},
        interval_seconds=60,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    claimed = store.claim_due_schedules("tenant-a")
    assert claimed[0]["job_id"] == job["job_id"]
    assert claimed[0]["lease_token"]



def test_tenant_warehouse_and_inventory_validation_edges(tmp_path) -> None:
    store = OperationalStore(tmp_path / "validation.sqlite")
    with pytest.raises(ValueError, match="tenant_id"):
        store.list_warehouses(" ")
    with pytest.raises(ValueError, match="ISO-8601"):
        store.record_demand("tenant-a", "WH-1", "SKU-1", 1, observed_at="not-a-date")
    with pytest.raises(ValueError, match="timezone"):
        store.record_demand("tenant-a", "WH-1", "SKU-1", 1, observed_at="2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="warehouse_id"):
        store.create_warehouse("tenant-a", "", "Main", "main")
    with pytest.raises(KeyError, match="warehouse"):
        store.get_warehouse("tenant-a", "missing")

    _warehouse(store)
    with pytest.raises(ValueError, match="sku_id"):
        store.record_inventory("tenant-a", "WH-1", " ", 1)
    with pytest.raises(ValueError, match="finite and non-negative"):
        store.record_inventory("tenant-a", "WH-1", "SKU-1", -1)
    with pytest.raises(KeyError, match="warehouse"):
        store.record_inventory("tenant-a", "missing", "SKU-1", 1)
    with pytest.raises(ValueError, match="sku_id"):
        store.record_demand(
            "tenant-a", "WH-1", " ", 1, observed_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.record_demand(
            "tenant-a",
            "missing",
            "SKU-1",
            1,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="limit"):
        store.demand_history("tenant-a", "WH-1", "SKU-1", limit=0)


def test_purchase_order_validation_and_erp_sync_state_edges(tmp_path) -> None:
    store = OperationalStore(tmp_path / "purchase.sqlite")
    _warehouse(store)
    store.create_warehouse("tenant-a", "WH-2", "Second", "second")
    with pytest.raises(ValueError, match="at least one line"):
        store.create_purchase_order(
            "tenant-a",
            order_id="PO-EMPTY",
            supplier_id="SUP-1",
            warehouse_id="WH-1",
            lines=[],
        )
    with pytest.raises(ValueError, match="unique"):
        store.create_purchase_order(
            "tenant-a",
            order_id="PO-DUP",
            supplier_id="SUP-1",
            warehouse_id="WH-1",
            lines=[{"sku_id": "SKU-1", "quantity": 1}, {"sku_id": "SKU-1", "quantity": 2}],
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.create_purchase_order(
            "tenant-a",
            order_id="PO-MISSING",
            supplier_id="SUP-1",
            warehouse_id="missing",
            lines=[{"sku_id": "SKU-1", "quantity": 1}],
        )
    with pytest.raises(KeyError, match="purchase order"):
        store.get_purchase_order("tenant-a", "missing")

    with pytest.raises(ValueError, match="at least one line"):
        store.sync_purchase_order(
            "tenant-a",
            order_id="ERP-EMPTY",
            supplier_id="SUP-1",
            warehouse_id="WH-1",
            lines=[],
        )
    with pytest.raises(ValueError, match="received quantity"):
        store.sync_purchase_order(
            "tenant-a",
            order_id="ERP-OVER",
            supplier_id="SUP-1",
            warehouse_id="WH-1",
            lines=[{"sku_id": "SKU-1", "quantity": 1, "received_quantity": 2}],
        )
    with pytest.raises(ValueError, match="unique"):
        store.sync_purchase_order(
            "tenant-a",
            order_id="ERP-DUP",
            supplier_id="SUP-1",
            warehouse_id="WH-1",
            lines=[
                {"sku_id": "SKU-1", "quantity": 1},
                {"sku_id": "SKU-1", "quantity": 2},
            ],
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.sync_purchase_order(
            "tenant-a",
            order_id="ERP-MISSING",
            supplier_id="SUP-1",
            warehouse_id="missing",
            lines=[{"sku_id": "SKU-1", "quantity": 1}],
        )

    submitted = store.sync_purchase_order(
        "tenant-a",
        order_id="ERP-SUBMITTED",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-2", "quantity": 10, "received_quantity": 0}],
    )
    assert submitted["status"] == "submitted"
    first = store.sync_purchase_order(
        "tenant-a",
        order_id="ERP-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 4}],
    )
    assert first["status"] == "partially_received"
    with pytest.raises(ValueError, match="cannot move"):
        store.sync_purchase_order(
            "tenant-a",
            order_id="ERP-1",
            supplier_id="SUP-1",
            warehouse_id="WH-1",
            lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 3}],
        )
    with pytest.raises(ValueError, match="move between warehouses"):
        store.sync_purchase_order(
            "tenant-a",
            order_id="ERP-1",
            supplier_id="SUP-1",
            warehouse_id="WH-2",
            lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 4}],
        )
    completed = store.sync_purchase_order(
        "tenant-a",
        order_id="ERP-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 10, "received_quantity": 10}],
    )
    assert completed["status"] == "received"


def test_purchase_receipt_validation_edges(tmp_path) -> None:
    store = OperationalStore(tmp_path / "receipts.sqlite")
    _warehouse(store)
    with pytest.raises(KeyError, match="purchase order"):
        store.receive_purchase_order("tenant-a", "missing", [{"sku_id": "SKU-1", "quantity": 1}])
    with pytest.raises(ValueError, match="at least one"):
        store.receive_purchase_order("tenant-a", "missing", [])
    store.create_purchase_order(
        "tenant-a",
        order_id="PO-1",
        supplier_id="SUP-1",
        warehouse_id="WH-1",
        lines=[{"sku_id": "SKU-1", "quantity": 2}],
    )
    with pytest.raises(ValueError, match="unknown"):
        store.receive_purchase_order("tenant-a", "PO-1", [{"sku_id": "unknown", "quantity": 1}])
    with pytest.raises(ValueError, match="unique"):
        store.receive_purchase_order(
            "tenant-a",
            "PO-1",
            [{"sku_id": "SKU-1", "quantity": 1}, {"sku_id": "SKU-1", "quantity": 1}],
        )
    store.receive_purchase_order("tenant-a", "PO-1", [{"sku_id": "SKU-1", "quantity": 2}])
    with pytest.raises(ValueError, match="only submitted"):
        store.receive_purchase_order("tenant-a", "PO-1", [{"sku_id": "SKU-1", "quantity": 1}])


def test_monitoring_and_retraining_validation_edges(tmp_path) -> None:
    store = OperationalStore(tmp_path / "monitor.sqlite")
    _warehouse(store)
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="must not be blank"):
        store.record_outcome(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id=" ",
            model_version="v1",
            forecast_origin=origin,
            target_at=origin + timedelta(days=1),
            predicted=1,
            actual=1,
        )
    with pytest.raises(ValueError, match="later than"):
        store.record_outcome(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            forecast_origin=origin,
            target_at=origin,
            predicted=1,
            actual=1,
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.record_outcome(
            "tenant-a",
            warehouse_id="missing",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            forecast_origin=origin,
            target_at=origin + timedelta(days=1),
            predicted=1,
            actual=1,
        )
    with pytest.raises(ValueError, match="sample_count"):
        store.set_model_baseline(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            baseline_mae=1,
            sample_count=0,
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.set_model_baseline(
            "tenant-a",
            warehouse_id="missing",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            baseline_mae=1,
            sample_count=5,
        )
    assert (
        store.model_health(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
        )["status"]
        == "baseline_missing"
    )
    with pytest.raises(ValueError, match="window"):
        store.model_health(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            window=0,
        )
    with pytest.raises(ValueError, match="degradation_ratio"):
        store.model_health(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            degradation_ratio=0,
        )
    with pytest.raises(ValueError, match="reason"):
        store.queue_retraining(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            reason=" ",
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.queue_retraining(
            "tenant-a",
            warehouse_id="missing",
            sku_id="SKU-1",
            model_id="m",
            model_version="v1",
            reason="drift",
        )
    with pytest.raises(ValueError, match="limit"):
        store.list_retraining_requests("tenant-a", limit=0)
    with pytest.raises(ValueError, match="already claimed"):
        store.claim_retraining("tenant-a", "missing")
    with pytest.raises(ValueError, match="stale or no longer owned"):
        store.finish_retraining(
            "tenant-a", "missing", success=True, claim_token="not-a-valid-claim"
        )


def test_policy_feedback_validation_edges(tmp_path) -> None:
    store = OperationalStore(tmp_path / "policy.sqlite")
    _warehouse(store)
    with pytest.raises(ValueError, match="finite"):
        store.record_policy_outcome(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            policy_id="p",
            decision_key="d",
            inventory_position=float("nan"),
            ordered_quantity=1,
            realized_demand=1,
            holding_cost_per_unit=1,
            shortage_cost_per_unit=1,
        )
    with pytest.raises(KeyError, match="warehouse"):
        store.record_policy_outcome(
            "tenant-a",
            warehouse_id="missing",
            sku_id="SKU-1",
            policy_id="p",
            decision_key="d",
            inventory_position=0,
            ordered_quantity=1,
            realized_demand=1,
            holding_cost_per_unit=1,
            shortage_cost_per_unit=1,
        )
    with pytest.raises(ValueError, match="min_samples"):
        store.rank_policies("tenant-a", warehouse_id="WH-1", sku_id="SKU-1", min_samples=0)
    with pytest.raises(ValueError, match="window"):
        store.rank_policies("tenant-a", warehouse_id="WH-1", sku_id="SKU-1", window=0)
    with pytest.raises(ValueError, match="min_samples"):
        store.rank_models("tenant-a", warehouse_id="WH-1", sku_id="SKU-1", min_samples=0)
    with pytest.raises(ValueError, match="window"):
        store.rank_models("tenant-a", warehouse_id="WH-1", sku_id="SKU-1", window=0)


def test_scheduler_validation_edges(tmp_path) -> None:
    store = OperationalStore(tmp_path / "schedule.sqlite")
    with pytest.raises(ValueError, match="finite JSON"):
        store.create_schedule(
            "tenant-a",
            job_type="forecast_refresh",
            payload={"bad": float("nan")},
            interval_seconds=60,
        )
    with pytest.raises(ValueError, match="timezone"):
        store.create_schedule(
            "tenant-a",
            job_type="forecast_refresh",
            payload={},
            interval_seconds=60,
            first_run_at="2026-01-01T00:00:00",
        )
    with pytest.raises(ValueError, match="invalid scheduler"):
        store.claim_due_schedules(
            "tenant-a",
            now=datetime(2026, 1, 1),
            lease_seconds=0,
        )
    with pytest.raises(ValueError, match="timezone"):
        store.complete_schedule(
            "tenant-a",
            "missing",
            lease_token="invalid",
            completed_at=datetime(2026, 1, 1),
        )
    with pytest.raises(KeyError, match="scheduled job"):
        store.complete_schedule("tenant-a", "missing", lease_token="invalid")
    job = store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={},
        interval_seconds=60,
    )
    with pytest.raises(ValueError, match="active lease"):
        store.complete_schedule("tenant-a", job["job_id"], lease_token="invalid")
    with pytest.raises(ValueError, match="positive integer"):
        store.release_schedule(
            "tenant-a", job["job_id"], lease_token="invalid", retry_after_seconds=0
        )
    with pytest.raises(ValueError, match="active lease"):
        store.release_schedule("tenant-a", job["job_id"], lease_token="invalid")
