"""Single-machine worker for durable forecast, replenishment, and monitoring schedules."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from typing import Any

from demand_forecast_kit.decisions import newsvendor_order
from demand_forecast_kit.lifecycle import ModelLifecycle
from demand_forecast_kit.models.base import ForecastAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.operations import OperationalStore
from demand_forecast_kit.run_service import RunService


class OperationalWorker:
    """Claim and execute due tenant jobs with retryable leases and idempotent runs."""

    def __init__(
        self,
        service: RunService,
        store: OperationalStore,
        lifecycle: ModelLifecycle | None = None,
        *,
        retraining_stale_after_seconds: int = 3600,
    ) -> None:
        if type(retraining_stale_after_seconds) is not int or retraining_stale_after_seconds < 1:
            raise ValueError("retraining_stale_after_seconds must be a positive integer")
        self.service = service
        self.store = store
        self.lifecycle = lifecycle or ModelLifecycle(store)
        self.retraining_stale_after_seconds = retraining_stale_after_seconds
        fallback = SeasonalNaiveAdapter()
        self.fallback_adapter = fallback
        self.adapters: dict[str, ForecastAdapter] = {fallback.model_id: fallback}

    def register_adapter(self, adapter: ForecastAdapter) -> None:
        """Register an available adapter for automatic SKU-level model routing."""
        self.adapters[adapter.model_id] = adapter

    def register_trainer(self, model_id: str, trainer: Any) -> None:
        """Register the model-specific trainer used for queued automatic retraining."""
        self.lifecycle.register_trainer(model_id, trainer)

    def run_once(self, tenant_id: str, *, limit: int = 20) -> dict[str, Any]:
        recovered_retraining = self.store.recover_stale_retraining(
            tenant_id, stale_after_seconds=self.retraining_stale_after_seconds
        )
        jobs = self.store.claim_due_schedules(tenant_id, limit=limit)
        completed: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        retrained: list[dict[str, Any]] = []
        for job in jobs:
            try:
                result = self._execute(tenant_id, job)
                self.store.complete_schedule(tenant_id, str(job["job_id"]))
                completed.append(
                    {"job_id": job["job_id"], "job_type": job["job_type"], "result": result}
                )
            except Exception as exc:
                self.store.release_schedule(tenant_id, str(job["job_id"]))
                failed.append(
                    {
                        "job_id": str(job["job_id"]),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        for request in self.store.list_retraining_requests(tenant_id, limit=1000):
            if request["status"] != "queued" or request["model_id"] not in self.lifecycle.trainers:
                continue
            try:
                retrained.append(
                    self.lifecycle.process_retraining_request(tenant_id, str(request["request_id"]))
                )
            except Exception as exc:
                failed.append(
                    {
                        "job_id": str(request["request_id"]),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "claimed": len(jobs),
            "recovered_retraining": recovered_retraining,
            "completed": completed,
            "failed": failed,
            "retraining": retrained,
        }

    def _execute(self, tenant_id: str, job: dict[str, Any]) -> dict[str, Any]:
        payload = job["payload"]
        job_type = job["job_type"]
        if job_type == "forecast_refresh":
            return self._forecast(tenant_id, payload)
        if job_type == "replenishment_review":
            return self._replenishment(tenant_id, payload, job)
        if job_type == "model_health":
            return self._model_health(tenant_id, payload)
        if job_type == "policy_review":
            return self._policy_review(tenant_id, payload)
        raise ValueError(f"unsupported job type: {job_type}")

    def _forecast(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        warehouse_id = str(payload["warehouse_id"])
        sku_id = str(payload["sku_id"])
        horizon = int(payload.get("horizon", 14))
        season_length = int(payload.get("season_length", 7))
        quantiles = tuple(float(item) for item in payload.get("quantiles", [0.1, 0.5, 0.9]))
        rows = self.store.demand_history(tenant_id, warehouse_id, sku_id, limit=100_000)
        history = [float(row["demand"]) for row in rows]
        if not history:
            raise ValueError("forecast refresh requires demand history")
        fallback = SeasonalNaiveAdapter(season_length=season_length)
        selection = self.lifecycle.select(
            tenant_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            min_samples=int(payload.get("model_min_samples", 5)),
            window=int(payload.get("model_window", 100)),
            fallback_model_id=fallback.model_id,
        )
        selected = selection["selected"]
        adapter = (
            None
            if selection["used_fallback"] or selected["model_id"] == fallback.model_id
            else self.adapters.get(str(selected["model_id"]))
        )
        if adapter is None or (
            selected["model_version"] is not None
            and adapter.model_version != selected["model_version"]
        ):
            adapter = fallback
            if not selection["used_fallback"]:
                selection["adapter_fallback_reason"] = (
                    "selected_adapter_not_registered_or_version_mismatch"
                )
        forecast = adapter.predict(
            f"{warehouse_id}:{sku_id}",
            history,
            horizon=horizon,
            quantile_levels=quantiles,
            seed=0,
        )
        result = {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "forecast_origin": rows[-1]["observed_at"],
            "model_id": adapter.model_id,
            "model_version": adapter.model_version,
            "model_selection": selection,
            "horizon": forecast.horizon,
            "quantiles": {str(level): list(values) for level, values in forecast.quantiles.items()},
        }
        config = {
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "horizon": horizon,
            "season_length": season_length,
            "quantiles": list(quantiles),
            "tenant_id": tenant_id,
            "model_id": adapter.model_id,
            "model_version": adapter.model_version,
            "model_selection": selection,
        }
        dataset = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        fingerprint = hashlib.sha256(dataset).hexdigest()
        payload_bytes = json.dumps(
            result, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        run = self.service.record_run(
            idempotency_key=self.service.idempotency_key(
                dataset_fingerprint=fingerprint,
                model_id=adapter.model_id,
                model_version=adapter.model_version,
                config=config,
            ),
            dataset_fingerprint=fingerprint,
            model_id=adapter.model_id,
            model_version=adapter.model_version,
            config=config,
            result=result,
            artifact_payload=payload_bytes,
        )
        return {"run": run.to_dict(), "forecast": result}

    def _replenishment(
        self, tenant_id: str, payload: dict[str, Any], job: dict[str, Any]
    ) -> dict[str, Any]:
        warehouse_id = str(payload["warehouse_id"])
        sku_id = str(payload["sku_id"])
        position = self.store.inventory_position(tenant_id, warehouse_id, sku_id)
        recommendation = newsvendor_order(
            {
                float(level): float(value)
                for level, value in payload["lead_time_demand_quantiles"].items()
            },
            underage_cost=float(payload["underage_cost"]),
            overage_cost=float(payload["overage_cost"]),
            inventory_position=float(position["inventory_position"]),
            pack_size=int(payload.get("pack_size", 1)),
        )
        decision = {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "inventory_position": position["inventory_position"],
            "quantity": recommendation.quantity,
            "target_stock_level": recommendation.target_stock_level,
            "target_service_level": recommendation.target_service_level,
            "policy": "newsvendor",
        }
        config = {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "lead_time_demand_quantiles": payload["lead_time_demand_quantiles"],
            "underage_cost": payload["underage_cost"],
            "overage_cost": payload["overage_cost"],
            "pack_size": payload.get("pack_size", 1),
            "inventory_position": position["inventory_position"],
        }
        encoded = json.dumps(
            config, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        result_bytes = json.dumps(
            decision, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        run = self.service.record_run(
            idempotency_key=self.service.idempotency_key(
                dataset_fingerprint=fingerprint,
                model_id="newsvendor-policy",
                model_version="1",
                config=config,
            ),
            dataset_fingerprint=fingerprint,
            model_id="newsvendor-policy",
            model_version="1",
            config=config,
            result=decision,
            artifact_payload=result_bytes,
        )
        stored = self.service.record_inventory_decision(
            run.run_id,
            decision_key=str(job["job_id"]),
            decision=decision,
        )
        return {"run": run.to_dict(), "decision": stored}

    def _policy_review(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        candidates = self.store.rank_policies(
            tenant_id,
            warehouse_id=str(payload["warehouse_id"]),
            sku_id=str(payload["sku_id"]),
            min_samples=int(payload.get("min_samples", 5)),
            window=int(payload.get("window", 100)),
        )
        if candidates:
            return {"selected": candidates[0], "candidates": candidates, "used_fallback": False}
        return {
            "selected": {
                "policy_id": str(payload.get("fallback_policy_id", "newsvendor-default")),
                "mean_cost": None,
                "sample_count": 0,
            },
            "candidates": [],
            "used_fallback": True,
            "reason": "insufficient_realized_outcome_evidence",
        }

    def _model_health(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        health = self.store.model_health(
            tenant_id,
            warehouse_id=str(payload["warehouse_id"]),
            sku_id=str(payload["sku_id"]),
            model_id=str(payload["model_id"]),
            model_version=str(payload["model_version"]),
            window=int(payload.get("window", 30)),
            min_samples=int(payload.get("min_samples", 10)),
            degradation_ratio=float(payload.get("degradation_ratio", 1.5)),
        )
        if health["alert"]:
            health["retraining_request"] = self.store.queue_retraining(
                tenant_id,
                warehouse_id=str(payload["warehouse_id"]),
                sku_id=str(payload["sku_id"]),
                model_id=str(payload["model_id"]),
                model_version=str(payload["model_version"]),
                reason="rolling_mae_degradation",
            )
        return health


def main() -> None:
    parser = argparse.ArgumentParser(description="Run due demand-forecast-kit operational jobs.")
    parser.add_argument("--tenant-id", default=os.environ.get("DEMAND_FORECAST_TENANT_ID", "local"))
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.poll_seconds < 1 or not args.tenant_id.strip():
        parser.error("--poll-seconds must be positive and --tenant-id must not be blank")
    service = RunService.from_environment()
    store = OperationalStore(service.state_dir / "operations.sqlite")
    worker = OperationalWorker(service, store)
    while True:
        report = worker.run_once(args.tenant_id)
        if report["claimed"]:
            print(json.dumps(report, sort_keys=True, allow_nan=False))
        if args.once:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
