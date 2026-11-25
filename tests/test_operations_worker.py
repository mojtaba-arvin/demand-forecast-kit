from datetime import UTC, datetime, timedelta

from demand_forecast_kit.operations import OperationalStore
from demand_forecast_kit.operations_worker import OperationalWorker
from demand_forecast_kit.run_service import RunService


def test_worker_executes_scheduled_forecast_and_persists_run(tmp_path) -> None:
    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(21):
        store.record_demand(
            "tenant-a",
            "WH-1",
            "SKU-1",
            float(index % 7),
            observed_at=start + timedelta(days=index),
        )
    store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "horizon": 3},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    report = OperationalWorker(service, store).run_once("tenant-a")

    assert report["claimed"] == 1
    assert report["failed"] == []
    assert report["completed"][0]["result"]["forecast"]["horizon"] == 3
    run_id = report["completed"][0]["result"]["run"]["run_id"]
    assert service.registry.get_run(run_id).status == "completed"


def test_worker_executes_replenishment_and_records_immutable_decision(tmp_path) -> None:
    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.record_inventory("tenant-a", "WH-1", "SKU-1", 10, reserved=2)
    store.create_schedule(
        "tenant-a",
        job_type="replenishment_review",
        payload={
            "warehouse_id": "WH-1",
            "sku_id": "SKU-1",
            "lead_time_demand_quantiles": {"0.1": 10, "0.5": 20, "0.9": 40},
            "underage_cost": 9,
            "overage_cost": 1,
            "pack_size": 6,
        },
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    report = OperationalWorker(service, store).run_once("tenant-a")

    assert report["failed"] == []
    result = report["completed"][0]["result"]
    assert result["decision"]["decision_key"]
    run = service.registry.get_run(result["run"]["run_id"])
    decisions = service.registry.list_inventory_decisions(run.run_id)
    assert len(decisions) == 1
    assert decisions[0].decision["quantity"] == 36


def test_worker_releases_failed_job_for_retry(tmp_path) -> None:
    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    job = store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "missing"},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    report = OperationalWorker(service, store).run_once("tenant-a")

    assert report["claimed"] == 1
    assert len(report["failed"]) == 1
    schedule = store.list_schedules("tenant-a")[0]
    assert schedule["job_id"] == job["job_id"]
    assert schedule["lease_until"] is None


def test_worker_runs_policy_review_from_realized_outcomes(tmp_path) -> None:
    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    for index in range(5):
        store.record_policy_outcome(
            "tenant-a",
            warehouse_id="WH-1",
            sku_id="SKU-1",
            policy_id="validated-policy",
            decision_key=f"decision-{index}",
            inventory_position=0,
            ordered_quantity=10,
            realized_demand=8,
            holding_cost_per_unit=1,
            shortage_cost_per_unit=10,
        )
    store.create_schedule(
        "tenant-a",
        job_type="policy_review",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "min_samples": 5},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    report = OperationalWorker(service, store).run_once("tenant-a")
    assert report["failed"] == []
    assert report["completed"][0]["result"]["selected"]["policy_id"] == "validated-policy"


def test_worker_runs_registered_model_retraining_plugin(tmp_path) -> None:
    from demand_forecast_kit.lifecycle import TrainingResult

    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    start = datetime(2026, 2, 1, tzinfo=UTC)
    for index in range(20):
        store.record_demand(
            "tenant-a",
            "WH-1",
            "SKU-1",
            float(index % 4),
            observed_at=start + timedelta(days=index),
        )
    store.queue_retraining(
        "tenant-a",
        warehouse_id="WH-1",
        sku_id="SKU-1",
        model_id="model-a",
        model_version="v1",
        reason="drift",
    )
    worker = OperationalWorker(service, store)
    worker.register_trainer(
        "model-a", lambda _request, history: TrainingResult("v2", 0.5, len(history))
    )

    report = worker.run_once("tenant-a")

    assert report["retraining"][0]["status"] == "completed"
    assert report["retraining"][0]["new_model_version"] == "v2"


def test_worker_automatically_routes_to_best_registered_model(tmp_path) -> None:
    from demand_forecast_kit.contracts import QuantileForecast

    class CandidateAdapter:
        model_id = "candidate-model"
        model_version = "v1"

        def predict(
            self, series_id, history, *, horizon, quantile_levels, seed
        ) -> QuantileForecast:
            values = tuple(5.0 for _ in range(horizon))
            return QuantileForecast(
                series_id=series_id,
                quantiles={float(level): values for level in quantile_levels},
            )

    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    start = datetime(2026, 3, 1, tzinfo=UTC)
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
            model_id="candidate-model",
            model_version="v1",
            forecast_origin=start + timedelta(days=index),
            target_at=start + timedelta(days=index + 1),
            predicted=10.5,
            actual=10,
        )
    store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "horizon": 2},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    worker = OperationalWorker(service, store)
    worker.register_adapter(CandidateAdapter())

    report = worker.run_once("tenant-a")

    forecast = report["completed"][0]["result"]["forecast"]
    assert forecast["model_id"] == "candidate-model"
    assert forecast["model_selection"]["used_fallback"] is False


def test_worker_routes_to_exact_selected_model_version_when_multiple_are_registered(
    tmp_path,
) -> None:
    from demand_forecast_kit.contracts import QuantileForecast

    class VersionedAdapter:
        model_id = "shared-model"

        def __init__(self, model_version: str, value: float) -> None:
            self.model_version = model_version
            self.value = value

        def predict(
            self, series_id, history, *, horizon, quantile_levels, seed
        ) -> QuantileForecast:
            values = tuple(self.value for _ in range(horizon))
            return QuantileForecast(
                series_id=series_id,
                quantiles={float(level): values for level in quantile_levels},
            )

    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    for index in range(21):
        store.record_demand(
            "tenant-a",
            "WH-1",
            "SKU-1",
            float(index % 7),
            observed_at=start + timedelta(days=index),
        )
    for index in range(5):
        for version, predicted in (("v1", 10.0), ("v2", 15.0)):
            store.record_outcome(
                "tenant-a",
                warehouse_id="WH-1",
                sku_id="SKU-1",
                model_id="shared-model",
                model_version=version,
                forecast_origin=start + timedelta(days=index),
                target_at=start + timedelta(days=index + 1),
                predicted=predicted,
                actual=10.0,
            )
    store.create_schedule(
        "tenant-a",
        job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "horizon": 2},
        interval_seconds=300,
        first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    worker = OperationalWorker(service, store)
    worker.register_adapter(VersionedAdapter("v1", 1.0))
    worker.register_adapter(VersionedAdapter("v2", 2.0))

    report = worker.run_once("tenant-a")

    forecast = report["completed"][0]["result"]["forecast"]
    assert forecast["model_id"] == "shared-model"
    assert forecast["model_version"] == "v1"
    assert forecast["quantiles"]["0.5"] == [1.0, 1.0]


def test_worker_loads_only_explicitly_activated_model_artifact(tmp_path) -> None:
    from demand_forecast_kit.contracts import QuantileForecast
    from demand_forecast_kit.model_registry import ModelArtifactRegistry

    class LoadedAdapter:
        model_id = "artifact-model"
        model_version = "v1"

        def predict(
            self, series_id, history, *, horizon, quantile_levels, seed
        ) -> QuantileForecast:
            values = tuple(42.0 for _ in range(horizon))
            return QuantileForecast(
                series_id=series_id,
                quantiles={float(level): values for level in quantile_levels},
            )

    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    start = datetime(2026, 5, 1, tzinfo=UTC)
    for index in range(21):
        store.record_demand(
            "tenant-a", "WH-1", "SKU-1", float(index % 7),
            observed_at=start + timedelta(days=index),
        )
    for index in range(5):
        store.record_outcome(
            "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
            model_id="artifact-model", model_version="v1",
            forecast_origin=start + timedelta(days=index),
            target_at=start + timedelta(days=index + 1), predicted=10.5, actual=10.0,
        )
    store.create_schedule(
        "tenant-a", job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "horizon": 2},
        interval_seconds=300, first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    artifacts = ModelArtifactRegistry(
        service.state_dir / "models.sqlite", service.state_dir / "model-artifacts"
    )
    artifacts.register_artifact(
        "artifact-model", "v1", b"reviewed-model-bytes",
        evaluation_report=b'{"wql":0.1}', media_type="application/vnd.test.forecast",
        validation_mae=0.5, validation_sample_count=100,
    )
    artifacts.activate("artifact-model", "v1", expected_active_version=None)
    worker = OperationalWorker(service, store, model_artifact_registry=artifacts)
    loads: list[bytes] = []

    def loader(payload, record):
        assert record.model_id == "artifact-model"
        loads.append(payload)
        return LoadedAdapter()

    worker.register_artifact_loader("application/vnd.test.forecast", loader)
    report = worker.run_once("tenant-a")

    forecast = report["completed"][0]["result"]["forecast"]
    assert report["failed"] == []
    assert forecast["model_id"] == "artifact-model"
    assert forecast["model_version"] == "v1"
    assert forecast["quantiles"]["0.5"] == [42.0, 42.0]
    assert forecast["model_selection"]["active_artifact_version"] == "v1"
    assert loads == [b"reviewed-model-bytes"]


def test_worker_falls_back_when_selected_artifact_is_not_active(tmp_path) -> None:
    from demand_forecast_kit.contracts import QuantileForecast
    from demand_forecast_kit.model_registry import ModelArtifactRegistry

    class CandidateAdapter:
        model_id = "inactive-model"
        model_version = "v1"

        def predict(
            self, series_id, history, *, horizon, quantile_levels, seed
        ) -> QuantileForecast:
            values = tuple(99.0 for _ in range(horizon))
            return QuantileForecast(
                series_id=series_id,
                quantiles={float(level): values for level in quantile_levels},
            )

    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    start = datetime(2026, 6, 1, tzinfo=UTC)
    for index in range(21):
        store.record_demand(
            "tenant-a", "WH-1", "SKU-1", float(index % 7),
            observed_at=start + timedelta(days=index),
        )
    for index in range(5):
        store.record_outcome(
            "tenant-a", warehouse_id="WH-1", sku_id="SKU-1",
            model_id="inactive-model", model_version="v1",
            forecast_origin=start + timedelta(days=index),
            target_at=start + timedelta(days=index + 1), predicted=10.5, actual=10.0,
        )
    store.create_schedule(
        "tenant-a", job_type="forecast_refresh",
        payload={"warehouse_id": "WH-1", "sku_id": "SKU-1", "horizon": 2},
        interval_seconds=300, first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    artifacts = ModelArtifactRegistry(
        service.state_dir / "models.sqlite", service.state_dir / "model-artifacts"
    )
    artifacts.register_artifact(
        "inactive-model", "v1", b"candidate-bytes",
        evaluation_report=b'{"wql":0.1}', media_type="application/vnd.test.forecast",
        validation_mae=0.5, validation_sample_count=100,
    )
    worker = OperationalWorker(service, store, model_artifact_registry=artifacts)
    worker.register_adapter(CandidateAdapter())
    worker.register_artifact_loader(
        "application/vnd.test.forecast", lambda _payload, _record: CandidateAdapter()
    )

    report = worker.run_once("tenant-a")

    forecast = report["completed"][0]["result"]["forecast"]
    assert report["failed"] == []
    assert forecast["model_id"] == "seasonal-naive"
    assert forecast["model_selection"]["adapter_fallback_reason"] == "no_active_model_artifact"


def test_worker_uses_active_versioned_policy_instead_of_schedule_costs(tmp_path) -> None:
    from demand_forecast_kit.policy_registry import ReplenishmentPolicyRegistry

    service = RunService(tmp_path / "state")
    store = OperationalStore(service.state_dir / "operations.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.record_inventory("tenant-a", "WH-1", "SKU-1", 10, reserved=2)
    policies = ReplenishmentPolicyRegistry(service.state_dir / "policies.sqlite")
    policies.register_policy(
        "tenant-a", "service-level-90", "v2",
        {"policy_type": "newsvendor", "underage_cost": 9, "overage_cost": 1, "pack_size": 6},
    )
    policies.activate("tenant-a", "service-level-90", "v2", expected_active_version=None)
    store.create_schedule(
        "tenant-a", job_type="replenishment_review",
        payload={
            "warehouse_id": "WH-1", "sku_id": "SKU-1", "policy_id": "service-level-90",
            "lead_time_demand_quantiles": {"0.1": 10, "0.5": 20, "0.9": 40},
            "underage_cost": 1, "overage_cost": 99, "pack_size": 1,
        },
        interval_seconds=300, first_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    report = OperationalWorker(service, store, policy_registry=policies).run_once("tenant-a")

    assert report["failed"] == []
    decision = report["completed"][0]["result"]["decision"]
    assert decision["quantity"] == 36
    assert decision["policy"] == "service-level-90"
    assert decision["policy_version"] == "v2"
    assert decision["policy_definition_sha256"]
    run = service.registry.get_run(report["completed"][0]["result"]["run"]["run_id"])
    assert run.model_id == "replenishment-policy:service-level-90"
    assert run.model_version == "v2"
