"""Single-machine worker for durable forecast, replenishment, and monitoring schedules."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import threading
from types import FrameType
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from demand_forecast_kit.decisions import newsvendor_order
from demand_forecast_kit.lifecycle import ModelLifecycle
from demand_forecast_kit.model_registry import ModelArtifactRecord, ModelArtifactRegistry
from demand_forecast_kit.models.base import ForecastAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.operations import OperationalStore
from demand_forecast_kit.policy_registry import (
    ReplenishmentPolicyRecord,
    ReplenishmentPolicyRegistry,
)
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
        model_artifact_registry: ModelArtifactRegistry | None = None,
        policy_registry: ReplenishmentPolicyRegistry | None = None,
    ) -> None:
        if type(retraining_stale_after_seconds) is not int or retraining_stale_after_seconds < 1:
            raise ValueError("retraining_stale_after_seconds must be a positive integer")
        self.service = service
        self.store = store
        self.hostname = socket.gethostname()
        self.worker_id = f"{self.hostname}:{os.getpid()}"
        self.started_at = datetime.now(UTC)
        self.lifecycle = lifecycle or ModelLifecycle(store)
        self.retraining_stale_after_seconds = retraining_stale_after_seconds
        self.model_artifact_registry = model_artifact_registry
        self.policy_registry = policy_registry
        self.artifact_loaders: dict[
            str, Callable[[bytes, ModelArtifactRecord], ForecastAdapter]
        ] = {}
        self._artifact_adapter_cache: dict[tuple[str, str, str], ForecastAdapter] = {}
        fallback = SeasonalNaiveAdapter()
        self.fallback_adapter = fallback
        self.adapters: dict[tuple[str, str], ForecastAdapter] = {
            (fallback.model_id, fallback.model_version): fallback
        }

    def heartbeat(self, tenant_id: str) -> dict[str, Any]:
        """Refresh this process's tenant-scoped liveness record."""
        return self.store.heartbeat_worker(
            tenant_id,
            self.worker_id,
            self.hostname,
            os.getpid(),
            self.started_at,
        )

    def stop(self, tenant_id: str) -> bool:
        """Mark this worker stopped after a graceful shutdown."""
        return self.store.stop_worker(tenant_id, self.worker_id)

    def register_adapter(self, adapter: ForecastAdapter) -> None:
        """Register an available adapter for automatic SKU-level model routing."""
        self.adapters[(adapter.model_id, adapter.model_version)] = adapter

    def register_artifact_loader(
        self,
        media_type: str,
        loader: Callable[[bytes, ModelArtifactRecord], ForecastAdapter],
    ) -> None:
        """Register reviewed application code for one opaque artifact media type."""
        content_type = media_type.strip()
        if not content_type:
            raise ValueError("media_type must not be blank")
        if not callable(loader):
            raise TypeError("loader must be callable")
        self.artifact_loaders[content_type] = loader
        self._artifact_adapter_cache.clear()

    def _resolve_selected_adapter(
        self, selected: dict[str, Any], fallback: ForecastAdapter
    ) -> ForecastAdapter:
        model_id = str(selected["model_id"])
        model_version = selected["model_version"]
        if model_id == fallback.model_id:
            return fallback
        if self.model_artifact_registry is None:
            adapter = self.adapters.get((model_id, str(model_version)))
            if adapter is None or (
                model_version is not None and adapter.model_version != model_version
            ):
                raise LookupError("selected_adapter_not_registered_or_version_mismatch")
            return adapter

        active = self.model_artifact_registry.get_active(model_id)
        if active is None:
            raise LookupError("no_active_model_artifact")
        if model_version is None or active.model_version != str(model_version):
            raise LookupError("selected_model_version_is_not_active")
        loader = self.artifact_loaders.get(active.media_type)
        if loader is None:
            raise LookupError("no_loader_registered_for_active_artifact_media_type")
        cache_key = (active.model_id, active.model_version, active.artifact_sha256)
        adapter = self._artifact_adapter_cache.get(cache_key)
        if adapter is None:
            payload = self.model_artifact_registry.read_artifact(
                active.model_id, active.model_version
            )
            adapter = loader(payload, active)
            if adapter.model_id != active.model_id or adapter.model_version != active.model_version:
                raise ValueError("artifact loader returned an adapter with mismatched identity")
            self._artifact_adapter_cache[cache_key] = adapter
        return adapter

    def register_trainer(self, model_id: str, trainer: Any) -> None:
        """Register the model-specific trainer used for queued automatic retraining."""
        self.lifecycle.register_trainer(model_id, trainer)

    def run_once(self, tenant_id: str, *, limit: int = 20) -> dict[str, Any]:
        self.heartbeat(tenant_id)
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
                self.store.complete_schedule(
                    tenant_id, str(job["job_id"]), lease_token=str(job["lease_token"])
                )
                completed.append(
                    {"job_id": job["job_id"], "job_type": job["job_type"], "result": result}
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                try:
                    self.store.release_schedule(
                        tenant_id, str(job["job_id"]), lease_token=str(job["lease_token"])
                    )
                except Exception as release_exc:
                    error += f"; lease release failed: {type(release_exc).__name__}: {release_exc}"
                failed.append({"job_id": str(job["job_id"]), "error": error})
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
        adapter = fallback
        if not selection["used_fallback"] and selected["model_id"] != fallback.model_id:
            try:
                adapter = self._resolve_selected_adapter(selected, fallback)
                selection["adapter_fallback"] = False
                if self.model_artifact_registry is not None:
                    active = self.model_artifact_registry.get_active(str(selected["model_id"]))
                    if active is not None:
                        selection["active_artifact_version"] = active.model_version
                        selection["active_artifact_sha256"] = active.artifact_sha256
            except Exception as exc:
                selection["adapter_fallback"] = True
                selection["adapter_fallback_reason"] = (
                    str(exc)
                    if isinstance(exc, LookupError)
                    else f"active_model_artifact_load_failed:{type(exc).__name__}"
                )
                adapter = fallback
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
        active_policy: ReplenishmentPolicyRecord | None = None
        policy_id = str(payload.get("policy_id", "newsvendor-default"))
        if self.policy_registry is not None:
            active_policy = self.policy_registry.get_active(tenant_id, policy_id)
            if active_policy is None:
                raise ValueError(f"no active replenishment policy for {policy_id!r}")
            definition = active_policy.definition
            underage_cost = float(definition["underage_cost"])
            overage_cost = float(definition["overage_cost"])
            pack_size = int(definition["pack_size"])
        else:
            underage_cost = float(payload["underage_cost"])
            overage_cost = float(payload["overage_cost"])
            pack_size = int(payload.get("pack_size", 1))
        recommendation = newsvendor_order(
            {
                float(level): float(value)
                for level, value in payload["lead_time_demand_quantiles"].items()
            },
            underage_cost=underage_cost,
            overage_cost=overage_cost,
            inventory_position=float(position["inventory_position"]),
            pack_size=pack_size,
        )
        decision = {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "inventory_position": position["inventory_position"],
            "quantity": recommendation.quantity,
            "target_stock_level": recommendation.target_stock_level,
            "target_service_level": recommendation.target_service_level,
            "policy": active_policy.policy_id if active_policy is not None else "newsvendor",
        }
        if active_policy is not None:
            decision["policy_version"] = active_policy.policy_version
            decision["policy_definition_sha256"] = active_policy.definition_sha256
        config = {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "lead_time_demand_quantiles": payload["lead_time_demand_quantiles"],
            "underage_cost": underage_cost,
            "overage_cost": overage_cost,
            "pack_size": pack_size,
            "inventory_position": position["inventory_position"],
        }
        if active_policy is not None:
            config["policy_id"] = active_policy.policy_id
            config["policy_version"] = active_policy.policy_version
            config["policy_definition_sha256"] = active_policy.definition_sha256
        model_id = (
            f"replenishment-policy:{policy_id}"
            if active_policy is not None
            else "newsvendor-policy"
        )
        model_version = active_policy.policy_version if active_policy is not None else "1"
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
                model_id=model_id,
                model_version=model_version,
                config=config,
            ),
            dataset_fingerprint=fingerprint,
            model_id=model_id,
            model_version=model_version,
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
    stop_event = threading.Event()

    def request_shutdown(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    def maintain_heartbeat() -> None:
        interval = min(args.poll_seconds, 30)
        while not stop_event.wait(interval):
            worker.heartbeat(args.tenant_id)

    worker.heartbeat(args.tenant_id)
    heartbeat_thread = threading.Thread(
        target=maintain_heartbeat,
        name="demand-forecast-worker-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        while not stop_event.is_set():
            report = worker.run_once(args.tenant_id)
            if report["claimed"] or report["failed"] or report["retraining"]:
                print(json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
            if args.once:
                break
            if stop_event.wait(args.poll_seconds):
                break
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=5)
        worker.stop(args.tenant_id)


if __name__ == "__main__":
    main()
