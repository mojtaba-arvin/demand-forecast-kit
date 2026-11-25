# Operational worker registry setup

The worker keeps model and policy registries opt-in so existing deployments
retain their current behavior. Applications that enable them own the durable
paths, reviewed model loaders, and explicit activation decisions.

```python
from demand_forecast_kit.model_registry import ModelArtifactRegistry
from demand_forecast_kit.operations import OperationalStore
from demand_forecast_kit.operations_worker import OperationalWorker
from demand_forecast_kit.policy_registry import ReplenishmentPolicyRegistry
from demand_forecast_kit.run_service import RunService

service = RunService.from_environment()
store = OperationalStore(service.state_dir / "operations.sqlite")
models = ModelArtifactRegistry(
    service.state_dir / "models.sqlite",
    service.state_dir / "model-artifacts",
)
policies = ReplenishmentPolicyRegistry(service.state_dir / "policies.sqlite")

worker = OperationalWorker(
    service,
    store,
    model_artifact_registry=models,
    policy_registry=policies,
)
worker.register_artifact_loader(
    "application/vnd.example.forecast-model",
    load_reviewed_model,  # application-owned: bytes + ModelArtifactRecord -> ForecastAdapter
)
```

The application must implement `load_reviewed_model` for its artifact format
and return a `ForecastAdapter` whose `model_id` and `model_version` exactly
match the record. Artifact metadata is never used to import executable code.
The registry verifies the artifact digest before calling the loader.

When model registry mode is enabled, a non-baseline model is served only if the
model lifecycle selected the exact active artifact version and a loader exists.
Otherwise the worker records the reason and uses seasonal-naive. No training
callback activates a model.

When policy registry mode is enabled, each replenishment schedule must include
the tenant's active `policy_id`. Registered costs and pack size override
schedule-supplied values. A missing active policy fails the job for retry;
there is no silent substitution. Activate and roll back policy versions
explicitly with compare-and-swap.

Both registries use local SQLite and are single-host components. Back up the
model registry database together with its artifact directory. Do not share
these SQLite files across multiple worker hosts.
